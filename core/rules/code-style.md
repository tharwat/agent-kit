---
paths:
  - "**/*.{ts,tsx,js,jsx,mjs,cjs,py,rb,go,rs,java,kt,swift,php,cs,sh}"
  - "**/*.{html,css,scss,vue,svelte}"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

# Code Style & Conventions

Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`. Follow the codebase's existing
conventions first; these rules fill the gaps. Packs may add checks here: see each installed `.claude/packs/*.md`.

## Language and copy

- Code, logs and comments in English. User-facing copy in `<UI_LANGUAGE>`, following `docs/agent/copy-rules.md`.
- URLs are always fully qualified with `https://`. A bare domain is not a clickable link in most email clients and
  apps.

## Logging

- Every log line starts with the file's name or path and ` -- `, then `[Context] message`, so one grep in
  `<LOG_SINK>` finds every line from that file.
- When you touch a file that predates the prefix, add it to the lines you change. Don't reformat untouched lines.
- No PII or secrets in logs (`.claude/rules/security.md`).

## Error handling: fail loud, never fail open

- **Handlers throw, never log-and-continue.** Check every query's error, counts and secondary lookups included, and
  throw so the outer catch returns a 5xx. A success response with missing fields is worse than an error, because the
  caller can't tell it from a real success.
- **Background delivery failures throw** after the last retry, so the scheduler records a failure instead of a
  success where nothing was sent.
- **Idempotency reads check their own error.** If reading "already sent / processed" state fails, abort. A read
  error is never "nothing sent yet"; treating it so double-sends.
- **Side effects run after the atomic operation succeeds** (audit logs, notifications, cleanup), never before it.
- **Post-commit cleanup is best-effort:** wrap it in try/catch and log, so it can't fail an operation that has
  already committed.
- **Deletes and cleanup** are scoped to the records actually deleted, and cover every identifier column the
  matching write path writes.
- **Reference targets must exist at write time.** A write that points at a just-deleted row fails; store a null
  reference and carry the identity in the payload.

## Data and logic

- **Counts come from a count query or a stored counter**, never the length of a display list that has a limit.
- **Parse and normalize at the boundary**, in one testable helper. Both sides of a comparison normalize the same way,
  and a value that decides something is stored in the form it is compared in.
- **Bound every scan** over input an operator or user controls; no unbounded patterns over it.
- **Renames are complete.** Grep for the old term before committing: labels, tooltips, accessibility text, comments,
  config keys, docs, test assertions. A field name is API contract (`.claude/rules/api-contracts.md`).
- **One of N sibling call sites left on the old pattern** is the most common miss. Find every sibling
  (`docs/agent/sibling-paths.md`) and change them together.

## UI state

- An action that depends on an in-flight check is disabled while the check is pending: track an explicit pending
  state.
- When a request nonce guards `.then()` against stale responses, `.finally()` checks the same nonce before clearing
  loading state.
- A state change reaches every effect that reads it; check their order.
