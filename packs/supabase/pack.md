<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Supabase pack

Steps this pack adds to core commands. Each command reads its own section at its hook line. The database rules are in
`.claude/rules/database.md`, which loads when a migration or SQL file is touched.

## Pack facts

| Fact | Value | Meaning |
|---|---|---|
| `DB_PROJECT_REF` | `{{DB_PROJECT_REF}}` | The one Supabase project. There is no QA project |
| `MIGRATION_TOOL` | `{{MIGRATION_TOOL}}` | `supabase-cli` (files in the repo, `supabase db push`) or `mcp-apply` (`apply_migration`, no folder) |
| `MIGRATIONS_DIR` | `{{MIGRATIONS_DIR}}` | Where migration files live; `none` with `mcp-apply` |
| `RLS_HELPER_EXEMPTIONS` | `{{RLS_HELPER_EXEMPTIONS}}` | RLS helper functions that stay executable by `anon`/`authenticated`, as `schema.name(arg types)`; `none` by default |

**Database access.** Reads go through the read-only MCP server `supabase` (`read_only=true`): `list_tables`,
`list_migrations`, `get_advisors`, and `execute_sql` for `SELECT` only. With `mcp-apply`, writes go through the
write-enabled server `supabase_apply`, whose tools are never pre-allowed, so every call prompts. **Codex:** if no
Supabase MCP is configured for Codex, record every live check as NEEDS_CONTEXT. Never assume the schema.

**Migration list.** "This branch's migrations" means: with `supabase-cli`,
`git diff --name-only --diff-filter=A origin/<MAIN_BRANCH>...HEAD -- <MIGRATIONS_DIR>`; with `mcp-apply`, the files
in `.claude/state/<ticket>/migrations/`, in name order. `.claude/state/<ticket>/migrations-applied.txt` records each
one the apply step ran: file name and the sha256 of the exact bytes applied.

### Privilege assertion (read-only)

Asks Postgres itself what the API roles can reach, so it checks the result, not the SQL text. Fill the `exempt`
array from `<RLS_HELPER_EXEMPTIONS>` (each one quoted; write `ARRAY[]::text[]` when there are none) and the schema
array with every schema the API exposes (`[api] schemas` in `supabase/config.toml`; usually just `public`).

```sql
WITH api(r) AS (VALUES ('anon'), ('authenticated')),
exposed AS (SELECT unnest(ARRAY['public']::regnamespace[]) AS ns),
exempt AS (
  SELECT to_regprocedure(e)::oid AS oid FROM unnest(ARRAY[]::text[]) AS e
  WHERE to_regprocedure(e) IS NOT NULL
),
app_fn AS (
  SELECT p.oid FROM pg_proc p
  WHERE p.pronamespace IN (SELECT ns FROM exposed)
    AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e')
),
app_rel AS (
  SELECT c.oid, c.relkind FROM pg_class c
  WHERE c.relnamespace IN (SELECT ns FROM exposed) AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
    AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e')
)
SELECT 'function' AS class, f.oid::regprocedure::text AS object, a.r || ' can EXECUTE' AS problem
FROM app_fn f CROSS JOIN api a
WHERE f.oid NOT IN (SELECT oid FROM exempt) AND has_function_privilege(a.r, f.oid, 'EXECUTE')
UNION ALL
SELECT 'function', f.oid::regprocedure::text, 'service_role cannot EXECUTE'
FROM app_fn f WHERE NOT has_function_privilege('service_role', f.oid, 'EXECUTE')
UNION ALL
SELECT 'relation', c.oid::regclass::text, a.r || ' holds a privilege'
FROM app_rel c CROSS JOIN api a
WHERE CASE WHEN c.relkind = 'S' THEN has_sequence_privilege(a.r, c.oid, 'USAGE,SELECT,UPDATE')
           ELSE has_table_privilege(a.r, c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                OR has_any_column_privilege(a.r, c.oid, 'SELECT,INSERT,UPDATE,REFERENCES') END
UNION ALL
SELECT 'relation', c.oid::regclass::text, 'service_role lacks ' || p
FROM app_rel c
CROSS JOIN LATERAL unnest(CASE WHEN c.relkind = 'S' THEN ARRAY['USAGE', 'SELECT', 'UPDATE']
                               ELSE ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] END) p
WHERE NOT CASE WHEN c.relkind = 'S' THEN has_sequence_privilege('service_role', c.oid, p)
               ELSE has_table_privilege('service_role', c.oid, p) END
UNION ALL
SELECT 'default', coalesce(nullif(d.defaclnamespace, 0)::regnamespace::text, '*') || ':' || d.defaclobjtype::text,
       CASE WHEN x.grantee = 0 THEN 'PUBLIC' ELSE x.grantee::regrole::text END || ' in postgres default privileges'
FROM pg_default_acl d, aclexplode(d.defaclacl) x
WHERE d.defaclrole = 'postgres'::regrole
  AND (d.defaclnamespace = 0 OR d.defaclnamespace IN (SELECT ns FROM exposed) OR d.defaclnamespace = 'storage'::regnamespace)
  AND (x.grantee = 0 OR x.grantee IN ('anon'::regrole, 'authenticated'::regrole))
UNION ALL
SELECT 'default', '*:f', 'PUBLIC in postgres default privileges (no global function row = built-in default)'
WHERE NOT EXISTS (SELECT 1 FROM pg_default_acl WHERE defaclrole = 'postgres'::regrole AND defaclnamespace = 0 AND defaclobjtype = 'f')
ORDER BY 1, 2, 3;
```

