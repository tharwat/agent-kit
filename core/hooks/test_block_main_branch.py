#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Tests for block-main-branch.py. Run: python3 -m unittest test_block_main_branch.py"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "block-main-branch.py")

FACTS = """# CLAUDE.md — Example

## Project facts

| Fact | Value | Meaning |
|---|---|---|
| `PROJECT_NAME` | Example | Short name |
| `MAIN_BRANCH` | {main} | The only long-lived branch |
| `BRANCH_PREFIX` | feature/ | Feature branch prefix |
"""


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd] + list(args), check=True, capture_output=True)


def make_repo(parent, name, branch):
    """A git repo whose HEAD points at `branch` (unborn is fine: no commits needed)."""
    path = os.path.join(parent, name)
    os.makedirs(path)
    git(path, "init", "-q")
    git(path, "symbolic-ref", "HEAD", "refs/heads/" + branch)
    return path


class HookCase(unittest.TestCase):
    main_branch = "main"   # value written in the CLAUDE.md facts table
    repo_branch = None     # branch the on-main repo is checked out on; defaults to main_branch

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = cls._tmp.name
        cls.project = os.path.join(root, "project")
        os.makedirs(cls.project)
        with open(os.path.join(cls.project, "CLAUDE.md"), "w", encoding="utf-8") as fh:
            fh.write(FACTS.format(main=cls.main_branch))
        cls.on_main = make_repo(cls.project, "on-main", cls.repo_branch or cls.main_branch)
        cls.on_feature = make_repo(cls.project, "on-feature", "feature/abc-1-nav")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_hook(self, command, cwd=None, tool="Bash", raw=None):
        payload = raw if raw is not None else json.dumps({
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": {"command": command, "description": "test"},
            "cwd": cwd or self.on_feature,
        })
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.project)
        return subprocess.run(
            [sys.executable, HOOK], input=payload, capture_output=True, text=True, env=env, timeout=30,
        )

    def assertBlocked(self, command, cwd=None):
        result = self.run_hook(command, cwd)
        self.assertEqual(result.returncode, 2, "expected block: %r\nstderr: %s" % (command, result.stderr))
        self.assertIn("main-branch guard", result.stderr)

    def assertAllowed(self, command, cwd=None, **kw):
        result = self.run_hook(command, cwd, **kw)
        self.assertEqual(result.returncode, 0, "expected allow: %r\nstderr: %s" % (command, result.stderr))


class BlockTests(HookCase):
    def test_commit_on_main(self):
        self.assertBlocked('git commit -m "add feature"', cwd=self.on_main)

    def test_commit_all_on_main(self):
        self.assertBlocked("git commit -am wip", cwd=self.on_main)

    def test_commit_on_main_with_heredoc_message(self):
        cmd = "git commit -m \"$(cat <<'EOF'\nfix nav\nEOF\n)\""
        self.assertBlocked(cmd, cwd=self.on_main)

    def test_commit_on_main_via_dash_C(self):
        self.assertBlocked("git -C %s commit -m x" % self.on_main, cwd=self.on_feature)

    def test_commit_on_main_after_cd(self):
        self.assertBlocked("cd %s && git commit -m x" % self.on_main, cwd=self.project)

    def test_push_origin_main(self):
        self.assertBlocked("git push origin main")

    def test_push_head_to_main(self):
        self.assertBlocked("git push origin HEAD:main")

    def test_push_head_to_refs_heads_main(self):
        self.assertBlocked("git push origin HEAD:refs/heads/main")

    def test_push_refs_heads_main(self):
        self.assertBlocked("git push origin refs/heads/main")

    def test_bare_push_on_main(self):
        self.assertBlocked("git push", cwd=self.on_main)

    def test_push_remote_only_on_main(self):
        self.assertBlocked("git push -u origin", cwd=self.on_main)

    def test_push_head_on_main(self):
        self.assertBlocked("git push origin HEAD", cwd=self.on_main)

    def test_force_push_main(self):
        self.assertBlocked("git push --force origin main")

    def test_short_force_push_main(self):
        self.assertBlocked("git push -f origin main")

    def test_force_with_lease_push_main(self):
        self.assertBlocked("git push --force-with-lease origin main")

    def test_plus_refspec_main(self):
        self.assertBlocked("git push origin +main")

    def test_delete_main(self):
        self.assertBlocked("git push origin :main")

    def test_push_all(self):
        self.assertBlocked("git push --all origin")

    def test_push_main_in_compound(self):
        self.assertBlocked("git status && git push origin main")

    def test_push_main_with_env_prefix(self):
        self.assertBlocked("GIT_TRACE=0 git push origin main")

    def test_push_main_inside_bash_c(self):
        self.assertBlocked('bash -c "git push origin main"')

    def test_push_main_inside_substitution(self):
        self.assertBlocked('echo "$(git push origin main)"')

    def test_push_main_with_shell_options(self):
        self.assertBlocked('bash -o pipefail -c "git push origin main"')

    def test_push_main_after_rare_global_option(self):
        self.assertBlocked("git --super-prefix x push origin main")

    def test_push_main_via_xargs_and_eval(self):
        self.assertBlocked("echo main | xargs git push origin main")
        self.assertBlocked('eval "git push origin main"')

    def test_gh_pr_merge_admin(self):
        self.assertBlocked("gh pr merge 12 --squash --admin")

    def test_push_second_refspec_main(self):
        self.assertBlocked("git push origin feature/abc-1-nav main")


