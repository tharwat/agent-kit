// Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
// Tests for kit-tools.mjs. Run: node --test <path to this file>
//
// Each test builds a throwaway git repo under fs.mkdtemp in the OS temp dir. Nothing here deletes anything: the temp
// dirs are left for the OS to reap, by design (the kit never runs a delete, in code or in instructions).

import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir, devNull } from "node:os";
import { join, dirname } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const CLI = join(dirname(fileURLToPath(import.meta.url)), "kit-tools.mjs");

// Keep the developer's global/system git config out, so signing, hooks or diff settings can't change the result.
const ENV = {
  ...process.env,
  GIT_CONFIG_GLOBAL: devNull, GIT_CONFIG_NOSYSTEM: "1",
  GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@example.invalid", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@example.invalid",
};

function git(cwd, ...args) {
  const r = spawnSync("git", args, { cwd, env: ENV, encoding: "utf8" });
  assert.equal(r.status, 0, `git ${args.join(" ")}: ${r.stderr}`);
  return r.stdout;
}

function kit(cwd, ...args) {
  return spawnSync(process.execPath, [CLI, ...args], { cwd, env: ENV, encoding: "utf8" });
}

function ok(r) {
  assert.equal(r.status, 0, `expected success, got ${r.status}: ${r.stderr}`);
  assert.equal(r.stderr, "");
  return r.stdout.trim();
}

function refused(r, pattern) {
  assert.equal(r.status, 1, `expected exit 1, got ${r.status}: ${r.stdout}`);
  assert.equal(r.stdout, "", "a refusal prints nothing on stdout");
  assert.equal(r.stderr.trim().split("\n").length, 1, "a refusal is one line on stderr");
  assert.match(r.stderr, pattern);
}

// A repo with a local bare origin, a base commit on main, and a feature branch with no changes yet.
function repo() {
  const dir = mkdtempSync(join(tmpdir(), "kit-tools-test-"));
  const bare = join(dir, "origin.git"), work = join(dir, "work");
  git(dir, "init", "-q", "--bare", bare);
  git(dir, "init", "-q", "-b", "main", work);
  git(work, "remote", "add", "origin", bare);
  mkdirSync(join(work, "src")); mkdirSync(join(work, "docs"));
  writeFileSync(join(work, "src", "a.mjs"), "export function a() {\n  return 1;\n}\n");
  writeFileSync(join(work, "docs", "guide.md"), "# Guide\n");
  writeFileSync(join(work, "README.md"), "readme\n");
  git(work, "add", "-A"); git(work, "commit", "-q", "-m", "base"); git(work, "push", "-q", "-u", "origin", "main");
  git(work, "checkout", "-q", "-b", "feature/x");
  return { dir, work };
}

const BASE = ["--base", "origin/main"];
const editCode = (work, body = "return 2;") => writeFileSync(join(work, "src", "a.mjs"), `export function a() {\n  ${body}\n}\n`);

// ---------------------------------------------------------------------------------------------------------- fingerprint

test("fingerprint is stable: same tree, same hash, from any directory and after committing", () => {
  const { work } = repo();
  editCode(work);
  const h = ok(kit(work, "fingerprint", ...BASE));
  assert.match(h, /^[a-f0-9]{64}$/);
  assert.equal(ok(kit(work, "fingerprint", ...BASE)), h);
  assert.equal(ok(kit(join(work, "src"), "fingerprint", ...BASE)), h, "same hash from a subdirectory");
  git(work, "commit", "-q", "-am", "work");
  assert.equal(ok(kit(work, "fingerprint", ...BASE)), h, "committing the same change does not move it (merge-base diff)");
  for (const [k, v] of [["diff.noprefix", "true"], ["color.ui", "always"], ["diff.algorithm", "patience"], ["diff.context", "7"], ["core.abbrev", "12"]]) {
    git(work, "config", k, v);
    assert.equal(ok(kit(work, "fingerprint", ...BASE)), h, `git config ${k}=${v} does not move it`);
  }
});

test("fingerprint ignores a docs-only edit: Markdown under docs/, READMEs, and an untracked doc", () => {
  const { work } = repo();
  editCode(work);
  const h = ok(kit(work, "fingerprint", ...BASE));
  writeFileSync(join(work, "docs", "guide.md"), "# Guide, edited\n");
  writeFileSync(join(work, "README.md"), "readme, edited\n");
  mkdirSync(join(work, "docs", "nested"));
  writeFileSync(join(work, "docs", "nested", "new.md"), "untracked doc\n");
  mkdirSync(join(work, "src", "pkg"));
  writeFileSync(join(work, "src", "pkg", "README.md"), "nested readme\n");
  assert.equal(ok(kit(work, "fingerprint", ...BASE)), h);
});

