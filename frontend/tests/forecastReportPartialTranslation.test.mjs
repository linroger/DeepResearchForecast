import assert from 'node:assert/strict'
import test from 'node:test'
import { createHash } from 'node:crypto'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'

import * as translationObserver from '../src/composables/useTranslationJob.js'
import * as forecastTranslationAdapter from '../src/utils/forecastTranslationAdapter.js'
import * as binaryForecasts from '../src/utils/binaryForecasts.js'
import * as i18n from '../src/i18n.js'
import * as markdown from '../src/utils/markdown.js'
import * as officialData from '../src/utils/officialData.js'
import * as reportLanguages from '../src/utils/reportLanguages.js'
import * as vizManifest from '../src/utils/vizManifest.js'
import { compileSfc } from './sfcHarness.mjs'

// Drives the real ForecastReport.vue through Vue's server renderer with the payload the
// backend publishes for a partial translation (GET /api/report/<id>: translation_status
// partial / can_update, translation.verbatim_chunks — FILTER-SAFE). The banner, its list
// of kept passages and the retry button must appear. Retry resumes pending work
// without force; only the separate explicit refresh regenerates a publication.
const REPORT_ID = 'report_partial_zh'
const SOURCE_SHA = 'a'.repeat(64)
const TARGET_MD = '# 展望\n\n正文。\n'
const TARGET_SHA = createHash('sha256').update(TARGET_MD, 'utf8').digest('hex')
const AUDIT_SHA = 'c'.repeat(64)

const buildReport = compileSfc(new URL('../src/components/research/ForecastReport.vue', import.meta.url))
const buildTable = compileSfc(new URL('../src/components/research/BinaryForecastTable.vue', import.meta.url))
const settle = () => new Promise(resolve => setImmediate(resolve))

function chunk(overrides = {}) {
  return {
    chunk: 1, heading: 'Executive Summary', reason: 'content_filter', scope: 'unit',
    detail: 'HTTP 400 code 1301', lines: 1, chars: 96,
    sample: 'The leadership of both governments signalled a readiness to extend the truce.',
    kept_lines: 1,
    ...overrides,
  }
}

const CHUNKS = [
  chunk(),
  chunk({ chunk: 4, heading: 'Scenario Analysis', reason: 'integrity', scope: 'section', lines: 3, kept_lines: 3,
    sample: 'Each scenario assumes the truce holds through June 2027.' }),
]

function translationPayload({ partial = false, outdated = false, canGenerate = true, chunks = [], residual } = {}) {
  const translation = {
    report_id: REPORT_ID, lang: 'zh', source_lang: 'en',
    path: 'full_report.zh.md', citations_path: 'citations.zh.json', final_audit_path: 'final_audit.zh.json',
    markdown_sha256: TARGET_SHA, source_markdown_sha256: SOURCE_SHA, final_audit_sha256: AUDIT_SHA,
    audit_verified: true, available: true,
    residual_source_lines: residual != null ? residual : chunks.reduce((sum, c) => sum + c.kept_lines, 0),
    translator_version: outdated ? '2026-09-29.1' : '2026-10-17.1',
    partial, verbatim_chunks: chunks,
  }
  return {
    translation_status: {
      report_id: REPORT_ID, source_lang: 'en', target_lang: 'zh', requested_lang: 'zh',
      status: 'available', available: true, can_generate: canGenerate, issues: [],
      source_markdown_sha256: SOURCE_SHA, markdown_sha256: TARGET_SHA,
      translation, partial, outdated, can_update: canGenerate && (partial || outdated),
    },
    translations: [translation],
  }
}

