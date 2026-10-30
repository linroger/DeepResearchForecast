import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  agencyLabel,
  decisionsSummary,
  eventKindLabel,
  formatWorldValue,
  headlineSummary,
  latestHistoryRound,
  latestHistoryRow,
  nextSelectedRound,
  resolveSelectedRound,
  summarizeWorldState,
  trackRecordRows,
  trackRecordSummary,
  variableDelta
} from '../src/utils/worldState.js'

// GET /world-state for the reflexivity scenario run through the real kernel (red line crossed in
// round 1, expectation checked in round 2, US withdrawal = broken obligation in round 4); pinned
// against the API by backend/tests/test_world_reader_signals.py
const reflexive = () => JSON.parse(readFileSync(new URL('./fixtures/world/world_state.reflexive.json', import.meta.url), 'utf8'))

test('formatWorldValue mirrors the backend rendering', () => {
  assert.equal(formatWorldValue(25, '%'), '25%')
  assert.equal(formatWorldValue(2e9, 'US$'), 'US$2.00 billion')
  assert.equal(formatWorldValue(3.5e12, 'CNY'), 'CNY3.50 trillion')
  assert.equal(formatWorldValue(1200, 'GW'), '1200 GW')
  assert.equal(formatWorldValue(25000, 'GW'), '25,000 GW')
  assert.equal(formatWorldValue(true, ''), 'yes')
  assert.equal(formatWorldValue('pending', ''), 'pending')
  assert.equal(formatWorldValue(null, 'x'), '— x')
  // a kind name is never a unit (arbiter-created facts of persisted runs carry "boolean" / "date")
  assert.equal(formatWorldValue(true, 'boolean'), 'yes')
  assert.equal(formatWorldValue('2027-03-10', 'date'), '2027-03-10')
  assert.equal(formatWorldValue(12, 'numeric'), '12')
})

test('variableDelta reads the last two history points', () => {
  assert.equal(variableDelta({ history: [{ round: 0, value: 10 }] }), null)
  assert.deepEqual(
    variableDelta({ history: [{ round: 0, value: 10 }, { round: 1, value: 25, cause: 'decree' }] }),
    { from: 10, to: 25, direction: 'up', cause: 'decree', round: 1 }
  )
  assert.equal(variableDelta({ history: [{ value: 'a' }, { value: 'b' }] }).direction, 'changed')
  assert.equal(variableDelta({ history: [{ value: 5 }, { value: 5 }] }).direction, 'flat')
  assert.equal(variableDelta(null), null)
})

test('latestHistoryRow picks the highest round and tolerates junk', () => {
  assert.equal(latestHistoryRow(null), null)
  assert.equal(latestHistoryRow([null, 'x']), null)
  assert.equal(latestHistoryRow([{ round: 1 }, { round: 3 }, { round: 2 }]).round, 3)
  assert.equal(latestHistoryRound([{ round: 1 }, { round: 3 }, { round: 2 }]), 3)
  assert.equal(latestHistoryRound([]), null)
  assert.equal(latestHistoryRound([{ round: 'x' }]), null)
})

const ROWS = [{ round: 1 }, { round: 2 }, null, { round: 3 }]

test('resolveSelectedRound keeps a live selection and falls back to the latest round', () => {
  assert.equal(resolveSelectedRound(ROWS, null), 3)                 // follow mode → latest
  assert.equal(resolveSelectedRound(ROWS, undefined), 3)
  assert.equal(resolveSelectedRound(ROWS, 2), 2)                    // a past round that still exists
  assert.equal(resolveSelectedRound(ROWS, '2'), 2)
  assert.equal(resolveSelectedRound(ROWS, 3), 3)
  assert.equal(resolveSelectedRound(ROWS, 7), 3)                    // vanished (rerun / rotated) → latest
  assert.equal(resolveSelectedRound(ROWS, 'zz'), 3)
  assert.equal(resolveSelectedRound([], 2), null)
  assert.equal(resolveSelectedRound(null, null), null)
})

test('nextSelectedRound pins past rounds and maps the latest round to follow mode', () => {
  assert.equal(nextSelectedRound(ROWS, 3), null)                    // clicking the latest → follow the live world
  assert.equal(nextSelectedRound(ROWS, 1), 1)
  assert.equal(nextSelectedRound(ROWS, '2'), 2)
  assert.equal(nextSelectedRound(ROWS, 9), null)                    // unknown round → follow mode, never a dead pin
  assert.equal(nextSelectedRound(ROWS, 'zz'), null)
  assert.equal(nextSelectedRound([], 1), null)
})

