import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import test from 'node:test'
import * as vue from 'vue'
import * as i18n from '../src/i18n.js'
import * as simRecord from '../src/utils/simRecord.js'
import * as recordTranslation from '../src/utils/simulationRecordTranslation.js'
import * as world from '../src/utils/worldSimulationView.js'
import * as worldState from '../src/utils/worldState.js'
import * as feedRounds from '../src/utils/feedRounds.js'
import { compileSfc } from './sfcHarness.mjs'
import { loadOverlay } from './simulationTranslationHarness.mjs'

const buildRecord = compileSfc(new URL('../src/components/research/SimulationRecordView.vue', import.meta.url))
const buildParent = compileSfc(new URL('../src/components/research/SimulationView.vue', import.meta.url))
const buildPanel = compileSfc(new URL('../src/components/research/WorldStatePanel.vue', import.meta.url))
const sha = value => createHash('sha256').update(value).digest('hex')
const canonical = value => JSON.stringify(value, (_, item) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) : item)
const settle = async () => { for (let i = 0; i < 30; i++) await new Promise(resolve => setImmediate(resolve)) }
const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes }); return { promise, resolve } }
const translated = value => `中文：${value}`

// Real Vue mounts and patches the compiled SFCs, including child lifecycle and
// event handlers. Only host DOM operations and network transports are replaced.
function mount(t, component, input) {
  const node = (type, text = '') => ({ type, text, props: {}, children: [], parent: null })
  const renderer = vue.createRenderer({
    createElement: type => node(type), createText: text => node('#text', text), createComment: text => node('#comment', text),
    setText: (el, text) => { el.text = text },
    setElementText: (el, text) => { el.children.forEach(child => { child.parent = null }); el.children = []; el.text = text },
    parentNode: el => el.parent,
    nextSibling: el => el.parent?.children[el.parent.children.indexOf(el) + 1] || null,
    patchProp: (el, key, _previous, value) => { el.props[key] = value },
    insert(el, parent, anchor = null) {
      if (el.parent) el.parent.children.splice(el.parent.children.indexOf(el), 1)
      const at = anchor ? parent.children.indexOf(anchor) : -1
      parent.children.splice(at < 0 ? parent.children.length : at, 0, el); el.parent = parent
    },
    remove(el) { if (el.parent) el.parent.children.splice(el.parent.children.indexOf(el), 1); el.parent = null },
  })
  const root = node('root'), props = vue.reactive(input)
  const app = renderer.createApp({ setup: () => () => vue.h(component, props) })
  app.mount(root)
  let unmounted = false
  const unmount = () => { if (!unmounted) { app.unmount(); unmounted = true } }
  t.after(unmount)
  const all = (el = root) => [el, ...el.children.flatMap(all)]
  const text = (el = root) => el.type === '#comment' ? '' : [el.text, ...el.children.map(text)].join(' ').replace(/\s+/g, ' ').trim()
  const buttons = () => all().filter(el => el.type === 'button')
  async function click(label) {
    const found = buttons().find(el => typeof label === 'string' ? text(el) === label : label.test(text(el)))
    assert.ok(found, `button ${label} missing from ${buttons().map(el => text(el)).join(' | ')}`)
    assert.ok(!found.props.disabled, `button ${label} is disabled`)
    await found.props.onClick(); await settle()
  }
  return { props, text, all, buttons, click, unmount }
}

