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

`.claude/hooks/block-push-before-review.py` (PreToolUse on `Bash` and on MCP `apply_migration` tools). While
`.claude/state/hardening/<ticket>.active` is armed and `<ticket>.postop-passed` doesn't exist (or says `restored`),
it blocks `git push` to `<MAIN_BRANCH>`, `gh pr merge` and migration-apply commands. Anything else passes. It reads
`MAIN_BRANCH` from the Project facts table in `CLAUDE.md` (`main` if it can't). It fails open, writes nothing, and
its message tells the agent to finish post-op, never to touch the markers. Its test is
`.claude/hooks/test_block_push_before_review.py`. Removing or weakening it is G7.

Codex: hook enforcement is Claude-only. `/hardening` is Claude-only too (Codex only reviews there).
