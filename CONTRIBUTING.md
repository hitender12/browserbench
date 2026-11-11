# Contributing to BrowserBench

Thank you for helping make browser-agent evaluation reproducible. BrowserBench
is a test harness, scenario format, and benchmark suite — not another browser
automation library — so the most valuable contributions are the ones that make
results *more trustworthy*: a well-specified task, a correct evaluator
condition, an honest adapter, or a clearer doc. Please read
[docs/benchmark-integrity.md](docs/benchmark-integrity.md) before touching
tasks, scoring, or anything that affects published results.

By participating you agree to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

## First contribution path

1. Run the demo and confirm the expected outcome:
   `python demo.py` — the scripted reference agent should pass 15/15 and the
   random baseline 0/15, followed by a replay check that reports `match=YES`.
2. Run the tests: `python -m unittest discover -s tests` (58 tests, ~16 s;
   2 expected failures are intentional — see "Tests" below).
3. Pick a small task: a new benchmark task, a new evaluator condition type,
   a bug fix, or a docs clarification. Good first issues are labelled
   `good first issue` and always include enough context to be completed
   without guessing.

## Local setup

Requirements:

- Python 3.10, 3.11, or 3.12 (CI tests all three; see
  `.github/workflows/ci.yml`). Check with `python --version`.
- Git. Nothing else. The core package has **zero dependencies** — standard
  library only (`pyproject.toml` lists `dependencies = []`), so there is no
  virtual-environment or network install step. If you want an isolated
  environment anyway, any `venv` works:
  `python -m venv .venv && .venv/bin/activate` (Windows:
  `.venv\Scripts\activate`).
- No API keys, no paid accounts, no browser download. The current build
  drives the synthetic test sites over local HTTP with a parsed-DOM
  observation; it does not use Playwright or a real browser yet (see
  "Honest status" in the README and ARCHITECTURE.md).

From the repository root:

```bash
git clone <the repository URL>   # use the real repo URL for this project
cd browserbench
python -m pip install -e .        # optional; enables the `browserbench` command
python -m unittest discover -s tests
python demo.py
```

Useful commands once set up:

```bash
python -m browserbench init my-bench                 # scaffold a workspace
python -m browserbench run --agent scripted           # reference agent, all tasks
python -m browserbench run --agent random              # random baseline, same tasks
python -m browserbench run --agent scripted --tasks shop-add-to-cart,crm-create-lead
python -m browserbench report latest
python -m browserbench replay runs/<run-id>/<task-id>
python examples/run_suite.py --agent random           # head-to-head helper
python examples/compare_agents.py                     # compare two agents
```

`browserbench run` exits `0` only when the suite passes 100%; a failing
agent is a *result*, not a crash, so do not treat a non-zero exit as a
harness error.

## Repository layout

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full map. In short:

| Area | What lives there |
|---|---|
| `browserbench/` | Core package: `spec.py` (task loading/validation), `sites.py` (4 synthetic apps), `dom.py`, `adapter.py` (agent contract), `agents.py`, `evaluator.py`, `runner.py` (safety boundary), `trace.py`, `replay.py`, `report.py`, `__main__.py` (CLI) |
| `tasks/<site>/` | Versioned task definitions (JSON, plus a YAML subset) |
| `agents/` | Bundled agents: `scripted_agent.py`, `random_agent.py`, `http_agent_example.py` |
| `tests/` | `unittest` suite (`test_browserbench.py`, `test_edge_cases.py`) |
| `docs/` | Methodology, task-authoring guide, integrity rules |
| `examples/` | Runnable suite/comparison helpers |
| `runs/` | Generated run artifacts (traces, reports). Do not commit these. |

## Tests

- Framework: `unittest`, standard library only. Keep the suite fast
  (seconds, not minutes) — it currently runs in ~16 s.
- Every public behaviour needs a test; every limitation goes in the
  README's honest-status section and in ARCHITECTURE.md, not just in a
  commit message.
- The suite asserts the task count in two places
  (`tests/test_browserbench.py` and `tests/test_edge_cases.py` currently
  expect 15 tasks). **If you add or remove a task, update both assertions
  in the same PR.**
- Two tests are marked as expected failures (`expectedFailure`): trace steps
  do not yet carry wall-clock timestamps or per-step state snapshots. Do
  not "fix" those by deleting the markers — implement the feature, then
  remove the marker in the same PR.
- Run the full suite before opening a PR, and add a regression test for
  every bug fix.

## Contributing a new benchmark task

Tasks are the heart of the project, and they have stricter rules than other
contributions. The full guide is
[docs/contributing-tasks.md](docs/contributing-tasks.md); the short version:

1. Add a JSON file (preferred) under `tasks/<site>/` with a new unique `id`
   and a `version` of `1.0.0`. Sites are `shop`, `crm`, `sched`, `support`.
   One task per file; the filename should match the task `id`.
2. Give it a `reference_plan` that reaches the success state, then verify
   the scripted agent passes it:
   `python -m browserbench run --agent scripted --tasks <id>`.
3. Verify the random baseline does **not** pass it by luck:
   `python -m browserbench run --agent random --tasks <id>`.
4. Verify replay: `python -m browserbench replay runs/<latest>/<id>` —
   it must report `match=YES`.
5. Update the task-count assertions in both test files (see "Tests" above).
6. Add the task to `CHANGELOG.md` under Unreleased.

Rules that are non-negotiable (enforced by review and by
[docs/benchmark-integrity.md](docs/benchmark-integrity.md)):

- Success conditions must be checkable against **final site state only**.
  No LLM judge for core scoring; no judging from screenshots, logs, or
  what the agent "seemed to do".
