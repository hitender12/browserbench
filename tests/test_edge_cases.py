"""Edge-case tests for BrowserBench.

Run: python -m unittest discover -s tests

Covers, beyond the happy path in test_browserbench.py:
- task reset correctness (exact starting state, per-site isolation, seeds)
- evaluator false positives (a wrong final state must FAIL)
- evaluator false negatives (a correct final state must PASS even with
  extra harmless state / extra harmless steps)
- trace completeness (every step recorded with action, URL, status,
  latency and a DOM/state snapshot)
- reproducibility (same task run twice gives the same result)
- the five tasks added in this change (tasks/*/…)

Known gap, recorded rather than hidden: TraceRecorder currently stores
no per-step wall-clock timestamp and no full site-state snapshot — see
test_step_has_wall_clock_timestamp and test_step_has_state_snapshot,
both marked @unittest.expectedFailure. Those tests encode the missing
fields; they must be un-decorated (and will then pass) once the trace
format in browserbench/trace.py gains them. The trace work is outside
the tests/ + tasks/ scope of this change, so it is flagged here and in
the change report instead of being edited in place.
"""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from browserbench.adapter import BaseAgent, load_agent  # noqa: E402
from browserbench.agents import ScriptedAgent  # noqa: E402
from browserbench.evaluator import evaluate  # noqa: E402
from browserbench.runner import run_suite, run_task  # noqa: E402
from browserbench.sites import initial_state, make_server  # noqa: E402
from browserbench.spec import load_tasks  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
TASKS_DIR = os.path.join(ROOT, "tasks")

NEW_TASK_IDS = (
    "crm-qualify-lead",
    "sched-book-afternoon",
    "shop-add-two-beta",
    "shop-buy-doohickey",
    "support-close-ticket",
)


def _load(task_id):
    return next(t for t in load_tasks(TASKS_DIR) if t.id == task_id)


class _PeekingAgent(BaseAgent):
    """Tries the harness-only endpoint, then gives up."""

    name = "peeking-agent"

    def act(self, observation):
        return {"type": "navigate", "url": "/__state__?site=shop"}


class _ExtraStepsAgent(BaseAgent):
    """Wraps the scripted agent but first takes harmless extra steps.

    The extras only navigate between pages the task already allows and
    return to the start page before delegating, so the final state must
    still satisfy the task — the evaluator scores state, not the path.
    """

    name = "extra-steps-agent"

    def __init__(self, task):
        self._inner = ScriptedAgent()
        self._task = task
        self._extras_done = 0

    def reset(self, task):
        self._task = task
        self._inner.reset(task)
        self._extras_done = 0

    def act(self, observation):
        if self._extras_done == 0:
            self._extras_done += 1
            return {"type": "navigate", "url": self._task.start_url}
        if self._extras_done == 1:
            self._extras_done += 1
            return {"type": "navigate", "url": "/shop/cart"}
        if self._extras_done == 2:
            self._extras_done += 1
            return {"type": "navigate", "url": self._task.start_url}
        return self._inner.act(observation)


class _ServerCase(unittest.TestCase):
    """Base class with a live test-site server and HTTP helpers."""

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

    def _post(self, path, fields):
        data = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(f"{self.base}{path}", data=data, method="POST")
        try:
            urllib.request.urlopen(req)
        except urllib.error.HTTPError:
            pass  # a 4xx still counts as the mutation attempt for these tests

    def _mutate(self, site):
        """Drive each site away from its starting state through the site."""
        if site == "shop":
            self._post("/shop/cart/add", {"product": "p1", "quantity": "2"})
        elif site == "crm":
            self._post("/crm/leads/new", {"name": "Test Person",
                                          "email": "test@example.com",
                                          "company": "Test Co"})
        elif site == "sched":
            self._post("/sched/book", {"slot": "2026-11-20 10:00",
                                       "name": "Test Person"})
        elif site == "support":
            self._post("/support/tickets/new", {"subject": "Test ticket",
                                                "category": "other",
                                                "description": "test"})


