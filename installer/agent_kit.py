#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""
agent-kit installer: every mechanical write of an install or upgrade.

The installing agent does the judgment (scanning the stack with this tool's help,
asking the owner, choosing conflict resolutions) and records it in answers.json.
This script turns the kit plus those answers into files, the same way every time:

  scan     --target DIR                         detection signals as JSON (read-only)
  plan     --target DIR [--answers FILE] [--json]   what apply/upgrade would do (read-only)
  apply    --target DIR [--answers FILE]        install exactly what plan shows
  upgrade  --target DIR [--answers FILE]        apply against an existing lock, plus the CHANGELOG
  verify   --target DIR                         post-install checks; prints TEST_COMMANDS to run
  third-party --target DIR --name N --from DIR [--replace]
                                                verify a fetched third-party tree against its pin, copy it in

Common option: --kit DIR (default: the kit this script lives in).
--answers is required unless .claude/agent-kit.lock.json exists; then the lock's
answers are the base and the file (if given) overrides them.

Safety: nothing in the target is ever deleted. A replaced file is renamed to
<file>.pre-agent-kit (or .pre-agent-kit.N). Secret values are never read or
printed: .mcp.json and settings files are touched only at the keys added, and
existing server definitions are never shown.

Exit codes: 0 ok; 1 problems found (verify, plan errors); 2 refused (apply/upgrade had
unresolved conflicts, missing facts or kit errors). Once apply has written the lock it
exits 0; a skill-link generator error after that is printed as a warning.

Python 3.9+, standard library only.
"""
import argparse
import copy
import fnmatch
import glob
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import schema_check  # noqa: E402

DEFAULT_KIT = os.path.dirname(HERE)
LOCK_PATH = ".claude/agent-kit.lock.json"
BACKUP_SUFFIX = ".pre-agent-kit"
LOCK_FORMAT = 1

FACTS_START = "<!-- agent-kit:facts:start -->"
FACTS_END = "<!-- agent-kit:facts:end -->"
AGENTS_START = "<!-- agent-kit:agents:start -->"
AGENTS_END = "<!-- agent-kit:agents:end -->"
RESTATE_TAG = "<!-- codex-restate -->"
RESTATED_START = "<!-- codex-restate:start -->"
RESTATED_END = "<!-- codex-restate:end -->"
KIT_IMPORT = "@CLAUDE.kit.md"
COPYRIGHT_TEXT = "Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License)."
COPYRIGHT_HTML = f"<!-- {COPYRIGHT_TEXT} -->"   # first line inside the CLAUDE.md and AGENTS.md kit blocks
COPYRIGHT_HASH = f"# {COPYRIGHT_TEXT}"          # with the kit's .gitignore lines

PLACEHOLDER_RE = re.compile(r"(?<!\$)\{\{([A-Z][A-Z0-9_]*)\}\}")
LEFTOVER_RE = re.compile(r"(?<!\$)\{\{\s*[A-Za-z_][A-Za-z0-9_ .-]*\s*\}\}")
ENV_REF_RE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)(?::-[^}]*)?\}")
RESOLUTIONS = ("keep-theirs", "take-kit", "kit-renamed")
SKIP_NAMES = {"__pycache__", ".DS_Store"}
SKIP_SUFFIXES = (".pyc",)
# A glob never installs a unit's own tests; list a test file explicitly in `files` to install it.
TEST_FILE_RE = re.compile(r"(^test_.*\.py$|_test\.py$|\.test\.[A-Za-z0-9]+$|\.spec\.[A-Za-z0-9]+$)")
PACK_SETTINGS_KEYS = {"statusLine"}  # top-level settings a pack may set (schema: settings)

LOCK_FILES = ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock",
              "poetry.lock", "Pipfile.lock", "uv.lock", "Cargo.lock", "go.sum", "Gemfile.lock", "composer.lock",
              "mix.lock", "pubspec.lock", "Podfile.lock")


class KitError(Exception):
    """A problem that stops the command (bad kit, bad answers, refused apply)."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def read_text(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def load_json(path, what):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise KitError(f"{what}: cannot read {path}: {exc}")


def dump_json(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def posix(path):
    return path.replace(os.sep, "/")


def tpath(target, rel):
    return os.path.join(target, *rel.split("/"))


def is_skipped_name(path):
    parts = posix(path).split("/")
    return any(p in SKIP_NAMES for p in parts) or path.endswith(SKIP_SUFFIXES)


def backup_name(path):
    cand = path + BACKUP_SUFFIX
    n = 1
    while os.path.lexists(cand):
        cand = f"{path}{BACKUP_SUFFIX}.{n}"
        n += 1
    return cand


def write_file(target, rel, data, log, executable=False):
    path = tpath(target, rel)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    if executable:
        mode = os.stat(path).st_mode
        os.chmod(path, mode | ((mode & 0o444) >> 2))  # add x wherever r is set
    log.append(f"wrote {rel}" + (" (executable)" if executable else ""))


def is_executable(path):
    return os.path.isfile(path) and bool(os.stat(path).st_mode & 0o111)


def rename_aside(target, rel, log):
    """Rename an existing file out of the way. Never deletes."""
    path = tpath(target, rel)
    dest = backup_name(path)
    os.rename(path, dest)
    log.append(f"renamed {rel} -> {posix(os.path.relpath(dest, target))}")


def copy_aside(target, rel, log):
    """Keep a copy of a file before an in-place edit of a kit-owned block."""
    path = tpath(target, rel)
    dest = backup_name(path)
    with open(dest, "wb") as fh:
        fh.write(read_bytes(path))
    log.append(f"saved a copy of {rel} as {posix(os.path.relpath(dest, target))}")


def parse_version(v):
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?", v or "")
    if not m:
        return (0, 0, 0, 0, "")
    pre = m.group(4)
    # A pre-release sorts before its release.
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), 0 if pre else 1, pre or "")


# ---------------------------------------------------------------------------
# The kit
# ---------------------------------------------------------------------------
class FileSpec:
    def __init__(self, unit, src, src_path, dest, template=False, project_owned=False, merge=None, when=None):
        self.unit, self.src, self.src_path, self.dest = unit, src, src_path, dest
        self.template, self.project_owned, self.merge, self.when = template, project_owned, merge, when


class Kit:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.manifest = load_json(os.path.join(self.root, "manifest.json"), "manifest")
        self.errors = []
        self.warnings = []
        schemas = os.path.join(self.root, "schemas")
        self.manifest_schema = load_json(os.path.join(schemas, "manifest.schema.json"), "schema")
        self.pack_schema = load_json(os.path.join(schemas, "pack.schema.json"), "schema")
        for e in schema_check.validate(self.manifest, self.manifest_schema):
            self.errors.append(f"manifest.json {e}")
        self.units = {}
        self.unit_paths = {}
        for rel in self.manifest.get("units", []):
            path = os.path.join(self.root, rel)
            if not os.path.isfile(path):
                self.errors.append(f"manifest.json lists {rel}, which does not exist")
                continue
            data = load_json(path, rel)
            errs = schema_check.validate(data, self.pack_schema)
            name = data.get("name") if isinstance(data, dict) else None
            if errs or not name:
                self.errors.extend(f"{rel} {e}" for e in (errs or ["has no name"]))
                if not name:
                    continue
            self.units[name] = data
            self.unit_paths[name] = os.path.dirname(path)
        if "core" not in self.units:
            self.errors.append("manifest.json lists no core unit")
        self.version = self.manifest.get("version", "0.0.0")
        self.commit = self._git_commit()

    def _git_commit(self):
        """HEAD of the kit clone, plus "-dirty" when the kit has uncommitted (or untracked) changes."""
        try:
            out = subprocess.run(["git", "-C", self.root, "rev-parse", "HEAD"], capture_output=True, text=True,
                                 timeout=10)
            if out.returncode != 0:
                return "unknown"
            head = out.stdout.strip()
            st = subprocess.run(["git", "-C", self.root, "status", "--porcelain", "--untracked-files=normal", "--",
                                 "."], capture_output=True, text=True, timeout=30)
            if st.returncode == 0 and st.stdout.strip():
                head += "-dirty"
            return head
        except (OSError, subprocess.SubprocessError):
            return "unknown"

    @property
    def commit_short(self):
        dirty = self.commit.endswith("-dirty")
        base = self.commit[:-len("-dirty")] if dirty else self.commit
        return base[:12] + ("-dirty" if dirty else "")

    def facts(self, unit_names):
        """name -> fact definition, for core plus the given units."""
        out = {}
        for u in ["core"] + [n for n in unit_names if n != "core"]:
            for f in self.units.get(u, {}).get("facts", []):
                out.setdefault(f["name"], dict(f, unit=u))
        return out

    def file_specs(self, unit):
        """Expand a unit's files and ci entries (globs included) into FileSpecs."""
        data = self.units[unit]
        udir = self.unit_paths[unit]
        specs = []
        entries = list(data.get("files", [])) + [dict(e, when=e.get("when", "github")) for e in data.get("ci", [])]
        if unit != "core" and os.path.isfile(os.path.join(udir, "pack.md")) \
                and not any(e["src"] == "pack.md" for e in entries):
            entries.append({"src": "pack.md", "dest": f".claude/packs/{unit}.md", "template": True})
        for e in entries:
            src = e["src"]
            kw = dict(template=bool(e.get("template")), project_owned=bool(e.get("project_owned")),
                      merge=e.get("merge"), when=e.get("when"))
            if any(ch in src for ch in "*?["):
                if not e["dest"].endswith("/"):
                    self.errors.append(f"{unit}: glob src {src} needs a dest ending in '/'")
                    continue
                base = src.split("*")[0].split("?")[0].split("[")[0]
                base = base[:base.rfind("/") + 1] if "/" in base else ""
                matches = sorted(glob.glob(os.path.join(udir, src), recursive=True))
                for m in matches:
                    if not os.path.isfile(m) or is_skipped_name(m) or TEST_FILE_RE.search(os.path.basename(m)):
                        continue
                    rel_src = posix(os.path.relpath(m, udir))
                    rest = rel_src[len(base):]
                    if kw["template"] and rest.endswith(".tmpl"):
                        rest = rest[:-len(".tmpl")]
                    specs.append(FileSpec(unit, rel_src, m, e["dest"] + rest, **kw))
            else:
                path = os.path.normpath(os.path.join(udir, src))
                if not path.startswith(self.root + os.sep):
                    self.errors.append(f"{unit}: src {src} is outside the kit")
                    continue
                if not os.path.isfile(path):
                    self.errors.append(f"{unit}: src {src} is missing from the kit")
                    continue
                dest = e["dest"]
                if dest.endswith("/"):
                    name = os.path.basename(src)
                    dest += name[:-5] if kw["template"] and name.endswith(".tmpl") else name
                specs.append(FileSpec(unit, src, path, dest, **kw))
        return specs


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------
ANSWER_KEYS = {"facts", "packs", "options", "mcp_map", "resolutions", "claude_only"}
MCP_KEY_PREFIX = ".mcp.json#"   # resolutions key for one server: ".mcp.json#<server>"
CLAUDE_ONLY_PATH = ".agents/claude-only.txt"
CMD_NAME_RE = re.compile(r"^\.claude/commands/([^/]+)\.md$")


def load_answers(path, lock):
    base = {"facts": {}, "packs": [], "options": {}, "mcp_map": {}, "resolutions": {}, "claude_only": []}
    if lock:
        prev = lock.get("answers", {})
        for k in ("facts", "options", "mcp_map"):
            base[k].update(prev.get(k, {}))
        base["packs"] = list(prev.get("packs", []))
        base["claude_only"] = list(prev.get("claude_only", []))
    if path:
        data = load_json(path, "answers")
        if not isinstance(data, dict):
            raise KitError("answers: the top level must be an object")
        unknown = set(data) - ANSWER_KEYS - {"$comment"}
        if unknown:
            raise KitError(f"answers: unknown key(s) {sorted(unknown)}; allowed: {sorted(ANSWER_KEYS)}")
        for k in ("facts", "options", "mcp_map", "resolutions"):
            if k in data:
                if not isinstance(data[k], dict):
                    raise KitError(f"answers: {k} must be an object")
                base[k].update(data[k])
        if "packs" in data:
            if not isinstance(data["packs"], list) or not all(isinstance(p, str) for p in data["packs"]):
                raise KitError("answers: packs must be a list of pack names")
            base["packs"] = list(data["packs"])
        if "claude_only" in data:
            co = data["claude_only"]
            if not isinstance(co, list) or not all(isinstance(c, str) and re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", c)
                                                   for c in co):
                raise KitError("answers: claude_only must be a list of command names (the file name without .md)")
            base["claude_only"] = list(dict.fromkeys(base["claude_only"] + co))
    elif not lock:
        raise KitError("--answers is required when the target has no .claude/agent-kit.lock.json")
    for dest, res in base["resolutions"].items():
        if res not in RESOLUTIONS:
            raise KitError(f"answers: resolution for {dest} is {res!r}; use one of {', '.join(RESOLUTIONS)}")
    for k, v in base["mcp_map"].items():
        if not isinstance(v, str) or not v:
            raise KitError(f"answers: mcp_map.{k} must be the name of an existing server")
    base["packs"] = [p for p in dict.fromkeys(base["packs"]) if p != "core"]
    return base


def fact_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return "\n".join(str(x) for x in v)
    return str(v)


# ---------------------------------------------------------------------------
# Markdown helpers for CLAUDE.md / AGENTS.md
# ---------------------------------------------------------------------------
def fenced_ranges(lines):
    """Indexes of lines inside fenced code blocks (fence lines included)."""
    inside, fence, out = False, None, set()
    for i, line in enumerate(lines):
        m = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if m and (not inside or (m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence))):
            out.add(i)
            if inside:
                inside, fence = False, None
            else:
                inside, fence = True, m.group(1)
            continue
        if inside:
            out.add(i)
    return out


_sync_mods = {}


def _load_sync_module(kit_root, name):
    """A module from the kit's sync/ folder (None when absent or broken; callers fall back)."""
    key = (os.path.abspath(kit_root), name)
    if key not in _sync_mods:
        path = os.path.join(kit_root, "sync", name + ".py")
        _sync_mods[key] = False
        if os.path.isfile(path):
            spec = importlib.util.spec_from_file_location("_kit_" + name, path)
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
                _sync_mods[key] = mod
            except Exception:  # fall back to the local reader
                pass
    return _sync_mods[key] or None


