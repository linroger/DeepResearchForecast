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

test('generated attributes and inline code are never parsed as markdown', () => {
  const html = renderMarkdown([
    '![literal [S1] **alt**](https://example.com/chart__[S1]__.png)',
    '[source](https://example.com/a__[S1]__?x=1&y=2)',
    '`[S1] [not a link](https://example.com) **literal**`',
    '', '## References', '- [S1] Source one',
  ].join('\n'), { resolveUrl: url => url, citations: { S1: 'A **title** [S2] "quoted"' } })
  assert.match(html, /src="https:\/\/example.com\/chart__\[S1\]__\.png" alt="literal \[S1\] \*\*alt\*\*"/)
  assert.match(html, /href="https:\/\/example.com\/a__\[S1\]__\?x=1&amp;y=2"/)
  assert.match(html, /<code>\[S1\] \[not a link\]\(https:\/\/example.com\) \*\*literal\*\*<\/code>/)
  assert.doesNotMatch(html, /(?:src|href|alt|title)="[^"\n]*<(?:sup|a|strong|em|code)/)
})

test('asset resolvers and interactive links cannot inject attributes or unsafe schemes', () => {
  for (const unsafe of ['javascript:alert(1)', 'data:text/html;base64,PHNjcmlwdD4=', 'java\tscript:alert(1)']) {
    const html = renderMarkdown('![plot](charts/x.png) [open](charts/x.html)', {
      resolveUrl: () => unsafe, interactiveHref: () => unsafe,
    })
    assert.doesNotMatch(html, /(?:src|href)="(?:javascript:|data:|java\t)/)
    assert.doesNotMatch(html, /<img/)
  }
  const html = renderMarkdown('![plot](charts/x.png)', {
    resolveUrl: () => '/api/chart.png?label=" onerror="alert(1)',
    interactiveHref: () => '/api/chart.html?label=" onclick="alert(1)',
  })
  assert.doesNotMatch(html, /" (?:onerror|onclick)="/)
})

test('link destinations cannot navigate to executable data while raster data images still render', () => {
  const html = renderMarkdown('[open](data:text/html;base64,PHNjcmlwdD4=) ![plot](data:image/png;base64,YQ==)', { resolveUrl: x => x })
  assert.doesNotMatch(html, /href="data:/)
  assert.match(html, /src="data:image\/png;base64,YQ=="/)
})

test('heading and citation discovery agree with rendering for comments and varied code fences', async () => {
  const { extractHeadings } = await import('../src/utils/markdown.js')
  for (const [open, close] of [['~~~md', '~~~'], ['````markdown', '````'], ['  ```c++', '  ```']]) {
    const md = ['# Real', open, '# Hidden', '## References', '- [S1] Fake source', ...(open.includes('````') || open.includes('~~~') ? ['```'] : []), close,
      '<!--', '# Comment heading', '-->', 'Body [S1].', '## **Visible**'].join('\n')
    const html = renderMarkdown(md)
    const headings = extractHeadings(md)
    assert.deepEqual(headings.map(h => h.text), ['Real', 'Visible'])
    assert.ok(headings.every(h => html.includes(`id="${h.id}"`)))
    assert.doesNotMatch(html, /href="#ref-S1"/)
    assert.match(html, /<pre class="md-pre"><code># Hidden/)
  }
})
