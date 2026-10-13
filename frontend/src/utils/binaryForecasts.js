/**
 * binaryForecasts.js — pure row models for the first-class binary-forecast table.
 *
 * LOOP-017: the report UI used to show binary forecasts only as whatever
 * markdown the report happened to contain. forecast.json — served whole by
 * GET /api/report/<id>/forecast, which ForecastReport.vue already fetches —
 * carries a structured `binary_forecasts[]` payload ({id, statement,
 * probability, confidence, adjustment_rationale, p_low/p_high/interval_source,
 * market_anchor{...}, market_influence{...}, data_anchor{...}}). This module folds each raw entry
 * into a display-ready, language-neutral row model so BinaryForecastTable.vue
 * stays a thin template; bilingual labels/tooltips are assembled in the
 * component via L().
 *
 * Contract: never throws on malformed payloads — invalid entries are skipped
 * and absent fields collapse to null/'' so the template degrades per cell.
 */

import {
  formatOfficialChange,
  formatOfficialDisplay,
  formatOfficialValue,
  isPercentUnits,
  officialAnchorPeriodLabel,
  roundHalfEven,
  safeSourceUrl,
} from './officialData.js'

/** Strict numeric coercion: numbers and non-empty numeric strings only. */
function num(v) {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null
  if (typeof v === 'string' && v.trim() !== '') {
    const n = Number(v)
    return Number.isFinite(n) ? n : null
  }
  return null
}

function str(v) {
  return typeof v === 'string' ? v.trim() : ''
}

function isPlainObject(v) {
  return Boolean(v) && typeof v === 'object' && !Array.isArray(v)
}

/** 0..1 probability → '62.3%' (same rounding as the dashboard's pct()); non-numeric → ''. */
export function formatProbability(v) {
  const n = num(v)
  if (n == null) return ''
  return (Math.round(n * 1000) / 10) + '%'
}

/**
 * model − market divergence (0..1 scale) → { text: '+12.3pp', tone: 'pos'|'neg'|'zero' }.
 * Tone is derived from the ROUNDED value so text and color never disagree.
 * Non-numeric → null (cell omits the delta).
 */
export function formatDivergence(v) {
  const n = num(v)
  if (n == null) return null
  const pp = Math.round(n * 1000) / 10
  return {
    text: (pp > 0 ? '+' : '') + pp + 'pp',
    tone: pp > 0 ? 'pos' : (pp < 0 ? 'neg' : 'zero'),
  }
}

/** Market URLs render as live links — accept absolute http(s) only (no javascript:/data:). */
export function safeMarketUrl(value) {
  const url = str(value)
  return /^https?:\/\//i.test(url) ? url : ''
}

/** 'High' → 'high'; unknown non-empty → 'other'; absent/blank → ''. */
export function confidenceLevel(value) {
  const c = String(value == null ? '' : value).trim().toLowerCase()
  if (!c) return ''
  return (c === 'low' || c === 'medium' || c === 'high') ? c : 'other'
}

/**
 * i3 self-consistency interval: requires ordered bounds within [0,1]
 * (0 ≤ p_low ≤ p_high ≤ 1); anything else → null (point estimate only).
 * `source` carries interval_source provenance for the tooltip ('' when untagged).
 */
function intervalModel(raw) {
  const low = num(raw.p_low)
  const high = num(raw.p_high)
  if (low == null || high == null) return null
  if (low < 0 || high > 1 || low > high) return null
  return {
    lowText: formatProbability(low),
    highText: formatProbability(high),
    text: formatProbability(low) + '–' + formatProbability(high),
    source: str(raw.interval_source),
  }
}

/**
 * market_anchor → display model. Dropped (null) when nothing displayable
 * remains (neither an implied probability nor a market id).
 */
