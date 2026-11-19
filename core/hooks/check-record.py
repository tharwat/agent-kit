#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Record checks: a workflow command can't end its turn while the record it must leave is missing or malformed.

  --start <kind> [--ticket <T>]  First step of /triage, /operate, /post-op, /handoff. Writes the start marker
                                 `.claude/state/<T>/.started-<kind>` (`.claude/state/.started-handoff` for handoff).
  --kind <kind> [--ticket <T>]   Last step of the command (Claude and Codex). Checks the record; exit 0 when it's
                                 complete (the marker is renamed `.checked-<kind>`, never deleted), exit 1 with
                                 what's missing.
  --cancel <kind> [--ticket <T>] A command that stops early on purpose (BLOCKED, nothing to do, Node missing) closes
                                 its marker: renamed `.cancelled-<kind>`.
  --stop                         The Stop hook. Acts only when a `.started-*` marker exists for the current branch's
                                 ticket (any ticket on a branch that names none) or for /handoff, meaning a command
                                 began and never passed its check. It sends Claude back **once per marker** with
                                 what's missing, and says what to do if the command is waiting (a background review,
                                 the owner) or stopped on purpose. `stop_hook_active` passes. A marker older than
                                 24 h is closed: `.checked-<kind>` if its record is complete, else `.abandoned-<kind>`
                                 (session-context reports those).

| kind     | record                              | must contain                                                    |
|----------|-------------------------------------|-----------------------------------------------------------------|
| triage   | .claude/state/<T>/triage.md         | the contract table header and at least one `| C<n> |` row       |
|          | + .claude/state/<T>/plan-check.json | triage Step 4.8 as fill-in boxes: state homes, contradiction    |
|          |                                     | check, lifecycles, safety defaults (see PLAN_CHECK below)       |
| operate  | .claude/state/<T>/self-review.md    | a `Fingerprint: <64-hex>` line, and an `Inventory: <section>`   |
|          | + .claude/state/<T>/inventory.json  | line naming a section of inventory.json whose boxes are filled  |
|          |                                     | (see INVENTORY below)                                           |
| post-op  | .claude/state/<T>/post-op.md        | `Fingerprint: <64-hex or none (no reviewable change)>` and      |
|          |                                     | `Result: clean or escalate` (`capped` is gone since 1.8.0)      |
| handoff  | .claude/handoffs/latest.md          | written after the start, with the `## Git state` / `Branch:` block |

The two JSON records are fill-in forms: the check asks only whether each box is filled, never how a note was
formatted. `--show plan-check|inventory [--ticket <T>]` prints a record as Markdown for the ticket comment, so the
JSON file stays the one home and the comment is a rendering of it.

