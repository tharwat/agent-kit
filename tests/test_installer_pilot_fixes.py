# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Installer fixes found by the pilots (I1-I11). Temporary targets and kit copies only."""
import json
import os
import shutil
import subprocess
import unittest

from kit_testlib import KIT, agent_kit, copy_kit, full_answers, load_json, read, run, snapshot, write, write_answers
from test_installer import FIXTURE_PACK, Base, add_fixture_pack

LOCK = ".claude/agent-kit.lock.json"


def edit_fixture(kit_root, fn):
    path = os.path.join(kit_root, "packs", FIXTURE_PACK, "pack.json")
    data = load_json(path)
    fn(data)
    write(path, json.dumps(data, indent=2))


class KitRenamedSkill(Base):
    """I1: a kit-renamed skill is remembered, its name: is rewritten, and nothing is reported orphaned."""
    THEIRS = "---\nname: worktree\ndescription: our own worktree skill\n---\n\nOurs.\n"
    SKILL = ".claude/skills/worktree/SKILL.md"
    RENAMED = ".claude/skills/worktree-kit/SKILL.md"

    def setUp(self):
        super().setUp()
        self.kit = copy_kit(os.path.join(self.tmp(), "kit"))
        write(self.t(self.SKILL), self.THEIRS)

    def test_renamed_skill_lock_name_and_upgrade(self):
        ans = self.answers(packs=("worktrees",), resolutions={self.SKILL: "kit-renamed"})
        out, err = self.apply(ans)
        self.assertNotIn("is unused", out + err)
        self.assertEqual(read(self.t(self.SKILL)), self.THEIRS)
        installed = read(self.t(self.RENAMED))
        self.assertIn("\nname: worktree-kit\n", installed)
        self.assertNotIn("\nname: worktree\n", installed)
        lock = load_json(self.t(LOCK))
        self.assertEqual(lock["files"][self.RENAMED]["renamed_from"], self.SKILL)
        self.assertNotIn(self.SKILL, lock["files"])
        before = snapshot(self.target)
        self.apply(self.answers(packs=("worktrees",)))  # remembered from the lock, no resolution needed
        self.assertEqual(snapshot(self.target), before)
        # The kit changes the skill: an upgrade updates the -kit copy; no conflict, no orphan.
        src = os.path.join(self.kit, "packs", "worktrees", "skills", "worktree", "SKILL.md")
        write(src, read(src) + "\nA new kit line.\n")
        rows = self.rows(self.answers(packs=("worktrees",)))
        self.assertEqual(rows[self.RENAMED]["action"], "pull")
        self.assertNotIn(self.SKILL, rows)
        self.assertFalse([d for d, r in rows.items() if r["action"] in ("orphaned", "conflict")])
        rc, out, err = run(["upgrade", "--target", self.target, "--kit", self.kit])
        self.assertEqual(rc, 0, out + err)
        self.assertIn("A new kit line.", read(self.t(self.RENAMED)))
        self.assertIn("\nname: worktree-kit\n", read(self.t(self.RENAMED)))
        self.assertEqual(read(self.t(self.SKILL)), self.THEIRS)

    def test_lock_without_renamed_from_is_still_understood(self):
        self.apply(self.answers(packs=("worktrees",), resolutions={self.SKILL: "kit-renamed"}))
        lock = load_json(self.t(LOCK))
        del lock["files"][self.RENAMED]["renamed_from"]  # a lock written by the pilot-era installer
        write(self.t(LOCK), json.dumps(lock, indent=2))
        rows = self.rows(self.answers(packs=("worktrees",)))
        self.assertEqual(rows[self.RENAMED]["action"], "unchanged")
        self.assertNotIn(self.SKILL, rows)

    def test_rename_frontmatter_only_touches_the_name_line(self):
        src = b"---\nname: 'ship'\ndescription: name: ship\n---\nname: ship\n"
        got = agent_kit.rename_frontmatter(src, ".claude/commands/ship.md", ".claude/commands/ship-kit.md")
        self.assertEqual(got, b"---\nname: ship-kit\ndescription: name: ship\n---\nname: ship\n")
        other = b"---\nname: something-else\n---\n"
        self.assertEqual(agent_kit.rename_frontmatter(other, ".claude/skills/a/SKILL.md", ".claude/skills/a-kit/SKILL.md"),
                         other)


