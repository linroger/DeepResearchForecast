import service from './index'

// 2026-10-21: graph / simulation 翻译 overlay（报告/卷宗翻译在各自的 API 模块里）
export function getGraphTranslation(graphId, lang, options = {}) {
  return service.get(`/api/graph/${encodeURIComponent(graphId)}/translations/${lang}`, options)
}
export function startGraphTranslation(graphId, lang, force = false, options = {}) {
  return service.post(`/api/graph/${encodeURIComponent(graphId)}/translations/${lang}${force ? '?force=1' : ''}`, undefined, options)
}
export function getSimulationTranslation(simId, lang, options = {}) {
  return service.get(`/api/simulation/${encodeURIComponent(simId)}/translations/${encodeURIComponent(lang)}`, options)
}
export function startSimulationTranslation(simId, lang, force = false, options = {}) {
  const { texts, entries, context, source_fingerprint, ...request } = options
  return service.post(`/api/simulation/${encodeURIComponent(simId)}/translations/${encodeURIComponent(lang)}${force ? '?force=1' : ''}`,
    texts || entries ? { ...(texts ? { texts } : { entries }), context, source_fingerprint } : undefined, request)
}
