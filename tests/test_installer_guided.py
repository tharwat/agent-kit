# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""The guided install: preflight, draft, review and --worktree, on a real git checkout with an origin and a lane."""
import json
import os
import shutil
import subprocess
import unittest

from kit_testlib import KIT, TempDirs, agent_kit, full_answers, read, run, snapshot, write, write_answers

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
        write(os.path.join(self.top, "supabase", "migrations", "001_rows.sql"),
              "create table t (\n  id uuid primary key,\n  synthetic boolean not null default false\n);\n")
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
                                         "proj_supabase": {"type": "http", "url": "https://example.invalid/db"}}}))
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
        path, d = self.draft()
        rc, out, _e = run(["preflight", "--target", self.top, "--answers", path])
        outside = {k: v for k, v in snapshot(self.top).items() if "agent-kit-install" not in k}
        self.assertEqual(outside, before)  # only the install worktree is new
        self.assertEqual(snapshot(self.lane), lane)
        self.assertEqual(d["notes"]["install_worktree"],
                         os.path.realpath(os.path.join(self.top, ".claude", "worktrees", "agent-kit-install")))
        self.assertIn("work in flight", out)
        self.assertIn("feature/abc-13-other", out)

    def test_the_checkouts_branch_and_changes_never_reach_the_install(self):
        # The checkout sits on an unmerged branch whose docs and workflow differ from main, plus an uncommitted edit.
        git(self.top, "switch", "-q", "-c", "feature/abc-20-paused")
        write(os.path.join(self.top, "docs", "open.md"), "# Notes\n\nOpen items live on ABC-99.\n")
        write(os.path.join(self.top, ".claude", "commands", "triage.md"), "---\ndescription: paused work\n---\n# x\n")
        git(self.top, "add", "-A")
        git(self.top, "commit", "-q", "-m", "ABC-20: paused, do not merge")
        write(os.path.join(self.top, "CLAUDE.md"), "# Proj\n\nJira: other.atlassian.net\n")  # uncommitted
        _p, d = self.draft()
        self.assertEqual(d["facts"]["OPEN_ITEMS_TICKET"]["value"], "ABC-1")     # main's docs, not the branch's
        self.assertEqual(d["facts"]["JIRA_SITE"]["value"], "acme.atlassian.net")  # main's CLAUDE.md
        self.assertIn("feature/abc-20-paused", d["notes"]["checkout_branch"])
        self.assertEqual(d["mcp_map"], {"jira": "proj_x_jira"})                  # local-only: from the checkout
        answers = self.filled(d)
        rc, out, err = run(["apply", "--target", self.top, "--answers", answers, "--worktree"])
        self.assertEqual(rc, 0, out + err)
        wt = d["notes"]["install_worktree"]
        self.assertNotIn("paused work", read(os.path.join(wt, ".claude", "commands", "triage.md")))
        self.assertEqual(git(self.top, "rev-parse", "--abbrev-ref", "HEAD"), "feature/abc-20-paused")  # untouched
        pf = agent_kit.preflight(agent_kit.Kit(KIT), self.top, d)
        self.assertTrue(any(i["check"] == "checkout branch" and not i["blocker"] for i in pf["items"]))

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
        before = {k: v for k, v in snapshot(self.top).items() if "agent-kit-install" not in k}
        lane = snapshot(self.lane)
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
        before = {k: v for k, v in snapshot(self.top).items() if "agent-kit-install" not in k}
        lane = snapshot(self.lane)
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

    def test_draft_reads_the_synthetic_marker_from_the_schema(self):
        _p, d = self.draft()
        f = d["facts"]["SYNTHETIC_MARKER"]
        self.assertEqual((f["value"], f["source"]), ("synthetic", "found"))
        self.assertIn("supabase/migrations/001_rows.sql:3", f["evidence"])

    def test_the_install_worktree_gets_the_env_files_and_verify_skips_local_only_files(self):
        _p, d = self.draft()
        answers = self.filled(d)
        rc, out, err = run(["apply", "--target", self.top, "--answers", answers, "--worktree"])
        self.assertEqual(rc, 0, out + err)
        wt = d["notes"]["install_worktree"]
        env = os.path.join(wt, ".env")
        self.assertTrue(os.path.islink(env))
        self.assertEqual(os.path.realpath(env), os.path.realpath(os.path.join(self.top, ".env")))
        rc, out, err = run(["verify", "--target", wt])
        self.assertNotIn("PROBLEM: .mcp.json", out)
        self.assertIn(".mcp.json: local-only", out)


    def test_an_earlier_attempt_is_reported_then_continued_or_parked_for_a_fresh_start(self):
        _p, d = self.draft()
        answers = self.filled(d)
        rc, out, err = run(["apply", "--target", self.top, "--answers", answers, "--worktree"])
        self.assertEqual(rc, 0, out + err)
        old = d["notes"]["install_worktree"]
        write(os.path.join(old, "CLAUDE.md"), "hand work from the earlier attempt\n")
        pf = agent_kit.preflight(agent_kit.Kit(KIT), self.top, d)
        item = next(i for i in pf["items"] if i["check"] == "earlier install attempt")
        self.assertFalse(item["blocker"])
        self.assertIn("continue it", item["detail"])
        _p, d2 = self.draft()  # no --fresh: the same attempt continues
        self.assertEqual(d2["notes"]["install_worktree"], old)
        out = os.path.join(self.tmp(), "fresh.json")
        rc, stdout, err = run(["draft", "--target", self.top, "--out", out, "--fresh"])
        self.assertEqual(rc, 0, stdout + err)
        version = agent_kit.Kit(KIT).version
        parked = f"{old}-{version}"
        self.assertEqual(read(os.path.join(parked, "CLAUDE.md")), "hand work from the earlier attempt\n")  # kept
        self.assertEqual(git(parked, "rev-parse", "--abbrev-ref", "HEAD"), f"{agent_kit.INSTALL_BRANCH}-{version}")
        self.assertFalse(os.path.isfile(os.path.join(old, agent_kit.LOCK_PATH)))  # the new attempt starts clean
        self.assertEqual(git(old, "rev-parse", "--abbrev-ref", "HEAD"), agent_kit.INSTALL_BRANCH)

    def test_a_merged_install_is_parked_and_a_lane_in_the_way_is_stepped_around(self):
        """An upgrade starts from main, not from the finished install's branch; a lane already sitting at the install
        path is left alone and the install goes next to it."""
        squatter = os.path.join(self.top, ".claude", "worktrees", "agent-kit-install")
        git(self.top, "worktree", "add", "-q", squatter, "-b", "feature/abc-14-docs")
        write(os.path.join(squatter, "wip.md"), "a lane's uncommitted work\n")
        _p, d = self.draft()
        first = d["notes"]["install_worktree"]
        self.assertEqual(first, squatter + "-2")
        rc, out, err = run(["apply", "--target", self.top, "--answers", self.filled(d), "--worktree"])
        self.assertEqual(rc, 0, out + err)
        git(first, "add", "-A")
        git(first, "commit", "-q", "-m", "ABC-15: install agent-kit")
        git(first, "push", "-q", "origin", agent_kit.INSTALL_BRANCH + ":main")  # the install PR merged
        git(self.top, "fetch", "-q", "origin")
        pf = agent_kit.preflight(agent_kit.Kit(KIT), self.top, d)
        item = next(i for i in pf["items"] if i["check"] == "finished install worktree")
        self.assertIn("parks it", item["detail"])
        self.assertFalse(any(i["check"] == "earlier install attempt" for i in pf["items"]))
        _p, d2 = self.draft()  # no --fresh needed
        new = d2["notes"]["install_worktree"]
        self.assertEqual(git(new, "rev-parse", "HEAD"), git(self.top, "rev-parse", "origin/main"))
        self.assertEqual(git(new, "rev-parse", "--abbrev-ref", "HEAD"), agent_kit.INSTALL_BRANCH)
        version = agent_kit.Kit(KIT).version
        self.assertTrue(os.path.isdir(f"{first}-{version}"))  # parked, never deleted
        self.assertEqual(read(os.path.join(squatter, "wip.md")), "a lane's uncommitted work\n")
        self.assertEqual(git(squatter, "rev-parse", "--abbrev-ref", "HEAD"), "feature/abc-14-docs")

    def test_unguarded_credential_files_are_listed_by_name_never_by_value(self):
        literal = "lit" + "eralvalue" * 4  # a fake credential, built so no scanner mistakes it for a real one
        write(os.path.join(self.top, ".gitignore"), ".mcp.json\n.env\n.claude/worktrees/\n.gdrive-token.json\n"
              "sa-key.json\n.gdrive-oauth-client.json\n")
        write(os.path.join(self.top, ".gdrive-token.json"), json.dumps({"refresh_token": literal}))
        write(os.path.join(self.top, "sa-key.json"), json.dumps({"type": "service_account", "private_key": literal}))
        write(os.path.join(self.top, ".gdrive-oauth-client.json"), "not json at all")
        write(os.path.join(self.top, ".codex", "config.toml"), '[mcp.env]\nN8N_API_KEY = "' + literal + '"\nmodel = "x"\n')
        write(os.path.join(self.top, ".claude", "settings.local.json"),
              json.dumps({"env": {"GOOGLE_API_KEY": literal, "LOG_LEVEL": "debug"}}))
        write(os.path.join(self.top, ".gitignore"), read(os.path.join(self.top, ".gitignore")) +
              ".codex/\n.claude/settings.local.json\n")
        servers = json.loads(read(os.path.join(self.top, ".mcp.json")))
        servers["mcpServers"]["proj_supabase"]["headers"] = {"Authorization": "Bearer " + literal}
        servers["mcpServers"]["proj_cal"] = {"type": "http", "url": "https://example.invalid/mcp?access_token=" + literal}
        write(os.path.join(self.top, ".claude", "state", "feature-abc-9-oauth-token.upstream"), "origin/main\n")
        servers["mcpServers"]["proj_x_jira"]["headers"] = {"Authorization": "Bearer ${JIRA_TOKEN}"}
        write(os.path.join(self.top, ".mcp.json"), json.dumps(servers))
        path, d = self.draft()
        found = {c["file"]: c["why"] for c in d["notes"]["credential_files"]}
        self.assertIn("refresh_token", found[".gdrive-token.json"])
        self.assertIn("private_key", found["sa-key.json"])
        self.assertIn("credential-like name", found[".gdrive-oauth-client.json"])
        self.assertIn("proj_supabase", found[".mcp.json"])  # "Bearer <token>"
        self.assertIn("proj_cal", found[".mcp.json"])       # ?access_token=<token>
        self.assertFalse(any(f.startswith(".claude/state/") for f in found))  # the kit's own state, not secrets
        self.assertNotIn("proj_x_jira", found[".mcp.json"])  # an ${ENV} reference holds no secret
        self.assertNotIn(".env", found)                       # already on the guard's built-in list
        self.assertIn("N8N_API_KEY", found[".codex/config.toml"])                     # TOML config
        self.assertIn("GOOGLE_API_KEY", found[".claude/settings.local.json"])         # an env-style key name
        self.assertIn("move the value into the environment", found[".claude/settings.local.json"])
        self.assertNotIn("LOG_LEVEL", found[".claude/settings.local.json"])
        rc, out, _e = run(["preflight", "--target", self.top, "--answers", path])
        self.assertIn("credential files the guard doesn't block", out)
        self.assertNotIn(literal, out + read(path))

    def test_a_none_default_the_project_contradicts_becomes_a_guess(self):
        write(os.path.join(self.top, "scripts", "sync-env.mjs"), "const id = process.env.RENDER_ENV_GROUP_ID;\n")
        git(self.top, "add", "-A")
        git(self.top, "commit", "-q", "-m", "ABC-21: sync env")
        git(self.top, "push", "-q", "origin", "main")
        out = os.path.join(self.tmp(), "d.json")
        rc, stdout, err = run(["draft", "--target", self.top, "--out", out])
        self.assertEqual(rc, 0, stdout + err)
        d = json.loads(read(out))
        wt = d["notes"]["install_worktree"]
        self.assertEqual(agent_kit.mentions(wt, "ENV_GROUPS"), ["scripts/sync-env.mjs"])  # ENV_GROUP, any case
        self.assertEqual(agent_kit.mentions(wt, "WEB_QA_URL"), [])
        # The draft applies it to every "none" default: LOG_SINK is one, and a file naming it turns it into a guess.
        write(os.path.join(self.top, "ops.md"), "Logs: see LOG_SINK in the runbook.\n")
        git(self.top, "add", "-A")
        git(self.top, "commit", "-q", "-m", "ABC-22: ops note")
        git(self.top, "push", "-q", "origin", "main")
        git(wt, "merge", "-q", "--ff-only", "origin/main")
        rc, stdout, err = run(["draft", "--target", self.top, "--out", out])
        f = json.loads(read(out))["facts"]["LOG_SINK"]
        self.assertEqual(f["source"], "guess")
        self.assertIn("ops.md", f["evidence"])

