---
description: Check new or changed code for diagnosable logging, covering the prefix, required log points, swallowed failures, and secrets or PII.
argument-hint: "[<ticket>]"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# /observability

Makes sure failures can be diagnosed from `<LOG_SINK>`. Run it after changing a route, middleware, a job, a webhook
handler or an external-service call.

## Step 1: Scope

```bash
git fetch origin
git diff origin/<MAIN_BRANCH>...HEAD
git diff
```

Find every new or changed function in these places (locations are in `docs/agent/source-layout.md`):

- route handlers and middleware;
- background and scheduled jobs. A scheduler wrapper's own start/success/failure logs don't replace the job's
  business-logic logs;
- webhook and inbound-message handlers;
- every caller of a service in `docs/agent/integrations.md`.

## Step 2: Log format

Every log line uses the prefix style in `.claude/rules/code-style.md`. Flag each line that doesn't, with the exact
corrected line. Why: a line without the prefix can't be found by searching the sink.

## Step 3: Required log points

| Point | Logs | Level |
|---|---|---|
| Start | What it is doing, plus a key identifier (masked) | info |
| Success | The outcome: what landed or was sent | info |
| Failure | The error context, with no secrets or PII | error |

Every new handler or job needs all three.

**A catch that logs and carries on where it should throw is a finding**, not a style nit. The job reports success
when nothing happened. Background delivery and idempotency reads must throw so the caller records the failure.

## Step 4: Secrets and PII

Flag any line that could emit:

- **secrets**: API keys, bearer, session or JWT tokens, webhook secrets, passwords, connection strings, signed URLs;
- **PII**: any field in `docs/agent/pii.md`, unless it is masked the way that file says;
- **bulk data**: full request or response payloads, full message contents, raw headers.

Give the masked or removed version. Security issues outside logging go to `/security`.

## Step 5: Hardcoded counts

When a log line or response carries a hardcoded count (`jobs: N`, "Loaded N items"), count the real items in the
same file. If they differ, flag it and give the right number.

## Step 6: Report

```
OBSERVABILITY AUDIT: <ticket or branch>

Log format:       all prefixed | <file:line> → <corrected line>
Required points:  all present | <handler>: missing <start|success|failure> → <line to add>
Swallowed errors: none | <file:line> logs and continues → <throw>
Secrets/PII:      none | <file:line> logs <what> → <fix>
Hardcoded counts: match | n/a | <file:line> says N, actual M

Verdict: CLEAR | FIXES NEEDED
Required fixes:
  1. <file:line> — <exact corrected statement>
Owner action: none | <the one action>
```

## Rules

- Give the exact corrected statement for every violation.
- Never delete a log to fix its format.
- If the right fix is unclear, flag it instead of guessing.

## Completion status

End with exactly one of: **DONE** (every violation has an exact fix), **DONE_WITH_CONCERNS** (list the follow-ups),
**BLOCKED** (the diff or files can't be read; say why) or **NEEDS_CONTEXT** (say what is needed).
