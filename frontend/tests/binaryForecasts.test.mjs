import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  binaryForecastRow,
  binaryForecastRows,
  confidenceLevel,
  formatDivergence,
  formatProbability,
  safeMarketUrl,
} from '../src/utils/binaryForecasts.js'
import { officialSeriesIndex } from '../src/utils/officialData.js'

// REAL payloads: forecast.json binaries (GET /api/report/<id>/forecast) and the same
// report's GET /api/report/<id>/official-data, from a real-bundle publication.
const fixture = name => JSON.parse(readFileSync(new URL(`./fixtures/official/${name}`, import.meta.url), 'utf8'))
const realForecast = fixture('binary_forecasts.en_report.json')
const officialSeries = officialSeriesIndex(fixture('official_data.en_report.en.json').data)

test('formatProbability renders one-decimal percentages and rejects non-numbers', () => {
  assert.equal(formatProbability(0.623), '62.3%')
  assert.equal(formatProbability(0), '0%')
  assert.equal(formatProbability(1), '100%')
  assert.equal(formatProbability('0.5'), '50%')
  assert.equal(formatProbability(''), '')
  assert.equal(formatProbability('nope'), '')
  assert.equal(formatProbability(null), '')
  assert.equal(formatProbability(true), '')
  assert.equal(formatProbability([]), '')
})

test('formatDivergence carries sign text and a tone that matches the rounded value', () => {
  assert.deepEqual(formatDivergence(0.123), { text: '+12.3pp', tone: 'pos' })
  assert.deepEqual(formatDivergence(-0.08), { text: '-8pp', tone: 'neg' })
  assert.deepEqual(formatDivergence(0), { text: '0pp', tone: 'zero' })
  // rounds to zero → text and tone agree (never '+0pp' colored positive)
  assert.deepEqual(formatDivergence(0.0004), { text: '0pp', tone: 'zero' })
  assert.equal(formatDivergence('n/a'), null)
  assert.equal(formatDivergence(undefined), null)
})

test('safeMarketUrl accepts only absolute http(s) URLs', () => {
  assert.equal(safeMarketUrl('https://polymarket.com/event/x'), 'https://polymarket.com/event/x')
  assert.equal(safeMarketUrl('  http://example.com/m  '), 'http://example.com/m')
  assert.equal(safeMarketUrl('javascript:alert(1)'), '')
  assert.equal(safeMarketUrl('ftp://example.com'), '')
  assert.equal(safeMarketUrl('/relative/path'), '')
  assert.equal(safeMarketUrl(42), '')
})

test('confidenceLevel normalizes known levels and flags unknown values', () => {
  assert.equal(confidenceLevel('High'), 'high')
  assert.equal(confidenceLevel(' medium '), 'medium')
  assert.equal(confidenceLevel('low'), 'low')
  assert.equal(confidenceLevel('speculative'), 'other')
  assert.equal(confidenceLevel(''), '')
  assert.equal(confidenceLevel(undefined), '')
})

test('builds a fully-populated row from a rich binary forecast', () => {
  const row = binaryForecastRow({
    id: 'b1',
    statement: 'BTC closes above $100k by 2026-12-31',
    probability: 0.62,
    confidence: 'High',
    adjustment_rationale: 'Base rate anchored to halving-cycle history.',
    p_low: 0.55,
    p_high: 0.7,
    interval_source: 'self_consistency_spread',
    market_anchor: {
      market_id: 'mkt-9',
      question: 'Will BTC close above $100k in 2026?',
      implied_yes_prob: 0.48,
      price_at_research: 0.48,
      divergence: 0.14,
      resolution_equivalence: 'Near',
      match_confidence: 0.85,
      url: 'https://polymarket.com/event/btc-100k',
      endDate: '2026-12-31',
    },
    market_influence: {
      market_id: 'mkt-9',
      market_question: 'Will BTC close above $100k in 2026?',
      prior_probability: 0.7,
      revised_probability: 0.62,
      anchor_removed: false,
      probability_restored: false,
    },
  }, 0)
  assert.equal(row.key, 'b1-0')
  assert.equal(row.statement, 'BTC closes above $100k by 2026-12-31')
  assert.equal(row.probabilityText, '62%')
  assert.deepEqual(row.interval, {
    lowText: '55%',
    highText: '70%',
    text: '55%–70%',
    source: 'self_consistency_spread',
  })
  assert.equal(row.confidenceLevel, 'high')
  assert.equal(row.rationale, 'Base rate anchored to halving-cycle history.')
  assert.equal(row.anchor.marketId, 'mkt-9')
  assert.equal(row.anchor.impliedText, '48%')
  assert.deepEqual(row.anchor.divergence, { text: '+14pp', tone: 'pos' })
  assert.equal(row.anchor.url, 'https://polymarket.com/event/btc-100k')
  assert.equal(row.anchor.equivalence, 'near')
  assert.equal(row.anchor.matchConfidenceText, '0.85')
  assert.equal(row.anchor.endDate, '2026-12-31')
  assert.equal(row.influence.priorText, '70%')
  assert.equal(row.influence.revisedText, '62%')
  assert.equal(row.influence.anchorRemoved, false)
  assert.equal(row.influence.probabilityRestored, false)
})

