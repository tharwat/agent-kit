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
- **`/peer-review` is not part of post-op.** It is the optional frozen-snapshot review the owner may ask for
  afterwards: `/triage` → `/operate` → `/post-op` → `/peer-review` (optional) → `/ship`. Never launch it here, and
  never report its absence as a gap. Codex as a finder inside a review round (Step 1.5) is separate from it.
- **The vote decides what is fixed here; you don't.** A real defect is fixed on this ticket when its loss is
  serious or normal use reaches it, whoever wrote it, and in the sweep also when its fix is small (round rule 2).
  Every other real defect goes into the ticket's one follow-up ticket, with the voters' analysis attached. Nothing
  is deferred by the author or by a round count, and nothing real is dropped. The ticket ends clean or goes to the
  owner (round rules 3 and 6).
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
  - the production lines each file gained are set against the page's `size`, and the diff adds no state, phase or
    recovery rule the page's `adds` doesn't have;
  - every value the diff changes has a `values` entry, and its readers and writers were re-walked against this
    diff;
  - every new behaviour has a `siblings` entry, with every guard its sibling has, copied or not applicable with a
    reason;
  - every fix batch has its fix notes (`/operate`, "Every fix batch");
  - every stored state matches its one home.

  A missing or stale entry fails the self-red-team. The work goes back to `/operate` Phase 1 step 2 for that row,
  never on to review.
- **Deliberate markers.** Every `Deliberate (decided R<n>-<k>)` comment in the diff names an id in
  `.claude/state/<ticket>/review-rounds.md`, and the code under it still matches the recorded reason.

Sort each self-red-team finding into one of two kinds:
- **Auto-fix:** mechanical, unambiguous and low-risk, such as a missing or wrongly formatted log line, an unmasked
  identifier in a log, a missing import, or a copy-rule wrap. Apply it and note `[AUTO-FIXED] <file:line> — <what>`.
- **Flag:** everything else, such as logic gaps, edge cases, security, or design trade-offs. Verify it against the
  code. A real defect is fixed now, through `/operate`, "Every fix batch": you never defer your own finding.

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

Runs after gates 1–8 pass, on the final code. Each round is the `consensus-review` workflow:

- **Finders** read the change with no context from you: three Claude reviewers with different lenses on every area,
  and Codex when it is installed. There is no cap on findings.
- **Voters** decide: one agent groups the reports by mechanism, so a defect reported from several files is voted
  on once. Two verifiers try to refute each group, and their answers sort a real one (round rule 2).
- **You are the witness, never a voter.** You wrote the code, so "it's minor" is the easy answer. You say what is
  already guarded or decided, and the voters check it.

Expect one sweep and one check of the fixes. A defect inside a fix stops the patching there (round rule 10).

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
   step 1): `git diff --output=.claude/state/<ticket>/round-<N>.diff <base>`. For round 1, take its areas:
   `node .claude/scripts/kit-tools.mjs areas --base origin/<MAIN_BRANCH>` prints them as one JSON line. A large diff
   is split so every area gets its own three reviewers. A later round passes no areas.
2. **Write the witness note:** one line for each guard or decision a reader without your context could miss, as
   `<file:line or record> — <what it guards or decides>`. Give a place to check, never an argument.
