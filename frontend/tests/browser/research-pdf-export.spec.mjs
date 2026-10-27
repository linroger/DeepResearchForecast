import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'

const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')
const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds))
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
const normalize = text => String(text).normalize('NFKC').replace(/\s+/g, '').replace(/[*_`]/g, '')
const fixtures = [
  { kind: 'dossier', id: 'pipe_pdf_en', language: 'en' },
  { kind: 'dossier', id: 'pipe_pdf_zh', language: 'zh-CN' },
  { kind: 'forecast', id: 'report_pdf_en', language: 'en' },
  { kind: 'forecast', id: 'report_pdf_zh', language: 'zh-CN' },
]
const resourceBase = fixture => fixture.kind === 'dossier'
  ? `/api/research/${fixture.id}/dossier/pdf-export` : `/api/report/${fixture.id}/pdf-export`

export function browserRequestAllowed(method, url, viteUrl) {
  const parsed = new URL(url)
  if (parsed.origin !== viteUrl) return false
  const pathname = parsed.pathname
  if (method === 'POST') return fixtures.some(fixture => pathname === resourceBase(fixture))
  if (method !== 'GET') return false
  if (!pathname.startsWith('/api/')) return true // Vite modules, CSS and fonts.
  return fixtures.some(fixture => {
    const base = resourceBase(fixture)
    if (pathname.startsWith(`${base}/`) && /^[A-Za-z0-9_-]+(?:\/download)?$/.test(pathname.slice(base.length + 1))) return true
    if (fixture.kind === 'dossier') return pathname === `/api/research/${fixture.id}/dossier`
      || pathname.startsWith(`/api/research/${fixture.id}/artifact/chart_`)
    return ['', '/viz-manifest', '/forecast', '/official-data'].some(suffix => pathname === `/api/report/${fixture.id}${suffix}`)
      || pathname.startsWith(`/api/report/${fixture.id}/charts/`)
  })
}

export function validateCachedCompletion(payload, status, fixture, prior) {
  assert.equal(status, 200, 'Cached real start must return HTTP200 without a redirect')
  assert.equal(payload?.success, true)
  const job = payload.data
  assert.equal(job?.state, 'completed')
  assert.equal(job?.error, null)
  assert.equal(job?.job_id, prior.job_id)
  assert.equal(job?.kind, fixture.kind)
  assert.equal(job?.resource_id, fixture.id)
  assert.equal(job?.requested_lang, null)
  assert.equal(job?.language, fixture.language)
  assert.equal(job?.source_digest, prior.source_digest)
  assert.equal(job?.download_url, `${resourceBase(fixture)}/${prior.job_id}/download`)
  return job
}

export async function runBrowserAcceptance({ browser, viteUrl, apiUrl, outputDir, extractPdfText, timeout = 180000 }) {
  const receipt = { schema: 'research-pdf-browser-acceptance/v1', started_at: new Date().toISOString(),
    status: 'running', api_url: apiUrl, vite_url: viteUrl,
    implementation: 'actual Vue SFCs, API clients, export helper, Flask jobs, agent and renderer; model transport controlled by fixture server',
    cases: [], limitations: ['No live provider calls or provider quality claim.', 'Primary English/Mandarin fixture exports; variant admission is covered by separate source/unit tests.'] }
  const receiptPath = path.join(outputDir, 'receipt.json')
  const persist = () => writeFile(receiptPath, JSON.stringify(receipt, null, 2) + '\n')
  await mkdir(outputDir, { recursive: true })
  await persist()

  async function apiGet(route) {
    const response = await fetch(`${apiUrl}${route}`, { signal: AbortSignal.timeout(timeout), redirect: 'error' })
    assert.ok(response.ok, `Fixture GET ${route} returned ${response.status}: ${response.ok ? '' : await response.text()}`)
    return response
  }

  async function withPage(name, work) {
    const directory = path.join(outputDir, name)
    await mkdir(directory, { recursive: true })
    const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1440, height: 1000 } })
    const external = [], blocked = [], pageErrors = [], requests = [], jobs = [], responseReads = []
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (!browserRequestAllowed(request.method(), url.href, viteUrl)) {
        blocked.push({ method: request.method(), url: url.href })
        if (url.origin !== viteUrl) external.push(url.href)
        await route.abort('blockedbyclient')
      } else await route.continue()
    })
    await context.tracing.start({ screenshots: true, snapshots: true, sources: true })
    const page = await context.newPage()
    page.setDefaultTimeout(15000)
    page.on('pageerror', error => pageErrors.push(error.message))
    page.on('request', request => {
      const url = new URL(request.url())
      if (url.pathname.startsWith('/api/')) requests.push({ method: request.method(), path: url.pathname,
        body: request.method() === 'POST' && /\/pdf-export$/.test(url.pathname) ? request.postDataJSON() : null })
    })
    page.on('response', response => {
      const pathname = new URL(response.url()).pathname
      if (/\/pdf-export(?:\/[^/]+)?$/.test(pathname)) {
        responseReads.push(response.json().then(payload => jobs.push({ http_status: response.status(), path: pathname, job: payload.data, error: payload.error }))
          .catch(() => {}))
      }
    })
    const result = { name, status: 'running' }
    receipt.cases.push(result)
    try {
      await work({ page, directory, requests, jobs, responseReads, result, context })
      await Promise.all(responseReads)
      assert.deepEqual(pageErrors, [], 'Browser page errors')
      assert.deepEqual(external, [], 'Unexpected external browser requests')
      assert.deepEqual(blocked, [], 'Unexpected request was blocked before reaching Flask')
      assert.ok(requests.every(row => row.method === 'GET' || (row.method === 'POST' && /\/pdf-export$/.test(row.path))), 'Unexpected write outside PDF job start')
      assert.ok(requests.every(row => !/\/pdf$/.test(row.path)), 'Legacy PDF fallback must never be requested')
      result.status = 'passed'
    } catch (error) {
      result.status = 'failed'
      result.error = error.stack || String(error)
      await page.screenshot({ path: path.join(directory, 'failure.png'), fullPage: true }).catch(() => {})
    } finally {
      await Promise.all(responseReads)
      result.requests = requests
      result.jobs = jobs
      result.page_errors = pageErrors
      result.external_requests = external
      result.blocked_requests = blocked
      await context.tracing.stop({ path: path.join(directory, 'trace.zip') })
      await context.close()
      await persist()
    }
  }

  async function openFixture(page, fixture) {
    await page.goto(`${viteUrl}/tests/browser/research-pdf-export.html?fixture=${fixture.id}`)
    await page.locator('#subject .pdf-btn').waitFor({ state: 'visible' })
    assert.equal(await page.locator('#subject .pdf-btn').count(), 1, 'Mount exactly one real PDF control')
    await page.evaluate(() => {
      window.__pdfObservations = []
      const capture = () => {
        const button = document.querySelector('#subject .pdf-btn')
        if (button) window.__pdfObservations.push({ text: button.textContent.trim(), disabled: button.disabled, busy: button.getAttribute('aria-busy') })
      }
      new MutationObserver(capture).observe(document.querySelector('#subject'), { subtree: true, childList: true, attributes: true, characterData: true })
      capture()
    })
  }

  for (const fixture of fixtures) {
    await withPage(`download-${fixture.id}`, async ({ page, directory, requests, jobs, responseReads, result }) => {
      const sourceRoute = fixture.kind === 'dossier' ? `/api/research/${fixture.id}/dossier` : `/api/report/${fixture.id}`
      const sourcePayload = await (await apiGet(sourceRoute)).json()
      const source = fixture.kind === 'dossier' ? sourcePayload.data?.report : sourcePayload.data?.markdown_content
      assert.ok(typeof source === 'string' && source.trim(), 'Fixture must serve its full source body')
      await openFixture(page, fixture)
      const downloaded = page.waitForEvent('download', { timeout })
      const exportError = page.locator('#subject [role="alert"]').first()
      const outcome = Promise.race([
        downloaded.then(download => ({ download })),
        exportError.waitFor({ state: 'visible', timeout }).then(async () => ({ error: await exportError.innerText() })),
      ])
      // Two synchronous clicks on the production control exercise its own request
      // guard even before Vue flushes the DOM's disabled attribute.
      await page.locator('#subject .pdf-btn').evaluate(button => { button.click(); button.click() })
      const completedOutcome = await outcome
      if (completedOutcome.error) throw new Error(`PDF export failed in the actual UI: ${completedOutcome.error}`)
      const download = completedOutcome.download
      const filename = download.suggestedFilename()
      assert.ok(filename.endsWith('.pdf') && !/[\\/]/.test(filename), 'Safe PDF filename')
      const pdfPath = path.join(directory, filename)
      await download.saveAs(pdfPath)
      assert.equal(await download.failure(), null)
      await Promise.all(responseReads)
      const starts = requests.filter(row => row.method === 'POST' && row.path === resourceBase(fixture))
      assert.equal(starts.length, 1, 'Repeated clicks must issue one start POST')
      assert.deepEqual(starts[0].body, { lang: null }, 'Primary selection must remain null, including Mandarin')
      const completed = jobs.findLast(row => row.job?.state === 'completed')?.job
      assert.ok(completed, `No completed job. Last responses: ${JSON.stringify(jobs.slice(-3))}`)
      assert.equal(completed.kind, fixture.kind)
      assert.equal(completed.resource_id, fixture.id)
      assert.equal(completed.requested_lang, null)
      assert.equal(completed.language, fixture.language)
      assert.match(completed.source_digest, /^[a-f0-9]{64}$/i)
      assert.equal(completed.download_url, `${resourceBase(fixture)}/${completed.job_id}/download`)
      const browserBytes = await readFile(pdfPath)
      assert.equal(browserBytes.subarray(0, 5).toString(), '%PDF-')
      const serverFile = await apiGet(completed.download_url)
      assert.match(serverFile.headers.get('content-type') || '', /^application\/pdf/)
      const serverBytes = Buffer.from(await serverFile.arrayBuffer())
      assert.equal(sha256(browserBytes), sha256(serverBytes), 'Browser file must match renewed server-admitted bytes exactly')
      const text = await extractPdfText(pdfPath)
      await writeFile(path.join(directory, 'download-text.txt'), text)
      const heading = source.match(/^#\s+(.+)$/m)?.[1]
      assert.ok(heading && normalize(text).includes(normalize(heading)), 'Downloaded PDF must include the selected source title')
      if (fixture.language === 'zh-CN') assert.ok((text.match(/[\u3400-\u9fff]/g) || []).length >= 5, 'Mandarin PDF must contain extractable Han text')
      else assert.ok((text.match(/[A-Za-z]{4,}/g) || []).length >= 5, 'English PDF must contain extractable English text')
      const observations = await page.evaluate(() => window.__pdfObservations)
      assert.ok(observations.some(row => row.busy === 'true' && row.disabled), 'Observe the production pending state')
      assert.ok(jobs.some(row => ['queued', 'running'].includes(row.job?.state)), 'Use a fresh fixture server to exercise an actual pending backend job')
      await page.waitForFunction(() => !document.querySelector('#subject .pdf-btn')?.disabled)
      await page.screenshot({ path: path.join(directory, 'completed.png'), fullPage: true })
      Object.assign(result, { fixture, job_id: completed.job_id, source_digest: completed.source_digest,
        source_markdown_sha256: sha256(source), pdf_sha256: sha256(browserBytes), server_pdf_sha256: sha256(serverBytes),
        filename, bytes: browserBytes.length, source_title: heading, observations })
    })
  }

  // Hold a real cached Flask start response at the browser boundary. This keeps
  // stale-response timing deterministic without replacing any job/model/PDF data.
  for (const fixture of fixtures.filter(row => row.language === 'en')) for (const change of ['resource', 'unmount']) {
    const prior = receipt.cases.find(row => row.name === `download-${fixture.id}`)
    if (prior?.status !== 'passed') continue
    await withPage(`stale-${fixture.id}-${change}`, async ({ page, requests, result }) => {
      await openFixture(page, fixture)
      const arrived = deferred(), release = deferred(), handlerSettled = deferred()
      const cancellations = []
      let heldJob, handlerFailure, deliveryFailure
      page.on('requestfailed', request => {
        if (new URL(request.url()).pathname === resourceBase(fixture)) cancellations.push(request.failure()?.errorText || '')
      })
      await page.route(`${viteUrl}${resourceBase(fixture)}`, async route => {
        try {
          assert.equal(route.request().method(), 'POST', 'Only the real start request may be delayed')
          // APIRequestContext does not pass redirects through browser routing.
          const response = await route.fetch({ timeout, maxRedirects: 0 })
          const payload = await response.json()
          heldJob = validateCachedCompletion(payload, response.status(), fixture, prior)
          arrived.resolve()
          await release.promise
          await route.fulfill({ response })
        } catch (error) {
          if (!heldJob) handlerFailure = error
          else deliveryFailure = error
          arrived.resolve()
        } finally {
          handlerSettled.resolve()
        }
      })
      const downloads = []
      page.on('download', item => downloads.push(item.suggestedFilename()))
      await page.locator('#subject .pdf-btn').click()
      let arrivalTimer
      try {
        await Promise.race([arrived.promise, new Promise((_, reject) => {
          arrivalTimer = setTimeout(() => reject(new Error('Real start response did not arrive')), timeout)
        })])
        if (handlerFailure) throw handlerFailure
        assert.equal(await page.locator('#subject .pdf-btn').isDisabled(), true)
        if (change === 'resource') await page.getByTestId('fixture').selectOption(fixture.id.replace(/_en$/, '_zh'))
        else await page.getByTestId('toggle-mount').click()
      } finally {
        clearTimeout(arrivalTimer)
        release.resolve()
      }
      await handlerSettled.promise
      await sleep(2000)
      if (deliveryFailure) assert.ok(cancellations.some(message => /abort|cancel/i.test(message)),
        `Failed delivery without expected request cancellation: ${deliveryFailure.message}`)
      assert.deepEqual(downloads, [], 'Late start response must not trigger a stale download')
      assert.equal(requests.filter(row => row.path.endsWith('/download')).length, 0)
      assert.equal(requests.filter(row => row.method === 'GET' && row.path === `${resourceBase(fixture)}/${heldJob.job_id}`).length, 0,
        'Late start must not schedule old-job status polling')
      assert.equal(requests.filter(row => row.method === 'POST').length, 1)
      if (change === 'resource') {
        await page.locator('#subject .pdf-btn').waitFor({ state: 'visible' })
        assert.equal(await page.locator('#subject .pdf-btn').isEnabled(), true)
      } else assert.equal(await page.locator('#subject .pdf-btn').count(), 0)
      Object.assign(result, { fixture, change, held_job_id: heldJob.job_id, browser_downloads: downloads,
        held_source_digest: heldJob.source_digest, cancellations, observation_window_ms: 2000,
        delivery: deliveryFailure ? 'aborted with browser cancellation evidence' : 'fulfilled unchanged real completion',
        timing_control: 'Delayed real Flask response; no mocked job or PDF' })
    })
  }

  receipt.finished_at = new Date().toISOString()
  receipt.status = receipt.cases.every(row => row.status === 'passed') && receipt.cases.length === 8 ? 'passed' : 'failed'
  receipt.counts = { total: receipt.cases.length, passed: receipt.cases.filter(row => row.status === 'passed').length,
    failed: receipt.cases.filter(row => row.status === 'failed').length }
  await persist()
  return { receipt, receiptPath }
}
