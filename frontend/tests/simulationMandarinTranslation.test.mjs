import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'
import * as i18n from '../src/i18n.js'
import * as world from '../src/utils/worldSimulationView.js'
import * as worldState from '../src/utils/worldState.js'
import * as feedRounds from '../src/utils/feedRounds.js'
import * as simRecord from '../src/utils/simRecord.js'
import { compileSfc } from './sfcHarness.mjs'
import { loadOverlay } from './simulationTranslationHarness.mjs'

const sha = source => createHash('sha256').update(source).digest('hex')
const settle = async () => { for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve)) }
const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes }); return { promise, resolve } }
const prose = html => html.replace(/<!--[^]*?-->/g, '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ')

function response(id, lang, selection, changes = {}) {
  return { success: true, data: {
    simulation_id: id, target_lang: lang, context: selection.context,
    request_digest: sha(JSON.stringify([id, lang, selection.context, selection.texts])),
    source_fingerprint: sha(JSON.stringify(selection.texts)), status: 'available', pending: 0, issues: [],
    translations: selection.texts.map(source => ({ source, text: `译文：${source}`, source_sha256: sha(source) })),
    ...changes,
  } }
}
function transport({ translate = source => `译文：${source}`, start, get } = {}) {
  const calls = [], cache = new Map()
  const module = loadOverlay({
    async startSimulationTranslation(id, lang, force, options) {
      calls.push({ operation: 'start', id, lang, force, options })
      const res = start ? await start(id, lang, force, options) : response(id, lang, options, {
        translations: options.texts.map(source => ({ source, text: translate(source), source_sha256: sha(source) })),
      })
      cache.set(res.data.request_digest, res)
      return res
    },
    async getSimulationTranslation(id, lang, options) {
      calls.push({ operation: 'get', id, lang, options })
      return get ? get(id, lang, options) : cache.get(options.params.request_digest)
    },
  })
  return { module, calls }
}
function controller(t, options = {}) {
  const http = transport(options)
  const current = vue.reactive({ id: 'sim_A', lang: 'en', context: { engine: 'oasis-legacy', platform: 'twitter', round: 2, view: 'public' }, texts: ['Supply remains 12 MW.'] })
  const scope = vue.effectScope()
  const state = scope.run(() => http.module.useSimulationTranslation({ simulationId: () => current.id,
    language: () => current.lang, context: () => current.context, texts: () => current.texts, pollMs: 0 }))
  t.after(() => scope.stop())
  return { ...http, current, state, scope }
}

test('real API adapter sends visible text/context and cancellation without putting source text in query strings', async () => {
  let code = readFileSync(new URL('../src/api/translations.js', import.meta.url), 'utf8')
  code = code.replace(/^import service[^\n]*\n/m, '').replace(/^export /gm, '')
  const calls = []
  const api = new Function('service', `${code}\nreturn {getSimulationTranslation,startSimulationTranslation}`)({
    post: (...args) => { calls.push(['post', ...args]) }, get: (...args) => { calls.push(['get', ...args]) },
  })
  const signal = new AbortController().signal
  api.startSimulationTranslation('sim_A', 'zh', true, { texts: ['Supply remains 12 MW.'], context: { round: 2 }, signal })
  api.getSimulationTranslation('sim_A', 'zh', { params: { request_digest: 'a'.repeat(64) }, signal })
  assert.equal(calls[0][1], '/api/simulation/sim_A/translations/zh?force=1')
  assert.deepEqual(calls[0][2].texts, ['Supply remains 12 MW.'])
  assert.deepEqual(calls[0][2].context, { round: 2 })
  assert.equal(calls[0][3].signal, signal)
  assert.equal(calls[1][2].signal, signal)
  assert.equal(calls[1][2].params.request_digest, 'a'.repeat(64))
})

test('source mode does not acquire; local Mandarin switch does not require a global UI language change', async t => {
  const h = controller(t)
  await settle()
  assert.equal(h.calls.length, 0)
  h.state.toggle()
  await settle()
  assert.equal(h.current.lang, 'en')
  assert.equal(h.state.lang.value, 'zh')
  assert.equal(h.state.L('世界状态', 'World state'), '世界状态')
  assert.equal(h.state.display('Supply remains 12 MW.'), '译文：Supply remains 12 MW.')
  assert.equal(h.state.status.value, 'available')
  assert.deepEqual(h.calls[0].options.context, h.current.context)
})

