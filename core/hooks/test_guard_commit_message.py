#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Tests for guard-commit-message.py and kit_facts.py. Run: python3 -m unittest test_guard_commit_message.py"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kit_facts  # noqa: E402

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guard-commit-message.py")
FACTS = """# CLAUDE.md

<!-- agent-kit:facts:start -->
| Fact | Value | Meaning |
|---|---|---|
| `PROJECT_NAME` | Example | Short name |
| `TICKET_PREFIX` | {prefix} | Ticket key prefix |
| `MAIN_BRANCH` | main | The only long-lived branch |
| `BRANCH_PREFIX` | {branch_prefix} | Feature branch prefix |
<!-- agent-kit:facts:end -->
"""
TRAILER = "Co-" + "Authored-By: Someone <noreply@example.com>"
GENERATED = "🤖 Generated " + "with [Claude Code](https://claude.com/claude-code)"


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd] + list(args), check=True, capture_output=True)


def make_repo(parent, name, branch):
    path = os.path.join(parent, name)
    os.makedirs(path)
    git(path, "init", "-q")
    git(path, "symbolic-ref", "HEAD", "refs/heads/" + branch)
    return path


def heredoc_commit(message, extra=""):
    return "git commit %s-m \"$(cat <<'EOF'\n%s\nEOF\n)\"" % (extra, message)


class HookCase(unittest.TestCase):
    prefix, branch_prefix = "ABC", "feature/"

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.project = os.path.join(os.path.realpath(cls._tmp.name), "project")
        os.makedirs(cls.project)
        with open(os.path.join(cls.project, "CLAUDE.md"), "w", encoding="utf-8") as fh:
            fh.write(FACTS.format(prefix=cls.prefix, branch_prefix=cls.branch_prefix))
        bp = "" if cls.branch_prefix == "none" else cls.branch_prefix
        cls.ticket = make_repo(cls.project, "ticket", bp + cls.prefix.lower() + "-12-nav-fix")
        cls.plain = make_repo(cls.project, "plain", "chore/tidy")
        cls.detached = make_repo(cls.project, "detached", "x")
        subprocess.run(["git", "-C", cls.detached, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-q",
                        "--allow-empty", "-m", "init"], check=True, capture_output=True)
        git(cls.detached, "checkout", "-q", "--detach")
        with open(os.path.join(cls.ticket, "msg.txt"), "w", encoding="utf-8") as fh:
            fh.write("ABC-12: from a file\n\n" + TRAILER + "\n")
        with open(os.path.join(cls.ticket, "ok.txt"), "w", encoding="utf-8") as fh:
            fh.write("ABC-12: from a file\n\nBody.\n")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_hook(self, command, cwd, raw=None, tool="Bash"):
        payload = raw if raw is not None else json.dumps({
            "tool_name": tool, "tool_input": {"command": command}, "cwd": cwd})
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.project)
        return subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True, env=env,
                              timeout=30)

    def assertBlocked(self, command, cwd, needle=None):
        r = self.run_hook(command, cwd)
        self.assertEqual(r.returncode, 2, "expected block: %r\nstderr: %s" % (command, r.stderr))
        self.assertIn("commit-message guard", r.stderr)
        if needle:
            self.assertIn(needle, r.stderr)

    def assertAllowed(self, command, cwd):
        r = self.run_hook(command, cwd)
        self.assertEqual(r.returncode, 0, "expected allow: %r\nstderr: %s" % (command, r.stderr))


