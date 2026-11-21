// Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
// Runs ../workflows/consensus-review.js with scripted agents, to pin the table and the events (post-op Step 1.5
// round rules 2 and 10). The Workflow tool's globals are stubbed: agent, parallel, pipeline, phase, log.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const SOURCE = readFileSync(fileURLToPath(new URL("../workflows/consensus-review.js", import.meta.url)), "utf8");
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const body = SOURCE.replace("export const meta", "const meta");

// A vote: real, remote, bounded and costly unless a field says otherwise (the one shape the table defers).
const vote = (over = {}) => ({ real: true, loss: "operator", bounded: true, reach: "one-failure", silent: false, fix: "costly",
  open_class: false, origin: "first-draft", mechanism_of: "none", repeat_of: "none", evidence: "e", ...over });
const finding = (k, over = {}) => ({ file: `src/f${k}.js`, line: k, summary: `finding ${k}`, failure_scenario: "x → y", ...over });

// script: { reviews: label → findings | null, votes: (findingIndex, voter) → vote | null, relay }
async function run(args, script) {
  const calls = [];
  const agent = async (prompt, opts) => {
    calls.push({ prompt, label: opts.label });
    if (opts.label === "review:codex") return script.relay ?? null;
    if (opts.label.startsWith("review:")) {
      const r = script.reviews ? script.reviews(opts.label) : [];
      return r === null ? null : { findings: r };
    }
    const [, i, n] = opts.label.match(/^verify:(\d+)\.(\w)$/);
    return script.votes(Number(i) - 1, n);
  };
  const parallel = fns => Promise.all(fns.map(f => f()));
  const pipeline = (items, fn) => Promise.all(items.map((x, i) => fn(x, x, i)));
  const out = await new AsyncFunction("args", "agent", "parallel", "pipeline", "phase", "log", body)(
    args, agent, parallel, pipeline, () => {}, () => {});
  return { out, calls };
}
const one = label => (label === "review:correctness" ? [finding(1)] : []);
const both = v => () => vote(v);

test("no base: the round did not run", async () => {
  const { out } = await run({}, {});
  assert.equal(out.round_ran, false);
});

test("fewer than two of three reviewers: the round did not run", async () => {
  const { out } = await run({ base: "origin/main" }, { reviews: l => (l === "review:risk" ? [] : null) });
  assert.equal(out.round_ran, false);
});

test("no cap: every finding a reviewer reports is verified", async () => {
  const many = Array.from({ length: 40 }, (_, k) => finding(k + 1));
  const { out, calls } = await run({ base: "origin/main" }, { reviews: l => (l === "review:correctness" ? many : []), votes: both({ fix: "small" }) });
  assert.equal(out.must_fix.length, 40);
  assert.ok(!/at most/i.test(calls[0].prompt));
});

test("the table: what two agreeing voters make of a real finding", async () => {
  const cases = [
    [{ loss: "data", reach: "two-failures" }, "must_fix", "S1"],
    [{ loss: "person", reach: "two-failures" }, "must_fix", "S2"],
    [{ loss: "critical" }, "must_fix", "S3"],
    [{ loss: "money", bounded: false }, "must_fix", "S1"],
    [{ loss: "appearance", reach: "normal" }, "must_fix", "S4"],
    [{ fix: "small", reach: "two-failures" }, "must_fix", "noted"],
    [{ loss: "money", bounded: true }, "tickets", "noted"],
    [{}, "tickets", "noted"],
    [{ loss: "none" }, "nits", "nit"],
    [{ open_class: true }, "open_class", "noted"],
    [{ open_class: true, reach: "normal" }, "redesign", "S4"],
  ];
  for (const [over, bucket, cls] of cases) {
    const { out } = await run({ base: "origin/main" }, { reviews: one, votes: both(over) });
    assert.equal(out[bucket].length, 1, `${JSON.stringify(over)} → ${bucket}`);
    assert.equal(out[bucket][0].class, cls, JSON.stringify(over));
  }
});

test("a deferred finding carries its analysis and a priority", async () => {
  const { out } = await run({ base: "origin/main" }, { reviews: one, votes: both({ silent: true }) });
  assert.equal(out.tickets[0].priority, "worth fixing");
  assert.match(out.tickets[0].analysis, /loss operator · reach one-failure · silent · fix costly/);
  assert.equal(out.next.action, "clean");
});