class Decisions(TempDirs, unittest.TestCase):
    """Every clash carries its advice; the owner's answers, exceptions and budget are kept and written down."""

    def setUp(self):
        self.target = self.tmp()
        self.decision = {"id": "D1", "guide": "schema-changes", "topic": "Removing a database column",
                         "kit_rule": "phased when something live would break", "project_rule": "one migration with "
                         "a backout and a snapshot (CLAUDE.md)", "found": "every consumer deploys from this repo",
                         "recommendation": "project", "why": "nothing deploys separately", "pro": "no follow-up "
                         "migrations", "con": "a missed separate reader breaks"}

    def answers(self, **extra):
        return write_answers(self.tmp(), full_answers(KIT, **extra))

    def test_a_half_advised_decision_refuses(self):
        for missing in ("found", "why", "pro", "con", "recommendation"):
            with self.subTest(missing=missing):
                d = dict(self.decision)
                d.pop(missing)
                rc, out, err = run(["plan", "--target", self.target, "--answers", self.answers(decisions=[d])])
                self.assertEqual(rc, 2)
                self.assertIn(f"decision D1 is missing {missing}", err)
        bad = dict(self.decision, guide="no-such-entry")
        rc, _o, err = run(["plan", "--target", self.target, "--answers", self.answers(decisions=[bad])])
        self.assertIn("is not an entry in installer/decision-guide.md", err)

    def test_an_unanswered_decision_refuses_apply(self):
        rc, _o, err = run(["apply", "--target", self.target, "--answers", self.answers(decisions=[self.decision])])
        self.assertEqual(rc, 2)
        self.assertIn("still to answer: decision(s) D1", err)

    def test_answered_decisions_are_written_down_and_kept_in_the_lock(self):
        d = dict(self.decision, answer="project")
        rc, out, err = run(["apply", "--target", self.target, "--answers", self.answers(decisions=[d])])
        self.assertEqual(rc, 0, out + err)
        doc = read(os.path.join(self.target, agent_kit.DECISIONS_DOC))
        self.assertIn("## D1: Removing a database column", doc)
        self.assertIn("**Decided:** the project's rule", doc)
        lock = json.loads(read(os.path.join(self.target, agent_kit.LOCK_PATH)))
        self.assertEqual(lock["answers"]["decisions"][0]["answer"], "project")
        rc, out, err = run(["upgrade", "--target", self.target])  # no answers: the lock's decisions carry over
        self.assertEqual(rc, 0, out + err)
        self.assertIn("## D1", read(os.path.join(self.target, agent_kit.DECISIONS_DOC)))

    def test_a_safety_exception_stays_out_on_every_apply_and_upgrade(self):
        rc, out, err = run(["apply", "--target", self.target, "--answers", self.answers(packs=["supabase"])])
        self.assertEqual(rc, 0, out + err)
        settings = json.loads(read(os.path.join(self.target, ".claude", "settings.json")))
        entry = next(x for x in settings["permissions"]["deny"] if x.endswith("__apply_migration"))
        other = self.tmp()
        exc = {"permissions.deny": [{"entry": entry, "reason": "standing yes for migrations; backout and snapshot "
                                     "rule", "approved": "owner, install review 2026-11-18"}]}
        for cmd in (["apply"], ["apply"], ["upgrade"]):
            ans = self.answers(packs=["supabase"], exceptions=exc) if cmd == ["apply"] else None
            rc, out, err = run(cmd + ["--target", other] + (["--answers", ans] if ans else []))
            self.assertEqual(rc, 0, out + err)
            settings = json.loads(read(os.path.join(other, ".claude", "settings.json")))
            self.assertNotIn(entry, settings["permissions"]["deny"])
        self.assertIn(f"Exception: `{entry}` is not blocked", read(os.path.join(other, agent_kit.DECISIONS_DOC)))
        no_yes = {"permissions.deny": [{"entry": entry, "reason": "x"}]}
        rc, _o, err = run(["plan", "--target", self.tmp(), "--answers", self.answers(packs=["supabase"],
                                                                                    exceptions=no_yes)])
        self.assertIn("needs entry, reason and approved", err)

    def test_a_raised_word_budget_needs_its_reason(self):
        a = full_answers(KIT)
        a["options"]["word_budget"] = 4100
        rc, _o, err = run(["plan", "--target", self.target, "--answers", write_answers(self.tmp(), a)])
        self.assertIn("add options.word_budget_reason", err)
        a["options"]["word_budget_reason"] = "the safety rules stay loaded in every session"
        rc, out, err = run(["apply", "--target", self.target, "--answers", write_answers(self.tmp(), a)])
        self.assertEqual(rc, 0, out + err)
        lock = json.loads(read(os.path.join(self.target, agent_kit.LOCK_PATH)))
        self.assertEqual(lock["answers"]["options"]["word_budget"], 4100)
        self.assertIn("## Word budget: 4100", read(os.path.join(self.target, agent_kit.DECISIONS_DOC)))

    def test_every_guide_entry_has_the_parts_a_first_time_owner_needs(self):
        text = read(agent_kit.GUIDE_PATH)
        entries = text.split("\n### ")[1:]
        self.assertGreaterEqual(len(entries), 12)
        budget = next(e for e in entries if e.startswith("word-budget:"))
        for step in ("Drop the repeats", "Move area rules", "Condense process notes", "Only if it's still over",
                     "editing the CI workflow", "search the project's tests"):
            self.assertIn(step, budget)
        for e in entries:
            with self.subTest(entry=e.split(":", 1)[0]):
                self.assertIn("**Kit:**", e)
                self.assertIn("**Recommend", e)
                self.assertIn("**Pro", e)
                self.assertIn("Con:**", e)

if __name__ == "__main__":
    unittest.main()
