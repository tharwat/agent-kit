# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Installer fixes found by the round-2 pilots (G1.1-G1.8). Temporary targets and kit copies only."""
import json
import os
import shutil
import subprocess
import unittest

from kit_testlib import agent_kit, copy_kit, full_answers, load_json, read, run, schema_check, snapshot, write, \
    write_answers
from test_installer import FIXTURE_PACK, Base, add_fixture_pack
from test_installer_pilot_fixes import edit_fixture

LOCK = ".claude/agent-kit.lock.json"
C_HTML = agent_kit.COPYRIGHT_HTML
C_HASH = agent_kit.COPYRIGHT_HASH
GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]


def has_git():
    return shutil.which("git") is not None


def git(target, *args):
    subprocess.run(["git", "-C", target] + GIT_ID + list(args), check=True, capture_output=True)


def block_lines(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0].strip("\n").split("\n")


class Copyright(Base):
    """G1.1: the generated blocks and wrappers carry the copyright line."""

    def test_fresh_install_blocks_and_wrappers(self):
        self.apply(self.answers())
        claude = read(self.t("CLAUDE.md"))
        self.assertEqual(block_lines(claude, agent_kit.FACTS_START, agent_kit.FACTS_END)[0], C_HTML)
        self.assertEqual(claude.count(C_HTML), 1)
        agents = read(self.t("AGENTS.md"))
        inner = block_lines(agents, agent_kit.AGENTS_START, agent_kit.AGENTS_END)
        self.assertEqual(inner[0], C_HTML)
        self.assertTrue(inner[1].startswith("# AGENTS.md"))  # a new file keeps the template's title
        self.assertEqual(agents.count(C_HTML), 1)
        gi = read(self.t(".gitignore")).split("\n")
        self.assertIn(C_HASH, gi)
        self.assertEqual(gi.index(C_HASH), gi.index(next(l for l in gi if l.startswith("# agent-kit"))) + 1)
        wrapper = read(self.t(".agents/skills/ship/SKILL.md"))
        fm_end = wrapper.index("\n---\n", 4) + len("\n---\n")
        self.assertTrue(wrapper[fm_end:].startswith(C_HTML + "\n"), wrapper)
        before = snapshot(self.target)
        self.apply(self.answers())
        self.assertEqual(snapshot(self.target), before)

    def test_merged_blocks_into_existing_files(self):
        write(self.t("CLAUDE.md"), "# Ours\n\nOur rule.\n")
        write(self.t("AGENTS.md"), "# Our agents\n\nOur agent rule.\n")
        self.apply(self.answers())
        claude = read(self.t("CLAUDE.md"))
        inner = block_lines(claude, agent_kit.FACTS_START, agent_kit.FACTS_END)
        self.assertEqual(inner[:2], [C_HTML, agent_kit.KIT_IMPORT])
        self.assertTrue(claude.startswith("# Ours\n\nOur rule.\n"))
        agents = read(self.t("AGENTS.md"))
        inner = block_lines(agents, agent_kit.AGENTS_START, agent_kit.AGENTS_END)
        self.assertEqual(inner[0], C_HTML)
        self.assertNotIn("# AGENTS.md", agents)  # the template's title is dropped below the project's own
        self.assertEqual(agents.count(C_HTML), 1)
        rc, out, err = self.cli("verify")
        self.assertEqual(rc, 0, out + err)
        before = snapshot(self.target)
        self.apply(self.answers())
        self.assertEqual(snapshot(self.target), before)

    def test_block_from_an_older_install_gains_the_line(self):
        self.apply(self.answers())
        claude = read(self.t("CLAUDE.md")).replace(C_HTML + "\n", "")
        write(self.t("CLAUDE.md"), claude)
        lock = load_json(self.t(LOCK))
        b = agent_kit.find_block(claude, agent_kit.FACTS_START, agent_kit.FACTS_END)
        lock["files"]["CLAUDE.md"]["block_sha256"] = agent_kit.sha256(claude[b[0]:b[1]].encode("utf-8"))
        write(self.t(LOCK), json.dumps(lock, indent=2))
        self.assertEqual(self.rows(self.answers())["CLAUDE.md"]["action"], "merge")
        self.apply(self.answers())
        self.assertEqual(read(self.t("CLAUDE.md")).count(C_HTML), 1)

    def test_gitignore_line_is_added_once(self):
        write(self.t(".gitignore"), "node_modules/\n")
        self.apply(self.answers())
        text = read(self.t(".gitignore"))
        self.assertTrue(text.startswith("node_modules/\n"))
        self.assertEqual(text.count(C_HASH), 1)


