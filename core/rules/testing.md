---
paths:
  - "**/*.test.*"
  - "**/*.spec.*"
  - "**/*_test.*"
  - "**/test_*.py"
  - "**/conftest.py"
  - "**/__tests__/**"
  - "**/__mocks__/**"
  - "**/test/**"
  - "**/tests/**"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

# Testing Rules

Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`. Packs add framework notes: see
each installed `.claude/packs/*.md`.

## Every change gets tests

- Tests are required for every ticket, even when it doesn't mention them.
- Find the existing tests first and follow their framework, naming, assertions and mocking. Where none exist, cover at
  least the happy path and each error path, next to the source.
- A regression fix is demonstrated: show the test failing without the fix, then passing with it.
- A test that still passes with the guard or fix deleted proves nothing. Mutation-test it: break the code on purpose
  and watch the test go red.

## Running the suite

- Run `<TEST_COMMANDS>` exactly as written. Never a hand-picked subset or an ad-hoc script that "checks the same
  thing"; substitutes hide reds.
- Take the test count from the runner's own output, not from a doc. Never fabricate or round up green output, and
  never report a subset as the suite.
- A green runner doesn't mean the code compiles: run `<TYPECHECK_COMMAND>` or `<SYNTAX_CHECK_COMMAND>` where set,
  before committing test files too.
- A green CI run that is really a skip hides breakage. Check the job actually ran.

## Isolation

- Tests run with no network and no production access. The runner may load env, so stub every client, or a test hits
  real services.
- Mocks match the real module: the same exports and the same return shapes. A mocked call can't prove what happens on
  the other side of it.
- Reset mock state between tests, including queued one-shot return values.
- Temp files go in a temp dir made with the language's own call (`fs.mkdtemp`, `tempfile.TemporaryDirectory`), never
  removed by shelling out.
- Rows a verification run writes carry `<SYNTHETIC_MARKER>`; teardown deletes by explicit IDs, never by pattern.

## Green is not behaviour

- A green suite checks logic, not the live surface. A behaviour change also climbs the verification ladder in
  `CLAUDE.kit.md` (dry-run, read the stored result, real run with logs, `/verify`).
- Never test in production anything with an irreversible side effect; `docs/agent/verify-map.md` lists them and the
  safe entry points.
- If you can't verify a path, say so and record it as an unverified gap.
