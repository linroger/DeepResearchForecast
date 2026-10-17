import service from './index'

// EXECPLAN2 F-10-12: 创建/准备/启动/采访均为非幂等 POST，绝不自动重试 —— 否则首请求其实
// 成功、客户端误判超时重试，会造成重复创建/重复启动等副作用。仅 GET/状态轮询可重试。

/**
 * 创建模拟
 * @param {Object} data - { project_id, graph_id?, enable_twitter?, enable_reddit? }
 */
export const createSimulation = (data) => {
  return service.post('/api/simulation/create', data)  // non-idempotent: do not retry
}

/**
 * 准备模拟环境（异步任务）
 * @param {Object} data - { simulation_id, entity_types?, use_llm_for_profiles?, parallel_profile_count?, force_regenerate? }
 */
export const prepareSimulation = (data) => {
  return service.post('/api/simulation/prepare', data)  // non-idempotent: do not retry
}

/**
 * 查询准备任务进度
 * @param {Object} data - { task_id?, simulation_id? }
 */
export const getPrepareStatus = (data) => {
  return service.post('/api/simulation/prepare/status', data)
}

/**
 * 获取模拟状态
 * @param {string} simulationId
 */
export const getSimulation = (simulationId, options = {}) => {
  return service.get(`/api/simulation/${simulationId}`, options)
}

/** Read one committed world projection. Revision conflicts require explicit refresh. */
export const getWorldSimulation = (simulationId, { view = 'public', actorId, round, revision } = {}, options = {}) => {
  const params = { view }
  if (view === 'actor' && actorId) params.actor_id = actorId
  if (round !== undefined && round !== null) params.round = round
  if (revision) params.revision = revision
  return service.get(`/api/simulation/${encodeURIComponent(simulationId)}/world`, { ...options, params })
}

/**
 * 获取模拟的 Agent Profiles
 * @param {string} simulationId
 * @param {string} platform - 'reddit' | 'twitter'
 */
export const getSimulationProfiles = (simulationId, platform = 'reddit') => {
  return service.get(`/api/simulation/${simulationId}/profiles`, { params: { platform } })
}

/**
 * 实时获取生成中的 Agent Profiles
 * @param {string} simulationId
 * @param {string} platform - 'reddit' | 'twitter'
 */
export const getSimulationProfilesRealtime = (simulationId, platform = 'reddit', options = {}) => {
  return service.get(`/api/simulation/${simulationId}/profiles/realtime`, { ...options, params: { platform } })
}

/**
 * 获取模拟配置
 * @param {string} simulationId
 */
export const getSimulationConfig = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/config`)
}

/**
 * 实时获取生成中的模拟配置
 * @param {string} simulationId
 * @returns {Promise} 返回配置信息，包含元数据和配置内容
 */
export const getSimulationConfigRealtime = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/config/realtime`)
}

/**
 * 列出所有模拟
 * @param {string} projectId - 可选，按项目ID过滤
 */
export const listSimulations = (projectId) => {
  const params = projectId ? { project_id: projectId } : {}
  return service.get('/api/simulation/list', { params })
}

/**
 * 启动模拟
 * @param {Object} data - { simulation_id, platform?, max_rounds?, enable_graph_memory_update? }
 */
export const startSimulation = (data) => {
  return service.post('/api/simulation/start', data)  // non-idempotent: do not retry
}

/**
 * 停止模拟
 * @param {Object} data - { simulation_id }
 */
export const stopSimulation = (data) => {
  return service.post('/api/simulation/stop', data)
}

/**
 * 获取模拟运行实时状态
 * @param {string} simulationId
 */
export const getRunStatus = (simulationId, options = {}) => {
  return service.get(`/api/simulation/${simulationId}/run-status`, options)
}

/**
 * 获取模拟运行详细状态（包含最近动作）
 * @param {string} simulationId
 */
