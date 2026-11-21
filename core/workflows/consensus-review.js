// Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
// One code-review round for /post-op Step 1.5. Post-op owns the fixes and the record; this script runs a round:
// finders with no author context (3 Claude lens reviewers per area, plus Codex when post-op passes its model), with
// no cap on findings → dedup in code → 2 refuting verifiers per finding (+1 tie-breaker), who also answer the impact
// questions → the table in `outcome` sorts each real finding (fix now | own ticket | open class | nit) → events
// decide what comes next: clean | fix | redesign.
// The author never votes. What it knows arrives as `witness` claims the voters check, and an objection to a result
// comes back through `recheck`, where the voters decide again.
// Run it by scriptPath (<repo root>/.claude/workflows/consensus-review.js), never by name.
export const meta = {
  name: 'consensus-review',
  description: 'One post-op review round: uncapped finders per area (Claude lenses, plus Codex), dedup, 2-of-3 adversarial verification with an impact vote, and the next step by event',
  whenToUse: 'Called by /post-op Step 1.5 for each code-review round (args: ticket, round, base, areas, repo, criticalDomain, consumerSurfaces, contract, threatModel, prior, savedDiff, scratchDir, witness, codexModel, recheck)',
  phases: [
    { title: 'Review', detail: 'finders with no author context, one lens each per area, plus Codex; no cap on findings' },
    { title: 'Verify', detail: '2 refuting verifiers per finding, a 3rd only on a split; they answer the impact questions' },
  ],
}

const A = args || {}
const ROUND = A.round || 1
const PRIOR = Array.isArray(A.prior) ? A.prior : []
const text = x => (typeof x === 'string' && x.trim()) || null
// post-op passes origin/<MAIN_BRANCH>. Without a base the round can't know what to review.
const BASE = text(A.base)
const CRITICAL = text(A.criticalDomain) || 'the logic that must never be wrong in this project'
const CONSUMERS = text(A.consumerSurfaces) || 'every client, job and service that reads what changed'
const SCRATCH = text(A.scratchDir) || '.claude/state/tmp'
const CODEX = text(A.codexModel)
const WITNESS = text(A.witness)
// A later round reviews only what changed since the saved diff (round rule 3).
const LATER = ROUND > 1 && !!text(A.savedDiff)
// Findings sent back to the voters: an unverified one, or one the author objects to with evidence.
const RECHECK = (Array.isArray(A.recheck) ? A.recheck : []).filter(f => f && text(f.file) && text(f.summary))
// The areas from `node .claude/scripts/kit-tools.mjs areas --base <base>`; one area when absent.
const AREAS = Array.isArray(A.areas) && A.areas.length > 1
  ? A.areas.filter(a => a && Array.isArray(a.paths) && a.paths.length).map(a => ({ name: String(a.name || 'area'), paths: a.paths }))
  : [{ name: LATER ? 'the fix delta' : 'whole branch', paths: null }]

const notRun = (reviewers, why) => {
  log(why)
  return { ticket: A.ticket || null, round: ROUND, round_ran: false, base: BASE, reviewers, reason: why,
    must_fix: [], redesign: [], tickets: [], open_class: [], nits: [], repeats: [], rejected: [], unverified: [], origins: {}, next: null }
}
if (!BASE) return notRun('0/3', 'args.base is missing (post-op passes origin/<MAIN_BRANCH>) — round did not run')

