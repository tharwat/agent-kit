---
description: Restore session context from .claude/handoffs/latest.md after a compact or at the start of a session.
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# /resume

Restores the session from `.claude/handoffs/latest.md`. Never ask the user anything.

## Step 1: Find the handoff

```bash
ls -la .claude/handoffs/latest.md
```

If it is missing, print `No handoff found at .claude/handoffs/latest.md. Run /handoff before compacting next time.
Starting fresh.` and stop.

## Step 2: Read it and check for drift

Read the whole file, then run in parallel:

```bash
git fetch origin --quiet
git branch --show-current
git log --oneline origin/<MAIN_BRANCH>..HEAD
git status --short
```

Drift is any difference from the handoff: another branch, the branch already merged to `<MAIN_BRANCH>`, new commits,
a changed working tree. A different branch is flagged before anything else.

## Step 3: Rebuild the tasks

Claude: `TaskCreate` each **In progress** item as `in_progress`, then each **Next steps** item, word for word, as
`pending`. Skip none. Codex has no task tool: it puts the same items into its plan in the same order, and the summary
shows `⏭️ Skipped — Codex` in place of the task count.

## Step 4: Orientation summary

```
─────────────────────────────────────────────
RESUMED: <ticket or branch>   Captured: <created>
Branch:  <branch> — <N> ahead of <MAIN_BRANCH>
Pending: <uncommitted changes, or "clean">
─────────────────────────────────────────────
DECISIONS TO REMEMBER
<every DECIDED and VERIFIED (external fact) line>
LIVE STATE
<last deploy observed; live operations performed, with row IDs>
NEXT STEPS (<N> tasks created)
<numbered list>
BLOCKERS (only if any)
<one per line>
─────────────────────────────────────────────
```

If there is drift, add:

```
DRIFT DETECTED
Handoff recorded: <what it said>
Current state:    <what git shows now>
Verify before continuing.
```

End with exactly: `Ready. Continuing from where we left off.`

## Rules

- Always show the decisions and verified external facts. They exist nowhere else.
- Leave the handoff file as it is.
