// Compatibility belongs at the transport boundary. The observer only consumes
// this normalized snapshot; availability and job activity are independent.
export function translationBody(response) {
  return response?.data?.data ?? response?.data ?? response ?? {}
}

const ACTIVE = new Set(['pending', 'processing', 'generating', 'queued', 'running', 'in_progress',
  'in-progress', 'starting', 'waiting_provider', 'translating', 'reviewing', 'repairing', 'publishing', 'review_pending'])
const RETRY = new Set(['partial', 'failed', 'error', 'stale', 'outdated', 'interrupted', 'cancelled',
  'canceled', 'timeout', 'unavailable', 'missing', 'empty', 'budget_exhausted'])
const count = value => Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : 0

export function normalizeTranslationSnapshot(raw, overrides = {}) {
  const data = translationBody(raw)
  if (raw?.success === false || data?.success === false) throw new Error(data.error || raw.error || 'Translation request failed')
  const job = data.translation_job || data.job || null
  let state = String(job?.job_state || job?.state || job?.status || overrides.state || data.status || 'unavailable').toLowerCase()
  const known = ACTIVE.has(state) || RETRY.has(state) || ['available', 'completed', 'complete', 'succeeded', 'success', 'source_language', 'blocked', 'disabled', 'unsupported', 'cooldown', 'cancel_requested'].includes(state)
  if (!known) state = 'error'
  const active = ACTIVE.has(state)
  if (!active && ['completed', 'complete', 'succeeded', 'success'].includes(state) && data.status && !ACTIVE.has(data.status)) state = data.status
  const available = overrides.available ?? (data.available === true || data.status === 'available' || data.status === 'empty')
  const partial = overrides.partial ?? (data.partial === true || data.structured_translation?.complete === false || data.status === 'partial')
  const c = overrides.coverage || data.coverage || (data.total_candidates != null ? {} : job?.coverage) || {}
  const total = count(c.total ?? c.required ?? c.total_units ?? data.total_candidates)
  const accepted = count(c.accepted ?? c.translated ?? c.completed ?? c.accepted_units ?? data.translated ?? data.cached)
  const pending = Math.max(total - accepted, count(c.pending ?? c.pending_units ?? data.pending ?? (c.pending_translation != null || c.pending_review != null || c.failed != null
    ? count(c.pending_translation) + count(c.pending_review) + count(c.failed) : Math.max(0, total - accepted))))
  const supplied = job?.actions || overrides.actions || data.actions
  const allowed = (name, fallback) => Array.isArray(supplied) ? supplied.includes(name)
    : supplied && name in supplied ? supplied[name] === true : fallback
  const issues = [...new Set([...(overrides.issues || []), ...(Array.isArray(data.issues) ? data.issues : []),
    ...(Array.isArray(job?.issues) ? job.issues : []), job?.error?.message || (typeof job?.error === 'string' ? job.error : '')].filter(Boolean))]
  if (!known) issues.push('Unrecognized translation status; please retry')
  return { state, active, available, partial, issues, refreshPending: count(data.refresh_pending ?? c.refresh_pending), coverage: { total, accepted, pending },
    actions: { start: allowed('start', !active && !available),
      retry: allowed('retry', !active && (partial || RETRY.has(state))),
      refresh: allowed('refresh', !active && available), stop: allowed('stop', false) }, data, job }
}

// Hash exactly the UTF-8 source/Markdown bytes returned to the displayed view.
export async function translationTextDigest(text) {
  const bytes = new TextEncoder().encode(text)
  return [...new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', bytes))]
    .map(byte => byte.toString(16).padStart(2, '0')).join('')
}
