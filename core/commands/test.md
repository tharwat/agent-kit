---
description: Find the test gaps in the current change, write the missing tests, then run the full suite and prove each contract row.
argument-hint: "[<ticket>]"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# /test

Two jobs: find what the change leaves untested and write those tests, then run the real suite and watch the change
work. `/verify` drives a live surface end to end; `/test` can always run. Read the relevant section of
`docs/agent/lessons.md` first.

## Step 1: Classify the change

```bash
git fetch origin
git diff --name-only origin/<MAIN_BRANCH>...HEAD
git status --short
```

Map each changed file to its test file with `docs/agent/source-layout.md`. Then classify:

- **No runtime surface** (docs, comments, copy with no code path): record `no runtime surface` and stop.
- **Script or job**: it has an entry point you can run.
- **Route, server or webhook**: Step 5 runs it; `/verify` does the full drive.
- **UI**: build it and load the affected view.

## Step 2: Find the gaps

Check that each changed function or route has tests for:

| Scenario | Required |
|---|---|
| Happy path; missing required field; invalid value; database or service failure | Always |
| Unauthenticated or wrong-role request | When auth applies |
| Feature-specific edge cases | Where they apply |
| The idempotency read itself fails: it must abort, not act | When the code checks "already done" before acting |
| External delivery fails after every retry: the failure surfaces, no success log | When it sends to any external service |
| Each query fails on its own and gives an error response | When a handler makes several queries |
| The count is the true total, not the list length | When a handler returns a count and a limited list |
| Each contract row's hostile case | When `.claude/state/<ticket>/triage.md` holds a contract |

Flag every scenario that has no test.

## Step 3: Write the missing tests

- First read the module's existing tests, and match their mocks, helpers, assertions and setup exactly.
- Put tests where `docs/agent/source-layout.md` says. Add no new framework. A new test dependency follows
  `<DEPENDENCY_POLICY>`.
- **The runner loads the env**, so a real client in a test reaches real services, possibly production. Stub every
  external client (database, HTTP, queue, mail, payment, model API), and assert the logic before the call.
- Assert the invariant of the real mechanism, not a proxy for it.
- Never drop a gap silently. Write the test, or flag it as a known gap with the reason.

## Step 4: Run the suite

1. If `<TYPECHECK_COMMAND>` isn't `none`, run it first and fix its errors.
2. Run **every** `<TEST_COMMANDS>` line exactly as written, from its directory. Never a subset, a single file, a
   narrower filter or an ad-hoc script that "checks the same thing". Why: each of those has hidden a red suite that
   was then reported green.
3. Take the counts from the runner's own output, never from a doc or an earlier run.
4. Run `<SYNTAX_CHECK_COMMAND>` on every changed file that has no compiler. Run `<BUILD_COMMAND>` for bundled or UI
   code when it isn't `none`.
5. If anything is red, stop and fix it. Never explain a failure away, or delete or skip a failing test.

Packs may add checks here: see the section for this command in each installed `.claude/packs/*.md`.

## Step 5: Watch it work (the safe ladder)

Start at the cheapest safe rung, and stop at the first that proves the change:

1. **Dry-run.** Use a dry-run entry point (`docs/agent/verify-map.md` lists them, or grep for `dry`), and read its
   "would do X" output.
2. **Read the store.** Query that the written rows landed with the right shape, read-only. Exit code 0 is not
   evidence.
3. **Real run with logs.** Run it and read local output or `<LOG_SINK>`. A production write is G2, except for rows
   marked `<SYNTHETIC_MARKER>`.

Never run anything `docs/agent/verify-map.md` lists as irreversible as a test. If a path can't be exercised, say so
and mark it an unverified gap.

**For a bug fix, show the regression test failing first.** Run it against the pre-fix code and paste the failure,
then run it on the fix and paste the pass. For the pre-fix code, use a disposable `git worktree` at
`origin/<MAIN_BRANCH>` with the test copied in, or `git stash` the fix (never drop the stash). A fix you can't
reproduce, you can't claim.

## Step 6: Contract proof

If `.claude/state/<ticket>/triage.md` holds a contract, record for every row `C<n>`:

- the exact test or probe, and the source path it runs;
- the hostile input, and an assertion on the field, state and branch the row names (a neighbouring input with the
  same label is not coverage);
- the counterfactual: the independently designed bad behaviour that must make it fail, with the failing output.

Run counterfactuals in a disposable worktree or temporary copy, never in the active checkout. A worktree starts at
HEAD, so copy the changed and untracked files in. Use a stubbed env, never production's, and syntax-check after
each mutation. A source scan is a control, not runtime proof. A test that still passes with the guard deleted proves
nothing. The full suite stays mandatory, but it isn't the only proof.

## Step 7: Report

```
TEST REPORT: <ticket or branch>

Change type:   script | route/server | UI | no runtime surface
Gaps found:    none | <function/route>: missing <scenario>
Tests written: none needed | <N> added to <file>
Typecheck:     clean | <file:line — error> | none
Syntax/build:  clean on <N> files | <file — error> | n/a
Suite:         <dir>: <N> passed, <N> failed   (one line per TEST_COMMANDS line)
Rung used:     dry-run | store query | real run + logs | n/a
Evidence:      <dry-run output | query result | log line>
Regression:    failed before, passes after | n/a
Contract:      C1: <test> on <path>; counterfactual <failed | still passed> | no contract

Verdict: PASS | PARTIAL: <what is unverified and why> | FAIL
Owner action: none | <the one action>
```

Notify: if `.claude/scripts/notify` exists, run
`.claude/scripts/notify "[<PROJECT_NAME>] Tests <ticket or branch>: <verdict>, <N> passed, <N> failed"`, naming any
failing tests. If the send fails, print one line and carry on.

## Rules

- Never say it works because it "should". Paste evidence. Never fabricate green output or call a subset the suite.
- A failed proof, an uncovered row or a verified defect is fixed and re-tested on this ticket. Neither a retry count
  nor a follow-up ticket completes the change.
- Tests run against stubs, never live services.

## Completion status

End with exactly one of: **DONE** (tests written and passing, evidence pasted), **DONE_WITH_CONCERNS** (list each
caveat), **BLOCKED** (say why) or **NEEDS_CONTEXT** (details missing to write meaningful tests).

**3 strikes.** If the same failure returns after 3 fix attempts, stop. Don't try a fourth variation:

```
STATUS: BLOCKED
REASON: <1–2 sentences>
ATTEMPTED: <attempt 1> / <attempt 2> / <attempt 3>
RECOMMENDATION: <what to do next>
```

**Escalating is not closing.** The failure stays open, the ticket stays BLOCKED, and nothing ships on it.
