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
| triage   | .claude/state/<T>/triage.md         | the contract table header and at least one `| C<n> |` row;     |
|          |                                     | the state-homes table (or `State homes: none — <reason>`), and  |
|          |                                     | `Contradiction check:` and `Lifecycle check:` lines             |
| operate  | .claude/state/<T>/self-review.md    | a `Fingerprint: <64-hex>` line, and an `Inventory: <heading>`   |
|          | + .claude/state/<T>/inventory.md    | line naming a `## <heading>` section of inventory.md that holds |
|          |                                     | Table 1a with rows (writers/readers as file:line or `none`, a   |
|          |                                     | Search cell) and Table 1b                                       |
| post-op  | .claude/state/<T>/post-op.md        | `Fingerprint: <64-hex or none (no reviewable change)>` and      |
|          |                                     | `Result: clean or escalate` (`capped` is gone since 1.8.0)      |
| handoff  | .claude/handoffs/latest.md          | written after the start, with the `## Git state` / `Branch:` block |

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
STATE_HOMES_HEADER = "| Fact | Its one home | Who writes it | Who reads it | Second home? |"
STATE_HOMES_NONE_RE = re.compile(r"^State homes:\s*none\s*[—-]\s*\S", re.M)
CHECK_LINE_RE = {name: re.compile(r"^%s:\s*\S" % name, re.M) for name in ("Contradiction check", "Lifecycle check")}
INVENTORY_1A = ("| Value changed | How it changes | Writers (file:line) | Readers (file:line) | What each reader assumes | "
                "Needs a change? | Search |")
INVENTORY_1B = "| New behaviour | Existing sibling (file:line) | Guards the sibling has | Copied? |"
INVENTORY_LINE_RE = re.compile(r"^Inventory:[ \t]*(.*)$", re.M)
FILE_LINE_RE = re.compile(r"[^\s|`]+:[0-9]+")


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


def table_rows(text, header):
    """The data rows (lists of cells) under every copy of `header` in `text`; separator rows are skipped."""
    rows, inside = [], False
    for line in text.split("\n"):
        if norm(line) == norm(header):
            inside = True
            continue
        if not inside:
            continue
        if not line.strip().startswith("|"):
            inside = False
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c):
            continue
        rows.append(cells)
    return rows


def evidenced(cell):
    """A writer/reader cell is backed by a `file:line` or says `none`."""
    return bool(FILE_LINE_RE.search(cell)) or cell.lower().startswith("none")


def inventory_problems(project, ticket, self_review):
    """The dependency inventory /operate writes before its first production edit (operate Phase 1 step 2)."""
    path = os.path.join(ticket_dir(project, ticket), "inventory.md")
    shown = rel(project, path)
    blocks = self_review.split("Self-review:")
    heading_m = INVENTORY_LINE_RE.findall(blocks[-1]) if len(blocks) > 1 else INVENTORY_LINE_RE.findall(self_review)
    heading = heading_m[-1].strip() if heading_m else ""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return ["%s doesn't exist (the dependency inventory comes before the first production edit)" % shown]
    if not heading:
        return ["the last Self-review block has no `Inventory: <heading>` line naming the inventory.md section it "
                "covers (Plan, or Fix batch <n>)"]
    sections = {}
    for part in re.split(r"^## ", text, flags=re.M)[1:]:
        title, _, body = part.partition("\n")
        sections[norm(title)] = body
    body = sections.get(norm(heading))
    if body is None:
        return ["%s has no `## %s` section (named by the Self-review `Inventory:` line)" % (shown, heading)]
    out = []
    if not any(norm(line) == norm(INVENTORY_1A) for line in body.split("\n")):
        out.append("%s `## %s` has no Table 1a (header `%s`)" % (shown, heading, INVENTORY_1A))
    else:
        rows = table_rows(body, INVENTORY_1A)
        if not rows:
            out.append("%s `## %s` Table 1a has no rows (write `none` with the search that showed it)" % (shown, heading))
        for cells in rows:
            cells = (cells + [""] * 7)[:7]
            name = cells[0] or "(unnamed row)"
            if not cells[0].lower().startswith("none") and not (evidenced(cells[2]) and evidenced(cells[3])):
                out.append("%s Table 1a row `%s`: every writer and reader needs a file:line (or `none`)" % (shown, name))
            if not cells[6]:
                out.append("%s Table 1a row `%s` has no Search command" % (shown, name))
    if heading.lower() == "plan" and not any(norm(line) == norm(INVENTORY_1B) for line in body.split("\n")):
        out.append("%s `## Plan` has no Table 1b (header `%s`)" % (shown, INVENTORY_1B))
    for cells in table_rows(body, INVENTORY_1B):
        cells = (cells + [""] * 4)[:4]
        if not cells[0].lower().startswith("none") and not evidenced(cells[1]):
            out.append("%s Table 1b row `%s`: the sibling needs a file:line (or `none`)" % (shown, cells[0] or "?"))
    return out


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
        if not (any(norm(line) == norm(STATE_HOMES_HEADER) for line in text.split("\n"))
                or STATE_HOMES_NONE_RE.search(text)):
            out.append("%s has no state-homes table (header `%s`, or `State homes: none — <reason>`)"
                       % (shown, STATE_HOMES_HEADER))
        for name, pattern in CHECK_LINE_RE.items():
            if not pattern.search(text):
                out.append("%s has no `%s:` line (triage Step 4.8)" % (shown, name))
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
    kind = args.start or args.kind or args.cancel
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
    return cmd_check(project, kind, ticket)


if __name__ == "__main__":
    sys.exit(main())
