# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""The guided install: preflight, draft, review and --worktree, on a real git checkout with an origin and a lane."""
import json
import os
import shutil
import subprocess
import unittest

from kit_testlib import KIT, TempDirs, agent_kit, read, run, snapshot, write

GIT_ID = ["-c", "user.name=Kit Test", "-c", "user.email=kit@example.invalid", "-c", "commit.gpgsign=false",
          "-c", "init.defaultBranch=main"]


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd] + GIT_ID + list(args), check=True, capture_output=True,
                          text=True).stdout.strip()


@unittest.skipUnless(shutil.which("git"), "git not installed")
class Guided(TempDirs, unittest.TestCase):
    def setUp(self):
        root = self.tmp()
        self.origin = os.path.join(root, "origin.git")
        self.top = os.path.realpath(os.path.join(root, "proj"))
        subprocess.run(["git"] + GIT_ID + ["init", "-q", "--bare", self.origin], check=True, capture_output=True)
        subprocess.run(["git"] + GIT_ID + ["init", "-q", self.top], check=True, capture_output=True)
        write(os.path.join(self.top, "package.json"), json.dumps({"name": "proj", "scripts": {"test": "node t.mjs"}}))
        write(os.path.join(self.top, ".gitignore"), ".mcp.json\n.env\n.claude/worktrees/\n")
        write(os.path.join(self.top, "docs", "open.md"), "# Notes\n\nOpen items live on ABC-1.\nSee ABC-7 too.\n")
        write(os.path.join(self.top, "CLAUDE.md"), "# Proj\n\nJira: acme.atlassian.net\n")
        git(self.top, "add", "-A")
        git(self.top, "commit", "-q", "-m", "ABC-3: first")
        git(self.top, "remote", "add", "origin", self.origin)
        git(self.top, "push", "-q", "origin", "main")
        git(self.top, "remote", "set-head", "origin", "main")
        git(self.top, "branch", "feature/abc-12-thing")
        git(self.top, "worktree", "add", "-q", os.path.join(self.top, ".claude", "worktrees", "lane-b"),
            "-b", "feature/abc-13-other")
        write(os.path.join(self.top, ".mcp.json"),
              json.dumps({"mcpServers": {"proj_x_jira": {"type": "http", "url": "https://example.invalid/mcp"},
                                         "proj_db": {"type": "http", "url": "https://example.invalid/db"}}}))
        write(os.path.join(self.top, ".env"), "SECRET=never-read\n")
        self.lane = os.path.join(self.top, ".claude", "worktrees", "lane-b")

    def draft(self):
        out = os.path.join(self.tmp(), "draft.json")
        rc, stdout, err = run(["draft", "--target", self.top, "--out", out])
        self.assertEqual(rc, 0, stdout + err)
        with open(out, encoding="utf-8") as fh:
            return out, json.load(fh)

    def filled(self, d):
        for name, v in d["facts"].items():
            if v["source"] == "ask":
                v["value"] = {"OPEN_ITEMS_TICKET": "ABC-1"}.get(name, "stub value")
                v["source"] = "guess"
        path = os.path.join(self.tmp(), "answers.json")
        write(path, json.dumps(d))
        return path

    def test_draft_finds_what_the_project_already_says(self):
        _p, d = self.draft()
        f = d["facts"]
        self.assertEqual((f["TICKET_PREFIX"]["value"], f["TICKET_PREFIX"]["source"]), ("ABC", "found"))
        self.assertIn("branch name", f["TICKET_PREFIX"]["evidence"])
        self.assertEqual(f["BRANCH_PREFIX"]["value"], "feature/")
        self.assertEqual(f["MAIN_BRANCH"]["value"], "main")
        self.assertEqual(f["TEST_COMMANDS"]["source"], "found")
        self.assertEqual((f["OPEN_ITEMS_TICKET"]["value"], f["OPEN_ITEMS_TICKET"]["source"]), ("ABC-1", "found"))
        self.assertIn("docs/open.md:3", f["OPEN_ITEMS_TICKET"]["evidence"])
        self.assertEqual(f["JIRA_SITE"]["value"], "acme.atlassian.net")
        self.assertEqual(d["mcp_map"], {"jira": "proj_x_jira"})
        self.assertEqual(f["MCP_PREFIX"]["value"], "proj_")
        self.assertIn("worktrees", d["packs"])
        self.assertEqual((f["WORKTREE_DIR"]["value"], f["WORKTREE_DIR"]["source"]), (".claude/worktrees", "found"))
        self.assertEqual(f["WORKTREE_ENV_FILES"]["value"], [".env"])
        self.assertEqual(f["PROJECT_SUMMARY"]["source"], "ask")
        self.assertEqual(f["CRITICAL_DOMAIN"]["source"], "ask")
        asked = {q["pack"] for q in d["notes"]["packs_to_ask"]}
        self.assertIn("hardening", asked)
        self.assertNotIn("cold-email", asked)  # a niche extra: listed on the page, never asked
        self.assertIn("cold-email", {x["pack"] for x in d["notes"]["optional_extras"]})
        self.assertNotIn("never-read", json.dumps(d))

    def test_draft_and_preflight_write_nothing_in_the_project(self):
        before, lane = snapshot(self.top), snapshot(self.lane)
        path, _d = self.draft()
        rc, out, _e = run(["preflight", "--target", self.top, "--answers", path])
        self.assertEqual(snapshot(self.top), before)
        self.assertEqual(snapshot(self.lane), lane)
        self.assertIn("work in flight", out)
        self.assertIn("feature/abc-13-other", out)

    def test_preflight_ready_and_its_blockers(self):
        path, d = self.draft()
        pf = agent_kit.preflight(agent_kit.Kit(KIT), self.top, d)
        tools = {"node ≥ 18", "gh logged in"}  # depend on the machine, not on the project
        self.assertEqual([i["check"] for i in pf["items"] if i["blocker"] and i["check"] not in tools], [])
        self.assertTrue(any("proj_x_jira" in c for c in pf["agent_checks"]))
        d["mcp_map"] = {"jira": "missing_jira"}
        pf = agent_kit.preflight(agent_kit.Kit(KIT), self.top, d)
        self.assertEqual(pf["status"], "BLOCKED")
        self.assertTrue(any(i["blocker"] and "missing_jira" in i["detail"] for i in pf["items"]))
        git(self.top, "remote", "remove", "origin")
        pf = agent_kit.preflight(agent_kit.Kit(KIT), self.top, d)
        self.assertTrue(any(i["check"] == "origin remote" and i["blocker"] for i in pf["items"]))

    def test_an_unanswered_ask_refuses(self):
        path, _d = self.draft()
        with self.assertRaises(agent_kit.KitError) as cm:
            agent_kit.load_answers(path, None)
        self.assertIn("still to answer", str(cm.exception))
        self.assertIn("PROJECT_SUMMARY", str(cm.exception))

    def test_review_is_one_page_and_creates_only_the_install_worktree(self):
        _p, d = self.draft()
        answers = self.filled(d)
        before, lane = snapshot(self.top), snapshot(self.lane)
        page = os.path.join(self.tmp(), "review.md")
        rc, out, err = run(["review", "--target", self.top, "--answers", answers, "--out", page])
        self.assertIn(rc, (0, 1), err)
        for heading in ("## A. Before anything is written", "## B. Answers", "## C. What happens to your files",
                        "## D. What gets added", "## E. After you approve"):
            self.assertIn(heading, read(page))
        wt = os.path.join(self.top, ".claude", "worktrees", "agent-kit-install")
        self.assertTrue(os.path.isdir(wt))
        self.assertEqual(git(wt, "rev-parse", "--abbrev-ref", "HEAD"), agent_kit.INSTALL_BRANCH)
        self.assertEqual({k: v for k, v in snapshot(self.top).items() if "agent-kit-install" not in k}, before)
        self.assertEqual(snapshot(self.lane), lane)

    def test_apply_worktree_writes_only_the_install_worktree(self):
        _p, d = self.draft()
        answers = self.filled(d)
        before, lane = snapshot(self.top), snapshot(self.lane)
        mcp_before = read(os.path.join(self.top, ".mcp.json"))
        rc, out, err = run(["apply", "--target", self.top, "--answers", answers, "--worktree"])
        self.assertEqual(rc, 0, out + err)
        wt = os.path.join(self.top, ".claude", "worktrees", "agent-kit-install")
        self.assertIn(f"install worktree: {os.path.realpath(wt)}", out)
        self.assertTrue(os.path.isfile(os.path.join(wt, ".claude", "commands", "triage.md")))
        self.assertTrue(os.path.isfile(os.path.join(wt, agent_kit.LOCK_PATH)))
        self.assertIn("proj_x_jira", read(os.path.join(wt, ".claude", "rules", "ticket-ops.md")))
        self.assertEqual({k: v for k, v in snapshot(self.top).items() if "agent-kit-install" not in k}, before)
        self.assertEqual(read(os.path.join(self.top, ".mcp.json")), mcp_before)  # mapped: nothing to add
        self.assertEqual(snapshot(self.lane), lane)
        self.assertFalse(os.path.exists(os.path.join(self.top, ".claude", "commands")))
        # Run again: the same worktree is reused, and nothing changes.
        rc, out, err = run(["apply", "--target", self.top, "--answers", answers, "--worktree"])
        self.assertEqual(rc, 0, out + err)
        self.assertIn("Nothing written", out)

    def test_a_kit_server_with_no_mapping_is_written_to_the_checkouts_local_mcp_json(self):
        _p, d = self.draft()
        d["mcp_map"] = {}
        d["facts"]["MCP_PREFIX"] = {"value": "none", "source": "guess", "evidence": "test"}
        answers = self.filled(d)
        rc, out, err = run(["apply", "--target", self.top, "--answers", answers, "--worktree"])
        self.assertEqual(rc, 0, out + err)
        servers = json.loads(read(os.path.join(self.top, ".mcp.json")))["mcpServers"]
        self.assertIn("jira", servers)            # added to the real, local-only file
        self.assertIn("proj_x_jira", servers)     # the project's own servers untouched
        wt = os.path.join(self.top, ".claude", "worktrees", "agent-kit-install")
        self.assertFalse(os.path.exists(os.path.join(wt, ".mcp.json")))


    def test_upgrade_review_needs_no_answers(self):
        _p, d = self.draft()
        answers = self.filled(d)
        rc, out, err = run(["apply", "--target", self.top, "--answers", answers, "--worktree"])
        self.assertEqual(rc, 0, out + err)
        wt = os.path.join(self.top, ".claude", "worktrees", "agent-kit-install")
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "ABC-14: install agent-kit")
        git(wt, "push", "-q", "origin", "HEAD:main")  # the install PR, merged
        git(self.top, "worktree", "remove", wt)       # a clean, merged worktree (git refuses a dirty one)
        git(self.top, "branch", "-d", agent_kit.INSTALL_BRANCH)
        rc, out, err = run(["review", "--target", self.top])
        self.assertIn("## F. What changed in the kit since", out)
        self.assertNotIn("Errors (the install refuses", out)

if __name__ == "__main__":
    unittest.main()
