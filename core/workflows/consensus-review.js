// Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
// One code-review round for /post-op Step 1.5. Post-op owns the loop, the cap, the fixes
// and the end states (round rules 1–11); this script only runs a round:
// 3 lens reviewers → dedup in code → 2 refuting verifiers per finding (+1 tie-breaker)
// → classed findings and a redesign signal.
// Run it by scriptPath (<repo root>/.claude/workflows/consensus-review.js), never by name.
export const meta = {
  name: 'consensus-review',
  description: 'One post-op review round: 3 lens reviewers, dedup, 2-of-3 adversarial verification, severity class + redesign signal',
  whenToUse: 'Called by /post-op Step 1.5 for each code-review round (args: ticket, round, base, criticalDomain, consumerSurfaces, contract, threatModel, prior, savedDiff, scratchDir)',
  phases: [
    { title: 'Review', detail: '3 reviewers, one lens each, on the merge-base diff against args.base' },
    { title: 'Verify', detail: '2 refuting verifiers per finding, a 3rd only on a split' },
  ],
}

const A = args || {}
const ROUND = A.round || 1
const PRIOR = Array.isArray(A.prior) ? A.prior : []
const text = x => (typeof x === 'string' && x.trim()) || null
// post-op passes origin/<MAIN_BRANCH>. Without a base the round can't know what to review.
const BASE = text(A.base)
const CRITICAL = text(A.criticalDomain) || '(not given: treat as the logic that must never be wrong in this project)'
const CONSUMERS = text(A.consumerSurfaces) || 'every client, job and service that reads what changed'
const SCRATCH = text(A.scratchDir) || '.claude/state/tmp'

const notRun = (reviewers, why) => {
  log(why)
  return { ticket: A.ticket || null, round: ROUND, round_ran: false, base: BASE, reviewers, reason: why,
    must_fix: [], noted: [], repeats: [], rejected: [], unverified: [], redesign_signal: { recommended: false, findings: [], simpler_shape: null } }
}
if (!BASE) return notRun('0/3', 'args.base is missing (post-op passes origin/<MAIN_BRANCH>) — round did not run')

const BAR = [
  'Severity bar (post-op Step 1.5 round rule 2). Must-fix only:',
  'S1 data integrity (loss/corruption, irreversible or wrong writes, cross-tenant exposure);',
  'S2 auth & security (lock-out, privilege or access-control holes, PII in logs, secrets, injection or unsafe input, unverified webhook);',
  `S3 ${CRITICAL} (a wrong result in the logic that must never be wrong here);`,
  'S4 the ticket\'s own behaviour (breaks a contract row or pre-code vector, or the changed flow crashes / returns a wrong result on input production realistically sends).',
  'Everything else is "noted": style, naming, refactors, test polish, wording, unmeasured performance, inputs outside the threat model, unreachable paths.',
].join(' ')

const CONTEXT = [
  `Ticket: ${A.ticket || '(none)'} · review round ${ROUND}.`,
  `Threat model / out of scope: ${A.threatModel || '(not given; use realistic production inputs and honest mistakes)'}`,
  `Acceptance contract: ${A.contract || '(not given; use the ticket acceptance criteria)'}`,
].join('\n')

const DIFF_HOWTO = [
  'Read the change yourself; do not modify any project file, commit, or run anything that writes, except the one scratch diff named below.',
  `Run these as separate plain commands (some guard hooks refuse $(...)): \`git merge-base ${BASE} HEAD\` (prints <base>), then \`git --no-pager diff <base>\` for the whole branch, working tree included.`,
  ROUND > 1 && A.savedDiff
    ? `This is a later round: the previous round reviewed the diff saved at ${A.savedDiff}. Compare it with the current diff (save the current one to ${SCRATCH}/consensus-round-${ROUND}-now.diff, never /tmp, and run \`diff\`) and look at what changed first, but report a real defect anywhere.`
    : 'This is round 1: review the whole branch.',
  'Read the surrounding code and every consumer of what changed, not just the diff lines.',
].join('\n')

const LENSES = [
  { key: 'correctness', focus: 'correctness and edge cases: null/empty/absent inputs, error paths that fail open, wrong results, crashes, races and double-fires, off-by-one, mocks that do not match the real module.' },
  { key: 'risk', focus: `S1–S3 risk only: data integrity and cross-tenant exposure, auth/security/PII/access control/secrets, and S3 (${CRITICAL}). Ignore anything that is not S1–S3.` },
  { key: 'contract', focus: `the acceptance contract and consumers: does every contract row hold, does every sibling path and consumer (${CONSUMERS}) still work, and is the design the simplest that works (a stored fact instead of inference)?` },
]

