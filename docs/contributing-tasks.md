# Contributing tasks

This is the detailed guide for adding a benchmark task to BrowserBench.
Read [benchmark-integrity.md](benchmark-integrity.md) first — tasks are
versioned, public, and scored by deterministic state assertions, and the
rules below exist to keep published results comparable.

## What a task is

A task is one declarative file under `tasks/<site>/` — JSON preferred,
or the YAML subset parsed by `browserbench/yamlmini.py` (plain mappings,
sequences, and scalars; keep YAML simple and prefer JSON for anything
non-trivial). One task per file; the filename should match the task `id`
(e.g. `tasks/shopping/shop-add-to-cart.json`).

Sites: `shop`, `crm`, `sched`, `support` (see `browserbench/spec.py`,
`SITES`). The four sites are synthetic apps in `browserbench/sites.py`
with in-memory, deterministic state — a task can only use state and pages
that its site actually provides. If your task needs a new page, field, or
workflow on a site, that is a site change: implement it in `sites.py`
with tests, in the same PR, and say so in the PR description.

## Anatomy of a task

Annotated example — `tasks/shopping/shop-add-to-cart.json`:

```json
{
  "id": "shop-add-to-cart",
  "version": "1.0.0",
  "site": "shop",
  "title": "Add a product to the cart",
  "goal": "Add one Widget Alpha to the shopping cart.",
  "seed": 1,
  "max_steps": 10,
  "start_url": "/shop/",
  "allowed_actions": ["navigate", "click", "fill", "submit", "done"],
  "allowed_prefixes": ["/shop"],
  "params": {"product": "Widget Alpha", "quantity": 1},
  "reference_plan": [
    {"action": "link", "text": "Widget Alpha"},
    {"action": "submit", "button": "Add to cart"},
    {"action": "expect", "text": "added to your cart"}
  ],
  "success": [
    {"type": "cart_contains", "product": "Widget Alpha", "quantity": 1}
  ]
}
```

Field reference (all fields except `params` and `reference_plan` are
required; see `TaskSpec.from_dict` in `browserbench/spec.py`):

| Field | Meaning |
|---|---|
| `id` | Unique within the task pack, kebab-case, prefixed by site (`shop-…`, `crm-…`, `sched-…`, `support-…`). Never reuse an id. |
| `version` | Semver, starting at `1.0.0`. Bump on any change after publication — never edit a published task in place (see "Versioning" below). |
| `site` | One of `shop`, `crm`, `sched`, `support`. Must match the directory. |
| `title` | Short human-readable name. |
| `goal` | Natural-language goal shown to the agent in every observation. Write it so an agent that has never seen the task can understand it; do not assume knowledge of the site layout beyond what the goal and the starting page show. |
| `seed` | Integer reset seed. The starting state is rebuilt from `initial_state(site, seed)` on every reset, so the same seed always gives the same start. Use `1` unless the task genuinely needs a different starting state. |
| `max_steps` | Step budget; exceeding it ends the run (the state at that point is still scored for partial credit). Must be at least the length of `reference_plan`, and generous enough that a competent agent is not failed by the budget alone. Most bundled tasks use 10–15. |
| `start_url` | Where the run begins, relative to the test server (e.g. `/shop/`). |
| `allowed_actions` | Subset of `navigate`, `click`, `fill`, `submit`, `done`. Only these action types are executable; anything else is blocked and counted as an unsafe attempt. |
| `allowed_prefixes` | URL prefixes the agent may navigate to (e.g. `["/shop"]`). Keep this to the task's own site. The runner also enforces same-host. |
| `params` | Task inputs (product names, form values, appointment ids…). The agent sees the goal, not `params` directly — put everything the agent needs to know in the `goal` text. |
| `reference_plan` | Abstract steps the bundled scripted agent follows (`link`, `submit`, `expect`, …). This is the solvability proof, not a hint for real agents: external agents must derive their own plan from `goal` + `params`. |
| `success` | One or more state conditions (below). A run passes only when **all** of them hold; otherwise it gets partial credit equal to the fraction satisfied. At least one condition is required. |

## Success conditions

Conditions are checked against final site state only, by
`browserbench/evaluator.py` (`CONDITIONS`). Use the most specific
condition available — `state_equals` is the escape hatch, not the
default. Full catalogue:

| Condition | Parameters | Checks |
|---|---|---|
| `cart_contains` | `product`, `quantity` (default 1) | Cart holds at least `quantity` × named product |
| `order_exists` | `product`, `customer?` | A placed order contains the product (and customer, if given) |
| `lead_exists` | `name`, `email?`, `company?`, `status?` | A CRM lead with that name (and given fields) exists |
| `lead_field` | `name`, `field`, `value` | A lead's attribute equals the value |
| `lead_note_contains` | `name`, `text` | A note on the lead contains the text |
| `appointment_exists` | `slot`, `name?` | An appointment exists at the slot (for the name, if given) |
| `appointment_absent` | `id` | The appointment with that id is gone (cancelled) |
| `ticket_exists` | `subject`, `status?` | A support ticket with that subject (and status) exists |
| `ticket_field` | `id`, `field`, `value` | A ticket's attribute equals the value |
| `ticket_reply_contains` | `id`, `text` | A reply on the ticket contains the text |
| `state_equals` | `path`, `value` | A dotted path into site state equals the value (e.g. `cart.<product-id>`) |

Guidelines:

