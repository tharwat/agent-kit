---
description: Copy gate. Checks user-facing copy for language, terminology, brand rules and unverified claims, giving the exact corrected string for each violation.
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# /compliance

Reviews user-facing copy: UI strings, emails, message templates, help content, website pages.

**Skip** when the diff changes no user-facing copy. Copy paths come from `docs/agent/source-layout.md`. Record
`⏭️ Skipped — no copy changes`.

## Step 1: Get the changed copy

```bash
git fetch origin <MAIN_BRANCH>
git diff origin/<MAIN_BRANCH>...HEAD -- <copy paths>
git diff HEAD -- <copy paths>
```

Read `docs/agent/copy-rules.md`. If its tables are empty, run only Step 2 and Step 5.

## Step 2: Language

All user-facing text is in `<UI_LANGUAGE>`. Flag any string a user sees in another language, with its translation.
Code, comments, logs, developer config and internal errors never shown to users may stay in English.

## Step 3: Terminology

Check each term against the terminology table in `copy-rules.md`, including any exceptions it lists. Flag every wrong
term with the right one.

## Step 4: Brand rules

Apply each brand rule in `copy-rules.md` exactly as written (spelling, casing, markup such as a no-translate
wrapper). Flag every miss with the corrected string.

## Step 5: Claims

Find every legal, regulatory or factual claim: a law or regulation and its name or year, a penalty, a certification,
a statistic, a guarantee. Check each against the verified-claims table in `copy-rules.md`.

- A claim that matches the table: ✅.
- A claim not in the table, or that differs from it: ❌ BLOCKED. Give the verified wording, or say the claim must be
  removed until the owner verifies it.
- Never invent or estimate a penalty.

With an empty table, every such claim is unverified.

## Step 6: Marketing copy

For marketing and outreach copy: no fear-based or coercive framing, no invented legal threats, no exaggerated
penalties. Follow any channel rules in `copy-rules.md`.

## Step 7: Output

```
COMPLIANCE AUDIT: <branch>

Language (<UI_LANGUAGE>): ✅ / ❌ <file:line> "<text>" → "<translation>"
Terminology:   ✅ / n/a / ❌ <file:line> "<wrong term>" → "<right term>"
Brand rules:   ✅ / n/a / ❌ <file:line> "<text>" → "<corrected>"
Claims:        ✅ all verified / n/a / ❌ <file:line> "<claim>" — not in the verified table → "<verified wording or remove>"
Marketing:     ✅ / n/a / ❌ <file:line> <issue> → "<corrected>"

Verdict: ✅ CLEAR / ⚠️ FIXES NEEDED / ❌ BLOCKED — unverified claim
Required fixes:
  1. <file:line> — "<exact corrected text>"
Owner action: none | <verify the claim "<claim>">
```

## Rules

- Give the exact corrected string for every violation, not a description.
- A claim you can't verify is flagged, never approved.

## Completion status

End with one of:

- **DONE**: every violation has its corrected string.
- **DONE_WITH_CONCERNS**: list items that need a human's judgement.
- **BLOCKED**: a claim not in the verified table, or a copy file can't be read. Say what is missing.
- **NEEDS_CONTEXT**: the diff or scope is unclear. Say what you need.
