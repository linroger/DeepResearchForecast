import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  dataSourceProbeRows,
  datasetManifestRows,
  distinctSeriesNames,
  formatOfficialChange,
  formatOfficialDisplay,
  formatOfficialValue,
  isPercentUnits,
  officialAnchorPeriodLabel,
  officialCsvFilename,
  officialFrequencyLabel,
  officialIndicatorTile,
  officialIndicatorTiles,
  officialKindLabel,
  officialPeriodLabel,
  officialSeriesCsv,
  officialSeriesIndex,
  roundHalfEven,
  safeSourceUrl,
  scaledOfficialValue,
  sparklineGeometry,
} from '../src/utils/officialData.js'

// REAL payloads: GET /api/report/<id>/official-data (en/zh), research data/datasets.json
// via GET /api/research/<pid>/artifact/datasets, and a live POST
// /api/settings/data-sources/test response (see fixtures/official/README.md).
const fixture = name => JSON.parse(readFileSync(new URL(`./fixtures/official/${name}`, import.meta.url), 'utf8'))
const officialEn = fixture('official_data.en_report.en.json').data
const officialZh = fixture('official_data.en_report.zh.json').data
const datasets = fixture('datasets_manifest.v3_run.json').data.content
const fiscalDatasets = fixture('datasets_manifest.usaspending_fy.json').data.content
const probe = fixture('data_sources_probe.live.json').data
// The exact body of a live POST /api/settings/data-sources/test through the Flask route
// (2026-10-12; Flask sorts JSON keys, so providers arrive alphabetically).
const endpointProbe = fixture('data_sources_probe.endpoint.json').data

// Expected strings computed by deerflow_bridge/data_sources.py (format_value,
// format_change, scaled_value) for the same inputs, including exact binary ties.
const PYTHON_CASES = [
  [3.8125, 'Percent', '3.812%', '+3.812 pp', '-3.812 pp', '', ''],
  [0.0625, 'Percent', '0.062%', '+0.062 pp', '-0.062 pp', '', ''],
  [2.5, 'Per cent per year', '2.5%', '+2.5 pp', '-2.5 pp', '', ''],
  [-0.0001, 'Percent', '0%', '0 pp', '0 pp', '', ''],
  [0, 'Percentage Points', '0', '0', '0', '', ''],
  [0.5, 'Percentage Points', '0.5', '+0.5', '-0.5', '', ''],
  [40093219044989.21, 'U.S. dollars', '40093219044989.21', '+40093219044989.21', '-40093219044989.21',
    '≈ 40.09 trillion U.S. dollars', '≈40.09万亿美元'],
  [24408.011, 'Billions of Chained 2017 Dollars', '24408.011', '+24408.011', '-24408.011', '', ''],
  [0.8961904761904762, 'Percent', '0.896%', '+0.896 pp', '-0.896 pp', '', ''],
  [12345.67845, 'Index', '12345.6784', '+12345.6784', '-12345.6784', '', ''],
  [0.000123456, 'Index', '0.0001235', '+0.0001235', '-0.0001235', '', ''],
  [1e-13, 'Index', '0', '0', '0', '', ''],
  [-166796952277.38, 'U.S. dollars', '-166796952277.38', '-166796952277.38', '+166796952277.38',
    '≈ -166.8 billion U.S. dollars', '≈-1667.97亿美元'],
  [2.5, 'Index', '2.5', '+2.5', '-2.5', '', ''],
  [0.00125, 'Ratio', '0.00125', '+0.00125', '-0.00125', '', ''],
  [1234567.5, 'Thousands of Persons', '1234567.5', '+1234567.5', '-1234567.5', '', ''],
  [7.25, 'Index 2017=100', '7.25', '+7.25', '-7.25', '', ''],
  [100, 'Index 1982-1984=100', '100', '+100', '-100', '', ''],
  [45e12, 'U.S. dollars', '45000000000000', '+45000000000000', '-45000000000000',
    '≈ 45 trillion U.S. dollars', '≈45万亿美元'],
  [1.5e9, 'Number', '1500000000', '+1500000000', '-1500000000', '≈ 1.5 billion', '≈15亿'],
]