async function render({ locale = 'en', payload = translationPayload(), activate = 'zh', regenerate = null } = {}) {
  i18n.locale.value = locale
  const requests = []
  const unexpected = name => () => { throw new Error(`Unexpected API call: ${name}`) }
  const api = {
    getReport: async id => ({ success: true, data: {
      report_id: id, status: 'completed', markdown_content: '# Outlook\n\nBody text.\n', ...payload,
    } }),
    getVizManifest: async () => ({ success: true, data: [] }),
    getForecast: async () => ({ success: true, data: { forecast: null } }),
    getReportOfficialData: async () => ({ success: true, data: { available: false } }),
    getReportTranslationMd: async () => TARGET_MD,
    requestReportTranslation: async (...args) => {
      requests.push(args)
      if (regenerate) return regenerate(...args)
      return { success: true, data: { status: 'failed', available: false, can_generate: true, issues: ['provider rejected the retry'] } }
    },
    getReportTranslationStatus: async () => ({ data: payload.translation_status }),
    getSectionsPartial: unexpected('getSectionsPartial'),
    reportMarkdownUrl: id => `/api/report/${id}/download`,
    reportPdfUrl: id => `/api/report/${id}/pdf`,
    reportAssetUrl: (id, rel) => `/api/report/${id}/${rel}`,
  }
  const table = buildTable({ vue, '../../utils/binaryForecasts': binaryForecasts, '../../i18n': i18n })
  const report = buildReport({
    vue,
    '../../api/report': api,
    '../../composables/useTranslationJob': translationObserver,
    '../../utils/forecastTranslationAdapter': forecastTranslationAdapter,
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
    if (activate) { state.switchLang(activate); for (let i = 0; i < 4; i += 1) await settle() }
    return state
  }
  const html = await renderToString(vue.createSSRApp(report, { reportId: REPORT_ID }))
  i18n.locale.value = 'en'
  return { html, requests, state }
}

const count = (html, needle) => html.split(needle).length - 1
const text = html => html.replace(/<!--[^]*?-->/g, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')

test('a partial translation shows the note, every kept passage and a retry button', async () => {
  const { html, state } = await render({ payload: translationPayload({ partial: true, chunks: CHUNKS }) })
  assert.equal(state.activeLang.value, 'zh')
  const body = text(html)
  assert.equal(count(html, 'class="partial-translation"'), 1)
  assert.match(body, /译文不完整：2 处段落保留原文（共 4 行）/)
  assert.match(body, /点击“重试翻译”可补全待处理内容/)
  assert.match(body, /Executive Summary 段落 · 提供方内容过滤 · 1 行 The leadership of both governments signalled a readiness to extend the truce\./)
  assert.match(body, /Scenario Analysis 整节 · 完整性审计 · 3 行 Each scenario assumes the truce holds through June 2027\./)
  assert.ok(html.includes('class="ptc-sample" title="HTTP 400 code 1301"'))
  assert.equal(count(html, 'class="ptc-heading"'), 2)
  // The header offers the regenerate flow under the retry wording, with the partial tooltip.
  assert.equal(count(html, '>重试翻译</button>'), 1)
  assert.equal(count(html, 'Refresh translation'), 0)
  assert.ok(html.includes('显式重新生成译文；已发布版本保留至新版本通过审计'))
  // The banner replaces the terse residual note (same lines would otherwise be counted twice).
  assert.equal(count(html, 'line(s) kept in the source language'), 0)
})

test('the retry resumes pending work without force and surfaces its outcome', async () => {
  const { state, requests } = await render({ payload: translationPayload({ partial: true, chunks: CHUNKS }) })
  await state.generateTranslation()
  assert.deepEqual(requests, [[REPORT_ID, 'zh', false]])
  assert.equal(state.translationBusy.value, false)
  assert.equal(state.translationIssueMessage.value, 'provider rejected the retry')
  // The published partial translation stays selected and disclosed while the retry fails.
  assert.equal(state.activeLang.value, 'zh')
  assert.equal(state.translationPartial.value?.chunkCount, 2)
  assert.ok(state.translationAction.value?.retry)
})

test('the note follows the shown language; the retry stays in the header on the original', async () => {
  const { html, state } = await render({ payload: translationPayload({ partial: true, chunks: CHUNKS }), activate: null })
  assert.equal(state.activeLang.value, null)
  assert.equal(count(html, 'class="partial-translation"'), 0)
  assert.equal(count(html, '>Retry translation</button>'), 1)
})

test('a complete translation renders exactly as before', async () => {
  const complete = await render({ payload: translationPayload({ residual: 1 }) })
  assert.equal(count(complete.html, 'class="partial-translation"'), 0)
  assert.equal(count(complete.html, 'Retry translation'), 0)
  assert.equal(count(complete.html, 'Update translation'), 0)
  assert.match(text(complete.html), /1 行未能翻译，保留原文/)

  const outdated = await render({ payload: translationPayload({ outdated: true }) })
  assert.equal(count(outdated.html, 'class="partial-translation"'), 0)
  assert.equal(count(outdated.html, '>更新翻译</button>'), 1)
  assert.ok(outdated.html.includes('显式重新生成译文；已发布版本保留至新版本通过审计'))
  await outdated.state.generateTranslation(true)
  assert.deepEqual(outdated.requests, [[REPORT_ID, 'zh', true]])
})

test('the Chinese interface words the partial note and the retry button in Chinese', async () => {
  const { html } = await render({ locale: 'zh', payload: translationPayload({ partial: true, chunks: CHUNKS }) })
  const body = text(html)
  assert.match(body, /译文不完整：2 处段落保留原文（共 4 行）/)
  assert.match(body, /点击“重试翻译”可补全待处理内容/)
  assert.match(body, /Executive Summary 段落 · 提供方内容过滤 · 1 行/)
  assert.match(body, /Scenario Analysis 整节 · 完整性审计 · 3 行/)
  assert.equal(count(html, '>重试翻译</button>'), 1)
})
