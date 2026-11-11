#!/usr/bin/env python3
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
"""Record checks: a workflow command can't end its turn while the record it must leave is missing or malformed.

  --start <kind> [--ticket <T>]  First step of /triage, /operate, /post-op, /handoff. Writes the start marker
                                 `.claude/state/<T>/.started-<kind>` (`.claude/state/.started-handoff` for handoff).
  --kind <kind> [--ticket <T>]   Last step of the command (Claude and Codex). Checks the record; exit 0 when it's
                                 complete (the marker is renamed `.checked-<kind>`, never deleted), exit 1 with
                                 what's missing.
  --stop                         The Stop hook. Acts only when a `.started-*` marker exists, meaning a command began
                                 and never passed its check: it runs that check and exits 2 with what's missing.
                                 One nudge only (`stop_hook_active` passes). A marker older than 24 h is renamed
                                 `.abandoned-<kind>` and reported once.

| kind     | record                              | must contain                                                    |
|----------|-------------------------------------|-----------------------------------------------------------------|
| triage   | .claude/state/<T>/triage.md         | the contract table header and at least one `| C<n> |` row      |
| operate  | .claude/state/<T>/self-review.md    | a `Fingerprint: <64-hex>` line                                  |
| post-op  | .claude/state/<T>/post-op.md        | `Fingerprint: <64-hex or none (no reviewable change)>` and      |
|          |                                     | `Result: clean, capped or escalate`                             |
| handoff  | .claude/handoffs/latest.md          | written after the start, with the `## Git state` / `Branch:` block |

The ticket comes from `--ticket`, else from the current `<BRANCH_PREFIX><ticket-lowercase>-<slug>` branch. With no
ticket the check can't run, and it fails open. Writes only under `.claude/state/`. No network.
"""

import argparse
import glob
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

KINDS = ("triage", "operate", "post-op", "handoff")
STALE_SECONDS = 24 * 3600
TICKET_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*-[0-9]+$")
TRIAGE_HEADER = ("| ID | Class | Invariant | Paths | Hostile case | Authority | Behavioral proof | Counterfactual | "
                 "Independent vector | Discharge |")
TRIAGE_ROW_RE = re.compile(r"^\|\s*C[0-9]+\s*\|", re.M)
HEX64 = r"[0-9a-f]{64}"
OPERATE_RE = re.compile(r"^Fingerprint:\s*%s\s*$" % HEX64, re.M)
POSTOP_FP_RE = re.compile(r"^Fingerprint:\s*(%s|none \(no reviewable change\))\s*$" % HEX64, re.M)
POSTOP_RESULT_RE = re.compile(r"^Result:\s*(clean|capped|escalate)\s*$", re.M)
HANDOFF_BRANCH_RE = re.compile(r"^Branch:\s*\S", re.M)


def norm(line):
    return re.sub(r"\s+", " ", line.strip())


# ---------------------------------------------------------------- paths

def project_dir(cwd=None):
    return os.environ.get("CLAUDE_PROJECT_DIR") or cwd or os.getcwd()


def state_dir(project):
    return os.path.join(project, ".claude", "state")


def ticket_from_branch(project):
    if kit_facts is None:
        return None
    facts = kit_facts.read_facts(project)
    return kit_facts.ticket_for_branch(kit_facts.current_branch(project), facts)


def marker_dir(project, kind, ticket):
    if kind == "handoff":
        return state_dir(project)
    return os.path.join(state_dir(project), ticket)


def record_path(project, kind, ticket):
    if kind == "handoff":
        return os.path.join(project, ".claude", "handoffs", "latest.md")
    name = {"triage": "triage.md", "operate": "self-review.md", "post-op": "post-op.md"}[kind]
    return os.path.join(state_dir(project), ticket, name)


def rel(project, path):
    return os.path.relpath(path, project).replace(os.sep, "/")


# ---------------------------------------------------------------- checks

def read_started(marker):
    try:
        with open(marker, encoding="utf-8") as fh:
            return float(fh.read().strip().split()[0])
    except (OSError, ValueError, IndexError):
        try:
            return os.path.getmtime(marker)
        except OSError:
            return None


