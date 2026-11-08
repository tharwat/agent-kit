---
description: Take a finished, reviewed feature branch to a merged PR on the main branch, verified, with open items filed and the ticket closed.
argument-hint: "[<ticket>]"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# Ship

Invoked as `/ship [<ticket>]`. With no argument, the key comes from the branch name
(`<BRANCH_PREFIX><ticket-lowercase>-<slug>`), confirmed with ticket op **get** `<ticket>`.

`/ship` is a merge engine, not a review. It takes a finished feature branch to "merged into `<MAIN_BRANCH>`":

1. Preconditions: post-op report, covered check, peer-review record.
2. Commit and push what's outstanding; open the PR.
3. `/verify` before merge.
4. The owner's yes (G3), then merge (waiting for required checks if `<HAS_CI>` is true).
5. After merge: confirm the deploy and logs, file open items, close the ticket, notify, report.

It needs a clean `/post-op` on the **final** code. `/peer-review` is optional: a branch that never ran it ships
normally. Don't ask for it and don't run it to satisfy this command. The one exception is Step 0.3.

## Hard guardrails

- **Only feature branches ship.** If `git branch --show-current` is `<MAIN_BRANCH>` or doesn't start with
  `<BRANCH_PREFIX>`, stop.
- **The PR base is always `<MAIN_BRANCH>`.** Verify it before merging.
- **Never push or commit to `<MAIN_BRANCH>` directly, and never force-push anything.**
- **No admin override.** Bypassing branch protection is Owner-Kept Gate G4.
- **No merge without the owner's explicit yes** (G3), unless this run is a step of an approved ticket train
  (ticket-trains pack).

---

## Step 0: Preconditions

### 0.0 GitHub remote

`/ship` opens, checks and merges the PR with `gh`, so in v1 it needs a remote named `origin` on GitHub and an
authenticated `gh`:

```bash
git remote get-url origin
gh repo view --json nameWithOwner,defaultBranchRef
```

No `origin`, a non-GitHub URL, or `gh repo view` failing (not installed, not logged in, no access) → **stop** and say:
"`/ship` needs a GitHub remote in v1; push the branch and open the PR on your host by hand." Then give the steps:

1. Push the branch to the project's remote: `git push -u <remote> HEAD` (never force).
2. On the host, open a pull/merge request from `<branch>` into `<MAIN_BRANCH>`. Put the post-op result and the
   `/verify` result in its description.
3. Merge it there only with the owner's yes (G3), with no admin override (G4), after any required checks pass.
4. After the merge: confirm the deploy and logs, file open items on `<OPEN_ITEMS_TICKET>`, and ticket op **close**
   `<ticket>`.

If `gh` is only logged out, the owner can run `gh auth login` instead and re-run `/ship`.

### Branch state

```bash
git fetch origin
git branch --show-current
git log origin/<MAIN_BRANCH>..HEAD --oneline
git status --short
```

- Nothing ahead of `origin/<MAIN_BRANCH>` and a clean tree → stop: "No changes to ship."
- No ticket key can be derived → ask for it before committing anything.

### 0.1 Post-op report

