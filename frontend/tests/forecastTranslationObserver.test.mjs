import assert from 'node:assert/strict'
import test from 'node:test'
import { setTimeout as realSetTimeout, clearTimeout as realClearTimeout } from 'node:timers'
import { createHash } from 'node:crypto'
import * as vue from 'vue'
import { readFileSync } from 'node:fs'
import * as observer from '../src/composables/useTranslationJob.js'
import * as adapter from '../src/utils/forecastTranslationAdapter.js'
import * as binaryForecasts from '../src/utils/binaryForecasts.js'
import * as i18n from '../src/i18n.js'
import * as markdown from '../src/utils/markdown.js'
import * as officialData from '../src/utils/officialData.js'
import * as reportLanguages from '../src/utils/reportLanguages.js'
import * as vizManifest from '../src/utils/vizManifest.js'
import * as sourceContext from '../src/utils/sourceContext.js'
import { compileSfc } from './sfcHarness.mjs'

const buildReport = compileSfc(new URL('../src/components/research/ForecastReport.vue', import.meta.url))
const buildTable = compileSfc(new URL('../src/components/research/BinaryForecastTable.vue', import.meta.url))
const buildPanel = compileSfc(new URL('../src/components/research/SourceContextPanel.vue', import.meta.url))
const settle = async () => { for (let i = 0; i < 3; i++) { await new Promise(resolve => setImmediate(resolve)); await vue.nextTick() } }
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { resolve, reject, promise } }
const sha = 'a'.repeat(64)
const digest = text => createHash('sha256').update(text, 'utf8').digest('hex')
const translatedMarkdown = lang => lang === 'zh' ? '# 已审核中文\n\n译文正文。' : '# Reviewed English\n\nAccepted translation.'
function job(state, extra = {}) {
  return { schema: 'translation-job/v2', job_id: 'tj_forecast', job_revision: 2, job_state: state,
    actions: { retry: ['failed', 'interrupted', 'partial'].includes(state), stop: state === 'running' },
    coverage: { required: 3, accepted: 1, pending_translation: 1, pending_review: 1, failed: 0, reused: 1 }, ...extra }
}
function report({ id = 'report_A', source = 'en', available = true, partial = false, state = null, translationJob = null } = {}) {
  const target = source === 'en' ? 'zh' : 'en'
  const translation = { report_id: id, lang: target, source_lang: source, available,
    path: `full_report.${target}.md`, citations_path: `citations.${target}.json`, final_audit_path: `final_audit.${target}.json`,
    source_markdown_sha256: sha, markdown_sha256: digest(translatedMarkdown(target)), final_audit_sha256: 'c'.repeat(64),
    partial, verbatim_chunks: partial ? [{ chunk: 1, heading: 'Summary', lines: 1, kept_lines: 1, reason: 'integrity' }] : [] }
  return { report_id: id, status: 'completed', markdown_content: source === 'zh' ? '# 中文原文\n\n已经审核。' : '# Original report\n\nAccepted source.\n\n## Details\n\nEvidence.',
    translations: available ? [translation] : [],
    translation_status: { report_id: id, source_lang: source, target_lang: target, requested_lang: target,
      status: state || (available ? 'available' : 'missing'), available, can_generate: true,
      can_update: available, source_markdown_sha256: sha, markdown_sha256: translation.markdown_sha256,
      translation, partial, ...(translationJob ? { translation_job: translationJob } : {}) } }
}
const response = data => ({ success: true, data })
const display = (lang, status = 'available') => response({
  forecast: { headline: lang === 'zh' ? '委员会展望' : 'Committee outlook', scenarios: [], binary_forecasts: [] },
  localization: { complete: status === 'available', localized: lang === 'zh' },
  display: { title: lang === 'zh' ? '中文报告标题' : 'Original report title', viz_manifest: [], failed_sections: [] },
  structured_translation: { status, partial: status === 'partial', complete: status === 'available' },
})

