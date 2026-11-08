---
description: Migration guard. Validates a schema change before it is applied: additive policy, gated destructive steps, required header, backout, consumers. Never applies it.
argument-hint: "[<migration file>]"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# /guard

Reviews a schema change **before it is applied**. There is one database and no QA copy, so a bad migration hits
production. This gate validates the SQL. **It never applies it.** `/post-op` skips it when the diff has no schema
change and records `⏭️ Skipped — no schema change`.

## Step 1: Get the SQL

Where migrations live comes from `docs/agent/source-layout.md`. Review the given file, or each new or changed
migration in the diff:

```bash
git fetch origin <MAIN_BRANCH>
git diff --name-only origin/<MAIN_BRANCH>...HEAD -- <migrations path>
git status --short -- <migrations path>
```

If the project applies SQL through a tool with no migrations folder, review the exact SQL you are about to hand that
tool. Not written yet? Write it first, then run this gate.

## Step 2: Check the live schema

Use the project's read-only database access, named in the installed database pack's rule. Confirm the target table
exists (for ALTER) or doesn't yet (for CREATE). For column detail:

```sql
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = '<table>'
ORDER BY ordinal_position;
```

No read access? Record the check as NEEDS_CONTEXT. Don't assume the schema.

## Step 3: Additive policy

| Operation | Allowed? |
|---|---|
| `CREATE TABLE`, `CREATE INDEX` | ✅ |
| `ADD COLUMN`, nullable or with a default | ✅ |
| `RENAME COLUMN`, `ALTER COLUMN TYPE` | ❌ in one step. Phase it: add the new column → backfill → move every read and write → remove the old column in a later migration |
| Final column removal, `DROP COLUMN` | Owner-Kept Gate G5 |
| `DROP TABLE` | G5 |
| Data deletion: `TRUNCATE`, a `DELETE` or a lossy `UPDATE`/backfill | G5 |
| Making data readable by clients: policies, grants, public storage | G6 |

Never route around a gate, for example emptying a table instead of dropping it.

## Step 4: Safety table for gated steps

Every G5 step needs all of these before it goes to the owner. A missing one is NEEDS_CHANGES.

| Requirement | Why |
|---|---|
| A backout that really reverses the step (Step 6) | One database, no safety net |
| A snapshot where rows or values would be lost: a backup table or export in the same migration | Loss can't be undone otherwise |
| Every consumer moved in the same change (Step 7) | A live path must never read a column that is gone |
| Atomic or phased, chosen for safety: one migration if nothing breaks mid-flight; phased if a live path would break during the change | Avoids a broken window |

With all four in place, stop for the owner's explicit yes. Record it in the migration's `-- Purpose:` line.

## Step 5: SECURITY DEFINER functions

Every `SECURITY DEFINER` function sets a fixed `search_path` of trusted schemas in its own definition, for example
`SET search_path = public, pg_catalog`. Without it, an object in another schema can shadow a built-in and run with the
owner's privileges.

## Step 6: Header and backout

The SQL starts with these comments:

- `-- Purpose:` what it does and why;
- `-- Risk:` what could go wrong, and what depends on this schema;
- `-- Backout:` the exact SQL that reverses it;
- `-- Validation:` queries to run after applying, with the expected result.

List each missing section and what it should say. Then run the backout in your head against the migration: would it
restore the schema and data exactly? A backout that can't restore lost data needs the snapshot from Step 4.

## Step 7: Downstream consumers

Grep every source path in `docs/agent/source-layout.md` for each table and column touched:

```bash
git grep -nE "<table>|<column>" -- <source paths>
```

List every file that reads or writes them. Those are what `/test` and `/verify` must cover.

## Step 8: Pack checks

Packs may add checks here: see the section for this command in each installed `.claude/packs/*.md` (for example row-level security, grants, or a
CI grant checker).

## Step 9: Output

```
MIGRATION GUARD: <file or migration name>

Status: ✅ SAFE TO APPLY / ⚠️ NEEDS CHANGES / ⛔ NEEDS APPROVAL (G5/G6) / ❌ BLOCKED

Live schema:     ✅ target <exists / doesn't exist yet> / NEEDS_CONTEXT
Additive policy: ✅ additive only / ❌ <op> — phase it / ⛔ <op> — G5 / ⛔ <op> — G6
Gated steps:     n/a / <op> — backout ✅ · snapshot ✅ · consumers moved ✅ · atomic/phased ✅
SECURITY DEFINER:✅ search_path fixed / n/a / ❌ <fn> → add SET search_path
Header:          ✅ purpose · risk · backout · validation / ❌ missing <which>
Backout:         <the SQL> — reverses cleanly ✅ / ❌ <why not>
Consumers:       tables/columns <list> · files <list> · all moved in this change ✅/❌
Validation:      1. <query> → <expected>
Pack checks:     <one line per pack> / n/a

Recommendation: APPLY (through the project's migration step) / FIX FIRST / NEEDS APPROVAL (G5 or G6)
Owner action: none | <yes or no on the gated step>
```

## Rules

- Validate only. Never apply the SQL in this gate.
- A verified database defect on this ticket's path (missing header or backout, a non-additive step, a broken key or
  `search_path`) joins this ticket's contract and is fixed before `/post-op` can be clean. "Pre-existing" is no excuse.
- A destructive step without the owner's recorded yes: stop and flag it. Don't suggest a workaround.

## Completion status

End with one of:

- **DONE**: safe to apply; header present, backout checked, consumers covered.
- **DONE_WITH_CONCERNS**: can proceed; list each item.
- **NEEDS_CHANGES**: add the missing header section, backout, snapshot or consumer update. Say which.
- **BLOCKED**: a G5 or G6 step without the owner's yes, or a step that breaks the additive policy. Say what must
  change.
- **NEEDS_CONTEXT**: the migration or the target table can't be found. Say what is missing.
