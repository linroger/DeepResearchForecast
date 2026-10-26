import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import test from 'node:test'
import * as vue from 'vue'
import { compileSfc } from './sfcHarness.mjs'
import * as markdown from '../src/utils/markdown.js'
import * as i18n from '../src/i18n.js'
import * as officialData from '../src/utils/officialData.js'
import * as researchTranslation from '../src/utils/researchTranslation.js'
import * as translationJob from '../src/composables/useTranslationJob.js'
import * as dossierTranslation from '../src/utils/dossierTranslationAdapter.js'
import * as pdfDownload from '../src/utils/pdfDownload.js'

const sha = text => createHash('sha256').update(text).digest('hex')
const build = compileSfc(new URL('../src/components/research/DossierViewer.vue', import.meta.url))
const pendingDigests = new Set()
const digestTests = new WeakSet()
function trackDigests(t) {
  if (digestTests.has(t)) return
  digestTests.add(t)
  const digest = globalThis.crypto.subtle.digest.bind(globalThis.crypto.subtle)
  t.mock.method(globalThis.crypto.subtle, 'digest', (...args) => {
    const pending = digest(...args)
    pendingDigests.add(pending)
    pending.then(() => pendingDigests.delete(pending), () => pendingDigests.delete(pending))
    return pending
  })
}
const settle = async () => {
  await new Promise(resolve => setImmediate(resolve))
  while (pendingDigests.size) {
    await Promise.all([...pendingDigests])
    await new Promise(resolve => setImmediate(resolve))
  }
  await vue.nextTick()
}
const response = data => ({ success: true, data: { target_lang: 'zh', ...data } })
const unavailable = () => response({ status: 'unavailable', available: false })
const admitted = (extra = {}) => response({ status: 'available', available: true, report: '# 已审计的中文报告\n\n中文正文。', ...extra })
function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

