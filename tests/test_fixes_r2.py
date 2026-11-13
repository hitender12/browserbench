"""Regression tests for the round-2 re-audit fixes (2026-11-11).

Run: python3 -m unittest discover -s tests

Each test names the finding it pins, reproduces the original failure
mode, and asserts the fix.
"""

import contextlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from browserbench import __version__  # noqa: E402
from browserbench.adapter import BaseAgent, load_agent  # noqa: E402
from browserbench.runner import run_task  # noqa: E402
from browserbench.sites import make_server  # noqa: E402
from browserbench.spec import TaskSpecError, load_tasks  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
TASKS_DIR = os.path.join(ROOT, "tasks")


def _load(task_id):
    return next(t for t in load_tasks(TASKS_DIR) if t.id == task_id)


class _SequenceAgent(BaseAgent):
    """Returns a fixed action list, then done."""

    name = "sequence-agent"

    def __init__(self, actions):
        self._actions = list(actions)
        self._i = 0

    def reset(self, task):
        self._i = 0

    def act(self, observation):
        if self._i >= len(self._actions):
            return {"type": "done"}
        action = self._actions[self._i]
        self._i += 1
        return action


class _ServerMixin:
    def setUp(self):
        self.server = make_server()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        host, port = self.server.server_address
        self.base = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def _run(self, task, agent):
        tmp = tempfile.mkdtemp()
        out = os.path.join(tmp, "r")
        result = run_task(task, agent, self.base, out)
        with open(os.path.join(out, "trace.json")) as fh:
            trace = json.load(fh)
        return result, trace

    def _final_leads(self, trace):
        snap = trace["steps"][-1]["state_snapshot"]
        return {lead["id"]: lead for lead in snap["leads"]}


class TestCrossPageFillLeak(_ServerMixin, unittest.TestCase):
    """F2: HttpClient.form_values was keyed by form index only, so a
    fill made on one page leaked into the same-index form of another
    page. Fills are now bound to (page URL, form index)."""

    def test_fill_on_ada_does_not_land_on_grace(self):
        # The auditor's exact scenario: fill the note form (index 1)
        # on Ada Lovelace's page (lead 1), navigate to Grace Hopper
        # (lead 2), submit form 1 — the note must NOT land on Grace.
        task = _load("crm-add-note")
        agent = _SequenceAgent([
            {"type": "navigate", "url": "/crm/leads/1"},
            {"type": "fill", "form": 1,
             "values": {"note": "LEAKED NOTE"}},
            {"type": "navigate", "url": "/crm/leads/2"},
            {"type": "submit", "form": 1},
            {"type": "done"},
        ])
        _result, trace = self._run(task, agent)
        leads = self._final_leads(trace)
        self.assertNotIn("LEAKED NOTE", leads[2]["notes"])
        self.assertNotIn("LEAKED NOTE", leads[1]["notes"])

    def test_fill_then_submit_on_same_page_still_works(self):
        task = _load("crm-add-note")
        agent = _SequenceAgent([
            {"type": "navigate", "url": "/crm/leads/1"},
            {"type": "fill", "form": 1,
             "values": {"note": "Called, interested in a demo."}},
            {"type": "submit", "form": 1},
            {"type": "done"},
        ])
        result, trace = self._run(task, agent)
        leads = self._final_leads(trace)
        self.assertIn("Called, interested in a demo.", leads[1]["notes"])
        self.assertTrue(result["evaluation"]["success"])

    def test_fill_survives_return_to_same_page(self):
        # Binding is (page URL, form index): navigating away and back
        # to the same page keeps the fill for that page's form.
        task = _load("crm-add-note")
        agent = _SequenceAgent([
            {"type": "navigate", "url": "/crm/leads/1"},
            {"type": "fill", "form": 1,
             "values": {"note": "Called, interested in a demo."}},
            {"type": "navigate", "url": "/crm/leads/2"},
            {"type": "navigate", "url": "/crm/leads/1"},
            {"type": "submit", "form": 1},
            {"type": "done"},
        ])
        result, trace = self._run(task, agent)
        leads = self._final_leads(trace)
        self.assertIn("Called, interested in a demo.", leads[1]["notes"])
        self.assertNotIn("Called, interested in a demo.", leads[2]["notes"])
        self.assertTrue(result["evaluation"]["success"])


