---
description: Check a ticket against the real code before work starts, and write its acceptance-and-proof contract.
argument-hint: "[<ticket>]"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# Triage

Invoked as `/triage [<ticket>]`.

Triage checks a ticket against the current code **before implementation**. It finds stale assumptions, work that's
already done and the fix's blast radius, and it writes the binding contract that `/operate` discharges. It is
analysis only: never start implementing.

---

## Step 1: Establish scope

**Ticket key.** Use the argument. With no argument, derive the key from the branch name
(`<BRANCH_PREFIX><ticket-lowercase>-<slug>`): uppercase the `<TICKET_PREFIX>-<digits>` part. If no key can be
derived, stop with `NEEDS_CONTEXT` and ask for it. Never guess a key (`docs/workflow/ticket-ops.md` §1).

**Fetch.** Ticket op **get** `<ticket>` (comments and links included). Extract:
- title, description, acceptance criteria, type, status, labels, priority;
- every referenced file path, column, endpoint, config key or package;
- **every comment**: decisions, scope changes and deferrals often live there, not in the body;
- every linked ticket and subtask.

Then ticket op **get** each linked ticket and note its status and relation: blocker, dependency, gap, subtask.

**Epic constraints.** If the ticket has a parent or epic, ticket op **get** it (comments included). List every
constraint agreed there: decisions, limits, shapes, things ruled out. Each child ticket must meet them. A constraint
this ticket would break is a conflict (Step 4).

**Lessons.** Read the sections of `docs/agent/lessons.md` and `docs/agent/defect-classes.md` that match the areas
this ticket touches.

---

## Step 2: Verify every claim the ticket makes

The code map is `docs/agent/source-layout.md`: where API routes, client and consumer surfaces, schema, tests and
user-facing copy live. For every file, column, endpoint or pattern the ticket names, confirm it with Glob and
Grep. Don't assume.

- **Files:** do they exist at the stated path? If not, what replaced them?
- **Schema:** check the schema source named in `source-layout.md`. The schema is the source of truth, not the
  ticket.
- **Endpoints:** confirm method, path and response shape in the routes and handlers.
- **Consumer surfaces:** check each consumer the source layout lists.

## Step 3: Check for prior implementation

```bash
git log --all --oneline --grep="<ticket>"
```

Grep for every identifier the ticket introduces (new columns, functions, routes). If any are present, part of the
ticket may be done already.

## Step 3.5: Reproduce the premise (mandatory)

A ticket's premise is a claim, not a fact. A "fix" for a non-defect is often harmful.

- Trace the exact code path or data the ticket blames. Does the symptom occur?
- For "X and Y disagree": build the concrete input that makes them disagree, then check whether any real producer
  ever creates it.
- For "X is broken or missing": find the input that triggers it and confirm it reaches that state.

State one, with `file:line` evidence: **Reproduces** (proceed) or **Does not reproduce** (explain what really
happens; this is a finding, not a failure). Never carry a premise forward unverified.

---

## Step 4: Reconcile

Compare intent with reality and sort each item:

- **Matches**: nothing to flag.
- **Outdated**: the ticket names something that changed. Use the current version.
- **Already done**: it exists. Skip it.
- **Conflicts**: the ticket contradicts code, a project rule or an epic constraint. Take the safer reading and
  record why. Only a product decision or an Owner-Kept Gate makes it `BLOCKED`.

### Negative-space prompt

If the ticket touches any of these, list the sibling paths that must be checked before `/post-op`. Also read
`docs/agent/sibling-paths.md` for this project's known pairs.

| Ticket touches | Also check |
|---|---|
| A guard, sanitizer or validation | Every other path that reaches the same downstream function. If one path is guarded, all must be |
| An API response shape | Every consumer surface that reads it. Will one break silently? |
| A query expecting one row | Can it ever return more than one (duplicates, concurrent writes)? |
| An outcome or status string | Every place that branches on it. Is every value handled? |
| A test double (mock, stub, fake) | The real module's interface. Does the double match it? |
| Removing or renaming a symbol (type, constant, function, column, outcome string) | **Every consumer**, not just the producer (Step 4.5 A) |
| A list, enum, constant or validation rule | **Every home of that fact** (Step 4.5 B) |
| New or moved shared code | The target module's import weight, import cycles, a lighter precedent (Step 4.5 D) |
| New logic reading a source field (column, API field, JSON attribute, generated text) | The null / empty / absent / zero-rows case. Does the branch skip silently (fail-open), fall to a wrong default, or throw? Confirm nullability in the schema source |
| One of `<CRITICAL_SYSTEMS>` | The four stricter checks in `CLAUDE.kit.md` (Critical Systems), carried into the contract |

