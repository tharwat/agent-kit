# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Installer behaviour on temporary target projects (never on a real one)."""
import json
import os
import re
import stat
import subprocess
import unittest

from kit_testlib import (KIT, TempDirs, agent_kit, copy_kit, full_answers, load_json, read, run, snapshot, write,
                         write_answers)

FIXTURE_PACK = "zz-fixture"


def add_fixture_pack(kit_root, tree_sha=None):
    """A pack exercising every pack.json feature, added to a COPY of the kit."""
    d = os.path.join(kit_root, "packs", FIXTURE_PACK)
    write(os.path.join(d, "pack.md"), "# Fixture pack\n\n## Pack facts\n\n| Fact | Value |\n|---|---|\n"
          "| `FIXTURE_KEY` | {{FIXTURE_KEY}} |\n| `FIXTURE_REF` | {{FIXTURE_REF}} |\n")
    write(os.path.join(d, "scripts", "tool"), "#!/bin/sh\necho tool\n")
    os.chmod(os.path.join(d, "scripts", "tool"), 0o755)
    write(os.path.join(d, "scripts", "test_tool.py"), "# a unit test; not installed\n")
    write(os.path.join(d, "scripts", "tool.test.mjs"), "// a unit test; not installed\n")
    tps = [{"name": "pending-skill", "source": "github:example/pending", "ref": None, "sha256": None,
            "note": "waiting for the owner"}]
    if tree_sha:
        tps.append({"name": "demo-skill", "source": "github:example/demo/skills/demo", "ref": "a" * 40,
                    "sha256": tree_sha, "license": "MIT"})
    pack = {
        "name": FIXTURE_PACK, "version": "1.0.0", "description": "test fixture", "kind": "extra",
        "requires": ["core"], "conflicts": [],
        "detect": {"files": ["fixture.cfg"], "package_deps": ["fixture-dep"], "package_json": {"type": "module"},
                   "ask": None},
        "facts": [
            {"name": "FIXTURE_KEY", "meaning": "m", "example": "K-1", "required": True, "ask": "Key?"},
            {"name": "FIXTURE_REF", "meaning": "m", "default": "{{TICKET_PREFIX}}", "required": True, "ask": "Ref?"}],
        "files": [{"src": "scripts/*", "dest": ".claude/scripts/"}],
        "hooks": [{"event": "PreToolUse", "matcher": "Bash",
                   "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/fixture.py", "timeout": 5}],
        "permissions": {"allow": ["mcp__demo__read"], "deny": ["mcp__demo__drop"]},
        "mcp": {"demo": {"type": "http", "url": "https://demo.invalid/mcp",
                         "headers": {"Authorization": "Bearer ${DEMO_TOKEN}"}},
                "demo2": {"type": "stdio", "command": "demo-mcp", "env": {"DEMO2_KEY": "${DEMO2_KEY}"}}},
        "env": [{"name": "DEMO_TOKEN", "purpose": "demo access", "how_to_get": "from the demo console"}],
        "owner_tasks": [{"task": "Create the demo project", "why": "the server needs one"}],
        "gitignore": [".fixture-cache/"],
        "third_party": tps,
    }
    write(os.path.join(d, "pack.json"), json.dumps(pack, indent=2))
    mpath = os.path.join(kit_root, "manifest.json")
    m = load_json(mpath)
    m["units"].append(f"packs/{FIXTURE_PACK}/pack.json")
    write(mpath, json.dumps(m, indent=2))


class Base(TempDirs, unittest.TestCase):
    def setUp(self):
        self.kit = KIT
        self.target = self.tmp()
        self.work = self.tmp()

    def answers(self, **kw):
        packs = kw.pop("packs", ())
        return write_answers(self.work, full_answers(self.kit, packs, **kw))

    def cli(self, cmd, answers=None, *extra):
        argv = [cmd, "--target", self.target, "--kit", self.kit]
        if answers:
            argv += ["--answers", answers]
        return run(argv + list(extra))

    def apply(self, answers, expect=0):
        rc, out, err = self.cli("apply", answers)
        self.assertEqual(rc, expect, out + err)
        return out, err

    def plan(self, answers):
        rc, out, err = self.cli("plan", answers, "--json")
        return json.loads(out)

    def rows(self, answers):
        return {r["dest"]: r for r in self.plan(answers)["files"]}

    def t(self, rel):
        return os.path.join(self.target, rel)

    def backups(self):
        return sorted(os.path.relpath(os.path.join(dp, f), self.target) for dp, _d, fs in os.walk(self.target)
                      for f in fs + _d if ".pre-agent-kit" in f)


