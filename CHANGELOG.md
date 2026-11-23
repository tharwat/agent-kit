<!-- Copyright 2026 Tharwat Abdul-Malik. Licensed under the MIT License (see LICENSE). -->
# Changelog

Each entry says what changed and what an upgrade will touch. The installer prints the entries newer than a project's
installed version before an upgrade.

## 1.12.0 — unreleased draft (2026-11-21)

The review loop, first half of a two-part change. The second half (a one-page design at triage, and removing the
steps that generate volume) waits for a live result. Evidence: the review records of two projects. Under "fix
every finding" rounds ran into the tens and most later defects sat in earlier fixes; under a severity bar the
loop stopped but about five of 25 runs ended with nothing from review left open.

- **The author no longer decides what a finding gets.** In `consensus-review.js` the verifiers answer facts about
  each real finding: what is lost and to whom, whether the loss is bounded, what has to happen first, whether
  anyone would notice, what the fix costs, and whether it is one more member of a class with no end. A table in
  code turns two agreeing answers into the outcome (`/post-op` round rule 2):
  - a serious loss, and anything normal use reaches: fixed on the ticket, in any round;
  - anything with a small fix: fixed in round 1, which sweeps the whole branch. In a later round it is filed,
    because every fix is new code another round must read;
  - a defect that cannot go wrong as the project stands today (`dormant`: it needs a setting production doesn't
    use, an edited constant, or far more data than exists): filed, with what would wake it;
  - every other real defect: filed, carrying the analysis and a priority;
  - a split vote: fixed now.

  Filed means the ticket's **one** follow-up ticket (`Follow-up: <ticket> review findings`), written once when no
  round is due. The disposition is `follow-up`; `own ticket` now means only an independent capability. A round
  with nothing to fix now is `clean`, however many entries the follow-up ticket holds.

  The author is a witness: it passes a `witness` note of what is already guarded or decided, and sends an
  objection or an unverified finding back with `recheck`. It never rejects, shrinks or defers a finding.
  The decided list (`prior`) also carries every owner decision recorded for the ticket before the review, so
  finders and voters don't raise a decided item again without new evidence.
- **`open class` is a new outcome:** one more phrase, format, evasion or fault combination that the same check
  would have to list. It is never fixed one by one. Finders report such a mechanism once.
- **No cap on findings.** "Report at most 15" is gone, and the fallback runs `/code-review high --max-findings
  all`, with two fresh subagents answering the questions.
- **Codex is a finder in every round** when the `codex` CLI runs on the machine (`codexModel`), headless,
  read-only, with MCP servers off. A round counts without it and its record says so.
- **Round 1 sweeps the whole branch; a later round reviews only the fix delta.**
- **Reports are grouped by mechanism before the vote.** Finders work per area, so one defect arrives from several
  files; the first live trial confirmed one defect five times, with ten verifiers. One agent now groups the
  reports and each group is voted on once (`mechanism`, `members`). In the sweep the same agent names any shared
  cause: a fact the code works out instead of reading, or a second copy of a mechanism, that one change closes.
  Two verifiers try to refute it. A cause they confirm for two or more findings is an event: those findings go
  to the redesign note instead of being patched one by one (`shared_causes`).
- **Events replace the redesign vote.** `next` is `redesign` when a real defect sits in lines an earlier fix
  wrote, comes from the same mechanism as an earlier fixed one, or is an open class that normal use or a serious
  loss reaches; the author raises it too when a fix would add a stored state, a user-visible outcome or a
  mechanism. Patching that part stops. A one-screen redesign note goes to the owner **before any edit** (it used
  to be applied without waiting): remove, reuse, or one closed shape, in that order. A redesign must change the
  kind of solution and remove code, and records `Redesign size: <before> → <after>`.
- **A fix batch writes fix notes, not an inventory section.** One fix per mechanism; before a fix changes what a
  function does, a `Fix note <id>:` line in `review-rounds.md` lists its exits, callers, readers and the writers
  of each key it looks up. `consensus-inventory.js` no longer has a fix-batch mode, and `check-record.py` accepts
  `Inventory: Fix note <id>` when that note exists. An `inventory.json` `Fix batch <n>` section is still accepted.
- **Review rounds no longer write `noted` items for `<OPEN_ITEMS_TICKET>`.** A deferred finding goes into the ticket's follow-up ticket.
  `/peer-review`, pack audits and owner-accepted defects still use the tracker.
- **Wrong text alone never stops the patching.** A defect whose only loss is appearance is fixed in the batch,
  even when it sits in a fix's lines or comes from a mechanism an earlier round fixed.
- **Triage Step 4.8 is the design page.** `plan-check.json` keeps its place and gains four boxes:
  - `adds`: each step of the flow the change touches, what does it today, and what the change adds ("nothing" is
    an answer). A second set of states or recovery rules beside an existing one is a design defect;
  - `open_work`: every part that judges free text or works a state out from several fields, and how the design
    closes it (a stored state, a structural rule, a classifier or a model call that fails closed);
  - `outside`: each behaviour of an outside service the design rests on, with its measurement, or `before code:`
    and the measurement `/operate` takes first;
  - `size`: every file as reused, changed or new with its estimated production lines, and what is out of the
    ticket.

  State homes now ask what a re-run must know, and what a later action must check: a queued or delayed action
  reads the stored fact when it acts, on every path that performs it, and a side effect that stands in for that
  fact is a defect in the page. They also ask what a re-run must know: a time limit, a try count or the order of two writes that stands
  in for a fact that could be read is a defect in the page. A state with more than two values that several
  places read is stored, with one writer and a table of allowed moves. An owner question whose option adds a
  mechanism says what it costs, and the smaller option is the recommended one.
- **`/operate` builds inside the page.** It takes the `before code:` measurements first, adds no state or recovery
  rule the page doesn't have, and sets the diff against `size` at the end of every build step: a production file
  more than half again over its estimate stops the build until the page is amended or the code removed. A flow
  that can run again gets a test that stops between two writes and runs it again.
