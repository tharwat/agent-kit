---
description: Run a triaged ticket train unattended, one ticket at a time, through operate, post-op, optional peer review and ship. Invoking it approves merging that queue only.
argument-hint: "<train>"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# Ticket train: run

Invoked as `/ticket-train-run <train>`. The last step of **create → triage → run**, in a fresh session.

**The state file is the source of truth, not your context.** Read `.claude/state/trains/<train>.json` first, and
record every state change **before** doing anything else, so a crash or a context compaction loses one transition,
not the run. Re-invoking the command resumes at the first `pending` ticket.

**Every write goes through the helper**, never an inline edit or an edit tool on `.claude/` (auto mode can refuse
those as self-modification):

```bash
node .claude/scripts/train-state.mjs summary .claude/state/trains/<train>.json [<ticket>]            # read; prints the revision
node .claude/scripts/train-state.mjs update .claude/state/trains/<train>.json <ticket|train> <revision> '<json patch>'
```

Read the revision just before each update. The helper locks the file, refuses a stale revision, validates the whole
state, and writes atomically. It also refuses an untriaged ticket going `in_progress`, a ticket going `done` with an
undischarged row or open finding, and any rewrite of recorded evidence. A refusal is a finding about the run: fix the
cause, never work around the helper. A live lock means another writer: wait and retry. A stale lock: stop and report
it (the owner renames it). Run each call from the repo root, as written (no `cd`, no shell variables), so it matches
the permission rules. If Node is unavailable, say so and stop.

## Unattended-run contract

- **One invocation is one run.** It continues through every ticket to a stopping point (see Stopping). Progress
  updates are informational: post one and keep working in the same turn. Never end a turn, ask for "continue", or
  make the owner re-invoke while queue work remains. Before any long wait (a review, the suite, a deploy, CI), record
  the exact phase in the ticket's `result`, so a resume needs no reconstruction.
- **Invoking this command is the owner's G3 approval for the queued tickets only.** For them it also authorizes the
  ordinary actions the workflow requires: sending credential-free diffs and contracts to the configured review
  engines; pushing ticket branches; opening and merging their PRs to `<MAIN_BRANCH>` through `/ship`; ticket ops;
  reading deploy and log state; using already-configured credentials without printing them; and anything in
  `rules.pre_authorized`. Don't ask again per ticket or per round.
- **Batch host approvals.** If the host still asks for interactive approval, put every action you can foresee into
  one plain-language request at session start, then continue automatically.
- **A denial affects only that action.** Record it on the ticket, continue every independent safe step and ticket,
  and list it in the final report.
- **Never** a forbidden action (`rules.forbidden`, verbatim). Hitting one → the ticket goes `blocked` with the reason,
  and the run moves on without asking or waiting.

## Hard rules

1. **Strictly sequential.** Start the next ticket only after the current one has merged with its post-merge check
   done, or is blocked with its work preserved and a clean tree. No parallel implementation agents.
2. **Only the queued tickets.** Work that seems to need another ticket → record it in this ticket's `notes` (or file
   it with ticket op **create** if it is a real discovery) and keep going. Respect `excluded` even when it looks
   related. A verified must-fix defect (S1–S4) on the current ticket's path is part of its contract and is fixed
   before it closes; it is never a follow-up.
3. **Respect recorded boundaries.** Exceeding an owner-set boundary in `constraints`, `notes` or a decision → blocked,
   not improvised. Prefer a fix that stays inside it. A change to one of `<CRITICAL_SYSTEMS>` with no owner-set
   boundary is allowed, with the Critical Systems checks from `CLAUDE.kit.md`.
4. **Recorded decisions outrank your judgment.** `decisions` and each non-blocking question's `default` are facts.
   Never re-open an answered question. A blocking question resolved only by a default means the file is mis-built:
   stop the train and say so.
5. **Run `<TEST_COMMANDS>` exactly as written**, never a subset or a substitute, and read the counts from the
   runner's own output.
6. **Merge blockers.** If a required check or the suite fails for a pre-existing reason unrelated to the diff,
   reproduce it on a clean `origin/<MAIN_BRANCH>` checkout first. Then fix the minimal cause on the current branch,
   add it to `unqueued_work` (train update with the whole list), and explain it on the ticket.

## Session start

1. Read the summary. Missing file → stop and list the trains.
2. **Triage gate.** `triage_required` with `triaged` null, or a `pending` ticket with `triage_gaps` or an unanswered
   blocking question → stop: "Train `<train>` isn't triaged (or has N open questions). Run
   `/ticket-train-triage <train>` first."
3. **Halt gate.** `halt` set → stop: a merge broke `<MAIN_BRANCH>`; `/ticket-train-triage <train>` asks the owner.
4. No `pending` ticket → final report, naming every `awaiting_answer` ticket (waiting on the owner, not finished).
5. If any `pending` ticket has `peer_review: "run"`, re-probe the engines and update `rules.adversarial` if it changed.
6. List the run's external actions once (review engines, pushes, PRs, ticket ops, deploy and log reads) and batch
   any host approval now.
