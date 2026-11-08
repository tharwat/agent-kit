---
description: Zero-context, review-only Codex reviewer of a frozen, hashed snapshot, run sandboxed and read-only.
argument-hint: "[ticket]"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# Codex Review

Codex model: `codex-auto-review`

This line is the only place the model is named. Every `<codex model>` below means it; to use another model, edit
this line.

Invoked with: `/codex-review [ticket]`.

## Purpose

Runs Codex as a hostile, zero-context reviewer of the snapshot `/peer-review` Step 1 froze. It is the second
engine of `/peer-review`, next to `/bteam`. A second engine is worth having because it doesn't share Claude's
assumptions.

- **Review-only.** Codex never writes code here. Any patch it returns is discarded; only its findings count. If it
  asks whether to implement a fix, the answer is no.
- **Hash-bound.** Its output must attest the snapshot hash and pass
  `node .claude/scripts/kit-tools.mjs check-review`.
- **Standalone runs are fine** as a second opinion. They still need a frozen snapshot (`/peer-review` Step 1), and
  they are **not a peer-review verdict**: no record is written and `/ship` has nothing to stop on. Say which you ran.
- It doesn't notify. `/peer-review` reports.

The brief, the lenses, the verification recipes and the prior-art gate are `/bteam`'s. This file adds only how to
run Codex.

## Step 1: Inputs

As `/bteam` Step 1: ticket key and intent, threat-model line, snapshot directory and hash. Write the brief exactly as
`/bteam` Step 2 (same lenses, same numbering, same output shape). If the snapshot no longer matches (`/peer-review`
Step 1c), stop and re-freeze there.

## Step 2: Prove Codex is available

```bash
codex exec -m <codex model> --sandbox read-only -c 'mcp_servers={}' --skip-git-repo-check \
  -o <scratch>/codex-probe.txt \
  "Reply with exactly the number of letters in the word 'watermelon' multiplied by 3, and nothing else." \
  < /dev/null > /dev/null 2> <scratch>/codex-probe.stderr
```

The last non-blank line of `<scratch>/codex-probe.txt` must be `30`. A nonzero exit, a missing file or any other
answer is `Codex (<codex model>): UNAVAILABLE — <actual error line>`. Record it and stop; no review row.

## Step 3: Run one review of the frozen snapshot

`<h12>` is the first 12 characters of the snapshot hash. The findings file name carries it, so output from another
snapshot can't be mistaken for this one.

```bash
D=<scratch>/<ticket>-codex-<h12>
mkdir -p "$D"
cp <scratch>/<ticket>-snapshot/patch.diff <scratch>/<ticket>-snapshot/contract.md "$D/"
cp <scratch>/<ticket>-bteam-brief.txt "$D/brief.txt"
( cd "$D" && codex exec -m <codex model> --sandbox read-only -c 'mcp_servers={}' --skip-git-repo-check \
    -o <scratch>/<ticket>-<h12>-codex.txt \
    "REVIEW-ONLY. Do not edit files or propose patches. Read brief.txt in the current directory and follow it exactly. Review only patch.diff and contract.md." \
    < /dev/null > /dev/null 2> <scratch>/<ticket>-<h12>-codex.stderr )
node .claude/scripts/kit-tools.mjs check-review --file <scratch>/<ticket>-<h12>-codex.txt --hash <snapshot hash> \
  --lenses <lens count> --contract <scratch>/<ticket>-snapshot/contract.md
```

- `--sandbox read-only` and `mcp_servers={}` keep the reviewer from writing anything or reaching any service.
- `-o` writes Codex's final message alone; diagnostics stay in the `.stderr` file.
- **Run it in the foreground with at least 15 minutes allowed.** If your shell tool caps a foreground command
  below that, run it in the background and follow the stall rule below.
- Completion is all of: a zero exit, and `check-review` printing `CLEAN …` or `FINDINGS …`. Anything else is
  `UNAVAILABLE`. Never infer success from a non-empty file or a partial narrative.
- Then run `/peer-review` Step 1c. A changed snapshot voids the result.

### Stall rule

**Poll the output, not the process.** A Codex run can finish its report and never exit; a live process is not
progress.

1. Bound the wait: about 15 minutes for a normal diff.
2. Judge progress by the output file. Unchanged across two polls with the process still running means stalled.
3. **On a stall, read what exists before stopping anything.** If `check-review` accepts the output, a finished
   report with a hung process is a **PASS**: take the findings, stop the run, record the row.
4. Only output that `check-review` refuses is `UNAVAILABLE`. Never record a verdict from a partial report.

A stopped-and-relaunched run is cheap; waiting hours on a finished report isn't.

## Step 4: Verify and present

Verify every `FINDING:` block with `/bteam` Step 4, **prior-art gate included**, at every severity. Present as
`/bteam` Step 5, with this header line:

```
Codex (<codex model>): <CLEAN | FINDINGS (N verified, M observations) | UNAVAILABLE — actual error> — <h12>
```

Through `/peer-review`, hand the table to it; it merges duplicates with B-Team by root cause and resolves in its
Step 6. Standalone, the disposition is **Fix** for S1–S4 and **Noted** otherwise, and a verified defect on this
ticket's path is fixed on this ticket.

---

## Rules

- Codex is review-only. Discard any patch it emits.
- Always sandboxed read-only with MCP servers off.
- Never make or change a snapshot or contract here.
- No probe answer, a failed run or output `check-review` refuses is `UNAVAILABLE`, never clean.
- A standalone run is not a peer-review verdict. Say which you ran.
- Never notify; `/peer-review` reports.
- When Codex itself runs this command, the steps are the same; `codex exec` starts a separate, sandboxed session.
