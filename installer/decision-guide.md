<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Decision guide: when a project's rules and the kit's differ

The installing agent reads this before it writes the review page. An owner installing for the first time has no
one to explain what each kit rule is for. This guide is that explanation.

**For every clash the agent finds**, it adds one entry to `decisions` in `answers.json`:

| Key | What it holds |
|---|---|
| `id` | A short code the owner can reply with: `D1`, `D2`, … |
| `guide` | The id of the entry below (`schema-changes`, …), or `other` |
| `topic` | A plain-words title: "Removing a database column" |
| `kit_rule` | The kit's rule, in plain words |
| `project_rule` | The project's rule, in plain words, with where it lives (`CLAUDE.md`, `.claude/rules/x.md`) |
| `found` | The project facts the recommendation rests on, each with where it was found |
| `recommendation` | `kit`, `project` or `other` |
| `why` | One or two sentences tying the recommendation to `found` |
| `pro`, `con` | Of the recommended choice |
| `answer` | Left empty for the owner. `kit`, `project` or `other`, plus `answer_detail` for `other` |

The installer refuses a decision missing any of these: "here is a clash, you decide" is never enough. Check what each
entry says to check, record what you found, then recommend. When this guide doesn't cover a clash, use `other` and
the same fields.

The owner's answers are written to `docs/agent/install-decisions.md` and kept in the lock, so later sessions and
upgrades follow them without asking again.

---

### schema-changes: Removing or reshaping a database column, table or enum

- **Kit:** removals and reshapes are done safely. One migration when nothing live breaks mid-change, with a
  backout, a snapshot of anything lost, and every reader and writer moved in the same change. Otherwise it is phased:
  add, backfill, move every read and write, deploy, then remove in a later migration. The destructive step is gate
  G5.
- **Protects against:** a client still reading the old column (an app version in users' hands, another service, a
  scheduled job deployed separately), and data that can't be recovered.
- **The project's way is as safe when:** every consumer deploys from this repo at the same time, and the project
  already requires a backout and a snapshot before a destructive change.
- **Check:** mobile apps or desktop builds in users' hands, other repos or services reading the database, separately
  deployed workers, and a backout or snapshot rule in the project's text.
- **Recommend:** `project` when everything deploys together and a backout and snapshot rule exists. Otherwise `kit`.
- **Pro of `project`:** no extra migrations or follow-up tickets. **Con:** if a separately deployed reader is
  missed, it breaks in production until it's redeployed.

### migration-apply: How migrations reach the live database

- **Kit:** migrations go through a write-enabled server that prompts on every call, so a migration can't run by
  accident. The normal server is read-only.
- **Protects against:** an agent running a migration nobody asked for, against production.
- **The project's way is as safe when:** the owner has given a standing yes for migrations, every migration carries
  a backout, and a snapshot is taken before destructive ones.
- **Check:** a standing authorization in the project's text, the backout and snapshot rule, and whether runs are
  unattended (ticket trains, overnight runs).
- **Recommend:** `project` (record an `exceptions.permissions.deny` entry for the migration tool, with the owner's
  yes) when the standing yes and backout rule exist and runs are unattended. Otherwise `kit`.
- **Pro of `project`:** unattended runs don't stall on a click. **Con:** a kit safety setting is off, gate G7,
  recorded with its reason.

### refactoring: Refactoring code while working a ticket

- **Words first:**
  - a **refactor** changes how the code is organized, while it does exactly the same thing: renaming, moving,
    splitting a long function, merging duplicate code;
  - a **redesign** changes how it works, such as storing a status instead of working it out from several fields.

  A project rule that says "refactor freely" often means redesign. Ask which, in the decision's `found`.
- **Kit:** refactor and simplify the code the ticket changes (`/operate` has a simplify step). Redesign when review
  findings keep coming (the spiral rule requires it). Don't broadly refactor, rename or move code the ticket doesn't
  touch, unless asked.
- **Protects against:** wide diffs. Every untouched file in a diff is more readers and writers to miss, the top cause
  of review findings and of bugs added by fixes.
- **The project's way is as safe when:** rarely. "Refactor freely" usually means the same as the kit: improve the
  code you're in, redesign when needed.
- **Check:** whether the project's rule means the touched code (the kit agrees) or sweeping changes to unrelated
  code.
- **Recommend:** `kit`, and tell the owner that a big refactor is fine as its own ticket ("unless asked").
- **Pro:** smaller diffs, fewer missed callers. **Con:** an unrelated cleanup you notice waits for its own ticket.

### triage-then-operate: What happens between /triage and /operate