- **Removed:** the per-finding `design` vote, the third-round notice, `proposed_class` from finders, and the
  `enumerations` box (lists derived by a test that re-derives them). A rule replaces a list, and no checker is
  written to prove one.
- New test: `core/scripts/consensus-review.test.mjs` pins the table and the events with scripted agents.

**Not changed, and now out of step:** `/peer-review`, `/bteam` and the hardening pack still sort their own
findings by the S1–S4 bar, with the author applying it.

**Upgrade touches:**
- `CLAUDE.kit.md` (the review severity and `/post-op` lines);
- `/post-op`, `/operate` ("Every fix batch"), `/peer-review`, `/codex-review`;
- `.claude/workflows/consensus-review.js`, `consensus-inventory.js`, `check-record.py`;
- with ticket-trains, `/ticket-train-run`, `/ticket-train-triage` and `train-state.mjs` (adds the `open class`
  disposition; a `redesign` now pauses the ticket for the owner); with hardening, `/hardening`.

A ticket that is mid-review when a project upgrades: finish its current round under the old rules, and start the
new rules at the next round.

## 1.11.0 — 2026-11-18

Rounds were a symptom; this release goes after the bad first draft and the bad fix. Evidence: the first ticket on
1.8 took four rounds (7, 6, 6, 4 real defects), from lists typed by hand, claims not traced, fixes made the same
way, and one review pass sampling a large diff.

- **Three agents build the dependency inventory before any code.** The new workflow `consensus-inventory.js` runs
  in `/operate` Phase 1:
  - three enumerators work independently;
  - a completeness critic looks for what all three missed;
  - two verifiers check every item only one source found.

  The inventory now also holds `claims` (every statement the change makes, with its proof and, for a safety claim,
  every effect found) and `lists`. `check-record.py` requires `consensus.run` and a `search` on every row.
- **Every fix batch goes through the same workflow,** and enumerates the finding's whole class, so the fix covers
  every member.
- **Lists are derived, never typed.** `plan-check.json` gains `enumerations`: each list the change writes or relies
  on, how it is derived from the source, and the test that re-derives it. `/operate` adds "a list typed by hand →
  derived with a test" and "a regex reading code → a real parser".
- **The review sweeps.** `kit-tools.mjs areas` splits a large diff into areas, and `consensus-review.js` runs its
  three lenses on each, so round 1 covers the whole change.
- **The verifiers decide what comes next.** `consensus-review.js` returns `next`:
  - `clean`;
  - `fix`;
  - `redesign`, when two votes agree a must-fix finding comes from a design that keeps breaking, including the
    same mechanism as a defect an earlier round fixed.

  The agent writes a redesign note and carries it out. The owner is asked only for a product decision or a change
  of behaviour, contract or scope.
- **Removed:** the round count, the limits, `extra_round`, redesign-once, and the "re-scope or ship with named
  defects" options. Ticket-trains no longer enforces a cap. A third round notifies the owner with the `Origins:`
  lines, as a notice, not a question.
- **`LOCAL_RUN` (`isolated | production`)** is the one home of "where a local run lands". It replaces 1.10.3's
  `DEV_SERVER_COMMAND = none`. `/verify`, `/test`, `/qa` and `/playwright-qa` read it.
- **A guessed install fact is confirmed first** through the project's own MCP server or CLI. Otherwise its evidence
  names where the owner checks it.

**Upgrade touches:**
- `CLAUDE.kit.md`, the facts table in `CLAUDE.md` (adds `LOCAL_RUN`);
- `/triage`, `/operate`, `/post-op`, `/verify`, `/test`, `/peer-review`;
- `.claude/workflows/` (adds `consensus-inventory.js`), `kit-tools.mjs`, `check-record.py`;
- with web-qa, `/qa` and `/playwright-qa`; with ticket-trains, its commands and `train-state.mjs`.

A project that set `DEV_SERVER_COMMAND` to `none` in 1.10.3 sets it back to its real command, with `LOCAL_RUN`
`production`.

## 1.10.3 — 2026-11-18

- **An upgrade starts from main, not from the finished install's branch.** A merged `agent-kit/install` worktree
  used to look like an unfinished attempt, so the upgrade would have continued on it. Now `preflight` reports it as
  finished, and `draft` parks it (renamed, never deleted) with no question. Finished means: nothing uncommitted, and
  the branch's commits are on main, or its lock is main's lock (a squash merge).
- **`/test` and web QA follow the safe list too.** `/test`'s dry-run rung no longer says "grep for `dry`": it uses
  only the map's safe list. `DEV_SERVER_COMMAND` `none` now means the app is never started locally: `/verify`
  defers, and `/qa` and `/playwright-qa` run against the deploy after merge. A real project's `npm start` also
  started its production schedulers.
- **A lane at the install path is stepped around.** When another worktree already sits at
  `<WORKTREE_DIR>/agent-kit-install`, the install uses `agent-kit-install-2` instead of stopping. A real upgrade found
  a ticket's uncommitted work in that folder.

**Upgrade touches:** `.claude/commands/test.md`, `.claude/commands/verify.md`; with web-qa,
`.claude/commands/qa.md` and `.claude/commands/playwright-qa.md`.

## 1.10.2 — 2026-11-18

- **An existing project's `docs/agent/*.md` are filled during the install,** from the project's own commands, rules
  and `CLAUDE.md`, before those are renamed `.pre-agent-kit`. A real install ended with blank templates, so the kit's
  gates checked only the basics.
- **The install report names every project file changed beyond the kit's own** (repointed tests, changed constants,
  condensed docs), with why. Those are the lines in the PR the owner should read.

- **Unguarded credential files are found during the install.**
  - `preflight` and `draft` list gitignored files that hold credentials but aren't on the secret guard's built-in
    list. The checks: JSON key names (`private_key`, `refresh_token`, `client_secret`, …), credential-like file
    names, and `.mcp.json` servers holding a literal token in `env`, in `headers` (including `Bearer <token>`) or in
    a URL query, instead of a `${ENV}` reference.
  - Names and reasons only; no value is ever shown.
  - A new guide entry, `secret-files`, recommends adding them to `docs/agent/secret-files.md`, plus a ticket to move
    the `.mcp.json` values into environment variables.
  - On a real project it found a service-account key that a manual review had missed.
