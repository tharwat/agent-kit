# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""PreToolUse hook (Edit|Write|MultiEdit|NotebookEdit): in a worktree session, block writes into the main checkout.

A worktree session is one whose cwd (from the event JSON) is inside a linked worktree under `<WORKTREE_DIR>` of the
main checkout. In such a session a write to a path in the main checkout is blocked (exit 2, reason on stderr),
except:
- the main checkout's `.claude/` (settings, hooks, memory: shared config that lives there);
- anything inside `<WORKTREE_DIR>` (a worktree, not the main checkout);
- anything outside the main checkout.

Outside a worktree session it allows everything. Internal errors allow, with a one-line stderr note.
"""

import json
import os
import sys

sys.dont_write_bytecode = True  # write nothing into .claude/hooks/
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import worktree_common as wc  # noqa: E402

PATH_KEYS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}


def main():
    try:
        payload = json.loads(sys.stdin.read() or "null")
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    key = PATH_KEYS.get(payload.get("tool_name"))
    tool_input = payload.get("tool_input")
    if key is None or not isinstance(tool_input, dict):
        return 0
    target = tool_input.get(key)
    cwd = payload.get("cwd") or os.getcwd()
    if not isinstance(target, str) or not target or not isinstance(cwd, str):
        return 0

    ctx = wc.context_for(cwd)
    if ctx is None or not ctx.in_worktree:
        return 0
    worktree = ctx.toplevel
    if not os.path.isabs(target):
        target = os.path.join(cwd, target)
    given = os.path.normpath(target)
    target = os.path.realpath(target)

    if wc.is_within(target, worktree) or wc.is_within(target, ctx.worktree_dir):
        return 0
    if not wc.is_within(target, ctx.main):
        return 0
    if wc.is_within(target, os.path.join(ctx.main, ".claude")):
        return 0

    if wc.is_within(given, worktree):
        sys.stderr.write(
            f"BLOCKED: {given} is a link into the main checkout ({target}).\n"
            "Writing through it changes the main checkout's file, which every session shares (an env file, say). "
            "Ask the owner before changing it.\n"
        )
        return 2
    rel = os.path.relpath(target, ctx.main)
    sys.stderr.write(
        "BLOCKED: this session works in a worktree, but the write targets the main checkout.\n"
        f"  Wrong:   {target}\n"
        f"  Correct: {os.path.join(worktree, rel)}\n"
        "Edit the worktree copy. Writes to the main checkout bypass this session's branch and can clobber "
        "another session's work.\n"
    )
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # fail open
        sys.stderr.write(f"block-main-repo-writes: internal error, allowed ({type(exc).__name__})\n")
        sys.exit(0)
