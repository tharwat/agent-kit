#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""PreToolUse hook (hardening pack): nothing reaches the main branch before a hardening run passes post-op.

A /hardening run arms `.claude/state/hardening/<ticket>.active` when it branches. While an armed marker exists and
its `.claude/state/hardening/<ticket>.postop-passed` doesn't (or says `restored`), this hook blocks:
  - `git push` to the main branch (a refspec whose destination is it, or --all / --mirror / --branches);
  - `gh pr merge`;
  - writes through the GitHub API, from `gh api`, `curl`, httpie (`http`), `xh` or `wget`: any method other than
    GET/HEAD, except comments, labels, reviews, review requests and issues, which can't move a branch. A REST
    merge, a `/merges` call, a ref update or a contents write is therefore blocked whatever its endpoint;
  - GraphQL mutations, and a GraphQL write whose query can't be read (a variable, an unreadable file, unseen stdin);
  - inline code (`python3 -c`, `node -e`, a script on stdin) that calls the GitHub API with a write, or runs any of
    the above;
  - commands that apply database migrations, and MCP `apply_migration` tools;
  - GitHub MCP tools that merge (`merge_pull_request`), or that write files (`push_files`, `create_or_update_file`,
    `delete_file`) on the main branch or with no branch named.
Commands are read with the core shared parser (`kit_shell.py`), so `bash -c`, `eval`, `$(…)`, heredoc scripts and
`xargs` are seen, and a command that only mentions one of these as text (`grep`, a commit message) is not blocked.
Everything else is allowed. A marker whose first line is `restored` is a finished run and arms nothing.

Known gaps: a script file run by name (`python3 merge.py`), a URL held in a variable, and a `gh` alias.

Its MCP registration runs it as `block-push-before-review.py --mcp-tools`: the argument is ignored, and only makes the
command differ from the Bash one, since the installer merges hooks by command text.

Contract: reads the event JSON on stdin. Exit 2 with the reason on stderr blocks; exit 0 allows. Any internal error
fails open with a one-line stderr note. If `kit_shell.py` is missing or the command doesn't parse, it falls back to
matching the raw command text. It writes nothing and makes no network call. Python 3.9+, stdlib only.
"""

import json
import os
import re
import shlex
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # write nothing into .claude/hooks/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import kit_shell  # installed beside this hook by core
except ImportError:
    kit_shell = None

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
MCP_MERGE_RE = re.compile(r"^mcp__.*merge_pull_request$")
MCP_FILE_WRITE_RE = re.compile(r"^mcp__.*(?:push_files|create_or_update_file|delete_file)$")
GH_MERGE_RE = re.compile(r"\bgh\s+pr\s+merge\b")
GIT_PUSH_TEXT_RE = re.compile(r"\bgit\b[^;&|\n]*\bpush\b")
SEPARATORS = {"&&", "||", ";", "|", "&", "(", ")", "{", "}", "\n"}

READ_METHODS = {"GET", "HEAD", "OPTIONS"}
HTTP_METHODS = READ_METHODS | {"POST", "PUT", "PATCH", "DELETE"}
# REST writes that can't move a branch: comments, labels, reviews, review requests, assignees, issues.
SAFE_WRITE_RE = re.compile(
    r"(?:^|/)(?:issues(?:/[^/]+(?:/(?:comments|labels(?:/[^/]+)?|assignees))?)?"
    r"|issues/comments/[^/]+|pulls/[^/]+/(?:comments(?:/[^/]+/replies)?|reviews(?:/[^/]+(?:/events|/comments)?)?"
    r"|requested_reviewers)|pulls/comments/[^/]+)/?$")
GITHUB_API_URL_RE = re.compile(r"(?:^|//|\b)api\.github\.com(?=/|$)|/api/v3(?=/|$)|/api/graphql\b")
MUTATION_RE = re.compile(r"\bmutation\b")
# Inline code that talks to the GitHub API and writes: block on sight (code isn't parsed further).
CODE_API_RE = re.compile(r"api\.github\.com|/api/v3/|graphql", re.IGNORECASE)
CODE_WRITE_RE = re.compile(r"\b(?:put|post|patch|delete|mutation|merge)\b", re.IGNORECASE)

GH_API_VALUE_LETTERS = set("XHfFqtp")
GH_API_VALUE_LONG = {"--method", "--header", "--raw-field", "--field", "--input", "--jq", "--template", "--hostname",
                     "--preview", "--cache"}
CURL_VALUE_LETTERS = set("dFHXToOuAebcKmrwxEDyYzCUQPt")
CURL_DATA_LONG = ("--data", "--json", "--form")
CURL_VALUE_LONG = {"--request", "--header", "--user", "--user-agent", "--referer", "--cookie", "--cookie-jar",
                   "--output", "--max-time", "--connect-timeout", "--proxy", "--url", "--upload-file", "--config",
                   "--cert", "--key", "--cacert", "--write-out", "--retry", "--resolve", "--interface", "--range",
                   "--oauth2-bearer", "--form-string"}
HTTPIE = {"http", "https", "xh", "xhs"}


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


# ---------------------------------------------------------------- raw-text fallback (no kit_shell, or no parse)

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


def raw_text_action(command, main):
    """The pre-parser check: match the raw text. Broad on purpose; used only when the command can't be parsed."""
    if GH_MERGE_RE.search(command):
        return "gh pr merge"
    if MIGRATION_RE.search(command):
        return "a migration apply command"
    if CODE_API_RE.search(command) and CODE_WRITE_RE.search(command):
        return "a write through the GitHub API (command not parsed)"
    for words in segments(command):
        if git_push_targets_main(words, main):
            return f"git push to {main}"
    return None


