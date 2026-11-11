# Benchmark methodology

## What BrowserBench measures

BrowserBench measures whether a browser-using agent can complete
multi-step tasks on synthetic applications, using only the final
application state as evidence. Each task defines success conditions
(e.g. "the cart contains 1 × Widget Alpha", "lead Ada Lovelace has
status Contacted"). A run passes when all conditions hold; otherwise it
receives partial credit equal to the fraction of conditions satisfied.

## Scoring rules

1. **State-based only.** Core scoring inspects final application state
   and required side effects. An LLM judge is not used for core scoring.
   If LLM judging is ever added, it is a clearly marked secondary metric
   and must never change the core score.
2. **Deterministic starting state.** Every task resets its site with a
   recorded seed before running. The same (task version, seed, agent,
   action sequence) must reproduce the same result — replay verifies this.
3. **Step budget.** Each task declares `max_steps`. Exceeding it ends the
   run; the state at that point is still scored (partial credit applies).
4. **Unsafe attempts are blocked, not scored as success.** Navigating
   outside the allowed URL prefixes, hitting harness endpoints
   (`/__state__`, `/__reset__`), or using a disallowed action type is
   blocked, counted, and recorded. A run that "succeeds" by peeking at
   state or skipping the UI cannot score — the evaluator only sees state
   produced through legitimate actions.
5. **No single aggregate number.** Reports always show success rate
   alongside mean partial completion, steps, duration, and unsafe
   attempts. Do not rank agents on success rate alone.

## Task versioning and integrity

- Tasks are versioned (`version` field, semver). A published task is
  never silently changed: a change means a new version, and old results
  are labelled with the version they ran against.
- Replay refuses artifacts whose task version differs from the current
  task file, and reports the drift instead of guessing.
- Public development tasks and any hidden evaluation set are separate;
  this repository ships only the public set.
- Test sites contain synthetic data only. Never test on real users'
  accounts or websites without permission.

## Reproducibility

A run artifact (`runs/<id>/artifact.json`) contains: format version,
task id + version, seed, agent name + version, config, and the exact
action sequence. `browserbench replay <run-dir>` re-executes it and
reports whether the outcome matches. A mismatch is a defect in the task
or the site, and must be investigated — never smoothed over.

## What the numbers do and do not mean

- The bundled scripted agent passes 10/10 because it follows each
  task's reference plan. It demonstrates that the tasks are solvable
  and the harness works. It is not evidence of general agent ability.
- The random baseline passes 0/10. Any real agent should beat it; an
  agent that does not is worse than chance on this suite.
- Results on this local HTTP driver test agent logic (planning, tool
  use, recovery, instruction following). They say nothing about real
  browser rendering, layout handling, or JavaScript behaviour — that
  needs the Playwright runner (production path).
- 10 tasks across 4 synthetic sites is a smoke suite, not a benchmark
  with statistical power. Grow the task registry before drawing strong
  conclusions about an agent.

## Leaderboard rules (for any future hosted leaderboard)

- Publish the full configuration: task versions, seed, agent version,
  model/provider where available, and the BrowserBench version.
- Reproducible configurations only; unverifiable claims are not ranked.
- Competing agent adapters are welcome; the benchmark must not be
  designed to favour its maintainers' agent.