class FreshInstall(Base):
    def test_fresh_empty_project(self):
        out, _ = self.apply(self.answers())
        for rel in ("CLAUDE.md", "CLAUDE.kit.md", "AGENTS.md", ".claude/settings.json", ".gitignore",
                    ".claude/agent-kit.lock.json", ".agents/claude-only.txt", "docs/agent/lessons.md",
                    "docs/workflow/ticket-ops.md", ".github/workflows/skill-link-check.yml",
                    ".github/scripts/check_skill_links.py"):
            self.assertTrue(os.path.isfile(self.t(rel)), rel)
        claude = read(self.t("CLAUDE.md"))
        self.assertIn(agent_kit.FACTS_START, claude)
        self.assertIn("@CLAUDE.kit.md", claude)
        self.assertIn("| `PROJECT_NAME` | Acme |", claude)
        self.assertNotRegex(claude, r"(?<!\$)\{\{[A-Z_]+\}\}")
        agents = read(self.t("AGENTS.md"))
        self.assertTrue(agents.startswith(agent_kit.AGENTS_START))
        self.assertIn("[CLAUDE.md](CLAUDE.md)", agents)
        self.assertEqual(self.backups(), [])
        wf = read(self.t(".github/workflows/skill-link-check.yml"))
        self.assertIn('"main"', wf)
        self.assertIn("${{ github.ref }}", wf)  # GitHub expressions are never treated as placeholders
        gi = read(self.t(".gitignore")).split("\n")
        for line in (".claude/state/", ".claude/handoffs/", ".claude/notify.env"):
            self.assertIn(line, gi)
        # Renamed-aside files stay visible to the owner. The one exception is the .mcp.json backup, which can hold
        # real credential values and must never be committed.
        self.assertFalse(any("pre-agent-kit" in l and not l.startswith("#") and not l.startswith(".mcp.json.")
                             for l in gi))
        self.assertIn(".mcp.json.pre-agent-kit", gi)
        lock = load_json(self.t(".claude/agent-kit.lock.json"))
        self.assertEqual(lock["kit"]["version"], load_json(os.path.join(KIT, "manifest.json"))["version"])
        for dest, e in lock["files"].items():
            self.assertTrue({"src", "unit", "sha256_as_installed", "project_owned"} <= set(e), dest)
        self.assertTrue(lock["files"]["docs/agent/lessons.md"]["project_owned"])

    def test_every_core_command_has_a_wrapper_or_claude_only_entry(self):
        self.apply(self.answers())
        only = set()
        for line in read(self.t(".agents/claude-only.txt")).split("\n"):
            name = line.split("#", 1)[0].strip()
            if name:
                only.add(name)
        cmds = [f[:-3] for f in os.listdir(os.path.join(KIT, "core", "commands")) if f.endswith(".md")]
        self.assertTrue(cmds)
        for c in cmds:
            with self.subTest(command=c):
                self.assertTrue(os.path.isfile(self.t(f".agents/skills/{c}/SKILL.md")) or c in only)
                if c not in only:
                    self.assertIn(f".claude/commands/{c}.md", read(self.t(f".agents/skills/{c}/SKILL.md")))

    def test_verify_passes_after_install(self):
        self.apply(self.answers())
        rc, out, err = self.cli("verify")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("check_skill_links.py --require-restated: passed", out)
        self.assertIn(".: npm test", out)

    def test_reapply_is_a_no_op(self):
        ans = self.answers()
        self.apply(ans)
        before = snapshot(self.target)
        out, _ = self.apply(ans)
        self.assertIn("Nothing written", out)
        self.assertEqual(snapshot(self.target), before)
        actions = {r["action"] for r in self.plan(ans)["files"]}
        self.assertLessEqual(actions, {"unchanged", "skip"})

    def test_missing_required_fact_refuses_and_writes_nothing(self):
        ans = full_answers(self.kit)
        del ans["facts"]["CRITICAL_DOMAIN"]
        rc, out, err = self.cli("apply", write_answers(self.work, ans))
        self.assertEqual(rc, 2)
        self.assertIn("required fact missing: CRITICAL_DOMAIN", err)
        self.assertEqual(os.listdir(self.target), [])

    def test_plan_is_read_only_and_markdown(self):
        rc, out, err = self.cli("plan", self.answers())
        self.assertEqual(rc, 0, out + err)
        self.assertIn("| Unit | Src | Dest | Action | Reason |", out)
        self.assertIn("## Unfilled required facts", out)
        self.assertEqual(os.listdir(self.target), [])

    def test_no_github_skips_the_workflow(self):
        ans = full_answers(self.kit)
        ans["options"]["github"] = False
        self.apply(write_answers(self.work, ans))
        self.assertFalse(os.path.exists(self.t(".github/workflows/skill-link-check.yml")))
        self.assertTrue(os.path.isfile(self.t(".github/scripts/check_skill_links.py")))

    def test_executable_bit_is_copied(self):
        self.apply(self.answers())
        lock = load_json(self.t(".claude/agent-kit.lock.json"))
        hooks = [d for d in lock["files"] if d.startswith(".claude/hooks/")]
        for dest in hooks:
            src = os.path.join(KIT, "core", lock["files"][dest]["src"])
            if os.stat(src).st_mode & stat.S_IXUSR:
                with self.subTest(dest=dest):
                    self.assertTrue(os.stat(self.t(dest)).st_mode & stat.S_IXUSR)

    def test_unit_tests_are_not_installed_by_globs(self):
        self.apply(self.answers())
        for dp, _d, files in os.walk(self.t(".claude")):
            for f in files:
                with self.subTest(file=f):
                    self.assertIsNone(agent_kit.TEST_FILE_RE.search(f))
        # Listed explicitly, so installed: the CI workflow runs them.
        self.assertTrue(os.path.isfile(self.t(".github/scripts/test_check_skill_links.py")))


