# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Shared helpers for the worktrees pack hooks. Python 3.9+, stdlib only.

Facts:
- `WORKTREE_DIR` and `WORKTREE_ENV_FILES` come from the Pack facts table in `.claude/packs/worktrees.md`.
- `MAIN_BRANCH` comes from the Project facts table in `CLAUDE.md`.
Both are read from the main checkout first, then from the worktree. A value that is empty, `none` or an unfilled
`{{...}}` placeholder counts as unset and falls back to its default.

Git always runs with an argument list, never through a shell, with a timeout and no terminal prompt.
"""

import datetime
import os
import re
import subprocess

DEFAULT_WORKTREE_DIR = ".claude/worktrees"
DEFAULT_MAIN_BRANCH = "main"
PACK_FACTS = os.path.join(".claude", "packs", "worktrees.md")
PROJECT_FACTS = "CLAUDE.md"
LOG_NAME = "worktree.log"
LOG_CAP_BYTES = 256 * 1024
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def is_within(path, root):
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def git(args, cwd, timeout=20):
    """Run git; return (returncode, stdout, stderr). Never raises on a git failure or timeout."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", LC_ALL="C")
    try:
        proc = subprocess.run(["git"] + list(args), cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", f"{type(exc).__name__}"
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def read_fact(path, name):
    """Value of `name` in a markdown facts table (| `NAME` | value | ...), or None when absent or unset.

    Unset: empty, `none` (any case) or an unfilled `{{...}}` placeholder. Callers then use their default.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    match = re.search(r"^\|\s*`?" + re.escape(name) + r"`?\s*\|([^|\n]*)\|", text, re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip().replace("`", "")
    if not value or "{{" in value or value.lower() == "none":
        return None
    return value


def first_fact(roots, rel_file, name):
    for root in roots:
        if root:
            value = read_fact(os.path.join(root, rel_file), name)
            if value is not None:
                return value
    return None


def safe_relative(item):
    """True for a plain relative path that stays inside its root."""
    return bool(item) and not os.path.isabs(item) and ".." not in re.split(r"[\\/]", item)


class Context:
    """Where a directory sits: its work tree, the main checkout, and the facts."""

    def __init__(self, toplevel, main):
        self.toplevel = toplevel
        self.main = main
        roots = (main, toplevel)
        wdir = first_fact(roots, PACK_FACTS, "WORKTREE_DIR") or DEFAULT_WORKTREE_DIR
        self.worktree_dir = os.path.realpath(os.path.join(main, wdir)) if main else None
        env_value = first_fact(roots, PACK_FACTS, "WORKTREE_ENV_FILES") or "none"
        self.env_files = [] if env_value.lower() == "none" else [
            item for item in re.split(r"[,\s]+", env_value) if safe_relative(item)]
        branch = first_fact(roots, PROJECT_FACTS, "MAIN_BRANCH") or DEFAULT_MAIN_BRANCH
        self.main_branch = branch if BRANCH_RE.match(branch) and not branch.startswith("-") else DEFAULT_MAIN_BRANCH

    @property
    def in_worktree(self):
        """True when this tree is a linked worktree of the main checkout, inside WORKTREE_DIR."""
        return bool(self.main and self.worktree_dir and self.toplevel != self.main
                    and is_within(self.toplevel, self.worktree_dir) and self.toplevel != self.worktree_dir)

    @property
    def name(self):
        return os.path.relpath(self.toplevel, self.worktree_dir) if self.in_worktree else ""


def context_for(directory):
    """Context for a directory inside a git work tree, or None."""
    if not isinstance(directory, str) or not os.path.isdir(directory):
        return None
    rc, out, _ = git(["rev-parse", "--show-toplevel", "--git-common-dir"], directory)
    lines = out.splitlines()
    if rc != 0 or len(lines) != 2:
        return None
    toplevel = os.path.realpath(lines[0])
    common = os.path.realpath(os.path.join(directory, lines[1]))
    main = os.path.dirname(common) if os.path.basename(common) == ".git" else None
    return Context(toplevel, main)


def state_dir(root):
    path = os.path.join(root, ".claude", "state")
    os.makedirs(path, exist_ok=True)
    return path


def rotate_log(path):
    """Rename a full log to <path>.<UTC YYYYMMDD-HHMMSS>[-N]. Never overwrites, never deletes.

    Old logs stay for the owner to remove. os.rename runs only after checking the target doesn't exist.
    """
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = f"{path}.{stamp}"
    n = 1
    while os.path.lexists(target):
        target = f"{path}.{stamp}-{n}"
        n += 1
    os.rename(path, target)
    return target


def log(main, message):
    """Append one line to <main>/.claude/state/worktree.log, rotating it first when over the cap."""
    try:
        path = os.path.join(state_dir(main), LOG_NAME)
        if os.path.exists(path) and os.path.getsize(path) > LOG_CAP_BYTES:
            rotate_log(path)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {message}\n")
    except OSError:
        pass


def sync(ctx, worktree):
    """Fetch, then move a clean worktree with no local commits to origin/<MAIN_BRANCH>, detached.

    Never resets and never discards: a dirty tree or local commits leave HEAD where it is and return a warning.
    Returns (ok, message).
    """
    branch = ctx.main_branch
    remote_ref = f"origin/{branch}"
    rc, _, err = git(["fetch", "--quiet", "origin", branch], worktree, timeout=60)
    if rc != 0:
        return False, f"fetch of origin {branch} failed ({err.splitlines()[-1] if err else 'no detail'}); not synced"
    rc, dirty, _ = git(["status", "--porcelain", "--untracked-files=no"], worktree)
    if rc != 0:
        return False, "git status failed; not synced"
    if dirty:
        return False, f"uncommitted changes; not synced to {remote_ref}"
    rc, ahead, _ = git(["rev-list", "--count", f"{remote_ref}..HEAD"], worktree)
    if rc != 0:
        return False, f"cannot compare HEAD with {remote_ref}; not synced"
    if int(ahead or 0) > 0:
        return False, f"HEAD has {ahead} commit(s) not on {remote_ref}; not synced"
    rc, behind, _ = git(["rev-list", "--count", f"HEAD..{remote_ref}"], worktree)
    if rc == 0 and int(behind or 0) == 0:
        return True, f"already at {remote_ref}"
    rc, _, err = git(["checkout", "--quiet", "--detach", remote_ref], worktree, timeout=60)
    if rc != 0:
        return False, f"checkout --detach {remote_ref} refused ({err.splitlines()[-1] if err else 'no detail'})"
    return True, f"synced to {remote_ref} (detached HEAD)"


def link_env_files(ctx, worktree):
    """Symlink each WORKTREE_ENV_FILES entry from the main checkout. Never overwrites. Returns log lines."""
    notes = []
    for rel in ctx.env_files:
        src = os.path.join(ctx.main, rel)
        dst = os.path.join(worktree, rel)
        if not os.path.isfile(src):
            notes.append(f"env {rel}: missing in the main checkout; not linked")
        elif os.path.lexists(dst):
            notes.append(f"env {rel}: already present; left as is")
        elif not os.path.isdir(os.path.dirname(dst)):
            notes.append(f"env {rel}: no such dir in the worktree; not linked")
        else:
            try:
                os.symlink(src, dst)
                notes.append(f"env {rel}: linked")
            except OSError as exc:
                notes.append(f"env {rel}: link failed ({type(exc).__name__})")
    return notes


def behind_count(ctx, worktree):
    rc, out, _ = git(["rev-list", "--count", f"HEAD..origin/{ctx.main_branch}"], worktree)
    try:
        return int(out) if rc == 0 else None
    except ValueError:
        return None