def _load_sync_checker(kit_root):
    return _load_sync_module(kit_root, "check_skill_links")


def frontmatter_lines(text):
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return []
    for j in range(1, len(lines)):
        if lines[j].strip() in ("---", "..."):
            return lines[1:j]
    return []


def frontmatter_description(text, kit_root):
    """The command's description: as make_skill_links.py reads it (falls back to a plain scalar read)."""
    mod = _load_sync_module(kit_root, "make_skill_links")
    if mod is not None and hasattr(mod, "frontmatter_value"):
        return mod.frontmatter_value(text, "description")
    for line in frontmatter_lines(text):
        m = re.match(r"description[ \t]*:(.*)$", line)
        if m:
            return m.group(1).strip().strip("\"'") or None
    return None


def _split_flow(raw):
    """Split a YAML flow list body on commas outside quotes and braces."""
    out, cur, depth, quote = [], "", 0, None
    for ch in raw:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur += ch
        elif ch in "{[":
            depth += 1
            cur += ch
        elif ch in "}]":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def _yaml_item(raw):
    raw = raw.strip()
    if raw[:1] in ("'", '"') and raw[-1:] == raw[:1] and len(raw) > 1:
        return raw[1:-1]
    return re.sub(r"[ \t]+#.*$", "", raw).strip()


def _strip_dot_slash(item):
    """One paths: glob without a leading "./"; quoted when it would start with a YAML indicator ("**")."""
    raw = item.strip()
    q = raw[:1] if raw[:1] in ("'", '"') and raw[-1:] == raw[:1] and len(raw) > 1 else ""
    body = raw[1:-1] if q else raw
    if not body.startswith("./"):
        return item
    body = re.sub(r"^(\./+)+", "", body) or "**"
    if not q and body[:1] in "*&!{[|>%@`'\"#,?:-":
        q = '"'
    lead = item[:len(item) - len(item.lstrip())]
    return f"{lead}{q}{body}{q}"


def normalize_frontmatter_paths(text):
    """Drop a leading "./" from each `paths:` glob in frontmatter ("./**" -> "**", "./src/**" -> "src/**"), so a
    directory fact of "." still gives a glob Claude Code matches. Only the frontmatter's paths: entries change."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return text
    in_paths = False
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() in ("---", "..."):
            break
        m = re.match(r"^paths[ \t]*:(.*)$", line)
        if m:
            raw = m.group(1)
            in_paths = not raw.strip()
            if raw.strip().startswith("[") and raw.strip().endswith("]"):
                inner = raw.strip()[1:-1]
                lines[i] = "paths: [" + ",".join(_strip_dot_slash(x) for x in _split_flow(inner)) + "]"
            elif raw.strip():
                lines[i] = "paths: " + _strip_dot_slash(raw).strip()
            continue
        if in_paths:
            mm = re.match(r"^(\s*-\s+)(.*)$", line)
            if mm:
                lines[i] = mm.group(1) + _strip_dot_slash(mm.group(2)).strip()
            elif line.strip() and not line[:1].isspace():
                in_paths = False
    return "\n".join(lines)


def frontmatter_paths(text):
    """A rule's `paths:` globs (block list, flow list or one scalar); [] when absent."""
    lines = frontmatter_lines(text)
    for i, line in enumerate(lines):
        m = re.match(r"^paths[ \t]*:(.*)$", line)
        if not m:
            continue
        raw = re.sub(r"^\s+|\s+#[^\"']*$", "", m.group(1))
        if raw.startswith("["):
            return [x for x in (_yaml_item(p) for p in _split_flow(raw.strip()[1:-1])) if x]
        if raw:
            return [_yaml_item(raw)]
        out = []
        for nxt in lines[i + 1:]:
            mm = re.match(r"^\s*-\s+(.*)$", nxt)
            if mm:
                out.append(_yaml_item(mm.group(1)))
            elif nxt.strip() and not nxt[:1].isspace():
                break
        return [x for x in out if x]
    return []


def tagged_lines(text, kit_root):
    """Lines ending in the codex-restate tag, outside code, as check_skill_links.py reads them."""
    mod = _load_sync_checker(kit_root)
    if mod is not None and hasattr(mod, "scan"):
        return [r["line"].rstrip() for r in mod.scan(text)
                if r["kind"] == "prose" and r["line"].rstrip().endswith(RESTATE_TAG)]
    lines = text.replace("\r\n", "\n").split("\n")
    fenced = fenced_ranges(lines)
    return [l.rstrip() for i, l in enumerate(lines) if i not in fenced and l.rstrip().endswith(RESTATE_TAG)]


def find_block(text, start, end):
    """(start_index, end_index_after_end_marker) of a marked block, None if absent. Raises on a broken pair."""
    lines = text.split("\n")
    fenced = fenced_ranges(lines)
    s = [i for i, l in enumerate(lines) if l.strip() == start and i not in fenced]
    e = [i for i, l in enumerate(lines) if l.strip() == end and i not in fenced]
    if not s and not e:
        return None
    if len(s) != 1 or len(e) != 1 or e[0] < s[0]:
        raise KitError(f"markers {start} / {end} must appear exactly once each, start first")
    off = [0]
    for l in lines:
        off.append(off[-1] + len(l) + 1)
    return off[s[0]], off[e[0] + 1] - 1  # end offset excludes the newline after the end marker


def section(text, heading):
    """The text from a '## heading' line up to (not including) the next '## ' heading."""
    lines = text.split("\n")
    fenced = fenced_ranges(lines)
    start = None
    for i, l in enumerate(lines):
        if i in fenced:
            continue
        if start is None and l.rstrip() == heading:
            start = i
        elif start is not None and re.match(r"^#{1,2} ", l):
            return start, i
    return (start, len(lines)) if start is not None else None


def wrap(body, start, end):
    return f"{start}\n{body.strip(chr(10))}\n{end}"


def strip_copyright(text):
    """text without a leading kit copyright comment line (the kit block adds its own)."""
    lines = text.split("\n")
    if lines and lines[0].strip() == COPYRIGHT_HTML:
        return "\n".join(lines[1:])
    return text


def replace_restated(text, tagged):
    lines = text.split("\n")
    s = [i for i, l in enumerate(lines) if l.strip() == RESTATED_START]
    e = [i for i, l in enumerate(lines) if l.strip() == RESTATED_END]
    if len(s) != 1 or len(e) != 1 or e[0] < s[0]:
        return text
    return "\n".join(lines[:s[0] + 1] + tagged + lines[e[0]:])


def blank_restated(text):
    lines = text.split("\n")
    s = [i for i, l in enumerate(lines) if l.strip() == RESTATED_START]
    e = [i for i, l in enumerate(lines) if l.strip() == RESTATED_END]
    if len(s) != 1 or len(e) != 1 or e[0] < s[0]:
        return text
    return "\n".join(lines[:s[0] + 1] + lines[e[0]:])


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------
class Row:
    def __init__(self, unit, src, dest, action, reason, **kw):
        self.unit, self.src, self.dest, self.action, self.reason = unit, src, dest, action, reason
        self.resolution = kw.get("resolution")
        self.content = kw.get("content")          # bytes to write, when the row writes
        self.backup = kw.get("backup")            # "rename" | "copy" | None
        self.lock = kw.get("lock")                # lock entry after apply (None: no record)
        self.options = kw.get("options", ())      # resolutions allowed when this is a conflict
        self.executable = kw.get("executable", False)
        self.renamed_from = None                  # the original dest when the kit's file went to <name>-kit

    def to_dict(self):
        d = {"unit": self.unit, "src": self.src, "dest": self.dest, "action": self.action, "reason": self.reason}
        if self.resolution:
            d["resolution"] = self.resolution
        if self.action == "conflict":
            d["options"] = list(self.options)
        return d


class Plan:
    def __init__(self):
        self.rows = []
        self.mcp = []          # dicts: server, unit, action, reason, env
        self.settings = {"hooks": [], "permissions": [], "keys": [], "kept": []}
        self.gitignore = []
        self.env = []
        self.owner_tasks = []
        self.third_party = []
        self.missing_facts = []
        self.no_description = []   # commands that would get no Codex skill (no description:, not Claude-only)
        self.errors = []
        self.warnings = []
        self.mode = "install"
        self.lock = None
        self.new_lock = None
        self.units = []
        self.auto_packs = []   # packs added by a fact (the ticket pack named by TICKET_SYSTEM), not by answers.packs
        self.facts = {}

    @property
    def unresolved(self):
        return [r for r in self.rows if r.action == "conflict" and not r.resolution]

    @property
    def mcp_unresolved(self):
        """MCP servers in conflict with no resolution: dicts with dest (".mcp.json#<server>"), reason, options."""
        return [{"dest": MCP_KEY_PREFIX + m["server"], "reason": m["reason"], "options": m["options"]}
                for m in self.mcp if m["action"] == "conflict" and not m.get("resolution")]

    def resolutions_template(self):
        """{dest: "option | option"} for every unresolved conflict: paste into answers.json, keep one option each."""
        out = {r.dest: " | ".join(r.options) for r in self.unresolved}
        out.update({c["dest"]: " | ".join(c["options"]) for c in self.mcp_unresolved})
        return out

    def to_dict(self):
        return {"mode": self.mode, "units": self.units, "auto_packs": self.auto_packs,
                "files": [r.to_dict() for r in self.rows], "mcp": self.mcp, "settings": self.settings,
                "gitignore": self.gitignore, "env": self.env, "owner_tasks": self.owner_tasks, "third_party": self.third_party,
                "missing_facts": self.missing_facts,
                "unresolved_conflicts": [r.dest for r in self.unresolved] + [c["dest"] for c in self.mcp_unresolved],
                "resolutions_template": self.resolutions_template(),
                "commands_without_description": self.no_description,
                "errors": self.errors, "warnings": self.warnings}


def renamed_dest(dest):
    """`<name>-kit` for commands and skills; None when renaming isn't offered for this path."""
    m = re.match(r"^(\.claude/commands/(?:.*/)?)([^/]+)\.md$", dest)
    if m:
        return f"{m.group(1)}{m.group(2)}-kit.md"
    m = re.match(r"^(\.(?:claude|agents)/skills/)([^/]+)(/.*)$", dest)
    if m:
        return f"{m.group(1)}{m.group(2)}-kit{m.group(3)}"
    return None


def renamed_name(dest):
    """The command or skill name a dest defines (commands: the file stem; skills: SKILL.md's folder)."""
    m = re.match(r"^\.claude/commands/(?:.*/)?([^/]+)\.md$", dest)
    if m:
        return m.group(1)
    m = re.match(r"^\.(?:claude|agents)/skills/([^/]+)/SKILL\.md$", dest)
    return m.group(1) if m else None


def rename_frontmatter(content, old_dest, new_dest):
    """Rewrite a frontmatter `name: <old>` to the kit-renamed name, so two skills never share one name."""
    old, new = renamed_name(old_dest), renamed_name(new_dest)
    if not old or not new or old == new:
        return content
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return content
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return content
    for i in range(1, len(lines)):
        line = lines[i].rstrip("\r")
        if line.strip() in ("---", "..."):
            break
        m = re.match(r"""^name[ \t]*:[ \t]*(["']?)([^"'#]*?)\1[ \t]*(#.*)?$""", line)
        if m and m.group(2).strip() == old:
            lines[i] = f"name: {new}" + ("\r" if lines[i].endswith("\r") else "")
            return "\n".join(lines).encode("utf-8")
    return content


def skill_dir(dest):
    m = re.match(r"^(\.(?:claude|agents)/skills/[^/]+)/", dest)
    return m.group(1) if m else None


def read_lock(target):
    path = tpath(target, LOCK_PATH)
    if not os.path.isfile(path):
        return None
    lock = load_json(path, "lock")
    if not isinstance(lock, dict) or not isinstance(lock.get("files"), dict):
        raise KitError(f"{LOCK_PATH} is not a valid agent-kit lock")
    return lock


TICKET_FACT = "TICKET_SYSTEM"


def ticket_pack_for(kit, answers, packs, plan):
    """The ticket pack follows TICKET_SYSTEM: [that pack] when the kit has a ticket pack by that name and it isn't
    chosen yet, else []. It is not written into answers.packs; the fact brings it back on every run."""
    ts = answers["facts"].get(TICKET_FACT)
    if ts in (None, ""):
        ts = next((f.get("default") for f in kit.units.get("core", {}).get("facts", []) if f["name"] == TICKET_FACT),
                  None)
    ts = fact_value(ts) if ts is not None else None
    ticket_packs = sorted(n for n, d in kit.units.items() if d.get("kind") == "ticket")
    for p in packs:
        if p in ticket_packs and p != ts:
            plan.warnings.append(f"pack {p} is a ticket pack but {TICKET_FACT} is {ts!r}; the ticket pack follows "
                                 f"{TICKET_FACT}: set it to {p!r}, or drop {p} from packs")
    if ts in ticket_packs:
        return [] if ts in packs else [ts]
    if ts and ts.lower() != "none":
        plan.warnings.append(f"{TICKET_FACT} is {ts!r}, and the kit has no ticket pack by that name (ticket packs: "
                             f"{', '.join(ticket_packs) or 'none'}); no ticket pack is installed, so the ticket ops "
                             "in docs/workflow/ticket-ops.md have no implementation")
    return []


def origin_warnings(target, github, main_branch):
    """The kit's fingerprint and covered calls compare against origin/<MAIN_BRANCH>; the CI check needs GitHub."""
    url = git_out(target, "remote", "get-url", "origin")
    if url is None:
        return [f"the target has no `origin` remote (or is not a git repository): the fingerprint and covered calls "
                f"in /triage, /operate, /post-op and /ship compare against origin/{main_branch}. Add origin and push "
                f"{main_branch} before running them"]
    host = remote_host(url)
    if github and host != "github.com":
        where = f"on {host}" if host else "a local path or an unrecognized URL"
        return [f"GitHub is on (options.github, or a .github/ folder), but origin is {where}, not GitHub: the "
                "skill-link GitHub Actions workflow won't run there. Answer options.github false, or run "
                ".github/scripts/check_skill_links.py --require-restated in that host's CI"]
    return []


def owner_task_applies(task, values):
    """An owner task with `when: {fact, equals}` is shown only when that fact has that value."""
    when = task.get("when")
    if not when:
        return True
    return values.get(when.get("fact")) == fact_value(when.get("equals"))


