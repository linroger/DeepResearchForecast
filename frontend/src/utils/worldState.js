// Pure helpers for the World State panel (reflexive simulation).
// No DOM, no network: unit-tested with node:test.

const CURRENCY_CODES = new Set(['usd', 'eur', 'gbp', 'cny', 'rmb', 'jpy', 'hkd', 'aud', 'cad', '美元', '人民币', '元'])
// Type names a model may echo into a variable's unit field ("yes boolean"). The backend blanks
// them on new runs; persisted runs can still carry them, so the formatter never prints one.
const KIND_NAME_UNITS = new Set([
  'numeric', 'categorical', 'boolean', 'text', 'number', 'num', 'int', 'integer', 'float', 'decimal',
  'bool', 'flag', 'string', 'str', 'category', 'enum', 'date', 'datetime', 'timestamp'
])

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
  if (!u || KIND_NAME_UNITS.has(u.toLowerCase())) return s
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

function objectRows(history) {
  return Array.isArray(history) ? history.filter((r) => r && typeof r === 'object') : []
}

function roundOf(row) {
  const n = Number(row && row.round)
  return Number.isFinite(n) ? n : null
}

function hasRound(history, round) {
  return objectRows(history).some((r) => roundOf(r) === round)
}

/** Latest history row (highest round), or null. */
export function latestHistoryRow(history) {
  const rows = objectRows(history)
  if (!rows.length) return null
  return rows.reduce((best, r) => (best === null || Number(r.round || 0) >= Number(best.round || 0) ? r : best), null)
}

/** Highest round among the history rows, or null when there is none. */
export function latestHistoryRound(history) {
  const row = latestHistoryRow(history)
  return row ? roundOf(row) : null
}

/**
 * The round the panel shows: the stored selection while that round still exists in the
 * history, otherwise the latest round (so a live refresh never resets a valid selection
 * and a vanished round — a rerun, a rotated artifact — falls back to the live world).
 */
export function resolveSelectedRound(history, selectedRound) {
  const latest = latestHistoryRound(history)
  if (selectedRound === null || selectedRound === undefined || latest === null) return latest
  const wanted = Number(selectedRound)
  return Number.isFinite(wanted) && hasRound(history, wanted) ? wanted : latest
}

/**
 * Stored selection after a tick is clicked: null means "follow the live world", so the
 * latest round (and an unknown one) maps to null and any past round pins that round.
 */
export function nextSelectedRound(history, round) {
  const latest = latestHistoryRound(history)
  const wanted = Number(round)
  if (!Number.isFinite(wanted) || latest === null || wanted === latest) return null
  return hasRound(history, wanted) ? wanted : null
}

/** "2026-12: 5 decisions · 2 facts changed · 4 events · arbiter=applied" — the headline without its narrative tail. */
export function headlineSummary(headline) {
  const parts = String(headline || '').split(' · ')
  const idx = parts.findIndex((p) => /^arbiter=/.test(p.trim()))
  return (idx >= 0 ? parts.slice(0, idx + 1) : parts).join(' · ').trim()
}

/** "5 decisions · 5 ok · 1 held": a round's decision counts; zero holds/failures/invalids are left out. */
export function decisionsSummary(decisions, labels = {}) {
  const d = decisions && typeof decisions === 'object' ? decisions : null
  if (!d || d.total === null || d.total === undefined || !Number.isFinite(Number(d.total))) return ''
  const lab = { decisions: 'decisions', ok: 'ok', held: 'held', failed: 'failed', invalid: 'invalid', ...labels }
  const parts = [`${Number(d.total)} ${lab.decisions}`]
  if (d.ok !== null && d.ok !== undefined && Number.isFinite(Number(d.ok))) parts.push(`${Number(d.ok)} ${lab.ok}`)
  for (const key of ['held', 'failed', 'invalid']) {
    const n = Number(d[key])
    if (d[key] !== null && d[key] !== undefined && Number.isFinite(n) && n > 0) parts.push(`${n} ${lab[key]}`)
  }
  return parts.join(' · ')
}

function textItems(list, max = 12) {
  if (!Array.isArray(list)) return []
  return list.slice(0, max).map((x) => {
    if (x && typeof x === 'object') return String(x.description || x.label || x.name || '').trim()
    return String(x ?? '').trim()
  }).filter(Boolean)
}

/** Readable tag for an event kind in the consequences list ("red_line" → "red line crossed"); other kinds pass through. */
export function eventKindLabel(kind, labels = {}) {
  const k = String(kind || '')
  const lab = { red_line: 'red line crossed', ...labels }
  return Object.prototype.hasOwnProperty.call(lab, k) && lab[k] ? String(lab[k]) : k
}

