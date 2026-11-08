#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""
Keep database functions, tables, views and sequences off the public API (Supabase).

Every function in an exposed schema is reachable through PostgREST
(POST /rest/v1/rpc/<fn>) by any role that holds EXECUTE on it, and the anon key is
public by design. A SECURITY DEFINER function runs as its owner (postgres, which
bypasses RLS), so one that `anon` or `authenticated` can execute is an open door.
This check stops a NEW migration from opening it.

Scanned: every <migrations_dir>/*.sql file that is NOT in the frozen baseline list.
The baseline lists the migrations that existed when the check was installed (made
once by make_function_grants_baseline.py). It is a list of filenames, not a
timestamp cutoff, so a back-dated migration added later is still scanned. The
list is pinned by `baseline_sha256` in the config file: editing it without editing
the config fails the check, so an added exemption is always visible in review.

Config: .github/scripts/function_grants_config.json (or --config PATH):
  {
    "migrations_dir": "supabase/migrations",
    "baseline_file": ".github/scripts/function_grants_baseline.txt",
    "baseline_sha256": "<64-hex sha256 of the baseline file's bytes>",
    "rls_helper_exemptions": ["public.my_rls_helper(uuid)"]
  }
`rls_helper_exemptions` lists RLS helper functions that policies call as the
requesting role, by exact identity (schema, name, argument types). Each must stay
executable by anon, authenticated and service_role. Default: none. Adding one is an
Owner-Kept Gate (G6, and G7 for the check itself).

Fails (exit 1) when a scanned migration:
  1. creates a SECURITY DEFINER function/procedure (CREATE ... SECURITY DEFINER, or
     ALTER FUNCTION/PROCEDURE/ROUTINE ... SECURITY DEFINER) and then does not, in
     statements AFTER that (last) CREATE, both
       - REVOKE EXECUTE|ALL ON FUNCTION|PROCEDURE|ROUTINE <it> FROM PUBLIC, anon,
         authenticated   (all three roles; may be split over several REVOKEs.
         REVOKE GRANT OPTION FOR ... does not count: it leaves EXECUTE. Neither
         does REVOKE ... GRANTED BY <another role>, which leaves postgres's grants), and
       - GRANT EXECUTE|ALL ON FUNCTION|PROCEDURE|ROUTINE <it> TO service_role, with no
         later REVOKE from service_role.
     An exempt RLS helper is the exception: it must instead be granted to anon,
     authenticated and service_role;
  2. grants EXECUTE/ALL on a function/procedure/routine (or ALL FUNCTIONS/ROUTINES
     IN SCHEMA) to PUBLIC, anon or authenticated (the optional GROUP noise word
     included), except an exempt RLS helper, exact overload only;
  3. uses ALTER DEFAULT PRIVILEGES to GRANT on FUNCTIONS/ROUTINES to PUBLIC, anon or
     authenticated, or to REVOKE them from service_role; REVOKEs EXECUTE from
     service_role on ALL FUNCTIONS IN SCHEMA, or on a routine it never grants back;
  4. makes anon/authenticated/PUBLIC a function OWNER (OWNER TO / REASSIGN OWNED) or a
     member of another role (GRANT <role> TO, ALTER GROUP ... ADD USER, CREATE ROLE
     ... ROLE); has a CREATE SCHEMA ... GRANT element that opens a function; or
     switches role (SET ROLE / SET SESSION AUTHORIZATION / set_config('role', ...));
     gives anon/authenticated a privilege or role-switch attribute (ALTER ROLE ...
     BYPASSRLS / SUPERUSER / SET role ...); or writes a privilege catalog directly
     (UPDATE pg_proc / pg_default_acl / pg_auth_members); or renames, moves or
     DROP ... CASCADEs an exempt RLS helper;
  5. has a GRANT or ALTER DEFAULT PRIVILEGES statement on functions that it cannot
     parse (fail closed);
  6. puts privilege-changing SQL (GRANT ... ON/TO, REVOKE ... FROM, DEFAULT PRIVILEGES,
     OWNER TO, SET ROLE, SECURITY DEFINER, role membership) in ANY string literal
     (EXECUTE argument, format() template, helper-function argument) outside a
     RAISE/ASSERT message. Migrations change privileges only with plain statements;
  7. inside any body (DO block, plpgsql body, or SQL-language body written as a
     string; nested more than 3 deep fails closed): mentions SECURITY DEFINER, runs
     any of the above as a static statement (found wherever it sits: after BEGIN,
     THEN, LOOP, FOREACH, CASE ...), or EXECUTEs anything but a single literal or
     format() of a literal template whose placeholders are %I / %L, or %s fed by a
     reg* cast, a catalog formatter (pg_get_function_arguments, quote_ident, ...) or
     a literal without ';' (no concatenation, no variable);
  8. cannot be read as UTF-8, or the baseline list does not match baseline_sha256;
  9. GRANTs a table, view, materialized view, foreign table or sequence (by name,
     bare `ON name`, or ALL TABLES/SEQUENCES IN SCHEMA, in any schema, at top level
     or inside a body) to PUBLIC, anon or authenticated (flagged even if a later
     statement revokes it), or makes one of them a relation OWNER;
 10. uses ALTER DEFAULT PRIVILEGES to GRANT on TABLES/SEQUENCES to PUBLIC, anon or
     authenticated, or to REVOKE them from service_role (a REVOKE GRANT OPTION FOR
     is a revoke of the option only and passes);
 11. REVOKEs a table or sequence from service_role without a later GRANT ALL back to
     service_role of the same name, or in bulk: ALL SEQUENCES for an explicit SEQUENCE,
     the same bulk kind for a bulk revoke, and both ALL TABLES and ALL SEQUENCES for
     `ON name` / `ON TABLE name` (either can name a sequence).

Threat model: honest mistakes. Deliberately disguised SQL is a code-review concern;
the /ship live privilege assertion checks the resulting privileges whatever the SQL
text looked like.

Comments are ignored everywhere, and text in a comment or a string never counts as
a REVOKE, GRANT or SECURITY DEFINER that satisfies rule 1. Function identity = schema
(default public) + name + argument TYPES (argument names, modes, defaults and OUT
arguments dropped; common type aliases normalized). A REVOKE/GRANT without an
argument list matches every overload of that name.

Run from anywhere inside the repo:  python3 .github/scripts/check_function_grants.py
One file, no baseline:              python3 .github/scripts/check_function_grants.py --file <path.sql>
Tests:                              python3 .github/scripts/test_check_function_grants.py
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

CONFIG_FILE = ".github/scripts/function_grants_config.json"
DEFAULT_MIGRATIONS_DIR = "supabase/migrations"
DEFAULT_BASELINE_FILE = ".github/scripts/function_grants_baseline.txt"

# RLS helpers that policies call as the requesting role: exact identities
# (schema, name, argument types). Filled from the config's rls_helper_exemptions at
# start-up; empty by default. A new overload of an exempt name is not exempt.
KEEP_SET = set()
PUBLIC_ROLES = {"public", "anon", "authenticated"}

TYPE_ALIASES = {
    "varchar": "character varying",
    "char": "character",
    "bpchar": "character",
    "int": "integer",
    "int4": "integer",
    "int2": "smallint",
    "int8": "bigint",
    "float8": "double precision",
    "float4": "real",
    "bool": "boolean",
    "timestamptz": "timestamp with time zone",
    "timestamp without time zone": "timestamp",
    "timetz": "time with time zone",
    "time without time zone": "time",
    "decimal": "numeric",
}
MULTIWORD_TYPES = [
    "timestamp with time zone", "timestamp without time zone",
    "time with time zone", "time without time zone",
    "character varying", "double precision", "bit varying",
]
ARG_MODES = {"in", "out", "inout", "variadic"}


# ---------------------------------------------------------------------------
# SQL scanning: blank out comments, strings and dollar-quoted bodies.
# ---------------------------------------------------------------------------
DOLLAR_TAG_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$")


def scrub(sql, keep_strings=False):
    """Return (clean_sql, bodies, strings). Comments -> ' '; '...' -> '$STR<n>$' with the
    literal's content kept in `strings` (kept verbatim instead when keep_strings);
    $tag$...$tag$ -> $$BODY<n>$$ with the body kept in `bodies`. Double-quoted
    identifiers are kept."""
    out = []
    bodies = []
    strings = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j
            out.append(" ")
        elif c == "/" and sql.startswith("/*", i):
            depth, i = 1, i + 2
            while i < n and depth:
                if sql.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif sql.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            out.append(" ")
        elif c == "'":
            escaped = i > 0 and sql[i - 1] in "eE" and (i < 2 or not (sql[i - 2].isalnum() or sql[i - 2] == "_"))
            start = i
            i += 1
            while i < n:
                if escaped and sql[i] == "\\":
                    i += 2
                    continue
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            if keep_strings:
                out.append(sql[start:i])
            else:
                lit = sql[start:i]
                strings.append(lit[lit.index("'") + 1:-1].replace("''", "'") if lit.endswith("'") else lit[1:])
                out.append(f"'$STR{len(strings) - 1}$'")
        elif c == '"':
            j = i + 1
            while j < n:
                if sql[j] == '"':
                    if j + 1 < n and sql[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i:j + 1])
            i = j + 1
        elif c == "$" and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")):
            m = DOLLAR_TAG_RE.match(sql, i)
            if not m:
                out.append(c)
                i += 1
                continue
            tag = m.group(0)
            end = sql.find(tag, m.end())
            body_end = n if end == -1 else end
            bodies.append(sql[m.end():body_end])
            out.append(f" $$BODY{len(bodies) - 1}$$ ")
            i = n if end == -1 else end + len(tag)
        else:
            out.append(c)
            i += 1
    return "".join(out), bodies, strings


def statements(clean):
    return [re.sub(r"\s+", " ", s).strip() for s in clean.split(";") if s.strip()]


# ---------------------------------------------------------------------------
# Identifiers and function identities.
# ---------------------------------------------------------------------------
IDENT = r'(?:"(?:[^"]|"")+"|[A-Za-z_][A-Za-z0-9_$]*)'
QNAME = rf"({IDENT})(?:\s*\.\s*({IDENT}))?"


def norm_ident(tok):
    if tok.startswith('"'):
        return tok[1:-1].replace('""', '"')
    return tok.lower()


def split_qname(a, b):
    return ("public", norm_ident(a)) if b is None else (norm_ident(a), norm_ident(b))


def split_top_level(s):
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur))
    return parts


def norm_type(t):
    t = re.sub(r"\s+", " ", t.strip().lower())
    t = re.sub(r"\s*\(\s*[\d\s,]*\)", "", t)  # varchar(10) -> varchar, numeric(10,2) -> numeric
    arr = ""
    while t.endswith("[]"):
        arr += "[]"
        t = t[:-2].strip()
    t = re.sub(r'^(?:"?public"?\s*\.\s*)', "", t).strip('"')
    return TYPE_ALIASES.get(t, t) + arr


def norm_args(argstr):
    """'p_id uuid, OUT x int, p varchar(10) DEFAULT null' -> ('uuid', 'character varying')"""
    types = []
    for raw in split_top_level(argstr):
        a = re.split(r"\s+default\s+|\s*=\s*", raw.strip(), maxsplit=1, flags=re.I)[0].strip()
        a = re.sub(r"\s*\([^()]*\)", "", a).strip()  # numeric(10, 2) -> numeric; timestamp(3) with time zone -> ...
        if not a:
            continue
        words = a.split()
        mode = words[0].lower() if words else ""
        if mode in ARG_MODES:
            words = words[1:]
        if mode == "out":
            continue
        rest = " ".join(words)
        # "name type" -> drop the name; a bare multi-word type ("double precision") stays whole
        if len(words) > 1 and not any(rest.lower().startswith(mt) for mt in MULTIWORD_TYPES):
            rest = " ".join(words[1:])
        types.append(norm_type(rest))
    return tuple(types)


def find_call(stmt, start):
    """Parse `<qname> [ ( args ) ]` at stmt[start:]; return (schema, name, args|None, end)."""
    m = re.compile(r"\s*" + QNAME).match(stmt, start)
    if not m:
        return None
    schema, name = split_qname(m.group(1), m.group(2))
    j = m.end()
    k = j
    while k < len(stmt) and stmt[k] == " ":
        k += 1
    if k < len(stmt) and stmt[k] == "(":
        depth, e = 0, k
        while e < len(stmt):
            if stmt[e] == "(":
                depth += 1
            elif stmt[e] == ")":
                depth -= 1
                if depth == 0:
                    break
            e += 1
        return schema, name, norm_args(stmt[k + 1:e]), e + 1
    return schema, name, None, j


def matches(target, fn):
    """target = (schema, name, args|None) from a REVOKE/GRANT; fn = (schema, name, args)."""
    if target[0] != fn[0] or target[1] != fn[1]:
        return False
    return target[2] is None or fn[2] is None or target[2] == fn[2]


# ---------------------------------------------------------------------------
# Statement classification.
# ---------------------------------------------------------------------------
PRIV = r"(?:execute|all(?:\s+privileges)?)"
PRIVS = rf"{PRIV}(?:\s*,\s*{PRIV})*"
ROUTINE_KW = r"(?:function|procedure|routine)s?"
ROLE_TOKEN = rf"(?:group\s+)?{IDENT}"
ROLE_LIST = rf"{ROLE_TOKEN}(?:\s*,\s*{ROLE_TOKEN})*"
GRANTED_BY = rf"(?:\s+granted\s+by\s+({IDENT}))?"
MAX_BODY_DEPTH = 3

CREATE_RE = re.compile(r"^create\s+(?:or\s+replace\s+)?(?:function|procedure)\s", re.I)
ALTER_FN_RE = re.compile(r"^alter\s+(?:function|procedure|routine)\s", re.I)
REVOKE_RE = re.compile(
    rf"^revoke\s+(grant\s+option\s+for\s+)?{PRIVS}\s+on\s+{ROUTINE_KW}\s+(.*?)\s+from\s+({ROLE_LIST})"
    rf"{GRANTED_BY}(?:\s+(?:cascade|restrict))?$", re.I)
REVOKE_ALL_IN_SCHEMA_RE = re.compile(
    rf"^revoke\s+.*?\bon\s+all\s+(?:functions|procedures|routines)\s+in\s+schema\s+.*?\s+from\s+({ROLE_LIST})", re.I)
GRANT_RE = re.compile(
    rf"^grant\s+{PRIVS}\s+on\s+(all\s+(?:functions|procedures|routines)\s+in\s+schema\s+.*?|{ROUTINE_KW}\s+.*?)"
    rf"\s+to\s+({ROLE_LIST})(?:\s+with\s+grant\s+option)?{GRANTED_BY}$", re.I)
ADP_GRANT_RE = re.compile(
    rf"^alter\s+default\s+privileges\b.*?\bgrant\s+{PRIVS}\s+on\s+(?:functions|routines)\s+to\s+({ROLE_LIST})"
    r"(?:\s+with\s+grant\s+option)?$", re.I)
ADP_REVOKE_RE = re.compile(
    rf"^alter\s+default\s+privileges\b.*?\brevoke\b.*?\bon\s+(?:functions|routines)\s+from\s+({ROLE_LIST})", re.I)
OWNER_RE = re.compile(rf"^alter\s+(?:function|procedure|routine)\s.*\bowner\s+to\s+({IDENT})$", re.I)
# Tables, views, materialized views, foreign tables and sequences. A GRANT or
# REVOKE whose object is not one of the other GRANT object types is a relation grant
# (`ON name` without a keyword means a table). An object keyword only counts when a name
# follows it: `ON language TO anon` grants a table called "language".
NON_RELATION_OBJECT = (r"(?:schema|type|domain|database|foreign\s+(?:data\s+wrapper|server)|language|large\s+object"
                       r"|tablespace|parameter|(?:all\s+)?(?:function|procedure|routine)s?)\s+(?!(?:to|from)\b)\S")
RELATION_OBJECT = rf"(?!{NON_RELATION_OBJECT})(all\s+(?:tables|sequences)\s+in\s+schema\s+.*?|(?:(?:table|sequence)\s+)?.*?)"
TABLE_GRANT_RE = re.compile(
    rf"^grant\s+.+?\s+on\s+{RELATION_OBJECT}\s+to\s+({ROLE_LIST})(?:\s+with\s+grant\s+option)?{GRANTED_BY}$", re.I)
TABLE_REVOKE_RE = re.compile(
    rf"^revoke\s+(grant\s+option\s+for\s+)?.+?\s+on\s+{RELATION_OBJECT}\s+from\s+({ROLE_LIST})"
    rf"{GRANTED_BY}(?:\s+(?:cascade|restrict))?$", re.I)
TABLE_GRANT_ALL_RE = re.compile(r"^grant\s+all(?:\s+privileges)?\s+on\s", re.I)
ADP_TABLE_GRANT_RE = re.compile(
    rf"^alter\s+default\s+privileges\b.*?\bgrant\s+.+?\s+on\s+(?:tables|sequences)\s+to\s+({ROLE_LIST})"
    r"(?:\s+with\s+grant\s+option)?$", re.I)
ADP_TABLE_REVOKE_RE = re.compile(
    rf"^alter\s+default\s+privileges\b.*?\brevoke\s+(grant\s+option\s+for\s+)?.*?\bon\s+(?:tables|sequences)\s+"
    rf"from\s+({ROLE_LIST})", re.I)
MENTIONS_RELATIONS_RE = re.compile(r"\bon\s+(?:tables|sequences)\b", re.I)
RELATION_OWNER_RE = re.compile(
    rf"^alter\s+(?:table|view|materialized\s+view|sequence|foreign\s+table)\s.*\bowner\s+to\s+({IDENT})$", re.I)
REASSIGN_RE = re.compile(rf"^reassign\s+owned\s+by\s+.*?\s+to\s+({IDENT})$", re.I)
# quoted grantees ("anon") are the dump's house style: end on whitespace/end, not \b
ROLE_GRANT_RE = re.compile(rf"^grant\s+(?!.*\son\s)({ROLE_LIST})\s+to\s+({ROLE_LIST})(?=\s|$)", re.I)
DROP_ROUTINE_RE = re.compile(r"^drop\s+(?:function|routine)\s+(?:if\s+exists\s+)?", re.I)
ALTER_EXTENSION_ADD_RE = re.compile(r"^alter\s+extension\s+.*\badd\s+(?:function|procedure|routine)\b", re.I)
ALTER_GROUP_RE = re.compile(rf"^alter\s+group\s+{IDENT}\s+add\s+user\s+({ROLE_LIST})$", re.I)
CREATE_ROLE_RE = re.compile(rf"^create\s+(?:role|user|group)\s+{IDENT}\b(.*)$", re.I)
CREATE_ROLE_MEMBERS_RE = re.compile(rf"(?<!\bin )\b(?:role|admin|user)\s+({ROLE_LIST})", re.I)
SET_ROLE_RE = re.compile(r"^(?:set\s+(?:local\s+|session\s+)?(?:role|session\s+authorization)\b|reset\s+(?:role|session\s+authorization)\b)", re.I)
SET_CONFIG_RE = re.compile(r"\bset_config\s*\(\s*'\$STR(\d+)\$'", re.I)
SET_CONFIG_COMPUTED_RE = re.compile(r"\bset_config\s*\(\s*(?!'\$STR\d+\$'\s*,)", re.I)
ALTER_API_ROLE_RE = re.compile(
    r"^alter\s+(?:role|user)\s+\"?(anon|authenticated|public)\"?\b.*\b(?:bypassrls|superuser|createrole|inherit"
    r"|set\s+(?:role|session_authorization)\b)", re.I)
CATALOG_WRITE_RE = re.compile(
    r"\b(?:update|insert\s+into|delete\s+from)\s+(?:only\s+)?(?:\"?pg_catalog\"?\s*\.\s*)?\"?(?:pg_proc|pg_default_acl"
    r"|pg_auth_members|pg_authid)\"?(?![\w])", re.I)
SECDEF_RE = re.compile(r"\bsecurity\s+definer\b", re.I)
MENTIONS_ROUTINES_RE = re.compile(r"\b(?:functions?|procedures?|routines?)\b", re.I)
# Where a privilege-relevant statement can start inside a plpgsql body (after
# BEGIN / THEN / LOOP / a label / FOREACH ... LOOP / CASE ... THEN, etc.).
BODY_KEYWORD_RE = re.compile(
    r"\b(?:grant|revoke|alter\s+default\s+privileges|alter\s+(?:function|procedure|routine|group|role|user|extension"
    r"|table|view|materialized\s+view|sequence|foreign\s+table)"
    r"|reassign\s+owned|drop\s+(?:function|routine)"
    r"|create\s+(?:or\s+replace\s+)?(?:function|procedure)|create\s+(?:schema|role|user|group)"
    r"|set\s+(?:local\s+|session\s+)?(?:role|session\s+authorization)|reset\s+(?:role|session\s+authorization))\b", re.I)
# A string literal that holds privilege-changing SQL. New migrations may not change
# privileges through dynamic SQL at all (EXECUTE, helper functions, templates):
# write GRANT / REVOKE / OWNER TO as plain statements so this check can read them.
# Structure, not vocabulary: an object GRANT needs ON ... TO, a role GRANT / REVOKE must
# start a statement, an object REVOKE needs ON ... FROM, so prose such as "A grant to
# an operator is pending" or "Moved to public listing" is not SQL.
STMT_START = r"(?:^|;|\b(?:begin|then|else|loop|do)\b)\s*"
PRIV_SQL_RE = re.compile(
    r"\bgrant\b[^;]*?\bon\b[^;]*?\bto\b"
    rf"|{STMT_START}grant\s+[\w\"$]+(?:\s*,\s*[\w\"$]+)*\s+to\s+(?:group\s+)?\"?(?:anon|authenticated|public)\"?(?![\w\"])"
    r"|\brevoke\b[^;]*?\bon\b[^;]*?\bfrom\b"
    r"|\bdefault\s+privileges\b|\bowner\s+to\b|\breassign\s+owned\b|\bset\s+role\b|\bsession\s+authorization\b"
    r"|\bsecurity\s+definer\b|\badd\s+user\b|\b(?:create|alter)\s+(?:role|group|user)\b"
    r"|\balter\s+extension\b[^;]*\badd\b", re.I)
# EXECUTE text naming a protected role as a grantee: TO anon / TO "anon" / TO GROUP anon
GRANTEE_PHRASE_RE = re.compile(r"\bto\s+(?:group\s+)?\"?(?:anon|authenticated|public)\"?(?![\w\"])", re.I)
# statement starts inside a (body) statement, used to tell a RAISE message from other literals
STMT_BOUNDARY_RE = re.compile(r"\b(?:then|else|loop|begin)\b", re.I)
# format() placeholders. %I (identifier) and %L (literal) quote their argument. A raw
# %s splices text in unquoted, so its argument must be something that cannot carry
# SQL: a reg* cast or a catalog formatter. A literal is never needed there (write the
# text into the template) and would let a keyword be split across template and argument.
FORMAT_PLACEHOLDER_RE = re.compile(r"%(?:(\d+)\$)?(-?(?:\d+|\*(?:\d+\$)?)?)([a-zA-Z%])")
SAFE_RAW_ARG_RE = re.compile(
    r"\s*(?:[\w.\"]+(?:\s*\(\s*[\w.\"]*\s*\))?\s*::\s*reg(?:procedure|proc|class|type|namespace|role|oper|operator"
    r"|collation|config|dictionary)"
    r"|(?:pg_catalog\s*\.\s*)?(?:pg_get_function_arguments|pg_get_function_identity_arguments|oidvectortypes"
    r"|format_type|quote_ident|quote_literal|quote_nullable)\s*\(.*\))\s*", re.S | re.I)


def raw_placeholders_safe(template, args_text):
    """True if every %s in the format() template is fed by an argument that cannot
    carry SQL (see SAFE_RAW_ARG_RE); a '*' width or a missing argument fails closed."""
    args = split_top_level(args_text or "")
    seq = 0
    for pos, width, conv in FORMAT_PLACEHOLDER_RE.findall(template):
        if conv == "%":
            continue
        if "*" in width:
            return False
        idx = int(pos) - 1 if pos else seq
        seq = idx + 1
        if conv == "s":
            if idx >= len(args) or not SAFE_RAW_ARG_RE.fullmatch(args[idx]):
                return False
        elif conv not in ("I", "L"):
            return False
    return True


def roles_of(text):
    """'PUBLIC, GROUP "Anon", authenticated' -> {'public', 'Anon', 'authenticated'} (GROUP is a noise word)."""
    out = set()
    for r in split_top_level(text):
        r = re.sub(r"^\s*group\s+", "", r.strip(), flags=re.I).strip()
        if r:
            out.add(norm_ident(r))
    return out


def targets_of(text):
    """'public.f(uuid), g' -> [(schema, name, args|None), ...]"""
    out, pos = [], 0
    while pos < len(text):
        call = find_call(text, pos)
        if not call:
            break
        schema, name, args, end = call
        out.append((schema, name, args))
        m = re.compile(r"\s*,\s*").match(text, end)
        if not m:
            break
        pos = m.end()
    return out


def is_keep_set(t):
    return (t[0], t[1], t[2]) in KEEP_SET


def names_keep_set(t):
    """True if t names an exempt helper by schema + name (any argument list)."""
    return any(k[0] == t[0] and k[1] == t[1] for k in KEEP_SET)


def relation_targets(text):
    """'TABLE public.a, "B"' -> {('rel', 'public', 'a'), ('rel', 'public', 'B')};
    'SEQUENCE s' -> {('seq', 'public', 's')};
    'ALL SEQUENCES IN SCHEMA public' -> {('all-sequences', 'public')}."""
    m = re.match(rf"all\s+(tables|sequences)\s+in\s+schema\s+(.*)$", text.strip(), re.I)
    if m:
        kind = "all-" + m.group(1).lower()
        return {(kind, norm_ident(s.strip())) for s in split_top_level(m.group(2))}
    kind = "seq" if re.match(r"sequence\s", text.strip(), re.I) else "rel"
    text = re.sub(r"^(?:table|sequence)\s+", "", text.strip(), flags=re.I)
    out = set()
    for part in split_top_level(text):
        q = re.compile(r"\s*" + QNAME + r"\s*$").match(part)
        if q:
            out.add((kind,) + split_qname(q.group(1), q.group(2)))
    return out


def covers(granted, revoked):
    """True if every revoked relation target is covered by a later GRANT ALL: the same
    name (with any keyword), or a bulk grant of the same kind — ALL SEQUENCES for an
    explicit SEQUENCE, the same bulk kind for a bulk revoke. `ON name` / `ON TABLE name`
    can also name a sequence, which ALL TABLES does not cover, so it needs a grant-back by
    name or both ALL TABLES and ALL SEQUENCES."""
    named = {g[1:] for g in granted if g[0] in ("rel", "seq")}
    for t in revoked:
        if t in granted:
            continue
        if t[0] in ("rel", "seq") and t[1:] in named:
            continue
        if t[0] == "seq" and ("all-sequences", t[1]) in granted:
            continue
        if t[0] == "rel" and ("all-tables", t[1]) in granted and ("all-sequences", t[1]) in granted:
            continue
        return False
    return bool(revoked)


def as_sql(text):
    """A string literal's content read the way Postgres would run it: comments removed
    (`GRANT /* x */ ... TO -- y` is still a GRANT), nested bodies kept as text,
    whitespace collapsed."""
    clean, bodies, _ = scrub(text, keep_strings=True)
    for n, body in enumerate(bodies):
        clean = clean.replace(f"$$BODY{n}$$", " " + as_sql(body) + " ")
    return re.sub(r"\s+", " ", clean)


def is_message_literal(st, pos):
    """True only if the literal at pos belongs to a RAISE / ASSERT that starts the
    (sub)statement it sits in — not merely a statement that mentions `raise` somewhere."""
    prefix = st[:pos]
    cuts = list(STMT_BOUNDARY_RE.finditer(prefix))
    seg = prefix[cuts[-1].end():] if cuts else prefix
    return bool(re.match(r"\s*(?:<<\w+>>\s*)?(?:raise|assert)\b", seg, re.I))


def blank_strings(text):
    """Same length as text, with the inside of every '...' literal replaced by spaces."""
    out, in_str, i = list(text), False, 0
    while i < len(text):
        ch = text[i]
        if ch == "'":
            if in_str and i + 1 < len(text) and text[i + 1] == "'":
                out[i] = out[i + 1] = " "
                i += 2
                continue
            in_str = not in_str
        elif in_str:
            out[i] = " "
        i += 1
    return "".join(out)


def check_body(body, problems, depth):
    """A DO block, a plpgsql body or a SQL-language string body. Static statements
    are classified like top-level ones; an EXECUTE may only run a single literal or
    format() of a literal template that uses the quoting placeholders %I / %L."""
    if depth >= MAX_BODY_DEPTH:
        problems.append("dollar-quoted bodies nested too deep to verify (fail closed)")
        return
    text, _, _ = scrub(body, keep_strings=True)
    if SECDEF_RE.search(text):
        problems.append("SECURITY DEFINER inside a DO block or function body cannot be verified — "
                        "create the function with a plain CREATE FUNCTION statement")
    classify(body, problems, events=[], depth=depth + 1)
    blanked = blank_strings(text)
    for m in re.finditer(r"\bexecute\b", blanked, re.I):
        before = blanked[:m.start()].rstrip()
        after = blanked[m.end():]
        if re.match(r"\s+on\b", after, re.I) or re.search(r"(?:\bgrant|\brevoke|\bfor|,)$", before, re.I):
            continue  # the EXECUTE privilege keyword, not the plpgsql EXECUTE statement
        end = blanked.find(";", m.end())
        end = len(blanked) if end == -1 else end
        cut = re.search(r"\b(?:into|using)\b", blanked[m.end():end], re.I)
        stop = m.end() + cut.start() if cut else end
        expr, expr_bl = text[m.end():stop], blanked[m.end():stop]
        # plain '...' only: an E'...' / U&'...' literal can spell a keyword with escapes
        lit = re.fullmatch(r"\s*'((?:[^']|'')*)'\s*", expr, re.S)
        fmt = re.fullmatch(r"\s*format\s*\(\s*'((?:[^']|'')*)'\s*(?:,(.*))?\)\s*", expr, re.S | re.I)
        if lit or (fmt and "||" not in expr_bl and raw_placeholders_safe(fmt.group(1), fmt.group(2))):
            sql = as_sql((lit or fmt).group(1).replace("''", "'"))
            if GRANTEE_PHRASE_RE.search(sql):
                problems.append(f"EXECUTE text names PUBLIC/anon/authenticated as a grantee: {sql.strip()[:80]!r}")
            continue  # the rest of the literal / template is checked by the string rule in classify()
        problems.append(f"EXECUTE of SQL that is not a single literal or format() of a literal template "
                        f"(%I / %L, or %s fed by a reg* cast / catalog formatter) cannot be verified "
                        f"(fail closed): {expr.strip()[:80]!r}")


def body_statement_start(st):
    """Position of the first privilege-relevant keyword in a body statement, or None.
    `UPDATE t SET role = ...` / `ON CONFLICT DO UPDATE SET role = ...` is not SET ROLE."""
    for m in BODY_KEYWORD_RE.finditer(st):
        if re.match(r"set\b", m.group(0), re.I) and re.search(r"\b(?:update|insert)\b", st[:m.start()], re.I):
            continue
        return m.start()
    return None


def classify(sql, problems, events, depth=0):
    """Walk one SQL text (a migration or a body). `events` records, in statement
    order, CREATE / REVOKE / GRANT on routines for the SECURITY DEFINER rule."""
    clean, bodies, strings = scrub(sql)
    for body in bodies:
        check_body(body, problems, depth)
    for st in statements(clean):
        for m in re.finditer(r"'\$STR(\d+)\$'", st):
            if is_message_literal(st, m.start()):
                continue  # RAISE / ASSERT message text never executes
            lit = strings[int(m.group(1))]
            if PRIV_SQL_RE.search(as_sql(lit)):
                problems.append(f"privilege-changing SQL in a string cannot be verified — write GRANT / REVOKE / "
                                f"OWNER TO as plain statements: {lit.strip()[:80]!r}")
        if CATALOG_WRITE_RE.search(st):
            problems.append(f"direct write to a privilege catalog (pg_proc / pg_default_acl / pg_auth_members) "
                            f"bypasses GRANT/REVOKE and cannot be verified: {st[:80]}")
        for m in SET_CONFIG_RE.finditer(st):
            if strings[int(m.group(1))].strip().lower() in ("role", "session_authorization"):
                problems.append(f"set_config('{strings[int(m.group(1))].strip()}', ...) switches role — "
                                f"migrations must run as postgres: {st[:60]}")
        if SET_CONFIG_COMPUTED_RE.search(st):
            problems.append(f"set_config() with a computed setting name cannot be verified (it could switch role) — "
                            f"use a literal name: {st[:60]}")
        if depth:
            k = body_statement_start(st)
            if k is None:
                continue
            st = st[k:]
        handle_statement(st, problems, events, strings, depth)


def handle_statement(st, problems, events, strings, depth):
    if CREATE_RE.match(st) or ALTER_FN_RE.match(st):
        m = OWNER_RE.match(st)
        if m and norm_ident(m.group(1)) in PUBLIC_ROLES:
            problems.append(f"ALTER ... OWNER TO {norm_ident(m.group(1))} — the owner can always execute: {st[:80]}")
        if re.search(r"\bset\s+(?:role|session_authorization)\b", st, re.I):
            problems.append(f"a function that sets `role` switches role when it runs — not allowed: {st[:80]}")
        if ALTER_FN_RE.match(st) and re.search(r"\b(?:rename\s+to|set\s+schema)\b", st, re.I):
            call = find_call(st, ALTER_FN_RE.match(st).end())
            if call and names_keep_set(call):
                problems.append(f"renaming or moving the exempt RLS helper {call[0]}.{call[1]} would carry its "
                                f"anon/authenticated grants to another name — not allowed: {st[:80]}")
        # a SQL-language body written as a string literal is still a body
        for ref in re.findall(r"\bas\s+'\$STR(\d+)\$'", st, re.I):
            check_body(strings[int(ref)], problems, depth)
        is_create = bool(CREATE_RE.match(st))
        if SECDEF_RE.search(st) or is_create:
            call = find_call(st, CREATE_RE.match(st).end() if is_create else ALTER_FN_RE.match(st).end())
            if not call:
                if SECDEF_RE.search(st):
                    problems.append(f"SECURITY DEFINER statement whose function name could not be parsed: {st[:80]}")
                return
            schema, name, args, _ = call
            fn = (schema, name, args or ())
            label = f"{schema}.{name}({', '.join(args or ())})"
            if is_create:  # a CREATE resets the ACL; an ALTER keeps it
                events.append(("create", fn, (label, bool(SECDEF_RE.search(st)))))
            else:
                events.append(("alter-secdef", fn, (label, True)))
        return
    m = RELATION_OWNER_RE.match(st)
    if m:
        if norm_ident(m.group(1)) in PUBLIC_ROLES:
            problems.append(f"ALTER ... OWNER TO {norm_ident(m.group(1))} on a table, view or sequence — the owner "
                            f"holds every privilege: {st[:80]}")
        return
    if re.match(r"^create\s+schema\b", st, re.I):
        g = re.search(r"\bgrant\b", st, re.I)
        if g:  # GRANT is a legal CREATE SCHEMA element
            handle_statement(st[g.start():], problems, events, strings, depth)
        return
    m = CREATE_ROLE_RE.match(st)
    if m:
        for mm in CREATE_ROLE_MEMBERS_RE.finditer(m.group(1)):
            bad = roles_of(mm.group(1)) & PUBLIC_ROLES
            if bad:
                problems.append(f"new role gets {', '.join(sorted(bad))} as a member — anon/authenticated must not "
                                f"inherit other roles: {st[:80]}")
        return
    m = DROP_ROUTINE_RE.match(st)
    if m:
        if re.search(r"\bcascade\b", st, re.I):
            for call in targets_of(st[m.end():]):
                if names_keep_set(call):
                    problems.append(f"DROP ... CASCADE on the exempt RLS helper {call[0]}.{call[1]} silently drops "
                                    f"the RLS policies that call it: {st[:80]}")
        return
    if ALTER_EXTENSION_ADD_RE.match(st):
        problems.append(f"ALTER EXTENSION ... ADD FUNCTION hides an app function from the extension-excluding "
                        f"privilege audits — not allowed: {st[:80]}")
        return
    m = ALTER_API_ROLE_RE.match(st)
    if m:
        problems.append(f"ALTER ROLE {m.group(1)} with a privilege or role-switch attribute — the public API roles "
                        f"must keep their defaults: {st[:80]}")
        return
    m = ALTER_GROUP_RE.match(st)
    if m:
        bad = roles_of(m.group(1)) & PUBLIC_ROLES
        if bad:
            problems.append(f"ALTER GROUP ... ADD USER {', '.join(sorted(bad))} — anon/authenticated must not inherit "
                            f"other roles: {st[:80]}")
        return
    m = REASSIGN_RE.match(st)
    if m:
        if norm_ident(m.group(1)) in PUBLIC_ROLES:
            problems.append(f"REASSIGN OWNED ... TO {norm_ident(m.group(1))} — the owner can always execute: {st[:80]}")
        return
    if SET_ROLE_RE.match(st):
        problems.append(f"migrations must run as postgres — role switching is not allowed: {st[:60]}")
        return
    if re.match(r"^revoke\b", st, re.I):
        m = REVOKE_ALL_IN_SCHEMA_RE.match(st)
        if m:
            if "service_role" in roles_of(m.group(1)):
                problems.append(f"REVOKE on ALL FUNCTIONS IN SCHEMA from service_role — the API loses every function: {st[:80]}")
            return
        m = REVOKE_RE.match(st)
        if m:
            grantor = norm_ident(m.group(4)) if m.group(4) else None
            effective = not m.group(1) and grantor in (None, "postgres", "current_user", "current_role")
            for t in targets_of(m.group(2)):
                # GRANT OPTION FOR leaves EXECUTE; GRANTED BY <other> leaves postgres's grants
                events.append(("revoke" if effective else "revoke-noop", t, roles_of(m.group(3))))
            return
        m = TABLE_REVOKE_RE.match(st)
        if m:
            grantor = norm_ident(m.group(4)) if m.group(4) else None
            effective = not m.group(1) and grantor in (None, "postgres", "current_user", "current_role")
            if effective and "service_role" in roles_of(m.group(3)):
                events.append(("rel-revoke-sr", frozenset(relation_targets(m.group(2))), st[:80]))
        return
    if re.match(r"^grant\b", st, re.I):
        m = GRANT_RE.match(st)
        if m:
            what, roles = m.group(1), roles_of(m.group(2))
            bad = roles & PUBLIC_ROLES
            if re.match(r"all\s", what, re.I):
                if bad:
                    problems.append(f"GRANT on ALL FUNCTIONS/ROUTINES IN SCHEMA to {', '.join(sorted(bad))} — never open functions in bulk")
                return
            for t in targets_of(re.sub(rf"^{ROUTINE_KW}\s+", "", what, flags=re.I)):
                if bad and not is_keep_set(t):
                    problems.append(f"GRANT on {t[0]}.{t[1]} to {', '.join(sorted(bad))} — functions must be service_role only")
                events.append(("grant", t, roles))
            return
        m = ROLE_GRANT_RE.match(st)
        if m:
            if roles_of(m.group(2)) & PUBLIC_ROLES:
                problems.append(f"role membership granted to {', '.join(sorted(roles_of(m.group(2)) & PUBLIC_ROLES))} — "
                                f"anon/authenticated must not inherit other roles: {st[:80]}")
            return
        if not re.search(r"\son\s", st, re.I):
            problems.append(f"role GRANT that this check cannot parse (fail closed): {st[:80]}")
            return
        m = TABLE_GRANT_RE.match(st)
        if m:
            roles = roles_of(m.group(2))
            bad = roles & PUBLIC_ROLES
            if bad:
                problems.append(f"GRANT on {m.group(1)[:60]} to {', '.join(sorted(bad))} — tables, views and sequences "
                                f"are service_role only (the API is their only reader; RLS is the second lock, not the "
                                f"first): {st[:80]}")
            if "service_role" in roles and TABLE_GRANT_ALL_RE.match(st):
                events.append(("rel-grant-all-sr", frozenset(relation_targets(m.group(1))), None))
            return
        if MENTIONS_ROUTINES_RE.search(st):
            problems.append(f"GRANT on functions that this check cannot parse (fail closed): {st[:80]}")
        return
    if re.match(r"^alter\s+default\s+privileges\b", st, re.I):
        action = re.search(r"\b(grant|revoke)\b", st, re.I)  # REVOKE GRANT OPTION FOR ... is a revoke
        if action and action.group(1).lower() == "grant":
            m = ADP_GRANT_RE.match(st)
            if m:
                bad = roles_of(m.group(1)) & PUBLIC_ROLES
                if bad:
                    problems.append(f"ALTER DEFAULT PRIVILEGES grants functions to {', '.join(sorted(bad))} — this re-opens every future function")
            elif MENTIONS_ROUTINES_RE.search(st):
                problems.append(f"ALTER DEFAULT PRIVILEGES on functions that this check cannot parse (fail closed): {st[:80]}")
            m = ADP_TABLE_GRANT_RE.match(st)
            if m:
                bad = roles_of(m.group(1)) & PUBLIC_ROLES
                if bad:
                    problems.append(f"ALTER DEFAULT PRIVILEGES grants tables/sequences to {', '.join(sorted(bad))} — this "
                                    f"re-opens every future table or sequence: {st[:80]}")
            elif MENTIONS_RELATIONS_RE.search(st):
                problems.append(f"ALTER DEFAULT PRIVILEGES on tables/sequences that this check cannot parse "
                                f"(fail closed): {st[:80]}")
        else:
            m = ADP_REVOKE_RE.match(st)
            if m and "service_role" in roles_of(m.group(1)):
                problems.append(f"ALTER DEFAULT PRIVILEGES revokes functions from service_role — the API could not call "
                                f"any new function: {st[:80]}")
            m = ADP_TABLE_REVOKE_RE.match(st)
            if m and not m.group(1) and "service_role" in roles_of(m.group(2)):
                problems.append(f"ALTER DEFAULT PRIVILEGES revokes tables/sequences from service_role — the API could "
                                f"not read or write any new table: {st[:80]}")


def final_holders(window, fn):
    """Walk REVOKE/GRANT events on fn in order; return the set of protected roles and
    service_role that still hold EXECUTE at the end, plus those explicitly revoked."""
    holds, revoked = set(), set()
    for kind, target, roles in window:
        if not matches(target, fn):
            continue
        if kind == "grant":
            holds |= roles
        elif kind == "revoke":
            holds -= roles
            revoked |= roles
    return holds, revoked


def check_sql(sql):
    """Return a list of human-readable problems for one migration's SQL."""
    problems, events = [], []
    classify(sql, problems, events)
    # The rule applies to each function's FINAL definition: SECURITY DEFINER if its last
    # CREATE / ALTER ... SECURITY DEFINER says so. Only REVOKE/GRANT after its last
    # CREATE count (a CREATE resets the ACL; an ALTER keeps what was granted before it).
    finals = {}
    for i, (kind, fn, info) in enumerate(events):
        if kind == "create":
            finals[fn] = {"secdef": info[1], "label": info[0], "start": i + 1}
        elif kind == "alter-secdef":
            f = finals.setdefault(fn, {"start": 0})
            f.update(secdef=True, label=info[0])
    for fn, f in finals.items():
        label = f["label"]
        window = [(k, t, r) for k, t, r in events[f["start"]:] if k in ("grant", "revoke")]
        holds, revoked = final_holders(window, fn)
        if is_keep_set(fn):  # SECURITY DEFINER or not: RLS policies call it as the requesting role
            missing = {"anon", "authenticated", "service_role"} - holds
            if missing:
                problems.append(f"{label} is an exempt RLS helper: after creating it, GRANT EXECUTE "
                                f"TO {', '.join(sorted(missing))} (RLS policies call it as the requesting role) — "
                                f"do NOT revoke it from anon/authenticated")
            continue
        if not f.get("secdef"):
            continue
        missing = PUBLIC_ROLES - revoked
        if missing:
            problems.append(f"SECURITY DEFINER {label}: missing REVOKE EXECUTE ... FROM {', '.join(sorted(missing))} "
                            f"after it is created (need FROM PUBLIC, anon, authenticated)")
        if "service_role" not in holds:
            problems.append(f"SECURITY DEFINER {label}: missing GRANT EXECUTE ... TO service_role after it is created "
                            f"(and after any REVOKE from service_role)")
    # availability: a REVOKE from service_role must be followed by a GRANT back to it
    for i, (kind, target, roles) in enumerate(events):
        if kind == "revoke" and "service_role" in roles:
            regranted = any(k == "grant" and "service_role" in r and (matches(t, target) or matches(target, t))
                            for k, t, r in events[i + 1:])
            if not regranted:
                problems.append(f"REVOKE on {target[0]}.{target[1]} from service_role is never granted back — "
                                f"the API loses this function")
    # A relation REVOKE from service_role needs a later GRANT ALL of the same
    # relations to service_role (a partial grant-back leaves the API short).
    for i, (kind, target, label) in enumerate(events):
        if kind == "rel-revoke-sr":
            granted = set()
            for k, t, _ in events[i + 1:]:
                if k == "rel-grant-all-sr":
                    granted |= t
            if not covers(granted, target):
                problems.append(f"table/sequence REVOKE from service_role is never fully granted back to service_role "
                                f"(GRANT ALL ... TO service_role) — the API loses access: {label}")
    return list(dict.fromkeys(problems))


# ---------------------------------------------------------------------------
# Repo driver.
# ---------------------------------------------------------------------------
def repo_root():
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else os.getcwd()


def parse_exemption(text):
    """'public.f(uuid, text)' -> ('public', 'f', ('uuid', 'text')). The argument list is
    required: an exemption is one exact identity, never every overload of a name."""
    call = find_call(text.strip(), 0)
    if not call or call[2] is None or call[3] != len(text.strip()):
        raise ValueError(f"rls_helper_exemptions entry {text!r} must be schema.name(argument types)")
    return call[0], call[1], call[2]


def load_config(path, required):
    """Return the config dict. A missing file is an error only when `required`."""
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        if required:
            raise ValueError(f"{path} not found: run make_function_grants_baseline.py once to create it")
        return {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"cannot read {path}: {e}")
    if not isinstance(cfg, dict):
        raise ValueError(f"{path} must hold a JSON object")
    ex = cfg.get("rls_helper_exemptions", [])
    if not isinstance(ex, list) or not all(isinstance(x, str) for x in ex):
        raise ValueError(f"{path}: rls_helper_exemptions must be a list of strings")
    return cfg


def report(errors, scanned_line):
    if errors:
        print("❌ Function grant check failed:")
        for e in errors:
            print(f"  - {e}")
        print("\nEvery SECURITY DEFINER function needs, in the same migration, after its last CREATE:\n"
              "  REVOKE EXECUTE ON FUNCTION <fn>(<args>) FROM PUBLIC, anon, authenticated;\n"
              "  GRANT EXECUTE ON FUNCTION <fn>(<args>) TO service_role;\n"
              "Tables, views and sequences are service_role only: never GRANT them to PUBLIC/anon/authenticated.\n"
              "See .claude/rules/database.md. Fix the migration, never this check (weakening it is G7).")
        return 1
    print(f"✅ Function grant check passed ({scanned_line})")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check migrations for grants that open the public API.")
    ap.add_argument("--repo", help="repository root (default: git toplevel)")
    ap.add_argument("--config", help=f"config file (default: <repo>/{CONFIG_FILE})")
    ap.add_argument("--file", action="append", default=[],
                    help="check only this SQL file (repeatable); the baseline is not used")
    a = ap.parse_args(argv)
    root = a.repo or repo_root()
    cfg_path = a.config or os.path.join(root, CONFIG_FILE)
    try:
        cfg = load_config(cfg_path, required=not a.file)
        KEEP_SET.clear()
        KEEP_SET.update(parse_exemption(x) for x in cfg.get("rls_helper_exemptions", []))
    except ValueError as e:
        print(f"check_function_grants: {e}")
        return 1
    errors = []
    if a.file:
        for path in a.file:
            try:
                with open(path, encoding="utf-8") as fh:
                    sql = fh.read()
            except (OSError, UnicodeDecodeError) as e:
                errors.append(f"{path}: cannot read as UTF-8 ({e})")
                continue
            errors.extend(f"{path}: {p}" for p in check_sql(sql))
        return report(errors, f"{len(a.file)} file(s) checked")
    migrations_dir = cfg.get("migrations_dir") or DEFAULT_MIGRATIONS_DIR
    baseline_file = cfg.get("baseline_file") or DEFAULT_BASELINE_FILE
    pinned = cfg.get("baseline_sha256")
    try:
        with open(os.path.join(root, baseline_file), "rb") as fh:
            raw = fh.read()
    except OSError as e:
        print(f"check_function_grants: cannot read {baseline_file}: {e}")
        return 1
    digest = hashlib.sha256(raw).hexdigest()
    if digest != pinned:
        errors.append(f"{baseline_file} changed (sha256 {digest}); the baseline is frozen — new migrations "
                      f"must pass this check instead of being exempted")
    baseline = {l.strip() for l in raw.decode("utf-8", "replace").splitlines()
                if l.strip() and not l.lstrip().startswith("#")}
    mig_dir = os.path.join(root, migrations_dir)
    try:
        names = sorted(os.listdir(mig_dir))
    except OSError as e:
        print(f"check_function_grants: cannot list {migrations_dir}: {e}")
        return 1
    scanned = 0
    for fname in names:
        if not fname.endswith(".sql") or fname in baseline:
            continue
        scanned += 1
        path = os.path.join(mig_dir, fname)
        try:
            with open(path, encoding="utf-8") as fh:
                sql = fh.read()
        except (OSError, UnicodeDecodeError) as e:
            errors.append(f"{migrations_dir}/{fname}: cannot read as UTF-8 ({e})")
            continue
        for p in check_sql(sql):
            errors.append(f"{migrations_dir}/{fname}: {p}")
    return report(errors, f"{scanned} migration(s) scanned, {len(baseline)} in the frozen baseline")


if __name__ == "__main__":
    sys.exit(main())