// Real mounted Vue component with a tiny host renderer. All watch/lifecycle hooks
// run normally; only transport and browser host facilities are controlled.
function mount(t, options = {}) {
  i18n.locale.value = 'en'
  const timers = new Map(); let timerId = 0
  t.mock.method(globalThis, 'setTimeout', (fn, ms) => { const id = ++timerId; timers.set(id, { fn, ms }); return id })
  t.mock.method(globalThis, 'clearTimeout', id => timers.delete(id))
  const calls = [], downloads = [], copied = [], saved = [], emitted = [], scrolled = []
  t.mock.method(URL, 'createObjectURL', blob => { downloads.push({ blob }); return 'blob:forecast' })
  t.mock.method(URL, 'revokeObjectURL', () => {})
  const installGlobal = (name, value) => {
    const before = Object.getOwnPropertyDescriptor(globalThis, name)
    Object.defineProperty(globalThis, name, { value, configurable: true })
    t.after(() => { if (before) Object.defineProperty(globalThis, name, before); else delete globalThis[name] })
  }
  installGlobal('document', {
    body: { appendChild() {} }, getElementById: id => ({ scrollIntoView: () => scrolled.push(id) }),
    createElement: () => ({ style: {}, click() { Object.assign(downloads.at(-1), { filename: this.download }) }, remove() {} }),
  })
  installGlobal('navigator', { clipboard: { writeText: async text => copied.push(text) } })
  t.mock.method(globalThis, 'fetch', async (...args) => {
    calls.push(['fetch', ...args]); return options.fetch ? options.fetch(...args) : new Response('%PDF-1.7\naccepted', { headers: { 'content-type': 'application/pdf', 'content-disposition': 'attachment; filename="accepted.pdf"' } })
  })
  let current = options.report || report()
  const api = {
    getReport: async id => { calls.push(['report', id]); return options.getReport ? options.getReport(id) : response({ ...current, report_id: id }) },
    getVizManifest: async () => response([]),
    getSectionsPartial: async (...args) => { calls.push(['sections', ...args]); return options.getSectionsPartial?.(...args) || response({ sections: [], done: false }) },
    getForecast: async (...args) => { calls.push(['forecast', ...args]); return options.getForecast ? options.getForecast(...args) : display(args[1]) },
    getReportOfficialData: async (...args) => { calls.push(['official', ...args]); return options.getOfficial ? options.getOfficial(...args) : response({ available: false }) },
    getReportTranslationMd: async (...args) => { calls.push(['markdown', ...args]); return options.getMd ? options.getMd(...args) : translatedMarkdown(args[1]) },
    getReportTranslationStatus: async (...args) => { calls.push(['status', ...args]); return options.getStatus ? options.getStatus(...args) : response(current.translation_status) },
    requestReportTranslation: async (...args) => { calls.push(['post', ...args]); return options.post ? options.post(...args) : response({ status: 'failed', issues: ['Provider unavailable'], can_generate: true }) },
    reportAssetUrl: (id, path) => `/api/report/${id}/${path}`,
    reportMarkdownUrl: (id, lang) => `/api/report/${id}/${lang ? `full_report.${lang}.md` : 'download'}`,
    reportPdfUrl: (id, lang) => `/api/report/${id}/pdf${lang ? `?lang=${lang}` : ''}`,
  }
  const panel = buildPanel({ vue, '../../i18n': i18n, '../../utils/sourceContext': sourceContext })
  const component = buildReport({ vue: { ...vue, defineAsyncComponent: () => panel },
    '../../api/report': api, '../../composables/useTranslationJob': observer, '../../utils/forecastTranslationAdapter': adapter,
    './BinaryForecastTable.vue': { default: buildTable({ vue, '../../utils/binaryForecasts': binaryForecasts, '../../i18n': i18n }) },
    '../../utils/markdown': markdown, '../../utils/vizManifest': vizManifest, '../../utils/reportLanguages': reportLanguages,
    '../../utils/officialData': officialData, '../../utils/saveTextFile': { saveTextFile: (...args) => saved.push(args) }, '../../i18n': i18n,
  })
  let state
  const setup = component.setup
  component.setup = (props, ctx) => { state = setup(props, ctx); return state }
  const node = (type, text = '') => ({ type, text, children: [], props: {}, parent: null })
  const renderer = vue.createRenderer({
    createElement: type => node(type), createText: text => node('#text', text), createComment: text => node('#comment', text),
    setText: (n, text) => { n.text = text }, setElementText: (n, text) => { n.text = text; n.children = [] },
    parentNode: n => n.parent, nextSibling: n => n.parent?.children[n.parent.children.indexOf(n) + 1] || null,
    patchProp: (n, key, _old, value) => { n.props[key] = value },
    insert(n, parent, anchor = null) {
      if (n.parent) n.parent.children.splice(n.parent.children.indexOf(n), 1)
      n.parent = parent
      const index = parent.children.indexOf(anchor)
      parent.children.splice(index < 0 ? parent.children.length : index, 0, n)
    },
    remove(n) { if (n.parent) n.parent.children.splice(n.parent.children.indexOf(n), 1); n.parent = null },
  })
  const root = node('root')
  const props = vue.reactive({ reportId: current.report_id })
  const app = renderer.createApp({ render: () => vue.h(component, { ...props, onOpenSimulationRecord: value => emitted.push(value) }) })
  app.mount(root)
  let unmounted = false
  const unmount = () => { if (!unmounted) { app.unmount(); unmounted = true } }
  t.after(() => { unmount(); i18n.locale.value = 'en' })
  const walk = n => [n, ...n.children.flatMap(walk)]
  const content = n => n.type === '#comment' ? '' : `${n.text || ''}${n.props.innerHTML || ''}${n.children.map(content).join(' ')}`
  const find = (cls, label) => walk(root).find(n => String(n.props.class || '').split(' ').includes(cls) && (!label || content(n).includes(label)))
  return { state, props, calls, downloads, copied, saved, emitted, scrolled, timers, unmount,
    setReport: value => { current = value }, text: () => content(root), find,
    async click(cls, label) { const n = find(cls, label); assert.ok(n, `missing ${cls} ${label || ''}: ${content(root)}`); assert.ok(!n.props.disabled, `disabled ${cls}`); const result = n.props.onClick(); await settle(); return result },
    async tick() { assert.ok(timers.size, 'expected observer timer'); const [id, entry] = timers.entries().next().value; timers.delete(id); entry.fn(); await settle() },
  }
}
const posts = h => h.calls.filter(call => call[0] === 'post')

// Admission includes asynchronous SHA-256 verification. A fixed number of event
// loop turns cannot establish that it finished when other test workers are busy.
async function waitForAdmittedLanguage(t, h, language) {
  const ready = () => h.state.activeLang.value === language
    && h.state.translationObserver.snapshot.value?.available === true
    && h.state.translationObserver.loading.value === false
  if (!ready()) await new Promise((resolve, reject) => {
    let stop
    const timer = realSetTimeout(() => {
      stop?.()
      reject(new Error(`Language ${language} was not admitted: ${h.state.translationObserver.status.value}`))
    }, 5000)
    stop = vue.watch(ready, value => {
      if (!value) return
      stop(); realClearTimeout(timer); resolve()
    }, { flush: 'post' })
    t.after(() => { stop(); realClearTimeout(timer) })
  })
  await vue.nextTick() // commit the enabled button associated with that state
}


