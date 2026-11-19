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
