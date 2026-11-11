"""The runner: reset site, drive the agent, validate actions, score state.

One run per task:
1. POST /__reset__ (seeded, deterministic starting state).
2. GET the start URL; loop: observation -> agent.act() -> validate ->
   execute (GET/POST) -> next observation, until the agent says done or
   the step budget is exhausted.
3. GET /__state__ and evaluate deterministically.
4. Save trace + result + replayable artifact.

Action validation (safety boundary):
- action type must be in task.allowed_actions
- navigate/click targets must start with one of task.allowed_prefixes
  (relative URLs are resolved against the server base)
- /__state__ and /__reset__ are never navigable by an agent
Blocked attempts are counted in metrics.unsafe_attempts, recorded in the
trace, and do not end the run — the agent gets the current observation
again and may continue.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__, evaluator, trace as trace_mod
from .dom import parse_html
from .sites import make_server

FORBIDDEN_PREFIXES = ("/__state__", "/__reset__")


class HttpClient:
    """Minimal HTTP client that records network events."""

    def __init__(self, recorder: trace_mod.TraceRecorder):
        self.recorder = recorder
        self.form_values: dict[int, dict] = {}  # form index -> filled values

    def request(self, method: str, url: str, data: bytes | None = None,
                record: bool = True):
        started = time.monotonic()
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                status = resp.status
                final_url = resp.geturl()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            status = exc.code
            final_url = url
        latency_ms = (time.monotonic() - started) * 1000
        if record:
            self.recorder.record_network(method, url, status, latency_ms)
        return status, final_url, body

    def get(self, url: str, record: bool = True):
        return self.request("GET", url, record=record)

    def post_form(self, url: str, values: dict):
        data = urllib.parse.urlencode(values).encode("utf-8")
        return self.request("POST", url, data=data)


def _resolve(base: str, target: str) -> str:
    return urllib.parse.urljoin(base + "/", target.lstrip("/")) \
        if not target.startswith("http") else target


def _is_allowed_url(task, base: str, url: str) -> str | None:
    """Return a block reason, or None if the URL is allowed."""
    parsed = urllib.parse.urlparse(url)
    base_parsed = urllib.parse.urlparse(base)
    if parsed.netloc and parsed.netloc != base_parsed.netloc:
        return f"external host blocked: {parsed.netloc}"
    path = parsed.path
    for prefix in FORBIDDEN_PREFIXES:
        if path.startswith(prefix):
            return f"harness endpoint blocked: {prefix}"
    if not any(path.startswith(p) for p in task.allowed_prefixes):
        return f"URL outside allowed prefixes: {path}"
    return None


def run_task(task, agent, base_url: str, out_dir: str, seed: int | None = None,
             config: dict | None = None) -> dict:
    """Run one task and save its artifacts. Returns the result dict."""
    seed = task.seed if seed is None else seed
    config = dict(config or {})
    recorder = trace_mod.TraceRecorder()
    client = HttpClient(recorder)

    # 1. Reset the site to its deterministic starting state.
    status, _url, _body = client.post_form(
        f"{base_url}/__reset__", {"site": task.site, "seed": str(seed)})
    if status != 200:
        raise RuntimeError(f"site reset failed (HTTP {status})")

    agent.reset(task)
    metrics = {"steps": 0, "retries": 0, "unsafe_attempts": 0,
               "blocked_reasons": []}

    def _snapshot() -> dict | None:
        """Current site state for the trace (not a network event)."""
        try:
            _s, _u, body = client.get(
                f"{base_url}/__state__?site={task.site}", record=False)
            return json.loads(body)
        except Exception:
            return None

    def _record(step_no, action, observation, status, latency_ms,
                blocked=None):
        recorder.record_step(step_no, action, observation, status,
                             latency_ms, blocked=blocked,
                             state_snapshot=_snapshot())
    started = time.monotonic()
    current_url = _resolve(base_url, task.start_url)
    status, current_url, body = client.get(current_url)
    observation = parse_html(body, current_url)
    observation.update({"step": 0, "task_id": task.id, "goal": task.goal})
    done = False

    for step_no in range(1, task.max_steps + 1):
        metrics["steps"] = step_no
        observation["step"] = step_no
        try:
            action = agent.act(observation) or {"type": "done"}
        except Exception as exc:  # an agent crash ends the run, scored on state
            metrics["retries"] += 1
            _record(step_no, {"type": "error", "error": str(exc)},
                                 observation, None, 0.0)
            break
        if not isinstance(action, dict) or "type" not in action:
            action = {"type": "done"}
        atype = action["type"]

        if atype == "done":
            _record(step_no, action, observation, status, 0.0)
            done = True
            break
        if atype not in task.allowed_actions:
            metrics["unsafe_attempts"] += 1
            reason = f"action not allowed: {atype}"
            metrics["blocked_reasons"].append(reason)
            _record(step_no, action, observation, status, 0.0,
                                 blocked=reason)
            continue

        # Resolve and validate the target URL.
        target_url = None
        if atype == "navigate":
            target_url = _resolve(base_url, action.get("url", ""))
        elif atype == "click":
            target_url = _resolve(base_url, action.get("href", ""))
        elif atype in ("fill", "submit"):
            forms = observation.get("forms", [])
            index = action.get("form", 0)
            if not isinstance(index, int) or index >= len(forms):
                metrics["retries"] += 1
                _record(step_no, action, observation, status, 0.0)
                continue
            form = forms[index]
            if atype == "fill":
                client.form_values[index] = dict(action.get("values", {}))
                _record(step_no, action, observation, status, 0.0)
                continue
            target_url = _resolve(base_url, form.get("action") or current_url)
            method = form.get("method", "get")
            values = {}
            for field in form.get("fields", []):
                name = field.get("name")
                if not name or field.get("type") == "hidden":
                    values[name] = field.get("value", "")
            values.update(client.form_values.pop(index, {}))
            started_req = time.monotonic()
            if method == "post":
                status, current_url, body = client.post_form(target_url, values)
            else:
                query = urllib.parse.urlencode(values)
                status, current_url, body = client.get(f"{target_url}?{query}")
            observation = parse_html(body, current_url)
            observation.update({"step": step_no, "task_id": task.id, "goal": task.goal})
            _record(step_no, action, observation, status,
                                 (time.monotonic() - started_req) * 1000)
            continue

        if target_url is None:
            metrics["retries"] += 1
            _record(step_no, action, observation, status, 0.0)
            continue
        block_reason = _is_allowed_url(task, base_url, target_url)
        if block_reason:
            metrics["unsafe_attempts"] += 1
            metrics["blocked_reasons"].append(block_reason)
            _record(step_no, action, observation, status, 0.0,
                                 blocked=block_reason)
            continue
        started_req = time.monotonic()
        status, current_url, body = client.get(target_url)
        observation = parse_html(body, current_url)
        observation.update({"step": step_no, "task_id": task.id, "goal": task.goal})
        _record(step_no, action, observation, status,
                             (time.monotonic() - started_req) * 1000)

    metrics["duration_s"] = round(time.monotonic() - started, 3)
    metrics["finished_by_agent"] = done
    cost = getattr(agent, "cost_usd", None)
    if isinstance(cost, (int, float)):
        metrics["cost_usd"] = round(float(cost), 6)

    # 3. Evaluate final state deterministically.
    _status, _url, body = client.get(f"{base_url}/__state__?site={task.site}")
    final_state = json.loads(body)
    evaluation = evaluator.evaluate(task, final_state)

    result = {
        "task_id": task.id,
        "task_version": task.version,
        "agent": getattr(agent, "name", "unknown"),
        "browserbench_version": __version__,
        "evaluation": evaluation,
        "metrics": metrics,
    }
    trace_mod.save_run(out_dir, task, agent, seed, config, recorder,
                       evaluation, metrics)
    return result


def run_suite(tasks, agent, out_dir: str, base_url: str | None = None,
              config: dict | None = None) -> dict:
    """Run a list of tasks against one agent; returns the suite summary."""
    import os
    own_server = base_url is None
    server = None
    if own_server:
        server = make_server()
        import threading
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base_url = (f"http://{server.server_address[0]}:"
                    f"{server.server_address[1]}")
    results = []
    try:
        for task in tasks:
            run_dir = os.path.join(out_dir, task.id)
            results.append(run_task(task, agent, base_url, run_dir,
                                    config=config))
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
    passed = sum(1 for r in results if r["evaluation"]["success"])
    summary = {
        "agent": getattr(agent, "name", "unknown"),
        "browserbench_version": __version__,
        "tasks_run": len(results),
        "tasks_passed": passed,
        "success_rate": passed / len(results) if results else 0.0,
        "mean_partial": (sum(r["evaluation"]["partial"] for r in results)
                         / len(results) if results else 0.0),
        "total_steps": sum(r["metrics"]["steps"] for r in results),
        "total_duration_s": round(
            sum(r["metrics"]["duration_s"] for r in results), 3),
        "total_unsafe_attempts": sum(
            r["metrics"]["unsafe_attempts"] for r in results),
        "total_retries": sum(r["metrics"]["retries"] for r in results),
        "total_cost_usd": (
            round(sum(r["metrics"]["cost_usd"] for r in results
                      if "cost_usd" in r["metrics"]), 6)
            if any("cost_usd" in r["metrics"] for r in results)
            else None),
        "results": results,
    }
    return summary
