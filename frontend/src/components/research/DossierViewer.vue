<template>
  <div class="dossier-viewer">
    <!-- Segmented tab toggle -->
    <div class="tabs" role="tablist">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        role="tab"
        class="tab"
        :class="{ active: activeTab === tab.key }"
        :aria-selected="activeTab === tab.key"
        @click="activeTab = tab.key"
      >
        <span class="tab-label">{{ tab.label }}</span>
        <span v-if="tab.count !== null" class="tab-count">{{ tab.count }}</span>
      </button>
    </div>

    <!-- 研究报告 -->
    <section v-show="activeTab === 'report'" class="panel" role="tabpanel">
      <div class="panel-head">
        <span class="diamond">◇</span>{{ L('研究报告', 'Research Report') }}
        <!-- BILINGUAL：原文/译文切换 + PDF 下载（与预测报告一致，degrade-safe） -->
        <span v-if="hasReport && !editing && pipelineId" class="report-lang-actions">
          <span class="lang-toggle" role="group" :aria-label="L('语言', 'Language')">
            <button
              type="button"
              class="lang-btn"
              :class="{ active: activeReportLang === null }"
              :aria-pressed="activeReportLang === null"
              :disabled="reportLangLoading"
              @click="switchReportLang(null)"
            >{{ L('原文', 'Source') }}</button>
            <button
              type="button"
              class="lang-btn"
              :class="{ active: activeReportLang === targetLang }"
              :aria-pressed="activeReportLang === targetLang"
              :disabled="reportLangLoading"
              @click="switchReportLang(targetLang)"
            >{{ targetLang === 'zh' ? '中文' : 'EN' }}</button>
          </span>
          <button
            v-if="showGenerateTranslation"
            type="button"
            class="edit-btn"
            :disabled="translationBusy"
            :title="translationIssues.join('; ')"
            @click="generateResearchTranslation"
          >{{ translationButtonLabel }}</button>
          <span v-if="translationFeedback" class="report-lang-feedback" aria-live="polite">{{ translationFeedback }}</span>
          <a
            class="edit-btn"
            :href="researchPdfHref"
            target="_blank"
            rel="noopener"
            :class="{ disabled: pdfDisabled }"
            :aria-disabled="pdfDisabled"
            @click="onPdfClick"
          >{{ L('下载 PDF', 'Download PDF') }}</a>
        </span>
        <!-- T5.4: 编辑入口（仅可编辑时显示；封存的研究只读，编辑会在「继续」时被重跑覆盖） -->
        <span v-if="editable && hasReport" class="edit-actions">
          <span v-if="sealed" class="edit-sealed" :title="L('该研究已被校验和清单与 judge/actor 血缘封存。直接编辑会在「继续」时被判定为篡改并重跑综合，因此不可编辑。如需修改，请用修订后的问题重新发起研究。', 'This research is sealed by a checksum manifest and judge/actor lineage. An in-place edit would be rejected on Continue and synthesis would re-run over it, so editing is disabled. To change it, start a new research run with a refined question.')">🔒 {{ L('已封存 · 只读', 'Sealed · read-only') }}</span>
          <button v-else-if="!editing" type="button" class="edit-btn" @click="startEdit">✎ {{ L('编辑', 'Edit') }}</button>
          <template v-else>
            <button type="button" class="edit-btn ghost" @click="cancelEdit" :disabled="saving">{{ L('取消', 'Cancel') }}</button>
            <button type="button" class="edit-btn primary" @click="saveAndContinue" :disabled="saving">
              {{ saving ? L('保存中…', 'Saving…') : L('保存并继续 →', 'Save & Continue →') }}
            </button>
          </template>
        </span>
      </div>
      <div class="panel-body">
        <div v-if="editing" class="edit-wrap">
          <p class="edit-hint">{{ L('编辑研究报告后「保存并继续」将以新内容重建图谱并运行完整管线。', 'After editing, “Save & Continue” rebuilds the graph from the new content and runs the full pipeline.') }}</p>
          <textarea v-model="editReport" class="edit-textarea" rows="24"></textarea>
          <p v-if="saveError" class="edit-error">{{ saveError }}</p>
        </div>
        <div v-else-if="hasReport" class="md-body" v-html="renderedReport"></div>
        <div v-else class="empty">
          <div class="empty-icon">◇</div>
          <div class="empty-title">{{ L('暂无研究报告', 'No research report yet') }}</div>
          <div class="empty-sub">{{ L('research_report.md 尚未生成或为空。', 'research_report.md has not been generated or is empty.') }}</div>
        </div>
      </div>
    </section>

    <!-- 关键参与者 -->
    <section v-show="activeTab === 'actors'" class="panel" role="tabpanel">
      <div class="panel-head"><span class="diamond">◇</span>{{ L('关键参与者', 'Key Actors') }}</div>
      <div class="panel-body">
        <template v-if="actorList.length">
          <!-- central question + as-of date -->
          <div v-if="centralQuestion || asOfDate" class="meta-row">
            <div v-if="centralQuestion" class="meta-question">
              <span class="meta-label">{{ L('核心问题', 'Central Question') }}</span>
              <span class="meta-text">{{ centralQuestion }}</span>
            </div>
            <div v-if="asOfDate" class="meta-date">{{ L('截至', 'As of') }} {{ asOfDate }}</div>
          </div>

          <div class="actor-grid">
            <article v-for="(actor, idx) in actorList" :key="actorKey(actor, idx)" class="actor-card">
              <header class="actor-head">
                <span class="actor-name">{{ actorName(actor) }}</span>
                <span class="influence-pill" :class="influenceClass(actor.influence)">
                  {{ influenceLabel(actor.influence) }}
                </span>
              </header>
              <div v-if="actor.type" class="type-badge">{{ actor.type }}</div>
              <div v-if="actor.role" class="actor-role">{{ actor.role }}</div>
              <div v-if="actor.stance" class="actor-stance" :title="actor.stance">{{ actor.stance }}</div>
              <div v-if="actor.memory" class="actor-memory" :title="actor.memory">{{ actor.memory }}</div>
            </article>
          </div>

          <!-- key events timeline -->
          <div v-if="keyEvents.length" class="sub-block">
            <div class="sub-label">{{ L('关键事件', 'Key Events') }}</div>
            <ul class="timeline">
              <li v-for="(ev, i) in keyEvents" :key="'ev' + i" class="timeline-item">
                <span class="timeline-date">{{ ev.date || '—' }}</span>
                <span class="timeline-event">{{ ev.event }}</span>
              </li>
            </ul>
          </div>

          <!-- hot topics chips -->
          <div v-if="hotTopics.length" class="sub-block">
            <div class="sub-label">{{ L('热点话题', 'Hot Topics') }}</div>
            <div class="chips">
              <span v-for="(topic, i) in hotTopics" :key="'topic' + i" class="chip">{{ topic }}</span>
            </div>
          </div>
        </template>

        <div v-else class="empty">
          <div class="empty-icon">◇</div>
          <div class="empty-title">{{ L('结构化参与者未生成（research_report.md 仍可用）', 'Structured actors not generated (research_report.md still available)') }}</div>
          <div class="empty-sub">{{ L('未在档案中找到结构化的参与者数据。', 'No structured actor data found in the dossier.') }}</div>
        </div>
      </div>
    </section>

    <!-- 局势简报 (T5.1) -->
    <section v-show="activeTab === 'brief'" class="panel" role="tabpanel">
      <div class="panel-head"><span class="diamond">◇</span>{{ L('局势简报', 'Situation Brief') }}</div>
      <div class="panel-body">
        <div v-if="briefFields.length" class="brief-blocks">
          <div v-for="(f, i) in briefFields" :key="'bf' + i" class="brief-block">
            <div class="sub-label">{{ f.label }}</div>
            <p v-if="f.text" class="brief-text">{{ f.text }}</p>
            <ul v-else-if="f.list" class="brief-list">
              <li v-for="(item, j) in f.list" :key="'bl' + i + '-' + j">{{ item }}</li>
            </ul>
          </div>
        </div>
        <div v-else class="empty">
          <div class="empty-icon">◇</div>
          <div class="empty-title">{{ L('暂无局势简报', 'No situation brief yet') }}</div>
        </div>
      </div>
    </section>

    <!-- 关系网 (T5.1) -->
    <section v-show="activeTab === 'relationships'" class="panel" role="tabpanel">
      <div class="panel-head"><span class="diamond">◇</span>{{ L('关系网', 'Relationships') }}</div>
      <div class="panel-body">
        <template v-if="relationships.length">
          <div class="sources-count">{{ L('共', 'Total') }} {{ relationships.length }} {{ L('条关系', 'relationships') }}</div>
          <ul class="rel-list">
            <li v-for="(rel, i) in relationships" :key="'rel' + i" class="rel-item">
              <span class="rel-node">{{ rel.source }}</span>
              <span class="rel-edge" :class="relSignClass(rel)">
                {{ relTypeLabel(rel.type) }}
                <span v-if="rel.strength" class="rel-strength">· {{ rel.strength }}</span>
              </span>
              <span class="rel-arrow">→</span>
              <span class="rel-node">{{ rel.target }}</span>
              <span v-if="rel.basis" class="rel-basis" :title="rel.basis">{{ rel.basis }}</span>
            </li>
          </ul>
        </template>
        <div v-else class="empty">
          <div class="empty-icon">◇</div>
          <div class="empty-title">{{ L('暂无关系数据', 'No relationship data') }}</div>
        </div>
      </div>
    </section>

    <!-- Prediction-market signals remain useful even without an exact forecast anchor. -->
    <section v-show="activeTab === 'markets'" class="panel" role="tabpanel">
      <div class="panel-head"><span class="diamond">◇</span>{{ L('预测市场信号', 'Prediction-market Signals') }}</div>
      <div class="panel-body">
        <template v-if="marketList.length">
          <div class="market-meta">
            <span>{{ L('快照时间', 'Snapshot') }}: {{ marketAsOf || '—' }}</span>
            <span>{{ L('仅作校准锚点，并非真值', 'Calibration anchors, not ground truth') }}</span>
          </div>
          <div class="market-grid">
            <article v-for="market in marketList" :key="market.market_id" class="market-card">
              <a :href="marketUrl(market)" target="_blank" rel="noopener" class="market-question">
                {{ market.question || market.event_title || market.market_id }}
              </a>
              <div class="market-prob">{{ formatProbability(market.implied_yes_prob) }}</div>
              <div class="market-detail">
                <span>{{ L('成交量', 'Volume') }} {{ formatUsd(market.volume) }}</span>
                <span v-if="market.end_date">{{ L('截止', 'Ends') }} {{ String(market.end_date).slice(0, 10) }}</span>
              </div>
            </article>
          </div>
        </template>
        <div v-else class="empty">
          <div class="empty-icon">◇</div>
          <div class="empty-title">{{ marketEmptyTitle }}</div>
          <div class="empty-sub">{{ marketEmptyDetail }}</div>
        </div>
      </div>
    </section>

    <!-- 信息来源 -->
    <section v-show="activeTab === 'sources'" class="panel" role="tabpanel">
      <div class="panel-head"><span class="diamond">◇</span>{{ L('信息来源', 'Sources') }}</div>
      <div class="panel-body">
        <template v-if="sourceList.length">
          <div class="sources-count">{{ L('共', 'Total') }} {{ sourceList.length }} {{ L('条来源', 'sources') }}</div>
          <ul class="source-list">
            <li v-for="(src, i) in sourceList" :key="'src' + i" class="source-item">
              <span class="source-idx">{{ i + 1 }}</span>
              <a
                :href="sourceHref(src)"
                target="_blank"
                rel="noopener"
                class="source-link"
              >{{ sourceTitle(src) }}</a>
            </li>
          </ul>
        </template>
        <div v-else class="empty">
          <div class="empty-icon">◇</div>
          <div class="empty-title">{{ L('暂无信息来源', 'No sources yet') }}</div>
          <div class="empty-sub">{{ L('该档案未附带可引用的来源链接。', 'This dossier has no citable source links attached.') }}</div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { renderMarkdown } from '../../utils/markdown'
