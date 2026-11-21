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
- **First-draft bugs track the production lines written, and nothing tried so far has changed the rate.** Across 19
  past tickets of one project, first-draft bugs against merged production lines gave r = 0.82: about 3 bugs, plus 1.2
  for every 100 production lines. Tickets under 300 lines averaged 5 bugs; tickets over 700 averaged 15. The large
  live ticket that ran the pre-code check landed on the same line (about 2,400 lines, 33 predicted, 38 found), so
  the check changed the amount of code, not its quality. Review fixes then grew that ticket's production code by
  about half. The lever with evidence behind it is writing less: a smaller design, a smaller ticket, and fixes that
  remove code. (Merged lines include fix lines, so part of the fit is circular.)
- **The plan named the existing mechanism and still built beside it.** A contract row cited the existing recovery
  job and the stored request id, so "look for the existing lifecycle" was not the missing step. The plan was a list
  of rows and cases, and nothing in its form set the existing mechanism against what the change adds. When the
  owner asked for exactly that (a table of existing step against "what this adds", with "nothing" allowed; no new
  states; reused and new code file by file with estimated lines; what is out of the ticket), the same agent
  produced a one-page design about a fifth the size. The form of the plan did what the instruction to look had not.
- **An owner question with a recommended option is the agent's decision in practice.** On one ticket the owner took
  the recommended option on 6 of 7 pre-code questions. Three of those added scope that the owner later cut: a
  recovery subsystem (recommended over the challenger's "accept the loss") and two forced confirmation steps. A
  question whose option adds a mechanism or a state must say what it costs (lines, new states, new failure paths),
  and the smaller option is the recommended one unless the owner has asked for the protection.
- **A replay that scores written expectations measures paper.** The pre-code replays asked whether an expectation
  covered each known bug (59%). Live, the tests written from those expectations each drove one path, and one passed
  only because it sent a field the real button never sends. A replay counts only if it builds the code and a review
  sweeps the result.
- **The kit's own review still has caps.** Each reviewer in `consensus-review.js` is told to "report at most 15",
  and the fallback runs the built-in review at its default limit. Both contradict the capped-review lesson above.
- **Long review loops come from two kinds of work, and both can be named at triage.** In a second project that
  runs three-reviewer consensus rounds, 15 of 25 post-op runs ended within three rounds and 9 ran past three or
  needed a redesign. Short did not mean finished: under a severity bar, six short runs fixed 11 findings and sent
  31 to the tracker, and only five of the 25 runs ended short with nothing from review left open. Of the 9 long
  runs, five were code that judges free text with patterns or word lists, and two were code that
  works a state out from several fields. Each round found one more phrase, format or field combination, and each
  fix added a case and broke another; in one ticket the count per round went 8, 7, 11, 9. The work has no finite
  list of cases, so no review can finish it. The design must close it before code: a stored state with a move
  table, a rule on structure or position that needs no meaning, or a model call that fails closed.
- **A redesign that keeps the same kind of solution doesn't end the loop.** Redesigns that deleted the mechanism
  (a text classifier removed, a decision stored on the record, four pattern lists replaced by one order rule) ended
  clean in one or two rounds. Redesigns that rebuilt the pattern matching in a tidier form kept producing findings.
  "At most one redesign" is the wrong limit; "the redesign changes the kind of solution and removes code" is the
  test.
- **The fix rule has swung between two failures.** "Fix every verified finding" had no stopping point (rounds into
  the tens). A severity bar that sent small findings to the tracker stopped the loop and filled the tracker with a
  dozen items a ticket, so the owner reversed it: fix everything the ticket wrote. That brought the loops back,
  and in one ticket every change after round 1 was undone because round 1 had found nothing that needed fixing.
  Both rules treat all small findings alike. They are three different things: a real defect a normal action
  reaches (fix it, however small); one more member of a class with no end (don't fix it; close the class or state
  its boundary); and a case that needs a fault or never occurs in the project. For that third kind the owner's
  direction is a vote on facts by agents other than the author: what is lost and to whom (data, money, a person
  wrongly contacted, security, hand work for the operator, appearance), what has to happen first, whether anyone
  would notice, and what the fix costs. A small fix is made now whatever the vote says; only a costly fix for a
  remote, bounded case becomes a ticket, and the ticket carries the analysis. The bar failed before because the
  author applied it to its own findings and "noted" was the easy answer.
- **Zero-context reviewers aimed at a checker never run out.** On a ticket that built a parser-style check, two
  hostile reviewers found about 11 new evasions a round for four rounds while the real change was clean from round
  2. The threat-model line and the prior-art questions the kit already has came from this; they are needed on
  every round, by every reviewer.
