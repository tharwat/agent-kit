---
paths:
  - ".claude/state/**"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

# Ticket ops: Jira

Implements every op in `docs/workflow/ticket-ops.md`, **reopen** included; its §1 rules apply. Read this file
before the first ticket op of a session. `<JIRA_SITE>` and `<JIRA_PROJECT_KEY>` come from the Pack facts table in
`.claude/packs/jira.md`.

## Tracker and facts

- Tools: the `jira` MCP server (Atlassian's remote server), `mcp__jira__<tool>`. Deferred tools run through `executeRead` /
  `executeWrite`. Get the `cloudId` once per session from `getAccessibleAtlassianResources` (the `<JIRA_SITE>`
  entry).
- Key pattern: `^<TICKET_PREFIX>-[0-9]+$`.
- Closed: status category Done. Open: every other category.
- Comments: send Markdown; the server stores ADF. The renderer can drop `+`, `[]` and `_`; keep exact text in
  `.claude/state/<ticket>/`.

## Op table

| Op | Implementation |
|---|---|
| get | `getJiraIssue` (every field the record needs); then `listJiraIssueComments`, every page, oldest first |
| comment | `addOrEditJiraIssueComment`, new comment, Markdown body; returns its id |
| close | `listJiraIssueTransitions`; take the one whose target is in category Done (several: the one named `Done`; none: fail, listing names); `transitionJiraIssue` with that id, status only; **comment** the note; **get** |
| reopen | as **close**, but the target is `To Do`, else `In Progress` (by name, open category); **comment** why; **get** shows it open |
| label | **get**; `editJiraIssue` with the full new `labels` set |
| search | `searchJiraIssuesUsingJql`, paging with `nextPageToken` |
| create | cross-reference first (below); else `createJiraIssue` in `<JIRA_PROJECT_KEY>`, issue type by name from `listJiraProjectIssueTypesMetadata`, optional `parent` and labels; use the returned key |

## Per-op notes

- **Transition and comment are two calls.** A plain-string transition comment fails (ADF only).
- **`labels` replaces the whole array.** Read, modify, then write the full set.
- **JQL:** `project = <JIRA_PROJECT_KEY>`, one `labels = "<l>"` clause per label, `statusCategory != Done` for open,
  `text ~ "<t>"`, `parent = <key>`. No wildcard on labels (`labels = "x*"` matches nothing); use
  `labels in (...)`.
- **Read every comment:** scope changes and decisions live there.
- **Keys:** never write a key you didn't fetch or create this session. Jira assigns numbers.
- **Cross-reference before create.** Search open and closed tickets. Record a decision per item before acting:
  tracked or deferred → skip, cite the key; partly covered → comment the gap there; not tracked → create. When
  unsure, comment on the closest ticket.
- **Idempotency.** Batches of creates or comments log `SKIP|COMMENTED|CREATED <key>` per item to
  `.claude/state/<ticket>/jira-log.md` after each call. Re-runs skip logged items. A failed call is logged; the
  batch goes on.

## Local `mcp-atlassian` server

Equivalent tools: `jira_get_issue`, `jira_search`, `jira_add_comment`, `jira_get_transitions`,
`jira_transition_issue`, `jira_update_issue`, `jira_create_issue`. The installer maps whichever the project has.

## What Codex uses

The same server if configured for Codex; otherwise each op fails and says so.