Packs may add checks here: see the section for this command in each installed `.claude/packs/*.md`.

### Mandatory sweeps

These run every time, not only when a trigger fires. A sweep skipped here comes back mid-review as an
adjacent-gap finding, and each one costs a capped review round.

- **Consumer sweep, exhaustive.** Grep every consumer of each touched function, column, endpoint or pattern across
  the source tree, including those the ticket doesn't name. Give each a disposition: covered by this fix, or
  out of scope with a reason. "The ticket only mentions X" is why the sweep exists.
- **Pattern-family sweep**, when the fix touches a regex, matcher, classifier or validation pattern. List every
  sibling pattern in the same file or family and **run** the ticket's defect class against each: case variants,
  curly vs straight quotes, accented vs unaccented forms, emoji and variation selectors, whitespace and newline
  splits, both match directions. Describe the match-set change against `origin/<MAIN_BRANCH>` before recommending
  an approach. A broken pattern's accidental coverage is live behaviour.
- **Adjacent gaps are decided now.** Anything the sweeps find that shares the ticket's execution path, invariant,
  safety outcome or acceptance criterion goes into this ticket's contract. It is a condition of finishing safely,
  not scope creep. Ticket op **create** a separate ticket only for an independent capability with no dependency on
  the behaviour being changed, never to defer a verified defect or a required edge case.

---

## Step 4.5: Blast radius of the fix (before recommending an approach)

Steps 1–4 check the ticket. This step checks the fix you're about to recommend. Don't call a change "safe",
"harmless", "trivial" or "minimal" until it is done and every consumer is accounted for. Checking only the
producer ("nothing writes this field") while missing the consumers is the classic miss.

**A. Symbol impact map.** For each symbol the fix adds, removes, renames or reshapes (type, constant, enum,
function signature, column, endpoint, outcome string):
1. `grep -rn "<symbol>"` across code, tests and docs.
2. Mark each hit as producer or consumer.
3. A removal, rename or shape change isn't safe until every consumer is listed and handled.

**B. Same fact, many homes.** When the change touches a list, enum, constant, validation rule or label, list every
place that fact lives: static type, runtime constant, validation schema, database constraint or enum, each consumer
surface, user-facing copy, tests, docs. Each one is updated or explicitly out of scope.

**C. Type-system ripple.** If the language has static types and the change alters a type or a value's type, check:
- cast sites, especially where a value becomes read-only or immutable;
- membership checks on values that aren't narrowed;
- exhaustive switches or match arms that must gain or lose a case;
- assignments and spreads into mutable-typed parameters.

Packs may add checks here: see the section for this command in each installed `.claude/packs/*.md`.

**D. Module placement.** Before choosing where shared code lives:
- Read the candidate module's top-level imports. Is it heavy (SDK clients, side effects at import)? Light consumers
  shouldn't have to pull it in.
- Check for an import cycle, direct or transitive.
- Prefer the lightest correct module, and name any standalone-module precedent.

---

## Step 4.6: Acceptance-and-proof contract (mandatory)

Turn Steps 1–4.5 into a finite contract that `/operate` must discharge before review. Add one row for **every**
acceptance criterion, safety gate, failure mode, epic constraint that applies, and in-scope sibling path.

| ID | Class | Invariant | Paths | Hostile case | Authority | Behavioral proof | Counterfactual | Independent vector | Discharge |
|---|---|---|---|---|---|---|---|---|---|
| C1 | S1–S4 | what must be true, or must never happen | exact producer, consumer and sibling runtime paths | malformed input, missing state, timeout, error response, race, unreadable state | the schema, payload, live doc, rule or code contract that sets the expected behaviour | the test seam, input and observable result that runs **this** path | the valid mutation or reversal that must make the proof fail | from Step 4.7, with engine and date | blank now; `/operate` fills it |

- **ID** is `C` followed by digits (`C1`, `C2`, …). The freeze step counts rows with `^\| *C[0-9]+ *\|`, so any
  other format reads as zero rows and the review refuses.
- **Class** is the severity class a breach would have: S1 data integrity, S2 auth and security, S3
  `<CRITICAL_DOMAIN>`, S4 the ticket's own behaviour. The contract is the boundary of S4: review fixes a finding
  on the ticket's behaviour only if it breaks a row or a pre-code vector, or the changed flow crashes or returns a
  wrong result on realistic input. A behaviour you want fixed in review must be a row here.
