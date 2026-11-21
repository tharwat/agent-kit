#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Tests for check-record.py. Run: python3 -m unittest test_check_record.py"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check-record.py")
TICKET = "ABC-12"
FP = "ab" * 32
HEADER = ("| ID | Class | Invariant | Paths | Hostile case | Authority | Behavioral proof | Counterfactual | "
          "Independent vector | Discharge |")
PLAN_CHECK = {
    "ticket": "ABC-12",
    "state_homes": [{"fact": "order status", "home": "orders.status", "writers": ["api/orders.js:40"],
                     "readers": ["jobs/ship.js:12", "ui/list.tsx:88-90"], "second_home": None}],
    "state_homes_none": None,
    "contradiction_check": {"rows_read": 1, "decisions_read": 2, "conflicts": []},
    "lifecycles": [{"state": "held", "created": "on hold", "changed": "release", "removed": "never",
                    "restored": "n/a", "edited_in_state": "blocked", "name_reuse": "n/a",
                    "safety_flags": "none apply", "what_a_person_sees": "a Held badge"}],
    "lifecycles_none": None,
    "enumerations": [{"what": "order-statuses", "derived_from": "the orders.status CHECK constraint",
                      "test": "tests/statuses.test.js"}],
    "enumerations_none": None,
    "safety_defaults": [],
}
INVENTORY = {
    "ticket": "ABC-12",
    "sections": [{
        "name": "Plan",
        "values": [{"value": "orders.status", "change": "adds 'held'", "writers": ["api/orders.js:40"],
                    "readers": ["jobs/ship.js:12", "ui/list.tsx:88"], "reader_assumes": "open = shippable",
                    "needs_change": {"answer": "yes"}, "search": "grep -rn \"status\" src"}],
        "siblings": [{"behaviour": "hold retry", "sibling": "jobs/retry.js:20", "guards": ["budget", "idempotency"],
                      "copied": {"answer": "yes"}, "search": "grep -rn retry jobs"}],
        "helpers": [{"helper": "loadOrder", "where": "lib/orders.js:5", "short_circuits": "null on missing id",
                     "errors": "throws DbError", "success": "a row"}],
        "claims": [{"subject": "scripts/hold --dry-run", "claim": "writes nothing", "proof": ["scripts/hold.js:12"],
                    "effects": [], "search": "read scripts/hold.js and its imports"}],
        "lists": [{"what": "order-statuses", "derived_from": "the CHECK constraint", "members": ["open", "held"]}],
        "consensus": {"run": "wf_abc123", "enumerators": "3/3", "critic": True, "single_source": 2, "dropped": []},
    }],
}
PLAN_CHECK_PATH = ".claude/state/ABC-12/plan-check.json"
INVENTORY_PATH = ".claude/state/ABC-12/inventory.json"


def dumps(obj):
    return json.dumps(obj, indent=2)


def variant(base, path, value):
    """A deep copy of base with the item at path (keys and list indexes) replaced; value None-sentinel deletes."""
    out = json.loads(json.dumps(base))
    node = out
    for key in path[:-1]:
        node = node[key]
    if value is DELETE:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return out


