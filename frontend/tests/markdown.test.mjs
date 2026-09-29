import assert from 'node:assert/strict'
import test from 'node:test'

import { renderMarkdown } from '../src/utils/markdown.js'

test('pipeline comment markers are not rendered as visible text', () => {
  const html = renderMarkdown([
    '<!-- binary-forecast-block:start -->',
    '## Part 1 — Binary Forecasts',
    '',
    '<!-- viz:charts/binary_forecast_dotplot.html -->',
    'Independent forecasts follow.',
    '<!-- a comment',
    'spanning lines -->',
    'After the comment.',
  ].join('\n'))
  assert.ok(!html.includes('&lt;!--'))
  assert.ok(!html.includes('viz:charts'))
  assert.ok(!html.includes('spanning lines'))
  assert.match(html, /Part 1 — Binary Forecasts/)
  assert.match(html, /<p>Independent forecasts follow\.<\/p>/)
  assert.match(html, /<p>After the comment\.<\/p>/)
})

test('comments inside fenced code stay verbatim', () => {
  const html = renderMarkdown('```\n<!-- kept -->\n```')
  assert.match(html, /&lt;!-- kept --&gt;/)
})