class ExistingClaudeAndAgents(Base):
    CLAUDE = "# My project\n\nOur own rules.\n\n- Never deploy on Fridays. <!-- codex-restate -->\n\nTrailing text\n"
    AGENTS = "# Codex notes\n\nSome project text.\n"

    def test_existing_text_kept_byte_for_byte(self):
        write(self.t("CLAUDE.md"), self.CLAUDE)
        write(self.t("AGENTS.md"), self.AGENTS)
        ans = self.answers()
        rows = self.rows(ans)
        self.assertEqual(rows["CLAUDE.md"]["action"], "merge")
        self.assertEqual(rows["AGENTS.md"]["action"], "merge")
        self.apply(ans)
        claude, agents = read(self.t("CLAUDE.md")), read(self.t("AGENTS.md"))
        self.assertTrue(claude.startswith(self.CLAUDE))
        tail = claude[len(self.CLAUDE):]
        self.assertTrue(tail.strip().startswith(agent_kit.FACTS_START))
        self.assertTrue(tail.strip().endswith(agent_kit.FACTS_END))
        self.assertIn("@CLAUDE.kit.md", tail)
        self.assertTrue(agents.startswith(self.AGENTS))
        tail = agents[len(self.AGENTS):]
        self.assertTrue(tail.strip().startswith(agent_kit.AGENTS_START))
        self.assertTrue(tail.strip().endswith(agent_kit.AGENTS_END))
        self.assertIn("[CLAUDE.md](CLAUDE.md)", tail)  # names CLAUDE.md as the source of truth
        # The project's own tagged line is restated after the kit's.
        restated = agents.split(agent_kit.RESTATED_START)[1].split(agent_kit.RESTATED_END)[0].strip().split("\n")
        self.assertEqual(restated[-1], "- Never deploy on Fridays. <!-- codex-restate -->")
        self.assertEqual(self.backups(), [])
        rc, out, err = self.cli("verify")
        self.assertEqual(rc, 0, out + err)
        before = snapshot(self.target)
        self.apply(ans)
        self.assertEqual(snapshot(self.target), before)

    def test_facts_update_only_inside_markers(self):
        write(self.t("CLAUDE.md"), self.CLAUDE)
        ans = full_answers(self.kit)
        self.apply(write_answers(self.work, ans))
        ans["facts"]["PROJECT_NAME"] = "Renamed"
        self.apply(write_answers(self.work, ans))
        claude = read(self.t("CLAUDE.md"))
        self.assertTrue(claude.startswith(self.CLAUDE))
        self.assertIn("| `PROJECT_NAME` | Renamed |", claude)

    def test_hand_edited_facts_block_is_a_conflict(self):
        ans = self.answers()
        self.apply(ans)
        text = read(self.t("CLAUDE.md")).replace("| `UI_LANGUAGE` | en |", "| `UI_LANGUAGE` | fr |")
        write(self.t("CLAUDE.md"), text)
        a2 = full_answers(self.kit)
        a2["facts"]["PROJECT_NAME"] = "Renamed"
        p = write_answers(self.work, a2)
        self.assertEqual(self.rows(p)["CLAUDE.md"]["action"], "conflict")
        self.apply(p, expect=2)
        a2["resolutions"] = {"CLAUDE.md": "keep-theirs"}
        self.apply(write_answers(self.work, a2))
        self.assertIn("| `UI_LANGUAGE` | fr |", read(self.t("CLAUDE.md")))
        self.assertNotIn("Renamed", read(self.t("CLAUDE.md")))


