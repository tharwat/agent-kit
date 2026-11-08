#!/usr/bin/env node
// Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
// train-state: the one writer of a ticket train's state file. Node >= 18, no dependencies.
// Installed at .claude/scripts/train-state.mjs by the ticket-trains pack. State lives at .claude/state/trains/<train>.json.
//
//   create  <file> <json|@path>                                   write a new train (making its folder); refuses if the file exists
//   update  <file> <train|ticket> <expected-revision> <json|@path> merge the patch, validate, write atomically
//   preview <file> <train|ticket> <expected-revision> <json|@path> print the state the update would write; writes nothing
//   summary <file> [<ticket>]                                     print a read-only summary; writes nothing
//
// A patch is a JSON object merged shallowly into the train (target `train`) or into one queue entry (target = its key).
// To change a nested list, send the whole list. `@path` reads the JSON from a file (for long contracts).
//
// Every write holds <file>.lock, re-validates the whole state, refuses a stale revision, writes <file>.tmp and renames
// it over <file>. The lock is released by renaming it to <file>.lock.released. Nothing here deletes a file.
// On success a command prints one JSON line on stdout. On a refusal it prints one line on stderr and exits 1; usage
// errors exit 2.

import { closeSync, existsSync, mkdirSync, openSync, readFileSync, realpathSync, renameSync, statSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { isDeepStrictEqual } from "node:util";
import { fileURLToPath } from "node:url";

export const STATES = Object.freeze(["pending", "awaiting_answer", "in_progress", "blocked", "done", "needs_verify"]);
// blocked returns to the queue only through /ticket-train-triage (blocked -> pending). done is final.
export const TRANSITIONS = Object.freeze({
  pending: ["awaiting_answer", "in_progress", "blocked"],
  awaiting_answer: ["pending", "blocked"],
  in_progress: ["blocked", "done", "needs_verify"],
  blocked: ["pending"],
  done: [],
  needs_verify: ["done", "blocked"],
});
export const DISPOSITIONS = Object.freeze(["must-fix", "noted", "own ticket", "rejected", "already decided", "needs owner", "repeat"]);
export const END_STATES = Object.freeze(["clean", "capped", "escalate"]);
export const CHECKPOINT_KIND = "WIP checkpoint — blocked";
export const STALE_LOCK_MS = 10 * 60_000;

const CLASSES = ["S1", "S2", "S3", "S4"];
const TRIAGE_STATUSES = ["DONE", "DONE_WITH_CONCERNS", "BLOCKED", "NEEDS_CONTEXT"];
const KEY = /^[A-Z][A-Z0-9_]*-[1-9][0-9]*$|^#?[1-9][0-9]*$/;
const TRAIN_NAME = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const DATE = /^\d{4}-\d{2}-\d{2}/;
const PLACEHOLDER = /^(TODO|TBD|N\/?A|NULL|<fill|<replace|<exact)/i;
const NEW_ENTRY = Object.freeze({ state: "pending", contract: [], decisions: [], questions: [], open_findings: [], code_review: null });

class Refusal extends Error {}
const refuse = (message) => { throw new Refusal(message); };
const same = (a, b) => isDeepStrictEqual(a, b);
const isObject = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
const text = (v) => typeof v === "string" && v.trim().length > 0;
const cell = (v) => text(v) && !PLACEHOLDER.test(v.trim());
const list = (v) => (Array.isArray(v) ? v : []);

// ---------------------------------------------------------------- shape checks (one state, no history)

function checkRules(rules) {
  if (!isObject(rules)) refuse("rules must be an object");
  if (rules.sequential !== true) refuse("rules.sequential must be true: a train runs one ticket at a time");
  for (const key of ["base_branch", "test_commands", "adversarial"]) if (!text(rules[key])) refuse(`rules.${key} is missing`);
  if (!Array.isArray(rules.forbidden) || !rules.forbidden.length || !rules.forbidden.every(text)) refuse("rules.forbidden must be a non-empty list of strings, recorded verbatim");
  if (!Array.isArray(rules.pre_authorized) || !rules.pre_authorized.every(text)) refuse("rules.pre_authorized must be a list of strings, recorded verbatim (empty when the owner named none)");
}

function checkRow(ticket, row) {
  const where = `ticket ${ticket.key} contract row ${row?.id ?? "?"}`;
  if (!isObject(row)) refuse(`${where} is not an object`);
  if (!/^C[1-9][0-9]*$/.test(row.id ?? "")) refuse(`${where}: id must be C<digits>`);
  if (!CLASSES.includes(row.class)) refuse(`${where}: class must be one of ${CLASSES.join(", ")}`);
  for (const key of ["invariant", "paths", "hostile_case", "authority", "proof", "counterfactual"]) if (!cell(row[key])) refuse(`${where}: ${key} is missing or a placeholder`);
  if (row.vector != null) {
    // A present vector must be whole: a half-filled one reads as independent coverage nobody designed.
    for (const key of ["input", "expected", "rejects", "source"]) if (!cell(row.vector?.[key])) refuse(`${where}: vector.${key} is missing`);
  }
  if (row.discharge != null) {
    for (const key of ["test", "result", "path_exercised", "counterfactual_result"]) if (!cell(row.discharge?.[key])) refuse(`${where}: discharge.${key} is missing`);
  }
}

function checkQuestion(ticket, q) {
  const where = `ticket ${ticket.key} question ${q?.id ?? "?"}`;
  if (!isObject(q) || !/^[a-z][a-z-]*[0-9]+$/.test(q.id ?? "")) refuse(`${where}: needs an id like q1, pr1, nc1, cr-e1, pr-f1`);
  if (!text(q.question)) refuse(`${where}: no question text`);
  if (!Array.isArray(q.options) || q.options.length < 2 || !q.options.every(text)) refuse(`${where}: needs at least two options`);
  if (!text(q.recommendation)) refuse(`${where}: every question carries a recommendation`);
  if (typeof q.blocking !== "boolean") refuse(`${where}: blocking must be true or false`);
  if (q.blocking && q.default != null) refuse(`${where}: a blocking question has no default; the run never decides it`);
  if (!q.blocking && !text(q.default)) refuse(`${where}: a non-blocking question needs the default the run will take`);
  if (q.answer != null && !text(q.answer)) refuse(`${where}: answer must be the owner's words or null`);
}

function checkDecisions(ticket) {
  const ids = new Set();
  for (const d of ticket.decisions) {
    if (!isObject(d) || !text(d.id) || !text(d.decision) || !text(d.date)) refuse(`ticket ${ticket.key}: each decision is { id, decision, by, date }`);
    if (ids.has(d.id)) refuse(`ticket ${ticket.key}: duplicate decision ${d.id} (one question, one answer)`);
    ids.add(d.id);
    const q = ticket.questions.find((x) => x.id === d.id);
    if (!q) refuse(`ticket ${ticket.key}: decision ${d.id} answers no recorded question`);
    if (d.by === "owner") continue;
    if (d.by !== "default") refuse(`ticket ${ticket.key}: decision ${d.id} must be by "owner" or "default"`);
    if (q.blocking) refuse(`ticket ${ticket.key}: decision ${d.id} takes a default on a blocking question; the state file is mis-built`);
    if (d.decision !== q.default) refuse(`ticket ${ticket.key}: decision ${d.id} by default must be the recorded default verbatim`);
  }
}

function checkCodeReview(ticket) {
  const cr = ticket.code_review;
  if (cr == null) return;
  const where = `ticket ${ticket.key} code_review`;
  if (!isObject(cr)) refuse(`${where} must be an object or null`);
  if (!Number.isInteger(cr.rounds) || cr.rounds < 0) refuse(`${where}.rounds must be a whole number`);
  if (typeof cr.extra_round !== "boolean") refuse(`${where}.extra_round must be true or false`);
  if (cr.redesign != null && !text(cr.redesign)) refuse(`${where}.redesign must be "<trigger> -> <decision>" or null`);
  // post-op round rule 3 and 10: three rounds, three more after one redesign, one more the owner grants.
  const cap = 3 + (cr.redesign ? 3 : 0) + (cr.extra_round ? 1 : 0);
  if (cr.rounds > cap) refuse(`${where}.rounds ${cr.rounds} is past the cap of ${cap} (post-op round rules 3, 6 and 10)`);
  if (cr.end_state != null && !END_STATES.includes(cr.end_state)) refuse(`${where}.end_state must be clean, capped, escalate or null`);
  if (!Array.isArray(cr.dispositions)) refuse(`${where}.dispositions must be a list`);
  for (const d of cr.dispositions) {
    if (!isObject(d) || !Number.isInteger(d.round) || d.round < 1 || d.round > cr.rounds) refuse(`${where}: a disposition names a round that did not run`);
    if (!text(d.finding)) refuse(`${where}: a disposition has no finding text`);
    if (![...CLASSES, "noted"].includes(d.class)) refuse(`${where}: class must be S1-S4 or noted`);
    if (!DISPOSITIONS.includes(d.disposition)) refuse(`${where}: disposition "${d.disposition}" is not one of ${DISPOSITIONS.join(" | ")}`);
  }
}

function checkFindings(ticket) {
  const ids = new Set();
  for (const f of ticket.open_findings) {
    if (!isObject(f) || !text(f.id) || !text(f.finding) || !text(f.source)) refuse(`ticket ${ticket.key}: each open finding is { id, source, finding, class, resolved }`);
    if (ids.has(f.id)) refuse(`ticket ${ticket.key}: duplicate open finding ${f.id}`);
    ids.add(f.id);
    if (![...CLASSES, "noted"].includes(f.class)) refuse(`ticket ${ticket.key}: open finding ${f.id} class must be S1-S4 or noted`);
    if (typeof f.resolved !== "boolean") refuse(`ticket ${ticket.key}: open finding ${f.id} resolved must be true or false`);
  }
}

function checkBlockedWork(ticket) {
  const w = ticket.blocked_work;
  if (w == null) return;
  const where = `ticket ${ticket.key} blocked_work`;
  if (!isObject(w)) refuse(`${where} must be an object or null`);
  if (!text(w.branch) || !/^[0-9a-f]{7,64}$/.test(w.commit ?? "") || !text(w.reason)) refuse(`${where} needs branch, commit and reason`);
  if (w.checkpoint_kind !== CHECKPOINT_KIND) refuse(`${where}.checkpoint_kind must be "${CHECKPOINT_KIND}"`);
  if (!["clean", "failed"].includes(w.diff_check)) refuse(`${where}.diff_check must be clean or failed`);
}

function checkTicket(ticket) {
  if (!isObject(ticket) || !KEY.test(ticket.key ?? "")) refuse(`queue entry has an invalid ticket key: ${JSON.stringify(ticket?.key)}`);
  const k = ticket.key;
  if (!STATES.includes(ticket.state)) refuse(`ticket ${k} has an invalid state ${JSON.stringify(ticket.state)}`);
  if (!text(ticket.title)) refuse(`ticket ${k} has no title`);
  if (typeof ticket.runtime_verifiable !== "boolean") refuse(`ticket ${k}: runtime_verifiable must be true or false`);
  for (const key of ["verify_how", "regression_test", "constraints", "notes"]) if (typeof ticket[key] !== "string") refuse(`ticket ${k}: ${key} must be a string ("none" when empty)`);
  if (ticket.state === "blocked" && !text(ticket.reason)) refuse(`ticket ${k} is blocked without a reason`);
  if (ticket.pr != null && (!Number.isInteger(ticket.pr) || ticket.pr < 1)) refuse(`ticket ${k}: pr must be a PR number or null`);
  if (ticket.peer_review != null && !["run", "skip"].includes(ticket.peer_review)) refuse(`ticket ${k}: peer_review must be "run", "skip" or null`);
  if (ticket.triage != null) {
    const t = ticket.triage;
    if (!isObject(t) || !TRIAGE_STATUSES.includes(t.status) || !text(t.date) || !Array.isArray(t.files) || !text(t.summary)) refuse(`ticket ${k}: triage must be { date, status, premise, files, summary }`);
  }
  for (const key of ["contract", "questions", "decisions", "open_findings"]) if (!Array.isArray(ticket[key])) refuse(`ticket ${k}: ${key} must be a list`);
  if (ticket.contract.length && ticket.contract_note != null) refuse(`ticket ${k} mixes contract rows with a contract_note`);
  if (ticket.contract_note != null && ticket.contract_note !== "no executable behavior") refuse(`ticket ${k}: contract_note may only be "no executable behavior"`);
  if (ticket.threat_model != null && !text(ticket.threat_model)) refuse(`ticket ${k}: threat_model must be one line or null`);
  const rowIds = new Set();
  for (const row of ticket.contract) { checkRow(ticket, row); if (rowIds.has(row.id)) refuse(`ticket ${k} has duplicate contract row ${row.id}`); rowIds.add(row.id); }
  const qIds = new Set();
  for (const q of ticket.questions) { checkQuestion(ticket, q); if (qIds.has(q.id)) refuse(`ticket ${k} has duplicate question ${q.id}`); qIds.add(q.id); }
  checkDecisions(ticket);
  checkFindings(ticket);
  checkCodeReview(ticket);
  checkBlockedWork(ticket);
}

// What makes a ticket executable-ready: a triage record and either a full contract (threat model, at least one
// independent vector) or the explicit docs-only note. An empty contract with no note is untriaged: an audit over
// nothing passes trivially and reports green.
export function triageGaps(ticket) {
  const gaps = [];
  if (ticket.triage == null) gaps.push("no triage record");
  else if (!["DONE", "DONE_WITH_CONCERNS"].includes(ticket.triage.status)) gaps.push(`triage status ${ticket.triage.status}`);
  if (ticket.contract_note === "no executable behavior") return gaps;
  if (!ticket.contract.length) gaps.push("empty contract with no contract_note");
  else {
    if (!text(ticket.threat_model)) gaps.push("no threat model");
    if (!ticket.contract.some((row) => row.vector != null)) gaps.push("no pre-code vectors");
  }
  return gaps;
}

const unansweredBlocking = (ticket) => ticket.questions.filter((q) => q.blocking && q.answer == null);
const unresolved = (ticket) => ticket.open_findings.filter((f) => !f.resolved);
const undischarged = (ticket) => ticket.contract.filter((row) => row.discharge == null);

export function checkState(state) {
  if (!isObject(state)) refuse("state must be a JSON object");
  if (!TRAIN_NAME.test(state.name ?? "")) refuse("name must be kebab-case");
  if (!Number.isInteger(state.revision) || state.revision < 0) refuse("revision is missing or invalid");
  if (!DATE.test(state.created ?? "")) refuse("created must be a YYYY-MM-DD date");
  if (typeof state.triage_required !== "boolean") refuse("triage_required must be true or false");
  if (state.triaged != null && !text(state.triaged)) refuse("triaged must be a date or null");
  if (state.halt != null && !text(state.halt)) refuse("halt must be a reason or null");
  checkRules(state.rules);
  for (const key of ["queue", "candidates", "unqueued_work", "excluded"]) if (!Array.isArray(state[key])) refuse(`${key} must be a list`);
  const keys = new Set();
  for (const ticket of state.queue) {
    checkTicket(ticket);
    if (keys.has(ticket.key)) refuse(`ticket ${ticket.key} is queued twice`);
    keys.add(ticket.key);
  }
  for (const x of state.excluded) if (!isObject(x) || !text(x.key) || !text(x.reason)) refuse("each excluded entry is { key, reason, unblock_by }");
  return state;
}

// ---------------------------------------------------------------- history checks (before -> after)

function appendOnly(label, before, after, mayChange = () => false) {
  const was = list(before), now = list(after);
  if (now.length < was.length) refuse(`${label} is append-only: an update may not remove entries`);
  was.forEach((item, i) => { if (!same(item, now[i]) && !mayChange(item, now[i])) refuse(`${label} is append-only: entry ${i + 1} was rewritten`); });
}

function keepContract(k, before, after) {
  for (const old of before.contract) {
    const next = after.contract.find((row) => row.id === old.id);
    if (!next) refuse(`ticket ${k}: update would remove contract row ${old.id}; amend by adding a row`);
    const { vector: ov, discharge: od, ...oldFixed } = old;
    const { vector: nv, discharge: nd, ...nextFixed } = next;
    if (!same(oldFixed, nextFixed)) refuse(`ticket ${k}: update would rewrite contract row ${old.id}; amend by adding a row`);
    // A vector may be added late, never rewritten or dropped: that is how an independent vector gets swapped.
    if (ov != null && !same(ov, nv)) refuse(`ticket ${k}: contract row ${old.id} vector is immutable once recorded`);
    if (od != null && !same(od, nd)) refuse(`ticket ${k}: contract row ${old.id} discharge is immutable once recorded`);
  }
  if (before.contract_note != null && after.contract_note !== before.contract_note) refuse(`ticket ${k}: contract_note is immutable once recorded`);
  if (text(before.threat_model) && after.threat_model !== before.threat_model) refuse(`ticket ${k}: threat_model is immutable once recorded`);
}

function keepTicket(before, after) {
  const k = after.key;
  if (before === NEW_ENTRY && after.state !== "pending") refuse(`ticket ${k} is being added to the queue and must arrive as pending`);
  if (before.state !== after.state && !TRANSITIONS[before.state]?.includes(after.state)) refuse(`ticket ${k}: invalid transition ${before.state} -> ${after.state}`);
  keepContract(k, before, after);
  // A question is fixed once asked; only its answer may be filled in, once.
  appendOnly(`ticket ${k} questions`, before.questions, after.questions, (a, b) => {
    const { answer: aa, ...ra } = a, { answer: ba, ...rb } = b ?? {};
    return same(ra, rb) && aa == null && text(ba);
  });
  appendOnly(`ticket ${k} decisions`, before.decisions, after.decisions);
  // Evidence is never erased: a finding can only go from unresolved to resolved.
  appendOnly(`ticket ${k} open_findings`, before.open_findings, after.open_findings, (a, b) => {
    const { resolved: ar, ...ra } = a, { resolved: br, ...rb } = b ?? {};
    return same(ra, rb) && ar === false && br === true;
  });
  if (before.code_review != null) {
    const b = before.code_review, a = after.code_review;
    if (a == null) refuse(`ticket ${k}: update would erase the code_review record`);
    if (a.rounds < b.rounds) refuse(`ticket ${k}: code_review.rounds never decreases (rounds are counted per ticket, not per run)`);
    if (b.extra_round && !a.extra_round) refuse(`ticket ${k}: code_review.extra_round cannot be taken back`);
    if (b.redesign != null && a.redesign !== b.redesign) refuse(`ticket ${k}: code_review.redesign is recorded once per ticket`);
    appendOnly(`ticket ${k} code_review.dispositions`, b.dispositions, a.dispositions);
  }
  if (before.blocked_work != null && after.blocked_work == null) refuse(`ticket ${k}: blocked_work is kept as evidence until the ticket is done`);
  if (before.pr != null && after.pr == null) refuse(`ticket ${k}: a recorded PR number is never cleared`);

  if (after.state === "pending" && ["blocked", "awaiting_answer"].includes(before.state)) {
    const open = unansweredBlocking(after);
    if (open.length) refuse(`ticket ${k} returns to pending only once its blocking questions are answered: ${open.map((q) => q.id).join(", ")}`);
  }
  if (after.state === "in_progress" && before.state !== "in_progress") {
    const gaps = triageGaps(after);
    if (gaps.length) refuse(`ticket ${k} is untriaged (${gaps.join("; ")}); block it back to /ticket-train-triage`);
    const open = unansweredBlocking(after);
    if (open.length) refuse(`ticket ${k} has unanswered blocking questions: ${open.map((q) => q.id).join(", ")}`);
  }
  if (["done", "needs_verify"].includes(after.state) && after.state !== before.state) {
    if (after.pr == null) refuse(`ticket ${k} cannot be ${after.state} without a recorded PR`);
    const rows = undischarged(after);
    if (rows.length) refuse(`ticket ${k} cannot be ${after.state}: contract rows not discharged: ${rows.map((r) => r.id).join(", ")}`);
    const open = unresolved(after);
    if (open.length) refuse(`ticket ${k} cannot be ${after.state} with unresolved findings: ${open.map((f) => f.id).join(", ")}`);
    const qs = unansweredBlocking(after);
    if (qs.length) refuse(`ticket ${k} cannot be ${after.state} with unanswered blocking questions: ${qs.map((q) => q.id).join(", ")}`);
  }
}

function keepTrain(before, after) {
  for (const key of ["name", "created"]) if (after[key] !== before[key]) refuse(`${key} is immutable`);
  for (const key of ["forbidden", "pre_authorized", "base_branch"]) if (!same(after.rules[key], before.rules[key])) refuse(`rules.${key} is recorded once, at create, and never changed`);
  appendOnly("unqueued_work", before.unqueued_work, after.unqueued_work);
  const old = new Map(before.queue.map((t) => [t.key, t]));
  for (const ticket of after.queue) keepTicket(old.get(ticket.key) ?? NEW_ENTRY, ticket);
  const now = new Set(after.queue.map((t) => t.key));
  for (const key of old.keys()) if (!now.has(key)) refuse(`update would remove queued ticket ${key}`);
}

export function applyPatch(state, { target, expectedRevision, patch }) {
  checkState(state);
  if (state.revision !== expectedRevision) refuse(`stale revision: expected ${expectedRevision}, found ${state.revision}; re-read the file and retry`);
  if (!isObject(patch)) refuse("the patch must be a JSON object");
  if ("revision" in patch) refuse("a patch may not set revision; the helper advances it");
  const next = structuredClone(state);
  if (target === "train") {
    if ("key" in patch) refuse("a train patch may not carry a ticket key");
    Object.assign(next, patch);
  } else {
    const ticket = next.queue.find((t) => t.key === target);
    if (!ticket) refuse(`no such ticket in the queue: ${target}`);
    if ("key" in patch && patch.key !== target) refuse("a patch may not change a ticket's key");
    Object.assign(ticket, patch);
  }
  checkState(next);
  keepTrain(state, next);
  next.revision = state.revision + 1;
  return next;
}

export function newTrain(state) {
  if (!isObject(state)) refuse("the new train must be a JSON object");
  if (state.revision !== 0) refuse("a new train starts at revision 0");
  checkState(state);
  for (const ticket of state.queue) if (ticket.state !== "pending") refuse(`ticket ${ticket.key} must start as pending`);
  return state;
}

// ---------------------------------------------------------------- summary (read-only)

export function summarize(state, key) {
  checkState(state);
  const counts = Object.fromEntries(STATES.map((s) => [s, 0]));
  for (const t of state.queue) counts[t.state]++;
  const ticketView = (t) => ({
    key: t.key, state: t.state, title: t.title, pr: t.pr ?? null, reason: t.reason ?? null, result: t.result ?? null,
    peer_review: t.peer_review ?? "undecided", verify_how: t.verify_how, constraints: t.constraints,
    triaged: t.triage != null, triage_gaps: triageGaps(t),
    decisions: t.decisions.length, defaults: t.decisions.filter((d) => d.by === "default").length,
    code_review: t.code_review ? { rounds: t.code_review.rounds, end_state: t.code_review.end_state ?? null, extra_round: t.code_review.extra_round, redesign: t.code_review.redesign ?? null } : null,
    open_questions: t.questions.filter((q) => q.answer == null).map((q) => ({ id: q.id, blocking: q.blocking, default: q.default ?? null, question: q.question })),
    unresolved_findings: unresolved(t).map((f) => f.id),
    undischarged_rows: t.contract_note ? [] : undischarged(t).map((r) => r.id),
    blocked_work: t.blocked_work ? { branch: t.blocked_work.branch, commit: t.blocked_work.commit } : null,
  });
  if (key != null) {
    const t = state.queue.find((x) => x.key === key);
    if (!t) refuse(`no such ticket in the queue: ${key}`);
    return { train: state.name, revision: state.revision, ticket: ticketView(t) };
  }
  const pending = state.queue.filter((t) => t.state === "pending");
  const notReady = [];
  if (state.triage_required && state.triaged == null) notReady.push("train not triaged");
  for (const t of pending) {
    const gaps = triageGaps(t);
    if (gaps.length) notReady.push(`${t.key}: ${gaps.join("; ")}`);
    const qs = unansweredBlocking(t);
    if (qs.length) notReady.push(`${t.key}: unanswered blocking ${qs.map((q) => q.id).join(", ")}`);
  }
  if (state.halt != null) notReady.push(`halted: ${state.halt}`);
  return {
    train: state.name, revision: state.revision, created: state.created, triaged: state.triaged ?? null,
    base_branch: state.rules.base_branch, adversarial: state.rules.adversarial, halt: state.halt ?? null,
    total: state.queue.length, counts,
    // needs_verify is merged but not confirmed: it is never counted as done.
    done: counts.done, complete: state.queue.every((t) => t.state === "done"),
    next: pending[0]?.key ?? null, ready_to_run: notReady.length === 0 && pending.length > 0, not_ready: notReady,
    tickets: state.queue.map(ticketView),
    candidates: state.candidates, unqueued_work: state.unqueued_work, excluded: state.excluded,
  };
}

// ---------------------------------------------------------------- file I/O (locked, atomic, never deletes)

function readJson(path) {
  let raw;
  try { raw = readFileSync(path, "utf8"); } catch (e) { refuse(`cannot read ${path}: ${e.code ?? e.message}`); }
  try { return JSON.parse(raw); } catch (e) { refuse(`${path} is not valid JSON: ${e.message}`); }
}

function patchArg(arg) {
  if (typeof arg !== "string") refuse("missing JSON argument");
  const raw = arg.startsWith("@") ? (() => { try { return readFileSync(arg.slice(1), "utf8"); } catch (e) { refuse(`cannot read ${arg.slice(1)}: ${e.code ?? e.message}`); } })() : arg;
  try { return JSON.parse(raw); } catch (e) { refuse(`the JSON argument does not parse: ${e.message}`); }
}

function withLock(path, fn, { staleLockMs = STALE_LOCK_MS } = {}) {
  const lock = `${path}.lock`;
  if (existsSync(lock)) {
    const age = Date.now() - statSync(lock).mtimeMs;
    if (age <= staleLockMs) refuse("the train state is locked by another live update; retry in a moment");
    refuse(`stale lock ${lock}: confirm no other run is writing this train, then rename it to ${lock}.stale-<date> and retry`);
  }
  let fd;
  try { fd = openSync(lock, "wx"); } catch (e) { refuse(e.code === "EEXIST" ? "the train state is locked by another live update; retry in a moment" : `cannot take the lock: ${e.code ?? e.message}`); }
  try {
    writeFileSync(fd, `pid ${process.pid} at ${new Date().toISOString()}\n`);
    closeSync(fd); fd = undefined;
    return fn();
  } finally {
    if (fd !== undefined) closeSync(fd);
    // Released by rename, never by deletion. The previous .released file is replaced by the rename.
    try { renameSync(lock, `${lock}.released`); } catch (e) { process.stderr.write(`train-state: could not release ${lock} (${e.code ?? e.message}); rename it by hand\n`); }
  }
}

function writeAtomic(path, state) {
  // The lock makes this writer the only one, so one fixed temp name is safe. A failed write leaves the temp file
  // behind; the next write overwrites it.
  const temp = `${path}.tmp`;
  writeFileSync(temp, `${JSON.stringify(state, null, 2)}\n`, { mode: 0o600 });
  renameSync(temp, path);
}

export function createFile(path, state, opts) {
  // The state folder may not exist yet on a first train; making it here keeps `mkdir` out of the command recipe.
  try { mkdirSync(dirname(path), { recursive: true }); } catch (e) { refuse(`cannot create ${dirname(path)}: ${e.code ?? e.message}`); }
  return withLock(path, () => {
    if (existsSync(path)) refuse(`${path} already exists; never overwrite a train`);
    const next = newTrain(state);
    writeAtomic(path, next);
    return next;
  }, opts);
}

export function updateFile(path, request, opts) {
  return withLock(path, () => {
    const next = applyPatch(readJson(path), request);
    writeAtomic(path, next);
    return next;
  }, opts);
}

// ---------------------------------------------------------------- CLI

const USAGE = "usage: train-state.mjs create <file> <json|@path> | update <file> <train|ticket> <expected-revision> <json|@path> | preview <file> <train|ticket> <expected-revision> <json|@path> | summary <file> [<ticket>]";

function revisionArg(value) {
  if (!/^[0-9]+$/.test(value ?? "")) refuse("expected-revision must be a whole number");
  return Number(value);
}

export function main(argv) {
  const [command, ...args] = argv;
  const out = (value) => process.stdout.write(`${JSON.stringify(value)}\n`);
  try {
    if (command === "create" && args.length === 2) {
      const next = createFile(args[0], patchArg(args[1]));
      out({ state: "created", train: next.name, revision: next.revision });
    } else if (command === "update" && args.length === 4) {
      const next = updateFile(args[0], { target: args[1], expectedRevision: revisionArg(args[2]), patch: patchArg(args[3]) });
      out({ state: "updated", target: args[1], revision: next.revision });
    } else if (command === "preview" && args.length === 4) {
      out(applyPatch(readJson(args[0]), { target: args[1], expectedRevision: revisionArg(args[2]), patch: patchArg(args[3]) }));
    } else if (command === "summary" && (args.length === 1 || args.length === 2)) {
      out(summarize(readJson(args[0]), args[1]));
    } else {
      process.stderr.write(`${USAGE}\n`);
      return 2;
    }
    return 0;
  } catch (error) {
    process.stderr.write(`train-state: ${error instanceof Refusal ? error.message : `internal error: ${error.message}`}\n`);
    return 1;
  }
}

const invoked = process.argv[1] && (() => { try { return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url)); } catch { return false; } })();
if (invoked) process.exitCode = main(process.argv.slice(2));
