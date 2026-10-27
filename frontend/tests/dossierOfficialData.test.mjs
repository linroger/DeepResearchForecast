import * as researchPdfExport from '../src/utils/researchPdfExport.js'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { babelParse, compileScript, parse } from '@vue/compiler-sfc'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'

import * as markdown from '../src/utils/markdown.js'
import * as i18n from '../src/i18n.js'
import * as officialData from '../src/utils/officialData.js'
import * as researchTranslation from '../src/utils/researchTranslation.js'
import { compileSfc } from './sfcHarness.mjs'

// Executes the real DossierViewer.vue setup (as dossierTranslationEnvelope.test.mjs
// does) with only the API and the file-save helper injected. The datasets payload is
// the REAL research handoff data/datasets.json served by GET /api/research/<pid>/artifact/datasets.
const filename = new URL('../src/components/research/DossierViewer.vue', import.meta.url)
const { descriptor } = parse(readFileSync(filename, 'utf8'))
const script = compileScript(descriptor, { id: 'dossier-official-data-test', genDefaultAs: 'DossierViewer' })
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
const createComponent = new Function('imports', 'setTimeout', 'clearTimeout', `${setupCode}\nreturn DossierViewer;`)

const datasetsResponse = JSON.parse(readFileSync(
  new URL('./fixtures/official/datasets_manifest.v3_run.json', import.meta.url), 'utf8'))
const UNRATE_CSV = 'fred_unrate_9d03984317fdea12.3d75202810c5af63.csv'
const settle = () => new Promise(resolve => setImmediate(resolve))

function dossier(t, { artifactNames = ['datasets'], getArtifact } = {}) {
  i18n.locale.value = 'en'
  const calls = []
  const saved = []
  const api = {
    editDossier: () => { throw new Error('Unexpected API call') },
    researchChartUrl: (id, rel) => `/api/research/${id}/artifact/chart_${rel.split('/').pop()}`,
    researchPdfUrl: id => `/api/research/${id}/dossier/pdf`,
    getResearchTranslation: () => { throw new Error('Unexpected API call') },
    requestResearchTranslation: () => { throw new Error('Unexpected API call') },
    getArtifact: (id, name) => {
      calls.push([id, name])
      return (getArtifact || (async () => datasetsResponse))(id, name)
    },
  }
  const component = createComponent({
    vue,
    '../../utils/markdown': markdown, '../../utils/researchPdfExport': researchPdfExport,
    '../../i18n': i18n,
    '../../api/research': api,
    '../../utils/researchTranslation': researchTranslation,
    '../../utils/officialData': officialData,
    '../../utils/saveTextFile': { saveTextFile: (...args) => saved.push(args) },
  }, setTimeout, clearTimeout)
  const props = vue.reactive({
    pipelineId: 'pipe_A',
    dossier: { has_report: true, report: '# Research\n\nBody.', sources: [] },
    editable: false,
    artifactNames,
  })
  const scope = vue.effectScope()
  const state = scope.run(() => component.setup(props, { expose() {}, emit() {} }))
  t.after(() => { state.stopTranslationPolling(); scope.stop(); i18n.locale.value = 'en' })
  return { state, props, calls, saved }
}

test('loads the registered datasets manifest into an Official Data tab', async t => {
  const h = dossier(t)
  await settle()
  assert.deepEqual(h.calls, [['pipe_A', 'datasets']])
  assert.equal(h.state.datasetRows.value.length, 8)
  const tab = h.state.tabs.value.find(entry => entry.key === 'data')
  assert.deepEqual(tab, { key: 'data', label: 'Official Data', count: 8 })
  assert.deepEqual(h.state.tabs.value.map(entry => entry.key).slice(-2), ['data', 'sources'])
  const unrate = h.state.datasetRows.value.find(row => row.series === 'fred:UNRATE')
  assert.equal(unrate.latestText, '4.2%')
  assert.equal(unrate.sourceId, 'S39')
  // Nothing beyond the manifest is registered: no chart or CSV link is offered.
  assert.equal(unrate.chartPath, '')
  assert.equal(unrate.csvArtifact, '')

  i18n.locale.value = 'zh'
  assert.equal(h.state.datasetRows.value.find(row => row.series === 'fred:UNRATE').label, '美国失业率')
})

test('runs without a registered datasets artifact never request it and show no tab', async t => {
  const h = dossier(t, { artifactNames: ['charts', 'dossier'] })
  await settle()
  assert.deepEqual(h.calls, [])
  assert.equal(h.state.tabs.value.some(entry => entry.key === 'data'), false)

  // The artifact appears on a later status poll: the manifest is loaded then.
  h.props.artifactNames = ['charts', 'dossier', 'datasets']
  await settle()
  assert.deepEqual(h.calls, [['pipe_A', 'datasets']])
  assert.equal(h.state.datasetRows.value.length, 8)
})

test('a failed manifest request hides the tab instead of erroring', async t => {
  const h = dossier(t, { getArtifact: async () => { throw new Error('404') } })
  await settle()
  assert.equal(h.state.datasetRows.value.length, 0)
  assert.equal(h.state.tabs.value.some(entry => entry.key === 'data'), false)
})

