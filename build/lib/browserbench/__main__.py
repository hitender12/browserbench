"""BrowserBench CLI.

Usage:
    python3 -m browserbench init [--dir DIR]
        Scaffold a workspace: tasks/, agents/, runs/, browserbench.yaml.

    python3 -m browserbench run --agent scripted|random|./agents/x.py|http://...
        [--tasks shopping,crm | all] [--out runs/2026-...] [--tasks-dir tasks]
        Run the task suite against an agent and write a summary + report.

    python3 -m browserbench report latest [--runs-dir runs]
        Print the most recent run's report.

    python3 -m browserbench replay <run-dir> [--tasks-dir tasks]
        Re-execute a saved artifact and compare the outcome.

Workspace config: when run inside a directory containing
``browserbench.yaml`` (created by ``init``), ``run``/``report``/``replay``
read ``tasks_dir``, ``runs_dir`` and ``default_agent`` from it, so
``python3 -m browserbench run`` with no flags uses the workspace's own
tasks. Explicit flags always win over the config file.

Exit codes (``run``): 0 when the agent passes every task (100% success
rate), 1 when any task fails, 2 for a usage/loading error. A run below
100% is a failing run — the exit code says so. Loading errors (unknown
agent, unreadable agent file, malformed task pack, missing/corrupt
replay artifact) also exit 2, with a one-line message on stderr and no
traceback — ``replay`` follows the same rule.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import sysconfig
import time

from . import __version__
from .adapter import load_agent
from .report import latest_run_dir, load_summary, render_summary_markdown, render_terminal
from .runner import run_suite
from .spec import load_tasks

_CHECKOUT_TASKS = os.path.join(os.path.dirname(__file__), "..", "tasks")
_CHECKOUT_AGENTS = os.path.join(os.path.dirname(__file__), "..", "agents")


def _bundled(path: str) -> str:
    """Bundled data directory (tasks or agents).

    Prefers the checkout copy next to the package; falls back to the
    data installed with the package (``<venv>/share/browserbench/...``)
    so ``browserbench run`` works outside a checkout after a
    non-editable ``pip install``.
    """
    checkout = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", path))
    if os.path.isdir(checkout):
        return checkout
    installed = os.path.join(
        sysconfig.get_path("data"), "share", "browserbench", path)
    if os.path.isdir(installed):
        return installed
    return checkout  # does not exist; the caller reports a clear error


def _load_workspace_config(directory: str = ".") -> dict:
    """Parse ``browserbench.yaml`` in `directory` (``key: value`` lines).

    Returns {} when there is no config file. Unknown keys are kept but
    ignored by the commands that read the config.
    """
    path = os.path.join(directory, "browserbench.yaml")
    config: dict[str, str] = {}
    if not os.path.isfile(path):
        return config
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, _, value = line.partition(":")
            config[key.strip()] = value.strip()
    return config


def _resolve_tasks_dir(explicit: str | None, config: dict) -> str:
    if explicit:
        return explicit
    if config.get("tasks_dir"):
        return os.path.join(".", config["tasks_dir"])
    return _bundled("tasks")


def _resolve_runs_dir(explicit: str | None, config: dict) -> str:
    if explicit:
        return explicit
    return config.get("runs_dir", "runs")


def _resolve_agent(explicit: str | None, config: dict) -> str:
    if explicit:
        return explicit
    return config.get("default_agent", "scripted")


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
    print("  python3 -m browserbench run --agent scripted")
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
    config = _load_workspace_config()
    tasks_dir = _resolve_tasks_dir(args.tasks_dir, config)
    runs_dir = _resolve_runs_dir(args.runs_dir, config)
    agent_spec = _resolve_agent(args.agent, config)
    if not os.path.isdir(tasks_dir):
        print(f"tasks directory not found: {tasks_dir}\n"
              "Pass --tasks-dir, or run inside a BrowserBench workspace "
              "(browserbench.yaml) or a checkout.", file=sys.stderr)
        return 2
    try:
        tasks = load_tasks(tasks_dir)
    except Exception as exc:  # duplicate id or unreadable pack: usage error
        print(f"browserbench: error: cannot load tasks from {tasks_dir}: "
              f"{exc}", file=sys.stderr)
        return 2
    tasks = _select_tasks(tasks, args.tasks)
    if not tasks:
        print("no tasks selected", file=sys.stderr)
        return 2
    try:
        agent = load_agent(agent_spec)
    except Exception as exc:  # unknown spec, missing/broken agent file
        print(f"browserbench: error: cannot load agent {agent_spec!r}: "
              f"{exc}", file=sys.stderr)
        return 2
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = args.out or os.path.join(runs_dir, f"{stamp}-{agent.name}")
    summary = run_suite(tasks, agent, out_dir,
                        config={"agent_spec": agent_spec})
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(render_summary_markdown(summary))
    print(render_terminal(summary))
    print(f"artifacts: {os.path.abspath(out_dir)}")
    return 0 if summary["success_rate"] == 1.0 else 1


def cmd_report(args) -> int:
    config = _load_workspace_config()
    runs_dir = _resolve_runs_dir(args.runs_dir, config)
    run_dir = None if args.run in (None, "latest") else args.run
    run_dir = run_dir or latest_run_dir(runs_dir)
    if not run_dir:
        print(f"no runs with a summary.json found in {runs_dir}\n"
              "Run `browserbench run` first, or point `report` at a suite "
              "run directory (one containing summary.json).",
              file=sys.stderr)
        return 2
    summary = load_summary(run_dir)
    if summary is None:
        print(f"{run_dir} has no summary.json — it may be a per-task run "
              "directory or an old demo run.\n"
              "Point `report` at a suite run directory (one containing "
              "summary.json), or use `browserbench report latest`.",
              file=sys.stderr)
        return 2
    print(render_terminal(summary))
    return 0


def cmd_replay(args) -> int:
    from .replay import replay_run
    config = _load_workspace_config()
    tasks_dir = _resolve_tasks_dir(args.tasks_dir, config)
    try:
        result = replay_run(args.run, tasks_dir)
    except (OSError, ValueError, RuntimeError) as exc:
        # Missing run directory, corrupt artifact.json, unknown format
        # version, task not found, version drift, unreadable task pack:
        # all usage errors — one line on stderr, exit 2, no traceback.
        print(f"browserbench: error: cannot replay {args.run}: {exc}",
              file=sys.stderr)
        return 2
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
        description="Reproducible evaluation for browser-using AI agents.",
        epilog="Exit codes for `run`: 0 when the agent passes every task, "
               "1 when any task fails, 2 for a usage or loading error.")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="scaffold a workspace")
    p_init.add_argument("dir", nargs="?", default=".",
                        help="workspace directory")
    p_init.add_argument("--dir", dest="dir", default=argparse.SUPPRESS,
                        help="workspace directory")
    p_init.set_defaults(func=cmd_init)

    p_run = sub.add_parser(
        "run", help="run tasks against an agent",
        description="Run the task suite against an agent. Exit code 0 "
                    "only when the agent passes every task; 1 otherwise.")
    p_run.add_argument("--agent", default=None,
                       help="scripted | random | ./agents/x.py | http://... "
                            "(default: browserbench.yaml default_agent, "
                            "else scripted)")
    p_run.add_argument("--tasks", default="all",
                       help="comma list of task ids/sites, or 'all'")
    p_run.add_argument("--tasks-dir", default=None,
                       help="task directory (default: browserbench.yaml "
                            "tasks_dir, else the bundled tasks)")
    p_run.add_argument("--runs-dir", default=None,
                       help="output root for run artifacts "
                            "(default: browserbench.yaml runs_dir, else runs)")
    p_run.add_argument("--out", default=None, help="output directory")
    p_run.set_defaults(func=cmd_run)

    p_report = sub.add_parser("report", help="show a run report")
    p_report.add_argument("run", nargs="?", default=None,
                          help="run directory (default: latest)")
    p_report.add_argument("--runs-dir", default=None,
                          help="run artifacts root (default: "
                               "browserbench.yaml runs_dir, else runs)")
    p_report.set_defaults(func=cmd_report)

    p_replay = sub.add_parser("replay", help="replay a saved run artifact")
    p_replay.add_argument("run", help="run directory containing artifact.json")
    p_replay.add_argument("--tasks-dir", default=None,
                          help="task directory (default: browserbench.yaml "
                               "tasks_dir, else the bundled tasks)")
    p_replay.set_defaults(func=cmd_replay)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
