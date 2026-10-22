import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'

import * as i18n from '../src/i18n.js'
import { compileSfc } from './sfcHarness.mjs'

// ADR 0003 (design §3.6): the run stage is labelled with the one reader-facing simulation
// name (sim_provenance.SIM_LABEL_* as a title) and its sub-label keeps the OASIS mention.
const build = compileSfc(new URL('../src/components/research/StageTimeline.vue', import.meta.url))
const text = html => html.replace(/<!--[^]*?-->/g, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')

const PROVENANCE = readFileSync(new URL('../../backend/app/services/sim_provenance.py', import.meta.url), 'utf8')
function pyConst(name) {
  const m = PROVENANCE.match(new RegExp(`^${name}: Final = (\\([^]*?\\)|"[^"\\n]*")`, 'm'))
  assert.ok(m, `${name} not found in sim_provenance.py`)
  return [...m[1].matchAll(/"((?:[^"\\]|\\.)*)"/g)].map(x => x[1]).join('')
}
const LABEL_EN = pyConst('SIM_LABEL_EN')
const LABEL_ZH = pyConst('SIM_LABEL_ZH')
const TITLE_EN = LABEL_EN.charAt(0).toUpperCase() + LABEL_EN.slice(1)

async function render(lang) {
  i18n.locale.value = lang
  const component = build({ vue, '../../i18n': i18n })
  const stages = { research: { status: 'completed' }, run: { status: 'running', progress: 40, message: 'round 4 of 9' } }
  const html = await renderToString(vue.createSSRApp(component, { stages, currentStage: 'run', mode: 'full', globalProgress: 70 }))
  i18n.locale.value = 'en'
  return text(html)
}

test('the run stage reads "Scenario simulation" with the OASIS engine in its sub-label', async () => {
  const body = await render('en')
  assert.equal(TITLE_EN, 'Scenario simulation')
  // once in the header's current-stage line, once in the row
  assert.equal(body.split(TITLE_EN).length - 1, 2)
  assert.match(body, /05 Scenario simulation Running Multi-agent scenario exercise · OASIS; simulated output, not evidence/)
  assert.doesNotMatch(body, /Crowd simulation/)
  assert.match(body, /06 Forecast report/)
})

test('the Chinese label is the SIM_LABEL_ZH constant and keeps OASIS', async () => {
  const body = await render('zh')
  assert.equal(LABEL_ZH, '情景模拟')
  assert.equal(body.split(LABEL_ZH).length - 1, 2)
  assert.match(body, /05 情景模拟 进行中 OASIS 多智能体情景推演；模拟输出，非证据/)
})

test('the run stage label is written as one L() call pinned to SIM_LABEL_* (T9 reads it back)', () => {
  const source = readFileSync(new URL('../src/components/research/StageTimeline.vue', import.meta.url), 'utf8')
  assert.ok(source.includes(`L('${LABEL_ZH}', '${TITLE_EN}')`), 'run stage label drifted from SIM_LABEL_*')
})
