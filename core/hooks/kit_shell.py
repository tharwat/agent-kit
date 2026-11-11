#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Shared shell-command parser for the kit's PreToolUse Bash hooks. Standard library only.

The hooks match parsed commands, never raw text, so `git commit -m "drop the rm call"` or
`grep -rn "rm -rf" docs/` are data, not commands. This module turns a Bash tool command string into the simple
commands the shell would run:

  iter_commands(command, cwd)  yields Cmd(argv, cwd, redirects) for every simple command, including those in
                               `$(…)`, backticks, `<(…)`, subshells and control-flow bodies, the code given to
                               `bash -c` / `sh -c` / `eval`, and the command run by `xargs` or `find -exec`.
                               Leading `VAR=value` words and wrappers (`env`, `sudo`, `nice`, `timeout <n>`, …) are
                               stripped. `cd <dir>` updates the tracked cwd for the commands after it.
  inline_code(argv)            the code string of `python[3] -c`, `node -e/--eval/-p`, `ruby -e`, `perl -e/-E`, or None.
  heredoc_bodies(command)      [(tag, body)] for every heredoc in the command.

It is a guardrail parser, not a shell: it doesn't expand variables or globs. Unbalanced quotes raise ParseError, and
the hooks fail open on it (the shell would refuse that command anyway).
"""

import os
import re

__all__ = ["ParseError", "Cmd", "Word", "parse", "iter_commands", "inline_code", "heredoc_bodies",
           "strip_heredocs", "strip_prefix", "has_expansion"]

MAX_DEPTH = 4
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
OPERATORS = ("&&", "||", ";;", "|&", ";", "|", "&", "(", ")")
RESERVED = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}"}
ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
EXPANSION_CHARS = set("*?[]$`~{}")


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

    def __bool__(self):
        return bool(self.words or self.redirects)


class Cmd:
    """One simple command after prefix stripping: argv (list of Word), the cwd it runs in, its redirects."""

    def __init__(self, argv, cwd, redirects=()):
        self.argv = argv
        self.cwd = cwd
        self.redirects = list(redirects)

    @property
    def prog(self):
        return os.path.basename(self.argv[0]) if self.argv else ""

    @property
    def args(self):
        return self.argv[1:]

    def __repr__(self):
        return "Cmd(%r, cwd=%r)" % (list(self.argv), self.cwd)


# ---------------------------------------------------------------- heredocs

def _heredocs(command):
    lines = command.split("\n")
    out, bodies, pending, body = [], [], [], []
    for line in lines:
        if pending:
            tag = pending[0]
            if line.strip() == tag:
                bodies.append((tag, "\n".join(body)))
                body = []
                pending.pop(0)
            else:
                body.append(line)
            continue
        out.append(line)
        pending.extend(m.group(2) for m in HEREDOC_RE.finditer(line))
    if pending and body:  # unterminated: the rest is the body
        bodies.append((pending[0], "\n".join(body)))
    return "\n".join(out), bodies


def strip_heredocs(command):
    """Drop heredoc bodies (they are data, not commands). Keeps the `<<TAG` marker."""
    return _heredocs(command)[0]


def heredoc_bodies(command):
    return _heredocs(command)[1]


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
        if c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                raise ParseError("unterminated single quote")
            i = j + 1
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


def _read_word(text, i):
    """Read one word starting at text[i]. Returns (Word, next index)."""
    n = len(text)
    start = i
    value, subs = [], []
    while i < n:
        c = text[i]
        if c in " \t\n;&|()<>" and not (c in "<>" and i + 1 < n and text[i + 1] == "(" and not value):
            break
        if c in "<>" and i + 1 < n and text[i + 1] == "(":  # process substitution <(…) / >(…)
            end = _match_close(text, i + 2, ")")
            subs.append(text[i + 2:end - 1])
            value.append(text[i:end])
            i = end
            continue
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
        if c == "$" and i + 1 < n and text[i + 1] in "({":
            end = _match_close(text, i + 2, ")" if text[i + 1] == "(" else "}")
            if text[i + 1] == "(":
                body = text[i + 2:end - 1]
                if body.startswith("(") and body.endswith(")"):  # $(( arithmetic ))
                    body = body[1:-1]
                subs.append(body)
            value.append(text[i:end])
            i = end
            continue
        value.append(c)
        i += 1
    return Word("".join(value), text[start:i], subs), i


def _subs_in(inner):
    """Command-substitution bodies inside double-quoted text."""
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
        if c == "$" and i + 1 < n and inner[i + 1] in "({":
            end = _match_close(inner, i + 2, ")" if inner[i + 1] == "(" else "}")
            if inner[i + 1] == "(":
                body = inner[i + 2:end - 1]
                if body.startswith("(") and body.endswith(")"):
                    body = body[1:-1]
                subs.append(body)
            i = end
            continue
        i += 1
    return subs


REDIRECT_RE = re.compile(r"(?:[0-9]+|&)?(?:>>|>&|>\||<<<|<<-|<<|<>|<&|>|<)")


def parse(command):
    """Split a command string into Simple commands (operators, newlines and parentheses separate them)."""
    text, _ = _heredocs(command)
    simples, cur = [], Simple()
    i, n = 0, len(text)

    def flush():
        nonlocal cur
        if cur:
            simples.append(cur)
        cur = Simple()

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
        if c == "#" and not cur.words and not cur.redirects or (c == "#" and text[i - 1] in " \t"):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        m = REDIRECT_RE.match(text, i)
        if m and not (text[i] in "<>" and i + 1 < n and text[i + 1] == "("):
            # digits only count as an fd when the redirect follows at once (`2>`); else they're a word
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
            flush()
            i += len(op)
            continue
        word, i = _read_word(text, i)
        cur.words.append(word)
    flush()
    return simples


# ---------------------------------------------------------------- prefix stripping

def _skip_opts(argv, i, with_value=(), stop_at_first_positional=True):
    while i < len(argv):
        a = argv[i]
        if a == "--":
            return i + 1
        if not a.startswith("-") or a == "-":
            return i
        name = a.split("=", 1)[0]
        if name in with_value and "=" not in a:
            i += 2
        elif len(a) > 2 and not a.startswith("--") and a[:2] in with_value:
            i += 1  # attached value: -n5, -uroot
        else:
            i += 1
    return i


def strip_prefix(argv):
    """Remove leading assignments, reserved words and wrappers. Returns the argv of the command that runs, or []."""
    i = 0
    while i < len(argv):
        a = argv[i]
        if ASSIGN_RE.match(a) or a in RESERVED:
            i += 1
            continue
        prog = os.path.basename(a)
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
    return argv[i:]


# ---------------------------------------------------------------- walking

def _shell_code(args):
    """The code string given to `bash -c` (also -lc, -ec, …), or None."""
    for k, a in enumerate(args):
        if a == "--":
            return None
        if a.startswith("-") and not a.startswith("--") and "c" in a[1:]:
            rest = [x for x in args[k + 1:] if not (x.startswith("-") and len(x) > 1)]
            return rest[0] if rest else None
        if a.startswith("-") or a.startswith("+"):
            continue
        return None  # a script file: not scanned
    return None


EXEC_FLAGS = {"-exec", "-execdir", "-ok", "-okdir"}


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


def _walk(command, state, depth):
    for simple in parse(command):
        for w in simple.words + [t for _, t in simple.redirects]:
            for body in w.subs:
                if depth < MAX_DEPTH:
                    yield from _walk(body, {"cwd": state["cwd"]}, depth + 1)
        yield from _dispatch(simple.words, state, depth, simple.redirects)


def _dispatch(words, state, depth, redirects=()):
    argv = strip_prefix(list(words))
    if not argv:
        return
    prog = os.path.basename(argv[0])
    cmd = Cmd(argv, state["cwd"], redirects)
    yield cmd
    args = argv[1:]
    if prog == "cd":
        target = next((a for a in args if not a.startswith("-") or a == "-"), None)
        if target and target != "-":
            state["cwd"] = os.path.normpath(os.path.join(state["cwd"], os.path.expanduser(target)))
        elif target is None:
            state["cwd"] = os.path.expanduser("~")
        return
    if depth >= MAX_DEPTH:
        return
    if prog in SHELLS:
        code = _shell_code(args)
        if code is not None:
            yield from _walk(code, {"cwd": state["cwd"]}, depth + 1)
    elif prog == "eval" and args:
        yield from _walk(" ".join(args), state, depth + 1)
    elif prog == "find":
        for payload in _find_exec_payloads(args):
            yield from _dispatch(payload, {"cwd": state["cwd"]}, depth + 1)


def iter_commands(command, cwd):
    """Every simple command in `command`, as Cmd objects, in order. Raises ParseError on unbalanced quotes."""
    yield from _walk(command, {"cwd": cwd}, 0)


# ---------------------------------------------------------------- inline code

INLINE_FLAGS = {
    "python": ("-c",), "python3": ("-c",), "python2": ("-c",),
    "node": ("-e", "--eval", "-p", "--print"), "deno": ("eval",), "bun": ("-e", "--eval"),
    "ruby": ("-e",), "perl": ("-e", "-E"),
}


def inline_code(argv):
    """The code string passed on the command line to an interpreter, or None (a script file isn't scanned)."""
    if not argv:
        return None
    prog = os.path.basename(argv[0])
    base = re.sub(r"[0-9.]+$", "", prog) or prog
    flags = INLINE_FLAGS.get(prog) or INLINE_FLAGS.get(base)
    if not flags:
        return None
    for k, a in enumerate(argv[1:], 1):
        name = a.split("=", 1)[0]
        if name in flags:
            if "=" in a and a.startswith("--"):
                return a.split("=", 1)[1]
            return argv[k + 1] if k + 1 < len(argv) else None
        if len(a) > 2 and a[:2] in flags and not a.startswith("--"):
            return a[2:]  # -c'code' written together
        if not a.startswith("-"):
            return None  # a script path comes first: not inline code
    return None


def has_expansion(word):
    """True when the word's source text holds anything the shell would expand (glob, $, backtick, ~, braces)."""
    raw = getattr(word, "raw", word)
    return any(ch in EXPANSION_CHARS for ch in raw)
