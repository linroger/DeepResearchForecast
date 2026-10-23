/**
 * Pure helpers for the Simulation After-Action Record (`simulation-record/v1`, ADR 0003).
 *
 * Simulation output is a `simulated` record class: never evidence, never a probability
 * input.  These helpers only reshape the record the gate published so the dashboard can
 * show it; they add no numbers, never call a share a probability, and tolerate missing or
 * malformed fields (an absent list renders as empty, never as a crash).  Companion of
 * SimulationRecordView.vue, as utils/worldState.js is of WorldStatePanel.vue.
 *
 * Field semantics: docs/handoff/simulation-after-action-record/design.md §4; the shape
 * contract is backend/app/services/simulation_record_contract.py.
 */
export const RECORD_SCHEMA = 'simulation-record/v1'
export const RECORD_CLASS = 'simulated'
// run_summary.simulation_health values for which Stage 5 writes a health stub and no
// narrative (design §3.1, invariant I-16); the view then states the exercise was unusable.
export const STUB_HEALTH = Object.freeze(['hollow', 'errored', 'truncated'])
// Offers are grouped in this order; statuses not listed follow alphabetically.
export const OFFER_STATUS_ORDER = Object.freeze(['accepted', 'countered', 'rejected', 'breached', 'lapsed', 'open', 'opened', 'deferred'])

const object = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const list = value => (Array.isArray(value) ? value : [])
const text = value => (value === null || value === undefined ? '' : String(value)).trim()
const int = value => {
  const n = Number(value)
  return value === null || value === undefined || value === '' || typeof value === 'boolean' || !Number.isFinite(n) ? null : Math.trunc(n)
}
const num = value => {
  const n = Number(value)
  return value === null || value === undefined || value === '' || typeof value === 'boolean' || !Number.isFinite(n) ? null : n
}

/** True for an object that carries the record schema and class the gate publishes. */
export function isSimulationRecord(value) {
  return object(value) && value.schema === RECORD_SCHEMA && value.record_class === RECORD_CLASS && Array.isArray(value.periods)
}

export function recordLanguage(record) {
  return text(record && record.language).toLowerCase().startsWith('zh') ? 'zh' : 'en'
}

/** Health block with the committed/planned counts; `null` where the record is silent. */
export function recordHealth(record) {
  const health = object(record && record.health) ? record.health : {}
  const seedGaps = health.seed_gaps
  return {
    health: text(health.simulation_health) || 'unknown',
    validity: text(health.validity) || 'unknown',
    arbiterFailedRounds: int(health.arbiter_failed_rounds),
    seedGaps: Array.isArray(seedGaps) ? seedGaps.length : int(seedGaps),
    organicActions: int(health.organic_actions),
    committed: int(record && record.rounds_committed),
    planned: int(record && record.rounds_planned),
  }
}

/** A hollow, errored, truncated or invalid run: the record is a health stub, not an account. */
export function isUnusableRecord(record) {
  const health = recordHealth(record)
  if (record?.limits?.stub === true || STUB_HEALTH.includes(health.health)) return true
  if (health.validity !== 'valid') return true
  return health.committed === 0
}

function eventText(event) {
  if (object(event)) return text(event.description || event.text || event.name || event.kind)
  return text(event)
}

function redLine(crossing) {
  if (object(crossing) && crossing.red_line) return {
    text: [text(crossing.actor), text(crossing.red_line)].filter(Boolean).join(': '),
    by: text(crossing.by),
  }
  return { text: eventText(crossing), by: '' }
}

function allianceText(shift) {
  if (object(shift) && shift.kind === 'alliance_move') {
    return `${text(shift.actor)}: ${text(shift.move)} → ${text(shift.target)}`
  }
  if (object(shift) && shift.kind === 'relationship') {
    return `${text(shift.source)} → ${text(shift.target)}: ${text(shift.from)} → ${text(shift.to)}`
  }
  return eventText(shift)
}

function normalizeMove(move) {
  const option = move.option
  const commitment = move.commitment
  let commitmentText = ''
  let commitmentDue = ''
  if (object(commitment)) {
    commitmentText = text(commitment.text || commitment.description)
    commitmentDue = text(commitment.due === undefined ? commitment.due_round : commitment.due)
  } else {
    commitmentText = text(commitment)
  }
  return {
    actor: text(move.actor || move.actor_name),
    option: object(option) ? text(option.label || option.id) : text(option),
    targets: list(move.targets).map(text).filter(Boolean),
    magnitude: num(move.magnitude),
    publicStatement: text(move.public_statement || move.statement),
    terms: text(move.terms),
    commitment: commitmentText ? { text: commitmentText, due: commitmentDue, duePeriods: object(commitment) ? int(commitment.due_periods) : null } : null,
  }
}

