<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Inbox: lessons waiting for the next release

Lessons from project sessions land here first, worded generically (no project facts). They ship together, between
the project's tickets, as one PR the owner approves (`CLAUDE.md`, "Lessons from a project wait for a release").
Before a release, group them by cause and fix the cause; a lesson that is a symptom of another gets no change of its
own. Move each shipped lesson to the CHANGELOG entry that shipped it.

## Waiting

- **1.11.0's "derive every list with a test" turned a docs ticket into building checkers.** Rounds 5–7 of the
  first ticket under it found 20, 24 and 22 defects, with 13, 16 and 17 created by fixes. Each fix added a checker
  (a shell-command reader, an SQL verb list, row shapes, word lists, program lists). Each claimed completeness, and
  the next round disproved it. Regressions followed. The only rounds where the count fell were the ones that
  deleted something. The verifiers voted `redesign` every round, and each redesign was a rebuild. The cause:
  rewarding completeness claims backed by new code, against `CLAUDE.kit.md`'s "build the deliverable, not machinery
  around it". The direction to take:
  - a claim the change doesn't need is removed, not proven;
  - a rule replaces a list;
  - a redesign deletes or simplifies and never adds a checker;
  - code that judges or parses text is never written to prove a doc.

- **A blind pre-code check did not hold up on a large live ticket.** On replays of four past tickets it covered 59%
  of the first-draft bugs. Live, on a large ticket, it fully covered 6 of 38 and partly covered 11. In 4 cases its
  own expectations prescribed the defect. Its tests exercised one path each, so even the covered bugs got through.
  One of its owner questions added a recovery subsystem, which then held about half of all review findings. Don't
  ship it as it stands. If it comes back, it must not add scope, and every test must drive the real path and
  inputs.
- **A capped review over a whole large diff drips; it doesn't converge.** A review that reports at most 10
  findings found 8, 10, 7, 9, 4 and 8 per round, and 39 of 46 were already in the first draft. A review that
  returns exactly its cap hasn't finished. Split a large diff into areas and review each one without a cap. Review
  a fix batch without a cap too.
- **Fix batches regress through the same miss as first drafts.** In the review after one uncapped sweep, 4 of 9
  defects were in the sweep's own fixes:
  - a step added to a flow was skipped by an early return;
  - a resumed path called out before checking the stored result;
  - a lookup narrowed for one caller broke another caller;
  - a reader needed fields that the new writer never set.
  A fix that changes a function's scope or steps must first list that function's exits, callers and readers, as a
  first draft should. The next review showed the check also needs the reverse direction: a fix that looked up a row
  by a key, with a limit of 1, missed three other writers that copy the same key onto other rows. A lookup needs
  every writer of the key it matches on.
- **Fixes that add a new state keep the rounds going.** Two rounds in a row, a fix added a new user-facing outcome
  or live state. The next review then found its biggest defects in the readers and timing of that new state. A fix
  should reuse an existing state that already behaves as needed, and ask the owner before adding a new one.
  Rounds 9–11 of one ticket were spent on a single rare edge case: a paid job the app may still collect. Each
  round added a protection, and the next round found that protection's bugs. The fix rounds should weigh what a
  protection costs against how rare and how cheap the edge case is. Where the protection keeps breaking, removing
  it and accepting the small loss is a valid fix.
- **Nothing in the loop triggers a redesign, so it never happens.** In one ticket, a job's state was worked out at
  read time from several fields (status, an outcome code, a provider id, the reconciler's list, a time limit).
  Every round from 9 to 11 found a reader that didn't select a field, a writer that didn't set one, or a timing
  gap. The loop only ever offered "fix these, review again". The trigger should be an event, not a count: when a
  finding sits in an earlier fix to the same area, stop fixing that area and redesign it. Store the state as one
  column, written where it changes and read everywhere; delete the code that works it out. The owner approves the
  design (states, writers, readers, deletions) before any code. The same rule belongs at triage: a state with more
  than two values that several screens read is stored, not derived.
  Storing it isn't enough on its own. The first try added the column, but readers still read the old status and
  code fields, and eight places wrote the column directly. The next review found 4 important defects, all from
  readers or writes in the wrong order. A stored state needs one function as its only writer, with a table of
  allowed moves that refuses all others and a test for every row. Every reader uses the state alone.
- **The ticket should have plugged into the lifecycle that already existed.** The project already kept a stored job
  lifecycle (queued, running, waiting at the provider, succeeded, failed), with a reconciler for paid provider
  renders and guards against paying twice. The change was "one more provider, plus a charge". Instead it built a
  provider-specific set of phases and a recovery system next to the existing ones: about 2,400 production lines and
  rounds into double figures. The pre-code check made it worse by listing 201 cases, and each case became code. The
  plan should start from the entity's stored states and their allowed moves, reuse the existing states, and say
  what the new thing adds to them. Cases come from that table. A plan that adds a parallel state system next to an
  existing one is a design defect, caught before code.
