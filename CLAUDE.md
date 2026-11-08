<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# CLAUDE.md: working on agent-kit itself

This repo **is** the kit: Claude Code + Codex workflow files that `INSTALL.md` installs into other projects. These
instructions are for changing the kit. They are not the rules the kit installs; those are in
`core/CLAUDE.kit.md.tmpl`.

- **Read `docs/kit-conventions.md` first.** It is the binding contract for every file in `core/` and `packs/`:
  notation (`{{FACT}}`, `<FACT>`), Project facts, the main-only branch model, the Owner-Kept Gates, ticket ops,
  notify, the helper script, the pack format and the hooks contract.
- **No project facts in the kit:**
  - no product names, ticket keys, project refs, domains, chat IDs, account names or absolute paths;
  - placeholders only, never a secret.
  - A gitignored `denylist.private.json` (if present) adds the owner's project-specific patterns to the leak tests.
- **No destructive commands,** in what you run or in what you write: no `rm`, `rmdir`, `git reset --hard`,
  `git clean`, force-push or `branch -D`. A replaced file is renamed `<file>.pre-agent-kit`.
- **Every new file** starts with the copyright line `Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT
  License).`, as a comment in that file type's syntax. Put it after frontmatter or a shebang. JSON is exempt.
- **Always-loaded budget:** `core/CLAUDE.kit.md.tmpl`, plus `core/CLAUDE.md.tmpl`, plus unscoped rules, must total
  ≤ 2,500 words. Pack rules carry `paths:`.
- **Before committing,** run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests`. It runs the schemas,
  the content checks, the installer scenarios and every unit's own suite. Keep it green.
- **A new pack** needs `packs/<name>/pack.json` (validated by `schemas/pack.schema.json`) and an entry in
  `manifest.json` `units`. Record it in `CHANGELOG.md`.
- **No AI attribution:** no `Co-Authored-By:` trailer and no "Generated with" line in commits or PR bodies, here
  or in anything the kit tells an agent to write.
- **Ask the owner** one question at a time, with a pro and a con for every option. Work on a branch and open a PR
  to `main`. Don't push without the owner's go-ahead.
