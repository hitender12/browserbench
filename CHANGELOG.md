# Changelog

All notable changes to BrowserBench are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Task definitions are versioned separately (see
`docs/benchmark-methodology.md`): a task's `version` field is bumped when
that task changes, independently of the BrowserBench release version.

## [Unreleased]

<!-- Add entries here in new PRs, under the right heading. -->

## [0.1.0] - 2026-11-11

Initial release: a reproducible test lab and benchmark for browser-using
AI agents, local-first, standard library only, with no real browser yet
(see "Known limitations" below).

### Added

- **15 deterministic benchmark tasks, all version `1.0.0`, across 4
  synthetic sites** — shopping (5: add to cart, add two, buy, checkout,
  search-and-add), CRM (4: create lead, qualify lead, update status, add
  note), scheduling (3: book, book afternoon, cancel), support (3: open
  ticket, close ticket, reply-and-close). Every task declares its goal,
  starting state, allowed actions, step budget, and state-based success
  conditions, and ships with a reference plan.
- **4 resettable synthetic test sites** (`browserbench/sites.py`):
  shop, CRM, scheduling, and support, served locally on `127.0.0.1`
  with reset endpoints and known deterministic starting state. Synthetic
  data only — no real websites or accounts.
- **Deterministic evaluator** (`browserbench/evaluator.py`): scores final
  application state only, with partial credit (fraction of success
  conditions satisfied) across 11 condition types
  (`cart_contains`, `order_exists`, `lead_exists`, `lead_field`,
  `lead_note_contains`, `appointment_exists`, `appointment_absent`,
  `ticket_exists`, `ticket_field`, `ticket_reply_contains`,
  `state_equals`). No LLM judge is used for core scoring.
- **Agent adapter contract** (`browserbench/adapter.py`, protocol
  `browserbench-agent/1`): any agent implementing
  `act(observation) -> action`, in-process (Python class or file) or over
  HTTP (`POST /act` with versioned JSON). Bundled agents: `scripted`
  (reference-plan follower — the solvability proof) and `random` (baseline),
  plus an example HTTP agent in `agents/http_agent_example.py`.
- **Safety boundary** (`browserbench/runner.py`): every action is
  validated against the task's `allowed_actions` and `allowed_prefixes`
  before execution; harness endpoints (`/__state__`, `/__reset__`) are
  never agent-navigable. Violations are blocked, counted as unsafe
  attempts, and recorded in the trace.
- **Trace capture and failure replay**: every run records the action
  sequence, DOM snapshots, network events, and per-step results; each
  run saves a replayable artifact (task id + version, seed, agent name +
  version, config, action sequence). `browserbench replay <run-dir>`
  re-executes the artifact and reports whether the outcome matches.
  Verified: the demo's replay of a failed run reports `match=YES`.
- **CLI** (`python -m browserbench`, also installed as the `browserbench`
  console script): `init` (scaffold a workspace), `run` (run the suite
  against an agent), `report` (latest run), `replay` (re-execute a saved
  run). Demo: `python demo.py` runs scripted vs random side by side.
- **Reports**: terminal and Markdown summaries showing success rate
  alongside mean partial completion, steps, duration, and unsafe
  attempts — never a single aggregate number on its own.
- **Docs**: `README.md` (60-second quickstart), `ARCHITECTURE.md`,
  `docs/benchmark-methodology.md` (scoring, versioning, integrity, and
  leaderboard rules), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and this
  changelog.

### Verified results (v0.1.0)

- `python demo.py`: scripted agent **15/15 passed** (63 steps), random
  baseline **0/15 passed** (51 steps, 16 unsafe attempts blocked),
  replay of a failed run matches.
- Test suite: **58 tests pass** (`python -m unittest discover -s tests`,
  ~16 s; 2 expected failures for not-yet-implemented per-step timestamps
  and state snapshots).

### Known limitations

- The runner drives test sites over local HTTP with a parsed-DOM
  observation — **no real browser, no Playwright, no screenshots/video**.
  Results test agent logic (planning, tool use, recovery), not rendering,
  layout, or JavaScript behaviour. The production path is Playwright +
  TypeScript.
- In-memory site state, single user, no persistence, no auth.
- No model-backed agents are bundled; external agents must derive their
  own plans (only the scripted agent may follow a task's reference plan).
- Cost is reported only when the agent supplies it; the bundled agents
  report none.
- No dashboard, no hosted leaderboard, no public task registry yet —
  local runs and Markdown reports only.
- 15 tasks across 4 synthetic sites is a smoke suite, not a benchmark
  with statistical power. Grow the task registry before drawing strong
  conclusions about an agent.
