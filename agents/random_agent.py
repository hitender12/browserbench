"""Random baseline agent — the simplest possible agent.

Picks a random allowed action each step. Any real agent should beat it;
the demo compares the two on identical tasks.

Run it with:
    python3 -m browserbench run --agent ./agents/random_agent.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from browserbench.agents import RandomAgent  # noqa: E402

Agent = RandomAgent
