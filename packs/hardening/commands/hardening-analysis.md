---
description: Set up a release-wide edge-case analysis (master brief, subsystem probes, chain analysis, schema dump), optionally running every probe with subagents.
argument-hint: "<version> [--auto]"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`. Pack facts (`<SCHEMA_DUMP_COMMAND>`)
come from `.claude/packs/hardening.md`.

# Hardening analysis

Invoked as `/hardening-analysis <version> [--auto]`.

`<version>` is required (for example `v3.0` or `q4-launch`). It names the folder `hardening/<version>/`, which
identifies the run for the rest of the project's life.

## Purpose

Builds a complete edge-case analysis framework for an upcoming release in one pass:

- a **master brief** fitted to this codebase: stack, domain concepts, risk categories, and the failure patterns this
  project has actually shipped;
- **one probe file per subsystem**, with the count and split discovered from the code, never fixed in advance;
- a **chain analysis** template for compound failures across probes;
- a **schema dump**, so probes have ground truth for every table and column claim.

**Default mode:** the owner runs each probe in its own fresh session, then the chain analysis last with every probe's
findings pasted in. Highest quality, slowest.

**`--auto`:** after writing the inputs, one subagent per probe runs in parallel, each writing its own findings file,
then one more runs the chain analysis. Faster, but each subagent has a smaller budget than an interactive session.

Either way, findings become tickets that `/hardening` takes one at a time.

**When to use:** before a major release, after a feature that widened the attack surface, or when an incident
suggests a systemic blind spot. Not for routine work: the output is 10+ files.

---

## Step 0: Preconditions

```bash
ls hardening/<version>                          # must not exist
git check-ignore -q hardening/x && echo ignored  # must print nothing: hardening/ is tracked
```

- `hardening/<version>/` already exists → stop: "`hardening/<version>/` already exists. Start in a new dated folder,
  for example `<version>-<YYYY-MM-DD>`." An earlier run's folder is a record; never reuse or overwrite it.
- `hardening/` is gitignored → stop: "`hardening/` is gitignored. Remove that entry before running: the point is a
  record across releases."

## Step 1: Read the project's reference material

These shape the master brief's "Known failure patterns":

- `CLAUDE.md` and `CLAUDE.kit.md`: forbidden actions, Owner-Kept Gates, `<CRITICAL_DOMAIN>`, `<CRITICAL_SYSTEMS>`;
- `docs/agent/lessons.md` and `docs/agent/defect-classes.md`: the bug classes this project has shipped;
- `docs/agent/source-layout.md`, `docs/agent/integrations.md`, `docs/agent/pii.md`;
- design docs under `docs/` that record architectural decisions.

Every known failure pattern must be one that has **really appeared here**, with its example. If the lessons don't
record it, don't invent it. Generic SaaS bug lists aren't wanted.

## Step 2: Discover the subsystems from the code

Walk the source tree top-down and list every area that is a distinct subsystem. Let the count emerge. A candidate
earns its own probe when it has its own data store or external service, its own user-facing surface (a screen, a
page, an endpoint group), or failure consequences meaningfully different from its neighbours. Merge candidates that
would produce mostly the same probe. A candidate too broad for one probe but still one subsystem stays one probe
that names each of its flows.

Typical projects land between 4 and 12. Don't enforce a number.

## Step 3: Dump the schema

```bash
mkdir -p hardening/<version>
<SCHEMA_DUMP_COMMAND> > hardening/<version>/schema.sql
```

- The command must dump the **schema only** (tables, indexes, constraints, access policies), never data. It is a
  read; it needs no gate.
- It fails → stop and report it. Probes without schema ground truth invent columns.
- `<SCHEMA_DUMP_COMMAND>` is `none` (no database) → skip this step and say so in the master brief.
- Read the dump before committing it: a schema dump must hold no secret, seed value or connection string.

## Step 4: Write the master brief

`hardening/<version>/00-master-brief.md`, sections in this order (domain context before code guidance):

1. `# <PROJECT_NAME> — <version> release hardening: edge-case analysis`
2. `## How to use these files`: run each probe in its own session; paste the master brief first, then the probe;
   give the session read access to the code and `schema.sql`; run the chain analysis last.
