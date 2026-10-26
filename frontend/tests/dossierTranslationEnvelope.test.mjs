import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { createDossierTranslationAdapter, normalizeDossierTranslation, dossierSourceDigest } from '../src/utils/dossierTranslationAdapter.js'

const source = '# Original research\n\nEnglish source.'
const sourceSha = createHash('sha256').update(source).digest('hex')
const response = data => ({ success: true, data: { target_lang: 'zh', source_sha256: sourceSha, ...data } })
const normalize = (data, options) => normalizeDossierTranslation(response(data), { lang: 'zh', sourceSha, ...options })

test('dossier adapter accepts backend JSON and Axios envelopes without losing the audited body', () => {
  const body = response({ status: 'available', available: true, report: '审计通过的译文。' })
  for (const raw of [body, { data: body }]) {
    const snapshot = normalizeDossierTranslation(raw, { lang: 'zh', sourceSha })
    assert.equal(snapshot.available, true)
    assert.equal(snapshot.data.report, body.data.report)
    assert.equal(snapshot.active, false)
  }
})

test('completed job or available status alone cannot admit unverified Markdown', () => {
  for (const data of [
    { status: 'available', report: 'Not admitted' },
    { available: false, report: 'Not admitted', translation_job: { job_state: 'completed' } },
    { available: true, report: '   ' },
    { available: true, report: { invalid: 'body' } },
  ]) assert.equal(normalize(data).available, false)
})

test('wrong target is a non-retryable identity rejection; backend failures are not content', () => {
  assert.throws(() => normalize({ target_lang: 'en', available: true, report: 'Wrong language' }),
    error => error.retryable === false && /language/.test(error.message))
  assert.throws(() => normalizeDossierTranslation({ success: false, error: 'audit failed' }, { lang: 'zh' }), /audit failed/)
  assert.throws(() => normalize({ structured_translation: { target_lang: 'en' } }), error => error.retryable === false)
})

test('actual research transport forwards abort signals and binds PDF requests to admitted identity', async () => {
  const calls = []
  const service = Object.fromEntries(['get', 'post'].map(method => [method, (...args) => calls.push([method, ...args])]))
  const source = readFileSync(new URL('../src/api/research.js', import.meta.url), 'utf8')
    .replace(/^import service, \{ apiUrl \} from '\.\/index'\n/, '').replace(/^export /gm, '')
  const api = new Function('service', 'apiUrl', `${source}\nreturn {getResearchTranslation,requestResearchTranslation,researchPdfUrl};`)(service, path => `/prefix${path}`)
  const controller = new AbortController()
  await api.getResearchTranslation('pipe_A', 'zh', { signal: controller.signal })
  await api.requestResearchTranslation('pipe_A', 'zh', false, { signal: controller.signal })
  await api.requestResearchTranslation('pipe_A', 'zh', true, { signal: controller.signal })
  assert.deepEqual(calls, [
    ['get', '/api/research/pipe_A/dossier/translations/zh', { signal: controller.signal }],
    ['post', '/api/research/pipe_A/dossier/translations/zh', undefined, { signal: controller.signal }],
    ['post', '/api/research/pipe_A/dossier/translations/zh?force=1', undefined, { signal: controller.signal }],
  ])
  assert.equal(api.researchPdfUrl('pipe_A'), '/prefix/api/research/pipe_A/dossier/pdf')
  assert.equal(api.researchPdfUrl('pipe_A', 'zh', { sourceSha: 'sha+A', generation: 'gen/1' }),
    '/prefix/api/research/pipe_A/dossier/pdf?lang=zh&source_sha256=sha%2BA&generation=gen%2F1')
})

test('attached job controls lifecycle while admitted body and partial structured coverage stay separate', () => {
  const snapshot = normalize({ status: 'available', available: true, report: '已通过审计。',
    structured_translation: { complete: false, status: 'generating' },
    translation_job: { schema: 'translation-job/v2', job_id: 'tj_resume', job_revision: 4,
      job_state: 'interrupted', issues: ['review needs resuming'], actions: { retry: true, stop: false },
      coverage: { required: 8, accepted: 5, pending_translation: 1, pending_review: 1, failed: 1, reused: 3 } },
  })
  assert.equal(snapshot.state, 'interrupted')
  assert.equal(snapshot.active, false)
  assert.equal(snapshot.available, true)
  assert.equal(snapshot.partial, true)
  assert.equal(snapshot.actions.retry, true)
  assert.deepEqual(snapshot.coverage, { total: 8, accepted: 5, pending: 3 })
  assert.ok(snapshot.issues.includes('review needs resuming'))
})

test('legacy structured generation remains observable after body publication', () => {
  const snapshot = normalize({ status: 'available', available: true, report: '已通过审计。',
    structured_translation: { status: 'generating', complete: false,
      coverage: { total: 7, translated: 4 }, issues: ['cards pending'] },
  })
  assert.equal(snapshot.active, true)
  assert.equal(snapshot.available, true)
  assert.equal(snapshot.partial, true)
  assert.deepEqual(snapshot.coverage, { total: 7, accepted: 4, pending: 3 })
  assert.ok(snapshot.issues.includes('cards pending'))
  assert.equal(normalize({ status: 'available', available: true, report: '正文。' }, { hasStructuredContent: true }).partial, true)
})

test('start acknowledgment reads the audited body; retry forwards force=false and cancellation', async () => {
  const controller = new AbortController()
  const calls = []
  const adapter = createDossierTranslationAdapter({ pipelineId: 'pipe_A', lang: 'zh', sourceMarkdown: source,
    get: async (...args) => { calls.push(['get', ...args]); return response({ available: true, report: '已存在。' }) },
    start: async (...args) => { calls.push(['post', ...args]); return response({ status: 'available', available: true }) },
  })
  const snapshot = await adapter.start({ signal: controller.signal, force: false, action: 'retry' })
  assert.equal(snapshot.data.report, '已存在。')
  assert.deepEqual(calls, [
    ['post', 'pipe_A', 'zh', false, { signal: controller.signal }],
    ['get', 'pipe_A', 'zh', { signal: controller.signal }],
  ])
  controller.abort()
  await adapter.start({ signal: controller.signal, force: true, action: 'refresh' })
  assert.equal(calls.length, 2, 'cancelled subscription cannot initiate a POST or publication GET')
})

test('source admission requires the displayed source digest, including when a job completed', () => {
  for (const digest of [undefined, '', createHash('sha256').update('Server replacement').digest('hex')]) {
    assert.throws(() => normalize({ source_sha256: digest, available: true, report: 'Changed source translation',
      translation_job: { job_state: 'completed' } }), error => error.retryable === false && /source/.test(error.message))
  }
})

test('fallback digest hashes exact displayed UTF-8 including Mandarin and line endings', async () => {
  for (const markdown of ['# 中文研究\n\n增长 3%。\n', '# 中文研究\r\n\r\n增长 3%。\r\n']) {
    assert.equal(await dossierSourceDigest(markdown), createHash('sha256').update(markdown, 'utf8').digest('hex'))
  }
  assert.notEqual(await dossierSourceDigest('A\nB'), await dossierSourceDigest('A\r\nB'))
  assert.equal(await dossierSourceDigest(source, sourceSha), sourceSha)
  assert.throws(() => dossierSourceDigest(source, 'invalid-server-digest'), error => error.retryable === false)
})
