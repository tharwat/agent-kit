#!/bin/sh
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
# Runs one worktrees-pack hook: worktree-hook.sh <block_main_repo_writes|ensure_worktree|enter_worktree>
# The logic is in <name>.py. Fails open: no python3, an unknown name, or any exit other than 2, allows.
# Tests: python3 -m unittest discover -s .claude/hooks -p 'test_*worktree*.py'
case "$1" in
  block_main_repo_writes|ensure_worktree|enter_worktree) ;;
  *) echo "worktree-hook: unknown hook '$1'; skipped" >&2; exit 0 ;;
esac
command -v python3 >/dev/null 2>&1 || { echo "worktree-hook: python3 not found; skipped" >&2; exit 0; }
python3 "$(dirname "$0")/$1.py"
[ "$?" -eq 2 ] && exit 2
exit 0
