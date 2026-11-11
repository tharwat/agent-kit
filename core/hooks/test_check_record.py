#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Tests for check-record.py. Run: python3 -m unittest test_check_record.py"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check-record.py")
TICKET = "ABC-12"
FP = "ab" * 32
HEADER = ("| ID | Class | Invariant | Paths | Hostile case | Authority | Behavioral proof | Counterfactual | "
          "Independent vector | Discharge |")
GOOD = {
    "triage": "# Triage ABC-12\n\n%s\n|---|---|---|---|---|---|---|---|---|---|\n| C1 | S4 | x | y | z | a | b | c | d | |\n"
              % HEADER,
    "operate": "Self-review: ABC-12\nFingerprint: %s\nCovers: whole branch\n" % FP,
    "post-op": "# Post-op\n\nFingerprint: %s\nResult: clean\n" % FP,
    "handoff": "---\nbranch: feature/abc-12-x\n---\n# Handoff\n\n## Git state\nBranch: feature/abc-12-x. Ahead: 1.\n",
}
PATHS = {"triage": ".claude/state/ABC-12/triage.md", "operate": ".claude/state/ABC-12/self-review.md",
         "post-op": ".claude/state/ABC-12/post-op.md", "handoff": ".claude/handoffs/latest.md"}


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = os.path.realpath(self._tmp.name)

    def run_cli(self, *args, stdin=""):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.project)
        return subprocess.run([sys.executable, HOOK] + list(args), input=stdin, capture_output=True, text=True,
                              env=env, cwd=self.project, timeout=30)

    def write(self, rel, text, age=0):
        path = os.path.join(self.project, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        if age:
            t = time.time() - age
            os.utime(path, (t, t))
        return path

    def start(self, kind, age=0):
        args = ["--start", kind] + ([] if kind == "handoff" else ["--ticket", TICKET])
        r = self.run_cli(*args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        marker = self.marker(kind, "started")
        self.assertTrue(os.path.isfile(marker))
        if age:
            with open(marker, "w", encoding="utf-8") as fh:
                fh.write("%f\n" % (time.time() - age))
        return marker

    def marker(self, kind, state):
        base = os.path.join(self.project, ".claude", "state")
        d = base if kind == "handoff" else os.path.join(base, TICKET)
        return os.path.join(d, ".%s-%s" % (state, kind))

    def check(self, kind):
        return self.run_cli("--kind", kind, *([] if kind == "handoff" else ["--ticket", TICKET]))

    def stop(self, **event):
        return self.run_cli("--stop", stdin=json.dumps(dict({"hook_event_name": "Stop", "cwd": self.project},
                                                            **event)))


class Kinds(Case):
    def test_each_kind_passes_with_a_good_record(self):
        for kind in GOOD:
            with self.subTest(kind=kind):
                self.start(kind)
                time.sleep(0.01)
                self.write(PATHS[kind], GOOD[kind])
                r = self.check(kind)
                self.assertEqual(r.returncode, 0, r.stdout)
                self.assertFalse(os.path.exists(self.marker(kind, "started")))
                self.assertTrue(os.path.exists(self.marker(kind, "checked")))  # renamed, never deleted

    def test_missing_file(self):
        for kind in GOOD:
            with self.subTest(kind=kind):
                r = self.check(kind)
                self.assertEqual(r.returncode, 1)
                self.assertIn("doesn't exist", r.stdout)

    def test_malformed_records(self):
        bad = {
            "triage": ["# Triage\n\nno table\n", "%s\n|---|\n" % HEADER],
            "operate": ["Fingerprint: abc\n", "Fingerprint: <h>\n", "Self-review only\n"],
            "post-op": ["Fingerprint: %s\n" % FP, "Result: clean\n", "Fingerprint: %s\nResult: done\n" % FP],
            "handoff": ["# Handoff\n\nno git state\n", "## Git state\nUncommitted: clean\n"],
        }
        for kind, texts in bad.items():
            for text in texts:
                with self.subTest(kind=kind, text=text[:20]):
                    self.write(PATHS[kind], text)
                    self.assertEqual(self.check(kind).returncode, 1)

    def test_post_op_docs_only_and_other_results(self):
        for text in ("Fingerprint: none (no reviewable change)\nResult: clean\n",
                     "Fingerprint: %s\nResult: capped\n" % FP, "Fingerprint: %s\nResult: escalate\n" % FP):
            with self.subTest(text=text[:30]):
                self.write(PATHS["post-op"], text)
                self.assertEqual(self.check("post-op").returncode, 0)

    def test_stale_record_from_before_the_start(self):
        self.write(PATHS["operate"], GOOD["operate"], age=600)
        self.start("operate")
        r = self.check("operate")
        self.assertEqual(r.returncode, 1)
        self.assertIn("older than the command's start", r.stdout)

    def test_no_ticket_fails_open(self):
        r = self.run_cli("--kind", "triage")
        self.assertEqual(r.returncode, 0)
        self.assertIn("no ticket", r.stdout)
        self.assertEqual(self.run_cli("--start", "operate", "--ticket", "../etc").returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.project, ".claude", "etc")))


class Stop(Case):
    def test_no_markers_is_free(self):
        r = self.stop()
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr, "")

    def test_open_marker_blocks_with_what_is_missing(self):
        self.start("post-op")
        r = self.stop()
        self.assertEqual(r.returncode, 2)
        self.assertIn("/post-op for ABC-12", r.stderr)
        self.assertIn("--kind post-op --ticket ABC-12", r.stderr)

    def test_stop_hook_active_passes(self):
        self.start("triage")
        self.assertEqual(self.stop(stop_hook_active=True).returncode, 0)

    def test_complete_record_passes_and_closes_the_marker(self):
        self.start("handoff")
        time.sleep(0.01)
        self.write(PATHS["handoff"], GOOD["handoff"])
        self.assertEqual(self.stop().returncode, 0)
        self.assertTrue(os.path.exists(self.marker("handoff", "checked")))
        self.assertEqual(self.stop().returncode, 0)

    def test_stale_marker_is_abandoned_once(self):
        self.start("operate", age=25 * 3600)
        r = self.stop()
        self.assertEqual(r.returncode, 0)
        self.assertIn("abandoned", r.stderr)
        self.assertTrue(os.path.exists(self.marker("operate", "abandoned")))
        r = self.stop()
        self.assertEqual(r.stderr, "")

    def test_fail_open(self):
        r = self.run_cli("--stop", stdin="{nope")
        self.assertEqual(r.returncode, 0)
        self.assertIn("allowing the stop", r.stderr)


class TicketFromBranch(Case):
    def test_branch_names_the_ticket(self):
        with open(os.path.join(self.project, "CLAUDE.md"), "w", encoding="utf-8") as fh:
            fh.write("| Fact | Value |\n|---|---|\n| `TICKET_PREFIX` | ABC |\n| `BRANCH_PREFIX` | feature/ |\n")
        subprocess.run(["git", "init", "-q", self.project], check=True)
        subprocess.run(["git", "-C", self.project, "symbolic-ref", "HEAD", "refs/heads/feature/abc-12-x"], check=True)
        r = self.run_cli("--start", "operate")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(os.path.isfile(self.marker("operate", "started")))


if __name__ == "__main__":
    unittest.main()
