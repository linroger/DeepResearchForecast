import { ref, computed, watch, onScopeDispose, getCurrentScope } from 'vue'
import { getGraphTranslation, startGraphTranslation,
         getSimulationTranslation, startSimulationTranslation } from '../api/translations'

const body = response => response?.data?.data || response?.data || response || {}
const aborted = () => Object.assign(new Error('Translation request cancelled'), { name: 'AbortError' })
const contextKey = context => JSON.stringify(Object.entries(context || {}).sort(([a], [b]) => a.localeCompare(b)))
const OVERLAY_STATES = new Set(['available', 'empty', 'partial', 'generating', 'pending', 'running', 'queued',
  'error', 'failed', 'stale', 'timeout', 'unavailable', 'missing', 'interrupted'])

export function graphOverlayFetcher(graphId) {
  return {
    get: (lang, options) => getGraphTranslation(graphId, lang, options),
    start: (lang, force, options) => startGraphTranslation(graphId, lang, force, options),
  }
}

// Poll only the digest of the exact visible selection, never a whole private cache.
export function simulationOverlayFetcher(simId, selection) {
  if (!selection) return {
    get: (lang, options) => getSimulationTranslation(simId, lang, options),
    start: (lang, force, options) => startSimulationTranslation(simId, lang, force, options),
  }
  let digest = ''
  let fingerprint = ''
  const checked = (response, lang) => {
    const data = body(response)
    if (data.simulation_id !== simId || data.target_lang !== lang || !/^[a-f0-9]{64}$/.test(data.request_digest)
        || !/^[a-f0-9]{64}$/.test(data.source_fingerprint)
        || contextKey(data.context) !== contextKey(selection.context)
        || (digest && digest !== data.request_digest) || (fingerprint && fingerprint !== data.source_fingerprint)) {
      throw new Error('Translation response does not match the selected simulation and language')
    }
    digest = data.request_digest
    fingerprint = data.source_fingerprint
    return response
  }
  return {
    preferStart: true,
    async start(lang, force, options) {
      return checked(await startSimulationTranslation(simId, lang, force, { ...options, ...selection }), lang)
    },
    async get(lang, options) {
      return checked(await getSimulationTranslation(simId, lang, { ...options,
        params: { request_digest: digest, context: JSON.stringify(selection.context) } }), lang)
    },
  }
}

function delay(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(aborted()); return }
    const cancel = () => { clearTimeout(timer); reject(aborted()) }
    const timer = setTimeout(() => { signal?.removeEventListener('abort', cancel); resolve() }, ms)
    signal?.addEventListener('abort', cancel, { once: true })
  })
}

