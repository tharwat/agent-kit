<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Security & Privacy Rules

Always loaded, for every file and task.

## Secrets

- Never commit, log or paste a secret anywhere. Name the env var, never the value.
- Gitignore a new secret-bearing file in the same change. A tracked secret file with no ignore rule is a blocker.
- Never select or print token columns, keys, or payloads that carry them.

## PII

- Never log the fields in `docs/agent/pii.md`, or full request/response payloads on production paths.
- Mask identifiers to their last 2–4 characters. When unsure whether something is sensitive, treat it as sensitive.
- Private files stay in private storage, reached only through short-lived signed URLs. Making data client-readable
  is G6.

## Inputs and entry points

- Parameterized queries only; never build query strings from input.
- Validate every input at the boundary, in one shared validator. A field the handler reads must be declared there.
- A guard on one input path covers every sibling path into the same downstream (LLM call, search, query); a guard
  on one path only is a bypass.
- Every path to a critical gate enforces it. Nav guards are UI only: each route enforces the same rule as its nav item.
- Never remove or bypass rate limiting.

## Webhooks and outbound calls

- Verify a webhook's signature (constant-time compare) before using its body. A mismatch is 401/403 and dropped,
  never "process and log". How each one is signed: `docs/agent/integrations.md`.
- A server-side fetch of a user- or scraper-supplied URL goes through one shared SSRF guard: resolve the host, reject
  private, loopback, link-local and mapped addresses, follow no redirects automatically, and cap type and size.

## Output

- LLM output rendered as HTML is sanitized against a tag allowlist, and any allowed tag carrying an attribute is
  rejected. Log a warning when stripping happens.
- Paginated results and their filter metadata use the same scope predicate.
- No stack traces or internal detail to clients; 4xx for client errors, 5xx for server errors. Classify provider
  failures (quota, rate limit, bad key) in your own words; never echo the provider's text.

Packs may add checks here: see each installed `.claude/packs/*.md`.