function fixture(engine = 'oasis-legacy') {
  return {
    schema: 'simulation-record/v1', record_class: 'simulated', engine, language: 'en',
    simulation_id: 'sim_A', config_hash: 'a'.repeat(64), generator_version: 'simulation_record/1.0',
    generated_at: '2026-10-26T00:00:00Z', as_of: '2026-10-01', horizon_date: '2026-12-31', calendar_unit: 'month',
    rounds_planned: 2, rounds_committed: 2,
    health: { simulation_health: 'ok', validity: 'valid', organic_actions: 12, arbiter_failed_rounds: 0, seed_gaps: 1 },
    banner: 'Simulated assumptions, not observed evidence.',
    setup: { private_rationale: 'SECRET setup inventory.', variables: [{ provenance: 'HIDDEN setup provenance.' }] },
    periods: [1, 2].map(round => ({
      round, label: `2026-${round === 1 ? '11' : '12'}`, period_start: `2026-${round === 1 ? '11' : '12'}-01`,
      period_end: `2026-${round === 1 ? '11' : '12'}-28`, arbiter_status: 'applied',
      narrative: `Narrative period ${round}: output remains 12 MW [S1].`, arbiter_problems: ['A modelling limitation.'],
      moves: [{ actor: 'actor_A', option: { id: 'option_1', label: 'Publish a schedule' }, targets: ['actor_B'], magnitude: 0.75,
        public_statement: 'Public statement 12 MW.', terms: 'Move terms 12 MW.',
        commitment: { text: 'Deliver 12 MW.', due: '2026-12-31', due_periods: 2 }, private_rationale: 'SECRET private move.' }],
      held_position: ['actor_C'], facts_changed: [{ id: 'capacity', variable: 'Capacity', from: '12.0000', to: '13.0000', unit: 'MW', cause: 'The permit took effect.' }],
      events: [{ description: 'A public event occurred.', private_rationale: 'SECRET event detail.' }],
      shocks_fired: ['A storm arrived.'], red_lines_crossed: [{ actor: 'actor_A', red_line: 'No output below 12 MW.', by: 'actor_B' }],
      offers: [{ from: 'actor_A', to: 'actor_B', kind: 'proposal', status: 'open', terms: 'Offer 12 MW.' }],
      alliances: [{ kind: 'alliance_move', actor: 'actor_A', move: 'join', target: 'actor_B' }],
      behaviour: { moves: 3, responsive_moves: 2, offers_answered: 1 },
      refs: [{ file: 'world_state_history.jsonl', round, id: `history_${round}`, sha256: 'b'.repeat(64) }],
    })),
    overall: {
      final_variables: [{ id: 'capacity', name: 'Final capacity', seed_value: '12.0000', final_value: '13.0000', unit: 'MW' }],
      shares: { final: { 'Steady supply': 0.75 }, paths: { k: 2, per_scenario: { 'Steady supply': { mean: 0.7, sd: 0.1, p10: 0.6, p90: 0.8 } } }, converged_at: 2 },
      turning_points: [{ round: 1, why: 'A permit changed the path.' }], track_records: [{ actor: 'actor_A', kept: 2, lapsed: 1, broken: 0 }],
      synthesis: { generator: 'llm', text: 'Synthesis one.\n\nSynthesis two.' },
    },
    limits: { arbiter_failed_rounds: 0, seed_gaps: [{ description: 'An evidence gap.' }], behaviour_note: 'A textual diagnostic only.', notes: ['A provenance limitation.'] },
  }
}

function transport({ start, get } = {}) {
  const calls = [], cache = new Map()
  function response(id, lang, selection, overrides = {}) {
    const pairs = [...new Set(selection.texts)].map(source => ['text:' + sha(source), source]).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
    return { success: true, data: {
      simulation_id: id, target_lang: lang, context: selection.context,
      request_digest: sha(canonical(['simulation', id, lang, selection.context, pairs])),
      // The backend binds all permitted typed source facts, not just these text
      // pairs. A valid fingerprint is opaque to the frontend and pinned per read.
      source_fingerprint: sha('permitted audited record and typed facts'), status: 'available', pending: 0, issues: [],
      translations: selection.texts.map(source => ({ source, text: translated(source), source_sha256: sha(source) })), ...overrides,
    } }
  }
  const module = loadOverlay({
    async startSimulationTranslation(id, lang, force, options) {
      const call = { operation: 'start', id, lang, force, options }; calls.push(call)
      const res = start ? await start(call, response) : response(id, lang, options)
      cache.set(res.data.request_digest, res)
      return res
    },
    async getSimulationTranslation(id, lang, options) {
      const call = { operation: 'get', id, lang, options }; calls.push(call)
      if (get) return get(call, cache)
      const cached = cache.get(options.params.request_digest)
      if (cached) return cached
      throw Object.assign(new Error('No cached selection'), { response: { status: 404 } })
    },
  })
  return { calls, module, cache, response, starts: () => calls.filter(call => call.operation === 'start') }
}

