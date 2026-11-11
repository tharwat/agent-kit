#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Claude Code status line: `<model> · <branch> · <ticket> · context <n>% used`.

Reads the status-line JSON on stdin (`model.display_name`, `workspace.current_dir`, `workspace.project_dir`,
`context_window.used_percentage`). The branch comes from local git; the ticket from the Project facts in CLAUDE.md
through `.claude/hooks/kit_facts.py`. Standard library only. No network, no writes. Always prints one line and exits 0.
"""

import json
import math
import os
import subprocess
import sys

sys.dont_write_bytecode = True  # never leave __pycache__ in .claude/
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "hooks"))  # .claude/hooks, where core installs kit_facts
try:
    import kit_facts
except Exception:  # missing, or broken by a partial upgrade: the line still prints
    kit_facts = None

SEP = " · "


def branch_of(directory):
    if kit_facts is not None:
        return kit_facts.current_branch(directory)
    try:
        out = subprocess.run(["git", "-C", directory, "symbolic-ref", "--short", "-q", "HEAD"], capture_output=True,
                             text=True, timeout=5)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def obj(value):
    return value if isinstance(value, dict) else {}


def context_part(data):
    window = obj(data.get("context_window"))
    pct = window.get("used_percentage")
    if isinstance(pct, (int, float)) and not isinstance(pct, bool) and math.isfinite(pct):
        return "context %d%% used" % round(pct)
    return "context –"


def line_for(data):
    model = obj(data.get("model"))
    name = str(model.get("display_name") or model.get("id") or "Claude")
    ws = obj(data.get("workspace"))
    cwd = ws.get("current_dir") or data.get("cwd") or os.getcwd()
    project = ws.get("project_dir") or os.environ.get("CLAUDE_PROJECT_DIR") or cwd
    parts = [name]
    branch = branch_of(cwd)
    parts.append(branch or "no branch")
    if kit_facts is not None and branch:
        ticket = kit_facts.ticket_for_branch(branch, kit_facts.read_facts(project))
        if ticket:
            parts.append(ticket)
    parts.append(context_part(data))
    return SEP.join(parts)


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            data = {}
        sys.stdout.write(line_for(data) + "\n")
    except Exception:  # a status line must never break the UI
        sys.stdout.write("Claude\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
