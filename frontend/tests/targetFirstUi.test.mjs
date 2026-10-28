import assert from 'node:assert/strict'
import test from 'node:test'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'
import * as i18n from '../src/i18n.js'
import * as liveProgress from '../src/utils/liveProgress.js'
import { compileSfc } from './sfcHarness.mjs'

const buildTarget = compileSfc(new URL('../src/components/research/TargetSimulationView.vue', import.meta.url))
const buildResearch = compileSfc(new URL('../src/views/ResearchView.vue', import.meta.url))
const settle = () => new Promise(resolve => setImmediate(resolve))
const text = html => html.replace(/<!--[^]*?-->/g, '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ')
const pending = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }

function payload(simulationId = 'sim_A', pipelineId = 'pipe_A') {
  return { success: true, data: {
    simulationId, pipelineId, forecastAuthority: 'target-first-v1', caseId: 'case_A', caseHash: 'a'.repeat(64),
    resolution: { targetNodeId: 'target', units: 'USD', horizon: '2027-12-31', settlementSource: { name: 'Synthetic source' } },
    nodes: [{ nodeId: 'target', label: 'Target spending', status: 'settled' }, { nodeId: 'growth', label: 'Unknown growth', status: 'unknown', basis: 'assumed', gap: 'No observed elasticity', range: { low: 0, high: 0.1 } }],
    mechanisms: [{ mechanismId: 'growth-edge', basis: 'assumed', gap: '<script>untrusted gap</script>' }],
    simulation: { schemaVersion: 'target-simulation/v1', caseId: 'case_A', caseHash: 'a'.repeat(64), simulationWeight: 0,
      paths: [{ pathId: 'path_0', targetValue: 0, parameters: { rate: 0 }, decisions: [], trajectory: [{ period: 0, values: { target: 5 } }, { period: 1, values: { target: 0 } }] },
        { pathId: 'path_1', targetValue: 10, parameters: { rate: 0.1 }, decisions: [], trajectory: [{ period: 0, values: { target: 5 } }, { period: 1, values: { target: 10 } }] }],
      targetSummary: { min: 0, max: 10 }, scenarioShares: { low: 0.5, high: 0.5 }, sensitivity: [{ nodeId: 'growth', effect: 10 }], signposts: [{ label: 'Observe demand' }] },
  } }
}

function mountedHarness(t, build, imports, props = {}) {
  i18n.locale.value = 'en'
  const cleanups = [], scope = vue.effectScope()
  const component = build({ ...imports, vue: { ...vue, ...imports.vue, onMounted() {}, onUnmounted: fn => cleanups.push(fn) } })
  const reactiveProps = vue.reactive(props)
  const state = scope.run(() => component.setup(reactiveProps, { expose() {} }))
  let disposed = false
  const dispose = () => { if (!disposed) { cleanups.forEach(fn => fn()); scope.stop(); disposed = true } }
  t.after(() => { dispose(); i18n.locale.value = 'en' })
  return { state, props: reactiveProps, dispose,
    render: () => renderToString(vue.createSSRApp({ ...component, setup: () => state }, reactiveProps)) }
}

function targetHarness(t, service = async request => payload(request.url.split('/')[3], request.params.pipeline_id), extra = {}) {
  const calls = []
  const h = mountedHarness(t, buildTarget, {
    '../../api/index': { default: request => { calls.push(request); return service(request) } }, '../../i18n': i18n,
  }, { pipelineId: 'pipe_A', simulationId: 'sim_A', stageStatus: 'completed', ...extra })
  return { ...h, calls }
}

