<template>
  <div class="graph-panel">
    <div class="panel-header">
      <span class="panel-title"><span class="panel-diamond" aria-hidden="true">◇</span>{{ L('图谱关系可视化', 'Graph Relationship Visualization') }}</span>
      <!-- 顶部工具栏 (Internal Top Right) -->
      <div class="header-tools">
        <!-- 节点搜索：按名称匹配，Enter 循环切换匹配项 -->
        <div v-if="graphData" class="graph-search">
          <input
            type="search"
            class="search-input"
            v-model="searchQuery"
            :placeholder="L('搜索节点', 'Search nodes')"
            :title="L('按名称搜索节点（Enter 切换匹配）', 'Search nodes by name (Enter cycles matches)')"
            @input="onSearchInput"
            @keydown.enter.prevent="onSearchEnter"
          />
          <span v-if="searchQuery" class="search-count">{{ searchCountLabel }}</span>
        </div>
        <!-- 时间过滤：按边的 valid_at 截断（载荷带时间字段时才显示） -->
        <div
          v-if="graphData && timeFilterTimes.length"
          class="time-filter"
          :title="L('按事实生效时间过滤边', 'Filter edges by fact valid time')"
        >
          <span class="time-filter-label">{{ timeFilterLabel }}</span>
          <input
            class="time-filter-slider"
            type="range"
            min="0"
            :max="timeFilterTimes.length"
            step="1"
            v-model.number="timeFilterIndex"
          />
        </div>
        <button class="tool-btn" @click="$emit('refresh')" :disabled="loading" :title="L('刷新图谱', 'Refresh graph')">
          <span class="icon-refresh" :class="{ 'spinning': loading }">↻</span>
          <span class="btn-text">{{ L('刷新', 'Refresh') }}</span>
        </button>
        <button class="tool-btn" :class="{ active: overlayLang === 'zh' }" @click="toggleOverlayLang"
                :disabled="!graphData?.graph_id"
                :title="L('切换中文翻译（节点摘要/边事实）', 'Toggle Chinese translation (node summaries / edge facts)')">
          <span class="btn-text">{{ overlayBusy ? '…' : '中' }}</span>
        </button>
        <button class="tool-btn" @click="$emit('toggle-maximize')" :title="L('最大化/还原', 'Maximize / restore')">
          <span class="icon-maximize">⛶</span>
        </button>
      </div>
    </div>
    
    <TranslationJobStatus v-if="overlayLang === 'zh'" class="graph-translation-status" :observer="overlayObserver" :L="L" />
    <div class="graph-container" ref="graphContainer">
      <!-- 图谱可视化 -->
      <div v-if="graphData" class="graph-view">
        <svg ref="graphSvg" class="graph-svg"></svg>
        
        <!-- 构建中/模拟中提示 -->
        <div v-if="currentPhase === 1 || isSimulating" class="graph-building-hint">
          <div class="memory-icon-wrapper">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="memory-icon">
              <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 4.44-4.04z" />
              <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-4.44-4.04z" />
            </svg>
          </div>
          {{ isSimulating ? L('GraphRAG长短期记忆实时更新中', 'GraphRAG long/short-term memory updating live') : L('实时更新中...', 'Updating live...') }}
        </div>
        
        <!-- 模拟结束后的提示 -->
        <div v-if="showSimulationFinishedHint" class="graph-building-hint finished-hint">
          <div class="hint-icon-wrapper">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="hint-icon">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="16" x2="12" y2="12"></line>
              <line x1="12" y1="8" x2="12.01" y2="8"></line>
            </svg>
          </div>
          <span class="hint-text">{{ L('还有少量内容处理中，建议稍后手动刷新图谱', 'A little content is still processing — refresh the graph manually later') }}</span>
          <button class="hint-close-btn" @click="dismissFinishedHint" :title="L('关闭提示', 'Dismiss hint')">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
        
        <!-- 聚焦模式提示条：大图默认只渲染 Top-K 子图，点击节点可展开邻居 -->
        <div v-if="focusModeActive" class="graph-focus-banner">
          <span class="focus-text">
            {{ L('聚焦模式', 'Focus mode') }}: {{ renderedNodeCount }}/{{ totalNodeCount }}
            {{ L('个节点 · 点击节点展开邻居', 'nodes · click a node to expand neighbors') }}
            <span v-if="expandingNode" class="focus-expanding">{{ L('（展开中…）', '(expanding…)') }}</span>
          </span>
          <button class="focus-btn" @click="loadFullGraph()" :disabled="fullGraphLoading">
            {{ fullGraphLoading ? L('加载中…', 'Loading…') : L('加载完整图谱', 'Load full graph') }}
          </button>
        </div>
        <div v-else-if="fullGraphRequested && totalNodeCount > GRAPH_UI_MAX_NODES" class="graph-focus-banner">
          <span class="focus-text">{{ L('已加载完整图谱', 'Full graph loaded') }} ({{ totalNodeCount }} {{ L('个节点', 'nodes') }})</span>
          <button class="focus-btn" @click="backToFocusMode">{{ L('返回聚焦模式', 'Back to focus mode') }}</button>
        </div>

        <!-- 节点/边详情面板 -->
        <div v-if="selectedItem" class="detail-panel">
          <div class="detail-panel-header">
            <span class="detail-title">{{ selectedItem.type === 'node' ? L('节点详情', 'Node Details') : L('关系', 'Relationship') }}</span>
            <span v-if="selectedItem.type === 'node'" class="detail-type-badge" :style="{ background: selectedItem.color, color: '#fff' }">
              {{ selectedItem.entityType }}
            </span>
            <button class="detail-close" @click="closeDetailPanel">×</button>
          </div>

          <div v-if="selectedItem.detailLoading" class="detail-status">
            {{ L('正在加载完整详情…', 'Loading full details…') }}
          </div>
          <div v-else-if="selectedItem.detailError" class="detail-status detail-error">
            {{ L('完整详情暂时不可用', 'Full details are temporarily unavailable') }}
          </div>
          
          <!-- 节点详情 -->
          <div v-if="selectedItem.type === 'node'" class="detail-content">
            <div class="detail-row">
              <span class="detail-label">{{ L('名称', 'Name') }}:</span>
              <span class="detail-value">{{ selectedItem.data.name }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">UUID:</span>
              <span class="detail-value uuid-text">{{ selectedItem.data.uuid }}</span>
            </div>
            <div class="detail-row" v-if="selectedItem.data.created_at">
              <span class="detail-label">{{ L('创建时间', 'Created') }}:</span>
              <span class="detail-value">{{ formatDateTime(selectedItem.data.created_at) }}</span>
            </div>

            <!-- Properties -->
            <div class="detail-section" v-if="selectedItem.data.attributes && Object.keys(selectedItem.data.attributes).length > 0">
              <div class="section-title">{{ L('属性', 'Properties') }}:</div>
              <div class="properties-list">
                <div v-for="(value, key) in selectedItem.data.attributes" :key="key" class="property-item">
                  <span class="property-key">{{ key }}:</span>
                  <span class="property-value">{{ value || L('无', 'None') }}</span>
                </div>
              </div>
            </div>
            
            <!-- Summary -->
            <div class="detail-section" v-if="selectedItem.data.summary">
              <div class="section-title">{{ L('摘要', 'Summary') }}:</div>
              <div class="summary-text">{{ displayText(`node:${selectedItem.data.uuid}:summary`, selectedItem.data.summary) }}</div>
            </div>

            <!-- Labels -->
            <div class="detail-section" v-if="selectedItem.data.labels && selectedItem.data.labels.length > 0">
              <div class="section-title">{{ L('标签', 'Labels') }}:</div>
              <div class="labels-list">
                <span v-for="label in selectedItem.data.labels" :key="label" class="label-tag">
                  {{ label }}
                </span>
              </div>
            </div>
          </div>
          
          <!-- 边详情 -->
          <div v-else class="detail-content">
            <!-- 自环组详情 -->
            <template v-if="selectedItem.data.isSelfLoopGroup">
              <div class="edge-relation-header self-loop-header">
                {{ selectedItem.data.source_name }} - {{ L('自身关系', 'Self Relations') }}
                <span class="self-loop-count">{{ selectedItem.data.selfLoopCount }} {{ L('条', 'items') }}</span>
              </div>
              
              <div class="self-loop-list">
                <div 
                  v-for="(loop, idx) in selectedItem.data.selfLoopEdges" 
                  :key="loop.uuid || idx" 
                  class="self-loop-item"
                  :class="{ expanded: expandedSelfLoops.has(loop.uuid || idx) }"
                >
                  <div 
                    class="self-loop-item-header"
                    @click="toggleSelfLoop(loop.uuid || idx)"
                  >
                    <span class="self-loop-index">#{{ idx + 1 }}</span>
                    <span class="self-loop-name">{{ loop.name || loop.fact_type || 'RELATED' }}</span>
                    <span class="self-loop-toggle">{{ expandedSelfLoops.has(loop.uuid || idx) ? '−' : '+' }}</span>
                  </div>
                  
                  <div class="self-loop-item-content" v-show="expandedSelfLoops.has(loop.uuid || idx)">
                    <div v-if="loop._detailLoading" class="detail-status">
                      {{ L('正在加载完整详情…', 'Loading full details…') }}
                    </div>
                    <div v-else-if="loop._detailError" class="detail-status detail-error">
                      {{ L('完整详情暂时不可用', 'Full details are temporarily unavailable') }}
                    </div>
                    <div class="detail-row" v-if="loop.uuid">
                      <span class="detail-label">UUID:</span>
                      <span class="detail-value uuid-text">{{ loop.uuid }}</span>
                    </div>
                    <div class="detail-row" v-if="loop.fact">
                      <span class="detail-label">{{ L('事实', 'Fact') }}:</span>
                      <span class="detail-value fact-text">{{ displayText(`edge:${loop.uuid}:fact`, loop.fact) }}</span>
                    </div>
                    <div class="detail-row" v-if="loop.fact_type">
                      <span class="detail-label">{{ L('类型', 'Type') }}:</span>
                      <span class="detail-value">{{ loop.fact_type }}</span>
                    </div>
                    <div class="detail-row" v-if="loop.created_at">
                      <span class="detail-label">{{ L('创建时间', 'Created') }}:</span>
                      <span class="detail-value">{{ formatDateTime(loop.created_at) }}</span>
                    </div>
                    <div v-if="loop.episodes && loop.episodes.length > 0" class="self-loop-episodes">
                      <span class="detail-label">{{ L('片段', 'Episodes') }}:</span>
                      <div class="episodes-list compact">
                        <span v-for="ep in loop.episodes" :key="ep" class="episode-tag small">{{ ep }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </template>
            
            <!-- 普通边详情 -->
            <template v-else>
              <div class="edge-relation-header">
                {{ selectedItem.data.source_name }} → {{ selectedItem.data.name || 'RELATED_TO' }} → {{ selectedItem.data.target_name }}
              </div>
              
              <div class="detail-row">
                <span class="detail-label">UUID:</span>
                <span class="detail-value uuid-text">{{ selectedItem.data.uuid }}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">{{ L('标签', 'Label') }}:</span>
                <span class="detail-value">{{ selectedItem.data.name || 'RELATED_TO' }}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">{{ L('类型', 'Type') }}:</span>
                <span class="detail-value">{{ selectedItem.data.fact_type || 'Unknown' }}</span>
              </div>
              <div class="detail-row" v-if="selectedItem.data.fact">
                <span class="detail-label">{{ L('事实', 'Fact') }}:</span>
                <span class="detail-value fact-text">{{ displayText(`edge:${selectedItem.data.uuid}:fact`, selectedItem.data.fact) }}</span>
              </div>

              <!-- Episodes -->
              <div class="detail-section" v-if="selectedItem.data.episodes && selectedItem.data.episodes.length > 0">
                <div class="section-title">{{ L('片段', 'Episodes') }}:</div>
                <div class="episodes-list">
                  <span v-for="ep in selectedItem.data.episodes" :key="ep" class="episode-tag">
                    {{ ep }}
                  </span>
                </div>
              </div>
              
              <div class="detail-row" v-if="selectedItem.data.created_at">
                <span class="detail-label">{{ L('创建时间', 'Created') }}:</span>
                <span class="detail-value">{{ formatDateTime(selectedItem.data.created_at) }}</span>
              </div>
              <div class="detail-row" v-if="selectedItem.data.valid_at">
                <span class="detail-label">{{ L('生效时间', 'Valid From') }}:</span>
                <span class="detail-value">{{ formatDateTime(selectedItem.data.valid_at) }}</span>
              </div>
            </template>
          </div>
        </div>
      </div>
      
      <!-- 加载状态 -->
      <div v-else-if="loading" class="graph-state">
        <div class="loading-spinner"></div>
        <p>{{ L('图谱数据加载中...', 'Loading graph data...') }}</p>
      </div>

      <!-- 等待/空状态 -->
      <div v-else class="graph-state">
        <div class="empty-icon">◇</div>
        <p class="empty-text">{{ L('等待本体生成...', 'Waiting for ontology generation...') }}</p>
      </div>
    </div>

    <!-- 底部图例 (Bottom Left) -->
    <div v-if="graphData && entityTypes.length" class="graph-legend">
      <span class="legend-title">{{ L('实体类型', 'Entity Types') }}</span>
      <div class="legend-items">
        <div class="legend-item" v-for="type in entityTypes" :key="type.name">
          <span class="legend-dot" :style="{ background: type.color }"></span>
          <span class="legend-label">{{ type.name }}</span>
        </div>
        <!-- T5.3: 研究种子图例（仅在有种子 actor 时显示） -->
        <div class="legend-item" v-if="seedActorSet.size">
          <span class="legend-dot seed-legend-dot"></span>
          <span class="legend-label">{{ L('研究确认', 'Researched') }}</span>
        </div>
      </div>
    </div>
    
    <!-- 显示边标签开关 -->
    <div v-if="graphData" class="edge-labels-toggle">
      <label class="toggle-switch">
        <input type="checkbox" v-model="showEdgeLabels" @change="userTouchedEdgeLabels = true" />
        <span class="slider"></span>
      </label>
      <span class="toggle-label">{{ L('显示边标签', 'Show Edge Labels') }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick, computed } from 'vue'
import * as d3 from 'd3'
import { L } from '../i18n'
import {
  getGraphData,
  getGraphNeighbors,
  getGraphNodeDetail,
  getGraphEdgeDetail,
} from '../api/graph'
import {
  DEFAULT_GRAPH_UI_MAX_NODES,
  boundedFocusNodeIds,
  graphPayloadMeta,
  graphPayloadRevision,
} from '../utils/graphPayload'
import { assignTypeColors, nodeRadius } from '../utils/graphStyle'
import { graphOverlayFetcher } from '../utils/overlayTranslation'
import { useTranslationJob } from '../composables/useTranslationJob.js'
import { normalizeTranslationSnapshot, translationBody } from '../utils/translationJobAdapter.js'
import TranslationJobStatus from './TranslationJobStatus.vue'

// ===== KG 渲染性能参数 =====
// 聚焦模式阈值：节点数超过该值时默认只渲染 Top-K 子图（可用 VITE_GRAPH_UI_MAX_NODES 覆盖）
const _envMaxNodes = Number(import.meta.env.VITE_GRAPH_UI_MAX_NODES)
const GRAPH_UI_MAX_NODES = Number.isFinite(_envMaxNodes) && _envMaxNodes > 0
  ? Math.floor(_envMaxNodes)
  : DEFAULT_GRAPH_UI_MAX_NODES
const EDGE_LABELS_AUTO_OFF_EDGES = 300 // 边数超过该值时默认关闭边标签（用户手动开过则尊重用户选择）
const LOD_LABEL_MIN_ZOOM = 0.8         // 缩放倍率低于该值时隐藏节点/边标签（LOD）
const DRAG_REHEAT_MAX_NODES = 300      // 节点数超过该值时拖拽不重启全局仿真，只移动被拖拽节点
const RESIZE_DEBOUNCE_MS = 200         // 窗口尺寸变化去抖

const props = defineProps({
  graphData: Object,
  loading: Boolean,
  currentPhase: Number,
  isSimulating: Boolean,
  // T5.3: 研究确认的 actor 名列表；匹配到的节点加「研究种子」环 + 图例
  seedActors: { type: Array, default: () => [] }
})

// Language selection stays local; the shared observer fences every graph/source revision.
const overlayLang = ref(null)
const overlayMap = ref({})
const overlayInventoryRevision = ref(0)
function toggleOverlayLang() {
  overlayLang.value = overlayLang.value === 'zh' ? null : 'zh'
  if (overlayLang.value === 'zh') return overlayObserver.start()
}
function displayText(key, sourceText) {
  if (overlayLang.value !== 'zh') return sourceText
  const translated = overlayMap.value[key]
  return translated?.source === String(sourceText || '').trim() ? translated.text : sourceText
}

// T5.3: 归一化（NFKC + lowercase + trim）的种子名集合，用于节点匹配
const seedActorSet = computed(() => {
  const s = new Set()
  for (const n of (props.seedActors || [])) {
    if (n == null) continue
    try {
      s.add(String(n).normalize('NFKC').toLowerCase().trim())
    } catch (e) {
      s.add(String(n).toLowerCase().trim())
    }
  }
  return s
})

function isSeedNode(node) {
  if (!node || !seedActorSet.value.size) return false
  const nm = node.name || node.id || ''
  try {
    return seedActorSet.value.has(String(nm).normalize('NFKC').toLowerCase().trim())
  } catch (e) {
    return seedActorSet.value.has(String(nm).toLowerCase().trim())
  }
}

const emit = defineEmits(['refresh', 'toggle-maximize'])

const graphContainer = ref(null)
const graphSvg = ref(null)
const selectedItem = ref(null)
const showEdgeLabels = ref(true) // 默认显示边标签
const expandedSelfLoops = ref(new Set()) // 展开的自环项
const showSimulationFinishedHint = ref(false) // 模拟结束后的提示
const wasSimulating = ref(false) // 追踪之前是否在模拟中
let detailSelectionVersion = 0 // 使切图/刷新/快速改选后的旧详情请求失效

// 关闭模拟结束提示
const dismissFinishedHint = () => {
  showSimulationFinishedHint.value = false
}

// 监听 isSimulating 变化，检测模拟结束
watch(() => props.isSimulating, (newValue, oldValue) => {
  if (wasSimulating.value && !newValue) {
    // 从模拟中变为非模拟状态，显示结束提示
    showSimulationFinishedHint.value = true
  }
  wasSimulating.value = newValue
}, { immediate: true })

// 切换自环项展开/折叠状态
const toggleSelfLoop = (id) => {
  const newSet = new Set(expandedSelfLoops.value)
  if (newSet.has(id)) {
    newSet.delete(id)
  } else {
    newSet.add(id)
    hydrateSelfLoopDetail(id)
  }
  expandedSelfLoops.value = newSet
}

function replaceSelectedSelfLoop(uuid, updater) {
  const current = selectedItem.value
  const loops = current?.data?.selfLoopEdges
  if (current?.type !== 'edge' || !current.data?.isSelfLoopGroup || !Array.isArray(loops)) return
  selectedItem.value = {
    ...current,
    data: {
      ...current.data,
      selfLoopEdges: loops.map(loop => loop?.uuid === uuid ? updater(loop) : loop),
    },
  }
}

async function hydrateSelfLoopDetail(id) {
  const current = selectedItem.value
  const loops = current?.data?.selfLoopEdges
  if (current?.type !== 'edge' || !current.data?.isSelfLoopGroup || !Array.isArray(loops)) return
  const loop = loops.find((item, index) => (item?.uuid || index) === id)
  const uuid = loop?.uuid
  if (!uuid || loop._detailLoaded || loop._detailLoading) return

  const gid = props.graphData?.graph_id
  if (!gid) return
  const selectionVersion = detailSelectionVersion
  replaceSelectedSelfLoop(uuid, item => ({ ...item, _detailLoading: true, _detailError: false }))
  try {
    const res = await getGraphEdgeDetail(gid, uuid)
    if (selectionVersion !== detailSelectionVersion || props.graphData?.graph_id !== gid) return
    if (res?.success && res.data) {
      replaceSelectedSelfLoop(uuid, item => ({
        ...item,
        ...res.data,
        _detailLoaded: true,
        _detailLoading: false,
        _detailError: false,
      }))
    } else {
      replaceSelectedSelfLoop(uuid, item => ({ ...item, _detailLoading: false, _detailError: true }))
    }
  } catch (_error) {
    if (selectionVersion === detailSelectionVersion && props.graphData?.graph_id === gid) {
      replaceSelectedSelfLoop(uuid, item => ({ ...item, _detailLoading: false, _detailError: true }))
    }
  }
}

// 计算实体类型用于图例。颜色按「类型名哈希 → 调色板槽位」确定性分配
// （utils/graphStyle），同名类型在不同图谱/不同刷新间保持同色。
const entityTypes = computed(() => {
  if (!props.graphData?.nodes) return []
  const counts = new Map()
  props.graphData.nodes.forEach(node => {
    const type = node.labels?.find(l => l !== 'Entity') || 'Entity'
    counts.set(type, (counts.get(type) || 0) + 1)
  })
  const colorMap = assignTypeColors([...counts.keys()])
  return [...counts.entries()].map(([name, count]) => ({
    name,
    count,
    color: colorMap.get(name) || '#999',
  }))
})

// ===== 节点搜索（按名称，Enter 循环匹配） =====
const searchQuery = ref('')
const searchMatchCount = ref(0)
const searchMatchIndex = ref(-1)
let searchSceneApi = null // renderGraph 每次重建后指向当前场景的搜索接口

const searchCountLabel = computed(() =>
  searchMatchCount.value > 0 ? `${searchMatchIndex.value + 1}/${searchMatchCount.value}` : '0/0'
)

function normalizeSearchText(value) {
  try {
    return String(value || '').normalize('NFKC').toLowerCase().trim()
  } catch (_e) {
    return String(value || '').toLowerCase().trim()
  }
}

function runSearch({ focus = false } = {}) {
  if (!searchSceneApi) return
  const query = normalizeSearchText(searchQuery.value)
  const count = searchSceneApi.setQuery(query)
  searchMatchCount.value = count
  searchMatchIndex.value = count > 0 ? 0 : -1
  if (count > 0 && focus) searchSceneApi.focusMatch(0)
}

function onSearchInput() {
  runSearch({ focus: true })
}

function onSearchEnter() {
  if (!searchSceneApi) return
  if (searchMatchCount.value === 0) {
    runSearch({ focus: true })
    return
  }
  searchMatchIndex.value = (searchMatchIndex.value + 1) % searchMatchCount.value
  searchSceneApi.focusMatch(searchMatchIndex.value)
}

function resetSearchState() {
  searchQuery.value = ''
  searchMatchCount.value = 0
  searchMatchIndex.value = -1
}

// ===== 时间过滤（按边的 valid_at 截断；slim 载荷无时间字段时控件自动隐藏） =====
const timeFilterTimes = ref([])   // 当前渲染边的 valid_at 时间戳（升序去重，ms）
const timeFilterIndex = ref(0)    // 滑块位置；== times.length 表示不过滤（全部）
let timeFilterCutoffMs = null     // 语义化截断时间；null = 全部（跨重渲染保留）
let applyTimeFilterFn = null      // renderGraph 每次重建后指向当前场景的过滤函数

const timeFilterLabel = computed(() => {
  const times = timeFilterTimes.value
  const idx = timeFilterIndex.value
  if (!times.length || idx >= times.length) return L('全部时间', 'All time')
  return formatFilterDate(times[Math.max(0, idx)])
})

function formatFilterDate(ms) {
  try {
    return new Date(ms).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  } catch (_e) {
    return String(ms)
  }
}

watch(timeFilterIndex, () => {
  const times = timeFilterTimes.value
  timeFilterCutoffMs = (!times.length || timeFilterIndex.value >= times.length)
    ? null
    : times[Math.max(0, timeFilterIndex.value)]
  if (applyTimeFilterFn) applyTimeFilterFn()
})

// 格式化时间
const formatDateTime = (dateStr) => {
  if (!dateStr) return ''
  try {
    const date = new Date(dateStr)
    return date.toLocaleString('en-US', { 
      month: 'short', 
      day: 'numeric', 
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true 
    })
  } catch {
    return dateStr
  }
}

const closeDetailPanel = () => {
  detailSelectionVersion += 1
  selectedItem.value = null
  expandedSelfLoops.value = new Set() // 重置展开状态
}

async function selectNodeItem(nodeDatum, color) {
  const base = nodeDatum.rawData
  const uuid = base?.uuid
  const gid = props.graphData?.graph_id
  const selectionVersion = ++detailSelectionVersion
  expandedSelfLoops.value = new Set()
  selectedItem.value = {
    type: 'node',
    data: base,
    entityType: nodeDatum.type,
    color,
    detailLoading: Boolean(gid && uuid),
    detailError: false,
  }
  if (!gid || !uuid) return
  try {
    const res = await getGraphNodeDetail(gid, uuid)
    const current = selectedItem.value
    if (selectionVersion !== detailSelectionVersion || props.graphData?.graph_id !== gid) return
    if (current?.type !== 'node' || current.data?.uuid !== uuid) return
    selectedItem.value = res?.success && res.data
      ? { ...current, data: { ...current.data, ...res.data }, detailLoading: false, detailError: false }
      : { ...current, detailLoading: false, detailError: true }
  } catch (_error) {
    const current = selectedItem.value
    if (selectionVersion === detailSelectionVersion && current?.type === 'node' && current.data?.uuid === uuid) {
      selectedItem.value = { ...current, detailLoading: false, detailError: true }
    }
  }
}

async function selectEdgeItem(base) {
  const isGroup = Boolean(base?.isSelfLoopGroup)
  const uuid = base?.uuid
  const gid = props.graphData?.graph_id
  const selectionVersion = ++detailSelectionVersion
  expandedSelfLoops.value = new Set()
  selectedItem.value = {
    type: 'edge',
    data: base,
    detailLoading: Boolean(!isGroup && gid && uuid),
    detailError: false,
  }
  if (isGroup || !gid || !uuid) return
  try {
    const res = await getGraphEdgeDetail(gid, uuid)
    const current = selectedItem.value
    if (selectionVersion !== detailSelectionVersion || props.graphData?.graph_id !== gid) return
    if (current?.type !== 'edge' || current.data?.uuid !== uuid) return
    selectedItem.value = res?.success && res.data
      ? { ...current, data: { ...current.data, ...res.data }, detailLoading: false, detailError: false }
      : { ...current, detailLoading: false, detailError: true }
  } catch (_error) {
    const current = selectedItem.value
    if (selectionVersion === detailSelectionVersion && current?.type === 'edge' && current.data?.uuid === uuid) {
      selectedItem.value = { ...current, detailLoading: false, detailError: true }
    }
  }
}

let currentSimulation = null
// EXECPLAN2 F-10-1: 跨刷新保留布局与视口，避免每次 refresh 全量重建 D3 仿真而丢失
// 缩放/平移与既有节点位置。
let zoomBehavior = null
let savedTransform = null

// 边标签开关 watcher 使用的模块级句柄（每次 renderGraph 重新赋值，闭包持有当前选择集）
let updateLabelLayerVisibilityFn = null

// ===== 聚焦模式（大图 Top-K 子图）状态 =====
let lastGraphId = null            // 检测图谱切换，切换时重置聚焦/展开状态
let lastOverviewRevision = null   // 同图轮询发生结构变化时使缓存失效
let expandedNodeIds = new Set()   // 聚焦模式下点击展开加入视图的节点 uuid
let expandedCenterIds = new Set() // 已请求过邻域的中心节点（与仅作为邻居出现的节点分开）
let activeFocusNodeId = null      // 最近点击的聚焦中心，预算收缩时优先保留
let extraNodes = []               // 服务端 slim/neighbors 返回、不在原始载荷中的节点
let extraEdges = []               // 同上，额外的边
let serverFilterSupport = null    // null=未探测；false=后端不支持 ?top_k/slim（忽略参数），本会话内不再尝试
let serverNeighborsSupport = null // null=未探测；false=/neighbors 端点不存在（404），回退本地展开
let serverFocusData = null        // 服务端过滤视图缓存 { key, nodes, edges }
let serverFocusFetching = false
let serverFocusRequestVersion = 0
let focusStateVersion = 0
let neighborRequestVersion = 0
let fullGraphDataRevision = null
let fullGraphRequestVersion = 0

const focusModeActive = ref(false)       // 当前渲染是否为聚焦（Top-K）视图
const fullGraphRequested = ref(false)    // 用户点击「加载完整图谱」的逃生阀
const fullGraphData = ref(null)          // 仅显式点击后获取；初始载荷永远不预下载完整图
const fullGraphLoading = ref(false)
const expandingNode = ref(false)         // 邻居展开请求进行中
const renderedNodeCount = ref(0)
const totalNodeCount = ref(0)
const userTouchedEdgeLabels = ref(false) // 用户手动动过边标签开关后，不再自动关闭

// Include the overview, loaded full graph, server focus and expanded neighbours.
// Exact source strings guard even in-place prose changes under an unchanged UUID.
const overlayInventory = computed(() => {
  void overlayInventoryRevision.value
  const currentId = props.graphData?.graph_id
  const owned = lastGraphId === currentId && lastOverviewRevision === graphPayloadRevision(props.graphData)
  const sources = [owned && { nodes: extraNodes, edges: extraEdges }, owned && serverFocusData,
    fullGraphData.value?.graph_id === currentId && fullGraphData.value, props.graphData,
    selectedItem.value?.type === 'node' ? { nodes: [selectedItem.value.data] }
      : selectedItem.value?.type === 'edge' ? { edges: selectedItem.value.data?.selfLoopEdges || [selectedItem.value.data] } : null].filter(Boolean)
  const entries = new Map()
  for (const graph of sources) {
    for (const node of graph.nodes || []) if (node.uuid && node.summary?.trim()) entries.set(`node:${node.uuid}:summary`, node.summary.trim())
    for (const edge of graph.edges || []) if (edge.uuid && edge.fact?.trim()) entries.set(`edge:${edge.uuid}:fact`, edge.fact.trim())
  }
  return [...entries]
})
const overlayObserver = useTranslationJob({
  identity: () => overlayLang.value === 'zh' && props.graphData?.graph_id
    ? { graphId: props.graphData.graph_id, revision: graphPayloadRevision(props.graphData), entries: overlayInventory.value, lang: 'zh' } : null,
  adapter: () => {
    const client = graphOverlayFetcher(props.graphData.graph_id)
    const inventory = new Map(overlayInventory.value)
    const normalize = response => {
      const data = translationBody(response)
      const admitted = (data.translations || []).filter(row => row?.source && typeof row.text === 'string' && /^[a-f0-9]{64}$/.test(row.source_sha256))
      const byKey = new Map(admitted.filter(row => row.key).map(row => [row.key, row]))
      const legacyPairs = new Set(admitted.filter(row => !row.key).map(row => JSON.stringify([row.source, row.text])))
      const overlay = {}
      for (const [key, source] of inventory) {
        const row = byKey.get(key), text = data.overlay?.[key]
        if (row ? row.source === source && row.text === text : legacyPairs.has(JSON.stringify([source, text]))) {
          overlay[key] = { source, text }
        }
      }
      const missing = inventory.size - Object.keys(overlay).length
      const normalized = normalizeTranslationSnapshot(response)
      const total = Math.max(inventory.size, normalized.coverage.total)
      const pending = Math.max(missing, normalized.coverage.pending)
      normalized.coverage = { total, accepted: Math.max(0, total - pending), pending }
      if (missing && !normalized.active) {
        normalized.state = 'partial'; normalized.partial = true
        normalized.actions.retry = true
        normalized.issues = [...new Set([...normalized.issues, 'Visible graph passages remain untranslated; retry to complete the full inventory.'])]
      }
      return { ...normalized, continue: data.continuation?.available === true, data: { ...data, admittedOverlay: overlay } }
    }
    return { get: async ({ signal }) => normalize(await client.get('zh', { signal })),
      start: async ({ signal, force }) => normalize(await client.start('zh', force, { signal })) }
  },
  onReset: () => { overlayMap.value = {} },
  onUpdate: state => { overlayMap.value = state.data.admittedOverlay },
})
const overlayBusy = overlayObserver.busy

// 渲染合并调度：同一 tick 内的多个触发只重建一次
let renderPending = false
function scheduleRender() {
  overlayInventoryRevision.value += 1
  if (renderPending) return
  renderPending = true
  nextTick(() => {
    renderPending = false
    renderGraph()
  })
}

const loadFullGraph = async ({ force = false } = {}) => {
  const gid = props.graphData?.graph_id
  if (!gid || fullGraphLoading.value) return
  const overviewRevision = graphPayloadRevision(props.graphData)
  if (!force && fullGraphData.value?.graph_id === gid && fullGraphDataRevision === overviewRevision) {
    fullGraphRequested.value = true
    scheduleRender()
    return
  }
  const requestVersion = ++fullGraphRequestVersion
  fullGraphLoading.value = true
  try {
    const res = await getGraphData(gid, { full: true })
    if (
      requestVersion === fullGraphRequestVersion &&
      props.graphData?.graph_id === gid &&
      graphPayloadRevision(props.graphData) === overviewRevision &&
      res?.success && res.data
    ) {
      fullGraphData.value = res.data
      fullGraphDataRevision = overviewRevision
      fullGraphRequested.value = true
      scheduleRender()
    }
  } catch (e) {
    console.warn('完整图谱加载失败:', e?.message || e)
  } finally {
    if (requestVersion === fullGraphRequestVersion) fullGraphLoading.value = false
  }
}

const backToFocusMode = () => {
  fullGraphRequested.value = false
  scheduleRender()
}

// 边的去重键：优先 uuid，无 uuid 时用端点+名称+时间组合
function edgeKey(e) {
  return e.uuid || `${e.source_node_uuid}|${e.target_node_uuid}|${e.name || ''}|${e.created_at || ''}`
}

function focusCacheKey(raw) {
  const total = graphPayloadMeta(raw, GRAPH_UI_MAX_NODES).totalNodes
  return `${raw.graph_id || ''}|${GRAPH_UI_MAX_NODES}|${total}`
}

// 探测/获取服务端 Top-K 过滤视图（后端不支持时会原样返回完整图，则本会话降级为客户端过滤）
async function maybeFetchServerFocus(raw) {
  if (!raw || !raw.graph_id || serverFilterSupport === false || serverFocusFetching) return
  const key = focusCacheKey(raw)
  if (serverFocusData && serverFocusData.key === key) return
  const requestVersion = ++serverFocusRequestVersion
  serverFocusFetching = true
  try {
    const res = await getGraphData(raw.graph_id, { topK: GRAPH_UI_MAX_NODES, slim: true })
    if (requestVersion !== serverFocusRequestVersion || props.graphData?.graph_id !== raw.graph_id) return
    const data = res && res.success ? res.data : null
    const total = graphPayloadMeta(raw, GRAPH_UI_MAX_NODES).totalNodes
    if (data && Array.isArray(data.nodes) && data.nodes.length > 0 && data.nodes.length < total) {
      serverFilterSupport = true
      serverFocusData = { key, nodes: data.nodes, edges: Array.isArray(data.edges) ? data.edges : [] }
      scheduleRender()
    } else {
      // 服务端忽略了 top_k/slim 参数（旧版后端）：改走客户端 Top-K 过滤
      serverFilterSupport = false
    }
  } catch (e) {
    if (requestVersion === serverFocusRequestVersion) {
      console.warn('服务端 Top-K 过滤视图不可用，回退客户端过滤:', e?.message || e)
      serverFilterSupport = false
    }
  } finally {
    if (requestVersion === serverFocusRequestVersion) serverFocusFetching = false
  }
}

// 客户端 Top-K：按度数排名取前 K 个节点
function clientTopKNodeIds(allNodes, allEdges) {
  const degree = new Map()
  for (const e of allEdges) {
    degree.set(e.source_node_uuid, (degree.get(e.source_node_uuid) || 0) + 1)
    if (e.target_node_uuid !== e.source_node_uuid) {
      degree.set(e.target_node_uuid, (degree.get(e.target_node_uuid) || 0) + 1)
    }
  }
  const ranked = allNodes.slice().sort((a, b) => (degree.get(b.uuid) || 0) - (degree.get(a.uuid) || 0))
  const kept = new Set()
  for (const n of ranked) {
    if (kept.size >= GRAPH_UI_MAX_NODES) break
    kept.add(n.uuid)
  }
  return kept
}

// 计算本次渲染的数据集：小图直接全量；大图走聚焦（服务端过滤优先，客户端 Top-K 兜底）
function resolveRenderData() {
  const raw = (fullGraphRequested.value && fullGraphData.value) || props.graphData || {}
  const meta = graphPayloadMeta(raw, GRAPH_UI_MAX_NODES)
  const allNodes = meta.nodes
  const allEdges = meta.edges
  totalNodeCount.value = meta.totalNodes

  const needFocus = !fullGraphRequested.value && meta.needsFocus
  focusModeActive.value = needFocus
  if (!needFocus) {
    renderedNodeCount.value = allNodes.length
    return { nodesData: allNodes, edgesData: allEdges }
  }

  // 父视图的首个请求已是服务端 slim/top-K overview 时，不再发第二次 focus 请求。
  // 邻域展开仍会经过下方的统一预算选择，避免多次点击重新累积成大图。
  const boundedOverview = meta.truncated && allNodes.length <= GRAPH_UI_MAX_NODES
  if (boundedOverview) {
    serverFilterSupport = true
  } else {
    maybeFetchServerFocus(raw) // 异步探测；命中后会触发一次重渲染
  }

  const useServerView = !boundedOverview && serverFocusData && serverFocusData.key === focusCacheKey(raw)
  const serverNodes = useServerView ? serverFocusData.nodes : []
  const serverEdges = useServerView ? serverFocusData.edges : []
  const candidateMap = new Map()
  for (const node of allNodes.concat(serverNodes, extraNodes)) {
    if (node?.uuid && !candidateMap.has(node.uuid)) candidateMap.set(node.uuid, node)
  }

  const seen = new Set()
  const candidateEdges = []
  for (const e of allEdges.concat(serverEdges, extraEdges)) {
    if (!e?.source_node_uuid || !e?.target_node_uuid) continue
    const k = edgeKey(e)
    if (seen.has(k)) continue
    seen.add(k)
    candidateEdges.push(e)
  }

  const baseNodeIds = boundedOverview
    ? allNodes.map(node => node.uuid)
    : useServerView
      ? serverNodes.map(node => node.uuid)
      : [...clientTopKNodeIds(allNodes, allEdges)]
  const candidateNodes = [...candidateMap.values()]
  const seedNodeIds = candidateNodes.filter(isSeedNode).map(node => node.uuid)
  const kept = boundedFocusNodeIds({
    candidateNodes,
    edges: candidateEdges,
    baseNodeIds,
    expandedNodeIds: [...expandedNodeIds],
    seedNodeIds,
    activeNodeId: activeFocusNodeId,
    limit: GRAPH_UI_MAX_NODES,
  })
  const nodesData = candidateNodes.filter(node => kept.has(node.uuid))
  const edgesData = candidateEdges.filter(
    edge => kept.has(edge.source_node_uuid) && kept.has(edge.target_node_uuid)
  )

  renderedNodeCount.value = nodesData.length
  return { nodesData, edgesData }
}

// 聚焦模式：点击节点展开其 1 跳邻居（服务端 /neighbors 优先，404/失败回退到完整载荷的本地查找）
async function expandNodeNeighbors(nodeDatum) {
  if (!focusModeActive.value || expandingNode.value) return
  const uuid = nodeDatum.id
  if (expandedCenterIds.has(uuid)) return
  const requestVersion = ++neighborRequestVersion
  const stateVersion = focusStateVersion
  expandingNode.value = true
  try {
    let merged = false
    const gid = props.graphData?.graph_id
    if (gid && serverNeighborsSupport !== false) {
      try {
        const res = await getGraphNeighbors(gid, uuid, 1)
        if (
          requestVersion === neighborRequestVersion &&
          stateVersion === focusStateVersion &&
          props.graphData?.graph_id === gid &&
          res?.success && res.data
        ) {
          mergeNeighborPayload(res.data)
          serverNeighborsSupport = true
          merged = true
        }
      } catch (e) {
        if (requestVersion === neighborRequestVersion && stateVersion === focusStateVersion) {
          serverNeighborsSupport = false
          console.warn('邻居子图端点不可用，回退本地展开:', e?.message || e)
        }
      }
    }
    if (requestVersion !== neighborRequestVersion || stateVersion !== focusStateVersion) return
    if (!merged) mergeNeighborsFromLocal(uuid)
    expandedNodeIds.add(uuid)
    expandedCenterIds.add(uuid)
    activeFocusNodeId = uuid
    scheduleRender()
  } finally {
    if (requestVersion === neighborRequestVersion) expandingNode.value = false
  }
}

function mergeNeighborPayload(data) {
  const localIds = new Set((props.graphData?.nodes || []).map(n => n.uuid))
  const extraIds = new Set(extraNodes.map(n => n.uuid))
  for (const n of (data.nodes || [])) {
    if (!n || !n.uuid) continue
    expandedNodeIds.add(n.uuid)
    if (!localIds.has(n.uuid) && !extraIds.has(n.uuid)) {
      extraNodes.push(n)
      extraIds.add(n.uuid)
    }
  }
  const extraEdgeKeys = new Set(extraEdges.map(edgeKey))
  for (const e of (data.edges || [])) {
    if (!e || !e.source_node_uuid || !e.target_node_uuid) continue
    const k = edgeKey(e)
    if (!extraEdgeKeys.has(k)) {
      extraEdges.push(e)
      extraEdgeKeys.add(k)
    }
  }
}

function mergeNeighborsFromLocal(uuid) {
  for (const e of (props.graphData?.edges || [])) {
    if (e.source_node_uuid === uuid) expandedNodeIds.add(e.target_node_uuid)
    else if (e.target_node_uuid === uuid) expandedNodeIds.add(e.source_node_uuid)
  }
}

// 图谱切换或同图结构版本变化时清理派生缓存；同图刷新后若用户在 full 模式则重新拉取。
// 返回值仅表示 graph_id 是否变化，用于决定是否保留视口。
function synchronizeGraphState() {
  const gid = props.graphData?.graph_id || null
  const revision = graphPayloadRevision(props.graphData)
  const graphChanged = gid !== lastGraphId
  const revisionChanged = !graphChanged && lastOverviewRevision !== null && revision !== lastOverviewRevision
  if (!graphChanged && !revisionChanged) return false

  const restoreFullMode = revisionChanged && fullGraphRequested.value
  lastGraphId = gid
  lastOverviewRevision = revision
  focusStateVersion += 1
  neighborRequestVersion += 1
  serverFocusRequestVersion += 1
  fullGraphRequestVersion += 1
  expandedNodeIds = new Set()
  expandedCenterIds = new Set()
  activeFocusNodeId = null
  extraNodes = []
  extraEdges = []
  fullGraphRequested.value = false
  fullGraphData.value = null
  fullGraphDataRevision = null
  fullGraphLoading.value = false
  expandingNode.value = false
  serverFocusData = null
  serverFocusFetching = false
  serverFilterSupport = null
  serverNeighborsSupport = null
  closeDetailPanel()
  overlayInventoryRevision.value += 1

  if (graphChanged) {
    userTouchedEdgeLabels.value = false
    showEdgeLabels.value = true
    savedTransform = null // 新图不继承旧图的视口
    resetSearchState()    // 搜索与时间过滤都不跨图保留
    timeFilterCutoffMs = null
  }
  if (restoreFullMode) nextTick(() => loadFullGraph({ force: true }))
  return graphChanged
}

// 后端预计算布局（graphData.positions: {uuid: [x,y] | {x,y}}，如 networkx spring_layout 输出）。
// 坐标按整体包围盒线性映射到当前视口；命中时仿真以极低 alpha 启动，只做微调。
function buildPositionLookup(raw, width, height) {
  const posMap = raw && raw.positions
  if (!posMap || typeof posMap !== 'object') return null
  const norm = new Map()
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  for (const [uuid, v] of Object.entries(posMap)) {
    let x, y
    if (Array.isArray(v)) {
      x = Number(v[0])
      y = Number(v[1])
    } else if (v && typeof v === 'object') {
      x = Number(v.x)
      y = Number(v.y)
    }
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue
    norm.set(uuid, { x, y })
    if (x < minX) minX = x
    if (x > maxX) maxX = x
    if (y < minY) minY = y
    if (y > maxY) maxY = y
  }
  if (!norm.size) return null
  const pad = 60
  const spanX = (maxX - minX) || 1
  const spanY = (maxY - minY) || 1
  return (uuid) => {
    const p = norm.get(uuid)
    if (!p) return null
    return {
      x: pad + (p.x - minX) / spanX * Math.max(width - pad * 2, 1),
      y: pad + (p.y - minY) / spanY * Math.max(height - pad * 2, 1)
    }
  }
}

// 边的 valid_at → 时间戳 ms（无字段 / 不可解析 / 自环组 → null）。
// slim 概览载荷不带时间字段（后端 _SLIM_EDGE_KEYS），此时时间过滤控件自动隐藏，
// 完整图谱模式与旧版全量后端载荷带字段时才启用 —— degrade-safe。
function edgeValidMs(d) {
  const raw = d?.rawData
  if (!raw || raw.isSelfLoopGroup) return null
  if (!raw.valid_at) return null
  const t = Date.parse(raw.valid_at)
  return Number.isFinite(t) ? t : null
}

// 过期事实：invalid_at 已设置（载荷无该字段时恒 false）→ 淡化 + 虚线
function isExpiredEdge(d) {
  return Boolean(!d?.isSelfLoop && d?.rawData && d.rawData.invalid_at)
}

// 标签隐藏无法 getBBox 时按字符宽度估算：CJK/全角 ≈ 9px，其他 ≈ 5.5px（font-size 9px）
function estimateLabelSize(text) {
  let w = 0
  const cjkRe = new RegExp('[\\u2E80-\\u9FFF\\uF900-\\uFAFF\\uFF00-\\uFF60\\uFFE0-\\uFFE6\\u3000-\\u303F]')
  for (const ch of String(text || '')) {
    w += cjkRe.test(ch) ? 9 : 5.5
  }
  return { w: Math.max(w, 12), h: 11 }
}

const renderGraph = () => {
  if (!graphSvg.value || !props.graphData) return

  const graphChanged = synchronizeGraphState()

  const container = graphContainer.value
  const width = container.clientWidth
  const height = container.clientHeight

  const svg = d3.select(graphSvg.value)
    .attr('width', width)
    .attr('height', height)
    .attr('viewBox', `0 0 ${width} ${height}`)

  // F-10-1: 拆除前先记录既有节点坐标与当前缩放变换，刷新后据此复原。
  const prevPositions = new Map()
  if (currentSimulation) {
    for (const n of currentSimulation.nodes()) {
      if (n && n.id != null && n.x != null && n.y != null) {
        prevPositions.set(n.id, { x: n.x, y: n.y })
      }
    }
    // 停止之前的仿真（在读取旧坐标之后）
    currentSimulation.stop()
  }
  try {
    const t = d3.zoomTransform(svg.node())
    // 图谱切换时不回存旧图的视口变换
    if (!graphChanged && t && (t.k !== 1 || t.x !== 0 || t.y !== 0)) savedTransform = t
  } catch (_e) { /* 首次渲染无变换 */ }

  svg.selectAll('*').remove()

  // 大图走聚焦（Top-K 子图）数据集，小图全量
  const { nodesData, edgesData } = resolveRenderData()

  if (nodesData.length === 0) return

  // 边太多时默认关闭边标签（除非用户手动开过）——每帧标签定位是主要开销之一
  if (!userTouchedEdgeLabels.value && showEdgeLabels.value && edgesData.length > EDGE_LABELS_AUTO_OFF_EDGES) {
    showEdgeLabels.value = false
  }

  // Prep data
  const nodeMap = {}
  nodesData.forEach(n => nodeMap[n.uuid] = n)

  // 度数 → 节点半径（sqrt 比例，6-18px）：枢纽节点一眼可辨（数据已在客户端）
  const degreeByUuid = new Map()
  for (const e of edgesData) {
    if (!e?.source_node_uuid || !e?.target_node_uuid) continue
    degreeByUuid.set(e.source_node_uuid, (degreeByUuid.get(e.source_node_uuid) || 0) + 1)
    if (e.target_node_uuid !== e.source_node_uuid) {
      degreeByUuid.set(e.target_node_uuid, (degreeByUuid.get(e.target_node_uuid) || 0) + 1)
    }
  }
  let maxDegree = 0
  degreeByUuid.forEach(v => { if (v > maxDegree) maxDegree = v })

  // 为已存在的节点种入上一次的坐标，仅新节点重新布局（F-10-1）；
  // 无旧坐标时用后端预计算布局（graphData.positions）作为初始位置。
  const posLookup = buildPositionLookup(props.graphData, width, height)
  let survived = 0
  let preSeeded = 0
  const nodes = nodesData.map(n => {
    const prev = prevPositions.get(n.uuid)
    if (prev) survived++
    const pre = !prev && posLookup ? posLookup(n.uuid) : null
    if (pre) preSeeded++
    const seed = prev || pre
    return {
      id: n.uuid,
      name: n.name || 'Unnamed',
      type: n.labels?.find(l => l !== 'Entity') || 'Entity',
      r: nodeRadius(degreeByUuid.get(n.uuid) || 0, maxDegree),
      rawData: n,
      ...(seed ? { x: seed.x, y: seed.y } : {})
    }
  })
  
  const nodeIds = new Set(nodes.map(n => n.id))
  
  // 处理边数据，计算同一对节点间的边数量和索引
  const edgePairCount = {}
  const selfLoopEdges = {} // 按节点分组的自环边
  const tempEdges = edgesData
    .filter(e => nodeIds.has(e.source_node_uuid) && nodeIds.has(e.target_node_uuid))
  
  // 统计每对节点之间的边数量，收集自环边
  tempEdges.forEach(e => {
    if (e.source_node_uuid === e.target_node_uuid) {
      // 自环 - 收集到数组中
      if (!selfLoopEdges[e.source_node_uuid]) {
        selfLoopEdges[e.source_node_uuid] = []
      }
      selfLoopEdges[e.source_node_uuid].push({
        ...e,
        source_name: nodeMap[e.source_node_uuid]?.name,
        target_name: nodeMap[e.target_node_uuid]?.name
      })
    } else {
      const pairKey = [e.source_node_uuid, e.target_node_uuid].sort().join('_')
      edgePairCount[pairKey] = (edgePairCount[pairKey] || 0) + 1
    }
  })
  
  // 记录当前处理到每对节点的第几条边
  const edgePairIndex = {}
  const processedSelfLoopNodes = new Set() // 已处理的自环节点
  
  const edges = []
  
  tempEdges.forEach(e => {
    const isSelfLoop = e.source_node_uuid === e.target_node_uuid
    
    if (isSelfLoop) {
      // 自环边 - 每个节点只添加一条合并的自环
      if (processedSelfLoopNodes.has(e.source_node_uuid)) {
        return // 已处理过，跳过
      }
      processedSelfLoopNodes.add(e.source_node_uuid)
      
      const allSelfLoops = selfLoopEdges[e.source_node_uuid]
      const nodeName = nodeMap[e.source_node_uuid]?.name || 'Unknown'
      
      edges.push({
        source: e.source_node_uuid,
        target: e.target_node_uuid,
        type: 'SELF_LOOP',
        name: `Self Relations (${allSelfLoops.length})`,
        curvature: 0,
        isSelfLoop: true,
        rawData: {
          isSelfLoopGroup: true,
          source_name: nodeName,
          target_name: nodeName,
          selfLoopCount: allSelfLoops.length,
          selfLoopEdges: allSelfLoops // 存储所有自环边的详细信息
        }
      })
      return
    }
    
    const pairKey = [e.source_node_uuid, e.target_node_uuid].sort().join('_')
    const totalCount = edgePairCount[pairKey]
    const currentIndex = edgePairIndex[pairKey] || 0
    edgePairIndex[pairKey] = currentIndex + 1
    
    // 判断边的方向是否与标准化方向一致（源UUID < 目标UUID）
    const isReversed = e.source_node_uuid > e.target_node_uuid
    
    // 计算曲率：多条边时分散开，单条边为直线
    let curvature = 0
    if (totalCount > 1) {
      // 均匀分布曲率，确保明显区分
      // 曲率范围根据边数量增加，边越多曲率范围越大
      const curvatureRange = Math.min(1.2, 0.6 + totalCount * 0.15)
      curvature = ((currentIndex / (totalCount - 1)) - 0.5) * curvatureRange * 2
      
      // 如果边的方向与标准化方向相反，翻转曲率
      // 这样确保所有边在同一参考系下分布，不会因方向不同而重叠
      if (isReversed) {
        curvature = -curvature
      }
    }
    
    edges.push({
      source: e.source_node_uuid,
      target: e.target_node_uuid,
      type: e.fact_type || e.name || 'RELATED',
      name: e.name || e.fact_type || 'RELATED',
      curvature,
      isSelfLoop: false,
      pairIndex: currentIndex,
      pairTotal: totalCount,
      rawData: {
        ...e,
        source_name: nodeMap[e.source_node_uuid]?.name,
        target_name: nodeMap[e.target_node_uuid]?.name
      }
    })
  })
    
  // Color scale
  const colorMap = {}
  entityTypes.value.forEach(t => colorMap[t.name] = t.color)
  const getColor = (type) => colorMap[type] || '#999'

  // Simulation - 根据边数量动态调整节点间距
  const simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(edges).id(d => d.id).distance(d => {
      // 根据这对节点之间的边数量动态调整距离
      // 基础距离 150，每多一条边增加 40
      const baseDistance = 150
      const edgeCount = d.pairTotal || 1
      return baseDistance + (edgeCount - 1) * 50
    }))
    .force('charge', d3.forceManyBody().strength(-400))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collide', d3.forceCollide(50))
    // 添加向中心的引力，让独立的节点群聚集到中心区域
    .force('x', d3.forceX(width / 2).strength(0.04))
    .force('y', d3.forceY(height / 2).strength(0.04))
  
  currentSimulation = simulation
  // F-10-1: 多数节点存活时降低初始 alpha，让布局微调而非整体重排（保留位置感）。
  if (nodes.length > 0 && survived / nodes.length > 0.5) {
    simulation.alpha(0.3)
  } else if (nodes.length > 0 && (survived + preSeeded) / nodes.length > 0.9) {
    // 预计算布局覆盖绝大多数节点：以极低 alpha 启动，仅做微调后即刻静止
    simulation.alpha(0.08)
  }

  const g = svg.append('g')

  // ===== 方向箭头（marker-end）=====
  // 有向边加小箭头；颜色跟随边的三种描边色（默认/选中/关联高亮），
  // userSpaceOnUse 固定像素尺寸，跟随缩放整体变换，逐帧零开销。
  const EDGE_COLOR_DEFAULT = '#C0C0C0'
  const EDGE_COLOR_ACTIVE = '#3498db'
  const EDGE_COLOR_ACCENT = '#E91E63'
  const arrowIds = {
    [EDGE_COLOR_DEFAULT]: 'gp-arrow-default',
    [EDGE_COLOR_ACTIVE]: 'gp-arrow-active',
    [EDGE_COLOR_ACCENT]: 'gp-arrow-accent',
  }
  const defs = svg.append('defs')
  for (const [color, id] of Object.entries(arrowIds)) {
    defs.append('marker')
      .attr('id', id)
      .attr('viewBox', '0 -4 8 8')
      .attr('refX', 8)
      .attr('refY', 0)
      .attr('markerWidth', 8)
      .attr('markerHeight', 8)
      .attr('markerUnits', 'userSpaceOnUse')
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-4L8,0L0,4')
      .attr('fill', color)
  }
  const edgeMarker = color => `url(#${arrowIds[color] || arrowIds[EDGE_COLOR_DEFAULT]})`
  // 统一的边描边样式（描边色 + 线宽 + 对应色箭头）；所有重置/高亮路径都走这里
  function styleEdges(sel, color, width) {
    sel.attr('stroke', color)
      .attr('stroke-width', width)
      .attr('marker-end', d => (d.isSelfLoop ? null : edgeMarker(color)))
  }

  // 标签 LOD：低倍率下隐藏节点/边标签，减少缩放/平移时需要重绘的矢量元素数量
  let lodLabelsHidden = (savedTransform ? savedTransform.k : 1) < LOD_LABEL_MIN_ZOOM
  let latestTransform = savedTransform || d3.zoomIdentity
  let zoomRaf = null
  let sceneReady = false // 防止恢复视口时同步触发的 zoom/end 事件在选择集构建完成前访问它们

  const applyZoomFrame = () => {
    zoomRaf = null
    g.attr('transform', latestTransform)
    if (!sceneReady) return
    const hide = latestTransform.k < LOD_LABEL_MIN_ZOOM
    if (hide !== lodLabelsHidden) {
      lodLabelsHidden = hide
      updateLabelLayerVisibility()
    }
  }

  // Zoom —— 复用具名 behavior，便于刷新后用 svg.call(zoomBehavior.transform, savedTransform) 复原视口。
  // 变换在 requestAnimationFrame 中应用，把高频滚轮/拖动事件合并为每帧一次重绘。
  zoomBehavior = d3.zoom().extent([[0, 0], [width, height]]).scaleExtent([0.1, 4])
    .on('zoom', (event) => {
      latestTransform = event.transform
      if (zoomRaf == null) zoomRaf = requestAnimationFrame(applyZoomFrame)
    })
    .on('end', () => {
      // 缩放/平移结束后做一次标签视口剔除
      if (sceneReady) applyViewportCull()
    })
  svg.call(zoomBehavior)
  if (savedTransform) {
    svg.call(zoomBehavior.transform, savedTransform)  // 复原上次的平移/缩放
  } else if (graphChanged) {
    svg.call(zoomBehavior.transform, d3.zoomIdentity) // 新图重置视口，清掉 svg 上残留的旧变换
  }

  // Links - 使用 path 支持曲线
  const linkGroup = g.append('g').attr('class', 'links')
  
  // 计算曲线路径
  // 箭头留白：路径终点从目标节点圆心回缩到圆边外侧，箭头才不会被节点盖住
  const ARROW_GAP = 3
  const getLinkPath = (d) => {
    const sx = d.source.x, sy = d.source.y
    const tx = d.target.x, ty = d.target.y

    // 检测自环
    if (d.isSelfLoop) {
      // 自环：绘制一个圆弧从节点出发再返回（起终点贴节点圆边）
      const loopRadius = 30
      const nr = Math.max((d.source.r || 10) - 2, 4)
      const x1 = sx + nr  // 起点偏移
      const y1 = sy - 4
      const x2 = sx + nr  // 终点偏移
      const y2 = sy + 4
      // 使用圆弧绘制自环（sweep-flag=1 顺时针）
      return `M${x1},${y1} A${loopRadius},${loopRadius} 0 1,1 ${x2},${y2}`
    }

    const targetPad = (d.target.r || 10) + ARROW_GAP

    if (d.curvature === 0) {
      // 直线：终点沿连线方向回缩，给箭头留位
      const dx = tx - sx, dy = ty - sy
      const dist = Math.sqrt(dx * dx + dy * dy) || 1
      const cut = Math.min(targetPad, Math.max(dist - 2, 0))
      const ex = tx - dx / dist * cut
      const ey = ty - dy / dist * cut
      return `M${sx},${sy} L${ex},${ey}`
    }

    // 计算曲线控制点 - 根据边数量和距离动态调整
    const dx = tx - sx, dy = ty - sy
    const dist = Math.sqrt(dx * dx + dy * dy)
    // 垂直于连线方向的偏移，根据距离比例计算，保证曲线明显可见
    // 边越多，偏移量占距离的比例越大
    const pairTotal = d.pairTotal || 1
    const offsetRatio = 0.25 + pairTotal * 0.05 // 基础25%，每多一条边增加5%
    const baseOffset = Math.max(35, dist * offsetRatio)
    const offsetX = -dy / dist * d.curvature * baseOffset
    const offsetY = dx / dist * d.curvature * baseOffset
    const cx = (sx + tx) / 2 + offsetX
    const cy = (sy + ty) / 2 + offsetY

    // 曲线：沿终点切线方向（控制点 → 终点）回缩
    const cdx = tx - cx, cdy = ty - cy
    const cdist = Math.sqrt(cdx * cdx + cdy * cdy) || 1
    const cut = Math.min(targetPad, Math.max(cdist - 2, 0))
    const ex = tx - cdx / cdist * cut
    const ey = ty - cdy / cdist * cut
    return `M${sx},${sy} Q${cx},${cy} ${ex},${ey}`
  }
  
  // 计算曲线中点（用于标签定位）
  const getLinkMidpoint = (d) => {
    const sx = d.source.x, sy = d.source.y
    const tx = d.target.x, ty = d.target.y
    
    // 检测自环
    if (d.isSelfLoop) {
      // 自环标签位置：节点右侧
      return { x: sx + 70, y: sy }
    }
    
    if (d.curvature === 0) {
      return { x: (sx + tx) / 2, y: (sy + ty) / 2 }
    }
    
    // 二次贝塞尔曲线的中点 t=0.5
    const dx = tx - sx, dy = ty - sy
    const dist = Math.sqrt(dx * dx + dy * dy)
    const pairTotal = d.pairTotal || 1
    const offsetRatio = 0.25 + pairTotal * 0.05
    const baseOffset = Math.max(35, dist * offsetRatio)
    const offsetX = -dy / dist * d.curvature * baseOffset
    const offsetY = dx / dist * d.curvature * baseOffset
    const cx = (sx + tx) / 2 + offsetX
    const cy = (sy + ty) / 2 + offsetY
    
    // 二次贝塞尔曲线公式 B(t) = (1-t)²P0 + 2(1-t)tP1 + t²P2, t=0.5
    const midX = 0.25 * sx + 0.5 * cx + 0.25 * tx
    const midY = 0.25 * sy + 0.5 * cy + 0.25 * ty
    
    return { x: midX, y: midY }
  }
  
  const link = linkGroup.selectAll('path')
    .data(edges)
    .enter().append('path')
    .attr('stroke', EDGE_COLOR_DEFAULT)
    .attr('stroke-width', 1.5)
    .attr('fill', 'none')
    // 有向边加箭头；自环组无方向语义，不加
    .attr('marker-end', d => (d.isSelfLoop ? null : edgeMarker(EDGE_COLOR_DEFAULT)))
    // 时间编码：invalid_at 已设置的过期事实淡化 + 虚线（元素级 opacity 连箭头一起淡化）
    .attr('stroke-dasharray', d => (isExpiredEdge(d) ? '4,3' : null))
    .attr('opacity', d => (isExpiredEdge(d) ? 0.35 : null))
    .style('cursor', 'pointer')
    .on('click', (event, d) => {
      event.stopPropagation()
      // 重置之前选中边的样式
      styleEdges(link, EDGE_COLOR_DEFAULT, 1.5)
      linkLabelBg.attr('fill', 'rgba(255,255,255,0.95)')
      linkLabels.attr('fill', '#666')
      // 高亮当前选中的边
      styleEdges(d3.select(event.target), EDGE_COLOR_ACTIVE, 3)

      selectEdgeItem(d.rawData)
    })

  // 边标签独立成组：显隐（开关/LOD）只需切换一个 <g> 的 display，而非逐元素改样式
  const edgeLabelGroup = g.append('g').attr('class', 'edge-labels')

  // Link labels background (白色背景使文字更清晰)
  const linkLabelBg = edgeLabelGroup.selectAll('rect')
    .data(edges)
    .enter().append('rect')
    .attr('fill', 'rgba(255,255,255,0.95)')
    .attr('rx', 3)
    .attr('ry', 3)
    .style('cursor', 'pointer')
    .style('pointer-events', 'all')
    .on('click', (event, d) => {
      event.stopPropagation()
      styleEdges(link, EDGE_COLOR_DEFAULT, 1.5)
      linkLabelBg.attr('fill', 'rgba(255,255,255,0.95)')
      linkLabels.attr('fill', '#666')
      // 高亮对应的边
      styleEdges(link.filter(l => l === d), EDGE_COLOR_ACTIVE, 3)
      d3.select(event.target).attr('fill', 'rgba(52, 152, 219, 0.1)')

      selectEdgeItem(d.rawData)
    })

  // Link labels
  const linkLabels = edgeLabelGroup.selectAll('text')
    .data(edges)
    .enter().append('text')
    .text(d => d.name)
    .attr('font-size', '9px')
    .attr('fill', '#666')
    .attr('text-anchor', 'middle')
    .attr('dominant-baseline', 'middle')
    .style('cursor', 'pointer')
    .style('pointer-events', 'all')
    .style('font-family', 'system-ui, sans-serif')
    .on('click', (event, d) => {
      event.stopPropagation()
      styleEdges(link, EDGE_COLOR_DEFAULT, 1.5)
      linkLabelBg.attr('fill', 'rgba(255,255,255,0.95)')
      linkLabels.attr('fill', '#666')
      // 高亮对应的边
      styleEdges(link.filter(l => l === d), EDGE_COLOR_ACTIVE, 3)
      d3.select(event.target).attr('fill', '#3498db')

      selectEdgeItem(d.rawData)
    })
  
  // ===== 边标签测量与定位（性能关键：绝不在 tick 中调用 getBBox）=====
  let edgeLabelsMeasured = false

  function edgeLabelsVisible() {
    return showEdgeLabels.value && !lodLabelsHidden
  }

  // 创建后只测量一次：批量 getBBox（纯读）后写入 datum 缓存，避免读写交错导致的逐元素回流
  function ensureEdgeLabelsMeasured() {
    if (edgeLabelsMeasured || !edgeLabelsVisible()) return
    linkLabels.each(function (d) {
      let w = 0
      let h = 0
      try {
        const b = this.getBBox()
        w = b.width
        h = b.height
      } catch (_e) { /* 隐藏元素在部分浏览器会抛错，走估算 */ }
      if (!(w > 0)) {
        const est = estimateLabelSize(d.name)
        w = est.w
        h = est.h
      }
      d._lw = w
      d._lh = h
    })
    edgeLabelsMeasured = true
  }

  // 用缓存的 bbox 写标签/背景位置（labelSel 与 bgSel 必须来自同一 data 顺序）
  function placeEdgeLabels(labelSel, bgSel) {
    const bgs = bgSel.nodes()
    labelSel.each(function (d, i) {
      const mid = getLinkMidpoint(d)
      this.setAttribute('x', mid.x)
      this.setAttribute('y', mid.y)
      const bg = bgs[i]
      if (!bg) return
      const w = d._lw || 24
      const h = d._lh || 11
      bg.setAttribute('x', mid.x - w / 2 - 4)
      bg.setAttribute('y', mid.y - h / 2 - 2)
      bg.setAttribute('width', w + 8)
      bg.setAttribute('height', h + 4)
    })
  }

  function placeAllEdgeLabels() {
    placeEdgeLabels(linkLabels, linkLabelBg)
  }

  function placeNodeLabels() {
    nodeLabels.attr('x', d => d.x).attr('y', d => d.y)
  }

  function updateLabelLayerVisibility() {
    const showEdge = edgeLabelsVisible()
    edgeLabelGroup.style('display', showEdge ? null : 'none')
    nodeLabelGroup.style('display', lodLabelsHidden ? 'none' : null)
    if (showEdge) {
      ensureEdgeLabelsMeasured()
      placeAllEdgeLabels() // 隐藏期间 tick 跳过了标签定位，重新显示时补一次
    }
    if (!lodLabelsHidden) placeNodeLabels()
  }

  // 视口剔除：缩放/平移结束或仿真静止后，隐藏视口外的标签（节点/边保留以维持整体形态感知）
  function applyViewportCull() {
    const t = latestTransform || d3.zoomIdentity
    const margin = 80
    const x0 = (0 - t.x) / t.k - margin
    const x1 = (width - t.x) / t.k + margin
    const y0 = (0 - t.y) / t.k - margin
    const y1 = (height - t.y) / t.k + margin
    const inView = (x, y) => !Number.isFinite(x) || !Number.isFinite(y) ||
      (x >= x0 && x <= x1 && y >= y0 && y <= y1)
    if (!lodLabelsHidden) {
      nodeLabels.style('display', d => inView(d.x, d.y) ? null : 'none')
    }
    if (edgeLabelsVisible()) {
      const bgs = linkLabelBg.nodes()
      linkLabels.each(function (d, i) {
        const mid = getLinkMidpoint(d)
        // 时间过滤隐藏的边，其标签也一并隐藏
        const disp = (!d._timeHidden && inView(mid.x, mid.y)) ? '' : 'none'
        this.style.display = disp
        if (bgs[i]) bgs[i].style.display = disp
      })
    }
  }

  // ===== 时间过滤（按 valid_at 截断）=====
  // 只切换 display，不动仿真/布局 —— 滑动过滤零布局开销
  function applyTimeFilter() {
    const cutoff = timeFilterCutoffMs
    link.each(function (d) {
      const t = edgeValidMs(d)
      d._timeHidden = cutoff != null && t != null && t > cutoff
      this.style.display = d._timeHidden ? 'none' : ''
    })
    // 标签的显隐经由视口剔除统一收敛（其判定已含 _timeHidden）
    applyViewportCull()
  }

  // 拖拽期间只更新被拖拽节点及其关联元素的选择集缓存（大图不重启全局仿真）
  let dragSelections = null

  // Nodes group
  const nodeGroup = g.append('g').attr('class', 'nodes')
  
  // T5.3: 研究种子节点的高亮外环（橙色），在节点 circle 之前绘制，置于其下方
  const seedRings = nodeGroup.selectAll('circle.seed-ring')
    .data(nodes.filter(d => isSeedNode(d)))
    .enter().append('circle')
    .attr('class', 'seed-ring')
    .attr('r', d => (d.r || 10) + 4)
    .attr('fill', 'none')
    .attr('stroke', '#FF4500')
    .attr('stroke-width', 2)
    .attr('stroke-dasharray', '3,2')
    .style('pointer-events', 'none')

  // Node circles
  const node = nodeGroup.selectAll('circle.node-dot')
    .data(nodes)
    .enter().append('circle')
    .attr('class', 'node-dot')
    .attr('r', d => d.r || 10)
    .attr('fill', d => getColor(d.type))
    .attr('stroke', '#fff')
    .attr('stroke-width', 2.5)
    .style('cursor', 'pointer')
    .call(d3.drag()
      .on('start', (event, d) => {
        // 只记录位置，不重启仿真（区分点击和拖拽）
        d.fx = d.x
        d.fy = d.y
        d._dragStartX = event.x
        d._dragStartY = event.y
        d._isDragging = false
        // 大图拖拽不重热全局仿真：预取被拖拽节点及其关联元素，逐帧只更新这些元素
        d._reheat = nodes.length <= DRAG_REHEAT_MAX_NODES
        if (!d._reheat) {
          dragSelections = {
            node: node.filter(n => n.id === d.id),
            ring: seedRings.filter(n => n.id === d.id),
            label: nodeLabels.filter(n => n.id === d.id),
            links: link.filter(l => l.source.id === d.id || l.target.id === d.id),
            linkLabels: linkLabels.filter(l => l.source.id === d.id || l.target.id === d.id),
            linkLabelBgs: linkLabelBg.filter(l => l.source.id === d.id || l.target.id === d.id)
          }
        }
      })
      .on('drag', (event, d) => {
        // 检测是否真正开始拖拽（移动超过阈值）
        const dx = event.x - d._dragStartX
        const dy = event.y - d._dragStartY
        const distance = Math.sqrt(dx * dx + dy * dy)

        if (!d._isDragging && distance > 3) {
          d._isDragging = true
          if (d._reheat) {
            // 小图：温和重热（0.1 而非 0.3），避免整图大幅重排
            simulation.alphaTarget(0.1).restart()
          }
        }

        if (d._isDragging) {
          d.fx = event.x
          d.fy = event.y
          if (!d._reheat && dragSelections) {
            // 大图：不惊动仿真，手动移动该节点及其关联边/标签
            d.x = event.x
            d.y = event.y
            dragSelections.node.attr('cx', d.x).attr('cy', d.y)
            dragSelections.ring.attr('cx', d.x).attr('cy', d.y)
            if (!lodLabelsHidden) dragSelections.label.attr('x', d.x).attr('y', d.y)
            dragSelections.links.attr('d', l => getLinkPath(l))
            if (edgeLabelsVisible()) placeEdgeLabels(dragSelections.linkLabels, dragSelections.linkLabelBgs)
          }
        }
      })
      .on('end', (event, d) => {
        // 只有小图（重热过）才需要让仿真逐渐停止
        if (d._isDragging && d._reheat) {
          simulation.alphaTarget(0)
        }
        d.fx = null
        d.fy = null
        d._isDragging = false
        dragSelections = null
      })
    )
    .on('click', (event, d) => {
      event.stopPropagation()
      // 重置所有节点样式
      node.attr('stroke', '#fff').attr('stroke-width', 2.5)
      styleEdges(link, EDGE_COLOR_DEFAULT, 1.5)
      // 高亮选中节点
      d3.select(event.target).attr('stroke', '#E91E63').attr('stroke-width', 4)
      // 高亮与此节点相连的边
      styleEdges(
        link.filter(l => l.source.id === d.id || l.target.id === d.id),
        EDGE_COLOR_ACCENT,
        2.5
      )

      selectNodeItem(d, getColor(d.type))

      // 聚焦模式：点击同时展开该节点的一跳邻居（保留现有节点位置，仅新节点参与布局）
      if (focusModeActive.value) expandNodeNeighbors(d)
    })
    .on('mouseenter', (event, d) => {
      if (!selectedItem.value || selectedItem.value.data?.uuid !== d.rawData.uuid) {
        d3.select(event.target).attr('stroke', '#333').attr('stroke-width', 3)
      }
    })
    .on('mouseleave', (event, d) => {
      if (!selectedItem.value || selectedItem.value.data?.uuid !== d.rawData.uuid) {
        d3.select(event.target).attr('stroke', '#fff').attr('stroke-width', 2.5)
      }
    })

  // 悬停显示完整名称（原生 SVG <title>，零渲染开销）
  node.append('title').text(d => d.name)

  // 搜索命中高亮环：单个元素，ticked 时跟随命中节点
  const searchRing = nodeGroup.append('circle')
    .attr('class', 'search-ring')
    .attr('fill', 'none')
    .attr('stroke', '#E91E63')
    .attr('stroke-width', 3)
    .style('display', 'none')
    .style('pointer-events', 'none')
  let searchFocusDatum = null

  // Node Labels —— 独立成组，LOD 显隐只切换组的 display
  const nodeLabelGroup = g.append('g').attr('class', 'node-labels')
  const nodeLabels = nodeLabelGroup.selectAll('text')
    .data(nodes)
    .enter().append('text')
    .text(d => d.name.length > 18 ? d.name.substring(0, 18) + '…' : d.name)
    .attr('font-size', '11px')
    .attr('fill', '#333')
    .attr('font-weight', '500')
    .attr('dx', d => (d.r || 10) + 4)
    .attr('dy', 4)
    .style('pointer-events', 'none')
    .style('font-family', 'system-ui, sans-serif')

  // tick 处理器：只写坐标属性，不做任何 getBBox 等强制回流的读操作；
  // 标签隐藏（开关关闭或低倍率 LOD）时整段跳过标签定位。
  function ticked() {
    // 更新曲线路径
    link.attr('d', d => getLinkPath(d))

    // 更新边标签位置（bbox 用创建时缓存的尺寸，无旋转，水平显示更清晰）
    if (edgeLabelsVisible()) {
      ensureEdgeLabelsMeasured()
      placeAllEdgeLabels()
    }

    node
      .attr('cx', d => d.x)
      .attr('cy', d => d.y)

    seedRings
      .attr('cx', d => d.x)
      .attr('cy', d => d.y)

    if (searchFocusDatum) {
      searchRing.attr('cx', searchFocusDatum.x).attr('cy', searchFocusDatum.y)
    }

    if (!lodLabelsHidden) placeNodeLabels()
  }

  simulation.on('tick', ticked).on('end', () => {
    // 布局静止后做一次标签视口剔除
    if (sceneReady) applyViewportCull()
  })

  // 点击空白处关闭详情面板
  svg.on('click', () => {
    closeDetailPanel()
    node.attr('stroke', '#fff').attr('stroke-width', 2.5)
    styleEdges(link, EDGE_COLOR_DEFAULT, 1.5)
    linkLabelBg.attr('fill', 'rgba(255,255,255,0.95)')
    linkLabels.attr('fill', '#666')
  })

  // ===== 场景级搜索接口（模块级 runSearch/onSearchEnter 经 searchSceneApi 调用） =====
  let searchMatches = []
  searchSceneApi = {
    setQuery(queryNorm) {
      if (!queryNorm) {
        searchMatches = []
        searchFocusDatum = null
        searchRing.style('display', 'none')
        return 0
      }
      searchMatches = nodes.filter(n => normalizeSearchText(n.name).includes(queryNorm))
      if (!searchMatches.length) {
        searchFocusDatum = null
        searchRing.style('display', 'none')
      }
      return searchMatches.length
    },
    focusMatch(index) {
      if (!searchMatches.length) return
      const datum = searchMatches[((index % searchMatches.length) + searchMatches.length) % searchMatches.length]
      if (!datum || !Number.isFinite(datum.x) || !Number.isFinite(datum.y)) return
      searchFocusDatum = datum
      searchRing
        .style('display', null)
        .attr('r', (datum.r || 10) + 5)
        .attr('cx', datum.x)
        .attr('cy', datum.y)
      // 平移/缩放到命中节点（沿用 zoomBehavior，RAF 合并管线不变）
      const k = Math.max(latestTransform.k, 1)
      const t = d3.zoomIdentity
        .translate(width / 2 - k * datum.x, height / 2 - k * datum.y)
        .scale(k)
      svg.transition().duration(400).call(zoomBehavior.transform, t)
    },
  }

  // ===== 时间过滤数据源：当前渲染边的 valid_at 全集（跨重渲染保留语义截断点） =====
  const validTimeSet = new Set()
  edges.forEach(e => {
    const t = edgeValidMs(e)
    if (t != null) validTimeSet.add(t)
  })
  const sortedValidTimes = [...validTimeSet].sort((a, b) => a - b)
  timeFilterTimes.value = sortedValidTimes
  if (timeFilterCutoffMs == null || !sortedValidTimes.length) {
    timeFilterCutoffMs = null
    timeFilterIndex.value = sortedValidTimes.length
  } else {
    // 语义截断点吸附到新时间轴的对应刻度，保证滑块标签与实际过滤一致
    const idx = Math.max(0, sortedValidTimes.filter(t => t <= timeFilterCutoffMs).length - 1)
    timeFilterCutoffMs = sortedValidTimes[idx]
    timeFilterIndex.value = idx
  }

  // 初始可见性 + 首帧绘制（预计算布局/低 alpha 时也能即刻成图）
  updateLabelLayerVisibility()
  ticked()

  // 模块级句柄：边标签开关 watcher / 时间过滤 watcher 使用
  updateLabelLayerVisibilityFn = updateLabelLayerVisibility
  applyTimeFilterFn = applyTimeFilter
  sceneReady = true

  // 持久化的时间截断在新场景上重放（无截断时也顺带初始化 _timeHidden 标记）
  applyTimeFilter()
  // 输入框里有保留的查询词时，静默刷新匹配集（不平移视口）
  if (searchQuery.value) runSearch()
}

// 廉价响应式触发：监听引用与节点/边数量变化，替代对整个 graphData 的 deep watch
// （深度遍历上千节点/边的代价与全量重建一样高，且节点内部字段变化并不需要重绘）
watch(
  () => [props.graphData, props.graphData?.nodes?.length ?? 0, props.graphData?.edges?.length ?? 0],
  () => {
    scheduleRender()
  }
)

// 监听边标签显示开关：组级 display 切换 + 重新显示时补测量/定位
watch(showEdgeLabels, () => {
  if (updateLabelLayerVisibilityFn) updateLabelLayerVisibilityFn()
})

// 窗口尺寸变化去抖（约 200ms），避免连续 resize 触发多次全量重建
let resizeTimer = null
const handleResize = () => {
  if (resizeTimer) clearTimeout(resizeTimer)
  resizeTimer = setTimeout(() => {
    resizeTimer = null
    scheduleRender()
  }, RESIZE_DEBOUNCE_MS)
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
  // 组件挂载时若已有数据（如视图切换回来），立即渲染一次
  if (props.graphData) scheduleRender()
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (resizeTimer) {
    clearTimeout(resizeTimer)
    resizeTimer = null
  }
  updateLabelLayerVisibilityFn = null
  applyTimeFilterFn = null
  searchSceneApi = null
  if (currentSimulation) {
    currentSimulation.stop()
  }
})
</script>

