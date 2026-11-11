---
description: Implement a triaged ticket. Contract first, tests before code, then a self-review record before /post-op.
argument-hint: "[ticket]"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# Operate

Invoked with: `/operate [ticket]`. With no ticket, take the key from the branch name.

**Record check.** First run `python3 .claude/hooks/check-record.py --start operate --ticket <ticket>`. The last step runs `--kind operate` the same way, and a Stop hook reminds Claude once if the record is still missing. If the command stops early on purpose (BLOCKED, nothing to do), run `--cancel operate` the same way instead. Codex runs these steps too.

The middle step of **`/triage` → `/operate` → `/post-op`** (then the optional `/peer-review`, then `/ship`). It is a
discipline to follow, not advice to weigh.

**Reviewers confirm the work; they don't repair it.** A defect a zero-context reviewer finds was visible on the
surface of a diff written with full context. Each one costs a fix round, which is new unreviewed code. Peer review
is optional, so on most tickets this command and `/post-op` are the only checks. **Nothing here reduces a gate**: it
is the work that makes the gates pass first time.

---

## Phase 1: Before you write a line

**1. Load the contract: it is the definition of done.** Read `.claude/state/<ticket>/triage.md` first (the exact
copy; trackers mangle symbols), then ticket op **get** `<ticket>` (comments and links included) for anything later.
- Every row must end true, and every listed regression must stay protected.
- **No contract:** say so, and write the rows before any code.
- The independent vectors come from `/peer-review test-contract <ticket>`, run by `/triage`. A row whose vector reads
  `not run` still needs its hostile case and counterfactual: they are what the test is built from.
- A verified must-fix finding (S1–S4, post-op Step 1.5 round rule 2) that shares the ticket's execution path,
  invariant, safety outcome or acceptance criterion joins the contract and is fixed here. It is never recorded away
  as "outside scope". Only a genuinely independent capability is recorded instead of built.

**2. Enumerate the space, not the example.** The defect class is larger than the ticket's instances, and you can
derive it now from the language, the schema or the call graph.

| Building | Enumerate |
|---|---|
| a guard, gate or validation | every code path that reaches the same downstream function. One guarded path and three unguarded is a bypass |
| a comparison of two values | every site that normalizes, formats or canonicalizes either side |
| a value that gets stored | every sink: database write, hash, external send, log |
| a guard reading a request field | the route's input schema. A validator that strips undeclared fields deletes what the schema doesn't declare |
| a guard reading a stored verdict | every producer that writes it. Readers can't tell you who forgot to write it |
| a matcher, detector or pin | every syntactic form the language allows for that construct |
| a cleanup or `finally` | every exit, including those where an external party still holds the resource |
| a shared component or helper | every consumer, found by search |
| a list, enum or constant | every home of the fact: type, runtime constant, validator schema, database constraint, each client, tests, docs |
| a rename or sweep | every consumer and every home, not just the producer |
| a UI state change | every effect that reads that state, and the order they flush in |
| new branch logic on a source field | the null, empty, absent and zero-rows cases, with nullability confirmed in the schema source |

Write the list down. It becomes the probe matrix in Phase 3. `docs/agent/source-layout.md` says where the schema,
clients and consumer surfaces live. `docs/agent/sibling-paths.md` lists known pairs that must change together.

**3. Read the sibling first.** The repo usually does this already somewhere. Open that code before writing yours,
and copy the pattern.

**4. Walk the recorded lessons.** Search `docs/agent/lessons.md` and `docs/agent/defect-classes.md` for the
mechanism you are about to touch (idempotency, retry, regex, effect ordering, migration, mocks, webhooks…). Open each
hit and check the plan against it now, while it costs a decision rather than a rewrite.

**5. Read the rules layer for the area**: `.claude/rules/`, including the rules packs installed.

**6. Pick the simplest design that meets the contract, and write down why.** Ask: *is this code working out a fact
that could simply be stored?* Code that reconstructs a state from several fields, timestamps or string patterns
breaks in every case nobody listed. If the fact is known when something is written, store it there and read it back.

