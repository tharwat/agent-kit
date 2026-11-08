---
description: API contract gate. Checks that endpoint changes are additive, every consumer still matches, and every external field is grounded in a real payload.
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# /api-contract

Run whenever an endpoint, outbound integration call or inbound webhook handler changes. `/post-op` skips it
otherwise and records `⏭️ Skipped — no API changes`.

**The policy is fixed: changes are additive.** Existing fields, URLs and status codes are never removed or changed.
A breaking change ships as a new route, or keeps the old shape working for clients already in the field. Why: a
client outside this repo can't move in the same change.

## Step 1: Find the changed surface

```bash
git fetch origin <MAIN_BRANCH>
git diff origin/<MAIN_BRANCH>...HEAD -- <api paths>
git diff HEAD -- <api paths>
```

API paths and consumer surfaces come from `docs/agent/source-layout.md`. List:

- new routes: method, path, auth, what they return;
- modified routes: what changed in path, method, params, response shape or status;
- removed or renamed routes;
- new or changed outbound integration calls, and the response shape the code now depends on;
- new or changed inbound webhook handlers.

## Step 2: Additive check

| Change to an existing endpoint | Allowed? |
|---|---|
| New optional response field | ✅ |
| New optional param | ✅ |
| New route | ✅ |
| Field renamed or removed | ❌ |
| Status code changed | ❌ |
| Required param added or removed | ❌ |
| Response envelope changed | ❌ |

For each ❌, prefer an additive alternative. A break that is truly needed carries, in the same change:

1. the new shape at a new (for example versioned) route, or the old shape kept alongside the new one;
2. every consumer that should use the new shape, updated;
3. proof that clients already in the field keep working. A client that updates only through a store release or a
   customer's own deploy is never assumed retired unless the project enforces a minimum version. A shape no released
   client ever used may go once every consumer using it is updated in the same change. Saying "old clients will
   break" is not compatibility. Record which client versions you checked.

A compatible break needs no owner approval, only that proof.

## Step 3: Consumer impact

For each consumer surface in `docs/agent/source-layout.md`, grep for each changed route path:

```bash
git grep -n "<route path>" -- <consumer paths>
```

- New route: is there a consumer call? Should there be?
- Modified route: does every call still match? A dropped field silently renders as nothing.

Assess every consumer surface, even when the answer is "none".

## Step 4: External contract grounding

For each new or changed outbound call, confirm every field and endpoint against a real request/response or the
vendor's live docs **seen this session**. `docs/agent/integrations.md` says where those docs live.

- Not seen this session? Fetch it, or mark the field UNVERIFIED. Never assert a vendor field from memory.
- Inbound webhooks: take the branch keys (event type, status) from a real event. Handle the missing or unknown case
  explicitly.

## Step 5: Logging

Each new route or handler logs start, success and failure, with masked identifiers (detail in `/observability`).

## Step 6: Pack checks

Packs may add checks here: see the section for this command in each installed `.claude/packs/*.md` (for example request/response type coverage,
or a mobile client check).

## Step 7: Output

```
API CONTRACT REVIEW: <branch>

New routes:
  <method> <path> — auth <yes/no> — logs ✅/❌ — consumer ✅ present / ⚠️ needed / n/a
Modified routes:
  <method> <path> — changed: <what> — additive ✅ / compatible break ⚠️ <proof> / ❌ breaks clients in the field
Consumers:
  <surface>: ✅ no change needed / ✅ updated / ⚠️ <file:line> needs <what>
External contracts:
  <integration call> — ✅ grounded (<payload or docs seen>) / ⚠️ UNVERIFIED — <how to confirm>
Pack checks: <one line per pack> / n/a

Verdict: ✅ CLEAR / ⚠️ UPDATES NEEDED / ❌ BREAKING CHANGE — stop
Required actions:
  1. <file> — <what>
Owner action: none
```

## Rules

- A change that breaks clients in the field: stop and report it. Don't patch around it.
- A new route without its consumer check and logs is not done.

## Completion status

End with one of:

- **DONE**: every changed route reviewed, consumers assessed, external fields grounded.
- **DONE_WITH_CONCERNS**: list each item. A compatible break lands here, with its proof.
- **NEEDS_WORK**: a consumer not yet updated, or an external contract not grounded. Say which.
- **BLOCKED**: a change that breaks clients in the field, or consumer impact can't be assessed. Say why.
- **NEEDS_CONTEXT**: routes or consumers can't be found. Say what is missing.