function imports(http, api = {}) {
  return { vue, '../../i18n': i18n, '../../utils/overlayTranslation': http.module,
    '../../utils/simulationRecordTranslation': recordTranslation, '../../utils/simRecord': simRecord,
    '../../utils/worldSimulationView': world, '../../utils/worldState': worldState,
    '../../utils/feedRounds': feedRounds, '../../api/simulation': api }
}
function mountRecord(t, options = {}) {
  const http = transport(options)
  const h = mount(t, buildRecord(imports(http)), { record: fixture(), simulationId: 'sim_A', generationId: 'gen_A',
    engine: 'oasis-legacy', language: 'en', translationRequest: 0, ...options.props })
  return { ...h, ...http }
}
async function startRecord(h) {
  h.props.language = 'zh'; h.props.translationRequest++; await settle()
}

test('mounted record reconnects read-only in Mandarin and starts/retries only on explicit actions', async t => {
  let attempts = 0
  const h = mountRecord(t, { props: { language: 'zh' }, start: async (call, response) => {
    const res = response(call.id, call.lang, call.options)
    if (++attempts === 1) {
      res.data.status = 'partial'; res.data.pending = 1
      res.data.translations = res.data.translations.filter(row => row.source !== 'Synthesis two.')
      res.data.issues = ['One synthesis paragraph awaits review.']
      res.data.translation_job = { schema: 'translation-job/v2', job_id: 'tj_record', job_revision: 2,
        job_state: 'interrupted', phase: 'reviewing', actions: { retry: true, stop: false },
        coverage: { required: call.options.texts.length, accepted: call.options.texts.length - 1, pending_translation: 0, pending_review: 1, failed: 0, reused: 0 } }
    }
    return res
  } })
  await settle()
  assert.ok(h.calls.some(call => call.operation === 'get'))
  assert.equal(h.starts().length, 0)
  assert.match(h.text(), /Simulated assumptions, not observed evidence/)
  await startRecord(h)
  assert.equal(h.starts().length, 1)
  assert.equal(h.starts()[0].force, false)
  assert.ok(h.text().includes(translated('Synthesis one.')))
  assert.ok(!h.text().includes(translated('Synthesis two.')))
  assert.match(h.text(), /One synthesis paragraph awaits review/)
  await h.click('重试翻译')
  assert.equal(h.starts().length, 2)
  assert.equal(h.starts()[1].force, false)
  assert.ok(h.text().includes(translated('Synthesis two.')))
  assert.ok(!h.buttons().some(button => h.text(button) === '重试翻译'))
})

test('every visible record prose category translates while facts, IDs, references and hidden text stay canonical', async t => {
  const record = fixture(), before = JSON.stringify(record)
  const h = mountRecord(t, { props: { record } })
  await startRecord(h)
  const call = h.starts()[0]
  assert.equal(call.options.context.surface, 'record')
  assert.equal(call.options.context.view, 'record')
  assert.equal(call.options.context.round, 1)
  assert.equal(call.options.context.generation_id, 'gen_A')
  assert.equal(call.options.context.revision, JSON.stringify([record.config_hash, record.generator_version, record.generated_at]))
  const expected = [record.banner, 'month', record.periods[0].narrative, 'A modelling limitation.', 'Publish a schedule',
    'Public statement 12 MW.', 'Move terms 12 MW.', 'Deliver 12 MW.', 'Capacity', 'The permit took effect.',
    'A public event occurred.', 'A storm arrived.', 'actor_A: No output below 12 MW.', 'proposal', 'Offer 12 MW.',
    'actor_A: join → actor_B', 'Final capacity', 'Steady supply', 'A permit changed the path.',
    'Synthesis one.', 'Synthesis two.', 'An evidence gap.', 'A textual diagnostic only.', 'A provenance limitation.']
  for (const source of expected) {
    assert.ok(call.options.texts.includes(source), `missing visible text: ${source}`)
    assert.ok(h.text().includes(translated(source)), `untranslated visible text: ${source}`)
  }
  assert.ok(!call.options.texts.includes(record.periods[1].narrative))
  assert.ok(!call.options.texts.some(text => /SECRET|HIDDEN/.test(text)))
  for (const immutable of ['actor_A', 'actor_B', 'option_1', '12.0000', '13.0000', 'MW', '2026-12-31', 'world_state_history.jsonl']) {
    assert.ok(!call.options.texts.includes(immutable), `immutable value was inventoried: ${immutable}`)
  }
  for (const fact of ['12.0000 MW', '13.0000 MW', '0.75', '75%', '70%', '60% – 80%', '2026-12-31', 'sim_A', 'simulation_record/1.0']) assert.ok(h.text().includes(fact), fact)
  assert.equal(JSON.stringify(record), before)
})

