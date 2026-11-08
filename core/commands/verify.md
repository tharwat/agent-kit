---
description: Drive the changed behaviour end to end against real services before merge, then confirm the deploy and logs after merge.
argument-hint: "[<ticket>]"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# Verify

Invoked as `/verify [<ticket>]`.

`/verify` drives the changed route, webhook, job, screen or migration end to end and observes what really happens.
`/ship` requires it for any behaviour change. `/test` is the lighter check.

A feature branch is deployed nowhere (no preview environment), so verification has two halves, and the second
never replaces the first:

- **Pre-merge (the gate):** run the branch's code locally against the real backing services.
- **Post-merge (the confirmation):** after `/ship` merges, confirm the deploy is live and the change shows in the
  logs.

`docs/agent/verify-map.md` holds the surface map (changed path → how to drive it), dry-run entry points, seed
commands, protected fixtures, test-account env var names and the irreversible side effects that never run as a test.
`docs/agent/integrations.md` says how each webhook is signed.

---

## Step 0: Classify the surface

```bash
git fetch origin
git diff origin/<MAIN_BRANCH>...HEAD --name-only
```

Map each changed path to its surface with `verify-map.md`. Only docs, comments or tests changed → verdict
`⏭️ SKIPPED — no runtime surface`, and stop.

Packs may add checks here: see the section for this command in each installed `.claude/packs/*.md`.

## Step 1: Drive it locally

Start the app with `<DEV_SERVER_COMMAND>` when the surface needs it, then exercise the **changed** path, including
the failure path the ticket fixed. Real requests and real responses, not a description of what would happen.

- **Authenticated routes:** log in through the app's login route with a test account (env var names from
  `verify-map.md`) and reuse the real session. Calling an internal function directly verifies the function, not
  the route.
- **Webhooks:** send a correctly signed payload. An unsigned probe only proves the rejection path.
- **Screens:** exercise the authenticated screen the ticket names, with zero page errors.
- **Seeding:** use the seed commands in `verify-map.md`. Never create accounts through a protected public endpoint
  (captcha, rate limit). Never change a protected fixture.
- **Nothing irreversible as a test.** Use the dry-run entry point for anything in the irreversible list.

## Step 1.5: Rows you create are synthetic (required)

Driving a flow against the real database writes real rows. They must never look like real users' data.

- Every row a verify run creates carries `<SYNTHETIC_MARKER>`. Writing such rows is allowed; any other write to
  production data is Owner-Kept Gate G2.
- Operator screens (lists, counts, search, bulk actions) filter marked rows out, so a row left by a crashed run is
  invisible rather than looking like a person. Keep a test that fails when an operator list lacks the filter.
- Background jobs and automated handlers **don't** filter it. A synthetic row has to flow through the real gates,
  or the run stops testing them. Never "fix" a verification by hiding its row from a job.
- **Tear down at the end** by the explicit IDs you recorded, never by a pattern: matching on user-controlled text
  is how a cleanup deletes a customer. For example
  `DELETE FROM <table> WHERE id IN (<ids you created>) AND <SYNTHETIC_MARKER> = true`, children before parents.
  Then confirm the count of marked rows from this run is zero.
- A table `/verify` must write to that has no marker column → stop and report it. Adding the column is a schema
  change for its own ticket.

## Step 2: Ground the observation in state

Confirm the effect, not just the run:

- **Data:** did the row land with the right **derived** values (computed status, masked field, count)?
- **Logs:** find the log line the change emits.
- **Regression:** reproduce the failure against the pre-fix behaviour first, then show it fixed. A fix you can't
  reproduce, you can't claim.

## Step 3: Post-merge confirmation (after `/ship` merges)

- **Deploy:** confirm every affected service's latest deploy is live. Changed shared code → check **every**
  service built from it.
- **Logs:** read them from `<LOG_SINK>` and find the change's log line. `<LOG_SINK>` is `none` → record
  `logs — no sink configured`.
- A failed build or failed update means the merge broke `<MAIN_BRANCH>`. Say so at once and loudly, and don't start
  other work.

Packs may add checks here: see the section for this command in each installed `.claude/packs/*.md`.

## Step 4: Output

```
VERIFY: <ticket / branch>

Surface:      <route / webhook / job / screen / migration / …>
Pre-merge:    <how it was driven locally>
Evidence:     <the response / query result / log line / dry-run output, pasted>
State check:  <the query and what it returned>
Synthetic:    <rows created, by id; teardown confirmed> | none
Regression:   <reproduced, then fixed> | n/a
Post-merge:   <service — deploy <id> live at <time>; log line seen> | pending merge

Verdict: ✅ VERIFIED — behaviour observed
         ⚠️ PARTIAL — <exactly what is unverified, and why>
         ❌ FAILS — <what was observed instead>
         ⏭️ SKIPPED — no runtime surface
```

Post this block with ticket op **comment** `<ticket>`, its first line changed to `Verify: <ticket> — <verdict>`
(one comment per run, so `/release` can find the evidence later).

Packs may add verdicts here: see the section for this command in each installed `.claude/packs/*.md`.

## Rules

- **Paste the evidence.** "It should work" isn't a verdict, and neither is a green test suite.
- **Never fabricate output.** A path that can't be exercised is `⚠️ PARTIAL`, said plainly.
- `⚠️ PARTIAL` isn't a pass. `/ship` merges on `✅ VERIFIED`, `⏭️ SKIPPED`, or a pack verdict
  that the pack's `## /verify` section declares passing (for example a deferred mobile build). Nothing else.

## Completion status

End with **DONE** (✅ or ⏭️, with evidence) · **DONE_WITH_CONCERNS** (⚠️ PARTIAL, gaps listed) · **BLOCKED**
(❌ FAILS, or it can't be driven; say why) · **NEEDS_CONTEXT**.