function anchorModel(raw) {
  const anchor = raw.market_anchor
  if (!isPlainObject(anchor)) return null
  const impliedText = formatProbability(anchor.implied_yes_prob)
  const marketId = str(anchor.market_id)
  if (!impliedText && !marketId) return null
  const matchConf = num(anchor.match_confidence)
  return {
    marketId,
    question: str(anchor.question),
    impliedText: impliedText || '—',
    priceText: formatProbability(anchor.price_at_research),
    divergence: formatDivergence(anchor.divergence),
    url: safeMarketUrl(anchor.url),
    equivalence: str(anchor.resolution_equivalence).toLowerCase(),
    matchConfidenceText: matchConf == null ? '' : String(Math.round(matchConf * 100) / 100),
    endDate: str(anchor.endDate),
  }
}

/**
 * market_influence stamp → badge model. The stamp survives anchor ejection
 * (extractor contract), so it is modeled independently of `anchor`:
 * anchorRemoved / probabilityRestored mirror the audit booleans strictly.
 */
function influenceModel(raw) {
  const inf = raw.market_influence
  if (!isPlainObject(inf)) return null
  return {
    marketId: str(inf.market_id),
    marketQuestion: str(inf.market_question),
    priorText: formatProbability(inf.prior_probability) || '—',
    revisedText: formatProbability(inf.revised_probability) || '—',
    anchorRemoved: inf.anchor_removed === true,
    probabilityRestored: inf.probability_restored === true,
  }
}

const COMPARATORS = Object.freeze({ '>': '>', '>=': '≥', '<': '<', '<=': '≤' })
// forecast_extractor._BASE_RATE_DIVERGENCE: binary_quality flags (never adjusts) a
// model probability more than 25 pp from its anchor's empirical base rate.
const BASE_RATE_DIVERGENCE = 0.25
// forecast_extractor._empirical_season: how the h-step sample of a monthly series without
// seasonal adjustment treats its seasons ('same_calendar_month', 'seasonal_profile' = the
// same-month seasonal mean plus pooled deviations, or 'all_start_months'). Every display of
// the rate discloses it, and binary_quality never flags a rate that pools the seasons
// ('all_start_months').
const SEASONAL_BASES = new Set(['same_calendar_month', 'seasonal_profile', 'all_start_months'])

function round9(n) {
  return Math.abs(n) < 1e21 ? Number(n.toFixed(9)) : n
}

function holds(value, comparator, threshold) {
  const v = round9(value)
  const t = round9(threshold)
  return { '>': v > t, '>=': v >= t, '<': v < t, '<=': v <= t }[comparator]
}

/**
 * data_anchor.empirical_base_rate (fix contract §1.8) → outside-view model:
 * p = share of historical h-step outcomes that satisfy the anchor.
 */
function baseRateModel(raw, probability, units, frequency, provenance) {
  if (!isPlainObject(raw)) return null
  const p = num(raw.p)
  if (p == null || p < 0 || p > 1) return null
  const n = num(raw.n)
  const h = num(raw.h)
  const window = isPlainObject(raw.window) ? raw.window : {}
  const quantiles = isPlainObject(raw.quantiles) ? raw.quantiles : {}
  const sigma = num(raw.sigma_distance)
  const seasonalBasis = SEASONAL_BASES.has(str(raw.seasonal_basis)) ? str(raw.seasonal_basis) : ''
  const model = num(probability)
  // Same gap as binary_quality (round(probability - p, 4)): 0.3 - 0.55 is
  // -0.25000000000000006 in floating point and must not read as over 25 pp.
  const gap = model == null ? null : roundHalfEven(model - p, 4)
  return {
    pText: formatProbability(p),
    n: Number.isInteger(n) ? n : null,
    h: Number.isInteger(h) ? h : null,
    windowText: str(window.start) && str(window.end)
      ? `${officialAnchorPeriodLabel(window.start, frequency, provenance)} – ${officialAnchorPeriodLabel(window.end, frequency, provenance)}`
      : '',
    sigmaText: sigma == null ? '' : String(sigma),
    rangeText: num(quantiles.p10) != null && num(quantiles.p90) != null
      ? `${formatOfficialValue(quantiles.p10, units)} – ${formatOfficialValue(quantiles.p90, units)}`
      : '',
    medianText: num(quantiles.p50) == null ? '' : formatOfficialValue(quantiles.p50, units),
    seasonalBasis,
    divergence: gap == null ? null : formatDivergence(gap),
    divergent: gap != null && seasonalBasis !== 'all_start_months' && Math.abs(gap) > BASE_RATE_DIVERGENCE,
  }
}

