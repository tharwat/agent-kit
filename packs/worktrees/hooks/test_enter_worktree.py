# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Tests for enter_worktree.py. Run: python3 .claude/hooks/test_enter_worktree.py"""

import os
import sys
import time
import unittest

sys.dont_write_bytecode = True

from worktree_fixture import WorktreeCase

HOOK = "enter_worktree"


def event(cwd, tool_input=None, tool_response=None, tool="EnterWorktree"):
    return {"hook_event_name": "PostToolUse", "tool_name": tool, "cwd": cwd,
            "tool_input": tool_input or {}, "tool_response": tool_response or {}}


class EnterWorktreeTest(WorktreeCase):
    def setUp(self):
        super().setUp()
        self.wt2 = self.add_worktree("wt2")
        self.new_sha = self.advance_origin()
        # wt1 is the newest by mtime: the old hook would have picked it.
        later = time.time() + 60
        os.utime(self.wt, (later, later))

    def test_path_from_tool_input_wins_over_newest_mtime(self):
        rc, out, err = self.run_hook(HOOK, event(self.main, {"path": self.wt2}))
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.head(self.wt2), self.new_sha)
        self.assertEqual(self.head(self.wt), self.base_sha)
        self.assertFalse(os.path.exists(self.stamp(self.wt)))
        self.assertIn(f"Entered worktree {self.wt2}", out)

    def test_path_from_tool_response(self):
        self.run_hook(HOOK, event(self.main, {}, {"worktreePath": self.wt2}))
        self.assertEqual(self.head(self.wt2), self.new_sha)
        self.assertEqual(self.head(self.wt), self.base_sha)

    def test_name_resolves_under_the_builtin_dir(self):
        self.run_hook(HOOK, event(self.main, {"name": "wt2"}))
        self.assertEqual(self.head(self.wt2), self.new_sha)
        self.assertEqual(self.head(self.wt), self.base_sha)

    def test_cwd_fallback(self):
        self.run_hook(HOOK, event(self.wt2))
        self.assertEqual(self.head(self.wt2), self.new_sha)

    def test_stamped_worktree_is_not_moved_again(self):
        self.run_hook(HOOK, event(self.main, {"path": self.wt2}))
        newer = self.advance_origin("three\n")
        rc, out, _ = self.run_hook(HOOK, event(self.main, {"path": self.wt2}))
        self.assertEqual(rc, 0)
        self.assertNotEqual(self.head(self.wt2), newer)
        self.assertIn("HEAD not moved", out)

    def test_dirty_worktree_is_not_moved(self):
        with open(f"{self.wt2}/a.txt", "w", encoding="utf-8") as fh:
            fh.write("unsaved\n")
        self.run_hook(HOOK, event(self.main, {"path": self.wt2}))
        self.assertEqual(self.head(self.wt2), self.base_sha)
        with open(f"{self.wt2}/a.txt", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "unsaved\n")

    def test_no_worktree_in_event_syncs_nothing(self):
        rc, _, _ = self.run_hook(HOOK, event(self.main, {"name": "../../etc"}))
        self.assertEqual(rc, 0)
        self.assertEqual(self.head(self.wt), self.base_sha)
        self.assertEqual(self.head(self.wt2), self.base_sha)
        self.assertIn("no worktree under WORKTREE_DIR", self.log_text())

    def test_worktree_outside_worktree_dir_is_ignored(self):
        outside = os.path.join(self.t, "outside-wt")
        self.git(["worktree", "add", "--quiet", "-b", "outside", outside, self.base_sha], self.main)
        self.run_hook(HOOK, event(self.main, {"path": outside}))
        self.assertEqual(self.head(outside), self.base_sha)

    def test_other_tools_and_malformed_payloads(self):
        for payload in ("", "not json{", "[]", '{"tool_name":"EnterWorktree","tool_input":"x"}',
                        event(self.main, {"path": self.wt2}, tool="Edit")):
            rc, _, _ = self.run_hook(HOOK, payload)
            self.assertEqual(rc, 0)
        self.assertEqual(self.head(self.wt2), self.base_sha)


if __name__ == "__main__":
    unittest.main()