test("fingerprint changes when code changes, including a tracked-but-uncommitted edit and a git add -N file", () => {
  const { work } = repo();
  editCode(work);
  const h1 = ok(kit(work, "fingerprint", ...BASE));
  editCode(work, "return 3;");
  const h2 = ok(kit(work, "fingerprint", ...BASE));
  assert.notEqual(h2, h1, "an unstaged edit to a tracked file moves it");
  writeFileSync(join(work, "src", "b.mjs"), "export const b = 1;\n");
  git(work, "add", "-N", "src/b.mjs");
  const h3 = ok(kit(work, "fingerprint", ...BASE));
  assert.notEqual(h3, h2, "an intent-to-add file is part of the hash");
  const status = git(work, "status", "--porcelain");
  assert.match(status, / A src\/b\.mjs/, "the tool did not change the index (still intent-to-add)");
});

test("fingerprint refuses untracked files", () => {
  const { work } = repo();
  editCode(work);
  writeFileSync(join(work, "src", "stray.mjs"), "export const s = 1;\n");
  refused(kit(work, "fingerprint", ...BASE), /untracked files.*src\/stray\.mjs/);
});

test("fingerprint refuses an empty diff, and a docs-only diff counts as empty", () => {
  const { work } = repo();
  refused(kit(work, "fingerprint", ...BASE), /empty diff/);
  writeFileSync(join(work, "docs", "guide.md"), "# Guide, edited\n");
  refused(kit(work, "fingerprint", ...BASE), /empty diff/);
});

test("fingerprint names a git failure in one line", () => {
  const { work, dir } = repo();
  editCode(work);
  refused(kit(work, "fingerprint", "--base", "origin/no-such-branch"), /git failed: git merge-base/);
  refused(kit(dir, "fingerprint", ...BASE), /git failed: git rev-parse/);
});

// ------------------------------------------------------------------------------------------------------------- covered

test("covered: exit 0 on a match, exit 1 on a mismatch", () => {
  const { work } = repo();
  editCode(work);
  const h = ok(kit(work, "fingerprint", ...BASE));
  assert.equal(ok(kit(work, "covered", "--hash", h, ...BASE)), `covered ${h}`);
  writeFileSync(join(work, "docs", "guide.md"), "# docs edit after review\n");
  ok(kit(work, "covered", "--hash", h, ...BASE));
  editCode(work, "return 99;");
  refused(kit(work, "covered", "--hash", h, ...BASE), /not covered/);
  refused(kit(work, "covered", "--hash", "nothex", ...BASE), /not a 64-character/);
});

// -------------------------------------------------------------------------------------------------------------- freeze

const CONTRACT = "| ID | Invariant | Discharge |\n|---|---|---|\n| C1 | a() never returns 1 | test a.test.mjs |\n| C2 | b exists | test b.test.mjs |\n";

test("freeze writes base.txt, patch.diff and contract.md, and the hash is stable and covers all three", () => {
  const { dir, work } = repo();
  editCode(work);
  const contract = join(dir, "contract-src.md");
  writeFileSync(contract, CONTRACT);
  const out = join(dir, "snap");
  const h = ok(kit(work, "freeze", ...BASE, "--contract", contract, "--out", out));
  assert.match(h, /^[a-f0-9]{64}$/);
  for (const f of ["base.txt", "patch.diff", "contract.md"]) assert.ok(existsSync(join(out, f)), `${f} written`);
  const mb = git(work, "merge-base", "origin/main", "HEAD").trim();
  assert.equal(readFileSync(join(out, "base.txt"), "utf8"), `${mb}\n`);
  assert.match(readFileSync(join(out, "patch.diff"), "utf8"), /return 2;/);
  assert.equal(readFileSync(join(out, "contract.md"), "utf8"), CONTRACT);

  // stable: same tree and contract, same hash; also when re-checked against the recorded base and its own copy
  assert.equal(ok(kit(work, "freeze", ...BASE, "--contract", contract, "--out", join(dir, "snap2"))), h);
  assert.equal(ok(kit(work, "freeze", "--base", mb, "--contract", join(out, "contract.md"), "--out", join(dir, "recheck"))), h);

  // the hash covers the contract and the docs (reviewers see the whole diff)
  writeFileSync(contract, `${CONTRACT}| C3 | more | test |\n`);
  assert.notEqual(ok(kit(work, "freeze", ...BASE, "--contract", contract, "--out", join(dir, "snap3"))), h);
  writeFileSync(contract, CONTRACT);
  writeFileSync(join(work, "docs", "guide.md"), "# edited\n");
  assert.notEqual(ok(kit(work, "freeze", ...BASE, "--contract", contract, "--out", join(dir, "snap4"))), h);
});

