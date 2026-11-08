<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Installing agent-kit into a project

You are an AI agent (Claude Code or Codex), and the owner asked you to install **agent-kit** into the project in
your current working directory. Follow these steps in order. The kit's installer script does every file write.
Your job is the judgment: scan, ask, show the plan, and resolve conflicts with the owner.

Rules for the whole install:
- **Ask the owner one question at a time**, in plain language, and give every option a pro and a con. Never ask what
  the scan already answered.
- **Change nothing** in the project until the owner approves the plan in Step 4.
- **Delete nothing, ever.** A replaced file is renamed to `<file>.pre-agent-kit`, and the owner removes it later.
  Don't run `rm`, `git clean`, `git reset --hard` or anything like them, and don't write them into any file.
- **Never read or copy a secret value.** For `.mcp.json`, `.env*` and settings files, look at key names only.
  Credentials become owner tasks, written as env var names.
- **Work on a branch.** Before Step 5, create `agent-kit/install` (or `agent-kit/upgrade-<version>`) from the
  project's main branch. Commit only when the owner says so.

## Step 0: Get the kit

Clone the kit into your scratch directory, never into the project. Use the session scratchpad if you have one,
otherwise a new temp dir:

```bash
git clone --depth 1 --branch main https://github.com/tharwat/agent-kit "<scratch>/agent-kit"
```

`--branch main` installs the latest kit. Use a tag (`--branch v1.0.0`) when the owner names a version. From here on, `<kit>` means that clone and `<project>` means the project root
(`git rev-parse --show-toplevel`).

Read `<kit>/manifest.json`, `<kit>/core/pack.json` and every `<kit>/packs/*/pack.json`. Python 3.9+ and Node 18+
must be available. If they aren't, tell the owner and stop.

## Step 1: Scan

```bash
python3 <kit>/installer/agent_kit.py scan --target <project>
```

The scan is read-only. It reports:
- package manifests and dependencies;
- framework files;
- the git remote host and default branch;
- existing `CLAUDE.md`, `AGENTS.md`, `.claude/commands`, `.agents/skills`;
- `.mcp.json` server **names**;
- `.github/workflows`;
- which packs' detection rules matched;
- whether `.claude/agent-kit.lock.json` exists.

**If the lock file exists, this is an upgrade. Go to "Upgrading" at the end.**

Then read the project's own `CLAUDE.md`, `AGENTS.md`, `.claude/commands/*`, `.claude/rules/*` and `.agents/skills/*`
so you understand what's already there. You'll need it for conflicts.

**Empty project** (no code yet, even if docs or old agent files exist): ask what will be built and with what
(language, framework, database, hosting, mobile or web). Pick the packs from those answers.

**Requirements to check now, and tell the owner about up front:**
- **`/ship` needs a git remote named `origin` on GitHub, with `gh` authenticated** in v1. Without one, the kit still
  installs, but the owner opens and merges PRs by hand.
- **The kit assumes one long-lived branch.** If the project uses a `qa` or `develop` branch, say so plainly. The
  installed commands work against `<MAIN_BRANCH>` only, and the owner adapts them for extra branches.
- **If `.mcp.json` is gitignored**, the MCP entries the kit adds stay local to this machine. Say so.

## Step 2: Ask

Collect `answers.json` (format below). Ask only what the scan didn't settle, one question at a time:

1. **Packs.** Propose the ones the scan matched, each with one line on what it adds. Then ask each pack's
   `detect.ask` question (worktrees, ticket trains, hardening, notify-telegram, extras). The ticket pack isn't
   asked for: it follows the `TICKET_SYSTEM` fact (v1 supports `jira`), and a ticket system is required.
2. **Core facts** from `core/pack.json` `facts`, in its order. Each has an `ask` and maybe a `default`. Offer the
   default, or the value the scan suggests (`suggested_facts`, e.g. `TEST_COMMANDS` from `package.json` scripts,
   `MAIN_BRANCH` from git), and let the owner confirm or change it. If a required fact has no default and the
   project has no evidence for it yet (no `eas.json`, no test runner), ask the owner. If they don't know, use the
   pack's example value and add an owner task to revisit it. Two need care:
   - `CRITICAL_DOMAIN`: "the one area of logic that must never be wrong here" (it is severity class S3). Give an
     example from the project's own domain.
   - `OPEN_ITEMS_TICKET`: offer to create the standing tracker ticket after install, through the ticket pack.
3. **Each chosen pack's facts** from its `pack.json`.
4. **GitHub:** does the project live on GitHub? The scan usually answers this (`origin_is_github`). If yes, the
   skill-link CI workflow is added. That workflow is CI, so also confirm `HAS_CI`: true only when merges must wait
   for required checks.

The kit assumes **one main branch plus feature branches**, with no QA branch. If the scan lists
`extra_long_lived_branches`, say so: the owner adapts the installed commands themselves.

## Step 3: Resolve what already exists

Run the plan to see conflicts:

```bash
python3 <kit>/installer/agent_kit.py plan --target <project> --answers <scratch>/answers.json
```

For every row marked `conflict`, decide with the owner, one at a time:

| Situation | Default |
|---|---|
| Same-name command or skill, clearly unrelated job | `kit-renamed`: the kit's copy installs as `<name>-kit.md`. Tell the owner that kit commands which call `/<name>` now need `/<name>-kit` |
| Same-name command or skill doing the same job | Show a short diff summary, then offer **keep theirs** (`keep-theirs`), **take the kit's** (`take-kit`; theirs is renamed `.pre-agent-kit`), or **merge** |
| Same-name **rule** | Default to **merge**. A project's rule usually holds project-specific content (PII fields, storage rules) that would stop loading if it were renamed aside |
| Project commands with no `description:` | Resolve the other conflicts first, then re-run `plan`: it lists the project's own commands that have no description. Offer to add them to `.agents/claude-only.txt` (`claude_only` in answers) so the Codex link check passes |
| Merge | The kit's structure, plus the project's facts and extra steps. Then resolve it as `keep-theirs`. If the merged file ends up identical to the kit's, drop its resolution; the plan shows it `unchanged`. **Keep the original:** copy it to `<file>.pre-agent-kit` first, since an untracked file has no git history to fall back on. **Project lines that would land in an always-loaded file** (like `security.md`) go into a path-scoped `.claude/rules/project-<area>.md` instead, so they don't eat the word budget |
| Existing `CLAUDE.md` / `AGENTS.md` | Never overwritten. The installer appends a marked kit block (`@CLAUDE.kit.md` import + Project facts; the Codex section). If the project's own text contradicts a kit rule, ask the owner which wins and record it in the project's own text |
| Existing `.mcp.json` server with the same purpose | Keep theirs and map the pack to it: `mcp_map: {"<kit server>": "<their server>"}` |
| Existing hook on the same event | Added alongside it; nothing is replaced. **Read every existing hook.** If one clashes with the kit (an old main-branch guard that blocks `git fetch origin main`, a second worktree manager), show the owner and offer to retire it: with their yes, rename the script to `.pre-agent-kit` and remove its entry from `.claude/settings.json`. **Carry over what it did** that the owner still wants (for example env files it linked → `WORKTREE_ENV_FILES`) |
| An existing `AGENTS.md` holding project rules, and no `CLAUDE.md` | Claude Code doesn't read `AGENTS.md`. The new `CLAUDE.md` gets a note pointing at it. After `apply`, offer to copy the project-specific rules into `CLAUDE.md`'s "Project rules" section instead, condensed, since they count toward the word budget. If all of them are copied, remove the pointer note |

