"""Run the full BrowserBench task suite with one agent and print a summary.

This is the smallest end-to-end use of the harness: load all bundled
tasks, run the reference scripted agent against them, and print the
terminal report. Artifacts (trace, result and replayable artifact per
task, plus ``summary.json`` / ``report.md``) are written under ``runs/``.

Usage (from the repo root):

    python3 examples/run_suite.py
    python3 examples/run_suite.py --agent random
    python3 examples/run_suite.py --out runs/my-first-suite

Exit code is 0 when the suite ran cleanly to completion, whatever the
pass rate — a failing agent is a result, not a crash. See
``examples/compare_agents.py`` for a head-to-head run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Allow running from the repo root without installing the package:
# examples/ lives one level below the repo root, which holds the
# ``browserbench`` package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from browserbench.adapter import load_agent
from browserbench.report import render_summary_markdown, render_terminal
from browserbench.runner import run_suite
from browserbench.spec import load_tasks


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the full BrowserBench suite with one agent.")
    parser.add_argument(
        "--agent", default="scripted",
        help="agent spec: 'scripted' (default), 'random', a .py file, "
             "or an http:// URL (see browserbench.adapter.load_agent)")
    parser.add_argument(
        "--tasks-dir", default=None,
        help="directory of task files (default: <repo root>/tasks)")
    parser.add_argument(
        "--out", default=None,
        help="output directory for run artifacts "
             "(default: runs/example-run-suite)")
    args = parser.parse_args(argv)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tasks_dir = args.tasks_dir or os.path.join(root, "tasks")
    out_dir = args.out or os.path.join(root, "runs", "example-run-suite")

    tasks = load_tasks(tasks_dir)
    agent = load_agent(args.agent)
    print(f"BrowserBench — {len(tasks)} tasks, agent: {agent.name}\n")

    summary = run_suite(tasks, agent, out_dir,
                        config={"agent_spec": args.agent, "example": "run_suite"})
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(render_summary_markdown(summary))

    print(render_terminal(summary))
    print(f"\nartifacts: {os.path.abspath(out_dir)}")
    print(f"summary:   {os.path.join(os.path.abspath(out_dir), 'summary.json')}")
    if summary["success_rate"] < 1.0:
        print(f"\nNote: {summary['tasks_run'] - summary['tasks_passed']} task(s) "
              f"failed — see examples/replay_failed.py to replay one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
