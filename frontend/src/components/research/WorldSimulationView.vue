<template>
  <section class="world-view" :aria-label="L('世界模拟', 'World simulation')" :aria-busy="loading">
    <header class="world-header">
      <div>
        <h2>{{ L('世界模拟', 'World simulation') }} <span class="engine">world-v1</span></h2>
        <p class="caveat">{{ L('声明假设下的条件路径；不是经过校准的概率预测。', 'Conditional pathway under declared assumptions; not a calibrated probability forecast.') }}</p>
      </div>
      <button type="button" :disabled="loading || !simulationId" @click="refreshLatest">{{ L('刷新至最新', 'Refresh latest') }}</button>
    </header>

    <div class="world-controls">
      <label>{{ L('可见范围', 'Visibility view') }}
        <select v-model="view">
          <option value="public">{{ L('公开视图', 'Public view') }}</option>
          <option value="actor">{{ L('参与者视图', 'Actor view') }}</option>
          <option value="analyst">{{ L('分析者视图 · 包含私有建模状态', 'Analyst view · includes private modeled state') }}</option>
        </select>
      </label>
      <form v-if="view === 'actor'" class="actor-form" @submit.prevent="applyActor">
        <label>{{ L('参与者标识', 'Actor ID') }}
          <input v-model="actorDraft" :list="uid + '-actors'" required maxlength="128" autocomplete="off" />
        </label>
        <datalist :id="uid + '-actors'"><option v-for="id in actorChoices" :key="id" :value="id" /></datalist>
        <button type="submit">{{ L('查看参与者', 'View actor') }}</button>
      </form>
      <label>{{ L('已提交回合', 'Committed round') }}
        <select v-model="selectedRound" :disabled="committedRound === null">
          <option value="">{{ L('最新已提交回合', 'Latest committed round') }}</option>
          <option v-for="round in rounds" :key="round" :value="String(round)">{{ round === 0 ? L('0 · 初始状态', '0 · Initial state') : round }}</option>
        </select>
      </label>
    </div>
    <p class="view-label">{{ viewLabel }}<template v-if="view === 'actor' && actorId"> · {{ actorId }}</template></p>
    <p v-if="view !== 'public'" class="privacy-note">{{ L('私有建模状态：模拟中的信念与计划，不代表参与者经核实的真实想法。', 'Private modeled state: simulated beliefs and plans, not verified real-world beliefs of the actors.') }}</p>
    <p v-if="view === 'actor' && !actorId" role="status">{{ L('请输入模型中的参与者标识。建议项仅包含本视图已可见的标识。', 'Enter an actor ID from the model. Suggestions include only IDs already visible in this view.') }}</p>
    <p v-else-if="loading" role="status">{{ L('正在读取已提交状态…', 'Reading committed state…') }}</p>
    <p v-if="errorCode" role="alert" class="error">{{ errorMessage }}</p>

    <template v-if="result">
      <dl class="world-summary">
        <div><dt>{{ L('所选回合', 'Selected round') }}</dt><dd>{{ result.round }} / {{ result.totalRounds }}</dd></div>
        <div><dt>{{ L('已提交至', 'Committed through') }}</dt><dd>{{ result.committedRound }}</dd></div>
        <div><dt>{{ L('模拟时间', 'Simulated time') }}</dt><dd>{{ text(result.world.simulatedAt) }}</dd></div>
        <div><dt>{{ L('状态', 'Status') }}</dt><dd>{{ result.completed ? L('预测期已提交', 'Horizon committed') : L('部分回合已提交', 'Partially committed') }}</dd></div>
        <div><dt>{{ L('数值性质', 'Value status') }}</dt><dd>{{ L('模拟值', 'Simulated') }}</dd></div>
      </dl>
      <details class="identity">
        <summary>{{ L('运行身份与版本', 'Run identity and revisions') }}</summary>
        <dl>
          <dt>{{ L('模拟', 'Simulation') }}</dt><dd>{{ result.simulationId }}</dd>
          <dt>{{ L('运行批次', 'Generation') }}</dt><dd>{{ result.generationId }}</dd>
          <dt>{{ L('最新已提交版本', 'Committed revision') }}</dt><dd>{{ result.revision }}</dd>
          <dt>{{ L('所选状态版本', 'Selected state revision') }}</dt><dd>{{ result.selectedRevision }}</dd>
        </dl>
      </details>

      <div class="world-tabs" role="tablist" :aria-label="L('模拟内容', 'Simulation content')">
        <button v-for="tab in tabs" :id="tabId(tab.key)" :key="tab.key" type="button" role="tab"
          :aria-selected="activeTab === tab.key" :aria-controls="panelId(tab.key)" :tabindex="activeTab === tab.key ? 0 : -1"
          @click="activeTab = tab.key" @keydown="tabKeydown($event, tab.key)">{{ tab.label }}</button>
      </div>

      <section v-show="activeTab === 'state'" :id="panelId('state')" role="tabpanel" :aria-labelledby="tabId('state')" tabindex="0">
        <section v-for="section in stateSections" :key="section.key" class="state-section">
          <h3>{{ section.label }}</h3>
          <div v-if="projection.sections[section.key]?.length" class="table-scroll">
            <table>
              <caption class="sr-only">{{ section.label }} · {{ viewLabel }}</caption>
              <thead><tr>
                <th scope="col">{{ L('名称', 'Name') }}</th><th scope="col">{{ L('数值', 'Value') }}</th>
                <th scope="col">{{ L('单位', 'Unit') }}</th><th scope="col">{{ L('状态', 'Status') }}</th><th scope="col">{{ L('依据', 'Basis') }}</th>
              </tr></thead>
              <tbody><tr v-for="row in projection.sections[section.key]" :key="row.id">
                <th scope="row">{{ row.label || row.name || row.id }}<small v-if="row.description">{{ row.description }}</small><small v-if="row.ownerId">{{ L('所有者', 'Owner') }}: {{ row.ownerId }}</small></th>
                <td class="value">{{ text(section.key === 'accounts' ? row.balance : row.value) }}
                  <small v-if="section.key === 'accounts'">{{ L('已预留', 'Reserved') }}: {{ text(row.reserved) }} {{ text(row.unit) }}</small>
                </td>
                <td>{{ ['rules', 'relations'].includes(section.key) ? L('不适用', 'Not applicable') : text(row.unit) }}</td><td>{{ statusLabel(row.valueStatus || row.status || (row.value == null && section.key !== 'accounts' ? 'unknown' : 'simulated')) }}</td>
                <td>{{ basisText(row) }}</td>
              </tr></tbody>
            </table>
          </div>
          <p v-else class="empty">{{ L('所选回合与视图中没有可见记录。', 'No visible records for this round and view.') }}</p>
        </section>
        <section v-if="view !== 'public'" class="private-state">
          <h3>{{ L('私有建模状态', 'Private modeled state') }}</h3>
          <article v-for="state in projection.privateStates" :key="state.actorId" class="record">
            <h4>{{ state.actorId }}</h4>
            <dl><template v-for="field in privateFields" :key="field.key">
              <dt>{{ field.label }}</dt><dd><pre>{{ text(state[field.key]) }}</pre></dd>
            </template></dl>
          </article>
          <p v-if="!projection.privateStates.length" class="empty">{{ L('此视图没有可见的私有状态。', 'No private state is visible in this view.') }}</p>
        </section>
      </section>

      <section v-show="activeTab === 'decisions'" :id="panelId('decisions')" role="tabpanel" :aria-labelledby="tabId('decisions')" tabindex="0">
        <h3>{{ L('决策与行动', 'Decisions and actions') }}</h3>
        <p v-if="view === 'public'">{{ L('公开视图仅显示可见后果。参与者决策与理由仅在参与者或分析者视图中显示。', 'The public view shows visible consequences. Actor decisions and rationales are available in actor or analyst views.') }}</p>
        <p class="muted">{{ L('包含截至所选回合的可见历史。', 'Visible history through the selected round.') }}</p>
        <article v-for="decision in projection.decisions" :key="decision.decisionId" class="record">
          <h4>{{ decision.actorId }} · {{ L('回合', 'Round') }} {{ decision.round }} · {{ statusLabel(decision.status) }}</h4>
          <p>{{ text(decision.rationale) }}</p>
          <p class="reference">{{ L('决策参考', 'Decision reference') }}: {{ decision.decisionId }} · {{ L('观察参考', 'Observation reference') }}: {{ decision.observationId }}</p>
          <section v-for="intent in decision.intents" :id="recordId('intent', intent.intentId)" :key="intent.intentId" tabindex="-1" class="intent">
            <h5>{{ intent.templateId }} · {{ statusLabel(intent.operation) }}</h5>
            <p class="reference">{{ L('行动参考', 'Action reference') }}: {{ intent.intentId }}</p>
            <pre>{{ text(intent.parameters) }}</pre>
            <p v-if="intent.resolution">{{ intent.resolution.accepted ? L('已接受', 'Accepted') : L('已拒绝', 'Rejected') }} · {{ text(intent.resolution.explanation) }}</p>
            <p v-else>{{ L('此视图没有可见的处理结果。', 'No resolution is visible in this view.') }}</p>
            <p v-if="intent.interactionId">{{ L('相关提议', 'Related offer') }}:
              <a v-if="references.has(intent.interactionId)" :href="referenceHref(intent.interactionId)" @click.prevent="followReference(intent.interactionId)">{{ intent.interactionId }}</a>
              <span v-else>{{ intent.interactionId }} · {{ L('此视图中不可见', 'not visible in this view') }}</span>
            </p>
            <ul v-if="intent.events.length"><li v-for="event in intent.events" :key="event.eventId">
              <a :href="referenceHref(event.eventId)" @click.prevent="followReference(event.eventId)">{{ event.description || event.kind }} · {{ event.eventId }}</a>
            </li></ul>
          </section>
        </article>
        <p v-if="view !== 'public' && !projection.decisions.length" class="empty">{{ L('所选回合与视图中没有可见决策。', 'No visible decisions for this round and view.') }}</p>
        <h3>{{ L('事件与后果', 'Events and consequences') }}</h3>
        <article v-for="event in projection.events" :id="recordId('event', event.eventId)" :key="event.eventId" class="record" tabindex="-1">
          <h4>{{ event.description || event.kind }}</h4>
          <p>{{ L('回合', 'Round') }} {{ event.round }} · {{ event.at }}<template v-if="event.actorId"> · {{ event.actorId }}</template></p>
          <p class="reference">{{ L('事件参考', 'Event reference') }}: {{ event.eventId }}</p>
          <p v-if="event.sourceIntentId">{{ L('来源行动', 'Source action') }}:
            <a v-if="references.has(event.sourceIntentId)" :href="referenceHref(event.sourceIntentId)" @click.prevent="followReference(event.sourceIntentId)">{{ event.sourceIntentId }}</a>
            <span v-else>{{ event.sourceIntentId }} · {{ L('此视图中不可见', 'not visible in this view') }}</span>
          </p>
          <p v-for="ref in eventLinks(event)" :key="ref">{{ L('相关记录', 'Related record') }}: <a :href="referenceHref(ref)" @click.prevent="followReference(ref)">{{ ref }}</a></p>
          <pre v-if="event.details && Object.keys(event.details).length">{{ text(event.details) }}</pre>
          <p class="muted">{{ basisText(event) }}</p>
        </article>
        <p v-if="!projection.events.length" class="empty">{{ L('所选回合与视图中没有可见事件。', 'No visible events for this round and view.') }}</p>
      </section>

      <section v-show="activeTab === 'commitments'" :id="panelId('commitments')" role="tabpanel" :aria-labelledby="tabId('commitments')" tabindex="0">
        <h3>{{ L('承诺与待处理事项', 'Commitments and pending work') }}</h3>
        <p>{{ L('待处理承诺', 'Pending commitments') }}: {{ pendingCount }}</p>
        <article v-for="item in projection.commitments" :id="recordId('commitment', item.id)" :key="item.id" class="record" tabindex="-1">
          <h4>{{ item.templateId || item.id }} · {{ statusLabel(item.status) }}</h4>
          <dl>
            <dt>{{ L('承诺参考', 'Commitment reference') }}</dt><dd>{{ item.id }}</dd>
            <dt>{{ L('参与者', 'Participants') }}</dt><dd>{{ text(item.participantIds) }}</dd>
            <dt>{{ L('到期时间', 'Due time') }}</dt><dd>{{ text(item.dueAt) }}</dd>
            <dt>{{ L('转移义务', 'Transfers') }}</dt><dd><pre>{{ text(item.transfers) }}</pre></dd>
            <dt>{{ L('待生效变化', 'Scheduled effects') }}</dt><dd><pre>{{ text(item.effects) }}</pre></dd>
          </dl>
          <p v-if="item.sourceIntentId">{{ L('来源行动', 'Source action') }}:
            <a v-if="references.has(item.sourceIntentId)" :href="referenceHref(item.sourceIntentId)" @click.prevent="followReference(item.sourceIntentId)">{{ item.sourceIntentId }}</a>
            <span v-else>{{ item.sourceIntentId }} · {{ L('此视图中不可见', 'not visible in this view') }}</span>
          </p>
          <p class="muted">{{ basisText(item) }}</p>
        </article>
        <p v-if="!projection.commitments.length" class="empty">{{ L('此视图没有可见承诺。', 'No commitments are visible in this view.') }}</p>
        <h3>{{ L('提议与互动', 'Offers and interactions') }}</h3>
        <article v-for="item in projection.interactions" :id="recordId('interaction', item.id)" :key="item.id" class="record" tabindex="-1">
          <h4>{{ item.templateId || item.id }} · {{ statusLabel(item.status) }}</h4>
          <p>{{ item.proposerId }} → {{ text(item.recipientIds) }}</p>
          <p class="reference">{{ L('提议参考', 'Offer reference') }}: {{ item.id }}</p>
          <p>{{ L('送达时间', 'Delivery time') }}: {{ text(item.deliverAt) }} · {{ L('失效时间', 'Expiry time') }}: {{ text(item.expiresAt) }}</p>
          <p>{{ L('条款版本', 'Terms version') }}: {{ text(item.termsVersion) }}</p>
          <pre>{{ text(item.terms) }}</pre>
          <p class="muted">{{ basisText(item) }}</p>
        </article>
        <p v-if="!projection.interactions.length" class="empty">{{ L('此视图没有可见提议。', 'No offers are visible in this view.') }}</p>
      </section>

      <section v-show="activeTab === 'assumptions'" :id="panelId('assumptions')" role="tabpanel" :aria-labelledby="tabId('assumptions')" tabindex="0">
        <h3>{{ L('模型假设', 'Model assumptions') }}</h3>
        <article v-for="(assumption, index) in projection.assumptions" :key="assumption.assumptionId || index" class="record">
          <h4>{{ assumption.label || assumption.assumptionId || L('假设', 'Assumption') + ' ' + (index + 1) }}</h4>
          <p>{{ text(assumption.description ?? assumption.statement ?? assumption.text ?? assumption.value) }}</p>
          <p class="muted">{{ L('情景假设', 'Scenario assumption') }}</p>
        </article>
        <p v-if="!projection.assumptions.length" class="empty">{{ L('此视图没有可见假设；这不表示模型没有假设。', 'No assumptions are visible in this view; this does not mean the model has no assumptions.') }}</p>
      </section>
    </template>
  </section>
