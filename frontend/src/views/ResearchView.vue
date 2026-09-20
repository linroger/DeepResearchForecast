<template>
  <div class="research-container">
    <!-- 顶部导航 -->
    <nav class="navbar">
      <div class="nav-brand">DeepResearch<span class="brand-accent">Forecast</span></div>
      <div class="nav-links">
        <span class="nav-tag">{{ L('STEP 0 · 深度研究 → 模拟 → 预测', 'STEP 0 · Research → Simulate → Forecast') }}</span>
        <button class="nav-icon-btn" :title="L('界面语言','Language')" @click="toggleLocale">{{ locale === 'en' ? '中' : 'EN' }}</button>
        <button class="nav-icon-btn" :title="L('设置','Settings')" :aria-label="L('设置','Settings')" @click="showSettings = true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>
        <button class="nav-hist-btn" :title="L('历史推演','History')" :aria-label="L('历史推演','History')" @click="showHistory = !showHistory">
          <span class="nav-hist-label">{{ L('历史推演','History') }}</span>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
            <line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
      </div>
    </nav>

    <!-- 历史抽屉 -->
    <transition name="drawer">
      <div v-if="showHistory" class="history-drawer">
        <div class="drawer-head">
          <span>{{ L('历史推演','Run history') }}</span>
          <button class="drawer-close" :aria-label="L('关闭','Close')" @click="showHistory = false">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <PipelineHistory :active-id="pipelineId" @select="selectPipeline" @deleted="onRunDeleted" />
      </div>
    </transition>
    <transition name="fade">
      <div v-if="showHistory" class="drawer-scrim" @click="showHistory = false"></div>
    </transition>

    <!-- 设置 -->
    <SettingsMenu v-if="showSettings" @close="showSettings = false" @changed="onProviderChanged" />

    <!-- 危险操作确认弹窗（替代 window.confirm） -->
    <ConfirmDialog ref="confirmDlg" />

    <div class="main-content">
      <!-- ====== 输入阶段 ====== -->
      <section v-if="!pipelineId" class="setup-section">
        <div class="tag-row">
          <span class="orange-tag">{{ L('一句话 · 从调研到推演', 'One prompt · research to forecast') }}</span>
          <span class="version-text">/ DeerFlow × OASIS</span>
        </div>
        <h1 class="main-title">
          {{ L('输入一个问题', 'Ask one question') }}<br>
          <span class="gradient-text">{{ L('自动调研、构建世界、推演未来', 'auto-research, build a world, simulate the future') }}</span>
        </h1>
        <p class="lead">
          {{ L('深度研究 Agent（DeerFlow）联网搜集资料、提取关键参与者并生成研究档案；据此构建知识图谱、生成数字人设、运行多智能体群体模拟（OASIS 双平台），最终由报告 Agent 产出可交互的预测报告。',
               'A deep-research agent (DeerFlow) searches the web, extracts the key actors and builds a research dossier; the system then constructs a knowledge graph, generates digital personas, runs a multi-agent population simulation (OASIS, dual-platform), and a report agent synthesizes an interactive forecast.') }}
        </p>

        <div class="console-box">
          <div class="console-section">
            <div class="console-header"><span class="console-label">&gt;_ {{ L('研究 / 预测问题', 'Research / forecast question') }}</span></div>
            <div class="input-wrapper">
              <textarea v-model="prompt" class="code-input" rows="6" :disabled="starting"
                :placeholder="L('// 例：预判2035年前全球电动汽车市场的发展趋势', '// e.g. Forecast global EV market trends through 2035')"></textarea>
            </div>
            <div class="examples">
              <span class="ex-label">{{ L('示例：','Examples:') }}</span>
              <button v-for="(ex, i) in exampleList" :key="i" class="ex-chip" @click="prompt = ex" :disabled="starting">{{ exShort(ex) }}</button>
            </div>
          </div>

          <div class="console-divider"><span>{{ L('参数','Parameters') }}</span></div>

          <div class="console-section params-row">
            <div class="param">
              <label>{{ L('模式','Mode') }}</label>
              <div class="seg">
                <button :class="{active: mode==='full'}" @click="mode='full'" :disabled="starting">{{ L('完整管线','Full pipeline') }}</button>
                <button :class="{active: mode==='research_only'}" @click="mode='research_only'" :disabled="starting">{{ L('仅研究','Research only') }}</button>
              </div>
            </div>
            <div class="param">
              <label>{{ L('研究深度','Research depth') }}</label>
              <div class="seg">
                <button v-for="d in depths" :key="d" :class="{active: depth===d}" @click="depth=d" :disabled="starting">{{ depthLabel(d) }}</button>
              </div>
            </div>
            <div class="param" v-if="mode==='full'">
              <label>{{ L('回合上限（日历模式下将粗化时间粒度，不截断预测期）','Round cap (calendar mode coarsens time granularity, never truncates the horizon)') }}</label>
              <input v-model.number="maxRounds" type="number" min="1" :placeholder="L('留空=按时长自动','blank = auto')" class="num-input" :disabled="starting"/>
            </div>
          </div>

          <!-- T5.5: 高级（研究语言 + 研究模型，每次运行覆盖） -->
          <div class="adv-toggle" @click="showAdvanced = !showAdvanced">
            <span class="adv-caret">{{ showAdvanced ? '▾' : '▸' }}</span>
            {{ L('高级','Advanced') }}
          </div>
          <div v-show="showAdvanced" class="console-section params-row adv-row">
            <div class="param">
              <label>{{ L('研究语言','Research language') }}</label>
              <select v-model="researchLanguage" class="adv-select" :disabled="starting">
                <option v-for="o in LANGUAGE_OPTIONS" :key="o.v" :value="o.v">{{ locale==='en' ? o.en : o.zh }}</option>
              </select>
            </div>
            <div class="param">
              <label>{{ L('研究模型','Research model') }}</label>
              <select v-model="researchModel" class="adv-select" :disabled="starting">
                <option value="">{{ L('默认','Default') }}</option>
                <option v-for="m in DEERFLOW_MODELS" :key="m" :value="m">{{ m }}</option>
              </select>
            </div>
          </div>

          <!-- T5.6: 就绪检查横幅 -->
          <div v-if="preflightChecked && !preflightReady" class="preflight-banner err-banner">
            <div class="pf-title">⚠ {{ L('启动前检查未通过','Not ready to launch') }}</div>
            <ul class="pf-list">
              <li v-for="(e, i) in preflightErrors" :key="i">{{ e }}</li>
            </ul>
          </div>
          <div v-else-if="preflightChecked && preflightReady" class="preflight-banner ok-banner">
            ✓ {{ L('配置就绪，可以启动','Configuration ready') }}
          </div>

          <div class="console-section btn-section">
            <button class="start-engine-btn" @click="start" :disabled="!canStart || starting">
              <span v-if="!starting">{{ mode==='full' ? L('启动 研究 + 模拟 + 预测','Run research + simulate + forecast') : L('启动深度研究','Run deep research') }}</span>
              <span v-else>{{ L('初始化中…','Initializing…') }}</span>
              <span class="btn-arrow">→</span>
            </button>
            <p v-if="error" class="err">{{ error }}</p>
          </div>
        </div>
      </section>

      <!-- ====== 运行 / 结果阶段 ====== -->
      <section v-else class="run-section">
        <div class="run-header">
          <div>
            <div class="console-label">
              {{ L('管线','Pipeline') }}
              <button type="button" class="pid-chip" :title="pipelineId"
                :aria-label="L('复制管线 ID','Copy pipeline id')" @click="copyPipelineId">
                {{ shortPipelineId }}
                <span v-if="pidCopied" class="pid-copied">✓ {{ L('已复制','Copied') }}</span>
              </button>
            </div>
            <h2 class="run-title">{{ statusTitle }}</h2>
            <RunVitals :live="liveVitals" :status="status"
              :created-at="runTiming.createdAt" :updated-at="runTiming.updatedAt"
              :resumed-at="runTiming.resumedAt" />
          </div>
          <div class="run-actions">
            <button v-if="status === 'running'" class="ghost-btn cancel-btn" :disabled="cancelling" @click="cancel">
              {{ cancelling ? L('取消中…','Cancelling…') : L('取消','Cancel') }}
            </button>
            <button v-if="canResume" class="ghost-btn resume-btn" :disabled="resuming" @click="resume">
              {{ resuming ? L('恢复中…','Resuming…') : L('继续','Resume') }}
            </button>
            <button v-if="canContinue" class="ghost-btn resume-btn" :disabled="continuing" @click="continueToFull">
              {{ continuing ? L('继续中…','Continuing…') : L('继续完整管线 →','Continue to full pipeline →') }}
            </button>
            <button class="ghost-btn" @click="showHistory = true">{{ L('历史','History') }}</button>
            <button class="ghost-btn" @click="reset">＋ {{ L('新建','New') }}</button>
          </div>
        </div>

        <div class="run-prompt-card">
          <span class="run-prompt-label">{{ L('初始研究 / 预测问题', 'Initial research / forecast prompt') }}</span>
          <p>{{ runPrompt || L('正在载入原始问题…', 'Loading the original prompt…') }}</p>
        </div>

        <div class="run-layout">
          <aside class="rail">
            <StageTimeline :stages="stages" :current-stage="currentStage" :mode="mode" :global-progress="globalProgress" />
          </aside>

          <div class="workspace">
            <div class="tabbar">
              <button v-for="t in tabs" :key="t.key"
                class="tab" :class="{ active: activeTab===t.key, disabled: !t.enabled }"
                :disabled="!t.enabled" @click="pickTab(t.key)">
                {{ t.label }}<span v-if="t.badge" class="tab-badge">{{ t.badge }}</span>
              </button>
            </div>

            <div class="tab-body">
              <ResearchConsole v-show="activeTab==='log'" :log-lines="logLines"
                :history-meta="logHistoryMeta" @refresh="refreshFullResearchLog" />
              <DossierViewer v-show="activeTab==='dossier'" :dossier="dossier"
                :pipeline-id="pipelineId" :editable="canContinue" @saved-continue="continueToFull" />
              <div v-show="activeTab==='graph'" class="graph-wrap" :class="{ max: graphMax }">
                <GraphPanel v-if="graphData" :graph-data="graphData" :loading="graphLoading"
                  :seed-actors="seedActorNames"
                  @refresh="fetchGraph(true)" @toggle-maximize="graphMax = !graphMax" />
                <div v-else class="lazy-empty">
                  <template v-if="graphLoading">
                    <span class="lazy-spinner" aria-hidden="true"></span>
                    <span>{{ L('加载知识图谱…','Loading knowledge graph…') }}</span>
                  </template>
                  <template v-else-if="graphId">
                    <span class="lazy-icon" aria-hidden="true">◇</span>
                    <button class="primary-btn" @click="fetchGraph(true)">{{ L('加载知识图谱','Load knowledge graph') }} →</button>
                  </template>
                  <template v-else>
                    <span class="lazy-icon" aria-hidden="true">◇</span>
                    <span>{{ L('知识图谱构建完成后可在此查看…','The knowledge graph will appear here once built…') }}</span>
                  </template>
                </div>
              </div>
              <SimulationView v-show="activeTab==='sim'" :simulation-id="simulationId" />
              <ForecastReport v-show="activeTab==='report'" :report-id="reportId" />
            </div>
          </div>
        </div>

        <p v-if="error" class="err run-err">{{ error }}</p>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { runPipeline, cancelPipeline, resumePipeline, getPipelineStatus, getProgressLog, getDossier, continuePipeline, getPreflight } from '../api/research'
