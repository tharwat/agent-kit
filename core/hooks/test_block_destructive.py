#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Tests for block-destructive.py. Run: python3 -m unittest test_block_destructive.py

BLOCKED and ALLOWED are keyed by the manifest `destructive_patterns` reason; the kit's own tests check that every
reason has at least one blocked case here."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "block-destructive.py")
SESSION = "0f0e0d0c-test-session"

BLOCKED = {
    "rm": ["rm a", "rm -fr x", "rm -r -f x", "cd d && rm -rf .", "ls | xargs rm", "ls | xargs -0 rm -f",
           "find . -exec rm {} +", "find . -name x -exec rm -f {} \\;", 'bash -c "rm x"', "sudo rm x",
           "/bin/rm x", "git rm x", "git rm -r --force dir", 'echo "$(rm x)"', "x=`rm y`", "env FOO=1 rm x",
           "for f in *.log; do rm \"$f\"; done", "rm -- -weird", "rm", 'eval "rm x"', "timeout 5 rm x",
           "true && (cd sub; rm x)", "rm .claude/state/tmp", "rm ~/x", 'bash -c "echo it\'s"; rm -rf x',
           'bash -o pipefail -c "rm -rf x"', "bash <<'EOF'\nrm -rf build\nEOF", "cat <<EOF\n$(rm -rf x)\nEOF",
           'echo "use <<EOF in bash"\nrm -rf x', "echo 'rm -rf build' | bash", "cat <<'X' | sh\nrm -rf build\nX",
           "bash -euo pipefail -c 'rm -rf build'", "(( m = 1 << n ))\nrm -rf build",
           "function cleanup { rm -rf build; }; cleanup", "rm -rf build; printf $'don\\'t\\n'",
           "x=$(echo hi # it's\n)\nrm -rf build"],
    "rmdir": ["rmdir d", "sudo rmdir d", "find . -type d -exec rmdir {} +"],
    "find -delete": ["find . -name '*.log' -delete", "find build -type f -delete -print"],
    "unlink": ["unlink f", "bash -c 'unlink f'"],
    "programmatic delete": [
        "python3 -c \"import shutil; shutil.rmtree('x')\"", "python -c 'import os; os.remove(\"a\")'",
        "python3 -c 'from pathlib import Path; Path(\"a\").unlink()'",
        "node -e \"fs.rmSync('x',{recursive:true})\"", "node -e \"require('fs').unlinkSync('a')\"",
        "node --eval=\"fs.promises.rm('x')\"", "ruby -e 'FileUtils.rm_rf(\"x\")'", "perl -e 'unlink \"a\"'",
        "python3 -c \"import subprocess; subprocess.run(['rm', '-rf', 'x'])\"",
        "node -e \"require('child_process').execSync('rm -rf x')\"",
        "python3 -Bc \"import shutil; shutil.rmtree('x')\"", "python3 -W ignore -c \"import shutil; shutil.rmtree('x')\"",
        "perl -i -ne 'unlink \"a\"'", "node -pe \"require('fs').unlinkSync('x')\"", "perl -le 'unlink \"x\"'",
        "python3 - <<'X'\nimport shutil; shutil.rmtree('build')\nX", "python3 <<'X'\nimport os; os.remove('a')\nX",
        "echo \"import os; os.remove('a')\" | python3", "node <<< \"require('fs').rmSync('x')\"",
        "uv run python -c \"import shutil; shutil.rmtree('build')\"",
        "poetry run python -c \"import os; os.remove('x')\"", "ruby -e '`rm -rf x`'"],
    "git reset --hard": ["git reset --hard", "git reset --hard HEAD~1", "git -C x reset --hard HEAD~1",
                         "git --git-dir=.git reset --hard", "git -c core.x=y reset --hard",
                         "cd sub && git reset --hard origin/main", 'bash <<< "git reset --hard"',
                         'bash -O extglob -c "git reset --hard"', 'eval "echo it\'s"; git reset --hard',
                         "git submodule foreach 'git reset --hard'"],
    "git clean": ["git clean -fd", "git clean -nf", "git clean -fdx", "git clean -n -f", "git clean",
                  "git clean -i", "git clean --dry-run --force", "git -C x clean -fd", "git --work-tree=. clean -f",
                  "git submodule foreach --recursive git clean -fdx"],
    "git branch -D": ["git branch -D x", "git branch --delete --force x", "git branch -d -f x", "git branch -df x",
                      "git -C x branch -D y", "git branch -f main HEAD~3", "git -C . branch -f x",
                      "git branch --force x y"],
    "force push": ["git push -f", "git push --force", "git push --force-with-lease", "git push --force-with-lease=x",
                   "git push origin +feature/x", "git push origin feature/x +other", "git push -uf origin x",
                   "git push -fu origin x", "git -C x push --force", "git push origin x --force"],
    "git checkout -- <path> discards changes": [
        "git checkout -- path", "git checkout .", "git checkout -f", "git checkout --force main",
        "git checkout HEAD -- src/", "git checkout main a.ts", "git checkout ./src", "git -C x checkout -- a",
        "git checkout -qf main", "git checkout --pathspec-from-file=list.txt", "git checkout --ours a.ts",
        "git checkout keep.txt", "git checkout -p keep.txt", "git checkout *.py", "git checkout 'src/*.ts'",
        "git diff --name-only | xargs git checkout --", "git ls-files -m | xargs git checkout"],
    "git stash drop/clear": ["git stash drop", "git stash drop stash@{1}", "git stash clear", "git -C x stash clear",
                             "git stash -q drop"],
    "git restore": ["git restore f", "git restore --worktree f", "git restore --staged --worktree f",
                    "git restore -s HEAD~1 f", "git restore -SW f", "git restore .", "git restore --source=HEAD f"],
    "git switch -f": ["git switch -f x", "git switch --force x", "git switch --discard-changes x",
                      "git switch -fc x"],
    "git worktree remove --force": ["git worktree remove --force p", "git worktree remove -f p",
                                    "git worktree remove p --force", "git worktree remove p -f"],
}