const FINDINGS = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          file: { type: 'string' },
          line: { type: 'integer' },
          summary: { type: 'string' },
          failure_scenario: { type: 'string' },
          proposed_class: { type: 'string', enum: ['S1', 'S2', 'S3', 'S4', 'noted'] },
          design: { type: 'string', enum: ['ok', 'redesign'] },
          simpler_shape: { type: 'string' },
        },
        required: ['file', 'line', 'summary', 'failure_scenario', 'proposed_class', 'design'],
      },
    },
  },
  required: ['findings'],
}

const VERDICT = {
  type: 'object',
  properties: {
    real: { type: 'boolean' },
    class: { type: 'string', enum: ['S1', 'S2', 'S3', 'S4', 'noted'] },
    repeat_of: { type: 'string' },
    evidence: { type: 'string' },
    design: { type: 'string', enum: ['ok', 'redesign'] },
    simpler_shape: { type: 'string' },
  },
  required: ['real', 'class', 'evidence', 'design'],
}

phase('Review')
const reviews = await parallel(LENSES.map(l => () =>
  agent(
    `You are one of three independent code reviewers. Your lens: ${l.focus}\n\n${CONTEXT}\n\n${BAR}\n\n${DIFF_HOWTO}\n\n` +
    'Report only defects you can tie to a file and line, each with a concrete failure scenario (input/state → wrong outcome). Classify each with the bar. ' +
    'For each, answer the design question: design="redesign" with a concrete simpler_shape if it is a symptom of a design that keeps breaking (code inferring a fact that could be stored, one mechanism producing several defects), else design="ok". ' +
    'Report at most 10, most severe first. An empty list is a valid answer.',
    { label: `review:${l.key}`, phase: 'Review', schema: FINDINGS })
    // A dead reviewer stays null so it is not counted as having returned.
    .then(r => (r ? r.findings.map(f => ({ ...f, lens: l.key })) : null))))

// Fewer than 2 of 3 reviewers returning means the round did not run. Stop before verifying.
const returned = reviews.filter(Boolean)
if (returned.length < 2) {
  return notRun(`${returned.length}/3`, `only ${returned.length}/3 reviewers returned — round did not run`)
}

// Dedup in code (barrier needed: merge across all reviewers before paying for verification).
// Merge only exact duplicates: same file, same line, same proposed class, from a different
// reviewer. Anything else is a separate claim and is verified on its own, so a vote is
// always about one claim. The merged reviewer's wording is kept in `also` for the record.
const shape = x => (typeof x.simpler_shape === 'string' && x.simpler_shape.trim()) || null
const all = returned.flat()
const merged = []
for (const f of all) {
  const twin = merged.find(m => m.file === f.file && m.line === f.line && m.proposed_class === f.proposed_class && !m.lenses.includes(f.lens))
  if (twin) {
    twin.lenses.push(f.lens)
    twin.also.push(f.summary)
    if (f.design === 'redesign' && shape(f)) twin.reviewer_redesign = twin.reviewer_redesign || shape(f)
  } else {
    merged.push({ ...f, lenses: [f.lens], also: [], reviewer_redesign: f.design === 'redesign' ? shape(f) : null })
  }
}
log(`${all.length} raw findings from ${returned.length}/3 reviewers → ${merged.length} after dedup`)

// Only dispositions that can make a finding a repeat (round rule 4); a fixed finding that
// comes back is new, so fixed ones are never offered as a repeat target. These words must
// equal post-op's disposition words: matching is by leading word.
const REPEATABLE = ['rejected', 'noted', 'own ticket', 'already decided']
const priorRepeatable = PRIOR.filter(p => { const d = String(p.disposition || '').trim().toLowerCase(); return REPEATABLE.some(r => d.startsWith(r)) })
const PRIOR_IDS = priorRepeatable.map((_, k) => `P${k + 1}`)
const priorText = priorRepeatable.length
  ? 'Earlier rounds already decided these. If this finding is the same defect as one of them, set repeat_of to its id; otherwise set repeat_of to "none":\n' +
    priorRepeatable.map((p, k) => `- ${PRIOR_IDS[k]}: ${p.finding} → ${p.disposition}`).join('\n')
  : 'No earlier decisions this could repeat: set repeat_of to "none".'
// The verdict schema for this round: repeat_of is one of the ids or "none" (no free text).
const VERDICT_ROUND = { ...VERDICT, properties: { ...VERDICT.properties, repeat_of: { type: 'string', enum: ['none', ...PRIOR_IDS] } },
  required: [...VERDICT.required, 'repeat_of'] }
const priorById = Object.fromEntries(priorRepeatable.map((p, k) => [PRIOR_IDS[k], `${p.finding} → ${p.disposition}`]))