class TestCliLoadingErrors(unittest.TestCase):
    """F1: `run`/`replay` loading errors exited 1 with a raw traceback
    instead of the documented exit 2 with a clean message."""

    def _main(self, argv):
        from browserbench.__main__ import main
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(argv)
        return rc, out.getvalue(), err.getvalue()

    def _run(self, agent):
        with tempfile.TemporaryDirectory() as tmp:
            return self._main(["run", "--agent", agent,
                               "--tasks", "shop-add-to-cart",
                               "--out", os.path.join(tmp, "r")])

    def test_run_bogus_agent_exits_2_cleanly(self):
        rc, _out, err = self._run("bogus")
        self.assertEqual(rc, 2)
        self.assertNotIn("Traceback", err)
        self.assertIn("bogus", err)

    def test_run_nonexistent_agent_file_exits_2_cleanly(self):
        rc, _out, err = self._run("/nonexistent.py")
        self.assertEqual(rc, 2)
        self.assertNotIn("Traceback", err)

    def test_run_broken_agent_file_exits_2_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent_path = os.path.join(tmp, "broken.py")
            with open(agent_path, "w", encoding="utf-8") as fh:
                fh.write("raise RuntimeError('boom at import time')\n")
            rc, _out, err = self._run(agent_path)
        self.assertEqual(rc, 2)
        self.assertNotIn("Traceback", err)

    def test_replay_missing_dir_exits_2_cleanly(self):
        rc, _out, err = self._main(["replay", "/does-not-exist"])
        self.assertEqual(rc, 2)
        self.assertNotIn("Traceback", err)

    def test_replay_corrupted_artifact_exits_2_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = os.path.join(tmp, "bad-run")
            os.makedirs(run_dir)
            with open(os.path.join(run_dir, "artifact.json"), "w") as fh:
                fh.write("{not valid json")
            rc, _out, err = self._main(["replay", run_dir])
        self.assertEqual(rc, 2)
        self.assertNotIn("Traceback", err)

    def test_replay_unknown_format_version_exits_2_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = os.path.join(tmp, "bad-run")
            os.makedirs(run_dir)
            with open(os.path.join(run_dir, "artifact.json"), "w") as fh:
                json.dump({"format_version": "99.0.0",
                           "task_id": "shop-add-to-cart",
                           "task_version": "1.0.0", "seed": 1,
                           "actions": [],
                           "evaluation": {"success": True, "passed": 1}}, fh)
            rc, _out, err = self._main(["replay", run_dir])
        self.assertEqual(rc, 2)
        self.assertNotIn("Traceback", err)

    def test_run_duplicate_task_id_exits_2_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks_dir = os.path.join(tmp, "tasks")
            shutil.copytree(TASKS_DIR, tasks_dir)
            with open(os.path.join(tasks_dir, "dup.json"), "w") as fh:
                json.dump({"id": "shop-add-to-cart", "version": "1.0.0",
                           "site": "shop", "title": "t", "goal": "g",
                           "seed": 1, "max_steps": 5, "start_url": "/shop/",
                           "allowed_actions": ["done"],
                           "allowed_prefixes": ["/shop/"],
                           "success": [{"type": "state_equals", "path": "a",
                                        "value": 1}]}, fh)
            rc, _out, err = self._main(
                ["run", "--agent", "scripted", "--tasks", "shop-add-to-cart",
                 "--tasks-dir", tasks_dir,
                 "--out", os.path.join(tmp, "r")])
        self.assertEqual(rc, 2)
        self.assertNotIn("Traceback", err)
        self.assertIn("duplicate task id", err)


class TestBadTaskFileSkipped(unittest.TestCase):
    """F3: one malformed task file failed the whole load with a raw
    traceback and zero tasks ran. Bad files are now skipped with a
    warning naming the file; the good tasks still load and run."""

    def _poisoned_dir(self):
        tmp = tempfile.mkdtemp()
        tasks_dir = os.path.join(tmp, "tasks")
        shutil.copytree(TASKS_DIR, tasks_dir)
        bad = {}
        bad["bad-seed.json"] = {"id": "bad-seed", "version": "1.0.0",
                                "site": "shop", "title": "t", "goal": "g",
                                "seed": "not-a-number", "max_steps": 5,
                                "start_url": "/shop/",
                                "allowed_actions": ["done"],
                                "allowed_prefixes": ["/shop/"],
                                "success": [{"type": "state_equals",
                                             "path": "a", "value": 1}]}
        bad["bad-site.json"] = dict(bad["bad-seed.json"], id="bad-site",
                                    seed=1, site="nope")
        bad["bad-fields.json"] = {"id": "bad-fields"}
        for name, data in bad.items():
            with open(os.path.join(tasks_dir, name), "w") as fh:
                json.dump(data, fh)
        with open(os.path.join(tasks_dir, "bad-json.json"), "w") as fh:
            fh.write("{oops")
        return tmp, tasks_dir, list(bad) + ["bad-json.json"]

    def test_bad_files_skipped_and_named(self):
        tmp, tasks_dir, bad_names = self._poisoned_dir()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            tasks = load_tasks(tasks_dir)
        self.assertEqual(len(tasks), 18)
        self.assertEqual({t.id for t in tasks},
                         {t.id for t in load_tasks(TASKS_DIR)})
        warning = err.getvalue()
        for name in bad_names:
            self.assertIn(name, warning)

    def test_good_tasks_still_run_from_poisoned_dir(self):
        from browserbench.runner import run_suite
        tmp, tasks_dir, _bad = self._poisoned_dir()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            tasks = load_tasks(tasks_dir)
        task = next(t for t in tasks if t.id == "shop-add-to-cart")
        with tempfile.TemporaryDirectory() as out:
            summary = run_suite([task], load_agent("scripted"), out)
        self.assertEqual(summary["tasks_passed"], 1)

    def test_duplicate_id_still_a_hard_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks_dir = os.path.join(tmp, "tasks")
            shutil.copytree(TASKS_DIR, tasks_dir)
            with open(os.path.join(tasks_dir, "dup.json"), "w") as fh:
                json.dump({"id": "shop-add-to-cart", "version": "1.0.0",
                           "site": "shop", "title": "t", "goal": "g",
                           "seed": 1, "max_steps": 5, "start_url": "/shop/",
                           "allowed_actions": ["done"],
                           "allowed_prefixes": ["/shop/"],
                           "success": [{"type": "state_equals", "path": "a",
                                        "value": 1}]}, fh)
            with self.assertRaises(TaskSpecError):
                load_tasks(tasks_dir)


