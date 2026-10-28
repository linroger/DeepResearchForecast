<template>
  <section class="target-view" aria-label="Target simulation diagnostics">
    <div class="target-heading">
      <h2>{{ L('目标分布与机制路径', 'Target distribution and mechanism paths') }}</h2>
      <button type="button" @click="load" :disabled="loading || !simulationId">{{ L('刷新', 'Refresh') }}</button>
    </div>
    <p class="weight-notice"><strong>{{ L('预测权重：0', 'Forecast weight: 0') }}</strong> · {{ L('条件机制诊断，不是经过校准的预测概率；报告数字由研究评估决定。', 'Conditional mechanism diagnostics, not calibrated forecast probabilities. Research assessments determine report numbers.') }}</p>
    <p v-if="!simulationId">{{ L('模拟准备完成后显示目标路径。', 'Target paths appear after simulation preparation.') }}</p>
    <p v-else-if="loading" role="status">{{ L('正在读取目标诊断…', 'Loading target diagnostics…') }}</p>
    <p v-else-if="error" role="alert">{{ error }}</p>
    <template v-else-if="result">
      <p class="identity">{{ result.caseId }} · {{ result.simulationId }} · {{ L('案例哈希', 'Case hash') }} {{ result.caseHash }}</p>
      <p><strong>{{ targetLabel }}</strong> · {{ result.resolution.units }} · {{ L('结算日期', 'Resolution date') }} {{ result.resolution.horizon }}</p>
      <p>{{ L('结算来源', 'Settlement source') }}: {{ result.resolution.settlementSource?.name || L('未知', 'Unknown') }}</p>
      <p v-if="result.simulation.decisionBudget" class="budget-status">
        {{ L('决策请求', 'Decision requests') }}: {{ result.simulation.decisionBudget.requests }} / {{ result.simulation.decisionBudget.maximumRequests }} · {{ L('缓存复用', 'Cache hits') }}: {{ result.simulation.decisionBudget.cacheHits }}
      </p>
      <p v-if="result.simulation.decisionBudget?.exhausted" role="status" class="weight-notice">
        {{ L('决策预算已耗尽；后续新决策请求返回空行动。部分路径受到预算限制，不能视为完整的战略响应。', 'Decision budget exhausted; subsequent new decision requests returned no actions. Some paths are budget-limited and do not represent complete strategic responses.') }}
      </p>
      <dl class="summary">
        <div><dt>{{ L('路径数', 'Paths') }}</dt><dd>{{ paths.length }}</dd></div>
        <div><dt>{{ L('最小值', 'Minimum') }}</dt><dd>{{ format(distribution.min) }}</dd></div>
        <div><dt>{{ L('中位数', 'Median') }}</dt><dd>{{ format(distribution.median) }}</dd></div>
        <div><dt>{{ L('最大值', 'Maximum') }}</dt><dd>{{ format(distribution.max) }}</dd></div>
      </dl>
      <h3>{{ L('终值分布', 'Terminal distribution') }}</h3>
      <div class="table-wrap"><table>
        <caption>{{ L('每条路径的目标终值；频数不等于研究后验概率。', 'Target terminal value for each path; frequencies are not research posterior probabilities.') }}</caption>
        <thead><tr><th scope="col">{{ L('路径', 'Path') }}</th><th scope="col">{{ result.resolution.units }}</th><th scope="col">{{ L('相对范围', 'Relative range') }}</th></tr></thead>
        <tbody><tr v-for="path in paths" :key="path.pathId"><th scope="row">{{ path.pathId }}</th><td>{{ format(path.targetValue) }}</td><td><meter :min="meterMin" :max="meterMax" :value="path.targetValue" :aria-label="`${path.pathId}: ${format(path.targetValue)}`" /></td></tr></tbody>
      </table></div>
      <h3>{{ L('路径详情', 'Path detail') }}</h3>
      <label>{{ L('选择路径', 'Select path') }} <select v-model="selectedPathId"><option v-for="path in paths" :key="path.pathId" :value="path.pathId">{{ path.pathId }}</option></select></label>
      <template v-if="selectedPath">
        <div class="table-wrap"><table>
          <caption>{{ L('目标轨迹', 'Target trajectory') }}</caption>
          <thead><tr><th scope="col">{{ L('时期', 'Period') }}</th><th scope="col">{{ targetLabel }}</th></tr></thead>
          <tbody><tr v-for="step in selectedPath.trajectory" :key="step.period"><th scope="row">{{ step.period }}</th><td>{{ format(step.values?.[result.resolution.targetNodeId]) }} {{ result.resolution.units }}</td></tr></tbody>
        </table></div>
        <details><summary>{{ L('本路径抽取的参数', 'Parameters sampled for this path') }}</summary><pre>{{ pretty(selectedPath.parameters) }}</pre></details>
        <details><summary>{{ L('参与者决策', 'Actor decisions') }}</summary><pre>{{ pretty(selectedPath.decisions) }}</pre></details>
      </template>
      <h3>{{ L('未解决假设', 'Unresolved assumptions') }}</h3>
      <p>{{ L('假设和未知量仍未被证据确认；模拟完成并不会消除这些缺口。', 'Assumptions and unknowns remain unverified by evidence; completing the simulation does not resolve these gaps.') }}</p>
      <ul v-if="assumptions.length" class="assumptions"><li v-for="item in assumptions" :key="item.id"><strong>{{ item.label }}</strong> · {{ item.status }}<p>{{ item.gap || L('未记录证据缺口说明。', 'No evidence-gap explanation recorded.') }}</p><p v-if="item.range">{{ L('假设范围', 'Assumed range') }}: {{ format(item.range.low) }} – {{ format(item.range.high) }}</p></li></ul>
      <p v-else>{{ L('案例未标记未解决假设；这不代表模型已校准。', 'The case marks no unresolved assumptions; this does not establish model calibration.') }}</p>
      <details><summary>{{ L('目标区域频数（诊断）', 'Outcome-region frequencies (diagnostic)') }}</summary><pre>{{ pretty(result.simulation.scenarioShares) }}</pre></details>
      <details><summary>{{ L('敏感性', 'Sensitivity') }}</summary><pre>{{ pretty(result.simulation.sensitivity) }}</pre></details>
      <details><summary>{{ L('可观察信号', 'Observable signposts') }}</summary><pre>{{ pretty(result.simulation.signposts) }}</pre></details>
    </template>
  </section>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'