# ---------------------------------------------------------------- git push

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


# ---------------------------------------------------------------- GitHub API writes

def read_file(path, cwd):
    """A file's text, or None when it can't be read."""
    try:
        with open(os.path.join(cwd, os.path.expanduser(path)), encoding="utf-8") as fh:
            return fh.read(1 << 20)
    except (OSError, ValueError):
        return None


def expands(word):
    """True when the shell would substitute something in this word: `$NAME`, `${…}`, `$(…)` or a backtick outside
    single quotes. A `$var` inside single quotes (a GraphQL variable) is literal text."""
    raw = getattr(word, "raw", None)
    if raw is None:  # no source text: be strict
        return bool(re.search(r"\$(?:[A-Za-z_{(]|\d)|`", str(word)))
    single = double = False
    i = 0
    while i < len(raw):
        ch = raw[i]
        if single:
            if ch == "'":
                single = False
        elif ch == "\\":
            i += 1
        elif ch == "'" and not double:
            single = True
        elif ch == '"':
            double = not double
        elif ch == "`":
            return True
        elif ch == "$" and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt == "'" and not double:  # $'…' ANSI-C string: literal
                single = True
                i += 1
            elif nxt.isalnum() or nxt in "_{(@*#?!-":
                return True
        i += 1
    return False


def body_text(value, cmd, file_prefix="@", unknown=False):
    """The text a body argument supplies, or None when it can't be known (expanded by the shell, an unreadable file,
    unseen stdin)."""
    if unknown:
        return None
    if file_prefix and value.startswith(file_prefix):
        path = value[len(file_prefix):]
        if path == "-":
            return "\n".join(cmd.stdin) if cmd.stdin else None
        return read_file(path, cmd.cwd)
    return value


def api_write_action(method, endpoint, bodies):
    """The block reason for a GitHub API call, or None. bodies: the request texts (None for one we can't read)."""
    if method in READ_METHODS:
        return None
    path = re.sub(r"[?#].*$", "", endpoint)
    if re.search(r"(?:^|/)graphql/?$", path):
        if not bodies or any(b is None for b in bodies):
            return "a GitHub GraphQL write whose query can't be read"
        if any(MUTATION_RE.search(b) for b in bodies):
            return "a GitHub GraphQL mutation"
        return None
    if SAFE_WRITE_RE.search(path):
        return None
    return f"a write through the GitHub API ({method} {endpoint})"


def short_cluster(arg, value_letters):
    """For a single-dash cluster (`-sX`, `-XPUT`): [(letter, attached value or None)], stopping at a value letter."""
    out = []
    group = arg[1:]
    for idx, ch in enumerate(group):
        if ch in value_letters:
            out.append((ch, group[idx + 1:] or None))
            return out
        out.append((ch, None))
    return out


