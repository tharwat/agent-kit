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
