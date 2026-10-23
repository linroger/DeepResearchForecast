/**
 * Dependency-free Markdown → HTML renderer, tuned for the MiroFish research /
 * forecast reports (which use headings, bold/italic, blockquotes, lists, tables,
 * `code`, fenced blocks, horizontal rules, links and `[citation:Title](url)`).
 *
 * It is intentionally small and safe: all raw text is HTML-escaped first, then a
 * fixed set of block/inline rules add markup. No user HTML is ever passed through.
 *
 * CITE-1：行内引文标记 [S3] / [S3-a] 渲染为上标引用；当文中存在 References/参考来源
 * 章节的 [Sxx] 条目时上标带 #ref-Sxx 锚点跳转，否则降级为纯上标（如 Dossier）。
 * VIZ-2：opts.interactiveHref 提供 manifest 驱动的 charts/*.png → .html 交互孪生链接。
 *
 * Usage:  import { renderMarkdown, extractHeadings } from '../utils/markdown'
 *         el.innerHTML = renderMarkdown(md)
 */

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

// Stable slug for heading anchors (used by the section nav).
export function slugify(text) {
  return String(text)
    .toLowerCase()
    .trim()
    .replace(/[^\w一-龥\s-]/g, '')
    .replace(/\s+/g, '-')
    .slice(0, 80) || 'h'
}

