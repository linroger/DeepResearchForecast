/**
 * officialData.js — pure display models for stored official-data series
 * (FRED, BLS, BIS, IMF, World Bank Data360, US Gov Open Data).
 *
 * Inputs are the backend's own payloads, never re-fetched data:
 *   - GET /api/report/<id>/official-data → { available, indicators[], official_data, … }
 *     where each indicator is report_agent.official_indicator_summary (display
 *     strings already localized server-side by ?lang=).
 *   - forecast.json binary_forecasts[].data_anchor (forecast_extractor).
 *   - research handoff data/datasets.json (via the research artifact endpoint).
 *   - POST /api/settings/data-sources/test → { enabled, providers{…}, … }.
 *
 * The number formatters mirror deerflow_bridge/data_sources.py (format_value,
 * format_change, scaled_value) so a value the frontend formats reads exactly
 * like the same value in the report. Contract: never throws on malformed
 * payloads; invalid entries are skipped and absent fields collapse to ''/null.
 */

const PERCENT_RE = /per\s*cent|%/i
const POINT_RE = /point/i
const SCALE_WORD_RE = /\b(?:thousands?|millions?|billions?|trillions?)\b/i
const PLAIN_UNIT_WORDS = new Set(['number', 'value', 'unknown', 'units', 'count'])
const ZH_UNITS = Object.freeze({
  'u.s. dollars': '美元', 'us dollars': '美元', 'u.s. dollar': '美元', 'us dollar': '美元', dollars: '美元',
})
const SOURCE_ID_RE = /^S[1-9]\d*$/

const FREQUENCY_LABELS = Object.freeze({
  en: { D: 'Daily', W: 'Weekly', M: 'Monthly', Q: 'Quarterly', A: 'Annual' },
  zh: { D: '日度', W: '周度', M: '月度', Q: '季度', A: '年度' },
})
// forecast_extractor.official_observation_kind labels (report_agent._OFFICIAL_KIND_LABELS_ZH).
const KIND_LABELS_ZH = Object.freeze({
  'historical observation': '历史观测值',
  'publisher projection': '发布方预测值',
  'publisher estimate': '发布方估计值',
  'publisher preliminary': '发布方初值',
  'unclassified publisher value': '未分类发布值',
  'partial-period value': '不完整期间值',
})

export function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function str(value) {
  return typeof value === 'string' ? value.trim() : ''
}

/** Strict numeric coercion: finite numbers and numeric strings only (never booleans). */
export function officialNumber(value) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string' && value.trim() !== '') {
    const n = Number(value)
    return Number.isFinite(n) ? n : null
  }
  return null
}

function isZh(lang) {
  return String(lang || '').toLowerCase().startsWith('zh')
}

/** data_sources.is_percent_units: percents (changes are pp); 'percentage points' units are not. */
export function isPercentUnits(units) {
  const text = String(units == null ? '' : units)
  return PERCENT_RE.test(text) && !POINT_RE.test(text)
}

/**
 * Python f"{x:.{digits}f}": the exact binary value rounded half-to-even.
 * Number#toFixed breaks exact ties away from zero, so ties are re-resolved
 * against the exact decimal expansion (toFixed(100) is exact for |x| < 1e21).
 */
function fixedHalfEven(x, digits) {
  const negative = x < 0 || Object.is(x, -0)
  const abs = Math.abs(x)
  let text = abs.toFixed(digits)
  if (abs < 1e21) {
    const [whole, fraction = ''] = abs.toFixed(100).split('.')
    if (/^50*$/.test(fraction.slice(digits))) {
      const truncated = digits ? `${whole}.${fraction.slice(0, digits)}` : whole
      if (Number(truncated[truncated.length - 1]) % 2 === 0) text = truncated
    }
  }
  return (negative ? '-' : '') + text
}

/** Python round(x, digits) for a finite float (same exact half-to-even rule as f-string formatting). */
export function roundHalfEven(value, digits) {
  return Number(fixedHalfEven(value, digits))
}