import service from '../../api/index'
import { L } from '../../i18n'

const props = defineProps({ pipelineId: { type: String, default: '' }, simulationId: { type: String, default: '' }, stageStatus: { type: String, default: '' } })
const loading = ref(false)
const error = ref('')
const result = ref(null)
const selectedPathId = ref('')
let requestId = 0
const paths = computed(() => result.value?.simulation.paths || [])
const targetLabel = computed(() => result.value?.nodes.find(node => node.nodeId === result.value.resolution.targetNodeId)?.label || result.value?.resolution.targetNodeId || '')
const selectedPath = computed(() => paths.value.find(path => path.pathId === selectedPathId.value) || paths.value[0])
const distribution = computed(() => {
  const values = paths.value.map(path => path.targetValue).sort((a, b) => a - b)
  const middle = Math.floor(values.length / 2)
  return { min: values[0], max: values[values.length - 1], median: values.length ? values.length % 2 ? values[middle] : (values[middle - 1] + values[middle]) / 2 : null }
})
const meterMin = computed(() => distribution.value.min ?? 0)
const meterMax = computed(() => distribution.value.max === meterMin.value ? meterMin.value + 1 : distribution.value.max ?? 1)
const assumptions = computed(() => !result.value ? [] : [
  ...result.value.nodes.filter(node => node.status !== 'settled' || node.basis === 'assumed').map(node => ({ id: `node:${node.nodeId}`, label: node.label || node.nodeId, status: node.status, gap: node.gap, range: node.range })),
  ...result.value.mechanisms.filter(mechanism => mechanism.basis !== 'observed').map(mechanism => ({ id: `mechanism:${mechanism.mechanismId}`, label: mechanism.mechanismId, status: mechanism.basis, gap: mechanism.gap })),
  ...(result.value.simulation.parameterBases || []).filter(parameter => parameter.parameter && parameter.basis !== 'observed').map(parameter => ({
    id: `parameter:${parameter.mechanismId || parameter.nodeId}:${parameter.parameter}`,
    label: `${parameter.mechanismId || parameter.nodeId}.${parameter.parameter}`, status: parameter.basis,
    gap: parameter.gap, range: { low: parameter.low, high: parameter.high },
  })),
])
function format(value) { return typeof value === 'number' && Number.isFinite(value) ? String(value) : L('未知', 'Unknown') }
function pretty(value) { return value == null ? L('未提供', 'Not supplied') : JSON.stringify(value, null, 2) }

