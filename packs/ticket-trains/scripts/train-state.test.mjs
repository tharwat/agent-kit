// Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
// Tests for train-state.mjs. Run: node --test <path to this file>
//
// Each test works in its own fs.mkdtemp directory under the OS temp dir. Nothing here deletes anything: the temp dirs
// are left for the OS to reap, by design (the kit never runs a delete, in code or in instructions).

import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { applyPatch, summarize, triageGaps } from "./train-state.mjs";

const CLI = join(dirname(fileURLToPath(import.meta.url)), "train-state.mjs");
const run = (...args) => spawnSync(process.execPath, [CLI, ...args], { encoding: "utf8" });
const tempFile = () => join(mkdtempSync(join(tmpdir(), "train-state-")), "t.json");

function ok(r) {
  assert.equal(r.status, 0, `expected success, got ${r.status}: ${r.stderr}`);
  return JSON.parse(r.stdout);
}
function refused(r, pattern) {
  assert.equal(r.status, 1, `expected exit 1, got ${r.status}: ${r.stdout}`);
  assert.equal(r.stdout, "");
  assert.match(r.stderr, pattern);
}

const row = (id, extra = {}) => ({
  id, class: "S4", invariant: "x is rejected", paths: "a.js -> b.js", hostile_case: "empty x", authority: "schema",
  proof: "test rejects empty x", counterfactual: "remove the guard", vector: null, discharge: null, ...extra,
});
const vector = { input: "x=''", expected: "400", rejects: "accepts empty", source: "bteam 2026-01-02" };
const discharge = { test: "rejects empty x", result: "pass", path_exercised: "POST /x", counterfactual_result: "red without guard" };
const ticket = (key, extra = {}) => ({
  key, state: "pending", title: `title ${key}`, runtime_verifiable: true, verify_how: "POST /x returns 400",
  regression_test: "none", constraints: "none", notes: "none", pr: null, branch: null, peer_review: null, reason: null,
  triage: null, contract: [], contract_note: null, threat_model: null, questions: [], decisions: [], open_findings: [],
  code_review: null, blocked_work: null, result: null, ...extra,
});
const triaged = (key, extra = {}) => ticket(key, {
  triage: { date: "2026-01-02", status: "DONE", premise: "Reproduces", files: ["a.js"], summary: "fix x" },
  contract: [row("C1", { vector })], threat_model: "honest mistakes; hostile authors out of scope", ...extra,
});
const train = (queue = [ticket("ABC-1"), ticket("ABC-2")]) => ({
  name: "spring-fixes", revision: 0, created: "2026-01-01", procedure: ".claude/commands/ticket-train-run.md",
  triage_required: true, triaged: null, halt: null,
  rules: {
    sequential: true, base_branch: "main", test_commands: ".: npm test", adversarial: "B-Team + Codex",
    forbidden: ["anything under G1, G2, G4, G5, G6 or G7"], pre_authorized: [],
  },
  queue, candidates: [], unqueued_work: [], excluded: [],
});
const patch = (state, target, p, rev = state.revision) => applyPatch(state, { target, expectedRevision: rev, patch: p });

// ------------------------------------------------------------ files, locking, atomic writes

test("create writes revision 0 and refuses to overwrite", () => {
  const f = tempFile();
  assert.deepEqual(ok(run("create", f, JSON.stringify(train()))), { state: "created", train: "spring-fixes", revision: 0 });
  assert.equal(JSON.parse(readFileSync(f, "utf8")).revision, 0);
  refused(run("create", f, JSON.stringify(train())), /already exists; never overwrite/);
});

test("create makes the state folder when it is missing", () => {
  const f = join(mkdtempSync(join(tmpdir(), "train-state-")), "state", "trains", "t.json");
  assert.equal(existsSync(dirname(f)), false);
  assert.deepEqual(ok(run("create", f, JSON.stringify(train()))), { state: "created", train: "spring-fixes", revision: 0 });
  assert.equal(JSON.parse(readFileSync(f, "utf8")).revision, 0);
});

