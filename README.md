# BrowserBench

> A reproducible test lab and benchmark for browser-using AI agents.

Browser agents can look great in a demo and fail on pagination, changed layouts, ambiguous buttons, authentication, stale content, retries, and multi-step tasks. BrowserBench gives them versioned tasks, resettable test websites, deterministic state-based scoring, and reproducible failures — so results can be compared honestly.

**BrowserBench is a test harness, scenario format, and benchmark suite — not another browser automation library.**

## 60-second quickstart

```bash
python -m browserbench init my-bench   # scaffold a workspace
cd my-bench
python -m browserbench run --agent scripted    # reference agent, 10 tasks
python -m browserbench run --agent random      # random baseline, same tasks
python -m browserbench report latest           # compare the runs
```

Or run the bundled demo (scripted vs random, side by side, plus a replay
of one failed run):

```bash
python demo.py
```

## How it works

1. **Tasks** (`tasks/`) are declarative JSON/YAML: goal, starting state, allowed actions, and state-based success conditions. Each task is versioned — never silently change a published task.
2. **Test sites** are synthetic apps (shopping, CRM, scheduling, support) served locally with reset endpoints and known deterministic state. Synthetic data only.
3. **Agents** implement one function, `act(observation) -> action`, in-process (Python file) or over the versioned JSON protocol (`browserbench-agent/1`) via HTTP. See `agents/`.
4. **The evaluator** scores final application state only. No LLM judge for core scoring — an LLM judge is a clearly marked secondary metric, not implemented here.
5. **Traces** record every step, DOM snapshot, and network event. Every run saves a replayable artifact (task version, seed, config, action sequence) — `browserbench replay <run-dir>` re-executes it and checks the result matches.

## The demo that should make you share it

```
BrowserBench — agent: scripted
passed 10/10 (100%)  mean partial 1.00  steps 43  0.9s  unsafe blocked 0
BrowserBench — agent: random
passed 0/10 (0%)  mean partial 0.00  steps 74  1.1s  unsafe blocked 0
```

Same 10 tasks, same starting state. Click a failed run and replay it locally — the failure reproduces exactly.

## Metrics reported per run

Task success, partial completion (fraction of success conditions met), time, steps, retries, cost where available, and unsafe/unauthorized action attempts (blocked and counted, never executed).

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md). In short: task registry → runner → agent adapter contract → synthetic test apps → deterministic state evaluator → metrics + reproducible report. The production path is Playwright + TypeScript with real browsers; this build drives the test sites over local HTTP with a deterministic adapter, so it tests agent logic, not real browser rendering.

## Benchmark methodology

Scoring rules, task versioning, integrity guarantees, and what the numbers do and do not mean: [docs/benchmark-methodology.md](docs/benchmark-methodology.md).

## Honest status (v0.1.0)

What genuinely works: 10 deterministic tasks across 4 synthetic sites; reset restores exact starting state; state-based evaluation with partial credit; unsafe-action blocking; trace capture; failure replay verified to reproduce results; scripted agent passes 10/10, random baseline 0/10.

What is simplified or stubbed (stated here and in ARCHITECTURE.md):
- The runner drives test sites over local HTTP with a parsed-DOM observation — **no real browser, no Playwright, no screenshots/video**. The production runner uses Playwright + TypeScript; this build tests agent logic, not rendering.
- In-memory site state, single user, no persistence, no auth.
- TF-IDF-free, LLM-free: no model-backed agents are bundled (the scripted agent follows the task's reference plan; external agents must derive their own).
- No dashboard, no hosted leaderboard, no public task registry yet — local runs and Markdown reports only.
- Cost is reported only when the agent supplies it; the bundled agents report none.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). New tasks must include a reference-plan pass, a random-baseline run, and a replay check.

## License

MIT — see [LICENSE](LICENSE).
