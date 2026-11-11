<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Pack: statusline

A Claude Code status line: `<model> · <branch> · <ticket> · context <n>% used`. The script is
`.claude/scripts/statusline.py`. It reads the status-line JSON Claude Code passes on stdin, plus local git state and
the Project facts in `CLAUDE.md`. It makes no network calls and writes nothing.

- **Context use** is Claude Code's own `context_window.used_percentage` (input tokens only). It shows `context –`
  before the first reply and right after a compaction.
- **Ticket** is shown on a `<BRANCH_PREFIX><ticket-lowercase>-<slug>` branch.
- **A project status line already in `.claude/settings.json` is kept,** and the plan says so. This one is a project
  setting, so it takes precedence over each developer's personal status line in `~/.claude/settings.json`; the plan
  warns when you have one. Remove the pack (or set your own in `.claude/settings.local.json`) to use yours.
- Codex has no status line; this pack does nothing there.

This pack adds no steps to core commands.
