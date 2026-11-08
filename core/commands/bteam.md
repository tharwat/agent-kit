---
description: Zero-context, review-only Claude reviewer (B-Team) of a frozen, hashed snapshot; also the pre-code test-contract designer.
argument-hint: "[ticket] | test-contract <ticket>"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# B-Team

Invoked with: `/bteam [ticket]`, or `/bteam test-contract <ticket>` (pre-code mode; `/peer-review test-contract`
runs it).

## Purpose

A hostile, zero-context Claude reviewer. Its job is to find how this change breaks production, not what could be
nicer. It is one of the two engines of `/peer-review` (the other is `/codex-review`).

- **Review-only.** It reports; it never edits. The implementer repairs through `/peer-review` Step 6.
- **It confirms the work; it doesn't repair it.** A finding from a zero-context reviewer was visible on the surface
  of the diff, so it is also a signal about the `/operate` pass that produced it.
- **Hash-bound.** It reviews only the snapshot `/peer-review` Step 1 froze, and its output must attest that hash.
- **Standalone runs are fine** as a second opinion. They still need a frozen snapshot (run `/peer-review` Step 1
  first), and they are **not a peer-review verdict**: no `peer-review.json` is written and `/ship` has nothing to
  stop on. Say which you ran.
- It doesn't notify. `/peer-review` reports.

---

## Pre-code test-contract mode

Runs during `/triage`, before any code or test exists. It designs test vectors; it never sees a patch, writes test
code, approves the ticket or stands in for a post-work review.

1. Make an artifact-only directory `<scratch>/<ticket>-precode/` holding `intent.md` (ticket key and intent),
   `code-map.md` (the baseline paths, producers, consumers and siblings from triage) and `contract.md` (the draft
   contract). No diff, no proposed implementation.
2. Write `brief.txt` there:

   ```text
   READ-ONLY TEST DESIGN. Do not propose an implementation and do not write test code. Use only intent.md,
   code-map.md and contract.md in the current directory. For each C<n> row in contract.md, name the exact hostile
   input or state, the observable result a test must assert, and the named bad behaviour the test must reject.
   Say which rows you cannot design a vector for, and why. End with a line containing exactly VECTORS_COMPLETE.
   ```
3. Dispatch it as in Step 3 below, with the output in `<scratch>/<ticket>-precode-vectors.txt`. Output whose last
   non-blank line isn't `VECTORS_COMPLETE` is unavailable.
4. Return this table. **Provenance is required**: it is what separates an independent vector from one the
   implementer wrote for themselves.

| Contract ID | Exact input/state | Expected observable result | Named bad behaviour rejected | Engine / date |
|---|---|---|---|---|
| C1 | ... | ... | ... | `claude -p` headless, <date> |

Triage verifies each vector against the baseline and folds the usable ones into the row's independent-vector
cell. `/operate` may add fixtures or a seam, but never weakens the input, the expected result or the named bad
behaviour. **If the designer is unavailable,** record why; those cells read `not run`. Never put a self-designed
vector in that column.

---

## Step 1: Inputs

You need: the ticket key and one-line intent, the contract's threat-model line, and the snapshot directory from
`/peer-review` Step 1b (`base.txt`, `patch.diff`, `contract.md`) with its snapshot hash. If any is missing, or
`/peer-review` Step 1c says the snapshot no longer matches, stop and re-freeze there. Never make a diff here.

## Step 2: Write the brief

Save this to `<scratch>/<ticket>-bteam-brief.txt`, filling the angle-bracket values. Consumer surfaces come from
`docs/agent/source-layout.md`; the two critical lines from Project facts. `/codex-review` sends the same brief.