- **A "none" default the project contradicts becomes a guess.** When a fact defaults to `none` but the project's
  tracked files name it (`ENV_GROUPS` → `RENDER_ENV_GROUP_ID` in a script), `draft` marks it `guess`, with where,
  instead of accepting the default. A real install had recorded `none` for a Render env group that existed.
- **The credential scan also reads config files:** TOML, YAML and INI (`.codex/config.toml`), plus env-style key
  names with literal values in any JSON (`"GOOGLE_API_KEY": …`). For a Claude settings file, it recommends moving
  the key into the environment rather than blocking the file.
- **"Dry-run" is a claim, not a fact.** `verify-map.md` gets a "checked side-effect free (file:line)" column, and
  `INSTALL.md` requires reading a command's code path before writing it down as safe. A real fill listed a
  `--dry-run` that could rotate a shared production token, and "run the worker locally", which would have started
  production jobs.
- **Secret-file globs:** the template and the guide warn that `*` also matches across `/`, and recommend an exact
  path for a single file.
- **Tickets the install replaces are closed by the agent,** with a comment linking the install PR. After the merge,
  the agent moves the checkout to the main branch if it was parked on a replaced branch.
- **When local is production, local checks come only from a proven-safe list.** `verify-map.md` now starts with
  "where a local run lands" and "safe to run locally" (each action with its `file:line` proof, dynamic imports and
  job queues followed). Each surface row names a local check, or `none`, and an after-merge check.
  - `/verify` runs nothing locally that isn't on the list. A surface with `Local check: none` gets the new verdict
    `🕒 DEFERRED`.
  - `/ship` accepts it, names it in the merge question, and runs the after-merge log line and read-only query as the
    change's proof.
  - A new guide entry, `local-verification`. A real docs fill spent two review rounds patching local recipes; each
    fix uncovered another path to the live provider, the ops alerts or a token save.
- **The cleanup SQL deletes a child table without the marker only through a marked parent.**
- **The secret guard checks the Grep tool by what it really reads.**
  - Before, a project glob for one JSON credential refused every `*.json` search. A search started inside the
    credential's folder still read it.
  - Now, a names-only Grep (the default) passes. A content Grep is refused when a secret file under its path is
    selected by its glob, or isn't gitignored, or when the glob singles out a built-in secret shape (`.env*`).
- **The settings-file advice checks the project's env sync first:** some projects rebuild `.env` from their host,
  so a key moved there is wiped.

**Upgrade touches:** `.claude/hooks/guard-secrets.py`, `.claude/commands/verify.md`, `.claude/commands/ship.md`. An
installed project's `docs/agent/verify-map.md` is its own: add the two new sections and the `Local check` and
`After-merge check` columns by hand, or ask the agent to.

## 1.10.1 — 2026-11-18

- **Starting an install over takes no git commands.** `preflight` reports an earlier, unfinished install attempt,
  and the agent asks one question: continue it, or start fresh. `draft --fresh` parks the old install worktree and
  its branch under the old kit version (renamed, never deleted), then starts clean. Before this, a "fresh" run
  silently continued the old attempt.

**Upgrade touches:** nothing installed.

## 1.10.0 — 2026-11-18 (supabase 1.0.1)

**An install a first-time owner can do alone.** In a real install, a second session had to explain every clash
between the project's rules and the kit, and the owner still had to work around four installer gaps. The advice now
ships with the kit, and the gaps are closed.

- **Decision guide** (`installer/decision-guide.md`). For every common clash it gives:
  - the kit's rule in plain words, and what it protects against;
  - when the project's way is just as safe;
  - what to check, a default recommendation, and its pro and con.

  The entries: schema changes, how migrations are applied, refactoring, triage → operate, standing owner yeses,
  commit attribution, the word budget, tests that pin old workflow text, review rounds, branch model, merge rights,
  dependencies, MCP write tools, destructive commands and existing hooks.
- **`decisions` in `answers.json`.** Each clash is recorded with what was found, a recommendation, why, a pro and a
  con.
  - The installer refuses one missing any part, and apply refuses while one is unanswered.
  - The review page opens with **Needs you**: each decision with its advice, open facts, packs to choose, and a
    glossary. The owner replies with codes or `accept`.
  - Answers are kept in the lock and written to `docs/agent/install-decisions.md`.
- **`exceptions`.** A project's opt-out of a kit deny rule (the migration tool under a standing yes) is recorded
  with its reason and the owner's yes (G7), and stays out on every apply and upgrade. Before this, it came back on
  every re-apply.
- **Word budget.** The guide gives the order: drop repeats of kit rules, move area rules into folder-scoped
  files, condense process notes (each rule kept as a line, its story moved to `docs/`), and only then raise the
  limit. Raising it is `options.word_budget` with a required `word_budget_reason`, never an edit to the CI workflow.
  The installed link check reads it from the lock.
- **Install worktree.**
  - The checkout's env files are linked in, so the tests run as they do in the checkout.
  - `INSTALL.md` adds a baseline test run before apply, so only new failures count as the install's doing.
- **`verify`** no longer reports a local-only (gitignored) file as missing in the install worktree.
- **`draft`** reads the synthetic-row marker from the schema, and maps only the MCP servers whose names the project
  prefix doesn't already give.
- **One schema rule everywhere.**
  - `CLAUDE.kit.md`, `AGENTS.md` and the Supabase pack's `database.md` now match `/guard`: a removal or reshape is
    one migration when nothing live breaks mid-change (backout, snapshot, every consumer moved), and phased
    otherwise.
  - The destructive step is G5, and a standing yes it falls under is recorded in `-- Purpose:`.
- **No hand edits after `apply`:** changes go through the answers. The README's existing-project section gets a
  "what to expect" list.

