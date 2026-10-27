import * as researchPdfExport from '../src/utils/researchPdfExport.js'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'
import * as i18n from '../src/i18n.js'
import * as sourceContext from '../src/utils/sourceContext.js'
import * as markdown from '../src/utils/markdown.js'
import * as officialData from '../src/utils/officialData.js'
import * as researchTranslation from '../src/utils/researchTranslation.js'
import * as reportLanguages from '../src/utils/reportLanguages.js'
import * as vizManifest from '../src/utils/vizManifest.js'
import * as binaryForecasts from '../src/utils/binaryForecasts.js'
import { compileSfc } from './sfcHarness.mjs'

const panelUrl = new URL('../src/components/research/SourceContextPanel.vue', import.meta.url)
const dossierUrl = new URL('../src/components/research/DossierViewer.vue', import.meta.url)
const reportUrl = new URL('../src/components/research/ForecastReport.vue', import.meta.url)
const buildPanel = compileSfc(panelUrl)
const buildDossier = compileSfc(dossierUrl)
const buildReport = compileSfc(reportUrl)
const buildTable = compileSfc(new URL('../src/components/research/BinaryForecastTable.vue', import.meta.url))
const panel = () => buildPanel({ vue, '../../i18n': i18n, '../../utils/sourceContext': sourceContext })

