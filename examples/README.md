# BrowserBench examples

Runnable examples that show the three core workflows of the harness.
Each is a standalone script under `examples/` — no manual input, no
extra dependencies beyond the repo itself. Run them from the **repo
root**; each script adds the repo root to `sys.path` so the
`browserbench` package is importable without installing it.

```bash
python examples/run_suite.py
python examples/compare_agents.py
python examples/replay_failed.py
```

All three write their run artifacts under `runs/` (traces, results and
replayable `artifact.json` files), so you can inspect or replay them
afterwards with the CLI (`python -m browserbench report …` /
`python -m browserbench replay …`).

## 1. `run_suite.py` — run the full suite with one agent

```bash
python examples/run_suite.py
python examples/run_suite.py --agent random
python examples/run_suite.py --out runs/my-first-suite
```

Loads all bundled tasks, runs the reference scripted agent (the
default; `--agent` also accepts `random`, a `.py` agent file or an
`http://` agent URL), prints the terminal summary report and writes
`summary.json` / `report.md` next to the per-task artifacts in
`runs/example-run-suite/` (or `--out`).

Expected output with the default agent: **every task passed** (the scripted
agent follows each task's reference plan). Exit code is 0 when the
suite ran cleanly to completion, whatever the pass rate — a failing
agent is a result, not a crash.

## 2. `compare_agents.py` — compare agents head to head

```bash
python examples/compare_agents.py
python examples/compare_agents.py --agents scripted random
python examples/compare_agents.py --out-dir runs/my-comparison
```

Runs each listed agent (default: `scripted` vs `random`) on the same
the full task list with identical starting state — every task is reset to its
seeded state before each run — and prints a side-by-side table
(success rate, mean partial completion, total steps, total duration,
unsafe attempts blocked) plus a per-task PASS/FAIL grid.

Expected outcome: scripted **all tasks (100%)**, random **none (0%)**.
That gap is the point — it shows the tasks are solvable and the random
baseline is a real floor. Artifacts go to
`runs/example-compare/<agent-name>/` (or `--out-dir`).

## 3. `replay_failed.py` — replay a failed run from its artifact

```bash
python examples/replay_failed.py
python examples/replay_failed.py --run-dir runs/demo-random
python examples/replay_failed.py --run-dir runs/demo-random/shop-checkout
```

Failure replay is what makes a BrowserBench failure debuggable: a run's
`artifact.json` records the task id + version, the seed and the exact
action sequence, so replaying it must reproduce the original result
exactly.

- With no arguments, the script first runs the random baseline (which
  fails nearly every task) into `runs/example-replay-random/` and replays
  its first failed task.
- With `--run-dir`, it replays an existing run instead: give a single
  task run directory (containing `artifact.json`) or a suite directory
  (the first failed task inside it is replayed).

Expected output: `match: YES` — original FAIL, replayed FAIL, same
conditions passed. Exit code is 0 on a match, 1 on a mismatch (task
or site drift — investigate, don't trust either result), and 2 when
no failed run could be found to replay.

## See also

- `../demo.py` — the bundled demo combining all three workflows in
  one script (compare + replay).
- `../README.md` — quickstart and the CLI equivalents
  (`browserbench run` / `report` / `replay`).
- `../docs/benchmark-methodology.md` — scoring rules and what the
  numbers do and do not mean.