The ticket comes from `--ticket` (upper-cased), else from the current `<BRANCH_PREFIX><ticket-lowercase>-<slug>`
branch. With no ticket the check can't run, and it fails open. The project is the git checkout the session is in (a
worktree's own root). Markers are renamed between states, never deleted or overwritten. Writes only under
`.claude/state/`. No network.
"""

import argparse
import json
import os
import re
import sys
import time

sys.dont_write_bytecode = True  # never leave __pycache__ in .claude/hooks/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import kit_facts
except ImportError:
    kit_facts = None

KINDS = kit_facts.RECORD_KINDS if kit_facts else ("triage", "operate", "post-op", "handoff")
NUDGED = kit_facts.NUDGED if kit_facts else "nudged"
STALE_SECONDS = kit_facts.STALE_SECONDS if kit_facts else 24 * 3600
TICKET_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*-[0-9]+$")
TRIAGE_HEADER = ("| ID | Class | Invariant | Paths | Hostile case | Authority | Behavioral proof | Counterfactual | "
                 "Independent vector | Discharge |")
TRIAGE_ROW_RE = re.compile(r"^\|\s*C[0-9]+\s*\|", re.M)
HEX64 = r"[0-9a-f]{64}"
OPERATE_RE = re.compile(r"^Fingerprint:\s*%s\s*$" % HEX64)
FINGERPRINT_LINE_RE = re.compile(r"^Fingerprint:.*$", re.M)
POSTOP_FP_RE = re.compile(r"^Fingerprint:\s*(%s|none \(no reviewable change\))\s*$" % HEX64)
POSTOP_RESULT_RE = re.compile(r"^Result:\s*(clean|escalate)\s*$")
RESULT_LINE_RE = re.compile(r"^Result:.*$", re.M)
HANDOFF_BRANCH_RE = re.compile(r"^Branch:\s*\S", re.M)
INVENTORY_LINE_RE = re.compile(r"^Inventory:[ \t]*(.*)$", re.M)
FILE_LINE_RE = re.compile(r"^\S+:[0-9]+(-[0-9]+)?\b")


def norm(line):
    return re.sub(r"\s+", " ", line.strip())


# ---------------------------------------------------------------- paths

def project_dir(cwd=None):
    if kit_facts is not None:
        return kit_facts.project_root(cwd)
    return os.environ.get("CLAUDE_PROJECT_DIR") or cwd or os.getcwd()


def state_dir(project):
    return os.path.join(project, ".claude", "state")


def ticket_from_branch(project):
    if kit_facts is None:
        return None
    facts = kit_facts.read_facts(project)
    return kit_facts.ticket_for_branch(kit_facts.current_branch(project), facts)


def ticket_dir(project, ticket):
    """`.claude/state/<ticket>/`, matching an existing dir whatever its case (`abc-12/` for `ABC-12`)."""
    if kit_facts is not None:
        return kit_facts.ticket_dir(state_dir(project), ticket)
    return os.path.join(state_dir(project), ticket)


def marker_dir(project, kind, ticket):
    if kind == "handoff":
        return state_dir(project)
    return ticket_dir(project, ticket)


def record_path(project, kind, ticket):
    if kind == "handoff":
        return os.path.join(project, ".claude", "handoffs", "latest.md")
    name = {"triage": "triage.md", "operate": "self-review.md", "post-op": "post-op.md"}[kind]
    return os.path.join(ticket_dir(project, ticket), name)


def rel(project, path):
    return os.path.relpath(path, project).replace(os.sep, "/")


# ---------------------------------------------------------------- checks

def read_marker(marker):
    """(start time, already nudged)."""
    if kit_facts is not None:
        return kit_facts.read_marker(marker)
    return None, False


def read_started(marker):
    return read_marker(marker)[0]


def fingerprints_at_start(marker):
    """The count of `Fingerprint:` lines self-review.md had when /operate started (`fp=<n>` in the marker)."""
    try:
        with open(marker, encoding="utf-8") as fh:
            for word in fh.read().split():
                if word.startswith("fp="):
                    return int(word[3:])
    except (OSError, ValueError):
        pass
    return None


# ---------------------------------------------------------------- JSON records (fill-in forms)
#
# plan-check.json (triage Step 4.8):
#   {"ticket", "state_homes": [{"fact", "home", "writers": [loc], "readers": [loc],
#                               "second_home": null | {"where", "kept_in_step_by": "transaction|trigger", "owner_ok"}}],
#    "state_homes_none": null | "<reason>",
#    "contradiction_check": {"rows_read": n, "decisions_read": n,
#                            "conflicts": [{"conflict", "resolved_by": "owner|default", "resolution"}]},
#    "lifecycles": [{"state", "created", "changed", "removed", "restored", "edited_in_state", "name_reuse",
#                    "safety_flags", "what_a_person_sees"}],
#    "lifecycles_none": null | "<reason>",
#    "safety_defaults": [{"default", "owner_answer"}]}
# inventory.json (operate Phase 1 step 2; one section "Plan", then "Fix batch <n>"):
#   {"ticket", "sections": [{"name",
#       "values": [{"value", "change", "writers": [loc], "readers": [loc], "reader_assumes",
#                   "needs_change": {"answer": "yes|no", "why"}, "search"}],
#       "values_none_search": null | "<search that showed none>",
#       "siblings": [{"behaviour", "sibling": loc, "guards": [str], "copied": {"answer": "yes|not applicable", "why"}}],
#       "siblings_none_search": null | "<search that showed none>",
#       "helpers": [{"helper", "where": loc, "short_circuits", "errors", "success"}]}]}
# A loc is "path:line" (or "path:line-line"). writers/readers may be ["none"]; in plan-check a writer not
# written yet is "new: <path>".

LIFECYCLE_KEYS = ("state", "created", "changed", "removed", "restored", "edited_in_state", "name_reuse",
                  "safety_flags", "what_a_person_sees")


def filled(x):
    return isinstance(x, str) and bool(x.strip())


def load_json(project, ticket, name, out):
    path = os.path.join(ticket_dir(project, ticket), name)
    shown = rel(project, path)
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        out.append("%s doesn't exist" % shown)
        return None, shown
    try:
        data = json.loads(raw)
    except ValueError as exc:
        out.append("%s isn't valid JSON (%s)" % (shown, exc))
        return None, shown
    if not isinstance(data, dict):
        out.append("%s must be a JSON object" % shown)
        return None, shown
    return data, shown


def locs_ok(v, allow_new=False):
    if not isinstance(v, list) or not v or not all(isinstance(x, str) for x in v):
        return False
    if [x.strip().lower() for x in v] == ["none"]:
        return True
    return all(FILE_LINE_RE.match(x.strip()) or (allow_new and x.strip().lower().startswith("new:") and
                                                  len(x.strip()) > 4) for x in v)


def listed(data, key, none_key, where, out, what):
    """A list that must have entries, unless its `none` box holds a reason. Returns the entries."""
    items = data.get(key)
    if items is None:
        items = []
    if not isinstance(items, list):
        out.append("%s `%s` must be a list" % (where, key))
        return []
    if not items and not filled(data.get(none_key)):
        out.append("%s `%s` is empty: add %s, or fill `%s`" % (where, key, what, none_key))
    return [x if isinstance(x, dict) else {} for x in items]


def plan_check_problems(project, ticket):
    out = []
    data, shown = load_json(project, ticket, "plan-check.json", out)
    if data is None:
        if out and out[0].endswith("doesn't exist"):
            out[0] += " (triage Step 4.8 writes it)"
        return out
    for i, h in enumerate(listed(data, "state_homes", "state_homes_none", shown, out, "a row per fact"), 1):
        tag = "%s state_homes[%d]" % (shown, i)
        for k in ("fact", "home"):
            if not filled(h.get(k)):
                out.append("%s: `%s` is empty" % (tag, k))
        for k in ("writers", "readers"):
            if not locs_ok(h.get(k), allow_new=True):
                out.append("%s: `%s` needs path:line entries (or [\"none\"], or \"new: <path>\")" % (tag, k))
        second = h.get("second_home")
        if second is not None:
            if not isinstance(second, dict) or not filled(second.get("where")) or \
                    second.get("kept_in_step_by") not in ("transaction", "trigger") or not filled(second.get("owner_ok")):
                out.append("%s: `second_home` needs `where`, `kept_in_step_by` (transaction or trigger) and "
                           "`owner_ok` (where the owner's OK is recorded), or null" % tag)
    cc = data.get("contradiction_check")
    if not isinstance(cc, dict):
        out.append("%s has no `contradiction_check`" % shown)
    else:
        for k in ("rows_read", "decisions_read"):
            if not isinstance(cc.get(k), int) or isinstance(cc.get(k), bool) or cc.get(k) < 0:
                out.append("%s contradiction_check: `%s` must be a whole number" % (shown, k))
        conflicts = cc.get("conflicts")
        if not isinstance(conflicts, list):
            out.append("%s contradiction_check: `conflicts` must be a list ([] when none were found)" % shown)
        else:
            for i, c in enumerate(conflicts, 1):
                c = c if isinstance(c, dict) else {}
                if not filled(c.get("conflict")) or c.get("resolved_by") not in ("owner", "default") or \
                        not filled(c.get("resolution")):
                    out.append("%s contradiction_check conflicts[%d]: needs `conflict`, `resolved_by` (owner or "
                               "default) and `resolution`" % (shown, i))
    for i, lc in enumerate(listed(data, "lifecycles", "lifecycles_none", shown, out, "a lifecycle per state"), 1):
        empty = [k for k in LIFECYCLE_KEYS if not filled(lc.get(k))]
        if empty:
            out.append("%s lifecycles[%d]: empty %s" % (shown, i, ", ".join("`%s`" % k for k in empty)))
    for i, e in enumerate(listed(data, "enumerations", "enumerations_none", shown, out,
                                 "a row per list the change writes or relies on"), 1):
        empty = [k for k in ("what", "derived_from", "test") if not filled(e.get(k))]
        if empty:
            out.append("%s enumerations[%d] (%s): empty %s. A list is derived from the source (a schema query, a "
                       "directory walk, a parser) and pinned by a test that re-derives it" %
                       (shown, i, e.get("what") or "unnamed", ", ".join("`%s`" % k for k in empty)))
    defaults = data.get("safety_defaults", [])
    if not isinstance(defaults, list):
        out.append("%s `safety_defaults` must be a list ([] when there are none)" % shown)
    else:
        for i, d in enumerate(defaults, 1):
            d = d if isinstance(d, dict) else {}
            if not filled(d.get("default")) or not filled(d.get("owner_answer")):
                out.append("%s safety_defaults[%d]: needs `default` and `owner_answer` (shown to the owner, never "
                           "applied silently)" % (shown, i))
    return out


def answer_ok(box, yes_word, other_word):
    if not isinstance(box, dict) or box.get("answer") not in (yes_word, other_word):
        return False
    return box["answer"] == yes_word or filled(box.get("why"))


def inventory_problems(project, ticket, self_review):
    """The dependency inventory /operate writes before its first production edit (operate Phase 1 step 2)."""
    out = []
    blocks = self_review.split("Self-review:")
    named = INVENTORY_LINE_RE.findall(blocks[-1])
    section_name = named[-1].strip() if named else ""
    data, shown = load_json(project, ticket, "inventory.json", out)
    if data is None:
        if out and out[0].endswith("doesn't exist"):
            out[0] += " (the dependency inventory comes before the first production edit)"
        return out
    if not section_name:
        return ["the last Self-review block has no `Inventory: <section>` line naming the inventory.json section it "
                "covers (Plan, or Fix batch <n>)"]
    sections = data.get("sections")
    if not isinstance(sections, list):
        return ["%s needs a `sections` list" % shown]
    match = [x for x in sections if isinstance(x, dict) and norm(str(x.get("name", ""))).lower() ==
             norm(section_name).lower()]
    if not match:
        return ["%s has no section named `%s` (named by the Self-review `Inventory:` line)" % (shown, section_name)]
    sec = match[-1]
    where = "%s section `%s`" % (shown, section_name)
    consensus = sec.get("consensus")
    if not isinstance(consensus, dict) or not filled(consensus.get("run")) or not filled(consensus.get("enumerators")):
        out.append("%s has no `consensus` with `run` and `enumerators`: the section is the output of "
                   ".claude/workflows/consensus-inventory.js, with its run id added as `consensus.run`" % where)
    for i, v in enumerate(listed(sec, "values", "values_none_search", where, out, "a row per value changed"), 1):
        tag = "%s values[%d] (%s)" % (where, i, v.get("value") or "unnamed")
        for k in ("value", "change", "reader_assumes", "search"):
            if not filled(v.get(k)):
                out.append("%s: `%s` is empty" % (tag, k))
        for k in ("writers", "readers"):
            if not locs_ok(v.get(k)):
                out.append("%s: `%s` needs path:line entries (or [\"none\"])" % (tag, k))
        if not answer_ok(v.get("needs_change"), "yes", "no"):
            out.append("%s: `needs_change` is {\"answer\": \"yes\"} or {\"answer\": \"no\", \"why\": ...}" % tag)
    plan = norm(section_name).lower() == "plan"
    if plan or sec.get("siblings"):
        for i, b in enumerate(listed(sec, "siblings", "siblings_none_search", where, out,
                                     "a row per new behaviour with an existing sibling"), 1):
            tag = "%s siblings[%d] (%s)" % (where, i, b.get("behaviour") or "unnamed")
            if not filled(b.get("behaviour")):
                out.append("%s: `behaviour` is empty" % tag)
            if not (isinstance(b.get("sibling"), str) and (FILE_LINE_RE.match(b["sibling"].strip()))):
                out.append("%s: `sibling` needs a path:line" % tag)
            guards = b.get("guards")
            if not isinstance(guards, list) or not guards or not all(filled(g) for g in guards):
                out.append("%s: `guards` lists every guard the sibling has" % tag)
            if not answer_ok(b.get("copied"), "yes", "not applicable"):
                out.append("%s: `copied` is {\"answer\": \"yes\"} or {\"answer\": \"not applicable\", \"why\": ...}"
                           % tag)
            if not filled(b.get("search")):
                out.append("%s: `search` is empty" % tag)
    for kind, keys in (("claims", ("subject", "claim", "search")), ("lists", ("what", "derived_from"))):
        rows = sec.get(kind, [])
        if not isinstance(rows, list):
            out.append("%s `%s` must be a list" % (where, kind))
            continue
        for i, r in enumerate(rows, 1):
            r = r if isinstance(r, dict) else {}
            tag = "%s %s[%d] (%s)" % (where, kind, i, r.get(keys[0]) or "unnamed")
            empty = [k for k in keys if not filled(r.get(k))]
            if empty:
                out.append("%s: empty %s" % (tag, ", ".join("`%s`" % k for k in empty)))
            if kind == "claims" and (not locs_ok(r.get("proof"), allow_new=True) or not isinstance(r.get("effects"), list)):
                out.append("%s: `proof` needs path:line entries, and `effects` a list ([] only after a search)" % tag)
            if kind == "lists" and (not isinstance(r.get("members"), list) or not r.get("members")):
                out.append("%s: `members` lists every member (or [\"none\"])" % tag)
    helpers = sec.get("helpers", [])
    if not isinstance(helpers, list):
        out.append("%s `helpers` must be a list" % where)
    else:
        for i, h in enumerate(helpers, 1):
            h = h if isinstance(h, dict) else {}
            empty = [k for k in ("helper", "short_circuits", "errors", "success") if not filled(h.get(k))]
            if empty or not (isinstance(h.get("where"), str) and FILE_LINE_RE.match(h["where"].strip())):
                out.append("%s helpers[%d]: needs `helper`, `where` (path:line), `short_circuits`, `errors` and "
                           "`success`" % (where, i))
    return out


# ---------------------------------------------------------------- --show: the readable copy

def cell(x):
    if isinstance(x, list):
        x = ", ".join(str(i) for i in x)
    if isinstance(x, dict):
        x = x.get("answer", "") + ((" — " + x["why"]) if filled(x.get("why")) else "")
    return str("" if x is None else x).replace("|", "\\|").replace("\n", " ")


def table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
    return lines


def render(kind, data):
    out = []
    if kind == "plan-check":
        out += ["## Plan self-check: %s" % data.get("ticket", ""), "", "### State homes"]
        homes = data.get("state_homes") or []
        if homes:
            out += table(["Fact", "Its one home", "Who writes it", "Who reads it", "Second home?"],
                         [[h.get("fact"), h.get("home"), h.get("writers"), h.get("readers"),
                           "none" if not h.get("second_home") else "%s (%s; owner OK: %s)" % (
                               h["second_home"].get("where"), h["second_home"].get("kept_in_step_by"),
                               h["second_home"].get("owner_ok"))] for h in homes])
        else:
            out.append("none — %s" % data.get("state_homes_none", ""))
        cc = data.get("contradiction_check") or {}
        out += ["", "### Contradiction check",
                "%s contract rows read against %s decisions." % (cc.get("rows_read"), cc.get("decisions_read"))]
        conflicts = cc.get("conflicts") or []
        out += table(["Conflict", "Resolved by", "Resolution"],
                     [[c.get("conflict"), c.get("resolved_by"), c.get("resolution")] for c in conflicts]) \
            if conflicts else ["No conflicts found."]
        out += ["", "### Lifecycle check"]
        lcs = data.get("lifecycles") or []
        if lcs:
            for lc in lcs:
                out.append("- **%s**: " % cell(lc.get("state")) + "; ".join(
                    "%s: %s" % (k.replace("_", " "), cell(lc.get(k))) for k in LIFECYCLE_KEYS[1:]))
        else:
            out.append("none — %s" % data.get("lifecycles_none", ""))
        out += ["", "### Derived lists"]
        enums = data.get("enumerations") or []
        out += table(["List", "Derived from", "Test that re-derives it"],
                     [[e.get("what"), e.get("derived_from"), e.get("test")] for e in enums]) \
            if enums else ["none — %s" % data.get("enumerations_none", "")]
        out += ["", "### Safety defaults"]
        out += ["- %s → owner: %s" % (cell(d.get("default")), cell(d.get("owner_answer")))
                for d in data.get("safety_defaults") or []] or ["none"]
    else:
        out += ["## Inventory: %s" % data.get("ticket", "")]
        for sec in data.get("sections") or []:
            out += ["", "### %s" % sec.get("name", ""), "", "Readers and writers:"]
            vals = sec.get("values") or []
            out += table(["Value changed", "How it changes", "Writers", "Readers", "What each reader assumes",
                          "Needs a change?", "Search"],
                         [[v.get("value"), v.get("change"), v.get("writers"), v.get("readers"),
                           v.get("reader_assumes"), v.get("needs_change"), v.get("search")] for v in vals]) \
                if vals else ["none — `%s`" % sec.get("values_none_search", "")]
            sibs = sec.get("siblings") or []
            out += ["", "Siblings:"]
            out += table(["New behaviour", "Existing sibling", "Guards the sibling has", "Copied?"],
                         [[b.get("behaviour"), b.get("sibling"), b.get("guards"), b.get("copied")] for b in sibs]) \
                if sibs else ["none — `%s`" % sec.get("siblings_none_search", "")]
            claims = sec.get("claims") or []
            if claims:
                out += ["", "Claims:"]
                out += table(["Subject", "Claim", "Proof", "Effects found", "Search"],
                             [[c.get("subject"), c.get("claim"), c.get("proof"), c.get("effects") or "none",
                               c.get("search")] for c in claims])
            lists = sec.get("lists") or []
            if lists:
                out += ["", "Derived lists:"]
                out += ["- **%s** (from `%s`): %s" % (cell(l.get("what")), cell(l.get("derived_from")),
                                                     cell(l.get("members"))) for l in lists]
            cons = sec.get("consensus") or {}
            if cons:
                out += ["", "Built by %s (enumerators %s, critic %s, %s single-source items verified)" % (
                    cell(cons.get("run")), cell(cons.get("enumerators")), cell(cons.get("critic")),
                    cell(cons.get("single_source")))]
            helpers = sec.get("helpers") or []
            if helpers:
                out += ["", "Helper contracts:"]
                out += ["- %s (%s): %s · %s · %s" % tuple(cell(h.get(k)) for k in
                                                          ("helper", "where", "short_circuits", "errors", "success"))
                        for h in helpers]
    return "\n".join(out) + "\n"


def cmd_show(project, kind, ticket):
    name = {"plan-check": "plan-check.json", "inventory": "inventory.json"}[kind]
    errors = []
    data, shown = load_json(project, ticket, name, errors)
    if data is None:
        print("check-record: " + "; ".join(errors))
        return 1
    sys.stdout.write(render(kind, data))
    return 0


def problems(project, kind, ticket, started=None, fp_before=None):
    """What's missing from the record, as a list of short reasons. Empty means complete."""
    path = record_path(project, kind, ticket)
    shown = rel(project, path)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return ["%s doesn't exist yet" % shown]
    out = []
    if started is not None and os.path.getmtime(path) + 1 < started:
        out.append("%s wasn't written by this run (it's older than the command's start)" % shown)
    if kind == "triage":
        if not any(norm(line) == norm(TRIAGE_HEADER) for line in text.split("\n")):
            out.append("%s has no contract table (header `%s`)" % (shown, TRIAGE_HEADER))
        elif not TRIAGE_ROW_RE.search(text):
            out.append("%s has a contract table with no `| C1 |` row" % shown)
        out.extend(plan_check_problems(project, ticket))
    elif kind == "operate":
        lines = FINGERPRINT_LINE_RE.findall(text)
        if fp_before is not None and len(lines) <= fp_before:
            out.append("%s has no new Self-review block since this /operate started" % shown)
        elif not lines or not OPERATE_RE.match(lines[-1].strip()):  # the last Fingerprint: line is the record
            out.append("%s: its last `Fingerprint:` line isn't `Fingerprint: <64-hex>` (take it with node "
                       ".claude/scripts/kit-tools.mjs fingerprint)" % shown)
        out.extend(inventory_problems(project, ticket, text))
    elif kind == "post-op":
        fps, results = FINGERPRINT_LINE_RE.findall(text), RESULT_LINE_RE.findall(text)
        # the closing lines are the record: the last of each
        if not fps or not POSTOP_FP_RE.match(fps[-1].strip()):
            out.append("%s: its last `Fingerprint:` line isn't `Fingerprint: <64-hex>` (or `none (no reviewable "
                       "change)`)" % shown)
        if not results or not POSTOP_RESULT_RE.match(results[-1].strip()):
            out.append("%s: its last `Result:` line isn't `Result: clean` or `escalate` (there is no `capped` end "
                       "state: post-op round rule 6)" % shown)
    elif kind == "handoff":
        section = text.split("## Git state", 1)[1].split("\n## ", 1)[0] if "## Git state" in text else ""
        if not HANDOFF_BRANCH_RE.search(section):
            out.append("%s has no `## Git state` section with a `Branch:` line" % shown)
    return out


