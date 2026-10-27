import { downloadFilenameFromDisposition, hasPdfMagic } from './reportLanguages.js'

const STATES = new Set(['queued', 'running', 'completed', 'failed', 'interrupted', 'cancelled', 'stale'])
const SHA256 = /^[a-f0-9]{64}$/i
const JOB_ID = /^[a-zA-Z0-9_-]{1,160}$/

export const initialPdfExportState = () => ({ busy: false, state: '', phase: '', error: null })

export function pdfExportLabel(state, L) {
  if (!state.busy) return state.error?.retryable
    ? L('重试 PDF', 'Retry PDF') : L('下载 PDF', 'Download PDF')
  if (state.phase === 'downloading') return L('正在下载…', 'Downloading…')
  if (state.state === 'queued') return L('等待导出…', 'Waiting to export…')
  if (['planning', 'rendering', 'repairing'].includes(state.phase)) return L('正在排版…', 'Formatting…')
  if (['checking_content', 'reviewing_pages', 'publishing'].includes(state.phase)) return L('正在检查页面…', 'Checking pages…')
  return L('正在准备报告…', 'Preparing report…')
}

function savePdf(bytes, filename) {
  const url = URL.createObjectURL(new Blob([bytes], { type: 'application/pdf' }))
  const anchor = document.createElement('a')
  try {
    anchor.href = url
    anchor.download = filename
    anchor.style.display = 'none'
    document.body.appendChild(anchor)
    anchor.click()
  } finally {
    anchor.remove()
    setTimeout(() => URL.revokeObjectURL(url), 0)
  }
}