import { L } from '../../i18n'
import {
  editDossier, researchChartUrl,
  requestResearchTranslation, getResearchTranslation, researchPdfUrl,
} from '../../api/research'
import { detectTranslationTarget } from '../../utils/researchTranslation'
import { marketLookupIncomplete } from '../../utils/marketStatus'

const props = defineProps({
  dossier: {
    type: Object,
    default: null
  },
  // T5.4: 可编辑（仅完成的 research_only）时传入 pipelineId + editable
  pipelineId: { type: String, default: '' },
  editable: { type: Boolean, default: false }
})

const emit = defineEmits(['saved-continue'])

const activeTab = ref('report')

// ---- BILINGUAL: research-report language toggle + PDF ---------------------
// activeReportLang: null = source markdown; otherwise the translated target code.
const activeReportLang = ref(null)
const researchLangCache = ref({})   // { lang: translated markdown }
const reportLangLoading = ref(false)
const translationBusy = ref(false)
const translationStatus = ref('')   // '' | generating | available | failed | unavailable
const translationIssues = ref([])
let researchLangVersion = 0
let translationPollTimer = null

function stopTranslationPolling() {
  if (translationPollTimer) {
    clearTimeout(translationPollTimer)
    translationPollTimer = null
  }
}

// Source-language sniff → the translation target is the OTHER language.
const targetLang = computed(() =>
  detectTranslationTarget((props.dossier && props.dossier.report) || '')
)

