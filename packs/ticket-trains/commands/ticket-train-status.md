---
description: Read-only progress report for ticket trains. Changes nothing.
argument-hint: "[<train>]"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# Ticket train: status

Invoked as `/ticket-train-status [<train>]`.

**Read-only.** It reads `.claude/state/trains/*.json` only through `node .claude/scripts/train-state.mjs summary`,
which writes nothing and takes no lock: no ticket op, git command, deploy or database call. Safe mid-run. If Node is
unavailable, say so and stop.

## With no train name: list the trains

Run `summary` on every `*.json` in `.claude/state/trains/` (say so plainly if there are none) and print one line each:

```
TRAINS
  <train>   created <date>   <done>/<total> done   [N in_progress] [N pending] [N blocked] [N needs_verify] [HALTED]
```

Then: "Run `/ticket-train-status <train>` for detail."

## With a train name: detail

Missing file → list the train names and stop. A malformed file → print `summary`'s one-line error and the path,
and stop. Never fix anything from here.

```
TICKET TRAIN: <train>   base: <base_branch>   created <date>   triaged <date | NOT YET>   peer review engines: <adversarial>
<HALTED: <halt> — /ticket-train-triage <train> asks the owner>   (only when halt is set)

| Ticket | State | PR | Result / verify plan |
|---|---|---|---|
| <key> | ✅ done | #N | <result, ~90 chars> |
| <key> | 🔄 in_progress | #N | <result, or verify_how> |
| <key> | ⏳ pending | — | <verify_how> [triaged · N decisions · review: run|skip|undecided · cr rounds N · <end_state>] |
| <key> | ❓ awaiting_answer | — | q1: <question, truncated> |
| <key> | ⚠️ needs_verify | #N | <what isn't confirmed; fix-forward key> |
| <key> | 🔁 own gate failing | — | <gate> · checkpoint <branch> |
| <key> | ⏸ peer finding | — | <finding id> · <unresolved findings> · checkpoint <branch> |
| <key> | ⏸ review escalation | — | cr-e<n> · round <N> · <end_state> |
| <key> | ⛔ blocked | — | <reason> |

Summary: <done>/<total> done · <n> pending · <n> awaiting_answer · <n> in_progress · <n> blocked · <n> needs_verify
Open questions: <ticket qN (blocking | default: …): question> | none
Constraints in play: <ticket — constraints, for each that isn't "none"> | none
Candidates not queued: <key (after <ticket>) — why> | none
Unqueued work: <one line each> | none
Excluded: <key — reason — unblock_by> | none
Next action: </ticket-train-triage <train> (not triaged | N questions | N circuit-breaker stops | halted) |
              /ticket-train-run <train> (continues at <next>) | train complete | blocked — see reasons above>
```

Rules for the detail view:

- **`needs_verify` is not done.** It is merged but its post-merge check didn't confirm, and the ticket is still
  open. Never count it as done or call the train complete while one remains (`summary` reports `complete: false`).
- Row by `reason` prefix: `own gate failing` → 🔁; `question pr-f` → ⏸ peer finding; `question cr-e` → ⏸ review
  escalation; any other `question` → ❓ (listed under Open questions). All of these point the next action at
  `/ticket-train-triage`, never at the run.
- `in_progress` with no run going in another session means a run was interrupted: say "interrupted;
  `/ticket-train-run <train>` resumes, but check `git status` and the `<BRANCH_PREFIX>` branch first."
- `review:` is the ticket's `peer_review` decision (`undecided` when null). A skipped peer review is a decision,
  never a warning.
- Truncate long `result` and `notes`; the state file and `TRAIN RESULT` comments hold the full record.
