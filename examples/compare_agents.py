"""Run two agents on the same tasks and print a side-by-side comparison.

Both agents get the identical task list, identical starting state (each
task is reset to its seeded state before every run) and the same step
budget, so the numbers are directly comparable. Compared per agent:
success rate, mean partial completion, total steps, total duration and
unsafe attempts blocked by the harness — plus a per-task PASS/FAIL grid.

Usage (from the repo root):

    python3 examples/compare_agents.py
    python3 examples/compare_agents.py --agents scripted random
    python3 examples/compare_agents.py --out-dir runs/my-comparison

With the bundled agents the expected outcome is stark: the reference
scripted agent passes every task and the random baseline passes none or near none. That
gap is the point — it shows the tasks are solvable and the baseline is
a real floor, not a straw man. Artifacts for each agent are written
under the output directory (one sub-directory per agent).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Allow running from the repo root without installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from browserbench.adapter import load_agent
from browserbench.report import render_summary_markdown
from browserbench.runner import run_suite
from browserbench.spec import load_tasks


def _fmt(summary: dict) -> dict[str, str]:
    return {
        "agent": summary["agent"],
        "passed": f"{summary['tasks_passed']}/{summary['tasks_run']}",
        "success_rate": f"{summary['success_rate']:.0%}",
        "mean_partial": f"{summary['mean_partial']:.2f}",
        "steps": str(summary["total_steps"]),
        "duration_s": f"{summary['total_duration_s']:.1f}",
        "unsafe": str(summary["total_unsafe_attempts"]),
    }


def _print_comparison(summaries: list[dict]) -> None:
    rows = [_fmt(s) for s in summaries]
    headers = ["agent", "passed", "success_rate", "mean_partial",
               "steps", "duration_s", "unsafe"]
    widths = {h: max(len(h), max(len(r[h]) for r in rows)) for h in headers}
    header_line = "  ".join(h.ljust(widths[h]) for h in headers)
    print("Side-by-side comparison (identical tasks, identical start state)")
    print(header_line)
    print("-" * len(header_line))
    for row in rows:
        print("  ".join(row[h].ljust(widths[h]) for h in headers))
    print()
    print("Unsafe = action attempts blocked by the harness (disallowed "
          "action type or URL outside the task's allowed prefixes). "
          "Blocked attempts never execute; they are counted, not hidden.")

    # Per-task PASS/FAIL grid.
    task_ids = [r["task_id"] for r in summaries[0]["results"]]
    print("\nPer task (P = pass, . = fail):")
    col = max(len(t) for t in task_ids)
    print(f"  {'task'.ljust(col)}  " + "  ".join(
        s["agent"][:12].ljust(12) for s in summaries))
    by_task = {
        s["agent"]: {r["task_id"]: r["evaluation"]["success"]
                     for r in s["results"]}
        for s in summaries
    }
    for task_id in task_ids:
        cells = ["P           " if by_task[s["agent"]][task_id]
                 else ".           " for s in summaries]
        print(f"  {task_id.ljust(col)}  " + "  ".join(cells))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare two or more agents on the same BrowserBench tasks.")
    parser.add_argument(
        "--agents", nargs="+", default=["scripted", "random"],
        help="agent specs to compare (default: scripted random)")
    parser.add_argument(
        "--tasks-dir", default=None,
        help="directory of task files (default: <repo root>/tasks)")
    parser.add_argument(
        "--out-dir", default=None,
        help="output directory for run artifacts "
             "(default: runs/example-compare)")
    args = parser.parse_args(argv)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tasks_dir = args.tasks_dir or os.path.join(root, "tasks")
    out_base = args.out_dir or os.path.join(root, "runs", "example-compare")

    tasks = load_tasks(tasks_dir)
    print(f"BrowserBench — comparing {len(args.agents)} agent(s) "
          f"on {len(tasks)} tasks\n")

    summaries = []
    for agent_spec in args.agents:
        agent = load_agent(agent_spec)
        out_dir = os.path.join(out_base, agent.name)
        summary = run_suite(tasks, agent, out_dir,
                            config={"agent_spec": agent_spec,
                                    "example": "compare_agents"})
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2)
        with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as fh:
            fh.write(render_summary_markdown(summary))
        summaries.append(summary)
        print(f"  {agent.name}: {summary['tasks_passed']}/{summary['tasks_run']} "
              f"passed, {summary['total_steps']} steps, "
              f"{summary['total_unsafe_attempts']} unsafe blocked")

    print()
    _print_comparison(summaries)
    print(f"\nartifacts: {os.path.abspath(out_base)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
