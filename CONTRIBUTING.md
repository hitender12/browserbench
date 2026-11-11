# Contributing to BrowserBench

## First contribution path

1. Run the demo: `python demo.py` — scripted should pass 10/10.
2. Run the tests: `python -m unittest discover -s tests`.
3. Pick a small task: a new task, a new condition type, or a bug fix.

## Adding a new task

1. Add a JSON (or YAML-subset) file under `tasks/<site>/` with a new
   unique `id` and a `version` of `1.0.0`.
2. Verify the scripted agent can pass it: give it a `reference_plan`
   that reaches the success state, then run
   `python -m browserbench run --agent scripted --tasks <id>`.
3. Verify the random baseline does not pass it by luck:
   `python -m browserbench run --agent random --tasks <id>`.
4. Verify replay: `python -m browserbench replay runs/<latest>/<id>`.
5. Add the task to the test suite's task-count assertion if it changes.

## Rules for tasks

- Success conditions must be checkable against final site state only.
- Never silently change a published task: bump `version` instead.
- Keep tasks deterministic — no wall-clock, randomness, or network
  dependence in the site fixtures.
- Synthetic data only; never point a task at a real website.

## Code style

- Python 3.10+, standard library only for the core package.
- Tests with `unittest`; keep the suite fast (seconds, not minutes).
- Every public behaviour needs a test; every limitation goes in the
  README's honest-status section and in ARCHITECTURE.md.