**Upgrade touches:**
- `CLAUDE.kit.md` (one tagged line) and `AGENTS.md`;
- `.claude/rules/database.md` (the Supabase pack);
- `.github/scripts/check_skill_links.py`.

## 1.9.2 — 2026-11-18

- **The branch the checkout is on no longer matters.** `draft` creates the install worktree (`agent-kit/install`,
  from `origin/<MAIN_BRANCH>`) and reads the project's tracked files there: package scripts, docs, `CLAUDE.md`,
  `settings.json`. Only local-only files and the lanes come from the checkout. A checkout parked on an unmerged
  branch, or holding uncommitted edits, can't leak into the install, and nobody has to switch branches first.
- `preflight` notes the checkout's branch, and says it isn't part of the install.
- `INSTALL.md`: the agent reads the project's own commands and rules in the install worktree, never in the
  checkout.

**Upgrade touches:** nothing installed.

## 1.9.1 — 2026-11-18

- **README: install into a new project vs an existing one.** Each case is spelled out: a new project needs a git
  repo, a GitHub `origin` and a pushed `main` first, which the agent offers to set up. An existing project installs
  from its real folder, and its work in progress is left untouched.
- **`preflight` fixes say how to set up a new project:** `git init`, a first commit, then
  `gh repo create <name> --private --source . --push`. `INSTALL.md` tells the agent to offer this, and to create
  the repo only with the owner's yes.

**Upgrade touches:** nothing installed.

## 1.9.0 — 2026-11-18

**A guided installer: three owner touch points instead of a string of questions.** A real install exposed four
problems:
- it ran from a fresh clone, which lacks the local-only files (`.mcp.json`, `.env*`) the install needs;
- it asked one at a time for answers the project already held;
- it found a blocker (an unauthorized Jira connector) halfway through;
- it bundled two packs into one choice.

New installer commands (`installer/agent_kit.py`):
- **`preflight`** reports every blocker before the first question, each with its fix:
  - git: origin, uncommitted changes, worktree lanes, work in flight;
  - tools: Python, Node, `gh`;
  - local-only files: names only;
  - the MCP server each pack needs.

  The installing agent then makes one read call through each server.
- **`draft`** writes the answers it finds, each `{value, source: found | default | guess | ask, evidence}`:
  - the ticket and branch prefixes, from branch names and commits;
  - `MCP_PREFIX`, and `mcp_map` to the project's own servers;
  - the worktrees pack, `WORKTREE_DIR` and the env files, from `git worktree list`;
  - the open-items ticket and Jira site, from the docs;
  - choice-only packs to ask about, saying when the project already has one.
- **`review`** writes the one page the owner approves:
  - A. blockers;
  - B. answers, with source and evidence;
  - C. what happens to each existing file;
  - D. what gets added;
  - E. after-merge steps;
  - F., on an upgrade: the CHANGELOG since the installed version.
- **`plan | apply | upgrade --worktree`:** `--target` is the real checkout. The install is built in its own
  worktree, on branch `agent-kit/install` from `origin/<MAIN_BRANCH>`, and the checkout and its lanes are never
  written. A gitignored `.mcp.json` is read from the checkout. A server the kit must add is written there, the only
  copy, and only when the page listed it.
- **`answers.json` accepts the draft form,** and refuses while a fact is still `ask`.

`INSTALL.md` and the README install section are rewritten around these steps. A test covers each: a real git
checkout with an origin and a lane, before-and-after snapshots, local-only `.mcp.json` routing, and an upgrade.

**Upgrade touches:** nothing installed. The installer and `INSTALL.md` are used at install time.

## 1.8.2 — 2026-11-18

- **INSTALL.md: one pack per choice.** The install asks about each pack on its own, and never bundles two packs
  into one option. When the project already has what a pack adds (a status line, a notify script, a worktree
  manager), the option says so, and says what choosing the pack would do.

**Upgrade touches:** nothing installed. `INSTALL.md` is read by the installing agent.

## 1.8.1 — 2026-11-18

- **The two new records are fill-in JSON forms, not formatted notes.**
  - `.claude/state/<ticket>/plan-check.json` replaces the state-homes table and the `Contradiction check:` /
    `Lifecycle check:` lines in `triage.md`;
  - `.claude/state/<ticket>/inventory.json` replaces `inventory.md`;
  - `check-record.py` checks that each box is filled and never guesses at layout, so a complete note is never
    refused for how it was written;
  - `check-record.py --show plan-check|inventory --ticket <T>` prints the readable Markdown copy for the ticket
    comment. The JSON file is the one home.
- **A "targeted fix" answer at a spiral assessment** that would push the next round past the limit now counts as
  the owner-granted round, so the fix is still reviewed and post-op doesn't escalate a second time.

**Upgrade touches:**
- `.claude/hooks/check-record.py`;
- `.claude/commands/{triage,operate,post-op}.md`.

A ticket in flight under 1.8.0 rewrites its `inventory.md` and Step 4.8 lines as the two JSON files before its next
record check.

## 1.8.0 — 2026-11-18 (ticket-trains 1.1.0, hardening 1.0.2)

