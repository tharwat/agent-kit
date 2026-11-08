#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""
Create the frozen baseline for check_function_grants.py. Run ONCE, at install.

Migrations that already exist were applied before the check existed, and their
history can't be changed, so they are listed in the baseline and never scanned.
Every migration added afterwards is scanned.

Writes:
  .github/scripts/function_grants_baseline.txt   one migration filename per line
  .github/scripts/function_grants_config.json    migrations_dir, baseline_file,
                                                 baseline_sha256 (the pin) and
                                                 rls_helper_exemptions

It refuses to run when the baseline already exists. Regenerating it would exempt
every migration added since install, which weakens the check: that is Owner-Kept
Gate G7. A deliberate change is made by hand, with the owner's yes, editing the
baseline and its pinned hash in the same reviewed change.

Usage (from anywhere inside the repo):
  python3 .github/scripts/make_function_grants_baseline.py \
      [--migrations-dir supabase/migrations] [--exemption 'public.my_helper(uuid)' ...]
"""
import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = ".github/scripts/function_grants_config.json"
BASELINE_FILE = ".github/scripts/function_grants_baseline.txt"
HEADER = [
    "# Frozen baseline for check_function_grants.py, made once at install by",
    "# make_function_grants_baseline.py. These migrations existed before the check and",
    "# are not scanned. The list is pinned by baseline_sha256 in function_grants_config.json.",
    "# Adding a line weakens the check: Owner-Kept Gate G7.",
]


def load_checker():
    sys.dont_write_bytecode = True  # leave no __pycache__ beside the installed scripts
    spec = importlib.util.spec_from_file_location("check_function_grants", os.path.join(HERE, "check_function_grants.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def repo_root():
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else os.getcwd()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Create the frozen function-grants baseline (once).")
    ap.add_argument("--repo", help="repository root (default: git toplevel)")
    ap.add_argument("--migrations-dir", default="supabase/migrations")
    ap.add_argument("--exemption", action="append", default=[],
                    help="an RLS helper policies call as the requesting role, as schema.name(argument types)")
    a = ap.parse_args(argv)
    root = a.repo or repo_root()
    baseline_path = os.path.join(root, BASELINE_FILE)
    config_path = os.path.join(root, CONFIG_FILE)

    if os.path.exists(baseline_path):
        print(f"make_function_grants_baseline: {BASELINE_FILE} already exists. The baseline is frozen; "
              f"regenerating it would exempt newer migrations (G7). Change it by hand with the owner's yes.")
        return 1
    checker = load_checker()
    try:
        for x in a.exemption:
            checker.parse_exemption(x)
    except ValueError as e:
        print(f"make_function_grants_baseline: {e}")
        return 1
    mig_dir = os.path.join(root, a.migrations_dir)
    try:
        names = sorted(f for f in os.listdir(mig_dir) if f.endswith(".sql"))
    except OSError as e:
        print(f"make_function_grants_baseline: cannot list {a.migrations_dir}: {e}")
        return 1

    raw = ("\n".join(HEADER + names) + "\n").encode("utf-8")
    os.makedirs(os.path.dirname(baseline_path), exist_ok=True)
    with open(baseline_path, "wb") as fh:
        fh.write(raw)
    config = {
        "migrations_dir": a.migrations_dir,
        "baseline_file": BASELINE_FILE,
        "baseline_sha256": hashlib.sha256(raw).hexdigest(),
        "rls_helper_exemptions": a.exemption,
    }
    with open(config_path, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
        fh.write("\n")
    print(f"Baseline written: {len(names)} migration(s) in {BASELINE_FILE}")
    print(f"Pinned sha256 {config['baseline_sha256']} in {CONFIG_FILE}")
    print(f"RLS helper exemptions: {', '.join(a.exemption) if a.exemption else 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
