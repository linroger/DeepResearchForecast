import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'
import * as i18n from '../src/i18n.js'
import * as world from '../src/utils/worldSimulationView.js'
import * as feedRounds from '../src/utils/feedRounds.js'
import * as simRecord from '../src/utils/simRecord.js'
import { compileSfc } from './sfcHarness.mjs'

const worldFile = new URL('../src/components/research/WorldSimulationView.vue', import.meta.url)
const parentFile = new URL('../src/components/research/SimulationView.vue', import.meta.url)
const buildWorld = compileSfc(worldFile)
const buildParent = compileSfc(parentFile)
const settle = async () => { for (let i = 0; i < 4; i++) await new Promise(resolve => setImmediate(resolve)) }
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
const PUBLIC = { kind: 'public' }
const PRIVATE = { kind: 'actors', actorIds: ['actor_A'] }
const basis = { kind: 'scenario_assumption', refs: ['assumption_1'] }
const record = (value, extra = {}) => ({ value, visibility: PUBLIC, basis, ...extra })

// Synthetic contract fixture follows results.read_result (world-result/v1).
// Distinct metadata/head/selected revisions catch accidental view or history mixing.
function payload(id = 'sim_A', options = {}) {
  const view = options.view || 'public'
  const actorId = view === 'actor' ? (options.actorId || 'actor_A') : null
  const round = options.round ?? 2
  return { success: true, data: {
    schemaVersion: 'world-result/v1', engine: 'world-v1', simulationId: id,
    generationId: options.generationId || `gen_${id}`, revision: options.revision || 'head-2', selectedRevision: `round-${round}`,
    forecastEffect: 'diagnostic_only', round, committedRound: 2, totalRounds: 4, completed: false,
    view, actorId, valueStatus: 'simulated', asOf: '2026-01-01T00:00:00Z', horizon: '2027-01-01T00:00:00Z',
    world: { round, simulatedAt: '2026-07-01T00:00:00Z',
      metrics: { capacity: record('12345678901234567890.123456789', { unit: 'MW', valueStatus: 'specified' }),
        missing: record(null, { unit: 'MW', valueStatus: 'unknown' }), zero: record('0', { unit: 'USD' }) },
      accounts: { cash: record(undefined, { balance: '20.25', reserved: '4.5', unit: 'USD', ownerId: 'actor_A' }) },
      rules: { permit: record(false) }, relations: { coalition: record('allied') },
      commitments: { c1: record(undefined, { templateId: 'invest', sourceIntentId: 'i1', actorId: 'actor_A', status: 'pending', participantIds: ['actor_A'], dueAt: '2026-09-01T00:00:00Z', transfers: [], effects: [{ kind: 'metric_delta', parameters: { targetMetric: 'capacity', delta: '3' } }] }) },
      interactions: { offer1: record(undefined, { templateId: 'agreement', proposerId: 'actor_A', recipientIds: ['actor_B'], status: 'pending', termsVersion: 2, terms: { quantity: '3' }, deliverAt: '2026-07-01T00:00:00Z', expiresAt: '2026-08-01T00:00:00Z' }) },
      ...(view === 'analyst' ? { actorStates: { actor_A: { beliefs: ['private belief A'], plans: ['private plan A'], priorityChanges: [], observedEvents: ['e1'] }, actor_B: { beliefs: ['private belief B'] } } } : {}),
      ...(view === 'actor' ? { actorState: { beliefs: ['private belief A'], plans: ['private plan A'] } } : {}),
    },
    // Trajectory is intentionally inconsistent so tests prove selected world is used.
    trajectory: [{ metrics: { capacity: record('WRONG HISTORY') } }],
    decisions: view === 'public' ? [] : [{ decisionId: 'd1', observationId: 'o1', actorId: 'actor_A', round: 1,
      phase: 'proposal', rationale: '<img src=x onerror=alert(1)>', status: 'acted',
      intents: [{ intentId: 'i1', actorId: 'actor_A', templateId: 'invest', operation: 'execute', parameters: { cost: '4.5' }, interactionId: 'offer1' }] }],
    resolutions: view === 'public' ? [] : [{ intentId: 'i1', actorId: 'actor_A', round: 1, accepted: false, code: 'resources', explanation: 'Not enough resources' }],
    events: [{ ...record(undefined), eventId: 'e1', sourceIntentId: 'i1', actorId: 'actor_A', round: 1, at: '2026-04-01T00:00:00Z', kind: 'investment', description: 'Investment commitment', details: { commitmentId: 'c1' } }],
    assumptions: [{ assumptionId: 'assumption_1', description: 'Demand remains constant.', visibility: PUBLIC }],
  } }
}

