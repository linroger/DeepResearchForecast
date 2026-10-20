import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'

import * as i18n from '../src/i18n.js'
import * as worldState from '../src/utils/worldState.js'
import { compileSfc } from './sfcHarness.mjs'

// Drives the real WorldStatePanel.vue (script setup + template) against a fake
// GET /api/simulation/<id>/world-state: the period strip must select any committed
// round, label past periods, survive live refreshes and fall back when a round vanishes.
const buildPanel = compileSfc(new URL('../src/components/research/WorldStatePanel.vue', import.meta.url))

function label(round) {
  return `2026-${String(round).padStart(2, '0')}`
}

function historyRow(round, extra = {}) {
  const status = extra.arbiter_status || 'applied'
  const narrative = status === 'applied' ? `Narrative ${round}.` : ''
  return {
    round,
    period_label: label(round),
    headline: `${label(round)}: ${round} decisions · 1 facts changed · 2 events · arbiter=${status}${narrative ? ' · ' + narrative : ''}`,
    narrative,
    arbiter_status: status,
    arbiter_problems: [],
    decisions: { total: round, ok: round, held: 0, failed: 0, invalid: 0 },
    deterministic: { actions: [`Move ${round} → Target`, 'Actor1 holds position'], effects_fired: [`Effect ${round}`],
      scheduled_events: [], commitments_lapsed: [] },
    diff: {
      variables_changed: [{ id: 'tariff', name: 'Tariff rate', from: 10 + round, to: 11 + round, unit: '%' }],
      variables_added: round % 3 === 0 ? [{ id: `fact${round}`, name: `New fact ${round}`, value: 'in force', unit: '' }] : [],
      relationships_changed: []
    },
    digest: `Digest ${round}.\nMoves:\n- Actor0: Move ${round}`,
    ...extra
  }
}

function payload(rounds) {
  const rows = rounds.map((r) => historyRow(r, [5, 6].includes(r)
    ? { arbiter_status: 'failed', arbiter_problems: ['llm error: BadRequestError'] }
    : {}))
  const last = rows[rows.length - 1]
  const windowRounds = rounds.slice(-4)
  return {
    committed_round: last.round,
    headline: last.headline,
    digest: last.digest,
    period: { label: last.period_label },
    summary: { arbiter_failed_rounds: rows.filter((r) => r.arbiter_status === 'failed').length },
    variables: [{ id: 'tariff', name: 'Tariff rate', value: 11 + last.round, unit: '%', kind: 'numeric', provenance: 'arbiter',
      history: [{ round: 0, value: 10 }, { round: last.round, value: 11 + last.round }] }],
    actors: [{ agent_id: 0, name: 'Actor0', pending_commitments: [{ description: 'Publish schedule', due_round: last.round + 1, status: 'pending' }] }],
    pending_effects: [],
    recent_events: windowRounds.flatMap((r) => [
      { round: r, kind: 'action', description: `Move ${r} → Target`, actors: ['Actor0'], targets: ['Target'], statement: `Statement ${r}` },
      { round: r, kind: 'emergent', description: `Protest ${r}` }
    ]),
    history: rows
  }
}

