<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Pack: cloudflare

An opt-in extra for Codex. It installs the third-party `cloudflare` skill at `.agents/skills/cloudflare/`, where
Codex finds skills, fetched from GitHub at the commit pinned in `pack.json` and checked against its sha256; the kit
never copies it. Claude Code doesn't load `.agents/skills/`. It extends no core command and has no facts of its
own.
