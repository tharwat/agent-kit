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
    A recursive search (`grep -r`, `rg`, `ag`) over a tree that holds a secret file the tool would read (rg and ag
    skip hidden and gitignored files unless told otherwise) is blocked unless the command excludes it by name
    (`--exclude='.env*'`, `-g '!.env*'`) or prints only names (`-l`).
    `source .env` / `. .env` (env files only, not keys) are allowed (owner decision): loading values doesn't print them, and the print checks
    stay. With `set -x` / `set -v` on in the same command it would print them, so that is blocked. (A malformed line
    can still show a fragment in a shell error.)
    Writing a new `.env` with Write is allowed; the content scan below still runs.
(b) Secret-content scan. Blocks new text (Write content, Edit/MultiEdit new_string, NotebookEdit new_source, the
    Bash command) holding a token shape (the token entries of the kit's manifest denylist) or a URL with an inline
    password. A line carrying `agent-kit: allow-secret-shape` is skipped, as are `*.example` / `*.sample` targets.

The message names the shape and line, never the matched text. Blocks with exit 2; fails open (exit 0, one stderr
line) on internal errors. Reads only the project's secret-files list and, for `.npmrc` / `.pypirc`, the file itself
(never echoed). No network, no writes.
"""

import fnmatch
import glob
import json
import os
import re
import subprocess
import sys
import time

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
                 ".claude/notify.env", ".netrc", ".aws/credentials", ".docker/config.json", ".kube/config",
                 ".config/gh/hosts.yml", ".git-credentials", "*.env", ".envrc"]
ENV_FILE_GLOBS = {".env", ".env.*", "*.env", ".envrc"}  # the secret files `source` may load (owner decision)
TOKEN_FILES = {".npmrc", ".pypirc"}  # secret only when they hold a credential
# a credential with a literal value (an `${ENV}` reference is not one)
TOKEN_FILE_RE = re.compile(r"(_authToken|_auth|_password|password)\s*[=:]\s*(?!\$\{|\$[A-Za-z_]|\s*$)\S", re.I | re.M)

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
URL_PASSWORD_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://([^\s/:@'\"]*):([^\s/@'\"]+)@(\[[^\]\s]*\]|[^\s/:'\"?#]*)", re.I)
# ${VAR:-default}, #{ruby}, {{tmpl}} spans can hold `:`; they become `$X` before the URL check
INTERPOLATION_RE = re.compile(r"\$\{[^}]*\}|#\{[^}]*\}|\{\{[^}]*\}\}")
# ${VAR}, $VAR, <placeholder>, ***, the word password, xxx, ..., f-string {var}, {{template}}, %s / %(name)s
PLACEHOLDER_PASSWORD_RE = re.compile(r"^(\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*|<[^>]*>|\*+|password|x+|\.\.\.|"
                                     r"\{\{?[^}]*\}\}?|%(\([A-Za-z_]+\))?s)$", re.I)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "[::1]"}
# well-known local-dev defaults (docker-compose, CI service containers): not secrets wherever the host is
DEV_PASSWORDS = {"postgres", "password", "pass", "root", "example", "changeme", "dev", "development", "test",
                 "testing", "secret", "admin", "guest", "mysql", "redis", "app", "user"}

READERS = {"cat", "less", "more", "head", "tail", "bat", "batcat", "nl", "tac", "grep", "egrep", "fgrep", "rg", "ag",
           "awk", "gawk", "sed", "cut", "sort", "uniq", "diff", "base64", "xxd", "od", "hexdump", "strings", "jq",
           "yq", "openssl", "ssh-keygen"}  # not `source` / `.`: loading a file prints nothing (owner decision)
COPIERS = {"cp", "mv", "scp", "rsync", "install"}
ARCHIVERS = {"tar", "zip", "7z", "gzip", "bzip2", "xz", "zstd"}
DATA_OPTS = {"-d", "--data", "--data-binary", "--data-raw", "--data-urlencode", "--data-ascii", "-F", "--form",
             "--form-string", "--json"}
VALUE_OPTS = {  # options whose value is the next argument, so it isn't read as a file
    "grep": {"-A", "-B", "-C", "-m", "-d", "-D", "--max-count", "--context", "--after-context", "--before-context"},
    "rg": {"-A", "-B", "-C", "-m", "-g", "-t", "-T", "-M", "-j", "--glob", "--type", "--max-count", "--context"},
    "head": {"-n", "-c"}, "tail": {"-n", "-c"}, "cut": {"-d", "-f", "-c", "-b"}, "sort": {"-k", "-t", "-o", "-S", "-T"},
    "jq": {"--arg", "--argjson"}, "openssl": {"-in", "-out", "-passin", "-passout"}, "ssh-keygen": {"-f"},
}
for _p in ("grep", "egrep", "fgrep", "rg", "ag"):  # patterns and exclude/include globs are not files read
    VALUE_OPTS.setdefault(_p, set()).update({"-e", "--regexp", "--exclude", "--exclude-dir", "--include", "--glob",
                                             "-g", "--iglob", "--ignore-file"})
# options that take a value (so the value isn't a copied file), per program
COPY_VALUE_OPTS = {
    "cp": {"-t", "--target-directory", "-S", "--suffix"},
    "mv": {"-t", "--target-directory", "-S", "--suffix"},
    "install": {"-t", "--target-directory", "-S", "--suffix", "-m", "--mode", "-o", "--owner", "-g", "--group"},
    "scp": {"-i", "-F", "-o", "-P", "-l", "-c", "-J", "-S", "-D", "-X"},
    "rsync": {"-e", "--rsh", "--exclude", "--exclude-from", "--include", "--include-from", "--filter", "-f",
              "-T", "--temp-dir", "--partial-dir", "--backup-dir", "--rsync-path", "--chmod", "--chown",
              "--files-from", "--log-file", "-B", "--block-size", "--port", "--password-file"},
    "tar": {"-C", "--directory", "-X", "--exclude-from", "-T", "--files-from", "--exclude", "-f", "--file",
            "-b", "--blocking-factor", "--owner", "--group", "--mode", "-I", "--use-compress-program"},
    "zip": {"-b", "-n", "-t", "-tt", "-O", "--out", "-i", "--include"},
    "7z": set(), "gzip": {"-S", "--suffix"}, "bzip2": set(), "xz": set(), "zstd": {"-o"},
}
PATTERN_FIRST = {"grep", "egrep", "fgrep", "rg", "ag"}  # first positional is the pattern
SCRIPT_FIRST = {"awk", "gawk", "sed", "jq", "yq"}         # first positional is the program
SECRET_PARTS = {"TOKEN", "SECRET", "PASSWORD", "PASSWD", "PASS", "PAT", "CREDENTIAL", "CREDENTIALS", "PWD"}


NOT_SECRET_NAMES = {"PWD", "OLDPWD", "GOOGLE_APPLICATION_CREDENTIALS"}  # a path by convention
NOT_SECRET_SUFFIXES = ("_FILE", "_PATH", "_DIR", "_SOCK", "_ID", "_NAME", "_URL_ENV")
PUBLIC_PARTS = {"PUBLIC", "PUBLISHABLE", "PUB"}


def secret_name(name):
    """GITHUB_TOKEN, API_KEY, DB_PASSWORD, NPM_PAT, AWS_SECRET_ACCESS_KEY: yes. SSH_AUTH_SOCK, KEYBOARD, PWD,
    POSTGRES_PASSWORD_FILE, SSH_KEY_PATH, PUBLIC_KEY, STRIPE_PUBLISHABLE_KEY: no."""
    name = str(name).upper()
    if name in NOT_SECRET_NAMES or not re.match(r"^[A-Z_][A-Z0-9_]*$", name) or name.endswith(NOT_SECRET_SUFFIXES):
        return False
    if set(name.split("_")) & PUBLIC_PARTS:
        return False
    if re.search(r"(^|_)(URL|URI|DSN)$", name) and re.search(
            r"DATABASE|(^|_)DB|REDIS|MONGO|POSTGRES|(^|_)PG|MYSQL|MARIADB|AMQP|RABBIT|CONNECTION|BROKER|CACHE", name):
        return True  # a connection string usually carries the password
    parts = [p for p in name.split("_") if p]
    return any(p in SECRET_PARTS or p.endswith("KEY") or p.endswith("TOKEN") for p in parts[1:] or parts) or \
        any(p in SECRET_PARTS for p in parts)


def expanded_vars(raw):
    """Names of the variables a word's source text expands to their value: `$X`, `${X}`, `${X:-d}`. Skips '$X' in
    single quotes, an escaped `\\$X`, and the presence and length forms `${X:+set}`, `${X+set}`, `${#X}`."""
    out, i, n, quote = [], 0, len(raw), None
    while i < n:
        c = raw[i]
        if quote == "'":
            if c == "'":
                quote = None
            i += 1
            continue
        if c == "\\":
            i += 2
            continue
        if raw.startswith("$(", i):  # a command substitution is its own command, checked on its own
            depth, i = 1, i + 2
            while i < n and depth:
                depth += {"(": 1, ")": -1}.get(raw[i], 0)
                i += 1
            continue
        if c == "'" and quote is None:
            quote = "'"
        elif c == '"':
            quote = None if quote == '"' else '"'
        elif c == "$" and i + 1 < n:
            m = re.match(r"\$\{(#?)([A-Za-z_][A-Za-z0-9_]*)(:?[-+=?]?)", raw[i:]) or \
                re.match(r"\$()([A-Za-z_][A-Za-z0-9_]*)()", raw[i:])
            if m:
                if not m.group(1) and m.group(3) not in (":+", "+"):
                    out.append(m.group(2))
                i += m.end()
                continue
        i += 1
    return out


class Blocked(Exception):
    pass


# ---------------------------------------------------------------- secret files

def project_dir(cwd):
    return os.environ.get("CLAUDE_PROJECT_DIR") or cwd


def project_globs(project):
    """Extra globs from docs/agent/secret-files.md: the first `code` span (or the text) of each `- ` bullet. Bullets
    under a `## Kit defaults` heading only document the built-in list and are skipped."""
    try:
        with open(os.path.join(project, PROJECT_LIST), encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError):
        return []
    out = []
    in_defaults = False
    for line in text.split("\n"):
        if line.startswith("#"):
            in_defaults = bool(re.match(r"^#+\s*kit defaults", line, re.I))
            continue
        if in_defaults:
            continue
        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if not m:
            continue
        item = m.group(1).strip()
        code = re.search(r"`([^`]+)`", item)
        pattern = (code.group(1) if code else item.split()[0] if item else "").strip()
        if pattern and not pattern.startswith("!"):
            out.append(pattern)
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

def scan_text(text, where, check_urls=True):
    if not text:
        return
    for n, line in enumerate(text.split("\n"), 1):
        if ALLOW_MARKER in line:
            continue
        for name, rx in COMPILED:
            if rx.search(line):
                raise Blocked("%s at line %d of %s. Name the env var instead of the value" % (name, n, where))
        if not check_urls:
            continue
        for m in URL_PASSWORD_RE.finditer(INTERPOLATION_RE.sub("$X", line)):
            if not PLACEHOLDER_PASSWORD_RE.match(m.group(2)) and m.group(3).lower() not in LOCAL_HOSTS and \
                    m.group(2).lower() not in DEV_PASSWORDS:
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
            samples = SECRET_SAMPLES + [p.replace("*", "x").replace("?", "x") for p in globs if "/" not in p]
            if any(fnmatch.fnmatchcase(sample, g) for sample in samples):
                return True
            if not set(g) & set("*?[") and secret_reason(g, project, globs):
                return True
    return False


def is_template_target(path):
    return bool(path) and os.path.basename(path).endswith(ENV_TEMPLATES)


# ---------------------------------------------------------------- Bash

def positionals(args, value_opts=(), keep=("-in", "-f")):
    out, k = [], 0
    while k < len(args):
        a = args[k]
        if a == "--":
            out.extend(args[k + 1:])
            break
        if a.startswith("-") and a != "-":
            if a in value_opts and a not in keep:
                k += 1  # skip the option's value (by default -in / -f name the file read: keep it)
        else:
            out.append(a)
        k += 1
    return out


def home_expanded(text):
    """`~/x`, `$HOME/x`, `${HOME}/x` as the shell would expand them; anything else unchanged."""
    text = re.sub(r"^(\$HOME|\$\{HOME\})(?=/|$)", "~", text)
    return os.path.expanduser(text)


def check_operand(word, cwd, project, globs, what):
    """A file operand. A glob (`.env*`) is checked by what it selects and by what it matches on disk."""
    text = home_expanded(str(word))
    if not set(text) & set("*?["):
        check_path(os.path.join(cwd, text), project, globs, what)
    else:
        if glob_targets_secrets(text, project, globs):
            raise Blocked("`%s` selects secret files; agents never %s one" % (text, what))
        for hit in glob.glob(os.path.join(cwd, text))[:200]:
            check_path(hit, project, globs, what)


VALUE_SHORT = {"grep": "ABCmdDef", "egrep": "ABCmdDef", "fgrep": "ABCmdDef", "rg": "ABCEMTdefgjmrt",
               "ag": "ABCGgm"}  # short options that take a value: the rest of the group is that value
# options that print names, counts or nothing (no file content), per program; rg -L is --follow, not this
NAMES_ONLY = {
    "grep": ("lLcq", {"--files-with-matches", "--files-without-match", "--count", "--quiet", "--silent"}),
    "rg": ("lcq", {"--files-with-matches", "--files-without-match", "--count", "--count-matches", "--quiet",
                   "--files"}),
    "ag": ("lLc", {"--files-with-matches", "--files-without-matches", "--count"}),
}
NAMES_ONLY["egrep"] = NAMES_ONLY["fgrep"] = NAMES_ONLY["grep"]
PRUNE_DIRS = {".git", "node_modules", ".venv", "venv", "vendor", "__pycache__"}  # dependencies: their fixtures aren't ours
WALK_LIMIT_FILES = 100000  # past this, or WALK_SECONDS, the walk stops (fail open) so a huge tree never stalls a command
WALK_SECONDS = 1.5


def brace_alternatives(pattern):
    m = re.match(r"^(.*)\{([^}]*)\}(.*)$", pattern)
    return [m.group(1) + alt + m.group(3) for alt in m.group(2).split(",")] if m else [pattern]


def option_values(args, names, braces="unquoted"):
    """Values of long or short options in `names`: `--exclude=x`, `--exclude x`, `-g x`, `-gx`. Braces are expanded
    "always" (rg globs support them) or only when "unquoted" (the shell expands them; grep's own globs don't)."""
    out = []
    for k, a in enumerate(args):
        text = str(a)
        if text == "--":
            break
        for n in names:
            value, word = None, a
            if text == n and k + 1 < len(args):
                value, word = str(args[k + 1]), args[k + 1]
            elif n.startswith("--") and text.startswith(n + "="):
                value = text.split("=", 1)[1]
            elif not n.startswith("--") and text.startswith(n) and len(text) > len(n):
                value = text[len(n):]
            if value is None:
                continue
            raw = getattr(word, "raw", str(word))
            expand = braces == "always" or not set(raw) & set("'\"\\")
            out.extend(brace_alternatives(value) if expand else [value])
    return out


def short_letters(prog, strs):
    """Every letter set in single-dash groups, in order (a list, so `-uu` counts twice)."""
    letters = []
    for a in strs:
        if a == "--":
            break
        if a.startswith("-") and not a.startswith("--") and a != "-":
            for ch in a[1:]:
                letters.append(ch)
                if ch in VALUE_SHORT.get(prog, ""):
                    break
    return letters


def ordered_filters(args, kinds, braces="unquoted", keep_path_includes=False):
    """[(kind, glob), …] in command order, for options mapped to "exclude" / "include" in `kinds`. An rg glob is
    one option for both: `!x` excludes, `x` includes."""
    out = []
    for k, a in enumerate(args):
        text = str(a)
        if text == "--":
            break
        for n, kind in kinds.items():
            if text == n and k + 1 < len(args):
                found = option_values([a, args[k + 1]], [n], braces)
            elif text.startswith(n + "=") or (not n.startswith("--") and text.startswith(n) and len(text) > len(n)):
                found = option_values([a], [n], braces)
            else:
                continue
            for g in found:
                if kind == "rg":
                    out.append(("exclude", g[1:]) if g.startswith("!") else ("include", g))
                else:
                    out.append((kind, g))
            break
    # a glob with a `/` is matched differently by each tool (and never by grep while recursing): it excludes nothing.
    # An rg include glob with a `/` is kept: it can still select a secret file (`-g '**/.env*'`)
    return [(kind, g) for kind, g in out if "/" not in g.rstrip("/") or (keep_path_includes and kind == "include")]


def recursive_search(prog, args):
    """How this grep / rg / ag searches directory trees, as a dict, when it prints matching lines; else None."""
    strs = [str(a) for a in args]
    letters = short_letters(prog, strs)
    short, longs = NAMES_ONLY.get(prog, ("", set()))
    if set(letters) & set(short) or {a.split("=", 1)[0] for a in strs} & longs:
        return None
    if prog in ("grep", "egrep", "fgrep"):
        recursive = set(letters) & {"r", "R"} or set(strs) & {"--recursive", "--dereference-recursive"} or \
            "recurse" in option_values(args, ["--directories", "-d"])
        if not recursive:
            return None
        return {"tool": "grep", "filters": ordered_filters(args, {"--exclude": "exclude", "--include": "include"}),
                "dir_excludes": option_values(args, ["--exclude-dir"]),
                "follow": "R" in letters or "--dereference-recursive" in strs, "hidden": True, "vcs_ignore": False}
    if prog == "rg":
        unrestricted = letters.count("u") + strs.count("--unrestricted")
        return {"tool": "rg", "filters": ordered_filters(args, {"-g": "rg", "--glob": "rg", "--iglob": "rg"}, "always",
                                                         keep_path_includes=True),
                "dir_excludes": [], "follow": "L" in letters or "--follow" in strs,
                "hidden": "--hidden" in strs or "." in letters or unrestricted >= 2,
                "vcs_ignore": not (unrestricted or set(strs) & {"--no-ignore", "--no-ignore-vcs"})}
    if prog == "ag":
        unrestricted = "u" in letters or "--unrestricted" in strs
        # -a / -t search every file: ag skips its ignore rules, --ignore included
        search_all = set(letters) & {"a", "t"} or set(strs) & {"--all-types", "--all-text"}
        return {"tool": "ag", "filters": [] if search_all else ordered_filters(args, {"--ignore": "exclude"}),
                "dir_excludes": [], "follow": "f" in letters or "--follow" in strs,
                "hidden": unrestricted or "--hidden" in strs,
                "vcs_ignore": not (unrestricted or search_all or "U" in letters or "--skip-vcs-ignores" in strs)}
    return None


def glob_matches(g, name, rel):
    if "/" not in g:
        return fnmatch.fnmatchcase(name, g)
    g = g.lstrip("/")
    return fnmatch.fnmatchcase(rel, g) or (g.startswith("**/") and fnmatch.fnmatchcase(name, g[3:]))


def search_state(name, rel, spec):
    """"skip" when the file's globs leave it out, "forced" when an rg include glob selects it (rg then reads it even
    if it's hidden or gitignored), else "default" (the tool's hidden and ignore rules decide)."""
    filters = spec["filters"]
    if not filters:
        return "default"
    matches = [kind for kind, g in filters if glob_matches(g, name, rel)]
    includes = [g for kind, g in filters if kind == "include"]
    if spec["tool"] == "rg":  # rg: the last matching glob wins; with any include glob, unmatched names are skipped
        if matches:
            return "forced" if matches[-1] == "include" else "skip"
        return "skip" if includes else "default"
    # plain reading: any exclude wins; with includes, only included names are searched
    plain = "exclude" in matches or (bool(includes) and "include" not in matches)
    # GNU grep: the last matching option wins; with none matching, the file is skipped only when the first is an include
    gnu = matches[-1] == "exclude" if matches else filters[0][0] == "include"
    return "skip" if plain and gnu else "default"  # BSD and GNU differ: searched if either would search it


def git_ignored(path):
    try:
        out = subprocess.run(["git", "-C", os.path.dirname(path), "check-ignore", "-q", path], capture_output=True,
                             timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def first_secret_in_tree(top, project, globs, spec, budget):
    """The first secret file a recursive search of `top` would read, as (path, glob), or None. `budget` is shared by
    every root of one command; when it runs out the walk stops (fail open)."""
    seen_dirs = set()
    for root, dirs, files in os.walk(top, followlinks=spec["follow"]):
        real = os.path.realpath(root)
        if real in seen_dirs:  # a symlink loop
            dirs[:] = []
            continue
        seen_dirs.add(real)
        dirs[:] = [d for d in dirs if d not in PRUNE_DIRS and (spec["hidden"] or not d.startswith("."))
                   and not any(fnmatch.fnmatchcase(d, g.rstrip("/")) for g in spec["dir_excludes"])]
        for name in files:
            budget["files"] += 1
            if budget["files"] > WALK_LIMIT_FILES or time.monotonic() > budget["deadline"]:
                return None
            full = os.path.join(root, name)
            state = search_state(name, os.path.relpath(full, top).replace(os.sep, "/"), spec)
            if state == "skip" or (state == "default" and not spec["hidden"] and name.startswith(".")):
                continue
            reason = secret_reason(full, project, globs)
            if reason and (state == "forced" or not (spec["vcs_ignore"] and git_ignored(full))):
                return full, reason
    return None


def operand_paths(word, cwd, project):
    """The paths one search operand names: braces and globs expanded, `$PWD` / `$(pwd)` / `$CLAUDE_PROJECT_DIR`
    resolved. Any other expansion: none (the path isn't known)."""
    text = str(word)
    for var, value in (("$(pwd)", cwd), ("${PWD}", cwd), ("$PWD", cwd), ("${CLAUDE_PROJECT_DIR}", project),
                       ("$CLAUDE_PROJECT_DIR", project)):
        text = text.replace(var, value)
    text = home_expanded(text)
    if set(text) & set("$`"):
        return []
    raw = getattr(word, "raw", str(word))
    words = brace_alternatives(text) if not set(raw) & set("'\"\\") else [text]
    out = []
    for w in words:
        if set(w) & set("*?["):  # `grep -r KEY *`: the shell hands grep every match, and grep recurses into them
            out.extend(sorted(glob.glob(os.path.join(cwd, w)))[:200])
        else:
            out.append(os.path.normpath(os.path.join(cwd, w)))
    return out


def check_recursive_search(prog, args, files, cwd, project, globs):
    spec = recursive_search(prog, args)
    if spec is None:
        return
    budget = {"files": 0, "deadline": time.monotonic() + WALK_SECONDS}
    tops = [p for f in (files or ["."]) for p in operand_paths(f, cwd, project)]
    for top in tops:
        if not os.path.isdir(top):
            continue
        hit = first_secret_in_tree(top, project, globs, spec, budget)
        if hit:
            name = os.path.basename(hit[0])
            pattern = ".env*" if name.startswith(".env") else name
            raise Blocked("`%s` searches %s, which holds the secret file %s (%s), and would print its matching "
                          "lines. Exclude it and retry: add `--exclude='%s'` (rg: `-g '!%s'`), or search a "
                          "narrower path. `-l` (file names only) is fine"
                          % (prog, os.path.relpath(top, cwd), os.path.relpath(hit[0], cwd), hit[1], pattern, pattern))


TRACE_OPTS = {"xtrace", "verbose"}


def turns_tracing(args):
    """True / False when `set` turns xtrace or verbose on / off, None when it doesn't touch them."""
    state = None
    for k, a in enumerate(args):
        a = str(a)
        if a in ("-o", "+o") and k + 1 < len(args) and str(args[k + 1]) in TRACE_OPTS:
            state = a == "-o"
        elif re.match(r"^[-+][a-zA-Z]+$", a) and set(a[1:]) & {"x", "v"}:
            state = a[0] == "-"
    return state


def check_bash(command, cwd, project, globs):
    scan_text(command, "the command")  # needs no parsing, so it runs even when the parser gives up
    tracing = False
    for cmd in kit_shell.iter_commands(command, cwd):
        prog, args = cmd.prog, list(cmd.args)
        if prog == "set":
            state = turns_tracing(args)
            tracing = tracing if state is None else state
        operands = args[1:] if args and str(args[0]) == "--" else args
        if prog in ("source", ".") and operands:
            target = operands[0]
            if tracing:
                check_operand(target, cmd.cwd, project, globs, "load with tracing on (`set -x` prints every value)")
            # sourcing is allowed for env files only; a key or token file isn't shell, so bash echoes it in errors
            path = os.path.join(cmd.cwd, home_expanded(str(target)))
            reason = secret_reason(path, project, globs)
            if reason and not any(fnmatch.fnmatchcase(os.path.basename(path), g) for g in ENV_FILE_GLOBS):
                raise Blocked("%s is a secret file (%s) and isn't shell: sourcing it prints its lines in errors"
                              % (os.path.basename(str(target)), reason))
        for op, target in cmd.redirects:
            if op.endswith("<") or op in ("<", "<>"):
                check_operand(target, cmd.cwd, project, globs, "read")
        if prog in ("env", "printenv") and (prog == "env" or not positionals(args)):
            # `env` reaching here has no command after it (kit_shell strips `env … cmd`), so it prints everything
            raise Blocked("`%s` with no command prints every secret in the environment. Print one non-secret "
                          "variable by name, or check that a secret is set with `test -n \"$NAME\"`" % prog)
        if (prog == "set" and not args) or (prog in ("export", "declare", "typeset") and
                                            (not args or set(args) <= {"-p", "-x", "-px", "-xp"})):
            raise Blocked("`%s` with no names prints every variable, secrets included. Check one by name" % prog)
        if prog in ("printenv", "declare", "typeset"):
            for name in positionals(args):
                if secret_name(name):
                    raise Blocked("`%s %s` prints a secret. Check that it's set with `test -n \"$%s\"`"
                                  % (prog, name, name))
        if prog in ("echo", "printf") and not cmd.pipe_out:  # `echo "$T" | docker login --password-stdin` is fine
            for a in args:
                for name in expanded_vars(getattr(a, "raw", str(a))):
                    if secret_name(name):
                        raise Blocked("`%s $%s` prints a secret. Check that it's set with `test -n \"$%s\"`"
                                      % (prog, name, name))
        if prog == "openssl" and args and str(args[0]) in ("x509", "crl", "verify", "s_client"):
            continue  # certificate tools: they read public certificates, not keys
        if prog in READERS:
            opts = VALUE_OPTS.get(prog, ())
            if prog == "ssh-keygen" and not set(args) & {"-y", "-l", "-p", "-e", "-lf", "-yf"}:
                opts = {"-f", "-t", "-b", "-C", "-N", "-a", "-Z"}  # generating a key: -f names the new file
            reading_key = prog != "ssh-keygen" or opts is VALUE_OPTS.get(prog)
            files = positionals(args, opts) if reading_key else positionals(args, opts, keep=())
            if prog in PATTERN_FIRST and not any(a in ("-e", "-f", "--regexp", "--file") or
                                                 a.startswith(("--regexp=", "--file=")) for a in args):
                files = files[1:]
            if prog in SCRIPT_FIRST and not any(a in ("-e", "-f", "--expression", "--file") or
                                                a.startswith(("--expression=", "--file=")) for a in args):
                files = files[1:]
            for f in files:
                check_operand(f, cmd.cwd, project, globs, "read")
            if prog in PATTERN_FIRST:
                check_recursive_search(prog, args, files, cmd.cwd, project, globs)
        elif prog in COPIERS:
            ops = positionals(args, COPY_VALUE_OPTS.get(prog, set()), keep=())
            if any(a in ("-t", "--target-directory") or str(a).startswith("--target-directory=") for a in args):
                sources = ops  # cp -t <dir> <sources…>: every operand is a source
            else:
                sources = ops[:-1]  # the last operand is the destination
            for f in sources:
                check_operand(f, cmd.cwd, project, globs, "copy")
        elif prog in ARCHIVERS:
            ops = list(args)
            if prog == "zip" and ("-x" in ops or "--exclude" in ops):  # zip -x takes every argument after it
                ops = ops[:ops.index("-x" if "-x" in ops else "--exclude")]
            for f in positionals(ops, COPY_VALUE_OPTS.get(prog, set()), keep=()):
                check_operand(f, cmd.cwd, project, globs, "copy")
        elif prog in ("curl", "wget", "http", "https"):
            for k, a in enumerate(args):
                a = str(a)
                data = None
                if a in DATA_OPTS and k + 1 < len(args):
                    data = str(args[k + 1])
                elif "=" in a and a.split("=", 1)[0] in DATA_OPTS:
                    data = a.split("=", 1)[1]
                elif a[:2] in ("-d", "-F") and len(a) > 2:
                    data = a[2:]
                if data and "@" in data:  # -d @file, -F name=@file;type=…
                    path = data.split("@", 1)[1].split(";", 1)[0]
                    if path and path != "-":
                        check_operand(kit_shell.Word(path, path), cmd.cwd, project, globs, "send")
                if a in ("-T", "--upload-file", "--post-file", "--body-file") and k + 1 < len(args):
                    check_operand(args[k + 1], cmd.cwd, project, globs, "send")
                elif a.startswith(("--upload-file=", "--post-file=", "--body-file=")):
                    check_operand(kit_shell.Word(a.split("=", 1)[1]), cmd.cwd, project, globs, "send")
                elif a.startswith("-T") and len(a) > 2:
                    check_operand(kit_shell.Word(a[2:]), cmd.cwd, project, globs, "send")
        elif prog == "git":
            sub, rest, gcwd = kit_shell.git_split(args, cmd.cwd)
            if sub in ("show", "cat-file", "archive", "diff", "log", "blame", "grep"):
                for a in rest:
                    if ":" in str(a) and not str(a).startswith("-"):
                        check_path(str(a).split(":", 1)[1], gcwd, globs, "read")  # HEAD:.env
                if sub == "diff" and "--no-index" in rest:  # compares files on disk: both are read
                    for a in positionals(rest):
                        check_operand(a, gcwd, project, globs, "read")
                prints_content = sub in ("show", "diff", "blame") or (sub == "log" and (
                    set(rest) & {"-p", "-u", "--patch", "-L"} or any(str(a).startswith("-L") for a in rest)))
                if prints_content and "--" in rest:
                    for a in rest[rest.index("--") + 1:]:
                        check_path(os.path.join(gcwd, str(a)), project, globs, "read")


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
        # a template is committed: real tokens are caught there too; only its sample URLs are left alone
        scan_text(ti.get("content") or "", os.path.basename(path) or "the file", not is_template_target(path))
    elif tool in ("Edit", "MultiEdit"):
        path = ti.get("file_path") or ""
        check_path(path, project, globs, "edit")
        texts = [ti.get("new_string") or ""]
        for e in ti.get("edits") or []:
            if isinstance(e, dict):
                texts.append(e.get("new_string") or "")
        for t in texts:
            scan_text(t, os.path.basename(path) or "the file", not is_template_target(path))
    elif tool == "NotebookEdit":
        path = ti.get("notebook_path") or ti.get("file_path") or ""
        check_path(path, project, globs, "edit")
        scan_text(ti.get("new_source") or "", os.path.basename(path) or "the notebook")
    elif tool == "Grep":
        path = ti.get("path") or ""
        if path:
            check_path(path, project, globs, "search")
        pattern = ti.get("glob") or ""
        if pattern and glob_targets_secrets(pattern, project, globs):
            raise Blocked("the glob `%s` selects secret files; agents never read one" % pattern)
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