- **Never silently change a published task**: a change means a new
  `version`, and old results stay labelled with the version they ran
  against.
- Keep tasks deterministic — no wall-clock, randomness, or network
  dependence in the task or the site fixtures. The seed in the task file
  fully determines the starting state.
- Synthetic data only; never point a task at a real website, a real
  account, or a real user's data.
- `max_steps` must be at least the length of the `reference_plan`, and
  generous enough that a competent agent is not failed by the budget.
- Do not design a task to favour (or punish) a particular agent,
  framework, or model. See the neutrality rule in the Code of Conduct.

## Adding an agent adapter

An agent is anything that implements `act(observation) -> action`
(`browserbench/adapter.py`, protocol `browserbench-agent/1`). There are
three ways to plug one in:

1. **In-process Python class** — subclass `browserbench.adapter.BaseAgent`
   and implement `act(self, observation)`. Override `reset(self, task)`
   if you need per-task state. Set class attributes `name` and `version`:
   both are recorded in every run artifact and published with results.
2. **Python file** — `python -m browserbench run --agent ./agents/my-agent.py`.
   The module must define `Agent` (a class) or `act` (a function). Copy
   `agents/scripted_agent.py` (reference-plan follower) or
   `agents/random_agent.py` (minimal shape) as a starting point.
3. **HTTP agent** — `python -m browserbench run --agent http://127.0.0.1:9000`.
   The runner POSTs `{"protocol": "browserbench-agent/1", "observation": {...}}`
   to `/act` and expects `{"protocol": "browserbench-agent/1", "action": {...}}`
   back (30 s timeout). `agents/http_agent_example.py` is a working
   reference server. The protocol version is part of the contract: if you
   change the observation or action shape, bump the protocol version
   instead of silently extending it.

Adapter rules:

- Actions are limited to `navigate`, `click`, `fill`, `submit`, `done`,
  and only within the task's `allowed_actions` and `allowed_prefixes`.
  The runner validates every action before execution; violations are
  blocked, counted as unsafe attempts, and recorded in the trace — they
  never reach the site. Do not try to work around the safety boundary:
  `/__state__` and `/__reset__` are never navigable by an agent.
- Derive your plan from the task `goal` (and `params` where the
  observation exposes them). **Do not read the task's `reference_plan`
  at run time** — the scripted agent is the only agent allowed to do
  that, and only to prove a task is solvable. An adapter that peeks at
  the reference plan, the site state, or the evaluator will be rejected.
- Report cost (and model/provider, where applicable) if you have it; the
  runner records whatever the agent supplies, and reports show cost only
  when present.
- Keep adapters deterministic where you can, and record your agent's
  version: results are only comparable when the agent version is known.

## Contributing to the evaluator

- New success-condition types go in `browserbench/evaluator.py`
  (`CONDITIONS` tuple plus a branch in `evaluate_condition`), with a
  docstring entry and tests covering pass, fail, and malformed input.
- Conditions inspect final state only and must be pure functions of
  `(condition, state)`. Never add a condition that depends on the action
  sequence, timing, or an external service.
- Partial credit is automatic (fraction of conditions satisfied); do not
  add ad-hoc weighting to a single condition.

## Pull request process

1. **Discuss first for big changes.** Open an issue before a new site, a
   new condition family, a protocol change, or anything that changes
   scoring — scoring changes affect every published result.
2. **Branch** from `main`: `git checkout -b <type>/<short-description>`
   (e.g. `task/shop-refund`, `fix/replay-version-check`).
3. **Keep PRs small and reviewable.** One task, one adapter, or one fix
   per PR. A PR that adds a task *and* changes the evaluator is two PRs.
4. **Include in every PR:**
   - Tests for the new/changed behaviour, passing locally.
   - A `CHANGELOG.md` entry under Unreleased (see CHANGELOG.md).
   - For tasks: the scripted-pass, random-baseline, and replay evidence
     from the checklist above (paste the commands and their output).
   - For scoring or protocol changes: a note on what happens to results
     published under the old version.
5. **CI must pass.** GitHub Actions runs the test suite on Python 3.10,
   3.11, and 3.12, plus a smoke run (`demo`-style CLI subset) on 3.12.
   A PR that fails CI is not reviewed until it is green.
6. **Review.** A maintainer reviews for correctness *and* for benchmark
   integrity: determinism, state-only scoring, versioning, and neutrality.
   Expect questions about edge cases; "it passed once" is not evidence —
   show the replay.
7. **Do not force-push after review starts** unless asked; it hides what
   changed. Squash only on merge if the maintainer asks.

## Reporting issues

- **Bugs:** open an issue with the task id (if any), agent, BrowserBench
  version (`python -m browserbench --version`), the exact command, and
  the run artifact or trace excerpt. A replayable failure is worth more
  than a screenshot.
- **Wrong results / benchmark integrity concerns:** open an issue and say
  so plainly — a task that is flaky, guessable, or gameable is a defect,
  not a feature. See [docs/benchmark-integrity.md](docs/benchmark-integrity.md).
- **Security vulnerabilities:** do **not** open a public issue. Follow
  [SECURITY.md](SECURITY.md).
- **Questions / ideas:** open a discussion or an issue labelled
  `question`. Feature requests should explain the workflow they unblock,
  not just the feature.

## Releases

Releases are tagged from `main` (`v0.1.0`, …) with a `CHANGELOG.md`
entry. Only maintainers cut releases. A release is reproducible from CI:
the tag, the changelog, and the test suite at that commit are the record
of what shipped.