test('headlineSummary strips the narrative tail of a world-update headline', () => {
  assert.equal(
    headlineSummary('2026-12: 5 decisions · 2 facts changed · 4 events · arbiter=applied · The G20 Miami meeting produced…'),
    '2026-12: 5 decisions · 2 facts changed · 4 events · arbiter=applied'
  )
  assert.equal(headlineSummary('2027-02: 6 decisions · 0 facts changed · 0 events · arbiter=failed'),
    '2027-02: 6 decisions · 0 facts changed · 0 events · arbiter=failed')
  assert.equal(headlineSummary('2027-02: update failed'), '2027-02: update failed')
  assert.equal(headlineSummary(''), '')
  assert.equal(headlineSummary(null), '')
})

test('decisionsSummary counts decisions and omits empty buckets', () => {
  assert.equal(decisionsSummary({ total: 5, ok: 5, held: 0, failed: 0, invalid: 0 }), '5 decisions · 5 ok')
  assert.equal(decisionsSummary({ total: 6, ok: 6, held: 1 }), '6 decisions · 6 ok · 1 held')
  assert.equal(decisionsSummary({ total: 4, ok: 2, failed: 1, invalid: 1 }), '4 decisions · 2 ok · 1 failed · 1 invalid')
  assert.equal(decisionsSummary({ total: 3 }), '3 decisions')
  assert.equal(decisionsSummary({ total: 3, ok: 3 }, { decisions: '项决策', ok: '有效' }), '3 项决策 · 3 有效')
  assert.equal(decisionsSummary({ ok: 3 }), '')
  assert.equal(decisionsSummary(null), '')
  assert.equal(decisionsSummary('x'), '')
})

function fixture() {
  return {
    committed_round: 2,
    headline: '2026-Q4: 3 decisions',
    digest: 'fallback digest',
    period: { label: '2026-Q4' },
    summary: { arbiter_failed_rounds: 1 },
    variables: [
      { id: 'permit', name: 'Permit', value: 'pending', unit: '', kind: 'categorical', history: [{ round: 0, value: 'pending' }] },
      { id: 'tariff', name: 'Tariff rate', value: 25, unit: '%', kind: 'numeric', provenance: 'arbiter',
        history: [{ round: 0, value: 10 }, { round: 2, value: 25, cause: 'decree' }] }
    ],
    actors: [
      { agent_id: 0, name: 'Actor0', pending_commitments: [{ description: 'Publish schedule', due_round: 3, status: 'due' }] },
      { agent_id: 1, name: 'Actor1', pending_commitments: [] }
    ],
    pending_effects: [{ description: 'Importers relocate', due_round: 4 }],
    recent_events: [
      { round: 1, kind: 'action', description: 'old move', actors: ['Actor0'] },
      { round: 2, kind: 'action', description: 'Impose tariff → Actor1', actors: ['Actor0'], targets: ['Actor1'], statement: 'Tariff raised' },
      { round: 2, kind: 'action', description: 'Actor1 holds position', actors: ['Actor1'] },
      { round: 2, kind: 'emergent', description: 'Importers protest' }
    ],
    history: [
      { round: 2, period_label: '2026-Q4', headline: 'h2', narrative: 'Shock.', arbiter_status: 'applied', arbiter_problems: [],
        decisions: { total: 3, ok: 3 }, digest: 'Digest 2.',
        diff: { variables_changed: [{ id: 'tariff', name: 'Tariff rate', from: 10, to: 25, unit: '%' }],
                relationships_changed: [{ source: 'Actor0', target: 'Actor1', to: 'adversarial', direction: 'farther' }] } },
      { round: 1, period_label: '2026-Q3', headline: '2026-Q3: 3 decisions · 1 facts changed · 0 events · arbiter=failed',
        arbiter_status: 'failed', arbiter_problems: ['llm error: BadRequestError'], error: 'BadRequestError: content filter',
        decisions: { total: 3, ok: 3, held: 1 }, digest: 'Digest 1.\nMoves:\n- Actor0: Impose tariff',
        deterministic: { actions: ['Impose tariff → Actor1', 'Actor1 holds position'], effects_fired: ['Importers brace'],
                         scheduled_events: [{ description: 'Midterms' }], commitments_lapsed: [] },
        diff: { variables_changed: [{ id: 'tariff', name: 'Tariff rate', from: 5, to: 10, unit: '%' }],
                variables_added: [{ id: 'permit', name: 'Permit', value: 'pending', unit: '' }] } }
    ]
  }
}