**Contradiction checklist.** Before Step 4, compare the project's own `CLAUDE.md`, `AGENTS.md`, rules and hooks
against the kit. Raise each clash as one question, and record the answer in the project's own text:
- branch model (talk of `qa`/`develop`, "never touch main");
- who may merge (the kit: the owner's yes, gate G3);
- schema changes and the migration tool;
- whether dependencies are allowed (`DEPENDENCY_POLICY`);
- the Critical Systems list;
- direct SQL through MCP;
- destructive commands in the project's own docs or hooks;
- pre-allowed write tools in the old settings.

## Step 4: Show the plan. STOP.

Re-run `plan` with the final answers and show the owner the whole output:
- every file, with `pull` / `skip` / `conflict` / `unchanged` / `merge` and its reason;
- MCP entries;
- settings hooks and permissions;
- `.gitignore` lines;
- third-party skills, with source and pinned commit;
- the credential and setup tasks.

**Wait for the owner's explicit approval.** Don't continue on silence or on "looks interesting".

## Step 5: Install

```bash
git -C <project> switch -c agent-kit/install <MAIN_BRANCH>
```

Now, on the install branch and before `apply`, do the approved hand work: write the merged files, and retire
clashing hooks. Then:

```bash
python3 <kit>/installer/agent_kit.py apply --target <project> --answers <scratch>/answers.json
```

`apply` writes exactly what the plan showed:
- the files, with `{{FACTS}}` filled;
- the merged `.claude/settings.json` and `.mcp.json` (`${ENV_VAR}` references only);
- `.claude/packs/*.md`;
- `.gitignore` lines;
- the `.agents/skills/*` Codex links;
- `.claude/agent-kit.lock.json`.

It refuses if a conflict is unresolved or a required fact is missing. It never deletes anything.

**Third-party skills** (extras): `apply` doesn't fetch them. For each `third_party` entry of a chosen pack, clone
its `source` at its `ref` into scratch, then:

```bash
python3 <kit>/installer/agent_kit.py third-party --target <project> --name <entry name> --from <fetched skill dir>
```

It checks the tree's hash before copying anything in. A mismatch or a pending pin (`ref: null`) is refused. Report
it and move on.

## Step 6: Verify

```bash
python3 <kit>/installer/agent_kit.py verify --target <project>
```

This checks for unfilled placeholders, leaked source-project facts, missing lock files and the Claude↔Codex links
(`check_skill_links.py --require-restated`).

**Then run each command in the printed `TEST_COMMANDS`, exactly as written,** so the project's own tests show
nothing broke. Always do this, even when verify passed. Report what you ran and what it printed. Never claim a
check passed without its output.

**If it fails because of the project's own text**, never edit that text without the owner. Show the owner what
failed and offer the fix:
- **Always-loaded words over 3,500:** `CLAUDE.md` plus `CLAUDE.kit.md` plus unscoped rules. The kit uses about
  2,200 of those, which leaves the project roughly 1,300. Offer to move area-specific parts of the project's
  `CLAUDE.md` into path-scoped `.claude/rules/project-<area>.md` files, or history into `docs/`. As a last resort,
  the owner can raise the budget with `--word-budget N` in the CI workflow.
- **A `<!-- codex-restate -->` tag whose line isn't restated in `AGENTS.md`, or a rule file missing from AGENTS.md's
  rule table:** re-run `apply`. It regenerates both. Do the same after adding any new `.claude/rules/*.md`.

## Step 7: Report

Tell the owner:
1. **Installed:** core plus the packs, the number of files, and the commands now available (`/triage`, `/operate`,
   `/post-op`, `/peer-review`, `/ship`, `/verify`, `/test`, …).
2. **Skipped or renamed**, and why. List every `.pre-agent-kit` file the owner may remove after checking.
3. **Credential and setup tasks**, as a checklist. These are env var names, plus steps like "authorize the
   Atlassian MCP on first use". The notify pack's bot setup is in `docs/agent/notify-telegram.md`.
4. **Project docs to fill in** under `docs/agent/` (source layout, docs map, verify map, integrations, copy rules,
   PII, sibling paths). The commands read them, and empty ones make the gates check only the basics.
5. **Next step:**
   1. Commit the install branch and open a PR (when the owner says so), then **merge it before starting ticket
      work**. Ticket branches start from `<MAIN_BRANCH>` once the kit is on it. Otherwise every review fingerprints
      the whole kit as part of the ticket. The helper also refuses untracked files, so commit everything the
      project wants tracked.
   2. **A git remote named `origin`** is needed beyond `/ship`: the review fingerprints compare against
      `origin/<MAIN_BRANCH>`. If the project has none, add one before the first ticket.
   3. Create the open-items ticket if it doesn't exist.
   4. Try `/triage <ticket>` on a real ticket.

## answers.json

```json
{
  "facts": {
    "PROJECT_NAME": "Acme",
    "PROJECT_SUMMARY": "Invoicing for small shops",
    "TICKET_SYSTEM": "jira",
    "TICKET_PREFIX": "ACME",
    "MAIN_BRANCH": "main",
    "TEST_COMMANDS": [".: npm test"],
    "CRITICAL_DOMAIN": "billing — invoice totals and refunds",
    "OPEN_ITEMS_TICKET": "ACME-1",
    "JIRA_SITE": "acme.atlassian.net"
  },
  "packs": ["jira", "supabase", "typescript", "notify-telegram"],
  "options": {"github": true},
  "mcp_map": {},
  "resolutions": {".claude/commands/ship.md": "take-kit"}
}
```

- **Fact values** are a string, a boolean, or a list (written one item per line). A missing optional fact takes its
  default.
- **`resolutions`** map an installed path to `keep-theirs`, `take-kit` or `kit-renamed`. An MCP server conflict is
  keyed `".mcp.json#<server>"` and takes `keep-theirs` or `take-kit`. Resolutions are never stored in the lock.
- **Upgrades:** once the lock exists, `--answers` is optional. The lock's answers are the base, and a file you pass
  overrides them. A file holding only `resolutions` is enough.
- **`claude_only`:** a list of project command names to add to `.agents/claude-only.txt`.

## Upgrading

The lock file is present, so the kit was installed before:

1. Clone the new kit version (Step 0).
2. Run `plan --upgrade --target <project>` (add `--answers` only for changed facts or new packs).
   - A file whose content still matches its installed hash wasn't customized, so it is updated.
   - A customized file is a **conflict**: resolve it as in Step 3. **The upgrade is all or nothing.** While any
     conflict is unresolved, nothing is written, not even the clean updates. `plan --upgrade` prints a
     `resolutions` JSON to fill in.
   - Project-owned files (`docs/agent/*`, `.agents/claude-only.txt`) are never touched.
   - Files the new kit no longer ships are reported as `orphaned` and left in place.
3. Show the plan, plus the `CHANGELOG.md` entries since the installed version. **STOP for approval.**
4. Run `upgrade --target <project> --answers <file with resolutions>`, then Steps 6 and 7.

Running the install again with no kit change and the same answers changes nothing. Every row reads `unchanged`,
or `skip` for project-owned files and files kept as theirs.
