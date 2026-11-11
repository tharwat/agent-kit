# Kit conventions (build-time contract)

Every file in `core/` and `packs/` follows this, and so must any new pack. Where an existing kit file contradicts
this document, fix the file.

## 1. Notation

| Written | Meaning | Filled when |
|---|---|---|
| `{{NAME}}` | Template placeholder | At install. Only allowed in `*.tmpl` files |
| `<NAME>` (UPPER_SNAKE) | A Project-facts value. The agent reads it from the Project facts block in `CLAUDE.md` at run time | Never substituted; commands stay identical across projects |
| `<lower-case>` | A run-time value | By the agent, e.g. `<ticket>`, `<branch>`, `<slug>` |

Each command's first body line is:

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

A test checks that every `<UPPER_SNAKE>` used anywhere is defined in `manifest.json`.

## 2. Project facts (tier 1, in the project's `CLAUDE.md`)

| Fact | Meaning | Example / default |
|---|---|---|
| `PROJECT_NAME` | Short name, used in reports and notifications | `Acme` |
| `PROJECT_SUMMARY` | One line on what the product does | |
| `TICKET_SYSTEM` | The installed ticket pack | `jira` |
| `TICKET_PREFIX` | Ticket key prefix | `ABC` (keys look like `ABC-123`) |
| `MCP_PREFIX` | Prefix on this project's MCP server names (§9) | `acme_` gives `acme_jira`; `none` for no prefix |
| `MAIN_BRANCH` | The only long-lived branch | `main` |
| `BRANCH_PREFIX` | Feature branch prefix | `feature/` |
| `HAS_CI` | `true` means `/ship` waits for required checks before merging | `false` |
| `TEST_COMMANDS` | One line per package: `<dir>: <command>`. Run exactly as written | `.: npm test` |
| `TYPECHECK_COMMAND` | Optional | `none` |
| `BUILD_COMMAND` | Optional | `none` |
| `SYNTAX_CHECK_COMMAND` | Optional, for code with no compiler | `node --check <file>` |
| `DEV_SERVER_COMMAND` | How to run the app locally for `/verify` | |
| `LOG_SINK` | Where production logs are read | "Render logs via MCP", `none` |
| `CRITICAL_DOMAIN` | Severity class S3: a label + one line on "the logic that must never be wrong here" | `billing — invoice totals and refunds` |
| `CRITICAL_SYSTEMS` | Areas whose changes get the stricter checks (§6) | auth, API contracts, schema |
| `OWNER_KEPT_GATES` | Extra gates on top of G1–G7 | `none` |
| `OPEN_ITEMS_TICKET` | The standing tracker ticket key | `ABC-1` |
| `UI_LANGUAGE` | Language of user-facing copy | `en` |
| `SYNTHETIC_MARKER` | Column or flag on rows that `/verify` creates | `is_synthetic` |
| `DEPENDENCY_POLICY` | When a new dependency is allowed | "allowed when it's the right tool; say why in the PR" |

Packs add their own facts in their own rule file (tier 2). Large maps are project files at fixed paths (tier 3, §3).
No other tier-1 facts may be invented. Propose new ones to the kit owner instead.

## 3. Project-owned files (tier 3, fixed paths)

The installer creates these from `core/project-docs/*.tmpl`, and the project owns them afterwards. Commands
reference them by path.

| Path | Holds |
|---|---|
| `docs/agent/source-layout.md` | Where API routes, clients/consumer surfaces, schema, tests and user-facing copy live; consumer surfaces |
| `docs/agent/docs-map.md` | Which doc to update for which kind of change (API spec, help content, READMEs, planning docs) |
| `docs/agent/verify-map.md` | Changed path → how that surface is verified; dry-run entry points; irreversible side effects never run as a test; protected fixtures; seed commands; test-account env var names |
| `docs/agent/integrations.md` | External services and webhooks (how each is signed), where their docs live |
| `docs/agent/copy-rules.md` | Terminology table, brand rules, the verified legal/factual-claims table |
| `docs/agent/pii.md` | PII fields and how each is masked in logs |
| `docs/agent/sibling-paths.md` | Known pairs of code paths that must change together |
| `docs/agent/defect-classes.md` | Defect classes this project ships. Seeded with the kit's generic list |
| `docs/agent/lessons.md` | Lessons learned, appended by `/post-op`. Commands read the relevant section before work |

## 4. Branch model (owner, 2026-11-07)

- One long-lived branch, `<MAIN_BRANCH>`. Feature branches are named `<BRANCH_PREFIX><ticket-lowercase>-<slug>`.
- Review diffs are always merge-base diffs: `git diff origin/<MAIN_BRANCH>...HEAD`, three dots, after a fetch.
- `/verify` runs on the feature branch, locally against real services, **before** merge. After merge, confirm the
  deploy and the logs.
