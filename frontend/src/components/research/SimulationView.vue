<template>
  <WorldSimulationView
    v-if="engine === WORLD_ENGINE"
    :key="simulationId + ':' + worldGenerationId"
    :simulation-id="simulationId"
    :generation-id="worldGenerationId"
  />
  <div v-else-if="engine === LEGACY_ENGINE" class="sim-view">
    <!-- ===== Header ===== -->
    <header class="sv-header">
      <div class="sv-title">
        <span class="diamond">◇</span>
        <span class="sv-title-text">{{ L('群体模拟 · OASIS','Crowd Simulation · OASIS') }}</span>
      </div>

      <div class="sv-controls">
        <!-- Platform segmented toggle -->
        <div class="segmented" role="tablist" :aria-label="L('平台选择','Select platform')">
          <button
            type="button"
            class="seg-btn"
            :class="{ active: platform === 'twitter' }"
            :aria-pressed="platform === 'twitter'"
            @click="switchPlatform('twitter')"
          >Twitter</button>
          <button
            type="button"
            class="seg-btn"
            :class="{ active: platform === 'reddit' }"
            :aria-pressed="platform === 'reddit'"
            @click="switchPlatform('reddit')"
          >Reddit</button>
        </div>

        <!-- Refresh -->
        <button
          type="button"
          class="refresh-btn"
          :disabled="loading"
          @click="loadAll"
          :title="L('刷新数据','Refresh data')"
        >
          <svg class="refresh-icon" :class="{ spinning: loading }" width="14" height="14" viewBox="0 0 24 24"
            fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <polyline points="23 4 23 10 17 10" />
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
          </svg>
          <span class="refresh-label">{{ L('刷新','Refresh') }}</span>
        </button>
      </div>
    </header>

    <!-- ===== Error banner ===== -->
    <div v-if="error" class="sv-error">
      <span class="err-dot">●</span>
      <span class="err-text">{{ error }}</span>
    </div>

    <!-- ===== Stats strip ===== -->
    <section class="stats-strip" v-if="statTiles.length || hasRoundInfo">
      <div class="stat-tile" v-if="hasRoundInfo">
        <span class="stat-label">{{ L('回合','Round') }}</span>
        <span class="stat-value mono">{{ roundLabel }}</span>
      </div>
      <div class="stat-tile" v-if="runnerStatus">
        <span class="stat-label">{{ L('运行状态','Status') }}</span>
        <span class="stat-value mono">{{ runnerStatus }}</span>
      </div>
      <div
        class="stat-tile"
        v-for="tile in statTiles"
        :key="tile.key"
      >
        <span class="stat-label">{{ tile.label }}</span>
        <span class="stat-value mono">{{ tile.value }}</span>
      </div>
    </section>

    <!-- ===== World state (reflexive simulation) ===== -->
    <WorldStatePanel
      :simulation-id="props.simulationId"
      :refresh-token="refreshToken"
      :round="selectedRound"
      @update:selected-round="onSelectRound"
    />

    <!-- ===== Two columns ===== -->
    <div class="sv-columns">
      <!-- LEFT: Personas -->
      <section class="col col-personas">
        <div class="col-head">
          <span class="diamond sm">◇</span>
          <span class="col-label">{{ L('数字人设','Personas') }} ({{ profiles.length }})</span>
        </div>

        <div class="col-body scroll" v-if="profiles.length">
          <article
            class="persona-card"
            v-for="(p, idx) in profiles"
            :key="personaKey(p, idx)"
          >
            <div class="persona-top">
              <div class="persona-avatar" :style="avatarStyle(personaName(p))">
                {{ initialOf(personaName(p)) }}
              </div>
              <div class="persona-id">
                <span class="persona-name">{{ personaName(p) }}</span>
                <span class="persona-type" v-if="personaType(p)">{{ personaType(p) }}</span>
              </div>
            </div>
            <p class="persona-snippet" v-if="personaSnippet(p)">{{ personaSnippet(p) }}</p>
            <p class="persona-snippet empty" v-else>{{ L('暂无人设描述','No persona description') }}</p>
          </article>
        </div>

        <div class="empty-state" v-else-if="!loading">
          <span class="empty-icon">◇</span>
          <span class="empty-text">{{ L('模拟尚未运行或暂无数据','Simulation not started or no data yet') }}</span>
        </div>

        <div class="empty-state" v-else>
          <span class="empty-icon loading-dot">●</span>
          <span class="empty-text">{{ L('加载中…','Loading…') }}</span>
        </div>
      </section>

      <!-- RIGHT: Feed -->
      <section class="col col-feed">
        <div class="col-head">
          <span class="diamond sm">◇</span>
          <span class="col-label">{{ L('信息流','Feed') }} ({{ posts.length }})</span>
          <span class="feed-period mono" v-if="selectedRound !== null">
            · {{ selectedPeriodLabel }}
          </span>
          <button type="button" class="feed-all mono" v-if="selectedRound !== null" @click="showAllPeriods">
            ↩ {{ L('全部时段','all periods') }}
          </button>
        </div>

        <div class="col-body scroll" v-if="posts.length">
          <article
            class="post-card"
            v-for="(post, idx) in posts"
            :key="postKey(post, idx)"
          >
            <div class="post-head">
              <div class="post-avatar" :style="avatarStyle(authorName(post))">
                {{ initialOf(authorName(post)) }}
              </div>
              <div class="post-meta">
                <span class="post-author">{{ authorName(post) }}</span>
                <span class="post-sub">
                  <span class="plat-tag">{{ platformTag }}</span>
                  <span class="post-time mono" v-if="relativeTime(post)">· {{ relativeTime(post) }}</span>
                  <span class="post-period mono" v-if="periodNote(post)">· {{ periodNote(post) }}</span>
                </span>
              </div>
            </div>

            <p class="post-text" v-if="postText(post)">{{ postText(post) }}</p>
            <p class="post-text empty" v-else>{{ L('（无内容）','(No content)') }}</p>

            <div class="post-metrics" v-if="hasLikes(post)">
              <span class="metric">♥ {{ likeCount(post) }}</span>
            </div>

            <!-- Replies (nested under their parent post) -->
            <div class="post-replies" v-if="repliesFor(post).length">
              <div class="replies-head">
                <span class="replies-count">{{ repliesFor(post).length }}
                  {{ L('条回复','repl' + (repliesFor(post).length === 1 ? 'y' : 'ies')) }}</span>
              </div>
              <article
                class="reply-card"
                v-for="(c, cidx) in repliesFor(post)"
                :key="commentKey(c, cidx)"
              >
                <div class="reply-head">
                  <div class="reply-avatar" :style="avatarStyle(commentAuthorName(c))">
                    {{ initialOf(commentAuthorName(c)) }}
                  </div>
                  <span class="reply-author">{{ commentAuthorName(c) }}</span>
                  <span class="reply-time mono" v-if="relativeTime(c)">· {{ relativeTime(c) }}</span>
                </div>
                <p class="reply-text">{{ commentText(c) }}</p>
                <div class="reply-metrics" v-if="commentLikeCount(c)">
                  <span class="metric">♥ {{ commentLikeCount(c) }}</span>
                </div>
              </article>
            </div>
          </article>
        </div>

        <div class="empty-state" v-else-if="!loading && selectedRound !== null">
          <span class="empty-icon">◇</span>
          <span class="empty-text">{{ L('本时段无帖子','No posts in this period') }} · {{ selectedPeriodLabel }}</span>
        </div>

        <div class="empty-state" v-else-if="!loading">
          <span class="empty-icon">◇</span>
          <span class="empty-text">{{ L('模拟尚未运行或暂无数据','Simulation not started or no data yet') }}</span>
        </div>

        <div class="empty-state" v-else>
          <span class="empty-icon loading-dot">●</span>
          <span class="empty-text">{{ L('加载中…','Loading…') }}</span>
        </div>
      </section>
    </div>
  </div>
  <section v-else class="sim-view" :aria-busy="loading">
    <p :role="error ? 'alert' : 'status'">{{ error || (loading
      ? L('正在读取已保存的模拟…', 'Reading saved simulation…')
      : L('尚未选择模拟', 'No simulation selected')) }}</p>
    <button v-if="simulationId" type="button" class="refresh-btn" :disabled="loading" @click="loadAll">
      {{ L('重试', 'Retry') }}
    </button>
  </section>
