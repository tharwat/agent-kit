# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Run every unit's own tests (they live next to the code and are not installed unless listed in `files`).

Python: `python3 -m unittest discover` in core/hooks, sync, packs/_third_party and packs/*/{hooks,scripts,ci}.
Node:   `node --test` for core/scripts/*.test.mjs and packs/*/scripts/*.test.mjs (skipped when node is absent).
"""
import glob
import os
import shutil
import subprocess
import sys
import unittest

from kit_testlib import KIT

ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def python_suite_dirs():
    pats = ["core/hooks", "sync", "packs/_third_party", "packs/*/hooks", "packs/*/scripts", "packs/*/ci"]
    dirs = []
    for pat in pats:
        for d in sorted(glob.glob(os.path.join(KIT, pat))):
            if os.path.isdir(d) and glob.glob(os.path.join(d, "test_*.py")):
                dirs.append(d)
    return dirs


def node_test_files():
    files = []
    for pat in ("core/scripts/*.test.mjs", "packs/*/scripts/*.test.mjs"):
        files += sorted(glob.glob(os.path.join(KIT, pat)))
    return files


class UnitSuites(unittest.TestCase):
    def test_python_suites(self):
        dirs = python_suite_dirs()
        self.assertTrue(dirs, "no unit test suites found")
        for d in dirs:
            rel = os.path.relpath(d, KIT)
            with self.subTest(suite=rel):
                p = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", d, "-t", d,
                                    "-p", "test_*.py"], cwd=d, capture_output=True, text=True, env=ENV, timeout=600)
                self.assertEqual(p.returncode, 0, f"{rel}:\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}")
                self.assertRegex(p.stderr, r"Ran [1-9]\d* tests?", f"{rel}: no tests ran")

    def test_node_suites(self):
        files = node_test_files()
        if not files:
            self.skipTest("no *.test.mjs files in the kit")
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed; skipped: " + ", ".join(os.path.relpath(f, KIT) for f in files))
        for f in files:
            rel = os.path.relpath(f, KIT)
            with self.subTest(suite=rel):
                p = subprocess.run([node, "--test", f], cwd=os.path.dirname(f), capture_output=True, text=True,
                                   timeout=600)
                self.assertEqual(p.returncode, 0, f"{rel}:\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}")


if __name__ == "__main__":
    unittest.main()
