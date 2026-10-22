import assert from 'node:assert/strict'
import test from 'node:test'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'
import * as i18n from '../src/i18n.js'
import * as markdown from '../src/utils/markdown.js'
import * as officialData from '../src/utils/officialData.js'
import * as researchTranslation from '../src/utils/researchTranslation.js'
import * as reportLanguages from '../src/utils/reportLanguages.js'
import * as vizManifest from '../src/utils/vizManifest.js'
import * as binaryForecasts from '../src/utils/binaryForecasts.js'
import * as sourceContext from '../src/utils/sourceContext.js'
import { compileSfc } from './sfcHarness.mjs'

// Execute the real setup, template, language methods and shared context child.
// Only API responses/timers are controlled: there is no substitute selector or UI.
const buildDossier = compileSfc(new URL('../src/components/research/DossierViewer.vue', import.meta.url))
const buildReport = compileSfc(new URL('../src/components/research/ForecastReport.vue', import.meta.url))
const buildPanel = compileSfc(new URL('../src/components/research/SourceContextPanel.vue', import.meta.url))
const buildTable = compileSfc(new URL('../src/components/research/BinaryForecastTable.vue', import.meta.url))
const panel = () => buildPanel({ vue, '../../i18n': i18n, '../../utils/sourceContext': sourceContext })
const integrationVue = { ...vue, defineAsyncComponent: () => panel() }
const settle = () => new Promise(resolve => setImmediate(resolve))
const text = html => html.replace(/<!--[^]*?-->/g, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
const fail = () => { throw new Error('Unexpected API call') }
function deferred() { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }

function context(zh = false) {
  return {
    schema_version: 1, generation_id: 'capture:G1', sealed: true,
    providers: { kalshi: { status: { state: 'ok', attempted: true } } },
    items: [{ id: 'kalshi:CPI-3', provider: 'kalshi', kind: 'market_quote', source_ref: 'S7',
      title: zh ? '2027 年 CPI 会超过 3% 吗？' : 'Will CPI exceed 3% in 2027?',
      snippet: zh ? '官方发布决定合约结果。' : 'Official releases determine the contract outcome.',
      url: 'https://example.org/CPI-3', language: 'en', published_at: '2026-10-18', retrieved_at: '2026-10-18T12:00:00Z',
      outcome: 'Yes', yes_bid: 0.4, yes_ask: 0.44, last_price: 0.41, quote_at: null,
      quote_basis: 'provider_reported_dollars_per_contract', units: 'USD_per_contract',
      probability_basis: 'last_price_dollars/1_USD_binary_payout',
      rules_primary: zh ? 'CPI 必须严格高于 3%。' : 'CPI must be strictly above 3%.',
      rules_secondary: zh ? '采用官方发布值。' : 'Use the official release.',
      eligibility: { context_only: true, anchor: false, resolution: false },
    }],
  }
}
function dossierPayload(zh = false) {
  return {
    has_report: true, sealed: true, report: zh ? '# 政策研究\n\n通过概率为 70%。[S1]' : '# Policy research\n\nApproval probability is 70%.[S1]',
    actors: {
      central_question: zh ? '委员会会通过提案吗？' : 'Will the committee approve the proposal?', as_of_date: '2026-10-22',
      actors: [{ id: 'actor:fed', name: 'Federal Reserve', type: zh ? '机构' : 'Institution', influence: 'high',
        role: zh ? '制定利率政策。' : 'Sets monetary policy.', stance: zh ? '等待数据确认。' : 'Waits for confirmation.',
        memory: zh ? '上一轮维持利率。' : 'Held rates in the prior round.' }],
      situation_brief: { current_situation: zh ? '委员会正在审议。' : 'The committee is deliberating.',
        context: zh ? '此前谈判尚未完成。' : 'Prior talks remain incomplete.', dynamics: zh ? '支持正在增加。' : 'Support is increasing.',
        fault_lines: [zh ? '各方对成本有分歧。' : 'Parties disagree about costs.'], catalysts: [zh ? '下一次会议可能促成决定。' : 'The next meeting may prompt a decision.'] },
      hot_topics: [zh ? '政策执行' : 'Policy implementation'],
      relationships: [{ source: 'Federal Reserve', target: 'Congress', type: 'INFLUENCES', strength: 0.8, basis: zh ? '预算决定可行空间。' : 'The budget constrains available options.' }],
    },
    timeline: [{ date: '2027-06-01', event: zh ? '委员会召开会议。' : 'The committee meets.' }],
    sources: [{ source_id: 'S1', title: zh ? '政策发布' : 'Policy announcement', url: 'https://example.org/source' }],
    datasets: { series: [{ series: 'fred:CPI', title: zh ? '消费者价格指数' : 'Consumer Price Index', geography: zh ? '美国' : 'United States', units: 'Index', frequency: 'M', source_id: 'S1', latest: { value: 125.4, date: '2026-09-01' }, first: '2025-01-01', last: '2026-09-01' }] },
    prediction_markets: { as_of: '2026-10-22', markets: [{ market_id: 'M1', question: zh ? '委员会会通过提案吗？' : 'Will the committee approve the proposal?', implied_yes_prob: 0.7, volume: 125, url: 'https://example.org/M1' }] },
    news_market_context: context(zh),
  }
}
function dossierHarness(t, { get, post, source = dossierPayload(), unmountCallbacks = null } = {}) {
  i18n.locale.value = 'en'
  const calls = []
  const lifecycleVue = unmountCallbacks ? { ...integrationVue, onBeforeUnmount: callback => unmountCallbacks.push(callback) } : integrationVue
  const component = buildDossier({ vue: lifecycleVue, '../../i18n': i18n, '../../utils/markdown': markdown,
    '../../utils/officialData': officialData, '../../utils/researchTranslation': researchTranslation,
    '../../utils/saveTextFile': { saveTextFile: fail }, '../../api/research': {
      editDossier: fail, getArtifact: fail, researchChartUrl: () => '', researchPdfUrl: (id, lang) => `/research/${id}${lang ? `.${lang}` : ''}.pdf`,
      getResearchTranslation: async (...args) => { calls.push(['get', ...args]); return get ? get(...args) : { data: { available: true, status: 'available', report: dossierPayload(true).report, dossier: dossierPayload(true), partial: false, structured_translation: { complete: true } } } },
      requestResearchTranslation: async (...args) => { calls.push(['post', ...args]); return post ? post(...args) : { data: { status: 'failed', issues: ['scripted failure'] } } },
    },
  })
  const props = vue.reactive({ pipelineId: 'pipe_A', dossier: source, editable: false, artifactNames: [] })
  const scope = vue.effectScope()
  const state = scope.run(() => component.setup(props, { expose() {}, emit() {} }))
  t.after(() => { state.stopTranslationPolling(); scope.stop(); i18n.locale.value = 'en' })
  return { component, props, state, calls }
}
async function renderExisting(component, props, state) {
  return renderToString(vue.createSSRApp({ ...component, setup: () => state }, props))
}

test('Research Report Mandarin spans actor, brief, timeline, relationships, markets, context and sources without changing canonical facts', async t => {
  const h = dossierHarness(t)
  const original = JSON.stringify(h.props.dossier)
  h.state.switchReportLang('zh')
  await settle()
  const html = await renderExisting(h.component, h.props, h.state)
  const body = text(html)
  for (const phrase of ['政策研究', '关键参与者', '制定利率政策。', '等待数据确认。', '上一轮维持利率。',
    '委员会正在审议。', '此前谈判尚未完成。', '支持正在增加。', '各方对成本有分歧。', '下一次会议可能促成决定。',
    '政策执行', '预算决定可行空间。', '委员会召开会议。', '委员会会通过提案吗？', '政策发布', '官方发布决定合约结果。',
    'CPI 必须严格高于 3%。', '采用官方发布值。', '消费者价格指数', '美国', '125.4', '月度', '买价 0.4', '卖价 0.44', '最近报价 0.41', '结果选项 Yes']) assert.ok(body.includes(phrase), phrase)
  for (const originalText of ['Sets monetary policy.', 'The committee is deliberating.', 'Policy implementation', 'Use the official release.']) assert.ok(!body.includes(originalText), originalText)
  for (const preserved of ['Federal Reserve', 'Congress', '2027-06-01', '2026-10-22', '70%', 'USD_per_contract', 'last_price_dollars/1_USD_binary_payout', 'S7']) assert.ok(body.includes(preserved), preserved)
  assert.ok(html.includes('href="https://example.org/source"'))
  assert.ok(html.includes('href="https://example.org/CPI-3"'))
  assert.equal(JSON.stringify(h.props.dossier), original)
  assert.equal(h.state.coverageFeedback.value, '')
  h.state.activeTab.value = 'actors'
  assert.ok((await renderExisting(h.component, h.props, h.state)).includes('dossier-language-bar'), 'language/retry controls remain outside individual tabs')
  h.state.switchReportLang(null)
  assert.equal(h.state.actorList.value[0].role, 'Sets monetary policy.')
})

test('Research Report missing structured projection is explicitly partial and the single retry preserves audited Markdown', async t => {
  const h = dossierHarness(t, { get: async () => ({ data: { available: true, status: 'available', report: '# 中文正文', partial: false } }) })
  h.state.switchReportLang('zh'); await settle()
  assert.equal(h.state.translationIncomplete.value, true)
  assert.match(h.state.coverageFeedback.value, /部分翻译.*保留原文/)
  assert.equal(h.state.showGenerateTranslation.value, true)
  assert.equal(h.state.translationButtonLabel.value, '重试翻译')
  const html = await renderExisting(h.component, h.props, h.state)
  assert.equal((html.match(/>重试翻译<\/button>/g) || []).length, 1)
  await h.state.generateResearchTranslation()
  assert.deepEqual(h.calls.at(-1), ['post', 'pipe_A', 'zh', false])
  assert.equal(h.state.translationStatus.value, 'failed')
})

test('Research Report rejects late language responses after source selection and after structured-only source changes', async t => {
  const pending = deferred()
  const h = dossierHarness(t, { get: () => pending.promise })
  h.state.switchReportLang('zh')
  h.state.switchReportLang(null)
  pending.resolve({ data: { status: 'available', available: true, report: '# 旧的译文', dossier: dossierPayload(true) } })
  await settle()
  assert.equal(h.state.activeReportLang.value, null)
  assert.deepEqual(h.state.researchLangCache.value, {})
  assert.equal(h.state.reportLangLoading.value, false)

  const next = deferred()
  const fresh = dossierHarness(t, { get: () => next.promise })
  fresh.state.switchReportLang('zh')
  fresh.props.dossier.actors.hot_topics = ['Replacement topic']
  next.resolve({ data: { status: 'available', available: true, report: '# 不应采用', dossier: dossierPayload(true) } })
  await settle()
  assert.equal(fresh.state.activeReportLang.value, null)
  assert.deepEqual(fresh.state.dossierLangCache.value, {})
  assert.deepEqual(fresh.state.hotTopics.value, ['Replacement topic'])
})

function reportMeta(id = 'report_A') {
  const translation = { report_id: id, lang: 'zh', source_lang: 'en', path: 'full_report.zh.md',
    citations_path: 'citations.zh.json', final_audit_path: 'final_audit.zh.json', available: true,
    markdown_sha256: 'b'.repeat(64), source_markdown_sha256: 'a'.repeat(64), audit_verified: true }
  return { report_id: id, status: 'completed', markdown_content: '# Committee outlook\n\nApproval probability is 70%.[S1]',
    news_market_context: context(), translation_status: { report_id: id, source_lang: 'en', target_lang: 'zh', requested_lang: 'zh',
      status: 'available', available: true, can_generate: true, markdown_sha256: 'b'.repeat(64), translation }, translations: [translation] }
}
function forecast(zh = false) {
  return { headline: zh ? '委员会可能通过提案。' : 'The committee may approve the proposal.', confidence: 'high',
    confidence_rationale: zh ? '证据具有一致性。' : 'The evidence is consistent.',
    scenarios: [{ name: zh ? '通过提案' : 'Approval', probability: 0.7, summary: zh ? '多数成员可能投赞成票。' : 'A majority may vote in favor.', key_drivers: [zh ? '支持率保持稳定。' : 'Support remains stable.'], resolution_criteria: zh ? '在 2027-06-01 前正式表决通过。' : 'Formal approval by 2027-06-01.' }],
    binary_forecasts: [{ id: 'F1', statement: zh ? '委员会会在 2027-06-01 前通过提案。' : 'The committee approves by 2027-06-01.',
      probability: 0.7, confidence: 'high', adjustment_rationale: zh ? '支持率稳定在 70%。' : 'Support holds at 70%.' }],
  }
}
function reportHarness(t, { getMd, getForecast, getReport, requestTranslation, unmountCallbacks = null } = {}) {
  i18n.locale.value = 'en'
  const requests = []
  const lifecycleVue = unmountCallbacks ? { ...integrationVue, onBeforeUnmount: callback => unmountCallbacks.push(callback) } : integrationVue
  const component = buildReport({ vue: lifecycleVue, '../../i18n': i18n, '../../utils/markdown': markdown,
    '../../utils/reportLanguages': reportLanguages, '../../utils/officialData': officialData, '../../utils/vizManifest': vizManifest,
    '../../utils/saveTextFile': { saveTextFile: fail }, './BinaryForecastTable.vue': { default: buildTable({ vue, '../../i18n': i18n, '../../utils/binaryForecasts': binaryForecasts }) },
    '../../api/report': { getReport: getReport || (async id => ({ data: reportMeta(id) })), getVizManifest: async () => ({ data: [] }),
      getForecast: getForecast || (async (_id, lang) => ({ data: { forecast: forecast(lang === 'zh'), localization: { localized: lang === 'zh', complete: true },
        display: lang === 'zh' ? { title: '委员会展望', news_market_context: context(true), viz_manifest: [], failed_sections: [] } : null,
        translation_status: { complete: true, partial: false } } })),
      getReportOfficialData: async () => ({ data: { available: false } }), getSectionsPartial: fail,
      getReportTranslationMd: getMd || (async () => '# 委员会展望\n\n通过概率为 70%。[S1]'),
      requestReportTranslation: async (...args) => { requests.push(args); return requestTranslation ? requestTranslation(...args) : { data: { status: 'failed', available: false, issues: ['scripted failure'] } } },
      getReportTranslationStatus: fail, reportMarkdownUrl: id => `/report/${id}.md`, reportPdfUrl: id => `/report/${id}.pdf`, reportAssetUrl: (id, path) => `/report/${id}/${path}`,
    },
  })
  const props = vue.reactive({ reportId: 'report_A' })
  const scope = vue.effectScope()
  const state = scope.run(() => component.setup(props, { expose() {} }))
  t.after(() => { state.stopPolling(); state.stopTranslationPolling(); state.stopStructuredPolling(); scope.stop(); i18n.locale.value = 'en' })
  return { component, props, state, requests }
}

test('Forecast Report Mandarin renders language-specific scenarios/binaries/title/context and UI labels, preserving probability and native quotes', async t => {
  const h = reportHarness(t)
  await h.state.load(); await settle(); await h.state.switchLang('zh')
  const html = await renderExisting(h.component, h.props, h.state)
  const body = text(html)
  for (const phrase of ['目录', '预测报告', '已完成', '委员会展望', '预测仪表盘', '委员会可能通过提案。', '通过提案',
    '在 2027-06-01 前正式表决通过。', '多数成员可能投赞成票。', '关键驱动因素', '支持率保持稳定。', '二元预测', '命题', '概率', '委员会会在 2027-06-01 前通过提案。',
    '新闻与市场背景', 'CPI 必须严格高于 3%。', '采用官方发布值。', '买价 0.4', '卖价 0.44', '最近报价 0.41']) assert.ok(body.includes(phrase), phrase)
  assert.ok(html.includes('支持率稳定在 70%。'), 'binary rationale tooltip is translated')
  for (const value of ['70%', '2027-06-01', 'USD_per_contract', 'last_price_dollars/1_USD_binary_payout', 'Yes', 'S7']) assert.ok(body.includes(value), value)
  assert.equal(h.state.structuredTranslationPartial.value, false)
  assert.equal(h.state.structuredTranslationNotice.value, '')
  assert.equal(h.state.forecastByLang.value.en.headline, 'The committee may approve the proposal.')
  assert.equal(h.state.meta.value.news_market_context.items[0].rules_secondary, 'Use the official release.')
})

test('Forecast Report explicitly discloses source fallback and offers one plain retry for incomplete structured translation', async t => {
  const h = reportHarness(t, { getForecast: async () => ({ data: { forecast: forecast(), localization: { localized: false }, display: null } }) })
  await h.state.load(); await settle(); await h.state.switchLang('zh')
  assert.equal(h.state.structuredTranslationPartial.value, true)
  assert.match(h.state.structuredTranslationNotice.value, /部分结构化内容.*原文显示/)
  const html = await renderExisting(h.component, h.props, h.state)
  assert.equal((html.match(/>重试翻译<\/button>/g) || []).length, 1)
  assert.ok(text(html).includes('The committee may approve the proposal.'))
  await h.state.generateTranslation(true)
  assert.deepEqual(h.requests, [['report_A', 'zh', false]])
  assert.equal(h.state.translationError.value, 'scripted failure')
})

test('Forecast Report source selection cancels pending Mandarin activation and cross-report responses cannot repopulate old data', async t => {
  const oldMd = deferred()
  const h = reportHarness(t, { getMd: () => oldMd.promise })
  await h.state.load(); await settle()
  const pending = h.state.switchLang('zh')
  await h.state.switchLang(null)
  oldMd.resolve('# 不应显示的译文')
  await pending
  assert.equal(h.state.activeLang.value, null)
  assert.equal(h.state.langLoading.value, false)
  assert.deepEqual(h.state.langMdCache.value, {})
  const oldForecast = deferred()
  const next = reportHarness(t, { getForecast: (id, lang) => lang === 'zh' ? oldForecast.promise : Promise.resolve({ data: { forecast: forecast() } }) })
  await next.state.load(); await settle()
  const oldSwitch = next.state.switchLang('zh')
  await settle()
  next.props.reportId = 'report_B'
  await settle()
  oldForecast.resolve({ data: { forecast: { headline: '旧报告不得显示' }, display: { title: '旧报告标题' }, localization: { localized: true, complete: true } } })
  await oldSwitch; await settle()
  assert.equal(next.state.meta.value.report_id, 'report_B')
  assert.ok(!JSON.stringify(next.state.forecastByLang.value).includes('旧报告'))
  assert.ok(!JSON.stringify(next.state.displayByLang.value).includes('旧报告'))
  assert.equal(next.state.activeLang.value, null)
})


test('Research Report can show translated structured content while failed Markdown is honestly shown as source', async t => {
  const h = dossierHarness(t, { get: async () => ({ data: { available: false, status: 'failed', report: null,
    dossier: dossierPayload(true), partial: true, issues: ['Markdown audit rejected a changed number'], structured_translation: { complete: true } } }) })
  h.state.switchReportLang('zh'); await settle()
  assert.equal(h.state.reportMarkdown.value, h.props.dossier.report)
  assert.equal(h.state.actorList.value[0].role, '制定利率政策。')
  assert.match(h.state.coverageFeedback.value, /译文尚不可用.*原文/)
  assert.match(h.state.translationFeedback.value, /未通过发布审计/)
  assert.equal(h.state.showGenerateTranslation.value, true)
  assert.deepEqual(h.state.translationIssues.value, ['Markdown audit rejected a changed number'])
})


test('Research Report invalidated server variant removes old Markdown and projected fields instead of displaying stale translations', async t => {
  let valid = true
  const h = dossierHarness(t, { get: async () => ({ data: valid ? {
    status: 'available', available: true, report: '# 有效译文', dossier: dossierPayload(true), structured_translation: { complete: true },
  } : { status: 'stale', available: false, report: null, issues: ['source fingerprint changed'] } }) })
  h.state.switchReportLang('zh'); await settle()
  assert.equal(h.state.reportMarkdown.value, '# 有效译文')
  valid = false
  await h.state.loadResearchTranslation('zh')
  assert.equal(h.state.reportMarkdown.value, h.props.dossier.report)
  assert.equal(h.state.actorList.value[0].role, 'Sets monetary policy.')
  assert.equal(h.state.pdfDisabled.value, true)
  assert.equal(h.state.translationButtonLabel.value, '重试翻译')
  assert.match(h.state.coverageFeedback.value, /译文尚不可用.*原文/)
})

// Fake only the existing bounded polling clock. Every tick still invokes the
// production GET/refetch methods; no synthetic completion or paid POST is added.
function pollingClock(t) {
  const originalSet = globalThis.setTimeout
  const originalClear = globalThis.clearTimeout
  const timers = new Map()
  let nextId = 0
  globalThis.setTimeout = (callback, delay) => { const id = ++nextId; timers.set(id, { callback, delay }); return id }
  globalThis.clearTimeout = id => timers.delete(id)
  t.after(() => { globalThis.setTimeout = originalSet; globalThis.clearTimeout = originalClear })
  return { timers, async next() {
    assert.equal(timers.size, 1, 'one read-only poll is scheduled')
    const [id, timer] = [...timers][0]
    assert.equal(timer.delay, 4000)
    timers.delete(id); timer.callback()
    await settle(); await settle()
  } }
}
const dossierDisplayResponse = (status, { complete = status === 'available' } = {}) => ({ data: {
  available: true, status: 'available', report: '# 已通过审计的正文', dossier: dossierPayload(complete),
  partial: !complete, structured_translation: { status, complete, partial: !complete,
    coverage: { complete }, source_fingerprint: 'g1', target_lang: 'zh' },
} })
const forecastDisplayResponse = (status, { complete = status === 'available' } = {}) => ({ data: {
  forecast: forecast(true), localization: { localized: true, complete: true },
  display: { title: complete ? '结构化翻译完成' : 'Structured title pending', news_market_context: context(complete), viz_manifest: [], failed_sections: [] },
  structured_translation: { status, complete, partial: !complete, coverage: { complete }, source_fingerprint: 'g1', target_lang: 'zh' },
} })

test('available research Markdown keeps serving while structured-generating GET polling completes without another POST', async t => {
  const clock = pollingClock(t)
  let count = 0
  const h = dossierHarness(t, { get: async () => dossierDisplayResponse(++count === 1 ? 'generating' : 'available') })
  h.state.switchReportLang('zh'); await settle()
  assert.equal(h.state.translationStatus.value, 'available', 'Markdown availability is independent')
  assert.equal(h.state.reportMarkdown.value, '# 已通过审计的正文')
  assert.equal(h.state.pdfDisabled.value, false)
  assert.equal(h.state.structuredGenerating.value, true)
  assert.match(h.state.coverageFeedback.value, /正文译文可用.*补全/)
  await h.state.generateResearchTranslation()
  assert.equal(h.calls.filter(c => c[0] === 'post').length, 0, 'polling never duplicates paid generation')
  await clock.next()
  assert.equal(h.state.structuredGenerating.value, false)
  assert.equal(h.state.translationIncomplete.value, false)
  assert.equal(h.state.actorList.value[0].role, '制定利率政策。')
  assert.equal(h.state.coverageFeedback.value, '')
  assert.equal(clock.timers.size, 0)
})

test('research structured poll rejects an in-flight response after source/identity changes', async t => {
  const clock = pollingClock(t)
  const stale = deferred()
  let count = 0
  const h = dossierHarness(t, { get: async () => ++count === 1 ? dossierDisplayResponse('generating') : stale.promise })
  h.state.switchReportLang('zh'); await settle(); await clock.next()
  h.props.pipelineId = 'pipe_B'
  stale.resolve(dossierDisplayResponse('available'))
  await settle()
  assert.equal(h.state.activeReportLang.value, null)
  assert.deepEqual(h.state.researchLangCache.value, {})
  assert.deepEqual(h.state.dossierLangCache.value, {})
  assert.equal(clock.timers.size, 0)
  assert.equal(h.calls.filter(c => c[0] === 'post').length, 0)
})

test('available forecast Markdown polls only forecast display to completion and never starts another translation task', async t => {
  const clock = pollingClock(t)
  let count = 0
  const h = reportHarness(t, { getForecast: async (_id, lang) => lang === 'zh'
    ? forecastDisplayResponse(++count === 1 ? 'generating' : 'available')
    : { data: { forecast: forecast() } } })
  await h.state.load(); await settle(); await h.state.switchLang('zh')
  assert.equal(h.state.activeLang.value, 'zh')
  assert.equal(h.state.structuredGenerating.value, true)
  assert.match(h.state.structuredTranslationNotice.value, /正文译文可用.*补全/)
  await h.state.generateTranslation(true)
  assert.deepEqual(h.requests, [])
  await clock.next()
  assert.equal(h.state.reportTitle.value, '结构化翻译完成')
  assert.equal(h.state.structuredGenerating.value, false)
  assert.equal(h.state.structuredTranslationNotice.value, '')
  assert.equal(h.state.currentMd.value, '# 委员会展望\n\n通过概率为 70%。[S1]')
  assert.deepEqual(h.requests, [])
  assert.equal(clock.timers.size, 0)
})

test('forecast structured poll cannot commit a late response after switching back to source', async t => {
  const clock = pollingClock(t)
  const stale = deferred()
  let count = 0
  const h = reportHarness(t, { getForecast: async (_id, lang) => lang === 'zh'
    ? (++count === 1 ? forecastDisplayResponse('generating') : stale.promise)
    : { data: { forecast: forecast() } } })
  await h.state.load(); await settle(); await h.state.switchLang('zh'); await clock.next()
  await h.state.switchLang(null)
  stale.resolve(forecastDisplayResponse('available'))
  await settle()
  assert.equal(h.state.activeLang.value, null)
  assert.equal(h.state.displayByLang.value.zh.title, 'Structured title pending', 'late polling bytes are rejected even from the inactive language cache')
  assert.equal(clock.timers.size, 0)
  assert.deepEqual(h.requests, [])
})

for (const scope of ['research', 'forecast']) {
  test(`${scope} structured polling stops after thirty reads with visible timeout and one retry, keeping translated Markdown`, async t => {
    const clock = pollingClock(t)
    const h = scope === 'research'
      ? dossierHarness(t, { get: async () => dossierDisplayResponse('generating') })
      : reportHarness(t, { getForecast: async (_id, lang) => lang === 'zh' ? forecastDisplayResponse('generating') : { data: { forecast: forecast() } } })
    if (scope === 'research') { h.state.switchReportLang('zh'); await settle() }
    else { await h.state.load(); await settle(); await h.state.switchLang('zh') }
    for (let i = 0; i < 30; i += 1) await clock.next()
    assert.equal(clock.timers.size, 0)
    assert.equal(h.state.structuredGenerating.value, false)
    assert.match(scope === 'research' ? h.state.coverageFeedback.value : h.state.structuredTranslationNotice.value, /等待超时.*停止自动查询/)
    assert.ok((scope === 'research' ? h.state.reportMarkdown.value : h.state.currentMd.value).includes('正文') || scope === 'forecast')
    const html = await renderExisting(h.component, h.props, h.state)
    assert.equal((html.match(/>重试翻译<\/button>/g) || []).length, 1)
    if (scope === 'research') assert.equal(h.calls.filter(c => c[0] === 'post').length, 0)
    else assert.deepEqual(h.requests, [])
  })
}


for (const scope of ['research', 'forecast']) {
  for (const terminal of ['partial', 'failed', 'network_error']) {
    test(`${scope} structured ${terminal} stops polling and exposes retry while preserving available Markdown`, async t => {
      const clock = pollingClock(t)
      let count = 0
      const response = () => {
        count += 1
        if (count > 1 && terminal === 'network_error') throw new Error('Read-only status request failed')
        const status = count === 1 ? 'generating' : terminal
        return scope === 'research' ? dossierDisplayResponse(status) : forecastDisplayResponse(status)
      }
      const h = scope === 'research'
        ? dossierHarness(t, { get: async () => response() })
        : reportHarness(t, { getForecast: async (_id, lang) => lang === 'zh' ? response() : { data: { forecast: forecast() } } })
      if (scope === 'research') { h.state.switchReportLang('zh'); await settle() }
      else { await h.state.load(); await settle(); await h.state.switchLang('zh') }
      await clock.next()
      assert.equal(clock.timers.size, 0)
      assert.equal(h.state.structuredGenerating.value, false)
      assert.ok(scope === 'research' ? h.state.reportMarkdown.value.includes('已通过审计') : h.state.currentMd.value.includes('委员会展望'))
      const html = await renderExisting(h.component, h.props, h.state)
      assert.equal((html.match(/>重试翻译<\/button>/g) || []).length, 1)
      if (scope === 'research') assert.equal(h.calls.filter(c => c[0] === 'post').length, 0)
      else assert.deepEqual(h.requests, [])
    })
  }
}


test('already-Mandarin canonical forecast is complete without a localized variant file or a false retry', async t => {
  const canonical = forecast(true)
  const original = JSON.stringify(canonical)
  const h = reportHarness(t, { getForecast: async (_id, lang) => ({ data: {
    forecast: canonical,
    localization: { localized: false, complete: true, already_target: true, source_forecast_sha256: 'f'.repeat(64) },
    display: lang === 'zh' ? { title: '委员会展望', news_market_context: context(true), viz_manifest: [], failed_sections: [] } : null,
    structured_translation: { complete: true, status: 'available', partial: false, target_lang: lang },
  } }) })
  await h.state.load(); await settle(); await h.state.switchLang('zh')
  assert.equal(h.state.forecastLocalizationByLang.value.zh.localized, false, 'localized retains its variant-file meaning')
  assert.equal(h.state.forecastLocalizationByLang.value.zh.already_target, true)
  assert.equal(h.state.structuredTranslationPartial.value, false)
  assert.equal(h.state.structuredTranslationNotice.value, '')
  assert.equal(h.state.translationUpdateAction.value, null)
  const html = await renderExisting(h.component, h.props, h.state)
  assert.ok(text(html).includes('委员会可能通过提案。'))
  assert.ok(text(html).includes('70%'))
  assert.ok(!html.includes('>重试翻译</button>'))
  assert.equal(JSON.stringify(canonical), original)
  assert.deepEqual(h.requests, [], 'already-target content needs no model request')
})


// Lifted from the independent actual-SFC unmount red. The initial language GET
// (pollVersion=null) must be invalidated, not only an already-scheduled poll.
test('Forecast initial language GET cannot mutate caches or restart structured polling after unmount', async t => {
  const clock = pollingClock(t)
  const pending = deferred()
  const unmountCallbacks = []
  const h = reportHarness(t, { unmountCallbacks, getForecast: async (_id, lang) => lang === 'zh'
    ? pending.promise : { data: { forecast: forecast() } } })
  await h.state.load(); await settle()
  const switching = h.state.switchLang('zh'); await settle()
  assert.equal(h.state.activeLang.value, 'zh')
  assert.equal(unmountCallbacks.length, 1, 'capture the actual production unmount callback')
  assert.equal(clock.timers.size, 0, 'initial structured GET is still in flight')
  unmountCallbacks.forEach(callback => callback())
  const before = JSON.stringify({ forecast: h.state.forecastByLang.value, display: h.state.displayByLang.value })
  pending.resolve(forecastDisplayResponse('generating'))
  await switching; await settle()
  assert.equal(clock.timers.size, 0, 'late initial GET must not reschedule a poll after unmount')
  assert.equal(JSON.stringify({ forecast: h.state.forecastByLang.value, display: h.state.displayByLang.value }), before)
  assert.deepEqual(h.requests, [])
})

test('Dossier initial translation GET stays invalid after its actual unmount callback', async t => {
  const clock = pollingClock(t)
  const pending = deferred()
  const unmountCallbacks = []
  const h = dossierHarness(t, { unmountCallbacks, get: async () => pending.promise })
  h.state.switchReportLang('zh'); await settle()
  assert.equal(unmountCallbacks.length, 1)
  assert.equal(clock.timers.size, 0)
  unmountCallbacks.forEach(callback => callback())
  pending.resolve(dossierDisplayResponse('generating'))
  await settle()
  assert.equal(clock.timers.size, 0, 'Dossier already advances its request epoch on unmount')
  assert.deepEqual(h.state.researchLangCache.value, {})
  assert.deepEqual(h.state.dossierLangCache.value, {})
  assert.equal(h.calls.filter(c => c[0] === 'post').length, 0)
})

test('Forecast display-only retry preserves audited Markdown with a plain POST when forecast localization is complete', async t => {
  const h = reportHarness(t, { getForecast: async () => forecastDisplayResponse('partial') })
  await h.state.load(); await settle(); await h.state.switchLang('zh')
  const published = h.state.currentMd.value
  assert.equal(h.state.forecastLocalizationByLang.value.zh.complete, true)
  assert.equal(h.state.structuredTranslationPartial.value, true)
  const html = await renderExisting(h.component, h.props, h.state)
  assert.equal((html.match(/>重试翻译<\/button>/g) || []).length, 1)
  await h.state.generateTranslation(true)
  assert.deepEqual(h.requests, [['report_A', 'zh', false]], 'cards-only retry must not regenerate already-audited report prose')
  assert.equal(h.state.currentMd.value, published)
})

for (const cause of ['partial', 'outdated']) {
  test(`Forecast explicit ${cause} body update keeps force even when forecast localization is complete`, async t => {
    const h = reportHarness(t, {
      getForecast: async () => forecastDisplayResponse('partial'),
      getReport: async id => { const current = reportMeta(id); current.translation_status = { ...current.translation_status, can_update: true, [cause]: true }; return { data: current } },
    })
    await h.state.load(); await settle(); await h.state.switchLang('zh')
    h.state.meta.value = { ...h.state.meta.value, translation_status: {
      ...h.state.meta.value.translation_status, can_update: true, [cause]: true,
    } }
    await h.state.generateTranslation(true)
    assert.deepEqual(h.requests, [['report_A', 'zh', true]])
  })
}

test('Dossier display-only retry preserves audited Markdown with a plain POST despite the aggregate partial flag', async t => {
  const h = dossierHarness(t, { get: async () => dossierDisplayResponse('partial') })
  h.state.switchReportLang('zh'); await settle()
  const published = h.state.reportMarkdown.value
  assert.equal(h.state.translationDetails.value.zh.partial, true)
  assert.equal(h.state.translationIncomplete.value, true)
  await h.state.generateResearchTranslation()
  assert.deepEqual(h.calls.at(-1), ['post', 'pipe_A', 'zh', false], 'aggregate structured partial must not force a Markdown rewrite')
  assert.equal(h.state.reportMarkdown.value, published)
})

test('Dossier partial body update keeps force when verbatim passages and incomplete cards coexist', async t => {
  const h = dossierHarness(t, { get: async () => {
    const payload = dossierDisplayResponse('partial')
    payload.data.verbatim_chunks = [{ chunk: 1, heading: 'Executive Summary', reason: 'content_filter', lines: 1 }]
    return payload
  } })
  h.state.switchReportLang('zh'); await settle()
  await h.state.generateResearchTranslation()
  assert.deepEqual(h.calls.at(-1), ['post', 'pipe_A', 'zh', true])
})

// Lifted from independentRetryScope.test.mjs: an incomplete forecast sidecar is
// not evidence that the separately audited Markdown body needs regeneration.
test('incomplete forecast cards retry without forcing a complete audited Markdown body', async t => {
  const h = reportHarness(t, { getForecast: async () => {
    const response = forecastDisplayResponse('partial')
    response.data.localization = { localized: true, complete: false }
    return response
  } })
  await h.state.load(); await settle(); await h.state.switchLang('zh')
  const body = h.state.currentMd.value
  assert.ok(body.includes('委员会展望'))
  const state = h.state.meta.value.translation_status
  assert.equal(state.available, true)
  assert.notEqual(state.partial, true)
  assert.notEqual(state.outdated, true)
  assert.equal(h.state.forecastLocalizationByLang.value.zh.complete, false)
  assert.equal(h.state.structuredTranslationPartial.value, true)
  await h.state.generateTranslation(true)
  assert.deepEqual(h.requests, [['report_A', 'zh', false]], 'forecast-only failure must repair sidecars without forcing audited Markdown regeneration')
  assert.equal(h.state.currentMd.value, body)
})

test('absent optional forecast stays absent without introducing a body-regeneration action', async t => {
  const h = reportHarness(t, { getForecast: async () => ({ data: {
    forecast: null, localization: { localized: false, complete: false },
    display: { title: '委员会展望', news_market_context: context(true), viz_manifest: [], failed_sections: [] },
    structured_translation: { complete: true, status: 'available', partial: false },
  } }) })
  await h.state.load(); await settle(); await h.state.switchLang('zh')
  assert.equal(h.state.fc.value, null)
  assert.equal(h.state.showDashboard.value, false)
  assert.equal(h.state.structuredTranslationPartial.value, false)
  assert.equal(h.state.translationUpdateAction.value, null)
  assert.deepEqual(h.requests, [])
})


test('retry refreshes cached partial metadata before deciding force for a currently complete Mandarin body', async t => {
  let metadataReads = 0
  let bodyReads = 0
  const h = reportHarness(t, {
    getReport: async id => {
      const current = reportMeta(id)
      if (++metadataReads === 1) {
        current.translation_status = { ...current.translation_status, partial: true, can_update: true }
        current.translations[0].partial = true
      }
      return { data: current }
    },
    getMd: async () => { bodyReads += 1; return '# 当前完整中文译文\n\n通过概率为 70%。[S1]' },
    getForecast: async () => { const result = forecastDisplayResponse('partial'); result.data.localization.complete = false; return result },
  })
  await h.state.load(); await settle(); await h.state.switchLang('zh')
  assert.equal(h.state.meta.value.translation_status.partial, true, 'reproduce the stale HMR metadata')
  const acceptedBody = h.state.currentMd.value
  await h.state.generateTranslation(true)
  assert.equal(metadataReads, 2, 'refresh current report metadata before POST')
  assert.deepEqual(h.requests, [['report_A', 'zh', false]])
  assert.notEqual(h.state.meta.value.translation_status.translation.partial, true)
  assert.equal(h.state.currentMd.value, acceptedBody)
  assert.equal(bodyReads, 1, 'deciding retry scope does not refetch or regenerate Markdown')
})

function cachedPartialMetadata(id) {
  const current = reportMeta(id)
  current.translation_status = { ...current.translation_status, partial: true, can_update: true }
  current.translations[0].partial = true
  return current
}

test('retry sets busy before refreshing metadata and deduplicates clicks without starting two POSTs', async t => {
  const pending = deferred()
  let reads = 0
  const h = reportHarness(t, { getReport: async id => ++reads === 1 ? { data: cachedPartialMetadata(id) } : pending.promise,
    getForecast: async () => forecastDisplayResponse('partial') })
  await h.state.load(); await settle(); await h.state.switchLang('zh')
  const first = h.state.generateTranslation(true)
  assert.equal(h.state.translationBusy.value, true)
  await h.state.generateTranslation(true)
  assert.equal(reads, 2)
  assert.deepEqual(h.requests, [], 'metadata must be checked before the first POST')
  pending.resolve({ data: reportMeta() })
  await first
  assert.deepEqual(h.requests, [['report_A', 'zh', false]])
  assert.equal(h.state.translationBusy.value, false)
})

test('retry metadata refresh failure preserves the accepted body and performs no POST', async t => {
  let reads = 0
  const h = reportHarness(t, { getReport: async id => {
    if (++reads > 1) throw new Error('Current metadata unavailable')
    return { data: cachedPartialMetadata(id) }
  }, getForecast: async () => forecastDisplayResponse('partial') })
  await h.state.load(); await settle(); await h.state.switchLang('zh')
  const body = h.state.currentMd.value
  await h.state.generateTranslation(true)
  assert.deepEqual(h.requests, [])
  assert.equal(h.state.translationBusy.value, false)
  assert.equal(h.state.translationError.value, 'Current metadata unavailable')
  assert.equal(h.state.currentMd.value, body)
})

for (const change of ['report', 'language', 'unmount']) {
  test(`retry rejects metadata that completes after a ${change} identity change`, async t => {
    const pending = deferred()
    const unmountCallbacks = []
    let reads = 0
    const h = reportHarness(t, { unmountCallbacks, getReport: async id => {
      reads += 1
      return reads === 2 ? pending.promise : { data: cachedPartialMetadata(id) }
    }, getForecast: async () => forecastDisplayResponse('partial') })
    await h.state.load(); await settle(); await h.state.switchLang('zh')
    const retry = h.state.generateTranslation(true)
    assert.equal(h.state.translationBusy.value, true)
    if (change === 'report') { h.props.reportId = 'report_B'; await settle() }
    else if (change === 'language') await h.state.switchLang(null)
    else unmountCallbacks.forEach(callback => callback())
    pending.resolve({ data: reportMeta('report_A') })
    await retry; await settle()
    assert.deepEqual(h.requests, [], 'stale refresh may not authorize a paid translation')
    if (change === 'report') assert.equal(h.state.meta.value.report_id, 'report_B')
    if (change === 'language') {
      assert.equal(h.state.activeLang.value, null)
      assert.equal(h.state.translationBusy.value, false)
    }
  })
}

for (const mismatch of ['report', 'language']) {
  test(`retry rejects freshly fetched metadata for the wrong ${mismatch}`, async t => {
    let reads = 0
    const h = reportHarness(t, { getReport: async id => {
      if (++reads === 1) return { data: cachedPartialMetadata(id) }
      const fresh = reportMeta(mismatch === 'report' ? 'report_other' : id)
      if (mismatch === 'language') fresh.translation_status.target_lang = 'en'
      return { data: fresh }
    }, getForecast: async () => forecastDisplayResponse('partial') })
    await h.state.load(); await settle(); await h.state.switchLang('zh')
    await h.state.generateTranslation(true)
    assert.deepEqual(h.requests, [])
    assert.equal(h.state.translationBusy.value, false)
    assert.match(h.state.translationError.value, /不匹配/)
  })
}


test('retry obeys freshly revoked permission for a still-partial body before POST', async t => {
  let reads = 0
  const h = reportHarness(t, { getReport: async id => {
    const current = cachedPartialMetadata(id)
    if (++reads > 1) current.translation_status.can_generate = false
    return { data: current }
  }, getForecast: async () => forecastDisplayResponse('partial') })
  await h.state.load(); await settle(); await h.state.switchLang('zh')
  await h.state.generateTranslation(true)
  assert.deepEqual(h.requests, [])
  assert.equal(h.state.translationBusy.value, false)
  assert.match(h.state.translationError.value, /未允许重新生成正文/)
})