class ScanSuggestions(Base):
    """G1.2: more suggested facts, and scan reports for plugins, ignored .mcp.json, branches and hook paths."""

    def scan(self, target=None):
        rc, out, err = run(["scan", "--target", target or self.target, "--kit", self.kit])
        self.assertEqual(rc, 0, err)
        return json.loads(out)

    def test_typescript_project(self):
        write(self.t("package.json"), json.dumps({"devDependencies": {"typescript": "5", "vitest": "1"},
                                                  "scripts": {"test": "vitest run"}}))
        write(self.t("tsconfig.json"), "{}")
        sf = self.scan()["suggested_facts"]
        self.assertEqual(sf["TYPECHECK_COMMAND"], "npx tsc --noEmit")
        self.assertEqual(sf["TS_PACKAGE_DIRS"], "auto")
        self.assertEqual(sf["TEST_FRAMEWORK"], "vitest")
        self.assertNotIn("SYNTAX_CHECK_COMMAND", sf)
        self.assertNotIn("MOBILE_DIR", sf)

    def test_tsconfig_in_one_package_only(self):
        write(self.t("package.json"), json.dumps({"devDependencies": {"typescript": "5"}}))
        write(self.t("server/tsconfig.json"), "{}")
        sf = self.scan()["suggested_facts"]
        self.assertEqual(sf["TYPECHECK_COMMAND"], "npx tsc --noEmit -p server")
        self.assertEqual(sf["TEST_FRAMEWORK"], "none")

    def test_tsconfig_without_typescript_dep_has_no_typecheck(self):
        write(self.t("package.json"), json.dumps({}))
        write(self.t("tsconfig.json"), "{}")
        sf = self.scan()["suggested_facts"]
        self.assertNotIn("TYPECHECK_COMMAND", sf)
        self.assertEqual(sf["TS_PACKAGE_DIRS"], "auto")

    def test_esm_without_tsconfig(self):
        write(self.t("package.json"), json.dumps({"scripts": {"start": "node server.mjs"}}))
        write(self.t("src/server.mjs"), "export {}\n")
        sf = self.scan()["suggested_facts"]
        self.assertEqual(sf["SYNTAX_CHECK_COMMAND"], "node --check <file>")
        self.assertNotIn("TEST_FRAMEWORK", sf)
        self.assertNotIn("TYPECHECK_COMMAND", sf)

    def test_mobile_dir(self):
        write(self.t("app.json"), json.dumps({"expo": {"name": "x"}}))
        self.assertEqual(self.scan()["suggested_facts"]["MOBILE_DIR"], ".")
        other = self.tmp()
        write(os.path.join(other, "package.json"), json.dumps({}))
        write(os.path.join(other, "apps", "mobile", "app.config.ts"), "export default {}\n")
        self.assertEqual(self.scan(other)["suggested_facts"]["MOBILE_DIR"], "apps/mobile")
        plain = self.tmp()
        write(os.path.join(plain, "app.json"), json.dumps({"name": "a heroku app"}))  # not an Expo app
        self.assertNotIn("MOBILE_DIR", self.scan(plain)["suggested_facts"])

    def test_no_package_json_no_package_manager(self):
        write(self.t("main.py"), "print(1)\n")
        data = self.scan()
        self.assertIsNone(data["package_manager"])
        self.assertEqual(data["enabled_plugins"], [])
        self.assertEqual(data["hooks_with_absolute_paths"], [])
        self.assertIsNone(data["mcp_json_gitignored"])  # not a git repository
        self.assertEqual(data["extra_long_lived_branches"], [])

    def test_settings_plugins_and_hook_paths(self):
        write(self.t(".claude/settings.json"), json.dumps({
            "enabledPlugins": {"alpha@market": True, "off@market": False},
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/ok.sh"},
                {"type": "command", "command": "/usr/bin/env python3 \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/ok.py"},
                {"type": "command", "command": "API_TOKEN=s3cret-value /home/dev/hooks/guard.sh"}]}]}}))
        write(self.t(".claude/settings.local.json"), json.dumps({
            "enabledPlugins": {"beta@market": True}, "env": {"SOME_KEY": "never-printed"},
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "sh ~/bin/notify.sh"}]}]}}))
        rc, out, err = run(["scan", "--target", self.target, "--kit", self.kit])
        self.assertNotIn("s3cret-value", out)
        self.assertNotIn("never-printed", out)
        data = json.loads(out)
        self.assertEqual(data["enabled_plugins"], ["alpha@market", "beta@market"])
        hooks = data["hooks_with_absolute_paths"]
        self.assertEqual([(h["file"], h["event"]) for h in hooks],
                         [(".claude/settings.json", "PreToolUse"), (".claude/settings.local.json", "Stop")])
        self.assertEqual(hooks[0]["command"], "API_TOKEN=<redacted> /home/dev/hooks/guard.sh")

    def test_git_signals(self):
        if not has_git():
            self.skipTest("git not available")
        git(self.target, "init", "-q")
        git(self.target, "symbolic-ref", "HEAD", "refs/heads/main")
        write(self.t(".gitignore"), ".mcp.json\n")
        write(self.t("package.json"), "{}")
        git(self.target, "add", "-A")
        git(self.target, "commit", "-q", "-m", "x")
        for b in ("qa", "develop", "feature/x", "release-notes"):
            git(self.target, "branch", b)
        data = self.scan()
        self.assertEqual(data["suggested_facts"]["MAIN_BRANCH"], "main")
        self.assertEqual(data["extra_long_lived_branches"], ["develop", "qa"])
        self.assertTrue(data["mcp_json_gitignored"])
        self.assertEqual(data["package_manager"], "npm")

    def test_ticket_pack_is_marked_as_chosen_by_the_fact(self):
        packs = {p["name"]: p for p in self.scan()["packs"]}
        self.assertIn("TICKET_SYSTEM", packs["jira"]["selected_by"])
        self.assertNotIn("selected_by", packs["supabase"])


