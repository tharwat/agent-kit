<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Inbox: lessons waiting for the next release

Lessons from project sessions land here first, worded generically (no project facts). They ship together, between
the project's tickets, as one PR the owner approves (`CLAUDE.md`, "Lessons from a project wait for a release").
Before a release, group them by cause and fix the cause; a lesson that is a symptom of another gets no change of its
own. Move each shipped lesson to the CHANGELOG entry that shipped it.

## Waiting

- **A blind pre-code check did not hold up on a large live ticket.** On replays of four past tickets it covered 59%
  of the first-draft bugs. Live, on a large ticket, it fully covered 6 of 38 and partly covered 11. In 4 cases its
  own expectations prescribed the defect. Its tests exercised one path each, so even the covered bugs got through.
  One of its owner questions added a recovery subsystem, which then held about half of all review findings. Don't
  ship it as it stands. If it comes back, it must not add scope, and every test must drive the real path and
  inputs.
- **A replay that scores written expectations measures paper.** The pre-code replays asked whether an expectation
  covered each known bug (59%). Live, the tests written from those expectations each drove one path, and one passed
  only because it sent a field the real button never sends. A replay counts only if it builds the code and a review
  sweeps the result.
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
- **The grouping step named no shared cause where one existed.** In a blind rebuild, three findings across two rounds
  were one fact (is the item still for sale when a queued message is sent), answered from a side effect instead of
  the stored status. Round 1's grouper named no shared cause, so each send path was patched on its own and the next
  round found the next path.
