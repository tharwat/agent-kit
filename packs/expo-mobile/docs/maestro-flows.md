<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Maestro flow map

`/mobile-qa` reads this file to pick flows. The project owns it. Replace each example row once you add real ones.
Values written `<LIKE_THIS>` come from the Pack facts table in `.claude/packs/expo-mobile.md`.

## Flows

Every flow sets `appId: <APP_ID_QA>`. Paths are relative to `<MAESTRO_DIR>`.

| Flow | Covers | Success marker (text that must be visible) | Physical-only step |
|---|---|---|---|
| `flows/00-login.yaml` | Example only: login, reused by other flows | `Home` | none |
| `flows/01-logout.yaml` | Example only: logout | `Sign in` | none |
| `flows/02-scan.yaml` | Example only: scanning a code with the camera | `Scan complete` | barcode held up to the camera (times out after 60 s → ⚠️ MANUAL) |

## Changed area → flows

| Changed path (under `<MOBILE_DIR>`) | Flows |
|---|---|
| `src/screens/auth/**` | Example only: `00-login`, `01-logout` |
| `src/components/camera/**` | Example only: `02-scan` |
| anything else | Example only: `00-login` plus the flow for the screen |

## Both platforms

Changes under these paths must pass `/mobile-qa` on iOS **and** Android.

- Example only: `src/components/camera/**`

## Flow parameters

Login values come from env vars named in `docs/agent/verify-map.md` (Test accounts). Never write a value here.

| Flow parameter (`-e`) | Env var |
|---|---|
| `QA_EMAIL` | Example only: `MOBILE_QA_USER_EMAIL` |
| `QA_PASSWORD` | Example only: `MOBILE_QA_USER_PASSWORD` |

## Pre-flight permissions

| Platform | Grant | Revoke |
|---|---|---|
| iOS (`simctl privacy` service) | Example only: `camera`, `photos` | Example only: `location` |
| Android (permission) | Example only: `android.permission.CAMERA` | Example only: `android.permission.ACCESS_FINE_LOCATION` |

## Test media

Files flows add with `addMedia` (unreliable on real iPhones: add them to the photo library by hand there).

- Example only: `test-media/sample-document.png`