</template>

<script setup>
import { ref, computed, onUnmounted, watch } from 'vue'
import { L } from '../../i18n'
import WorldStatePanel from './WorldStatePanel.vue'
import WorldSimulationView from './WorldSimulationView.vue'
import { WORLD_ENGINE, LEGACY_ENGINE, WORLD_REQUEST_TIMEOUT_MS, savedSimulationEngine, createRequestGate } from '../../utils/worldSimulationView'
import {
  getSimulation,
  getSimulationProfilesRealtime,
  getSimulationPosts,
  getSimulationComments,
  getFeedRounds,
  getAgentStats,
  getRunStatus
} from '../../api/simulation'
import { feedRequest, postPeriodNote, roundLabel as periodRoundLabel, selectionFromPanel } from '../../utils/feedRounds'

const props = defineProps({
  simulationId: { type: String, default: '' }
})

// ===== Local state =====
const platform = ref('twitter') // 'twitter' | 'reddit'
const profiles = ref([])
const posts = ref([])
const comments = ref([])
// PERIOD VIEW: the committed round pinned in the World State panel (null = latest posts),
// the feed's round index (labels + counts) and the label the server returned for the page
const selectedRound = ref(null)
const feedRounds = ref([])
const feedPeriodLabel = ref('')
const stats = ref({})
const runState = ref({})
const userMap = ref({})
const loading = ref(false)
const error = ref('')
const refreshToken = ref(0) // bumps on every loadAll so the world-state panel reloads with the feed
const engine = ref(null)
const worldGenerationId = ref('')
const requests = createRequestGate()
let refreshTimer = null

