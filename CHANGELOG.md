# Changelog

All notable changes to BrowserBench are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Task definitions are versioned separately (see
`docs/benchmark-methodology.md`): a task's `version` field is bumped when
that task changes, independently of the BrowserBench release version.

## [Unreleased]

### Added

- **Three new benchmark tasks (18 total, all version `1.0.0`)** —
  `shop-buy-two-checkout` (two products, one order; two success
  conditions, so a one-product checkout scores partial 0.5),
  `crm-create-and-note` (create a lead and add a note; two conditions),
  and `sched-book-and-verify` (book an appointment; uses `state_equals`
  on `next_appointment_id`, the first task to do so). Partial credit and
  `state_equals` are now exercised by real tasks, not just unit tests.
- **Cost reporting** — an agent may supply `cost_usd` (in-process
  attribute, or `cost_usd` in the HTTP response envelope); the runner
  records it in run metrics and the suite summary (`total_cost_usd`),
  and reports show it. The bundled agents report no cost.
- **Retries aggregated** — suite summaries now carry `total_retries`
  and reports show it.
- **Per-step trace timestamps and state snapshots** — every trace step
  now records an ISO-8601 UTC `timestamp` and the full
  `state_snapshot` after the action. The two `expectedFailure` tests
  that pinned the gap are now ordinary passing tests.
- **Workspace config is honoured** — `run`, `report` and `replay`
  read `tasks_dir`, `runs_dir` and `default_agent` from
  `browserbench.yaml` in the current directory; explicit flags win.
- **Non-editable installs ship the bundled data** — `setup.py` installs
  `tasks/`, `agents/` and `demo.py` as data files, and the CLI falls
  back to the installed copy when the checkout copy is absent, so
  `browserbench run` works outside a checkout.
- **Random baseline reported as a range and a mean over seeds 0, 1, 2**
  (`demo.py` and the README); a single random run is never quoted as
  the baseline.

### Fixed

- **Random agent not reproducible across processes** — `RandomAgent`
  seeded from `hash(task.id)`, and Python string hashing is randomised
  per process. It now seeds from SHA-256 of the base seed plus the task
  id; identical runs are verified across processes with different
  `PYTHONHASHSEED` values.
- **Stale README demo numbers** — the demo block (43 steps / 0.9 s
  scripted, 74 steps random, 10 tasks) did not match real runs. It now
  shows the real numbers (scripted 18/18, 82 steps; random 0–0/18
  across 3 seeds, 51 steps for seed 0) and the test suite pins the
  block against a fresh run. Durations are not quoted — they vary.
- **Trace overstatement** — docs claimed a full DOM snapshot per step;
  the trace stores a DOM *summary* plus the full state snapshot. Docs
  now say so.
- **`report latest` failed on old demo runs** — it picked the newest
  directory even without a `summary.json`. It now skips directories
  without one, and `report` on such a directory explains what to point
  it at instead.
- **`init` workspace was decorative** — `browserbench.yaml` was written
  but never read (see Added, above).
- **Undocumented exit-code contract** — `run` exits 0 only at 100%,
  1 otherwise; now documented in the CLI help, README and methodology.
- **Bare interpreter commands** — all docs and code now use `python3`.
- **Task counts** — README, methodology, integrity docs and
  CONTRIBUTING now say 18 tasks, not 10 or 15.

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
- **CLI** (`python3 -m browserbench`, also installed as the `browserbench`
  console script): `init` (scaffold a workspace), `run` (run the suite
  against an agent), `report` (latest run), `replay` (re-execute a saved
  run). Demo: `python3 demo.py` runs scripted vs random side by side.
- **Reports**: terminal and Markdown summaries showing success rate
  alongside mean partial completion, steps, duration, and unsafe
  attempts — never a single aggregate number on its own.
- **Docs**: `README.md` (60-second quickstart), `ARCHITECTURE.md`,
  `docs/benchmark-methodology.md` (scoring, versioning, integrity, and
  leaderboard rules), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and this
  changelog.

### Verified results (v0.1.0)

- `python3 demo.py`: scripted agent **15/15 passed** (63 steps), random
  baseline **0/15 passed** (51 steps, 16 unsafe attempts blocked),
  replay of a failed run matches.
- Test suite: **58 tests pass** (`python3 -m unittest discover -s tests`,
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