ALLOWED = {
    "rm": ['grep "rm " f', "echo rm", "git rm --cached x", "git rm -r --cached dir", "rm --help",
           'git commit -m "drop the rm call"', "grep -rn \"rm -rf\" docs/", "echo 'rm -rf /'", "command -v rm",
           "man rm", "cat <<'EOF'\nrm -rf /\nEOF", "cat <<'EOF'\n$(rm x)\nEOF", 'echo "use <<EOF in bash"',
           "bash run.sh <<EOF\nrm x\nEOF", "echo 'rm x' | cat", "python3 - <<'X'\nprint('ok')\nX"],
    "rmdir": ["echo rmdir", "mkdir -p d"],
    "find -delete": ["find . -name '*.log'", "find . -name '-delete'", "grep -- -delete f"],
    "unlink": ["echo unlink", "grep unlink src/"],
    "programmatic delete": ["python3 script.py", "node app.js", "python3 -c 'print(1)'",
                            "perl -ne 'print if /unlink/' x", "uv run pytest", "poetry run python app.py",
                            "python3 - <<'EOF'\ns = s.replace('rm -f x', 'mv x x.bak')\nEOF",
                            "python3 -c \"print('use os.remove to delete')\"",
                            "node -e \"console.log('ok')\"", "python3 -m unittest discover"],
    "git reset --hard": ["git reset", "git reset --soft HEAD~1", "git reset HEAD a.ts", "git log --grep=reset"],
    "git clean": ["git clean -n", "git clean --dry-run", "git clean -nd", "git clean -n -d -x", "git clean -Xn",
                  "git clean -X -n"],
    "git branch -D": ["git branch -d x", "git branch --delete x", "git branch -a", "git branch new-feature",
                      "git branch -m old new", "git branch -u origin/x", "git branch --format=%(refname)",
                      "git branch -M old new", "git branch -C old new"],  # no such branch here: see OverwriteBranch
    "force push": ["git push -u origin feature/x", "git push", "git push origin HEAD", "git push --follow-tags",
                   "git push -o ci.skip origin x", "git push origin feature/x:feature/x"],
    "git checkout -- <path> discards changes": [
        "git checkout feature/x", "git checkout --detach origin/main", "git checkout -b feature/x origin/main",
        "git checkout -", "git checkout main", "git checkout -B feature/x", "git checkout -t origin/x"],
    "git stash drop/clear": ["git stash", "git stash list", "git stash pop", "git stash push -m wip",
                             "git stash show -p"],
    "git restore": ["git restore --staged f", "git restore -S f", "git restore --staged -s HEAD~1 f"],
    "git switch -f": ["git switch x", "git switch -c x", "git switch -cfix-x", "git switch --detach origin/main"],
    "git worktree remove --force": ["git worktree remove p", "git worktree list", "git worktree add ../wt -b x",
                                    "git submodule foreach git status", "git submodule update --init"],
}


