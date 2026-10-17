import test from 'node:test'
import assert from 'node:assert/strict'

import {
  agencyLabel,
  decisionsSummary,
  formatWorldValue,
  headlineSummary,
  latestHistoryRound,
  latestHistoryRow,
  nextSelectedRound,
  resolveSelectedRound,
  summarizeWorldState,
  variableDelta
} from '../src/utils/worldState.js'

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
