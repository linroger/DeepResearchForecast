import { ref, computed, unref, watch, onScopeDispose, getCurrentScope } from 'vue'

const read = value => typeof value === 'function' ? value() : unref(value)

// All translation surfaces share this observer. GET never acquires provider work;
// only explicit start/retry/refresh crosses the mutation boundary. Every awaited
// continuation carries both a resource-selection key and a request generation.
export function useTranslationJob({ identity, adapter, onUpdate = () => {}, onReset = () => {},
  pollMs = 2500, maxPolls = 120, maxErrors = 6, maxPages = 20 }) {
  const snapshot = ref(null)
  const status = ref('source')
  const issues = ref([])
  const error = ref('')
  const loading = ref(false)
  const busy = computed(() => loading.value || snapshot.value?.active === true || status.value === 'reconnecting')
  const coverage = computed(() => snapshot.value?.coverage || { total: 0, accepted: 0, pending: 0 })
  const actions = computed(() => ({ ...(snapshot.value?.actions || {}),
    ...(error.value || status.value === 'timeout' ? { retry: true } : {}) }))
  const key = computed(() => {
    const value = read(identity)
    return value == null || value === false || value === '' ? '' : JSON.stringify(value)
  })
  let generation = 0, timer = null, controller = null, polls = 0, failures = 0
  let transport = null, disposed = false, mutation = null
  let requested = false, pages = 0, progressed = 0, refreshProgress = 0

  function invalidate() {
    ++generation
    clearTimeout(timer); timer = null
    controller?.abort(); controller = null
    mutation = null
    loading.value = false
  }
  function cancel() {
    invalidate()
    snapshot.value = null; status.value = 'source'; issues.value = []; error.value = ''
    onReset()
  }
  function schedule(ticket, selectedKey, delay, action = 'observe') {
    if (disposed || ticket !== generation || selectedKey !== key.value) return
    clearTimeout(timer)
    timer = setTimeout(() => { timer = null; request(action, false) }, delay)
  }
  async function request(action, restart = true) {
    if (disposed || !key.value) return null
    if (action !== 'observe' && mutation) return mutation
    if (restart) {
      invalidate(); polls = 0; failures = 0
      requested = action !== 'observe'; pages = 0; progressed = snapshot.value?.coverage?.accepted || 0
      refreshProgress = action === 'refresh' ? Infinity : snapshot.value?.refreshPending || 0
      transport = read(adapter)
    }
    const ticket = generation, selectedKey = key.value
    const token = new AbortController()
    controller = token
    const current = () => !disposed && ticket === generation && selectedKey === key.value && !token.signal.aborted
    const activeTransport = transport || read(adapter)
    loading.value = true; error.value = ''
    const execute = async () => {
      try {
        if (!current()) return null
        if (action !== 'observe') pages++
        const next = action === 'observe'
          ? await activeTransport.get({ signal: token.signal })
          : await activeTransport.start({ signal: token.signal, force: action === 'refresh', action })
        if (!current()) return null
        if (!next || typeof next.active !== 'boolean' || !next.state) throw new Error('Invalid translation status response')
        const previousJob = snapshot.value?.job
        if (next.job?.job_id && next.job.job_id === previousJob?.job_id
            && Number(next.job.job_revision) < Number(previousJob.job_revision)) {
          if (++polls >= maxPolls) {
            status.value = 'timeout'
            snapshot.value = { ...snapshot.value, active: false }
            error.value = 'Translation status is out of date. Reconnect to check the saved job.'
          } else schedule(ticket, selectedKey, pollMs)
          return snapshot.value
        }
        snapshot.value = next; status.value = next.state; issues.value = next.issues || []; failures = 0
        await onUpdate(next, { isCurrent: current, signal: token.signal })
        if (!current()) return null
        if (next.active) {
          if (++polls >= maxPolls) {
            status.value = 'timeout'
            snapshot.value = { ...next, active: false, actions: { ...next.actions, retry: true } }
            error.value = 'Translation observation timed out. Reconnect to check the saved job.'
          } else schedule(ticket, selectedKey, pollMs)
        } else if (requested && next.continue === true && (next.coverage?.pending > 0 || next.refreshPending > 0)
            && (next.coverage.accepted > progressed || next.refreshPending < refreshProgress) && pages < maxPages) {
          progressed = next.coverage.accepted
          refreshProgress = next.refreshPending || 0
          snapshot.value = { ...next, active: true }
          status.value = 'generating'
          schedule(ticket, selectedKey, pollMs, 'continue')
        }
        return next
      } catch (cause) {
        if (!current()) return null
        if (cause?.retryable === false) { snapshot.value = null; onReset() }
        error.value = String(cause?.message || cause)
        issues.value = [...new Set([...(snapshot.value?.issues || []), error.value])]
        // An uncertain POST is never repeated automatically. Reconnect by GET,
        // since the server may already have durably accepted it.
        if (cause?.retryable !== false && ++failures < maxErrors) {
          status.value = 'reconnecting'
          schedule(ticket, selectedKey, Math.min(20000, Math.max(1, pollMs) * 2 ** (failures - 1)))
        } else {
          status.value = 'error'
          if (snapshot.value) snapshot.value = { ...snapshot.value, active: false }
        }
        return null
      } finally {
        if (current()) { loading.value = false; mutation = null }
      }
    }
    const promise = execute()
    if (action !== 'observe') {
      mutation = promise
      promise.finally(() => { if (mutation === promise) mutation = null })
    }
    return promise
  }
  const observe = () => request('observe')
  const start = () => request('start')
  const retry = () => status.value === 'timeout' || status.value === 'reconnecting' || snapshot.value?.active
    ? observe() : request('retry')
  const refresh = () => request('refresh')
  const stop = watch(key, () => { cancel(); if (key.value) observe() }, { immediate: true, flush: 'sync' })
  const reconnect = () => { if (key.value && (error.value || snapshot.value?.active)) observe() }
  if (typeof window !== 'undefined') window.addEventListener?.('online', reconnect)
  if (getCurrentScope()) onScopeDispose(() => {
    disposed = true; stop(); cancel()
    if (typeof window !== 'undefined') window.removeEventListener?.('online', reconnect)
  })
  return { snapshot, status, issues, error, busy, loading, coverage, actions,
    observe, start, retry, refresh, cancel }
}
