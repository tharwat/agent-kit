#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""
Tests for make_skill_links.py (stdlib unittest, no dependencies).

Each test builds a small throwaway repo in tempfile.TemporaryDirectory, runs the
generator against it with --repo, and asserts the exit code, the reported status
and what is (or isn't) on disk. Generated repos are also run through
check_skill_links.py, so the two scripts agree on what a wrapper is.

Run: python3 .github/scripts/test_make_skill_links.py
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "make_skill_links.py")
CHECKER = os.path.join(HERE, "check_skill_links.py")
sys.dont_write_bytecode = True
sys.path.insert(0, HERE)
import make_skill_links as msl  # noqa: E402

SHIP = '---\ndescription: Take a reviewed branch to a merged PR.\nargument-hint: "[<ticket>]"\n---\n\n# ship\n'
VERIFY = "---\ndescription: Drive the change end to end.\n---\n\n# verify\n"


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="make-skill-links-")
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.write(".claude/commands/ship.md", SHIP)
        self.write(".claude/commands/verify.md", VERIFY)
        self.write("AGENTS.md", "Read [CLAUDE.md](CLAUDE.md).\n")
        self.write("CLAUDE.md", "# rules\n")

    def path(self, rel):
        return os.path.join(self.root, rel)

    def write(self, rel, text):
        os.makedirs(os.path.dirname(self.path(rel)), exist_ok=True)
        with open(self.path(rel), "w", encoding="utf-8") as f:
            f.write(text)

    def read(self, rel):
        with open(self.path(rel), encoding="utf-8") as f:
            return f.read()

    def run_gen(self, *args):
        r = subprocess.run([sys.executable, SCRIPT, "--repo", self.root, *args], capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def gen_ok(self, *args):
        code, out = self.run_gen(*args)
        self.assertEqual(code, 0, out)
        self.assertNotIn("Traceback", out)
        return out

    def gen_fails(self, *args):
        code, out = self.run_gen(*args)
        self.assertEqual(code, 1, out)
        self.assertNotIn("Traceback", out)
        return out

    def checker(self):
        r = subprocess.run([sys.executable, CHECKER, "--repo", self.root], capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr


class GenerateTests(Base):
    def test_creates_wrappers_that_the_checker_accepts(self):
        out = self.gen_ok()
        self.assertIn("create: .agents/skills/ship/SKILL.md", out)
        self.assertIn("create: .agents/skills/verify/SKILL.md", out)
        text = self.read(".agents/skills/ship/SKILL.md")
        self.assertTrue(text.startswith("---\nname: ship\ndescription: Take a reviewed branch to a merged PR.\n---\n"))
        self.assertIn("[the canonical ship workflow](../../../.claude/commands/ship.md)", text)
        self.assertIn("](../../../AGENTS.md)", text)
        self.assertIn("Invocation: `$ship [<ticket>]`.", text)
        self.assertIn("Invocation: `$verify`.", self.read(".agents/skills/verify/SKILL.md"))
        self.assertNotIn("Take a reviewed branch to a merged PR.\n\n#", text.split("---", 2)[2])  # no command body
        code, cout = self.checker()
        self.assertEqual(code, 0, cout)
        self.assertIn("2 Codex skill(s) link to their Claude command", cout)

    def test_wrapper_holds_no_command_text(self):
        self.write(".claude/commands/ship.md", SHIP + "\n## Step 1\n\nA unique instruction line.\n")
        self.gen_ok()
        self.assertNotIn("A unique instruction line", self.read(".agents/skills/ship/SKILL.md"))

    def test_second_run_is_unchanged_and_writes_nothing(self):
        self.gen_ok()
        p = self.path(".agents/skills/ship/SKILL.md")
        os.utime(p, (1_000_000, 1_000_000))
        out = self.gen_ok()
        self.assertIn("unchanged: .agents/skills/ship/SKILL.md", out)
        self.assertIn("summary: 2 unchanged", out)
        self.assertEqual(os.stat(p).st_mtime, 1_000_000)

    def test_kit_made_wrapper_is_updated(self):
        self.gen_ok()
        self.write(".claude/commands/ship.md", SHIP.replace("merged PR", "merged pull request"))
        out = self.gen_ok()
        self.assertIn("update: .agents/skills/ship/SKILL.md", out)
        self.assertIn("merged pull request", self.read(".agents/skills/ship/SKILL.md"))

    def test_hand_written_wrapper_is_a_conflict_and_untouched(self):
        hand = "---\nname: ship\ndescription: mine\n---\n[w](../../../.claude/commands/ship.md)\n"
        self.write(".agents/skills/ship/SKILL.md", hand)
        out = self.gen_fails()
        self.assertIn("conflict: .agents/skills/ship/SKILL.md", out)
        self.assertEqual(self.read(".agents/skills/ship/SKILL.md"), hand)
        self.assertIn("create: .agents/skills/verify/SKILL.md", out)  # the rest still proceeds

    def test_force_wrappers_backs_up_then_replaces(self):
        hand = "---\nname: ship\ndescription: mine\n---\nHand-written.\n"
        self.write(".agents/skills/ship/SKILL.md", hand)
        out = self.gen_ok("--force-wrappers")
        self.assertIn("replace: .agents/skills/ship/SKILL.md (old wrapper saved as SKILL.md.pre-agent-kit)", out)
        self.assertEqual(self.read(".agents/skills/ship/SKILL.md.pre-agent-kit"), hand)
        self.assertIn(msl.MARKER, self.read(".agents/skills/ship/SKILL.md"))
        code, cout = self.checker()
        self.assertEqual(code, 0, cout)
        self.assertIn("backup of a replaced wrapper", cout)

    def test_force_wrappers_never_overwrites_an_existing_backup(self):
        self.write(".agents/skills/ship/SKILL.md", "hand v2\n")
        self.write(".agents/skills/ship/SKILL.md.pre-agent-kit", "hand v1\n")
        out = self.gen_fails("--force-wrappers")
        self.assertIn("SKILL.md.pre-agent-kit already exists", out)
        self.assertEqual(self.read(".agents/skills/ship/SKILL.md"), "hand v2\n")
        self.assertEqual(self.read(".agents/skills/ship/SKILL.md.pre-agent-kit"), "hand v1\n")

    def test_symlinked_wrapper_is_a_conflict(self):
        self.write("elsewhere.md", "x\n")
        os.makedirs(self.path(".agents/skills/ship"))
        os.symlink(self.path("elsewhere.md"), self.path(".agents/skills/ship/SKILL.md"))
        out = self.gen_fails()
        self.assertIn("conflict: .agents/skills/ship/SKILL.md", out)
        self.assertEqual(self.read("elsewhere.md"), "x\n")

    def test_stale_wrapper_is_reported_never_removed(self):
        self.gen_ok()
        os.rename(self.path(".claude/commands/verify.md"), self.path("verify.md.moved"))
        out = self.gen_fails()
        self.assertIn("stale: .agents/skills/verify/SKILL.md", out)
        self.assertIn("suggest renaming it to .agents/skills/verify/SKILL.md.pre-agent-kit", out)
        self.assertTrue(os.path.isfile(self.path(".agents/skills/verify/SKILL.md")))

    def test_hand_written_wrapper_of_a_gone_command_is_stale(self):
        self.write(".agents/skills/old/SKILL.md", "---\nname: old\n---\n[w](../../../.claude/commands/old.md)\n")
        out = self.gen_fails()
        self.assertIn("stale: .agents/skills/old/SKILL.md", out)

    def test_native_skill_is_ignored(self):
        native = "---\nname: helper\ndescription: third party\n---\nDo things.\n"
        self.write(".agents/skills/helper/SKILL.md", native)
        out = self.gen_ok()
        self.assertNotIn("helper", out)
        self.assertEqual(self.read(".agents/skills/helper/SKILL.md"), native)

    def test_claude_only_command_is_skipped(self):
        self.write(".agents/claude-only.txt", "# Claude-only commands\nverify  # needs a Claude-only tool\n")
        out = self.gen_ok()
        self.assertIn("skipped: .agents/skills/verify/SKILL.md", out)
        self.assertFalse(os.path.exists(self.path(".agents/skills/verify")))

    def test_kit_wrapper_for_a_claude_only_command_is_stale(self):
        self.gen_ok()
        self.write(".agents/claude-only.txt", "verify\n")
        out = self.gen_fails()
        self.assertIn("stale: .agents/skills/verify/SKILL.md ('verify' is Claude-only", out)
        self.assertTrue(os.path.isfile(self.path(".agents/skills/verify/SKILL.md")))

    def test_unknown_claude_only_entry_warns(self):
        self.write(".agents/claude-only.txt", "nothing-here\n")
        out = self.gen_ok()
        self.assertIn("warning: .agents/claude-only.txt lists 'nothing-here'", out)

    def test_check_writes_nothing(self):
        out = self.gen_fails("--check")
        self.assertIn("would create: .agents/skills/ship/SKILL.md", out)
        self.assertFalse(os.path.exists(self.path(".agents")))
        self.gen_ok()
        self.assertIn("summary: 2 unchanged", self.gen_ok("--check"))

    def test_check_with_force_writes_nothing(self):
        self.write(".agents/skills/ship/SKILL.md", "hand\n")
        out = self.gen_fails("--check", "--force-wrappers")
        self.assertIn("would replace: .agents/skills/ship/SKILL.md", out)
        self.assertEqual(self.read(".agents/skills/ship/SKILL.md"), "hand\n")
        self.assertFalse(os.path.exists(self.path(".agents/skills/ship/SKILL.md.pre-agent-kit")))

    def test_missing_description_is_an_error(self):
        self.write(".claude/commands/bare.md", "# bare\n")
        out = self.gen_fails()
        self.assertIn("error: .agents/skills/bare/SKILL.md (.claude/commands/bare.md has no description:", out)
        self.assertFalse(os.path.exists(self.path(".agents/skills/bare")))

    def test_unreadable_command_is_an_error(self):
        with open(self.path(".claude/commands/bad.md"), "wb") as f:
            f.write(b"\xff\xfe")
        self.assertIn("cannot be read as UTF-8", self.gen_fails())

    def test_missing_commands_dir_fails(self):
        with tempfile.TemporaryDirectory() as empty:
            r = subprocess.run([sys.executable, SCRIPT, "--repo", empty], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn(".claude/commands not found", r.stdout)

    def test_description_needing_quotes_round_trips(self):
        self.write(".claude/commands/guard.md",
                   "---\ndescription: Migration guard. Validates a change: additive policy.\n---\n")
        self.write(".claude/commands/count.md", '---\ndescription: "Counts the # of steps"\n---\n')
        self.gen_ok()
        self.assertIn('description: "Migration guard. Validates a change: additive policy."\n',
                      self.read(".agents/skills/guard/SKILL.md"))
        self.assertIn('description: "Counts the # of steps"\n', self.read(".agents/skills/count/SKILL.md"))

    def test_source_never_calls_a_delete(self):
        with open(SCRIPT, encoding="utf-8") as f:
            src = f.read()
        self.assertIsNone(re.search(r"os\.remove|os\.unlink|rmtree|rmdir|\.unlink\(", src))


class FrontmatterTests(unittest.TestCase):
    def test_plain_quoted_and_block_values(self):
        fv = msl.frontmatter_value
        self.assertEqual(fv("---\ndescription: plain text # note\n---\n", "description"), "plain text")
        self.assertEqual(fv('---\ndescription: "say \\"hi\\": now"\n---\n', "description"), 'say "hi": now')
        self.assertEqual(fv("---\ndescription: 'it''s fine'\n---\n", "description"), "it's fine")
        self.assertEqual(fv("---\ndescription: >\n  folded\n  text\nother: x\n---\n", "description"), "folded text")
        self.assertEqual(fv("---\ndescription: first\n  second\n---\n", "description"), "first second")
        self.assertIsNone(fv("---\nother: x\n---\n", "description"))
        self.assertIsNone(fv("description: not frontmatter\n", "description"))
        self.assertEqual(fv('---\nargument-hint: "[<ticket>]"\n---\n', "argument-hint"), "[<ticket>]")

    def test_yaml_scalar_quotes_only_when_needed(self):
        ys = msl.yaml_scalar
        self.assertEqual(ys("Plain words, and more."), "Plain words, and more.")
        self.assertEqual(ys("a: b"), '"a: b"')
        self.assertEqual(ys("[x]"), '"[x]"')
        self.assertEqual(ys("true"), '"true"')
        self.assertEqual(ys('say "hi"'), 'say "hi"')
        self.assertEqual(ys("- dash"), '"- dash"')

    def test_hint_with_backtick_is_dropped(self):
        self.assertIn("Invocation: `$x`.", msl.render("x", "d", "`bad`"))

    def test_copyright_follows_the_frontmatter(self):
        text = msl.render("x", "d", None)
        self.assertTrue(text.startswith("---\nname: x\ndescription: d\n---\n" + msl.COPYRIGHT + "\n\n# x\n"), text)
        self.assertEqual(msl.COPYRIGHT,
                         "<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->")
        self.assertEqual(msl.frontmatter_value(text, "description"), "d")


if __name__ == "__main__":
    unittest.main(verbosity=2)