function researchHarness(t, options = {}) {
  const calls = [], timers = new Map()
  let clockId = 0
  t.mock.method(globalThis, 'setTimeout', fn => { timers.set(++clockId, fn); return clockId })
  t.mock.method(globalThis, 'clearTimeout', id => timers.delete(id))
  const oldDocument = globalThis.document
  globalThis.document = { hidden: false, addEventListener() {}, removeEventListener() {} }
  t.after(() => { if (oldDocument === undefined) delete globalThis.document; else globalThis.document = oldDocument })
  const imports = {
    '../api/research': {
      getPreflight: async (mode, params) => { calls.push({ kind: 'preflight', mode, params }); return options.preflight?.(mode, params) || { success: true, data: { mode, simulation_engine: params.simulation_engine || 'oasis-legacy', ready: true, errors: [] } } },
      runPipeline: async data => { calls.push({ kind: 'run', data }); return { success: true, data: { pipeline_id: 'pipe_started' } } },
      getPipelineStatus: async id => ({ success: true, data: { status: 'running', mode: 'full', options: options.savedOptions || {}, simulation_id: 'sim_saved', report_id: 'report_normal', stages: {} } }),
      getProgressLog: async () => ({ data: { scope: 'full', total_exact: true, truncated: false, lines: [] } }),
      getDossier: async () => ({ data: {} }), cancelPipeline() {}, resumePipeline() {}, continuePipeline() {},
    },
    '../api/graph': { getGraphData: options.graph || (async () => ({ data: { nodes: [], edges: [] } })) },
    '../i18n': i18n, '../utils/liveProgress': liveProgress,
    '../components/GraphPanel.vue': { default: { render: () => null } },
  }
  for (const name of ['StageTimeline', 'RunVitals', 'ResearchConsole', 'DossierViewer', 'SimulationView', 'TargetSimulationView', 'ForecastReport', 'PipelineHistory', 'SettingsMenu', 'ConfirmDialog']) {
    imports[`../components/research/${name}.vue`] = { default: { name, props: ['simulationId', 'reportId', 'pipelineId'], render() { return vue.h('div', { 'data-child': name }, this.reportId || this.simulationId || '') } } }
  }
  imports.vue = { defineAsyncComponent: () => imports['../components/research/TargetSimulationView.vue'].default }
  const h = mountedHarness(t, buildResearch, imports)
  h.state.prompt.value = 'Forecast a synthetic target'
  return { ...h, calls, timers }
}

test('target panel renders distributions, selected trajectory, zero, unknowns and bilingual caveats', async t => {
  const h = targetHarness(t)
  await settle()
  const en = await h.render()
  assert.equal(h.calls[0].url, '/api/simulation/sim_A/target')
  assert.deepEqual(h.calls[0].params, { pipeline_id: 'pipe_A' })
  assert.match(text(en), /Forecast weight: 0/)
  assert.match(text(en), /Minimum 0 Median 5 Maximum 10/)
  assert.match(text(en), /Unknown growth.*No observed elasticity.*Assumed range: 0 – 0.1/)
  assert.match(en, /&lt;script&gt;untrusted gap&lt;\/script&gt;/)
  assert.doesNotMatch(en, /<script>/)
  h.state.selectedPathId.value = 'path_1'
  assert.match(text(await h.render()), /Target trajectory.*1 10 USD/)
  i18n.locale.value = 'zh'
  assert.match(text(await h.render()), /预测权重：0.*未解决假设/)
})

test('target response identity and nonzero weight fail closed', async t => {
  for (const mutate of [data => { data.pipelineId = 'pipe_B' }, data => { data.simulation.caseHash = 'bad' }, data => { data.simulation.simulationWeight = 0.5 }, data => { data.simulation.paths[0].targetValue = null }]) {
    const h = targetHarness(t, async () => { const response = payload(); mutate(response.data); return response })
    await settle()
    assert.equal(h.state.result.value, null)
    assert.match(text(await h.render()), /failed identity or data validation/)
  }
})

test('parameter-level gaps remain visible for observed mechanisms and exhausted decisions are qualified', async t => {
  const h = targetHarness(t, async () => {
    const response = payload()
    response.data.nodes = [response.data.nodes[0]]
    response.data.mechanisms = [{ mechanismId: 'linear', basis: 'observed' }]
    response.data.simulation.parameterBases = [{ mechanismId: 'linear', parameter: 'coefficient', basis: 'assumed', low: 0.1, high: 0.9, gap: 'Coefficient has no measured support' }]
    response.data.simulation.decisionBudget = { maximumRequests: 128, requests: 128, cacheHits: 3, exhausted: true }
    return response
  })
  await settle()
  assert.match(text(await h.render()), /Decision requests: 128 \/ 128.*Cache hits: 3.*Decision budget exhausted/)
  assert.match(text(await h.render()), /linear.coefficient.*Coefficient has no measured support.*0.1 – 0.9/)
  i18n.locale.value = 'zh'
  assert.match(text(await h.render()), /决策预算已耗尽.*未解决假设.*Coefficient has no measured support/)
})

test('target switching and disposal discard stale responses and stale errors', async t => {
  const requests = []
  const h = targetHarness(t, () => { const request = pending(); requests.push(request); return request.promise })
  h.props.simulationId = 'sim_B'
  assert.equal(h.state.result.value, null)
  requests[1].resolve(payload('sim_B'))
  await settle()
  requests[0].reject(new Error('stale error'))
  await settle()
  assert.equal(h.state.result.value.simulationId, 'sim_B')
  assert.equal(h.state.error.value, '')
  h.props.simulationId = 'sim_C'
  h.dispose()
  requests[2].resolve(payload('sim_C'))
  await settle()
  assert.equal(h.state.result.value, null)
})

