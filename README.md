<!-- Copyright 2026 Tharwat Abdul-Malik. Licensed under the MIT License (see LICENSE). -->
# agent-kit

A set of working conventions for **Claude Code and Codex**: a full ticket workflow, a review loop, rules, hooks and
Claude↔Codex sync. You can install it into any project, new or existing. An AI agent does the install: it scans the
project, asks only what it can't work out itself, shows you a plan, and writes nothing until you approve it.

- [Install](#install)
- [After installing](#after-installing)
- [Using it](#using-it)
- [Commands](#commands)
- [Ground rules and hooks](#ground-rules-and-hooks)
- [Packs](#packs)
- [Codex](#codex)
- [Upgrading](#upgrading)
- [Installing without an agent](#installing-without-an-agent)
- [Developing the kit](#developing-the-kit)

## Install

The same one line installs into a new project or an existing one. Open Claude Code (or Codex) in the project's
folder and paste:

> Read https://github.com/tharwat/agent-kit/blob/main/INSTALL.md and follow it for this project.

**A new project** (an empty folder, or code that isn't in git or on GitHub yet):
- The kit needs a git repo with a GitHub `origin` and a pushed `main`, because reviews and the install compare
  against `origin/main`. If those are missing, the agent offers to set them up (`git init`, a first commit, a
  private GitHub repo) and asks you first.
- With no code yet, it asks what you'll build (language, framework, database, hosting) and proposes the packs from
  that.

**An existing project** (already in git, maybe with its own workflow, `CLAUDE.md`, hooks or MCP servers):
- Start it in your **real project folder**, not a fresh clone. A clone is missing your local-only files
  (`.mcp.json`, `.env*`, `settings.local.json`), which the install reads.
- It's safe while you have work in progress. It lists your uncommitted changes, other worktrees and unmerged
  branches, and never touches them. Merge the install PR between tickets.
- Your own commands, rules and hooks show up on the review page, each with what will happen to it: kept, merged,
  or replaced (the original is kept as `.pre-agent-kit`).
- **Where your rules and the kit's differ,** each difference is a decision with a recommendation, why, a pro and a
  con, based on what was found in your project. Examples: schema changes, refactoring, standing owner approvals,
  review rounds. Reply with codes, or `accept`. Your answers are written to `docs/agent/install-decisions.md`, so
  later sessions and upgrades don't ask again.
- **What to expect:**
  - Replaced files and old Codex wrappers are kept as `*.pre-agent-kit`. Remove them once you're happy.
  - If your project has tests that check its old workflow files' text, they fail once those files are replaced.
    The agent points guards for your own rules at their new place, and offers to retire tests of the old wording.
  - A long `CLAUDE.md` is moved into folder-scoped rules to fit the always-loaded budget. Your safety rules stay
    always loaded, and the budget is raised, with a recorded reason, if they need the room.
  - Your tests run before and after the install, in the install folder. Only new failures are the install's doing.
  - An exception you approve to a kit safety setting (say, migrations without a prompt) is recorded once and kept
    on every upgrade.

Either way, you do three things: start it, approve **one review page**, and say when to merge the PR. The agent:

1. **Checks for blockers first** (git, tools, MCP servers, work in flight) and reports them all at once, each with
   its fix.
2. **Finds the answers itself:**
   - your ticket prefix, from branch names and commits;
   - the MCP servers you already use, mapped by name;
   - your worktree lanes and env files;
   - test commands, and the open-items ticket from your docs;
   - a proposal for the few judgment facts.
3. **Shows one review page:**
   - blockers;
   - every answer, with where it came from;
   - what happens to each of your files;
   - what gets added;
   - what's left after the merge.

   You correct anything in plain words. It asks only what it truly couldn't find. **Nothing is written until you
   approve.**
4. **Installs in its own git worktree,** on branch `agent-kit/install`. Your checkout and your other worktrees are
   never written. It runs the checks and your tests there, then opens the PR.
5. **You merge between tickets.** Every lane then picks the kit up from `main`.

It **never deletes anything**. A file it replaces is renamed `<file>.pre-agent-kit` and kept. Your own `CLAUDE.md`
content is kept, and the kit's rules go in a separate `CLAUDE.kit.md` that `CLAUDE.md` imports.

**Requirements:**
- Python 3.9+, Node 18+ and git.
- A ticket system. v1 supports **Jira** through the Atlassian MCP server.
- `/ship` needs a GitHub remote and the `gh` CLI. Without them, everything else still works, and you open and merge
  PRs by hand.

## After installing

**Merge the install PR first,** then branch tickets from `main`.

**What was added to your repo:**

| Path | What it is |
|---|---|
| `CLAUDE.md` | Your file. The kit adds a **Project facts** block (main branch, test command, log sink, ticket system…) and imports `CLAUDE.kit.md`. Your project rules go in its "Project rules" section |
| `CLAUDE.kit.md` | The kit's always-loaded rules. Don't edit it; upgrades replace it |
| `AGENTS.md` | The same contract for Codex: links to the above, plus the safety rules restated so Codex sees them |
| `.claude/commands/` | The workflow commands |
| `.claude/rules/` | Code style, testing, security and API-contract rules, plus pack rules that load only for matching paths |
| `.claude/hooks/`, `.claude/settings.json` | The guard hooks and permission allow/deny lists |
| `.claude/scripts/kit-tools.mjs` | Diff fingerprinting and review freezing, used by the review loop |
| `.claude/workflows/consensus-review.js` | The multi-reviewer review round |
| `.claude/packs/*.md` | Per-pack additions to core commands |
| `docs/agent/*.md` | **Yours to fill in** (see below). Upgrades never touch them |
| `docs/workflow/` | Ticket-ops reference and the history behind the rules |
| `.agents/skills/` | Codex skill wrappers, generated from the commands |
| `.github/workflows/skill-link-check.yml` | CI that keeps the Codex wrappers, `AGENTS.md` and the word budget in step |
| `.claude/agent-kit.lock.json` | Kit version, your answers, and a hash of every installed file |

**MCP servers are named per project.** The kit's servers install as `<prefix><service>`, for example
`acme_jira`, `acme_supabase` and `acme_render`. Every permission and tool reference follows that name, so an
agent in one project can't reach another project's Jira, database or host by mistake. They use `${ENV_VAR}`
references only, never a pasted token.

**Fill in the project docs.** The commands read these when they need detail about your project. Empty sections
are fine to begin with; fill them in as tickets need them.

| File | Used by | Holds |
|---|---|---|
| `verify-map.md` | `/verify`, `/test`, `/release`, QA commands | How to drive each surface (route, webhook, job, screen), seed commands, test accounts, irreversible side effects |
| `source-layout.md` | `/triage`, `/operate`, most gates | Where things live in the code |
| `integrations.md` | `/verify`, `/security`, `/api-contract`, `/investigate` | External services and how each webhook is signed |
| `pii.md` | `/security`, `/observability` | Which fields are personal data and how they may be logged |
| `copy-rules.md` | `/compliance`, `/docs-update` | Language, terminology and brand rules for user-facing text |
| `docs-map.md` | `/docs-update`, `/post-op` | Which docs to update when which code changes |
| `defect-classes.md` | `/triage`, `/operate`, `/post-op` | Bug classes this project has had, so reviews look for them |
| `lessons.md` | `/post-op` writes; `/triage`, `/operate`, `/investigate` read | Lessons recorded after each ticket |
| `sibling-paths.md` | `/triage`, `/operate`, `/investigate` | Code paths that must change together |
| `secret-files.md` | the `guard-secrets.py` hook | Extra secret-file globs agents must never open (the kit defaults always apply) |

**Do the owner tasks** the install report lists, for example creating a Telegram bot or installing a CLI a pack
uses.

## Using it

A ticket goes through five commands. Each one posts its result to the ticket as a comment, so the ticket is the
record of what was decided, built, reviewed and verified.

```
/triage PROJ-123 → /operate → /post-op → /peer-review (optional) → /ship
```

1. **`/triage PROJ-123`** reads the ticket and the real code, then writes an **acceptance-and-proof contract**.
   Each row is something the change must do, with its severity class, a hostile case and a counterfactual ("this
   test would fail without the change"). It records a threat-model line and asks you anything the ticket leaves
   open. It also writes a one-page **design page**: what exists today against what the change adds ("nothing" is
   an answer), where each fact a re-run needs is stored, how any open-ended work is closed, what an outside service
   was measured to do, and each file with its estimated lines. It writes no code.
2. **`/operate`** builds against the contract on a feature branch cut from `main`: tests first, then code. It ends
   with a self-review record tied to a fingerprint of the diff, so a later change to the diff is visible. It builds
   only what the design page adds, and stops when a file runs more than half again over its estimate.
3. **`/post-op`** checks the finished work:
   - a self-red-team pass and a contract audit;
   - eight gates: observability, security, API contract, migration guard, copy compliance, docs, tests and mock
     fidelity;
   - a **consensus review round**: three reviewers with different lenses on every area of the change, plus Codex
     when it is installed, with no cap on findings. Two verifiers try to refute each finding.

   The verifiers, not the author, decide what happens to a real finding. They answer what is lost and to whom, what
   has to happen first, whether anyone would notice, and what the fix costs. A serious loss and anything normal use
   reaches is fixed on the ticket. The first round sweeps the whole change and also fixes anything with a small
   fix. A later round checks only the fixes. Every other real defect goes into one follow-up ticket, with that
   analysis attached, so a round that finds nothing serious ends the review. A defect inside a fix stops the
   patching: you get a one-screen redesign note that must change the kind of solution and remove code. No round counter decides. It ends `clean` or `escalate`, never
   with a fix no reviewer read.
4. **`/peer-review`** (optional) freezes the diff, then has it reviewed by a zero-context second Claude and by Codex.
   Both reviews are bound to the frozen snapshot's hash.
5. **`/ship`** opens the PR to `main`, requires a passing `/verify`, and **asks for your yes before merging**. After
   the merge it checks the deploy and logs, files anything left open on your open-items ticket, and closes the
   ticket.

**Your decisions.** Agents decide everything except the seven Owner-Kept Gates below. Whenever a gate is reached,
the command stops and asks you. Nothing else needs you, unless a review escalates.

**Between sessions,** run `/handoff` before a compact or when you stop, and `/resume` when you start again.

**For a bug,** `/investigate` finds and proves the root cause before anything is fixed. **For a release,**
`/release` runs the go/no-go checklist and stops for your yes.

## Commands

**Workflow:** `/triage`, `/operate`, `/post-op`, `/peer-review` and `/ship`, as above.

| Command | What it does |
|---|---|
| `/verify [<ticket>]` | Drives the changed route, webhook, job or screen end to end against real services before merge, then confirms the deploy and logs after merge. Rows it creates are marked synthetic and torn down by ID |
| `/test` | Finds test gaps in the change, writes the missing tests, runs the suite and proves each contract row |
| `/investigate` | Finds and confirms a bug's root cause before the fix, then proves the fix |
| `/pressure-test [<ticket> \| idea]` | Five council members attack and defend an idea (a business, a feature or a ticket), then one GO / RESHAPE / KILL verdict and the cheapest test before building. `/triage` offers it for new features |
| `/release` | Go/no-go checklist for releasing `main` to production. Stops for your yes |
| `/handoff`, `/resume` | Save session state to `.claude/handoffs/latest.md` and restore it |
| `/bteam` | A zero-context, review-only Claude reviewer of a frozen snapshot. Also designs the pre-code test contract |
| `/codex-review` | The same, run by Codex in a read-only sandbox |
| `/security` | Secrets, PII in logs, auth and webhook holes, SSRF, unsafe output |
| `/api-contract` | Endpoint changes are additive, every consumer still matches, every external field is grounded in a real payload |
| `/guard` | Validates a schema change before it is applied. Never applies it |
| `/observability` | Logging you can diagnose from: prefixes, required log points, no swallowed failures, no secrets |
| `/compliance` | User-facing copy against your copy rules, with the corrected string for each violation |
| `/docs-update` | Updates the docs the change affects, using your docs map |

The gate commands (`/security` through `/docs-update`) run inside `/post-op`, and you can also run them on their own.

## Ground rules and hooks

Installed with the kit and binding on Claude and Codex alike:

- **One long-lived branch (`main`)** plus feature branches. Nothing is committed or pushed to `main` directly;
  `/ship` merges through a PR. A project that wants more long-lived branches adapts the commands itself.
- **Seven Owner-Kept Gates.** These always need your explicit yes at the time:
  1. production builds and releases;
  2. production data writes;
  3. merging to main;
  4. admin overrides;
  5. destructive schema steps;
  6. making data client-readable;
  7. weakening a safety check.
- **Additive-only API and schema changes.** Removing a field, route or column is phased, and its last step is a
  gate.
- **No destructive filesystem or git commands,** whether run or written into code and docs. Files are renamed, not
  deleted.
- **No secrets** in code, logs, commits, PRs or tickets, and no new dependency without your dependency policy.
- **No AI attribution:** commits and PRs get no `Co-Authored-By:` trailer or "Generated with" line. The installed
  settings turn Claude Code's attribution off, and a hook blocks a trailer written by hand.
- **A word budget** for instructions loaded in every session: 3,500 words in an installed project, with the kit using
  about 1,900 of them. The rest loads by path or on demand. CI checks it.

**Hooks** (blocking hooks exit 2 with the reason, and fail open on their own errors):

| Hook | From | Blocks |
|---|---|---|
| `block-main-branch.py` | core | `git commit` on `main`, any `git push` to `main` (forced or not), `gh pr merge --admin` |
| `block-destructive.py` | core | Deleting or discarding: `rm`, `rmdir`, `unlink`, `find -delete`, `git reset --hard`, `git clean`, `git branch -D`, force pushes, `git checkout -- <path>`, `git restore`, `git switch -f`, `git stash drop`, `git worktree remove --force`, and file deletes in `python -c` / `node -e` code. It parses the command, so `git -C x reset --hard`, `xargs rm`, `find -exec rm` and `bash -c "rm x"` are caught and `grep "rm -rf" docs/` isn't. Allowed: `git rm --cached`, `git restore --staged`, `git clean -n`, and `rm` inside the session scratch dir |
| `guard-secrets.py` | core | Opening, printing or copying a secret file (`.env`, private keys, `.netrc`, a token-holding `.npmrc`, plus your globs in `docs/agent/secret-files.md`), a recursive `grep` / `rg` over a folder holding one unless it's excluded, `env` / `printenv` dumps, and writing a token or a password-bearing URL into a file or command. The message names the shape and line, never the value |
| `guard-commit-message.py` | core | A `Co-Authored-By:` trailer or "Generated with" line in a commit, PR or issue text; on a ticket branch, a commit subject that doesn't start with `<TICKET>-<n>: ` |
| `check-record.py` | core | A Stop hook: ending the turn while `/triage`, `/operate`, `/post-op` or `/handoff` started and its record (contract table, `Fingerprint:`, `Result:`, handoff file) is missing or malformed. One nudge only. The same script is each command's last step, for Codex too |
| `session-context.py` | core | Nothing; on session start, resume and after a compaction it prints the branch, ticket, which records exist, an unfinished command, and "run `/resume`" when a handoff is newer than the last commit |
| `typecheck` | `typescript` | Runs the type checker after each edit and hands any type errors back to the agent to fix |
| `block_main_repo_writes.py` | `worktrees` | Writes into the main checkout from a worktree session |
| `notify-waiting.py` | `notify-telegram` | Nothing; pings your Telegram chat when a run waits on a permission prompt or sits idle (at most once per 10 minutes) |
| `block-push-before-review.py` | `hardening` | Push to `main`, merges and migrations during a hardening run until its review passes |

Hooks are guardrails, not a sandbox: a determined bypass (a script that deletes, an encoded command) gets past them.
The written rules in `CLAUDE.kit.md` still bind. Codex has no hooks and relies on the written rules.

`.claude/settings.json` adds a deny list for destructive commands (`rm -rf`, `rmdir`, `unlink`, `git reset --hard`,
`git clean`, force pushes, `git branch -D`/`-f`, `git checkout --`/`.`/`-f`, `git switch -f`, `git stash drop`/`clear`,
`git worktree remove --force`) and an allow list for the read-only commands the workflow runs, so routine steps don't
prompt you.

## Packs

The agent proposes packs that match your stack and asks about the rest. Only what you pick is installed. Packs add
rules, commands, hooks and Project facts, and extend core commands through `.claude/packs/<pack>.md`.

| Pack | Adds | Commands |
|---|---|---|
| `jira` | Ticket operations (get, comment, close, label, search, create) mapped to the Atlassian MCP server. Required in v1 | |
| `supabase` | RLS and grant rules, a migration-guard overlay, additive migrations applied before merge, a function-grants CI check | |
| `render` | Post-merge deploy and log checks, release checks, runtime-memory notes | |
| `expo-mobile` | EAS builds and Maestro QA for iOS and Android | `/build-qa`, `/build-qa-sim`, `/build-prod`, `/mobile-qa` |
| `web-qa` | Playwright E2E and visual QA | `/qa`, `/playwright-qa` |
| `typescript` | A type-check hook after each edit, vitest/jest discipline, a mock-fidelity lens, a dependency vulnerability audit in `/security` and `/release` | |
| `statusline` | A status line: model, branch, ticket and context-window use. A project `statusLine` already set is kept; as a project setting it overrides personal ones | |
| `node-esm` | ESM and Node rules for code with no compiler; a dependency vulnerability audit in `/security` and `/release` | |
| `notify-telegram` | Outcome notifications to one Telegram chat per project, plus a ping when a run waits on you (a permission prompt or idle). A failed send never fails a command | |
| `worktrees` | Parallel sessions in git worktrees: safe sync to `main`, env-file links, a guard against writing to the main checkout | `/worktree` |
| `ticket-trains` | Queue triaged tickets and run them unattended, with a circuit breaker and locked state. Running a train approves merging that queue only | `/ticket-train-create`, `/ticket-train-triage`, `/ticket-train-run`, `/ticket-train-status` |
| `hardening` | Deep-security mode: required peer review per ticket and a release-wide edge-case analysis | `/hardening`, `/hardening-analysis` |
| `turnstile` | Cloudflare Turnstile bot protection for sign-up, login, OTP and other public forms: Cloudflare's setup skill, plus server-side token checks in `/triage`, `/security` and `/verify`. Works on any host | |

## Codex

Codex reads `AGENTS.md` and `.agents/skills/<name>/SKILL.md`. Each skill is a short generated wrapper that links to
the matching `.claude/commands/<name>.md`, so Claude and Codex run the same instructions, and editing a command
changes it for both. After adding or renaming a command, regenerate the wrappers:

```
python3 .github/scripts/make_skill_links.py
```

To keep a command Claude-only, list it in `.agents/claude-only.txt`. CI (`skill-link-check.yml`) fails if a wrapper
is missing, stale or hand-copied, if `AGENTS.md` drifts from the rules it restates, or if the word budget is exceeded.

## Upgrading

Run the same one-line install prompt again. It follows the same path (preflight, one review page that adds what
changed in the kit, the install worktree, a PR) and compares each installed file against the hash in
`.claude/agent-kit.lock.json`:

- Files you haven't customized are updated.
- Files you customized are shown as conflicts, and you choose to keep yours or take the kit's.
- Your project's own files (`docs/agent/*`, your `CLAUDE.md` rules) are never touched.
- If a conflict is unresolved, nothing is written.

`CHANGELOG.md` lists what each version changes.

**Removing the kit** is manual. The lock file lists every installed file, and any file the kit replaced is still
there as `<file>.pre-agent-kit`.

## Installing without an agent

The installer is one stdlib Python script, and the agent drives it through these steps. You can run it yourself
from a clone of this repo:

```
python3 installer/agent_kit.py preflight --target <project>                           # every blocker, up front
python3 installer/agent_kit.py draft     --target <project> --out answers.json        # answers found, with sources
python3 installer/agent_kit.py review    --target <project> --answers answers.json    # the one page; makes the worktree
python3 installer/agent_kit.py apply     --target <project> --answers answers.json --worktree   # install there
python3 installer/agent_kit.py verify    --target <install worktree>                  # run the installed checks
python3 installer/agent_kit.py upgrade   --target <project> --worktree                # a later kit version
```

Edit `answers.json` between `draft` and `review`: fill every fact marked `ask`, check every `guess`.

`answers.json` holds your facts, chosen packs and conflict resolutions; `INSTALL.md` documents its format. Run each
subcommand with `-h` for its options.

## Developing the kit

```
INSTALL.md       the steps the installing agent follows
manifest.json    units, global questions, checks
core/            the always-installed unit: commands, rules, templates, hooks, scripts, workflows
packs/<name>/    opt-in units, each with a pack.json
sync/            Claude↔Codex wrapper generator and checker
installer/       agent_kit.py: preflight / draft / review / scan / plan / apply / upgrade / verify (stdlib Python)
schemas/         JSON schemas for manifest.json and pack.json
tests/           the kit's own tests
```

`docs/kit-conventions.md` is the contract every kit file follows: notation, Project facts, the branch model, gates,
the pack format and the hooks contract. Read it before changing a command or adding a pack.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

This runs the schema checks and the content checks: no project facts, no destructive instructions, every
placeholder defined, the word budget. It also runs the installer scenarios and every unit's own test suite (Python
and Node).

## License

MIT. Copyright 2026 Tharwat Abdul-Malik. Third-party skills keep their own licenses.
