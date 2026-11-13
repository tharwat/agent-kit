#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Shared shell-command parser for the kit's PreToolUse Bash hooks. Standard library only.

The hooks match parsed commands, never raw text, so `git commit -m "drop the rm call"` or
`grep -rn "rm -rf" docs/` are data, not commands. This module turns a Bash tool command string into the simple
commands the shell would run:

  iter_commands(command, cwd)  yields Cmd(argv, cwd, redirects, heredocs) for every simple command, including those
                               in `$(…)`, backticks, `<(…)`, subshells and control-flow bodies, the code given to
                               `bash -c` / `sh -c` / `eval`, a script fed to a shell on stdin (`bash <<'EOF'`,
                               `bash <<< "…"`), substitutions in an unquoted heredoc, and the command run by
                               `xargs` or `find -exec`. Leading `VAR=value` words and wrappers (`env`, `sudo`, `nice`,
                               `timeout <n>`, …) are stripped. `cd <dir>` updates the tracked cwd for the commands
                               after it, within the same subshell, never across a pipe.
  inline_code(argv)            the code string of `python[3] -c`, `node -e/--eval/-p`, `ruby -e`, `perl -e/-E`, or None.
  git_split(args, cwd)         (subcommand, its args, cwd after `-C`) for a `git` argv, past git's global options.
  heredoc_bodies(command)      [(tag, body)] for every heredoc in the command.