test('stable enum labels and conventional acronyms translate locally without unnecessary provider failures', async t => {
  const h = controller(t)
  h.current.texts = ['company', 'applied', 'official', 'USD', 'OASIS']
  h.state.toggle(); await settle()
  assert.equal(h.calls.length, 0)
  assert.equal(h.state.display('company'), '企业')
  assert.equal(h.state.display('applied'), '已应用')
  assert.equal(h.state.display('official'), '官方数据')
  assert.equal(h.state.display('USD'), 'USD')
  assert.equal(h.state.display('OASIS'), 'OASIS')
  assert.equal(h.state.feedback.value, '')
})

test('partial output is disclosed, successful passages render and retry uses force', async t => {
  let count = 0
  const h = controller(t, { start: async (id, lang, force, selection) => response(id, lang, selection, ++count === 1
    ? { status: 'partial', partial: true, pending: 1, translations: [], issues: ['one passage failed integrity'] }
    : {}) })
  h.state.toggle(); await settle()
  assert.equal(h.state.status.value, 'partial')
  assert.equal(h.state.display('Supply remains 12 MW.'), 'Supply remains 12 MW.')
  assert.match(h.state.feedback.value, /保留原文/)
  assert.equal(h.state.retryable.value, true)
  await h.state.retry()
  assert.equal(h.calls.at(-1).force, true)
  assert.equal(h.state.status.value, 'available')
  assert.equal(h.state.feedback.value, '')
})

test('polling uses the exact returned digest and bound context, with partial updates before final completion', async t => {
  const h = controller(t, { start: async (id, lang, _force, selection) => response(id, lang, selection, { status: 'generating', translations: [], pending: 1 }),
    get: async (id, lang, options) => response(id, lang, { texts: ['Supply remains 12 MW.'], context: JSON.parse(options.params.context) }) })
  h.state.toggle(); await new Promise(resolve => setTimeout(resolve, 15)); await settle()
  assert.equal(h.state.status.value, 'available')
  assert.equal(h.calls[1].operation, 'get')
  assert.equal(h.calls[1].options.params.request_digest, sha(JSON.stringify(['sim_A', 'zh', h.current.context, h.current.texts])))
  assert.deepEqual(JSON.parse(h.calls[1].options.params.context), h.current.context)
})

test('same-run new content refreshes and old delayed output cannot bind to a new period, platform, actor or language', async t => {
  const old = deferred()
  let first = true
  const h = controller(t, { start: async (id, lang, _force, options) => {
    if (first) { first = false; await old.promise }
    return response(id, lang, options)
  } })
  h.state.toggle(); await settle()
  h.current.id = 'sim_B'; h.current.context = { engine: 'world-v1', round: 3, generation_id: 'gen_B', revision: 'r3', view: 'actor', actor_id: 'actor_B' }
  h.current.texts = ['New actor decision.']; await settle()
  assert.equal(h.state.display('New actor decision.'), '译文：New actor decision.')
  const firstSignal = h.calls[0].options.signal
  assert.equal(firstSignal.aborted, true)
  old.resolve(); await settle()
  assert.equal(h.state.display('Supply remains 12 MW.'), 'Supply remains 12 MW.')
  assert.equal(h.state.display('New actor decision.'), '译文：New actor decision.')
  h.current.texts = ['Updated actor decision.']; await settle()
  assert.equal(h.state.display('Updated actor decision.'), '译文：Updated actor decision.')
  h.state.toggle(); await settle()
  assert.equal(h.state.display('Updated actor decision.'), 'Updated actor decision.')
  assert.equal(h.state.busy.value, false)
})

test('foreign identity, context, source fingerprint and digest responses fail visibly rather than render', async t => {
  for (const change of [
    { simulation_id: 'sim_foreign' }, { target_lang: 'en' }, { request_digest: '' },
    { context: { view: 'analyst' } }, { source_fingerprint: '' },
  ]) {
    const h = controller(t, { start: async (id, lang, _force, options) => response(id, lang, options, change) })
    h.state.toggle(); await settle()
    assert.equal(h.state.status.value, 'error')
    assert.equal(h.state.display('Supply remains 12 MW.'), 'Supply remains 12 MW.')
    assert.match(h.state.feedback.value, /请重试/)
  }
})