- **Discharge** is filled by `/operate`: the exact test or probe, its result, the path it ran, and the
  counterfactual's result. It cannot be blank at freeze.
- **Critical Systems.** A row that changes one of `<CRITICAL_SYSTEMS>` records why the change is needed and its
  risk, lists every consumer, and names the tests (including regressions) and the pre-merge verify.

**Threat model / out of scope (one line, mandatory).** Say what the change defends against and what it doesn't.
For example: "realistic inputs and honest mistakes; a deliberately obfuscating author is out of scope", or
"signed production payloads; forged unsigned webhooks are rejected by the existing signature check, not this
code". Reviewer and verifier briefs carry this line. A finding that needs input outside it is `noted`, never
must-fix.

**Proof rules.**
- The proof must run the named runtime path. A source scan, a test of a similarly named field, or a green full
  suite may supplement a proof but never discharges a row.
- For each external field, the authority is a real payload or current docs seen in this session.
- For each fail-closed guard, include the malformed or unreadable condition that must be rejected.

The contract goes intact to `/operate`, `/post-op` and `/peer-review`. `DONE` is unavailable while any row lacks a
hostile case, a proof plan or a counterfactual.

## Step 4.7: Independent pre-code test design (mandatory for executable work)

Before any production source or test changes, run `/peer-review test-contract <ticket>`. It runs a fresh,
read-only pass over the ticket intent, the baseline code map and the Step 4.6 contract. It sees no implementation
or patch. It returns adversarial vectors:

| Contract ID | Exact input or state | Expected observable result | Named bad behaviour it rejects | Engine / date |
|---|---|---|---|---|

- Check each vector against the baseline and fold every applicable one into its row's **Independent vector** cell,
  with the engine and date. Provenance is what makes a vector independent.
- **Never write a self-designed vector in that column.** Your own test plan belongs in **Behavioral proof**.
- `/operate` may add fixtures or a callable seam but may not weaken a vector's input, expected result or named
  bad behaviour to fit the code. A vector that must change is a contract amendment, recorded before the related
  production edit.
- If the pass fails, retry once. If it still fails, end `NEEDS_CONTEXT` and name the failure: executable work isn't
  triaged until its contract has survived this pass.