test('formatters match the Python data layer byte for byte, including half-even ties', () => {
  for (const [value, units, text, up, down, scaledEn, scaledZh] of PYTHON_CASES) {
    assert.equal(formatOfficialValue(value, units), text, `${value} ${units}`)
    assert.equal(formatOfficialChange(value, units), up, `+${value} ${units}`)
    assert.equal(formatOfficialChange(-value, units), down, `-${value} ${units}`)
    assert.equal(scaledOfficialValue(value, units, 'en'), scaledEn, `scaled ${value}`)
    assert.equal(scaledOfficialValue(value, units, 'zh'), scaledZh, `scaled zh ${value}`)
  }
})

test('roundHalfEven mirrors Python round() on the exact binary value', () => {
  // Expected values printed by CPython round(x, digits) for the same floats.
  for (const [value, digits, expected] of [
    [-0.25000000000000006, 4, -0.25],
    [2.675, 2, 2.67],
    [0.125, 2, 0.12],
    [0.375, 2, 0.38],
    [0.00125, 4, 0.0013],
    [-0.00005, 4, -0.0001],
    [0.26000000000000006, 4, 0.26],
  ]) {
    assert.equal(roundHalfEven(value, digits), expected, `${value} ${digits}`)
  }
})

test('formatters reject non-numeric input instead of rendering a number', () => {
  for (const bad of [null, undefined, '', 'n/a', true, NaN, Infinity, [], {}]) {
    assert.equal(formatOfficialValue(bad, 'Percent'), '')
    assert.equal(formatOfficialChange(bad, 'Percent'), '')
    assert.equal(formatOfficialDisplay(bad, 'U.S. dollars'), '')
  }
  assert.equal(formatOfficialValue('4.25', 'Percent'), '4.25%')
  assert.equal(isPercentUnits('Percentage Points'), false)
  assert.equal(isPercentUnits('Per cent per year'), true)
})

test('every display string the real report API returns is reproduced by the frontend formatters', () => {
  for (const [payload, lang] of [[officialEn, 'en'], [officialZh, 'zh']]) {
    assert.equal(payload.indicators.length, 12)
    for (const row of payload.indicators) {
      const points = [row.latest, row.previous_year, row.publisher_value,
        row.five_year && row.five_year.min, row.five_year && row.five_year.max].filter(Boolean)
      for (const point of points) {
        assert.equal(formatOfficialDisplay(point.value, row.units, lang), point.display, `${row.series} ${point.date}`)
        assert.equal(officialPeriodLabel(point.date, row.frequency), point.period)
      }
      if (row.change && lang === 'en') {
        const own = formatOfficialChange(row.change.value, row.units)
        assert.equal(isPercentUnits(row.units) ? row.change.display : row.change.display.split(' (')[0], own,
          `${row.series} change`)
      }
      assert.equal(officialFrequencyLabel(row.frequency, lang), row.frequency_label)
    }
  }
})

test('indicator tiles carry latest value, period, change, sparkline and attribution (real EN payload)', () => {
  const tiles = officialIndicatorTiles(officialEn)
  assert.equal(tiles.length, 12)
  const unrate = tiles[0]
  assert.equal(unrate.series, 'fred:UNRATE')
  assert.equal(unrate.label, 'Unemployment Rate — United States')
  assert.equal(unrate.valueText, '4.2%')
  assert.equal(unrate.periodText, '2026-09')
  assert.equal(unrate.headlineKind, '')
  assert.equal(unrate.changeText, '-0.2 pp')
  assert.equal(unrate.changeDirection, 'down')
  assert.equal(unrate.sourceId, 'S1')
  assert.equal(unrate.sourceUrl, 'https://fred.stlouisfed.org/series/UNRATE')
  assert.equal(unrate.providerName, 'FRED (Federal Reserve Bank of St. Louis)')
  assert.equal(unrate.frequencyLabel, 'Monthly')
  assert.equal(unrate.unitsLabel, '')
  assert.equal(tiles.find(tile => tile.series === 'fred:SAHMREALTIME').unitsLabel, 'Percentage Points')
  assert.deepEqual(unrate.range, {
    low: { display: '3.4%', period: '2023-04', date: '2023-04-01', kind: '' },
    high: { display: '4.7%', period: '2021-09', date: '2021-09-01', kind: '' },
  })
  assert.equal(unrate.publisher, null)
  assert.equal(unrate.spark.count, 24)
  assert.equal(unrate.spark.lastDate, '2026-09-01')

  // Projection-only series headline their newest publisher value, flagged by kind.
  const weo = tiles.find(tile => tile.series === 'imf:WEO/G001.NGDP_RPCH.A')
  assert.equal(weo.valueText, '3.056%')
  assert.equal(weo.periodText, '2026')
  assert.equal(weo.headlineKind, 'unclassified publisher value')
  assert.equal(weo.changeText, '')
  assert.equal(weo.spark, null)

  // A series with history AND a newer non-historical value shows both.
  const spread = tiles.find(tile => tile.series === 'fred:T10Y3M')
  assert.equal(spread.valueText, '0.896%')
  assert.equal(spread.publisher.display, '1.05%')
  assert.equal(spread.publisher.kind, 'partial-period value')

  const debt = tiles.find(tile => tile.series === 'usgov:treasury/debt_to_penny')
  assert.equal(debt.valueText, '40093219044989.21')
  assert.equal(debt.valueScaled, '≈ 40.09 trillion U.S. dollars')
  assert.equal(debt.unitsLabel, '', 'the companion already names the units')
  assert.equal(debt.changeDirection, 'up')
  assert.equal(unrate.valueScaled, '')
})