3. **Run the workflow by path.** Call the Workflow tool with
   `scriptPath: "<repo root>/.claude/workflows/consensus-review.js"`, where `<repo root>` is the output of
   `git rev-parse --show-toplevel`. Never call it by `name`: a name resolves to the copy loaded when the session
   started, which is stale if the workflow changed since. Pass `args`:
   ```json
   { "ticket": "<ticket>", "round": N, "base": "origin/<MAIN_BRANCH>", "areas": <the areas JSON, round 1>,
     "criticalDomain": "<CRITICAL_DOMAIN>", "consumerSurfaces": "<consumer surfaces from docs/agent/source-layout.md>",
     "contract": "<contract rows>", "threatModel": "<the contract's threat-model line>",
     "prior": [{ "finding": "...", "disposition": "..." }], "savedDiff": "<previous round's saved diff, rounds 2+>",
     "witness": "<the witness note>", "codexModel": "<see below>",
     "scratchDir": "<session scratch dir, else .claude/state/tmp>" }
   ```
   - `prior` is the **decided list**: every earlier finding, as `"R<n>-<k>: <finding>"`, with its disposition, plus
     the standing items. It also holds every owner decision recorded for this ticket before the review (on the
     ticket, in the contract, in a triage answer, in a project doc the change follows), as `"Owner: <the
     decision>"` with the disposition `already decided — <where it is recorded>`. Finders and voters both get it,
     so a decided item comes back only with new evidence.
   - `codexModel` is the model on the `Codex model:` line of `.claude/commands/codex-review.md`. Pass it when
     `codex --version` runs on this machine; leave it out otherwise. Codex then reviews headless, read-only, with MCP
     servers off. A round counts without it, and the result's `codex` says what happened.

   Running the workflow is part of this command and needs no separate opt-in.
