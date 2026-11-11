"""Deterministic, state-based evaluator.

Scoring inspects the final application state only — never an LLM judge.
Each success condition in a task spec is checked independently, so a run
gets partial credit (fraction of conditions satisfied) as well as a
pass/fail verdict. LLM judging is a clearly marked secondary metric and
is NOT implemented here; if added later it must be reported separately
and must never change the core score.

Condition types (``{"type": ..., ...}``):
- cart_contains       {product, quantity}            — shop cart
- order_exists        {product, customer?}           — a placed order
- lead_exists         {name, email?, company?}       — CRM lead
- lead_field          {name, field, value}           — lead attribute
- lead_note_contains  {name, text}                   — note on a lead
- appointment_exists  {slot, name?}                  — booked appointment
- appointment_absent  {id}                           — appointment gone/cancelled
- ticket_exists       {subject, status?}             — support ticket
- ticket_field        {id, field, value}             — ticket attribute
- ticket_reply_contains {id, text}                   — reply on a ticket
- state_equals        {path, value}                  — dotted path into state
"""

from __future__ import annotations


def _find(collection, **match):
    for item in collection:
        if all(item.get(k) == v for k, v in match.items()):
            return item
    return None


def _state_path(state: dict, path: str):
    current = state
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            return None, False
    return current, True


def evaluate_condition(condition: dict, state: dict) -> tuple[bool, str]:
    """Return (passed, explanation) for one condition against site state."""
    ctype = condition.get("type")
    site = state.get("_site")
    if ctype == "cart_contains":
        cart = state.get("cart", {})
        products = {p["id"]: p for p in state.get("products", [])}
        pid = next((p["id"] for p in state.get("products", [])
                    if p["name"] == condition["product"]), None)
        qty = cart.get(pid, 0) if pid else 0
        want = int(condition.get("quantity", 1))
        return qty >= want, f"cart has {qty} × {condition['product']} (want {want})"
    if ctype == "order_exists":
        for order in state.get("orders", []):
            products = {p["id"]: p for p in state.get("products", [])}
            names = [products[pid]["name"] for pid in order.get("items", {})]
            if condition["product"] in names:
                if "customer" in condition and order.get("customer") != condition["customer"]:
                    continue
                return True, f"order #{order['id']} for {condition['product']} exists"
        return False, f"no order for {condition['product']} found"
    if ctype == "lead_exists":
        lead = _find(state.get("leads", []), name=condition["name"])
        if lead is None:
            return False, f"no lead named {condition['name']}"
        for key in ("email", "company", "status"):
            if key in condition and lead.get(key) != condition[key]:
                return False, f"lead {condition['name']} has {key}={lead.get(key)!r}"
        return True, f"lead {condition['name']} exists"
    if ctype == "lead_field":
        lead = _find(state.get("leads", []), name=condition["name"])
        if lead is None:
            return False, f"no lead named {condition['name']}"
        ok = lead.get(condition["field"]) == condition["value"]
        return ok, (f"lead {condition['name']} {condition['field']}="
                    f"{lead.get(condition['field'])!r} (want {condition['value']!r})")
    if ctype == "lead_note_contains":
        lead = _find(state.get("leads", []), name=condition["name"])
        if lead is None:
            return False, f"no lead named {condition['name']}"
        hit = any(condition["text"] in note for note in lead.get("notes", []))
        return hit, f"lead {condition['name']} notes contain {condition['text']!r}: {hit}"
    if ctype == "appointment_exists":
        for appt in state.get("appointments", []):
            if appt.get("slot") == condition["slot"] and appt.get("status") == "booked":
                if "name" in condition and appt.get("name") != condition["name"]:
                    continue
                return True, f"appointment at {condition['slot']} exists"
        return False, f"no booked appointment at {condition['slot']}"
    if ctype == "appointment_absent":
        appt = _find(state.get("appointments", []), id=condition["id"])
        gone = appt is None or appt.get("status") != "booked"
        return gone, f"appointment {condition['id']} booked: {not gone}"
    if ctype == "ticket_exists":
        ticket = _find(state.get("tickets", []), subject=condition["subject"])
        if ticket is None:
            return False, f"no ticket {condition['subject']!r}"
        if "status" in condition and ticket.get("status") != condition["status"]:
            return False, f"ticket status is {ticket.get('status')!r}"
        return True, f"ticket {condition['subject']!r} exists"
    if ctype == "ticket_field":
        ticket = _find(state.get("tickets", []), id=condition["id"])
        if ticket is None:
            return False, f"no ticket #{condition['id']}"
        ok = ticket.get(condition["field"]) == condition["value"]
        return ok, (f"ticket #{condition['id']} {condition['field']}="
                    f"{ticket.get(condition['field'])!r} (want {condition['value']!r})")
    if ctype == "ticket_reply_contains":
        ticket = _find(state.get("tickets", []), id=condition["id"])
        if ticket is None:
            return False, f"no ticket #{condition['id']}"
        hit = any(condition["text"] in r for r in ticket.get("replies", []))
        return hit, f"ticket #{condition['id']} replies contain {condition['text']!r}: {hit}"
    if ctype == "state_equals":
        value, found = _state_path(state, condition["path"])
        if not found:
            return False, f"path {condition['path']} not found in state"
        return value == condition["value"], f"{condition['path']}={value!r}"
    return False, f"unknown condition type: {ctype!r}"


CONDITIONS = (
    "cart_contains", "order_exists", "lead_exists", "lead_field",
    "lead_note_contains", "appointment_exists", "appointment_absent",
    "ticket_exists", "ticket_field", "ticket_reply_contains", "state_equals",
)


def evaluate(task, state: dict) -> dict:
    """Score a task against final site state. Returns the result dict."""
    tagged = dict(state)
    tagged["_site"] = task.site
    results = []
    for cond in task.success:
        passed, explanation = evaluate_condition(cond, tagged)
        results.append({"condition": cond, "passed": passed,
                        "explanation": explanation})
    passed_count = sum(1 for r in results if r["passed"])
    return {
        "success": passed_count == len(results) and len(results) > 0,
        "partial": passed_count / len(results) if results else 0.0,
        "passed": passed_count,
        "total": len(results),
        "conditions": results,
    }