class TestOutOfRangeFormIndexBlocked(_ServerMixin, unittest.TestCase):
    """F4: a fill/submit naming a form index that does not exist on the
    current page was counted as a retry with blocked=None. It is now a
    blocked (unsafe) attempt with a reason."""

    def _check_blocked(self, action):
        task = _load("crm-add-note")
        agent = _SequenceAgent([action, {"type": "done"}])
        result, trace = self._run(task, agent)
        step = trace["steps"][0]
        self.assertEqual(result["metrics"]["unsafe_attempts"], 1)
        self.assertEqual(result["metrics"]["retries"], 0)
        self.assertIn("out of range", step["blocked"])
        self.assertIn("out of range",
                      result["metrics"]["blocked_reasons"][0])
        return result, trace

    def test_submit_index_99_blocked(self):
        self._check_blocked({"type": "submit", "form": 99})

    def test_fill_index_99_blocked(self):
        self._check_blocked({"type": "fill", "form": 99,
                             "values": {"note": "x"}})

    def test_negative_index_blocked(self):
        # Previously forms[-1] silently submitted the page's last form.
        self._check_blocked({"type": "submit", "form": -1})

    def test_non_integer_index_blocked(self):
        self._check_blocked({"type": "submit", "form": "1"})


def _free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class TestHttpExampleAgentDocstring(unittest.TestCase):
    """F5: the example HTTP agent's docstring said it 'solves a few of
    the bundled tasks'. It solves exactly one of the 18
    (sched-cancel-appointment). The docstring now says so, and the
    documented run command actually starts the server."""

    def test_example_agent_solves_exactly_one(self):
        from browserbench.runner import run_suite
        port = _free_port()
        env = dict(os.environ)  # no PYTHONPATH: the script must bootstrap
        proc = subprocess.Popen(
            [sys.executable, "agents/http_agent_example.py", str(port)],
            cwd=ROOT, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.time() + 15
            up = False
            while time.time() < deadline:
                try:
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{port}/act",
                        data=json.dumps(
                            {"protocol": "browserbench-agent/1",
                             "observation": {"goal": "", "links": [],
                                             "forms": []}}).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST")
                    with urllib.request.urlopen(req, timeout=2) as resp:
                        up = resp.status == 200
                    break
                except Exception:
                    time.sleep(0.2)
            self.assertTrue(up, "example HTTP agent did not start")
            tasks = load_tasks(TASKS_DIR)
            with tempfile.TemporaryDirectory() as tmp:
                summary = run_suite(
                    tasks, load_agent(f"http://127.0.0.1:{port}"), tmp)
            passed = [r["task_id"] for r in summary["results"]
                      if r["evaluation"]["success"]]
            self.assertEqual(passed, ["sched-cancel-appointment"])
        finally:
            proc.terminate()
            proc.wait(timeout=10)

    def test_docstring_states_the_truth(self):
        with open(os.path.join(ROOT, "agents", "http_agent_example.py"),
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("exactly one", text)
        self.assertIn("sched-cancel-appointment", text)
        self.assertIn("18 bundled tasks", text)
        self.assertNotIn("a few of the bundled tasks", text)

    def test_documented_command_starts_without_pythonpath(self):
        port = _free_port()
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        proc = subprocess.Popen(
            [sys.executable, "agents/http_agent_example.py", str(port)],
            cwd=ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.time() + 15
            body = None
            while time.time() < deadline:
                try:
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{port}/act",
                        data=json.dumps(
                            {"protocol": "browserbench-agent/1",
                             "observation": {"goal": "", "links": [],
                                             "forms": []}}).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST")
                    with urllib.request.urlopen(req, timeout=2) as resp:
                        body = json.loads(resp.read())
                    break
                except Exception:
                    time.sleep(0.2)
            self.assertIsNotNone(body, "server never answered")
            self.assertEqual(body.get("protocol"), "browserbench-agent/1")
        finally:
            proc.terminate()
            _out, err = proc.communicate(timeout=10)
            self.assertNotIn("ModuleNotFoundError", err)


if __name__ == "__main__":
    unittest.main()
