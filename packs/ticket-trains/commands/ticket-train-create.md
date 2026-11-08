---
description: Build a named ticket train's state file (queue order, boundaries, verify plans) for an unattended run later. Ships nothing.
argument-hint: "<train> <ticket> [<ticket> ...]"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# Ticket train: create

Invoked as `/ticket-train-create <train> <ticket> [<ticket> ...]`.

The runbook is **create → triage → run**. This step orders the queue and records its boundaries while this session
still has context. `/ticket-train-triage <train>` then runs the full `/triage` on each ticket and asks the owner its
questions. `/ticket-train-run <train>` acts on the recorded answers in a fresh session that knows only the state file.

**Creating a train ships nothing.** No code, no branches, no ticket transitions. Invoking `/ticket-train-run <train>`
is the owner's G3 approval for exactly the tickets in that queue, and for nothing else.

All state goes through the helper, never an inline edit: `.claude/state/trains/<train>.json` (gitignored), written
with `node .claude/scripts/train-state.mjs`. If Node is unavailable, say so and stop.

---

## Step 1: Validate inputs

- `<train>` is kebab-case. If `.claude/state/trains/<train>.json` exists, stop: a train is never overwritten (the
  helper's `create` refuses too).
- At least one ticket key; no duplicates in the list.
- For each other train file, run `node .claude/scripts/train-state.mjs summary <file>`. A listed ticket that is
  `pending`, `awaiting_answer`, `in_progress` or `blocked` there → stop and name the collision.

## Step 2: Light check per ticket

This is not `/triage`; that is the triage step's job, where questions can still be asked. It only keeps stale tickets
out of the queue. For each ticket, in the order given:

1. Ticket op **get** `<ticket>` (comments and links included). Not found or already closed → drop it and say why.
2. Check its 2–3 load-bearing claims against the code and the schema source named in `docs/agent/source-layout.md`:
   the files exist, the bug is still there.
3. Record:
   - `runtime_verifiable`: can `/verify` drive the changed behaviour locally against the real services with no
     human and no irreversible side effect (`docs/agent/verify-map.md`)? `/ship` won't merge a behaviour change
     without an observed verify, so a ticket that needs a human to verify goes to `excluded` (Step 4) with
     `unblock_by: "ship it attended"`.
   - `verify_how`: one sentence naming the entry point, route, query or screen and the expected before → after.
     Seed through the seed commands in `verify-map.md`, never a protected public endpoint. If measurement must come
     before design, say so.
   - `regression_test`: for a bug, where the guarding test belongs and the invariant it asserts; else `none`.
   - `notes`: scope boundaries, overlaps with sibling tickets in this train ("run after X; reconcile the shared
     constant once"), known couplings.
   - `constraints`: the boundary the run must respect, or `none`. Always record: a schema change (migration
     before the code that needs it; `/guard` first); a change to one of `<CRITICAL_SYSTEMS>` (which Critical
     Systems checks from `CLAUDE.kit.md` apply); a live customer-facing surface; a production env var (the run
     reports the variable name, never sets it). A hard boundary ("message change only") is recorded only when the
     owner set it.

## Step 3: Order the queue

Order by: (a) dependency and overlap chains; (b) migration before the code that depends on it; (c) highest value
first among independent tickets. Put a one-line `why_first` on the lead ticket if the order isn't obvious.

## Step 4: Run conditions

- **Peer review** is per ticket and decided at triage (`peer_review: run | skip`, default `skip`). Probe the engines
  now (`codex --version`, and the `/bteam` probe) and record `rules.adversarial`: `"B-Team + Codex"` or
  `"<engine> unavailable as of <date>"`. An outage never blocks the train; the run reports a single-engine pass as
  partial coverage.
- **Forbidden** (`rules.forbidden`, verbatim, at least these): "any action under G1, G2, G4, G5, G6, G7 or
  `<OWNER_KEPT_GATES>`"; "any Forbidden action in `CLAUDE.kit.md`"; "a test that sends to a live customer-facing
  surface or runs an irreversible side effect in `docs/agent/verify-map.md`"; "setting or changing a production
  environment variable or secret". Add anything the owner names, in the owner's words.
- **Pre-authorized** (`rules.pre_authorized`): only actions the owner names now, verbatim with the date. Default
  `[]`. An entry never widens a forbidden item; where they overlap, forbidden wins.
- **Excluded:** a ticket whose fix needs an owner decision (a product or copy call, a gated step, relaxing a safety
  check, a destructive production-data change) goes to `excluded`, never the queue: queueing it only buys a block
  later. Each entry: `{ "key", "reason", "unblock_by" }`.

## Step 5: Write the state file

Write the JSON to the scratch directory, then run (it creates `.claude/state/trains/` if needed):

```bash
node .claude/scripts/train-state.mjs create .claude/state/trains/<train>.json @<scratch>/<train>.json
```

```json
{
  "name": "<train>", "revision": 0, "created": "<YYYY-MM-DD>",
  "procedure": ".claude/commands/ticket-train-run.md",
  "triage_required": true, "triaged": null, "halt": null,
  "rules": {
    "sequential": true, "base_branch": "<MAIN_BRANCH>", "test_commands": "<TEST_COMMANDS, verbatim>",
    "verified_defects": "every verified S1-S4 defect on a ticket's path is fixed on that ticket; nothing is deferred",
    "peer_review": "per ticket: the entry's peer_review, set by /ticket-train-triage; default skip",
    "adversarial": "<recorded mode>", "forbidden": ["<verbatim>"], "pre_authorized": []
  },
  "queue": [
    {
      "key": "<ticket>", "state": "pending", "title": "<summary>", "why_first": "<lead ticket only>",
      "runtime_verifiable": true, "verify_how": "<plan>", "regression_test": "<test + invariant | none>",
      "notes": "<…>", "constraints": "<… | none>",
      "pr": null, "branch": null, "reason": null, "result": null, "peer_review": null,
      "triage": null, "contract": [], "contract_note": null, "threat_model": null,
      "questions": [], "decisions": [], "open_findings": [], "code_review": null, "blocked_work": null
    }
  ],
  "candidates": [], "unqueued_work": [], "excluded": []
}
```

- `/ticket-train-triage` writes `triage`, `contract`, `contract_note`, `threat_model`, `questions`, `decisions`,
  `peer_review` and `candidates`. Leave them empty here.
- `contract` holds the acceptance-and-proof rows, one object each: `id` (`C<digits>`), `class` (S1–S4),
  `invariant`, `paths`, `hostile_case`, `authority`, `proof`, `counterfactual`, `vector` (the independent pre-code
  vector `{ input, expected, rejects, source }`, `source` naming engine and date, or `null`) and `discharge`
  (`null` until the run writes `{ test, result, path_exercised, counterfactual_result }`).
- `contract_note: "no executable behavior"` marks a docs-only ticket. An empty `contract` with no note means
  **untriaged**: an audit over nothing passes trivially, so the helper refuses to start that ticket.
- `code_review` (written by the run) is `{ rounds, extra_round, redesign, end_state, self_review, dispositions[] }`.
  Each disposition is `{ round, finding, class, disposition }`, using post-op Step 1.5's disposition words.
- `open_findings` entries are `{ id, source, finding, class, resolved }`. `blocked_work` is the local-only checkpoint
  record (`/ticket-train-run`, "Preserve blocked work"). `unqueued_work` lists merge-blocker fixes the run made
  outside the queue.
- The helper enforces the rest: states `pending → awaiting_answer ⇄ pending → in_progress → done | needs_verify |
  blocked`, `blocked → pending` only through triage; contract rows, vectors, discharges, questions, decisions and
  findings are append-only; recorded `forbidden`, `pre_authorized` and `base_branch` never change.

## Step 6: Report

```
Train "<train>" created: N tickets queued, not yet triaged. Nothing shipped.
  1. <ticket> — <title> — <why here>
Excluded: <key — reason — unblock_by> | none
Peer review engines: <rules.adversarial>
Next: /clear, then /ticket-train-triage <train>   (full triage per ticket; then its questions, one at a time)
Then: /clear, then /ticket-train-run <train>      (refuses to start until triage is recorded)
Progress at any time: /ticket-train-status <train>
Owner action: none
```

## Rules

- Never overwrite a train file, and never queue a closed ticket or one another train holds.
- The only writes are the state file and, if the owner asks, one "queued in train `<train>`" comment per ticket.
- Everything the run needs must be in the JSON: it starts with no other context.
- Codex: same steps. It writes the file through the same helper.
