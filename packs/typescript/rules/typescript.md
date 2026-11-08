---
paths:
  - "**/*.{ts,tsx}"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

# TypeScript

Installed by the typescript pack. Follow the codebase's existing conventions first; these fill the gaps.

- **Request handlers** (Express-style) are `async (req: Request, res: Response): Promise<void>`. They send the
  response; they don't return it. Every handler uses the project's one response envelope, for example
  `{ success: boolean, data?: T, error?: string }`. Never add a second shape.
- **`catch (error: unknown)`** in new code, then narrow before reading it:
  `error instanceof Error ? error.message : String(error)`. Don't rewrite catch clauses you aren't otherwise
  changing.
- **No `any` in new code**, tests included. Use `unknown` and narrow. A cast (`as T`) belongs only at a boundary that
  has just validated the value.
- **Static types and runtime validation agree.** Derive the type from the validator's schema, or validate into the
  declared type. A type alone checks nothing at run time.
- **Type-check before committing**, test files included: `tsc --noEmit` in the package. A passing test run doesn't
  prove the code compiles. After each edit, a hook type-checks the packages listed in `.claude/packs/typescript.md`;
  fix what it reports before moving on.
