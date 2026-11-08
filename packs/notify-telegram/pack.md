<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Pack: notify-telegram

## Pack facts

| Fact | Value | Meaning |
|---|---|---|
| `NOTIFY_TELEGRAM_CHAT_ID` | {{NOTIFY_TELEGRAM_CHAT_ID}} | The chat this project posts to. A record only: `.claude/scripts/notify` reads `TELEGRAM_CHAT_ID` |

## Markers

This pack writes no ticket comments, so it has no markers.

This pack adds no steps to core commands. They already call `.claude/scripts/notify` when it exists. Setup and
behaviour: `docs/agent/notify-telegram.md`.
