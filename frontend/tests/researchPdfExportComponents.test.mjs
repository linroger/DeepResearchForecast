import assert from 'node:assert/strict'
import test from 'node:test'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'
import * as markdown from '../src/utils/markdown.js'
import * as i18n from '../src/i18n.js'
import * as officialData from '../src/utils/officialData.js'
import * as reportLanguages from '../src/utils/reportLanguages.js'
import * as researchTranslation from '../src/utils/researchTranslation.js'
import * as vizManifest from '../src/utils/vizManifest.js'
import * as researchPdfExport from '../src/utils/researchPdfExport.js'
import { compileSfc } from './sfcHarness.mjs'

const buildDossier = compileSfc(new URL('../src/components/research/DossierViewer.vue', import.meta.url))
const buildForecast = compileSfc(new URL('../src/components/research/ForecastReport.vue', import.meta.url))
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { resolve, promise } }
const settle = () => new Promise(resolve => setImmediate(resolve))
const fail = () => { throw new Error('Unexpected old export or translation POST') }
const body = lang => lang === 'zh' ? '# 研究展望\n\n完整正文与表格。' : '# Research outlook\n\nComplete source body.'
function reportMeta(id, sourceLang) {
  const target = sourceLang === 'en' ? 'zh' : 'en'
  const row = { report_id: id, lang: target, source_lang: sourceLang, path: `full_report.${target}.md`,
    citations_path: `citations.${target}.json`, final_audit_path: `final_audit.${target}.json`,
    available: true, audit_verified: true, markdown_sha256: 'b'.repeat(64), source_markdown_sha256: 'a'.repeat(64) }
  return { report_id: id, status: 'completed', markdown_content: body(sourceLang), translations: [row],
    translation_status: { report_id: id, source_lang: sourceLang, target_lang: target, status: 'available',
      available: true, requested_lang: target, markdown_sha256: row.markdown_sha256, translation: row } }
}

