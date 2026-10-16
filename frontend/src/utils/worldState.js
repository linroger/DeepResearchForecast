// Pure helpers for the World State panel (reflexive simulation).
// No DOM, no network: unit-tested with node:test.

const CURRENCY_CODES = new Set(['usd', 'eur', 'gbp', 'cny', 'rmb', 'jpy', 'hkd', 'aud', 'cad', '美元', '人民币', '元'])

function isCurrencyUnit(unit) {
  const u = String(unit || '').trim()
  if (!u) return false
  if (/[$€£¥￥]/.test(u)) return true
  return CURRENCY_CODES.has(u.toLowerCase())
}

function fmtNumber(v) {
  const av = Math.abs(v)
  if (av >= 1e12) return `${(v / 1e12).toFixed(2)} trillion`
  if (av >= 1e9) return `${(v / 1e9).toFixed(2)} billion`
  if (av >= 1e6) return `${(v / 1e6).toFixed(2)} million`
  if (av >= 1e4) return v.toLocaleString('en-US', { maximumFractionDigits: 0 })
  if (Number.isInteger(v)) return String(v)
  return String(Number(v.toFixed(2)))
}

/** Render a variable value with its unit the way the backend brief does. */
export function formatWorldValue(value, unit = '') {
  let s
  if (typeof value === 'boolean') s = value ? 'yes' : 'no'
  else if (typeof value === 'number' && Number.isFinite(value)) s = fmtNumber(value)
  else if (value === null || value === undefined) s = '—'
  else s = String(value).trim().slice(0, 120)
  const u = String(unit || '').trim()
  if (!u) return s
  if (u === '%') return `${s}%`
  if (isCurrencyUnit(u)) return `${u}${s}`
  return `${s} ${u}`
}

/** Change of a variable over its recorded history: { from, to, direction }. */
export function variableDelta(variable) {
  const hist = Array.isArray(variable && variable.history) ? variable.history : []
  if (hist.length < 2) return null
  const prev = hist[hist.length - 2]
  const last = hist[hist.length - 1]
  if (!prev || !last) return null
  const a = prev.value
  const b = last.value
  let direction = 'flat'
  if (typeof a === 'number' && typeof b === 'number') {
    direction = b > a ? 'up' : b < a ? 'down' : 'flat'
  } else if (a !== b) {
    direction = 'changed'
  }
  return { from: a, to: b, direction, cause: last.cause || '', round: last.round ?? null }
}

/** Latest history row (highest round), or null. */
export function latestHistoryRow(history) {
  const rows = Array.isArray(history) ? history.filter((r) => r && typeof r === 'object') : []
  if (!rows.length) return null
  return rows.reduce((best, r) => (best === null || Number(r.round || 0) >= Number(best.round || 0) ? r : best), null)
}

/** View model for the panel, built from the /world-state payload. Defensive against partial data. */
export function summarizeWorldState(data) {
  const d = data && typeof data === 'object' ? data : {}
  const latest = latestHistoryRow(d.history)
  const variables = (Array.isArray(d.variables) ? d.variables : [])
    .filter((v) => v && typeof v === 'object')
    .map((v) => {
      const delta = variableDelta(v)
      return {
        id: v.id,
        name: v.name || v.id || '',
        display: formatWorldValue(v.value, v.unit),
        kind: v.kind || 'text',
        provenance: v.provenance || '',
        delta,
        deltaDisplay: delta && delta.direction !== 'flat'
          ? `${formatWorldValue(delta.from, v.unit)} → ${formatWorldValue(delta.to, v.unit)}`
          : ''
      }
    })
    .sort((a, b) => Number(Boolean(b.delta && b.delta.direction !== 'flat')) - Number(Boolean(a.delta && a.delta.direction !== 'flat')))
  const committed = Number(d.committed_round || 0)
  const events = Array.isArray(d.recent_events) ? d.recent_events.filter((e) => e && typeof e === 'object') : []
  const moves = events
    .filter((e) => e.kind === 'action' && Number(e.round) === committed && !/holds position|no recorded move/.test(String(e.description || '')))
    .map((e) => ({
      actor: Array.isArray(e.actors) && e.actors.length ? e.actors[0] : 'Actor',
      description: String(e.description || ''),
      statement: String(e.statement || ''),
      targets: Array.isArray(e.targets) ? e.targets : []
    }))
  const consequences = events
    .filter((e) => e.kind !== 'action' && Number(e.round) === committed)
    .map((e) => ({ kind: e.kind || 'event', description: String(e.description || '') }))
  const diff = latest && latest.diff && typeof latest.diff === 'object' ? latest.diff : {}
  const relationshipChanges = (Array.isArray(diff.relationships_changed) ? diff.relationships_changed : [])
    .map((rc) => ({
      source: rc.source, target: rc.target, to: rc.to || '', direction: rc.direction || ''
    }))
  const pending = []
  for (const a of Array.isArray(d.actors) ? d.actors : []) {
    if (!a || typeof a !== 'object') continue
    for (const c of Array.isArray(a.pending_commitments) ? a.pending_commitments : []) {
      pending.push({ actor: a.name || `Agent ${a.agent_id}`, description: c.description || '', dueRound: c.due_round ?? null, status: c.status || 'pending' })
    }
  }
  for (const fx of Array.isArray(d.pending_effects) ? d.pending_effects : []) {
    if (fx && fx.description) pending.push({ actor: 'Expected', description: fx.description, dueRound: fx.due_round ?? null, status: 'effect' })
  }
  const summary = d.summary && typeof d.summary === 'object' ? d.summary : {}
  return {
    committedRound: committed,
    periodLabel: (d.period && d.period.label) || (latest && latest.period_label) || '',
    headline: String(d.headline || (latest && latest.headline) || ''),
    narrative: String((latest && latest.narrative) || d.digest || ''),
    arbiterStatus: (latest && latest.arbiter_status) || '',
    arbiterFailedRounds: Number(summary.arbiter_failed_rounds || 0),
    decisions: latest && latest.decisions && typeof latest.decisions === 'object' ? latest.decisions : null,
    variables,
    moves,
    consequences,
    relationshipChanges,
    pending,
    history: (Array.isArray(d.history) ? d.history : [])
      .filter((r) => r && typeof r === 'object')
      .slice()
      .sort((a, b) => Number(a.round || 0) - Number(b.round || 0))
      .map((r) => ({
        round: r.round, label: r.period_label || `#${r.round}`, headline: String(r.headline || ''),
        arbiterStatus: r.arbiter_status || '', factsChanged: Array.isArray(r.diff && r.diff.variables_changed) ? r.diff.variables_changed.length : 0
      }))
  }
}

/** Human label for an agency class id ("sovereign_government" → "sovereign government"). */
export function agencyLabel(klass) {
  return String(klass || '').replace(/_/g, ' ').trim()
}
