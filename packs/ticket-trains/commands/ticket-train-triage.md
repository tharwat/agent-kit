---
description: Run the full /triage on every queued ticket of a train, record each contract, then ask the owner the open questions one at a time. Ships nothing.
argument-hint: "<train>"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# Ticket train: triage

Invoked as `/ticket-train-triage <train>`. Run it in a fresh session (`/clear` first).

The middle step of **create → triage → run**. It runs the full `/triage` on each queued ticket while the owner can
still answer, turns every open point into a recorded question, and asks them one at a time. The run then treats the
answers as facts. An unattended run that hits a question can only block, so questions are settled here.

**Triage ships nothing.** No branch, no code, no merge, no ticket transition. Its writes are the state file, ticket
comments, and (per `/triage`'s own rule) ticket op **create** for an independent adjacent gap.
`/ticket-train-run <train>` stays the only ship approval.

State: `.claude/state/trains/<train>.json`, changed only through the helper:

```bash
node .claude/scripts/train-state.mjs summary .claude/state/trains/<train>.json            # read, with revision
node .claude/scripts/train-state.mjs update .claude/state/trains/<train>.json <ticket|train> <revision> '<json patch>'
```

Read the revision just before each update. A stale revision, an invalid transition or a rewrite of recorded evidence
is refused: re-read and retry, never work around it. Long patches go in a scratch file passed as `@<path>`. If Node
is unavailable, say so and stop.

---

## Step 1: Load the train and choose the work

Read the summary. Missing file → stop and list the trains in `.claude/state/trains/`. Then, in queue order:

| Ticket | Goes to |
|---|---|
| `pending`, no `triage`, or `triage_gaps` not empty | Full triage (Step 2) |
| `pending`, triaged, but a commit on `origin/<MAIN_BRANCH>` newer than `triage.date` touched a file in `triage.files` (`git log --since=<date> origin/<MAIN_BRANCH> -- <files>`) | Re-validate: `/triage` Steps 2–4 only; a new comment and question only if a finding changed |
| `awaiting_answer`, or `blocked` with a reason starting `question` | Step 3 |
| `blocked`, reason starting `own gate failing` (the circuit breaker) | Step 3, question `nc1` |
| any ticket, while the train's `halt` is set | Step 3, question `halt<n>` on the ticket that set it |
| `done`, `needs_verify`, other `blocked` | Untouched |

Print the plan (full triage / re-validate / waiting on the owner), then continue without asking. Steps 1–2 are
unattended.

## Step 2: Full triage per ticket

Run `/triage <ticket>` **in full**, Steps 1–6: premise reproduced, mandatory sweeps, blast radius, the
acceptance-and-proof contract with its threat-model line, the independent pre-code pass (Step 4.7) and the hand-off
(which writes `.claude/state/<ticket>/triage.md`). Then:

1. **Comment.** Ticket op **comment** `<ticket>`, first line `TRAIN TRIAGE (<train>): <ticket> — <date>`, then
   the summary, the questions raised and the contract's row IDs. It tells the run's re-validation apart from this
   triage.
2. **Record**, in one update to the ticket:
   - `triage`: `{ "date", "status": "DONE|DONE_WITH_CONCERNS|BLOCKED|NEEDS_CONTEXT", "premise": "Reproduces|Does not reproduce|n/a (feature)", "files": [<blast-radius files>], "summary": "<two lines: the fix, and what the sweeps changed about scope>" }`.
   - `contract`: every row, copied **verbatim** from `.claude/state/<ticket>/triage.md` (the tracker's copy may have
     lost characters), with its class, `vector` from Step 4.7 (`source` = engine and date) or `null`, and
     `discharge: null`. `threat_model`: the contract's one line.
   - Refresh `verify_how`, `regression_test`, `notes` and `constraints` from what the full triage found.
3. **Never an empty contract on executable work.** If `/triage` produced none, record `status: "NEEDS_CONTEXT"` and
   leave `contract` empty: the run refuses to start it. Only a docs- or copy-only ticket records
   `contract_note: "no executable behavior"`.
4. **Vectors are immutable.** A re-triage may add rows and may add a vector to a row that has none. It never
   rewrites or removes a recorded row, vector or discharge; a change is a new row (the helper refuses anything else).
   Never fill a vector you designed yourself, and never write a partial one.

Write after **every** ticket, before the next, so a crash loses one triage, not the pass.

### Open points become questions

Every ⚠️ conflict, `BLOCKED` status, premise that doesn't reproduce, and fork where the run would otherwise "decide
from existing patterns" becomes one entry in `questions`:

```json
{ "id": "q1", "asked": "<date>", "question": "<one concrete sentence>", "context": "<file:line or query result>",
  "options": ["<A>", "<B>"], "recommendation": "<which, and why>", "blocking": true, "default": null, "answer": null }
```

Classify `blocking` honestly; it is the whole design.

- **Blocking, no default:** an owner decision. These classes always are:
  - a product, copy or customer-facing behaviour call;
  - an Owner-Kept Gate (G1–G7, `<OWNER_KEPT_GATES>`), including relaxing or removing a safety check (G7);
  - a destructive production-data or schema change (G2, G5);
  - spend or an external action outside `rules.pre_authorized`;
  - anything on a live publish, send or other irreversible surface;
  - a premise that doesn't reproduce, or a ticket that looks already implemented ("drop it, or re-scope to the
    remaining half?").
- **Not owner decisions:** a change to one of `<CRITICAL_SYSTEMS>`. Put the Critical Systems checks in the contract
  and recommend `peer_review: run`.
- **Non-blocking, with a default:** an engineering choice with a defensible default (which helper, where a test
  lives, whether two adjacent sibling sites join). The default is exactly what the run will do, written as an
  instruction. If you wouldn't stand behind a default, the question is blocking.

A ticket with an unanswered blocking question moves to `awaiting_answer`; otherwise it stays `pending`.

**Peer review, one question per executable ticket:** `pr1`, non-blocking, default `skip`, options `run` / `skip`.
Recommend `run` when a miss is expensive: one of `<CRITICAL_SYSTEMS>`, `<CRITICAL_DOMAIN>` logic, a money or data
write path, a security guard. A docs-only ticket gets `peer_review: "skip"` and no question.

**Adjacent gaps.** A defect or edge case on the ticket's execution path joins its contract now; it is never a
candidate. Only an independent capability is filed (ticket op **create**, labels per `.claude/rules/ticket-ops.md`)
and listed in `candidates` as `{ "key", "title", "after", "why" }`. The queue doesn't grow on its own.

## Step 3: Ask the owner, one question at a time

Never print the list. Ask **one question per message** (Claude: `AskUserQuestion`, one per call; Codex: one plain
message), wait, record the answer (Step 4), then ask the next. Order: blocking questions in queue order, then
non-blocking ones, then every `pr1`, then candidates.

- Plain language, in product terms. No file paths, line numbers or symbol names; they are in the triage comment and
  the state file.
- **Why:** at most two plain sentences on what is at stake.
- **Every option gets a pro and a con**, your recommendation included. Say which you recommend and why in one line.
- End with `A, B, or "your call".` "Your call" records the recommendation's text, `by: "owner"`.
- If the owner stops answering, the file keeps the rest; a later run of this command resumes at the next one.

```
QUESTION 1 of N — <ticket>

<one sentence>

Why: <at most two sentences>

A) <option>  (recommended)
   + <pro>
   − <con>
B) <option>
   + <pro>
   − <con>

A, B, or "your call".
```

Questions the run raises, asked the same way:

| ID | Raised when | Options (each with a pro and a con) |
|---|---|---|
| `nc1` | the circuit breaker: an own gate the run couldn't make pass (show its output and the kept branch) | **continue** on the kept work; **re-scope** the notes or contract first; **drop** (stays blocked) |
| `cr-e<n>` | post-op ended `escalate` (round rule 6). Name the cause: an S1–S3 finding in or after the last round, an open needs-owner finding, or a redesign needing a gate | those the escalation carries, typically **accept and ship** / **one more round on the fix** / **revert and re-scope** |
| `pr-f<n>` | `/peer-review` left a verified finding unresolved, or a `NEEDS-OWNER` one (show the finding, its evidence, the snapshot hash) | **new approach** / **re-scope** keeping every unresolved row / **stop** (stays blocked) |
| `halt<n>` | a merge broke `<MAIN_BRANCH>` and the run stopped. Before asking, check the fix-forward ticket merged and the deploy is live (`/verify` post-merge half) | **resume** the train / **stay halted** |

## Step 4: Record each answer as it arrives

1. Set the question's `answer` to the owner's words and append `{ "id", "decision": "<verbatim>", "by": "owner",
   "date" }` to `decisions`, in the same update. A decision is a quote, never a paraphrase.
2. If it changes scope, verification or a boundary, update `notes`, `verify_how` or `constraints` in that update.
3. A `pr1` answer sets `peer_review` to `run` or `skip`.
4. **Re-entry.** A ticket returns to `pending` only when no blocking question is open (the helper enforces it):
   - `awaiting_answer`, or blocked on a `question q<n>`: back to `pending`.
   - `nc1` **continue** or **re-scope**: `pending`, keeping `blocked_work` and `open_findings`; the run resumes on the
     checkpoint and must still fix every open finding. **drop**: stays `blocked`, reason
     `dropped by owner after circuit breaker — <why>`.
   - `cr-e<n>`: `pending`; the run applies the answer on the checkpoint and continues the round count.
   - `pr-f<n>` (unresolved peer finding): `pending` only with an owner-chosen new approach or re-scope that keeps
     every unresolved contract row and every open finding. Never erase the evidence (`open_findings`,
     `blocked_work`, `.claude/state/<ticket>/peer-review.json`), never relabel a finding to pass it, never mark the
     ticket done. **stop** leaves it `blocked` with the decision recorded.
   - `halt<n>` **resume**: train update `{"halt": null}`.
   - A dropped ticket: `blocked`, reason `dropped by owner at triage — <why>`.
5. A candidate the owner queues: append a create-style entry at the stated position (train update with the whole
   `queue`; it must arrive `pending`), after checking no other train holds it, then give it a full Step 2 triage.
6. For each answer that changed scope, ticket op **comment** `<ticket>`, first line
   `TRAIN TRIAGE DECISION (<train>): <ticket>`, then the answer verbatim.

## Step 5: Report

When every `pending` ticket has a triage record with no gaps and no blocking question is open, train update
`{"triaged": "<date>"}`. The run refuses to start a `triage_required` train without it.

```
TRAIN TRIAGE: <train> (<date>)
  <ticket>  pending          triaged — <summary>   decisions N · defaults N · peer review run|skip
  <ticket>  awaiting_answer  q1 blocking, unanswered — <question>
  <ticket>  blocked          dropped by owner — <why>
Candidates not queued: <key (after <ticket>) — why> | none
Ready to run: yes | no — <what is missing>
Next: /clear, then /ticket-train-run <train>
Owner action: none | answer <N> waiting questions: /ticket-train-triage <train>
```

## Rules

- **Triage only.** No branch, implementation, merge or transition.
- **Every question carries a recommendation, and every default is a commitment.**
- **Never mark an owner decision non-blocking to keep the train unattended.** A run that finds a blocking question
  settled by a default stops the train: the file is mis-built (the helper also refuses that write).
- **Verbatim answers.** The owner's words are the decision.
- **Re-validation isn't re-triage.** Only a changed finding earns a new comment and a new question.
- Use ticket ops only; never call a tracker tool by name.
