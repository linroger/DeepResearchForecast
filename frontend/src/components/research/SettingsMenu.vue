<template>
  <div class="settings-scrim" @click.self="$emit('close')">
    <div class="settings-modal">
      <div class="modal-head">
        <span class="modal-title">◇ {{ L('设置', 'Settings') }}</span>
        <button class="modal-close" :aria-label="L('关闭', 'Close')" @click="$emit('close')">✕</button>
      </div>

      <div class="modal-body">
        <!-- 语言 -->
        <section class="block">
          <div class="block-label">{{ L('界面语言', 'Interface language') }}</div>
          <div class="seg">
            <button :class="{active: locale==='zh'}" @click="setLocale('zh')">中文</button>
            <button :class="{active: locale==='en'}" @click="setLocale('en')">English</button>
          </div>
        </section>

        <!-- 模型提供方 -->
        <section class="block">
          <div class="block-label">{{ L('模型提供方', 'Model provider') }}</div>
          <p class="hint">
            {{ L('切换对新发起的推演生效（运行中的不受影响）。Claude / Codex / Kimi / MiniMax / DeepSeek / 通义千问 / GLM 都有各自的深度研究模型；OpenAI 兼容 API 的研究阶段回退至 Claude。',
                 'Applies to new runs (in-flight runs are unaffected). Claude, Codex, Kimi, MiniMax, DeepSeek, Qwen and GLM each drive their own deep-research model; the OpenAI-compatible provider falls back to Claude for the research stage.') }}
          </p>

          <div v-if="loadingInfo" class="loading">{{ L('加载中…', 'Loading…') }}</div>
          <div v-else class="provider-list">
            <label v-for="p in providers" :key="p.id" class="provider-card" :class="{ active: selected===p.id }">
              <input type="radio" :value="p.id" v-model="selected" />
              <div class="provider-main">
                <div class="provider-name">
                  {{ p.label }}
                  <span v-if="p.id===current" class="cur-pill">{{ L('当前', 'current') }}</span>
                </div>
                <div class="provider-sub">
                  {{ p.needs_key ? L('需要 API Key', 'Requires API key') : L('使用本机 CLI 订阅，无需 Key', 'Uses local CLI subscription, no key') }}
                  · {{ L('研究', 'research') }}: {{ deerflowModelFor(p) }}
                </div>
              </div>
            </label>
          </div>

          <!-- 需要 Key 的提供方：填写 Key（可选 base/model 高级项） -->
          <div v-if="selectedNeedsKey" class="key-area">
            <label class="field-label">API Key
              <span v-if="selected===current && hasApiKey" class="faint">（{{ L('已配置，可留空沿用', 'configured — leave blank to keep') }}）</span>
            </label>
            <input v-model="apiKey" type="password" class="text-input"
              :placeholder="keyPlaceholder" autocomplete="off" />
            <details class="advanced">
              <summary>{{ L('高级（可选）', 'Advanced (optional)') }}</summary>
              <label class="field-label">Base URL</label>
              <input v-model="baseUrl" type="text" class="text-input" :placeholder="defaultBase" />
              <label class="field-label">{{ L('模型名', 'Model name') }}</label>
              <input v-model="model" type="text" class="text-input" :placeholder="defaultModel" />
            </details>
          </div>

          <!-- 连通性测试：API 提供方验证 Key，CLI 提供方检查本机 CLI。不持久化任何配置。 -->
          <div class="test-row">
            <button class="test-btn" :disabled="testing || !canTest" @click="testConnection">
              {{ testing ? L('测试中…', 'Testing…') : L('测试连接', 'Test connection') }}
            </button>
            <span v-if="testResult" class="test-result" :class="testResult.ok ? 'ok' : 'err'">
              <template v-if="testResult.ok">
                ✓ {{ L('连接成功', 'Connected') }}<template v-if="testResult.latency_ms"> · {{ testResult.latency_ms }}ms</template><template v-if="testResult.model"> · {{ testResult.model }}</template><template v-if="testResult.detail"> · {{ testResult.detail }}</template>
              </template>
              <template v-else>✗ {{ testResult.error }}</template>
            </span>
          </div>
        </section>

        <!-- i8/MON-1：市场判定监测手动触发（202=已启动 / 409=上一轮在飞 / 网络错误）。 -->
        <section class="block">
          <div class="block-label">{{ L('维护', 'Maintenance') }}</div>
          <p class="hint">
            {{ L('检查近期预测中锚定的预测市场是否已判定，并把结果回填到历史运行（后台执行，随时可触发；同一时刻只跑一轮）。',
                 'Checks whether prediction markets anchored in recent forecasts have resolved and back-fills outcomes into past runs (runs in the background; only one round at a time).') }}
          </p>
          <div class="test-row">
            <button class="test-btn" :disabled="monitorBusy" @click="runMonitor">
              {{ monitorBusy ? L('触发中…', 'Starting…') : L('市场判定监测', 'Market resolution check') }}
            </button>
            <span v-if="monitorNote" class="test-result" :class="monitorNote.tone" aria-live="polite">
              {{ monitorNote.text }}
            </span>
          </div>
        </section>

        <p v-if="error" class="err">{{ error }}</p>
        <p v-if="okMsg" class="ok">{{ okMsg }}</p>
      </div>

      <div class="modal-foot">
        <button class="ghost-btn" @click="$emit('close')">{{ L('取消', 'Cancel') }}</button>
        <button class="primary-btn" :disabled="saving || !canSave" @click="save">
          {{ saving ? L('保存中…', 'Saving…') : L('应用', 'Apply') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { getLlmSettings, setLlmSettings, testLlmSettings } from '../../api/settings'
import { runResolutionMonitor } from '../../api/research'
import { locale, setLocale, L } from '../../i18n'

const emit = defineEmits(['close', 'changed'])

const loadingInfo = ref(true)
const providers = ref([])
const current = ref('')
const hasApiKey = ref(false)
const selected = ref('')
const apiKey = ref('')
const baseUrl = ref('')
const model = ref('')
const saving = ref(false)
const error = ref('')
const okMsg = ref('')
const testing = ref(false)
const testResult = ref(null)

// 研究模型以后端 PROVIDER_META.deerflow_model 为准（/api/settings 随 providers 下发）；
// 本表只在旧后端未下发该字段时兜底，须与 backend/app/config.py 保持一致。
const DEERFLOW_MAP = {
  'claude-cli': 'claude', 'codex-cli': 'codex', openai: 'claude', kimi: 'kimi',
  minimax: 'minimax', deepseek: 'deepseek', qwen: 'qwen', glm: 'glm'
}
const DEFAULTS = {
  openai: { base: 'https://api.openai.com/v1', model: 'gpt-4o-mini', ph: 'sk-…' },
  kimi: { base: 'https://api.kimi.com/coding/v1', model: 'kimi-for-coding', ph: 'sk-…' },
  minimax: { base: 'https://api.minimaxi.com/v1', model: 'MiniMax-M3', ph: 'sk-cp-…' },
  deepseek: { base: 'https://api.deepseek.com/v1', model: 'deepseek-chat', ph: 'sk-…' },
  qwen: { base: 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus', ph: 'sk-…' },
  glm: { base: 'https://api.z.ai/api/paas/v4', model: 'glm-4.6', ph: '••••.••••' }
}
function deerflowModelFor(p) { return (p && p.deerflow_model) || DEERFLOW_MAP[p && p.id] || 'claude' }

const selectedMeta = computed(() => providers.value.find(p => p.id === selected.value) || {})
const selectedNeedsKey = computed(() => !!selectedMeta.value.needs_key)
const defaultBase = computed(() => (DEFAULTS[selected.value] || {}).base || '')
const defaultModel = computed(() => (DEFAULTS[selected.value] || {}).model || '')
const keyPlaceholder = computed(() => (DEFAULTS[selected.value] || {}).ph || 'API key')
const canSave = computed(() => {
  if (!selected.value) return false
  if (selectedNeedsKey.value && !(selected.value === current.value && hasApiKey.value) && !apiKey.value.trim()) return false
  return true
})
// 可测试 = 可保存的同一约束（CLI 提供方永远可测；API 提供方需要 Key 或已配置的沿用 Key）
const canTest = computed(() => canSave.value)

async function load() {
  loadingInfo.value = true
  error.value = ''
  try {
    const res = await getLlmSettings()
    const d = res.data || {}
    providers.value = d.providers || []
    current.value = d.current || ''
    hasApiKey.value = !!d.has_api_key
    selected.value = d.current || (providers.value[0] && providers.value[0].id) || ''
  } catch (e) {
    error.value = (e && e.message) || 'Failed to load settings'
  } finally {
    loadingInfo.value = false
  }
}

async function testConnection() {
  if (!canTest.value || testing.value) return
  testing.value = true
  testResult.value = null
  try {
    const payload = { provider: selected.value }
    if (selectedNeedsKey.value) {
      if (apiKey.value.trim()) payload.api_key = apiKey.value.trim()
      if (baseUrl.value.trim()) payload.base_url = baseUrl.value.trim()
      if (model.value.trim()) payload.model = model.value.trim()
    }
    const res = await testLlmSettings(payload)
    testResult.value = res.data || { ok: false, error: 'Empty response' }
  } catch (e) {
    testResult.value = { ok: false, error: (e && e.message) || 'Test failed' }
  } finally {
    testing.value = false
  }
}

async function save() {
  if (!canSave.value || saving.value) return
  saving.value = true; error.value = ''; okMsg.value = ''
  try {
    const payload = { provider: selected.value }
    if (selectedNeedsKey.value) {
      if (apiKey.value.trim()) payload.api_key = apiKey.value.trim()
      if (baseUrl.value.trim()) payload.base_url = baseUrl.value.trim()
      if (model.value.trim()) payload.model = model.value.trim()
    }
    const res = await setLlmSettings(payload)
    const d = res.data || {}
    current.value = d.current || selected.value
    hasApiKey.value = !!d.has_api_key
    apiKey.value = ''
    okMsg.value = L('已切换到 ', 'Switched to ') + (selectedMeta.value.label || selected.value)
    emit('changed', d)
  } catch (e) {
    error.value = (e && e.message) || 'Failed to apply'
  } finally {
    saving.value = false
  }
}

// ---------- i8/MON-1：市场判定监测手动触发 ----------
const monitorBusy = ref(false)
const monitorNote = ref(null)   // { tone: 'ok'|'warn'|'err', text } — 瞬态提示，6s 后自清
let monitorNoteTimer = null

function setMonitorNote(tone, text) {
  monitorNote.value = { tone, text }
  if (monitorNoteTimer) clearTimeout(monitorNoteTimer)
  monitorNoteTimer = setTimeout(() => { monitorNote.value = null }, 6000)
}

async function runMonitor() {
  if (monitorBusy.value) return
  monitorBusy.value = true
  monitorNote.value = null
  try {
    const res = await runResolutionMonitor()
    if (res && res.data && res.data.started) {
      setMonitorNote('ok', '✓ ' + L('已在后台启动一轮判定监测', 'Resolution check started in the background'))
    } else {
      // 2xx 但缺 started 契约字段：防御性提示，不假装确认成功。
      setMonitorNote('warn', L('请求已受理，但后端未确认启动', 'Request accepted, but the backend did not confirm a start'))
    }
  } catch (e) {
    const resp = e && e.response
    if ((resp && resp.status === 409) || (resp && resp.data && resp.data.inflight)) {
      setMonitorNote('warn', L('上一轮判定监测仍在运行', 'A resolution check is already running'))
    } else {
      setMonitorNote('err', '✗ ' + ((e && e.message) || L('无法启动判定监测', 'Unable to start the resolution check')))
    }
  } finally {
    monitorBusy.value = false
  }
}

// 切换提供方时清掉上一次的测试结果，避免误读为新选择的状态
watch(selected, () => { testResult.value = null })

onMounted(load)
onBeforeUnmount(() => { if (monitorNoteTimer) clearTimeout(monitorNoteTimer) })
</script>

<style scoped>
.settings-scrim { position: fixed; inset: 0; background: rgba(0,0,0,.4); z-index: 60; display: flex; align-items: center; justify-content: center; animation: sm-fade var(--dur-2, 180ms) var(--ease, ease); }
.settings-modal {
  width: 560px; max-width: 92vw; max-height: 88vh; background: #fff; border: 1px solid #000;
  display: flex; flex-direction: column; box-shadow: var(--shadow-pop, 0 24px 64px rgba(10,10,10,.28));
  --orange: #FF4500; --border: #E5E5E5; --mono: 'JetBrains Mono', monospace;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
  animation: sm-rise var(--dur-3, 250ms) var(--ease, ease);
}
@keyframes sm-fade { from { opacity: 0; } }
@keyframes sm-rise { from { opacity: 0; transform: translateY(10px); } }
.modal-head { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid var(--border); }
.modal-title { font-family: var(--mono); font-weight: 700; font-size: .95rem; }
.modal-close { background: none; border: none; font-size: 1.1rem; cursor: pointer; color: var(--color-muted, #666); transition: color var(--dur-1, 120ms) var(--ease, ease); }
.modal-close:hover { color: var(--color-ink, #000); }
.modal-body { padding: 20px; overflow-y: auto; }
.block { margin-bottom: 24px; }
.block-label { font-family: var(--mono); font-size: .74rem; color: #888; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 10px; }
.hint { font-size: .78rem; color: #888; line-height: 1.6; margin-bottom: 14px; }
.seg { display: inline-flex; border: 1px solid #DDD; border-radius: var(--radius, 2px); overflow: hidden; }
.seg button { background: #fff; border: none; border-right: 1px solid #eee; padding: 8px 18px; font-family: var(--mono); font-size: .82rem; cursor: pointer; color: #555; transition: background var(--dur-1, 120ms) var(--ease, ease), color var(--dur-1, 120ms) var(--ease, ease); }
.seg button:last-child { border-right: none; }
.seg button:hover:not(.active) { background: var(--color-soft, #FAFAFA); color: #000; }
.seg button.active { background: #000; color: #fff; }
.loading { color: #999; font-family: var(--mono); font-size: .82rem; }
.provider-list { display: flex; flex-direction: column; gap: 8px; }
.provider-card { display: flex; align-items: center; gap: 12px; border: 1px solid var(--border); border-radius: var(--radius, 2px); padding: 12px 14px; cursor: pointer; transition: border-color var(--dur-1, 120ms) var(--ease, ease), background var(--dur-1, 120ms) var(--ease, ease); }
.provider-card:hover { border-color: #bbb; background: var(--color-soft, #FAFAFA); }
.provider-card.active { border-color: var(--orange); background: var(--color-accent-soft, #FFF6F2); }
.provider-card input { accent-color: var(--orange); }
.provider-main { flex: 1; }
.provider-name { font-weight: 600; font-size: .92rem; display: flex; align-items: center; gap: 8px; }
.cur-pill { background: #16a34a; color: #fff; font-family: var(--mono); font-size: .6rem; padding: 1px 6px; border-radius: 8px; }
.provider-sub { font-size: .74rem; color: #888; margin-top: 3px; font-family: var(--mono); }
.key-area { margin-top: 14px; border-top: 1px dashed var(--border); padding-top: 14px; }
.field-label { display: block; font-family: var(--mono); font-size: .72rem; color: #888; margin: 10px 0 5px; }
.faint { color: #bbb; }
.text-input { width: 100%; border: 1px solid #DDD; padding: 9px 11px; font-family: var(--mono); font-size: .82rem; outline: none; }
.text-input:focus { border-color: var(--orange); }
.advanced { margin-top: 8px; }
.advanced summary { font-family: var(--mono); font-size: .74rem; color: #888; cursor: pointer; }
.modal-foot { display: flex; justify-content: flex-end; gap: 10px; padding: 14px 20px; border-top: 1px solid var(--border); }
.primary-btn { background: var(--orange); color: #fff; border: none; border-radius: var(--radius, 2px); padding: 10px 20px; font-family: var(--mono); font-weight: 700; cursor: pointer; transition: opacity var(--dur-1, 120ms) var(--ease, ease); }
.primary-btn:hover:not(:disabled) { opacity: .88; }
.primary-btn:disabled { background: #E5E5E5; color: #999; cursor: not-allowed; }
.ghost-btn { background: #fff; border: 1px solid #DDD; border-radius: var(--radius, 2px); padding: 10px 18px; font-family: var(--mono); cursor: pointer; transition: border-color var(--dur-1, 120ms) var(--ease, ease); }
.ghost-btn:hover { border-color: var(--color-ink, #000); }
.err { color: var(--orange); font-family: var(--mono); font-size: .8rem; margin-top: 12px; }
.ok { color: #16a34a; font-family: var(--mono); font-size: .8rem; margin-top: 12px; }
.test-row { display: flex; align-items: center; gap: 12px; margin-top: 14px; flex-wrap: wrap; }
.test-btn { background: #fff; border: 1px solid #000; padding: 8px 16px; font-family: var(--mono); font-size: .78rem; font-weight: 700; cursor: pointer; }
.test-btn:hover:not(:disabled) { background: #000; color: #fff; }
.test-btn:disabled { border-color: #DDD; color: #999; cursor: not-allowed; }
.test-result { font-family: var(--mono); font-size: .76rem; line-height: 1.5; word-break: break-word; }
.test-result.ok { color: #16a34a; margin-top: 0; }
.test-result.err { color: var(--orange); margin-top: 0; }
.test-result.warn { color: var(--color-warn, #D97706); margin-top: 0; }
</style>