test("create reads @file and rejects a non-pending start", () => {
  const f = tempFile(), src = `${f}.src`;
  writeFileSync(src, JSON.stringify(train([ticket("ABC-1", { state: "done" })])));
  refused(run("create", f, `@${src}`), /must start as pending/);
  assert.equal(existsSync(f), false);
});

test("update advances the revision, writes atomically and releases the lock by rename", () => {
  const f = tempFile();
  ok(run("create", f, JSON.stringify(train())));
  assert.deepEqual(ok(run("update", f, "ABC-1", "0", '{"notes":"run after ABC-2"}')), { state: "updated", target: "ABC-1", revision: 1 });
  const s = JSON.parse(readFileSync(f, "utf8"));
  assert.equal(s.revision, 1);
  assert.equal(s.queue[0].notes, "run after ABC-2");
  assert.equal(existsSync(`${f}.lock`), false);
  assert.equal(existsSync(`${f}.lock.released`), true);
  assert.equal(existsSync(`${f}.tmp`), false);
});

test("a stale revision is refused and the file is untouched", () => {
  const f = tempFile();
  ok(run("create", f, JSON.stringify(train())));
  ok(run("update", f, "ABC-1", "0", '{"notes":"one"}'));
  const before = readFileSync(f, "utf8");
  refused(run("update", f, "ABC-1", "0", '{"notes":"two"}'), /stale revision: expected 0, found 1/);
  assert.equal(readFileSync(f, "utf8"), before);
  assert.equal(existsSync(`${f}.lock`), false);
});

test("a live lock is refused; a stale lock asks for a rename, never a delete", () => {
  const f = tempFile();
  ok(run("create", f, JSON.stringify(train())));
  writeFileSync(`${f}.lock`, "pid 1\n");
  refused(run("update", f, "ABC-1", "1", '{"notes":"x"}'), /locked by another live update/);
  const old = new Date(Date.now() - 60 * 60_000);
  utimesSync(`${f}.lock`, old, old);
  refused(run("update", f, "ABC-1", "1", '{"notes":"x"}'), /stale lock .*rename it to/);
  assert.equal(existsSync(`${f}.lock`), true, "the helper never removes someone else's lock");
});

test("preview prints the next state and writes nothing", () => {
  const f = tempFile();
  ok(run("create", f, JSON.stringify(train())));
  const before = readFileSync(f, "utf8"), released = readFileSync(`${f}.lock.released`, "utf8");
  const next = ok(run("preview", f, "ABC-2", "0", '{"notes":"preview"}'));
  assert.equal(next.revision, 1);
  assert.equal(next.queue[1].notes, "preview");
  assert.equal(readFileSync(f, "utf8"), before);
  assert.equal(readFileSync(`${f}.lock.released`, "utf8"), released, "preview takes no lock");
  assert.equal(existsSync(`${f}.lock`), false);
});

test("summary is read-only and never counts needs_verify as done", () => {
  const f = tempFile();
  const s = train([
    triaged("ABC-1", { state: "done", pr: 7, contract: [row("C1", { vector, discharge })] }),
    triaged("ABC-2", { state: "needs_verify", pr: 8, contract: [row("C1", { vector, discharge })] }),
    ticket("ABC-3"),
  ]);
  writeFileSync(f, JSON.stringify(s));
  const before = readFileSync(f, "utf8");
  const sum = ok(run("summary", f));
  assert.equal(sum.done, 1);
  assert.equal(sum.counts.needs_verify, 1);
  assert.equal(sum.complete, false);
  assert.equal(sum.base_branch, "main");
  assert.equal(sum.next, "ABC-3");
  assert.equal(sum.ready_to_run, false);
  assert.ok(sum.not_ready.includes("train not triaged"));
  assert.equal(readFileSync(f, "utf8"), before);
  assert.equal(ok(run("summary", f, "ABC-2")).ticket.state, "needs_verify");
  refused(run("summary", f, "ABC-9"), /no such ticket/);
});

test("usage errors exit 2; malformed JSON exits 1", () => {
  assert.equal(run("bogus").status, 2);
  assert.equal(run("update", "x").status, 2);
  const f = tempFile();
  writeFileSync(f, "{not json");
  refused(run("summary", f), /not valid JSON/);
  ok(run("create", `${f}2`, JSON.stringify(train())));
  refused(run("update", `${f}2`, "ABC-1", "zero", "{}"), /whole number/);
});