def gh_api_action(args, cmd):
    """`gh api …` args (after `api`)."""
    method, endpoint, fields, inputs = None, None, [], []
    k = 0
    while k < len(args):
        a = args[k]
        if a == "--":
            if endpoint is None and k + 1 < len(args):
                endpoint = args[k + 1]
            break
        if a.startswith("--"):
            name, eq, val = a.partition("=")
            if name in GH_API_VALUE_LONG:
                if not eq:
                    val = args[k + 1] if k + 1 < len(args) else ""
                    k += 1
                src = a if eq else (args[k] if k < len(args) else a)
                if name == "--method":
                    method = val.upper()
                elif name in ("--raw-field", "--field"):
                    fields.append((name == "--field", val, expands(src)))
                elif name == "--input":
                    inputs.append((val, expands(src)))
            k += 1
            continue
        if a.startswith("-") and len(a) > 1:
            for ch, attached in short_cluster(a, GH_API_VALUE_LETTERS):
                if ch in GH_API_VALUE_LETTERS:
                    val, src = attached, a
                    if val is None:
                        val = args[k + 1] if k + 1 < len(args) else ""
                        src = args[k + 1] if k + 1 < len(args) else a
                        k += 1
                    val = val[1:] if val.startswith("=") else val
                    if ch == "X":
                        method = val.upper()
                    elif ch in "fF":
                        fields.append((ch == "F", val, expands(src)))
            k += 1
            continue
        if endpoint is None:
            endpoint = a
        k += 1
    if endpoint is None:
        return None
    if method is None:
        method = "POST" if fields or inputs else "GET"
    bodies = []
    for typed, val, unknown in fields:
        key, _, v = val.partition("=")
        if key == "query":
            bodies.append(body_text(v, cmd, "@" if typed else "", unknown))
    for path, unknown in inputs:
        bodies.append(body_text("@" + path, cmd, unknown=unknown))
    return api_write_action(method, endpoint, bodies)


def api_endpoint(url):
    """The API path of a GitHub API URL (`repos/o/r/…`, `graphql`), or None for any other URL."""
    m = GITHUB_API_URL_RE.search(url)
    if not m:
        return None
    rest = url[m.end():]
    if "graphql" in m.group(0):
        return "graphql"
    return rest.lstrip("/")


def curl_action(args, cmd):
    method, urls, data, upload, force_get = None, [], [], False, False
    k = 0
    while k < len(args):
        a = args[k]
        if a.startswith("--"):
            name, eq, val = a.partition("=")
            takes = name in CURL_VALUE_LONG or name.startswith(CURL_DATA_LONG)
            if takes and not eq:
                val = args[k + 1] if k + 1 < len(args) else ""
                k += 1
            if name == "--request":
                method = val.upper()
            elif name == "--url":
                urls.append(val)
            elif name == "--upload-file":
                upload = True
            elif name.startswith(CURL_DATA_LONG) or name == "--form-string":
                data.append((val, expands(a if eq or k >= len(args) else args[k])))
            elif name == "--get":
                force_get = True
            k += 1
            continue
        if a.startswith("-") and len(a) > 1:
            for ch, attached in short_cluster(a, CURL_VALUE_LETTERS):
                if ch == "G":
                    force_get = True
                if ch in CURL_VALUE_LETTERS:
                    val, src = attached, a
                    if val is None:
                        val = args[k + 1] if k + 1 < len(args) else ""
                        src = args[k + 1] if k + 1 < len(args) else a
                        k += 1
                    if ch == "X":
                        method = val.upper()
                    elif ch == "T":
                        upload = True
                    elif ch in "dF":
                        data.append((val, expands(src)))
            k += 1
            continue
        urls.append(a)
        k += 1
    if method is None:
        method = "GET" if force_get else "PUT" if upload else "POST" if data else "GET"
    for url in urls:
        endpoint = api_endpoint(url)
        if endpoint is not None:
            return api_write_action(method, endpoint, [body_text(d, cmd, unknown=u) for d, u in data])
    return None


HTTPIE_VALUE_OPTS = {"-a", "--auth", "-A", "--auth-type", "-o", "--output", "--session", "--session-read-only", "-p",
                     "--print", "--verify", "--cert", "--cert-key", "--timeout", "--proxy", "-s", "--style", "--pretty",
                     "--format-options", "--max-redirects", "--max-headers", "--boundary", "--default-scheme",
                     "--bearer", "--ssl"}


