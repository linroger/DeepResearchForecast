import service, { apiUrl } from './index'

export { apiUrl }

// EXECPLAN2 F-10-12: report 生成/对话为非幂等 POST（触发整轮 LLM 报告 agent），不自动重试。

/**
 * 开始报告生成
 * @param {Object} data - { simulation_id, force_regenerate? }
 */
export const generateReport = (data) => {
  return service.post('/api/report/generate', data)  // non-idempotent: do not retry
}

/**
 * 获取报告生成状态
 * @param {{task_id: string, simulation_id?: string}} data
 */
export const getReportStatus = (data) => {
  return service.post('/api/report/generate/status', data)
}

/**
 * 获取 Agent 日志（增量）
 * @param {string} reportId
 * @param {number} fromLine - 从第几行开始获取
 */
export const getAgentLog = (reportId, fromLine = 0) => {
  return service.get(`/api/report/${reportId}/agent-log`, { params: { from_line: fromLine } })
}

/**
 * 获取控制台日志（增量）
 * @param {string} reportId
 * @param {number} fromLine - 从第几行开始获取
 */
export const getConsoleLog = (reportId, fromLine = 0) => {
  return service.get(`/api/report/${reportId}/console-log`, { params: { from_line: fromLine } })
}

/**
 * 获取报告详情
 * @param {string} reportId
 */
export const getReport = (reportId) => {
  return service.get(`/api/report/${reportId}`)
}

/**
 * 与 Report Agent 对话
 * @param {Object} data - { simulation_id, message, chat_history? }
 */
export const chatWithReport = (data) => {
  return service.post('/api/report/chat', data)  // non-idempotent: do not retry
}

// ============== 报告增强能力（VIZ-1 / PDF-1 / BILINGUAL / PROGRESSIVE）==============

/**
 * VIZ-1：获取报告可视化清单 reports/{id}/viz_manifest.json。
 * 返回 { success, data: [{path, type, source, caption, placement_hint}], count }。
 * 无清单（未开启可视化 / 无可渲染工件）→ data 为空数组（degrade-safe，前端据此不渲染图区）。
 * @param {string} reportId
 */
export const getVizManifest = (reportId) => {
  return service.get(`/api/report/${reportId}/viz-manifest`)
}

/**
 * PROGRESSIVE：生成期章节增量。契约 { sections: [{index, title, status, content_md}], done: bool }。
 * 后端该端点与本前端并行搭建；未上线时命中 404 → 调用方据此静默停轮询（degrade-safe）。
 * @param {string} reportId
 */
export const getSectionsPartial = (reportId) => {
  return service.get(`/api/report/${reportId}/sections-partial`)
}

/**
 * BILINGUAL：拉取自动生成的另一语种成稿 full_report.<lang>.md（lang ∈ {en, zh}）的原始 Markdown 文本。
 * 该语种未生成（REPORT_BILINGUAL 关闭 / 同语种 / 翻译失败）→ 404（degrade-safe，调用方回退原文）。
 * @param {string} reportId
 * @param {string} lang - 'en' | 'zh'
 */
export const getReportTranslationMd = (reportId, lang) => {
  // responseType text：返回体是 text/markdown 原文而非 JSON，避免 axios 误当 JSON 解析。
  return service.get(`/api/report/${reportId}/full_report.${lang}.md`, { responseType: 'text' })
}

/**
 * Start or deduplicate a publication-gated translation retry.  `force` regenerates a
 * published variant (e.g. one an older engine produced); the published variant
 * stays until the new one passes the audit.
 */
export const requestReportTranslation = (reportId, lang, force = false) => {
  return service.post(
    `/api/report/${reportId}/translations/${lang}`,
    null,
    force ? { params: { force: 1 } } : undefined,
  )
}

/** Poll one report-bound translation task; task ids cannot cross reports/languages. */
export const getReportTranslationStatus = (reportId, lang, taskId) => {
  return service.get(`/api/report/${reportId}/translations/${lang}/status`, {
    params: taskId ? { task_id: taskId } : undefined,
  })
}

/** Direct Markdown download for the primary or selected published variant. */
export const reportMarkdownUrl = (reportId, lang) => {
  const path = lang
    ? `/api/report/${reportId}/full_report.${encodeURIComponent(lang)}.md`
    : `/api/report/${reportId}/download`
  return apiUrl(path)
}

/**
 * PDF-1：报告 PDF 直链（浏览器可直接下载/打开，绕过 axios 实例）。
 * lang ∈ {en, zh} 时取双语版 ?lang=；缺省/其它取主报告 PDF（行为与历史一致）。
 * @param {string} reportId
 * @param {string} [lang] - 'en' | 'zh'
 * @returns {string} 可放进 <a href> 的 URL
 */
export const reportPdfUrl = (reportId, lang) => {
  const path = `/api/report/${reportId}/pdf`
  return apiUrl(lang ? `${path}?lang=${encodeURIComponent(lang)}` : path)
}

/**
 * FORECAST-DASH：获取报告的机器可读结构化预测对象（第一方报告 API）。
 * 返回 { success, data: { report_id, simulation_id, forecast, available, localization } }；
 * forecast 内含 scenarios / confidence / ensemble / market_comparison 等字段。
 * lang（en|zh，可选）：返回该语种的仪表盘文本（绑定已封存 forecast.json 的本地化副本），
 * 无副本时回退为原始预测；localization.localized 说明实际返回的是哪一份。
 * 降级路径（调用方一律按「无仪表盘」处理，不报错）：
 *   · 报告不存在 → 404；
 *   · 已审计旧报告没有 forecast.json → 200 + forecast: null；
 *   · 报告未通过发布门 → 409。
 * @param {string} reportId
 * @param {string} [lang]
 */
export const getForecast = (reportId, lang) => {
  return service.get(`/api/report/${reportId}/forecast`, lang ? { params: { lang } } : undefined)
}

/**
 * 把报告内相对可视化资源路径（如 'charts/xxx.png'）重写为可访问 URL。
 * 与 /charts 端点同源：/api/report/<id>/charts/<file>。用于 renderMarkdown 的 resolveUrl 及图表画廊。
 * @param {string} reportId
 * @param {string} rel - 报告内相对路径（'charts/…'）
 * @returns {string}
 */
export const reportAssetUrl = (reportId, rel) => {
  const clean = String(rel || '').replace(/^\/+/, '')
  return apiUrl(`/api/report/${reportId}/${clean}`)
}
