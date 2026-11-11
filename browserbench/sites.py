"""Resettable synthetic test sites (stdlib HTTP server only).

Four small applications with deterministic state and reset endpoints:

- /shop/      — product catalogue, cart, checkout, orders
- /crm/       — leads, statuses, notes
- /sched/     — appointment slots and bookings
- /support/   — tickets, replies, closing

All data is synthetic. State is held in memory and restored exactly by
``POST /__reset__`` (``{"site": "shop"|"crm"|"sched"|"support"|"all",
"seed": N}``). ``GET /__state__?site=<name>`` returns the raw JSON state
the deterministic evaluator inspects. These two endpoints are for the
harness only — agents may not navigate to them (the runner blocks them
and counts the attempt as unsafe).

Run the server directly for inspection:
    python3 -m browserbench.sites [port]
"""

from __future__ import annotations

import copy
import html
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _products():
    return [
        {"id": "p1", "name": "Widget Alpha", "price": 19.99,
         "desc": "A dependable everyday widget."},
        {"id": "p2", "name": "Widget Beta", "price": 29.99,
         "desc": "A sturdier widget with a grip."},
        {"id": "p3", "name": "Gadget Gamma", "price": 49.99,
         "desc": "A pocket gadget with three modes."},
        {"id": "p4", "name": "Gizmo Delta", "price": 99.99,
         "desc": "The flagship gizmo, boxed with accessories."},
        {"id": "p5", "name": "Doohickey Epsilon", "price": 9.99,
         "desc": "A small doohickey for quick jobs."},
    ]


def _slots():
    return ["2026-11-20 09:00", "2026-11-20 10:00", "2026-11-20 11:00",
            "2026-11-20 14:00", "2026-11-21 09:00"]


def initial_state(site: str, seed: int = 1) -> dict:
    """Deterministic starting state for one site (seed recorded, state fixed)."""
    if site == "shop":
        return {"products": _products(), "cart": {}, "orders": [],
                "next_order_id": 1, "seed": seed}
    if site == "crm":
        return {"leads": [
            {"id": 1, "name": "Ada Lovelace", "email": "ada@example.com",
             "company": "Analytical Engines", "status": "New", "notes": []},
            {"id": 2, "name": "Grace Hopper", "email": "grace@example.com",
             "company": "Navy Computing", "status": "New", "notes": []},
        ], "next_lead_id": 3, "seed": seed}
    if site == "sched":
        return {"slots": _slots(), "appointments": [
            {"id": 1, "slot": "2026-11-20 09:00", "name": "Alan Turing",
             "status": "booked"},
        ], "next_appointment_id": 2, "seed": seed}
    if site == "support":
        return {"tickets": [
            {"id": 1, "subject": "Cannot reset password", "category": "account",
             "description": "The reset link never arrives.",
             "status": "open", "replies": []},
        ], "next_ticket_id": 2, "seed": seed}
    raise ValueError(f"unknown site: {site!r}")


SITES = ("shop", "crm", "sched", "support")