def httpie_action(args, cmd):
    pos, k = [], 0
    while k < len(args):
        a = args[k]
        if a.startswith("-"):
            k += 2 if a in HTTPIE_VALUE_OPTS else 1
            continue
        pos.append(a)
        k += 1
    if not pos:
        return None
    method = None
    if pos[0].upper() in HTTP_METHODS:
        method, pos = pos[0].upper(), pos[1:]
    if not pos:
        return None
    url, items = pos[0], pos[1:]
    endpoint = api_endpoint(url if "//" in url else "//" + url)
    if endpoint is None:
        return None
    data = [i for i in items if re.match(r"^[^=:@]+(?::=|=(?!=)|@)", i)]
    if method is None:
        method = "POST" if data else "GET"
    bodies = []
    for item in data:
        m = re.match(r"^([^=:@]+)(:=@|=@|@|:=|=)(.*)$", item, re.S)
        if m and m.group(1) == "query":
            bodies.append(body_text(("@" if "@" in m.group(2) else "") + m.group(3), cmd, "@", expands(item)))
    if endpoint.startswith("graphql") and not bodies and data:
        bodies.append(None)
    return api_write_action(method, endpoint, bodies)


def wget_action(args, cmd):
    method, urls, bodies = None, [], []
    k = 0
    while k < len(args):
        a = args[k]
        name, eq, val = a.partition("=")
        if name in ("--method", "--post-data", "--post-file", "--body-data", "--body-file"):
            if not eq:
                val = args[k + 1] if k + 1 < len(args) else ""
                k += 1
            if name == "--method":
                method = val.upper()
            else:
                method = method or "POST"
                src = a if eq or k >= len(args) else args[k]
                bodies.append(body_text(("@" + val) if name.endswith("-file") else val, cmd,
                                        "@" if name.endswith("-file") else "", expands(src)))
        elif not a.startswith("-"):
            urls.append(a)
        k += 1
    for url in urls:
        endpoint = api_endpoint(url)
        if endpoint is not None:
            return api_write_action(method or "GET", endpoint, bodies)
    return None


# ---------------------------------------------------------------- per command

def code_action(code, main):
    """Inline code or a script fed on stdin: matched as text."""
    if GH_MERGE_RE.search(code):
        return "gh pr merge (in inline code)"
    if MIGRATION_RE.search(code):
        return "a migration apply command (in inline code)"
    if CODE_API_RE.search(code) and CODE_WRITE_RE.search(code):
        return "a write through the GitHub API (in inline code)"
    if GIT_PUSH_TEXT_RE.search(code) and (re.search(r"\b(?:%s|--all|--mirror|--branches)\b" % re.escape(main), code)):
        return f"git push to {main} (in inline code)"
    return None


def command_action(cmd, main):
    argv = list(cmd.argv)  # Words: str values that keep their source text for expands()
    if not argv:
        return None
    prog = os.path.basename(argv[0])
    args = argv[1:]
    if prog == "gh":
        pos = [a for a in args if not a.startswith("-")]
        if pos[:2] == ["pr", "merge"]:
            return "gh pr merge"
        if pos[:1] == ["api"]:
            return gh_api_action(args[args.index("api") + 1:], cmd)
    elif prog == "curl":
        return curl_action(args, cmd)
    elif prog in HTTPIE:
        return httpie_action(args, cmd)
    elif prog == "wget":
        return wget_action(args, cmd)
    elif prog == "git" and git_push_targets_main(argv, main):
        return f"git push to {main}"
    if MIGRATION_RE.search(" ".join(argv)):
        return "a migration apply command"
    code = kit_shell.inline_code(cmd.argv)
    if code is None and kit_shell.interpreter_reads_stdin(cmd.argv) and cmd.stdin:
        code = "\n".join(cmd.stdin)
    if code:
        return code_action(code, main)
    return None


def bash_action(command, cwd, main):
    if kit_shell is None:
        return raw_text_action(command, main)
    try:
        cmds = kit_shell.iter_commands(command, cwd)
    except kit_shell.ParseError:
        return raw_text_action(command, main)
    for cmd in cmds:
        action = command_action(cmd, main)
        if action:
            return action
    return None


def blocked_action(event, main, cwd):
    tool = event.get("tool_name") or ""
    ti = event.get("tool_input") or {}
    if MCP_MIGRATION_RE.match(tool):
        return f"migration apply through {tool}"
    if MCP_MERGE_RE.match(tool):
        return f"a pull request merge through {tool}"
    if MCP_FILE_WRITE_RE.match(tool):
        branch = str(ti.get("branch") or "")
        if not branch or branch in (main, f"refs/heads/{main}"):
            return f"a write to {main} through {tool}" if branch else f"a write through {tool} with no branch named"
        return None
    if tool != "Bash":
        return None
    command = ti.get("command") or ""
    if not command.strip():
        return None
    return bash_action(command, cwd, main)


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
    cwd = event.get("cwd") or str(root)
    action = blocked_action(event, main_branch(root), cwd)
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