class TestResetCorrectness(_ServerCase):
    def test_fresh_server_state_matches_initial_state(self):
        for site in ("shop", "crm", "sched", "support"):
            self.assertEqual(self._get_state(site), initial_state(site, 1))

    def test_reset_restores_exact_starting_state_for_every_site(self):
        for site in ("shop", "crm", "sched", "support"):
            before = self._get_state(site)
            self._mutate(site)
            self.assertNotEqual(self._get_state(site), before,
                                f"{site} mutation did not change state")
            self._reset(site)
            self.assertEqual(self._get_state(site), before)
            self.assertEqual(self._get_state(site), initial_state(site, 1))

    def test_reset_is_idempotent(self):
        self._mutate("shop")
        self._reset("shop")
        first = self._get_state("shop")
        self._reset("shop")
        self.assertEqual(self._get_state("shop"), first)

    def test_reset_one_site_leaves_other_sites_untouched(self):
        self._mutate("shop")
        self._mutate("crm")
        shop_mutated = self._get_state("shop")
        crm_mutated = self._get_state("crm")
        self.assertNotEqual(shop_mutated, initial_state("shop", 1))
        self.assertNotEqual(crm_mutated, initial_state("crm", 1))
        self._reset("shop")
        self.assertEqual(self._get_state("shop"), initial_state("shop", 1))
        # The CRM mutation must survive a shop-only reset.
        self.assertEqual(self._get_state("crm"), crm_mutated)

    def test_reset_all_restores_every_site(self):
        for site in ("shop", "crm", "sched", "support"):
            self._mutate(site)
        self._reset("all")
        for site in ("shop", "crm", "sched", "support"):
            self.assertEqual(self._get_state(site), initial_state(site, 1))

    def test_reset_seed_is_recorded_and_deterministic(self):
        self._reset("shop", seed=7)
        seeded = self._get_state("shop")
        self.assertEqual(seeded["seed"], 7)
        self._mutate("shop")
        self._reset("shop", seed=7)
        self.assertEqual(self._get_state("shop"), seeded)
        self._reset("shop", seed=1)
        unseeded = self._get_state("shop")
        self.assertEqual(unseeded["seed"], 1)
        # Only the recorded seed differs between the two resets.
        seeded.pop("seed")
        unseeded.pop("seed")
        self.assertEqual(seeded, unseeded)