- `/ship` opens a PR to `<MAIN_BRANCH>` and needs the owner's explicit yes before merging (gate G3). If
  `<HAS_CI>` is true, it waits for the required checks.
- Never push, commit or force-push to `<MAIN_BRANCH>` directly.
- There is no qa branch or QA environment. Never write one in.

## 5. Severity classes

| Class | Covers |
|---|---|
| S1 | Data integrity: loss, corruption, wrong writes, cross-tenant exposure |
| S2 | Auth and security: access-control holes, secrets, injection, unsafe input |
| S3 | `<CRITICAL_DOMAIN>` |
| S4 | The ticket's own behaviour: a contract row not met |

S1–S4 findings are must-fix. Everything else is `noted` and goes to the open-items tracker.

## 6. Owner-Kept Gates and Critical Systems

Defined once in `CLAUDE.kit.md`. Elsewhere, cite them by label only.

| Gate | Needs the owner's explicit yes before |
|---|---|
| G1 | Production builds and releases |
| G2 | Writes to production data, except rows the agent created with `<SYNTHETIC_MARKER>` |
| G3 | Merging to `<MAIN_BRANCH>`. With the ticket-trains pack installed, invoking `/ticket-train-run` approves that train's queue only |
| G4 | Admin-override merges, or bypassing branch protection |
| G5 | Destructive schema steps: DROP, final column removal, data deletion |
| G6 | Making data readable by clients: policies, grants, public buckets |
| G7 | Weakening or removing a safety check: CI checks, hooks, settings hook entries, these gates. Adding or tightening a check doesn't need the owner |

Projects add gates in `<OWNER_KEPT_GATES>`. Everything else is decided by agents.

A change to one of the `<CRITICAL_SYSTEMS>` is agent-approved with stricter checks:
1. Find every consumer.
2. Record why the change is needed and its risk.
3. Add tests, including regressions.
4. Verify before merge.

A post-merge failure is fixed forward on a new ticket and alerts the owner.

## 7. Shared mechanisms

- **Ticket ops.** Core commands never name a tracker's tools. They call ticket ops: `get`, `comment`, `close`,
  `label`, `search`, `create`. Each op is defined in `core/docs/ticket-ops.md` (installed at
  `docs/workflow/ticket-ops.md`; command text always uses installed paths, never `core/...`). The installed ticket pack provides
  `.claude/rules/ticket-ops.md`, which maps each op to its tools. Write it as: "ticket op **get** `<ticket>`
  (comments and links included)".
- **Notify.** "Notify: if `.claude/scripts/notify` exists, run `.claude/scripts/notify "<text>"`."
  - Text starts with `[<PROJECT_NAME>]`.
  - A failed send prints one line and never fails the command.
  - No command contains a chat ID or a messaging tool name.
- **Helper script.** `.claude/scripts/kit-tools.mjs` (Node ≥18, no dependencies). The interface is fixed:

  | Command | What it does | Failure behaviour |
  |---|---|---|
  | `fingerprint --base origin/<MAIN_BRANCH>` | Prints the sha256 of the merge-base → working-tree diff. Docs-only paths are excluded | Exits non-zero, with a one-line reason, on untracked files, an empty diff or a git failure |
  | `freeze --base origin/<MAIN_BRANCH> --contract <file> --out <dir>` | Writes `base.txt`, `patch.diff` and `contract.md`, and prints the snapshot hash of base + patch + contract | |
  | `covered --hash <h> --base origin/<MAIN_BRANCH>` | Exits 0 if the current fingerprint equals `<h>` | Exits non-zero otherwise |
  | `check-review --file <f> --hash <h> [--lenses <n>] [--contract <file>]` | Validates a reviewer's output: a `REVIEW_HASH:` line equal to `<h>`, a status for every lens, and `REVIEW_COMPLETE` | Missing or partial output is `UNAVAILABLE` |

  If Node is unavailable, the command says so and stops. There is no hand-run fallback.
- **Call form.** Commands call kit scripts from the repo root exactly as the installed allow rule spells them:
  `node .claude/scripts/kit-tools.mjs <command> …`, `node .claude/scripts/train-state.mjs <command> …`. No
  `$(git rev-parse …)` prefix, no `$(…)` in arguments, no bare `kit-tools`, no shell variables standing in for the
  path. Permission rules use the ` *` form, never the legacy `:*`.