// ---- T5.4: edit-and-continue ----
// Sealed research (research_contract_manifest.json) is read-only: the backend
// refuses the edit, because Continue would otherwise re-run synthesis over it.
const sealed = computed(() => !!(props.dossier && props.dossier.sealed))
const editing = ref(false)
const editReport = ref('')
const saving = ref(false)
const saveError = ref('')

function startEdit() {
  editReport.value = (props.dossier && props.dossier.report) || ''
  saveError.value = ''
  editing.value = true
}
function cancelEdit() {
  editing.value = false
  saveError.value = ''
}
async function saveAndContinue() {
  if (saving.value || !props.pipelineId) return
  saving.value = true
  saveError.value = ''
  try {
    await editDossier(props.pipelineId, { report: editReport.value })
    editing.value = false
    emit('saved-continue')
  } catch (e) {
    saveError.value = (e && e.message) || L('保存失败', 'Save failed')
  } finally {
    saving.value = false
  }
}

// ---- Safe accessors ------------------------------------------------------

// dossier.actors is the structured-actors container { actors:[...], key_events:[...], ... }
const actorsContainer = computed(() => {
  const a = props.dossier && props.dossier.actors
  return a && typeof a === 'object' ? a : null
})

const actorList = computed(() => {
  const c = actorsContainer.value
  return c && Array.isArray(c.actors) ? c.actors.filter(Boolean) : []
})

// T5.2: 优先用一等公民 dossier.timeline（timeline.json），否则回退 actors.key_events
const keyEvents = computed(() => {
  const tl = props.dossier && props.dossier.timeline
  if (Array.isArray(tl) && tl.length) {
    return tl.filter(ev => ev && (ev.event || ev.date))
  }
  const c = actorsContainer.value
  if (!c || !Array.isArray(c.key_events)) return []
  return c.key_events.filter(ev => ev && (ev.event || ev.date))
})

// T5.1: 局势简报（仅在存在时渲染）
const situationBrief = computed(() => {
  const c = actorsContainer.value
  const sb = c && c.situation_brief
  return sb && typeof sb === 'object' ? sb : null
})

