---
description: Deep-security mode for one ticket. Runs triage, operate, post-op, a required peer review (up to three snapshots), then ship, with nothing reaching the main branch before review.
argument-hint: "<ticket>"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# Hardening

Invoked as `/hardening <ticket>`. The ticket key is required.

Takes one hardening ticket through the whole lifecycle, end to end:

**triage → operate → post-op (own gates and review rounds) → peer review (required, up to 3 snapshots) → post-op
report → commit → ship.**

It pauses only for a product decision, an Owner-Kept Gate, a review-loop escalation, or a failed check or unexpected
state, which stops the run rather than merging.

- **Peer review is required here.** Everywhere else `/peer-review` is optional. Hardening is the deliberate
  deep-security mode, so both engines always run.
- **Claude writes the code; Codex only reviews.** Whatever the size of the fix. If it is too big for one pass, split
  it into smaller steps; never hand the writing to Codex. Codex runs only through `/codex-review`, review-only, and
  any patch it returns is discarded.
- **Nothing reaches `<MAIN_BRANCH>` before review and post-op.** No merge, no push to `<MAIN_BRANCH>`, no migration
  applied, until Step 6 records a pass. The `block-push-before-review` hook enforces this while the run is armed
  (Step 1), but the rule holds without it.
- **Codex** doesn't run this command: here Codex only reviews. If invoked in Codex, say so and stop.

Markers live in `.claude/state/hardening/` (gitignored), relative to `git rev-parse --show-toplevel`:
`<ticket>.active` (the run is armed) and `<ticket>.postop-passed` (post-op and peer review passed). A marker whose
first line is `restored` is inactive. Markers are never removed.

---

## Before starting: fresh context

This command needs a fresh context. If this conversation already holds code reads, diffs or work from another
ticket, stop and say: "This session has context from earlier work. Run `/clear`, then `/hardening <ticket>` again."

## Step 0: State check

```bash
git fetch origin
git status --short                 # must be clean
git branch --show-current          # empty (detached) or a branch with nothing ahead of origin/<MAIN_BRANCH>
git log origin/<MAIN_BRANCH>..HEAD --oneline
```

Any uncommitted or unpushed work → stop and say exactly what must be resolved. Ticket op **get** `<ticket>`
(comments and links included); note which analysis findings (`hardening/<version>/`) it covers.

## Step 1: Branch and arm

```bash
git checkout -b <BRANCH_PREFIX><ticket-lowercase>-<slug> origin/<MAIN_BRANCH>
mkdir -p .claude/state/hardening
printf '%s\n' "<ticket> armed <date>" > .claude/state/hardening/<ticket>.active
```

If `.claude/state/hardening/<ticket>.postop-passed` exists from an earlier run, overwrite it with `restored`
(`printf 'restored\n' > …`) so the hook re-arms.

## Step 2: Triage

Run `/triage <ticket>` in full, including the pre-code vectors (Step 4.7) and the hand-off. Post its analysis and
continue. Stop only for a product decision or an Owner-Kept Gate.

## Step 3: Implement

Run `/operate <ticket>`. Claude writes the code. It ends with the self-review record for the current fingerprint.
**Don't commit yet**: the commit comes after the gates (Step 7).

## Step 4: Own gates first

Run `/post-op <ticket>`: Before starting (self-red-team, contract audit), gates 1–8, then the Step 1.5 review rounds
under round rules 1–11. Fix every must-fix finding (S1–S4) on this ticket; the rest are noted. The reviewers in Step
5 start only when post-op ends `clean` or `capped` with the code covered. An `escalate` → ask the owner (round rule
6) and continue with the answer. The engines confirm this work; they don't do it.

## Step 5: Required peer review (at most 3 snapshots)

Run `/peer-review <ticket>` in full: one frozen, hashed snapshot; `/bteam` and `/codex-review` together on it; every
finding verified, prior-art gate included; the record written. Make no source edit while the engines run. Here it
runs without asking.

