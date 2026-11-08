#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""
Verify the Claude <-> Codex skill LINKS are intact (one source of truth, no copies).

Model: every Claude command lives once, at .claude/commands/<name>.md. Its Codex
skill .agents/skills/<name>/SKILL.md is a short entry point that LINKS to that
file (relative markdown link) instead of copying it. AGENTS.md links Codex to
CLAUDE.md (and CLAUDE.kit.md) and restates only the tagged must-never lines.
Nothing else is duplicated, so nothing can drift; this check guards the links.

Fails (exit 1) when:
  1. a skill named like a Claude command does not link to .claude/commands/<name>.md,
     or links to a .claude/commands/*.md file that does not exist (exact case, so a
     case-insensitive disk can't pass what a case-sensitive CI runner would fail);
  2. a Claude command has no Codex skill (unless listed in .agents/claude-only.txt);
  3. a wrapper skill directory holds anything besides SKILL.md (a copied command
     under any name, or a symlinked directory). A SKILL.md.pre-agent-kit backup left
     by make_skill_links.py is only a warning;
  4. AGENTS.md has no real markdown link to CLAUDE.md (and to CLAUDE.kit.md when that
     file exists), or any relative link in it points at a missing or unreadable file;
  5. any file exists under .agents/rules/ (Codex must read .claude/rules/ directly);
  6. AGENTS.md's restated block (whole-line markers, outside code) is not EXACTLY the
     lines tagged <!-- codex-restate --> in CLAUDE.kit.md, then CLAUDE.md, in order;
     every tagged line must fit on one line. In CLAUDE.kit.md only (the kit's file),
     the "Forbidden actions" heading must exist and every list item under it must be
     tagged and fit on one line. A project's own CLAUDE.md is checked only for its
     tagged lines being restated: its untagged rules are its own business;
  7. a command or skill file is a symlink;
  8. a command, skill, CLAUDE.md, CLAUDE.kit.md, AGENTS.md, rule, lock or allowlist
     file cannot be read as UTF-8;
  9. the always-loaded instructions (CLAUDE.md + CLAUDE.kit.md + every .claude/rules
     file without `paths:` frontmatter) exceed the word budget (default 3,500: the
     kit's own text keeps to 2,500, leaving room for the project's rules);
 10. skills-lock.json exists and a locked skill's folder is missing, or its content
     hash no longer matches a 64-hex sha256 `computedHash`. Other hash formats are
     reported as unverifiable (a warning), not as failures;
 11. AGENTS.md's rule table (the rows inside its agent-kit:rules markers, else every
     table row naming a .claude/rules file) leaves out a .claude/rules/*.md file, so
     Codex would never read that rule. An AGENTS.md with no rule table at all is a
     warning.

"Link", "heading" and "list item" follow CommonMark: text in fenced code (closed or
not), indented code, inline code spans, HTML comments and YAML frontmatter is never
a link, heading or rule. Inline and reference links both count; a link needs a
visible label. Skills with no same-name Claude command (native Codex skills) are
ignored, except by the skills-lock.json check.

Run from anywhere inside the repo:
    python3 .github/scripts/check_skill_links.py [--require-restated] [--word-budget N] [--repo PATH]
Tests:
    python3 .github/scripts/test_check_skill_links.py
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

CMD_DIR = ".claude/commands"
SKILL_DIR = ".agents/skills"
ALLOW_FILE = ".agents/claude-only.txt"  # one command name per line; '#' comments allowed
RULES_COPY_DIR = ".agents/rules"
RULES_DIR = ".claude/rules"
LOCK_FILE = "skills-lock.json"
RESTATE_TAG = "<!-- codex-restate -->"  # ends a line that AGENTS.md must restate
RESTATED_START = "<!-- codex-restate:start -->"
RESTATED_END = "<!-- codex-restate:end -->"
RESTATE_SOURCES = ("CLAUDE.kit.md", "CLAUDE.md")  # tagged lines are read in this order
FORBIDDEN_HEADING = "Forbidden actions"  # every list item under this heading must be tagged...
FORBIDDEN_SOURCE = "CLAUDE.kit.md"  # ...in this file only; a project's own CLAUDE.md is not held to it
BACKUP_SUFFIX = ".pre-agent-kit"
DEFAULT_WORD_BUDGET = 3500  # installed projects; the kit tests hold the kit's own text to 2,500
RULES_START = "<!-- agent-kit:rules:start -->"
RULES_END = "<!-- agent-kit:rules:end -->"
RULE_REF_RE = re.compile(r"\.claude/rules/([A-Za-z0-9._-]+\.md)\b")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

# ---------------------------------------------------------------------------
# Minimal CommonMark scanner — just enough to know what a reader sees as prose,
# links, headings and list items. Standard library only.
# ---------------------------------------------------------------------------
FENCE_OPEN_RE = re.compile(r"^( {0,3})(`{3,})([^`]*)$|^( {0,3})(~{3,})(.*)$")
ATX_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
SETEXT_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
LIST_ITEM_RE = re.compile(r"^([ \t]*)(?:[-*+]|\d{1,9}[.)])(?:[ \t]+|$)")
THEMATIC_RE = re.compile(r"^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$")
REF_DEF_RE = re.compile(r"^ {0,3}\[((?:[^\[\]\\]|\\.)+)\]:[ \t]*(?:<([^<>\n]*)>|(\S+))")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def _indent(line):
    n = 0
    for ch in line:
        if ch == " ":
            n += 1
        elif ch == "\t":
            n += 4 - n % 4
        else:
            break
    return n


def _is_full_ref_def(line):
    """A single-line link reference definition: [label]: dest ["title"] and nothing else."""
    m = REF_DEF_RE.match(line)
    if not m:
        return False
    rest = line[m.end():].strip()
    return rest == "" or re.fullmatch(r'"[^"]*"|\'[^\']*\'|\([^)]*\)', rest) is not None


def scan(text):
    """Line-by-line CommonMark block scan. Returns one dict per line:
    kind   — 'code' (frontmatter, fenced or indented code), 'html' (comment block),
             'prose' or 'blank';
    item   — the line starts a list item;
    head   — (level, title) if the line is an ATX heading or the text of a setext heading,
             (0, '') for a setext underline, else None;
    pstart — the line starts a paragraph (where a link reference definition may appear).
    Indentation is measured relative to the enclosing list item's content column."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    rows = [dict(line=l, kind="prose", item=False, head=None, pstart=False, refdef=False, hcont=False)
            for l in lines]
    i = 0
    if lines and lines[0].strip() == "---":
        for j in range(1, len(lines)):
            if lines[j].strip() in ("---", "..."):
                for k in range(j + 1):
                    rows[k]["kind"] = "code"
                i = j + 1
                break
    fence = None        # (char, length, base) inside a fenced block
    in_comment = False
    prev = "blank"      # blank | prose | icode | block (heading / thematic break / closed fence / comment)
    stack = []          # content columns of the open list items, innermost last
    while i < len(lines):
        r, line = rows[i], lines[i]
        i += 1
        ind = _indent(line)
        if fence and fence[2] > 0 and line.strip() and ind < fence[2]:
            fence, prev = None, "block"  # the list item holding the fence ended
            while stack and ind < stack[-1]:
                stack.pop()
        if fence:
            ch, n, fbase = fence
            r["kind"] = "code"
            if ind - fbase <= 3 and re.match(re.escape(ch) + "{" + str(n) + r",}[ \t]*$", line.lstrip()):
                fence, prev = None, "block"
            continue
        if in_comment:
            r["kind"] = "html"
            if "-->" in line:
                in_comment, prev = False, "block"
            continue
        if not line.strip():
            r["kind"] = "blank"
            prev = "icode" if prev == "icode" else "blank"
            continue
        # Leaving list items: at a lower indent, anything but lazy paragraph continuation closes them.
        was_in_list, closed_list_now = bool(stack), False
        if stack and ind < stack[-1]:
            b0 = line.lstrip()
            rel0 = ind - next((c for c in reversed(stack) if ind >= c), 0)
            block_start = rel0 <= 3 and (b0.startswith("<!--") or FENCE_OPEN_RE.match(b0) is not None
                                         or (b0.startswith("#") and ATX_RE.match(b0) is not None)
                                         or THEMATIC_RE.match(b0) is not None
                                         or LIST_ITEM_RE.match(line) is not None)
            if prev != "prose" or block_start:
                while stack and ind < stack[-1]:
                    stack.pop()
                    closed_list_now = True
        lazy = bool(stack) and ind < stack[-1]
        base = stack[-1] if (stack and ind >= stack[-1]) else 0
        rel = ind - base
        body = line.lstrip()
        if rel >= 4 and prev in ("blank", "icode", "block"):
            r["kind"], prev = "code", "icode"
            continue
        if rel <= 3 and body.startswith("<!--"):
            r["kind"] = "html"
            in_comment = "-->" not in body[4:]
            prev = "prose" if in_comment else "block"
            continue
        m = FENCE_OPEN_RE.match(" " * min(rel, 3) + body) if rel <= 3 else None
        if m:
            run = m.group(2) or m.group(5)
            fence, r["kind"] = (run[0], len(run), base), "code"
            continue
        if rel <= 3 and THEMATIC_RE.match(body) and not (prev == "prose" and SETEXT_RE.match(body)
                                                          and not closed_list_now and not lazy):
            prev = "block"
            continue
        im = LIST_ITEM_RE.match(line) if rel <= 3 else None
        if im:
            marker = body.split()[0] if body.split() else body
            empty = not body[len(marker):].strip()
            interrupts = prev == "prose" and not was_in_list
            if interrupts and (empty or (marker[0].isdigit() and not marker.startswith("1"))):
                im = None  # this cannot interrupt a paragraph: it is continuation text
        if im:
            r["item"] = True
            after = line[len(im.group(0)):]
            spaces = _indent(im.group(0)) - _indent(line[:len(im.group(0)) - len(im.group(0).lstrip())]) - len(marker)
            content = ind + len(marker) + (1 if (not after.strip() or spaces > 4) else max(1, spaces))
            stack.append(content)
            r["pstart"], prev = True, "prose"
            continue
        h = ATX_RE.match(body) if rel <= 3 else None
        if h and (body.startswith("#") and (len(body) == len(h.group(1)) or body[len(h.group(1))] in " \t")):
            r["head"], prev = (len(h.group(1)), (h.group(2) or "").strip()), "block"
            continue
        if rel <= 3 and SETEXT_RE.match(body) and prev == "prose" and not closed_list_now and not lazy:
            j = i - 2  # the paragraph line above
            if not rows[j]["item"] and rows[j]["head"] is None:
                k = j
                while k > 0 and not rows[k]["pstart"] and rows[k - 1]["kind"] == "prose" \
                        and not rows[k - 1]["item"] and rows[k - 1]["head"] is None:
                    k -= 1
                title = "\n".join(lines[x].strip() for x in range(k, j + 1))
                rows[k]["head"] = (1 if body[0] == "=" else 2, title)
                for x in range(k + 1, j + 1):
                    rows[x]["hcont"] = True
                r["head"], prev = (0, ""), "block"
                continue
        r["pstart"] = prev != "prose" or bool(rows[i - 2]["refdef"])
        r["refdef"] = bool(r["pstart"] and REF_DEF_RE.match(line) and _is_full_ref_def(line))
        prev = "block" if r["refdef"] else "prose"
    return rows


def classify(text):
    """[(line, kind)] — see scan()."""
    return [(r["line"], r["kind"]) for r in scan(text)]


def strip_code_spans(para):
    """Replace CommonMark inline code spans with a neutral placeholder."""
    res, i, n = [], 0, len(para)
    while i < n:
        c = para[i]
        if c == "\\" and i + 1 < n:
            res.append(para[i:i + 2])
            i += 2
            continue
        if c == "`":
            j = i
            while j < n and para[j] == "`":
                j += 1
            run, k, close = j - i, j, -1
            while k < n:
                if para[k] == "`":
                    m = k
                    while m < n and para[m] == "`":
                        m += 1
                    if m - k == run:
                        close = k
                        break
                    k = m
                else:
                    k += 1
            if close >= 0:
                res.append("code")
                i = close + run
            else:
                res.append(para[i:j])  # unmatched run is literal backticks
                i = j
            continue
        res.append(c)
        i += 1
    return "".join(res)


def prose_paragraphs(text, rows=None):
    """Prose blocks (paragraph, list-item text, heading), code and HTML comment blocks
    removed; inline code spans never cross a block boundary."""
    rows = rows if rows is not None else scan(text)
    blocks, cur = [], []
    for r in rows:
        starts = r["pstart"] or r["item"] or (r["head"] is not None and r["head"][0] != 0)
        if r["kind"] != "prose" or starts:
            if cur:
                blocks.append(cur)
            cur = []
        if r["kind"] == "prose" and r["head"] != (0, "") and not r["refdef"]:
            cur.append(r["line"])
    if cur:
        blocks.append(cur)
    return [strip_code_spans(COMMENT_RE.sub("", "\n".join(b))) for b in blocks]


def _link_dest(s, i):
    """Parse a link destination (+ optional title) after '('. Returns (dest, end) or None."""
    n = len(s)
    while i < n and s[i] in " \t\n":
        i += 1
    if i < n and s[i] == "<":
        j = s.find(">", i + 1)
        if j < 0 or "\n" in s[i:j]:
            return None
        dest, i = s[i + 1:j], j + 1
    else:
        depth, j = 0, i
        while j < n and s[j] not in " \t\n":
            if s[j] == "\\" and j + 1 < n:
                j += 2
                continue
            if s[j] == "(":
                depth += 1
            elif s[j] == ")":
                if depth == 0:
                    break
                depth -= 1
            j += 1
        dest, i = s[i:j], j
    while i < n and s[i] in " \t\n":
        i += 1
    if i < n and s[i] in "\"'(":
        close = {"\"": "\"", "'": "'", "(": ")"}[s[i]]
        j = i + 1
        while j < n and s[j] != close:
            j += 2 if s[j] == "\\" else 1
        if j >= n:
            return None
        i = j + 1
        while i < n and s[i] in " \t\n":
            i += 1
    if i < n and s[i] == ")":
        return dest, i + 1
    return None


def md_links(text):
    """Targets of real links (inline and reference) with a visible label, in prose only."""
    rows = scan(text)
    paras = prose_paragraphs(text, rows)
    defs = {}
    for r in rows:
        if r["kind"] == "prose" and r["refdef"]:
            m = REF_DEF_RE.match(r["line"])
            if m:
                key = " ".join(m.group(1).lower().split())
                defs.setdefault(key, m.group(2) if m.group(2) is not None else m.group(3))
    targets = []
    for body in paras:
        # CommonMark bracket algorithm: each ']' pairs with the NEAREST open '['; a
        # successful link deactivates earlier '[' openers (no links inside links).
        openers = []  # [position, is_image, active]
        i, n = 0, len(body)
        while i < n:
            c = body[i]
            if c == "\\":
                i += 2
                continue
            if c == "[":
                openers.append([i, i > 0 and body[i - 1] == "!" and not (i > 1 and body[i - 2] == "\\"), True])
                i += 1
                continue
            if c != "]" or not openers:
                i += 1
                continue
            start, is_image, active = openers.pop()
            if not active:
                i += 1
                continue
            label, j, dest, end = body[start + 1:i], i + 1, None, None
            if j < n and body[j] == "(":
                parsed = _link_dest(body, j + 1)
                if parsed:
                    dest, end = parsed
            if dest is None:
                ref, end2 = label, j
                if j < n and body[j] == "[":
                    k = body.find("]", j + 1)
                    if k >= 0:
                        ref, end2 = body[j + 1:k] or label, k + 1
                key = " ".join(ref.lower().split())
                if key in defs:
                    dest, end = defs[key], end2
            if dest is None:
                i += 1
                continue
            if not is_image:
                if label.strip():
                    targets.append(dest)
                for o in openers:
                    if not o[1]:
                        o[2] = False
            i = end
    return targets


def headings(text):
    """{line_index: (level, title)} for ATX and setext headings (level 0 = setext underline)."""
    return {i: r["head"] for i, r in enumerate(scan(text)) if r["head"] is not None}



# ---------------------------------------------------------------------------
# Word budget: what Claude loads into every session.
# ---------------------------------------------------------------------------
PATHS_KEY_RE = re.compile(r"(?m)^paths[ \t]*:")


def split_frontmatter(text):
    """(frontmatter, body). Frontmatter is a leading '---' block closed by '---' or '...'."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[0].strip() == "---":
        for j in range(1, len(lines)):
            if lines[j].strip() in ("---", "..."):
                return "\n".join(lines[:j + 1]), "\n".join(lines[j + 1:])
    return "", text


def count_words(text):
    """Words after frontmatter and HTML comments are removed. A word is a whitespace-separated
    token holding at least one letter or digit, so table pipes and list markers don't count."""
    _fm, body = split_frontmatter(text)
    body = COMMENT_RE.sub(" ", body)
    return sum(1 for tok in body.split() if re.search(r"\w", tok))


# ---------------------------------------------------------------------------
# skills-lock.json: content hash of a native skill folder.
# The lock's 64-hex computedHash is sha256 over each file, in path order, of its
# '/'-separated relative path followed by its bytes; .git and node_modules are
# skipped, and symlinks are not followed. The tool that writes the lock sorts paths
# with JavaScript's localeCompare, which _collation_key approximates; plain code-point
# order is tried too, and a stray .DS_Store is tolerated.
# ---------------------------------------------------------------------------
_PUNCT_ORDER = "_-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$"


def _collation_key(s):
    primary, tertiary = [], []
    for ch in s:
        lo = ch.lower()
        if ch.isspace():
            primary.append((0, ord(ch)))
        elif ch in _PUNCT_ORDER:
            primary.append((1, _PUNCT_ORDER.index(ch)))
        elif ch.isdigit():
            primary.append((3, ord(ch)))
        elif lo.isalpha() and ord(lo) < 128:
            primary.append((4, ord(lo)))
        else:
            primary.append((5, ord(lo)))
        tertiary.append(0 if ch == lo else 1)  # lower case sorts first on a tie
    return primary, tertiary


def _skill_files(path):
    out = []
    for dirpath, dirs, files in os.walk(path):
        dirs[:] = sorted(d for d in dirs if d not in (".git", "node_modules")
                         and not os.path.islink(os.path.join(dirpath, d)))
        for f in files:
            p = os.path.join(dirpath, f)
            if os.path.islink(p) or not os.path.isfile(p):
                continue
            with open(p, "rb") as fh:
                out.append((os.path.relpath(p, path).replace(os.sep, "/"), fh.read()))
    return out


def skill_hashes(path):
    """Every hash the folder could legitimately have under the orderings above."""
    files = _skill_files(path)
    no_ds = [f for f in files if f[0].rsplit("/", 1)[-1] != ".DS_Store"]
    found = set()
    for fs in (files, no_ds):
        for key in (lambda f: _collation_key(f[0]), lambda f: f[0]):
            h = hashlib.sha256()
            for rel, data in sorted(fs, key=key):
                h.update(rel.encode("utf-8"))
                h.update(data)
            found.add(h.hexdigest())
    return found


# ---------------------------------------------------------------------------
def parse_args(argv):
    p = argparse.ArgumentParser(description="Check that Claude commands and Codex skills stay linked, not copied.")
    p.add_argument("--require-restated", action="store_true",
                   help="fail when AGENTS.md has no restated block, or an empty one")
    p.add_argument("--word-budget", type=int, default=DEFAULT_WORD_BUDGET, metavar="N",
                   help=f"max words always loaded into a Claude session (default {DEFAULT_WORD_BUDGET})")
    p.add_argument("--repo", metavar="PATH", help="repository root (default: the git top level of the cwd)")
    args = p.parse_args(argv)
    if args.word_budget < 1:
        p.error("--word-budget must be a positive integer")
    return args


def main(argv):
    args = parse_args(argv)
    if args.repo:
        if not os.path.isdir(args.repo):
            print(f"❌ --repo {args.repo}: not a directory")
            return 1
        os.chdir(args.repo)
    else:
        try:
            r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        except OSError:
            r = None
        if r is None or r.returncode != 0:
            print("❌ not inside a git work tree — run this from within the repository, or pass --repo")
            return 1
        os.chdir(r.stdout.strip())
    require_restated = args.require_restated
    errors, warnings = [], []
    cache = {}

    def read(path):
        if path not in cache:
            try:
                with open(path, encoding="utf-8") as f:
                    cache[path] = f.read()
            except (OSError, UnicodeDecodeError) as e:
                errors.append(f"{path}: cannot be read as UTF-8 text ({e.__class__.__name__})")
                cache[path] = ""
        return cache[path]

    def exists_exact(path):
        cur = "."
        for part in os.path.normpath(path).split(os.sep):
            if part in ("", "."):
                continue
            if part == "..":
                cur = os.path.join(cur, part)
                continue
            try:
                if part not in os.listdir(cur):
                    return False
            except OSError:
                return False
            cur = os.path.join(cur, part)
        return os.path.isfile(cur)

    if not os.path.isdir(CMD_DIR) or not any(f.endswith(".md") for f in os.listdir(CMD_DIR)):
        errors.append(f"{CMD_DIR} is missing or has no commands — was it moved? Every check below would pass vacuously")
    if not os.path.isdir(SKILL_DIR):
        errors.append(f"{SKILL_DIR} is missing — Codex has no skills at all")
    commands = sorted(f[:-3] for f in os.listdir(CMD_DIR) if f.endswith(".md")) if os.path.isdir(CMD_DIR) else []
    skill_dirs = sorted(d for d in os.listdir(SKILL_DIR)
                        if os.path.isdir(os.path.join(SKILL_DIR, d))) if os.path.isdir(SKILL_DIR) else []
    skills = [d for d in skill_dirs if os.path.isfile(os.path.join(SKILL_DIR, d, "SKILL.md"))]

    # 7 + 8. Commands are real, readable files; skills are not symlinks.
    for c in commands:
        p = os.path.join(CMD_DIR, c + ".md")
        if os.path.islink(p):
            errors.append(f"{p}: is a symlink — commands must be real files")
        read(p)
    for s in skills:
        if os.path.islink(os.path.join(SKILL_DIR, s)) or os.path.islink(os.path.join(SKILL_DIR, s, "SKILL.md")):
            errors.append(f"{SKILL_DIR}/{s}: skill directory or SKILL.md is a symlink — must be a real file")

    claude_only = set()
    if os.path.isfile(ALLOW_FILE):
        for line in read(ALLOW_FILE).splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                claude_only.add(line)

    # 1. Wrapper skills link to their own command; every command link resolves.
    for s in skills:
        skill_md = os.path.join(SKILL_DIR, s, "SKILL.md")
        targets = set()
        for link in md_links(read(skill_md)):
            link = link.split("#", 1)[0]
            if not re.search(r"(^|/)\.claude/commands/[^/]+\.md$", link):
                continue
            resolved = os.path.normpath(os.path.join(os.path.dirname(skill_md), link))
            targets.add(resolved)
            if not exists_exact(resolved):
                errors.append(f"{skill_md}: links to missing file {link} (resolves to {resolved}; case must match exactly)")
        own = os.path.normpath(os.path.join(CMD_DIR, s + ".md"))
        if s in commands and own not in targets:
            errors.append(f"{skill_md}: does not link to its canonical command {own} "
                          f"(needs a real markdown link outside code, e.g. [workflow](../../../{own}))")

    # 2. Every Claude command needs a Codex skill, unless explicitly Claude-only.
    for c in commands:
        if c not in skills and c not in claude_only:
            errors.append(f"{CMD_DIR}/{c}.md: no Codex skill at {SKILL_DIR}/{c}/SKILL.md "
                          f"(run make_skill_links.py, or list '{c}' in {ALLOW_FILE})")
    for c in sorted(claude_only - set(commands)):
        warnings.append(f"{ALLOW_FILE}: '{c}' has no matching command — remove the stale entry")

    # 3. A wrapper skill is ONLY its SKILL.md; the old copy filename is banned everywhere.
    for s in skill_dirs:
        base = os.path.join(SKILL_DIR, s)
        if s not in commands:
            for dirpath, _dirs, files in os.walk(base):
                if "claude-command.md" in files:
                    errors.append(f"{os.path.join(dirpath, 'claude-command.md')}: copied command text — remove it")
            continue  # native Codex skills may carry their own reference docs
        for dirpath, dirs, files in os.walk(base):
            for d in dirs:
                if os.path.islink(os.path.join(dirpath, d)):
                    errors.append(f"{os.path.join(dirpath, d)}: symlinked directory in a linking skill — remove it")
            for f in files:
                p = os.path.join(dirpath, f)
                if p == os.path.join(base, "SKILL.md") or f == ".DS_Store":
                    continue
                if dirpath == base and f == "SKILL.md" + BACKUP_SUFFIX:
                    warnings.append(f"{p}: backup of a replaced wrapper — review it, then remove it when no longer needed")
                    continue
                kind = "copied command text" if f.endswith(".md") else "extra file"
                errors.append(f"{p}: {kind} in a linking skill — remove it; the skill links to {CMD_DIR}/{s}.md")

    # 4. AGENTS.md links to CLAUDE.md (and CLAUDE.kit.md); every relative link resolves.
    agents_text = ""
    if not os.path.isfile("AGENTS.md"):
        errors.append("AGENTS.md is missing")
    else:
        agents_text = read("AGENTS.md")
        agent_links = [t.split("#", 1)[0] for t in md_links(agents_text)]
        for t in sorted(set(agent_links)):
            if not t or re.match(r"^[a-z][a-z0-9+.-]*:", t, re.I) or t.startswith("/"):
                continue  # external URL or absolute path
            if not exists_exact(t):
                errors.append(f"AGENTS.md: links to missing file {t} (case must match exactly) — Codex would follow a dead link")
            else:
                read(t)
        required = ["CLAUDE.md"] + (["CLAUDE.kit.md"] if os.path.isfile("CLAUDE.kit.md") else [])
        for name in required:
            if not any(t in (name, "./" + name) for t in agent_links) or not os.path.isfile(name):
                errors.append(f"AGENTS.md has no markdown link to {name} (e.g. [{name}]({name})) outside code "
                              f"and comments — Codex loses its route to the shared rules")

    # 5. Nothing at all under .agents/rules/.
    if os.path.isdir(RULES_COPY_DIR):
        for dirpath, _dirs, files in os.walk(RULES_COPY_DIR):
            for f in sorted(files):
                if f != ".DS_Store":
                    errors.append(f"{os.path.join(dirpath, f)}: copied rule file — remove it and point AGENTS.md "
                                  f"at .claude/rules/ instead")

    # 6. Restated rules: exact, ordered, complete, one line each.
    forbidden_re = r"\s+".join(re.escape(w) for w in FORBIDDEN_HEADING.split())
    tagged, found_forbidden = [], False
    for src in RESTATE_SOURCES:
        if not os.path.isfile(src):
            continue
        check_forbidden = src == FORBIDDEN_SOURCE
        rows = scan(read(src))
        forbidden_level = None
        for idx, r in enumerate(rows):
            if r["kind"] != "prose":
                continue
            line = r["line"]
            is_tagged = line.rstrip().endswith(RESTATE_TAG)
            if is_tagged:
                tagged.append(line.rstrip())
            if r["head"] is not None:
                lvl, title = r["head"]
                if lvl == 0:
                    continue
                if forbidden_level is not None and lvl <= forbidden_level:
                    forbidden_level = None
                if check_forbidden and re.search(forbidden_re, title, re.I):
                    forbidden_level, found_forbidden = lvl, True
                continue
            if forbidden_level is not None and r["item"] and not is_tagged:
                errors.append(f"{src}: {FORBIDDEN_HEADING} item is not tagged {RESTATE_TAG} — tag it and restate it "
                              f"in AGENTS.md so Codex gets it: {line.strip()[:80]}")
            if is_tagged or (forbidden_level is not None and r["item"]):
                nxt = rows[idx + 1] if idx + 1 < len(rows) else None
                if nxt and nxt["kind"] == "prose" and nxt["head"] is None and not nxt["item"] \
                        and not nxt["line"].rstrip().endswith(RESTATE_TAG):
                    errors.append(f"{src}: a restated or {FORBIDDEN_HEADING} rule continues onto the next line — "
                                  f"keep each on ONE line so it is restated whole: {line.strip()[:80]}")
    if os.path.isfile(FORBIDDEN_SOURCE) and (tagged or require_restated) and not found_forbidden:
        errors.append(f"no '{FORBIDDEN_HEADING}' heading in {FORBIDDEN_SOURCE} — cannot confirm every forbidden "
                      f"rule reaches Codex (was the heading renamed?)")
    if agents_text:
        arows = classify(agents_text)
        starts = [i for i, (l, k) in enumerate(arows) if k in ("prose", "html") and l.strip() == RESTATED_START]
        ends = [i for i, (l, k) in enumerate(arows) if k in ("prose", "html") and l.strip() == RESTATED_END]
        if not starts and not ends:
            if require_restated or tagged:
                errors.append(f"AGENTS.md: missing the restated block ({RESTATED_START} … {RESTATED_END}) — it must "
                              f"contain the {len(tagged)} line(s) tagged {RESTATE_TAG} in {', then '.join(RESTATE_SOURCES)}")
        elif len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
            errors.append(f"AGENTS.md: restated block needs exactly one start and one end marker, each on its "
                          f"own line, start before end (found {len(starts)} start, {len(ends)} end)")
        else:
            block = [l.rstrip() for l, k in arows[starts[0] + 1:ends[0]] if k not in ("blank", "html")]
            if not block and require_restated:
                errors.append("AGENTS.md: restated block is empty")
            if block != tagged:
                missing = [l for l in tagged if l not in block]
                extra = [l for l in block if l not in tagged]
                for l in missing:
                    errors.append(f"AGENTS.md: restated block is missing tagged line: {l[:90]}")
                for l in extra:
                    errors.append(f"AGENTS.md: restated line is not a tagged line (drifted or untagged): {l[:90]}")
                if not missing and not extra:
                    if len(block) != len(tagged):
                        errors.append(f"AGENTS.md: restated block has {len(block)} line(s) but {len(tagged)} are "
                                      f"tagged — a line is duplicated on one side")
                    else:
                        errors.append(f"AGENTS.md: restated lines are out of order — copy the tagged lines in order "
                                      f"({', then '.join(RESTATE_SOURCES)})")

    # 11. AGENTS.md's rule table names every top-level .claude/rules/*.md.
    if agents_text and os.path.isdir(RULES_DIR):
        rule_files = sorted(f for f in os.listdir(RULES_DIR)
                            if f.endswith(".md") and os.path.isfile(os.path.join(RULES_DIR, f)))
        arows = classify(agents_text)
        s_idx = [i for i, (l, k) in enumerate(arows) if l.strip() == RULES_START]
        e_idx = [i for i, (l, k) in enumerate(arows) if l.strip() == RULES_END]
        span = arows[s_idx[0] + 1:e_idx[0]] if len(s_idx) == 1 and len(e_idx) == 1 and s_idx[0] < e_idx[0] else arows
        table = [l for l, k in span if k == "prose" and l.lstrip().startswith("|")]
        listed = {m.group(1) for l in table for m in RULE_REF_RE.finditer(l)}
        if rule_files and not listed:
            warnings.append(f"AGENTS.md has no rule table naming {RULES_DIR}/*.md — Codex may not read "
                            f"{', '.join(rule_files)}")
        elif listed:
            for f in rule_files:
                if f not in listed:
                    errors.append(f"AGENTS.md: the rule table leaves out {RULES_DIR}/{f} — Codex would never read it. "
                                  f"Re-run the agent-kit installer's apply (it regenerates the table), or add a row")

    # 9. Always-loaded word budget.
    budget_files = [f for f in ("CLAUDE.md", "CLAUDE.kit.md") if os.path.isfile(f)]
    if os.path.isdir(RULES_DIR):
        for dirpath, dirs, files in os.walk(RULES_DIR):
            dirs.sort()
            for f in sorted(files):
                p = os.path.join(dirpath, f)
                if f.endswith(".md") and os.path.isfile(p):
                    frontmatter, _body = split_frontmatter(read(p))
                    if not PATHS_KEY_RE.search(frontmatter):
                        budget_files.append(p)
    counts = [(p, count_words(read(p))) for p in budget_files]
    words = sum(n for _p, n in counts)
    breakdown = ", ".join(f"{p} {n}" for p, n in counts) or "no files"
    print(f"ℹ️  always-loaded words: {words} / {args.word_budget} ({breakdown})")
    if words > args.word_budget:
        errors.append(f"always-loaded instructions are {words} words, over the {args.word_budget}-word budget — give "
                      f"area rules `paths:` frontmatter, or move rationale to docs/workflow/history/")

    # 10. skills-lock.json: native skills match their locked content hash.
    locked_ok, unverifiable = 0, []
    if os.path.lexists(LOCK_FILE):
        text = read(LOCK_FILE)
        data = None
        if text:
            try:
                data = json.loads(text)
            except ValueError as e:
                errors.append(f"{LOCK_FILE}: not valid JSON ({e})")
        locked = data.get("skills") if isinstance(data, dict) else None
        if text and data is not None and not isinstance(locked, dict):
            errors.append(f"{LOCK_FILE}: expected a top-level \"skills\" object mapping skill name to its entry")
        for name, entry in sorted((locked or {}).items()):
            if not name or name in (".", "..") or "/" in name or "\\" in name:
                errors.append(f"{LOCK_FILE}: skill name {name!r} is not a plain folder name")
                continue
            path = os.path.join(SKILL_DIR, name)
            if not os.path.isdir(path):
                errors.append(f"{LOCK_FILE}: locked skill '{name}' has no folder at {path} — reinstall it or update the lock")
                continue
            want = entry.get("computedHash") if isinstance(entry, dict) else None
            if not isinstance(want, str) or not SHA256_RE.match(want):
                unverifiable.append(name)
                continue
            try:
                have = skill_hashes(path)
            except OSError as e:
                errors.append(f"{path}: cannot be read to hash it ({e.__class__.__name__})")
                continue
            if want.lower() in have:
                locked_ok += 1
            else:
                errors.append(f"{path}: content does not match its computedHash in {LOCK_FILE} — the skill was edited "
                              f"or partly updated; reinstall it, or refresh the lock if the change is intended")
        if unverifiable:
            warnings.append(f"{LOCK_FILE}: {len(unverifiable)} skill(s) unverifiable (computedHash is not a 64-hex "
                            f"sha256): {', '.join(unverifiable)}")

    for w in warnings:
        print(f"⚠️  {w}")
    for e in errors:
        print(f"❌ {e}")
    if errors:
        print(f"\n💥 {len(errors)} skill-link problem(s).")
        return 1
    wrappers = sum(1 for s in skills if s in commands)
    print(f"✅ {wrappers} Codex skill(s) link to their Claude command; "
          f"{len(claude_only)} Claude-only command(s); no copied command or rule text; AGENTS.md links to the shared "
          f"rules; {len(tagged)} restated rule line(s) in sync; {words}/{args.word_budget} always-loaded words; "
          f"{locked_ok} locked skill(s) match {LOCK_FILE}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