It is a guardrail parser, not a shell: it doesn't expand variables or globs. Unbalanced quotes at the top level raise
ParseError, and the hooks fail open on it (the shell refuses that command too). A nested body that doesn't parse (a
`bash -c` string, `$(…)`) is skipped; the commands around it are still checked.
"""

import os
import re

__all__ = ["ParseError", "Cmd", "Word", "parse", "iter_commands", "inline_code", "interpreter_mode",
           "interpreter_reads_stdin", "git_split", "heredoc_bodies", "PUSH_OPTS_WITH_VALUE",
           "strip_heredocs", "strip_prefix", "has_expansion", "EXEC_FLAGS", "SHELLS", "GIT_OPTS_WITH_VALUE"]

MAX_DEPTH = 4
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
OPERATORS = ("&&", "||", ";;", "|&", ";", "|", "&", "(", ")")
WRAPPERS = {"env", "command", "builtin", "exec", "nohup", "time", "stdbuf", "sudo", "nice", "timeout", "xargs"}
RESERVED = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}"}
ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
HEREDOC_OP_RE = re.compile(r"<<(-?)[ \t]*(\\?[A-Za-z_][A-Za-z0-9_.-]*|'[^'\n]*'|\"[^\"\n]*\")")
HEREDOC_MARK = "__kit_heredoc_%d__"
HEREDOC_MARK_RE = re.compile(r"^__kit_heredoc_(\d+)__$")
EXPANSION_CHARS = set("*?[]$`~{}")
GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env",
                       "--super-prefix", "--list-cmds", "--attr-source"}
EXEC_FLAGS = {"-exec", "-execdir", "-ok", "-okdir"}
PUSH_OPTS_WITH_VALUE = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}


class ParseError(ValueError):
    pass


class Word(str):
    """A shell word with quotes removed. `.raw` is the source text; `.subs` the command-substitution bodies in it."""

    def __new__(cls, value, raw="", subs=()):
        w = str.__new__(cls, value)
        w.raw = raw
        w.subs = list(subs)
        return w


class Simple:
    def __init__(self):
        self.words = []
        self.redirects = []  # (op, Word)
        self.depth = 0          # subshell depth at this level of text
        self.piped = False      # part of a pipeline (runs in its own subshell)
        self.pipe_out = False   # its stdout feeds the next command
        self.background = False # ended by `&` (runs in its own subshell)

    def __bool__(self):
        return bool(self.words or self.redirects)


class Cmd:
    """One simple command after prefix stripping: argv (list of Word), the cwd it runs in, its redirects, the bodies
    of its heredocs as (body, quoted), and the stdin text it gets (`stdin`)."""

    def __init__(self, argv, cwd, redirects=(), heredocs=(), cwd_known=True, stdin=(), operands_unknown=False,
                 pipe_out=False):
        self.argv = argv
        self.pipe_out = pipe_out  # its stdout feeds the next command, not the terminal
        self.operands_unknown = operands_unknown  # run by xargs or find -exec: more operands arrive at run time
        self.cwd = cwd
        self.cwd_known = cwd_known  # False after `cd -`, `cd "$DIR"`, `popd`: cwd is then only a guess
        self.redirects = list(redirects)
        self.heredocs = list(heredocs)
        self.stdin = list(stdin)    # text fed on stdin that we can see: heredocs, here-strings, a piped echo/cat

    @property
    def prog(self):
        return os.path.basename(self.argv[0]) if self.argv else ""

    @property
    def args(self):
        return self.argv[1:]

    def __repr__(self):
        return "Cmd(%r, cwd=%r)" % (list(self.argv), self.cwd)


# ---------------------------------------------------------------- heredocs

def _heredocs(command, registry):
    """Cut heredoc bodies out of the text. Each `<<TAG` operator in code (not inside quotes or a comment) is replaced
    by `<<__kit_heredoc_<n>__`, where n indexes registry entries (tag, body, quoted). Returns the cut text."""
    out = []
    pending = []  # (tag, strip_tabs, quoted, index)
    stack = []    # context: "'", '"', "`", "$(", "((" (arithmetic)
    i, n = 0, len(command)
    while i < n:
        c = command[i]
        top = stack[-1] if stack else None
        if c == "\n" and pending:
            out.append(c)
            i += 1
            for tag, dash, quoted, idx in pending:
                lines = []
                while i < n:
                    j = command.find("\n", i)
                    line = command[i:j if j >= 0 else n]
                    i = j + 1 if j >= 0 else n
                    if (line.lstrip("\t") if dash else line).strip() == tag:
                        break
                    lines.append(line.lstrip("\t") if dash else line)  # <<- strips leading tabs
                registry[idx] = (tag, "\n".join(lines), quoted)
            pending = []
            continue
        if top == "'":
            out.append(c)
            i += 1
            if c == "'":
                stack.pop()
            continue
        if top == "$'":
            if c == "\\":
                out.append(command[i:i + 2])
                i += 2
                continue
            out.append(c)
            i += 1
            if c == "'":
                stack.pop()
            continue
        if c == "\\":
            out.append(command[i:i + 2])
            i += 2
            continue
        if top == "((":
            if command.startswith("))", i):
                stack.pop()
                out.append("))")
                i += 2
                continue
            out.append(c)
            i += 1
            continue
        if top == '"':
            if c == '"':
                stack.pop()
            elif c == "`":
                stack.append("`")
            elif command.startswith("$(", i):
                stack.append("((" if command.startswith("$((", i) else "$(")
                out.append(command[i:i + 2])
                i += 2
                continue
            out.append(c)
            i += 1
            continue
        # code: top level, inside $( … ) or backticks
        if top == "`" and c == "`":
            stack.pop()
        elif command.startswith("$'", i):
            stack.append("$'")
            out.append("$'")
            i += 2
            continue
        elif c in "'\"`":
            stack.append(c)
        elif command.startswith("((", i) and command[:i].rstrip(" \t")[-1:] in ("", "\n", ";", "&", "|", "("):
            stack.append("((")  # an arithmetic command: `<<` in it is a shift
            out.append("((")
            i += 2
            continue
        elif command.startswith("$((", i):
            stack.append("((")
            out.append("$((")
            i += 3
            continue
        elif command.startswith("$(", i):
            stack.append("$(")
            out.append("$(")
            i += 2
            continue
        elif c == ")" and top == "$(":
            stack.pop()
        elif c == "#" and (i == 0 or command[i - 1] in " \t\n;&|()"):
            j = command.find("\n", i)
            j = n if j < 0 else j
            out.append(command[i:j])
            i = j
            continue
        elif command.startswith("<<<", i):  # a here-string, not a heredoc
            out.append("<<<")
            i += 3
            continue
        elif command.startswith("<<", i):
            m = HEREDOC_OP_RE.match(command, i)
            if m and HEREDOC_MARK_RE.match(m.group(2)):  # already cut by an outer parse
                out.append(m.group(0))
                i = m.end()
                continue
            if m:
                raw_tag = m.group(2)
                quoted = raw_tag[0] in "'\"\\"
                tag = raw_tag.strip("'\"").lstrip("\\")
                idx = len(registry)
                registry.append((tag, "", quoted))
                pending.append((tag, m.group(1) == "-", quoted, idx))
                out.append("<<" + m.group(1) + HEREDOC_MARK % idx)
                i = m.end()
                continue
        out.append(c)
        i += 1
    return "".join(out)


def strip_heredocs(command):
    """The command with heredoc bodies removed (they are data, not commands)."""
    return _heredocs(command, [])


def heredoc_bodies(command):
    registry = []
    _heredocs(command, registry)
    return [(tag, body) for tag, body, _ in registry]


# ---------------------------------------------------------------- tokenizer

def _match_close(text, i, close):
    """Index just past the `close` char that ends a `$(`, `${`, `<(` group starting at text[i] (after the opener)."""
    opener = "(" if close == ")" else "{"
    depth = 1
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "$" and text.startswith("$'", i):
            i = _skip_ansi(text, i + 2)
            continue
        if c == "'" and close == ")":
            j = text.find("'", i + 1)
            if j < 0:
                raise ParseError("unterminated single quote")
            i = j + 1
            continue
        if c == "#" and close == ")" and (i == 0 or text[i - 1] in " \t\n;&|("):
            j = text.find("\n", i)
            if j < 0:
                raise ParseError("unterminated ( group")
            i = j
            continue
        if c == '"':
            i = _skip_double(text, i + 1)
            continue
        if c == "`":
            i = _skip_backtick(text, i + 1)
            continue
        if c == opener:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ParseError("unterminated %s group" % opener)


def _skip_double(text, i):
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == '"':
            return i + 1
        if c == "`":
            i = _skip_backtick(text, i + 1)
            continue
        if c == "$" and i + 1 < n and text[i + 1] in "({":
            i = _match_close(text, i + 2, ")" if text[i + 1] == "(" else "}")
            continue
        i += 1
    raise ParseError("unterminated double quote")


def _skip_ansi(text, i):
    """Index just past the `'` closing an ANSI-C `$'…'` string whose body starts at text[i]."""
    n = len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "'":
            return i + 1
        i += 1
    raise ParseError("unterminated $' string")


ANSI_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f",
                "v": "\v", "\\": "\\", "'": "'", '"': '"', "?": "?"}


def _ansi_decode(body):
    """The value of an ANSI-C `$'…'` string: `\\n` is a newline, `\\x41` is `A`, and so on."""
    def sub(m):
        s = m.group(1)
        if s[0] == "x":
            return chr(int(s[1:], 16)) if len(s) > 1 else "x"
        if s[0] in "01234567":
            return chr(int(s, 8) & 0xFF)
        return ANSI_ESCAPES.get(s, "\\" + s)
    return re.sub(r"\\(x[0-9A-Fa-f]{1,2}|[0-7]{1,3}|.)", sub, body, flags=re.S)


def _skip_backtick(text, i):
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "`":
            return i + 1
        i += 1
    raise ParseError("unterminated backtick")


def _subst_body(text, i):
    """For `$(` / `$((` at text[i]: (body or None for arithmetic, index past the group)."""
    end = _match_close(text, i + 2, ")")
    body = text[i + 2:end - 1]
    if body.startswith("(") and body.endswith(")"):  # $(( arithmetic ))
        return None, end
    return body, end


def _read_word(text, i):
    """Read one word starting at text[i]. Returns (Word, next index)."""
    n = len(text)
    start = i
    value, subs = [], []
    while i < n:
        c = text[i]
        if c in "<>" and i + 1 < n and text[i + 1] == "(":  # process substitution <(…) / >(…)
            end = _match_close(text, i + 2, ")")
            subs.append(text[i + 2:end - 1])
            value.append(text[i:end])
            i = end
            continue
        if c in " \t\n;&|()<>":
            break
        if c == "\\":
            if i + 1 < n and text[i + 1] != "\n":
                value.append(text[i + 1])
            i += 2
            continue
        if c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                raise ParseError("unterminated single quote")
            value.append(text[i + 1:j])
            i = j + 1
            continue
        if c == '"':
            end = _skip_double(text, i + 1)
            inner = text[i + 1:end - 1]
            subs.extend(_subs_in(inner))
            value.append(re.sub(r'\\([\\"$`])', r"\1", inner))
            i = end
            continue
        if c == "`":
            end = _skip_backtick(text, i + 1)
            subs.append(text[i + 1:end - 1].replace("\\`", "`"))
            value.append(text[i:end])
            i = end
            continue
        if c == "$" and i + 1 < n and text[i + 1] == "(":
            body, end = _subst_body(text, i)
            if body is not None:
                subs.append(body)
            value.append(text[i:end])
            i = end
            continue
        if c == "$" and i + 1 < n and text[i + 1] == "{":
            end = _match_close(text, i + 2, "}")
            value.append(text[i:end])
            i = end
            continue
        if c == "$" and i + 1 < n and text[i + 1] == "'":
            end = _skip_ansi(text, i + 2)
            value.append(_ansi_decode(text[i + 2:end - 1]))
            i = end
            continue
        value.append(c)
        i += 1
    return Word("".join(value), text[start:i], subs), i


def _subs_in(inner):
    """Command-substitution bodies inside double-quoted (or unquoted-heredoc) text."""
    subs, i, n = [], 0, len(inner)
    while i < n:
        c = inner[i]
        if c == "\\":
            i += 2
            continue
        if c == "`":
            end = _skip_backtick(inner, i + 1)
            subs.append(inner[i + 1:end - 1].replace("\\`", "`"))
            i = end
            continue
        if c == "$" and i + 1 < n and inner[i + 1] == "(":
            body, end = _subst_body(inner, i)
            if body is not None:
                subs.append(body)
            i = end
            continue
        if c == "$" and i + 1 < n and inner[i + 1] == "{":
            i = _match_close(inner, i + 2, "}")
            continue
        i += 1
    return subs


REDIRECT_RE = re.compile(r"(?:[0-9]+|&)?(?:>>|>&|>\||<<<|<<-|<<|<>|<&|>|<)")


def parse(command, registry=None):
    """Split a command string into Simple commands. Operators, newlines and parentheses separate them; each Simple
    records its subshell depth and whether it is part of a pipeline."""
    registry = [] if registry is None else registry
    text = _heredocs(command, registry)
    simples, cur = [], Simple()
    depth = 0
    next_piped = False
    i, n = 0, len(text)

    def flush(piped_after=False, background=False):
        nonlocal cur, next_piped
        if cur:
            cur.piped = piped_after or next_piped
            cur.pipe_out = piped_after
            cur.background = background
            simples.append(cur)
        next_piped = piped_after
        cur = Simple()
        cur.depth = depth

    while i < n:
        c = text[i]
        if c in " \t":
            i += 1
            continue
        if c == "\\" and i + 1 < n and text[i + 1] == "\n":
            i += 2
            continue
        if c == "\n":
            flush()
            i += 1
            continue
        if c == "#" and (i == 0 or text[i - 1] in " \t\n;&|()"):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        m = REDIRECT_RE.match(text, i)
        if m and not (text[i] in "<>" and i + 1 < n and text[i + 1] == "("):
            op = m.group(0)
            i = m.end()
            while i < n and text[i] in " \t":
                i += 1
            if i < n and text[i] not in "\n;&|()":
                target, i = _read_word(text, i)
            else:
                target = Word("")
            cur.redirects.append((op, target))
            continue
        op = next((o for o in OPERATORS if text.startswith(o, i)), None)
        if op:
            if op == "(":
                flush()
                depth += 1
                cur.depth = depth
            elif op == ")":
                flush()
                depth = max(0, depth - 1)
                cur.depth = depth
            else:
                flush(piped_after=op in ("|", "|&"), background=op == "&")
            i += len(op)
            continue
        word, i = _read_word(text, i)
        if not cur:
            cur.depth = depth
        cur.words.append(word)
    flush()
    return simples


# ---------------------------------------------------------------- prefix stripping

RUNNERS = {"uv": "run", "poetry": "run", "pipenv": "run", "pdm": "run", "hatch": "run", "rye": "run",
           "pnpm": "exec", "npm": "exec", "yarn": "exec", "bundle": "exec"}
RUNNER_OPTS_WITH_VALUE = ("--with", "--python", "-p", "--project", "--directory", "--env-file", "--extra", "--group",
                          "--package", "--index", "--with-requirements", "-e", "--env", "-w", "--workspace")

def _skip_opts(argv, i, with_value=()):
    while i < len(argv):
        a = argv[i]
        if a == "--":
            return i + 1
        if not a.startswith("-") or a == "-":
            return i
        name = a.split("=", 1)[0]
        if name in with_value and "=" not in a:
            i += 2
        else:
            i += 1  # a flag, or a value attached: -n5, -uroot
    return i


def strip_prefix(argv):
    """Remove leading assignments, reserved words and wrappers. Returns the argv of the command that runs, or [].
    A wrapper with no command after it (`env`, `sudo -l`) is itself the command: `env` alone prints the environment."""
    i = 0
    wrapper_at = None
    while i < len(argv):
        a = argv[i]
        if ASSIGN_RE.match(a) or a in RESERVED:
            i += 1
            continue
        if a == "function":  # `function name { … }`: the body follows the name
            i += 2
            continue
        prog = os.path.basename(a)
        nxt = argv[i + 1] if i + 1 < len(argv) else ""
        if prog in RUNNERS and nxt == RUNNERS[prog]:  # uv run …, poetry run …, pnpm exec …
            i = _skip_opts(argv, i + 2, RUNNER_OPTS_WITH_VALUE)
            continue
        if prog in ("npx", "bunx", "pnpx"):  # the package named next is the program
            i = _skip_opts(argv, i + 1, ("-p", "--package", "-c", "--call"))
            continue
        if prog in WRAPPERS:
            wrapper_at = i
        if prog == "env":
            j = i + 1
            while j < len(argv) and argv[j].startswith("-") and argv[j] != "--":
                if argv[j] in ("-S", "--split-string") and j + 1 < len(argv):
                    # env -S "cmd args": the string is split into words and run
                    return strip_prefix([Word(x, x) for x in argv[j + 1].split()] + argv[j + 2:])
                if argv[j].startswith("--split-string="):
                    v = argv[j].split("=", 1)[1]
                    return strip_prefix([Word(x, x) for x in v.split()] + argv[j + 1:])
                j += 2 if argv[j] in ("-u", "--unset", "-C", "--chdir") else 1
            i = j + 1 if j < len(argv) and argv[j] == "--" else j
            continue
        if prog in ("command", "builtin"):
            rest = argv[i + 1:]
            if rest and rest[0] in ("-v", "-V"):
                return []  # a lookup, not a run
            i = _skip_opts(argv, i + 1)
            continue
        if prog == "exec":
            i = _skip_opts(argv, i + 1, ("-a",))
            continue
        if prog in ("nohup", "time", "stdbuf"):
            i = _skip_opts(argv, i + 1, ("-o", "-e", "-i", "-f"))
            continue
        if prog == "sudo":
            i = _skip_opts(argv, i + 1, ("-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U", "-T"))
            continue
        if prog == "nice":
            i = _skip_opts(argv, i + 1, ("-n", "--adjustment"))
            continue
        if prog == "timeout":
            i = _skip_opts(argv, i + 1, ("-s", "--signal", "-k", "--kill-after"))
            if i < len(argv):
                i += 1  # the duration
            continue
        if prog == "xargs":
            i = _skip_opts(argv, i + 1, ("-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a", "--delimiter",
                                         "--max-args", "--max-procs", "--max-lines", "--max-chars", "--arg-file",
                                         "--eof", "--replace"))
            continue
        break
    if i >= len(argv) and wrapper_at is not None:
        return argv[wrapper_at:]
    return argv[i:]


# ---------------------------------------------------------------- walking

SHELL_OPTS_WITH_VALUE = {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}


def _shell_mode(args):
    """For a shell's args: ("code", string) for `-c`, ("stdin", None) when it reads its script from stdin, or
    ("file", None) when it runs a script file."""
    k = 0
    while k < len(args):
        a = args[k]
        if a == "--":
            return ("file", None) if k + 1 < len(args) else ("stdin", None)
        if a in SHELL_OPTS_WITH_VALUE:
            k += 2
            continue
        if a.startswith("--"):
            k += 1
            continue
        if a[:1] in "-+" and len(a) > 1:
            if a[0] == "-" and "c" in a[1:]:
                rest = args[k + 1:]
                j = 0
                while j < len(rest):
                    r = rest[j]
                    if r in SHELL_OPTS_WITH_VALUE or (r[:1] in "-+" and len(r) > 2 and r[-1] in "oO"):
                        j += 2
                    elif r[:1] in "-+" and len(r) > 1:
                        j += 1
                    else:
                        return ("code", r)
                return ("code", None)
            if a[-1] in "oO":  # -eo pipefail, -euo pipefail: the cluster's last option takes a value
                k += 2
                continue
            if a[0] == "-" and "s" in a[1:]:
                return ("stdin", None)
            k += 1
            continue
        return ("file", None)
    return ("stdin", None)


def _find_exec_payloads(args):
    out, k = [], 0
    while k < len(args):
        if args[k] in EXEC_FLAGS:
            j = k + 1
            while j < len(args) and args[j] not in (";", "+"):
                j += 1
            if j > k + 1:
                out.append(args[k + 1:j])
            k = j
        k += 1
    return out


def _nested(body, cwd, depth, registry, known=True):
    """Commands in a nested body. A body that doesn't parse is skipped (the shell would refuse it too); the
    commands around it are still checked."""
    if depth > MAX_DEPTH or not body:
        return []
    try:
        return list(_walk(body, {"cwd": cwd, "cwd_known": known, "registry": registry}, depth))
    except ParseError:
        return []


def _stdin_from(simple, registry):
    """Text a simple command writes to a pipe that we can see: echo/printf args, its heredocs and here-strings."""
    texts = []
    argv = strip_prefix(list(simple.words))
    prog = os.path.basename(argv[0]) if argv else ""
    if prog in ("echo", "printf"):
        args = [a for a in argv[1:] if not (a.startswith("-") and len(a) <= 3)]
        if args:
            texts.append(" ".join(args).replace("\\n", "\n"))
    for op, target in simple.redirects:
        m = HEREDOC_MARK_RE.match(str(target)) if op in ("<<", "<<-") else None
        if m and int(m.group(1)) < len(registry):
            texts.append(registry[int(m.group(1))][1])
        elif op.endswith("<<<"):
            texts.append(str(target))
    return texts


def _walk(command, state, depth):
    registry = state.setdefault("registry", [])
    level = []  # (cwd, cwd_known) on entry to each open subshell
    cur_depth = 0
    prev = None
    for simple in parse(command, registry):
        while cur_depth < simple.depth:
            level.append((state["cwd"], state.get("cwd_known", True)))
            cur_depth += 1
        while cur_depth > simple.depth:
            state["cwd"], state["cwd_known"] = level.pop()
            cur_depth -= 1
        for w in simple.words + [t for _, t in simple.redirects]:
            for body in w.subs:
                yield from _nested(body, state["cwd"], depth + 1, registry)
        heredocs = []
        stdin = []
        for op, target in simple.redirects:
            m = HEREDOC_MARK_RE.match(str(target)) if op in ("<<", "<<-") else None
            if m and int(m.group(1)) < len(registry):
                _tag, body, quoted = registry[int(m.group(1))]
                heredocs.append((body, quoted))
                stdin.append(body)
                if not quoted:  # bash expands $(…) and backticks inside an unquoted heredoc
                    try:
                        subs = _subs_in(body)
                    except ParseError:
                        subs = []
                    for sub in subs:
                        yield from _nested(sub, state["cwd"], depth + 1, registry)
            elif op.endswith("<<<"):
                stdin.append(str(target))
        if prev is not None and prev.pipe_out:
            stdin.extend(_stdin_from(prev, registry))
        yield from _dispatch(simple.words, state, depth, simple.redirects, heredocs,
                             simple.piped or simple.background, stdin, pipe_out=simple.pipe_out)
        prev = simple


def _dispatch(words, state, depth, redirects=(), heredocs=(), subshell=False, stdin=(), operands_unknown=False,
              pipe_out=False):
    words = list(words)
    argv = strip_prefix(words)
    if not argv:
        if redirects:  # `done < file`, `> out`: no command, but the redirects still happen
            yield Cmd([], state["cwd"], redirects, heredocs)
        return
    prog = os.path.basename(argv[0])
    known = state.get("cwd_known", True)
    wrappers = words[:max(0, len(words) - len(argv))]
    operands_unknown = operands_unknown or any(os.path.basename(str(w)) == "xargs" for w in wrappers)
    cmd = Cmd(argv, state["cwd"], redirects, heredocs, known, stdin, operands_unknown, pipe_out)
    yield cmd
    args = argv[1:]
    registry = state.get("registry", [])
    if prog in ("cd", "pushd", "popd"):
        if subshell:
            return  # a pipeline part or a background job runs in its own subshell
        target = next((a for a in args if not a.startswith("-") or a == "-"), None)
        if prog == "popd" or target == "-" or (target is not None and (has_expansion(target) or
                                                                          str(target).startswith("~-"))):
            state["cwd_known"] = False  # we can't tell where it goes
        elif target is None:
            state["cwd"] = os.path.expanduser("~")
        else:
            state["cwd"] = os.path.normpath(os.path.join(state["cwd"], os.path.expanduser(target)))
        return
    if depth >= MAX_DEPTH:
        return
    if prog in SHELLS:
        mode, code = _shell_mode(args)
        if mode == "code" and code is not None:
            yield from _nested(code, state["cwd"], depth + 1, registry)
        elif mode == "stdin":
            for text in stdin:
                yield from _nested(text, state["cwd"], depth + 1, registry)
    elif prog == "eval" and args:
        yield from _nested(" ".join(args), state["cwd"], depth + 1, registry)
    elif prog == "find":
        for payload in _find_exec_payloads(args):
            yield from _dispatch(payload, {"cwd": state["cwd"], "cwd_known": known, "registry": registry},
                                 depth + 1, operands_unknown=True)
    elif prog == "git":
        sub, rest, _cwd = git_split(args, state["cwd"])
        if sub == "submodule":
            rest = [a for a in rest if a not in ("-q", "--quiet")]
            if rest and rest[0] == "foreach":
                payload = [a for a in rest[1:] if a not in ("--recursive", "-q", "--quiet")]
                # runs in every submodule's directory, so the cwd is unknown there
                if len(payload) == 1:
                    yield from _nested(str(payload[0]), state["cwd"], depth + 1, registry, known=False)
                elif payload:
                    yield from _dispatch(payload, {"cwd": state["cwd"], "cwd_known": False, "registry": registry},
                                         depth + 1)


def iter_commands(command, cwd, registry=None):
    """Every simple command in `command`, as Cmd objects, in order. Raises ParseError on unbalanced quotes.
    Pass a list as `registry` to get the heredocs back: entry n is (tag, body, quoted) for the marker
    `__kit_heredoc_<n>__` left in the text where that heredoc's `<<TAG` was."""
    return list(_walk(command, {"cwd": cwd, "registry": [] if registry is None else registry}, 0))