test('request cancellation after disposal prevents a delayed POST from mutating state', async t => {
  const old = deferred()
  const h = controller(t, { start: async (id, lang, _force, options) => { await old.promise; return response(id, lang, options) } })
  h.state.toggle(); await settle()
  h.scope.stop(); old.resolve(); await settle()
  assert.equal(h.calls[0].options.signal.aborted, true)
  assert.equal(h.state.status.value, 'source')
  assert.equal(h.state.display('Supply remains 12 MW.'), 'Supply remains 12 MW.')
})

test('cancellation interrupts the actual polling timer without issuing another GET', async () => {
  const m = loadOverlay(), controller = new AbortController()
  let gets = 0
  const task = m.ensureOverlay({ preferStart: true, start: async () => ({ data: { status: 'generating' } }),
    get: async () => { gets++; return { data: { status: 'available' } } } }, 'zh', { signal: controller.signal, pollMs: 60000 })
  await settle(); controller.abort()
  assert.equal((await task).status, 'cancelled')
  assert.equal(gets, 0)
})

test('poll results changing digest, source fingerprint or actor context are rejected', async () => {
  for (const change of [{ request_digest: 'c'.repeat(64) }, { source_fingerprint: 'd'.repeat(64) }, { context: { view: 'analyst' } }]) {
    const selection = { texts: ['Demand remains stable.'], context: { view: 'public', round: 2 } }
    const http = transport({ start: async (id, lang, _force, input) => response(id, lang, input, { status: 'generating', translations: [] }),
      get: async (id, lang) => response(id, lang, selection, change) })
    const state = await http.module.ensureOverlay(http.module.simulationOverlayFetcher('sim_A', selection), 'zh', { pollMs: 0 })
    assert.equal(state.status, 'error')
    assert.equal(state.translations, undefined)
  }
})

test('changing the parent language clears a child language override and cancels its request', async t => {
  const h = controller(t)
  h.state.toggle(); await settle()
  h.current.lang = 'zh'; await settle()
  h.state.toggle(); await settle()
  assert.equal(h.state.lang.value, 'en')
  h.current.lang = 'en'; await settle()
  h.current.lang = 'zh'; await settle()
  assert.equal(h.state.lang.value, 'zh')
  assert.equal(h.state.status.value, 'available')
})

test('known failure and timeout are terminal, explicit and retryable; error start is not silently ignored', async () => {
  const m = loadOverlay()
  const failed = await m.ensureOverlay({ preferStart: true, start: async () => { throw new Error('native translation failed') } }, 'zh')
  assert.equal(failed.status, 'error'); assert.deepEqual(failed.issues, ['native translation failed'])
  const stale = await m.ensureOverlay({ get: async () => ({ data: { status: 'stale' } }), start: async () => ({ data: { status: 'failed', issues: ['audit failed'] } }) }, 'zh')
  assert.equal(stale.status, 'failed')
  const timeout = await m.ensureOverlay({ preferStart: true, start: async () => ({ data: { status: 'generating' } }) }, 'zh', { maxPolls: 0 })
  assert.equal(timeout.status, 'timeout'); assert.equal(timeout.retryable, true)
  const unknown = await m.ensureOverlay({ preferStart: true, start: async () => ({ data: { status: 'mystery' } }) }, 'zh')
  assert.equal(unknown.status, 'error')
  const prematureCancel = await m.ensureOverlay({ preferStart: true, start: async () => { throw Object.assign(new Error('transport cancelled'), { code: 'ERR_CANCELED' }) } }, 'zh')
  assert.equal(prematureCancel.status, 'error')
})

test('full period >1200 passages and a long persona are bounded across requests without dropping source text', async t => {
  const h = controller(t, { translate: source => source.replaceAll('Sentence', '句子').trim() })
  const long = 'Sentence with a source number 42. '.repeat(2000)
  h.current.texts = [...Array.from({ length: 1501 }, (_, i) => `Sentence ${i}.`), long]
  h.state.toggle(); await settle()
  assert.equal(h.state.status.value, 'available')
  assert.ok(h.calls.length >= 2)
  assert.ok(h.calls.every(call => call.options.texts.length <= 1000 && call.options.texts.join('').length <= 200000))
  assert.equal(h.state.display('Sentence 1500.'), '句子 1500.')
  assert.equal(h.state.display(long), long.replaceAll('Sentence', '句子'))
})

