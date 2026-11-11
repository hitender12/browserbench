"""Regression tests for the 13 QA-audit fixes (2026-11-11).

Run: python3 -m unittest discover -s tests

Each test names the finding it pins, reproduces the original failure
mode, and asserts the fix. The non-editable-install test is slow (builds
a venv); it is skipped when venv creation is unavailable.
"""

import dataclasses
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from browserbench import __version__  # noqa: E402
from browserbench.adapter import BaseAgent, HttpAgent, load_agent  # noqa: E402
from browserbench.agents import RandomAgent  # noqa: E402
from browserbench.evaluator import evaluate, evaluate_condition  # noqa: E402
from browserbench.report import latest_run_dir, load_summary  # noqa: E402
from browserbench.runner import run_suite, run_task  # noqa: E402
from browserbench.sites import make_server  # noqa: E402
from browserbench.spec import load_tasks  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
TASKS_DIR = os.path.join(ROOT, "tasks")

# Runs the random agent on one task and prints its actions + result as
# JSON, so two processes can be compared byte for byte.
_RANDOM_PROBE = """
import json, sys, tempfile
sys.path.insert(0, {root!r})
from browserbench.adapter import load_agent
from browserbench.runner import run_suite
from browserbench.spec import load_tasks
task = next(t for t in load_tasks({tasks!r}) if t.id == "shop-add-to-cart")
with tempfile.TemporaryDirectory() as tmp:
    s = run_suite([task], load_agent("random"), tmp)
    with open(tmp + "/shop-add-to-cart/artifact.json") as fh:
        artifact = json.load(fh)
r = s["results"][0]
print(json.dumps({{"actions": artifact["actions"],
                  "evaluation": r["evaluation"],
                  "steps": r["metrics"]["steps"],
                  "unsafe": r["metrics"]["unsafe_attempts"]}}, sort_keys=True))
"""


def _load(task_id):
    return next(t for t in load_tasks(TASKS_DIR) if t.id == task_id)


class _CostlyAgent(BaseAgent):
    """Scripted agent that reports a fixed cost."""

    name = "costly-agent"
    cost_usd = 0.42

    def __init__(self, task):
        self._inner = load_agent("scripted")
        self._task = task

    def reset(self, task):
        self._task = task
        self._inner.reset(task)

    def act(self, observation):
        return self._inner.act(observation)


class _CrashingAgent(BaseAgent):
    """Raises on every call: exercises the retries path."""

    name = "crashing-agent"

    def act(self, observation):
        raise RuntimeError("boom")


class TestRandomReproducibility(unittest.TestCase):
    """Fix 1: RandomAgent seeded from hash(task.id) was not reproducible
    across processes (Python string hash is randomised per process)."""

    def test_same_seed_same_actions_in_process(self):
        task = _load("shop-add-to-cart")
        observation = {"links": [{"text": "Widget Alpha", "href": "/shop/product/p1"},
                                 {"text": "View cart", "href": "/shop/cart"}],
                       "forms": [{"name": "f", "fields": []}]}
        first, second = RandomAgent(0), RandomAgent(0)
        first.reset(task)
        second.reset(task)
        self.assertEqual([first.act(observation) for _ in range(5)],
                         [second.act(observation) for _ in range(5)])

    def test_different_base_seeds_differ(self):
        task = _load("shop-add-to-cart")
        observation = {"links": [{"text": "Widget Alpha", "href": "/shop/product/p1"}],
                       "forms": []}
        a, b = RandomAgent(0), RandomAgent(1)
        a.reset(task)
        b.reset(task)
        self.assertNotEqual([a.act(observation) for _ in range(5)],
                            [b.act(observation) for _ in range(5)])

    def test_cross_process_identical_under_different_hash_seeds(self):
        script = _RANDOM_PROBE.format(root=ROOT, tasks=TASKS_DIR)
        outputs = []
        for hash_seed in ("0", "999", "12345"):
            env = dict(os.environ, PYTHONHASHSEED=hash_seed)
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True, env=env, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            outputs.append(proc.stdout.strip())
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[1], outputs[2])