/** Offers of one period grouped by status in OFFER_STATUS_ORDER. */
export function offersByStatus(offers) {
  const groups = new Map()
  for (const offer of list(offers)) {
    if (!object(offer)) continue
    const status = text(offer.status) || 'unknown'
    if (!groups.has(status)) groups.set(status, [])
    groups.get(status).push({
      from: text(offer.from_actor || offer.from || offer.proposer),
      to: text(offer.to_actor || offer.to || offer.recipient),
      kind: text(offer.kind),
      status,
      terms: text(offer.terms),
    })
  }
  const rank = status => {
    const index = OFFER_STATUS_ORDER.indexOf(status)
    return index < 0 ? OFFER_STATUS_ORDER.length : index
  }
  return [...groups.keys()]
    .sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
    .map(status => ({ status, offers: groups.get(status) }))
}

/** Periods in round order, every list present, text fields trimmed. */
export function recordPeriods(record) {
  return list(record && record.periods)
    .filter(object)
    .map(period => {
      const round = int(period.round)
      const arbiterStatus = text(period.arbiter_status) || 'none'
      const offers = offersByStatus(period.offers)
      return {
        round,
        label: text(period.label) || (round === null ? '—' : `#${round}`),
        periodStart: text(period.period_start),
        periodEnd: text(period.period_end),
        arbiterStatus,
        arbiterProblems: list(period.arbiter_problems).map(text).filter(Boolean),
        // The compiler knows whether an arbiter applies to this engine; preserve that flag.
        mechanicalOnly: typeof period.mechanical_only === 'boolean' ? period.mechanical_only : arbiterStatus !== 'applied',
        narrative: text(period.narrative),
        moves: list(period.moves).filter(object).map(normalizeMove),
        heldPosition: list(period.held_position).map(text).filter(Boolean),
        factsChanged: list(period.facts_changed).filter(object).map(fact => ({
          variable: text(fact.variable || fact.name || fact.id),
          from: fact.from,
          to: fact.to,
          unit: text(fact.unit),
          cause: text(fact.cause),
        })),
        events: list(period.events).map(eventText).filter(Boolean),
        shocksFired: list(period.shocks_fired).map(eventText).filter(Boolean),
        redLinesCrossed: list(period.red_lines_crossed).map(redLine).filter(row => row.text),
        alliances: list(period.alliances).map(allianceText).filter(Boolean),
        offers,
        offerCount: offers.reduce((total, group) => total + group.offers.length, 0),
        behaviour: object(period.behaviour) ? period.behaviour : null,
      }
    })
    .sort((a, b) => (a.round === null ? 0 : a.round) - (b.round === null ? 0 : b.round))
}

/** The record reads chronologically: the first committed period opens by default. */
export function defaultPeriodRound(periods) {
  return list(periods).length ? periods[0].round : null
}

/** Keep a selection only while its period exists; otherwise fall back to the default. */
export function resolvePeriodRound(periods, round) {
  const wanted = int(round)
  return list(periods).some(period => period.round === wanted) ? wanted : defaultPeriodRound(periods)
}

/** `85.43 EUR/MWh`, `12%`, `true`, or the verbatim string; `—` when empty. */
export function formatQuantity(value, unit = '') {
  if (value === null || value === undefined || value === '') return '—'
  let shown
  if (typeof value === 'boolean') shown = value ? 'true' : 'false'
  // Preserve the stored quantity; rounding here can silently turn a real change into zero.
  else if (typeof value === 'number') shown = Number.isFinite(value) ? String(value) : '—'
  else shown = text(value)
  const u = text(unit)
  if (!u || typeof value === 'boolean') return shown
  return u === '%' ? `${shown}%` : `${shown} ${u}`
}

/** A simulated outcome share as a percentage string, e.g. `50.6%`; never the word probability. */
export function formatShare(value) {
  const n = num(value)
  if (n === null) return '—'
  return `${Math.round(n * 1000) / 10}%`
}

/** Final versus seed values for the overall section. */
export function finalVariableRows(record) {
  const overall = object(record && record.overall) ? record.overall : {}
  return list(overall.final_variables).filter(object).map(row => {
    const seed = row.seed_value
    const final = row.final_value
    const seedNum = num(seed)
    const finalNum = num(final)
    let direction = 'flat'
    if (seedNum !== null && finalNum !== null && finalNum !== seedNum) direction = finalNum > seedNum ? 'up' : 'down'
    else if (seedNum === null || finalNum === null) direction = text(seed) === text(final) ? 'flat' : 'changed'
    return {
      name: text(row.name || row.variable || row.id),
      unit: text(row.unit),
      seed: formatQuantity(seed, row.unit),
      final: formatQuantity(final, row.unit),
      direction,
    }
  })
}