def build_plan(kit, target, answers_path, upgrade=False):
    target = os.path.abspath(target)
    if not os.path.isdir(target):
        raise KitError(f"target {target} is not a directory")
    plan = Plan()
    plan.errors.extend(kit.errors)
    lock = read_lock(target)
    if upgrade and not lock:
        raise KitError(f"upgrade needs {LOCK_PATH}; run apply for a first install")
    plan.lock = lock
    plan.mode = "upgrade" if lock else "install"
    answers = load_answers(answers_path, lock)

    # Units: core + chosen packs, checked against requires/conflicts.
    packs = answers["packs"]
    for p in packs:
        if p not in kit.units:
            plan.errors.append(f"pack {p!r} is not in this kit (known: {', '.join(sorted(n for n in kit.units if n != 'core'))})")
    packs = [p for p in packs if p in kit.units]
    plan.auto_packs = ticket_pack_for(kit, answers, packs, plan)
    packs += plan.auto_packs
    units = ["core"] + packs
    plan.units = units
    for p in packs:
        for r in kit.units[p].get("requires", []):
            if r not in units:
                plan.errors.append(f"pack {p} requires {r}, which is not selected")
        for c in kit.units[p].get("conflicts", []):
            if c in units:
                plan.errors.append(f"pack {p} conflicts with {c}; pick one")

    # Facts.
    fact_defs = kit.facts(units)
    values = {}
    defaulted = []
    for name, f in fact_defs.items():
        if name in answers["facts"] and answers["facts"][name] not in (None, ""):
            values[name] = fact_value(answers["facts"][name])
        elif "default" in f:
            values[name] = f["default"]  # may reference another fact as {{NAME}}; filled below
            if f.get("required"):
                defaulted.append(f"{name}={f['default']!r}")
        else:
            # No answer and no default: refused, required or not. A fact used as a label, path or directory must
            # never silently become "none"; the owner answers "none" explicitly when that is what they mean.
            plan.missing_facts.append({"name": name, "unit": f["unit"], "ask": f.get("ask", ""),
                                       "required": bool(f.get("required"))})
    for name in list(values):
        if name not in answers["facts"] and PLACEHOLDER_RE.search(values[name]):
            filled = PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), m.group(0)), values[name])
            if PLACEHOLDER_RE.search(filled):
                del values[name]
                plan.missing_facts.append({"name": name, "unit": fact_defs[name]["unit"],
                                           "ask": fact_defs[name].get("ask", ""),
                                           "required": bool(fact_defs[name].get("required"))})
            else:
                values[name] = filled
    if defaulted:
        plan.warnings.append(f"{len(defaulted)} required fact(s) not answered; using the defaults: "
                             + ", ".join(defaulted))
    unknown_facts = sorted(set(answers["facts"]) - set(fact_defs))
    if unknown_facts:
        plan.warnings.append(f"answers.facts has values no selected unit defines: {', '.join(unknown_facts)}")
    plan.facts = values
    missing = {m["name"] for m in plan.missing_facts}
    if "MCP_PREFIX" in values and values["MCP_PREFIX"] != "none" and not MCP_PREFIX_RE.match(values["MCP_PREFIX"]):
        plan.errors.append(f"MCP_PREFIX {values['MCP_PREFIX']!r}: use lowercase letters, digits and _ only "
                           "(for example acme_), or none")
    names = mcp_names(kit, units, values, answers["mcp_map"])

    def render(spec):
        raw = read_bytes(spec.src_path)
        if not spec.template:
            if b"mcp__" in raw or b"MCP server" in raw:
                try:
                    return rename_mcp_refs(raw.decode("utf-8"), names).encode("utf-8")
                except UnicodeDecodeError:
                    return raw
            return raw
        text = raw.decode("utf-8")
        unknown = set()

        def sub(m):
            n = m.group(1)
            if n in values:
                return values[n]
            if n not in missing:
                unknown.add(n)
            return m.group(0)
        out = rename_mcp_refs(normalize_frontmatter_paths(PLACEHOLDER_RE.sub(sub, text)), names)
        if unknown:
            plan.errors.append(f"{spec.unit}/{spec.src}: placeholder(s) no unit defines: {', '.join(sorted(unknown))}")
        return out.encode("utf-8")

    github = answers["options"].get("github")
    if github is None:
        github = scan_github(target)
    plan.warnings.extend(origin_warnings(target, github, values.get("MAIN_BRANCH", "main")))
    lock_files = lock["files"] if lock else {}
    resolutions = answers["resolutions"]

    # Expand file specs.
    specs = []
    for u in units:
        specs.extend(kit.file_specs(u))
    plan.errors.extend(e for e in kit.errors if e not in plan.errors)

    # Destinations already renamed by an earlier kit-renamed resolution.
    renamed_by_lock = {(e.get("unit"), e.get("src")): d for d, e in lock_files.items() if e.get("renamed_from")}
    renamed_dirs = set()
    for dest, res in resolutions.items():
        if res == "kit-renamed" and skill_dir(dest):
            renamed_dirs.add(skill_dir(dest))
    for e in lock_files.values():
        if e.get("renamed_from") and skill_dir(e["renamed_from"]):
            renamed_dirs.add(skill_dir(e["renamed_from"]))

    seen = {}
    merges = {}
    produced = set()
    for spec in specs:
        if spec.dest in seen:
            plan.errors.append(f"{spec.dest} is installed by both {seen[spec.dest]} and {spec.unit}/{spec.src}")
            continue
        seen[spec.dest] = f"{spec.unit}/{spec.src}"
        if spec.merge:
            merges[spec.merge] = spec
            continue
        if spec.when == "github" and not github:
            plan.rows.append(Row(spec.unit, spec.src, spec.dest, "skip", "the target doesn't use GitHub"))
            continue
        content = render(spec)
        dest = renamed_by_lock.get((spec.unit, spec.src), spec.dest)
        sd = skill_dir(spec.dest)
        if dest == spec.dest and sd in renamed_dirs:
            dest = renamed_dest(spec.dest)
        alt = renamed_dest(spec.dest)
        if dest == spec.dest and alt and spec.dest not in lock_files and \
                (lock_files.get(alt, {}).get("unit"), lock_files.get(alt, {}).get("src")) == (spec.unit, spec.src):
            dest = alt  # a lock written before renamed_from was recorded for skills
        if dest != spec.dest:
            content = rename_frontmatter(content, spec.dest, dest)
        produced.add(dest)
        row = plan_file(target, spec, dest, content, lock_files.get(dest), resolutions)
        if dest != spec.dest:
            row.renamed_from = spec.dest
            if row.lock is not None:
                row.lock["renamed_from"] = spec.dest
            if row.action in ("pull", "unchanged"):
                row.reason = f"kit-renamed: the project's {spec.dest} stays; " + row.reason
        plan.rows.append(row)

    # A kit-renamed resolution moves the file to <name>-kit and plans it again there.
    for i, row in enumerate(plan.rows):
        if row.action == "conflict" and row.resolution == "kit-renamed":
            new = renamed_dest(row.dest)
            spec = next(s for s in specs if s.unit == row.unit and s.src == row.src)
            again = plan_file(target, spec, new, rename_frontmatter(row.content_kit, row.dest, new),
                              lock_files.get(new), {})
            again.reason = f"kit-renamed: the project's {row.dest} stays; " + again.reason
            again.renamed_from = row.dest
            if again.lock:
                again.lock["renamed_from"] = row.dest
            if again.action == "conflict":
                plan.errors.append(f"{new} (the kit-renamed target) also exists and differs; resolve it by hand")
            produced.add(new)
            plan.rows[i] = again

    # Claude-only commands named in the answers go into .agents/claude-only.txt; then predict which commands
    # make_skill_links.py can't wrap (no description: frontmatter) so the owner decides before apply.
    plan_claude_only(target, plan, answers["claude_only"])
    plan.no_description = commands_without_description(kit, target, plan)
    if plan.no_description:
        plan.warnings.append("command(s) with no description: frontmatter get no Codex skill, and make_skill_links "
                             "reports an error for each: " + ", ".join(plan.no_description) + ". Add a description: "
                             "line to each, or list them in answers.json \"claude_only\" (written to "
                             f"{CLAUDE_ONLY_PATH}).")

    # Special merges.
    claude_kit = next((r for r in plan.rows if r.dest == "CLAUDE.kit.md"), None)
    if "claude-md" in merges:
        plan.rows.append(plan_claude_md(target, merges["claude-md"], render(merges["claude-md"]).decode("utf-8"),
                                        lock_files.get("CLAUDE.md"), resolutions,
                                        agents_note=agents_note_needed(target, lock_files.get("CLAUDE.md"))))
        produced.add("CLAUDE.md")
    if "agents-md" in merges:
        kit_md = (claude_kit.content or claude_kit.content_kit) if claude_kit else b""
        cm = next((r for r in plan.rows if r.dest == "CLAUDE.md"), None)
        claude_md = cm.final_text if cm else ""
        agents_rendered = rule_loading_table(render(merges["agents-md"]).decode("utf-8"), final_rules(target, plan))
        plan.rows.append(plan_agents_md(kit, target, merges["agents-md"], agents_rendered,
                                        kit_md.decode("utf-8"), claude_md, lock_files.get("AGENTS.md"), resolutions))
        produced.add("AGENTS.md")
    settings_spec = merges.get("settings-json")
    plan.rows.append(plan_settings(kit, target, units, settings_spec, render(settings_spec) if settings_spec else None,
                                   plan, values, names, lock_files.get(".claude/settings.json")))
    produced.add(".claude/settings.json")
    plan.rows.append(plan_mcp(kit, target, units, answers["mcp_map"], plan, values, missing,
                              lock_files.get(".mcp.json"), resolutions))
    produced.add(".mcp.json")
    plan.rows.append(plan_gitignore(kit, target, plan, units))
    produced.add(".gitignore")

    # Orphans: in the lock, no longer shipped.
    for dest, e in sorted(lock_files.items()):
        if dest not in produced and dest != LOCK_PATH:
            row = Row(e.get("unit", "?"), e.get("src", "?"), dest, "orphaned",
                      "the kit no longer ships this file (or its pack was dropped); left in place")
            row.lock = dict(e, orphaned=True)
            plan.rows.append(row)

    # Credentials and third-party sources.
    for u in units:
        for env in kit.units[u].get("env", []):
            plan.env.append(dict(env, unit=u))
        for tp in kit.units[u].get("third_party", []):
            plan.third_party.append(dict(tp, unit=u))
        for t in kit.units[u].get("owner_tasks", []):
            if not owner_task_applies(t, values):
                continue
            plan.owner_tasks.append({k: rename_mcp_refs(fill_text(v, values), names) if isinstance(v, str) else v
                                     for k, v in dict(t, unit=u).items() if k != "when"})

    # Stale resolutions are only warnings. One the lock already settled (a re-run with the same answers) is quiet.
    conflict_dests = {r.dest for r in plan.rows if r.resolution} | {r.renamed_from for r in plan.rows
                                                                     if r.renamed_from}
    conflict_dests |= {MCP_KEY_PREFIX + m["server"] for m in plan.mcp if m.get("resolution")}
    conflict_dests |= set(lock_files)
    conflict_dests |= {MCP_KEY_PREFIX + s for s in (lock_files.get(".mcp.json", {}).get("servers") or {})}
    for dest in resolutions:
        if dest not in conflict_dests and not any(r.lock and r.lock.get("renamed_from") == dest for r in plan.rows):
            plan.warnings.append(f"resolution for {dest} is unused (no conflict there)")

    # The lock this run would write.
    plan.new_lock = build_lock(kit, plan, answers)
    return plan


def plan_file(target, spec, dest, content, lock_entry, resolutions):
    """One ordinary (non-merge) file."""
    path = tpath(target, dest)
    cur = read_bytes(path) if os.path.isfile(path) else None
    kit_sha = sha256(content)
    opts = ("keep-theirs", "take-kit") + (("kit-renamed",) if renamed_dest(dest) else ())
    base_lock = {"src": spec.src, "unit": spec.unit, "project_owned": spec.project_owned, "kit_sha256": kit_sha,
                 "template": spec.template}
    if lock_entry and lock_entry.get("renamed_from"):
        base_lock["renamed_from"] = lock_entry["renamed_from"]

    def row(action, reason, write=False, backup=None, status="installed", sha=None, resolution=None):
        r = Row(spec.unit, spec.src, dest, action, reason, resolution=resolution,
                content=content if write else None, backup=backup, options=opts,
                executable=is_executable(spec.src_path))
        r.content_kit = content
        if status:
            r.lock = dict(base_lock, status=status, sha256_as_installed=sha if sha is not None else
                          (kit_sha if write or status == "installed" else None))
        return r

    if os.path.lexists(path) and not os.path.isfile(path):
        r = row("skip", "exists and is not a regular file; left alone", status=None)
        return r
    if spec.project_owned:
        if lock_entry:
            return row("skip", "project-owned; never touched after the first install", status=None) \
                if cur is None else _keep(row("skip", "project-owned; never touched after the first install",
                                              status=None), lock_entry)
        if cur is None:
            return row("pull", "project-owned; written once, never upgraded", write=True)
        return row("skip", "project-owned and already present; kept as is", status=None)

    res = resolutions.get(dest)
    if cur is None:
        if lock_entry and lock_entry.get("status") != "kept-theirs":
            return _resolve(row, res, "removed by the project since install", cur=None)
        if lock_entry and lock_entry.get("status") == "kept-theirs":
            return _resolve(row, res, "kept-theirs earlier, now missing", cur=None)
        return row("pull", "new file", write=True)
    if cur == content:
        if is_executable(spec.src_path) and not is_executable(path):
            r = row("pull", "content identical; sets the executable bit the kit's file has", write=True)
            return r
        return row("unchanged", "already identical to the kit's version", sha=kit_sha)
    cur_sha = sha256(cur)
    if lock_entry and lock_entry.get("status") == "installed" and lock_entry.get("sha256_as_installed") == cur_sha:
        return row("pull", "update: the kit changed and the file was not customized", write=True)
    if lock_entry and lock_entry.get("status") == "kept-theirs" and lock_entry.get("kit_sha256") == kit_sha:
        r = row("skip", "kept the project's version earlier; the kit's version hasn't changed since",
                status="kept-theirs")
        r.lock["sha256_as_installed"] = None
        return r
    why = "customized since install" if lock_entry else "exists and differs from the kit's version"
    return _resolve(row, res, why, cur=cur)


def _keep(r, lock_entry):
    r.lock = dict(lock_entry)
    return r


