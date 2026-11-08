---
description: Ticket-targeted Maestro QA of the mobile app on an iOS simulator or Android emulator, with the QA build only.
argument-hint: "<ticket> [ios|android]"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`, or from the Pack facts table in
> `.claude/packs/expo-mobile.md`.

# /mobile-qa

Invoked as `/mobile-qa <ticket> [ios|android]`. The platform defaults to `ios`. Run it once per platform.

It drives the screens a ticket changed with Maestro, on a **simulator or emulator only**, against the QA app
`<APP_ID_QA>`. It never touches `<APP_ID_PROD>` and never a physical device.

**Notify** means: if `.claude/scripts/notify` exists, run `.claude/scripts/notify "[<PROJECT_NAME>] <text>"`. A
failed send prints one line and never fails the command.

`<MAESTRO_FLOW_MAP>` (project-owned) maps changed areas to flows, and lists success markers, permissions, test media,
physical-only steps and the areas that need both platforms. `<out>` below is `.claude/state/<ticket>/mobile-qa/<platform>/`.

## Platform commands

The two platforms differ only here.

| Action | iOS simulator | Android emulator |
|---|---|---|
| Device ready | `xcrun simctl list devices \| grep Booted` → note its UDID | `adb devices` → an `emulator-<n>  device` line; note the serial |
| App installed | `xcrun simctl get_app_container booted <APP_ID_QA>` | `adb shell pm list packages \| grep -x "package:<APP_ID_QA>"` |
| Grant / revoke a permission | `xcrun simctl privacy booted grant\|revoke <service> <APP_ID_QA>` | `adb shell pm grant\|revoke <APP_ID_QA> <android.permission.X>` |
| Stop the app | `xcrun simctl terminate booted <APP_ID_QA>` | `adb shell am force-stop <APP_ID_QA>` |
| Reset the keychain | `xcrun simctl keychain booted reset` | n/a |

Always pass the device ID to Maestro (`maestro --device <id> …`), so a connected phone is never picked. An Android
serial that isn't `emulator-…` is a physical device: stop.

## Step 1: What changed

Ticket op **get** `<ticket>` (comments and links included): title, acceptance criteria, labels.

```bash
git fetch origin
git diff origin/<MAIN_BRANCH>...HEAD --name-only          # branch not merged yet
```

Already merged (a `<NEEDS_BUILD_QA_LABEL>` run): take the merge commit,
`git log origin/<MAIN_BRANCH> --merges --grep "<ticket>" -1 --format=%H`, then `git diff <sha>^1 <sha> --name-only`.

Keep the mobile changes: app code or app config under `<MOBILE_DIR>/`, not `docs/`, `.claude/`, `.agents/`, `*.md`,
CI files or test-only files (this matters when `<MOBILE_DIR>` is `.`). None → `⏭️ SKIPPED — no mobile surface`, stop. Note which changed paths fall in
`<CRITICAL_SYSTEMS>` (locations per `docs/agent/source-layout.md`).

## Step 2: Device and build

1. Device ready (table). None → notify `❌ Mobile QA <ticket>: no <simulator | emulator> booted`, BLOCKED.
2. The build must contain the change (run `<EAS_CLI>` from `<MOBILE_DIR>`, in place when it is `.`; git and grep
   commands from the repo root):

   ```bash
   <EAS_CLI> build:list --platform <platform> --build-profile <EAS_PROFILE_SIM> --status finished --limit 1 --json
   ```

   Its `gitCommitHash` must contain the change (`git merge-base --is-ancestor <change sha> <gitCommitHash>`). If not,
   or the app isn't installed, notify `📦 Mobile QA <ticket>: building <platform>` and run `/build-qa-sim <platform>`'s
   steps. If unsure what is installed, install that build with
   `<EAS_CLI> build:run --platform <platform> --id <id>` (iOS: add `--simulator <udid>`).
3. `grep -rn "appId:" <MAESTRO_DIR>` for the flows you'll run: every one must be `<APP_ID_QA>`. Any `<APP_ID_PROD>`
   → stop.

## Step 3: Pre-flight reset

Grant and revoke the permissions `<MAESTRO_FLOW_MAP>` lists, stop the app, and on iOS reset the keychain (a stored
session skips the login flow and hides login bugs).

## Step 4: Pick the flows

From `<MAESTRO_FLOW_MAP>`, take every flow mapped to a changed area. If no flow covers a changed screen, write a
scratch flow at `<MAESTRO_DIR>/scratch-<ticket>.yaml` (`appId: <APP_ID_QA>`, reusing the login subflow) that walks
the acceptance criteria. **Scratch flows are never committed.** After the run, move it to `<out>` with `mv`, so the
tree stays clean and the flow can be re-run.

## Step 5: Run, one flow at a time

QA login values come from the env var names in `docs/agent/verify-map.md` (Test accounts). Pass them by shell
expansion; never print a value:

```bash
maestro --device <id> test <MAESTRO_DIR>/<flow>.yaml --debug-output <out> \
  -e <flow-param>="$<env-var-name>"
