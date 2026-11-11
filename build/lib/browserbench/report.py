"""Reports: terminal tables and Markdown summaries of suite runs."""

from __future__ import annotations

import json
import os


def render_summary_markdown(summary: dict) -> str:
    lines = [
        "# BrowserBench run report",
        "",
        f"Agent: **{summary['agent']}**  |  "
        f"BrowserBench {summary['browserbench_version']}",
        "",
        f"- Tasks run: {summary['tasks_run']}",
        f"- Tasks passed: {summary['tasks_passed']} "
        f"({summary['success_rate']:.0%} success rate)",
        f"- Mean partial completion: {summary['mean_partial']:.2f}",
        f"- Total steps: {summary['total_steps']}",
        f"- Total duration: {summary['total_duration_s']}s",
        f"- Total retries (agent errors / invalid actions): "
        f"{summary.get('total_retries', 0)}",
        f"- Total unsafe attempts blocked: {summary['total_unsafe_attempts']}",
    ]
    if summary.get("total_cost_usd") is not None:
        lines.append(f"- Total cost: ${summary['total_cost_usd']:.2f}")
    lines += [
        "",
        "| Task | Result | Partial | Steps | Duration (s) | Unsafe |",
        "|------|--------|---------|-------|--------------|--------|",
    ]
    for result in summary["results"]:
        ev = result["evaluation"]
        metrics = result["metrics"]
        lines.append(
            f"| {result['task_id']} | {'PASS' if ev['success'] else 'FAIL'} | "
            f"{ev['partial']:.2f} | {metrics['steps']} | "
            f"{metrics['duration_s']} | {metrics['unsafe_attempts']} |")
    lines.append("")
    lines.append("Scoring is deterministic and state-based; see "
                 "docs/benchmark-methodology.md for the rules.")
    return "\n".join(lines) + "\n"


def render_terminal(summary: dict) -> str:
    width = 72
    headline = (f"passed {summary['tasks_passed']}/{summary['tasks_run']} "
                f"({summary['success_rate']:.0%})  "
                f"mean partial {summary['mean_partial']:.2f}  "
                f"steps {summary['total_steps']}  "
                f"{summary['total_duration_s']}s  "
                f"unsafe blocked {summary['total_unsafe_attempts']}  "
                f"retries {summary.get('total_retries', 0)}")
    if summary.get("total_cost_usd") is not None:
        headline += f"  cost ${summary['total_cost_usd']:.2f}"
    lines = ["=" * width,
             f"BrowserBench — agent: {summary['agent']}",
             headline,
             "-" * width]
    for result in summary["results"]:
        ev = result["evaluation"]
        metrics = result["metrics"]
        mark = "PASS" if ev["success"] else "FAIL"
        lines.append(f"  [{mark}] {result['task_id']:<28} "
                     f"partial {ev['partial']:.2f}  "
                     f"steps {metrics['steps']:>2}  "
                     f"{metrics['duration_s']:>6}s  "
                     f"unsafe {metrics['unsafe_attempts']}")
    lines.append("=" * width)
    return "\n".join(lines)


def latest_run_dir(runs_dir: str) -> str | None:
    """Most recently modified run directory under `runs_dir` that has a
    ``summary.json``. Directories without one (per-task run dirs, old
    demo runs) are skipped, not treated as the latest run."""
    if not os.path.isdir(runs_dir):
        return None
    candidates = [os.path.join(runs_dir, name) for name in os.listdir(runs_dir)
                  if os.path.isdir(os.path.join(runs_dir, name))
                  and os.path.exists(os.path.join(runs_dir, name,
                                                  "summary.json"))]
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def load_summary(run_dir: str) -> dict | None:
    path = os.path.join(run_dir, "summary.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
