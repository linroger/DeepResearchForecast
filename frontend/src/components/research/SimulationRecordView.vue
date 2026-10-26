<template>
  <section v-if="rec" class="sim-record" :aria-label="L('情景模拟 · 事后记录', 'Scenario simulation · after-action record')">
    <!-- ===== Header card: banner verbatim from the record, identity, health ===== -->
    <header class="rec-head">
      <div class="rec-eyebrow">
        <span class="diamond">◇</span>
        <span class="rec-label mono">{{ L('情景模拟 · 事后记录', 'Scenario simulation · after-action record') }}</span>
        <span class="rec-class mono">{{ L('模拟记录，非证据', 'simulated record, not evidence') }}</span>
      </div>
      <p class="rec-banner">{{ d(rec.banner) }}</p>
      <dl class="rec-meta mono">
        <div><dt>{{ L('引擎', 'engine') }}</dt><dd>{{ rec.engine || '—' }}</dd></div>
        <div><dt>{{ L('时间范围', 'horizon') }}</dt><dd>{{ horizonText }}</dd></div>
        <div><dt>{{ L('时段', 'periods') }}</dt><dd>{{ periodsText }}</dd></div>
        <div><dt>{{ L('语言', 'language') }}</dt><dd>{{ rec.language || '—' }}</dd></div>
      </dl>
      <p class="rec-health mono" :class="{ 'rec-health-bad': unusable }">{{ healthLine }}</p>
      <ul v-if="limits.notes.length" class="rec-notes">
        <li v-for="(note, i) in limits.notes" :key="'note-' + i">{{ d(note) }}</li>
      </ul>
      <div v-if="unusable" class="rec-unusable" role="alert">
        <p class="rec-unusable-text">{{ unusableText }}</p>
        <table class="rec-table rec-health-table">
          <tbody>
            <tr><th scope="row">{{ L('健康状态', 'simulation health') }}</th><td class="mono">{{ d(health.health) }}</td></tr>
            <tr><th scope="row">{{ L('有效性', 'validity') }}</th><td class="mono">{{ d(health.validity) }}</td></tr>
            <tr><th scope="row">{{ L('仲裁失败轮次', 'arbiter-failed rounds') }}</th><td class="mono">{{ dash(health.arbiterFailedRounds) }}</td></tr>
            <tr><th scope="row">{{ L('建模缺口', 'seed gaps') }}</th><td class="mono">{{ dash(health.seedGaps) }}</td></tr>
            <tr><th scope="row">{{ L('自发行动', 'organic actions') }}</th><td class="mono">{{ dash(health.organicActions) }}</td></tr>
            <tr><th scope="row">{{ L('已提交 / 计划时段', 'periods committed / planned') }}</th><td class="mono">{{ dash(health.committed) }} / {{ dash(health.planned) }}</td></tr>
          </tbody>
        </table>
      </div>
    </header>

    <TranslationJobStatus class="rec-translation" :observer="translation.observer" :L="L">
      <span>{{ translation.feedback.value }}</span>
    </TranslationJobStatus>

    <template v-if="!unusable">
      <!-- ===== Period strip: one button per committed period ===== -->
      <div v-if="periods.length" class="rec-strip" role="group" :aria-label="L('选择时段', 'Select a period')">
        <button
          v-for="p in periods"
          :key="'period-' + p.round"
          type="button"
          class="rec-tick mono"
          :class="['st-' + p.arbiterStatus, { selected: p.round === selectedRound }]"
          :aria-pressed="p.round === selectedRound"
          :aria-label="tickLabel(p)"
          :title="p.periodStart && p.periodEnd ? p.periodStart + ' → ' + p.periodEnd : d(p.label)"
          @click="selectPeriod(p.round)"
        >{{ d(p.label) }}</button>
      </div>

      <!-- ===== Selected period ===== -->
      <section v-if="period" class="rec-period" :aria-label="L('所选时段', 'Selected period')">
        <h3 class="rec-period-title">
          <span>{{ L('第', 'Period ') }}{{ period.round }}{{ L('期', '') }} · {{ d(period.label) }}</span>
          <span v-if="period.periodStart && period.periodEnd" class="rec-dates mono">{{ period.periodStart }} → {{ period.periodEnd }}</span>
          <span class="rec-badge mono" :class="'st-' + period.arbiterStatus">{{ L('仲裁', 'arbiter') }}: {{ d(period.arbiterStatus) }}</span>
          <span v-if="period.mechanicalOnly" class="rec-badge mono st-failed">{{ L('仅机械推进', 'mechanical only') }}</span>
        </h3>
        <ul v-if="period.arbiterProblems.length" class="rec-problems">
          <li v-for="(problem, i) in period.arbiterProblems" :key="'ap' + i">
            <span class="warn-dot">▲</span><span>{{ L('仲裁问题', 'arbiter problem') }}: {{ d(problem) }}</span>
          </li>
        </ul>

        <div class="rec-card rec-narrative">
          <div class="rec-card-head">{{ L('仲裁叙事（模拟文本）', 'Arbiter narrative (simulated text)') }}</div>
          <blockquote v-if="period.narrative" class="rec-quote">{{ d(period.narrative) }}</blockquote>
          <p v-else class="rec-empty">{{ L('本时段无仲裁叙事', 'No arbiter narrative for this period') }}</p>
        </div>

        <div class="rec-grid">
          <div class="rec-card">
            <div class="rec-card-head">{{ L('本时段行动', 'Moves this period') }} ({{ period.moves.length }})</div>
            <ul class="rec-list">
              <li v-for="(m, i) in period.moves" :key="'m' + i" class="rec-move">
                <span class="rec-actor">{{ m.actor }}</span>
                <span class="rec-move-desc">{{ d(m.option) }}<template v-if="m.targets.length"> → {{ m.targets.join(', ') }}</template></span>
                <span v-if="m.magnitude !== null" class="rec-mag mono">{{ L('力度', 'magnitude') }} {{ m.magnitude }}</span>
                <q v-if="m.publicStatement" class="rec-stmt">{{ d(m.publicStatement) }}</q>
                <span v-if="m.commitment" class="rec-commit">
                  {{ L('承诺', 'commitment') }}: {{ d(m.commitment.text) }}<template v-if="m.commitment.duePeriods !== null"> · {{ L('到期时段数', 'due in periods') }} {{ m.commitment.duePeriods }}</template><template v-if="m.commitment.due"> · {{ L('到期', 'due') }} {{ m.commitment.due }}</template>
                </span>
                <span v-if="m.terms" class="rec-terms">{{ L('条款', 'terms') }}: {{ d(m.terms) }}</span>
              </li>
              <li v-if="period.heldPosition.length" class="rec-held">
                <span class="rec-kind mono">{{ L('观望', 'held') }}</span><span>{{ period.heldPosition.join(', ') }}</span>
              </li>
              <li v-if="!period.moves.length && !period.heldPosition.length" class="rec-empty">{{ L('本时段无实质行动', 'No consequential move this period') }}</li>
            </ul>
          </div>

          <div class="rec-card">
            <div class="rec-card-head">{{ L('本时段事实变化', 'Facts changed this period') }} ({{ period.factsChanged.length }})</div>
            <table v-if="period.factsChanged.length" class="rec-table">
              <thead>
                <tr>
                  <th scope="col">{{ L('变量', 'Variable') }}</th>
                  <th scope="col">{{ L('变化', 'Change') }}</th>
                  <th scope="col">{{ L('原因', 'Cause') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(f, i) in period.factsChanged" :key="'f' + i">
                  <th scope="row">{{ d(f.variable) }}</th>
                  <td class="mono">{{ quantity(f.from, f.unit) }} → {{ quantity(f.to, f.unit) }}</td>
                  <td>{{ d(f.cause) || '—' }}</td>
                </tr>
              </tbody>
            </table>
            <p v-else class="rec-empty">{{ L('本时段无事实变化', 'No facts changed this period') }}</p>
          </div>

          <div class="rec-card">
            <div class="rec-card-head">
              {{ L('事件、冲击与红线', 'Events, shocks and red lines') }}
              ({{ period.events.length + period.shocksFired.length + period.redLinesCrossed.length }})
            </div>
            <ul class="rec-list">
              <li v-for="(r, i) in period.redLinesCrossed" :key="'rl' + i" class="rec-event ev-red-line">
                <span class="rec-kind mono">{{ L('越过红线', 'red line crossed') }}</span><span>{{ d(r.text) }}<template v-if="r.by"> · {{ L('越线方', 'crossed by') }}: {{ r.by }}</template></span>
              </li>
              <li v-for="(s, i) in period.shocksFired" :key="'sh' + i" class="rec-event ev-shock">
                <span class="rec-kind mono">{{ L('冲击', 'shock') }}</span><span>{{ d(s) }}</span>
              </li>
              <li v-for="(e, i) in period.events" :key="'ev' + i" class="rec-event">
                <span class="rec-kind mono">{{ L('事件', 'event') }}</span><span>{{ d(e) }}</span>
              </li>
              <li v-if="!period.events.length && !period.shocksFired.length && !period.redLinesCrossed.length" class="rec-empty">
                {{ L('本时段无新事件', 'No new events this period') }}
              </li>
            </ul>
          </div>

          <div class="rec-card">
            <div class="rec-card-head">{{ L('要约（按状态）', 'Offers by status') }} ({{ period.offerCount }})</div>
            <div v-for="group in period.offers" :key="'og-' + group.status" class="rec-offer-group">
              <div class="rec-offer-status mono" :class="'offer-' + group.status">{{ d(group.status) }} · {{ group.offers.length }}</div>
              <ul class="rec-list">
                <li v-for="(o, i) in group.offers" :key="'o' + group.status + i" class="rec-offer">
                  <span class="rec-actor">{{ o.from }} → {{ o.to }}</span>
                  <span v-if="o.kind" class="rec-kind mono">{{ d(o.kind) }}</span>
                  <span v-if="o.terms" class="rec-terms">{{ d(o.terms) }}</span>
                </li>
              </ul>
            </div>
            <p v-if="!period.offerCount" class="rec-empty">{{ L('本时段无要约变动', 'No offers moved this period') }}</p>
          </div>

          <div v-if="period.alliances.length" class="rec-card">
            <div class="rec-card-head">{{ L('联盟变动', 'Alliance shifts') }} ({{ period.alliances.length }})</div>
            <ul class="rec-list">
              <li v-for="(a, i) in period.alliances" :key="'al' + i" class="rec-event">
                <span class="rec-kind mono">{{ L('联盟', 'alliance') }}</span><span>{{ d(a) }}</span>
              </li>
            </ul>
          </div>
        </div>

        <div v-if="behaviourText" class="rec-behaviour">
          <span class="rec-badge mono st-behaviour">{{ behaviourText }}</span>
          <span class="rec-note">{{ behaviourNote }}</span>
        </div>
      </section>

      <!-- ===== Overall section ===== -->
      <section class="rec-overall" :aria-label="L('总体', 'Overall')">
        <h3 class="rec-section-title">{{ L('总体：最终状态与种子对比', 'Overall: final state against the seed') }}</h3>
        <div class="rec-grid">
          <div class="rec-card">
            <div class="rec-card-head">{{ L('最终值 vs 种子值', 'Final versus seed values') }} ({{ finalVariables.length }})</div>
            <table v-if="finalVariables.length" class="rec-table">
              <thead>
                <tr>
                  <th scope="col">{{ L('变量', 'Variable') }}</th>
                  <th scope="col">{{ L('种子值', 'Seed') }}</th>
                  <th scope="col">{{ L('最终值', 'Final') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(v, i) in finalVariables" :key="'fv' + i" :class="'dir-' + v.direction">
                  <th scope="row">{{ d(v.name) }}</th>
                  <td class="mono">{{ v.seed }}</td>
                  <td class="mono">{{ v.final }}</td>
                </tr>
              </tbody>
            </table>
            <p v-else class="rec-empty">{{ L('无变量变化记录', 'No variable changes recorded') }}</p>
          </div>

          <div class="rec-card rec-shares">
            <div class="rec-card-head rec-shares-head">
              {{ L('模拟结果份额', 'Simulated outcome shares') }}
              <span class="rec-badge mono st-note">{{ L('模拟份额，非概率', 'simulated share, not a probability') }}</span>
            </div>
            <table v-if="shares.rows.length" class="rec-table rec-shares-table">
              <thead>
                <tr>
                  <th scope="col">{{ L('情景', 'Scenario') }}</th>
                  <th scope="col">{{ L('最终份额', 'Final share') }}</th>
                  <template v-if="shares.hasPaths">
                    <th scope="col">{{ L('路径均值', 'Path mean') }}</th>
                    <th scope="col">p10 – p90</th>
                  </template>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in shares.rows" :key="'share-' + row.name">
                  <th scope="row">{{ d(row.name) }}</th>
                  <td class="mono">{{ row.finalText }}</td>
                  <template v-if="shares.hasPaths">
                    <td class="mono">{{ row.meanText }}<template v-if="row.sdText"> ± {{ row.sdText }}</template></td>
                    <td class="mono">{{ row.spreadText || '—' }}</td>
                  </template>
                </tr>
              </tbody>
            </table>
            <p v-else class="rec-empty">{{ L('记录未含情景份额', 'The record carries no scenario shares') }}</p>
            <p class="rec-note mono">
              <template v-if="shares.hasPaths">{{ L('路径数', 'paths') }} K={{ shares.k }} · </template>
              <template v-if="shares.convergedAt !== null">{{ L('收敛于第', 'converged at period ') }}{{ shares.convergedAt }}{{ L('期', '') }}</template>
              <template v-else>{{ L('未收敛', 'not converged') }}</template>
            </p>
          </div>

          <div class="rec-card">
            <div class="rec-card-head">{{ L('转折点', 'Turning points') }} ({{ turningPoints.length }})</div>
            <ul class="rec-list">
              <li v-for="(tp, i) in turningPoints" :key="'tp' + i" class="rec-event">
                <span class="rec-kind mono">{{ L('第', 'period ') }}{{ tp.round }}{{ L('期', '') }}</span><span>{{ d(tp.why) }}</span>
              </li>
              <li v-if="!turningPoints.length" class="rec-empty">{{ L('未识别转折点', 'No turning point identified') }}</li>
            </ul>
          </div>

          <div class="rec-card">
            <div class="rec-card-head">{{ L('履约记录', 'Track records') }} ({{ trackRecords.length }})</div>
            <ul class="rec-list">
              <li v-for="(r, i) in trackRecords" :key="'tr' + i" class="rec-record" :class="{ 'tr-broken': r.broken > 0, 'tr-lapsed': !r.broken && r.lapsed > 0 }">
                <span class="rec-actor">{{ r.actor }}</span>
                <span class="mono">{{ trackRecordLine(r) }}</span>
              </li>
              <li v-if="!trackRecords.length" class="rec-empty">{{ L('尚无已结算的承诺', 'No commitment resolved') }}</li>
            </ul>
          </div>
        </div>

        <div class="rec-card rec-synthesis">
          <div class="rec-card-head">
            {{ L('综合', 'Synthesis') }}
            <span class="rec-badge mono st-note" :title="L('生成方式', 'generator')">{{ L('生成方式', 'generated by') }}: {{ generatorLabel }}</span>
          </div>
          <p v-for="(para, i) in synthesis.paragraphs" :key="'syn' + i" class="rec-synthesis-text">{{ d(para) }}</p>
          <p v-if="!synthesis.paragraphs.length" class="rec-empty">{{ L('本记录无综合文本', 'No synthesis text in this record') }}</p>
        </div>

        <div class="rec-card rec-limits">
          <div class="rec-card-head">{{ L('局限', 'Limits') }}</div>
          <ul class="rec-list">
            <li class="rec-event">
              <span class="rec-kind mono">{{ L('仲裁', 'arbiter') }}</span>
              <span>{{ L(`仲裁失败 ${dash(limits.arbiterFailedRounds)} 轮`, `${dash(limits.arbiterFailedRounds)} arbiter-failed rounds`) }}</span>
            </li>
            <li v-for="(gap, i) in limits.seedGaps" :key="'gap' + i" class="rec-event">
              <span class="rec-kind mono">{{ L('缺口', 'gap') }}</span><span>{{ d(gap) }}</span>
            </li>
            <li v-if="limits.behaviourNote" class="rec-event">
              <span class="rec-kind mono">{{ L('行为指标', 'behaviour') }}</span><span>{{ d(limits.behaviourNote) }}</span>
            </li>
          </ul>
        </div>
      </section>
    </template>

    <footer class="rec-foot mono">
      {{ rec.simulation_id }}<template v-if="rec.generator_version"> · {{ rec.generator_version }}</template><template v-if="rec.generated_at"> · {{ rec.generated_at }}</template>
    </footer>
  </section>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { locale } from '../../i18n'
import { useSimulationTranslation } from '../../utils/overlayTranslation'
import TranslationJobStatus from '../TranslationJobStatus.vue'
import { simulationRecordTranslationTexts } from '../../utils/simulationRecordTranslation'
import {
  behaviourSummary, defaultPeriodRound, finalVariableRows, formatQuantity, isSimulationRecord, isUnusableRecord,
  limitsOf, recordHealth, recordPeriods, resolvePeriodRound, shareRows, synthesisOf, trackRecordRows, turningPointRows
} from '../../utils/simRecord'

// ADR 0003 (design §3.6 "Dashboard"): the Simulation After-Action Record as the reader
// sees it after a run — one section per committed period, then the overall account.
// Reviewed display prose overlays the gate-passed record; canonical facts and provenance
// remain intact. Shares are shares, never probabilities (gate check G8).
const props = defineProps({
  record: { type: Object, default: null },
  simulationId: { type: String, default: '' },
  generationId: { type: String, default: '' },
  engine: { type: String, default: '' },
  language: { type: String, default: '' },
  // Changes only for an explicit click on the Simulation tab's language control.
  translationRequest: { type: Number, default: 0 }
})

const rec = computed(() => (isSimulationRecord(props.record) ? props.record : null))
const health = computed(() => recordHealth(rec.value))
const unusable = computed(() => isUnusableRecord(rec.value))
const periods = computed(() => recordPeriods(rec.value))
const selectedRound = ref(defaultPeriodRound(periods.value))
const period = computed(() => periods.value.find(p => p.round === selectedRound.value) || null)
const finalVariables = computed(() => finalVariableRows(rec.value))
const shares = computed(() => shareRows(rec.value))
const turningPoints = computed(() => turningPointRows(rec.value))
const trackRecords = computed(() => trackRecordRows(rec.value))
const synthesis = computed(() => synthesisOf(rec.value))
const limits = computed(() => limitsOf(rec.value))
const visibleTexts = computed(() => simulationRecordTranslationTexts(rec.value, selectedRound.value))
const visibleTextSet = computed(() => new Set(visibleTexts.value))
const translation = useSimulationTranslation({
  simulationId: () => rec.value && (!props.simulationId || rec.value.simulation_id === props.simulationId)
    ? (props.simulationId || rec.value.simulation_id) : '',
  language: () => props.language || locale.value,
  context: () => ({ engine: props.engine || rec.value?.engine || '', platform: '', round: selectedRound.value,
    generation_id: props.generationId || '',
    revision: JSON.stringify([rec.value?.config_hash || '', rec.value?.generator_version || '', rec.value?.generated_at || '']),
    view: 'record', surface: 'record', actor_id: '' }),
  texts: () => visibleTexts.value,
})
const L = translation.L
// Identity fallbacks (for example option.id or variable.id) never gain a translated
// spelling, even if a backend map also happens to contain the same source string.
const d = value => visibleTextSet.value.has(value) ? translation.display(value) : (value ?? '')

watch(periods, next => { selectedRound.value = resolvePeriodRound(next, selectedRound.value) })
watch(() => [props.simulationId, props.generationId], () => {
  selectedRound.value = defaultPeriodRound(periods.value)
}, { flush: 'sync' })
// Mount, record arrival, source refresh and period changes are read-only observer
// selections. Never replay an old click when switching back from the live view.
watch(() => props.translationRequest, (next, previous) => {
  if (next > (previous || 0) && translation.lang.value === 'zh') translation.start()
}, { flush: 'post' })

function dash(value) {
  return value === null || value === undefined || value === '' ? '—' : value
}

function quantity(value, unit) {
  return formatQuantity(value, unit)
}

function selectPeriod(round) {
  selectedRound.value = resolvePeriodRound(periods.value, round)
}

function tickLabel(p) {
  const bits = [d(p.label), `${L('仲裁', 'arbiter')} ${d(p.arbiterStatus)}`]
  if (p.factsChanged.length) bits.push(`${p.factsChanged.length} ${L('项事实变化', 'facts changed')}`)
  if (p.redLinesCrossed.length) bits.push(`${p.redLinesCrossed.length} ${L('条红线被越过', 'red lines crossed')}`)
  return bits.join(', ')
}

const horizonText = computed(() => {
  const r = rec.value || {}
  const span = [r.as_of, r.horizon_date].filter(Boolean).join(' → ') || '—'
  return r.calendar_unit ? `${span} · ${d(r.calendar_unit)}` : span
})

const periodsText = computed(() => {
  const h = health.value
  return L(`已提交 ${dash(h.committed)} / 计划 ${dash(h.planned)} 个时段`, `${dash(h.committed)} of ${dash(h.planned)} periods committed`)
})

const healthLine = computed(() => {
  const h = health.value
  return [
    `${L('健康', 'health')} ${d(h.health)}`,
    `${L('有效性', 'validity')} ${d(h.validity)}`,
    L(`仲裁失败 ${dash(h.arbiterFailedRounds)} 轮`, `${dash(h.arbiterFailedRounds)} arbiter-failed rounds`),
    L(`建模缺口 ${dash(h.seedGaps)} 项`, `${dash(h.seedGaps)} seed gaps`),
    L(`自发行动 ${dash(h.organicActions)} 次`, `${dash(h.organicActions)} organic actions`)
  ].join(' · ')
})

const unusableText = computed(() => {
  const h = health.value
  const reason = d(h.validity !== 'valid' ? h.validity : h.health)
  return L(
    `本次推演不可用（状态：${reason}）。记录仅含健康表；未生成叙事，也没有可供阅读的时段账目。`,
    `This exercise was not usable (status: ${reason}). The record carries the health table only; no narrative was generated and there is no period account to read.`
  )
})

const behaviourText = computed(() => behaviourSummary(period.value && period.value.behaviour, {
  moves: L('项行动', 'moves'), responsive: L('项回应上期', 'responsive'), offersAnswered: L('项应答要约', 'offers answered')
}))
const behaviourNote = computed(() => d(limits.value.behaviourNote) || L('文本层面的诊断，非真实性判定', 'textual diagnostic, not a realism verdict'))

const generatorLabel = computed(() => {
  const g = synthesis.value.generator
  if (g === 'llm') return L('有界 LLM 综合（经门禁校验）', 'bounded LLM synthesis (gate-checked)')
  if (g === 'deterministic') return L('确定性模板', 'deterministic template')
  return d(g)
})

function trackRecordLine(r) {
  const bits = [L(`兑现 ${r.kept}`, `kept ${r.kept}`)]
  if (r.lapsed) bits.push(L(`失效 ${r.lapsed}`, `lapsed ${r.lapsed}`))
  if (r.broken) bits.push(L(`违约 ${r.broken}`, `broken ${r.broken}`))
  return bits.join(' · ')
}
</script>

<style scoped>
.rec-translation { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 8px 12px; background: #fff7ed; font-size: 13px; }
.sim-record {
  --orange: #FF4500;
  --border: #E5E5E5;
  --mono: 'JetBrains Mono', monospace;
  --ink: #000;
  --paper: #fff;
  --muted: #666;
  --faint: #999;
  --err: #b91c1c;
  --warn: #d97706;
  --soft: #FAFAFA;
  display: flex;
  flex-direction: column;
  gap: 14px;
  color: var(--ink);
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
}
.sim-record * { box-sizing: border-box; }
.mono { font-family: var(--mono); }
.diamond { color: var(--orange); font-size: 12px; line-height: 1; }

/* ===== Header card ===== */
.rec-head {
  border: 1px solid var(--border);
  border-left: 3px solid var(--orange);
  background: var(--soft);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.rec-eyebrow { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.rec-label { font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 600; color: var(--muted); }
.rec-class { font-size: 10px; padding: 1px 7px; border-radius: 999px; border: 1px solid var(--orange); color: var(--orange); }
.rec-banner { margin: 0; font-size: 14px; font-weight: 600; line-height: 1.45; }
.rec-meta { display: flex; flex-wrap: wrap; gap: 6px 18px; margin: 0; font-size: 11.5px; }
.rec-meta div { display: flex; gap: 6px; }
.rec-meta dt { color: var(--faint); }
.rec-meta dd { margin: 0; }
.rec-health { margin: 0; font-size: 11.5px; color: var(--muted); }
.rec-notes { margin: 0; padding-left: 18px; font-size: 12.5px; line-height: 1.5; }
.rec-health-bad { color: var(--err); }
.rec-unusable { border: 1px solid var(--err); background: #FEF2F2; padding: 10px 12px; }
.rec-unusable-text { margin: 0 0 8px; color: var(--err); font-weight: 600; font-size: 13px; }

/* ===== Period strip ===== */
.rec-strip { display: flex; flex-wrap: wrap; gap: 6px; }
.rec-tick {
  appearance: none; cursor: pointer; font-size: 11px; padding: 3px 9px; border-radius: 4px;
  border: 1px solid var(--border); background: var(--paper); color: var(--ink);
}
.rec-tick:hover { border-color: var(--ink); }
.rec-tick.selected { background: var(--ink); color: var(--paper); border-color: var(--ink); }
.rec-tick.st-failed, .rec-tick.st-invalid { border-color: var(--err); color: var(--err); }
.rec-tick.st-failed.selected, .rec-tick.st-invalid.selected { background: var(--err); color: var(--paper); }
.rec-tick.st-skipped { border-color: var(--warn); color: var(--warn); }

/* ===== Period and overall sections ===== */
.rec-period, .rec-overall { display: flex; flex-direction: column; gap: 10px; }
.rec-period-title, .rec-section-title { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 0; font-size: 15px; font-weight: 600; }
.rec-dates { font-size: 11px; color: var(--muted); }
.rec-badge { font-size: 11px; padding: 2px 7px; border-radius: 999px; border: 1px solid var(--border); font-weight: 500; }
.rec-badge.st-applied { border-color: #16a34a; color: #15803d; }
.rec-badge.st-failed, .rec-badge.st-invalid { border-color: var(--err); color: var(--err); }
.rec-badge.st-skipped { border-color: var(--warn); color: var(--warn); }
.rec-badge.st-note { opacity: 0.75; }
.rec-badge.st-behaviour { border-color: #1d4ed8; color: #1d4ed8; }
.rec-problems { margin: 0; padding: 0; list-style: none; font-size: 12px; color: var(--err); }
.rec-problems li { display: flex; gap: 6px; }
.warn-dot { color: var(--warn); }
.rec-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 10px; }
.rec-card { border: 1px solid var(--border); background: var(--paper); padding: 10px 12px; }
.rec-card-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); font-weight: 600; margin-bottom: 8px; }
.rec-narrative { border-left: 3px solid var(--orange); }
.rec-quote { margin: 0; padding: 0 0 0 10px; border-left: 2px solid var(--border); font-size: 13.5px; line-height: 1.55; }
.rec-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 6px; font-size: 12.5px; }
.rec-move, .rec-offer, .rec-record, .rec-event, .rec-held { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: baseline; }
.rec-actor { font-weight: 600; }
.rec-move-desc { color: var(--ink); }
.rec-mag { font-size: 10.5px; color: var(--faint); }
.rec-stmt { display: block; width: 100%; color: var(--muted); font-style: italic; }
.rec-commit { display: block; width: 100%; font-size: 12px; color: #1d4ed8; }
.rec-kind { font-size: 10px; padding: 1px 6px; border: 1px solid var(--border); border-radius: 3px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
.ev-red-line .rec-kind { border-color: var(--err); color: var(--err); }
.ev-shock .rec-kind { border-color: var(--warn); color: var(--warn); }
.rec-offer-group { margin-bottom: 8px; }
.rec-offer-status { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin-bottom: 4px; }
.rec-offer-status.offer-accepted { color: #15803d; }
.rec-offer-status.offer-breached, .rec-offer-status.offer-rejected { color: var(--err); }
.rec-offer-status.offer-lapsed { color: var(--warn); }
.rec-terms { display: block; width: 100%; color: var(--muted); font-size: 12px; }
.rec-record.tr-broken .rec-actor { color: var(--err); }
.rec-record.tr-lapsed .rec-actor { color: var(--warn); }
.rec-behaviour { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 12px; }
.rec-note { color: var(--faint); font-size: 11.5px; margin: 6px 0 0; }
.rec-empty { margin: 0; color: var(--faint); font-size: 12px; }

/* ===== Tables ===== */
.rec-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.rec-table th, .rec-table td { text-align: left; padding: 4px 8px 4px 0; border-bottom: 1px solid var(--border); vertical-align: top; }
.rec-table thead th { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); font-weight: 600; }
.rec-table tbody th { font-weight: 500; }
.rec-table tr.dir-up td { color: #15803d; }
.rec-table tr.dir-down td { color: var(--err); }
.rec-health-table th { width: 55%; color: var(--muted); font-weight: 500; }

/* ===== Synthesis / limits / footer ===== */
.rec-synthesis-text { margin: 0 0 8px; font-size: 13.5px; line-height: 1.55; }
.rec-foot { font-size: 10.5px; color: var(--faint); }
</style>
