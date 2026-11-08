<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# History: triage, ship, verify and ticket ops

Why the rules in `core/commands/triage.md`, `ship.md`, `verify.md` and `core/docs/ticket-ops.md` exist. Not loaded
every session. If this file and a rule disagree, the rule wins.

## Triage

- **Hand-off before status.** The owner always clears the context between `/triage` and `/operate`, and the agent
  can't. Work was lost several times when triage reported first and saved later, so saving comes before any status.
- **Exact copy in `.claude/state/`.** A tracker's renderer silently dropped `+`, `[]` and `_` from contract rows.
  The comment is a pointer; the state file is the source.
- **Threat-model line.** Without it, review loops on guards, checkers, parsers and sanitizers kept finding
  "bypasses" that needed a deliberately hostile author. One loop ran four rounds that way. The line marks those
  findings `noted`.
- **Mandatory sweeps.** When triage skipped the consumer sweep, the gaps came back mid-review as new findings, each
  costing one of the capped rounds, and several turned into deferral tickets. A sweep at triage is cheaper.
- **Adjacent gaps go in the contract.** Deferring an edge case on the same execution path left a known defect
  shipped. Finishing the feature safely includes it.
- **Null / empty source check.** A nullable field fed new logic, and for a noticeable share of rows the check
  silently skipped. The happy path alone looked correct.
- **Contract ID `C<digits>`.** The freeze step counts rows by regex. Another ID format counted as zero rows and the
  review refused to start.
- **Vector provenance.** An implementer-written vector placed in the independent column looks like independent
  evidence but isn't. Engine and date make the difference visible.
- **Pre-code vectors are mandatory.** Green tests can all exercise adjacent paths. A vector designed without the
  patch makes sure deleting the guard turns something red.
- **One question at a time.** A triage once printed eighteen questions across four tickets. The owner couldn't
  start on any of them. A batch nobody can answer is worse than none.
- **Conflicts take the safer reading.** Owner decision for unattended runs: an engineering conflict is the agent's
  to resolve and record. Only a product decision or an Owner-Kept Gate needs the owner.
- **Epic constraints.** Salvaged from the retired review-work lens: a child ticket triaged on its own can miss what
  was agreed on its epic.
- **Removed: the review-work folder scan** and the review-* commands in the workflow table. `/peer-review` replaced
  that loop, and its "ticket per finding" step contradicted the one-comment open-items rule.
- **Removed: the train block.** Trains are an opt-in pack, so core can't depend on them.
- **Removed: the memory-index step** of the hand-off. It depended on one project's memory layout. The ticket comment
  and the state file carry everything.
- **Removed: scope from the bare diff** when no key is found. A ticket system is required, so `/triage` asks for
  the key instead.

## Ship

- **Covered check is executable.** It existed only as prose, so "covered" at ship time was a recollection. A
  fingerprint comparison removes the guess.
- **Peer-review check is an allow-list.** A deny-list let a misspelt or differently capitalised status through.
  An unparseable record is treated as open, because a broken record isn't evidence that nothing is open.
- **Optional peer review, one exception.** Running two independent reviewers and then shipping past what they found
  turns a real defect into a recorded, ignored one.
- **G3: owner's yes before merge.** The owner's standing rule is never to ship without explicit approval. Picking
  an option or saying "work on X" isn't approval.
- **Transition by name, then a separate comment.** A transition id hard-coded from one project was wrong in
  another. An inline comment on a transition failed because the tracker wanted its own document format.
- **Open items tracker, one writer.** Noted findings written only on their own ticket were lost when that ticket
  closed. One comment per ticket per PR on a standing tracker keeps them; a ticket per finding flooded the board.
- **Don't close when open items can't be filed.** No later step would file them.
- **One failure alert.** A failure that also needed a label used to send a second message about the same event.
  One alert names everything.
- **`Context: ready to /clear`.** Owner decision: one ticket per context. The next ticket starts fresh.
- **Never force-push; no admin merge.** Both bypass the review the merge depends on.
- **Removed:** a static-site deploy paragraph (one project's hosting), the migration push and privilege assertion
  (supabase pack), the needs-a-device-build label (expo-mobile pack), the hard-coded transition id, and the qa
  branch flow (one main branch now).

## Verify

- **Before merge, locally, against real services.** There is no preview environment. A post-merge check alone
  verifies code that is already live.
- **Synthetic rows.** Test rows written by verify runs piled up in a live operator inbox, and the owner found one
  while reading real messages, with no way to tell it was fake. The marker hides them from operator screens. Jobs
  still see them, so the run still tests the real gates.
- **Teardown by explicit IDs.** A cleanup that matched on a pattern in user-controlled text can delete a real
  customer's rows.
- **Seed through seed commands.** Account creation through the public API is captcha-protected, and other tests
  depend on the shared fixtures staying as they are.
- **Build failure means main is broken.** Every later merge would build on top of it, so it is called out at once.
- **Removed:** the deploy-target table and service IDs (render pack), the mobile "deferred" verdict (expo-mobile
  pack), hard-coded test accounts and passwords (env var names in `verify-map.md` only).

## Ticket ops

- **Never write a key you didn't fetch or create.** Twice, under time pressure, work was committed under a guessed
  next number. Both numbers were then assigned to unrelated tickets, and merged history stayed mislabelled.
- **Label writes send the whole set.** The tracker's label field replaced the array, so adding one label removed the
  rest.
- **`get` includes all comments.** Scope changes, decisions and deferrals live in comments more often than in the
  body.
