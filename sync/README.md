<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# sync: Claude ↔ Codex

Codex reads `.agents/skills/<name>/SKILL.md`. In an installed project each of those is a short wrapper: frontmatter
plus a relative link to `.claude/commands/<name>.md` and one to `AGENTS.md`. There are no symlinks and no copies, and
no rules are restated in a wrapper. These files generate the wrappers and keep them honest in CI.

Python 3.9+, standard library only. Nothing to install.

| File | Installed at | What it is |
|---|---|---|
| `make_skill_links.py` | `.github/scripts/make_skill_links.py` | Writes a wrapper for every command not listed in `claude-only.txt`. Idempotent; never deletes |
| `check_skill_links.py` | `.github/scripts/check_skill_links.py` | The CI check: links, copies, `AGENTS.md`, restated block, word budget, `skills-lock.json` |
| `test_make_skill_links.py` | `.github/scripts/test_make_skill_links.py` | Tests for the generator |
| `test_check_skill_links.py` | `.github/scripts/test_check_skill_links.py` | Tests for the check |
| `skill-link-check.yml.tmpl` | `.github/workflows/skill-link-check.yml` | The workflow. Its main-branch placeholder is filled at install |
| `claude-only.txt` | `.agents/claude-only.txt` | Commands that get no Codex skill. Empty apart from its header |

## Running

From the project root:

```
python3 .github/scripts/make_skill_links.py                   # write or refresh the wrappers
python3 .github/scripts/make_skill_links.py --check           # dry run; exits 1 if anything would change
python3 .github/scripts/make_skill_links.py --force-wrappers  # replace hand-written wrappers (old one kept as SKILL.md.pre-agent-kit)
python3 .github/scripts/check_skill_links.py --require-restated [--word-budget 3500]
python3 .github/scripts/test_make_skill_links.py
python3 .github/scripts/test_check_skill_links.py
```

Both scripts take `--repo <path>` to run against another directory. The check otherwise finds the repo root with git.

## What the generator reports

- `create`, `update` or `unchanged`. Only wrappers it made itself (they end with an `agent-kit: generated` comment)
  are ever rewritten.
- `conflict`: a wrapper that differs and isn't kit-made. It is left untouched unless you pass `--force-wrappers`.
- `stale`: a wrapper whose command is gone or is now Claude-only. It stays in place, the script suggests renaming it
  to `SKILL.md.pre-agent-kit`, and it exits 1.
- `skipped`: the command is listed in `claude-only.txt`.
- `error`: the command has no `description:`, can't be read, or has an unusable file name.

Native skills, meaning a `.agents/skills/<name>` with no matching command that doesn't link to one, are ignored.

## What the check enforces

- Every command has a wrapper that links to it (exact case), or is listed in `claude-only.txt`.
- A wrapper folder holds only `SKILL.md`. A `SKILL.md.pre-agent-kit` backup is a warning.
- There are no symlinks, and nothing under `.agents/rules/`.
- `AGENTS.md` links to `CLAUDE.md`, and to `CLAUDE.kit.md` when that exists. Every relative link in it resolves.
- The lines ending in `<!-- codex-restate -->`, from `CLAUDE.kit.md` then `CLAUDE.md`, appear verbatim and in
  order between `<!-- codex-restate:start -->` and `<!-- codex-restate:end -->` in `AGENTS.md`. In `CLAUDE.kit.md` only, every list item under
  its "Forbidden actions" heading must be tagged. A project's own `CLAUDE.md` is checked only for its tagged lines.
- `CLAUDE.md` + `CLAUDE.kit.md` + every `.claude/rules/**/*.md` without `paths:` frontmatter come to at most 3,500
  words by default. The kit's own text keeps to 2,500 (the kit tests check that), which leaves about 1,000 for the
  project's rules. Frontmatter and HTML comments are not counted, and a word must contain a letter or digit.
- `AGENTS.md`'s rule table (inside its `agent-kit:rules` markers) names every `.claude/rules/*.md`. A rule it leaves
  out fails the check; re-running the installer's `apply` regenerates the table. No rule table at all is a warning.
- When `skills-lock.json` exists, each locked skill's folder matches its 64-hex sha256 `computedHash`. Other hash
  formats are reported as unverifiable, not as failures.