test('renders nothing when no binary forecasts exist', () => {
  assert.deepEqual(binaryForecastRows(null), [])
  assert.deepEqual(binaryForecastRows(undefined), [])
  assert.deepEqual(binaryForecastRows({}), [])
  assert.deepEqual(binaryForecastRows({ binary_forecasts: [] }), [])
  assert.deepEqual(binaryForecastRows({ binary_forecasts: 'not-a-list' }), [])
  assert.deepEqual(binaryForecastRows([]), [])
})

test('skips entries without a usable statement and non-object entries', () => {
  const rows = binaryForecastRows({
    binary_forecasts: [
      { probability: 0.5 },
      { statement: '   ' },
      'just a string',
      null,
      ['nested'],
      { statement: 'Kept', probability: 0.3 },
    ],
  })
  assert.equal(rows.length, 1)
  assert.equal(rows[0].statement, 'Kept')
})

test('minimal row degrades per field: no anchor, influence, interval or confidence', () => {
  const row = binaryForecastRow({ statement: 'Sparse claim' }, 3)
  assert.equal(row.key, 'bf-3')
  assert.equal(row.id, '')
  assert.equal(row.probabilityText, '—')
  assert.equal(row.interval, null)
  assert.equal(row.confidenceLevel, '')
  assert.equal(row.anchor, null)
  assert.equal(row.influence, null)
  assert.equal(row.dataAnchor, null)
})

test('interval requires ordered bounds inside [0,1]', () => {
  const base = { statement: 'S', probability: 0.4 }
  assert.equal(binaryForecastRow({ ...base, p_low: 0.5, p_high: 0.3 }, 0).interval, null)
  assert.equal(binaryForecastRow({ ...base, p_low: -0.1, p_high: 0.5 }, 0).interval, null)
  assert.equal(binaryForecastRow({ ...base, p_low: 0.2, p_high: 1.2 }, 0).interval, null)
  assert.equal(binaryForecastRow({ ...base, p_low: 0.2 }, 0).interval, null)
  const untagged = binaryForecastRow({ ...base, p_low: 0.3, p_high: 0.5 }, 0).interval
  assert.deepEqual(untagged, { lowText: '30%', highText: '50%', text: '30%–50%', source: '' })
})

test('anchor sanitizes unsafe URLs and drops undisplayable anchors', () => {
  const unsafe = binaryForecastRow({
    statement: 'S',
    market_anchor: { market_id: 'm1', implied_yes_prob: 0.4, url: 'javascript:alert(1)' },
  }, 0)
  assert.equal(unsafe.anchor.url, '')
  assert.equal(unsafe.anchor.impliedText, '40%')
  // market_id only (implied price missing) is still displayable — em-dash implied
  const idOnly = binaryForecastRow({
    statement: 'S',
    market_anchor: { market_id: 'm2' },
  }, 0)
  assert.equal(idOnly.anchor.impliedText, '—')
  assert.equal(idOnly.anchor.divergence, null)
  // an empty anchor object carries nothing displayable → dropped
  assert.equal(binaryForecastRow({ statement: 'S', market_anchor: {} }, 0).anchor, null)
  assert.equal(binaryForecastRow({ statement: 'S', market_anchor: 'mkt' }, 0).anchor, null)
})