class TestReadmeDemoBlock(unittest.TestCase):
    """Fix 2: the README demo block (43 steps / 0.9s scripted, 74 steps
    random) did not match real runs. The block now reports pass counts
    and step counts only (durations vary run to run) and this test pins
    it against a fresh run."""

    def _readme_block(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = fh.read()
        scripted = re.search(
            r"scripted\s*\npassed (\d+)/(\d+) .* steps (\d+)", readme)
        random = re.search(
            r"random\s*\npassed (\d+)–(\d+)/(\d+) .* steps (\d+)", readme)
        self.assertIsNotNone(scripted, "README has no scripted demo line")
        self.assertIsNotNone(random, "README has no random demo line")
        return readme, scripted, random

    def test_demo_block_matches_fresh_run(self):
        readme, scripted_m, random_m = self._readme_block()
        tasks = load_tasks(TASKS_DIR)
        with tempfile.TemporaryDirectory() as tmp:
            s_sum = run_suite(tasks, load_agent("scripted"), tmp)
        with tempfile.TemporaryDirectory() as tmp:
            r_sum = run_suite(tasks, load_agent("random"), tmp)
        self.assertEqual((int(scripted_m.group(1)), int(scripted_m.group(2))),
                         (s_sum["tasks_passed"], s_sum["tasks_run"]))
        self.assertEqual(int(scripted_m.group(3)), s_sum["total_steps"])
        # Random is reported as a range across seeds; seed 0 must fall
        # inside it, and the denominator must be the task count.
        self.assertEqual(int(random_m.group(3)), r_sum["tasks_run"])
        self.assertLessEqual(int(random_m.group(1)), r_sum["tasks_passed"])
        self.assertLessEqual(r_sum["tasks_passed"], int(random_m.group(2)))
        self.assertEqual(int(random_m.group(4)), r_sum["total_steps"])
        # No stale single-run numbers anywhere in the README.
        self.assertNotIn("10/10", readme)
        self.assertNotIn("0/10", readme)
        self.assertNotIn("43 steps", readme)
        self.assertNotIn("74 steps", readme)


class TestRandomBaselineRange(unittest.TestCase):
    """Fix 3: 'random baseline passes 0/10' was a single-run number that
    did not hold on a fresh run. The baseline is now reported as a range
    and a mean over seeds."""

    def test_baseline_range_covers_fresh_seed_runs(self):
        from demo import RANDOM_SEEDS, summarize_random_baseline
        tasks = load_tasks(TASKS_DIR)
        summaries = []
        for seed in RANDOM_SEEDS:
            with tempfile.TemporaryDirectory() as tmp:
                summaries.append(
                    run_suite(tasks, RandomAgent(seed), tmp))
        stats = summarize_random_baseline(summaries)
        self.assertEqual(stats["passed"],
                         [s["tasks_passed"] for s in summaries])
        self.assertEqual(stats["min"], min(stats["passed"]))
        self.assertEqual(stats["max"], max(stats["passed"]))
        self.assertAlmostEqual(stats["mean"],
                               sum(stats["passed"]) / len(stats["passed"]))
        self.assertEqual(stats["tasks_run"], len(tasks))

    def test_readme_reports_range_not_single_number(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = fh.read()
        self.assertIn("across 3 seeds", readme)
        self.assertNotRegex(readme, r"random baseline 0/\d+")


class TestCostReporting(unittest.TestCase):
    """Fix 4: 'cost where available' had no cost field anywhere in code.
    Agents may now supply cost_usd (attribute, or HTTP envelope)."""

    def test_agent_cost_in_metrics_summary_and_report(self):
        from browserbench.report import render_summary_markdown, render_terminal
        task = _load("shop-add-to-cart")
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_suite([task], _CostlyAgent(task), tmp)
        self.assertEqual(summary["results"][0]["metrics"]["cost_usd"], 0.42)
        self.assertEqual(summary["total_cost_usd"], 0.42)
        self.assertIn("$0.42", render_summary_markdown(summary))
        self.assertIn("cost $0.42", render_terminal(summary))

    def test_bundled_agents_report_no_cost(self):
        task = _load("shop-add-to-cart")
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_suite([task], load_agent("scripted"), tmp)
        self.assertNotIn("cost_usd", summary["results"][0]["metrics"])
        self.assertIsNone(summary["total_cost_usd"])

    def test_http_agent_accumulates_cost_from_envelope(self):
        class _CostHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.dumps({
                    "protocol": "browserbench-agent/1",
                    "action": {"type": "done"},
                    "cost_usd": 0.05}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), _CostHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            host, port = server.server_address
            agent = HttpAgent(f"http://{host}:{port}")
            agent.act({"url": "http://x/", "links": [], "forms": []})
            agent.act({"url": "http://x/", "links": [], "forms": []})
        finally:
            server.shutdown()
            server.server_close()
        self.assertAlmostEqual(agent.cost_usd, 0.10)


class TestRetriesAggregated(unittest.TestCase):
    """Fix 5: retries were counted per task only, never aggregated into
    summary.json or shown in the report."""

    def test_retries_in_summary_and_report(self):
        from browserbench.report import render_summary_markdown
        task = _load("shop-add-to-cart")
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_suite([task], _CrashingAgent(), tmp)
        self.assertGreaterEqual(summary["results"][0]["metrics"]["retries"], 1)
        self.assertGreaterEqual(summary["total_retries"], 1)
        self.assertIn("Total retries", render_summary_markdown(summary))


class TestReportLatestSkipsIncompleteRuns(unittest.TestCase):
    """Fix 7: `report latest` picked the newest directory even when it
    had no summary.json (e.g. runs/demo-random) and died with exit 2."""

    def test_latest_skips_dirs_without_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            valid = os.path.join(tmp, "20260101-old-valid")
            os.makedirs(valid)
            with open(os.path.join(valid, "summary.json"), "w") as fh:
                json.dump({"agent": "x"}, fh)
            os.utime(valid, (1000000000, 1000000000))
            broken = os.path.join(tmp, "demo-random")
            os.makedirs(os.path.join(broken, "shop-add-to-cart"))
            os.utime(broken, (1700000000, 1700000000))
            self.assertEqual(latest_run_dir(tmp), valid)

    def test_latest_returns_none_when_no_summary_anywhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "demo-random"))
            self.assertIsNone(latest_run_dir(tmp))

    def test_report_on_dir_without_summary_errors_cleanly(self):
        from browserbench.__main__ import cmd_report
        import argparse
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = os.path.join(tmp, "demo-random")
            os.makedirs(run_dir)
            args = argparse.Namespace(run=run_dir, runs_dir=tmp)
            self.assertEqual(cmd_report(args), 2)