class CommandConflict(Base):
    THEIRS = "---\ndescription: our own ship\n---\n\nOur ship steps.\n"

    def setUp(self):
        super().setUp()
        write(self.t(".claude/commands/ship.md"), self.THEIRS)
        self.kit_ship = read(os.path.join(KIT, "core", "commands", "ship.md"))

    def test_refused_without_resolution(self):
        ans = self.answers()
        row = self.rows(ans)[".claude/commands/ship.md"]
        self.assertEqual(row["action"], "conflict")
        self.assertIn("kit-renamed", row["options"])
        before = snapshot(self.target)
        rc, out, err = self.cli("apply", ans)
        self.assertEqual(rc, 2)
        self.assertIn("unresolved conflict: .claude/commands/ship.md", err)
        self.assertEqual(snapshot(self.target), before)

    def test_keep_theirs(self):
        ans = self.answers(resolutions={".claude/commands/ship.md": "keep-theirs"})
        self.apply(ans)
        self.assertEqual(read(self.t(".claude/commands/ship.md")), self.THEIRS)
        self.assertEqual(self.backups(), [])
        lock = load_json(self.t(".claude/agent-kit.lock.json"))
        self.assertEqual(lock["files"][".claude/commands/ship.md"]["status"], "kept-theirs")
        before = snapshot(self.target)
        self.apply(ans)
        self.assertEqual(snapshot(self.target), before)
        # Without the resolution, a re-run still respects the earlier choice.
        self.apply(self.answers())

    def test_take_kit(self):
        write(self.t(".claude/commands/ship.md.pre-agent-kit"), "an older backup\n")
        ans = self.answers(resolutions={".claude/commands/ship.md": "take-kit"})
        self.apply(ans)
        self.assertEqual(read(self.t(".claude/commands/ship.md")), self.kit_ship)
        self.assertEqual(read(self.t(".claude/commands/ship.md.pre-agent-kit")), "an older backup\n")
        self.assertEqual(read(self.t(".claude/commands/ship.md.pre-agent-kit.1")), self.THEIRS)
        before = snapshot(self.target)
        self.apply(ans)
        self.assertEqual(snapshot(self.target), before)

    def test_kit_renamed(self):
        ans = self.answers(resolutions={".claude/commands/ship.md": "kit-renamed"})
        self.apply(ans)
        self.assertEqual(read(self.t(".claude/commands/ship.md")), self.THEIRS)
        self.assertEqual(read(self.t(".claude/commands/ship-kit.md")), self.kit_ship)
        lock = load_json(self.t(".claude/agent-kit.lock.json"))
        self.assertEqual(lock["files"][".claude/commands/ship-kit.md"]["renamed_from"], ".claude/commands/ship.md")
        self.assertNotIn(".claude/commands/ship.md", lock["files"])
        before = snapshot(self.target)
        self.apply(self.answers())  # remembered from the lock
        self.assertEqual(snapshot(self.target), before)

    def test_kit_renamed_refused_for_non_commands(self):
        write(self.t(".claude/rules/security.md"), "ours\n")
        ans = self.answers(resolutions={".claude/commands/ship.md": "keep-theirs",
                                        ".claude/rules/security.md": "kit-renamed"})
        rc, out, err = self.cli("apply", ans)
        self.assertEqual(rc, 2)
        self.assertIn(".claude/rules/security.md", err)


