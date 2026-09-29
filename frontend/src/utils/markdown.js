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

// 相对资源地址解析（图片/链接）：绝对 http(s)/data 原样；以 / 开头的同源绝对路径原样；
// 其它显式协议（javascript: 等）拒绝为空串；相对路径（如 'charts/xxx.png'）交给 resolve()
// 重写到 API base。无 resolve 时相对路径无法定位 → 返回空串（调用方据此退化）。
function safeAssetUrl(url, resolve) {
  if (/^(https?:|data:)/i.test(url)) return url
  if (/^\//.test(url)) return url
  if (/^[a-z][a-z0-9+.-]*:/i.test(url)) return ''   // 未知/危险协议一律拒绝
  return resolve ? (resolve(url) || '') : ''
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
  let inFence = false
  for (const line of lines) {
    if (/^```/.test(line)) { inFence = !inFence; continue }
    if (inFence) continue
    const h = line.match(/^(#{1,6})\s+(.*)$/)
    if (h) { inRefs = REF_HEADING_RE.test(h[2]); continue }
    if (inRefs && /^\s*([-*+]|\d+\.)\s+\[S\d+(-[A-Za-z])?\]/.test(line)) return true
  }
  return false
}

// Inline formatting on an already-escaped string.
// opts.resolveUrl(rel) —— 可选：把报告内相对资源路径（charts/…）重写为可访问 URL。
// 提供时图片渲染为 <img>；不提供时保持历史行为（图片退化为 alt 文本，供 Dossier 等无资源上下文复用）。
// opts.interactiveHref(rel) —— 可选（VIZ-2，manifest 驱动）：charts/<x>.png 存在交互式 .html
// 孪生时返回其可访问 URL → 图片下方追加「交互版 Interactive」新标签页链接；返回空串则不追加。
// opts.citations —— 可选（CITE-1）：{ 'S3': '来源标题…' } 映射，为引文上标提供 hover 提示。
function renderInline(text, opts) {
  const resolve = opts && typeof opts.resolveUrl === 'function' ? opts.resolveUrl : null
  const interactive = opts && typeof opts.interactiveHref === 'function' ? opts.interactiveHref : null
  let t = text
  // 图片：有 resolveUrl 时渲染 <img>（相对 charts/… 重写到 API base，PNG 图表得以显示）；
  // 否则退化为 alt 文本（与历史一致，避免 Dossier 等上下文出现坏图）。
  if (resolve) {
    t = t.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;[^&]*&quot;)?\)/g, (m, alt, url) => {
      const src = safeAssetUrl(url, resolve)
      if (!src) return alt
      const img = `<img class="md-img" src="${src}" alt="${alt}" loading="lazy" />`
      // VIZ-2：交互孪生链接只来自 viz_manifest（调用方校验路径），绝不注入 markdown 内任意 HTML。
      const ihref = interactive ? (interactive(url) || '') : ''
      if (ihref) {
        return `<span class="md-img-wrap">${img}<a class="md-img-interactive" href="${ihref}" target="_blank" rel="noopener noreferrer">交互版 Interactive ↗</a></span>`
      }
      return img
    })
  } else {
    t = t.replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
  }
  // CITE-1：引文标记 [S3] / [S3-a] → 阅读流内不打扰的上标引用。
  // 仅当本文档存在可锚定的 References 条目（opts._citeAnchors，由 renderMarkdown 预扫描）
  // 时生成跳转链接；否则退化为纯上标。hover 提示取自可选的 opts.citations 映射。
  t = t.replace(CITE_RE, (m, n, letter) => {
    const key = citeKey(n, letter)
    const cite = opts && opts.citations ? opts.citations[key] : null
    const tipRaw = cite == null ? '' : (typeof cite === 'string' ? cite : String(cite.title || ''))
    const titleAttr = tipRaw ? ` title="${escapeHtml(tipRaw)}"` : ''
    const label = n + (letter ? letter.slice(1).toLowerCase() : '')
    if (opts && opts._citeAnchors) {
      return `<sup class="md-cite"><a href="#ref-${key}"${titleAttr}>${label}</a></sup>`
    }
    return `<sup class="md-cite"${titleAttr}>${label}</sup>`
  })
  // links: [label](url)  — also handles [citation:Label](url)
  t = t.replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+&quot;[^&]*&quot;)?\)/g, (m, label, url) => {
    const clean = label.replace(/^citation:/i, '')
    const safeUrl = /^(https?:|mailto:|#|\/)/i.test(url)
      ? url
      : (resolve ? (safeAssetUrl(url, resolve) || '#') : '#')
    const external = /^https?:/i.test(safeUrl)
    return `<a href="${safeUrl}"${external ? ' target="_blank" rel="noopener noreferrer"' : ''}>${clean}</a>`
  })
  // bold then italic then inline code
  t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  t = t.replace(/__([^_]+)__/g, '<strong>$1</strong>')
  t = t.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
  t = t.replace(/`([^`]+)`/g, '<code>$1</code>')
  return t
}

function renderTable(rows, opts) {
  // rows: array of raw markdown table lines (without the separator row)
  const parseRow = (line) => line.replace(/^\||\|$/g, '').split('|').map(c => c.trim())
  const header = parseRow(rows[0])
  const body = rows.slice(2) // skip header + separator
  let html = '<table class="md-table"><thead><tr>'
  header.forEach(h => { html += `<th>${renderInline(escapeHtml(h), opts)}</th>` })
  html += '</tr></thead><tbody>'
  body.forEach(line => {
    if (!line.trim()) return
    const cells = parseRow(line)
    html += '<tr>'
    cells.forEach(c => { html += `<td>${renderInline(escapeHtml(c), opts)}</td>` })
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
      out.push('<p>' + renderInline(escapeHtml(buf.join(' ')), o) + '</p>')
      buf.length = 0
    }
  }
  const paraBuf = []

  while (i < lines.length) {
    let line = lines[i]

    // fenced code block
    const fence = line.match(/^```(\w*)\s*$/)
    if (fence) {
      flushParagraph(paraBuf)
      const code = []
      i++
      while (i < lines.length && !/^```\s*$/.test(lines[i])) { code.push(lines[i]); i++ }
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
      while (i < lines.length && /\|/.test(lines[i]) && lines[i].trim()) { tbl.push(lines[i]); i++ }
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
      out.push(`<h${level} id="${id}" class="md-h md-h${level}">${renderInline(escapeHtml(text), o)}</h${level}>`)
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
      out.push('<blockquote class="md-quote">' + renderInline(escapeHtml(quote.join(' ')), o) + '</blockquote>')
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
          out.push(`<li${idAttr} class="md-ref"><span class="md-ref-tag">${key}</span> ` + renderInline(escapeHtml(rm[3]), o) + '</li>')
        } else {
          out.push('<li>' + renderInline(escapeHtml(item), o) + '</li>')
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
  String(md).split('\n').forEach(line => {
    const h = line.match(/^(#{1,6})\s+(.*)$/)
    if (h) {
      const text = h[2].replace(/\s+#*\s*$/, '').replace(/[*_`]/g, '').trim()
      if (text) out.push({ level: h[1].length, text, id: slugify(text) })
    }
  })
  return out
}
