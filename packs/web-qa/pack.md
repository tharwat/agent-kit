<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Pack: web-qa

Playwright end-to-end and visual QA for a web frontend. Core commands read the section named after them at their
"Packs may add …" lines.

## Pack facts

| Fact | Value | Meaning |
|---|---|---|
| `WEB_QA_URL` | `{{WEB_QA_URL}}` | Deployed URL the owner allows read-only QA against after deploy, or `none` |
| `E2E_DIR` | `{{E2E_DIR}}` | Directory holding `playwright.config.*` and the E2E specs |
| `WEB_QA_BREAKPOINTS` | `{{WEB_QA_BREAKPOINTS}}` | Viewport widths for `/playwright-qa`, in px. Default `375, 768, 1440` |

Values written `<LIKE_THIS>` in the sections below come from this table or from the Project facts block in
`CLAUDE.md`.

**Ticket record marker this pack adds** (first line of a comment): `Web QA: <ticket> — <PASS|FAIL> (<tier>,
<local|deployed>)`, written by `/qa`, read by `/verify`.

**Test users** (set up by the owner at install): a web QA test user and a lower-privilege one for guard checks,
whose logins sit in env vars named in `docs/agent/verify-map.md`. A missing user, `@playwright/test` or browser is
the owner action, not a reason to skip.

## /triage

| When | Command | Purpose |
|---|---|---|
| A page, component or client route changed | `/qa <ticket> [--quick \| --exhaustive]` | Playwright E2E of the acceptance criteria against the local dev server |
| Layout or styling changed | `/playwright-qa <ticket>` | Screenshots at `<WEB_QA_BREAKPOINTS>` plus interaction checks |

## /verify

**At Step 0 (screens).** A changed page or component is driven in Step 1 with `/qa <ticket> --quick` against the
local dev server: log in with the test account, open the authenticated screen the ticket names, exercise the change,
and require **zero page errors** and no failed same-origin API requests. The evidence is its `Web QA:` record and
the counts.

**At Step 3.** If `<WEB_QA_URL>` isn't `none`, load the changed page there once, read-only, and confirm zero page
errors. Record `web: <page> loads clean on <WEB_QA_URL>`, or `⏭️ no WEB_QA_URL`.

## /security

- **Route and nav guard parity.** A client route guard, a role-gated nav item or a hidden button is UI only; the
  server enforces. For each one the diff adds or changes, list the API calls behind that screen and confirm each
  checks the same rule on the server. Prove it: as the lower-privilege test account, call those endpoints directly
  (or open the URL directly in Playwright) and see `401`/`403` from the server, not just a client redirect.
- **Public env prefixes.** Variables named `VITE_*`, `NEXT_PUBLIC_*`, `PUBLIC_*`, `REACT_APP_*` or `EXPO_PUBLIC_*` are
  built into the bundle every visitor downloads. None may hold a secret, a service-role key or a private URL.
- **Raw HTML sinks.** `dangerouslySetInnerHTML`, `v-html`, `{@html}`, `set:html` and `innerHTML` fed with user or
  external data go through the project's sanitizer.

Report line: `web: guard parity ✅ | ❌ <route> · public env ✅ | ❌ <name> · raw HTML ✅ | n/a | ❌ <file:line>`.

## /test

Playwright notes:

- Run from `<E2E_DIR>`, where `playwright.config.*` lives. From elsewhere the config doesn't load and Playwright fails
  (for example "test.describe() called in config file") or finds no tests.
- `test.use({ timeout })` inside a `describe` doesn't reliably reach loop-generated tests. Call `test.setTimeout()` in
  `beforeEach`.
- Wait with web-first assertions (`await expect(locator).toBeVisible()`), never fixed sleeps.
- A test that times out has failed. Never turn a timeout into a pass.
- **Captcha:** never solve or bypass one in CI or Playwright; checking the widget is present is the ceiling. Never
  create accounts through a captcha-protected endpoint: seed them with the commands in `docs/agent/verify-map.md`.
- Credentials come from `process.env` by the names in `verify-map.md`; never written into a spec.
- Scratch specs (`scratch-*.spec.ts`) are never committed and never count as the suite. Whether E2E specs run in
  `<TEST_COMMANDS>` is the project's choice.
- Browsers: `npx playwright install chromium` once per machine; on Linux CI, add `--with-deps`.
