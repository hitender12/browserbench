# Benchmark integrity

A benchmark is useful only if people trust it. BrowserBench's credibility
rests on these rules, not on any single score. They bind maintainers and
contributors alike, and they override convenience: if a shortcut would
make results look better but less trustworthy, do not take it.

The scoring rules themselves live in
[benchmark-methodology.md](benchmark-methodology.md). This document is
the governance around them: versioning, what must be published with a
result, what counts as gaming, and how results can be challenged.

## 1. Version tasks and test sites — never silently change a task

- Every task carries a semver `version` (starting at `1.0.0`). Every
  result is labelled with the task versions it ran against.
- **A published task is never silently changed.** Any change to a task's
  goal, starting state, allowed actions, success conditions, or
  reference plan after results have been published against it requires
  a version bump, and the change is noted in `CHANGELOG.md`. Old
  results keep the old version label; they are never re-labelled as if
  they ran against the new version.
- The same applies to the test sites in `browserbench/sites.py`: a site
  change that alters what a task can do or what its starting state is
  must be accompanied by task version bumps for every affected task,
  and a changelog entry saying which tasks changed and why.
- Replay is the enforcement mechanism: `browserbench replay` refuses
  artifacts whose task version differs from the current task file and
  reports the drift instead of guessing. A replay mismatch is a defect
  in the task or the site and must be investigated — never smoothed
  over, and never fixed by editing the artifact.
- Never reuse a task `id` for a different task. Withdrawn tasks are
  removed and noted in the changelog; their ids stay retired.

## 2. Deterministic state assertions over LLM judges

- Core scoring inspects **final application state only**, using the
  condition types in `browserbench/evaluator.py`. A run passes when all
  of a task's success conditions hold; otherwise it receives partial
  credit equal to the fraction satisfied.
- **No LLM judge for core scoring.** An LLM judge is non-deterministic,
  unreproducible, and sensitive to prompt and model changes. If LLM
  judging is ever added, it is a clearly marked **secondary metric**,
  reported separately, and it must never change the core score.
- The same applies to scoring from screenshots, logs, or narrative
  summaries of "what the agent seemed to do": evidence is state, not
  vibes. A run that "succeeds" by peeking at harness state
  (`/__state__`, `/__reset__`), skipping the UI, or using a disallowed
  action cannot score — the evaluator only sees state produced through
  legitimate actions, and the safety boundary blocks the rest.
- Determinism is testable: the same (task version, seed, agent, action
  sequence) must reproduce the same result. Tasks must not depend on
  wall-clock time, randomness, or the network. If a result cannot be
  replayed, it is not a result — it is a bug report.

## 3. Publish the full configuration with results

A result without its configuration is unverifiable and must not be
ranked or quoted as a benchmark score. Every published result — in a
README, a report, a leaderboard, or a blog post — must include:

- BrowserBench version (`browserbench_version` in `summary.json`).
- Task ids **and** task versions for every task run.
- Seed(s) used (each task records its seed; a run that overrides seeds
  must say so).
- Agent name **and** agent version, plus model/provider details where
  available (model name, provider, temperature/sampling settings if
  they affect behaviour).
- Browser / driver details: the current build drives sites over local
  HTTP with a parsed-DOM observation — **no real browser**. Any result
  from this build must say that, and must not be presented as evidence
  about real-browser rendering, layout, or JavaScript behaviour. When
  the Playwright runner lands, its browser version is part of the
  configuration too.
- The run artifact (`runs/<id>/`, including `summary.json`,
  `report.md`, and per-task artifacts) or a link to it, so anyone can
  replay it locally with `browserbench replay`.

Reports must show success rate **alongside** mean partial completion,
steps, duration, retries, cost (when reported), and unsafe attempts.
**Do not rank agents on a single aggregate number** without showing
cost, latency, failure categories, and task coverage. The bundled
scripted agent passing 18/18 proves the
tasks are solvable; it is not evidence of general agent ability, and
must never be presented as a competing agent's score.

## 4. Separate public dev tasks from any hidden eval set

- This repository ships **only the public development set** (currently
  18 tasks). Agent developers may study, tune against, and overfit to
  these tasks — that is what a dev set is for.
- Any hidden evaluation set, if one is ever created, must be kept
  separate: different tasks, different files, not shipped in this
  repository, and never used for development or tuning. Its purpose,
  size, and the fact of its existence must be documented; its contents
  must not leak into the public set through "hints" in task text,
  fixtures, or docs.
- Do not present dev-set scores as if they were held-out evaluation
  scores. A dev-set score measures fit to the public tasks; a hidden-set
  score measures generalisation. Conflating the two is misrepresentation.
- If a task from the public set is found to be leaked into, or
  duplicated in, a hidden set, the overlap must be disclosed and the
  affected results relabelled.

## 5. Neutrality — the benchmark must not favour its maintainers' agent

- Tasks, sites, scoring, and adapters must not be designed to favour
  (or punish) any particular agent, framework, model, or vendor —
  including any agent maintained by BrowserBench maintainers.
- Competing agent adapters are welcome. An adapter that follows the
  documented contract (`act(observation) -> action`, protocol
  `browserbench-agent/1`) must be treated the same as a bundled agent.
- Maintainers must recuse themselves from reviewing a task or scoring
  change that benefits their own agent, and must disclose the conflict
  in the PR.
- Benchmark governance gets stricter as the project grows: if a hosted
  leaderboard is ever built, it needs reproducible configurations only,
  neutral governance, and a public process for disputing a result.

## 6. Synthetic data only

- Test sites contain synthetic data only (invented products, leads,
  appointments, tickets). Never test on real users' accounts or real
  websites without permission, and never put real personal data,
  credentials, or API keys into a task, an agent, a fixture, or a run
  artifact.
- Do not publish a run directory without checking it first: traces may
  contain task parameters and action sequences.

## 7. What invalidates a result

A result must be withdrawn or relabelled if any of the following is
found:

- It ran against a task version different from the one claimed.
- The task was changed after the result was published without a version
  bump (see §1).
- The agent peeked at the task's `reference_plan`, site state, or
  evaluator internals at run time (only the scripted agent may follow
  a reference plan, and only to prove solvability).
- The configuration in §3 is missing or wrong (wrong agent version,
  undisclosed model change, unreported seed override).
- The result cannot be reproduced by replaying its artifact.
- The score quoted is a dev-set score presented as a held-out score.

Withdrawing a result is not a punishment — it is how the public record
stays accurate. Corrections are published in `CHANGELOG.md` and, where
the result was widely quoted, in the methodology docs.

## 8. Challenging a result or a task

Anyone may challenge a published result or a task: open an issue
explaining what is wrong (flaky, guessable, gameable, mislabelled,
unreproducible) with the task id, versions, and artifact involved.
Maintainers will investigate, reproduce via replay where possible, and
publish the outcome — including, where the challenge is upheld, a
correction and a task version bump. Challenges made in good faith are
welcome even when they turn out to be wrong; gaming the benchmark is
not, and is covered by the [Code of Conduct](../CODE_OF_CONDUCT.md).