test('summarizeWorldState builds the panel view model', () => {
  const vm = summarizeWorldState(fixture())
  assert.equal(vm.committedRound, 2)
  assert.equal(vm.latestRound, 2)
  assert.equal(vm.selectedRound, 2)
  assert.equal(vm.isPast, false)
  assert.equal(vm.latestLabel, '2026-Q4')
  assert.equal(vm.periodLabel, '2026-Q4')
  assert.equal(vm.headline, '2026-Q4: 3 decisions')
  assert.equal(vm.headlineSummary, '2026-Q4: 3 decisions')
  assert.equal(vm.narrative, 'Shock.')
  assert.equal(vm.digest, 'Digest 2.')
  assert.equal(vm.arbiterStatus, 'applied')
  assert.deepEqual(vm.arbiterProblems, [])
  assert.equal(vm.arbiterFailedRounds, 1)
  assert.deepEqual(vm.decisions, { total: 3, ok: 3 })
  // changed variables sort first and carry a readable delta
  assert.equal(vm.variables[0].name, 'Tariff rate')
  assert.equal(vm.variables[0].deltaDisplay, '10% → 25%')
  assert.equal(vm.variables[1].display, 'pending')
  assert.equal(vm.variables[1].deltaDisplay, '')
  assert.deepEqual(vm.variablesChanged, [{ id: 'tariff', name: 'Tariff rate', direction: 'up', display: '10% → 25%' }])
  assert.deepEqual(vm.variablesAdded, [])
  // moves of the committed round only, holds excluded
  assert.deepEqual(vm.moves, [{ actor: 'Actor0', description: 'Impose tariff → Actor1', statement: 'Tariff raised', targets: ['Actor1'] }])
  assert.deepEqual(vm.consequences, [{ kind: 'emergent', description: 'Importers protest' }])
  assert.equal(vm.eventsInWindow, true)
  assert.deepEqual(vm.relationshipChanges, [{ source: 'Actor0', target: 'Actor1', to: 'adversarial', direction: 'farther' }])
  assert.deepEqual(vm.pending, [
    { actor: 'Actor0', description: 'Publish schedule', dueRound: 3, status: 'due' },
    { actor: 'Expected', description: 'Importers relocate', dueRound: 4, status: 'effect' }
  ])
  assert.deepEqual(vm.history.map((h) => [h.round, h.label, h.arbiterStatus, h.factsChanged, h.factsAdded, h.isCurrent, h.isSelected]),
    [[1, '2026-Q3', 'failed', 1, 1, false, false], [2, '2026-Q4', 'applied', 1, 0, true, true]])
})

test('summarizeWorldState describes a selected past round from its history row', () => {
  const vm = summarizeWorldState(fixture(), 1)
  assert.equal(vm.isPast, true)
  assert.equal(vm.selectedRound, 1)
  assert.equal(vm.latestRound, 2)
  assert.equal(vm.committedRound, 2)                                  // the live world is still round 2
  assert.equal(vm.periodLabel, '2026-Q3')
  assert.equal(vm.latestLabel, '2026-Q4')
  assert.equal(vm.headline, '2026-Q3: 3 decisions · 1 facts changed · 0 events · arbiter=failed')
  assert.equal(vm.headlineSummary, vm.headline)
  assert.equal(vm.narrative, '')
  assert.equal(vm.digest, 'Digest 1.\nMoves:\n- Actor0: Impose tariff')
  assert.equal(vm.arbiterStatus, 'failed')
  assert.deepEqual(vm.arbiterProblems, ['llm error: BadRequestError', 'BadRequestError: content filter'])
  assert.deepEqual(vm.decisions, { total: 3, ok: 3, held: 1 })
  assert.deepEqual(vm.variablesChanged, [{ id: 'tariff', name: 'Tariff rate', direction: 'up', display: '5% → 10%' }])
  assert.deepEqual(vm.variablesAdded, [{ id: 'permit', name: 'Permit', display: 'pending' }])
  // round 1 is inside the recent-event window: its events are used, holds excluded
  assert.equal(vm.eventsInWindow, true)
  assert.deepEqual(vm.moves, [{ actor: 'Actor0', description: 'old move', statement: '', targets: [] }])
  assert.deepEqual(vm.consequences, [])
  assert.deepEqual(vm.relationshipChanges, [])
  // the tracked variables and open commitments still describe the latest world
  assert.equal(vm.variables[0].deltaDisplay, '10% → 25%')
  assert.equal(vm.pending.length, 2)
  assert.deepEqual(vm.history.map((h) => [h.round, h.isCurrent, h.isSelected]), [[1, false, true], [2, true, false]])
})

