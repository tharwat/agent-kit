---
description: Go/no-go checklist for releasing what is on the main branch to production. Stops for the owner's yes (G1).
argument-hint: "[<last-released-commit-or-tag>]"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# /release

Decides whether `<MAIN_BRANCH>` is ready for production. A production build or release is **G1**: this command
never starts one without the owner's explicit yes.

## Step 1: Scope

A release is what is on `origin/<MAIN_BRANCH>`. Unmerged branches are not in it, whatever their status. The range
starts at the last released commit: take it from the argument, the newest release tag, or what a deploy pack
reports as live. If none of those gives it, stop with NEEDS_CONTEXT.

```bash
git fetch origin
git log --oneline <last-released>..origin/<MAIN_BRANCH>
git diff --stat <last-released>..origin/<MAIN_BRANCH>
```

List the `<TICKET_PREFIX>-<n>` tickets in the range, and any commit with no ticket.

## Step 2: Verification

Run ticket op **get** `<ticket>` (comments and links included) for each ticket. Find the pre-merge `Verify:` record
and the `Post-merge:` record. "Confirmed" means evidence (a verdict, a log line, a query result), never
"should work".

- A commit with no ticket needs its own evidence, or it becomes a condition.
- A post-merge failure blocks until its fix-forward ticket is merged and verified.
- A change to one of the `<CRITICAL_SYSTEMS>` also needs its stricter checks on record.
- Core defines no blocking label. A pack may add one, checked with ticket op **search**.

## Step 3: Env vars

Find every env var the range adds or starts reading, using the range diff and the config and env-example files named
in `docs/agent/source-layout.md`. Each must be confirmed present in production, by a deploy pack's section or by the
owner. Use names only; never print a value.

## Step 4: Migrations

Every schema migration in the range needs:

- the Purpose / Risk / Backout / Validation header (see `/guard`);
- a backout that really reverses it, run through step by step in your head;
- for a destructive step, G5's own yes, and a snapshot when data would be lost.

## Step 5: Rollback plan

In the order the steps would run:

1. **Code**: the previous release to return to. Revert with `git revert` on a new branch through `/ship`, never by
   force-pushing `<MAIN_BRANCH>`. A deploy pack may offer a faster platform rollback.
2. **Schema**: each backout, newest first.
3. **Irreversible effects**: anything from the list in `docs/agent/verify-map.md` that the release may trigger, and
   how to contain each one.
4. **Manual steps**, and who does them.

## Step 6: Pack sections

Run the `## /release` section of each installed `.claude/packs/*.md` (render: services and env groups; supabase:
migration backouts; expo-mobile: store tracks). With no pack section, report
`Pack sections: none installed`.

## Step 7: Report

```
RELEASE CHECKLIST: <last-released>..<release-sha>

Scope:         <N> commits; tickets <keys>; no-ticket commits <shas | none>
Verification:  all confirmed | <ticket>: <what is missing>
Env vars:      none new | <env-var-name>: confirmed | UNCONFIRMED
Migrations:    none | <file>: backout <reverses | MISSING>
Critical:      none touched | <system>: stricter checks <on record | missing>
Pack sections: <one line per pack> | none installed
Rollback plan: 1. <step>  2. <step>

Verdict: GO | CONDITIONAL GO: <exact conditions> | NO-GO: <every blocker>
Owner action: <the G1 yes, or the one blocker to clear>
```

Notify: if `.claude/scripts/notify` exists, run
`.claude/scripts/notify "[<PROJECT_NAME>] Release <range>: <verdict> — <conditions or blockers>"`. If the send
fails, print one line and carry on.

## Step 8: Gate G1

A GO is a verdict, not the owner's yes. After a GO, or a CONDITIONAL GO whose conditions are now met, ask the owner
one question: release now, or hold? Give a pro and a con for each.

- **Yes:** run the release steps from the installed pack sections. With none, the owner releases, and the report
  says so.
- **No, or no answer:** nothing is released.

## Rules

- No GO without confirmed verification for every change in the range.
- No GO with an unconfirmed env var.
- No GO if a migration lacks a backout.
- A CONDITIONAL GO lists the exact conditions. A NO-GO lists every blocker. No vague summaries.
- Never start a production build or release without the G1 yes.

## Completion status

End with exactly one of: **DONE** (GO, with evidence for every check), **DONE_WITH_CONCERNS** (CONDITIONAL GO; list
each condition), **BLOCKED** (NO-GO; list each blocker) or **NEEDS_CONTEXT** (a required check can't be assessed;
say what is missing).
