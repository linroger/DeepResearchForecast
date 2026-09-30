import assert from 'node:assert/strict'
import test from 'node:test'

import {
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
  assert.equal(
    localizeChartCaption('Market-Implied P(yes) History vs Model', 'zh'),
    '市场隐含 P(是) 历史与模型对比',
  )
  assert.equal(localizeChartCaption('Scenario Probabilities', 'en'), 'Scenario Probabilities')
  assert.equal(localizeChartCaption('Scenario Probabilities', ''), 'Scenario Probabilities')
  assert.equal(localizeChartCaption('A future chart', 'zh'), 'A future chart')
  assert.equal(localizeChartCaption(undefined, 'zh'), '')
})