// ===== Defensive helpers =====
function asArray(v) {
  return Array.isArray(v) ? v : []
}

function isPlainObject(v) {
  return v != null && typeof v === 'object' && !Array.isArray(v)
}

// Normalize profiles: res.data may be an array, or { profiles: [...] }
function normalizeProfiles(data) {
  if (Array.isArray(data)) return data
  if (isPlainObject(data) && Array.isArray(data.profiles)) return data.profiles
  return []
}

// Build userId -> name map from profiles
function buildUserMap(list) {
  const map = {}
  asArray(list).forEach((p) => {
    if (!isPlainObject(p)) return
    const id = p.user_id ?? p.agent_id ?? p.id
    if (id === undefined || id === null) return
    const name = personaName(p)
    if (name) map[String(id)] = name
  })
  return map
}

// ===== Persona accessors (all guarded) =====
function personaName(p) {
  if (!isPlainObject(p)) return ''
  return (p.name || p.user_name || p.username || '').toString().trim()
}

function personaType(p) {
  if (!isPlainObject(p)) return ''
  return (p.type || p.category || '').toString().trim()
}

function personaSnippet(p) {
  if (!isPlainObject(p)) return ''
  const raw = p.persona || p.bio || p.description || p.self_description || ''
  return raw == null ? '' : String(raw).trim()
}

function personaKey(p, idx) {
  if (isPlainObject(p)) {
    const id = p.user_id ?? p.agent_id ?? p.id
    if (id !== undefined && id !== null) return 'p-' + id + '-' + idx
  }
  return 'p-' + idx
}

// ===== Post accessors (all guarded) =====
function postText(post) {
  if (!isPlainObject(post)) return ''
  const raw = post.content ?? post.text ?? post.message ?? ''
  return raw == null ? '' : String(raw).trim()
}

function authorName(post) {
  if (!isPlainObject(post)) return 'Agent'
  const id = post.user_id ?? post.agent_id ?? post.author_id ?? post.id
  if (id !== undefined && id !== null) {
    const mapped = userMap.value[String(id)]
    if (mapped) return mapped
    return 'Agent ' + id
  }
  return 'Agent'
}

