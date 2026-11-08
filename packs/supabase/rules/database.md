---
paths:
  - "supabase/**"
  - "{{MIGRATIONS_DIR}}/**"
  - "**/*.sql"
  - ".github/scripts/*function_grants*"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

# Database rules (Supabase)

Values written `<LIKE_THIS>` come from the Pack facts table in `.claude/packs/supabase.md`, or from the Project
facts block in `CLAUDE.md`. Gates G5, G6 and G7 are defined in `CLAUDE.kit.md`.

There is one database, `<DB_PROJECT_REF>`, and no QA copy. A bad migration hits production, so the bar is high.
Never point a migration at any other project.

## Migration path

Schema changes go only through `<MIGRATION_TOOL>`. Never run DDL by hand: not through psql, the dashboard SQL
editor, `execute_sql` or a script.

- **`supabase-cli`.** `supabase migration new <name>` creates a timestamped file in `<MIGRATIONS_DIR>`. Write the
  SQL there, on the feature branch.
- **`mcp-apply`.** There is no migrations folder. Never commit a `.sql` file or create a folder for one: Supabase's
  migration ledger (`list_migrations`) is the record, and a file on disk is a second copy that silently diverges.
  Compose the SQL in `.claude/state/<ticket>/migrations/<nn>-<name>.sql`; the header comments go inside the SQL
  passed to `apply_migration`, through the write-enabled server, and every call prompts.
- **Reads** go through the read-only Supabase MCP server: `list_tables`, `list_migrations`, `list_extensions`,
  `get_advisors`, and `execute_sql` for `SELECT` only.

**When it is applied.**

- **Additive migrations go live before merge, on the same ticket.** Once `/guard` returns SAFE TO APPLY, the pack's
  apply step (`.claude/packs/supabase.md`, `/verify` section) applies it to production, with the privilege
  assertion before and after. The code is then tested and verified against the real schema and shipped on the same
  ticket. Old code on `<MAIN_BRANCH>` ignores the new objects, which is why only additive steps may go out this way.
- **A G5 step never goes out pre-merge.** A drop, a final column removal or a data deletion is its own migration on
  its own ticket, opened once nothing reads the old shape. It is applied only after its PR merges, and only with
  the owner's recorded G5 yes.
- **A G6 step** (a grant, policy or public bucket that makes data client-readable) is applied only after the
  owner's recorded G6 yes.
- **An applied migration is never edited.** A fix is a new migration on the same branch, guarded and applied the same
  way. `/ship` checks that the merged file is byte-for-byte the one that was applied.
- **A branch that won't merge** leaves its additive schema live. Record it on the tracker; removing it is G5.

**Worktree trap.** A migration file created in one checkout and edited in another is two different files, and the
apply reads only one of them. Create, edit, apply and commit from the checkout that holds the branch.
`supabase db push --dry-run` must list exactly this branch's unapplied files. If the ledger records a version but
its objects are missing (an empty apply), stop and report it. Repairing the ledger is the owner's call.

## Every migration

- Starts with the `-- Purpose:`, `-- Risk:`, `-- Backout:` and `-- Validation:` header (`/guard`). Validation
  queries are read-only.
- Is additive. A rename, a type change or a removal is phased: add → backfill → move every read and write → remove
  in a later migration. The final removal, `DROP`, and any data deletion are G5. Record the owner's yes in
  `-- Purpose:`.
- A test that pins a live constraint or enum definition verbatim (for example a `pg_get_constraintdef` string) is
  updated in the same diff as the migration that changes it. `/verify` re-reads the live definition and compares.

## Tables, views and sequences: service role only

- Every `CREATE TABLE` is followed at once by `ALTER TABLE <name> ENABLE ROW LEVEL SECURITY;` and the comment
  `-- No policies: service role only.` The service role bypasses RLS; `anon` and `authenticated` get nothing.
- Never grant a table, view or sequence to `PUBLIC`, `anon` or `authenticated`: not by name, not with `ALL TABLES |
  SEQUENCES IN SCHEMA`, not through `ALTER DEFAULT PRIVILEGES`, not with `OWNER TO`.
- While the project's default privileges still grant new objects to `anon`/`authenticated` (the `default` rows of
  the privilege assertion in `.claude/packs/supabase.md`), each new table, view and sequence also gets
  `REVOKE ALL ON <object> FROM anon, authenticated;` in the same migration. RLS is the second lock, not the first.
