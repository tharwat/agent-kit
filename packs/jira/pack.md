<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Pack: jira

## Pack facts

| Fact | Value | Meaning |
|---|---|---|
| `JIRA_SITE` | {{JIRA_SITE}} | Atlassian site host; picks the `cloudId` from `getAccessibleAtlassianResources` |
| `JIRA_PROJECT_KEY` | {{JIRA_PROJECT_KEY}} | Jira project that tickets are searched and created in. Its keys use `<TICKET_PREFIX>` |

This pack adds no steps to core commands. Core commands call ticket ops; `.claude/rules/ticket-ops.md` maps each op
to Atlassian MCP tools.

## Markers

This pack writes no comment markers of its own. Its idempotency log is the local file
`.claude/state/<ticket>/jira-log.md`, not a comment.
