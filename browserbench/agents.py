"""Bundled reference agents.

ScriptedAgent — a deterministic planner that follows the task's
``reference_plan`` (a list of abstract steps). It exists so the harness
can be demonstrated end to end and so task authors can verify a task is
solvable. It is NOT a general browser agent: it reads the plan, not the
goal. External agents must derive their own plan from ``goal`` + ``params``.

RandomAgent — picks a random allowed action each step. The baseline every
real agent should beat; the demo compares the two on identical tasks.
"""

from __future__ import annotations

import random

from .adapter import BaseAgent


def _norm(text: str) -> str:
    return " ".join(str(text).lower().split())


class ScriptedAgent(BaseAgent):
    """Executes a task's reference_plan step by step."""

    name = "scripted-agent"
    version = "0.1.0"

    def __init__(self):
        self._plan: list = []
        self._step = 0

    def reset(self, task) -> None:
        self._plan = list(task.reference_plan or [])
        self._step = 0

    def _find_link(self, observation, fragment: str):
        needle = _norm(fragment)
        for link in observation.get("links", []):
            if needle in _norm(link.get("text", "")):
                return link["href"]
        return None

    def _find_form(self, observation, submit_label: str | None = None,
                   fields: set | None = None):
        for index, form in enumerate(observation.get("forms", [])):
            names = {f["name"] for f in form.get("fields", [])}
            if submit_label and _norm(submit_label) not in _norm(form.get("submit", "")):
                continue
            if fields and not fields.issubset(names):
                continue
            return index, form
        return None, None

    def act(self, observation: dict) -> dict:
        if self._step >= len(self._plan):
            return {"type": "done"}
        step = self._plan[self._step]
        kind = step.get("action")
        if kind == "navigate":
            self._step += 1
            return {"type": "navigate", "url": step["url"]}
        if kind == "link":
            href = self._find_link(observation, step["text"])
            if href is None:
                return {"type": "done"}  # plan cannot proceed; evaluator scores state
            self._step += 1
            return {"type": "click", "href": href}
        if kind == "fill":
            values = step.get("values", {})
            index, _form = self._find_form(observation, fields=set(values))
            if index is None:
                return {"type": "done"}
            self._step += 1
            return {"type": "fill", "form": index, "values": values}
        if kind == "submit":
            index, _form = self._find_form(
                observation, submit_label=step.get("button"))
            if index is None:
                return {"type": "done"}
            self._step += 1
            return {"type": "submit", "form": index}
        if kind == "expect":
            self._step += 1
            if _norm(step.get("text", "")) in _norm(observation.get("text", "")):
                return {"type": "done"}
            return {"type": "done"}
        return {"type": "done"}


class RandomAgent(BaseAgent):
    """Uniformly random allowed actions. The baseline to beat."""

    name = "random-agent"
    version = "0.1.0"

    def __init__(self, seed: int = 0):
        self._rng = random.Random(seed)

    def reset(self, task) -> None:
        self._rng = random.Random(hash(task.id) & 0xFFFF)

    def act(self, observation: dict) -> dict:
        links = observation.get("links", [])
        forms = observation.get("forms", [])
        choices = ["done"]
        if links:
            choices.append("click")
        if forms:
            choices += ["fill", "submit"]
        pick = self._rng.choice(choices)
        if pick == "click":
            link = self._rng.choice(links)
            return {"type": "click", "href": link["href"]}
        if pick == "fill":
            index = self._rng.randrange(len(forms))
            form = forms[index]
            values = {}
            for field in form.get("fields", []):
                if field["type"] == "hidden":
                    continue
                if field["type"] == "select" and field.get("options"):
                    values[field["name"]] = self._rng.choice(field["options"])
                else:
                    values[field["name"]] = self._rng.choice(
                        ["test", "hello", "42", "x@y.z"])
            return {"type": "fill", "form": index, "values": values}
        if pick == "submit":
            return {"type": "submit", "form": self._rng.randrange(len(forms))}
        return {"type": "done"}