class FactsWithoutDefault(Base):
    """I2: a fact with no answer and no default is refused, required or not, unless answered "none"."""

    def setUp(self):
        super().setUp()
        self.kit = copy_kit(os.path.join(self.tmp(), "kit"))
        add_fixture_pack(self.kit)
        edit_fixture(self.kit, lambda d: d["facts"].append(
            {"name": "FIXTURE_DIR", "meaning": "a directory", "required": False, "ask": "Which directory?"}))

    def test_optional_fact_without_default_is_refused(self):
        ans = full_answers(self.kit, (FIXTURE_PACK,))
        del ans["facts"]["FIXTURE_DIR"]
        p = write_answers(self.work, ans)
        plan = self.plan(p)
        self.assertIn("FIXTURE_DIR", [m["name"] for m in plan["missing_facts"]])
        rc, out, err = self.cli("apply", p)
        self.assertEqual(rc, 2)
        self.assertIn("fact missing: FIXTURE_DIR", err)
        self.assertEqual(os.listdir(self.target), [])

    def test_explicit_none_is_accepted(self):
        ans = full_answers(self.kit, (FIXTURE_PACK,))
        ans["facts"]["FIXTURE_DIR"] = "none"
        self.apply(write_answers(self.work, ans))
        self.assertEqual(load_json(self.t(LOCK))["answers"]["facts"]["FIXTURE_DIR"], "none")


class ClaudeOnlyCommands(Base):
    """I3: plan predicts commands with no description:, answers.claude_only writes them, apply exits 0."""
    NODESC = "# Our command with no frontmatter\n"

    def setUp(self):
        super().setUp()
        write(self.t(".claude/commands/legacy.md"), self.NODESC)

    def test_plan_predicts_and_apply_warns_without_failing(self):
        ans = self.answers()
        plan = self.plan(ans)
        self.assertEqual(plan["commands_without_description"], ["legacy"])
        rc, md, _ = self.cli("plan", ans)
        self.assertIn("## Commands with no Codex skill", md)
        self.assertIn('{"claude_only": ["legacy"]}', md)
        out, err = self.apply(ans)  # expects exit 0
        self.assertIn("make_skill_links exited", out)
        self.assertTrue(os.path.isfile(self.t(LOCK)))

    def test_claude_only_answer_is_written_and_remembered(self):
        ans = self.answers(claude_only=["legacy"])
        self.assertEqual(self.plan(ans)["commands_without_description"], [])
        out, err = self.apply(ans)
        self.assertNotIn("make_skill_links exited", out)
        names = [l.split("#", 1)[0].strip() for l in read(self.t(".agents/claude-only.txt")).splitlines()]
        self.assertIn("legacy", names)
        self.assertFalse(os.path.exists(self.t(".agents/skills/legacy")))
        self.assertEqual(load_json(self.t(LOCK))["answers"]["claude_only"], ["legacy"])
        before = snapshot(self.target)
        self.apply(self.answers())  # the lock remembers claude_only
        self.assertEqual(snapshot(self.target), before)
        rc, out, err = self.cli("verify")
        self.assertEqual(rc, 0, out + err)

    def test_claude_only_appends_to_an_existing_project_file(self):
        self.apply(self.answers())
        text = read(self.t(".agents/claude-only.txt"))
        self.apply(self.answers(claude_only=["legacy"]))
        new = read(self.t(".agents/claude-only.txt"))
        self.assertTrue(new.startswith(text))
        self.assertIn("legacy", new[len(text):])

    def test_bad_claude_only_answer_refused(self):
        rc, out, err = self.cli("plan", self.answers(claude_only="legacy"))
        self.assertEqual(rc, 2)
        self.assertIn("claude_only", err)


