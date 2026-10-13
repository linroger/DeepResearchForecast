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

// Renders the real ForecastReport.vue + BinaryForecastTable.vue (script and template)
// through Vue's server renderer with REAL backend payloads from a real-bundle
// publication: GET /official-data (en/zh), the forecast binaries, the viz manifest.
const fixture = name => JSON.parse(readFileSync(new URL(`./fixtures/official/${name}`, import.meta.url), 'utf8'))
const OFFICIAL = { en: fixture('official_data.en_report.en.json'), zh: fixture('official_data.en_report.zh.json') }
const BINARIES = fixture('binary_forecasts.en_report.json').binary_forecasts
const MANIFEST = fixture('viz_manifest_official.en_report.json').data
const REPORT_ID = 'report_full_english'

const buildReport = compileSfc(new URL('../src/components/research/ForecastReport.vue', import.meta.url))
const buildTable = compileSfc(new URL('../src/components/research/BinaryForecastTable.vue', import.meta.url))
const settle = () => new Promise(resolve => setImmediate(resolve))

async function render({ sourceLang = 'en', official = lang => OFFICIAL[lang] } = {}) {
  i18n.locale.value = sourceLang
  const calls = []
  const saved = []
  const unexpected = name => () => { throw new Error(`Unexpected API call: ${name}`) }
  const api = {
    getReport: async id => ({ success: true, data: {
      report_id: id, status: 'completed', markdown_content: '# Recession outlook\n\nBody text.\n',
      translation_status: { source_lang: sourceLang },
    } }),
    getVizManifest: async () => ({ success: true, data: MANIFEST }),
    getForecast: async () => ({ success: true, data: { forecast: { binary_forecasts: BINARIES } } }),
    getReportOfficialData: async (id, lang) => {
      calls.push([id, lang])
      const body = official(lang)
      if (!body) throw Object.assign(new Error('report not publishable'), { response: { status: 409 } })
      return body
    },
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
    '../../utils/saveTextFile': { saveTextFile: (...args) => saved.push(args) },
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
  const html = await renderToString(vue.createSSRApp(report, { reportId: REPORT_ID }))
  i18n.locale.value = 'en'
  return { html, calls, saved, state }
}

const count = (html, needle) => html.split(needle).length - 1
const text = html => html.replace(/<!--[^]*?-->/g, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')

test('the dashboard shows official indicator tiles even without scenario cards', async () => {
  const { html, calls } = await render()
  assert.deepEqual(calls, [[REPORT_ID, 'en']])
  assert.equal(count(html, 'class="official-tile"'), 12)
  const body = text(html)
  assert.match(body, /Forecast Dashboard/)
  assert.match(body, /Official Indicators Stored official observations from research/)
  assert.match(body, /Unemployment Rate — United States S1 4\.2% 2026-09 · Monthly ▼ YoY -0\.2 pp/)
  assert.match(body, /Gross domestic product \(GDP\), Constant prices, Percent change: World S9 3\.056% 2026 · Annual unclassified publisher value/)
  // Non-percent units are shown under the value.
  assert.match(body, /Real Gross Domestic Product — United States S2 24408\.011 Billions of Chained 2017 Dollars 2026-Q2 · Quarterly ▲ YoY \+523\.448 \(\+2\.192%\)/)
  assert.match(body, /S11 40093219044989\.21 ≈ 40\.09 trillion U\.S\. dollars 2026-09 · Monthly/)
  assert.equal(count(html, 'class="dash-grid"'), 0, 'no scenario grid without scenarios')
  assert.ok(html.includes('href="https://fred.stlouisfed.org/series/UNRATE"'))
  // Sparklines for the 9 series with history; CSV only for the 3 carried series of the trimmed fixture.
  assert.equal(count(html, '<polyline'), 9)
  assert.equal(count(html, 'class="ot-csv"'), 3)
})

test('the binary table gains a data-anchor column fed by the report series labels', async () => {
  const { html } = await render()
  const body = text(html)
  assert.match(body, /Data anchor/)
  assert.ok(html.includes('bft-table bft-wide'))
  assert.match(body, /Unemployment Rate — United States ↗ \[S1\] ≥ 4\.5% · 2027-06 Latest 4\.2% \(2026-09\) gap \+0\.3 pp Base rate 30\.5% · n=82 Δ \+24\.5pp/)
  assert.match(body, /Central bank policy rates - United States - Monthly - End of period ↗ \[S7\] ≤ 3% · 2027-06 Latest 3\.875% \(2026-09\) gap -0\.875 pp/)
  assert.match(body, /Real-time Sahm Rule Recession Indicator — United States ↗ \[S5\] ≥ 0\.5 Percentage Points · 2027-06/)
  // The one binary without an anchor gets an empty cell; nine anchored cells link out.
  assert.equal(count(html, 'class="da-link"'), 9)
})

test('gallery cards carry the official source attribution', async () => {
  const { html } = await render()
  assert.equal(count(html, 'class="chart-fig"'), 5)
  assert.equal(count(html, 'class="chart-src"'), 5)
  const body = text(html)
  // Each entry reads like the audited Markdown caption: provider [S#]; units; frequency; adjustment.
  assert.ok(html.includes('FRED (Federal Reserve Bank of St. Louis)</a><span class="chart-src-sid"> [S1]</span>'
    + '<span class="chart-src-detail">; Percent; Monthly; SA</span>'))
  assert.match(body, /Source FRED \(Federal Reserve Bank of St\. Louis\) \[S1\] ; Percent; Monthly; SA/)
  assert.match(body, /Bank for International Settlements \(BIS\) \[S7\] ; Per cent per year; Monthly; adjustment unknown/)
  // Single-series detail charts name their series.
  assert.match(body, /Unemployment Rate · FRED \(Federal Reserve Bank of St\. Louis\) \[S1\]/)
})

test('a Chinese report view requests zh summaries and localizes every official label', async () => {
  const { html, calls } = await render({ sourceLang: 'zh' })
  assert.deepEqual(calls, [[REPORT_ID, 'zh']])
  const body = text(html)
  assert.match(body, /官方指标/)
  assert.match(body, /美国失业率 S1 4\.2% 2026-09 · 月度 ▼ 同比 -0\.2 个百分点/)
  assert.match(body, /未分类发布值/)
  assert.match(body, /数据锚点/)
  assert.match(body, /最新 4\.2% \(2026-09\) 距阈值 \+0\.3 个百分点 经验基率 30\.5%/)
  assert.match(body, /来源 FRED \(Federal Reserve Bank of St\. Louis\) \[S1\] ; Percent; 月度; SA/)
})

test('without official data the report renders exactly as before (no tiles, no anchor labels)', async () => {
  const { html, calls } = await render({ official: () => null })
  assert.deepEqual(calls, [[REPORT_ID, 'en']])
  assert.equal(count(html, 'forecast-dash'), 0)
  assert.equal(count(html, 'official-tile'), 0)
  // Anchors still render from forecast.json, labelled by series id.
  assert.match(text(html), /fred:UNRATE ↗ ≥ 4\.5% · 2027-06/)
  const unavailable = await render({ official: lang => ({ success: true, data: {
    report_id: REPORT_ID, available: false, indicators: [], official_data: null, lang } }) })
  assert.equal(count(unavailable.html, 'official-tile'), 0)
})

test('tile CSV buttons name their series for assistive technology (EN and ZH)', async () => {
  const names = html => [...html.matchAll(/<button class="ot-csv"[^>]*aria-label="([^"]*)"/g)].map(match => match[1])
  const en = await render()
  assert.deepEqual(names(en.html), [
    'Download Unemployment Rate — United States as CSV',
    'Download Gross domestic product (GDP), Constant prices, Percent change: World as CSV',
    'Download Debt to the Penny: Total Public Debt Outstanding — United States as CSV',
  ])
  const zh = await render({ sourceLang: 'zh' })
  assert.deepEqual(names(zh.html), ['下载美国失业率 CSV', '下载世界实际GDP增长率（IMF WEO） CSV', '下载美国联邦公共债务总额（每日） CSV'])
})

test('tile CSV export writes the stored carrier observations', async () => {
  const { state, saved } = await render()
  state.downloadOfficialCsv('fred:UNRATE')
  assert.equal(saved.length, 1)
  const [csv, filename, type] = saved[0]
  assert.equal(filename, 'fred_UNRATE.csv')
  assert.equal(type, 'text/csv;charset=utf-8')
  assert.ok(csv.startsWith('date,value\n2019-01-01,4\n'))
  state.downloadOfficialCsv('fred:NOT_CARRIED')
  assert.equal(saved.length, 1)
})

test('the data-anchor cell discloses a seasonal basis and does not flag a pooled-season rate', async () => {
  // Real backend output (fixtures/official/binary_forecast.mts_nsa_pooled.json): the Part-1
  // table cell reads '24% (n=59, h=13; start months pooled, not seasonally adjusted)'.
  const pooled = fixture('binary_forecast.mts_nsa_pooled.json')
  const table = buildTable({ vue, '../../utils/binaryForecasts': binaryForecasts, '../../i18n': i18n })
  try {
    for (const [locale, note] of [
      ['en', 'start months pooled, not seasonally adjusted'],
      ['zh', '合并所有起始月份，未经季节调整'],
    ]) {
      i18n.locale.value = locale
      const html = await renderToString(vue.createSSRApp(table, { forecast: pooled, lang: locale }))
      assert.equal(count(html, 'da-divergent'), 0, locale)
      assert.equal(count(html, 'class="da-season"'), 1, locale)
      assert.ok(text(html).includes(note), `${locale} cell`)
      const title = html.match(/class="cell-data" title="([^"]*)"/)[1]
      assert.ok(title.includes(note), `${locale} tooltip`)
      assert.ok(!/flagged by the quality check|质量检查已标记/.test(title), `${locale} tooltip flag`)
    }
  } finally {
    i18n.locale.value = 'en'
  }
})

test('a seasonal-profile base rate is disclosed with the backend wording and stays flagged', async () => {
  // Real backend output (fixtures/official/binary_forecast.eia_nsa_profile.json): the Part-1
  // table cell reads '0% (n=112, h=5; same-month seasonal mean plus pooled deviations, not
  // seasonally adjusted)' and binary_quality.base_rate_divergence lists F1 (+40 pp).
  const profile = fixture('binary_forecast.eia_nsa_profile.json')
  const table = buildTable({ vue, '../../utils/binaryForecasts': binaryForecasts, '../../i18n': i18n })
  try {
    for (const [locale, note, flag] of [
      ['en', 'same-month seasonal mean plus pooled deviations, not seasonally adjusted', 'over 25pp, flagged by the quality check'],
      ['zh', '同月季节均值加合并偏差，未经季节调整', '超过 25pp，质量检查已标记'],
    ]) {
      i18n.locale.value = locale
      const html = await renderToString(vue.createSSRApp(table, { forecast: profile, lang: locale }))
      assert.equal(count(html, 'da-divergent'), 1, locale)
      assert.equal(count(html, 'class="da-season"'), 1, locale)
      assert.ok(text(html).includes(note), `${locale} cell`)
      const title = html.match(/class="cell-data" title="([^"]*)"/)[1]
      assert.ok(title.includes(note), `${locale} tooltip`)
      assert.ok(title.includes(flag), `${locale} tooltip flag`)
    }
  } finally {
    i18n.locale.value = 'en'
  }
})