function likeCount(post) {
  if (!isPlainObject(post)) return 0
  const v = post.num_likes ?? post.likes ?? post.like_count
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

function hasLikes(post) {
  if (!isPlainObject(post)) return false
  const v = post.num_likes ?? post.likes ?? post.like_count
  return v !== undefined && v !== null && Number.isFinite(Number(v))
}

function postKey(post, idx) {
  if (isPlainObject(post)) {
    const id = post.post_id ?? post.id
    if (id !== undefined && id !== null) return 'post-' + id + '-' + idx
  }
  return 'post-' + idx
}

// ===== Comment accessors (all guarded) =====
function commentText(c) {
  if (!isPlainObject(c)) return ''
  const raw = c.content ?? c.text ?? c.message ?? ''
  return raw == null ? '' : String(raw).trim()
}

function commentAuthorName(c) {
  if (!isPlainObject(c)) return 'Agent'
  const id = c.user_id ?? c.agent_id ?? c.author_id ?? c.id
  if (id !== undefined && id !== null) {
    const mapped = userMap.value[String(id)]
    if (mapped) return mapped
    return 'Agent ' + id
  }
  return 'Agent'
}

function commentLikeCount(c) {
  if (!isPlainObject(c)) return 0
  const v = c.num_likes ?? c.likes ?? c.like_count
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

function commentKey(c, idx) {
  if (isPlainObject(c)) {
    const id = c.comment_id ?? c.id
    if (id !== undefined && id !== null) return 'comment-' + id + '-' + idx
  }
  return 'comment-' + idx
}

// Group comments by their parent post_id, oldest-first within each thread so a
// reply chain reads top-to-bottom in chronological order (comments arrive from
// the API newest-first, matching the posts feed's ordering).
const commentsByPost = computed(() => {
  const map = {}
  for (const c of asArray(comments.value)) {
    if (!isPlainObject(c)) continue
    const pid = c.post_id
    if (pid === undefined || pid === null) continue
    const key = String(pid)
    if (!map[key]) map[key] = []
    map[key].push(c)
  }
  for (const key of Object.keys(map)) {
    map[key].sort((a, b) => {
      const ta = Date.parse(a.created_at ?? a.timestamp ?? '') || 0
      const tb = Date.parse(b.created_at ?? b.timestamp ?? '') || 0
      return ta - tb
    })
  }
  return map
})

function repliesFor(post) {
  if (!isPlainObject(post)) return []
  const pid = post.post_id ?? post.id
  if (pid === undefined || pid === null) return []
  return commentsByPost.value[String(pid)] || []
}

// ===== Period view (the World State panel's selection drives the feed) =====
const selectedPeriodLabel = computed(() =>
  selectedRound.value === null ? '' : periodRoundLabel(feedRounds.value, selectedRound.value, feedPeriodLabel.value))

function onSelectRound(value) {
  const next = selectionFromPanel(value)
  if (next === selectedRound.value) return
  selectedRound.value = next
  loadAll()
}

function showAllPeriods() {
  onSelectRound(null)
}

function periodNote(post) {
  return postPeriodNote(post, selectedRound.value, feedRounds.value, L('发表于', 'posted in'))
}

// ===== Time formatting =====
function relativeTime(post) {
  if (!isPlainObject(post)) return ''
  const rawTs = post.created_at ?? post.timestamp ?? post.time
  if (rawTs === undefined || rawTs === null || rawTs === '') return ''
  let ms
  if (typeof rawTs === 'number') {
    // seconds vs milliseconds heuristic
    ms = rawTs < 1e12 ? rawTs * 1000 : rawTs
  } else {
    const parsed = Date.parse(String(rawTs))
    if (Number.isNaN(parsed)) return ''
    ms = parsed
  }
  const diff = Date.now() - ms
  if (!Number.isFinite(diff)) return ''
  if (diff < 0) return L('刚刚', 'just now')
  const sec = Math.floor(diff / 1000)
  if (sec < 60) return L('刚刚', 'just now')
  const min = Math.floor(sec / 60)
  if (min < 60) return min + L('分钟前', 'm ago')
  const hr = Math.floor(min / 60)
  if (hr < 24) return hr + L('小时前', 'h ago')
  const day = Math.floor(hr / 24)
  if (day < 30) return day + L('天前', 'd ago')
  const mon = Math.floor(day / 30)
  if (mon < 12) return mon + L('个月前', 'mo ago')
  return Math.floor(mon / 12) + L('年前', 'y ago')
}

// ===== Avatar helpers =====
function initialOf(name) {
  const n = (name || '').toString().trim()
  if (!n) return '?'
  return n.charAt(0).toUpperCase()
}

const AVATAR_COLORS = [
  '#FF4500', '#0f766e', '#1d4ed8', '#7c3aed',
  '#b91c1c', '#16a34a', '#c2410c', '#0891b2'
]

function avatarStyle(name) {
  const n = (name || '').toString()
  let hash = 0
  for (let i = 0; i < n.length; i++) {
    hash = (hash * 31 + n.charCodeAt(i)) >>> 0
  }
  const bg = AVATAR_COLORS[hash % AVATAR_COLORS.length]
  return { background: bg }
}

// ===== Platform display =====
const platformTag = computed(() => (platform.value === 'reddit' ? 'Reddit' : 'Twitter'))

// ===== Run state / round info =====
const hasRoundInfo = computed(() => {
  const rs = runState.value
  if (!isPlainObject(rs)) return false
  const cur = rs.current_round
  const total = rs.total_rounds
  return (cur !== undefined && cur !== null) || (total !== undefined && total !== null)
})

const roundLabel = computed(() => {
  const rs = isPlainObject(runState.value) ? runState.value : {}
  const cur = rs.current_round
  const total = rs.total_rounds
  const curStr = cur === undefined || cur === null ? '—' : cur
  const totalStr = total === undefined || total === null ? '—' : total
  // CAL-TEMPORAL: calendar-mode runs expose temporal_mode/current_period_end in the
  // run-status payload — badge reads "{label} · r/N"; hours-mode payloads lack these
  // fields and keep the legacy "r / N" badge unchanged.
  if (rs.temporal_mode === 'calendar' && rs.current_period_end) {
    return String(rs.current_period_end) + ' · ' + curStr + '/' + totalStr
  }
  return curStr + ' / ' + totalStr
})

const runnerStatus = computed(() => {
  const rs = isPlainObject(runState.value) ? runState.value : {}
  const s = rs.runner_status
  return s === undefined || s === null || s === '' ? '' : String(s)
})

// ===== Stat tiles from stats object (numeric entries only) =====
const STAT_LABELS = {
  total_actions: ['总动作', 'Total actions'],
  total_posts: ['总帖子', 'Total posts'],
  total_agents: ['总智能体', 'Total agents'],
  total_comments: ['总评论', 'Total comments'],
  total_likes: ['总点赞', 'Total likes'],
  total_rounds: ['总回合', 'Total rounds'],
  active_agents: ['活跃智能体', 'Active agents'],
  posts: ['帖子', 'Posts'],
  actions: ['动作', 'Actions'],
  agents: ['智能体', 'Agents']
}

function humanizeKey(key) {
  if (STAT_LABELS[key]) return L(STAT_LABELS[key][0], STAT_LABELS[key][1])
  return String(key)
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim()
}

const statTiles = computed(() => {
  const s = stats.value
  if (!isPlainObject(s)) return []
  const tiles = []
  for (const key of Object.keys(s)) {
    const val = s[key]
    if (typeof val === 'number' && Number.isFinite(val)) {
      tiles.push({ key, label: humanizeKey(key), value: formatNumber(val) })
    }
  }
  return tiles
})

function formatNumber(n) {
  if (!Number.isFinite(n)) return String(n)
  if (Math.abs(n) >= 1000) return n.toLocaleString('en-US')
  return String(n)
}

// ===== Data loading =====
async function loadAll() {
  if (refreshTimer) { clearTimeout(refreshTimer); refreshTimer = null }
  const request = requests.begin()
  if (!props.simulationId) {
    profiles.value = []
    posts.value = []
    comments.value = []
    stats.value = {}
    runState.value = {}
    userMap.value = {}
    error.value = ''
    engine.value = null
    loading.value = false
    return
  }

  loading.value = true
  error.value = ''
  refreshToken.value += 1
  const simId = props.simulationId
  const plat = platform.value
  const feedReq = feedRequest(selectedRound.value)

  // Route by the saved pin, never by deployment defaults or by social data being
  // empty. This also covers prepared world runs that have no runner state yet.
  try {
    const response = await getSimulation(simId, { signal: request.signal, timeout: WORLD_REQUEST_TIMEOUT_MS })
    if (!request.isCurrent()) return
    if (response?.success !== true || response.data?.simulation_id !== simId) throw new Error('Invalid saved state')
    const savedEngine = savedSimulationEngine(response.data)
    if (![WORLD_ENGINE, LEGACY_ENGINE].includes(savedEngine)) {
      engine.value = null
      error.value = L('此模拟保存的引擎尚不受支持。', 'This simulation uses an unsupported saved engine.')
      loading.value = false
      return
    }
    worldGenerationId.value = response.data.world_generation_id || ''
    engine.value = savedEngine
    if (savedEngine === WORLD_ENGINE) { loading.value = false; return }
  } catch {
    if (!request.isCurrent()) return
    engine.value = null
    error.value = L('无法读取已保存的模拟，请重试。', 'Could not read the saved simulation. Please retry.')
    loading.value = false
    return
  }

  const options = { signal: request.signal, timeout: WORLD_REQUEST_TIMEOUT_MS }
  // PERIOD VIEW: the selected committed round narrows posts and replies (sent as `round`)
  const feedOptions = { ...options, round: feedReq.round }
  const results = await Promise.allSettled([
    getSimulationProfilesRealtime(simId, plat, options),
    getSimulationPosts(simId, plat, feedReq.limit, 0, feedOptions),
    getSimulationComments(simId, plat, feedReq.commentLimit, 0, feedOptions),
    getAgentStats(simId, options),
    getRunStatus(simId, options),
    getFeedRounds(simId, plat, options)
  ])

  // Guard against a stale response landing after a platform/sim/period switch (each switch starts
  // a new request through the gate; the period check is a second line of defence)
  if (!request.isCurrent() || selectedRound.value !== feedReq.round) return

  const [profilesRes, postsRes, commentsRes, statsRes, runRes, roundsRes] = results
  if (runRes.status === 'fulfilled' && runRes.value?.data?.simulation_engine !== undefined
      && runRes.value.data.simulation_engine !== engine.value) {
    engine.value = null
    error.value = L('模拟身份已变更，请重新加载。', 'Simulation identity changed. Please reload.')
    loading.value = false
    return
  }

  // Feed rounds (period labels + counts); absent on runs without an action log
  if (roundsRes.status === 'fulfilled') {
    const data = roundsRes.value && roundsRes.value.data
    feedRounds.value = asArray(isPlainObject(data) ? data.rounds : null)
  } else {
    feedRounds.value = []
  }

  // Profiles
  if (profilesRes.status === 'fulfilled') {
    const data = profilesRes.value && profilesRes.value.data
    const list = normalizeProfiles(data)
    profiles.value = asArray(list)
    userMap.value = buildUserMap(profiles.value)
  } else {
    profiles.value = []
    userMap.value = {}
  }

  // Posts
  if (postsRes.status === 'fulfilled') {
    const data = postsRes.value && postsRes.value.data
    posts.value = asArray(isPlainObject(data) ? data.posts : null)
    feedPeriodLabel.value = isPlainObject(data) && data.period_label ? String(data.period_label) : ''
  } else {
    posts.value = []
    feedPeriodLabel.value = ''
  }

  // Comments (replies) — grouped under their parent post in the template
  if (commentsRes.status === 'fulfilled') {
    const data = commentsRes.value && commentsRes.value.data
    comments.value = asArray(isPlainObject(data) ? data.comments : null)
  } else {
    comments.value = []
  }

  // Stats
  if (statsRes.status === 'fulfilled') {
    const data = statsRes.value && statsRes.value.data
    stats.value = isPlainObject(data) ? data : {}
  } else {
    stats.value = {}
  }

  // Run state
  if (runRes.status === 'fulfilled') {
    const data = runRes.value && runRes.value.data
    runState.value = isPlainObject(data) ? data : {}
  } else {
    runState.value = {}
  }

  // Surface an error only when every request failed (transient/empty data stays graceful).
  const allFailed = results.every((r) => r.status === 'rejected')
  if (allFailed) {
    const first = results.find((r) => r.status === 'rejected')
    const reason = first && first.reason
    error.value = (reason && reason.message) ? reason.message : L('加载模拟数据失败', 'Failed to load simulation data')
  }

  loading.value = false
  scheduleAutoRefresh()
}

function switchPlatform(next) {
  if (platform.value === next) return
  platform.value = next
  loadAll()
}

// ===== Lifecycle / live auto-refresh =====
// While the simulation is still running, re-poll every 10s so personas/feed/stats update
// live without a manual refresh. Stops automatically once the run completes.
function scheduleAutoRefresh() {
  if (refreshTimer) { clearTimeout(refreshTimer); refreshTimer = null }
  const rs = isPlainObject(runState.value) ? runState.value : {}
  const st = String(rs.runner_status || '').toLowerCase()
  if (props.simulationId && (st === 'running' || st === 'starting')) {
    refreshTimer = setTimeout(loadAll, 10000)
  }
}

watch(
  () => props.simulationId,
  () => {
    engine.value = null
    worldGenerationId.value = ''
    profiles.value = []; posts.value = []; comments.value = []
    stats.value = {}; runState.value = {}; userMap.value = {}
    selectedRound.value = null
    feedRounds.value = []
    feedPeriodLabel.value = ''
    loadAll()
  },
  { immediate: true, flush: 'sync' }
)

onUnmounted(() => {
  requests.invalidate()
  if (refreshTimer) { clearTimeout(refreshTimer); refreshTimer = null }
})
</script>

<style scoped>
.sim-view {
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

  display: flex;
  flex-direction: column;
  gap: 16px;
  width: 100%;
  box-sizing: border-box;
  color: var(--ink);
  background: var(--paper);
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
}

.sim-view * {
  box-sizing: border-box;
}

.mono {
  font-family: var(--mono);
}

/* ===== Header ===== */
.sv-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.sv-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.diamond {
  color: var(--orange);
  font-size: 14px;
  line-height: 1;
}

.diamond.sm {
  font-size: 11px;
}

.sv-title-text {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  font-family: var(--mono);
}

.sv-controls {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* Segmented toggle */
.segmented {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: 2px;
  overflow: hidden;
}

.seg-btn {
  appearance: none;
  border: none;
  background: var(--paper);
  color: var(--muted);
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.03em;
  padding: 6px 14px;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.seg-btn + .seg-btn {
  border-left: 1px solid var(--border);
}

.seg-btn:hover:not(.active) {
  background: var(--soft);
  color: var(--ink);
}

.seg-btn.active {
  background: var(--ink);
  color: var(--paper);
}

/* Refresh button */
.refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border);
  border-radius: 2px;
  background: var(--paper);
  color: var(--ink);
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.03em;
  padding: 6px 12px;
  cursor: pointer;
  transition: transform 0.15s ease, border-color 0.15s ease;
}

.refresh-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  border-color: var(--ink);
}

.refresh-btn:disabled {
  opacity: 0.55;
  cursor: default;
}

.refresh-icon {
  display: inline-block;
  font-size: 13px;
  line-height: 1;
}

.refresh-icon.spinning {
  animation: sv-spin 0.9s linear infinite;
}

@keyframes sv-spin {
  to { transform: rotate(360deg); }
}

/* ===== Error ===== */
.sv-error {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--border);
  border-left: 3px solid var(--err);
  background: var(--color-err-soft, #FEF2F2);
  padding: 8px 12px;
  border-radius: var(--radius, 2px);
  font-size: 12px;
}

.err-dot {
  color: var(--err);
  font-size: 8px;
}

.err-text {
  color: var(--err);
  font-family: var(--mono);
}

/* ===== Stats strip ===== */
.stats-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.stat-tile {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 96px;
  border: 1px solid var(--border);
  border-radius: 2px;
  padding: 10px 14px;
  background: var(--paper);
  transition: transform 0.15s ease, border-color 0.15s ease;
}

.stat-tile:hover {
  transform: translateY(-1px);
  border-color: var(--ink);
}

.stat-label {
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--faint);
}

