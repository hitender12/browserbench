# BrowserBench architecture

## Components

```text
Task registry (versioned JSON/YAML scenarios)
              |
       BrowserBench runner (browserbench/runner.py)
              |
       Agent adapter contract (browserbench/adapter.py)
         /           \
  Python agent     HTTP agent (versioned JSON)
         \           /
       Local HTTP driver (urllib + DOM parser)
                 |
        Synthetic test applications (browserbench/sites.py)
                 |
       Trace + DOM summaries + state snapshots + network events (browserbench/trace.py)
                 |
       Deterministic state evaluator (browserbench/evaluator.py)
                 |
        Metrics + reproducible report (browserbench/report.py)
                 |
      CLI / demo / failure replay (browserbench/replay.py)
```

## Modules

| Module | Responsibility |
|---|---|
| `spec.py` | TaskSpec: load/validate JSON + YAML-subset tasks; versioning rules |
| `yamlmini.py` | Minimal YAML-subset parser (mappings, sequences, scalars) |
| `sites.py` | Four synthetic apps + reset/state endpoints; in-memory, deterministic |
| `dom.py` | HTML → observation snapshot (title, text, links, forms) |
| `adapter.py` | Agent contract: `act(observation) -> action`; Python + HTTP loading |
| `agents.py` | Scripted (reference-plan) and random (baseline) agents |
| `evaluator.py` | State-based conditions; partial credit; no LLM judge |
| `runner.py` | Reset → observe → act → validate → execute → evaluate; safety boundary |
| `trace.py` | Per-run trace, result, and replayable artifact files (per-step wall-clock timestamps + full state snapshots) |
| `replay.py` | Re-execute a saved artifact and compare the outcome |
| `report.py` | Terminal + Markdown reports; latest-run lookup |
| `__main__.py` | CLI: `init`, `run`, `report`, `replay` |

## The safety boundary (runner)

Every action passes through validation before execution:

1. The action type must be in the task's `allowed_actions`.
2. The target URL must start with one of the task's `allowed_prefixes`
   and share the test server's host (no external hosts).
3. `/__state__` and `/__reset__` are never navigable by an agent.

Violations are blocked, counted in `metrics.unsafe_attempts`, recorded in
the trace with the exact reason, and do not end the run.

## State and determinism

- Each site's state is a plain dict, rebuilt from `initial_state(site, seed)`
  on every reset. A reset restores the starting state exactly.
- The runner is single-user and single-threaded per task; the HTTP server
  is threaded only so the runner's client and the site can coexist.
- A run is fully described by (task id, task version, seed, agent name +
  version, config, action sequence). That is what the artifact stores,
  and what replay re-executes.

## What is intentionally not here yet

- **Real browsers.** The production runner is Playwright + TypeScript with
  isolated contexts, screenshots, and video. This build substitutes a
  deterministic local HTTP driver + DOM parser, which tests agent logic
  (planning, tool use, recovery) but not rendering, layout, or JS behaviour.
- **Persistence.** Site state is in-memory; PostgreSQL (suite runs) and
  SQLite (local mode) are the production path.
- **Dashboard / leaderboard.** Local Markdown reports only; a hosted
  leaderboard needs neutral governance and reproducible configurations,
  per the methodology doc.
- **Rust runner service.** Only once profiling justifies high-concurrency
  scheduling and artifact indexing.
