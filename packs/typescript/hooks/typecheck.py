# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""PostToolUse hook (Edit|Write|MultiEdit): type-check the TypeScript package an edit touched.

Called by typecheck.sh. Reads the hook event JSON on stdin.

- Target: an edit to a .ts/.tsx file inside one of the TypeScript package dirs of this repository or of one of its
  git worktrees. The tree is taken from the edited path, never from the cwd.
- Package dirs come from the `TS_PACKAGE_DIRS` row of the Pack facts table in `.claude/packs/typescript.md`
  (comma- or space-separated, relative to the tree root; `.` is the root). `auto`, an empty or an unfilled value
  means: every dir holding a tsconfig.json, up to depth 2. The deepest package containing the file wins.
- Runs that package's own tsc (node_modules/.bin/tsc in the package or a parent inside the tree; never npx, never
  an install) with --noEmit and an incremental cache in .claude/state/tsc-hook/.
- Type errors: exit 2, with a header, the first 30 lines and the true total on stderr.
- Everything else exits 0: clean, not a target, no tsc, a malformed payload, a tsc crash or config error with no
  file-located "error TS" line, a timeout (the whole process group is killed), or a lock held by another check of
  the same package.

The path is only ever an argv element or a filesystem path. It never reaches a shell.
"""

import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys

HOOK_DIR = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(HOOK_DIR))
STATE_DIR = os.path.join(REPO, ".claude", "state", "tsc-hook")
FACTS_FILE = os.path.join(".claude", "packs", "typescript.md")
TOOLS = {"Edit", "Write", "MultiEdit"}
EXTENSIONS = (".ts", ".tsx")
MAX_LINES = 30
SCAN_DEPTH = 2
SKIP_DIRS = {"node_modules"}
# Only errors located in a file count: "src/a.ts(1,2): error TS2322: ...". A bare "error TS5023: ..." is a config
# problem, which is not the edit's fault, so the hook fails open on it.
ERROR_RE = re.compile(r"\(\d+,\d+\): error TS\d+")


def timeout_seconds():
    try:
        return max(1, int(os.environ.get("TSC_HOOK_TIMEOUT", "60")))
    except ValueError:
        return 60


def is_within(path, root):
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def common_git_dir(root):
    """The shared .git dir of a work tree root: <root>/.git, or the main repo's .git for a linked worktree."""
    dot_git = os.path.join(root, ".git")
    if os.path.isdir(dot_git):
        return os.path.realpath(dot_git)
    if not os.path.isfile(dot_git):
        return None
    try:
        with open(dot_git, encoding="utf-8") as fh:
            first = fh.readline().strip()
    except OSError:
        return None
    if not first.startswith("gitdir:"):
        return None
    gitdir = first[len("gitdir:"):].strip()
    gitdir = os.path.realpath(os.path.join(root, gitdir))
    commondir_file = os.path.join(gitdir, "commondir")
    if os.path.isfile(commondir_file):
        try:
            with open(commondir_file, encoding="utf-8") as fh:
                return os.path.realpath(os.path.join(gitdir, fh.readline().strip()))
        except OSError:
            return None
    parent = os.path.dirname(gitdir)
    if os.path.basename(parent) == "worktrees":
        return os.path.dirname(parent)
    return None