const briefFields = computed(() => {
  const sb = situationBrief.value
  if (!sb) return []
  const out = []
  const push = (label, key) => {
    const v = sb[key]
    if (typeof v === 'string' && v.trim()) out.push({ label, text: v.trim(), list: null })
    else if (Array.isArray(v) && v.length) out.push({ label, text: null, list: v.filter(x => x != null && String(x).trim() !== '') })
  }
  push(L('当前态势', 'Current Situation'), 'current_situation')
  push(L('来龙去脉', 'Context'), 'context')
  push(L('张力 / 动态', 'Dynamics'), 'dynamics')
  push(L('争议断层', 'Fault Lines'), 'fault_lines')
  push(L('潜在触发', 'Catalysts'), 'catalysts')
  return out
})

// T5.1: 关系图（source --[type]--> target，仅端点都在 actors 内时已由后端筛过；此处只渲染）
const relationships = computed(() => {
  const c = actorsContainer.value
  if (!c || !Array.isArray(c.relationships)) return []
  return c.relationships.filter(r => r && r.source && r.target && r.type)
})

const hotTopics = computed(() => {
  const c = actorsContainer.value
  if (!c || !Array.isArray(c.hot_topics)) return []
  return c.hot_topics.filter(t => t != null && String(t).trim() !== '')
})

const centralQuestion = computed(() => {
  const c = actorsContainer.value
  return c && c.central_question ? String(c.central_question) : ''
})

const asOfDate = computed(() => {
  const c = actorsContainer.value
  return c && c.as_of_date ? String(c.as_of_date) : ''
})

// sources may be an array, or { sources:[...] }, or null
const sourceList = computed(() => {
  const s = props.dossier && props.dossier.sources
  if (!s) return []
  if (Array.isArray(s)) return s.filter(Boolean)
  if (typeof s === 'object' && Array.isArray(s.sources)) return s.sources.filter(Boolean)
  return []
})

const marketContainer = computed(() => {
  const value = props.dossier && props.dossier.prediction_markets
  return value && typeof value === 'object' && !Array.isArray(value) ? value : null
})

const marketList = computed(() => {
  const value = marketContainer.value
  return value && Array.isArray(value.markets)
    ? value.markets.filter(row => row && row.market_id && row.implied_yes_prob != null)
    : []
})

const marketAsOf = computed(() => String((marketContainer.value && marketContainer.value.as_of) || ''))

// A failed, partial or timed-out lookup leaves coverage unknown: never "no market exists".
const marketLookupFailed = computed(() =>
  marketLookupIncomplete(marketContainer.value && marketContainer.value.status))

const marketEmptyTitle = computed(() => {
  if (marketLookupFailed.value) {
    return L('市场数据暂不可用', 'Market data unavailable')
  }
  return L('未找到足够相关且流动的市场', 'No sufficiently relevant liquid market found')
})

const marketEmptyDetail = computed(() => {
  if (!marketContainer.value) return L('该研究运行没有市场快照。', 'This research run has no market snapshot.')
  if (marketLookupFailed.value) {
    return L('本轮市场查询失败或不完整，覆盖情况未知；这不表示不存在相关市场。',
      'The market lookup failed or was incomplete this run, so coverage is unknown; this does not mean no market exists.')
  }
  return L('这表示没有可用的外部市场锚点，并非研究阶段失败。', 'This means no usable external market anchor was found; it is not a research failure.')
})

const citationTitles = computed(() => {
  const out = {}
  sourceList.value.forEach((source, index) => {
    if (!source || typeof source !== 'object') return
    out[`S${index + 1}`] = String(source.title || source.name || source.url || `Source ${index + 1}`)
  })
  return out
})

const hasReport = computed(() => {
  const d = props.dossier
  return !!(d && d.has_report && d.report && String(d.report).trim() !== '')
})

// Active markdown: the cached translation when a target language is selected and
// available, otherwise the source report.  Selecting a not-yet-loaded language shows
// the source until its verified bytes arrive (never another pipeline's translation).
const reportMarkdown = computed(() => {
  const lang = activeReportLang.value
  if (lang && researchLangCache.value[lang]) return researchLangCache.value[lang]
  return (props.dossier && props.dossier.report) || ''
})

const renderedReport = computed(() => {
  if (!hasReport.value) return ''
  try {
    // GATE-W9：研究卷宗的 Visual Annex 内嵌相对 charts/*.png（W9 确定性渲染步产出），
    // 经产物深链端点（chart_<文件名>，原始字节直出）解析；无 pipelineId 时优雅降级。
    return renderMarkdown(reportMarkdown.value, {
      resolveUrl: (rel) => researchChartUrl(props.pipelineId, rel),
      citations: citationTitles.value
    })
  } catch (e) {
    return ''
  }
})

const showGenerateTranslation = computed(() => {
  // Offer generate/retry only when the target variant is not currently available.
  if (activeReportLang.value !== targetLang.value) return false
  return translationStatus.value !== 'available'
    && !researchLangCache.value[targetLang.value]
})

const translationButtonLabel = computed(() => {
  if (translationBusy.value || translationStatus.value === 'generating') {
    return L('翻译中…', 'Translating…')
  }
  if (translationStatus.value === 'failed') return L('重试翻译', 'Retry translation')
  return targetLang.value === 'zh' ? L('生成中文', 'Generate 中文') : L('Generate EN', 'Generate EN')
})