def run_hook(command, cwd, session=SESSION, tool="Bash", raw=None, project=None):
    payload = raw if raw is not None else json.dumps({
        "hook_event_name": "PreToolUse", "tool_name": tool, "session_id": session,
        "tool_input": {"command": command, "description": "test"}, "cwd": cwd,
    })
    env = dict(os.environ, CLAUDE_PROJECT_DIR=project or cwd)
    return subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True, env=env,
                          timeout=30)


class HookCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = os.path.realpath(cls._tmp.name)
        cls.project = os.path.join(root, "project")
        os.makedirs(os.path.join(cls.project, ".claude", "state", "tmp", "job"))
        cls.scratch = os.path.join(root, "claude-1", "-proj", SESSION, "scratchpad")
        cls.other_scratch = os.path.join(root, "claude-1", "-proj", "another-session", "scratchpad")
        for d in (cls.scratch, cls.other_scratch, os.path.join(cls.scratch, "sub")):
            os.makedirs(d, exist_ok=True)
        for f in (os.path.join(cls.scratch, "a.txt"), os.path.join(cls.scratch, "b.txt"),
                  os.path.join(cls.other_scratch, "a.txt"), os.path.join(cls.project, "keep.txt")):
            open(f, "w").close()
        os.symlink(cls.project, os.path.join(cls.scratch, "link-out"))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def assertBlocked(self, command, reason=None, cwd=None, **kw):
        r = run_hook(command, cwd or self.project, project=self.project, **kw)
        self.assertEqual(r.returncode, 2, "expected block: %r\nstderr: %s" % (command, r.stderr))
        self.assertIn("destructive-command guard", r.stderr)
        self.assertIn("pre-agent-kit", r.stderr)  # the message teaches the allowed alternative
        if reason:
            self.assertIn(": %s (" % reason, r.stderr)

    def assertAllowed(self, command, cwd=None, **kw):
        r = run_hook(command, cwd or self.project, project=self.project, **kw)
        self.assertEqual(r.returncode, 0, "expected allow: %r\nstderr: %s" % (command, r.stderr))
        return r


class Table(HookCase):
    def test_blocked(self):
        for reason, cmds in BLOCKED.items():
            for cmd in cmds:
                with self.subTest(reason=reason, cmd=cmd):
                    self.assertBlocked(cmd, reason)

    def test_allowed(self):
        for reason, cmds in ALLOWED.items():
            for cmd in cmds:
                with self.subTest(reason=reason, cmd=cmd):
                    self.assertAllowed(cmd)


