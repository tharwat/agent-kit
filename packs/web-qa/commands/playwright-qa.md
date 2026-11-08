---
description: Visual QA of changed web pages with Playwright — full-page screenshots at each breakpoint plus interaction checks.
argument-hint: "[<ticket>] [<page path> ...] [--deployed]"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`, or from the Pack facts table in
> `.claude/packs/web-qa.md`.

# /playwright-qa

Invoked as `/playwright-qa [<ticket>] [<page path> ...] [--deployed]`. It shows how changed pages look and behave at
each width in `<WEB_QA_BREAKPOINTS>`. `/qa` tests behaviour; this checks layout and interaction.

**Notify** means: if `.claude/scripts/notify` exists, run `.claude/scripts/notify "[<PROJECT_NAME>] <text>"`. A
failed send prints one line and never fails the command. `<state>` is `.claude/state/<ticket or visual-<date>>/playwright-qa/`.

## Step 1: Pages

The page paths given, or those the ticket's diff changes (`git diff origin/<MAIN_BRANCH>...HEAD --name-only`, mapped
to routes with `docs/agent/source-layout.md`). Note which need a login and which UI the change touched. Unclear →
NEEDS_CONTEXT.

## Step 2: Target

Default: start `<DEV_SERVER_COMMAND>` in the background and use the local URL it prints. `--deployed`: use
`<WEB_QA_URL>` (`none` → NEEDS_CONTEXT); setting it at install was the owner's yes for read-only checks there.
**Any other production URL needs the owner's yes for this run**: ask one question, with a pro and a con per option.
On a production target, interactions that write data are G2: skip them unless the owner says yes.

## Step 3: Screenshots and checks

Write `<E2E_DIR>/scratch-visual-<ticket or date>.spec.ts`. For each page × each width:

1. Set the viewport, open the page (log in first with the test account whose env var names are in
   `docs/agent/verify-map.md`), and wait for the network to settle.
2. Full-page screenshot to `<state>/<page>-<width>.png`.
3. Record page errors (`pageerror`), console errors and failed requests (4xx/5xx).
4. Assert no horizontal scroll: `document.documentElement.scrollWidth <= window.innerWidth`.
5. On the changed UI: fill the form, click the buttons, open and close the modal. Screenshot each result state.

Run from `<E2E_DIR>` with `npx playwright test <spec> --reporter=list` (first run on a machine:
`npx playwright install chromium`). The scratch spec is never committed: afterwards, move it to `<state>` with `mv`.

## Step 4: Look

Open every screenshot and look at it: overlap, clipped or overflowing text, broken layout, missing images, wrong
state after an interaction. A page that didn't load is **❌ UNREACHABLE**, never passed.

## Step 5: Notify and report

Notify `🎭 Playwright QA <ticket>: ✅ passed | ❌ <n> issues — <first issue>`.

```
PLAYWRIGHT QA: <ticket or pages> · <local URL | WEB_QA_URL>
<page>: <width> ✅ | ❌ <issue> … · interactions ✅ | ❌ <issue> · page errors <n>
Screenshots: <state>

Verdict: ✅ PASSED | ❌ ISSUES FOUND
Owner action: none | <the one action>
```

End with **DONE** (every page at every width) · **DONE_WITH_CONCERNS** (issues listed) · **BLOCKED** (unreachable,
login failing) · **NEEDS_CONTEXT**.
