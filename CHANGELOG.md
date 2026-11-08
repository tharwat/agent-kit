<!-- Copyright 2026 Tharwat Abdul-Malik. Licensed under the MIT License (see LICENSE). -->
# Changelog

Each entry says what changed and what an upgrade will touch. The installer prints the entries newer than a project's
installed version before an upgrade.

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