Quality first: write the first draft right, hold every fix to the same bar, and never end a ticket with known defects.
A root-cause study of multi-round tickets found 67% of real defects in the first draft, 33% introduced by review
fixes, and 41% of findings repeats of decided items. Rationale: `docs/workflow/history/review-loop.md` ("Quality
first").

- **`/triage` Step 4.8, plan self-check:**
  - a state-homes table (one fact, one home; two copies only in one transaction or by a database trigger, with
    the owner's OK);
  - a contradiction check, contract rows against decisions;
  - a lifecycle check for every state the ticket adds or changes;
  - every safety default shown to the owner.

  `check-record.py --kind triage` requires all of them.
- **`/operate` dependency inventory:**
  - `.claude/state/<ticket>/inventory.md` is written before the first production edit;
  - Table 1a lists the readers and writers of every value changed, each with `file:line` and the search that found
    it. Table 1b lists siblings and their guards. Helper contracts get one line each;
  - every fix batch appends `## Fix batch <n>`;
  - `check-record.py --kind operate` requires the inventory, plus an `Inventory:` line in the self-review record;
  - the design step gains two rows. Hand-built language classifiers → a stored field, else the cheapest
    classifier that passes the tests: a dedicated classification model, then a general model call (the one
    `docs/agent/integrations.md` lists), acting only above a recorded probability threshold. One fact kept in two
    places → one home.
- **`/post-op` round rules:**
  - **No `capped` end state.** Post-op ends `clean`, or `escalate`. The only passing `escalate` is the owner
    accepting named defects. No fix ships unreviewed: with the round limit reached, a needed change escalates.
  - **Origin decides for the ticket's own code.** Each finding is `first-draft`, `fix-introduced` or
    `pre-existing`. A real defect in code the ticket wrote is fixed at any class. Only pre-existing below-bar
    defects are `noted` and filed on the tracker. A new `nit` disposition (no wrong behaviour) is neither fixed nor
    filed.
  - **Spiral rule (round rule 10).** It fires on a second real finding in one area, and when round 3 still finds
    the ticket's own defects. Before any edit, post-op writes a spiral assessment covering origins, the simplest
    approach, state, a self-check, classification in code and a recommendation, and the owner decides.
  - **New self-red-team probes:** the inventory audit and `Deliberate (decided R<n>-<k>)` markers.
  - **Round records** number findings `R<n>-<k>` and carry an `Origins:` line, so a project can measure its first
    drafts.
- **`consensus-review` workflow:**
  - reviewers now get the decided list, and verifiers vote on `origin`;
  - `nit` is a class;
  - the result adds `nits` and `origins`, `must_fix` includes the ticket's own below-bar defects, and `noted` holds
    only pre-existing ones.
- **`/ship`:**
  - refuses a legacy `Result: capped` (re-run `/post-op`);
  - files only pre-existing noted items and owner-accepted defects.
- **`/peer-review`:** a defect introduced by the diff is must-fix at any class, and fixes need their inventory.
- **ticket-trains 1.1.0:** `END_STATES` drops `capped`, and `nit` is accepted as a disposition and class.
- **hardening 1.0.2:** follows the new end states. A must-fix left after the third snapshot escalates.

**Upgrade touches:**
- `CLAUDE.kit.md`;
- `.claude/commands/{triage,operate,post-op,peer-review,ship}.md`;
- `.claude/workflows/consensus-review.js`;
- `.claude/hooks/check-record.py`;
- the ticket-trains and hardening commands and scripts.

A ticket in flight across the upgrade needs `inventory.md` and the triage Step 4.8 lines before its next record
check, and a re-run of `/post-op` if its record says `capped`.

## 1.7.1 — 2026-11-13 (hardening 1.0.1)

- **hardening pack: `block-push-before-review.py` closes the routes to main it missed.** While a hardening run hasn't
  passed post-op it now also blocks:
  - any write through the GitHub API from `gh api`, `curl`, `wget`, httpie or `xh` (a method other than GET/HEAD, in
    any spelling such as `-sXPUT` or `--method=put`; the host in any case, with a port or a trailing dot; paths with
    `..` resolved; curl's `--request-target`; a host in a variable when the path shows it's the GitHub API), except
    comments, labels, reviews, review requests, issues and opening or editing a PR. That covers PR merges, `/merges`,
    ref updates and contents writes. httpie and xh send stdin as a body without saying
    so, so for them only an explicit `GET` / `HEAD` is a read;
  - GraphQL mutations (also JSON-escaped in a body file), and a GraphQL write whose query is a shell variable, an
    unreadable file or unseen stdin;
  - inline code (`python3 -c`, `node -e`, a script on stdin) that runs `gh pr merge`, `gh api`, a migration or a push
    to main (also in list form, `['gh', 'pr', 'merge']`), writes to the GitHub API, or merges through a GitHub client
    library (PyGithub, Octokit);
  - `git push` with a `:` or glob refspec, and `HEAD` / `@` / a shell-filled branch name or a bare `git push` while
    on the main branch, including after a `git checkout main` / `git switch main` earlier in the same command; git's
    `--config-env` option before `push`;
  - `gh pr merge` with `-R` / `--repo` before `merge`;
  - GitHub MCP `merge_pull_request`, and `push_files` / `create_or_update_file` / `delete_file` on the main branch or
    with no branch named (a GitHub server by name, or a tool input with `owner` and `repo`).
- **It reads commands with the core parser** (`kit_shell.py`) and finds these tools, and a shell's `-c` code, anywhere
  in a command's words, so `bash -c "…"`, `eval`, heredoc scripts, `xargs` and launchers such as `op run --`,
  `caffeinate -i`, `watch -n 5` or `docker compose exec api sh -c "…"` don't hide them. A quoted word with spaces (a commit message, a grep pattern) is data, and so are
  the words of a program that only searches or reads them (`grep`, `cat`, `man`), so a command that only mentions a
  merge or a migration is no longer blocked. Without the parser, or when a command doesn't
  parse, it falls back to the old raw-text match.
- **Fix: the hook's MCP entry was never installed.** The installer merges hooks by command text, and the MCP entry
  had the same command as the Bash one, so it was dropped: MCP `apply_migration` tools were never checked. The MCP
  entry now runs `block-push-before-review.py --mcp-tools` (the argument is ignored), so install and upgrade add it.
  A new kit test fails when two hook entries share an event and a command.
- Known gaps: a script file run by name, a command held in a variable or a quoted launcher string
  (`watch "gh pr merge 1"`), curl `-K` config files, a `gh` alias.

**Upgrade touches:** `.claude/settings.json` (adds the hardening hook's MCP entry), `.claude/hooks/block-push-before-review.py`,
its test and `.claude/packs/hardening.md`, if the hardening pack is installed.

## 1.7.0 — 2026-11-11

- **New pack `statusline` (extra, asked at install).** A Claude Code status line:
  `<model> · <branch> · <ticket> · context <n>% used`, from the status-line JSON, local git and the Project facts.
  It shows `context –` before the first reply and after a compaction. No network, no writes.
- **Packs can set top-level settings,** through a new `settings` key in `pack.json`. It is an allow-list:
  `statusLine` only, for now. A key is added only when the project has none, the kit's own earlier value is updated
  on upgrade (the lock records it), and the install plan says when the project's own value is kept. A project
  status line overrides a developer's personal one, and the plan warns when you have one.

**Upgrade touches:** nothing unless you add the `statusline` pack. Then `.claude/settings.json` (adds `statusLine`
if absent), `.claude/scripts/statusline.py` and `.claude/packs/statusline.md`.

## 1.6.1 — 2026-11-11

- **notify-telegram 1.1.0: waiting pings.** A Notification hook (`notify-waiting.py`) pings the project's chat when
  Claude is waiting on a permission prompt or sits idle: `[<PROJECT_NAME>] Waiting for you: <reason>`. It sends at
  most one ping per 10 minutes per session, and only the event type and tool name, never the prompt text. A
  failed send is reported and doesn't use up the 10-minute slot. It is installed only with the pack.
- **node-esm 1.1.0, typescript 1.1.0: dependency vulnerability audit.** A `## /security` section runs
  `npm audit --omit=dev --json` (or the pnpm / yarn form for that lockfile) and reports direct vs transitive and
  whether a fix exists. A reachable critical or high advisory in a runtime dependency is S2. A ticket must fix an
  S2 only when its own lockfile change brought it in or its code newly calls the vulnerable code. One already on
  main is class `noted` for the ticket (the verdict stays CLEAR): shown as
  `⚠️ pre-existing` on the `Pack checks:` line and posted in a `Noted for the tracker (security <date>)` comment,
  which `/ship` files on the open-items ticket. The rest is `noted`. `/release` runs the same audit and blocks on any
  open S2.
  - A workspace is audited once, at its root lockfile.
  - Yarn 2+ audits transitive dependencies (`--all --recursive`).
  - Non-zero exits with JSON advisories are results. No lockfile, a Bun lockfile, or output with no JSON (offline,
    registry error) reads as "not run", never as a pass.
  - Allow rules cover only the exact read-only audit commands. `npm audit fix`, `pnpm audit --fix` and
    `pnpm audit --ignore…` are denied, global flags before `audit` included.
- **Conventions:** future stack packs add their ecosystem's audit the same way (`pip-audit`, `govulncheck`).

**Upgrade touches:** with notify-telegram, `.claude/settings.json` (adds the Notification hook) and
`.claude/hooks/notify-waiting.py`; with node-esm or typescript, `.claude/packs/<pack>.md` and the allow rules in
`.claude/settings.json`; always, `docs/workflow/ticket-ops.md` (adds the `Noted for the tracker (security …)` row) and
`.claude/commands/post-op.md` (round rule 11 names that comment).

## 1.6.0 — 2026-11-11

- **Record checks (`check-record.py`, core).** `/triage`, `/operate`, `/post-op` and `/handoff` now start with
  `check-record.py --start <kind>` and end with `check-record.py --kind <kind>`, which checks the record the
  command must leave:
  - **triage:** the contract table, with at least one row;
  - **operate:** a `Fingerprint:` line;
  - **post-op:** `Fingerprint:` and `Result:`;
  - **handoff:** a fresh `latest.md` with its git block.

  A **Stop hook** catches a command that started and never passed its check, and sends Claude back with what's
  missing, **once per run**: a command waiting on a background review or the owner isn't pushed to fake a record.
  It checks only the current branch's ticket, and costs nothing when no command is open. A command that stops early
  on purpose runs `check-record.py --cancel <kind>`. A marker older than 24 h is closed (checked or abandoned), and
  session-context reports abandoned runs. Markers are renamed, never deleted or overwritten. Codex runs the same steps
  from the command text.
- **Session context (`session-context.py`, core).** On startup, resume and after a compaction, a SessionStart hook
  prints up to 15 lines:
  - the branch, ticket, commits ahead and changed files;
  - which records exist, and a pointer to the contract;
  - an unfinished command;
  - "run `/resume`" when a handoff is newer than the last commit.

  It works in the checkout the session is in (a worktree's own root), shows the handoff hint only for the branch the
  handoff was written on, and prints paths and status words only, never file contents. Codex has no session hooks; `/resume` stays the
  manual path.
- **Allow rule** `Bash(python3 .claude/hooks/check-record.py *)`.

**Upgrade touches:** `.claude/settings.json` (adds the Stop and SessionStart hooks and the allow rule; your own
hooks are kept), `.claude/hooks/` (adds `check-record.py` and `session-context.py`), `.claude/commands/triage.md`,
`operate.md`, `post-op.md`, `handoff.md`.

## 1.5.1 — 2026-11-11

- **New hook `guard-commit-message.py` (core).** It checks the message of `git commit` (`-m`, `--message`, `-F` file
  or stdin, and the `-m "$(cat <<'EOF' … EOF)"` form) and the text of `gh pr` / `gh issue` `create`, `edit`,
  `comment` and `review`, and of `gh pr merge` (`--subject`, `--body`: the squash commit).
  - **Attribution:** blocks a `Co-Authored-By:` trailer (in the text or through `--trailer`), a "Generated with
    <AI tool>" line or a 🤖 Claude Code line, on any branch. Bundled flags (`-am`), `--message=`, `$'…'`, a piped
    `-F -` and several heredoc messages in one command are all read correctly.
  - **Ticket commits:** on a ticket branch (`<BRANCH_PREFIX><ticket-lowercase>-<n>-<slug>`), the subject must start
    with `<TICKET>-<n>: `, that exact ticket in upper case. Any subject is fine on other branches.
  - Commits with no message argument (the editor, `--amend --no-edit`) are allowed. When the hook can't see the
    whole message (a file written earlier in the same command, `$(cat msg.txt)`), or with `--fixup` / `--squash`,
    it skips the ticket check.
- `block-main-branch.py` now reads the facts through `kit_facts.py`.
- **Shared facts reader `kit_facts.py`** in `.claude/hooks/`: the Project facts table and branch → ticket.

**Upgrade touches:** `.claude/settings.json` (adds the `guard-commit-message.py` PreToolUse hook), `.claude/hooks/`
(adds `guard-commit-message.py` and `kit_facts.py`).

## 1.5.0 — 2026-11-11

- **New hook `guard-secrets.py` (core),** on Read, Edit, Write, MultiEdit, NotebookEdit, Bash and Grep.
  - **Secret files:** blocks opening, printing or copying `.env` / `.env.*` / `*.env` / `.envrc` (templates such as
    `.env.example` are fine), private keys (`*.pem`, `*.key`, `*.p8`, `*.p12`, `*.pfx`, `id_rsa*`, `id_ed25519*`, `id_ecdsa*`),
    `.claude/notify.env`, `.netrc`, `.git-credentials`, cloud CLI credentials (`.aws/credentials`, `.docker/config.json`,
    `.kube/config`, `.config/gh/hosts.yml`), and `.npmrc` / `.pypirc` that hold a literal token (an `${ENV}` reference
    is fine). `~/…` and `$HOME/…` paths are expanded. In Bash it checks the files given to readers, copiers and archivers (`cat`, `grep`, `sed`, `cp`, `cp -t`,
    `tar`, …), globs such as `cat .env*`, `< file` redirects, `git show HEAD:.env`, and files sent with
    `curl -d @file` / `-F x=@file` / `-T file`. Writing a *new* `.env` is allowed, and so is `source .env` /
    `. .env` (env files only; sourcing a key or token file would print it in shell errors): loading the values doesn't print them, and the print checks below still apply (with `set -x` / `set -v`
    on in the same command it would, so that is blocked).
  - **Recursive searches:** `grep -r`, `rg` or `ag` over a folder that holds a secret file the tool would read (rg and
    ag skip hidden and gitignored files unless told otherwise; an rg include glob such as `-g '.env*'` overrides that) is blocked unless the command excludes it by name: the message says to add `--exclude='.env*'` (rg:
    `-g '!.env*'`). Glob and brace operands (`grep -rn KEY *`) and followed symlinks (`grep -R`) count; a path
    glob (`--exclude=app/.env`) doesn't exclude. `-l` / `-c` / `-q`
    (names, counts, nothing) are fine, and dependency folders (`node_modules`, `.venv`, `vendor`) are skipped.
  - **Environment dumps:** blocks `env`, `printenv`, bare `set` and `export -p` with no command or names, and
    `printenv` / `declare -p` / `echo $NAME` of a secret-looking name (`*_TOKEN`, `*_KEY`, `*PASSWORD*`, a
    `DATABASE_URL`-style connection string, …). `set -x`, `printenv SSH_AUTH_SOCK` and
    `echo "$TOKEN" | docker login --password-stdin` are fine.
  - **Secret content:** blocks writing a token shape (JWT, `sk-`, GitHub, AWS, Slack, Supabase, Render, Atlassian,
    Telegram bot, private key) or a URL with an inline password into a file or a command. The message names the
    shape and line, never the value. A line marked `agent-kit: allow-secret-shape` (for test fixtures) is skipped.
    Templates (`.example`, `.sample`, `.template`, `.dist`) are committed, so they're scanned for tokens too; only
    their sample URLs are left alone. Placeholders (`${VAR}`, `${VAR:-default}`, `{password}`, `#{x}`, `%s`, `<pass>`)
    and localhost dev URLs aren't secrets. The content scan runs even when a command can't be parsed.
- **Rule text:** the No secrets rule in `CLAUDE.kit.md` and its `AGENTS.md` restatement now say "`source` an env
  file only to run a command", matching the hook.
- **New project-owned file `docs/agent/secret-files.md`:** your extra secret-file globs, one per bullet. The kit
  defaults are always enforced; the file only adds.
- **Parser:** `env` or `sudo` with nothing after it is now reported as the command itself, and a redirect on a
  keyword (`done < file`) is kept.
- **Kit test:** every token-shape entry in the manifest denylist must have a rule in the hook and a blocked sample.
  The No secrets rule must carry the env-file exception the hook allows, and `AGENTS.md.tmpl`'s restated block
  must equal the tagged lines it copies.

**Upgrade touches:** `.claude/settings.json` (adds the `guard-secrets.py` PreToolUse hook), `.claude/hooks/` (adds
`guard-secrets.py`, updates `kit_shell.py`), `CLAUDE.kit.md`, the `AGENTS.md` Codex section, `docs/agent/secret-files.md`
(created if absent, never overwritten).

## 1.4.0 — 2026-11-11

- **New hook `block-destructive.py` (core).** It blocks destructive filesystem and git commands that the deny list
  can't see: options before the subcommand (`git -C x reset --hard`), combined short flags (`git push -uf`),
  `+refspec` force pushes, `git checkout <path>` / `<rev> <path>` / `--ours`, `git branch -f`, `git checkout -B` / `git switch -C` / `git branch -M/-C` over a branch that already exists (a new name is allowed), `git restore`
  (allowed: `--staged` alone), `git rm` (allowed: `--cached`), `find -delete`, and deletes passed as arguments
  (`xargs rm`, `find -exec rm`, `bash -c "…"`, `bash <<'EOF'`, `eval`, `git submodule foreach`, and `python3 -c` /
  `node -e` / `perl -e` / `python3 - <<'EOF'` code, also behind `uv run` / `poetry run` / `npx`). `rm` is allowed only when every operand is a plain path inside this session's
  scratch dir or `.claude/state/tmp/` (no globs or `$`, symlinks and `..` resolved, never the root itself). The
  settings deny rules still win, so `rm -rf` stays refused even there. The block message names the rule and the
  allowed alternative.
- **Shared shell parser `kit_shell.py`** in `.claude/hooks/`. The hooks parse commands instead of matching text, so
  `git commit -m "drop the rm call"` and `grep "rm -rf" docs/` are allowed. It now also reads `$(…)`, backticks,
  `<(…)`, `eval`, `xargs` and `find -exec` payloads, scripts fed to a shell (`bash <<'EOF'`, `bash <<< "…"`), and
  `$(…)` inside an unquoted heredoc. A `cd` inside `( … )` or a pipeline doesn't carry over to later commands.
  `block-main-branch.py` uses it, so it now also catches a push to main inside `$(…)` or `bash -o pipefail -c`, and
  it no longer blocks `git checkout -b feat && git commit` run from main (the commit lands on `feat`).
- **Core hooks are declared in `core/pack.json`** (they were in the settings template). The main-branch hook's
  command is unchanged, so an upgrade doesn't add it twice.
- **Kit test:** every `destructive_patterns` reason in `manifest.json` must have a rule in the hook and a blocked
  test case.

**Upgrade touches:** `.claude/settings.json` (adds the `block-destructive.py` PreToolUse hook), `.claude/hooks/`
(adds `block-destructive.py` and `kit_shell.py`, updates `block-main-branch.py`).

## 1.3.1 — 2026-11-11

- **Wider destructive-command deny list.** The installed `.claude/settings.json` now also denies `rmdir`, `unlink`,
  `git stash drop` / `clear`, `git checkout -- <path>` / `<rev> -- <path>` / `.` / `<rev> .` / `-f` / `--force`,
  `git switch -f` / `--force` / `--discard-changes`, `git worktree remove --force` / `-f`, and the force flags of
  `git reset --hard`, `git branch -D` / `-f` / `--force` and `git push --force` / `-f` / `--force-with-lease` wherever
  they sit after the subcommand. Claude Code applies deny rules to every sub-command, including inside `$(…)`,
  subshells and loop bodies.
- **Left to the destructive-command guard hook (next release),** because a prefix rule can't express them or would
  also refuse an allowed form: options before the subcommand (`git -C x reset --hard`), combined short flags
  (`git push -uf`, `git branch -df`), `+refspec` force pushes, `git checkout <rev> <path>`, `git restore` (allowed
  with `--staged` alone), plain `rm` (allowed inside the session scratch dir), `git rm` (allowed with `--cached`), and
  deletes passed as arguments (`xargs rm`, `find -exec rm`, `bash -c "…"`).
- **Kit text checks:** `git restore`, `git switch -f` and `git worktree remove --force` join the destructive patterns
  the kit's own tests forbid in commands and rules.
- **Kept on purpose:** `Bash(rm -rf *)` and `Bash(git clean *)` stay denied, so `git clean -n` stays refused too.

**Upgrade touches:** `.claude/settings.json` (the new deny rules are appended; your own rules and their order are
kept).

## 1.3.0 — 2026-11-08

- **No AI attribution.** The installed `.claude/settings.json` sets Claude Code's `attribution` off (`commit` and
  `pr` empty, `sessionUrl` false), so commits get no `Co-Authored-By:` trailer and PRs no "Generated with" line. A
  project's own `attribution` setting is kept. `CLAUDE.kit.md`, `/ship` and `/hardening` say never to add one.
- **Removed fact `CO_AUTHOR_TRAILER`.** An old answer for it is reported as unused and ignored.
- **Codex:** Codex may add its own trailer, depending on your ChatGPT account settings. Check a Codex commit once.

**Upgrade touches:** `.claude/settings.json` (adds `attribution` if absent), `CLAUDE.kit.md`, the `CLAUDE.md` facts
block, `.claude/commands/ship.md`, and `hardening.md` if installed.

## 1.2.0 — 2026-11-08

- **Per-project MCP server names.** New required core fact `MCP_PREFIX` (for example `acme_`). Kit servers install
  as `<MCP_PREFIX><service>`, and the installer rewrites every `mcp__<server>__` permission and text reference, and
  owner task, to the installed name. `none` keeps the plain names.
- **Fix:** with `mcp_map`, the kit's permissions and the Jira tool references still named the kit's server, so
  allow and deny rules (including the `apply_migration` deny) didn't match the project's server. They now follow the
  mapped name.
- **Jira:** the pack's server is now named `jira` (was `atlassian`).

**Upgrade touches:** `.mcp.json` (servers re-added under the new names; the old entries are reported as orphaned
and left in place for you to remove), `.claude/settings.json` permissions, `.claude/rules/ticket-ops.md`, the
`CLAUDE.md` facts block. Answer `MCP_PREFIX` when upgrading.

## 1.1.0 — 2026-11-08

- **New pack `turnstile`:** Cloudflare Turnstile bot protection. It installs Cloudflare's `turnstile-spin` setup
  skill (Apache-2.0) from GitHub at a pinned commit, checked by hash. It adds a contract row to `/triage` for public
  actions that cost money, siteverify checks to `/security`, and a real-token, replay and no-token check to `/verify`.
- **Version:** `manifest.json` and `core/pack.json` now carry the release version. v1.0.0 shipped them as
  `1.0.0-dev`.

**Upgrade touches:** the kit version in the lock file only, unless you add the `turnstile` pack.

## 1.0.0 — 2026-11-07

First release.

- **Core:**
  - 19 workflow commands: triage, operate, post-op, peer-review, bteam, codex-review, ship, verify, test,
    investigate, handoff, resume, observability, security, api-contract, guard, compliance, docs-update, release.
  - The consensus-review workflow.
  - The `kit-tools.mjs` fingerprint helper.
  - The `CLAUDE.kit.md`, `CLAUDE.md` and `AGENTS.md` templates.
  - Four rules.
  - Project-doc stubs, with seeded defect classes.
  - The main-branch guard hook.
  - The settings template.
- **Packs:** jira, supabase, render, expo-mobile, web-qa, typescript, node-esm, notify-telegram, worktrees,
  ticket-trains, hardening. Extras: scrollcraft, pressure-test, fal-media, remotion, cold-email, cloudflare.
- **Claude↔Codex sync:** a wrapper generator, a link checker and a CI workflow.
- **Installer:** scan, plan, apply, upgrade, verify, third-party.

**Upgrade touches:** nothing (first install).
