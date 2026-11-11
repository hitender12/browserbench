"""Demo: run the scripted reference agent and the random baseline on the
same 10 tasks, then print a side-by-side comparison.

    python demo.py

This is the demo from the blueprint: identical tasks, completion rate,
steps, latency and failure modes — plus a replay of one failed run.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browserbench.adapter import load_agent
from browserbench.report import render_terminal
from browserbench.replay import replay_run
from browserbench.runner import run_suite
from browserbench.spec import load_tasks


def main() -> int:
    root = os.path.dirname(os.path.abspath(__file__))
    tasks = load_tasks(os.path.join(root, "tasks"))
    print(f"BrowserBench demo — {len(tasks)} tasks, two agents, identical conditions\n")

    summaries = {}
    for agent_spec in ("scripted", "random"):
        agent = load_agent(agent_spec)
        out_dir = os.path.join(root, "runs", f"demo-{agent_spec}")
        summary = run_suite(tasks, agent, out_dir)
        summaries[agent_spec] = summary
        print(render_terminal(summary))
        print()

    scripted = summaries["scripted"]
    random_ = summaries["random"]
    print("Side by side")
    print(f"  scripted: {scripted['tasks_passed']}/{scripted['tasks_run']} passed, "
          f"{scripted['total_steps']} steps, {scripted['total_duration_s']}s, "
          f"{scripted['total_unsafe_attempts']} unsafe blocked")
    print(f"  random:   {random_['tasks_passed']}/{random_['tasks_run']} passed, "
          f"{random_['total_steps']} steps, {random_['total_duration_s']}s, "
          f"{random_['total_unsafe_attempts']} unsafe blocked")

    # Replay one failed random run to show failure replay works.
    failed = next((r for r in random_["results"]
                   if not r["evaluation"]["success"]), None)
    if failed is not None:
        run_dir = os.path.join(root, "runs", "demo-random", failed["task_id"])
        replayed = replay_run(run_dir, os.path.join(root, "tasks"))
        print(f"\nReplay of failed run {failed['task_id']}: "
              f"match={'YES' if replayed['match'] else 'NO'} "
              f"(replayed {'PASS' if replayed['replayed_success'] else 'FAIL'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