// The impact questions (post-op Step 1.5 round rule 2). The voters answer facts; `outcome` below applies the table.
const IMPACT = [
  'If the finding is real, answer the impact questions from the code, as facts. They decide whether it is fixed now or later, so do not shade them (post-op Step 1.5 round rule 2):',
  `- loss: the worst thing lost when it happens. "data" (data lost, corrupted, wrongly or irreversibly written, or shown to the wrong tenant); "security" (an access-control hole, a lock-out, a leaked secret, personal data in logs, injection or unsafe input, an unverified webhook); "person" (a person wrongly contacted or charged, or a legal or compliance breach); "critical" (a wrong result in ${CRITICAL}); "money" (money lost or mis-charged, and nothing above); "operator" (hand work for an operator or support, and nothing above); "appearance" (wrong text, layout or log line, and nothing else lost); "none" (no wrong behaviour at all: style, naming, a refactor, test polish, wording of a comment, unmeasured performance).`,
  '- bounded: true when each occurrence loses a small, known amount that can be put right; false when it can repeat or grow without anyone seeing it.',
  '- reach: what has to happen first. "normal" (an ordinary action, or an input production really sends); "unusual" (a valid but unusual input, order or timing); "one-failure" (one independent failure at the wrong moment: a crash, a timeout, an outage); "two-failures" (two or more independent things going wrong together).',
  '- silent: true when nobody would notice it happened (no error, no alert, nothing visible).',
  '- fix: "small" when the root-cause fix is a few lines in one place and adds no stored state, no list entry, no exception to a rule and no new mechanism; otherwise "costly".',
  '- open_class: true when this is one more member of a class with no end: another phrase, format, evasion or combination of faults that the same check would have to list, so that fixing this one leaves the next. Name the class in the evidence.',
  'Inputs outside the threat model, a deliberately hostile author, an unreachable path and a case you cannot construct from the code are not real.',
].join('\n')

const ORIGIN = [
  'Origin of a real finding:',
  `"pre-existing" when the defective code is unchanged from ${BASE} (check with \`git show <base>:<file>\`);`,
  '"fix-introduced" when it sits in lines an earlier review round\'s fix added or changed (the fix delta: the previous round\'s saved diff against the current diff);',
  '"first-draft" for any other line this branch wrote.',
].join(' ')

const CONTEXT = [
  `Ticket: ${A.ticket || '(none)'} · review round ${ROUND}.`,
  text(A.repo) ? `Work only in the project at ${A.repo}: run every command there (cd ${A.repo} first).` : '',
  `Threat model / out of scope: ${A.threatModel || '(not given; use realistic production inputs and honest mistakes)'}`,
  `Acceptance contract: ${A.contract || '(not given; use the ticket acceptance criteria)'}`,
].join('\n')

// canWrite is false for Codex, which runs in a read-only sandbox.
const diffHowto = canWrite => [
  canWrite
    ? 'Read the change yourself; do not modify any project file, commit, or run anything that writes, except the one scratch diff named below.'
    : 'Read the change yourself. You are read-only: write nothing.',
  `Run these as separate plain commands (some guard hooks refuse $(...)): \`git merge-base ${BASE} HEAD\` (prints <base>), then \`git --no-pager diff <base>\` for the whole branch, working tree included.`,
  LATER
    ? `This is a later round. Round 1 swept the whole branch; this round covers only what changed since. The previous round reviewed the diff saved at ${A.savedDiff}. ` +
      (canWrite ? `Save the current diff to ${SCRATCH}/consensus-round-${ROUND}-now.diff (never /tmp) and compare the two with \`diff\`. ` : 'Compare it with the current diff. ') +
      'The lines that differ, and the functions those lines sit in, are the fix delta.'
    : 'This round covers the whole branch.',
  'Read the surrounding code and every consumer of what changed, not just the diff lines.',
].join('\n')
const DIFF_HOWTO = diffHowto(true)

const LENSES = [
  { key: 'correctness', focus: 'correctness and edge cases: null/empty/absent inputs, error paths that fail open, wrong results, crashes, races and double-fires, off-by-one, mocks that do not match the real module.' },
  { key: 'risk', focus: `the serious losses only: data integrity and cross-tenant exposure, auth, security, personal data, access control and secrets, a person wrongly contacted or charged, and ${CRITICAL}. Ignore everything else.` },
  { key: 'contract', focus: `the acceptance contract and consumers: does every contract row hold, does every sibling path and consumer (${CONSUMERS}) still work, and is a state stored once instead of worked out from several fields?` },
]

