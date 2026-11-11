"""Task specifications: declarative, versioned, deterministic.

A task is a JSON (or YAML-subset) document with a goal, a starting state,
allowed actions, a reference plan for the bundled scripted agent, and
state-based success conditions. The evaluator scores only final state —
never an LLM judge — so any agent strategy is fairly comparable.

Schema (all fields except the noted optional ones are required):
    id            str   unique within a task pack, e.g. "shop-add-to-cart"
    version       str   semver; never silently change a published task
    site          str   one of "shop" | "crm" | "sched" | "support"
    title         str   human-readable name
    goal          str   natural-language goal shown to the agent
    seed          int   reset seed; the starting state is deterministic
    max_steps     int   step budget; exceeding it ends the run as failed
    start_url     str   where the run begins (relative to the test server)
    allowed_actions  [str]  action types the agent may use
    allowed_prefixes [str]  URL prefixes the agent may navigate to
    params        dict  task inputs (product names, form values, ...)
    reference_plan [dict]   abstract steps the bundled scripted agent
                            follows; external agents must derive their
                            own plan from `goal` + `params`
    success       [dict]  state conditions; see evaluator.CONDITIONS
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from . import yamlmini

SITES = ("shop", "crm", "sched", "support")
ACTION_TYPES = ("navigate", "click", "fill", "submit", "done")


class TaskSpecError(ValueError):
    pass


@dataclass
class TaskSpec:
    id: str
    version: str
    site: str
    title: str
    goal: str
    seed: int
    max_steps: int
    start_url: str
    allowed_actions: list
    allowed_prefixes: list
    params: dict = field(default_factory=dict)
    reference_plan: list = field(default_factory=list)
    success: list = field(default_factory=list)

    def validate(self) -> None:
        if not self.id or not isinstance(self.id, str):
            raise TaskSpecError("task id must be a non-empty string")
        if self.site not in SITES:
            raise TaskSpecError(f"task {self.id}: unknown site {self.site!r}")
        if not isinstance(self.seed, int):
            raise TaskSpecError(f"task {self.id}: seed must be an int")
        if not isinstance(self.max_steps, int) or self.max_steps < 1:
            raise TaskSpecError(f"task {self.id}: max_steps must be >= 1")
        for action in self.allowed_actions:
            if action not in ACTION_TYPES:
                raise TaskSpecError(f"task {self.id}: unknown action {action!r}")
        if not self.success:
            raise TaskSpecError(f"task {self.id}: at least one success condition is required")
        for cond in self.success:
            if not isinstance(cond, dict) or "type" not in cond:
                raise TaskSpecError(f"task {self.id}: malformed success condition {cond!r}")

    @classmethod
    def from_dict(cls, data: dict) -> "TaskSpec":
        required = (
            "id", "version", "site", "title", "goal", "seed", "max_steps",
            "start_url", "allowed_actions", "allowed_prefixes", "success",
        )
        missing = [k for k in required if k not in data]
        if missing:
            raise TaskSpecError(f"task spec missing fields: {missing}")
        spec = cls(
            id=data["id"],
            version=str(data["version"]),
            site=data["site"],
            title=data["title"],
            goal=data["goal"],
            seed=int(data["seed"]),
            max_steps=int(data["max_steps"]),
            start_url=data["start_url"],
            allowed_actions=list(data["allowed_actions"]),
            allowed_prefixes=list(data["allowed_prefixes"]),
            params=dict(data.get("params", {})),
            reference_plan=list(data.get("reference_plan", [])),
            success=list(data["success"]),
        )
        spec.validate()
        return spec

    @classmethod
    def from_file(cls, path: str) -> "TaskSpec":
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
        if path.endswith(".json"):
            data = json.loads(raw)
        elif path.endswith((".yaml", ".yml")):
            data = yamlmini.parse(raw)
        else:
            raise TaskSpecError(f"unsupported task file: {path}")
        if not isinstance(data, dict):
            raise TaskSpecError(f"task file {path} must contain a mapping")
        return cls.from_dict(data)


def load_tasks(directory: str) -> list[TaskSpec]:
    """Load every task file under `directory` (recursive), sorted by id."""
    specs: list[TaskSpec] = []
    for root, _dirs, files in os.walk(directory):
        for name in sorted(files):
            if name.endswith((".json", ".yaml", ".yml")):
                specs.append(TaskSpec.from_file(os.path.join(root, name)))
    specs.sort(key=lambda s: s.id)
    seen: set[str] = set()
    for spec in specs:
        if spec.id in seen:
            raise TaskSpecError(f"duplicate task id: {spec.id}")
        seen.add(spec.id)
    return specs