| Instead of | Prefer |
|---|---|
| inferring a status from several columns, joins or timestamps | a status or flag the writer sets, then a plain check |
| matching text or patterns to recover what a record is | a typed field written when the record is created |
| the same rule computed in the API and in each client | one stored value, or one function, that all of them read |
| a special-case branch for each new shape | one data shape with no special cases |

- A new nullable column, or one with a default, is the lower-risk path (the additive schema rule in
  `CLAUDE.kit.md`). It goes in the contract as a row: who writes it, the backfill, who reads it.
- Changing or removing an existing column, an API contract, auth, or anything in `<CRITICAL_SYSTEMS>` is a Critical
  System change. It needs no owner approval, but the Critical Systems checks in `CLAUDE.kit.md` apply.
- Anything that hits an Owner-Kept Gate still needs the owner.

Record one line for the self-review record (Phase 3, step 8):
`Design: <shape chosen>; simpler alternative considered: <one>, rejected because <reason>`.

---

## Phase 1.5: Make the contract executable

Before changing production source, turn every contract row's hostile case, and its pre-code vector where one
exists, into a direct behavioral test. Prefer a callable seam with a real input and an observable return, error,
state or response. A source-text scan is allowed only for a structural policy (an import boundary, a rule file)
that can't be driven at runtime. It never stands in for the behavior the policy protects.

For each row, record the test name, the exact input, the expected result, the named bad behavior, and one of:
- **Existing defect:** the new test fails on the baseline for the named bad behavior.
- **New behavior:** the test is red because the behavior doesn't exist yet. Demonstrate the named bad behavior in a
  disposable copy, never the active checkout.
- **Seam extraction:** the behavior is trapped behind a script or I/O. First extract a behavior-preserving callable
  seam, prove it against existing behavior, then write the contract test.