test('mounted source report reconnects to attached in-flight job, shows coverage, never POSTs', async t => {
  const h = mount(t, { report: report({ translationJob: job('running') }) }); await settle()
  assert.equal(h.state.translationObserver.status.value, 'running')
  assert.match(h.text(), /Reviewed 1\/3; 2 pending/)
  assert.equal(h.timers.size, 1)
  assert.equal(h.calls.filter(c => c[0] === 'sections').length, 0)
  h.setReport(report({ translationJob: job('completed') })); await h.tick()
  assert.equal(h.timers.size, 0); assert.deepEqual(posts(h), [])
})

test('transient resource GET reconnects automatically while retaining published source', async t => {
  let reads = 0
  const h = mount(t, { getReport: async () => { if (++reads === 2) throw new Error('Temporary disconnect'); return response(report()) } }); await settle()
  assert.equal(h.state.translationObserver.status.value, 'reconnecting')
  assert.match(h.text(), /Temporary disconnect/)
  assert.ok(h.state.currentMd.value.includes('Accepted source'))
  await h.tick()
  assert.equal(h.state.translationObserver.error.value, '')
  assert.equal(h.timers.size, 0); assert.deepEqual(posts(h), [])
})

test('legacy in-flight GET is normalized outside observer and completion refreshes publication', async t => {
  let completed = false
  const h = mount(t, { report: report({ available: false, state: 'generating' }),
    getReport: async () => response(report({ available: completed, state: completed ? 'available' : 'generating' })),
    getStatus: async () => { completed = true; return response({ status: 'completed', available: true }) },
  }); await settle()
  assert.ok(h.find('lang-btn', '中文')); assert.equal(h.timers.size, 0); assert.deepEqual(posts(h), [])
})

test('start control performs one non-forced POST and only admits publication metadata', async t => {
  const pending = deferred()
  const h = mount(t, { report: report({ available: false }), post: () => pending.promise }); await settle()
  const button = h.find('translate-btn', 'Generate')
  assert.ok(button)
  button.props.onClick(); button.props.onClick(); await settle()
  assert.equal(posts(h).length, 1); assert.equal(posts(h)[0][3], false)
  pending.resolve(response({ status: 'completed', available: true })); await settle()
  assert.equal(h.state.activeLang.value, null)
  assert.equal(h.find('lang-btn', '中文'), undefined)
})

for (const cause of ['body', 'structured']) {
  test(`${cause} partial retry is non-forced and preserves accepted Markdown`, async t => {
    const h = mount(t, { report: report({ partial: cause === 'body' }),
      getForecast: async (_id, lang) => display(lang, cause === 'structured' && lang === 'zh' ? 'partial' : 'available') }); await settle()
    await h.click('lang-btn', '中文'); await settle()
    const body = h.state.currentMd.value
    await h.click('translate-btn', '重试翻译')
    assert.deepEqual(posts(h), [['post', 'report_A', 'zh', false]])
    assert.equal(h.state.currentMd.value, body)
    assert.match(h.text(), /Provider unavailable/)
  })
}

test('refresh is explicit force true and retains the accepted variant while replacement runs', async t => {
  const h = mount(t, { post: async () => response({ translation_job: job('running'), available: false }) }); await settle()
  await h.click('lang-btn', '中文'); await settle()
  const body = h.state.currentMd.value
  await h.click('translate-btn', '更新翻译')
  assert.deepEqual(posts(h), [['post', 'report_A', 'zh', true]])
  assert.equal(h.state.currentMd.value, body); assert.equal(h.state.translationBusy.value, true)
  assert.ok(h.find('lang-btn', 'EN')); await h.click('lang-btn', 'EN')
  assert.equal(h.state.activeLang.value, null)
})

test('structured generating uses the shared observer until complete without POST or body rewrite', async t => {
  let count = 0
  const h = mount(t, { getForecast: async (_id, lang) => display(lang, lang === 'zh' && ++count === 1 ? 'generating' : 'available') }); await settle()
  await h.click('lang-btn', '中文'); await settle()
  assert.equal(h.state.structuredGenerating.value, true)
  assert.match(h.text(), /正文译文可用/)
  await h.tick()
  assert.equal(h.state.structuredGenerating.value, false)
  assert.equal(h.state.structuredTranslationNotice.value, '')
  assert.equal(h.calls.filter(c => c[0] === 'markdown').length, 1)
  assert.deepEqual(posts(h), [])
})

for (const change of ['language', 'report', 'unmount']) {
  test(`late structured and Markdown reads cannot commit after ${change} changes`, async t => {
    const pending = deferred()
    const h = mount(t, { getForecast: async (_id, lang) => lang === 'zh' ? pending.promise : display(lang) }); await settle()
    await h.click('lang-btn', '中文'); await settle()
    if (change === 'language') await h.click('lang-btn', 'EN')
    if (change === 'report') { h.setReport(report({ id: 'report_B' })); h.props.reportId = 'report_B'; await settle() }
    if (change === 'unmount') h.unmount()
    const before = JSON.stringify(h.state.displayByLang.value)
    pending.resolve(display('zh', 'generating')); await settle()
    assert.equal(JSON.stringify(h.state.displayByLang.value), before)
    assert.equal(h.state.activeLang.value, null); assert.equal(h.timers.size, 0); assert.deepEqual(posts(h), [])
  })
}

test('check status reconnects by GET and completion exposes a newly published variant', async t => {
  const h = mount(t, { report: report({ available: false, state: 'failed' }) }); await settle()
  h.setReport(report())
  await h.click('check-translation-btn')
  assert.ok(h.find('lang-btn', '中文')); assert.deepEqual(posts(h), [])
})

