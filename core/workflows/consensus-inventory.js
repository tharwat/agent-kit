// Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License).
// The dependency inventory for /operate Phase 1 (section "Plan"), built BEFORE the code is written. A fix batch
// no longer runs it: a fix writes a short fix note instead (/operate, "Every fix batch").
// 3 independent enumerators → merge in code → 1 completeness critic → 2 verifiers on every
// item only one source found → one inventory.json section.
// Why: about half of all review findings are a reader, writer, sibling, claim or list member
// that one agent missed. Three independent searches miss far less than one; a disputed item is
// kept unless both verifiers refute it (a false row costs a check, a missed one costs a bug).
// Run it by scriptPath (<repo root>/.claude/workflows/consensus-inventory.js), never by name.
export const meta = {
  name: 'consensus-inventory',
  description: 'Dependency inventory before code: 3 independent enumerators, merge, completeness critic, 2 verifiers per single-source item',
  whenToUse: 'Called by /operate Phase 1 (section Plan). args: ticket, section, base, plan, contract, planCheck, scratchDir, repo',
  phases: [
    { title: 'Enumerate', detail: '3 agents enumerate independently from the source' },
    { title: 'Critic', detail: 'one agent looks for what all three missed' },
    { title: 'Verify', detail: '2 verifiers on every item only one source found' },
  ],
}

const A = args || {}
const text = x => (typeof x === 'string' && x.trim()) || null
const TICKET = text(A.ticket) || '(none)'
const SECTION = text(A.section) || 'Plan'
const BASE = text(A.base)
const PLAN = text(A.plan)
const SCRATCH = text(A.scratchDir) || '.claude/state/tmp'
const WHERE = text(A.repo) ? `Work only in the project at ${A.repo}: run every command there (cd ${A.repo} first).` : 'Work in the current project checkout.'

const notRun = why => {
  log(why)
  return { ran: false, reason: why, section: null }
}
if (!PLAN) return notRun('args.plan is missing: the planned change is the input')

const CONTEXT = [
  `Ticket: ${TICKET} · inventory section: ${SECTION}.`,
  `Base: ${BASE || '(not given)'}. ${WHERE}`,
  `Acceptance contract: ${text(A.contract) || '(see .claude/state/<ticket>/triage.md)'}`,
  `Plan self-check (state homes, derived lists): ${text(A.planCheck) || '(see .claude/state/<ticket>/plan-check.json)'}`,
  `The planned change:\n${PLAN}`,
].join('\n')

const RULES = [
  'Rules for every entry:',
  '- Find it by searching the source, never from memory. Record in `search` the exact command, query or parse you ran, so it can be repeated.',
  '- A location is `path:line` or `path:line-line`. Read the code at it before listing it.',
  '- Include indirect readers: anything that branches on the value, counts, displays, logs or relays it to a person.',
  '- A claim that something is SAFE or has NO effect (a dry-run, a local command, a read-only path) needs every call followed: static and dynamic imports, queue and job handlers, what a job does when real work is waiting. List every outside effect you found in `effects` (database writes, external calls, messages, alerts, token refreshes or saves, jobs started). An empty `effects` is a claim too: search for it.',
  '- A list the change writes or relies on (columns, tables, folders, services, routes, imports, safe actions) is derived from the real source (a schema query, a directory walk, an import graph from a real parser, a route table), never typed by hand. Give `derived_from` and every member.',
  '- `subject` and `what` are identifiers, not prose: a path, a table.column, a service name, a short kebab-case list name.',
  'Read only. Do not modify any project file, commit, or run anything that writes, except scratch files under ' + SCRATCH + '.',
].filter(Boolean).join('\n')

const LOCS = { type: 'array', items: { type: 'string' } }
const ANSWER = { type: 'object', properties: { answer: { type: 'string' }, why: { type: 'string' } }, required: ['answer'] }
const INVENTORY = {
  type: 'object',
  properties: {
    values: { type: 'array', items: { type: 'object', properties: {
      value: { type: 'string' }, change: { type: 'string' }, writers: LOCS, readers: LOCS,
      reader_assumes: { type: 'string' }, needs_change: ANSWER, search: { type: 'string' } },
      required: ['value', 'change', 'writers', 'readers', 'reader_assumes', 'needs_change', 'search'] } },
    siblings: { type: 'array', items: { type: 'object', properties: {
      behaviour: { type: 'string' }, sibling: { type: 'string' }, guards: { type: 'array', items: { type: 'string' } },
      copied: ANSWER, search: { type: 'string' } },
      required: ['behaviour', 'sibling', 'guards', 'copied', 'search'] } },
    helpers: { type: 'array', items: { type: 'object', properties: {
      helper: { type: 'string' }, where: { type: 'string' }, short_circuits: { type: 'string' },
      errors: { type: 'string' }, success: { type: 'string' } },
      required: ['helper', 'where', 'short_circuits', 'errors', 'success'] } },
    claims: { type: 'array', items: { type: 'object', properties: {
      subject: { type: 'string' }, claim: { type: 'string' }, proof: LOCS,
      effects: { type: 'array', items: { type: 'string' } }, search: { type: 'string' } },
      required: ['subject', 'claim', 'proof', 'effects', 'search'] } },
    lists: { type: 'array', items: { type: 'object', properties: {
      what: { type: 'string' }, derived_from: { type: 'string' }, members: { type: 'array', items: { type: 'string' } } },
      required: ['what', 'derived_from', 'members'] } },
  },
  required: ['values', 'siblings', 'helpers', 'claims', 'lists'],
}