async function load() {
  const generation = ++requestId
  const { pipelineId, simulationId } = props
  result.value = null
  error.value = ''
  loading.value = false
  if (!pipelineId || !simulationId) return
  if (!/^pipe_[A-Za-z0-9_-]{1,100}$/.test(pipelineId) || !/^sim_[A-Za-z0-9_-]{1,100}$/.test(simulationId)) {
    error.value = L('无效的管线或模拟标识。', 'Invalid pipeline or simulation identifier.')
    return
  }
  loading.value = true
  try {
    const response = await service({ url: `/api/simulation/${encodeURIComponent(simulationId)}/target`, method: 'get', params: { pipeline_id: pipelineId } })
    if (generation !== requestId) return
    const data = response?.data
    const simulation = data?.simulation
    if (response?.success !== true || data?.pipelineId !== pipelineId || data?.simulationId !== simulationId ||
        data?.forecastAuthority !== 'target-first-v1' || !data?.caseId || !data?.caseHash ||
        simulation?.schemaVersion !== 'target-simulation/v1' || simulation?.simulationWeight !== 0 ||
        simulation?.caseId !== data.caseId || simulation?.caseHash !== data.caseHash ||
        !data.resolution?.targetNodeId || !Array.isArray(data.nodes) || !Array.isArray(data.mechanisms) ||
        (simulation.parameterBases != null && (!Array.isArray(simulation.parameterBases) || simulation.parameterBases.some(row => !row || typeof row !== 'object'))) ||
        !Array.isArray(simulation.paths) || !simulation.paths.length || simulation.paths.some(path =>
          !path || typeof path.pathId !== 'string' || !Number.isFinite(path.targetValue) || !Array.isArray(path.trajectory))) {
      throw new Error(L('目标诊断身份或数据校验失败。', 'Target diagnostics failed identity or data validation.'))
    }
    result.value = data
    selectedPathId.value = simulation.paths[0].pathId
  } catch (err) {
    if (generation !== requestId) return
    error.value = err?.response?.status === 404
      ? L('目标诊断尚未就绪。运行完成后刷新。', 'Target diagnostics are not available yet. Refresh after the run completes.')
      : err?.message || L('目标诊断读取失败。', 'Unable to read target diagnostics.')
  } finally {
    if (generation === requestId) loading.value = false
  }
}
watch(() => [props.pipelineId, props.simulationId, props.stageStatus], load, { immediate: true, flush: 'sync' })
onUnmounted(() => { requestId += 1 })
</script>

<style scoped>
.target-view { padding: 20px; color: #252525; }
.target-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h2 { font-size: 1.1rem; } h3 { margin-top: 24px; font-size: 1rem; }
.weight-notice { border-left: 3px solid #c64918; background: #fff5ef; padding: 12px; line-height: 1.6; }
.identity { font-size: 12px; color: #666; overflow-wrap: anywhere; }
.summary { display: flex; flex-wrap: wrap; gap: 24px; } .summary dd { margin: 6px 0; font-weight: 600; }
.table-wrap { overflow: auto; max-height: 320px; margin: 12px 0; }
table { border-collapse: collapse; width: 100%; text-align: left; font-size: 13px; }
caption { text-align: left; margin-bottom: 8px; color: #666; } th, td { padding: 8px; border-bottom: 1px solid #e5e5e5; }
meter { width: 100%; min-width: 70px; } select, button { padding: 6px 10px; }
.assumptions { padding-left: 22px; } .assumptions li { padding: 8px 0; } .assumptions p { margin: 5px 0; }
details { margin: 14px 0; } summary { cursor: pointer; } pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 300px; overflow: auto; background: #f7f7f7; padding: 12px; font-size: 12px; }
</style>
