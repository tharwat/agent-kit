# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Every kit-created file carries the owner's copyright line.

Exempt: JSON (no comment syntax; covered by the root LICENSE), the scroll-craft
upstream files (they keep their original author's notice), and non-text files.
"""
import os
import unittest

from kit_testlib import KIT

MARK = "Copyright 2026 Tharwat Abdul-Malik"
SCOPE = ["core", "packs", "sync", "installer", "tests", "INSTALL.md", "README.md", "CHANGELOG.md"]
UPSTREAM = os.path.join("packs", "scrollcraft", "skills", "scroll-craft")
COMMENTABLE = {".md", ".py", ".sh", ".yml", ".yaml", ".txt", ".mjs", ".js"}


def _kind_ok(rel):
    name = rel[:-5] if rel.endswith(".tmpl") else rel
    ext = os.path.splitext(name)[1]
    return ext in COMMENTABLE or os.path.basename(name) in ("notify", "LICENSE")


class Copyright(unittest.TestCase):
    def test_every_kit_file_has_the_owner_copyright(self):
        missing = []
        for top in SCOPE:
            base = os.path.join(KIT, top)
            paths = [base] if os.path.isfile(base) else [
                os.path.join(d, f) for d, _, fs in os.walk(base) if "__pycache__" not in d for f in fs]
            for p in paths:
                rel = os.path.relpath(p, KIT)
                if rel.startswith(UPSTREAM) or not _kind_ok(rel):
                    continue
                with open(p, encoding="utf-8") as fh:
                    if MARK not in fh.read():
                        missing.append(rel)
        self.assertEqual(missing, [], "files missing the copyright line")

    def test_license_is_mit_with_owner(self):
        with open(os.path.join(KIT, "LICENSE"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("MIT License", text)
        self.assertIn("Copyright (c) 2026 Tharwat Abdul-Malik", text)


if __name__ == "__main__":
    unittest.main()
