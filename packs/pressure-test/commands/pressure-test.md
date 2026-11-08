---
description: Pressure-test a business idea with a 5-member council, then one GO / RESHAPE / KILL verdict and the cheapest test to de-risk it.
argument-hint: "[the idea to pressure-test]"
---
<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->

> Values written `<LIKE_THIS>` come from the Project facts block in `CLAUDE.md`.

# Pressure test

Use before you spend time or money building the wrong thing. Five adversarial council members attack and defend the
idea, then a Judge makes one call. No member hedges or is polite: the value is in the friction.

## Step 1: The brief

Start from `$ARGUMENTS` if it holds the idea. Ask only what is missing, in one batch of 3–4 questions at most:

1. **The idea**, in one or two sentences.
2. **Who it's for** and **how it makes money** (buyer, price, model).
3. **Your edge**: skills, audience or assets you already have.
4. **Constraints**: budget, timeline, how soon you need the first dollar.

If the user says "just run it" or has given enough, skip the questions. One round only.

Write the brief as one short paragraph. Every council member gets the same paragraph.

## Step 2: The council (5 agents, in parallel)

Start all five in one message, one general-purpose subagent each, with the brief and its mandate.
Codex has no subagents: play the five members yourself, one after another, each written without reading the
others first.

Each member returns: a one-line stance, its 3–5 sharpest points, the one thing the user must hear, and a 1–10
score on its own dimension (1 = walk away, 10 = no-brainer).

1. **Contrarian (red team).** Assume the idea fails. Find the fatal flaws, the fastest way it dies, and the
   load-bearing assumptions that are probably wrong. Ruthless and specific; attack the weakest points.
2. **Expansionist (bull).** Make the strongest case for it: the biggest upside, the 10x version, the adjacent
   openings the founder isn't seeing. Be specific about where the money and leverage are.
3. **Logician (first principles).** No research, no web. Does the core mechanism make sense, do the incentives
   line up, does the math work in theory?
4. **Researcher (evidence).** Use web search. Who competes, what demand signals and market size exist, what
   comparable products charge. Cite sources. Does the real world say yes or no?
5. **Buyer (voice of the customer).** Be the exact target customer, in first person. Would you pay? What is your
   real objection? What would make you pick a competitor or do nothing? What price feels right, and what makes
   you say yes today? Skeptical, not a cheerleader.

## Step 3: The verdict

You are the Judge. Weigh every member's findings; don't average the scores. Name the real tension between the
members and resolve it. Add the economics yourself: rough price, realistic time to first dollar, and whether
the user can ship it fast with the edge they described.

Output exactly this shape:

```
## THE VERDICT: GO / RESHAPE / KILL
Confidence: [low / medium / high]

**The call in one line:** [the decision, plainly]

**Why:** [2-3 sentences resolving the council's tension]

**Biggest risk:** [the single thing most likely to kill it]
**Biggest upside:** [the strongest reason to do it]

**Money read:** [rough price, time-to-first-dollar, can they ship fast]

**The cheapest 48-hour test:** [the smallest, fastest thing they can do
to validate the riskiest assumption BEFORE building anything]

**If RESHAPE:** [the specific pivot that fixes the fatal flaw while keeping the upside]
```

Then the five scores on one line: `Contrarian X/10 · Expansionist X/10 · Logician X/10 · Researcher X/10 · Buyer X/10`.

## Rules

- Every member stays in character and never softens.
- The Judge makes a real call. "It depends" is not a verdict.
- The cheapest 48-hour test is the most important output: it tells the user whether they're right without
  building anything.
- Keep the verdict skimmable. The council does the depth; the Judge does the decision.