class TestWorkspaceConfig(unittest.TestCase):
    """Fix 8: `init` wrote browserbench.yaml but `run` never read it —
    the workspace was decorative. `run`/`report`/`replay` now honour it."""

    def _run_cli(self, cwd, args, extra_env=None):
        env = dict(os.environ, PYTHONPATH=ROOT)
        if extra_env:
            env.update(extra_env)
        return subprocess.run([sys.executable, "-m", "browserbench"] + args,
                              capture_output=True, text=True, cwd=cwd,
                              env=env, timeout=120)

    def test_run_inside_workspace_uses_workspace_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = os.path.join(tmp, "ws")
            proc = self._run_cli(tmp, ["init", ws])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            proc = self._run_cli(
                ws, ["run", "--tasks", "shop-add-to-cart"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("passed 1/1", proc.stdout)
            runs = os.listdir(os.path.join(ws, "runs"))
            self.assertEqual(len(runs), 1)
            self.assertTrue(os.path.exists(
                os.path.join(ws, "runs", runs[0], "summary.json")))

    def test_explicit_tasks_dir_overrides_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = os.path.join(tmp, "ws")
            self.assertEqual(self._run_cli(tmp, ["init", ws]).returncode, 0)
            proc = self._run_cli(
                ws, ["run", "--tasks", "shop-add-to-cart",
                     "--tasks-dir", TASKS_DIR])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("passed 1/1", proc.stdout)

    def test_default_agent_from_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = os.path.join(tmp, "ws")
            self.assertEqual(self._run_cli(tmp, ["init", ws]).returncode, 0)
            # No --agent flag: the config's default_agent (scripted) applies.
            proc = self._run_cli(ws, ["run", "--tasks", "shop-add-to-cart"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("passed 1/1", proc.stdout)


class TestExitCodeContract(unittest.TestCase):
    """Fix 9: any run below 100% exits 1 — now documented in the CLI
    help, the module docstring, README and methodology."""

    def test_scripted_single_task_exits_0(self):
        from browserbench.__main__ import main
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["run", "--agent", "scripted",
                                   "--tasks", "shop-add-to-cart",
                                   "--out", os.path.join(tmp, "r")]), 0)

    def test_failing_run_exits_1(self):
        from browserbench.__main__ import main
        agent_path = os.path.join(
            tempfile.mkdtemp(), "crash_agent.py")
        with open(agent_path, "w", encoding="utf-8") as fh:
            fh.write("class Agent:\n"
                     "    name = 'crash'\n"
                     "    def reset(self, task): pass\n"
                     "    def act(self, o): raise RuntimeError('boom')\n")
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["run", "--agent", agent_path,
                                   "--tasks", "shop-add-to-cart",
                                   "--out", os.path.join(tmp, "r")]), 1)

    def test_exit_code_documented(self):
        with open(os.path.join(ROOT, "browserbench", "__main__.py"),
                  encoding="utf-8") as fh:
            cli = fh.read()
        self.assertIn("0 when the agent passes every task", cli)
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            self.assertIn("exit code", fh.read().lower())