test('zh payload tiles keep the server-localized labels and change wording', () => {
  const tiles = officialIndicatorTiles(officialZh)
  assert.equal(tiles[0].label, '美国失业率')
  assert.equal(tiles[0].changeText, '-0.2 个百分点')
  assert.equal(tiles[0].frequencyLabel, '月度')
  const debt = tiles.find(tile => tile.series === 'usgov:treasury/debt_to_penny')
  assert.equal(debt.valueText, '40093219044989.21')
  assert.equal(debt.valueScaled, '≈40.09万亿美元')
  assert.equal(debt.unitsLabel, 'U.S. dollars')
})

test('the change arrow follows the displayed change, never float noise', () => {
  // report_agent.official_indicator_summary output (en and zh) for the real UNRATE carrier row
  // whose latest and year-earlier months are means of a constant 3.88 daily rate over 21 and
  // 19 days (data_sources: sum(values) / len(values)): equal readings, a 4.4e-16 delta.
  const unrate = officialEn.indicators[0]
  const noise = 4.440892098500626e-16
  for (const display of ['0 pp', '0 个百分点']) {
    const tile = officialIndicatorTile({
      ...unrate,
      latest: { ...unrate.latest, value: 3.8800000000000003, display: '3.88%' },
      previous_year: { ...unrate.previous_year, value: 3.88, display: '3.88%' },
      change: { value: noise, percent: 1.1445598192011925e-14, display, display_words: display },
    })
    assert.equal(tile.changeText, display)
    assert.equal(tile.changeDirection, 'flat')
  }
  assert.equal(formatOfficialChange(noise, 'Percent'), '0 pp')
  // A displayed sign decides the direction, including level series with a relative change.
  assert.equal(officialIndicatorTile({ ...unrate, change: { value: 0.0004, display: '0 pp' } }).changeDirection, 'flat')
  assert.equal(officialIndicatorTile({ ...unrate, change: { value: -0.2, display: '-0.2 pp' } }).changeDirection, 'down')
  assert.equal(officialIndicatorTiles(officialEn)[1].changeDirection, 'up')
})

test('malformed indicator rows are skipped, never thrown on', () => {
  assert.deepEqual(officialIndicatorTiles(null), [])
  assert.deepEqual(officialIndicatorTiles({ available: false, indicators: [] }), [])
  assert.deepEqual(officialIndicatorTiles({ indicators: 'nope' }), [])
  assert.equal(officialIndicatorTile({ series: 'fred:X' }), null)
  assert.equal(officialIndicatorTile({ latest: { display: '1' } }), null)
  const tile = officialIndicatorTile({
    series: 'fred:X',
    latest: { display: '1%', period: '2026-01' },
    source_id: 'S0',
    source_url: 'javascript:alert(1)',
    history: [['2026-01-01', 'x']],
  })
  assert.equal(tile.sourceId, '')
  assert.equal(tile.sourceUrl, '')
  assert.equal(tile.spark, null)
  assert.equal(tile.label, 'fred:X')
})