- **Kit:** `/triage` writes the plan, and implementation follows without waiting for the owner, unless there is an
  owner question or a gate.
- **Protects against:** stalls in unattended runs.
- **The project's way is as safe when:** always. Requiring the owner to start `/operate` is just slower.
- **Check:** whether the owner runs tickets unattended (ticket trains) or one at a time.
- **Recommend:** `project` when the owner starts each step, `kit` when tickets run unattended.
- **Pro of `project`:** the owner sees every plan first. **Con:** nothing moves while the owner is away.

### standing-owner-yes: Standing authorizations for gated actions

- **Kit:** gates G1–G7 need the owner's yes at the time.
- **Protects against:** irreversible actions taken on an old or assumed yes.
- **The project's way is as safe when:** the standing yes names exact actions ("live migrations", "the RAG ingest",
  "token spend up to N"), not categories, and the rest of the gates still apply.
- **Check:** the wording of each standing authorization, and whether it is bounded.
- **Recommend:** `project`, recorded as a standing yes for exactly the named actions. Everything else still asks:
  merging to main (G3), other production writes (G2), grants (G6).
- **Pro:** the work the owner already approved keeps flowing. **Con:** those named actions no longer pause.

### commit-attribution: AI co-author trailers in commits

- **Kit:** no `Co-Authored-By:` trailer and no "Generated with" line. A hook blocks commits carrying one.
- **Protects against:** attribution lines the owner didn't choose.
- **Check:** what the project's text or ticket rules require.
- **Recommend:** `kit`, unless the owner wants the trailers. Then the commit-message hook must be removed, which is
  a G7 exception with its reason.
- **Pro:** clean history. **Con:** none, unless someone relies on the trailer.

### word-budget: Always-loaded instructions over the budget

- **Kit:** 3,500 always-loaded words: `CLAUDE.md`, `CLAUDE.kit.md`, and rules without `paths:`. The installed link
  check (CI and `verify`) fails above it.
- **Protects against:** a context window crowded before work starts, and instructions too long to be followed.
- **Check:** the word count of each always-loaded file and of each `CLAUDE.md` section (`verify` prints the totals).
  The kit's own share is about 2,200: `CLAUDE.kit.md`, the Project facts block in `CLAUDE.md`, and its unscoped
  rules. That leaves a project roughly 1,300 words of its own always-loaded text.
  Sort every section into one of four kinds:
  - **safety or money rules**, the ones that must never be missed;
  - **area rules**, needed only when working in one folder;
  - **process notes with their stories:** incidents, reasons, examples, "why we do this";
  - **repeats of a kit rule.** The kit already loads its rule, for example no destructive commands, or verify
    before done.
- **Recommend, in this order, and stop as soon as it fits:**
  1. **Drop the repeats** of kit rules. The kit's version is loaded anyway.
  2. **Move area rules** into `.claude/rules/project-<area>.md` with `paths:` for their folders.
  3. **Condense process notes:** keep each rule as one line, with a one-line why. Move the stories and full
     reasons to a history doc in `docs/`, and leave a pointer. Nothing is deleted; it stops loading in every
     session. **Before rewording any rule,** search the project's tests for its sentences. A sentence a test pins
     (often a safety rule) stays word for word. Never loosen the test to fit the shorter text.
  4. **Only if it's still over:** keep a short always-loaded core with the safety and money rules, and raise the
     project's budget through the answers: `options.word_budget` plus `word_budget_reason`.
- **Never:**
  - cut, or folder-scope, a safety or money rule to hit the number (a planning session that opens no files would
    miss it);
  - raise the budget by editing the CI workflow or a kit file. An upgrade puts it back, and it hides the reason.
- **Pro:** every session loads less, and still sees every critical rule. **Con:** a condensed section's stories
  live only in `docs/`, one click away, not in every session.

### workflow-text-tests: Project tests that pin the old workflow's text

- **Kit:** the kit tests its own commands in its own repo.
- **What happens:** a project that tested its own workflow files ("ship.md must mention X") fails those tests once the
  kit's versions replace them.
- **Check:** for each failing test, does it guard a **project rule** (a deploy list, a security pointer, a standing
  authorization) or the **old workflow's wording**?
- **Recommend:** point project-rule guards at where the rule lives now (`project-*.md`, `CLAUDE.md`). Retire the
  tests of the old wording by renaming them `.pre-agent-kit`: that is G7, needs the owner's yes, and has the reason
  "the kit replaced that text".
- **Watch for:** a test that matches by substring can collide with a kit file's name. For example, a check for
  "worktrees" also matches the kit's `.claude/packs/worktrees.md`. Anchor it to the real path (`.claude/worktrees/`)
  instead of loosening it.