def tree_root(path):
    """Nearest ancestor of path holding a .git entry, or None."""
    current = os.path.dirname(path)
    while True:
        if os.path.lexists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def read_fact(path, name):
    """Value of `name` in a markdown facts table (| `NAME` | value | ...), or None."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    match = re.search(r"^\|\s*`?" + re.escape(name) + r"`?\s*\|([^|\n]*)\|", text, re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip().replace("`", "")
    if not value or "{{" in value:
        return None
    return value


def scan_packages(root):
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        depth = 0 if dirpath == root else os.path.relpath(dirpath, root).count(os.sep) + 1
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
        if depth >= SCAN_DEPTH:
            dirnames[:] = []
        if "tsconfig.json" in filenames:
            found.append(dirpath)
    return found


def package_dirs(root):
    value = read_fact(os.path.join(root, FACTS_FILE), "TS_PACKAGE_DIRS")
    if value is None:
        value = read_fact(os.path.join(REPO, FACTS_FILE), "TS_PACKAGE_DIRS")
    if value is None or value.lower() == "auto":
        return scan_packages(root)
    dirs = []
    for item in re.split(r"[,\s]+", value):
        if not item or os.path.isabs(item) or ".." in item.split("/"):
            continue
        full = os.path.normpath(os.path.join(root, item))
        if is_within(full, root):
            dirs.append(full)
    return dirs


def find_tsc(package, root):
    current = package
    while is_within(current, root):
        candidate = os.path.join(current, "node_modules", ".bin", "tsc")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
        if current == root:
            break
        current = os.path.dirname(current)
    return None


def target(path):
    """(tree root, package dir) for an edit worth checking, else None."""
    if not isinstance(path, str) or not os.path.isabs(path) or not path.endswith(EXTENSIONS):
        return None
    path = os.path.realpath(path)
    if not path.endswith(EXTENSIONS) or os.sep + "node_modules" + os.sep in path:
        return None
    root = tree_root(path)
    if root is None:
        return None
    repo_common = common_git_dir(REPO)
    if repo_common is None or common_git_dir(root) != repo_common:
        return None  # not this repository or one of its worktrees
    candidates = [d for d in package_dirs(root) if is_within(path, d)]
    if not candidates:
        return None
    return root, max(candidates, key=len)


def main():
    try:
        payload = json.loads(sys.stdin.read() or "null")
    except ValueError:
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") not in TOOLS:
        return 0
    tool_input = payload.get("tool_input")
    path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    found = target(path)
    if found is None:
        return 0
    root, package = found
    tsconfig = os.path.join(package, "tsconfig.json")
    tsc = find_tsc(package, root)
    if tsc is None or not os.path.isfile(tsconfig):
        return 0  # e.g. a worktree before npm install: never install anything

    os.makedirs(STATE_DIR, exist_ok=True)
    key = hashlib.sha1(package.encode("utf-8")).hexdigest()[:12]
    lock = open(os.path.join(STATE_DIR, key + ".lock"), "w")
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0  # another check of this package is running; it will report
        proc = subprocess.Popen(
            [tsc, "--noEmit", "-p", tsconfig, "--incremental",
             "--tsBuildInfoFile", os.path.join(STATE_DIR, key + ".tsbuildinfo"), "--pretty", "false"],
            cwd=package, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            out, _ = proc.communicate(timeout=timeout_seconds())
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            proc.communicate()
            sys.stderr.write("typecheck hook: tsc timed out; skipped\n")
            return 0
    finally:
        lock.close()
    if proc.returncode == 0:
        return 0
    lines = out.decode("utf-8", "replace").splitlines()
    errors = [line for line in lines if ERROR_RE.search(line)]
    if not errors:
        sys.stderr.write("typecheck hook: tsc failed without a type error (config problem?); skipped\n")
        return 0
    rel_file = os.path.relpath(os.path.realpath(path), root)
    rel_pkg = os.path.relpath(package, root)
    sys.stderr.write(f"Type check of {rel_pkg} failed after editing {rel_file} ({len(errors)} errors total):\n")
    sys.stderr.write("\n".join(lines[:MAX_LINES]) + "\n")
    if len(lines) > MAX_LINES:
        sys.stderr.write(f"... {len(lines) - MAX_LINES} more lines; run tsc --noEmit in {rel_pkg}\n")
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # fail open: a broken hook must never block unrelated work
        sys.stderr.write(f"typecheck hook: internal error, skipped ({type(exc).__name__})\n")
        sys.exit(0)