function harness(t, { parent = false, api = {}, id = 'sim_A', generationId = '', lang = 'en' } = {}) {
  i18n.locale.value = lang
  const cleanups = []
  const calls = []
  const defaults = {
    getWorldSimulation: async (id, request) => payload(id, request),
    getSimulation: async id => ({ success: true, data: { simulation_id: id, simulation_engine: 'world-v1' } }),
    getSimulationProfilesRealtime: async () => ({ success: true, data: { profiles: [{ user_id: 1, name: 'Alice' }] } }),
    getSimulationPosts: async () => ({ success: true, data: { posts: [{ post_id: 1, user_id: 1, content: 'Legacy social post' }] } }),
    getSimulationComments: async () => ({ success: true, data: { comments: [] } }),
    getAgentStats: async () => ({ success: true, data: { total_posts: 1 } }),
    getRunStatus: async () => ({ success: true, data: { simulation_engine: 'oasis-legacy', runner_status: 'completed', current_round: 2, total_rounds: 2 } }),
    getFeedRounds: async () => ({ success: true, data: { rounds: [] } }),
    // ADR 0003: no gate-passed after-action record exists for these runs (today's layout)
    fetchRecord: async () => ({ record: null, status: 404, publicationStatus: 'absent' }),
  }
  const actual = Object.fromEntries(Object.entries({ ...defaults, ...api }).map(([key, fn]) => [key, (...args) => { calls.push({ key, args }); return fn(...args) }]))
  const imports = {
    vue: { ...vue, onUnmounted: fn => cleanups.push(fn), useId: () => 'world-test' },
    '../../i18n': i18n, '../../api/simulation': actual, '../../utils/worldSimulationView': world,
    './WorldSimulationView.vue': { default: { props: ['simulationId', 'generationId'], template: '<div class="world-child" />' } },
    // the OASIS view's reflexive-world panel and per-period feed helpers (combined simulation tab)
    './WorldStatePanel.vue': { default: { props: ['simulationId', 'refreshToken', 'round'], emits: ['update:selectedRound'], template: '<div class="world-state-panel" />' } },
    '../../utils/feedRounds': feedRounds,
    // ADR 0003: the after-action record view (exercised in simulationRecordView.test.mjs)
    './SimulationRecordView.vue': { default: { props: ['record'], template: '<div class="sim-record-view" />' } },
    '../../utils/simRecord': simRecord,
  }
  const component = (parent ? buildParent : buildWorld)(imports)
  const props = vue.reactive({ simulationId: id, generationId })
  const scope = vue.effectScope()
  const state = scope.run(() => component.setup(props, { expose() {} }))
  let disposed = false
  const dispose = () => { if (!disposed) { cleanups.forEach(fn => fn()); scope.stop(); disposed = true } }
  t.after(() => { dispose(); i18n.locale.value = 'en' })
  const render = async () => {
    // Same real compiled template, with this tested reactive setup state.
    const rendered = { ...component, setup: () => state }
    return renderToString(vue.createSSRApp(rendered, props))
  }
  return { state, props, calls, render, dispose }
}
const request = (extra = {}) => ({ simulationId: 'sim_A', view: 'public', ...extra })
const body = html => html.replace(/<!--[^]*?-->/g, '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ')

