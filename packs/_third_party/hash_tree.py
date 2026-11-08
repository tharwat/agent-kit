#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Content hash of an installed third-party skill tree (agent-kit pack.json `third_party[].sha256`).

The installer recomputes this after fetching a pinned `ref`, and refuses the install on a mismatch. The kit
test recomputes it to check a pinned entry.

Algorithm (stable across machines and file systems):
  1. Collect every regular file under the root. Directories contribute nothing by themselves, so an empty
     directory doesn't change the hash. A `.git` directory anywhere in the tree is skipped.
  2. Take each file's path relative to the root, with `/` separators, encoded as UTF-8.
  3. Sort the paths by those bytes.
  4. Feed sha256, per file in that order:  path  NUL  <decimal byte length>  NUL  <file bytes>
     The length prefix keeps one file's bytes from being read as the next file's path.
  5. The result is the lowercase hex digest (64 characters).

A symbolic link anywhere in the tree is refused (ValueError): a pinned tree must be plain files.

Usage:
  python3 hash_tree.py <dir>                 print the hash
  python3 hash_tree.py <dir> --expect <hex>  exit 0 if it matches, 1 with a one-line reason if not

Python 3.9+, standard library only.
"""

import hashlib
import os
import sys

SKIP_DIRS = {".git"}


def tree_files(root):
    """Sorted (relative POSIX path bytes, absolute path) pairs for every regular file under root."""
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise ValueError(f"not a directory: {root}")
    out = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for d in list(dirnames):
            full = os.path.join(dirpath, d)
            if os.path.islink(full):
                raise ValueError(f"symbolic link in tree: {os.path.relpath(full, root)}")
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if os.path.islink(full):
                raise ValueError(f"symbolic link in tree: {rel}")
            if not os.path.isfile(full):
                raise ValueError(f"not a regular file: {rel}")
            out.append((rel.encode("utf-8"), full))
    out.sort(key=lambda pair: pair[0])
    return out


def hash_tree(root):
    """The sha256 hex digest of the tree at root, per the module docstring."""
    h = hashlib.sha256()
    for rel, full in tree_files(root):
        with open(full, "rb") as f:
            data = f.read()
        h.update(rel)
        h.update(b"\0")
        h.update(str(len(data)).encode("ascii"))
        h.update(b"\0")
        h.update(data)
    return h.hexdigest()


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv else 2
    root = argv[0]
    expect = None
    if len(argv) == 3 and argv[1] == "--expect":
        expect = argv[2].strip().lower()
    elif len(argv) != 1:
        print("usage: hash_tree.py <dir> [--expect <hex>]", file=sys.stderr)
        return 2
    try:
        got = hash_tree(root)
    except (OSError, ValueError) as e:
        print(f"hash_tree: {e}", file=sys.stderr)
        return 2
    if expect is None:
        print(got)
        return 0
    if got == expect:
        return 0
    print(f"hash_tree: mismatch for {root}: expected {expect}, got {got}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