test('period/source/generation/language changes reject late output and never replay a provider start', async t => {
  const old = deferred()
  const h = mountRecord(t, { start: async (call, response) => {
    if (call.options.context.round === 1) await old.promise
    return response(call.id, call.lang, call.options)
  } })
  await startRecord(h)
  assert.equal(h.starts().length, 1)
  const previous = h.starts()[0]
  await h.click('2026-12')
  assert.equal(previous.options.signal.aborted, true)
  assert.equal(h.starts().length, 1)
  assert.ok(h.text().includes(fixture().periods[1].narrative))
  old.resolve(); await settle()
  assert.ok(!h.text().includes(translated(fixture().periods[0].narrative)))
  await h.click('重试翻译')
  assert.equal(h.starts().at(-1).options.context.round, 2)
  assert.ok(h.text().includes(translated(fixture().periods[1].narrative)))
  h.props.record = { ...h.props.record, banner: 'New source banner.', generated_at: '2026-10-26T01:00:00Z' }
  await settle()
  assert.equal(h.starts().length, 2)
  assert.ok(h.text().includes('New source banner.'))
  assert.ok(!h.text().includes(translated('New source banner.')))
  h.props.generationId = 'gen_B'; await settle()
  assert.equal(h.starts().length, 2)
  assert.equal(JSON.parse(h.calls.at(-1).options.params.context).generation_id, 'gen_B')
  assert.equal(JSON.parse(h.calls.at(-1).options.params.context).round, 1)
  h.props.language = 'en'; await settle()
  assert.ok(!h.text().includes('中文：'))
  assert.equal(h.starts().length, 2)
})

test('late record arrival and remount with an old request token are passive; unmount cancels late translation', async t => {
  const pending = deferred()
  const h = mountRecord(t, { props: { record: null, language: 'zh', translationRequest: 7 },
    start: async (call, response) => { await pending.promise; return response(call.id, call.lang, call.options) } })
  await settle(); assert.equal(h.calls.length, 0)
  h.props.record = fixture(); await settle()
  assert.equal(h.starts().length, 0)
  await startRecord(h)
  assert.equal(h.starts().length, 1)
  h.unmount()
  assert.equal(h.starts()[0].options.signal.aborted, true)
  pending.resolve(); await settle()
  assert.equal(h.text(), '')
  assert.equal(h.starts().length, 1)
})

test('unusable records inventory only the visible health/header and never hidden period/overall prose', async t => {
  const record = fixture(); record.limits.stub = true
  const h = mountRecord(t, { props: { record } })
  await startRecord(h)
  const texts = h.starts()[0].options.texts
  assert.ok(texts.includes(record.banner))
  assert.ok(texts.includes('A provenance limitation.'))
  assert.ok(!texts.includes(record.periods[0].narrative))
  assert.ok(!texts.includes('Synthesis one.'))
  assert.ok(!texts.includes('An evidence gap.'))
  assert.match(h.text(), /12/)
  assert.ok(!h.text().includes('Narrative period'))
})

test('an empty health-only record binds a null round and the exact revision tuple', async t => {
  const record = fixture()
  record.periods = []; record.rounds_committed = 0; record.limits.stub = true
  delete record.config_hash; delete record.generator_version; delete record.generated_at
  const h = mountRecord(t, { props: { record } })
  await startRecord(h)
  assert.equal(h.starts().length, 1)
  assert.equal(h.starts()[0].options.context.round, null)
  assert.equal(h.starts()[0].options.context.revision, '["","",""]')
  assert.ok(!h.starts()[0].options.texts.includes('Synthesis one.'))
  assert.ok(!h.buttons().some(button => /^2026-/.test(h.text(button))))
})