const FINDING_PROPS = {
  file: { type: 'string' },
  line: { type: 'integer' },
  summary: { type: 'string' },
  failure_scenario: { type: 'string' },
}
const FINDING_REQUIRED = ['file', 'line', 'summary', 'failure_scenario']
const FINDINGS = {
  type: 'object',
  properties: { findings: { type: 'array', items: { type: 'object', properties: FINDING_PROPS, required: FINDING_REQUIRED } } },
  required: ['findings'],
}
// What the Codex relay returns: Codex's findings unchanged, or why it could not run.
const RELAY = {
  type: 'object',
  properties: { unavailable: { type: 'string' }, findings: FINDINGS.properties.findings },
  required: ['unavailable', 'findings'],
}
// The schema file handed to `codex exec --output-schema` (strict: every property required, nothing extra).
const CODEX_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['findings'],
  properties: { findings: { type: 'array', items: { type: 'object', additionalProperties: false, properties: FINDING_PROPS, required: FINDING_REQUIRED } } },
}

// Only dispositions that can make a finding a repeat (round rule 4); a fixed finding that comes back is new. These
// words must equal post-op's disposition words: matching is by leading word. `noted` is read from older records.
const REPEATABLE = ['rejected', 'nit', 'own ticket', 'open class', 'already decided', 'noted']
const lead = p => String(p.disposition || '').trim().toLowerCase()
const priorRepeatable = PRIOR.filter(p => REPEATABLE.some(r => lead(p).startsWith(r)))
const PRIOR_IDS = priorRepeatable.map((_, k) => `P${k + 1}`)
const priorText = priorRepeatable.length
  ? 'Earlier rounds already decided these. If this finding is the same defect as one of them, set repeat_of to its id; otherwise set repeat_of to "none":\n' +
    priorRepeatable.map((p, k) => `- ${PRIOR_IDS[k]}: ${p.finding} → ${p.disposition}`).join('\n')
  : 'No earlier decisions this could repeat: set repeat_of to "none".'
const priorById = Object.fromEntries(priorRepeatable.map((p, k) => [PRIOR_IDS[k], `${p.finding} → ${p.disposition}`]))
// Defects earlier rounds fixed. A new defect from the same mechanism is an event (round rule 10): the fix covered
// one case and patching has stopped working there.
const fixedBefore = PRIOR.filter(p => lead(p).startsWith('must-fix'))
const FIXED_IDS = fixedBefore.map((_, k) => `F${k + 1}`)
const fixedText = fixedBefore.length
  ? 'Earlier rounds already fixed these defects. If this finding comes from the same mechanism (the same function, rule, piece of state or flow) as one of them, set mechanism_of to its id; otherwise "none":\n' +
    fixedBefore.map((p, k) => `- ${FIXED_IDS[k]}: ${p.finding}`).join('\n')
  : 'No earlier round fixed anything: set mechanism_of to "none".'
const fixedById = Object.fromEntries(fixedBefore.map((p, k) => [FIXED_IDS[k], p.finding]))
// Finders get the decided list too, so they stop re-raising it.
const decidedText = priorRepeatable.length
  ? 'Already decided in earlier rounds. Do not raise these again unless you bring NEW evidence that the recorded reason is wrong:\n' +
    priorRepeatable.map(p => `- ${p.finding} → ${p.disposition}`).join('\n')
  : 'Nothing has been decided in earlier rounds.'
const witnessText = WITNESS
  ? 'The author, who does not vote, states that the following is already guarded or already decided. Each line is a claim, not a fact: open the place it names and check it. What it truly answers is not a defect.\n' + WITNESS
  : 'The author gave no witness note.'
const MARKERS = 'A code comment starting "Deliberate (decided R<n>-<k>):" states a reason for a decided design choice. Check the reason against the code: report the spot only if the reason is wrong, and say why. It covers only the concern it names.'