test('world projection preserves decimals, zero, false, unknowns and the selected snapshot', () => {
  const response = payload()
  const data = world.readWorldResponse(response, request())
  const p = world.projectWorldResult(data)
  assert.equal(p.sections.metrics[0].value, '12345678901234567890.123456789')
  assert.equal(p.sections.metrics[1].value, null)
  assert.equal(world.worldValue(p.sections.metrics[2].value), '0')
  assert.equal(world.worldValue(p.sections.rules[0].value), 'false')
  assert.equal(world.worldValue(null), 'Unknown')
  assert.deepEqual(p.decisions, [])
  assert.deepEqual(p.privateStates, [])
  assert.equal(p.commitments[0].status, 'pending')
  assert.equal(p.interactions[0].termsVersion, 2)
})

test('public and actor projections do not expose extra private records or other actors decisions', () => {
  const data = payload('sim_A', { view: 'analyst' }).data
  data.world.metrics.secret = record('SECRET', { visibility: PRIVATE })
  data.world.actorState = { beliefs: ['actor-local'] }
  data.decisions.push({ decisionId: 'other', actorId: 'actor_B', intents: [] })
  data.view = 'public'
  assert.deepEqual(world.projectWorldResult(data).privateStates, [])
  assert.deepEqual(world.projectWorldResult(data).decisions, [])
  assert.ok(!world.projectWorldResult(data).sections.metrics.some(row => row.id === 'secret'))
  data.view = 'actor'; data.actorId = 'actor_A'
  const actor = world.projectWorldResult(data)
  assert.equal(actor.decisions.length, 1)
  assert.equal(actor.privateStates.length, 1)
  assert.deepEqual(actor.privateStates[0].beliefs, ['actor-local'])
  assert.equal(actor.decisions[0].intents[0].resolution.accepted, false)
  assert.equal(actor.decisions[0].intents[0].events[0].eventId, 'e1')
})

test('response reader rejects mismatched run, generation, cursor, round, view and actor', () => {
  for (const changes of [
    { simulationId: 'sim_B' }, { generationId: 'other' }, { revision: 'new-head' },
    { round: 0 }, { view: 'analyst' }, { actorId: 'actor_B' }, { schemaVersion: 'future' }, { engine: 'future' },
  ]) {
    const response = payload()
    Object.assign(response.data, changes)
    assert.throws(() => world.readWorldResponse(response, request({ generationId: 'gen_sim_A', revision: 'head-2' })), { code: 'view_mismatch' })
  }
  assert.throws(() => world.readWorldResponse({ success: false, code: 'stale_revision' }, request()), { code: 'stale_revision' })
  assert.equal(world.readWorldResponse(payload('sim_A', { round: 0 }), request({ round: 0 })).round, 0)
})

test('actual world template renders EN/ZH, exact values, semantic controls, caveat and identity', async t => {
  const h = harness(t)
  await settle()
  const en = await h.render()
  assert.match(body(en), /Conditional pathway under declared assumptions; not a calibrated probability forecast/)
  assert.match(body(en), /Resource accounts/)
  assert.match(body(en), /12345678901234567890.123456789/)
  assert.match(body(en), /Reserved: 4.5 USD/)
  assert.match(body(en), /false Not applicable Simulated/)
  assert.match(body(en), /Generation gen_sim_A Committed revision head-2 Selected state revision round-2/)
  assert.match(body(en), /missing Unknown MW Unknown/)
  assert.match(body(en), /Pending commitments: 1/)
  assert.match(body(en), /Demand remains constant/)
  assert.ok(!en.includes('WRONG HISTORY'))
  assert.equal((en.match(/role="tab"/g) || []).length, 4)
  assert.equal((en.match(/role="tabpanel"/g) || []).length, 4)
  assert.equal((en.match(/aria-selected="true"/g) || []).length, 1)
  assert.match(en, /<label>Visibility view <select/)
  assert.match(en, /<th scope="col">Unit/)
  assert.match(en, /<option value="0">0 · Initial state/)
  assert.ok(!en.includes('private belief'))
  i18n.locale.value = 'zh'
  const zh = body(await h.render())
  assert.match(zh, /声明假设下的条件路径；不是经过校准的概率预测/)
  assert.match(zh, /资源账户/)
  assert.match(zh, /missing 未知 MW 未知/)
  assert.match(zh, /模型假设/)
})

