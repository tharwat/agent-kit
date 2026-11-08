---
description: Security and privacy gate. Audits the branch diff for leaked secrets, PII in logs, auth and webhook holes, unguarded paths, SSRF and unsafe output.
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# /security

Run before committing anything that touches auth, webhooks, logging, middleware, external calls or data flows.
`/post-op` runs it on every change. Every ❌ is a must-fix finding: S2, or S1 when it exposes another user's or
tenant's data. Before starting, read the security section of `docs/agent/lessons.md`, if it has one.

## Step 1: Get the diff

```bash
git fetch origin <MAIN_BRANCH>
git diff origin/<MAIN_BRANCH>...HEAD   # committed branch work
git diff HEAD                          # uncommitted work
git status --short                     # new files
```

`docs/agent/source-layout.md` says where routes, middleware, clients and jobs live. Focus there.

## Step 2: Secrets

- **Secret-bearing files.** List candidates by name only. Never print their contents.

  ```bash
  git status --short --untracked-files=all
  git ls-files | grep -iE '(^|/)\.env($|\.)|\.(pem|key|p8|p12|pfx|jks|keystore)$|(secret|credential|service.?account|token)[^/]*\.json$'
  git check-ignore -v <path>
  ```

  A secret-bearing file that is tracked, staged, or untracked with no ignore rule is a BLOCKER. A template that
  holds only placeholder values (such as `.env.example`) is fine once you confirm it has no real value.
- **Inline secrets.** Grep the added lines of both diffs:

  ```bash
  git diff origin/<MAIN_BRANCH>...HEAD | grep -inE '^\+.*((api.?key|secret|token|passw(or)?d|bearer|private.?key)[[:space:]"'\'']*[:=]|BEGIN [A-Z ]*PRIVATE KEY|://[^/[:space:]:@]+:[^/[:space:]@]+@)'
  ```

  Judge each hit. A value that isn't read from the environment or a secret store is a finding: move it there.
- **Echoes.** No changed line logs, returns or prints a secret, or a full payload that contains one.
- **A committed secret is always ❌ BLOCKED.** Fix: stop tracking it, add the ignore rule, load it from the
  environment. It stays in git history, so rotating it is the owner action.

## Step 3: PII and secrets in logs

Scan every log call in the diff. The PII fields and their masks come from `docs/agent/pii.md`. If that file is empty,
treat names, emails, phone numbers, government IDs, addresses, payment identifiers, message bodies and uploaded-file
URIs as PII. Never log tokens, passwords, secrets, or full request/response payloads on production paths. The fix is
masked logging, not deleting the log line.

## Step 4: Auth, rate limits, guard parity

- New routes use the auth middleware. Nothing that needs auth is reachable without it.
- Tokens are not stored beyond the session window, and refresh follows the existing pattern.
- New auth and other abuse-prone endpoints are rate-limited. The change never removes or bypasses an existing limiter.
- **Route/UI guard parity.** A UI guard (hidden or disabled nav item, role-gated menu) is an affordance only. The route
  behind it must enforce the same guard, or a direct URL gets through.

## Step 5: Webhooks

For each inbound webhook the diff touches, `docs/agent/integrations.md` says how it is signed. If it doesn't, that row
is NEEDS_CONTEXT: don't guess.

- The signature is verified over the raw body, with a constant-time comparison, **before** the body is parsed, used
  or logged.
- A missing or wrong signature returns 401/403 and drops the request. Never "process anyway" or "process and log".

## Step 6: Input and guarded paths

- Inputs are validated by the project's validation layer before use: type, length, format. Uploads check type and
  size. SQL is parameterized or built by the query builder, never concatenated from input.
- **Every path to a guarded action enforces the guard.** If the diff adds or touches a guard (sanitizer, validator,
  safety check, a check for one of `<CRITICAL_SYSTEMS>`), or adds a path to a guarded action (an LLM or retrieval
  call, a send or publish, a privileged write), list every path to that action: each entry point and input kind
  (text, captions, button replies, imports, jobs). Each must pass the guard. A sibling that skips it is a BLOCKER.
  Check `docs/agent/sibling-paths.md` for known pairs.