def _resolve(row, res, why, cur):
    if not res:
        r = row("conflict", why + "; needs a resolution", status=None)
        return r
    if res == "keep-theirs":
        r = row("conflict", f"{why}; resolved keep-theirs: the project's file stays", status="kept-theirs",
                resolution=res)
        r.lock["sha256_as_installed"] = None
        return r
    if res == "take-kit":
        r = row("conflict", f"{why}; resolved take-kit: theirs is renamed to *{BACKUP_SUFFIX}, the kit's is written"
                if cur is not None else f"{why}; resolved take-kit: the kit's file is restored", write=True,
                backup="rename" if cur is not None else None, resolution=res)
        return r
    r = row("conflict", f"{why}; resolved kit-renamed", status=None, resolution=res)
    if not renamed_dest(r.dest):
        r.reason = f"{why}; kit-renamed is only for commands and skills, pick another resolution"
        r.resolution = None
    return r


AGENTS_NOTE = "This project's own agent rules are in AGENTS.md above the agent-kit section: read them."


def agents_note_needed(target, lock_entry):
    """True when CLAUDE.md is new and a pre-existing AGENTS.md has the project's own text (outside kit markers).
    Remembered in the lock, so later runs keep the line."""
    if lock_entry:
        return bool(lock_entry.get("agents_note"))
    if os.path.isfile(tpath(target, "CLAUDE.md")) or not os.path.isfile(tpath(target, "AGENTS.md")):
        return False
    try:
        text = read_text(tpath(target, "AGENTS.md"))
        blk = find_block(text, AGENTS_START, AGENTS_END)
    except (OSError, UnicodeDecodeError, KitError):
        return False
    outside = text[:blk[0]] + text[blk[1]:] if blk else text
    return bool(outside.strip())


def plan_claude_md(target, spec, rendered, lock_entry, resolutions, agents_note=False):
    dest = "CLAUDE.md"
    path = tpath(target, dest)
    cur = read_text(path) if os.path.isfile(path) else None
    # The kit's facts block: the template's "## Project facts" section, or the template's own markers.
    blk = find_block(rendered, FACTS_START, FACTS_END)
    lines = rendered.split("\n")
    sec = None if blk else section(rendered, "## Project facts")
    if blk:
        facts_body = rendered[blk[0]:blk[1]].split("\n", 1)[1].rsplit("\n", 1)[0]
    elif sec:
        facts_body = "\n".join(lines[sec[0]:sec[1]]).rstrip("\n")
    else:
        facts_body = "## Project facts\n"
    facts_body = strip_copyright(facts_body)
    if agents_note:
        facts_body = AGENTS_NOTE + "\n\n" + facts_body

    def kit_block(prefix=""):
        """The marked facts block: the copyright line first, then the optional import, then the facts."""
        return wrap(COPYRIGHT_HTML + "\n" + prefix + facts_body, FACTS_START, FACTS_END)

    if blk:
        full = rendered[:blk[0]] + kit_block() + rendered[blk[1]:]
    elif sec:
        full = "\n".join(lines[:sec[0]] + [kit_block(), ""] + lines[sec[1]:])
    else:
        full = rendered.rstrip("\n") + "\n\n" + kit_block() + "\n"
    full = strip_copyright(full)  # a new file carries the notice once, inside the facts block
    base_lock = {"src": spec.src, "unit": spec.unit, "project_owned": False, "merge": "claude-md"}
    if agents_note:
        base_lock["agents_note"] = True
    res = resolutions.get(dest)

    def mk(action, reason, text, status="installed", resolution=None, backup=None):
        r = Row(spec.unit, spec.src, dest, action, reason, resolution=resolution, backup=backup,
                content=text.encode("utf-8") if text is not None and text != cur else None,
                options=("keep-theirs", "take-kit"))
        r.final_text = text if text is not None else (cur or "")
        if status:
            b = find_block(r.final_text, FACTS_START, FACTS_END)
            r.lock = dict(base_lock, status=status, sha256_as_installed=sha256(r.final_text.encode("utf-8")),
                          block_sha256=sha256(r.final_text[b[0]:b[1]].encode("utf-8")) if b else None)
        return r

    if cur is None:
        return mk("pull", "new file from the template; Project facts block marked", full)
    try:
        blk = find_block(cur, FACTS_START, FACTS_END)
    except KitError as exc:
        return mk("conflict", f"broken facts markers ({exc}); fix by hand", None, status=None)
    has_import = any(l.strip() == KIT_IMPORT for l in cur.split("\n"))
    if blk is None:
        prefix = "" if has_import else KIT_IMPORT + "\n\n"
        new_block = kit_block(prefix)
        sep = "" if cur.endswith("\n\n") else ("\n" if cur.endswith("\n") else "\n\n")
        return mk("merge", "existing CLAUDE.md kept; adds the marked Project facts block"
                  + ("" if has_import else " with the @CLAUDE.kit.md import") + " at the end",
                  cur + sep + new_block + "\n")
    current_block = cur[blk[0]:blk[1]]
    inner = strip_copyright(current_block.split("\n", 1)[1].rsplit("\n", 1)[0])
    import_in_block = inner.startswith(KIT_IMPORT + "\n")
    outside_import = any(l.strip() == KIT_IMPORT for l in (cur[:blk[0]] + cur[blk[1]:]).split("\n"))
    prefix = KIT_IMPORT + "\n\n" if (import_in_block or not outside_import) else ""
    new_block = kit_block(prefix)
    if current_block == new_block:
        return mk("unchanged", "facts block already current", cur)
    customized = not lock_entry or lock_entry.get("block_sha256") != sha256(current_block.encode("utf-8"))
    if customized and lock_entry and lock_entry.get("status") == "kept-theirs" \
            and lock_entry.get("kit_block_sha256") == sha256(new_block.encode("utf-8")):
        r = mk("skip", "facts block kept as the project edited it; the kit's version hasn't changed", cur,
               status="kept-theirs")
        r.lock["kit_block_sha256"] = sha256(new_block.encode("utf-8"))
        return r
    new_text = cur[:blk[0]] + new_block + cur[blk[1]:]
    if not customized:
        return mk("merge", "updates only inside the facts markers", new_text)
    why = "the facts block was edited since install" if lock_entry else "a facts block exists that the lock doesn't know"
    if not res:
        return mk("conflict", why + "; needs a resolution", None, status=None)
    if res == "keep-theirs":
        r = mk("conflict", why + "; resolved keep-theirs", cur, status="kept-theirs", resolution=res)
        r.lock["kit_block_sha256"] = sha256(new_block.encode("utf-8"))
        return r
    if res == "take-kit":
        return mk("conflict", why + f"; resolved take-kit: a copy is saved as *{BACKUP_SUFFIX}, then the block is "
                  "replaced", new_text, resolution=res, backup="copy")
    return mk("conflict", why + "; kit-renamed doesn't apply to CLAUDE.md", None, status=None)


def plan_agents_md(kit, target, spec, rendered, kit_md, claude_md, lock_entry, resolutions):
    dest = "AGENTS.md"
    path = tpath(target, dest)
    cur = read_text(path) if os.path.isfile(path) else None
    tagged = tagged_lines(kit_md, kit.root) + tagged_lines(claude_md, kit.root)
    body = strip_copyright(replace_restated(rendered, tagged))  # the block's first line is the canonical notice
    base_lock = {"src": spec.src, "unit": spec.unit, "project_owned": False, "merge": "agents-md"}
    res = resolutions.get(dest)

    def norm(block):
        return sha256(blank_restated(block).encode("utf-8"))

    def mk(action, reason, text, status="installed", resolution=None, backup=None):
        r = Row(spec.unit, spec.src, dest, action, reason, resolution=resolution, backup=backup,
                content=text.encode("utf-8") if text is not None and text != cur else None,
                options=("keep-theirs", "take-kit"))
        r.final_text = text if text is not None else (cur or "")
        if status:
            b = find_block(r.final_text, AGENTS_START, AGENTS_END)
            r.lock = dict(base_lock, status=status, sha256_as_installed=sha256(r.final_text.encode("utf-8")),
                          block_sha256=norm(r.final_text[b[0]:b[1]]) if b else None)
        return r

    def kit_block(text):
        return wrap(COPYRIGHT_HTML + "\n" + text, AGENTS_START, AGENTS_END)

    if cur is None:
        return mk("pull", "new file from the template, inside agent-kit markers", kit_block(body) + "\n")
    try:
        blk = find_block(cur, AGENTS_START, AGENTS_END)
    except KitError as exc:
        return mk("conflict", f"broken agents markers ({exc}); fix by hand", None, status=None)
    # In an existing AGENTS.md the template's H1 is dropped; the project keeps its own title.
    lines = body.split("\n")
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    new_block = kit_block("\n".join(lines))
    if blk is None:
        sep = "" if cur.endswith("\n\n") else ("\n" if cur.endswith("\n") else "\n\n")
        return mk("merge", "existing AGENTS.md kept; appends the kit's section (names CLAUDE.md as the source of "
                  "truth) inside agent-kit markers", cur + sep + new_block + "\n")
    current_block = cur[blk[0]:blk[1]]
    first = strip_copyright("\n".join(current_block.split("\n")[1:])).split("\n", 1)[0]
    if first.startswith("# "):
        # A fresh install wrapped the whole template, H1 included; keep that shape.
        new_block = kit_block(body)
    if current_block == new_block:
        return mk("unchanged", "kit section already current", cur)
    customized = not lock_entry or lock_entry.get("block_sha256") != norm(current_block)
    new_text = cur[:blk[0]] + new_block + cur[blk[1]:]
    if not customized:
        return mk("merge", "updates only inside the agent-kit markers (restated block regenerated)", new_text)
    if lock_entry and lock_entry.get("status") == "kept-theirs" and lock_entry.get("kit_block_sha256") == norm(new_block):
        r = mk("skip", "kit section kept as the project edited it; the kit's version hasn't changed", cur,
               status="kept-theirs")
        r.lock["kit_block_sha256"] = norm(new_block)
        return r
    why = "the kit section was edited since install" if lock_entry else "a kit section exists that the lock doesn't know"
    if not res:
        return mk("conflict", why + "; needs a resolution", None, status=None)
    if res == "keep-theirs":
        r = mk("conflict", why + "; resolved keep-theirs", cur, status="kept-theirs", resolution=res)
        r.lock["kit_block_sha256"] = norm(new_block)
        return r
    if res == "take-kit":
        return mk("conflict", why + f"; resolved take-kit: a copy is saved as *{BACKUP_SUFFIX}, then the section "
                  "is replaced", new_text, resolution=res, backup="copy")
    return mk("conflict", why + "; kit-renamed doesn't apply to AGENTS.md", None, status=None)


def _merge_json_target(target, rel, plan):
    path = tpath(target, rel)
    if not os.path.isfile(path):
        return None, None
    raw = read_text(path)
    try:
        data = json.loads(raw)
    except ValueError:
        plan.errors.append(f"{rel} is not valid JSON; fix it before installing (the installer never rewrites it)")
        return raw, False
    if not isinstance(data, dict):
        plan.errors.append(f"{rel}: the top level is not an object")
        return raw, False
    return raw, data


def valid_pack_setting(key, value):
    """A pack's top-level setting value is well-formed (the schema's allow-list, checked again at install)."""
    if key == "statusLine":
        return isinstance(value, dict) and value.get("type") == "command" and isinstance(value.get("command"), str) \
            and value["command"].strip() != ""
    return False


