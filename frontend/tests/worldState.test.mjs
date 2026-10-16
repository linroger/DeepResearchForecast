import test from 'node:test'
import assert from 'node:assert/strict'

import {
  agencyLabel,
  formatWorldValue,
  latestHistoryRow,
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
})

test('summarizeWorldState builds the panel view model', () => {
  const vm = summarizeWorldState({
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
      { round: 2, period_label: '2026-Q4', headline: 'h2', narrative: 'Shock.', arbiter_status: 'applied',
        decisions: { total: 3 }, diff: { variables_changed: [{ id: 'tariff' }], relationships_changed: [{ source: 'Actor0', target: 'Actor1', to: 'adversarial', direction: 'farther' }] } },
      { round: 1, period_label: '2026-Q3', headline: 'h1', arbiter_status: 'failed', diff: {} }
    ]
  })
  assert.equal(vm.committedRound, 2)
  assert.equal(vm.periodLabel, '2026-Q4')
  assert.equal(vm.headline, '2026-Q4: 3 decisions')
  assert.equal(vm.narrative, 'Shock.')
  assert.equal(vm.arbiterStatus, 'applied')
  assert.equal(vm.arbiterFailedRounds, 1)
  // changed variables sort first and carry a readable delta
  assert.equal(vm.variables[0].name, 'Tariff rate')
  assert.equal(vm.variables[0].deltaDisplay, '10% → 25%')
  assert.equal(vm.variables[1].display, 'pending')
  assert.equal(vm.variables[1].deltaDisplay, '')
  // moves of the committed round only, holds excluded
  assert.deepEqual(vm.moves, [{ actor: 'Actor0', description: 'Impose tariff → Actor1', statement: 'Tariff raised', targets: ['Actor1'] }])
  assert.deepEqual(vm.consequences, [{ kind: 'emergent', description: 'Importers protest' }])
  assert.deepEqual(vm.relationshipChanges, [{ source: 'Actor0', target: 'Actor1', to: 'adversarial', direction: 'farther' }])
  assert.deepEqual(vm.pending, [
    { actor: 'Actor0', description: 'Publish schedule', dueRound: 3, status: 'due' },
    { actor: 'Expected', description: 'Importers relocate', dueRound: 4, status: 'effect' }
  ])
  assert.deepEqual(vm.history.map((h) => [h.round, h.label, h.arbiterStatus, h.factsChanged]),
    [[1, '2026-Q3', 'failed', 0], [2, '2026-Q4', 'applied', 1]])
})

test('summarizeWorldState is defensive', () => {
  const vm = summarizeWorldState(null)
  assert.equal(vm.committedRound, 0)
  assert.deepEqual(vm.variables, [])
  assert.deepEqual(vm.moves, [])
  assert.equal(vm.headline, '')
  assert.equal(agencyLabel('sovereign_government'), 'sovereign government')
  assert.equal(agencyLabel(null), '')
})
