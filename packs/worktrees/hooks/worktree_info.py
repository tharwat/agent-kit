# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Read-only worktree status, used by the /worktree skill.

Usage: python3 .claude/hooks/worktree_info.py [<worktree path>]

With no path: the current worktree when the cwd is in one, else every worktree under `<WORKTREE_DIR>`.
For each: branch and short status, ahead/behind origin/<MAIN_BRANCH> as of the last fetch, last commit, env links.
Then the last 20 lines of `.claude/state/worktree.log`. It writes nothing and never fetches.
"""

import os
import sys

sys.dont_write_bytecode = True  # write nothing into .claude/hooks/
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import worktree_common as wc  # noqa: E402

LOG_TAIL = 20


def worktrees_of(ctx):
    rc, out, _ = wc.git(["worktree", "list", "--porcelain"], ctx.main)
    paths = []
    if rc == 0:
        for line in out.splitlines():
            if line.startswith("worktree "):
                path = os.path.realpath(line[len("worktree "):])
                if path != ctx.main and wc.is_within(path, ctx.worktree_dir):
                    paths.append(path)
    return paths


def report(ctx, worktree):
    base = f"origin/{ctx.main_branch}"
    print(f"Worktree: {worktree}")
    _, status, _ = wc.git(["status", "-sb"], worktree)
    print("  Status:")
    for line in (status or "(unavailable)").splitlines()[:15]:
        print(f"    {line}")
    rc, counts, _ = wc.git(["rev-list", "--left-right", "--count", f"{base}...HEAD"], worktree)
    if rc == 0 and len(counts.split()) == 2:
        behind, ahead = counts.split()
        print(f"  Against {base} (last fetch): {ahead} ahead, {behind} behind")
    else:
        print(f"  Against {base}: unknown (no such ref yet?)")
    _, last, _ = wc.git(["log", "-1", "--format=%h %s (%cr)"], worktree)
    print(f"  Last commit: {last or '(none)'}")
    stamp = os.path.join(worktree, ".claude", "state", "worktree-initialized")
    try:
        with open(stamp, encoding="utf-8") as fh:
            print(f"  Initialized: {fh.readline().strip()}")
    except OSError:
        print("  Initialized: no (the next prompt in this worktree will sync it)")
    if ctx.env_files:
        print("  Env files:")
        for rel in ctx.env_files:
            full = os.path.join(worktree, rel)
            if os.path.islink(full):
                print(f"    linked   {rel} -> {os.readlink(full)}")
            elif os.path.exists(full):
                print(f"    present  {rel} (a real file, not a link)")
            else:
                print(f"    missing  {rel}")
    print()


def main(argv):
    start = argv[0] if argv else os.getcwd()
    ctx = wc.context_for(os.path.abspath(start))
    if ctx is None or not ctx.main:
        print(f"Not in a git work tree with a main checkout: {start}")
        return 0
    if ctx.in_worktree:
        targets = [ctx.toplevel]
    else:
        targets = worktrees_of(ctx)
        if not targets:
            print(f"No worktrees under {ctx.worktree_dir}")
    for worktree in targets:
        report(wc.context_for(worktree) or ctx, worktree)
    log = os.path.join(ctx.main, ".claude", "state", wc.LOG_NAME)
    print(f"Last {LOG_TAIL} lines of {log}:")
    try:
        with open(log, encoding="utf-8") as fh:
            for line in fh.readlines()[-LOG_TAIL:]:
                print(f"  {line.rstrip()}")
    except OSError:
        print("  (no log yet)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:
        sys.stderr.write(f"worktree-info: internal error ({type(exc).__name__})\n")
        sys.exit(1)
