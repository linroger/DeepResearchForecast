import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'

import * as i18n from '../src/i18n.js'
import * as officialData from '../src/utils/officialData.js'
import { compileSfc } from './sfcHarness.mjs'

// Renders the real SettingsMenu.vue after running its data-source test against the
// REAL live POST /api/settings/data-sources/test response (T's live probe of the six
// official-data MCP servers; key names and states only, never values).
const PROBE = JSON.parse(readFileSync(new URL('./fixtures/official/data_sources_probe.live.json', import.meta.url), 'utf8'))
const buildSettings = compileSfc(new URL('../src/components/research/SettingsMenu.vue', import.meta.url))

async function render(testDataSources, locale = 'en') {
  i18n.locale.value = locale
  const calls = []
  const settings = buildSettings({
    vue,
    '../../api/settings': {
      getLlmSettings: async () => ({ success: true, data: { providers: [], current: '' } }),
      setLlmSettings: () => { throw new Error('Unexpected API call') },
      testLlmSettings: () => { throw new Error('Unexpected API call') },
      testDataSources: () => { calls.push('probe'); return testDataSources() },
    },
    '../../api/research': { runResolutionMonitor: () => { throw new Error('Unexpected API call') } },
    '../../utils/officialData': officialData,
    '../../i18n': i18n,
  })
  let state = null
  const setup = settings.setup
  settings.setup = async (props, ctx) => {
    state = setup(props, ctx)
    await state.runDataSourceTest()
    return state
  }
  const html = await renderToString(vue.createSSRApp(settings))
  i18n.locale.value = 'en'
  const text = html.replace(/<!--[^]*?-->/g, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
  return { html, text, calls, state }
}

test('the data-source card lists every provider with state, latency, detail and key names', async () => {
  const { html, text, calls, state } = await render(async () => PROBE)
  assert.deepEqual(calls, ['probe'])
  assert.equal(state.dataTesting.value, false)
  assert.match(text, /Official data sources/)
  assert.match(text, /4 OK · 2 Degraded · 47\.01 s/)
  assert.equal((html.match(/class="ds-row"/g) || []).length, 6)
  assert.match(text, /FRED OK 1\.66 s MCP handshake ok \(3 tools, ready in 0\.403 s\); sample fred:UNRATE: 118 observations/)
  assert.match(text, /BLS OK 0\.35 s .*handshake only: no BLS data request/)
  assert.match(text, /IMF Degraded 44\.95 s .*DATA_UNAVAILABLE\[timeout\]/)
  assert.match(text, /World Bank Data360 Degraded/)
  assert.match(text, /US Gov Open Data OK 4\.42 s .* EIA_API_KEY: set BEA_API_KEY: set CENSUS_API_KEY: not set/)
  assert.ok(html.includes('class="ds-state st-degraded"'))
  assert.ok(html.includes('class="test-result warn"'))
})

test('Chinese labels and the busy (409) and disabled outcomes', async () => {
  const zh = await render(async () => PROBE, 'zh')
  assert.match(zh.text, /官方数据源/)
  assert.match(zh.text, /4 正常 · 2 降级 · 47\.01 s/)
  assert.match(zh.text, /CENSUS_API_KEY: 未设置/)

  const busy = await render(async () => {
    throw Object.assign(new Error('a data-source test is already running; retry when it finishes'),
      { response: { status: 409 } })
  })
  assert.match(busy.text, /✗ A data-source test is already running; retry when it finishes/)
  assert.equal((busy.html.match(/class="ds-row"/g) || []).length, 0)
  assert.equal(busy.state.dataTesting.value, false)

  const disabled = await render(async () => ({ success: true, data: {
    enabled: false, deadline_s: 75, elapsed_s: 0,
    providers: Object.fromEntries(['fred', 'bls', 'bis', 'imf', 'wb', 'usgov'].map(name => [name,
      { state: 'disabled', detail: 'DATA_SOURCES_ENABLED=false', latency_s: 0, keys: {} }])),
  } }))
  assert.match(disabled.text, /Official data is disabled \(DATA_SOURCES_ENABLED=false\)/)
  assert.equal((disabled.html.match(/class="ds-state st-disabled"/g) || []).length, 6)

  const failed = await render(async () => { throw new Error('Network Error') })
  assert.match(failed.text, /✗ Network Error/)
})

test('the probe summary lives in a polite live region that exists before the result arrives', async () => {
  // Screen readers announce changes inside an aria-live region only when the region is
  // already in the DOM; a region inserted together with its text may stay silent.
  i18n.locale.value = 'en'
  const idle = buildSettings({
    vue,
    '../../api/settings': {
      getLlmSettings: async () => ({ success: true, data: { providers: [], current: '' } }),
      setLlmSettings: () => { throw new Error('Unexpected API call') },
      testLlmSettings: () => { throw new Error('Unexpected API call') },
      testDataSources: () => { throw new Error('Unexpected API call') },
    },
    '../../api/research': { runResolutionMonitor: () => { throw new Error('Unexpected API call') } },
    '../../utils/officialData': officialData,
    '../../i18n': i18n,
  })
  const uncommented = html => html.replace(/<!--[^]*?-->/g, '')
  const before = uncommented(await renderToString(vue.createSSRApp(idle)))
  const region = /Test data sources\s*<\/button><span[^>]*aria-live="polite"[^>]*>\s*<\/span>/
  assert.match(before, region)

  const { html } = await render(async () => PROBE)
  assert.match(uncommented(html), /Test data sources\s*<\/button><span[^>]*class="test-result warn"[^>]*aria-live="polite"[^>]*>\s*4 OK · 2 Degraded · 47\.01 s\s*<\/span>/)
})

test('the card states the endpoint worst case that settings.probe_data_sources documents', async () => {
  // _DATA_TEST_MAX_SECONDS = probe budget + worker grace + private-hub close timeout + its
  // kill/join overhead; the hint must not promise a shorter wait than the endpoint can take.
  const source = readFileSync(new URL('../../backend/app/api/settings.py', import.meta.url), 'utf8')
  const seconds = name => Number(source.match(new RegExp(`^${name} = ([0-9.]+)`, 'm'))[1])
  const bound = ['_DATA_TEST_DEADLINE_SECONDS', '_DATA_TEST_GRACE_SECONDS', '_DATA_TEST_CLOSE_SECONDS',
    '_DATA_HUB_CLOSE_OVERHEAD_SECONDS'].reduce((sum, name) => sum + seconds(name), 0)
  const en = await render(async () => PROBE)
  assert.match(en.text, new RegExp(`takes up to about ${bound} s\\.`))
  const zh = await render(async () => PROBE, 'zh')
  assert.match(zh.text, new RegExp(`最长约 ${bound} 秒。`))
})
