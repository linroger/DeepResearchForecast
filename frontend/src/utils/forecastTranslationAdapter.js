import { normalizeTranslationSnapshot, translationBody, translationTextDigest } from './translationJobAdapter.js'
import { normalizeReportTranslations, reportTranslationIssues, reportTranslationPartial } from './reportLanguages.js'

export { translationTextDigest }

const ACTIVE = new Set(['pending', 'processing', 'generating', 'queued', 'running', 'waiting_provider', 'in_progress', 'starting'])
const code = value => String(value || '').trim().toLowerCase()

function checkSignal(signal) {
  if (signal?.aborted) throw Object.assign(new Error('Request cancelled'), { name: 'AbortError' })
}

function validateResource(data, identity, { translation = false } = {}) {
  const jobIdentity = data.translation_job?.identity || {}
  if ((data.report_id && data.report_id !== identity.reportId)
      || (translation && data.target_lang && data.target_lang !== identity.targetLang)
      || (jobIdentity.ref_id && jobIdentity.ref_id !== identity.reportId)
      || (jobIdentity.report_id && jobIdentity.report_id !== identity.reportId)
      || (jobIdentity.target_lang && jobIdentity.target_lang !== identity.targetLang)
      || (identity.sourceHash && jobIdentity.source_markdown_sha256
        && jobIdentity.source_markdown_sha256 !== identity.sourceHash)) {
    throw Object.assign(new Error('Translation response does not match the current report or language'), { retryable: false })
  }
}

export function forecastStructuredState(data = {}) {
  return data.structured_translation || data.translation_status
    || data.display?.structured_translation || data.display?.translation_status || {}
}

/** Resource compatibility belongs here; the shared observer owns every timer/epoch. */
export function normalizeForecastTranslation(report, progress = {}, fields = {}, identity = {}) {
  const body = report.translation_status || {}
  const structured = identity.selectedLang ? forecastStructuredState(fields)
    : progress.structured_translation || body.structured_translation || {}
  const available = normalizeReportTranslations(report).some(row => row.lang === identity.targetLang)
  const bodyPartial = Boolean(reportTranslationPartial(report, identity.targetLang))
  const structuredPartial = structured.partial === true || structured.complete === false
    || (Boolean(identity.selectedLang && fields.forecast) && fields.localization?.complete !== true)
    || (Boolean(identity.selectedLang && report.news_market_context) && !fields.display?.news_market_context)
  const partial = bodyPartial || structuredPartial
  const bodyState = code(progress.status || body.status) || 'missing'
  const structuredState = code(structured.status)
  const legacyState = ACTIVE.has(bodyState) ? bodyState
    : ACTIVE.has(structuredState) ? structuredState
      : ['failed', 'interrupted', 'cancelled'].includes(bodyState) ? bodyState
        : partial ? 'partial' : available ? 'completed' : bodyState
  const job = progress.translation_job || report.translation_job || body.translation_job || structured.translation_job
  const allowed = body.can_generate === true && progress.can_generate !== false
  const issues = [...new Set([
    ...reportTranslationIssues(progress), ...reportTranslationIssues(body), ...reportTranslationIssues(structured),
  ])]
  // A task can cover only one page. Prefer the full artifact inventory when present;
  // legacy { complete: boolean } coverage is not a measured inventory.
  const coverage = [structured.coverage, body.coverage, progress.coverage, job?.coverage]
    .find(value => value && ['total', 'required', 'total_units'].some(key => value[key] != null))
  const snapshot = normalizeTranslationSnapshot({ ...progress, status: job ? undefined : progress.status, translation_job: job }, {
    state: legacyState, available, partial, issues,
    coverage,
    actions: {
      start: allowed && !available && bodyState === 'missing',
      retry: allowed && (partial || (!available && bodyState !== 'missing')),
      refresh: allowed && available && body.can_update === true,
    },
  })
  // Execution completion alone never admits a Markdown publication.
  return { ...snapshot, available, partial, actions: { ...snapshot.actions,
    start: job?.actions?.start ?? (allowed && !available && bodyState === 'missing'),
    refresh: job?.actions?.refresh ?? (allowed && available && body.can_update === true),
  }, data: { report, progress, fields, structured, bodyPartial } }
}

