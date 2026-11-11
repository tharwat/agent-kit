#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""PreToolUse hook (Read|Edit|Write|MultiEdit|NotebookEdit|Bash|Grep): keep secrets out of the agent's context and
out of what it writes.

(a) Secret-file access. Blocks opening or printing a secret file: `.env` and `.env.*` (not `.example`, `.sample`,
    `.template`, `.dist`), private keys (`*.pem`, `*.key`, `*.p8`, `*.p12`, `*.pfx`, `id_rsa*`, `id_ed25519*`,
    `id_ecdsa*`, not `.pub`), `.claude/notify.env`, `.netrc`, and `.npmrc` / `.pypirc` when they hold a token or
    password. Projects add their own globs in `docs/agent/secret-files.md` (one per bullet); the defaults always
    apply. Bash is checked on the file arguments of readers and copiers and on `< file` redirects, and `env`,
    `printenv`, `set`, `export -p` with no names (they dump every secret) and `printenv <secret-name>` are blocked.
    Writing a new `.env` with Write is allowed; the content scan below still runs.
(b) Secret-content scan. Blocks new text (Write content, Edit/MultiEdit new_string, NotebookEdit new_source, the
    Bash command) holding a token shape (the token entries of the kit's manifest denylist) or a URL with an inline
    password. A line carrying `agent-kit: allow-secret-shape` is skipped, as are `*.example` / `*.sample` targets.

The message names the shape and line, never the matched text. Blocks with exit 2; fails open (exit 0, one stderr
line) on internal errors. Reads only the project's secret-files list and, for `.npmrc` / `.pypirc`, the file itself
(never echoed). No network, no writes.
"""

import fnmatch
import json
import os
import re
import sys

sys.dont_write_bytecode = True  # never leave __pycache__ in .claude/hooks/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import kit_shell
except ImportError:  # a partial install: Bash checks fail open in main()
    kit_shell = None

ALLOW_MARKER = "agent-kit: allow-secret-shape"
PROJECT_LIST = os.path.join("docs", "agent", "secret-files.md")
ENV_TEMPLATES = (".example", ".sample", ".template", ".dist")

# Default secret-file globs. A glob with a `/` matches the project-relative path, else the file name.
DEFAULT_GLOBS = [".env", ".env.*", "*.pem", "*.key", "*.p8", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*", "id_ecdsa*",
                 ".claude/notify.env", ".netrc"]
TOKEN_FILES = {".npmrc", ".pypirc"}  # secret only when they hold a credential
TOKEN_FILE_RE = re.compile(r"_authToken|_auth\s*=|_password|password\s*[=:]", re.I)

# Token shapes, keyed by the manifest denylist `reason`. Kept in step with manifest.json by a kit test.
SHAPES = {
    "Telegram bot token shape": r"\b[0-9]{8,10}:[A-Za-z0-9_-]{35}\b",
    "JWT shape": r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}",
    "API secret key shape": r"\bsk-[A-Za-z0-9_-]{20,}",
    "GitHub token shape": r"\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{20,}",
    "AWS access key shape": r"\bAKIA[0-9A-Z]{16}\b",
    "Slack token shape": r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    "Supabase access token shape": r"\bsbp_[0-9a-f]{40}\b",
    "Render API key shape": r"\brnd_[A-Za-z0-9]{20,}",
    "Atlassian API token shape": r"\bATATT[A-Za-z0-9_=-]{20,}",
    "private key": r"-----BEGIN [A-Z ]*PRIVATE" + r" KEY-----",
}
COMPILED = [(name, re.compile(rx)) for name, rx in SHAPES.items()]
URL_PASSWORD_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://([^\s/:@'\"]+):([^\s/@'\"]+)@", re.I)
PLACEHOLDER_PASSWORD_RE = re.compile(r"^(\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*|<[^>]*>|\*+|password|x+|\.\.\.)$", re.I)

READERS = {"cat", "less", "more", "head", "tail", "bat", "batcat", "nl", "tac", "grep", "egrep", "fgrep", "rg", "ag",
           "awk", "gawk", "sed", "cut", "sort", "uniq", "diff", "base64", "xxd", "od", "hexdump", "strings", "source",
           ".", "jq", "yq", "openssl", "ssh-keygen"}
COPIERS = {"cp", "mv", "scp", "rsync", "install"}
VALUE_OPTS = {  # options whose value is the next argument, so it isn't read as a file
    "grep": {"-A", "-B", "-C", "-m", "-d", "-D", "--max-count", "--context", "--after-context", "--before-context"},
    "rg": {"-A", "-B", "-C", "-m", "-g", "-t", "-T", "-M", "-j", "--glob", "--type", "--max-count", "--context"},
    "head": {"-n", "-c"}, "tail": {"-n", "-c"}, "cut": {"-d", "-f", "-c", "-b"}, "sort": {"-k", "-t", "-o", "-S", "-T"},
    "jq": {"--arg", "--argjson"}, "openssl": {"-in", "-out", "-passin", "-passout"}, "ssh-keygen": {"-f"},
}
PATTERN_FIRST = {"grep", "egrep", "fgrep", "rg", "ag"}  # first positional is the pattern
SCRIPT_FIRST = {"awk", "gawk", "sed", "jq", "yq"}         # first positional is the program
SECRET_NAME_RE = re.compile(r"TOKEN|SECRET|KEY|PASSWORD|PASSWD|PASS$|_PAT$|CREDENTIAL|PRIVATE|AUTH", re.I)


class Blocked(Exception):
    pass


# ---------------------------------------------------------------- secret files

def project_dir(cwd):
    return os.environ.get("CLAUDE_PROJECT_DIR") or cwd


def project_globs(project):
    """Extra globs from docs/agent/secret-files.md: the first `code` span (or the text) of each `- ` bullet."""
    try:
        with open(os.path.join(project, PROJECT_LIST), encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError):
        return []
    out = []
    for line in text.split("\n"):
        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if not m:
            continue
        item = m.group(1).strip()
        code = re.search(r"`([^`]+)`", item)
        glob = (code.group(1) if code else item.split()[0] if item else "").strip()
        if glob and not glob.startswith("!"):
            out.append(glob)
    return out


def secret_reason(path, project, globs):
    """The glob a path matches as a secret file, or None."""
    if not path:
        return None
    full = os.path.normpath(os.path.join(project, os.path.expanduser(path)))
    name = os.path.basename(full)
    try:
        rel = os.path.relpath(full, project).replace(os.sep, "/")
    except ValueError:
        rel = full
    if name.endswith(ENV_TEMPLATES) or name.endswith(".pub"):
        return None
    for g in globs:
        if "/" in g:
            if fnmatch.fnmatchcase(rel, g) or fnmatch.fnmatchcase(full.replace(os.sep, "/"), "*/" + g):
                return g
        elif fnmatch.fnmatchcase(name, g):
            return g
    if name in TOKEN_FILES:
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                if TOKEN_FILE_RE.search(fh.read(65536)):
                    return name + " holding a credential"
        except OSError:
            return None
    return None


def check_path(path, project, globs, what="open"):
    reason = secret_reason(path, project, globs)
    if reason:
        raise Blocked("%s is a secret file (%s); agents never %s one. Ask the owner for the variable *name*, "
                      "and use it by name" % (os.path.basename(path.rstrip("/")) or path, reason, what))


# ---------------------------------------------------------------- content scan

def scan_text(text, where):
    if not text:
        return
    for n, line in enumerate(text.split("\n"), 1):
        if ALLOW_MARKER in line:
            continue
        for name, rx in COMPILED:
            if rx.search(line):
                raise Blocked("%s at line %d of %s. Name the env var instead of the value" % (name, n, where))
        for m in URL_PASSWORD_RE.finditer(line):
            if not PLACEHOLDER_PASSWORD_RE.match(m.group(2)):
                raise Blocked("a URL with an inline password at line %d of %s. Put the password in an env var and "
                              "reference it as ${NAME}" % (n, where))


SECRET_SAMPLES = [".env", ".env.local", ".env.production", "server.pem", "server.key", "id_rsa", "id_ed25519",
                  ".netrc", "AuthKey.p8", "cert.p12"]


def glob_targets_secrets(glob, project, globs):
    """True when a Grep glob singles out secret files (`.env*`, `*.pem`), not when it merely could (`*`)."""
    brace = re.match(r"^(.*)\{([^}]*)\}(.*)$", glob)
    parts = [brace.group(1) + alt + brace.group(3) for alt in brace.group(2).split(",")] if brace else [glob]
    for part in parts:
        for g in re.split(r"[,\s]+", part):
            g = g.split("/")[-1]
            if not g or g.startswith("!") or fnmatch.fnmatchcase("README.md", g) or fnmatch.fnmatchcase("index.ts", g):
                continue
            if any(fnmatch.fnmatchcase(sample, g) for sample in SECRET_SAMPLES) or secret_reason(g, project, globs):
                return True
    return False


def is_template_target(path):
    return bool(path) and os.path.basename(path).endswith((".example", ".sample"))


# ---------------------------------------------------------------- Bash

def positionals(args, value_opts=()):
    out, k = [], 0
    while k < len(args):
        a = args[k]
        if a == "--":
            out.extend(args[k + 1:])
            break
        if a.startswith("-") and a != "-":
            if a in value_opts and a not in ("-in", "-f"):
                k += 1  # skip the option's value (-in / -f name the file itself: keep it)
        else:
            out.append(a)
        k += 1
    return out


def check_bash(command, cwd, project, globs):
    for cmd in kit_shell.iter_commands(command, cwd):
        prog, args = cmd.prog, list(cmd.args)
        for op, target in cmd.redirects:
            if op.endswith("<") or op in ("<", "<>"):
                check_path(os.path.join(cmd.cwd, str(target)), project, globs, "read")
        if prog in ("env", "printenv") and not positionals(args):
            raise Blocked("`%s` with no names prints every secret in the environment. Print one non-secret "
                          "variable by name, or check that a secret is set with `test -n \"$NAME\"`" % prog)
        if prog in ("set", "export", "declare", "typeset") and (not args or set(args) <= {"-p", "-x", "-px"}):
            raise Blocked("`%s` with no names prints every variable, secrets included. Check one by name" % prog)
        if prog == "printenv":
            for name in positionals(args):
                if SECRET_NAME_RE.search(name):
                    raise Blocked("`printenv %s` prints a secret. Check that it's set with `test -n \"$%s\"`"
                                  % (name, name))
        if prog in READERS:
            files = positionals(args, VALUE_OPTS.get(prog, ()))
            if prog in PATTERN_FIRST and not any(a in ("-e", "-f", "--regexp", "--file") or
                                                 a.startswith(("--regexp=", "--file=")) for a in args):
                files = files[1:]
            if prog in SCRIPT_FIRST and not any(a in ("-e", "-f", "--expression", "--file") or
                                                a.startswith(("--expression=", "--file=")) for a in args):
                files = files[1:]
            for f in files:
                check_path(os.path.join(cmd.cwd, str(f)), project, globs, "read")
        elif prog in COPIERS:
            for f in positionals(args)[:-1]:  # the last operand is the destination
                check_path(os.path.join(cmd.cwd, str(f)), project, globs, "copy")
    scan_text(command, "the command")


# ---------------------------------------------------------------- entry point

def check_event(event):
    tool = event.get("tool_name") or ""
    ti = event.get("tool_input") or {}
    cwd = event.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    project = project_dir(cwd)
    globs = DEFAULT_GLOBS + project_globs(project)

    if tool == "Read":
        check_path(ti.get("file_path"), project, globs, "read")
    elif tool == "Write":
        path = ti.get("file_path") or ""
        if path and os.path.exists(os.path.join(project, path)):
            check_path(path, project, globs, "overwrite")
        if not is_template_target(path):
            scan_text(ti.get("content") or "", os.path.basename(path) or "the file")
    elif tool in ("Edit", "MultiEdit"):
        path = ti.get("file_path") or ""
        check_path(path, project, globs, "edit")
        if not is_template_target(path):
            texts = [ti.get("new_string") or ""]
            for e in ti.get("edits") or []:
                if isinstance(e, dict):
                    texts.append(e.get("new_string") or "")
            for t in texts:
                scan_text(t, os.path.basename(path) or "the file")
    elif tool == "NotebookEdit":
        path = ti.get("notebook_path") or ti.get("file_path") or ""
        check_path(path, project, globs, "edit")
        scan_text(ti.get("new_source") or "", os.path.basename(path) or "the notebook")
    elif tool == "Grep":
        path = ti.get("path") or ""
        if path:
            check_path(path, project, globs, "search")
        glob = ti.get("glob") or ""
        if glob and glob_targets_secrets(glob, project, globs):
            raise Blocked("the glob `%s` selects secret files; agents never read one" % glob)
    elif tool == "Bash":
        if kit_shell is None:
            raise ImportError("kit_shell.py is missing")
        command = ti.get("command") or ""
        if command.strip():
            check_bash(command, cwd, project, globs)


def main():
    try:
        event = json.loads(sys.stdin.read())
        check_event(event)
        return 0
    except Blocked as exc:
        sys.stderr.write("Blocked by the secret guard: %s (CLAUDE.kit.md, Forbidden actions).\n" % exc)
        return 2
    except Exception as exc:  # fail open on anything unexpected
        sys.stderr.write("guard-secrets: could not check the tool call (%s); allowing it.\n" % type(exc).__name__)
        return 0


if __name__ == "__main__":
    sys.exit(main())