DELETE = object()
GOOD = {
    "triage": "# Triage ABC-12\n\n%s\n|---|---|---|---|---|---|---|---|---|---|\n| C1 | S4 | x | y | z | a | b | c | d | |\n"
              % HEADER,
    "operate": "Self-review: ABC-12\nFingerprint: %s\nCovers: whole branch\nInventory: Plan\n" % FP,
    "post-op": "# Post-op\n\nFingerprint: %s\nResult: clean\n" % FP,
    "handoff": "---\nbranch: feature/abc-12-x\n---\n# Handoff\n\n## Git state\nBranch: feature/abc-12-x. Ahead: 1.\n",
}
PATHS = {"triage": ".claude/state/ABC-12/triage.md", "operate": ".claude/state/ABC-12/self-review.md",
         "post-op": ".claude/state/ABC-12/post-op.md", "handoff": ".claude/handoffs/latest.md"}


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = os.path.realpath(self._tmp.name)

    def run_cli(self, *args, stdin=""):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.project)
        return subprocess.run([sys.executable, HOOK] + list(args), input=stdin, capture_output=True, text=True,
                              env=env, cwd=self.project, timeout=30)

    def write(self, rel, text, age=0):
        if rel == PATHS["operate"] and not os.path.exists(os.path.join(self.project, INVENTORY_PATH)):
            self.write(INVENTORY_PATH, dumps(INVENTORY))  # /operate writes the inventory before its record
        if rel == PATHS["triage"] and not os.path.exists(os.path.join(self.project, PLAN_CHECK_PATH)):
            self.write(PLAN_CHECK_PATH, dumps(PLAN_CHECK))  # triage Step 4.8 writes it with the contract
        path = os.path.join(self.project, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        if age:
            t = time.time() - age
            os.utime(path, (t, t))
        return path

    def start(self, kind, age=0):
        args = ["--start", kind] + ([] if kind == "handoff" else ["--ticket", TICKET])
        r = self.run_cli(*args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        marker = self.marker(kind, "started")
        self.assertTrue(os.path.isfile(marker))
        if age:
            with open(marker, "w", encoding="utf-8") as fh:
                fh.write("%f\n" % (time.time() - age))
        return marker

    def marker(self, kind, state):
        base = os.path.join(self.project, ".claude", "state")
        d = base if kind == "handoff" else os.path.join(base, TICKET)
        return os.path.join(d, ".%s-%s" % (state, kind))

    def check(self, kind):
        return self.run_cli("--kind", kind, *([] if kind == "handoff" else ["--ticket", TICKET]))

    def stop(self, **event):
        return self.run_cli("--stop", stdin=json.dumps(dict({"hook_event_name": "Stop", "cwd": self.project},
                                                            **event)))


class Kinds(Case):
    def test_each_kind_passes_with_a_good_record(self):
        for kind in GOOD:
            with self.subTest(kind=kind):
                self.start(kind)
                time.sleep(0.01)
                self.write(PATHS[kind], GOOD[kind])
                r = self.check(kind)
                self.assertEqual(r.returncode, 0, r.stdout)
                self.assertFalse(os.path.exists(self.marker(kind, "started")))
                self.assertTrue(os.path.exists(self.marker(kind, "checked")))  # renamed, never deleted

    def test_missing_file(self):
        for kind in GOOD:
            with self.subTest(kind=kind):
                r = self.check(kind)
                self.assertEqual(r.returncode, 1)
                self.assertIn("doesn't exist", r.stdout)

    def test_malformed_records(self):
        bad = {
            "triage": ["# Triage\n\nno table\n", "%s\n|---|\n" % HEADER],
            "operate": ["Fingerprint: abc\n", "Fingerprint: <h>\n", "Self-review only\n"],
            "post-op": ["Fingerprint: %s\n" % FP, "Result: clean\n", "Fingerprint: %s\nResult: done\n" % FP],
            "handoff": ["# Handoff\n\nno git state\n", "## Git state\nUncommitted: clean\n"],
        }
        for kind, texts in bad.items():
            for text in texts:
                with self.subTest(kind=kind, text=text[:20]):
                    self.write(PATHS[kind], text)
                    self.assertEqual(self.check(kind).returncode, 1)

    def test_post_op_docs_only_and_other_results(self):
        for text in ("Fingerprint: none (no reviewable change)\nResult: clean\n",
                     "Fingerprint: %s\nResult: escalate\n" % FP):
            with self.subTest(text=text[:30]):
                self.write(PATHS["post-op"], text)
                self.assertEqual(self.check("post-op").returncode, 0)

    def test_post_op_capped_is_no_longer_an_end_state(self):
        self.write(PATHS["post-op"], "Fingerprint: %s\nResult: capped\n" % FP)
        r = self.check("post-op")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no `capped` end state", r.stdout)

    def test_triage_needs_the_plan_check(self):
        self.write(PATHS["triage"], GOOD["triage"])
        os.rename(os.path.join(self.project, PLAN_CHECK_PATH), os.path.join(self.project, PLAN_CHECK_PATH + ".moved"))
        r = self.check("triage")
        self.assertEqual(r.returncode, 1)
        self.assertIn("plan-check.json doesn't exist", r.stdout)

    def test_plan_check_boxes(self):
        cases = {
            "`state_homes` is empty": variant(PLAN_CHECK, ["state_homes"], []),
            "`home` is empty": variant(PLAN_CHECK, ["state_homes", 0, "home"], " "),
            "`readers` needs path:line": variant(PLAN_CHECK, ["state_homes", 0, "readers"], ["the jobs"]),
            "`second_home` needs": variant(PLAN_CHECK, ["state_homes", 0, "second_home"],
                                           {"where": "cache", "kept_in_step_by": "a hook", "owner_ok": "x"}),
            "no `contradiction_check`": variant(PLAN_CHECK, ["contradiction_check"], DELETE),
            "`rows_read` must be a whole number": variant(PLAN_CHECK, ["contradiction_check", "rows_read"], "1"),
            "resolved_by": variant(PLAN_CHECK, ["contradiction_check", "conflicts"], [{"conflict": "C2 vs D4"}]),
            "empty `removed`": variant(PLAN_CHECK, ["lifecycles", 0, "removed"], ""),
            "`lifecycles` is empty": variant(PLAN_CHECK, ["lifecycles"], []),
            "owner_answer": variant(PLAN_CHECK, ["safety_defaults"], [{"default": "on error, skip"}]),
            "`enumerations` is empty": variant(PLAN_CHECK, ["enumerations"], []),
            "empty `test`": variant(PLAN_CHECK, ["enumerations", 0, "test"], ""),
        }
        for want, data in cases.items():
            with self.subTest(want=want):
                self.write(PLAN_CHECK_PATH, dumps(data))
                self.write(PATHS["triage"], GOOD["triage"])
                r = self.check("triage")
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn(want, r.stdout)
        self.write(PLAN_CHECK_PATH, "{ not json")
        self.assertIn("isn't valid JSON", self.check("triage").stdout)

    def test_plan_check_none_boxes_and_new_writers(self):
        data = variant(variant(PLAN_CHECK, ["state_homes"], []), ["state_homes_none"], "docs-only ticket")
        data = variant(variant(data, ["lifecycles"], []), ["lifecycles_none"], "no state added")
        data = variant(variant(data, ["enumerations"], []), ["enumerations_none"], "the change keeps no list")
        self.write(PLAN_CHECK_PATH, dumps(data))
        self.write(PATHS["triage"], GOOD["triage"])
        self.assertEqual(self.check("triage").returncode, 0)
        data = variant(PLAN_CHECK, ["state_homes", 0, "writers"], ["new: api/hold.js"])
        data = variant(data, ["state_homes", 0, "second_home"],
                       {"where": "search index", "kept_in_step_by": "trigger", "owner_ok": "comment 812"})
        self.write(PLAN_CHECK_PATH, dumps(data))
        self.assertEqual(self.check("triage").returncode, 0, self.check("triage").stdout)

    def test_operate_needs_the_inventory(self):
        self.write(PATHS["operate"], GOOD["operate"])
        os.rename(os.path.join(self.project, INVENTORY_PATH), os.path.join(self.project, INVENTORY_PATH + ".moved"))
        r = self.check("operate")
        self.assertEqual(r.returncode, 1)
        self.assertIn("inventory.json doesn't exist", r.stdout)

    def test_operate_inventory_boxes(self):
        v = ["sections", 0, "values", 0]
        b = ["sections", 0, "siblings", 0]
        cases = {
            "no `Inventory:": (GOOD["operate"].replace("Inventory: Plan\n", ""), INVENTORY),
            "no section named `Fix batch 1`": (GOOD["operate"].replace("Plan", "Fix batch 1"), INVENTORY),
            "`values` is empty": (GOOD["operate"], variant(INVENTORY, v[:-1], [])),
            "`readers` needs path:line": (GOOD["operate"], variant(INVENTORY, v + ["readers"], ["the jobs"])),
            "`search` is empty": (GOOD["operate"], variant(INVENTORY, v + ["search"], "")),
            "`needs_change`": (GOOD["operate"], variant(INVENTORY, v + ["needs_change"], {"answer": "no"})),
            "`sibling` needs a path:line": (GOOD["operate"], variant(INVENTORY, b + ["sibling"], "the retry job")),
            "`guards` lists": (GOOD["operate"], variant(INVENTORY, b + ["guards"], [])),
            "`copied`": (GOOD["operate"], variant(INVENTORY, b + ["copied"], {"answer": "not applicable"})),
            "`siblings` is empty": (GOOD["operate"], variant(INVENTORY, b[:-1], [])),
            "helpers[1]": (GOOD["operate"], variant(INVENTORY, ["sections", 0, "helpers", 0, "where"], "lib")),
            "no `consensus`": (GOOD["operate"], variant(INVENTORY, ["sections", 0, "consensus"], DELETE)),
            "siblings[1] (hold retry): `search`": (GOOD["operate"], variant(INVENTORY, b + ["search"], "")),
            "claims[1]": (GOOD["operate"], variant(INVENTORY, ["sections", 0, "claims", 0, "proof"], ["the script"])),
            "lists[1]": (GOOD["operate"], variant(INVENTORY, ["sections", 0, "lists", 0, "members"], [])),
        }
        for want, (record, inventory) in cases.items():
            with self.subTest(want=want):
                self.write(INVENTORY_PATH, dumps(inventory))
                self.write(PATHS["operate"], record)
                r = self.check("operate")
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn(want, r.stdout)

    def test_operate_fix_batch_and_none_boxes(self):
        data = json.loads(dumps(INVENTORY))
        data["sections"].append({"name": "Fix batch 1", "values": [], "values_none_search": "git diff --stat",
                                 "consensus": {"run": "wf_fix1", "enumerators": "3/3"}})
        self.write(INVENTORY_PATH, dumps(data))
        self.write(PATHS["operate"], GOOD["operate"] + "\nSelf-review: ABC-12\nFingerprint: %s\n"
                   "Covers: fix batch since %s\nInventory: Fix batch 1\n" % ("cd" * 32, FP))
        r = self.check("operate")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_operate_fix_batch_names_its_fix_notes(self):
        rounds = ".claude/state/ABC-12/review-rounds.md"
        record = (GOOD["operate"] + "\nSelf-review: ABC-12\nFingerprint: %s\n"
                  "Covers: fix batch since %s\nInventory: Fix note R2\n" % ("cd" * 32, FP))
        self.write(PATHS["operate"], record)
        r = self.check("operate")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("review-rounds.md doesn't exist", r.stdout)
        for text, code, want in (("Review round 2: ABC-12\nFix note R2:\n", 1, "no line starting `Fix note R2:`"),
                                 ("Fix note R1: hold() — exits: a.js:3\n", 1, "no line starting `Fix note R2:`"),
                                 ("Fix note R2: hold() — exits: a.js:3 · callers: b.js:9\n", 0, "")):
            with self.subTest(text=text):
                self.write(rounds, text)
                r = self.check("operate")
                self.assertEqual(r.returncode, code, r.stdout)
                self.assertIn(want, r.stdout)

    def test_show_renders_the_readable_copy(self):
        self.write(PLAN_CHECK_PATH, dumps(PLAN_CHECK))
        self.write(INVENTORY_PATH, dumps(INVENTORY))
        r = self.run_cli("--show", "plan-check", "--ticket", TICKET)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("| order status | orders.status | api/orders.js:40 |", r.stdout)
        self.assertIn("No conflicts found.", r.stdout)
        r = self.run_cli("--show", "inventory", "--ticket", TICKET)
        self.assertIn("scripts/hold --dry-run", r.stdout)
        self.assertIn("Built by wf_abc123", r.stdout)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("### Plan", r.stdout)
        self.assertIn("| hold retry | jobs/retry.js:20 | budget, idempotency | yes |", r.stdout)
        self.write(INVENTORY_PATH, "[")
        self.assertEqual(self.run_cli("--show", "inventory", "--ticket", TICKET).returncode, 1)

    def test_last_fingerprint_line_is_the_record(self):
        self.write(PATHS["operate"], GOOD["operate"] + "\nSelf-review: ABC-12\nFingerprint: <h>\n")
        self.assertEqual(self.check("operate").returncode, 1)
        self.write(PATHS["operate"], "Fingerprint: <h>\n\n" + GOOD["operate"])
        self.assertEqual(self.check("operate").returncode, 0)

    def test_lower_case_ticket(self):
        self.write(PATHS["triage"], GOOD["triage"])
        self.assertEqual(self.run_cli("--kind", "triage", "--ticket", "abc-12").returncode, 0)

    def test_stale_record_from_before_the_start(self):
        self.write(PATHS["operate"], GOOD["operate"], age=600)
        self.start("operate")
        r = self.check("operate")
        self.assertEqual(r.returncode, 1)
        self.assertIn("older than the command's start", r.stdout)

    def test_no_ticket_fails_open(self):
        r = self.run_cli("--kind", "triage")
        self.assertEqual(r.returncode, 0)
        self.assertIn("no ticket", r.stdout)
        self.assertEqual(self.run_cli("--start", "operate", "--ticket", "../etc").returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.project, ".claude", "etc")))