const translationFeedback = computed(() => {
  if (activeReportLang.value !== targetLang.value) return ''
  if (translationStatus.value === 'generating' || translationBusy.value) {
    return L('正在生成译文，请稍候…', 'Generating translation…')
  }
  if (translationStatus.value === 'failed') {
    return L('译文未通过发布审计', 'Translation did not pass the publication audit')
  }
  return ''
})

const pdfDisabled = computed(() => {
  // A language PDF is fail-closed on the audit: only offer it once the variant is ready.
  if (activeReportLang.value && !researchLangCache.value[activeReportLang.value]) return true
  return false
})

const researchPdfHref = computed(() => {
  if (pdfDisabled.value) return 'javascript:void(0)'
  return researchPdfUrl(props.pipelineId, activeReportLang.value || undefined)
})

function onPdfClick(event) {
  if (pdfDisabled.value) event.preventDefault()
}

async function loadResearchTranslation(lang, { trigger = false } = {}) {
  if (!props.pipelineId || !lang) return
  const version = researchLangVersion
  reportLangLoading.value = true
  try {
    const res = await getResearchTranslation(props.pipelineId, lang)
    if (version !== researchLangVersion) return   // report changed mid-flight
    const data = (res && res.data && res.data.data) || {}
    translationStatus.value = data.status || 'unavailable'
    translationIssues.value = Array.isArray(data.issues) ? data.issues : []
    if (data.available && typeof data.report === 'string' && data.report.trim()) {
      researchLangCache.value = { ...researchLangCache.value, [lang]: data.report }
      stopTranslationPolling()
    } else if (trigger && translationStatus.value !== 'generating') {
      await generateResearchTranslation()
    } else if (translationStatus.value === 'generating') {
      scheduleTranslationPoll(lang)
    }
  } catch (e) {
    if (version === researchLangVersion) translationStatus.value = 'unavailable'
  } finally {
    if (version === researchLangVersion) reportLangLoading.value = false
  }
}

function scheduleTranslationPoll(lang) {
  stopTranslationPolling()
  const version = researchLangVersion
  translationPollTimer = setTimeout(() => {
    if (version === researchLangVersion) loadResearchTranslation(lang)
  }, 4000)
}

async function generateResearchTranslation() {
  if (!props.pipelineId || translationBusy.value) return
  const lang = targetLang.value
  translationBusy.value = true
  try {
    const res = await requestResearchTranslation(props.pipelineId, lang)
    const data = (res && res.data && res.data.data) || {}
    translationStatus.value = data.status || 'generating'
    if (data.available) {
      await loadResearchTranslation(lang)
    } else {
      scheduleTranslationPoll(lang)
    }
  } catch (e) {
    translationStatus.value = 'failed'
  } finally {
    translationBusy.value = false
  }
}

function switchReportLang(lang) {
  activeReportLang.value = lang
  if (lang && !researchLangCache.value[lang]) {
    loadResearchTranslation(lang, { trigger: false })
  }
}

// Report-identity guard: clearing the cache and resetting language whenever the
// pipeline changes prevents a second dossier from ever showing the previous
// pipeline's translated bytes (the same stale-variant bug fixed on the forecast view).
watch(
  () => [props.pipelineId, (props.dossier && props.dossier.report) || ''],
  () => {
    researchLangVersion += 1
    stopTranslationPolling()
    activeReportLang.value = null
    researchLangCache.value = {}
    reportLangLoading.value = false
    translationBusy.value = false
    translationStatus.value = ''
    translationIssues.value = []
  },
)

// ---- Tabs ----------------------------------------------------------------

const tabs = computed(() => {
  const t = [
    { key: 'report', label: L('研究报告', 'Research Report'), count: null },
    { key: 'actors', label: L('关键参与者', 'Key Actors'), count: actorList.value.length }
  ]
  // T5.1: 仅在存在时插入 Brief / Relationships 标签
  if (briefFields.value.length) {
    t.push({ key: 'brief', label: L('局势简报', 'Situation Brief'), count: null })
  }
  if (relationships.value.length) {
    t.push({ key: 'relationships', label: L('关系网', 'Relationships'), count: relationships.value.length })
  }
  if (marketContainer.value) {
    t.push({ key: 'markets', label: L('预测市场', 'Markets'), count: marketList.value.length })
  }
  t.push({ key: 'sources', label: L('信息来源', 'Sources'), count: sourceList.value.length })
  return t
})

// 关系类型 → 中英文标签 + 情感色（与 actors.py REL_LABEL 对齐）
const REL_META = {
  ALLY_OF: { zh: '盟友', en: 'Ally', sign: 'ally' },
  PARTNERS_WITH: { zh: '伙伴', en: 'Partner', sign: 'ally' },
  INFLUENCES: { zh: '影响', en: 'Influences', sign: 'neutral' },
  DEPENDS_ON: { zh: '依赖', en: 'Depends on', sign: 'neutral' },
  REGULATES: { zh: '监管', en: 'Regulates', sign: 'neutral' },
  OPPOSES: { zh: '对立', en: 'Opposes', sign: 'rival' },
  COMPETES_WITH: { zh: '竞争', en: 'Competes', sign: 'rival' }
}

