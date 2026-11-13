# BrowserBench

> A reproducible test lab and benchmark for browser-using AI agents.

Browser agents can look great in a demo and fail on pagination, changed layouts, ambiguous buttons, authentication, stale content, retries, and multi-step tasks. BrowserBench gives them versioned tasks, resettable test websites, deterministic state-based scoring, and reproducible failures — so results can be compared honestly.

**BrowserBench is a test harness, scenario format, and benchmark suite — not another browser automation library.**

## 60-second quickstart

```bash
python3 -m browserbench init my-bench   # scaffold a workspace
cd my-bench
python3 -m browserbench run --agent scripted    # reference agent, 18 tasks
python3 -m browserbench run --agent random      # random baseline, same tasks
python3 -m browserbench report latest           # compare the runs
```

Inside an `init` workspace, `browserbench run` with no flags uses the
workspace's own tasks (from `browserbench.yaml`); explicit flags always
win over the config file. Outside a workspace it uses the bundled tasks.

Or run the bundled demo (scripted vs random, side by side, plus a replay
of one failed run):

```bash
python3 demo.py
```

## How it works

1. **Tasks** (`tasks/`) are declarative JSON/YAML: goal, starting state, allowed actions, and state-based success conditions. Each task is versioned — never silently change a published task.
2. **Test sites** are synthetic apps (shopping, CRM, scheduling, support) served locally with reset endpoints and known deterministic state. Synthetic data only.
3. **Agents** implement one function, `act(observation) -> action`, in-process (Python file) or over the versioned JSON protocol (`browserbench-agent/1`) via HTTP. See `agents/`. A fill is bound to the (page URL, form index) it was made on — filled values never leak into another page's form.
4. **The evaluator** scores final application state only. No LLM judge for core scoring — an LLM judge is a clearly marked secondary metric, not implemented here.
5. **Traces** record every step: the action, URL, HTTP status, latency, a wall-clock timestamp (ISO-8601 UTC), a DOM summary (links, form names, 500-character text excerpt), and the full site-state snapshot after the action — plus network events and any blocked (unsafe) attempts. Every run saves a replayable artifact (task version, seed, config, action sequence) — `browserbench replay <run-dir>` re-executes it and checks the result matches.

## The demo that should make you share it

```
BrowserBench — agent: scripted
passed 18/18 (100%)  mean partial 1.00  steps 82  unsafe blocked 0  retries 0
BrowserBench — agent: random
passed 0–0/18 across 3 seeds (mean 0.0)  steps 51 (seed 0)  unsafe blocked 10  retries 0
```

Same 18 tasks, same starting state. Click a failed run and replay it locally — the failure reproduces exactly.

The numbers above are from a real demo run, and the test suite pins
them: pass counts and step counts are deterministic (the scripted agent
follows the reference plans; the random agent is seeded from SHA-256 of
seed + task id, so it reproduces exactly across processes), while
durations vary run to run and are not quoted here. The random baseline
is run across 3 seeds (0, 1, 2) and reported as a range and a mean,
because a single random run is not a stable number.

## Metrics reported per run

Task success, partial completion (fraction of success conditions met), time, steps, retries (agent errors, aggregated across the suite), cost when the agent supplies it, and unsafe/unauthorized action attempts (blocked and counted, never executed) — including navigation outside the allowed prefixes and form actions naming a form index that does not exist on the current page.

Cost: an agent reports what a run cost it by setting the `cost_usd`
attribute (in-process agents) or by including `cost_usd` in its HTTP
response envelope (HTTP agents; values accumulate across calls). The
runner records it in the run metrics and the suite summary; agents that
do not supply a cost report none. The bundled agents report no cost.

Exit codes: `browserbench run` exits 0 only when the agent passes every
task (100% success rate), 1 when any task fails, and 2 for a usage or
loading error. A run below 100% is a failing run — the exit code says so.
Loading errors (unknown agent, broken agent file, malformed task pack,
missing or corrupt replay artifact) also exit 2, with a one-line message
on stderr and no traceback.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md). In short: task registry → runner → agent adapter contract → synthetic test apps → deterministic state evaluator → metrics + reproducible report. The production path is Playwright + TypeScript with real browsers; this build drives the test sites over local HTTP with a deterministic adapter, so it tests agent logic, not real browser rendering.

## Benchmark methodology

Scoring rules, task versioning, integrity guarantees, and what the numbers do and do not mean: [docs/benchmark-methodology.md](docs/benchmark-methodology.md).

## Honest status (v0.1.0)

What genuinely works: 18 deterministic tasks across 4 synthetic sites; reset restores exact starting state; state-based evaluation with partial credit (exercised by real multi-condition tasks); unsafe-action blocking; trace capture with per-step timestamps and state snapshots; failure replay verified to reproduce results; scripted agent passes 18/18, random baseline 0–0/18 across seeds 0–2.

What is simplified or stubbed (stated here and in ARCHITECTURE.md):
- The runner drives test sites over local HTTP with a parsed-DOM observation — **no real browser, no Playwright, no screenshots/video**. The production runner uses Playwright + TypeScript; this build tests agent logic, not rendering.
- In-memory site state, single user, no persistence, no auth.
- TF-IDF-free, LLM-free: no model-backed agents are bundled (the scripted agent follows the task's reference plan; external agents must derive their own).
- No dashboard, no hosted leaderboard, no public task registry yet — local runs and Markdown reports only.
- Cost is reported only when the agent supplies it; the bundled agents report none.
- 18 tasks across 4 synthetic sites is a smoke suite, not a benchmark with statistical power. Grow the task registry before drawing strong conclusions about an agent.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). New tasks must include a reference-plan pass, a random-baseline run, and a replay check.

## License

MIT — see [LICENSE](LICENSE).
