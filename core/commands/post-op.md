---
description: Run your own gates on the finished work (self-red-team, inventory audit, contract audit, eight gates, code-review rounds until clean, lessons) and report whether it is ready to ship.
argument-hint: "[ticket]"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# Post-op

Invoked with: `/post-op [ticket]`. With no ticket, take the key from the branch name. Post-op reads the branch's
diff against `origin/<MAIN_BRANCH>`, committed or not.

**Record check.** First run `python3 .claude/hooks/check-record.py --start post-op --ticket <ticket>`. The last step runs `--kind post-op` the same way, and a Stop hook reminds Claude once if the record is still missing. If the command stops early on purpose (BLOCKED, nothing to do), run `--cancel post-op` the same way instead. Codex runs these steps too.

## Purpose

Post-op is your own check of your own work: the self-red-team, the contract audit, eight gates, the code-review
rounds (Step 1.5) and Lessons learned. It ends with a report that answers one question: **is this ready to ship?**

- **Post-op reports. It doesn't hand off, recommend a next step, or ask permission.** It asks the owner only a
  needs-owner finding or an escalation (round rule 6).
- **B-Team and Codex reviews are not part of post-op.** They run in the optional `/peer-review`, after post-op, when
  the owner chooses: `/triage` → `/operate` → `/post-op` → `/peer-review` (optional) → `/ship`. Never launch them
  here, and never report their absence as a gap.
- **Verified defects converge on this ticket.** Every real defect in code this ticket wrote, of any class, and a
  must-fix defect (round rule 2) on this ticket's execution path, invariant, safety outcome or contract are fixed
  here: regression proof, root-cause and sibling repair, then the gates again. "Pre-existing" is attribution, not
  permission. A separate ticket is only for an independent capability. The ticket ends clean or goes to the owner:
  it never ends with known defects of its own (round rules 3 and 6).
- **The gates are static and check conventions.** None runs the changed code against real services, so a green
  post-op is not "validated": that is `/verify`, run by `/ship` before merge. Nor do they attack the diff: the
  self-red-team does. A diff can pass every gate and still hold a dead path, impossible user-facing copy, or a race.

---

## Before starting

```bash
git fetch origin <MAIN_BRANCH>
git log origin/<MAIN_BRANCH>..HEAD --oneline
git diff origin/<MAIN_BRANCH>...HEAD --stat
git status --short
```

- Fetch first: a stale base makes the review and the fingerprint span other tickets' merged commits.
- Nothing ahead and a clean tree: stop with "No changes ahead of origin/<MAIN_BRANCH>. Nothing to check."
- **Include every intended new file.** `git diff` omits untracked files. Run `git add -N -- <path>` on each intended
  new path. A new secret-bearing file is a Security blocker, not a reason to hide it.
- Run post-op **before committing** when possible, so fixes land in the same commit.
- Load the contract, with the discharge `/operate` wrote, from `.claude/state/<ticket>/triage.md`. No contract: say
  so in the report; don't invent one.

### Self-red-team (mandatory on any executable change)

The tail of `/operate`: if that ran, confirm its record. Attack your diff as a hostile zero-context reviewer would,
and record what each probe covered, so a skip is visible.

- **Scope drift.** Compare what was requested (contract, ticket, branch name) with what the diff delivers:
  ```
  Scope: CLEAN | DRIFT | MISSING
  Intent:    <one line: what was requested>
  Delivered: <one line: what the diff does>
  <DRIFT: each out-of-scope file or change · MISSING: each unaddressed requirement>
  ```
  Remove a drift change, or justify it in one line. A missing requirement that is a contract row is fixed here.
- **Match-set delta** (pattern, matcher or classifier changes). Probe the full delta against `origin/<MAIN_BRANCH>`
  in both directions, with the input shapes production really sends: accents, curly apostrophes, case, whitespace
  and newline splits, and the number or identifier formats the domain uses. A bug's accidental coverage is live
  behavior. List what the old version matched that the new one won't, and the reverse.
- **Recorded-lessons walk.** Check the diff against each relevant entry in `docs/agent/lessons.md` and
  `docs/agent/defect-classes.md`, as a checklist, not from memory.
- **Multi-writer and race.** Trace every writer/reader pair the diff touches, and each interleaving: read-then-write
  windows, mid-flight events, webhook replays, concurrent submissions. Name the ones accepted as bounded, and why.