class McpUpgrade(Base):
    """I4: kit-installed servers are recorded with a hash; unchanged ones follow the kit, edited ones conflict."""

    def setUp(self):
        super().setUp()
        self.kit = copy_kit(os.path.join(self.tmp(), "kit"))
        add_fixture_pack(self.kit)
        edit_fixture(self.kit, lambda d: d["mcp"]["demo"].update(url="https://demo.invalid/mcp?ref={{FIXTURE_KEY}}"))
        ans = full_answers(self.kit, (FIXTURE_PACK,))
        ans["facts"]["TICKET_SYSTEM"] = "none"  # only the fixture's servers
        self.ans = write_answers(self.work, ans)

    def change_kit_url(self, url):
        edit_fixture(self.kit, lambda d: d["mcp"]["demo"].update(url=url))

    def test_install_records_servers_and_fills_facts(self):
        self.apply(self.ans)
        servers = load_json(self.t(".mcp.json"))["mcpServers"]
        self.assertEqual(servers["demo"]["url"], "https://demo.invalid/mcp?ref=K-1")
        rec = load_json(self.t(LOCK))["files"][".mcp.json"]["servers"]
        self.assertEqual(set(rec), {"demo", "demo2"})
        self.assertEqual(rec["demo"]["sha256"], agent_kit.entry_sha(servers["demo"]))

    def test_unchanged_server_is_updated_on_upgrade(self):
        self.apply(self.ans)
        self.change_kit_url("https://demo.invalid/v2")
        mcp = {m["server"]: m for m in self.plan(self.ans)["mcp"]}
        self.assertEqual(mcp["demo"]["action"], "update")
        self.assertEqual(mcp["demo2"]["action"], "unchanged")
        self.apply(self.ans)
        self.assertEqual(load_json(self.t(".mcp.json"))["mcpServers"]["demo"]["url"], "https://demo.invalid/v2")
        before = snapshot(self.target)
        self.apply(self.ans)
        self.assertEqual(snapshot(self.target), before)

    def test_edited_server_is_a_conflict(self):
        self.apply(self.ans)
        data = load_json(self.t(".mcp.json"))
        data["mcpServers"]["demo"]["url"] = "https://edited.invalid/secret-path-xyz"
        write(self.t(".mcp.json"), json.dumps(data, indent=2))
        self.change_kit_url("https://demo.invalid/v2")
        plan = self.plan(self.ans)
        self.assertIn(".mcp.json#demo", plan["unresolved_conflicts"])
        self.assertIn(".mcp.json#demo", plan["resolutions_template"])
        rc, out, err = self.cli("apply", self.ans)
        self.assertEqual(rc, 2)
        self.assertIn(".mcp.json#demo", err)
        self.assertNotIn("secret-path-xyz", out + err)
        keep = self.answers(packs=(FIXTURE_PACK,), resolutions={".mcp.json#demo": "keep-theirs"})
        out, err = self.apply(keep)
        self.assertNotIn("is unused", out + err)
        self.assertEqual(load_json(self.t(".mcp.json"))["mcpServers"]["demo"]["url"],
                         "https://edited.invalid/secret-path-xyz")
        mcp = {m["server"]: m for m in self.plan(self.ans)["mcp"]}
        self.assertEqual(mcp["demo"]["action"], "kept")  # remembered until the kit's entry changes again
        take = self.answers(packs=(FIXTURE_PACK,), resolutions={".mcp.json#demo": "take-kit"})
        self.change_kit_url("https://demo.invalid/v3")
        self.apply(take)
        self.assertEqual(load_json(self.t(".mcp.json"))["mcpServers"]["demo"]["url"], "https://demo.invalid/v3")
        self.assertIn(".mcp.json.pre-agent-kit", self.backups())

    def test_project_server_never_installed_by_kit_is_left_alone(self):
        theirs = {"mcpServers": {"demo": {"type": "stdio", "command": "their-demo"}}}
        write(self.t(".mcp.json"), json.dumps(theirs, indent=2))
        self.apply(self.ans)
        mcp = {m["server"]: m for m in self.plan(self.ans)["mcp"]}
        self.assertEqual(mcp["demo"]["action"], "kept")
        self.assertIn("never installed", mcp["demo"]["reason"])
        self.assertNotIn("demo", load_json(self.t(LOCK))["files"][".mcp.json"].get("servers", {}))
        self.change_kit_url("https://demo.invalid/v2")
        self.apply(self.ans)
        self.assertEqual(load_json(self.t(".mcp.json"))["mcpServers"]["demo"], theirs["mcpServers"]["demo"])


