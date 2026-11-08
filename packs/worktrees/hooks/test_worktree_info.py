# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Tests for worktree_info.py. Run: python3 .claude/hooks/test_worktree_info.py"""

import os
import sys
import unittest

sys.dont_write_bytecode = True

from worktree_fixture import WorktreeCase

SCRIPT = "worktree_info.py"


def snapshot(root):
    """Every path under root (except the fake HOME, where Python may cache bytecode) with its mtime and size."""
    seen = {}
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath == root:
            dirnames[:] = [d for d in dirnames if d != "home"]
        for name in dirnames + filenames:
            path = os.path.join(dirpath, name)
            st = os.lstat(path)
            seen[path] = (st.st_mtime_ns, st.st_size)
    return seen


class WorktreeInfoTest(WorktreeCase):
    ENV_FILES = "api/.env"

    def test_in_a_worktree_reports_it_and_writes_nothing(self):
        self.advance_origin()
        self.git(["fetch", "--quiet", "origin"], self.wt)
        before = snapshot(self.t)
        rc, out, err = self.run_script(SCRIPT, [], cwd=self.wt)
        self.assertEqual(rc, 0, err)
        self.assertEqual(snapshot(self.t), before)
        self.assertIn(f"Worktree: {self.wt}", out)
        self.assertIn("0 ahead, 1 behind", out)
        self.assertIn("Initialized: no", out)
        self.assertIn("missing  api/.env", out)
        self.assertIn("(no log yet)", out)

    def test_from_the_main_checkout_lists_every_worktree(self):
        wt2 = self.add_worktree("wt2")
        rc, out, _ = self.run_script(SCRIPT, [], cwd=self.main)
        self.assertEqual(rc, 0)
        self.assertIn(f"Worktree: {self.wt}", out)
        self.assertIn(f"Worktree: {wt2}", out)

    def test_explicit_path_argument(self):
        rc, out, _ = self.run_script(SCRIPT, [self.wt], cwd=self.t)
        self.assertEqual(rc, 0)
        self.assertIn(f"Worktree: {self.wt}", out)

    def test_outside_git(self):
        os.makedirs(f"{self.t}/plain")
        rc, out, _ = self.run_script(SCRIPT, [], cwd=f"{self.t}/plain")
        self.assertEqual(rc, 0)
        self.assertIn("Not in a git work tree", out)


if __name__ == "__main__":
    unittest.main()
