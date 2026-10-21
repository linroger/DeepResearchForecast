import assert from 'node:assert/strict'
import test from 'node:test'
import {
  MAX_SOURCE_CONTEXT_ITEMS, MAX_SOURCE_CONTEXT_PROVIDERS,
  safeSourceContextUrl, sourceContextTimestamp, sourceContextView,
} from '../src/utils/sourceContext.js'

const item = (overrides = {}) => ({
  id: 'newsapi:one', provider: 'newsapi', kind: 'news_snippet', title: 'A source',
  url: 'https://publisher.example/story', published_at: null,
  retrieved_at: '2026-10-18T12:00:00Z', language: 'en', query: 'outlook',
  snippet: 'Stored source context.', eligibility: { context_only: true, anchor: false, resolution: false },
  ...overrides,
})
const context = (overrides = {}) => ({
  schema_version: 1, providers: { newsapi: { status: { state: 'ok', attempted: true } } },
  items: [item()], ...overrides,
})

test('only safe absolute HTTP(S) source URLs are linkable', () => {
  for (const url of [
    'javascript:alert(1)', 'JaVaScRiPt:alert(1)', 'data:text/html,<script>alert(1)</script>',
    '//evil.example', '/relative', 'file:///etc/passwd', 'https://user:secret@example.com',
    'https://example.com/\nscript', 'https://example.com/\tstory', 'https:\\evil.example',
    'https://', {}, null, 'https://example.com/' + 'a'.repeat(2048),
  ]) assert.equal(safeSourceContextUrl(url), '', String(url))
  assert.equal(safeSourceContextUrl(' HTTPS://Publisher.example/story?a=1&b=2 '), 'https://publisher.example/story?a=1&b=2')
  assert.equal(safeSourceContextUrl('http://publisher.example/story'), 'http://publisher.example/story')
})

test('timestamps have an explicit date/offset and unknowns are never guessed', () => {
  assert.equal(sourceContextTimestamp('2026-10-18T20:00:00+08:00'), '2026-10-18T12:00:00.000Z')
  assert.equal(sourceContextTimestamp('2026-10-18'), '2026-10-18')
  for (const value of [null, '', 'yesterday', '2026-10-18T12:00:00', '2026-02-30', '2026-02-30T12:00:00Z', '<img onerror=x>', 100]) {
    assert.equal(sourceContextTimestamp(value), '')
  }
})

test('legacy, missing, disabled and empty off carriers hide the whole view', () => {
  for (const payload of [null, undefined, {}, [], context({ schema_version: 2 }),
    context({ enabled: false }), context({ providers: {}, items: [] }),
    context({ providers: { newsapi: { state: 'disabled', attempted: false } }, items: [] }),
  ]) assert.equal(sourceContextView(payload).visible, false)
})

test('failed and partially available providers never become verified empty', () => {
  const providers = Object.fromEntries([
    'unavailable', 'forbidden', 'rate_limited', 'timeout', 'budget_exhausted', 'partial',
    'unsupported', 'verified_empty', 'disabled', 'ok',
  ].map(state => [state, { status: { state, attempted: state !== 'disabled' } }]))
  providers.missing = {}
  providers.unknown = { status: { state: 'new_state' } }
  const view = sourceContextView(context({ providers, items: [] }))
  assert.equal(view.visible, true)
  assert.equal(view.totalItems, 0)
  for (const [provider, value] of Object.entries(providers)) {
    assert.equal(view.providers.find(row => row.provider === provider).state, value.status?.state === 'new_state'
      ? 'unavailable' : value.status?.state || 'unavailable')
  }
  const noStatus = sourceContextView(context({ providers: null }))
  assert.deepEqual(noStatus.providers, [{ provider: 'newsapi', state: 'unavailable', attempted: null }])
})

