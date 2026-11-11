"""Agent adapter contract (protocol version 1).

An agent is anything that implements ``act(observation) -> action``.

Observation (what the agent sees after each step):
    {
      "url": str, "title": str, "text": str,          # current page
      "goal": str,                                    # task goal (natural language)
      "links": [{"text": str, "href": str}],          # clickable links
      "forms": [{"action": str, "method": str,
                 "fields": [{"name": str, "type": str, "value": str,
                             "options": [str]}],      # select options
                 "submit": str}],                    # submit button label
      "step": int, "task_id": str,
    }

Action (what the agent returns):
    {"type": "navigate", "url": str}                  # GET a URL
    {"type": "click", "href": str}                    # follow a link
    {"type": "fill", "form": int, "values": {name: value}}
    {"type": "submit", "form": int}                   # submit a form
    {"type": "done"}                                  # end the run

Cost (optional): an agent may report what a run cost it by setting the
``cost_usd`` attribute (in-process agents) or by including a ``cost_usd``
number in its HTTP response envelope (HTTP agents; the value is
accumulated across calls). The runner records it in the run metrics and
the suite summary; agents that do not supply a cost report none, and
reports show no cost line for them. The bundled agents report no cost.

Adapters:
- Python class: any object with an ``act`` method (in-process).
- Python file: ``--agent ./agents/my-agent.py`` — the module must define
  ``Agent`` (a class) or ``act`` (a function). It is imported by path.
- HTTP: ``--agent http://127.0.0.1:9000`` — the runner POSTs the
  observation as versioned JSON to ``/act`` and expects an action back:
  ``{"protocol": "browserbench-agent/1", "action": {...}}``.

The runner validates every action against the task's allowed actions and
allowed URL prefixes. Anything else is blocked, counted as an unsafe
attempt, and recorded in the trace — the agent never touches the raw
server that way.
"""

from __future__ import annotations

import importlib.util
import json
import urllib.request

PROTOCOL = "browserbench-agent/1"


class AgentError(Exception):
    pass


class BaseAgent:
    """In-process agent base class. Subclass and implement ``act``.

    Optional attributes an agent may set:
    - ``cost_usd`` (float or None): what the run cost the agent, in USD.
      The runner reads it after the run and records it in the metrics.
      Leave it None (the default) to report no cost.
    """

    name = "base-agent"
    version = "0.1.0"
    cost_usd: float | None = None

    def act(self, observation: dict) -> dict:  # pragma: no cover - interface
        raise NotImplementedError

    def reset(self, task) -> None:
        """Called once before a task starts; override to keep per-task state."""


class HttpAgent(BaseAgent):
    """Agent speaking the versioned JSON protocol over local HTTP."""

    def __init__(self, base_url: str, name: str = "http-agent"):
        self.base_url = base_url.rstrip("/")
        self.name = name
        self.cost_usd: float | None = None

    def act(self, observation: dict) -> dict:
        payload = json.dumps(
            {"protocol": PROTOCOL, "observation": observation}
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/act", data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise AgentError(f"HTTP agent unreachable: {exc}") from exc
        if body.get("protocol") != PROTOCOL:
            raise AgentError(
                f"HTTP agent protocol mismatch: {body.get('protocol')!r}")
        if isinstance(body.get("cost_usd"), (int, float)):
            self.cost_usd = (self.cost_usd or 0.0) + float(body["cost_usd"])
        return body.get("action") or {"type": "done"}


def _load_module_from_path(path: str):
    spec = importlib.util.spec_from_file_location("browserbench_user_agent", path)
    if spec is None or spec.loader is None:
        raise AgentError(f"cannot import agent file: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_agent(spec: str):
    """Resolve an ``--agent`` spec into a BaseAgent instance.

    ``scripted`` / ``random`` — the bundled reference agents.
    ``http://...`` — an HTTP agent.
    ``./path/to/agent.py`` — a Python file defining ``Agent`` or ``act``.
    """
    from .agents import RandomAgent, ScriptedAgent

    if spec == "scripted":
        return ScriptedAgent()
    if spec == "random":
        return RandomAgent()
    if spec.startswith("http://") or spec.startswith("https://"):
        return HttpAgent(spec)
    if spec.endswith(".py"):
        module = _load_module_from_path(spec)
        if hasattr(module, "Agent"):
            return module.Agent()
        if hasattr(module, "act"):
            agent = BaseAgent()
            agent.act = module.act  # type: ignore[method-assign]
            agent.name = getattr(module, "AGENT_NAME", "file-agent")
            return agent
        raise AgentError(
            f"agent file {spec} must define `Agent` or `act`")
    raise AgentError(
        f"unknown agent spec {spec!r} "
        "(expected 'scripted', 'random', an http:// URL, or a .py file)")
