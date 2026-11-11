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
TOOL_RE = re.compile(r"permission to use ([A-Za-z][A-Za-z0-9_-]{0,79})")  # MCP names hold hyphens
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


def load_state(state_path):
    try:
        with open(state_path, encoding="utf-8") as fh:
            state = json.load(fh)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def throttled(state_path, session, now):
    """True if this session pinged in the last 10 minutes."""
    last = load_state(state_path).get(session)
    return isinstance(last, (int, float)) and now - last < THROTTLE_SECONDS


def record_ping(state_path, session, now):
    """Remember this session's ping. Written to a per-process temp file, then moved into place."""
    state = load_state(state_path)
    state[session] = now
    if len(state) > MAX_SESSIONS:  # keep the file small: newest sessions only
        state = dict(sorted(state.items(), key=lambda kv: kv[1] if isinstance(kv[1], (int, float)) else 0)
                     [-MAX_SESSIONS:])
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    tmp = "%s.%d.tmp" % (state_path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    os.replace(tmp, state_path)


def main():
    try:
        event = json.loads(sys.stdin.read() or "{}")
        project = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
        notify = os.path.join(project, ".claude", "scripts", "notify")
        if not os.path.isfile(notify):
            return 0
        session = str(event.get("session_id") or "unknown")[:80]
        state_path = os.path.join(project, ".claude", "state", "notify-waiting.json")
        now = time.time()
        if throttled(state_path, session, now):
            return 0
        text = "[%s] Waiting for you: %s" % (project_name(project), reason_for(event))
        r = subprocess.run([sys.executable, notify, text], capture_output=True, text=True, timeout=12, cwd=project)
        problem = (r.stderr or "").strip().splitlines()
        if r.returncode != 0 or problem:  # notify reports a failed or unconfigured send on stderr
            sys.stderr.write("notify-waiting: %s\n" % (problem[-1][:200] if problem else "send failed"))
            return 0  # not recorded, so the next wait can try again
        record_ping(state_path, session, now)
    except Exception as exc:  # never fail: this is a courtesy ping
        sys.stderr.write("notify-waiting: no ping sent (%s).\n" % type(exc).__name__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
