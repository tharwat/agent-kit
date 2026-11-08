#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""
Tests for check_skill_links.py (stdlib unittest, no dependencies).

Each test builds a small throwaway git repo with the Claude/Codex layout, runs the
check against it, and asserts the exit code AND the reason in the output, so a
test only passes when the check fails for the right cause. Temp repos live in
tempfile.TemporaryDirectory and are cleaned up by it.

Run: python3 .github/scripts/test_check_skill_links.py
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "check_skill_links.py")
sys.dont_write_bytecode = True
sys.path.insert(0, HERE)
import check_skill_links as csl  # noqa: E402


def skill_md(name):
    return (f"---\nname: {name}\ndescription: test\n---\n\n# {name}\n\n"
            f"1. Read [the canonical workflow](../../../.claude/commands/{name}.md) and "
            f"[AGENTS.md](../../../AGENTS.md).\n")


def lock_hash(files):
    """sha256 of relpath + bytes, in the given order (the lock's format)."""
    h = hashlib.sha256()
    for rel, data in files:
        h.update(rel.encode("utf-8"))
        h.update(data)
    return h.hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="skill-links-")
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        subprocess.run(["git", "init", "-q", self.root], check=True)
        for name in ("ship", "verify"):
            self.write(f".claude/commands/{name}.md", f"# {name}\n")
            self.write(f".agents/skills/{name}/SKILL.md", skill_md(name))
        self.write(".claude/rules/tracker.md", "# tracker rules\n")
        self.write("AGENTS.md", "Read [CLAUDE.md](CLAUDE.md) in full.\n")
        self.write("CLAUDE.md", "# rules\n")

    def path(self, rel):
        return os.path.join(self.root, rel)

    def write(self, rel, text):
        os.makedirs(os.path.dirname(self.path(rel)), exist_ok=True)
        with open(self.path(rel), "w", encoding="utf-8") as f:
            f.write(text)

    def write_bytes(self, rel, data):
        os.makedirs(os.path.dirname(self.path(rel)), exist_ok=True)
        with open(self.path(rel), "wb") as f:
            f.write(data)

    def move_aside(self, rel):
        os.rename(self.path(rel), self.path(rel) + ".moved")

    def check(self, *args, cwd=None, env=None):
        r = subprocess.run([sys.executable, SCRIPT, *args], cwd=cwd or self.root, capture_output=True, text=True,
                           env=env)
        return r.returncode, r.stdout + r.stderr

    def assertPasses(self, *args):
        code, out = self.check(*args)
        self.assertEqual(code, 0, out)
        return out

    def assertFails(self, reason, *args):
        code, out = self.check(*args)
        self.assertEqual(code, 1, out)
        self.assertIn(reason, out)
        return out