def plan_settings(kit, target, units, spec, rendered, plan, values=None, names=None, lock_entry=None):
    rel = ".claude/settings.json"
    raw, cur = _merge_json_target(target, rel, plan)
    unit, src = (spec.unit, spec.src) if spec else ("core", "(pack hooks/permissions)")
    if cur is False:
        return Row(unit, src, rel, "skip", "invalid JSON; not touched")
    tmpl = {}
    if rendered is not None:
        try:
            tmpl = json.loads(rendered.decode("utf-8"))
        except ValueError as exc:
            plan.errors.append(f"{unit}/{src} is not valid JSON after filling: {exc}")
            tmpl = {}
    new = copy.deepcopy(cur) if cur else {}
    # Top-level keys other than permissions/hooks: added only when absent.
    for k, v in tmpl.items():
        if k in ("permissions", "hooks"):
            continue
        if k not in new:
            new[k] = copy.deepcopy(v)
            plan.settings["keys"].append(k)
    # Pack settings (allow-listed top-level keys): added when absent, updated when the value is the one the kit
    # installed last time (the lock records it), and otherwise kept: the project's own value always wins.
    kit_wrote = (lock_entry or {}).get("pack_settings")
    kit_wrote = dict(kit_wrote) if isinstance(kit_wrote, dict) else {}  # a hand-edited lock can't crash the plan
    written, claimed = {}, {}
    for u in units:
        settings = kit.units[u].get("settings") or {}
        if not isinstance(settings, dict):
            plan.errors.append(f"{u}: pack.json settings must be an object")
            continue
        for k, v in settings.items():
            if k not in PACK_SETTINGS_KEYS:
                plan.errors.append(f"{u}: pack.json settings.{k} is not allowed (only {sorted(PACK_SETTINGS_KEYS)})")
                continue
            if values is not None:
                unknown = set()
                v = fill_json(v, values, unknown)
                if unknown:
                    plan.errors.append(f"{u}: pack.json settings.{k} names unknown facts: {sorted(unknown)}")
                    continue
            if not valid_pack_setting(k, v):
                plan.errors.append(f"{u}: pack.json settings.{k} is malformed")
                continue
            if k in claimed:
                plan.settings["kept"].append({"key": k, "unit": u, "reason": f"already claimed by the {claimed[k]} pack"})
                continue
            claimed[k] = u
            if k not in new and k in kit_wrote:
                # the kit set it before and the project removed it: that choice stands. Recorded as removed (None),
                # so a value the project puts back later counts as the project's own.
                written[k] = None
                plan.settings["kept"].append({"key": k, "unit": u, "reason": "the project removed it earlier"})
            elif k not in new:
                new[k] = copy.deepcopy(v)
                plan.settings["keys"].append(k)
                written[k] = v
            elif new[k] == v:
                written[k] = v
            elif kit_wrote.get(k) is not None and new[k] == kit_wrote[k]:
                new[k] = copy.deepcopy(v)  # the kit's own earlier value: take the new one
                plan.settings["keys"].append(k)
                written[k] = v
            else:
                plan.settings["kept"].append({"key": k, "unit": u, "reason": "the project sets its own"})
            if k == "statusLine" and k in plan.settings["keys"] and personal_setting(k):
                plan.warnings.append("statusLine: this project's status line (from the statusline pack) takes "
                                     "precedence over the one in your ~/.claude/settings.json")
    # Permissions: union, existing order first.
    perm_sources = [("core", tmpl.get("permissions", {}))] + [(u, kit.units[u].get("permissions", {})) for u in units]
    if values is not None:  # a pack's allow rules may name a fact, e.g. Bash({{EAS_CLI}} whoami)
        perm_sources = [(u, fill_json(perms, values, set())) for u, perms in perm_sources]
    if names:  # tools of a renamed or mapped MCP server: mcp__jira__x -> mcp__acme_jira__x
        perm_sources = [(u, rename_mcp_json(perms, names)) for u, perms in perm_sources]
    for u, perms in perm_sources:
        if not perms:
            continue
        for k, v in perms.items():
            if isinstance(v, list):
                if v:
                    p = new.setdefault("permissions", {})
                    lst = p.setdefault(k, [])
                    if not isinstance(lst, list):
                        plan.errors.append(f"{rel}: permissions.{k} is not a list")
                        continue
                    for item in v:
                        if item not in lst:
                            lst.append(item)
                            plan.settings["permissions"].append(f"{k}: {item} ({u})")
            else:
                p = new.setdefault("permissions", {})
                if k not in p:
                    p[k] = copy.deepcopy(v)
                    plan.settings["permissions"].append(f"{k}: {v} ({u})")
    # Hooks: appended, deduped by command string within the event.
    groups = []
    for event, gs in (tmpl.get("hooks") or {}).items():
        for g in gs:
            groups.append(("core", event, g))
    for u in units:
        for h in kit.units[u].get("hooks", []):
            entry = {"type": "command", "command": h["command"]}
            if "timeout" in h:
                entry["timeout"] = h["timeout"]
            g = {"hooks": [entry]}
            if h.get("matcher") is not None:
                g = {"matcher": h["matcher"], "hooks": [entry]}
            groups.append((u, h["event"], g))
    for u, event, g in groups:
        hooks = new.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            plan.errors.append(f"{rel}: hooks is not an object")
            break
        lst = hooks.setdefault(event, [])
        have = {h.get("command") for eg in lst if isinstance(eg, dict) for h in eg.get("hooks", []) if isinstance(h, dict)}
        add = [h for h in g.get("hooks", []) if h.get("command") not in have]
        if add:
            ng = {k: v for k, v in g.items() if k != "hooks"}
            ng["hooks"] = copy.deepcopy(add)
            lst.append(ng)
            for h in add:
                plan.settings["hooks"].append(f"{event}[{g.get('matcher', '*')}]: {h.get('command')} ({u})")
    for k, v in kit_wrote.items():  # set by a pack that's no longer installed: reported, never removed by the kit
        if k not in claimed and v is not None and new.get(k) == v:
            written[k] = v
            plan.warnings.append(f"{k}: set by a pack that is no longer installed; it stays in .claude/settings.json "
                                 "until you remove it")
    lock = {"src": src, "unit": unit, "project_owned": False, "merge": "settings-json", "status": "installed"}
    if written:
        lock["pack_settings"] = written
    if cur is None:
        if not new:
            return Row(unit, src, rel, "skip", "nothing to add")
        text = dump_json(new)
        r = Row(unit, src, rel, "pull", "new file", content=text.encode("utf-8"))
    elif new == cur:
        r = Row(unit, src, rel, "unchanged", "every kit hook and permission is already present")
        text = raw
    else:
        text = dump_json(new)
        r = Row(unit, src, rel, "merge", "adds kit hooks/permissions; existing entries kept in order",
                content=text.encode("utf-8"))
    r.lock = dict(lock, sha256_as_installed=sha256(text.encode("utf-8")))
    return r


def personal_setting(key):
    """True when the user's own ~/.claude/settings.json sets this top-level key (a project setting overrides it)."""
    try:
        with open(os.path.join(os.path.expanduser("~"), ".claude", "settings.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and key in data


def fill_text(text, values):
    """Fill {{FACT}} placeholders that have values; leave the rest as written."""
    return PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), m.group(0)), text)


def fill_json(obj, values, unknown):
    if isinstance(obj, str):
        for m in PLACEHOLDER_RE.finditer(obj):
            if m.group(1) not in values:
                unknown.add(m.group(1))
        return fill_text(obj, values)
    if isinstance(obj, list):
        return [fill_json(x, values, unknown) for x in obj]
    if isinstance(obj, dict):
        return {k: fill_json(v, values, unknown) for k, v in obj.items()}
    return obj


