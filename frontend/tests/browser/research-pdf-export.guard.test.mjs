import assert from 'node:assert/strict'
import test from 'node:test'
import { browserRequestAllowed, validateCachedCompletion } from './research-pdf-export.spec.mjs'

const origin = 'http://127.0.0.1:37891'
const fixture = { kind: 'dossier', id: 'pipe_pdf_en', language: 'en' }
const prior = { job_id: 'pdf_job_A', source_digest: 'a'.repeat(64) }
const complete = () => ({ success: true, data: { job_id: prior.job_id, source_digest: prior.source_digest,
  kind: fixture.kind, resource_id: fixture.id, requested_lang: null, language: 'en', state: 'completed', error: null,
  download_url: '/api/research/pipe_pdf_en/dossier/pdf-export/pdf_job_A/download' } })

for (const [method, route] of [
  ['GET', '/src/components/research/ForecastReport.vue'],
  ['GET', '/api/research/pipe_pdf_zh/dossier'],
  ['GET', '/api/report/report_pdf_zh'],
  ['GET', '/api/report/report_pdf_en/forecast?lang=en'],
  ['GET', '/api/report/report_pdf_zh/official-data?lang=zh'],
  ['GET', '/api/report/report_pdf_en/charts/figure.png'],
  ['POST', '/api/research/pipe_pdf_en/dossier/pdf-export'],
  ['POST', '/api/report/report_pdf_zh/pdf-export'],
  ['GET', '/api/research/pipe_pdf_en/dossier/pdf-export/pdf_job_A'],
  ['GET', '/api/report/report_pdf_en/pdf-export/pdf_job_A/download'],
]) test(`routing admits ${method} ${route}`, () => {
  assert.equal(browserRequestAllowed(method, origin + route, origin), true)
})

for (const [method, url] of [
  ['POST', origin + '/api/research/run'],
  ['POST', origin + '/api/report/report_pdf_en/translations/zh'],
  ['POST', origin + '/api/report/report_unrelated/pdf-export'],
  ['POST', origin + '/api/report/report_pdf_en/pdf-export/pdf_job_A/cancel'],
  ['PUT', origin + '/api/research/pipe_pdf_en/dossier'],
  ['DELETE', origin + '/api/research/pipe_pdf_en'],
  ['GET', origin + '/api/research/pipe_pdf_en/dossier/pdf'],
  ['GET', origin + '/api/report/report_pdf_en/pdf'],
  ['GET', origin + '/api/report/report_unrelated'],
  ['GET', 'https://provider.example/v1/models'],
]) test(`routing blocks before dispatch ${method} ${url}`, () => {
  assert.equal(browserRequestAllowed(method, url, origin), false)
})

test('a completed cached response carries exact source and resource identity', () => {
  assert.equal(validateCachedCompletion(complete(), 200, fixture, prior).job_id, prior.job_id)
})
for (const patch of [
  { state: 'failed' }, { state: 'stale' }, { state: 'running' },
  { resource_id: 'pipe_pdf_zh' }, { requested_lang: 'zh' }, { language: 'zh-CN' },
  { source_digest: 'b'.repeat(64) }, { error: { code: 'rejected' } },
  { download_url: 'https://external.example/file.pdf' },
]) test(`stale-observer fixture rejects invalid held completion ${JSON.stringify(patch)}`, () => {
  const payload = complete()
  Object.assign(payload.data, patch)
  assert.throws(() => validateCachedCompletion(payload, 200, fixture, prior))
})
test('a redirect cannot count as the held real cache completion', () => {
  assert.throws(() => validateCachedCompletion(complete(), 302, fixture, prior))
})