import { getGraphData } from '../api/graph'
import { locale, setLocale, L } from '../i18n'
import {
  liveLogRevision,
  mergeProgressLines,
  needsFinalProgressSnapshot
} from '../utils/liveProgress'
import StageTimeline from '../components/research/StageTimeline.vue'
import RunVitals from '../components/research/RunVitals.vue'
import ResearchConsole from '../components/research/ResearchConsole.vue'
import DossierViewer from '../components/research/DossierViewer.vue'
import SimulationView from '../components/research/SimulationView.vue'
import ForecastReport from '../components/research/ForecastReport.vue'
import PipelineHistory from '../components/research/PipelineHistory.vue'
import SettingsMenu from '../components/research/SettingsMenu.vue'
import ConfirmDialog from '../components/research/ConfirmDialog.vue'
import GraphPanel from '../components/GraphPanel.vue'

const ACTIVE_PIPELINE_KEY = 'drf_active_pipeline'
// One-time migration: earlier builds persisted under the old MiroFish key.
const LEGACY_PIPELINE_KEY = 'mirofish_active_pipeline'

// —— 输入 ——
const prompt = ref('')
const mode = ref('full')
const depth = ref('deep')
const depths = ['quick', 'standard', 'deep']
function depthLabel(d) {
  return { quick: L('快速', 'Quick'), standard: L('标准', 'Standard'), deep: L('深度', 'Deep') }[d] || d
}
const maxRounds = ref(null)
const starting = ref(false)
const error = ref('')
const showSettings = ref(false)