3. `## What this application is`: one paragraph, as if briefing a new engineer. Say why `<CRITICAL_DOMAIN>` is a
   safety concern and not just a bug class, and name the primary flows.
4. `## Technology stack`: a table of layer and technology, read from the package manifests.
5. Domain sections (account types, roles, document types…) only where the project really has them as primary
   concepts. Read them from the code and docs.
6. `## The five risk categories`: **critical-domain violation** (`<CRITICAL_DOMAIN>`), **silent failure**,
   **financial error**, **auth bypass**, **data integrity**.
7. `## Known failure patterns in this codebase`: 8–12 patterns from Step 1, each one sentence on the pattern and one
   on the real example. Fewer when the lessons are thin; that is honest.
8. `## Output format`, verbatim:
   ```
   FINDING: [Short descriptive title]
   Subsystem:        [which probe this came from]
   Severity:         Critical / High / Medium / Low
   Risk type:        [one of the five categories]
   Trigger:          [exact conditions: what input, what state, what sequence of events]
   Current behavior: [what the system does today; what the user sees]
   Impact:           [what goes wrong as a result]
   Verify at:        [file:line to inspect, or exact steps to reproduce]
   Compound risk:    [does this interact with another subsystem? yes/no; if yes, which]
   ```
9. `## Calibration`: "Each probe should yield 8–15 findings across all severities. Fewer than 5 means it skimmed;
   more than 20 is noise."
10. `## What not to report`: style, "add more logging" with no specific point, "add validation" with no specific
    endpoint. The focus is behavioural edge cases, critical-domain violations and silent failures.

## Step 5: One probe file per subsystem

`hardening/<version>/NN-<subsystem-slug>.md`, `NN` zero-padded from `01`:

1. `# Probe NN — <subsystem>`
2. `> Read the master brief (00-master-brief.md) before this probe.`
3. `## What this probe covers`: one paragraph; list each flow separately when there are several.
4. `## Files to read`: grouped by surface (API routes, services, jobs, clients…). Only paths you confirmed exist.
   Also the tables to check in `schema.sql`.
5. `## Questions to answer`: **8–15 specific questions from reading this subsystem's code.** Each names the file and
   the behaviour, states a concrete hypothesis, and gives the place to check. Shapes that work:
   - "`<function>` in `<file>` reads one row with a single-row helper. Can `<condition>` produce two matching rows,
     and what does the caller do then?"
   - "`<field>` drives `<decision>`. What happens when it is (a) exactly on the boundary, (b) null or unparseable,
     (c) in the future?"
   - "`<handler>` marks the event processed before `<side effect>`. If `<side effect>` fails, is the event retried
     or lost?"

   Avoid "are there any race conditions in X?": too vague, and it yields shallow findings. The questions are the
   load-bearing artifact; spend the time here.

## Step 6: Chain analysis template

`hardening/<version>/NN-chain-analysis.md`, with `NN` the next number after the last probe:

1. `# Probe NN — Chain analysis (cross-subsystem compound failures)`
2. `> Read the master brief (00-master-brief.md) before this probe.` and `> Run this probe last, after every
   subsystem probe.`
3. `## What this probe covers`: a flaw in subsystem A and one in B that together cause an outcome neither probe saw.
4. `## How to run this probe`: paste every probe's findings into "Findings input", then answer the questions.
5. `## Findings input`: one empty `### Probe NN — <name>` heading per probe.
6. `## Chain failure questions`: 5–10 starter questions of the form "if finding X from probe A meets finding Y
   from probe B, what breaks?", for example a body-supplied tenant id meeting a billing lookup, or a silent job
   failure meeting an idempotency record that marks unsent work as sent. The analyst may add more.

## Step 7: Run-sheet (default mode)

Without `--auto`, print:

