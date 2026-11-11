#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Shared Project-facts reader for the kit's hooks. Standard library only.

  read_facts(cwd)                  {NAME: value} from the Project facts table in CLAUDE.md (in $CLAUDE_PROJECT_DIR,
                                   else the nearest one at or above cwd). Missing or unreadable file: {}.
  fact(facts, name, default)       one value, or the default when absent, empty or an unfilled template placeholder.
  current_branch(directory)        the checked-out branch's short name, or None (detached, not a repo, error).
  ticket_for_branch(branch, facts) the ticket key (`ABC-12`) a `<BRANCH_PREFIX><ticket-lowercase>-<slug>` branch
                                   names, or None.

Reads files and local git state only. No network, no writes.
"""

import os
import re
import subprocess

FACT_ROW_RE = re.compile(r"^\|\s*`?([A-Z][A-Z0-9_]*)`?\s*\|\s*(.*?)\s*\|")
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
