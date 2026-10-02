import assert from 'node:assert/strict'
import test from 'node:test'

import { marketLookupIncomplete } from '../src/utils/marketStatus.js'

test('a failed, partial or timed-out lookup is incomplete (empty_reason or merge state)', () => {
  assert.equal(marketLookupIncomplete({ empty_reason: 'transport_failure' }), true)
  assert.equal(marketLookupIncomplete({ empty_reason: 'partial_transport_failure' }), true)
  assert.equal(marketLookupIncomplete({ empty_reason: 'inflight_timeout' }), true)
  // Legacy pair: before FU-6 the multi-track merge could store state 'inflight_timeout' beside
  // empty_reason 'no_equivalent_market'; it must still read as incomplete.
  assert.equal(marketLookupIncomplete({ state: 'inflight_timeout', empty_reason: 'no_equivalent_market' }), true)
  assert.equal(marketLookupIncomplete({ state: 'partial_transport_failure' }), true)
  assert.equal(marketLookupIncomplete({ empty_reason: ' Partial_Transport_Failure ' }), true)
})

test('a completed search that found nothing relevant is not incomplete', () => {
  assert.equal(marketLookupIncomplete({ empty_reason: 'no_equivalent_market' }), false)
  assert.equal(marketLookupIncomplete({ state: 'verified_empty', empty_reason: 'no_equivalent_market' }), false)
  assert.equal(marketLookupIncomplete({ empty_reason: 'all_candidates_irrelevant' }), false)
  assert.equal(marketLookupIncomplete({ empty_reason: 'no_derivable_queries' }), false)
})

test('a missing or malformed status is not incomplete', () => {
  assert.equal(marketLookupIncomplete(null), false)
  assert.equal(marketLookupIncomplete(undefined), false)
  assert.equal(marketLookupIncomplete('transport_failure'), false)
  assert.equal(marketLookupIncomplete(['transport_failure']), false)
  assert.equal(marketLookupIncomplete({}), false)
})
