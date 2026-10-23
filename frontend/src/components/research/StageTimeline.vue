<template>
  <div class="stage-timeline">
    <!-- ============ HEADER: global progress ============ -->
    <div class="st-header">
      <div class="st-header-top">
        <span class="st-eyebrow mono">{{ L('◇ 管线进度 · PIPELINE', '◇ Pipeline progress · PIPELINE') }}</span>
        <span class="st-mode mono">{{ modeLabel }}</span>
      </div>

      <div class="st-progress-block">
        <div class="st-progress-number">
          <span class="st-progress-value">{{ safeGlobalProgress }}</span>
          <span class="st-progress-unit">%</span>
        </div>
        <div class="st-progress-side">
          <div class="st-progress-bar">
            <div
              class="st-progress-fill"
              :style="{ width: safeGlobalProgress + '%' }"
            ></div>
          </div>
          <div class="st-current-line">
            <span class="st-current-dot" :class="'dot--' + currentStageStatus"></span>
            <span class="st-current-label">{{ currentStageLabel }}</span>
            <span class="st-current-sub mono" v-if="currentStageStatus">{{ statusText(currentStageStatus) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ============ VERTICAL TIMELINE ============ -->
    <div class="st-timeline" v-if="orderedStages.length">
      <div
        v-for="(s, idx) in orderedStages"
        :key="s.key"
        class="st-row"
        :class="['row--' + s.status, { 'is-current': s.key === currentStage }]"
      >
        <!-- Left connector + dot -->
        <div class="st-connector">
          <div
            class="st-line st-line--top"
            :class="{ 'is-hidden': idx === 0 }"
          ></div>
          <div class="st-dot" :class="'dot--' + s.status">
            <span v-if="s.status === 'completed'" class="st-dot-glyph">✓</span>
            <span v-else-if="s.status === 'failed'" class="st-dot-glyph">✕</span>
          </div>
          <div
            class="st-line st-line--bottom"
            :class="{ 'is-hidden': idx === orderedStages.length - 1 }"
          ></div>
        </div>

        <!-- Stage content -->
        <div class="st-content">
          <div class="st-content-head">
            <span class="st-index mono">{{ padNum(idx + 1) }}</span>
            <span class="st-label">{{ s.label }}</span>
            <span class="st-status-pill mono" :class="'pill--' + s.status">
              {{ statusText(s.status) }}
            </span>
          </div>

          <div class="st-desc">{{ s.desc }}</div>

          <!-- RUNNING: sub-progress + message -->
          <div class="st-running-block" v-if="s.status === 'running'">
            <div class="st-sub-bar">
              <div
                class="st-sub-fill"
                :style="{ width: clampPct(s.progress) + '%' }"
              ></div>
            </div>
            <div class="st-sub-meta">
              <span class="st-sub-pct mono">{{ clampPct(s.progress) }}%</span>
              <span class="st-sub-msg" v-if="s.message">{{ truncate(s.message, 80) }}</span>
            </div>
          </div>

          <!-- COMPLETED: 完成 + elapsed -->
          <div class="st-done-block" v-else-if="s.status === 'completed'">
            <span class="st-done-tag">{{ L('完成', 'Done') }}</span>
            <span class="st-done-elapsed mono" v-if="elapsed(s) !== null">
              · {{ elapsed(s) }}s
            </span>
            <span class="st-done-msg" v-if="s.message">{{ truncate(s.message, 60) }}</span>
          </div>

          <!-- FAILED: error in red -->
          <div class="st-fail-block" v-else-if="s.status === 'failed'">
            <span class="st-fail-msg">{{ s.error || s.message || L('该阶段执行失败', 'This stage failed') }}</span>
          </div>

          <!-- PENDING: muted waiting -->
          <div class="st-pending-block" v-else>
            <span class="st-pending-msg">{{ L('等待中…', 'Waiting…') }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div class="st-empty" v-else>
      <span class="st-empty-mark">◇</span>
      <span class="st-empty-text">{{ L('暂无管线阶段', 'No pipeline stages yet') }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { L } from '../../i18n'

/**
 * StageTimeline — purely presentational vertical pipeline timeline.
 * Props-driven and reactive; performs no API calls and emits nothing.
 * Every array/object access is guarded so the component never throws on
 * missing, null, or malformed props.
 */
const props = defineProps({
  // { stageName: { status, progress, message, started_at, finished_at, error } }
  stages: {
    type: Object,
    default: () => ({})
  },
  currentStage: {
    type: String,
    default: ''
  },
  mode: {
    type: String,
    default: 'full'
  },
  globalProgress: {
    type: Number,
    default: 0
  }
})

// Canonical stage order per mode.
const STAGE_ORDER_FULL = ['research', 'ontology', 'graph', 'prepare', 'run', 'report']
const STAGE_ORDER_RESEARCH = ['research']

// Chinese labels + one-line English/desc subtitles.
function stageMeta(key) {
  switch (key) {
    case 'research': return { label: L('深度研究 · DeerFlow', 'Deep research · DeerFlow'), desc: L('联网调研，生成研究档案', 'Web research, build research dossier') }
    case 'ontology': return { label: L('本体生成', 'Ontology generation'), desc: L('从档案抽取实体与关系本体', 'Extract entity and relation ontology from dossier') }
    case 'graph': return { label: L('知识图谱', 'Knowledge graph'), desc: L('构建时序知识图谱', 'Build temporal knowledge graph') }
    case 'prepare': return { label: L('环境搭建 · 人设', 'Environment setup · personas'), desc: L('生成 Agent 人设与模拟环境', 'Generate agent personas and simulation environment') }
    // ADR 0003: the run stage carries the one reader-facing simulation name
    // (sim_provenance.SIM_LABEL_* as a title); the sub-label keeps the OASIS engine mention.
    case 'run': return { label: L('情景模拟', 'Scenario simulation'), desc: L('OASIS 多智能体情景推演；模拟输出，非证据', 'Multi-agent scenario exercise · OASIS; simulated output, not evidence') }
    case 'report': return { label: L('预测报告', 'Forecast report'), desc: L('综合分析，生成预测报告', 'Synthesize analysis, generate forecast report') }
    default: return null
  }
}

const VALID_STATUS = new Set(['pending', 'running', 'completed', 'failed', 'cancelled'])

function statusText(status) {
  switch (status) {
    case 'pending': return L('待执行', 'Pending')
    case 'running': return L('进行中', 'Running')
    case 'completed': return L('已完成', 'Completed')
    case 'failed': return L('失败', 'Failed')
    case 'cancelled': return L('已取消', 'Cancelled')
    default: return ''
  }
}

function padNum(n) {
  return String(n).padStart(2, '0')
}

// Clamp progress into a safe 0–100 integer; tolerate strings / nulls / NaN.
function clampPct(v) {
  const n = Number(v)
  if (!Number.isFinite(n)) return 0
  return Math.max(0, Math.min(100, Math.round(n)))
}

function truncate(str, max) {
  if (str === null || str === undefined) return ''
  const s = String(str)
  if (s.length <= max) return s
  return s.slice(0, Math.max(0, max - 1)) + '…'
}

// Normalize a raw stage entry into a guaranteed-safe shape.
function normalizeStage(key) {
  const raw = (props.stages && typeof props.stages === 'object') ? props.stages[key] : null
  const meta = stageMeta(key) || { label: key, desc: '' }
  const rawStatus = raw && typeof raw === 'object' ? raw.status : null
  const status = VALID_STATUS.has(rawStatus) ? rawStatus : 'pending'
  return {
    key,
    label: meta.label,
    desc: meta.desc,
    status,
    progress: raw && typeof raw === 'object' ? raw.progress : 0,
    message: raw && typeof raw === 'object' && raw.message ? String(raw.message) : '',
    started_at: raw && typeof raw === 'object' ? raw.started_at : null,
    finished_at: raw && typeof raw === 'object' ? raw.finished_at : null,
    error: raw && typeof raw === 'object' && raw.error ? String(raw.error) : ''
  }
}

const orderedStages = computed(() => {
  const order = props.mode === 'research_only' ? STAGE_ORDER_RESEARCH : STAGE_ORDER_FULL
  return order.map(normalizeStage)
})

const safeGlobalProgress = computed(() => clampPct(props.globalProgress))

const modeLabel = computed(() =>
  props.mode === 'research_only' ? L('仅研究', 'Research only') : L('完整管线', 'Full pipeline')
)

// Status of the currently-active stage (for the header current-line dot).
const currentStageStatus = computed(() => {
  const key = props.currentStage
  if (!key) return ''
  const found = orderedStages.value.find(s => s.key === key)
  return found ? found.status : ''
})

const currentStageLabel = computed(() => {
  const key = props.currentStage
  if (!key) return L('尚未开始', 'Not started')
  const meta = stageMeta(key)
  return meta ? meta.label : key
})

// Elapsed seconds from started_at → finished_at; null when not computable.
function elapsed(stage) {
  if (!stage || !stage.started_at || !stage.finished_at) return null
  const start = Date.parse(stage.started_at)
  const end = Date.parse(stage.finished_at)
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null
  const secs = (end - start) / 1000
  if (!Number.isFinite(secs) || secs < 0) return null
  return secs < 10 ? secs.toFixed(1) : Math.round(secs)
}
</script>

<style scoped>
.stage-timeline {
  --orange: #FF4500;
  --border: #E5E5E5;
  --mono: 'JetBrains Mono', monospace;
  --ink: #000;
  --paper: #fff;
  --muted: #666;
  --faint: #999;
  --ok: #16a34a;
  --err: #b91c1c;
  --soft: #FAFAFA;

  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
  color: var(--ink);
  background: var(--paper);
  border: 1px solid var(--border);
  padding: 0;
  display: flex;
  flex-direction: column;
}

.mono {
  font-family: var(--mono);
}

/* ============ HEADER ============ */
.st-header {
  padding: 18px 20px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--soft);
}

.st-header-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.st-eyebrow {
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted);
}

.st-eyebrow::first-letter {
  color: var(--orange);
}

.st-mode {
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--faint);
  border: 1px solid var(--border);
  padding: 2px 8px;
  border-radius: 2px;
  background: var(--paper);
}

.st-progress-block {
  display: flex;
  align-items: flex-end;
  gap: 20px;
}

.st-progress-number {
  display: flex;
  align-items: baseline;
  line-height: 1;
}

.st-progress-value {
  font-size: 52px;
  font-weight: 600;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}

.st-progress-unit {
  font-size: 22px;
  font-weight: 500;
  color: var(--muted);
  margin-left: 2px;
}

.st-progress-side {
  flex: 1;
  min-width: 0;
  padding-bottom: 6px;
}

.st-progress-bar {
  height: 4px;
  background: var(--border);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 10px;
}

.st-progress-fill {
  height: 100%;
  background: var(--orange);
  border-radius: 2px;
  transition: width 0.5s ease;
}

.st-current-line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.st-current-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--faint);
}

