// Presentation only: this carrier never contributes to forecasts or market anchors.
export const MAX_SOURCE_CONTEXT_ITEMS = 12
export const MAX_SOURCE_CONTEXT_PROVIDERS = 24

const STATES = new Set([
  'ok', 'verified_empty', 'disabled', 'unavailable', 'forbidden', 'rate_limited',
  'timeout', 'budget_exhausted', 'partial', 'unsupported',
])
const KINDS = new Set(['news_snippet', 'social_post', 'market_quote', 'community_forecast'])
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const text = (value, limit = 240) => typeof value === 'string' ? value.trim().slice(0, limit) : ''
const number = value => typeof value === 'number' && Number.isFinite(value) ? String(value) : ''
const quoteValue = (quote, yesField, genericField) => number(Object.hasOwn(quote, yesField) ? quote[yesField] : quote[genericField])

export function safeSourceContextUrl(value) {
  if (typeof value !== 'string' || value.length > 2048) return ''
  const raw = value.trim()
  if (!/^https?:\/\//i.test(raw) || /[\u0000-\u0020\u007f\\]/.test(raw)) return ''
  try {
    const url = new URL(raw)
    return url.hostname && !url.username && !url.password ? url.href : ''
  } catch {
    return ''
  }
}

export function sourceContextTimestamp(value) {
  // Preserve explicit dates/offsets; never infer a timezone for an ambiguous date.
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))?$/.test(value)) return ''
  const day = value.slice(0, 10)
  const calendar = Date.parse(`${day}T00:00:00Z`)
  if (!Number.isFinite(calendar) || new Date(calendar).toISOString().slice(0, 10) !== day) return ''
  if (value.length === 10) return day
  const time = Date.parse(value)
  return Number.isFinite(time) ? new Date(time).toISOString() : ''
}

function normalizeItem(item, index) {
  const quote = record(item.quote) ? item.quote : item
  return {
    key: `${text(item.id)}:${index}`,
    provider: text(item.provider, 80),
    kind: item.kind,
    title: text(item.title, 320),
    url: safeSourceContextUrl(item.url),
    publisher: text(record(item.publisher) ? item.publisher.name : item.publisher),
    publishedAt: sourceContextTimestamp(item.published_at),
    retrievedAt: sourceContextTimestamp(item.retrieved_at),
    language: text(item.language, 24),
    sourceRef: text(item.source_ref, 40),
    snippet: text(item.snippet, 1200),
    // Render supplied quote values verbatim. Never infer a probability from a price,
    // social sentiment, missing quote, or community participation count.
    basis: text(quote.quote_basis),
    probabilityBasis: text(quote.probability_basis || quote.price_basis),
    units: text(quote.price_unit || quote.quote_units || quote.units, 100),
    outcome: text(quote.outcome, 100),
    quoteAt: sourceContextTimestamp(quote.quote_at),
    endAt: sourceContextTimestamp(item.end_date),
    rulesPrimary: text(item.rules_primary, 6000),
    rulesSecondary: text(item.rules_secondary, 6000),
    strikeType: text(item.strike_type, 100),
    floorStrike: number(item.floor_strike),
    capStrike: number(item.cap_strike),
    // Literal-Yes fields are supplied by normalize_kalshi_market. Explicit nulls
    // stay unknown even if a generic legacy alias is also present.
    bid: item.kind === 'market_quote' ? quoteValue(quote, 'yes_bid', 'bid') : '',
    ask: item.kind === 'market_quote' ? quoteValue(quote, 'yes_ask', 'ask') : '',
    last: item.kind === 'market_quote' ? quoteValue(quote, 'last_price', 'last') : '',
    forecasters: item.kind === 'community_forecast' && Number.isInteger(item.forecaster_count)
      && item.forecaster_count >= 0 ? String(item.forecaster_count) : '',
  }
}

export function sourceContextView(context, maxItems = MAX_SOURCE_CONTEXT_ITEMS) {
  const hidden = { visible: false, items: [], providers: [], totalItems: 0, hiddenProviders: 0 }
  if (!record(context) || context.schema_version !== 1 || context.enabled === false) return hidden
  const eligible = (Array.isArray(context.items) ? context.items : []).filter(item =>
    record(item) && KINDS.has(item.kind) && item.eligibility?.context_only === true)
  const providers = new Map()
  if (record(context.providers)) {
    for (const [provider, value] of Object.entries(context.providers)) {
      const status = record(value?.status) ? value.status : value
      providers.set(provider, {
        provider: text(provider, 80),
        state: STATES.has(status?.state) ? status.state : 'unavailable',
        attempted: typeof status?.attempted === 'boolean' ? status.attempted : null,
      })
    }
  }
  // An item without a provider status is not proof of a successful/empty search.
  for (const item of eligible) {
    const provider = text(item.provider, 80)
    if (provider && !providers.has(provider)) providers.set(provider, { provider, state: 'unavailable', attempted: null })
  }
  const statuses = [...providers.values()]
  if (!eligible.length && (!statuses.length || statuses.every(status => status.state === 'disabled'))) return hidden
  const limit = Number.isInteger(maxItems) ? Math.min(MAX_SOURCE_CONTEXT_ITEMS, Math.max(1, maxItems)) : MAX_SOURCE_CONTEXT_ITEMS
  return {
    visible: true,
    items: eligible.slice(0, limit).map(normalizeItem),
    providers: statuses.slice(0, MAX_SOURCE_CONTEXT_PROVIDERS),
    totalItems: eligible.length,
    hiddenProviders: Math.max(0, statuses.length - MAX_SOURCE_CONTEXT_PROVIDERS),
  }
}
