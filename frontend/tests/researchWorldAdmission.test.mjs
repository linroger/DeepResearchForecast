import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'
import * as i18n from '../src/i18n.js'
import * as liveProgress from '../src/utils/liveProgress.js'
import { compileSfc } from './sfcHarness.mjs'

// Exercise the real API adapter and SFC setup/template. Only transport, child
// components, lifecycle scheduling, storage, and polling timers are substituted.
const buildView = compileSfc(new URL('../src/views/ResearchView.vue', import.meta.url))
const apiSource = readFileSync(new URL('../src/api/research.js', import.meta.url), 'utf8')
const buildApi = new Function('service', 'apiUrl', apiSource
  .replace("import service, { apiUrl } from './index'", '')
  .replace(/^export function /gm, 'function ') + `
  return { getPreflight, runPipeline, cancelPipeline, resumePipeline,
    getPipelineStatus, getProgressLog, getDossier, continuePipeline };
`)
const settle = () => new Promise(resolve => setImmediate(resolve))
const text = html => html.replace(/<!--[^]*?-->/g, '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ')
const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const response = (mode = 'full', engine = 'oasis-legacy', extra = {}) => ({ success: true, data: {
  mode, ready: true, errors: [], simulation_engine: engine,
  default_simulation_engine: 'oasis-legacy', simulation_admission: {}, ...extra,
} })

function replaceGlobal(key, value) {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, key)
  Object.defineProperty(globalThis, key, { value, configurable: true, writable: true })
  return () => {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor)
    else delete globalThis[key]
  }
}

function findNode(node, predicate) {
  if (!node || typeof node !== 'object') return null
  if (predicate(node)) return node
  for (const child of Array.isArray(node.children) ? node.children : []) {
    const found = findNode(child, predicate)
    if (found) return found
  }
  return null
}

function harness(t, { mount = true, saved = '', lang = 'en' } = {}) {
  i18n.locale.value = lang
  const storage = new Map(saved ? [['drf_active_pipeline', saved]] : [])
  const restoreStorage = replaceGlobal('localStorage', {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key),
  })
  const restoreDocument = replaceGlobal('document', { addEventListener() {}, removeEventListener() {} })
  const timers = new Map()
  let timerId = 0
  t.mock.method(globalThis, 'setTimeout', callback => { timers.set(++timerId, callback); return timerId })
  t.mock.method(globalThis, 'clearTimeout', id => timers.delete(id))
  const preflights = [], launches = [], mounted = [], cleanups = []
  const unexpected = () => { throw new Error('Unexpected API call') }
  const api = buildApi(request => {
    if (request.url === '/api/research/preflight' && request.method === 'get') {
      const pending = { ...deferred(), params: request.params }
      preflights.push(pending)
      return pending.promise
    }
    if (request.url === '/api/research/run' && request.method === 'post') {
      launches.push(request.data)
      return Promise.resolve({ success: true, data: { pipeline_id: 'pipe_new' } })
    }
    return unexpected()
  }, value => value)
  const imports = {
    vue: { ...vue, onMounted: fn => mounted.push(fn), onUnmounted: fn => cleanups.push(fn) },
    '../api/research': api, '../api/graph': { getGraphData: unexpected },
    '../i18n': i18n, '../utils/liveProgress': liveProgress,
  }
  for (const name of ['StageTimeline', 'RunVitals', 'ResearchConsole', 'DossierViewer',
    'SimulationView', 'ForecastReport', 'PipelineHistory', 'SettingsMenu', 'ConfirmDialog']) {
    imports[`../components/research/${name}.vue`] = { default: { name, render: () => null } }
  }
  imports['../components/GraphPanel.vue'] = { default: { render: () => null } }
  const component = buildView(imports)
  const scope = vue.effectScope()
  const state = scope.run(() => component.setup({}, { expose() {} }))
  state.prompt.value = '  Forecast a hypothetical market  '
  let disposed = false, tree
  const dispose = () => {
    if (disposed) return
    cleanups.forEach(fn => fn())
    scope.stop()
    disposed = true
  }
  t.after(() => {
    try { dispose() }
    finally { restoreDocument(); restoreStorage(); i18n.locale.value = 'en' }
  })
  const render = () => renderToString(vue.createSSRApp({
    ...component, setup: () => state,
    render(...args) { tree = component.render.apply(this, args); return tree },
  }))
  if (mount) mounted.forEach(fn => fn())
  return {
    state, preflights, launches, render, dispose, timers, storage,
    node: predicate => findNode(tree, predicate),
    async accept(index = preflights.length - 1, engine, extra = {}) {
      const pending = preflights[index]
      pending.resolve(response(pending.params.mode, engine || pending.params.simulation_engine || 'oasis-legacy', extra))
      await settle()
    },
  }
}