test("freeze refuses untracked files, an empty diff, and a contract with no rows", () => {
  const { dir, work } = repo();
  const contract = join(dir, "contract-src.md");
  writeFileSync(contract, CONTRACT);
  refused(kit(work, "freeze", ...BASE, "--contract", contract, "--out", join(dir, "s1")), /empty diff/);
  editCode(work);
  writeFileSync(join(work, "docs", "untracked.md"), "new doc\n");
  refused(kit(work, "freeze", ...BASE, "--contract", contract, "--out", join(dir, "s2")), /untracked files.*docs\/untracked\.md/);
  git(work, "add", "-N", "docs/untracked.md");
  const empty = join(dir, "no-rows.md");
  writeFileSync(empty, "| ID | Invariant |\n|---|---|\n");
  refused(kit(work, "freeze", ...BASE, "--contract", empty, "--out", join(dir, "s3")), /no C<n> rows/);
  writeFileSync(empty, "NO CONTRACT: work predates triage\n");
  assert.match(ok(kit(work, "freeze", ...BASE, "--contract", empty, "--out", join(dir, "s4"))), /^[a-f0-9]{64}$/);
  const dup = join(dir, "dup.md");
  writeFileSync(dup, `${CONTRACT}| C1 | again | x |\n`);
  refused(kit(work, "freeze", ...BASE, "--contract", dup, "--out", join(dir, "s5")), /duplicate contract row C1/);
});

// -------------------------------------------------------------------------------------------------------- check-review

const HASH = "a".repeat(64);
const LENS_NAMES = ["Integration contract", "Sibling path", "Schema and data shape", "Fail-open and idempotency", "Race and double-fire", "Test coverage", "Backward compatibility", "Critical domain"];

function review({ hash = HASH, finding = 0, drop = 0, complete = true } = {}) {
  const lines = [`REVIEW_HASH: ${hash}`];
  LENS_NAMES.forEach((name, i) => {
    const n = i + 1;
    if (n === drop) return;
    lines.push(`${n}) ${n === finding ? "Finding" : "Clean"} — ${name}`);
  });
  if (finding) lines.push("FINDING:", `Lens: ${finding}`, "Severity: MAJOR", "Basis: C1", "Path: handler → writer", "Reproduction: send the event twice", "Observed: two rows written", "Required: C1 one row per event");
  lines.push("OBSERVATION: the helper name is unclear");
  if (complete) lines.push("REVIEW_COMPLETE");
  return `${lines.join("\n")}\n`;
}

function checkReview(text, ...extra) {
  const dir = mkdtempSync(join(tmpdir(), "kit-tools-review-"));
  const f = join(dir, "review.txt");
  writeFileSync(f, text);
  const contract = join(dir, "contract.md");
  writeFileSync(contract, CONTRACT);
  return kit(dir, "check-review", "--file", f, "--hash", HASH, "--contract", contract, ...extra);
}

test("check-review: a valid clean review is CLEAN; a valid review with a finding is FINDINGS", () => {
  assert.equal(ok(checkReview(review())), "CLEAN 8 lenses, 0 findings, 1 observations");
  assert.equal(ok(checkReview(review({ finding: 4 }))), "FINDINGS 8 lenses, 1 findings, 1 observations");
});

test("check-review: the wrong hash is UNAVAILABLE", () => {
  refused(checkReview(review({ hash: "b".repeat(64) })), /UNAVAILABLE: review does not begin with REVIEW_HASH/);
});

test("check-review: a missing lens status is UNAVAILABLE", () => {
  refused(checkReview(review({ drop: 5 })), /UNAVAILABLE: lens status 6 is out of order or lens 5 is missing/);
  refused(checkReview(review({ drop: 8 })), /UNAVAILABLE: review has 7 lens status lines, expected 8/);
  refused(checkReview(review(), "--lenses", "9"), /UNAVAILABLE: review has 8 lens status lines, expected 9/);
});

test("check-review: missing REVIEW_COMPLETE, or no output at all, is UNAVAILABLE", () => {
  refused(checkReview(review({ complete: false })), /UNAVAILABLE: review does not end with REVIEW_COMPLETE/);
  refused(checkReview(""), /UNAVAILABLE: review output is empty/);
  const dir = mkdtempSync(join(tmpdir(), "kit-tools-review-"));
  refused(kit(dir, "check-review", "--file", join(dir, "absent.txt"), "--hash", HASH), /UNAVAILABLE: review output .* is missing/);
});

test("check-review: a finding must be eligible and match its lens", () => {
  refused(checkReview(review({ finding: 2 }).replace("Basis: C1", "Basis: C9")), /unknown contract row C9/);
  refused(checkReview(review({ finding: 2 }).replace("Basis: C1", "Basis: STYLE")), /Basis must be/);
  refused(checkReview(review({ finding: 2 }).replace("Basis: C1", "Basis: SAFETY_EXCEPTION")), /must be CRITICAL/);
  refused(checkReview(review({ finding: 2 }).replace("Required: C1 one row per event\n", "")), /lacks Required/);
  refused(checkReview(review().replace("2) Clean", "2) Finding")), /lens 2 says Finding but its FINDING blocks disagree/);
});

test("usage errors exit 2", () => {
  const dir = mkdtempSync(join(tmpdir(), "kit-tools-usage-"));
  assert.equal(kit(dir, "fingerprint").status, 2);
  assert.equal(kit(dir, "nope").status, 2);
  assert.equal(kit(dir, "covered", "--hash", HASH).status, 2);
});
