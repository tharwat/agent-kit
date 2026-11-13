<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Telegram notifications

Commands that report an outcome (`/ship`, `/post-op`, `/peer-review`, `/test`, `/investigate`, `/release`, and pack
commands such as builds and QA) run
`.claude/scripts/notify "<text>"`. The script posts the text to one Telegram chat. Every message starts with
`[<PROJECT_NAME>]`; the commands add that prefix.

Use **one channel per project**, so projects never share a chat.

## Set it up

1. **Create a bot.** In Telegram, message @BotFather and send `/newbot`. Choose a name and a username ending in
   `bot`. BotFather replies with the bot token. Treat it as a password.
2. **Create a channel or group** for this project, for example "<PROJECT_NAME> ops".
3. **Add the bot.**
   - Channel: add it as an administrator with permission to post messages.
   - Group: add it as a member. Then send a message that mentions it (`@<bot username> hi`), because bots in groups
     only see messages addressed to them.
4. **Get the chat ID.** Post a message in the channel or group, then run:

   ```
   curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getUpdates"
   ```

   with the token exported first. Look for `"chat":{"id":...}`. Channel and supergroup IDs start with `-100`.
   Don't paste that URL with the token into a ticket, chat or doc.
5. **Set the two variables** in one of two places. The environment wins when both set a value.
   - **Environment:** export `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the shell profile that starts Claude
     Code or Codex. This works for both agents.
   - **File:** `.claude/notify.env`, one `KEY=value` per line. The installer lists it in `.gitignore`; check that
     `git check-ignore .claude/notify.env` prints the path before you create it. Never commit it.
6. **Record the chat ID** as the `NOTIFY_TELEGRAM_CHAT_ID` fact, so others know which chat this project posts to:
   put `"NOTIFY_TELEGRAM_CHAT_ID": "<chat id>"` under `facts` in an answers file and re-run the agent-kit
   installer's `upgrade --target <project> --answers <file>` (see the kit's `INSTALL.md`, "Upgrading"). Don't edit
   `.claude/packs/notify-telegram.md` by hand: the kit owns it, so the next upgrade would report it as a conflict.
   The script reads `TELEGRAM_CHAT_ID`, not the fact.
7. **Test it:** `.claude/scripts/notify "[<PROJECT_NAME>] notify test"`.

## How it behaves

- Plain text only: no parse mode, so nothing needs escaping.
- Text over 4,000 characters is sent as several messages, split at line breaks where possible.
- Each request times out after 10 seconds.
- It never fails the command that called it. Missing config prints
  `notify: not configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID)`; a failed send prints one `notify: send failed`
  line. Both exit 0.
- The token is never printed, including in error messages.
- **Waiting pings (Claude Code).** A Notification hook (`.claude/hooks/notify-waiting.py`) sends
  `[<project>] Waiting for you: a permission prompt (Bash)` or `… idle, waiting for your input` when a run stalls on
  you. It sends at most one per 10 minutes per session, and only the event type and tool name, never the prompt's
  text. Codex has no hooks, so it sends none.

If the token leaks, revoke it with @BotFather (`/revoke`) and set the new one.