test('structured prose translates without changing numeric strings, IDs, URLs, units or reference lists', () => {
  const m = loadOverlay()
  const source = { actorId: 'actor_A', targetMetric: 'supply', amount: '12345678901234567890.1200',
    unit: 'USD_per_contract', description: 'The permit becomes active.', terms: { probability: 0.41, rationale: 'Demand remains stable.' },
    refs: ['[S1]', 'https://source.example/2026'], observedEvents: ['event_1'], dueAt: '2026-10-22T00:00:00Z' }
  const copy = JSON.stringify(source)
  assert.deepEqual(m.simulationProse(source), ['The permit becomes active.', 'Demand remains stable.'])
  const target = m.simulationDisplayValue(source, text => text === 'The permit becomes active.' ? '许可开始生效。' : text === 'Demand remains stable.' ? '需求保持稳定。' : text)
  assert.equal(target.actorId, 'actor_A'); assert.equal(target.targetMetric, 'supply')
  assert.equal(target['金额'], '12345678901234567890.1200'); assert.equal(target.unit, 'USD_per_contract')
  assert.equal(target['条款']['概率'], 0.41); assert.deepEqual(target.refs, source.refs)
  assert.equal(target['描述'], '许可开始生效。'); assert.equal(target['条款']['理由'], '需求保持稳定。')
  assert.equal(JSON.stringify(source), copy)
})

const buildLegacy = compileSfc(new URL('../src/components/research/SimulationView.vue', import.meta.url))
const buildPanel = compileSfc(new URL('../src/components/research/WorldStatePanel.vue', import.meta.url))
const buildWorld = compileSfc(new URL('../src/components/research/WorldSimulationView.vue', import.meta.url))
function mount(t, builder, { api = {}, props = {}, translate, start } = {}) {
  i18n.locale.value = 'en'
  const http = transport({ translate, start })
  const cleanups = []
  const component = builder({
    vue: { ...vue, onMounted: () => {}, onUnmounted: fn => cleanups.push(fn), useId: () => 'mandarin-simulation-test' },
    '../../i18n': i18n, '../../utils/overlayTranslation': http.module, '../../utils/worldSimulationView': world,
    '../../utils/worldState': worldState, '../../utils/feedRounds': feedRounds, '../../utils/simRecord': simRecord, '../../api/simulation': api,
    './WorldStatePanel.vue': { default: { props: ['language'], template: '<aside>{{ language }}</aside>' } },
    './WorldSimulationView.vue': { default: { props: ['language'], template: '<aside>{{ language }}</aside>' } },
    './SimulationRecordView.vue': { default: { props: ['record'], template: '<section class="record-child">{{ record.simulation_id }}</section>' } },
  })
  const reactiveProps = vue.reactive({ simulationId: 'sim_A', generationId: '', language: '', pollMs: 0, round: undefined, ...props })
  const scope = vue.effectScope()
  const state = scope.run(() => component.setup(reactiveProps, { expose() {}, emit() {} }))
  t.after(() => { cleanups.forEach(fn => fn()); scope.stop(); i18n.locale.value = 'en' })
  const render = () => renderToString(vue.createSSRApp({ ...component, setup: () => state }, reactiveProps))
  return { ...http, state, props: reactiveProps, render }
}

const LEGACY_TEXT = {
  'Policy analyst at ACME.': 'ACME 的政策分析师。', 'The tariff stays at 12%.': '关税维持在 12%。',
  'Capacity remains 40 MW.': '产能维持在 40 MW。', 'The permit is delayed.': '许可有所延迟。',
}
function legacyApi() {
  return {
    getSimulation: async id => ({ success: true, data: { simulation_id: id, simulation_engine: 'oasis-legacy' } }),
    getSimulationProfilesRealtime: async () => ({ data: { profiles: [{ user_id: 1, name: 'ACME', type: 'company', persona: 'Policy analyst at ACME.' }] } }),
    getSimulationPosts: async () => ({ data: { posts: [{ post_id: 21, user_id: 1, content: 'The tariff stays at 12%.', round: 2 }] } }),
    getSimulationComments: async () => ({ data: { comments: [{ comment_id: 31, post_id: 21, user_id: 1, content: 'Capacity remains 40 MW.' }] } }),
    getAgentStats: async () => ({ data: { total_posts: 1234 } }),
    getRunStatus: async () => ({ data: { runner_status: 'completed', current_round: 2, total_rounds: 2 } }),
    getFeedRounds: async () => ({ data: { rounds: [{ round: 2, period_label: '2026-10' }] } }),
    fetchRecord: async () => ({ record: null, status: 409, publicationStatus: 'failed' }),
  }
}