const ASK = [
  'Build the dependency inventory for this change, before any code is written.',
  '- values: every value the change alters (a column, field, enum value, status, mode, flag, the meaning of an existing value, a function\'s return or error contract, a config key, a response shape), with EVERY writer and reader.',
  '- siblings: every new behaviour that does a job an existing path already does (sends a message, screens input, retries, runs in a scheduled job, handles a burst, writes a status), with every guard the sibling has (error and retry shape, fail-closed checks, burst handling, time budget, synthetic or test-data refusal, idempotency and compare-and-swap, log redaction, user-facing wording, gate order) and whether the new path needs it.',
  '- helpers: every existing helper the change will call: its short-circuits, the error shape it throws or returns, what success means.',
  '- claims: every factual statement the change will make in code, docs, config or data, with the code that proves it (and, for a safety claim, every effect found).',
  '- lists: every list the change writes or relies on, derived from the source, with every member.',
  'An empty list is a valid answer only after a search that shows there is nothing; say so in `search`.',
].join('\n')

phase('Enumerate')
const raw = await parallel([0, 1, 2].map(k => () =>
  agent(`You are enumerator ${k + 1} of 3, working independently. Be exhaustive: a missed reader, sibling, claim or list member is the most common cause of a bug in review.\n\n${CONTEXT}\n\n${RULES}\n\n${ASK}`,
    { label: `enumerate:${k + 1}`, phase: 'Enumerate', schema: INVENTORY })))
const sources = raw.filter(Boolean)
if (sources.length < 2) return notRun(`only ${sources.length}/3 enumerators returned: the inventory did not run`)

// ---- merge in code: one entry per key, every location and member unioned, with how many sources found it
const norm = s => String(s || '').trim().toLowerCase().replace(/\s+/g, ' ')
const fileOf = loc => norm(loc).split(':')[0]
const KEYS = {
  values: v => norm(v.value),
  siblings: s => `${norm(s.behaviour)}|${fileOf(s.sibling)}`,
  helpers: h => norm(h.helper),
  claims: c => norm(c.subject),
  lists: l => norm(l.what),
}
const SETS = { values: ['writers', 'readers'], siblings: ['guards'], helpers: [], claims: ['proof', 'effects'], lists: ['members'] }
const merged = Object.fromEntries(Object.keys(KEYS).map(k => [k, []]))
const addFrom = (src, label) => {
  for (const kind of Object.keys(KEYS)) {
    for (const item of src[kind] || []) {
      const key = KEYS[kind](item)
      if (!key) continue
      let m = merged[kind].find(x => x._key === key)
      if (!m) {
        m = { ...item, _key: key, _by: new Set(), _sets: {} }
        for (const f of SETS[kind]) m._sets[f] = new Map()
        merged[kind].push(m)
      }
      m._by.add(label)
      if (kind === 'values' && item.needs_change && item.needs_change.answer === 'yes') m.needs_change = item.needs_change
      if (kind === 'siblings' && item.copied && item.copied.answer === 'yes') m.copied = item.copied
      if (item.search && !(m.search || '').includes(item.search)) m.search = m.search ? `${m.search} ; ${item.search}` : item.search
      for (const f of SETS[kind]) {
        for (const x of item[f] || []) {
          const xk = norm(x)
          if (!xk) continue
          if (!m._sets[f].has(xk)) m._sets[f].set(xk, { text: x, by: new Set() })
          m._sets[f].get(xk).by.add(label)
        }
      }
    }
  }
}
sources.forEach((s, i) => addFrom(s, `e${i + 1}`))