const TRACK_RECORD_COUNTS = ['kept', 'lapsed', 'broken', 'released', 'open']
const MOVE_OUTCOMES = ['success', 'partial', 'blocked', 'failed']

function countOf(value) {
  const n = Number(value)
  return value !== null && value !== undefined && typeof value !== 'boolean' && Number.isFinite(n) && n > 0 ? Math.floor(n) : 0
}

/**
 * TRACK RECORDS: one row per actor whose `track_record` (GET /world-state `actors[]`) holds a
 * resolved, released or open commitment or a resolved move. Breakers first: the most broken or
 * lapsed commitments (the agents' public brief ranks by the same sum), then the most broken, the
 * most resolved, the name. `resolved` = kept + lapsed + broken; `reliability` = kept / resolved.
 */
export function trackRecordRows(actors) {
  const rows = []
  for (const a of Array.isArray(actors) ? actors : []) {
    const rec = a && typeof a === 'object' ? a.track_record : null
    if (!rec || typeof rec !== 'object' || Array.isArray(rec)) continue
    const counts = {}
    for (const key of TRACK_RECORD_COUNTS) counts[key] = countOf(rec[key])
    const resolved = counts.kept + counts.lapsed + counts.broken
    const given = Number(rec.reliability)
    const reliability = !resolved ? null
      : (rec.reliability !== null && rec.reliability !== undefined && typeof rec.reliability !== 'boolean' && Number.isFinite(given)
          ? Math.max(0, Math.min(1, given)) : counts.kept / resolved)
    const outcomes = rec.outcomes && typeof rec.outcomes === 'object'
      ? MOVE_OUTCOMES.map((outcome) => ({ outcome, count: countOf(rec.outcomes[outcome]) })).filter((o) => o.count > 0)
      : []
    if (!resolved && !counts.released && !counts.open && !outcomes.length) continue
    rows.push({ actor: String(a.name || `Agent ${a.agent_id}`), ...counts, resolved, reliability, outcomes })
  }
  const failures = (r) => r.broken + r.lapsed
  return rows.sort((x, y) => failures(y) - failures(x) || y.broken - x.broken || y.resolved - x.resolved
    || (x.actor < y.actor ? -1 : x.actor > y.actor ? 1 : 0))
}

/**
 * "kept 1 of 3 (33%) · 1 broken · 1 lapsed · 2 open · moves: 2 succeeded, 1 blocked" for one
 * `trackRecordRows` row; zero buckets are left out. `labels.kept` takes {k} (kept) and {n} (resolved).
 */
export function trackRecordSummary(row, labels = {}) {
  if (!row || typeof row !== 'object') return ''
  const lab = {
    kept: 'kept {k} of {n}', broken: 'broken', lapsed: 'lapsed', released: 'released', open: 'open', moves: 'moves',
    success: 'succeeded', partial: 'partly succeeded', blocked: 'blocked', failed: 'failed', colon: ': ', separator: ', ',
    ...labels
  }
  const parts = []
  if (row.resolved > 0) {
    const pct = row.reliability !== null && row.reliability !== undefined ? ` (${Math.round(row.reliability * 100)}%)` : ''
    parts.push(String(lab.kept).replace('{k}', String(row.kept)).replace('{n}', String(row.resolved)) + pct)
  }
  for (const key of ['broken', 'lapsed', 'released', 'open']) {
    if (row[key] > 0) parts.push(`${row[key]} ${lab[key]}`)
  }
  const outcomes = Array.isArray(row.outcomes) ? row.outcomes : []
  if (outcomes.length) parts.push(`${lab.moves}${lab.colon}` + outcomes.map((o) => `${o.count} ${lab[o.outcome] || o.outcome}`).join(lab.separator))
  return parts.join(' · ')
}

/** RED LINES of a history row (`red_lines_crossed`), as consequence rows worded like the kernel's red_line events. */
function redLineConsequences(list) {
  return (Array.isArray(list) ? list : []).slice(0, 4)
    .filter((x) => x && typeof x === 'object' && x.actor && x.by && x.red_line)
    .map((x) => ({ kind: 'red_line', description: `${x.by} crossed ${x.actor}'s red line: ${x.red_line}` }))
}

/**
 * View model for the panel, built from the /world-state payload. Defensive against partial data.
 * `selectedRound` (null = follow the latest committed round) picks which history row the
 * narrative, arbiter verdict, decisions, moves, consequences, diff and digest describe; the
 * tracked variables, open commitments and track records always describe the latest world.
 */
