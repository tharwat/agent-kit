---
description: Ticket-targeted Playwright E2E QA of the web app, at quick, standard or exhaustive depth, against the local dev server before merge or the deployed app after.
argument-hint: "<ticket> [--quick | --exhaustive] [--deployed] [headed]"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`, or from the Pack facts table in
> `.claude/packs/web-qa.md`.

# /qa

Invoked as `/qa <ticket> [--quick | --exhaustive] [--deployed] [headed]`. Headless unless `headed` is given.

| Flag | Depth | Scope per acceptance criterion |
|---|---|---|
| `--quick` | Quick | Happy path only |
| none | Standard | Happy path + at least one failure or edge case |
| `--exhaustive` | Exhaustive | Happy path + every failure path + boundaries (empty state, max length, double submit, unauthorized access) |

**Notify** means: if `.claude/scripts/notify` exists, run `.claude/scripts/notify "[<PROJECT_NAME>] <text>"`. A
failed send prints one line and never fails the command. `<state>` below is `.claude/state/<ticket>/qa/`.

## Step 1: What changed

Ticket op **get** `<ticket>` (comments and links included): title, acceptance criteria.

```bash
git fetch origin
git diff origin/<MAIN_BRANCH>...HEAD --name-only          # branch not merged yet
```

Already merged: take the merge commit (`git log origin/<MAIN_BRANCH> --merges --grep "<ticket>" -1 --format=%H`),
then `git diff <sha>^1 <sha> --name-only`. Using `docs/agent/source-layout.md`, list the pages and components, the
API calls they make, and what each acceptance criterion says the user can do. No web surface → say so and stop.

## Step 2: Target

- **Before merge (default):** start `<DEV_SERVER_COMMAND>` in the background and use the local URL it prints.
- **After deploy (`--deployed`):** use `<WEB_QA_URL>` (setting it at install was the owner's yes for read-only
  runs there); `none` → NEEDS_CONTEXT. First confirm the deploy is live with
  the `## /qa` section of each installed `.claude/packs/*.md` (a deploy pack such as render). No such section →
  record `Deploy check: ⏭️ skipped — no deploy pack`. Not live → notify `⚠️ QA <ticket> blocked — deploy not live`,
  BLOCKED.
- If the target serves real users, any test that writes data is G2: ask the owner first, or run read-only paths
  only. Nothing from the irreversible list in `docs/agent/verify-map.md`, ever.

Notify `🧪 QA <ticket> starting — <one line> · <tier> · <local | deployed>`.

## Step 3: Write the scratch spec

Write `<E2E_DIR>/scratch-<ticket>.spec.ts`:

- Only the ticket's acceptance criteria, at the chosen depth. No general smoke test.
- Reuse the fixtures, auth state and conventions already in `<E2E_DIR>`.
- Log in with the test account whose env var names are in `docs/agent/verify-map.md`, read through `process.env`.
  Never write a value into the spec.
- Point it at the target (`test.use({ baseURL })` or the config's base URL).
- Every test collects `page.on('pageerror')` and asserts there were none.
- Never solve or bypass a captcha. Seed accounts with the seed commands in `verify-map.md`.

**The scratch spec is never committed.** When the command ends, pass or fail, move it to `<state>` with `mv`, so
the tree stays clean (`/post-op`'s fingerprint refuses untracked files) and the spec can be re-run.

## Step 4: Run it

From `<E2E_DIR>` (Playwright's config must load), in the background (Codex: foreground). `<repo root>` is the
output of `git rev-parse --show-toplevel`, written in literally:

```bash
PLAYWRIGHT_JSON_OUTPUT_NAME="<repo root>/<state>/results.json" \
  npx playwright test scratch-<ticket>.spec.ts --reporter=list,json [--headed]
```

First run on a machine: `npx playwright install chromium` (on Linux CI add `--with-deps`).

**3 strikes:** the same test fails 3 times with no clear fix → stop:

```
STATUS: BLOCKED
REASON: <1–2 sentences>
ATTEMPTED: <what each try changed>
RECOMMENDATION: <next step for the owner>
```

## Step 5: Baseline delta

From `results.json`, write `<state>/baseline.json`:

```json
{"ticket": "<ticket>", "date": "<ISO-8601>", "tier": "quick|standard|exhaustive", "target": "local|deployed",
 "passed": 0, "failed": 0, "tests": [{"name": "<title>", "status": "passed|failed", "error": "<summary>|null"}]}
```

If a previous baseline exists, compare first: `Regression delta: <n> fixed, <n> regressed, <n> new` (or
`first run — no prior baseline`). Keep the previous file as `baseline.<its date>.json`.

## Step 6: Record, notify, report

Ticket op **comment** `<ticket>`, first line `Web QA: <ticket> — <PASS | FAIL> (<tier>, <local | deployed>)`, then
the counts, failures and delta. Notify `✅ QA <ticket> passed — <n> tests` or
`❌ QA <ticket>: <n> failed — <first failure>`.

```
QA: <ticket> — <title>
Tested:  <acceptance criteria covered>
Target:  <local URL | WEB_QA_URL> · <tier> · <headless | headed> · deploy check <✅ | ⏭️>
Results: ✅ <n> passed · ❌ <n> failed · page errors <n>
Delta:   <regression delta>
Spec:    <state>/scratch-<ticket>.spec.ts

Verdict: ✅ PASSING | ❌ FIX FAILURES BEFORE MERGING
Owner action: none | <the one action>
```

End with **DONE** · **DONE_WITH_CONCERNS** (passed, with issues listed) · **BLOCKED** (deploy not live, server won't
start, 3 strikes) · **NEEDS_CONTEXT**.

## Rules

- Test the ticket's change, not the whole app.
- A target serving real users gets read-only tests unless the owner says yes (G2). Never an irreversible action.
- Unreachable is not a pass; never fabricate a result.