test('actual legacy template translates personas, posts, replies, status and all headers with global locale still English', async t => {
  const h = mount(t, buildLegacy, { api: legacyApi(), translate: source => LEGACY_TEXT[source] || source })
  await settle()
  assert.match(prose(await h.render()), /Crowd Simulation/)
  h.state.translation.toggle(); await settle()
  const html = await h.render(), text = prose(html)
  assert.equal(i18n.locale.value, 'en')
  for (const expected of ['群体模拟', '数字人设', '信息流', 'ACME 的政策分析师。', '关税维持在 12%。', '产能维持在 40 MW。', '企业', '已完成', '1,234']) assert.ok(text.includes(expected), expected)
  assert.ok(!text.includes('The tariff stays'))
  assert.match(html, /<aside[^>]*>zh<\/aside>/)
  assert.ok(h.calls[0].options.texts.includes('Capacity remains 40 MW.'))
  h.state.selectedRound.value = 2; await h.state.loadAll(); await settle()
  assert.equal(h.calls.at(-1).options.context.round, 2)
  assert.match(prose(await h.render()), /2026-10/)
})

test('completed record and live controls coexist without resetting the selected simulation language', async t => {
  const record = JSON.parse(readFileSync(new URL('./fixtures/sim/simulation_record.en.json', import.meta.url), 'utf8'))
  const h = mount(t, buildLegacy, { api: { ...legacyApi(), fetchRecord: async () => ({ record, status: 200, publicationStatus: 'passed' }) },
    translate: source => LEGACY_TEXT[source] || source })
  await settle()
  assert.match(await h.render(), /class="record-child"/)
  h.state.translation.toggle(); await settle()
  assert.match(prose(await h.render()), /记录 实时视图/)
  h.state.showRecord.value = false
  const html = await h.render()
  assert.doesNotMatch(html, /class="record-child"/)
  assert.match(prose(html), /关税维持在 12%/)
  assert.match(html, /<aside[^>]*>zh<\/aside>/)
  h.state.showRecord.value = true
  assert.match(await h.render(), /class="record-child"/)
  assert.equal(h.state.translation.lang.value, 'zh')
})

test('world record fallback and record-to-live switching both pass the selected language to the world view', async t => {
  const record = JSON.parse(readFileSync(new URL('./fixtures/sim/simulation_record.en.json', import.meta.url), 'utf8'))
  let published = false
  const h = mount(t, buildLegacy, { api: { ...legacyApi(),
    getSimulation: async id => ({ success: true, data: { simulation_id: id, simulation_engine: 'world-v1', world_generation_id: 'gen_A', status: 'completed' } }),
    fetchRecord: async () => published ? { record, status: 200, publicationStatus: 'passed' } : { record: null, status: 409, publicationStatus: 'failed' },
  } })
  await settle()
  i18n.locale.value = 'zh'; await settle()
  assert.match(await h.render(), /<aside[^>]*>zh<\/aside>/)
  published = true
  await h.state.retryRecord()
  assert.match(await h.render(), /class="record-child"/)
  h.state.showRecord.value = false
  assert.match(await h.render(), /<aside[^>]*>zh<\/aside>/)
})

