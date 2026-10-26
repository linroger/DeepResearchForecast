import {
  finalVariableRows, isUnusableRecord, limitsOf, recordHealth, recordPeriods,
  shareRows, synthesisOf, turningPointRows,
} from './simRecord.js'

const objects = value => (Array.isArray(value) ? value : []).filter(row => row && typeof row === 'object' && !Array.isArray(row))

// The record's rendered projection, never a recursive walk of its canonical JSON.
// Actor names, IDs, units, quantities, dates, references and hidden setup/provenance
// carriers stay in the source. Only the selected period's account is on screen.
export function simulationRecordTranslationTexts(record, selectedRound) {
  if (!record) return []
  const health = recordHealth(record)
  const limits = limitsOf(record)
  const texts = [record.banner, record.calendar_unit, health.health, health.validity, ...limits.notes]
  if (isUnusableRecord(record)) return texts.filter(value => typeof value === 'string' && value)

  const periods = recordPeriods(record)
  texts.push(...periods.flatMap(period => [period.label, period.arbiterStatus]))
  const period = periods.find(row => row.round === selectedRound)
  const rawPeriod = objects(record.periods).find(row => Number(row.round) === selectedRound)
  if (period) {
    texts.push(period.narrative, ...period.arbiterProblems, ...period.events, ...period.shocksFired,
      ...period.redLinesCrossed.map(row => row.text), ...period.alliances)
    const rawMoves = objects(rawPeriod?.moves)
    period.moves.forEach((move, index) => {
      const option = rawMoves[index]?.option
      // An option.id is an identity fallback, not a label to translate.
      if (!option || typeof option !== 'object' || option.label) texts.push(move.option)
      texts.push(move.publicStatement, move.terms, move.commitment?.text)
    })
    const rawFacts = objects(rawPeriod?.facts_changed)
    period.factsChanged.forEach((fact, index) => {
      if (rawFacts[index]?.variable || rawFacts[index]?.name) texts.push(fact.variable)
      texts.push(fact.cause)
    })
    for (const group of period.offers) {
      texts.push(group.status, ...group.offers.flatMap(offer => [offer.kind, offer.terms]))
    }
  }
  const rawVariables = objects(record.overall?.final_variables)
  finalVariableRows(record).forEach((row, index) => {
    if (rawVariables[index]?.name || rawVariables[index]?.variable) texts.push(row.name)
  })
  const synthesis = synthesisOf(record)
  texts.push(...shareRows(record).rows.map(row => row.name),
    ...turningPointRows(record).map(row => row.why), ...synthesis.paragraphs,
    ...limits.seedGaps, limits.behaviourNote)
  if (!['llm', 'deterministic'].includes(synthesis.generator)) texts.push(synthesis.generator)
  return [...new Set(texts.filter(value => typeof value === 'string' && value))]
}
