#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""PreToolUse Bash hook: block destructive filesystem and git commands.

The settings deny list refuses the plain prefix forms. This hook covers what a prefix rule can't see: options
before the subcommand (`git -C x reset --hard`), combined short flags (`git push -uf`), `+refspec` force pushes,
`git checkout <path>` (a path that exists and isn't a revision), `checkout -B` / `switch -C` / `branch -M` over an existing branch, `find -delete`, and deletes passed as arguments
(`xargs rm`, `find -exec rm`, `bash -c "rm x"`, `bash <<'EOF'`, `python3 -c` / `node -e` code). Commands are parsed (kit_shell.py), never matched as raw text, so `grep "rm -rf" docs/` and
`git commit -m "drop the rm call"` are allowed.

Allowed forms (owner decisions): `git rm --cached`, `git clean -n` / `--dry-run` without `-f`/`-i`,
`git restore --staged` (index only), and `rm` whose every operand sits inside this session's scratch directory or
`<project>/.claude/state/tmp/` (no globs or `$`; symlinks and `..` resolved first; never the scratch root itself).

Each rule's key is the `reason` of a `manifest.json` `checks.destructive_patterns` entry; a kit test keeps them in
step. Blocks with exit 2 and the reason on stderr; fails open (exit 0, one stderr line) on internal errors.
Reads no files, makes no network calls, writes nothing.
"""

import json
import os
import re
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True  # never leave __pycache__ in .claude/hooks/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import kit_shell
except ImportError:  # a partial install: fail open in main()
    kit_shell = None

# reason (manifest destructive_patterns) -> what the hook blocks
RULES = {
    "rm": "rm, and git rm without --cached",
    "rmdir": "rmdir",
    "find -delete": "find -delete",
    "unlink": "unlink",
    "programmatic delete": "file deletes in python -c / node -e / ruby -e / perl -e code",
    "git reset --hard": "git reset --hard",
    "git clean": "git clean, unless -n/--dry-run without -f/-i",
    "git branch -D": "git branch -D / -f / --force; -M / -C, checkout -B, switch -C over an existing branch",
    "force push": "git push --force / -f / --force-with-lease / +refspec",
    "git checkout -- <path> discards changes": "git checkout -- <path>, <path>, <rev> <path>, ., -f/--force, --ours",
    "git stash drop/clear": "git stash drop / clear",
    "git restore": "git restore that touches the working tree (only --staged alone is allowed)",
    "git switch -f": "git switch -f / --force / --discard-changes",
    "git worktree remove --force": "git worktree remove --force / -f",
}

# Delete *calls* in inline or stdin code. A name that is only mentioned (a regex, a string being edited) isn't one.
PROGRAMMATIC_RE = re.compile(
    r"\bos\.(remove|unlink|rmdir|removedirs)\s*\(|\brmtree\s*\(|\.unlink\s*\(|\.rmdir\s*\("
    r"|\b(rmSync|rmdirSync|unlinkSync)\s*\(|\bfs(\.promises)?\.(rm|rmdir|unlink)\s*\(|\bfsPromises\.(rm|unlink)\s*\("
    r"|\bFileUtils\.(rm|rm_r|rm_rf|rm_f|remove|remove_dir|remove_entry)\b|\bFile\.(delete|unlink)\b"
    r"|\bDir\.(delete|rmdir|unlink)\b|\bremove_tree\s*\("
    r"|(?<![\w.$])(unlink|rmdir)\s*(\(|[\"'$@])"  # perl: unlink "a", unlink $f, rmdir(...)
    r"|\b(system|exec\w*|spawn\w*|run|call|check_call|check_output|Popen|popen)\s*\(\s*\[?\s*[\"'`]rm\b"
    r"|`rm\s"  # backtick shell-out (ruby, perl, node template)
)


class Blocked(Exception):
    def __init__(self, reason, argv):
        super().__init__(reason)
        self.reason = reason
        self.argv = argv


# ---------------------------------------------------------------- helpers

def short_flags(args, value_chars=""):
    """Letters set in single-dash flag groups (`-uf` -> {u, f}). A letter in value_chars takes the rest of its group
    (or the next arg) as its value, so `-cfix` is `-c fix`, not `-c -f -i -x`."""
    out = set()
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a == "--":
            break
        if not a.startswith("-") or a.startswith("--") or a == "-":
            continue
        group = a[1:]
        for k, ch in enumerate(group):
            out.add(ch)
            if ch in value_chars:
                if k == len(group) - 1:
                    skip = True
                break
    return out


def long_flags(args):
    out = set()
    for a in args:
        if a == "--":
            break
        if a.startswith("--"):
            out.add(a.split("=", 1)[0])
    return out


def positionals(args, value_opts=()):
    """Non-option args (everything after `--` counts too)."""
    out, k = [], 0
    while k < len(args):
        a = args[k]
        if a == "--":
            out.extend(args[k + 1:])
            break
        if a.startswith("-") and a != "-":
            if a.split("=", 1)[0] in value_opts and "=" not in a:
                k += 1
        else:
            out.append(a)
        k += 1
    return out


def excerpt(argv, limit=80):
    text = " ".join(str(a) for a in argv)
    return text if len(text) <= limit else text[:limit - 1] + "…"


# ---------------------------------------------------------------- scratch-dir exception

def temp_roots():
    roots = {os.path.realpath(tempfile.gettempdir()), os.path.realpath("/tmp")}
    if sys.platform == "darwin":
        roots.add("/private/tmp")
    if os.environ.get("TMPDIR"):
        roots.add(os.path.realpath(os.environ["TMPDIR"]))
    return {r.rstrip(os.sep) for r in roots if r}


def inside(path, root):
    return path.startswith(root.rstrip(os.sep) + os.sep)


def scratch_ok(word, cwd, ctx, cwd_known=True):
    """True when this operand may be removed: a plain path strictly inside an allowed scratch directory."""
    if kit_shell.has_expansion(word) or not str(word):
        return False
    if not cwd_known and not os.path.isabs(str(word)):
        return False  # after `cd -` / `cd "$DIR"` we can't tell where a relative path points
    path = os.path.realpath(os.path.join(cwd, str(word)))
    state_tmp = ctx.get("state_tmp")
    if state_tmp and inside(path, state_tmp):
        return True
    session = ctx.get("session_id")
    if session and re.match(r"^[A-Za-z0-9._-]+$", session):
        marker = os.sep + session + os.sep + "scratchpad"
        idx = path.find(marker + os.sep)
        if idx >= 0:
            root = path[:idx + len(marker)]
            if any(inside(root, t) for t in temp_roots()) and inside(path, root):
                return True
    return False


# ---------------------------------------------------------------- checks

def check_rm(cmd, ctx):
    args = list(cmd.args)
    if long_flags(args) & {"--help", "--version"}:
        return
    operands = positionals(args)
    if not operands:  # `xargs rm` and friends supply the operands
        raise Blocked("rm", cmd.argv)
    if all(scratch_ok(w, cmd.cwd, ctx, cmd.cwd_known) for w in operands):
        return
    raise Blocked("rm", cmd.argv)


FIND_VALUE_PREDICATES = {"-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename", "-regex", "-iregex",
                         "-lname", "-ilname", "-type", "-xtype", "-user", "-group", "-uid", "-gid", "-perm", "-size",
                         "-newer", "-anewer", "-cnewer", "-mtime", "-atime", "-ctime", "-mmin", "-amin", "-cmin",
                         "-maxdepth", "-mindepth", "-printf", "-fprint", "-fprint0", "-fprintf", "-fls", "-inum",
                         "-links", "-samefile", "-used", "-fstype", "-context", "-regextype", "-D", "-O"}


def check_find(cmd):
    args = list(cmd.args)
    k = 0
    while k < len(args):
        a = args[k]
        if a == "-delete":
            raise Blocked("find -delete", cmd.argv)
        if a in kit_shell.EXEC_FLAGS:
            while k < len(args) and args[k] not in (";", "+"):
                k += 1
        elif a in FIND_VALUE_PREDICATES:
            k += 1
        k += 1


def check_git(cmd):
    sub, rest, git_cwd = kit_shell.git_split(list(cmd.args), cmd.cwd)
    if sub is None:
        return
    shorts, longs = short_flags(rest), long_flags(rest)
    argv = cmd.argv

    if sub == "reset":
        if "--hard" in longs:
            raise Blocked("git reset --hard", argv)
    elif sub == "clean":
        dry = "n" in short_flags(rest, "e") or "--dry-run" in longs
        forced = bool(short_flags(rest, "e") & {"f", "i"}) or longs & {"--force", "--interactive"}
        if not dry or forced:
            raise Blocked("git clean", argv)
    elif sub == "branch":
        flags = short_flags(rest, "u")
        force = "f" in flags or "--force" in longs
        # -D (or -d with --force) deletes unmerged work
        if "D" in flags or (force and ("d" in flags or "--delete" in longs)):
            raise Blocked("git branch -D", argv)
        # -M / -C (or -m / -c with --force) rename or copy over the target: blocked only when it already exists
        if flags & {"M", "C"} or (force and (flags & {"m", "c"} or longs & {"--move", "--copy"})):
            pos = positionals(rest, ("-u", "--set-upstream-to"))
            if pos and branch_exists(cmd, git_cwd, pos[-1]):
                raise Blocked("git branch -D", argv)
        elif force:  # -f moves a branch to another commit
            raise Blocked("git branch -D", argv)
    elif sub == "push":
        flags = short_flags(rest, "o")
        if "f" in flags or longs & {"--force", "--force-with-lease"}:
            raise Blocked("force push", argv)
        pos = positionals(rest, kit_shell.PUSH_OPTS_WITH_VALUE)
        if any(p.startswith("+") for p in pos[1:]):
            raise Blocked("force push", argv)
    elif sub == "checkout":
        flags = short_flags(rest, "bBt")
        target = option_value(rest, "B", "bBt")
        if target is not None and branch_exists(cmd, git_cwd, target):  # -B resets an existing branch
            raise Blocked("git branch -D", argv)
        if "f" in flags or "--force" in longs or "--pathspec-from-file" in longs:
            raise Blocked("git checkout -- <path> discards changes", argv)
        if "--" in rest and rest.index("--") < len(rest) - 1:
            raise Blocked("git checkout -- <path> discards changes", argv)
        pos = positionals(rest, ("-b", "-B", "--orphan", "-t", "--track", "--conflict"))
        creating = bool(short_flags(rest, "bB") & {"b", "B"}) or "--orphan" in longs
        if any(p == "." or p.startswith("./") or p.startswith("../") or p == ".." or p.startswith(":/")
               for p in pos):
            raise Blocked("git checkout -- <path> discards changes", argv)
        if len(pos) > 1 and not creating:  # `git checkout <rev> <path>…` overwrites those files
            raise Blocked("git checkout -- <path> discards changes", argv)
        if pos and (longs & {"--ours", "--theirs", "--patch"} or "p" in flags):
            raise Blocked("git checkout -- <path> discards changes", argv)
        if any(set(str(p)) & set("*?[") for p in pos) and not creating:  # a glob pathspec
            raise Blocked("git checkout -- <path> discards changes", argv)
        if cmd.operands_unknown and not creating and "--detach" not in longs:  # `… | xargs git checkout --`
            raise Blocked("git checkout -- <path> discards changes", argv)
        if len(pos) == 1 and not creating and "--detach" not in longs and pos[0] != "-":
            # `git checkout <path>` discards that path's changes; a branch or commit name is fine
            if os.path.exists(os.path.join(git_cwd, pos[0])) and not is_revision(git_cwd, pos[0]):
                raise Blocked("git checkout -- <path> discards changes", argv)
    elif sub == "stash":
        action = next((a for a in rest if not a.startswith("-")), None)
        if action in ("drop", "clear"):
            raise Blocked("git stash drop/clear", argv)
    elif sub == "restore":
        flags = short_flags(rest, "s")
        staged = "S" in flags or "--staged" in longs
        worktree = "W" in flags or "--worktree" in longs
        if worktree or not staged:
            raise Blocked("git restore", argv)
    elif sub == "switch":
        flags = short_flags(rest, "cCt")
        if "f" in flags or longs & {"--force", "--discard-changes"}:
            raise Blocked("git switch -f", argv)
        target = option_value(rest, "C", "cCt", "--force-create")
        if target is not None and branch_exists(cmd, git_cwd, target):  # -C resets an existing branch
            raise Blocked("git branch -D", argv)
    elif sub == "worktree":
        if rest and rest[0] == "remove":
            if "f" in short_flags(rest[1:]) or "--force" in long_flags(rest[1:]):
                raise Blocked("git worktree remove --force", argv)
    elif sub == "rm":
        if "--cached" not in longs:
            raise Blocked("rm", argv)


def option_value(args, letter, value_chars, long_name=None):
    """The value of short option `letter` (`-B x`, `-Bx`, `-qB x`) or of `long_name` (`--force-create x`, `=x`).
    A letter in value_chars takes the rest of its group as its value, so `-bfixB` is `-b fixB`, not `-B`.
    None when the option isn't given; "" when it is given without a value."""
    for k, a in enumerate(args):
        if a == "--":
            break
        if long_name and (a == long_name or a.startswith(long_name + "=")):
            if "=" in a:
                return a.split("=", 1)[1]
            return args[k + 1] if k + 1 < len(args) else ""
        if a.startswith("-") and not a.startswith("--") and a != "-":
            group = a[1:]
            for i, ch in enumerate(group):
                if ch == letter:
                    tail = group[i + 1:]
                    if tail:
                        return tail
                    return args[k + 1] if k + 1 < len(args) else ""
                if ch in value_chars:
                    break
    return None


def branch_exists(cmd, directory, name):
    """True when `name` is an existing local branch, so -B / -C / -M would replace it. When that can't be told (an
    unknown cwd, an expansion in the name, git failing to run), assume it exists: the safe side is to block."""
    if not name:
        return False
    if not cmd.cwd_known or kit_shell.has_expansion(name):
        return True
    try:
        out = subprocess.run(["git", "-C", directory, "show-ref", "--verify", "--quiet", "refs/heads/" + str(name)],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return True
    return out.returncode == 0


def is_revision(directory, name):
    """True when `name` resolves to a commit in the repo at `directory` (a branch, tag or SHA)."""
    try:
        out = subprocess.run(["git", "-C", directory, "rev-parse", "--verify", "--quiet", name + "^{commit}"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def check_command(command, cwd, ctx):
    for cmd in kit_shell.iter_commands(command, cwd):
        prog = cmd.prog
        if prog == "rm":
            check_rm(cmd, ctx)
        elif prog == "rmdir":
            raise Blocked("rmdir", cmd.argv)
        elif prog == "unlink":
            raise Blocked("unlink", cmd.argv)
        elif prog == "find":
            check_find(cmd)
        elif prog == "git":
            check_git(cmd)
        else:
            code = kit_shell.inline_code(cmd.argv)
            if code and PROGRAMMATIC_RE.search(code):
                raise Blocked("programmatic delete", cmd.argv)
            if kit_shell.interpreter_reads_stdin(cmd.argv):  # python3 - <<'EOF' … / echo … | node
                if any(PROGRAMMATIC_RE.search(t) for t in cmd.stdin):
                    raise Blocked("programmatic delete", cmd.argv)


def project_dir(cwd):
    return os.environ.get("CLAUDE_PROJECT_DIR") or cwd


# ---------------------------------------------------------------- entry point

def main():
    try:
        event = json.loads(sys.stdin.read())
        if kit_shell is None:
            raise ImportError("kit_shell.py is missing")
        if event.get("tool_name") != "Bash":
            return 0
        command = (event.get("tool_input") or {}).get("command") or ""
        if not command.strip():
            return 0
        cwd = event.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        ctx = {
            "session_id": event.get("session_id") or "",
            "state_tmp": os.path.realpath(os.path.join(project_dir(cwd), ".claude", "state", "tmp")),
        }
        check_command(command, cwd, ctx)
        return 0
    except Blocked as exc:
        sys.stderr.write(
            "Blocked by the destructive-command guard: %s (%s). agent-kit forbids deleting or discarding. Rename to "
            "<file>.pre-agent-kit, git stash, use a disposable worktree, or list the files for the owner to remove.\n"
            % (exc.reason, excerpt(exc.argv))
        )
        return 2
    except Exception as exc:  # fail open on anything unexpected
        sys.stderr.write("block-destructive: could not check the command (%s); allowing it.\n" % type(exc).__name__)
        return 0


if __name__ == "__main__":
    sys.exit(main())
