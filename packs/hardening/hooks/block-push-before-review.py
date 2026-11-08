#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""PreToolUse hook (hardening pack): nothing reaches the main branch before a hardening run passes post-op.

A /hardening run arms `.claude/state/hardening/<ticket>.active` when it branches. While an armed marker exists and
its `.claude/state/hardening/<ticket>.postop-passed` doesn't (or says `restored`), this hook blocks:
  - `git push` to the main branch (a refspec whose destination is it, or --all / --mirror);
  - `gh pr merge`;
  - commands that apply database migrations, and MCP `apply_migration` tools.
Everything else is allowed. A marker whose first line is `restored` is a finished run and arms nothing.

Contract: reads the event JSON on stdin. Exit 2 with the reason on stderr blocks; exit 0 allows. Any internal error
fails open with a one-line stderr note. It writes nothing and makes no network call. Python 3.9+, stdlib only.
"""

import json
import os
import re
import shlex
import sys
from pathlib import Path

STATE_SUBDIR = Path(".claude") / "state" / "hardening"
DEFAULT_MAIN = "main"

# Commands that apply migrations to a database. In a main-only project there is one database, so applying a
# migration before review lands it in production.
MIGRATION_PATTERNS = [
    r"\bsupabase\s+(?:db\s+push|migration\s+up)\b",
    r"\bprisma\s+(?:migrate\s+(?:deploy|dev|reset)|db\s+push)\b",
    r"\bdrizzle-kit\s+(?:push|migrate)\b",
    r"\b(?:rails|rake)\s+db:(?:migrate|schema:load)\b",
    r"\bmanage\.py\s+migrate\b",
    r"\balembic\s+(?:\S+\s+)*upgrade\b",
    r"\bknex\s+migrate:(?:latest|up)\b",
    r"\bsequelize(?:-cli)?\s+db:migrate\b",
    r"\btypeorm(?:-ts-node-\w+)?\s+migration:run\b",
    r"\bflyway\b.*\bmigrate\b",
    r"\bdbmate\s+(?:up|migrate)\b",
    r"\bgoose\b.*\bup\b",
    r"\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:db:)?(?:migrate|migration)(?::(?:up|deploy|latest|run|apply))?(?=\s|$|;|&|\|)",
    r"\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?db:push\b",
]
MIGRATION_RE = re.compile("|".join(MIGRATION_PATTERNS))
MCP_MIGRATION_RE = re.compile(r"^mcp__.*apply_migration$")
GH_MERGE_RE = re.compile(r"\bgh\s+pr\s+merge\b")
SEPARATORS = {"&&", "||", ";", "|", "&", "(", ")", "{", "}", "\n"}


def project_dir(event):
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd())


def main_branch(root):
    """MAIN_BRANCH from the Project facts table in CLAUDE.md; `main` when it can't be read."""
    try:
        text = (root / "CLAUDE.md").read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_MAIN
    match = re.search(r"^\|\s*`?MAIN_BRANCH`?\s*\|\s*`?([^|`\s]+)`?\s*\|", text, re.MULTILINE)
    if not match or match.group(1).startswith("{{"):
        return DEFAULT_MAIN
    return match.group(1)


def first_line(path):
    try:
        with path.open(encoding="utf-8") as handle:
            return handle.readline().strip()
    except OSError:
        return None


def unpassed_runs(root):
    """Tickets whose hardening run is armed and hasn't passed post-op."""
    state = root / STATE_SUBDIR
    if not state.is_dir():
        return []
    tickets = []
    for marker in sorted(state.glob("*.active")):
        if first_line(marker) == "restored":
            continue
        ticket = marker.name[: -len(".active")]
        passed = first_line(state / f"{ticket}.postop-passed")
        if passed is None or passed == "restored":
            tickets.append(ticket)
    return tickets


def tokens(command):
    lexer = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return command.split()


def segments(command):
    current = []
    for tok in tokens(command):
        if tok in SEPARATORS or set(tok) <= set("&|;()"):
            if current:
                yield current
            current = []
        else:
            current.append(tok)
    if current:
        yield current


def git_push_targets_main(words, main):
    """True when a `git ... push ...` segment can update the main branch."""
    # Skip env assignments and wrappers (`FOO=1 git push`, `command git push`).
    i = 0
    while i < len(words) and ("=" in words[i] and not words[i].startswith("-") or words[i] in ("command", "exec", "env", "sudo")):
        i += 1
    if i >= len(words) or os.path.basename(words[i]) != "git":
        return False
    i += 1
    while i < len(words) and words[i].startswith("-"):  # git -C dir / -c k=v / --git-dir=...
        if words[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace"):
            i += 1
        i += 1
    if i >= len(words) or words[i] != "push":
        return False
    positional = []
    args = words[i + 1:]
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in ("--all", "--mirror", "--branches"):
            return True
        if arg in ("--repo", "-o", "--push-option", "--receive-pack", "--exec"):
            skip_next = True
            continue
        if arg.startswith("-"):
            continue
        positional.append(arg)
    for refspec in positional[1:]:  # positional[0] is the remote
        dest = refspec.lstrip("+").split(":", 1)[-1]
        if dest.startswith("refs/heads/"):
            dest = dest[len("refs/heads/"):]
        if dest == main:
            return True
    return False


def blocked_action(event, main):
    tool = event.get("tool_name") or ""
    if MCP_MIGRATION_RE.match(tool):
        return f"migration apply through {tool}"
    if tool != "Bash":
        return None
    command = (event.get("tool_input") or {}).get("command") or ""
    if not command.strip():
        return None
    if GH_MERGE_RE.search(command):
        return "gh pr merge"
    if MIGRATION_RE.search(command):
        return "a migration apply command"
    for words in segments(command):
        if git_push_targets_main(words, main):
            return f"git push to {main}"
    return None


def message(tickets, action):
    names = ", ".join(tickets)
    return (
        f"BLOCKED: {action} while hardening run {names} hasn't passed post-op.\n"
        "Finish the run first: /post-op gates and review rounds, the required /peer-review, then the post-op report. "
        "/hardening writes the post-op-passed marker itself when they pass, and only then can the run ship.\n"
        "Never remove, rename or edit the hardening markers to get past this check."
    )


def run(stdin_text):
    event = json.loads(stdin_text or "{}")
    root = project_dir(event)
    tickets = unpassed_runs(root)
    if not tickets:
        return 0, ""
    action = blocked_action(event, main_branch(root))
    if action is None:
        return 0, ""
    return 2, message(tickets, action)


def main():
    try:
        code, reason = run(sys.stdin.read())
    except Exception as error:  # fail open: a broken hook must never block unrelated work
        print(f"block-push-before-review: internal error, allowing ({error.__class__.__name__}: {error})", file=sys.stderr)
        return 0
    if reason:
        print(reason, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
