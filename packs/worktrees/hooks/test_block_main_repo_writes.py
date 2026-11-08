# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Tests for block_main_repo_writes.py. Run: python3 .claude/hooks/test_block_main_repo_writes.py"""

import json
import os
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True

from worktree_fixture import WRAPPER, WorktreeCase, write

HOOK = "block_main_repo_writes"


def edit(path, cwd, tool="Edit"):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    return {"tool_name": tool, "tool_input": {key: path}, "cwd": cwd}


class BlockMainRepoWritesTest(WorktreeCase):
    def test_blocks_every_write_tool_into_the_main_checkout(self):
        for tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            rc, out, err = self.run_hook(HOOK, edit(f"{self.main}/a.txt", self.wt, tool))
            self.assertEqual(rc, 2, tool)
            self.assertEqual(out, "")
            self.assertIn("BLOCKED", err)
            self.assertIn(f"Correct: {self.wt}/a.txt", err)

    def test_allows_the_worktree_itself_and_relative_paths(self):
        for path in (f"{self.wt}/a.txt", f"{self.wt}/new/dir/file.ts", "a.txt", "api/index.js"):
            rc, _, err = self.run_hook(HOOK, edit(path, self.wt))
            self.assertEqual(rc, 0, f"{path}: {err}")

    def test_allows_main_dot_claude_and_other_worktrees(self):
        for path in (f"{self.main}/.claude/settings.json", f"{self.main}/.claude/worktrees/wt2/a.txt"):
            rc, _, _ = self.run_hook(HOOK, edit(path, self.wt))
            self.assertEqual(rc, 0, path)

    def test_allows_paths_outside_the_main_checkout(self):
        rc, _, _ = self.run_hook(HOOK, edit(f"{self.t}/elsewhere/x.txt", self.wt))
        self.assertEqual(rc, 0)

    def test_dot_dot_escape_into_main_is_blocked(self):
        rc, _, _ = self.run_hook(HOOK, edit(f"{self.wt}/../../../a.txt", self.wt))
        self.assertEqual(rc, 2)

    def test_symlink_into_main_is_blocked(self):
        os.symlink(f"{self.main}/a.txt", f"{self.wt}/linked.txt")
        rc, _, err = self.run_hook(HOOK, edit(f"{self.wt}/linked.txt", self.wt))
        self.assertEqual(rc, 2)
        self.assertIn("link", err)

    def test_session_in_a_subdir_of_the_worktree(self):
        rc, _, _ = self.run_hook(HOOK, edit(f"{self.main}/a.txt", f"{self.wt}/api"))
        self.assertEqual(rc, 2)

    def test_no_cwd_in_payload_uses_the_process_cwd(self):
        payload = {"tool_name": "Edit", "tool_input": {"file_path": f"{self.main}/a.txt"}}
        rc, _, _ = self.run_hook(HOOK, payload, cwd=self.wt)
        self.assertEqual(rc, 2)

    def test_main_checkout_session_is_not_a_worktree_session(self):
        rc, _, _ = self.run_hook(HOOK, edit(f"{self.main}/a.txt", self.main))
        self.assertEqual(rc, 0)

    def test_worktree_outside_worktree_dir_is_not_a_session(self):
        self.set_facts("elsewhere/worktrees", "none")
        rc, _, _ = self.run_hook(HOOK, edit(f"{self.main}/a.txt", self.wt))
        self.assertEqual(rc, 0)

    def test_unfilled_fact_uses_the_default_dir(self):
        self.set_facts("{{WORKTREE_DIR}}", "{{WORKTREE_ENV_FILES}}")
        rc, _, _ = self.run_hook(HOOK, edit(f"{self.main}/a.txt", self.wt))
        self.assertEqual(rc, 2)

    def test_none_or_empty_fact_uses_the_default_dir(self):
        for value in ("none", "None", "", "`none`"):
            with self.subTest(value=value):
                self.set_facts(value, value)
                rc, _, _ = self.run_hook(HOOK, edit(f"{self.main}/a.txt", self.wt))
                self.assertEqual(rc, 2)
                self.assertFalse(os.path.exists(os.path.join(self.main, "none")))

    def test_read_fact_treats_none_empty_and_placeholders_as_unset(self):
        import worktree_common as wc
        path = os.path.join(self.t, "facts.md")
        for value, expected in (("none", None), ("NONE", None), ("", None), ("{{WORKTREE_DIR}}", None),
                                ("`.claude/worktrees`", ".claude/worktrees"), ("worktrees", "worktrees")):
            with self.subTest(value=value):
                write(path, f"| Fact | Value |\n|---|---|\n| `WORKTREE_DIR` | {value} |\n")
                self.assertEqual(wc.read_fact(path, "WORKTREE_DIR"), expected)

    def test_not_a_git_dir(self):
        os.makedirs(f"{self.t}/plain")
        rc, _, _ = self.run_hook(HOOK, edit(f"{self.main}/a.txt", f"{self.t}/plain"))
        self.assertEqual(rc, 0)

    def test_malformed_payloads_and_other_tools_allow(self):
        for payload in ("", "not json{", "[]", '{"tool_name":"Edit"}', '{"tool_name":"Edit","tool_input":"x"}',
                        json.dumps({"tool_name": "Edit", "tool_input": {"file_path": None}, "cwd": self.wt}),
                        json.dumps({"tool_name": "Edit", "tool_input": {"file_path": 7}, "cwd": self.wt}),
                        json.dumps(edit(f"{self.main}/a.txt", self.wt, "Read")),
                        json.dumps(edit(f"{self.main}/a.txt", self.wt, "Bash"))):
            rc, _, _ = self.run_hook(HOOK, payload)
            self.assertEqual(rc, 0, payload)

    def test_path_is_never_shell_evaluated(self):
        pwned = f"{self.t}/pwned"
        for path in (f"{self.main}/$(touch {pwned})", f"{self.main}/a`touch {pwned}`;b\"c'd"):
            rc, _, _ = self.run_hook(HOOK, edit(path, self.wt))
            self.assertEqual(rc, 2)
        self.assertFalse(os.path.exists(pwned))

    def test_python_missing_allows(self):
        proc = subprocess.run(["/bin/sh", WRAPPER, HOOK], input=json.dumps(edit(f"{self.main}/a.txt", self.wt)),
                              capture_output=True, text=True, env={"PATH": "/nonexistent"}, timeout=30)
        self.assertEqual(proc.returncode, 0)

    def test_unknown_hook_name_allows(self):
        rc, _, err = self.run_hook("bogus", edit(f"{self.main}/a.txt", self.wt))
        self.assertEqual(rc, 0)
        self.assertIn("unknown hook", err)


class CustomWorktreeDirTest(WorktreeCase):
    WORKTREE_DIR = "worktrees"

    def test_blocks_main_and_allows_worktrees_outside_dot_claude(self):
        rc, _, _ = self.run_hook(HOOK, edit(f"{self.main}/a.txt", self.wt))
        self.assertEqual(rc, 2)
        rc, _, _ = self.run_hook(HOOK, edit(f"{self.main}/worktrees/other/a.txt", self.wt))
        self.assertEqual(rc, 0)
        rc, _, _ = self.run_hook(HOOK, edit(f"{self.main}/.claude/settings.json", self.wt))
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