// —— T5.5: 高级（每次运行覆盖研究语言/模型）——
const showAdvanced = ref(false)
const researchLanguage = ref('')   // ''=默认；'auto'/'Chinese'/'English'
const researchModel = ref('')      // ''=默认；7 个 DeerFlow 模型之一
const DEERFLOW_MODELS = ['claude', 'codex', 'minimax', 'deepseek', 'qwen', 'glm', 'kimi']
const LANGUAGE_OPTIONS = [
  { v: '', zh: '默认', en: 'Default' },
  { v: 'Chinese', zh: '中文', en: 'Chinese' },
  { v: 'English', zh: '英文', en: 'English' },
  { v: 'auto', zh: '自动', en: 'Auto' }
]

// —— T5.6: 启动前就绪检查 ——
const preflightReady = ref(true)
const preflightErrors = ref([])
const preflightChecked = ref(false)
async function checkPreflight() {
  try {
    const res = await getPreflight(mode.value)
    preflightReady.value = !!(res && res.data && res.data.ready)
    preflightErrors.value = (res && res.data && res.data.errors) || []
  } catch (e) {
    // 检查接口本身失败：不阻塞用户，按就绪处理（真正的错误会在 /run 时拦截）
    preflightReady.value = true
    preflightErrors.value = []
  } finally {
    preflightChecked.value = true
  }
}

// —— T6.2: research_only → 继续完整管线 ——
const continuing = ref(false)
const canContinue = computed(
  () => !!pipelineId.value && status.value === 'completed' && mode.value === 'research_only'
)
async function continueToFull() {
  if (!pipelineId.value || continuing.value) return
  continuing.value = true
  error.value = ''
  try {
    const res = await continuePipeline(pipelineId.value)
    const id = (res && res.data && res.data.pipeline_id) || pipelineId.value
    pipelineId.value = id
    mode.value = 'full'
    status.value = 'running'
    // The previous terminal snapshot's `live` block would mislead under a
    // "running" header (its elapsed is age-since-created); wait for fresh data.
    liveVitals.value = null
    try { localStorage.setItem(ACTIVE_PIPELINE_KEY, id) } catch (e) { /* noop */ }
    startPolling()
  } catch (e) {
    error.value = e?.message || L('继续失败', 'Continue failed')
  } finally {
    continuing.value = false
  }
}

const EXAMPLES = [
  ['预判2035年前全球电动汽车市场的发展趋势', 'Forecast global EV market trends through 2035'],
  ['俄乌战争最可能在何时、以何种方式收场？', 'How and when will the Russia–Ukraine war end?'],
  ['特朗普第二任期下美欧关系将如何演变？', 'How will US–EU relations evolve under Trump II?']
]
const exampleList = computed(() => EXAMPLES.map(e => (locale.value === 'en' ? e[1] : e[0])))
function exShort(ex) { return ex.length > 24 ? ex.slice(0, 24) + '…' : ex }

// —— 运行态 ——
const pipelineId = ref('')
const status = ref('running')
const globalProgress = ref(0)
const currentStage = ref('')
const stages = ref({})
const graphId = ref('')
const simulationId = ref('')
const reportId = ref('')
const runPrompt = ref('')
const logLines = ref([])
const logSourceCount = ref(0)
const logHistoryHydrated = ref(false)
const logHistoryFinalized = ref(false)
const logInitialSnapshotAttempted = ref(false)
const logFinalSnapshotAttempts = ref(0)
const logHistoryLoading = ref(false)
const logHistoryError = ref('')
const dossier = ref(null)
const showHistory = ref(false)

// OBS-1/I-7: computed `live` block from the same status poll (may be absent —
// older servers, helper failure — and every field is individually nullable).
// runTiming carries the sibling timestamps RunVitals needs to derive a
// truthful final duration for terminal states.
const liveVitals = ref(null)
const runTiming = ref({ createdAt: '', updatedAt: '', resumedAt: '' })

// —— 标签 / 图谱 ——
const activeTab = ref('log')
const userPickedTab = ref(false)
const graphData = ref(null)
const graphLoading = ref(false)
const graphMax = ref(false)

// T5.3: 研究种子 actor 名（用于在图谱中高亮「研究确认 vs 模拟涌现」节点）
const seedActorNames = computed(() => {
  const a = dossier.value && dossier.value.actors
  const list = a && Array.isArray(a.actors) ? a.actors : []
  return list.map(x => x && x.name).filter(Boolean)
})

const logHistoryMeta = computed(() => ({
  sourceCount: logSourceCount.value,
  totalExact: logHistoryHydrated.value,
  finalized: logHistoryFinalized.value,
  loading: logHistoryLoading.value,
  error: logHistoryError.value
}))

let pollTimer = null
let dossierFetched = false
let pollFailures = 0
let connErrorShown = false
const POLL_FAILURE_THRESHOLD = 4 // 连续 4 次（约 10s）轮询失败才提示，容忍偶发抖动
const MAX_FINAL_SNAPSHOT_ATTEMPTS = 2

// FE-1: 自适应轮询 —— 状态未变化时把间隔从 2.5s 逐步拉到 12s，标签页隐藏时暂停，
// 重新可见时立即拉一次。降低长管线（数小时）空转时的后端/网络负载。
const POLL_MIN_MS = 2500
const POLL_MAX_MS = 12000
let pollActive = false          // 轮询是否处于活动状态（避免隐藏/终态后被定时器重新唤醒）
let pollDelay = POLL_MIN_MS     // 当前自适应间隔
let lastFingerprint = ''        // 上一次轮询观测到的状态指纹，用于判定"有无变化"
let visibilityHandler = null    // visibilitychange 监听器引用，便于卸载时移除
let pollInFlightGeneration = null // 同一 generation 不叠加；新管线不被旧慢请求阻塞
let pollGeneration = 0          // 丢弃上一条管线/上一轮轮询的迟到响应

// 计算一份轻量状态指纹。固定 400 行的 rolling tail 也必须看最新行内容；只看 length
// 会在控制台装满后误判为静止，把真正活跃的研究轮询退避到 12 秒。
function pollFingerprint() {
  const stageSig = Object.keys(stages.value || {})
    .map(k => `${k}:${stages.value[k] && stages.value[k].status}`)
    .join('|')
  return `${status.value}#${globalProgress.value}#${currentStage.value}#${stageSig}#${liveLogRevision(logLines.value)}`
}

function stageLabel(name) {
  return {
    research: L('深度研究', 'Research'), ontology: L('本体生成', 'Ontology'), graph: L('知识图谱', 'Graph'),
    prepare: L('环境搭建', 'Prepare'), run: L('群体模拟', 'Simulate'), report: L('预测报告', 'Forecast')
  }[name] || name
}