- **State.** Per-ticket state lives in `.claude/state/<ticket>/`, which is gitignored:

  | File | Holds |
  |---|---|
  | `triage.md` | Contract copy and hand-off |
  | `self-review.md` | Contains `Fingerprint: <h>` |
  | `review-rounds.md` | One block per round |
  | `post-op.md` | Contains `Fingerprint: <h>` and `Result: clean\|capped\|escalate`. `clean` with a `⏭️ Skipped — Codex` review row means the gates passed and the review round was skipped |
  | `self-review.diff`, `round-<n>.diff` | The saved diffs the fingerprints were taken from |
  | `upstream.txt` | Saved upstream for the fallback review path. Marked `restored` afterwards, never removed |
  | `peer-review.json` | See below |

  `peer-review.json` holds: `ticket`, `branch`, `snapshot_hash`, `fingerprint` (the `kit-tools fingerprint` output at freeze, re-taken after peer review's own fix step once tests and gates re-ran; ship checks it with `covered`, and post-op's fingerprint stays the authoritative coverage check), `engines` (bteam and codex, each
  `CLEAN|FINDINGS|UNAVAILABLE|not run`), and `findings[]` (`id`, `class`, `status`, `resolved`). `status` is one of
  `VERIFIED|REJECTED|ALREADY-RESOLVED|NEEDS-OWNER|NOTED`. The file ends with
  `verdict: "not run"|"CLEAN"|"UNRESOLVED"`.
- **Scratch.** Temporary files go in the session scratch directory when one exists, else
  `.claude/state/tmp/`. Never write to `/tmp`.
- **Reports** end with `Owner action: none`, or the single action the owner must take now.

## 8. Writing rules for every kit file

1. **No source-project facts**: no ticket keys, product names or domain content from the projects the kit was built from (the private denylist lists them), no
   vendor names as facts, no project refs or IDs, no domains, no chat IDs, no absolute paths, no `origin/qa`.
2. **Incident rules** keep the rule and a one-line generic *why*, and drop the ticket, date, names and story.
   Longer rationale goes to `core/docs/workflow/history/<area>.md`, one file per area, installed at
   `docs/workflow/history/<area>.md`. Commands may link there. These files are not loaded
   every session. If history and a rule disagree, the rule wins.
3. **No destructive commands** in any instruction: no `rm`, `rmdir`, `find -delete`, `unlink`, `git reset --hard`,
   `git clean`, `git push --force` / `-f` / `--force-with-lease`, `git checkout -- <path>` / `.` / `-f`,
   `git switch -f` / `--discard-changes`, `git restore` (except `--staged` alone), `git stash drop` / `clear`,
   `git worktree remove --force`, `git branch -D` / `-f` / `--force`. Instead: rename to
   `<file>.pre-agent-kit`, mark a file `restored`, `git checkout --detach origin/<MAIN_BRANCH>`, `git stash`
   (never drop), or a disposable `git worktree`. Test code uses `tempfile.TemporaryDirectory` or `fs.mkdtemp`, and
   never shells out to `rm`.
4. **Stack-specific lines** (Supabase, Render, Expo, TypeScript/vitest, Playwright, Jira) go to the owning pack, not
   core. Where core needs a hook point, write "Packs may add checks here: see `.claude/rules/*.md` installed by
   packs."
5. **Plain language.** Cut narrative. Keep every rule. Target at most 70% of the source's length.
6. **Command frontmatter:** `description:` (one line) and `argument-hint:` where the command takes arguments.
7. **Codex:** anything that needs a Claude-only feature (the Workflow tool, `AskUserQuestion`, hooks) says what
   Codex does instead, and records skipped rows as `⏭️ Skipped — Codex`.
8. **Questions to the owner:** one at a time, plain language, every option with a pro and a con.

## 9. Packs (and core) as installable units

Core and every pack are **units** with the same layout. Core is the unit `core/` and is always installed.

```
packs/<name>/
  pack.json            the unit's manifest (schema below)
  pack.md              becomes .claude/packs/<name>.md: one "## /<command>" section per core command it extends
  commands/ rules/ hooks/ scripts/ skills/ workflows/ docs/   only what the pack needs
```

**`.claude/packs/<name>.md` is how a pack extends core commands.**
- Core commands have hook lines ("Packs may add checks here…"). At each one, the agent reads the matching
  `## /<command>` section, or `## <command> lenses` for bteam/operate, in every installed `.claude/packs/*.md`.
- These files are never auto-loaded, so they cost no always-loaded words.
- A pack's facts go in a `## Pack facts` table at the top of its `pack.md`, written as `{{NAME}}`. The installer
  fills them.

**Pack rules** (`rules/*.md`) must carry `paths:` frontmatter, so they load only when their files are touched. A
pack rule without `paths:` counts against the 2,500-word always-loaded budget and needs a written reason in
`pack.json`.

