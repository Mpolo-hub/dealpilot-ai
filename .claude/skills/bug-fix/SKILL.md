---
name: bug-fix
description: Forensic bug-fixing workflow for DealPilot AI (generator, analytics, API, tests, repo config). Use when something is broken or behaves unexpectedly, a test or check fails, a report finds a defect, or the user asks to fix a bug. Covers reproducing the failure, a regression test that fails first, root cause with evidence, the smallest fix, re-verification, the scope check and the report.
---

# Bug fix

Project rules live in `AGENTS.md`; expected behavior in `specs/` and `docs/evaluation.md`.
Commands for checks live in the `feature-development` skill (ruff, pytest, scope check)
and the `synthetic-data-testing` skill (generator and `data/raw` checks). Use them; don't
reinvent them.

## Hard rules
- **Fix the code, not the expectation.** Never change an approved acceptance threshold,
  formula, seed or expected value to make a test pass. If the spec itself looks wrong,
  stop and report it (spec changes need approval).
- **No fix before a root cause.** A change that makes the symptom disappear without an
  explained cause is not a fix.
- Smallest targeted change. No refactors, cleanups or extra features in the same diff.
- Never overwrite `data/raw`; never stage, commit or push (see `AGENTS.md` Rules).

## Workflow
1. **Reproduce.** Get the exact failing command, input or test, and its exact output
   (exit code, error, wrong value). If it can't be reproduced, say so and stop.
2. **Regression test first.** Write a test that fails now for the right reason. Name it
   after the acceptance criterion it violates (`test_ac_NN_...`, `test_ac_api_NN_...`);
   otherwise `test_security_...` in `tests/test_security.py` for security issues, or a
   descriptive `test_..._regression` name. Run it and record the failure. For non-code
   defects (config, `.gitignore`), a test is still preferred; otherwise record a command
   that shows the failure.
3. **Root cause with evidence.** Trace the failure to the responsible line, rule or data
   and show it (file:line, command output, a minimal probe). Grep every caller of the code
   you will touch. Check whether the same cause hides elsewhere (example from this repo:
   the root `data/` ignore rule hid the generator source from git *and* from ruff).
4. **Smallest fix** at the root cause, once, in the shared code. Keep the API contract,
   validation order, error bodies, exact decimal money and the row limit of
   `specs/002-api.md` unless the bug is in one of them and a fix is approved.
5. **Re-verify.** The regression test now passes; then run ruff and pytest as in the
   `feature-development` skill. Add `pytest -m slow` when the generator, data or AC-10
   code is involved.
6. **Generator or data involved:** follow the `synthetic-data-testing` skill. Seed-42 output
   must stay byte-identical to `data/raw` unless an approved behavior change says
   otherwise; all spec 001 acceptance criteria must still pass. AC-12 stays provisional.
7. **Scope check.** Compare file hashes and `git status` as in the `feature-development`
   skill. Only the fix and its test may have changed; report anything else before touching
   it.

## Report
Symptom (with the reproducing command and output), root cause (with evidence), the fix,
the regression test name, exact checks run with exit codes and pass/fail/error counts,
files changed, residual risks, and decisions needing approval. Name every check that could
not run and why; never present an unrun check as passed.