async function harness(t, kind, { sourceLang = 'en', start, read, file } = {}) {
  i18n.locale.value = 'en'
  const starts = [], reads = [], files = [], downloads = [], unmounts = []
  const id = kind === 'dossier' ? 'pipe_A' : 'report_A'
  const base = kind === 'dossier' ? `/api/research/${id}/dossier/pdf-export` : `/api/report/${id}/pdf-export`
  const result = (lang, overrides = {}) => ({ success: true, data: {
    job_id: 'job_A', kind, resource_id: id, requested_lang: lang,
    language: (lang || sourceLang) === 'zh' ? 'zh-CN' : 'en', source_digest: 'c'.repeat(64),
    state: 'completed', phase: 'publishing', error: null, download_url: `${base}/job_A/download`, ...overrides,
  } })
  const startJob = async (...args) => { starts.push(args); return start ? start(...args) : result(args[1]) }
  const getJob = async (...args) => { reads.push(args); return read ? read(...args) : result(starts[0][1]) }
  const downloadUrl = (_id, jobId) => `${base}/${jobId}/download`
  const imports = {
    vue: { ...vue, onMounted: () => {}, onBeforeUnmount: cb => unmounts.push(cb), defineAsyncComponent: () => ({ render: () => null }) },
    '../../utils/markdown': markdown, '../../i18n': i18n, '../../utils/officialData': officialData,
    '../../utils/reportLanguages': reportLanguages, '../../utils/researchTranslation': researchTranslation,
    '../../utils/vizManifest': vizManifest, '../../utils/saveTextFile': { saveTextFile: fail },
    './BinaryForecastTable.vue': { default: { render: () => null } },
    '../../utils/researchPdfExport': { ...researchPdfExport, createResearchPdfExport: options => researchPdfExport.createResearchPdfExport({
      ...options, pollInterval: 0,
      fetchFile: async (...args) => {
        files.push(args)
        return file ? file(...args) : { ok: true, headers: new Headers({ 'content-disposition': 'attachment; filename="accepted.pdf"' }),
          arrayBuffer: async () => new TextEncoder().encode('%PDF-1.7 verified').buffer }
      },
      saveFile: (...args) => downloads.push(args),
    }) },
    '../../api/research': {
      editDossier: fail, researchChartUrl: () => '', getArtifact: fail, requestResearchTranslation: fail,
      getResearchTranslation: async (_id, lang) => ({ success: true, data: { available: true, status: 'available',
        target_lang: lang, source_lang: sourceLang, report: body(lang), structured_translation: { complete: true } } }),
      researchPdfUrl: fail, startResearchPdfExport: startJob, getResearchPdfExport: getJob, researchPdfExportDownloadUrl: downloadUrl,
    },
    '../../api/report': {
      getReport: async resource => ({ success: true, data: reportMeta(resource, sourceLang) }),
      getVizManifest: async () => ({ data: [] }), getForecast: async () => ({ data: { forecast: null } }),
      getReportOfficialData: async () => ({ data: { available: false } }), getSectionsPartial: fail,
      getReportTranslationMd: async (_id, lang) => body(lang), requestReportTranslation: fail, getReportTranslationStatus: fail,
      reportMarkdownUrl: resource => `/api/report/${resource}/download`, reportAssetUrl: () => '', reportPdfUrl: fail,
      startReportPdfExport: startJob, getReportPdfExport: getJob, reportPdfExportDownloadUrl: downloadUrl,
    },
  }
  const component = (kind === 'dossier' ? buildDossier : buildForecast)(imports)
  const props = vue.reactive(kind === 'dossier' ? { pipelineId: id, dossier: { has_report: true, report: body(sourceLang) }, artifactNames: [], editable: false } : { reportId: id })
  const scope = vue.effectScope()
  const state = scope.run(() => component.setup(props, { expose() {}, emit() {} }))
  if (kind === 'forecast') await state.load()
  t.after(() => { unmounts.forEach(fn => fn()); scope.stop(); i18n.locale.value = 'en' })
  return { state, props, starts, reads, files, downloads, result, unmounts,
    click: () => kind === 'dossier' ? state.downloadPdf() : state.downloadArtifact('pdf'),
    select: async lang => { if (kind === 'dossier') { state.switchReportLang(lang); await settle() } else await state.switchLang(lang) },
    html: () => renderToString(vue.createSSRApp({ ...component, setup: () => state }, props)),
  }
}

for (const kind of ['dossier', 'forecast']) for (const [sourceLang, selected] of [['en', null], ['en', 'zh'], ['zh', null], ['zh', 'en']]) {
  test(`${kind} original PDF button exports ${sourceLang} primary / ${selected || 'source'} selection`, async t => {
    const h = await harness(t, kind, { sourceLang })
    if (selected) await h.select(selected)
    const html = await h.html()
    assert.match(html, /<button[^>]*class="[^"]*pdf-btn/)
    assert.doesNotMatch(html, /href="[^"\s]*\/pdf(?:\?|\")/)
    await h.click()
    assert.equal(h.starts.length, 1)
    assert.deepEqual(h.starts[0].slice(0, 2), [kind === 'dossier' ? 'pipe_A' : 'report_A', selected])
    assert.equal(h.files.length, 1)
    assert.match(h.files[0][0], /\/pdf-export\/job_A\/download$/)
    assert.equal(h.downloads[0][1], 'accepted.pdf')
    assert.equal(h.state.pdfExport.value.busy, false)
  })
}