test('analyst rendering labels private modeled state, escapes model output and links visible causal records', async t => {
  const h = harness(t)
  await settle()
  h.state.view.value = 'analyst'
  await settle()
  const html = await h.render()
  assert.match(body(html), /Analyst view · includes private modeled state/)
  assert.match(body(html), /Private modeled state: simulated beliefs and plans/)
  assert.match(body(html), /private belief A/)
  assert.match(body(html), /Rejected · Not enough resources/)
  assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;'))
  assert.ok(!html.includes('<img'))
  assert.match(html, /href="#world-test-intent-i1"/)
  assert.match(html, /href="#world-test-event-e1"/)
  assert.match(html, /href="#world-test-commitment-c1"/)
  await h.state.followReference('c1')
  assert.equal(h.state.activeTab.value, 'commitments')
  let prevented = 0
  for (const [key, current, next] of [['ArrowRight', 'assumptions', 'state'], ['ArrowLeft', 'state', 'assumptions'], ['Home', 'decisions', 'state'], ['End', 'state', 'assumptions']]) {
    await h.state.tabKeydown({ key, preventDefault: () => prevented++ }, current)
    assert.equal(h.state.activeTab.value, next)
  }
  assert.equal(prevented, 4)
  i18n.locale.value = 'zh'
  assert.match(body(await h.render()), /私有建模状态：模拟中的信念与计划/)
})

test('analyst rendering names a decision committed with an unresolved review and a failed commitment', async t => {
  const flagged = async (id, req) => {
    const response = payload(id, req)
    if (response.data.view === 'analyst') {
      response.data.decisions[0].consistencyStatus = 'unresolved'
      response.data.world.commitments.c1.status = 'failed'
    }
    return response
  }
  const h = harness(t, { api: { getWorldSimulation: flagged } })
  await settle()
  h.state.view.value = 'analyst'
  await settle()
  const en = body(await h.render())
  assert.match(en, /actor_A · Round 1 · Acted · Consistency review unresolved/)
  assert.match(en, /invest · Failed/)
  i18n.locale.value = 'zh'
  const zh = body(await h.render())
  assert.match(zh, /一致性复核未解决/)
  assert.match(zh, /invest · 未能履行/)
})

for (const stale of ['success', 'envelope', 'reject']) {
  test(`simulation A→B→A discards stale ${stale}, including loading/error writes`, async t => {
    const pending = []
    const h = harness(t, { api: { getWorldSimulation: (id, req, options) => { const d = deferred(); pending.push({ ...d, id, req, options }); return d.promise } } })
    h.props.simulationId = 'sim_B'
    h.props.simulationId = 'sim_A' // Same tick is deliberate; flush:'sync' must invalidate both boundaries.
    assert.equal(pending.length, 3)
    assert.equal(pending[0].options.signal.aborted, true)
    assert.equal(pending[1].options.signal.aborted, true)
    if (stale === 'success') pending[0].resolve(payload('sim_A', { revision: 'obsolete' }))
    if (stale === 'envelope') pending[0].resolve({ success: false, code: 'stale_revision' })
    if (stale === 'reject') pending[0].reject(new Error('old failure'))
    await settle()
    assert.equal(h.state.result.value, null)
    assert.equal(h.state.errorCode.value, '')
    assert.equal(h.state.loading.value, true)
    pending[2].resolve(payload())
    await settle()
    pending[1].reject(new Error('late B'))
    await settle()
    assert.equal(h.state.result.value.simulationId, 'sim_A')
    assert.equal(h.state.revision.value, 'head-2')
    assert.equal(h.state.errorCode.value, '')
    assert.equal(h.state.loading.value, false)
  })
}