const VERDICT = {
  type: 'object',
  properties: {
    real: { type: 'boolean' },
    loss: { type: 'string', enum: ['data', 'security', 'person', 'critical', 'money', 'operator', 'appearance', 'none'] },
    bounded: { type: 'boolean' },
    reach: { type: 'string', enum: ['normal', 'unusual', 'one-failure', 'two-failures'] },
    silent: { type: 'boolean' },
    fix: { type: 'string', enum: ['small', 'costly'] },
    open_class: { type: 'boolean' },
    origin: { type: 'string', enum: ['first-draft', 'fix-introduced', 'pre-existing'] },
    mechanism_of: { type: 'string', enum: ['none', ...FIXED_IDS] },
    repeat_of: { type: 'string', enum: ['none', ...PRIOR_IDS] },
    evidence: { type: 'string' },
  },
  required: ['real', 'loss', 'bounded', 'reach', 'silent', 'fix', 'open_class', 'origin', 'mechanism_of', 'repeat_of', 'evidence'],
}

const scopeText = a => (a.paths
  ? `Your area of this round: ${a.name}. Report findings only in these changed files: ${a.paths.join(', ')}. ` +
    'Read anything else you need (callers, consumers, the rest of the diff) to judge them. Other reviewers cover the other areas. '
  : '') + (LATER ? 'Report findings only in the fix delta.' : 'Go deep: this round is the sweep of the whole change.')
const FIND_RULES = [
  'Report every real defect you can tie to a file and line, each with a concrete failure scenario (input or state → wrong outcome).',
  'There is no limit on how many: a defect you leave out is found a round later, after more code sits on top of it. An empty list is a valid answer.',
  'Do not report style, naming or refactors.',
  'Where the code judges free text with patterns or word lists, or works a state out from several fields, do not list the inputs it gets wrong one by one: report the mechanism once, with two example inputs, and say that it is an open class.',
].join(' ')
const brief = (who, a, canWrite) =>
  `${who}\n\n${CONTEXT}\n\n${scopeText(a)}\n\n${diffHowto(canWrite)}\n\n${decidedText}\n\n${witnessText}\n\n${MARKERS}\n\n${FIND_RULES}`

// Codex is a second engine: it does not share the first engine's assumptions. An agent starts it headless and
// read-only, with MCP servers off, and relays what it wrote. The relay does not review.
const CX = `${SCRATCH}/consensus-round-${ROUND}-codex`
const codexBrief = brief('REVIEW-ONLY. You are an independent code reviewer with no context from the author. Do not edit files and do not propose patches. ' +
  `Look for: ${LENSES.map(l => l.focus).join(' Also: ')}`, { name: 'whole change', paths: null }, false) +
  '\n\nReply with JSON only, in the shape you were given: {"findings": [{"file", "line", "summary", "failure_scenario"}]}.'
const relayPrompt = [
  'You start a second review engine and relay its findings. You do not review: do not read the diff, and add, drop or reword nothing.',
  text(A.repo) ? `Run every command in the project at ${A.repo} (cd ${A.repo} first).` : 'Run every command from the repository root.',
  `1. With your file tool, write the text between the BEGIN and END lines below to ${CX}-prompt.txt, exactly.`,
  `2. With your file tool, write this JSON to ${CX}-schema.json: ${JSON.stringify(CODEX_SCHEMA)}`,
  '3. Run this one command in the foreground, allowing at least 15 minutes. If your shell caps a foreground command lower, run it in the background and wait for the output file to stop changing:',
  `   codex exec -m ${CODEX} --sandbox read-only -c 'mcp_servers={}' --output-schema ${CX}-schema.json -o ${CX}.json - < ${CX}-prompt.txt > /dev/null 2> ${CX}.stderr`,
  `4. Read ${CX}.json. Return its findings unchanged, with unavailable set to "".`,
  `If the command is missing, exits nonzero, or ${CX}.json is absent or is not JSON of that shape, return an empty findings list and set unavailable to the actual error line (from ${CX}.stderr when there is one). Never return findings of your own.`,
  '----- BEGIN -----',
  codexBrief,
  '----- END -----',
].join('\n')

