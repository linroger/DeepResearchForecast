<template>
  <section class="ws-panel" v-if="hasWorld || loading || error">
    <div class="ws-head">
      <div class="ws-title">
        <span class="diamond sm">◇</span>
        <span class="ws-label">{{ L('世界状态', 'World state') }}</span>
        <span class="ws-period mono" v-if="vm.periodLabel">{{ vm.periodLabel }}</span>
        <span class="ws-past mono" v-if="vm.isPast">
          {{ L('历史时段', 'past period') }} · {{ L('第', 'round ') }}{{ vm.selectedRound }}{{ L('期', '') }} / {{ vm.latestRound }}
        </span>
        <span class="ws-round mono" v-if="vm.committedRound">
          {{ L('已提交', 'committed') }} {{ vm.committedRound }}
        </span>
        <button type="button" class="ws-back mono" v-if="vm.isPast" @click="backToLatest">
          ↩ {{ L('回到最新', 'back to latest') }}<template v-if="vm.latestLabel"> · {{ vm.latestLabel }}</template>
        </button>
      </div>
      <div class="ws-badges">
        <span class="ws-badge" :class="'st-' + (vm.arbiterStatus || 'none')" v-if="vm.arbiterStatus">
          {{ L('仲裁', 'arbiter') }}: {{ vm.arbiterStatus }}
        </span>
        <span class="ws-badge st-failed" v-if="vm.arbiterFailedRounds">
          {{ vm.arbiterFailedRounds }} {{ L('轮仅机械推进', 'mechanical-only rounds') }}
        </span>
        <span class="ws-badge st-gaps" v-if="vm.seedGaps.length" :title="gapsTitle">
          {{ vm.seedGaps.length }} {{ L('项建模缺口', 'modelling gaps') }}
        </span>
        <span class="ws-badge st-behaviour" v-if="vm.behaviour" :title="behaviourTitle">
          {{ L('回应上期', 'responsive moves') }} {{ Math.round(vm.behaviour.responsiveShare * 100) }}%
        </span>
        <span class="ws-badge st-note">{{ L('推演投影，非观察证据', 'model projection, not evidence') }}</span>
        <button class="ws-lang-btn" :class="{ active: overlayLang === 'zh' }" @click="toggleOverlayLang"
                :disabled="overlayBusy" :title="L('切换中文翻译', 'Toggle Chinese translation')">
          {{ overlayBusy ? '…' : '中' }}</button>
      </div>
    </div>

    <div class="ws-error" v-if="error"><span class="err-dot">●</span><span>{{ error }}</span></div>

    <div class="ws-headline mono" v-if="vm.headlineSummary">{{ vm.headlineSummary }}</div>
    <p class="ws-narrative" v-if="vm.narrative">{{ displayText(digestKey, vm.narrative) }}</p>
    <p class="ws-narrative empty" v-else-if="!loading && hasWorld">{{ L('本时段无仲裁叙事', 'No arbiter narrative for this period') }}</p>
    <ul class="ws-problems" v-if="vm.arbiterProblems.length">
      <li v-for="(p, i) in vm.arbiterProblems" :key="'ap' + i">
        <span class="warn-dot">▲</span><span>{{ L('仲裁问题', 'arbiter problem') }}: {{ p }}</span>
      </li>
    </ul>
    <div class="ws-decisions mono" v-if="decisionsLine">{{ decisionsLine }}</div>

    <div class="ws-grid" v-if="hasWorld">
      <div class="ws-card" v-if="!vm.isPast">
        <div class="ws-card-head">{{ L('关键事实', 'Key facts') }} ({{ vm.variables.length }})</div>
        <ul class="ws-list">
          <li v-for="v in vm.variables.slice(0, 12)" :key="v.id" class="ws-var">
            <span class="ws-var-name">{{ tvar(v.id, v.name) }}</span>
            <span class="ws-var-value mono">{{ v.display }}</span>
            <span class="ws-var-delta mono" v-if="v.deltaDisplay" :class="'dir-' + (v.delta ? v.delta.direction : 'flat')">
              {{ v.deltaDisplay }}
            </span>
            <span class="ws-var-prov" v-if="v.provenance">{{ v.provenance }}</span>
          </li>
          <li v-if="!vm.variables.length" class="ws-empty">{{ L('暂无追踪变量', 'No tracked variables yet') }}</li>
        </ul>
      </div>
      <div class="ws-card" v-else>
        <div class="ws-card-head">
          {{ L('本时段事实变化', 'Facts changed this period') }} ({{ vm.variablesChanged.length + vm.variablesAdded.length }})
        </div>
        <ul class="ws-list">
          <li v-for="v in vm.variablesChanged.slice(0, 12)" :key="'vc' + v.id" class="ws-var">
            <span class="ws-var-name">{{ tvar(v.id, v.name) }}</span>
            <span class="ws-var-delta mono" :class="'dir-' + v.direction">{{ v.display }}</span>
          </li>
          <li v-for="v in vm.variablesAdded.slice(0, 8)" :key="'va' + v.id" class="ws-var">
            <span class="ws-kind mono">{{ L('新增', 'new') }}</span>
            <span class="ws-var-name">{{ tvar(v.id, v.name) }}</span>
            <span class="ws-var-value mono">{{ v.display }}</span>
          </li>
          <li v-if="!vm.variablesChanged.length && !vm.variablesAdded.length" class="ws-empty">
            {{ L('本时段无事实变化', 'No facts changed this period') }}
          </li>
        </ul>
      </div>

      <div class="ws-card">
        <div class="ws-card-head">{{ L('本时段行动', 'Moves this period') }} ({{ vm.moves.length }})</div>
        <ul class="ws-list">
          <li v-for="(m, i) in vm.moves.slice(0, 10)" :key="'m' + i" class="ws-move">
            <span class="ws-actor" v-if="m.actor">{{ m.actor }}</span>
            <span class="ws-move-desc">{{ m.description }}</span>
            <q class="ws-stmt" v-if="m.statement">{{ m.statement }}</q>
          </li>
          <li v-if="!vm.moves.length" class="ws-empty">{{ L('无实质行动（观望）', 'No consequential move (actors held)') }}</li>
        </ul>
      </div>

      <div class="ws-card">
        <div class="ws-card-head">
          {{ L('后果与事件', 'Consequences and events') }} ({{ vm.consequences.length + vm.relationshipChanges.length }})
        </div>
        <ul class="ws-list">
          <li v-for="(c, i) in vm.consequences.slice(0, 10)" :key="'c' + i" class="ws-event">
            <span class="ws-kind mono">{{ c.kind }}</span><span>{{ c.description }}</span>
          </li>
          <li v-for="(r, i) in vm.relationshipChanges.slice(0, 6)" :key="'r' + i" class="ws-event">
            <span class="ws-kind mono">{{ L('关系', 'relation') }}</span>
            <span>{{ r.source }} — {{ r.target }}: {{ r.to }}<template v-if="r.direction"> ({{ r.direction }})</template></span>
          </li>
          <li v-if="!vm.consequences.length && !vm.relationshipChanges.length" class="ws-empty">
            {{ L('本时段无新事件', 'No new events this period') }}
          </li>
        </ul>
      </div>

      <div class="ws-card" v-if="!vm.isPast">
        <div class="ws-card-head">{{ L('待兑现与预期', 'Pending and expected') }} ({{ vm.pending.length }})</div>
        <ul class="ws-list">
          <li v-for="(p, i) in vm.pending.slice(0, 10)" :key="'p' + i" class="ws-pending">
            <span class="ws-actor">{{ p.actor }}</span>
            <span>{{ p.description }}</span>
            <span class="ws-due mono" v-if="p.dueRound !== null">{{ L('第', 'round ') }}{{ p.dueRound }}{{ L('期', '') }}</span>
          </li>
          <li v-if="!vm.pending.length" class="ws-empty">{{ L('无待兑现承诺', 'No open commitments') }}</li>
        </ul>
      </div>
      <div class="ws-card" v-if="vm.offers.length || vm.offerCounts">
        <div class="ws-card-head">
          {{ vm.isPast ? L('本时段的要约与协议', 'Offers and agreements this period') : L('要约与协议', 'Offers and agreements') }}
          ({{ vm.offers.length }})
        </div>
        <ul class="ws-list">
          <li v-for="it in vm.offers.slice(0, 8)" :key="it.id" class="ws-offer">
            <span class="ws-badge mono" :class="'offer-' + it.status">{{ it.status }}</span>
            <span class="ws-actor">{{ it.proposer }} → {{ it.recipient }}</span>
            <span>{{ it.terms }}</span>
            <span class="ws-due mono" v-if="!vm.isPast && it.expiresRound !== null && (it.status === 'open' || it.status === 'deferred')">
              {{ L('截至第', 'until round ') }}{{ it.expiresRound }}{{ L('期', '') }}
            </span>
          </li>
          <li v-if="!vm.offers.length" class="ws-empty">{{ L('本时段无要约变动', 'No offers moved this period') }}</li>
        </ul>
        <div class="ws-decisions mono" v-if="vm.offerCounts && !vm.isPast">
          {{ L('累计', 'total') }} {{ vm.offerCounts.opened || 0 }} · {{ L('接受', 'accepted') }} {{ vm.offerCounts.accepted || 0 }}
          · {{ L('拒绝', 'rejected') }} {{ vm.offerCounts.rejected || 0 }} · {{ L('失效', 'lapsed') }} {{ vm.offerCounts.lapsed || 0 }}
          · {{ L('违约', 'breached') }} {{ vm.offerCounts.breached || 0 }}
        </div>
      </div>
    </div>

    <details class="ws-digest" v-if="vm.digest" :open="!vm.narrative">
      <summary>{{ L('本时段推送给智能体的摘要', 'Digest shown to the agents this period') }}</summary>
      <pre class="ws-digest-text">{{ displayText(digestKey, vm.digest) }}</pre>
    </details>

    <div class="ws-timeline" role="group" :aria-label="L('选择已提交的时段', 'Select a committed period')" v-if="vm.history.length > 1">
      <button
        v-for="h in vm.history"
        :key="h.round"
        type="button"
        class="ws-tick mono"
        :class="['st-' + (h.arbiterStatus || 'none'), { current: h.isCurrent, selected: h.isSelected }]"
        :aria-pressed="h.isSelected"
        :aria-label="tickLabel(h)"
        :title="h.headline"
        @click="selectRound(h.round)"
      >{{ h.label }}<template v-if="h.factsChanged"> · {{ h.factsChanged }}Δ</template></button>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { L } from '../../i18n'
