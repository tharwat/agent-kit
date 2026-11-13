# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""The kit's self-checks (PLAN §10): no source-project facts, no secrets, no delete instructions,
every placeholder defined and used, the always-loaded word budget, and a kit that loads cleanly."""
import fnmatch
import importlib.util
import json
import os
import re
import tempfile
import unittest

from kit_testlib import KIT, agent_kit, kit_text_files, load_json, manifest, unit_files

CHECKS = manifest()["checks"]
ROOTS = tuple(CHECKS["scan_roots"])
UPPER_RE = re.compile(r"<([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*)>")  # single letters (<N>) are run-time counters, skipped below
TEMPLATE_RE = re.compile(r"(?<!\$)\{\{([A-Z][A-Z0-9_]*)\}\}")
PATHS_KEY_RE = re.compile(r"(?m)^paths\s*:")


def readf(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def deny_items():
    """The public generic denylist, plus the gitignored private list of project-specific patterns when present."""
    items = list(CHECKS["denylist"])
    priv = os.path.join(KIT, CHECKS.get("denylist_private_file", "denylist.private.json"))
    if os.path.exists(priv):
        items += load_json(priv)["denylist"]
    return items


def compiled(items):
    return [(re.compile(p["regex"], re.I if p.get("ignore_case") else 0), p["reason"]) for p in items]


def unit_of(rel):
    """'core' or the pack name that owns a kit-relative path."""
    parts = rel.split("/")
    if parts[0] == "packs" and len(parts) > 2:
        return parts[1]
    return "core"


def facts_by_unit():
    out = {}
    for name, path in unit_files().items():
        d = load_json(path)
        out[name] = ({f["name"] for f in d.get("facts", [])}, d.get("requires", []))
    return out


def visible_facts(unit, table):
    names = set(table.get("core", (set(), []))[0])
    stack, seen = [unit], set()
    while stack:
        u = stack.pop()
        if u in seen or u not in table:
            continue
        seen.add(u)
        names |= table[u][0]
        stack.extend(table[u][1])
    return names


def word_count(text):
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[0].strip() == "---":
        for j in range(1, len(lines)):
            if lines[j].strip() in ("---", "..."):
                lines = lines[j + 1:]
                break
    body = re.sub(r"<!--.*?-->", " ", "\n".join(lines), flags=re.S)
    return sum(1 for tok in body.split() if re.search(r"\w", tok))


class KitLoads(unittest.TestCase):
    def test_kit_loads_without_errors(self):
        kit = agent_kit.Kit(KIT)
        for u in kit.units:
            kit.file_specs(u)
        self.assertEqual(kit.errors, [], "\n".join(kit.errors))

    def test_no_two_units_install_the_same_dest(self):
        kit = agent_kit.Kit(KIT)
        seen = {}
        for u in kit.units:
            for s in kit.file_specs(u):
                with self.subTest(dest=s.dest):
                    self.assertNotIn(s.dest, seen, f"{s.dest}: {seen.get(s.dest)} and {u}/{s.src}")
                seen[s.dest] = f"{u}/{s.src}"

    def test_core_file_map(self):
        kit = agent_kit.Kit(KIT)
        dests = {s.src: s.dest for s in kit.file_specs("core")}
        for name in os.listdir(os.path.join(KIT, "core", "commands")):
            if name.endswith(".md"):
                self.assertEqual(dests[f"commands/{name}"], f".claude/commands/{name}")
        self.assertEqual(dests["CLAUDE.kit.md.tmpl"], "CLAUDE.kit.md")
        self.assertEqual(dests["docs/ticket-ops.md"], "docs/workflow/ticket-ops.md")
        self.assertEqual(dests["../sync/claude-only.txt"], ".agents/claude-only.txt")
        owned = {s.dest for s in kit.file_specs("core") if s.project_owned}
        for name in os.listdir(os.path.join(KIT, "core", "project-docs")):
            if name.endswith(".md.tmpl"):
                self.assertIn(f"docs/agent/{name[:-5]}", owned)


class NoSourceFacts(unittest.TestCase):
    def test_denylist(self):
        pats = compiled(deny_items())
        hits = []
        for rel, text in kit_text_files(ROOTS):
            for i, line in enumerate(text.split("\n"), 1):
                for rx, why in pats:
                    if rx.search(line):
                        hits.append(f"{rel}:{i}: {why}: {line.strip()[:100]}")
        self.assertEqual(hits, [], "source-project facts or secrets in the kit:\n" + "\n".join(hits))

    def test_denylist_catches_known_shapes(self):
        pats = compiled(CHECKS["denylist"])
        samples = ["origin/qa", "/Users/someone/x",
                   "-1001234567890", "ghp_" + "a" * 36, "AKIA" + "A" * 16, "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0",
                   "123456789:" + "A" * 35]
        for s in samples:
            with self.subTest(sample=s):
                self.assertTrue(any(rx.search(s) for rx, _ in pats))
        for s in ["umbrella", "confirm the result", "<JIRA_SITE>.atlassian.net", "${SUPABASE_ACCESS_TOKEN}"]:
            with self.subTest(clean=s):
                self.assertFalse(any(rx.search(s) for rx, _ in pats))


class NoDeleteInstructions(unittest.TestCase):
    def _exempt(self, rel):
        return any(fnmatch.fnmatch(rel, e["glob"]) for e in CHECKS["destructive_exempt"])

    @staticmethod
    def _without_deny(rel, text):
        """Settings-shaped JSON may deny destructive commands: drop permissions.deny before scanning."""
        if not (rel.endswith(".json") or rel.endswith(".json.tmpl")):
            return text
        try:
            data = json.loads(text)
        except ValueError:
            return text
        if isinstance(data, dict) and isinstance(data.get("permissions"), dict):
            data["permissions"].pop("deny", None)
        return json.dumps(data, indent=1, ensure_ascii=False)

    def test_no_destructive_commands(self):
        pats = compiled(CHECKS["destructive_patterns"])
        hits = []
        for rel, text in kit_text_files(ROOTS):
            if self._exempt(rel):
                continue
            for i, line in enumerate(self._without_deny(rel, text).split("\n"), 1):
                for rx, why in pats:
                    if rx.search(line):
                        hits.append(f"{rel}:{i}: {why}: {line.strip()[:100]}")
        self.assertEqual(hits, [], "delete instructions in the kit:\n" + "\n".join(hits))

    def test_patterns_catch_and_spare(self):
        pats = compiled(CHECKS["destructive_patterns"])
        for s in ["rm -rf build", "rmdir x", "find . -delete", "fs.unlinkSync(p)", "git reset --hard",
                  "git clean -fd", "git branch -D x", "git push --force", "git push origin x -f", "shutil.rmtree(d)",
                  "git restore a.ts", "git restore --staged --worktree a.ts", "git restore -W a.ts",
                  "git switch -f main", "git switch main --discard-changes", "git worktree remove --force ../wt",
                  "git worktree remove ../wt -f", "git checkout HEAD -- a.ts", "git checkout .", "git checkout -f main",
                  "git checkout main --force", "git reset HEAD~1 --hard", "git branch x -D", "git branch -f x y"]:
            with self.subTest(bad=s):
                self.assertTrue(any(rx.search(s) for rx, _ in pats))
        for s in ["confirm the deploy", "a just-deleted row", "git push origin feature/x", "format the term",
                  "git restore --staged a.ts", "git restore -S a.ts", "git switch -c feature/x",
                  "git worktree remove ../wt", "git worktree add ../wt", "switch to the log and run `tail -f out.log`",
                  "git checkout feature/x", "git checkout --detach origin/main", "git branch -d x",
                  "git checkout -b feature/x origin/main", "a git checkout.", "remove the worktree -f flag"]:
            with self.subTest(ok=s):
                self.assertFalse(any(rx.search(s) for rx, _ in pats))

    def test_settings_deny_list_is_exempt(self):
        text = json.dumps({"permissions": {"allow": [], "deny": ["Bash(rm -rf *)"]}})
        self.assertNotIn("rm -rf", self._without_deny("core/settings.json.tmpl", text))

    def test_installer_never_deletes(self):
        for name in ("agent_kit.py", "schema_check.py"):
            src = readf(os.path.join(KIT, "installer", name))
            with self.subTest(file=name):
                self.assertIsNone(re.search(r"os\.remove|os\.unlink|\.unlink\(|rmtree|os\.rmdir|\brm\b ", src))


def load_hook(rel, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(KIT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class HooksEnforcePatterns(unittest.TestCase):
    """Every rule the kit writes down has a hook rule and a blocked test case, so the two can't drift apart."""

    def test_destructive_patterns_have_a_hook_rule_and_a_blocked_case(self):
        hook = load_hook("core/hooks/block-destructive.py", "block_destructive")
        cases = load_hook("core/hooks/test_block_destructive.py", "test_block_destructive")
        for p in CHECKS["destructive_patterns"]:
            with self.subTest(reason=p["reason"]):
                self.assertIn(p["reason"], hook.RULES)
                self.assertTrue(cases.BLOCKED.get(p["reason"]), "no blocked test case")
        self.assertEqual(set(hook.RULES), {p["reason"] for p in CHECKS["destructive_patterns"]})

    # Denylist entries that are not token shapes: the secret guard doesn't scan for them.
    NOT_TOKENS = {"source-project branch model (the kit is main-only)", "owner's absolute path", "absolute home path",
                  "Telegram chat ID shape", "a real Supabase project URL", "UUID-shaped ID (cloud IDs, project IDs)"}

    def test_token_shapes_have_a_hook_rule_and_a_blocked_case(self):
        hook = load_hook("core/hooks/guard-secrets.py", "guard_secrets")
        cases = load_hook("core/hooks/test_guard_secrets.py", "test_guard_secrets")
        tokens = [p for p in CHECKS["denylist"] if p["reason"] not in self.NOT_TOKENS]
        self.assertTrue(tokens)
        for p in tokens:
            with self.subTest(reason=p["reason"], regex=p["regex"]):
                self.assertIn(p["reason"], hook.SHAPES)
                samples = cases.SHAPE_SAMPLES.get(p["reason"]) or []
                rx = re.compile(p["regex"], re.I if p.get("ignore_case") else 0)
                hit = [s for s in samples if rx.search(s)]
                self.assertTrue(hit, "no blocked sample matches this manifest pattern")
                self.assertTrue(all(re.search(hook.SHAPES[p["reason"]], s) for s in hit))
        self.assertEqual(set(hook.SHAPES), {p["reason"] for p in tokens})

    SOURCE_EXCEPTION = "`source` an env file only to run a command"

    def test_secret_rule_and_hook_agree_on_sourcing(self):
        """The written No-secrets rule allows `source` of an env file, the hook allows it, and both copies agree."""
        for rel in ("core/CLAUDE.kit.md.tmpl", "core/AGENTS.md.tmpl"):
            rule = [l for l in readf(os.path.join(KIT, rel)).split("\n") if l.startswith("- **No secrets**")]
            with self.subTest(file=rel):
                self.assertEqual(len(rule), 1)
                self.assertIn(self.SOURCE_EXCEPTION, rule[0])
        hook = load_hook("core/hooks/guard-secrets.py", "guard_secrets")
        with tempfile.TemporaryDirectory() as d:
            event = lambda cmd: {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": d}
            hook.check_event(event("source .env && npm test"))  # allowed: raises nothing
            with self.assertRaises(hook.Blocked):
                hook.check_event(event("cat .env"))

    def test_agents_template_restates_the_tagged_lines(self):
        """AGENTS.md.tmpl's restated block is exactly CLAUDE.kit.md.tmpl's tagged lines, then CLAUDE.md.tmpl's.
        The installer rebuilds the block on install, so without this the template's copy could drift unseen."""
        tagged = [l for rel in ("core/CLAUDE.kit.md.tmpl", "core/CLAUDE.md.tmpl")
                  for l in readf(os.path.join(KIT, rel)).split("\n") if l.rstrip().endswith("<!-- codex-restate -->")]
        agents = readf(os.path.join(KIT, "core", "AGENTS.md.tmpl"))
        block = agents.split("<!-- codex-restate:start -->\n", 1)[1].split("<!-- codex-restate:end -->", 1)[0]
        self.assertTrue(tagged)
        self.assertEqual([l for l in block.split("\n") if l.strip()], tagged)


class Placeholders(unittest.TestCase):
    def setUp(self):
        self.table = facts_by_unit()
        self.exempt = set(CHECKS["placeholder_exempt"])
        self.kit = agent_kit.Kit(KIT)

    def test_every_upper_snake_value_is_defined(self):
        bad = []
        for rel, text in kit_text_files(ROOTS):
            if rel.endswith("pack.json"):
                continue
            known = visible_facts(unit_of(rel), self.table) | self.exempt
            for i, line in enumerate(text.split("\n"), 1):
                for m in UPPER_RE.finditer(line):
                    if len(m.group(1)) > 1 and m.group(1) not in known:
                        bad.append(f"{rel}:{i}: <{m.group(1)}>")
        self.assertEqual(bad, [], "undefined <UPPER_SNAKE> values (define them as facts):\n" + "\n".join(bad))

    def test_every_template_placeholder_is_defined(self):
        bad = []
        for u in self.kit.units:
            known = visible_facts(u, self.table)
            for s in self.kit.file_specs(u):
                if not s.template:
                    continue
                text = readf(s.src_path)
                for n in TEMPLATE_RE.findall(text):
                    if n not in known:
                        bad.append(f"{u}/{s.src}: {{{{{n}}}}}")
        self.assertEqual(bad, [], "\n".join(bad))

    def test_fact_defaults_reference_visible_facts(self):
        bad = []
        for name, path in unit_files().items():
            known = visible_facts(name, self.table)
            for f in load_json(path).get("facts", []):
                for n in TEMPLATE_RE.findall(f.get("default", "")):
                    if n not in known or n == f["name"]:
                        bad.append(f"{name}: {f['name']} default refers to {n}")
        self.assertEqual(bad, [], "\n".join(bad))

    def test_placeholders_only_in_templates(self):
        templates = {os.path.relpath(s.src_path, KIT).replace(os.sep, "/")
                     for u in self.kit.units for s in self.kit.file_specs(u) if s.template}
        bad = []
        for rel, text in kit_text_files(ROOTS):
            if rel in templates or rel.endswith("pack.json") or fnmatch.fnmatch(rel, "*/hooks/test_*"):
                continue
            if TEMPLATE_RE.search(text):
                bad.append(rel)
        self.assertEqual(bad, [], "{{NAME}} outside a template file (mark the file template: true)")

    def test_every_fact_has_a_default_or_is_required(self):
        # The installer refuses a fact with no answer and no default; an optional fact needs a default so a quiet
        # owner gets a working value, never a silent "none" used as a label, path or directory.
        bad = []
        for name, path in unit_files().items():
            for f in load_json(path).get("facts", []):
                if "default" not in f and not f.get("required"):
                    bad.append(f"{name}: {f['name']}")
        self.assertEqual(bad, [], "optional facts with no default (add a default, or make them required)")

    def test_every_defined_fact_is_used(self):
        corpus = "\n".join(t for _r, t in kit_text_files(ROOTS + ("sync",)) if not _r.endswith("pack.json"))
        unused = []
        for unit, (names, _req) in self.table.items():
            for n in sorted(names):
                if f"<{n}>" not in corpus and f"{{{{{n}}}}}" not in corpus:
                    unused.append(f"{unit}: {n}")
        self.assertEqual(unused, [], "facts defined but never used")


class OwnerTaskConditions(unittest.TestCase):
    def test_when_names_a_visible_fact(self):
        """An owner task's `when` must name a fact of core, the unit or what it requires (else it never shows)."""
        table = facts_by_unit()
        for name, path in unit_files().items():
            for t in load_json(path).get("owner_tasks", []):
                if "when" in t:
                    with self.subTest(unit=name, task=t["task"][:40]):
                        self.assertIn(t["when"]["fact"], visible_facts(name, table))


class WordBudget(unittest.TestCase):
    def test_always_loaded_budget(self):
        files = [os.path.join(KIT, "core", "CLAUDE.kit.md.tmpl"), os.path.join(KIT, "core", "CLAUDE.md.tmpl")]
        for rel, text in kit_text_files(ROOTS):
            parts = rel.split("/")
            is_rule = (parts[:2] == ["core", "rules"]) or (parts[0] == "packs" and len(parts) > 3 and parts[2] == "rules")
            if is_rule and rel.endswith(".md"):
                head = text.split("\n---", 1)[0] if text.startswith("---") else ""
                if not PATHS_KEY_RE.search(head):
                    files.append(os.path.join(KIT, rel))
        counts = {os.path.relpath(f, KIT): word_count(readf(f)) for f in files}
        total = sum(counts.values())
        self.assertLessEqual(total, CHECKS["word_budget"], f"always-loaded words {total}: {counts}")

    def test_unscoped_pack_rules_give_a_reason(self):
        for name, path in unit_files().items():
            if name == "core":
                continue
            d = load_json(path)
            for f in d.get("files", []):
                if f["dest"].startswith(".claude/rules/"):
                    src = os.path.join(os.path.dirname(path), f["src"])
                    if not os.path.isfile(src):
                        continue
                    text = readf(src)
                    head = text.split("\n---", 1)[0] if text.startswith("---") else ""
                    with self.subTest(rule=f["src"], pack=name):
                        if not PATHS_KEY_RE.search(head):
                            self.assertTrue(d.get("always_loaded_reason"), "rule without paths: needs a reason")


if __name__ == "__main__":
    unittest.main()