test('influence badge survives anchor ejection and reports its audit state', () => {
  const row = binaryForecastRow({
    statement: 'S',
    probability: 0.55,
    market_influence: {
      market_id: 'm3',
      prior_probability: 0.55,
      revised_probability: 0.42,
      anchor_removed: true,
      probability_restored: true,
    },
  }, 0)
  assert.equal(row.anchor, null)
  assert.equal(row.influence.priorText, '55%')
  assert.equal(row.influence.revisedText, '42%')
  assert.equal(row.influence.anchorRemoved, true)
  assert.equal(row.influence.probabilityRestored, true)
})

test('influence with missing numeric fields falls back to em-dashes', () => {
  const row = binaryForecastRow({
    statement: 'S',
    market_influence: { market_id: 'm4', market_question: 'Q?' },
  }, 0)
  assert.equal(row.influence.priorText, '—')
  assert.equal(row.influence.revisedText, '—')
  assert.equal(row.influence.anchorRemoved, false)
  assert.equal(row.influence.probabilityRestored, false)
  assert.equal(row.influence.marketQuestion, 'Q?')
})

test('row keys stay unique even when payload ids collide', () => {
  const rows = binaryForecastRows({
    binary_forecasts: [
      { id: 'dup', statement: 'A' },
      { id: 'dup', statement: 'B' },
    ],
  })
  assert.deepEqual(rows.map(r => r.key), ['dup-0', 'dup-1'])
})

test('data anchor: threshold, period, latest vs threshold and empirical base rate (real forecast)', () => {
  const rows = binaryForecastRows(realForecast, { officialSeries, lang: 'en' })
  assert.equal(rows.length, 10)
  assert.equal(rows.filter(row => row.dataAnchor).length, 9)
  const f1 = rows[0].dataAnchor
  assert.equal(f1.series, 'fred:UNRATE')
  assert.equal(f1.label, 'Unemployment Rate — United States')
  assert.equal(f1.sourceId, 'S1')
  assert.equal(f1.sourceUrl, 'https://fred.stlouisfed.org/series/UNRATE')
  assert.equal(f1.comparatorText, '≥')
  assert.equal(f1.thresholdText, '4.5%')
  assert.equal(f1.periodText, '2027-06')
  assert.equal(f1.latestText, '4.2%')
  assert.equal(f1.latestPeriod, '2026-09')
  assert.equal(f1.gapText, '+0.3 pp')
  assert.equal(f1.met, false)
  assert.deepEqual(f1.baseRate, {
    pText: '30.5%',
    n: 82,
    h: 9,
    windowText: '2019-01 – 2026-09',
    sigmaText: '0.11',
    rangeText: '2.11% – 6.35%',
    medianText: '4.2%',
    seasonalBasis: '',
    divergence: { text: '+24.5pp', tone: 'pos' },
    divergent: false,
  })

  // '<=' against a 'Per cent per year' BIS series: percent formatting, negative gap.
  const f9 = rows[8].dataAnchor
  assert.equal(f9.series, 'bis:WS_CBPOL/M.US')
  assert.equal(f9.sourceId, 'S7')
  assert.equal(f9.comparatorText, '≤')
  assert.equal(f9.thresholdText, '3%')
  assert.equal(f9.latestText, '3.875%')
  assert.equal(f9.gapText, '-0.875 pp')
  assert.equal(f9.met, false)
  // model 0.8 vs empirical 0.2051 → flagged like binary_quality.base_rate_divergence.
  const f10 = rows[9].dataAnchor
  assert.deepEqual(f10.baseRate.divergence, { text: '+59.5pp', tone: 'pos' })
  assert.equal(f10.baseRate.divergent, true)

  // 'Percentage Points' units are levels, not percents.
  const f4 = rows[3].dataAnchor
  assert.equal(f4.thresholdText, '0.5')
  assert.equal(f4.latestText, '0')
  assert.equal(f4.gapText, '+0.5')
  assert.equal(f4.percentUnits, false)

  // No empirical base rate when the history cannot support 30 h-step samples.
  const f8 = rows[7].dataAnchor
  assert.equal(f8.baseRate, null)
  assert.equal(f8.latestText, '4.989%')
  assert.equal(f8.met, false)
  assert.equal(rows[6].dataAnchor, null)
})