class TestPython3Everywhere(unittest.TestCase):
    """Fix 10: README used `python3` throughout but only `python3`
    exists on this VM."""

    def test_no_bare_python_in_docs_or_code(self):
        # The bare interpreter name, without the trailing 3 (not the
        # `python3` command, not `requires-python`, not the GitHub
        # Actions `python-version` input name). The pattern is built
        # from parts so this test file does not flag its own regex.
        word = "py" + "thon"
        pattern = re.compile(r"(?<![\w-])" + word + r"(?![\w3]|(-version))")
        offenders = []
        for root, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs
                       if d not in ("runs", "__pycache__", ".git", ".venv")]
            for name in files:
                if not name.endswith((".md", ".py", ".toml", ".yml",
                                      ".yaml", ".txt")):
                    continue
                path = os.path.join(root, name)
                with open(path, encoding="utf-8") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if pattern.search(line):
                            offenders.append(f"{path}:{lineno}: {line.strip()}")
        self.assertEqual(offenders, [])


class TestNonEditableInstall(unittest.TestCase):
    """Fix 11: a non-editable install shipped only the browserbench
    package — tasks/, agents/ and demo.py were missing, so `browserbench
    run` with no --tasks-dir failed outside a checkout."""

    def test_installed_cli_runs_outside_checkout(self):
        try:
            subprocess.run([sys.executable, "-m", "venv", "--help"],
                           capture_output=True, check=True, timeout=30)
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.skipTest("venv unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            venv = os.path.join(tmp, "venv")
            proc = subprocess.run(
                [sys.executable, "-m", "venv", "--system-site-packages", venv],
                capture_output=True, text=True, timeout=120)
            if proc.returncode != 0:
                self.skipTest(f"venv creation failed: {proc.stderr[:200]}")
            vpy = os.path.join(venv, "bin", "python3")
            proc = subprocess.run(
                [vpy, "-m", "pip", "install", "--no-build-isolation",
                 "--quiet", ROOT],
                capture_output=True, text=True, timeout=300)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out_dir = os.path.join(tmp, "run")
            proc = subprocess.run(
                [os.path.join(venv, "bin", "browserbench"), "run",
                 "--agent", "scripted", "--tasks", "shop-add-to-cart",
                 "--out", out_dir],
                capture_output=True, text=True, cwd=tmp, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("passed 1/1", proc.stdout)
            self.assertTrue(os.path.exists(
                os.path.join(out_dir, "summary.json")))


class TestNewTasks(unittest.TestCase):
    """Fix 13: partial credit was never exercised by real tasks and
    state_equals was used by no task. Three new tasks (18 total) fix
    both."""

    def test_eighteen_tasks_load(self):
        tasks = load_tasks(TASKS_DIR)
        self.assertEqual(len(tasks), 18)
        ids = {t.id for t in tasks}
        for new_id in ("shop-buy-two-checkout", "crm-create-and-note",
                       "sched-book-and-verify"):
            self.assertIn(new_id, ids)

    def test_new_tasks_have_multiple_conditions(self):
        for task_id in ("shop-buy-two-checkout", "crm-create-and-note",
                        "sched-book-and-verify"):
            self.assertGreaterEqual(len(_load(task_id).success), 2)

    def test_new_tasks_scripted_pass_all(self):
        tasks = [_load(t) for t in ("shop-buy-two-checkout",
                                    "crm-create-and-note",
                                    "sched-book-and-verify")]
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_suite(tasks, load_agent("scripted"), tmp)
        self.assertEqual(summary["tasks_passed"], 3)

    def test_real_partial_run_scores_half(self):
        # The scripted agent with a truncated plan buys only Widget
        # Alpha and checks out: exactly one of the two order conditions.
        task = _load("shop-buy-two-checkout")
        truncated = dataclasses.replace(task, reference_plan=[
            {"action": "link", "text": "Widget Alpha"},
            {"action": "submit", "button": "Add to cart"},
            # After the add, the agent is on the cart page, so it goes
            # straight to checkout with only Widget Alpha in the cart.
            {"action": "link", "text": "Checkout"},
            {"action": "fill", "values": {"address": "12 Test Street",
                                          "name": "Ada Lovelace"}},
            {"action": "submit", "button": "Place order"},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_suite([truncated], load_agent("scripted"), tmp)
        result = summary["results"][0]
        self.assertFalse(result["evaluation"]["success"])
        self.assertEqual(result["evaluation"]["partial"], 0.5)
        self.assertEqual((result["evaluation"]["passed"],
                          result["evaluation"]["total"]), (1, 2))

    def test_state_equals_task_uses_state_equals(self):
        task = _load("sched-book-and-verify")
        self.assertTrue(any(c["type"] == "state_equals"
                            for c in task.success))
        good = {"appointments": [
            {"id": 1, "slot": "2026-11-20 09:00", "name": "Alan Turing",
             "status": "booked"},
            {"id": 2, "slot": "2026-11-20 14:00", "name": "Grace Hopper",
             "status": "booked"}],
            "next_appointment_id": 3, "slots": []}
        self.assertTrue(evaluate(task, good)["success"])
        bad = dict(good, next_appointment_id=2)
        self.assertFalse(evaluate(task, bad)["success"])


class TestDocsMatchCode(unittest.TestCase):
    """README and methodology must match the fixed code (fixes 2, 6, 12)."""

    def _read(self, rel):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_readme_counts_and_trace_wording(self):
        readme = self._read("README.md")
        self.assertIn("18 tasks", readme)
        self.assertIn("18/18", readme)
        # The trace stores a DOM summary + full state snapshot, not a
        # full DOM snapshot.
        self.assertIn("DOM summary", readme)
        self.assertNotIn("DOM snapshot", readme)
        self.assertIn("state snapshot", readme)

    def test_methodology_counts_and_claims(self):
        method = self._read("docs/benchmark-methodology.md")
        self.assertIn("18 tasks", method)
        self.assertIn("18/18", method)
        self.assertIn("exit code", method.lower())
        self.assertIn("retries", method.lower())
        self.assertIn("cost", method.lower())
        self.assertNotIn("10/10", method)
        self.assertNotIn("0/10", method)


if __name__ == "__main__":
    unittest.main()