// Mount the compiled SFC using actual Vue rendering, lifecycle and observer code.
// Only DOM primitives and transport are injected. Tests click rendered controls.
function node(type, text = '') { return { type, text, props: {}, children: [], parent: null, style: {} } }
const renderer = vue.createRenderer({
  createElement: tag => node(tag), createText: text => node('#text', text), createComment: text => node('#comment', text),
  setText: (n, text) => { n.text = text }, setElementText: (n, text) => { n.text = text; n.children = [] },
  patchProp: (n, key, _old, value) => { n.props[key] = value }, parentNode: n => n.parent,
  nextSibling: n => n.parent?.children[n.parent.children.indexOf(n) + 1] || null,
  insert(n, parent, anchor = null) {
    if (n.parent) n.parent.children.splice(n.parent.children.indexOf(n), 1)
    n.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index < 0) parent.children.push(n); else parent.children.splice(index, 0, n)
  },
  remove(n) { if (n.parent) n.parent.children.splice(n.parent.children.indexOf(n), 1); n.parent = null },
})
const nodes = n => [n, ...n.children.flatMap(nodes)]
const text = n => n.type === '#comment' ? '' : n.text + (n.props.innerHTML || '') + n.children.map(text).join('')
function mountDossier(t, { get = unavailable, post = () => response({ status: 'generating' }), dossier = {} } = {}) {
  trackDigests(t)
  t.mock.timers.enable({ apis: ['setTimeout'] })
  i18n.locale.value = 'en'
  const calls = []
  const component = build({
    vue: { ...vue, defineAsyncComponent: () => ({ props: ['context', 'lang'], render() { return vue.h('aside', JSON.stringify(this.context)) } }) },
    '../../utils/markdown': markdown, '../../i18n': i18n, '../../utils/officialData': officialData,
    '../../utils/researchTranslation': researchTranslation, '../../composables/useTranslationJob': translationJob,
    '../../utils/dossierTranslationAdapter': dossierTranslation, '../../utils/pdfDownload': pdfDownload,
    '../../utils/saveTextFile': { saveTextFile() { throw new Error('Unexpected CSV') } },
    '../../api/research': {
      editDossier() { throw new Error('Unexpected edit') }, getArtifact() { throw new Error('Unexpected artifact') }, researchChartUrl: () => '',
      researchPdfUrl: (id, lang, { sourceSha, generation } = {}) => {
        const query = new URLSearchParams()
        if (lang) query.set('lang', lang)
        if (sourceSha) query.set('source_sha256', sourceSha)
        if (generation) query.set('generation', generation)
        return `/api/research/${id}/dossier/pdf${query.size ? `?${query}` : ''}`
      },
      getResearchTranslation(id, lang, options) {
        calls.push({ method: 'get', id, lang, ...options })
        const sourceSha = sha(props.dossier.report)
        return Promise.resolve(get(id, lang, options)).then(result => ({ ...result, data: { source_sha256: sourceSha, ...result.data } }))
      },
      requestResearchTranslation(id, lang, force, options) {
        calls.push({ method: 'post', id, lang, force, ...options })
        const sourceSha = sha(props.dossier.report)
        return Promise.resolve(post(id, lang, force, options)).then(result => ({ ...result, data: { source_sha256: sourceSha, ...result.data } }))
      },
    },
  })
  const props = vue.reactive({ pipelineId: 'pipe_A', editable: false, artifactNames: [],
    dossier: { has_report: true, report: '# Source A\n\nEnglish research body.', ...dossier } })
  const root = node('root')
  const app = renderer.createApp({ render: () => vue.h(component, props) })
  app.mount(root)
  let mounted = true
  const unmount = () => { if (mounted) { app.unmount(); mounted = false } }
  t.after(() => { unmount(); i18n.locale.value = 'en' })
  const buttons = () => nodes(root).filter(n => n.type === 'button')
  const button = label => {
    const found = buttons().find(n => typeof label === 'string' ? text(n) === label : label.test(text(n)))
    assert.ok(found, `Missing button ${label}: ${buttons().map(text).join(' | ')}`)
    return found
  }
  const clickNode = n => { assert.ok(!n.props.disabled, `Button disabled: ${text(n)}`); return n.props.onClick({ preventDefault() {} }) }
  return { root, props, calls, button, unmount, text: () => text(root), click: label => clickNode(button(label)),
    source: () => clickNode(buttons().filter(n => String(n.props.class).includes('lang-btn'))[0]),
    target: () => clickNode(buttons().filter(n => String(n.props.class).includes('lang-btn'))[1]),
    poll: async (ms = 2500) => { t.mock.timers.tick(ms); await settle() },
  }
}
const pdfResponse = () => new Response('%PDF-1.7\nverified', { headers: { 'Content-Type': 'application/pdf' } })
function downloads(t, fetcher = async () => pdfResponse()) {
  const requests = [], saved = [], revoked = []
  t.mock.method(globalThis, 'fetch', (url, options) => { requests.push({ url, ...options }); return fetcher(url, options) })
  t.mock.method(URL, 'createObjectURL', () => 'blob:verified-pdf')
  t.mock.method(URL, 'revokeObjectURL', url => revoked.push(url))
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'document')
  Object.defineProperty(globalThis, 'document', { configurable: true, value: {
    body: { appendChild() {} }, createElement: () => ({ style: {}, click() { saved.push(this.download) }, remove() {} }),
  } })
  t.after(() => { if (previous) Object.defineProperty(globalThis, 'document', previous); else delete globalThis.document })
  return { requests, saved, revoked }
}

