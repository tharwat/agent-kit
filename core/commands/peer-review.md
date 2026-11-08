---
description: Optional two-engine review (B-Team + Codex) of one frozen, hashed snapshot, after /post-op and before /ship. Also runs the pre-code test-contract pass.
argument-hint: "[ticket] | test-contract <ticket>"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# Peer Review

Invoked with: `/peer-review [ticket]`, or `/peer-review test-contract <ticket>` (pre-code mode). With no ticket, take
the key from the branch name and confirm it with ticket op **get**.

## Purpose

Runs two independent, zero-context, review-only engines against finished work: `/bteam` (Claude) and
`/codex-review` (Codex). They report; they never edit. This command freezes the one artifact both review, combines
their results and writes the record `/ship` reads. The engines' files hold the brief, the lenses, the verification
recipes and the prior-art gate: follow them in full.

- **Optional.** `/triage → /operate → /post-op → /peer-review (optional) → /ship`. The owner decides per ticket. Never
  run it unasked, and never call its absence a missing step.
- **The one exception:** once a pass has run, an unresolved verified finding stops `/ship`.
- **No substitutes.** Reading the diff yourself, re-running the suite or a hand-made checklist is not a peer review.
  The value is two engines that don't share your assumptions.

Rationale: `docs/workflow/history/peer-review.md`. If it and this file disagree, this file wins.

---

## Pre-code test-contract mode

`/peer-review test-contract <ticket>` is the independent test-design pass `/triage` runs for executable work. It
runs `/bteam` "Pre-code test-contract mode" exactly as written there: a fresh reviewer gets the ticket intent, the
baseline code map and the draft contract, never a patch, and returns hostile vectors with their provenance
(engine and date). Triage verifies them and folds them into the contract. This mode writes no peer-review record
and has no effect on `/ship`. The rest of this file is the post-work review.

---

## Step 0: Preconditions

```bash
git fetch origin <MAIN_BRANCH>
git log origin/<MAIN_BRANCH>..HEAD --oneline
git status --short
```

- Nothing ahead and a clean tree → stop: "Nothing to review."
- If Node is unavailable, say so and stop. There is no hand-run fallback for the helper.
- **Own gates first.** The last `Fingerprint:` in `.claude/state/<ticket>/post-op.md` must equal
  `node .claude/scripts/kit-tools.mjs fingerprint --base origin/<MAIN_BRANCH>`, with `Result: clean` or
  `Result: capped` (both are passing end states). Otherwise say so and stop: reviewing code whose own gates haven't
  passed spends both engines on defects you'd find yourself.
- **Docs-only diff** (the fingerprint refuses it as empty): say so and ask the owner whether to still run. Don't
  refuse.

## Step 1: Freeze the snapshot

A review belongs to the snapshot it reviewed. **Make no source edit from here until both engines have returned.**

**1a. Save the contract.** With the file-edit tool, copy the contract from `.claude/state/<ticket>/triage.md` to
`<scratch>/<ticket>-contract.md`: the header, every `C<n>` row with its filled `Discharge` cell, and the
threat-model line. No placeholder rows. If the ticket has no contract, write one line, `NO CONTRACT: <why>`, and
say so in the verdict. Don't invent one.

**1b. Freeze.** `git add -N -- <path>` every intended new file first. Then:

```bash
git fetch origin <MAIN_BRANCH>
node .claude/scripts/kit-tools.mjs fingerprint --base origin/<MAIN_BRANCH>
node .claude/scripts/kit-tools.mjs freeze --base origin/<MAIN_BRANCH> \
  --contract <scratch>/<ticket>-contract.md --out <scratch>/<ticket>-snapshot
```

- `fingerprint` prints the **fingerprint** (reviewable diff, docs excluded). On a docs-only diff it refuses; record
  `null`.
- `freeze` writes `base.txt` (the merge-base), `patch.diff` and `contract.md`, and prints the **snapshot hash** of
  all three.
- A refusal prints one line. Fix its cause (an untracked file: `git add -N` it or gitignore it) and run again.
  Never hand-roll a diff or a hash.