import { getWorldState } from '../../api/simulation'
import { decisionsSummary, nextSelectedRound, resolveSelectedRound, summarizeWorldState } from '../../utils/worldState'

const props = defineProps({
  simulationId: { type: String, default: '' },
  // bump to force a reload (the parent passes its refresh counter)
  refreshToken: { type: Number, default: 0 },
  pollMs: { type: Number, default: 15000 },
  // PERIOD VIEW: the parent's copy of the selection (null = latest). Leave undefined to let
  // the panel own it; pass a value to push a reset (e.g. the feed's "all periods" button).
  round: { default: undefined }
})
// PERIOD VIEW: every change of the selected round is announced so the feed can follow it
const emit = defineEmits(['update:selectedRound'])

// history rows requested per poll: four years of monthly rounds; the API caps at 200
const HISTORY_ROWS = 48

const raw = ref(null)
const loading = ref(false)
const error = ref('')
// null = follow the latest committed round; a round number pins that past period across live refreshes
const selectedRound = ref(null)
let timer = null

// 2026-10-21: 中文翻译 overlay（问题/变量名/仲裁叙事/摘要）。生成走后台 + 轮询；
// 任何失败静默回退源文本。digestKey 跟随当前选择的轮次。
const overlayLang = ref(null)
const overlayBusy = ref(false)
const overlayMap = ref({})
const digestKey = computed(() => (selectedRound.value ? `digest:${selectedRound.value}` : 'digest:latest'))
async function toggleOverlayLang() {
  if (overlayBusy.value) return
  if (overlayLang.value === 'zh') { overlayLang.value = null; return }
  overlayBusy.value = true
  overlayLang.value = 'zh'
  try {
    if (props.simulationId) {
      const { ensureOverlay, simulationOverlayFetcher } = await import('../../utils/overlayTranslation')
      const result = await ensureOverlay(simulationOverlayFetcher(props.simulationId), 'zh')
      overlayMap.value = (result && result.overlay) || {}
    }
  } finally { overlayBusy.value = false }
}
function tvar(varId, sourceName) {
  if (overlayLang.value !== 'zh') return sourceName
  return overlayMap.value[`var:${varId}:name`] || sourceName
}
function displayText(key, sourceText) {
  if (overlayLang.value !== 'zh') return sourceText
  return overlayMap.value[key] || sourceText
}

