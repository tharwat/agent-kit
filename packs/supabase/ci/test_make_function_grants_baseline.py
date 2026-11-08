#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""
Tests for make_function_grants_baseline.py (stdlib unittest, synthetic fixtures only).

Run: python3 .github/scripts/test_make_function_grants_baseline.py
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MAKE = os.path.join(HERE, "make_function_grants_baseline.py")
CHECK = os.path.join(HERE, "check_function_grants.py")
CONFIG = ".github/scripts/function_grants_config.json"
BASELINE = ".github/scripts/function_grants_baseline.txt"
OPEN_FN = "create function public.legacy() returns int language sql security definer as 'select 1';"


class MakeBaselineTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="fn-grants-base-")
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        subprocess.run(["git", "init", "-q", self.root], check=True)
        os.makedirs(os.path.join(self.root, "supabase/migrations"))

    def write(self, rel, text):
        with open(os.path.join(self.root, rel), "w") as fh:
            fh.write(text)

    def read(self, rel, mode="r"):
        with open(os.path.join(self.root, rel), mode) as fh:
            return fh.read()

    def run_py(self, script, *args):
        r = subprocess.run([sys.executable, script, *args], cwd=self.root, capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def test_existing_migrations_are_baselined_and_new_ones_scanned(self):
        self.write("supabase/migrations/20200101000000_a.sql", OPEN_FN)
        self.write("supabase/migrations/20200102000000_b.sql", "select 1;")
        self.write("supabase/migrations/README.md", "not a migration")
        code, out = self.run_py(MAKE)
        self.assertEqual(code, 0, out)
        self.assertIn("2 migration(s)", out)
        listed = [l for l in self.read(BASELINE).splitlines() if l and not l.startswith("#")]
        self.assertEqual(listed, ["20200101000000_a.sql", "20200102000000_b.sql"])
        cfg = json.loads(self.read(CONFIG))
        self.assertEqual(cfg["baseline_sha256"], hashlib.sha256(self.read(BASELINE, "rb")).hexdigest())
        self.assertEqual(cfg["rls_helper_exemptions"], [])
        self.assertEqual(cfg["migrations_dir"], "supabase/migrations")
        # the legacy open function is baselined, so the check passes straight after install
        code, out = self.run_py(CHECK)
        self.assertEqual(code, 0, out)
        self.assertIn("0 migration(s) scanned, 2 in the frozen baseline", out)
        # and a new migration is scanned
        self.write("supabase/migrations/20261001000000_new.sql", OPEN_FN)
        code, out = self.run_py(CHECK)
        self.assertEqual(code, 1, out)
        self.assertIn("20261001000000_new.sql", out)

    def test_refuses_to_regenerate_an_existing_baseline(self):
        self.assertEqual(self.run_py(MAKE)[0], 0)
        before = self.read(BASELINE)
        self.write("supabase/migrations/20261001000000_new.sql", OPEN_FN)
        code, out = self.run_py(MAKE)
        self.assertEqual(code, 1, out)
        self.assertIn("already exists", out)
        self.assertEqual(self.read(BASELINE), before)

    def test_exemptions_are_validated_and_recorded(self):
        code, out = self.run_py(MAKE, "--exemption", "public.get_member_role")
        self.assertEqual(code, 1, out)
        self.assertIn("must be schema.name(argument types)", out)
        self.assertFalse(os.path.exists(os.path.join(self.root, BASELINE)))
        code, out = self.run_py(MAKE, "--exemption", "public.get_member_role(uuid)")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(self.read(CONFIG))["rls_helper_exemptions"], ["public.get_member_role(uuid)"])

    def test_custom_migrations_dir_and_empty_dir(self):
        os.makedirs(os.path.join(self.root, "db/migrations"))
        code, out = self.run_py(MAKE, "--migrations-dir", "db/migrations")
        self.assertEqual(code, 0, out)
        self.assertIn("0 migration(s)", out)
        self.assertEqual(json.loads(self.read(CONFIG))["migrations_dir"], "db/migrations")
        self.assertEqual(self.run_py(CHECK)[0], 0)

    def test_missing_migrations_dir_fails(self):
        code, out = self.run_py(MAKE, "--migrations-dir", "nope")
        self.assertEqual(code, 1, out)
        self.assertIn("cannot list nope", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