test('every seasonal basis reads exactly like forecast_extractor.EMPIRICAL_SEASONAL_BASIS_TEXT', async () => {
  // The backend tables, briefs and Part-1 cells use this mapping; the data-anchor cell and
  // its tooltip must disclose the same full wording, in both languages, for every basis.
  const source = readFileSync(new URL('../../backend/app/services/forecast_extractor.py', import.meta.url), 'utf8')
  const block = source.match(/^EMPIRICAL_SEASONAL_BASIS_TEXT = \{([^]*?)^\}/m)[1]
  const wording = [...block.matchAll(/"(\w+)":\s*\(\s*"([^"]*)",\s*"([^"]*)"\s*\)/g)]
    .map(([, basis, en, zh]) => ({ basis, en, zh }))
  assert.deepEqual(wording.map(entry => entry.basis).sort(),
    ['all_start_months', 'same_calendar_month', 'seasonal_profile'])
  const raw = fixture('binary_forecast.eia_nsa_profile.json').binary_forecasts[0]
  const table = buildTable({ vue, '../../utils/binaryForecasts': binaryForecasts, '../../i18n': i18n })
  try {
    for (const { basis, en, zh } of wording) {
      const forecast = { binary_forecasts: [{
        ...raw,
        data_anchor: { ...raw.data_anchor, empirical_base_rate: { ...raw.data_anchor.empirical_base_rate, seasonal_basis: basis } },
      }] }
      for (const [locale, note] of [['en', en], ['zh', zh]]) {
        i18n.locale.value = locale
        const html = await renderToString(vue.createSSRApp(table, { forecast, lang: locale }))
        const season = html.match(/<div class="da-season">([^<]*)<\/div>/)
        assert.ok(season, `${basis} ${locale}`)
        assert.equal(season[1].trim(), note, `${basis} ${locale} cell`)
        const title = html.match(/class="cell-data" title="([^"]*)"/)[1]
        assert.ok(title.includes(`; ${note}`) || title.includes(`；${note}`), `${basis} ${locale} tooltip`)
      }
    }
  } finally {
    i18n.locale.value = 'en'
  }
})