test('view A→B→A clears private content immediately and refuses late privileged results', async t => {
  const pending = []
  const h = harness(t, { api: { getWorldSimulation: (id, req) => { const d = deferred(); pending.push({ ...d, req }); return d.promise } } })
  pending[0].resolve(payload())
  await settle()
  h.state.view.value = 'analyst'
  h.state.view.value = 'public'
  assert.equal(h.state.result.value, null)
  assert.deepEqual(h.state.actorChoices.value, [])
  pending[2].resolve(payload())
  await settle()
  pending[1].resolve(payload('sim_A', { view: 'analyst' }))
  await settle()
  assert.equal(h.state.result.value.view, 'public')
  assert.deepEqual(h.state.projection.value.privateStates, [])
  assert.ok(!(await h.render()).includes('private belief'))
})

test('actor selection is explicit; actor A→B→A errors and unmount cannot publish', async t => {
  const pending = []
  const h = harness(t, { api: { getWorldSimulation: (id, req, options) => { const d = deferred(); pending.push({ ...d, req, options }); return d.promise } } })
  pending[0].resolve(payload()); await settle()
  h.state.view.value = 'actor'
  assert.equal(pending.length, 1, 'actor view waits for an explicit ID')
  h.state.actorDraft.value = 'actor_A'; h.state.applyActor()
  h.state.actorDraft.value = 'actor_B'; h.state.applyActor()
  h.state.actorDraft.value = 'actor_A'; h.state.applyActor()
  pending[1].resolve({ success: false, code: 'unknown_actor' })
  pending[2].reject(new Error('old actor error'))
  pending[3].resolve(payload('sim_A', { view: 'actor' }))
  await settle()
  assert.equal(h.state.errorCode.value, '')
  assert.equal(h.state.result.value.actorId, 'actor_A')
  const html = await h.render()
  assert.match(html, /<input[^>]*required[^>]*maxlength="128"/)
  assert.match(body(html), /Actor view · information visible to this actor · actor_A/)
  h.state.refreshLatest()
  h.dispose()
  assert.equal(pending[4].options.signal.aborted, true)
  pending[4].reject(new Error('after unmount')); await settle()
  assert.equal(h.state.errorCode.value, '')
  assert.equal(h.state.result.value, null)
})

test('round cursor conflicts stop with a useful message; explicit refresh removes the cursor', async t => {
  let conflict = false
  const h = harness(t, { api: { getWorldSimulation: async (id, req) => conflict
    ? { success: false, code: 'stale_revision' } : payload(id, req) } })
  await settle()
  conflict = true
  h.state.selectedRound.value = '0'; await settle()
  assert.equal(h.calls.at(-1).args[1].round, 0)
  assert.equal(h.calls.at(-1).args[1].revision, 'head-2')
  assert.equal(h.state.result.value, null)
  assert.equal(h.state.loading.value, false)
  assert.match(body(await h.render()), /The committed state changed/)
  const before = h.calls.length
  await settle(); assert.equal(h.calls.length, before, 'conflicts must not retry in a loop')
  conflict = false
  h.state.refreshLatest(); await settle()
  assert.equal(h.calls.at(-1).args[1].revision, undefined)
  assert.equal(h.calls.at(-1).args[1].round, undefined)
  assert.equal(h.state.result.value.round, 2)
  assert.equal(h.calls.at(-1).args[2].timeout, 20000)
})