class OriginWarnings(Base):
    """G1.3: warn when there is no origin, and when GitHub is on but origin isn't GitHub."""

    def warnings(self, **kw):
        return self.plan(self.answers(**kw))["warnings"]

    def test_no_origin(self):
        ws = self.warnings()
        self.assertTrue(any("no `origin` remote" in w and "origin/main" in w for w in ws), ws)
        out, _ = self.apply(self.answers())
        self.assertIn("warning: the target has no `origin` remote", out)

    def test_origin_not_on_github(self):
        if not has_git():
            self.skipTest("git not available")
        git(self.target, "init", "-q")
        git(self.target, "remote", "add", "origin", "git@gitlab.com:acme/app.git")
        ws = self.warnings()
        self.assertTrue(any("origin is on gitlab.com, not GitHub" in w for w in ws), ws)
        self.assertFalse(any("no `origin` remote" in w for w in ws), ws)
        self.assertFalse(any("not GitHub" in w for w in self.warnings(options={"github": False})))

    def test_local_path_origin(self):
        if not has_git():
            self.skipTest("git not available")
        git(self.target, "init", "-q")
        git(self.target, "remote", "add", "origin", os.path.join(self.tmp(), "origin.git"))
        ws = self.warnings()
        self.assertTrue(any("origin is a local path or an unrecognized URL, not GitHub" in w for w in ws), ws)
        self.assertIsNone(agent_kit.remote_host("file:///srv/git/app.git"))

    def test_origin_on_github_is_quiet(self):
        if not has_git():
            self.skipTest("git not available")
        git(self.target, "init", "-q")
        git(self.target, "remote", "add", "origin", "https://github.com/acme/app.git")
        ws = self.warnings()
        self.assertFalse(any("origin" in w for w in ws), ws)


