<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Pack: hardening

Deep-security mode. `/hardening-analysis <version>` builds a release-wide edge-case analysis; `/hardening <ticket>`
takes each resulting ticket through triage → operate → post-op → a **required** peer review (up to three snapshots)
→ ship. The `block-push-before-review` hook keeps anything from reaching the main branch before review and post-op.

## Pack facts

| Fact | Value | Meaning |
|---|---|---|
| `SCHEMA_DUMP_COMMAND` | {{SCHEMA_DUMP_COMMAND}} | Prints the database schema only (no data) to stdout, or `none` when there is no database. Used by `/hardening-analysis` |

## /triage

Rows for "Workflow after triage":

| When | Command | Purpose |
|---|---|---|
| Before a major release, or after an incident that suggests a blind spot | `/hardening-analysis <version> [--auto]` | Master brief, subsystem probes, chain analysis and schema dump in `hardening/<version>/`; findings become tickets |
| A ticket from a hardening analysis, or any ticket the owner wants in deep-security mode | `/hardening <ticket>` | The whole lifecycle with peer review **required** (at most 3 snapshots); nothing reaches `<MAIN_BRANCH>` before review and post-op |

## The hook

`.claude/hooks/block-push-before-review.py` (PreToolUse on `Bash`, on MCP `apply_migration` tools and on GitHub MCP
merge and file-write tools). While
`.claude/state/hardening/<ticket>.active` is armed and `<ticket>.postop-passed` doesn't exist (or says `restored`),
it blocks a `git push` that can update `<MAIN_BRANCH>`, `gh pr merge`, writes through the GitHub API (`gh api`, `curl`,
`wget`, httpie, `xh`, or inline code; only comments, labels, reviews, review requests and issues may be written),
GraphQL mutations, migration-apply commands, and GitHub MCP merges or file writes on `<MAIN_BRANCH>`. It reads
commands with the core parser and finds these tools anywhere in a command, so `bash -c`, `eval`, heredoc scripts
and launchers such as `op run --` are seen, and a quoted message or pattern that only mentions them is not
blocked. Anything else passes. It reads
`MAIN_BRANCH` from the Project facts table in `CLAUDE.md` (`main` if it can't). It fails open, writes nothing, and
its message tells the agent to finish post-op, never to touch the markers. Its test is
`.claude/hooks/test_block_push_before_review.py`. Removing or weakening it is G7.

Codex: hook enforcement is Claude-only. `/hardening` is Claude-only too (Codex only reviews there).