test('round A→B→A and generation changes invalidate old responses and cursor state', async t => {
  const pending = []
  const h = harness(t, { api: { getWorldSimulation: (id, req) => { const d = deferred(); pending.push({ ...d, req }); return d.promise } } })
  pending[0].resolve(payload()); await settle()
  h.state.selectedRound.value = '0'
  h.state.selectedRound.value = '1'
  h.state.selectedRound.value = '0'
  pending[3].resolve(payload('sim_A', { round: 0 })); await settle()
  pending[1].reject(new Error('old 0')); pending[2].resolve(payload('sim_A', { round: 1 })); await settle()
  assert.equal(h.state.result.value.round, 0)
  h.props.generationId = 'gen_new'
  assert.equal(h.state.result.value, null)
  assert.equal(h.state.revision.value, '')
  assert.equal(h.state.selectedRound.value, '')
  assert.equal(pending[4].req.generationId, 'gen_new')
  pending[4].resolve(payload()) // same simulation, wrong generation
  await settle()
  assert.equal(h.state.errorCode.value, 'view_mismatch')
  assert.equal(h.state.result.value, null)
})

test('parent uses saved engine, preserves legacy feed, and makes no social calls for world runs', async t => {
  const h = harness(t, { parent: true })
  await settle()
  assert.equal(h.state.engine.value, 'world-v1')
  // the saved pin, then one request for the gate-passed record (ADR 0003); still no social calls
  assert.deepEqual(h.calls.map(call => call.key), ['getSimulation', 'fetchRecord'])
  assert.match(await h.render(), /class="world-child"/)
  const legacy = harness(t, { parent: true, api: { getSimulation: async id => ({ success: true, data: { simulation_id: id } }) } })
  await settle()
  assert.equal(legacy.state.engine.value, 'oasis-legacy')
  const html = await legacy.render()
  assert.match(body(html), /Crowd Simulation · OASIS/)
  assert.match(body(html), /Alice/)
  assert.match(body(html), /Legacy social post/)
  assert.match(body(html), /Twitter/)
  assert.match(body(html), /Reddit/)
  assert.equal(legacy.calls.filter(c => c.key === 'getWorldSimulation').length, 0)
})

test('parent does not fall back on unknown pins, failed saved-state envelopes or mismatched runner pins', async t => {
  for (const response of [
    { success: true, data: { simulation_id: 'sim_A', simulation_engine: 'future-v9' } },
    { success: true, data: { simulation_id: 'sim_A', simulation_engine: null } },
    { success: false, error: 'failure' },
  ]) {
    const h = harness(t, { parent: true, api: { getSimulation: async () => response } })
    await settle()
    assert.equal(h.state.engine.value, null)
    assert.equal(h.calls.length, 1)
    assert.match(await h.render(), /role="alert"/)
  }
  const h = harness(t, { parent: true, api: {
    getSimulation: async id => ({ success: true, data: { simulation_id: id, simulation_engine: 'oasis-legacy' } }),
    getRunStatus: async () => ({ success: true, data: { simulation_engine: 'world-v1' } }),
  } })
  await settle()
  assert.equal(h.state.engine.value, null)
  assert.match(body(await h.render()), /Simulation identity changed/)
})

for (const stale of ['success', 'envelope', 'reject']) {
  test(`parent engine A→B→A ignores stale ${stale}`, async t => {
    const pending = []
    const h = harness(t, { parent: true, api: { getSimulation: (id, options) => { const d = deferred(); pending.push({ ...d, id, options }); return d.promise } } })
    h.props.simulationId = 'sim_B'; h.props.simulationId = 'sim_A'
    assert.equal(pending.length, 3)
    assert.equal(pending[0].options.signal.aborted, true)
    pending[2].resolve({ success: true, data: { simulation_id: 'sim_A', simulation_engine: 'world-v1', world_generation_id: 'gen_latest' } })
    await settle()
    if (stale === 'success') pending[0].resolve({ success: true, data: { simulation_id: 'sim_A', simulation_engine: 'oasis-legacy' } })
    if (stale === 'envelope') pending[0].resolve({ success: false, error: 'old error' })
    if (stale === 'reject') pending[0].reject(new Error('old error'))
    pending[1].reject(new Error('late B')); await settle()
    assert.equal(h.state.engine.value, 'world-v1')
    assert.equal(h.state.worldGenerationId.value, 'gen_latest')
    assert.equal(h.state.error.value, '')
    assert.ok(h.calls.every(call => ['getSimulation', 'fetchRecord'].includes(call.key)))
  })
}