.stat-value {
  font-size: 18px;
  font-weight: 600;
  color: var(--ink);
}

/* ===== Columns ===== */
.sv-columns {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.25fr);
  gap: 16px;
  align-items: start;
}

.col {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: 2px;
  background: var(--paper);
  min-height: 220px;
  max-height: 640px;
  overflow: hidden;
}

.col-head {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--soft);
  flex: 0 0 auto;
}

.col-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  font-family: var(--mono);
  color: var(--ink);
}

.col-body {
  flex: 1 1 auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.scroll {
  overflow-y: auto;
}

.scroll::-webkit-scrollbar {
  width: 8px;
}

.scroll::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 4px;
}

.scroll::-webkit-scrollbar-thumb:hover {
  background: var(--faint);
}

/* ===== Persona card ===== */
.persona-card {
  border: 1px solid var(--border);
  border-radius: 2px;
  padding: 12px;
  background: var(--paper);
  transition: transform 0.15s ease, border-color 0.15s ease;
}

.persona-card:hover {
  transform: translateY(-1px);
  border-color: var(--ink);
}

.persona-top {
  display: flex;
  align-items: center;
  gap: 10px;
}

.persona-avatar,
.post-avatar {
  flex: 0 0 auto;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-family: var(--mono);
  font-size: 14px;
  font-weight: 600;
  user-select: none;
}

