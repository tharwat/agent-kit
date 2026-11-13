#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Shared Project-facts reader for the kit's hooks. Standard library only.

  read_facts(cwd)                  {NAME: value} from the Project facts table in CLAUDE.md (in $CLAUDE_PROJECT_DIR,
                                   else the nearest one at or above cwd). Missing or unreadable file: {}.
  fact(facts, name, default)       one value, or the default when absent, empty or an unfilled template placeholder.
  current_branch(directory)        the checked-out branch's short name, or None (detached, not a repo, error).
  ticket_for_branch(branch, facts) the ticket key (`ABC-12`) a `<BRANCH_PREFIX><ticket-lowercase>-<slug>` branch
                                   names, or None.
  switched_to(sub, rest, dir)      the branch an in-command `git checkout` / `git switch` moves to (`""` detached,
                                   None when it doesn't switch or we can't tell).
  BranchTracker                    the branch a later `git commit` in the same command lands on.

Reads files and local git state only. No network, no writes.
"""

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
