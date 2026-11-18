<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# History: the review loop

Why `/operate`, `/post-op` and the `consensus-review` workflow say what they say. This file is not loaded every
session. If it and a rule disagree, the rule wins.

## /operate

- **Reviewers confirm; they don't repair.** Zero-context reviewers kept finding defects in diffs written with full
  context: a comparison whose two sides normalized a value differently, a raw value stored and hashed while its
  normalized form decided, a request field silently stripped by a validator that drops undeclared fields, a second
  screen that used the same component and needed the same fix. Every one was visible on the surface of the diff, and
  reading it once would have caught it. The owner rejected every remedy that did less work (defer, review less, drop
  findings): the fix is doing the work correctly the first time. So nothing in operate reduces a gate.
- **Peer review became optional, which raised the stakes here.** Once the independent reviewers became the owner's
  call per ticket, operate and post-op became the only passes over most diffs. A defect not caught here ships.
- **Enumerate the space.** Reviewers handed back one shape of a defect class at a time, each costing a round. The
  classes were derivable up front: every syntactic form of a construct a matcher must recognize, every producer of
  a verdict a guard reads (readers can't show who forgot to write it), every exit from a cleanup block, every effect
  that reads a piece of UI state and the order they flush in.
- **Read the sibling first.** A scanner that didn't skip string literals sat forty lines below three sibling
  scanners that did. The correct pattern was already in the file.
- **Simplest design, stored fact over inference.** Code that reconstructed a state from several columns, timestamps
  or string patterns broke in every case nobody listed, and every review round found one more. Storing the fact
  where it was known, and reading it back, ended those spirals. The `Design:` line makes the choice visible.
- **Contract → tests before code.** Tests written after the code tend to be shaped to pass it. Locking the input,
  expected result and named bad behavior before production edits keeps them honest. A real change to them is a
  contract amendment, so it is visible.
- **Execute every helper as it is written.** A regex with an escaped interpolation could never match, so a rule
  shipped as dead text. A pattern that never matches looks exactly like one that found nothing.
- **Anchor structurally.** Whole-file scans were satisfied by the wrong occurrence, and fixed character windows broke
  on innocent edits and admitted a code line as "the comment".
- **Bound scans and measure them.** An unbounded quantifier on a keystroke path took seconds on a 20,000-character
  input. Reasoning about it had said it was fine.
- **Counterfactual setup reproduces the test.** A disposable worktree starts at `HEAD`, without the uncommitted
  change. Counterfactuals run there without copying the changed files in "proved" things about a different program.
  A mutation that left an unbalanced brace made a detector fail closed on the syntax error, not on the behavior.
- **No stash for the red half.** After `git add -N`, a stash can fail or lose track of new files. A disposable
  worktree can't damage the active checkout.
- **Never log and continue.** A handler that logged a data-layer error and returned success with missing fields
  was worse than a 500: the client couldn't tell anything had gone wrong.
- **Simplify pass and self-review record.** Fix rounds produced patch on patch. The record makes the line-by-line
  read, the design question and the red-team probes a written artifact. Keying it to a diff fingerprint means a fix
  batch that skipped the pass is caught mechanically, not by memory.
- **Integration and consumer contract lens.** A field renamed on the server rendered nothing in a client that read
  it by key, with no error. An external field taken from memory was a silent `undefined`. Hence: every consumer
  checked, every external field confirmed against a real payload or docs seen in the session.

## /post-op

- **The gates are static.** A green post-op once stood for "validated" while nothing had run the changed code. The
  report says so explicitly, and runtime proof belongs to `/verify`.
- **Small is never a skip condition.** A mechanical many-site sweep of a live path skipped the gates as "trivial".
  It put a variable inside its own initializer. The syntax check passed it, the suite never ran that handler, and a
  production feature was down for hours. The gates were the only thing that would have caught it.
- **Per-row contract audit.** A report line like "6/6 rows × 4" can be typed without doing the work. One line per
  row, with the input, observable, mutation and result, can't.
- **Fetch first.** A stale local base made the review and the hash span commits other tickets had already merged.
- **Code review as the final gate.** On multi-file tickets, every review run found at least one real defect a green
  post-op had missed, such as one tenant seeing another's records, an admin preview returning 500, and a re-routed
  request dropping out of deadline alerts.
- **Consensus voting.** A single reviewer's findings needed a full manual check each. Three lenses plus two
  refuting verifiers per finding (a third on a split) make each disposition a 2-of-3 decision, and cut false
  positives before they cost a fix.
- **Run by path, never by name.** A workflow name resolves to the copy loaded when the session started. A ticket
  that edited the workflow, or an old session, ran a stale version.
- **`high`, never `ultra`, never blank.** `ultra` is the owner's manual cloud review. A blank level reuses whatever
  level was chosen last.
- **Save and restore the upstream.** The fallback review diffs against the branch upstream. Overwriting a pushed
  branch's upstream for good made `git status` and `git pull` act on the main branch. A session can die between the
  switch and the restore, so the old value is saved to a file first, the next run repairs from it, and the file is
  marked `restored` rather than removed.
- **A cap, not an owner gate per round (superseded in 1.8.0).** Every fix is new code, so a reviewer always finds
  something. An uncapped, owner-gated loop ran 12–20 rounds per ticket and needed the owner at each one. The cap
  (three, three more after one redesign, one owner-granted) gave the loop a stopping condition other than the
  owner. It also let a ticket stop with defects left. See "Quality first" below.
- **Severity bar.** Without it, style notes and theoretical edge cases each bought another round. Classing by what a
  defect does to users or data, not by the size of the fix, keeps the must-fix set honest.
- **Threat-model line.** Guards, checkers, parsers and sanitizers ran four or more rounds on inputs nobody would
  send. One line on what the change defends against lets verifiers mark those `noted`.
- **Redesign rule.** Patching the same mechanism round after round meant the design was wrong. The triggers catch
  that, and the redesign gets one fresh count, once.
- **Open items on one tracker, one writer.** Noted findings written only on their own ticket were lost when it
  closed. A ticket per finding buried the backlog. One comment per closed ticket on a standing tracker, written by
  the closing step alone, keeps them findable and never duplicated.
- **`Owner action:` line.** Reports used to end with chores and already-tracked gates listed as owner tasks. The
  line names only the one decision the owner must make now, or `none`.
- **Reports, doesn't ask.** Post-op kept ending with "shall I…?" questions that stalled unattended runs. It states
  readiness and stops. The owner decides what happens next.
- **Scope drift and auto-fix vs flag.** These came from a retired review command. Checking requested against
  delivered catches both extra changes and missed requirements. Applying the mechanical fixes directly while
  verifying everything else stops trivial items from turning into review findings.
- **Lessons learned.** It was once numbered like the gates, which clashed with Owner-Kept Gate G6, so it is now just
  "Lessons learned". Lessons live in a project file (`docs/agent/lessons.md`), grouped by theme, because per-session
  memory files multiplied into a long list nobody walked.

## consensus-review.js

- **Constants are fixed** (owner decision): 3 lens reviewers, 2 verifiers plus 1 tie-breaker, quorum 2, at most 10
  findings per reviewer, at least 2 of 3 reviewers returning.
- **Dedup merges only exact twins** (same file, line and class, from different lenses), so every vote is about one
  claim.
- **`REPEATABLE` matches by leading word**, so post-op's disposition words must stay exactly `rejected`, `noted`,
  `nit`, `own ticket` and `already decided`.
- **Reviewers get the decided list (1.8.0).** Only the verifiers used to see earlier decisions, so reviewers raised
  the same decided items every round, and the verifiers spent votes marking them as repeats.
- **`origin` is a vote like class (1.8.0).** It decides whether a below-bar defect is fixed (the ticket's own code)
  or noted (pre-existing), so it has to be agreed, not guessed by one agent.

## Quality first (1.8.0)

The owner's diagnosis was that the agent writes defective code and the loop then spirals trying to fix it. A
root-cause study of four multi-round tickets (19 rounds, 132 findings, every finding classified by an independent
agent) found:
- **Real defects: 76.** 67% were in the first draft, and 33% were introduced by an earlier round's fix. In late
  rounds, the fix-introduced ones dominated: some tickets' last two rounds found only bugs that earlier fixes added.
- **41% of all findings were not defects,** mostly the same already-decided items raised again every round.
- **About half the real defects were one failure:** a value or behaviour changed without listing everything that
  reads it, writes it, or already does the same job with its own guards. Notes in memory ("name the sibling",
  "store the fact") were already there and the bugs recurred. A note does not prevent a bug; a step that must
  produce checked written output does.
- **Every ticket had one design that kept the same fact in two places**, or stored two independent facts as one.
  Each fix broke the next thing until the design was rebuilt.
- **Some defects started in the plan:** a contract row contradicting a decision, a state whose lifecycle was never
  settled, an engineering default on a safety path applied without asking.
- **Process slips:** fixes applied after the last round that no reviewer read, and reviewers never told what had
  already been decided.

What changed, and why:
- **Triage plan self-check** (state homes, contradiction check, lifecycle check, safety defaults) addresses defects
  that start before code.
- **The dependency inventory** (`inventory.json`, checked by `check-record.py`) addresses the missed reader, writer
  and sibling, the largest root cause. It has to exist before the first production edit, and every fix batch adds
  its own.
- **The spiral rule fires at the second finding in one area**, not after must-fix findings in two rounds. Round 3
  finding the ticket's own defects also fires it. The assessment comes from the owner's standing "pause and
  reassess" prompt (origins, simplest approach, state, self-check, classification in code, recommendation). The owner
  decides, because patching without that decision was what spiralled.
- **No `capped` end state.** The cap ended tickets with known defects and with fixes that shipped unread. The ticket
  now ends clean, or the owner explicitly accepts named defects.
- **Origin over severity for the ticket's own code.** Below-bar defects in code the ticket wrote went to the tracker
  and were never fixed. Only pre-existing defects are filed now; nits are not filed at all.
- **Hand-built classifiers.** Word lists and pattern checks that judge language grew by one check per round. The
  design step and the spiral assessment now ask whether a stored field or a classifier replaces them. The owner's
  order is by cost: a dedicated classification model (one that returns probabilities over fixed choices) costs a
  small fraction of a general model, and a general model costs less than hand-written checks that every round
  extends.

- **Fill-in forms, not formatted notes (1.8.1).** The first records were Markdown tables that the checker parsed.
  The same note can be written in many layouts (bold labels, bullets, different header wording), and the checker
  had to guess which ones counted. A sibling implementation of the same idea found eight checker bugs in two review
  rounds, each one a complete note refused as "missing". As JSON, each box is either filled or not, so there is
  nothing to guess. `--show` prints the readable copy for the ticket, so the JSON stays the one home.
- **A targeted fix at a spiral stop is still reviewed (1.8.1).** An owner answer of "targeted fix" at round 3 left
  the fix's review round past the limit, so the next step escalated again. The answer now counts as the
  owner-granted round.

How to tell it worked: every round record carries an `Origins:` line. Over the next tickets, compare with the
study's baseline (about 13 first-draft and 6 fix-introduced defects per ticket, 41% not-a-defect findings, about
4.75 rounds per ticket). The targets: first-draft defects well under half, fix-introduced defects at 0–1, noise under
15%, and 1–2 rounds.