test('revoked publication removes selected target bytes and export uses the displayed source', async t => {
  const h = mount(t); await settle(); await h.click('lang-btn', '中文'); await settle()
  h.setReport(report({ available: false, state: 'stale' }))
  await h.click('check-translation-btn')
  assert.equal(h.state.activeLang.value, null)
  assert.match(h.text(), /publication admission/)
  assert.equal(h.state.pdfHref.value, '/api/report/report_A/pdf')
})

for (const source of ['en', 'zh']) {
  test(`${source} primary and opposite-language PDFs use displayed language and correct routes`, async t => {
    const h = mount(t, { report: report({ source }) }); await settle()
    assert.match(h.find('pdf-btn').text, source === 'en' ? /English PDF/ : /Mandarin PDF/)
    await h.click('pdf-btn')
    assert.equal(h.calls.find(c => c[0] === 'fetch')[1], `/api/report/report_A/pdf?source_sha256=${digest(h.state.md.value)}`)
    assert.equal(h.downloads[0].filename, 'accepted.pdf')
    await h.click('lang-btn', source === 'en' ? '中文' : 'EN'); await settle()
    const target = source === 'en' ? 'zh' : 'en'
    assert.match(h.find('pdf-btn').text, target === 'zh' ? /中文 PDF/ : /English PDF/)
    await h.click('pdf-btn')
    assert.equal(h.calls.filter(c => c[0] === 'fetch').at(-1)[1], `/api/report/report_A/pdf?lang=${target}&source_sha256=${digest(h.state.md.value)}`)
    assert.equal(h.state.exportBusy.value, '')
  })
}

for (const failure of ['magic', 'content-type', 'http', 'typed-http', 'transport']) {
  test(`PDF ${failure} failure is inline, resets busy and never downloads`, async t => {
    const h = mount(t, { fetch: async () => {
      if (failure === 'transport') throw new Error('Connection failed')
      if (failure === 'http') return new Response(JSON.stringify({ error: 'Artifact changed; retry' }), { status: 409 })
      if (failure === 'typed-http') return new Response(JSON.stringify({ error: { code: 'stale_artifact', message: 'Publication changed; reload' } }), { status: 409, headers: { 'content-type': 'application/json' } })
      if (failure === 'content-type') return new Response('%PDF-1.7\nwrong media type', { headers: { 'content-type': 'text/html' } })
      return new Response('<html>Not a PDF</html>', { headers: { 'content-type': 'application/pdf' } })
    } }); await settle(); await h.click('pdf-btn')
    assert.equal(h.downloads.length, 0); assert.equal(h.state.exportBusy.value, '')
    assert.match(h.text(), /invalid PDF|Artifact changed|Publication changed|Connection failed/)
  })
}

for (const change of ['language', 'report', 'publication', 'unmount']) {
  test(`late PDF bytes discarded on ${change} change; repeated clicks cannot duplicate download`, async t => {
    const pending = deferred()
    const h = mount(t, { fetch: () => pending.promise }); await settle()
    const button = h.find('pdf-btn'); button.props.onClick(); button.props.onClick(); await settle()
    assert.equal(h.calls.filter(c => c[0] === 'fetch').length, 1)
    assert.ok(h.find('pdf-btn').props.disabled)
    if (change === 'language') await h.click('lang-btn', '中文')
    if (change === 'report') { h.setReport(report({ id: 'report_B' })); h.props.reportId = 'report_B'; await settle() }
    if (change === 'publication') { const next = report(); next.markdown_content += '\nChanged source'; h.setReport(next); await h.click('check-translation-btn') }
    if (change === 'unmount') h.unmount()
    pending.resolve(new Response('%PDF-1.7\nlate', { headers: { 'content-type': 'application/pdf' } })); await settle()
    assert.equal(h.downloads.length, 0); assert.equal(h.state.exportBusy.value, '')
  })
}

test('mounted Markdown download, copy, navigation and simulation-record controls', async t => {
  const current = report(); current.simulation_record_ref = { url: '/api/simulation/sim_A/record', sha256: sha }
  const h = mount(t, { report: current, fetch: async () => new Response('# Markdown export') }); await settle()
  await h.click('markdown-btn')
  assert.equal(h.calls.find(c => c[0] === 'fetch')[1], '/api/report/report_A/download')
  assert.equal(h.downloads[0].filename, 'report_A.md')
  await h.click('copy-btn'); assert.equal(h.copied[0], h.state.displayMd.value)
  await h.click('nav-item'); assert.equal(h.scrolled.length, 1)
  await h.click('sra-btn'); assert.equal(h.emitted.length, 1)
  await h.click('lang-btn', '中文'); await settle(); await h.click('markdown-btn')
  assert.equal(h.calls.filter(c => c[0] === 'fetch').at(-1)[1], '/api/report/report_A/full_report.zh.md')
})

test('official CSV control remains wired to stored observations', async t => {
  const fixture = JSON.parse(readFileSync(new URL('./fixtures/official/official_data.en_report.en.json', import.meta.url)))
  fixture.data.report_id = 'report_A'
  const h = mount(t, { getOfficial: async () => fixture }); await settle()
  await h.click('ot-csv'); assert.equal(h.saved.length, 1); assert.match(h.saved[0][1], /\.csv$/)
})