class Attribution(HookCase):
    def test_trailer_blocked_everywhere(self):
        for cwd in (self.plain, self.ticket, self.detached):
            for cmd in (heredoc_commit("ABC-12: x\n\nBody.\n\n" + TRAILER),
                        'git commit -m "ABC-12: x" -m "%s"' % TRAILER,
                        heredoc_commit("ABC-12: x\n\n" + TRAILER.lower() + "\nmore body"),
                        heredoc_commit("ABC-12: x\n\n" + GENERATED)):
                with self.subTest(cwd=os.path.basename(cwd), cmd=cmd[-40:]):
                    self.assertBlocked(cmd, cwd, "AI attribution")

    def test_trailer_in_a_message_file(self):
        self.assertBlocked("git commit -F msg.txt", self.ticket, "Co-Authored-By")
        self.assertBlocked("git commit --file=msg.txt", self.ticket)
        self.assertAllowed("git commit -F ok.txt", self.ticket)

    def test_trailer_on_stdin(self):
        self.assertBlocked("git commit -F - <<'EOF'\nABC-12: x\n\n%s\nEOF" % TRAILER, self.ticket)

    def test_gh_pr_and_issue(self):
        for cmd in ('gh pr create --title "x" --body "Summary\n\n%s"' % GENERATED,
                    "gh pr create --title x --body \"$(cat <<'EOF'\nSummary\n\n%s\nEOF\n)\"" % GENERATED,
                    'gh pr edit 3 -b "%s"' % TRAILER, 'gh pr comment 3 --body "%s"' % GENERATED,
                    'gh issue create -t x -b "%s"' % TRAILER, 'gh issue comment 9 --body="%s"' % TRAILER):
            with self.subTest(cmd=cmd[:40]):
                self.assertBlocked(cmd, self.plain)

    def test_clean_text_allowed(self):
        self.assertAllowed('gh pr create --title "ABC-12: x" --body "Summary. Generated the fixtures by hand."',
                           self.plain)
        self.assertAllowed('git commit -m "Remove the Co-Authored-By trailer from the template"', self.plain)
        self.assertAllowed("gh pr view 3", self.plain)


class TicketFormat(HookCase):
    def test_right_ticket(self):
        for cmd in ('git commit -m "ABC-12: fix the nav"', heredoc_commit("ABC-12: fix the nav\n\nWhy."),
                    'git commit -am "ABC-12: fix"', 'git commit --message="ABC-12: fix"', 'git commit -m"ABC-12: x"',
                    'cd ticket && git commit -m "ABC-12: x"'):
            with self.subTest(cmd=cmd[:40]):
                self.assertAllowed(cmd, self.ticket if not cmd.startswith("cd") else self.project)

    def test_wrong_or_malformed(self):
        for cmd in ('git commit -m "ABC-13: fix"', 'git commit -m "abc-12: fix"', 'git commit -m "ABC-12 fix"',
                    'git commit -m "fix the nav"', heredoc_commit("Fix the nav\n\nABC-12: in the body"),
                    'git commit -m "ABC-12:fix"', 'git -C ticket commit -m "fix"'):
            with self.subTest(cmd=cmd[:40]):
                self.assertBlocked(cmd, self.ticket if "-C" not in cmd else self.project, "ABC-12: ")

    def test_no_check_off_ticket_branches(self):
        self.assertAllowed('git commit -m "tidy up"', self.plain)
        self.assertAllowed('git commit -m "tidy up"', self.detached)

    def test_no_message_argument(self):
        for cmd in ("git commit", "git commit --amend --no-edit", "git commit -C HEAD", "git commit --help"):
            with self.subTest(cmd=cmd):
                self.assertAllowed(cmd, self.ticket)


