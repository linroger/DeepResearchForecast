import service from './index'

// 2026-10-21: graph / simulation 翻译 overlay（报告/卷宗翻译在各自的 API 模块里）
export function getGraphTranslation(graphId, lang) {
  return service.get(`/api/graph/${encodeURIComponent(graphId)}/translations/${lang}`)
}
export function startGraphTranslation(graphId, lang, force = false) {
  return service.post(`/api/graph/${encodeURIComponent(graphId)}/translations/${lang}${force ? '?force=1' : ''}`)
}
export function getSimulationTranslation(simId, lang) {
  return service.get(`/api/simulation/${encodeURIComponent(simId)}/translations/${lang}`)
}
export function startSimulationTranslation(simId, lang, force = false) {
  return service.post(`/api/simulation/${encodeURIComponent(simId)}/translations/${lang}${force ? '?force=1' : ''}`)
}