function panelPayload() {
  return { committed_round: 2, period: { label: '2026-10' }, headline: '2026-10: 2 decisions · 1 facts changed · 1 events · arbiter=applied',
    history: [1, 2].map(round => ({ round, period_label: `2026-0${round}`, headline: `Period ${round} headline.`, narrative: round === 1 ? 'The permit is delayed.' : 'The tariff stays at 12%.', digest: `Digest ${round}.`, arbiter_status: 'applied', decisions: { total: 2, ok: 2 },
      deterministic: { actions: ['The permit is delayed.'], effects_fired: ['Capacity remains 40 MW.'] },
      diff: { variables_changed: [{ id: 'rate', name: 'Tariff rate', from: 10, to: 12, unit: '%' }], relationships_changed: [{ source: 'ACME', target: 'BETA', to: 'neutral', direction: 'closer' }] } })),
    variables: [{ id: 'rate', name: 'Tariff rate', value: 12, unit: '%', provenance: 'arbiter' }],
    actors: [{ name: 'ACME', agent_id: 1, pending_commitments: [{ description: 'Deliver the equipment.', due_round: 3 }] }],
    pending_effects: [{ description: 'Demand remains stable.', due_round: 3 }],
    recent_events: [{ round: 2, kind: 'action', actors: ['ACME'], description: 'Deliver the equipment.', statement: 'The tariff stays at 12%.' }, { round: 2, kind: 'emergent', description: 'The permit is delayed.' }],
    interactions: [{ id: 'i_1', status: 'open', proposer: 'ACME', recipient: 'BETA', terms: 'Deliver 40 MW before the deadline.' }],
    seed_gaps: [{ kind: 'missing_evidence', subject: 'ACME', note: 'No official data was available.' }],
  }
}
const PANEL_TEXT = { ...LEGACY_TEXT, 'Tariff rate': '关税税率', 'Deliver the equipment.': '交付设备。',
  'Demand remains stable.': '需求保持稳定。', 'Deliver 40 MW before the deadline.': '在截止日期前交付 40 MW。',
  'No official data was available.': '没有可用的官方数据。', 'missing_evidence': '证据缺失',
  'Digest 1.': '第 1 期摘要。', 'Digest 2.': '第 2 期摘要。', 'Period 1 headline.': '第 1 期标题。', 'Period 2 headline.': '第 2 期标题。',
  '2026-10: 2 decisions · 1 facts changed · 1 events · arbiter=applied': '2026-10：2 项决策 · 1 项事实变化 · 1 个事件 · 仲裁已应用' }

test('actual world-state template translates all cards, selected-period digest, timeline tooltip and modelling gaps', async t => {
  const source = panelPayload(), before = JSON.stringify(source)
  const h = mount(t, buildPanel, { api: { getWorldState: async () => ({ data: source }) }, translate: text => PANEL_TEXT[text] || text })
  await h.state.load(); h.state.translation.toggle(); await settle()
  const html = await h.render(), text = prose(html)
  for (const expected of ['世界状态', '关税税率', '12%', '交付设备。', '关税维持在 12%。', '许可有所延迟。', '需求保持稳定。', '在截止日期前交付 40 MW。', '待回应', '中立', '趋近']) assert.ok(text.includes(expected), expected)
  assert.ok(html.includes('没有可用的官方数据。'))
  assert.ok(html.includes('第 1 期标题。'))
  assert.ok(!html.includes('facts changed'))
  assert.ok(!html.includes('Deliver the equipment.'))
  assert.equal(JSON.stringify(source), before)
  h.state.selectRound(1); await settle()
  const past = prose(await h.render())
  assert.match(past, /历史时段/); assert.match(past, /许可有所延迟。/); assert.match(past, /第 1 期摘要。/)
  assert.match(past, /10% → 12%/)
  assert.equal(h.calls.at(-1).options.context.round, 1)
})

