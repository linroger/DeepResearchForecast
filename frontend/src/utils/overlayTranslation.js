import { ref, computed, unref, watch, onScopeDispose, getCurrentScope, effectScope } from 'vue'
import { getGraphTranslation, startGraphTranslation,
         getSimulationTranslation, startSimulationTranslation } from '../api/translations'
import { useTranslationJob } from '../composables/useTranslationJob.js'
import { normalizeTranslationSnapshot, translationBody } from './translationJobAdapter.js'

const contextKey = context => JSON.stringify(Object.entries(context || {}).sort(([a], [b]) => a.localeCompare(b)))
const invalidIdentity = () => Object.assign(new Error('Translation response does not match the selected resource, source and language'), { retryable: false })
const canonical = value => JSON.stringify(value, (_, item) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) : item)
async function digest(value) {
  const bytes = new TextEncoder().encode(value)
  return [...new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', bytes))].map(b => b.toString(16).padStart(2, '0')).join('')
}
export async function simulationSelectionIdentity(simId, lang, selection) {
  const pairs = await Promise.all(selection.texts.filter(text => text.trim()).map(async text => ['text:' + await digest(text), text]))
  pairs.sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
  return { request_digest: await digest(canonical(['simulation', simId, lang, selection.context, pairs])),
    source_fingerprint: await digest(canonical(pairs)), pairs }
}

export function graphOverlayFetcher(graphId) {
  const checked = response => {
    const data = translationBody(response)
    if ((data.ref_id || data.graph_id) !== graphId || (data.graph_id && data.graph_id !== graphId)
        || data.target_lang !== 'zh') throw invalidIdentity()
    return response
  }
  return {
    get: async (lang, options) => checked(await getGraphTranslation(graphId, lang, options)),
    start: async (lang, force, options) => checked(await startGraphTranslation(graphId, lang, force, options)),
  }
}

// Compute the exact permitted selection digest locally so a reload reconnects by
// GET. Never fall back to the unscoped simulation cache or send prose in a URL.
export function simulationOverlayFetcher(simId, selection) {
  if (!selection) return {
    get: (lang, options) => getSimulationTranslation(simId, lang, options),
    start: (lang, force, options) => startSimulationTranslation(simId, lang, force, options),
  }
  let identityPromise, fingerprint = ''
  const identity = lang => identityPromise ||= simulationSelectionIdentity(simId, lang, selection)
  const checked = async (response, lang) => {
    const data = translationBody(response), expected = await identity(lang)
    if (data.simulation_id !== simId || data.target_lang !== lang
        || data.request_digest !== expected.request_digest || !/^[a-f0-9]{64}$/.test(data.source_fingerprint)
        || (fingerprint && data.source_fingerprint !== fingerprint)
        || contextKey(data.context) !== contextKey(selection.context)) throw invalidIdentity()
    fingerprint = data.source_fingerprint
    const wanted = new Map(expected.pairs.map(([key, source]) => [source, key.slice(5)]))
    if ((data.translations || []).some(row => wanted.get(row.source) !== row.source_sha256)) throw invalidIdentity()
    return response
  }
  return {
    async start(lang, force, options) {
      return checked(await startSimulationTranslation(simId, lang, force, { ...options, ...selection }), lang)
    },
    async get(lang, options) {
      const expected = await identity(lang)
      if (options?.signal?.aborted) throw Object.assign(new Error('Translation selection changed'), { name: 'AbortError' })
      try {
        return await checked(await getSimulationTranslation(simId, lang, { ...options,
          params: { request_digest: expected.request_digest, context: JSON.stringify(selection.context) } }), lang)
      } catch (error) {
        // An absent digest is not an invitation to start work. The visible
        // Generate/Retry action creates it; never read the unscoped cache.
        const status = error?.response?.status ?? error?.status
        if (status === 404) return { data: { status: 'unavailable', pending: selection.texts.length,
          total_candidates: selection.texts.length, translations: [], issues: [], ...expected } }
        throw error
      }
    },
  }
}

// Compatibility helper for external callers, implemented by the SAME observer.
// New components use the composable directly and reconnect without a POST.
export function ensureOverlay(fetcher, lang, { maxPolls = 60, pollMs = 5000,
  signal, force = false, onUpdate = () => {}, timeout = 20000 } = {}) {
  return new Promise(resolve => {
    const scope = effectScope(), enabled = ref(null)
    let observer, settled = false
    const finish = data => { if (settled) return; settled = true; signal?.removeEventListener('abort', cancel); scope.stop(); resolve(data) }
    const cancel = () => finish({ status: 'cancelled' })
    if (signal?.aborted) { cancel(); return }
    signal?.addEventListener('abort', cancel, { once: true })
    scope.run(() => {
      observer = useTranslationJob({ identity: () => enabled.value, pollMs, maxPolls, maxErrors: 1,
        adapter: () => ({ get: async options => normalizeTranslationSnapshot(await fetcher.get(lang, { ...options, timeout })),
          start: async options => normalizeTranslationSnapshot(await fetcher.start(lang, options.force, { signal: options.signal, timeout })) }),
        onUpdate: state => { onUpdate(state.data); if (!state.active) finish(state.data) } })
      watch(observer.status, status => {
        if (['error', 'timeout'].includes(status)) finish({ status, retryable: true, issues: observer.issues.value })
      }, { flush: 'sync' })
    })
    enabled.value = lang
    // The compatibility function itself is an explicit action.
    if (force) observer.refresh(); else observer.start()
  })
}

// Conventional identifiers, units and proper names keep their original spelling.
const LABELS = {
  running: '运行中', starting: '正在启动', preparing: '准备中', pending: '待处理', completed: '已完成',
  failed: '失败', stopped: '已停止', stopping: '正在停止', paused: '已暂停', idle: '未运行', error: '错误',
  applied: '已应用', skipped: '已跳过', invalid: '无效', ok: '有效', held: '观望', none: '无',
  arbiter: '仲裁', seed: '初始设定', research: '研究依据', official: '官方数据', shock: '外生冲击',
  grounded: '有来源依据', mechanical: '机械推进', simulated: '模拟值',
  action: '行动', event: '事件', effect: '后续影响', scheduled: '计划事件', emergent: '涌现事件',
  consequence: '后果', resolution: '裁定', system: '系统事件', offer: '要约', agreement: '协议', breach: '违约',
  red_line: '越过红线', lapsed: '已失效', open: '待回应', deferred: '已延后', accepted: '已接受',
  rejected: '已拒绝', breached: '已违约', withdrawn: '已撤回', released: '已解除', kept: '已兑现',
  settled: '已履行', fulfilled: '已兑现', due: '已到期', voting: '投票中', expired: '已过期', superseded: '已替代',
  neutral: '中立', allied: '结盟', adversarial: '敌对', cooperative: '合作', transactional: '交易性关系', directional: '单向关系', closer: '趋近', further: '疏远',
  up: '上升', down: '下降', flat: '不变', changed: '已变化', unchanged: '未变化',
  yes: '是', no: '否', true: '是', false: '否', unknown: '未知', specified: '已指定', contested: '有争议',
  missing_evidence: '证据缺失', missing_actor: '参与者缺失', ungrounded: '缺少来源依据',
  Expected: '预期影响', Actor: '参与者', Agent: '智能体',
  execute: '执行', propose: '提议', accept: '接受', reject: '拒绝', counter: '还价', defer: '延后', withdraw: '撤回',
  source_claim: '来源陈述', report_excerpt: '报告摘录', scenario_assumption: '情景假设', simulation_event: '模拟事件',
  sovereign_government: '主权政府', institution: '机构', organization: '组织', company: '企业', individual: '个人',
  description: '描述', rationale: '理由', statement: '声明', explanation: '解释', terms: '条款',
  quantity: '数量', amount: '金额', cost: '成本', value: '数值', balance: '余额', reserved: '预留',
  kind: '类型', status: '状态', probability: '概率', confidence: '置信度', direction: '方向',
}

export function simulationLabel(value, lang = 'zh') {
  const source = value == null ? '' : String(value)
  return lang === 'zh' ? LABELS[source] || source : source
}

export function isSimulationProse(value) {
  return typeof value === 'string' && /[A-Za-z]{2}/.test(value)
    && !/^[A-Z][A-Z0-9&.-]+$/.test(value.trim())
    && !/^(?:https?:\/\/|\[S\d+\]$)/i.test(value.trim())
    && !/^[A-Za-z][\w.-]*[_:/][\w./:-]+$/.test(value.trim())
    && !/^\d{4}-\d\d(?:-\d\d)?(?:T[\d:.+Z-]+)?$/.test(value.trim())
}
const identityField = key => /(?:Id|Ids|_id|_ids|At|_at|Date|_date)$/.test(key)
  || /^(?:unit|refs|observedEvents|source_refs|targetMetric|targetAccount|field|target|template|citation)$/i.test(key)

export function simulationProse(value, key = '') {
  if (identityField(key)) return []
  if (Array.isArray(value)) return value.flatMap(item => simulationProse(item, key))
  if (value && typeof value === 'object') return Object.entries(value).flatMap(([field, item]) => simulationProse(item, field))
  return isSimulationProse(value) && !LABELS[value] ? [value] : []
}

export function simulationDisplayValue(value, translate, lang = 'zh', key = '') {
  if (identityField(key)) return value
  if (Array.isArray(value)) return value.map(item => simulationDisplayValue(item, translate, lang, key))
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([field, item]) =>
    [simulationLabel(field, lang), simulationDisplayValue(item, translate, lang, field)]))
  return typeof value === 'string' ? translate(simulationLabel(value, lang)) : value
}