// Errors are explicit while the source stays visible. Poll only recognized active
// states; stale and partial results offer an explicit retry instead of disappearing.
export async function ensureOverlay(fetcher, lang, { maxPolls = 60, pollMs = 5000,
  signal, force = false, onUpdate = () => {}, timeout = 20000 } = {}) {
  const options = { signal, timeout }
  const check = () => { if (signal?.aborted) throw aborted() }
  const active = data => ['generating', 'pending', 'running', 'queued'].includes(data.status)
  const emit = data => {
    check()
    const result = OVERLAY_STATES.has(data?.status) ? data : { status: 'error', retryable: true,
      issues: ['Unrecognized translation status; please retry'] }
    onUpdate(result)
    return result
  }
  try {
    check()
    let data = body(fetcher.preferStart
      ? await fetcher.start(lang, force, options) : await fetcher.get(lang, options))
    data = emit(data)
    if (!fetcher.preferStart && (force || ['empty', 'unavailable', 'missing', 'stale'].includes(data.status))) {
      check()
      data = body(await fetcher.start(lang, force, options))
      data = emit(data)
    }
    for (let i = 0; active(data) && i < maxPolls; i++) {
      await delay(pollMs, signal)
      check()
      data = body(await fetcher.get(lang, options))
      data = emit(data)
    }
    return active(data) ? emit({ ...data, status: 'timeout', retryable: true }) : data
  } catch (error) {
    if (signal?.aborted) return { status: 'cancelled' }
    return emit({ status: 'error', retryable: true, issues: [String(error?.message || error)] })
  }
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

const read = value => typeof value === 'function' ? value() : value?.value ?? value

// Source text is never mutated. Identity/language/view/period and exact source
// strings form one versioned request; old completions cannot release a new task.
export function useSimulationTranslation({ simulationId, context, texts, language,
  fetcher = simulationOverlayFetcher, pollMs = 5000 }) {
  const chosenLanguage = ref(null)
  const lang = computed(() => chosenLanguage.value || read(language) || 'en')
  const status = ref('source')
  const issues = ref([])
  const pending = ref(0)
  const map = ref(new Map())
  const busy = computed(() => ['generating', 'pending', 'running', 'queued'].includes(status.value))
  const retryable = computed(() => ['partial', 'error', 'failed', 'stale', 'timeout', 'unavailable', 'interrupted'].includes(status.value))
  let version = 0
  let controller = null
  const selection = computed(() => ({ id: read(simulationId) || '', lang: lang.value,
    context: read(context) || {}, texts: [...new Set((read(texts) || []).filter(text =>
      isSimulationProse(text) && simulationLabel(text, 'zh') === text))].sort() }))
  const key = computed(() => JSON.stringify(selection.value))
  const display = source => {
    const value = source == null ? '' : String(source)
    if (lang.value !== 'zh') return value
    return simulationLabel(map.value.get(value) || value, lang.value)
  }
  const structured = value => simulationDisplayValue(value, display, lang.value)
  const L = (zh, en) => lang.value === 'zh' ? zh : (en ?? zh)
  const feedback = computed(() => {
    if (busy.value) return L('正在翻译当前视图；未完成部分暂显示原文。', 'Translating this view; unfinished passages show the source.')
    if (status.value === 'partial') return L(`部分翻译已完成；${pending.value || '部分'}段仍保留原文，可重试。`, `Translation is partial; ${pending.value || 'some'} passages remain in the source. Retry is available.`)
    if (status.value === 'timeout') return L('翻译仍未完成，可重试查看最新结果；当前保留原文。', 'Translation did not finish in time. Retry to check again; the source remains visible.')
    if (retryable.value) return L('此视图的翻译未完成，当前保留原文。请重试。', 'This view could not be translated. The source remains visible. Please retry.')
    return ''
  })
  async function refresh(force = false) {
    const ticket = ++version
    controller?.abort()
    controller = new AbortController()
    const signal = controller.signal
    const snapshot = selection.value
    const snapshotKey = key.value
    map.value = new Map(); issues.value = []; pending.value = 0
    if (!snapshot.id || snapshot.lang !== 'zh' || !snapshot.texts.length) { status.value = 'source'; return }
    const current = () => ticket === version && !signal.aborted && snapshotKey === key.value
    status.value = 'generating'
    const { pieces, batches } = simulationTranslationBatches(snapshot.texts)
    const collected = new Map()
    const update = (data, final = false) => {
      if (!current()) return
      const entries = Array.isArray(data.translations) ? data.translations : []
      const wanted = new Set(batches.flat())
      for (const row of entries) {
        if (row && wanted.has(row.source) && /^[a-f0-9]{64}$/.test(row.source_sha256)
            && typeof row.text === 'string' && row.text.trim()) collected.set(row.source, row.text)
      }
      let missing = 0
      map.value = new Map([...pieces].map(([source, parts]) => [source, parts.map(part => {
        if (!isSimulationProse(part)) return part
        if (!collected.has(part)) missing++
        const translated = collected.get(part)
        // Providers commonly trim a chunk. Restore source separators so adjacent
        // numeric/name tokens cannot fuse when translated segments are joined.
        return translated ? part.match(/^\s*/)[0] + translated.trim() + part.match(/\s*$/)[0] : part
      }).join('')]))
      pending.value = missing
      status.value = final ? (missing ? (collected.size || ['available', 'empty'].includes(data.status) ? 'partial' : data.status || 'error') : 'available') : 'generating'
      if (Array.isArray(data.issues)) issues.value = [...new Set([...issues.value, ...data.issues])]
    }
    let last = { status: 'available' }
    for (const batch of batches) {
      if (!current()) return
      last = await ensureOverlay(fetcher(snapshot.id, { texts: batch, context: snapshot.context }), 'zh',
        { signal, force, pollMs, onUpdate: data => update(data) })
      if (!current()) return
      update(last)
    }
    update(last, true)
  }
  function toggle() { chosenLanguage.value = lang.value === 'zh' ? 'en' : 'zh' }
  function cancel() { ++version; controller?.abort(); status.value = 'source'; map.value = new Map() }
  const stopLanguage = watch(() => read(language), () => { chosenLanguage.value = null }, { flush: 'sync' })
  const stop = watch(key, () => { refresh() }, { immediate: true })
  if (getCurrentScope()) onScopeDispose(() => { stop(); stopLanguage(); cancel() })
  return { lang, chosenLanguage, status, issues, pending, busy, retryable, feedback, display, structured, L,
    toggle, refresh, retry: () => refresh(true), cancel }
}
