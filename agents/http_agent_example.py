"""Example HTTP agent: serves the versioned JSON agent protocol.

The runner POSTs observations to /act and expects an action back:
    {"protocol": "browserbench-agent/1", "action": {...}}

This example is a tiny generic agent: it clicks the first link whose
text shares a word with the task goal, fills the first form it finds,
and submits it. It solves exactly one of the 18 bundled tasks
(sched-cancel-appointment) and fails the rest — which is exactly what
an example should do. Replace the strategy with your own; the protocol
stays the same.

Run it, then point the runner at it:
    python3 agents/http_agent_example.py 9000
    python3 -m browserbench run --agent http://127.0.0.1:9000
"""

import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Allow running as `python3 agents/http_agent_example.py` from the repo
# root: the script's directory (agents/) is on sys.path, not the root,
# so make the checkout root importable for `browserbench`.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from browserbench.adapter import PROTOCOL

STOPWORDS = {"a", "an", "the", "to", "for", "and", "on", "in", "of", "with",
             "add", "set", "new", "one", "its", "an"}


def goal_words(goal: str) -> set:
    words = set(re.findall(r"[a-z0-9]+", goal.lower()))
    return words - STOPWORDS


def decide(observation: dict) -> dict:
    words = goal_words(observation.get("goal", ""))
    for link in observation.get("links", []):
        link_words = set(re.findall(r"[a-z0-9]+", link.get("text", "").lower()))
        if words & link_words:
            return {"type": "click", "href": link["href"]}
    forms = observation.get("forms", [])
    if forms:
        form = forms[0]
        values = {}
        for field in form.get("fields", []):
            if field.get("type") in ("hidden", "select"):
                continue
            name = field.get("name", "")
            if "email" in name:
                values[name] = "agent@example.com"
            elif "name" in name:
                values[name] = "Agent Example"
            else:
                values[name] = "example"
        return {"type": "submit", "form": 0} if not values else \
            {"type": "fill", "form": 0, "values": values}
    if observation.get("links"):
        return {"type": "click", "href": observation["links"][0]["href"]}
    return {"type": "done"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        if self.path != "/act":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if payload.get("protocol") != PROTOCOL:
            self.send_response(400)
            self.end_headers()
            return
        action = decide(payload["observation"])
        body = json.dumps({"protocol": PROTOCOL, "action": action}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    print(f"example HTTP agent on http://127.0.0.1:{port} "
          f"(protocol {PROTOCOL})")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