**No test runner yet** (a pack's test-framework fact is `none`, or no `<TEST_COMMANDS>` line runs tests): write each
contract test as a plain Node or TypeScript script that exits non-zero on failure, and add the line that runs it to
`<TEST_COMMANDS>` in the same change. Use `node:test` and `node:assert` when the runtime has them. Adding a runner
is its own change, never part of this ticket. If a row can't be driven that way, stop: record it
`BLOCKED — no test runner` in the hand-off and name the owner action "add a test runner".

The input, expected result and named bad behavior are locked for the batch. You may add fixtures and plumbing. You
may not weaken them after a production edit to make the suite green. A real change is a contract amendment through
`/triage`, with evidence.

---

## Phase 2: While you write

- **Execute every helper the moment you write it**: one positive and one negative input in a scratch script, before
  it has a caller. A pattern that can never match looks exactly like a pattern that found nothing.
- **Parse and normalize at the boundary**, in one small testable helper. Apply the same guard, normalization and
  error policy at every equivalent site the sibling sweep found. Don't scatter slightly different checks.
- **Apply the treatment at every site, not most.** The site you skipped is the bug. Search for the others and change
  them in the same pass.
- **Anchor structurally, never by distance or by file.** Slice to the function body, the object literal or the
  contiguous block. A whole-file search is satisfied by the wrong occurrence. A fixed character window breaks on an
  innocent edit.
- **Fail closed, and know which input proves it.** A branch that can't decide must refuse. Write the malformed input
  that exercises it while you write the guard. An idempotency read that treats a database error as "nothing sent
  yet" double-sends.
- **Never log and continue in a request handler.** Check every data-layer error and throw. A success response with
  missing fields is worse than a 500, because the client can't tell.
- **Bound every scan over operator-controlled or arbitrary input**, and measure it. Don't reason about it.
- **Keep statements inside their block.** A stray assertion after a closing brace runs at module load, not as a
  named test.
- **Keep test doubles honest.** Reset mock return values and queued responses between tests.

Packs may add checks here: see the section for this command in each installed `.claude/packs/*.md`.

---

## Phase 3: Before any reviewer sees it

This is the phase that gets skipped. It is not optional and it is not slow.

**1. Read the diff, line by line.** Run these from the repo root as separate commands, written as shown (no `$(...)`,
pipes or redirects, so each matches an allow rule in `.claude/settings.json`):

```bash
git fetch origin <MAIN_BRANCH>
git status --short                         # then: git add -N -- <each intended new file>
git merge-base origin/<MAIN_BRANCH> HEAD   # prints <base>
git diff <base>                            # the branch diff: every file, committed or not
```

For a fix batch, compare against the diff the last record saved. Write the current diff to the scratch directory
(the session scratch dir, else `.claude/state/tmp/`) with `git diff --output=<scratch>/now.diff <base>`, then run
`diff .claude/state/<ticket>/self-review.diff <scratch>/now.diff`.

Read it as if someone else wrote it and you are paid to find the error: the characters that are there, not what you
meant.

**2. Discharge the contract and the Phase 1 probe matrix**, not one a reviewer suggests later. Fill each row's
`Discharge` cell in `.claude/state/<ticket>/triage.md`:

| Contract row | Exact proof command or test | Result | Runtime path exercised | Counterfactual and result |
|---|---|---|---|---|

A similarly named test is not a discharge.

**3. Show that each probe fails for the right reason.** Run its named bad behavior in a disposable worktree or copy,
never the active checkout, and show that this exact test turns red. A red test proves something fired, not that
your change fired. Read the failure message.
- A worktree starts at `HEAD`, not at your uncommitted diff. Copy every changed and untracked production and test
  file the counterfactual needs into it.
- Use a stubbed or offline environment, never a production env file.
- A mutation must be valid source and change a whole balanced unit (the entire `if` block, never one line of a
  multi-line construct). Syntax-check the mutated file (`<SYNTAX_CHECK_COMMAND>` or `<TYPECHECK_COMMAND>`) first.
- A red test against an incomplete or differently configured copy is not a counterfactual.

**4. Prove every regression test fails against the pre-fix code.** Revert the fix in the disposable worktree, watch
the test go red there, and watch it go green with the fix. Don't stash in the active checkout: a stash fails or
loses track of files once `git add -N` is in play. A test that always passes proves nothing.

**5. Run the suites exactly as written.** Run each `<TEST_COMMANDS>` line for every package the diff touches. Never
a subset, never a substitute.

**6. Type-check and build.** Run `<TYPECHECK_COMMAND>` and `<BUILD_COMMAND>` unless `none`, and
`<SYNTAX_CHECK_COMMAND>` on each changed file of code without a compiler. A green test run doesn't mean the code
compiles. Also re-run every existing regression test for the invariants your edits touch: a green full suite doesn't
show that an old protection is still exercised.

**7. Simplify without losing anything.** Go through the diff function by function. Could each part be shorter,
merged with an existing helper, or deleted, without dropping a contract row or a passing test? Re-check the design
line: now that the code exists, would a stored value (Phase 1 step 6) be simpler? Simplify now, then re-run steps
4–6. Less code is less for a reviewer to find fault with.

**8. Self-red-team, then write the self-review record.** Run the self-red-team probes from `post-op.md` "Before
starting" and the lenses below. Then:

1. Save the diff this record covers: `git diff --output=.claude/state/<ticket>/self-review.diff <base>`.
2. Take the fingerprint: `node .claude/scripts/kit-tools.mjs fingerprint --base origin/<MAIN_BRANCH>`. If it exits
   non-zero, fix the reason it prints (an untracked file: `git add -N` it or gitignore it). If Node is unavailable,
   say so and stop: there is no hand-run fallback.
3. Append this block to `.claude/state/<ticket>/self-review.md`, and post it with ticket op **comment** `<ticket>`:

```
Self-review: <ticket>
Fingerprint: <h>
Covers: whole branch | fix batch since <previous fingerprint>
Diff read: <files> · <lines> lines, read line by line against origin/<MAIN_BRANCH>
Design: <shape chosen>; simpler alternative considered: <one>, rejected because <reason>
Edge cases checked: <null/empty/absent, malformed, concurrent, each sibling path…>
Bugs found and fixed by me: <list, or "none">
Simplifications made: <list, or "none: reason">
Red-team probes: <each probe and lens, with what it found>
```

The last `Fingerprint:` line in the file is the current record. `/post-op` won't start the code review (Step 1.5)
unless it equals the current fingerprint.

4. Run `python3 .claude/hooks/check-record.py --kind operate --ticket <ticket>`. Fix the record and re-run until it
   exits 0.

**Review-ready checklist.** Don't hand code to `/post-op` until:
1. every contract row has a behavioral proof on the exact runtime path, and its named bad behavior demonstrably
   fails it;
2. the whole diff has been read line by line;
3. the affected regression tests and the full suites are green, and type-check, build and syntax checks pass;
4. every mutation ran in a disposable copy, never the active checkout;
5. the self-review record is written for the current fingerprint.

**Every fix batch comes back through this phase.** Fixes from a review round, a gate or `/peer-review` are new code.
Before the next round, do steps 1, 7 and 8 on the **fix delta**: read it line by line, simplify it, red-team it,
write a new record. Then ask again: *am I fixing the same mechanism a second time?* If yes, stop patching and follow
the redesign rule (post-op Step 1.5 round rule 10).

Only now hand it to `/post-op`. Its own gates run before any external reviewer sees the code.

---

## The reviewers' lenses, turned on yourself

Work these before `/post-op`. A finding here costs nothing; from a reviewer it costs a fix round.

1. **Integration and consumer contract.** Every field the diff adds, renames or removes in a response, event or
   message: does each consumer surface in `docs/agent/source-layout.md` read it by key name? A missing field fails
   silently. Every external field the diff reads must be confirmed against a real payload, or against live docs seen
   in this session, never from memory. A wrong field name is a silent `undefined`.
2. **Sibling path.** List every path that reaches the changed downstream function. Does each carry the same guard?
   This lens finds the most, and you can do it entirely alone.
3. **Fail open.** Does any new `catch` swallow where it must throw? Does every idempotency read check its own error?
   Is every post-commit cleanup wrapped so it can't fail an operation that already committed?
4. **Mock fidelity.** Does each test double match the real module's exports and return shapes?
5. **Schema.** Does every table and column the diff names exist, with that nullability, in the schema source?
6. **Race and double-fire.** Trace each writer/reader pair and each interleaving: read-then-write windows, webhook
   replays, concurrent submissions. Name the ones you accept as bounded, and why.
7. **Critical domain.** Does the diff add or move a path into `<CRITICAL_DOMAIN>` or one of `<CRITICAL_SYSTEMS>`
   without the guard that path needs?

Packs may add lenses here: see the section for this command in each installed `.claude/packs/*.md`.

**Defect classes.** Check the diff against every class in `docs/agent/defect-classes.md` that applies.

---

## Rules

- **Reviewers confirm; they don't repair.** A major finding from a zero-context reviewer is a defect you could have
  seen. Treat it as a signal about the pass that produced it, not just as a task.
- **Never hand over code you haven't read back.** Writing it is not reading it.
- **Never ship a pattern you haven't watched match something.**
- **Never accept a red test without reading why it is red**, or a green one without knowing what would turn it red.
- **Must-fix findings (S1–S4) inside the definition of done are fixed here.** Findings below the bar are noted
  (post-op Step 1.5 round rule 2). A verified must-fix defect on the ticket's execution path is always inside it:
  calling it "pre-existing", or reading the ticket narrowly, never makes it safe to leave. Only a genuinely
  independent capability gets its own ticket (post-op Step 1.5, disposition "own ticket").
- **Slow is the point.** Every shortcut skipped here was tried, and it produced a fix round, which is slower.

Why these rules exist: `docs/workflow/history/review-loop.md` (not loaded by default; where it disagrees with a rule
here, the rule wins).
