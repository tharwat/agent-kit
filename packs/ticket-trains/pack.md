<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Pack: ticket-trains

Queue several triaged tickets and run them unattended, one at a time: **create → triage → run**, with
`/ticket-train-status` at any time. State lives at `.claude/state/trains/<train>.json` and is written only through
`node .claude/scripts/train-state.mjs` (locked, revisioned, validated, atomic).

## Pack facts

None. The train records its rules (`base_branch`, `test_commands`, `forbidden`, `pre_authorized`) from Project facts
and the owner's words at create time.

## /triage

Rows for "Workflow after triage":

| When | Command | Purpose |
|---|---|---|
| Several tickets planned as a batch | `/ticket-train-create <train> <ticket> …` | Light premise check and ordering into a self-contained queue. Ships nothing |
| Before the run | `/ticket-train-triage <train>` | The full `/triage` per ticket, then its questions to the owner one at a time, each option with a pro and a con. Answers are recorded verbatim; engineering forks get a recorded default. Ships nothing |
| Ready to execute | `/ticket-train-run <train>` | Runs `/operate` → `/post-op` → `/peer-review` (when the ticket's `peer_review` is `run`) → `/ship` per ticket, sequentially and unattended, on the recorded decisions. Refuses an untriaged train. Invoking it is G3 for exactly that queue |
| Any time | `/ticket-train-status [<train>]` | Read-only progress, including open questions. Safe mid-run |

The run starts with no context, so the verify plan, boundaries and the answer to every question triage can raise
must be in the state file first. A question that still surfaces mid-run blocks only that ticket and hands it back to
`/ticket-train-triage`.

When `/triage` runs inside `/ticket-train-triage`, the train also needs, per ticket: the contract rows verbatim with
their class, the vectors with provenance (engine and date), the threat-model line, and the blast-radius file list.
`/ticket-train-triage` Step 2 copies them from `.claude/state/<ticket>/triage.md`.

## Markers

Comment-as-record markers this pack adds to `docs/workflow/ticket-ops.md` §3. A record is a comment whose first line
starts with the marker; check with ticket op **get** before writing, so a re-run doesn't write it twice.

| Marker (first line) | Written by | Read by |
|---|---|---|
| `TRAIN TRIAGE (<train>): <ticket> — <date>` | `/ticket-train-triage` (one per triaged ticket) | `/ticket-train-run` (re-validation baseline) |
| `TRAIN TRIAGE DECISION (<train>): <ticket>` | `/ticket-train-triage` (an answer that changed scope, verbatim) | `/ticket-train-run`, the owner |
| `TRAIN RESULT (<train>): <ticket> — <state>` | `/ticket-train-run` (one per finished ticket) | the owner, `/release` |