test('context-only items are bounded and retain unknown timestamps and safe provenance', () => {
  const items = Array.from({ length: 20 }, (_, i) => item({ id: `newsapi:${i}`, title: `Item ${i}` }))
  items.push(item({ eligibility: { context_only: false } }), item({ eligibility: null }), null)
  const view = sourceContextView(context({ items }))
  assert.equal(view.totalItems, 20)
  assert.equal(view.items.length, MAX_SOURCE_CONTEXT_ITEMS)
  assert.equal(view.items.at(-1).title, 'Item 11')
  assert.equal(view.items[0].publishedAt, '')
  assert.equal(view.items[0].retrievedAt, '2026-10-18T12:00:00.000Z')
  assert.equal(sourceContextView(context({ items }), 100).items.length, 12)
  assert.equal(sourceContextView(context({ items }), 3).items.length, 3)
  assert.equal(sourceContextView(context({ items }), NaN).items.length, 12)
  const huge = sourceContextView(context({ items: [item({ title: 't'.repeat(1000), snippet: 's'.repeat(3000) })] }))
  assert.equal(huge.items[0].title.length, 320)
  assert.equal(huge.items[0].snippet.length, 1200)
})

test('provider statuses are bounded independently of the item list', () => {
  const providers = Object.fromEntries(Array.from({ length: 30 }, (_, i) => [`provider${i}`, { state: 'unavailable' }]))
  const view = sourceContextView(context({ providers, items: [] }))
  assert.equal(view.providers.length, MAX_SOURCE_CONTEXT_PROVIDERS)
  assert.equal(view.hiddenProviders, 6)
})

test('quotes preserve basis, units and zero values without inferring probabilities', () => {
  const items = [
    item({ kind: 'market_quote', quote_basis: 'Yes order book', quote_units: 'USD per contract',
      bid: 0, ask: 0.42, last: 0.4, probability: 0.99 }),
    item({ kind: 'market_quote', quote: { quote_basis: 'Last trade', units: 'cents', bid: NaN, ask: Infinity, last: 42 } }),
    item({ kind: 'social_post', bid: 0.9, probability: 0.95, sentiment: 0.8 }),
    item({ kind: 'community_forecast', forecaster_count: 91, bid: 0.5, probability: 0.4 }),
  ]
  const view = sourceContextView(context({ items }))
  assert.equal(view.items[0].bid, '0')
  assert.equal(view.items[0].ask, '0.42')
  assert.equal(view.items[0].basis, 'Yes order book')
  assert.equal(view.items[0].units, 'USD per contract')
  assert.equal(view.items[1].bid, '')
  assert.equal(view.items[1].ask, '')
  assert.equal(view.items[1].last, '42')
  assert.equal(view.items[2].bid, '')
  assert.equal(view.items[3].forecasters, '91')
  assert.ok(view.items.every(row => !('probability' in row) && !('sentiment' in row)))
})

test('literal-Yes market aliases preserve supplied values, including null and zero', () => {
  const view = sourceContextView(context({ items: [
    item({ provider: 'kalshi', kind: 'market_quote', yes_bid: 0, yes_ask: 0.44, last_price: 0.43,
      price_unit: 'USD_per_contract', quote_basis: 'provider_reported_dollars_per_contract', outcome: 'Yes', quote_at: null }),
    item({ kind: 'market_quote', yes_bid: null, bid: 0.9, yes_ask: null, ask: 0.9, last_price: null, last: 0.9 }),
  ] }))
  assert.equal(view.items[0].bid, '0')
  assert.equal(view.items[0].ask, '0.44')
  assert.equal(view.items[0].last, '0.43')
  assert.equal(view.items[0].units, 'USD_per_contract')
  assert.equal(view.items[0].outcome, 'Yes')
  assert.equal(view.items[0].quoteAt, '')
  assert.equal(view.items[1].bid, '')
  assert.equal(view.items[1].ask, '')
  assert.equal(view.items[1].last, '')
})

test('native settlement rules, horizons and thresholds stay supplied evidence', () => {
  const original = context({ items: [item({ kind: 'market_quote', rules_primary: 'Use the official release.',
    rules_secondary: 'Apply the stated revision rule.', end_date: '2027-12-31T23:59:59Z',
    strike_type: 'greater', floor_strike: 0, cap_strike: null,
    probability_basis: 'last_price_dollars/1_USD_binary_payout' })] })
  const before = JSON.stringify(original)
  const row = sourceContextView(original).items[0]
  assert.equal(row.rulesPrimary, 'Use the official release.')
  assert.equal(row.rulesSecondary, 'Apply the stated revision rule.')
  assert.equal(row.floorStrike, '0')
  assert.equal(row.capStrike, '')
  assert.equal(row.endAt, '2027-12-31T23:59:59.000Z')
  assert.equal(row.probabilityBasis, 'last_price_dollars/1_USD_binary_payout')
  assert.equal(JSON.stringify(original), before)
})