// ---- the completeness critic: what did all three miss?
phase('Critic')
const snapshot = kind => merged[kind].map(m => ({ key: m._key, ...Object.fromEntries(SETS[kind].map(f => [f, [...m._sets[f].values()].map(x => x.text)])) }))
const critic = await agent(
  `You are the completeness critic. Three agents built this dependency inventory independently. Your only job is to find what ALL of them missed: a reader or writer not listed, a sibling path, a helper, a claim the change makes, a list member. Search the source for each; report only additions you can tie to a location or a query result. Report nothing already listed.\n\n${CONTEXT}\n\n${RULES}\n\nThe merged inventory so far:\n${JSON.stringify(Object.fromEntries(Object.keys(KEYS).map(k => [k, snapshot(k)])))}`,
  { label: 'critic', phase: 'Critic', schema: INVENTORY })
if (critic) addFrom(critic, 'critic')

// ---- verify every item and every location or member that only one source found
const disputed = []
for (const kind of Object.keys(KEYS)) {
  for (const m of merged[kind]) {
    if (m._by.size === 1) disputed.push({ id: `D${disputed.length + 1}`, kind, key: m._key, what: 'entry', item: m })
    for (const f of SETS[kind]) {
      if (f === 'guards' || f === 'effects') continue  // a guard or an effect listed once is kept: missing one is the bug
      for (const x of m._sets[f].values()) {
        if (m._by.size > 1 && x.by.size === 1) disputed.push({ id: `D${disputed.length + 1}`, kind, key: m._key, what: f, item: x.text })
      }
    }
  }
}
log(`${sources.length}/3 enumerators${critic ? ' + critic' : ''}: ${Object.keys(KEYS).map(k => `${merged[k].length} ${k}`).join(', ')}; ${disputed.length} single-source items to verify`)

const VERDICTS = {
  type: 'object',
  properties: { verdicts: { type: 'array', items: { type: 'object', properties: {
    id: { type: 'string' }, real: { type: 'boolean' }, evidence: { type: 'string' } }, required: ['id', 'real', 'evidence'] } } },
  required: ['verdicts'],
}
const describe = d => d.what === 'entry'
  ? `${d.id} · ${d.kind} entry "${d.key}": ${JSON.stringify(Object.fromEntries(Object.entries(d.item).filter(([k]) => !k.startsWith('_'))))}`
  : `${d.id} · ${d.kind} "${d.key}" ${d.what}: ${d.item}`
let refuted = new Set()
if (disputed.length) {
  phase('Verify')
  const votes = (await parallel(['a', 'b'].map(v => () => agent(
    `You are a skeptical verifier. Only one source found each item below. For each, check the source: is it real and relevant to this change (the location reads or writes the value, the sibling does the same job, the claim's subject is what the change states, the member belongs in the list)? real=false only when the source shows it is wrong or unrelated; give the evidence either way.\n\n${CONTEXT}\n\n${RULES}\n\nItems:\n${disputed.map(describe).join('\n')}`,
    { label: `verify:${v}`, phase: 'Verify', schema: VERDICTS })))).filter(Boolean)
  const notReal = {}
  for (const vote of votes) for (const v of vote.verdicts || []) if (v.real === false) notReal[v.id] = (notReal[v.id] || 0) + 1
  // dropped only when two verifiers agree it is wrong; one verifier returning, or a split, keeps it
  refuted = new Set(Object.keys(notReal).filter(id => notReal[id] >= 2))
}
const dropped = disputed.filter(d => refuted.has(d.id))
const dropEntry = new Set(dropped.filter(d => d.what === 'entry').map(d => `${d.kind}|${d.key}`))
const dropPart = new Set(dropped.filter(d => d.what !== 'entry').map(d => `${d.kind}|${d.key}|${d.what}|${norm(d.item)}`))

const out = kind => merged[kind].filter(m => !dropEntry.has(`${kind}|${m._key}`)).map(m => {
  const row = Object.fromEntries(Object.entries(m).filter(([k]) => !k.startsWith('_')))
  for (const f of SETS[kind]) {
    row[f] = [...m._sets[f].entries()].filter(([xk]) => !dropPart.has(`${kind}|${m._key}|${f}|${xk}`)).map(([, x]) => x.text)
  }
  if (kind === 'values') for (const f of ['writers', 'readers']) if (!row[f].length) row[f] = ['none']
  row.found_by = m._by.size
  return row
})

const section = {
  name: SECTION,
  values: out('values'),
  values_none_search: merged.values.length ? null : `searched by ${sources.length} enumerators and the critic; none`,
  siblings: out('siblings'),
  siblings_none_search: merged.siblings.length ? null : `searched by ${sources.length} enumerators and the critic; none`,
  helpers: out('helpers'),
  claims: out('claims'),
  lists: out('lists'),
  consensus: {
    enumerators: `${sources.length}/3`,
    critic: Boolean(critic),
    single_source: disputed.length,
    dropped: dropped.map(d => `${describe(d)} (refuted by both verifiers)`),
  },
}
return { ran: true, ticket: TICKET, section }
