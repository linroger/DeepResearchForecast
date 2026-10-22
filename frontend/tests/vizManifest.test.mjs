import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  chartAttribution,
  filterVizGalleryByMarkdown,
  localizeChartCaption,
  normalizeVizGallery,
  safeChartPath,
} from '../src/utils/vizManifest.js'

test('preserves schema-v2 HTML-only Plotly artifacts', () => {
  assert.deepEqual(
    normalizeVizGallery([{ id: 'timeline', type: 'html', path: 'charts/timeline.html' }]),
    [{
      id: 'timeline',
      imagePath: '',
      interactivePath: 'charts/timeline.html',
      caption: '',
      sourceCaption: '',
      sources: [],
    }],
  )
})

test('folds legacy twins regardless of row ordering', () => {
  const htmlFirst = [
    { type: 'html', path: 'charts/actors.html', caption: 'Actor network' },
    { type: 'png', path: 'charts/actors.png' },
  ]
  const pngFirst = [...htmlFirst].reverse()
  const expected = [{
    id: 'charts/actors',
    imagePath: 'charts/actors.png',
    interactivePath: 'charts/actors.html',
    caption: 'Actor network',
    sourceCaption: '',
    sources: [],
  }]
  assert.deepEqual(normalizeVizGallery(htmlFirst), expected)
  assert.deepEqual(normalizeVizGallery(pngFirst), expected)
})

test('accepts contained nested chart paths', () => {
  assert.equal(safeChartPath('charts/topic/forecast.png'), 'charts/topic/forecast.png')
  assert.deepEqual(
    normalizeVizGallery([{ type: 'png', path: 'charts/topic/forecast.png' }])[0].imagePath,
    'charts/topic/forecast.png',
  )
})

test('uses the extension instead of a contradictory declared type', () => {
  const result = normalizeVizGallery([{ type: 'image', path: 'charts/timeline.html' }])
  assert.equal(result.length, 1)
  assert.equal(result[0].imagePath, '')
  assert.equal(result[0].interactivePath, 'charts/timeline.html')
})

test('gallery keeps only fallback figures not already embedded in markdown', () => {
  const gallery = normalizeVizGallery([
    { type: 'html', path: 'charts/timeline.html', png_path: 'charts/timeline.png' },
    { type: 'html', path: 'charts/actors.html', png_path: 'charts/actors.png' },
  ])
  const filtered = filterVizGalleryByMarkdown(
    gallery,
    '# Report\n\n<!-- viz:charts/timeline.html -->\n![Timeline](charts/timeline.png)',
  )
  assert.equal(filtered.length, 1)
  assert.equal(filtered[0].interactivePath, 'charts/actors.html')
})

test('a viz marker alone does not suppress a missing translated figure', () => {
  const gallery = normalizeVizGallery([
    { type: 'html', path: 'charts/timeline.html', png_path: 'charts/timeline.png' },
  ])
  const filtered = filterVizGalleryByMarkdown(
    gallery,
    '# Translated report\n\n<!-- viz:charts/timeline.html -->\nThe translated image was dropped.',
  )
  assert.equal(filtered.length, 1)
  assert.equal(filtered[0].imagePath, 'charts/timeline.png')
})

test('an HTML-only chart is suppressed only by an actual markdown link', () => {
  const gallery = normalizeVizGallery([
    { type: 'html', path: 'charts/actor_network.html' },
  ])
  assert.equal(filterVizGalleryByMarkdown(
    gallery,
    '<!-- viz:charts/actor_network.html -->',
  ).length, 1)
  assert.equal(filterVizGalleryByMarkdown(
    gallery,
    '[Open chart](charts/actor_network.html)',
  ).length, 0)
})

test('rejects traversal, encoded traversal, absolute, and backslash paths', () => {
  for (const path of [
    '../secret.png',
    'charts/../secret.png',
    'charts/%2e%2e/secret.png',
    'charts/%252e%252e/secret.png',
    'charts/.\n./secret.png',
    'charts/.\t./secret.png',
    'charts/.\r./secret.png',
    '/charts/a.png',
    'charts\\a.png',
  ]) {
    assert.equal(safeChartPath(path), '')
  }
})

