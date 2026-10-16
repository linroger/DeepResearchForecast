import { officialFrequencyLabel, safeSourceUrl } from './officialData.js'

const IMAGE_RE = /\.(png|svg|jpe?g|gif|webp)$/i
const HTML_RE = /\.html$/i

export function safeChartPath(value) {
  const raw = String(value || '').trim().replace(/^\.\//, '')
  // Manifest entries are filesystem-relative paths, not URL-encoded paths.
  // Reject '%' outright so browser URL normalization cannot turn %2e%2e into '..'.
  if (
    !raw || raw.startsWith('/') || raw.includes('\\') || raw.includes('%') ||
    /[\u0000-\u001F\u007F]/.test(raw)
  ) return ''
  const parts = raw.split('/').filter(part => part && part !== '.')
  if (parts[0]?.toLowerCase() !== 'charts' || parts.length < 2 || parts.includes('..')) return ''
  return parts.join('/')
}

export function chartAssetKind(path, declaredType = '') {
  if (!path) return ''
  if (IMAGE_RE.test(path)) return 'image'
  if (HTML_RE.test(path)) return 'html'
  // A real extension is authoritative. Only extensionless legacy rows may use type.
  if (/\.[^/]+$/.test(path)) return ''
  const type = String(declaredType || '').toLowerCase()
  if (['png', 'svg', 'jpg', 'jpeg', 'gif', 'webp', 'image'].includes(type)) return 'image'
  if (['html', 'plotly', 'interactive'].includes(type)) return 'html'
  return ''
}

function assetStem(path) {
  return String(path || '').replace(/\.[^/.]+$/, '')
}

function preferImage(current, candidate) {
  if (!current) return candidate
  if (/\.png$/i.test(candidate) && !/\.png$/i.test(current)) return candidate
  return current
}

const SOURCE_ID_RE = /^S[1-9]\d*$/

function text(value) {
  return typeof value === 'string' ? value.trim() : ''
}

/**
 * Official-data exhibit provenance (report_visualizer, harmonized to the report's
 * own [S#] by report_agent) → attribution entries. Language-neutral: the
 * frequency code is localized at render time by chartAttribution().
 */
function provenanceSources(provenance) {
  if (!Array.isArray(provenance)) return []
  return provenance
    .filter(entry => entry && typeof entry === 'object' && !Array.isArray(entry))
    .map(entry => ({
      series: text(entry.series),
      title: text(entry.title),
      label: text(entry.provider_name) || text(entry.provider) || text(entry.series),
      href: safeSourceUrl(entry.source_url),
      sourceId: SOURCE_ID_RE.test(text(entry.source_id)) ? text(entry.source_id) : '',
      units: text(entry.units),
      frequency: text(entry.frequency),
      adjustment: text(entry.seasonal_adjustment),
    }))
    .filter(entry => entry.label)
}

/**
 * Fold legacy PNG+HTML twin rows and schema-v2 HTML/png_path rows into cards.
 * HTML-only Plotly artifacts remain first-class cards when static export fails.
 * Official-data exhibits keep their attribution: `sourceCaption` (the audited
 * Markdown line under the exhibit) and `sources` (structured provenance).
 */
export function normalizeVizGallery(manifest) {
  const rows = Array.isArray(manifest) ? manifest.filter(x => x && typeof x === 'object') : []
  const groups = new Map()

  for (const item of rows) {
    const path = safeChartPath(item.path)
    const pngPath = safeChartPath(item.png_path)
    const primaryKind = chartAssetKind(path, item.type)
    const pngKind = chartAssetKind(pngPath, 'image')

    let imagePath = pngKind === 'image' ? pngPath : ''
    let interactivePath = ''
    if (primaryKind === 'image') imagePath = preferImage(imagePath, path)
    if (primaryKind === 'html') interactivePath = path
    if (!imagePath && !interactivePath) continue

    const stem = assetStem(interactivePath || imagePath)
    if (!stem) continue
    const existing = groups.get(stem) || {
      imagePath: '',
      interactivePath: '',
      caption: '',
      id: '',
      sourceCaption: '',
      sources: [],
    }
    existing.imagePath = preferImage(existing.imagePath, imagePath)
    if (!existing.interactivePath && interactivePath) existing.interactivePath = interactivePath
    if (!existing.caption && item.caption) existing.caption = String(item.caption)
    if (!existing.id) existing.id = String(item.id || item.name || stem)
    if (!existing.sourceCaption && text(item.source_caption)) existing.sourceCaption = text(item.source_caption)
    if (!existing.sources.length) existing.sources = provenanceSources(item.provenance)
    groups.set(stem, existing)
  }

  return [...groups.values()].filter(item => item.imagePath || item.interactivePath)
}

export function filterVizGalleryByMarkdown(gallery, markdown) {
  const source = String(markdown || '')
  const embeddedImages = new Set()
  const embeddedLinks = new Set()
  let match
  const imageRe = /!\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g
  const linkRe = /(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g
  while ((match = imageRe.exec(source)) !== null) {
    const path = safeChartPath(match[1])
    if (path) embeddedImages.add(path)
  }
  while ((match = linkRe.exec(source)) !== null) {
    const path = safeChartPath(match[1])
    if (path) embeddedLinks.add(path)
  }
  return (Array.isArray(gallery) ? gallery : []).filter(item => (
    !embeddedImages.has(item?.imagePath) && !embeddedLinks.has(item?.interactivePath)
  ))
}

// Manifest captions are the fixed English titles emitted by the chart builders
// (backend report_visualizer.py).  A translated report view shows them in its own
// language; unknown captions (future builders) stay as emitted.
const ZH_CHART_CAPTIONS = Object.freeze({
  'Scenario Probabilities': '情景概率',
  'Binary Forecasts — P(yes)': '二元预测 — P(是)',
  'Model vs Market (binary forecasts)': '模型与市场对比（二元预测）',
  'Model vs Market': '模型与市场对比',
  'Event Timeline': '事件时间线',
  'Actor Relationship Network': '行为体关系网络',
  'Source Mix — tier / origin / reachability': '来源构成 — 层级 / 来源 / 可达性',
  'Key Metric Trajectories (research-extracted)': '关键指标轨迹（研究提取）',
  'Technology Shares by Metric Family': '按指标族划分的技术份额',
  'Regional Comparison by Metric Family': '按指标族划分的地区比较',
  'Comparable Forecast Benchmarks': '可比预测基准',
  'Forecast Revisions Across Published Vintages': '历次发布版本的预测修订',
  'Forecast Outcome-Share Trajectory': '预测结果份额轨迹',
  'Simulated World Variables (indexed, seed = 100)': '推演世界变量（指数化，种子值 = 100）',
  'Baseline vs Scenario': '基线与情景对比',
  'Calibration Curve': '校准曲线',
  'Market-Implied P(yes) History vs Model': '市场隐含 P(是) 历史与模型对比',
  'Official Indicators': '官方指标',
  'Official Series History and Forecast Thresholds': '官方序列历史与预测阈值',
})

export function localizeChartCaption(caption, lang) {
  const text = String(caption || '')
  if (String(lang || '').toLowerCase() !== 'zh') return text
  return ZH_CHART_CAPTIONS[text.trim()] || text
}

const CAPTION_PREFIX_RE = /^(?:Source:\s*|来源[：:]\s*)/
const CAPTION_PART_RE = /^\[([^\]]+)\]\(<?([^)<>\s]+)>?\)\s*(?:\[(S[1-9]\d*)\])?\s*;?\s*(.*)$/

