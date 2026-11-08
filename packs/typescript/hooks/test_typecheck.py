# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Tests for typecheck.sh / typecheck.py. Run: python3 .claude/hooks/test_typecheck.py

Each test builds a throwaway repo in a temp dir, copies the hook into it and drives it with real hook payloads.
tsc is a stub script that records its arguments, so the tests check the hook's logic, not TypeScript.
"""

import json
import os
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import unittest

HOOK_SRC = os.path.dirname(os.path.abspath(__file__))
HOOK_FILES = ("typecheck.sh", "typecheck.py")


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    if mode is not None:
        os.chmod(path, mode)


class TypecheckHookTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.t = os.path.realpath(self._tmp.name)
        self.repo = os.path.join(self.t, "repo")
        self.calls = os.path.join(self.t, "tsc-calls")
        hooks = os.path.join(self.repo, ".claude", "hooks")
        os.makedirs(os.path.join(self.repo, ".git", "worktrees", "wt1"))
        os.makedirs(hooks)
        for name in HOOK_FILES:
            shutil.copy2(os.path.join(HOOK_SRC, name), os.path.join(hooks, name))
            os.chmod(os.path.join(hooks, name), 0o755)
        self.hook = os.path.join(hooks, "typecheck.sh")
        self.state = os.path.join(self.repo, ".claude", "state", "tsc-hook")
        self.make_package(self.repo, "api")
        # A linked worktree of the repo, as git lays it out.
        self.wt = os.path.join(self.repo, ".claude", "worktrees", "wt1")
        write(os.path.join(self.wt, ".git"), f"gitdir: {self.repo}/.git/worktrees/wt1\n")
        write(os.path.join(self.repo, ".git", "worktrees", "wt1", "commondir"), "../..\n")
        self.make_package(self.wt, "api")

    # --- fixtures -----------------------------------------------------------------------------------------------
    def make_package(self, root, rel):
        write(os.path.join(root, rel, "tsconfig.json"), '{"compilerOptions":{"strict":true}}\n')
        os.makedirs(os.path.join(root, rel, "src"), exist_ok=True)

    def stub_tsc(self, directory, body="exit 0"):
        path = os.path.join(directory, "node_modules", ".bin", "tsc")
        write(path, f'#!/bin/sh\necho "$PWD|$*" >> "{self.calls}"\n{body}\n', 0o755)
        return path

    def set_facts(self, root, value):
        write(os.path.join(root, ".claude", "packs", "typescript.md"),
              "# typescript pack\n\n## Pack facts\n\n| Fact | Value | Meaning |\n|---|---|---|\n"
              f"| `TS_PACKAGE_DIRS` | {value} | dirs |\n| `TEST_FRAMEWORK` | vitest | runner |\n")

    def call_lines(self):
        if not os.path.exists(self.calls):
            return []
        with open(self.calls, encoding="utf-8") as fh:
            return fh.read().splitlines()

    def run_hook(self, payload, env=None):
        data = payload if isinstance(payload, str) else json.dumps(payload)
        full_env = dict(os.environ)
        full_env.update(env or {})
        proc = subprocess.run(["sh", self.hook], input=data, capture_output=True, text=True, env=full_env,
                              timeout=60)
        return proc.returncode, proc.stdout, proc.stderr

    @staticmethod
    def edit(path, tool="Edit"):
        return {"tool_name": tool, "tool_input": {"file_path": path}, "tool_response": {}}

    # --- H1: errors block with a capped report; clean is silent -----------------------------------------------
    def test_clean_package_exits_0_silently_and_uses_cache(self):
        self.stub_tsc(os.path.join(self.repo, "api"))
        rc, out, err = self.run_hook(self.edit(f"{self.repo}/api/src/a.ts"))
        self.assertEqual((rc, out, err), (0, "", ""))
        calls = self.call_lines()
        self.assertEqual(len(calls), 1)
        self.assertIn("--noEmit", calls[0])
        self.assertIn("--incremental", calls[0])
        self.assertIn(f"--tsBuildInfoFile {self.state}/", calls[0])

    def test_type_errors_exit_2_capped_with_total(self):
        body = ('i=1; while [ $i -le 80 ]; do echo "src/foo.ts($i,1): error TS2322: Type string is not '
                'assignable to type number."; i=$((i+1)); done; exit 2')
        self.stub_tsc(os.path.join(self.repo, "api"), body)
        rc, out, err = self.run_hook(self.edit(f"{self.repo}/api/src/__tests__/x.test.ts", "Write"))
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")
        self.assertIn("api/src/__tests__/x.test.ts", err.splitlines()[0])
        self.assertIn("80 errors total", err.splitlines()[0])
        self.assertIn("src/foo.ts", err)
        self.assertLessEqual(err.count("error TS"), 30)
        self.assertIn("more lines", err)

    def test_tsx_and_multiedit_are_targets(self):
        self.stub_tsc(os.path.join(self.repo, "api"))
        self.run_hook(self.edit(f"{self.repo}/api/src/View.tsx", "MultiEdit"))
        self.assertEqual(len(self.call_lines()), 1)

    # --- root and package come from the edited path ----------------------------------------------------------
    def test_worktree_edit_checks_the_worktree_package(self):
        self.stub_tsc(os.path.join(self.repo, "api"))
        self.stub_tsc(os.path.join(self.wt, "api"))
        self.run_hook(self.edit(f"{self.wt}/api/src/index.ts"))
        calls = self.call_lines()
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith(f"{self.wt}/api|"), calls[0])
        self.assertIn(f"-p {self.wt}/api/tsconfig.json", calls[0])

    def test_main_and_worktree_use_different_caches(self):
        self.stub_tsc(os.path.join(self.repo, "api"))
        self.stub_tsc(os.path.join(self.wt, "api"))
        self.run_hook(self.edit(f"{self.repo}/api/src/a.ts"))
        self.run_hook(self.edit(f"{self.wt}/api/src/a.ts"))
        caches = {c.split("--tsBuildInfoFile ")[1].split(" ")[0] for c in self.call_lines()}
        self.assertEqual(len(caches), 2)

    def test_auto_detect_depth_two_and_deepest_package_wins(self):
        self.make_package(self.repo, ".")
        self.make_package(self.repo, "packages/web")
        self.make_package(self.repo, "a/b/c")  # depth 3: not a package
        self.stub_tsc(self.repo)  # hoisted tsc at the root serves every package
        self.run_hook(self.edit(f"{self.repo}/packages/web/src/x.ts"))
        self.run_hook(self.edit(f"{self.repo}/a/b/c/x.ts"))
        calls = self.call_lines()
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].startswith(f"{self.repo}/packages/web|"), calls[0])
        self.assertTrue(calls[1].startswith(f"{self.repo}|"), calls[1])  # falls back to the root package

    def test_facts_table_limits_packages(self):
        self.make_package(self.repo, "web")
        self.stub_tsc(os.path.join(self.repo, "api"))
        self.stub_tsc(os.path.join(self.repo, "web"))
        self.set_facts(self.repo, "`api`")
        self.run_hook(self.edit(f"{self.repo}/web/src/a.ts"))
        self.assertEqual(self.call_lines(), [])
        self.run_hook(self.edit(f"{self.repo}/api/src/a.ts"))
        self.assertEqual(len(self.call_lines()), 1)

    def test_unfilled_or_auto_fact_falls_back_to_scan(self):
        self.stub_tsc(os.path.join(self.repo, "api"))
        for value in ("{{TS_PACKAGE_DIRS}}", "auto", ""):
            self.set_facts(self.repo, value)
            self.run_hook(self.edit(f"{self.repo}/api/src/a.ts"))
        self.assertEqual(len(self.call_lines()), 3)

    def test_fact_rejects_escaping_dirs(self):
        self.stub_tsc(os.path.join(self.repo, "api"))
        self.set_facts(self.repo, "../evil, /abs")
        self.run_hook(self.edit(f"{self.repo}/api/src/a.ts"))
        self.assertEqual(self.call_lines(), [])

    # --- H2: non-targets never run tsc -----------------------------------------------------------------------
    def test_non_targets_skip(self):
        self.stub_tsc(os.path.join(self.repo, "api"))
        other = os.path.join(self.t, "other")
        os.makedirs(os.path.join(other, ".git"))
        self.make_package(other, "api")
        self.stub_tsc(os.path.join(other, "api"))
        paths = [
            f"{self.repo}/api/package.json", f"{self.repo}/api/src/prompts/x.md", f"{self.repo}/api/src/a.ts.bak",
            f"{self.repo}/api/src/a.mts", f"{self.repo}/mobile/src/a.ts", f"{self.repo}/api/src/../../mobile/a.ts",
            f"{self.repo}/api/node_modules/pkg/index.ts", "api/src/a.ts", f"{other}/api/src/a.ts",
            f"{self.t}/no-repo/api/src/a.ts",
        ]
        for path in paths:
            rc, _, _ = self.run_hook(self.edit(path))
            self.assertEqual(rc, 0, path)
        for tool in ("Read", "Bash", "NotebookEdit"):
            self.run_hook(self.edit(f"{self.repo}/api/src/a.ts", tool))
        self.assertEqual(self.call_lines(), [])

    # --- H3: fail open ---------------------------------------------------------------------------------------
    def test_malformed_payloads_exit_0(self):
        self.stub_tsc(os.path.join(self.repo, "api"))
        for payload in ("", "not json{", '{"tool_input":{}}', "[]",
                        '{"tool_name":"Edit","tool_input":{"file_path":null}}',
                        '{"tool_name":"Edit","tool_input":{"file_path":123}}',
                        '{"tool_name":"Edit","tool_input":"x"}'):
            rc, _, _ = self.run_hook(payload)
            self.assertEqual(rc, 0, payload)
        self.assertEqual(self.call_lines(), [])

    def test_no_tsc_installed_skips_and_creates_nothing(self):
        rc, _, _ = self.run_hook(self.edit(f"{self.wt}/api/src/a.ts"))
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(os.path.join(self.wt, "api", "node_modules")))

    def test_python_missing_exits_0(self):
        proc = subprocess.run(["/bin/sh", self.hook], input=json.dumps(self.edit(f"{self.repo}/api/src/a.ts")),
                              capture_output=True, text=True, env={"PATH": "/nonexistent"}, timeout=30)
        self.assertEqual(proc.returncode, 0)

    def test_config_error_without_located_type_error_exits_0(self):
        self.stub_tsc(os.path.join(self.repo, "api"),
                      'echo "error TS5023: Unknown compiler option \'foo\'."; exit 1')
        rc, _, err = self.run_hook(self.edit(f"{self.repo}/api/src/a.ts"))
        self.assertEqual(rc, 0)
        self.assertIn("skipped", err)

    def test_timeout_kills_the_process_group(self):
        pid_file = os.path.join(self.t, "sleep.pid")
        self.stub_tsc(os.path.join(self.repo, "api"), f'sleep 300 & echo $! > "{pid_file}"; wait')
        start = time.time()
        rc, _, _ = self.run_hook(self.edit(f"{self.repo}/api/src/a.ts"), env={"TSC_HOOK_TIMEOUT": "2"})
        self.assertEqual(rc, 0)
        self.assertLess(time.time() - start, 15)
        time.sleep(0.5)
        with open(pid_file, encoding="utf-8") as fh:
            child = int(fh.read().strip())
        alive = True
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            alive = False
        if alive:
            os.kill(child, 9)
        self.assertFalse(alive, "orphan tsc child left running")

    # --- H4: lock ---------------------------------------------------------------------------------------------
    def test_concurrent_check_skips_while_lock_held(self):
        self.stub_tsc(os.path.join(self.repo, "api"), "sleep 3; exit 0")
        first = threading.Thread(target=self.run_hook, args=(self.edit(f"{self.repo}/api/src/a.ts"),))
        first.start()
        deadline = time.time() + 10
        while not self.call_lines() and time.time() < deadline:
            time.sleep(0.1)
        rc, _, _ = self.run_hook(self.edit(f"{self.repo}/api/src/b.ts"))
        first.join()
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.call_lines()), 1)

    # --- H5: the path never reaches a shell ------------------------------------------------------------------
    def test_path_is_never_shell_evaluated(self):
        self.stub_tsc(os.path.join(self.repo, "api"))
        pwned = os.path.join(self.t, "pwned")
        rc1, _, _ = self.run_hook(self.edit(f"{self.repo}/api/src/$(touch {pwned}).ts"))
        rc2, _, _ = self.run_hook(self.edit(f"{self.repo}/api/src/a b\"c'd;`touch {pwned}`.ts"))
        self.assertFalse(os.path.exists(pwned))
        self.assertEqual((rc1, rc2), (0, 0))

    def test_wrapper_is_executable_in_source(self):
        mode = os.stat(os.path.join(HOOK_SRC, "typecheck.sh")).st_mode
        self.assertTrue(mode & stat.S_IXUSR, "typecheck.sh must be executable for the hook command")


if __name__ == "__main__":
    unittest.main()