class ReviewRound1(HookCase):
    def test_bundled_short_flags(self):
        self.assertBlocked('git commit -am "wip\n\n%s"' % TRAILER, self.plain, "AI attribution")
        self.assertBlocked('git commit -am "wip"', self.ticket, "ABC-12: ")
        self.assertAllowed('git commit -am "ABC-12: wip"', self.ticket)
        self.assertAllowed('git commit -sm "ABC-12: wip"', self.ticket)

    def test_heredocs_matched_by_marker_not_position(self):
        cmd = ("cat > notes.txt <<'EOF'\nplain notes\nEOF\n" + heredoc_commit("ABC-12: x\n\n" + TRAILER))
        self.assertBlocked(cmd, self.ticket, "AI attribution")
        two = heredoc_commit("ABC-12: one") + " && " + heredoc_commit("ABC-12: two\n\n" + TRAILER)
        self.assertBlocked(two, self.ticket, "AI attribution")

    def test_piped_stdin_message(self):
        self.assertAllowed("echo 'ABC-12: x' | git commit -F -", self.ticket)
        self.assertBlocked("printf 'x\\n\\n%s\\n' | git commit -F -" % TRAILER, self.plain)
        self.assertBlocked("cat <<'EOF' | gh pr create -t x -F -\nSummary\n\n%s\nEOF" % GENERATED, self.plain)

    def test_unknown_message_skips_the_ticket_check(self):
        for cmd in ("printf 'ABC-12: x\\n' > m.txt && git commit -F m.txt", 'git commit -m "$(cat msg.txt)"',
                    "some-tool | git commit -F -"):
            with self.subTest(cmd=cmd):
                self.assertAllowed(cmd, self.ticket)

    def test_message_equals_and_attached_forms_expanded(self):
        cmd = "git commit --message=\"$(cat <<'EOF'\nABC-12: fix\n\n%s\nEOF\n)\"" % TRAILER
        self.assertBlocked(cmd, self.plain, "AI attribution")
        self.assertAllowed("git commit --message=\"$(cat <<'EOF'\nABC-12: fix\nEOF\n)\"", self.ticket)

    def test_trailer_option(self):
        self.assertBlocked('git commit -m "ABC-12: x" --trailer "Co-authored-by: C <n@x>"', self.ticket, "trailer")
        self.assertBlocked('git commit -m "ABC-12: x" --trailer=co-authored-by=C', self.ticket, "trailer")
        self.assertAllowed('git commit -m "ABC-12: x" --trailer "Reviewed-by: A <a@b>"', self.ticket)

    def test_ansi_c_message(self):
        self.assertBlocked("git commit -m $'ABC-12: x\\n\\n%s'" % TRAILER, self.ticket, "AI attribution")

    def test_generated_with_a_code_generator_is_fine(self):
        self.assertAllowed('git commit -m "ABC-12: regen client" -m "Generated with openapi-generator 7.1"',
                           self.ticket)
        self.assertBlocked('git commit -m "ABC-12: x" -m "Generated with Claude Code"', self.ticket)

    def test_fixup_and_squash(self):
        self.assertAllowed('git commit --fixup=HEAD -m "more"', self.ticket)
        self.assertAllowed('git commit --squash HEAD -m "more"', self.ticket)