.persona-id {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.persona-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.persona-type {
  align-self: flex-start;
  font-size: 10px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  font-family: var(--mono);
  color: var(--orange);
  border: 1px solid var(--orange);
  border-radius: 2px;
  padding: 1px 6px;
  line-height: 1.4;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.persona-snippet {
  margin: 10px 0 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--muted);
  display: -webkit-box;
  -webkit-line-clamp: 4;
  line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.persona-snippet.empty {
  color: var(--faint);
  font-style: italic;
}

/* ===== Post card ===== */
.post-card {
  border: 1px solid var(--border);
  border-radius: 2px;
  padding: 12px;
  background: var(--paper);
  transition: transform 0.15s ease, border-color 0.15s ease;
}

.post-card:hover {
  transform: translateY(-1px);
  border-color: var(--ink);
}

.post-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.post-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.post-author {
  font-size: 13px;
  font-weight: 700;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.post-sub {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
}

.plat-tag {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--muted);
  border: 1px solid var(--border);
  border-radius: 2px;
  padding: 0 5px;
  line-height: 1.5;
}

.feed-period { font-size: 12px; opacity: 0.8; margin-left: 6px; }
.feed-all {
  margin-left: auto; font-size: 11px; padding: 1px 8px; border-radius: 4px; cursor: pointer;
  border: 1px solid var(--border, #e5e7eb); background: transparent; color: inherit;
}
.feed-all:hover { background: var(--panel-bg, rgba(0, 0, 0, 0.04)); }
.post-period { font-size: 11px; opacity: 0.7; }
.post-time {
  color: var(--faint);
  font-size: 11px;
}

.post-text {
  margin: 10px 0 0;
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--ink);
  white-space: pre-wrap;
  word-break: break-word;
}

.post-text.empty {
  color: var(--faint);
  font-style: italic;
}

.post-metrics {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}

.metric {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--faint);
}

/* ===== Replies (nested under a post) ===== */
.post-replies {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.replies-head {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--faint);
}

.reply-card {
  margin-left: 16px;
  padding: 8px 10px;
  border-left: 2px solid var(--border);
  background: transparent;
}

.reply-head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.reply-avatar {
  flex: 0 0 auto;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 600;
  user-select: none;
}

.reply-author {
  font-size: 12px;
  font-weight: 700;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.reply-time {
  font-size: 10.5px;
  color: var(--faint);
}

.reply-text {
  margin: 6px 0 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--ink);
  white-space: pre-wrap;
  word-break: break-word;
}

.reply-metrics {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 6px;
}

/* ===== Empty / loading state ===== */
.empty-state {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px 16px;
  text-align: center;
}

.empty-icon {
  font-size: 20px;
  color: var(--border);
}

.empty-icon.loading-dot {
  font-size: 12px;
  color: var(--orange);
  animation: sv-pulse 1.1s ease-in-out infinite;
}

@keyframes sv-pulse {
  0%, 100% { opacity: 0.35; }
  50% { opacity: 1; }
}

.empty-text {
  font-size: 12px;
  color: var(--faint);
  font-family: var(--mono);
  letter-spacing: 0.02em;
}

/* ===== Responsive: stack below 960px ===== */
@media (max-width: 960px) {
  .sv-columns {
    grid-template-columns: minmax(0, 1fr);
  }

  .col {
    max-height: 480px;
  }
}
</style>