```text
REVIEW-ONLY. You are a hostile code reviewer with no context on this project. Do not edit files, produce patches
or implement fixes. Review only patch.diff (the frozen change) and contract.md (its acceptance-and-proof contract)
in the current directory. Do not look for a working tree.

Ticket: <ticket> — <one-line intent>
Threat model: <threat-model line>
Consumer surfaces: <list>
Critical domain: <CRITICAL_DOMAIN>
Critical systems: <CRITICAL_SYSTEMS>

Find how this change breaks production: silent failures, wrong results, corrupted data, bypassed guards. Not style,
not missing features. Use these lenses, in order:

1. Integration contract. For every field added, renamed or removed in a response, event or message: does a
   consumer read it by key and now silently get nothing? For every external field read: is the name and shape
   right, or is it a silent undefined?
2. Sibling path. Where a guard, validation or sanitizer is added on one path, does every other path reaching the
   same downstream function, and every other writer of the same state (jobs, retries, admin routes, webhooks),
   carry it?
3. Schema and data shape. Does every table, column and field named exist, with that type and nullability? Is a
   single-row read used on a query that can return many? Does each return shape match what its caller parses? For
   a proposed new column, say "verify it does not already exist".
4. Fail-open and idempotency. A catch that swallows where it must throw; a job that reports success with nothing
   done; an idempotency record written before the side effect; a failure answered with success to a retrying
   caller; an idempotency read that never checks its own error.
5. Race and double-fire. Concurrent requests, webhook replays, two results arriving together: read-then-write
   windows, a second write overwriting the first, a constraint violation outside its handler rolling back too much.
6. Test coverage. Does every new branch have a test on the exact path, including failure, rollback and
   idempotent-skip paths? Do test doubles match the real module's exports and return shapes? A test of a
   similarly named field is not coverage.
7. Backward compatibility. Is any existing field, URL, status code, signature or required/optional flag changed or
   removed? Name every consumer that breaks.
8. Critical domain. Does the change produce a wrong result in the critical domain above, in either direction
   (false positive or false negative)? Does it add or move a path into a critical system without the guard that
   path needs?
<9 and up: pack lenses, if any>

Output exactly this shape:
- First line: REVIEW_HASH: <snapshot hash>
- One status line per lens, in order: "<n>) Clean — <one line>" or "<n>) Finding — <one line>".
- After the status lines, one block per blocking finding:
  FINDING:
  Lens: <n>
  Severity: <CRITICAL|MAJOR|MINOR>
  Basis: <C<n>|CHANGED_PATH|SAFETY_EXCEPTION>
  Path: <exact changed runtime path, file:line>
  Reproduction: <exact input, state or command>
  Observed: <the wrong result>
  Required: <the contract requirement or the safe outcome>
- A finding may block only if it is (a) a violated C<n> row in contract.md, (b) a demonstrated wrong result on a
  changed runtime path (CHANGED_PATH), or (c) a concrete safety, data-integrity or release-safety exception
  (SAFETY_EXCEPTION, CRITICAL only). Anything needing an input outside the threat model is not a finding.
- Everything else (improvements, theoretical edge cases, test ideas, unrelated concerns) is one line:
  "OBSERVATION: <text>". Observations never block and never create a ticket.
- A lens with no blocking finding is Clean, even if it has observations.
- Last line: REVIEW_COMPLETE
```

Packs may add lenses here: see the section for this command in each installed `.claude/packs/*.md`. Number them from 9 and pass the total to
`check-review --lenses`.

## Step 3: Dispatch, then check the output

**Preferred: headless Claude in an artifact-only directory**, so the reviewer has no session context and nothing but
the artifact to read. `<h12>` is the first 12 characters of the snapshot hash.

```bash
D=<scratch>/<ticket>-bteam-<h12>
mkdir -p "$D"
cp <scratch>/<ticket>-snapshot/patch.diff <scratch>/<ticket>-snapshot/contract.md "$D/"
cp <scratch>/<ticket>-bteam-brief.txt "$D/brief.txt"
( cd "$D" && claude -p --no-session-persistence --permission-mode plan --output-format text < brief.txt ) \
  > <scratch>/<ticket>-<h12>-bteam.txt 2> <scratch>/<ticket>-<h12>-bteam.stderr
node .claude/scripts/kit-tools.mjs check-review --file <scratch>/<ticket>-<h12>-bteam.txt --hash <snapshot hash> \
  --lenses <lens count> --contract <scratch>/<ticket>-snapshot/contract.md
```

- Allow at least 15 minutes. If your shell tool caps a foreground command below that, run it in the background and
  apply `/codex-review`'s stall rule: poll the output file, not the process.
- A nonzero exit is `UNAVAILABLE — <last line of the .stderr file>`.
- `check-review` prints `CLEAN …` or `FINDINGS …`, or exits 1 with `UNAVAILABLE: <reason>`. Missing hash, a missing
  lens status, a malformed finding or no `REVIEW_COMPLETE` is `UNAVAILABLE`, never clean.