test('localizes builder chart captions only for the Chinese view', () => {
  assert.equal(localizeChartCaption('Scenario Probabilities', 'zh'), '情景概率')
  assert.equal(localizeChartCaption('Event Timeline ', 'zh'), '事件时间线')
  // Simulated charts carry "Simulated" in the title (ADR 0003); the caption table
  // mirrors backend CHART_TITLES_ZH exactly (test_report_zh_presentation.py).
  assert.equal(
    localizeChartCaption('Simulated outcome-share trajectory', 'zh'),
    '模拟结果份额轨迹',
  )
  assert.equal(localizeChartCaption('Scenario Probabilities', 'en'), 'Scenario Probabilities')
  assert.equal(localizeChartCaption('Scenario Probabilities', ''), 'Scenario Probabilities')
  assert.equal(localizeChartCaption('A future chart', 'zh'), 'A future chart')
  assert.equal(localizeChartCaption(undefined, 'zh'), '')
})

// REAL GET /api/report/<id>/viz-manifest official-data items (EN and ZH publications).
const manifestFixture = name => JSON.parse(
  readFileSync(new URL(`./fixtures/official/${name}`, import.meta.url), 'utf8'),
).data

function captionFrom(entries, prefix) {
  return prefix + entries.map(entry => `[${entry.label}](<${entry.href}>)`
    + (entry.sourceId ? ` [${entry.sourceId}]` : '') + `; ${entry.detail}`).join(' · ')
}

test('gallery cards keep official-data attribution identical to the audited source caption', () => {
  for (const [name, lang, prefix] of [
    ['viz_manifest_official.en_report.json', 'en', 'Source: '],
    ['viz_manifest_official.zh_report.json', 'zh', '来源：'],
  ]) {
    const manifest = manifestFixture(name)
    const gallery = normalizeVizGallery(manifest)
    assert.equal(gallery.length, manifest.length)
    for (const [index, card] of gallery.entries()) {
      assert.equal(card.sourceCaption, manifest[index].source_caption)
      assert.equal(card.sources.length, manifest[index].provenance.length)
      const fromProvenance = chartAttribution(card, lang)
      assert.equal(captionFrom(fromProvenance, prefix), manifest[index].source_caption, `${name} ${card.id}`)
      // Without provenance the parsed caption yields the same links, tags and details.
      const fromCaption = chartAttribution({ ...card, sources: [] }, lang)
      assert.deepEqual(fromCaption, fromProvenance.map(entry => ({ ...entry, title: '' })))
    }
  }
  const [dashboard] = normalizeVizGallery(manifestFixture('viz_manifest_official.en_report.json'))
  assert.deepEqual(chartAttribution(dashboard, 'en')[0], {
    label: 'FRED (Federal Reserve Bank of St. Louis)',
    href: 'https://fred.stlouisfed.org/series/UNRATE',
    sourceId: 'S1',
    title: 'Unemployment Rate',
    detail: 'Percent; Monthly; SA',
  })
  // A zh view of an English report localizes frequency and unknown adjustment.
  const bis = chartAttribution(dashboard, 'zh').find(entry => entry.sourceId === 'S7')
  assert.equal(bis.detail, 'Per cent per year; 月度; 季节调整未知')
})

test('attribution is empty for non-official charts and unsafe links are dropped', () => {
  const [plain] = normalizeVizGallery([{ type: 'png', path: 'charts/scenarios.png', caption: 'Scenario Probabilities' }])
  assert.deepEqual(chartAttribution(plain, 'en'), [])
  const [unsafe] = normalizeVizGallery([{
    type: 'png',
    path: 'charts/official_indicators.png',
    source_caption: 'Source: [Evil](<javascript:alert(1)>) [S1]; Percent; Monthly; SA',
    provenance: [{ provider_name: 'Evil', source_url: 'javascript:alert(1)', source_id: 'S1x', units: 'Percent',
      frequency: 'M', seasonal_adjustment: 'SA' }],
  }])
  const [entry] = chartAttribution(unsafe, 'en')
  assert.equal(entry.href, '')
  assert.equal(entry.sourceId, '')
  assert.equal(chartAttribution({ ...unsafe, sources: [] }, 'en')[0].href, '')
  assert.deepEqual(chartAttribution(null, 'en'), [])
})