def rename(src, dst):
    """Rename a marker to its next state. An earlier marker of that name is kept: the new one gets a time suffix."""
    if os.path.exists(dst):
        dst = "%s.%d" % (dst, int(time.time() * 1000))
    try:
        os.rename(src, dst)
    except OSError:
        pass


# ---------------------------------------------------------------- modes

def cmd_start(project, kind, ticket):
    d = marker_dir(project, kind, ticket)
    os.makedirs(d, exist_ok=True)
    marker = os.path.join(d, ".started-" + kind)
    if os.path.exists(marker):  # an earlier run never finished: keep its marker, under its own name
        rename(marker, os.path.join(d, ".abandoned-" + kind))
    extra = ""
    if kind == "operate":  # remember how many Self-review blocks exist, so the check needs a new one
        try:
            with open(record_path(project, kind, ticket), encoding="utf-8", errors="replace") as fh:
                extra = " fp=%d" % len(FINGERPRINT_LINE_RE.findall(fh.read()))
        except OSError:
            extra = " fp=0"
    with open(marker, "w", encoding="utf-8") as fh:
        fh.write("%f%s\n" % (time.time(), extra))
    print("check-record: /%s started%s." % (kind, "" if kind == "handoff" else " for " + ticket))
    return 0


def cmd_cancel(project, kind, ticket):
    marker = os.path.join(marker_dir(project, kind, ticket), ".started-" + kind)
    if os.path.exists(marker):
        rename(marker, os.path.join(os.path.dirname(marker), ".cancelled-" + kind))
    print("check-record: /%s closed without a record (stopped on purpose)." % kind)
    return 0


