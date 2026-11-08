---
paths:
  - "**/{api,apis,routes,controllers,handlers,endpoints,server}/**"
  - "**/{openapi,swagger}*.{yaml,yml,json}"
  - "**/{package.json,requirements*.txt,pyproject.toml,go.mod,Cargo.toml,Gemfile}"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

# API Contracts & Dependencies

Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`. These globs are generic; a project may
narrow them to the API and client directories in `docs/agent/source-layout.md`.

## Always additive

Clients depend on exact contracts: URLs, methods, response shapes, field names, status codes and required parameters.

- Existing fields, URLs and status codes are **never removed or changed**.
- Add new endpoints at new URLs, and new fields as optional.
- A breaking change ships as a new route (for example a versioned one), or keeps the old shape working beside the new
  one. Explaining that old clients will break is not compatibility.
- Installed or cached clients may not update; treat every released client as live.

## When a contract changes

In the same change:

1. Update the types, schemas and API spec.
2. Update every consumer in `docs/agent/source-layout.md`. Grep for the path; don't assume.
3. Keep old clients working, and record on the ticket which consumers and versions you checked.
4. Update docs per `docs/agent/docs-map.md`.

A contract change is a Critical Systems change when the API is in `<CRITICAL_SYSTEMS>`.

## External contracts

- Use only endpoints and fields confirmed this session against live docs or a real payload. A vendor field not
  confirmed this session is UNVERIFIED.
- Inbound webhook shapes are external contracts too. Confirm the real payload, and handle an unknown or missing
  field explicitly.
- When a call fails, read the actual error body before proposing a fix.

## Endpoint behaviour

- Every new endpoint logs request start, success and failure, with the file prefix and identifiers masked
  (`.claude/rules/code-style.md`).
- Errors use the project's existing envelope: 4xx for client errors, 5xx for server errors, no stack traces.
- A field the handler reads is declared in the input validator, or the validator may strip it.

## Dependencies and refactors

- A new dependency is allowed only as `<DEPENDENCY_POLICY>` says (Forbidden actions, `CLAUDE.kit.md`). Check
  built-ins and existing helpers first, and record why on the ticket or PR.
- Pin third-party versions: an unpinned install can change behaviour with no change in the repo.
- No broad refactors, renames or file moves unless asked.
