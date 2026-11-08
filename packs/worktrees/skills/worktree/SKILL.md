---
name: worktree
description: Sync and check this session's git worktree against origin's main branch, then show its status. Use when the user types /worktree or asks to fix, sync or check a worktree.
allowed-tools: Bash
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

# /worktree

Run from the session's working directory, in order:

1. `python3 .claude/hooks/ensure_worktree.py --now`
   - In a worktree under the pack's `WORKTREE_DIR`: fetches, then moves the worktree to
     `origin/<main branch>` (detached) **only** if the tree is clean and has no local commits; otherwise it leaves
     HEAD alone and says why. Links missing env files from the main checkout. It never resets or discards.
   - Anywhere else it says there is nothing to sync.
2. `python3 .claude/hooks/worktree_info.py`: read-only status of this worktree, or of every worktree when run from
   the main checkout, plus the tail of `.claude/state/worktree.log`.

Report both outputs. Then, if step 1 refused to sync:
- **Uncommitted changes or local commits:** don't touch them. Tell the user, and offer to rebase or merge
  `origin/<main branch>` into the branch. Never reset, never discard, never stash on their behalf without asking.
- **Fetch failed:** report the error line; the sync runs again on the next `/worktree`.

Notes:
- This skill doesn't create worktrees. For a new one, start `claude --worktree <name>` from the repo root, or ask
  Claude to enter a worktree (the EnterWorktree tool).
- The main branch comes from `MAIN_BRANCH` in `CLAUDE.md`; the worktree dir and env files from
  `.claude/packs/worktrees.md`.
- **Codex:** Codex runs no hooks, so nothing syncs or guards a Codex worktree automatically. At the start of a Codex
  session in a worktree, run steps 1 and 2 by hand, and edit only paths inside the worktree.