**1c. Prove the snapshot held.** After both engines return, read the merge-base sha from
`<scratch>/<ticket>-snapshot/base.txt` and re-freeze against it, written literally (no `$(…)`, so the call matches
the allow rule):

```bash
node .claude/scripts/kit-tools.mjs freeze --base <sha from base.txt> \
  --contract <scratch>/<ticket>-snapshot/contract.md --out <scratch>/<ticket>-recheck
```

It must print the snapshot hash. If it doesn't, the reviews describe code that no longer exists: re-freeze and
re-run. Never record them.

**When to re-freeze:** any edit before both engines finish; a failed 1c; or, after fixes, when the owner wants
another pass (a large fix, a safety path, a fix you're unsure of). A new snapshot starts a new pass; results from an
old snapshot never carry over.

## Step 2: Run both engines, in parallel

Start `/bteam` and `/codex-review` together. Give each: ticket key and one-line intent, the threat-model line, the
snapshot directory and the snapshot hash.

- **Both, or say which.** An unavailable engine is recorded as `UNAVAILABLE — <actual error line>`. It doesn't
  block the ticket, since the pass is optional, but a single-engine run is labelled as one and never reported as full
  coverage. Don't re-run the other engine to make up for it.
- An engine's result counts only when `node .claude/scripts/kit-tools.mjs check-review` accepts its output for this
  hash. Missing or partial output is `UNAVAILABLE`, never clean.
- The Codex row names its model.

## Step 3: Verify every claim

A claim is a hypothesis, not a bug. Only `FINDING:` blocks can block; `OBSERVATION:` entries are recorded, never
block and never create a ticket. Verify each finding against the snapshot with `/bteam` Step 4, **prior-art gate
included**, at every severity. For an integration or schema claim, check the real schema, a real payload or live
docs. Then give it a status:

| Status | Meaning |
|---|---|
| `VERIFIED` | Real, with `file:line` evidence; survived the prior-art gate. Labelled `[introduced by this diff]` or `[pre-existing]` |
| `NOTED` | Verified, but below the bar (class `noted`) |
| `REJECTED` | Disproved, with the evidence |
| `ALREADY-RESOLVED` | Already guarded, or an earlier documented decision. Cite where |
| `NEEDS-OWNER` | A product, safety-limit or destructive-operation decision that reading code can't settle |

Give every verified finding a class: S1–S4 is must-fix, anything else is `noted` (post-op Step 1.5 round rule 2).
Merge the same root cause across engines and mark it "both".

## Step 4: Combined table

```
PEER REVIEW: <ticket> — snapshot <hash first 12> · fingerprint <first 12>
B-Team: <CLEAN | FINDINGS (N) | UNAVAILABLE — why>  (<headless | in-session subagent>)
Codex:  <CLEAN | FINDINGS (N) | UNAVAILABLE — why>  (<model>)

| ID | Finding | Class | Engine | Evidence | Status | Disposition |
|----|---------|-------|--------|----------|--------|-------------|
| F1 | ...     | S2    | both   | file:line shows … | VERIFIED | Fix |
| F2 | ...     | noted | Codex  | file:line shows … | NOTED    | Tracker |
| F3 | ...     | S4    | B-Team | file:line shows … | NEEDS-OWNER | <question> |

Rejected / already-resolved: <each with its evidence>
Observations: <each, non-blocking>
```

A verified must-fix finding on this ticket's path is fixed here, even if `[pre-existing]`. Only a genuinely
independent capability gets its own ticket; say so in the table.

## Step 5: Write the record

Write `.claude/state/<ticket>/peer-review.json`. A new pass replaces it.

```json
{
  "ticket": "<ticket>",
  "branch": "<branch>",
  "snapshot_hash": "<snapshot hash>",
  "fingerprint": "<fingerprint, or null for a docs-only diff>",
  "engines": { "bteam": "CLEAN|FINDINGS|UNAVAILABLE|not run", "codex": "CLEAN|FINDINGS|UNAVAILABLE|not run" },
  "findings": [
    { "id": "F1", "class": "S1|S2|S3|S4|noted", "status": "VERIFIED|REJECTED|ALREADY-RESOLVED|NEEDS-OWNER|NOTED", "resolved": false }
  ],
  "verdict": "CLEAN|UNRESOLVED"
}
```

- Every finding from Step 3 goes in `findings`. `NOTED`, `REJECTED` and `ALREADY-RESOLVED` are written with
  `resolved: true`: nothing is left to do. `VERIFIED` and `NEEDS-OWNER` start `false`.
- A `NOTED` finding must have class `noted`. A must-fix class is never `NOTED`.
- `verdict` is `CLEAN` when every finding is `resolved: true`, otherwise `UNRESOLVED`.
- `fingerprint` is the tree this record vouches for. `/ship` runs
  `node .claude/scripts/kit-tools.mjs covered --hash <fingerprint> --base origin/<MAIN_BRANCH>`; a mismatch means the
  review is **STALE** for the tree being shipped.

Then post ticket op **comment** `<ticket>` with first line `PEER_REVIEW: CLEAN <snapshot hash>` or
`PEER_REVIEW: UNRESOLVED <ids>`, followed by the Step 4 table. The comment is the durable record when the local
file is missing.

## Step 6: Resolve the findings

**Noted.** Post one ticket op **comment** `<ticket>` whose first line is `Noted for the tracker (peer review <date>)`,
listing every `NOTED` finding with where, effect and suggested fix. `/ship` files it on `<OPEN_ITEMS_TICKET>`
(post-op Step 1.5 round rule 11). Never a ticket per finding.

**Must-fix (`VERIFIED`, S1–S4).** For each:
1. Add a regression test on the exact faulty path that fails without the fix. Run it to prove that.
2. Fix the root cause and every sibling with the same mechanism. A verified `CHANGED_PATH` finding becomes a new
   `C<n>` contract row first.
3. Run `<TEST_COMMANDS>` exactly.
4. Set `resolved: true`.

**`NEEDS-OWNER`.** Ask the owner one question at a time, every option with a pro and a con. Post the answer verbatim
with ticket op **comment**, then set `resolved: true`.

**After fixes.** The fixes are new code: run `/operate` Phase 3 steps 1, 7 and 8 on the fix delta (new self-review
record), then `/post-op`'s static gates, and a review round if the cap allows (post-op Step 1.5 round rules 5
and 7). Same mechanism twice: follow the redesign rule (round rule 10). Then take a new
`node .claude/scripts/kit-tools.mjs fingerprint --base origin/<MAIN_BRANCH>`, write it to `fingerprint`, recompute
`verdict`, and post a fresh `PEER_REVIEW:` comment. A fixed finding with a failing-without-fix regression test
counts as resolved. Another peer-review pass is the owner's call, not a loop this command enters.