Before acting on the combined table, check every `VERIFIED` finding once more against an existing guard in the
touched code, an accepted decision recorded on a parent or sibling ticket, and whether it is `[pre-existing]` or
`[introduced by this diff]`. Anything already guarded or decided goes to the rejected / already-resolved row with
its `file:line` or ticket, never the fix list.

Dispositions: **fix** every verified must-fix on this ticket's path, pre-existing or not (none is deferred; only an
independent capability gets its own ticket); **noted** below the bar (peer review's `Noted for the tracker`
comment); **rejected** with new evidence; **owner decision** only for a product, safety-limit or destructive question.

Repair through `/peer-review` Step 6. Every fix batch goes back through Step 4 (`/operate` Phase 3 steps 1, 7 and 8
on the fix delta, the gates, a review round if one is due), then a **fresh snapshot** in Step 5 over the whole
feature. Repeat until a snapshot has no unresolved must-fix, **at most three snapshots**. After the third, fix any
remaining must-fix; if one is S1–S3, escalate with round rule 6's message, whatever the round count. Review rounds
the fixes make due still run within their own cap.

## Step 6: Post-op report and the pass marker

Run `/post-op <ticket>` to its report on the final code. Its gates already ran in Steps 4–5; any source change since
the last snapshot means Steps 4–5 again. Add the final snapshot hash and both engine outcomes to the hardening
summary (they aren't post-op rows).

Any gate failing → **stop**: report which gates failed and what each needs. Don't continue.

Only when the report is `✅ All gates passed`, `.claude/state/<ticket>/post-op.md` holds `Result: clean` or
`capped` (or an answered `escalate`), and `.claude/state/<ticket>/peer-review.json` has `verdict: "CLEAN"`, record the
pass:

```bash
printf 'Fingerprint: %s\n' "<the Fingerprint line from post-op.md>" > .claude/state/hardening/<ticket>.postop-passed
```

Never write this marker while a gate fails or a finding is open.

## Step 7: Commit

Now, after the gates, commit the work:

```bash
git add -- <each intended path>      # never git add -A or git add .
git commit -m "<ticket>: <what changed>"
```

No co-author trailer. Committing doesn't move the fingerprint, so the post-op coverage holds.

## Step 8: Ship

Run `/ship <ticket>` in full. It checks post-op coverage and the peer-review record, pushes, opens the PR to
`<MAIN_BRANCH>`, runs `/verify` before merge, asks the owner's yes (G3), merges, confirms the deploy and logs, files
open items and closes the ticket. Installed packs add their steps there (for example a migration apply). A hardening
ticket isn't done on green checks alone: `/ship`'s pre-merge verify is part of it.

- If `/ship` stops (failed check, failed verify, held for the owner), the markers stay as they are. A fix is a new
  cycle: overwrite `<ticket>.postop-passed` with `restored`, then Steps 3–8 again.
- After `/ship` confirms the merge, mark the run finished: `printf 'restored\n' > .claude/state/hardening/<ticket>.active`.
  Both files stay as the run's record.

## Step 9: Summary

```
✅ <ticket> — <merge commit> — <what was fixed> — merged to <MAIN_BRANCH>, deploy confirmed, ticket closed.
Peer review: CLEAN <snapshot hash> · <N> snapshots · B-Team <outcome> · Codex <outcome>
Owner action: none | <the one action>
```

## Rules

- **Claude writes the code; Codex only reviews.** Never brief Codex to change code.
- **Verify before reporting.** Engine findings are claims; an unverified one is never presented.
- **Verified must-fix findings converge on this ticket.** Own gates (Step 4) always run before the engines (Step 5),
  including after every fix batch.
- Never write code before the Step 2 contract exists, never commit before Step 6 records a pass, never merge except
  through `/ship`, never push to `<MAIN_BRANCH>`.
- Stage named files only.
- An unexpected result stops the run; report it, don't skip ahead. A skipped step states its skip reason.
- Never remove or edit the hardening markers to get past the hook. Finish post-op instead.
