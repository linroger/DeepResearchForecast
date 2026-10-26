import assert from 'node:assert/strict'
import test from 'node:test'
import { effectScope, ref } from 'vue'
import { useTranslationJob } from '../src/composables/useTranslationJob.js'
import { normalizeTranslationSnapshot as normalize } from '../src/utils/translationJobAdapter.js'

const waitFor = async condition => { for (let i = 0; i < 200 && !condition(); i++) await new Promise(r => setTimeout(r, 1)); assert.ok(condition()) }
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
function mount(t, { get, start, ...options }) {
  const identity = ref({ resource: 'A', revision: 1, lang: 'zh' }), scope = effectScope(), seen = []
  const observer = scope.run(() => useTranslationJob({ identity, adapter: () => ({ get, start }),
    onUpdate: state => seen.push(state.data), pollMs: 1, ...options }))
  t.after(() => scope.stop())
  return { identity, scope, seen, observer }
}
const state = (status, extra = {}) => normalize({ status, ...extra })

test('mount reconnects to queued durable work and recovers a transient GET without a POST', async t => {
  let gets = 0, posts = 0
  const h = mount(t, { get: async () => {
    gets++
    if (gets === 2) throw new Error('offline')
    return state(gets < 3 ? 'generating' : 'available')
  }, start: async () => { posts++; return state('generating') } })
  await waitFor(() => h.observer.status.value === 'available')
  assert.equal(posts, 0); assert.equal(gets, 3); assert.equal(h.observer.error.value, '')
})

test('source/revision/language changes and scope disposal reject late responses despite ignored abort', async t => {
  const old = deferred(), late = deferred(); let calls = 0
  const h = mount(t, { get: async () => ++calls === 1 ? old.promise : state('available', { text: 'current' }), start: async () => late.promise })
  h.identity.value = { resource: 'B', revision: 2, lang: 'zh' }
  await waitFor(() => h.seen.length === 1)
  old.resolve(state('available', { text: 'old' })); await new Promise(r => setImmediate(r))
  assert.deepEqual(h.seen.map(s => s.text), ['current'])
  const action = h.observer.retry(); h.identity.value = null
  late.resolve(state('available', { text: 'late' })); await action
  assert.equal(h.observer.status.value, 'source'); assert.equal(h.seen.length, 1)
  h.scope.stop()
})

test('retry reuses candidates and explicit refresh alone forces replacement', async t => {
  const forces = []
  const h = mount(t, { get: async () => state('failed'), start: async options => { forces.push(options.force); return state('available') } })
  await waitFor(() => h.observer.status.value === 'failed')
  await h.observer.retry(); await h.observer.refresh()
  assert.deepEqual(forces, [false, true])
})

test('v2 job activity is independent of admitted content and coverage counts pending review', () => {
  const s = normalize({ status: 'available', available: true, translation_job: {
    schema: 'translation-job/v2', job_id: 'tj_x', job_revision: 3, job_state: 'running', status: 'generating', phase: 'review',
    coverage: { required: 10, accepted: 5, pending_translation: 2, pending_review: 2, failed: 1, reused: 4 }, actions: { retry: false, stop: true },
  } })
  assert.equal(s.active, true); assert.equal(s.available, true); assert.equal(s.actions.retry, false)
  assert.deepEqual(s.coverage, { total: 10, accepted: 5, pending: 5 })
})

test('explicit generation progresses bounded pages without force; a reader never advances a tail', async t => {
  let posts = 0
  const page = n => ({ ...state('partial', { partial: true, pending: 8 - n }), continue: true,
    coverage: { total: 8, accepted: n, pending: 8 - n } })
  const h = mount(t, { maxPages: 3, get: async () => page(1), start: async options => {
    assert.equal(options.force, false); posts++; return page(posts + 1)
  } })
  await waitFor(() => h.observer.status.value === 'partial'); assert.equal(posts, 0)
  await h.observer.retry(); await waitFor(() => posts === 3 && !h.observer.busy.value)
  assert.equal(h.observer.coverage.value.pending, 4)
  assert.equal(h.observer.actions.value.retry, true)
})

test('failed/no-progress page never loops and older job revisions cannot replace newer progress', async t => {
  let posts = 0, gets = 0
  const job = revision => state('partial', { translation_job: { job_id: 'tj_x', job_revision: revision, job_state: 'interrupted' } })
  const h = mount(t, { get: async () => job(++gets === 1 ? 3 : gets === 2 ? 2 : 4), start: async () => {
    posts++; return { ...state('failed'), continue: false, coverage: { total: 100, accepted: 5, pending: 95 } }
  } })
  await waitFor(() => h.observer.snapshot.value?.job?.job_revision === 3)
  await h.observer.observe(); assert.equal(h.observer.snapshot.value.job.job_revision, 3)
  await waitFor(() => h.observer.snapshot.value.job.job_revision === 4)
  await h.observer.retry(); await new Promise(r => setTimeout(r, 5)); assert.equal(posts, 1)
})

test('refresh continuation advances when accepted count stays constant and refresh_pending falls', async t => {
  const forces = []
  const h = mount(t, { get: async () => state('available', { total_candidates: 600, translated: 600, pending: 0 }),
    start: async ({ force }) => {
      forces.push(force)
      const remaining = Math.max(0, 600 - forces.length * 216)
      return { ...state(remaining ? 'partial' : 'available', { total_candidates: 600, translated: 600,
        pending: 0, refresh_pending: remaining }), continue: remaining > 0 }
    } })
  await waitFor(() => h.observer.status.value === 'available')
  await h.observer.refresh()
  await waitFor(() => forces.length === 3 && !h.observer.busy.value)
  assert.deepEqual(forces, [true, false, false])
  assert.equal(h.observer.snapshot.value.refreshPending, 0)
})

test('artifact full inventory wins over completed page coverage and false page retry action', () => {
  const s = normalize({ status: 'partial', partial: true, total_candidates: 1001, translated: 216, pending: 785,
    translation_job: { job_id: 'tj_page', job_state: 'completed', coverage: { required: 216, accepted: 216 }, actions: { retry: false } } })
  assert.equal(s.state, 'partial')
  assert.deepEqual(s.coverage, { total: 1001, accepted: 216, pending: 785 })
})

test('legacy translated coverage and waiting_provider preserve full counters and active observation', () => {
  const complete = normalize({ status: 'available', coverage: { total: 10, translated: 10, complete: true } })
  assert.deepEqual(complete.coverage, { total: 10, accepted: 10, pending: 0 })
  const pending = normalize({ translation_job: { job_state: 'waiting_provider', coverage: {
    required: 10, accepted: 5, pending_translation: 1, pending_review: 2, failed: 1, disclosed_source_fallback: 1,
  } } })
  assert.equal(pending.active, true)
  assert.deepEqual(pending.coverage, { total: 10, accepted: 5, pending: 5 })
})

test('permanently old job revisions cannot create an unbounded status-read loop', async t => {
  let gets = 0
  const h = mount(t, { maxPolls: 2, get: async () => state('available', { translation_job: {
    job_id: 'tj_stale', job_state: 'completed', job_revision: ++gets === 1 ? 4 : 3,
  } }), start: async () => { throw new Error('No provider start permitted') } })
  await waitFor(() => h.observer.snapshot.value?.job?.job_revision === 4)
  await h.observer.observe()
  await waitFor(() => h.observer.status.value === 'timeout')
  assert.equal(gets, 3)
  assert.equal(h.observer.snapshot.value.job.job_revision, 4)
  assert.equal(h.observer.actions.value.retry, true)
})