// A pinned period can render 500 posts and 1000 replies. Bound each server
// request without silently dropping the tail of that page or a long persona.
export function simulationTranslationBatches(sources) {
  const pieces = new Map()
  for (const source of sources) {
    const parts = []
    let rest = source
    while (rest.length > 16000) {
      let cut = rest.lastIndexOf('\n', 16000)
      if (cut < 8000) cut = rest.lastIndexOf(' ', 16000)
      if (cut < 8000) cut = 16000
      // Keep the separator with its original segment.
      else cut += 1
      // Do not break a UTF-16 surrogate or a CRLF pair at a hard boundary.
      if (/[\uD800-\uDBFF]/.test(rest[cut - 1]) || (rest[cut - 1] === '\r' && rest[cut] === '\n')) cut--
      parts.push(rest.slice(0, cut)); rest = rest.slice(cut)
    }
    if (rest) parts.push(rest)
    pieces.set(source, parts)
  }
  const unique = [...new Set([...pieces.values()].flat().filter(isSimulationProse))]
  const batches = []
  let batch = [], length = 0
  for (const text of unique) {
    if (batch.length && (batch.length >= 1000 || length + text.length > 200000)) {
      batches.push(batch); batch = []; length = 0
    }
    batch.push(text); length += text.length
  }
  if (batch.length) batches.push(batch)
  return { pieces, batches }
}