const verifyOne = (f, i, n) => agent(
  `You are a skeptical verifier. Try to REFUTE this code-review finding against the actual code. If you cannot confirm it from the code, it is not real (real=false). Read the code; do not trust the claim.\n\n` +
  `Finding: ${f.file}:${f.line} — ${f.summary}\nClaimed failure: ${f.failure_scenario}\n` +
  (f.also.length ? `Another reviewer reported the same defect at this line as: ${f.also.join(' / ')}\n` : '') +
  `\n${CONTEXT}\n\n${BAR}\n\n${priorText}\n\n` +
  'If real, give its class by the bar (classify by what it does to users or data, never by how big the fix is), and the evidence (file:line and what the code does). ' +
  'Then the design question: is this a symptom of a design that keeps breaking (several defects from one mechanism, code inferring a fact that could be stored)? design="redesign" with simpler_shape, else design="ok". Do not modify any file.',
  { label: `verify:${i + 1}.${n}`, phase: 'Verify', schema: VERDICT_ROUND })

const SEV = ['S1', 'S2', 'S3', 'S4', 'noted']
// The one rule for every decision: a value counts only when 2 votes agree on it; a split is null.
const quorum = (votes, key) => {
  const c = {}
  votes.forEach(v => { const k = key(v); c[k] = (c[k] || 0) + 1 })
  return Object.keys(c).find(k => c[k] >= 2) || null
}
const statusKey = v => (v.real ? 'real' : 'not')
const bucketKey = v => (v.class === 'noted' ? 'noted' : 'must_fix')
const repeatKey = v => v.repeat_of || 'none'
const decide = votes => {
  const status = quorum(votes, statusKey)
  if (status !== 'real') return { status }
  const yes = votes.filter(v => v.real)
  return { status, bucket: quorum(yes, bucketKey), repeat: quorum(yes, repeatKey) }
}
const settled = d => d.status === 'not' || (d.status === 'real' && d.bucket && d.repeat)

const judged = await pipeline(merged, async (f, _orig, i) => {
  let votes = (await parallel([() => verifyOne(f, i, 'a'), () => verifyOne(f, i, 'b')])).filter(Boolean)
  // Any split (or a dead verifier) calls the single tie-breaker.
  if (!settled(decide(votes))) {
    const third = await verifyOne(f, i, 'c')
    if (third) votes.push(third)
  }
  const d = decide(votes)
  const yes = votes.filter(v => v.real)
  const no = votes.filter(v => !v.real)
  const status = d.status === 'not' ? 'rejected' : settled(d) ? 'real' : 'unverified'
  // Within must_fix, the exact S-class goes to the most severe class a "real" vote gave.
  const cls = status !== 'real' ? null
    : d.bucket === 'noted' ? 'noted'
    : yes.map(v => v.class).filter(c => c !== 'noted').sort((x, y) => SEV.indexOf(x) - SEV.indexOf(y))[0]
  const shapes = [f.reviewer_redesign, ...yes.filter(v => v.design === 'redesign').map(shape)].filter(Boolean)
  return {
    file: f.file, line: f.line, summary: f.summary, failure_scenario: f.failure_scenario, also: f.also,
    lenses: f.lenses, votes: `${yes.length} real / ${no.length} not / ${votes.length} returned`, status, class: cls,
    repeat_of: status === 'real' && d.repeat !== 'none' ? `${d.repeat}: ${priorById[d.repeat] || ''}` : null,
    evidence: (status === 'real' ? yes : votes).map(v => v.evidence).join(' | '),
    redesign: shapes.length > 0, simpler_shape: shapes[0] || null,
  }
})

const results = judged.filter(Boolean)
const verified = results.filter(r => r.status === 'real' && !r.repeat_of)
const mustFix = verified.filter(r => r.class !== 'noted')
// Round rule 10(c): one concrete recommendation from a reviewer or verifier on a verified finding is enough.
const redesignOn = verified.filter(r => r.redesign)
const unverified = results.filter(r => r.status === 'unverified')
log(`${verified.length} verified (${mustFix.length} must-fix), ${results.filter(r => r.status === 'rejected').length} rejected, ` +
    `${results.filter(r => r.status === 'real' && r.repeat_of).length} repeats, ${unverified.length} unverified`)

return {
  ticket: A.ticket || null,
  round: ROUND,
  round_ran: true,
  base: `${BASE} (merge-base, working tree included)`,
  reviewers: `${returned.length}/3`,
  must_fix: mustFix,
  noted: verified.filter(r => r.class === 'noted'),
  repeats: results.filter(r => r.status === 'real' && r.repeat_of),
  rejected: results.filter(r => r.status === 'rejected').map(r => ({ file: r.file, line: r.line, summary: r.summary, votes: r.votes, evidence: r.evidence })),
  unverified,
  redesign_signal: {
    recommended: redesignOn.length > 0,
    findings: redesignOn.map(r => `${r.file}:${r.line} — ${r.summary}`),
    simpler_shape: redesignOn.map(r => r.simpler_shape).filter(Boolean)[0] || null,
  },
}