test('language selection only observes; Generate deduplicates and polls into admitted content', async t => {
  let reads = 0
  const posting = deferred()
  const h = mountDossier(t, { get: () => ++reads === 1 ? unavailable() : admitted(), post: () => posting.promise })
  assert.equal(h.calls.length, 0, 'Source disables observation at mount')
  h.target(); await settle()
  assert.deepEqual(h.calls.map(c => c.method), ['get'])
  assert.match(h.text(), /English research body/)
  assert.match(h.text(), /下方显示原文/)
  const status = nodes(h.root).filter(n => n.props.class === 'translation-job-status')
  assert.equal(status.length, 1, 'the actual shared status component owns the feedback region')
  assert.equal(status[0].props.role, 'status')
  assert.match(text(status[0]), /下方显示原文/, 'dossier-specific feedback renders through its slot')
  assert.equal(nodes(status[0]).filter(n => n.type === 'button' || n.type === 'details').length, 0,
    'shared actions and issues are disabled to preserve the existing dossier controls')
  const request = h.click('生成中文'); await settle()
  assert.equal(h.button('翻译中…').props.disabled, true)
  assert.equal(h.calls.filter(c => c.method === 'post').length, 1)
  assert.equal(h.calls.at(-1).force, false)
  posting.resolve(response({ status: 'generating', translation_job: { job_state: 'running' } }))
  await request; await settle()
  assert.match(h.text(), /正在生成译文/)
  await h.poll()
  assert.match(h.text(), /已审计的中文报告/)
  assert.ok(h.button('下载中文 PDF'))
  h.source(); await settle()
  assert.match(h.text(), /English research body/)
  assert.doesNotMatch(h.text(), /已审计的中文报告/)
  h.target(); await settle()
  assert.equal(h.calls.filter(c => c.method === 'post').length, 1)
  assert.match(h.text(), /已审计的中文报告/)
})

test('attached interrupted job overrides generating; Retry reuses and Refresh alone forces', async t => {
  const h = mountDossier(t, { dossier: { actors: { actors: [{ name: 'Original actor' }] } },
    get: () => admitted({ partial: true, dossier: { actors: { actors: [{ name: '参与者译文' }] } },
      structured_translation: { status: 'generating', complete: false },
      translation_job: { job_state: 'interrupted', actions: { retry: true }, issues: ['Review interrupted'],
        coverage: { required: 8, accepted: 6, pending_translation: 1, pending_review: 1 } } }),
    post: () => admitted({ dossier: { actors: { actors: [{ name: '完整译文' }] } } }),
  })
  h.target(); await settle()
  assert.match(h.text(), /参与者译文/)
  assert.match(h.text(), /6\/8/)
  assert.match(h.text(), /Review interrupted/)
  await h.click('重试翻译'); await settle()
  assert.equal(h.calls.at(-1).force, false)
  assert.match(h.text(), /完整译文/)
  await h.click('重新翻译'); await settle()
  assert.equal(h.calls.at(-1).force, true)
})

test('available POST acknowledgment reads the audited GET using the same subscription', async t => {
  let reads = 0
  const h = mountDossier(t, { get: () => ++reads === 1 ? unavailable() : admitted(), post: () => response({ status: 'available', available: true }) })
  h.target(); await settle()
  await h.click('生成中文'); await settle()
  assert.deepEqual(h.calls.map(c => c.method), ['get', 'post', 'get'])
  assert.match(h.text(), /已审计的中文报告/)
})

test('legacy body plus generating cards keeps polling and discloses partial coverage', async t => {
  let reads = 0
  const h = mountDossier(t, { get: () => ++reads === 1 ? admitted({ structured_translation: {
    status: 'generating', complete: false, coverage: { total: 3, translated: 2 },
  } }) : admitted() })
  h.target(); await settle()
  assert.match(h.text(), /部分翻译/)
  assert.match(h.text(), /2\/3/)
  await h.poll()
  assert.equal(h.calls.length, 2)
  assert.doesNotMatch(h.text(), /部分翻译/)
})

