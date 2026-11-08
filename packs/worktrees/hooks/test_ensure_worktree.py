# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Tests for ensure_worktree.py. Run: python3 .claude/hooks/test_ensure_worktree.py"""

import os
import sys
import time
import unittest

sys.dont_write_bytecode = True

from worktree_fixture import WorktreeCase, read, write

HOOK = "ensure_worktree"


def prompt(cwd):
    return {"hook_event_name": "UserPromptSubmit", "prompt": "hi", "cwd": cwd}


class EnsureWorktreeTest(WorktreeCase):
    ENV_FILES = "`api/.env, .env.local rag/.env ../escape.env`"

    def setUp(self):
        super().setUp()
        write(f"{self.main}/api/.env", "SECRET_PLACEHOLDER=1\n")
        write(f"{self.main}/.env.local", "MAIN=1\n")

    def test_first_prompt_syncs_a_clean_worktree_detached(self):
        new_sha = self.advance_origin()
        rc, out, err = self.run_hook(HOOK, prompt(self.wt))
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.head(self.wt), new_sha)
        self.assertEqual(self.git(["rev-parse", "--abbrev-ref", "HEAD"], self.wt), "HEAD")  # detached
        self.assertIn(f"Worktree path: {self.wt}", out)
        self.assertIn("synced to origin/main", out)
        self.assertIn("Up to date with origin/main", out)
        self.assertTrue(os.path.exists(self.stamp(self.wt)))
        self.assertIn("wt1: init: synced to origin/main", self.log_text())

    def test_branch_ref_keeps_its_commit_after_detach(self):
        self.advance_origin()
        self.run_hook(HOOK, prompt(self.wt))
        self.assertEqual(self.git(["rev-parse", "worktree-wt1"], self.wt), self.base_sha)

    def test_dirty_tree_is_never_moved_or_discarded(self):
        self.advance_origin()
        write(f"{self.wt}/a.txt", "my unsaved work\n")
        rc, out, _ = self.run_hook(HOOK, prompt(self.wt))
        self.assertEqual(rc, 0)
        self.assertEqual(self.head(self.wt), self.base_sha)
        self.assertEqual(read(f"{self.wt}/a.txt"), "my unsaved work\n")
        self.assertIn("uncommitted changes; not synced", out)
        self.assertIn("WARNING: 1 commit(s) behind origin/main", out)

    def test_local_commits_are_never_moved(self):
        self.advance_origin()
        write(f"{self.wt}/b.txt", "local\n")
        self.git(["add", "b.txt"], self.wt)
        self.git(["commit", "--quiet", "-m", "local work"], self.wt)
        local = self.head(self.wt)
        rc, out, _ = self.run_hook(HOOK, prompt(self.wt))
        self.assertEqual(rc, 0)
        self.assertEqual(self.head(self.wt), local)
        self.assertIn("1 commit(s) not on origin/main; not synced", out)

    def test_env_files_linked_only_when_missing_and_never_overwritten(self):
        write(f"{self.wt}/.env.local", "WORKTREE=1\n")
        self.run_hook(HOOK, prompt(self.wt))
        link = f"{self.wt}/api/.env"
        self.assertTrue(os.path.islink(link))
        self.assertEqual(os.readlink(link), f"{self.main}/api/.env")
        self.assertFalse(os.path.islink(f"{self.wt}/.env.local"))
        self.assertEqual(read(f"{self.wt}/.env.local"), "WORKTREE=1\n")
        self.assertEqual(read(f"{self.main}/.env.local"), "MAIN=1\n")
        log = self.log_text()
        self.assertIn("env api/.env: linked", log)
        self.assertIn("env .env.local: already present; left as is", log)
        self.assertIn("env rag/.env: missing in the main checkout", log)
        self.assertNotIn("escape", log)
        self.assertFalse(os.path.lexists(f"{self.main}/../escape.env"))

    def test_later_prompts_do_not_move_head_but_warn_when_behind(self):
        self.run_hook(HOOK, prompt(self.wt))
        synced = self.head(self.wt)
        self.advance_origin("three\n")
        rc, out, _ = self.run_hook(HOOK, prompt(self.wt))  # fetch throttled: still looks up to date
        self.assertEqual(rc, 0)
        self.assertIn("Up to date", out)
        old = time.time() - 3600
        os.utime(f"{self.wt}/.claude/state/worktree-last-fetch", (old, old))
        rc, out, _ = self.run_hook(HOOK, prompt(self.wt))
        self.assertEqual(self.head(self.wt), synced)
        self.assertIn("WARNING: 1 commit(s) behind origin/main", out)
        self.assertIn("git checkout --detach origin/main", out)
        self.assertNotIn("reset", out)

    def test_now_flag_resyncs_a_stamped_worktree(self):
        self.run_hook(HOOK, prompt(self.wt))
        new_sha = self.advance_origin("four\n")
        rc, out, _ = self.run_script("ensure_worktree.py", ["--now"], cwd=self.wt)
        self.assertEqual(rc, 0)
        self.assertEqual(self.head(self.wt), new_sha)
        self.assertIn("synced to origin/main", out)

    def test_fetch_failure_warns_and_still_stamps(self):
        self.git(["remote", "set-url", "origin", f"{self.t}/no-such-remote.git"], self.main)
        rc, out, _ = self.run_hook(HOOK, prompt(self.wt))
        self.assertEqual(rc, 0)
        self.assertIn("fetch of origin main failed", out)
        self.assertEqual(self.head(self.wt), self.base_sha)
        self.assertTrue(os.path.exists(self.stamp(self.wt)))

    def test_main_checkout_and_non_git_dirs_are_silent(self):
        os.makedirs(f"{self.t}/plain")
        for cwd in (self.main, f"{self.t}/plain"):
            rc, out, _ = self.run_hook(HOOK, prompt(cwd))
            self.assertEqual((rc, out), (0, ""), cwd)
        self.assertEqual(self.log_text(), "")
        self.assertFalse(os.path.exists(f"{self.main}/.claude/state/worktree-initialized"))

    def test_malformed_payload_falls_back_to_process_cwd(self):
        for payload in ("", "not json{", "[]", '{"cwd": 5}'):
            rc, out, _ = self.run_hook(HOOK, payload, cwd=self.wt)
            self.assertEqual(rc, 0, payload)
            self.assertIn("[worktree-guard]", out)

    def rotated_logs(self):
        state = f"{self.main}/.claude/state"
        return sorted(n for n in os.listdir(state) if n.startswith("worktree.log."))

    def test_log_is_rotated_by_rename_never_deleted(self):
        log = f"{self.main}/.claude/state/worktree.log"
        write(log, "x" * (300 * 1024))
        self.run_hook(HOOK, prompt(self.wt))
        rotated = self.rotated_logs()
        self.assertEqual(len(rotated), 1)
        self.assertRegex(rotated[0], r"^worktree\.log\.\d{8}-\d{6}$")
        self.assertEqual(os.path.getsize(f"{self.main}/.claude/state/{rotated[0]}"), 300 * 1024)
        self.assertLess(os.path.getsize(log), 4096)
        self.assertIn("init:", read(log))

    def test_rotating_twice_keeps_both_old_logs(self):
        log = f"{self.main}/.claude/state/worktree.log"
        write(log, "a" * (300 * 1024))
        self.run_hook(HOOK, prompt(self.wt))
        write(log, "b" * (300 * 1024))
        self.run_script("ensure_worktree.py", ["--now"], cwd=self.wt)  # logs again, so rotates again
        rotated = self.rotated_logs()
        self.assertEqual(len(rotated), 2, rotated)
        contents = sorted(read(f"{self.main}/.claude/state/{name}")[0] for name in rotated)
        self.assertEqual(contents, ["a", "b"])
        for name in rotated:
            self.assertEqual(os.path.getsize(f"{self.main}/.claude/state/{name}"), 300 * 1024)
        self.assertIn("init:", read(log))

    def test_rotation_never_overwrites_an_existing_name(self):
        import importlib
        common = importlib.import_module("worktree_common")
        state = f"{self.main}/.claude/state"
        log = f"{state}/worktree.log"
        first = common.rotate_log(self._full_log(log, "1"))
        second = common.rotate_log(self._full_log(log, "2"))
        third = common.rotate_log(self._full_log(log, "3"))
        self.assertEqual(len({first, second, third}), 3)
        self.assertEqual(sorted(read(p) for p in (first, second, third)), ["1", "2", "3"])

    @staticmethod
    def _full_log(path, text):
        write(path, text)
        return path


class NonDefaultMainBranchTest(WorktreeCase):
    def test_main_branch_fact_is_used(self):
        self.git(["checkout", "--quiet", "-b", "trunk"], self.main)
        write(f"{self.main}/CLAUDE.md", "| `MAIN_BRANCH` | trunk | x |\n")
        write(f"{self.main}/c.txt", "trunk\n")
        self.git(["add", "-A"], self.main)
        self.git(["commit", "--quiet", "-m", "trunk"], self.main)
        self.git(["push", "--quiet", "origin", "trunk"], self.main)
        rc, out, _ = self.run_hook(HOOK, prompt(self.wt))
        self.assertEqual(rc, 0)
        self.assertEqual(self.head(self.wt), self.head(self.main))
        self.assertIn("origin/trunk", out)


if __name__ == "__main__":
    unittest.main()