.st-current-label {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.st-current-sub {
  font-size: 10px;
  color: var(--faint);
  letter-spacing: 0.04em;
  flex-shrink: 0;
}

/* ============ TIMELINE ============ */
.st-timeline {
  padding: 8px 20px 16px;
}

.st-row {
  display: flex;
  gap: 16px;
  position: relative;
}

/* Connector column */
.st-connector {
  position: relative;
  width: 22px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.st-line {
  width: 1px;
  background: var(--border);
  flex: 1;
  min-height: 8px;
}

.st-line--top {
  height: 18px;
  flex: 0 0 auto;
}

.st-line.is-hidden {
  visibility: hidden;
}

.st-dot {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  flex-shrink: 0;
  margin: 2px 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px solid var(--faint);
  background: var(--paper);
  box-sizing: border-box;
  position: relative;
  z-index: 1;
}

.st-dot-glyph {
  font-size: 9px;
  line-height: 1;
  color: var(--paper);
  font-weight: 700;
}

/* dot states */
.dot--pending {
  border-color: var(--faint);
  background: var(--paper);
}

.dot--running {
  border-color: var(--orange);
  background: var(--orange);
  animation: st-pulse 1.4s ease-in-out infinite;
}

.dot--completed {
  border-color: var(--ok);
  background: var(--ok);
}

.dot--failed {
  border-color: var(--err);
  background: var(--err);
}

@keyframes st-pulse {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(255, 69, 0, 0.45);
  }
  50% {
    box-shadow: 0 0 0 5px rgba(255, 69, 0, 0);
  }
}

/* Content column */
.st-content {
  flex: 1;
  min-width: 0;
  padding: 14px 0 18px;
}

.st-content-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 4px;
}

