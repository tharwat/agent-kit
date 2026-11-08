#!/bin/sh
# Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
# PostToolUse hook (Edit|Write|MultiEdit): type-checks the TypeScript package an edit touched.
# The logic is in typecheck.py. Fails open: no python3, or any exit other than 2, allows.
# Tests: python3 .claude/hooks/test_typecheck.py
command -v python3 >/dev/null 2>&1 || { echo "typecheck hook: python3 not found; skipped" >&2; exit 0; }
python3 "$(dirname "$0")/typecheck.py"
[ "$?" -eq 2 ] && exit 2
exit 0