test('transient GET and uncertain POST failures reconnect using GET only', async t => {
  let reads = 0
  const h = mountDossier(t, { get: () => {
    if (++reads === 2) throw new Error('Temporary connection failure')
    return reads >= 3 ? admitted() : unavailable()
  }, post: async () => { throw new Error('POST response lost') } })
  h.target(); await settle()
  await h.click('生成中文'); await settle()
  assert.match(h.text(), /POST response lost/)
  await h.poll()
  assert.match(h.text(), /Temporary connection failure/)
  await h.poll(5000)
  assert.match(h.text(), /已审计的中文报告/)
  assert.equal(h.calls.filter(c => c.method === 'post').length, 1)
})

test('wrong-language publication fails closed without automatic reconnect', async t => {
  const h = mountDossier(t, { get: () => admitted({ target_lang: 'en', report: 'WRONG VARIANT' }) })
  h.target(); await settle()
  assert.match(h.text(), /language does not match/)
  assert.doesNotMatch(h.text(), /WRONG VARIANT/)
  assert.ok(h.button('下载英文 PDF'))
  await h.poll(20000)
  assert.equal(h.calls.length, 1)
})

for (const change of ['source selection', 'pipeline', 'body', 'structured content', 'unmount']) {
  test(`${change} aborts late GET and prevents stale translated bytes`, async t => {
    const old = deferred()
    const h = mountDossier(t, { get: () => old.promise })
    h.target(); await settle()
    const signal = h.calls[0].signal
    if (change === 'source selection') h.source()
    else if (change === 'pipeline') h.props.pipelineId = 'pipe_B'
    else if (change === 'body') h.props.dossier.report = '# New source'
    else if (change === 'structured content') h.props.dossier.actors = { actors: [{ name: 'New actor' }] }
    else h.unmount()
    await settle()
    assert.equal(signal.aborted, true)
    old.resolve(admitted({ report: 'STALE TRANSLATION' })); await settle()
    assert.doesNotMatch(h.text(), /STALE TRANSLATION/)
    await h.poll(20000)
    assert.equal(h.calls.length, 1)
  })
}
for (const outcome of ['generating', 'available', 'rejected']) {
  test(`late POST ${outcome} cannot affect the new pipeline or clear its busy state`, async t => {
    const old = deferred(), current = deferred()
    let posts = 0
    const h = mountDossier(t, { post: () => ++posts === 1 ? old.promise : current.promise })
    h.target(); await settle()
    const first = h.click('生成中文')
    h.props.pipelineId = 'pipe_B'; await settle()
    h.target(); await settle()
    const second = h.click('生成中文'); await settle()
    if (outcome === 'rejected') old.reject(new Error('STALE ERROR'))
    else old.resolve(response({ status: outcome, available: outcome === 'available' }))
    await first; await settle()
    assert.equal(h.button('翻译中…').props.disabled, true)
    assert.doesNotMatch(h.text(), /STALE ERROR/)
    assert.equal(h.calls.length, 4, 'stale POST cannot issue a publication GET')
    current.resolve(admitted()); await second; await settle()
    assert.match(h.text(), /已审计的中文报告/)
  })
}

