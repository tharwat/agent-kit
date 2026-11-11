#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Tests for session-context.py. Run: python3 -m unittest test_session_context.py"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session-context.py")
FACTS = "| Fact | Value |\n|---|---|\n| `TICKET_PREFIX` | ABC |\n| `BRANCH_PREFIX` | feature/ |\n| `MAIN_BRANCH` | main |\n"
SECRET = "super-secret-pasted-text"


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd, "-c", "user.email=a@b", "-c", "user.name=t"] + list(args), check=True,
                   capture_output=True)


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = os.path.realpath(self._tmp.name)

    def repo(self, branch="feature/abc-12-nav"):
        self.write("CLAUDE.md", FACTS)
        git(self.project, "init", "-q", "-b", "main")
        git(self.project, "add", "CLAUDE.md")
        git(self.project, "commit", "-q", "-m", "init")
        if branch != "main":
            git(self.project, "checkout", "-q", "-b", branch)

    def write(self, rel, text, mtime=None):
        path = os.path.join(self.project, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        if mtime is not None:
            os.utime(path, (mtime, mtime))

    def run_hook(self, source="startup", raw=None):
        payload = raw if raw is not None else json.dumps({"hook_event_name": "SessionStart", "source": source,
                                                          "cwd": self.project})
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.project)
        r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True, env=env,
                           timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLessEqual(len(r.stdout.strip().split("\n")), 15)
        self.assertNotIn(SECRET, r.stdout)
        return r.stdout


class Context(Case):
    def test_not_a_repo_prints_nothing(self):
        self.assertEqual(self.run_hook(), "")

    def test_ticket_branch_with_every_record(self):
        self.repo()
        self.write(".claude/state/ABC-12/triage.md", "contract " + SECRET)
        self.write(".claude/state/ABC-12/self-review.md", "Fingerprint: x " + SECRET)
        self.write(".claude/state/ABC-12/post-op.md", "%s\nResult: capped\n" % SECRET)
        out = self.run_hook()
        self.assertIn("Branch: feature/abc-12-nav · ticket: ABC-12", out)
        self.assertIn("triage.md, self-review.md, post-op.md (Result: capped)", out)
        self.assertIn("Read `.claude/state/ABC-12/triage.md` (the contract)", out)

    def test_record_combinations(self):
        self.repo()
        self.write(".claude/state/ABC-12/self-review.md", "x")
        out = self.run_hook()
        self.assertIn("Records in .claude/state/ABC-12/: self-review.md", out)
        self.assertNotIn("the contract", out)
        self.write(".claude/state/ABC-12/post-op.md", "Result: weird\n")
        self.assertIn("post-op.md (Result: no Result line)", self.run_hook())

    def test_no_ticket_and_on_main(self):
        self.repo(branch="main")
        out = self.run_hook()
        self.assertIn("ticket: none", out)
        self.assertIn("You are on main", out)
        self.assertNotIn("Records", out)

    def test_detached_head(self):
        self.repo()
        git(self.project, "checkout", "-q", "--detach")
        self.assertIn("Branch: detached HEAD", self.run_hook())

    def test_dirty_count_and_ahead_unknown_without_origin(self):
        self.repo()
        self.write("a.txt", "x")
        out = self.run_hook()
        self.assertIn("? commits ahead of origin/main · 1 changed files", out)

    def test_open_command_marker(self):
        self.repo()
        self.write(".claude/state/ABC-12/.started-operate", "1\n")
        self.assertIn("/operate for ABC-12 started and hasn't written its record yet", self.run_hook())

    def test_handoff_newer_than_last_commit(self):
        self.repo()
        self.write(".claude/handoffs/latest.md", SECRET, mtime=time.time() + 60)
        self.assertIn("run /resume.", self.run_hook("resume"))
        self.assertIn("Context was just compacted", self.run_hook("compact"))

    def test_old_handoff_is_ignored(self):
        self.repo()
        self.write(".claude/handoffs/latest.md", "x", mtime=time.time() - 86400 * 30)
        self.assertNotIn("handoff", self.run_hook())

    def test_handoff_from_another_branch_is_ignored(self):
        self.repo()
        self.write(".claude/handoffs/latest.md", "---\nbranch: feature/abc-7-old\n---\n" + SECRET,
                   mtime=time.time() + 60)
        self.assertNotIn("/resume", self.run_hook("compact"))
        self.write(".claude/handoffs/latest.md", "---\nbranch: feature/abc-12-nav\n---\n", mtime=time.time() + 60)
        self.assertIn("/resume", self.run_hook("compact"))

    def test_resume_line_survives_many_markers(self):
        self.repo()
        for n in range(30):
            self.write(".claude/state/ABC-%d/.started-operate" % n, "1\n")
        self.write(".claude/handoffs/latest.md", "x", mtime=time.time() + 60)
        out = self.run_hook("compact")
        self.assertIn("run /resume now", out)
        self.assertIn("more unfinished runs", out)

    def test_stale_and_unknown_markers_and_abandoned_runs(self):
        self.repo()
        self.write(".claude/state/ABC-1/.started-operate", "1\n", mtime=time.time() - 2 * 86400)
        self.write(".claude/state/ABC-2/.started-foo", "1\n")
        self.write(".claude/state/ABC-3/.abandoned-triage", "1\n")
        out = self.run_hook()
        self.assertNotIn("/operate for ABC-1", out)
        self.assertNotIn("/foo", out)
        self.assertIn("1 run(s) were left unfinished", out)

    def test_bad_input_never_blocks(self):
        self.repo()
        self.run_hook(raw="{nope")


if __name__ == "__main__":
    unittest.main()
