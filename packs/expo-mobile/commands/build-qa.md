---
description: Build the QA device app for iOS and Android on EAS, and submit each to TestFlight / Play internal testing as soon as it finishes.
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`, or from the Pack facts table in
> `.claude/packs/expo-mobile.md`.

# /build-qa

Builds both platforms with the `<EAS_PROFILE_QA>` profile and submits each to its internal track: TestFlight (iOS)
and Play internal testing (Android). Internal tracks reach testers only, so no owner gate applies. Store release is
`/build-prod`.

## Step 0: Pre-flight

Run the `<EAS_CLI>` commands below from `<MOBILE_DIR>` (in place when it is `.`), each as its own command; see
"Working directory" in `.claude/packs/expo-mobile.md`.

```bash
<EAS_CLI> --version
<EAS_CLI> whoami
<EAS_CLI> project:info
```

`<EAS_CLI> project:info` must show `@<EAS_ACCOUNT>/<EAS_PROJECT_SLUG>`. Not logged in (and no `EXPO_TOKEN`), or another
project → stop and report.

## Step 1: Start both builds

Start both at once, in the background (Claude: `run_in_background: true`; Codex: add `--no-wait` and poll
`<EAS_CLI> build:view <id> --json` until the status is final):

```bash
<EAS_CLI> build --profile <EAS_PROFILE_QA> --platform ios --non-interactive
<EAS_CLI> build --profile <EAS_PROFILE_QA> --platform android --non-interactive
```

Take each EAS build ID from the first output lines. Notify `📦 QA builds started — iOS <id> · Android <id>`.

**Notify** in this command means: if `.claude/scripts/notify` exists, run
`.claude/scripts/notify "[<PROJECT_NAME>] <text>"`. A failed send prints one line and never fails the command.

## Step 2: Each build as it finishes

Handle each platform on its own; never wait for the other.

- **Finished** (`Build finished` and an artifact URL) → notify `✅ <platform> QA build <id> finished — submitting`,
  then submit **this build** in the background:

  ```bash
  <EAS_CLI> submit --platform <ios|android> --profile <EAS_PROFILE_QA> --non-interactive --id <build-id>
  ```

- **Failed** → notify `❌ <platform> QA build <id> failed — https://expo.dev/accounts/<EAS_ACCOUNT>/projects/<EAS_PROJECT_SLUG>/builds/<id>`.

**Always `--id`, never `--latest`.** `--latest` takes the newest finished build of any profile, which can be a
simulator artifact instead of the device `.ipa` / `.aab`.

## Step 3: Each submission as it finishes

Notify `✅ <platform> QA build <id> submitted to <TestFlight | Play internal>` or
`❌ <platform> submission failed — <one-line error>`.

## Step 4: Report

```
BUILD QA: <done | partial>
iOS:     <build id> — ✅ submitted to TestFlight | ❌ build failed | ❌ submit failed: <error>
Android: <build id> — ✅ submitted to Play internal | ❌ build failed | ❌ submit failed: <error>
Owner action: none | <the one action>
```

## Rules

- Both platforms, every time.
- `<EAS_PROFILE_QA>` only. Never `<EAS_PROFILE_PROD>` from this command.
- Submit each platform as soon as its own build is done, with its exact `--id`.
- No owner step between build and internal submit.