// T5.6: 就绪检查未通过时禁用启动（preflightChecked 前不阻塞，避免初次加载抖动）
const canStart = computed(() =>
  prompt.value.trim().length > 0 && (!preflightChecked.value || preflightReady.value)
)
const statusTitle = computed(() => {
  if (status.value === 'completed') return mode.value === 'research_only' ? L('研究完成', 'Research complete') : L('推演完成 · 预测就绪', 'Done · forecast ready')
  if (status.value === 'failed') return L('运行失败', 'Run failed')
  if (status.value === 'cancelled') return L('已取消', 'Cancelled')
  return currentStage.value ? `${L('运行中','Running')} · ${stageLabel(currentStage.value)}` : L('运行中…', 'Running…')
})

const tabs = computed(() => {
  const researchDone = (dossier.value && dossier.value.has_report) || (stages.value.research && stages.value.research.status === 'completed')
  const actorCount = dossier.value && dossier.value.actors && dossier.value.actors.actors ? dossier.value.actors.actors.length : 0
  return [
    { key: 'log', label: L('实时日志', 'Live log'), enabled: true },
    { key: 'dossier', label: L('研究档案', 'Dossier'), enabled: !!researchDone, badge: actorCount || '' },
    { key: 'graph', label: L('知识图谱', 'Graph'), enabled: !!graphId.value },
    { key: 'sim', label: L('群体模拟', 'Simulation'), enabled: !!simulationId.value },
    { key: 'report', label: L('预测报告', 'Forecast'), enabled: !!reportId.value }
  ]
})

function toggleLocale() { setLocale(locale.value === 'en' ? 'zh' : 'en') }
function onProviderChanged() { /* provider applies to new runs; nothing to refresh here */ }

function pickTab(key) {
  const t = tabs.value.find(x => x.key === key)
  if (!t || !t.enabled) return
  userPickedTab.value = true
  activeTab.value = key
  if (key === 'graph' && !graphData.value && graphId.value) fetchGraph()
}

watch([() => reportId.value, () => (dossier.value && dossier.value.has_report)], () => {
  if (userPickedTab.value) return
  if (reportId.value) activeTab.value = 'report'
  else if (dossier.value && dossier.value.has_report) activeTab.value = 'dossier'
})

async function start() {
  if (!canStart.value || starting.value) return
  starting.value = true
  error.value = ''
  try {
    const res = await runPipeline({
      prompt: prompt.value.trim(),
      mode: mode.value,
      depth: depth.value,
      max_rounds: maxRounds.value || undefined,
      language: researchLanguage.value || undefined,  // T5.5
      model: researchModel.value || undefined          // T5.5
    })
    beginPipeline(res.data.pipeline_id, prompt.value.trim())
  } catch (e) {
    error.value = e?.message || L('启动失败', 'Failed to start')
  } finally {
    starting.value = false
  }
}

function beginPipeline(id, initialPrompt = '') {
  pipelineId.value = id
  runPrompt.value = String(initialPrompt || '').trim()
  logLines.value = []
  logSourceCount.value = 0
  logHistoryHydrated.value = false
  logHistoryFinalized.value = false
  logInitialSnapshotAttempted.value = false
  logFinalSnapshotAttempts.value = 0
  logHistoryLoading.value = false
  logHistoryError.value = ''
  try { localStorage.setItem(ACTIVE_PIPELINE_KEY, id) } catch (e) { /* noop */ }
  startPolling()
}

function applyProgressLogResponse(response, { finalized = false } = {}) {
  const data = response && response.data
  if (!data || !Array.isArray(data.lines)) return false
  const exact = data.scope === 'full' && data.total_exact === true && data.truncated === false
  if (exact) {
    logLines.value = data.lines.map(line => String(line ?? ''))
    logHistoryHydrated.value = true
    logHistoryFinalized.value = !!finalized
    logHistoryError.value = ''
  } else {
    logLines.value = mergeProgressLines(logLines.value, data.lines)
  }
  logSourceCount.value = Math.max(logSourceCount.value, Number(data.source_count) || 0)
  return exact
}

async function requestProgressLog(id, scope) {
  if (!id) return null
  if (scope === 'full') logHistoryLoading.value = true
  try {
    return await getProgressLog(id, 500, scope)
  } catch (e) {
    if (scope === 'full') {
      logHistoryError.value = e?.message || L('全部记录事件载入失败', 'Failed to load recorded history')
    }
    return null
  } finally {
    if (scope === 'full') logHistoryLoading.value = false
  }
}

async function refreshFullResearchLog() {
  const id = pipelineId.value
  if (!id || logHistoryLoading.value) return
  // A snapshot may be labeled final only when the terminal boundary was
  // already observed before this request began. If status crosses while the
  // request is in flight, the polling path still owes a distinct final read.
  const researchStatusBefore = stages.value.research && stages.value.research.status
  const terminalBeforeRequest = needsFinalProgressSnapshot(
    status.value, researchStatusBefore, false
  )
  const response = await requestProgressLog(id, 'full')
  if (id !== pipelineId.value) return
  logInitialSnapshotAttempted.value = true
  if (terminalBeforeRequest) {
    logFinalSnapshotAttempts.value = Math.max(1, logFinalSnapshotAttempts.value)
  }
  applyProgressLogResponse(response, { finalized: terminalBeforeRequest })
}

async function finalizeResearchLog(id, generation) {
  while (logFinalSnapshotAttempts.value < MAX_FINAL_SNAPSHOT_ATTEMPTS) {
    logFinalSnapshotAttempts.value += 1
    const response = await requestProgressLog(id, 'full')
    if (!pollActive || generation !== pollGeneration || id !== pipelineId.value) return false
    if (applyProgressLogResponse(response, { finalized: true })) return true
  }
  return false
}

const cancelling = ref(false)
const resuming = ref(false)
const canResume = computed(() => !!pipelineId.value && (status.value === 'failed' || status.value === 'cancelled'))
const confirmDlg = ref(null)
async function cancel() {
  if (!pipelineId.value || cancelling.value) return
  const ok = confirmDlg.value && await confirmDlg.value.open({
    title: L('取消推演', 'Cancel run'),
    message: L('确定取消本次推演？正在运行的研究/模拟将被终止。', 'Cancel this run? The in-flight research/simulation will be stopped.'),
    confirmLabel: L('确定取消', 'Yes, cancel'),
    cancelLabel: L('继续运行', 'Keep running'),
    danger: true
  })
  if (!ok) return
  cancelling.value = true
  try {
    await cancelPipeline(pipelineId.value)
    // 状态翻转由轮询接管（cancelled 是终态）
  } catch (e) {
    error.value = e?.message || L('取消失败', 'Cancel failed')
  } finally {
    cancelling.value = false
  }
}

