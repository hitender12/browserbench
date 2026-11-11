"""Failure replay: re-run a saved artifact and compare the outcome.

Replay loads ``artifact.json`` from a run directory, resets the site with
the recorded seed, re-executes the recorded action sequence through the
same executor, re-evaluates the final state, and reports whether the
replayed result matches the original. Because the test sites are
deterministic given (seed, action sequence), a replay must reproduce the
original result exactly; a mismatch means the task or the site changed
and is reported loudly rather than silently.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.parse
import urllib.request

from . import evaluator
from .dom import parse_html
from .runner import HttpClient, _is_allowed_url, _resolve
from .sites import make_server
from .spec import TaskSpec
from .trace import FORMAT_VERSION, TraceRecorder, load_artifact


class _ReplayAgent:
    """An agent that simply replays a recorded action list."""

    name = "replay-agent"
    version = "0.1.0"

    def __init__(self, actions):
        self._actions = list(actions)
        self._index = 0

    def reset(self, task):
        self._index = 0

    def act(self, observation):
        if self._index >= len(self._actions):
            return {"type": "done"}
        action = self._actions[self._index]
        self._index += 1
        return action


def replay_run(run_dir: str, tasks_dir: str) -> dict:
    """Replay the artifact in ``run_dir``; return a comparison report."""
    artifact = load_artifact(os.path.join(run_dir, "artifact.json"))
    task = next(
        (t for t in _load_all(tasks_dir) if t.id == artifact["task_id"]), None)
    if task is None:
        raise ValueError(f"task {artifact['task_id']!r} not found in {tasks_dir}")
    if task.version != artifact["task_version"]:
        raise ValueError(
            f"task version drift: artifact was recorded against "
            f"{artifact['task_version']}, current task is {task.version}. "
            "Replays must use the same task version.")

    server = make_server()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base_url = (f"http://{server.server_address[0]}:"
                f"{server.server_address[1]}")
    try:
        recorder = TraceRecorder()
        client = HttpClient(recorder)
        status, _u, _b = client.post_form(
            f"{base_url}/__reset__",
            {"site": task.site, "seed": str(artifact["seed"])})
        if status != 200:
            raise RuntimeError("site reset failed during replay")

        agent = _ReplayAgent(artifact["actions"])
        agent.reset(task)
        current_url = _resolve(base_url, task.start_url)
        status, current_url, body = client.get(current_url)
        observation = parse_html(body, current_url)
        observation.update({"step": 0, "task_id": task.id, "goal": task.goal})
        for step_no, action in enumerate(artifact["actions"], start=1):
            observation["step"] = step_no
            if action.get("type") == "done":
                break
            new_url = _execute_action(task, client, base_url, observation, action)
            if new_url:
                current_url = new_url
            # refresh observation for the next action
            status, current_url, body = client.get(current_url)
            observation = parse_html(body, current_url)
            observation.update({"step": step_no, "task_id": task.id, "goal": task.goal})
        _status, _url, body = client.get(
            f"{base_url}/__state__?site={task.site}")
        evaluation = evaluator.evaluate(task, json.loads(body))
    finally:
        server.shutdown()
        server.server_close()

    original = artifact["evaluation"]
    match = (evaluation["success"] == original["success"]
             and evaluation["passed"] == original["passed"])
    return {
        "task_id": task.id,
        "task_version": task.version,
        "format_version": FORMAT_VERSION,
        "replayed_success": evaluation["success"],
        "original_success": original["success"],
        "replayed_passed": evaluation["passed"],
        "original_passed": original["passed"],
        "match": match,
        "evaluation": evaluation,
    }


def _execute_action(task, client, base_url, observation, action):
    """Execute one recorded action (same rules as the runner)."""
    atype = action.get("type")
    if atype == "navigate":
        url = _resolve(base_url, action.get("url", ""))
        if _is_allowed_url(task, base_url, url):
            return
        _s, url, _b = client.get(url)
        return url
    if atype == "click":
        url = _resolve(base_url, action.get("href", ""))
        if _is_allowed_url(task, base_url, url):
            return
        _s, url, _b = client.get(url)
        return url
    if atype == "fill":
        client.form_values[action.get("form", 0)] = dict(action.get("values", {}))
        return None
    if atype == "submit":
        forms = observation.get("forms", [])
        index = action.get("form", 0)
        if index >= len(forms):
            return None
        form = forms[index]
        url = _resolve(base_url, form.get("action") or observation["url"])
        values = {f["name"]: f.get("value", "") for f in form.get("fields", [])
                  if f.get("name")}
        values.update(client.form_values.pop(index, {}))
        if form.get("method", "get") == "post":
            _s, url, _b = client.post_form(url, values)
        else:
            _s, url, _b = client.get(f"{url}?{urllib.parse.urlencode(values)}")
        return url
    return None


def _load_all(tasks_dir: str):
    from .spec import load_tasks
    return load_tasks(tasks_dir)