- Then run `/peer-review` Step 1c. A changed snapshot voids the result.

**Fallback: an in-session subagent**, only when the `claude` CLI is missing or fails before reviewing. Spawn a
fresh subagent with no session context. Its prompt is the brief, plus: "The files are `$D/patch.diff` and
`$D/contract.md`; read nothing else. Your final message is the review." Save its final message verbatim to the same
findings file and run the same `check-review`. Record it as `B-Team (in-session subagent; claude CLI unavailable:
<why>)`. Codex has no subagent: there, B-Team is `UNAVAILABLE — claude CLI not found`.

## Step 4: Verify every finding

Findings are claims. Verify every `FINDING:` block, at every severity, before presenting it.

| Lens | How to verify |
|---|---|
| Integration contract | Grep each consumer surface for the field by key. Confirm the diff really removed or renamed it. For an external field, check a real payload or live docs seen this session |
| Sibling path | Read the named `file:line`. Confirm the same pattern exists and the path is reachable (not dead code, not behind an off flag). Grep every writer of the same state |
| Schema and data shape | Read the schema source (`docs/agent/source-layout.md`): the create and every later alter for that table. "Column missing": confirm it's absent in the latest state. "Add column": confirm it doesn't exist under any name, else REJECTED with the real name. Return shapes: compare with an existing production consumer of a similar call, not with reasoning |
| Fail-open and idempotency | Read the flow. Confirm the order of the idempotency write and the side-effect commit, and what a retry hits |
| Race and double-fire | Trace what each branch commits and which handler catches what, at which scope. Confirm the window is reachable: no upstream lock or unique constraint closes it first |
| Test coverage | Grep the tests for the assertion. Confirm no indirectly named test covers it. For a double, read the real module's exports and the calls made |
| Backward compatibility | Read the response builder before and after. Grep the consumers |
| Critical domain | Trace the data from the field to the decision. Confirm the wrong outcome is what the code does, not a hypothetical |

### Prior-art gate (before anything is VERIFIED)

The reviewer can't know what the codebase already handles. "Structurally real" isn't enough. Answer all three:

1. **Already guarded here?** Re-read the surrounding code, not just the flagged line.
2. **Already accepted?** Check code comments, reused helpers, `git log` / `git blame` on the lines, and the sibling
   or parent ticket for a documented decision.
3. **Introduced by this diff, or pre-existing?** Pre-existing isn't out of scope, but it's labelled and kept apart
   from regressions.

Guarded or accepted → `ALREADY-RESOLVED`, citing the `file:line` or ticket. Disproved → `REJECTED`, with the
evidence. Ambiguous without runtime data → `NEEDS-OWNER`, with the ambiguity stated. Survived → `VERIFIED`, labelled
`[introduced by this diff]` or `[pre-existing]`, with a class: S1–S4, or `noted` (status `NOTED`) below the bar
(post-op Step 1.5 round rule 2). Never present an unverified or already-resolved finding as actionable.

## Step 5: Present

```
B-Team (<headless | in-session subagent>): <CLEAN | FINDINGS | UNAVAILABLE — why> — <h12>
Design: ok | redesign recommended — <the simpler shape>   (when several findings share one mechanism; post-op Step 1.5 round rule 10)

| Finding | Class | Evidence | Status | Disposition |
|---------|-------|----------|--------|-------------|
| [MAJOR] ... | S1 | file:line shows … | VERIFIED [introduced by this diff] | Fix |
| [MINOR] ... | noted | file:line shows … | NOTED | Tracker |

Rejected / already-resolved: | Finding | Outcome | Evidence |
Observations: <each, non-blocking>
```

Through `/peer-review`, hand this to it; it combines both engines and resolves in its Step 6. Standalone, the
disposition is **Fix** for S1–S4 and **Noted** otherwise. A verified defect on this ticket's path is fixed on this
ticket, never deferred. A later rejection needs new evidence, never "this won't happen".

---

## Rules

- The reviewer gets no session context: only the artifact and the brief.
- Never make or change a snapshot or contract here.
- Missing or partial output is `UNAVAILABLE`, never clean.
- Verify every finding, every severity, through the prior-art gate.
- A standalone run is not a peer-review verdict. Say which you ran.
- Never notify; `/peer-review` reports.
