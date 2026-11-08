---
description: Docs gate. Updates the docs this change affects (API spec, help content, READMEs, planning docs) using the project's docs map, with targeted edits.
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# /docs-update

Updates the docs this change affects, on the feature branch before merge. Docs are part of the feature, not a
post-merge step. `docs/agent/docs-map.md` says which doc to update for which kind of change.

**Skip** when no docs-map row matches the diff, no planning doc is affected (Step 5) and no touched folder has a
README. Still print the output block, with `⏭️ Skipped — no affected docs`.

## Step 1: What changed

```bash
git fetch origin <MAIN_BRANCH>
git log --oneline origin/<MAIN_BRANCH>..HEAD
git diff origin/<MAIN_BRANCH>...HEAD
git diff HEAD
```

Sort the changes by the kinds in `docs-map.md` (new or changed endpoints, user-facing flows, pricing, auth and so on).
Update only the docs mapped to those kinds. Don't touch unrelated docs.

## Step 2: API spec

Only if endpoints were added or changed, and `docs-map.md` names an API spec.

- New endpoint: add a full entry in the file's existing format: summary, auth, params, request body, responses
  (success, 4xx, 5xx), matching the response envelope.
- Changed endpoint: update its entry. Never remove a documented field; the API is additive.
- **Field-level check, for every response change**, even when the endpoint already has an entry: find every place
  the changed handler builds its response, list each field it returns, and confirm each one appears in the documented
  schema. Add any that are missing. Incremental field additions slip through otherwise.
- Check the spec still parses: run the project's validator if it has one, else check braces and brackets match.

The spec must match the implemented endpoint, not the ticket description.

## Step 3: Mapped docs

For each other doc `docs-map.md` names for this kind of change (help content, FAQs, knowledge base, prompts, portal
pages):

- Make targeted edits. Never rewrite a doc or prompt wholesale.
- Keep the existing structure. User-facing text is in `<UI_LANGUAGE>` and follows `docs/agent/copy-rules.md`.
- Keep it factual and short, not marketing.
- Don't change a legal reference unless the change altered compliance behaviour.

## Step 4: READMEs

For each folder the diff touches, check for a README.

1. Read it in full.
2. Update only the sections that are now wrong or incomplete. Keep its language.
3. Never create a README unprompted. If a folder clearly needs one, note it under DONE_WITH_CONCERNS.

## Step 5: Planning and architecture docs

These rot silently: a ticket ships, and the plan still says "not built, next: <ticket>", misleading the next session.

Find every docs folder, read-only:

```bash
find . -type d -name docs -not -path "*/node_modules/*" -not -path "*/.git/*" -not -path "*/dist/*" -not -path "*/build/*"
```

Add any other doc folders `docs-map.md` names. `docs/agent/` holds the project's agent files; change it only where
`docs-map.md` says to. For each planning doc this change affects:

1. **Check reality first, never the diff or memory.** For every ticket the doc names, ticket op **get** `<ticket>`
   (or **search**) for its real status, and confirm the feature's state in the code. A confidently wrong doc is worse
   than a stale one.
2. **Status headers:** flip `not built` / `design` / `in progress` once the work has shipped (done in the ticket
   system and present in code). Name the shipped ticket and the live files or tables.
3. **Board and lane tables:** match them to the ticket system. Mark shipped work done; move deferred work to its
   right lane; call out anything parked so it isn't pulled forward by mistake.
4. **"Next action" and "current state":** point them at the real next open work. Set any "as of" date to today.
5. Edit status, board and next-action lines only. If deeper prose is stale and risky to rewrite, flag it under
   DONE_WITH_CONCERNS.

If a docs folder is unaffected, say so. Don't touch it.

## Step 6: Pack checks

Packs may add checks here: see the section for this command in each installed `.claude/packs/*.md`.

## Step 7: Output

Always print this block, even when nothing changed.

```
DOCS UPDATE: <branch>

API spec:        ✅ no API changes — skipped / ✅ updated: <endpoints> · field check ✅ / ❌ <field> missing
Mapped docs:     ✅ none affected / ✅ updated: <path> — <what>
READMEs:         ✅ none in touched folders / ✅ no change needed / ✅ updated: <path> — <what>
Planning docs:   ✅ none affected / ✅ updated: <path> — <status / board / next action / as-of>
Pack checks:     <one line per pack> / n/a
Concerns:        none / <item>
Owner action: none
```

## Rules

- Never invent a feature or capability that isn't in the diff.
- Targeted edits, never rewrites.

## Completion status

End with one of:

- **DONE**: every affected doc updated, or none needed (say which).
- **DONE_WITH_CONCERNS**: list each item for human review.
- **BLOCKED**: a required doc or the diff can't be read. Say what is missing.
- **NEEDS_CONTEXT**: you can't tell what changed or which docs it affects. Say what you need.
