#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""SessionStart hook (startup, resume, compact): put the ticket's state back in context.

Prints at most 15 lines, which Claude Code adds to the context:
  - the branch, the ticket it names, commits ahead of origin/<MAIN_BRANCH> (local refs only, no fetch) and the
    count of changed files;
  - which records exist in .claude/state/<ticket>/ (triage.md, self-review.md, post-op.md with its Result), and a
    pointer to read the contract first;
  - a workflow command that started and never finished its record;
  - a handoff newer than the last commit: run /resume (said more strongly right after a compaction).

Never prints file contents, only paths and status words. Not a git repo: prints nothing. Always exits 0; one stderr
line on an internal error. Reads local files and git state only. No network, no writes.
"""

import glob
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True  # never leave __pycache__ in .claude/hooks/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import kit_facts
except ImportError:
    kit_facts = None

MAX_LINES = 15
RESULTS = ("clean", "capped", "escalate")


def git(project, *args):
    try:
        out = subprocess.run(["git", "-C", project] + list(args), capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def post_op_result(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("Result:"):
                    word = line.split(":", 1)[1].strip().split(" ")[0]
                    if word in RESULTS:
                        return word
    except OSError:
        pass
    return "no Result line"


def lines_for(project, source):
    if git(project, "rev-parse", "--is-inside-work-tree") != "true":
        return []
    facts = kit_facts.read_facts(project)
    main = kit_facts.fact(facts, "MAIN_BRANCH", "main")
    branch = kit_facts.current_branch(project)
    ticket = kit_facts.ticket_for_branch(branch, facts)
    ahead = git(project, "rev-list", "--count", "origin/%s..HEAD" % main)
    status = git(project, "status", "--porcelain")
    dirty = len([l for l in (status or "").split("\n") if l.strip()]) if status is not None else "?"
    out = ["agent-kit session context (%s):" % source,
           "- Branch: %s · ticket: %s · %s commits ahead of origin/%s · %s changed files"
           % (branch or "detached HEAD", ticket or "none", ahead if ahead is not None else "?", main, dirty)]
    if branch == main:
        out.append("- You are on %s: start a ticket branch before changing code." % main)

    state = os.path.join(project, ".claude", "state")
    if ticket and os.path.isdir(os.path.join(state, ticket)):
        d = os.path.join(state, ticket)
        have = []
        for name in ("triage.md", "self-review.md"):
            if os.path.isfile(os.path.join(d, name)):
                have.append(name)
        if os.path.isfile(os.path.join(d, "post-op.md")):
            have.append("post-op.md (Result: %s)" % post_op_result(os.path.join(d, "post-op.md")))
        out.append("- Records in .claude/state/%s/: %s" % (ticket, ", ".join(have) or "none yet"))
        if "triage.md" in have:
            out.append("- Read `.claude/state/%s/triage.md` (the contract) before continuing." % ticket)

    for marker in sorted(glob.glob(os.path.join(state, ".started-*")) + glob.glob(os.path.join(state, "*",
                                                                                              ".started-*"))):
        kind = os.path.basename(marker)[len(".started-"):]
        parent = os.path.basename(os.path.dirname(marker))
        where = "" if os.path.dirname(marker) == state else " for %s" % parent
        out.append("- /%s%s started and hasn't written its record yet." % (kind, where))

    handoff = os.path.join(project, ".claude", "handoffs", "latest.md")
    if os.path.isfile(handoff):
        last = git(project, "log", "-1", "--format=%ct")
        if not last or os.path.getmtime(handoff) > float(last):
            if source == "compact":
                out.append("- Context was just compacted and a handoff exists: run /resume now, before anything "
                           "else.")
            else:
                out.append("- A handoff exists (.claude/handoffs/latest.md): run /resume.")
    return out[:MAX_LINES]


def main():
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
        if kit_facts is None:
            raise ImportError("kit_facts.py is missing")
        project = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
        out = lines_for(project, event.get("source") or "startup")
        if out:
            sys.stdout.write("\n".join(out) + "\n")
    except Exception as exc:  # never block a session start
        sys.stderr.write("session-context: no context added (%s).\n" % type(exc).__name__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