7. `git fetch origin`, then `git checkout --detach origin/<MAIN_BRANCH>`; the tree must be clean. Run
   `<TEST_COMMANDS>`. Red on a clean `<MAIN_BRANCH>` is a pre-existing break: report it and stop. Every ticket would
   look broken on a red baseline.

## Per-ticket sequence

Take the first `pending` ticket.

1. **Start and re-validate.** Update `{"state": "in_progress"}` (the helper refuses an untriaged ticket: then update
   `{"state": "blocked", "reason": "untriaged: <the gaps it named>"}` and move on). Read `triage`, `questions`,
   `decisions`, `constraints`. Run `/triage <ticket>` in full, since code may have moved. Compare with
   `triage.summary`: no change → ticket op **comment** `Run re-validation <date>: no change since TRAIN TRIAGE`; a
   change → the delta as the analysis comment, and any new rows appended to `contract`. Resolve each fork in order:
   a recorded decision → act on it; a non-blocking default → take it and append
   `{ "id", "decision": "<the default>", "by": "default", "date" }`; anything new → append a question (blocking per
   `/ticket-train-triage`'s classes) and block, reason `question q<n>: <one line>`. A `/triage` `BLOCKED` that isn't
   a question (a forbidden action, a premise that no longer reproduces) → blocked with that reason.
2. **Branch or resume.**
   - **No `blocked_work`:** `git checkout -b <BRANCH_PREFIX><ticket-lowercase>-<slug> origin/<MAIN_BRANCH>` and
     record `branch`.
   - **`blocked_work` set:** `git checkout <its branch>` and check `HEAD` equals its `commit`. Record
     `blocked_work.rebasing: true` and `pre_rebase_commit`, then `git rebase origin/<MAIN_BRANCH>` (the checkpoint is
     local-only, never pushed, so rebasing it is safe). A conflict → `git rebase --abort`, block with
     `rebase conflict with origin/<MAIN_BRANCH> — <files>`. Then turn the checkpoint back into uncommitted work with
     `git reset --soft HEAD~1` (every change stays staged; never a hard reset), and record `resumed_at` with
     `rebasing: false` in one update. On resume, `rebasing: true` means a crash between the two writes: accept the
     current `HEAD` as the checkpoint and carry on. Apply the recorded answer, then continue at step 4: the work and
     its contract are already there, and the round count continues from `code_review`, never from round 1.
3. **Implement: run `/operate <ticket>`.** It turns every contract row and vector into a behavioural test before any
   production edit and red-teams the diff. Its counterfactuals and every regression test's red half run in a
   disposable worktree (`git worktree add <scratch>/red-<ticket> HEAD`, then copy the changed files in), **never
   `git stash`** (a stash fails once `git add -N` is in play). Run `<TEST_COMMANDS>` exactly.
4. **Write the discharge back the same turn.** For each contract row, update its `discharge` with `{ "test",
   "result", "path_exercised", "counterfactual_result" }` from the Discharge cells `/operate` filled in
   `.claude/state/<ticket>/triage.md` (send the whole `contract` list). A row still `null` is not discharged: the
   ticket can't pass post-op, ship or close.
5. **Own gates and review rounds: run `/post-op <ticket>`** (Before starting, gates 1–8, Step 1.5) under round rules
   1–11, unattended (round rule 9). After each round, update `code_review` (`rounds`, `extra_round`, `redesign`,
   `end_state`, `self_review` = the record's fingerprint, every disposition appended). Then by end state:
   - `clean` or `capped` → step 6.
   - `escalate` → post-op has already posted its one escalation comment and notified (round rule 6). Preserve the
     work (below), add each open item to `open_findings`, add one `cr-e<n>` question (the items, a recommendation,
     options each with a pro and a con), block with `question cr-e<n>: <one line>`.
   - An own gate that won't pass after a real root-cause attempt: don't loop. Preserve the work, record the gate and
     its output in `notes`, block with `own gate failing — <gate>`. This is a circuit-breaker block.
6. **Peer review, only when the ticket's `peer_review` is `"run"`.** Otherwise record
   `Peer review: skipped (<owner decision | default>)` in `result` and go on. When `"run"`: `/peer-review <ticket>`
   in full. An unavailable engine is recorded and reported as partial coverage, never as blocking. Fix every
   verified must-fix through its Step 6, then back to step 5 (gates on the fix, and a round if one is due). One pass,
   unless a decision says otherwise. A finding that stays unresolved or is `NEEDS-OWNER` → preserve the work, add it to
   `open_findings`, add a blocking `pr-f<n>` question with the evidence and snapshot hash, block with
   `question pr-f<n>: unresolved peer-review finding <id>`. Never relabel it to get past it.
7. **Ship: run `/ship <ticket>`** in full: post-op and covered checks, the peer-review record, commit, push, PR,
   `/verify` before merge, then merge (this invocation is the G3 yes), post-merge deploy and logs, open items, close.
   - **Record the PR number the moment `/ship` creates it** (update `{"pr": <N>}`), before verify or merge.
   - **Pre-merge `/verify` ❌ FAILS:** it's an S4 defect on this ticket. Fix forward once on the same branch through
     steps 3–5 (a new contract row through `/triage` first), then `/ship` again. Fails again, or the fix needs an owner
     decision → preserve the work, block with `verify failed — <what was observed>`.
   - **⚠️ PARTIAL** (couldn't be driven) → preserve the work, block with `verify partial — <what is unverified>`.
   - **A required check fails** → rule 6 if pre-existing; otherwise fix through steps 3–5, or block with the failing
     job's log line.
   - **Post-merge build or deploy failure** (`<MAIN_BRANCH>` is broken) → update the ticket
     `{"state": "needs_verify", "result": "main broken — <deploy and error>"}`, train update
     `{"halt": "<ticket>: main broken — <one line>"}`, notify, and **stop the train**. Later tickets would build on a
     broken base.
   - **Other post-merge failure** → `/ship` files the fix-forward ticket and leaves this one open:
     `{"state": "needs_verify", "result": "merged; post-merge check failed — fix-forward <key>"}`.
   - **Open items not filed, or the close failed** → `/ship` leaves the ticket open: block with
     `open items not filed — <error>` or `close failed — <error>`. These don't count toward the circuit breaker.
   - **Merged, verified, closed** → `{"state": "done", "result": "<one line>"}`.
8. **Result comment.** Ticket op **comment** `<ticket>`, first line `TRAIN RESULT (<train>): <ticket> — <state>`: PR,
   `<TEST_COMMANDS>` counts, the verify evidence, the deploy, the code-review outcome (rounds, end state,
   dispositions), the peer-review outcome (skipped, or engines and snapshot hash), decisions and defaults acted on,
   unqueued work, and the `Open items (PR #<N>)` marker `/ship` wrote.
9. **Advance.** `/ship` already detached the checkout and deleted the merged branch. Confirm `git status --short` is
   clean, notify (`.claude/scripts/notify "[<PROJECT_NAME>] Train <train>: <ticket> <state> · PR #<N>"`, if it
   exists; a failed send prints one line), then take the next `pending` ticket.

## Preserve blocked work

Any block after the ticket branch has changes gets a **local-only checkpoint** before anything else:

1. `git diff --check`, and record whether it was clean.
2. `git add -- <each path this ticket changed>` (never `-A` or `.`), then
   `git commit -m "<ticket>: WIP checkpoint — blocked (<reason>)"`.
3. Update the ticket in one write: `state: "blocked"`, `reason`, and `blocked_work: { "branch", "commit": "<head commit>",
   "reason", "checkpoint_kind": "WIP checkpoint — blocked", "diff_check": "clean|failed", "resumed_at": null }`.
4. `git checkout --detach origin/<MAIN_BRANCH>`, and confirm `git status --short` is clean before the next ticket.

The checkpoint only preserves work. It is never pushed, reviewed, opened as a PR, merged, or used to close the
ticket, and its diff is never copied into another ticket's branch. The record stays as evidence until the ticket is
done.

## Stopping

Stop the loop and report when:

- a merge broke `<MAIN_BRANCH>` (`halt` set);
- **circuit breaker:** two consecutive tickets ended `blocked` for a reason that isn't a question (`own gate
  failing`, `verify failed`, `verify partial`, `untriaged`, a forbidden action), or three in a row ended blocked on a
  question (the triage missed its purpose; the owner should look before more spend). `open items not filed` and
  `close failed` don't count;
- no ticket is `pending`;
- a git, GitHub or database operation left a state you didn't intend. Record the exact state on the ticket and stop;
  no creative recovery.

## Final report

Per ticket: final state, PR, `<TEST_COMMANDS>` counts, verified (with evidence) or `needs_verify` (what isn't
confirmed, and the fix-forward key), the code-review outcome, whether peer review ran (and its coverage: full or
single-engine), every verified finding with its fix and regression proof, decisions and defaults acted on, unqueued
work, any denied action, and the `Open items (PR #<N>)` marker. For a blocked ticket: the reason, open findings or
failing gate, and the checkpoint branch. Then the totals, the remaining queue, and, separately, every ticket waiting
on a question, with the question.

`needs_verify` is not done, and a single-engine peer review is not full coverage. Send the summary through Notify.

`Owner action:` is `none`, or the single thing only the owner can do now: usually
`answer N questions: /ticket-train-triage <train>`, or `close <ticket>: its open items couldn't be filed`.

## Codex

Codex runs the same sequence. `/post-op` records the review row `⏭️ Skipped — Codex` (no Workflow tool), and
`/peer-review` records B-Team as `UNAVAILABLE` when the Claude CLI is missing. Report both plainly; neither is
full coverage.