function mountPanel(t, first) {
  i18n.locale.value = 'en'
  let current = first
  const calls = []
  const panel = buildPanel({
    // the SSR run has no mounted instance: the panel loads on demand through state.load()
    vue: { ...vue, onMounted: () => {}, onUnmounted: () => {} },
    '../../i18n': i18n,
    '../../api/simulation': { getWorldState: async (simId, rows) => { calls.push([simId, rows]); return { data: current } } },
    '../../utils/worldState': worldState
  })
  const props = vue.reactive({ simulationId: 'sim_1', refreshToken: 0, pollMs: 0, round: undefined })
  const emitted = []
  const scope = vue.effectScope()
  const state = scope.run(() => panel.setup(props, {
    expose() {}, emit: (name, value) => { emitted.push([name, value]) }, attrs: {}, slots: {}
  }))
  t.after(() => { scope.stop(); i18n.locale.value = 'en' })
  const host = { setup: () => state, render: panel.render }
  async function render() {
    // SSR fragment markers (<!--[-->) are stripped: assertions look at the markup people get
    const html = (await renderToString(vue.createSSRApp(host))).replace(/<!--[^]*?-->/g, '')
    const text = html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
    const ticks = [...html.matchAll(/<button[^>]*class="ws-tick[^"]*"[^>]*>[^<]*<\/button>/g)].map((m) => m[0])
    return { html, text, ticks }
  }
  return { state, props, calls, emitted, render, serve: (p) => { current = p } }
}

const pressed = (tick) => /aria-pressed="true"/.test(tick)

test('every committed round is a toggle button; the latest one is selected by default', async (t) => {
  const h = mountPanel(t, payload([1, 2, 3, 4, 5, 6, 7, 8, 9]))
  await h.state.load()
  assert.deepEqual(h.calls, [['sim_1', 48]])
  const r = await h.render()
  assert.equal(r.ticks.length, 9)
  assert.ok(r.html.includes('role="group"') && r.html.includes('aria-label="Select a committed period"'))
  assert.deepEqual(r.ticks.map(pressed), [false, false, false, false, false, false, false, false, true])
  assert.ok(r.ticks.every((tick) => /aria-pressed="(true|false)"/.test(tick) && /aria-label="2026-/.test(tick)))
  assert.match(r.ticks[8], /class="ws-tick mono st-applied current selected"/)
  assert.match(r.ticks[8], /aria-label="2026-09, arbiter applied, 1 facts changed, latest"/)
  assert.match(r.ticks[4], /class="ws-tick mono st-failed"/)
  assert.match(r.ticks[2], /class="ws-tick mono st-applied"/)
  assert.match(r.ticks[2], />2026-03 · 1Δ</)
  assert.doesNotMatch(r.text, /past period|back to latest/)
  assert.match(r.text, /World state 2026-09 committed 9/)
  assert.match(r.text, /2026-09: 9 decisions · 1 facts changed · 2 events · arbiter=applied Narrative 9\./)
  assert.match(r.text, /9 decisions · 9 ok/)
  assert.match(r.text, /Key facts \(1\)/)
  assert.match(r.text, /Pending and expected \(1\)/)
  assert.match(r.text, /Moves this period \(1\) Actor0 Move 9 → Target Statement 9/)
  assert.match(r.html, /<details class="ws-digest"><summary>Digest shown to the agents this period<\/summary>/)
})

test('selecting a past round shows that round, labelled, with a one-click return', async (t) => {
  const h = mountPanel(t, payload([1, 2, 3, 4, 5, 6, 7, 8, 9]))
  await h.state.load()
  h.state.selectRound(3)
  assert.equal(h.state.selectedRound.value, 3)
  let r = await h.render()
  assert.deepEqual(r.ticks.map(pressed).filter(Boolean).length, 1)
  assert.match(r.ticks[2], /class="ws-tick mono st-applied selected"/)
  assert.match(r.ticks[8], /class="ws-tick mono st-applied current"/)      // the latest keeps its bold ring
  assert.match(r.text, /World state 2026-03 past period · round 3 \/ 9 committed 9 ↩ back to latest · 2026-09/)
  assert.match(r.text, /2026-03: 3 decisions · 1 facts changed · 2 events · arbiter=applied Narrative 3\./)
  assert.match(r.text, /3 decisions · 3 ok/)
  assert.match(r.text, /Facts changed this period \(2\) Tariff rate 13% → 14% new New fact 3 in force/)
  // round 3 is outside the recent-event window → the history row's deterministic lists stand in
  assert.match(r.text, /Moves this period \(1\) Move 3 → Target/)
  assert.match(r.text, /Consequences and events \(1\) effect Effect 3/)
  assert.doesNotMatch(r.text, /Key facts|Pending and expected/)
  assert.match(r.text, /Digest 3\. Moves: - Actor0: Move 3/)
  assert.match(r.html, /<button[^>]*class="ws-back mono"/)
  // a failed round: red tick, verdict badge, problems, digest expanded in place of the missing narrative
  h.state.selectRound(5)
  r = await h.render()
  assert.match(r.ticks[4], /class="ws-tick mono st-failed selected"/)
  assert.match(r.text, /arbiter: failed/)
  assert.match(r.text, /No arbiter narrative for this period ▲ arbiter problem: llm error: BadRequestError/)
  assert.match(r.html, /<details class="ws-digest" open>/)
  // back to the live world
  h.state.backToLatest()
  assert.equal(h.state.selectedRound.value, null)
  r = await h.render()
  assert.ok(pressed(r.ticks[8]))
  assert.doesNotMatch(r.text, /past period/)
  // clicking the latest tick is the same as following the live world
  h.state.selectRound(9)
  assert.equal(h.state.selectedRound.value, null)
})

test('a live refresh keeps the selection until the round disappears', async (t) => {
  const h = mountPanel(t, payload([1, 2, 3, 4, 5, 6, 7, 8, 9]))
  await h.state.load()
  h.state.selectRound(3)
  h.serve(payload([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]))                   // a new round commits
  await h.state.load()
  assert.equal(h.state.selectedRound.value, 3)
  let r = await h.render()
  assert.equal(r.ticks.length, 10)
  assert.match(r.text, /past period · round 3 \/ 10 committed 10/)
  assert.ok(pressed(r.ticks[2]) && !pressed(r.ticks[9]))
  h.serve(payload([11, 12]))                                           // a rerun rotated the artifacts
  await h.state.load()
  assert.equal(h.state.selectedRound.value, null)
  r = await h.render()
  assert.deepEqual(r.ticks.map(pressed), [false, true])
  assert.doesNotMatch(r.text, /past period/)
  assert.match(r.text, /World state 2026-12 committed 12/)
  // a different simulation drops the selection too
  h.state.selectRound(11)
  assert.equal(h.state.selectedRound.value, 11)
  h.props.simulationId = 'sim_2'
  await vue.nextTick()
  assert.equal(h.state.selectedRound.value, null)
  assert.deepEqual(h.calls.map((c) => c[0]), ['sim_1', 'sim_1', 'sim_1', 'sim_2'])
})

test('the panel reads Chinese labels from the locale', async (t) => {
  const h = mountPanel(t, payload([1, 2, 3]))
  await h.state.load()
  i18n.locale.value = 'zh'
  h.state.selectRound(1)
  const r = await h.render()
  assert.match(r.text, /世界状态 2026-01 历史时段 · 第1期 \/ 3 已提交 3 ↩ 回到最新 · 2026-03/)
  assert.match(r.text, /1 项决策 · 1 有效/)
  assert.match(r.text, /本时段事实变化 \(1\)/)
  assert.match(r.html, /aria-label="选择已提交的时段"/)
  assert.match(r.ticks[0], /aria-label="2026-01, 仲裁 applied, 1 项事实变化"/)
})


test('the selection is announced to the parent and a parent reset is honoured', async (t) => {
  const h = mountPanel(t, payload([1, 2, 3, 4, 5]))
  await h.state.load()
  assert.deepEqual(h.emitted, [])
  h.state.selectRound(2)
  await vue.nextTick()
  assert.deepEqual(h.emitted, [['update:selectedRound', 2]])
  h.state.selectRound(5)                                              // the latest round = follow the live world
  await vue.nextTick()
  assert.deepEqual(h.emitted.at(-1), ['update:selectedRound', null])
  h.state.selectRound(3)
  await vue.nextTick()
  assert.equal(h.state.selectedRound.value, 3)
  // the feed's "all periods" button pushes null through the prop; the panel follows and announces it
  h.props.round = null
  await vue.nextTick()
  assert.equal(h.state.selectedRound.value, null)
  assert.deepEqual(h.emitted.at(-1), ['update:selectedRound', null])
  // a parent value equal to the current one is a no-op; an undefined prop leaves the panel in charge
  h.props.round = null
  await vue.nextTick()
  h.props.round = undefined
  h.state.selectRound(4)
  await vue.nextTick()
  assert.equal(h.state.selectedRound.value, 4)
  assert.deepEqual(h.emitted.at(-1), ['update:selectedRound', 4])
  const r = await h.render()
  assert.match(r.text, /past period · round 4 \/ 5/)
})

// GET /world-state for the reflexivity scenario run through the real kernel (see worldState.test.mjs)
const reflexive = () => JSON.parse(readFileSync(new URL('./fixtures/world/world_state.reflexive.json', import.meta.url), 'utf8'))
const CROSSING = 'United States Government crossed China Ministry of Commerce&#39;s red line: No tariffs above 100% on Chinese goods'

test('track records, the expected-reaction count and a crossed red line reach the reader', async (t) => {
  const h = mountPanel(t, reflexive())
  await h.state.load()
  let r = await h.render()
  // the expectation badge sits beside the responsive-moves badge and explains itself on hover
  assert.match(r.text, /responsive moves 25% expected reactions followed 1\/1 model projection, not evidence/)
  assert.match(r.html, /title="1 of the 1 reactions the actors expected after their own moves were followed by a move of the actor they named, one period later\. Whether that move matched the expectation is not judged\."/)
  // breakers first; zero buckets left out; released is not the actor's failure
  assert.match(r.text, /Track records \(2\) United States Government kept 0 of 1 \(0%\) · 1 broken · moves: 1 succeeded China Ministry of Commerce 1 released · moves: 1 partly succeeded/)
  assert.match(r.html, /<li class="ws-record tr-broken"><span class="ws-actor">United States Government<\/span>/)
  assert.match(r.html, /<li class="ws-record"><span class="ws-actor">China Ministry of Commerce<\/span>/)
  assert.match(r.html, /<div class="ws-card-head" title="Commitments the world recorded for each actor: kept, lapsed/)
  assert.doesNotMatch(r.text, /reputation|0\.37/)                   // counts, never the mixed score
  // the crossing period: the red line is labelled, not tagged red_line, and leads the list
  h.state.selectRound(1)
  r = await h.render()
  assert.match(r.text, new RegExp(`Consequences and events \\(2\\) red line crossed ${CROSSING} — 145% announced relation`))
  assert.match(r.html, /<li class="ws-event ev-red-line"><span class="ws-kind mono">red line crossed<\/span>/)
  assert.doesNotMatch(r.text, /red_line|Track records/)              // track records describe the latest world
  // the same period after its events left the API window: the history row stands in
  const data = reflexive()
  data.recent_events = data.recent_events.filter((e) => e.round > 2)
  h.serve(data)
  await h.state.load()
  r = await h.render()
  assert.match(r.text, new RegExp(`Consequences and events \\(2\\) red line crossed ${CROSSING} relation`))
})

test('the new lines read Chinese labels from the locale', async (t) => {
  const h = mountPanel(t, reflexive())
  await h.state.load()
  i18n.locale.value = 'zh'
  let r = await h.render()
  assert.match(r.text, /回应上期 25% 预期反应获跟进 1\/1/)
  assert.match(r.html, /title="角色在自身行动后预期他方作出的 1 项反应中，1 项在下一时段确有被点名方的行动跟进；该行动是否符合预期不作判定。"/)
  assert.match(r.text, /履约记录 \(2\) United States Government 兑现 0\/1 \(0%\) · 1 项违约 · 行动：1 项成功 China Ministry of Commerce 1 项因对方违约解除 · 行动：1 项部分成功/)
  h.state.selectRound(1)
  r = await h.render()
  assert.match(r.html, /<span class="ws-kind mono">越过红线<\/span>/)
})

test('a run whose records hold nothing yet says so', async (t) => {
  const early = payload([1])
  early.actors[0].track_record = { kept: 0, lapsed: 0, broken: 0, released: 0, open: 0, resolved: 0, reliability: null, outcomes: {} }
  const h = mountPanel(t, early)
  await h.state.load()
  const r = await h.render()
  assert.match(r.text, /Track records \(0\) No commitment or move resolved yet/)
})

test('runs from before the reflexivity signals render no new lines', async (t) => {
  const legacy = payload([1, 2, 3])
  legacy.summary.behaviour = { rounds_scored: 2, moves: 4, responsive_moves: 1, responsive_share: 0.25, offers_answered: 0 }
  const h = mountPanel(t, legacy)
  await h.state.load()
  const r = await h.render()
  assert.match(r.text, /responsive moves 25% model projection, not evidence/)
  assert.doesNotMatch(r.text, /expected reactions|Track records|red line/)
  assert.doesNotMatch(r.html, /ws-record|ev-red-line/)
})
