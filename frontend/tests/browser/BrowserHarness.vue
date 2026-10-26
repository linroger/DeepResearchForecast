<script setup>
import { onMounted, ref } from 'vue'
import DossierViewer from '../../src/components/research/DossierViewer.vue'
import ForecastReport from '../../src/components/research/ForecastReport.vue'
import GraphPanel from '../../src/components/GraphPanel.vue'
import SimulationView from '../../src/components/research/SimulationView.vue'
import WorldStatePanel from '../../src/components/research/WorldStatePanel.vue'
import WorldSimulationView from '../../src/components/research/WorldSimulationView.vue'

const tabs = [
  ['dossier', 'Dossier'], ['forecast', 'Forecast'], ['graph', 'Graph'],
  ['oasis', 'OASIS'], ['world-state', 'World state'], ['world', 'World-v1'], ['record', 'Completed record'],
]
const selected = ref('dossier')
const bootstrap = ref(null)
const failure = ref('')
const revision = ref(0)
const maximized = ref(false)
async function reload() {
  failure.value = ''
  try {
    const response = await fetch('/__fixture/bootstrap', { cache: 'no-store' })
    if (!response.ok) throw new Error(`Fixture bootstrap HTTP ${response.status}`)
    const data = await response.json()
    for (const key of ['pipeline', 'report', 'oasis', 'world', 'record']) {
      if (!data.ids?.[key]) throw new Error(`Fixture is missing ids.${key}`)
    }
    if (!data.dossier || !data.graph) throw new Error('Fixture must supply dossier and graph')
    bootstrap.value = data
    revision.value++
  } catch (error) { failure.value = error.message }
}
onMounted(reload)
</script>

<template>
  <main class="fixture-shell" :class="{ maximized }" data-testid="browser-harness" :data-ready="Boolean(bootstrap)">
    <header class="fixture-header">
      <strong>Translation browser acceptance</strong>
      <span>Disposable fixture · controlled CJK provider · no semantic quality claim</span>
      <button data-testid="reload-fixture" type="button" @click="reload">Reload fixture</button>
    </header>
    <nav class="fixture-tabs" aria-label="Fixture surfaces">
      <button v-for="[key, label] in tabs" :key="key" type="button" :data-testid="`tab-${key}`"
        :aria-pressed="selected === key" @click="selected = key">{{ label }}</button>
    </nav>
    <p v-if="failure" role="alert" data-testid="bootstrap-error">{{ failure }}</p>
    <section v-if="bootstrap" :key="`${selected}:${revision}`" class="fixture-surface" :data-testid="`surface-${selected}`">
      <DossierViewer v-if="selected === 'dossier'" :pipeline-id="bootstrap.ids.pipeline" :dossier="bootstrap.dossier" />
      <ForecastReport v-else-if="selected === 'forecast'" :report-id="bootstrap.ids.report" />
      <GraphPanel v-else-if="selected === 'graph'" :graph-data="bootstrap.graph" :loading="false" :current-phase="3"
        :is-simulating="false" @refresh="reload" @toggle-maximize="maximized = !maximized" />
      <SimulationView v-else-if="selected === 'oasis'" :simulation-id="bootstrap.ids.oasis" stage-status="completed" />
      <WorldStatePanel v-else-if="selected === 'world-state'" :simulation-id="bootstrap.ids.oasis" language="en" :poll-ms="0" />
      <WorldSimulationView v-else-if="selected === 'world'" :simulation-id="bootstrap.ids.world" language="en" />
      <SimulationView v-else-if="selected === 'record'" :simulation-id="bootstrap.ids.record" stage-status="completed" />
    </section>
  </main>
</template>

<style>
html, body, #app { margin: 0; min-height: 100%; font-family: Inter, 'Noto Sans SC', sans-serif; color: #111; background: #f3f4f6; }
* { box-sizing: border-box; }
.fixture-shell { padding: 14px; }
.fixture-header { display: flex; gap: 20px; align-items: center; padding: 8px 0 14px; }
.fixture-header span { flex: 1; font-size: 12px; color: #555; }
.fixture-tabs { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.fixture-tabs button, .fixture-header button { font: inherit; padding: 8px 12px; border: 1px solid #bbb; background: white; cursor: pointer; }
.fixture-tabs button[aria-pressed="true"] { color: white; background: #111; }
.fixture-surface { min-height: 800px; height: calc(100vh - 140px); overflow: auto; border: 1px solid #ddd; background: white; }
.fixture-surface > .graph-panel { height: 100%; min-height: 780px; }
.fixture-surface > .world-view, .fixture-surface > .ws-panel { min-height: 700px; }
.maximized .fixture-surface { height: calc(100vh - 140px); }
</style>