- **Inventory audit.** Open `.claude/state/<ticket>/inventory.json` (`/operate` Phase 1 step 2) and `state_homes`
  in `plan-check.json` (triage Step 4.8), and walk the final diff against them:
  - every value the diff changes has a `values` entry, and its readers and writers were re-walked against this
    diff;
  - every new behaviour has a `siblings` entry, with every guard its sibling has, copied or not applicable with a
    reason;
  - every fix batch has its `Fix batch <n>` section;
  - every stored state matches its one home.

  A missing or stale entry fails the self-red-team. The work goes back to `/operate` Phase 1 step 2 for that row,
  never on to review.
- **Deliberate markers.** Every `Deliberate (decided R<n>-<k>)` comment in the diff names an id in
  `.claude/state/<ticket>/review-rounds.md`, and the code under it still matches the recorded reason.

Sort each self-red-team finding into one of two kinds:
- **Auto-fix:** mechanical, unambiguous and low-risk, such as a missing or wrongly formatted log line, an unmasked
  identifier in a log, a missing import, or a copy-rule wrap. Apply it and note `[AUTO-FIXED] <file:line> — <what>`.
- **Flag:** everything else, such as logic gaps, edge cases, security, or design trade-offs. Verify it, classify it
  by the severity bar (round rule 2), and dispose of it as Step 1.5 does. A real defect is fixed now.

### Contract audit (after the self-red-team)

Make four checks for every executable contract row, and record each one:
1. the row's vector or hostile case **exists** and still fits the final code;
2. the direct test feeds **that exact input** into the named behavior;
3. the **expected observable result** is asserted;
4. the test **demonstrably catches the named bad behavior**: the mutation was run in a disposable copy or worktree,
   never the active tree, and the test went red.

Record one line per row (format in Step 2), never a total: **a total is a claim, not evidence.** A source scan or
an adjacent test is a substitution, not a proof. A test that still passes with the guard deleted doesn't prove the
guard, and a green test whose bad behavior was never caught leaves the row uncovered.

---

## Step 1: The eight gates

Work through each gate **in order**, following its command file in full. Record its verdict before the next. A gate
that finds issues is completed and recorded, the issues are fixed, and the gate is re-run. A gate skips only when
its own skip condition holds. **"The change is small, low-risk or well-tested" is never a skip condition.**

| # | Gate | Follow | Skip only when the diff… | Statuses |
|---|---|---|---|---|
| 1 | Observability | `.claude/commands/observability.md` | never skips | Pass / Issues found |
| 2 | Security | `.claude/commands/security.md` | never skips | Pass / Issues found |
| 3 | API Contract | `.claude/commands/api-contract.md` | has no API change (API paths per `docs/agent/source-layout.md`) and no external-integration call | Pass / Issues found / `⏭️ Skipped — no API changes` |
| 4 | Migration Guard | `.claude/commands/guard.md`, plus the overlays installed packs add | has no schema change (schema locations per `docs/agent/source-layout.md`) | Pass / Issues found / `⏭️ Skipped — no schema change` |
| 5 | Compliance | `.claude/commands/compliance.md` | changes no user-facing copy | Pass / Issues found / `⏭️ Skipped — no copy changes` |
| 6 | Docs Update | `.claude/commands/docs-update.md` | affects no doc in `docs/agent/docs-map.md` | Pass / Updated / Issues found / `⏭️ Skipped — no affected docs` |
| 7 | Test | `.claude/commands/test.md`: every `<TEST_COMMANDS>` line exactly, plus type-check, build and syntax checks | never skips | Pass / Issues found, with suite counts |
| 8 | Mock Fidelity | the checks below | adds or changes no test double and no test file | Pass / Issues found / `⏭️ Skipped — no test changes` |

Record each as **Status** plus a one-line **Summary**, such as "3 endpoints checked, all log start, success and
failure" or "missing failure log in `<function>`".

**Mock Fidelity**, for each test double the diff adds or changes:
- **Check A, shape:** read the real module. Flag a double that declares exports the real module lacks, or omits
  exports the code under test calls.
- **Check C, return values:** does each mocked function return the shape the real one returns? A double that returns
  `{ data: [] }` where the real call returns `{ data: [], count: null }` hides a mishandled count.

Packs may add checks here: see the section for this command in each installed `.claude/packs/*.md`.

---

## Step 1.5: Code review rounds (the final gate)

