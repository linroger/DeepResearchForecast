import service from './index'

/** 当前 LLM 提供方 + 受支持提供方清单 */
export function getLlmSettings() {
  return service({ url: '/api/settings/llm', method: 'get' })
}

/**
 * 切换 LLM 提供方（对新发起的管线生效，无需重启）
 * @param {Object} data { provider, api_key?, base_url?, model? }
 */
export function setLlmSettings(data) {
  return service({ url: '/api/settings/llm', method: 'post', data })
}

/**
 * 测试提供方连通性（不持久化任何配置）。
 * CLI 提供方检查本机 CLI；API 提供方发一条最小 chat completion 验证 Key。
 * @param {Object} data { provider, api_key?, base_url?, model? }
 */
export function testLlmSettings(data) {
  return service({ url: '/api/settings/llm/test', method: 'post', data, timeout: 45000 })
}

/**
 * 官方数据源探活（FRED / BLS / BIS / IMF / World Bank Data360 / US Gov Open Data）：
 * 每个启用的 MCP 服务握手 + 一条缓存优先的目录样本（BLS 只握手，不耗日配额）。纯建议性，不持久化。
 * 返回 { success, data: { enabled, providers: { name: { state, detail, latency_s, keys } },
 * deadline_s, elapsed_s } }；另一探活进行中 → 409。服务端预算约 75 s + 关闭余量，故超时放宽到 120 s。
 */
export function testDataSources() {
  return service({ url: '/api/settings/data-sources/test', method: 'post', timeout: 120000 })
}