/**
 * Final simulated shares per scenario, largest first, with the K-path spread when the
 * record carries more than one path.  Callers label them "share", never "probability".
 */
export function shareRows(record) {
  const overall = object(record && record.overall) ? record.overall : {}
  const shares = object(overall.shares) ? overall.shares : {}
  const final = object(shares.final) ? shares.final : {}
  const paths = object(shares.paths) ? shares.paths : {}
  const k = int(paths.k)
  const perScenario = object(paths.per_scenario) ? paths.per_scenario : {}
  const names = new Set([...Object.keys(final), ...Object.keys(perScenario)])
  const rows = [...names].map(name => {
    const stats = object(perScenario[name]) ? perScenario[name] : {}
    return {
      name,
      final: num(final[name]),
      finalText: formatShare(final[name]),
      mean: num(stats.mean),
      meanText: formatShare(stats.mean),
      sd: num(stats.sd),
      sdText: num(stats.sd) === null ? '' : formatShare(stats.sd),
      p10: num(stats.p10),
      p50: num(stats.p50),
      p90: num(stats.p90),
      spreadText: num(stats.p10) === null || num(stats.p90) === null ? '' : `${formatShare(stats.p10)} – ${formatShare(stats.p90)}`,
      p50Text: formatShare(stats.p50),
    }
  }).sort((a, b) => (b.final === null ? -1 : b.final) - (a.final === null ? -1 : a.final) || a.name.localeCompare(b.name))
  return {
    rows,
    k,
    hasPaths: k !== null && k > 1 && rows.some(row => row.spreadText),
    convergedAt: int(shares.converged_at),
  }
}

export function turningPointRows(record) {
  const overall = object(record && record.overall) ? record.overall : {}
  return list(overall.turning_points).filter(object).map(row => ({ round: int(row.round), why: text(row.why || row.reason) })).filter(row => row.why)
}

/** Breakers first, then lapsers, then by name (mirrors utils/worldState.js). */
export function trackRecordRows(record) {
  const overall = object(record && record.overall) ? record.overall : {}
  return list(overall.track_records).filter(object).map(row => ({
    actor: text(row.actor || row.name),
    kept: int(row.kept) || 0,
    lapsed: int(row.lapsed) || 0,
    broken: int(row.broken) || 0,
  })).filter(row => row.actor).sort((a, b) => b.broken - a.broken || b.lapsed - a.lapsed || a.actor.localeCompare(b.actor))
}

export function synthesisOf(record) {
  const overall = object(record && record.overall) ? record.overall : {}
  const synthesis = object(overall.synthesis) ? overall.synthesis : {}
  const body = text(synthesis.text)
  return {
    generator: text(synthesis.generator) || 'deterministic',
    text: body,
    paragraphs: body ? body.split(/\n{2,}/).map(part => part.trim()).filter(Boolean) : [],
  }
}

export function limitsOf(record) {
  const limits = object(record && record.limits) ? record.limits : {}
  const seedGaps = limits.seed_gaps
  return {
    arbiterFailedRounds: int(limits.arbiter_failed_rounds),
    seedGaps: Array.isArray(seedGaps) ? seedGaps.map(eventText).filter(Boolean) : [],
    seedGapCount: Array.isArray(seedGaps) ? seedGaps.length : int(seedGaps),
    behaviourNote: text(limits.behaviour_note),
    notes: list(limits.notes).map(eventText).filter(Boolean),
  }
}

/**
 * One line for a period's behaviour counters, e.g. `11 moves · 7 responsive · 2 offers
 * answered`; the caller passes localized labels.  Empty when the record has no counters.
 */
export function behaviourSummary(behaviour, labels) {
  if (!object(behaviour)) return ''
  const parts = []
  const moves = int(behaviour.moves)
  const responsive = int(behaviour.responsive_moves)
  const answered = int(behaviour.offers_answered)
  if (moves !== null) parts.push(`${moves} ${labels.moves}`)
  if (responsive !== null) parts.push(`${responsive} ${labels.responsive}`)
  if (answered !== null) parts.push(`${answered} ${labels.offersAnswered}`)
  return parts.join(' · ')
}

/** `3f2a…9c1d` for a SHA-256 shown inline; the full digest belongs in a title attribute. */
export function shortSha(sha, head = 8, tail = 4) {
  const value = text(sha)
  if (!value) return ''
  return value.length <= head + tail + 1 ? value : `${value.slice(0, head)}…${value.slice(-tail)}`
}
