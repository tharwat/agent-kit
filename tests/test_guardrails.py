# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Guardrails (1.3.1+): the installed settings and hooks enforce the kit's written rules, on a fresh install and on
an upgrade from 1.3.0. Temporary targets only."""
import json
import os
import unittest

from kit_testlib import KIT, load_json, run, write
from test_installer import Base

# The deny list as 1.3.0 installed it.
DENY_1_3_0 = ["Bash(rm -rf *)", "Bash(git reset --hard *)", "Bash(git clean *)", "Bash(git push --force *)",
              "Bash(git push -f *)", "Bash(git branch -D *)"]
# Added in 1.3.1: commands with no allowed form, so a prefix deny rule is safe.
DENY_1_3_1 = ["Bash(rmdir *)", "Bash(unlink *)", "Bash(git stash drop*)", "Bash(git stash clear*)",
              "Bash(git checkout -- *)", "Bash(git checkout -f*)", "Bash(git switch -f*)",
              "Bash(git switch --discard-changes*)", "Bash(git worktree remove --force*)",
              "Bash(git worktree remove -f*)", "Bash(git push --force-with-lease*)", "Bash(git push * --force*)",
              "Bash(git push * -f*)"]


def template_deny():
    return load_json(os.path.join(KIT, "core", "settings.json.tmpl"))["permissions"]["deny"]


class DenyList(Base):
    def test_template_keeps_the_old_rules_and_adds_the_new(self):
        deny = template_deny()
        for rule in DENY_1_3_0 + DENY_1_3_1:
            self.assertIn(rule, deny)
        self.assertEqual(len(deny), len(set(deny)))

    def test_no_rule_blocks_an_allowed_form(self):
        # The hook owns these: a prefix rule would also refuse the allowed form.
        deny = template_deny()
        for rule in ("Bash(rm *)", "Bash(git restore *)", "Bash(git rm *)", "Bash(git stash *)"):
            self.assertNotIn(rule, deny)

    def test_fresh_install_has_every_rule(self):
        self.apply(self.answers())
        deny = load_json(self.t(".claude/settings.json"))["permissions"]["deny"]
        for rule in DENY_1_3_0 + DENY_1_3_1:
            self.assertIn(rule, deny)

    def test_upgrade_from_1_3_0_appends_new_rules_and_keeps_the_project_s(self):
        ans = self.answers()
        self.apply(ans)
        path = self.t(".claude/settings.json")
        settings = load_json(path)
        settings["permissions"]["deny"] = ["Bash(curl *)"] + DENY_1_3_0
        write(path, json.dumps(settings, indent=2))
        rc, out, err = run(["upgrade", "--target", self.target, "--kit", self.kit])
        self.assertEqual(rc, 0, out + err)
        deny = load_json(path)["permissions"]["deny"]
        self.assertEqual(deny[:len(DENY_1_3_0) + 1], ["Bash(curl *)"] + DENY_1_3_0)
        added = deny[len(DENY_1_3_0) + 1:]
        for rule in DENY_1_3_1:
            self.assertIn(rule, added)
        self.assertEqual(len(deny), len(set(deny)))


if __name__ == "__main__":
    unittest.main()
