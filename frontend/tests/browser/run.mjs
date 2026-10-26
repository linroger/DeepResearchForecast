import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { createHash } from 'node:crypto'
import { mkdir, readdir, readFile, writeFile, stat } from 'node:fs/promises'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ORIGIN = 'http://127.0.0.1:18761'
const EGRESS_NEGATIVE = 'https://translation-fixture.invalid/blocked'
const arg = name => { const i = process.argv.indexOf(name); return i < 0 ? undefined : process.argv[i + 1] }
const evidenceArg = arg('--evidence-dir') || process.env.DRF_BROWSER_EVIDENCE
if (!evidenceArg) throw new Error('Usage: node frontend/tests/browser/run.mjs --evidence-dir /private/tmp/<new-browser-evidence> [--surfaces dossier,forecast,...] [--smoke]')
if (arg('--origin') && arg('--origin') !== ORIGIN) throw new Error('Only the exact guarded fixture origin is allowed')
const evidence = path.resolve(evidenceArg)
const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
if (evidence === repository || evidence.startsWith(repository + path.sep)) throw new Error('Evidence must be outside the repository')
await mkdir(evidence, { recursive: false, mode: 0o700 })
for (const name of ['screenshots', 'downloads', 'network', 'pdf-pages', 'receipts']) await mkdir(path.join(evidence, name))
const playwright = createRequire(import.meta.url)('/opt/homebrew/lib/node_modules/mcp-jobs/node_modules/playwright')
const executablePath = arg('--browser-executable') || process.env.DRF_BROWSER_EXECUTABLE || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
if (!path.isAbsolute(executablePath)) throw new Error('Browser executable must be an explicit absolute path')
await stat(executablePath)
const hash = data => createHash('sha256').update(data).digest('hex')
const safe = value => String(value).replace(/[^a-zA-Z0-9_.-]+/g, '-')
const json = (name, data) => writeFile(path.join(evidence, name), JSON.stringify(data, null, 2) + '\n')
const network = [], pageErrors = [], consoleMessages = [], blocked = [], downloads = [], cases = [], browserEvents = []
let finalReceipt = null, egressNegative = null, buildSourceDrift = []
const pending = new Set()
let phase = 'startup', context, page, bootstrap, browserVersion = '', terminationSignal = null
const started = Date.now(), budget = Number(arg('--budget-ms') || 600000)
const remaining = () => Math.max(1, budget - (Date.now() - started))
const track = promise => { pending.add(promise); promise.catch(error => consoleMessages.push({ phase, capture_error: error.message })).finally(() => pending.delete(promise)) }
const emit = message => process.stdout.write(JSON.stringify({ at: new Date().toISOString(), phase, ...message }) + '\n')
async function fixture(endpoint, command) {
  assert.ok(endpoint.startsWith('/__fixture/') || endpoint === '/build-receipt.json')
  const response = await fetch(ORIGIN + endpoint, { redirect: 'error', signal: AbortSignal.timeout(15000),
    ...(command ? { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(command) } : {}) })
  if (!response.ok) throw new Error(`Fixture ${endpoint} returned HTTP ${response.status}: ${(await response.text()).slice(0, 300)}`)
  return response.json()
}
const control = command => fixture('/__fixture/control', command)
async function receipt(label) { const data = await fixture('/__fixture/receipt'); await json(`receipts/${safe(label)}.json`, data); return data }
async function screenshot(label) {
  const filename = `screenshots/${safe(label)}.png`
  await page.screenshot({ path: path.join(evidence, filename), fullPage: true, animations: 'disabled', timeout: 15000 })
  await writeFile(path.join(evidence, 'screenshots', `${safe(label)}.txt`), await page.locator('body').innerText())
  return filename
}
async function until(predicate, description, timeout = 60000) {
  const end = Date.now() + Math.min(timeout, remaining())
  let last
  while (Date.now() < end) {
    if (terminationSignal) throw new Error(`Browser run interrupted by ${terminationSignal}`)
    if (page?.isClosed()) throw new Error('Browser closed while waiting; this case cannot continue')
    try { const value = await predicate(); if (value) return value } catch (error) { last = error }
    await new Promise(resolve => setTimeout(resolve, 150))
  }
  throw new Error(`Timed out: ${description}${last ? ` (${last.message})` : ''}`)
}
function routes(surface) {
  if (surface === 'dossier') return { post: `/api/research/${bootstrap.ids.pipeline}/dossier/translations/zh`, get: `/api/research/${bootstrap.ids.pipeline}/dossier/translations/zh` }
  if (surface === 'forecast') return { post: `/api/report/${bootstrap.ids.report}/translations/zh`, get: `/api/report/${bootstrap.ids.report}/translations/zh/status` }
  if (surface === 'graph') return { post: `/api/graph/${bootstrap.graph.graph_id}/translations/zh`, get: `/api/graph/${bootstrap.graph.graph_id}/translations/zh` }
  const id = surface === 'world' ? bootstrap.ids.world : surface === 'record' ? bootstrap.ids.record : bootstrap.ids.oasis
  return { post: `/api/simulation/${id}/translations/zh`, get: `/api/simulation/${id}/translations/zh` }
}
const root = surface => page.getByTestId(`surface-${surface}`)
function bodyLocator(surface) {
  const selector = { dossier: '.md-body', forecast: '.md-body', graph: '.summary-text', oasis: '.post-text:not(.empty)',
    'world-state': '.ws-var-prov', world: '[role="tabpanel"]:visible .record > p:not(.muted)', record: '.rec-banner' }[surface]
  return root(surface).locator(selector).first()
}
async function openSurface(surface) {
  await page.getByTestId(`tab-${surface}`).click()
  const target = root(surface)
  await target.waitFor({ state: 'visible' })
  if (surface === 'graph') {
    await until(async () => await target.locator('circle.node-dot').count() > 0, 'graph nodes rendered')
    // Click the actual D3-generated node. No component internals are invoked.
    await target.locator('circle.node-dot').first().click({ force: true })
  }
  if (surface === 'world') {
    await target.getByRole('tab', { name: /Model assumptions|模型假设/ }).click()
  }
  await bodyLocator(surface).waitFor({ state: 'visible', timeout: 30000 })
  return target
}
async function enabledButton(locator) {
  for (let i = 0; i < await locator.count(); i++) {
    const button = locator.nth(i)
    if (await button.isVisible() && await button.isEnabled()) return button
  }
  return null
}
async function activateTarget(surface) {
  const target = root(surface)
  if (surface === 'forecast') {
    const language = target.locator('.lang-btn').filter({ hasText: '中文' })
    if (await language.count()) await language.first().click()
    else await (await until(() => enabledButton(target.locator('.translate-btn').filter({ hasText: /Generate|Retry|生成|重试/i })), 'forecast start button')).click()
  } else if (surface === 'dossier') {
    await target.locator('.lang-btn').filter({ hasText: '中文' }).click()
    const action = await until(() => enabledButton(target.locator('.edit-btn').filter({ hasText: /Generate Mandarin|生成中文|Retry translation|重试翻译/i })), 'dossier start/retry button')
    await action.click()
  } else if (surface === 'graph') await target.getByTitle(/Toggle Chinese translation|切换中文翻译/).click()
  else if (surface === 'world-state') await target.locator('.ws-lang-btn').click()
  else if (surface === 'world') await target.locator('.world-header button').filter({ hasText: /中文/ }).click()
  else await target.locator('.sv-header .refresh-btn').filter({ hasText: /中文/ }).first().click()
}
async function sourceLanguage(surface) {
  const target = root(surface)
  if (surface === 'dossier') await target.locator('.lang-btn').first().click()
  else if (surface === 'forecast') await target.locator('.lang-btn').filter({ hasText: /^EN$/ }).click()
  else if (surface === 'graph') await target.getByTitle(/Toggle Chinese translation|切换中文翻译/).click()
  else if (surface === 'world-state') await target.locator('.ws-lang-btn').click()
  else if (surface === 'world') await target.locator('.world-header button').filter({ hasText: /English/ }).click()
  else await target.locator('.sv-header .refresh-btn').filter({ hasText: /English/ }).first().click()
}
function retryButtons(surface) {
  const target = root(surface)
  if (surface === 'forecast') return target.locator('.translate-btn').filter({ hasText: /Retry translation|重试翻译/i })
  if (surface === 'dossier') return target.locator('.edit-btn').filter({ hasText: /Retry translation|重试翻译/i })
  const statusClass = { graph: '.graph-translation-status', oasis: '.sv-translation', 'world-state': '.ws-translation', world: '.translation-note', record: '.rec-translation' }[surface]
  return target.locator(statusClass).getByRole('button', { name: /Retry translation|重试翻译/i })
}
const isPost = (event, route) => event.method === 'POST' && new URL(event.url).pathname === route
async function downloadPdf(surface, language) {
  const target = root(surface), index = network.length
  const button = surface === 'forecast' ? target.locator('.pdf-btn') : target.locator('.dossier-language-bar .edit-btn').filter({ hasText: /PDF/ })
  assert.ok(new RegExp(language === 'zh' ? 'Mandarin|中文' : 'English|英文', 'i').test(await button.innerText()), 'PDF button must explicitly identify displayed language')
  const [download] = await Promise.all([page.waitForEvent('download', { timeout: 45000 }), button.click()])
  const name = download.suggestedFilename()
  assert.ok(name.endsWith(language === 'zh' ? '.zh.pdf' : '.pdf'))
  if (language === 'en') assert.ok(!/\.(zh|en)\.pdf$/.test(name), 'primary filename must be unsuffixed')
  const relative = `downloads/${surface}-${language}-${safe(name)}`
  await download.saveAs(path.join(evidence, relative))
  assert.equal(await download.failure(), null)
  const bytes = await readFile(path.join(evidence, relative))
  assert.equal(bytes.subarray(0, 5).toString(), '%PDF-')
  const response = await until(() => network.slice(index).find(event => event.status === 200 && /^application\/pdf/i.test(event.contentType || '')), 'PDF MIME response')
  const requestUrl = new URL(response.url)
  if (language === 'en') assert.equal(requestUrl.searchParams.has('lang'), false)
  else assert.equal(requestUrl.searchParams.get('lang'), 'zh')
  assert.match(requestUrl.searchParams.get('source_sha256') || requestUrl.searchParams.get('source_sha') || '', /^[a-f0-9]{64}$/)
  const textPath = path.join(evidence, relative + '.txt')
  execFileSync('/opt/homebrew/bin/pdftotext', ['-layout', path.join(evidence, relative), textPath], { timeout: 15000 })
  const extracted = await readFile(textPath, 'utf8')
  assert.ok(extracted.includes(language === 'zh' ? 'BROWSER PDF MANDARIN' : 'BROWSER PDF ENGLISH'), 'PDF language marker')
  if (language === 'zh') assert.match(extracted, /[\u3400-\u9fff]/, 'PDF must contain Mandarin body glyphs')
  else assert.match(extracted, /committee|capacity|equipment/i, 'PDF must contain the actual English body')
  assert.ok(!extracted.includes('\ufffd'), 'PDF must not contain replacement glyphs')
  const imagePrefix = path.join(evidence, 'pdf-pages', `${surface}-${language}`)
  execFileSync('/opt/homebrew/bin/pdftoppm', ['-f', '1', '-singlefile', '-scale-to', '1600', '-png', path.join(evidence, relative), imagePrefix], { timeout: 15000 })
  downloads.push({ surface, language, filename: name, file: relative, sha256: hash(bytes), bytes: bytes.length,
    contentType: response.contentType, url: response.url, text: relative + '.txt', rendered_page: `pdf-pages/${surface}-${language}.png` })
}
async function oneSurface(surface) {
  phase = surface; emit({ state: 'starting' })
  const source = await openSurface(surface)
  const original = await bodyLocator(surface).innerText()
  assert.ok(original.trim(), 'source body is populated')
  await screenshot(`${surface}-source`)
  if (surface === 'dossier' || surface === 'forecast') await downloadPdf(surface, 'en')
  const begin = await receipt(`${surface}-before`)
  await control({ action: 'fail_provider', value: true })
  const startIndex = network.length
  await activateTarget(surface)
  await until(() => network.slice(startIndex).some(event => isPost(event, routes(surface).post)), 'explicit translation POST')
  await until(async () => {
    const r = await fixture('/__fixture/receipt')
    return r.provider_failures > begin.provider_failures && await enabledButton(retryButtons(surface))
  }, 'failed provider state with a usable retry control', 90000)
  await screenshot(`${surface}-failed-retry`)
  await control({ action: 'fail_provider', value: false })
  await control({ action: 'delay_provider', seconds: 0.15 })
  const retryIndex = network.length
  const posted = page.waitForRequest(request => request.method() === 'POST' && new URL(request.url()).pathname === routes(surface).post, { timeout: 15000 })
  await (await enabledButton(retryButtons(surface))).click()
  await posted
  // Arm after the explicit mutation so the transport interruption hits observation,
  // not an earlier mount GET or the paid-work admission check.
  await control({ action: 'fail_get', path: routes(surface).get, count: 1 })
  await until(() => network.slice(retryIndex).some(event => event.status === 503 && new URL(event.url).pathname === routes(surface).get), 'injected translation GET failure', 90000)
  await until(async () => /Reconnecting|Connection lost|连接中断|正在重新查询/.test(await source.innerText()), 'visible reconnect feedback', 12000)
  await screenshot(`${surface}-reconnecting`)
  await until(async () => /[\u3400-\u9fff]/.test(await bodyLocator(surface).innerText()), 'translated content is visible', 120000)
  if (surface === 'graph') {
    await until(async () => /1001\s*\/\s*1001/.test(await source.locator('.graph-translation-status').innerText()), 'complete graph inventory across five pages', 120000)
    const posts = network.slice(retryIndex).filter(event => event.kind === 'request' && isPost(event, routes(surface).post))
    assert.equal(posts.length, 5, '1001-entry graph must advance through exactly five successful continuation requests')
  }
  let admittedContent = null
  if (surface === 'world') {
    // Only model prose counts. Static status/basis labels can turn Chinese before
    // any provider result and therefore cannot establish translation acceptance.
    admittedContent = await until(async () => {
      const visible = (await bodyLocator(surface).innerText()).trim()
      for (const event of network.slice(retryIndex).filter(event => event.kind === 'response' && event.status === 200
          && new URL(event.url).pathname === routes(surface).get && event.body_file).reverse()) {
        let envelope
        try { envelope = JSON.parse(await readFile(path.join(evidence, event.body_file), 'utf8')) } catch { continue }
        const data = envelope.data || envelope
        const row = (data.translations || []).find(row => row.source === original.trim()
          && row.source_sha256 === hash(Buffer.from(original.trim(), 'utf8')) && row.text?.trim() === visible)
        if (row) return { source: row.source, translated: row.text, source_sha256: row.source_sha256, response_file: event.body_file }
      }
      return false
    }, 'visible model assumption equals its exact source-bound admitted translation row', 30000)
  }
  await screenshot(`${surface}-translated`)
  if (surface === 'dossier' || surface === 'forecast') await downloadPdf(surface, 'zh')
  const translated = await bodyLocator(surface).innerText()
  assert.notEqual(translated, original, 'target content must differ from the source body, not merely UI chrome')
  await sourceLanguage(surface)
  await until(async () => (await bodyLocator(surface).innerText()) === original, 'source-language body restored')
  await screenshot(`${surface}-restored-source`)
  const end = await receipt(`${surface}-after`)
  await control({ action: 'delay_provider', seconds: 0.015 })
  return { source_text: original, translated_text: translated, admitted_content: admittedContent, provider_calls_before: begin.provider_calls,
    provider_calls_after: end.provider_calls, provider_failures_before: begin.provider_failures,
    provider_failures_after: end.provider_failures, translation_post_count: network.slice(startIndex).filter(event => event.kind === 'request' && isPost(event, routes(surface).post)).length }
}