```

Claude runs each in the background; Codex in the foreground. Classify each flow:

| Result | When |
|---|---|
| ✅ PASS | The flow's success marker (from the flow map) was seen |
| ❌ FAIL | An assertion failed, or the flow **timed out**. A timed-out flow is never a pass |
| ⚠️ MANUAL | A physical-only step (barcode or camera scan held up to a real camera) timed out waiting for a human. Not FAILED, not PASS |

Before diagnosing a failure, read the screenshots in `<out>`. **3 strikes:** the same flow fails 3 times with no clear
fix → stop:

```
STATUS: BLOCKED
REASON: <1–2 sentences>
ATTEMPTED: <what each try changed>
RECOMMENDATION: <next step for the owner>
```

**A physical-only step whose code changed can't be skipped.** The verdict stays ⚠️ until a human runs that step on
the internal-track build (`/build-qa`) on a real device. On a real iPhone, Maestro's `addMedia` is unreliable: put
the test media in the photo library by hand and drop the `addMedia` lines from a local copy of the flow (never
committed).

## Step 6: Record, labels, escalation

Ticket op **comment** `<ticket>`, first line `Mobile QA: <ticket> — <platform> — <PASS | FAIL | MANUAL>`, then each
flow and its result, the build ID and `<APP_ID_QA>`.

- **All PASS, nothing physical pending:** if the ticket carries `<NEEDS_BUILD_QA_LABEL>`, remove it (ticket op
  **label**) once every platform it needs has a `PASS` record: both, when a changed path is in the flow map's
  "both platforms" list; else this one. If it carries `<PROMOTION_BLOCK_LABEL>` and this build holds the fix,
  remove that too, from the ticket and its fix-forward ticket.
- **FAIL before merge:** an ordinary failure. Fix it on the branch before `/ship`.
- **FAIL after merge, on a change touching `<CRITICAL_SYSTEMS>`:**
  1. Reopen the ticket, using the reopen helper in `.claude/rules/ticket-ops.md` if the ticket pack has one.
     Otherwise ticket op **create** a fix-forward ticket labelled `<PROMOTION_BLOCK_LABEL>` and comment its key on
     `<ticket>`.
  2. Ticket op **label** `<ticket>` add `<PROMOTION_BLOCK_LABEL>`. An open ticket with that label stops
     `/build-prod` and `/release`.
- **FAIL after merge, other changes:** ticket op **create** a fix-forward ticket; comment its key on `<ticket>`.

Notify once: `✅ Mobile QA <ticket> (<platform>) passed — <n> flows` or
`❌ Mobile QA <ticket> (<platform>): <flow> failed at <step>[ · labelled <PROMOTION_BLOCK_LABEL>]`.

## Step 7: Report

```
MOBILE QA: <ticket> — <title> · <platform>
Build:   <id> (<gitCommitHash short>) · App: <APP_ID_QA> · Device: <id>
Tested:  <acceptance criteria / screens covered>
Flows:   ✅ | ❌ | ⚠️  <flow> — <step / marker>
Scratch: <out>/scratch-<ticket>.yaml | none
Labels:  <changes made> | none

Verdict: ✅ PASSING | ⚠️ MANUAL STEP PENDING — <step> | ❌ FIX FAILURES | ⏭️ SKIPPED — no mobile surface
Owner action: none | <the one action>
```

End with **DONE** (all pass) · **DONE_WITH_CONCERNS** (manual step pending, or a flaky step; list each) · **BLOCKED**
(no device, build or install failed, 3 strikes) · **NEEDS_CONTEXT** (no flow map, unclear scope).

## Rules

- Simulator or emulator only; `<APP_ID_QA>` only; `<EAS_PROFILE_SIM>` for any build this command starts.
- A timed-out flow is not a pass. Unreachable is not a pass. Never fabricate a result.
- Scratch flows and debug output stay out of git.