/**
 * data_anchor (admitted by forecast_extractor._admit_data_anchor) → display model:
 * threshold + period, the latest historical observation against the threshold,
 * and the empirical base rate when the history supports one. `officialSeries`
 * (officialSeriesIndex of the report's stored data) supplies the reader label and
 * the report's [S#]. Dropped (null) without a series, comparator or threshold.
 */
function dataAnchorModel(raw, officialSeries, lang) {
  const anchor = raw.data_anchor
  if (!isPlainObject(anchor)) return null
  const series = str(anchor.series)
  const threshold = num(anchor.threshold)
  const comparator = str(anchor.comparator)
  if (!series || threshold == null || !COMPARATORS[comparator]) return null
  const units = str(anchor.units)
  const frequency = str(anchor.frequency)
  const info = isPlainObject(officialSeries) && isPlainObject(officialSeries[series]) ? officialSeries[series] : {}
  // Fiscal-year rows read 'FY2027' for 2026-10-01, as the report does (stored carrier provenance).
  const provenance = isPlainObject(info.provenance) ? info.provenance : null
  const latest = num(anchor.latest_value)
  const latestDate = str(anchor.latest_date)
  // Percentage-point gaps read '个百分点' in zh, as in the report's indicator table.
  const gap = latest == null ? '' : formatOfficialChange(round9(threshold) - round9(latest), units)
  const gapText = String(lang || '').toLowerCase().startsWith('zh') && gap.endsWith(' pp')
    ? gap.slice(0, -3) + ' 个百分点'
    : gap
  return {
    series,
    label: str(info.label) || series,
    sourceId: str(info.sourceId),
    sourceUrl: safeSourceUrl(anchor.source_url) || str(info.sourceUrl),
    comparator,
    comparatorText: COMPARATORS[comparator],
    thresholdText: formatOfficialDisplay(threshold, units, lang),
    units,
    percentUnits: isPercentUnits(units),
    periodText: officialAnchorPeriodLabel(anchor.period, frequency, provenance) || str(anchor.observation),
    latestText: latest == null ? '' : formatOfficialDisplay(latest, units, lang),
    latestPeriod: latest == null ? '' : officialAnchorPeriodLabel(latestDate, frequency, provenance),
    gapText,
    met: latest == null ? null : holds(latest, comparator, threshold),
    baseRate: baseRateModel(anchor.empirical_base_rate, raw.probability, units, frequency, provenance),
  }
}

/**
 * One raw binary forecast → row model, or null when the entry has no usable
 * statement (a probability without a proposition is unreadable in a table).
 * `key` is always unique per list position even when ids collide.
 * Options: `officialSeries` (officialSeriesIndex: series id → {label, sourceId, sourceUrl, provenance}) and `lang`
 * ('en' | 'zh', for scaled magnitudes) shape the data-anchor model.
 */
export function binaryForecastRow(raw, index = 0, { officialSeries = null, lang = 'en' } = {}) {
  if (!isPlainObject(raw)) return null
  const statement = str(raw.statement)
  if (!statement) return null
  const id = str(raw.id)
  return {
    key: (id || 'bf') + '-' + index,
    id,
    statement,
    rationale: str(raw.adjustment_rationale),
    probabilityText: formatProbability(raw.probability) || '—',
    interval: intervalModel(raw),
    confidenceLevel: confidenceLevel(raw.confidence),
    confidenceRaw: String(raw.confidence == null ? '' : raw.confidence).trim(),
    anchor: anchorModel(raw),
    influence: influenceModel(raw),
    dataAnchor: dataAnchorModel(raw, officialSeries, lang),
  }
}

/** Forecast payload → row models. Missing/invalid `binary_forecasts` → []. */
export function binaryForecastRows(forecast, options = {}) {
  const list = isPlainObject(forecast) && Array.isArray(forecast.binary_forecasts)
    ? forecast.binary_forecasts
    : []
  const rows = []
  list.forEach((raw, i) => {
    const row = binaryForecastRow(raw, i, options)
    if (row) rows.push(row)
  })
  return rows
}
