# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""UserPromptSubmit hook: keep a worktree session pointed at the right tree and base.

Runs only when the session cwd (from the event JSON) is inside a linked worktree under `<WORKTREE_DIR>`.

- First prompt (no stamp in the worktree's `.claude/state/`): fetch origin `<MAIN_BRANCH>`; if the tree is clean
  and has no local commits, `git checkout --detach origin/<MAIN_BRANCH>`, otherwise leave HEAD alone and warn.
  Then symlink each `<WORKTREE_ENV_FILES>` entry from the main checkout when it is missing (never overwrite), and
  stamp. Never resets, never discards.
- Every prompt: print path-guard context (stdout becomes context for the model) and warn when the worktree is
  behind origin/<MAIN_BRANCH>. Fetches again at most every 5 minutes.
- Actions go to the main checkout's `.claude/state/worktree.log`. Over 256 KB it is renamed to
  `worktree.log.<UTC YYYYMMDD-HHMMSS>[-N]` and a fresh log starts; old logs are never overwritten or deleted.

`--now` (used by the /worktree skill) runs the first-prompt sync for the current directory regardless of the stamp.
Always exits 0. Internal errors print a one-line stderr note.
"""

import fcntl
import json
import os
import sys
import time

sys.dont_write_bytecode = True  # write nothing into .claude/hooks/
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import worktree_common as wc  # noqa: E402

STAMP = "worktree-initialized"
LAST_FETCH = "worktree-last-fetch"
LOCK = "worktree.lock"
FETCH_INTERVAL = 300


def initialize(ctx, worktree, state):
    ok, message = wc.sync(ctx, worktree)
    wc.log(ctx.main, f"{ctx.name}: init: {message}")
    for note in wc.link_env_files(ctx, worktree):
        wc.log(ctx.main, f"{ctx.name}: {note}")
    with open(os.path.join(state, STAMP), "w", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    with open(os.path.join(state, LAST_FETCH), "w", encoding="utf-8") as fh:
        fh.write(str(int(time.time())) + "\n")
    return ok, message


def refresh(ctx, worktree, state):
    """Fetch again when the last fetch is older than FETCH_INTERVAL. Never moves HEAD."""
    stamp = os.path.join(state, LAST_FETCH)
    try:
        if time.time() - os.path.getmtime(stamp) < FETCH_INTERVAL:
            return
    except OSError:
        pass
    rc, _, _ = wc.git(["fetch", "--quiet", "origin", ctx.main_branch], worktree, timeout=30)
    if rc != 0:
        wc.log(ctx.main, f"{ctx.name}: fetch of origin {ctx.main_branch} failed")
    with open(stamp, "w", encoding="utf-8") as fh:
        fh.write(str(int(time.time())) + "\n")


def sync_locked(ctx, force):
    """Initialize (when unstamped or forced) or refresh, under a per-worktree lock.

    Returns the init message, or None when nothing was initialized (stamped already, or the lock is held by
    another prompt or session syncing this worktree).
    """
    worktree = ctx.toplevel
    state = wc.state_dir(worktree)
    lock = open(os.path.join(state, LOCK), "w")
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return None
        if force or not os.path.exists(os.path.join(state, STAMP)):
            return initialize(ctx, worktree, state)[1]
        refresh(ctx, worktree, state)
        return None
    finally:
        lock.close()


def run(cwd, force=False):
    ctx = wc.context_for(cwd)
    if ctx is None or not ctx.in_worktree:
        if force:
            print("Not inside a worktree under the configured WORKTREE_DIR; nothing to sync.")
        return 0
    worktree = ctx.toplevel
    init_message = sync_locked(ctx, force)

    base = f"origin/{ctx.main_branch}"
    lines = [
        "[worktree-guard] This session works in a git worktree.",
        f"[worktree-guard] Worktree path: {worktree}",
        f"[worktree-guard] Main checkout: {ctx.main} (file writes there are blocked, except its .claude/)",
        f"[worktree-guard] Every Edit/Write path must start with {worktree}/",
    ]
    if init_message:
        lines.append(f"[worktree-guard] Sync: {init_message}")
    behind = wc.behind_count(ctx, worktree)
    if behind:
        lines.append(
            f"[worktree-guard] WARNING: {behind} commit(s) behind {base}. Before writing code: with a clean tree and "
            f"no local commits, run `git checkout --detach {base}`; with local work, rebase or merge {base} into it.")
    elif behind == 0:
        lines.append(f"[worktree-guard] Up to date with {base} (as of the last fetch).")
    print("\n".join(lines))
    return 0


def main(argv):
    if "--now" in argv:
        return run(os.getcwd(), force=True)
    try:
        payload = json.loads(sys.stdin.read() or "null")
    except ValueError:
        payload = None
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    return run(cwd if isinstance(cwd, str) and cwd else os.getcwd())


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:  # fail open: never block a prompt
        sys.stderr.write(f"ensure-worktree: internal error, skipped ({type(exc).__name__})\n")
        sys.exit(0)