test('Source and target fallback export the unsuffixed source with an explicit English label', async t => {
  const files = downloads(t)
  const h = mountDossier(t)
  await h.click('Download English PDF'); await settle()
  assert.equal(new URL(files.requests[0].url, 'https://example.test').pathname, '/api/research/pipe_A/dossier/pdf')
  assert.equal(new URL(files.requests[0].url, 'https://example.test').searchParams.get('lang'), null)
  assert.equal(new URL(files.requests[0].url, 'https://example.test').searchParams.get('source_sha256'), sha(h.props.dossier.report))
  assert.equal(files.requests[0].headers.Accept, 'application/pdf')
  assert.equal(files.saved[0], 'research_pipe_A.pdf')
  h.target(); await settle()
  await h.click('下载英文 PDF'); await settle()
  assert.equal(new URL(files.requests[1].url, 'https://example.test').searchParams.get('lang'), null)
  assert.equal(new URL(files.requests[1].url, 'https://example.test').searchParams.get('source_sha256'), sha(h.props.dossier.report))
  assert.equal(files.saved[1], 'research_pipe_A.pdf')
  assert.equal(h.calls.filter(c => c.method === 'post').length, 0)
  t.mock.timers.tick(1)
  assert.equal(files.revoked.length, 2)
})
for (const sourceLang of ['en', 'zh']) {
  test(`${sourceLang} source exports admitted opposite-language PDF with the correct suffix`, async t => {
    const files = downloads(t)
    const target = sourceLang === 'en' ? 'zh' : 'en'
    const h = mountDossier(t, { dossier: { report: sourceLang === 'en' ? '# English source' : '# 中文原始研究报告\n\n大量中文内容。' },
      get: () => admitted({ target_lang: target, report: target === 'zh' ? '中文译文。' : 'Admitted English report.' }) })
    h.target(); await settle()
    await h.click(target === 'zh' ? '下载中文 PDF' : 'Download English PDF'); await settle()
    assert.equal(new URL(files.requests[0].url, 'https://example.test').searchParams.get('lang'), target)
    assert.equal(new URL(files.requests[0].url, 'https://example.test').searchParams.get('source_sha256'), sha(h.props.dossier.report))
    assert.equal(files.saved[0], `research_pipe_A.${target}.pdf`)
    h.source(); await settle()
    assert.ok(h.button(sourceLang === 'en' ? 'Download English PDF' : 'Download Mandarin PDF'))
  })
}
for (const failure of [
  { body: '<html>Error</html>', type: 'text/html', expected: /invalid content type/ },
  { body: '{"error":"failure"}', type: 'application/pdf', expected: /invalid PDF file/ },
  { body: '%PDF-1.7', type: 'application/json', expected: /invalid content type/ },
  { body: '{"error":{"message":"PDF rendering is disabled"}}', type: 'application/json', status: 503, expected: /rendering is disabled/ },
  { body: '<html>Internal error</html>', type: 'text/html', status: 500, expected: /HTTP 500/ },
  { body: '{"code":"pdf_export_disabled"}', type: 'application/json', status: 503, expected: /PDF export is disabled/ },
]) {
  test(`PDF rejects ${failure.status || 200} ${failure.type} with inline error and released busy state`, async t => {
    const files = downloads(t, async () => new Response(failure.body, { status: failure.status || 200, headers: { 'Content-Type': failure.type } }))
    const h = mountDossier(t)
    await h.click('Download English PDF'); await settle()
    assert.match(h.text(), failure.expected)
    assert.equal(files.saved.length, 0)
    assert.equal(h.button('Download English PDF').props.disabled, false)
    assert.ok(nodes(h.root).some(n => n.props.role === 'alert' && failure.expected.test(text(n))))
  })
}

test('PDF busy disables repeated clicks and Source cancels a late completion', async t => {
  const pending = deferred()
  const files = downloads(t, () => pending.promise)
  const h = mountDossier(t, { get: admitted })
  h.target(); await settle()
  const request = h.click('下载中文 PDF'); await settle()
  assert.equal(h.button('正在导出 PDF…').props.disabled, true)
  h.source(); await settle()
  assert.equal(files.requests[0].signal.aborted, true)
  pending.resolve(pdfResponse()); await request; await settle()
  assert.equal(files.saved.length, 0)
  assert.equal(h.button('Download English PDF').props.disabled, false)
})
for (const change of ['pipeline', 'source', 'newly admitted translation', 'unmount']) {
  test(`PDF ${change} invalidates late bytes even if transport ignores abort`, async t => {
    const bytes = deferred(), translated = deferred()
    const files = downloads(t, async () => ({ ok: true, headers: new Headers({ 'Content-Type': 'application/pdf' }), blob: () => bytes.promise }))
    const h = mountDossier(t, { get: () => translated.promise })
    if (change === 'newly admitted translation') { h.target(); await settle() }
    const request = h.click(change === 'newly admitted translation' ? '下载英文 PDF' : 'Download English PDF')
    await settle()
    if (change === 'pipeline') h.props.pipelineId = 'pipe_B'
    else if (change === 'source') h.props.dossier.report = '# Revised source'
    else if (change === 'newly admitted translation') translated.resolve(admitted())
    else h.unmount()
    await settle()
    assert.equal(files.requests[0].signal.aborted, true)
    bytes.resolve(new Blob(['%PDF-1.7'], { type: 'application/pdf' })); await request; await settle()
    assert.equal(files.saved.length, 0)
  })
}