- **Query scope.** An endpoint that returns results plus filter metadata (dropdown options, counts, selectors) uses
  the same scope predicate for every metadata query as for the main query, including any role extension.

## Step 7: Outbound calls and output

- **SSRF.** A server-side fetch of a URL from a user, operator or scraper goes through one shared guard, never an
  inline copy (a weaker sibling is a bypass). The guard resolves the host and rejects private, loopback, link-local,
  ULA, CGNAT and IPv4-mapped IPv6 addresses. It handles redirects manually and re-checks each hop, and caps the
  response by content type and bytes. A string denylist alone is bypassed by redirects and alternate IP encodings.
- **Provider failures.** An operator-fixable failure (quota, rate limit, bad key) is classified by its shape and
  answered in our own words with a fitting status (for example 402, 429, 502). The provider's raw text and upstream
  error pages never reach a client; they go to the logs. A test asserts the surfaced message holds none of the raw
  fields.
- **Errors.** No stack traces or internal detail to clients. 4xx for client errors, 5xx for server errors.
- **LLM output used as HTML** is sanitized between the raw response and its use, against an allowlist of tags **and**
  attributes. A check on tag names alone lets `onclick` and `style` through. Log a warning when something is stripped.

## Step 8: Pack checks

Packs may add checks here: see the section for this command in each installed `.claude/packs/*.md` (for example storage buckets, signed URLs and
row-level security).

## Step 9: Contract proof

For each safety invariant this change touches (fail-closed, auth, endpoint, credential, PII, execution boundary), the
contract in `.claude/state/<ticket>/triage.md` needs a row with an exact-path behavioural proof and a failing
counterfactual: the hostile input or state, the observable result, and the bad behaviour the test catches. A green
suite, or a test of a similarly named input, does not pin a guard.

## Step 10: Output

```
SECURITY AUDIT: <branch>

Secrets:            ✅ none tracked or inline / ❌ <file:line> <what> → <fix>
PII/secrets in logs:✅ / ❌ <file:line> logs <what> → <masked alternative>
Auth and tokens:    ✅ / ❌ <issue> → <fix>
Rate limiting:      ✅ / n/a / ❌ <endpoint> → <fix>
Route/UI parity:    ✅ / n/a / ❌ <nav item>: route <path> lacks <guard>
Webhooks:           ✅ verified in constant time before use / n/a / ❌ <handler> → <fix>
Input validation:   ✅ / ❌ <endpoint> → <what to add>
Guarded paths:      ✅ every path to <action> passes <guard> / n/a / ❌ <file:line> <path> skips <guard>
Query scope:        ✅ / n/a / ❌ <file:line> → <fix>
SSRF:               ✅ / n/a / ❌ <file:line> → <fix>
Provider errors:    ✅ / n/a / ❌ <file:line> → <fix>
LLM output as HTML: ✅ tags and attributes allowlisted / n/a / ❌ <file:line> → <fix>
Pack checks:        <one line per pack> / n/a

Verdict: ✅ CLEAR / ⚠️ MINOR ISSUES / ❌ BLOCKED — fix before commit
Required fixes:
  1. <file:line> — <exact change>
Owner action: none | <the single action, e.g. rotate the committed secret>
```

## Rules

- A verified security defect on this ticket's path is fixed on this ticket, regression-tested and re-reviewed. It is
  never deferred because it is small, old or found late. Why: a deferred fix lets the ticket close with the hole open.
- Give the exact fix for every ❌. Flagging is not enough.
- Treat any doubt about PII as PII.
- A skipped safety check on any path is a blocker, not a style note.

## Completion status

End with one of: **DONE** · **DONE_WITH_CONCERNS** (list each item) · **BLOCKED** (say why) · **NEEDS_CONTEXT** (say
exactly what you need).

If a fix can't be worked out after 3 attempts, stop and escalate: a wrong security fix is worse than none.
Escalating is not closing. The finding stays open, the ticket stays blocked, and nothing ships until the owner decides.