# ---------------------------------------------------------------- git

def git_split(args, cwd):
    """(subcommand, its args, cwd after any `-C dir`) for the args after `git`. subcommand is None if absent."""
    i = 0
    while i < len(args):
        a = args[i]
        if not a.startswith("-"):
            return a, list(args[i + 1:]), cwd
        name = a.split("=", 1)[0]
        if name in GIT_OPTS_WITH_VALUE and "=" not in a:
            if name == "-C" and i + 1 < len(args):
                cwd = os.path.normpath(os.path.join(cwd, os.path.expanduser(args[i + 1])))
            i += 2
            continue
        i += 1
    return None, [], cwd


# ---------------------------------------------------------------- inline code

# interpreter -> (letters that introduce code, letters that take a value, letters that mean "not inline code",
#                 long options that introduce code, long options that take a value,
#                 True when a value letter only takes an attached value (perl -Idir, -i.bak),
#                 True when the code may be attached to its letter (python -c'…'; node -e never is))
INTERPRETERS = {
    "python": ("c", "WXQ", "m", (), ("--check-hash-based-pycs",), False, True),
    "node": ("ep", "r", "", ("--eval", "--print"), ("--require", "--import", "--loader", "--experimental-loader",
                                                    "--input-type", "--env-file", "--conditions", "--title"),
             False, False),
    "bun": ("ep", "r", "", ("--eval", "--print"), ("--preload", "--cwd", "--env-file"), False, False),
    "ruby": ("e", "rICFE", "", (), (), False, True),
    "perl": ("eE", "IMmix", "", (), (), True, True),
}


