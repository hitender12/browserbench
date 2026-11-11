"""Trace capture and reproducible run artifacts.

Every run writes a directory ``runs/<run-id>/`` containing:
- ``trace.json``  — every step: action, URL, HTTP status, latency,
  wall-clock timestamp (ISO-8601 UTC), a DOM summary (links, form
  names, 500-char text excerpt) and the full site-state snapshot after
  the action, plus network events and any blocked (unsafe) attempts.
  Note: the trace stores a DOM *summary*, not a full DOM snapshot —
  the complete state is what ``state_snapshot`` records.
- ``result.json`` — the evaluation result and aggregate metrics
- ``artifact.json`` — the replayable artifact: task id + version, seed,
  agent name + version, config, and the exact action sequence, so the
  run can be reproduced locally with ``browserbench replay``.

Artifact format version is recorded explicitly; replay refuses artifacts
whose format version it does not understand.
"""

from __future__ import annotations

import copy
import json
import os
import time
from datetime import datetime, timezone

FORMAT_VERSION = "1.0.0"


class TraceRecorder:
    def __init__(self):
        self.steps: list[dict] = []
        self.network: list[dict] = []

    def record_step(self, step_no: int, action: dict, observation: dict,
                    status: int | None, latency_ms: float,
                    blocked: str | None = None,
                    state_snapshot: dict | None = None) -> None:
        self.steps.append({
            "step": step_no,
            "action": action,
            "url": observation.get("url"),
            "title": observation.get("title"),
            "http_status": status,
            "latency_ms": round(latency_ms, 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "blocked": blocked,
            "dom": {
                "links": observation.get("links", []),
                "forms": [
                    {"action": f.get("action"), "method": f.get("method"),
                     "fields": [fld["name"] for fld in f.get("fields", [])],
                     "submit": f.get("submit")}
                    for f in observation.get("forms", [])
                ],
            },
            "text_excerpt": (observation.get("text", "") or "")[:500],
            "state_snapshot": copy.deepcopy(state_snapshot)
            if state_snapshot is not None else None,
        })

    def record_network(self, method: str, url: str, status: int | None,
                       latency_ms: float) -> None:
        self.network.append({
            "method": method, "url": url, "status": status,
            "latency_ms": round(latency_ms, 1),
        })

    def to_dict(self) -> dict:
        return {"steps": self.steps, "network": self.network}


def save_run(out_dir: str, task, agent, seed: int, config: dict,
             trace: TraceRecorder, evaluation: dict, metrics: dict) -> dict:
    """Write trace.json, result.json and artifact.json; return the artifact."""
    os.makedirs(out_dir, exist_ok=True)
    artifact = {
        "format_version": FORMAT_VERSION,
        "task_id": task.id,
        "task_version": task.version,
        "seed": seed,
        "agent": {"name": getattr(agent, "name", "unknown"),
                  "version": getattr(agent, "version", "unknown")},
        "config": config,
        "actions": [s["action"] for s in trace.steps],
        "evaluation": evaluation,
        "metrics": metrics,
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(os.path.join(out_dir, "trace.json"), "w", encoding="utf-8") as fh:
        json.dump(trace.to_dict(), fh, indent=2)
    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as fh:
        json.dump({"task_id": task.id, "evaluation": evaluation,
                   "metrics": metrics}, fh, indent=2)
    with open(os.path.join(out_dir, "artifact.json"), "w", encoding="utf-8") as fh:
        json.dump(artifact, fh, indent=2)
    return artifact


def load_artifact(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        artifact = json.load(fh)
    if artifact.get("format_version") != FORMAT_VERSION:
        raise ValueError(
            f"unsupported artifact format version: "
            f"{artifact.get('format_version')!r} (want {FORMAT_VERSION!r})")
    return artifact
