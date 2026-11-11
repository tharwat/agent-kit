# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Guardrails (1.3.1+): the installed settings and hooks enforce the kit's written rules, on a fresh install and on
an upgrade from 1.3.0. Temporary targets only."""
import json
import os
import re
import unittest

from kit_testlib import KIT, load_json, run, write
from test_installer import Base

# The deny list as 1.3.0 installed it.
DENY_1_3_0 = ["Bash(rm -rf *)", "Bash(git reset --hard *)", "Bash(git clean *)", "Bash(git push --force *)",
              "Bash(git push -f *)", "Bash(git branch -D *)"]

# Commands the deny list must refuse: each has no allowed form.
DENIED = ["rmdir build", "unlink a.txt", "git stash drop", "git stash drop stash@{1}", "git stash clear",
          "git checkout -- src/a.ts", "git checkout .", "git checkout ./src", "git checkout HEAD -- src/",
          "git checkout main -- a.ts", "git checkout -f", "git checkout -f main", "git checkout --force main",
          "git switch -f main", "git switch --force main", "git switch --discard-changes main",
          "git worktree remove --force ../wt", "git worktree remove -f ../wt", "git worktree remove ../wt --force",
          "git worktree remove ../wt -f", "git push --force", "git push --force origin x", "git push -f",
          "git push --force-with-lease", "git push --force-with-lease origin x", "git push origin x --force",
          "git push origin x -f", "git push origin x --force-with-lease", "rm -rf build", "git reset --hard",
          "git reset --hard HEAD~1", "git clean -fd", "git branch -D x"]

# Commands the kit tells agents to run, or the hook allows: no deny rule may refuse them.
ALLOWED = ["git stash", "git stash list", "git stash pop", "git stash push -m wip", "git checkout feature/abc-1-x",
           "git checkout -b feature/abc-1-x origin/main", "git checkout --detach origin/main",
           "git switch feature/x", "git switch -c feature/x", "git worktree add ../wt -b x",
           "git worktree remove ../wt", "git worktree list", "git push -u origin feature/abc-1-x",
           "git push origin HEAD", "git push --follow-tags origin x", "git restore --staged a.ts",
           "git rm --cached a.ts", "git branch -d x", "git reset", "git reset --soft HEAD~1", "rm a.txt",
           "git commit -m \"fix the -f flag\"", "git log --oneline -- src/"]


def rule_matches(rule, command):
    """Claude Code's Bash rule matching: `*` matches any text (spaces included), and a trailing ` *` also matches
    the bare command (`Bash(ls *)` matches `ls`, not `lsof`)."""
    m = re.fullmatch(r"Bash\((.*)\)", rule)
    if not m:
        return False
    pat = m.group(1)
    rx = ".*".join(re.escape(part) for part in pat.split("*"))
    if pat.endswith(" *"):
        rx = "(?:%s|%s)" % (rx, re.escape(pat[:-2]))
    return re.fullmatch(rx, command) is not None


def template_deny():
    return load_json(os.path.join(KIT, "core", "settings.json.tmpl"))["permissions"]["deny"]


class DenyList(Base):
    def test_matcher_semantics(self):
        self.assertTrue(rule_matches("Bash(ls *)", "ls"))
        self.assertTrue(rule_matches("Bash(ls *)", "ls -la"))
        self.assertFalse(rule_matches("Bash(ls *)", "lsof"))

    def test_template_keeps_the_1_3_0_rules(self):
        deny = template_deny()
        for rule in DENY_1_3_0:
            self.assertIn(rule, deny)
        self.assertEqual(len(deny), len(set(deny)))

    def test_every_destructive_form_is_denied(self):
        deny = template_deny()
        for cmd in DENIED:
            with self.subTest(cmd=cmd):
                self.assertTrue(any(rule_matches(r, cmd) for r in deny), cmd)

    def test_no_rule_refuses_an_allowed_form(self):
        # The hook owns `rm` (scratch-dir exception), `git restore` and `git rm` (`--staged` / `--cached` allowed).
        deny = template_deny()
        for cmd in ALLOWED:
            with self.subTest(cmd=cmd):
                self.assertEqual([r for r in deny if rule_matches(r, cmd)], [], cmd)

    def test_fresh_install_has_every_rule(self):
        self.apply(self.answers())
        deny = load_json(self.t(".claude/settings.json"))["permissions"]["deny"]
        for rule in template_deny():
            self.assertIn(rule, deny)

    def test_upgrade_from_1_3_0_appends_new_rules_and_keeps_the_project_s(self):
        self.apply(self.answers())
        lock_path = self.t(".claude/agent-kit.lock.json")
        lock = load_json(lock_path)
        lock["kit"]["version"] = "1.3.0"
        write(lock_path, json.dumps(lock, indent=2))
        path = self.t(".claude/settings.json")
        settings = load_json(path)
        settings["permissions"]["deny"] = ["Bash(curl *)"] + DENY_1_3_0
        write(path, json.dumps(settings, indent=2))
        rc, out, err = run(["upgrade", "--target", self.target, "--kit", self.kit])
        self.assertEqual(rc, 0, out + err)
        self.assertIn("Wider destructive-command deny list", out)  # the 1.3.1 CHANGELOG entry is shown
        deny = load_json(path)["permissions"]["deny"]
        self.assertEqual(deny[:len(DENY_1_3_0) + 1], ["Bash(curl *)"] + DENY_1_3_0)
        added = deny[len(DENY_1_3_0) + 1:]
        for rule in template_deny():
            if rule not in DENY_1_3_0:
                self.assertIn(rule, added)
        self.assertEqual(len(deny), len(set(deny)))
        self.assertNotEqual(load_json(lock_path)["kit"]["version"], "1.3.0")


if __name__ == "__main__":
    unittest.main()
