<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Pack: scrollcraft

An opt-in extra. It installs the `scroll-craft` skill at `.claude/skills/scroll-craft/`: an MIT fork of the upstream
skill, modified by the agent-kit owner (Segmind replaces kie.ai; see the skill's `LICENSE` and `CHANGELOG.md`).
It extends no core command and has no facts of its own.

## Notes

- **`SEGMIND_API_KEY`** is needed only to generate images or clips, and never goes on a command line. Every call
  prints what it cost; the skill asks the owner before a build would spend more than about $20.
- If the skill's tools fail, run `node .claude/skills/scroll-craft/scripts/doctor.mjs` and report what it names.

## Codex

Codex can read the skill's files and run its scripts, but it does not load `.claude/skills/` by itself. To use the
skill from Codex, point it at `.claude/skills/scroll-craft/SKILL.md`.