class OwnerTasks(Base):
    """I5: setup owner tasks from every chosen unit appear in plan and in the apply summary, facts filled."""

    def setUp(self):
        super().setUp()
        self.kit = copy_kit(os.path.join(self.tmp(), "kit"))
        add_fixture_pack(self.kit)
        edit_fixture(self.kit, lambda d: d["owner_tasks"].append(
            {"task": "Create the ticket {{FIXTURE_KEY}} if it doesn't exist", "why": "for {{TICKET_PREFIX}}"}))

    def test_owner_tasks_listed(self):
        ans = self.answers(packs=(FIXTURE_PACK,))
        rc, md, _ = self.cli("plan", ans)
        setup = md.split("## Owner tasks: setup", 1)[1].split("\n## ", 1)[0]
        self.assertNotIn("None.", setup)
        self.assertIn("Create the demo project", setup)
        self.assertIn("Create the ticket K-1 if it doesn't exist", setup)
        self.assertIn("for ABC", setup)
        out, _ = self.apply(ans)
        self.assertIn("Owner tasks (setup):", out)
        self.assertIn("Create the ticket K-1", out)


class KitCommitDirty(Base):
    """I6: the lock records the kit commit, plus -dirty when the kit clone has uncommitted changes."""

    def test_dirty_suffix(self):
        if not shutil.which("git"):
            self.skipTest("git not available")
        kit = copy_kit(os.path.join(self.tmp(), "kit"))
        git = ["git", "-C", kit, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c",
               "commit.gpgsign=false"]
        for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "x"]):
            subprocess.run(git + cmd, check=True, capture_output=True)
        head = subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(agent_kit.Kit(kit).commit, head)
        write(os.path.join(kit, "core", "commands", "verify.md"),
              read(os.path.join(kit, "core", "commands", "verify.md")) + "\nlocal edit\n")
        self.kit = kit
        self.apply(self.answers())
        self.assertEqual(load_json(self.t(LOCK))["kit"]["commit"], head + "-dirty")
        rc, md, _ = self.cli("plan", self.answers())
        self.assertIn(f"commit {head[:12]}-dirty", md)


class ScanSignals(Base):
    """I7: scripts, type, eas profiles, test runner, origin, and suggested facts."""

    def test_scan_reports_and_suggests(self):
        write(self.t("package.json"), json.dumps({
            "type": "module", "devDependencies": {"jest": "29"},
            "scripts": {"test": "jest", "start": "expo start", "deploy": "API_TOKEN=abc123 eas deploy"}}))
        write(self.t("yarn.lock"), "")
        write(self.t("eas.json"), json.dumps({"build": {
            "development": {"developmentClient": True}, "preview": {"distribution": "internal"},
            "preview-simulator": {"ios": {"simulator": True}}, "production": {"env": {"SECRET": "zzz-hidden"}}}}))
        try:
            subprocess.run(["git", "init", "-q", self.target], check=True, capture_output=True)
            subprocess.run(["git", "-C", self.target, "remote", "add", "origin", "git@github.com:acme/app.git"],
                           check=True, capture_output=True)
            has_git = True
        except (OSError, subprocess.CalledProcessError):
            has_git = False
        rc, out, err = self.cli("scan")
        self.assertEqual(rc, 0, err)
        self.assertNotIn("abc123", out)
        self.assertNotIn("zzz-hidden", out)
        data = json.loads(out)
        pkg = data["packages"][0]
        self.assertEqual((pkg["path"], pkg["type"]), ("package.json", "module"))
        self.assertEqual(pkg["scripts"]["test"], "jest")
        self.assertEqual(pkg["scripts"]["deploy"], "API_TOKEN=<redacted> eas deploy")
        self.assertEqual([p["name"] for p in data["eas"][0]["build_profiles"]],
                         ["development", "preview", "preview-simulator", "production"])
        self.assertEqual(data["test_runner"]["guess"], "jest")
        sf = data["suggested_facts"]
        self.assertEqual(sf["TEST_COMMANDS"], [".: yarn test"])
        self.assertEqual(sf["DEV_SERVER_COMMAND"], "yarn start")
        self.assertNotIn("TEST_FRAMEWORK", sf)  # suggested only with a tsconfig (it is a typescript-pack fact)
        self.assertEqual(sf["SYNTAX_CHECK_COMMAND"], "node --check <file>")  # "type": "module", no tsconfig
        self.assertEqual((sf["EAS_PROFILE_QA"], sf["EAS_PROFILE_SIM"], sf["EAS_PROFILE_PROD"]),
                         ("preview", "preview-simulator", "production"))
        if has_git:
            self.assertTrue(data["git"]["has_origin"])
            self.assertTrue(data["git"]["origin_is_github"])

    def test_no_runner_and_no_origin(self):
        write(self.t("package.json"), json.dumps({"scripts": {"test": "echo \"Error: no test specified\" && exit 1",
                                                              "dev": "node --watch server.mjs"}}))
        data = json.loads(self.cli("scan")[1])
        self.assertIsNone(data["test_runner"]["guess"])
        self.assertNotIn("TEST_COMMANDS", data["suggested_facts"])
        self.assertNotIn("TEST_FRAMEWORK", data["suggested_facts"])
        self.assertEqual(data["suggested_facts"]["DEV_SERVER_COMMAND"], "npm run dev")
        self.assertFalse(data["git"]["has_origin"])
        self.assertFalse(data["git"]["origin_is_github"])

    def test_node_test_and_pytest_guesses(self):
        write(self.t("package.json"), json.dumps({"scripts": {"test": "node --test test/"}}))
        self.assertEqual(json.loads(self.cli("scan")[1])["test_runner"]["guess"], "node --test")
        other = self.tmp()
        write(os.path.join(other, "pyproject.toml"), "[tool.pytest.ini_options]\n")
        data = json.loads(run(["scan", "--target", other, "--kit", self.kit])[1])
        self.assertEqual(data["test_runner"]["guess"], "pytest")
        self.assertEqual(data["suggested_facts"]["TEST_COMMANDS"], [".: python3 -m pytest"])