.st-index {
  font-size: 11px;
  color: var(--faint);
  font-variant-numeric: tabular-nums;
}

.st-label {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.st-status-pill {
  font-size: 9px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 2px 7px;
  border-radius: 2px;
  border: 1px solid var(--border);
  color: var(--muted);
  background: var(--paper);
}

.pill--running {
  color: var(--orange);
  border-color: var(--orange);
  background: rgba(255, 69, 0, 0.06);
}

.pill--completed {
  color: var(--ok);
  border-color: var(--ok);
  background: rgba(22, 163, 74, 0.06);
}

.pill--failed {
  color: var(--err);
  border-color: var(--err);
  background: rgba(185, 28, 28, 0.06);
}

.st-desc {
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 8px;
  line-height: 1.5;
}

/* Running block */
.st-running-block {
  margin-top: 6px;
}

.st-sub-bar {
  height: 3px;
  background: var(--border);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 6px;
}

.st-sub-fill {
  height: 100%;
  background: var(--orange);
  border-radius: 2px;
  transition: width 0.4s ease;
}

.st-sub-meta {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}

.st-sub-pct {
  font-size: 11px;
  color: var(--orange);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

.st-sub-msg {
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Done block */
.st-done-block {
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
}

.st-done-tag {
  font-size: 12px;
  font-weight: 600;
  color: var(--ok);
}

.st-done-elapsed {
  font-size: 11px;
  color: var(--faint);
  font-variant-numeric: tabular-nums;
}

.st-done-msg {
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

/* Fail block */
.st-fail-block {
  margin-top: 2px;
}

.st-fail-msg {
  font-size: 12px;
  color: var(--err);
  line-height: 1.5;
  display: block;
  word-break: break-word;
}

/* Pending block */
.st-pending-block {
  margin-top: 2px;
}

.st-pending-msg {
  font-size: 12px;
  color: var(--faint);
}

/* Current-row subtle highlight */
.st-row.is-current .st-content {
  position: relative;
}

.st-row.is-current .st-label {
  color: var(--ink);
}

/* ============ EMPTY STATE ============ */
.st-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 48px 20px;
  color: var(--faint);
}

.st-empty-mark {
  font-size: 24px;
  color: var(--orange);
}

.st-empty-text {
  font-size: 13px;
}
</style>
