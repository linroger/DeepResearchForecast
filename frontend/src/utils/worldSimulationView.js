// Display only the selected committed projection. Never reconstruct it from the
// trajectory or merge responses from different revisions or visibility modes.
export const WORLD_ENGINE = 'world-v1'
export const LEGACY_ENGINE = 'oasis-legacy'
export const WORLD_REQUEST_TIMEOUT_MS = 20000

const object = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const list = value => Array.isArray(value) ? value : []

export function savedSimulationEngine(state) {
  // Only an absent historical pin is legacy. Unknown/empty pins fail closed.
  return state?.simulation_engine === undefined ? LEGACY_ENGINE : state.simulation_engine
}

export function createRequestGate() {
  let current = null
  return {
    begin() {
      current?.abort()
      const controller = new AbortController()
      current = controller
      return { signal: controller.signal, isCurrent: () => current === controller }
    },
    invalidate() {
      current?.abort()
      current = null
    },
  }
}

export function readWorldResponse(response, request) {
  if (response?.success !== true) throw Object.assign(new Error('World request failed'), { code: response?.code })
  const data = response.data
  const validRound = value => Number.isInteger(value) && value >= 0 && value <= 1000
  const valid = object(data) && data.schemaVersion === 'world-result/v1' && data.engine === WORLD_ENGINE
    && data.simulationId === request.simulationId && typeof data.generationId === 'string' && !!data.generationId
    && (!request.generationId || data.generationId === request.generationId)
    && data.view === request.view && (data.actorId ?? null) === (request.actorId || null)
    && typeof data.revision === 'string' && !!data.revision
    && typeof data.selectedRevision === 'string' && !!data.selectedRevision
    && (!request.revision || data.revision === request.revision)
    && validRound(data.round) && validRound(data.committedRound) && validRound(data.totalRounds)
    && data.round <= data.committedRound && data.committedRound <= data.totalRounds
    && data.round === (request.round ?? data.committedRound)
    && object(data.world) && data.world.round === data.round
    && ['metrics', 'accounts', 'rules', 'relations', 'commitments', 'interactions'].every(key => object(data.world[key]))
    && ['events', 'decisions', 'resolutions', 'assumptions'].every(key => Array.isArray(data[key]))
  if (!valid) throw Object.assign(new Error('World response identity mismatch'), { code: 'view_mismatch' })
  return data
}

export function worldErrorCode(error) {
  return error?.response?.data?.code || error?.code || 'unavailable'
}

function visible(record, result) {
  return object(record) && (result.view === 'analyst' || record.visibility?.kind === 'public'
    || (result.view === 'actor' && record.visibility?.kind === 'actors'
      && list(record.visibility.actorIds).includes(result.actorId)))
}

export function projectWorldResult(result) {
  if (!result) return { sections: {}, decisions: [], events: [], commitments: [], interactions: [], assumptions: [], privateStates: [], actorIds: [] }
  const records = key => Object.entries(result.world[key] || {})
    .filter(([, record]) => visible(record, result)).map(([id, record]) => ({ ...record, id }))
  const sections = Object.fromEntries(['metrics', 'accounts', 'rules', 'relations'].map(key => [key, records(key)]))
  const events = list(result.events).filter(event => visible(event, result))
  const mayReadDecision = record => object(record) && (result.view === 'analyst'
    || (result.view === 'actor' && record.actorId === result.actorId))
  const resolutions = list(result.resolutions).filter(mayReadDecision)
  // Results contain cumulative history. Index once instead of rescanning every
  // event/resolution for every intent as committed rounds accumulate.
  const resolutionKey = (actorId, intentId) => JSON.stringify([actorId, intentId])
  const resolutionByIntent = new Map()
  for (const resolution of resolutions) {
    const key = resolutionKey(resolution.actorId, resolution.intentId)
    if (!resolutionByIntent.has(key)) resolutionByIntent.set(key, resolution)
  }
  const eventsByIntent = new Map()
  for (const event of events) {
    const id = event.sourceIntentId
    if (!id) continue
    if (!eventsByIntent.has(id)) eventsByIntent.set(id, [])
    eventsByIntent.get(id).push(event)
  }
  const decisions = list(result.decisions).filter(mayReadDecision).map(decision => ({
    ...decision,
    intents: list(decision.intents).map(intent => ({
      ...intent,
      resolution: resolutionByIntent.get(resolutionKey(decision.actorId, intent.intentId)),
      events: eventsByIntent.get(intent.intentId) || [],
    })),
  }))
  const commitments = records('commitments')
  const interactions = records('interactions')
  const privateStates = result.view === 'analyst'
    ? Object.entries(result.world.actorStates || {}).map(([actorId, state]) => ({ ...state, actorId }))
    : result.view === 'actor' && object(result.world.actorState) ? [{ ...result.world.actorState, actorId: result.actorId }] : []
  const actorIds = [...new Set([
    ...sections.accounts.map(row => row.ownerId), ...decisions.map(row => row.actorId),
    ...events.map(row => row.actorId), ...privateStates.map(row => row.actorId),
    ...commitments.flatMap(row => [row.actorId, ...list(row.participantIds)]),
    ...interactions.flatMap(row => [row.proposerId, ...list(row.recipientIds)]),
  ].filter(id => typeof id === 'string' && id && id !== 'external'))].sort()
  return { sections, decisions, events, commitments, interactions, privateStates, actorIds,
    assumptions: list(result.assumptions).filter(record => visible(record, result)) }
}

export function worldValue(value, unknown = 'Unknown') {
  if (value === null || value === undefined || value === '') return unknown
  // Keep decimal strings exact, and preserve zero and false.
  return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)
}