4. **Fallback, when the Workflow tool is unavailable:** run `/code-review high --max-findings all` (Skill
   `code-review`). It is built into Claude Code, not shipped by the kit; if this session doesn't list it, the round
   didn't run (`⚠️ Not run`). Codex has neither, so it skips Step 1.5 and records `⏭️ Skipped — Codex`. Never
   `ultra` (the owner's manual cloud review), never without a level (it reuses the last one). It diffs against the
   branch upstream, so point the upstream at the base, saving a pushed branch's own upstream to restore afterwards.
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
   file. It is marked `restored`, never removed.

   The built-in review has no voters, and you still don't vote. Start two fresh subagents with no context from
   you. Give each the findings, the contract's threat-model line, the decided list and round rule 2's questions.
   Apply the table to their answers as written: where the two don't agree, the finding is fixed now. With no
   subagents either, every real finding is fixed now. You may reject one only with `file:line` evidence, and you
   never defer one.
5. **Wait for the completion notification** before writing the report. Don't call `ReportFindings`.
6. **Check what it reviewed:** the branch against `origin/<MAIN_BRANCH>` (the workflow's `base` and `scope`; for the
   fallback, paste the `must print` output into the row). A failed reviewer, a wrong base or `round_ran: false`
   (fewer than 2 of 3 reviewers returned for an area) means the round didn't run: run it again.
7. **Take the result as decided.** Each list in it (`must_fix`, `redesign`, `tickets`, `open_class`, `nits`,
   `rejected`, `repeats`) is a disposition below, and each real finding carries its `why`, `class` and `origin`.
8. **Object, don't overrule.** If you can show with `file:line` that an item is already guarded or decided, or the
   result has `unverified` items, run the workflow again with the same `round` and
   `"recheck": [{ "file", "line", "summary", "failure_scenario", "objection": "<your evidence>" }]`. Only the voters
   run, and their answer stands. The round doesn't count while anything is unverified. You never reject, shrink or
   defer a finding yourself.

Give each finding an id `R<round>-<k>` and one disposition, starting with its word exactly as below (the workflow
matches earlier dispositions by leading word):
- **`must-fix`**: the result's `must_fix` or `redesign`. It is fixed on this ticket: a `must_fix` item as one batch
  through `/operate`, "Every fix batch", with no owner question; a `redesign` item through round rule 10. Then
  gates 1–8 again.
- **`follow-up`**: the result's `tickets`. The vote deferred it: it is real, its loss is bounded, and normal use
  doesn't reach it. All of a ticket's deferred findings go into **one** follow-up ticket, written once, when no
  round is due (round rule 6). Run ticket op **search** for `Follow-up: <ticket>`. If it exists, add to it with
  ticket op **comment**. Otherwise use ticket op **create** in the backlog (title `Follow-up: <ticket> review
  findings`; parent: the ticket's epic, if any; labels per `.claude/rules/ticket-ops.md`). It has one entry per
  finding: where (`file:line`), what happens and to whom, the voters' `analysis` as returned, the `priority` (for
  `dormant`, what would wake it), and a suggested fix and test. Record its key on every `follow-up` line.
- **`own ticket`**: a genuinely independent capability, never a defect of this change. Ticket op **search**, then
  **comment** on the open ticket that covers it, or **create** one. Record the key and carry on.
- **`open class`**: the result's `open_class`, one more member of a class with no end. Never fixed or filed on its
  own: one line under its mechanism in the round record, as a known limit.
- **`nit`**: nothing wrong happens (style, naming, refactor, test polish, wording, unmeasured performance). Not
  fixed, not filed: one line in the round record.
- **`rejected`**: the voters could not confirm it, or it is outside the threat model or unreachable, with their
  evidence. When it upholds a deliberate design choice, write the reason at the site as a code comment:
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
2. **The impact vote decides what a real finding gets.** The voters answer facts, the table is applied in code, and
   the author answers nothing.
   - **Real or not.** Inputs outside the threat model, a deliberately hostile author, an unreachable path and a
     case no voter can construct from the code are not real: `rejected`. No threat-model / out-of-scope line in
     the contract: write one from the acceptance criteria before the round, and show it in the round record.
   - **The questions,** for each real finding:

     | Question | Answers |
     |---|---|
     | What is lost, at worst | data · security · a person (wrongly contacted or charged, or a legal breach) · `<CRITICAL_DOMAIN>` · money · an operator's hand work · appearance · nothing |
     | Is the loss bounded | yes (small, known, can be put right) · no (it can repeat or grow unseen) |
     | What has to happen first | normal use · an unusual but valid input, order or timing · one independent failure · two or more · nothing can today (`dormant`: it needs a setting production doesn't use, an edited constant, or far more data than exists) |
     | Would anyone notice | yes · no |
     | What does the fix cost | small (a few lines in one place; no new state, list entry, exception or mechanism) · costly |
     | Is it one more member of a class with no end | yes (another phrase, format, evasion or fault combination) · no |
   - **The table.** The first row that fits wins. Two voters must agree; where they split, it is fixed now.

     | The voters agree that | Then |
     |---|---|
     | nothing wrong happens | `nit` |
     | it is one more member of a class with no end | `open class`: never fixed one by one. If normal use or a serious loss reaches it, the mechanism is redesigned (round rule 10) |
     | the loss is serious: data, security, a person, `<CRITICAL_DOMAIN>`, or money with no ceiling | fix now, however unlikely |
     | normal use reaches it | fix now, however small |
     | it cannot go wrong as the project stands today (`dormant`) | `follow-up`, naming what would wake it |
     | the fix is small, and the round is the sweep (round 1) | fix now, however unlikely |
     | none of these | `follow-up`, with the analysis and a priority |
   - **Who a defect reaches decides, not the size of its fix.** The sweep reads everything once, so it also fixes
     what is small. After it, every fix is new code another round must read: a later round fixes only a serious
     loss or a defect normal use reaches, and files the rest. A round with nothing to fix now is `clean`, however
     many entries the follow-up ticket holds.
   - **Class** is the label the record keeps: **S1** data integrity, or money with no ceiling; **S2** auth and
     security, or a person; **S3** `<CRITICAL_DOMAIN>`; **S4** anything else normal use reaches; **noted** any
     other real defect; **nit**.
   - **Origin:** `first-draft` (a line this branch wrote), `fix-introduced` (a line an earlier round's fix added or
     changed) or `pre-existing` (unchanged from `origin/<MAIN_BRANCH>`). Origin doesn't change the table. It is how
     a project measures its first drafts, and `fix-introduced` is an event (round rule 10).
3. **Rounds run until the code is clean.** Rounds are numbered per ticket, not per run. Continue the numbering from
   the round records (round rule 8): the state file, or the `Review round` comments from ticket op **get** when it
   is missing. Every round saves the diff it reviewed.
   - **Round 1 sweeps the whole branch,** area by area, with no cap on findings.
   - **A later round reviews only the fix delta:** the previous round's saved diff against the current one, plus
     the functions those lines sit in. The delta holds every change since, from any source, committed or not.
   - Rounds run without asking, attended or not, and never create or move branches.
   - **No counter decides anything.** A round count never ends the work, never asks the owner, and never defers a
     finding.
4. **Repeats.** A finding that repeats an earlier `rejected`, `nit`, `follow-up`, `open class` or `already
   decided` disposition is marked `repeat` (citing its id) and never counts as new. A finding fixed in an earlier
   round that comes back is **not** a repeat: the fix didn't hold, which is an event (round rule 10).
5. **A round is due** when a reviewable change landed after the last round (a must-fix, a gate fix, a
   `/peer-review` fix). Tickets, open-class lines, nits, rejected leads and repeats change no code, so they never
   make a round due. Re-run gates 1–8 before each round. **No change ships unreviewed:** every change is followed
   by a round.
6. **End states.** When no round is due, take the **first** line that matches:
   1. **`escalate`:** a needs-owner finding is open, or a redesign note is waiting for the owner (round rule 10).
   2. **`clean`:** anything else. The last round ran on the final code (round rule 7) and its `next` is `clean`.
      Write the follow-up ticket now, from every `follow-up` line of every round.

   **Escalating:** send **one** message to the owner. Attended: ask in the session. Unattended: post it with
   ticket op **comment** `<ticket>` and Notify (Step 3), and pause the loop. It holds the product question or the
   redesign note, in plain language, with its evidence, a recommendation, and options each with a pro and a con.
   The answer is recorded and applied without another question, and the loop continues. Never offer to ship a
   must-fix or to file it elsewhere: only the vote defers a finding. The owner may still accept a defect by name,
   unprompted: the closing step files it (round rule 11). A round that fails or doesn't cover its scope is not a
   round: run it again.
7. **Covered** (needed for every passing status): no round is due, and the last round reviewed the current code.
   Compare its saved diff with the current diff: nothing but code comments and plain docs (round rule 1) may have
   changed, so a `Deliberate` marker added after a round keeps the code covered. A reviewable change after the last
   round makes a round due.
8. **Record each round** as one block in `.claude/state/<ticket>/review-rounds.md`, and post the same block with
   ticket op **comment** `<ticket>`, first line `Review round <n>: <ticket>` (the record marker in
   `docs/workflow/ticket-ops.md` §3; `/ship` reads it). Include:
   - the saved diff's path and fingerprint, the round's `scope`, and a `Panel:` line (`reviewers` and `codex` from
     the result);
   - every finding with its id, class, origin, disposition and the result's `why`;
   - a `Fixed:` line, `<X> of <N> real findings fixed here`, then every other real finding with where it went and
     why;
   - an `Origins:` line (`first-draft <a> · fix-introduced <b> · pre-existing <d> · not a defect <e>`, where `e`
     counts rejected, repeats and nits). This is how a project measures whether its first drafts are improving;
   - the fix notes of the batch that follows (`/operate`, "Every fix batch");
   - the standing items, the tickets created, the end state, and any owner answer, verbatim;
   - the round's `next`, and any redesign note with its `Redesign size:` line.
9. **Attended and unattended runs follow the same rules.** Only how an escalation reaches the owner differs (round
   rule 6). Plain post-op and packs that run it (ticket trains) all use rules 1–11.
10. **The next step is the round's `next`: `clean`, `fix` or `redesign`. Events decide it, never a count, a guess or
    the author.**
    - **`fix`:** one batch (`/operate`, "Every fix batch"), then the next round, which reviews only that batch.
    - **`redesign`** means the part `next.part` names is not patched finding by finding. It fires when:
      - in the sweep, two or more findings share a cause that one change closes (`shared_causes`): a fact the code
        works out instead of reading, or a second copy of a mechanism. Two verifiers confirmed it;
      - a real defect sits in lines an earlier fix wrote;
      - a real defect comes from the same mechanism as one an earlier round fixed.
        For both of these, wrong text alone (the only loss is appearance) is just fixed;
      - normal use or a serious loss reaches an open class;
      - a fix you are about to write would add a stored state, a user-visible outcome or a new mechanism. That is
        a design change, not a fix, and you raise it yourself.

      Make no further edit to that part. The round's other `must_fix` items are still fixed in the same batch.
    - **The redesign note goes to the owner before any edit** (round rule 6). Write it into `review-rounds.md` and
      post it with ticket op **comment** (first line `Redesign: <ticket>`). Keep it to one screen:
      1. **What happened:** the findings and fixes in this part so far, one line each, and the shared cause when
         the round named one (its proposed change is where the choice starts).
      2. **The choice,** taking the first that works:
         - **remove** the protection or the part. Say what is lost, how rare the case is and what one occurrence
           costs. Accepting a small, rare loss is a valid design;
         - **reuse** a state or mechanism that already exists, with its `file:line`;
         - **one closed shape:** a stored state with its allowed moves and one writer, a rule on structure or
           position, or a model call with a fixed output that fails closed. Never another pattern, word list,
           exception or state worked out from several fields: that is the same kind of solution again.
      3. **What it deletes,** and the production lines in this part now and expected after.
    - **A redesign changes the kind of solution and removes code.** Implement the approved choice through `/operate`
      from Phase 1 step 2, replacing the patched code. Then record `Redesign size: <production lines in the part
      before> → <after>`. If it grew, it was a rebuild: tell the owner, with the numbers, before the next round.
      The next round reviews the delta, which holds the whole redesign.
11. **Open items go to `<OPEN_ITEMS_TICKET>`.** It holds work that isn't a review finding of this ticket: the vote
    sends a deferred finding to the ticket's follow-up ticket (round rule 2), so review rounds add nothing here. **One writer, at
    one moment:** the step that closes the ticket (`/ship`, or a pack that closes tickets) writes **one** comment
    on `<OPEN_ITEMS_TICKET>` with ticket op **comment**, before closing, from the records already on the ticket.
    Post-op and `/peer-review` only record items on the ticket.
    - **Filed:**
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
- `✅ Clear`: end state `clean`, no real finding in any round, covered;
- `✅ N found, N resolved`: end state `clean`, every finding disposed of, covered;
- `✅ Accepted by owner`: an answered `escalate` that ships named defects, covered;
- `⏭️ Skipped — no reviewable change`: docs only;
- `⏭️ Skipped — Codex`: Codex has no Workflow tool or `/code-review`, and never claims a review ran.

Not passing:
- `⚠️ Escalated`: waiting on the owner (a product decision or a redesign note);
- `⚠️ N open`: a must-fix isn't fixed;
- `⚠️ Not run`: the review failed, didn't cover its scope, or the code isn't covered.

Summary: one line, such as "base origin/<MAIN_BRANCH> · 2 rounds · clean · Codex returned 4 · 11 real: 9 fixed, 1
follow-up, 1 open class (first-draft 9 · fix-introduced 0 · pre-existing 2) · 6 not a defect".

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
  [R1-1] <finding> — <file:line> — <class> · <origin> — <disposition> — <why>
Panel: <reviewers> · Codex <returned n | unavailable — why | not requested>
Fixed: <X> of <N> real findings fixed here · <follow-up ticket key> · <open-class lines>
Origins: first-draft <a> · fix-introduced <b> · pre-existing <d> · not a defect <e>

Peer review: not run | CLEAN <snapshot_hash> | UNRESOLVED
Recorded for the tracker: <N> (filed on <OPEN_ITEMS_TICKET> when the ticket closes) | 0

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
- Never defer, shrink or reject a finding yourself. Only the vote sends one to the follow-up ticket (round rule 2),
  and it never sends a serious loss or a defect normal use reaches.

Why these rules exist: `docs/workflow/history/review-loop.md` (not loaded by default; where it disagrees with a rule
here, the rule wins).