- **Done when:** the suite's failures match the baseline from before the install exactly, with none added and none
  hidden.
- **Pro:** every real guard keeps working, and the suite returns to its baseline. **Con:** the project no longer
  tests the command text itself; the kit's tests do.

### review-rounds: The project's own review loop

- **Kit:** review rounds run until the code is clean. A second finding in one area stops the patching for a written
  spiral assessment the owner decides on. A ticket never ends with known defects of its own, or with a fix no
  reviewer read.
- **Check:** a round cap in the project's text ("stop at 3"), and whether leftover findings go to a tracker.
- **Recommend:** `kit`. A fixed cap ends tickets with known bugs and fills the tracker.
- **Pro:** defects get fixed, not filed. **Con:** a hard ticket can take more rounds, or reach the owner sooner.

### branch-model: Long-lived branches besides main

- **Kit:** one long-lived branch, plus a short-lived branch per ticket.
- **Check:** `qa`, `develop` or `staging` branches, and deploys tied to them.
- **Recommend:** `kit` if those branches are unused. If they are live, `other`: install, and the owner adapts
  `/ship` and `/verify` for the extra branch.
- **Pro:** one path to production. **Con:** a team that relies on a QA branch has to adapt the commands.

### merge-rights: Who may merge to main

- **Kit:** only with the owner's explicit yes (G3).
- **Check:** auto-merge rules or "agents may merge" in the project's text.
- **Recommend:** `kit`. Ticket trains already approve a whole queue with one yes.
- **Pro:** nothing reaches main unseen. **Con:** one yes per PR outside trains.

### dependencies: Adding a dependency

- **Kit:** allowed per `DEPENDENCY_POLICY`, with the reason recorded.
- **Check:** "no new dependencies" or an approved list in the project's text.
- **Recommend:** `project`, written into `DEPENDENCY_POLICY`.
- **Pro:** the project's policy stays in force. **Con:** none.

### mcp-write-tools: MCP tools that write (database, tracker, deploys)

- **Kit:** permissions pre-allow read-only tools. Write tools prompt, and destructive ones are denied.
- **Check:** write tools the old settings pre-allowed.
- **Recommend:** `kit`. Keep a project-wide write allow only with a standing yes (see `standing-owner-yes`).
- **Pro:** an unexpected write asks first. **Con:** more prompts until the standing yeses are recorded.

### destructive-commands: Deleting files and history

- **Kit:** no `rm`, hard resets, cleans, force-pushes or branch deletes, run or written. Replaced files are renamed
  `.pre-agent-kit`.
- **Check:** scripts or docs in the project that call those commands.
- **Recommend:** `kit`, and list the project's scripts that use them for the owner to change.
- **Pro:** nothing is lost by an agent. **Con:** cleanup is the owner's job.

### existing-hooks: A project hook on the same event as a kit hook

- **Kit:** its hooks are added beside the project's, and nothing is replaced.
- **Check:** each existing hook. An old main-branch guard that blocks `git fetch`, or a second worktree manager,
  clashes.
- **Recommend:** keep hooks that don't clash. For one that clashes, `other`: retire it (rename it `.pre-agent-kit`,
  with the owner's yes) and carry over what it did.
- **Pro:** one set of guards that agree. **Con:** an owner who relied on the old hook's exact behavior must check
  the kit's.

### secret-files: Local credential files the secret guard doesn't know

- **Kit:** the secret guard blocks agents from opening `.env` files, private keys and a few known credential files.
  A project adds its own to `docs/agent/secret-files.md`.
- **Protects against:** a live token printed into a conversation, a transcript or a log by one file read.
- **Check:** `preflight` lists gitignored files that hold credentials but aren't on the guard's list. It judges by
  JSON key names (`private_key`, `refresh_token`, `client_secret`, …), by credential-like names (OAuth, token,
  service account), and, for `.mcp.json`, by a server holding a literal value instead of a `${ENV}` reference. It
  never shows a value.
- **Recommend:** `kit`. Add every listed file to `docs/agent/secret-files.md`, `.mcp.json` included when it holds
  literal credentials. Use the exact path for a single file: a `*` also matches across `/` and can block whole
  folders. Confirm which key is live before naming it (old, unused keys often sit next to the live one). Then propose a follow-up ticket that moves those values to environment variables
  (`"Authorization": "Bearer ${RENDER_API_KEY}"`), so `.mcp.json` holds none.
- **Pro:** no session can leak those tokens. Scripts that read the files in their own process keep working. **Con:**
  agents can't open the file to inspect it. They read server names through the installer, or ask the owner.
