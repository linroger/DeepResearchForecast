import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { babelParse, compileScript, parse } from '@vue/compiler-sfc'
import * as vue from 'vue'

import * as markdown from '../src/utils/markdown.js'
import * as i18n from '../src/i18n.js'
import * as officialData from '../src/utils/officialData.js'
import * as researchTranslation from '../src/utils/researchTranslation.js'

// Execute the actual SFC setup and its methods with real Vue reactivity. Only
// API calls and timers are injected; no browser, backend, or network is involved.
// The compiler's returned setup bindings expose methods without a production
// defineExpose/test hook or a second implementation of the translation workflow.
const filename = new URL('../src/components/research/DossierViewer.vue', import.meta.url)
const { descriptor } = parse(readFileSync(filename, 'utf8'))
const script = compileScript(descriptor, {
  id: 'dossier-translation-envelope-test',
  genDefaultAs: 'DossierViewer',
})
let setupCode = script.content
const imports = babelParse(setupCode, { sourceType: 'module' }).program.body
  .filter(node => node.type === 'ImportDeclaration')
for (const node of imports.reverse()) {
  const bindings = node.specifiers.map(specifier => {
    assert.equal(specifier.type, 'ImportSpecifier')
    return `const ${specifier.local.name} = imports[${JSON.stringify(node.source.value)}][${JSON.stringify(specifier.imported.name)}];`
  }).join('\n')
  setupCode = setupCode.slice(0, node.start) + bindings + setupCode.slice(node.end)
}
const createComponent = new Function('imports', 'setTimeout', 'clearTimeout',
  `${setupCode}\nreturn DossierViewer;`)

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

// Allow fire-and-forget language switches and poll callbacks to finish their
// promise continuations, including Vue's default queued identity watcher.
const settle = () => new Promise(resolve => setImmediate(resolve))

function dossier(t, { get, post } = {}) {
  i18n.locale.value = 'en'
  const calls = []
  const timers = new Map()
  let timerId = 0
  const unexpected = () => { throw new Error('Unexpected API call') }
  const api = {
    editDossier: unexpected,
    getArtifact: unexpected,
    researchChartUrl: () => null,
    researchPdfUrl: (id, lang) => `/api/research/${id}/dossier/pdf${lang ? `?lang=${lang}` : ''}`,
    getResearchTranslation: (id, lang) => {
      calls.push(['get', id, lang])
      return (get || unexpected)(id, lang)
    },
    requestResearchTranslation: (id, lang) => {
      calls.push(['post', id, lang])
      return (post || unexpected)(id, lang)
    },
  }
  const component = createComponent({
    vue,
    '../../utils/markdown': markdown,
    '../../i18n': i18n,
    '../../api/research': api,
    '../../utils/researchTranslation': researchTranslation,
    '../../utils/officialData': officialData,
    '../../utils/saveTextFile': { saveTextFile: unexpected },
  }, (callback, delay) => {
    const id = ++timerId
    timers.set(id, { callback, delay })
    return id
  }, id => timers.delete(id))
  const props = vue.reactive({
    pipelineId: 'pipe_A',
    dossier: { has_report: true, report: '# Source A\n\nEnglish report body.' },
    editable: false,
  })
  const scope = vue.effectScope()
  const state = scope.run(() => component.setup(props, { expose() {}, emit() {} }))
  t.after(() => { state.stopTranslationPolling(); scope.stop() })
  return {
    state, props, calls, timers,
    async poll() {
      assert.equal(timers.size, 1, 'exactly one translation poll must be scheduled')
      const [id, timer] = [...timers][0]
      assert.equal(timer.delay, 4000, 'preserve the existing poll interval')
      timers.delete(id)
      timer.callback()
      await settle()
    },
  }
}

