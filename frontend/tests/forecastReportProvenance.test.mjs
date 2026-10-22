import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'

import * as binaryForecasts from '../src/utils/binaryForecasts.js'
import * as i18n from '../src/i18n.js'
import * as markdown from '../src/utils/markdown.js'
import * as officialData from '../src/utils/officialData.js'
import * as reportLanguages from '../src/utils/reportLanguages.js'
import * as vizManifest from '../src/utils/vizManifest.js'
import { compileSfc } from './sfcHarness.mjs'

// ADR 0003 (design §3.6, slice S2): the real ForecastReport.vue + BinaryForecastTable.vue
// through Vue's server renderer.  The provenance legend heads the report body; the one
// fenced simulation bridge (sim_provenance.BRIDGE_START / BRIDGE_END) renders as a shaded
// box through the existing markdown renderer; the record anchor card appears only with
// `simulation_record_ref`; the binary table's footnote names the policy.  Without any of
// these payload fields the report renders exactly as before.
const fixture = name => JSON.parse(readFileSync(new URL(`./fixtures/official/${name}`, import.meta.url), 'utf8'))
const BINARIES = fixture('binary_forecasts.en_report.json').binary_forecasts
const REPORT_ID = 'report_provenance'

const buildReport = compileSfc(new URL('../src/components/research/ForecastReport.vue', import.meta.url))
const buildTable = compileSfc(new URL('../src/components/research/BinaryForecastTable.vue', import.meta.url))
const settle = () => new Promise(resolve => setImmediate(resolve))
const count = (html, needle) => html.split(needle).length - 1
const decode = s => s.replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
const text = html => decode(html.replace(/<!--[^]*?-->/g, '').replace(/<[^>]+>/g, ' ')).replace(/\s+/g, ' ')

// The markers and the bridge title come from the backend constants module (T9's single source).
const PROVENANCE = readFileSync(new URL('../../backend/app/services/sim_provenance.py', import.meta.url), 'utf8')
function pyConst(name) {
  const m = PROVENANCE.match(new RegExp(`^${name}: Final = (\\([^]*?\\)|"[^"\\n]*")`, 'm'))
  assert.ok(m, `${name} not found in sim_provenance.py`)
  return [...m[1].matchAll(/"((?:[^"\\]|\\.)*)"/g)].map(x => x[1]).join('')
}
const BRIDGE_START = pyConst('BRIDGE_START')
const BRIDGE_END = pyConst('BRIDGE_END')
const BRIDGE_TITLE_EN = pyConst('BRIDGE_TITLE_EN')
const SIM_BANNER_EN = pyConst('SIM_BANNER_EN')

const PLAIN_MD = '# Outlook\n\nBody text [S1].\n\n## Scenarios\n\nMore text [S1].\n\n## References\n\n- [S1] Source one\n'
const BRIDGE_MD = [
  BRIDGE_START,
  `## ${BRIDGE_TITLE_EN}`,
  '',
  SIM_BANNER_EN,
  '',
  '| Scenario | Simulated share | Report probability |',
  '|---|---|---|',
  '| Truce holds | 44% | 40% |',
  '',
  'Brent at $26 per barrel stayed anchored; the probabilities in this report were not changed by the exercise (policy: diagnostic_only).',
  BRIDGE_END,
].join('\n')
const BRIDGED_MD = `# Outlook\n\nBody text [S1].\n\n## Scenarios\n\nMore text [S1].\n\n${BRIDGE_MD}\n\n## References\n\n- [S1] Source one\n`

async function render({ locale = 'en', markdownContent = PLAIN_MD, extra = {}, forecast = null, onOpen = null } = {}) {
  i18n.locale.value = locale
  const unexpected = name => () => { throw new Error(`Unexpected API call: ${name}`) }
  const api = {
    getReport: async id => ({ success: true, data: {
      report_id: id, status: 'completed', markdown_content: markdownContent,
      translation_status: { source_lang: locale }, ...extra,
    } }),
    getVizManifest: async () => ({ success: true, data: [] }),
    getForecast: async () => ({ success: true, data: { forecast } }),
    getReportOfficialData: async () => ({ success: true, data: { available: false } }),
    getSectionsPartial: unexpected('getSectionsPartial'),
    getReportTranslationMd: unexpected('getReportTranslationMd'),
    requestReportTranslation: unexpected('requestReportTranslation'),
    getReportTranslationStatus: unexpected('getReportTranslationStatus'),
    reportMarkdownUrl: id => `/api/report/${id}/download`,
    reportPdfUrl: id => `/api/report/${id}/pdf`,
    reportAssetUrl: (id, rel) => `/api/report/${id}/${rel}`,
  }
  const table = buildTable({ vue, '../../utils/binaryForecasts': binaryForecasts, '../../i18n': i18n })
  const report = buildReport({
    vue,
    '../../api/report': api,
    './BinaryForecastTable.vue': { default: table },
    '../../utils/markdown': markdown,
    '../../utils/vizManifest': vizManifest,
    '../../utils/reportLanguages': reportLanguages,
    '../../utils/officialData': officialData,
    '../../utils/saveTextFile': { saveTextFile: () => {} },
    '../../i18n': i18n,
  })
  let state = null
  const setup = report.setup
  report.setup = async (props, ctx) => {
    state = setup(props, ctx)
    await state.load()
    for (let i = 0; i < 4; i += 1) await settle()
    return state
  }
  const rootProps = { reportId: REPORT_ID }
  if (onOpen) rootProps.onOpenSimulationRecord = onOpen
  const html = (await renderToString(vue.createSSRApp(report, rootProps))).replace(/<!--[^]*?-->/g, '')
  i18n.locale.value = 'en'
  return { html, state }
}

