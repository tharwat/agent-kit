#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""PreToolUse Bash hook: no AI attribution, and ticket commits name their ticket.

Checks the message of `git commit` (`-m`, `--message`, `-F <file>` / `--file`, `-F -` with a heredoc, and the usual
`-m "$(cat <<'EOF' … EOF)"` form) and the title and body of `gh pr create|edit|comment` and
`gh issue create|edit|comment` (`--title`, `--body`, `--body-file`).

Blocks (exit 2, reason on stderr):
  - a `Co-Authored-By:` trailer, a "Generated with …" line, or a 🤖 Claude Code link line, anywhere in the text;
  - on a ticket branch (`<BRANCH_PREFIX><ticket-lowercase>-<n>-<slug>`, from the Project facts in CLAUDE.md), a commit
    subject that doesn't start with `<ticket>: `, that exact ticket key in upper case.

Allowed: commits with no message argument (the editor, `--amend --no-edit`, `-C <commit>`), any subject on a
non-ticket branch or a detached HEAD. Fails open (exit 0, one stderr line) on internal errors. Reads only CLAUDE.md,
local git state and a `-F` / `--body-file` file. No network, no writes.
"""

import json
import os
import re
import sys

sys.dont_write_bytecode = True  # never leave __pycache__ in .claude/hooks/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import kit_facts
    import kit_shell
except ImportError:  # a partial install: fail open in main()
    kit_shell = kit_facts = None

ATTRIBUTION = [
    (re.compile(r"^\s*co-authored-by\s*:", re.I | re.M), "a `Co-Authored-By:` trailer"),
    (re.compile(r"^\W*generated with\b", re.I | re.M), "a \"Generated with\" line"),
    (re.compile(r"^.*🤖.*claude", re.I | re.M), "a 🤖 Claude Code line"),
]
MAX_FILE = 256 * 1024


class Blocked(Exception):
    pass


def read_file(path, cwd):
    try:
        with open(os.path.join(cwd, path), encoding="utf-8", errors="replace") as fh:
            return fh.read(MAX_FILE)
    except OSError:
        return ""


def stdin_text(cmd):
    return "\n".join(body for body, _quoted in cmd.heredocs) + "".join(
        "\n" + str(t) for op, t in cmd.redirects if op.endswith("<<<"))


def expand(word, bodies):
    """A message word with `$(cat <<'EOF' … EOF)` substitutions replaced by their heredoc bodies."""
    text = str(word)
    if "$(" not in getattr(word, "raw", text) and "`" not in text:
        return text
    if bodies:
        out = re.sub(r"\$\((?:[^()]|\([^()]*\))*\)|`[^`]*`", lambda m: bodies.pop(0) if bodies else m.group(0), text,
                     count=len(bodies))
        return out
    return text


def option_values(args, short, long_names):
    """Values of an option given as `-m v`, `-mv`, `--message v` or `--message=v`, in order."""
    out, k = [], 0
    while k < len(args):
        a = args[k]
        if a == "--":
            break
        name = a.split("=", 1)[0]
        if name in long_names:
            if "=" in a:
                out.append(a.split("=", 1)[1])
            elif k + 1 < len(args):
                out.append(args[k + 1])
                k += 1
        elif short and a == short and k + 1 < len(args):
            out.append(args[k + 1])
            k += 1
        elif short and a.startswith(short) and len(a) > 2 and not a.startswith("--"):
            out.append(a[2:])
        k += 1
    return out


def check_attribution(text, what):
    for rx, label in ATTRIBUTION:
        if rx.search(text or ""):
            raise Blocked("%s in the %s. agent-kit forbids AI attribution (CLAUDE.kit.md, Git and workflow): remove "
                          "it" % (label, what))


def commit_message(cmd, rest, bodies):
    """(message or None, where it came from). None means no message argument (editor or reuse)."""
    words = list(rest)
    k, parts = 0, []
    while k < len(words):
        a = words[k]
        if a in ("-m", "--message") and k + 1 < len(words):
            parts.append(expand(words[k + 1], bodies))
            k += 2
            continue
        if a.startswith("--message="):
            parts.append(a.split("=", 1)[1])
        elif a.startswith("-m") and len(a) > 2 and not a.startswith("--"):
            parts.append(a[2:])
        k += 1
    if parts:
        return "\n\n".join(parts)
    files = option_values(words, "-F", ("--file",))
    if files:
        return "\n".join(stdin_text(cmd) if f == "-" else read_file(f, cmd.cwd) for f in files)
    return None


def check_commit(cmd, rest, cwd, bodies, facts):
    message = commit_message(cmd, rest, bodies)
    if message is None:
        return
    check_attribution(message, "commit message")
    ticket = kit_facts.ticket_for_branch(kit_facts.current_branch(cwd), facts)
    if not ticket:
        return
    subject = message.lstrip("\n").split("\n", 1)[0]
    if not subject.startswith(ticket + ": "):
        raise Blocked("this branch is for %s, so the commit subject must start with `%s: ` (CLAUDE.kit.md, Git and "
                      "workflow: `<ticket>: <what changed>`)" % (ticket, ticket))


def check_gh(cmd, bodies):
    args = list(cmd.args)
    if len(args) < 2 or args[0] not in ("pr", "issue") or args[1] not in ("create", "edit", "comment"):
        return
    rest = args[2:]
    what = "%s %s" % (args[0], "comment" if args[1] == "comment" else "title or body")
    texts = [expand(v, bodies) if isinstance(v, kit_shell.Word) else v
             for v in option_values(rest, "-t", ("--title",)) + option_values(rest, "-b", ("--body",))]
    for f in option_values(rest, "-F", ("--body-file",)):
        texts.append(stdin_text(cmd) if f == "-" else read_file(f, cmd.cwd))
    for t in texts:
        check_attribution(t, what)


def check_command(command, cwd):
    cmds = kit_shell.iter_commands(command, cwd)
    # Heredoc bodies in command order: a `-m "$(cat <<'EOF' … EOF)"` message is the body fed to that `cat`.
    bodies = [body for c in cmds if c.prog == "cat" for body, _quoted in c.heredocs]
    facts = None
    for cmd in cmds:
        if cmd.prog == "git":
            sub, rest, git_cwd = kit_shell.git_split(list(cmd.args), cmd.cwd)
            if sub == "commit":
                if facts is None:
                    facts = kit_facts.read_facts(cwd)
                check_commit(cmd, rest, git_cwd, list(bodies), facts)
        elif cmd.prog == "gh":
            check_gh(cmd, list(bodies))


def main():
    try:
        event = json.loads(sys.stdin.read())
        if kit_shell is None or kit_facts is None:
            raise ImportError("kit_shell.py or kit_facts.py is missing")
        if event.get("tool_name") != "Bash":
            return 0
        command = (event.get("tool_input") or {}).get("command") or ""
        if not re.search(r"\b(git|gh)\b", command):
            return 0
        cwd = event.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        check_command(command, cwd)
        return 0
    except Blocked as exc:
        sys.stderr.write("Blocked by the commit-message guard: %s.\n" % exc)
        return 2
    except Exception as exc:  # fail open on anything unexpected
        sys.stderr.write("guard-commit-message: could not check the command (%s); allowing it.\n"
                         % type(exc).__name__)
        return 0


if __name__ == "__main__":
    sys.exit(main())
