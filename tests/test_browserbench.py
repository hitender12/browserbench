"""Tests for BrowserBench. Run: python3 -m unittest discover -s tests"""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from browserbench import __version__  # noqa: E402
from browserbench.adapter import BaseAgent, load_agent  # noqa: E402
from browserbench.dom import parse_html  # noqa: E402
from browserbench.evaluator import evaluate, evaluate_condition  # noqa: E402
from browserbench.replay import replay_run  # noqa: E402
from browserbench.runner import run_suite, run_task  # noqa: E402
from browserbench.sites import make_server  # noqa: E402
from browserbench.spec import TaskSpec, TaskSpecError, load_tasks  # noqa: E402
from browserbench.yamlmini import YamlMiniError, parse as yaml_parse  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
TASKS_DIR = os.path.join(ROOT, "tasks")


def _load(task_id):
    return next(t for t in load_tasks(TASKS_DIR) if t.id == task_id)


class MaliciousAgent(BaseAgent):
    """Tries to peek at harness state, then gives up."""

    name = "malicious-agent"

    def __init__(self):
        self.tried = False

    def reset(self, task):
        self.tried = False

    def act(self, observation):
        if not self.tried:
            self.tried = True
            return {"type": "navigate", "url": "/__state__?site=shop"}
        return {"type": "done"}


class TestSpecLoading(unittest.TestCase):
    def test_eighteen_tasks_load(self):
        tasks = load_tasks(TASKS_DIR)
        self.assertEqual(len(tasks), 18)
        ids = {t.id for t in tasks}
        self.assertIn("shop-add-to-cart", ids)
        self.assertIn("sched-cancel-appointment", ids)
        for new_id in ("shop-add-two-beta", "shop-buy-doohickey",
                       "crm-qualify-lead", "sched-book-afternoon",
                       "support-close-ticket", "shop-buy-two-checkout",
                       "crm-create-and-note", "sched-book-and-verify"):
            self.assertIn(new_id, ids)

    def test_yaml_task_loads(self):
        task = _load("sched-cancel-appointment")
        self.assertEqual(task.site, "sched")
        self.assertEqual(task.success, [{"type": "appointment_absent", "id": 1}])
        self.assertEqual(task.reference_plan[0], {"action": "link", "text": "Alan Turing"})

    def test_bad_spec_rejected(self):
        with self.assertRaises(TaskSpecError):
            TaskSpec.from_dict({"id": "x"})  # missing required fields
        with self.assertRaises(TaskSpecError):
            TaskSpec.from_dict({
                "id": "x", "version": "1.0.0", "site": "nope", "title": "t",
                "goal": "g", "seed": 1, "max_steps": 5, "start_url": "/",
                "allowed_actions": ["done"], "allowed_prefixes": ["/"],
                "success": [{"type": "state_equals", "path": "a", "value": 1}],
            })

    def test_yaml_subset_parser(self):
        data = yaml_parse("a: 1\nb:\n  - x\n  - y: 2\n    z: true\nc: 'quoted'\n")
        self.assertEqual(data, {"a": 1, "b": ["x", {"y": 2, "z": True}],
                                "c": "quoted"})
        with self.assertRaises(YamlMiniError):
            yaml_parse("not a mapping at all")


class TestDomParser(unittest.TestCase):
    def test_links_forms_text(self):
        html_doc = ("<html><head><title>Shop</title></head><body>"
                    "<a href='/shop/product/p1'>Widget Alpha</a>"
                    "<form action='/shop/cart/add' method='post'>"
                    "<input type='hidden' name='product' value='p1'>"
                    "<input name='quantity' type='number' value='1'>"
                    "<input type='submit' value='Add to cart'></form>"
                    "</body></html>")
        snap = parse_html(html_doc, "http://x/shop/")
        self.assertEqual(snap["title"], "Shop")
        self.assertEqual(snap["links"], [{"text": "Widget Alpha", "href": "/shop/product/p1"}])
        self.assertEqual(len(snap["forms"]), 1)
        form = snap["forms"][0]
        self.assertEqual(form["action"], "/shop/cart/add")
        self.assertEqual(form["submit"], "Add to cart")
        self.assertIn("quantity", [f["name"] for f in form["fields"]])


