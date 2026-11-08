# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Test fixture for the worktrees pack: throwaway git repos with worktrees, in a temp dir.

Layout under the temp dir:
  origin.git        bare "remote"
  main/             the main checkout (clone of origin), with CLAUDE.md and the pack facts
  main/<wdir>/wt1   a linked worktree on its own branch, at the first commit
Git runs with an isolated HOME and no system or global config.
"""

import json
import os
import subprocess
import tempfile
import unittest

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
WRAPPER = os.path.join(HOOK_DIR, "worktree-hook.sh")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class WorktreeCase(unittest.TestCase):
    WORKTREE_DIR = ".claude/worktrees"
    ENV_FILES = "none"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.t = os.path.realpath(self._tmp.name)
        home = os.path.join(self.t, "home")
        os.makedirs(home)
        gitconfig = os.path.join(home, ".gitconfig")
        write(gitconfig, "[user]\n\tname = Test\n\temail = test@example.invalid\n"
                         "[commit]\n\tgpgsign = false\n[init]\n\tdefaultBranch = main\n")
        self.env = dict(os.environ, HOME=home, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=gitconfig)
        self.env.pop("GIT_DIR", None)
        self.env.pop("GIT_WORK_TREE", None)
        self.origin = os.path.join(self.t, "origin.git")
        self.main = os.path.join(self.t, "main")
        self.git(["init", "--quiet", "--bare", "-b", "main", self.origin], self.t)
        self.git(["clone", "--quiet", self.origin, self.main], self.t)
        write(os.path.join(self.main, "CLAUDE.md"),
              "# Project\n\n## Project facts\n\n| Fact | Value | Meaning |\n|---|---|---|\n"
              "| `MAIN_BRANCH` | main | The only long-lived branch |\n")
        write(os.path.join(self.main, ".gitignore"), ".claude/state/\n.claude/worktrees/\nworktrees/\n*.env\n.env*\n")
        write(os.path.join(self.main, "a.txt"), "one\n")
        write(os.path.join(self.main, "api", "index.js"), "export {};\n")
        self.set_facts(self.WORKTREE_DIR, self.ENV_FILES)
        self.git(["add", "-A"], self.main)
        self.git(["commit", "--quiet", "-m", "base"], self.main)
        self.git(["push", "--quiet", "origin", "main"], self.main)
        self.base_sha = self.head(self.main)
        self.wt = self.add_worktree("wt1")

    # --- helpers ------------------------------------------------------------------------------------------------
    def git(self, args, cwd):
        proc = subprocess.run(["git"] + args, cwd=cwd, env=self.env, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
        return proc.stdout.strip()

    def head(self, cwd):
        return self.git(["rev-parse", "HEAD"], cwd)

    def set_facts(self, worktree_dir, env_files):
        write(os.path.join(self.main, ".claude", "packs", "worktrees.md"),
              "# Pack: worktrees\n\n## Pack facts\n\n| Fact | Value | Meaning |\n|---|---|---|\n"
              f"| `WORKTREE_DIR` | {worktree_dir} | where worktrees live |\n"
              f"| `WORKTREE_ENV_FILES` | {env_files} | env files to link |\n")

    def add_worktree(self, name, at=None):
        path = os.path.join(self.main, self.WORKTREE_DIR, name)
        self.git(["worktree", "add", "--quiet", "-b", f"worktree-{name}", path, at or self.base_sha], self.main)
        return os.path.realpath(path)

    def advance_origin(self, text="two\n"):
        """Push a commit to origin/main from a separate clone, as another session would.

        The main checkout's origin/main ref only moves when a hook (or test) fetches.
        """
        other = os.path.join(self.t, "other")
        if not os.path.isdir(other):
            self.git(["clone", "--quiet", self.origin, other], self.t)
        self.git(["pull", "--quiet", "--ff-only", "origin", "main"], other)
        write(os.path.join(other, "a.txt"), text)
        self.git(["commit", "--quiet", "-am", "advance"], other)
        self.git(["push", "--quiet", "origin", "main"], other)
        return self.head(other)

    def run_hook(self, name, payload, cwd=None, env=None):
        data = payload if isinstance(payload, str) else json.dumps(payload)
        full_env = dict(self.env)
        full_env.update(env or {})
        proc = subprocess.run(["sh", WRAPPER, name], input=data, cwd=cwd or self.t, env=full_env,
                              capture_output=True, text=True, timeout=120)
        return proc.returncode, proc.stdout, proc.stderr

    def run_script(self, script, args, cwd):
        proc = subprocess.run(["python3", os.path.join(HOOK_DIR, script)] + list(args), cwd=cwd, env=self.env,
                              capture_output=True, text=True, timeout=120)
        return proc.returncode, proc.stdout, proc.stderr

    def log_text(self):
        path = os.path.join(self.main, ".claude", "state", "worktree.log")
        return read(path) if os.path.exists(path) else ""

    def stamp(self, worktree):
        return os.path.join(worktree, ".claude", "state", "worktree-initialized")