class AllowTests(HookCase):
    def test_commit_on_feature_mentioning_main(self):
        self.assertAllowed('git commit -m "fix main nav on the main screen"')

    def test_commit_on_feature_heredoc_mentioning_main(self):
        cmd = "git commit -m \"$(cat <<'EOF'\nmerge origin/main into feature\ngit push origin main\nEOF\n)\""
        self.assertAllowed(cmd)

    def test_path_main_ts(self):
        self.assertAllowed("cat src/main.ts && git add src/main.ts")

    def test_checkout_main(self):
        self.assertAllowed("git checkout main")

    def test_checkout_detach_origin_main(self):
        self.assertAllowed("git checkout --detach origin/main")

    def test_pull(self):
        self.assertAllowed("git pull origin main")

    def test_fetch(self):
        self.assertAllowed("git fetch origin main")

    def test_merge_base_diff(self):
        self.assertAllowed("git diff origin/main...HEAD")

    def test_log_range(self):
        self.assertAllowed("git log --oneline origin/main..HEAD")

    def test_rebase_onto_main(self):
        self.assertAllowed("git rebase origin/main")

    def test_gh_pr_merge_without_admin(self):
        self.assertAllowed("gh pr merge 12 --squash --delete-branch")

    def test_gh_pr_create_base_main(self):
        self.assertAllowed('gh pr create --base main --title "ABC-1: nav" --body "targets main"')

    def test_push_feature_branch(self):
        self.assertAllowed("git push -u origin feature/abc-1-nav")

    def test_bare_push_on_feature(self):
        self.assertAllowed("git push")

    def test_push_head_on_feature(self):
        self.assertAllowed("git push origin HEAD")

    def test_force_push_feature_not_this_hooks_job(self):
        self.assertAllowed("git push --force-with-lease origin feature/abc-1-nav")

    def test_echo_quoted_push_main(self):
        self.assertAllowed('echo "never run: git push origin main"')

    def test_branch_named_like_main(self):
        self.assertAllowed("git push origin feature/main-menu")

    def test_non_bash_tool(self):
        self.assertAllowed("git push origin main", tool="Edit")

    def test_malformed_json_fails_open(self):
        result = self.run_hook("", raw="{not json")
        self.assertEqual(result.returncode, 0)
        self.assertIn("allowing", result.stderr)

    def test_unbalanced_quotes_fail_open(self):
        result = self.run_hook('git commit -m "unterminated', cwd=self.on_main)
        self.assertEqual(result.returncode, 0)

    def test_commit_outside_a_repo(self):
        with tempfile.TemporaryDirectory() as plain:
            self.assertAllowed("git commit -m x", cwd=plain)


class CustomMainBranchTests(HookCase):
    main_branch = "trunk"

    def test_push_custom_main_blocked(self):
        self.assertBlocked("git push origin trunk")

    def test_commit_on_custom_main_blocked(self):
        self.assertBlocked("git commit -m x", cwd=self.on_main)

    def test_push_literal_main_allowed_when_main_branch_is_trunk(self):
        self.assertAllowed("git push origin main")


class PlaceholderFactTests(HookCase):
    """An unfilled `{{MAIN_BRANCH}}` falls back to `main`."""
    main_branch = "{{MAIN_BRANCH}}"
    repo_branch = "main"

    def test_default_main_blocked(self):
        self.assertBlocked("git push origin main")

    def test_default_commit_on_main_blocked(self):
        self.assertBlocked("git commit -m x", cwd=self.on_main)


if __name__ == "__main__":
    unittest.main()
