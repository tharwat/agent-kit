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

Open Claude Code (or Codex) in your project and paste:

> Read https://github.com/tharwat/agent-kit/blob/main/INSTALL.md and follow it for this project.

The agent then:

1. Clones the kit into a scratch folder. Nothing of the kit is copied into your repo except what you approve.
2. Scans your project: stack, package manager, test and build commands, CI, existing `CLAUDE.md` / `AGENTS.md` /
   `.claude/`, hooks and MCP servers.
3. Asks you a few questions, one at a time, each option with a pro and a con. It asks which packs you want, and for
   any Project fact it couldn't detect.
4. Shows a **plan table**: every file it would add, skip, merge or treat as a conflict, with a reason for each.
   **It stops until you approve.**
5. Installs on a new branch, runs the checks, and reports what it did and what's left for you.

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
   open. It writes no code.
2. **`/operate`** builds against the contract on a feature branch cut from `main`: tests first, then code. It ends
   with a self-review record tied to a fingerprint of the diff, so a later change to the diff is visible.
3. **`/post-op`** checks the finished work:
   - a self-red-team pass and a contract audit;
   - eight gates: observability, security, API contract, migration guard, copy compliance, docs, tests and mock
     fidelity;
   - a **consensus review round**: three reviewers with different lenses, and each finding checked by two
     verifiers who try to refute it.

   Findings at severity S1–S4 must be fixed; lower ones are noted. It runs at most three rounds and ends `clean`,
   `capped` or `escalate`. An escalation tells you exactly what it needs from you.
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
  settings turn Claude Code's attribution off.
- **A word budget** for instructions loaded in every session: 3,500 words in an installed project, with the kit using
  about 1,900 of them. The rest loads by path or on demand. CI checks it.

**Hooks** (blocking hooks exit 2 with the reason, and fail open on their own errors):

| Hook | From | Blocks |
|---|---|---|
| `block-main-branch.py` | core | `git commit` on `main`, any `git push` to `main` (forced or not), `gh pr merge --admin` |
| `typecheck` | `typescript` | Runs the type checker after each edit and hands any type errors back to the agent to fix |
| `block_main_repo_writes.py` | `worktrees` | Writes into the main checkout from a worktree session |
| `block-push-before-review.py` | `hardening` | Push to `main`, merges and migrations during a hardening run until its review passes |

`.claude/settings.json` adds a deny list for destructive commands (`rm -rf`, `rmdir`, `unlink`, `git reset --hard`,
`git clean`, force pushes, `git branch -D`, `git checkout --`, `git switch -f`, `git stash drop`/`clear`,
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
| `typescript` | A type-check hook after each edit, vitest/jest discipline, a mock-fidelity lens | |
| `node-esm` | ESM and Node rules for code with no compiler | |
| `notify-telegram` | Outcome notifications to one Telegram chat per project. A failed send never fails a command | |
| `worktrees` | Parallel sessions in git worktrees: safe sync to `main`, env-file links, a guard against writing to the main checkout | `/worktree` |
| `ticket-trains` | Queue triaged tickets and run them unattended, with a circuit breaker and locked state. Running a train approves merging that queue only | `/ticket-train-create`, `/ticket-train-triage`, `/ticket-train-run`, `/ticket-train-status` |
| `hardening` | Deep-security mode: required peer review per ticket and a release-wide edge-case analysis | `/hardening`, `/hardening-analysis` |
| `turnstile` | Cloudflare Turnstile bot protection for sign-up, login, OTP and other public forms: Cloudflare's setup skill, plus server-side token checks in `/triage`, `/security` and `/verify`. Works on any host | |

**Extras** are opt-in skills that aren't part of the workflow:

| Extra | Adds |
|---|---|
| `scrollcraft` | Scroll-driven landing pages, with Segmind asset generation (a modified MIT fork) |
| `pressure-test` | `/pressure-test`: a five-member council attacks a business idea and returns GO / RESHAPE / KILL |
| `fal-media` | fal.ai image, video and audio generation skills |
| `remotion` | Remotion (video in React) best practices |
| `cold-email` | Cold email sequence generator |
| `cloudflare` | Choosing and building with Cloudflare products |

Third-party extras are installed from their source at a pinned commit and verified by hash, never copied into this
repo. They keep their own licenses.

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

Run the same one-line install prompt again. The agent compares each installed file against the hash in
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
python3 installer/agent_kit.py scan    --target <project>                          # what's there, suggested facts
python3 installer/agent_kit.py plan    --target <project> --answers answers.json   # the plan table; writes nothing
python3 installer/agent_kit.py apply   --target <project> --answers answers.json   # install
python3 installer/agent_kit.py verify  --target <project>                          # run the installed checks
python3 installer/agent_kit.py upgrade --target <project>                          # a later kit version
```

`answers.json` holds your facts, chosen packs and conflict resolutions; `INSTALL.md` documents its format. Run each
subcommand with `-h` for its options.

## Developing the kit

```
INSTALL.md       the steps the installing agent follows
manifest.json    units, global questions, checks
core/            the always-installed unit: commands, rules, templates, hooks, scripts, workflows
packs/<name>/    opt-in units, each with a pack.json
sync/            Claude↔Codex wrapper generator and checker
installer/       agent_kit.py: scan / plan / apply / upgrade / verify (stdlib Python)
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

MIT. Copyright 2026 Tharwat Abdul-Malik. Third-party skills keep their own licenses; the `scrollcraft` pack is a
modified fork of an MIT-licensed skill and keeps its original notice.