<style scoped>
.graph-translation-status { position: absolute; top: 58px; left: 10px; right: 10px; z-index: 5; }
.graph-panel {
  position: relative;
  width: 100%;
  height: 100%;
  background-color: #FAFAFA;
  background-image: radial-gradient(#D0D0D0 1.5px, transparent 1.5px);
  background-size: 24px 24px;
  overflow: hidden;
}

.panel-header {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  padding: 16px 20px;
  z-index: 10;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: linear-gradient(to bottom, rgba(255,255,255,0.95), rgba(255,255,255,0));
  pointer-events: none;
}

.panel-title {
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--color-ink, #0A0A0A);
  pointer-events: auto;
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.panel-diamond {
  color: var(--color-accent, #FF4500);
  font-size: 12px;
  line-height: 1;
}

.header-tools {
  pointer-events: auto;
  display: flex;
  gap: 10px;
  align-items: center;
}

.tool-btn {
  height: 32px;
  padding: 0 12px;
  border: 1px solid var(--color-border, #E5E5E5);
  background: #FFF;
  border-radius: var(--radius, 2px);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  cursor: pointer;
  color: #666;
  transition: background var(--dur-1, 120ms) var(--ease, ease), color var(--dur-1, 120ms) var(--ease, ease), border-color var(--dur-1, 120ms) var(--ease, ease);
  box-shadow: var(--shadow-sm, 0 1px 3px rgba(10,10,10,0.06));
  font-size: 13px;
}

.tool-btn:hover {
  background: var(--color-soft, #FAFAFA);
  color: #000;
  border-color: var(--color-accent, #FF4500);
}

.tool-btn .btn-text {
  font-size: 12px;
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
}

/* 节点搜索输入框（跟随 tool-btn 视觉） */
.graph-search {
  display: flex;
  align-items: center;
  gap: 6px;
}

.search-input {
  height: 32px;
  width: 150px;
  padding: 0 10px;
  border: 1px solid var(--color-border, #E5E5E5);
  background: #FFF;
  border-radius: var(--radius, 2px);
  font-size: 12px;
  color: #333;
  box-shadow: var(--shadow-sm, 0 1px 3px rgba(10,10,10,0.06));
  outline: none;
  transition: border-color var(--dur-2, 180ms) var(--ease, ease);
}

.search-input:focus {
  border-color: var(--color-accent, #FF4500);
}

.search-count {
  font-size: 11px;
  color: #888;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

/* 时间过滤（按 valid_at 截断边） */
.time-filter {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--color-border, #E5E5E5);
  background: #FFF;
  border-radius: var(--radius, 2px);
  box-shadow: var(--shadow-sm, 0 1px 3px rgba(10,10,10,0.06));
}

.time-filter-label {
  font-size: 11px;
  color: #666;
  white-space: nowrap;
  min-width: 74px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.time-filter-slider {
  width: 90px;
  accent-color: var(--color-accent, #FF4500);
  cursor: pointer;
}

.icon-refresh.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

.graph-container {
  width: 100%;
  height: 100%;
}

.graph-view, .graph-svg {
  width: 100%;
  height: 100%;
  display: block;
}

.graph-state {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  color: #999;
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 13px;
}

.empty-icon {
  font-size: 40px;
  margin-bottom: 16px;
  color: var(--color-accent, #FF4500);
  opacity: 0.55;
}

/* Entity Types Legend - Bottom Left */
.graph-legend {
  position: absolute;
  bottom: 24px;
  left: 24px;
  background: rgba(255,255,255,0.95);
  padding: 12px 16px;
  border-radius: var(--radius, 2px);
  border: 1px solid var(--color-border, #E5E5E5);
  box-shadow: var(--shadow-md, 0 2px 10px rgba(10,10,10,0.08));
  z-index: 10;
}

.legend-title {
  display: block;
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 10px;
  font-weight: 600;
  color: var(--color-muted, #666);
  margin-bottom: 10px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.legend-items {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 16px;
  max-width: 320px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #555;
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.legend-label {
  white-space: nowrap;
}

/* T5.3: 研究种子图例点（空心橙色虚环，呼应图谱里的 seed-ring） */
.seed-legend-dot {
  background: transparent;
  border: 2px dashed #FF4500;
  width: 12px;
  height: 12px;
}

/* 聚焦模式提示条（大图 Top-K 子图） */
.graph-focus-banner {
  position: absolute;
  top: 60px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 12px;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid var(--color-border, #E5E5E5);
  border-radius: var(--radius-pill, 999px);
  padding: 8px 14px;
  box-shadow: var(--shadow-md, 0 2px 10px rgba(10,10,10,0.08));
  z-index: 15;
  max-width: calc(100% - 48px);
}

.graph-focus-banner .focus-text {
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 11px;
  color: #555;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.graph-focus-banner .focus-expanding {
  color: var(--color-accent, #FF4500);
}

.graph-focus-banner .focus-btn {
  flex-shrink: 0;
  height: 26px;
  padding: 0 12px;
  border: 1px solid var(--color-accent, #FF4500);
  background: #FFF;
  color: var(--color-accent, #FF4500);
  border-radius: var(--radius-pill, 999px);
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 11px;
  cursor: pointer;
  transition: background var(--dur-1, 120ms) var(--ease, ease), color var(--dur-1, 120ms) var(--ease, ease);
}

.graph-focus-banner .focus-btn:hover {
  background: var(--color-accent, #FF4500);
  color: #FFF;
}

.graph-focus-banner .focus-btn:disabled {
  cursor: wait;
  opacity: 0.6;
}

/* Edge Labels Toggle - Top Right */
.edge-labels-toggle {
  position: absolute;
  top: 60px;
  right: 20px;
  display: flex;
  align-items: center;
  gap: 10px;
  background: #FFF;
  padding: 8px 14px;
  border-radius: var(--radius-pill, 999px);
  border: 1px solid var(--color-border, #E5E5E5);
  box-shadow: var(--shadow-md, 0 2px 10px rgba(10,10,10,0.08));
  z-index: 10;
}

.toggle-switch {
  position: relative;
  display: inline-block;
  width: 40px;
  height: 22px;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #E0E0E0;
  border-radius: 22px;
  transition: 0.3s;
}

.slider:before {
  position: absolute;
  content: "";
  height: 16px;
  width: 16px;
  left: 3px;
  bottom: 3px;
  background-color: white;
  border-radius: 50%;
  transition: 0.3s;
}

input:checked + .slider {
  background-color: var(--color-ink, #0A0A0A);
}

input:checked + .slider:before {
  transform: translateX(18px);
}

/* Keyboard focus on the visually-hidden checkbox lights up the switch. */
input:focus-visible + .slider {
  outline: 2px solid var(--color-accent, #FF4500);
  outline-offset: 2px;
}

.toggle-label {
  font-size: 12px;
  color: #666;
}

/* Detail Panel - Right Side */
.detail-panel {
  position: absolute;
  top: 60px;
  right: 20px;
  width: 320px;
  max-height: calc(100% - 100px);
  background: #FFF;
  border: 1px solid var(--color-border, #E5E5E5);
  border-radius: var(--radius, 2px);
  box-shadow: var(--shadow-lg, 0 8px 32px rgba(10,10,10,0.12));
  overflow: hidden;
  font-family: var(--font-sans, 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif);
  font-size: 13px;
  z-index: 20;
  display: flex;
  flex-direction: column;
}

.detail-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  background: #FAFAFA;
  border-bottom: 1px solid #EEE;
  flex-shrink: 0;
}

.detail-title {
  font-weight: 600;
  color: #333;
  font-size: 14px;
}

.detail-type-badge {
  padding: 4px 10px;
  border-radius: var(--radius-pill, 999px);
  font-size: 11px;
  font-weight: 500;
  margin-left: auto;
  margin-right: 12px;
}

.detail-close {
  background: none;
  border: none;
  font-size: 20px;
  cursor: pointer;
  color: #999;
  line-height: 1;
  padding: 0;
  transition: color 0.2s;
}

.detail-close:hover {
  color: #333;
}

.detail-content {
  padding: 16px;
  overflow-y: auto;
  flex: 1;
}

.detail-status {
  padding: 8px 16px;
  color: #666;
  background: #F7F7FA;
  border-bottom: 1px solid #EEE;
  font-size: 12px;
}

.detail-status.detail-error {
  color: var(--color-warn, #D97706);
  background: #FFF8ED;
}

.detail-row {
  margin-bottom: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.detail-label {
  color: #888;
  font-size: 12px;
  font-weight: 500;
  min-width: 80px;
}

.detail-value {
  color: #333;
  flex: 1;
  word-break: break-word;
}

.detail-value.uuid-text {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #666;
}

.detail-value.fact-text {
  line-height: 1.5;
  color: #444;
}

.detail-section {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid #F0F0F0;
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: #666;
  margin-bottom: 10px;
}

.properties-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.property-item {
  display: flex;
  gap: 8px;
}

.property-key {
  color: #888;
  font-weight: 500;
  min-width: 90px;
}

.property-value {
  color: #333;
  flex: 1;
}

.summary-text {
  line-height: 1.6;
  color: #444;
  font-size: 12px;
}

.labels-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.label-tag {
  display: inline-block;
  padding: 4px 12px;
  background: #F5F5F5;
  border: 1px solid var(--color-border, #E5E5E5);
  border-radius: var(--radius-pill, 999px);
  font-size: 11px;
  color: #555;
}

.episodes-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.episode-tag {
  display: inline-block;
  padding: 6px 10px;
  background: #F8F8F8;
  border: 1px solid #E8E8E8;
  border-radius: var(--radius, 2px);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #666;
  word-break: break-all;
}

/* Edge relation header */
.edge-relation-header {
  background: #F8F8F8;
  padding: 12px;
  border-radius: var(--radius, 2px);
  margin-bottom: 16px;
  font-size: 13px;
  font-weight: 500;
  color: #333;
  line-height: 1.5;
  word-break: break-word;
}

/* Building hint */
.graph-building-hint {
  position: absolute;
  bottom: 160px; /* Moved up from 80px */
  left: 50%;
  transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(8px);
  color: #fff;
  padding: 10px 20px;
  border-radius: 30px;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 10px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
  border: 1px solid rgba(255, 255, 255, 0.1);
  font-weight: 500;
  letter-spacing: 0.5px;
  z-index: 100;
}

.memory-icon-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  animation: breathe 2s ease-in-out infinite;
}

.memory-icon {
  width: 18px;
  height: 18px;
  color: var(--color-ok, #16A34A);
}

@keyframes breathe {
  0%, 100% { opacity: 0.7; transform: scale(1); filter: drop-shadow(0 0 2px rgba(22, 163, 74, 0.3)); }
  50% { opacity: 1; transform: scale(1.15); filter: drop-shadow(0 0 8px rgba(22, 163, 74, 0.6)); }
}

/* 模拟结束后的提示样式 */
.graph-building-hint.finished-hint {
  background: rgba(0, 0, 0, 0.65);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.finished-hint .hint-icon-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
}

.finished-hint .hint-icon {
  width: 18px;
  height: 18px;
  color: #FFF;
}

.finished-hint .hint-text {
  flex: 1;
  white-space: nowrap;
}

.hint-close-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  background: rgba(255, 255, 255, 0.2);
  border: none;
  border-radius: 50%;
  cursor: pointer;
  color: #FFF;
  transition: all 0.2s;
  margin-left: 8px;
  flex-shrink: 0;
}

.hint-close-btn:hover {
  background: rgba(255, 255, 255, 0.35);
  transform: scale(1.1);
}

/* Loading spinner */
.loading-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--color-border, #E5E5E5);
  border-top-color: var(--color-accent, #FF4500);
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 16px;
}

/* Self-loop styles */
.self-loop-header {
  display: flex;
  align-items: center;
  gap: 8px;
  background: linear-gradient(135deg, #E8F5E9 0%, #F1F8E9 100%);
  border: 1px solid #C8E6C9;
}

.self-loop-count {
  margin-left: auto;
  font-size: 11px;
  color: #666;
  background: rgba(255,255,255,0.8);
  padding: 2px 8px;
  border-radius: 10px;
}

.self-loop-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.self-loop-item {
  background: #FAFAFA;
  border: 1px solid var(--color-border, #E5E5E5);
  border-radius: var(--radius, 2px);
}

.self-loop-item-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: #F5F5F5;
  cursor: pointer;
  transition: background 0.2s;
}

.self-loop-item-header:hover {
  background: #EEEEEE;
}

.self-loop-item.expanded .self-loop-item-header {
  background: #E8E8E8;
}

.self-loop-index {
  font-size: 10px;
  font-weight: 600;
  color: #888;
  background: #E0E0E0;
  padding: 2px 6px;
  border-radius: 4px;
}

.self-loop-name {
  font-size: 12px;
  font-weight: 500;
  color: #333;
  flex: 1;
}

.self-loop-toggle {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  color: #888;
  background: #E0E0E0;
  border-radius: 4px;
  transition: all 0.2s;
}

.self-loop-item.expanded .self-loop-toggle {
  background: #D0D0D0;
  color: #666;
}

.self-loop-item-content {
  padding: 12px;
  border-top: 1px solid #EAEAEA;
}

.self-loop-item-content .detail-row {
  margin-bottom: 8px;
}

.self-loop-item-content .detail-label {
  font-size: 11px;
  min-width: 60px;
}

.self-loop-item-content .detail-value {
  font-size: 12px;
}

.self-loop-episodes {
  margin-top: 8px;
}

.episodes-list.compact {
  flex-direction: row;
  flex-wrap: wrap;
  gap: 4px;
}

.episode-tag.small {
  padding: 3px 6px;
  font-size: 9px;
}
</style>
