---
description: Find and confirm the root cause of a bug or regression before fixing it, then prove the fix.
argument-hint: "[<ticket> | <symptom>]"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# /investigate

**Iron law: no fix without a confirmed root cause.** A symptom fix makes the next bug harder to find.

## Phase 1: Gather evidence

1. **Read the error**: full message, stack trace, exact steps. For an integration failure, read the real error
   response body; it usually names the cause (wrong scope, account or endpoint). Vendor docs are listed in
   `docs/agent/integrations.md`.
2. **Recent changes.** If it worked before, the cause is in the diff.
   ```bash
   git fetch origin
   git log --oneline -20 origin/<MAIN_BRANCH> -- <affected-files>
   git diff --name-only origin/<MAIN_BRANCH>...HEAD
   ```
3. **Reproduce it.** If you can't trigger it reliably, gather more evidence first.
4. **Deployed bug:** search `<LOG_SINK>` (skip if `none`) for the suspect file's log prefix
   (`.claude/rules/code-style.md`).
5. Read the relevant section of `docs/agent/lessons.md`.

Output: `Evidence gathered: <what you know>`.

## Negative-space check

Ask what the code is **not** doing. Most failures are in a sibling path that wasn't changed.

1. What downstream thing is involved: a write, an external call, a response, a render?
2. Grep every call site that reaches it.
3. Which paths changed, and which didn't? A sibling that reaches the same function without the same guard is the
   likely root cause. The reported path only shows the symptom.

Check the known traps in `docs/agent/sibling-paths.md`.

## Phase 2: Match a pattern

| Pattern | Signature | Look at |
|---|---|---|
| Race / double-fire | Intermittent; duplicates under load or with concurrent deliveries | An idempotency read that ignores its own error; concurrent writes; webhook retries |
| Null propagation | "Cannot read property of undefined"; empty result used as a row | Single-row reads that throw vs return empty; missing optional chaining |
| State corruption | Inconsistent UI, partial updates, stale values | State stores, effect dependencies, multi-step writes with no transaction |
| Integration failure | Timeout, 4xx/5xx, odd response | The vendor's error body |
| Contract drift | A field is suddenly undefined | A field renamed on our side but not in its consumers, or a changed external shape. Check a real payload or docs read this session |
| Config drift | Works in one environment, not another | Env vars present? Secrets set? Right account, project, URL? |
| Stale cache | Old data until refresh or restart | Client caches, token refresh, local storage |
| Type mismatch | Silently wrong value | Loose casts, changed response shapes, parsing |
| Fail-open swallow | Job reports success, nothing happened | A catch that logs and continues where it should throw |

Packs may add checks here: see the section for this command in each installed `.claude/packs/*.md`.

## Phase 3: Hypothesis and scope

> Root cause hypothesis: <a specific, testable claim about what is wrong and why>.

Write the affected directory to `investigate-scope.txt` in the scratch dir: the session scratch directory if there
is one, else `.claude/state/tmp/`, never the system temp dir. Report `Scope locked to <dir>/.`, and make no edits
outside it. If the bug really spans the codebase, skip the lock and say why.

## Phase 4: Confirm the hypothesis

Before any fix, put a temporary log line or assertion at the suspected cause, reproduce, and confirm it fires as
predicted. If it doesn't, go back to Phase 2. Remove the instrumentation before the fix is committed.

**3 strikes.** If 3 hypotheses fail, stop:

```
STATUS: BLOCKED
REASON: 3 hypotheses tested, none match the evidence
ATTEMPTED: <h1> / <h2> / <h3>
RECOMMENDATION: <add instrumentation | escalate | architecture review>
```

Red flags: "quick fix for now"; a fix proposed before the data flow is traced; each fix revealing a new problem (the
wrong layer).

## Phase 5: Fix the root cause

1. Make the smallest change that removes the cause.
2. Write a regression test that **fails before the fix and passes after**, and paste both runs (`/test` Step 5).
3. If no unit test is possible, **demonstrate it**: reproduce, fix, and show the behaviour with a dry-run, a store
   query or a log line. Record why there is no test.
4. Run every `<TEST_COMMANDS>` line exactly, and paste the counts.
5. If the fix touches more than 5 files, stop and ask the owner one question: proceed, or find a narrower fix? Give
   a pro and a con for each.

## Phase 6: Verify and report

Reproduce the original scenario again and show it is fixed. This is not optional.

```
DEBUG REPORT
Symptom:      <observed>
Root cause:   <what was wrong, file:line>
Pattern:      <from Phase 2>
Fix:          <file:line>
Evidence:     <failed-then-fixed output | log line | query result>
Regression:   <test file:line> | demonstrated: <how; why no test>
Blast radius: <N files>
Status:       <completion status>
Owner action: none | <the one action>
```

Notify: if `.claude/scripts/notify` exists, run
`.claude/scripts/notify "[<PROJECT_NAME>] Investigate <ticket or symptom>: <status>. Root cause: <one line>"`. If
the send fails, print one line and carry on.

## Rules

- Never skip Phase 4. Never ship a fix you can't verify.
- For an integration bug, read the real error response before theorizing.
- A regression test must fail before the fix.
- Never say "this should fix it". Demonstrate it.

## Completion status

End with exactly one of: **DONE** (cause confirmed, fixed, proved, suite green), **DONE_WITH_CONCERNS** (fixed but
not fully verifiable; say why), **BLOCKED** (cause unclear or 3 strikes) or **NEEDS_CONTEXT** (missing repro, logs
or access).