def entry_sha(conf):
    """Hash of one server definition. Only the hash is kept; a value inside is never printed."""
    return sha256(json.dumps(conf, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


MCP_PREFIX_RE = re.compile(r"^[a-z0-9_]*$")


def mcp_prefix(values):
    """The MCP_PREFIX fact as a string to prepend ('' for none or unset)."""
    v = (values or {}).get("MCP_PREFIX", "")
    return "" if v in ("none", None) else v


def mcp_names(kit, units, values, mcp_map):
    """{kit server name: name installed in .mcp.json}. A server mapped in mcp_map keeps the project's name;
    every other server gets MCP_PREFIX in front."""
    prefix = mcp_prefix(values)
    names = {}
    for u in units:
        for name in kit.units[u].get("mcp", {}):
            names[name] = mcp_map.get(name) or prefix + name
    return names


def rename_mcp_refs(text, names):
    """Rewrite `mcp__<kit server>__` tool names and "`<kit server>` MCP server" phrases to the installed names."""
    for kit_name, real in names.items():
        if real == kit_name:
            continue
        text = re.sub(r"(?<![A-Za-z0-9_])mcp__" + re.escape(kit_name) + "__", "mcp__" + real + "__", text)
        text = text.replace("`" + kit_name + "` MCP server", "`" + real + "` MCP server")
    return text


def rename_mcp_json(obj, names):
    if isinstance(obj, str):
        return rename_mcp_refs(obj, names)
    if isinstance(obj, list):
        return [rename_mcp_json(x, names) for x in obj]
    if isinstance(obj, dict):
        return {k: rename_mcp_json(v, names) for k, v in obj.items()}
    return obj


def plan_mcp(kit, target, units, mcp_map, plan, values=None, missing=(), lock_entry=None, resolutions=None):
    """Add, update or keep each kit MCP server. Servers the kit installed are recorded in the lock (with a hash of
    the entry): an unchanged one follows the kit, an edited one is a conflict. A server the kit never installed is
    the project's and is left alone."""
    rel = ".mcp.json"
    values, resolutions = values or {}, resolutions or {}
    raw, cur = _merge_json_target(target, rel, plan)
    if cur is False:
        return Row("core", "(pack mcp)", rel, "skip", "invalid JSON; not touched")
    cur_servers = (cur or {}).get("mcpServers") or {}
    if not isinstance(cur_servers, dict):
        plan.errors.append(f"{rel}: mcpServers is not an object")
        return Row("core", "(pack mcp)", rel, "skip", "mcpServers is not an object; not touched")
    existing = set(cur_servers)
    recs = (lock_entry or {}).get("servers") or {}
    new = copy.deepcopy(cur) if cur else {}
    changed, backup, records, shipped = False, None, {}, set()
    names = mcp_names(kit, units, values, mcp_map)
    for u in units:
        for kit_name, conf in sorted(kit.units[u].get("mcp", {}).items()):
            name = names[kit_name] if kit_name not in mcp_map else kit_name
            shipped.add(name)
            unknown = set()
            conf = fill_json(conf, values, unknown)
            unknown -= set(missing)
            if unknown:
                plan.errors.append(f"{u}: mcp {name}: placeholder(s) no unit defines: {', '.join(sorted(unknown))}")
            envs = sorted(set(ENV_REF_RE.findall(json.dumps(conf))))
            want = entry_sha(conf)
            item = {"server": name, "unit": u, "env": envs}
            if name != kit_name:
                item["kit_server"] = kit_name
            key = MCP_KEY_PREFIX + name
            res = resolutions.get(key)
            rec = recs.get(name)
            have = cur_servers.get(name)

            def put(action, reason):
                nonlocal changed
                new.setdefault("mcpServers", {})[name] = copy.deepcopy(conf)
                changed = True
                records[name] = {"unit": u, "status": "installed", "sha256": want}
                item.update(action=action, reason=reason)

            def conflict(why):
                nonlocal backup
                item["options"] = ["keep-theirs", "take-kit"]
                if res == "keep-theirs":
                    records[name] = {"unit": u, "status": "kept-theirs", "kit_sha256": want}
                    item.update(action="conflict", resolution=res, reason=f"{why}; resolved keep-theirs: the "
                                "project's entry stays")
                elif res == "take-kit":
                    put("conflict", f"{why}; resolved take-kit: a copy of .mcp.json is saved as *{BACKUP_SUFFIX} "
                                    "(it may hold values: keep it out of git), then the kit's entry is written")
                    item["resolution"] = res
                    if have is not None:
                        backup = "copy"
                else:
                    item.update(action="conflict", reason=why + "; needs a resolution" +
                                ("" if not res else f" ({res} doesn't apply to an MCP server)"))

            if kit_name in mcp_map:
                mapped = mcp_map[kit_name]
                if mapped in existing:
                    item.update(action="mapped", reason=f"mapped to the existing server {mapped!r}; not added")
                else:
                    item.update(action="error", reason=f"mapped to {mapped!r}, which .mcp.json doesn't have")
                    plan.errors.append(f"mcp_map: {kit_name} -> {mapped}: no such server in .mcp.json")
            elif have is None and rec is None:
                put("add", "added with ${ENV} references only")
            elif have is None:
                if rec.get("status") == "kept-theirs" and rec.get("kit_sha256") == want:
                    records[name] = rec
                    item.update(action="kept", reason="removed by the project earlier (kept-theirs); the kit's "
                                "entry hasn't changed since")
                else:
                    conflict("the kit installed this server and the project removed it since")
            elif rec is None:
                if entry_sha(have) == want:
                    records[name] = {"unit": u, "status": "installed", "sha256": want}
                    item.update(action="unchanged", reason="already identical to the kit's entry")
                else:
                    item.update(action="kept", reason="the project's own server with this name (the kit never "
                                "installed it); left untouched. If it is not the same service, tell the owner")
            else:
                cur_sha = entry_sha(have)
                if cur_sha == want:
                    records[name] = {"unit": u, "status": "installed", "sha256": want}
                    item.update(action="unchanged", reason="already identical to the kit's entry")
                elif rec.get("status") == "installed" and rec.get("sha256") == cur_sha:
                    put("update", "the kit changed this server and the project didn't edit it; updated")
                elif rec.get("status") == "kept-theirs" and rec.get("kit_sha256") == want:
                    records[name] = rec
                    item.update(action="kept", reason="kept the project's edited entry earlier; the kit's entry "
                                "hasn't changed since")
                else:
                    conflict("edited in .mcp.json since the kit installed it")
            plan.mcp.append(item)
    for name in sorted(set(recs) - shipped):
        plan.mcp.append({"server": name, "unit": recs[name].get("unit", "?"), "env": [], "action": "orphaned",
                         "reason": "the kit no longer ships this server (or its pack was dropped); left in place"})
    lock = {"src": "(pack mcp)", "unit": "core", "project_owned": False, "merge": "mcp-json", "status": "installed"}
    if records:
        lock["servers"] = {k: records[k] for k in sorted(records)}
    if not changed:
        r = Row("core", "(pack mcp)", rel, "unchanged" if cur is not None else "skip",
                "no MCP servers to add" if not plan.mcp else "nothing new to add or update")
        if cur is not None and plan.mcp:
            r.lock = dict(lock, sha256_as_installed=sha256(raw.encode("utf-8")))
        return r
    text = dump_json(new)
    r = Row("core", "(pack mcp)", rel, "merge" if cur is not None else "pull",
            "adds or updates kit servers; the project's servers untouched" if cur is not None else "new file",
            content=text.encode("utf-8"), backup=backup)
    r.lock = dict(lock, sha256_as_installed=sha256(text.encode("utf-8")))
    return r


def plan_claude_only(target, plan, names):
    """Append answers.claude_only names missing from .agents/claude-only.txt (project-owned: append only)."""
    if not names:
        return
    row = next((r for r in plan.rows if r.dest == CLAUDE_ONLY_PATH), None)
    path = tpath(target, CLAUDE_ONLY_PATH)
    if row is not None and row.content is not None:
        base = row.content.decode("utf-8")
    elif os.path.isfile(path):
        base = read_text(path)
    else:
        base = ""
    listed = {l.split("#", 1)[0].strip() for l in base.splitlines()}
    add = [n for n in names if n not in listed]
    if not add:
        return
    text = base + ("" if not base or base.endswith("\n") else "\n")
    text += "".join(f"{n}  # Claude-only: no description: frontmatter (answers.json claude_only)\n" for n in add)
    if row is None:
        row = Row("core", "(answers claude_only)", CLAUDE_ONLY_PATH, "pull", "", )
        plan.rows.append(row)
    if row.action != "pull":
        row.action = "merge"
    row.reason = (row.reason + "; " if row.action == "pull" and row.reason else "") + \
        f"appends {len(add)} Claude-only command(s) from answers.json: {', '.join(add)}"
    row.content = text.encode("utf-8")


def commands_without_description(kit, target, plan):
    """Commands that will exist after apply, aren't Claude-only and have no description: frontmatter."""
    final = {}
    cmd_dir = tpath(target, ".claude/commands")
    if os.path.isdir(cmd_dir):
        for f in sorted(os.listdir(cmd_dir)):
            p = os.path.join(cmd_dir, f)
            if f.endswith(".md") and os.path.isfile(p):
                final[f[:-3]] = read_bytes(p)
    only_text = None
    for r in plan.rows:
        if r.dest == CLAUDE_ONLY_PATH:
            only_text = r.content
        m = CMD_NAME_RE.match(r.dest)
        if not m:
            continue
        if r.content is not None:
            final[m.group(1)] = r.content
        elif m.group(1) not in final and getattr(r, "content_kit", None) is not None:
            final[m.group(1)] = r.content_kit
    if only_text is None and os.path.isfile(tpath(target, CLAUDE_ONLY_PATH)):
        only_text = read_bytes(tpath(target, CLAUDE_ONLY_PATH))
    only = {l.split("#", 1)[0].strip() for l in (only_text or b"").decode("utf-8", "replace").splitlines()}
    out = []
    for name, data in sorted(final.items()):
        if name in only:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if not frontmatter_description(text, kit.root):
            out.append(name)
    return out


RULES_START = "<!-- agent-kit:rules:start -->"
RULES_END = "<!-- agent-kit:rules:end -->"
RULE_DEST_RE = re.compile(r"^\.claude/rules/[^/]+\.md$")
# "Read before" wording for kit rules whose paths: globs don't say when to read them (the template has no row).
RULE_LABELS = {".claude/rules/ticket-ops.md": "Before any ticket op"}


def final_rules(target, plan):
    """{dest: text} for every .claude/rules/*.md that exists after apply (kit rows and the project's own)."""
    out = {}
    rdir = tpath(target, ".claude/rules")
    if os.path.isdir(rdir):
        for f in sorted(os.listdir(rdir)):
            p = os.path.join(rdir, f)
            if f.endswith(".md") and os.path.isfile(p):
                out[".claude/rules/" + f] = read_bytes(p)
    for r in plan.rows:
        if not RULE_DEST_RE.match(r.dest) or r.action == "skip" and r.content is None and r.dest not in out:
            continue
        if r.content is not None:
            out[r.dest] = r.content
        elif r.dest not in out and getattr(r, "content_kit", None) is not None:
            out[r.dest] = r.content_kit
    return {k: v.decode("utf-8", "replace") for k, v in out.items()}


def rule_loading_table(rendered, rules):
    """Regenerate AGENTS.md's "Rule loading" table inside its own markers, one row per installed rule.
    A row the template already has keeps its wording; any other rule is described by its paths: globs."""
    blk = find_block(rendered, RULES_START, RULES_END)
    lines = rendered.split("\n")
    if blk:
        before, inner, after = rendered[:blk[0]], rendered[blk[0]:blk[1]].split("\n")[1:-1], rendered[blk[1]:]
    else:
        sec = section(rendered, "## Rule loading")
        if not sec:
            return rendered
        i = next((k for k in range(sec[0], sec[1]) if lines[k].lstrip().startswith("|")), None)
        if i is None:
            return rendered
        j = i
        while j < sec[1] and lines[j].lstrip().startswith("|"):
            j += 1
        before = "\n".join(lines[:i]) + "\n"
        inner = lines[i:j]
        after = "\n" + "\n".join(lines[j:]) if j < len(lines) else ""
    header = [l for l in inner[:2] if l.lstrip().startswith("|")]
    if len(header) < 2:
        header = ["| Rule | Read before |", "|---|---|"]
    known, order = {}, []
    for l in inner[2:]:
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        m = re.match(r"^`([^`]+)`$", cells[0]) if cells else None
        if m and len(cells) >= 2 and RULE_DEST_RE.match(m.group(1)):
            known[m.group(1)] = cells[1]
            order.append(m.group(1))
    rows = []
    for dest in [d for d in order if d in rules] + sorted(d for d in rules if d not in known):
        if dest in known:
            when = known[dest]
        elif dest in RULE_LABELS:
            when = RULE_LABELS[dest]
        else:
            globs = frontmatter_paths(rules[dest])
            when = ("Files matching " + ", ".join(f"`{g}`" for g in globs)) if globs else "Any task (always loaded)"
        rows.append(f"| `{dest}` | {md_cell(when)} |")
    table = "\n".join([RULES_START] + header + rows + [RULES_END])
    return before + table + after


def plan_gitignore(kit, target, plan, units=("core",)):
    rel = ".gitignore"
    path = tpath(target, rel)
    cur = read_text(path) if os.path.isfile(path) else None
    have = {l.strip() for l in (cur or "").split("\n")}
    lines = list(kit.manifest.get("gitignore", []))
    for u in units:
        lines += kit.units[u].get("gitignore", [])
    want = [l for l in dict.fromkeys(lines) if l not in have and l.rstrip("/") not in have
            and "/" + l.lstrip("/") not in have]
    plan.gitignore = want
    lock = {"src": "manifest.json#gitignore", "unit": "core", "project_owned": False, "merge": "gitignore",
            "status": "installed"}
    if not want:
        r = Row("core", "manifest.json#gitignore", rel, "unchanged", "kit ignore lines already present")
        r.lock = dict(lock, sha256_as_installed=sha256((cur or "").encode("utf-8")))
        return r
    text = cur or ""
    if text and not text.endswith("\n"):
        text += "\n"
    header = "# agent-kit (per-ticket state and local secrets; *.pre-agent-kit backups are NOT ignored)"
    if header not in have:
        text += ("\n" if text else "") + header + "\n"
    if COPYRIGHT_HASH not in have:
        text += COPYRIGHT_HASH + "\n"
    text += "".join(l + "\n" for l in want)
    r = Row("core", "manifest.json#gitignore", rel, "merge" if cur is not None else "pull",
            f"appends {len(want)} line(s)", content=text.encode("utf-8"))
    r.lock = dict(lock, sha256_as_installed=sha256(text.encode("utf-8")))
    return r


def build_lock(kit, plan, answers):
    files = {}
    if plan.lock:
        # Carry forward entries this plan doesn't speak for (e.g. project-owned files).
        for dest, e in plan.lock.get("files", {}).items():
            files[dest] = e
    for r in plan.rows:
        if r.lock is not None:
            files[r.dest] = {k: v for k, v in sorted(r.lock.items())}
            old = r.lock.get("renamed_from")
            if old and files.get(old, {}).get("src") == r.lock.get("src"):
                files.pop(old)  # drops a lock record only; the project's file itself stays
    units = [{"name": u, "version": kit.units[u].get("version", "0.0.0")} for u in plan.units]
    recorded = {"facts": {k: answers["facts"][k] for k in sorted(answers["facts"])},
                "packs": answers["packs"],
                "options": {k: answers["options"][k] for k in sorted(answers["options"])},
                "mcp_map": {k: answers["mcp_map"][k] for k in sorted(answers["mcp_map"])}}
    if answers["claude_only"]:
        recorded["claude_only"] = sorted(answers["claude_only"])
    return {
        "lock_format": LOCK_FORMAT,
        "kit": {"name": kit.manifest.get("name", "agent-kit"), "version": kit.version, "commit": kit.commit},
        "units": units,
        "answers": recorded,
        "files": {k: files[k] for k in sorted(files)},
        "third_party": (plan.lock or {}).get("third_party", {}),
    }


# ---------------------------------------------------------------------------
# Rendering the plan
# ---------------------------------------------------------------------------
def md_cell(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def summary_line(plan):
    """Row counts by action. A conflict that has a resolution counts as "resolved <how>", not as a conflict."""
    counts = {}
    for r in plan.rows:
        key = f"resolved {r.resolution}" if r.action == "conflict" and r.resolution else r.action
        counts[key] = counts.get(key, 0) + 1
    return "Summary: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))


def plan_markdown(kit, target, plan):
    auto = f" ({', '.join(plan.auto_packs)}: chosen by {TICKET_FACT})" if plan.auto_packs else ""
    out = [f"# agent-kit plan: {target}", "",
           f"Kit {kit.manifest.get('name')} {kit.version} (commit {kit.commit_short}). Mode: **{plan.mode}**. "
           f"Units: {', '.join(plan.units)}{auto}.", ""]
    out.append(summary_line(plan) + ".")
    out += ["", "## Files", "", "| Unit | Src | Dest | Action | Reason |", "|---|---|---|---|---|"]
    order = {"conflict": 0, "pull": 1, "merge": 2, "orphaned": 3, "skip": 4, "unchanged": 5}
    for r in sorted(plan.rows, key=lambda r: (order.get(r.action, 9), r.dest)):
        out.append(f"| {md_cell(r.unit)} | `{md_cell(r.src)}` | `{md_cell(r.dest)}` | {r.action} | {md_cell(r.reason)} |")
    tmpl = plan.resolutions_template()
    if tmpl:
        out += ["", "## Conflicts needing a resolution", "",
                "Add each to `resolutions` in answers.json. Merging by hand = do the merge first, then `keep-theirs`. "
                "Apply and upgrade are all-or-nothing: nothing is written until every conflict has a resolution.", ""]
        for r in plan.unresolved:
            out.append(f"- `{r.dest}`: {' | '.join(r.options)}")
        for c in plan.mcp_unresolved:
            out.append(f"- `{c['dest']}` ({md_cell(c['reason'])}): {' | '.join(c['options'])}")
        out += ["", "Ready to fill: keep one option per line and merge into answers.json.", "", "```json",
                json.dumps({"resolutions": tmpl}, indent=2), "```"]
    if plan.mcp:  # no section at all when no unit ships a server
        out += ["", "## MCP servers (.mcp.json)", "",
                "| Server | Unit | Action | Env vars referenced | Reason |", "|---|---|---|---|---|"]
        for m in plan.mcp:
            out.append(f"| {m['server']} | {m['unit']} | {m['action']} | {', '.join(m['env']) or '—'} | "
                       f"{md_cell(m['reason'])} |")
    if plan.no_description:
        out += ["", "## Commands with no Codex skill", "",
                "These commands have no `description:` frontmatter, so make_skill_links.py can't wrap them for Codex. "
                "Add a description to each, or list them as Claude-only (written to "
                f"`{CLAUDE_ONLY_PATH}`) with this in answers.json:", "", "```json",
                json.dumps({"claude_only": plan.no_description}), "```"]
    out += ["", "## Settings (.claude/settings.json)", ""]
    s = plan.settings
    if s["hooks"] or s["permissions"] or s["keys"] or s.get("kept"):
        out += [f"- hook {h}" for h in s["hooks"]] + [f"- permission {p}" for p in s["permissions"]] + \
               [f"- top-level key `{k}` (set by the kit)" for k in s["keys"]] + \
               [f"- top-level key `{k['key']}` kept, not taken from the {k['unit']} pack: {k['reason']}"
                for k in s.get("kept", [])]
    else:
        out.append("Nothing to add.")
    out += ["", "## .gitignore", ""] + ([f"- `{l}`" for l in plan.gitignore] or ["Nothing to add."])
    out += ["", "## Owner tasks: credentials", ""]
    if plan.env:
        for e in plan.env:
            out.append(f"- Set `{e['name']}` ({e['unit']}): {e.get('purpose', '')}"
                       + (f" How: {e['how_to_get']}" if e.get("how_to_get") else ""))
    else:
        out.append("None.")
    out += ["", "## Owner tasks: setup", ""]
    out += [f"- {t['task']} ({t['unit']})" + (f": {t['why']}" if t.get("why") else "") for t in plan.owner_tasks] \
        or ["None."]
    if plan.third_party:
        out += ["", "## Third-party sources (installed by the agent from the pinned source, never copied)", ""]
        for t in plan.third_party:
            if not t.get("ref") or not t.get("sha256"):
                out.append(f"- {t['name']} ({t['unit']}): pin pending (ref or sha256 is null); it will NOT be installed"
                           + (f". {t['note']}" if t.get("note") else ""))
                continue
            out.append(f"- {t['name']} ({t['unit']}): fetch `{t['source']}` at `{t['ref']}`, then "
                       f"`agent_kit.py third-party --name {t['name']} --from <fetched dir>` installs it into "
                       f"`{third_party_dest(t)}/` after checking sha256 `{t['sha256']}`"
                       + (f" ({t['license']})" if t.get("license") else ""))
    out += ["", "## Unfilled required facts", ""]
    if plan.missing_facts:
        out += ["Apply refuses until each has an answer. A fact with no default must be answered even when it is "
                "optional; answer `none` when that is what the owner means.", ""]
    out += [f"- `{m['name']}` ({m['unit']}{'' if m.get('required', True) else ', optional, no default'}): {m['ask']}"
            for m in plan.missing_facts] or ["None."]
    if plan.warnings:
        out += ["", "## Warnings", ""] + [f"- {w}" for w in plan.warnings]
    if plan.errors:
        out += ["", "## Errors (apply will refuse)", ""] + [f"- {e}" for e in plan.errors]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------
def refuse_reasons(plan):
    reasons = list(plan.errors)
    reasons += [f"unresolved conflict: {r.dest} ({r.reason})" for r in plan.unresolved]
    reasons += [f"unresolved conflict: {c['dest']} ({c['reason']})" for c in plan.mcp_unresolved]
    reasons += [f"required fact missing: {m['name']}" if m.get("required", True) else
                f"fact missing: {m['name']} (optional, but it has no default: answer it, or answer \"none\")"
                for m in plan.missing_facts]
    return reasons


def apply_plan(kit, target, plan):
    target = os.path.abspath(target)
    reasons = refuse_reasons(plan)
    if reasons:
        msg = "refusing to apply:\n  - " + "\n  - ".join(reasons)
        tmpl = plan.resolutions_template()
        if tmpl:
            msg += ("\nNothing was written (all-or-nothing). Resolutions to fill in answers.json, one option each:\n"
                    + json.dumps({"resolutions": tmpl}, indent=2))
        raise KitError(msg)
    log = []
    for r in plan.rows:
        if r.content is None:
            continue
        path = tpath(target, r.dest)
        if os.path.isfile(path) and read_bytes(path) == r.content:
            if r.executable and not is_executable(path):
                mode = os.stat(path).st_mode
                os.chmod(path, mode | ((mode & 0o444) >> 2))
                log.append(f"set the executable bit on {r.dest}")
            continue
        if r.backup == "rename" and os.path.lexists(path):
            rename_aside(target, r.dest, log)
        elif r.backup == "copy" and os.path.isfile(path):
            copy_aside(target, r.dest, log)
        write_file(target, r.dest, r.content, log, executable=r.executable)
    sync_rc = run_skill_links(kit, target, log)
    lock_text = dump_json(plan.new_lock).encode("utf-8")
    lock_path = tpath(target, LOCK_PATH)
    if not (os.path.isfile(lock_path) and read_bytes(lock_path) == lock_text):
        write_file(target, LOCK_PATH, lock_text, log)
    return log, sync_rc


def run_skill_links(kit, target, log):
    script = os.path.join(kit.root, "sync", "make_skill_links.py")
    if not os.path.isfile(script):
        log.append("sync/make_skill_links.py not in this kit; skill wrappers not generated")
        return 0
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run([sys.executable, script, "--repo", target], capture_output=True, text=True, env=env)
    for line in (proc.stdout + proc.stderr).splitlines():
        if line.strip() and not re.search(r"\bunchanged\b", line):
            log.append(f"make_skill_links: {line}")
    if proc.returncode != 0:
        log.append(f"make_skill_links exited {proc.returncode}")
    return proc.returncode


def print_changelog(kit, since):
    path = os.path.join(kit.root, "CHANGELOG.md")
    if not os.path.isfile(path):
        return
    text = read_text(path)
    parts = re.split(r"(?m)^## +\[?v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)\]?.*$", text)
    entries = []
    for i in range(1, len(parts), 2):
        if parts[i] and parse_version(parts[i]) > parse_version(since):
            entries.append(f"## {parts[i]}\n{parts[i + 1].strip()}\n")
    if entries:
        print(f"\nCHANGELOG since {since}:\n")
        print("\n".join(entries))


# ---------------------------------------------------------------------------
# Third-party trees (fetched by the agent, verified and copied here)
# ---------------------------------------------------------------------------
def third_party_dest(entry):
    d = entry.get("dest") or f".claude/skills/{entry['name']}/"
    return d.rstrip("/")


def _hash_tree_module(kit_root):
    path = os.path.join(kit_root, "packs", "_third_party", "hash_tree.py")
    if not os.path.isfile(path):
        raise KitError("packs/_third_party/hash_tree.py is missing from the kit; can't verify a third-party tree")
    spec = importlib.util.spec_from_file_location("_kit_hash_tree", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def install_third_party(kit, target, name, src_dir, replace=False):
    """Verify a fetched tree against its pinned sha256, then copy it into the target. Never deletes."""
    target = os.path.abspath(target)
    lock = read_lock(target)
    if not lock:
        raise KitError(f"run apply first: third-party installs are recorded in {LOCK_PATH}")
    units = [u["name"] for u in lock.get("units", [])]
    entry = None
    for u in units:
        for tp in kit.units.get(u, {}).get("third_party", []):
            if tp.get("name") == name:
                entry = dict(tp, unit=u)
    if entry is None:
        raise KitError(f"no third_party entry named {name!r} in the installed units ({', '.join(units)})")
    if not entry.get("ref") or not entry.get("sha256"):
        raise KitError(f"{name}: the pin is pending (ref or sha256 is null), so it can't be installed"
                       + (f": {entry['note']}" if entry.get("note") else ""))
    ht = _hash_tree_module(kit.root)
    try:
        got = ht.hash_tree(src_dir)
    except (OSError, ValueError) as exc:
        raise KitError(f"{name}: can't hash {src_dir}: {exc}")
    if got != entry["sha256"]:
        raise KitError(f"{name}: the fetched tree doesn't match the pin (expected {entry['sha256']}, got {got}); "
                       f"fetch {entry['source']} at {entry['ref']} exactly")
    dest = third_party_dest(entry)
    dpath = tpath(target, dest)
    log = []
    if os.path.lexists(dpath):
        same = False
        try:
            same = os.path.isdir(dpath) and ht.hash_tree(dpath) == got
        except (OSError, ValueError):
            pass
        if not same:
            if not replace:
                raise KitError(f"{dest} exists and differs from the pinned tree; re-run with --replace to rename it "
                               f"to {dest}{BACKUP_SUFFIX} first")
            rename_aside(target, dest, log)
    if not os.path.isdir(dpath):
        for rel, full in ht.tree_files(src_dir):
            out = tpath(target, dest + "/" + rel.decode("utf-8"))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(full, "rb") as fh_in, open(out, "wb") as fh_out:
                fh_out.write(fh_in.read())
            os.chmod(out, os.stat(full).st_mode & 0o777)
        log.append(f"copied {name} into {dest}")
    tp = lock.setdefault("third_party", {})
    rec = {"unit": entry["unit"], "source": entry["source"], "ref": entry["ref"], "sha256": entry["sha256"],
           "dest": dest}
    if tp.get(name) != rec:
        tp[name] = rec
        lock["third_party"] = {k: tp[k] for k in sorted(tp)}
        write_file(target, LOCK_PATH, dump_json(lock).encode("utf-8"), log)
    return log


# ---------------------------------------------------------------------------
# Scan (read-only)
# ---------------------------------------------------------------------------
def git_out(target, *args):
    try:
        p = subprocess.run(["git", "-C", target] + list(args), capture_output=True, text=True, timeout=10)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def remote_host(url):
    if not url or url.startswith("file:"):
        return None
    m = re.match(r"^[a-z+]+://(?:[^@/]*@)?([^/:]+)", url)  # credentials in the URL are dropped
    if m:
        return m.group(1).lower()
    m = re.match(r"^(?:[^@]+@)?([^:/]+):", url)  # scp-like git@host:path
    return m.group(1).lower() if m else None


def scan_github(target):
    host = remote_host(git_out(target, "remote", "get-url", "origin"))
    return host == "github.com" or os.path.isdir(os.path.join(target, ".github"))


def package_jsons(target):
    """Parsed package.json files: the root one, then workspaces up to two levels down (no node_modules)."""
    out = []
    paths = [os.path.join(target, "package.json")]
    for pat in (("*", "package.json"), ("*", "*", "package.json")):
        paths += sorted(glob.glob(os.path.join(target, *pat)))
    for pj in paths:
        if "node_modules" in pj.split(os.sep) or not os.path.isfile(pj):
            continue
        try:
            with open(pj, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out.append((posix(os.path.relpath(pj, target)), data))
    return out


def package_deps(target):
    deps = set()
    for _rel, data in package_jsons(target):
        for k in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            if isinstance(data.get(k), dict):
                deps.update(data[k])
    for req in glob.glob(os.path.join(target, "requirements*.txt")):
        try:
            for line in read_text(req).splitlines():
                m = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)", line)
                if m:
                    deps.add(m.group(1).lower())
        except OSError:
            pass
    py = os.path.join(target, "pyproject.toml")
    if os.path.isfile(py):
        for m in re.finditer(r'^\s*"([A-Za-z0-9][A-Za-z0-9._-]*)', read_text(py), re.M):
            deps.add(m.group(1).lower())
    return sorted(deps)


SECRET_ASSIGN_RE = re.compile(r"\b([A-Za-z0-9_]*(?:TOKEN|SECRET|KEY|PASSWORD|PASSWD|PASS|AUTH)[A-Za-z0-9_]*)=(\"[^\"]*\"|'[^']*'|\S+)",
                              re.I)
NPM_NO_TEST = "no test specified"


def redact_command(cmd):
    """A script command with inline secret-looking assignments masked (NAME=<redacted>)."""
    return SECRET_ASSIGN_RE.sub(lambda m: f"{m.group(1)}=<redacted>", cmd)


def package_manager(target):
    for f, pm in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("bun.lockb", "bun"), ("bun.lock", "bun")):
        if os.path.isfile(os.path.join(target, f)):
            return pm
    return "npm"


def run_script(pm, script):
    if script in ("test", "start"):
        return {"npm": f"npm {script}", "pnpm": f"pnpm {script}", "yarn": f"yarn {script}"}.get(pm, f"bun run {script}")
    return {"yarn": f"yarn {script}"}.get(pm, f"{pm} run {script}")


def eas_profiles(target):
    """eas.json files (root and two levels down): build profile names, with simulator / distribution hints only."""
    out = []
    paths = [os.path.join(target, "eas.json")]
    for pat in (("*", "eas.json"), ("*", "*", "eas.json")):
        paths += sorted(glob.glob(os.path.join(target, *pat)))
    for p in paths:
        if "node_modules" in p.split(os.sep) or not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        build = data.get("build") if isinstance(data, dict) else None
        if not isinstance(build, dict):
            continue
        rel = posix(os.path.relpath(p, target))
        profiles = []
        for name, conf in build.items():
            conf = conf if isinstance(conf, dict) else {}
            ios = conf.get("ios") if isinstance(conf.get("ios"), dict) else {}
            android = conf.get("android") if isinstance(conf.get("android"), dict) else {}
            profiles.append({"name": name, "simulator": bool(ios.get("simulator")) or android.get("buildType") == "apk"
                             and "sim" in name.lower(),
                             "distribution": conf.get("distribution") if isinstance(conf.get("distribution"), str)
                             else None})
        out.append({"path": rel, "dir": posix(os.path.dirname(rel)) or ".", "build_profiles": profiles})
    return out


def guess_test_runner(target, deps, pjs):
    """(guess or None, [evidence]) for jest / vitest / node --test / pytest."""
    evidence = {"vitest": [], "jest": [], "node --test": [], "pytest": []}
    for rel, data in pjs:
        scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
        for k, v in scripts.items():
            if not isinstance(v, str) or not k.startswith("test"):
                continue
            if re.search(r"\bvitest\b", v):
                evidence["vitest"].append(f"{rel} scripts.{k}")
            if re.search(r"\bjest\b", v):
                evidence["jest"].append(f"{rel} scripts.{k}")
            if re.search(r"\bnode\b[^&|;]*--test\b", v):
                evidence["node --test"].append(f"{rel} scripts.{k}")
            if re.search(r"\bpytest\b", v):
                evidence["pytest"].append(f"{rel} scripts.{k}")
    for dep, runner in (("vitest", "vitest"), ("jest", "jest"), ("jest-expo", "jest"), ("pytest", "pytest")):
        if dep in deps:
            evidence[runner].append(f"dependency {dep}")
    for f in ("pytest.ini", "conftest.py", "tests/conftest.py"):
        if os.path.isfile(os.path.join(target, *f.split("/"))):
            evidence["pytest"].append(f"file {f}")
    for f in ("jest.config.js", "jest.config.ts", "jest.config.cjs", "jest.config.mjs", "vitest.config.ts",
              "vitest.config.js", "vitest.config.mts"):
        if os.path.isfile(os.path.join(target, f)):
            evidence["vitest" if f.startswith("vitest") else "jest"].append(f"file {f}")
    py = os.path.join(target, "pyproject.toml")
    if os.path.isfile(py):
        try:
            if "[tool.pytest" in read_text(py):
                evidence["pytest"].append("pyproject.toml [tool.pytest]")
        except (OSError, UnicodeDecodeError):
            pass
    ranked = sorted((r for r in evidence if evidence[r]), key=lambda r: -len(evidence[r]))
    guess = ranked[0] if ranked else None
    return guess, {r: v for r, v in evidence.items() if v}


def find_files(target, match, max_depth=2):
    """posix relpaths (root first, then sorted) of files whose name satisfies match(), down to max_depth levels.
    Skips .git, node_modules and build output."""
    out = []
    skip = {".git", "node_modules", "dist", "build", ".expo", ".next", "coverage", "__pycache__"}
    for dirpath, dirs, files in os.walk(target):
        rel = os.path.relpath(dirpath, target)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        dirs[:] = sorted(d for d in dirs if d not in skip and not d.startswith(".")) if depth < max_depth else []
        out += [posix(os.path.normpath(os.path.join(rel, f))) for f in sorted(files) if match(f)]
    return sorted(out, key=lambda r: (r.count("/"), r))


APP_CONFIG_RE = re.compile(r"^app\.config\.(?:js|ts|mjs|cjs|json)$")


def mobile_dir(target, deps):
    """The Expo app directory: "." when app.json / app.config.* is at the root, else the first dir holding one.
    app.json counts only with an "expo" key or an expo dependency (other tools use that name too)."""
    for rel in find_files(target, lambda f: f == "app.json" or APP_CONFIG_RE.match(f) is not None):
        if os.path.basename(rel) == "app.json" and "expo" not in deps:
            try:
                with open(tpath(target, rel), encoding="utf-8") as fh:
                    if "expo" not in (json.load(fh) or {}):
                        continue
            except (OSError, ValueError, TypeError):
                continue
        return posix(os.path.dirname(rel)) or "."
    return None


def suggest_facts(target, pjs, eas, runner, default_branch=None, deps=()):
    """Proposed fact values from the scan; the agent confirms each with the owner."""
    out = {}
    deps = set(deps)
    if default_branch:
        out["MAIN_BRANCH"] = default_branch
    pm = package_manager(target) if pjs else None
    tests = []
    for rel, data in pjs:
        scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
        t = scripts.get("test")
        if isinstance(t, str) and t.strip() and NPM_NO_TEST not in t:
            tests.append(f"{posix(os.path.dirname(rel)) or '.'}: {run_script(pm, 'test')}")
    if not tests and runner == "pytest":
        tests.append(".: python3 -m pytest")
    if tests:
        out["TEST_COMMANDS"] = tests
    root = next((d for rel, d in pjs if rel == "package.json"), None)
    scripts = root.get("scripts") if root and isinstance(root.get("scripts"), dict) else {}
    for name in ("dev", "start"):
        if isinstance(scripts.get(name), str):
            out["DEV_SERVER_COMMAND"] = run_script(pm, name)
            break
    tsconfigs = find_files(target, lambda f: f == "tsconfig.json")
    if tsconfigs:
        out["TEST_FRAMEWORK"] = runner if runner in ("vitest", "jest") else "none"
        out["TS_PACKAGE_DIRS"] = "auto"
        if "typescript" in deps:
            if "tsconfig.json" in tsconfigs:
                out["TYPECHECK_COMMAND"] = "npx tsc --noEmit"
            elif len(tsconfigs) == 1:
                out["TYPECHECK_COMMAND"] = f"npx tsc --noEmit -p {posix(os.path.dirname(tsconfigs[0]))}"
    else:
        esm = bool(root and root.get("type") == "module") or bool(find_files(target, lambda f: f.endswith(".mjs")))
        if esm:
            out["SYNTAX_CHECK_COMMAND"] = "node --check <file>"
    md = mobile_dir(target, deps)
    if md:
        out["MOBILE_DIR"] = md
    if eas:
        profiles = eas[0]["build_profiles"]
        names = [p["name"] for p in profiles]
        sims = [p["name"] for p in profiles if p["simulator"]]
        sim = next((n for n in sims if "sim" in n.lower()), sims[0] if sims else
                   next((n for n in names if "sim" in n.lower()), None))
        prod = "production" if "production" in names else next((n for n in names if "prod" in n.lower()), None)
        qa = "preview" if "preview" in names and "preview" != sim else next(
            (p["name"] for p in profiles if p["distribution"] == "internal" and p["name"] not in (sim, prod)
             and not p["simulator"]), None)
        for k, v in (("EAS_PROFILE_QA", qa), ("EAS_PROFILE_SIM", sim), ("EAS_PROFILE_PROD", prod)):
            if v:
                out[k] = v
    if os.path.isdir(os.path.join(target, "supabase", "migrations")):
        out["MIGRATION_TOOL"] = "supabase-cli"
        out["MIGRATIONS_DIR"] = "supabase/migrations"
    return out


LONG_LIVED_NAMES = ("qa", "develop", "staging", "release")
SETTINGS_FILES = (".claude/settings.json", ".claude/settings.local.json")
# An absolute or home path in a hook command (machine-specific); system tool paths are fine.
ABS_PATH_RE = re.compile(r"""(?:^|[\s"'=:])(~/|/(?!(?:usr/)?(?:local/)?s?bin/|dev/null|opt/homebrew/bin/)[A-Za-z])""")


def extra_long_lived_branches(target):
    """Local or remote branches named like a second long-lived branch (qa, develop, staging, release)."""
    refs = git_out(target, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes") or ""
    out = []
    for ref in refs.splitlines():
        if ref.startswith("refs/heads/"):
            short = ref[len("refs/heads/"):]
            name = short
        elif ref.startswith("refs/remotes/"):
            short = ref[len("refs/remotes/"):]
            name = short.split("/", 1)[1] if "/" in short else ""
        else:
            continue
        if name in LONG_LIVED_NAMES:
            out.append(short)
    return sorted(set(out))


def claude_settings(target):
    """[(relpath, parsed object)] for the project's Claude settings files that parse as JSON objects."""
    out = []
    for rel in SETTINGS_FILES:
        try:
            with open(tpath(target, rel), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out.append((rel, data))
    return out


def enabled_plugins(settings):
    """Names of the plugins enabled in .claude/settings*.json (names only)."""
    names = set()
    for _rel, data in settings:
        ep = data.get("enabledPlugins")
        if isinstance(ep, dict):
            names.update(k for k, v in ep.items() if v)
        elif isinstance(ep, list):
            names.update(x for x in ep if isinstance(x, str))
    return sorted(names)


def hooks_with_absolute_paths(settings):
    """Hook commands that name an absolute or home path (they break on another machine). Inline secrets masked."""
    out = []
    for rel, data in settings:
        hooks = data.get("hooks")
        if not isinstance(hooks, dict):
            continue
        for event, groups in sorted(hooks.items()):
            for g in groups if isinstance(groups, list) else []:
                for h in (g.get("hooks") if isinstance(g, dict) else None) or []:
                    cmd = h.get("command") if isinstance(h, dict) else None
                    if isinstance(cmd, str) and ABS_PATH_RE.search(cmd.replace("$CLAUDE_PROJECT_DIR", "")):
                        out.append({"file": rel, "event": event, "command": redact_command(cmd)})
    return out


def mcp_json_gitignored(target, is_repo):
    """True when git ignores .mcp.json (the kit's servers then don't reach other clones); None outside a repo."""
    if not is_repo:
        return None
    return git_out(target, "check-ignore", "-q", ".mcp.json") is not None


def scan(kit, target):
    target = os.path.abspath(target)
    if not os.path.isdir(target):
        raise KitError(f"target {target} is not a directory")
    entries = sorted(os.listdir(target))
    files = [e for e in entries if os.path.isfile(os.path.join(target, e)) and e != ".DS_Store"]
    dirs = [e + "/" for e in entries if os.path.isdir(os.path.join(target, e)) and e != ".git"]
    deps = package_deps(target)
    pjs = package_jsons(target)
    url = git_out(target, "remote", "get-url", "origin")
    default_branch = None
    ref = git_out(target, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if ref:
        default_branch = ref.rsplit("/", 1)[-1]
    current = git_out(target, "symbolic-ref", "--quiet", "--short", "HEAD")
    if not default_branch:
        for b in ("main", "master"):
            if git_out(target, "rev-parse", "--verify", "--quiet", f"refs/heads/{b}"):
                default_branch = b
                break

    def listdir(rel, suffix=""):
        p = tpath(target, rel)
        if not os.path.isdir(p):
            return None
        return sorted(e for e in os.listdir(p) if e.endswith(suffix) and e != ".DS_Store")

    mcp_names = None
    mcp_path = os.path.join(target, ".mcp.json")
    if os.path.isfile(mcp_path):
        try:
            with open(mcp_path, encoding="utf-8") as fh:
                servers = json.load(fh).get("mcpServers", {})
            mcp_names = sorted(servers) if isinstance(servers, dict) else []  # names only, never values
        except (OSError, ValueError, AttributeError):
            mcp_names = "unreadable"
    packs = []
    for name in sorted(kit.units):
        if name == "core":
            continue
        d = kit.units[name].get("detect", {}) or {}
        sig = []
        for pat in d.get("files", []):
            if glob.glob(os.path.join(target, pat)):
                sig.append(f"file {pat}")
        for dep in d.get("package_deps", []):
            if dep in deps:
                sig.append(f"dep {dep}")
        for key, want in sorted((d.get("package_json") or {}).items()):
            for rel, data in pjs:
                if key in data and data[key] == want:
                    sig.append(f"{rel} {key}={json.dumps(want)}")
                    break
        entry = {"name": name, "kind": kit.units[name].get("kind"), "matched": bool(sig), "signals": sig,
                 "ask": d.get("ask"), "description": kit.units[name].get("description", "")}
        if entry["kind"] == "ticket":
            entry["selected_by"] = f"the {TICKET_FACT} fact (don't ask for it as a pack)"
        packs.append(entry)
    packages = []
    for rel, data in pjs:
        scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
        packages.append({"path": rel, "dir": posix(os.path.dirname(rel)) or ".",
                         "type": data.get("type") if isinstance(data.get("type"), str) else None,
                         "scripts": {k: redact_command(v) for k, v in scripts.items() if isinstance(v, str)}})
    eas = eas_profiles(target)
    runner, runner_evidence = guess_test_runner(target, set(deps), pjs)
    is_repo = git_out(target, "rev-parse", "--is-inside-work-tree") == "true"
    settings = claude_settings(target)
    lock = None
    if os.path.isfile(tpath(target, LOCK_PATH)):
        try:
            lk = read_lock(target)
            lock = {"kit_version": lk.get("kit", {}).get("version"), "packs": lk.get("answers", {}).get("packs")}
        except KitError:
            lock = "unreadable"
    return {
        "target": target,
        "empty": not [e for e in entries if e not in (".git", ".DS_Store")],
        "mode": "upgrade" if lock else "install",
        "lock": lock,
        "files": files,
        "dirs": dirs,
        "lock_files": [f for f in LOCK_FILES if os.path.isfile(os.path.join(target, f))],
        "package_deps": deps,
        "git": {"is_repo": is_repo,
                "remote_host": remote_host(url), "default_branch": default_branch, "current_branch": current,
                "has_origin": url is not None, "origin_is_github": remote_host(url) == "github.com"},
        "github": scan_github(target),
        "package_manager": package_manager(target) if pjs else None,
        "packages": packages,
        "eas": eas,
        "test_runner": {"guess": runner, "evidence": runner_evidence},
        "suggested_facts": suggest_facts(target, pjs, eas, runner, default_branch, deps),
        "enabled_plugins": enabled_plugins(settings),
        "mcp_json_gitignored": mcp_json_gitignored(target, is_repo),
        "extra_long_lived_branches": extra_long_lived_branches(target) if is_repo else [],
        "hooks_with_absolute_paths": hooks_with_absolute_paths(settings),
        "existing": {
            "CLAUDE.md": os.path.isfile(os.path.join(target, "CLAUDE.md")),
            "AGENTS.md": os.path.isfile(os.path.join(target, "AGENTS.md")),
            ".claude/commands": listdir(".claude/commands", ".md"),
            ".claude/skills": listdir(".claude/skills"),
            ".claude/rules": listdir(".claude/rules", ".md"),
            ".claude/hooks": listdir(".claude/hooks"),
            ".claude/settings.json": os.path.isfile(tpath(target, ".claude/settings.json")),
            ".agents/skills": listdir(".agents/skills"),
            ".mcp.json servers": mcp_names,
            ".github/workflows": listdir(".github/workflows"),
        },
        "packs": packs,
    }


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------
def compile_patterns(items):
    return [(re.compile(p["regex"], re.I if p.get("ignore_case") else 0), p["reason"]) for p in items]


def verify(kit, target):
    target = os.path.abspath(target)
    lock = read_lock(target)
    problems, notes = [], []
    if not lock:
        raise KitError(f"no {LOCK_PATH}; nothing to verify")
    deny_items = list(kit.manifest["checks"]["denylist"])
    priv = os.path.join(kit.root, kit.manifest["checks"].get("denylist_private_file", "denylist.private.json"))
    if os.path.exists(priv):  # the kit owner's private, gitignored project patterns; absent in public clones
        with open(priv, encoding="utf-8") as fh:
            deny_items += json.load(fh)["denylist"]
    deny = compile_patterns(deny_items)
    for dest, e in sorted(lock["files"].items()):
        path = tpath(target, dest)
        if not os.path.exists(path):
            if e.get("status") == "kept-theirs" and e.get("sha256_as_installed") is None:
                continue
            if e.get("project_owned"):
                notes.append(f"{dest}: project-owned and removed by the project (fine)")
                continue
            problems.append(f"{dest}: in the lock but missing")
            continue
        if e.get("status") == "kept-theirs" or not os.path.isfile(path):
            continue
        try:
            text = read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        if e.get("template") or e.get("merge") in ("claude-md", "agents-md"):
            for i, line in enumerate(text.split("\n"), 1):
                for m in LEFTOVER_RE.finditer(line):
                    problems.append(f"{dest}:{i}: unfilled placeholder {m.group(0)}")
        if not e.get("project_owned") and not e.get("merge"):
            for i, line in enumerate(text.split("\n"), 1):
                for rx, why in deny:
                    if rx.search(line):
                        problems.append(f"{dest}:{i}: matches the kit denylist ({why})")
    for name, rec in sorted((lock.get("third_party") or {}).items()):
        dpath = tpath(target, rec["dest"])
        try:
            ok = _hash_tree_module(kit.root).hash_tree(dpath) == rec["sha256"]
        except (OSError, ValueError, KitError) as exc:
            ok = False
            notes.append(f"third-party {name}: {exc}")
        if not ok:
            problems.append(f"third-party {name}: {rec['dest']} no longer matches its pinned sha256")
    checker = tpath(target, ".github/scripts/check_skill_links.py")
    if os.path.isfile(checker):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.run([sys.executable, checker, "--repo", target, "--require-restated"],
                              capture_output=True, text=True, env=env)
        notes.append("check_skill_links.py --require-restated: " + ("passed" if proc.returncode == 0 else "FAILED"))
        notes.extend(l.strip() for l in (proc.stdout + proc.stderr).splitlines() if "always-loaded words" in l)
        if proc.returncode != 0:
            problems.extend("check_skill_links: " + l for l in (proc.stdout + proc.stderr).splitlines()
                            if l.strip().startswith(("❌", "-", "✗")) or "error" in l.lower())
            if not any(p.startswith("check_skill_links") for p in problems):
                problems.append("check_skill_links.py failed:\n" + (proc.stdout + proc.stderr).strip())
    else:
        notes.append("check_skill_links.py not installed; link check skipped")
    tests = lock.get("answers", {}).get("facts", {}).get("TEST_COMMANDS")
    return problems, notes, fact_value(tests) if tests is not None else None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(prog="agent_kit.py", description="agent-kit installer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "plan", "apply", "upgrade", "verify", "third-party"):
        p = sub.add_parser(name)
        p.add_argument("--target", required=True, help="the project directory")
        p.add_argument("--kit", default=DEFAULT_KIT, help="the kit root (default: this script's kit)")
        if name in ("plan", "apply", "upgrade"):
            p.add_argument("--answers", help="answers.json (optional when a lock exists)")
        if name == "third-party":
            p.add_argument("--name", required=True, help="the third_party entry's name")
            p.add_argument("--from", dest="src", required=True, help="the fetched tree (the source's path at ref)")
            p.add_argument("--replace", action="store_true",
                           help="rename an existing, different dest to *.pre-agent-kit first")
        if name == "plan":
            p.add_argument("--json", action="store_true", help="print the plan as JSON")
            p.add_argument("--upgrade", action="store_true", help="plan an upgrade (requires the lock)")
    args = ap.parse_args(argv)
    try:
        kit = Kit(args.kit)
        if args.cmd == "scan":
            print(json.dumps(scan(kit, args.target), indent=2))
            return 0
        if args.cmd == "third-party":
            for line in install_third_party(kit, args.target, args.name, args.src, args.replace) or ["unchanged"]:
                print(f"- {line}")
            return 0
        if args.cmd == "verify":
            problems, notes, tests = verify(kit, args.target)
            for n in notes:
                print(f"- {n}")
            for p in problems:
                print(f"PROBLEM: {p}")
            print("\nNow run the project's tests exactly as written (TEST_COMMANDS, '<dir>: <command>' per line):")
            print(tests if tests else "(TEST_COMMANDS not recorded in the lock)")
            print("\nverify: " + ("FAILED" if problems else "ok"))
            return 1 if problems else 0
        upgrade = args.cmd == "upgrade" or getattr(args, "upgrade", False)
        plan = build_plan(kit, args.target, args.answers, upgrade=upgrade)
        if args.cmd == "plan":
            if args.json:
                print(json.dumps(plan.to_dict(), indent=2))
            else:
                sys.stdout.write(plan_markdown(kit, os.path.abspath(args.target), plan))
            return 1 if plan.errors else 0
        if upgrade:
            since = (plan.lock or {}).get("kit", {}).get("version", "0.0.0")
            print(f"Upgrading from kit {since} to {kit.version}.")
        log, sync_rc = apply_plan(kit, args.target, plan)
        for line in log:
            print(f"- {line}")
        print(summary_line(plan))
        if not log:
            print("Nothing written: everything is already current.")
        for w in plan.warnings:
            print(f"warning: {w}")
        if sync_rc:
            print(f"warning: make_skill_links exited {sync_rc}; the install and the lock are written. Fix the "
                  "commands it names (or list them in answers.json claude_only) and re-run apply.")
        if plan.env:
            print("Owner tasks (credentials): " + ", ".join(e["name"] for e in plan.env))
        if plan.owner_tasks:
            print("Owner tasks (setup):")
            for t in plan.owner_tasks:
                print(f"- Owner task ({t['unit']}): {t['task']}" + (f" ({t['why']})" if t.get("why") else ""))
        if upgrade:
            print_changelog(kit, since)
        return 0
    except KitError as exc:
        print(f"agent-kit: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