phase('Review')
const jobs = RECHECK.length ? [] : AREAS.flatMap((a, ai) => LENSES.map(l => ({ a, ai, l })))
const useCodex = !!CODEX && !RECHECK.length
const outs = await parallel([
  ...jobs.map(({ a, ai, l }) => () =>
    agent(brief(`You are one of three independent code reviewers for this area. You have no context from the author. Your lens: ${l.focus}`, a, true),
      { label: AREAS.length > 1 ? `review:${l.key}:${ai + 1}` : `review:${l.key}`, phase: 'Review', schema: FINDINGS })
      // A dead reviewer stays null so it is not counted as having returned.
      .then(r => (r ? r.findings.map(f => ({ ...f, lens: `${l.key}${AREAS.length > 1 ? `@${ai + 1}` : ''}` })) : null))),
  ...(useCodex ? [() => agent(relayPrompt, { label: 'review:codex', phase: 'Review', schema: RELAY })] : []),
])
const reviews = outs.slice(0, jobs.length)
const relay = useCodex ? outs[jobs.length] : null

// An area where fewer than 2 of its 3 Claude reviewers returned was not reviewed, so the round did not run.
for (let ai = 0; ai < AREAS.length && !RECHECK.length; ai++) {
  const back = reviews.filter((r, j) => r && jobs[j].ai === ai).length
  if (back < 2) return notRun(`${back}/3 in ${AREAS[ai].name}`, `only ${back}/3 reviewers returned for area "${AREAS[ai].name}" — round did not run`)
}
const returned = reviews.filter(Boolean)
// The round counts without Codex; the record says what happened to it.
const codexDown = !CODEX ? null : !relay ? 'the relay did not return' : text(relay.unavailable)
const codexFindings = useCodex && relay && !codexDown ? relay.findings.map(f => ({ ...f, lens: 'codex' })) : []
const codexNote = RECHECK.length ? 'not run (recheck)' : !CODEX ? 'not requested' : codexDown ? `unavailable — ${codexDown}` : `returned ${codexFindings.length}`

// Dedup in code (barrier needed: merge across all finders before paying for verification). Merge only the same
// file and line from a different finder; the merged finder's wording is kept in `also`, and the verifier sees both.
const all = RECHECK.length
  ? RECHECK.map(f => ({ file: f.file, line: Number.isInteger(f.line) ? f.line : 0, summary: f.summary,
      failure_scenario: text(f.failure_scenario) || '(not given)', objection: text(f.objection), lens: 'recheck' }))
  : [...returned.flat(), ...codexFindings]
const merged = []
for (const f of all) {
  const twin = merged.find(m => m.file === f.file && m.line === f.line && !m.lenses.includes(f.lens))
  if (twin) {
    twin.lenses.push(f.lens)
    twin.also.push(f.summary)
  } else {
    merged.push({ ...f, lenses: [f.lens], also: [] })
  }
}
log(RECHECK.length
  ? `recheck of ${merged.length} finding(s)`
  : `${all.length} raw findings from ${returned.length}/${jobs.length} reviewers in ${AREAS.length} area(s), Codex ${codexNote} → ${merged.length} after dedup`)

