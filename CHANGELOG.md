<!-- Copyright 2026 Tharwat Abdul-Malik. Licensed under the MIT License (see LICENSE). -->
# Changelog

Each entry says what changed and what an upgrade will touch. The installer prints the entries newer than a project's
installed version before an upgrade.

## 1.3.1 — 2026-11-11

- **Wider destructive-command deny list.** The installed `.claude/settings.json` now also denies `rmdir`, `unlink`,
  `git stash drop` / `clear`, `git checkout -- <path>` / `<rev> -- <path>` / `.` / `<rev> .` / `-f` / `--force`,
  `git switch -f` / `--force` / `--discard-changes`, `git worktree remove --force` / `-f`, and the force flags of
  `git reset --hard`, `git branch -D` / `-f` / `--force` and `git push --force` / `-f` / `--force-with-lease` wherever
  they sit after the subcommand. Claude Code applies deny rules to every sub-command, including inside `$(…)`,
  subshells and loop bodies.
- **Left to the destructive-command guard hook (next release),** because a prefix rule can't express them or would
  also refuse an allowed form: options before the subcommand (`git -C x reset --hard`), combined short flags
  (`git push -uf`, `git branch -df`), `+refspec` force pushes, `git checkout <rev> <path>`, `git restore` (allowed
  with `--staged` alone), plain `rm` (allowed inside the session scratch dir), `git rm` (allowed with `--cached`), and
  deletes passed as arguments (`xargs rm`, `find -exec rm`, `bash -c "…"`).
- **Kit text checks:** `git restore`, `git switch -f` and `git worktree remove --force` join the destructive patterns
  the kit's own tests forbid in commands and rules.
- **Kept on purpose:** `Bash(rm -rf *)` and `Bash(git clean *)` stay denied, so `git clean -n` stays refused too.

**Upgrade touches:** `.claude/settings.json` (the new deny rules are appended; your own rules and their order are
kept).

## 1.3.0 — 2026-11-08

- **No AI attribution.** The installed `.claude/settings.json` sets Claude Code's `attribution` off (`commit` and
  `pr` empty, `sessionUrl` false), so commits get no `Co-Authored-By:` trailer and PRs no "Generated with" line. A
  project's own `attribution` setting is kept. `CLAUDE.kit.md`, `/ship` and `/hardening` say never to add one.
- **Removed fact `CO_AUTHOR_TRAILER`.** An old answer for it is reported as unused and ignored.
- **Codex:** Codex may add its own trailer, depending on your ChatGPT account settings. Check a Codex commit once.

**Upgrade touches:** `.claude/settings.json` (adds `attribution` if absent), `CLAUDE.kit.md`, the `CLAUDE.md` facts
block, `.claude/commands/ship.md`, and `hardening.md` if installed.

## 1.2.0 — 2026-11-08

- **Per-project MCP server names.** New required core fact `MCP_PREFIX` (for example `acme_`). Kit servers install
  as `<MCP_PREFIX><service>`, and the installer rewrites every `mcp__<server>__` permission and text reference, and
  owner task, to the installed name. `none` keeps the plain names.
- **Fix:** with `mcp_map`, the kit's permissions and the Jira tool references still named the kit's server, so
  allow and deny rules (including the `apply_migration` deny) didn't match the project's server. They now follow the
  mapped name.
- **Jira:** the pack's server is now named `jira` (was `atlassian`).

**Upgrade touches:** `.mcp.json` (servers re-added under the new names; the old entries are reported as orphaned
and left in place for you to remove), `.claude/settings.json` permissions, `.claude/rules/ticket-ops.md`, the
`CLAUDE.md` facts block. Answer `MCP_PREFIX` when upgrading.

## 1.1.0 — 2026-11-08

- **New pack `turnstile`:** Cloudflare Turnstile bot protection. It installs Cloudflare's `turnstile-spin` setup
  skill (Apache-2.0) from GitHub at a pinned commit, checked by hash. It adds a contract row to `/triage` for public
  actions that cost money, siteverify checks to `/security`, and a real-token, replay and no-token check to `/verify`.
- **Version:** `manifest.json` and `core/pack.json` now carry the release version. v1.0.0 shipped them as
  `1.0.0-dev`.

**Upgrade touches:** the kit version in the lock file only, unless you add the `turnstile` pack.

## 1.0.0 — 2026-11-07

First release.

- **Core:**
  - 19 workflow commands: triage, operate, post-op, peer-review, bteam, codex-review, ship, verify, test,
    investigate, handoff, resume, observability, security, api-contract, guard, compliance, docs-update, release.
  - The consensus-review workflow.
  - The `kit-tools.mjs` fingerprint helper.
  - The `CLAUDE.kit.md`, `CLAUDE.md` and `AGENTS.md` templates.
  - Four rules.
  - Project-doc stubs, with seeded defect classes.
  - The main-branch guard hook.
  - The settings template.
- **Packs:** jira, supabase, render, expo-mobile, web-qa, typescript, node-esm, notify-telegram, worktrees,
  ticket-trains, hardening. Extras: scrollcraft, pressure-test, fal-media, remotion, cold-email, cloudflare.
- **Claude↔Codex sync:** a wrapper generator, a link checker and a CI workflow.
- **Installer:** scan, plan, apply, upgrade, verify, third-party.

**Upgrade touches:** nothing (first install).