- Only the `has_*_privilege` functions decide. A NULL ACL means the built-in default, and a `PUBLIC` or column
  grant counts. Never search `proacl`/`relacl` text for a role name.
- An exemption is the exact identity only; a new overload of an exempt name is flagged. Extension-owned objects are
  excluded through `pg_depend`.
- `default` rows mean new objects will be opened automatically. Until they are gone, every migration revokes its
  new objects explicitly (`.claude/rules/database.md`).
- **Rows that exist before a migration** are a pre-existing finding, not this ticket's failure. Report them once:
  ticket op **search** for an open ticket on the API privilege lock-down; none → ticket op **create** one with the
  rows. Locking them down is its own migration. **Rows that appear after a migration** are this ticket's failure.

## /triage

Contract rows to add when the ticket touches the database:

| Trigger | Row |
|---|---|
| A query using `.maybeSingle()` or `.single()` | Can it ever match more than one row (two writers, concurrent requests)? Zero rows? |
| New logic reading a column | The null / absent / zero-rows case, with nullability confirmed in the live schema |
| A new table, function, bucket or policy | Who can reach it: service role only, or G6 with caller-checking policies |
| New code that needs a schema change | An additive migration, guarded and applied before merge on this ticket (`/verify` apply step). A G5 step is its own ticket, applied after merge with the owner's yes |

## /guard

Run these at Step 8, on every migration in this branch's list. Each `❌` is BLOCKED. `/guard` validates; it never
applies. The apply is a separate step that follows a SAFE TO APPLY result: the apply step in this pack's `/verify`
section, for additive migrations only.

1. **RLS gate.** Every `CREATE TABLE` has `ALTER TABLE <name> ENABLE ROW LEVEL SECURITY` in the same file.
2. **Table-grant gate.** Nothing grants a table, view, materialized view, foreign table or sequence to `PUBLIC`,
   `anon` or `authenticated`: not by name, not bare `ON <name>`, not `ALL TABLES|SEQUENCES IN SCHEMA`, not
   `ALTER DEFAULT PRIVILEGES`, not `OWNER TO`, not even if a later statement revokes it. No revoke from
   `service_role` without `GRANT ALL … TO service_role` back. No policy whose `USING` lacks a caller check.
   While the project's default privileges still open new objects (the assertion's `default` rows), each new
   object is revoked from `anon, authenticated` explicitly. The one exception is a G6-approved client-readable
   table (`.claude/rules/database.md`).