def cmd_check(project, kind, ticket):
    marker = os.path.join(marker_dir(project, kind, ticket), ".started-" + kind)
    started = read_started(marker) if os.path.exists(marker) else None
    found = problems(project, kind, ticket, started,
                     fingerprints_at_start(marker) if os.path.exists(marker) else None)
    if found:
        print("check-record: the /%s record is incomplete:" % kind)
        for p in found:
            print("  - " + p)
        print("Fix it, then run this check again.")
        return 1
    if os.path.exists(marker):
        rename(marker, os.path.join(os.path.dirname(marker), ".checked-" + kind))
    print("check-record: the /%s record is complete." % kind)
    return 0


def cmd_stop(event):
    if event.get("stop_hook_active") or kit_facts is None:
        return 0  # one nudge only; never a loop
    # Filesystem only until a marker turns up: an ordinary turn costs a couple of directory lookups, no git.
    found_markers = [(d, m) for d in kit_facts.state_dirs(event.get("cwd")) for m in kit_facts.open_markers(d)]
    if not found_markers:
        return 0
    now = time.time()
    messages = []
    currents = {}
    for state, (kind, ticket, marker) in found_markers:
        project = os.path.dirname(os.path.dirname(state))
        if project not in currents:
            currents[project] = ticket_from_branch(project)
        current = currents[project]
        if current and ticket is not None and ticket.upper() != current.upper():
            continue  # another ticket's run: session-context lists it, this turn isn't about it
        started, nudged = read_marker(marker)
        if started is None:
            continue
        found = problems(project, kind, ticket, started, fingerprints_at_start(marker))
        if not found:
            rename(marker, os.path.join(os.path.dirname(marker), ".checked-" + kind))
            continue
        if now - started > STALE_SECONDS:
            rename(marker, os.path.join(os.path.dirname(marker), ".abandoned-" + kind))
            continue
        if nudged:
            continue  # said once already; the command may be waiting on a review or the owner
        try:
            st = os.stat(marker)
            with open(marker, "a", encoding="utf-8") as fh:
                fh.write(" %s\n" % NUDGED)
            os.utime(marker, (st.st_atime, st.st_mtime))  # keep the start time for the 24 h close
        except OSError:
            continue  # can't record the nudge, so don't send it: it could never stop repeating
        suffix = "" if ticket is None else " --ticket " + ticket
        messages.append(
            "/%s%s started but its record is incomplete: %s. If the command is finished, complete the record and "
            "run `python3 .claude/hooks/check-record.py --kind %s%s`. If it is waiting (a background review, the "
            "owner's answer), just say so and stop: this reminder won't repeat. If it stopped early on purpose, run "
            "`python3 .claude/hooks/check-record.py --cancel %s%s`. Never write a record you haven't earned."
            % (kind, "" if ticket is None else " for " + ticket, "; ".join(found), kind, suffix, kind, suffix))
    if messages:
        sys.stderr.write("Record check: " + " ".join(messages) + "\n")
        return 2
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="agent-kit record checks")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--start", choices=KINDS)
    mode.add_argument("--kind", choices=KINDS)
    mode.add_argument("--cancel", choices=KINDS)
    mode.add_argument("--stop", action="store_true")
    mode.add_argument("--show", choices=("plan-check", "inventory"))
    ap.add_argument("--ticket")
    args = ap.parse_args(argv)

    if args.stop:
        try:
            raw = sys.stdin.read()
            event = json.loads(raw) if raw.strip() else {}
            return cmd_stop(event)
        except Exception as exc:  # fail open on anything unexpected
            sys.stderr.write("check-record: could not check records (%s); allowing the stop.\n" % type(exc).__name__)
            return 0

    project = project_dir()
    kind = args.start or args.kind or args.cancel or args.show
    ticket = None
    if kind != "handoff":
        ticket = (args.ticket or ticket_from_branch(project) or "").upper()
        if not ticket or not TICKET_RE.match(ticket):
            print("check-record: no ticket (pass --ticket <ticket>, or run on a ticket branch); nothing checked.")
            return 0
    if args.start:
        try:
            return cmd_start(project, kind, ticket)
        except OSError as exc:
            print("check-record: couldn't write the start marker (%s); continuing without it." % type(exc).__name__)
            return 0
    if args.cancel:
        return cmd_cancel(project, kind, ticket)
    if args.show:
        return cmd_show(project, kind, ticket)
    return cmd_check(project, kind, ticket)


if __name__ == "__main__":
    sys.exit(main())