// ------------------------------------------------------------ schema and history rules

test("a patch may not set the revision, remove a ticket, or change a recorded rule", () => {
  const s = train();
  assert.throws(() => patch(s, "ABC-1", { revision: 5 }), /may not set revision/);
  assert.throws(() => patch(s, "train", { queue: [s.queue[0]] }), /would remove queued ticket ABC-2/);
  assert.throws(() => patch(s, "train", { rules: { ...s.rules, forbidden: ["nothing"] } }), /rules.forbidden is recorded once/);
  assert.throws(() => patch(s, "train", { rules: { ...s.rules, pre_authorized: ["G2 writes"] } }), /rules.pre_authorized is recorded once/);
  assert.throws(() => patch(s, "train", { rules: { ...s.rules, base_branch: "develop" } }), /rules.base_branch/);
});

test("a ticket added to the queue must arrive pending", () => {
  const s = train();
  assert.throws(() => patch(s, "train", { queue: [...s.queue, ticket("ABC-3", { state: "in_progress" })] }), /must arrive as pending/);
  assert.equal(patch(s, "train", { queue: [...s.queue, ticket("ABC-3")] }).queue.length, 3);
});

test("blocked needs a reason and returns only to pending", () => {
  const s = train();
  assert.throws(() => patch(s, "ABC-1", { state: "blocked" }), /blocked without a reason/);
  const b = patch(s, "ABC-1", { state: "blocked", reason: "question q1: scope" });
  assert.throws(() => patch(b, "ABC-1", { state: "in_progress" }), /invalid transition blocked -> in_progress/);
  assert.equal(patch(b, "ABC-1", { state: "pending" }).queue[0].state, "pending");
});

test("in_progress is refused for an untriaged ticket", () => {
  const s = train([ticket("ABC-1"), triaged("ABC-2", { contract: [row("C1")] }), triaged("ABC-3", { threat_model: null })]);
  assert.throws(() => patch(s, "ABC-1", { state: "in_progress" }), /untriaged \(no triage record; empty contract with no contract_note\)/);
  assert.throws(() => patch(s, "ABC-2", { state: "in_progress" }), /no pre-code vectors/);
  assert.throws(() => patch(s, "ABC-3", { state: "in_progress" }), /no threat model/);
  const docs = train([triaged("ABC-1", { contract: [], threat_model: null, contract_note: "no executable behavior" })]);
  assert.equal(patch(docs, "ABC-1", { state: "in_progress" }).queue[0].state, "in_progress");
  assert.deepEqual(triageGaps(triaged("ABC-9")), []);
});

test("contract rows are append-only; a vector or discharge is written once", () => {
  const s = train([triaged("ABC-1", { contract: [row("C1"), row("C2", { vector })] })]);
  assert.throws(() => patch(s, "ABC-1", { contract: [row("C2", { vector })] }), /remove contract row C1/);
  assert.throws(() => patch(s, "ABC-1", { contract: [row("C1", { invariant: "weaker" }), row("C2", { vector })] }), /rewrite contract row C1/);
  const added = patch(s, "ABC-1", { contract: [row("C1", { vector }), row("C2", { vector }), row("C3")] });
  assert.equal(added.queue[0].contract.length, 3);
  assert.throws(() => patch(added, "ABC-1", { contract: [row("C1", { vector: { ...vector, expected: "200" } }), row("C2", { vector }), row("C3")] }), /vector is immutable/);
  const d = patch(added, "ABC-1", { contract: [row("C1", { vector, discharge }), row("C2", { vector }), row("C3")] });
  assert.throws(() => patch(d, "ABC-1", { contract: [row("C1", { vector, discharge: { ...discharge, result: "skip" } }), row("C2", { vector }), row("C3")] }), /discharge is immutable/);
  assert.throws(() => patch(s, "ABC-1", { contract: [row("C1", { vector: { input: "x" } }), row("C2", { vector })] }), /vector.expected is missing/);
  assert.throws(() => patch(s, "ABC-1", { contract: [row("C1"), row("C2", { vector }), row("C3", { invariant: "TODO" })] }), /invariant is missing or a placeholder/);
  assert.throws(() => patch(s, "ABC-1", { contract_note: "no executable behavior" }), /mixes contract rows/);
});

