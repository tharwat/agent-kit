<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Ticket ops

Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

Core commands never name a tracker's tools. They call six ticket ops. The installed ticket pack implements them in
its `.claude/rules/ticket-ops.md`. Commands write a call as: ticket op **get** `<ticket>` (comments and links
included).

## 1. Rules every pack enforces

1. **Never write a ticket key you didn't fetch or create.** A key may appear in a branch name, commit, PR, code
   comment, test, migration, doc or another ticket's comment only after a successful **get** of that key, or as the
   key a **create** returned, in this session. A key read from a branch name is confirmed with **get** before use.
   Never guess the next number: the tracker assigns it. Urgency is no exception; creating the ticket is one call.
   If a wrong key is already in merged history, don't rewrite `<MAIN_BRANCH>`: comment on the real ticket and point
   at the commit.
2. **No silent success.** Each op returns its result or fails with a one-line reason. "Not found" is a failure,
   never an empty ticket. A command never treats a failed op as done and never invents a result.
3. **No hard-coded tracker ids.** Transitions, statuses, issue types and users are looked up by name at run time.
4. **Status change and comment are separate calls.** No op passes a comment inside a transition.
5. **Unavailable tools.** If the pack's tools aren't available to the current agent (for example Codex without the
   tracker's server), the op fails and says so. The command reports it; it doesn't fall back to guessing.

## 2. The ops

| Op | Inputs | Returns |
|---|---|---|
| **get** | `key` | The ticket record below |
| **comment** | `key`, `body` (Markdown) | The new comment's id |
| **close** | `key`, optional `note` (Markdown) | The status after the transition, confirmed by a fresh **get** |
| **label** | `key`, `add[]`, `remove[]` | The label set after the change |
| **search** | filters: `labels[]` (all must match), `open` (true / false / any), optional `text`, optional `parent` | A list of `{key, title, status, open, labels}` |
| **create** | `type`, `title`, `body` (Markdown), optional `labels[]`, optional `parent` | The key the tracker assigned |

### get

Returns `key`, `title`, `description`, `type`, `status`, `open` (true/false), `labels`, `priority`, `parent`
(the epic or parent key, or none), `links` (each: key, relation, status), `subtasks` (each: key, status), and
**every** comment (each: id, author, created, body), oldest first. The pack pages through comments until all are
read. A partial comment list is a failure, because scope changes, decisions and record markers live in comments.

### comment

- Takes Markdown. The pack converts it to the tracker's format.
- The **first line survives verbatim**, because it may be a record marker (§3).
- If the tracker's renderer can lose characters (for example `+`, `[]`, `_`), the pack's file says so. Commands
  then keep the exact text in `.claude/state/<ticket>/` and treat the comment as a pointer, not the source.

### close

1. Fetch the ticket's available transitions.
2. Pick the one whose **target status name** equals the pack's closed-status name. Never use a stored transition
   id. If no transition matches, fail and list the available names.
3. Run the transition, status only.
4. If a `note` was given, post it as a separate **comment**.
5. **get** the ticket and return its status. A status that isn't closed is a failure.

### label

Read the current labels with **get**, apply `add` and `remove`, and write the whole set. Many trackers replace the
array on write, so sending only the new labels would drop the old ones. Returns the resulting set.

### search

Takes label and open/closed filters, plus optional free text and parent. The pack translates them to the tracker's
query language and handles its quirks (for example, no wildcards on labels). It returns all matches, paging as
needed.

### create

Before creating, **search** for an open ticket about the same thing. If one exists, comment there instead and use
its key. Otherwise create and use only the key the tracker returns. The pack fills required fields (project, issue
type looked up by name, parent link) from its own facts.

### reopen (optional)

Moves a closed ticket back to an open status, found by name like **close**, then comments why. A pack that can't
reopen says so in its op table. Callers then **create** a fix-forward ticket linked to the closed one instead.

## 3. Comment-as-record markers

Some comments are records that other commands read back. A record is a comment whose **first line** starts with the
marker. Text that only quotes a marker further down a comment is not a record. Before writing a marker, a command
does **get** and checks whether that exact record already exists, so a re-run doesn't write it twice.

| Marker (first line) | Written by | Read by |
|---|---|---|
| `TICKET ANALYSIS: <ticket> — <title>` | `/triage` (analysis + contract) | `/operate`, `/post-op` |
| `Pre-code vectors: <ticket>` | `/triage` | `/operate`, `/post-op` |
| `Verify: <ticket> — <verdict>` | `/verify` (one per run) | `/release`, `/ship` |
| `Post-merge: <ticket> — <result>` | `/ship` (the close note) | `/release` |
| `Self-review: <ticket>` | `/operate` Phase 3 (one per fix batch) | the owner and reviewers (audit trail); the local `self-review.md` is what `/post-op` checks |
| `Review round <n>: <ticket>` | `/post-op` (one per round) | `/post-op` (round count), `/ship` (open items) |
| `Noted for the tracker (peer review <date>)` | `/peer-review` | `/ship` (open items) |
| `Noted for the tracker (security <date>)` | `/security` (node-esm / typescript dependency audit) | `/ship` (open items) |
| `PEER_REVIEW: not run` / `PEER_REVIEW: CLEAN <hash>` / `PEER_REVIEW: UNRESOLVED <ids>` | `/peer-review` | `/ship` (when the local record is missing) |
| `Open items (PR #<N>): <OPEN_ITEMS_TICKET> comment <id>` or `Open items (PR #<N>): none` | `/ship` only | `/ship` (idempotency, and the start of the next PR's items) |

Packs add their own markers (for example a train pack's triage record, or `Mobile QA: <ticket> — <platform> —
<result>`) in a `## Markers` table in their `pack.md`, with the same columns. Core never edits this table at install.

## 4. How a pack maps the ops

The pack ships `.claude/rules/ticket-ops.md` with these sections, in this order:

1. **Tracker and facts.** The tracker name, the key pattern (a regex), the closed-status name, which statuses count
   as open, and the comment format the tracker stores. These are tier-2 pack facts.
2. **Op table.** One row per op: the tool or command that implements it, and its inputs.
3. **Per-op notes.** Paging, format conversion, characters the renderer loses, query-language quirks, rate limits.
4. **What Codex uses**, if it differs from Claude.

The six ops are the whole contract. A pack may add helpers, but core commands call only these six.

### Worked example: a fictional tracker, "Tasklog"

Tasklog has a CLI, `tl`, that prints JSON.

```markdown
# Ticket ops: Tasklog

## Tracker and facts
- Key pattern: `^<TICKET_PREFIX>-[0-9]+$`
- Closed status name: `Done`. Open statuses: `To do`, `In progress`, `In review`.
- Comments are stored as Markdown. The renderer keeps every character.

## Op table
| Op | Implementation |
|---|---|
| get | `tl show <key> --with comments,links,labels --json`; repeat with `--comment-page <n>` until `next_page` is null |
| comment | write the body to a scratch file, then `tl comment add <key> --file <file>`; returns `{id}` |
| close | `tl transitions <key> --json`; take the entry whose `to.name` is `Done`; `tl transition <key> --id <that id>`; then `comment` for any note; then `get` |
| label | `get`; compute the full set; `tl edit <key> --labels <comma-separated full set>` |
| search | `tl find --label <l> [--label <l2>] --state open|closed|any [--text <t>] [--parent <key>] --json --all` |
| create | `search` first; else `tl new --type Task --title <t> --file <body file> [--parent <key>] [--label <l>]`; the key is `.key` in the output |

## Per-op notes
- `tl transition` ignores `--comment`, so never pass one. Comment in a separate call.
- `tl find` matches labels exactly. There are no wildcards.

## What Codex uses
The same `tl` commands. Codex needs the `tl` login in its environment.
```