test('sparkline geometry spans the box, puts the max on top and handles flat series', () => {
  const geometry = sparklineGeometry([['2026-01-01', 1], ['2026-02-01', 3], ['2026-03-01', 2]],
    { width: 100, height: 20, pad: 0 })
  assert.equal(geometry.points, '0,20 50,0 100,10')
  assert.deepEqual(geometry.last, { x: 100, y: 10 })
  assert.equal(geometry.min, 1)
  assert.equal(geometry.max, 3)
  const flat = sparklineGeometry([['a', 5], ['b', 5]], { width: 10, height: 10, pad: 1 })
  assert.equal(flat.points, '1,5 9,5')
  assert.equal(sparklineGeometry([['a', 5]]), null)
  assert.equal(sparklineGeometry(null), null)
})

test('series index maps carrier ids to the report label and [S#]', () => {
  const index = officialSeriesIndex(officialEn)
  assert.deepEqual(index['fred:UNRATE'], {
    label: 'Unemployment Rate — United States',
    sourceId: 'S1',
    sourceUrl: 'https://fred.stlouisfed.org/series/UNRATE',
    providerName: 'FRED (Federal Reserve Bank of St. Louis)',
    // The trimmed fixture carrier dropped provenance; a full one is carried through.
    provenance: null,
  })
  assert.equal(index['bis:WS_CBPOL/M.US'].sourceId, 'S7')
  const fiscal = officialSeriesIndex(fixture('official_data.usaspending_fy.en.json').data)['usgov:spending/total']
  assert.equal(fiscal.provenance.periods['2025-10-01'].label, 'FY2026')
  assert.deepEqual(officialSeriesIndex(undefined), {})
})

test('per-series control names stay distinct even when two series share a label', () => {
  // Accessible names of the per-series CSV / chart controls. The catalog has series that
  // share a reader label (fred:FEDFUNDS and fred:DFF both read 'Federal Funds Effective
  // Rate — United States'): only those get their series id appended.
  const tiles = officialIndicatorTiles(officialEn)
  const names = distinctSeriesNames(tiles.map(tile => ({ key: tile.key, label: tile.label, series: tile.series })))
  assert.equal(names[tiles[0].key], 'Unemployment Rate — United States')
  assert.equal(new Set(Object.values(names)).size, tiles.length)
  assert.deepEqual(distinctSeriesNames([
    { key: 'a', label: 'Federal Funds Effective Rate — United States', series: 'fred:FEDFUNDS' },
    { key: 'b', label: 'Federal Funds Effective Rate — United States', series: 'fred:DFF' },
    { key: 'c', label: 'Unemployment Rate — United States', series: 'fred:UNRATE' },
    { key: 'd', label: '', series: 'fred:PAYEMS' },
    null,
  ]), {
    a: 'Federal Funds Effective Rate — United States (fred:FEDFUNDS)',
    b: 'Federal Funds Effective Rate — United States (fred:DFF)',
    c: 'Unemployment Rate — United States',
    d: 'fred:PAYEMS',
  })
  assert.deepEqual(distinctSeriesNames(null), {})
})

test('series CSV exports exactly the stored observations of the report carrier', () => {
  const carrier = officialEn.official_data
  const csv = officialSeriesCsv(carrier, 'fred:UNRATE')
  const lines = csv.trimEnd().split('\n')
  const stored = carrier.series.find(row => row.series === 'fred:UNRATE').observations
  assert.equal(lines[0], 'date,value')
  assert.equal(lines.length, stored.length + 1)
  assert.equal(lines[1], '2019-01-01,4')
  assert.equal(lines[lines.length - 1], `${stored[stored.length - 1].date},${stored[stored.length - 1].value}`)
  const debt = officialSeriesCsv(carrier, 'usgov:treasury/debt_to_penny')
  assert.match(debt, /\n2026-09-01,40093219044989\.21\n/)
  assert.equal(officialSeriesCsv(carrier, 'fred:NOPE'), '')
  assert.equal(officialSeriesCsv(null, 'fred:UNRATE'), '')
  assert.equal(officialSeriesCsv({ series: [{ series: 'x', observations: [{ date: '2020,1', value: null }] }] }, 'x'),
    'date,value\n"2020,1",\n')
  assert.equal(officialCsvFilename('bis:WS_CBPOL/M.US'), 'bis_WS_CBPOL_M.US.csv')
  assert.equal(officialCsvFilename('../x'), 'x.csv')
})

