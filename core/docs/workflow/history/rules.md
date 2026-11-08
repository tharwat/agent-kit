<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Rules: rationale and history

Why the rules in `CLAUDE.kit.md`, `CLAUDE.md` and `.claude/rules/` say what they say. This file is not loaded into a
session, and no rule lives only here. If this file and a rule disagree, the rule wins.

## How the rules layer is built

- **A separate `CLAUDE.kit.md`.** Kit upgrades replace one file and never touch the project's own `CLAUDE.md`, so
  project rules and Project facts survive every upgrade.
- **A word budget for what is always loaded** (`CLAUDE.kit.md` + `CLAUDE.md` + unscoped rules: the kit's own text
  stays within 2,500 words, an installed project within 3,500, which leaves room for the project's rules). Long
  always-loaded instructions get skimmed, and rules buried in narrative get missed. Rules tied to one area carry
  `paths:` frontmatter so they load only when a matching file is touched; incident stories live here.
- **`CLAUDE.kit.md` states rules, not their detail.** Where a command or another always-loaded file already holds a
  definition, `CLAUDE.kit.md` names the step and stops: `/post-op`'s gate list (observability, security, API
  contract, migration guard, compliance, docs, test and verify, mock fidelity) lives in its command file; masking PII
  in logs is `.claude/rules/security.md`; the `<LIKE_THIS>` notation is explained in the Project facts block of
  `CLAUDE.md`; the project docs are listed in `docs/agent/` itself.
- **Facts as `<LIKE_THIS>`, not literals.** Commands stay identical across projects, and a changed fact is edited once.
- **Path-scoped rules replace per-area session profiles.** Profiles each repeated the universal rules, and the
  copies drifted apart.

## Forbidden actions

- **Destructive commands.** A delete "guarded" behind a check, or a runbook line telling an agent to delete, is the
  same risk one step removed. Renaming, stashing and disposable worktrees keep every change recoverable. A checkout
  that refuses to overwrite local work replaces a hard reset for syncing a stale tree.
- **Secrets.** Once committed or pasted into a ticket, a secret has to be rotated; naming the env var is enough for
  anyone who needs it.
- **No direct commits to the main branch.** With one long-lived branch, the PR in `/ship` is the only point where
  review, verification and the owner's yes all meet.
- **Additive API and schema.** Installed and cached clients can't be forced to update, so removing a field, URL or
  status breaks every consumer at once, with no error on their side, only missing data. Explaining that old clients
  will break is not compatibility. This is a fixed kit rule rather than an install answer, so every project gets the
  safe default. A destructive schema step stays possible, behind G5, with a backout that really reverses it and a
  snapshot when data would be lost.
- **Never invent a ticket key.** A guessed key links work to the wrong item or to nothing, and the trail is lost.

## Owner-Kept Gates and Critical Systems

- Agents approve everything except G1–G7. Asking the owner for every risky change made the owner the bottleneck
  without making changes safer; the stricter Critical Systems checks do that instead.
- **G3** means every `/ship` waits for an explicit yes: work is never shipped on an implied approval. Invoking a
  ticket train run is the yes for exactly that queue.
- **G7** guards the guards. Adding or tightening a check is always welcome; quietly removing one is how protection
  erodes.
- Gates are defined once and cited by label everywhere else, because restated copies drift.
- A Critical Systems failure found after merge is fixed forward on a new ticket: with one branch there is nothing to
  hold back, and a revert can strand a migration.

## Review workflow

- **`/operate` exists** because zero-context reviewers kept finding defects that were plainly visible in the
  author's own diff: a normalizer that diverged from its counterpart, a sibling screen left on the old pattern.
  Doing the work correctly the first time is cheaper than any review round.
- **The review loop is capped.** An open-ended loop (fix everything, any fix makes another round due, the owner asked
  every round) made tickets run many rounds. The severity bar plus a round cap ended that; only escalations reach the
  owner.
- **Noted findings go to one standing tracker**, one comment per ticket. Findings left as comments on a ticket that
  `/ship` then closed were never seen again. Exactly one step writes them, because several writers at different
  moments lost items.
- **`Owner action:` ends every report.** Restating already-tracked items as "still open" made the owner hand-hold
  work that needed nothing from them.
- **`/post-op` is never optional, including for `.claude/` changes.** Command and rule files are what an agent
  executes, so a defect there is as real as one in source. A mechanical sweep is the least safe change to skip:
  its blast radius is every site it touched, the author stops reading carefully after the first few, and a syntax
  check or test suite may never execute the changed lines.
- **Peer review is optional.** As a mandatory gate with a repeat-until-clean loop it became the pipeline's
  bottleneck. Once a pass has run, an unresolved verified finding stops `/ship`: shipping past what reviewers found
  is worse than not running them.
- **Verified defects are fixed on their ticket.** "Pre-existing" or "found late" is attribution, not permission to
  leave known broken behaviour in place.
- **One question at a time, with a pro and a con.** A long batch of questions was unanswerable; one plain question
  gets a decision.

## Verification discipline

- Repeated wrong guesses about an integration failure wasted hours when the provider's error body named the cause
  all along. Hence: read the error first, verify before asserting, and change approach after being wrong twice.
- **Run the suite exactly as written.** Hand-picked subsets and "equivalent" scripts have hidden reds that were then
  reported as green. Test counts written in docs drift, so take them from the runner.
- **Green is not behaviour.** A suite asserts logic, not the live surface; the verification ladder exists because
  merged-with-green-CI changes still failed at runtime.
- **Mutation-test checks.** A test that passes with the guard deleted gave false confidence more than once.
- **Evidence** means something observed: a log line, a query result, dry-run output. "It should work" is a
  prediction, not evidence.

## code-style.md

- Handlers throw: a success response with missing fields can't be told apart from a valid one.
- Delivery failures throw: log-and-return made the scheduler record success when nothing was delivered.
- Idempotency reads check errors: proceeding as if nothing was sent while the store is down double-sends messages,
  double-charges or double-processes events.
- Side effects after the atomic operation: an audit row written before a failing operation records something that
  never happened.
- Counts: removing the display limit to fix a count is also wrong, because an unlimited list can grow without bound.
- Renames: a heading changed while its tooltip keeps the old name is an incomplete rename.
- The log prefix exists so one grep in the log sink finds every line from a file.

## security.md

- LLM output: a sanitizer that checks only tag names passes a tag with an event-handler attribute, so attributes are
  rejected too. A bad model response or a prompt injection can produce script or frame tags.
- Query scope: when results and filter dropdowns use different scopes, items appear that the filters can't reach.
- Entry points: a guard on text messages that skips image captions is a bypass, not a fix.
- SSRF: a string denylist is bypassed by redirects and by decimal, hex, octal or IPv6 encodings of the same address.
- Provider errors: echoing a provider's response leaks infrastructure detail and tells the user nothing they can act
  on.

## Claude and Codex

- Codex loads `AGENTS.md`, not `CLAUDE.md`, so the must-never-miss lines are restated there verbatim, and CI fails
  when the copy drifts.
- Codex skills link to the Claude command files instead of copying them: copied skills drifted, and a blind
  find-and-replace once produced paths that didn't exist.