async function resume() {
  if (!pipelineId.value || resuming.value) return
  resuming.value = true
  error.value = ''
  try {
    const res = await resumePipeline(pipelineId.value)
    const id = (res && res.data && res.data.pipeline_id) || pipelineId.value
    pipelineId.value = id
    status.value = 'running'
    liveVitals.value = null  // same reasoning as continueToFull: await fresh live data
    // A failed/cancelled terminal snapshot is exact only for the pre-resume
    // stream. The resumed producer may append new research events.
    logHistoryFinalized.value = false
    logFinalSnapshotAttempts.value = 0
    try { localStorage.setItem(ACTIVE_PIPELINE_KEY, id) } catch (e) { /* noop */ }
    startPolling()
  } catch (e) {
    error.value = e?.message || L('恢复失败', 'Resume failed')
  } finally {
    resuming.value = false
  }
}

// FE-1: 用自重排的 setTimeout 取代固定 setInterval，使间隔可随"有无进展"自适应。
function startPolling() {
  stopPolling()
  pollActive = true
  pollGeneration += 1
  pollDelay = POLL_MIN_MS
  lastFingerprint = ''
  if (!visibilityHandler) {
    visibilityHandler = () => {
      if (!pollActive) return
      if (!document.hidden) {
        // 重新可见：复位为快节奏并立即拉一次，避免回到页面看到陈旧状态。
        pollDelay = POLL_MIN_MS
        scheduleNext(0)
      }
    }
    document.addEventListener('visibilitychange', visibilityHandler)
  }
  scheduleNext(0)
}

function stopPolling() {
  pollActive = false
  pollGeneration += 1
  if (pollTimer) { clearTimeout(pollTimer); pollTimer = null }
  if (visibilityHandler) {
    document.removeEventListener('visibilitychange', visibilityHandler)
    visibilityHandler = null
  }
}

// 安排下一次轮询；隐藏标签页时不发起网络请求（暂停），仅保留一个慢心跳兜底，
// 防止极少数情况下 visibilitychange 事件丢失导致永不恢复。
function scheduleNext(delay) {
  if (pollTimer) { clearTimeout(pollTimer); pollTimer = null }
  if (!pollActive) return
  const generation = pollGeneration
  pollTimer = setTimeout(() => runPoll(generation), delay)
}

async function runPoll(generation) {
  if (!pollActive || generation !== pollGeneration) return
  if (typeof document !== 'undefined' && document.hidden) {
    // 暂停：标签页不可见时跳过实际请求，留一个 POLL_MAX_MS 的兜底心跳。
    scheduleNext(POLL_MAX_MS)
    return
  }
  if (pollInFlightGeneration === generation) {
    scheduleNext(POLL_MIN_MS)
    return
  }
  pollInFlightGeneration = generation
  try {
    await poll(generation)
  } finally {
    // 新 generation 可能已在旧请求返回前取得 ownership；旧请求不得清掉它。
    if (pollInFlightGeneration === generation) pollInFlightGeneration = null
  }
  if (!pollActive || generation !== pollGeneration) return
  scheduleNext(pollDelay)
}

async function poll(generation) {
  const requestedPipelineId = pipelineId.value
  if (!requestedPipelineId) return
  try {
    // 首次打开做一次精确全量 hydration；随后只拉有界 tail 并累积，避免每 2.5s
    // 对数小时日志做 O(file) 扫描。研究完成边界再做一次精确快照，弥合任何突发窗口。
    const researchRunning = !(stages.value.research && stages.value.research.status === 'completed') || logLines.value.length === 0
    const progressScope = !logHistoryHydrated.value && !logInitialSnapshotAttempted.value
      ? 'full'
      : (researchRunning ? 'tail' : null)
    if (progressScope === 'full') logInitialSnapshotAttempted.value = true
    const [st, lg] = await Promise.all([
      getPipelineStatus(requestedPipelineId),
      progressScope
        ? requestProgressLog(requestedPipelineId, progressScope)
        : Promise.resolve(null)
    ])
    if (!pollActive || generation !== pollGeneration || requestedPipelineId !== pipelineId.value) return
    pollFailures = 0
    if (connErrorShown) { error.value = ''; connErrorShown = false }
    const d = st.data
    status.value = d.status
    globalProgress.value = d.global_progress || 0
    currentStage.value = d.current_stage || ''
    stages.value = d.stages || {}
    if (d.mode) mode.value = d.mode
    if (typeof d.prompt === 'string') runPrompt.value = d.prompt
    // Per-response truth: an absent `live` block renders no vitals strip.
    liveVitals.value = (d.live && typeof d.live === 'object' && !Array.isArray(d.live)) ? d.live : null
    runTiming.value = {
      createdAt: d.created_at || '',
      updatedAt: d.updated_at || '',
      resumedAt: (d.options && d.options.resumed_at) || ''
    }
    if (d.graph_id) graphId.value = d.graph_id
    if (d.simulation_id) simulationId.value = d.simulation_id
    if (d.report_id) reportId.value = d.report_id
    const researchStatus = stages.value.research && stages.value.research.status
    const researchDone = researchStatus === 'completed'
    // An initial full hydration is exact only at the instant it was read. Never
    // promote it to "final" merely because the concurrently fetched status has
    // crossed a boundary; always take one distinct post-observation snapshot.
    applyProgressLogResponse(lg, { finalized: false })
    if (needsFinalProgressSnapshot(status.value, researchStatus, logHistoryFinalized.value)) {
      await finalizeResearchLog(requestedPipelineId, generation)
    }

    // FE-1: 有进展则复位为快节奏，连续无变化则把间隔向 POLL_MAX_MS 拉升（~1.5x 阶梯）。
    const fp = pollFingerprint()
    if (fp !== lastFingerprint) {
      pollDelay = POLL_MIN_MS
    } else {
      pollDelay = Math.min(POLL_MAX_MS, Math.round(pollDelay * 1.5))
    }
    lastFingerprint = fp

    if (researchDone && !dossierFetched) {
      dossierFetched = true
      try {
        const dossierResult = await getDossier(requestedPipelineId)
        if (pollActive && generation === pollGeneration && requestedPipelineId === pipelineId.value) {
          dossier.value = dossierResult.data
        }
      } catch (e) { /* noop */ }
    }

    if (status.value === 'completed' || status.value === 'failed' || status.value === 'cancelled') {
      stopPolling()
      try { localStorage.removeItem(ACTIVE_PIPELINE_KEY) } catch (e) { /* noop */ }
      if (!dossier.value) {
        try {
          const dossierResult = await getDossier(requestedPipelineId)
          if (requestedPipelineId === pipelineId.value) dossier.value = dossierResult.data
        } catch (e) { /* noop */ }
      }
      if (status.value === 'failed') {
        const failed = Object.values(stages.value).find(s => s.status === 'failed')
        error.value = (failed && failed.error) || d.error || L('运行失败', 'Run failed')
      }
    }
  } catch (e) {
    if (!pollActive || generation !== pollGeneration || requestedPipelineId !== pipelineId.value) return
    if (e && e.response && e.response.status === 404) {
      stopPolling()
      try { localStorage.removeItem(ACTIVE_PIPELINE_KEY) } catch (_) { /* noop */ }
      status.value = 'failed'
      error.value = L('该管线不存在或已被清理', 'This pipeline no longer exists')
      return
    }
    // 非 404 失败（后端崩溃/网络断开）不再静默吞掉：连续多次失败时提示用户，
    // 但保持轮询——后端恢复后下一次成功轮询会自动清掉提示。
    pollFailures += 1
    if (pollFailures >= POLL_FAILURE_THRESHOLD) {
      error.value = L('与后端失去连接（持续重试中）：', 'Lost connection to the backend (retrying): ') + (e?.message || '')
      connErrorShown = true
    }
  }
}

