import { spawn } from 'node:child_process'
import { mkdir, readFile, writeFile, open } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const arg = name => { const i = process.argv.indexOf(name); return i < 0 ? undefined : process.argv[i + 1] }
const requested = arg('--evidence-dir')
if (!requested) throw new Error('Usage: node frontend/tests/browser/run-isolated.mjs --evidence-dir /private/tmp/<new-suite> [--surfaces dossier,forecast,...] [--budget-ms 600000]')
const directory = path.resolve(requested)
await mkdir(directory, { mode: 0o700 })
const surfaces = (arg('--surfaces') || 'dossier,forecast,graph,oasis,world-state,world,record').split(',')
const known = new Set(['dossier', 'forecast', 'graph', 'oasis', 'world-state', 'world', 'record'])
if (surfaces.some(surface => !known.has(surface)) || new Set(surfaces).size !== surfaces.length) throw new Error('Invalid or duplicate surface')
const started = Date.now(), budget = Number(arg('--budget-ms') || 600000), results = []
const runner = fileURLToPath(new URL('./run.mjs', import.meta.url))
for (const surface of surfaces) {
  const remaining = budget - (Date.now() - started)
  if (remaining <= 0) { results.push({ surface, passed: false, not_run: true, reason: 'suite budget exhausted' }); continue }
  const caseBudget = Math.min(150000, remaining)
  const childDirectory = path.join(directory, surface)
  const log = await open(path.join(directory, `${surface}.log`), 'wx')
  const args = [runner, '--evidence-dir', childDirectory, '--surfaces', surface, '--budget-ms', String(Math.max(1000, caseBudget - 5000))]
  if (process.argv.includes('--smoke')) args.push('--smoke')
  process.stdout.write(JSON.stringify({ surface, phase: 'starting', evidence: childDirectory }) + '\n')
  const child = spawn(process.execPath, args, { stdio: ['ignore', log.fd, log.fd], env: { ...process.env, DEBUG: 'pw:browser' } })
  let timedOut = false
  const timer = setTimeout(() => { timedOut = true; child.kill('SIGTERM') }, caseBudget)
  const outcome = await new Promise(resolve => {
    child.once('error', error => resolve({ error: error.message }))
    child.once('exit', (code, signal) => resolve({ code, signal }))
  })
  clearTimeout(timer)
  await log.close()
  let result = null
  try { result = JSON.parse(await readFile(path.join(childDirectory, 'result.json'), 'utf8')) } catch {}
  const record = { surface, ...outcome, timed_out: timedOut, passed: outcome.code === 0 && result?.passed === true,
    result_file: result ? `${surface}/result.json` : null, cases: result?.cases || [], fatal: result?.fatal || null,
    page_error_count: result?.page_error_count, source_drift: result?.source_drift, build_source_drift: result?.build_source_drift }
  results.push(record)
  await writeFile(path.join(directory, 'isolated-results.json'), JSON.stringify({ schema: 'translation-browser-isolated/v1', complete: false, results }, null, 2) + '\n')
  process.stdout.write(JSON.stringify({ surface, passed: record.passed, timed_out: timedOut, fatal: record.fatal }) + '\n')
}
const result = { schema: 'translation-browser-isolated/v1', complete: true, elapsed_ms: Date.now() - started,
  passed: results.length === surfaces.length && results.every(record => record.passed), results,
  acceptance_ready: surfaces.length === 7 && !process.argv.includes('--smoke') && results.every(record => record.passed
    && record.source_drift?.length === 0 && record.build_source_drift?.length === 0),
  note: 'Each surface ran in a new process and Chrome profile. A failure cannot close a later surface browser. No failed or unrun case is waived.' }
await writeFile(path.join(directory, 'isolated-results.json'), JSON.stringify(result, null, 2) + '\n')
process.stdout.write(JSON.stringify({ passed: result.passed, acceptance_ready: result.acceptance_ready, evidence: directory }) + '\n')
process.exitCode = result.passed ? 0 : 1