/** data_sources._trim: drop trailing zeros and a bare point; '-0' → '0'. */
function trimNumber(text) {
  const trimmed = text.includes('.') ? text.replace(/0+$/, '').replace(/\.$/, '') : text
  return trimmed === '-0' || trimmed === '' ? '0' : trimmed
}

/**
 * data_sources.format_value: percent-like units keep up to 3 decimals ('3.875%');
 * levels keep up to 4 decimals within 15 significant digits, 4 significant below 1.
 * Non-numeric → ''.
 */
export function formatOfficialValue(value, units = '') {
  const n = officialNumber(value)
  if (n == null) return ''
  if (isPercentUnits(units)) return trimNumber(fixedHalfEven(n, 3)) + '%'
  let decimals
  if (n === 0 || Math.abs(n) >= 1) {
    decimals = n ? Math.max(0, Math.min(4, 15 - Math.floor(Math.log10(Math.abs(n))))) : 4
  } else {
    decimals = Math.min(12, 3 - Math.floor(Math.log10(Math.abs(n))))
  }
  return trimNumber(fixedHalfEven(n, decimals))
}

function signed(text) {
  return text.startsWith('-') || text.replace(/[% p]+$/, '') === '0' ? text : '+' + text
}

/** data_sources.format_change: '+0.25 pp' for percent-like units, else a signed level. */
export function formatOfficialChange(delta, units = '') {
  const n = officialNumber(delta)
  if (n == null) return ''
  if (isPercentUnits(units)) return signed(trimNumber(fixedHalfEven(n, 3)) + ' pp')
  return signed(formatOfficialValue(n, units))
}

/**
 * data_sources.scaled_value: magnitude companion such as '≈ 40.27 trillion U.S.
 * dollars' (zh '≈40.27万亿美元') for |value| ≥ 1e9 when the units carry no scale
 * word and are not percents; otherwise ''.
 */
export function scaledOfficialValue(value, units = '', lang = 'en') {
  const n = officialNumber(value)
  let text = String(units == null ? '' : units).split(/\s+/).filter(Boolean).join(' ').slice(0, 80)
  if (n == null || Math.abs(n) < 1e9 || isPercentUnits(text) || SCALE_WORD_RE.test(text)) return ''
  if (PLAIN_UNIT_WORDS.has(text.toLowerCase())) text = ''
  if (isZh(lang)) {
    const [divisor, word] = Math.abs(n) >= 1e12 ? [1e12, '万亿'] : [1e8, '亿']
    const unit = ZH_UNITS[text.toLowerCase()] ?? (text ? ' ' + text : '')
    return `≈${trimNumber(fixedHalfEven(n / divisor, 2))}${word}${unit}`
  }
  const [divisor, word] = Math.abs(n) >= 1e12 ? [1e12, 'trillion'] : [1e9, 'billion']
  return `≈ ${trimNumber(fixedHalfEven(n / divisor, 2))} ${word}` + (text ? ' ' + text : '')
}

/** report_agent._official_value_display: '40093219044989.21 (≈ 40.09 trillion U.S. dollars)'. */
export function formatOfficialDisplay(value, units = '', lang = 'en') {
  const text = formatOfficialValue(value, units)
  if (!text) return ''
  const scaled = scaledOfficialValue(value, units, lang)
  return scaled ? `${text} (${scaled})` : text
}

/**
 * Reader period for a stored date: 2026-09 (M), 2026-Q2 (Q), 2025 (A), the date otherwise.
 * A US federal fiscal-year period recorded in the row's `provenance.periods` reads by its
 * label ('FY2026' for 2025-10-01), as report_agent.official_period_label does.
 */
