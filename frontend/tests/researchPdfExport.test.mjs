import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { createResearchPdfExport, pdfExportLabel } from '../src/utils/researchPdfExport.js'

const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { resolve, promise } }
const path = (id, jobId) => id.kind === 'dossier'
  ? `/api/research/${id.resourceId}/dossier/pdf-export/${jobId}/download`
  : `/api/report/${id.resourceId}/pdf-export/${jobId}/download`
function job(id, changes = {}) {
  const row = { job_id: 'pdf_job_1', kind: id.kind, resource_id: id.resourceId, requested_lang: id.lang,
    language: id.lang === 'zh' ? 'zh-CN' : 'en', source_digest: 'a'.repeat(64), state: 'completed',
    phase: 'publishing', progress: {}, error: null, download_url: path(id, 'pdf_job_1'), ...changes }
  return { success: true, data: row }
}
const pdf = (text = '%PDF-1.7 verified', filename = "attachment; filename*=UTF-8''verified.zh.pdf") => ({
  ok: true, headers: new Headers({ 'content-disposition': filename }),
  arrayBuffer: async () => new TextEncoder().encode(text).buffer,
})
function harness(t, overrides = {}) {
  let selected = overrides.selected || { kind: 'dossier', resourceId: 'pipe_A', lang: null }
  const states = [], starts = [], reads = [], files = [], downloads = []
  const controller = createResearchPdfExport({
    identity: () => selected, onChange: state => states.push(state), pollInterval: 0,
    startJob: async (id, options) => { starts.push({ id, options }); return job(id) },
    getJob: async (id, jobId, options) => { reads.push({ id, jobId, options }); return job(id) },
    downloadUrl: path, fetchFile: async (...args) => { files.push(args); return pdf() },
    saveFile: (...args) => downloads.push(args), ...overrides,
  })
  t.after(() => controller.cancel())
  return { controller, states, starts, reads, files, downloads,
    select: value => { selected = value }, state: () => states.at(-1) }
}

for (const kind of ['dossier', 'forecast']) for (const lang of [null, 'en', 'zh']) {
  test(`${kind} selected ${lang || 'source'} uses only its completed job download`, async t => {
    const id = { kind, resourceId: kind === 'dossier' ? 'pipe_A' : 'report_A', lang }
    const h = harness(t, { selected: id })
    await h.controller.start()
    assert.equal(h.starts.length, 1)
    assert.deepEqual(h.starts[0].id, id)
    assert.equal(h.files[0][0], path(id, 'pdf_job_1'))
    assert.equal(h.files[0][1].redirect, 'error')
    assert.equal(h.downloads[0][1], 'verified.zh.pdf')
    assert.equal(h.state().state, 'completed')
    assert.equal(h.reads.length, 0)
  })
}

test('queued/running poll without extra POST and retain job identity until download', async t => {
  let posts = 0, reads = 0
  const h = harness(t, {
    startJob: async id => { posts++; return job(id, { state: 'queued', download_url: null }) },
    getJob: async id => { reads++; return job(id, reads === 1 ? { state: 'running', phase: 'reviewing_pages', download_url: null } : {}) },
  })
  await h.controller.start()
  assert.equal(posts, 1)
  assert.equal(reads, 2)
  assert.equal(h.downloads.length, 1)
  assert.ok(h.states.some(s => s.phase === 'reviewing_pages'))
})

for (const mismatch of [
  { kind: 'forecast' }, { resource_id: 'pipe_B' }, { requested_lang: 'zh' },
  { language: 'fr' }, { source_digest: 'bad' }, { job_id: '../other' }, { state: 'unknown' },
  { download_url: '/api/research/pipe_A/dossier/pdf' }, { download_url: 'https://evil.example/file.pdf' },
]) test(`reject invalid start job ${JSON.stringify(mismatch)}`, async t => {
  const h = harness(t, { startJob: async id => job(id, mismatch) })
  await h.controller.start()
  assert.equal(h.state().state, 'failed')
  assert.equal(h.files.length, 0)
  assert.equal(h.downloads.length, 0)
})

