---
description: Pressure-test an idea (a business, a product, a feature or a ticket) with a 5-member council, then one GO / RESHAPE / KILL verdict and the cheapest test before building.
argument-hint: "[<ticket> | the idea to pressure-test]"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# Pressure test

Use before you spend time or money building the wrong thing. Five adversarial council members attack and defend the
idea, then a Judge makes one call. No member hedges or is polite: the value is in the friction. It writes no code
and changes nothing; it is safe to run on any idea, at any time.

## Step 1: The brief

**What is being tested.** A ticket key → ticket op **get** it (comments included) and test the feature it asks
for. Anything else in `$ARGUMENTS` is the idea itself. Say which kind it is:
- **business**: a product, service or offer someone would pay for;
- **feature**: something new this project would build for its users (most tickets that add a capability).

Ask only what is missing, in one batch of 3–4 questions at most, and skip the questions if the owner says "just
run it" or has given enough. One round only.
- Business: the idea; who it's for and how it makes money (buyer, price, model); the owner's edge (skills,
  audience, assets); constraints (budget, timeline, how soon the first dollar is needed).
- Feature: the idea; who uses it and the problem it solves for them; what they do today without it; how the owner
  will know it worked.

**For a feature, read before writing the brief:** the code and docs for the area it touches, so the brief says
what the project already does there. A council that doesn't know what exists will argue about the wrong thing.

Write the brief as one short paragraph. Every council member gets the same paragraph.

## Step 2: The council (5 agents, in parallel)

Start all five in one message, one general-purpose subagent each, with the brief, the kind, and its mandate.
Codex has no subagents: play the five members yourself, one after another, each written without reading the
others first.

Each member returns: a one-line stance, its 3–5 sharpest points, the one thing the owner must hear, and a 1–10
score on its own dimension (1 = walk away, 10 = no-brainer).

1. **Contrarian (red team).** Assume it fails. Find the fatal flaws, the fastest way it dies, and the
   load-bearing assumptions that are probably wrong. For a feature: nobody uses it, it breaks something that
   works, or it costs more to keep than it gives. Ruthless and specific; attack the weakest points.
2. **Expansionist (bull).** Make the strongest case for it: the biggest upside, the 10x version, the openings the
   owner isn't seeing. Then name the smallest version that still captures most of that upside.
3. **Logician (first principles).** No research. Does the core mechanism make sense, do the incentives line up,
   does the math work? For a feature: does it fit how the project already works, or fight it?
4. **Researcher (evidence).** Business: use web search for competitors, demand signals, market size and what
   comparable products charge, and cite sources. Feature: read the project (code, docs, tickets, logs or data the
   owner has given access to) for what already exists, what users actually do today, and how others solve the
   same problem. Does the real world say yes or no?
5. **User (voice of the customer).** Be the exact person it is for, in first person. Business: would you pay,
   what price feels right, what makes you pick a competitor or do nothing? Feature: would you use it, what would
   you do instead, what would make you ignore it? Skeptical, not a cheerleader.

## Step 3: The verdict

You are the Judge. Weigh every member's findings; don't average the scores. Name the real tension between the
members and resolve it. Add the economics yourself: for a business, rough price, realistic time to first dollar,
and whether the owner can ship it fast with the edge they described; for a feature, the rough size, what it costs
to keep running, and what it displaces.

Output exactly this shape:

```
## THE VERDICT: GO / RESHAPE / KILL
Confidence: [low / medium / high]

**The call in one line:** [the decision, plainly]

**Why:** [2-3 sentences resolving the council's tension]

**Biggest risk:** [the single thing most likely to kill it]
**Biggest upside:** [the strongest reason to do it]

**Cost read:** [business: price, time to first dollar, can they ship fast · feature: size, upkeep, what it displaces]

**The cheapest test:** [the smallest, fastest thing that checks the riskiest assumption BEFORE building:
a landing page, five buyer calls, a query on real data, a manual run of the flow]

**If RESHAPE:** [the specific change that fixes the fatal flaw while keeping the upside; for a feature, the
smaller version to build]
```

Then the five scores on one line: `Contrarian X/10 · Expansionist X/10 · Logician X/10 · Researcher X/10 · User X/10`.

**When it tested a ticket,** save the verdict to `.claude/state/<ticket>/pressure-test.md`. `/triage` reads it.

## Rules

- Every member stays in character and never softens.
- The Judge makes a real call. "It depends" is not a verdict.
- The cheapest test is the most important output: it tells the owner whether they're right without building
  anything.
- The verdict advises; the owner decides. Nothing else in the workflow acts on it without their word.
- Keep the verdict skimmable. The council does the depth; the Judge does the decision.