**`pack.json` schema** (`$schema`-validated in Phase 5; keep to these keys):

```json
{
  "name": "supabase",
  "version": "1.0.0",
  "description": "one line",
  "kind": "stack | ticket | workflow | extra",
  "requires": ["core"],
  "conflicts": [],
  "detect": {
    "files": ["supabase/config.toml"],
    "package_deps": ["@supabase/supabase-js"],
    "ask": null
  },
  "facts": [
    {"name": "DB_PROJECT_REF", "meaning": "…", "example": "abcd1234", "required": true, "ask": "question text"}
  ],
  "files": [
    {"src": "pack.md", "dest": ".claude/packs/supabase.md", "template": true},
    {"src": "rules/database.md", "dest": ".claude/rules/database.md"}
  ],
  "hooks": [
    {"event": "PreToolUse", "matcher": "Bash", "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/x.sh", "timeout": 30}
  ],
  "permissions": {"allow": ["mcp__supabase__list_tables"], "deny": []},
  "mcp": {"supabase": {"type": "http", "url": "https://mcp.supabase.com/mcp?project_ref=${SUPABASE_PROJECT_REF}",
          "headers": {"Authorization": "Bearer ${SUPABASE_ACCESS_TOKEN}"}}},
  "env": [{"name": "SUPABASE_ACCESS_TOKEN", "purpose": "…", "how_to_get": "…"}],
  "third_party": [{"name": "…", "source": "github:owner/repo/path", "ref": "<40-hex commit>", "sha256": "<64-hex of the installed tree>", "license": "MIT"}],
  "ci": [{"src": "ci/x.yml", "dest": ".github/workflows/x.yml", "template": true}]
}
```

Rules for `pack.json`:
- **`detect.ask`** is set when a scan can't decide (for example worktrees). The installer then asks that question.
  Ticket packs carry no `detect.ask`: the installer selects the one named by the `TICKET_SYSTEM` fact.
- **`owner_tasks`** are `{task, why, when?}`. `when` is `{fact, equals}`, and the task is shown only when that fact
  has that value.
- **`template: true`** means the file holds `{{FACT}}` placeholders to fill at install.
- **MCP:** a server is defined only with `${ENV_VAR}` references. Never write a value.
- **MCP names:** a pack names its server by service (`jira`, `supabase`, `render`) and writes its tools as
  `mcp__<server>__<tool>`, in permissions and in text. The installer installs the server as `<MCP_PREFIX><server>`
  (or the project's server named in `mcp_map`) and rewrites every `mcp__<server>__` reference and every
  "`<server>` MCP server" phrase to match, so a project's agent only ever calls its own project's servers.
- **`env`:** every credential is an owner task.
- **`permissions`:** allow only read-only tools. Destructive commands go in `deny`.
- **Hook commands** always use `"$CLAUDE_PROJECT_DIR"/.claude/hooks/...`.

**Hooks contract** (core and packs):
- Block with **exit 2 and the reason on stderr**. Exit 0 allows.
- Never use exit 1 to block; it doesn't block.
- Read the event JSON from stdin.
- Fail open on internal errors, with a one-line stderr note.
- Never write outside `.claude/state/`.
- No network calls, unless the hook's purpose needs one (the worktree sync).
- Every hook ships a test: `hooks/test_<hook>.py`, stdlib `unittest`, feeding JSON on stdin and asserting the exit
  code.
- Python 3.9+ or POSIX sh. No dependencies.
- **Bash hooks parse, they don't grep.** A hook that inspects a Bash command imports the shared parser
  `core/hooks/kit_shell.py` (installed beside it in `.claude/hooks/`) with `sys.dont_write_bytecode = True` set first,
  so no `__pycache__` lands in `.claude/hooks/`. If the import fails, the hook fails open. `iter_commands()` yields
  every simple command, including `$(…)`, backticks, `bash -c`, `eval`, `xargs` and `find -exec` payloads.
- **Block messages teach.** Say what was blocked, which kit rule it breaks, and the allowed alternative.
- **Core hooks** are declared in `core/pack.json` `hooks`, the same way packs declare theirs. New hook commands use
  `python3 "$CLAUDE_PROJECT_DIR"/.claude/hooks/<x>.py` and an explicit `timeout`.
- **A rule and its hook stay in step.** `manifest.json` `checks.destructive_patterns` reasons are the keys of
  `block-destructive.py` `RULES`, and each has a blocked case in its test. A kit test enforces both.

**Codex.** Codex reads `AGENTS.md`. Hook enforcement is Claude-only in v1. Pack commands say what Codex does instead,
as in conventions §8.7.