function relTypeLabel(type) {
  const m = REL_META[String(type || '').toUpperCase()]
  return m ? L(m.zh, m.en) : String(type || '')
}

function relSignClass(rel) {
  const m = REL_META[String(rel.type || '').toUpperCase()]
  const sign = rel.sign || (m ? m.sign : 'neutral')
  if (sign === 'ally') return 'rel-ally'
  if (sign === 'rival') return 'rel-rival'
  return 'rel-neutral'
}

// ---- Field helpers (defensive) ------------------------------------------

function actorName(actor) {
  if (!actor) return L('未知', 'Unknown')
  return actor.name || actor.user_name || actor.username || L('未知', 'Unknown')
}

function actorKey(actor, idx) {
  return (actor && (actor.name || actor.user_name)) ? `${actor.name || actor.user_name}-${idx}` : `actor-${idx}`
}

function influenceClass(influence) {
  const v = String(influence || '').toLowerCase()
  if (v === 'high' || v === '高') return 'inf-high'
  if (v === 'medium' || v === 'mid' || v === '中') return 'inf-medium'
  if (v === 'low' || v === '低') return 'inf-low'
  return 'inf-unknown'
}

function influenceLabel(influence) {
  const v = String(influence || '').toLowerCase()
  if (v === 'high' || v === '高') return L('高影响', 'High')
  if (v === 'medium' || v === 'mid' || v === '中') return L('中影响', 'Medium')
  if (v === 'low' || v === '低') return L('低影响', 'Low')
  return influence ? String(influence) : L('未知', 'Unknown')
}

function sourceTitle(src) {
  if (!src) return ''
  if (typeof src === 'string') return src
  return src.title || src.url || L('未命名来源', 'Untitled source')
}

function sourceHref(src) {
  if (!src) return '#'
  if (typeof src === 'string') return src
  const url = src.url || src.title
  return url ? String(url) : '#'
}

function marketUrl(market) {
  return String((market && (market.url || market.event_url)) || '#')
}

function formatProbability(value) {
  const number = Number(value)
  return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : '—'
}

function formatUsd(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1
  }).format(number)
}
</script>

<style scoped>
.dossier-viewer {
  --orange: #FF4500;
  --border: #E5E5E5;
  --mono: 'JetBrains Mono', monospace;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
  color: #000;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ---- Segmented tabs ----
   Per-button borders with -1px collapse (instead of a clipping container
   border) so the tab set wraps to extra rows at narrow widths with clean
   separators — previously overflow:hidden made trailing tabs unreachable. */
.tabs {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 0;
  align-self: flex-start;
  padding-top: 1px;
  padding-left: 1px;
  background: #fff;
}

.tab {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  font-family: var(--mono);
  font-size: 12px;
  letter-spacing: 0.04em;
  background: #fff;
  color: #000;
  border: 1px solid var(--border);
  margin: -1px 0 0 -1px;
  cursor: pointer;
  transition: background var(--dur-1, 120ms) var(--ease, ease), color var(--dur-1, 120ms) var(--ease, ease);
}

.tab:hover:not(.active) {
  background: #FAFAFA;
}

.tab.active {
  background: #000;
  border-color: #000;
  color: #fff;
  position: relative; /* keep the dark border above collapsed neighbours */
  z-index: 1;
}

.tab-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  font-size: 11px;
  background: var(--border);
  color: #000;
}

.tab.active .tab-count {
  background: var(--orange);
  color: #fff;
}

/* ---- Panels ---- */
.panel {
  border: 1px solid var(--border);
  border-radius: 2px;
  background: #fff;
}

.panel-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  font-family: var(--mono);
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #000;
  background: #FAFAFA;
}

.diamond {
  color: var(--orange);
  font-size: 12px;
}

.panel-body {
  padding: 20px 22px;
}

/* ---- Empty states ---- */
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 6px;
  padding: 48px 16px;
}

.empty-icon {
  color: var(--orange);
  font-size: 24px;
  margin-bottom: 4px;
}

.empty-title {
  font-size: 14px;
  font-weight: 600;
  color: #000;
}

.empty-sub {
  font-size: 12px;
  color: #999;
  font-family: var(--mono);
}

/* ---- Actors meta row ---- */
.meta-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 18px;
  padding-bottom: 14px;
  border-bottom: 1px dashed var(--border);
}

.meta-question {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1 1 60%;
  min-width: 0;
}

.meta-label {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #999;
}

.meta-text {
  font-size: 14px;
  line-height: 1.6;
  color: #000;
}

.meta-date {
  font-family: var(--mono);
  font-size: 11px;
  color: #666;
  white-space: nowrap;
}

/* ---- Actor grid ---- */
.actor-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 14px;
}

.actor-card {
  border: 1px solid var(--border);
  border-radius: 2px;
  padding: 14px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: transform 0.15s, box-shadow 0.15s;
}

.actor-card:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.actor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.actor-name {
  font-weight: 700;
  font-size: 15px;
  color: #000;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.influence-pill {
  flex-shrink: 0;
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.04em;
  padding: 2px 8px;
  border-radius: 10px;
  white-space: nowrap;
}

.inf-high {
  background: var(--orange);
  color: #fff;
}

.inf-medium {
  background: #fff;
  color: #000;
  border: 1px solid #000;
}