export const getRunStatusDetail = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/run-status/detail`)
}

/**
 * 获取模拟中的帖子
 * @param {string} simulationId
 * @param {string} platform - 'reddit' | 'twitter'
 * @param {number} limit - 返回数量
 * @param {number} offset - 偏移量
 */
export const getSimulationPosts = (simulationId, platform = 'reddit', limit = 50, offset = 0, options = {}) => {
  // `options` are request options (signal, timeout); PERIOD VIEW: `options.round` (a committed round
  // number) narrows the feed to that period's posts and is sent as a query parameter, not to axios
  const { round = null, ...request } = options || {}
  const params = { platform, limit, offset }
  if (round !== null && round !== undefined) params.round = round
  return service.get(`/api/simulation/${simulationId}/posts`, { ...request, params })
}

/**
 * 获取模拟中的评论/回复（Twitter/Reddit 均支持）
 * @param {string} simulationId
 * @param {string} platform - 'reddit' | 'twitter'
 * @param {number} limit - 返回数量
 * @param {number} offset - 偏移量
 */
export const getSimulationComments = (simulationId, platform = 'reddit', limit = 200, offset = 0, options = {}) => {
  // PERIOD VIEW: `options.round` narrows the replies to the ones written in that period
  const { round = null, ...request } = options || {}
  const params = { platform, limit, offset }
  if (round !== null && round !== undefined) params.round = round
  return service.get(`/api/simulation/${simulationId}/comments`, { ...request, params })
}

/**
 * PERIOD VIEW: the rounds of a platform's feed with period labels and post/reply counts
 * (GET /api/simulation/<id>/feed-rounds). Empty `rounds` before the run has an action log.
 */
export const getFeedRounds = (simulationId, platform = 'reddit', options = {}) => {
  return service.get(`/api/simulation/${simulationId}/feed-rounds`, { ...options, params: { platform } })
}

/**
 * 获取模拟时间线（按轮次汇总）
 * @param {string} simulationId
 * @param {number} startRound - 起始轮次
 * @param {number} endRound - 结束轮次
 */
/**
 * Reflexive world model: latest committed world state + bounded per-round history.
 * 404 while the world has not committed a round yet (hours mode / legacy runs).
 */
export const getWorldState = (simulationId, rows = 24) => {
  return service.get(`/api/simulation/${simulationId}/world-state`, { params: { rows } })
}

export const getSimulationTimeline = (simulationId, startRound = 0, endRound = null) => {
  const params = { start_round: startRound }
  if (endRound !== null) {
    params.end_round = endRound
  }
  return service.get(`/api/simulation/${simulationId}/timeline`, { params })
}

/**
 * 获取Agent统计信息
 * @param {string} simulationId
 */
export const getAgentStats = (simulationId, options = {}) => {
  return service.get(`/api/simulation/${simulationId}/agent-stats`, options)
}

/**
 * 获取模拟动作历史
 * @param {string} simulationId
 * @param {Object} params - { limit, offset, platform, agent_id, round_num }
 */
export const getSimulationActions = (simulationId, params = {}) => {
  return service.get(`/api/simulation/${simulationId}/actions`, { params })
}

/**
 * 关闭模拟环境（优雅退出）
 * @param {Object} data - { simulation_id, timeout? }
 */
export const closeSimulationEnv = (data) => {
  return service.post('/api/simulation/close-env', data)
}

/**
 * 获取模拟环境状态
 * @param {Object} data - { simulation_id }
 */
export const getEnvStatus = (data) => {
  return service.post('/api/simulation/env-status', data)
}

/**
 * 批量采访 Agent
 * @param {Object} data - { simulation_id, interviews: [{ agent_id, prompt }] }
 */
export const interviewAgents = (data) => {
  return service.post('/api/simulation/interview/batch', data)  // non-idempotent: do not retry
}

/**
 * 获取历史模拟列表（带项目详情）
 * 用于首页历史项目展示
 * @param {number} limit - 返回数量限制
 */
export const getSimulationHistory = (limit = 20) => {
  return service.get('/api/simulation/history', { params: { limit } })
}

