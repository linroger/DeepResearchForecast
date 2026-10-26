import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'

const ORIGIN = 'http://127.0.0.1:18761'
const index = process.argv.indexOf('--evidence-dir')
if (index < 0 || !process.argv[index + 1]) throw new Error('--evidence-dir is required')
const evidence = path.resolve(process.argv[index + 1])
await mkdir(evidence, { mode: 0o700 })
const { chromium } = createRequire(import.meta.url)('/opt/homebrew/lib/node_modules/mcp-jobs/node_modules/playwright')
const events = [], pending = new Set()
const save = (name, value) => writeFile(path.join(evidence, name), JSON.stringify(value, null, 2) + '\n')
const fixtureReceipt = async () => {
  const response = await fetch(ORIGIN + '/__fixture/receipt', { redirect: 'error', signal: AbortSignal.timeout(5000) })
  assert.equal(response.status, 200)
  return response.json()
}
const beforeReceipt = await fixtureReceipt()
const context = await chromium.launchPersistentContext(path.join(evidence, 'profile'), {
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true,
  viewport: { width: 1500, height: 1100 }, serviceWorkers: 'block',
  args: ['--no-first-run', '--disable-background-networking', '--disable-component-update', '--disable-sync', '--no-proxy-server',
    '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'],
})
let result
try {
  await context.route('**/*', route => new URL(route.request().url()).origin === ORIGIN ? route.continue() : route.abort('blockedbyclient'))
  const page = context.pages()[0] || await context.newPage()
  page.setDefaultTimeout(12000)
  page.on('console', message => events.push({ event: 'console', type: message.type(), message: message.text() }))
  page.on('pageerror', error => events.push({ event: 'pageerror', message: error.message }))
  page.on('close', () => events.push({ event: 'pageclosed', at: new Date().toISOString() }))
  page.on('request', request => { if (request.url().includes('/api/')) events.push({ event: 'request', method: request.method(), url: request.url(), body: request.postData() }) })
  page.on('response', response => {
    if (!response.url().includes('/api/')) return
    const task = (async () => { let body; try { body = await response.json() } catch {} events.push({ event: 'response', url: response.url(), status: response.status(), body }) })()
    pending.add(task); task.finally(() => pending.delete(task))
  })
  await page.goto(ORIGIN, { waitUntil: 'domcontentloaded' })
  await page.getByTestId('tab-forecast').click()
  const root = page.getByTestId('surface-forecast')
  const action = root.locator('.translate-btn').filter({ hasText: /Retry translation|重试翻译|Generate|生成/i }).first()
  await action.waitFor({ state: 'visible' })
  await page.waitForFunction(() => [...document.querySelectorAll('[data-testid="surface-forecast"] .translate-btn')]
    .some(button => /Retry translation|重试翻译|Generate|生成/i.test(button.textContent) && !button.disabled))
  const buttonBefore = { textContent: await action.textContent(), innerText: await action.innerText(), disabled: await action.isDisabled() }
  await page.screenshot({ path: path.join(evidence, 'before.png'), fullPage: true })
  await writeFile(path.join(evidence, 'before.txt'), await root.innerText())
  const eventIndex = events.length
  await action.click()
  // Observe the visible UI effect, not an internal component state or direct method.
  await root.getByText('The current report does not permit this translation action', { exact: true }).waitFor({ state: 'visible', timeout: 5000 })
  await page.screenshot({ path: path.join(evidence, 'after.png'), fullPage: true })
  const after = await root.innerText()
  await writeFile(path.join(evidence, 'after.txt'), after)
  await Promise.allSettled([...pending])
  const clickRequests = events.slice(eventIndex).filter(event => event.event === 'request')
  const afterReceipt = await fixtureReceipt()
  result = { reproduced: true, buttonBefore, inline_error: 'The current report does not permit this translation action',
    click_requests: clickRequests, translation_posts: clickRequests.filter(event => event.method === 'POST' && event.url.includes('/translations/')).length,
    provider_calls_before: beforeReceipt.provider_calls, provider_calls_after: afterReceipt.provider_calls,
    page_errors: events.filter(event => event.event === 'pageerror'), current_build_source_drift: afterReceipt.guard.source_drift,
    conclusion: 'Actual enabled Retry click re-reads report metadata, rejects action admission inline, and never reaches resource POST.' }
  assert.equal(result.translation_posts, 0)
  assert.equal(result.provider_calls_after, result.provider_calls_before)
  await save('server-before.json', beforeReceipt); await save('server-after.json', afterReceipt)
} catch (error) {
  result = { reproduced: false, error: error.message, stack: error.stack }
  process.exitCode = 1
} finally {
  await Promise.allSettled([...pending])
  await save('events.json', events); await save('result.json', result)
  await context.close()
  process.stdout.write(JSON.stringify({ evidence, ...result }) + '\n')
}