test("questions are fixed once asked; only the answer is filled in, once", () => {
  const q = { id: "q1", question: "Accept both forms?", options: ["accept", "reject"], recommendation: "accept", blocking: true, default: null, answer: null };
  const s = train([ticket("ABC-1", { state: "awaiting_answer", questions: [q] })]);
  assert.throws(() => patch(s, "ABC-1", { questions: [{ ...q, question: "something else" }] }), /questions is append-only/);
  assert.throws(() => patch(s, "ABC-1", { questions: [] }), /questions is append-only/);
  assert.throws(() => patch(s, "ABC-1", { state: "pending" }), /blocking questions are answered: q1/);
  const a = patch(s, "ABC-1", { questions: [{ ...q, answer: "accept" }], decisions: [{ id: "q1", decision: "accept", by: "owner", date: "2026-01-03" }], state: "pending" });
  assert.equal(a.queue[0].state, "pending");
  assert.throws(() => patch(a, "ABC-1", { questions: [{ ...q, answer: "reject" }] }), /questions is append-only/);
  assert.throws(() => patch(a, "ABC-1", { decisions: [] }), /decisions is append-only/);
  assert.throws(() => patch(s, "ABC-1", { questions: [{ ...q, default: "accept" }] }), /blocking question has no default/);
});

test("a default is only taken on a non-blocking question, verbatim", () => {
  const nb = { id: "q2", question: "Which helper?", options: ["a", "b"], recommendation: "a", blocking: false, default: "a", answer: null };
  const bl = { id: "q3", question: "Ship to customers?", options: ["yes", "no"], recommendation: "no", blocking: true, default: null, answer: null };
  const s = train([ticket("ABC-1", { questions: [nb, bl] })]);
  assert.equal(patch(s, "ABC-1", { decisions: [{ id: "q2", decision: "a", by: "default", date: "2026-01-03" }] }).revision, 1);
  assert.throws(() => patch(s, "ABC-1", { decisions: [{ id: "q2", decision: "b", by: "default", date: "2026-01-03" }] }), /recorded default verbatim/);
  assert.throws(() => patch(s, "ABC-1", { decisions: [{ id: "q3", decision: "no", by: "default", date: "2026-01-03" }] }), /mis-built/);
  assert.throws(() => patch(s, "ABC-1", { decisions: [{ id: "q9", decision: "x", by: "owner", date: "2026-01-03" }] }), /answers no recorded question/);
});

test("open findings are never erased; they only move to resolved", () => {
  const f = { id: "F1", source: "peer-review", finding: "null deref", class: "S4", resolved: false };
  const s = train([ticket("ABC-1", { open_findings: [f] })]);
  assert.throws(() => patch(s, "ABC-1", { open_findings: [] }), /open_findings is append-only/);
  assert.throws(() => patch(s, "ABC-1", { open_findings: [{ ...f, class: "noted" }] }), /open_findings is append-only/);
  const r = patch(s, "ABC-1", { open_findings: [{ ...f, resolved: true }] });
  assert.throws(() => patch(r, "ABC-1", { open_findings: [f] }), /open_findings is append-only/);
});