test('API keeps no-argument and mode-only callers compatible and allows only model/engine options', async () => {
  const calls = []
  const api = buildApi(request => { calls.push(request); return Promise.resolve(response()) }, value => value)
  await api.getPreflight()
  await api.getPreflight('research_only')
  await api.getPreflight('full', { model: 'codex', simulation_engine: 'world-v1', max_rounds: 4 })
  await api.getPreflight('full', { model: '', simulation_engine: '' })
  assert.deepEqual(calls.map(call => call.params), [
    { mode: 'full' }, { mode: 'research_only' },
    { mode: 'full', model: 'codex', simulation_engine: 'world-v1' }, { mode: 'full' },
  ])
  assert.ok(calls.every(call => call.url === '/api/research/preflight' && call.method === 'get'))
})

test('initial and pending readiness block actual launch; template offers all engines in both languages', async t => {
  const h = harness(t, { mount: false })
  assert.equal(h.state.canStart.value, false)
  await h.state.start()
  assert.equal(h.launches.length, 0)
  const checking = h.state.checkPreflight()
  const en = await h.render()
  assert.match(en, /<button[^>]*class="start-engine-btn"[^>]*disabled/)
  assert.match(text(en), /Checking launch configuration/)
  assert.doesNotMatch(text(en), /Configuration ready|OASIS/)
  // SSR may serialize the empty default value as either `value` or `value=""`.
  assert.match(en, /<option value(?:="")?(?=[\s>])[^>]*>Server default<\/option>/)
  assert.match(en, /<option value="world-v1"[^>]*>World simulation<\/option>/)
  assert.match(en, /<option value="oasis-legacy"[^>]*>Social simulation \(legacy\)<\/option>/)
  assert.doesNotMatch(en, /id="max-rounds"/)
  i18n.locale.value = 'zh'
  const zhHtml = await h.render()
  assert.match(zhHtml, /<option value(?:="")?(?=[\s>])[^>]*>服务器默认<\/option>/)
  const zh = text(zhHtml)
  assert.match(zh, /服务器默认 世界模拟 社交模拟（传统）/)
  assert.match(zh, /正在检查启动配置/)
  assert.doesNotMatch(zh, /OASIS/)
  await h.accept()
  await checking
  assert.equal(h.state.canStart.value, true)
})

test('failed fetch clears prior readiness; the rendered retry button performs a fresh check', async t => {
  const h = harness(t)
  await h.accept()
  h.state.onProviderChanged()
  assert.equal(h.state.canStart.value, false)
  h.preflights[1].reject(new Error('Network Error'))
  await settle()
  assert.equal(h.state.effectiveSimulationEngine.value, '')
  assert.equal(h.state.preflightFailed.value, true)
  let html = await h.render()
  assert.match(text(html), /Unable to confirm launch configuration\. Retry the check\./)
  assert.doesNotMatch(html, /Configuration ready/)
  await h.state.start()
  assert.equal(h.launches.length, 0)
  i18n.locale.value = 'zh'
  assert.match(text(await h.render()), /无法确认启动配置，请重试检查。.*重试检查/)
  i18n.locale.value = 'en'
  const retry = h.node(node => typeof node.props?.class === 'string' && node.props.class.includes('preflight-retry'))
  assert.ok(retry, 'retry must be wired in the actual template')
  const retrying = retry.props.onClick()
  assert.equal(h.preflights.length, 3)
  assert.equal(h.state.preflightLoading.value, true)
  await h.accept()
  await retrying
  html = await h.render()
  assert.match(text(html), /Configuration ready/)
  assert.equal(h.state.canStart.value, true)
})