class TestSites(unittest.TestCase):
    def setUp(self):
        self.server = make_server()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        host, port = self.server.server_address
        self.base = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def _get_state(self, site):
        with urllib.request.urlopen(f"{self.base}/__state__?site={site}") as resp:
            return json.loads(resp.read())

    def _reset(self, site, seed=1):
        data = urllib.parse.urlencode({"site": site, "seed": str(seed)}).encode()
        req = urllib.request.Request(f"{self.base}/__reset__", data=data, method="POST")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def test_reset_restores_starting_state_exactly(self):
        before = self._get_state("shop")
        # Mutate state through the site itself.
        data = urllib.parse.urlencode({"product": "p1", "quantity": "2"}).encode()
        req = urllib.request.Request(f"{self.base}/shop/cart/add", data=data, method="POST")
        urllib.request.urlopen(req)
        mutated = self._get_state("shop")
        self.assertNotEqual(mutated["cart"], before["cart"])
        self._reset("shop")
        after = self._get_state("shop")
        self.assertEqual(after, before)

    def test_shop_pages_serve(self):
        with urllib.request.urlopen(f"{self.base}/shop/") as resp:
            body = resp.read().decode()
        self.assertIn("Widget Alpha", body)
        self.assertIn("Search products", body)


class TestEvaluator(unittest.TestCase):
    def test_wrong_final_state_fails(self):
        task = _load("shop-add-to-cart")
        fresh = {"cart": {}, "products": [
            {"id": "p1", "name": "Widget Alpha", "price": 19.99}]}
        result = evaluate(task, fresh)
        self.assertFalse(result["success"])
        self.assertEqual(result["partial"], 0.0)

    def test_correct_final_state_passes(self):
        task = _load("shop-add-to-cart")
        state = {"cart": {"p1": 1}, "products": [
            {"id": "p1", "name": "Widget Alpha", "price": 19.99}]}
        result = evaluate(task, state)
        self.assertTrue(result["success"])
        self.assertEqual(result["partial"], 1.0)

    def test_unknown_condition_fails_safe(self):
        passed, _ = evaluate_condition({"type": "nope"}, {})
        self.assertFalse(passed)


class TestRunner(unittest.TestCase):
    def test_scripted_agent_passes_task(self):
        task = _load("shop-add-to-cart")
        agent = load_agent("scripted")
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_suite([task], agent, tmp)
        self.assertEqual(summary["tasks_passed"], 1)
        self.assertEqual(summary["success_rate"], 1.0)

    def test_random_agent_runs_without_crashing(self):
        task = _load("crm-create-lead")
        agent = load_agent("random")
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_suite([task], agent, tmp)
        self.assertEqual(summary["tasks_run"], 1)

    def test_unsafe_action_blocked_and_counted(self):
        task = _load("shop-add-to-cart")
        agent = MaliciousAgent()
        server = make_server()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        host, port = server.server_address
        base = f"http://{host}:{port}"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                result = run_task(task, agent, base,
                                  os.path.join(tmp, "run"))
        finally:
            server.shutdown()
            server.server_close()
        self.assertGreaterEqual(result["metrics"]["unsafe_attempts"], 1)
        self.assertIn("harness endpoint blocked",
                      " ".join(result["metrics"]["blocked_reasons"]))
        self.assertFalse(result["evaluation"]["success"])

    def test_replay_reproduces_result(self):
        task = _load("support-open-ticket")
        agent = load_agent("scripted")
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_suite([task], agent, tmp)
            self.assertEqual(summary["tasks_passed"], 1)
            run_dir = os.path.join(tmp, task.id)
            replayed = replay_run(run_dir, TASKS_DIR)
        self.assertTrue(replayed["match"])
        self.assertTrue(replayed["replayed_success"])

    def test_full_suite_scripted_passes_all(self):
        tasks = load_tasks(TASKS_DIR)
        agent = load_agent("scripted")
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_suite(tasks, agent, tmp)
        self.assertEqual(summary["tasks_run"], 18)
        self.assertEqual(summary["tasks_passed"], 18)
        self.assertEqual(summary["total_unsafe_attempts"], 0)


class TestAdapters(unittest.TestCase):
    def test_load_agent_file(self):
        path = os.path.join(ROOT, "agents", "random_agent.py")
        agent = load_agent(path)
        self.assertEqual(agent.name, "random-agent")

    def test_unknown_agent_spec_rejected(self):
        from browserbench.adapter import AgentError
        with self.assertRaises(AgentError):
            load_agent("does-not-exist")


if __name__ == "__main__":
    unittest.main()