const verifyOne = (f, i, n) => agent(
  `You are a skeptical verifier. Try to REFUTE this code-review finding against the actual code. If you cannot confirm it from the code, it is not real (real=false). Read the code; do not trust the claim.\n\n` +
  `Finding: ${f.file}:${f.line} — ${f.summary}\nClaimed failure: ${f.failure_scenario}\n` +
  (f.also.length ? `Another reviewer reported at this line: ${f.also.join(' / ')}\n` : '') +
  (f.objection ? `The author objects, and does not vote: ${f.objection}\nThe objection is a claim. Check it against the code like the finding.\n` : '') +
  `\n${CONTEXT}\n\n${IMPACT}\n\n${ORIGIN}\n\n${DIFF_HOWTO}\n\n${priorText}\n\n${fixedText}\n\n${witnessText}\n\n${MARKERS}\n\n` +
  'Give the evidence (file:line and what the code does). When the finding is not real, the impact answers are ignored: give loss "none". Do not modify any file.',
  { label: `verify:${i + 1}.${n}`, phase: 'Verify', schema: VERDICT })

// The one rule for every decision: a value counts only when 2 votes agree on it; a split is null.
const quorum = (votes, key) => {
  const c = {}
  votes.forEach(v => { const k = key(v); c[k] = (c[k] || 0) + 1 })
  return Object.keys(c).find(k => c[k] >= 2) || null
}
const statusKey = v => (v.real ? 'real' : 'not')
const repeatKey = v => v.repeat_of || 'none'
// Round rule 2, the table, applied to one vote. The first line that matches wins.
const serious = v => ['data', 'security', 'person', 'critical'].includes(v.loss) || (v.loss === 'money' && !v.bounded)
const outcome = v =>
  v.loss === 'none' ? 'nit'
  : v.open_class ? 'open'
  : serious(v) || v.reach === 'normal' || v.fix === 'small' ? 'fix'
  : 'ticket'
const reason = v =>
  v.loss === 'none' ? 'nothing wrong happens'
  : v.open_class ? 'one more member of a class with no end'
  : serious(v) ? `serious loss (${v.loss}${v.loss === 'money' ? ', no ceiling' : ''})`
  : v.reach === 'normal' ? 'normal use reaches it'
  : v.fix === 'small' ? 'the fix is small'
  : 'remote, bounded, and costly to fix'
// The label the record keeps (round rule 2): S1 data or money with no ceiling, S2 security or a person, S3 the
// critical domain, S4 anything else normal use reaches, noted any other real defect.
const SEV = ['S1', 'S2', 'S3', 'S4', 'noted', 'nit']
const label = v =>
  v.loss === 'none' ? 'nit'
  : v.loss === 'data' || (v.loss === 'money' && !v.bounded) ? 'S1'
  : v.loss === 'security' || v.loss === 'person' ? 'S2'
  : v.loss === 'critical' ? 'S3'
  : v.reach === 'normal' ? 'S4' : 'noted'
const facts = v => `loss ${v.loss}${v.loss === 'money' ? (v.bounded ? ' (bounded)' : ' (no ceiling)') : ''} · reach ${v.reach} · ${v.silent ? 'silent' : 'noticed'} · fix ${v.fix}`
const decide = votes => {
  const status = quorum(votes, statusKey)
  if (status !== 'real') return { status }
  const yes = votes.filter(v => v.real)
  return { status, outcome: quorum(yes, outcome), repeat: quorum(yes, repeatKey) }
}
const settled = d => d.status === 'not' || (d.status === 'real' && d.outcome && d.repeat)

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
  const base = { file: f.file, line: f.line, summary: f.summary, failure_scenario: f.failure_scenario, also: f.also, finders: f.lenses,
    votes: `${yes.length} real / ${no.length} not / ${votes.length} returned` }
  if (d.status !== 'real') return { ...base, status: d.status === 'not' ? 'rejected' : 'unverified', evidence: votes.map(v => v.evidence).join(' | ') }
  // A split on the outcome means fix now (round rule 2); a split on "is it a repeat" means it is not one.
  const out = d.outcome || 'fix'
  const repeat = d.repeat && d.repeat !== 'none' ? d.repeat : null
  const origin = quorum(yes, v => v.origin) || 'unclear'
  const mech = quorum(yes, v => v.mechanism_of || 'none')
  const sameMechanism = mech && mech !== 'none' ? mech : null
  // Round rule 10, the events that stop patching. Wrong text alone in a fix is just fixed.
  const stop = repeat ? null
    : out === 'open' ? (yes.some(v => serious(v) || v.reach === 'normal') ? 'an open class that normal use or a serious loss reaches' : null)
    : out !== 'fix' ? null
    : sameMechanism ? `the same mechanism as a defect an earlier round fixed (${fixedById[sameMechanism]})`
    : origin === 'fix-introduced' && !yes.every(v => v.loss === 'appearance') ? 'a defect in lines an earlier fix wrote'
    : null
  return {
    ...base, status: 'real', outcome: out,
    class: out === 'nit' ? 'nit' : yes.map(label).filter(c => c !== 'nit').sort((x, y) => SEV.indexOf(x) - SEV.indexOf(y))[0] || 'noted',
    origin,
    why: d.outcome ? reason(yes.find(v => outcome(v) === out)) : 'the voters split, so it is fixed now',
    analysis: yes.map(facts).join(' | '),
    priority: out === 'ticket' ? (yes.some(v => v.reach === 'unusual' || v.silent) ? 'worth fixing' : 'minor') : null,
    repeat_of: repeat ? `${repeat}: ${priorById[repeat] || ''}` : null,
    evidence: yes.map(v => v.evidence).join(' | '),
    stop,
  }
})