const read = value => typeof value === 'function' ? value() : unref(value)

// Inventory construction stays in the adapter; the shared observer owns every
// request, timer, reconnect and action across both simulation engines.
export function useSimulationTranslation({ simulationId, context, texts, language,
  fetcher = simulationOverlayFetcher, pollMs = 5000 }) {
  const chosenLanguage = ref(null)
  const lang = computed(() => chosenLanguage.value || read(language) || 'en')
  const map = ref(new Map())
  const pending = ref(0)
  const selection = computed(() => ({ id: read(simulationId) || '', lang: lang.value,
    context: read(context) || {}, texts: [...new Set((read(texts) || []).filter(text =>
      isSimulationProse(text) && simulationLabel(text, 'zh') === text))].sort() }))
  const identity = () => {
    const current = selection.value
    return current.id && current.lang === 'zh' && current.texts.length ? current : null
  }
  const observer = useTranslationJob({ identity, pollMs,
    adapter: () => {
      const selected = selection.value
      const { pieces, batches } = simulationTranslationBatches(selected.texts)
      const clients = batches.map(batch => fetcher(selected.id, { texts: batch, context: selected.context }))
      const previous = clients.map(() => null)
      const collect = async (operation, { signal, force = false, action }) => {
        const states = []
        for (const [index, client] of clients.entries()) {
          // A progressing page never grants permission to retry a failed sibling.
          // Explicit Retry covers the selection; automatic continuation covers only
          // the batches whose server-issued continuation authorizes another page.
          if (operation === 'start' && action === 'continue' && previous[index]?.data.continuation?.available !== true) {
            states.push(previous[index]); continue
          }
          if (signal.aborted) throw new Error('Translation selection changed')
          const response = operation === 'get' ? await client.get('zh', { signal, timeout: 20000 })
            : await client.start('zh', force, { signal, timeout: 20000 })
          previous[index] = normalizeTranslationSnapshot(response)
          states.push(previous[index])
        }
        const active = states.some(state => state.active)
        const rows = states.flatMap(state => state.data.translations || [])
        const accepted = new Map(rows.map(row => [row.source, row.text]))
        const missing = batches.flat().filter(source => !accepted.has(source)).length
        const available = !missing && states.every(state => state.available && !state.partial)
        const state = active ? 'generating' : available ? 'available' : states.find(s => !s.available)?.state || 'partial'
        return { state, active, available, partial: !available,
          continue: !active && states.some(s => s.data.continuation?.available === true),
          refreshPending: states.reduce((total, state) => total + state.refreshPending, 0), issues: [...new Set(states.flatMap(s => s.issues))],
          coverage: { total: batches.flat().length, accepted: accepted.size, pending: missing },
          actions: { start: !active && !available, retry: !active && !available, refresh: !active && available },
          data: { translations: rows, pieces }, job: states.map(s => s.job).filter(Boolean) }
      }
      return { get: options => collect('get', options), start: options => collect('start', options) }
    },
    onReset: () => { map.value = new Map(); pending.value = 0 },
    onUpdate: state => {
      const translated = new Map(state.data.translations.map(row => [row.source, row.text]))
      map.value = new Map([...state.data.pieces].map(([source, parts]) => [source, parts.map(part => {
        const text = translated.get(part)
        return typeof text === 'string' && text.trim() ? part.match(/^\s*/)[0] + text.trim() + part.match(/\s*$/)[0] : part
      }).join('')]))
      pending.value = state.coverage.pending
    },
  })
  const display = source => {
    const value = source == null ? '' : String(source)
    return lang.value === 'zh' ? simulationLabel(map.value.get(value) || value, lang.value) : value
  }
  const structured = value => simulationDisplayValue(value, display, lang.value)
  const L = (zh, en) => lang.value === 'zh' ? zh : (en ?? zh)
  const retryable = computed(() => observer.actions.value.retry === true || observer.actions.value.start === true)
  const feedback = computed(() => {
    if (observer.status.value === 'reconnecting') return L('连接中断，正在重新查询已保存的翻译。', 'Connection interrupted; reconnecting to the saved translation.')
    if (observer.busy.value) return L('正在翻译当前视图；未完成部分暂显示原文。', 'Translating this view; unfinished passages show the source.')
    if (observer.status.value === 'partial') return L(`部分翻译已完成；${pending.value || '部分'}段仍保留原文，可重试。`, `Translation is partial; ${pending.value || 'some'} passages remain in the source. Retry is available.`)
    if (retryable.value) return L('此视图的翻译未完成，当前保留原文。请重试。', 'This view has untranslated content. The source remains visible. Generate or retry translation.')
    return ''
  })
  function toggle() {
    chosenLanguage.value = lang.value === 'zh' ? 'en' : 'zh'
    if (lang.value === 'zh') return observer.start()
  }
  const stopLanguage = watch(() => read(language), () => { chosenLanguage.value = null }, { flush: 'sync' })
  if (getCurrentScope()) onScopeDispose(stopLanguage)
  return { lang, chosenLanguage, status: observer.status, issues: observer.issues, pending,
    busy: observer.busy, retryable, feedback, display, structured, L, toggle, observer,
    start: observer.start, refresh: observer.refresh, retry: observer.retry, cancel: observer.cancel }
}