test('target pending artifacts show retryable state; stage completion retries; malformed IDs never request', async t => {
  let ready = false
  const h = targetHarness(t, async () => { if (!ready) throw { response: { status: 404 } }; return payload() }, { stageStatus: 'running' })
  await settle()
  assert.match(text(await h.render()), /not available yet/)
  ready = true
  h.props.stageStatus = 'completed'
  await settle()
  assert.ok(h.state.result.value)
  h.props.simulationId = '../sim_secret'
  assert.equal(h.calls.length, 2)
  assert.match(text(await h.render()), /Invalid pipeline/)
})

test('forecast selector defaults remain legacy; explicit target sends only the target launch contract', async t => {
  const legacy = researchHarness(t)
  await legacy.state.checkPreflight()
  assert.equal(legacy.state.forecastAuthority.value, '')
  assert.match(await legacy.render(), /value="target-first-v1"/)
  await legacy.state.start()
  assert.equal(legacy.calls.find(c => c.kind === 'run').data.forecast_authority, undefined)
  legacy.dispose()
  const target = researchHarness(t)
  target.state.simulationEngine.value = 'world-v1'
  target.state.forecastAuthority.value = 'target-first-v1'
  await settle()
  assert.deepEqual(target.calls.at(-1).params, { simulation_engine: 'target-first-v1' })
  assert.equal(target.state.showRoundCap.value, false)
  assert.doesNotMatch(await target.render(), /id="simulation-engine"|id="max-rounds"/)
  target.state.targetSeed.value = 7
  await target.state.start()
  const data = target.calls.find(c => c.kind === 'run').data
  assert.equal(data.forecast_authority, 'target-first-v1')
  assert.deepEqual(data.target_simulation, { paths: 32, periods: 12, seed: 7 })
  assert.equal(data.simulation_engine, undefined)
  assert.equal(data.world_spec, undefined)
  assert.equal(data.max_rounds, undefined)
})

test('target invalid settings and mismatched preflight prevent launch', async t => {
  const h = researchHarness(t)
  h.state.forecastAuthority.value = 'target-first-v1'
  await settle()
  for (const [key, value] of [['targetPaths', 0], ['targetPaths', 257], ['targetPeriods', 1.5], ['targetSeed', -1]]) {
    const before = h.state[key].value
    h.state[key].value = value
    await h.state.start()
    assert.equal(h.calls.filter(c => c.kind === 'run').length, 0)
    h.state[key].value = before
  }
  h.dispose()
  const bad = researchHarness(t, { preflight: async mode => ({ success: true, data: { mode, ready: true, errors: [], simulation_engine: 'oasis-legacy' } }) })
  bad.state.forecastAuthority.value = 'target-first-v1'
  await settle()
  assert.equal(bad.state.canStart.value, false)
  assert.equal(bad.state.preflightFailed.value, true)
})

test('saved authority controls renderer and preserves ordinary report ID regardless of selector', async t => {
  const h = researchHarness(t, { savedOptions: { forecast_authority: 'target-first-v1' } })
  h.state.beginPipeline('pipe_saved')
  await h.state.poll(h.state.pollGeneration)
  const html = await h.render()
  assert.equal(h.state.isTargetForecast.value, true)
  assert.match(html, /data-child="TargetSimulationView"/)
  assert.doesNotMatch(html, /data-child="SimulationView"/)
  assert.match(html, /data-child="ForecastReport"[^>]*>report_normal/)
  h.state.resetState()
  assert.equal(h.state.isTargetForecast.value, false)
  assert.equal(h.state.simulationId.value, '')
})

test('late target graph response never replaces another pipeline graph', async t => {
  const request = pending()
  const h = researchHarness(t, { graph: () => request.promise })
  h.state.pipelineId.value = 'pipe_A'
  h.state.graphId.value = 'target_graph_pipe_A'
  const reading = h.state.fetchGraph()
  h.state.resetState()
  h.state.pipelineId.value = 'pipe_B'
  h.state.graphId.value = 'target_graph_pipe_B'
  request.resolve({ data: { nodes: [{ uuid: 'stale' }], edges: [] } })
  await reading
  assert.equal(h.state.graphData.value, null)
})