test('data anchor degrades without the report series index and on malformed anchors', () => {
  const [row] = binaryForecastRows({ binary_forecasts: [realForecast.binary_forecasts[0]] })
  assert.equal(row.dataAnchor.label, 'fred:UNRATE')
  assert.equal(row.dataAnchor.sourceId, '')
  assert.equal(row.dataAnchor.sourceUrl, 'https://fred.stlouisfed.org/series/UNRATE')

  const anchor = realForecast.binary_forecasts[0].data_anchor
  const variant = changes => binaryForecastRow(
    { statement: 's', probability: 0.5, data_anchor: { ...anchor, ...changes } },
  ).dataAnchor
  assert.equal(variant({ comparator: '==' }), null)
  assert.equal(variant({ threshold: 'high' }), null)
  assert.equal(variant({ series: '' }), null)
  const pending = variant({ latest_value: null, latest_date: '', empirical_base_rate: { p: 1.4 } })
  assert.equal(pending.latestText, '')
  assert.equal(pending.gapText, '')
  assert.equal(pending.met, null)
  assert.equal(pending.baseRate, null)
  assert.equal(variant({ source_url: 'javascript:alert(1)' }).sourceUrl, '')
  // Already satisfied today: the latest value meets the comparison.
  const met = variant({ comparator: '<=', threshold: 4.2 })
  assert.equal(met.met, true)
  assert.equal(met.gapText, '0 pp')
  // Trillion-dollar thresholds carry the magnitude companion (zh wording in zh).
  const debt = binaryForecastRow({
    statement: 'Debt above $45tn',
    probability: 0.4,
    data_anchor: {
      series: 'usgov:treasury/debt_to_penny', comparator: '>', threshold: 45e12,
      units: 'U.S. dollars', frequency: 'M', period: '2027-12-01',
      latest_value: 40093219044989.21, latest_date: '2026-09-01',
    },
  }, 0, { lang: 'zh' }).dataAnchor
  assert.equal(debt.thresholdText, '45000000000000 (≈45万亿美元)')
  const zhPercent = binaryForecastRow(realForecast.binary_forecasts[0], 0, { officialSeries, lang: 'zh' }).dataAnchor
  assert.equal(zhPercent.gapText, '+0.3 个百分点')
  // Same text as data_sources.format_change(45e12 - 40093219044989.21, 'U.S. dollars').
  assert.equal(debt.gapText, '+4906780955010.789')
})

test('a fiscal-year anchor reads its FY label like the report tables and settlement sentence', () => {
  // Real backend output for the replayed USAspending capture (annual US federal fiscal years
  // dated at their 1 October start): forecast_extractor.official_anchor_period_text reads
  // 2026-10-01 as FY2027 (a stored, partial fiscal year) and 2027-10-01 as FY2028 (not stored
  // yet: the data layer's FY<start year + 1> rule); the criteria say 'for FY2027' / 'for FY2028'.
  const forecast = fixture('binary_forecasts.usaspending_fy.json')
  const series = officialSeriesIndex(fixture('official_data.usaspending_fy.en.json').data)
  const [stored, ahead] = binaryForecastRows(forecast, { officialSeries: series })
  assert.ok(forecast.binary_forecasts[0].resolution_criteria.endsWith('for FY2027.'))
  assert.equal(stored.dataAnchor.periodText, 'FY2027')
  assert.ok(forecast.binary_forecasts[1].resolution_criteria.endsWith('for FY2028.'))
  assert.equal(ahead.dataAnchor.periodText, 'FY2028')
  assert.equal(stored.dataAnchor.label, 'USAspending: Federal Award Spending by Fiscal Year — United States')
  // Without the report's stored carrier the calendar year of the period date is all there is.
  assert.equal(binaryForecastRows(forecast)[0].dataAnchor.periodText, '2026')
  // Calendar-year series are unaffected.
  assert.equal(binaryForecastRows(realForecast, { officialSeries })[0].dataAnchor.periodText, '2027-06')
})