test('native rule details remain inspectable in both languages without mutating capture', async () => {
  const context = envelope({ items: [{ ...kalshiNormalized, floor_strike: 0,
    rules_secondary: '<script>unsafe()</script> Use official release.' }] })
  const original = JSON.stringify(context)
  for (const lang of ['en', 'zh']) {
    const html = await renderPanel(context, lang)
    assert.ok(html.includes(lang === 'en' ? 'Settlement rules and thresholds' : '结算规则与阈值'))
    assert.ok(html.includes('CPI strictly above 3 at the specified release.'))
    assert.ok(html.includes('&lt;script&gt;unsafe()&lt;/script&gt; Use official release.'))
    assert.ok(!html.includes('<script>'))
    assert.ok(html.includes('last_price_dollars/1_USD_binary_payout'))
    assert.ok(html.includes(lang === 'en' ? 'Lower threshold: 0' : '下限: 0'))
    assert.ok(html.includes('2026-12-31T23:59:59.000Z'))
  }
  assert.equal(JSON.stringify(context), original)
})
const count = (html, needle) => html.split(needle).length - 1
const text = html => html.replace(/<!--[^]*?-->/g, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
const settle = () => new Promise(resolve => setImmediate(resolve))
const item = (overrides = {}) => ({
  id: 'newsapi:source', provider: 'newsapi', kind: 'news_snippet', title: 'Publisher outlook',
  url: 'https://publisher.example/story', published_at: '2026-10-18T11:00:00Z',
  retrieved_at: '2026-10-18T12:00:00Z', publisher: 'Example Publisher', language: 'en',
  query: 'outlook', snippet: 'Stored news snippet.', source_ref: 'S7',
  eligibility: { context_only: true, anchor: false, resolution: false }, ...overrides,
})
const envelope = (overrides = {}) => ({
  schema_version: 1, generation_id: 'context:fixture', language: 'en', sealed: true,
  providers: { newsapi: { status: { state: 'ok', attempted: true } }, reddit: { status: { state: 'disabled', attempted: false } } },
  items: [item()], ...overrides,
})
// Source-shaped normalize_kalshi_market result for the market worker's kalshi()
// fixture in backend/tests/test_market_intelligence.py. Values are supplied in
// dollars by that normalizer, not cent-scaled or reconstructed by the frontend.
const kalshiNormalized = {
  id: 'kalshi:CPI-26-T3', native_id: 'CPI-26-T3', provider: 'kalshi', kind: 'market_quote',
  title: 'CPI above 3 in 2026?', url: 'https://external-api.kalshi.com/trade-api/v2/markets/CPI-26-T3',
  published_at: '2026-01-01T00:00:00+00:00', retrieved_at: '2026-10-18T12:00:00+00:00',
  language: 'en', query: 'CPI', snippet: null, eligibility: { context_only: true, anchor: false, resolution: false },
  market_type: 'binary', event_id: 'CPI-26', outcome: 'Yes', yes_label: null, no_label: null,
  probability: 0.43, probability_basis: 'last_price_dollars/1_USD_binary_payout',
  quote_basis: 'provider_reported_dollars_per_contract', price_unit: 'USD_per_contract', quote_at: null,
  metadata_updated_at: '2026-10-18T11:00:00+00:00', volume: 1.5, volume_unit: 'contracts',
  volume_24h: 0.25, open_interest: 1.25, notional_value: 1,
  rules_primary: 'CPI strictly above 3 at the specified release.', rules_secondary: 'Use official release.',
  end_date: '2026-12-31T23:59:59+00:00', expiration_time: null, strike_type: 'greater',
  floor_strike: 3, cap_strike: null, status: 'active',
  yes_bid: 0.42, yes_ask: 0.44, no_bid: 0.56, no_ask: 0.58, last_price: 0.43,
  rules: 'CPI strictly above 3 at the specified release.\nUse official release.', volume_units: 'contracts',
  units: 'USD_per_contract', price_basis: 'last_price_dollars/1_USD_binary_payout', contract_type: 'binary',
  bid: 0.42, ask: 0.44, last: 0.43, quote_units: 'USD_per_contract',
  source_price_fields: { yes_bid_dollars: '0.4200', yes_ask_dollars: '0.4400', no_bid_dollars: '0.5600',
    no_ask_dollars: '0.5800', last_price_dollars: '0.4300' },
}
async function withLocale(lang, run) {
  const previous = i18n.locale.value
  i18n.locale.value = lang
  try { return await run() } finally { i18n.locale.value = previous }
}
const renderPanel = (context, lang = 'en') => withLocale(lang,
  () => renderToString(vue.createSSRApp(panel(), { context })))

test('real SFC renders a collapsed accessible evidence view with attribution and times', async () => {
  const html = await renderPanel(envelope())
  assert.match(html, /^<details class="source-context-panel"/)
  assert.match(html, /<summary>/)
  assert.doesNotMatch(html, /<details[^>]*\sopen(?:[\s=>])/)
  assert.match(html, /aria-label="Provider statuses"/)
  assert.match(html, /href="https:\/\/publisher.example\/story" target="_blank" rel="noopener noreferrer"/)
  assert.match(html, /<time datetime="2026-10-18T11:00:00.000Z"/)
  assert.match(html, /<time datetime="2026-10-18T12:00:00.000Z"/)
  assert.match(text(html), /News &amp; market context 1 items Context only/)
  assert.match(text(html), /News snippet newsapi Publisher: Example Publisher Original research ledger reference: S7 Language: en/)
  assert.match(text(html), /ineligible for probability anchoring or resolution/)
})

test('hostile title/snippet/provider content is escaped; unsafe URLs are plain text', async () => {
  const payload = '<img src=x onerror="alert(1)"><script>bad()</script>'
  const html = await renderPanel(envelope({
    providers: { [payload]: { status: { state: 'unavailable', attempted: true, reason: '<script>raw failure</script>' } } },
    items: [item({ title: payload, snippet: payload, publisher: payload, url: 'javascript:alert(1)' }),
      item({ id: 'newsapi:data', url: 'data:text/html,<script>bad()</script>' }),
      item({ id: 'newsapi:auth', url: 'https://user:secret@publisher.example' })],
  }))
  assert.equal(count(html, '<a '), 0)
  assert.doesNotMatch(html, /<script|<img|href="javascript:|href="data:|raw failure|user:secret/)
  assert.match(html, /&lt;img src=x onerror=&quot;alert\(1\)&quot;&gt;/)
  assert.match(html, /&lt;script&gt;bad\(\)&lt;\/script&gt;/)
})

test('all explicit failure statuses and partial results are visible without claiming empty', async () => {
  const providers = Object.fromEntries(['unavailable', 'partial', 'verified_empty', 'forbidden', 'rate_limited',
    'timeout', 'budget_exhausted', 'unsupported'].map(state => [state, { status: { state, attempted: true } }]))
  providers.missing = {}
  const html = await renderPanel(envelope({ providers, items: [] }))
  for (const state of Object.keys(providers).filter(state => state !== 'missing')) assert.ok(html.includes(`data-state="${state}"`))
  assert.match(text(html), /Unavailable Attempted/)
  assert.match(text(html), /Partial results Attempted/)
  assert.match(text(html), /Verified empty Attempted/)
  assert.match(text(html), /missing Unavailable Attempt status unknown/)
  assert.match(text(html), /No context items to display. Check each provider/)
  const failure = await renderPanel(envelope({ providers: { newsapi: { status: { state: 'unavailable', attempted: true } } }, items: [] }))
  assert.doesNotMatch(text(failure), /Verified empty/)
})

test('old, missing and disabled contexts produce no panel markup', async () => {
  for (const value of [null, {}, { items: [item()] }, envelope({ enabled: false }),
    envelope({ items: [], providers: { newsapi: { status: { state: 'disabled', attempted: false } } } }),
  ]) assert.doesNotMatch(await renderPanel(value), /source-context-panel|<details|<summary/)
})

test('four source kinds, quote units/basis, unknown dates and forecaster counts stay distinct', async () => {
  const html = await renderPanel(envelope({ items: [
    item(), item({ id: 'reddit:one', provider: 'reddit', kind: 'social_post', published_at: null, probability: 0.98 }),
    item({ id: 'kalshi:one', provider: 'kalshi', kind: 'market_quote', quote_basis: 'Yes order book',
      quote_units: 'USD per contract', bid: 0, ask: 0.42, last: 0.4, probability: 0.99 }),
    item({ id: 'metaculus:one', provider: 'metaculus', kind: 'community_forecast', forecaster_count: 91, probability: 0.5 }),
  ] }))
  const body = text(html)
  for (const kind of ['News snippet', 'Social opinion', 'Traded market quote', 'Community forecast']) assert.ok(body.includes(kind))
  assert.match(body, /Quote \/ forecast basis Yes order book Units USD per contract Bid 0 Ask 0.42 Last quote 0.4/)
  assert.match(body, /Forecasters 91/)
  assert.match(body, /Published: Unknown/)
  assert.doesNotMatch(body, /99%|98%|50%|91 USD|dollar volume/)
})

test('English and Chinese labels cover kinds, provider status and context limits', async () => {
  const context = envelope({ providers: { newsapi: { status: { state: 'partial', attempted: true } } }, items: [
    item(), item({ kind: 'social_post' }), item({ kind: 'market_quote', quote_basis: 'Yes', units: 'USD', bid: 0.4 }),
    item({ kind: 'community_forecast', forecaster_count: 0 }),
  ] })
  const en = text(await renderPanel(context, 'en'))
  const zh = text(await renderPanel(context, 'zh'))
  assert.match(en, /Context only/)
  for (const label of ['新闻与市场背景', '仅供背景参考', '部分结果', '已尝试', '新闻摘要', '社交观点',
    '交易市场报价', '社区预测', '发布时间', '采集时间', '报价／预测口径', '单位', '买价', '预测人数']) assert.ok(zh.includes(label), label)
  assert.match(zh, /展示 4 \/ 4 条背景资料/)
  assert.doesNotMatch(zh, /Context only|Partial results|Traded market quote/)
})

test('rendered list is capped at 12 and discloses the total', async () => {
  const html = await renderPanel(envelope({ items: Array.from({ length: 25 }, (_, i) => item({ id: `newsapi:${i}`, title: `Headline ${i}` })) }))
  assert.equal(count(html, 'class="context-item"'), 12)
  assert.match(text(html), /Showing 12 of 25 context items/)
  assert.match(text(html), /Headline 11/)
  assert.doesNotMatch(text(html), /Headline 12/)
})

// The existing SFC harness injects static imports only. Resolve the production
// async import to the REAL compiled panel here; the loader path and bindings are
// separately checked below and Vite builds the actual child chunk.
function integrationVue() {
  return { ...vue, defineAsyncComponent: loader => {
    assert.match(String(loader), /import\('\.\/SourceContextPanel\.vue'\)/)
    return vue.defineAsyncComponent(async () => panel())
  } }
}
const unexpected = name => () => { throw new Error(`Unexpected API call: ${name}`) }
async function renderDossier(context, lang = 'en') {
  return withLocale(lang, async () => {
    const component = buildDossier({
      vue: integrationVue(), '../../i18n': i18n, '../../utils/markdown': markdown, '../../utils/researchPdfExport': researchPdfExport,
      '../../utils/researchTranslation': researchTranslation, '../../utils/officialData': officialData,
      '../../utils/saveTextFile': { saveTextFile: unexpected('saveTextFile') },
      '../../api/research': {
        editDossier: unexpected('editDossier'), getArtifact: unexpected('getArtifact'),
        getResearchTranslation: unexpected('getResearchTranslation'), requestResearchTranslation: unexpected('requestResearchTranslation'),
        researchChartUrl: unexpected('researchChartUrl'), researchPdfUrl: () => '/research.pdf',
      },
    })
    return renderToString(vue.createSSRApp(component, { dossier: { report: '# Research', news_market_context: context } }))
  })
}
async function renderReport(context, lang = 'en', { markdownContent = '# Report\n\nBody.' } = {}) {
  return withLocale(lang, async () => {
    const calls = []
    const component = buildReport({
      vue: integrationVue(), '../../i18n': i18n, '../../utils/markdown': markdown, '../../utils/researchPdfExport': researchPdfExport,
      '../../utils/reportLanguages': reportLanguages, '../../utils/officialData': officialData,
      '../../utils/vizManifest': vizManifest, '../../utils/saveTextFile': { saveTextFile: unexpected('saveTextFile') },
      './BinaryForecastTable.vue': { default: buildTable({ vue, '../../i18n': i18n, '../../utils/binaryForecasts': binaryForecasts }) },
      '../../api/report': {
        getReport: async id => {
          calls.push(id)
          return { success: true, data: { report_id: id, status: 'completed', markdown_content: markdownContent,
            news_market_context: context, translation_status: { source_lang: lang } } }
        },
        getVizManifest: async () => ({ data: [] }), getForecast: async () => ({ data: { forecast: null } }),
        getReportOfficialData: async () => ({ available: false }),
        getSectionsPartial: unexpected('getSectionsPartial'), getReportTranslationMd: unexpected('getReportTranslationMd'),
        requestReportTranslation: unexpected('requestReportTranslation'), getReportTranslationStatus: unexpected('getReportTranslationStatus'),
        reportMarkdownUrl: () => '/report.md', reportPdfUrl: () => '/report.pdf', reportAssetUrl: unexpected('reportAssetUrl'),
      },
    })
    const setup = component.setup
    component.setup = async (props, ctx) => {
      const state = setup(props, ctx)
      await state.load()
      await settle()
      return state
    }
    const html = await renderToString(vue.createSSRApp(component, { reportId: 'report_context' }))
    assert.deepEqual(calls, ['report_context'])
    return html
  })
}

test('both real parent SFCs render the shared panel from their existing context carriers', async () => {
  for (const render of [renderDossier, renderReport]) {
    for (const lang of ['en', 'zh']) {
      const html = await render(envelope(), lang)
      assert.equal(count(html, 'class="source-context-panel"'), 1)
      assert.match(html, /Publisher outlook/)
      assert.match(text(html), lang === 'en' ? /Context only/ : /仅供背景参考/)
      assert.match(html, /href="https:\/\/publisher.example\/story"/)
    }
  }
})

test('real consumer integrations preserve failure statuses, safe output and the display bound', async () => {
  const context = envelope({ providers: { newsapi: { status: { state: 'unavailable', attempted: true } },
    kalshi: { status: { state: 'partial', attempted: true } } },
  items: Array.from({ length: 16 }, (_, i) => item({ id: `newsapi:${i}`, title: `Context ${i}`,
    snippet: '<script>alert(1)</script>', url: 'javascript:alert(1)' })) })
  for (const render of [renderDossier, renderReport]) {
    const html = await render(context)
    assert.equal(count(html, 'class="context-item"'), 12)
    assert.match(html, /data-state="unavailable"/)
    assert.match(html, /data-state="partial"/)
    assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/)
    assert.doesNotMatch(html, /href="javascript:|<script>|Verified empty/)
  }
})

test('both existing views stay compatible with legacy and disabled payloads', async () => {
  for (const render of [renderDossier, renderReport]) {
    for (const context of [undefined, {}, envelope({ enabled: false }),
      envelope({ providers: { newsapi: { status: { state: 'disabled', attempted: false } } }, items: [] })]) {
      assert.doesNotMatch(await render(context), /class="source-context-panel"|<details|<summary/)
    }
    const failed = await render(envelope({ providers: { newsapi: { status: { state: 'unavailable', attempted: true } } }, items: [] }))
    assert.match(failed, /class="source-context-panel"/)
    assert.match(failed, /data-state="unavailable"/)
    assert.doesNotMatch(failed, /Verified empty/)
  }
})

test('production templates use the same literal shared component and existing transport fields', () => {
  const dossier = readFileSync(dossierUrl, 'utf8')
  const report = readFileSync(reportUrl, 'utf8')
  for (const source of [dossier, report]) {
    assert.match(source, /defineAsyncComponent\(\(\) => import\('\.\/SourceContextPanel\.vue'\)\)/)
    assert.equal(count(source, '<SourceContextPanel '), 1)
  }
  assert.match(dossier, /:context="displayDossier.news_market_context"/)
  assert.match(report, /:context="displayContext"/)
  assert.match(report, /const res = await getReport\(reportId\)[\s\S]*?meta.value = data \|\| \{\}/)
  assert.doesNotMatch(readFileSync(panelUrl, 'utf8'), /v-html|fetch\(|getReport|setInterval/)
})

test('actual Kalshi normalization shape renders supplied dollar quotes in the panel and both consumers', async () => {
  const context = envelope({ providers: { kalshi: { status: { state: 'ok', attempted: true } } }, items: [kalshiNormalized] })
  for (const render of [renderPanel, renderDossier, renderReport]) {
    const html = await render(context)
    const body = text(html)
    assert.match(body, /Quote \/ forecast basis provider_reported_dollars_per_contract/)
    assert.match(body, /Units USD_per_contract/)
    assert.match(body, /Bid 0.42 Ask 0.44 Last quote 0.43/)
    assert.match(body, /Outcome Yes/)
    assert.match(body, /Quote time: Unknown/)
    assert.match(body, /Retrieved: 2026-10-18T12:00:00.000Z/)
    assert.doesNotMatch(body, /43%|42%|44%|0.56|0.58/)
    assert.match(html, /href="https:\/\/external-api.kalshi.com\/trade-api\/v2\/markets\/CPI-26-T3"/)
  }
})

test('sealed store-shaped carrier keeps direct provider statuses and canonical unit projection', async () => {
  // ContextClient._normalize preserves units/quote_basis and flat quote numbers;
  // it need not retain the adapter's price_unit/quote_units aliases.
  const stored = { ...kalshiNormalized }
  delete stored.price_unit
  delete stored.quote_units
  const context = envelope({ providers: { kalshi: { state: 'partial', attempted: true },
    newsapi: { state: 'verified_empty', attempted: true } }, items: [stored] })
  for (const render of [renderPanel, renderDossier, renderReport]) {
    const html = await render(context)
    assert.match(html, /data-state="partial"/)
    assert.match(html, /data-state="verified_empty"/)
    assert.match(text(html), /Units USD_per_contract Bid 0.42 Ask 0.44 Last quote 0.43/)
  }
})

test('ForecastReport distinguishes original research S1/S87 from reordered report citations without changing the capture', async () => {
  const context = envelope({ items: [
    item({ id: 'newsapi:original-s1', source_ref: 'S1', title: 'Original research source one',
      url: 'https://publisher.example/original-one' }),
    item({ id: 'newsapi:original-s87', source_ref: 'S87', title: 'Original research source eighty-seven',
      url: 'https://publisher.example/original-eighty-seven' }),
  ] })
  // Match the capture's sorted-key JSON hashing, excluding sha256 itself. The
  // display must not remap original source refs or rewrite the sealed envelope.
  const digest = ({ sha256, ...body }) => createHash('sha256').update(JSON.stringify(body, (_key, value) =>
    value && typeof value === 'object' && !Array.isArray(value)
      ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) : value)).digest('hex')
  context.sha256 = digest(context)
  const before = structuredClone(context)
  const markdownContent = '# Report\n\nReport finding [S1].\n\n## References\n'
    + '- [S1] [Different final-report source](https://report.example/final-source)\n'
  for (const lang of ['en', 'zh']) {
    const html = await renderReport(context, lang, { markdownContent })
    assert.match(html, /href="#ref-S1" title="Different final-report source"/)
    assert.match(html, /id="ref-S1" class="md-ref"[\s\S]*?href="https:\/\/report.example\/final-source"/)
    const contextHtml = html.match(/<details\b[^>]*class="source-context-panel"[^>]*>[\s\S]*?<\/details>/)?.[0]
    assert.ok(contextHtml, 'the real report must render its shared context panel')
    const label = lang === 'en' ? 'Original research ledger reference' : '原始研究来源台账编号'
    assert.ok(text(contextHtml).includes(`${label}: S1`))
    assert.ok(text(contextHtml).includes(`${label}: S87`))
    assert.match(contextHtml, /href="https:\/\/publisher.example\/original-one"/)
    assert.match(contextHtml, /href="https:\/\/publisher.example\/original-eighty-seven"/)
    assert.doesNotMatch(contextHtml, /\[S(?:1|87)\]|href="#ref-|md-cite|https:\/\/report.example\/final-source/)
    assert.equal(context.sha256, before.sha256, 'the supplied capture digest must be unchanged')
    assert.equal(digest(context), before.sha256, 'the sealed capture content must retain its digest')
    assert.deepEqual(context, before, 'all original capture references and values must be unchanged')
  }
})
