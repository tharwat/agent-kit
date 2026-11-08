# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Shared helpers for the kit's self-tests. Standard library only."""
import contextlib
import glob
import io
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "installer"))
import agent_kit  # noqa: E402
import schema_check  # noqa: E402

SKIP_DIRS = {".git", "__pycache__", "node_modules"}


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def manifest():
    return load_json(os.path.join(KIT, "manifest.json"))


def unit_files():
    """{unit name: pack.json path} for core and every packs/*/pack.json on disk."""
    out = {"core": os.path.join(KIT, "core", "pack.json")}
    for p in sorted(glob.glob(os.path.join(KIT, "packs", "*", "pack.json"))):
        data = load_json(p)
        out[data.get("name") or os.path.basename(os.path.dirname(p))] = p
    return out


def kit_text_files(roots=("core", "packs")):
    """(relpath, text) for every UTF-8 file under the given kit roots."""
    for root in roots:
        base = os.path.join(KIT, root)
        for dirpath, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for f in sorted(files):
                if f == ".DS_Store" or f.endswith(".pyc"):
                    continue
                path = os.path.join(dirpath, f)
                try:
                    with open(path, encoding="utf-8") as fh:
                        text = fh.read()
                except (UnicodeDecodeError, OSError):
                    continue
                yield os.path.relpath(path, KIT).replace(os.sep, "/"), text


def copy_kit(dest):
    """A private copy of the kit to mutate (upgrade tests, fixture packs)."""
    shutil.copytree(KIT, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "node_modules"))
    return dest


def run(argv):
    """Run the installer CLI in-process. Returns (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = agent_kit.main(argv)
    return rc, out.getvalue(), err.getvalue()


def snapshot(root):
    """{relpath: (mtime_ns, size)} for every file under root."""
    snap = {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__"}]
        for f in files:
            p = os.path.join(dirpath, f)
            st = os.stat(p)
            snap[os.path.relpath(p, root)] = (st.st_mtime_ns, st.st_size)
    return snap


def read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def full_answers(kit_root, packs=(), **extra):
    """Answers that fill every fact of core + packs (example, else default, else a stub)."""
    facts = {}
    paths = {"core": os.path.join(kit_root, "core", "pack.json")}
    for p in glob.glob(os.path.join(kit_root, "packs", "*", "pack.json")):
        d = load_json(p)
        paths[d.get("name")] = p
    core_facts = load_json(paths["core"]).get("facts", [])
    ticket = next((f.get("example") or f.get("default") for f in core_facts if f["name"] == "TICKET_SYSTEM"), None)
    auto = (ticket,) if ticket in paths and load_json(paths[ticket]).get("kind") == "ticket" else ()
    for u in ("core",) + tuple(packs) + auto:  # the installer adds the ticket pack TICKET_SYSTEM names
        for f in (load_json(paths[u]).get("facts", []) if u in paths else []):
            if "{{" in f.get("default", ""):
                continue  # a default that refers to another fact: let the installer fill it
            facts[f["name"]] = f.get("example") or f.get("default") or "stub"
    facts.update({"PROJECT_NAME": "Acme", "PROJECT_SUMMARY": "Invoices for small agencies", "TICKET_PREFIX": "ABC",
                  "TEST_COMMANDS": [".: npm test"], "CRITICAL_DOMAIN": "billing — invoice totals",
                  "OPEN_ITEMS_TICKET": "ABC-1", "MAIN_BRANCH": "main"})
    ans = {"facts": facts, "packs": list(packs), "options": {"github": True}}
    for k, v in extra.items():
        ans[k] = v
    return ans


def write_answers(dirpath, answers, name="answers.json"):
    p = os.path.join(dirpath, name)
    write(p, json.dumps(answers, indent=2))
    return p


class TempDirs:
    """Mixin: self.tmp() returns a fresh TemporaryDirectory path, cleaned up after the test."""

    def tmp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return td.name