Read `.claude/state/<ticket>/post-op.md`. It must hold `Result: clean` or `Result: capped` (or `escalate` with the
owner's answer recorded), and its Code review row must be `✅ Clear`, `✅ N found, N resolved` or
`⏭️ Skipped — Codex` or `⏭️ Skipped — no reviewable change` (docs-only branch; its `Fingerprint: none (no
reviewable change)` is handled by the empty-diff case in 0.2). `⚠️ Escalated`, `⚠️ N open`, `⚠️ Not run` or a missing file → **stop**: `/post-op` hasn't
passed. `/ship` never runs the gates for you.

### 0.2 Covered check

The tree you ship must be the tree the last review round covered. This is a hash comparison, never a recollection.

```bash
node .claude/scripts/kit-tools.mjs covered --hash <Fingerprint from post-op.md> --base origin/<MAIN_BRANCH>
```

- Exit 0 → covered. Continue.
- Non-zero, a mismatch → **stop**. A reviewable change came after the last round: run `/post-op` again. Never
  re-record the hash to make it pass.
- Non-zero, `untracked files` → `git add -N` the intended files and re-run.
- Non-zero, empty diff → the branch has no reviewable change (docs only), so it's covered by definition. Continue.
- Non-zero, git failure → fix the infrastructure (offline, not a repo). Another review round can't fix it.
- Node unavailable → say so and stop. There is no hand-run fallback.

### 0.3 Peer-review record (only stops when a peer review ran)

```bash
test -f .claude/state/<ticket>/peer-review.json && node -e '
const d = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8"));
if (!Array.isArray(d.findings)) throw new Error("no findings list");
const ok = (x) => x !== null && typeof x === "object" && (
  ["REJECTED", "ALREADY-RESOLVED"].includes(x.status) ||
  (x.status === "NOTED" && x.class === "noted") ||
  (["VERIFIED", "NEEDS-OWNER"].includes(x.status) && x.resolved === true));
const bad = d.findings.filter((x) => !ok(x));
bad.forEach((x) => console.log("open:", x && x.id, x && x.class, x && x.status));
if (!["CLEAN", "not run"].includes(d.verdict)) console.log("verdict:", d.verdict);
process.exit(bad.length || !["CLEAN", "not run"].includes(d.verdict) ? 1 : 0);
' .claude/state/<ticket>/peer-review.json
```

It's an allow-list. A finding passes only when its status is exactly `REJECTED` or `ALREADY-RESOLVED`; or `NOTED`
with class exactly `noted` (a must-fix class marked noted blocks); or `VERIFIED` / `NEEDS-OWNER` with
`resolved: true`. Anything else blocks: a misspelling, other capitalisation, a missing status.

- **No file** → check the ticket's comments (from **get**) for a `PEER_REVIEW:` record from an earlier session. None
  → peer review wasn't run. Continue, and don't suggest running it.
- **Exit 0** → continue to the staleness check.
- **Exit 1 with findings or `verdict: UNRESOLVED` listed** → **stop**. Name each one. Resolve it through
  `/peer-review`, disprove it with evidence, or get the owner's decision; then run `/ship` again.
- **Exit 1 with a JavaScript error** (unparseable, no findings list) → **stop**. A broken record isn't evidence that
  nothing is open.

**Staleness.** When the verdict is `CLEAN`, confirm the snapshot still covers the tree:
`node .claude/scripts/kit-tools.mjs covered --hash <the fingerprint peer review recorded at freeze> --base
origin/<MAIN_BRANCH>`. Non-zero
→ the review is `STALE`. Say so in the report; never present it as covering the shipped code. Re-freeze through
`/peer-review` if the owner wants coverage.

### 0.4 Commit and push

- Uncommitted changes → show `git diff --stat` and commit as `<ticket>: <description>`. If `<CO_AUTHOR_TRAILER>`
  isn't `none`, end the message with it. If the change is ambiguous or risky, stop and ask first.
- Committing new work after 0.2 makes the branch uncovered: re-run 0.2.
- `git push -u origin HEAD`. Never force-push.

Packs may add checks here: see the section for this command in each installed `.claude/packs/*.md`.

---

## Step 1: Open the PR

Reuse an existing PR for the branch (`gh pr list --head <branch> --json number`). Otherwise:

```bash
gh pr create --base <MAIN_BRANCH> \
  --title "<ticket>: <concise description>" \
  --body "<what changed, why, and how it was verified>"
gh pr view <N> --json number,baseRefName,headRefName
```

`baseRefName` isn't `<MAIN_BRANCH>` → `gh pr close <N>` and stop.

## Step 2: Verify before merge

Classify the diff (`git diff origin/<MAIN_BRANCH>...HEAD --name-only`):

- **No runtime surface** (docs, comments, tests only, config with no behaviour change) → record
  `Validation: ⏭️ skipped — no runtime surface`.
- **Behaviour change** → run `/verify <ticket>` (pre-merge half). Only `✅ VERIFIED` passes. `⚠️ PARTIAL` or
  `❌ FAILS` → don't merge. Notify (Step 6, failure), report, stop. A fix is a new cycle.

Packs may add checks here: see the section for this command in each installed `.claude/packs/*.md`.

## Step 3: The owner's yes, then merge

**G3.** Ask the owner one question:

> Merge PR #<N> (`<ticket>`: <title>) into `<MAIN_BRANCH>`? Verify: <result>. Post-op: <result>. Peer review:
> <result>.
> - **Yes, merge now.** Pro: the verified change ships. Con: it goes to production as soon as it deploys.
> - **No, hold it.** Pro: time to look first. Con: the ticket stays open and the branch can drift.

No yes → leave the PR open, report `Merged: — held for owner`, stop. When the ticket-trains pack is installed and this
run is inside `/ticket-train-run`, invoking the run is the yes for that train's queue only.

**If `<HAS_CI>` is true:**

```bash
gh pr merge <N> --auto --merge
gh pr checks <N> --watch --interval 30 --fail-fast    # Claude: in the background. Codex: in the foreground
```

Report a status line each cycle: `⏳ <ticket> PR #<N>: 6/9 checks green · 3 pending · 0 failed`. On a red check:

1. Find it: `gh pr checks <N>`, then `gh run view <run-id> --log-failed`.
2. Cancel the queued merge: `gh pr merge <N> --disable-auto`.
3. Notify (Step 6, failure) with the check name, the error and the run URL. Stop. Don't merge.

**Otherwise** (no required checks; the pre-merge `/verify` stands in for CI):

```bash
gh pr merge <N> --merge
```

Either way, confirm it landed: `gh pr view <N> --json state,mergedAt` must show `MERGED`.

## Step 4: After merge

### 4.1 Deploy and logs

Run `/verify <ticket>`'s post-merge half: confirm the deploy is live and the change's log lines appear. Skip it
only when Step 2 recorded no runtime surface.

- A build failure means `<MAIN_BRANCH>` is broken. Say so at once and loudly, notify, and don't start other work.
- Any other post-merge failure: the merge stands. Fix forward on a new ticket (ticket op **create**), comment its
  key on this ticket, leave this ticket open, notify.

Packs may add post-merge checks here: see the section for this command in each installed `.claude/packs/*.md`
(for example, that each migration file merged to `<MAIN_BRANCH>` is byte-identical to the one applied).

### 4.2 Local cleanup

```bash
git fetch origin
git checkout --detach origin/<MAIN_BRANCH>
git branch -d <branch>
```

`git branch -d` refuses an unmerged branch. If it refuses, leave the branch and say so.

### 4.3 Open items (before closing)

`/ship` is the only writer to `<OPEN_ITEMS_TICKET>`. It never stops the ship and never asks the owner.

1. Ticket op **get** `<ticket>` (comments included). A record is a comment whose **first line** starts with
   `Open items (PR #`.
2. A record for **this** PR exists → already filed. Go to 4.4.
3. Otherwise collect items from comments after the latest earlier `Open items` record (all comments if none):
   every `noted` item in a `Review round` record, and every item in a `Noted for the tracker` comment. List an item
   found more than once only once.
4. Items found → ticket op **comment** `<OPEN_ITEMS_TICKET>` with one comment:
   `## <ticket> — <title> (closed <date>; round records <comment ids>)`, then one numbered item each with
   **where** (`file:line` or function), **effect** (what happens, to whom), **why left open** (class, pre-existing
   or not) and **suggested fix and test**, tagged `(worth fixing)` or `(minor)`. Then ticket op **comment**
   `<ticket>`: `Open items (PR #<N>): <OPEN_ITEMS_TICKET> comment <id>`.
5. No items → ticket op **comment** `<ticket>`: `Open items (PR #<N>): none`.

A write fails → retry once. Still failing → **don't close the ticket**. Report
`Open items: not filed — <error>; ticket left open` with `Owner action: close <ticket> — its open items could not
be filed`.

### 4.4 Close the ticket

Only when this PR's `Open items` record exists and 4.1 didn't fail: ticket op **close** `<ticket>` with a note
naming the PR. The note's first line is `Post-merge: <ticket> — <deploy and log result>`, the evidence `/release`
reads. If it fails, don't undo the merge. Report `Ticket close failed` and leave the key visible.

## Step 5: Owner action

`Owner action:` is `none` unless the owner must act now: an Owner-Kept Gate at the moment it applies, a product
decision, or open items that couldn't be filed (4.3). Never list a step the workflow already tracks, a chore the
agent can do, or the optional `/peer-review`.

## Step 6: Notify

If `.claude/scripts/notify` exists, run it once. A failed send prints one line and never fails `/ship`.

- Success: `.claude/scripts/notify "[<PROJECT_NAME>] 🚀 Shipped <ticket> — <title> · PR #<N> merged to <MAIN_BRANCH> · ticket closed"`
- Failure: one alert per run, naming every problem:
  `.claude/scripts/notify "[<PROJECT_NAME>] ❌ Ship blocked: <ticket> · <what failed> · <one-line error> · <run-url>"`

## Step 7: Final report

```
─────────────────────────────────────
SHIP: <ticket> — <title>
PR:          #<N> (base: <MAIN_BRANCH>)
Checks:      ✅ N/N green | ❌ <check> failed | — no CI
Validation:  ✅ /verify passed pre-merge on <surface> | ⏭️ skipped — no runtime surface
Merged:      ✅ <timestamp> | — not merged: <reason>
Post-merge:  ✅ deploy live, log line seen | ❌ <failure> → fix-forward <key>
Open items:  <OPEN_ITEMS_TICKET> comment <id> | none | not filed — <error>
Cleanup:     local branch deleted | kept: <reason> · ticket closed | left open: <reason>
Post-op:     <Result> · fingerprint covered
Code review: ✅ Clear | ✅ N found, N resolved | ⏭️ Skipped — Codex · <R> rounds
Peer review: not run | CLEAN <hash> | STALE <hash> | UNRESOLVED — blocked
Owner action: none | <the one action>
Context: ready to /clear
─────────────────────────────────────
```

## Rules

- Never merge past a failed check, a failed pre-merge verify, an uncovered tree, or an unresolved peer-review
  finding.
- A behaviour change isn't done without an observed `/verify`. Only a diff with no runtime surface skips it.
- Peer review's absence never blocks and is never reported as a gap.
- Closing the ticket is part of shipping. If it can't close, say so plainly.
- One ticket per context: after this report, don't start the next ticket here.
- Use ticket ops only. Never call a tracker tool by name.