test('mode, model, engine and the actual provider event each recheck with current request parameters', async t => {
  const h = harness(t)
  await h.accept()
  h.state.mode.value = 'research_only'
  assert.equal(h.state.canStart.value, false)
  h.state.researchModel.value = 'codex'
  h.state.simulationEngine.value = 'world-v1'
  h.state.showSettings.value = true
  await h.render()
  const settings = h.node(node => node.type?.name === 'SettingsMenu')
  assert.ok(settings)
  settings.props.onChanged({ current: 'provider_B' })
  assert.deepEqual(h.preflights.map(item => item.params), [
    { mode: 'full' }, { mode: 'research_only' },
    { mode: 'research_only', model: 'codex' },
    { mode: 'research_only', model: 'codex', simulation_engine: 'world-v1' },
    { mode: 'research_only', model: 'codex', simulation_engine: 'world-v1' },
  ])
  await h.accept()
  assert.equal(h.state.canStart.value, true)
})

for (const field of ['mode', 'researchModel', 'simulationEngine', 'provider']) {
  for (const outcome of ['success', 'reject']) {
    test(`${field} same-tick A→B→A rejects stale ${outcome} and cannot clear the latest loading state`, async t => {
      const h = harness(t)
      if (field === 'provider') {
        h.state.onProviderChanged({ current: 'provider_B' })
        h.state.onProviderChanged({ current: 'provider_A' })
      } else {
        const a = h.state[field].value
        h.state[field].value = { mode: 'research_only', researchModel: 'codex', simulationEngine: 'world-v1' }[field]
        h.state[field].value = a
      }
      assert.equal(h.preflights.length, 3, 'same-tick changes must not collapse into one request')
      if (outcome === 'success') h.preflights[0].resolve(response('full', 'oasis-legacy'))
      else h.preflights[0].reject(new Error('obsolete A'))
      await settle()
      assert.equal(h.state.preflightLoading.value, true)
      assert.equal(h.state.preflightChecked.value, false)
      assert.equal(h.state.preflightFailed.value, false)
      assert.equal(h.state.effectiveSimulationEngine.value, '')
      assert.equal(h.state.canStart.value, false)
      // Server default is deliberately world on latest A, distinct from old A.
      await h.accept(2, 'world-v1')
      h.preflights[1].resolve({ success: false, data: { ready: false, errors: ['obsolete B'] } })
      await settle()
      assert.equal(h.state.effectiveSimulationEngine.value, 'world-v1')
      assert.equal(h.state.preflightReady.value, true)
      assert.equal(h.state.preflightLoading.value, false)
      assert.equal(h.state.preflightFailed.value, false)
      assert.deepEqual(h.state.preflightErrors.value, [])
    })
  }
}

for (const [name, payload] of [
  ['missing effective engine', { success: true, data: { mode: 'full', ready: true, errors: [] } }],
  ['unknown effective engine', response('full', 'future-engine')],
  ['wrong mode', response('research_only')],
  ['failed envelope', { ...response(), success: false }],
  ['non-boolean readiness', response('full', 'oasis-legacy', { ready: 'true' })],
  ['malformed errors', response('full', 'oasis-legacy', { errors: null })],
]) {
  test(`${name} is unknown and blocked rather than configuration-ready`, async t => {
    const h = harness(t)
    h.preflights[0].resolve(payload)
    await settle()
    assert.equal(h.state.canStart.value, false)
    assert.equal(h.state.preflightFailed.value, true)
    assert.equal(h.state.effectiveSimulationEngine.value, '')
    assert.doesNotMatch(await h.render(), /Configuration ready/)
    await h.state.start()
    assert.equal(h.launches.length, 0)
  })
}