test("a split between fix now and later is fixed now", async () => {
  const votes = (i, n) => (n === "a" ? vote({ reach: "normal" }) : n === "b" ? vote() : vote({ real: false }));
  const { out } = await run({ base: "origin/main" }, { reviews: one, votes });
  assert.equal(out.must_fix.length, 1);
  assert.match(out.must_fix[0].why, /split/);
});

test("two voters who cannot confirm it reject it; one against one is unverified", async () => {
  const no = await run({ base: "origin/main" }, { reviews: one, votes: both({ real: false }) });
  assert.equal(no.out.rejected.length, 1);
  const tie = await run({ base: "origin/main" }, { reviews: one, votes: (i, n) => (n === "a" ? vote() : n === "b" ? vote({ real: false }) : null) });
  assert.equal(tie.out.unverified.length, 1);
  assert.equal(tie.out.next.action, "fix");
});

test("events: a defect in a fix, or in a mechanism already fixed, stops the patching", async () => {
  const inFix = await run({ base: "origin/main" }, { reviews: one, votes: both({ origin: "fix-introduced", reach: "normal" }) });
  assert.equal(inFix.out.next.action, "redesign");
  assert.deepEqual(inFix.out.next.part, ["src/f1.js"]);
  assert.equal(inFix.out.must_fix.length, 0);

  const text = await run({ base: "origin/main" }, { reviews: one, votes: both({ origin: "fix-introduced", loss: "appearance", fix: "small" }) });
  assert.equal(text.out.next.action, "fix");

  const prior = [{ finding: "R1-1: the retry double-charges", disposition: "must-fix" }];
  const again = await run({ base: "origin/main", prior }, { reviews: one, votes: both({ mechanism_of: "F1", fix: "small" }) });
  assert.equal(again.out.next.action, "redesign");
  assert.match(again.out.redesign[0].stop, /double-charges/);
});

test("a repeat of an earlier decision is not new", async () => {
  const prior = [{ finding: "R1-2: slow query", disposition: "own ticket ABC-9" }];
  const { out } = await run({ base: "origin/main", prior }, { reviews: one, votes: both({ repeat_of: "P1", reach: "normal" }) });
  assert.equal(out.repeats.length, 1);
  assert.equal(out.next.action, "clean");
});

test("Codex: its findings join the vote, and the round counts without it", async () => {
  const relay = { unavailable: "", findings: [finding(1, { summary: "codex wording" }), finding(7)] };
  const withIt = await run({ base: "origin/main", codexModel: "m" }, { reviews: one, relay, votes: both({ fix: "small" }) });
  assert.equal(withIt.out.codex, "returned 2");
  assert.equal(withIt.out.must_fix.length, 2);
  assert.deepEqual(withIt.out.must_fix[0].finders, ["correctness", "codex"]);
  const relayCall = withIt.calls.find(c => c.label === "review:codex");
  assert.match(relayCall.prompt, /--sandbox read-only -c 'mcp_servers=\{\}'/);

  const down = await run({ base: "origin/main", codexModel: "m" }, { reviews: one, relay: { unavailable: "not logged in", findings: [] }, votes: both() });
  assert.equal(down.out.round_ran, true);
  assert.equal(down.out.codex, "unavailable — not logged in");

  const off = await run({ base: "origin/main" }, { reviews: one, votes: both() });
  assert.equal(off.out.codex, "not requested");
  assert.ok(!off.calls.some(c => c.label === "review:codex"));
});

test("the author is a witness: the note reaches finders and voters as a claim, and an objection is rechecked", async () => {
  const { calls } = await run({ base: "origin/main", witness: "src/a.js:10 — the amount is checked here" }, { reviews: one, votes: both() });
  assert.ok(calls.every(c => /does not vote/.test(c.prompt) && /the amount is checked here/.test(c.prompt)));

  const recheck = [{ file: "src/f1.js", line: 1, summary: "finding 1", failure_scenario: "x → y", objection: "guarded at src/a.js:10" }];
  const again = await run({ base: "origin/main", recheck }, { votes: both({ real: false }) });
  assert.equal(again.out.recheck, true);
  assert.equal(again.out.rejected.length, 1);
  assert.ok(again.calls.every(c => c.label.startsWith("verify:") && /guarded at src\/a\.js:10/.test(c.prompt)));
});

test("a later round reviews only the fix delta", async () => {
  const { out, calls } = await run({ base: "origin/main", round: 2, savedDiff: ".claude/state/T/round-1.diff" }, { reviews: one, votes: both() });
  assert.equal(out.scope, "fix delta");
  assert.match(calls[0].prompt, /Report findings only in the fix delta/);
});
