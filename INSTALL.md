<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Installing agent-kit into a project

You are an AI agent (Claude Code or Codex), and the owner asked you to install **agent-kit** into the project in
your current working directory. The kit's installer script does every file write and finds every answer it can.
Your job is the judgment: fill in what only reading the project can tell, propose a resolution for each clash, and
put **one review page** in front of the owner.

**The owner has three touch points, no more:**
1. They start the install from their real project folder.
2. They read **one review page** and approve it. They answer only what the page marks `ask`.
3. They say when to merge the install PR.

Rules for the whole install:
- **Never ask what the project already answers.** `draft` reads the branches, commits, docs, `.mcp.json` server
  names and worktrees. Put what you find on the page with its evidence; don't turn it into a question.
- **Run from the real checkout, never from a fresh clone.** A clone lacks the local-only files (`.mcp.json`,
  `.env*`, `settings.local.json`) the install needs to read. The installer builds the install in its own git
  worktree, so the owner's checkout and lanes are never written.
- **Every blocker first.** Run `preflight` before anything else and report every blocker in one message, each
  with its fix. Never discover a blocker halfway through.
- **Change nothing** in the project until the owner approves the review page. **Delete nothing, ever:** a
  replaced file is renamed `<file>.pre-agent-kit`. Don't run `rm`, `git clean`, `git reset --hard` or anything like
  them, and don't write them into any file.
- **Never read or copy a secret value.** For `.mcp.json`, `.env*` and settings files, use key names only.
  Credentials become owner tasks, written as env var names.
- **Questions, when one is truly needed:** one at a time, in plain language, each option with a pro and a con.
  **One pack per choice**: never bundle two packs into one option. When the project already has what a pack adds
  (a status line, a notify script, a worktree manager), the option says so, and says what choosing the pack would
  do.

## Step 0: Get the kit

Clone the **kit** into your scratch directory, never into the project. Use the session scratchpad if you have one,
otherwise a new temp dir:

```bash
git clone --depth 1 --branch main https://github.com/tharwat/agent-kit "<scratch>/agent-kit"
```

`--branch main` installs the latest kit. Use a tag (`--branch v1.9.0`) when the owner names a version. From here on,
`<kit>` means that clone, and `<project>` means the project's real checkout (`git rev-parse --show-toplevel`).
Started inside one of the project's worktrees? The installer finds the main checkout itself.

## Step 1: Preflight

```bash
python3 <kit>/installer/agent_kit.py preflight --target <project>
```

It only reads. It reports:
- git: the origin, the default branch, uncommitted changes and worktree lanes (left untouched), and unmerged
  branches (work in flight: merge the install only between tickets);
- tools: Python 3.9+, Node 18+, `gh` logged in;
- local-only files: `.mcp.json` and whether git ignores it, `settings.local.json` hooks, `.env*` names;
- the MCP server each chosen pack needs (present, mapped, or added by the kit).

Then do its **agent checks**: one read call through each MCP server it names (for Jira, fetch any issue). A server
that isn't authorized is a blocker. **BLOCKED:** send the owner every blocker with its fix, in one message, and
stop.

**A new project** (the only blockers are no git repository, no `origin`, or no pushed main branch): offer to set it
up, as one question with a pro and a con. With the owner's yes:
1. `git init`, plus a `.gitignore` for the stack;
2. a first commit of what is there;
3. `gh repo create <name> --private --source . --push`, which creates the GitHub repo and pushes `main`. Creating a
   repo is outward-facing: never do it without that yes.

Then run `preflight` again. **If the lock file exists, this is an upgrade: go to "Upgrading" at the end.**

## Step 2: Draft the answers

```bash
python3 <kit>/installer/agent_kit.py draft --target <project> --out <scratch>/answers.json
```

`draft` creates the install worktree (branch `agent-kit/install`, from `origin/<MAIN_BRANCH>`) and reads the
project's tracked files there, so the branch the checkout is on doesn't matter. Every fact comes back as
`{value, source, evidence}`:
- `found` came from the project;
- `default` is the kit's;
- `guess` needs a check;
- `ask` needs the owner.