class Upgrade(Base):
    def setUp(self):
        super().setUp()
        self.kit = copy_kit(os.path.join(self.tmp(), "kit"))

    def test_upgrade_updates_uncustomized_and_conflicts_on_customized(self):
        ans = self.answers()
        self.apply(ans)
        write(self.t(".claude/commands/test.md"), read(self.t(".claude/commands/test.md")) + "\nOur extra step.\n")
        for name in ("test.md", "verify.md"):
            p = os.path.join(self.kit, "core", "commands", name)
            write(p, read(p) + "\nA new kit line.\n")
        hist = os.path.join(self.kit, "core", "docs", "workflow", "history")
        orphan = sorted(f for f in os.listdir(hist) if f.endswith(".md"))[0]
        os.rename(os.path.join(hist, orphan), os.path.join(hist, orphan + ".retired"))
        mpath = os.path.join(self.kit, "manifest.json")
        m = load_json(mpath)
        old_version, m["version"] = m["version"], "1.0.0"
        write(mpath, json.dumps(m, indent=2))
        write(os.path.join(self.kit, "CHANGELOG.md"), "# Changelog\n\n## 1.0.0\n\n- New kit lines.\n\n"
              f"## {old_version}\n\n- Old entry.\n\n## 0.9.0\n\n- Ancient.\n")
        rows = self.rows(ans)
        self.assertEqual(rows[".claude/commands/test.md"]["action"], "conflict")
        self.assertEqual(rows[".claude/commands/verify.md"]["action"], "pull")
        self.assertIn("not customized", rows[".claude/commands/verify.md"]["reason"])
        self.assertEqual(rows[f"docs/workflow/history/{orphan}"]["action"], "orphaned")
        rc, out, err = self.cli("upgrade", ans)
        self.assertEqual(rc, 2, out + err)
        self.assertIn(".claude/commands/test.md", err)
        p = write_answers(self.work, full_answers(self.kit, resolutions={".claude/commands/test.md": "keep-theirs"}))
        rc, out, err = self.cli("upgrade", p)
        self.assertEqual(rc, 0, out + err)
        self.assertIn("A new kit line.", read(self.t(".claude/commands/verify.md")))
        self.assertIn("Our extra step.", read(self.t(".claude/commands/test.md")))
        self.assertNotIn("A new kit line.", read(self.t(".claude/commands/test.md")))
        self.assertTrue(os.path.isfile(self.t(f"docs/workflow/history/{orphan}")))
        self.assertIn("New kit lines.", out)
        self.assertNotIn("Old entry.", out)
        self.assertNotIn("Ancient.", out)
        lock = load_json(self.t(".claude/agent-kit.lock.json"))
        self.assertEqual(lock["kit"]["version"], "1.0.0")
        self.assertTrue(lock["files"][f"docs/workflow/history/{orphan}"]["orphaned"])

    def test_upgrade_without_answers_uses_the_lock(self):
        self.apply(self.answers())
        p = os.path.join(self.kit, "core", "commands", "verify.md")
        write(p, read(p) + "\nAnother kit line.\n")
        rc, out, err = run(["upgrade", "--target", self.target, "--kit", self.kit])
        self.assertEqual(rc, 0, out + err)
        self.assertIn("Another kit line.", read(self.t(".claude/commands/verify.md")))

    def test_upgrade_needs_a_lock(self):
        rc, out, err = self.cli("upgrade", self.answers())
        self.assertEqual(rc, 2)
        self.assertIn("lock", err)

    def test_project_owned_files_never_touched(self):
        self.apply(self.answers())
        write(self.t("docs/agent/lessons.md"), "our lessons\n")
        p = os.path.join(self.kit, "core", "project-docs", "lessons.md.tmpl")
        write(p, read(p) + "\nNew kit seed.\n")
        rc, out, err = run(["upgrade", "--target", self.target, "--kit", self.kit])
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(read(self.t("docs/agent/lessons.md")), "our lessons\n")