class Stop(Case):
    def test_no_markers_is_free(self):
        r = self.stop()
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr, "")

    def test_open_marker_blocks_with_what_is_missing(self):
        self.start("post-op")
        r = self.stop()
        self.assertEqual(r.returncode, 2)
        self.assertIn("/post-op for ABC-12", r.stderr)
        self.assertIn("--kind post-op --ticket ABC-12", r.stderr)

    def test_stop_hook_active_passes(self):
        self.start("triage")
        self.assertEqual(self.stop(stop_hook_active=True).returncode, 0)

    def test_complete_record_passes_and_closes_the_marker(self):
        self.start("handoff")
        time.sleep(0.01)
        self.write(PATHS["handoff"], GOOD["handoff"])
        self.assertEqual(self.stop().returncode, 0)
        self.assertTrue(os.path.exists(self.marker("handoff", "checked")))
        self.assertEqual(self.stop().returncode, 0)

    def test_stale_marker_is_abandoned_once(self):
        self.start("operate", age=25 * 3600)
        self.assertEqual(self.stop().returncode, 0)
        self.assertTrue(os.path.exists(self.marker("operate", "abandoned")))
        self.assertEqual(self.stop().stderr, "")

    def test_stale_but_complete_record_is_checked(self):
        self.write(PATHS["triage"], GOOD["triage"])
        self.start("triage", age=25 * 3600)
        os.utime(os.path.join(self.project, PATHS["triage"]))
        self.assertEqual(self.stop().returncode, 0)
        self.assertTrue(os.path.exists(self.marker("triage", "checked")))

    def test_one_nudge_per_marker(self):
        # /post-op waiting on its background review: reminded once, never trapped
        self.start("post-op")
        r = self.stop()
        self.assertEqual(r.returncode, 2)
        self.assertIn("won't repeat", r.stderr)
        self.assertIn("--cancel post-op", r.stderr)
        self.assertEqual(self.stop().returncode, 0)
        self.assertTrue(os.path.exists(self.marker("post-op", "started")))  # still open, just quiet

    def test_cancel(self):
        self.start("triage")
        r = self.run_cli("--cancel", "triage", "--ticket", TICKET)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(os.path.exists(self.marker("triage", "cancelled")))
        self.assertEqual(self.stop().returncode, 0)

    def test_renames_never_overwrite(self):
        for _ in range(2):
            self.start("triage")
            self.write(PATHS["triage"], GOOD["triage"])
            self.assertEqual(self.check("triage").returncode, 0)
        d = os.path.dirname(self.marker("triage", "checked"))
        self.assertEqual(len([f for f in os.listdir(d) if f.startswith(".checked-triage")]), 2)

    def test_fail_open(self):
        r = self.run_cli("--stop", stdin="{nope")
        self.assertEqual(r.returncode, 0)
        self.assertIn("allowing the stop", r.stderr)