test('summarizeWorldState falls back to the deterministic lists outside the recent-event window', () => {
  const data = fixture()
  data.recent_events = data.recent_events.filter((e) => e.round === 2)
  const vm = summarizeWorldState(data, 1)
  assert.equal(vm.eventsInWindow, false)
  assert.deepEqual(vm.moves, [{ actor: '', description: 'Impose tariff → Actor1', statement: '', targets: [] }])
  assert.deepEqual(vm.consequences, [
    { kind: 'effect', description: 'Importers brace' },
    { kind: 'scheduled', description: 'Midterms' }
  ])
})

test('summarizeWorldState ignores a selection that no longer exists', () => {
  const vm = summarizeWorldState(fixture(), 99)
  assert.equal(vm.isPast, false)
  assert.equal(vm.selectedRound, 2)
  assert.equal(vm.narrative, 'Shock.')
  assert.deepEqual(vm.history.map((h) => h.isSelected), [false, true])
})

test('summarizeWorldState keeps the legacy digest fallback and is defensive', () => {
  const legacy = summarizeWorldState({ committed_round: 1, digest: 'only digest', period: { label: '2026-Q3' } })
  assert.equal(legacy.latestRound, 1)
  assert.equal(legacy.selectedRound, 1)
  assert.equal(legacy.isPast, false)
  assert.equal(legacy.narrative, 'only digest')
  assert.equal(legacy.digest, 'only digest')
  assert.equal(legacy.periodLabel, '2026-Q3')
  assert.deepEqual(legacy.history, [])
  const vm = summarizeWorldState(null)
  assert.equal(vm.committedRound, 0)
  assert.equal(vm.latestRound, null)
  assert.equal(vm.selectedRound, null)
  assert.equal(vm.isPast, false)
  assert.deepEqual(vm.variables, [])
  assert.deepEqual(vm.moves, [])
  assert.deepEqual(vm.arbiterProblems, [])
  assert.equal(vm.headline, '')
  assert.equal(vm.digest, '')
  assert.equal(agencyLabel('sovereign_government'), 'sovereign government')
  assert.equal(agencyLabel(null), '')
})

test('offers: the latest view lists the API rows and a past period lists the status changes of its diff', () => {
  const data = {
    committed_round: 3,
    summary: { offers: { opened: 2, open: 1, accepted: 1, rejected: 0, countered: 0, lapsed: 0, breached: 0 } },
    interactions: [
      { id: 'i3_2', status: 'open', proposer: 'Union', recipient: 'Ministry', terms: 'Wage floor', expires_round: 5, resolved_round: null },
      { id: 'i1_1', status: 'accepted', proposer: 'Ministry', recipient: 'Agency', terms: 'Audits', expires_round: 3, resolved_round: 2 }
    ],
    history: [
      { round: 2, period_label: '2026-11', diff: { variables_changed: [], variables_added: [], relationships_changed: [],
        interactions_changed: [{ id: 'i1_1', from: 'open', to: 'accepted', proposer: 'Ministry', recipient: 'Agency', terms: 'Audits' }] } },
      { round: 3, period_label: '2026-12', diff: { variables_changed: [], variables_added: [], relationships_changed: [] } }
    ]
  }
  const latest = summarizeWorldState(data)
  assert.deepEqual(latest.offers.map((o) => [o.id, o.status, o.expiresRound]), [['i3_2', 'open', 5], ['i1_1', 'accepted', 3]])
  assert.equal(latest.offerCounts.accepted, 1)
  const past = summarizeWorldState(data, 2)
  assert.deepEqual(past.offers, [{ id: 'i1_1', status: 'accepted', proposer: 'Ministry', recipient: 'Agency', terms: 'Audits',
    expiresRound: null, resolvedRound: 2 }])
  assert.deepEqual(summarizeWorldState(data, 3).offers, latest.offers)        // the latest round is the live view
  assert.deepEqual(summarizeWorldState({ committed_round: 1, history: [] }).offers, [])
  assert.equal(summarizeWorldState({ committed_round: 1, history: [] }).offerCounts, null)
})

