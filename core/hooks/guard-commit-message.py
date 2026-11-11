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

AI = r"(claude|claude code|codex|chatgpt|gpt-?[0-9][\w.]*|copilot|gemini|anthropic|openai)"
ATTRIBUTION = [
    (re.compile(r"^\s*co-authored-by\s*:", re.I | re.M), "a `Co-Authored-By:` trailer"),
    (re.compile(r"^\W*generated with\b.*\b%s\b" % AI, re.I | re.M), "a \"Generated with\" line"),
    (re.compile(r"^.*🤖.*\b(claude|generated)\b", re.I | re.M), "a 🤖 Claude Code line"),
]
STDIN_PATHS = {"-", "/dev/stdin", "/dev/fd/0"}
MAX_FILE = 256 * 1024
SUBST_RE = re.compile(r"\$\(\s*cat\s+<<-?\s*__kit_heredoc_(\d+)__\s*\)")
# `git commit` options that take a value, short (letters) and long
COMMIT_SHORT_VALUE = "mFCct"
COMMIT_LONG_VALUE = {"--message", "--file", "--reuse-message", "--reedit-message", "--template", "--trailer",
                     "--author", "--date", "--fixup", "--squash", "--cleanup", "--pathspec-from-file"}


class Blocked(Exception):
    pass


class Text:
    """A piece of message text, and whether we could see all of it."""

    def __init__(self, text, known=True):
        self.text = text or ""
        self.known = known


def read_file(path, cwd):
    try:
        with open(os.path.join(cwd, path), encoding="utf-8", errors="replace") as fh:
            return Text(fh.read(MAX_FILE))
    except OSError:
        return Text("", known=False)  # written earlier in the same command, or missing: unknown


def stdin_text(cmd):
    """What a command reads on stdin. A `$` or backtick in it, or a printf format, may change at run time."""
    text = "\n".join(cmd.stdin)
    known = bool(cmd.stdin) and "$" not in text and "`" not in text and not re.search(r"%[-+ #0-9.]*[sdbqifx]", text)
    return Text(text, known)


def expand(value, registry):
    """A value with each `$(cat <<'EOF' … EOF)` replaced by that heredoc's body. Any other substitution leaves the
    text unknown."""
    def body(m):
        n = int(m.group(1))
        return registry[n][1] if n < len(registry) else m.group(0)
    text = SUBST_RE.sub(body, str(value))
    # known only when the shell won't change it: no expansion outside single quotes, other than the heredoc cats
    raw = SUBST_RE.sub("", getattr(value, "raw", str(value)))
    raw = re.sub(r"'[^']*'", "", raw)
    known = "$" not in raw and "`" not in raw
    return Text(text, known)


def parse_options(args, short_value, long_value):
    """[(name, value)] for every option in a git/gh argv, short groups (`-am msg`) included. Names are `-m`,
    `--message`, … ; a flag's value is None."""
    out, k = [], 0
    while k < len(args):
        a = str(args[k])
        if a == "--":
            break
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            if "=" in a:
                out.append((name, args[k][len(name) + 1:]))
            elif name in long_value and k + 1 < len(args):
                out.append((name, args[k + 1]))
                k += 1
            else:
                out.append((name, None))
        elif a.startswith("-") and len(a) > 1:
            group = a[1:]
            for idx, ch in enumerate(group):
                if ch in short_value:
                    rest = args[k][idx + 2:]
                    if rest:
                        out.append(("-" + ch, rest))
                    elif k + 1 < len(args):
                        out.append(("-" + ch, args[k + 1]))
                        k += 1
                    break
                out.append(("-" + ch, None))
        k += 1
    return out


def check_attribution(text, what):
    text = text or ""
    if "\\n" in text:  # `$(printf 'a\\n\\nCo-Authored-By: …')`: the shell makes real newlines of these
        text += "\n" + text.replace("\\n", "\n")
    for rx, label in ATTRIBUTION:
        if rx.search(text):
            raise Blocked("%s in the %s. agent-kit forbids AI attribution (CLAUDE.kit.md, Git and workflow): remove "
                          "it" % (label, what))


def check_commit(cmd, rest, cwd, registry, facts):
    opts = parse_options(rest, COMMIT_SHORT_VALUE, COMMIT_LONG_VALUE)
    names = {n for n, _ in opts}
    if names & {"-h", "--help"}:
        return
    parts = [expand(v, registry) for n, v in opts if n in ("-m", "--message") and v is not None]
    for n, v in opts:
        if n in ("-F", "--file") and v is not None:
            parts.append(stdin_text(cmd) if str(v) in STDIN_PATHS else read_file(str(v), cwd))
    for n, v in opts:
        if n == "--trailer" and v is not None:
            check_attribution(re.sub(r"\s*[=:]\s*", ": ", str(v), count=1), "commit trailer")
    if not parts:
        return  # the editor, --amend --no-edit, -C <commit>: no message to check
    message = "\n\n".join(p.text for p in parts)
    check_attribution(message, "commit message")
    if not all(p.known for p in parts) or names & {"--fixup", "--squash"} or not cmd.cwd_known:
        return  # we can't see the whole message or the repo, or git writes the subject itself
    ticket = kit_facts.ticket_for_branch(kit_facts.current_branch(cwd), facts)
    if not ticket:
        return
    subject = message.lstrip("\n").split("\n", 1)[0]
    if not subject.startswith(ticket + ": "):
        raise Blocked("this branch is for %s, so the commit subject must start with `%s: ` (CLAUDE.kit.md, Git and "
                      "workflow: `<ticket>: <what changed>`)" % (ticket, ticket))


def check_gh(cmd, registry):
    args = list(cmd.args)
    if len(args) < 2 or args[0] not in ("pr", "issue"):
        return
    if args[1] not in ("create", "edit", "comment", "review") and not (args[0] == "pr" and args[1] == "merge"):
        return
    # pr merge --subject/--body writes the squash commit on main; review/comment bodies are posted as written
    what = "%s %s" % (args[0], {"comment": "comment", "review": "review", "merge": "merge commit"}.get(
        args[1], "title or body"))
    opts = parse_options(args[2:], "tbFBA", {"--title", "--subject", "--body", "--body-file", "--base", "--head",
                                             "--repo", "--label", "--assignee", "--reviewer", "--milestone",
                                             "--project", "--author-email", "--match-head-commit"})
    for n, v in opts:
        if v is None:
            continue
        if n in ("-t", "--title", "--subject", "-b", "--body"):
            check_attribution(expand(v, registry).text, what)
        elif n in ("-F", "--body-file"):
            check_attribution((stdin_text(cmd) if str(v) in STDIN_PATHS else read_file(str(v), cmd.cwd)).text, what)


def check_command(command, cwd):
    registry = []
    cmds = kit_shell.iter_commands(command, cwd, registry)
    facts = None
    for cmd in cmds:
        if cmd.prog == "git":
            sub, rest, git_cwd = kit_shell.git_split(list(cmd.args), cmd.cwd)
            if sub == "commit":
                if facts is None:
                    facts = kit_facts.read_facts(cwd)
                check_commit(cmd, rest, git_cwd, registry, facts)
        elif cmd.prog == "gh":
            check_gh(cmd, registry)


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
