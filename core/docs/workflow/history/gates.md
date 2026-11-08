<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# History: the gate commands

Why `/security`, `/api-contract`, `/guard`, `/compliance` and `/docs-update` say what they say. This file is not
loaded every session. If it and a rule disagree, the rule wins.

## /security

- **A verified security defect is fixed on its own ticket.** Turning a security finding into a follow-up ticket
  so the current one can close ships the hole. The fix, its regression proof and its re-review all
  happen on the ticket that found it.
- **Escalating is not closing.** When an agent can't work out a safe fix, it hands the decision to the owner. That is a
  question of authority, never a licence to leave the defect unfixed, so the ticket stays blocked until the owner
  decides.
- **Contract proof for safety invariants.** A green suite, or a test of a similarly named input, doesn't show that
  a guard is pinned. Each safety invariant needs an exact-path proof and a counterfactual that fails without the
  guard.
- **Committed secrets are always BLOCKED.** "Note it and continue" leaves a live credential in history. Removing
  the file from tracking doesn't remove it from history, so the secret must also be rotated, and that is the owner's
  call.
- **Constant-time webhook checks, before the body is used.** An unverified webhook must be rejected, not processed
  and logged: anything done before the check runs on a forged payload. A plain string comparison also leaks timing.
- **Every path to a guard.** A sanitizer was added to the text-message path into an LLM pipeline. Image captions and
  button replies reached the same pipeline without it. A guard on one path is a bypass, not a fix.
- **Route/UI guard parity.** A nav item was hidden for users who hadn't finished signing up, but its route had only
  the login guard. Typing the URL got straight in.
- **LLM output as HTML.** A sanitizer allowed `<p>` and `<strong>` but didn't strip their attributes, so
  `<p onclick=…>` survived. Tags and attributes both need an allowlist.
- **Query scope.** A results query was widened for one role, but the filter-option queries weren't. Some rows showed
  up in results but could never be reached through any filter.
- **SSRF.** Fetching an operator-pasted URL server-side is a way into the internal network. A private-IP regex copied
  inline was weaker than the shared guard. A string denylist is beaten by redirects and decimal, hex, octal or IPv6
  forms of an address. Hence one shared guard, manual redirects, and a byte cap.
- **Provider failures in our own words.** A catch-all turned a quota or bad-key failure into "please try again",
  which the operator couldn't act on. Echoing the provider's text instead leaked internal detail, and an upstream
  HTML error page once reached an operator's screen verbatim, server banner included.

## /api-contract

- **Always additive (owner, 2026-11-07, Q7).** One source project reshaped its internal API freely and moved every
  consumer in the same change. The other kept old shapes working because its installed apps update only through a
  store release and it had no minimum-version check. The kit can't know that every client lives in the repo, so the
  stricter rule is fixed for every project.
- **A compatible break needs no owner approval.** It used to need one. It now needs proof that clients in the field
  keep working, which is a better check than a yes.
- **External fields are grounded this session.** Vendor fields recalled from memory or training data can be
  wrong or out of date. A field not seen in a real payload or live docs this session is UNVERIFIED.
- **Webhook branch keys come from a real event.** A remembered event name or status can be wrong, and a handler
  that branches on it silently does nothing. The unknown case must be handled explicitly.

## /guard

- **Additive schema changes, with phased removal (owner, 2026-11-07, Q7).** DROP, final column removal and data
  deletion are G5. Making data client-readable is G6. The other source allowed any destructive change with a backout
  and a snapshot. Its safety table is kept for the steps that now go to the owner.
- **Never apply in the gate.** With one database there is no QA copy to absorb a mistake. The gate validates;
  applying is a separate, later step.
- **Mentally run the backout.** A backout is only worth something if it really reverses the change. Reverse SQL
  can recreate a dropped column but not its data, which is why lossy steps also need a snapshot.
- **Grants, row-level security and the CI grant checker live in the database pack.** They depend on one database
  product's roles. Core keeps only what any Postgres migration needs, such as a fixed `search_path` on
  SECURITY DEFINER functions.
- **Database defects on the ticket's path are fixed on the ticket.** A missing backout or `search_path` was waved
  through as "pre-existing". It joins the ticket's contract instead.

## /compliance

- **Only the verified-claims table counts.** Product copy once cited a law that didn't apply, and quoted penalties
  nobody had checked. Every claim now comes from the project's verified table, or it is BLOCKED.
- **Exact corrected strings.** A violation is only actionable with the replacement text; a description of the
  problem leaves the fix to guesswork.
- **Laws, regulators and brand specifics moved to `docs/agent/copy-rules.md`.** They belong to one project.

## /docs-update

- **Field-level spec check.** Endpoints already in the spec gained response fields one at a time, and the spec missed
  them. Every field in a changed response is now checked against the documented schema.
- **Planning docs are reconciled against tickets and code.** A plan still said "not built, next: X" after X shipped,
  and the next session started from it. Reality comes from ticket ops and the code, never from memory or the diff.
- **No README is created unprompted.** Creating docs is a scope decision, not a docs fix. A folder that needs one
  is noted for the owner.
- **Project file lists moved to `docs/agent/docs-map.md`.** The source listed its own knowledge-base files, a line
  number in its API spec and a retrieval re-ingest step. None of that is generic.