test("code_review: rounds never decrease and stay under the cap", () => {
  const cr = { rounds: 2, extra_round: false, redesign: null, end_state: null, self_review: null, dispositions: [{ round: 1, finding: "x", class: "S4", disposition: "must-fix" }] };
  const s = train([ticket("ABC-1", { code_review: cr })]);
  assert.throws(() => patch(s, "ABC-1", { code_review: { ...cr, rounds: 1 } }), /never decreases/);
  assert.throws(() => patch(s, "ABC-1", { code_review: { ...cr, rounds: 4 } }), /past the cap of 3/);
  assert.equal(patch(s, "ABC-1", { code_review: { ...cr, rounds: 4, extra_round: true } }).revision, 1);
  assert.equal(patch(s, "ABC-1", { code_review: { ...cr, rounds: 6, redesign: "(b) same mechanism -> redesign as proposed" } }).revision, 1);
  assert.throws(() => patch(s, "ABC-1", { code_review: { ...cr, rounds: 8, extra_round: true, redesign: "r" } }), /past the cap of 7/);
  assert.throws(() => patch(s, "ABC-1", { code_review: { ...cr, dispositions: [] } }), /dispositions is append-only/);
  assert.throws(() => patch(s, "ABC-1", { code_review: { ...cr, dispositions: [...cr.dispositions, { round: 3, finding: "y", class: "S4", disposition: "must-fix" }] } }), /round that did not run/);
  assert.throws(() => patch(s, "ABC-1", { code_review: { ...cr, dispositions: [...cr.dispositions, { round: 2, finding: "y", class: "S4", disposition: "fix" }] } }), /not one of/);
  assert.throws(() => patch(s, "ABC-1", { code_review: null }), /erase the code_review/);
  const granted = patch(s, "ABC-1", { code_review: { ...cr, extra_round: true } });
  assert.throws(() => patch(granted, "ABC-1", { code_review: { ...cr } }), /extra_round cannot be taken back/);
});

test("done and needs_verify need a PR, every row discharged, nothing open", () => {
  const base = triaged("ABC-1", { state: "in_progress" });
  const s = train([base]);
  assert.throws(() => patch(s, "ABC-1", { state: "done" }), /without a recorded PR/);
  assert.throws(() => patch(s, "ABC-1", { state: "done", pr: 12 }), /not discharged: C1/);
  const dis = { pr: 12, contract: [row("C1", { vector, discharge })] };
  assert.throws(() => patch(s, "ABC-1", { state: "needs_verify", ...dis, open_findings: [{ id: "F1", source: "post-op", finding: "x", class: "S2", resolved: false }] }), /unresolved findings: F1/);
  assert.equal(patch(s, "ABC-1", { state: "done", ...dis }).queue[0].state, "done");
  const d = patch(s, "ABC-1", { state: "done", ...dis });
  assert.throws(() => patch(d, "ABC-1", { state: "pending" }), /invalid transition done -> pending/);
  assert.throws(() => patch(d, "ABC-1", { pr: null }), /PR number is never cleared/);
});

test("blocked_work is a full local checkpoint record and is never cleared", () => {
  const w = { branch: "feature/abc-1-x", commit: "0123abc", reason: "question q1", checkpoint_kind: "WIP checkpoint — blocked", diff_check: "clean", resumed_at: null };
  const s = train([ticket("ABC-1", { blocked_work: w })]);
  assert.throws(() => patch(s, "ABC-1", { blocked_work: null }), /kept as evidence/);
  assert.throws(() => patch(s, "ABC-1", { blocked_work: { ...w, checkpoint_kind: "wip" } }), /checkpoint_kind/);
  assert.throws(() => patch(s, "ABC-1", { blocked_work: { ...w, commit: "HEAD" } }), /needs branch, commit and reason/);
  assert.equal(patch(s, "ABC-1", { blocked_work: { ...w, resumed_at: "2026-01-04" } }).revision, 1);
});

test("the state shape is validated on read", () => {
  assert.throws(() => summarize({ ...train(), name: "Spring Fixes" }), /kebab-case/);
  assert.throws(() => summarize(train([ticket("abc-1")])), /invalid ticket key/);
  assert.throws(() => summarize(train([ticket("ABC-1"), ticket("ABC-1")])), /queued twice/);
  assert.throws(() => summarize({ ...train(), rules: { ...train().rules, forbidden: [] } }), /rules.forbidden/);
  assert.throws(() => summarize({ ...train(), rules: { ...train().rules, sequential: false } }), /one ticket at a time/);
  assert.throws(() => summarize(train([ticket("ABC-1", { peer_review: "maybe" })])), /peer_review must be/);
  assert.throws(() => summarize(train([ticket("ABC-1", { contract_note: "docs" })])), /contract_note may only be/);
  assert.equal(summarize(train([ticket("#42")])).total, 1);
});