```
✅ Hardening analysis set up at hardening/<version>/

Files: 00-master-brief.md · 01-<a>.md … · NN-chain-analysis.md · schema.sql

For each probe (01 … NN-1), in its own fresh session:
  1. Paste 00-master-brief.md, then the probe file.
  2. Give it read access to the probe's "Files to read" and to schema.sql.
  3. Save its findings as hardening/<version>/NN-<subsystem>-results.md.
Then, last: paste the chain template with every probe's findings in "Findings input";
save the output as hardening/<version>/NN-chain-analysis-findings.md.

Then turn findings into tickets (below) and run /hardening <ticket> for each.
(--auto next time runs the probes with subagents.)
Owner action: run the probe sessions above
```

## Step 8: Auto mode (`--auto` only)

Each subagent starts with no context from this session, which gives each probe independent eyes, unattended.

**8a. One subagent per probe, all in one message** (general-purpose agents, sent together so they run in parallel).
Prompt for probe `NN` (`<S>`):

```
You are running edge-case probe NN for the <version> release hardening of <PROJECT_NAME>. You have no prior context;
everything you need is below or in files you can read.

## Master brief
<full contents of 00-master-brief.md>

## Your probe
<full contents of NN-<S>.md>

## Schema
hardening/<version>/schema.sql. Check every table and column claim against it.

## Deliverable
Write your findings to hardening/<version>/NN-<S>-results.md in the FINDING format from the master brief. Every
finding needs a real file:line or concrete reproduction steps. Never invent files or columns. Aim for 8–15 findings.
Finish with one line: "<N> findings written to NN-<S>-results.md (Critical: X, High: Y, Medium: Z, Low: W)".
Read the code before writing findings. Generic findings aren't wanted: each must name behaviour in this codebase.
```

**8b. Check each results file** exists and isn't empty. Re-run any probe that failed, alone, before going on: the
chain analysis needs all of them.

**8c. Then one chain-analysis subagent**, never in parallel with the probes. Its prompt: the master brief, the chain
template, the path of every results file, and: "Read each results file, assemble the findings input, answer every
chain question, and write hardening/<version>/NN-chain-analysis-findings.md in the FINDING format. Each chain finding
cites the probe findings it combines, by title. Finish with the same one-line count."

**8d. Report:**

```
✅ Hardening analysis complete: hardening/<version>/
  01-<a>-results.md            N findings (Critical X · High Y · Medium Z · Low W)
  …
  NN-chain-analysis-findings.md  N findings (…)
Total: <sum> findings across <N+1> probes.
Next: review the findings, turn them into tickets, then /hardening <ticket> for each.
Owner action: review the findings before tickets are filed
```

**8e. Quality caveat.** A probe with fewer than 5 findings probably skimmed: flag it ("Probe NN returned only N
findings; re-run it in a fresh session"). For the highest-stakes release, the manual mode is still better.

**Codex:** no subagent fan-out. Treat `--auto` as default mode and say so.

## Turning findings into tickets

After the owner reviews the findings, ticket op **create** them (ticket op **search** first; comment on an existing
ticket instead of duplicating). A typical split: one ticket per Critical; grouped tickets for High and Medium findings
that share a fix surface; one bundled ticket for the rest. Each ticket names its finding titles and the results file.
Then `/hardening <ticket>` per ticket.

## The folder is tracked

`hardening/` is committed on purpose: the probes, schema snapshot and findings are the record of what each release
was checked for. If a finding is too sensitive for the repository (an actively exploitable hole), hold it back and
say so before anything is committed.

## Rules

- **One pass for setup.** Steps 0–7 run in one invocation; Step 8 only with `--auto`.
- **The subsystem split is discovered**, never copied from an earlier run.
- **Probe questions come from reading the code.** A probe of generic questions has failed.
- **Known failure patterns come from the lessons.** Never invented.
- **The schema dump is mandatory** when there is a database. It failed → halt and report.
- **Default mode: don't run the probes yourself.** Independent context per probe is the point.
- **Never write the findings files yourself.** They come from probe runs, manual or subagent.