</template>

<script setup>
import { ref, computed, watch, onUnmounted, nextTick, useId } from 'vue'
import { L } from '../../i18n'
import { getWorldSimulation } from '../../api/simulation'
import { createRequestGate, readWorldResponse, projectWorldResult, worldValue, worldErrorCode, WORLD_REQUEST_TIMEOUT_MS } from '../../utils/worldSimulationView'

const props = defineProps({ simulationId: { type: String, default: '' }, generationId: { type: String, default: '' } })
const uid = useId()
const view = ref('public')
const actorDraft = ref('')
const actorId = ref('')
const selectedRound = ref('')
const committedRound = ref(null)
const result = ref(null)
const revision = ref('')
const pinnedGeneration = ref('')
const actorChoices = ref([])
const loading = ref(false)
const errorCode = ref('')
const activeTab = ref('state')
const requests = createRequestGate()
let resetting = false
const projection = computed(() => projectWorldResult(result.value))
const rounds = computed(() => committedRound.value === null ? [] : Array.from({ length: committedRound.value + 1 }, (_, i) => i))
const pendingCount = computed(() => projection.value.commitments.filter(item => ['pending', 'voting'].includes(item.status)).length)
const viewLabel = computed(() => view.value === 'analyst' ? L('分析者视图 · 包含私有建模状态', 'Analyst view · includes private modeled state')
  : view.value === 'actor' ? L('参与者视图 · 仅该参与者可见的信息', 'Actor view · information visible to this actor') : L('公开视图', 'Public view'))
