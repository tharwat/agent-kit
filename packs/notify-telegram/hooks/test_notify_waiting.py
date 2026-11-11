#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Tests for notify-waiting.py. Run: python3 -m unittest test_notify_waiting.py"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "notify-waiting.py")
CORE_HOOKS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "core", "hooks"))  # kit_facts, as installed
FAKE_NOTIFY = "import sys\nopen(sys.argv[0] + '.log', 'a', encoding='utf-8').write(sys.argv[1] + '\\n')\n"
FACTS = "| Fact | Value |\n|---|---|\n| `PROJECT_NAME` | Acme |\n"


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = os.path.realpath(self._tmp.name)
        with open(os.path.join(self.project, "CLAUDE.md"), "w", encoding="utf-8") as fh:
            fh.write(FACTS)
        os.makedirs(os.path.join(self.project, ".claude", "scripts"))
        self.notify = os.path.join(self.project, ".claude", "scripts", "notify")
        with open(self.notify, "w", encoding="utf-8") as fh:
            fh.write(FAKE_NOTIFY)

    def fire(self, raw=None, **event):
        payload = raw if raw is not None else json.dumps(dict({
            "hook_event_name": "Notification", "session_id": "s1", "cwd": self.project,
            "notification_type": "permission_prompt",
            "message": "Claude needs your permission to use Bash"}, **event))
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.project, PYTHONPATH=CORE_HOOKS)
        r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def sent(self):
        try:
            with open(self.notify + ".log", encoding="utf-8") as fh:
                return fh.read().splitlines()
        except OSError:
            return []


class Ping(Case):
    def test_permission_prompt(self):
        self.fire()
        self.assertEqual(self.sent(), ["[Acme] Waiting for you: a permission prompt (Bash)"])

    def test_idle_prompt(self):
        self.fire(notification_type="idle_prompt", message="Claude is waiting for your input")
        self.assertEqual(self.sent(), ["[Acme] Waiting for you: idle, waiting for your input"])

    def test_message_text_never_sent(self):
        self.fire(message="Claude needs your permission to use Bash: cat /secret/path TOKEN=abc")
        self.assertEqual(self.sent(), ["[Acme] Waiting for you: a permission prompt (Bash)"])
        self.fire(session_id="s2", notification_type="weird; rm -rf /", message="x")
        self.assertEqual(self.sent()[-1], "[Acme] Waiting for you: notification")

    def test_throttle_per_session(self):
        self.fire()
        self.fire()
        self.assertEqual(len(self.sent()), 1)
        self.fire(session_id="s2")
        self.assertEqual(len(self.sent()), 2)
        state = os.path.join(self.project, ".claude", "state", "notify-waiting.json")
        with open(state, encoding="utf-8") as fh:
            data = json.load(fh)
        data["s1"] -= 601
        with open(state, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        self.fire()
        self.assertEqual(len(self.sent()), 3)


class ReviewRound1(Case):
    def test_hyphenated_mcp_tool(self):
        self.fire(message="Claude needs your permission to use mcp__my-server__deploy")
        self.assertEqual(self.sent(), ["[Acme] Waiting for you: a permission prompt (mcp__my-server__deploy)"])

    def test_failed_send_is_reported_and_not_throttled(self):
        with open(self.notify, "w", encoding="utf-8") as fh:
            fh.write("import sys\nsys.stderr.write('notify: send failed\\n')\n")
        r = self.fire()
        self.assertIn("notify: send failed", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.project, ".claude", "state", "notify-waiting.json")))
        with open(self.notify, "w", encoding="utf-8") as fh:
            fh.write(FAKE_NOTIFY)
        self.fire()
        self.assertEqual(len(self.sent()), 1)  # the next wait still pings


class NeverFails(Case):
    def test_no_notify_script(self):
        os.rename(self.notify, self.notify + ".off")
        r = self.fire()
        self.assertEqual(r.stderr, "")
        self.assertFalse(os.path.exists(os.path.join(self.project, ".claude", "state", "notify-waiting.json")))

    def test_bad_input(self):
        r = self.fire(raw="{nope")
        self.assertIn("no ping sent", r.stderr)
        self.assertEqual(self.sent(), [])

    def test_corrupt_state_file(self):
        os.makedirs(os.path.join(self.project, ".claude", "state"))
        with open(os.path.join(self.project, ".claude", "state", "notify-waiting.json"), "w") as fh:
            fh.write("[not, a dict")
        self.fire()
        self.assertEqual(len(self.sent()), 1)

    def test_no_facts_reader(self):
        payload = json.dumps({"session_id": "s9", "notification_type": "idle_prompt", "cwd": self.project})
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.project)
        env.pop("PYTHONPATH", None)
        r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.sent(), ["[project] Waiting for you: idle, waiting for your input"])


if __name__ == "__main__":
    unittest.main()