test('registered CSVs download the artifact content; failures surface an error', async t => {
  const csv = 'date,value\n2026-09-01,4.2\n'
  let fail = false
  const h = dossier(t, {
    artifactNames: ['datasets', `dataset_${UNRATE_CSV}_partial`, 'chart_data_fred_unrate_9d03984317fdea12.png'],
    getArtifact: async (id, name) => {
      if (name === 'datasets') return datasetsResponse
      if (fail) throw new Error('artifact missing')
      return { success: true, data: { name, content: csv } }
    },
  })
  await settle()
  const row = h.state.datasetRows.value.find(entry => entry.series === 'fred:UNRATE')
  assert.equal(row.csvArtifact, `dataset_${UNRATE_CSV}_partial`)
  assert.equal(row.chartPath, 'charts/data_fred_unrate_9d03984317fdea12.png')

  await h.state.downloadDatasetCsv(row)
  assert.deepEqual(h.calls.at(-1), ['pipe_A', `dataset_${UNRATE_CSV}_partial`])
  assert.deepEqual(h.saved, [[csv, UNRATE_CSV, 'text/csv;charset=utf-8']])
  assert.equal(h.state.csvBusy.value, '')
  assert.equal(h.state.csvError.value, '')

  fail = true
  await h.state.downloadDatasetCsv(row)
  assert.equal(h.saved.length, 1)
  assert.equal(h.state.csvError.value, 'artifact missing')
  assert.equal(h.state.csvBusy.value, '')
})

test('a pipeline change discards a late manifest and the stale tab falls back to the report', async t => {
  let release
  const late = new Promise(resolve => { release = resolve })
  const h = dossier(t, {
    getArtifact: (id) => (id === 'pipe_A' ? late : Promise.reject(new Error('404'))),
  })
  await settle()
  h.props.pipelineId = 'pipe_B'
  await settle()
  release(datasetsResponse)
  await settle()
  assert.deepEqual(h.calls, [['pipe_A', 'datasets'], ['pipe_B', 'datasets']])
  assert.equal(h.state.datasetRows.value.length, 0, 'pipe_A rows must never show under pipe_B')

  const fresh = dossier(t)
  await settle()
  fresh.state.activeTab.value = 'data'
  fresh.props.artifactNames = []
  await settle()
  assert.equal(fresh.state.activeTab.value, 'report')
})

test('every series file control has its own accessible name (EN and ZH)', async () => {
  // Rendered markup of the real template: each row's CSV button and chart link must say
  // which series it acts on, not just 'CSV' / 'Chart' repeated down the table.
  const build = compileSfc(filename)
  const rows = datasetsResponse.data.content.series
  const base = path => path.split('/').pop()
  const artifactNames = ['datasets', ...rows.flatMap(row => [`dataset_${base(row.csv)}`, `chart_${base(row.chart)}`])]
  const render = async (locale, busyRow = -1) => {
    i18n.locale.value = locale
    const component = build({
      vue,
      '../../utils/markdown': markdown, '../../utils/researchPdfExport': researchPdfExport,
      '../../i18n': i18n,
      '../../api/research': {
        editDossier: () => { throw new Error('Unexpected API call') },
        researchChartUrl: (id, rel) => `/api/research/${id}/artifact/chart_${rel.split('/').pop()}`,
        researchPdfUrl: id => `/api/research/${id}/dossier/pdf`,
        getResearchTranslation: () => { throw new Error('Unexpected API call') },
        requestResearchTranslation: () => { throw new Error('Unexpected API call') },
        getArtifact: async () => datasetsResponse,
      },
      '../../utils/researchTranslation': researchTranslation,
      '../../utils/officialData': officialData,
      '../../utils/saveTextFile': { saveTextFile: () => {} },
    })
    const setup = component.setup
    component.setup = async (props, ctx) => {
      const state = setup(props, ctx)
      await settle()
      if (busyRow >= 0) state.csvBusy.value = state.datasetRows.value[busyRow].key
      return state
    }
    try {
      return await renderToString(vue.createSSRApp(component, {
        pipelineId: 'pipe_A',
        dossier: { has_report: true, report: '# Research\n\nBody.', sources: [] },
        editable: false,
        artifactNames,
      }))
    } finally {
      i18n.locale.value = 'en'
    }
  }
  const labels = (html, tag) => [...html.matchAll(new RegExp(`<${tag} [^>]*class="dt-file"[^>]*aria-label="([^"]*)"`, 'g'))]
    .map(match => match[1])

  const en = await render('en')
  const csv = labels(en, 'button')
  const charts = labels(en, 'a')
  assert.equal(csv.length, 8)
  assert.equal(charts.length, 8)
  assert.equal(new Set(csv).size, 8)
  assert.equal(new Set(charts).size, 8)
  assert.equal(csv[5], 'Download Unemployment Rate — USA as CSV')
  assert.equal(charts[5], 'Open the Unemployment Rate — USA chart')

  const zh = await render('zh')
  assert.equal(labels(zh, 'button')[5], '下载美国失业率 — USA CSV')
  assert.equal(labels(zh, 'a')[5], '打开美国失业率 — USA图表')

  // While its download runs, the button's name keeps the series and says so.
  const busy = labels(await render('en', 5), 'button')
  assert.equal(busy[5], 'Downloading Unemployment Rate — USA as CSV…')
  assert.equal(busy[4], csv[4])
})
