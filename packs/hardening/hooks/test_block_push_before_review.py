#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Tests for block-push-before-review.py. Run: python3 -m unittest <path to this file>

Each test builds a project dir under tempfile.TemporaryDirectory and feeds the hook event JSON on stdin.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "block-push-before-review.py"


class Project:
    def __init__(self, root, main="main"):
        self.root = Path(root)
        self.state = self.root / ".claude" / "state" / "hardening"
        (self.root / "CLAUDE.md").write_text(
            "# CLAUDE.md\n\n## Project facts\n\n| Fact | Value | Meaning |\n|---|---|---|\n"
            f"| `MAIN_BRANCH` | {main} | The only long-lived branch |\n",
            encoding="utf-8",
        )

    def arm(self, ticket="ABC-7", content="ABC-7 armed 2026-01-01"):
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / f"{ticket}.active").write_text(content + "\n", encoding="utf-8")

    def passed(self, ticket="ABC-7", content="Fingerprint: abc"):
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / f"{ticket}.postop-passed").write_text(content + "\n", encoding="utf-8")

    def run(self, command=None, tool="Bash", raw=None):
        event = {"tool_name": tool, "tool_input": {"command": command} if command is not None else {}, "cwd": str(self.root)}
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.root)}
        return subprocess.run(
            [sys.executable, str(HOOK)], input=raw if raw is not None else json.dumps(event),
            capture_output=True, text=True, env=env, timeout=30,
        )


class BlockPushBeforeReview(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = Project(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def assertBlocked(self, result, action):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(action, result.stderr)
        self.assertIn("Never remove, rename or edit the hardening markers", result.stderr)
        self.assertIn("ABC-7", result.stderr)

    def assertAllowed(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)

    # --- no armed run: never blocks

    def test_no_marker_allows_everything(self):
        for cmd in ["git push origin main", "gh pr merge 5 --merge", "supabase db push"]:
            self.assertAllowed(self.p.run(cmd))

    def test_restored_marker_is_a_finished_run(self):
        self.p.arm(content="restored")
        self.assertAllowed(self.p.run("git push origin main"))

    # --- armed and not passed: blocks the three kinds

    def test_blocks_push_to_main(self):
        self.p.arm()
        for cmd in [
            "git push origin main",
            "git push origin HEAD:main",
            "git push origin +feature/abc-7-x:refs/heads/main",
            "git -C . push -u origin main",
            "cd repo && git push origin main",
            "GIT_TRACE=1 git push origin main",
            "git push --all origin",
            "git push --mirror origin",
        ]:
            with self.subTest(cmd=cmd):
                self.assertBlocked(self.p.run(cmd), "git push to main")

    def test_blocks_gh_pr_merge(self):
        self.p.arm()
        for cmd in ["gh pr merge 12 --merge", "gh pr merge 12 --auto --merge && gh pr checks 12"]:
            with self.subTest(cmd=cmd):
                self.assertBlocked(self.p.run(cmd), "gh pr merge")

    def test_blocks_migration_apply(self):
        self.p.arm()
        for cmd in [
            "supabase db push",
            "npx prisma migrate deploy",
            "bin/rails db:migrate",
            "python manage.py migrate",
            "alembic -c a.ini upgrade head",
            "npx knex migrate:latest",
            "npm run migrate",
            "pnpm db:migrate:deploy",
            "yarn run db:push",
            "npx drizzle-kit push",
        ]:
            with self.subTest(cmd=cmd):
                self.assertBlocked(self.p.run(cmd), "migration apply")

    def test_blocks_mcp_apply_migration(self):
        self.p.arm()
        self.assertBlocked(self.p.run(tool="mcp__db__apply_migration"), "migration apply through mcp__db__apply_migration")

    # --- armed: ordinary work is allowed

    def test_allows_feature_work(self):
        self.p.arm()
        for cmd in [
            "git push -u origin HEAD",
            "git push origin feature/abc-7-main-guard",
            "git commit -m 'ABC-7: touch src/main.ts'",
            "git diff origin/main...HEAD",
            "git fetch origin main",
            "gh pr create --base main --title x",
            "gh pr view 12 --json state",
            "npm test",
            "npm run migrate:status-check-docs",
            "cat docs/main.md",
        ]:
            with self.subTest(cmd=cmd):
                self.assertAllowed(self.p.run(cmd))

    def test_other_tools_are_allowed(self):
        self.p.arm()
        self.assertAllowed(self.p.run(tool="Edit"))

    # --- passing post-op unlocks; marking it restored re-arms

    def test_postop_passed_unlocks(self):
        self.p.arm()
        self.p.passed()
        for cmd in ["git push origin main", "gh pr merge 12 --merge", "supabase db push"]:
            self.assertAllowed(self.p.run(cmd))

    def test_restored_postop_marker_rearms(self):
        self.p.arm()
        self.p.passed(content="restored")
        self.assertBlocked(self.p.run("gh pr merge 12"), "gh pr merge")

    def test_another_tickets_pass_does_not_unlock(self):
        self.p.arm("ABC-7")
        self.p.passed("ABC-8")
        self.assertBlocked(self.p.run("gh pr merge 12"), "gh pr merge")

    # --- main branch name comes from Project facts

    def test_main_branch_from_project_facts(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        p = Project(other.name, main="trunk")
        p.arm()
        self.assertEqual(p.run("git push origin trunk").returncode, 2)
        self.assertEqual(p.run("git push origin main").returncode, 0)

    def test_defaults_to_main_without_claude_md(self):
        (self.p.root / "CLAUDE.md").write_text("no facts here\n", encoding="utf-8")
        self.p.arm()
        self.assertEqual(self.p.run("git push origin main").returncode, 2)

    # --- fail open

    def test_malformed_json_fails_open(self):
        self.p.arm()
        result = self.p.run(raw="{not json")
        self.assertEqual(result.returncode, 0)
        self.assertIn("internal error, allowing", result.stderr)

    def test_unbalanced_quotes_still_checked(self):
        self.p.arm()
        self.assertEqual(self.p.run("git push origin main 'unterminated").returncode, 2)

    def test_hook_writes_nothing(self):
        self.p.arm()
        before = sorted(str(x) for x in self.p.root.rglob("*"))
        self.p.run("git push origin main")
        self.p.run("npm test")
        self.assertEqual(before, sorted(str(x) for x in self.p.root.rglob("*")))


if __name__ == "__main__":
    unittest.main()
