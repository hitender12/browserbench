# Security Policy

## Supported versions

BrowserBench is at its initial release. Only the latest release line
receives security fixes.

| Version | Supported with security fixes |
|---|---|
| 0.1.x | Yes |
| < 0.1 | No (no earlier release exists) |

When a new minor version ships, the previous line is supported only until
the release notes say otherwise; security fixes are not backported to
unsupported versions.

## How to report a vulnerability

**Do not open a public GitHub issue for a vulnerability.** Use GitHub's
private vulnerability reporting on this repository (Security tab →
"Report a vulnerability"). That keeps the details private until a fix is
ready. If private reporting is unavailable to you, contact a maintainer
privately through GitHub and ask for a secure channel — do not post
exploit details in a public issue, discussion, or pull request.

Please include, where you can:

- What the vulnerability is and where it lives (file, endpoint, task, or
  adapter — e.g. `browserbench/runner.py`, the `/__reset__` handling, or
  the HTTP agent protocol).
- Steps to reproduce, ideally a minimal task/agent and the exact command.
- The BrowserBench version (`python3 -m browserbench --version`) and
  Python version.
- The impact you see: what an attacker (or a malicious agent/task) could
  do that the safety boundary is supposed to prevent.
- Whether the issue is already being exploited, if you know.

What happens next: maintainers will acknowledge the report, investigate,
and work on a fix. There is no formal response-time SLA in v0.1.0 —
reports are triaged as maintainer time allows — but security reports are
treated as the highest-priority work. Once a fix is ready we will ship a
release, describe the issue in `CHANGELOG.md` (without a working exploit),
and credit the reporter if they want to be credited. Please do not
disclose the vulnerability publicly until the fix is released.

## Scope

BrowserBench is a **local test harness for synthetic websites**. Its
threat model is deliberately narrow, and the scope of this policy is:

- The core package (`browserbench/`), the CLI, the task loader
  (`spec.py`), the evaluator (`evaluator.py`), the runner and its safety
  boundary (`runner.py`), the test-site server (`sites.py`), trace and
  replay (`trace.py`, `replay.py`), and the bundled agents (`agents/`).
- The task definitions in `tasks/` and the task format itself (for
  example, a task that could escape its site or smuggle state past the
  evaluator).

Out of scope: vulnerabilities in third-party tools you connect to
BrowserBench (your model provider, your browser, your OS), and issues
that only arise if you point the harness at a real website or a real
account — that is explicitly unsupported (see below).

## What is safe by design — and what is not

**Safe by design (please report it if any of this fails):**

- Test sites are synthetic and served locally. `sites.make_server()`
  binds `127.0.0.1` on an ephemeral port; nothing in the harness listens
  on a public interface, and the runner's client and the site coexist on
  the same machine.
- The safety boundary in `runner.py` validates every agent action before
  execution: the action type must be in the task's `allowed_actions`,
  the target URL must start with one of the task's `allowed_prefixes`
  and share the test server's host, and `/__state__` and `/__reset__`
  are never navigable by an agent. Violations are blocked, counted in
  `metrics.unsafe_attempts`, and recorded in the trace.
- All test data is synthetic (invented products, leads, appointments,
  tickets). No real accounts, credentials, or personal data are bundled
  or required.
- The core package has zero dependencies (standard library only), so
  there is no third-party supply chain inside the harness itself.

**Known limitations — do not rely on the harness for these:**

- **Agent code is executed, not sandboxed.** Running
  `python3 -m browserbench run --agent ./agents/some-agent.py` imports
  and executes that file with your user privileges. Only run agent files
  you have read and trust; never run an agent file from an untrusted
  pull request, download, or task submission without reviewing it first.
  The same applies to HTTP agents you point the runner at: the runner
  trusts whatever the agent server returns as an action (subject to the
  safety boundary above), so only connect to agent servers you control.
- **No authentication or multi-user isolation.** The test sites are
  in-memory, single-user, with no auth and no persistence. They must
  never be exposed to a network or used with real data.
- **No real browser (yet).** The current build drives sites over local
  HTTP with a parsed-DOM observation — no Playwright, no screenshots or
  video. Do not treat a local pass as evidence about real-browser
  rendering or JavaScript behaviour.
- **Traces and run artifacts are local files** under `runs/` and may
  contain task parameters and action sequences. They contain only
  synthetic data by design, but do not publish a run directory without
  checking it first, and never put real credentials, tokens, or API keys
  into a task file, an agent file, or a run config — the harness has no
  secret handling and will happily record whatever you give it.
- **No LLM judge is bundled.** If one is added later, it must be a
  clearly marked secondary metric that never changes the core state-based
  score (see `docs/benchmark-methodology.md`).

## If you find a security problem in a task or adapter

A task that escapes its site, reads harness state (`/__state__`,
`/__reset__`), or makes the evaluator pass without performing the work
is a security defect in the benchmark, not a clever agent. Report it
privately as above; do not publish a "bypass" as a demo. The same applies
to an adapter that peeks at a task's `reference_plan` or site state at
run time.
