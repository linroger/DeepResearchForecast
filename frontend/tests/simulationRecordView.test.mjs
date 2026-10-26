import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'

import * as i18n from '../src/i18n.js'
import * as simRecord from '../src/utils/simRecord.js'
import * as recordTranslation from '../src/utils/simulationRecordTranslation.js'
import * as world from '../src/utils/worldSimulationView.js'
import * as feedRounds from '../src/utils/feedRounds.js'
import { compileSfc } from './sfcHarness.mjs'
const translationHarness = new URL('./simulationTranslationHarness.mjs', import.meta.url)
const overlay = existsSync(translationHarness) ? (await import(translationHarness.href)).overlay : {}

// T12 (ADR 0003, design §6): the real SimulationRecordView.vue renders a gate-passed
// simulation-record/v1 through Vue's server renderer — the banner verbatim, the health line,
// one button per committed period, the selected period's account and the overall section
// whose shares are never called probabilities — and SimulationView.vue makes that record the
// default view after completion while keeping today's layout when /record answers 404/409.
// Fixtures: tests/fixtures/sim (README there).
const fixture = name => JSON.parse(readFileSync(new URL(`./fixtures/sim/${name}`, import.meta.url), 'utf8'))
const RECORD_EN = fixture('simulation_record.en.json')
const RECORD_ZH = fixture('simulation_record.zh.json')
const HOLLOW = fixture('simulation_record.hollow.json')
const PATHS = fixture('simulation_record.paths.json')

const buildRecordView = compileSfc(new URL('../src/components/research/SimulationRecordView.vue', import.meta.url))
const buildSimulationView = compileSfc(new URL('../src/components/research/SimulationView.vue', import.meta.url))

const strip = html => html.replace(/<!--[^]*?-->/g, '')
// the markup people get, as text: tags removed, the renderer's entities (&#39; &quot; &amp;) decoded
const decode = s => s.replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
const text = html => decode(strip(html).replace(/<[^>]+>/g, ' ')).replace(/\s+/g, ' ').trim()
const count = (html, needle) => html.split(needle).length - 1
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise(resolve => setImmediate(resolve)) }

// The reader-facing strings are pinned to backend/app/services/sim_provenance.py (T9 reads the
// Vue files from Python; this is the mirror image).
const PROVENANCE = readFileSync(new URL('../../backend/app/services/sim_provenance.py', import.meta.url), 'utf8')
function pyConst(name) {
  const m = PROVENANCE.match(new RegExp(`^${name}: Final = (\\([^]*?\\)|"[^"\\n]*")`, 'm'))
  assert.ok(m, `${name} not found in sim_provenance.py`)
  return [...m[1].matchAll(/"((?:[^"\\]|\\.)*)"/g)].map(x => x[1]).join('')
}
const SIM_BANNER_EN = pyConst('SIM_BANNER_EN')
const SIM_BANNER_ZH = pyConst('SIM_BANNER_ZH')
const SIM_CAVEAT_EN = pyConst('SIM_CAVEAT_EN')
const SIM_CAVEAT_ZH = pyConst('SIM_CAVEAT_ZH')
const NO_PROBABILITY_LABEL_EN = 'simulated share, not a probability'
const NO_PROBABILITY_LABEL_ZH = '模拟份额，非概率'

