<!-- Copyright 2026 Tharwat Abdul-Malik. Licensed under the MIT License (see LICENSE). -->
# Changelog

Each entry says what changed and what an upgrade will touch. The installer prints the entries newer than a project's
installed version before an upgrade.

## 1.7.1 — 2026-11-13 (hardening 1.0.1)

- **hardening pack: `block-push-before-review.py` closes the routes to main it missed.** While a hardening run hasn't
  passed post-op it now also blocks:
  - any write through the GitHub API from `gh api`, `curl`, `wget`, httpie or `xh` (a method other than GET/HEAD, in
    any spelling such as `-sXPUT` or `--method=put`; the host in any case, with a port or a trailing dot; paths with
    `..` resolved; curl's `--request-target`), except comments, labels, reviews, review requests and issues. That
    covers PR merges, `/merges`, ref updates and contents writes. httpie and xh send stdin as a body without saying
    so, so for them only an explicit `GET` / `HEAD` is a read;
  - GraphQL mutations (also JSON-escaped in a body file), and a GraphQL write whose query is a shell variable, an
    unreadable file or unseen stdin;
  - inline code (`python3 -c`, `node -e`, a script on stdin) that runs `gh pr merge`, `gh api`, a migration or a push
    to main (also in list form, `['gh', 'pr', 'merge']`), writes to the GitHub API, or merges through a GitHub client
    library (PyGithub, Octokit);
  - `git push` with a `:` or glob refspec, `HEAD` / `@` or a bare `git push` while on the main branch, and git's
    `--config-env` option before `push`;
  - GitHub MCP `merge_pull_request`, and `push_files` / `create_or_update_file` / `delete_file` on the main branch or
    with no branch named (a GitHub server by name, or a tool input with `owner` and `repo`).
- **It reads commands with the core parser** (`kit_shell.py`) and finds these tools anywhere in a command's words,
  so `bash -c "…"`, `eval`, heredoc scripts, `xargs` and launchers such as `op run --`, `caffeinate -i` or
  `watch -n 5` don't hide them. A quoted word with spaces (a commit message, a grep pattern) is data, so a command
  that only mentions a merge or a migration is no longer blocked. Without the parser, or when a command doesn't
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
