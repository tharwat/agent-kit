# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""MCP_PREFIX: every kit MCP server installs as <prefix><server>, and every mcp__<server>__ reference (permissions,
rules, owner tasks) follows it. A server mapped to the project's own (mcp_map) is renamed the same way. Temporary
targets only."""
import json
import os
import unittest

from kit_testlib import load_json, read, write
from test_installer import Base


class McpPrefix(Base):
    PACKS = ("supabase",)

    def installed(self):
        settings = load_json(self.t(".claude/settings.json"))
        perms = settings["permissions"]
        servers = load_json(self.t(".mcp.json"))["mcpServers"]
        return servers, perms["allow"], perms["deny"]

    def all_text(self):
        out = []
        for root, _, files in os.walk(self.target):
            for f in files:
                if f.endswith((".md", ".json")):
                    out.append(read(os.path.join(root, f)))
        return "\n".join(out)

    def test_prefix_renames_servers_permissions_and_text(self):
        out, _ = self.apply(self.answers_with(MCP_PREFIX="acme_"))
        servers, allow, deny = self.installed()
        self.assertEqual(sorted(servers), ["acme_jira", "acme_supabase"])
        self.assertIn("mcp__acme_jira__getJiraIssue", allow)
        self.assertIn("mcp__acme_supabase__list_tables", allow)
        self.assertIn("mcp__acme_supabase__apply_migration", deny)  # the safety deny follows the rename
        self.assertIn("mcp__acme_jira__executeDestructive", deny)
        self.assertIn("`mcp__acme_jira__<tool>`", read(self.t(".claude/rules/ticket-ops.md")))
        text = self.all_text()
        for kit_name in ("jira", "supabase"):
            self.assertNotIn(f"mcp__{kit_name}__", text)
        self.assertIn("| `MCP_PREFIX` | acme_ |", read(self.t("CLAUDE.md")))
        self.assertIn("`acme_jira` MCP server", out)  # owner task names the installed server

    def test_none_keeps_kit_names(self):
        self.apply(self.answers_with(MCP_PREFIX="none"))
        servers, allow, _ = self.installed()
        self.assertEqual(sorted(servers), ["jira", "supabase"])
        self.assertIn("mcp__jira__getJiraIssue", allow)

    def test_mapped_server_renames_permissions_to_the_projects_server(self):
        write(self.t(".mcp.json"), json.dumps({"mcpServers": {"our_jira": {"type": "http",
                                                                           "url": "https://mcp.atlassian.com/v1/mcp"}}}))
        self.apply(self.answers_with(MCP_PREFIX="acme_", mcp_map={"jira": "our_jira"}))
        servers, allow, _ = self.installed()
        self.assertEqual(sorted(servers), ["acme_supabase", "our_jira"])  # mapped: not added again
        self.assertIn("mcp__our_jira__getJiraIssue", allow)
        self.assertNotIn("mcp__acme_jira__getJiraIssue", allow)
        self.assertIn("`mcp__our_jira__<tool>`", read(self.t(".claude/rules/ticket-ops.md")))

    def test_bad_prefix_refused(self):
        _, err = self.apply(self.answers_with(MCP_PREFIX="Acme-"), expect=2)
        self.assertIn("MCP_PREFIX", err)

    def test_reapply_is_a_no_op(self):
        ans = self.answers_with(MCP_PREFIX="acme_")
        self.apply(ans)
        plan = self.plan(ans)
        changed = [r for r in plan["files"] if r["action"] not in ("unchanged", "skip")]
        self.assertEqual(changed, [], changed)

    def answers_with(self, mcp_map=None, **facts):
        from kit_testlib import full_answers, write_answers
        ans = full_answers(self.kit, self.PACKS)
        ans["facts"].update(facts)
        if mcp_map:
            ans["mcp_map"] = mcp_map
        return write_answers(self.work, ans)


if __name__ == "__main__":
    unittest.main()