async function fetchGraph(force = false) {
  if (!graphId.value) return
  if (graphData.value && !force) return
  graphLoading.value = true
  try {
    const res = await getGraphData(graphId.value)
    graphData.value = res.data || { nodes: [], edges: [] }
  } catch (e) {
    error.value = L('图谱加载失败：', 'Graph load failed: ') + (e?.message || '')
  } finally {
    graphLoading.value = false
  }
}

function selectPipeline(id) {
  if (!id || id === pipelineId.value) { showHistory.value = false; return }
  resetState()
  showHistory.value = false
  beginPipeline(id)
}

// —— 管线 ID：截断显示 + 点击复制完整 ID ——
const pidCopied = ref(false)
let pidCopiedTimer = null
const shortPipelineId = computed(() => (pipelineId.value ? pipelineId.value.slice(0, 8) : ''))
async function copyPipelineId() {
  const text = pipelineId.value
  if (!text) return
  let copied = false
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text)
      copied = true
    }
  } catch (e) { copied = false }
  if (!copied) {
    // 非安全上下文（如 http://LAN）没有 navigator.clipboard，回退到 execCommand。
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.setAttribute('readonly', '')
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      copied = document.execCommand('copy')
      document.body.removeChild(ta)
    } catch (e) { copied = false }
  }
  if (copied) {
    pidCopied.value = true
    if (pidCopiedTimer) clearTimeout(pidCopiedTimer)
    pidCopiedTimer = setTimeout(() => { pidCopied.value = false }, 1600)
  }
}

function resetState() {
  stopPolling()
  status.value = 'running'; globalProgress.value = 0; currentStage.value = ''
  stages.value = {}; graphId.value = ''; simulationId.value = ''; reportId.value = ''
  runPrompt.value = ''; logLines.value = []; logSourceCount.value = 0
  liveVitals.value = null; runTiming.value = { createdAt: '', updatedAt: '', resumedAt: '' }
  logHistoryHydrated.value = false; logHistoryFinalized.value = false
  logInitialSnapshotAttempted.value = false; logFinalSnapshotAttempts.value = 0
  logHistoryLoading.value = false; logHistoryError.value = ''
  dossier.value = null; dossierFetched = false
  graphData.value = null; graphLoading.value = false; graphMax.value = false
  activeTab.value = 'log'; userPickedTab.value = false; error.value = ''
}
function reset() {
  resetState()
  pipelineId.value = ''
  try { localStorage.removeItem(ACTIVE_PIPELINE_KEY) } catch (e) { /* noop */ }
}

/** 历史抽屉里删掉的运行若正是当前查看的运行，回到输入页（避免对已删 id 继续轮询/展示）。 */
function onRunDeleted(id) {
  if (id && id === pipelineId.value) reset()
}

onMounted(() => {
  let saved = null
  try {
    saved = localStorage.getItem(ACTIVE_PIPELINE_KEY)
    if (!saved) {
      // 一次性迁移旧 MiroFish 键：读旧写新，随后删除旧键。
      const legacy = localStorage.getItem(LEGACY_PIPELINE_KEY)
      if (legacy) {
        saved = legacy
        localStorage.setItem(ACTIVE_PIPELINE_KEY, legacy)
        localStorage.removeItem(LEGACY_PIPELINE_KEY)
      }
    }
  } catch (e) { saved = null }
  if (saved) beginPipeline(saved)
  else checkPreflight()  // T5.6: 落地即检查就绪状态
})
// T5.6: 切换模式时重新检查（research_only 跳过图谱/报告 LLM 检查）
watch(mode, () => { if (!pipelineId.value) checkPreflight() })
onUnmounted(() => {
  stopPolling()
  if (pidCopiedTimer) { clearTimeout(pidCopiedTimer); pidCopiedTimer = null }
})
</script>