class ScratchDir(HookCase):
    def test_rm_inside_session_scratchpad(self):
        self.assertAllowed("rm %s/a.txt" % self.scratch)
        self.assertAllowed("rm -r %s/sub" % self.scratch)
        self.assertAllowed("cd %s && rm a.txt b.txt" % self.scratch)

    def test_rm_inside_state_tmp(self):
        self.assertAllowed("rm -r .claude/state/tmp/job")

    def test_symlink_out_of_scratch(self):
        self.assertBlocked("rm -r %s/link-out" % self.scratch, "rm")

    def test_dotdot_escape(self):
        self.assertBlocked("rm %s/../../../../project/keep.txt" % self.scratch, "rm")
        self.assertBlocked("rm -r .claude/state/tmp/../../settings.json", "rm")

    def test_other_sessions_scratchpad(self):
        self.assertBlocked("rm %s/a.txt" % self.other_scratch, "rm")

    def test_no_session_id(self):
        self.assertBlocked("rm %s/a.txt" % self.scratch, "rm", session="")

    def test_glob_operand(self):
        self.assertBlocked("rm %s/*.txt" % self.scratch, "rm")
        self.assertBlocked("rm $SCRATCH/a.txt", "rm")

    def test_scratch_root_itself(self):
        self.assertBlocked("rm -r %s" % self.scratch, "rm")
        self.assertBlocked("rm -r .claude/state/tmp", "rm")

    def test_subshell_or_pipeline_cd_does_not_reach_rm(self):
        self.assertBlocked("(cd %s; true); rm keep.txt" % self.scratch, "rm")
        self.assertBlocked("cd %s | true; rm keep.txt" % self.scratch, "rm")
        self.assertAllowed("(cd %s && rm a.txt)" % self.scratch)

    def test_unknown_cwd_blocks_relative_operands(self):
        for cmd in ("cd %s && cd - && rm a.txt", 'cd %s && cd "$OLDPWD" && rm a.txt', "cd %s && popd && rm a.txt"):
            with self.subTest(cmd=cmd):
                self.assertBlocked(cmd % self.scratch, "rm")
        self.assertBlocked("cd %s & rm a.txt" % self.scratch, "rm")  # the cd ran in a background subshell
        self.assertAllowed("cd - && rm %s/a.txt" % self.scratch)  # an absolute operand is still known

    def test_mixed_operands(self):
        self.assertBlocked("rm %s/a.txt keep.txt" % self.scratch, "rm")

    def test_scratch_outside_a_temp_root(self):
        self.assertBlocked("rm /%s/scratchpad/x" % SESSION, "rm")



class OverwriteBranch(HookCase):
    """Owner decision: -B / -C / -M (and -m / -c with --force) are blocked only when the target branch exists."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.repo = os.path.join(os.path.dirname(cls.project), "repo")
        os.makedirs(cls.repo)

        def git(*args):
            subprocess.run(["git", "-C", cls.repo] + list(args), check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "i")
        git("branch", "feature/x")

    def test_existing_target_blocked(self):
        for cmd in ("git checkout -B feature/x", "git checkout -B feature/x origin/main", "git checkout -qB main",
                    "git checkout -Bmain", "git switch -C feature/x", "git switch -qC main",
                    "git switch --force-create feature/x", "git switch --force-create=main",
                    "git branch -M feature/x", "git branch -M old feature/x", "git branch -C main",
                    "git branch -m -f old main", "git branch --move --force old main", "git branch -cf old main",
                    "cd / && git -C %s checkout -B main" % self.repo):
            with self.subTest(cmd=cmd):
                self.assertBlocked(cmd, "git branch -D", cwd=self.repo)

    def test_new_target_allowed(self):
        for cmd in ("git checkout -B new-thing", "git checkout -B new-thing origin/main", "git switch -C new-thing",
                    "git switch --force-create=new-thing", "git branch -M new-name", "git branch -M main renamed",
                    "git branch -C main copy", "git checkout -bfixB", "git checkout -b feature/y",
                    "git switch -cmain2"):
            with self.subTest(cmd=cmd):
                self.assertAllowed(cmd, cwd=self.repo)

    def test_unknown_target_blocked(self):
        for cmd in ('git checkout -B "$BRANCH"', "cd - && git checkout -B new-thing", "git switch -C ${B}"):
            with self.subTest(cmd=cmd):
                self.assertBlocked(cmd, "git branch -D", cwd=self.repo)

    def test_delete_and_plain_force_still_blocked(self):
        for cmd in ("git branch -D new-thing", "git branch -f new-thing", "git branch -d --force new-thing"):
            with self.subTest(cmd=cmd):
                self.assertBlocked(cmd, "git branch -D", cwd=self.repo)


class FailOpen(HookCase):
    def test_non_bash_tool(self):
        self.assertAllowed("rm -rf x", tool="Write")

    def test_malformed_json(self):
        r = run_hook("", self.project, raw="{not json", project=self.project)
        self.assertEqual(r.returncode, 0)
        self.assertIn("allowing it", r.stderr)

    def test_unbalanced_quotes(self):
        r = run_hook('echo "abc', self.project, project=self.project)
        self.assertEqual(r.returncode, 0)

    def test_empty_command(self):
        self.assertAllowed("   ")


if __name__ == "__main__":
    unittest.main()