test('modelling gaps and behaviour diagnostics are summarised when present', () => {
  const data = {
    committed_round: 2, history: [],
    summary: { seed_gaps: 2, behaviour: { rounds_scored: 1, moves: 3, responsive_moves: 2, responsive_share: 0.667, offers_answered: 1 } },
    seed_gaps: [{ kind: 'variable_without_unit', subject: 'Permits', note: 'no unit' }, 'junk', { kind: 'no_relationships', subject: 'cast', note: 'none' }]
  }
  const vm = summarizeWorldState(data)
  assert.deepEqual(vm.seedGaps.map((g) => g.subject), ['Permits', 'cast'])
  assert.deepEqual(vm.behaviour, { roundsScored: 1, moves: 3, responsiveMoves: 2, responsiveShare: 0.667, offersAnswered: 1 })
  assert.equal(summarizeWorldState({ committed_round: 1, history: [], summary: { behaviour: { responsive_share: null } } }).behaviour, null)
  assert.deepEqual(summarizeWorldState({ committed_round: 1, history: [] }).seedGaps, [])
})

const record = (o = {}) => ({ kept: 0, lapsed: 0, broken: 0, released: 0, open: 0, outcomes: {}, ...o })

test('trackRecordRows lists actors with a record, breakers first, and skips empty or junk records', () => {
  const rows = trackRecordRows([
    { name: 'Clean', track_record: record({ kept: 3, reliability: 1 }) },
    { name: 'Lapser', track_record: record({ kept: 1, lapsed: 2, reliability: 0.333 }) },
    { name: 'Breaker', track_record: record({ broken: 1, lapsed: 1, outcomes: { blocked: 2, success: 1, bogus: 4 } }) },
    { name: 'Tied', track_record: record({ lapsed: 2, kept: 4 }) },
    { name: 'OpenOnly', track_record: record({ open: 2 }) },
    { name: 'Nothing', track_record: record() },
    { name: 'Legacy' },
    { name: 'Junk', track_record: [1, 2] },
    { agent_id: 7, track_record: record({ broken: true, lapsed: -1, kept: 'x', released: 1.7 }) },
    null, 'junk'
  ])
  assert.deepEqual(rows.map((r) => r.actor), ['Breaker', 'Tied', 'Lapser', 'Clean', 'Agent 7', 'OpenOnly'])
  assert.deepEqual(rows[0], { actor: 'Breaker', kept: 0, lapsed: 1, broken: 1, released: 0, open: 0, resolved: 2,
    reliability: 0, outcomes: [{ outcome: 'success', count: 1 }, { outcome: 'blocked', count: 2 }] })
  assert.equal(rows[1].reliability, 4 / 6)                         // no reliability in the row → kept / resolved
  assert.equal(rows[2].reliability, 0.333)                         // the API's own figure when present
  assert.equal(rows[4].released, 1)                                // junk counts read as zero, fractions floor
  assert.equal(rows[4].reliability, null)                          // nothing resolved
  assert.deepEqual(trackRecordRows(null), [])
  assert.deepEqual(trackRecordRows([{ name: 'A' }]), [])
})

test('trackRecordSummary words a record and leaves zero buckets out', () => {
  const [breaker, opener] = trackRecordRows([
    { name: 'B', track_record: record({ kept: 1, broken: 1, lapsed: 1, released: 1, open: 2, outcomes: { success: 2, blocked: 1 } }) },
    { name: 'O', track_record: record({ open: 1 }) }
  ])
  assert.equal(trackRecordSummary(breaker),
    'kept 1 of 3 (33%) · 1 broken · 1 lapsed · 1 released · 2 open · moves: 2 succeeded, 1 blocked')
  assert.equal(trackRecordSummary(opener), '1 open')
  assert.equal(trackRecordSummary(breaker, {
    kept: '兑现 {k}/{n}', broken: '项违约', lapsed: '项失效', released: '项因对方违约解除', open: '项未到期',
    moves: '行动', success: '项成功', blocked: '项受阻', colon: '：', separator: '、'
  }), '兑现 1/3 (33%) · 1 项违约 · 1 项失效 · 1 项因对方违约解除 · 2 项未到期 · 行动：2 项成功、1 项受阻')
  assert.equal(trackRecordSummary(null), '')
})