export function summarizeWorldState(data, selectedRound = null) {
  const d = data && typeof data === 'object' ? data : {}
  const rows = objectRows(d.history).slice().sort((a, b) => Number(a.round || 0) - Number(b.round || 0))
  const committed = Number(d.committed_round || 0)
  const latestRow = latestHistoryRow(rows)
  const latestRound = latestRow ? roundOf(latestRow) : (committed || null)
  const shownRound = resolveSelectedRound(rows, selectedRound) ?? latestRound
  const isPast = shownRound !== null && latestRound !== null && shownRound !== latestRound
  const row = rows.find((r) => roundOf(r) === shownRound) || (isPast ? null : latestRow)
  const focusRound = shownRound ?? committed
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
  const events = Array.isArray(d.recent_events) ? d.recent_events.filter((e) => e && typeof e === 'object') : []
  const eventRounds = events.map((e) => Number(e.round)).filter((n) => Number.isFinite(n))
  // the API carries only the last N events: older rounds fall back to the history row's deterministic lists
  const eventsInWindow = eventRounds.length > 0 && focusRound >= Math.min(...eventRounds)
  const det = row && row.deterministic && typeof row.deterministic === 'object' ? row.deterministic : {}
  let moves = events
    .filter((e) => e.kind === 'action' && Number(e.round) === focusRound && !/holds position|no recorded move/.test(String(e.description || '')))
    .map((e) => ({
      actor: Array.isArray(e.actors) && e.actors.length ? e.actors[0] : 'Actor',
      description: String(e.description || ''),
      statement: String(e.statement || ''),
      targets: Array.isArray(e.targets) ? e.targets : []
    }))
  let consequences = events
    .filter((e) => e.kind !== 'action' && Number(e.round) === focusRound)
    .map((e) => ({ kind: e.kind || 'event', description: String(e.description || '') }))
  if (isPast && !eventsInWindow) {
    moves = textItems(det.actions).filter((a) => !/holds position|no recorded move/.test(a))
      .map((a) => ({ actor: '', description: a, statement: '', targets: [] }))
    consequences = [
      ...redLineConsequences(row && row.red_lines_crossed),
      ...textItems(det.effects_fired).map((x) => ({ kind: 'effect', description: x })),
      ...textItems(det.scheduled_events).map((x) => ({ kind: 'scheduled', description: x })),
      ...textItems(det.commitments_lapsed).map((x) => ({ kind: 'lapsed', description: x }))
    ]
  }
  // RED LINES lead the list (the card shows its first ten); the rest keep their order
  consequences = [...consequences.filter((c) => c.kind === 'red_line'), ...consequences.filter((c) => c.kind !== 'red_line')]
  const diff = row && row.diff && typeof row.diff === 'object' ? row.diff : {}
  const relationshipChanges = (Array.isArray(diff.relationships_changed) ? diff.relationships_changed : [])
    .filter((rc) => rc && typeof rc === 'object')
    .map((rc) => ({
      source: rc.source, target: rc.target, to: rc.to || '', direction: rc.direction || ''
    }))
  const variablesChanged = (Array.isArray(diff.variables_changed) ? diff.variables_changed : [])
    .filter((ch) => ch && typeof ch === 'object')
    .map((ch) => {
      let direction = 'changed'
      if (typeof ch.from === 'number' && typeof ch.to === 'number') direction = ch.to > ch.from ? 'up' : ch.to < ch.from ? 'down' : 'flat'
      return {
        id: ch.id, name: ch.name || ch.id || '', direction,
        display: `${formatWorldValue(ch.from, ch.unit)} → ${formatWorldValue(ch.to, ch.unit)}`
      }
    })
  const variablesAdded = (Array.isArray(diff.variables_added) ? diff.variables_added : [])
    .filter((nv) => nv && typeof nv === 'object')
    .map((nv) => ({ id: nv.id, name: nv.name || nv.id || '', display: formatWorldValue(nv.value, nv.unit) }))
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
  // OFFERS (consent mechanics): the latest view lists open offers and the newest settled ones;
  // a past period lists the offers whose status changed in that period (from the row's diff)
  const offers = isPast
    ? (Array.isArray(diff.interactions_changed) ? diff.interactions_changed : [])
        .filter((it) => it && typeof it === 'object')
        .map((it) => ({ id: String(it.id || ''), status: String(it.to || ''), proposer: String(it.proposer || ''),
          recipient: String(it.recipient || ''), terms: String(it.terms || ''), expiresRound: null, resolvedRound: shownRound }))
    : (Array.isArray(d.interactions) ? d.interactions : [])
        .filter((it) => it && typeof it === 'object')
        .map((it) => ({ id: String(it.id || ''), status: String(it.status || ''), proposer: String(it.proposer || ''),
          recipient: String(it.recipient || ''), terms: String(it.terms || ''),
          expiresRound: it.expires_round ?? null, resolvedRound: it.resolved_round ?? null }))
  const summary = d.summary && typeof d.summary === 'object' ? d.summary : {}
  const offerCounts = summary.offers && typeof summary.offers === 'object' ? summary.offers : null
  // MODELLING GAPS (what the seed could not ground) and BEHAVIOUR (textual responsiveness diagnostics)
  const seedGaps = (Array.isArray(d.seed_gaps) ? d.seed_gaps : [])
    .filter((g) => g && typeof g === 'object')
    .map((g) => ({ kind: String(g.kind || ''), subject: String(g.subject || ''), note: String(g.note || '') }))
  const behaviour = summary.behaviour && typeof summary.behaviour === 'object' && summary.behaviour.responsive_share !== null
    && summary.behaviour.responsive_share !== undefined
    ? { roundsScored: Number(summary.behaviour.rounds_scored || 0), moves: Number(summary.behaviour.moves || 0),
        responsiveMoves: Number(summary.behaviour.responsive_moves || 0),
        responsiveShare: Number(summary.behaviour.responsive_share), offersAnswered: Number(summary.behaviour.offers_answered || 0) }
    : null
  // EXPECTATIONS: of the reactions actors expected after their moves, how many the named actor
  // followed with a move one period later (counted apart from the move score; absent on older runs)
  const beh = summary.behaviour && typeof summary.behaviour === 'object' ? summary.behaviour : {}
  const expectationsChecked = countOf(beh.expectations_checked)
  const expectations = expectationsChecked
    ? { checked: expectationsChecked, reacted: Math.min(expectationsChecked, countOf(beh.expectations_reacted)) }
    : null
  // TRACK RECORDS describe the latest world; `trackRecordsAvailable` is false on runs whose API rows predate them
  const actorRows = Array.isArray(d.actors) ? d.actors : []
  const trackRecordsAvailable = actorRows.some((a) => a && typeof a === 'object' && a.track_record
    && typeof a.track_record === 'object' && !Array.isArray(a.track_record))
  const trackRecords = trackRecordRows(actorRows)
  const problems = textItems(row && row.arbiter_problems, 12)
  if (row && row.error) problems.push(String(row.error))
  const headline = isPast
    ? String((row && row.headline) || '')
    : String(d.headline || (row && row.headline) || '')
  return {
    committedRound: committed,
    latestRound,
    latestLabel: latestRow ? String(latestRow.period_label || `#${latestRow.round}`) : ((d.period && d.period.label) || ''),
    selectedRound: shownRound,
    isPast,
    periodLabel: isPast
      ? String((row && row.period_label) || `#${shownRound}`)
      : ((d.period && d.period.label) || (row && row.period_label) || ''),
    headline,
    headlineSummary: headlineSummary(headline),
    narrative: row ? String(row.narrative || '') : String(d.digest || ''),
    digest: String((row && row.digest) || (!isPast ? d.digest || '' : '')),
    arbiterStatus: (row && row.arbiter_status) || '',
    arbiterProblems: problems,
    arbiterFailedRounds: Number(summary.arbiter_failed_rounds || 0),
    decisions: row && row.decisions && typeof row.decisions === 'object' ? row.decisions : null,
    variables,
    variablesChanged,
    variablesAdded,
    moves,
    consequences,
    eventsInWindow,
    relationshipChanges,
    pending,
    offers,
    offerCounts,
    seedGaps,
    behaviour,
    expectations,
    trackRecords,
    trackRecordsAvailable,
    history: rows.map((r) => ({
      round: r.round, label: r.period_label || `#${r.round}`, headline: String(r.headline || ''),
      arbiterStatus: r.arbiter_status || '',
      factsChanged: Array.isArray(r.diff && r.diff.variables_changed) ? r.diff.variables_changed.length : 0,
      factsAdded: Array.isArray(r.diff && r.diff.variables_added) ? r.diff.variables_added.length : 0,
      isCurrent: roundOf(r) === latestRound,
      isSelected: roundOf(r) === shownRound
    }))
  }
}

/** Human label for an agency class id ("sovereign_government" → "sovereign government"). */
export function agencyLabel(klass) {
  return String(klass || '').replace(/_/g, ' ').trim()
}
