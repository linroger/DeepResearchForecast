import { normalizeTranslationSnapshot, translationBody, translationTextDigest } from './translationJobAdapter.js'

const invalidSource = () => Object.assign(new Error('Translation source does not match the displayed dossier; reload before retrying'), { retryable: false })
const isDigest = value => typeof value === 'string' && /^[a-f0-9]{64}$/i.test(value)

export function dossierSourceDigest(sourceMarkdown, sourceSha) {
  if (sourceSha) {
    if (!isDigest(sourceSha)) throw invalidSource()
    return Promise.resolve(sourceSha.toLowerCase())
  }
  return translationTextDigest(sourceMarkdown)
}

// Availability is the dossier reader's publication/audit verdict, never a job's
// completion flag. Keep that boundary even when an attached job owns lifecycle.
export function normalizeDossierTranslation(raw, { lang, pipelineId, sourceSha, hasStructuredContent = false } = {}) {
  const data = translationBody(raw)
  if (raw?.success === false || data?.success === false) {
    throw new Error(data.error || raw.error || 'Translation request failed')
  }
  const identity = data.translation_job?.identity || data.job?.identity || {}
  if ([data.target_lang, identity.target_lang, data.structured_translation?.target_lang].some(target => target && target !== lang)) {
    const error = new Error('Translation language does not match the selection')
    error.retryable = false
    throw error
  }
  if (pipelineId && [data.pipeline_id, identity.ref_id, identity.pipeline_id].some(id => id && id !== pipelineId)) {
    const error = new Error('Translation resource or source does not match the selected dossier')
    error.retryable = false
    throw error
  }
  // Every current dossier read carries the raw source digest. Missing evidence is
  // not admission, even if a job completed or the body passed a different audit.
  if (!isDigest(sourceSha) || data.source_sha256 !== sourceSha
      || (identity.source_sha256 && identity.source_sha256 !== sourceSha)) throw invalidSource()
  const available = data.available === true && typeof data.report === 'string' && !!data.report.trim()
  const structured = data.structured_translation || {}
  const projection = data.dossier && typeof data.dossier === 'object' && !Array.isArray(data.dossier)
    ? data.dossier : null
  const partial = data.partial === true || data.markdown_partial === true || data.body_partial === true
    || (Array.isArray(data.verbatim_chunks) && data.verbatim_chunks.length > 0)
    || structured.complete === false || (available && hasStructuredContent && !projection)
  const coverage = structured.coverage
  return normalizeTranslationSnapshot(raw, {
    state: data.status === 'generating' || structured.status === 'generating' ? 'running' : data.status,
    available,
    partial,
    issues: Array.isArray(structured.issues) ? structured.issues : [],
    coverage: data.coverage || (coverage ? {
      total: coverage.total, accepted: coverage.accepted ?? coverage.translated,
      pending: coverage.pending ?? structured.pending,
    } : undefined),
  })
}

// Capture transport identity once per observer subscription. The shared observer
// supplies cancellation and rejects late responses, including post-start reads.
export function createDossierTranslationAdapter({ pipelineId, lang, sourceMarkdown, sourceSha, hasStructuredContent, get, start }) {
  let expectedSourceSha = ''
  let digestRequest
  const digest = () => digestRequest ||= dossierSourceDigest(sourceMarkdown, sourceSha).then(value => {
    expectedSourceSha = value
    return value
  })
  const normalize = raw => normalizeDossierTranslation(raw, { lang, pipelineId, sourceSha: expectedSourceSha, hasStructuredContent })
  const read = async signal => {
    const raw = await get(pipelineId, lang, { signal })
    if (!expectedSourceSha) await digest()
    const snapshot = normalize(raw)
    // GET is authoritative about publication absence. A POST acknowledgment,
    // however, may omit publication fields while replacing an admitted variant.
    return { ...snapshot, data: { ...snapshot.data,
      report: snapshot.available ? snapshot.data.report : '', dossier: snapshot.data.dossier ?? null } }
  }
  return {
    get: ({ signal }) => read(signal),
    start: async ({ signal, force }) => {
      if (!expectedSourceSha) await digest()
      if (signal.aborted) return null
      const snapshot = normalize(await start(pipelineId, lang, force, { signal }))
      // Compatibility POSTs can acknowledge an existing publication without
      // returning its audited Markdown. Read the publication before displaying it.
      if (snapshot.data.available === true && !snapshot.available && !signal.aborted) {
        return read(signal)
      }
      return snapshot
    },
  }
}