test('eventKindLabel names a crossed red line and passes other kinds through', () => {
  assert.equal(eventKindLabel('red_line'), 'red line crossed')
  assert.equal(eventKindLabel('red_line', { red_line: '越过红线' }), '越过红线')
  assert.equal(eventKindLabel('emergent'), 'emergent')
  assert.equal(eventKindLabel('toString'), 'toString')                // never an inherited property
  assert.equal(eventKindLabel(null), '')
})

test('expectation counts come from the run summary, apart from the move score', () => {
  const vm = (behaviour) => summarizeWorldState({ committed_round: 2, history: [], summary: { behaviour } })
  assert.deepEqual(vm({ responsive_share: 0.5, moves: 2, expectations_checked: 5, expectations_reacted: 3 }).expectations,
    { checked: 5, reacted: 3 })
  // every actor held after the expectations were stated: no move score, the counts still show
  const held = vm({ responsive_share: null, moves: 0, expectations_checked: 2, expectations_reacted: 0 })
  assert.equal(held.behaviour, null)
  assert.deepEqual(held.expectations, { checked: 2, reacted: 0 })
  assert.deepEqual(vm({ expectations_checked: 2, expectations_reacted: 9 }).expectations, { checked: 2, reacted: 2 })
  assert.equal(vm({ expectations_checked: 0, expectations_reacted: 0 }).expectations, null)
  assert.equal(vm({ responsive_share: 0.5 }).expectations, null)    // runs from before the counts
  assert.equal(summarizeWorldState({ committed_round: 1 }).expectations, null)
})

test('track records describe the latest world; runs without them say so', () => {
  const vm = summarizeWorldState(reflexive())
  assert.equal(vm.trackRecordsAvailable, true)
  assert.deepEqual(vm.trackRecords.map((r) => [r.actor, r.kept, r.broken, r.released, r.resolved, r.reliability]), [
    ['United States Government', 0, 1, 0, 2, 0],
    ['China Ministry of Commerce', 0, 0, 1, 0, null]
  ])
  assert.deepEqual(vm.trackRecords[0].outcomes, [{ outcome: 'success', count: 1 }])
  assert.deepEqual(vm.expectations, { checked: 1, reacted: 1 })
  assert.deepEqual(summarizeWorldState(reflexive(), 1).trackRecords, vm.trackRecords)   // a past period: same rows
  const legacy = summarizeWorldState(fixture())
  assert.equal(legacy.trackRecordsAvailable, false)
  assert.deepEqual(legacy.trackRecords, [])
  assert.equal(legacy.expectations, null)
})

test('red lines lead the consequences, also when a past period falls back to its history row', () => {
  const crossing = "United States Government crossed China Ministry of Commerce's red line: No tariffs above 100% on Chinese goods"
  const inWindow = summarizeWorldState(reflexive(), 1)
  assert.equal(inWindow.eventsInWindow, true)
  assert.deepEqual(inWindow.consequences, [{ kind: 'red_line', description: `${crossing} — 145% announced` }])
  // the round's events left the API's recent-event window: the history row's red_lines_crossed stand in
  const data = reflexive()
  data.recent_events = data.recent_events.filter((e) => e.round > 2)
  const past = summarizeWorldState(data, 1)
  assert.equal(past.eventsInWindow, false)
  assert.deepEqual(past.consequences, [{ kind: 'red_line', description: crossing }])
  assert.deepEqual(summarizeWorldState(data, 2).consequences, [{ kind: 'effect', description: 'executive order' }])
  // within a period, a red line moves ahead of the other events and the rest keep their order
  const mixed = fixture()
  mixed.recent_events.push({ round: 2, kind: 'consequence', description: 'Ports slow' },
    { round: 2, kind: 'red_line', description: 'Actor0 crossed Actor1\'s red line: no tariffs' })
  assert.deepEqual(summarizeWorldState(mixed).consequences.map((c) => c.kind), ['red_line', 'emergent', 'consequence'])
  // junk crossings in a history row are skipped
  const junk = fixture()
  junk.recent_events = junk.recent_events.filter((e) => e.round === 2)
  junk.history[1].red_lines_crossed = ['junk', { actor: 'A', by: '', red_line: 'x' }, { actor: 'A', by: 'B', red_line: 'y' }]
  assert.deepEqual(summarizeWorldState(junk, 1).consequences[0], { kind: 'red_line', description: "B crossed A's red line: y" })
})