test('late PDF rejection cannot clear a new export or inject its error', async t => {
  const old = deferred(), current = deferred()
  let requests = 0
  const files = downloads(t, () => ++requests === 1 ? old.promise : current.promise)
  const h = mountDossier(t)
  const first = h.click('Download English PDF')
  await settle()
  h.props.pipelineId = 'pipe_B'; await settle()
  const second = h.click('Download English PDF'); await settle()
  old.reject(new Error('STALE PDF ERROR')); await first; await settle()
  assert.doesNotMatch(h.text(), /STALE PDF ERROR/)
  assert.equal(h.button('Exporting PDF…').props.disabled, true)
  current.resolve(pdfResponse()); await second; await settle()
  assert.deepEqual(files.saved, ['research_pipe_B.pdf'])
})

test('refresh acknowledgments preserve admitted content; authoritative GET can revoke it', async t => {
  let reads = 0
  const h = mountDossier(t, {
    get: () => ++reads === 1 ? admitted() : response({ status: 'failed', available: false, report: null, issues: ['Publication revoked'] }),
    post: () => response({ status: 'generating', available: false }),
  })
  h.target(); await settle()
  await h.click('重新翻译'); await settle()
  assert.match(h.text(), /已审计的中文报告/)
  assert.ok(h.button('下载中文 PDF'), 'an acknowledgment is not an audit revocation')
  await h.poll()
  assert.doesNotMatch(h.text(), /已审计的中文报告/)
  assert.ok(h.button('下载英文 PDF'), 'an authoritative absence falls back to source')
})

test('same-tick repeated Generate and PDF events perform only one request each', async t => {
  const posting = deferred(), fetching = deferred()
  const files = downloads(t, () => fetching.promise)
  const h = mountDossier(t, { post: () => posting.promise })
  h.target(); await settle()
  const generate = h.button('生成中文').props.onClick
  const first = generate(), second = generate()
  assert.equal(h.calls.filter(c => c.method === 'post').length, 1)
  posting.resolve(admitted()); await Promise.all([first, second]); await settle()
  const download = h.button('下载中文 PDF').props.onClick
  const export1 = download(), export2 = download()
  assert.equal(files.requests.length, 1)
  fetching.resolve(pdfResponse()); await Promise.all([export1, export2]); await settle()
  assert.equal(files.saved.length, 1)
})

test('a dequeued polling callback cannot read again after returning to Source', async t => {
  const h = mountDossier(t, { get: () => response({ status: 'generating' }) })
  h.target(); await settle()
  h.source(); await settle()
  await h.poll(10000)
  assert.equal(h.calls.length, 1)
})

test('admitted PDF uses its publication identity across refresh acknowledgments', async t => {
  const files = downloads(t)
  const h = mountDossier(t, { get: () => admitted({ generation: 'generation-A' }),
    post: () => response({ status: 'generating', available: false }) })
  h.target(); await settle()
  await h.click('重新翻译'); await settle()
  await h.click('下载中文 PDF'); await settle()
  const query = new URL(files.requests[0].url, 'https://example.test').searchParams
  assert.equal(query.get('lang'), 'zh')
  assert.equal(query.get('source_sha256'), sha(h.props.dossier.report))
  assert.equal(query.get('generation'), 'generation-A')
})