for (const engine of ['oasis-legacy', 'world-v1']) {
  test(`${engine}: mounted parent language control reaches actual completed record and excludes hidden live feeds`, async t => {
    i18n.locale.value = 'en'; t.after(() => { i18n.locale.value = 'en' })
    const http = transport(), record = fixture(engine)
    const api = {
      getSimulation: async id => ({ success: true, data: { simulation_id: id, simulation_engine: engine, world_generation_id: 'gen_A', status: 'completed' } }),
      getSimulationProfilesRealtime: async () => ({ success: true, data: { profiles: [{ name: 'Actor', bio: 'HIDDEN live persona.' }] } }),
      getSimulationPosts: async () => ({ success: true, data: { posts: [{ post_id: 1, content: 'HIDDEN live feed.' }] } }),
      getSimulationComments: async () => ({ success: true, data: { comments: [{ post_id: 1, content: 'HIDDEN live reply.' }] } }),
      getAgentStats: async () => ({ success: true, data: {} }),
      getRunStatus: async () => ({ success: true, data: { simulation_engine: engine, runner_status: 'completed' } }),
      getFeedRounds: async () => ({ success: true, data: { rounds: [] } }),
      fetchRecord: async () => ({ record, status: 200, publicationStatus: 'passed' }),
    }
    const child = buildRecord(imports(http))
    const empty = { render: () => vue.h('aside') }
    const parent = buildParent({ ...imports(http, api), './SimulationRecordView.vue': { default: child },
      './WorldSimulationView.vue': { default: empty }, './WorldStatePanel.vue': { default: empty } })
    const h = mount(t, parent, { simulationId: 'sim_A', stageStatus: 'completed' })
    await settle()
    assert.ok(h.text().includes('Scenario simulation · after-action record'))
    assert.equal(http.starts().length, 0)
    await h.click('中文 · 翻译整个模拟')
    assert.equal(http.starts().length, 1)
    assert.equal(http.starts()[0].options.context.engine, engine)
    assert.equal(http.starts()[0].options.context.surface, 'record')
    assert.ok(h.text().includes(translated(record.banner)))
    assert.ok(!http.starts().some(call => call.options.texts.some(text => text.includes('HIDDEN'))))
    assert.equal(i18n.locale.value, 'en')
    // Returning to the record in Mandarin observes its cached inventory. The old
    // click token cannot create another provider request on the new child mount.
    await h.click('实时视图'); await h.click('记录')
    assert.equal(http.starts().length, 1)
    assert.ok(h.text().includes(translated(record.banner)))
    await h.click('原文 / English')
    assert.equal(http.starts().length, 1)
    assert.ok(h.text().includes(record.banner))
    assert.ok(!h.text().includes(translated(record.banner)))
  })
}

