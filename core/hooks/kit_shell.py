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

__all__ = ["ParseError", "Cmd", "Word", "parse", "iter_commands", "inline_code", "git_split", "heredoc_bodies",
           "strip_heredocs", "strip_prefix", "has_expansion", "EXEC_FLAGS", "SHELLS", "GIT_OPTS_WITH_VALUE"]

MAX_DEPTH = 4
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
OPERATORS = ("&&", "||", ";;", "|&", ";", "|", "&", "(", ")")
RESERVED = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}"}
ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
HEREDOC_OP_RE = re.compile(r"<<(-?)[ \t]*(\\?[A-Za-z_][A-Za-z0-9_.-]*|'[^'\n]*'|\"[^\"\n]*\")")
HEREDOC_MARK = "__kit_heredoc_%d__"
HEREDOC_MARK_RE = re.compile(r"^__kit_heredoc_(\d+)__$")
EXPANSION_CHARS = set("*?[]$`~{}")
GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env",
                       "--super-prefix", "--list-cmds", "--attr-source"}
EXEC_FLAGS = {"-exec", "-execdir", "-ok", "-okdir"}


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
        self.depth = 0       # subshell depth at this level of text
        self.piped = False   # part of a pipeline (runs in its own subshell)

    def __bool__(self):
        return bool(self.words or self.redirects)


class Cmd:
    """One simple command after prefix stripping: argv (list of Word), the cwd it runs in, its redirects, and the
    bodies of its heredocs as (body, quoted)."""

    def __init__(self, argv, cwd, redirects=(), heredocs=()):
        self.argv = argv
        self.cwd = cwd
        self.redirects = list(redirects)
        self.heredocs = list(heredocs)

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
                    lines.append(line)
                registry[idx] = (tag, "\n".join(lines), quoted)
            pending = []
            continue
        if top == "'":
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
        elif c in "'\"`":
            stack.append(c)
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
        if c == "'" and close == ")":
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

    def flush(piped_after=False):
        nonlocal cur, next_piped
        if cur:
            cur.piped = piped_after or next_piped
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
                flush(piped_after=op in ("|", "|&"))
            i += len(op)
            continue
        word, i = _read_word(text, i)
        if not cur:
            cur.depth = depth
        cur.words.append(word)
    flush()
    return simples


# ---------------------------------------------------------------- prefix stripping

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
                for r in args[k + 1:]:
                    if not (r[:1] in "-+" and len(r) > 1):
                        return ("code", r)
                return ("code", None)
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


def _nested(body, cwd, depth, registry):
    """Commands in a nested body. A body that doesn't parse is skipped (the shell would refuse it too); the
    commands around it are still checked."""
    if depth > MAX_DEPTH or not body:
        return []
    try:
        return list(_walk(body, {"cwd": cwd, "registry": registry}, depth))
    except ParseError:
        return []


def _walk(command, state, depth):
    registry = state.setdefault("registry", [])
    level_cwds = []  # cwd on entry to each open subshell
    cur_depth = 0
    for simple in parse(command, registry):
        while cur_depth < simple.depth:
            level_cwds.append(state["cwd"])
            cur_depth += 1
        while cur_depth > simple.depth:
            state["cwd"] = level_cwds.pop()
            cur_depth -= 1
        for w in simple.words + [t for _, t in simple.redirects]:
            for body in w.subs:
                yield from _nested(body, state["cwd"], depth + 1, registry)
        heredocs = []
        for op, target in simple.redirects:
            m = HEREDOC_MARK_RE.match(str(target)) if op in ("<<", "<<-") else None
            if m and int(m.group(1)) < len(registry):
                _tag, body, quoted = registry[int(m.group(1))]
                heredocs.append((body, quoted))
                if not quoted:  # bash expands $(…) and backticks inside an unquoted heredoc
                    try:
                        subs = _subs_in(body)
                    except ParseError:
                        subs = []
                    for sub in subs:
                        yield from _nested(sub, state["cwd"], depth + 1, registry)
        yield from _dispatch(simple.words, state, depth, simple.redirects, heredocs, simple.piped)