// The controller cancels observation/download only. It never claims to cancel a
// dispatched agent job, and only an explicit start/retry can issue another POST.
export function createResearchPdfExport({
  identity, startJob, getJob, downloadUrl, onChange,
  L = (_zh, en) => en,
  fetchFile = (...args) => fetch(...args), saveFile = savePdf,
  schedule = setTimeout, unschedule = clearTimeout,
  pollInterval = 1500, timeoutMs = 20 * 60 * 1000,
}) {
  let active = null
  let generation = 0
  const sameIdentity = (a, b) => a.kind === b.kind && a.resourceId === b.resourceId && a.lang === b.lang
  const current = run => active === run && run.generation === generation && sameIdentity(run.identity, identity())
  const publish = (run, value) => { if (current(run)) onChange(value) }
  const failure = (code, message, retryable = false) => Object.assign(new Error(message), { code, retryable })
  const identityError = () => failure('pdf_job_identity', L('导出任务与当前报告或语言不匹配', 'Export job does not match this report or language'))

  function validate(envelope, run, previous) {
    const job = envelope?.success === true ? envelope.data : null
    if (!job || job.kind !== run.identity.kind || job.resource_id !== run.identity.resourceId
        || job.requested_lang !== run.identity.lang || typeof job.job_id !== 'string' || !JOB_ID.test(job.job_id)
        || !SHA256.test(job.source_digest || '') || !['en', 'zh-CN'].includes(job.language)
        || (run.identity.lang && job.language !== (run.identity.lang === 'zh' ? 'zh-CN' : 'en'))
        || (previous && (job.job_id !== previous.job_id || job.source_digest !== previous.source_digest
          || job.language !== previous.language))) throw identityError()
    if (!STATES.has(job.state)) throw failure('pdf_job_state', L('服务器返回了无效的导出状态', 'Server returned an invalid export state'))
    return job
  }

  function wait(run) {
    return new Promise(resolve => {
      let timer
      const finish = () => {
        unschedule(timer)
        run.controller.signal.removeEventListener('abort', finish)
        resolve()
      }
      timer = schedule(finish, pollInterval)
      run.controller.signal.addEventListener('abort', finish, { once: true })
      if (run.controller.signal.aborted) finish()
    })
  }

  function cancel() {
    generation += 1
    const run = active
    active = null
    if (run) {
      unschedule(run.deadline)
      run.controller.abort()
    }
    onChange(initialPdfExportState())
  }

  async function start({ retry = false } = {}) {
    if (active && current(active)) return
    cancel()
    const selected = { ...identity() }
    if (!selected.resourceId || !['dossier', 'forecast'].includes(selected.kind)
        || ![null, 'en', 'zh'].includes(selected.lang)) return
    const run = { identity: selected, generation, controller: new AbortController() }
    active = run
    publish(run, { busy: true, state: 'running', phase: 'reading_source', error: null })
    run.deadline = schedule(() => {
      if (!current(run)) return
      publish(run, { busy: false, state: 'interrupted', phase: '', error: {
        code: 'pdf_wait_timeout', retryable: true,
        message: L('已停止等待，服务器上的导出可能仍在运行。可重试以查询或继续。', 'Stopped waiting; the server export may still be running. Retry to rejoin or continue.'),
      } })
      active = null
      run.controller.abort()
    }, timeoutMs)
    try {
      let response = await startJob(selected, { retry, signal: run.controller.signal })
      if (!current(run)) return
      let job = validate(response, run)
      while (current(run)) {
        publish(run, { busy: true, state: job.state, phase: job.phase, error: null })
        if (job.state === 'completed') {
          // Use only the resource/job-scoped URL. A server response cannot redirect
          // this consumer to a different report, the legacy route, or an external host.
          const expectedUrl = downloadUrl(selected, job.job_id)
          const resourcePath = downloadUrl(selected, job.job_id, { relative: true })
          const base = globalThis.location?.href || 'http://localhost/'
          const expected = new URL(expectedUrl, base)
          const advertised = typeof job.download_url === 'string' && job.download_url
            ? new URL(job.download_url, expected.origin) : null
          if (!advertised || (job.download_url !== resourcePath && advertised.href !== expected.href)) throw identityError()
          publish(run, { busy: true, state: job.state, phase: 'downloading', error: null })
          const file = await fetchFile(expectedUrl, {
            headers: { Accept: 'application/pdf' }, signal: run.controller.signal, redirect: 'error',
          })
          if (!current(run)) return
          if (!file.ok) {
            let payload
            try { payload = await file.json() } catch (_) { /* use the HTTP status */ }
            const detail = payload?.error && typeof payload.error === 'object' ? payload.error : payload
            throw failure(detail?.code || 'pdf_download_failed',
              detail?.message || (typeof payload?.error === 'string' ? payload.error : '')
                || L(`下载失败 (${file.status})`, `Download failed (${file.status})`),
              typeof detail?.retryable === 'boolean' ? detail.retryable : file.status >= 500)
          }
          const bytes = new Uint8Array(await file.arrayBuffer())
          if (!current(run)) return
          if (!hasPdfMagic(bytes)) throw failure('pdf_invalid_bytes', L('服务器返回的文件不是有效 PDF', 'Server returned an invalid PDF'), true)
          const fallback = `${selected.resourceId}${selected.lang ? `.${selected.lang}` : ''}.pdf`
          const filename = downloadFilenameFromDisposition(file.headers.get('content-disposition'), fallback)
          saveFile(bytes, filename)
          publish(run, { busy: false, state: 'completed', phase: '', error: null })
          return
        }
        if (!['queued', 'running'].includes(job.state)) {
          const retryable = typeof job.error?.retryable === 'boolean' ? job.error.retryable
            : ['interrupted', 'cancelled'].includes(job.state)
          throw failure(job.error?.code || `pdf_${job.state}`, job.error?.message
            || L('导出未完成，请检查报告后重试。', 'Export did not complete. Check the report and retry.'), retryable)
        }
        await wait(run)
        if (!current(run)) return
        response = await getJob(selected, job.job_id, { signal: run.controller.signal })
        if (!current(run)) return
        job = validate(response, run, job)
      }
    } catch (error) {
      if (!current(run)) return
      const payload = error?.response?.data
      const detail = payload?.error && typeof payload.error === 'object' ? payload.error : payload
      publish(run, { busy: false, state: 'failed', phase: '', error: {
        code: detail?.code || error.code || 'pdf_export_failed',
        message: detail?.message || (typeof payload?.error === 'string' ? payload.error : '')
          || error.message || L('导出失败', 'Export failed'),
        retryable: typeof detail?.retryable === 'boolean' ? detail.retryable
          : typeof error.retryable === 'boolean' ? error.retryable
            : !error.response || error.response.status >= 500,
      } })
    } finally {
      unschedule(run.deadline)
      if (active === run) active = null
    }
  }

  return { start, cancel }
}