// Validate both authored and resolver-provided URLs; escaping alone cannot reject schemes.
function safeAssetUrl(value, resolve, image = false) {
  if (typeof value !== 'string' || !value || /[\u0000-\u0020\u007f\\]/.test(value)) return ''
  if (/^https?:\/\//i.test(value) || /^\//.test(value)) return value
  if (!image && /^(mailto:|#)/i.test(value)) return value
  if (image && /^data:image\/(?:png|jpeg|gif|webp|avif);base64,[a-z0-9+/=]+$/i.test(value)) return value
  if (/^[a-z][a-z0-9+.-]*:/i.test(value)) return ''
  return resolve ? safeAssetUrl(resolve(value), null, image) : ''
}

function openingFence(line) {
  const match = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/)
  if (!match || (match[1][0] === '`' && match[2].includes('`'))) return null
  return match[1]
}

function closesFence(line, fence) {
  const match = line.match(/^ {0,3}(`{3,}|~{3,})[ \t]*$/)
  return Boolean(match && match[1][0] === fence[0] && match[1].length >= fence.length)
}

// Preserve offsets for marked-block extraction. All consumers use the same fence/comment
// grammar, so headings, reference discovery and bridge parsing agree with rendered code.
function* markdownLines(md) {
  let fence = null
  let inComment = false
  for (const match of String(md).matchAll(/[^\r\n]*(?:\r\n|\r|\n|$)/g)) {
    if (!match[0]) continue
    const line = match[0].replace(/[\r\n]+$/, '')
    const row = { line, start: match.index, end: match.index + line.length, kind: 'text' }
    if (fence) {
      row.kind = 'code'
      if (closesFence(line, fence)) fence = null
    } else if (inComment) {
      row.kind = 'comment-body'
      if (line.includes('-->')) inComment = false
    } else if ((fence = openingFence(line))) {
      row.kind = 'code'
    } else if (/^\s*<!--/.test(line)) {
      row.kind = 'comment'
      inComment = !line.includes('-->')
    }
    yield row
  }
}

// ---------- CITE-1：引文标记（[S3] / [S3-a]）可点击化 ----------
// 报告正文的行内引文标记与 References/参考来源 章节标题、条目的识别正则。
// (?!\() 排除普通链接标签 [S3](url) —— 那是链接规则的职责。
const CITE_RE = /\[S(\d+)(-[A-Za-z])?\](?!\()/g
const REF_HEADING_RE = /references|sources|bibliography|参考|来源|文献/i
const REF_ITEM_RE = /^\[S(\d+)(-[A-Za-z])?\]\s*[:：.、,，—–-]?\s*(.*)$/

// 引文标记 key（'S3' / 'S3-a'，与 <li id="ref-…"> 锚点一致）。
function citeKey(n, letter) {
  return 'S' + n + (letter ? letter.toLowerCase() : '')
}

// 预扫描：仅当 References 类章节内存在以 [Sxx] 开头的列表条目（即锚点会被生成）时，
// 行内引文才渲染为 <a href="#ref-…">；否则退化为纯上标（Dossier 等无 References 上下文）。
// 围栏代码块内的内容不参与判定（与 renderMarkdown 的 fence 分支一致）。
function detectRefAnchors(lines) {
  let inRefs = false
  for (const { line, kind } of markdownLines(lines.join('\n'))) {
    if (kind !== 'text') continue
    const h = line.match(/^(#{1,6})\s+(.*)$/)
    if (h) { inRefs = REF_HEADING_RE.test(h[2]); continue }
    if (inRefs && /^\s*([-*+]|\d+\.)\s+\[S\d+(-[A-Za-z])?\]/.test(line)) return true
  }
  return false
}

function emphasis(text) {
  return text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/__([^_]+)__/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
}

// Only source text is parsed. Generated tags, attributes and code spans are opaque to
// subsequent markdown rules (including citation and emphasis substitution).
function renderInline(text, opts) {
  const resolve = typeof opts?.resolveUrl === 'function' ? opts.resolveUrl : null
  const interactive = typeof opts?.interactiveHref === 'function' ? opts.interactiveHref : null
  let t = String(text)
  let prefix = '\u0000MDTOKEN'
  while (t.includes(prefix)) prefix += 'X'
  const tokenRe = new RegExp(`${prefix}(\\d+)\u0000`, 'g')
  const fragments = []
  const restore = (value, literal = false) => value.replace(tokenRe, (_, index) =>
    literal ? fragments[index].literal : fragments[index].html)
  const stash = (html, literal) => {
    const token = `${prefix}${fragments.length}\u0000`
    fragments.push({ html, literal })
    return token
  }
  t = t.replace(/(`+)([^]*?)\1(?!`)/g, (all, ticks, code) =>
    stash('<code>' + escapeHtml(code) + '</code>', all))
  // A single nested bracket level admits source markers in labels/alt text.
  const imageRe = /!\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g
  t = t.replace(imageRe, (all, alt, url) => {
    const plainAlt = escapeHtml(restore(alt, true))
    const src = resolve && !url.includes(prefix) ? safeAssetUrl(url, resolve, true) : ''
    if (!src) return stash(plainAlt, restore(alt, true))
    const img = `<img class="md-img" src="${escapeHtml(src)}" alt="${plainAlt}" loading="lazy" />`
    const ihref = interactive ? safeAssetUrl(interactive(url), null) : ''
    const html = ihref
      ? `<span class="md-img-wrap">${img}<a class="md-img-interactive" href="${escapeHtml(ihref)}" target="_blank" rel="noopener noreferrer">交互版 Interactive ↗</a></span>`
      : img
    return stash(html, all)
  })
  const linkRe = /\[((?:[^\[\]]|\[[^\[\]]*\])+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g
  t = t.replace(linkRe, (all, label, url) => {
    const clean = restore(emphasis(escapeHtml(label.replace(/^citation:/i, ''))))
    const href = (!url.includes(prefix) && safeAssetUrl(url, resolve)) || '#'
    const external = /^(https?:|\/\/)/i.test(href)
    return stash(`<a href="${escapeHtml(href)}"${external ? ' target="_blank" rel="noopener noreferrer"' : ''}>${clean}</a>`, all)
  })
  t = t.replace(CITE_RE, (all, n, letter) => {
    const key = citeKey(n, letter)
    const cite = opts?.citations?.[key]
    const tip = cite == null ? '' : (typeof cite === 'string' ? cite : String(cite.title || ''))
    const title = tip ? ` title="${escapeHtml(tip)}"` : ''
    const label = n + (letter ? letter.slice(1).toLowerCase() : '')
    return stash(opts?._citeAnchors
      ? `<sup class="md-cite"><a href="#ref-${key}"${title}>${label}</a></sup>`
      : `<sup class="md-cite"${title}>${label}</sup>`, all)
  })
  return restore(emphasis(escapeHtml(t)))
}

function renderTable(rows, opts) {
  // rows: array of raw markdown table lines (without the separator row)
  const parseRow = (line) => line.replace(/^\||\|$/g, '').split('|').map(c => c.trim())
  const header = parseRow(rows[0])
  const body = rows.slice(2) // skip header + separator
  let html = '<table class="md-table"><thead><tr>'
  header.forEach(h => { html += `<th>${renderInline(h, opts)}</th>` })
  html += '</tr></thead><tbody>'
  body.forEach(line => {
    if (!line.trim()) return
    const cells = parseRow(line)
    html += '<tr>'
    cells.forEach(c => { html += `<td>${renderInline(c, opts)}</td>` })
    html += '</tr>'
  })
  html += '</tbody></table>'
  // 宽表（如 Market Cross-Check）用横向滚动容器包裹，避免撑破正文导致整页横向滚动。
  return '<div class="md-table-wrap">' + html + '</div>'
}

// opts.resolveUrl(rel) —— 可选相对资源解析器（见 renderInline）。缺省时行为与历史完全一致。
// opts.citations / opts.interactiveHref —— 可选（CITE-1 / VIZ-2，见 renderInline）。
export function renderMarkdown(md, opts) {
  if (!md) return ''
  const src = String(md).replace(/\r\n/g, '\n').replace(/\r/g, '\n')
  const lines = src.split('\n')
  const out = []
  let i = 0

  // CITE-1：预扫描决定引文上标是否带锚点链接（无 References 条目 → 纯上标降级）。
  const o = Object.assign({}, opts || {}, { _citeAnchors: detectRefAnchors(lines) })
  // 当前是否处于 References/参考来源 类章节（决定列表条目是否生成 ref 锚点）。
  let inRefs = false
  // 已发放的 ref 锚点 id（同 key 多条目只锚第一条，保证 id 唯一）。
  const usedRefIds = new Set()

  const flushParagraph = (buf) => {
    if (buf.length) {
      out.push('<p>' + renderInline(buf.join(' '), o) + '</p>')
      buf.length = 0
    }
  }
  const paraBuf = []

  while (i < lines.length) {
    let line = lines[i]

    // fenced code block
    const fence = openingFence(line)
    if (fence) {
      flushParagraph(paraBuf)
      const code = []
      i++
      while (i < lines.length && !closesFence(lines[i], fence)) { code.push(lines[i]); i++ }
      i++ // closing fence
      out.push('<pre class="md-pre"><code>' + escapeHtml(code.join('\n')) + '</code></pre>')
      continue
    }

    // HTML comments are pipeline markers (<!-- viz:charts/… -->,
    // <!-- binary-forecast-block:start -->), never reader text: drop them instead of
    // escaping them into the page.  A comment may span lines until its "-->".
    if (/^\s*<!--/.test(line)) {
      flushParagraph(paraBuf)
      while (i < lines.length && !/-->/.test(lines[i])) i++
      i++
      continue
    }

    // table (header line + separator of dashes/pipes)
    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1]) && lines[i + 1].includes('-')) {
      flushParagraph(paraBuf)
      const tbl = []
      while (i < lines.length && /\|/.test(lines[i]) && lines[i].trim() && !openingFence(lines[i])) { tbl.push(lines[i]); i++ }
      out.push(renderTable(tbl, o))
      continue
    }

    // heading
    const h = line.match(/^(#{1,6})\s+(.*)$/)
    if (h) {
      flushParagraph(paraBuf)
      const level = h[1].length
      const text = h[2].replace(/\s+#*\s*$/, '')
      // CITE-1：进入/离开 References 类章节（决定后续列表条目是否生成 ref 锚点）。
      inRefs = REF_HEADING_RE.test(text)
      const id = slugify(text)
      out.push(`<h${level} id="${id}" class="md-h md-h${level}">${renderInline(text, o)}</h${level}>`)
      i++
      continue
    }

    // horizontal rule
    if (/^\s*([-*_])\s*(\1\s*){2,}$/.test(line)) {
      flushParagraph(paraBuf)
      out.push('<hr class="md-hr"/>')
      i++
      continue
    }

    // blockquote (possibly multi-line)
    if (/^\s*>/.test(line)) {
      flushParagraph(paraBuf)
      const quote = []
      while (i < lines.length && /^\s*>/.test(lines[i])) {
        quote.push(lines[i].replace(/^\s*>\s?/, ''))
        i++
      }
      out.push('<blockquote class="md-quote">' + renderInline(quote.join(' '), o) + '</blockquote>')
      continue
    }

    // lists (unordered / ordered), supports simple nesting by indentation
    if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
      flushParagraph(paraBuf)
      const ordered = /^\s*\d+\.\s+/.test(line)
      const tag = ordered ? 'ol' : 'ul'
      out.push(`<${tag} class="md-list">`)
      while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
        const item = lines[i].replace(/^\s*([-*+]|\d+\.)\s+/, '')
        // CITE-1：References 章节内以 [Sxx] 开头的条目 → 锚定 <li id="ref-Sxx">，
        // 供正文引文上标 #ref-Sxx 跳转；标记本体以标签样式呈现而非再次上标化。
        const rm = inRefs ? item.match(REF_ITEM_RE) : null
        if (rm) {
          const key = citeKey(rm[1], rm[2])
          const idAttr = usedRefIds.has(key) ? '' : ` id="ref-${key}"`
          usedRefIds.add(key)
          out.push(`<li${idAttr} class="md-ref"><span class="md-ref-tag">${key}</span> ` + renderInline(rm[3], o) + '</li>')
        } else {
          out.push('<li>' + renderInline(item, o) + '</li>')
        }
        i++
      }
      out.push(`</${tag}>`)
      continue
    }

    // blank line → paragraph break
    if (!line.trim()) {
      flushParagraph(paraBuf)
      i++
      continue
    }

    // accumulate paragraph text
    paraBuf.push(line.trim())
    i++
  }
  flushParagraph(paraBuf)
  return out.join('\n')
}

/**
 * Extract the heading outline for a section nav.
 * @returns {Array<{level:number, text:string, id:string}>}
 */
export function extractHeadings(md) {
  if (!md) return []
  const out = []
  for (const { line, kind } of markdownLines(md)) {
    if (kind !== 'text') continue
    const h = line.match(/^(#{1,6})\s+(.*)$/)
    if (h) {
      const raw = h[2].replace(/\s+#*\s*$/, '')
      const text = raw.replace(/[*_`]/g, '').trim()
      if (text) out.push({ level: h[1].length, text, id: slugify(raw) })
    }
  }
  return out
}