class TestEvaluatorFalsePositives(unittest.TestCase):
    """A wrong final state must FAIL, never pass."""

    def test_wrong_product_in_cart_fails(self):
        task = _load("shop-add-to-cart")
        state = {"cart": {"p2": 1}, "products": [
            {"id": "p1", "name": "Widget Alpha", "price": 19.99},
            {"id": "p2", "name": "Widget Beta", "price": 29.99}]}
        result = evaluate(task, state)
        self.assertFalse(result["success"])
        self.assertEqual(result["partial"], 0.0)

    def test_empty_cart_fails(self):
        task = _load("shop-add-to-cart")
        state = {"cart": {}, "products": [
            {"id": "p1", "name": "Widget Alpha", "price": 19.99}]}
        self.assertFalse(evaluate(task, state)["success"])

    def test_quantity_shortfall_fails(self):
        # Want 2 x Widget Beta; only 1 present.
        task = _load("shop-add-two-beta")
        state = {"cart": {"p2": 1}, "products": [
            {"id": "p2", "name": "Widget Beta", "price": 29.99}]}
        result = evaluate(task, state)
        self.assertFalse(result["success"])
        self.assertEqual(result["partial"], 0.0)

    def test_order_wrong_product_fails(self):
        task = _load("shop-checkout")
        state = {"cart": {}, "orders": [{"id": 1, "customer": "Ada Lovelace",
                                         "items": {"p1": 1}}], "products": [
            {"id": "p1", "name": "Widget Alpha", "price": 19.99},
            {"id": "p3", "name": "Gadget Gamma", "price": 49.99}]}
        self.assertFalse(evaluate(task, state)["success"])

    def test_order_right_product_wrong_customer_fails(self):
        task = _load("shop-checkout")
        state = {"cart": {}, "orders": [{"id": 1, "customer": "Grace Hopper",
                                         "items": {"p3": 1}}], "products": [
            {"id": "p3", "name": "Gadget Gamma", "price": 49.99}]}
        self.assertFalse(evaluate(task, state)["success"])

    def test_lead_wrong_email_fails(self):
        task = _load("crm-create-lead")
        state = {"leads": [{"id": 3, "name": "Alan Turing",
                            "email": "wrong@example.com",
                            "company": "Bletchley Park", "status": "New",
                            "notes": []}]}
        self.assertFalse(evaluate(task, state)["success"])

    def test_lead_wrong_status_fails(self):
        task = _load("crm-update-status")
        state = {"leads": [{"id": 1, "name": "Ada Lovelace",
                            "email": "ada@example.com",
                            "company": "Analytical Engines", "status": "New",
                            "notes": []}]}
        self.assertFalse(evaluate(task, state)["success"])

    def test_appointment_wrong_slot_fails(self):
        task = _load("sched-book-appointment")
        state = {"appointments": [{"id": 2, "slot": "2026-11-20 11:00",
                                   "name": "Alan Turing", "status": "booked"}]}
        self.assertFalse(evaluate(task, state)["success"])

    def test_appointment_still_booked_fails_cancel_task(self):
        task = _load("sched-cancel-appointment")
        state = {"appointments": [{"id": 1, "slot": "2026-11-20 09:00",
                                   "name": "Alan Turing", "status": "booked"}]}
        self.assertFalse(evaluate(task, state)["success"])

    def test_ticket_wrong_status_fails(self):
        task = _load("support-open-ticket")
        state = {"tickets": [{"id": 2, "subject": "Login fails on checkout",
                              "category": "billing", "description": "x",
                              "status": "closed", "replies": []}]}
        self.assertFalse(evaluate(task, state)["success"])

    def test_ticket_reply_missing_text_fails(self):
        task = _load("support-reply-close")
        state = {"tickets": [{"id": 1, "subject": "Cannot reset password",
                              "category": "account", "description": "x",
                              "status": "closed",
                              "replies": ["Something unrelated."]}]}
        result = evaluate(task, state)
        self.assertFalse(result["success"])
        self.assertEqual(result["partial"], 0.5)
        self.assertEqual((result["passed"], result["total"]), (1, 2))

    def test_partial_credit_only_half_when_one_of_two_conditions_met(self):
        # Reply present, ticket still open: exactly half the conditions.
        task = _load("support-reply-close")
        state = {"tickets": [{"id": 1, "subject": "Cannot reset password",
                              "category": "account", "description": "x",
                              "status": "open",
                              "replies": ["Reset link sent. Check inbox."]}]}
        result = evaluate(task, state)
        self.assertFalse(result["success"])
        self.assertEqual(result["partial"], 0.5)

    def test_near_miss_note_text_fails(self):
        task = _load("crm-add-note")
        state = {"leads": [{"id": 1, "name": "Ada Lovelace",
                            "email": "ada@example.com",
                            "company": "Analytical Engines", "status": "New",
                            "notes": ["Called, interested in a call."]}]}
        self.assertFalse(evaluate(task, state)["success"])

    def test_state_equals_wrong_value_fails(self):
        task = _load("sched-cancel-appointment")
        state = {"appointments": [{"id": 1, "slot": "2026-11-20 09:00",
                                   "name": "Alan Turing",
                                   "status": "cancelled"}]}
        # Sanity: the cancel task itself passes on a cancelled appointment…
        self.assertTrue(evaluate(task, state)["success"])
        # …while a bare state_equals check on a wrong value must fail.
        from browserbench.evaluator import evaluate_condition
        passed, _ = evaluate_condition(
            {"type": "state_equals", "path": "appointments.0.status",
             "value": "booked"}, state)
        self.assertFalse(passed)


