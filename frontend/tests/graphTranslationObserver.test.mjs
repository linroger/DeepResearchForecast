import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import test from 'node:test'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'
import * as i18n from '../src/i18n.js'
import * as payload from '../src/utils/graphPayload.js'
import * as style from '../src/utils/graphStyle.js'
import * as adapter from '../src/utils/translationJobAdapter.js'
import { useTranslationJob } from '../src/composables/useTranslationJob.js'
import { compileSfc } from './sfcHarness.mjs'
import { loadOverlay } from './simulationTranslationHarness.mjs'

const sha = text => createHash('sha256').update(text).digest('hex')
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
const waitFor = async predicate => { for (let i = 0; i < 200 && !predicate(); i++) await new Promise(r => setTimeout(r, 1)); assert.ok(predicate()) }
const build = compileSfc(new URL('../src/components/GraphPanel.vue', import.meta.url))
const status = compileSfc(new URL('../src/components/TranslationJobStatus.vue', import.meta.url))
const graph = (id = 'graph_A', count = 1, revision = '') => ({ graph_id: id,
  nodes: Array.from({ length: count }, (_, i) => ({ uuid: `n${i}`, name: `Node ${i}`, summary: `Summary ${revision}${i}.` })),
  edges: [{ uuid: 'self', source_node_uuid: 'n0', target_node_uuid: 'n0', fact: `Self loop ${revision}fact.` }] })
function response(data, { count = Infinity, state = 'available', continuation = false } = {}) {
  const pairs = [...data.nodes.map(n => [`node:${n.uuid}:summary`, n.summary]), ...data.edges.map(e => [`edge:${e.uuid}:fact`, e.fact])]
  const accepted = pairs.slice(0, count)
  return { data: { ref_id: data.graph_id, target_lang: 'zh', status: state, overlay: Object.fromEntries(accepted.map(([key, source]) => [key, `中文 ${source}`])),
    translations: accepted.map(([, source]) => ({ source, text: `中文 ${source}`, source_sha256: sha(source) })),
    translated: accepted.length, total_candidates: pairs.length, pending: pairs.length - accepted.length,
    continuation: { available: continuation, cursor: 'next', page_size: 216 } } }
}
function mount(t, { source = graph(), get, start, full } = {}) {
  i18n.locale.value = 'en'
  const calls = []
  const module = loadOverlay({ getGraphTranslation: async (id, lang, options) => { calls.push(['get', id]); return get ? get(id, lang, options) : response(source, { count: 0, state: 'failed' }) },
    startGraphTranslation: async (id, lang, force, options) => { calls.push(['start', id, force]); return start ? start(id, lang, force, options) : response(source) } })
  const component = build({ vue: { ...vue, onMounted: () => {}, onUnmounted: () => {} }, d3: {}, '../i18n': i18n,
    '../api/graph': { getGraphData: async () => ({ success: true, data: full || source }) }, '../utils/graphPayload': payload, '../utils/graphStyle': style,
    '../utils/overlayTranslation': module, '../composables/useTranslationJob.js': { useTranslationJob: options => useTranslationJob({ ...options, pollMs: 0 }) },
    '../utils/translationJobAdapter.js': adapter, './TranslationJobStatus.vue': { default: status({ vue }) } })
  const props = vue.reactive({ graphData: source, loading: false, currentPhase: 2, isSimulating: false, seedActors: [] })
  const scope = vue.effectScope()
  const state = scope.run(() => component.setup(props, { expose() {}, emit() {} }))
  t.after(() => scope.stop())
  const render = () => renderToString(vue.createSSRApp({ ...component, setup: () => state }, props))
  return { props, state, scope, calls, render }
}

test('actual graph control renders failed/partial status, retries normally and translates summary and self-loop', async t => {
  let tries = 0; const source = graph()
  const h = mount(t, { source, start: async () => response(source, ++tries === 1 ? { count: 0, state: 'failed' } : {}) })
  await h.state.toggleOverlayLang()
  let html = await h.render()
  assert.match(html, /Retry translation/); assert.match(html, /2 pending/)
  await h.state.overlayObserver.retry()
  h.state.selectedItem.value = { type: 'node', data: source.nodes[0] }
  html = await h.render(); assert.match(html, /中文 Summary 0\./)
  h.state.selectedItem.value = { type: 'edge', data: source.edges[0] }
  html = await h.render(); assert.match(html, /中文 Self loop fact\./)
  assert.ok(h.calls.filter(row => row[0] === 'start').every(row => row[2] === false))
})

test('late graph A request, same UUID changed prose, language switch and unmount cannot contaminate graph B', async t => {
  const old = deferred(), source = graph()
  const h = mount(t, { source, start: async () => old.promise, get: async id => response(graph(id)) })
  const request = h.state.toggleOverlayLang()
  h.props.graphData = graph('graph_B', 1, 'new ')
  await h.state.overlayObserver.observe()
  old.resolve(response(source)); await request
  assert.equal(h.state.displayText('node:n0:summary', 'Summary new 0.'), 'Summary new 0.')
  assert.equal(h.state.displayText('node:n0:summary', 'Summary 0.'), 'Summary 0.')
  h.state.toggleOverlayLang(); assert.equal(h.state.overlayLang.value, null)
  h.scope.stop(); assert.deepEqual(h.state.overlayMap.value, {})
})

test('full graph and detail inventories disclose the tail and explicit start alone advances bounded pages', async t => {
  const source = graph('graph_A', 500); let pages = 0
  const h = mount(t, { source, start: async (_id, _lang, force) => {
    assert.equal(force, false); pages++
    return response(source, { count: pages * 216, state: pages < 3 ? 'partial' : 'available', continuation: pages < 3 })
  } })
  await h.state.toggleOverlayLang()
  await waitFor(() => pages === 3 && !h.state.overlayBusy.value)
  assert.equal(h.state.overlayObserver.coverage.value.total, 501)
  assert.equal(h.state.overlayObserver.coverage.value.pending, 0)
  h.state.selectedItem.value = { type: 'node', data: source.nodes[499] }
  // A selected detail with the same source does not start another provider page.
  assert.match(await h.render(), /中文 Summary 499\./)
  assert.equal(pages, 3)
})

test('duplicate graph prose admits each field-specific reviewed rendering without permanent false partial', async t => {
  const source = graph('graph_A', 2)
  source.nodes[1].summary = source.nodes[0].summary
  const reply = response(source)
  const rows = [...source.nodes.map(n => [`node:${n.uuid}:summary`, n.summary]), ['edge:self:fact', source.edges[0].fact]]
  reply.data.translations = rows.map(([key, value], index) => ({ key, source: value, source_sha256: sha(value), text: `译法${index}` }))
  reply.data.overlay = Object.fromEntries(reply.data.translations.map(row => [row.key, row.text]))
  const h = mount(t, { source, start: async () => reply })
  await h.state.toggleOverlayLang()
  assert.equal(h.state.displayText('node:n0:summary', source.nodes[0].summary), '译法0')
  assert.equal(h.state.displayText('node:n1:summary', source.nodes[1].summary), '译法1')
  assert.equal(h.state.overlayObserver.coverage.value.pending, 0)
})
