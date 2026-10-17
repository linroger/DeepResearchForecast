import service, { apiUrl } from './index'

/**
 * GATE-W9：把研究卷宗内的相对图表路径（'charts/xxx.png'）重写为产物深链 URL。
 * 后端把 handoff/charts 下的静态图与交互式 HTML 逐个登记为名为 'chart_<文件名>' 的产物
 * （VIZ-2），经 GET /api/research/<pid>/artifact/chart_<文件名> 以原始字节直出。
 * 非 charts/ 相对路径（无法定位）返回 ''，renderMarkdown 据此优雅降级。
 * @param {string} pipelineId
 * @param {string} rel - 卷宗内相对路径（'charts/…'）
 * @returns {string}
 */
export function researchChartUrl(pipelineId, rel) {
  const clean = String(rel || '').replace(/^\.?\//, '')
  const m = clean.match(/^charts\/([^/]+)$/)
  if (!pipelineId || !m) return ''
  return apiUrl(`/api/research/${pipelineId}/artifact/chart_${encodeURIComponent(m[1])}`)
}

/**
 * 启动统一研究→预测管线（Step 0）
 *
 * 注意：此请求 **非幂等** —— 每次 /run 都会新建一条 pipeline 并拉起一个 DeerFlow 子进程
 * 与一整轮模拟。因此绝不能用 requestWithRetry 包裹：一次因超时/网络抖动而丢失响应的
 * 重试会启动第二条不可见的管线，白白消耗 Claude 额度与算力。改用单次 service() 调用。
 * @param {Object} data { prompt, mode, project_name, depth, model, simulation_engine?, max_rounds? }
 * @returns {Promise}
 */
export function runPipeline(data) {
  return service({
    url: '/api/research/run',
    method: 'post',
    data
  })
}

/**
 * 取消在飞管线（杀掉研究子进程 / 停止 OASIS 模拟）
 * @param {String} pipelineId
 * @returns {Promise}
 */
export function cancelPipeline(pipelineId) {
  return service({
    url: `/api/research/${pipelineId}/cancel`,
    method: 'post'
  })
}

/**
 * 恢复失败/取消的管线。后端会复用已完成产物并从第一个缺失/失败阶段继续。
 * @param {String} pipelineId
 * @returns {Promise}
 */
export function resumePipeline(pipelineId) {
  return service({
    url: `/api/research/${pipelineId}/resume`,
    method: 'post'
  })
}

/**
 * 把已完成的 research_only 管线继续跑成完整管线（复用研究产物，不重跑研究）。T6.2
 * @param {String} pipelineId
 * @returns {Promise}
 */
export function continuePipeline(pipelineId) {
  return service({
    url: `/api/research/${pipelineId}/continue`,
    method: 'post'
  })
}

/**
 * 在 PREPARE 处分叉一个 what-if 情景管线（复用 base 研究/本体/图谱）。T4.6
 * @param {String} pipelineId 基础管线
 * @param {Object} overlay { label, max_rounds?, influence_overrides?, stance_overrides?, injected_events?, as_of_shift? }
 * @returns {Promise}
 */
export function forkScenario(pipelineId, overlay) {
  return service({
    url: `/api/research/${pipelineId}/scenario`,
    method: 'post',
    data: overlay
  })
}

/**
 * 读取某阶段产物（dossier/timeline/sources/ontology/communities/initial_posts/personas/run_summary）。T6.3
 * @param {String} pipelineId
 * @param {String} name
 * @returns {Promise}
 */
export function getArtifact(pipelineId, name) {
  return service({
    url: `/api/research/${pipelineId}/artifact/${name}`,
    method: 'get'
  })
}

/**
 * 启动前就绪检查（不发起管线）。T5.6
 * @param {String} mode full | research_only
 * @param {Object} options Optional research model and explicit simulation_engine; omit engine for server default.
 * @returns {Promise}
 */
export function getPreflight(mode = 'full', options = {}) {
  const params = { mode }
  if (options.model) params.model = options.model
  if (options.simulation_engine) params.simulation_engine = options.simulation_engine
  return service({
    url: '/api/research/preflight',
    method: 'get',
    params
  })
}

/**
 * 删除一条已结束的管线记录（在飞管线须先取消，否则后端返回 409）
 * @param {String} pipelineId
 * @returns {Promise}
 */
export function deletePipeline(pipelineId) {
  return service({
    url: `/api/research/${pipelineId}`,
    method: 'delete'
  })
}

/**
 * 批量清理失败/已取消的管线记录
 * @param {Array<String>} statuses 默认 ['failed','cancelled']
 * @returns {Promise}
 */
export function cleanPipelines(statuses = ['failed', 'cancelled']) {
  return service({
    url: '/api/research/clean',
    method: 'post',
    data: { statuses }
  })
}

/**
 * 查询管线聚合进度
 * @param {String} pipelineId
 * @returns {Promise}
 */
export function getPipelineStatus(pipelineId) {
  return service({
    url: `/api/research/status/${pipelineId}`,
    method: 'get'
  })
}

/**
 * 管线列表
 */
export function listPipelines() {
  return service({ url: '/api/research/list', method: 'get' })
}

/**
 * 研究产出（research_report.md + actors/sources）
 * @param {String} pipelineId
 */
export function getDossier(pipelineId) {
  return service({
    url: `/api/research/${pipelineId}/dossier`,
    method: 'get'
  })
}

/**
 * 编辑研究档案（research_report.md / actors.json）。仅完成的 research_only 或建图前失败管线可编辑。T5.4
 * @param {String} pipelineId
 * @param {Object} payload { report?: string, actors?: object }
 */
export function editDossier(pipelineId, payload) {
  return service({
    url: `/api/research/${pipelineId}/dossier`,
    method: 'put',
    data: payload
  })
}

/**
 * BILINGUAL（研究报告）：启动/去重结构无损的研究报告翻译（en⇄zh）。
 * 后端复用与预测报告完全相同的翻译器（标题/表格/数字/引用逐一保真 + 污染重译 + 审计前 lint），
 * 仅在隔离审计硬通过时落 research_report.<lang>.md + 审计侧车；失败不发布（fail-closed）。
 * @param {String} pipelineId
 * @param {String} lang - 'en' | 'zh'
 */
export function requestResearchTranslation(pipelineId, lang) {
  return service.post(`/api/research/${pipelineId}/dossier/translations/${lang}`)
}

/**
 * 拉取研究报告的某语种译文 Markdown + 审计状态。
 * 返回 { success, data: { status, available, issues, source_lang, target_lang, report } }。
 * 未生成/失败 → available:false（degrade-safe，调用方回退原文）。
 * @param {String} pipelineId
 * @param {String} lang - 'en' | 'zh'
 */
export function getResearchTranslation(pipelineId, lang) {
  return service.get(`/api/research/${pipelineId}/dossier/translations/${lang}`)
}

/**
 * 研究报告 PDF 直链（浏览器直下；绕过 axios）。lang ∈ {en,zh} 取审计通过的双语版（?lang=），
 * 缺省取主报告。与预测报告 PDF 复用同一 LaTeX 模板（CJK/符号安全）。
 * @param {String} pipelineId
 * @param {String} [lang] - 'en' | 'zh'
 * @returns {String} 可放进 <a href> 的 URL
 */
export function researchPdfUrl(pipelineId, lang) {
  const base = `/api/research/${pipelineId}/dossier/pdf`
  return apiUrl(lang ? `${base}?lang=${encodeURIComponent(lang)}` : base)
}

/**
 * i8/MON-1：手动触发一轮市场判定监测（后台子进程 `run --all-recent`）。
 * 后端自带在飞去重：202 {started:true}=已启动；409 {inflight:true}=上一轮仍在运行。
 * 绝不用 requestWithRetry 包裹——重试会把 409 的「已在跑」语义误报成失败/双触发。
 * @returns {Promise}
 */
export function runResolutionMonitor() {
  return service.post('/api/research/resolution-monitor/run')  // non-idempotent: do not retry
}

/**
 * 研究子进程进度日志（tail）
 * @param {String} pipelineId
 * @param {Number} lines
 * @param {'tail'|'full'} scope recurring bounded tail or explicit exact snapshot
 */
export function getProgressLog(pipelineId, lines = 200, scope = 'tail') {
  return service({
    url: `/api/research/${pipelineId}/progress`,
    method: 'get',
    params: { lines, scope }
  })
}
