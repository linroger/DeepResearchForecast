// 2026-10-21: 图谱/模拟面板的语言 overlay 组合式工具。
// ensureOverlay(getFn, startFn, id, lang): 立即取缓存；未生成则启动后台任务并轮询，
// 有界重试（最多 ~90s），任何失败静默回退源文本（UI 永不因翻译报错）。
import { getGraphTranslation, startGraphTranslation,
         getSimulationTranslation, startSimulationTranslation } from '../api/translations'

export function graphOverlayFetcher(graphId) {
  return {
    get: (lang) => getGraphTranslation(graphId, lang),
    start: (lang, force) => startGraphTranslation(graphId, lang, force),
  }
}

export function simulationOverlayFetcher(simId) {
  return {
    get: (lang) => getSimulationTranslation(simId, lang),
    start: (lang, force) => startSimulationTranslation(simId, lang, force),
  }
}

export async function ensureOverlay(fetcher, lang, { maxPolls = 18, pollMs = 5000 } = {}) {
  try {
    let res = await fetcher.get(lang)
    let data = res?.data?.data || res?.data || {}
    if (data.status === 'available' || data.status === 'empty') return data
    if (data.status === 'error') return null
    await fetcher.start(lang, false).catch(() => {})
    for (let i = 0; i < maxPolls; i++) {
      await new Promise((r) => setTimeout(r, pollMs))
      res = await fetcher.get(lang)
      data = res?.data?.data || res?.data || {}
      if (data.status === 'available' || data.status === 'empty') return data
      if (data.status !== 'generating') return data
    }
    return data?.status === 'generating' ? { ...data, status: 'timeout' } : data
  } catch (e) {
    return null
  }
}