test('one parent click starts the visible feed and WorldStatePanel including provenance; reads and remounts never replay it', async t => {
  i18n.locale.value = 'en'; t.after(() => { i18n.locale.value = 'en' })
  const http = transport(), record = fixture()
  let data = {
    committed_round: 1, period: { label: '2026-11' },
    variables: [{ id: 'capacity', name: 'Capacity', value: 12, unit: 'MW', provenance: 'Derived from official observations [S1].', history: [] }],
    history: [{ round: 1, period_label: '2026-11', arbiter_status: 'applied', narrative: 'The permit takes effect.',
      diff: { variables_changed: [], variables_added: [], relationships_changed: [] }, deterministic: {} }],
  }
  const original = JSON.stringify(data)
  const api = {
    getSimulation: async id => ({ success: true, data: { simulation_id: id, simulation_engine: 'oasis-legacy', status: 'completed' } }),
    getSimulationProfilesRealtime: async () => ({ success: true, data: { profiles: [{ name: 'Actor', bio: 'A public persona.' }] } }),
    getSimulationPosts: async () => ({ success: true, data: { posts: [{ post_id: 1, content: 'A public feed entry.' }] } }),
    getSimulationComments: async () => ({ success: true, data: { comments: [] } }),
    getAgentStats: async () => ({ success: true, data: {} }),
    getRunStatus: async () => ({ success: true, data: { simulation_engine: 'oasis-legacy', runner_status: 'completed' } }),
    getFeedRounds: async () => ({ success: true, data: { rounds: [] } }),
    fetchRecord: async () => ({ record, status: 200, publicationStatus: 'passed' }),
    getWorldState: async () => ({ data }),
  }
  const parent = buildParent({ ...imports(http, api),
    './SimulationRecordView.vue': { default: buildRecord(imports(http)) },
    './WorldStatePanel.vue': { default: buildPanel(imports(http, api)) },
    './WorldSimulationView.vue': { default: { render: () => vue.h('aside') } },
  })
  const h = mount(t, parent, { simulationId: 'sim_A', stageStatus: 'completed' })
  await settle()
  await h.click('Live view')
  assert.ok(h.text().includes('A public feed entry.'))
  assert.ok(h.text().includes('Derived from official observations [S1].'))
  assert.equal(http.starts().length, 0)
  await h.click('中文 · 翻译整个模拟')
  assert.equal(http.starts().length, 2, 'one explicit click starts both visible inventories')
  const feed = http.starts().find(call => call.options.context.platform === 'twitter')
  const panel = http.starts().find(call => call.options.context.platform === '')
  assert.ok(feed.options.texts.includes('A public feed entry.'))
  assert.ok(!feed.options.texts.includes('Derived from official observations [S1].'))
  assert.ok(panel.options.texts.includes('Derived from official observations [S1].'))
  assert.ok(!panel.options.texts.includes('A public feed entry.'))
  assert.ok(http.starts().every(call => call.force === false))
  assert.ok(h.text().includes(translated('A public feed entry.')))
  assert.ok(h.text().includes(translated('Derived from official observations [S1].')))
  assert.ok(h.text().includes('12 MW'))
  assert.equal(JSON.stringify(data), original)
  await h.click('记录'); await h.click('实时视图')
  assert.equal(http.starts().length, 2, 'remount cannot replay the previous token')
  data = { ...data, variables: [{ ...data.variables[0], provenance: 'Updated official observation [S2].' }] }
  await h.click('刷新')
  assert.equal(http.starts().length, 2, 'fresh source reads cannot replay the previous token')
  assert.ok(h.text().includes('Updated official observation [S2].'))
  assert.ok(!h.text().includes(translated('Updated official observation [S2].')))
  await h.click('原文 / English')
  assert.equal(http.starts().length, 2)
})

test('mounted WorldStatePanel translates visible explanatory provenance with facts intact, excluding hidden rows/past provenance', async t => {
  const http = transport()
  const data = {
    committed_round: 2, period: { label: '2026-12' },
    variables: Array.from({ length: 13 }, (_, i) => ({ id: `fact_${i}`, name: `Capacity ${i}`, value: 12.125, unit: 'MW',
      provenance: i < 12 ? 'Derived from official observations [S1].' : 'HIDDEN row provenance.', history: [] })),
    history: [1, 2].map(round => ({ round, period_label: `2026-${round === 1 ? '11' : '12'}`, arbiter_status: 'applied',
      narrative: `Period ${round}.`, diff: { variables_changed: [], variables_added: [], relationships_changed: [] }, deterministic: {} })),
  }
  const before = JSON.stringify(data)
  const h = mount(t, buildPanel(imports(http, { getWorldState: async () => ({ data }) })),
    { simulationId: 'sim_A', language: 'en', pollMs: 0 })
  await settle()
  assert.ok(h.text().includes('Derived from official observations [S1].'))
  const displayedFact = worldState.summarizeWorldState(data).variables[0].display
  assert.ok(h.text().includes(displayedFact))
  await h.click('中文')
  assert.equal(http.starts().length, 1)
  assert.ok(http.starts()[0].options.texts.includes('Derived from official observations [S1].'))
  assert.ok(!http.starts()[0].options.texts.includes('HIDDEN row provenance.'))
  assert.ok(h.text().includes(translated('Derived from official observations [S1].')))
  assert.ok(h.text().includes(displayedFact))
  await h.click('2026-11')
  assert.equal(http.starts().length, 1)
  await h.click('重试翻译')
  assert.ok(!http.starts().at(-1).options.texts.includes('Derived from official observations [S1].'))
  assert.equal(JSON.stringify(data), before)
})