test('world API preserves round zero and sends only the chosen view/cursor with cancellation', async () => {
  const source = readFileSync(new URL('../src/api/simulation.js', import.meta.url), 'utf8')
  const calls = []
  const api = new Function('service', source.replace("import service from './index'", '').replaceAll('export const ', 'const ')
    + '\nreturn { getWorldSimulation, getSimulation };')({ get: (...args) => { calls.push(args); return Promise.resolve({ success: true }) } })
  const controller = new AbortController()
  await api.getWorldSimulation('sim/a', { view: 'actor', actorId: 'actor A', round: 0, revision: 'rev1' }, { signal: controller.signal, timeout: 20000 })
  assert.equal(calls[0][0], '/api/simulation/sim%2Fa/world')
  assert.deepEqual(calls[0][1].params, { view: 'actor', actor_id: 'actor A', round: 0, revision: 'rev1' })
  assert.equal(calls[0][1].signal, controller.signal)
  await api.getWorldSimulation('sim_A', { view: 'public', actorId: 'must-not-be-sent' })
  assert.deepEqual(calls[1][1].params, { view: 'public' })
})

test('real contract claim/span references remain readable, assumptions are explicit and disputed values stay labeled', async t => {
  const h = harness(t, { api: { getWorldSimulation: async (id, req) => {
    const res = payload(id, req)
    res.data.world.metrics.capacity.basis = { kind: 'source_claim', refs: [{ actorId: 'actor_A', claimId: 'C14', field: 'capacity', target: 'value' }] }
    res.data.world.metrics.capacity.description = 'Installed capacity'
    res.data.world.metrics.capacity.valueStatus = 'contested'
    res.data.world.metrics.missing.basis = { kind: 'report_excerpt', refs: [{ start: 12, end: 40, sha256: 'not-a-user-control' }] }
    return res
  } } })
  await settle()
  const en = body(await h.render())
  assert.match(en, /Installed capacity/)
  assert.match(en, /Contested Source claim · actor_A \/ C14 · capacity → value/)
  assert.match(en, /Report characters 12–40/)
  assert.match(en, /Demand remains constant. Scenario assumption/)
  assert.ok(!en.includes('[object Object]'))
  assert.ok(!en.includes('not-a-user-control'))
  i18n.locale.value = 'zh'
  assert.match(body(await h.render()), /有争议 来源陈述/)
})

test('current HTTP conflicts and timeouts finish loading without exposing backend diagnostics', async t => {
  for (const error of [
    Object.assign(new Error('sensitive internal path'), { response: { data: { code: 'stale_revision' } } }),
    Object.assign(new Error('sensitive internal path'), { code: 'ECONNABORTED' }),
  ]) {
    const h = harness(t, { api: { getWorldSimulation: async () => { throw error } } })
    await settle()
    assert.equal(h.state.loading.value, false)
    assert.equal(h.state.result.value, null)
    assert.match(await h.render(), /role="alert"/)
    assert.ok(!(await h.render()).includes('sensitive internal path'))
  }
})

