#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Tests for statusline.py. Run: python3 -m unittest test_statusline.py"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "statusline.py")
KIT_FACTS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "core", "hooks", "kit_facts.py"))
FACTS = "| Fact | Value |\n|---|---|\n| `TICKET_PREFIX` | ABC |\n| `BRANCH_PREFIX` | feature/ |\n"


class StatusLine(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = os.path.realpath(self._tmp.name)
        # the installed layout: .claude/scripts/statusline.py beside .claude/hooks/kit_facts.py
        os.makedirs(os.path.join(self.project, ".claude", "scripts"))
        os.makedirs(os.path.join(self.project, ".claude", "hooks"))
        self.script = os.path.join(self.project, ".claude", "scripts", "statusline.py")
        shutil.copy(SCRIPT, self.script)
        shutil.copy(KIT_FACTS, os.path.join(self.project, ".claude", "hooks", "kit_facts.py"))
        with open(os.path.join(self.project, "CLAUDE.md"), "w", encoding="utf-8") as fh:
            fh.write(FACTS)
        subprocess.run(["git", "init", "-q", self.project], check=True)
        subprocess.run(["git", "-C", self.project, "symbolic-ref", "HEAD", "refs/heads/feature/abc-12-nav"], check=True)

    def run_line(self, data=None, raw=None):
        payload = raw if raw is not None else json.dumps(data)
        env = dict(os.environ)
        env.pop("CLAUDE_PROJECT_DIR", None)
        r = subprocess.run([sys.executable, self.script], input=payload, capture_output=True, text=True, env=env,
                           timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stdout.strip().split("\n")), 1)
        return r.stdout.strip()

    def data(self, pct=42.4):
        return {"model": {"id": "x", "display_name": "Opus"}, "cwd": self.project,
                "workspace": {"current_dir": self.project, "project_dir": self.project},
                "context_window": {"used_percentage": pct, "context_window_size": 200000}}

    def test_full_line(self):
        self.assertEqual(self.run_line(self.data()), "Opus · feature/abc-12-nav · ABC-12 · context 42% used")

    def test_before_first_reply(self):
        self.assertEqual(self.run_line(self.data(pct=None)), "Opus · feature/abc-12-nav · ABC-12 · context –")

    def test_non_ticket_branch(self):
        subprocess.run(["git", "-C", self.project, "symbolic-ref", "HEAD", "refs/heads/main"], check=True)
        self.assertEqual(self.run_line(self.data(10)), "Opus · main · context 10% used")

    def test_not_a_repo_and_bad_input(self):
        d = self.data(5)
        with tempfile.TemporaryDirectory() as other:
            d["workspace"] = {"current_dir": other, "project_dir": other}
            self.assertEqual(self.run_line(d), "Opus · no branch · context 5% used")
        self.assertEqual(self.run_line(raw="{nope"), "Claude")
        self.assertTrue(self.run_line(raw="").startswith("Claude"))

    def test_without_kit_facts(self):
        os.rename(os.path.join(self.project, ".claude", "hooks", "kit_facts.py"),
                  os.path.join(self.project, ".claude", "hooks", "kit_facts.py.off"))
        self.assertEqual(self.run_line(self.data(1)), "Opus · feature/abc-12-nav · context 1% used")


if __name__ == "__main__":
    unittest.main()
