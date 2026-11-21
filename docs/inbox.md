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
- **A state several screens read is stored, not worked out (the triage half of a lesson whose review half shipped
  in 1.12.0).** In one ticket a job's state was worked out at read time from several fields (status, an outcome
  code, a provider id, a reconciler's list, a time limit), and every round found a reader that didn't select a
  field, a writer that didn't set one, or a timing gap. Triage should catch it before code: a state with more than
  two values that several screens read is stored. Storing it isn't enough on its own: the first try added the
  column, but readers still read the old fields and eight places wrote the column directly. A stored state needs
  one function as its only writer, with a table of allowed moves that refuses all others and a test for every row.
  Every reader uses the state alone.
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
- **Long review loops come from two kinds of work, and both can be named at triage.** In a second project that
  runs three-reviewer consensus rounds, 15 of 25 post-op runs ended within three rounds and 9 ran past three or
  needed a redesign. Short did not mean finished: under a severity bar, six short runs fixed 11 findings and sent
  31 to the tracker, and only five of the 25 runs ended short with nothing from review left open. Of the 9 long
  runs, five were code that judges free text with patterns or word lists, and two were code that
  works a state out from several fields. Each round found one more phrase, format or field combination, and each
  fix added a case and broke another; in one ticket the count per round went 8, 7, 11, 9. The work has no finite
  list of cases, so no review can finish it. The design must close it before code: a stored state with a move
  table, a rule on structure or position that needs no meaning, or a model call that fails closed.
  (1.12.0 shipped the review half: such a finding is an `open class` and is never fixed alone. Naming the two
  kinds at triage still waits.)
