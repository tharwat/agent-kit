#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""
Tests for check_function_grants.py (stdlib unittest, no dependencies).

Each test builds a throwaway git repo holding a synthetic frozen baseline, a config
file with one RLS helper exemption, and one new migration. It runs the check
against that repo and asserts the exit code AND the reason in the output, so a test
only passes when the check fails for the right cause.

Run: python3 .github/scripts/test_check_function_grants.py
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "check_function_grants.py")

NEW = "20261001000000_new_feature.sql"
OLD = "20200101000000_initial.sql"
CONFIG = ".github/scripts/function_grants_config.json"
BASELINE = ".github/scripts/function_grants_baseline.txt"
HELPER = "public.get_member_role(uuid)"

LOCKED_OK = """
CREATE OR REPLACE FUNCTION public.do_thing(p_id uuid, p_note varchar DEFAULT NULL)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_catalog
AS $$ BEGIN UPDATE t SET n = p_note WHERE id = p_id; END; $$;
REVOKE EXECUTE ON FUNCTION public.do_thing(uuid, character varying) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.do_thing(uuid, character varying) TO service_role;
"""


class CheckFunctionGrantsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="fn-grants-")
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        subprocess.run(["git", "init", "-q", self.root], check=True)
        os.makedirs(os.path.join(self.root, ".github/scripts"))
        os.makedirs(os.path.join(self.root, "supabase/migrations"))
        self.write_baseline(f"# synthetic baseline\n{OLD}\n")
        self.write_config(exemptions=[HELPER])

    def write(self, rel, content, mode="w"):
        path = os.path.join(self.root, rel)
        with open(path, mode) as fh:
            fh.write(content)

    def write_baseline(self, text):
        self.write(BASELINE, text)
        self.baseline_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

    def write_config(self, exemptions=(), **overrides):
        cfg = {"migrations_dir": "supabase/migrations", "baseline_file": BASELINE,
               "baseline_sha256": self.baseline_sha, "rls_helper_exemptions": list(exemptions)}
        cfg.update(overrides)
        self.write(CONFIG, json.dumps(cfg))

    def migration(self, sql, name=NEW):
        self.write(f"supabase/migrations/{name}", sql)

    def run_check(self, *args):
        r = subprocess.run([sys.executable, SCRIPT, *args], cwd=self.root, capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def assertFails(self, *needles, args=()):
        code, out = self.run_check(*args)
        self.assertEqual(code, 1, out)
        for n in needles:
            self.assertIn(n, out)
        return out

    def assertPasses(self, args=()):
        code, out = self.run_check(*args)
        self.assertEqual(code, 0, out)
        return out

    # --- the correct pattern -------------------------------------------------
    def test_locked_secdef_function_passes(self):
        self.migration(LOCKED_OK)
        self.assertIn("1 migration(s) scanned", self.assertPasses())

    def test_split_revokes_routine_keyword_and_type_aliases_pass(self):
        self.migration("""
create function audit.f(a int4, b timestamptz, VARIADIC c text[]) returns int
  language sql security definer set search_path = public, pg_catalog as 'select 1';
revoke all on routine audit.f(integer, timestamp with time zone, text[]) from public;
revoke execute on function audit.f from anon, authenticated;
grant execute on routine audit.f(int, timestamptz, text[]) to service_role;
""")
        self.assertPasses()

    def test_invoker_function_needs_nothing(self):
        self.migration("create function public.helper() returns int language sql as 'select 1';")
        self.assertPasses()

    # --- missing or misplaced locks ---------------------------------------------
    def test_lowercase_multiline_secdef_with_public_only_revoke_fails(self):
        self.migration("""create or replace function public.x() returns void language sql
  security
  definer as $$ select 1 $$;
REVOKE EXECUTE ON FUNCTION public.x() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.x() TO service_role;
""")
        self.assertFails("public.x()", "missing REVOKE EXECUTE ... FROM anon, authenticated")

    def test_revoke_text_inside_body_or_comment_does_not_count(self):
        self.migration("""CREATE FUNCTION public.x(p uuid) RETURNS void LANGUAGE plpgsql SECURITY DEFINER
AS $fn$
BEGIN
  -- REVOKE EXECUTE ON FUNCTION public.x(uuid) FROM PUBLIC, anon, authenticated;
  PERFORM 'GRANT EXECUTE ON FUNCTION public.x(uuid) TO service_role';
END;
$fn$;
/* REVOKE EXECUTE ON FUNCTION public.x(uuid) FROM PUBLIC, anon, authenticated; */
-- GRANT EXECUTE ON FUNCTION public.x(uuid) TO service_role;
""")
        self.assertFails("missing REVOKE EXECUTE ... FROM anon, authenticated, public",
                         "missing GRANT EXECUTE ... TO service_role")

    def test_revoke_after_a_semicolon_inside_a_comment_or_string_does_not_count(self):
        self.migration("""CREATE FUNCTION public.x(p uuid) RETURNS void LANGUAGE sql SECURITY DEFINER AS $$ SELECT 1 $$;
SELECT 1; -- done; REVOKE EXECUTE ON FUNCTION public.x(uuid) FROM PUBLIC, anon, authenticated
SELECT 'note; GRANT EXECUTE ON FUNCTION public.x(uuid) TO service_role; end';
""")
        self.assertFails("missing REVOKE EXECUTE ... FROM anon, authenticated, public",
                         "missing GRANT EXECUTE ... TO service_role")

    def test_security_definer_in_comment_on_invoker_function_passes(self):
        self.migration("""-- This function is NOT SECURITY DEFINER.
CREATE FUNCTION public.y() RETURNS int LANGUAGE sql AS $$ SELECT 1 /* security definer */ $$;
""")
        self.assertPasses()

    def test_alter_function_security_definer_needs_the_lock(self):
        self.migration("ALTER FUNCTION public.y(uuid) SECURITY DEFINER;")
        self.assertFails("SECURITY DEFINER public.y(uuid)", "missing REVOKE", "missing GRANT")

    def test_unqualified_create_quoted_revoke_missing_authenticated_fails(self):
        self.migration("""create function x(p uuid) returns int language sql security definer as 'select 1';
revoke execute on function public."x"(uuid) from public, anon;
grant execute on function public."x"(uuid) to service_role;
""")
        out = self.assertFails("missing REVOKE EXECUTE ... FROM authenticated")
        self.assertNotIn("anon, authenticated", out.split("missing REVOKE EXECUTE ... FROM")[1].split("(")[0])

    def test_grant_to_anon_fails_but_keep_set_is_allowed(self):
        self.migration("GRANT EXECUTE ON FUNCTION public.anything(uuid) TO anon;")
        self.assertFails("GRANT on public.anything to anon")
        self.migration("GRANT EXECUTE ON FUNCTION public.get_member_role(uuid) TO anon, authenticated;")
        self.assertPasses()

    def test_backdated_migration_not_in_baseline_is_scanned(self):
        self.migration("create function public.z() returns int language sql security definer as 'select 1';",
                       name="20260101000000_backdated.sql")
        self.assertFails("20260101000000_backdated.sql", "SECURITY DEFINER public.z()")

    # --- other ways to re-open the door ----------------------------------------
    def test_revoking_only_the_grant_option_does_not_count(self):
        self.migration("""create function public.g(p uuid) returns int language sql security definer as 'select 1';
revoke grant option for execute on function public.g(uuid) from public, anon, authenticated;
grant execute on function public.g(uuid) to service_role;
""")
        self.assertFails("SECURITY DEFINER public.g(uuid)", "missing REVOKE EXECUTE ... FROM anon, authenticated, public")

    def test_unparseable_security_definer_statement_fails(self):
        self.migration("CREATE FUNCTION 123bad() RETURNS int LANGUAGE sql SECURITY DEFINER AS 'select 1';")
        self.assertFails("function name could not be parsed")

    def test_missing_service_role_grant_fails(self):
        self.migration(LOCKED_OK.replace(
            "GRANT EXECUTE ON FUNCTION public.do_thing(uuid, character varying) TO service_role;", ""))
        self.assertFails("missing GRANT EXECUTE ... TO service_role")

    def test_revoke_for_a_different_overload_does_not_count(self):
        self.migration("""create function public.f(a text) returns int language sql security definer as 'select 1';
revoke execute on function public.f(uuid) from public, anon, authenticated;
grant execute on function public.f(uuid) to service_role;
""")
        self.assertFails("SECURITY DEFINER public.f(text)", "missing REVOKE", "missing GRANT")

    def test_security_definer_inside_do_block_fails(self):
        self.migration("""DO $$ BEGIN
  EXECUTE 'CREATE FUNCTION public.d() RETURNS int LANGUAGE sql SECURITY DEFINER AS ''select 1''';
END $$;""")
        self.assertFails("SECURITY DEFINER inside a DO block")

    def test_security_definer_in_nested_dollar_body_inside_do_block_fails(self):
        self.migration("""DO $outer$ BEGIN
  EXECUTE $q$CREATE FUNCTION public.d() RETURNS int LANGUAGE sql SECURITY DEFINER AS 'select 1'$q$;
END $outer$;""")
        self.assertFails("SECURITY DEFINER inside a DO block")

    def test_do_block_that_only_mentions_it_in_a_comment_passes(self):
        self.migration("""DO $$ BEGIN
  -- no SECURITY DEFINER functions are created here
  PERFORM 1;
END $$;""")
        self.assertPasses()

    def test_default_privileges_grant_to_anon_fails(self):
        self.migration("ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon;")
        self.assertFails("ALTER DEFAULT PRIVILEGES grants functions to anon")

    def test_bulk_grant_on_all_functions_fails(self):
        self.migration("GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO authenticated;")
        self.assertFails("GRANT on ALL FUNCTIONS/ROUTINES IN SCHEMA to authenticated")

    def test_semicolons_and_dashes_inside_strings_and_bodies_do_not_split_statements(self):
        self.migration("""CREATE FUNCTION public.s(p text) RETURNS text AS $body$
BEGIN RETURN 'a; b -- not a comment'; END;
$body$ LANGUAGE plpgsql SECURITY DEFINER;
SELECT E'it''s; -- \\' still a string';
REVOKE EXECUTE ON FUNCTION public.s(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.s(text) TO service_role;
""")
        self.assertPasses()

    # --- bodies, dynamic SQL and bulk grants ---------------------------------------
    def test_static_grant_to_anon_inside_do_block_fails(self):
        self.migration("DO $$ BEGIN GRANT EXECUTE ON FUNCTION public.purge_account(uuid) TO anon; END $$;")
        self.assertFails("GRANT on public.purge_account to anon")

    def test_dynamic_grant_to_anon_inside_do_block_fails(self):
        self.migration("DO $$ BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.purge_account(uuid) TO anon'; END $$;")
        self.assertFails("privilege-changing SQL in a string cannot be verified")

    def test_constructed_dynamic_grant_inside_do_block_fails(self):
        self.migration("""DO $$ BEGIN
  EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO %I', 'public.f()', 'anon');
END $$;""")
        self.assertFails("privilege-changing SQL in a string cannot be verified")

    def test_default_privileges_grant_inside_do_block_fails(self):
        self.migration("DO $$ BEGIN ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon; END $$;")
        self.assertFails("ALTER DEFAULT PRIVILEGES grants functions to anon")

    def test_dynamic_grant_inside_a_function_body_fails(self):
        self.migration("""CREATE FUNCTION public.opener() RETURNS void LANGUAGE plpgsql AS $$
BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.purge_account(uuid) TO authenticated'; END $$;
SELECT public.opener();""")
        self.assertFails("privilege-changing SQL in a string cannot be verified")

    def test_dynamic_lock_loop_is_rejected_new_migrations_must_be_static(self):
        # Only a baselined migration may change privileges dynamically.
        self.migration("""DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT p.oid FROM pg_proc p LOOP
    EXECUTE format('REVOKE ALL ON ROUTINE %s FROM PUBLIC, anon, authenticated CASCADE', r.oid::regprocedure);
    EXECUTE format('GRANT EXECUTE ON ROUTINE %s TO service_role', r.oid::regprocedure);
  END LOOP;
  IF false THEN RAISE EXCEPTION 'grant on functions to anon still open'; END IF;
END $$;""")
        out = self.assertFails("privilege-changing SQL in a string cannot be verified")
        self.assertNotIn("still open", out)  # the RAISE message is never treated as SQL

    def test_group_noise_word_does_not_hide_a_grant(self):
        self.migration("GRANT EXECUTE ON FUNCTION public.f() TO GROUP anon;")
        self.assertFails("GRANT on public.f to anon")
        self.migration("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO GROUP authenticated;")
        self.assertFails("ALTER DEFAULT PRIVILEGES grants functions to authenticated")

    def test_group_noise_word_in_a_revoke_still_counts(self):
        self.migration("""create function public.q() returns int language sql security definer as 'select 1';
revoke execute on function public.q() from public, group anon, group authenticated;
grant execute on function public.q() to service_role;
""")
        self.assertPasses()

    def test_granted_by_quoted_role_and_repeated_privileges_are_parsed(self):
        self.migration('GRANT EXECUTE ON FUNCTION public.f() TO anon GRANTED BY "Some Role";')
        self.assertFails("GRANT on public.f to anon")
        self.migration("GRANT EXECUTE, EXECUTE ON FUNCTION public.f() TO authenticated;")
        self.assertFails("GRANT on public.f to authenticated")

    def test_unparseable_function_grant_fails_closed(self):
        self.migration("GRANT EXECUTE ON FUNCTION public.f() TO anon WITH SOMETHING UNEXPECTED;")
        self.assertFails("cannot parse (fail closed)")

    def test_revoke_granted_by_another_role_does_not_count(self):
        self.migration("""create function public.g(p uuid) returns int language sql security definer as 'select 1';
revoke execute on function public.g(uuid) from public, anon, authenticated granted by supabase_admin;
grant execute on function public.g(uuid) to service_role;
""")
        self.assertFails("missing REVOKE EXECUTE ... FROM anon, authenticated, public")

    def test_keep_set_exemption_is_the_exact_overload_only(self):
        self.migration("GRANT EXECUTE ON FUNCTION public.get_member_role(uuid, text) TO anon;")
        self.assertFails("GRANT on public.get_member_role to anon")
        self.migration("GRANT EXECUTE ON FUNCTION public.get_member_role TO anon;")
        self.assertFails("GRANT on public.get_member_role to anon")

    def test_updating_a_column_named_role_in_a_body_is_not_role_switching(self):
        self.migration("""CREATE FUNCTION public.promote(p uuid) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  UPDATE memberships SET role = 'admin' WHERE id = p;
  IF FOUND THEN UPDATE memberships SET role = 'admin' WHERE id = p; END IF;
END $$;""")
        self.assertPasses()

    def test_grant_after_if_then_inside_a_body_fails(self):
        self.migration("DO $$ BEGIN IF true THEN GRANT EXECUTE ON FUNCTION public.f() TO anon; END IF; END $$;")
        self.assertFails("GRANT on public.f to anon")

    def test_owner_role_membership_and_role_switching_fail(self):
        self.migration("ALTER FUNCTION public.f(uuid) OWNER TO anon;")
        self.assertFails("OWNER TO anon")
        self.migration("GRANT service_role TO authenticated;")
        self.assertFails("role membership granted to authenticated")
        self.migration("SET ROLE supabase_admin;\nCREATE FUNCTION public.h() RETURNS int LANGUAGE sql AS 'select 1';")
        self.assertFails("role switching is not allowed")

    # --- control flow inside bodies, format() and false positives -----------------
    def test_grant_after_foreach_loop_inside_a_body_fails(self):
        self.migration("""DO $$ DECLARE r text; BEGIN
  FOREACH r IN ARRAY ARRAY['a'] LOOP GRANT EXECUTE ON FUNCTION public.f() TO anon; END LOOP;
END $$;""")
        self.assertFails("GRANT on public.f to anon")

    def test_default_privileges_after_foreach_loop_fails(self):
        self.migration("""DO $$ DECLARE r text; BEGIN
  FOREACH r IN ARRAY ARRAY['a'] LOOP ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon; END LOOP;
END $$;""")
        self.assertFails("ALTER DEFAULT PRIVILEGES grants functions to anon")

    def test_grant_inside_case_when_fails(self):
        self.migration("DO $$ BEGIN CASE 1 WHEN 1 THEN GRANT EXECUTE ON FUNCTION public.f() TO anon; END CASE; END $$;")
        self.assertFails("GRANT on public.f to anon")

    def test_concatenated_dynamic_grant_fails(self):
        self.migration("DO $$ BEGIN EXECUTE 'GR' || 'ANT EXECUTE ON FUNCTION public.f() TO anon'; END $$;")
        self.assertFails("EXECUTE of SQL that is not a single literal")

    def test_execute_of_a_variable_fails_closed(self):
        self.migration("""DO $$ DECLARE v text := 'SELECT 1'; BEGIN EXECUTE v; END $$;""")
        self.assertFails("EXECUTE of SQL that is not a single literal")

    def test_format_with_concatenated_arguments_fails(self):
        self.migration("DO $$ BEGIN EXECUTE format('SELECT %s', 'GRANT EXECUTE ON FUNCTION public.f() TO an' || 'on'); END $$;")
        self.assertFails("EXECUTE of SQL that is not a single literal", "privilege-changing SQL in a string")

    def test_format_template_that_is_only_a_placeholder_fails(self):
        self.migration("DO $$ DECLARE v text := 'SELECT 1'; BEGIN EXECUTE format('%s', v); END $$;")
        self.assertFails("EXECUTE of SQL that is not a single literal")

    def test_value_injected_into_the_safe_grant_template_fails(self):
        self.migration("""DO $$ BEGIN
  EXECUTE format('GRANT EXECUTE ON ROUTINE %s TO service_role', 'public.f() TO anon; SELECT --');
END $$;""")
        self.assertFails("privilege-changing SQL in a string cannot be verified")

    def test_bodies_nested_too_deep_fail_closed(self):
        self.migration("""DO $a$ BEGIN EXECUTE $b$ DO $c$ BEGIN EXECUTE $d$ DO $e$ BEGIN
  GRANT EXECUTE ON FUNCTION public.f() TO anon; END $e$ $d$; END $c$ $b$; END $a$;""")
        self.assertFails("nested too deep to verify")

    def test_create_schema_grant_element_fails(self):
        self.migration("CREATE SCHEMA x GRANT EXECUTE ON FUNCTION public.f() TO anon;")
        self.assertFails("GRANT on public.f to anon")

    def test_reassign_owned_to_anon_fails(self):
        self.migration("REASSIGN OWNED BY postgres TO anon;")
        self.assertFails("REASSIGN OWNED ... TO anon")

    def test_grant_inside_a_sql_language_string_body_fails(self):
        self.migration("""CREATE FUNCTION public.opener() RETURNS void LANGUAGE sql
  AS 'GRANT EXECUTE ON FUNCTION public.purge_account(uuid) TO anon';
SELECT public.opener();""")
        self.assertFails("GRANT on public.purge_account to anon")

    def test_typmods_do_not_break_type_matching(self):
        self.migration("""create function public.h(numeric(10, 2), timestamp(3) with time zone) returns int
  language sql security definer as 'select 1';
revoke execute on function public.h(numeric, timestamptz) from public, anon, authenticated;
grant execute on function public.h(numeric, timestamptz) to service_role;
""")
        self.assertPasses()

    def test_the_word_grant_as_data_in_a_body_is_not_dynamic_sql(self):
        self.migration("""CREATE FUNCTION public.label() RETURNS text LANGUAGE plpgsql AS $$
BEGIN RETURN 'Monthly credit grant'; END $$;""")
        self.assertPasses()

    # --- role membership, role switching and service_role availability -------------
    def test_role_membership_via_alter_group_and_create_role_fails(self):
        self.migration("ALTER GROUP rpc_open ADD USER authenticated;")
        self.assertFails("ALTER GROUP ... ADD USER authenticated")
        self.migration("CREATE ROLE rpc_open NOLOGIN ROLE anon;")
        self.assertFails("new role gets anon as a member")
        self.migration("CREATE ROLE rpc_reader NOLOGIN IN ROLE anon;")
        self.assertPasses()  # IN ROLE makes the NEW role a member of anon; anon itself gains nothing

    def test_set_config_role_switch_fails(self):
        self.migration("SELECT set_config('role', 'anon', true);")
        self.assertFails("set_config('role', ...) switches role")
        self.migration("DO $$ BEGIN PERFORM set_config('role', 'anon', true); END $$;")
        self.assertFails("set_config('role', ...) switches role")

    def test_revoking_service_role_after_the_grant_fails(self):
        self.migration(LOCKED_OK + "REVOKE EXECUTE ON FUNCTION public.do_thing(uuid, character varying) FROM service_role;\n")
        self.assertFails("missing GRANT EXECUTE ... TO service_role", "never granted back")

    def test_revoke_and_regrant_of_service_role_passes(self):
        self.migration("""create function public.q() returns int language sql security definer as 'select 1';
revoke all on function public.q() from public, anon, authenticated, service_role;
grant execute on function public.q() to service_role;
""")
        self.assertPasses()

    def test_locks_written_before_a_re_create_do_not_count(self):
        self.migration("""revoke execute on function public.r() from public, anon, authenticated;
grant execute on function public.r() to service_role;
drop function public.r();
create function public.r() returns int language sql security definer as 'select 1';
""")
        self.assertFails("SECURITY DEFINER public.r()", "after it is created")

    def test_keep_set_helper_needs_grants_not_revokes(self):
        self.migration("""create or replace function public.get_member_role(p uuid) returns text
  language sql security definer set search_path = public, pg_catalog as 'select null::text';
""")
        out = self.assertFails("exempt RLS helper", "do NOT revoke it")
        self.assertNotIn("missing REVOKE", out)
        self.migration("""create or replace function public.get_member_role(p uuid) returns text
  language sql security definer set search_path = public, pg_catalog as 'select null::text';
grant execute on function public.get_member_role(uuid) to anon, authenticated, service_role;
""")
        self.assertPasses()

    def test_injection_through_a_raw_placeholder_or_quoted_role_fails(self):
        self.migration("""DO $$ DECLARE v text := 'x'; BEGIN
  EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', v);
END $$;""")
        self.assertFails("privilege-changing SQL in a string", "EXECUTE of SQL that is not a single literal")
        self.migration("""DO $$ BEGIN EXECUTE format('REVOKE %s', 'ALL ON FUNCTION f() FROM x; GRANT ALL ON FUNCTION f() TO "anon"'); END $$;""")
        self.assertFails("privilege-changing SQL in a string")

    def test_quoting_placeholders_in_a_non_privilege_template_pass(self):
        self.migration("""DO $$ BEGIN EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS note text DEFAULT %L', 'visits', 'n/a'); END $$;""")
        self.assertPasses()

    def test_raw_placeholder_fed_by_catalog_formatter_or_reg_cast_passes(self):
        # dynamic ALTER FUNCTION ... SET search_path over catalog-derived args
        self.migration("DO $$ DECLARE func_oid oid; BEGIN\n"
                       "  EXECUTE format('ALTER FUNCTION public.f(%s) SET search_path = ''public''', "
                       "pg_get_function_arguments(func_oid));\n"
                       "  EXECUTE format('ALTER FUNCTION %s SET search_path = public, pg_catalog', func_oid::regprocedure);\n"
                       "END $$;")
        self.assertPasses()

    def test_raw_placeholder_fed_by_a_variable_or_semicolon_literal_fails(self):
        self.migration("DO $$ DECLARE v text := 'f()'; BEGIN\n"
                       "  EXECUTE format('ALTER FUNCTION %s SET search_path = public', v);\nEND $$;")
        self.assertFails("EXECUTE of SQL that is not a single literal")
        self.migration("DO $$ BEGIN\n"
                       "  EXECUTE format('ALTER FUNCTION %s SET search_path = public', 'f(); SELECT 1');\nEND $$;")
        self.assertFails("EXECUTE of SQL that is not a single literal")

    def test_concatenation_hidden_behind_a_catalog_looking_argument_fails(self):
        self.migration("DO $$ DECLARE a text; v text; BEGIN\n"
                       "  EXECUTE format('ALTER FUNCTION %s SET search_path = public', quote_ident(a) || lower(v));\nEND $$;")
        self.assertFails("EXECUTE of SQL that is not a single literal")
        self.migration("DO $$ DECLARE v text; x oid; BEGIN\n"
                       "  EXECUTE format('ALTER FUNCTION %s SET search_path = public', v || x::regprocedure);\nEND $$;")
        self.assertFails("EXECUTE of SQL that is not a single literal")

    def test_only_the_final_definition_of_a_function_counts(self):
        # SECURITY DEFINER first, then replaced by an ordinary function: nothing to lock
        self.migration("""create function public.t() returns int language sql security definer as 'select 1';
create or replace function public.t() returns int language sql as 'select 2';
""")
        self.assertPasses()
        # locked, then re-created as SECURITY DEFINER with no new lock after it
        self.migration("""create function public.t() returns int language sql security definer as 'select 1';
revoke execute on function public.t() from public, anon, authenticated;
grant execute on function public.t() to service_role;
create or replace function public.t() returns int language sql security definer as 'select 2';
""")
        # Postgres would keep the ACL across CREATE OR REPLACE, but the check cannot see a DROP in
        # between, so it is deliberately conservative: the lock must follow the LAST CREATE.
        self.assertFails("SECURITY DEFINER public.t()", "after it is created")
        self.migration("""create function public.t() returns int language sql security definer as 'select 1';
revoke execute on function public.t() from public, anon, authenticated;
grant execute on function public.t() to service_role;
drop function public.t();
create function public.t() returns int language sql security definer as 'select 2';
""")
        self.assertFails("SECURITY DEFINER public.t()", "after it is created")

    def test_alter_to_security_definer_keeps_grants_made_after_the_create(self):
        self.migration("""create function public.u(p uuid) returns int language sql as 'select 1';
revoke execute on function public.u(uuid) from public, anon, authenticated;
grant execute on function public.u(uuid) to service_role;
alter function public.u(uuid) security definer;
""")
        self.assertPasses()

    def test_data_strings_mentioning_public_or_grant_pass(self):
        self.migration("""CREATE FUNCTION public.note_it() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN INSERT INTO notes(msg) VALUES ('Moved to public listing'), ('Monthly credit grant'); RETURN NEW; END $$;""")
        self.assertPasses()

    def test_privilege_sql_passed_to_a_helper_function_fails(self):
        self.migration("SELECT run_sql('GRANT EXECUTE ON FUNCTION public.purge_account(uuid) TO anon');")
        self.assertFails("privilege-changing SQL in a string cannot be verified")

    def test_bulk_or_default_revoke_from_service_role_fails(self):
        self.migration("REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM service_role;")
        self.assertFails("REVOKE on ALL FUNCTIONS IN SCHEMA from service_role")
        self.migration("ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM service_role;")
        self.assertFails("ALTER DEFAULT PRIVILEGES revokes functions from service_role")

    def test_escalating_the_api_roles_themselves_fails(self):
        self.migration("ALTER ROLE anon BYPASSRLS;")
        self.assertFails("ALTER ROLE anon with a privilege or role-switch attribute")
        self.migration("ALTER ROLE authenticated SET role = 'service_role';")
        self.assertFails("ALTER ROLE authenticated with a privilege or role-switch attribute")
        self.migration("ALTER ROLE anon SET statement_timeout = '3s';")
        self.assertPasses()  # Supabase tunes timeouts on the API roles; that is not a privilege

    def test_direct_catalog_writes_fail(self):
        self.migration("UPDATE pg_catalog.pg_proc SET proacl = NULL WHERE proname = 'purge_account';")
        self.assertFails("direct write to a privilege catalog")
        self.migration("DO $$ BEGIN UPDATE pg_proc SET proacl = NULL; END $$;")
        self.assertFails("direct write to a privilege catalog")

    # --- quoting, escapes and laundering -------------------------------------------
    def test_quoted_grantee_in_a_role_membership_grant_fails(self):
        self.migration('GRANT postgres TO "anon";')
        self.assertFails("role membership granted to anon")
        self.migration('GRANT "service_role" TO "authenticated";')
        self.assertFails("role membership granted to authenticated")

    def test_unparseable_role_grant_fails_closed(self):
        self.migration("GRANT service_role TO anon WITH SOMETHING ODD;")
        self.assertFails("role membership granted to anon")
        self.migration("GRANT service_role TO (anon);")
        self.assertFails("role GRANT that this check cannot parse")

    def test_keyword_split_across_template_and_argument_fails(self):
        self.migration("DO $$ BEGIN EXECUTE format('%s EXECUTE ON FUNCTION public.f() TO anon', 'GRANT'); END $$;")
        self.assertFails("EXECUTE of SQL that is not a single literal")
        self.migration("DO $$ BEGIN EXECUTE format('GR%sNT EXECUTE ON FUNCTION public.f() TO anon', 'A'); END $$;")
        self.assertFails("EXECUTE of SQL that is not a single literal")
        self.migration("DO $$ BEGIN EXECUTE format('%s service_role %s authenticated', 'GRANT', 'TO'); END $$;")
        self.assertFails("EXECUTE of SQL that is not a single literal")

    def test_escape_string_literal_in_execute_fails(self):
        self.migration("DO $$ BEGIN EXECUTE E'GR\\\\x41NT EXECUTE ON FUNCTION public.f() TO anon'; END $$;")
        self.assertFails("EXECUTE of SQL that is not a single literal")

    def test_execute_text_naming_anon_as_grantee_fails(self):
        self.migration("DO $$ BEGIN EXECUTE 'ALTER DEFAULT PRIVILEGES GRANT SELECT ON TABLES TO \"anon\"'; END $$;")
        self.assertFails("EXECUTE text names PUBLIC/anon/authenticated as a grantee")

    def test_raise_exemption_only_covers_the_raise_message(self):
        self.migration("DO $$ BEGIN IF (SELECT raise FROM cfg) THEN "
                       "EXECUTE 'GRANT EXECUTE ON FUNCTION public.f() TO anon'; END IF; END $$;")
        self.assertFails("privilege-changing SQL in a string cannot be verified")
        self.migration("SELECT raise, dblink_exec('GRANT EXECUTE ON FUNCTION public.f() TO anon') FROM t;")
        self.assertFails("privilege-changing SQL in a string cannot be verified")

    def test_computed_set_config_name_fails(self):
        self.migration("SELECT set_config(format('%s', 'role'), 'service_role', true);")
        self.assertFails("set_config() with a computed setting name")
        self.migration("SELECT set_config('search_path', 'public', true);")
        self.assertPasses()

    def test_update_only_pg_proc_fails(self):
        self.migration("UPDATE ONLY pg_catalog.pg_proc SET proacl = NULL;")
        self.assertFails("direct write to a privilege catalog")

    def test_keep_set_helper_recreated_without_grants_fails_even_as_invoker(self):
        self.migration("""CREATE OR REPLACE FUNCTION public.get_member_role(p uuid) RETURNS text
  LANGUAGE sql STABLE AS $$ SELECT NULL::text $$;""")
        self.assertFails("exempt RLS helper")

    def test_drop_cascade_rename_and_extension_laundering_fail(self):
        self.migration("DROP FUNCTION public.get_member_role(uuid) CASCADE;")
        self.assertFails("silently drops the RLS policies")
        self.migration("ALTER FUNCTION public.get_member_role(uuid) RENAME TO wipe_all;")
        self.assertFails("renaming or moving the exempt RLS helper")
        self.migration("ALTER EXTENSION vector ADD FUNCTION public.f(uuid);")
        self.assertFails("ALTER EXTENSION ... ADD FUNCTION")

    def test_function_that_sets_role_fails(self):
        self.migration("CREATE FUNCTION public.f() RETURNS int LANGUAGE sql SET role = 'service_role' AS 'select 1';")
        self.assertFails("a function that sets `role`")

    def test_dynamic_role_membership_grant_to_anon_in_a_string_fails(self):
        self.migration("SELECT run_sql('GRANT service_role TO anon');")
        self.assertFails("privilege-changing SQL in a string cannot be verified")

    def test_comments_inside_a_dynamic_string_do_not_hide_it(self):
        self.migration("SELECT run_sql('GRANT /* c */ service_role /* c */ TO /* c */ \"anon\"');")
        self.assertFails("privilege-changing SQL in a string cannot be verified")
        self.migration("DO $$ BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION f() -- x\n TO anon'; END $$;")
        self.assertFails("privilege-changing SQL in a string cannot be verified")

    def test_dollar_quoted_execute_and_do_inside_execute_fail(self):
        self.migration("DO $$ BEGIN EXECUTE $q$GRANT EXECUTE ON FUNCTION public.f() TO anon$q$; END $$;")
        self.assertFails("GRANT on public.f to anon")
        self.migration("DO $$ BEGIN EXECUTE 'DO $i$ BEGIN GRANT EXECUTE ON FUNCTION public.f() TO anon; END $i$'; END $$;")
        self.assertFails("privilege-changing SQL in a string cannot be verified")

    def test_prose_mentioning_grant_to_is_not_sql(self):
        self.migration("""CREATE FUNCTION public.notify_pending() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN INSERT INTO notes(msg) VALUES ('A grant to an operator is pending'), ('Revoke access from old devices'),
  ('Grant access to your team');
RETURN NEW; END $$;""")
        self.assertPasses()

    # --- tables, views and sequences are service_role only -----------------------
    TABLE_RULE = "tables, views and sequences are service_role only"
    TABLE_ADP_RULE = "re-opens every future table or sequence"
    TABLE_SR_RULE = "is never fully granted back to service_role"

    def test_table_grant_to_anon_fails_with_or_without_the_table_keyword(self):
        self.migration("GRANT SELECT ON public.foo TO anon;")
        self.assertFails(self.TABLE_RULE)
        self.migration("GRANT SELECT ON TABLE public.foo TO anon;")
        self.assertFails(self.TABLE_RULE)

    def test_table_grant_with_several_objects_and_a_mixed_role_list_fails(self):
        self.migration("GRANT SELECT, INSERT ON TABLE public.a, public.b TO service_role, authenticated;")
        self.assertFails(self.TABLE_RULE, "authenticated")

    def test_bulk_grant_on_all_tables_or_sequences_fails(self):
        self.migration("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO anon;")
        self.assertFails(self.TABLE_RULE)
        self.migration("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO authenticated;")
        self.assertFails(self.TABLE_RULE)

    def test_sequence_grant_role_spellings_all_fail(self):
        for grantee in ('"authenticated"', "GROUP anon", "Anon", "PUBLIC"):
            with self.subTest(grantee=grantee):
                self.migration(f"GRANT USAGE ON SEQUENCE public.s TO {grantee};")
                self.assertFails(self.TABLE_RULE)

    def test_every_table_privilege_keyword_fails(self):
        for priv in ("MAINTAIN", "REFERENCES", "TRIGGER", "TRUNCATE"):
            with self.subTest(priv=priv):
                self.migration(f"GRANT {priv} ON public.t TO anon;")
                self.assertFails(self.TABLE_RULE)

    def test_column_list_grant_fails(self):
        self.migration("GRANT SELECT (id, email), UPDATE (push_token) ON public.users TO authenticated;")
        self.assertFails(self.TABLE_RULE)

    def test_multiline_grant_with_grant_option_fails(self):
        self.migration("GRANT SELECT\n  ON public.t\n  TO\n  anon\n  WITH GRANT OPTION;")
        self.assertFails(self.TABLE_RULE)

    def test_table_grant_inside_a_do_block_fails(self):
        self.migration("DO $$ BEGIN IF NOT EXISTS (SELECT 1) THEN GRANT SELECT ON public.t TO anon; END IF; END $$;")
        self.assertFails(self.TABLE_RULE)

    def test_table_grant_fails_even_if_revoked_later_in_the_file(self):
        self.migration("GRANT SELECT ON public.t TO anon;\nREVOKE SELECT ON public.t FROM anon;")
        self.assertFails(self.TABLE_RULE)

    def test_table_grant_in_another_schema_fails(self):
        self.migration("GRANT SELECT ON TABLE storage.objects TO authenticated;")
        self.assertFails(self.TABLE_RULE)

    def test_default_privileges_grant_on_tables_or_sequences_fails(self):
        for sql in ("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO anon;",
                    "ALTER DEFAULT PRIVILEGES FOR USER postgres GRANT USAGE ON SEQUENCES TO authenticated;",
                    "ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON TABLES TO PUBLIC;"):
            with self.subTest(sql=sql):
                self.migration(sql)
                self.assertFails(self.TABLE_ADP_RULE)

    def test_revoking_tables_from_service_role_without_a_full_grant_back_fails(self):
        self.migration("REVOKE ALL ON TABLE public.t FROM anon, authenticated, service_role;")
        self.assertFails(self.TABLE_SR_RULE)
        self.migration("REVOKE ALL ON public.t FROM service_role;\nGRANT SELECT ON public.t TO service_role;")
        self.assertFails(self.TABLE_SR_RULE)
        self.migration("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM service_role;")
        self.assertFails(self.TABLE_SR_RULE)

    def test_bulk_grant_back_must_match_the_kind_that_was_revoked(self):
        self.migration("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM service_role;\n"
                       "GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;")
        self.assertFails(self.TABLE_SR_RULE)
        # (a bare `ON public.t` revoke is not covered by ALL TABLES alone: see
        # test_a_bare_or_table_keyword_revoke_needs_a_named_or_complete_bulk_grant_back)
        self.migration("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM service_role;\n"
                       "GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;\n"
                       "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM service_role;\n"
                       "GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;")
        self.assertPasses()

    def test_grant_back_respects_an_explicit_table_or_sequence_keyword(self):
        # ALL TABLES never covers a sequence, ALL SEQUENCES never a table
        for sql in ("REVOKE ALL ON SEQUENCE public.s FROM service_role;\n"
                    "GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;",
                    "REVOKE ALL ON TABLE public.t FROM service_role;\n"
                    "GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;",
                    "REVOKE ALL ON public.t FROM service_role;\n"
                    "GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;"):
            with self.subTest(sql=sql):
                self.migration(sql)
                self.assertFails(self.TABLE_SR_RULE)
        for sql in ("REVOKE ALL ON SEQUENCE public.s FROM service_role;\n"
                    "GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;",
                    "REVOKE ALL ON SEQUENCE public.s FROM service_role;\nGRANT ALL ON SEQUENCE public.s TO service_role;",
                    "REVOKE ALL ON public.t FROM service_role;\nGRANT ALL ON TABLE public.t TO service_role;",
                    # same name, different keyword: a sequence revoked as `ON name` and granted back by name
                    "REVOKE ALL ON public.s FROM service_role;\nGRANT ALL ON SEQUENCE public.s TO service_role;"):
            with self.subTest(sql=sql):
                self.migration(sql)
                self.assertPasses()

    def test_a_bare_or_table_keyword_revoke_needs_a_named_or_complete_bulk_grant_back(self):
        # `ON name` / `ON TABLE name` may be a sequence, which ALL TABLES does not cover
        for sql in ("REVOKE ALL ON qq FROM service_role;\nGRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;",
                    "REVOKE ALL ON TABLE public.qq FROM service_role;\n"
                    "GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;"):
            with self.subTest(sql=sql):
                self.migration(sql)
                self.assertFails(self.TABLE_SR_RULE)
        self.migration("REVOKE ALL ON qq FROM service_role;\n"
                       "GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;\n"
                       "GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;")
        self.assertPasses()

    def test_a_table_named_like_an_object_keyword_is_still_a_table(self):
        # the keyword only means another object type when a name follows it
        for name in ("language", "type", "domain", "parameter", "tablespace", "schema"):
            with self.subTest(name=name):
                self.migration(f"GRANT SELECT ON {name} TO anon;")
                self.assertFails(self.TABLE_RULE)
        self.migration("GRANT USAGE ON LANGUAGE plpgsql TO anon;\nGRANT SET ON PARAMETER work_mem TO anon;\n"
                       "GRANT USAGE ON DOMAIN public.d TO authenticated;")
        self.assertPasses()

    def test_revoking_only_the_grant_option_or_another_grantors_grant_from_service_role_passes(self):
        # neither removes postgres's grant to service_role, so no grant-back is needed
        self.migration("REVOKE GRANT OPTION FOR ALL ON public.t FROM service_role;\n"
                       "REVOKE ALL ON public.t FROM service_role GRANTED BY supabase_admin;")
        self.assertPasses()

    def test_default_privileges_revoke_on_tables_from_service_role_fails(self):
        self.migration("ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON TABLES FROM service_role;")
        self.assertFails("revokes tables/sequences from service_role")

    def test_default_privileges_revoke_grant_option_is_read_as_a_revoke(self):
        # "GRANT OPTION FOR" contains the word grant; it is still a REVOKE and leaves the privilege.
        self.migration("ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
                       "REVOKE GRANT OPTION FOR ALL ON TABLES FROM service_role;")
        self.assertPasses()

    def test_owner_to_an_api_role_on_a_relation_fails(self):
        for sql in ("ALTER TABLE public.t OWNER TO authenticated;", "ALTER SEQUENCE public.s OWNER TO anon;",
                    "ALTER VIEW public.v OWNER TO anon;", "ALTER MATERIALIZED VIEW public.m OWNER TO \"anon\";"):
            with self.subTest(sql=sql):
                self.migration(sql)
                self.assertFails("the owner holds every privilege")

    def test_owner_to_an_api_role_inside_a_do_block_fails(self):
        self.migration("DO $$ BEGIN ALTER TABLE public.t OWNER TO anon; END $$;")
        self.assertFails("the owner holds every privilege")

    def test_lock_down_statements_pass(self):
        self.migration("""
CREATE TABLE public.t (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY);
ALTER TABLE public.t ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.t OWNER TO postgres;
REVOKE ALL ON public.t FROM service_role;
GRANT ALL ON public.t TO service_role;
GRANT ALL ON TABLE public.t TO service_role;
REVOKE ALL ON public.t FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES TO service_role;
DROP POLICY IF EXISTS "Public can validate reset tokens" ON public.password_reset_tokens;
""")
        self.assertPasses()

    def test_non_relation_grants_policies_and_the_keep_set_pass(self):
        self.migration("""
GRANT USAGE ON SCHEMA public TO anon;
GRANT USAGE ON TYPE public.my_enum TO authenticated;
GRANT anon TO authenticator;
CREATE POLICY p ON public.t FOR SELECT TO anon USING (false);
GRANT EXECUTE ON FUNCTION public.get_member_role(uuid) TO anon, authenticated, service_role;
""")
        self.assertPasses()

    def test_table_grant_text_in_comments_and_raise_messages_passes(self):
        self.migration("""-- GRANT SELECT ON t TO anon
/* GRANT SELECT ON t TO anon */
DO $$ BEGIN RAISE EXCEPTION 'still granted to anon on %', 1; END $$;""")
        self.assertPasses()

    def test_table_grant_text_in_a_comment_on_string_fails_as_before(self):
        # Rule 6 (no privilege-changing SQL in any string) covers table grants too: documented, not changed.
        self.migration("COMMENT ON TABLE public.t IS 'do not GRANT SELECT ON t TO anon';")
        self.assertFails("privilege-changing SQL in a string cannot be verified")

    # --- baseline, config and modes ---------------------------------------------
    def test_baseline_listed_file_is_exempt(self):
        self.migration("create function public.old() returns int language sql security definer as 'select 1';",
                       name=OLD)
        self.assertIn("0 migration(s) scanned", self.assertPasses())

    def test_editing_the_baseline_fails(self):
        self.write(BASELINE, NEW + "\n", mode="a")
        self.migration("create function public.z() returns int language sql security definer as 'select 1';")
        self.assertFails("function_grants_baseline.txt changed", "baseline is frozen")

    def test_unreadable_migration_fails(self):
        self.write(f"supabase/migrations/{NEW}", b"\xff\xfe select 1;", mode="wb")
        self.assertFails("cannot read as UTF-8")

    def test_no_exemptions_means_no_helper_may_be_opened(self):
        self.write_config(exemptions=[])
        self.migration(f"GRANT EXECUTE ON FUNCTION {HELPER} TO anon, authenticated;")
        self.assertFails("GRANT on public.get_member_role to anon, authenticated")

    def test_missing_config_fails_closed(self):
        os.rename(os.path.join(self.root, CONFIG), os.path.join(self.root, CONFIG + ".pre-agent-kit"))
        self.migration(LOCKED_OK)
        self.assertFails("function_grants_config.json not found", "make_function_grants_baseline.py")

    def test_exemption_without_an_argument_list_is_rejected(self):
        self.write_config(exemptions=["public.get_member_role"])
        self.migration(LOCKED_OK)
        self.assertFails("must be schema.name(argument types)")

    def test_unparseable_config_fails_closed(self):
        self.write(CONFIG, "{not json")
        self.migration(LOCKED_OK)
        self.assertFails("cannot read")

    def test_missing_migrations_dir_fails_closed(self):
        self.write_config(exemptions=[HELPER], migrations_dir="db/migrations")
        self.assertFails("cannot list db/migrations")

    def test_custom_migrations_dir_is_scanned(self):
        os.makedirs(os.path.join(self.root, "db/migrations"))
        self.write_config(exemptions=[HELPER], migrations_dir="db/migrations")
        self.write(f"db/migrations/{NEW}", "create function public.z() returns int language sql security definer as 'select 1';")
        self.assertFails(f"db/migrations/{NEW}", "SECURITY DEFINER public.z()")

    def test_file_mode_checks_one_file_without_a_baseline(self):
        os.rename(os.path.join(self.root, CONFIG), os.path.join(self.root, CONFIG + ".pre-agent-kit"))
        self.write("draft.sql", "create function public.z() returns int language sql security definer as 'select 1';")
        self.assertFails("draft.sql", "SECURITY DEFINER public.z()", args=("--file", "draft.sql"))
        self.write("draft.sql", LOCKED_OK)
        self.assertIn("1 file(s) checked", self.assertPasses(args=("--file", "draft.sql")))

    def test_drop_cascade_of_a_function_that_is_not_exempt_passes(self):
        self.migration("DROP FUNCTION IF EXISTS public.old_report(uuid) CASCADE;")
        self.assertPasses()

    def test_every_listed_exemption_is_honoured_exactly(self):
        self.write_config(exemptions=[HELPER, "app.is_member(uuid, text)"])
        self.migration("GRANT EXECUTE ON FUNCTION app.is_member(uuid, text) TO authenticated;")
        self.assertPasses()
        self.migration("GRANT EXECUTE ON FUNCTION app.is_member(uuid) TO authenticated;")
        self.assertFails("GRANT on app.is_member to authenticated")
        self.migration("DROP FUNCTION app.is_member(uuid, text) CASCADE;")
        self.assertFails("exempt RLS helper app.is_member")

    def test_file_mode_still_reads_exemptions_when_config_exists(self):
        self.write("draft.sql", f"GRANT EXECUTE ON FUNCTION {HELPER} TO anon, authenticated, service_role;")
        self.assertPasses(args=("--file", "draft.sql"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