/**
 * Classify a single marked block. Only standalone markers outside code/comments count.
 * Invalid boundaries are distinct from absent markers: consumers must not silently
 * display ambiguous simulated content as ordinary report prose.
 */
export function parseMarkedBlock(md, startMarker, endMarker) {
  const src = String(md || '')
  if (!src || !startMarker || !endMarker || startMarker === endMarker) return { status: 'absent' }
  let prefixLength = 0
  while (prefixLength < startMarker.length && startMarker[prefixLength] === endMarker[prefixLength]) prefixLength++
  const shared = startMarker.slice(0, prefixLength)
  const markerPrefix = shared.endsWith(':') ? shared : ''
  const markers = []
  for (const row of markdownLines(src)) {
    if (row.kind === 'code' || row.kind === 'comment-body') continue
    // Inline code examples are literal too. Malformed marker comments (including an
    // unfinished start marker) remain invalid, rather than concealing a second block.
    if (row.kind === 'comment' && !row.line.trimStart().startsWith(markerPrefix || startMarker)
      && !row.line.trimStart().startsWith(endMarker)) continue
    const prose = row.line.replace(/(`+)([^]*?)\1(?!`)/g, '')
    if (!prose.includes(startMarker) && !prose.includes(endMarker)
      && !(markerPrefix && prose.includes(markerPrefix))) continue
    const marker = row.line.trim()
    if (marker !== startMarker && marker !== endMarker) return { status: 'invalid' }
    const start = row.start + row.line.indexOf(marker)
    markers.push({ marker, start, end: start + marker.length })
  }
  if (!markers.length) return { status: 'absent' }
  if (markers.length !== 2 || markers[0].marker !== startMarker || markers[1].marker !== endMarker) {
    return { status: 'invalid' }
  }
  return {
    status: 'valid',
    before: src.slice(0, markers[0].start),
    inner: src.slice(markers[0].end, markers[1].start),
    after: src.slice(markers[1].end),
  }
}

/** Compatibility helper for consumers that only need a valid split. */
export function splitMarkedBlock(md, startMarker, endMarker) {
  const { status, ...split } = parseMarkedBlock(md, startMarker, endMarker)
  return status === 'valid' ? split : null
}