// ---------- SimulationRecordView ----------
function mountRecord(t, record, lang = 'en') {
  i18n.locale.value = lang
  const component = buildRecordView({ vue, '../../i18n': i18n, '../../utils/simRecord': simRecord,
    '../../utils/overlayTranslation': overlay, '../../utils/simulationRecordTranslation': recordTranslation })
  const props = vue.reactive({ record })
  const scope = vue.effectScope()
  const state = scope.run(() => component.setup(props, { expose() {}, emit() {}, attrs: {}, slots: {} }))
  t.after(() => { scope.stop(); i18n.locale.value = 'en' })
  const host = { setup: () => state, render: component.render }
  async function render() {
    const html = strip(await renderToString(vue.createSSRApp(host)))
    return {
      html,
      text: text(html),
      ticks: [...html.matchAll(/<button[^>]*class="rec-tick[^"]*"[^>]*>[^<]*<\/button>/g)].map(m => m[0]),
    }
  }
  return { state, props, render }
}

// The shares card (head + table) in isolation: it must call shares "share", never probability.
function sharesText(html) {
  const head = html.match(/<div class="rec-card-head rec-shares-head">[^]*?<\/div>/)
  const table = html.match(/<table class="rec-table rec-shares-table">[^]*?<\/table>/)
  assert.ok(head && table, 'shares head and table are rendered')
  return text(head[0] + table[0])
}
const pressed = tick => /aria-pressed="true"/.test(tick)

test('the fixture banners are byte-equal to the sim_provenance constants', () => {
  assert.equal(RECORD_EN.banner, SIM_BANNER_EN)
  assert.equal(HOLLOW.banner, SIM_BANNER_EN)
  assert.equal(PATHS.banner, SIM_BANNER_EN)
  assert.equal(RECORD_ZH.banner, SIM_BANNER_ZH)
  assert.equal(RECORD_EN.record_class, 'simulated')
  assert.equal(RECORD_EN.periods.length, RECORD_EN.rounds_committed)
  // the compiler's allowlist kept private_rationale out of the fixture
  assert.doesNotMatch(JSON.stringify(RECORD_EN), /private_rationale/)
})

test('EN record: banner verbatim, health line, one button per period, the first period opens', async t => {
  const h = mountRecord(t, RECORD_EN)
  const r = await h.render()
  // header card
  assert.ok(r.text.includes(SIM_BANNER_EN), 'banner verbatim')
  assert.match(r.text, /Scenario simulation · after-action record simulated record, not evidence/)
  assert.match(r.text, /engine oasis-reflexive horizon 2026-10-22 → 2026-10-31 · day periods 3 of 3 periods committed language en/)
  assert.match(r.text, /health ok · validity valid · 0 arbiter-failed rounds · 10 seed gaps · 629 organic actions/)
  assert.equal(count(r.html, 'class="rec-unusable"'), 0)
  // period strip
  assert.equal(r.ticks.length, 3)
  assert.deepEqual(r.ticks.map(pressed), [true, false, false])
  assert.deepEqual(r.ticks.map(tick => tick.match(/>([^<]*)</)[1]), ['2026-10-23', '2026-10-24', '2026-10-25'])
  assert.match(r.ticks[0], /class="rec-tick mono st-applied selected"/)
  assert.match(r.ticks[0], /aria-label="2026-10-23, arbiter applied, 2 facts changed"/)
  assert.ok(r.html.includes('role="group"') && r.html.includes('aria-label="Select a period"'))
  // the selected period: labelled arbiter narrative, moves with public statements, facts with unit and cause
  const first = RECORD_EN.periods[0]
  assert.match(r.text, /Period 1 · 2026-10-23 2026-10-23 → 2026-10-23 arbiter: applied/)
  assert.doesNotMatch(r.text, /mechanical only/)
  assert.match(r.text, /Arbiter narrative \(simulated text\)/)
  assert.ok(r.text.includes(first.narrative), 'narrative verbatim')
  assert.match(r.text, new RegExp(`Moves this period \\(${first.moves.length}\\) Government of Iran Advance your documented plan`))
  assert.ok(r.text.includes(first.moves[0].public_statement), 'public statement shown')
  assert.match(r.text, /commitment: Iran will reopen the Strait of Hormuz within seven days of verified US relief measures commencing/)
  assert.match(r.text, /Facts changed this period \(2\) Variable Change Cause Drone launch tempo 337 count → 319 count Slight dip as Russia avoids overt escalation/)
  assert.match(r.text, /TTF natural gas 86\.93 EUR\/MWh → 85\.43 EUR\/MWh Marginal easing on ceasefire-talks headlines/)
  assert.match(r.text, new RegExp(`Events, shocks and red lines \\(${first.events.length}\\)`))
  assert.match(r.text, /Offers by status \(2\) open · 2 US Government → Government of Russia proposal US hosts trilateral talks/)
  assert.match(r.text, new RegExp(`${first.behaviour.moves} moves · ${first.behaviour.offers_answered} offers answered textual diagnostic, not a realism verdict`))
  // overall: final versus seed, shares as shares, turning points, track records, synthesis with its generator
  assert.match(r.text, /Overall: final state against the seed Final versus seed values \(4\) Variable Seed Final Drone launch tempo 337 count 320 count/)
  assert.match(r.text, /TTF CME Nov26 futures 88\.595 EUR\/MWh 88\.3 EUR\/MWh/)
  const shares = sharesText(r.html)
  assert.match(shares, /Simulated outcome shares simulated share, not a probability Scenario Final share Stalemate with fragile talks 50\.6% Ukraine ceasefire, Iran holds 24\.2%/)
  assert.doesNotMatch(shares, /Path mean|p10/)                                    // K = 1: no spread columns
  assert.doesNotMatch(shares.replace(NO_PROBABILITY_LABEL_EN, ''), /probabilit/i)
  assert.match(r.text, /not converged/)
  assert.match(r.text, /Turning points \(2\) period 2 offer countered: US Government → Government of Russia/)
  assert.match(r.text, /Track records \(1\) US Government kept 0/)
  assert.match(r.text, /Synthesis generated by: deterministic template/)
  assert.ok(r.text.includes(RECORD_EN.overall.synthesis.text.slice(0, 120)), 'synthesis text')
  assert.match(r.text, /Limits arbiter 0 arbiter-failed rounds gap actor_without_plans: US Government/)
  assert.match(r.text, /sim_fixture_record_en · simulation_record\/1\.0 · 2026-10-22T14:30:00Z/)
  // the word "probability" appears only in the banner and in the fixed "not a probability" label
  assert.doesNotMatch(r.text.replace(SIM_BANNER_EN, '').replace(NO_PROBABILITY_LABEL_EN, ''), /probabilit/i)
})

test('selecting a period shows that period; an unknown round falls back to the first', async t => {
  const h = mountRecord(t, RECORD_EN)
  h.state.selectPeriod(2)
  let r = await h.render()
  assert.deepEqual(r.ticks.map(pressed), [false, true, false])
  assert.match(r.text, /Period 2 · 2026-10-24/)
  assert.ok(r.text.includes(RECORD_EN.periods[1].narrative))
  assert.match(r.text, /arbiter problem: unknown relationship direction 'flat'/)
  assert.match(r.text, /Offers by status \(5\) countered · 2 .* open · 3/)
  assert.match(r.text, /Facts changed this period \(3\)/)
  h.state.selectPeriod(99)
  r = await h.render()
  assert.deepEqual(r.ticks.map(pressed), [true, false, false])
  h.state.selectPeriod(3)
  r = await h.render()
  assert.match(r.text, /Period 3 · 2026-10-25/)
  // the overall section does not move with the period
  assert.match(r.text, /Final versus seed values \(4\)/)
})

test('ZH record: the Chinese banner verbatim and Chinese labels; shares are 份额, never 概率', async t => {
  const h = mountRecord(t, RECORD_ZH, 'zh')
  const r = await h.render()
  assert.ok(r.text.includes(SIM_BANNER_ZH), 'ZH banner verbatim')
  assert.match(r.text, /情景模拟 · 事后记录 模拟记录，非证据/)
  assert.match(r.text, /健康 有效 · 有效性 valid · 仲裁失败 0 轮 · 建模缺口 10 项 · 自发行动 629 次/)
  assert.match(r.text, /已提交 3 \/ 计划 3 个时段/)
  assert.ok(r.html.includes('aria-label="选择时段"'))
  assert.equal(r.ticks.length, 3)
  assert.match(r.text, /第1期 · 2026-10-23/)
  assert.match(r.text, /仲裁叙事（模拟文本）/)
  assert.ok(r.text.includes(RECORD_ZH.periods[0].narrative))
  assert.match(r.text, /本时段行动 \(4\)/)
  assert.match(r.text, /本时段事实变化 \(2\) 变量 变化 原因/)
  assert.match(r.text, /要约（按状态） \(2\)/)
  const shares = sharesText(r.html)
  assert.match(shares, /模拟结果份额 模拟份额，非概率 情景 最终份额 Stalemate with fragile talks 50\.6%/)
  assert.doesNotMatch(shares.replace(NO_PROBABILITY_LABEL_ZH, ''), /概率|probabilit/i)
  assert.match(r.text, /综合 生成方式: 确定性模板/)
  assert.match(r.text, /文本层面的诊断，非真实性判定/)
  assert.doesNotMatch(r.text.replace(SIM_BANNER_ZH, '').replace(NO_PROBABILITY_LABEL_ZH, ''), /概率/)
})

test('a hollow record shows the health table and says the exercise was not usable', async t => {
  const h = mountRecord(t, HOLLOW)
  const r = await h.render()
  assert.ok(r.text.includes(SIM_BANNER_EN))
  assert.equal(count(r.html, 'class="rec-unusable"'), 1)
  assert.match(r.html, /role="alert"/)
  assert.match(r.text, /This exercise was not usable \(status: hollow\)\. The record carries the health table only; no narrative was generated and there is no period account to read\./)
  assert.match(r.text, /simulation health hollow validity valid arbiter-failed rounds 0 seed gaps 10 organic actions 0 periods committed \/ planned 0 \/ 9/)
  assert.match(r.text, /health hollow · validity valid/)
  assert.equal(r.ticks.length, 0)
  assert.doesNotMatch(r.text, /Arbiter narrative|Simulated outcome shares|Synthesis/)
  // a truncated run and an invalid decision channel are stubs too
  for (const [key, value] of [['simulation_health', 'truncated'], ['simulation_health', 'errored'], ['validity', 'invalid']]) {
    const stub = JSON.parse(JSON.stringify(RECORD_EN))
    stub.health[key] = value
    assert.equal(simRecord.isUnusableRecord(stub), true, `${key}=${value}`)
  }
  assert.equal(simRecord.isUnusableRecord(RECORD_EN), false)
})

test('K > 1 paths, red lines, shocks, alliances and a mechanical-only round reach the reader', async t => {
  const h = mountRecord(t, PATHS)
  let r = await h.render()
  assert.match(r.text, /health ok · validity valid · 1 arbiter-failed rounds · 1 seed gaps · 40 organic actions/)
  assert.equal(r.ticks.length, 2)
  assert.match(r.ticks[1], /class="rec-tick mono st-failed"/)
  assert.match(r.ticks[0], /aria-label="2026-W45, arbiter applied, 1 facts changed, 1 red lines crossed"/)
  assert.match(r.text, /Events, shocks and red lines \(3\) red line crossed Actor B crossed Actor A's red line: No tariff above 100% shock Port closure event Shipping insurers repriced the route/)
  assert.match(r.html, /<li class="rec-event ev-red-line"><span class="rec-kind mono">red line crossed<\/span>/)
  assert.match(r.text, /Offers by status \(1\) accepted · 1 Actor A → Actor B talks Talks within two weeks/)
  assert.match(r.text, /Alliance shifts \(1\) alliance Actor A and Actor C aligned on the counter-offer/)
  assert.match(r.text, /held Actor C/)
  assert.match(r.text, /Tariff rate 10% → 145% Actor B's tariff order took effect/)
  assert.match(r.text, /commitment: Keep the tariff until talks resume · due 2026-W47/)
  assert.match(r.text, /2 moves · 1 responsive · 1 offers answered textual diagnostic, not a realism verdict/)
  const shares = sharesText(r.html)
  assert.match(shares, /Scenario Final share Path mean p10 – p90 Escalation 56% 58% ± 5% 51% – 64% Truce holds 44% 42% ± 5% 36% – 49%/)
  assert.doesNotMatch(shares.replace(NO_PROBABILITY_LABEL_EN, ''), /probabilit/i)
  assert.match(r.text, /paths K=4 · converged at period 2/)
  assert.match(r.text, /Turning points \(1\) period 1 red line crossed: No tariff above 100%/)
  // breakers first; counts, never a score
  assert.match(r.text, /Track records \(2\) Actor B kept 0 · lapsed 1 · broken 1 Actor A kept 2/)
  assert.match(r.html, /<li class="rec-record tr-broken"><span class="rec-actor">Actor B<\/span>/)
  assert.match(r.text, /Synthesis generated by: bounded LLM synthesis \(gate-checked\) The exercise turned on one crossing in the first week\. The second week added nothing/)
  assert.equal(count(r.html, 'class="rec-synthesis-text"'), 2)
  // the arbiter-failed round is marked mechanical only, with its problem and no narrative
  h.state.selectPeriod(2)
  r = await h.render()
  assert.match(r.text, /Period 2 · 2026-W46 2026-11-08 → 2026-11-14 arbiter: failed mechanical only ▲ arbiter problem: llm error: BadRequestError/)
  assert.match(r.text, /No arbiter narrative for this period/)
  assert.match(r.text, /No consequential move this period/)
  assert.doesNotMatch(r.text.replace(SIM_BANNER_EN, '').replace(NO_PROBABILITY_LABEL_EN, ''), /probabilit/i)
})

test('a malformed or absent record renders nothing', async t => {
  for (const bad of [null, {}, { schema: 'simulation-record/v1' }, { ...RECORD_EN, record_class: 'observed' }]) {
    const h = mountRecord(t, bad)
    const r = await h.render()
    assert.equal(r.text, '', JSON.stringify(bad).slice(0, 40))
  }
})

test('the pure helpers tolerate missing fields and keep shares as shares', () => {
  assert.equal(simRecord.isSimulationRecord(RECORD_EN), true)
  assert.equal(simRecord.isSimulationRecord({ ...RECORD_EN, periods: 'no' }), false)
  assert.deepEqual(simRecord.recordPeriods({ periods: [{ round: 2 }, { round: 1, label: 'first' }] }).map(p => [p.round, p.label, p.arbiterStatus, p.mechanicalOnly]),
    [[1, 'first', 'none', true], [2, '#2', 'none', true]])
  assert.equal(simRecord.formatShare(0.5063), '50.6%')
  assert.equal(simRecord.formatShare('0.25'), '25%')
  assert.equal(simRecord.formatShare(null), '—')
  assert.equal(simRecord.formatQuantity(85.43, 'EUR/MWh'), '85.43 EUR/MWh')
  assert.equal(simRecord.formatQuantity(12, '%'), '12%')
  assert.equal(simRecord.formatQuantity(true, 'x'), 'true')
  assert.equal(simRecord.formatQuantity(undefined), '—')
  assert.deepEqual(simRecord.offersByStatus([{ status: 'lapsed' }, { status: 'accepted', from: 'A', to: 'B' }, { status: 'zzz' }]).map(g => g.status), ['accepted', 'lapsed', 'zzz'])
  const shares = simRecord.shareRows(PATHS)
  assert.deepEqual(shares.rows.map(r => r.name), ['Escalation', 'Truce holds'])
  assert.equal(shares.hasPaths, true)
  assert.equal(simRecord.shareRows(RECORD_EN).hasPaths, false)
  assert.equal(simRecord.shareRows({}).rows.length, 0)
  assert.equal(simRecord.shortSha('a'.repeat(64)), 'aaaaaaaa…aaaa')
  assert.equal(simRecord.behaviourSummary(null, {}), '')
})

test('the fixed caveat and label strings in SimulationView match sim_provenance', () => {
  const simView = readFileSync(new URL('../src/components/research/SimulationView.vue', import.meta.url), 'utf8')
  assert.ok(simView.includes(`L('${SIM_CAVEAT_ZH}', '${SIM_CAVEAT_EN}')`), 'legacy header caveat drifted from SIM_CAVEAT_*')
  const label = pyConst('SIM_LABEL_EN')
  const title = label.charAt(0).toUpperCase() + label.slice(1)
  assert.ok(simView.includes(`L('${pyConst('SIM_LABEL_ZH')}', '${title}')`), 'record shell title drifted from SIM_LABEL_*')
})

// ---------- SimulationView: the record is the default view after completion ----------
function mountSimulationView(t, { api = {}, lang = 'en', stageStatus = '', openRecordRequest = 0 } = {}) {
  i18n.locale.value = lang
  const calls = []
  const emitted = []
  const cleanups = []
  const timers = []
  const defaults = {
    getSimulation: async id => ({ success: true, data: { simulation_id: id, simulation_engine: 'oasis-legacy' } }),
    getSimulationProfilesRealtime: async () => ({ success: true, data: { profiles: [{ user_id: 1, name: 'Alice' }] } }),
    getSimulationPosts: async () => ({ success: true, data: { posts: [{ post_id: 1, user_id: 1, content: 'Legacy social post' }] } }),
    getSimulationComments: async () => ({ success: true, data: { comments: [] } }),
    getAgentStats: async () => ({ success: true, data: { total_posts: 1 } }),
    getRunStatus: async () => ({ success: true, data: { simulation_engine: 'oasis-legacy', runner_status: 'completed', current_round: 3, total_rounds: 3 } }),
    getFeedRounds: async () => ({ success: true, data: { rounds: [] } }),
    fetchRecord: async () => ({ record: RECORD_EN, status: 200, publicationStatus: 'passed' }),
  }
  const actual = Object.fromEntries(Object.entries({ ...defaults, ...api }).map(([key, fn]) => [key, (...args) => { calls.push(key); return fn(...args) }]))
  // timers never fire: the test only observes what the view schedules (live refresh / record retry)
  t.mock.method(globalThis, 'setTimeout', (fn, ms) => { timers.push(ms); return timers.length })
  t.mock.method(globalThis, 'clearTimeout', () => {})
  const imports = {
    vue: { ...vue, onUnmounted: fn => cleanups.push(fn) },
    '../../i18n': i18n,
    '../../api/simulation': actual,
    '../../utils/overlayTranslation': overlay,
    '../../utils/worldSimulationView': world,
    '../../utils/feedRounds': feedRounds,
    '../../utils/simRecord': simRecord,
    './WorldSimulationView.vue': { default: { props: ['simulationId', 'generationId'], template: '<div class="world-child" />' } },
    './WorldStatePanel.vue': { default: { props: ['simulationId', 'refreshToken', 'round'], emits: ['update:selectedRound'], template: '<div class="world-state-panel" />' } },
    './SimulationRecordView.vue': { default: { props: ['record'], template: '<div class="sim-record-view">{{ record && record.simulation_id }}</div>' } },
  }
  const component = buildSimulationView(imports)
  const props = vue.reactive({ simulationId: 'sim_1', stageStatus, openRecordRequest })
  const scope = vue.effectScope()
  const state = scope.run(() => component.setup(props, {
    expose() {}, emit: (name, payload) => emitted.push([name, payload]), attrs: {}, slots: {},
  }))
  t.after(() => { cleanups.forEach(fn => fn()); scope.stop(); i18n.locale.value = 'en' })
  async function render() {
    const html = strip(await renderToString(vue.createSSRApp({ ...component, setup: () => state }, props)))
    return { html, text: text(html) }
  }
  return { state, props, calls, emitted, timers, render }
}

test('a completed legacy run with a gate-passed record opens on the Record view, one toggle from the live layout', async t => {
  const h = mountSimulationView(t)
  await settle()
  assert.equal(h.state.engine.value, 'oasis-legacy')
  assert.equal(h.state.record.value && h.state.record.value.simulation_id, 'sim_fixture_record_en')
  assert.equal(h.state.showRecord.value, true)
  assert.equal(h.calls.filter(key => key === 'fetchRecord').length, 1)
  assert.deepEqual(h.emitted.at(-1), ['record-state', { available: true, status: 200 }])
  assert.deepEqual(h.timers, [], 'no refresh or retry timer once the record is in')
  let r = await h.render()
  assert.match(r.text, /Crowd Simulation · OASIS/)
  assert.ok(r.text.includes(SIM_CAVEAT_EN), 'legacy header carries the fixed caveat')
  assert.equal(count(r.html, 'class="sim-record-view"'), 1)
  assert.match(r.text, /sim_fixture_record_en/)
  assert.match(r.html, /<button[^>]*class="seg-btn active"[^>]*aria-pressed="true"[^>]*>Record<\/button>/)
  assert.match(r.html, /<button[^>]*class="seg-btn"[^>]*aria-pressed="false"[^>]*>Live view<\/button>/)
  assert.equal(count(r.html, 'class="world-state-panel"'), 0)
  assert.doesNotMatch(r.text, /Alice|Legacy social post/)
  // the live view is one click away and shows today's layout
  h.state.showRecord.value = false
  r = await h.render()
  assert.equal(count(r.html, 'class="sim-record-view"'), 0)
  assert.equal(count(r.html, 'class="world-state-panel"'), 1)
  assert.match(r.text, /Alice/)
  assert.match(r.text, /Legacy social post/)
  assert.match(r.html, /aria-pressed="true"[^>]*>Live view<\/button>/)
})

test('without a record (404) today\'s layout stands, the caveat is still shown and the record is re-asked a bounded number of times', async t => {
  const h = mountSimulationView(t, { api: { fetchRecord: async () => ({ record: null, status: 404, publicationStatus: 'absent' }) } })
  await settle()
  assert.equal(h.state.record.value, null)
  assert.deepEqual(h.emitted.at(-1), ['record-state', { available: false, status: 404 }])
  const r = await h.render()
  assert.equal(count(r.html, 'class="sim-record-view"'), 0)
  assert.equal(count(r.html, 'class="world-state-panel"'), 1)
  assert.match(r.text, /Alice/)
  assert.ok(r.text.includes(SIM_CAVEAT_EN))
  assert.doesNotMatch(r.html, /Live view|>Record</)
  // Stage 5 writes the record shortly after the runner reports completion: four 15 s retries, then stop
  assert.deepEqual(h.timers, [15000])
  for (let i = 0; i < 4; i++) await h.state.loadAll()
  assert.deepEqual(h.timers, [15000, 15000, 15000, 15000])
  assert.equal(h.calls.filter(key => key === 'fetchRecord').length, 5)
})

test('a record that failed its gate (409) is not shown and not retried; a transport failure is not an error either', async t => {
  const gated = mountSimulationView(t, { api: { fetchRecord: async () => ({ record: null, status: 409, publicationStatus: 'failed' }) } })
  await settle()
  assert.equal(gated.state.record.value, null)
  assert.deepEqual(gated.timers, [])
  assert.deepEqual(gated.emitted.at(-1), ['record-state', { available: false, status: 409 }])
  assert.equal(count((await gated.render()).html, 'class="world-state-panel"'), 1)
  const broken = mountSimulationView(t, { api: { fetchRecord: async () => { throw new Error('network down') } } })
  await settle()
  assert.equal(broken.state.record.value, null)
  assert.equal(broken.state.error.value, '')
  assert.equal(count((await broken.render()).html, 'class="world-state-panel"'), 1)
  // a transport failure with nothing shown yet re-arms the same bounded retry as a 404 (S2 review)
  assert.deepEqual(broken.timers, [15000])
  // ... and a transport failure never drops a record that is already shown
  let serveRecord = true
  const flaky = mountSimulationView(t, { api: { fetchRecord: async () => {
    if (serveRecord) return { record: RECORD_EN, status: 200, publicationStatus: 'passed' }
    throw new Error('network down')
  } } })
  await settle()
  assert.ok(flaky.state.record.value)
  serveRecord = false
  await flaky.state.loadAll()
  assert.ok(flaky.state.record.value, 'a shown record survives a transport failure')
  // a record with the wrong shape is ignored
  const odd = mountSimulationView(t, { api: { fetchRecord: async () => ({ record: { schema: 'other' }, status: 200 }) } })
  await settle()
  assert.equal(odd.state.record.value, null)
})

test('while the run is in progress the record is not asked for and the live refresh keeps its cadence', async t => {
  const h = mountSimulationView(t, { api: {
    getRunStatus: async () => ({ success: true, data: { simulation_engine: 'oasis-legacy', runner_status: 'running', current_round: 1, total_rounds: 3 } }),
  } })
  await settle()
  assert.equal(h.calls.filter(key => key === 'fetchRecord').length, 0)
  assert.equal(h.state.record.value, null)
  assert.deepEqual(h.timers, [10000])
  const r = await h.render()
  assert.equal(count(r.html, 'class="world-state-panel"'), 1)
  assert.doesNotMatch(r.html, /sim-record-view|Live view/)
})

test('a world-v1 run with a record shows the Record view above a toggle back to the world view', async t => {
  const h = mountSimulationView(t, { api: {
    getSimulation: async id => ({ success: true, data: { simulation_id: id, simulation_engine: 'world-v1', world_generation_id: 'gen_1' } }),
  } })
  await settle()
  assert.equal(h.state.engine.value, 'world-v1')
  assert.deepEqual(h.calls, ['getSimulation', 'fetchRecord'])
  let r = await h.render()
  assert.equal(count(r.html, 'class="sim-record-view"'), 1)
  assert.equal(count(r.html, 'class="world-child"'), 0)
  assert.match(r.text, /Scenario simulation world-v1/)
  assert.ok(r.text.includes(SIM_CAVEAT_EN))
  h.state.showRecord.value = false
  r = await h.render()
  assert.equal(count(r.html, 'class="sim-record-view"'), 0)
  assert.equal(count(r.html, 'class="world-child"'), 1)
  assert.match(r.text, /Scenario simulation world-v1/)
  // without a record the world view renders alone, exactly as before
  const bare = mountSimulationView(t, { api: {
    getSimulation: async id => ({ success: true, data: { simulation_id: id, simulation_engine: 'world-v1' } }),
    fetchRecord: async () => ({ record: null, status: 404, publicationStatus: 'absent' }),
  } })
  await settle()
  const b = await bare.render()
  assert.equal(count(b.html, 'class="world-child"'), 1)
  assert.doesNotMatch(b.html, /sim-record-shell|sim-record-view|Live view/)
})

test('switching to another simulation drops the record and tells the parent', async t => {
  let serve = { record: RECORD_EN, status: 200, publicationStatus: 'passed' }
  const h = mountSimulationView(t, { api: { fetchRecord: async () => serve } })
  await settle()
  assert.equal(h.state.record.value.simulation_id, 'sim_fixture_record_en')
  h.state.showRecord.value = false
  serve = { record: null, status: 404, publicationStatus: 'absent' }
  h.props.simulationId = 'sim_2'
  await settle()
  assert.equal(h.state.record.value, null)
  assert.equal(h.state.showRecord.value, true, 'the next run opens on its record again')
  assert.deepEqual(h.emitted.at(-1), ['record-state', { available: false, status: 404 }])
  h.props.simulationId = ''
  await settle()
  assert.deepEqual(h.emitted.at(-1), ['record-state', { available: false, status: null }])
})

test('the Chinese interface words the toggle, the caveat and the record labels in Chinese', async t => {
  const h = mountSimulationView(t, { lang: 'zh' })
  await settle()
  const r = await h.render()
  assert.ok(r.text.includes(SIM_CAVEAT_ZH))
  assert.match(r.html, />记录<\/button>/)
  assert.match(r.html, />实时视图<\/button>/)
  assert.ok(r.html.includes('aria-label="视图选择"'))
})


test('world-v1 runs re-ask for a missing record the same bounded number of times (S2 review)', async t => {
  const h = mountSimulationView(t, { api: {
    getSimulation: async id => ({ success: true, data: { simulation_id: id, simulation_engine: 'world-v1' } }),
    fetchRecord: async () => ({ record: null, status: 404, publicationStatus: 'absent' }),
  } })
  await settle()
  assert.equal(h.state.record.value, null)
  assert.deepEqual(h.timers, [15000])
  for (let i = 0; i < 4; i++) await h.state.loadAll()
  assert.deepEqual(h.timers, [15000, 15000, 15000, 15000])
  assert.equal(h.calls.filter(key => key === 'fetchRecord').length, 5)
})

test('the record acceptance literals are the backend constants', () => {
  assert.equal(simRecord.RECORD_SCHEMA, pyConst('RECORD_SCHEMA'))
  assert.equal(simRecord.RECORD_CLASS, pyConst('RECORD_CLASS'))
})

for (const engine of ['oasis-legacy', 'world-v1']) {
  test(`${engine}: Stage 5 completion re-arms record loading after earlier retries stopped`, async t => {
    let available = false
    const h = mountSimulationView(t, { stageStatus: 'pending', api: {
      getSimulation: async id => ({ success: true, data: { simulation_id: id, simulation_engine: engine } }),
      fetchRecord: async () => available
        ? { record: RECORD_EN, status: 200, publicationStatus: 'passed' }
        : { record: null, status: 404, publicationStatus: 'absent' },
    } })
    await settle()
    for (let i = 0; i < 5; i++) await h.state.loadAll()
    h.props.stageStatus = 'running'
    await settle()
    assert.equal(h.calls.filter(key => key === 'fetchRecord').length, 0, 'do not spend publication retries before Stage 5 finalizes')
    available = true
    h.props.stageStatus = 'completed'
    await settle()
    assert.equal(h.state.record.value?.simulation_id, RECORD_EN.simulation_id)
    assert.equal(h.state.showRecord.value, true)
    assert.match((await h.render()).html, /class="sim-record-view"/)
  })
}

test('the report record request selects Record again and retries an exhausted or failed publication read', async t => {
  let available = false
  const h = mountSimulationView(t, { api: { fetchRecord: async () => available
    ? { record: RECORD_EN, status: 200, publicationStatus: 'passed' }
    : { record: null, status: 409, publicationStatus: 'failed' } } })
  await settle()
  h.state.showRecord.value = false
  available = true
  h.props.openRecordRequest++
  await settle()
  assert.equal(h.state.showRecord.value, true)
  assert.match((await h.render()).html, /class="sim-record-view"/)
})

test('a pending audit is retried, but a failed or stale audit remains unavailable', async t => {
  for (const publicationStatus of ['not_audited', 'failed', 'stale_audit']) {
    const h = mountSimulationView(t, { api: { fetchRecord: async () => ({ record: null, status: 409, publicationStatus }) } })
    await settle()
    assert.deepEqual(h.timers, publicationStatus === 'not_audited' ? [15000] : [])
    assert.equal(h.state.record.value, null)
  }
})

test('switching simulation ignores a delayed record even if transport cannot abort', async t => {
  let finish
  const h = mountSimulationView(t, { api: { fetchRecord: id => id === 'sim_1'
    ? new Promise(resolve => { finish = resolve })
    : Promise.resolve({ record: null, status: 409, publicationStatus: 'failed' }) } })
  await settle()
  h.props.simulationId = 'sim_2'
  await settle()
  finish({ record: RECORD_EN, status: 200, publicationStatus: 'passed' })
  await settle()
  assert.equal(h.state.record.value, null)
  assert.deepEqual(h.emitted.at(-1), ['record-state', { available: false, status: 409 }])
})

test('record quantities preserve small values and precision; Chinese rendering escapes source text', async t => {
  const rec = structuredClone(RECORD_ZH)
  rec.periods[0].facts_changed[0] = {
    variable: '<img src=x onerror=alert(1)>', from: 0.000012345, to: 1.23456789,
    unit: '万吨', cause: '<script>bad()</script>',
  }
  rec.overall.final_variables[0] = { name: '变化', seed_value: 0, final_value: 0.000012345, unit: '万吨' }
  rec.periods[0].narrative = '<svg onload=alert(1)>'
  const h = mountRecord(t, rec, 'zh')
  const r = await h.render()
  assert.match(r.text, /0\.000012345 万吨 → 1\.23456789 万吨/)
  assert.match(r.text, /变化 0 万吨 0\.000012345 万吨/)
  assert.match(r.html, /&lt;img src=x onerror=alert\(1\)&gt;/)
  assert.doesNotMatch(r.html, /<script|<svg|<img/)
  assert.ok(r.text.includes(SIM_BANNER_ZH))
})

// Shapes emitted by _periods_reflexive / _periods_world_v1, rather than the early
// S2 fixture sketch. Exercise those producer fields through the actual SFC.
test('compiler-shaped public moves, offers, red lines and alliances retain their meaning in both languages', async t => {
  const rec = structuredClone(RECORD_EN)
  const p = rec.periods[0]
  p.moves = [{ actor: '甲', option: '谈判', magnitude: 0, terms: '阶段性降税',
    commitment: { text: '履行协议', due_periods: 0 } }]
  p.offers = [{ from_actor: '甲', to_actor: '乙', kind: 'talks', status: 'accepted', terms: '保留原始条款' }]
  p.red_lines_crossed = [{ actor: '甲', by: '乙', red_line: '不得增加关税' }]
  p.alliances = [{ kind: 'alliance_move', actor: '甲', move: 'join', target: '丙' },
    { kind: 'relationship', source: '甲', target: '乙', from: 'cooperative', to: 'hostile' }]
  const h = mountRecord(t, rec)
  let r = await h.render()
  assert.match(r.text, /甲 → 乙 talks 保留原始条款/)
  assert.match(r.text, /甲: 不得增加关税.*乙/)
  assert.match(r.text, /甲: join → 丙/)
  assert.match(r.text, /甲 → 乙: cooperative → hostile/)
  assert.match(r.text, /due in periods 0/)
  assert.match(r.text, /terms: 阶段性降税/)
  i18n.locale.value = 'zh'
  r = await h.render()
  assert.match(r.text, /到期时段数 0/)
  assert.match(r.text, /条款: 阶段性降税/)
  assert.match(r.text, /甲: 不得增加关税.*越线方: 乙/)
  assert.doesNotMatch(r.text, /\[object Object\]/)
})

test('world-v1 compiler explicitly marks periods without an arbiter as not mechanical-only', async t => {
  const rec = structuredClone(RECORD_EN)
  rec.engine = 'world-v1'
  rec.periods[0].arbiter_status = 'not_applicable'
  rec.periods[0].mechanical_only = false
  const h = mountRecord(t, rec)
  const r = await h.render()
  assert.match(r.text, /arbiter: not_applicable/)
  assert.doesNotMatch(r.text, /mechanical only/)
})


test('world record conflicts offer an explicit retry, which revalidates before showing the record', async t => {
  let available = false
  const h = mountSimulationView(t, { api: {
    getSimulation: async id => ({ success: true, data: { simulation_id: id, simulation_engine: 'world-v1' } }),
    fetchRecord: async () => available ? { record: RECORD_EN, status: 200, publicationStatus: 'passed' }
      : { record: null, status: 409, publicationStatus: 'failed' },
  } })
  await settle()
  const before = await h.render()
  assert.match(before.text, /not passed its current publication check/)
  assert.match(before.html, /<button[^>]*>Retry record<\/button>/)
  assert.deepEqual(h.timers, [])
  available = true
  await h.state.retryRecord()
  assert.match((await h.render()).html, /class="sim-record-view"/)
  assert.doesNotMatch((await h.render()).text, /Retry record/)
})

test('a new world generation cannot retain the old record on a transport failure', async t => {
  let generation = 'first'
  const h = mountSimulationView(t, { api: {
    getSimulation: async id => ({ success: true, data: { simulation_id: id, simulation_engine: 'world-v1', world_generation_id: generation } }),
    fetchRecord: async () => {
      if (generation === 'first') return { record: RECORD_EN, status: 200, publicationStatus: 'passed' }
      throw new Error('offline')
    },
  } })
  await settle()
  assert.ok(h.state.record.value)
  generation = 'second'
  await h.state.loadAll()
  assert.equal(h.state.record.value, null)
  assert.equal(h.state.worldGenerationId.value, 'second')
  assert.deepEqual(h.emitted.at(-1), ['record-state', { available: false, status: 'error' }])
})


test('adapter limitations remain visible in the header, including thin records and health stubs', async t => {
  for (const source of [RECORD_EN, HOLLOW]) {
    const rec = structuredClone(source)
    rec.engine = 'oasis-hours'
    rec.limits.notes = ['No world model ran (oasis-hours).', '<script>raw source note</script>']
    const h = mountRecord(t, rec)
    const r = await h.render()
    assert.match(r.text, /No world model ran \(oasis-hours\)\./)
    assert.match(r.html, /&lt;script&gt;raw source note&lt;\/script&gt;/)
    assert.doesNotMatch(r.html, /<script>/)
  }
})


test('producer stubs with unknown validity never render period accounts or shares', async t => {
  for (const explicitStub of [true, false]) {
    const rec = structuredClone(RECORD_EN)
    rec.health.validity = 'unknown'
    if (explicitStub) rec.limits.stub = true
    const h = mountRecord(t, rec)
    const r = await h.render()
    assert.match(r.html, /class="rec-unusable"/)
    assert.match(r.text, /not usable \(status: unknown\)/)
    assert.equal(r.ticks.length, 0)
    assert.doesNotMatch(r.text, /Arbiter narrative|Simulated outcome shares|No consequential move/)
  }
  const rec = structuredClone(RECORD_EN)
  rec.limits.stub = true
  assert.equal(simRecord.isUnusableRecord(rec), true, 'the producer stub flag is authoritative')
})