- Never revoke from `service_role` without `GRANT ALL … TO service_role` back on the same objects.
- **A table a client must read directly is G6.** In the same migration: RLS, policies that check the **caller**
  (`auth.uid()` or a JWT claim), and a `GRANT` of exactly the needed privileges to `authenticated` (to `anon` only
  for truly public data). The CI checker has no table exemption, so the same PR changes the checker, which is G7.
- A policy whose `USING` tests only the row (`expires_at > now()`) makes every matching row public once a grant
  exists. Every policy checks the caller.

## Functions

Every function in an exposed schema is callable through `/rest/v1/rpc` by any role with EXECUTE. The anon key is
public, and a `SECURITY DEFINER` function runs as its owner and bypasses RLS. So every `SECURITY DEFINER` function:

```sql
CREATE OR REPLACE FUNCTION public.my_fn(p_id uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_catalog
AS $$ … $$;
REVOKE EXECUTE ON FUNCTION public.my_fn(uuid) FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION public.my_fn(uuid) TO service_role;
```

- `SET search_path` in its own definition, so another schema's object can't shadow a built-in.
- The REVOKE names all three roles: Supabase grants `anon` and `authenticated` explicitly, so `FROM PUBLIC` alone
  leaves them in. `REVOKE GRANT OPTION FOR …` and `REVOKE … GRANTED BY <another role>` don't count.
- CREATE, REVOKE and GRANT sit in one migration, which runs as one transaction, so the function is never callable
  by the API roles in between. The lock comes **after** the function's last `CREATE`; a lock written before a
  `DROP` + re-`CREATE` doesn't apply to the new object.
- Never grant a function to `PUBLIC`/`anon`/`authenticated`, singly, in bulk or through default privileges. The only
  exceptions are `<RLS_HELPER_EXEMPTIONS>`: helpers that RLS policies call as the requesting role. After any
  re-`CREATE` each gets `GRANT EXECUTE … TO anon, authenticated, service_role`; never revoke, rename or move it, or
  `DROP … CASCADE` it (that drops the policies that call it). Adding an exemption is G6 and G7.
- A function another role must call needs an explicit grant (an Auth hook → `supabase_auth_admin`), or that role
  gets error 42501.
- Privilege changes are plain statements, never SQL inside a string. In a body, `EXECUTE` runs one literal, or
  `format('<literal>', …)` with `%I`/`%L`, or `%s` fed by a `reg*` cast or a catalog formatter.
- CI also rejects: making an API role an owner or a member of another role; `SET ROLE` and
  `set_config('role', …)`; `ALTER ROLE anon|authenticated` with `BYPASSRLS`, `SUPERUSER` or `SET role`; writes to
  `pg_proc`, `pg_default_acl` or `pg_auth_members`; `ALTER EXTENSION … ADD FUNCTION` on an app function.

Validate grants with `has_function_privilege`, never by searching `proacl` text: a `PUBLIC` grant shows as `=X`
with no role name, and a NULL `proacl` means the default, under which `PUBLIC` can execute.

```sql
SELECT has_function_privilege('anon',          'public.my_fn(uuid)', 'EXECUTE') AS anon,          -- false
       has_function_privilege('authenticated', 'public.my_fn(uuid)', 'EXECUTE') AS authenticated, -- false
       has_function_privilege('service_role',  'public.my_fn(uuid)', 'EXECUTE') AS service_role;  -- true
```

The CI check (`.github/scripts/check_function_grants.py`) catches honest mistakes. Disguised SQL is code review's
job, and `/ship`'s live privilege assertion checks the result whatever the SQL looked like.

## Storage

- Buckets are private by default. Private files are served through short-lived signed URLs; store the bucket and
  object path, never a signed URL and never a local folder path.
- A public bucket, or a storage policy that lets a client read objects, is G6.
- Media and generated files live in storage, not in git.

## Deletes

- Scope a cleanup to the records actually deleted: find the true orphans first, never the whole membership set.
- Cover every identifier column the matching write function writes. Read the writer first.
- A write that references a row deleted earlier in the request, by foreign key, fails, even a nullable one. An audit
  row written after the delete uses `null` for the key and carries the identity in its details.

## Advisors (`get_advisors`)

- `rls_disabled`: always a bug. Fix it at once.
- `rls_enabled_no_policy`: expected for service-role-only tables.
- `anon_security_definer_function_executable`, `authenticated_security_definer_function_executable`: always a bug.
  Lock the function to `service_role`.

## App code

- Queries go through the Supabase client, parameterized; never build SQL strings from input.
- Server code uses the service-role client. The service-role (secret) key never reaches a client bundle.
- A client using the anon key reads no table (service role only). Giving it one is G6.