<style scoped>
.research-container {
  min-height: 100vh; background: #fff;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
  color: #000; --orange: #FF4500; --mono: 'JetBrains Mono', monospace; --border: #E5E5E5;
}
.navbar { min-height: 60px; background:#000; color:#fff; display:flex; justify-content:space-between; align-items:center; gap:18px; padding:0 40px; position:sticky; top:0; z-index:20; }
.nav-brand { font-family: var(--mono); font-weight:800; letter-spacing:0; font-size:1.05rem; flex:0 1 auto; min-width:0; white-space:nowrap; }
.brand-accent { color: var(--orange); }
.nav-links { display:flex; align-items:center; justify-content:flex-end; gap:10px; min-width:0; flex:1 1 auto; }
.nav-tag { font-family: var(--mono); font-size:.74rem; color:#bbb; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.nav-icon-btn { background:transparent; border:1px solid #444; border-radius:var(--radius, 2px); color:#ddd; font-family:var(--mono); font-size:.74rem; min-width:30px; width:30px; height:30px; cursor:pointer; display:flex; align-items:center; justify-content:center; transition:border-color var(--dur-1, 120ms) var(--ease, ease), color var(--dur-1, 120ms) var(--ease, ease), background var(--dur-1, 120ms) var(--ease, ease); }
.nav-icon-btn:hover { border-color:var(--orange); color:#fff; background:rgba(255,69,0,.12); }
.nav-hist-btn { background:transparent; border:1px solid #444; border-radius:var(--radius, 2px); color:#ddd; font-family:var(--mono); font-size:.74rem; padding:6px 12px; cursor:pointer; display:inline-flex; align-items:center; gap:7px; transition:border-color var(--dur-1, 120ms) var(--ease, ease), color var(--dur-1, 120ms) var(--ease, ease), background var(--dur-1, 120ms) var(--ease, ease); }
.nav-hist-btn:hover { border-color:var(--orange); color:#fff; background:rgba(255,69,0,.12); }

.main-content { max-width:1480px; margin:0 auto; padding:40px; }

.history-drawer { position:fixed; top:0; right:0; width:380px; max-width:90vw; height:100vh; background:#fff; border-left:1px solid var(--border); z-index:40; box-shadow:var(--shadow-lg, -8px 0 32px rgba(0,0,0,.12)); display:flex; flex-direction:column; }
.drawer-head { display:flex; justify-content:space-between; align-items:center; padding:18px 20px; border-bottom:1px solid var(--border); font-family:var(--mono); font-size:.85rem; height:60px; }
.drawer-close { background:none; border:none; font-size:1.1rem; cursor:pointer; color:var(--color-muted, #666); transition:color var(--dur-1, 120ms) var(--ease, ease); }
.drawer-close:hover { color:var(--color-ink, #000); }
.drawer-scrim { position:fixed; inset:0; background:rgba(0,0,0,.25); z-index:30; }
.drawer-enter-active,.drawer-leave-active { transition: transform var(--dur-3, 250ms) var(--ease, ease); }
.drawer-enter-from,.drawer-leave-to { transform: translateX(100%); }
.fade-enter-active,.fade-leave-active { transition: opacity var(--dur-3, 250ms) var(--ease, ease); }
.fade-enter-from,.fade-leave-to { opacity: 0; }

.tag-row { display:flex; gap:15px; align-items:center; margin-bottom:20px; font-family:var(--mono); font-size:.8rem; }
.orange-tag { background:var(--orange); color:#fff; padding:4px 10px; font-weight:700; letter-spacing:1px; font-size:.75rem; }
.version-text { color:#999; }
.main-title { font-size:clamp(2rem, 4.5vw, 3.25rem); line-height:1.2; font-weight:500; letter-spacing:0; margin:0 0 22px; }
.gradient-text { background:linear-gradient(90deg,#000,#FF4500); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.lead { color:#666; line-height:1.85; max-width:820px; margin-bottom:34px; }
.console-box { border:1px solid var(--color-border, #E5E5E5); border-radius:var(--radius, 2px); padding:8px; box-shadow:var(--shadow-sm, 0 1px 3px rgba(10,10,10,.06)); background:#fff; }
.console-section { padding:20px; }
.console-section.btn-section { padding-top:0; }
.console-header { display:flex; justify-content:space-between; margin-bottom:12px; font-family:var(--mono); font-size:.75rem; color:#666; }
.input-wrapper { border:1px solid #DDD; background:#FAFAFA; border-radius:var(--radius, 2px); transition:border-color var(--dur-2, 180ms) var(--ease, ease), background var(--dur-2, 180ms) var(--ease, ease); }
.input-wrapper:focus-within { border-color:var(--orange); background:#fff; }
.code-input { width:100%; border:none; background:transparent; padding:18px; font-family:var(--mono); font-size:.9rem; line-height:1.6; resize:vertical; outline:none; min-height:130px; }
.examples { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:12px; }
.ex-label { font-family:var(--mono); font-size:.72rem; color:#999; }
.ex-chip { border:1px solid var(--border); border-radius:var(--radius-pill, 999px); background:#fff; font-size:.74rem; padding:5px 12px; cursor:pointer; color:#444; font-family:'Noto Sans SC',sans-serif; transition:border-color var(--dur-1, 120ms) var(--ease, ease), color var(--dur-1, 120ms) var(--ease, ease), background var(--dur-1, 120ms) var(--ease, ease); }
.ex-chip:hover:not(:disabled) { border-color:var(--orange); color:var(--orange); background:var(--color-accent-soft, #FFF6F2); }
.ex-chip:disabled { color:#bbb; cursor:not-allowed; }
.console-divider { display:flex; align-items:center; margin:6px 0; }
.console-divider::before,.console-divider::after { content:''; flex:1; height:1px; background:#EEE; }
.console-divider span { padding:0 15px; font-family:var(--mono); font-size:.7rem; color:#BBB; letter-spacing:1px; }
.params-row { display:flex; gap:32px; flex-wrap:wrap; }
.param label { display:block; font-family:var(--mono); font-size:.72rem; color:#888; margin-bottom:8px; }
.seg { display:flex; border:1px solid #DDD; border-radius:var(--radius, 2px); overflow:hidden; }
.seg button { background:#fff; border:none; border-right:1px solid #eee; padding:8px 14px; font-family:var(--mono); font-size:.8rem; cursor:pointer; color:#555; transition:background var(--dur-1, 120ms) var(--ease, ease), color var(--dur-1, 120ms) var(--ease, ease); }
.seg button:last-child { border-right:none; }
.seg button:hover:not(.active):not(:disabled) { background:var(--color-soft, #FAFAFA); color:#000; }
.seg button.active { background:#000; color:#fff; }
.num-input { border:1px solid #DDD; border-radius:var(--radius, 2px); padding:8px 10px; font-family:var(--mono); font-size:.85rem; width:200px; outline:none; transition:border-color var(--dur-2, 180ms) var(--ease, ease); }
.num-input:focus { border-color:var(--orange); }
/* T5.5 高级 */
.adv-toggle { font-family:var(--mono); font-size:.78rem; color:#666; cursor:pointer; padding:10px 0 4px; user-select:none; }
.adv-toggle:hover { color:var(--orange); }
.adv-caret { color:var(--orange); margin-right:6px; }
.adv-row { margin-top:6px; }
.adv-select { border:1px solid #DDD; border-radius:var(--radius, 2px); padding:8px 10px; font-family:var(--mono); font-size:.85rem; width:200px; outline:none; background:#fff; cursor:pointer; transition:border-color var(--dur-2, 180ms) var(--ease, ease); }
.adv-select:focus { border-color:var(--orange); }
/* T5.6 就绪横幅 */
.preflight-banner { margin-top:14px; padding:10px 14px; font-family:var(--mono); font-size:.8rem; border-radius:var(--radius, 2px); }
.preflight-banner.ok-banner { color:var(--color-ok, #16A34A); background:var(--color-ok-soft, #F0FDF4); border:1px solid #b7ebc6; }
.preflight-banner.err-banner { color:var(--color-err, #B91C1C); background:var(--color-err-soft, #FEF2F2); border:1px solid #f0bcbc; }
.pf-title { font-weight:700; margin-bottom:6px; }
.pf-list { margin:0; padding-left:18px; }
.pf-list li { margin:3px 0; line-height:1.5; }
.start-engine-btn { width:100%; background:#000; color:#fff; border:none; border-radius:var(--radius, 2px); padding:18px; font-family:var(--mono); font-weight:700; font-size:1.05rem; display:flex; justify-content:space-between; align-items:center; cursor:pointer; transition:background var(--dur-2, 180ms) var(--ease, ease), transform var(--dur-2, 180ms) var(--ease, ease), box-shadow var(--dur-2, 180ms) var(--ease, ease); letter-spacing:1px; }
.start-engine-btn:hover:not(:disabled) { background:var(--orange); transform:translateY(-2px); box-shadow:var(--shadow-md, 0 2px 10px rgba(10,10,10,.08)); }
.start-engine-btn:active:not(:disabled) { transform:translateY(0); box-shadow:none; }
.start-engine-btn:disabled { background:#E5E5E5; color:#999; cursor:not-allowed; }
.err { color:var(--orange); font-family:var(--mono); font-size:.8rem; margin-top:12px; }
.run-err { margin-top:18px; }

.run-header { display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:20px; }
.console-label { font-family:var(--mono); font-size:.72rem; color:#999; }
.pid-chip { background:none; border:1px dashed #ccc; border-radius:var(--radius, 2px); color:#777; font-family:var(--mono); font-size:.72rem; padding:1px 7px; cursor:pointer; display:inline-flex; align-items:center; gap:6px; transition:border-color var(--dur-1, 120ms) var(--ease, ease), color var(--dur-1, 120ms) var(--ease, ease); }
.pid-chip:hover { border-color:var(--orange); color:#000; }
.pid-copied { color:var(--color-ok, #16A34A); font-weight:700; }
.run-title { font-size:1.7rem; font-weight:500; margin:6px 0 0; letter-spacing:-0.01em; }
.run-actions { display:flex; gap:12px; }
.primary-btn { background:var(--orange); color:#fff; border:none; border-radius:var(--radius, 2px); padding:12px 18px; font-family:var(--mono); font-weight:700; cursor:pointer; transition:opacity var(--dur-1, 120ms) var(--ease, ease), transform var(--dur-1, 120ms) var(--ease, ease); }
.primary-btn:hover { opacity:.9; transform:translateY(-1px); }
.ghost-btn { background:#fff; color:#000; border:1px solid #DDD; border-radius:var(--radius, 2px); padding:10px 16px; font-family:var(--mono); font-size:.82rem; cursor:pointer; transition:border-color var(--dur-1, 120ms) var(--ease, ease), color var(--dur-1, 120ms) var(--ease, ease), background var(--dur-1, 120ms) var(--ease, ease); }
.ghost-btn:hover { border-color:var(--orange); background:var(--color-soft, #FAFAFA); }
.cancel-btn { color:var(--orange); border-color:#F3C4B2; }
.cancel-btn:disabled { color:#bbb; border-color:#E5E5E5; cursor:not-allowed; }
.resume-btn { color:#166534; border-color:#B7E4C7; }
.resume-btn:hover { border-color:#16a34a; }
.resume-btn:disabled { color:#bbb; border-color:#E5E5E5; cursor:not-allowed; }
.run-prompt-card { border:1px solid var(--border); border-left:3px solid var(--orange); background:#FAFAFA; padding:14px 18px; margin:0 0 22px; }
.run-prompt-label { display:block; margin-bottom:6px; color:var(--orange); font-family:var(--mono); font-size:.66rem; font-weight:700; letter-spacing:1px; text-transform:uppercase; }
.run-prompt-card p { margin:0; color:#222; font-size:.94rem; line-height:1.65; white-space:pre-wrap; overflow-wrap:anywhere; }

.run-layout { display:grid; grid-template-columns:330px 1fr; gap:24px; align-items:start; }
.rail { position:sticky; top:84px; }
.workspace { min-width:0; }
.tabbar { display:flex; gap:4px; border-bottom:1px solid var(--border); flex-wrap:wrap; }
.tab { background:#fff; border:1px solid var(--border); border-bottom:none; border-radius:var(--radius, 2px) var(--radius, 2px) 0 0; padding:11px 18px; font-family:var(--mono); font-size:.8rem; cursor:pointer; color:#777; position:relative; top:1px; display:flex; align-items:center; gap:7px; transition:color var(--dur-1, 120ms) var(--ease, ease), background var(--dur-1, 120ms) var(--ease, ease); }
.tab:hover:not(.active):not(.disabled) { color:#000; background:var(--color-soft, #FAFAFA); }
.tab.active { color:#000; border-color:var(--border); border-bottom:2px solid var(--orange); background:#fff; font-weight:700; }
.tab.disabled { color:#ccc; cursor:not-allowed; background:#FAFAFA; }
.tab-badge { background:var(--orange); color:#fff; font-size:.62rem; padding:1px 7px; border-radius:var(--radius-pill, 999px); }
.tab-body { border:1px solid var(--border); border-top:none; min-height:min(560px, 70vh); background:#fff; }
.graph-wrap { height:600px; }
.graph-wrap.max { height:calc(100vh - 220px); }
.lazy-empty { height:100%; display:flex; flex-direction:column; gap:14px; align-items:center; justify-content:center; color:#999; font-family:var(--mono); font-size:.85rem; padding:40px; text-align:center; }
.lazy-icon { font-size:24px; color:var(--orange); line-height:1; }
.lazy-spinner { width:22px; height:22px; border:2px solid var(--border); border-top-color:var(--orange); border-radius:50%; animation:rv-spin .8s linear infinite; }
@keyframes rv-spin { to { transform:rotate(360deg); } }

@media (max-width: 1080px) {
  .run-layout { grid-template-columns:1fr; }
  .rail { position:static; }
}

@media (max-width: 640px) {
  .navbar { padding:10px 16px; align-items:flex-start; }
  .nav-brand { font-size:.95rem; line-height:30px; }
  .nav-links { flex:0 0 auto; gap:8px; }
  .nav-tag { display:none; }
  .nav-hist-btn { width:30px; height:30px; padding:0; justify-content:center; }
  .nav-hist-label { display:none; }
  .main-content { padding:28px 16px; }
  .lead { font-size:.95rem; line-height:1.75; }
  .console-section { padding:16px; }
  .params-row { gap:18px; }
  .param, .num-input { width:100%; }
  .seg { width:100%; }
  .seg button { flex:1; min-width:0; padding:9px 10px; }
  .run-header { align-items:flex-start; flex-direction:column; gap:14px; }
  .run-actions { flex-wrap:wrap; }
}

/* Print: the visible tab's document (dossier / report) prints as a clean page;
   navigation chrome, rails and controls are suppressed. */
@media print {
  .navbar, .history-drawer, .drawer-scrim, .rail, .tabbar,
  .run-actions, .pid-chip, .run-vitals, .run-err { display:none !important; }
  .research-container { background:#fff; }
  .main-content { max-width:none; padding:0; }
  .run-layout { display:block; }
  .tab-body { border:none; min-height:0; }
  .run-prompt-card { border:1px solid #ccc; border-left:3px solid #000; background:#fff; }
}
</style>