3. **DEFINER EXECUTE gate.** Every `SECURITY DEFINER` function (created, or altered to it) has, after its last
   `CREATE`, `REVOKE EXECUTE … FROM PUBLIC, anon, authenticated` (all three) and
   `GRANT EXECUTE … TO service_role`. Also BLOCKED: any function grant to the API roles except
   `<RLS_HELPER_EXEMPTIONS>` (exact identity); `SECURITY DEFINER` inside a body; privilege SQL inside a string;
   role membership or ownership for the API roles; role switching; catalog writes.
4. **CI checker.** Run the check CI runs:
   - `supabase-cli`: `python3 .github/scripts/check_function_grants.py`
   - `mcp-apply`: `python3 .github/scripts/check_function_grants.py --file .claude/state/<ticket>/migrations/<file>.sql`
     for each file, if the script is installed. Not installed → do gates 1–3 by reading.
5. **Validation section** proves the lock with `has_function_privilege('anon'|'authenticated'|'service_role',
   '<fn>(<args>)', 'EXECUTE')` → false / false / true, and for a new table
   `has_table_privilege('anon', '<table>', 'SELECT')` → false.
6. **Live schema** (core Step 2) uses the read-only `supabase` server: `list_tables`, or `execute_sql` on
   `information_schema.columns`.

Output lines for `Pack checks:`

```
RLS gate:        ✅ every CREATE TABLE enables RLS / ❌ <table>
Table grants:    ✅ none to PUBLIC/anon/authenticated; service_role keeps ALL / ❌ <statement>
DEFINER grants:  ✅ revoked from PUBLIC, anon, authenticated; granted to service_role / n/a / ❌ <fn>: missing <what>
CI checker:      ✅ passed / ❌ <first failure> / ⏭️ not installed
Next step:       apply before merge (/verify apply step) / G5 — own ticket, applied after merge with the owner's yes / G6 — owner's yes first
```

## /ship

Skip when this branch's migration list is empty. Migrations are already live (the `/verify` apply step); `/ship`
never applies one.

**At the hook after Step 0.4 (before the PR):**

1. Every file in the list is in `migrations-applied.txt`, and its current sha256 equals the recorded one. A file
   never applied → stop and run the apply step. A changed hash → **stop**: the file no longer matches the live
   schema. Restore the applied text and put the change in a new migration (guarded and applied the same way).
2. `list_migrations` shows each one applied (`supabase-cli`: `supabase migration list` shows it local and remote).
3. `mcp-apply`: put each applied SQL file, in full, in the PR body under `## Migrations (applied)`. It is the only
   copy reviewers see.

**At the hook after Step 2:** add one line to the G3 question: `Migrations: <files>, already live on <DB_PROJECT_REF>`. If the
owner holds the PR, the schema stays live: record it on the tracker; removing it is G5.

**At Step 4.1, with `/verify`'s post-merge half:** confirm the merged branch holds exactly what was applied.

- `supabase-cli`: for each file, the sha256 of `git show origin/<MAIN_BRANCH>:<MIGRATIONS_DIR>/<file>` equals the
  hash in `migrations-applied.txt`, and `supabase migration list` shows local and remote in step.
- `mcp-apply`: `list_migrations` holds each name, and the merged PR's body holds its SQL.
- A mismatch means the file on `<MAIN_BRANCH>` and the live schema disagree. Say so at once and loudly, notify, and
  fix forward on a new ticket with a new migration. Never edit the applied file to match.

Report line: `Migrations: <files> live since <time> · merged file = applied ✅ | ❌ <what differs>`.

## /verify

**Apply step (before merge; at Step 0, before driving anything).** Code that needs this branch's schema is tested
and verified against the real database, so an additive migration goes live first. Run it as soon as the migration
is written and `/guard` passes; `/operate` calls it too. For each file in the branch's list not yet in
`migrations-applied.txt`, in order:

