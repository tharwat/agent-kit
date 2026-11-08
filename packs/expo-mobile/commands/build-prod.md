---
description: Build the production app for iOS and Android on EAS, then submit each platform to its store only on the owner's explicit yes (Owner-Kept Gate G1).
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`, or from the Pack facts table in
> `.claude/packs/expo-mobile.md`.

# /build-prod

Production builds and store submissions are **Owner-Kept Gate G1**. This command asks twice: before it builds, and
per platform before it submits. **Silence or an unclear answer is no.** It never submits on its own.

**Notify** means: if `.claude/scripts/notify` exists, run `.claude/scripts/notify "[<PROJECT_NAME>] <text>"`. A
failed send prints one line and never fails the command.

## Step 0: Pre-flight

1. **Promotion block.** Ticket op **search** `labels: [<PROMOTION_BLOCK_LABEL>]`, `open: true`. Any result → stop.
   Name each ticket: a Critical-System change failed its build QA and isn't fixed.
2. **Unchecked mobile changes.** Ticket op **search** `labels: [<NEEDS_BUILD_QA_LABEL>]`, `open: any`. Each result
   is a merged mobile change not yet driven on a build. It doesn't block, but the G1 question names every one.
3. **EAS.** Run this pack's `<EAS_CLI>` commands from `<MOBILE_DIR>` (in place when it is `.`), each as its own
   command; see "Working directory" in `.claude/packs/expo-mobile.md`.

   ```bash
   <EAS_CLI> --version
   <EAS_CLI> whoami
   <EAS_CLI> project:info
   ```

   `<EAS_CLI> project:info` must show `@<EAS_ACCOUNT>/<EAS_PROJECT_SLUG>`; otherwise stop and report.

## Step 1: G1, before building

Ask the owner one question:

> Start **production** builds for iOS and Android from `<MAIN_BRANCH>` at `<short sha>`? Not yet checked on a build:
> <tickets from step 0.2, or "none">. Nothing is submitted without a second yes per platform.
> - **Yes, build.** Pro: store-ready artifacts in ~20–40 minutes. Con: uses EAS build credits.
> - **No.** Pro: nothing changes. Con: the release waits.

No clear yes → stop with `Owner action: none — production build not approved`.

## Step 2: Build both, in the background

```bash
<EAS_CLI> build --profile <EAS_PROFILE_PROD> --platform ios --non-interactive
<EAS_CLI> build --profile <EAS_PROFILE_PROD> --platform android --non-interactive
```

Claude: `run_in_background: true`. Codex: add `--no-wait` and poll `<EAS_CLI> build:view <id> --json` until the status is
final. Take each build ID from the first output lines. Notify `📦 Production builds started — iOS <id> · Android <id>`.

As each finishes:

- **Finished** → notify `⏸️ <platform> production build <id> ready — waiting for the owner's approval to submit`.
  Don't submit.
- **Failed** → notify `❌ <platform> production build <id> failed — https://expo.dev/accounts/<EAS_ACCOUNT>/projects/<EAS_PROJECT_SLUG>/builds/<id>`.

## Step 3: G1, per platform

When both results are known, ask one question per finished platform, one at a time:

> Submit <platform> build `<id>` (<version> / <build number>) to <App Store Connect | Google Play>?
> - **Yes, submit.** Pro: the build reaches store review / the release track. Con: it can't be pulled back from
>   review by this command.
> - **No, hold it.** Pro: time to test the build first. Con: the store release waits; the artifact stays on EAS.

## Step 4: Submit only what was approved

```bash
<EAS_CLI> submit --platform <ios|android> --profile <EAS_PROFILE_PROD> --non-interactive --id <build-id>
```

In the background, with the exact `--id`, never `--latest`. Notify `✅ <platform> build <id> submitted to <store>` or
`❌ <platform> submission failed — <one-line error>`.

## Step 5: Report

```
BUILD PROD: <sha>
iOS:     <id> — ✅ submitted to App Store Connect | ⏭️ held by owner | ❌ <failed step>
Android: <id> — ✅ submitted to Google Play | ⏭️ held by owner | ❌ <failed step>
Not yet checked on a build: <tickets> | none
Owner action: none | <the one action>
```

## Rules

- Never auto-submit a production build. A yes for one platform is not a yes for the other.
- `<EAS_PROFILE_PROD>` only, always `--id`.
- An open `<PROMOTION_BLOCK_LABEL>` ticket stops the command before anything is built.