/**
 * Attribution entries for one gallery card: structured provenance when present
 * (frequency and an unknown adjustment localized to `lang`), else the parsed
 * audited source caption ('Source: [FRED](<url>) [S1]; Percent; Monthly; SA · …').
 * Each entry: { label, href, sourceId, detail, title } (title: the series title,
 * '' when only the caption is known). [] for non-official charts.
 */
export function chartAttribution(item, lang = 'en') {
  const zh = String(lang || '').toLowerCase() === 'zh'
  const sources = Array.isArray(item?.sources) ? item.sources : []
  if (sources.length) {
    return sources.map(entry => ({
      label: entry.label,
      href: entry.href,
      sourceId: entry.sourceId,
      title: entry.title || '',
      detail: [
        entry.units,
        officialFrequencyLabel(entry.frequency, lang),
        entry.adjustment || (zh ? '季节调整未知' : 'adjustment unknown'),
      ].filter(Boolean).join('; '),
    }))
  }
  const caption = text(item?.sourceCaption).replace(CAPTION_PREFIX_RE, '')
  if (!caption) return []
  return caption.split(' · ').map(part => {
    const match = part.trim().match(CAPTION_PART_RE)
    if (!match) return { label: part.trim(), href: '', sourceId: '', detail: '', title: '' }
    return {
      label: match[1].trim(),
      href: safeSourceUrl(match[2]),
      sourceId: match[3] || '',
      detail: match[4].trim(),
      title: '',
    }
  }).filter(entry => entry.label)
}