for (const kind of ['dossier', 'forecast']) {
  test(`${kind} busy phase deduplicates button clicks; failed job exposes explicit retry`, async t => {
    const pending = deferred()
    const h = await harness(t, kind, { start: () => pending.promise })
    const run = h.click()
    await h.click()
    assert.equal(h.starts.length, 1)
    assert.match(await h.html(), /role="status"/)
    pending.resolve(h.result(null, { state: 'failed', error: { code: 'review_failed', message: 'Review rejected the pages', retryable: true }, download_url: null }))
    await run
    const html = await h.html()
    assert.match(html, /role="alert"[^>]*>Review rejected the pages/)
    assert.match(html, /Retry PDF/)
    await h.click()
    assert.equal(h.starts[1][2].retry, true)
    assert.equal(h.files.length, 0)
  })

  for (const change of ['resource', 'language', 'source', 'unmount']) {
    test(`${kind} ${change} change invalidates pending start response`, async t => {
      const pending = deferred()
      const h = await harness(t, kind, { start: () => pending.promise })
      const run = h.click()
      const signal = h.starts[0][2].signal
      if (change === 'resource') {
        if (kind === 'dossier') h.props.pipelineId = 'pipe_B'
        else h.props.reportId = 'report_B'
      } else if (change === 'language') await h.select('zh')
      else if (change === 'source') {
        if (kind === 'dossier') h.props.dossier.report += '\nChanged source'
        else h.state.md.value += '\nChanged source'
      } else h.unmounts.forEach(fn => fn())
      assert.equal(signal.aborted, true)
      pending.resolve(h.result(null))
      await run
      assert.equal(h.files.length, 0)
      assert.equal(h.downloads.length, 0)
      assert.equal(h.state.pdfExport.value.busy, false)
    })
  }
}

test('dossier cannot start PDF with selected but unavailable translation', async t => {
  const h = await harness(t, 'dossier')
  h.state.activeReportLang.value = 'zh'
  await h.click()
  assert.equal(h.starts.length, 0)
})

test('forecast generation poll resets selected language even when both bodies are identical', async t => {
  const pending = deferred()
  const h = await harness(t, 'forecast', { start: () => pending.promise })
  h.state.langMdCache.value = { zh: h.state.md.value }
  h.state.activeLang.value = 'zh'
  const run = h.click()
  const signal = h.starts[0][2].signal
  await h.state.pollOnce()
  assert.equal(h.state.activeLang.value, null)
  assert.equal(signal.aborted, true)
  assert.equal(h.state.pdfExport.value.busy, false)
  pending.resolve(h.result('zh'))
  await run
  assert.equal(h.downloads.length, 0)
})

for (const kind of ['dossier', 'forecast']) for (const terminal of ['interrupted', 'cancelled']) {
  test(`${kind} explicitly retries ${terminal} job when error metadata is absent`, async t => {
    let h
    h = await harness(t, kind, { start: async (_id, lang, options) => h.result(lang,
      options.retry ? {} : { state: terminal, error: null, download_url: null }) })
    await h.click()
    assert.equal(h.state.pdfExport.value.error.retryable, true)
    assert.match(await h.html(), /Retry PDF/)
    await h.click()
    assert.equal(h.starts[1][2].retry, true)
    assert.equal(h.downloads.length, 1)
  })
}

test('forecast Markdown download remains on its original endpoint and does not start a PDF job', async t => {
  const h = await harness(t, 'forecast')
  const requests = [], links = []
  const oldFetch = globalThis.fetch, oldDocument = globalThis.document
  globalThis.fetch = async (...args) => { requests.push(args); return { ok: true,
    headers: new Headers({ 'content-disposition': 'attachment; filename="source.md"' }),
    arrayBuffer: async () => new TextEncoder().encode(body('en')).buffer } }
  globalThis.document = { body: { appendChild: a => links.push(a) }, createElement: () => ({ style: {}, click() {}, remove() {} }) }
  t.after(() => { globalThis.fetch = oldFetch; globalThis.document = oldDocument })
  await h.state.downloadArtifact('md')
  assert.equal(requests[0][0], '/api/report/report_A/download')
  assert.equal(requests[0][1].headers.Accept, 'text/markdown')
  assert.equal(links[0].download, 'source.md')
  assert.equal(h.starts.length, 0)
})