def problems(project, kind, ticket, started=None):
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
    elif kind == "operate":
        if not OPERATE_RE.search(text):
            out.append("%s has no `Fingerprint: <64-hex>` line (take it with node .claude/scripts/kit-tools.mjs "
                       "fingerprint)" % shown)
    elif kind == "post-op":
        if not POSTOP_FP_RE.search(text):
            out.append("%s has no `Fingerprint: <64-hex>` (or `none (no reviewable change)`) line" % shown)
        if not POSTOP_RESULT_RE.search(text):
            out.append("%s has no `Result: clean | capped | escalate` line" % shown)
    elif kind == "handoff":
        if "## Git state" not in text or not HANDOFF_BRANCH_RE.search(text):
            out.append("%s has no `## Git state` section with a `Branch:` line" % shown)
    return out


def rename(src, dst):
    try:
        os.replace(src, dst)  # a rename: the marker is kept under its new name, never deleted
    except OSError:
        pass


# ---------------------------------------------------------------- modes

def cmd_start(project, kind, ticket):
    d = marker_dir(project, kind, ticket)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, ".started-" + kind), "w", encoding="utf-8") as fh:
        fh.write("%f\n" % time.time())
    print("check-record: /%s started%s." % (kind, "" if kind == "handoff" else " for " + ticket))
    return 0


def cmd_check(project, kind, ticket):
    marker = os.path.join(marker_dir(project, kind, ticket), ".started-" + kind)
    started = read_started(marker) if os.path.exists(marker) else None
    found = problems(project, kind, ticket, started)
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


def open_markers(project):
    """(kind, ticket or None, marker path) for every `.started-*` marker."""
    out = []
    base = state_dir(project)
    for path in sorted(glob.glob(os.path.join(base, ".started-*")) + glob.glob(os.path.join(base, "*", ".started-*"))):
        kind = os.path.basename(path)[len(".started-"):]
        if kind not in KINDS:
            continue
        parent = os.path.dirname(path)
        ticket = None if parent == base else os.path.basename(parent)
        if (kind == "handoff") != (ticket is None):
            continue
        out.append((kind, ticket, path))
    return out


def cmd_stop(project, event):
    if event.get("stop_hook_active"):
        return 0  # one nudge only; never a loop
    now = time.time()
    messages = []
    for kind, ticket, marker in open_markers(project):
        started = read_started(marker)
        if started is None:
            continue
        if now - started > STALE_SECONDS:
            rename(marker, os.path.join(os.path.dirname(marker), ".abandoned-" + kind))
            sys.stderr.write("check-record: an old /%s%s run never finished its record; marked abandoned.\n"
                             % (kind, "" if ticket is None else " for " + ticket))
            continue
        found = problems(project, kind, ticket, started)
        if not found:
            rename(marker, os.path.join(os.path.dirname(marker), ".checked-" + kind))
            continue
        how = "python3 .claude/hooks/check-record.py --kind %s%s" % (kind, "" if ticket is None else
                                                                     " --ticket " + ticket)
        messages.append("/%s%s started but its record is incomplete: %s. Finish the record, then run `%s`."
                        % (kind, "" if ticket is None else " for " + ticket, "; ".join(found), how))
    if messages:
        sys.stderr.write("Record check: " + " ".join(messages) + "\n")
        return 2
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="agent-kit record checks")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--start", choices=KINDS)
    mode.add_argument("--kind", choices=KINDS)
    mode.add_argument("--stop", action="store_true")
    ap.add_argument("--ticket")
    args = ap.parse_args(argv)

    if args.stop:
        try:
            raw = sys.stdin.read()
            event = json.loads(raw) if raw.strip() else {}
            return cmd_stop(project_dir(event.get("cwd")), event)
        except Exception as exc:  # fail open on anything unexpected
            sys.stderr.write("check-record: could not check records (%s); allowing the stop.\n" % type(exc).__name__)
            return 0

    project = project_dir()
    kind = args.start or args.kind
    ticket = None
    if kind != "handoff":
        ticket = args.ticket or ticket_from_branch(project)
        if not ticket or not TICKET_RE.match(ticket):
            print("check-record: no ticket (pass --ticket <ticket>, or run on a ticket branch); nothing checked.")
            return 0
    if args.start:
        return cmd_start(project, kind, ticket)
    return cmd_check(project, kind, ticket)


if __name__ == "__main__":
    sys.exit(main())