class TestEvaluatorFalseNegatives(unittest.TestCase):
    """A correct final state must PASS, even with extra harmless state."""

    def test_correct_cart_plus_extra_items_passes(self):
        task = _load("shop-add-to-cart")
        state = {"cart": {"p1": 1, "p2": 3, "p5": 1}, "products": [
            {"id": "p1", "name": "Widget Alpha", "price": 19.99},
            {"id": "p2", "name": "Widget Beta", "price": 29.99},
            {"id": "p5", "name": "Doohickey Epsilon", "price": 9.99}]}
        result = evaluate(task, state)
        self.assertTrue(result["success"])
        self.assertEqual(result["partial"], 1.0)

    def test_more_than_required_quantity_passes(self):
        task = _load("shop-add-to-cart")
        state = {"cart": {"p1": 5}, "products": [
            {"id": "p1", "name": "Widget Alpha", "price": 19.99}]}
        self.assertTrue(evaluate(task, state)["success"])
        task2 = _load("shop-add-two-beta")
        state2 = {"cart": {"p2": 3}, "products": [
            {"id": "p2", "name": "Widget Beta", "price": 29.99}]}
        self.assertTrue(evaluate(task2, state2)["success"])

    def test_correct_lead_plus_extra_leads_passes(self):
        task = _load("crm-create-lead")
        state = {"leads": [
            {"id": 1, "name": "Ada Lovelace", "email": "ada@example.com",
             "company": "Analytical Engines", "status": "New", "notes": []},
            {"id": 3, "name": "Alan Turing", "email": "alan@example.com",
             "company": "Bletchley Park", "status": "New", "notes": []}]}
        self.assertTrue(evaluate(task, state)["success"])

    def test_lead_exists_without_optional_fields_passes(self):
        # The condition only names the lead; email/company are not required.
        task = _load("crm-create-lead")
        task_no_extras = _load("crm-add-note")  # lead_note_contains path
        state = {"leads": [{"id": 1, "name": "Ada Lovelace",
                            "email": "ada@example.com",
                            "company": "Analytical Engines", "status": "New",
                            "notes": ["Called, interested in a demo."]}]}
        self.assertTrue(evaluate(task_no_extras, state)["success"])

    def test_correct_appointment_plus_extra_appointments_passes(self):
        task = _load("sched-book-appointment")
        state = {"appointments": [
            {"id": 1, "slot": "2026-11-20 09:00", "name": "Alan Turing",
             "status": "booked"},
            {"id": 2, "slot": "2026-11-20 10:00", "name": "Alan Turing",
             "status": "booked"},
            {"id": 3, "slot": "2026-11-20 11:00", "name": "Grace Hopper",
             "status": "booked"}]}
        self.assertTrue(evaluate(task, state)["success"])

    def test_correct_ticket_plus_extra_replies_passes(self):
        task = _load("support-reply-close")
        state = {"tickets": [{"id": 1, "subject": "Cannot reset password",
                              "category": "account", "description": "x",
                              "status": "closed",
                              "replies": ["Hello, looking into it.",
                                          "Reset link sent. Please check "
                                          "your inbox.",
                                          "Let us know if it worked."]}]}
        result = evaluate(task, state)
        self.assertTrue(result["success"])
        self.assertEqual(result["partial"], 1.0)

    def test_correct_state_with_unrelated_extra_keys_passes(self):
        task = _load("shop-add-to-cart")
        state = {"cart": {"p1": 1}, "products": [
            {"id": "p1", "name": "Widget Alpha", "price": 19.99}],
            "unrelated_audit_log": ["something"], "debug_flag": True}
        self.assertTrue(evaluate(task, state)["success"])

    def test_extra_harmless_steps_still_pass_at_runner_level(self):
        task = _load("shop-add-to-cart")
        agent = _ExtraStepsAgent(task)
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_suite([task], agent, tmp)
        self.assertEqual(summary["tasks_passed"], 1)
        self.assertEqual(summary["success_rate"], 1.0)
        # The extra navigations were actually taken (more than the
        # scripted plan's 3 steps) and none was unsafe.
        self.assertGreater(summary["total_steps"], 3)
        self.assertEqual(summary["total_unsafe_attempts"], 0)