export function officialPeriodLabel(date, frequency, provenance = null) {
  const day = str(date)
  const periods = isPlainObject(provenance) && isPlainObject(provenance.periods) ? provenance.periods : null
  const record = periods && Object.prototype.hasOwnProperty.call(periods, day) ? periods[day] : null
  if (isPlainObject(record) && record.calendar === 'us_federal_fiscal_year' && str(record.label)) {
    return str(record.label)
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return day
  if (frequency === 'A') return day.slice(0, 4)
  if (frequency === 'Q') return `${day.slice(0, 4)}-Q${Math.floor((Number(day.slice(5, 7)) - 1) / 3) + 1}`
  return frequency === 'M' ? day.slice(0, 7) : day
}

/**
 * forecast_extractor._official_fiscal_label: 'FY2026' when `period` (a stored or anchored date,
 * '2025-10-01') of an annual row is a US federal fiscal year, else ''. The row's stored period
 * record names it; a fiscal year the row does not store yet takes the data layer's rule,
 * FY<start year + 1>.
 */
function fiscalPeriodLabel(period, provenance) {
  const periods = isPlainObject(provenance) && isPlainObject(provenance.periods) ? provenance.periods : null
  if (!periods) return ''
  const day = String(period || '').slice(0, 10)
  const record = Object.prototype.hasOwnProperty.call(periods, day) ? periods[day] : null
  if (isPlainObject(record) && record.calendar === 'us_federal_fiscal_year') {
    const label = String(record.label || '').trim()
    return /^FY\d{4}$/.test(label) ? label : ''
  }
  if (provenance.fiscal_start_month === 10 && /^\d{4}-10-01$/.test(day)
    && Object.values(periods).some(entry => isPlainObject(entry) && entry.calendar === 'us_federal_fiscal_year')) {
    return `FY${Number(day.slice(0, 4)) + 1}`
  }
  return ''
}

/**
 * forecast_extractor.official_anchor_period_text: the reader period of a data anchor's period
 * or latest date. A US federal fiscal-year row (annual, `provenance` from the stored carrier)
 * reads 'FY2027' for 2026-10-01, as the report's tables and settlement sentence do; every
 * other period reads as officialPeriodLabel.
 */
export function officialAnchorPeriodLabel(date, frequency, provenance = null) {
  return (frequency === 'A' ? fiscalPeriodLabel(date, provenance) : '') || officialPeriodLabel(date, frequency)
}

export function officialFrequencyLabel(frequency, lang = 'en') {
  const code = str(frequency)
  return FREQUENCY_LABELS[isZh(lang) ? 'zh' : 'en'][code] || code
}

/** Observation-kind label ('publisher projection' → '发布方预测值' in zh). */
export function officialKindLabel(kind, lang = 'en') {
  const text = str(kind)
  return isZh(lang) ? (KIND_LABELS_ZH[text] || text) : text
}

/** Source links render live: absolute http(s) URLs without credentials only. */
export function safeSourceUrl(value) {
  const text = str(value)
  if (!/^https?:\/\//i.test(text)) return ''
  try {
    const url = new URL(text)
    if (!/^https?:$/.test(url.protocol) || !url.hostname || url.username || url.password) return ''
    return text
  } catch (e) {
    return ''
  }
}

function sourceId(value) {
  const text = str(value)
  return SOURCE_ID_RE.test(text) ? text : ''
}

/**
 * Polyline geometry for a sparkline from [[date, value], …] (ascending).
 * Returns null when fewer than two numeric points exist; a constant series is
 * drawn flat at mid-height.
 */
export function sparklineGeometry(history, { width = 120, height = 32, pad = 2 } = {}) {
  const points = (Array.isArray(history) ? history : [])
    .filter(entry => Array.isArray(entry) && officialNumber(entry[1]) != null)
    .map(entry => ({ date: str(entry[0]), value: officialNumber(entry[1]) }))
  if (points.length < 2) return null
  const values = points.map(point => point.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min
  const stepX = (width - 2 * pad) / (points.length - 1)
  const round = n => Math.round(n * 100) / 100
  const coords = points.map((point, i) => [
    round(pad + i * stepX),
    round(span ? pad + (1 - (point.value - min) / span) * (height - 2 * pad) : height / 2),
  ])
  const [lastX, lastY] = coords[coords.length - 1]
  return {
    width,
    height,
    points: coords.map(([x, y]) => `${x},${y}`).join(' '),
    last: { x: lastX, y: lastY },
    min,
    max,
    count: points.length,
    firstDate: points[0].date,
    lastDate: points[points.length - 1].date,
  }
}

function summaryPoint(raw) {
  if (!isPlainObject(raw)) return null
  const display = str(raw.display)
  if (!display) return null
  return { display, period: str(raw.period), date: str(raw.date), kind: str(raw.kind) }
}

// report_agent._official_value_display appends the magnitude companion: '<exact> (≈ …)'.
const SCALED_DISPLAY_RE = /^(.*\S) \((≈[^()]*)\)$/

// The arrow follows the displayed (rounded, signed) change: equal readings whose stored
// means differ by float noise display '0 pp' and must not point up or down.
function changeDirection(display) {
  const text = str(display)
  return text.startsWith('+') ? 'up' : (text.startsWith('-') ? 'down' : 'flat')
}

/**
 * One official_indicator_summary → tile model, or null when it carries no
 * displayable value. The headline is the latest historical observation; a series
 * with only publisher values (WEO/GEP projections, unclassified Data360 rows)
 * headlines its newest publisher value, flagged by `headlineKind`.
 */
export function officialIndicatorTile(raw, index = 0) {
  if (!isPlainObject(raw)) return null
  const series = str(raw.series)
  if (!series) return null
  const latest = summaryPoint(raw.latest)
  const publisher = summaryPoint(raw.publisher_value)
  const headline = latest || publisher
  if (!headline) return null
  const change = isPlainObject(raw.change) && str(raw.change.display) ? raw.change : null
  const window = isPlainObject(raw.five_year) ? raw.five_year : null
  const scaled = headline.display.match(SCALED_DISPLAY_RE)
  const units = str(raw.units)
  const low = window && summaryPoint(window.min)
  const high = window && summaryPoint(window.max)
  return {
    key: `${series}-${index}`,
    series,
    label: str(raw.label) || series,
    sourceId: sourceId(raw.source_id),
    sourceUrl: safeSourceUrl(raw.source_url),
    providerName: str(raw.provider_name) || str(raw.provider),
    units,
    // Percent values carry their unit in the number ('4.2%'); other units are shown
    // unless the magnitude companion already names them.
    unitsLabel: isPercentUnits(units) || (scaled && units && scaled[2].includes(units)) ? '' : units,
    frequencyLabel: str(raw.frequency_label) || str(raw.frequency),
    seasonalAdjustment: str(raw.seasonal_adjustment),
    // The exact stored value headlines; '≈ 40.09 trillion U.S. dollars' reads below it.
    valueText: scaled ? scaled[1] : headline.display,
    valueScaled: scaled ? scaled[2] : '',
    periodText: headline.period,
    headlineKind: latest ? '' : publisher.kind,
    changeText: change ? str(change.display) : '',
    changeDirection: change ? changeDirection(change.display) : '',
    range: low && high ? { low, high } : null,
    publisher: latest && publisher ? publisher : null,
    spark: sparklineGeometry(raw.history),
  }
}

/** GET /official-data `data` → tile models in carrier order (malformed rows skipped). */
export function officialIndicatorTiles(payload) {
  const list = isPlainObject(payload) && Array.isArray(payload.indicators) ? payload.indicators : []
  const tiles = []
  list.forEach((raw, index) => {
    const tile = officialIndicatorTile(raw, index)
    if (tile) tiles.push(tile)
  })
  return tiles
}

/**
 * Series id → { label, sourceId, sourceUrl, providerName, provenance } from the indicator
 * summaries; `provenance` is the stored carrier row's (fiscal-year period labels), or null.
 */
export function officialSeriesIndex(payload) {
  const index = {}
  const list = isPlainObject(payload) && Array.isArray(payload.indicators) ? payload.indicators : []
  const carrier = isPlainObject(payload) && isPlainObject(payload.official_data)
    && Array.isArray(payload.official_data.series) ? payload.official_data.series : []
  for (const raw of list) {
    const series = isPlainObject(raw) ? str(raw.series) : ''
    if (!series || index[series]) continue
    const row = carrier.find(entry => isPlainObject(entry) && entry.series === series)
    index[series] = {
      label: str(raw.label) || series,
      sourceId: sourceId(raw.source_id),
      sourceUrl: safeSourceUrl(raw.source_url),
      providerName: str(raw.provider_name) || str(raw.provider),
      provenance: row && isPlainObject(row.provenance) ? row.provenance : null,
    }
  }
  return index
}

/**
 * Accessible names for per-series controls (CSV downloads, chart links), one per
 * `{ key, label, series }` entry: the label (the series id when it has none), with the
 * series id appended where another entry shares the label, so no two controls of a
 * list read alike. Returns { [key]: name }.
 */
export function distinctSeriesNames(entries) {
  const list = (Array.isArray(entries) ? entries : []).filter(isPlainObject)
  const name = entry => str(entry.label) || str(entry.series)
  const counts = new Map()
  for (const entry of list) counts.set(name(entry), (counts.get(name(entry)) || 0) + 1)
  const names = {}
  for (const entry of list) {
    const text = name(entry)
    const series = str(entry.series)
    names[entry.key] = counts.get(text) > 1 && series && series !== text ? `${text} (${series})` : text
  }
  return names
}

function csvCell(value) {
  const text = String(value)
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

/**
 * The stored observations of one carrier series as CSV ('date,value', the same
 * columns as the research dataset CSVs; a missing value is an empty cell).
 * '' when the series is not in the carrier.
 */
export function officialSeriesCsv(carrier, series) {
  const rows = isPlainObject(carrier) && Array.isArray(carrier.series) ? carrier.series : []
  const row = rows.find(entry => isPlainObject(entry) && entry.series === series)
  if (!row || !Array.isArray(row.observations)) return ''
  const lines = ['date,value']
  for (const observation of row.observations) {
    if (!isPlainObject(observation) || !str(observation.date)) continue
    const value = officialNumber(observation.value)
    lines.push(`${csvCell(str(observation.date))},${value == null ? '' : String(value)}`)
  }
  return lines.join('\n') + '\n'
}

/** Download name for a series CSV: 'fred_UNRATE.csv', 'bis_WS_CBPOL_M.US.csv'. */
export function officialCsvFilename(series) {
  const stem = String(series || 'series').replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^[._]+/, '')
  return `${stem || 'series'}.csv`
}

function basename(path) {
  const parts = String(path || '').split('/')
  return parts[parts.length - 1] || ''
}

function registeredArtifact(registered, prefix, file, extension) {
  if (!file || !extension.test(file)) return ''
  return [`${prefix}${file}`, `${prefix}${file}_partial`].find(name => registered.has(name)) || ''
}

/**
 * Research data/datasets.json → dossier list rows. `artifactNames` (the pipeline
 * status `artifacts` keys) decides what the research artifact endpoint can serve:
 * a dataset CSV only when `dataset_<file>` (or its live-scan `_partial` key) is
 * registered, the series chart only when `chart_<file>` is, so no row ever shows
 * a dead link.
 */
export function datasetManifestRows(manifest, { lang = 'en', artifactNames = [] } = {}) {
  const series = isPlainObject(manifest) && Array.isArray(manifest.series) ? manifest.series : []
  const registered = new Set(Array.isArray(artifactNames) ? artifactNames : [])
  const zh = isZh(lang)
  const rows = []
  series.forEach((raw, index) => {
    if (!isPlainObject(raw)) return
    const id = str(raw.series)
    if (!id) return
    const units = str(raw.units)
    const frequency = str(raw.frequency)
    const latest = isPlainObject(raw.latest) ? raw.latest : null
    const latestValue = latest ? officialNumber(latest.value) : null
    const csvFile = basename(raw.csv)
    const chartPath = str(raw.chart)
    const title = (zh && str(raw.title_zh)) || str(raw.title) || id
    const count = officialNumber(raw.observations)
    const period = day => officialPeriodLabel(day, frequency, raw.provenance)
    rows.push({
      key: `${id}-${index}`,
      series: id,
      label: title,
      geography: str(raw.geography),
      providerName: str(raw.provider_name) || str(raw.provider),
      sourceId: sourceId(raw.source_id),
      sourceUrl: safeSourceUrl(raw.source_url),
      units,
      frequencyLabel: officialFrequencyLabel(frequency, lang),
      latestText: latestValue == null ? '' : formatOfficialDisplay(latestValue, units, lang),
      latestPeriod: latestValue == null ? '' : period(latest.date),
      coverage: str(raw.first) && str(raw.last) ? `${period(raw.first)} – ${period(raw.last)}` : '',
      observationCount: Number.isInteger(count) && count >= 0 ? count : null,
      kiqs: Array.isArray(raw.kiqs) ? raw.kiqs.map(str).filter(Boolean) : [],
      chartPath: registeredArtifact(registered, 'chart_', basename(chartPath), /\.(png|svg|html)$/i) ? chartPath : '',
      csvArtifact: registeredArtifact(registered, 'dataset_', csvFile, /\.csv$/i),
      csvFilename: csvFile,
    })
  })
  return rows
}

const PROBE_PROVIDERS = Object.freeze(['fred', 'bls', 'bis', 'imf', 'wb', 'usgov'])
const PROBE_NAMES = Object.freeze({
  fred: 'FRED',
  bls: 'BLS',
  bis: 'BIS',
  imf: 'IMF',
  wb: 'World Bank Data360',
  usgov: 'US Gov Open Data',
})
const PROBE_STATES = new Set(['ok', 'degraded', 'unavailable', 'disabled'])
const KEY_STATES = new Set(['set', 'not set', 'invalid'])

/**
 * POST /api/settings/data-sources/test `data` → provider rows in the fixed
 * provider order (unknown providers after), plus per-state counts.
 * Key entries carry names and set / not set / invalid only — never values.
 */
export function dataSourceProbeRows(payload) {
  const providers = isPlainObject(payload) && isPlainObject(payload.providers) ? payload.providers : {}
  const names = [
    ...PROBE_PROVIDERS.filter(name => isPlainObject(providers[name])),
    ...Object.keys(providers).filter(name => !PROBE_PROVIDERS.includes(name) && isPlainObject(providers[name])).sort(),
  ]
  const counts = { ok: 0, degraded: 0, unavailable: 0, disabled: 0, unknown: 0 }
  const rows = names.map(name => {
    const raw = providers[name]
    const state = PROBE_STATES.has(str(raw.state)) ? str(raw.state) : 'unknown'
    counts[state] += 1
    const latency = officialNumber(raw.latency_s)
    const keys = isPlainObject(raw.keys)
      ? Object.keys(raw.keys).map(key => ({
        name: key,
        status: KEY_STATES.has(str(raw.keys[key])) ? str(raw.keys[key]) : 'unknown',
      }))
      : []
    return {
      provider: name,
      name: PROBE_NAMES[name] || name,
      state,
      detail: str(raw.detail),
      latencyText: latency == null ? '' : `${latency} s`,
      keys,
    }
  })
  return {
    enabled: !(isPlainObject(payload) && payload.enabled === false),
    rows,
    counts,
    elapsedText: isPlainObject(payload) && officialNumber(payload.elapsed_s) != null ? `${payload.elapsed_s} s` : '',
  }
}
