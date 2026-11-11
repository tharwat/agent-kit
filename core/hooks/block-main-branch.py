#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""PreToolUse Bash hook: keep agents off the main branch.

Blocks (exit 2, reason on stderr):
  - `git commit` while the current branch is the main branch;
  - `git push` whose target is the main branch: `origin main`, `HEAD:main`,
    `refs/heads/main`, `+main`, `:main`, `--all`/`--mirror`, or a push with no
    refspec (or `HEAD`) while on main. Force flags make no difference: any
    push to main is blocked;
  - `gh pr merge --admin`.

Everything else is allowed (exit 0): paths such as `src/main.ts`,
`git checkout main`, `git pull`, `git fetch`, `git diff origin/main...HEAD`,
`gh pr create --base main`, `gh pr merge` without `--admin`, and commit
messages that mention "main".

The main branch is the `MAIN_BRANCH` row of the Project facts table in
CLAUDE.md, defaulting to `main`. The hook reads git state locally, makes no
network calls, writes nothing, and fails open (exit 0 with a one-line stderr
note) on any internal error.
"""

import json
import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True  # never leave __pycache__ in .claude/hooks/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import kit_facts
    import kit_shell
except ImportError:  # a partial install: fail open in main()
    kit_shell = kit_facts = None

DEFAULT_MAIN = "main"
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


class Blocked(Exception):
    pass


# ---------------------------------------------------------------- main branch

def read_main_branch(cwd):
    value = kit_facts.fact(kit_facts.read_facts(cwd), "MAIN_BRANCH", DEFAULT_MAIN)
    return value if BRANCH_RE.match(value) else DEFAULT_MAIN


def current_branch(directory):
    """Short name of the checked-out branch, or None (detached, not a repo, error)."""
    return kit_facts.current_branch(directory)


# ---------------------------------------------------------------- checks

def normalize_ref(ref):
    if ref.startswith("refs/heads/"):
        return ref[len("refs/heads/"):]
    return ref


def check_push(args, directory, main, branch_of=None):
    branch_of = branch_of or current_branch
    positionals = []
    everything = False
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--":
            positionals.extend(args[i + 1:])
            break
        if tok.startswith("-"):
            name = tok.split("=", 1)[0]
            if name in ("--all", "--mirror", "--branches"):
                everything = True
            if name in kit_shell.PUSH_OPTS_WITH_VALUE and "=" not in tok:
                i += 1
        else:
            positionals.append(tok)
        i += 1

    if everything:
        raise Blocked("`git push --all/--mirror` pushes every branch, including `%s`" % main)

    refspecs = positionals[1:]
    if not refspecs:
        branch = branch_of(directory)
        if branch == main:
            raise Blocked("`git push` with no refspec while on `%s` pushes `%s`" % (main, main))
        return
    for spec in refspecs:
        spec = spec.lstrip("+")
        if ":" in spec:
            src, dst = spec.split(":", 1)
            if not dst:
                dst = src
        else:
            src = dst = spec
        if dst == "HEAD":
            dst = branch_of(directory) or ""
        if normalize_ref(dst) == main:
            raise Blocked("`git push` targets `%s`" % main)


def check_git(args, directory, main, branches=None):
    """`branches` maps a directory to the branch an earlier command in this same tool call switched it to."""
    branches = {} if branches is None else branches

    def branch_of(d):
        key = os.path.normpath(d)
        return branches[key] if key in branches else current_branch(d)

    sub, rest, directory = kit_shell.git_split(args, directory)
    if sub == "commit":
        if "-h" in rest or "--help" in rest:
            return
        if branch_of(directory) == main:
            raise Blocked("`git commit` on `%s`" % main)
    elif sub == "push":
        check_push(rest, directory, main, branch_of)
    elif sub in ("checkout", "switch"):
        target = kit_facts.switched_to(sub, rest, directory, main)
        if target is not None:
            branches[os.path.normpath(directory)] = target or None


def check_gh(args):
    if len(args) >= 2 and args[0] == "pr" and args[1] == "merge" and "--admin" in args[2:]:
        raise Blocked("`gh pr merge --admin` bypasses branch protection (gate G4)")


def check_command(command, cwd, main):
    branches = {}
    for cmd in kit_shell.iter_commands(command, cwd):
        if cmd.prog == "git":
            check_git(list(cmd.args), cmd.cwd, main, branches)
        elif cmd.prog == "gh":
            check_gh(list(cmd.args))


# ---------------------------------------------------------------- entry point

def main():
    try:
        raw = sys.stdin.read()
        event = json.loads(raw)
        if kit_shell is None or kit_facts is None:
            raise ImportError("kit_shell.py or kit_facts.py is missing")
        if event.get("tool_name") != "Bash":
            return 0
        command = (event.get("tool_input") or {}).get("command") or ""
        if not command.strip():
            return 0
        cwd = event.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        main_branch = read_main_branch(cwd)
        check_command(command, cwd, main_branch)
        return 0
    except Blocked as exc:
        sys.stderr.write(
            "Blocked by the main-branch guard: %s. Work on a feature branch; /ship merges through a PR "
            "after the owner's yes (gates G3/G4).\n" % exc
        )
        return 2
    except Exception as exc:  # fail open on anything unexpected
        sys.stderr.write("block-main-branch: could not check the command (%s); allowing it.\n" % type(exc).__name__)
        return 0


if __name__ == "__main__":
    sys.exit(main())
