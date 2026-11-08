<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Pack: expo-mobile

Expo / React Native app built and submitted with EAS, QA'd with Maestro on simulators. Core commands read the
section named after them at their "Packs may add …" lines.

## Pack facts

| Fact | Value | Meaning |
|---|---|---|
| `MOBILE_DIR` | `{{MOBILE_DIR}}` | App directory (holds `app.json` / `app.config.*` and `eas.json`), relative to the repo root |
| `EAS_CLI` | `{{EAS_CLI}}` | How the EAS CLI is run, e.g. `npx eas-cli@latest` or `eas` |
| `EAS_ACCOUNT` | `{{EAS_ACCOUNT}}` | Expo account or organization that owns the project |
| `EAS_PROJECT_SLUG` | `{{EAS_PROJECT_SLUG}}` | Project slug; `<EAS_CLI> project:info` shows `@<EAS_ACCOUNT>/<EAS_PROJECT_SLUG>` |
| `EAS_PROFILE_QA` | `{{EAS_PROFILE_QA}}` | Build and submit profile for QA device builds (TestFlight / Play internal) |
| `EAS_PROFILE_SIM` | `{{EAS_PROFILE_SIM}}` | Build profile for simulator / emulator builds |
| `EAS_PROFILE_PROD` | `{{EAS_PROFILE_PROD}}` | Build and submit profile for store releases |
| `APP_ID_QA` | `{{APP_ID_QA}}` | Bundle ID / package name of the QA app |
| `APP_ID_PROD` | `{{APP_ID_PROD}}` | Bundle ID / package name of the store app. Never used by automation |
| `MAESTRO_DIR` | `{{MAESTRO_DIR}}` | Directory holding the Maestro flows |
| `MAESTRO_FLOW_MAP` | `{{MAESTRO_FLOW_MAP}}` | Project-owned flow map `/mobile-qa` reads |
| `PROMOTION_BLOCK_LABEL` | `{{PROMOTION_BLOCK_LABEL}}` | Label on an open ticket that stops `/build-prod` and `/release` |
| `NEEDS_BUILD_QA_LABEL` | `{{NEEDS_BUILD_QA_LABEL}}` | Label on a merged mobile change not yet driven on a build |

Values written `<LIKE_THIS>` in the sections below come from this table or from the Project facts block in
`CLAUDE.md`.

**Ticket record markers this pack adds** (first line of a comment): `Mobile QA: <ticket> — <platform> —
<PASS|FAIL|MANUAL>`, written by `/mobile-qa`, read by `/mobile-qa`, `/release` and `/build-prod`.

**Expo MCP** (optional, Claude only): the hosted server signs in with the Expo account through `/mcp` (OAuth); there
is no token to store. Read-only tools (builds, logs, workflows, TestFlight and store crashes and reviews) are allowed.
Build, submit and review-reply tools are denied: builds and submissions go through this pack's commands and the
EAS CLI (`<EAS_CLI>`), so G1 stays in one place. Codex uses `<EAS_CLI>` only.

**Working directory.** Every `<EAS_CLI>` command runs from `<MOBILE_DIR>`. When it is `.`, run the commands in place,
as written. Otherwise `cd <MOBILE_DIR>` as its own command first, and back to the repo root before any other command.
Never wrap them in `(cd … && …)`: no allow rule matches that form, so each one would prompt.

**Setup** is the owner's, listed as owner tasks at install: `eas.json` with the three profiles, store credentials
in EAS, the QA test user, simulators and the Maestro CLI, and the Expo MCP sign-in. Credentials stay with EAS or the
local env, never in the repo. When a command fails because one is missing, name it as the owner action.

**What counts as a mobile change.** A changed path is **mobile** only when it is app code or app config (`app.json`,
`app.config.*`, `eas.json`, native folders, package files) under `<MOBILE_DIR>`. Not mobile: `docs/`, `.claude/`,
`.agents/`, `*.md`, CI files (`.github/` and the like), and test-only files. This matters most when `<MOBILE_DIR>` is
`.` (the app is the repo root): most paths are then under it, and only app code needs a build. Every "changed
`<MOBILE_DIR>`" below means a mobile change in this sense.

## /triage

| When | Command | Purpose |
|---|---|---|
| A mobile change (app code under `<MOBILE_DIR>`, see above) | `/mobile-qa <ticket> [ios\|android]` | Maestro flows for the changed screens on a simulator build; both platforms for fragile native areas |
| A simulator build is needed without tests | `/build-qa-sim [ios\|android]` | Build and install the QA simulator app |
| Testers need the change on devices | `/build-qa` | QA device builds, each submitted to TestFlight / Play internal as soon as it's done |
| Store release | `/build-prod` | Production builds; each store submission waits for the owner's yes (G1). It never auto-submits |

## /verify