class SettingsMerge(Base):
    def test_foreign_hook_and_values_kept(self):
        theirs = {"env": {"SOME_SETTING": "value-kept-private"},
                  "permissions": {"allow": ["Bash(ls *)"], "deny": ["Bash(curl *)"]},
                  "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command",
                                                                          "command": "echo foreign"}]}],
                            "Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}]}}
        write(self.t(".claude/settings.json"), json.dumps(theirs, indent=2))
        out, err = self.apply(self.answers())
        self.assertNotIn("value-kept-private", out + err)
        new = load_json(self.t(".claude/settings.json"))
        self.assertEqual(new["env"], theirs["env"])
        self.assertEqual(new["permissions"]["allow"][0], "Bash(ls *)")
        self.assertEqual(new["permissions"]["deny"][0], "Bash(curl *)")
        self.assertEqual(new["hooks"]["PreToolUse"][0], theirs["hooks"]["PreToolUse"][0])
        self.assertEqual(new["hooks"]["Stop"], theirs["hooks"]["Stop"])
        cmds = [h["command"] for g in new["hooks"]["PreToolUse"] for h in g["hooks"]]
        self.assertTrue(any("block-main-branch" in c for c in cmds))
        self.assertEqual(len(cmds), len(set(cmds)))
        before = snapshot(self.target)
        self.apply(self.answers())
        self.assertEqual(snapshot(self.target), before)

    def test_invalid_settings_json_refused(self):
        write(self.t(".claude/settings.json"), "{not json")
        rc, out, err = self.cli("apply", self.answers())
        self.assertEqual(rc, 2)
        self.assertEqual(read(self.t(".claude/settings.json")), "{not json")