/** API functions are injected so this transport can be exercised without a backend. */
export function createForecastTranslationAdapter(identity, api) {
  let taskId = ''
  let markdownCache = null
  const request = async (fn, args, signal) => {
    checkSignal(signal)
    const result = await fn(...args)
    checkSignal(signal)
    if (result?.success === false) throw new Error(result.error || 'Report request failed')
    return result
  }
  const readReport = async signal => {
    const report = translationBody(await request(api.getReport, [identity.reportId], signal))
    validateResource(report, identity)
    validateResource(report.translation_status || {}, identity, { translation: true })
    if (report.report_id !== identity.reportId) throw Object.assign(new Error('Report response is missing its resource identity'), { retryable: false })
    return report
  }
  const sourceChanged = report => (report.markdown_content || '') !== identity.sourceMarkdown
    || (report.translation_status?.source_markdown_sha256 || '') !== identity.sourceHash
  async function read({ signal }, suppliedReport = null, suppliedProgress = null) {
    let report = suppliedReport || await readReport(signal)
    if (sourceChanged(report)) {
      return { ...normalizeForecastTranslation(report, {}, {}, identity), active: false,
        data: { report, sourceChanged: true } }
    }
    const body = report.translation_status || {}
    let progress = suppliedProgress || body
    if (!suppliedProgress && identity.targetLang && body.report_id === identity.reportId
        && !body.translation_job && !report.translation_job) {
      progress = translationBody(await request(api.getReportTranslationStatus,
        [identity.reportId, identity.targetLang, taskId || body.task_id], signal))
      if ((taskId || !normalizeReportTranslations(report).some(row => row.lang === identity.targetLang))
          && (progress.available === true || ['completed', 'available'].includes(code(progress.status)))) {
        report = await readReport(signal)
      }
    }
    validateResource(progress, identity, { translation: true })
    if (identity.sourceHash && progress.source_markdown_sha256
        && progress.source_markdown_sha256 !== identity.sourceHash) {
      throw new Error('Translation status source changed; checking current report metadata')
    }
    if (sourceChanged(report)) return { ...normalizeForecastTranslation(report, {}, {}, identity), active: false,
      data: { report, sourceChanged: true } }
    if (progress.task_id) taskId = progress.task_id
    const key = identity.selectedLang || identity.sourceLang || ''
    const admitted = normalizeReportTranslations(report).find(row => row.lang === identity.selectedLang)
    const optional = async (fn, args) => {
      try { return translationBody(await request(fn, args, signal)) }
      catch (error) {
        // Old reports can legitimately lack optional display/official artifacts.
        // Transport failures must escape so the observer can reconnect.
        if ([404, 409].includes(error?.response?.status)) return {}
        throw error
      }
    }
    const [fields, official, markdown] = await Promise.all([
      optional(api.getForecast, [identity.reportId, key || undefined]),
      optional(api.getReportOfficialData, [identity.reportId, key || undefined]),
      admitted ? (async () => {
        const generationId = admitted.generation_id || report.translation_status?.generation_id || ''
        const expectedSha = admitted.markdown_sha256.toLowerCase()
        if (markdownCache?.sha === expectedSha && markdownCache.generationId === generationId) return markdownCache.text
        const raw = await request(api.getReportTranslationMd,
          [identity.reportId, identity.selectedLang, { signal, generationId }], signal)
        const text = typeof raw === 'string' ? raw : raw?.data
        if (typeof text !== 'string' || !text.trim()) throw new Error('Language variant is empty or unavailable')
        const actualSha = await translationTextDigest(text)
        checkSignal(signal)
        if (actualSha !== expectedSha) {
          // Leave any prior admitted bytes intact. The shared observer reconnects
          // by GET and obtains fresh metadata; it never repeats a mutation here.
          throw new Error('Translation publication changed while reading Markdown; checking the current publication')
        }
        markdownCache = { sha: actualSha, generationId, text }
        return text
      })() : null,
    ])
    checkSignal(signal)
    validateResource(fields, identity)
    validateResource(official, identity)
    const snapshot = normalizeForecastTranslation(report, progress, fields, identity)
    if (!snapshot.active) taskId = ''
    snapshot.data = { ...snapshot.data, official, markdown, key }
    return snapshot
  }
  return {
    get: read,
    async start({ signal, force = false, action = 'start' }) {
      const report = await readReport(signal)
      if (sourceChanged(report)) throw new Error('Report source changed; check status before starting translation')
      const body = report.translation_status || {}
      if (body.report_id !== identity.reportId || body.target_lang !== identity.targetLang) {
        throw Object.assign(new Error('Current translation state does not match this report or language'), { retryable: false })
      }
      // Admit against the same full resource/status/display read that offered the
      // control. Body-only metadata omits structured partial work, so rebuilding
      // actions from it can incorrectly reject the visible ordinary Retry.
      const fresh = await read({ signal }, report)
      if (fresh.data.sourceChanged) throw new Error('Report source changed; check status before starting translation')
      if (fresh.active) return fresh
      const currentBody = fresh.data.report.translation_status || {}
      const permitted = fresh.actions[action] === true
        || (!fresh.job && currentBody.can_generate === true && fresh.data.progress.can_generate !== false
          && !force && fresh.available)
      if (!permitted) throw Object.assign(new Error('The current report does not permit this translation action'), { retryable: false })
      const progress = translationBody(await request(api.requestReportTranslation,
        [identity.reportId, identity.targetLang, force === true], signal))
      validateResource(progress, identity, { translation: true })
      if (progress.task_id) taskId = progress.task_id
      // Re-read publication metadata; a task's available flag is not admission.
      return read({ signal }, await readReport(signal), progress)
    },
  }
}