for (const mismatch of [{ job_id: 'pdf_other' }, { source_digest: 'b'.repeat(64) }, { language: 'zh-CN' }]) {
  test(`reject status identity drift ${JSON.stringify(mismatch)}`, async t => {
    const h = harness(t, {
      startJob: async id => job(id, { state: 'running' }), getJob: async id => job(id, mismatch),
    })
    await h.controller.start()
    assert.equal(h.state().error.code, 'pdf_job_identity')
    assert.equal(h.files.length, 0)
  })
}

test('same-language primary Mandarin needs no translation file or explicit lang', async t => {
  const h = harness(t, { startJob: async id => job(id, { language: 'zh-CN' }) })
  await h.controller.start()
  assert.equal(h.starts.length, 0) // overridden transport above
  assert.equal(h.downloads.length, 1)
})

test('repeated click deduplicates, explicit retry is the only subsequent POST', async t => {
  const pending = deferred()
  const calls = []
  const h = harness(t, { startJob: (id, options) => { calls.push(options); return pending.promise } })
  const run = h.controller.start()
  await h.controller.start()
  assert.equal(calls.length, 1)
  pending.resolve(job({ kind: 'dossier', resourceId: 'pipe_A', lang: null }, {
    state: 'failed', error: { code: 'review_failed', message: 'Page review failed', retryable: true }, download_url: null,
  }))
  await run
  assert.equal(h.state().error.message, 'Page review failed')
  assert.equal(pdfExportLabel(h.state(), (_zh, en) => en), 'Retry PDF')
  await h.controller.start({ retry: true })
  assert.equal(calls.length, 2)
  assert.equal(calls[1].retry, true)
  assert.equal(h.downloads.length, 0)
})

for (const terminal of ['failed', 'interrupted', 'cancelled', 'stale']) {
  test(`${terminal} stops polling and never calls the old exporter`, async t => {
    const h = harness(t, { startJob: async id => job(id, { state: terminal, error: { code: terminal, message: 'Stopped', retryable: false } }) })
    await h.controller.start()
    assert.equal(h.state().busy, false)
    assert.equal(h.state().error.retryable, false)
    assert.equal(h.files.length + h.reads.length, 0)
  })
}

for (const stage of ['start', 'status', 'bytes']) {
  test(`cancel observation rejects late ${stage} completion without cancelling backend`, async t => {
    const pending = deferred()
    const h = harness(t, {
      startJob: id => stage === 'start' ? pending.promise : Promise.resolve(job(id, stage === 'status' ? { state: 'running' } : {})),
      getJob: () => pending.promise,
      fetchFile: async () => ({ ...pdf(), arrayBuffer: () => pending.promise }),
    })
    const run = h.controller.start()
    await new Promise(resolve => setTimeout(resolve, 5))
    h.controller.cancel()
    pending.resolve(stage === 'bytes' ? new TextEncoder().encode('%PDF-1.7').buffer
      : job({ kind: 'dossier', resourceId: 'pipe_A', lang: null }))
    await run
    assert.equal(h.downloads.length, 0)
    assert.equal(h.state().state, '')
  })
}

test('late request cleanup cannot clear a newer resource request', async t => {
  const first = deferred(), second = deferred()
  const h = harness(t, { startJob: id => id.resourceId === 'pipe_A' ? first.promise : second.promise })
  const a = h.controller.start()
  h.select({ kind: 'dossier', resourceId: 'pipe_B', lang: null })
  const b = h.controller.start()
  first.resolve(job({ kind: 'dossier', resourceId: 'pipe_A', lang: null }))
  await a
  assert.equal(h.state().busy, true)
  second.resolve(job({ kind: 'dossier', resourceId: 'pipe_B', lang: null }))
  await b
  assert.equal(h.downloads.length, 1)
})

test('observer deadline exposes honest retry and ignores a transport that never acknowledged abort', async t => {
  const pending = deferred()
  const h = harness(t, { startJob: () => pending.promise, timeoutMs: 5 })
  const run = h.controller.start()
  await new Promise(resolve => setTimeout(resolve, 15))
  assert.equal(h.state().error.code, 'pdf_wait_timeout')
  assert.match(h.state().error.message, /may still be running/)
  pending.resolve(job({ kind: 'dossier', resourceId: 'pipe_A', lang: null }))
  await run
  assert.equal(h.downloads.length, 0)
})