1. **Preconditions.** `/guard` on this exact file returned SAFE TO APPLY: additive, no G5 step, CI checker passed.
   A G5 step never goes out this way. A G6 step needs the owner's recorded yes first.
2. **Before.** Run the privilege assertion; save its rows to `.claude/state/<ticket>/privileges-before.txt`. Rows
   already there are pre-existing: file them once on the lock-down ticket (see the assertion's notes). They never
   block this ticket.
3. **Apply.**
   - `supabase-cli`: from the checkout that holds the branch, `supabase db push --dry-run`. It must list exactly
     this file (or this branch's unapplied files). Anything else, or a complaint that the file is older than the
     newest applied migration → stop. For the age case, re-create it with `supabase migration new` and move the
     SQL in, then `/guard` it again. Then `supabase db push`.
   - `mcp-apply`: `apply_migration` on `supabase_apply`, named after the file, with the file's full SQL, header
     included. It prompts.
4. **Record** the file name and the sha256 of the exact bytes applied in `migrations-applied.txt`. From now on the
   file is frozen; a fix is a new migration.
5. **Confirm.** `list_migrations` shows it; each `-- Validation:` query (read-only) returns what it says.
6. **After.** Run the privilege assertion again. **A row that is not in `privileges-before.txt` is a FAIL.**
7. **On failure** (apply, validation or a new row): nothing is merged, so `<MAIN_BRANCH>` is unaffected, but the
   live schema is now wrong. Stop, notify, and fix forward on this branch with a new migration that closes the gap,
   guarded and applied the same way. A fix that would drop or delete anything is G5.

Report it in the verify output: `Migrations: <file> applied <time> · validation ✅ · privileges: no new rows`.

**A migration-only change** is verified by the apply step's validation queries and the privilege assertion, and by
driving any path that reads the new schema.

**State checks** use `execute_sql` on the read-only `supabase` server, `SELECT` only. Assert the derived values (a
computed status, a masked field, a count), not just that a row exists. The read-only server can't write, so the
core Step 1.5 teardown runs through the teardown or seed command in `docs/agent/verify-map.md`. With `mcp-apply`,
`execute_sql` on `supabase_apply` may run exactly that teardown `DELETE`, by explicit IDs and the marker; it
prompts. No other write goes through `execute_sql`.

**Pinned definitions.** If the migration changed a constraint or enum that a test pins verbatim, re-read it
(`SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = '<name>'`) and compare with the test fixture.

## /investigate

| Signature | Look at |
|---|---|
| `PGRST116`, "JSON object requested, multiple (or no) rows returned" | `.single()` on a query that can return 0 or several rows; `.maybeSingle()` with several |
| `42501` permission denied | A role with no grant: a client on the anon key, or an Auth hook or helper that lacks EXECUTE |
| A result that is silently empty | RLS filtering the caller's rows; the anon-key client used where the service-role client was meant |
| A list cut short at the same size every time | The API's max-rows cap with no `.range()` paging |
| Data that "didn't save", with no error | `{ data, error }` returned and `error` never checked |

Read database logs with the `supabase` server's log tool (`get_logs` or `query_logs`, whichever it offers).

## /security

Add to Step 8:

- **Buckets.** `SELECT id, public FROM storage.buckets;` Every `public = true` bucket has a recorded G6 yes; any
  other is BLOCKED. New code serves private objects with `createSignedUrl` and a short expiry, never
  `getPublicUrl`, and stores bucket + path, never a signed URL. New storage policies on `storage.objects` that let
  a client read are G6.
- **Keys.** The anon (publishable) key is public by design and may ship in a client. The service-role (secret) key
  never does: grep client source and client-exposed env prefixes for it. A client that queries a table, or calls an
  RPC directly, needs a G6 grant; flag any new one.
- **Advisors.** `get_advisors` (security): `rls_disabled` and the `*_security_definer_function_executable` lints are
  BLOCKED.

`Pack checks:` line: `Supabase: buckets <n> private, <n> public (G6 ✅) · service key not in clients ✅ · advisors clean ✅`.

## /post-op

**Mock Fidelity, Check B (query-builder coverage).** For every Supabase client mock the diff adds or changes (a
chain mock or equivalent), list the methods it exposes. Then list every chain method the code under test calls:

```bash
grep -nE "\.(maybeSingle|single|select|eq|neq|gt|gte|lt|lte|is|in|not|or|match|ilike|like|order|limit|range|insert|update|upsert|delete|rpc)\(" <file under test>
```

Each method the real code calls must exist on the mock. A mock missing `.maybeSingle()` passes the test while
production throws `.maybeSingle is not a function`. RPC mocks return the shape the function's signature gives (see
the lens below).

## /release

Migrations went live before their PRs merged, so a release ships no schema. It checks that the schema and
`<MAIN_BRANCH>` agree:

- **Ledger.** `list_migrations` holds every migration in the range (`supabase-cli`: `supabase migration list`
  shows local and remote in step). A live migration that isn't on `origin/<MAIN_BRANCH>` is from a held or
  abandoned branch: list it, with its ticket.
- **Backouts.** Every migration in the range has a `-- Backout:` that really reverses it, read step by step. A
  backout that loses data is G5 and needs a snapshot.
- **G5 steps** in the range were applied after their own PR merged, with the owner's recorded yes.
- **Privileges.** The privilege assertion shows no rows beyond the known lock-down ticket's list.
- **Rollback plan, schema part:** each backout, newest first, and who runs it. Rolling code back doesn't roll the
  schema back; additive schema can stay.

`Pack sections:` line: `supabase: <n> migrations live · ledger = <MAIN_BRANCH> ✅ | unmerged: <names> · backouts ✅ · privileges ✅`.

## /operate

When the change needs schema: write the migration first, run `/guard` on it, then run the apply step in this pack's
`/verify` section before writing code that reads the new schema, so tests and local runs meet the real database.

## bteam lenses

**SQL / PostgREST / RPC shape** (number it after core's 8 and any other pack's lenses):

- Every new `SECURITY DEFINER` function sets `search_path` and is revoked from `PUBLIC, anon, authenticated` and
  granted to `service_role` in the same migration. `FROM PUBLIC` alone leaves it callable with the anon key.
- Every INSERT/UPDATE column exists in the live schema with that nullability. A wrong column in a select returns an
  error or null, not the data.
- `EXCEPTION` blocks protect only the statement they wrap: catching `unique_violation` at one INSERT doesn't cover a
  later one, and an uncaught error rolls back the whole function, idempotency record included.
- The idempotency INSERT of an atomic RPC is in the same transaction as its side effects. If not, name the window
  where a retry skips work that never happened.
- The client parses the shape the signature returns: a scalar → the value; `RETURNS TABLE` or `SETOF` → an array;
  `RETURNS record` with OUT parameters → one object. A consumer that accepts "either shape" hides the bug.
- Query-builder traps: `.single()` errors on zero or several rows; `.maybeSingle()` errors on several; writes return
  no rows unless `.select()` is chained; a count needs `select(…, { count: 'exact' })`; a request returns at most the
  API's max rows, with no error, unless paged with `.range()`; every call's `error` is checked and thrown, because
  supabase-js returns errors instead of throwing.

Verify a shape claim against an existing consumer of a similar RPC, not by reasoning.

## operate lenses

**SQL / PostgREST / RPC shape.** Before handing over: does each Supabase call check `error` and throw? Can each
`.single()`/`.maybeSingle()` meet zero or several rows? Does each RPC consumer parse the shape the signature
returns? Does each mock expose every chain method the code calls? Does each column the diff names exist, with that
nullability, in the live schema?