class RuleLoadingTable(Base):
    """I8: AGENTS.md's Rule loading table lists every installed rule with its paths:, inside its own markers."""

    def test_table_lists_pack_and_project_rules(self):
        write(self.t(".claude/rules/own.md"), "---\npaths:\n  - \"src/**/*.{ts,tsx}\"\n  - 'lib/**'\n---\n# own\n")
        self.apply(self.answers(packs=("typescript",)))
        agents = read(self.t("AGENTS.md"))
        table = agents.split(agent_kit.RULES_START, 1)[1].split(agent_kit.RULES_END, 1)[0]
        self.assertIn("| `.claude/rules/security.md` | Any task |", table)
        self.assertIn("| `.claude/rules/typescript.md` | Files matching `**/*.{ts,tsx}` |", table)
        self.assertIn("| `.claude/rules/own.md` | Files matching `src/**/*.{ts,tsx}`, `lib/**` |", table)
        self.assertNotIn("<pack rule>", table)
        rc, out, err = self.cli("verify")
        self.assertEqual(rc, 0, out + err)
        before = snapshot(self.target)
        self.apply(self.answers(packs=("typescript",)))
        self.assertEqual(snapshot(self.target), before)
        # A pack added later shows up on the next run, as an update inside the kit's markers.
        self.apply(self.answers(packs=("typescript", "supabase")))
        self.assertIn("`.claude/rules/database.md` | Files matching `supabase/**`", read(self.t("AGENTS.md")))

    def test_frontmatter_paths_forms(self):
        fp = agent_kit.frontmatter_paths
        self.assertEqual(fp("---\npaths: \"a/**\"\n---\n"), ["a/**"])
        self.assertEqual(fp("---\npaths: [\"a/**\", 'b/*.{x,y}']\n---\n"), ["a/**", "b/*.{x,y}"])
        self.assertEqual(fp("---\npaths:\n  - a\n  - \"b\"\nother: 1\n---\n"), ["a", "b"])
        self.assertEqual(fp("# no frontmatter\n"), [])


