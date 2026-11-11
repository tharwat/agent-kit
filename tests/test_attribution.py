# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""No AI attribution: the installed settings turn Claude Code's commit and PR attribution off, and no kit file tells
an agent to add a co-author trailer. Temporary targets only."""
import os
import re
import unittest

from kit_testlib import load_json, read, write
from test_installer import Base

KIT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class NoAttribution(Base):
    def test_installed_settings_turn_attribution_off(self):
        self.apply(self.answers())
        attr = load_json(self.t(".claude/settings.json"))["attribution"]
        self.assertEqual(attr["commit"], "")
        self.assertEqual(attr["pr"], "")
        self.assertIs(attr["sessionUrl"], False)

    def test_commit_message_guard_is_wired(self):
        self.apply(self.answers())
        settings = load_json(self.t(".claude/settings.json"))
        cmds = [h["command"] for g in settings["hooks"]["PreToolUse"] if g.get("matcher") == "Bash"
                for h in g["hooks"]]
        self.assertIn('python3 "$CLAUDE_PROJECT_DIR"/.claude/hooks/guard-commit-message.py', cmds)
        for f in ("guard-commit-message.py", "kit_facts.py", "kit_shell.py"):
            self.assertTrue(os.path.isfile(self.t(".claude/hooks/" + f)), f)

    def test_projects_own_attribution_setting_is_kept(self):
        write(self.t(".claude/settings.json"), '{"attribution": {"commit": "ours"}}')
        self.apply(self.answers())
        self.assertEqual(load_json(self.t(".claude/settings.json"))["attribution"], {"commit": "ours"})

    def test_no_kit_file_asks_for_a_trailer(self):
        bad = re.compile(r"CO_AUTHOR|end the message with .*co-author", re.I)
        hits = []
        for top in ("core", "packs", "sync"):
            for root, _, files in os.walk(os.path.join(KIT_ROOT, top)):
                for f in files:
                    if f.endswith((".md", ".tmpl", ".json")):
                        p = os.path.join(root, f)
                        if bad.search(read(p)):
                            hits.append(os.path.relpath(p, KIT_ROOT))
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