for (const [label, file, code] of [
  ['HTML with HTTP200', pdf('<html>Error</html>'), 'pdf_invalid_bytes'],
  ['publication 409', { ok: false, status: 409, json: async () => ({ error: { code: 'source_stale', message: 'Source changed', retryable: false } }) }, 'source_stale'],
  ['service 503', { ok: false, status: 503, json: async () => ({ error: 'Review unavailable' }) }, 'pdf_download_failed'],
]) test(`${label} is shown without download or fallback`, async t => {
  const h = harness(t, { fetchFile: async () => file })
  await h.controller.start()
  assert.equal(h.state().error.code, code)
  assert.equal(h.downloads.length, 0)
})

test('JSON transport failure preserves actionable backend error and retryability', async t => {
  const h = harness(t, { startJob: async () => { throw Object.assign(new Error('Request failed'), {
    response: { status: 503, data: { success: false, error: { code: 'review_unavailable', message: 'Configure a visual reviewer', retryable: false } } },
  }) } })
  await h.controller.start()
  assert.deepEqual(h.state().error, { code: 'review_unavailable', message: 'Configure a visual reviewer', retryable: false })
})

test('download honors an explicit non-retryable service error', async t => {
  const h = harness(t, { fetchFile: async () => ({ ok: false, status: 503,
    json: async () => ({ error: { code: 'configuration_missing', message: 'Configure the reviewer', retryable: false } }),
  }) })
  await h.controller.start()
  assert.equal(h.state().error.retryable, false)
  assert.equal(h.state().error.message, 'Configure the reviewer')
  assert.equal(h.downloads.length, 0)
})

test('configured API base prefix applies to the resource download, never to a foreign URL', async t => {
  const h = harness(t, { downloadUrl: (id, jobId, { relative = false } = {}) => relative ? path(id, jobId) : `https://api.example/prefix${path(id, jobId)}` })
  await h.controller.start()
  assert.equal(h.files[0]?.[0], 'https://api.example/prefix/api/research/pipe_A/dossier/pdf-export/pdf_job_1/download')
  assert.equal(h.downloads.length, 1)
})

for (const [module, names, base] of [
  ['research', ['startResearchPdfExport', 'getResearchPdfExport', 'researchPdfExportDownloadUrl'], '/api/research/pipe_A/dossier/pdf-export'],
  ['report', ['startReportPdfExport', 'getReportPdfExport', 'reportPdfExportDownloadUrl'], '/api/report/report_A/pdf-export'],
]) test(`${module} client keeps envelope and sends exact non-retrying job routes`, async () => {
  const calls = [], envelope = { success: true, data: { job_id: 'job_1' } }
  const service = { post: (...args) => { calls.push(['post', ...args]); return envelope }, get: (...args) => { calls.push(['get', ...args]); return envelope } }
  const source = readFileSync(new URL(`../src/api/${module}.js`, import.meta.url), 'utf8')
    .replace(/^import .*$/gm, '').replace(/^export \{[^}]*\}.*$/gm, '').replace(/export (const|function)/g, '$1')
  const api = new Function('service', 'apiUrl', `${source}\nreturn {${names.join(',')}}`)(service, rel => `https://api.example/prefix${rel}`)
  const signal = new AbortController().signal, id = module === 'research' ? 'pipe_A' : 'report_A'
  assert.equal(await api[names[0]](id, null, { signal }), envelope)
  await api[names[0]](id, 'zh', { retry: true, signal })
  await api[names[1]](id, 'job_1', { signal })
  assert.deepEqual(calls, [
    ['post', base, { lang: null }, { signal, timeout: 30000 }],
    ['post', base, { lang: 'zh', retry: true }, { signal, timeout: 30000 }],
    ['get', `${base}/job_1`, { signal, timeout: 30000 }],
  ])
  assert.equal(api[names[2]](id, 'job_1'), `https://api.example/prefix${base}/job_1/download`)
})