class OtherTickets(Case):
    def test_only_the_current_branchs_ticket_is_checked(self):
        with open(os.path.join(self.project, "CLAUDE.md"), "w", encoding="utf-8") as fh:
            fh.write("| Fact | Value |\n|---|---|\n| `TICKET_PREFIX` | ABC |\n| `BRANCH_PREFIX` | feature/ |\n")
        subprocess.run(["git", "init", "-q", self.project], check=True)
        subprocess.run(["git", "-C", self.project, "symbolic-ref", "HEAD", "refs/heads/feature/abc-99-other"],
                       check=True)
        self.start("operate")  # ABC-12, paused
        self.assertEqual(self.stop().returncode, 0)
        subprocess.run(["git", "-C", self.project, "symbolic-ref", "HEAD", "refs/heads/feature/abc-12-x"], check=True)
        self.assertEqual(self.stop().returncode, 2)


class ReviewRound2(Case):
    def test_lower_case_record_dir(self):
        self.write(".claude/state/abc-12/triage.md", GOOD["triage"])
        self.write(".claude/state/abc-12/plan-check.json", dumps(PLAN_CHECK))  # found in the same lower-case dir
        self.assertEqual(self.run_cli("--kind", "triage", "--ticket", "abc-12").returncode, 0)

    def test_marker_without_a_time_still_nudges_once(self):
        path = os.path.join(self.project, ".claude", "state", TICKET, ".started-operate")
        os.makedirs(os.path.dirname(path))
        open(path, "w").close()
        self.assertEqual(self.stop().returncode, 2)
        self.assertEqual(self.stop().returncode, 0)

    def test_turn_ending_in_another_checkout(self):
        self.start("post-op")
        with tempfile.TemporaryDirectory() as scratch:
            r = self.run_cli("--stop", stdin=json.dumps({"cwd": scratch}))
        self.assertEqual(r.returncode, 2)  # $CLAUDE_PROJECT_DIR's records are still checked

    def test_post_op_closing_lines_are_the_record(self):
        self.write(PATHS["post-op"], "Quoted: \nFingerprint: %s\nResult: clean\n\nFingerprint: <output of node …>\n"
                                     "Result: clean | escalate\n" % FP)
        self.assertEqual(self.check("post-op").returncode, 1)

    def test_start_that_cannot_write_fails_open(self):
        os.makedirs(os.path.join(self.project, ".claude"))
        open(os.path.join(self.project, ".claude", "state"), "w").close()  # a file where the dir should be
        r = self.run_cli("--start", "triage", "--ticket", TICKET)
        self.assertEqual(r.returncode, 0)
        self.assertIn("couldn't write", r.stdout)

    def test_no_markers_runs_no_git(self):
        r = self.run_cli("--stop", stdin=json.dumps({"cwd": self.project}))
        self.assertEqual((r.returncode, r.stderr), (0, ""))


