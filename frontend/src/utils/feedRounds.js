/**
 * Period view of the simulation feed: pure helpers shared by SimulationView and its tests.
 *
 * `rounds` are the rows of GET /api/simulation/<id>/feed-rounds
 * ({ round, period_label, headline, posts, comments }); `selectedRound` is null while the
 * feed follows the latest posts and a round number while one committed period is pinned.
 */

/** The label of a round: its period label, the given fallback, or `#<round>`. */
export function roundLabel(rounds, round, fallback = '') {
  const n = Number(round)
  if (!Number.isFinite(n)) return fallback || ''
  const row = (Array.isArray(rounds) ? rounds : []).find((r) => r && Number(r.round) === n)
  if (row && row.period_label) return String(row.period_label)
  return fallback || `#${n}`
}

/** Normalise what the World State panel emits (number, numeric string, null, undefined). */
export function selectionFromPanel(value) {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

/**
 * The posts/comments request for the current selection: the newest window when no period
 * is pinned, a whole period (server-side `round` filter, generous caps) when one is.
 */
export function feedRequest(selectedRound) {
  if (selectedRound === null || selectedRound === undefined) {
    return { round: null, limit: 60, commentLimit: 200 }
  }
  return { round: Number(selectedRound), limit: 500, commentLimit: 1000 }
}

/**
 * The note shown on a post card inside a pinned period when the post itself was written
 * in an earlier period (it appears because it was replied to this period): "posted in
 * <label>", or '' when nothing needs saying.
 */
export function postPeriodNote(post, selectedRound, rounds, prefix = 'posted in') {
  if (selectedRound === null || selectedRound === undefined || !post || typeof post !== 'object') return ''
  const own = Number(post.round)
  if (!Number.isFinite(own) || own === Number(selectedRound)) return ''
  return `${prefix} ${roundLabel(rounds, own)}`.trim()
}