**At Step 0.** Mobile changes (app code under `<MOBILE_DIR>`; not docs, `.claude/`, `*.md`, CI or test-only files) are
the **mobile** surface. The dev server can't drive it: it needs a build. Record `📱 DEFERRED — <NEEDS_BUILD_QA_LABEL>` for that surface, unless `/mobile-qa <ticket> <platform>` passed
this session on a simulator build whose `gitCommitHash` is this branch's HEAD, for every platform the change needs.
Then the surface is `✅` with that `Mobile QA:` record as evidence. Other surfaces in the same diff are verified as
usual.

**At Step 3.** A mobile change has no deploy to confirm: record `📱 ships with the next store build`.

**Verdicts.** Add `📱 DEFERRED — needs a build (mobile)`. It is not `⚠️ PARTIAL`. It covers the mobile surface only
and is a pass for `/ship` only when every other surface is `✅ VERIFIED` or `⏭️ SKIPPED`.

## /ship

**At Step 2.** When `/verify` returns `📱 DEFERRED`:

1. Ticket op **label** `<ticket>` add `<NEEDS_BUILD_QA_LABEL>`.
2. Ticket op **comment** `<ticket>`: "Mobile behaviour not yet driven. Run `/mobile-qa <ticket>` on the next
   simulator build (both platforms for fragile native areas) before `/build-prod`."
3. Record `Validation: 📱 deferred — <NEEDS_BUILD_QA_LABEL>` and put it in the G3 question.

The ticket still closes after merge. The label is the tracking, so `<NEEDS_BUILD_QA_LABEL>` is never an open item or
an owner action. At Step 4.1, a mobile-only change has no deploy: record `📱 no deploy — ships with the next store
build`.

## /release

1. **Promotion block.** Ticket op **search** `labels: [<PROMOTION_BLOCK_LABEL>]`, `open: true`. Any result → NO-GO;
   name each ticket.
2. **Build QA.** Each ticket in the range that carries `<NEEDS_BUILD_QA_LABEL>`, or made a mobile change, needs a
   `Mobile QA: … — PASS` record for every platform it needs. Missing → a condition naming the ticket and platform.
3. **Store tracks.** The QA device build testers used (`/build-qa`) must be the release SHA:

   ```bash
   <EAS_CLI> build:list --build-profile <EAS_PROFILE_QA> --status finished --limit 4 --json
   ```

   One iOS and one Android build whose `gitCommitHash` equals the release SHA, each submitted to TestFlight / Play
   internal testing and validated there by a person (a ticket comment or the owner's word). An older build →
   condition: "`/build-qa` at <sha>". Not validated → CONDITIONAL GO: "validated on TestFlight / internal".
   `/build-prod` then builds that same SHA.
4. **Build-time env.** `EXPO_PUBLIC_*` values are baked in at build time. Each one the range adds must be set for
   `<EAS_PROFILE_PROD>` (in `eas.json`, or `<EAS_CLI> env:list <environment>` for that profile's environment). Names
   only; never `--include-sensitive`.
5. **Rollback.** A store release can't be recalled from users' devices. Name the plan: halt a staged rollout or pull
   the version from sale, and ship a fix build. Every API change in the range must still work for the version being
   replaced.
6. **Release step at G1:** `/build-prod`. It asks its own per-platform yes before each submission.

Report line: `expo-mobile: block <none | keys> · build QA <complete | missing: …> · build <id> at <sha> · TestFlight/internal <validated | not validated>`.

## /api-contract

**Mobile client check.** For each changed route, `git grep -n "<route path>" -- <MOBILE_DIR>`. For each one the app
calls:

- **Store-released apps have no forced minimum version** unless the project enforces one; name it if so. Old
  versions stay in use, so the old shape keeps working: no field removed or renamed, no new required request field
  (make it optional with a server default), no status change.
- Check against the oldest release still in use, not the current code: find its commit
  (its release tag, or `<EAS_CLI> build:list --build-profile <EAS_PROFILE_PROD> --app-version <version> --json` →
  `gitCommitHash`),
  then `git show <sha>:<path>` to read how that version parses the response.
- A new enum or status value: does that old version fall into a safe default branch, or a wrong one?

Report line: `mobile: ✅ compatible with <oldest version> | ❌ <route> breaks <version>: <field>`.

## bteam lenses

Add this lens to the brief, numbered after core's 8 and any earlier pack lenses:

```text
<n>. Mobile contract. The app in <MOBILE_DIR> consumes this API, and released versions stay installed with no
   forced update. For every response field added, renamed or removed, every new required request field and every
   new enum or status value: does an app version already in the stores break silently (a missing field renders as
   nothing; an unknown value takes the wrong branch)? Name the screen, the field and the version.
```

When checking a finding from this lens, confirm the app really reads the field
(`git grep -n "<field>" -- <MOBILE_DIR>`) and that the diff really changed it. If the app never reads it, the
finding is moot.

## operate lenses

**Mobile contract.** For each response field, request field or enum value the diff changes, `git grep` it under
`<MOBILE_DIR>`. Would the version already in the stores still work?