const vm = computed(() => summarizeWorldState(raw.value, selectedRound.value))
const hasWorld = computed(() => !!(raw.value && raw.value.committed_round))
const decisionsLine = computed(() => decisionsSummary(vm.value.decisions, {
  decisions: L('项决策', 'decisions'), ok: L('有效', 'ok'), held: L('观望', 'held'),
  failed: L('失败', 'failed'), invalid: L('无效', 'invalid')
}))

function selectRound(round) {
  selectedRound.value = nextSelectedRound(vm.value.history, round)
}

function backToLatest() {
  selectedRound.value = null
}

// MODELLING GAPS / BEHAVIOUR badges carry their detail in the title attribute (hover)
const gapsTitle = computed(() => vm.value.seedGaps.map((g) => `${g.kind}: ${g.subject} — ${g.note}`).join('\n'))
const behaviourTitle = computed(() => vm.value.behaviour
  ? `${vm.value.behaviour.responsiveMoves}/${vm.value.behaviour.moves} ${L('项行动回应了上期的事实变化或他方行动', 'moves answered last period\'s changes or another actor')} (${vm.value.behaviour.roundsScored} ${L('个时段', 'periods')}, ${vm.value.behaviour.offersAnswered} ${L('项应答要约', 'offers answered')}). ${L('文本层面的诊断，非真实性判定', 'Textual diagnostic, not a realism verdict')}`
  : '')

