"""Pick a failed run, replay it from its saved artifact, and check it matches.

A BrowserBench run saves a replayable artifact (``artifact.json``) with
the task id + version, the seed and the exact action sequence. Replay
resets the site with the recorded seed, re-executes those actions and
re-evaluates the final state. Because the test sites are deterministic
given (seed, action sequence), the replayed result must match the
original exactly — a mismatch means the task or the site changed, and
is reported loudly rather than silently.

By default this example first produces a failed run to replay: it runs
the random baseline (which fails nearly every bundled task) into
``runs/example-replay-random`` and replays its first failed task. Pass
``--run-dir`` to replay an existing run instead — either a single task
run directory (containing ``artifact.json``) or a suite directory (the
first failed task inside it is replayed).

Usage (from the repo root):

    python3 examples/replay_failed.py
    python3 examples/replay_failed.py --run-dir runs/demo-random
    python3 examples/replay_failed.py --run-dir runs/demo-random/shop-checkout

Exit code is 0 when the replay matches the original result, 1 on a
mismatch, and 2 when no failed run could be found to replay.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Allow running from the repo root without installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from browserbench.adapter import load_agent
from browserbench.replay import replay_run
from browserbench.runner import run_suite
from browserbench.spec import load_tasks


def _find_failed_run_dir(suite_dir: str) -> str | None:
    """First task sub-directory under `suite_dir` whose result failed."""
    if os.path.isfile(os.path.join(suite_dir, "artifact.json")):
        return suite_dir  # already a single task run directory
    if not os.path.isdir(suite_dir):
        return None
    for name in sorted(os.listdir(suite_dir)):
        run_dir = os.path.join(suite_dir, name)
        result_path = os.path.join(run_dir, "result.json")
        if not os.path.isfile(result_path):
            continue
        with open(result_path, "r", encoding="utf-8") as fh:
            result = json.load(fh)
        if not result.get("evaluation", {}).get("success", True):
            return run_dir
    return None


def _produce_failed_run(root: str, tasks_dir: str) -> str:
    """Run the random baseline (expected to fail) and return a failed run dir."""
    tasks = load_tasks(tasks_dir)
    agent = load_agent("random")
    out_dir = os.path.join(root, "runs", "example-replay-random")
    print(f"No run directory given — running the random baseline on "
          f"{len(tasks)} tasks to produce a failed run ...")
    summary = run_suite(tasks, agent, out_dir,
                        config={"agent_spec": "random",
                                "example": "replay_failed"})
    failed = next((r for r in summary["results"]
                   if not r["evaluation"]["success"]), None)
    if failed is None:
        print("The random baseline passed every task — nothing to replay.")
        return ""
    print(f"  random baseline: {summary['tasks_passed']}/{summary['tasks_run']} "
          f"passed; first failure: {failed['task_id']}\n")
    return os.path.join(out_dir, failed["task_id"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay a failed BrowserBench run and check it matches.")
    parser.add_argument(
        "--run-dir", default=None,
        help="existing run directory to replay: a single task run dir "
             "(with artifact.json) or a suite dir (first failed task "
             "inside it is used). Default: run the random baseline first.")
    parser.add_argument(
        "--tasks-dir", default=None,
        help="directory of task files (default: <repo root>/tasks)")
    args = parser.parse_args(argv)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tasks_dir = args.tasks_dir or os.path.join(root, "tasks")

    if args.run_dir:
        run_dir = _find_failed_run_dir(args.run_dir)
        if run_dir is None:
            print(f"No failed run found in {args.run_dir!r} "
                  f"(need an artifact.json or a result.json with success=false).",
                  file=sys.stderr)
            return 2
    else:
        run_dir = _produce_failed_run(root, tasks_dir)
        if not run_dir:
            return 2

    print(f"Replaying failed run: {run_dir}")
    replayed = replay_run(run_dir, tasks_dir)

    print(f"\nReplay of {replayed['task_id']} (task v{replayed['task_version']}):")
    print(f"  original:  {'PASS' if replayed['original_success'] else 'FAIL'} "
          f"({replayed['original_passed']} conditions passed)")
    print(f"  replayed:  {'PASS' if replayed['replayed_success'] else 'FAIL'} "
          f"({replayed['replayed_passed']} conditions passed)")
    print(f"  match: {'YES' if replayed['match'] else 'NO — INVESTIGATE'}")
    if not replayed["match"]:
        print("  The replay diverged from the original run. That means the "
              "task or the test site changed since the run was recorded; "
              "do not trust either result until the drift is explained.")
        return 1
    print("  The failure reproduces exactly — it can be debugged locally "
          "from the saved artifact.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