## Step 7: Notify

Notify: if `.claude/scripts/notify` exists, run `.claude/scripts/notify "<text>"`. A failed send prints one line and
never fails the command.

```
[<PROJECT_NAME>] Peer review <ticket>: B-Team <CLEAN|N verified|UNAVAILABLE> · Codex <CLEAN|N verified|UNAVAILABLE>
Open <N> · Fixed <N> · Needs owner <N> · Noted <N> → <clear to ship | /ship blocked until N resolved>
```

## Report

End with the Step 4 table, the verdict, and `Owner action: none` or the single action the owner must take now
(usually answering a `NEEDS-OWNER` question).

---

## Rules

- **Optional, owner-decided.** Its absence is never a defect in a post-op or a ship.
- **Own gates first.** Never on code whose `/post-op` hasn't ended clean, and never while code is still changing.
- **Review-only engines.** Discard any patch either one returns.
- **One artifact.** Only this command freezes. The engines consume the snapshot; they never make another.
- **One snapshot per pass.** No edits while the engines run; a result belongs only to the hash it attests.
- **Verify before presenting.** Unverified or already-resolved claims are never shown as actionable.
- **An unresolved verified finding blocks `/ship`.** `resolved: false` blocks; so does a stale `fingerprint`.
- **No loop by default.** Fix, prove with a test, re-run the gates, update the record.
- Codex runs this command the same way. Where `/bteam` falls back to a Claude subagent, Codex records B-Team as
  `UNAVAILABLE — claude CLI not found`.