let fatal
for (const signal of ['SIGTERM', 'SIGINT']) process.once(signal, () => {
  terminationSignal = signal
  fatal ||= { message: `Browser run interrupted by ${signal}` }
  emit({ stopping: signal })
  // Give normal finally blocks a bounded chance to save receipts. The parent
  // orchestrator also owns process-group cleanup if this deadline is exceeded.
  const deadline = setTimeout(() => process.exit(signal === 'SIGTERM' ? 143 : 130), 8000)
  deadline.unref()
  Promise.resolve(context?.close()).catch(() => {})
})
try {
  bootstrap = await fixture('/__fixture/bootstrap')
  await json('bootstrap.json', bootstrap)
  const initial = await receipt('initial')
  assert.equal(Object.values(initial.negative_controls || {}).filter(value => value === 'blocked').length, 7, 'fixture isolation negative controls')
  const buildReceipt = await fixture('/build-receipt.json')
  await json('build-receipt.json', buildReceipt)
  for (const row of buildReceipt.sources || []) {
    if (hash(await readFile(path.join(repository, row.path))) !== row.sha256) buildSourceDrift.push(row.path)
  }
  const fixtureFiles = []
  for (const name of (await readdir(path.dirname(fileURLToPath(import.meta.url)))).sort()) {
    const file = new URL(name, import.meta.url)
    if ((await stat(file)).isFile()) fixtureFiles.push({ path: `frontend/tests/browser/${name}`, sha256: hash(await readFile(file)) })
  }
  await json('browser-source-hashes.json', fixtureFiles)
  context = await playwright.chromium.launchPersistentContext(path.join(evidence, 'chromium-profile'), {
    executablePath, headless: !process.argv.includes('--headed'), viewport: { width: 1500, height: 1100 },
    acceptDownloads: true, serviceWorkers: 'block', locale: 'en-US',
    args: ['--disable-background-networking', '--disable-component-update', '--disable-sync', '--no-first-run', '--no-default-browser-check',
      '--disable-default-apps', '--no-proxy-server', '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',
      '--disable-features=MediaRouter,OptimizationHints,AutofillServerCommunication,CertificateTransparencyComponentUpdater'],
  })
  browserVersion = context.browser()?.version() || ''
  await context.route('**/*', async route => {
    const url = route.request().url()
    if (new URL(url).origin !== ORIGIN) { blocked.push({ phase, url, expected: url === EGRESS_NEGATIVE }); return route.abort('blockedbyclient') }
    return route.continue()
  })
  if (context.routeWebSocket) await context.routeWebSocket('**/*', socket => { blocked.push({ phase, websocket: socket.url() }); socket.close() })
  context.on('close', () => browserEvents.push({ event: 'context-closed', at: new Date().toISOString(), phase }))
  context.browser()?.on('disconnected', () => browserEvents.push({ event: 'browser-disconnected', at: new Date().toISOString(), phase }))
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true })
  page = context.pages()[0] || await context.newPage()
  page.setDefaultTimeout(15000)
  page.on('close', () => browserEvents.push({ event: 'page-closed', at: new Date().toISOString(), phase }))
  page.on('crash', () => browserEvents.push({ event: 'page-crashed', at: new Date().toISOString(), phase }))
  const ids = new WeakMap(); let sequence = 0
  page.on('request', request => {
    const id = ++sequence; ids.set(request, id)
    network.push({ kind: 'request', id, phase, at: new Date().toISOString(), method: request.method(), url: request.url(), body: request.postData() })
  })
  page.on('response', response => track((async () => {
    const request = response.request(), headers = await response.allHeaders(), id = ids.get(request)
    const event = { kind: 'response', id, phase, at: new Date().toISOString(), method: request.method(), url: response.url(),
      status: response.status(), contentType: headers['content-type'] || '', disposition: headers['content-disposition'] || '' }
    network.push(event)
    if (new URL(response.url()).origin === ORIGIN && /application\/json|application\/pdf/.test(event.contentType)) {
      try {
        const bytes = await response.body(); event.bytes = bytes.length; event.sha256 = hash(bytes)
        if (/application\/json/.test(event.contentType) && bytes.length < 10000000) {
          event.body_file = `network/${id}.json`; await writeFile(path.join(evidence, event.body_file), bytes)
        }
      } catch (error) { event.body_error = error.message }
    }
  })()))
  page.on('requestfailed', request => network.push({ kind: 'requestfailed', id: ids.get(request), phase, url: request.url(), failure: request.failure() }))
  page.on('pageerror', error => pageErrors.push({ phase, message: error.message, stack: error.stack }))
  page.on('console', message => consoleMessages.push({ phase, type: message.type(), text: message.text() }))
  await page.goto(ORIGIN, { waitUntil: 'domcontentloaded' })
  await page.getByTestId('browser-harness').locator('[data-testid="tab-dossier"]').waitFor()
  await until(async () => await page.getByTestId('browser-harness').getAttribute('data-ready') === 'true', 'real harness bootstrap')
  phase = 'egress-negative-control'
  const rejected = await page.evaluate(async url => { try { await fetch(url, { mode: 'no-cors' }); return false } catch { return true } }, EGRESS_NEGATIVE)
  assert.equal(rejected, true, 'outbound fetch must fail')
  assert.ok(blocked.some(event => event.url === EGRESS_NEGATIVE && event.expected))
  assert.equal(network.some(event => event.kind === 'response' && event.url === EGRESS_NEGATIVE), false)
  egressNegative = { url: EGRESS_NEGATIVE, blocked: true, received_response: false, payload: null }
  await json('egress-negative-control.json', egressNegative)
  const surfaces = (arg('--surfaces') || 'dossier,forecast,graph,oasis,world-state,world,record').split(',')
  for (const surface of surfaces) {
    if (remaining() <= 1) throw new Error('Browser acceptance time budget exhausted')
    if (page.isClosed()) throw new Error('Browser closed before the next surface; remaining surfaces were not run')
    phase = surface
    const start = Date.now()
    try {
      const result = process.argv.includes('--smoke')
        ? (await openSurface(surface), await screenshot(`${surface}-smoke`), { smoke_only: true, text: await bodyLocator(surface).innerText() })
        : await oneSurface(surface)
      cases.push({ surface, passed: true, elapsed_ms: Date.now() - start, ...result }); emit({ surface, passed: true })
    } catch (error) {
      cases.push({ surface, passed: false, elapsed_ms: Date.now() - start, error: error.message, stack: error.stack })
      await screenshot(`${surface}-failure`).catch(() => {})
      emit({ surface, passed: false, error: error.message })
      if (page.isClosed()) throw new Error(`Browser disconnected during ${surface}; later surfaces were not run`)
    } finally { if (!terminationSignal) { await control({ action: 'fail_provider', value: false }).catch(() => {}); await control({ action: 'delay_provider', seconds: 0.015 }).catch(() => {}) } }
  }
  if (pageErrors.length) throw new Error(`${pageErrors.length} uncaught browser page errors`)
  if (blocked.some(event => !event.expected)) throw new Error('Unexpected requests outside the fixture origin were blocked')
} catch (error) { fatal = { message: error.message, stack: error.stack }; emit({ fatal: error.message }) }
finally {
  await Promise.allSettled([...pending])
  await json('network.json', network); await json('page-errors.json', pageErrors); await json('console.json', consoleMessages); await json('blocked-requests.json', blocked)
  finalReceipt = await receipt('final').catch(error => { fatal ||= { message: `Final fixture receipt unavailable: ${error.message}` } })
  if (context) { await context.tracing.stop({ path: path.join(evidence, 'trace.zip') }).catch(() => {}); await context.close() }
  await json('browser-events.json', browserEvents)
  const sourceDrift = finalReceipt?.guard?.source_drift || []
  const passed = !fatal && cases.length > 0 && cases.every(item => item.passed)
  const result = { schema: 'translation-browser-acceptance/v1', started_at: new Date(started).toISOString(), elapsed_ms: Date.now() - started,
    origin: ORIGIN, browser: executablePath, browser_version: browserVersion, termination_signal: terminationSignal, custom_profile: 'chromium-profile', smoke_only: process.argv.includes('--smoke'),
    passed, acceptance_ready: passed && !process.argv.includes('--smoke') && cases.length === 7
      && sourceDrift.length === 0 && buildSourceDrift.length === 0, cases, fatal, downloads,
    source_drift: sourceDrift, build_source_drift: buildSourceDrift, egress_negative_control: egressNegative,
    page_error_count: pageErrors.length, blocked_request_count: blocked.length, unexpected_blocked_request_count: blocked.filter(event => !event.expected).length,
    isolation: 'Chromium context routing allows exact fixture origin only; service workers blocked, WebSockets closed, DNS/background networking disabled. This is not a host firewall.',
    limits: ['Controlled deterministic CJK translation/review stand-in; no live-provider semantic-quality claim.',
      'Real API/publication/PDF browser transport with fixture PyMuPDF renderer; Pandoc typography is outside this run.'] }
  await json('result.json', result)
  emit({ passed: result.passed, evidence, surfaces: cases.length, downloads: downloads.length })
  process.exitCode = result.passed ? 0 : 1
}
