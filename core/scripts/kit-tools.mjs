#!/usr/bin/env node
// Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
// kit-tools: the one implementation of the review-loop hashes, so no command grows its own shell recipe.
// Node >= 18, no dependencies. The interface below is fixed by agent-kit; change it there, not in a project copy.
//
//   fingerprint  --base <rev>                                  sha256 of the reviewable merge-base diff
//   freeze       --base <rev> --contract <file> --out <dir>    writes base.txt, patch.diff, contract.md; prints the snapshot hash
//   covered      --hash <h> --base <rev>                       exit 0 when the current fingerprint equals <h>
//   check-review --file <f> --hash <h> [--lenses <n>] [--contract <file>]
//                                                              validates a reviewer's output; prints CLEAN|FINDINGS
//
// On success a command prints one line on stdout. On any refusal or failure it prints nothing on stdout, one line on
// stderr, and exits 1 (usage errors exit 2). The tool never fetches: the caller runs `git fetch` first. It never
// writes to the git index or the working tree; `freeze` writes only inside --out.

import { mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { devNull } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

// Docs-only paths are not reviewable changes: Markdown under docs/ and READMEs anywhere. Editing them never moves the
// fingerprint, and an untracked one is not refused. Paths are relative to the repo top level.
export const DOCS_ONLY_PATHSPECS = [":(glob,exclude)docs/**/*.md", ":(glob,exclude)**/README.md"];

// Lenses every review brief carries: 7 generic ones plus the one generated from <CRITICAL_DOMAIN>/<CRITICAL_SYSTEMS>.
// Packs that add lenses pass the new total with --lenses.
export const CORE_LENS_COUNT = 8;

// sha256 of zero bytes: the hash of an empty diff, which covers nothing.
export const EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";

// `git diff` text depends on config (prefixes, colour, algorithm, context, order file, abbreviation, quoting) as well as
// on content. Pin every one of them so two machines, or one machine a month apart, hash the same change identically.
// No --binary: its base85 body depends on core.compression; --full-index already names a binary's exact content.
const DETERMINISTIC_DIFF = [
  "-c", "diff.noprefix=false", "-c", "diff.mnemonicPrefix=false", "-c", "diff.algorithm=myers",
  "-c", "core.quotePath=false", "-c", "color.ui=never", "-c", "diff.suppressBlankEmpty=false",
  "diff", "--full-index", "--no-color", "--no-ext-diff", "--no-textconv", "--no-renames",
  "-U3", "--inter-hunk-context=0", `-O${devNull}`, "--indent-heuristic", "--src-prefix=a/", "--dst-prefix=b/",
];

const SHA256_HEX = /^[a-f0-9]{64}$/;

class Refusal extends Error {}

const firstLine = (text) => String(text ?? "").trim().split("\n")[0].trim();

// Never block on a credential prompt; read env at call time so callers (and tests) can isolate git config.
const gitEnv = () => ({ ...process.env, GIT_TERMINAL_PROMPT: "0", GIT_SSH_COMMAND: process.env.GIT_SSH_COMMAND ?? "ssh -o BatchMode=yes" });

function git(args, cwd, binary = false) {
  try {
    return execFileSync("git", args, {
      cwd, env: gitEnv(), timeout: 120_000, maxBuffer: 256 * 1024 * 1024,
      encoding: binary ? "buffer" : "utf8", stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (error) {
    const sub = args.find((a, i) => a !== "-c" && args[i - 1] !== "-c");
    const reason = firstLine(error.stderr) || firstLine(error.message) || "no output";
    throw new Refusal(`git failed: git ${sub}: ${reason}`);
  }
}

function repoTop(cwd) {
  return String(git(["rev-parse", "--show-toplevel"], cwd)).trim();
}

function mergeBase(top, base) {
  return String(git(["merge-base", base, "HEAD"], top)).trim();
}

function untracked(top, pathspecs) {
  return String(git(["ls-files", "--others", "--exclude-standard", "--", ".", ...pathspecs], top)).trim();
}

// The diff from the merge-base to the working tree. It includes staged and unstaged edits to tracked files and every
// intent-to-add file (`git add -N`). Untracked files are invisible to `git diff`, so they are refused rather than
// silently left out; the caller adds the intended ones with `git add -N`. The tool itself never touches the index.
function workingDiff(top, base, pathspecs) {
  const stray = untracked(top, pathspecs);
  if (stray) throw new Refusal(`untracked files (git add -N the intended ones, or gitignore them): ${stray.split("\n").join(", ")}`);
  const mb = mergeBase(top, base);
  const diff = git([...DETERMINISTIC_DIFF, mb, "--", ".", ...pathspecs], top, true);
  if (diff.length === 0) throw new Refusal(`empty diff against ${base}: nothing to hash`);
  return { mergeBase: mb, diff };
}

const sha256 = (...parts) => {
  const h = createHash("sha256");
  for (const p of parts) h.update(p);
  return h.digest("hex");
};

export function fingerprint({ base, cwd = process.cwd() }) {
  const top = repoTop(cwd);
  const hash = sha256(workingDiff(top, base, DOCS_ONLY_PATHSPECS).diff);
  if (hash === EMPTY_SHA256) throw new Refusal(`empty diff against ${base}: nothing to hash`);
  return hash;
}

export function covered({ hash, base, cwd = process.cwd() }) {
  const current = fingerprint({ base, cwd });
  if (current !== hash) throw new Refusal(`not covered: current fingerprint ${current} differs from ${hash}`);
  return current;
}

const CONTRACT_ROW = /^\|\s*(C\d+)\s*\|/;

function contractIds(text) {
  const ids = [];
  for (const line of text.replaceAll("\r", "").split("\n")) {
    const m = CONTRACT_ROW.exec(line.trim());
    if (!m) continue;
    if (!/^C[1-9]\d*$/.test(m[1])) throw new Refusal(`invalid contract id ${m[1]}`);
    if (ids.includes(m[1])) throw new Refusal(`duplicate contract row ${m[1]}`);
    ids.push(m[1]);
  }
  return ids;
}

// The frozen review artifact. The patch is the whole merge-base diff, docs included, so reviewers see everything and
// any later edit makes the snapshot stale. The hash covers base.txt + patch.diff + contract.md, in that order.
export function freeze({ base, contract, out, cwd = process.cwd() }) {
  let contractText;
  try { contractText = readFileSync(contract); } catch (error) { throw new Refusal(`cannot read contract ${contract}: ${firstLine(error.message)}`); }
  const asText = contractText.toString("utf8");
  if (!asText.trim()) throw new Refusal(`contract ${contract} is empty`);
  if (!contractIds(asText).length && !/^NO CONTRACT: \S/m.test(asText)) {
    throw new Refusal(`contract ${contract} has no C<n> rows and no "NO CONTRACT: <reason>" line`);
  }
  const top = repoTop(cwd);
  const { mergeBase: mb, diff } = workingDiff(top, base, []);
  const baseText = Buffer.from(`${mb}\n`);
  try {
    mkdirSync(out, { recursive: true });
    writeFileSync(join(out, "base.txt"), baseText);
    writeFileSync(join(out, "patch.diff"), diff);
    writeFileSync(join(out, "contract.md"), contractText);
  } catch (error) {
    throw new Refusal(`cannot write snapshot to ${out}: ${firstLine(error.message)}`);
  }
  return sha256(baseText, diff, contractText);
}

const STATUS = /^(\d+)\)\s+(Clean|Finding)\s+[—–-]\s+\S/;
const FIELDS = ["Lens", "Severity", "Basis", "Path", "Reproduction", "Observed", "Required"];
const FIELD = /^(Lens|Severity|Basis|Path|Reproduction|Observed|Required):\s*(.*)$/;

// A reviewer's output counts only when it is complete and bound to the frozen snapshot. Anything missing or out of
// shape is UNAVAILABLE, never clean.
export function checkReview({ text, hash, lenses = CORE_LENS_COUNT, contractText = null }) {
  const lines = text.replaceAll("\r", "").split("\n").map((l) => l.trim()).filter(Boolean);
  if (!lines.length) throw new Refusal("review output is empty");
  if (lines[0] !== `REVIEW_HASH: ${hash}`) throw new Refusal("review does not begin with REVIEW_HASH: <frozen hash>");
  if (lines.at(-1) !== "REVIEW_COMPLETE") throw new Refusal("review does not end with REVIEW_COMPLETE (incomplete output)");

  const statuses = new Map();
  for (const line of lines) {
    const m = STATUS.exec(line);
    if (!m) continue;
    const n = Number(m[1]);
    if (statuses.has(n)) throw new Refusal(`lens ${n} has more than one status line`);
    if (n !== statuses.size + 1) throw new Refusal(`lens status ${n} is out of order or lens ${statuses.size + 1} is missing`);
    statuses.set(n, m[2]);
  }
  if (statuses.size !== lenses) throw new Refusal(`review has ${statuses.size} lens status lines, expected ${lenses}`);

  const ids = contractText == null ? null : contractIds(contractText);
  const findings = [];
  for (let i = 0; i < lines.length; i++) {
    if (lines[i] !== "FINDING:") continue;
    const block = {};
    for (i++; i < lines.length && lines[i] !== "FINDING:" && lines[i] !== "REVIEW_COMPLETE"; i++) {
      const m = FIELD.exec(lines[i]);
      if (!m) continue;
      if (m[1] in block) throw new Refusal(`a finding repeats ${m[1]}`);
      block[m[1]] = m[2].trim();
    }
    i--;
    for (const f of FIELDS) if (!block[f]) throw new Refusal(`a finding lacks ${f}`);
    if (statuses.get(Number(block.Lens)) !== "Finding" || !/^\d+$/.test(block.Lens)) throw new Refusal(`a finding names lens ${block.Lens}, which is not a Finding lens`);
    if (!/^(CRITICAL|MAJOR|MINOR)$/.test(block.Severity)) throw new Refusal(`a finding has invalid severity ${block.Severity}`);
    if (/^C[1-9]\d*$/.test(block.Basis)) {
      if (ids && !ids.includes(block.Basis)) throw new Refusal(`a finding names unknown contract row ${block.Basis}`);
    } else if (block.Basis === "SAFETY_EXCEPTION") {
      if (block.Severity !== "CRITICAL") throw new Refusal("a SAFETY_EXCEPTION finding must be CRITICAL");
    } else if (block.Basis !== "CHANGED_PATH") {
      throw new Refusal("a finding's Basis must be C<n>, CHANGED_PATH or SAFETY_EXCEPTION");
    }
    findings.push(block);
  }
  for (const [n, status] of statuses) {
    const has = findings.some((f) => Number(f.Lens) === n);
    if ((status === "Finding") !== has) throw new Refusal(`lens ${n} says ${status} but its FINDING blocks disagree`);
  }
  const observations = lines.filter((l) => l.startsWith("OBSERVATION:")).length;
  return { result: findings.length ? "FINDINGS" : "CLEAN", lenses: statuses.size, findings: findings.length, observations };
}

// ---------------------------------------------------------------------------------------------------------------- CLI

const USAGE = "usage: kit-tools.mjs fingerprint --base <rev> | freeze --base <rev> --contract <file> --out <dir> | covered --hash <h> --base <rev> | check-review --file <f> --hash <h> [--lenses <n>] [--contract <file>]";

const SPEC = {
  fingerprint: { required: ["base"], optional: [] },
  freeze: { required: ["base", "contract", "out"], optional: [] },
  covered: { required: ["hash", "base"], optional: [] },
  "check-review": { required: ["file", "hash"], optional: ["lenses", "contract"] },
};

class Usage extends Error {}

function parse(argv) {
  const [command, ...rest] = argv;
  const spec = SPEC[command];
  if (!spec) throw new Usage(USAGE);
  const opts = {};
  for (let i = 0; i < rest.length; i += 2) {
    const name = rest[i]?.startsWith("--") ? rest[i].slice(2) : null;
    if (!name || ![...spec.required, ...spec.optional].includes(name) || rest[i + 1] == null || name in opts) throw new Usage(USAGE);
    opts[name] = rest[i + 1];
  }
  for (const r of spec.required) if (!opts[r]) throw new Usage(USAGE);
  return { command, opts };
}

function main(argv) {
  const { command, opts } = parse(argv);
  if ("hash" in opts && !SHA256_HEX.test(opts.hash)) throw new Refusal(`--hash is not a 64-character lowercase sha256: ${opts.hash}`);
  if (command === "fingerprint") return fingerprint({ base: opts.base });
  if (command === "covered") return `covered ${covered({ hash: opts.hash, base: opts.base })}`;
  if (command === "freeze") return freeze({ base: opts.base, contract: opts.contract, out: opts.out });
  // check-review
  const lenses = opts.lenses == null ? CORE_LENS_COUNT : Number(opts.lenses);
  if (!Number.isInteger(lenses) || lenses < 1) throw new Usage(USAGE);
  let text, contractText = null;
  try { text = readFileSync(opts.file, "utf8"); } catch { throw new Refusal(`UNAVAILABLE: review output ${opts.file} is missing`); }
  if (opts.contract != null) {
    try { contractText = readFileSync(opts.contract, "utf8"); } catch { throw new Refusal(`cannot read contract ${opts.contract}`); }
  }
  try {
    const r = checkReview({ text, hash: opts.hash, lenses, contractText });
    return `${r.result} ${r.lenses} lenses, ${r.findings} findings, ${r.observations} observations`;
  } catch (error) {
    if (error instanceof Refusal) throw new Refusal(`UNAVAILABLE: ${error.message}`);
    throw error;
  }
}

const isMain = (() => {
  try { return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url)); } catch { return false; }
})();

if (isMain) {
  try {
    process.stdout.write(`${main(process.argv.slice(2))}\n`);
  } catch (error) {
    const usage = error instanceof Usage;
    process.stderr.write(`kit-tools: ${usage ? error.message : firstLine(error.message)}\n`);
    process.exitCode = usage ? 2 : 1;
  }
}