test('base-rate divergence is flagged exactly like binary_quality at the 25pp boundary', () => {
  // forecast_extractor._binary_quality flags abs(round(probability - p, 4)) > 0.25. Expected
  // flags were produced by that function for these pairs: 0.3 - 0.55 is -0.25000000000000006
  // in binary floating point, which rounds to -0.25 and is NOT flagged by the backend.
  const anchor = realForecast.binary_forecasts[0].data_anchor
  const flagged = (probability, p) => binaryForecastRow({
    statement: 's',
    probability,
    data_anchor: { ...anchor, empirical_base_rate: { ...anchor.empirical_base_rate, p } },
  }).dataAnchor.baseRate
  for (const [probability, p, expected, text] of [
    [0.3, 0.55, false, '-25pp'],
    [0.8, 0.55, false, '+25pp'],
    [0.75, 0.5, false, '+25pp'],
    [0.81, 0.55, true, '+26pp'],
    [0.7501, 0.5, true, '+25pp'],
  ]) {
    const baseRate = flagged(probability, p)
    assert.equal(baseRate.divergent, expected, `${probability} vs ${p}`)
    assert.equal(baseRate.divergence.text, text, `${probability} vs ${p}`)
  }
})

test('a base rate that pools the seasons is disclosed and never flagged, like binary_quality', () => {
  // Real forecast_extractor._normalize_binaries output for the committed real v3 carrier
  // (Monthly Treasury Statement balance, 72 NSA monthly observations to 2026-08): August
  // starts give too few 13-step changes for a same-month sample or a seasonal profile, so
  // the rate pools every start month and records seasonal_basis 'all_start_months'.
  // binary_quality does not flag it (a pooled-season rate is no yardstick), although the
  // model's 60% is 36 pp above the empirical 24%.
  const pooled = fixture('binary_forecast.mts_nsa_pooled.json')
  const [row] = binaryForecastRows(pooled)
  const base = row.dataAnchor.baseRate
  assert.equal(base.seasonalBasis, 'all_start_months')
  assert.equal(base.pText, '23.7%')
  assert.equal(base.n, 59)
  assert.equal(base.h, 13)
  assert.deepEqual(base.divergence, { text: '+36.3pp', tone: 'pos' })
  assert.equal(base.divergent, false)

  // A same-calendar-month sample is still a yardstick: disclosed and flagged.
  const raw = pooled.binary_forecasts[0]
  const withBasis = basis => binaryForecastRow({
    ...raw,
    data_anchor: { ...raw.data_anchor, empirical_base_rate: { ...raw.data_anchor.empirical_base_rate, seasonal_basis: basis } },
  }).dataAnchor.baseRate
  assert.equal(withBasis('same_calendar_month').seasonalBasis, 'same_calendar_month')
  assert.equal(withBasis('same_calendar_month').divergent, true)
  // Plain pooled samples (no basis) and unknown values carry no disclosure.
  assert.equal(withBasis(undefined).seasonalBasis, '')
  assert.equal(withBasis(undefined).divergent, true)
  assert.equal(withBasis('bogus').seasonalBasis, '')
})

test('a seasonal-profile base rate is disclosed and still flagged, like binary_quality', () => {
  // Real forecast_extractor._normalize_binaries output for the same EIA carrier under the
  // seasonal-basis contract: too few July starts for a same-month sample, so the sample is
  // the July seasonal mean plus the pooled deviations (seasonal_basis 'seasonal_profile').
  // binary_quality flags it: the model's 40% is 40 pp above the empirical 0%.
  const profile = fixture('binary_forecast.eia_nsa_profile.json')
  const [row] = binaryForecastRows(profile)
  const base = row.dataAnchor.baseRate
  assert.equal(base.seasonalBasis, 'seasonal_profile')
  assert.equal(base.pText, '0%')
  assert.equal(base.n, 112)
  assert.equal(base.h, 5)
  assert.deepEqual(base.divergence, { text: '+40pp', tone: 'pos' })
  assert.equal(base.divergent, true)

  // The 25 pp flag is OFF only for a rate that pools the start months.
  const raw = profile.binary_forecasts[0]
  for (const [basis, flagged] of [
    [undefined, true],
    ['same_calendar_month', true],
    ['seasonal_profile', true],
    ['all_start_months', false],
  ]) {
    const variant = binaryForecastRow({
      ...raw,
      data_anchor: { ...raw.data_anchor, empirical_base_rate: { ...raw.data_anchor.empirical_base_rate, seasonal_basis: basis } },
    }).dataAnchor.baseRate
    assert.equal(variant.divergent, flagged, String(basis))
    assert.equal(variant.seasonalBasis, basis || '', String(basis))
  }
})