test('labels: frequency, observation kinds and period granularity', () => {
  assert.equal(officialFrequencyLabel('Q', 'zh'), '季度')
  assert.equal(officialFrequencyLabel('X', 'en'), 'X')
  assert.equal(officialKindLabel('publisher projection', 'zh'), '发布方预测值')
  assert.equal(officialKindLabel('publisher projection', 'en'), 'publisher projection')
  assert.equal(officialPeriodLabel('2026-08-01', 'Q'), '2026-Q3')
  assert.equal(officialPeriodLabel('2026-08-14', 'D'), '2026-08-14')
  assert.equal(officialPeriodLabel('garbage', 'M'), 'garbage')
})

test('safeSourceUrl admits only credential-free absolute http(s) links', () => {
  assert.equal(safeSourceUrl('https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US'),
    'https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US')
  assert.equal(safeSourceUrl('javascript:alert(1)'), '')
  assert.equal(safeSourceUrl('https://user:pw@example.com/x'), '')
  assert.equal(safeSourceUrl('//example.com'), '')
  assert.equal(safeSourceUrl(null), '')
})

test('research dataset manifest rows (real v3 datasets.json) with CSV only when registered', () => {
  const rows = datasetManifestRows(datasets, { lang: 'en' })
  assert.equal(rows.length, 8)
  const unrate = rows.find(row => row.series === 'fred:UNRATE')
  assert.equal(unrate.label, 'Unemployment Rate')
  assert.equal(unrate.latestText, '4.2%')
  assert.equal(unrate.latestPeriod, '2026-09')
  assert.equal(unrate.sourceId, 'S39')
  assert.equal(unrate.coverage, '2016-11 – 2026-09')
  assert.equal(unrate.observationCount, 119)
  assert.deepEqual(unrate.kiqs, ['K4'])
  assert.equal(unrate.chartPath, '')
  assert.equal(unrate.csvArtifact, '')
  assert.equal(unrate.csvFilename, 'fred_unrate_9d03984317fdea12.3d75202810c5af63.csv')
  // A daily-aggregated series whose months are all partial has no latest observation.
  const upper = rows.find(row => row.series === 'fred:DFEDTARU')
  assert.equal(upper.latestText, '')
  assert.equal(upper.latestPeriod, '')

  const registered = datasetManifestRows(datasets, {
    lang: 'zh',
    artifactNames: ['datasets', 'dataset_fred_unrate_9d03984317fdea12.3d75202810c5af63.csv_partial',
      'chart_data_fred_unrate_9d03984317fdea12.png'],
  })
  const zhUnrate = registered.find(row => row.series === 'fred:UNRATE')
  assert.equal(zhUnrate.label, '美国失业率')
  assert.equal(zhUnrate.frequencyLabel, '月度')
  assert.equal(zhUnrate.csvArtifact, 'dataset_fred_unrate_9d03984317fdea12.3d75202810c5af63.csv_partial')
  assert.equal(zhUnrate.chartPath, 'charts/data_fred_unrate_9d03984317fdea12.png')
  assert.equal(registered.find(row => row.series === 'fred:CIVPART').chartPath, '')
  assert.deepEqual(datasetManifestRows(null), [])
  assert.deepEqual(datasetManifestRows({ series: [null, { title: 'no id' }] }), [])
})

test('fiscal-year datasets read FY labels like the report (report_agent.official_period_label)', () => {
  // Real data layer output for usgov:spending/total: each annual observation is dated at the
  // start of a US federal fiscal year (2022-10-01 is FY2023), recorded in provenance.periods.
  const [row] = datasetManifestRows(fiscalDatasets, { lang: 'en' })
  assert.equal(row.series, 'usgov:spending/total')
  assert.equal(row.coverage, 'FY2023 – FY2027')
  const periods = fiscalDatasets.series[0].provenance.periods
  assert.equal(officialPeriodLabel('2025-10-01', 'A', { periods }), 'FY2026')
  // Calendar-year rows and rows without fiscal provenance keep the plain year.
  assert.equal(officialPeriodLabel('2025-10-01', 'A'), '2025')
  assert.equal(officialPeriodLabel('2025-10-01', 'A', { periods: { '2025-10-01': { label: 'FY2026' } } }), '2025')
  assert.equal(officialPeriodLabel('2025-01-01', 'A', { periods }), '2025')
  const latest = datasetManifestRows({ series: [{
    ...fiscalDatasets.series[0], latest: { date: '2024-10-01', value: 5315833520242.8 },
  }] }, { lang: 'zh' })[0]
  assert.equal(latest.latestPeriod, 'FY2025')
  assert.equal(latest.latestText, '5315833520242.8 (≈5.32万亿美元)')
})

