<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Peer review: why it works this way

Background for `/peer-review`, `/bteam`, `/codex-review` and `.claude/scripts/kit-tools.mjs`. Not loaded every
session. If this file and a rule disagree, the rule wins.

## Optional, owner-decided

Peer review used to be a mandatory post-op gate with a repeat-until-convergence loop. Every round re-froze a
snapshot, re-ran both engines, and any new claim restarted the loop, so the reviewers became the bottleneck of the
whole pipeline. Single tickets took days. Whether a change is worth two adversarial passes is now the owner's call
per change. Post-op's own gates and its capped review loop still run on every change.

The one non-optional part: once a pass has run, an unresolved verified finding stops `/ship`. Running reviewers and
then shipping past what they found turns a real defect into a recorded, ignored one.

## Own gates first

Launching reviewers at code that is still changing, or whose own gates haven't passed, spends both engines on
defects the implementer would have found alone, and caused multi-round reviews. Hence the post-op fingerprint check
in Step 0.

## A frozen, merge-base snapshot

An earlier snapshot was a tree diff against the moving integration branch (`git diff <branch>`), not a merge-base
diff. Once that branch moved on, the frozen patch carried other tickets' changes, and reviewers were reviewing code
that wasn't part of the ticket. The kit's freeze:

- diffs from the merge-base (after a fetch), so only the branch's own changes are in the patch;
- refuses untracked files, because `git diff` can't see them and the review would silently miss them;
- hashes base + patch + contract together, so a changed contract also makes the review stale;
- pins every diff setting that changes the bytes but not the content (prefixes, colour, algorithm, context,
  abbreviation, order file), so the same change hashes the same everywhere. `--binary` is left out because its body
  depends on the compression level; the full-index line already names a binary's content.

The fingerprint leaves out docs-only paths so a README edit doesn't force another review. The snapshot keeps them so
reviewers see everything.

## Hash-bound, complete output

A review is evidence only about the exact artifact it read. So each engine's output must begin with the snapshot
hash, give a status for every lens and end with `REVIEW_COMPLETE`; the helper checks it. A truncated answer, a
crashed CLI or a missing lens used to read as "no findings". Now they are `UNAVAILABLE`, and a single-engine pass is
labelled as one.

## Blocking eligibility

Unbounded reviewers produce endless "consider…" items, and treating them as blockers made loops that never
converged. A finding blocks only if it breaks a contract row, shows a wrong result on a changed path, or is a
concrete critical safety exception. Everything else is an observation: recorded, never blocking, never an automatic
ticket.

## Prior-art gate

Zero-context reviewers don't know what the codebase already guards or which limits were deliberately accepted. A
large share of their findings were already handled. Presenting those as a fix-list wasted rounds and eroded trust,
so every finding passes three questions (guarded here? accepted before? introduced by this diff?) before it is
verified.

## Headless, artifact-only reviewers

A subagent spawned from a long session can inherit its framing. Running `claude -p` in plan mode, in a directory that
holds only the patch, the contract and the brief, keeps the B-Team reviewer genuinely zero-context. Codex runs
sandboxed read-only with MCP servers off, so a review can't write or call out. An in-session subagent remains a
labelled fallback.

## The Codex stall rule

A detached Codex run once finished its whole report and then never exited; it sat "running" for hours while a
monitor waited on the process. Progress is judged by the output, and a complete report with a hung process is a
pass.

## No loop by default

A verified finding fixed with a regression test that fails without the fix counts as resolved. Fixes re-enter the
implementer's own self-review and post-op gates. Another peer-review pass is a choice, not an obligation.

## Pre-code vectors

Green tests can all exercise adjacent paths. An independent vector designed before any code exists means a guard
can't be deleted without something going red. Its provenance (engine and date) is recorded because a vector the
implementer wrote for themselves is an ordinary test plan, not an independent one.