class PackFeatures(Base):
    """Fixture pack in a kit copy: MCP merge, hooks, gitignore, owner tasks, defaults, exec bit, third-party."""

    def setUp(self):
        super().setUp()
        self.kit = copy_kit(os.path.join(self.tmp(), "kit"))
        self.tree = os.path.join(self.tmp(), "fetched")
        write(os.path.join(self.tree, "SKILL.md"), "---\nname: demo\n---\nDemo skill.\n")
        write(os.path.join(self.tree, "ref", "notes.md"), "notes\n")
        sha = agent_kit._hash_tree_module(self.kit).hash_tree(self.tree)
        add_fixture_pack(self.kit, sha)

    def test_existing_mcp_server_untouched_and_mapping(self):
        theirs = {"mcpServers": {"demo": {"type": "stdio", "command": "their-demo", "env": {"K": "secret-xyz"}},
                                 "mine": {"type": "stdio", "command": "x"}}}
        write(self.t(".mcp.json"), json.dumps(theirs, indent=2))
        ans = full_answers(self.kit, (FIXTURE_PACK,), mcp_map={"demo2": "mine"})
        ans["facts"]["TICKET_SYSTEM"] = "none"  # no ticket pack, so no atlassian server is added
        ans = write_answers(self.work, ans)
        plan = self.plan(ans)
        mcp = {m["server"]: m for m in plan["mcp"]}
        self.assertEqual(mcp["demo"]["action"], "kept")
        self.assertEqual(mcp["demo2"]["action"], "mapped")
        rc, md, _ = self.cli("plan", ans)
        self.assertNotIn("secret-xyz", md)
        out, err = self.apply(ans)
        self.assertNotIn("secret-xyz", out + err)
        self.assertEqual(load_json(self.t(".mcp.json")), theirs)

    def test_new_mcp_server_added_with_env_refs(self):
        ans = self.answers(packs=(FIXTURE_PACK,))
        rc, md, _ = self.cli("plan", ans)
        self.assertIn("DEMO_TOKEN", md)
        self.assertIn("Create the demo project", md)
        self.assertIn("pin pending", md)
        out, _ = self.apply(ans)
        self.assertIn("Owner task", out)
        servers = load_json(self.t(".mcp.json"))["mcpServers"]
        self.assertEqual(servers["demo"]["headers"]["Authorization"], "Bearer ${DEMO_TOKEN}")
        self.assertEqual(servers["demo2"]["env"]["DEMO2_KEY"], "${DEMO2_KEY}")
        settings = load_json(self.t(".claude/settings.json"))
        self.assertIn("mcp__demo__read", settings["permissions"]["allow"])
        self.assertIn("mcp__demo__drop", settings["permissions"]["deny"])
        self.assertIn(".fixture-cache/", read(self.t(".gitignore")).split("\n"))
        packmd = read(self.t(f".claude/packs/{FIXTURE_PACK}.md"))
        self.assertIn("| `FIXTURE_KEY` | K-1 |", packmd)
        self.assertIn("| `FIXTURE_REF` | ABC |", packmd)  # default filled from TICKET_PREFIX
        self.assertTrue(os.stat(self.t(".claude/scripts/tool")).st_mode & stat.S_IXUSR)
        self.assertFalse(os.path.exists(self.t(".claude/scripts/test_tool.py")))
        self.assertFalse(os.path.exists(self.t(".claude/scripts/tool.test.mjs")))
        before = snapshot(self.target)
        self.apply(ans)
        self.assertEqual(snapshot(self.target), before)

    def test_missing_pack_fact_refused(self):
        ans = full_answers(self.kit, (FIXTURE_PACK,))
        del ans["facts"]["FIXTURE_KEY"]
        rc, out, err = self.cli("apply", write_answers(self.work, ans))
        self.assertEqual(rc, 2)
        self.assertIn("FIXTURE_KEY", err)

    def test_unknown_pack_refused(self):
        rc, out, err = self.cli("apply", self.answers(packs=("no-such-pack",)))
        self.assertEqual(rc, 2)
        self.assertIn("no-such-pack", err)

    def test_third_party_verified_then_copied(self):
        self.apply(self.answers(packs=(FIXTURE_PACK,)))
        rc, out, err = self.cli("third-party", None, "--name", "pending-skill", "--from", self.tree)
        self.assertEqual(rc, 2)
        self.assertIn("pending", err)
        bad = os.path.join(self.tmp(), "bad")
        write(os.path.join(bad, "SKILL.md"), "tampered\n")
        rc, out, err = self.cli("third-party", None, "--name", "demo-skill", "--from", bad)
        self.assertEqual(rc, 2)
        self.assertIn("doesn't match the pin", err)
        self.assertFalse(os.path.exists(self.t(".claude/skills/demo-skill")))
        rc, out, err = self.cli("third-party", None, "--name", "demo-skill", "--from", self.tree)
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(read(self.t(".claude/skills/demo-skill/ref/notes.md")), "notes\n")
        lock = load_json(self.t(".claude/agent-kit.lock.json"))
        self.assertEqual(lock["third_party"]["demo-skill"]["ref"], "a" * 40)
        before = snapshot(self.target)
        rc, out, err = self.cli("third-party", None, "--name", "demo-skill", "--from", self.tree)
        self.assertEqual(snapshot(self.target), before)
        self.apply(self.answers(packs=(FIXTURE_PACK,)))  # apply keeps the third-party record
        self.assertIn("demo-skill", load_json(self.t(".claude/agent-kit.lock.json"))["third_party"])
        rc, out, err = self.cli("verify")
        self.assertEqual(rc, 0, out + err)
        write(self.t(".claude/skills/demo-skill/SKILL.md"), "edited\n")
        rc, out, err = self.cli("verify")
        self.assertEqual(rc, 1)
        self.assertIn("demo-skill", out)


