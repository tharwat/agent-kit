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
- **A one-page design held the scope but not the bug rate, and its "no new states" rule left facts unstored.** The
  rebuild of the large ticket followed an owner-approved one-page design (existing step against "what this adds",
  no new states, file-by-file line estimates). What it showed:
  - *The estimate was half the build.* Every file came out at about twice its estimate, evenly. First-draft bugs
    then landed on the fitted line for the lines actually written. An estimate nobody compares with the diff during
    the build limits nothing.
  - *The part designed as a stored state stayed quiet; the part designed as numbers did not.* The charge had a
    stored state, one writer and a move table, and review found no cluster there. A late requirement (collect the
    result faster) went onto the page as "three numbers, about 30 lines, no new states". That code was under a
    tenth of the production lines and held almost half the findings, at the same count every round.
  - *"No new states" pushed the design to work facts out.* Two facts a re-run needs (is the result already in our
    own storage; which record did this request become) were guessed from time limits, try counts and the order of
    two writes. One was stored but read in a single branch; the other was not stored. The page must ask the other
    question as well: what must this code know when it is run again after stopping at any point, and where is each
    fact stored? A time limit or a try count that stands in for a fact that could be read is the sign.
  - *A read with one question beat three rounds of lens review.* Asked to reassess, the author read the re-run path
    once with one fact in mind (which branches decide without reading it) and found three serious defects no
    reviewer had reported. No test stopped the job between two writes and resumed it; that one test would have
    caught the family.
  - *The owner's "pause and reassess" questions gave the right diagnosis, three rounds late.* Do the findings share
    a cause; is a state being worked out instead of read; is this still the simplest way to meet the requirement.
    The cluster was already visible in the first round's findings. Nothing in the kit asks these before the first
    fix; the 1.12.0 draft stops patching only after a fix has itself broken.
  - *A limit rested on an outside service's documented behaviour, which read two ways and was never measured.*
    Every time limit assumed one reading. When a design depends on what an outside service does, a measurement
    comes before the code.
- **A loop that fixes every small confirmed finding has no end, and its "nothing serious left" describes the
  review's reach, not the code.** The rebuilt large ticket ended at round 4 by the owner's order ("fix, then stop
  reviewing"), with six fixes shipping unreviewed. What its last round and a side-by-side trial showed:
  - *The last round listed 8 findings and none was serious.* Two repeated things the owner had already decided. Of
    the six real ones, three could not go wrong today (behind a switch that is off, two numbers that happen to be
    equal, a row limit six times the data), and two traced to the previous fix batch. All six were proposed as
    "fix", so all six would be new code for another round to read. Nothing in the loop could say "this one is real,
    small and not reachable today: one follow-up ticket". The owner had to end it by hand.
  - *A wider round found the narrow loop's later findings a round earlier, and many it never found.* One round of
    the draft review (three lenses per area plus a second vendor's reviewer) on the round-3 code reported 30
    distinct defects. The project's own next fix batch closed 7 of them. Its round 4 then reported 2 more and part
    of a third. About 20 are still in the code, raised by no project round. Four of those, read again in the code,
    are real and touch a paid item (thrown away, bought twice, let past the spending limit, left unusable). A
    three-lens round that comes back quiet has sampled; it has not swept.
  - *Storing the fact held.* The recovery part gave 4, 3 and 4 findings a round. The fix asked one stored fact once,
    before any other decision about the job, and the next round found nothing serious there. The file grew: the
    simplification was one fact read in one place, not fewer lines.
  - *An open class grew when it was patched.* A choice made by matching patterns on an outside service's free-text
    error was reported as an open class, and the next fix batch added a second pattern to it.
  - The direction: who a defect reaches decides now against ticket, not the size of its fix; a real finding that
    normal use cannot reach today goes to one follow-up ticket; finders and voters are given the owner's decided
    list, so a decided item is not raised again; a round ends on "nothing serious and reachable is open, the rest
    is in a ticket", never on zero findings.
- **A blind rebuild under the 1.12.0 draft held its size but not its review, and did not pass.** One past ticket was
  rebuilt from its text and the owner's recorded answers, in a copy of the project with no history, then reviewed
  under the draft. Pass rules were written before the run. What it showed:
  - *The size held.* The design page estimated 79 production lines; the first draft added 80, and 100 after one fix
    batch. The size check never had to stop the build.
  - *The bug rate did not fall.* The first round confirmed 10 defects to fix now. A blind judge with the original
    build's known bug list found the first draft repeated 5 of the 10 that applied to what it built, and the review
    raised none of those 5.
  - *The second round stopped for a redesign.* It found 6 defects, 4 in lines the fixes wrote. Three of the round-1
    and round-2 findings were one fact: is this item still for sale when a message queued earlier is sent. The code
    answered it from whether the item's facts still existed, not from its stored status. The fix added a status
    check at one send path; the next round found a second path and a branch that skipped the check. The design
    page's re-run question names jobs and retries; a message queued now and sent later is the same case, and the
    page did not catch it. The grouping step named no shared cause in round 1.
  - *An event fired out of proportion.* A wrong-text regression in a fix triggered a redesign because it shared a
    mechanism with an earlier fix. A defect in a fix whose only loss is wrong text is just fixed; the same should
    hold for the same-mechanism event.
- **A second blind rebuild, after two fixes to the draft, did worse.** The same ticket, a fresh agent, the same
  pass rules. The design page now asked what a later action must check. The agent wrote 61 production lines
  against an estimate of 64, then answered that very question with the smaller option: rely on the side effect
  (the item's facts are removed) instead of reading the stored status at send time, because the kit also says the
  smaller option is the recommended one. The judge found 6 of 11 applicable known bugs repeated (the first run: 5
  of 10); round 1 confirmed 12 defects to fix now and stopped on an open class. Across both runs:
  - *Size fell about five times; the defects did not.* Roughly 10 to 13 confirmed defects on 60 to 100 lines.
  - *About half the confirmed defects were in lines the change did not write.* The sweep reads the code around the
    change, and the rule "fixed here whoever wrote it" makes each one this ticket's work.
  - *The same known bugs survived both runs and both reviews:* a one-click destructive action, an action that can
    be repeated on an item already in its final state, an item in a final state that can still be edited, and a
    message naming a step that no longer exists. Each is a state the change made final without asking what may
    still happen to it. The design page's lifecycle box asks this, and both runs filled it without catching them.
  - *Two kit rules collided:* "the smaller option is recommended" won over "a side effect that stands in for a
    fact is a defect". A rule that says what is a defect must say it beats the smaller option.