class ReapplyOutput(Base):
    """G1.4: settled resolutions are quiet, resolved conflicts aren't counted as conflicts, defaults on one line,
    and no empty MCP table."""
    CMD = ".claude/commands/resume.md"

    def test_resolved_conflict_summary_and_settled_resolutions(self):
        write(self.t(self.CMD), "---\ndescription: ours\n---\nOur resume.\n")
        ans = self.answers(resolutions={self.CMD: "keep-theirs", ".claude/commands/nope.md": "take-kit"})
        rc, md, _ = self.cli("plan", ans)
        self.assertIn("resolved keep-theirs 1", md)
        self.assertNotIn("conflict 1", md)
        out, _ = self.apply(ans)
        summary = next(l for l in out.splitlines() if l.startswith("Summary:"))
        self.assertIn("resolved keep-theirs 1", summary)
        self.assertNotIn("conflict", summary)
        self.assertIn("resolution for .claude/commands/nope.md is unused", out)  # a real stray still warns
        out, _ = self.apply(ans)  # the same answers again: the lock settled the first one
        self.assertNotIn(f"resolution for {self.CMD} is unused", out)
        self.assertIn("resolution for .claude/commands/nope.md is unused", out)

    def test_defaults_on_one_line(self):
        ans = full_answers(self.kit)
        for k in ("TICKET_SYSTEM", "MAIN_BRANCH"):
            del ans["facts"][k]
        out, _ = self.apply(write_answers(self.work, ans))
        lines = [l for l in out.splitlines() if "not answered" in l]
        self.assertEqual(len(lines), 1, out)
        self.assertIn("TICKET_SYSTEM='jira'", lines[0])
        self.assertIn("MAIN_BRANCH='main'", lines[0])

    def test_mcp_section_only_when_a_server_ships(self):
        ans = full_answers(self.kit)
        ans["facts"]["TICKET_SYSTEM"] = "none"
        rc, md, _ = self.cli("plan", write_answers(self.work, ans))
        self.assertNotIn("## MCP servers", md)
        rc, md, _ = self.cli("plan", self.answers())  # jira (from TICKET_SYSTEM) ships the atlassian server
        self.assertIn("## MCP servers (.mcp.json)", md)
        self.assertIn("| atlassian | jira | add |", md)


class OwnerTaskWhen(Base):
    """G1.5: an owner task with `when` shows only when its fact has that value."""

    def setUp(self):
        super().setUp()
        self.kit = copy_kit(os.path.join(self.tmp(), "kit"))
        add_fixture_pack(self.kit)
        edit_fixture(self.kit, lambda d: d["owner_tasks"].extend([
            {"task": "Shown for K-1", "when": {"fact": "FIXTURE_KEY", "equals": "K-1"}},
            {"task": "Hidden for K-1", "why": "w", "when": {"fact": "FIXTURE_KEY", "equals": "K-2"}}]))

    def test_when_filters_tasks(self):
        self.assertEqual(agent_kit.Kit(self.kit).errors, [])
        ans = self.answers(packs=(FIXTURE_PACK,))
        tasks = [t["task"] for t in self.plan(ans)["owner_tasks"]]
        self.assertIn("Shown for K-1", tasks)
        self.assertNotIn("Hidden for K-1", tasks)
        self.assertIn("Create the demo project", tasks)
        self.assertFalse(any("when" in t for t in self.plan(ans)["owner_tasks"]))
        out, _ = self.apply(ans)
        self.assertIn("Shown for K-1", out)
        self.assertNotIn("Hidden for K-1", out)

    def test_schema(self):
        schema = load_json(os.path.join(self.kit, "schemas", "pack.schema.json"))
        base = {"name": "x", "version": "1.0.0", "description": "d", "kind": "extra", "files": []}
        ok = dict(base, owner_tasks=[{"task": "t", "when": {"fact": "MIGRATION_TOOL", "equals": "mcp-apply"}}])
        self.assertEqual(schema_check.validate(ok, schema), [])
        for bad in ({"fact": "MIGRATION_TOOL"}, {"fact": "lower", "equals": "x"},
                    {"fact": "A", "equals": "x", "other": 1}):
            self.assertTrue(schema_check.validate(dict(base, owner_tasks=[{"task": "t", "when": bad}]), schema), bad)