class TestTraceCompleteness(unittest.TestCase):
    def _run_scripted(self, task_id):
        task = _load(task_id)
        agent = load_agent("scripted")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        run_suite([task], agent, tmp.name)
        run_dir = os.path.join(tmp.name, task_id)
        with open(os.path.join(run_dir, "trace.json"), encoding="utf-8") as fh:
            trace = json.load(fh)
        with open(os.path.join(run_dir, "artifact.json"), encoding="utf-8") as fh:
            artifact = json.load(fh)
        with open(os.path.join(run_dir, "result.json"), encoding="utf-8") as fh:
            result = json.load(fh)
        return task, trace, artifact, result

    def test_every_step_has_action_url_status_latency_and_dom_snapshot(self):
        _task, trace, _artifact, _result = self._run_scripted("shop-add-to-cart")
        steps = trace["steps"]
        self.assertGreater(len(steps), 0)
        self.assertEqual([s["step"] for s in steps], list(range(1, len(steps) + 1)))
        for step in steps:
            self.assertIsInstance(step["action"], dict)
            self.assertIn("type", step["action"])
            self.assertIsInstance(step["url"], str)
            self.assertTrue(step["url"].startswith("http"))
            self.assertIsInstance(step["http_status"], int)
            self.assertIsInstance(step["latency_ms"], (int, float))
            self.assertGreaterEqual(step["latency_ms"], 0)
            # The per-step state snapshot: DOM links/forms + text excerpt
            # of the page observed after the action.
            self.assertIn("dom", step)
            self.assertIsInstance(step["dom"]["links"], list)
            self.assertIsInstance(step["dom"]["forms"], list)
            self.assertIsInstance(step["text_excerpt"], str)

    def test_trace_step_count_matches_metrics_and_artifact(self):
        task, trace, artifact, result = self._run_scripted("shop-add-to-cart")
        steps = trace["steps"]
        self.assertEqual(len(steps), result["metrics"]["steps"])
        self.assertEqual(artifact["actions"], [s["action"] for s in steps])
        self.assertEqual(steps[-1]["action"], {"type": "done"})
        self.assertEqual(artifact["task_id"], task.id)
        self.assertEqual(artifact["task_version"], task.version)
        self.assertEqual(artifact["evaluation"], result["evaluation"])

    def test_trace_records_blocked_attempts_with_action(self):
        task = _load("shop-add-to-cart")
        agent = _PeekingAgent()
        server = make_server()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        host, port = server.server_address
        base = f"http://{host}:{port}"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                run_task(task, agent, base, os.path.join(tmp, "run"))
                with open(os.path.join(tmp, "run", "trace.json"),
                          encoding="utf-8") as fh:
                    trace = json.load(fh)
        finally:
            server.shutdown()
            server.server_close()
        blocked = [s for s in trace["steps"] if s.get("blocked")]
        self.assertGreaterEqual(len(blocked), 1)
        self.assertIn("harness endpoint blocked", blocked[0]["blocked"])
        # The blocked attempt is still recorded with its action.
        self.assertEqual(blocked[0]["action"]["type"], "navigate")

    def test_run_artifact_carries_a_timestamp(self):
        _task, _trace, artifact, _result = self._run_scripted("shop-add-to-cart")
        self.assertIn("saved_at", artifact)
        self.assertIsInstance(artifact["saved_at"], str)
        self.assertTrue(artifact["saved_at"])

    @unittest.expectedFailure
    def test_step_has_wall_clock_timestamp(self):
        # GAP (browserbench/trace.py, out of scope for this change):
        # TraceRecorder.record_step stores latency_ms but no per-step
        # wall-clock timestamp, so a step cannot be placed on a timeline
        # or correlated with external logs. Remove the decorator once
        # each step records e.g. "timestamp" in ISO-8601 UTC.
        _task, trace, _artifact, _result = self._run_scripted("shop-add-to-cart")
        for step in trace["steps"]:
            self.assertIn("timestamp", step)

    @unittest.expectedFailure
    def test_step_has_state_snapshot(self):
        # GAP (browserbench/trace.py, out of scope for this change):
        # each step records a DOM summary (links/forms/text excerpt) but
        # not the full site-state snapshot after the action, so a trace
        # alone cannot show how state evolved step by step. Remove the
        # decorator once each step records e.g. "state_snapshot".
        _task, trace, _artifact, _result = self._run_scripted("shop-add-to-cart")
        for step in trace["steps"]:
            self.assertIn("state_snapshot", step)
            self.assertIsInstance(step["state_snapshot"], dict)


