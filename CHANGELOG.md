<!-- Copyright 2026 Tharwat Abdul-Malik. Licensed under the MIT License (see LICENSE). -->
# Changelog

Each entry says what changed and what an upgrade will touch. The installer prints the entries newer than a project's
installed version before an upgrade.

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
