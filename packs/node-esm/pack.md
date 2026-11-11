<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Pack: node-esm

Core commands read the matching section below at their "Packs may add …" lines. This pack has no facts of its own.

## /test

At Step 4 (run the suite):

- **Syntax check.** For `.mjs` and `.js` files there is no compiler, so run `<SYNTAX_CHECK_COMMAND>` (normally
  `node --check <file>`) on every changed file. `node --check` parses only: a wrong import path, a missing named
  export or a misspelled `node:` module fails only when the module loads. So every changed module must be imported
  by at least one test that the suite runs.
- **`node --test`.** Run the project's `<TEST_COMMANDS>` line, never a hand-picked `node --test <file>` subset. Take
  the counts from the runner's own summary. Node's default reporter prints `ℹ tests N`, `ℹ pass N` and `ℹ fail N`;
  the TAP reporter (`--test-reporter=tap`) prints `# tests N` instead. A non-zero exit is a red suite even when the
  visible tail looks green.
- **Writing tests for `node:test`.** Use `node:test` and `node:assert/strict`. Put test files where the project already
  keeps them (a `test/` folder, or co-located `*.test.mjs`) and match their naming; never impose a layout. Stub
  clients with `mock.method()` or the test context's `t.mock`, which restores itself after the test. Module mocking
  (`mock.module`) is experimental and needs a flag on most Node versions: prefer injecting the dependency.
- **What `node --test` can't load.** It parses no JSX and has no bundler, so a test that imports a `.jsx` file or
  anything reading `import.meta.env` fails the whole file. Keep such tests on the bundler's own runner, or test a pure
  helper module instead.

## /security

At Step 8 (pack checks): **dependency vulnerability audit.** If both the node-esm and typescript packs are installed,
run it once.

1. Pick the command from the lockfile in each package dir from `<TEST_COMMANDS>`:

   | Lockfile | Command |
   |---|---|
   | `package-lock.json` (or none) | `npm audit --omit=dev --json` |
   | `pnpm-lock.yaml` | `pnpm audit --prod --json` |
   | `yarn.lock`, Yarn 1 | `yarn audit --groups dependencies --json` |
   | `yarn.lock`, Yarn 2+ | `yarn npm audit --environment production --json` |

2. For each advisory, record the package, severity, whether it is **direct** (in `package.json`) or **transitive**
   (and through which direct dependency), and whether a fixed version exists.
3. **Severity.** A `critical` or `high` advisory in a runtime dependency whose vulnerable code this project can reach
   is **S2 must-fix**: upgrade the dependency (a dependency change under `<DEPENDENCY_POLICY>`; say why in the PR).
   Everything else, including dev-only and unreachable advisories, is `noted` with the reason.
4. **Never run `npm audit fix`** (or `pnpm` / `yarn` equivalents). It rewrites the lockfile, which is a dependency
   change you must make on purpose.
5. The audit needs the network. If it can't reach the registry, report `Dependency audit: not run (offline)`. That is
   not a pass.

## /release

At Step 6: run the `/security` dependency audit above on the release commit. An open S2 advisory blocks the release
until it is fixed or the owner accepts it.