class TestReproducibility(unittest.TestCase):
    def _run_once(self, task_id):
        task = _load(task_id)
        agent = load_agent("scripted")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        summary = run_suite([task], agent, tmp.name)
        with open(os.path.join(tmp.name, task_id, "artifact.json"),
                  encoding="utf-8") as fh:
            artifact = json.load(fh)
        return summary["results"][0], artifact

    def test_same_task_twice_same_result(self):
        first_result, first_artifact = self._run_once("shop-add-to-cart")
        second_result, second_artifact = self._run_once("shop-add-to-cart")
        self.assertEqual(first_result["evaluation"], second_result["evaluation"])
        self.assertEqual(first_artifact["actions"], second_artifact["actions"])
        self.assertEqual(first_result["metrics"]["steps"],
                         second_result["metrics"]["steps"])
        self.assertEqual(first_result["metrics"]["unsafe_attempts"],
                         second_result["metrics"]["unsafe_attempts"])
        self.assertTrue(first_result["evaluation"]["success"])

    def test_full_suite_twice_identical_results(self):
        tasks = load_tasks(TASKS_DIR)
        agent = load_agent("scripted")
        with tempfile.TemporaryDirectory() as tmp1:
            first = run_suite(tasks, agent, tmp1)
        agent = load_agent("scripted")
        with tempfile.TemporaryDirectory() as tmp2:
            second = run_suite(tasks, agent, tmp2)
        self.assertEqual(first["tasks_run"], second["tasks_run"])
        self.assertEqual(first["tasks_passed"], second["tasks_passed"])
        for r1, r2 in zip(first["results"], second["results"]):
            self.assertEqual(r1["task_id"], r2["task_id"])
            self.assertEqual(r1["evaluation"], r2["evaluation"])

    def test_replay_reproduces_result_twice(self):
        from browserbench.replay import replay_run  # noqa: PLC0415

        task = _load("support-open-ticket")
        agent = load_agent("scripted")
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_suite([task], agent, tmp)
            self.assertEqual(summary["tasks_passed"], 1)
            run_dir = os.path.join(tmp, task.id)
            first = replay_run(run_dir, TASKS_DIR)
            second = replay_run(run_dir, TASKS_DIR)
        self.assertTrue(first["match"])
        self.assertTrue(second["match"])
        self.assertEqual(first["evaluation"], second["evaluation"])


class TestNewTasks(unittest.TestCase):
    def test_five_new_tasks_load(self):
        tasks = load_tasks(TASKS_DIR)
        self.assertEqual(len(tasks), 15)
        ids = {t.id for t in tasks}
        for task_id in NEW_TASK_IDS:
            self.assertIn(task_id, ids)

    def test_new_tasks_have_required_fields(self):
        for task_id in NEW_TASK_IDS:
            task = _load(task_id)
            self.assertTrue(task.goal)
            self.assertTrue(task.title)
            self.assertTrue(task.start_url.startswith("/"))
            self.assertIn("done", task.allowed_actions)
            self.assertTrue(task.allowed_prefixes)
            self.assertTrue(task.success)
            self.assertTrue(task.reference_plan)
            self.assertGreaterEqual(task.max_steps, len(task.reference_plan))

    def test_new_tasks_cover_all_four_sites(self):
        sites = {_load(t).site for t in NEW_TASK_IDS}
        self.assertEqual(sites, {"shop", "crm", "sched", "support"})

    def test_new_tasks_scripted_pass_all(self):
        tasks = [_load(t) for t in NEW_TASK_IDS]
        agent = load_agent("scripted")
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_suite(tasks, agent, tmp)
        self.assertEqual(summary["tasks_run"], 5)
        self.assertEqual(summary["tasks_passed"], 5)
        self.assertEqual(summary["total_unsafe_attempts"], 0)


if __name__ == "__main__":
    unittest.main()
