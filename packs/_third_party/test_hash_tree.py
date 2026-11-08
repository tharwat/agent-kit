# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Tests for hash_tree.py. Run: python3 -m unittest packs/_third_party/test_hash_tree.py"""

import hashlib
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hash_tree  # noqa: E402


def write(root, rel, data):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def expected(files):
    """Reference implementation of the documented algorithm, from a {path: bytes} dict."""
    h = hashlib.sha256()
    for rel in sorted(files, key=lambda p: p.encode("utf-8")):
        data = files[rel]
        h.update(rel.encode("utf-8") + b"\0" + str(len(data)).encode() + b"\0" + data)
    return h.hexdigest()


class HashTreeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_matches_documented_algorithm(self):
        files = {"SKILL.md": b"# skill\n", "scripts/run.sh": b"echo hi\n", "references/a.md": b""}
        for rel, data in files.items():
            write(self.root, rel, data)
        self.assertEqual(hash_tree.hash_tree(self.root), expected(files))

    def test_empty_tree_is_sha256_of_nothing(self):
        self.assertEqual(hash_tree.hash_tree(self.root), hashlib.sha256(b"").hexdigest())

    def test_creation_order_does_not_matter(self):
        with tempfile.TemporaryDirectory() as other:
            write(self.root, "b.md", b"b")
            write(self.root, "a/x.md", b"x")
            write(other, "a/x.md", b"x")
            write(other, "b.md", b"b")
            self.assertEqual(hash_tree.hash_tree(self.root), hash_tree.hash_tree(other))

    def test_content_change_changes_hash(self):
        write(self.root, "SKILL.md", b"one")
        before = hash_tree.hash_tree(self.root)
        write(self.root, "SKILL.md", b"two")
        self.assertNotEqual(before, hash_tree.hash_tree(self.root))

    def test_rename_changes_hash(self):
        with tempfile.TemporaryDirectory() as other:
            write(self.root, "a.md", b"same")
            write(other, "b.md", b"same")
            self.assertNotEqual(hash_tree.hash_tree(self.root), hash_tree.hash_tree(other))

    def test_path_and_content_boundary_is_unambiguous(self):
        # Without the length prefix these two trees could feed sha256 the same byte stream.
        with tempfile.TemporaryDirectory() as other:
            write(self.root, "a", b"b\0c")
            write(other, "a", b"b")
            write(other, "c", b"")
            self.assertNotEqual(hash_tree.hash_tree(self.root), hash_tree.hash_tree(other))

    def test_empty_directory_is_ignored(self):
        write(self.root, "SKILL.md", b"x")
        before = hash_tree.hash_tree(self.root)
        os.makedirs(os.path.join(self.root, "empty"))
        self.assertEqual(before, hash_tree.hash_tree(self.root))

    def test_git_directory_is_skipped(self):
        write(self.root, "SKILL.md", b"x")
        before = hash_tree.hash_tree(self.root)
        write(self.root, ".git/HEAD", b"ref: refs/heads/main\n")
        self.assertEqual(before, hash_tree.hash_tree(self.root))

    def test_dotfiles_are_included(self):
        write(self.root, "SKILL.md", b"x")
        before = hash_tree.hash_tree(self.root)
        write(self.root, ".gitignore", b"node_modules\n")
        self.assertNotEqual(before, hash_tree.hash_tree(self.root))

    def test_paths_sort_by_utf8_bytes(self):
        files = {"B.md": b"1", "a.md": b"2", "a/b.md": b"3", "a-b.md": b"4", "é.md": b"5"}
        for rel, data in files.items():
            write(self.root, rel, data)
        self.assertEqual(hash_tree.hash_tree(self.root), expected(files))

    @unittest.skipUnless(hasattr(os, "symlink"), "no symlink support")
    def test_symlink_is_refused(self):
        write(self.root, "SKILL.md", b"x")
        os.symlink("SKILL.md", os.path.join(self.root, "link.md"))
        with self.assertRaises(ValueError):
            hash_tree.hash_tree(self.root)

    @unittest.skipUnless(hasattr(os, "symlink"), "no symlink support")
    def test_symlinked_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as outside:
            write(outside, "x.md", b"x")
            os.symlink(outside, os.path.join(self.root, "dir"))
            with self.assertRaises(ValueError):
                hash_tree.hash_tree(self.root)

    def test_missing_root_is_refused(self):
        with self.assertRaises(ValueError):
            hash_tree.hash_tree(os.path.join(self.root, "nope"))

    def test_cli_prints_hash(self):
        write(self.root, "SKILL.md", b"x")
        out = io.StringIO()
        with redirect_stdout(out):
            code = hash_tree.main([self.root])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().strip(), hash_tree.hash_tree(self.root))

    def test_cli_expect_match_and_mismatch(self):
        write(self.root, "SKILL.md", b"x")
        good = hash_tree.hash_tree(self.root)
        self.assertEqual(hash_tree.main([self.root, "--expect", good.upper()]), 0)
        err = io.StringIO()
        with redirect_stderr(err):
            code = hash_tree.main([self.root, "--expect", "0" * 64])
        self.assertEqual(code, 1)
        self.assertIn("mismatch", err.getvalue())

    def test_cli_error_exits_2(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = hash_tree.main([os.path.join(self.root, "nope")])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