Runs after gates 1–8 pass, on the final code. Each round is the `consensus-review` workflow: three reviewers with
different lenses, and only findings that survive adversarial verification by vote.

**Precondition: the self-review record.** Compare `node .claude/scripts/kit-tools.mjs fingerprint --base
origin/<MAIN_BRANCH>` with the last `Fingerprint:` line in `.claude/state/<ticket>/self-review.md`.
- **Equal:** start the round. (Committing or merging the base in doesn't change it; a code change does.)
- **Different:** refuse. A fix batch skipped the pass: run `/operate` Phase 3 steps 1, 7 and 8 on it, write a new
  record, compare again.
- **No record:** do that pass and write it first. A reviewer is a second reader, not the first.
- **Empty diff:** the branch changes only docs. The row is `⏭️ Skipped — no reviewable change`, which passes.
- **Untracked files:** `git add -N` the intended ones (or gitignore them) and re-run.
- **Node unavailable:** say so and stop. There is no hand-run fallback.

**How to run a round:**
1. **Save the branch diff it reviews**, the merge-base diff with the working tree (`<base>` as in `/operate` Phase 3
   step 1): `git diff --output=.claude/state/<ticket>/round-<N>.diff <base>`.
2. **Run the workflow by path.** Call the Workflow tool with
   `scriptPath: "<repo root>/.claude/workflows/consensus-review.js"`, where `<repo root>` is the output of
   `git rev-parse --show-toplevel`. Never call it by `name`: a name resolves to the copy loaded when the session
   started, which is stale if the workflow changed since. Pass `args`:
   ```json
   { "ticket": "<ticket>", "round": N, "base": "origin/<MAIN_BRANCH>",
     "criticalDomain": "<CRITICAL_DOMAIN>", "consumerSurfaces": "<consumer surfaces from docs/agent/source-layout.md>",
     "contract": "<contract rows with their classes>", "threatModel": "<the contract's threat-model line>",
     "prior": [{ "finding": "...", "disposition": "..." }], "savedDiff": "<previous round's saved diff, rounds 2+>",
     "scratchDir": "<session scratch dir, else .claude/state/tmp>" }
   ```
   `prior` is the **decided list**: every earlier finding, as `"R<n>-<k>: <finding>"`, with its disposition, plus
   the standing items. Reviewers and verifiers both get it, so an already-decided item comes back only with new
   evidence. Running the workflow is part of this command and needs no separate opt-in.
3. **Fallback, when the Workflow tool is unavailable:** run `/code-review high` (Skill `code-review`, args `high`).
   It is built into Claude Code, not shipped by the kit; if this session doesn't list it, the round didn't run
   (`⚠️ Not run`). Codex has neither, so it skips Step 1.5 and records `⏭️ Skipped — Codex`. Never `ultra` (the
   owner's manual cloud review), never without a level (it reuses the last one). It diffs against the branch
   upstream, so point the upstream at the base, saving a pushed branch's own upstream to restore afterwards. The
   save file lets the next run repair a run killed mid-way:
   Run each step from the repo root as its own plain command; `<saved>` is the content of
   `.claude/state/<ticket>/upstream.txt`, read with your file tool.
   1. `git rev-parse --abbrev-ref --symbolic-full-name @{upstream}` prints the current upstream; an error means
      `none`.
   2. **Repair an aborted run**, only when the file exists, `<saved>` is neither `restored` nor empty, and step 1
      printed `origin/<MAIN_BRANCH>`: run `git branch --unset-upstream` if `<saved>` is `none`, else
      `git branch --set-upstream-to=<saved>`. If that fails, the saved upstream is gone: say so, restore it by hand,
      and stop. Then repeat step 1.
   3. Write step 1's output (or `none`) to `.claude/state/<ticket>/upstream.txt` with your file tool.
   4. `git branch --set-upstream-to=origin/<MAIN_BRANCH>`
   5. `git rev-parse --abbrev-ref @{upstream}` must print `origin/<MAIN_BRANCH>`.

   After the review: read `<saved>` again. If it is `none`, run `git branch --unset-upstream`; if it is a branch, run
   `git branch --set-upstream-to=<saved>`; if it is `restored` or empty, do nothing. Then write `restored` into the
   file. It is marked `restored`, never removed. Verify the fallback's findings yourself, as in step 6. The
   built-in review takes no extra instructions, so match each finding against the decided list yourself (same
   file and symbol, same claim) and mark matches `repeat` (round rule 4), then give each real finding its origin
   (round rule 2).
4. **Wait for the completion notification** before writing the report. Don't call `ReportFindings`.
5. **Check what it reviewed:** the whole branch against `origin/<MAIN_BRANCH>` (the workflow's `base`; for the
   fallback, paste the `must print` output into the row). A failed reviewer, a wrong base or `round_ran: false`
   (fewer than 2 of 3 reviewers returned) means the round didn't run: run it again. A partial review is not a round.
6. **Use the votes, then check before fixing.** `rejected`, `repeats` and `nits` were decided by 2 agreeing votes
   and need no more work. `noted` (pre-existing, below the bar) is recorded as is. `must_fix` holds every real
   defect to fix here: S1–S4, plus the ticket's own code at any class. Each finding carries its `origin`, and
   `origins` gives the round's counts (round rule 8). `redesign_signal.recommended` is round rule 10 trigger (c).
   `unverified` (verifiers died before 2 agreed): verify each yourself before the round counts. Before fixing a
   `must_fix` item, confirm the evidence at its `file:line`; disagree only with new evidence, as `rejected`.

**Every finding is a lead, not a fact.** Check it against the code and how the app really behaves. Give it an id
`R<round>-<k>`, a class and an origin (round rule 2), and one disposition, starting with its word exactly as below
(the workflow matches earlier dispositions by leading word):
- **`must-fix`**: real, with `<file:line>` evidence, and either in code this ticket wrote (origin `first-draft` or
  `fix-introduced`, any class) or a pre-existing S1–S4 defect on the ticket's path. Fix it on this ticket now, with
  no owner question, in this order: the redesign triggers first (round rule 10); the fix inventory (`/operate`,
  "Every fix batch"); a regression test that fails without the fix; the root-cause and sibling repair; `/operate`
  Phase 3 steps 1, 7 and 8 on the fix delta; gates 1–8 again. A fix that changes a state transition must match the
  `lifecycles` in `plan-check.json`. A path the plan doesn't have is a scope change, so it is `needs owner`.
- **`noted`**: real, **pre-existing** and below the bar. Don't fix it. Record it with where, effect and suggested fix
  (round rule 8). The closing step files it on the tracker (round rule 11).
- **`nit`**: no wrong behaviour (style, naming, refactor, test polish, wording, unmeasured performance). Not fixed,
  not filed: one line in the round record.
- **`own ticket`**: a genuinely independent capability, never a defect on the ticket's own path. Run ticket op
  **search** first. If an open ticket covers it, add the finding there with ticket op **comment**. Otherwise use
  ticket op **create** in the backlog with the finding and evidence (parent: the ticket's epic, if any; labels per
  `.claude/rules/ticket-ops.md`). Record the key and carry on.
- **`rejected`**: disproved, outside the threat model, or unreachable, with the evidence. When it upholds a
  deliberate design choice, write the reason at the site as a code comment:
  `Deliberate (decided R<n>-<k>): <the concern> — <why it is right> — <evidence>`. Write a reason, never "ignore
  this": a reviewer who can show the reason is wrong must still flag it. The marker covers only the concern it
  names. If the code under it changes, re-check the marker in the same change.
- **`already decided`**: an owner decision covers it. Quote where it is recorded. A process item that stays true
  until ship ("the migration isn't applied yet", "the env var isn't set") is recorded once as `already decided —
  standing until ship`, gets no code marker, and is passed to every later round.
- **`needs owner`**: a product decision code can't settle. Don't stop the round. Collect it for the one escalation
  (round rule 6). Post-op doesn't pass while one is unanswered.
- **`repeat`**: see round rule 4.

### Round rules

This section is the one definition. Other commands cite it as "round rule N".

1. **Reviewable change** means any change to the ticket's diff except code comments and plain developer docs
   (`docs/`, READMEs). Merging `origin/<MAIN_BRANCH>` in doesn't count. Source, tests, migrations, templates,
   user-facing copy, config the code reads, and the files that drive agents (`.claude/`, `CLAUDE.md`,
   `CLAUDE.kit.md`, `AGENTS.md`, `.agents/`) all count. This is not the "executable change" that decides the
   Self-red-team and Contract-audit rows.
2. **Severity bar and origin.** A verified finding has a class:
   - **S1 data integrity:** data loss or corruption, wrong or irreversible writes, cross-tenant exposure.
   - **S2 auth and security:** lock-out, privilege or access-control holes, PII in logs, leaked secrets, injection or
     unsafe input, an unverified webhook.
   - **S3 `<CRITICAL_DOMAIN>`:** a wrong result in the logic that must never be wrong here.
   - **S4 the ticket's own behaviour:** it breaks a contract row or pre-code vector, or the changed flow crashes or
     returns a wrong result on input production realistically sends.
   - **noted:** any other real wrong behaviour.
   - **nit:** no wrong behaviour at all: style, naming, refactors, test polish, wording, extra logging, unmeasured
     performance.

   Inputs outside the threat model, a deliberately hostile author and unreachable paths are not real: `rejected`.
   Classify by what the defect does to users or data, never by the size of the fix. Between S4 and noted, read the
   contract: breaking a row or vector is S4. No threat-model / out-of-scope line in the contract: write one from
   the acceptance criteria before classifying, and show it in the round record and the summary.

   It also has an **origin**: `first-draft` (a line this branch wrote), `fix-introduced` (a line an earlier round's
   fix added or changed, which is inside the fix delta) or `pre-existing` (unchanged from `origin/<MAIN_BRANCH>`).
   **Every real defect in code this ticket wrote is fixed on this ticket, whatever its class.** The S1–S4 bar
   decides only pre-existing defects: S1–S4 on the ticket's path is must-fix, and the rest is noted. A ticket's own
   bugs never go to the tracker.
3. **Rounds run until the code is clean.** The count is a checkpoint, not an exit, and it is counted per ticket,
   not per run. Continue the count from the round records (round rule 8): the state file, or the `Review round`
   comments from ticket op **get** when it is missing. Every round reviews the branch against
   `origin/<MAIN_BRANCH>` and saves the diff it reviewed.
   - Round 1 covers the whole branch.
   - Every later round (including owner-granted and post-redesign rounds) looks first at the **fix delta**: the
     previous round's saved diff against the current one, plus the functions those lines sit in. The delta holds
     every fix since, from any source, committed or not. It sets where the reviewer looks first, not what counts:
     a verified finding anywhere is classed like any other.
   - Rounds run without asking, attended or not, and never create or move branches.
   - Round 3 brings the design review (round rule 10 trigger d). One redesign allows three more rounds, and the
     owner may grant one extra round (round rule 6).
   - **The limit is reached** at three rounds with no redesign, or six after one, plus any owner-granted round.
     Reaching it with work left escalates. It never ends the work quietly, and nothing is filed away to make it
     end.
4. **Repeats.** A finding that repeats an earlier `rejected`, `noted`, `nit`, `own ticket` or `already decided`
   disposition is marked `repeat` (citing its id) and never counts as new. A finding fixed in an earlier round
   that comes back is **not** a repeat: the fix didn't hold, so it is new, and it is redesign trigger (a).
5. **A round is due** when a reviewable change landed after the last round (a must-fix, a gate fix, a
   `/peer-review` fix). Noted items, nits, rejected leads and repeats change no code, so they never make a round
   due. Re-run gates 1–8 before each round. **No change ships unreviewed:** with the limit reached, don't make the
   change. Escalate it (round rule 6).
6. **End states.** When no round is due and no assessment or redesign is in progress, take the **first** line that
   matches:
   1. **`escalate`:** a needs-owner finding is open; **or** a spiral assessment waits for the owner (round rule
      10); **or** the limit is reached and the last round found a must-fix.
   2. **`clean`:** anything else. The last round ran on the final code (round rule 7) and found no new must-fix.

   **Escalating:** send **one** message to the owner. Attended: ask in the session. Unattended: post it with
   ticket op **comment** `<ticket>` and Notify (Step 3), and pause the loop. It holds every open item: the finding
   in plain language, its evidence and origin, the proposed fix (not applied), a recommendation, and options each
   with a pro and a con. Typically:
   - **redesign as the spiral assessment proposes**, offered only while no redesign has run;
   - **one more round on the fix**, which grants exactly one round past the limit, is recorded as
     `extra_round: true`, and is offered only while none has been granted;
   - **re-scope the ticket**;
   - **ship with these named defects**: the owner accepts each defect by name.

   The answer is recorded and applied without another question. A redesign or an extra round continues the loop,
   and the end state is taken again afterwards. The only passing `escalate` is an answered **ship with these named
   defects**: the closing step files those defects (round rule 11). A round that fails or doesn't cover its branch
   is not a round: run it again.
7. **Covered** (needed for every passing status): no round is due, and the last round reviewed the current code.
   Compare its saved diff with the current diff: nothing but code comments and plain docs (round rule 1) may have
   changed, so a `Deliberate` marker added after a round keeps the code covered. There are no post-cap fixes: a
   reviewable change after the last round makes a round due, or, with the limit reached, escalates.
8. **Record each round** as one block in `.claude/state/<ticket>/review-rounds.md`, and post the same block with
   ticket op **comment** `<ticket>`, first line `Review round <n>: <ticket>` (the record marker in
   `docs/workflow/ticket-ops.md` §3; `/ship` reads it). Include:
   - the saved diff's path and fingerprint;
   - every finding with its id, class, origin and disposition;
   - an `Origins:` line (`first-draft <a> · fix-introduced <b> · pre-existing <d> · not a defect <e>`, where `e`
     counts rejected, repeats and nits). This is how a project measures whether its first drafts are improving;
   - each `noted` item with **where**, **effect** and **suggested fix** (the closing step copies them);
   - the standing items;
   - tickets created;
   - the end state;
   - any owner answer, verbatim;
   - any `redesign:` line and spiral assessment.
9. **Attended and unattended runs follow the same rules.** Only how an escalation reaches the owner differs (round
   rule 6). Plain post-op and packs that run it (ticket trains) all use rules 1–11.
10. **Patch spiral → stop and assess before any edit.** In every round from round 2 on, after verifying the
    findings and **before fixing any**, check the triggers:
    - (a) a finding shows an earlier fix didn't work: the same defect is back, or the fix is the defect;
    - (b) a **second** real finding (any class but nit) in the same area as an earlier one, in this round or an
      earlier one. "Same area" means the same mechanism, rule, inference, piece of state, or flow. An unrelated
      finding that only shares a function doesn't count;
    - (c) a reviewer or verifier recommends a redesign with a concrete simpler shape. With the fallback, the agent
      verifying the round answers `design: ok | redesign recommended — <simpler shape>`;
    - (d) round 3 or later finds a must-fix in code this ticket wrote.

    If a trigger fires, **stop editing**. Write a **spiral assessment** into `review-rounds.md`, and post it with
    ticket op **comment** (first line `Spiral assessment: <ticket>`). Cite specific findings, and say where the
    evidence is inconclusive:
    1. **Origins.** For every finding so far: first-draft, fix-introduced, or a gap in the requirements or the
       verification; an isolated defect, or a symptom of one shared design problem.
    2. **Simplest approach.** Back to the original requirements: is this approach still the simplest that meets
       them? What logic can be removed, consolidated or redesigned while keeping the behaviour existing callers
       rely on? Several findings from one cause get one fix at that level.
    3. **State.** Is the same state inferred again and again from scattered fields, logs or side effects? Would an
       explicit status in an existing record or a durable store be simpler? List the valid states, who may change
       each, and what happens on retries, failures and concurrent updates. If the state can be derived reliably
       from an existing source, say why that is simpler. Check `state_homes` in `plan-check.json`: one fact, one
       home.
    4. **Self-check.** Read the full diff line by line, and trace the affected paths end to end, including existing
       data and partial failures. For each earlier fix that touched shared logic, list what depends on it. Report
       the checks actually run, what they showed, and what still needs verifying.
    5. **Classification in code.** Is code using word lists, keyword or pattern checks, or hand-built heuristics to
       judge language or content? Those grow with every round. Name the alternative (`/operate` Phase 1 step 6): a
       stored field, a dedicated classification model, or a general model call with a fixed output schema,
       whichever is cheapest and passes the tests.
    6. **Recommendation.** **Targeted fix**, **simplify <part>** or **redesign <flow>**. Say why, what would change,
       which test would prove the root cause is fixed without breaking existing behaviour, what evidence would
       close the review, and what would justify another round. A redesign note says what is stored, who writes
       it, who reads it, the backfill, the code it removes, and which contract rows change.

    **The owner decides** (round rule 6 escalation, options from the recommendation, each with a pro and a con).
    Make no edit until the answer is recorded.
    - **Redesign:** implement it with `/operate` from Phase 1 step 2 (a fresh inventory) through Phase 3, starting
      from `state_homes` in `plan-check.json` (rewritten for the new design), **replacing** the patched code. Run the Critical Systems checks in
      `CLAUDE.kit.md` where they apply. This starts a new count of up to three rounds, and its round 1 reviews the
      whole branch. At most **once per ticket**: a trigger after it escalates again with a fresh assessment, and
      without the redesign option.
    - **Targeted fix** or **simplify:** carry on with the fix steps, then the next round. If that round would pass
      the limit (round rule 3), the answer is the owner-granted round (`extra_round: true`), so the fix is still
      reviewed. With that round already used, offer only redesign, re-scope or ship with named defects.

    Record `redesign: <trigger> → <decision>`. While an assessment or a redesign is in progress, the loop has no end
    state.
11. **Open items go to `<OPEN_ITEMS_TICKET>`.** It holds only work that isn't this ticket's own defect. A noted
    finding kept only on its own ticket is lost when that ticket closes. **One writer, at one moment:** the step
    that closes the ticket (`/ship`, or a pack that closes tickets) writes **one** comment on
    `<OPEN_ITEMS_TICKET>` with ticket op **comment**, before closing, from the records already on the ticket. Never a
    ticket per finding. Post-op and `/peer-review` only record items on the ticket.
    - **Filed:**
      - every `noted` item in the round records (pre-existing, below the bar);
      - every item in a `Noted for the tracker` comment (from `/peer-review`, or a pack's `/security` audit);
      - every pre-existing gap or accepted bounded race the records name;
      - every defect the owner accepted by name, tagged `accepted by owner`.

      Never a must-fix or a nit.
    - **Format:** `## <ticket> — <title> (closed <date>; round records <comment refs>)`, then one numbered item
      each: **where** (`file:line` or function), **effect** (what happens, to whom), **why it was left open** (class,
      origin, or owner acceptance), **suggested fix and test**, tagged `(worth fixing)` or `(minor)`, plus `· S3`
      when it touches `<CRITICAL_DOMAIN>` logic.
    - **Marker** on the source ticket, first line: `Open items (PR #<N>): <OPEN_ITEMS_TICKET> comment <id>`, or
      `Open items (PR #<N>): none` (then nothing is filed). One marker per PR, so a reopened ticket files only items
      recorded after its previous marker.
    - `<OPEN_ITEMS_TICKET>` stays open. A later ticket that fixes an item replies on that item's comment:
      `fixed in <ticket>`.

**Code review row.** Passing:
- `✅ Clear`: end state `clean`, no must-fix in any round, covered;
- `✅ N found, N resolved`: end state `clean`, every finding disposed of, covered;
- `✅ Accepted by owner`: an answered `escalate` that ships named defects, covered;
- `⏭️ Skipped — no reviewable change`: docs only;
- `⏭️ Skipped — Codex`: Codex has no Workflow tool or `/code-review`, and never claims a review ran.

Not passing:
- `⚠️ Escalated`: waiting on the owner, including a spiral assessment;
- `⚠️ N open`: a must-fix isn't fixed;
- `⚠️ Not run`: the review failed, didn't cover the branch, or the code isn't covered.

Summary: one line, such as "base origin/<MAIN_BRANCH> · 2 rounds · clean: 9 found (first-draft 5 · fix-introduced 1
· pre-existing 1 · not a defect 2), 6 fixed, 1 noted, 2 rejected".

---

## Step 2: Report

After all gates and the code review finish, never interleaved:

```
POST-OP REPORT: <ticket> — <title>

| Gate            | Status          | Summary                                         |
|-----------------|-----------------|-------------------------------------------------|
| Self-red-team   | ✅ Ran          | <scope check · what was probed · auto-fixes>     |
| Contract audit  | ✅ N/N rows     | <one line per row below>                         |
| Observability   | ✅ Pass         | <one line>                                       |
| Security        | ✅ Pass         | <one line>                                       |
| API Contract    | ⏭️ Skipped      | no API changes                                   |
| Migration Guard | ⏭️ Skipped      | no schema change                                 |
| Compliance      | ⏭️ Skipped      | no copy changes                                  |
| Docs Update     | ✅ Updated      | <one line>                                       |
| Test            | ✅ Pass         | <suite counts>                                   |
| Mock Fidelity   | ✅ Pass         | <one line>                                       |
| Code review     | ✅ Clear        | <base origin/<MAIN_BRANCH> · R rounds · end state · N found> |

Contract audit:
  C1 | <exact input> | <observable asserted> | <mutation applied> | <counterfactual result>

Code review findings (one line each):
  [R1-1] <finding> — <file:line> — <class> · <origin> — <disposition>
Origins: first-draft <a> · fix-introduced <b> · pre-existing <d> · not a defect <e>

Peer review: not run | CLEAN <snapshot_hash> | UNRESOLVED
Recorded for the tracker: <N> noted (filed on <OPEN_ITEMS_TICKET> when the ticket closes) | 0

✅ All gates passed. Ready to ship.
  or
⚠️ <N> unresolved, post-op is incomplete:
  - <Gate>: <specific action>

Owner action: none | <the one decision needed now>
```

- **Peer review line:** read `verdict` from `.claude/state/<ticket>/peer-review.json`; no file means `not run`. It
  is informational. Post-op never requires `/peer-review`, but `/ship` stops on an `UNRESOLVED` one.
- **Incomplete** if a gate has an unresolved defect, the suite is red, a contract row is unaudited, or the Code
  review row is `⚠️`. Self-red-team and Contract audit rows are mandatory on executable changes, Code review on
  every run. A missing row is a skipped step.
- **`Owner action:` is `none`** unless only the owner can decide something now: an Owner-Kept Gate as it applies, a
  product decision, or an escalation's choice. (The one non-decision case: the closing step failed to file open
  items.) Never list gates the workflow already tracks, never hand the owner a chore the agent can do or caused, and
  don't count offering `/peer-review`. A process gap found mid-run is fixed under its own ticket and reported.

**State file.** When the report is complete, write `.claude/state/<ticket>/post-op.md` with the report and these two
lines:
```
Fingerprint: <output of node .claude/scripts/kit-tools.mjs fingerprint --base origin/<MAIN_BRANCH>, on this tree>
Result: clean | escalate
```
`Result` is the end state (round rule 6); `escalate` is written only once the owner has answered **ship with these
named defects**. Any other answer continues the loop. On a
docs-only branch, write `Fingerprint: none (no reviewable change)` and `Result: clean`. On a Codex run, `Result:
clean` means the gates passed and the report's Code review row says `⏭️ Skipped — Codex`. `/ship` reads this file
for its covered check, so write it last, after every fix. Then run
`python3 .claude/hooks/check-record.py --kind post-op --ticket <ticket>`; fix the file and re-run until it exits 0.

---

## Step 2.5: Lessons learned (never skipped)

Answer two questions:
1. **Assumption delta:** what did the ticket or plan assume that proved wrong against the real code, schema or API?
2. **Gate gap:** which gate would have caught it at the start, if it had existed? With no surprises, write: "No
   assumption deltas — gates covered the work."

For each delta, append to `docs/agent/lessons.md` under the fitting theme heading (a new heading only when none
fits):
```
### <ticket> — <one-line lesson>
Rule: <the rule derived>. Why: <the assumption that was wrong>. How to apply: <what to check next time>.
```
"No deltas" is a valid answer, and saying so takes 30 seconds.

---

## Step 3: Notify

Notify: if `.claude/scripts/notify` exists, run `.claude/scripts/notify "<text>"`. A failed send prints one line and
never fails post-op. Text:
```
[<PROJECT_NAME>] Post-op <ticket>: <✅ ready to ship | ⚠️ N issue(s)>
Gates: <each gate: ✅ / ⚠️ / ⏭️>
Code review: <status> · <R rounds · end state>
Owner action: <none | the action>
<if a lesson was recorded: Lesson: <one line>>
```

---

## Rules

- **Order:** self-red-team and contract audit → gates 1–8, every defect fixed → code-review rounds on that final
  code → report → Lessons learned → notify.
- **Never report a gate you didn't run on the current code.** Any fix after a gate ran, including a `/peer-review`
  fix, invalidates the gate verdicts: re-run gates 1–8, or mark the ones not re-run.
- Only the closing step writes to `<OPEN_ITEMS_TICKET>` and the `Open items (PR #<N>)` marker, so a later
  `/peer-review` can still add items.
- Never defer, downsize or split a real S1–S4 defect on the ticket's path, or any real defect in code this ticket
  wrote. Filing it on the tracker is deferring it.

Why these rules exist: `docs/workflow/history/review-loop.md` (not loaded by default; where it disagrees with a rule
here, the rule wins).