test('server refusal remains blocked with escaped actionable errors, and explicit engine mismatch is rejected', async t => {
  const h = harness(t)
  h.state.simulationEngine.value = 'world-v1'
  await h.accept(1, 'world-v1', { ready: false, errors: ['Configure the world profile <operator>'] })
  assert.equal(h.state.canStart.value, false)
  assert.equal(h.state.preflightFailed.value, false)
  const html = await h.render()
  assert.match(html, /Configure the world profile &lt;operator&gt;/)
  assert.match(text(html), /Not ready to launch.*Retry check/)
  h.state.checkPreflight()
  await h.accept(2, 'oasis-legacy')
  assert.equal(h.state.preflightFailed.value, true)
  assert.equal(h.state.canStart.value, false)
  assert.equal(h.state.effectiveSimulationEngine.value, '')
})

for (const selection of ['', 'world-v1', 'oasis-legacy']) {
  for (const mode of ['full', 'research_only']) {
    const engines = selection ? [selection] : ['oasis-legacy', 'world-v1']
    for (const engine of engines) {
      test(`${mode}: ${selection || 'server default'} resolving to ${engine} controls rendered rounds and the actual POST`, async t => {
        const h = harness(t)
        h.state.mode.value = mode
        h.state.simulationEngine.value = selection
        h.state.maxRounds.value = 7
        h.state.researchModel.value = 'codex'
        h.state.researchLanguage.value = 'English'
        await h.accept(undefined, engine)
        const legacyFull = mode === 'full' && engine === 'oasis-legacy'
        const html = await h.render()
        assert.equal(html.includes('id="max-rounds"'), legacyFull)
        assert.match(text(html), engine === 'world-v1'
          ? /Engine confirmed by preflight: World simulation/
          : /Engine confirmed by preflight: Social simulation \(legacy\)/)
        if (mode === 'research_only') assert.match(text(html), /Research-only mode does not run a simulation/)
        await h.state.start()
        assert.equal(h.launches.length, 1)
        const expected = { prompt: 'Forecast a hypothetical market', mode, depth: 'deep', language: 'English', model: 'codex' }
        if (selection) expected.simulation_engine = selection
        if (legacyFull) expected.max_rounds = 7
        assert.deepEqual(h.launches[0], expected)
        assert.equal(h.state.pipelineId.value, 'pipe_new')
        assert.equal(h.storage.get('drf_active_pipeline'), 'pipe_new')
        assert.equal(h.state.canStart.value, false)
      })
    }
  }
}

test('legacy round value survives a world selection but is hidden until fresh legacy readiness returns', async t => {
  const h = harness(t)
  h.state.maxRounds.value = 9
  await h.accept()
  assert.match(await h.render(), /id="max-rounds"/)
  h.state.simulationEngine.value = 'world-v1'
  assert.doesNotMatch(await h.render(), /id="max-rounds"/)
  await h.accept()
  assert.equal(h.state.maxRounds.value, 9)
  h.state.simulationEngine.value = 'oasis-legacy'
  assert.equal(h.state.showRoundCap.value, false)
  await h.accept()
  assert.match(await h.render(), /id="max-rounds"[^>]*value="9"/)
  await h.state.start()
  assert.equal(h.launches[0].max_rounds, 9)
})

test('restoring a saved run skips fresh admission; New requests readiness and old responses cannot cross run boundaries', async t => {
  const h = harness(t, { saved: 'pipe_saved' })
  assert.equal(h.state.pipelineId.value, 'pipe_saved')
  assert.equal(h.preflights.length, 0)
  h.state.onProviderChanged()
  assert.equal(h.preflights.length, 0)
  h.state.reset()
  assert.equal(h.preflights.length, 1)
  assert.equal(h.state.canStart.value, false)
  h.state.selectPipeline('pipe_other')
  h.preflights[0].resolve(response())
  await settle()
  assert.equal(h.state.preflightReady.value, false)
  assert.equal(h.state.effectiveSimulationEngine.value, '')
  h.state.reset()
  assert.equal(h.preflights.length, 2)
  await h.accept()
  assert.equal(h.state.canStart.value, true)
})

test('unmount invalidates an outstanding preflight and late completion cannot restore readiness', async t => {
  const h = harness(t)
  h.dispose()
  h.preflights[0].resolve(response())
  await settle()
  assert.equal(h.state.preflightReady.value, false)
  assert.equal(h.state.preflightLoading.value, false)
  assert.equal(h.state.preflightChecked.value, false)
  assert.equal(h.state.effectiveSimulationEngine.value, '')
})