test('anchor periods read like forecast_extractor.official_anchor_period_text', () => {
  // Expected strings printed by the backend helper for the replayed USAspending carrier's
  // provenance (fiscal years stored to FY2027, fiscal_start_month 10) and variants of it.
  const provenance = fixture('official_data.usaspending_fy.en.json').data.official_data.series[0].provenance
  const { fiscal_start_month: _month, ...noFiscalStart } = provenance
  for (const [date, frequency, prov, expected] of [
    ['2025-10-01', 'A', provenance, 'FY2026'],
    ['2026-10-01', 'A', provenance, 'FY2027'],
    ['2027-10-01', 'A', provenance, 'FY2028'],
    ['2030-10-01', 'A', provenance, 'FY2031'],
    ['2026-09-01', 'A', provenance, '2026'],
    ['2026-10-01', 'M', provenance, '2026-10'],
    ['2026-10-01', 'Q', provenance, '2026-Q4'],
    ['2025-10-01', 'A', noFiscalStart, 'FY2026'],
    ['2027-10-01', 'A', noFiscalStart, '2027'],
    ['2026-10-01', 'A', { fiscal_start_month: 10, periods: { '2024-01-01': { calendar: 'gregorian', label: '2024' } } }, '2026'],
    ['2026-10-01', 'A', null, '2026'],
  ]) {
    assert.equal(officialAnchorPeriodLabel(date, frequency, prov), expected, `${date} ${frequency}`)
  }
})

test('data-source probe rows (real live response): fixed order, states, key names only', () => {
  const model = dataSourceProbeRows(probe)
  assert.equal(model.enabled, true)
  assert.deepEqual(model.rows.map(row => row.provider), ['fred', 'bls', 'bis', 'imf', 'wb', 'usgov'])
  assert.deepEqual(model.counts, { ok: 4, degraded: 2, unavailable: 0, disabled: 0, unknown: 0 })
  const imf = model.rows.find(row => row.provider === 'imf')
  assert.equal(imf.name, 'IMF')
  assert.equal(imf.state, 'degraded')
  assert.equal(imf.latencyText, '44.95 s')
  assert.match(imf.detail, /DATA_UNAVAILABLE\[timeout\]/)
  assert.deepEqual(model.rows.find(row => row.provider === 'usgov').keys, [
    { name: 'EIA_API_KEY', status: 'set' },
    { name: 'BEA_API_KEY', status: 'set' },
    { name: 'CENSUS_API_KEY', status: 'not set' },
  ])
  assert.equal(model.elapsedText, '47.01 s')
})

test('the live endpoint body (alphabetical providers) is shown in the fixed provider order', () => {
  assert.deepEqual(Object.keys(endpointProbe.providers), ['bis', 'bls', 'fred', 'imf', 'usgov', 'wb'])
  const model = dataSourceProbeRows(endpointProbe)
  assert.deepEqual(model.rows.map(row => row.name),
    ['FRED', 'BLS', 'BIS', 'IMF', 'World Bank Data360', 'US Gov Open Data'])
  assert.deepEqual(model.counts, { ok: 6, degraded: 0, unavailable: 0, disabled: 0, unknown: 0 })
  assert.match(model.rows.find(row => row.provider === 'imf').detail, /30 observations to 2031-01-01 \(live via mcp\)/)
  assert.deepEqual(model.rows.find(row => row.provider === 'bls').keys, [{ name: 'BLS_API_KEY', status: 'set' }])
  assert.equal(model.elapsedText, '61.26 s')
})

test('probe rows degrade safely on disabled, unknown or malformed payloads', () => {
  const disabled = dataSourceProbeRows({
    enabled: false,
    providers: { fred: { state: 'disabled', detail: 'DATA_SOURCES_ENABLED=false', latency_s: 0, keys: {} } },
  })
  assert.equal(disabled.enabled, false)
  assert.equal(disabled.rows[0].state, 'disabled')
  const odd = dataSourceProbeRows({ providers: { zzz: { state: 'weird', keys: { K: 'leaked-value' } }, bls: 'x' } })
  assert.deepEqual(odd.rows.map(row => [row.provider, row.state]), [['zzz', 'unknown']])
  assert.deepEqual(odd.rows[0].keys, [{ name: 'K', status: 'unknown' }])
  assert.deepEqual(dataSourceProbeRows(null).rows, [])
})