- Docs- or rules-only changes record `Pre-code test design: skipped — no executable behaviour`.
- **No test runner yet** (a pack's test-framework fact is `none`, or no `<TEST_COMMANDS>` line runs tests): design
  the vectors as usual. In **Behavioral proof**, name a plain Node or TypeScript script (`node:test` /
  `node:assert`) that `/operate` adds to `<TEST_COMMANDS>`. A row no such script can drive makes the ticket
  `BLOCKED — no test runner`; the owner action is "add a test runner".

This pass designs vectors only. It doesn't implement, waive the later reviews, or add a delivery stage. The
post-work `/peer-review` stays optional.

---

## Step 5: Output

```
TICKET ANALYSIS: <ticket> — <title>

✅ Matches current code:
  - <item>: <note>
⚠️ Outdated / adjusted:
  - <item>: ticket says X, code or schema has Y → use Y
❌ Already implemented:
  - <item>: exists at <file:line> → skip
⚠️ Conflicts:
  - <item>: ticket proposes X, conflicts with <rule / code / epic constraint>. Resolved: <safer reading, and why>
    (or: Needs owner — product decision / Owner-Kept Gate)
🧭 Epic constraints: <parent key>
  - <constraint> → met by row C<n> / not applicable because <reason>   (omit if no parent)
🔗 Linked tickets:
  - <key> (<status>): <blocker / dependency / gap / subtask>
⚠️ Sibling paths to cover:
  - <path>: <why>   (omit if no trigger fired)
🔎 Adjacent gaps (from the sweeps):
  - <gap> → in this contract / independent capability filed as <key>   (omit if none)
🔬 Premise: Reproduces / Does not reproduce — <what happens, file:line>
🎯 Fix blast radius:
  - Symbols: <symbol> — producers <…> / consumers <…> (all accounted for)
  - Same-fact homes: <each — updated or out of scope>
  - Type ripple: <affected sites, or none>
  - Module placement: <chosen module and why, or n/a>
  - Files this approach touches: <list>
🧪 Test approach: existing patterns at <path>; new tests <yes/no + what>
🧾 Acceptance-and-proof contract: <the Step 4.6 table>
  Threat model / out of scope: <one line>
🧨 Pre-code vectors: <the Step 4.7 table, or: skipped — no executable behaviour>
📋 Full scope: <every acceptance criterion and in-scope finding to implement>
```

## Checklist

- [ ] Read every comment on the ticket, its linked tickets and its parent; listed the epic constraints
- [ ] Verified every file, column and endpoint the ticket names, against the schema source of truth
- [ ] Checked git history for prior implementation
- [ ] Reproduced the premise, with `file:line` evidence
- [ ] Resolved each conflict (safer reading recorded) or flagged it as a product decision or Owner-Kept Gate
- [ ] Ran the consumer sweep, and the pattern-family sweep if a matcher changed; every adjacent gap has a disposition
- [ ] Built the symbol impact map and the same-fact homes list; checked null / empty / absent / zero-rows inputs
- [ ] Checked type ripple and module placement where they apply
- [ ] Every contract row has an ID `C<digits>`, a class, a hostile case, a proof plan and a counterfactual, plus the
      threat-model line
- [ ] Ran `/peer-review test-contract` (executable work) and folded in its vectors with provenance
- [ ] Completed the Step 6 hand-off

---

## Step 6: Hand-off (mandatory, before any completion status)

The owner clears the context between `/triage` and `/operate`. Everything `/operate` needs must be saved before you
state a status:

1. **Ticket.** Ticket op **comment** `<ticket>` with the TICKET ANALYSIS and contract (first line
   `TICKET ANALYSIS: <ticket> — <title>`). Ticket op **comment** `<ticket>` with the vectors (first line
   `Pre-code vectors: <ticket>`). For each linked ticket triage decided something for, ticket op **comment** on it
   with that constraint.
2. **Exact copy.** Write `.claude/state/<ticket>/triage.md` (gitignored) with the final design decisions, every
   contract row and every vector **verbatim**, plus the comment ids. A tracker's renderer can drop characters, so
   this file, not the comment, is what `/operate` reads.

End the report with `Context: ready to /clear`. Never ask the owner whether clearing is safe.

## Rules

- Triage only. Don't implement.
- The contract is the deliverable, not a summary. A row without an exact runtime path, a hostile case and a
  counterfactual isn't a row. Rows are engineering facts, not owner choices.
- A safety condition or edge case on the ticket's execution path is neither an optional adjacent gap nor an owner
  question. Add it to the contract and implement it in this ticket.
- Owner decisions are only for product, strategy, safety-limit, destructive-operation or authority questions.
- **Questions to the owner:** one at a time, in plain language, every option with a pro and a con, including your
  recommendation. Keep line numbers, symbol names and paths out of the question; they belong in the analysis
  comment.
- Cite real `file:line`, not guesses.
- If the ticket is fully implemented already, say so and stop.
- Use ticket ops only. Never call a tracker tool by name.

## Completion status

End with one of:
- **DONE**: every claim checked, checklist complete, contract and vectors saved. Ready for `/operate`.
- **DONE_WITH_CONCERNS**: complete, but items need resolving before implementation. List each.
- **BLOCKED**: a product decision or an Owner-Kept Gate, or no test runner for a row (Step 4.7). Say exactly what
  must be decided.
- **NEEDS_CONTEXT**: a referenced file, table, endpoint or ticket can't be reached, or the pre-code pass failed.
  Say exactly what is missing.

If the ticket conflicts with the code, take the safer reading, record why, and continue. `BLOCKED` is only for a
product decision, an Owner-Kept Gate or a missing test runner.

---

## Workflow after triage

| When | Command | Purpose |
|---|---|---|
| Bug or regression | `/investigate` | Root cause first; no fix without a confirmed cause |
| Always | `/operate` | The implementation: discharge every contract row, run every helper, read the diff back before review |
| Always | `/post-op` | Self-red-team, contract audit, the gates (observability, security, API contract, migration guard, compliance, docs, test, mock fidelity), then the capped review rounds. Before any commit that touches source |
| Optional, owner's call | `/peer-review` | Two independent reviewers on a frozen snapshot, after post-op. Not required by `/ship`, but an unresolved verified finding blocks it |
| Behaviour on a live surface | `/verify` | Drive the changed flow locally against real services before merge; confirm deploy and logs after |
| Ready to merge | `/ship` | PR to `<MAIN_BRANCH>`, owner's yes, merge, open items, close |
| Production release | `/release` | Release checklist; Owner-Kept Gate G1 |

Packs may add rows: see the section for this command in each installed `.claude/packs/*.md`.