test('the provenance legend heads the report body; without markers or a record ref nothing else is added', async () => {
  const { html } = await render()
  assert.equal(count(html, 'class="prov-legend"'), 1)
  assert.ok(html.indexOf('class="prov-legend"') < html.indexOf('class="md-body"'))
  assert.match(text(html), /Observed \[S#\] Forecast \(authors’ judgement\) Simulated \(model exercise, not evidence\)/)
  assert.ok(html.includes('aria-label="Provenance legend"'))
  assert.equal(count(html, 'class="sim-bridge"'), 0)
  assert.equal(count(html, 'class="sim-record-anchor"'), 0)
  assert.equal(count(html, 'class="bft-foot"'), 0, 'no binary table, no footnote')
  // the citation machinery is untouched
  assert.ok(count(html, 'href="#ref-S1"') >= 2)
  assert.equal(count(html, 'id="ref-S1"'), 1)
  assert.equal(count(html, 'class="nav-item"'), 3)
})

test('the fenced bridge renders as one shaded box through the markdown renderer, in place', async () => {
  const { html, state } = await render({ markdownContent: BRIDGED_MD })
  assert.equal(count(html, 'class="sim-bridge"'), 1)
  assert.equal(count(html, 'data-record-class="simulated"'), 1)
  const box = html.match(/<section class="sim-bridge"[^]*?<\/section>/)[0]
  // the eyebrow labels the box; the inner markdown is rendered (heading, table, paragraph), not escaped
  assert.match(text(box), /Scenario simulation · simulated record: not evidence, not an input to any probability/)
  assert.ok(box.includes(`<h2 id="${markdown.slugify(BRIDGE_TITLE_EN)}" class="md-h md-h2">${BRIDGE_TITLE_EN}</h2>`))
  assert.ok(box.includes('<table'))
  assert.match(text(box), /Truce holds 44% 40%/)
  assert.ok(text(box).includes(SIM_BANNER_EN))
  assert.match(text(box), /Brent at \$26 per barrel stayed anchored/)              // `$` survives the slot replacement
  // the markers never reach the page; the box sits where the markers were
  assert.equal(count(html, 'sim-bridge:start'), 0)
  assert.equal(count(html, 'sim-bridge:end'), 0)
  assert.equal(count(html, 'SIMBRIDGESLOT'), 0)
  assert.ok(html.indexOf('More text') < html.indexOf('class="sim-bridge"'))
  assert.ok(html.indexOf('class="sim-bridge"') < html.indexOf('id="references"'))
  // the surrounding document still resolves its citations and lists every heading, the bridge's included
  assert.ok(count(html, 'href="#ref-S1"') >= 2)
  assert.equal(count(html, 'id="ref-S1"'), 1)
  assert.equal(count(html, 'class="nav-item"'), 4)
  assert.ok(state.bridgeSplit.value && state.bridgeSplit.value.inner.includes(BRIDGE_TITLE_EN))
  // the inner content is not rendered a second time outside the box
  assert.equal(count(html, BRIDGE_TITLE_EN), 2, 'once in the nav, once in the box')
})

test('a record reference adds the anchor card, whose button asks the parent for the Simulation tab', async () => {
  const opened = []
  const sha = 'a1b2c3d4'.repeat(8)
  const { html, state } = await render({
    extra: { simulation_record_ref: { sha256: sha, url: '/api/simulation/sim_1/record' } },
    onOpen: payload => opened.push(payload),
  })
  assert.equal(count(html, 'class="sim-record-anchor"'), 1)
  assert.match(text(html), /Scenario simulation after-action record passed its gate \(simulated record: not evidence, not an input to any probability\) SHA-256 a1b2c3d4…c3d4 Open the record in the Simulation tab →/)
  assert.ok(html.includes(`title="${sha}"`))
  state.openSimulationRecord()
  assert.deepEqual(opened, [{ sha256: sha, url: '/api/simulation/sim_1/record' }])
  // a malformed or empty reference renders no card
  for (const bad of ['nope', {}, { sha256: '' }, null, ['x']]) {
    const r = await render({ extra: { simulation_record_ref: bad } })
    assert.equal(count(r.html, 'class="sim-record-anchor"'), 0, JSON.stringify(bad))
  }
})

test('the binary table carries the research-only footnote with the policy from the payload', async () => {
  const forecast = { binary_forecasts: BINARIES }
  let r = await render({ forecast, extra: { forecast_effect: 'diagnostic_only' } })
  assert.equal(count(r.html, 'class="bft-foot"'), 1)
  assert.match(text(r.html), /Probabilities come from research evidence only \(policy: diagnostic_only\)/)
  // absent field → the footnote says the policy is not recorded; it never assumes one (S2 review)
  r = await render({ forecast })
  assert.match(text(r.html), /The forecast policy is not recorded for this run/)
  assert.doesNotMatch(text(r.html), /research evidence only/)
  // the fixture-only policy that let simulation signals into extraction says so
  r = await render({ forecast, extra: { forecast_effect: 'legacy_prompt' } })
  assert.match(text(r.html), /legacy_prompt: simulation signals entered probability extraction/)
  assert.doesNotMatch(text(r.html), /research evidence only/)
  // another policy, and the forecast.json simulation_bridge carrier (design §3.3) as the fallback source
  r = await render({ forecast, extra: { forecast_effect: 'no_update' } })
  assert.match(text(r.html), /\(policy: no_update\)/)
  r = await render({ forecast: { ...forecast, simulation_bridge: { sha256: 'x', forecast_effect: 'no_update', probabilityEvidence: false } } })
  assert.match(text(r.html), /\(policy: no_update\)/)
  assert.equal(r.state.forecastEffect.value, 'no_update')
  // no binaries → no table → no footnote
  r = await render({ forecast: { binary_forecasts: [] }, extra: { forecast_effect: 'diagnostic_only' } })
  assert.equal(count(r.html, 'class="bft-foot"'), 0)
})

test('the Chinese interface words the legend, the bridge label and the footnote in Chinese', async () => {
  const { html } = await render({
    locale: 'zh', markdownContent: BRIDGED_MD, forecast: { binary_forecasts: BINARIES },
    extra: { forecast_effect: 'diagnostic_only', simulation_record_ref: { sha256: 'b'.repeat(64) } },
  })
  const body = text(html)
  assert.match(body, /观察事实 \[S#\] 预测（作者判断） 模拟（模型推演，非证据）/)
  assert.match(body, /情景模拟 · 模拟记录：非证据，未进入任何概率/)
  assert.match(body, /概率仅来自研究证据（策略：diagnostic_only）/)
  assert.match(body, /情景模拟事后记录已通过门禁（模拟记录：非证据，未进入任何概率） SHA-256 bbbbbbbb…bbbb 在模拟标签页查看记录 →/)
  assert.ok(html.includes('aria-label="来源图例"'))
})

test('splitMarkedBlock finds the first fenced block and refuses a missing or inverted pair', () => {
  const split = markdown.splitMarkedBlock('a\n<!-- s -->\nmid\n<!-- e -->\nz', '<!-- s -->', '<!-- e -->')
  assert.deepEqual(split, { before: 'a\n', inner: '\nmid\n', after: '\nz' })
  assert.equal(markdown.splitMarkedBlock('no markers', '<!-- s -->', '<!-- e -->'), null)
  assert.equal(markdown.splitMarkedBlock('<!-- e -->\nx\n<!-- s -->', '<!-- s -->', '<!-- e -->'), null)
  assert.equal(markdown.splitMarkedBlock('<!-- s -->\nopen ended', '<!-- s -->', '<!-- e -->'), null)
  assert.equal(markdown.splitMarkedBlock('', '<!-- s -->', '<!-- e -->'), null)
  assert.equal(markdown.splitMarkedBlock('x', '', '<!-- e -->'), null)
  // the real markers are comments the renderer already drops, so a bridge-less render is unchanged
  assert.equal(markdown.renderMarkdown(`${BRIDGE_START}\n\nText\n\n${BRIDGE_END}`), '<p>Text</p>')
})


test('an unclosed code fence before the bridge never leaks the slot token; the labelled box still renders once (S2 review)', async () => {
  const md = [
    '# Title', '', 'Intro with a citation [S1].', '', '```', 'an unclosed fence', '',
    BRIDGE_START, `## ${BRIDGE_TITLE_EN}`, '', SIM_BANNER_EN, '', BRIDGE_END, '',
    '## References', '', '1. [S1] Source one. https://example.com/one',
  ].join('\n')
  const { html } = await render({ markdownContent: md })
  assert.equal(count(html, 'SIMBRIDGESLOT'), 0)
  assert.equal(count(html, 'class="sim-bridge"'), 1)
  assert.equal(count(html, 'sim-bridge:start'), 0)
  assert.ok(text(html).includes(SIM_BANNER_EN))
})