for (const identity of [{ ref_id: 'pipe_B' }, { target_lang: 'en' }, { source_sha256: 'other-source' }]) {
  test(`foreign job identity ${JSON.stringify(identity)} cannot display publication bytes`, async t => {
    const h = mountDossier(t, { dossier: { source_sha256: sha('# Source A\n\nEnglish research body.') }, get: () => admitted({
      translation_job: { job_state: 'completed', identity }, report: 'FOREIGN BYTES',
    }) })
    h.target(); await settle()
    assert.doesNotMatch(h.text(), /FOREIGN BYTES/)
    assert.match(h.text(), /does not match/)
    assert.ok(h.button('下载英文 PDF'))
    await h.poll(20000)
    assert.equal(h.calls.length, 1)
  })
}

test('a replacement generation with unchanged body still cancels the earlier PDF request', async t => {
  let reads = 0
  const bytes = deferred()
  const files = downloads(t, () => bytes.promise)
  const h = mountDossier(t, { get: () => admitted({ generation: ++reads === 1 ? 'generation-A' : 'generation-B',
    translation_job: { job_state: reads === 1 ? 'running' : 'completed' } }) })
  h.target(); await settle()
  const request = h.click('下载中文 PDF'); await settle()
  await h.poll()
  assert.equal(files.requests[0].signal.aborted, true)
  bytes.resolve(pdfResponse()); await request; await settle()
  assert.equal(files.saved.length, 0)
})

test('server source drift without prop update revokes body and cards and binds fallback PDF to the displayed source', async t => {
  let reads = 0
  const files = downloads(t, async () => new Response(JSON.stringify({ code: 'source_changed' }), {
    status: 409, headers: { 'Content-Type': 'application/json' },
  }))
  const h = mountDossier(t, { dossier: { actors: { actors: [{ name: 'Original actor' }] } }, get: () => ++reads === 1
    ? admitted({ dossier: { actors: { actors: [{ name: 'ADMITTED OLD CARD' }] } }, translation_job: { job_state: 'running' } })
    : admitted({ source_sha256: sha('# Server changed the source'), report: 'FOREIGN NEW BODY',
      dossier: { actors: { actors: [{ name: 'FOREIGN NEW CARD' }] } }, translation_job: { job_state: 'completed' } }) })
  const displayed = JSON.stringify(h.props.dossier)
  assert.equal(h.props.dossier.source_sha256, undefined, 'reproduce the digest-less dossier endpoint')
  h.target(); await settle()
  assert.match(h.text(), /已审计的中文报告/)
  assert.match(h.text(), /ADMITTED OLD CARD/)
  await h.poll()
  assert.equal(JSON.stringify(h.props.dossier), displayed, 'no client-side source update occurred')
  assert.doesNotMatch(h.text(), /已审计的中文报告|ADMITTED OLD CARD|FOREIGN NEW/)
  assert.match(h.text(), /Original actor/)
  assert.match(h.text(), /source does not match the displayed dossier/)
  await h.poll(20000)
  assert.equal(h.calls.length, 2, 'invalid source identity does not reconnect or POST automatically')
  await h.click('下载英文 PDF'); await settle()
  const query = new URL(files.requests[0].url, 'https://example.test').searchParams
  assert.equal(query.get('source_sha256'), sha(h.props.dossier.report))
  assert.equal(query.get('lang'), null)
  assert.equal(files.saved.length, 0)
  assert.match(h.text(), /source changed.*Reload the dossier/)
})

test('a missing response source digest cannot admit completed translation or projected cards', async t => {
  const h = mountDossier(t, { get: () => admitted({ source_sha256: undefined, report: 'UNBOUND BODY',
    dossier: { actors: { actors: [{ name: 'UNBOUND CARD' }] } }, translation_job: { job_state: 'completed' } }) })
  h.target(); await settle()
  assert.doesNotMatch(h.text(), /UNBOUND BODY|UNBOUND CARD/)
  assert.match(h.text(), /source does not match the displayed dossier/)
  assert.ok(h.button('下载英文 PDF'))
})