test('GET body loads the available translation and preserves cache/source toggling', async t => {
  const h = dossier(t, {
    get: async () => ({ success: true, data: {
      status: 'available', available: true, issues: [], report: '# 中文译文\n\n正文。',
      source_lang: 'en', target_lang: 'zh',
    } }),
  })
  h.state.switchReportLang('zh')
  await settle()

  assert.equal(h.state.translationStatus.value, 'available')
  assert.equal(h.state.reportMarkdown.value, '# 中文译文\n\n正文。')
  assert.match(h.state.renderedReport.value, /中文译文/)
  assert.equal(h.state.pdfDisabled.value, false)
  assert.equal(h.state.researchPdfHref.value, '/api/research/pipe_A/dossier/pdf?lang=zh')
  assert.equal(h.state.showGenerateTranslation.value, false)
  assert.equal(h.state.reportLangLoading.value, false)
  assert.equal(h.timers.size, 0)

  h.state.switchReportLang(null)
  assert.equal(h.state.reportMarkdown.value, h.props.dossier.report)
  h.state.switchReportLang('zh')
  assert.equal(h.state.reportMarkdown.value, '# 中文译文\n\n正文。')
  assert.deepEqual(h.calls, [['get', 'pipe_A', 'zh']], 'cached switches never reload or generate')
})

test('unavailable GET stays on source; POST generating polls until available', async t => {
  const generation = deferred()
  const responses = [
    { success: true, data: { status: 'unavailable', available: false, report: null } },
    { success: true, data: { status: 'generating', available: false, report: null } },
    { success: true, data: { status: 'available', available: true, report: '完成的中文译文。' } },
  ]
  const h = dossier(t, { get: async () => responses.shift(), post: () => generation.promise })
  h.state.switchReportLang('zh')
  await settle()
  assert.equal(h.state.reportMarkdown.value, h.props.dossier.report)
  assert.equal(h.state.showGenerateTranslation.value, true)
  assert.equal(h.state.pdfDisabled.value, true)
  assert.equal(h.timers.size, 0)

  const pending = h.state.generateResearchTranslation()
  await h.state.generateResearchTranslation()
  assert.equal(h.state.translationBusy.value, true)
  assert.equal(h.calls.filter(call => call[0] === 'post').length, 1, 'deduplicate generation')
  generation.resolve({ success: true, data: { status: 'generating', available: false } })
  await pending
  assert.equal(h.state.translationStatus.value, 'generating')
  assert.equal(h.state.translationBusy.value, false)
  assert.equal(h.state.translationFeedback.value, 'Generating translation…')
  await h.poll()
  assert.equal(h.state.translationStatus.value, 'generating')
  assert.equal(h.state.reportMarkdown.value, h.props.dossier.report)
  await h.poll()
  assert.equal(h.state.translationStatus.value, 'available')
  assert.equal(h.state.reportMarkdown.value, '完成的中文译文。')
  assert.equal(h.state.translationFeedback.value, '')
  assert.equal(h.timers.size, 0)
  assert.deepEqual(h.calls, [
    ['get', 'pipe_A', 'zh'], ['post', 'pipe_A', 'zh'],
    ['get', 'pipe_A', 'zh'], ['get', 'pipe_A', 'zh'],
  ])
})

test('already-available POST immediately loads the verified GET report without a poll', async t => {
  const h = dossier(t, {
    post: async () => ({ success: true, data: { status: 'available', available: true } }),
    get: async () => ({ success: true, data: { status: 'available', available: true, report: '已存在的译文。' } }),
  })
  await h.state.generateResearchTranslation()
  assert.deepEqual(h.calls, [['post', 'pipe_A', 'zh'], ['get', 'pipe_A', 'zh']])
  assert.equal(h.state.researchLangCache.value.zh, '已存在的译文。')
  assert.equal(h.state.translationStatus.value, 'available')
  assert.equal(h.timers.size, 0)
})

for (const status of ['interrupted', 'failed']) {
  test(`GET generating polls into ${status}, preserves issues, and offers retry`, async t => {
    const responses = [
      { success: true, data: { status: 'generating', available: false, report: null } },
      { success: true, data: { status, available: false, report: null, issues: ['worker stopped or audit failed'] } },
    ]
    const h = dossier(t, { get: async () => responses.shift() })
    h.state.switchReportLang('zh')
    await settle()
    assert.equal(h.state.translationStatus.value, 'generating')
    await h.poll()
    assert.equal(h.state.translationStatus.value, status)
    assert.deepEqual(h.state.translationIssues.value, ['worker stopped or audit failed'])
    assert.equal(h.state.translationButtonLabel.value, 'Retry translation')
    assert.match(h.state.translationFeedback.value, status === 'failed' ? /publication audit/ : /interrupted/)
    assert.equal(h.state.reportMarkdown.value, h.props.dossier.report)
    assert.deepEqual(h.state.researchLangCache.value, {})
    assert.equal(h.state.showGenerateTranslation.value, true)
    assert.equal(h.state.pdfDisabled.value, true)
    assert.equal(h.state.reportLangLoading.value, false)
    assert.equal(h.timers.size, 0)
    assert.equal(h.calls.length, 2, 'status checks never automatically generate')
  })
}

