---
paths:
  - "{{MOBILE_DIR}}/**"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

# Mobile rules (Expo)

Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`, or from the Pack facts table in
`.claude/packs/expo-mobile.md`.

## Fragile native areas

- Camera, scanning, media pickers, permissions, push, deep links and any code that branches on the platform behave
  differently on iOS and Android. A change there is tested on **both**: `/mobile-qa <ticket> ios` and
  `/mobile-qa <ticket> android`. `<MAESTRO_FLOW_MAP>` lists the project's areas under "both platforms".
- A platform-specific delay or workaround in a native area stays unless the change proves it unneeded on that
  platform. Why: these are usually the fix for a bug that only shows on one platform's hardware.

## Native packages

No new package with native code (a config plugin, `ios/` or `android/` sources, anything needing a new build)
without a check recorded in the ticket or PR:

- installed with `npx expo install` so the version matches the Expo SDK;
- `npx expo-doctor` clean;
- why no existing package or JS-only option does the job (`<DEPENDENCY_POLICY>` also applies);
- both platforms build with `<EAS_PROFILE_SIM>`.

## Builds and QA

- Any app-code change under `<MOBILE_DIR>` needs a new build before it can be driven. Docs, `.claude/`, `*.md`, CI
  and test-only files don't (see "What counts as a mobile change" in `.claude/packs/expo-mobile.md`). `/verify`
  records `📱 DEFERRED` and `/ship` labels the ticket `<NEEDS_BUILD_QA_LABEL>` until `/mobile-qa` passes on a build.
- `<EAS_CLI> submit` always takes `--id <build-id>`, never `--latest`: the newest build can be another profile's artifact.
- Reset the simulator keychain (`xcrun simctl keychain booted reset`) before Maestro runs, so a stored session
  doesn't skip the login flow.
- QA runs use `<APP_ID_QA>`; nothing automated ever targets `<APP_ID_PROD>`.
- Released app versions stay in users' hands. API changes they call stay compatible (`/api-contract`).