test('report generation polling remains independent and hands completed body to the observer', async t => {
  const generating = report(); generating.markdown_content = ''; generating.status = 'generating'
  let reads = 0
  const h = mount(t, { report: generating, getReport: async () => response(++reads < 3 ? generating : report({ translationJob: job('running') })) }); await settle()
  assert.ok(h.calls.some(c => c[0] === 'sections')); assert.ok(h.state.isGenerating.value)
  await h.tick(); await settle()
  assert.equal(h.state.isGenerating.value, false)
  const sectionReads = h.calls.filter(c => c[0] === 'sections').length
  await h.tick()
  assert.equal(h.calls.filter(c => c[0] === 'sections').length, sectionReads)
  assert.deepEqual(posts(h), [])
})

test('the component contains no translation or structured polling controllers', () => {
  const source = readFileSync(new URL('../src/components/research/ForecastReport.vue', import.meta.url), 'utf8')
  assert.doesNotMatch(source, /translationPoll|structuredPoll|pollTranslation|stopTranslationPolling|scheduleStructuredPoll/)
  assert.match(source, /useTranslationJob\(/)
})

test('status endpoint reconnects a structured job even when metadata declares the body available', async t => {
  let complete = false
  const h = mount(t, { getStatus: async () => response({ status: 'available', available: true,
    translation_job: job(complete ? 'completed' : 'running') }) }); await settle()
  assert.equal(h.state.translationObserver.status.value, 'running')
  assert.ok(h.calls.some(c => c[0] === 'status'))
  assert.match(h.text(), /Reviewed 1\/3; 2 pending/)
  complete = true; await h.tick()
  assert.equal(h.state.translationObserver.status.value, 'completed')
  assert.equal(h.timers.size, 0); assert.deepEqual(posts(h), [])
})

test('PDF and Markdown export bind the admitted generation, leaving primary URL unsuffixed', async t => {
  const current = report(); current.translations[0].generation_id = 'generation accepted/1'
  const h = mount(t, { report: current }); await settle()
  assert.equal(h.state.pdfHref.value, '/api/report/report_A/pdf')
  await h.click('lang-btn', '中文'); await settle()
  await h.click('pdf-btn')
  assert.equal(h.calls.filter(c => c[0] === 'fetch').at(-1)[1], `/api/report/report_A/pdf?lang=zh&generation_id=generation%20accepted%2F1&source_sha256=${digest(h.state.md.value)}`)
  assert.equal(h.state.markdownHref.value, '/api/report/report_A/full_report.zh.md?generation_id=generation%20accepted%2F1')
})

for (const mismatch of ['resource', 'language', 'source']) {
  test(`attached job with mismatched ${mismatch} identity is rejected without reconnect or paid work`, async t => {
    let invalid = false
    const h = mount(t, { getStatus: async () => response({ status: 'available', available: true,
      ...(invalid ? { translation_job: job('running', { identity: {
        ref_id: mismatch === 'resource' ? 'report_other' : 'report_A',
        target_lang: mismatch === 'language' ? 'en' : 'zh',
        source_markdown_sha256: mismatch === 'source' ? 'd'.repeat(64) : sha,
      } }) } : {}) }) }); await settle()
    await h.click('lang-btn', '中文')
    await waitForAdmittedLanguage(t, h, 'zh')
    invalid = true; await h.click('check-translation-btn')
    assert.equal(h.state.translationObserver.status.value, 'error')
    assert.equal(h.state.activeLang.value, null)
    assert.deepEqual(h.state.langMdCache.value, {})
    assert.equal(h.timers.size, 0); assert.deepEqual(posts(h), [])
  })
}

for (const change of ['language', 'report', 'unmount']) {
  test(`pending mutation admission cannot POST after ${change} changes`, async t => {
    let waiting = false
    const pending = deferred()
    const h = mount(t, { report: report({ partial: true }), getReport: async id => waiting ? pending.promise : response(report({ id, partial: true })) }); await settle()
    await h.click('lang-btn', '中文'); await settle()
    waiting = true
    h.find('translate-btn', '重试翻译').props.onClick(); await settle()
    if (change === 'language') { waiting = false; await h.click('lang-btn', 'EN') }
    if (change === 'report') { waiting = false; h.props.reportId = 'report_B'; await settle() }
    if (change === 'unmount') h.unmount()
    pending.resolve(response(report({ partial: true }))); await settle()
    assert.deepEqual(posts(h), [])
  })
}

test('initial report-load failure renders a working read-only retry control', async t => {
  let reads = 0
  const h = mount(t, { getReport: async () => { if (++reads === 1) throw new Error('Report unavailable'); return response(report()) } }); await settle()
  assert.match(h.text(), /Report unavailable/)
  await h.click('retry-btn')
  assert.equal(h.state.error.value, '')
  assert.match(h.text(), /Accepted source/)
  assert.deepEqual(posts(h), [])
})

test('structured read transport failure preserves the already displayed admitted body and reconnects by GET', async t => {
  let calls = 0
  const h = mount(t, { getForecast: async (_id, lang) => {
    if (lang !== 'zh') return display(lang)
    calls++
    if (calls === 2) throw new Error('Display connection lost')
    return display(lang, calls === 1 ? 'generating' : 'available')
  } }); await settle(); await h.click('lang-btn', '中文'); await settle()
  const body = h.state.currentMd.value
  await h.tick()
  assert.equal(h.state.translationObserver.status.value, 'reconnecting')
  assert.equal(h.state.currentMd.value, body)
  await h.tick()
  assert.equal(h.state.translationObserver.error.value, '')
  assert.equal(h.state.currentMd.value, body)
  assert.equal(h.timers.size, 0); assert.deepEqual(posts(h), [])
})

test('bounded observer timeout retains admitted body and Check status resumes by GET', async t => {
  let complete = false
  const h = mount(t, { getForecast: async (_id, lang) => display(lang, lang === 'zh' && !complete ? 'generating' : 'available') }); await settle()
  await h.click('lang-btn', '中文'); await settle()
  const body = h.state.currentMd.value
  for (let i = 0; i < 119; i++) await h.tick()
  assert.equal(h.state.translationObserver.status.value, 'timeout')
  assert.equal(h.timers.size, 0)
  assert.equal(h.state.currentMd.value, body)
  complete = true; await h.click('check-translation-btn')
  assert.equal(h.state.translationObserver.snapshot.value.active, false)
  assert.equal(h.state.translationObserver.error.value, '')
  assert.deepEqual(posts(h), [])
})

test('publication revocation cancels an in-flight target PDF and releases export busy', async t => {
  const pending = deferred()
  const h = mount(t, { fetch: () => pending.promise }); await settle()
  await h.click('lang-btn', '中文'); await settle()
  h.find('pdf-btn').props.onClick(); await settle()
  assert.equal(h.state.exportBusy.value, 'pdf')
  h.setReport(report({ available: false, state: 'stale' }))
  await h.click('check-translation-btn')
  assert.equal(h.state.exportBusy.value, '')
  const request = h.calls.find(c => c[0] === 'fetch')
  assert.equal(request[2].signal.aborted, true)
  pending.resolve(new Response('%PDF-1.7\nrevoked', { headers: { 'content-type': 'application/pdf' } })); await settle()
  assert.equal(h.downloads.length, 0)
})

function publication(markdown, generationId) {
  const current = report()
  current.translations[0].markdown_sha256 = digest(markdown)
  current.translations[0].generation_id = generationId
  current.translation_status.markdown_sha256 = digest(markdown)
  current.translation_status.generation_id = generationId
  return current
}

test('metadata/Markdown generation race rejects mismatched bytes, then reconnects with fresh admission using GET only', async t => {
  const before = '# 旧版已审核\n\n预测概率为 70%。\n'
  const after = '# 新版已审核\n\n预测概率为 75%。\n'
  const pending = deferred()
  let reads = 0
  const h = mount(t, { report: publication(before, 'generation-1'),
    getMd: async () => ++reads === 1 ? pending.promise : after }); await settle()
  await h.click('lang-btn', '中文'); await settle()
  const firstRead = h.calls.find(call => call[0] === 'markdown')
  assert.equal(firstRead[3].generationId, 'generation-1')
  assert.ok(firstRead[3].signal instanceof AbortSignal)
  h.setReport(publication(after, 'generation-2'))
  pending.resolve(after); await settle()
  assert.equal(h.state.translationObserver.status.value, 'reconnecting')
  assert.match(h.state.translationIssueMessage.value, /publication changed/)
  assert.equal(h.state.activeLang.value, null)
  assert.deepEqual(h.state.langMdCache.value, {}, 'unverified bytes must never enter the component cache')
  assert.ok(!h.text().includes('新版已审核'))
  assert.equal(h.timers.size, 1)
  await h.tick()
  assert.equal(h.state.currentMd.value, after)
  assert.equal(h.calls.filter(call => call[0] === 'markdown').at(-1)[3].generationId, 'generation-2')
  assert.equal(h.state.pdfHref.value, '/api/report/report_A/pdf?lang=zh&generation_id=generation-2')
  assert.equal(h.state.translationObserver.error.value, '')
  assert.deepEqual(posts(h), [])
})

test('a later generation race preserves the last verified body and export generation until recovery', async t => {
  const before = translatedMarkdown('zh')
  const middle = '# 第二版\n\n需要绑定这一版。'
  const after = '# 第三版\n\n最新审核内容。'
  const pending = deferred()
  let reads = 0
  const h = mount(t, { report: publication(before, 'generation-1'), getMd: async () => {
    reads++
    return reads === 1 ? before : reads === 2 ? pending.promise : after
  } }); await settle(); await h.click('lang-btn', '中文'); await settle()
  h.setReport(publication(middle, 'generation-2'))
  h.find('check-translation-btn').props.onClick(); await settle()
  h.setReport(publication(after, 'generation-3'))
  pending.resolve(after); await settle()
  assert.equal(h.state.translationObserver.status.value, 'reconnecting')
  assert.equal(h.state.currentMd.value, before)
  assert.equal(h.state.langMdCache.value.zh, before)
  assert.equal(h.state.pdfHref.value, '/api/report/report_A/pdf?lang=zh&generation_id=generation-1')
  await h.tick()
  assert.equal(h.state.currentMd.value, after)
  assert.equal(h.state.pdfHref.value, '/api/report/report_A/pdf?lang=zh&generation_id=generation-3')
  assert.deepEqual(posts(h), [])
})

test('generation-conflict HTTP 409 refreshes metadata without admitting or retrying provider work', async t => {
  const before = translatedMarkdown('zh')
  const after = '# 新的审核版本\n\n完整正文。'
  let reads = 0
  const h = mount(t, { report: publication(before, 'generation-1'), getMd: async () => {
    if (++reads === 1) throw Object.assign(new Error('Displayed translation changed'), { response: { status: 409 } })
    return after
  } }); await settle(); await h.click('lang-btn', '中文'); await settle()
  assert.equal(h.state.translationObserver.status.value, 'reconnecting')
  assert.deepEqual(h.state.langMdCache.value, {})
  h.setReport(publication(after, 'generation-2')); await h.tick()
  assert.equal(h.state.currentMd.value, after)
  assert.deepEqual(posts(h), [])
})

test('unchanged UTF8 bytes in a new generation require a generation-bound read before cache reuse', async t => {
  const body = translatedMarkdown('zh')
  const h = mount(t, { report: publication(body, 'generation-1') }); await settle()
  await h.click('lang-btn', '中文'); await settle()
  h.setReport(publication(body, 'generation-2')); await h.click('check-translation-btn')
  const reads = h.calls.filter(call => call[0] === 'markdown')
  assert.deepEqual(reads.map(call => call[3].generationId), ['generation-1', 'generation-2'])
  assert.equal(h.state.currentMd.value, body)
  await h.click('check-translation-btn')
  assert.equal(h.calls.filter(call => call[0] === 'markdown').length, 2, 'same verified generation is cached')
  assert.deepEqual(posts(h), [])
})

for (const inventory of ['structured', 'body']) {
  test(`${inventory} aggregate coverage takes precedence over completed job-page coverage`, async t => {
    const current = report({ translationJob: job('completed', { coverage: { required: 2, accepted: 2, pending_translation: 0, pending_review: 0, failed: 0 } }) })
    if (inventory === 'body') current.translation_status.coverage = { total: 9, translated: 4, pending: 0 }
    const h = mount(t, { report: current, getForecast: async (_id, lang) => {
      const result = display(lang, lang === 'zh' ? 'partial' : 'available')
      if (inventory === 'structured' && lang === 'zh') result.data.structured_translation.coverage = { total: 9, translated: 4, pending: 0 }
      return result
    } }); await settle(); await h.click('lang-btn', '中文'); await settle()
    assert.deepEqual(h.state.translationObserver.coverage.value, { total: 9, accepted: 4, pending: 5 })
    assert.match(h.text(), /已审核 4\/9，待完成 5/)
    assert.deepEqual(posts(h), [])
  })
}

test('report Markdown API passes generation_id and abort signal through its real request wrapper', async () => {
  const source = readFileSync(new URL('../src/api/report.js', import.meta.url), 'utf8')
  const calls = []
  const api = new Function('service', 'apiUrl', source
    .replace("import service, { apiUrl } from './index'", '')
    .replace('export { apiUrl }', '')
    .replaceAll('export const ', 'const ') + '\nreturn { getReportTranslationMd };')({ get: async (...args) => { calls.push(args); return 'Markdown' } }, path => path)
  const controller = new AbortController()
  assert.equal(await api.getReportTranslationMd('report_A', 'zh', { signal: controller.signal, generationId: 'generation-2' }), 'Markdown')
  assert.deepEqual(calls[0], ['/api/report/report_A/full_report.zh.md', {
    responseType: 'text', signal: controller.signal, params: { generation_id: 'generation-2' },
  }])
  await api.getReportTranslationMd('report_A', 'zh')
  assert.equal(calls[1][1].params, undefined, 'legacy publications still use digest admission without a generation id')
})

test('primary PDF sends the displayed source digest and refuses HTTP 409 after server source drift', async t => {
  const displayed = report()
  const serverSource = displayed.markdown_content + '\n\nUpdated server-only source.'
  const h = mount(t, { report: displayed, fetch: async href => {
    const request = new URL(href, 'http://localhost')
    assert.equal(request.pathname, '/api/report/report_A/pdf')
    assert.equal(request.searchParams.has('lang'), false, 'primary remains the unsuffixed resource')
    assert.equal(request.searchParams.get('source_sha256'), digest(displayed.markdown_content))
    if (request.searchParams.get('source_sha256') !== digest(serverSource)) {
      return new Response(JSON.stringify({ error: { code: 'stale_artifact', message: 'Displayed report source changed; reload before exporting' } }),
        { status: 409, headers: { 'content-type': 'application/json' } })
    }
    return new Response('%PDF-1.7\nnew source', { headers: { 'content-type': 'application/pdf' } })
  } }); await settle()
  await h.click('pdf-btn')
  assert.equal(h.calls.filter(call => call[0] === 'fetch').length, 1)
  assert.equal(h.downloads.length, 0)
  assert.equal(h.state.exportBusy.value, '')
  assert.match(h.text(), /Displayed report source changed; reload before exporting/)
  assert.equal(h.state.currentMd.value, displayed.markdown_content)
  assert.deepEqual(posts(h), [])
})

test('source changes during awaited PDF hashing cancel export before any fetch', async t => {
  const h = mount(t); await settle()
  const pending = deferred()
  const nativeDigest = globalThis.crypto.subtle.digest.bind(globalThis.crypto.subtle)
  t.mock.method(globalThis.crypto.subtle, 'digest', async (...args) => {
    await pending.promise
    return nativeDigest(...args)
  })
  const exporting = h.find('pdf-btn').props.onClick(); await settle()
  assert.equal(h.state.exportBusy.value, 'pdf')
  assert.equal(h.calls.filter(call => call[0] === 'fetch').length, 0)
  const replacement = report(); replacement.markdown_content += '\n\nReplacement source.'
  h.setReport(replacement); await h.click('check-translation-btn')
  assert.equal(h.state.md.value, replacement.markdown_content)
  pending.resolve(); await exporting; await settle()
  assert.equal(h.calls.filter(call => call[0] === 'fetch').length, 0, 'stale hash completion must never start a download request')
  assert.equal(h.state.exportBusy.value, '')
  assert.equal(h.downloads.length, 0)
})

// Real routes differ: GET /report returns body-only status, while the translation
// status route adds display/forecast completeness even before a body exists.
function routeShapedMissingBodyStatus(meta) {
  const structured = { status: 'partial', complete: false, partial: true, display_complete: false,
    target_lang: 'zh', pending: 1, retryable: true, translation_job: null,
    coverage: { complete: false, total: 1, translated: 0,
      display: { complete: false, total: 1, translated: 0 },
      forecast: { complete: true, total: 0, translated: 0 } },
    forecast: { complete: true, localized: false, pending: 0, present: false,
      requested_lang: 'zh', source_forecast_sha256: null },
    issues: ['Some source text remains untranslated; resume pending entries.'] }
  return { ...meta.translation_status, partial: true, structured_translation: structured,
    translation_status: structured, display: { title: 'Original report', failed_sections: [],
      news_market_context: null, structured_translation: structured, translation_status: structured },
    translation_job: null }
}

test('actual missing-body metadata plus partial structured status admits the Retry button it renders', async t => {
  const meta = report({ available: false })
  let statusReads = 0
  const h = mount(t, { report: meta,
    getStatus: async () => { statusReads++; return response(routeShapedMissingBodyStatus(meta)) },
    post: async () => response({ ...routeShapedMissingBodyStatus(meta), translation_job: job('queued') }),
  }); await settle()
  assert.equal(meta.translation_status.status, 'missing')
  assert.equal(meta.translation_status.structured_translation, undefined)
  assert.equal(h.state.translationObserver.snapshot.value.partial, true)
  assert.equal(h.state.translationObserver.actions.value.start, true)
  assert.equal(h.state.translationObserver.actions.value.retry, true)
  await h.click('translate-btn', 'Retry translation')
  assert.deepEqual(posts(h), [['post', 'report_A', 'zh', false]], 'actual offered retry must reach the resource POST without force')
  assert.equal(statusReads, 2, 'preflight re-reads the same full status used by observation')
  assert.equal(h.state.translationObserver.error.value, '')
  assert.equal(h.state.translationObserver.snapshot.value.state, 'queued')
})

for (const revokedIn of ['metadata', 'status']) {
  test(`full-status preflight rejects a freshly revoked ${revokedIn} permission`, async t => {
    const meta = report({ available: false })
    let revoke = false, preflightStatusReads = 0
    const h = mount(t, { report: meta,
      getReport: async () => response({ ...meta, translation_status: {
        ...meta.translation_status, can_generate: !(revoke && revokedIn === 'metadata'),
      } }),
      getStatus: async () => {
        if (revoke) preflightStatusReads++
        return response({ ...routeShapedMissingBodyStatus(meta), can_generate: !(revoke && revokedIn === 'status') })
      },
    }); await settle()
    assert.ok(h.find('translate-btn', 'Retry translation'))
    revoke = true
    await h.click('translate-btn', 'Retry translation')
    assert.equal(preflightStatusReads, 1)
    assert.deepEqual(posts(h), [])
    assert.match(h.state.translationObserver.error.value, /does not permit/)
    assert.equal(h.timers.size, 0)
  })
}

for (const change of ['language', 'report', 'unmount']) {
  test(`full-status preflight finishing after ${change} changes cannot authorize POST`, async t => {
    const meta = report({ partial: true })
    const pending = deferred()
    let hold = false
    const h = mount(t, { report: meta, getStatus: async () => hold ? pending.promise : response(meta.translation_status) }); await settle()
    await h.click('lang-btn', '中文'); await settle()
    hold = true
    const retry = h.find('translate-btn', '重试翻译').props.onClick(); await settle()
    assert.equal(h.state.translationBusy.value, true)
    hold = false
    if (change === 'language') await h.click('lang-btn', 'EN')
    if (change === 'report') { h.setReport(report({ id: 'report_B' })); h.props.reportId = 'report_B'; await settle() }
    if (change === 'unmount') h.unmount()
    pending.resolve(response(meta.translation_status)); await retry; await settle()
    assert.deepEqual(posts(h), [])
  })
}

test('failed full-status preflight reconnects read-only and never automatically submits the pending retry', async t => {
  const meta = report({ available: false })
  let reads = 0
  const h = mount(t, { report: meta, getStatus: async () => {
    if (++reads === 2) throw new Error('Preflight status temporarily unavailable')
    return response(routeShapedMissingBodyStatus(meta))
  } }); await settle()
  await h.click('translate-btn', 'Retry translation')
  assert.equal(h.state.translationObserver.status.value, 'reconnecting')
  assert.deepEqual(posts(h), [])
  await h.tick()
  assert.equal(h.state.translationObserver.error.value, '')
  assert.deepEqual(posts(h), [], 'reconnect only reads saved status; another POST needs another explicit click')
})

test('a fresh in-flight status attaches read-only instead of resubmitting the earlier Retry', async t => {
  const meta = report({ available: false })
  let active = false
  const h = mount(t, { report: meta, getStatus: async () => response({ ...routeShapedMissingBodyStatus(meta),
    ...(active ? { translation_job: job('running') } : {}),
  }) }); await settle()
  active = true
  await h.click('translate-btn', 'Retry translation')
  assert.deepEqual(posts(h), [])
  assert.equal(h.state.translationObserver.status.value, 'running')
  assert.equal(h.state.translationObserver.error.value, '')
})

test('source drift in the fresh status preflight cannot authorize a retry against old report metadata', async t => {
  const meta = report({ available: false })
  let changed = false
  const h = mount(t, { report: meta, getStatus: async () => response({ ...routeShapedMissingBodyStatus(meta),
    source_markdown_sha256: changed ? 'd'.repeat(64) : sha,
  }) }); await settle()
  changed = true
  await h.click('translate-btn', 'Retry translation')
  assert.deepEqual(posts(h), [])
  assert.equal(h.state.translationObserver.status.value, 'reconnecting')
  assert.match(h.state.translationObserver.error.value, /status source changed/)
})
