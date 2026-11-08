# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""PostToolUse hook (EnterWorktree): sync the worktree the session just entered.

The worktree path comes from the hook event JSON, never from "the newest directory": two sessions entering
worktrees at once would otherwise sync each other's. Candidates, in order:
1. a path field in tool_response (`worktreePath`, `worktree_path`, `path`);
2. tool_input `path` (entering an existing worktree);
3. tool_input `name` under the main checkout's `.claude/worktrees/` (where EnterWorktree creates new ones);
4. the event's `cwd`.
The first candidate that is a linked worktree under `<WORKTREE_DIR>` is used. None → exit 0, logged.

The sync is the same safe one ensure-worktree does (fetch; `checkout --detach origin/<MAIN_BRANCH>` only on a clean
tree with no local commits; link missing env files; stamp), done once per worktree. Always exits 0.
"""

import json
import os
import sys

sys.dont_write_bytecode = True  # write nothing into .claude/hooks/
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import worktree_common as wc  # noqa: E402
import ensure_worktree  # noqa: E402

RESPONSE_KEYS = ("worktreePath", "worktree_path", "path")
BUILTIN_DIR = os.path.join(".claude", "worktrees")


def candidates(payload):
    out = []
    response = payload.get("tool_response")
    if isinstance(response, dict):
        out.extend(response.get(k) for k in RESPONSE_KEYS)
    tool_input = payload.get("tool_input")
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else None
    if isinstance(tool_input, dict):
        path = tool_input.get("path")
        if isinstance(path, str) and path and not os.path.isabs(path) and cwd:
            path = os.path.join(cwd, path)
        out.append(path)
        name = tool_input.get("name")
        if isinstance(name, str) and wc.safe_relative(name) and cwd:
            base = wc.context_for(cwd)
            if base is not None and base.main:
                out.append(os.path.join(base.main, BUILTIN_DIR, name))
    out.append(cwd)
    return [c for c in out if isinstance(c, str) and c and os.path.isabs(c)]


def main():
    try:
        payload = json.loads(sys.stdin.read() or "null")
    except ValueError:
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") != "EnterWorktree":
        return 0
    for candidate in candidates(payload):
        ctx = wc.context_for(candidate)
        if ctx is None or not ctx.in_worktree:
            continue
        wc.log(ctx.main, f"{ctx.name}: entered via EnterWorktree")
        # A worktree entered before is stamped and not moved again; ensure-worktree warns if it is behind.
        message = ensure_worktree.sync_locked(ctx, force=False) or "already initialized (or being synced); HEAD not moved"
        print(f"[worktree-guard] Entered worktree {ctx.toplevel}. Sync: {message}")
        return 0
    ctx = wc.context_for(payload.get("cwd")) if isinstance(payload.get("cwd"), str) else None
    if ctx is not None and ctx.main:
        wc.log(ctx.main, "EnterWorktree: no worktree under WORKTREE_DIR found in the event; nothing synced")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # fail open
        sys.stderr.write(f"enter-worktree: internal error, skipped ({type(exc).__name__})\n")
        sys.exit(0)