function tickLabel(h) {
  const bits = [h.label, `${L('仲裁', 'arbiter')} ${h.arbiterStatus || L('无', 'none')}`]
  if (h.factsChanged) bits.push(`${h.factsChanged} ${L('项事实变化', 'facts changed')}`)
  if (h.isCurrent) bits.push(L('最新', 'latest'))
  return bits.join(', ')
}

// a pinned round that vanished from the history (rerun, rotated artifacts) → follow the live world again
function dropStaleSelection() {
  if (selectedRound.value === null) return
  const history = raw.value && Array.isArray(raw.value.history) ? raw.value.history : []
  if (resolveSelectedRound(history, selectedRound.value) !== selectedRound.value) selectedRound.value = null
}

async function load() {
  if (!props.simulationId) {
    raw.value = null
    error.value = ''
    selectedRound.value = null
    return
  }
  loading.value = true
  const simId = props.simulationId
  try {
    const res = await getWorldState(simId, HISTORY_ROWS)
    if (props.simulationId !== simId) return
    const data = res && res.data
    raw.value = data && typeof data === 'object' ? data : null
    error.value = ''
    dropStaleSelection()
  } catch (e) {
    if (props.simulationId !== simId) return
    const status = e && e.response && e.response.status
    // 404 = the world has not committed a round yet (or legacy run): stay quiet
    if (status === 404) {
      raw.value = null
      error.value = ''
      selectedRound.value = null
    } else {
      error.value = L('世界状态加载失败', 'Could not load the world state')
    }
  } finally {
    loading.value = false
  }
}

function startPolling() {
  stopPolling()
  if (props.pollMs > 0) timer = setInterval(load, props.pollMs)
}
function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

watch(() => props.simulationId, () => { selectedRound.value = null; load(); startPolling() })
watch(selectedRound, (value) => { emit('update:selectedRound', value) })
watch(() => props.round, (value) => {
  if (value !== undefined && value !== selectedRound.value) selectedRound.value = value
})
watch(() => props.refreshToken, () => { load() })
onMounted(() => { load(); startPolling() })
onUnmounted(stopPolling)
</script>