function worldPayload(request) {
  const visible = { kind: 'public' }, basis = { kind: 'scenario_assumption', refs: ['S1'] }
  const record = extra => ({ visibility: visible, basis, ...extra })
  const data = { schemaVersion: 'world-result/v1', engine: 'world-v1', simulationId: 'sim_A', generationId: 'gen_A', revision: 'r2', selectedRevision: `r${request.round ?? 2}`,
    round: request.round ?? 2, committedRound: 2, totalRounds: 3, completed: false, view: request.view, actorId: request.actorId || null,
    world: { round: request.round ?? 2, simulatedAt: '2026-10-22T00:00:00Z',
      metrics: { supply: record({ label: 'Available capacity', description: 'Capacity remains 40 MW.', value: '12345678901234567890.1200', unit: 'MW', valueStatus: 'simulated' }),
        secret: record({ label: 'Private field only', value: '999', visibility: { kind: 'actors', actorIds: ['actor_A'] } }) },
      accounts: {}, rules: {}, relations: {},
      commitments: { c1: record({ templateId: 'delivery', participantIds: ['actor_A'], dueAt: '2026-11-01T00:00:00Z', status: 'pending', transfers: [{ description: 'Deliver the equipment.', amount: '40.00', unit: 'MW' }], effects: [{ explanation: 'The permit is delayed.', probability: 0.41 }] }) },
      interactions: { offer1: record({ templateId: 'contract', proposerId: 'actor_A', recipientIds: ['actor_B'], termsVersion: 3, terms: { description: 'Deliver 40 MW before the deadline.' }, status: 'pending' }) },
    }, events: [record({ eventId: 'e1', kind: 'investment', description: 'Demand remains stable.', round: 2, actorId: 'actor_A', at: '2026-10-22T00:00:00Z', details: { explanation: 'The permit is delayed.', commitmentId: 'c1' } })],
    assumptions: [record({ assumptionId: 'a1', label: 'Demand assumption', description: 'Demand remains stable.' })], decisions: [], resolutions: [],
  }
  if (request.view !== 'public') {
    data.decisions = [{ actorId: 'actor_A', decisionId: 'd1', observationId: 'o1', status: 'acted', round: 2, rationale: 'The tariff stays at 12%.', intents: [{ intentId: 'i1', templateId: 'supply_contract', operation: 'execute', parameters: { explanation: 'Deliver the equipment.', cost: '4.5000', actorId: 'actor_B' } }] }]
    data.resolutions = [{ actorId: 'actor_A', intentId: 'i1', accepted: false, explanation: 'The permit is delayed.' }]
    data.world[request.view === 'analyst' ? 'actorStates' : 'actorState'] = request.view === 'analyst' ? { actor_A: { beliefs: ['Demand remains stable.'], plans: ['Deliver the equipment.'], observedEvents: ['e1'] } } : { beliefs: ['Demand remains stable.'], plans: ['Deliver the equipment.'], observedEvents: ['e1'] }
  }
  return { success: true, data }
}

test('actual world-v1 template translates state, decisions, outcomes, commitments, parameters and assumptions while preserving visibility and values', async t => {
  const h = mount(t, buildWorld, { api: { getWorldSimulation: async (_id, request) => worldPayload(request) },
    translate: source => ({ ...PANEL_TEXT, 'Available capacity': '可用产能', 'Demand assumption': '需求假设' }[source] || source) })
  await settle(); h.state.translation.toggle(); await settle()
  let html = await h.render(), text = prose(html)
  for (const expected of ['世界模拟', '可用产能', '产能维持在 40 MW。', '需求保持稳定。', '在截止日期前交付 40 MW。', '12345678901234567890.1200', '40.00', '0.41', '需求假设']) assert.ok(text.includes(expected), expected)
  assert.ok(!html.includes('Private field only'))
  assert.ok(!h.calls.flatMap(call => call.options.texts || []).includes('Private field only'))
  h.state.view.value = 'analyst'; await settle()
  html = await h.render(); text = prose(html)
  for (const expected of ['私有建模状态', '建模信念', '建模计划', '交付设备。', '关税维持在 12%。', '许可有所延迟。', 'actor_A', 'actor_B', 'supply_contract', '4.5000', 'S1', 'e1']) assert.ok(text.includes(expected), expected)
  assert.equal(h.calls.at(-1).options.context.view, 'analyst')
  h.state.view.value = 'public'; await settle()
  assert.ok(!h.calls.at(-1).options.texts.includes('Private field only'))
  assert.ok(!prose(await h.render()).includes('建模信念'))
})

test('actual failure UI keeps source visible and offers a real force retry without locking the language toggle', async t => {
  let failed = true
  const h = mount(t, buildLegacy, { api: legacyApi(), start: async (id, lang, force, options) => {
    if (force) failed = false
    return response(id, lang, options, failed ? { status: 'failed', issues: ['translation integrity failed'], translations: [], pending: options.texts.length } : {
      translations: options.texts.map(source => ({ source, text: LEGACY_TEXT[source] || source, source_sha256: sha(source) })),
    })
  } })
  await settle(); h.state.translation.toggle(); await settle()
  const failedHtml = await h.render()
  assert.match(prose(failedHtml), /重试翻译/); assert.match(prose(failedHtml), /The tariff stays at 12%/)
  assert.match(failedHtml, /role="status" aria-live="polite"/)
  await h.state.translation.retry()
  assert.match(prose(await h.render()), /关税维持在 12%。/)
  assert.equal(h.calls.at(-1).force, true)
  h.state.translation.toggle(); await settle()
  assert.match(prose(await h.render()), /Crowd Simulation/)
})
