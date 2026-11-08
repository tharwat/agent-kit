<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Pack: worktrees

For projects that run parallel Claude sessions, each in its own git worktree. Core commands read the matching
section below at their "Packs may add …" lines. The hooks in `.claude/hooks/` read the Pack facts table.

What the hooks do:
- **ensure-worktree** (every prompt): in a worktree under `<WORKTREE_DIR>`, the first prompt fetches and moves a
  clean worktree with no local commits to `origin/<MAIN_BRANCH>` (detached), links missing env files from the main
  checkout and stamps `.claude/state/`. Every prompt states the worktree path and warns when it is behind.
- **block-main-repo-writes** (before Edit, Write, MultiEdit, NotebookEdit): in a worktree session, blocks writes
  into the main checkout, except its `.claude/`.
- **enter-worktree** (after EnterWorktree): syncs the worktree named in the event, the same safe way.
- `/worktree` skill: sync on demand plus a read-only status (`worktree_info.py`).

None of them resets, cleans or overwrites anything. A dirty tree or local commits are left where they are, with a
warning. The log is `.claude/state/worktree.log` in the main checkout. Over 256 KB it is renamed to
`worktree.log.<UTC timestamp>` and a fresh one starts; old logs are kept for the owner to remove.

**Codex** runs no hooks: in a Codex worktree session, run `/worktree`'s two scripts by hand first.

## Pack facts

| Fact | Value | Meaning |
|---|---|---|
| `WORKTREE_DIR` | {{WORKTREE_DIR}} | Where session worktrees live, relative to the main checkout. Default `.claude/worktrees` |
| `WORKTREE_ENV_FILES` | {{WORKTREE_ENV_FILES}} | Untracked env files to symlink from the main checkout into each worktree (comma-separated paths), or `none` |

## /verify

- A worktree has no untracked files of its own. Env files listed in `<WORKTREE_ENV_FILES>` are links to the main
  checkout's copies, so a change to one changes every session's. Anything else untracked (a local config, seed
  output, `node_modules`) is missing until you install or create it in the worktree. Never reach into the main
  checkout for it.
- Another session may already run the dev server. Start yours on a free port, and stop only the process you started.

## /ship

- `<MAIN_BRANCH>` is usually checked out in the main checkout, so git refuses to check it out in a worktree. After the
  merge, use `git checkout --detach origin/<MAIN_BRANCH>` in the worktree.
- `git branch -d <branch>` refuses a branch that another worktree has checked out. Leave it and say so.