- Prefer positive state assertions ("the order exists") over asserting
  the absence of something, except for genuine deletions/cancellations
  (`appointment_absent`).
- Use `*_contains` conditions for free-text the agent writes (notes,
  replies): exact-match on agent prose is brittle and punishes
  legitimate phrasing.
- Keep the condition count small (bundled tasks use 1–2). More conditions
  means more partial-credit granularity, but also more ways for a task to
  be half-right for the wrong reason.
- Never write a condition that can pass without the agent doing the work
  (e.g. a condition that already holds in the starting state), and never
  write one that inspects the action sequence, timing, or anything
  outside final state. If you need a new condition type, add it to
  `evaluator.py` with tests — do not shoehorn it into `state_equals`.

## Determinism rules

A task must produce the same result for the same
(task version, seed, agent, action sequence) — replay depends on it.

- **No wall-clock, randomness, or network dependence** in the task or
  the site fixtures it touches. Dates, times, and ids in fixtures are
  fixed values (e.g. the scheduling fixtures use `2026-11-20`), not
  "today" or "now".
- **No real-world dependence.** Synthetic data only; never point a task
  at a real website, a real account, or a live service.
- **Fixed starting state.** The seed determines the start; the task must
  not depend on state left over from a previous run. Reset restores the
  starting state exactly — if your task needs a precondition (an existing
  appointment to cancel, a lead to update), it must be part of the
  seeded initial state, and the reference plan must be able to reach it.
- **No hidden information.** Everything the agent needs is in the goal
  and the pages it can navigate to. Do not require knowledge that is
  only in the task file (`params`, `reference_plan`, success conditions).
- **No LLM judge.** Core scoring is state assertions only. If you want a
  qualitative judgement of an agent's behaviour, propose it as a
  separate, clearly marked secondary metric — it must never change the
  core score.

## Reference plans

The `reference_plan` is what the scripted agent (`browserbench/agents.py`,
`ScriptedAgent`) executes step by step. Its steps are abstract
(`link` + visible text, `submit` + button label, `expect` + text that
must appear, `fill` + values). Rules:

- The plan must be **minimal but complete**: the shortest honest path
  from `start_url` to the success state. Do not add sightseeing steps.
- Every `link` text and `submit` button label must match the site's
  actual rendered text exactly — the scripted agent matches on it.
- `max_steps` must be ≥ the plan length, with headroom for a real agent
  (a plan of 6 steps with a budget of 6 is a trap, not a test).
- If the scripted agent cannot pass with your plan, the task is broken,
  not the agent — fix the task or the site, not the plan's expectations.

## Versioning

- New tasks start at `1.0.0`.
- **Never silently change a published task.** If the goal, starting
  state, allowed actions, success conditions, or reference plan need to
  change after results have been published against it, bump the version
  (patch for a fix that does not change what is being tested, minor for
  a change in scope, major for a change in what counts as success) and
  say what changed in `CHANGELOG.md`. Old results stay labelled with
  the version they ran against.
- Replay refuses artifacts whose task version differs from the current
  task file and reports the drift — that is the safety net, not a
  nuisance to work around. If replay refuses your task, you changed a
  published task without bumping its version.
- Never reuse a task `id` for a different task. If a task is withdrawn,
  delete the file and note the removal in `CHANGELOG.md`; do not
  repurpose the id.

## Validation checklist (run all of it)

```bash
# 1. The task loads and validates
python -c "from browserbench.spec import load_tasks; print([t.id for t in load_tasks('tasks') if t.id == '<id>'])"

# 2. The scripted agent passes it (solvability proof)
python -m browserbench run --agent scripted --tasks <id>

# 3. The random baseline does NOT pass it by luck
python -m browserbench run --agent random --tasks <id>

# 4. Replay reproduces the result
python -m browserbench replay runs/<latest>/<id>   # must report match=YES

# 5. Full suite still green, with the count assertion updated
python -m unittest discover -s tests
```

Also run the task by hand once (start the site, follow the goal as a
user would) and check that the goal text is unambiguous: if two
reasonable people disagree about what the task asks for, rewrite the
goal. If the random baseline passes, the task is either trivial or its
success condition already holds at the start — redesign it. If the
scripted agent fails, the plan or the site is wrong — do not weaken the
success condition to make it pass.

## What makes a good task

- **One clear outcome.** "Book the 10:00 slot for Alan Turing" beats
  "do something useful in scheduling". Multi-condition tasks are fine
  when the conditions are facets of one outcome (reply *and* close a
  ticket), not two unrelated chores stapled together.
- **A realistic failure mode.** The best tasks target a known agent
  weakness: pagination, an ambiguous button, a form with a required
  field, a multi-step flow where step 3 depends on step 1, stale
  content after an action. Name the failure mode in the PR description.
- **Grounded in the site.** The task should exercise the site as a user
  would — navigating, reading, filling, submitting — not a shortcut the
  site happens to allow.
- **Fair to any agent.** No task should be solvable only by knowing the
  reference plan, the fixture ids, or the evaluator's internals, and
  none should favour one framework, model, or vendor.

## Review expectations

Task PRs are reviewed for determinism, state-only scoring, versioning,
and neutrality (see [benchmark-integrity.md](benchmark-integrity.md)).
Expect the reviewer to ask: what failure mode does this test, why is
the random baseline's failure meaningful, and could a different
reasonable agent pass it a different way? A task that only the scripted
agent can pass is not a benchmark task — it is a script.
