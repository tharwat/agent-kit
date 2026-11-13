#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Shared Project-facts reader for the kit's hooks. Standard library only.

  read_facts(cwd)                  {NAME: value} from the Project facts table in CLAUDE.md (in $CLAUDE_PROJECT_DIR,
                                   else the nearest one at or above cwd). Missing or unreadable file: {}.
  fact(facts, name, default)       one value, or the default when absent, empty or an unfilled template placeholder.
  project_root(cwd)                the checkout a session works in (a worktree's own root when in one).
  current_branch(directory)        the checked-out branch's short name, or None (detached, not a repo, error).
  ticket_for_branch(branch, facts) the ticket key (`ABC-12`) a `<BRANCH_PREFIX><ticket-lowercase>-<slug>` branch
                                   names, or None.
  switched_to(sub, rest, dir)      the branch an in-command `git checkout` / `git switch` moves to (`""` detached,
                                   None when it doesn't switch or we can't tell).
  BranchTracker                    the branch a later `git commit` in the same command lands on.

Reads files and local git state only. No network, no writes.
"""

import glob
import os
import re
import subprocess

FACT_ROW_RE = re.compile(r"^\|?\s*`?([A-Z][A-Z0-9_]*)`?\s*\|\s*(.*?)\s*(\||$)")  # a leading `|` is optional
PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")


def find_claude_md(cwd):
    """CLAUDE.md in $CLAUDE_PROJECT_DIR, else the nearest one at or above cwd."""
    project = os.environ.get("CLAUDE_PROJECT_DIR")
    if project:
        path = os.path.join(project, "CLAUDE.md")
        if os.path.isfile(path):
            return path
    here = os.path.abspath(cwd or os.getcwd())
    while True:
        path = os.path.join(here, "CLAUDE.md")
        if os.path.isfile(path):
            return path
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent


def read_facts(cwd):
    path = find_claude_md(cwd)
    if not path:
        return {}
    facts = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                m = FACT_ROW_RE.match(line.strip())
                if m and m.group(1) not in facts:
                    facts[m.group(1)] = m.group(2).strip().strip("`").strip()
    except (OSError, UnicodeDecodeError):
        return {}
    return facts


def fact(facts, name, default=None):
    value = (facts or {}).get(name)
    if not value or "{{" in value:
        return default
    return value


def project_root(cwd=None):
    """The checkout a session works in: the git top level of cwd (a worktree's own root), else
    $CLAUDE_PROJECT_DIR, else cwd."""
    cwd = cwd or os.getcwd()
    try:
        # inside a submodule, the project is the superproject; otherwise the checkout's own top level
        out = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-superproject-working-tree", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5)
        lines = [l for l in out.stdout.split("\n") if l.strip()]
        if out.returncode == 0 and lines:
            return lines[0].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return os.environ.get("CLAUDE_PROJECT_DIR") or cwd


def current_branch(directory):
    try:
        out = subprocess.run(["git", "-C", directory, "symbolic-ref", "--short", "-q", "HEAD"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def ticket_for_branch(branch, facts):
    """`feature/abc-12-nav` -> `ABC-12` when BRANCH_PREFIX is `feature/` and TICKET_PREFIX is `ABC`."""
    prefix = fact(facts, "TICKET_PREFIX")
    if not branch or not prefix or not PREFIX_RE.match(prefix):
        return None
    branch_prefix = fact(facts, "BRANCH_PREFIX", "feature/")
    if branch_prefix.lower() == "none":
        branch_prefix = ""
    m = re.match(r"^%s%s-([0-9]+)(?:-|$)" % (re.escape(branch_prefix), re.escape(prefix.lower())), branch)
    if not m:
        return None
    return "%s-%s" % (prefix.upper(), m.group(1))


def ref_exists(directory, ref):
    try:
        out = subprocess.run(["git", "-C", directory, "show-ref", "--verify", "--quiet", ref],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def switched_to(sub, rest, directory, main=None):
    """The branch a `git checkout` / `git switch` in this command moves to: a name, "" for detached, or None when it
    doesn't switch branches (or we can't tell)."""
    def value_of(names):
        for k, a in enumerate(rest):
            for n in names:
                if a == n and k + 1 < len(rest):
                    return rest[k + 1]
                if n.startswith("--") and a.startswith(n + "="):
                    return a.split("=", 1)[1]
                if not n.startswith("--") and a.startswith(n) and len(a) > len(n):
                    return a[len(n):]
        return None

    if "--detach" in rest or (sub == "switch" and "-d" in rest):
        return ""
    created = value_of(("-b", "-B", "--orphan") if sub == "checkout" else
                       ("-c", "-C", "--create", "--force-create", "--orphan"))
    if created:
        return created
    if "--" in rest:
        return None
    pos = [a for a in rest if not a.startswith("-")]
    if len(pos) != 1:
        return None
    name = pos[0]
    if sub == "switch" or name == main:
        return name
    # `git checkout <name>`: a branch only if one exists by that name (else it may be a path)
    if ref_exists(directory, "refs/heads/" + name) or ref_exists(directory, "refs/remotes/origin/" + name):
        return name
    return None


class BranchTracker:
    """The branch each directory is on, as the commands of one tool call run: starts from git, then follows any
    `git checkout -b` / `git switch -c` / `git checkout <branch>` in the command."""

    def __init__(self, main=None):
        self.main = main
        self.branches = {}

    def branch_of(self, directory):
        key = os.path.normpath(directory)
        return self.branches[key] if key in self.branches else current_branch(directory)

    def saw(self, sub, rest, directory):
        if sub in ("checkout", "switch"):
            target = switched_to(sub, rest, directory, self.main)
            if target is not None:
                self.branches[os.path.normpath(directory)] = target or None


# ---------------------------------------------------------------- record-check markers (check-record, session-context)

RECORD_KINDS = ("triage", "operate", "post-op", "handoff")
STALE_SECONDS = 24 * 3600
NUDGED = "nudged"


def read_marker(path):
    """(start time or None, already nudged). The start time is the marker's first word, else its mtime."""
    try:
        with open(path, encoding="utf-8") as fh:
            words = fh.read().split()
    except OSError:
        return None, False
    nudged = NUDGED in words
    try:
        return float(words[0]), nudged
    except (ValueError, IndexError):
        try:
            return os.path.getmtime(path), nudged
        except OSError:
            return None, nudged


def open_markers(state, prefix=".started-"):
    """[(kind, ticket or None, path)] for the markers of known kinds in a `.claude/state` dir: `/handoff`'s at its
    top, the others one level down in their ticket's dir."""
    out = []
    try:
        safe = glob.escape(state)  # a project path may hold [ ] * ?
        paths = sorted(glob.glob(os.path.join(safe, prefix + "*")) +
                       glob.glob(os.path.join(safe, "*", prefix + "*")))
    except OSError:
        return out
    for path in paths:
        kind = os.path.basename(path)[len(prefix):].split(".")[0]
        if kind not in RECORD_KINDS:
            continue
        parent = os.path.dirname(path)
        ticket = None if os.path.normpath(parent) == os.path.normpath(state) else os.path.basename(parent)
        if (kind == "handoff") != (ticket is None):
            continue
        out.append((kind, ticket, path))
    return out


def ticket_dir(state, ticket):
    """`<state>/<ticket>/`, matching an existing dir whatever its case (`abc-12/` for `ABC-12`)."""
    exact = os.path.join(state, ticket)
    try:
        names = [n for n in os.listdir(state) if os.path.isdir(os.path.join(state, n))]
    except OSError:
        return exact
    if ticket in names:
        return exact
    for name in names:  # the name as it is on disk, also on a case-insensitive filesystem
        if name.upper() == ticket.upper():
            return os.path.join(state, name)
    return exact


def state_dirs(cwd=None):
    """Every `.claude/state` a session may have records in, without running git: the nearest one at or above cwd
    (a worktree's own), and $CLAUDE_PROJECT_DIR's."""
    out = []
    here = os.path.abspath(cwd or os.getcwd())
    while True:
        d = os.path.join(here, ".claude", "state")
        if os.path.isdir(d):
            out.append(d)
            break
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        d = os.path.join(env, ".claude", "state")
        if os.path.isdir(d) and os.path.realpath(d) not in [os.path.realpath(x) for x in out]:
            out.append(d)
    return out
