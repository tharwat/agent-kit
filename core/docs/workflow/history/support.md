<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Support commands: why the rules exist

Covers `/test`, `/investigate`, `/handoff`, `/resume`, `/observability` and `/release`. Sessions don't load this file.
No rule lives only here. If this file and a command disagree, the command wins.

## /test

- **One command, two jobs (owner decision).** One source used `/test` to find coverage gaps and write tests. The
  other used it to run the real suite and observe behaviour. They were merged rather than split into `/test` and
  `/test-gaps`, so one run both finds and writes the missing tests and then proves the change with the full suite.
- **Run every test command exactly as written.** On more than one occasion an agent ran a narrower command in place
  of the suite: a subset, one file, or an ad-hoc script that "checked the same thing". Each time the real suite was
  red, and the change was reported green. The only safe command is the configured one, word for word.
- **Read counts from the runner.** Documented suite sizes drifted several times as tests were added. A number
  copied from a doc tells you nothing about this run.
- **The runner loads the env.** The suite read the project's env file, so a test that called a real client reached
  the single production database. That is why every external client is stubbed, and why the logic before the call
  is what gets asserted.
- **The safe ladder.** With no separate test environment, a careless "quick test in prod" has no safety net. Dry-run
  entry points and read-only queries prove most changes without side effects. A real run is the last rung.
- **Syntax or build checks.** In a codebase with no compiler and no CI, nothing else catches a syntax error in a
  file no test imports. It passes the suite and breaks at runtime. A per-file syntax check costs nothing.
- **A green test runner is not a passing type check.** In a typed codebase, tests can pass while the compiler fails,
  and the deploy build then breaks. The ordering detail belongs to the typescript pack.
- **Regression shown failing first, and the counterfactual.** A test that would keep passing with the guard deleted
  proves nothing about the guard. So a contract row is discharged only when its test fails under the named bad
  behaviour. That run happens in a disposable copy, so the active checkout is never mutated.
- **Escalating is not closing.** After three failed attempts the agent stops. Without this rule, a stop could be
  read as the end of the work, and the ticket could close with the failure still open. So the failure stays open,
  the ticket is BLOCKED, and nothing ships on it.

## /investigate

- **Read the integration's real error body.** Integration bugs got chased through guesses about scopes, accounts
  and endpoints when the vendor's response already named the cause. The source's standing rule was "verify, don't
  guess".
- **The negative-space check.** Most production failures came from a sibling path that reached the same function
  without the guard the changed path had. The reported path showed the symptom. Each project keeps its known pairs
  in `docs/agent/sibling-paths.md`.
- **Contract drift, fail-open swallow, race/double-fire.** These three patterns are added to the general table
  because they fail silently:
  - a field renamed on one side;
  - a background job that catches an error, logs it and reports success;
  - an idempotency read whose own error is ignored, so a failed check reads as "not yet sent" and the action runs
    twice.
- **"Works in one environment, not another".** The original wording assumed a QA environment. The kit has one main
  branch and no QA environment, so the pattern is phrased by environment in general: local vs deployed, one service
  vs another.
- **Scope file in the scratch dir.** The source wrote it to the system temp dir, which is shared between sessions
  and worktrees. The kit's scratch rule applies.
- **"Demonstrate it".** Some fixes can't be unit-tested, such as a live webhook or an external callback. Then the
  proof is a reproduce, fix, observe sequence with pasted output, plus the reason no test was possible.

## /handoff and /resume

- **The VERIFIED (external fact) line.** Facts about external APIs and schemas take effort to confirm. Without a
  place in the handoff, they are lost at compaction and the next session guesses them again.
- **Last deploy observed, and live operations performed.** Git can't tell a fresh session whether a deploy went
  out, or which production rows and external sends the previous session made. It needs that for cleanup, and so it
  doesn't repeat an irreversible action.
- **Handoffs are gitignored.** A handoff holds session detail that doesn't belong in history. Ignoring the
  directory makes an accidental commit impossible.
- **Dropped:** work lanes and links to an external wiki checklist. They were specific to one project's setup.

## /observability

- **Catch-log-continue is a finding.** A job that swallows its delivery errors and logs success looks healthy in
  the logs while nothing is delivered. Background delivery must throw so the scheduler records a failure.
- **Secrets as well as PII.** One source only checked PII. Tokens and webhook secrets in logs leak just
  as badly, and log sinks are often readable by more people than the secret store.
- **Scope includes webhook handlers and every external caller.** These are the paths that fail silently, so
  checking route handlers alone is not enough.
- **Hardcoded counts.** A count written into a log line or health response goes stale without warning when items
  are added or removed. It then misreports what is running.

## /release

- **A core checklist, packs add sections (owner decision).** Most release checks are about the host and the
  database, so the stack-specific parts (services and env groups, migration backouts, store tracks) come from the
  packs.
- **Names G1.** The source checklist never named the gate that protects production, so a GO could be read as
  permission to release. Here a GO is a verdict, and the owner's yes is a separate step.
- **Main-only.** The source checked a promotion from a QA branch. With one main branch, a release is what is on
  main, and a post-merge failure is fixed forward on a new ticket. A promotion-blocking label exists only where a
  pack defines one, for example a mobile store build.
