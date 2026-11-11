"""BrowserBench CLI.

Usage:
    python -m browserbench init [--dir DIR]
        Scaffold a workspace: tasks/, agents/, runs/, browserbench.yaml.

    python -m browserbench run --agent scripted|random|./agents/x.py|http://...
        [--tasks shopping,crm | all] [--out runs/2026-...] [--tasks-dir tasks]
        Run the task suite against an agent and write a summary + report.

    python -m browserbench report latest [--runs-dir runs]
        Print the most recent run's report.

    python -m browserbench replay <run-dir> [--tasks-dir tasks]
        Re-execute a saved artifact and compare the outcome.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

from . import __version__
from .adapter import load_agent
from .report import latest_run_dir, load_summary, render_summary_markdown, render_terminal
from .runner import run_suite
from .spec import load_tasks

_BUNDLED_TASKS = os.path.join(os.path.dirname(__file__), "..", "tasks")
_BUNDLED_AGENTS = os.path.join(os.path.dirname(__file__), "..", "agents")


def _bundled(path: str) -> str:
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", path))


def cmd_init(args) -> int:
    root = args.dir
    for sub in ("tasks", "agents", "runs"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    for task_dir in ("shopping", "crm", "scheduling", "support"):
        src = os.path.join(_bundled("tasks"), task_dir)
        dst = os.path.join(root, "tasks", task_dir)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
    for name in os.listdir(_bundled("agents")):
        src_path = os.path.join(_bundled("agents"), name)
        if os.path.isfile(src_path):
            shutil.copy2(src_path, os.path.join(root, "agents", name))
    config = (
        "# BrowserBench workspace\n"
        f"browserbench_version: {__version__}\n"
        "tasks_dir: tasks\n"
        "runs_dir: runs\n"
        "default_agent: scripted\n"
    )
    with open(os.path.join(root, "browserbench.yaml"), "w", encoding="utf-8") as fh:
        fh.write(config)
    print(f"Initialised BrowserBench workspace at {os.path.abspath(root)}")
    print("  browserbench run --agent scripted")
    return 0


def _select_tasks(tasks, selection: str):
    if selection in ("all", ""):
        return tasks
    wanted = {name.strip() for name in selection.split(",") if name.strip()}
    selected = [t for t in tasks if t.id in wanted
                or t.site in wanted or t.id.split("-")[0] in wanted]
    missing = wanted - {t.id for t in tasks} - {t.site for t in tasks}
    if missing:
        print(f"warning: no tasks matched {sorted(missing)}", file=sys.stderr)
    return selected


def cmd_run(args) -> int:
    tasks = load_tasks(args.tasks_dir)
    tasks = _select_tasks(tasks, args.tasks)
    if not tasks:
        print("no tasks selected", file=sys.stderr)
        return 2
    agent = load_agent(args.agent)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = args.out or os.path.join(args.runs_dir, f"{stamp}-{agent.name}")
    summary = run_suite(tasks, agent, out_dir,
                        config={"agent_spec": args.agent})
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(render_summary_markdown(summary))
    print(render_terminal(summary))
    print(f"artifacts: {os.path.abspath(out_dir)}")
    return 0 if summary["success_rate"] == 1.0 else 1


def cmd_report(args) -> int:
    run_dir = None if args.run in (None, "latest") else args.run
    run_dir = run_dir or latest_run_dir(args.runs_dir)
    if not run_dir:
        print("no runs found", file=sys.stderr)
        return 2
    summary = load_summary(run_dir)
    if summary is None:
        print(f"no summary.json in {run_dir}", file=sys.stderr)
        return 2
    print(render_terminal(summary))
    return 0


def cmd_replay(args) -> int:
    from .replay import replay_run
    result = replay_run(args.run, args.tasks_dir)
    print(f"replay of {result['task_id']} (task v{result['task_version']}):")
    print(f"  original:  {'PASS' if result['original_success'] else 'FAIL'} "
          f"({result['original_passed']} conditions)")
    print(f"  replayed:  {'PASS' if result['replayed_success'] else 'FAIL'} "
          f"({result['replayed_passed']} conditions)")
    print(f"  match: {'YES' if result['match'] else 'NO — INVESTIGATE'}")
    return 0 if result["match"] else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="browserbench",
        description="Reproducible evaluation for browser-using AI agents.")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="scaffold a workspace")
    p_init.add_argument("dir", nargs="?", default=".",
                        help="workspace directory")
    p_init.add_argument("--dir", dest="dir", default=argparse.SUPPRESS,
                        help="workspace directory")
    p_init.set_defaults(func=cmd_init)

    p_run = sub.add_parser("run", help="run tasks against an agent")
    p_run.add_argument("--agent", required=True,
                       help="scripted | random | ./agents/x.py | http://...")
    p_run.add_argument("--tasks", default="all",
                       help="comma list of task ids/sites, or 'all'")
    p_run.add_argument("--tasks-dir", default=_bundled("tasks"))
    p_run.add_argument("--runs-dir", default="runs")
    p_run.add_argument("--out", default=None, help="output directory")
    p_run.set_defaults(func=cmd_run)

    p_report = sub.add_parser("report", help="show a run report")
    p_report.add_argument("run", nargs="?", default=None,
                          help="run directory (default: latest)")
    p_report.add_argument("--runs-dir", default="runs")
    p_report.set_defaults(func=cmd_report)

    p_replay = sub.add_parser("replay", help="replay a saved run artifact")
    p_replay.add_argument("run", help="run directory containing artifact.json")
    p_replay.add_argument("--tasks-dir", default=_bundled("tasks"))
    p_replay.set_defaults(func=cmd_replay)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