const tabs = computed(() => [
  { key: 'state', label: L('世界状态', 'World state') }, { key: 'decisions', label: L('决策与行动', 'Decisions and actions') },
  { key: 'commitments', label: L('承诺与待处理事项', 'Commitments and pending work') }, { key: 'assumptions', label: L('模型假设', 'Model assumptions') },
])
const stateSections = computed(() => [
  { key: 'metrics', label: L('指标', 'Metrics') }, { key: 'accounts', label: L('资源账户', 'Resource accounts') },
  { key: 'rules', label: L('规则', 'Rules') }, { key: 'relations', label: L('关系', 'Relations') },
])
const privateFields = computed(() => [
  { key: 'beliefs', label: L('建模信念', 'Modeled beliefs') }, { key: 'plans', label: L('建模计划', 'Modeled plans') },
  { key: 'priorityChanges', label: L('优先级变化', 'Priority changes') }, { key: 'observedEvents', label: L('已观察事件参考', 'Observed event references') },
])
const errorMessage = computed(() => {
  if (errorCode.value === 'stale_revision') return L('已提交状态已变化。请选择“刷新至最新”读取新版本。', 'The committed state changed. Choose “Refresh latest” to read the new revision.')
  if (errorCode.value === 'unknown_actor') return L('未找到该参与者，请检查参与者标识。', 'Actor not found. Check the actor ID.')
  if (errorCode.value === 'view_mismatch') return L('返回结果与所选运行或视图不一致，已隐藏。请重新加载模拟。', 'The result does not match the selected run or view and was hidden. Reload the simulation.')
  if (errorCode.value === 'missing_artifact' || errorCode.value === 'world_incomplete') return L('已提交的世界结果尚不可用，请稍后刷新。', 'Committed world results are not available yet. Refresh later.')
  return L('无法读取此视图。请检查所选参与者与回合，然后刷新重试。', 'Could not read this view. Check the selected actor and round, then refresh to retry.')
})
const text = value => worldValue(value, L('未知', 'Unknown'))
function statusLabel(value) {
  const labels = {
    unknown: ['未知', 'Unknown'], contested: ['有争议', 'Contested'], specified: ['已指定', 'Specified'], simulated: ['模拟值', 'Simulated'],
    pending: ['待处理', 'Pending'], voting: ['投票中', 'Voting'], settled: ['已履行', 'Settled'], breached: ['已违约', 'Breached'],
    accepted: ['已接受', 'Accepted'], rejected: ['已拒绝', 'Rejected'], withdrawn: ['已撤回', 'Withdrawn'], expired: ['已过期', 'Expired'], superseded: ['已替代', 'Superseded'],
    acted: ['已行动', 'Acted'], wait: ['等待', 'Wait'], unable: ['无法行动', 'Unable'], execute: ['执行', 'Execute'],
    propose: ['提议', 'Propose'], accept: ['接受', 'Accept'], reject: ['拒绝', 'Reject'], counter: ['还价', 'Counter'], defer: ['延后', 'Defer'], withdraw: ['撤回', 'Withdraw'],
  }
  return labels[value] ? L(...labels[value]) : text(value)
}
function basisText(record) {
  const basis = record?.basis
  const labels = { source_claim: ['来源陈述', 'Source claim'], report_excerpt: ['报告摘录', 'Report excerpt'],
    scenario_assumption: ['情景假设', 'Scenario assumption'], simulation_event: ['模拟事件', 'Simulation event'] }
  const kind = labels[basis?.kind] ? L(...labels[basis.kind]) : L('依据未知', 'Unknown basis')
  const refs = Array.isArray(basis?.refs) ? basis.refs.map(ref => {
    if (typeof ref === 'string') return ref
    if (ref?.actorId && ref?.claimId) return `${ref.actorId} / ${ref.claimId}${ref.field ? ` · ${ref.field} → ${ref.target}` : ''}`
    if (Number.isInteger(ref?.start) && Number.isInteger(ref?.end)) return `${L('报告字符', 'Report characters')} ${ref.start}–${ref.end}`
    return L('参考未知', 'Unknown reference')
  }) : []
  return `${kind} · ${refs.length ? refs.join(', ') : L('参考未知', 'Unknown references')}`
}
const tabId = key => `${uid}-tab-${key}`
const panelId = key => `${uid}-panel-${key}`
const recordId = (kind, id) => `${uid}-${kind}-${encodeURIComponent(id)}`
const references = computed(() => {
  const map = new Map()
  const add = (id, kind, tab) => { if (id) map.set(id, { id: recordId(kind, id), tab }) }
  for (const decision of projection.value.decisions) for (const intent of decision.intents) add(intent.intentId, 'intent', 'decisions')
  for (const event of projection.value.events) add(event.eventId, 'event', 'decisions')
  for (const item of projection.value.commitments) add(item.id, 'commitment', 'commitments')
  for (const item of projection.value.interactions) add(item.id, 'interaction', 'commitments')
  return map
})
const referenceHref = id => '#' + references.value.get(id)?.id
const eventLinks = event => [event.details?.commitmentId, event.details?.interactionId].filter(id => id && references.value.has(id))
async function followReference(id) {
  const target = references.value.get(id)
  if (!target) return
  activeTab.value = target.tab
  await nextTick()
  if (typeof document !== 'undefined') document.getElementById(target.id)?.focus()
}
async function tabKeydown(event, key) {
  const keys = tabs.value.map(tab => tab.key)
  const index = keys.indexOf(key)
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? keys.length - 1
    : event.key === 'ArrowRight' ? (index + 1) % keys.length : event.key === 'ArrowLeft' ? (index + keys.length - 1) % keys.length : null
  if (next === null) return
  event.preventDefault()
  activeTab.value = keys[next]
  await nextTick()
  if (typeof document !== 'undefined') document.getElementById(tabId(keys[next]))?.focus()
}
function applyActor() {
  const next = actorDraft.value.trim()
  if (!next) return
  if (actorId.value === next) load()
  else actorId.value = next
}
function refreshLatest() {
  resetting = true
  revision.value = ''
  selectedRound.value = ''
  resetting = false
  load()
}
async function load() {
  const ticket = requests.begin()
  result.value = null
  actorChoices.value = []
  errorCode.value = ''
  loading.value = false
  if (!props.simulationId || (view.value === 'actor' && !actorId.value)) return
  const request = { simulationId: props.simulationId, generationId: props.generationId || pinnedGeneration.value,
    view: view.value, actorId: view.value === 'actor' ? actorId.value : undefined,
    round: selectedRound.value === '' ? undefined : Number(selectedRound.value), revision: revision.value || undefined }
  loading.value = true
  try {
    const response = await getWorldSimulation(request.simulationId, request, { signal: ticket.signal, timeout: WORLD_REQUEST_TIMEOUT_MS })
    if (!ticket.isCurrent()) return
    const data = readWorldResponse(response, request)
    result.value = data
    revision.value = data.revision
    pinnedGeneration.value = data.generationId
    committedRound.value = data.committedRound
    actorChoices.value = projection.value.actorIds
  } catch (error) {
    if (!ticket.isCurrent()) return
    errorCode.value = worldErrorCode(error)
  } finally {
    if (ticket.isCurrent()) loading.value = false
  }
}
watch(() => [props.simulationId, props.generationId, view.value, actorId.value, selectedRound.value], (next, previous) => {
  if (resetting) return
  if (previous && (next[0] !== previous[0] || next[1] !== previous[1])) {
    resetting = true
    view.value = 'public'; actorId.value = ''; actorDraft.value = ''; selectedRound.value = ''
    revision.value = ''; pinnedGeneration.value = ''; committedRound.value = null; activeTab.value = 'state'
    actorChoices.value = []
    resetting = false
  } else if (previous && (next[2] !== previous[2] || next[3] !== previous[3])) {
    // Suggestions must never retain IDs learned in a more privileged view.
    actorChoices.value = []
  }
  load()
}, { immediate: true, flush: 'sync' })
onUnmounted(() => requests.invalidate())
</script>

