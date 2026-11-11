"""Demo: run the scripted reference agent and the random baseline on the
same tasks, then print a side-by-side comparison.

    python3 demo.py

The random baseline is run across several seeds (default 0, 1, 2) and
reported as a range and a mean, because a single random run is not a
stable number — one seed can pass a task another fails. The scripted
agent is deterministic, so one run is enough for it.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browserbench.adapter import load_agent
from browserbench.agents import RandomAgent
from browserbench.report import render_terminal
from browserbench.replay import replay_run
from browserbench.runner import run_suite
from browserbench.spec import load_tasks

RANDOM_SEEDS = (0, 1, 2)


def summarize_random_baseline(summaries: list[dict]) -> dict:
    """Range/mean of the random baseline across seeds.

    Returns {"passed": [per-seed pass counts], "min": int, "max": int,
    "mean": float, "tasks_run": int}. A single seed's pass count is
    never quoted on its own — only the range and the mean.
    """
    passed = [s["tasks_passed"] for s in summaries]
    return {
        "passed": passed,
        "min": min(passed),
        "max": max(passed),
        "mean": sum(passed) / len(passed) if passed else 0.0,
        "tasks_run": summaries[0]["tasks_run"] if summaries else 0,
    }


def main() -> int:
    root = os.path.dirname(os.path.abspath(__file__))
    tasks = load_tasks(os.path.join(root, "tasks"))
    print(f"BrowserBench demo — {len(tasks)} tasks, two agents, identical conditions\n")

    agent = load_agent("scripted")
    out_dir = os.path.join(root, "runs", "demo-scripted")
    scripted = run_suite(tasks, agent, out_dir)
    print(render_terminal(scripted))
    print()

    random_summaries = []
    for seed in RANDOM_SEEDS:
        agent = RandomAgent(seed)
        suffix = "demo-random" if seed == RANDOM_SEEDS[0] else f"demo-random-seed{seed}"
        out_dir = os.path.join(root, "runs", suffix)
        summary = run_suite(tasks, agent, out_dir)
        random_summaries.append(summary)
    baseline = summarize_random_baseline(random_summaries)
    print(render_terminal(random_summaries[0]))
    print(f"(random baseline across seeds {list(RANDOM_SEEDS)}: "
          f"{baseline['min']}–{baseline['max']}/{baseline['tasks_run']} passed, "
          f"mean {baseline['mean']:.1f})")
    print()

    print("Side by side")
    print(f"  scripted: {scripted['tasks_passed']}/{scripted['tasks_run']} passed, "
          f"{scripted['total_steps']} steps, {scripted['total_duration_s']}s, "
          f"{scripted['total_unsafe_attempts']} unsafe blocked")
    print(f"  random:   {baseline['min']}–{baseline['max']}/"
          f"{baseline['tasks_run']} passed across {len(RANDOM_SEEDS)} seeds "
          f"(mean {baseline['mean']:.1f}), "
          f"{random_summaries[0]['total_steps']} steps (seed 0), "
          f"{random_summaries[0]['total_duration_s']}s, "
          f"{random_summaries[0]['total_unsafe_attempts']} unsafe blocked")

    # Replay one failed random run to show failure replay works.
    failed = next((r for r in random_summaries[0]["results"]
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