The draft also fills `packs` (scan matches plus worktrees, when the checkout has any) and `mcp_map` (the kit's
servers mapped to the project's own, by name). `notes.packs_to_ask` lists the choice-only packs, and
`notes.optional_extras` lists the niche ones.

Then do the judgment, writing your answers into the same file:
1. **Read the project's own `CLAUDE.md`, `AGENTS.md`, README, `.claude/commands/*`, `.claude/rules/*` and
   `.agents/skills/*` in the install worktree that `draft` printed, never in the checkout.** The worktree is
   `origin/<MAIN_BRANCH>`. The checkout may be on an unmerged branch or hold uncommitted edits, which must not
   shape the install. Nobody needs to switch branches first. Read only the local-only files (`.mcp.json`,
   `.env*` names, `settings.local.json`) from the checkout.
2. **Fill the judgment facts as `guess`, with your evidence:** `PROJECT_SUMMARY` (one line), `CRITICAL_DOMAIN`
   (the one area of logic that must never be wrong, which is severity S3), and `CRITICAL_SYSTEMS`. A proposal the
   owner can correct beats a blank they must write.
3. **Propose each choice-only pack, yes or no, with a one-line reason:** worktrees, ticket trains, hardening,
   notify-telegram, statusline. Record it in `packs` and say why in `notes`.
4. **Empty project** (no code yet): propose the stack packs from the ticket or the owner's stated plan, marked
   `guess`.
5. **Decisions: every clash between the project's rules and the kit.** Read `<kit>/installer/decision-guide.md`.
   For each clash (the contradiction checklist below, plus anything else you find), add a `decisions` entry. It
   holds:
   - what you **found** in the project;
   - a **recommendation** and **why**, tied to what you found;
   - a **pro** and a **con**.

   The owner may be installing for the first time, with no one to explain what a kit rule protects against. The
   decision is where that explanation goes. The installer refuses a decision missing any part. Leave `answer`
   empty for the owner.
6. **Exceptions to a kit safety setting** (for example, leaving the migration tool unblocked under a standing yes)
   go in `exceptions`, each with its reason and the owner's yes. Never by editing a file after `apply`: the next
   apply or upgrade would put the setting back.
7. **Over the word budget:** follow the guide's `word-budget` entry in order. Drop the repeats of kit rules, move
   area rules to folder-scoped files, and condense process notes (rule kept, story moved to `docs/`). Raise
   `options.word_budget`, with `word_budget_reason`, only if the safety core still doesn't fit. Never edit the CI
   workflow to raise it.
8. **Requirements to flag on the page:**
   - `/ship` needs an `origin` on GitHub with `gh` logged in. Without one, the owner merges PRs by hand.
   - The kit assumes **one main branch plus feature branches**. If the scan lists `extra_long_lived_branches`
     (`qa`, `develop`), say so: the owner adapts the commands for those.
   - Facts you can't find and can't reasonably propose stay `ask`.

## Step 3: The review page. STOP for one approval.

Propose a resolution for every clash **before** rendering the page, so the page shows a decision to approve, not a
question. Use the table below. Write each one into `resolutions`, and keep the reason for the page.

```bash
python3 <kit>/installer/agent_kit.py review --target <project> --answers <scratch>/answers.json --out <scratch>/agent-kit-review.md
```

It creates the install worktree (branch `agent-kit/install`, made from `origin/<MAIN_BRANCH>`, in `WORKTREE_DIR`
when set), plans the install there, and writes one page:
- **A. Blockers.**
- **B. Answers**, with source and evidence.
- **C. What happens to each of the owner's files.**
- **D. What gets added.**
- **E. After the merge.**

Show the owner the whole page. It opens with **Needs you**:
- every open decision, with its recommendation, why, a pro and a con;
- every fact still `ask`;
- every pack to choose;
- a short glossary.

The owner replies with codes (`D1 project, D2 kit`), or `accept` to take every recommendation they've read, or in
plain words ("critical domain should say…"). Record each answer in its decision's `answer`, re-render, and ask only
what is still open, one at a time. **Wait for one explicit approval of the page.** Silence, or "looks
interesting", is not approval.

### Proposing resolutions

For every row marked `conflict` on the page, propose:

| Situation | Default |
|---|---|
| Same-name command or skill, clearly unrelated job | `kit-renamed`: the kit's copy installs as `<name>-kit.md`. Tell the owner that kit commands which call `/<name>` now need `/<name>-kit` |
| Same-name command or skill doing the same job | Show a short diff summary, then offer **keep theirs** (`keep-theirs`), **take the kit's** (`take-kit`; theirs is renamed `.pre-agent-kit`), or **merge** |
| Same-name **rule** | Default to **merge**. A project's rule usually holds project-specific content (PII fields, storage rules) that would stop loading if it were renamed aside |
| Project commands with no `description:` | Resolve the other conflicts first, then re-run `plan`: it lists the project's own commands that have no description. Offer to add them to `.agents/claude-only.txt` (`claude_only` in answers) so the Codex link check passes |
| Merge | The kit's structure, plus the project's facts and extra steps. Then resolve it as `keep-theirs`. If the merged file ends up identical to the kit's, drop its resolution; the plan shows it `unchanged`. **Keep the original:** copy it to `<file>.pre-agent-kit` first, since an untracked file has no git history to fall back on. **Project lines that would land in an always-loaded file** (like `security.md`) go into a path-scoped `.claude/rules/project-<area>.md` instead, so they don't eat the word budget |
| Existing `CLAUDE.md` / `AGENTS.md` | Never overwritten. The installer appends a marked kit block (`@CLAUDE.kit.md` import + Project facts; the Codex section). If the project's own text contradicts a kit rule, ask the owner which wins and record it in the project's own text |
| Existing `.mcp.json` server with the same purpose | Keep theirs and map the pack to it: `mcp_map: {"<kit server>": "<their server>"}`. The kit's permissions and tool references are rewritten to their server's name. Never copy a server from another project: its URL, project ref or token points at that project. Install the kit's entry under this project's prefix instead |
| Existing hook on the same event | Added alongside it; nothing is replaced. **Read every existing hook.** If one clashes with the kit (an old main-branch guard that blocks `git fetch origin main`, a second worktree manager), show the owner and offer to retire it: with their yes, rename the script to `.pre-agent-kit` and remove its entry from `.claude/settings.json`. **Carry over what it did** that the owner still wants (for example env files it linked → `WORKTREE_ENV_FILES`) |
| An existing `AGENTS.md` holding project rules, and no `CLAUDE.md` | Claude Code doesn't read `AGENTS.md`. The new `CLAUDE.md` gets a note pointing at it. After `apply`, offer to copy the project-specific rules into `CLAUDE.md`'s "Project rules" section instead, condensed, since they count toward the word budget. If all of them are copied, remove the pointer note |

**Contradiction checklist.** Compare the project's own `CLAUDE.md`, `AGENTS.md`, rules and hooks against the kit.
Put each clash on the review page with your proposal, and record the owner's answer in the project's own text:
- branch model (talk of `qa`/`develop`, "never touch main");
- who may merge (the kit: the owner's yes, gate G3);
- schema changes and the migration tool;
- whether dependencies are allowed (`DEPENDENCY_POLICY`);
- the Critical Systems list;
- direct SQL through MCP;
- destructive commands in the project's own docs or hooks;
- pre-allowed write tools in the old settings.

## Step 4: Install, in the install worktree

`<wt>` is the install worktree that `review` printed. Its env files are linked from the checkout, so the project's
tests run there as they do in the checkout.

1. **Baseline first.** In `<wt>`, before any install change, install the project's dependencies (its lockfile
   command, such as `npm ci`) and run every `TEST_COMMANDS` line. Record each failing test. The install is judged
   only on failures **not** in this baseline.
2. **Do the approved hand work in `<wt>`:** write the merged files, retire clashing hooks, and repoint or retire
   tests as the decisions say.
3. **Then apply:**

```bash
python3 <kit>/installer/agent_kit.py apply --target <project> --answers <scratch>/answers.json --worktree
```

`apply --worktree` writes exactly what the page showed, and only inside `<wt>`:
- the files, with `{{FACTS}}` filled;
- the merged `.claude/settings.json`;
- `.claude/packs/*.md`;
- `.gitignore` lines;
- the `.agents/skills/*` Codex links;
- `.claude/agent-kit.lock.json`.

The one exception is a local-only `.mcp.json` (gitignored). Servers mapped through `mcp_map` need no change. A
server the kit must add is written to the **checkout's** `.mcp.json`, because that is the only copy that exists, and
only when the page listed it. `apply` refuses if a conflict is unresolved, or if a fact or decision is still open. It never deletes
anything.

**No hand edits to kit-managed files after `apply`.** Re-running apply or upgrade restores them. A change the
owner wants goes through the answers: `resolutions`, `exceptions`, facts or decisions. The owner's decisions are
written to `docs/agent/install-decisions.md`, so later sessions follow them.

**Third-party skills** (extras): `apply` doesn't fetch them. For each `third_party` entry of a chosen pack, clone
its `source` at its `ref` into scratch, then:

```bash
python3 <kit>/installer/agent_kit.py third-party --target <wt> --name <entry name> --from <fetched skill dir>
```

It checks the tree's hash before copying anything in. A mismatch or a pending pin (`ref: null`) is refused. Report
it and move on.

## Step 5: Verify

```bash
python3 <kit>/installer/agent_kit.py verify --target <wt>
```

This checks for unfilled placeholders, leaked source-project facts, missing lock files and the Claude↔Codex links
(`check_skill_links.py --require-restated`).

**Then run each command in the printed `TEST_COMMANDS` in `<wt>`, exactly as written, and compare with the
Step 4 baseline.** Report:
- **new failures**: the install's doing, each fixed or put to the owner;
- **baseline failures**: there before the install; list them and leave them alone.

Never report the total as the install's result. Always do this, even when verify passed. Report what you ran and what it printed. Never claim a
check passed without its output.

**If it fails because of the project's own text**, never edit that text without the owner. Show the owner what
failed and offer the fix:
- **Always-loaded words over 3,500:** `CLAUDE.md` plus `CLAUDE.kit.md` plus unscoped rules. The kit uses about
  2,200 of those, which leaves the project roughly 1,300. Offer to move area-specific parts of the project's
  `CLAUDE.md` into path-scoped `.claude/rules/project-<area>.md` files, or history into `docs/`. As a last resort,
  the owner can raise the budget with `--word-budget N` in the CI workflow.
- **A `<!-- codex-restate -->` tag whose line isn't restated in `AGENTS.md`, or a rule file missing from AGENTS.md's
  rule table:** re-run `apply`. It regenerates both. Do the same after adding any new `.claude/rules/*.md`.

## Step 6: Report

Tell the owner:
1. **Installed:** core plus the packs, the number of files, and the commands now available (`/triage`, `/operate`,
   `/post-op`, `/peer-review`, `/ship`, `/verify`, `/test`, …).
2. **Skipped or renamed**, and why. List every `.pre-agent-kit` file the owner may remove after checking.
3. **Credential and setup tasks**, as a checklist. These are env var names, plus steps like "authorize the
   Atlassian MCP on first use". The notify pack's bot setup is in `docs/agent/notify-telegram.md`.
4. **Project docs to fill in** under `docs/agent/` (source layout, docs map, verify map, integrations, copy rules,
   PII, sibling paths). The commands read them, and empty ones make the gates check only the basics.
5. **Next step:**
   1. Commit in `<wt>`, push `agent-kit/install` and open the PR (the page's approval covers this). Merge it **only
      on the owner's yes, and between tickets**: the preflight's work-in-flight list says what's open. Ticket branches
      start from `<MAIN_BRANCH>` once the kit is on it. Otherwise every review fingerprints the whole kit as part of
      the ticket.
   2. After the merge, every lane picks the kit up from `<MAIN_BRANCH>`. Worktrees sync on their next prompt (with
      the worktrees pack), and the checkout needs `git pull`. `<wt>` can then be removed by the owner with
      `git worktree remove <wt>`.
   3. Create the open-items ticket if the page said so.
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
  default. A draft's `{value, source, evidence}` form is accepted as is. A fact still `ask` with no value refuses
  the install.
- **`notes`** holds the draft's evidence (packs found, packs to ask about, local-only files). The installer ignores
  it.
- **`decisions`:** a list of `{id, guide, topic, kit_rule, project_rule, found, recommendation, why, pro, con,
  answer, answer_detail}` (see `installer/decision-guide.md`). They are kept in the lock and written to
  `docs/agent/install-decisions.md`.
- **`exceptions`:** `{"permissions.deny": [{"entry", "reason", "approved"}]}`. These are kit deny rules the project
  opted out of with the owner's yes (gate G7). They are kept in the lock and never re-added by apply or upgrade.
- **`options.word_budget`** (with **`options.word_budget_reason`** when above 3,500): the project's always-loaded
  word limit. The installed link check reads it from the lock.
- **`resolutions`** map an installed path to `keep-theirs`, `take-kit` or `kit-renamed`. An MCP server conflict is
  keyed `".mcp.json#<server>"` and takes `keep-theirs` or `take-kit`. Resolutions are never stored in the lock.
- **Upgrades:** once the lock exists, `--answers` is optional. The lock's answers are the base, and a file you pass
  overrides them. A file holding only `resolutions` is enough.
- **`claude_only`:** a list of project command names to add to `.agents/claude-only.txt`.

## Upgrading

The lock file is present, so the kit was installed before. It's the same path, with no draft:

1. Clone the new kit version (Step 0), and run `preflight` (Step 1).
2. Run `review --target <project>`. Add `--answers` only for changed facts, new packs or resolutions. The page
   adds **F. What changed in the kit** since the installed version.
   - A file whose content still matches its installed hash wasn't customized, so it is updated.
   - A customized file is a **conflict**: propose a resolution as in Step 3. **The upgrade is all or nothing.**
     While any conflict is unresolved, nothing is written, not even the clean updates.
   - Project-owned files (`docs/agent/*`, `.agents/claude-only.txt`) are never touched.
   - Files the new kit no longer ships are reported as `orphaned` and left in place.
3. **STOP for one approval of the page.**
4. Run `upgrade --target <project> --worktree` (with `--answers <file>` if you made one), then Steps 5 and 6.

Running the install again with no kit change and the same answers changes nothing. Every row reads `unchanged`,
or `skip` for project-owned files and files kept as theirs.