class LinkTests(Base):
    def test_clean_layout_passes(self):
        out = self.assertPasses()
        self.assertIn("2 Codex skill(s) link to their Claude command", out)

    def test_renamed_command_fails_on_both_sides(self):
        os.rename(self.path(".claude/commands/verify.md"), self.path(".claude/commands/verify-local.md"))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn(".agents/skills/verify/SKILL.md: links to missing file", out)
        self.assertIn(".claude/commands/verify-local.md: no Codex skill", out)

    def test_skill_linking_wrong_command_fails(self):
        self.write(".agents/skills/verify/SKILL.md", skill_md("verify").replace("commands/verify.md", "commands/ship.md"))
        self.assertFails("does not link to its canonical command .claude/commands/verify.md")

    def test_new_command_without_skill_fails(self):
        self.write(".claude/commands/brand-new.md", "# new\n")
        self.assertFails(".claude/commands/brand-new.md: no Codex skill")

    def test_claude_only_allowlist_passes(self):
        self.write(".claude/commands/brand-new.md", "# new\n")
        self.write(".agents/claude-only.txt", "brand-new  # Claude-only: test\n")
        out = self.assertPasses()
        self.assertIn("1 Claude-only command(s)", out)

    def test_stale_allowlist_entry_warns_only(self):
        self.write(".agents/claude-only.txt", "gone-command\n")
        out = self.assertPasses()
        self.assertIn("'gone-command' has no matching command", out)

    def test_copied_command_text_fails(self):
        self.write(".agents/skills/ship/references/claude-command.md", "# ship\n")
        self.assertFails("copied command text")

    def test_copied_rule_file_fails(self):
        self.write(".agents/rules/tracker.md", "# tracker rules\n")
        self.assertFails(".agents/rules/tracker.md: copied rule file")

    def test_agents_md_without_claude_pointer_fails(self):
        self.write("AGENTS.md", "Codex notes only.\n")
        self.assertFails("AGENTS.md has no markdown link to CLAUDE.md")

    def test_agents_md_mentioning_claude_md_without_a_link_fails(self):
        self.write("AGENTS.md", "Do not read CLAUDE.md. <!-- [CLAUDE.md](CLAUDE.md) --> `[CLAUDE.md](CLAUDE.md)`\n")
        self.assertFails("AGENTS.md has no markdown link to CLAUDE.md")

    def test_agents_md_must_link_kit_file_when_it_exists(self):
        self.write("CLAUDE.kit.md", "# kit rules\n")
        self.assertFails("AGENTS.md has no markdown link to CLAUDE.kit.md")
        self.write("AGENTS.md", "Read [CLAUDE.md](CLAUDE.md) and [CLAUDE.kit.md](./CLAUDE.kit.md).\n")
        self.assertPasses()

    def test_missing_agents_md_fails(self):
        self.move_aside("AGENTS.md")
        self.assertFails("AGENTS.md is missing")

    def test_native_codex_skill_is_ignored(self):
        self.write(".agents/skills/third-party/SKILL.md", "---\nname: third-party\n---\nNative skill.\n")
        self.write(".agents/skills/third-party/references/guide.md", "# guide\n")
        self.assertPasses()

    def test_runs_from_a_subdirectory(self):
        code, out = self.check(cwd=self.path(".agents/skills"))
        self.assertEqual(code, 0, out)

    def test_repo_flag_works_outside_git(self):
        with tempfile.TemporaryDirectory(prefix="no-git-") as other:
            env = dict(os.environ, GIT_CEILING_DIRECTORIES=os.path.dirname(os.path.realpath(other)))
            r = subprocess.run([sys.executable, SCRIPT], cwd=other, capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("not inside a git work tree", r.stdout)
            r = subprocess.run([sys.executable, SCRIPT, "--repo", self.root], cwd=other, capture_output=True,
                               text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    # --- link parsing ---
    def only_link(self, link_line):
        self.write(".agents/skills/verify/SKILL.md", f"---\nname: verify\n---\n{link_line}\n")

    def test_mdx_suffix_is_not_the_md_file(self):
        self.only_link("[w](../../../.claude/commands/verify.mdx)")
        self.assertFails("does not link to its canonical command .claude/commands/verify.md")

    def test_md_bak_suffix_is_not_the_md_file(self):
        self.only_link("[w](../../../.claude/commands/verify.md.bak)")
        self.assertFails("does not link to its canonical command .claude/commands/verify.md")

    def test_link_inside_fenced_block_does_not_count(self):
        self.only_link("```\n[w](../../../.claude/commands/verify.md)\n```")
        self.assertFails("does not link to its canonical command")

    def test_link_inside_html_comment_does_not_count(self):
        self.only_link("<!-- [w](../../../.claude/commands/verify.md) -->")
        self.assertFails("does not link to its canonical command")

    def test_link_inside_inline_code_does_not_count(self):
        self.only_link("`[w](../../../.claude/commands/verify.md)`")
        self.assertFails("does not link to its canonical command")

    def test_code_span_label_with_real_link_passes(self):
        self.only_link("[`.claude/commands/verify.md`](../../../.claude/commands/verify.md)")
        self.assertPasses()

    def test_angle_bracket_and_anchor_links_pass(self):
        self.only_link("[w](<../../../.claude/commands/verify.md>) and [s](../../../.claude/commands/verify.md#step-1)")
        self.assertPasses()

    def test_reference_link_passes(self):
        self.only_link("Read [the workflow][wf].\n\n[wf]: ../../../.claude/commands/verify.md")
        self.assertPasses()

    def test_wrong_case_link_fails_even_on_case_insensitive_disks(self):
        self.only_link("[w](../../../.claude/commands/Verify.md)")
        self.assertFails("case must match exactly")

    def test_link_after_unclosed_fence_does_not_count(self):
        self.only_link("```\n[w](../../../.claude/commands/verify.md)")
        self.assertFails("does not link to its canonical command")

    def test_link_inside_indented_fence_does_not_count(self):
        self.only_link("  ```\n[w](../../../.claude/commands/verify.md)\n  ```")
        self.assertFails("does not link to its canonical command")

    def test_link_inside_double_backtick_span_does_not_count(self):
        self.only_link("``[w](../../../.claude/commands/verify.md)``")
        self.assertFails("does not link to its canonical command")

    def test_link_in_indented_code_block_does_not_count(self):
        self.only_link("Text.\n\n    [w](../../../.claude/commands/verify.md)")
        self.assertFails("does not link to its canonical command")

    # --- copies and structure ---
    def test_copy_under_another_name_fails(self):
        self.write(".agents/skills/ship/references/ship.md", "# ship\n")
        self.assertFails("references/ship.md: copied command text")

    def test_extra_non_md_file_fails(self):
        self.write(".agents/skills/ship/notes.txt", "x\n")
        self.assertFails("notes.txt: extra file in a linking skill")

    def test_pre_agent_kit_backup_warns_only(self):
        self.write(".agents/skills/ship/SKILL.md.pre-agent-kit", "old wrapper\n")
        out = self.assertPasses()
        self.assertIn("SKILL.md.pre-agent-kit: backup of a replaced wrapper", out)

    def test_backup_name_elsewhere_still_fails(self):
        self.write(".agents/skills/ship/references/SKILL.md.pre-agent-kit", "old\n")
        self.assertFails("extra file in a linking skill")

    def test_copy_in_orphan_skill_dir_fails(self):
        self.write(".agents/skills/old-skill/references/claude-command.md", "# old\n")
        self.assertFails("old-skill/references/claude-command.md: copied command text")

    def test_nested_rules_copy_fails(self):
        self.write(".agents/rules/sub/tracker.md", "# tracker\n")
        self.assertFails(".agents/rules/sub/tracker.md: copied rule file")

    def test_non_md_rules_copy_fails(self):
        self.write(".agents/rules/security.mdc", "# security\n")
        self.assertFails(".agents/rules/security.mdc: copied rule file")

    def test_missing_skills_dir_fails(self):
        self.move_aside(".agents/skills")
        self.assertFails(".agents/skills is missing")

    def test_missing_commands_dir_fails(self):
        self.move_aside(".claude/commands")
        self.assertFails(".claude/commands is missing or has no commands")

    def test_symlinked_command_fails(self):
        real = self.path("elsewhere.md")
        os.rename(self.path(".claude/commands/ship.md"), real)
        os.symlink(real, self.path(".claude/commands/ship.md"))
        self.assertFails(".claude/commands/ship.md: is a symlink")

    def test_symlinked_skill_fails(self):
        real = self.path("elsewhere-skill.md")
        os.rename(self.path(".agents/skills/ship/SKILL.md"), real)
        os.symlink(real, self.path(".agents/skills/ship/SKILL.md"))
        self.assertFails(".agents/skills/ship: skill directory or SKILL.md is a symlink")

    def test_symlinked_dir_inside_wrapper_fails(self):
        os.symlink(self.path(".claude/commands"), self.path(".agents/skills/ship/references"))
        self.assertFails("symlinked directory in a linking skill")

    def test_invalid_utf8_is_a_clean_error(self):
        self.write_bytes(".agents/skills/ship/SKILL.md", b"\xff\xfe not utf-8")
        out = self.assertFails("cannot be read as UTF-8")
        self.assertNotIn("Traceback", out)

    def test_invalid_utf8_command_fails(self):
        self.write_bytes(".claude/commands/ship.md", b"\xff\xfe not utf-8")
        self.assertFails(".claude/commands/ship.md: cannot be read as UTF-8")

    def test_agents_md_dead_rule_link_fails(self):
        self.write("AGENTS.md", "Read [CLAUDE.md](CLAUDE.md) and [tracker](.claude/rules/tracker.md).\n")
        self.assertPasses()
        self.move_aside(".claude/rules/tracker.md")
        self.assertFails("AGENTS.md: links to missing file .claude/rules/tracker.md")

    def test_agents_md_unreadable_rule_link_fails(self):
        self.write("AGENTS.md", "Read [CLAUDE.md](CLAUDE.md) and [tracker](.claude/rules/tracker.md).\n")
        self.write_bytes(".claude/rules/tracker.md", b"\xff\xfe")
        self.assertFails(".claude/rules/tracker.md: cannot be read as UTF-8")


class RestateTests(Base):
    TAG = " <!-- codex-restate -->"
    FORBIDDEN = ["- **No raw SQL** — use the migration tool.", "- **No new packages** without a reason."]

    def claude_md(self, forbidden, tagged_extra=(), tag_forbidden=True, path="CLAUDE.md"):
        tag = self.TAG if tag_forbidden else ""
        body = "# rules\n\n## ⛔ Forbidden actions\n\n" + "".join(f"{l}{tag}\n" for l in forbidden)
        body += "\n## Other\n\n" + "".join(f"{l}{self.TAG}\n" for l in tagged_extra)
        self.write(path, body)

    def agents_md(self, block_lines, pre="Read [CLAUDE.md](CLAUDE.md).\n"):
        self.write("AGENTS.md", pre + "<!-- codex-restate:start -->\n"
                   + "".join(f"{l}\n" for l in block_lines) + "<!-- codex-restate:end -->\n")

    def tagged(self, lines):
        return [l + self.TAG for l in lines]

    def test_exact_restated_block_passes(self):
        self.claude_md(self.FORBIDDEN, ["Never skip the review gate."])
        self.agents_md(self.tagged(self.FORBIDDEN + ["Never skip the review gate."]))
        out = self.assertPasses("--require-restated")
        self.assertIn("3 restated rule line(s) in sync", out)

    def test_drifted_restated_line_fails(self):
        self.claude_md(self.FORBIDDEN)
        self.agents_md(self.tagged(["- **No raw SQL** — use a console.", self.FORBIDDEN[1]]))
        out = self.assertFails("missing tagged line")
        self.assertIn("not a tagged line", out)

    def test_partial_restated_block_fails(self):
        self.claude_md(self.FORBIDDEN)
        self.agents_md(self.tagged(self.FORBIDDEN[:1]))
        self.assertFails("restated block is missing tagged line: - **No new packages**")

    def test_decoy_verbatim_but_untagged_line_fails(self):
        self.claude_md(self.FORBIDDEN)
        self.agents_md(self.tagged(self.FORBIDDEN) + ["---"])
        self.assertFails("not a tagged line (drifted or untagged): ---")

    def test_new_untagged_forbidden_bullet_in_kit_file_fails(self):
        self.claude_md(self.FORBIDDEN, path="CLAUDE.kit.md")
        with open(self.path("CLAUDE.kit.md"), encoding="utf-8") as f:
            text = f.read()
        self.write("CLAUDE.kit.md", text.replace("## Other", "- **No force-push** ever.\n\n## Other"))
        self.agents_md(self.tagged(self.FORBIDDEN), pre=self.KIT_AGENTS)
        self.assertFails("CLAUDE.kit.md: Forbidden actions item is not tagged")

    def test_untagged_forbidden_bullets_in_project_claude_md_pass(self):
        # A project's own CLAUDE.md may keep untagged (and multi-line) Forbidden actions: only its tagged lines are
        # checked. The kit's own file is still held to the rule.
        self.claude_md(self.FORBIDDEN, path="CLAUDE.kit.md")
        self.write("CLAUDE.md", "# project\n\n@CLAUDE.kit.md\n\n## Forbidden actions\n\n"
                   "- **No new packages** without approval.\n- **No CI triggers** — no deploy\n  commands.\n"
                   "- Project rule." + self.TAG + "\n")
        self.agents_md(self.tagged(self.FORBIDDEN + ["- Project rule."]), pre=self.KIT_AGENTS)
        out = self.assertPasses("--require-restated")
        self.assertIn("3 restated rule line(s) in sync", out)
        self.assertNotIn("not tagged", out)

    def test_project_claude_md_tagged_line_must_still_be_restated(self):
        self.claude_md(self.FORBIDDEN, path="CLAUDE.kit.md")
        self.write("CLAUDE.md", "# project\n\n## Forbidden actions\n\n- Project rule." + self.TAG + "\n")
        self.agents_md(self.tagged(self.FORBIDDEN), pre=self.KIT_AGENTS)
        self.assertFails("restated block is missing tagged line: - Project rule.")

    def test_multi_line_tagged_rule_fails(self):
        self.write("CLAUDE.md", "# rules\n\n## Forbidden actions\n\n- **No raw SQL**" + self.TAG + "\ncontinued here\n")
        self.agents_md(["- **No raw SQL**" + self.TAG])
        self.assertFails("continues onto the next line")

    def test_missing_forbidden_heading_in_kit_file_fails(self):
        self.write("CLAUDE.kit.md", "# rules\n\n## Rules\n\n- one" + self.TAG + "\n")
        self.agents_md(["- one" + self.TAG], pre=self.KIT_AGENTS)
        self.assertFails("no 'Forbidden actions' heading in CLAUDE.kit.md")

    def test_project_claude_md_needs_no_forbidden_heading(self):
        self.write("CLAUDE.md", "# rules\n\n## Rules\n\n- one" + self.TAG + "\n")
        self.agents_md(["- one" + self.TAG])
        self.assertPasses("--require-restated")

    def test_out_of_order_block_fails(self):
        self.claude_md(self.FORBIDDEN)
        self.agents_md(self.tagged(list(reversed(self.FORBIDDEN))))
        self.assertFails("restated lines are out of order")

    def test_duplicated_line_fails(self):
        self.claude_md(self.FORBIDDEN)
        self.agents_md(self.tagged(self.FORBIDDEN + self.FORBIDDEN[:1]))
        self.assertFails("a line is duplicated on one side")

    def test_missing_block_fails_when_claude_has_tagged_lines(self):
        self.claude_md(self.FORBIDDEN)
        self.assertFails("missing the restated block")

    def test_no_tags_and_no_block_passes_without_flag(self):
        self.assertPasses()
        self.assertFails("missing the restated block", "--require-restated")

    def test_empty_restated_block_fails_when_required(self):
        self.write("CLAUDE.md", "# rules\n\n## Forbidden actions\n\nNone yet.\n")
        self.agents_md([])
        self.assertFails("restated block is empty", "--require-restated")

    def test_single_marker_fails(self):
        self.write("AGENTS.md", "Read [CLAUDE.md](CLAUDE.md).\n<!-- codex-restate:start -->\n- x\n")
        self.assertFails("needs exactly one start and one end marker")

    def test_duplicate_block_fails(self):
        self.claude_md(self.FORBIDDEN)
        self.agents_md(self.tagged(self.FORBIDDEN))
        with open(self.path("AGENTS.md"), encoding="utf-8") as f:
            text = f.read()
        self.write("AGENTS.md", text + "<!-- codex-restate:start -->\n- drift\n<!-- codex-restate:end -->\n")
        self.assertFails("(found 2 start, 2 end)")

    def test_marker_text_in_prose_is_not_a_marker(self):
        self.claude_md(self.FORBIDDEN)
        self.agents_md(self.tagged(self.FORBIDDEN),
                       pre="Read [CLAUDE.md](CLAUDE.md). The block uses `<!-- codex-restate:start -->` markers.\n")
        self.assertPasses("--require-restated")

    # --- CLAUDE.kit.md first, then CLAUDE.md ---
    KIT_AGENTS = "Read [CLAUDE.md](CLAUDE.md) and [CLAUDE.kit.md](CLAUDE.kit.md).\n"

    def test_kit_lines_come_first_then_project_lines(self):
        self.claude_md(self.FORBIDDEN, path="CLAUDE.kit.md")
        self.write("CLAUDE.md", "# project\n\n@CLAUDE.kit.md\n\n- Project rule." + self.TAG + "\n")
        self.agents_md(self.tagged(self.FORBIDDEN + ["- Project rule."]), pre=self.KIT_AGENTS)
        out = self.assertPasses("--require-restated")
        self.assertIn("3 restated rule line(s) in sync", out)
        self.agents_md(self.tagged(["- Project rule."] + self.FORBIDDEN), pre=self.KIT_AGENTS)
        self.assertFails("restated lines are out of order")

    def test_forbidden_heading_in_kit_file_is_checked(self):
        self.claude_md(self.FORBIDDEN + ["- **Untagged** rule."], path="CLAUDE.kit.md")
        with open(self.path("CLAUDE.kit.md"), encoding="utf-8") as f:
            text = f.read()
        self.write("CLAUDE.kit.md", text.replace("- **Untagged** rule." + self.TAG, "- **Untagged** rule."))
        self.agents_md(self.tagged(self.FORBIDDEN), pre=self.KIT_AGENTS)
        self.assertFails("CLAUDE.kit.md: Forbidden actions item is not tagged")

    def test_bare_word_and_mid_line_tag_are_not_tags(self):
        self.write("CLAUDE.md", "# rules\n\n## Forbidden actions\n\n"
                   "- **No raw SQL**" + self.TAG + "\n\n"
                   "Lines ending with the `codex-restate` tag are copied. codex-restate\n\n"
                   "A <!-- codex-restate --> tag mid-line does not count.\n\n"
                   "```\n- fenced" + self.TAG + "\n```\n")
        self.agents_md(["- **No raw SQL**" + self.TAG])
        out = self.assertPasses("--require-restated")
        self.assertIn("1 restated rule line(s) in sync", out)

    def test_tag_without_spaces_is_not_the_tag(self):
        self.write("CLAUDE.kit.md", "# rules\n\n## Forbidden actions\n\n- **No raw SQL** <!--codex-restate-->\n")
        self.agents_md([], pre=self.KIT_AGENTS)
        self.assertFails("CLAUDE.kit.md: Forbidden actions item is not tagged")


class WordBudgetTests(Base):
    def words(self, n, prefix="w"):
        return " ".join(f"{prefix}{i}" for i in range(n)) + "\n"

    def test_count_is_reported(self):
        self.write("CLAUDE.md", self.words(10))
        out = self.assertPasses()
        # CLAUDE.md 10 + .claude/rules/tracker.md ("# tracker rules" = 2 words)
        self.assertIn("always-loaded words: 12 / 3500", out)

    def test_over_budget_fails(self):
        self.write("CLAUDE.md", self.words(30))
        self.assertFails("over the 20-word budget", "--word-budget", "20")
        self.assertPasses("--word-budget", "32")

    def test_default_budget_is_3500(self):
        self.assertEqual(csl.DEFAULT_WORD_BUDGET, 3500)
        self.write("CLAUDE.md", self.words(3499))
        self.assertFails("over the 3500-word budget")
        self.write("CLAUDE.md", self.words(3498))
        self.assertPasses()

    def test_kit_file_and_unscoped_rules_count_scoped_rules_do_not(self):
        self.write("CLAUDE.md", self.words(5))
        self.write("CLAUDE.kit.md", self.words(7))
        self.write("AGENTS.md", "Read [CLAUDE.md](CLAUDE.md) and [CLAUDE.kit.md](CLAUDE.kit.md).\n")
        self.write(".claude/rules/scoped.md", "---\npaths:\n  - \"**/*.py\"\n---\n" + self.words(500))
        self.write(".claude/rules/sub/nested.md", self.words(3))
        out = self.assertPasses()
        self.assertIn("always-loaded words: 17 / 3500", out)  # 5 + 7 + 2 + 3
        self.assertNotIn("scoped.md", out.splitlines()[0])  # not in the word-count breakdown

    def test_frontmatter_without_paths_still_counts(self):
        self.write(".claude/rules/tracker.md", "---\ndescription: always\n---\n" + self.words(4))
        out = self.assertPasses()
        self.assertIn(".claude/rules/tracker.md 4", out)

    def test_comments_frontmatter_and_markup_are_not_words(self):
        text = ("---\ntitle: x y z\n---\n# Head\n\n<!-- hidden words here -->\n\n| a | b |\n|---|---|\n"
                "- item <!-- codex-restate -->\n\n---\n")
        self.assertEqual(csl.count_words(text), 4)  # Head, a, b, item

    def test_bad_budget_value_is_a_usage_error(self):
        code, out = self.check("--word-budget", "0")
        self.assertEqual(code, 2, out)


class SkillsLockTests(Base):
    def native(self, name, files):
        for rel, data in files:
            self.write_bytes(f".agents/skills/{name}/{rel}", data)

    def lock(self, entries):
        self.write("skills-lock.json", json.dumps({"version": 1, "skills": entries}))

    def test_no_lock_file_is_fine(self):
        out = self.assertPasses()
        self.assertIn("0 locked skill(s) match", out)

    def test_matching_hash_passes(self):
        files = [("SKILL.md", b"---\nname: helper\n---\nHi.\n"), ("scripts/run.sh", b"echo hi\n")]
        self.native("helper", files)
        self.lock({"helper": {"source": "example/skills", "sourceType": "github", "computedHash": lock_hash(files)}})
        out = self.assertPasses()
        self.assertIn("1 locked skill(s) match skills-lock.json", out)

    def test_locale_order_is_used(self):
        # Code-point order puts "B.md" before "a.md"; the lock tool's locale order does not.
        files = [("a.md", b"a\n"), ("B.md", b"b\n"), ("SKILL.md", b"s\n")]
        self.native("helper", files)
        self.lock({"helper": {"computedHash": lock_hash(files)}})
        self.assertPasses()

    def test_edited_skill_fails(self):
        files = [("SKILL.md", b"original\n")]
        self.native("helper", files)
        self.lock({"helper": {"computedHash": lock_hash(files)}})
        self.write(".agents/skills/helper/SKILL.md", "edited\n")
        self.assertFails(".agents/skills/helper: content does not match its computedHash")

    def test_ds_store_is_tolerated(self):
        files = [("SKILL.md", b"s\n")]
        self.native("helper", files)
        self.lock({"helper": {"computedHash": lock_hash(files)}})
        self.write_bytes(".agents/skills/helper/.DS_Store", b"\x00\x01")
        self.assertPasses()

    def test_other_hash_format_is_unverifiable_not_a_failure(self):
        self.native("helper", [("SKILL.md", b"s\n")])
        self.lock({"helper": {"computedHash": "a" * 40}})
        out = self.assertPasses()
        self.assertIn("1 skill(s) unverifiable", out)

    def test_missing_locked_skill_fails(self):
        self.lock({"gone": {"computedHash": "0" * 64}})
        self.assertFails("locked skill 'gone' has no folder")

    def test_path_like_name_fails(self):
        self.lock({"../escape": {"computedHash": "0" * 64}})
        self.assertFails("is not a plain folder name")

    def test_invalid_json_fails(self):
        self.write("skills-lock.json", "{not json")
        self.assertFails("skills-lock.json: not valid JSON")

    def test_wrong_shape_fails(self):
        self.write("skills-lock.json", "[]")
        self.assertFails("expected a top-level \"skills\" object")



class RuleTableTests(Base):
    """11. AGENTS.md's rule table names every .claude/rules/*.md."""
    START, END = csl.RULES_START, csl.RULES_END

    def agents(self, rows, markers=True):
        table = ["| Rule | Read before |", "|---|---|"] + [f"| `.claude/rules/{r}` | Any task |" for r in rows]
        if markers:
            table = [self.START] + table + [self.END]
        self.write("AGENTS.md", "Read [CLAUDE.md](CLAUDE.md) in full.\n\n## Rule loading\n\n" + "\n".join(table) + "\n")

    def test_table_listing_every_rule_passes(self):
        self.write(".claude/rules/security.md", "# security\n")
        self.agents(["security.md", "tracker.md"])
        out = self.assertPasses()
        self.assertNotIn("rule table", out)

    def test_rule_left_out_of_the_table_fails(self):
        self.write(".claude/rules/ticket-ops.md", "---\npaths:\n  - \".claude/state/**\"\n---\n# ticket ops\n")
        self.agents(["tracker.md"])
        self.assertFails("AGENTS.md: the rule table leaves out .claude/rules/ticket-ops.md")

    def test_rows_outside_the_markers_do_not_count_when_markers_exist(self):
        self.write("AGENTS.md", "Read [CLAUDE.md](CLAUDE.md).\n\n| `.claude/rules/tracker.md` | x |\n\n"
                   + self.START + "\n| Rule | Read before |\n|---|---|\n| `.claude/rules/other.md` | x |\n"
                   + self.END + "\n")
        self.write(".claude/rules/other.md", "# other\n")
        self.assertFails("the rule table leaves out .claude/rules/tracker.md")

    def test_table_without_markers_counts(self):
        self.agents(["tracker.md"], markers=False)
        self.assertPasses()
        self.write(".claude/rules/new.md", "# new\n")
        self.assertFails("the rule table leaves out .claude/rules/new.md")

    def test_rows_in_code_do_not_count(self):
        self.write("AGENTS.md", "Read [CLAUDE.md](CLAUDE.md).\n\n| `.claude/rules/x.md` | x |\n\n"
                   "```\n| `.claude/rules/tracker.md` | x |\n```\n")
        self.write(".claude/rules/x.md", "# x\n")
        self.assertFails("the rule table leaves out .claude/rules/tracker.md")

    def test_no_table_is_only_a_warning(self):
        out = self.assertPasses()
        self.assertIn("AGENTS.md has no rule table naming .claude/rules/*.md", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
