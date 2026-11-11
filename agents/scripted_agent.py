"""Scripted reference agent — copy this file to build your own agent.

This agent follows the task's ``reference_plan``. Real agents should
derive their own plan from the task goal instead; see
``random_agent.py`` for the minimal shape and ``http_agent_example.py``
for the HTTP protocol.

Run it with:
    python3 -m browserbench run --agent ./agents/scripted_agent.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from browserbench.agents import ScriptedAgent  # noqa: E402

Agent = ScriptedAgent