const results = judged.filter(Boolean)
const live = results.filter(r => r.status === 'real' && !r.repeat_of)
const redesign = live.filter(r => r.stop)
const mustFix = live.filter(r => r.outcome === 'fix' && !r.stop)
const unverified = results.filter(r => r.status === 'unverified')
// Round rule 8: the origin counts every round record carries.
const origins = live.filter(r => r.outcome !== 'nit').reduce((c, r) => ({ ...c, [r.origin]: (c[r.origin] || 0) + 1 }), {})
// The next step, by event: redesign when patching has stopped working somewhere; fix when anything is left to fix
// or to recheck; otherwise clean. Post-op follows it; no counter and no author decides this.
const next = redesign.length
  ? { action: 'redesign', part: [...new Set(redesign.map(r => r.file))],
      findings: redesign.map(r => `${r.file}:${r.line} — ${r.summary} (${r.stop})`),
      why: `patching has stopped working in the part named; ${mustFix.length} other finding(s) are still fixed in this batch` }
  : mustFix.length || unverified.length
    ? { action: 'fix', why: `${mustFix.length} finding(s) to fix now${unverified.length ? `, ${unverified.length} unverified to send back as recheck` : ''}` }
    : { action: 'clean', why: 'nothing to fix now and nothing unverified' }
log(`${live.length} real (${mustFix.length} fix now, ${redesign.length} stopped for redesign, origins ${JSON.stringify(origins)}), ` +
    `${results.filter(r => r.status === 'rejected').length} rejected, ${results.filter(r => r.status === 'real' && r.repeat_of).length} repeats, ${unverified.length} unverified`)

return {
  ticket: A.ticket || null,
  round: ROUND,
  round_ran: true,
  recheck: RECHECK.length > 0,
  base: `${BASE} (merge-base, working tree included)`,
  scope: LATER ? 'fix delta' : 'whole branch',
  reviewers: RECHECK.length ? 'recheck' : `${returned.length}/${jobs.length} in ${AREAS.length} area(s)`,
  codex: codexNote,
  areas: AREAS.map(a => a.name),
  must_fix: mustFix,
  redesign,
  tickets: live.filter(r => r.outcome === 'ticket'),
  open_class: live.filter(r => r.outcome === 'open' && !r.stop),
  nits: live.filter(r => r.outcome === 'nit'),
  origins,
  repeats: results.filter(r => r.status === 'real' && r.repeat_of),
  rejected: results.filter(r => r.status === 'rejected').map(r => ({ file: r.file, line: r.line, summary: r.summary, votes: r.votes, evidence: r.evidence })),
  unverified,
  next,
}
