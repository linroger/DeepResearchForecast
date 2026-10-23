import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { isSimulationRecord } from '../src/utils/simRecord.js'

const source = readFileSync(new URL('../src/api/simulation.js', import.meta.url), 'utf8')
const fixture = JSON.parse(readFileSync(new URL('./fixtures/sim/simulation_record.en.json', import.meta.url), 'utf8'))
const buildApi = service => new Function('service', 'isSimulationRecord', source.replace("import service from './index'", '').replace("import { isSimulationRecord } from '../utils/simRecord'", '').replaceAll('export const ', 'const ')
  + '\nreturn { fetchRecord };')(service, isSimulationRecord)

test('record API reads bare and success-envelope records and preserves cancellation and identity', async () => {
  for (const wrapped of [true, false]) {
    const calls = []
    const api = buildApi({ get: async (...args) => { calls.push(args); return wrapped ? { success: true, data: fixture } : fixture } })
    const options = { signal: new AbortController().signal, timeout: 20000 }
    const result = await api.fetchRecord(fixture.simulation_id, options)
    assert.equal(result.record, fixture)
    assert.equal(result.status, 200)
    assert.equal(result.publicationStatus, 'passed')
    assert.deepEqual(calls, [[`/api/simulation/${fixture.simulation_id}/record`, options]])
  }
})

test('record API normalizes absence and audit conflicts while retaining the pending-audit distinction', async () => {
  for (const [status, publication_status] of [[404, 'absent'], [409, 'not_audited'], [409, 'failed'], [409, 'stale_audit']]) {
    const api = buildApi({ get: async () => { throw { response: { status, data: { publication_status } } } } })
    assert.deepEqual(await api.fetchRecord('sim/a'), { record: null, status, publicationStatus: publication_status })
  }
})

test('record API rejects wrong-run, malformed and unsuccessful data instead of asserting a passed gate', async () => {
  for (const data of [{}, [], { success: false, data: fixture }, { ...fixture, simulation_id: 'wrong' },
    { ...fixture, record_class: 'observed' }, { ...fixture, periods: null }]) {
    const api = buildApi({ get: async () => data })
    await assert.rejects(api.fetchRecord(fixture.simulation_id), /Invalid simulation record/)
  }
  const failure = new Error('timeout')
  const api = buildApi({ get: async () => { throw failure } })
  await assert.rejects(api.fetchRecord('sim/a'), error => error === failure)
})