class ReviewRound2(HookCase):
    def test_variables_make_the_message_unknown(self):
        for cmd in ('git commit -m "$MSG"', 'T=ABC-12; git commit -m "${T}: fix"', 'echo "$MSG" | git commit -F -',
                    "printf '%s\\n' 'ABC-12: x' | git commit -F -"):
            with self.subTest(cmd=cmd):
                self.assertAllowed(cmd, self.ticket)
        self.assertBlocked("git commit -m 'fix $5 bug'", self.ticket, "ABC-12: ")  # single quotes: known

    def test_dev_stdin(self):
        self.assertAllowed("git commit -F /dev/stdin <<'EOF'\nABC-12: x\nEOF", self.ticket)
        self.assertBlocked("git commit -F /dev/stdin <<'EOF'\nABC-12: x\n\n%s\nEOF" % TRAILER, self.ticket,
                           "AI attribution")

    def test_printf_newlines(self):
        self.assertBlocked("git commit -m \"$(printf 'ABC-12: x\\n\\n%s')\"" % TRAILER, self.plain,
                           "AI attribution")

    def test_dash_heredoc_strips_tabs(self):
        self.assertAllowed("git commit -m \"$(cat <<-'EOF'\n\tABC-12: x\n\tEOF\n)\"", self.ticket)

    def test_message_file_beside_git_dash_c(self):
        with open(os.path.join(self.project, "msg.txt"), "w", encoding="utf-8") as fh:
            fh.write("wrong subject\n")
        self.assertAllowed("git -C ticket commit -F ok.txt", self.project)

    def test_unknown_cwd_skips_the_ticket_check(self):
        self.assertAllowed('cd "$OTHER_REPO" && git commit -m "tidy"', self.ticket)

    def test_gh_merge_and_review(self):
        self.assertBlocked("gh pr merge 3 --squash --body $'Summary\\n\\n%s'" % TRAILER, self.plain)
        self.assertBlocked('gh pr merge 3 --squash -t "x" -b "%s"' % GENERATED, self.plain)
        self.assertBlocked('gh pr review 3 --approve --body "%s"' % TRAILER, self.plain)
        self.assertAllowed('gh pr merge 3 --squash --subject "ABC-12: x (#3)"', self.plain)

    def test_ordinary_generator_words(self):
        self.assertAllowed('git commit -m "ABC-12: x" -m "Generated with sqlc for the cursor pagination queries"',
                           self.ticket)
        self.assertAllowed('gh pr comment 3 --body "🤖 bot: regenerated snapshots"', self.plain)


class OtherPrefixes(HookCase):
    prefix, branch_prefix = "OPS", "none"

    def test_branch_without_prefix(self):
        self.assertAllowed('git commit -m "OPS-12: x"', self.ticket)
        self.assertBlocked('git commit -m "x"', self.ticket, "OPS-12: ")


class Facts(unittest.TestCase):
    def test_ticket_for_branch(self):
        f = {"TICKET_PREFIX": "ABC", "BRANCH_PREFIX": "feature/"}
        cases = {"feature/abc-12-nav": "ABC-12", "feature/abc-12": "ABC-12", "feature/abc-12x": None,
                 "feature/xyz-12-nav": None, "abc-12-nav": None, "main": None, None: None,
                 "feature/abc-nav": None}
        for branch, want in cases.items():
            with self.subTest(branch=branch):
                self.assertEqual(kit_facts.ticket_for_branch(branch, f), want)
        self.assertIsNone(kit_facts.ticket_for_branch("feature/abc-1-x", {"TICKET_PREFIX": "{{TICKET_PREFIX}}"}))
        self.assertEqual(kit_facts.ticket_for_branch("abc-1-x", {"TICKET_PREFIX": "ABC", "BRANCH_PREFIX": "none"}),
                         "ABC-1")

    def test_read_facts(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "CLAUDE.md"), "w", encoding="utf-8") as fh:
                fh.write(FACTS.format(prefix="ABC", branch_prefix="feat/"))
            os.makedirs(os.path.join(d, "a", "b"))
            env = os.environ.pop("CLAUDE_PROJECT_DIR", None)
            try:
                facts = kit_facts.read_facts(os.path.join(d, "a", "b"))
            finally:
                if env is not None:
                    os.environ["CLAUDE_PROJECT_DIR"] = env
            self.assertEqual(facts["TICKET_PREFIX"], "ABC")
            self.assertEqual(facts["BRANCH_PREFIX"], "feat/")
            self.assertEqual(kit_facts.fact(facts, "MISSING", "dflt"), "dflt")


class FailOpen(HookCase):
    def test_malformed_and_other_tools(self):
        r = self.run_hook("", self.ticket, raw="{nope")
        self.assertEqual(r.returncode, 0)
        self.assertIn("allowing it", r.stderr)
        self.assertEqual(self.run_hook("git commit -m x", self.ticket, tool="Write").returncode, 0)
        self.assertEqual(self.run_hook('git commit -m "abc', self.ticket).returncode, 0)

    def test_not_a_repo(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertAllowed('git commit -m "anything"', d)


if __name__ == "__main__":
    unittest.main()
