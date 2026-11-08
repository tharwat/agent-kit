---
description: Save the session state to .claude/handoffs/latest.md before a compact or the end of a session.
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# /handoff

Saves the session state for `/resume`. Fully automatic: never ask the user anything. Run it, then compact.

## Step 1: Git state (in parallel)

```bash
git branch --show-current
git log --oneline origin/<MAIN_BRANCH>..HEAD
git diff --stat
git status --short
git stash list
```

Record the branch, the ticket (from a `<BRANCH_PREFIX><ticket-lowercase>-<slug>` branch or a `<TICKET_PREFIX>-<n>`
key in the commits, else `none`), commits ahead, staged and unstaged changes, and stash entries.

## Step 2: Task state

Claude: `TaskList`, recording in-progress and pending tasks. Codex has no task list, so it uses its plan. If either
is empty, work it out from the diff and the conversation.

## Step 3: Session intelligence

- **Where it started**: 2–3 sentences on the original ask, early constraints, and any drift. It stops a fresh
  agent from reopening settled decisions.
- **Decisions**: non-obvious choices, workarounds and why, things ruled out.
- **Verified external facts**: each API, schema or service fact confirmed this session, and how. Nobody should have
  to guess it again.
- **Files in flight**: edited but not committed, with the function or section.
- **Blockers**, including any Owner-Kept Gate waiting for a yes.
- **Environment state**: last migration applied; last dry-run or real run and its result; last deploy observed;
  every live operation performed (production writes, external sends, synthetic row IDs).
- **Next steps**: 3–5 in priority order, each actionable cold with a path, a line and the exact action.
  - BAD: "Fix the bug"
  - GOOD: "Disable submit while the async uniqueness check is in flight, in `src/forms/SignupForm.tsx:142`. The
    check fires, but the button stays enabled."

## Step 4: Write the file

```bash
mkdir -p .claude/handoffs
git check-ignore -q .claude/handoffs/latest.md || echo "not ignored"
```

If it isn't ignored, add `.claude/handoffs/` to `.gitignore`. Then write `.claude/handoffs/latest.md`, replacing the
old one:

```markdown
---
created: <date -u +"%Y-%m-%dT%H:%M:%SZ">
branch: <branch>
ticket: <ticket or "none">
---
# Handoff: <ticket or branch>

## Where it started
## Git state
Branch: <name>. Ahead of <MAIN_BRANCH>: <N>. Commits: <hash message, one per line>.
Uncommitted: <git status --short, or "clean">. Stash: <entries, or "none">.
## Task state
In progress: <items or "none">. Pending: <items or "none">.
## Decisions
- DECIDED: <what> — REASON: <why>
- VERIFIED (external fact): <fact> — CONFIRMED BY: <payload | docs | query>
## Files in flight
## Blockers / pending approvals
## Environment state
- Last migration applied: <name or "none">
- Last dry-run / real run: <what + result, or "none">
- Last deploy observed: <service + status, or "n/a">
- Live operations performed: <what, where, row IDs, or "none">
## Next steps
1. <action — path:line — exactly what to do>
## Pick up here
<one sentence: the most likely next action>
```

## Step 5: Confirm (last thing in the response)

```
Handoff saved → .claude/handoffs/latest.md
Branch: <branch>  Ticket: <ticket>  Ahead: <N>
Tasks: <N> in progress, <N> pending.  Steps: <N>
Ignore: already ignored | added .claude/handoffs/ to .gitignore
Safe to compact.
```

## Rules

- A session with no work still gets a file, with "none" in each section.
- Valid markdown, with no unfilled placeholders.
- Never commit the handoff.