class Scan(Base):
    def test_scan_reads_signals_and_never_prints_secrets(self):
        write(self.t("package.json"), json.dumps({"dependencies": {"fixture-dep": "1"}, "devDependencies": {"x": "1"}}))
        write(self.t("apps/web/package.json"), json.dumps({"type": "module", "dependencies": {"ws-dep": "1"}}))
        write(self.t("node_modules/z/package.json"), json.dumps({"dependencies": {"hidden-dep": "1"}}))
        write(self.t("package-lock.json"), "{}")
        write(self.t(".mcp.json"), json.dumps({"mcpServers": {"alpha": {"env": {"TOKEN": "tok-should-not-print"}}}}))
        write(self.t("CLAUDE.md"), "# x\n")
        write(self.t(".claude/commands/foo.md"), "x\n")
        try:
            subprocess.run(["git", "init", "-q", "-b", "trunk", self.target], check=True, capture_output=True)
            subprocess.run(["git", "-C", self.target, "remote", "add", "origin",
                            "https://user:tok-in-url@github.com/acme/app.git"], check=True, capture_output=True)
            has_git = True
        except (OSError, subprocess.CalledProcessError):
            has_git = False
        kit = copy_kit(os.path.join(self.tmp(), "kit"))
        add_fixture_pack(kit)
        rc, out, err = run(["scan", "--target", self.target, "--kit", kit])
        self.assertEqual(rc, 0, err)
        self.assertNotIn("tok-should-not-print", out)
        self.assertNotIn("tok-in-url", out)
        data = json.loads(out)
        self.assertEqual(data["existing"][".mcp.json servers"], ["alpha"])
        self.assertTrue(data["existing"]["CLAUDE.md"])
        self.assertEqual(data["existing"][".claude/commands"], ["foo.md"])
        self.assertIn("package-lock.json", data["lock_files"])
        self.assertIn("fixture-dep", data["package_deps"])
        self.assertIn("ws-dep", data["package_deps"])
        self.assertNotIn("hidden-dep", data["package_deps"])
        fx = next(p for p in data["packs"] if p["name"] == FIXTURE_PACK)
        self.assertTrue(fx["matched"])
        self.assertIn('apps/web/package.json type="module"', fx["signals"])
        if has_git:
            self.assertEqual(data["git"]["remote_host"], "github.com")
            self.assertEqual(data["git"]["default_branch"] or data["git"]["current_branch"], "trunk")
            self.assertTrue(data["github"])


class AllPacks(Base):
    """Install core + every shipped pack that can go together, then verify."""

    def test_install_every_pack(self):
        kit = agent_kit.Kit(KIT)
        packs = [n for n in sorted(kit.units) if n != "core"]
        if not packs:
            self.skipTest("no packs/*/pack.json in the kit yet")
        chosen = []
        for p in packs:
            if any(c in chosen for c in kit.units[p].get("conflicts", [])):
                continue
            chosen.append(p)
        ans = self.answers(packs=tuple(chosen))
        out, _ = self.apply(ans)
        rc, vout, verr = self.cli("verify")
        self.assertEqual(rc, 0, vout + verr)
        before = snapshot(self.target)
        self.apply(ans)
        self.assertEqual(snapshot(self.target), before)
        for p in chosen:
            if os.path.isfile(os.path.join(KIT, "packs", p, "pack.md")):
                self.assertTrue(os.path.isfile(self.t(f".claude/packs/{p}.md")), p)


if __name__ == "__main__":
    unittest.main()
