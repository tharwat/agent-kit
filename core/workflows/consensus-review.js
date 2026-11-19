// Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
// One code-review round for /post-op Step 1.5. Post-op owns the fixes and the record; this
// script runs a round and decides, by 2-of-3 votes, what comes next:
// 3 lens reviewers per area (a large diff is split into areas by `kit-tools.mjs areas`, so the
// round sweeps every part instead of sampling) → dedup in code → 2 refuting verifiers per
// finding (+1 tie-breaker) → classed findings with their origin → next: clean | fix | redesign.
// Run it by scriptPath (<repo root>/.claude/workflows/consensus-review.js), never by name.
export const meta = {
  name: 'consensus-review',
  description: 'One post-op review round: 3 lens reviewers per area, dedup, 2-of-3 adversarial verification, severity class + origin, and the next step by consensus',
  whenToUse: 'Called by /post-op Step 1.5 for each code-review round (args: ticket, round, base, areas, repo, criticalDomain, consumerSurfaces, contract, threatModel, prior, savedDiff, scratchDir)',
  phases: [
    { title: 'Review', detail: '3 reviewers per area, one lens each, on the merge-base diff against args.base' },
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
// The areas from `node .claude/scripts/kit-tools.mjs areas --base <base>`; one area (the whole branch) when absent.
const AREAS = Array.isArray(A.areas) && A.areas.length > 1
  ? A.areas.filter(a => a && Array.isArray(a.paths) && a.paths.length).map(a => ({ name: String(a.name || 'area'), paths: a.paths }))
  : [{ name: 'whole branch', paths: null }]

const notRun = (reviewers, why) => {
  log(why)
  return { ticket: A.ticket || null, round: ROUND, round_ran: false, base: BASE, reviewers, reason: why,
    must_fix: [], noted: [], nits: [], repeats: [], rejected: [], unverified: [], origins: {}, next: null }
}
if (!BASE) return notRun('0/3', 'args.base is missing (post-op passes origin/<MAIN_BRANCH>) — round did not run')

const BAR = [
  'Severity bar (post-op Step 1.5 round rule 2). Must-fix only:',
  'S1 data integrity (loss/corruption, irreversible or wrong writes, cross-tenant exposure);',
  'S2 auth & security (lock-out, privilege or access-control holes, PII in logs, secrets, injection or unsafe input, unverified webhook);',
  `S3 ${CRITICAL} (a wrong result in the logic that must never be wrong here);`,
  'S4 the ticket\'s own behaviour (breaks a contract row or pre-code vector, or the changed flow crashes / returns a wrong result on input production realistically sends).',
  'Below the bar is "noted": a real wrong behaviour that is none of S1–S4. A finding with no wrong behaviour at all (style, naming, refactor, test polish, wording, unmeasured performance) is "nit". Inputs outside the threat model and unreachable paths are not real.',
].join(' ')

// Round rule 2: origin decides whether a real defect is fixed here. Code this ticket wrote is fixed whatever its class.
const ORIGIN = [
  'Origin of a real finding (post-op round rule 2):',
  `"pre-existing" when the defective code is unchanged from ${BASE || 'the base'} (check with \`git show <base>:<file>\`);`,
  '"fix-introduced" when it sits in lines an earlier review round\'s fix added or changed (the fix delta: the previous round\'s saved diff against the current diff);',
  '"first-draft" for any other line this branch wrote.',
].join(' ')

const CONTEXT = [
  `Ticket: ${A.ticket || '(none)'} · review round ${ROUND}.`,
  text(A.repo) ? `Work only in the project at ${A.repo}: run every command there (cd ${A.repo} first).` : '',
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
          proposed_class: { type: 'string', enum: ['S1', 'S2', 'S3', 'S4', 'noted', 'nit'] },
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
    class: { type: 'string', enum: ['S1', 'S2', 'S3', 'S4', 'noted', 'nit'] },
    origin: { type: 'string', enum: ['first-draft', 'fix-introduced', 'pre-existing'] },
    repeat_of: { type: 'string' },
    evidence: { type: 'string' },
    design: { type: 'string', enum: ['ok', 'redesign'] },
    simpler_shape: { type: 'string' },
  },
  required: ['real', 'class', 'origin', 'evidence', 'design'],
}

// Only dispositions that can make a finding a repeat (round rule 4); a fixed finding that
// comes back is new, so fixed ones are never offered as a repeat target. These words must
// equal post-op's disposition words: matching is by leading word.
const REPEATABLE = ['rejected', 'noted', 'nit', 'own ticket', 'already decided']
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
// Defects earlier rounds fixed. A new finding in the same mechanism means that fix covered one member of a class
// and not the class: the verifiers then vote for a redesign.
const fixedBefore = PRIOR.filter(p => String(p.disposition || '').trim().toLowerCase().startsWith('must-fix'))
const fixedText = fixedBefore.length
  ? 'Earlier rounds already fixed these defects. If this finding comes from the same mechanism, rule, inference, piece of state or flow as one of them, the earlier fix covered one case and not the class: answer design="redesign" with the simpler shape that ends the class:\n' +
    fixedBefore.map(p => `- ${p.finding}`).join('\n')
  : ''
// Reviewers get the same list (doc: the decided list reaches the reviewer), so they stop re-raising it.
const decidedText = priorRepeatable.length
  ? 'Already decided in earlier rounds. Do not raise these again unless you bring NEW evidence that the recorded reason is wrong:\n' +
    priorRepeatable.map(p => `- ${p.finding} → ${p.disposition}`).join('\n')
  : 'Nothing has been decided in earlier rounds.'
const MARKERS = 'A code comment starting "Deliberate (decided R<n>-<k>):" states a reason for a decided design choice. Check the reason against the code: report the spot only if the reason is wrong, and say why. It covers only the concern it names.'

const areaText = a => a.paths
  ? `Your area of this round: ${a.name}. Report findings only in these changed files: ${a.paths.join(', ')}. ` +
    'Read anything else you need (callers, consumers, the rest of the diff) to judge them. Other reviewers cover the other areas, so go deep: report every real defect in your area, not a sample.'
  : 'Your area: the whole branch. Report every real defect, not a sample.'

phase('Review')
const jobs = AREAS.flatMap((a, ai) => LENSES.map(l => ({ a, ai, l })))
const reviews = await parallel(jobs.map(({ a, ai, l }) => () =>
  agent(
    `You are one of three independent code reviewers for this area. Your lens: ${l.focus}\n\n${CONTEXT}\n\n${areaText(a)}\n\n${BAR}\n\n${DIFF_HOWTO}\n\n${decidedText}\n\n${MARKERS}\n\n` +
    'Report only defects you can tie to a file and line, each with a concrete failure scenario (input/state → wrong outcome). Classify each with the bar. ' +
    'For each, answer the design question: design="redesign" with a concrete simpler_shape if it is a symptom of a design that keeps breaking (code inferring a fact that could be stored, one mechanism producing several defects, a list kept by hand that could be derived), else design="ok". ' +
    'Report at most 15, most severe first. An empty list is a valid answer.',
    { label: AREAS.length > 1 ? `review:${l.key}:${ai + 1}` : `review:${l.key}`, phase: 'Review', schema: FINDINGS })
    // A dead reviewer stays null so it is not counted as having returned.
    .then(r => (r ? r.findings.map(f => ({ ...f, lens: `${l.key}${AREAS.length > 1 ? `@${ai + 1}` : ''}`, area: ai })) : null))))

// An area where fewer than 2 of its 3 reviewers returned was not reviewed, so the round did not run.
for (let ai = 0; ai < AREAS.length; ai++) {
  const back = reviews.filter((r, j) => r && jobs[j].ai === ai).length
  if (back < 2) return notRun(`${back}/3 in ${AREAS[ai].name}`, `only ${back}/3 reviewers returned for area "${AREAS[ai].name}" — round did not run`)
}
const returned = reviews.filter(Boolean)

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
log(`${all.length} raw findings from ${returned.length}/${jobs.length} reviewers in ${AREAS.length} area(s) → ${merged.length} after dedup`)


const verifyOne = (f, i, n) => agent(
  `You are a skeptical verifier. Try to REFUTE this code-review finding against the actual code. If you cannot confirm it from the code, it is not real (real=false). Read the code; do not trust the claim.\n\n` +
  `Finding: ${f.file}:${f.line} — ${f.summary}\nClaimed failure: ${f.failure_scenario}\n` +
  (f.also.length ? `Another reviewer reported the same defect at this line as: ${f.also.join(' / ')}\n` : '') +
  `\n${CONTEXT}\n\n${BAR}\n\n${ORIGIN}\n\n${DIFF_HOWTO}\n\n${priorText}\n\n${fixedText}\n\n${MARKERS}\n\n` +
  'If real, give its class by the bar (classify by what it does to users or data, never by how big the fix is), its origin, and the evidence (file:line and what the code does). ' +
  'Then the design question: is this a symptom of a design that keeps breaking (several defects from one mechanism, code inferring a fact that could be stored, a list kept by hand that could be derived, the same mechanism as a defect an earlier round fixed)? design="redesign" with simpler_shape, else design="ok". Do not modify any file.',
  { label: `verify:${i + 1}.${n}`, phase: 'Verify', schema: VERDICT_ROUND })

const SEV = ['S1', 'S2', 'S3', 'S4', 'noted', 'nit']
// The one rule for every decision: a value counts only when 2 votes agree on it; a split is null.
const quorum = (votes, key) => {
  const c = {}
  votes.forEach(v => { const k = key(v); c[k] = (c[k] || 0) + 1 })
  return Object.keys(c).find(k => c[k] >= 2) || null
}
const statusKey = v => (v.real ? 'real' : 'not')
// Round rule 2: a nit is never fixed or filed; a below-bar defect is "noted" only when it is pre-existing;
// every other real defect (S1–S4, or this ticket's own code at any class) is fixed on the ticket.
const bucketKey = v => (v.class === 'nit' ? 'nit' : v.class === 'noted' && v.origin === 'pre-existing' ? 'noted' : 'must_fix')
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
  // Within must_fix, the class is the most severe one a "real" vote gave (own-code defects may be "noted").
  const cls = status !== 'real' ? null
    : d.bucket === 'nit' ? 'nit'
    : d.bucket === 'noted' ? 'noted'
    : yes.map(v => v.class).filter(c => c !== 'nit').sort((x, y) => SEV.indexOf(x) - SEV.indexOf(y))[0]
  const origin = status !== 'real' ? null : quorum(yes, v => v.origin) || 'unclear'
  const shapes = [f.reviewer_redesign, ...yes.filter(v => v.design === 'redesign').map(shape)].filter(Boolean)
  // The redesign vote: the verifiers who found it real, plus the reviewer who raised it. Two agreeing is a decision.
  const redesignVotes = yes.filter(v => v.design === 'redesign').length + (f.reviewer_redesign ? 1 : 0)
  return {
    file: f.file, line: f.line, summary: f.summary, failure_scenario: f.failure_scenario, also: f.also,
    lenses: f.lenses, votes: `${yes.length} real / ${no.length} not / ${votes.length} returned`, status, class: cls, origin,
    repeat_of: status === 'real' && d.repeat !== 'none' ? `${d.repeat}: ${priorById[d.repeat] || ''}` : null,
    evidence: (status === 'real' ? yes : votes).map(v => v.evidence).join(' | '),
    redesign: redesignVotes >= 2, redesign_votes: redesignVotes, simpler_shape: shapes[0] || null,
  }
})