<style scoped>
.ws-panel {
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 10px;
  padding: 12px 14px;
  margin: 10px 0 14px;
  background: var(--panel-bg, rgba(255, 255, 255, 0.6));
}
.ws-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; }
.ws-title { display: flex; align-items: center; gap: 8px; font-weight: 600; flex-wrap: wrap; }
.ws-period, .ws-round { font-size: 12px; opacity: 0.8; padding: 1px 6px; border-radius: 4px; border: 1px solid var(--border, #e5e7eb); }
.ws-past {
  font-size: 12px; padding: 1px 6px; border-radius: 4px;
  border: 1px solid var(--color-warn, #d97706); color: var(--color-warn, #d97706); background: rgba(217, 119, 6, 0.1);
}
.ws-back {
  appearance: none; cursor: pointer; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 4px;
  border: 1px solid var(--color-ink, #0a0a0a); background: var(--color-ink, #0a0a0a); color: var(--color-paper, #fff);
}
.ws-back:hover { opacity: 0.85; }
.ws-badges { display: flex; gap: 6px; flex-wrap: wrap; }
.ws-badge { font-size: 11px; padding: 2px 7px; border-radius: 999px; border: 1px solid var(--border, #e5e7eb); opacity: 0.9; }
.ws-badge.st-applied { border-color: #16a34a; color: #15803d; }
.ws-badge.st-failed, .ws-badge.st-invalid { border-color: #dc2626; color: #b91c1c; }
.ws-badge.st-skipped { border-color: #ca8a04; color: #a16207; }
.ws-badge.st-note { opacity: 0.65; }
.ws-error { color: #b91c1c; font-size: 12px; margin-top: 6px; display: flex; gap: 6px; align-items: center; }
.ws-headline { font-size: 11px; opacity: 0.7; margin-top: 8px; }
.ws-narrative { margin: 6px 0 8px; font-size: 13px; line-height: 1.5; }
.ws-narrative.empty { opacity: 0.6; }
.ws-problems { list-style: none; margin: 0 0 8px; padding: 0; display: flex; flex-direction: column; gap: 3px; font-size: 12px; color: #b45309; }
.ws-problems li { display: flex; gap: 6px; align-items: baseline; }
.warn-dot { font-size: 9px; }
.ws-decisions { font-size: 11px; opacity: 0.75; margin: 0 0 8px; }
.ws-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 10px; }
.ws-card { border: 1px solid var(--border, #e5e7eb); border-radius: 8px; padding: 8px 10px; min-height: 80px; }
.ws-card-head { font-size: 12px; font-weight: 600; opacity: 0.85; margin-bottom: 6px; }
.ws-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 5px; font-size: 12.5px; }
.ws-var { display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; }
.ws-var-name { flex: 1 1 auto; }
.ws-var-value { font-weight: 600; }
.ws-var-delta { font-size: 11px; opacity: 0.8; }
.ws-var-delta.dir-up { color: #15803d; }
.ws-var-delta.dir-down { color: #b91c1c; }
.ws-var-prov { font-size: 10px; opacity: 0.55; text-transform: uppercase; letter-spacing: 0.03em; }
.ws-move, .ws-pending, .ws-event, .ws-offer { display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; }
.st-gaps { border-color: #d97706; color: #b45309; cursor: help; }
.st-behaviour { cursor: help; }
.offer-open, .offer-deferred { border-color: #d97706; color: #b45309; }
.offer-accepted { border-color: #16a34a; color: #15803d; }
.offer-rejected, .offer-lapsed { opacity: 0.75; }
.offer-breached { border-color: #dc2626; color: #b91c1c; }
.ws-actor { font-weight: 600; }
.ws-stmt { display: block; width: 100%; opacity: 0.8; font-style: italic; }
.ws-kind { font-size: 10px; opacity: 0.6; padding: 0 4px; border-radius: 3px; border: 1px solid var(--border, #e5e7eb); }
.ws-due { font-size: 11px; opacity: 0.7; }
.ws-empty { opacity: 0.6; }
.ws-digest { margin-top: 10px; font-size: 12px; }
.ws-digest summary { cursor: pointer; opacity: 0.75; }
.ws-digest-text {
  white-space: pre-wrap; font-family: inherit; font-size: 12px; line-height: 1.5;
  margin: 6px 0 0; padding: 8px 10px; border: 1px solid var(--border, #e5e7eb); border-radius: 6px; max-height: 260px; overflow: auto;
}

/* Period strip: one toggle button per committed round. Hue = arbiter verdict (translucent tints and
   inherited text stay legible on light and dark surfaces), solid fill = selected, bold + ring = latest. */
.ws-timeline { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; }
.ws-tick {
  appearance: none; cursor: pointer; font: inherit; font-size: 11px; line-height: 1.5; padding: 2px 8px;
  border-radius: 4px; color: inherit; border: 1px solid rgba(120, 120, 120, 0.55); background: rgba(120, 120, 120, 0.1);
}
.ws-tick.st-applied { border-color: rgba(22, 163, 74, 0.7); background: rgba(22, 163, 74, 0.12); }
.ws-tick.st-skipped { border-color: #ca8a04; background: rgba(202, 138, 4, 0.12); }
.ws-tick.st-failed, .ws-tick.st-invalid { border-color: #dc2626; background: rgba(220, 38, 38, 0.1); }
.ws-tick:hover { text-decoration: underline; }
.ws-tick.current { font-weight: 700; box-shadow: 0 0 0 1px currentColor; }
.ws-tick.selected { color: #fff; background: #52525b; border-color: #52525b; }
.ws-tick.selected.st-applied { background: #15803d; border-color: #15803d; }
.ws-tick.selected.st-skipped { background: #a16207; border-color: #a16207; }
.ws-tick.selected.st-failed, .ws-tick.selected.st-invalid { background: #b91c1c; border-color: #b91c1c; }
.diamond.sm { font-size: 11px; opacity: 0.7; }
.mono { font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace; }
</style>

<style scoped>
.ws-lang-btn { margin-left: auto; border: 1px solid var(--color-neu, #9aa5b1); background: transparent;
  color: inherit; border-radius: 6px; padding: 1px 8px; font-size: 12px; cursor: pointer; }
.ws-lang-btn.active { background: var(--color-accent, #3b6fb0); color: #fff; border-color: transparent; }
.ws-lang-btn:disabled { opacity: 0.5; cursor: wait; }
</style>