class PathsDotSlash(Base):
    """A directory fact of "." must not leave "./**" in a rule's paths: frontmatter."""

    def test_normalize_forms(self):
        n = agent_kit.normalize_frontmatter_paths
        self.assertEqual(n('---\npaths:\n  - "./**"\n  - ./src/**\n  - ./**\n  - "lib/**"\n---\nbody ./x\n'),
                         '---\npaths:\n  - "**"\n  - src/**\n  - "**"\n  - "lib/**"\n---\nbody ./x\n')
        self.assertEqual(n('---\npaths: ["./**", "./a/*", b]\n---\n'), '---\npaths: ["**", "a/*", b]\n---\n')
        self.assertEqual(n("---\npaths: ./**\n---\n"), '---\npaths: "**"\n---\n')
        self.assertEqual(n("---\nother: ./x\n---\n./y\n"), "---\nother: ./x\n---\n./y\n")

    def test_expo_rule_with_mobile_dir_dot(self):
        ans = full_answers(self.kit, ("expo-mobile",))
        ans["facts"]["MOBILE_DIR"] = "."
        self.apply(write_answers(self.work, ans))
        rule = read(self.t(".claude/rules/mobile.md"))
        self.assertEqual(agent_kit.frontmatter_paths(rule)[:1], ["**"])
        self.assertNotIn("./**", rule.split("\n---", 1)[0])
        before = snapshot(self.target)
        self.apply(write_answers(self.work, ans))
        self.assertEqual(snapshot(self.target), before)


class GitignorePycache(Base):
    """I9: installed Python tests create __pycache__/, so it is ignored."""

    def test_pycache_ignored(self):
        self.apply(self.answers())
        self.assertIn("__pycache__/", read(self.t(".gitignore")).split("\n"))


class ResolutionsTemplate(Base):
    """I10: plan prints a ready-to-fill resolutions JSON for every conflict; refusal repeats it."""

    def test_template_in_plan_and_refusal(self):
        write(self.t(".claude/commands/ship.md"), "---\ndescription: ours\n---\nOurs.\n")
        write(self.t(".claude/rules/security.md"), "ours\n")
        ans = self.answers()
        rc, md, _ = self.cli("plan", ans)
        block = md.split("```json\n", 1)[1].split("```", 1)[0]
        tmpl = json.loads(block)["resolutions"]
        self.assertEqual(tmpl[".claude/commands/ship.md"], "keep-theirs | take-kit | kit-renamed")
        self.assertEqual(tmpl[".claude/rules/security.md"], "keep-theirs | take-kit")
        self.assertEqual(self.plan(ans)["resolutions_template"], tmpl)
        rc, out, err = self.cli("apply", ans)
        self.assertEqual(rc, 2)
        self.assertIn("all-or-nothing", err)
        self.assertIn('"resolutions"', err)


class AgentsNoteInClaudeMd(Base):
    """I11: a new CLAUDE.md points at a pre-existing AGENTS.md's own rules."""

    def test_note_when_agents_md_has_project_text(self):
        write(self.t("AGENTS.md"), "# Codex notes\n\nRun the linter before every commit.\n")
        ans = self.answers()
        self.apply(ans)
        claude = read(self.t("CLAUDE.md"))
        block = claude.split(agent_kit.FACTS_START, 1)[1].split(agent_kit.FACTS_END, 1)[0]
        self.assertIn(agent_kit.AGENTS_NOTE, block)
        self.assertEqual(claude.count(agent_kit.AGENTS_NOTE), 1)
        self.assertTrue(load_json(self.t(LOCK))["files"]["CLAUDE.md"]["agents_note"])
        before = snapshot(self.target)
        self.apply(ans)
        self.assertEqual(snapshot(self.target), before)
        a2 = full_answers(self.kit)
        a2["facts"]["PROJECT_NAME"] = "Renamed"
        self.apply(write_answers(self.work, a2))
        self.assertIn(agent_kit.AGENTS_NOTE, read(self.t("CLAUDE.md")))

    def test_no_note_without_project_text(self):
        self.apply(self.answers())
        self.assertNotIn(agent_kit.AGENTS_NOTE, read(self.t("CLAUDE.md")))

    def test_no_note_when_claude_md_existed(self):
        write(self.t("AGENTS.md"), "# Codex notes\n\nOurs.\n")
        write(self.t("CLAUDE.md"), "# Ours\n")
        self.apply(self.answers())
        self.assertNotIn(agent_kit.AGENTS_NOTE, read(self.t("CLAUDE.md")))


if __name__ == "__main__":
    unittest.main()