test('rejected API requests release loading/busy state and keep the source', async t => {
  const fail = async () => { throw new Error('Local API stub rejection') }
  const h = dossier(t, { get: fail, post: fail })
  h.state.switchReportLang('zh')
  await settle()
  assert.equal(h.state.translationStatus.value, 'unavailable')
  assert.equal(h.state.reportLangLoading.value, false)
  await h.state.generateResearchTranslation()
  assert.equal(h.state.translationStatus.value, 'failed')
  assert.equal(h.state.translationBusy.value, false)
  assert.equal(h.state.reportMarkdown.value, h.props.dossier.report)
  assert.equal(h.timers.size, 0)
})

for (const identity of ['pipeline', 'source']) {
  const changeIdentity = props => {
    if (identity === 'pipeline') props.pipelineId = 'pipe_B'
    else props.dossier.report = '# Revised source\n\nNew English report.'
  }

  test(`a ${identity} change rejects late GET bytes and preserves the new loading state`, async t => {
    const oldLoad = deferred()
    const newLoad = deferred()
    const h = dossier(t, { get: () => h.calls.length === 1 ? oldLoad.promise : newLoad.promise })
    h.state.switchReportLang('zh')
    changeIdentity(h.props)
    await vue.nextTick()
    assert.equal(h.state.activeReportLang.value, null)
    assert.deepEqual(h.state.researchLangCache.value, {})
    h.state.switchReportLang('zh')
    oldLoad.resolve({ success: true, data: { status: 'available', available: true, report: '旧译文。' } })
    await settle()
    assert.deepEqual(h.state.researchLangCache.value, {})
    assert.equal(h.state.reportMarkdown.value, h.props.dossier.report)
    assert.equal(h.state.reportLangLoading.value, true)
    newLoad.resolve({ success: true, data: { status: 'available', available: true, report: '新译文。' } })
    await settle()
    assert.equal(h.state.reportMarkdown.value, '新译文。')
    assert.equal(h.state.reportLangLoading.value, false)
  })

  for (const outcome of ['generating', 'available', 'rejected']) {
    test(`a ${identity} change ignores stale POST ${outcome}, including busy cleanup`, async t => {
      const oldPost = deferred()
      const newPost = deferred()
      const h = dossier(t, { post: () => h.calls.length === 1 ? oldPost.promise : newPost.promise })
      const oldRequest = h.state.generateResearchTranslation()
      changeIdentity(h.props)
      await vue.nextTick()
      const newRequest = h.state.generateResearchTranslation()
      if (outcome === 'rejected') oldPost.reject(new Error('Old generation failed'))
      else oldPost.resolve({ success: true, data: { status: outcome, available: outcome === 'available' } })
      await oldRequest
      assert.equal(h.state.translationStatus.value, '')
      assert.equal(h.state.translationBusy.value, true, 'old cleanup cannot release the new request')
      assert.deepEqual(h.state.researchLangCache.value, {})
      assert.equal(h.timers.size, 0, 'old POST cannot create a poll for the new report')
      assert.equal(h.calls.length, 2, 'old POST cannot load a translation for the new report')
      newPost.resolve({ success: true, data: { status: 'generating', available: false } })
      await newRequest
      assert.equal(h.state.translationStatus.value, 'generating')
      assert.equal(h.state.translationBusy.value, false)
      assert.equal(h.timers.size, 1)
    })
  }

  test(`a ${identity} change cancels polling and rejects an already-dequeued callback`, async t => {
    const h = dossier(t, { get: async () => ({ success: true, data: { status: 'generating', available: false } }) })
    await h.state.loadResearchTranslation('zh')
    assert.equal(h.timers.size, 1)
    const queuedCallback = [...h.timers.values()][0].callback
    changeIdentity(h.props)
    await vue.nextTick()
    assert.equal(h.timers.size, 0)
    queuedCallback()
    await settle()
    assert.equal(h.calls.length, 1)
    assert.equal(h.state.translationStatus.value, '')
  })
}
