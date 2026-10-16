<template>
  <section class="ws-panel" v-if="hasWorld || loading || error">
    <div class="ws-head">
      <div class="ws-title">
        <span class="diamond sm">◇</span>
        <span class="ws-label">{{ L('世界状态', 'World state') }}</span>
        <span class="ws-period mono" v-if="vm.periodLabel">{{ vm.periodLabel }}</span>
        <span class="ws-round mono" v-if="vm.committedRound">
          {{ L('已提交', 'committed') }} {{ vm.committedRound }}
        </span>
      </div>
      <div class="ws-badges">
        <span class="ws-badge" :class="'st-' + (vm.arbiterStatus || 'none')" v-if="vm.arbiterStatus">
          {{ L('仲裁', 'arbiter') }}: {{ vm.arbiterStatus }}
        </span>
        <span class="ws-badge st-failed" v-if="vm.arbiterFailedRounds">
          {{ vm.arbiterFailedRounds }} {{ L('轮仅机械推进', 'mechanical-only rounds') }}
        </span>
        <span class="ws-badge st-note">{{ L('推演投影，非观察证据', 'model projection, not evidence') }}</span>
      </div>
    </div>

    <div class="ws-error" v-if="error"><span class="err-dot">●</span><span>{{ error }}</span></div>

    <p class="ws-narrative" v-if="vm.narrative">{{ vm.narrative }}</p>
    <p class="ws-narrative empty" v-else-if="!loading && hasWorld">{{ L('本时段无仲裁叙事', 'No arbiter narrative for this period') }}</p>

    <div class="ws-grid" v-if="hasWorld">
      <div class="ws-card">
        <div class="ws-card-head">{{ L('关键事实', 'Key facts') }} ({{ vm.variables.length }})</div>
        <ul class="ws-list">
          <li v-for="v in vm.variables.slice(0, 12)" :key="v.id" class="ws-var">
            <span class="ws-var-name">{{ v.name }}</span>
            <span class="ws-var-value mono">{{ v.display }}</span>
            <span class="ws-var-delta mono" v-if="v.deltaDisplay" :class="'dir-' + (v.delta ? v.delta.direction : 'flat')">
              {{ v.deltaDisplay }}
            </span>
            <span class="ws-var-prov" v-if="v.provenance">{{ v.provenance }}</span>
          </li>
          <li v-if="!vm.variables.length" class="ws-empty">{{ L('暂无追踪变量', 'No tracked variables yet') }}</li>
        </ul>
      </div>

      <div class="ws-card">
        <div class="ws-card-head">{{ L('本时段行动', 'Moves this period') }} ({{ vm.moves.length }})</div>
        <ul class="ws-list">
          <li v-for="(m, i) in vm.moves.slice(0, 10)" :key="'m' + i" class="ws-move">
            <span class="ws-actor">{{ m.actor }}</span>
            <span class="ws-move-desc">{{ m.description }}</span>
            <q class="ws-stmt" v-if="m.statement">{{ m.statement }}</q>
          </li>
          <li v-if="!vm.moves.length" class="ws-empty">{{ L('无实质行动（观望）', 'No consequential move (actors held)') }}</li>
        </ul>
      </div>

      <div class="ws-card">
        <div class="ws-card-head">{{ L('后果与事件', 'Consequences and events') }} ({{ vm.consequences.length }})</div>
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

      <div class="ws-card">
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
    </div>

    <div class="ws-timeline" v-if="vm.history.length > 1">
      <span
        v-for="h in vm.history"
        :key="h.round"
        class="ws-tick mono"
        :class="['st-' + (h.arbiterStatus || 'none'), { current: h.round === vm.committedRound }]"
        :title="h.headline"
      >{{ h.label }}<template v-if="h.factsChanged"> · {{ h.factsChanged }}Δ</template></span>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { L } from '../../i18n'
import { getWorldState } from '../../api/simulation'
import { summarizeWorldState } from '../../utils/worldState'

const props = defineProps({
  simulationId: { type: String, default: '' },
  // bump to force a reload (the parent passes its refresh counter)
  refreshToken: { type: Number, default: 0 },
  pollMs: { type: Number, default: 15000 }
})

const raw = ref(null)
const loading = ref(false)
const error = ref('')
let timer = null

const vm = computed(() => summarizeWorldState(raw.value))
const hasWorld = computed(() => !!(raw.value && raw.value.committed_round))

async function load() {
  if (!props.simulationId) {
    raw.value = null
    error.value = ''
    return
  }
  loading.value = true
  const simId = props.simulationId
  try {
    const res = await getWorldState(simId, 24)
    if (props.simulationId !== simId) return
    const data = res && res.data
    raw.value = data && typeof data === 'object' ? data : null
    error.value = ''
  } catch (e) {
    if (props.simulationId !== simId) return
    const status = e && e.response && e.response.status
    // 404 = the world has not committed a round yet (or legacy run): stay quiet
    if (status === 404) {
      raw.value = null
      error.value = ''
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

watch(() => props.simulationId, () => { load(); startPolling() })
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
.ws-title { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.ws-period, .ws-round { font-size: 12px; opacity: 0.8; padding: 1px 6px; border-radius: 4px; border: 1px solid var(--border, #e5e7eb); }
.ws-badges { display: flex; gap: 6px; flex-wrap: wrap; }
.ws-badge { font-size: 11px; padding: 2px 7px; border-radius: 999px; border: 1px solid var(--border, #e5e7eb); opacity: 0.9; }
.ws-badge.st-applied { border-color: #16a34a; color: #15803d; }
.ws-badge.st-failed, .ws-badge.st-invalid { border-color: #dc2626; color: #b91c1c; }
.ws-badge.st-skipped { border-color: #ca8a04; color: #a16207; }
.ws-badge.st-note { opacity: 0.65; }
.ws-error { color: #b91c1c; font-size: 12px; margin-top: 6px; display: flex; gap: 6px; align-items: center; }
.ws-narrative { margin: 8px 0 10px; font-size: 13px; line-height: 1.5; }
.ws-narrative.empty { opacity: 0.6; }
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
.ws-move, .ws-pending, .ws-event { display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; }
.ws-actor { font-weight: 600; }
.ws-stmt { display: block; width: 100%; opacity: 0.8; font-style: italic; }
.ws-kind { font-size: 10px; opacity: 0.6; padding: 0 4px; border-radius: 3px; border: 1px solid var(--border, #e5e7eb); }
.ws-due { font-size: 11px; opacity: 0.7; }
.ws-empty { opacity: 0.6; }
.ws-timeline { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; }
.ws-tick { font-size: 11px; padding: 2px 6px; border-radius: 4px; border: 1px solid var(--border, #e5e7eb); opacity: 0.85; }
.ws-tick.st-failed, .ws-tick.st-invalid { border-color: #dc2626; }
.ws-tick.current { font-weight: 700; border-color: currentColor; }
.diamond.sm { font-size: 11px; opacity: 0.7; }
.mono { font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace; }
</style>