<style scoped>
.world-view { color: #17211f; background: #fff; font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif; display: grid; gap: 18px; min-width: 0; }
h2, h3, h4, h5, p { margin: 0; } h2 { font-size: 21px; } h3 { font-size: 17px; margin: 18px 0 12px; } h4 { font-size: 15px; } h5 { font-size: 14px; }
.world-header, .world-controls, .actor-form { display: flex; flex-wrap: wrap; align-items: end; gap: 14px; }
.world-header { align-items: start; justify-content: space-between; }
.world-header > div { flex: 1 1 280px; }
.engine { font-size: 12px; color: #16675c; border: 1px solid #aad2c9; padding: 3px 7px; border-radius: 4px; white-space: nowrap; }
.caveat { font-size: 14px; line-height: 1.6; color: #555; margin-top: 10px; }
label { display: grid; gap: 6px; font-size: 13px; font-weight: 600; }
button, select, input { font: inherit; font-size: 13px; color: inherit; border: 1px solid #b7c5c0; border-radius: 5px; padding: 9px 12px; background: white; max-width: 100%; }
button { cursor: pointer; } button:disabled, select:disabled { opacity: .55; cursor: default; }
button:hover:not(:disabled) { background: #f0f6f4; }
:focus-visible { outline: 3px solid #167eac; outline-offset: 3px; }
.view-label { font-weight: 600; font-size: 14px; }
.privacy-note { padding: 12px; border-left: 3px solid #9c6e16; background: #fff8e9; line-height: 1.6; }
.error { color: #9b2226; padding: 12px; background: #fff1f0; }
.world-summary { display: flex; flex-wrap: wrap; gap: 20px; padding: 16px; background: #f3f7f5; margin: 0; }
dt { font-size: 12px; color: #53605b; margin-top: 8px; } dd { margin: 4px 0 0; overflow-wrap: anywhere; }
.identity { font-size: 13px; overflow-wrap: anywhere; } summary { cursor: pointer; font-weight: 600; padding: 8px 0; }
.world-tabs { display: flex; flex-wrap: wrap; gap: 6px; border-bottom: 1px solid #dce4e0; padding-bottom: 10px; }
[role='tab'][aria-selected='true'] { background: #145d52; border-color: #145d52; color: #fff; }
[role='tabpanel'] { min-width: 0; }
.table-scroll { overflow-x: auto; } table { border-collapse: collapse; width: 100%; font-size: 13px; text-align: left; }
th, td { border-bottom: 1px solid #e2e7e4; padding: 12px; vertical-align: top; overflow-wrap: anywhere; }
thead { background: #f5f7f6; } small { display: block; color: #53605b; font-weight: normal; margin-top: 5px; }
.value, pre, .reference { font-family: 'JetBrains Mono', monospace; }
.record { padding: 16px; margin: 12px 0; border: 1px solid #dce4e0; border-radius: 6px; overflow-wrap: anywhere; }
.record p { margin: 10px 0; line-height: 1.6; } .intent { border-left: 2px solid #aad2c9; padding: 12px; margin-top: 12px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; line-height: 1.6; margin: 8px 0; }
.reference, .muted, .empty { font-size: 13px; color: #53605b; line-height: 1.6; }
a { color: #096858; text-decoration: underline; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (max-width: 600px) { .world-controls > label, .actor-form { width: 100%; } .actor-form label { flex: 1; min-width: 0; } th, td { padding: 8px; } }
</style>