def _dispatch(words, state, depth, redirects=(), heredocs=(), piped=False):
    argv = strip_prefix(list(words))
    if not argv:
        return
    prog = os.path.basename(argv[0])
    cmd = Cmd(argv, state["cwd"], redirects, heredocs)
    yield cmd
    args = argv[1:]
    registry = state.get("registry", [])
    if prog == "cd":
        if piped:
            return  # each part of a pipeline runs in its own subshell
        target = next((a for a in args if not a.startswith("-") or a == "-"), None)
        if target and target != "-":
            state["cwd"] = os.path.normpath(os.path.join(state["cwd"], os.path.expanduser(target)))
        elif target is None:
            state["cwd"] = os.path.expanduser("~")
        return
    if depth >= MAX_DEPTH:
        return
    if prog in SHELLS:
        mode, code = _shell_mode(args)
        if mode == "code" and code is not None:
            yield from _nested(code, state["cwd"], depth + 1, registry)
        elif mode == "stdin":
            for body, _quoted in heredocs:
                yield from _nested(body, state["cwd"], depth + 1, registry)
            for op, target in redirects:
                if op.endswith("<<<"):
                    yield from _nested(str(target), state["cwd"], depth + 1, registry)
    elif prog == "eval" and args:
        yield from _nested(" ".join(args), state["cwd"], depth + 1, registry)
    elif prog == "find":
        for payload in _find_exec_payloads(args):
            yield from _dispatch(payload, {"cwd": state["cwd"], "registry": registry}, depth + 1)


def iter_commands(command, cwd):
    """Every simple command in `command`, as Cmd objects, in order. Raises ParseError on unbalanced quotes."""
    return list(_walk(command, {"cwd": cwd, "registry": []}, 0))


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
#                 True when a value letter only takes an attached value: perl -Idir, -i.bak)
INTERPRETERS = {
    "python": ("c", "WXQ", "m", (), ("--check-hash-based-pycs",), False),
    "node": ("ep", "r", "", ("--eval", "--print"), ("--require", "--import", "--loader", "--experimental-loader",
                                                    "--input-type", "--env-file", "--conditions", "--title"), False),
    "bun": ("e", "r", "", ("--eval", "--print"), ("--preload", "--cwd", "--env-file"), False),
    "ruby": ("e", "rICFE", "", (), (), False),
    "perl": ("eE", "IMmixl0", "", (), (), True),
}


def inline_code(argv):
    """The code string passed on the command line to an interpreter, or None (a script file isn't scanned)."""
    if not argv:
        return None
    prog = os.path.basename(argv[0])
    base = re.sub(r"[0-9.]+$", "", prog) or prog
    if base == "deno":
        return argv[2] if len(argv) > 2 and argv[1] == "eval" else None
    spec = INTERPRETERS.get(base)
    if not spec:
        return None
    code_letters, value_letters, stop_letters, code_long, value_long, attached_only = spec
    args = argv[1:]
    k = 0
    while k < len(args):
        a = args[k]
        if a == "--":
            return None
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            if name in code_long:
                return a.split("=", 1)[1] if "=" in a else (args[k + 1] if k + 1 < len(args) else None)
            if name in value_long and "=" not in a:
                k += 2
                continue
            k += 1
            continue
        if a.startswith("-") and len(a) > 1:
            group = a[1:]
            for idx, ch in enumerate(group):
                if ch in stop_letters:
                    return None
                if ch in code_letters:
                    rest = group[idx + 1:]
                    return rest if rest else (args[k + 1] if k + 1 < len(args) else None)
                if ch in value_letters:
                    if idx == len(group) - 1 and not attached_only:
                        k += 1  # the value is the next arg
                    break
            k += 1
            continue
        return None  # a script path comes first: not inline code
    return None


def has_expansion(word):
    """True when the word's source text holds anything the shell would expand (glob, $, backtick, ~, braces)."""
    raw = getattr(word, "raw", word)
    return any(ch in EXPANSION_CHARS for ch in raw)
