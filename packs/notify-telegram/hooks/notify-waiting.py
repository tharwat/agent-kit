#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Notification hook (permission_prompt, idle_prompt): ping the owner when the agent is waiting for them.

Sends `[<PROJECT_NAME>] Waiting for you: <reason>` through `.claude/scripts/notify`. The reason is the event type,
plus the tool name for a permission prompt. The notification's own text is never sent: it can hold paths or
command text.

At most one ping per 10 minutes per session (state in `.claude/state/notify-waiting.json`). Inherits the notify
script's never-fail behaviour: always exits 0, one stderr line on a problem. The network call is the notify
script's, which is this hook's purpose.
"""

import json
import os
import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True  # never leave __pycache__ in .claude/hooks/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import kit_facts  # installed beside this hook by core
except ImportError:
    kit_facts = None

THROTTLE_SECONDS = 600
MAX_SESSIONS = 50
TOOL_RE = re.compile(r"permission to use ([A-Za-z][A-Za-z0-9_]{0,63})\b")
REASONS = {"permission_prompt": "a permission prompt", "idle_prompt": "idle, waiting for your input"}


def project_name(project):
    if kit_facts is not None:
        name = kit_facts.fact(kit_facts.read_facts(project), "PROJECT_NAME")
        if name and re.match(r"^[\w .-]{1,40}$", name):
            return name
    return "project"


def reason_for(event):
    kind = str(event.get("notification_type") or "")
    if not re.match(r"^[a-z_]{1,40}$", kind):
        kind = "notification"
    reason = REASONS.get(kind, kind.replace("_", " "))
    if kind == "permission_prompt":
        m = TOOL_RE.search(str(event.get("message") or ""))
        if m:
            reason += " (%s)" % m.group(1)
    return reason


def throttled(state_path, session, now):
    """True if this session pinged in the last 10 minutes; otherwise records this ping."""
    try:
        with open(state_path, encoding="utf-8") as fh:
            state = json.load(fh)
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    last = state.get(session)
    if isinstance(last, (int, float)) and now - last < THROTTLE_SECONDS:
        return True
    state[session] = now
    if len(state) > MAX_SESSIONS:  # keep the file small: newest sessions only
        state = dict(sorted(state.items(), key=lambda kv: kv[1] if isinstance(kv[1], (int, float)) else 0)
                     [-MAX_SESSIONS:])
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    tmp = state_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    os.replace(tmp, state_path)
    return False


def main():
    try:
        event = json.loads(sys.stdin.read() or "{}")
        project = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
        notify = os.path.join(project, ".claude", "scripts", "notify")
        if not os.path.isfile(notify):
            return 0
        session = str(event.get("session_id") or "unknown")[:80]
        if throttled(os.path.join(project, ".claude", "state", "notify-waiting.json"), session, time.time()):
            return 0
        text = "[%s] Waiting for you: %s" % (project_name(project), reason_for(event))
        subprocess.run([sys.executable, notify, text], capture_output=True, text=True, timeout=12, cwd=project)
    except Exception as exc:  # never fail: this is a courtesy ping
        sys.stderr.write("notify-waiting: no ping sent (%s).\n" % type(exc).__name__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