const results = judged.filter(Boolean)
const verified = results.filter(r => r.status === 'real' && !r.repeat_of)
const mustFix = verified.filter(r => r.class !== 'nit' && !(r.class === 'noted' && r.origin === 'pre-existing'))
// Round rule 8: the origin counts every round record carries (A first-draft, B fix-introduced, D pre-existing).
const origins = verified.filter(r => r.class !== 'nit').reduce((c, r) => ({ ...c, [r.origin]: (c[r.origin] || 0) + 1 }), {})
const unverified = results.filter(r => r.status === 'unverified')
// The next step, by consensus: clean when nothing is left to fix; redesign when 2 votes agree a must-fix finding is a
// symptom of a design that keeps breaking; otherwise fix. Post-op follows it; no counter and no owner decides this.
const redesignOn = mustFix.filter(r => r.redesign)
const next = mustFix.length === 0 && unverified.length === 0
  ? { action: 'clean', why: 'no must-fix finding and nothing unverified' }
  : redesignOn.length
    ? { action: 'redesign', part: [...new Set(redesignOn.map(r => r.file))], simpler_shape: redesignOn.map(r => r.simpler_shape).filter(Boolean)[0] || null,
        findings: redesignOn.map(r => `${r.file}:${r.line} — ${r.summary} (${r.redesign_votes} redesign votes)`),
        why: 'two or more votes agree these findings come from a design that keeps breaking' }
    : { action: 'fix', why: `${mustFix.length} must-fix finding(s)${unverified.length ? `, ${unverified.length} unverified to check` : ''}; no redesign consensus` }
log(`${verified.length} verified (${mustFix.length} must-fix, origins ${JSON.stringify(origins)}), ${results.filter(r => r.status === 'rejected').length} rejected, ` +
    `${results.filter(r => r.status === 'real' && r.repeat_of).length} repeats, ${unverified.length} unverified`)

return {
  ticket: A.ticket || null,
  round: ROUND,
  round_ran: true,
  base: `${BASE} (merge-base, working tree included)`,
  reviewers: `${returned.length}/${jobs.length} in ${AREAS.length} area(s)`,
  areas: AREAS.map(a => a.name),
  must_fix: mustFix,
  noted: verified.filter(r => r.class === 'noted' && r.origin === 'pre-existing'),
  nits: verified.filter(r => r.class === 'nit'),
  origins,
  repeats: results.filter(r => r.status === 'real' && r.repeat_of),
  rejected: results.filter(r => r.status === 'rejected').map(r => ({ file: r.file, line: r.line, summary: r.summary, votes: r.votes, evidence: r.evidence })),
  unverified,
  next,
}
