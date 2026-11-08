---
paths:
  - "**/*.{mjs,js}"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

# Node.js ESM

Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`. Installed by the node-esm pack, for
`.mjs` files and `.js` files in a `"type": "module"` package. Follow the codebase's existing conventions first.

- **ESM only.** `import` / `export`, never `require` or `module.exports`. A file that must be CommonJS is `.cjs`.
- **Relative imports carry the full file name** (`./lib/thing.mjs`). ESM doesn't resolve an extensionless relative path
  or a directory's `index` file.
- **Core modules use the `node:` prefix**: `node:fs/promises`, `node:crypto`, `node:path`, `node:test`.
- **Top-level `await` is fine** in a module. No async IIFE wrappers.
- **No `__dirname` / `__filename`.** Use `import.meta.dirname` / `import.meta.filename` where the Node version has
  them, else `fileURLToPath(import.meta.url)`.
- **Target the declared Node version** (`engines` in `package.json`, or `.nvmrc`). Use no API newer than it, and check
  that version's docs for anything marked experimental.
- **Built-ins before dependencies.** Check Node's built-ins (global `fetch`, `node:test`, `node:crypto`) and the project's
  own helpers first, then follow `<DEPENDENCY_POLICY>`.
- **No compiler, so nothing checks the code before it runs.** Run `<SYNTAX_CHECK_COMMAND>` (usually
  `node --check <file>`) on every changed file, and make sure a test imports every changed module.
