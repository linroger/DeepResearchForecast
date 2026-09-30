/**
 * Prediction-market snapshot status (`prediction_markets.json` `status`) for the
 * dossier's market panel.
 *
 * A lookup that failed, was cut short or timed out leaves market coverage
 * unknown, so an empty panel must not read as "no relevant market exists"
 * (RESEARCH-3). The labels match the backend's absence.market_status, which maps
 * them to "unavailable": the bridge writes `empty_reason`, the multi-track merge
 * also writes `state`.
 */

const LOOKUP_INCOMPLETE_LABELS = new Set([
  'transport_failure', 'partial_transport_failure', 'inflight_timeout',
])

function label(value) {
  return String(value || '').trim().toLowerCase()
}

/** True when the snapshot status says the market lookup failed or was incomplete. */
export function marketLookupIncomplete(status) {
  if (!status || typeof status !== 'object' || Array.isArray(status)) return false
  return LOOKUP_INCOMPLETE_LABELS.has(label(status.empty_reason))
    || LOOKUP_INCOMPLETE_LABELS.has(label(status.state))
}
