# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Guardrails (1.3.1+): the installed settings and hooks enforce the kit's written rules, on a fresh install and on
an upgrade from 1.3.0. Temporary targets only."""
import json
import os
import re
import unittest

from kit_testlib import KIT, load_json, read, run, write
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
          "git reset --hard HEAD~1", "git clean -fd", "git branch -D x", "git checkout main -f",
          "git checkout main --force", "git checkout HEAD .", "git switch main -f", "git switch main --force",
          "git switch main --discard-changes", "git reset HEAD~1 --hard", "git branch x -D",
          "git branch --delete --force x", "git branch -d -f x", "git push -f origin x"]

# Commands the kit tells agents to run, or the hook allows: no deny rule may refuse them.
ALLOWED = ["git stash", "git stash list", "git stash pop", "git stash push -m wip", "git checkout feature/abc-1-x",
           "git checkout -b feature/abc-1-x origin/main", "git checkout --detach origin/main",
           "git switch feature/x", "git switch -c feature/x", "git worktree add ../wt -b x",
           "git worktree remove ../wt", "git worktree list", "git push -u origin feature/abc-1-x",
           "git push origin HEAD", "git push --follow-tags origin x", "git restore --staged a.ts",
           "git rm --cached a.ts", "git branch -d x", "git reset", "git reset --soft HEAD~1", "rm a.txt",
           "git commit -m \"fix the -f flag\"", "git log --oneline -- src/", "git branch --format=%(refname) --list",
           "git checkout -b feature/abc-1-fix origin/main", "git switch -c fix-x", "git push origin feature/fix-x",
           "git branch -a", "git reset HEAD a.ts"]


def rule_matches(rule, command):
    """Claude Code's Bash rule matching: `*` matches any text (spaces included), and a trailing ` *` also matches
    the bare command (`Bash(ls *)` matches `ls`, not `lsof`)."""
    m = re.fullmatch(r"Bash\((.*)\)", rule)
    if not m:
        return False
    pat = m.group(1)

    def wild(p):
        return ".*".join(re.escape(part) for part in p.split("*"))

    rx = wild(pat)
    if pat.endswith(" *"):
        rx = "(?:%s|%s)" % (rx, wild(pat[:-2]))
    return re.fullmatch(rx, command) is not None


def template_deny():
    return load_json(os.path.join(KIT, "core", "settings.json.tmpl"))["permissions"]["deny"]


class DenyRules(unittest.TestCase):
    def test_matcher_semantics(self):
        self.assertTrue(rule_matches("Bash(git checkout * -- *)", "git checkout main --"))
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
        # `rm` (scratch-dir exception), `git restore` and `git rm` (`--staged` / `--cached` allowed) are left to the
        # destructive-command guard hook: a prefix rule would also refuse the allowed form.
        deny = template_deny()
        for cmd in ALLOWED:
            with self.subTest(cmd=cmd):
                self.assertEqual([r for r in deny if rule_matches(r, cmd)], [], cmd)


class DenyListInstall(Base):
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
        self.assertEqual(load_json(lock_path)["kit"]["version"], load_json(os.path.join(KIT, "manifest.json"))["version"])


def bash_hooks(settings):
    return [h["command"] for g in settings.get("hooks", {}).get("PreToolUse", []) if g.get("matcher") == "Bash"
            for h in g["hooks"]]


# The hook block as 1.3.0 installed it.
HOOKS_1_3_0 = {"PreToolUse": [{"matcher": "Bash", "hooks": [
    {"type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/block-main-branch.py", "timeout": 10}]}]}


class DestructiveHook(Base):
    def test_fresh_install_wires_the_hook_and_its_parser(self):
        self.apply(self.answers())
        cmds = bash_hooks(load_json(self.t(".claude/settings.json")))
        self.assertTrue(any(c.endswith("/.claude/hooks/block-destructive.py") for c in cmds), cmds)
        self.assertTrue(any(c.endswith("/.claude/hooks/block-main-branch.py") for c in cmds), cmds)
        self.assertEqual(len(cmds), len(set(cmds)))
        for f in ("block-destructive.py", "kit_shell.py", "block-main-branch.py"):
            self.assertTrue(os.path.isfile(self.t(".claude/hooks/" + f)), f)

    def test_upgrade_from_1_3_0_adds_the_hook_once(self):
        self.apply(self.answers())
        path = self.t(".claude/settings.json")
        settings = load_json(path)
        settings["hooks"] = json.loads(json.dumps(HOOKS_1_3_0))
        write(path, json.dumps(settings, indent=2))
        rc, out, err = run(["upgrade", "--target", self.target, "--kit", self.kit])
        self.assertEqual(rc, 0, out + err)
        cmds = bash_hooks(load_json(path))
        self.assertEqual(cmds[0], HOOKS_1_3_0["PreToolUse"][0]["hooks"][0]["command"])
        self.assertEqual(len(cmds), len(set(cmds)))
        self.assertTrue(any(c.endswith("/.claude/hooks/block-destructive.py") for c in cmds), cmds)



def hook_commands(settings, event="PreToolUse"):
    return [(g.get("matcher"), h["command"]) for g in settings.get("hooks", {}).get(event, []) for h in g["hooks"]]


class SecretGuard(Base):
    MATCHER = "Read|Edit|Write|MultiEdit|NotebookEdit|Bash|Grep"

    def test_fresh_install_wires_the_hook_and_seeds_the_list(self):
        self.apply(self.answers())
        hooks = hook_commands(load_json(self.t(".claude/settings.json")))
        self.assertIn((self.MATCHER, 'python3 "$CLAUDE_PROJECT_DIR"/.claude/hooks/guard-secrets.py'), hooks)
        self.assertTrue(os.path.isfile(self.t(".claude/hooks/guard-secrets.py")))
        self.assertIn("- `.env`", read(self.t("docs/agent/secret-files.md")))

    def test_upgrade_from_1_3_0_adds_the_hook_and_creates_the_list_once(self):
        self.apply(self.answers())
        path = self.t(".claude/settings.json")
        settings = load_json(path)
        settings["hooks"] = json.loads(json.dumps(HOOKS_1_3_0))
        write(path, json.dumps(settings, indent=2))
        # A 1.3.0 project: no secret-files.md, and no lock entry for it.
        os.rename(self.t("docs/agent/secret-files.md"), self.t("docs/agent/secret-files.md.gone"))
        lock_path = self.t(".claude/agent-kit.lock.json")
        lock = load_json(lock_path)
        lock["files"].pop("docs/agent/secret-files.md")
        lock["kit"]["version"] = "1.3.0"
        write(lock_path, json.dumps(lock, indent=2))
        rc, out, err = run(["upgrade", "--target", self.target, "--kit", self.kit])
        self.assertEqual(rc, 0, out + err)
        self.assertIn((self.MATCHER, 'python3 "$CLAUDE_PROJECT_DIR"/.claude/hooks/guard-secrets.py'),
                      hook_commands(load_json(path)))
        self.assertTrue(os.path.isfile(self.t("docs/agent/secret-files.md")))
        # The project owns it from now on: an upgrade never rewrites it.
        write(self.t("docs/agent/secret-files.md"), "# ours\n\n- `*.tfvars`\n")
        rc, out, err = run(["upgrade", "--target", self.target, "--kit", self.kit])
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(read(self.t("docs/agent/secret-files.md")), "# ours\n\n- `*.tfvars`\n")



class RecordsAndContext(Base):
    STOP = 'python3 "$CLAUDE_PROJECT_DIR"/.claude/hooks/check-record.py --stop'
    START = 'python3 "$CLAUDE_PROJECT_DIR"/.claude/hooks/session-context.py'

    def wired(self, settings):
        return (hook_commands(settings, "Stop"), hook_commands(settings, "SessionStart"))

    def test_fresh_install(self):
        self.apply(self.answers())
        settings = load_json(self.t(".claude/settings.json"))
        stop, start = self.wired(settings)
        self.assertIn((None, self.STOP), stop)
        self.assertIn(("startup|resume|compact", self.START), start)
        self.assertIn("Bash(python3 .claude/hooks/check-record.py *)", settings["permissions"]["allow"])
        for f in ("check-record.py", "session-context.py", "kit_facts.py"):
            self.assertTrue(os.path.isfile(self.t(".claude/hooks/" + f)), f)
        for cmd in ("triage", "operate", "post-op", "handoff"):
            text = read(self.t(".claude/commands/%s.md" % cmd))
            self.assertIn("check-record.py --start %s" % cmd, text)
            self.assertIn("check-record.py --kind %s" % cmd, text)

    def test_upgrade_from_1_3_0_keeps_the_projects_stop_hook(self):
        self.apply(self.answers())
        path = self.t(".claude/settings.json")
        settings = load_json(path)
        settings["hooks"] = json.loads(json.dumps(HOOKS_1_3_0))
        settings["hooks"]["Stop"] = [{"hooks": [{"type": "command", "command": "echo ours"}]}]
        write(path, json.dumps(settings, indent=2))
        rc, out, err = run(["upgrade", "--target", self.target, "--kit", self.kit])
        self.assertEqual(rc, 0, out + err)
        stop, start = self.wired(load_json(path))
        self.assertEqual(stop[0], (None, "echo ours"))
        self.assertIn((None, self.STOP), stop)
        self.assertIn(("startup|resume|compact", self.START), start)



class PackGuardrails(Base):
    NOTIFY = 'python3 "$CLAUDE_PROJECT_DIR"/.claude/hooks/notify-waiting.py'
    AUDIT = ["Bash(npm audit --omit=dev --json*)", "Bash(pnpm audit --prod --json*)",
             "Bash(yarn audit --groups dependencies --json*)",
             "Bash(yarn npm audit --all --recursive --environment production --json*)"]

    def test_notify_hook_only_with_its_pack(self):
        self.apply(self.answers())
        settings = load_json(self.t(".claude/settings.json"))
        self.assertNotIn((("permission_prompt|idle_prompt"), self.NOTIFY), hook_commands(settings, "Notification"))
        self.assertFalse(os.path.exists(self.t(".claude/hooks/notify-waiting.py")))
        self.apply(self.answers(packs=("notify-telegram",)))
        settings = load_json(self.t(".claude/settings.json"))
        self.assertIn(("permission_prompt|idle_prompt", self.NOTIFY), hook_commands(settings, "Notification"))
        self.assertTrue(os.path.isfile(self.t(".claude/hooks/notify-waiting.py")))
        self.assertFalse(os.path.exists(self.t(".claude/hooks/test_notify_waiting.py")))

    def test_audit_section_and_allow_rules_with_stack_packs(self):
        self.apply(self.answers(packs=("node-esm",)))
        allow = load_json(self.t(".claude/settings.json"))["permissions"]["allow"]
        for rule in self.AUDIT:
            self.assertIn(rule, allow)
        settings = load_json(self.t(".claude/settings.json"))
        deny = settings["permissions"]["deny"]
        for cmd in ("npm audit fix", "npm audit fix --force", "npm audit --omit=dev fix", "pnpm audit --fix",
                    "pnpm audit --prod --fix"):
            with self.subTest(fix=cmd):
                self.assertTrue(any(rule_matches(r, cmd) for r in deny), cmd)
        for cmd in ("npm audit --omit=dev --json", "pnpm audit --prod --json"):
            with self.subTest(read=cmd):
                self.assertTrue(any(rule_matches(r, cmd) for r in allow))
                self.assertFalse(any(rule_matches(r, cmd) for r in deny))
        text = read(self.t(".claude/packs/node-esm.md"))
        self.assertIn("## /security", text)
        self.assertIn("npm audit --omit=dev --json", text)
        self.assertIn("Never run `npm audit fix`", text)


if __name__ == "__main__":
    unittest.main()