class ReviewRound3(Case):
    def test_project_path_with_glob_characters(self):
        odd = os.path.join(self.project, "p [x]")
        os.makedirs(odd)
        self.project = odd
        self.start("triage")
        self.assertEqual(self.stop().returncode, 2)

    def test_operate_needs_a_new_block(self):
        self.write(PATHS["operate"], GOOD["operate"])
        self.start("operate")
        time.sleep(0.01)
        with open(os.path.join(self.project, PATHS["operate"]), "a", encoding="utf-8") as fh:
            fh.write("a partial note\n")
        r = self.check("operate")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no new Self-review block", r.stdout)
        with open(os.path.join(self.project, PATHS["operate"]), "a", encoding="utf-8") as fh:
            fh.write("Self-review: ABC-12\nFingerprint: %s\nInventory: Plan\n" % ("cd" * 32))
        self.assertEqual(self.check("operate").returncode, 0)

    def test_restart_keeps_the_earlier_marker(self):
        self.start("triage")
        self.start("triage")
        d = os.path.dirname(self.marker("triage", "started"))
        self.assertTrue(any(f.startswith(".abandoned-triage") for f in os.listdir(d)))

    def test_handoff_branch_line_must_be_in_git_state(self):
        self.write(PATHS["handoff"], "# Handoff\n\n## Git state\n\n## Pick up here\nBranch: x\n")
        self.assertEqual(self.check("handoff").returncode, 1)

    def test_unwritable_marker_is_not_nudged(self):
        marker = self.start("post-op")
        os.chmod(marker, 0o444)
        self.addCleanup(os.chmod, marker, 0o644)
        self.assertEqual(self.stop().returncode, 0)


class TicketFromBranch(Case):
    def test_branch_names_the_ticket(self):
        with open(os.path.join(self.project, "CLAUDE.md"), "w", encoding="utf-8") as fh:
            fh.write("| Fact | Value |\n|---|---|\n| `TICKET_PREFIX` | ABC |\n| `BRANCH_PREFIX` | feature/ |\n")
        subprocess.run(["git", "init", "-q", self.project], check=True)
        subprocess.run(["git", "-C", self.project, "symbolic-ref", "HEAD", "refs/heads/feature/abc-12-x"], check=True)
        r = self.run_cli("--start", "operate")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(os.path.isfile(self.marker("operate", "started")))


if __name__ == "__main__":
    unittest.main()
