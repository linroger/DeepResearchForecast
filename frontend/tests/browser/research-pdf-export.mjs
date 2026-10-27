#!/usr/bin/env node
import { existsSync } from 'node:fs'
import { mkdtemp, mkdir, writeFile } from 'node:fs/promises'
import { tmpdir, homedir } from 'node:os'
import { createRequire } from 'node:module'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { runBrowserAcceptance } from './research-pdf-export.spec.mjs'

const execFileAsync = promisify(execFile)
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const argv = process.argv.slice(2)
const options = {}
for (let index = 0; index < argv.length; index++) {
  const argument = argv[index]
  if (['--help', '--check', '--headed'].includes(argument)) options[argument.slice(2)] = true
  else if (['--api-url', '--output-dir', '--playwright-module', '--browser-executable', '--pdftotext', '--timeout-ms'].includes(argument)) {
    if (!argv[index + 1] || argv[index + 1].startsWith('--')) throw new Error(`Missing value for ${argument}`)
    options[argument.slice(2)] = argv[++index]
  } else throw new Error(`Unknown argument: ${argument}`)
}
if (options.help) {
  console.log(`Usage: node tests/browser/research-pdf-export.mjs --api-url http://127.0.0.1:PORT [--output-dir DIR]

Requires the parent-owned fixture server, already running on a private loopback port.
This CLI never starts Flask or contacts a provider. It starts/stops its own loopback
Vite server and temporary-profile Chromium browser, and writes eight case receipts.

Options:
  --check                   Compile the real SFC harness and smoke-check Chromium;
                            never connect to a backend. --api-url is not needed.
  --playwright-module PATH  Installed Playwright entry; defaults to local or bundled.
  --browser-executable PATH Existing browser; defaults to installed Chrome if needed.
  --pdftotext PATH          Existing pdftotext command (default: PATH/Homebrew).
  --timeout-ms NUMBER       Per-export limit (default 180000).
  --headed                  Show the private browser window.

Use a fresh fixture server for four real pending-job cases; cached jobs are then
reused for four delayed-response stale-observer cases. No job/PDF response is mocked.`)
  process.exit(0)
}

function loopbackUrl(value) {
  const parsed = new URL(value)
  if (!['http:', 'https:'].includes(parsed.protocol)
      || !['127.0.0.1', 'localhost', '[::1]'].includes(parsed.hostname)
      || parsed.username || parsed.password || parsed.pathname !== '/' || parsed.search || parsed.hash
      || !parsed.port) throw new Error('--api-url must name an explicit private loopback server port, without credentials or a path')
  return parsed.origin
}
const apiUrl = options.check ? null : loopbackUrl(options['api-url'] || '')
const timeout = Number(options['timeout-ms'] || 180000)
if (!Number.isFinite(timeout) || timeout < 1000 || timeout > 20 * 60 * 1000) throw new Error('--timeout-ms must be between 1000 and 1200000')
const outputDir = options['output-dir'] ? path.resolve(options['output-dir']) : await mkdtemp(path.join(tmpdir(), 'research-pdf-browser-'))
await mkdir(outputDir, { recursive: true })

async function loadPlaywright() {
  const require = createRequire(import.meta.url)
  const candidates = [options['playwright-module'], process.env.PLAYWRIGHT_MODULE,
    path.join(root, 'node_modules/playwright/index.mjs'),
    path.join(homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')]
  try { candidates.push(require.resolve('playwright')) } catch (_) { /* use runtime bundle */ }
  for (const entry of candidates.filter(Boolean)) {
    if (existsSync(entry)) return import(pathToFileURL(path.resolve(entry)).href)
  }
  throw new Error('Installed Playwright not found. Pass --playwright-module pointing to the bundled installation; this harness does not install dependencies.')
}
const { chromium } = await loadPlaywright()
const candidates = [options['browser-executable'], process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
  chromium.executablePath(), '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome']
const executablePath = candidates.find(candidate => candidate && existsSync(candidate))
if (!executablePath) throw new Error('No installed Chromium executable. Pass --browser-executable; no browser installation is performed.')
const pdftotext = options.pdftotext || process.env.PDFTOTEXT || (existsSync('/opt/homebrew/bin/pdftotext') ? '/opt/homebrew/bin/pdftotext' : 'pdftotext')
if (!options.check) await execFileAsync(pdftotext, ['-v'], { timeout: 5000 })

let server, browser
try {
  server = await createServer({
    configFile: false, root, plugins: [vue()], logLevel: 'warn',
    cacheDir: path.join(outputDir, '.vite'),
    define: { 'import.meta.env.VITE_API_BASE_URL': JSON.stringify('') },
    server: { host: '127.0.0.1', port: 0, strictPort: true, open: false,
      proxy: apiUrl ? { '/api': { target: apiUrl, changeOrigin: true, xfwd: true } } : undefined },
  })
  await server.listen()
  const address = server.httpServer.address()
  const viteUrl = `http://127.0.0.1:${address.port}`
  browser = await chromium.launch({ headless: !options.headed, executablePath })
  if (options.check) {
    const transformed = []
    for (const file of ['/tests/browser/research-pdf-export-app.js', '/src/components/research/DossierViewer.vue', '/src/components/research/ForecastReport.vue']) {
      const output = await server.transformRequest(file)
      if (!output?.code) throw new Error(`No compiled code for ${file}`)
      transformed.push(file)
    }
    const page = await browser.newPage()
    await page.setContent('<title>Browser dependency check</title><p>Private Chromium is ready.</p>')
    if (await page.title() !== 'Browser dependency check') throw new Error('Chromium smoke check failed')
    const result = { status: 'ready', backend_started: false, backend_contacted: false, acceptance_executed: false,
      transformed, browser_version: browser.version(), executable: executablePath, output_dir: outputDir }
    await writeFile(path.join(outputDir, 'readiness.json'), JSON.stringify(result, null, 2) + '\n')
    console.log(JSON.stringify(result, null, 2))
  } else {
    const { receipt, receiptPath } = await runBrowserAcceptance({ browser, viteUrl, apiUrl, outputDir, timeout,
      extractPdfText: async pdfPath => {
        const { stdout } = await execFileAsync(pdftotext, ['-layout', pdfPath, '-'], { timeout: 30000, maxBuffer: 16 * 1024 * 1024 })
        return stdout
      },
    })
    console.log(JSON.stringify({ status: receipt.status, ...receipt.counts, receipt: receiptPath, output_dir: outputDir }, null, 2))
    if (receipt.status !== 'passed') process.exitCode = 1
  }
} finally {
  await browser?.close()
  await server?.close()
}