test('legacy platform A→B→A drops late feed success and errors without changing the legacy presentation', async t => {
  const pending = []
  const h = harness(t, { parent: true, api: {
    getSimulation: async id => ({ success: true, data: { simulation_id: id, simulation_engine: 'oasis-legacy' } }),
    getSimulationPosts: (id, platform, limit, offset, options) => { const d = deferred(); pending.push({ ...d, platform, options }); return d.promise },
  } })
  await settle()
  h.state.switchPlatform('reddit'); await settle()
  h.state.switchPlatform('twitter'); await settle()
  assert.equal(pending.length, 3)
  assert.equal(pending[0].options.signal.aborted, true)
  assert.equal(pending[1].options.signal.aborted, true)
  assert.equal(pending[2].options.timeout, 20000)
  pending[0].resolve({ success: true, data: { posts: [{ content: 'obsolete' }] } })
  pending[1].reject(new Error('old platform'))
  await settle()
  assert.equal(h.state.loading.value, true)
  assert.deepEqual(h.state.posts.value, [])
  pending[2].resolve({ success: true, data: { posts: [{ content: 'fresh social post' }] } })
  await settle()
  assert.equal(h.state.posts.value[0].content, 'fresh social post')
  assert.equal(h.state.error.value, '')
  assert.equal(h.state.loading.value, false)
})

test('parent disposal and empty identity invalidate unresolved engine requests', async t => {
  for (const action of ['dispose', 'clear']) {
    const d = deferred()
    const h = harness(t, { parent: true, api: { getSimulation: () => d.promise } })
    if (action === 'dispose') h.dispose()
    else h.props.simulationId = ''
    assert.equal(h.calls[0].args[1].signal.aborted, true)
    d.resolve({ success: true, data: { simulation_id: 'sim_A', simulation_engine: 'world-v1' } })
    await settle()
    assert.equal(h.state.engine.value, null)
    assert.equal(h.state.error.value, '')
    assert.equal(h.calls.length, 1)
  }
})

test('round invalidation clears actor suggestions before loading and after failure', async t => {
  const late = deferred()
  const h = harness(t, { api: { getWorldSimulation: async (id, req) => req.round === 0 ? late.promise : payload(id, req) } })
  await settle()
  h.state.view.value = 'actor'
  h.state.actorDraft.value = 'actor_A'; h.state.applyActor()
  await settle()
  assert.ok(h.state.actorChoices.value.includes('actor_B'), 'later-round offer makes actor_B visible')
  h.state.selectedRound.value = '0'
  assert.deepEqual(h.state.actorChoices.value, [], 'no suggestions from another round while loading')
  late.reject(new Error('round request failed')); await settle()
  assert.deepEqual(h.state.actorChoices.value, [], 'failed loads cannot retain stale historical identifiers')
})

test('causal joins scale linearly with cumulative history and keep actor-bound resolutions', () => {
  const data = payload('sim_A', { view: 'analyst' }).data
  const count = 2000
  let eventReferenceReads = 0
  let resolutionReferenceReads = 0
  data.decisions = Array.from({ length: count }, (_, i) => ({ actorId: 'actor_A', decisionId: `d${i}`, intents: [{ intentId: `i${i}` }] }))
  data.events = Array.from({ length: count }, (_, i) => ({ eventId: `e${i}`, visibility: PUBLIC,
    get sourceIntentId() { eventReferenceReads++; return `i${i}` } }))
  data.resolutions = Array.from({ length: count }, (_, i) => ({ actorId: 'actor_A', accepted: true,
    get intentId() { resolutionReferenceReads++; return `i${i}` } }))
  data.resolutions.unshift({ actorId: 'actor_B', intentId: 'i0', accepted: false })
  const projected = world.projectWorldResult(data)
  assert.equal(projected.decisions.length, count)
  assert.equal(projected.decisions[0].intents[0].resolution.accepted, true)
  assert.equal(projected.decisions.at(-1).intents[0].events[0].eventId, `e${count - 1}`)
  assert.ok(eventReferenceReads <= count * 2, `event joins exceeded a linear read budget: ${eventReferenceReads}`)
  assert.ok(resolutionReferenceReads <= count * 2, `resolution joins exceeded a linear read budget: ${resolutionReferenceReads}`)
})