.inf-low {
  background: #F0F0F0;
  color: #666;
}

.inf-unknown {
  background: #F0F0F0;
  color: #999;
}

.type-badge {
  align-self: flex-start;
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 2px 7px;
  background: #000;
  color: #fff;
  border-radius: 2px;
}

.actor-role {
  font-size: 13px;
  color: #000;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.actor-stance {
  font-size: 12px;
  color: #666;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.actor-memory {
  font-size: 11px;
  color: #999;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ---- Sub-blocks (timeline / chips) ---- */
.sub-block {
  margin-top: 22px;
}

.sub-label {
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #999;
  margin-bottom: 10px;
}

.timeline {
  list-style: none;
  margin: 0;
  padding: 0;
  border-left: 1px solid var(--border);
}

.timeline-item {
  position: relative;
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding: 6px 0 6px 16px;
}

.timeline-item::before {
  content: '';
  position: absolute;
  left: -4px;
  top: 11px;
  width: 7px;
  height: 7px;
  background: var(--orange);
  border-radius: 50%;
}

.timeline-date {
  flex-shrink: 0;
  font-family: var(--mono);
  font-size: 11px;
  color: #666;
  min-width: 84px;
}

.timeline-event {
  font-size: 13px;
  color: #000;
  line-height: 1.5;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chip {
  font-size: 12px;
  padding: 4px 12px;
  border: 1px solid var(--orange);
  border-radius: 14px;
  color: var(--orange);
  background: #fff;
  white-space: nowrap;
}

/* ---- Edit & continue (T5.4) ---- */
.edit-actions {
  margin-left: auto;
  display: inline-flex;
  gap: 8px;
}

.edit-btn {
  font-family: var(--mono);
  font-size: 11px;
  padding: 4px 12px;
  border: 1px solid var(--border);
  background: #fff;
  color: #000;
  cursor: pointer;
  border-radius: var(--radius, 2px);
  transition: background var(--dur-1, 120ms) var(--ease, ease), color var(--dur-1, 120ms) var(--ease, ease), border-color var(--dur-1, 120ms) var(--ease, ease);
}

.edit-btn:hover:not(:disabled):not(.primary):not(.disabled) {
  border-color: var(--orange);
  color: var(--orange);
}

.edit-btn.primary {
  background: #000;
  color: #fff;
  border-color: #000;
}

.edit-btn.primary:hover:not(:disabled) {
  background: var(--orange);
  border-color: var(--orange);
}

.edit-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.edit-sealed {
  font-family: var(--mono);
  font-size: 11px;
  color: #666;
  padding: 4px 0;
  cursor: help;
}

.edit-hint {
  font-size: 12px;
  color: #666;
  margin: 0 0 10px;
  line-height: 1.6;
}

/* BILINGUAL: research-report language toggle + PDF controls */
.report-lang-actions {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.report-lang-actions .lang-toggle {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: 2px;
  overflow: hidden;
}

.report-lang-actions .lang-btn {
  font-family: var(--mono);
  font-size: 11px;
  padding: 4px 10px;
  border: none;
  border-right: 1px solid var(--border);
  background: #fff;
  color: #000;
  cursor: pointer;
}

.report-lang-actions .lang-btn:last-child {
  border-right: none;
}

.report-lang-actions .lang-btn.active {
  background: #000;
  color: #fff;
}

.report-lang-actions .lang-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.report-lang-actions .edit-btn {
  text-decoration: none;
  display: inline-flex;
  align-items: center;
}

.report-lang-actions .edit-btn.disabled {
  opacity: 0.5;
  cursor: not-allowed;
  pointer-events: none;
}

.report-lang-feedback {
  font-size: 11px;
  color: #666;
}

.edit-textarea {
  width: 100%;
  font-family: var(--mono);
  font-size: 13px;
  line-height: 1.6;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 2px;
  resize: vertical;
  outline: none;
  box-sizing: border-box;
}

.edit-textarea:focus {
  border-color: var(--orange);
}

.edit-error {
  color: var(--color-err, #B91C1C);
  font-size: 12px;
  font-family: var(--mono);
  margin: 8px 0 0;
}

/* ---- Situation Brief (T5.1) ---- */
.brief-blocks {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.brief-text {
  font-size: 14px;
  line-height: 1.75;
  color: #000;
  margin: 0;
}

.brief-list {
  margin: 0;
  padding-left: 20px;
}

.brief-list li {
  font-size: 13px;
  line-height: 1.7;
  color: #000;
  margin: 3px 0;
}

/* ---- Relationships (T5.1) ---- */
.rel-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.rel-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 0;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}

.rel-item:last-child {
  border-bottom: none;
}

.rel-node {
  font-weight: 600;
  font-size: 14px;
  color: #000;
}

.rel-arrow {
  color: #999;
  font-family: var(--mono);
}

.rel-edge {
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.03em;
  padding: 2px 9px;
  border-radius: 10px;
  white-space: nowrap;
}

.rel-strength {
  opacity: 0.7;
}

.rel-ally {
  background: #fff;
  color: #000;
  border: 1px solid #000;
}

.rel-rival {
  background: var(--orange);
  color: #fff;
}

.rel-neutral {
  background: #F0F0F0;
  color: #666;
}

.rel-basis {
  flex: 1 1 100%;
  font-size: 11px;
  color: #999;
  line-height: 1.5;
  padding-left: 2px;
}

/* ---- Prediction-market signals ---- */
.market-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
  color: #777;
  font-family: var(--mono);
  font-size: 10px;
}

.market-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

.market-card {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 10px 14px;
  align-items: start;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 2px;
}

.market-question {
  color: #000;
  text-decoration: none;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.45;
}

.market-question:hover { color: var(--orange); }

.market-prob {
  color: var(--orange);
  font-family: var(--mono);
  font-size: 20px;
  font-weight: 700;
  white-space: nowrap;
}

.market-detail {
  grid-column: 1 / -1;
  display: flex;
  justify-content: space-between;
  gap: 10px;
  color: #777;
  font-family: var(--mono);
  font-size: 10px;
}

/* ---- Sources ---- */
.sources-count {
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.04em;
  color: #999;
  margin-bottom: 12px;
}

.source-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.source-item {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding: 9px 0;
  border-bottom: 1px solid var(--border);
}

.source-item:last-child {
  border-bottom: none;
}

.source-idx {
  flex-shrink: 0;
  font-family: var(--mono);
  font-size: 11px;
  color: #999;
  min-width: 24px;
}

.source-link {
  color: var(--orange);
  text-decoration: none;
  font-size: 14px;
  line-height: 1.5;
  word-break: break-word;
  transition: text-decoration 0.15s;
}

.source-link:hover {
  text-decoration: underline;
}

/* ---- Markdown body typography ---- */
.md-body {
  font-size: 15px;
  color: #000;
  line-height: 1.85;
  word-wrap: break-word;
}

.md-body :deep(h1) {
  font-family: 'Space Grotesk', system-ui, sans-serif;
  font-size: 28px;
  font-weight: 700;
  line-height: 1.25;
  margin: 28px 0 16px;
}

.md-body :deep(h2) {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.3;
  margin: 26px 0 14px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}

.md-body :deep(h3) {
  font-size: 18px;
  font-weight: 600;
  line-height: 1.35;
  margin: 22px 0 10px;
}

.md-body :deep(h4) {
  font-size: 15px;
  font-weight: 600;
  line-height: 1.4;
  margin: 18px 0 8px;
  color: #333;
}

.md-body :deep(p) {
  margin: 0 0 14px;
  line-height: 1.85;
}

.md-body :deep(ul),
.md-body :deep(ol) {
  margin: 0 0 14px;
  padding-left: 26px;
}

.md-body :deep(li) {
  margin: 4px 0;
  line-height: 1.7;
}

.md-body :deep(blockquote) {
  margin: 16px 0;
  padding: 10px 16px;
  border-left: 3px solid var(--orange);
  background: #FAFAFA;
  color: #444;
}

.md-body :deep(.md-table),
.md-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 16px 0;
  font-size: 13px;
}

.md-body :deep(.md-table th),
.md-body :deep(.md-table td),
.md-body :deep(table th),
.md-body :deep(table td) {
  border: 1px solid var(--border);
  padding: 8px 10px;
  text-align: left;
  vertical-align: top;
}

.md-body :deep(.md-table th),
.md-body :deep(table th) {
  background: #FAFAFA;
  font-weight: 600;
  font-family: var(--mono);
  font-size: 12px;
  letter-spacing: 0.02em;
}

.md-body :deep(code) {
  font-family: var(--mono);
  font-size: 0.88em;
  background: #FAFAFA;
  border: 1px solid var(--border);
  border-radius: 2px;
  padding: 1px 5px;
}

.md-body :deep(pre),
.md-body :deep(.md-pre) {
  margin: 16px 0;
  padding: 14px 16px;
  background: #FAFAFA;
  border: 1px solid var(--border);
  border-radius: 2px;
  overflow-x: auto;
}

.md-body :deep(pre code),
.md-body :deep(.md-pre code) {
  background: none;
  border: none;
  padding: 0;
  font-size: 13px;
  line-height: 1.6;
}

.md-body :deep(a) {
  color: var(--orange);
  text-decoration: none;
}

.md-body :deep(a:hover) {
  text-decoration: underline;
}

.md-body :deep(hr),
.md-body :deep(.md-hr) {
  border: none;
  border-top: 1px solid var(--border);
  margin: 24px 0;
}

.md-body :deep(strong) {
  font-weight: 700;
}

.md-body :deep(img) {
  max-width: 100%;
  height: auto;
}

/* CITE-1（降级形态）：Dossier 不传 citations 映射，[Sxx] 渲染为无链接的纯上标；
   若研究报告自带 References 条目，锚点/标签样式同样适用。 */
.md-body :deep(.md-cite) {
  font-family: var(--mono);
  font-size: 0.68em;
  line-height: 0;
  vertical-align: super;
  margin: 0 1px;
  color: #666;
}
.md-body :deep(.md-cite a) {
  color: var(--orange);
  text-decoration: none;
  padding: 0 2px;
}
.md-body :deep(.md-ref) { scroll-margin-top: 16px; }
.md-body :deep(.md-ref-tag) {
  font-family: var(--mono);
  font-size: 0.76em;
  color: #666;
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 0 5px;
  margin-right: 5px;
  white-space: nowrap;
  background: #FAFAFA;
}
</style>