class RuleTable(Base):
    """G1.6: ticket-ops.md has its own label, and the installed check fails when a rule is missing from the table."""

    def test_ticket_ops_label_and_missing_rule(self):
        self.apply(self.answers())
        agents = read(self.t("AGENTS.md"))
        self.assertIn("| `.claude/rules/ticket-ops.md` | Before any ticket op |", agents)
        rc, out, err = self.cli("verify")
        self.assertEqual(rc, 0, out + err)
        write(self.t(".claude/rules/project-db.md"), "---\npaths:\n  - \"db/**\"\n---\n# db\n")
        rc, out, err = self.cli("verify")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("the rule table leaves out .claude/rules/project-db.md", out)
        self.apply(self.answers())  # re-running apply lists it
        rc, out, err = self.cli("verify")
        self.assertEqual(rc, 0, out + err)


class InstalledWordBudget(Base):
    """G1.7: the installed checker allows 3,500 always-loaded words; the kit's own text is held to 2,500."""

    def test_installed_checker_default(self):
        self.apply(self.answers())
        proc = subprocess.run(["python3", self.t(".github/scripts/check_skill_links.py"), "--repo", self.target],
                              capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertIn(" / 3500 ", proc.stdout)
        self.assertEqual(load_json(os.path.join(self.kit, "manifest.json"))["checks"]["word_budget"], 2500)


class TicketPackFollowsFact(Base):
    """G1.8: the ticket pack is the one TICKET_SYSTEM names; it isn't asked for or recorded as a chosen pack."""

    def answers_with(self, ticket, packs=()):
        ans = full_answers(self.kit, packs)
        ans["facts"]["TICKET_SYSTEM"] = ticket
        return write_answers(self.work, ans)

    def test_jira_added_by_the_fact(self):
        ans = self.answers_with("jira")
        plan = self.plan(ans)
        self.assertIn("jira", plan["units"])
        self.assertEqual(plan["auto_packs"], ["jira"])
        rc, md, _ = self.cli("plan", ans)
        self.assertIn("(jira: chosen by TICKET_SYSTEM)", md)
        self.apply(ans)
        lock = load_json(self.t(LOCK))
        self.assertNotIn("jira", lock["answers"]["packs"])
        self.assertIn("jira", [u["name"] for u in lock["units"]])
        self.assertTrue(os.path.isfile(self.t(".claude/rules/ticket-ops.md")))
        rc, out, err = self.cli("upgrade")  # from the lock alone: the fact brings jira back
        self.assertEqual(rc, 0, out + err)
        self.assertIn("jira", [u["name"] for u in load_json(self.t(LOCK))["units"]])

    def test_explicit_jira_is_not_doubled(self):
        plan = self.plan(self.answers_with("jira", packs=("jira",)))
        self.assertEqual(plan["units"].count("jira"), 1)
        self.assertEqual(plan["auto_packs"], [])

    def test_none_and_unknown_systems(self):
        plan = self.plan(self.answers_with("none"))
        self.assertNotIn("jira", plan["units"])
        self.assertFalse(any("TICKET_SYSTEM" in w for w in plan["warnings"]))
        plan = self.plan(self.answers_with("linear"))
        self.assertNotIn("jira", plan["units"])
        self.assertTrue(any("TICKET_SYSTEM is 'linear'" in w for w in plan["warnings"]), plan["warnings"])

    def test_ticket_pack_that_disagrees_with_the_fact_warns(self):
        plan = self.plan(self.answers_with("linear", packs=("jira",)))
        self.assertTrue(any("pack jira is a ticket pack but TICKET_SYSTEM is 'linear'" in w
                            for w in plan["warnings"]), plan["warnings"])


if __name__ == "__main__":
    unittest.main()