def interpreter_mode(argv):
    """For an interpreter argv: ("code", string) for inline code (`python3 -c`, `node -e`, `perl -e`, `deno eval`),
    ("stdin", None) when it runs whatever arrives on stdin (`python3`, `python3 -`), ("file", None) for a script or
    module, or None when argv isn't a known interpreter."""
    if not argv:
        return None
    prog = os.path.basename(argv[0])
    base = re.sub(r"[0-9.]+$", "", prog) or prog
    if base == "deno":
        return ("code", argv[2]) if len(argv) > 2 and argv[1] == "eval" else ("file", None)
    spec = INTERPRETERS.get(base)
    if not spec:
        return None
    code_letters, value_letters, stop_letters, code_long, value_long, attached_only, code_attached = spec
    args = argv[1:]
    k = 0
    while k < len(args):
        a = args[k]
        if a == "-":
            return ("stdin", None)
        if a == "--":
            return ("file", None) if k + 1 < len(args) else ("stdin", None)
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            if name in code_long:
                return ("code", a.split("=", 1)[1] if "=" in a else (args[k + 1] if k + 1 < len(args) else None))
            k += 2 if name in value_long and "=" not in a else 1
            continue
        if a.startswith("-") and len(a) > 1:
            group = a[1:]
            for idx, ch in enumerate(group):
                if ch in stop_letters:
                    return ("file", None)  # python -m: a module, not inline code
                if ch in code_letters:
                    rest = group[idx + 1:]
                    if rest and code_attached:
                        return ("code", rest)
                    return ("code", args[k + 1] if k + 1 < len(args) else None)
                if ch in value_letters:
                    if idx == len(group) - 1 and not attached_only:
                        k += 1  # the value is the next arg
                    break
            k += 1
            continue
        return ("file", None)  # a script path
    return ("stdin", None)


def inline_code(argv):
    """The code string passed on the command line to an interpreter, or None (a script file isn't scanned)."""
    mode = interpreter_mode(argv)
    return mode[1] if mode and mode[0] == "code" else None


def interpreter_reads_stdin(argv):
    """True for an interpreter run with no inline code and no script file: it runs whatever arrives on stdin."""
    mode = interpreter_mode(argv)
    return bool(mode) and mode[0] == "stdin"


def has_expansion(word):
    """True when the word's source text holds anything the shell would expand (glob, $, backtick, ~, braces)."""
    raw = getattr(word, "raw", word)
    return any(ch in EXPANSION_CHARS for ch in raw)
