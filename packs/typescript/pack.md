<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Pack: typescript

Core commands read the matching section below at their "Packs may add …" lines. Values written `<LIKE_THIS>` in
this file come from the Pack facts table; the `.claude/hooks/typecheck.sh` hook reads the same table.

## Pack facts

| Fact | Value | Meaning |
|---|---|---|
| `TS_PACKAGE_DIRS` | {{TS_PACKAGE_DIRS}} | Dirs (from the repo root, comma-separated; `.` is the root) the edit hook type-checks. `auto`: every dir holding a `tsconfig.json`, up to depth 2 |
| `TEST_FRAMEWORK` | {{TEST_FRAMEWORK}} | `vitest`, `jest`, or `none` (no runner yet) |

**`<TEST_FRAMEWORK>` is `none`:** there is no runner yet. Tests are plain `.ts` or `.mjs` scripts using `node:test`
and `node:assert`, run by a `<TEST_COMMANDS>` line (`.ts` needs a runtime that strips types, or a compile step).
The vitest/jest items below don't apply; type-checking and "no `any`" still do. A row such a script can't drive is
`BLOCKED — no test runner` (core `/operate` Phase 1.5).

## /test

At Step 4 (run the suite), and while writing tests in Step 3:

- **Type-check before committing tests.** Run `tsc --noEmit` in every package in `<TS_PACKAGE_DIRS>` whose files
  changed, tests included. A green test run doesn't prove the code compiles: vitest, and jest with a
  transpile-only transform, strip types without checking them.
- **Import the test API explicitly.** vitest: `import { describe, it, expect, vi, beforeEach } from 'vitest'`. jest:
  `import { jest, describe, it, expect } from '@jest/globals'`. The runner's `globals` option doesn't reach `tsc`,
  so a file relying on it fails the type check.
- **Mocks referenced inside a mock factory.** `vi.mock` / `jest.mock` calls are hoisted above the imports, so a
  plain top-level `const` used in the factory is not yet initialized. vitest: declare those with `vi.hoisted()`.
  jest: name them `mock…` and only read them lazily inside the factory's functions.
- **No `any` in new tests.** Type doubles with `vi.mocked(fn)` / `jest.mocked(fn)`, so a wrong return shape fails
  `tsc`. For fixtures use the real type, `Partial<T>` or `satisfies T`. `as any` and `as unknown as T` switch off the
  check that keeps a double honest.
- **Reset between tests.** `clearAllMocks` clears call history only; queued `mockReturnValueOnce` values and
  implementations survive it. Use `resetAllMocks`, or set every return value again in `beforeEach`.

## /post-op

Mock Fidelity (gate 8), in `<TEST_FRAMEWORK>` syntax (with `none`: for every hand-written double, apply checks A and C
to whatever replaces the real module):

- **Check A, shape.** For each `vi.mock('<path>', factory)` / `jest.mock('<path>', factory)`, open the real module
  and compare: every key the factory returns is a real export, and every export the code under test calls is
  present. A default export needs a `default:` key in an ESM factory. A partial mock spreads the real module
  (`await importOriginal()` in vitest, `jest.requireActual('<path>')` in jest) and overrides only what it must.
- **Check C, return values.** Each `mockReturnValue`, `mockResolvedValue`, `mockRejectedValue` and
  `mockImplementation` returns what the real function's declared return type says: the same wrapper object, the
  same optional fields, a rejection where the real one throws. Prefer `vi.mocked(realFn).mockResolvedValue(...)`
  so `tsc` checks it. A cast on the value (`as any`, `as never`, `as unknown as T`) is a finding.

## bteam lenses

Take the next free lens number.

- **Mock fidelity (`vi.mock` / `jest.mock`).** For every test double in the diff: do the factory's keys match the
  real module's exports, including `default`? Does each mocked return value match the real function's return type,
  without a cast? Is a module mocked whole where the code under test also needs a real export (partial mock
  missing)? Does a test pass only because a mocked value from an earlier test leaked through (`mockReturnValueOnce`
  left queued, no reset)? A test that is green against a double the real module can't produce proves nothing.

## operate lenses

- **Mock fidelity (`vi.mock` / `jest.mock`).** Before `/post-op`, open the real module behind every double you wrote
  or changed. Match the factory's keys to its exports (`default` included) and each mocked value to the real return
  type, through `vi.mocked` / `jest.mocked`, with no casts. Run `tsc --noEmit` on the test files.

## /api-contract

Request/response type coverage, for every route or handler the diff adds or changes:

- The request body, query and params have a declared type **and** a runtime validator, and the two agree: derive
  the type from the schema (`z.infer<typeof schema>` or the validator's equivalent), or validate into the declared
  type. A static type alone validates nothing at run time.
- The response is typed with the project's one response envelope. No `any` or untyped `res.json(...)` payload.
- A field that becomes optional, changes type or is removed is a contract change: find every client package that
  imports the type and run `tsc --noEmit` in each package in `<TS_PACKAGE_DIRS>` that does.
- Shared request/response types live in one place that clients import; a hand-copied duplicate in a client is a
  finding.

## /triage

Type-system ripple (Step 4.5 C), TypeScript specifics:

- A changed exported type, interface, enum or union: grep every importer, including `import type`, re-exports
  through barrel `index.ts` files and declaration merging. Each importing package in `<TS_PACKAGE_DIRS>` is in the
  blast radius and gets its own `tsc --noEmit`.
- A union or enum gaining a member: every `switch` with an exhaustive `never` check, every `Record<Union, …>`
  literal and every lookup table must gain the case.
- An array becoming `as const` (readonly): `.includes()` with a wider string type no longer compiles, and passing it
  to a mutable-array parameter fails. Find the call sites.
- A value's type widening or narrowing (`string` → literal union, optional → required): find the casts and `!`
  assertions that hid the old shape, since they hide the new one too.

## /security

At Step 8 (pack checks): **dependency vulnerability audit.** If both the node-esm and typescript packs are installed,
run it once.

1. Find every JavaScript lockfile in the repo (`git ls-files` for `package-lock.json`, `npm-shrinkwrap.json`,
   `pnpm-lock.yaml`, `yarn.lock`, `bun.lock*`), not only those under `<TEST_COMMANDS>` dirs. A workspace keeps one at
   its root. Run each lockfile's audit once, in its dir. The package manager is the one `package.json`
   `packageManager` names. Without that field, it is the one whose lockfile is there; if a dir holds several, audit
   each and say which is stale.

   | Lockfile | Command |
   |---|---|
   | `package-lock.json` or `npm-shrinkwrap.json` | `npm audit --omit=dev --json` |
   | `pnpm-lock.yaml` | `pnpm audit --prod --json` |
   | `yarn.lock`, Yarn 1 (`packageManager: yarn@1…`, or no `.yarnrc.yml` and no `packageManager`) | `yarn audit --groups dependencies --json` |
   | `yarn.lock`, Yarn 2+ (`packageManager: yarn@2…` or later, or a `.yarnrc.yml`) | `yarn npm audit --all --recursive --environment production --json` |
   | none, or only `bun.lock` / `bun.lockb` | none: report `Dependency audit: not run (no supported lockfile)` |

2. For each advisory, record the package, severity, whether it is **direct** (in `package.json`) or **transitive**
   (and through which direct dependency), and whether a fixed version exists.
3. **Severity.** A `critical` or `high` advisory in a runtime dependency whose vulnerable code this project can reach
   is **S2**. Everything else, including dev-only and unreachable advisories, is `noted` with the reason.
4. **Which S2s this ticket fixes.** An S2 is a **must-fix** finding of this ticket when this ticket brought it in or
   newly reaches it: the lockfile diff (`git diff origin/<MAIN_BRANCH>...HEAD -- <lockfile>`) adds the vulnerable
   package or changes it to a vulnerable version, or the code diff adds a call into the vulnerable function or module
   the advisory names. Fix it by upgrading the dependency (a dependency change under `<DEPENDENCY_POLICY>`; say why in
   the PR). An advisory already on `<MAIN_BRANCH>` that this diff doesn't newly reach is not on this ticket's path:
   its class here is `noted`, not S2, so it doesn't block this ticket. `/release` still blocks on it as S2.
   - **Report it** on the `Pack checks:` line as `⚠️ pre-existing: <package> <advisory id> (noted)`. A ❌ there is only
     for an S2 this ticket must fix. A pre-existing ⚠️ alone leaves the `/security` verdict ✅ CLEAR and the post-op
     Security gate Pass: there is nothing to fix or re-run.
   - **File it:** post one ticket op **comment** `<ticket>` whose first line is
     `Noted for the tracker (security <date>)`, listing each pre-existing advisory, and every other advisory step 3
     marked `noted`, with package, severity, advisory id and fixed version. `/ship` files it on `<OPEN_ITEMS_TICKET>` with the other noted findings. Leave out an
     advisory `<OPEN_ITEMS_TICKET>` already lists.
5. **Never run `npm audit fix`** (or `pnpm` / `yarn` equivalents). It rewrites the lockfile, which is a dependency
   change you must make on purpose.
6. **Exit codes.** These commands exit non-zero when they *find* advisories: a non-zero exit with JSON advisories in
   the output is a result, not an error. Only when there is no parseable JSON (offline, a registry error, a retired
   audit endpoint, a missing lockfile) report `Dependency audit: not run (<reason>)`. That, or an empty answer, is
   never a pass.

## /release

At Step 6: run the `/security` dependency audit above on the release commit. An open S2 advisory blocks the release
until it is fixed or the owner accepts it.