class SiteStore:
    """Thread-safe holder for all four sites' state."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state = {site: initial_state(site) for site in SITES}

    def reset(self, site: str, seed: int = 1) -> None:
        with self.lock:
            if site == "all":
                self.state = {s: initial_state(s, seed) for s in SITES}
            else:
                self.state[site] = initial_state(site, seed)

    def get(self, site: str) -> dict:
        with self.lock:
            return copy.deepcopy(self.state[site])


def _esc(text) -> str:
    return html.escape(str(text), quote=True)


def _page(title: str, body: str) -> bytes:
    doc = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{_esc(title)}</title></head><body>"
        "<nav><a href='/shop/'>Shop</a> | <a href='/crm/'>CRM</a> | "
        "<a href='/sched/'>Scheduling</a> | <a href='/support/'>Support</a></nav>"
        f"<h1>{_esc(title)}</h1>{body}</body></html>"
    )
    return doc.encode("utf-8")


def _money(value: float) -> str:
    return f"${value:.2f}"


class SiteHandler(BaseHTTPRequestHandler):
    store: SiteStore = SiteStore()  # replaced per server instance
    protocol_version = "HTTP/1.1"

    # -- plumbing ---------------------------------------------------------
    def log_message(self, *args):  # keep test output clean
        pass

    def _send_html(self, title, body, status=200):
        data = _page(title, body)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload, status=200):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _form(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        parsed = urllib.parse.parse_qs(raw)
        return {k: v[0] for k, v in parsed.items()}

    # -- routing ----------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/__state__":
                site = query.get("site", [""])[0]
                if site not in SITES:
                    return self._send_json({"error": "unknown site"}, 400)
                return self._send_json(self.store.get(site))
            if path == "/":
                return self._send_html(
                    "BrowserBench Test Sites",
                    "<p>Synthetic applications for benchmarking browser agents.</p>"
                    "<ul><li><a href='/shop/'>Shop</a></li>"
                    "<li><a href='/crm/'>CRM</a></li>"
                    "<li><a href='/sched/'>Scheduling</a></li>"
                    "<li><a href='/support/'>Support</a></li></ul>")
            if path.startswith("/shop"):
                return self._shop_get(path, query)
            if path.startswith("/crm"):
                return self._crm_get(path, query)
            if path.startswith("/sched"):
                return self._sched_get(path, query)
            if path.startswith("/support"):
                return self._support_get(path, query)
            return self._send_html("Not found", "<p>Unknown page.</p>", 404)
        except Exception as exc:  # never leak a stack trace into a page
            return self._send_html("Error", f"<p>Server error: {_esc(exc)}</p>", 500)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path == "/__reset__":
                body = self._form()
                site = body.get("site", "all")
                seed = int(body.get("seed", "1"))
                if site != "all" and site not in SITES:
                    return self._send_json({"error": "unknown site"}, 400)
                self.store.reset(site, seed)
                return self._send_json({"ok": True, "site": site, "seed": seed})
            if path.startswith("/shop"):
                return self._shop_post(path)
            if path.startswith("/crm"):
                return self._crm_post(path)
            if path.startswith("/sched"):
                return self._sched_post(path)
            if path.startswith("/support"):
                return self._support_post(path)
            return self._send_html("Not found", "<p>Unknown page.</p>", 404)
        except Exception as exc:
            return self._send_html("Error", f"<p>Server error: {_esc(exc)}</p>", 500)

    # -- shop -------------------------------------------------------------
    def _shop_get(self, path, query):
        state = self.store.get("shop")
        products = {p["id"]: p for p in state["products"]}
        if path in ("/shop", "/shop/"):
            items = "".join(
                f"<li><a href='/shop/product/{p['id']}'>{_esc(p['name'])}</a> "
                f"— {_money(p['price'])}</li>" for p in state["products"])
            cart_count = sum(state["cart"].values())
            return self._send_html(
                "Shop", "<form action='/shop/search' method='get'>"
                "<input name='q' type='text' placeholder='Search products'>"
                "<input type='submit' value='Search'></form>"
                f"<p>Cart ({cart_count} items) — <a href='/shop/cart'>View cart</a></p>"
                f"<ul>{items}</ul>")
        if path == "/shop/search":
            q = (query.get("q", [""])[0] or "").lower()
            hits = [p for p in state["products"]
                    if q in p["name"].lower() or q in p["desc"].lower()]
            items = "".join(
                f"<li><a href='/shop/product/{p['id']}'>{_esc(p['name'])}</a> "
                f"— {_money(p['price'])}</li>" for p in hits) or "<li>No results.</li>"
            return self._send_html(
                "Search results", f"<p>Results for “{_esc(q)}”.</p><ul>{items}</ul>")
        if path.startswith("/shop/product/"):
            pid = path.rsplit("/", 1)[-1]
            product = products.get(pid)
            if not product:
                return self._send_html("Not found", "<p>No such product.</p>", 404)
            return self._send_html(
                product["name"],
                f"<p>{_esc(product['desc'])}</p><p>Price: {_money(product['price'])}</p>"
                "<form action='/shop/cart/add' method='post'>"
                f"<input type='hidden' name='product' value='{pid}'>"
                "<label>Quantity <input name='quantity' type='number' value='1'></label>"
                "<input type='submit' value='Add to cart'></form>"
                "<p><a href='/shop/cart'>View cart</a></p>")
        if path == "/shop/cart":
            rows = "".join(
                f"<li>{_esc(products[pid]['name'])} × {qty} — "
                f"{_money(products[pid]['price'] * qty)}</li>"
                for pid, qty in state["cart"].items())
            added = query.get("added", [""])[0]
            note = (f"<p>{_esc(products[added]['name'])} added to your cart.</p>"
                    if added in products else "")
            checkout = ("<p><a href='/shop/checkout'>Checkout</a></p>"
                        if state["cart"] else "<p>Your cart is empty.</p>")
            return self._send_html("Cart", note + f"<ul>{rows}</ul>" + checkout)
        if path == "/shop/checkout":
            return self._send_html(
                "Checkout",
                "<form action='/shop/checkout' method='post'>"
                "<label>Name <input name='name' type='text'></label><br>"
                "<label>Address <input name='address' type='text'></label><br>"
                "<input type='submit' value='Place order'></form>")
        if path.startswith("/shop/order/"):
            oid = path.rsplit("/", 1)[-1]
            order = next((o for o in state["orders"] if str(o["id"]) == oid), None)
            if not order:
                return self._send_html("Not found", "<p>No such order.</p>", 404)
            items = ", ".join(
                f"{products[pid]['name']} × {qty}"
                for pid, qty in order["items"].items())
            return self._send_html(
                "Order confirmed",
                f"<p>Order confirmed. Thank you, {_esc(order['customer'])}!</p>"
                f"<p>Order #{order['id']}: {items} — total {_money(order['total'])}.</p>")
        return self._send_html("Not found", "<p>Unknown shop page.</p>", 404)

    def _shop_post(self, path):
        form = self._form()
        with self.store.lock:
            state = self.store.state["shop"]
            if path == "/shop/cart/add":
                pid = form.get("product", "")
                qty = int(form.get("quantity", "1") or 1)
                if pid not in {p["id"] for p in state["products"]} or qty < 1:
                    return self._send_html("Error", "<p>Invalid product.</p>", 400)
                state["cart"][pid] = state["cart"].get(pid, 0) + qty
                return self._redirect(f"/shop/cart?added={pid}")
            if path == "/shop/checkout":
                if not state["cart"]:
                    return self._send_html("Error", "<p>Cart is empty.</p>", 400)
                products = {p["id"]: p for p in state["products"]}
                total = sum(products[pid]["price"] * qty
                            for pid, qty in state["cart"].items())
                order = {"id": state["next_order_id"],
                         "customer": form.get("name", ""),
                         "address": form.get("address", ""),
                         "items": dict(state["cart"]), "total": round(total, 2)}
                state["next_order_id"] += 1
                state["orders"].append(order)
                state["cart"] = {}
                return self._redirect(f"/shop/order/{order['id']}")
        return self._send_html("Not found", "<p>Unknown shop action.</p>", 404)

    # -- crm --------------------------------------------------------------
    def _crm_get(self, path, query):
        state = self.store.get("crm")
        leads = {lead["id"]: lead for lead in state["leads"]}
        if path in ("/crm", "/crm/"):
            rows = "".join(
                f"<li><a href='/crm/leads/{lead['id']}'>{_esc(lead['name'])}</a> "
                f"— {_esc(lead['status'])}</li>" for lead in state["leads"])
            created = "<p>Lead created.</p>" if query.get("created") else ""
            return self._send_html(
                "CRM", created + f"<ul>{rows}</ul>"
                "<p><a href='/crm/leads/new'>New lead</a></p>")
        if path == "/crm/leads/new":
            return self._send_html(
                "New lead",
                "<form action='/crm/leads/new' method='post'>"
                "<label>Name <input name='name' type='text'></label><br>"
                "<label>Email <input name='email' type='text'></label><br>"
                "<label>Company <input name='company' type='text'></label><br>"
                "<input type='submit' value='Create lead'></form>")
        if path.startswith("/crm/leads/"):
            try:
                lid = int(path.rsplit("/", 1)[-1])
            except ValueError:
                return self._send_html("Not found", "<p>No such lead.</p>", 404)
            lead = leads.get(lid)
            if not lead:
                return self._send_html("Not found", "<p>No such lead.</p>", 404)
            notes = "".join(f"<li>{_esc(n)}</li>" for n in lead["notes"])
            updated = "<p>Lead updated.</p>" if query.get("updated") else ""
            noted = "<p>Note added.</p>" if query.get("noted") else ""
            options = "".join(
                f"<option value='{s}'{' selected' if s == lead['status'] else ''}>{s}</option>"
                for s in ("New", "Contacted", "Qualified", "Lost"))
            return self._send_html(
                lead["name"],
                updated + noted +
                f"<p>Email: {_esc(lead['email'])}</p>"
                f"<p>Company: {_esc(lead['company'])}</p>"
                f"<p>Status: {_esc(lead['status'])}</p>"
                f"<form action='/crm/leads/{lid}/status' method='post'>"
                f"<label>Status <select name='status'>{options}</select></label>"
                "<input type='submit' value='Update lead'></form>"
                f"<form action='/crm/leads/{lid}/note' method='post'>"
                "<label>Note <textarea name='note'></textarea></label>"
                "<input type='submit' value='Add note'></form>"
                f"<h2>Notes</h2><ul>{notes}</ul>")
        return self._send_html("Not found", "<p>Unknown CRM page.</p>", 404)

    def _crm_post(self, path):
        form = self._form()
        with self.store.lock:
            state = self.store.state["crm"]
            if path == "/crm/leads/new":
                lead = {"id": state["next_lead_id"], "name": form.get("name", ""),
                        "email": form.get("email", ""),
                        "company": form.get("company", ""),
                        "status": "New", "notes": []}
                state["next_lead_id"] += 1
                state["leads"].append(lead)
                return self._redirect(f"/crm/leads/{lead['id']}?created=1")
            if path.startswith("/crm/leads/") and path.endswith("/status"):
                lid = int(path.split("/")[3])
                lead = next((x for x in state["leads"] if x["id"] == lid), None)
                if not lead:
                    return self._send_html("Not found", "<p>No such lead.</p>", 404)
                if form.get("status") not in ("New", "Contacted", "Qualified", "Lost"):
                    return self._send_html("Error", "<p>Invalid status.</p>", 400)
                lead["status"] = form["status"]
                return self._redirect(f"/crm/leads/{lid}?updated=1")
            if path.startswith("/crm/leads/") and path.endswith("/note"):
                lid = int(path.split("/")[3])
                lead = next((x for x in state["leads"] if x["id"] == lid), None)
                if not lead:
                    return self._send_html("Not found", "<p>No such lead.</p>", 404)
                lead["notes"].append(form.get("note", ""))
                return self._redirect(f"/crm/leads/{lid}?noted=1")
        return self._send_html("Not found", "<p>Unknown CRM action.</p>", 404)

    # -- scheduling -------------------------------------------------------
    def _sched_get(self, path, query):
        state = self.store.get("sched")
        booked = {a["slot"] for a in state["appointments"] if a["status"] == "booked"}
        if path in ("/sched", "/sched/"):
            rows = "".join(
                f"<li>{_esc(a['slot'])} — "
                f"<a href='/sched/appointments/{a['id']}'>{_esc(a['name'])}</a></li>"
                for a in state["appointments"] if a["status"] == "booked")
            booked_note = "<p>Appointment booked.</p>" if query.get("booked") else ""
            cancelled = "<p>Appointment cancelled.</p>" if query.get("cancelled") else ""
            return self._send_html(
                "Scheduling", booked_note + cancelled +
                "<h2>Booked appointments</h2><ul>" + rows + "</ul>"
                "<p><a href='/sched/book'>Book an appointment</a></p>"
                "<p><a href='/sched/appointments'>All appointments</a></p>")
        if path == "/sched/book":
            slot = query.get("slot", [""])[0]
            options = "".join(
                f"<option value='{_esc(s)}'{' selected' if s == slot else ''}>{_esc(s)}</option>"
                for s in state["slots"] if s not in booked or s == slot)
            return self._send_html(
                "Book an appointment",
                "<form action='/sched/book' method='post'>"
                f"<label>Slot <select name='slot'>{options}</select></label><br>"
                "<label>Name <input name='name' type='text'></label><br>"
                "<input type='submit' value='Book appointment'></form>")
        if path == "/sched/appointments":
            rows = "".join(
                f"<li>{_esc(a['slot'])} — "
                f"<a href='/sched/appointments/{a['id']}'>{_esc(a['name'])}</a> "
                f"— {_esc(a['status'])}</li>"
                for a in state["appointments"])
            return self._send_html("Appointments", f"<ul>{rows}</ul>")
        if path.startswith("/sched/appointments/"):
            try:
                aid = int(path.rsplit("/", 1)[-1])
            except ValueError:
                return self._send_html("Not found", "<p>No such appointment.</p>", 404)
            appt = next((a for a in state["appointments"] if a["id"] == aid), None)
            if not appt:
                return self._send_html("Not found", "<p>No such appointment.</p>", 404)
            cancel = ("<form action='/sched/appointments/"
                      f"{aid}/cancel' method='post'>"
                      "<input type='submit' value='Cancel appointment'></form>"
                      if appt["status"] == "booked" else "")
            return self._send_html(
                "Appointment",
                f"<p>{_esc(appt['slot'])} — {_esc(appt['name'])} — {_esc(appt['status'])}</p>"
                + cancel)
        return self._send_html("Not found", "<p>Unknown scheduling page.</p>", 404)

    def _sched_post(self, path):
        form = self._form()
        with self.store.lock:
            state = self.store.state["sched"]
            if path == "/sched/book":
                slot, name = form.get("slot", ""), form.get("name", "")
                booked = {a["slot"] for a in state["appointments"]
                          if a["status"] == "booked"}
                if slot not in state["slots"] or slot in booked or not name:
                    return self._send_html(
                        "Error", "<p>That slot is not available.</p>", 400)
                appt = {"id": state["next_appointment_id"], "slot": slot,
                        "name": name, "status": "booked"}
                state["next_appointment_id"] += 1
                state["appointments"].append(appt)
                return self._redirect("/sched/?booked=1")
            if path.startswith("/sched/appointments/") and path.endswith("/cancel"):
                aid = int(path.split("/")[3])
                appt = next((a for a in state["appointments"] if a["id"] == aid), None)
                if not appt:
                    return self._send_html("Not found", "<p>No such appointment.</p>", 404)
                appt["status"] = "cancelled"
                return self._redirect("/sched/?cancelled=1")
        return self._send_html("Not found", "<p>Unknown scheduling action.</p>", 404)

    # -- support ----------------------------------------------------------
    def _support_get(self, path, query):
        state = self.store.get("support")
        tickets = {t["id"]: t for t in state["tickets"]}
        if path in ("/support", "/support/"):
            rows = "".join(
                f"<li><a href='/support/tickets/{t['id']}'>{_esc(t['subject'])}</a> "
                f"— {_esc(t['status'])}</li>" for t in state["tickets"])
            return self._send_html(
                "Support", f"<ul>{rows}</ul>"
                "<p><a href='/support/tickets/new'>New ticket</a></p>")
        if path == "/support/tickets/new":
            options = "".join(
                f"<option value='{c}'>{c}</option>"
                for c in ("billing", "account", "technical", "other"))
            return self._send_html(
                "New ticket",
                "<form action='/support/tickets/new' method='post'>"
                "<label>Subject <input name='subject' type='text'></label><br>"
                f"<label>Category <select name='category'>{options}</select></label><br>"
                "<label>Description <textarea name='description'></textarea></label><br>"
                "<input type='submit' value='Open ticket'></form>")
        if path.startswith("/support/tickets/"):
            try:
                tid = int(path.rsplit("/", 1)[-1])
            except ValueError:
                return self._send_html("Not found", "<p>No such ticket.</p>", 404)
            ticket = tickets.get(tid)
            if not ticket:
                return self._send_html("Not found", "<p>No such ticket.</p>", 404)
            replies = "".join(f"<li>{_esc(r)}</li>" for r in ticket["replies"])
            created = "<p>Ticket created.</p>" if query.get("created") else ""
            replied = "<p>Reply sent.</p>" if query.get("replied") else ""
            closed = "<p>Ticket closed.</p>" if query.get("closed") else ""
            close = ("<form action='/support/tickets/"
                     f"{tid}/close' method='post'>"
                     "<input type='submit' value='Close ticket'></form>"
                     if ticket["status"] == "open" else "")
            return self._send_html(
                ticket["subject"],
                created + replied + closed +
                f"<p>Category: {_esc(ticket['category'])}</p>"
                f"<p>{_esc(ticket['description'])}</p>"
                f"<p>Status: {_esc(ticket['status'])}</p>"
                f"<form action='/support/tickets/{tid}/reply' method='post'>"
                "<label>Reply <textarea name='reply'></textarea></label>"
                "<input type='submit' value='Send reply'></form>"
                + close + f"<h2>Replies</h2><ul>{replies}</ul>")
        return self._send_html("Not found", "<p>Unknown support page.</p>", 404)

    def _support_post(self, path):
        form = self._form()
        with self.store.lock:
            state = self.store.state["support"]
            if path == "/support/tickets/new":
                ticket = {"id": state["next_ticket_id"],
                          "subject": form.get("subject", ""),
                          "category": form.get("category", "other"),
                          "description": form.get("description", ""),
                          "status": "open", "replies": []}
                state["next_ticket_id"] += 1
                state["tickets"].append(ticket)
                return self._redirect(f"/support/tickets/{ticket['id']}?created=1")
            if path.startswith("/support/tickets/") and path.endswith("/reply"):
                tid = int(path.split("/")[3])
                ticket = next((t for t in state["tickets"] if t["id"] == tid), None)
                if not ticket:
                    return self._send_html("Not found", "<p>No such ticket.</p>", 404)
                ticket["replies"].append(form.get("reply", ""))
                return self._redirect(f"/support/tickets/{tid}?replied=1")
            if path.startswith("/support/tickets/") and path.endswith("/close"):
                tid = int(path.split("/")[3])
                ticket = next((t for t in state["tickets"] if t["id"] == tid), None)
                if not ticket:
                    return self._send_html("Not found", "<p>No such ticket.</p>", 404)
                ticket["status"] = "closed"
                return self._redirect(f"/support/tickets/{tid}?closed=1")
        return self._send_html("Not found", "<p>Unknown support action.</p>", 404)


def make_server(host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    """Create a test-site server on an ephemeral port (port=0)."""
    handler = type("BoundHandler", (SiteHandler,), {"store": SiteStore()})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def serve_forever(host: str = "127.0.0.1", port: int = 0):
    server = make_server(host, port)
    print(f"BrowserBench test sites at http://{server.server_address[0]}:"
          f"{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    import sys
    serve_forever(port=int(sys.argv[1]) if len(sys.argv) > 1 else 0)
