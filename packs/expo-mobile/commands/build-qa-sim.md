---
description: Build the QA simulator/emulator app on EAS and install it on the booted iOS simulator or Android emulator.
argument-hint: "[ios|android]"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`, or from the Pack facts table in
> `.claude/packs/expo-mobile.md`.

# /build-qa-sim

Invoked as `/build-qa-sim [ios|android]`. The platform defaults to `ios`. The `<EAS_PROFILE_SIM>` profile makes a
`.app` (iOS simulator) or `.apk` (Android emulator), never a store artifact.

**Notify** means: if `.claude/scripts/notify` exists, run `.claude/scripts/notify "[<PROJECT_NAME>] <text>"`. A
failed send prints one line and never fails the command.

## Step 0: Pre-flight

Run the `<EAS_CLI>` commands below from `<MOBILE_DIR>` (in place when it is `.`), each as its own command; see
"Working directory" in `.claude/packs/expo-mobile.md`.

```bash
<EAS_CLI> --version
<EAS_CLI> whoami
<EAS_CLI> project:info
```

`<EAS_CLI> project:info` must show `@<EAS_ACCOUNT>/<EAS_PROJECT_SLUG>`; otherwise stop and report. Android: `adb devices`
must list an emulator, or stop and ask the owner to boot one. iOS needs a booted simulator only for the install
(Step 2).

## Step 1: Build in the background

```bash
<EAS_CLI> build --profile <EAS_PROFILE_SIM> --platform <platform> --non-interactive
```

Claude: `run_in_background: true`. Codex: add `--no-wait` and poll `<EAS_CLI> build:view <id> --json` until the status is
final. Take the build ID from the first output lines.

- **Failed** → notify `❌ <platform> simulator build <id> failed — https://expo.dev/accounts/<EAS_ACCOUNT>/projects/<EAS_PROJECT_SLUG>/builds/<id>`
  and stop.
- **Finished** → notify `✅ <platform> simulator build <id> finished — installing`.

## Step 2: Install that build

```bash
xcrun simctl list devices booted              # iOS: must list one
<EAS_CLI> build:run --platform <platform> --id <build-id>   # iOS: add --simulator <udid>
```

Run the install in the background too. Always `--id`, never `--latest`: the newest build may be another profile's.

- **Installed** → notify `✅ <platform> app <APP_ID_QA> installed from build <id> — ready for /mobile-qa`.
- **Failed** → notify `❌ <platform> install failed — is a simulator/emulator booted?` and stop.

## Step 3: Report

```
BUILD QA SIM: <platform>
Profile:  <EAS_PROFILE_SIM> · App: <APP_ID_QA>
Build:    <id> — ✅ finished | ❌ failed
Install:  ✅ on <simulator | emulator> | ❌ <error>
Next:     /mobile-qa <ticket> <platform>
Owner action: none | <the one action>
```

## Rules

- `<EAS_PROFILE_SIM>` only: never `<EAS_PROFILE_QA>` (device artifacts) or `<EAS_PROFILE_PROD>`.
- Never start Maestro from here. `/mobile-qa` runs the flows.
