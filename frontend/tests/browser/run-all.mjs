// Each surface gets both a fresh browser process AND a fresh guarded Flask root.
// Cached child world-state translations cannot make a later negative case vacuous.
import { spawn, execFileSync } from 'node:child_process'
import { createConnection } from 'node:net'
import { mkdir, open, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const repo = path.resolve(here, '../../..')
const arg = name => { const i = process.argv.indexOf(name); return i < 0 ? undefined : process.argv[i + 1] }
const evidence = path.resolve(arg('--evidence-dir') || '')
const staticDir = path.resolve(arg('--static-dir') || '')
if (!arg('--evidence-dir') || !arg('--static-dir')) throw new Error('Supply new --evidence-dir and already built --static-dir')
if (evidence.startsWith(repo + path.sep) || evidence === repo) throw new Error('Evidence must be disposable and outside the repository')
const surfaces = (arg('--surfaces') || 'dossier,forecast,graph,oasis,world-state,world,record').split(',')
const all = ['dossier', 'forecast', 'graph', 'oasis', 'world-state', 'world', 'record']
if (surfaces.some(s => !all.includes(s)) || new Set(surfaces).size !== surfaces.length) throw new Error('Invalid surface selection')
const budget = Number(arg('--case-budget-ms') || 180000)
if (!Number.isFinite(budget) || budget < 10000 || budget > 300000) throw new Error('Case budget must be 10–300 seconds')
const origin = 'http://127.0.0.1:18761'
const occupied = () => new Promise(resolve => {
  const socket = createConnection({ host: '127.0.0.1', port: 18761 })
  socket.once('connect', () => { socket.destroy(); resolve(true) })
  socket.once('error', () => resolve(false))
  socket.setTimeout(1000, () => { socket.destroy(); resolve(false) })
})
if (await occupied()) throw new Error('Refusing to use an occupied fixture port; stop only your owned fixture first')
await mkdir(evidence, { mode: 0o700 })
const emit = value => process.stdout.write(JSON.stringify({ at: new Date().toISOString(), ...value }) + '\n')
const pause = ms => new Promise(resolve => setTimeout(resolve, ms))
const owned = new Map()
function processRows() {
  return execFileSync('/bin/ps', ['-axo', 'pid=,ppid=,pgid=,command='], { encoding: 'utf8', timeout: 3000, maxBuffer: 8 * 1024 * 1024 })
    .split('\n').flatMap(line => { const m = line.trim().match(/^(\d+)\s+(\d+)\s+(\d+)\s+(.+)$/)
      return m ? [{ pid: Number(m[1]), parent: Number(m[2]), group: Number(m[3]), command: m[4] }] : [] })
}
async function terminateOwned(child, profile = '') {
  const rows = processRows(), pids = new Set(rows.filter(row => row.pid === child.pid
    || (profile && row.command.includes('--user-data-dir=' + profile))).map(row => row.pid))
  for (let count = -1; count !== pids.size;) { count = pids.size; for (const row of rows) if (pids.has(row.parent)) pids.add(row.pid) }
  const groups = new Set(rows.filter(row => pids.has(row.pid)).map(row => row.group).filter(group => group > 1 && group !== process.pid))
  const signal = (group, name) => { try { process.kill(-group, name) } catch (error) { if (error.code !== 'ESRCH') throw error } }
  for (const group of groups) signal(group, 'SIGTERM')
  const live = () => [...new Set(processRows().filter(row => groups.has(row.group)).map(row => row.group))]
  let deadline = Date.now() + 3000
  while (live().length && Date.now() < deadline) await pause(100)
  for (const group of live()) signal(group, 'SIGKILL')
  deadline = Date.now() + 3000
  while (live().length && Date.now() < deadline) await pause(100)
  return { signalled_groups: [...groups], surviving_groups: live() }
}
const boundedExit = (promise, ms) => new Promise(resolve => {
  const timer = setTimeout(() => resolve({ error: 'owned child did not exit within cleanup bound' }), ms)
  promise.then(value => { clearTimeout(timer); resolve(value) }, error => { clearTimeout(timer); resolve({ error: error.message }) })
})
let interrupted = false
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => {
  interrupted = true
  Promise.allSettled([...owned].map(([child, profile]) => terminateOwned(child, profile)))
    .finally(() => { process.exitCode = 130 })
})
const load = async file => { try { return JSON.parse(await readFile(file, 'utf8')) } catch { return null } }
const results = []
for (const surface of surfaces) {
  const folder = path.join(evidence, surface)
  await mkdir(folder)
  const serverLog = await open(path.join(folder, 'server.log'), 'wx')
  const server = spawn(path.join(repo, 'backend/.venv/bin/python'), ['-I', '-S', '-B',
    path.join(repo, 'backend/tests/fixtures/translation_browser_server.py'), '--evidence-dir', path.join(folder, 'runtime'),
    '--static-dir', staticDir, '--port', '18761'], { cwd: repo, detached: true, stdio: ['ignore', serverLog.fd, serverLog.fd] })
  owned.set(server, '')
  let serverExited = false
  const serverExit = new Promise(resolve => { server.once('exit', (code, signal) => { serverExited = true; resolve({ code, signal }) }); server.once('error', error => { serverExited = true; resolve({ error: error.message }) }) })
  let ready = false, problem = null, browserExit = null, browserResult = null, forcedShutdown = false
  emit({ surface, phase: 'starting-fixture', pid: server.pid })
  try {
    const deadline = Date.now() + 45000
    while (Date.now() < deadline && !serverExited) {
      try {
        const response = await fetch(origin + '/__fixture/receipt', { redirect: 'error', signal: AbortSignal.timeout(1000) })
        const receipt = await response.json()
        if (response.ok && receipt.guard?.pid === server.pid) { ready = true; break }
      } catch {}
      await pause(200)
    }
    if (!ready) throw new Error('Owned fixture did not become ready; inspect server.log')
    const log = await open(path.join(folder, 'browser.log'), 'wx')
    const browser = spawn(process.execPath, [path.join(here, 'run.mjs'), '--evidence-dir', path.join(folder, 'browser'),
      '--surfaces', surface, '--budget-ms', String(budget - 5000),
      ...(arg('--browser-executable') ? ['--browser-executable', arg('--browser-executable')] : [])], { cwd: repo, detached: true,
      stdio: ['ignore', log.fd, log.fd], env: { ...process.env, DEBUG: 'pw:browser' } })
    const profile = path.join(folder, 'browser/chromium-profile')
    owned.set(browser, profile)
    let timedOut = false, cleanup = null
    const browserDone = new Promise(resolve => {
      browser.once('exit', (code, signal) => resolve({ code, signal }))
      browser.once('error', error => resolve({ error: error.message }))
    })
    let outcome = await boundedExit(browserDone, budget)
    if (outcome.error === 'owned child did not exit within cleanup bound') {
      timedOut = true; cleanup = await terminateOwned(browser, profile); outcome = await boundedExit(browserDone, 5000)
    }
    owned.delete(browser)
    await log.close()
    browserExit = { ...outcome, timed_out: timedOut, cleanup }
    browserResult = await load(path.join(folder, 'browser/result.json'))
    if (timedOut) throw new Error('Bounded browser case timed out; no later surface shares its process')
  } catch (error) { problem = error.message }
  finally {
    if (ready && !serverExited) {
      await fetch(origin + '/__fixture/control', { method: 'POST', redirect: 'error', signal: AbortSignal.timeout(5000),
        headers: { 'content-type': 'application/json' }, body: JSON.stringify({ action: 'shutdown' }) }).catch(() => {})
    }
    const stopDeadline = Date.now() + 30000
    while (!serverExited && Date.now() < stopDeadline) await pause(100)
    let serverCleanup = null
    if (!serverExited) { forcedShutdown = true; serverCleanup = await terminateOwned(server) }
    const stopped = await boundedExit(serverExit, 5000)
    owned.delete(server)
    await serverLog.close()
    const guard = await load(path.join(folder, 'runtime/completed.json'))
    const api = await load(path.join(folder, 'runtime/browser-server-receipt.json'))
    const record = { surface, passed: !problem && browserExit?.code === 0 && browserResult?.passed === true
      && stopped.code === 0 && !forcedShutdown && guard?.shutdown_complete === true && guard?.source_drift?.length === 0
      && browserResult?.source_drift?.length === 0 && browserResult?.build_source_drift?.length === 0,
      error: problem, browser_exit: browserExit, server_exit: stopped, forced_shutdown: forcedShutdown,
      browser_result: `${surface}/browser/result.json`, guard_receipt: `${surface}/runtime/completed.json`,
      server_cleanup: serverCleanup, server_receipt: `${surface}/runtime/browser-server-receipt.json`, cases: browserResult?.cases || [],
      downloads: browserResult?.downloads || [], source_drift: guard?.source_drift || [],
      shutdown: api?.shutdown || null }
    results.push(record)
    await writeFile(path.join(evidence, 'suite.json'), JSON.stringify({ complete: false, results }, null, 2) + '\n')
    emit({ surface, phase: 'complete', passed: record.passed, error: record.error,
      browser_error: record.cases.find(c => !c.passed)?.error || browserResult?.fatal?.message })
  }
  if (interrupted) throw new Error('Suite interrupted; owned process groups were stopped')
  if (await occupied()) throw new Error('Fixture listener survived teardown; refusing to start another server')
}
const result = { schema: 'translation-browser-per-surface/v1', complete: true,
  passed: results.length === surfaces.length && results.every(row => row.passed),
  acceptance_ready: surfaces.length === all.length && results.every(row => row.passed),
  independent_server_and_browser_per_surface: true, origin, static_dir: staticDir, results }
await writeFile(path.join(evidence, 'suite.json'), JSON.stringify(result, null, 2) + '\n')
emit({ passed: result.passed, acceptance_ready: result.acceptance_ready, evidence })
process.exitCode = result.passed ? 0 : 1
