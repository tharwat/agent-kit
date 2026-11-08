<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Pack: turnstile

Cloudflare Turnstile bot protection. It installs Cloudflare's third-party `turnstile-spin` skill at
`.claude/skills/turnstile-spin/`, fetched from GitHub at the commit pinned in `pack.json` and checked against its
sha256; the kit never copies it. Ask for "set up Turnstile on <form or endpoint>" and the skill runs the setup:
widget, frontend snippet, server-side siteverify, validation. Core commands read the sections below at their
"Packs may add …" lines.

**The rule:** a Turnstile token proves nothing until the **server** checks it. A widget on the page with no
siteverify call in the handler protects nothing.

## /triage

A ticket that adds or changes a public, unauthenticated action that costs money or creates records (sign-up, login,
OTP or SMS/WhatsApp send, password reset, contact form, session creation) gets a contract row: "a request without a
valid Turnstile token is rejected by the server", with the hostile case "a scripted POST with no token, a reused
token, or a token for another action".

## /security

For each handler the diff protects with Turnstile, or each public action that costs money and has no protection:

- **Server-side siteverify** is called before any side effect, with `TURNSTILE_SECRET` from the environment, and
  the handler requires `success === true`, the expected `action`, and a `hostname` in `TURNSTILE_HOSTNAMES`.
- **Fails closed:** a missing token, a siteverify network error or a non-200 rejects the request. It is never
  skipped "to keep the form working".
- **No secret in the client:** `TURNSTILE_SECRET` never appears in frontend code or a public env prefix (`VITE_*`,
  `NEXT_PUBLIC_*`, …). Only the sitekey is public.
- **Production hostnames** exclude `localhost` and `127.0.0.1`.
- A new public action that costs money (OTP, SMS, paid API) with no bot protection is a finding (S2).

Report line: `turnstile: siteverify ✅ | ❌ <handler> · fail-closed ✅ | ❌ · secret server-only ✅ | ❌ · n/a`.

## /verify

**At Step 1,** for a protected handler: one request with a fresh real token succeeds, the **same token replayed**
is rejected, and a request with no token is rejected. Paste the three responses. Cloudflare's published test
sitekeys and secrets (always pass, always fail) are allowed locally only, never in production config. A handler
that can't be driven with a real token is `⚠️ PARTIAL — turnstile not exercised`.
