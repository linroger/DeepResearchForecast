# frontend — Vue 3 frontend: views, components, API client, progress polling

Scope: `frontend/src/**` (all files), `frontend/vite.config.js`, `frontend/package.json`, `frontend/tests/**`.
Branch `main`, read from disk 2026-10-11. All anchors are repo-relative. Backend anchors are given only to
resolve what an endpoint is; the backend is mapped by other slices.

File inventory (lines): `views/ResearchView.vue` 1016 · `components/GraphPanel.vue` 2625 ·
`components/research/{ForecastReport 1955, DossierViewer 1567, SimulationView 1184, StageTimeline 660,
PipelineHistory 651, ResearchConsole 444, BinaryForecastTable 319, SettingsMenu 316, RunVitals 281,
ConfirmDialog 118}.vue` · `api/{index 88, research 236, report 156, simulation 203, graph 109, settings 23}.js` ·
`utils/{markdown 298, reportLanguages 294, runVitals 204, binaryForecasts 166, vizManifest 123,
graphPayload 103, liveProgress 96, graphStyle 82, researchTranslation 65}.js` · `i18n.js` 52 · `main.js` 26 ·
`App.vue` 40 · `router/index.js` 29 · `styles/tokens.css` 126 · 10 test files (1,300 lines) · `vite.config.js` 34 ·
`package.json` 26. (There is no `src/store/` directory; see Surprises.)

---

## Purpose & position in the pipeline

The frontend is a single-page Vue 3 dashboard with exactly one real route (`/` → `ResearchView`,
`frontend/src/router/index.js:5-21`). It is the human entry and observation surface for the whole pipeline:
the user types one question, chooses mode/depth/round cap/language/model, and POSTs `/api/research/run`
(`frontend/src/views/ResearchView.vue:456-475`). From then on the SPA only **polls** the Flask backend
over HTTP (no SSE/WebSocket anywhere in the slice): an adaptive status poll drives a 6-stage timeline
(research → ontology → graph → prepare → run → report), a live research-log console, run vitals, and five
tabs (Live log · Dossier · Graph · Simulation · Forecast). Each tab component owns its own fetching
(dossier translations, graph overview/focus/neighbors, OASIS feed, report sections/translations/forecast).
It never talks to an LLM directly; several endpoints it calls do trigger LLM work server-side
(run/resume/continue, translations, settings test, resolution monitor). In dev, Vite (port 3000) proxies
`/api` to Flask on `localhost:5001` (`frontend/vite.config.js:23-31`); in "hosted" mode Flask itself
serves the built `frontend/dist` (`backend/app/__init__.py:88`, `:221-243`).

---

## Walkthrough (source order)

### Build / tooling

- **`frontend/package.json:6-11`** — scripts: `dev`=`vite`, `build`=`vite build`, `test:unit`=`node --test
  tests/*.test.mjs` (includes `devServer.test.mjs`, which really starts a Vite server — not a pure unit test),
  `preview`=`vite preview`. Runtime deps (`:12-21`): `@fontsource/*` (inter, jetbrains-mono, noto-sans-sc,
  space-grotesk), `axios ^1.13.2`, `d3 ^7.9.0`, `vue ^3.5.24`, `vue-router ^4.6.3`. Dev deps: `@vitejs/plugin-vue`,
  `vite ^7.2.4` (`:22-25`). No test framework dependency (uses `node:test`).
- **`frontend/vite.config.js:13`** — `host = process.env.FRONTEND_HOST || '127.0.0.1'` (IPv4 loopback literal on
  purpose, comment `:4-12`). `server` (`:18-33`): `port: 3000`, `strictPort: true` (fails rather than picks another
  port), `open: true` (opens a browser), proxy `'/api' → 'http://localhost:5001'`, `changeOrigin: true`,
  `secure: false`, `xfwd: true` (adds X-Forwarded-For so the backend auth gate can distinguish LAN clients,
  `backend/app/__init__.py:154-172`).
- **`frontend/index.html`** (not in slice list but read) — `<html lang="zh-CN">`, English title, mounts `#app`,
  loads `/src/main.js`.

### Entry

- **`frontend/src/main.js:3-17`** — imports self-hosted font CSS (comment `:1-2`: replaced a Google Fonts CDN
  request) and `styles/tokens.css`; **`:22-26`** creates the app, installs the router, mounts `#app`. No store,
  no global error handler.
- **`frontend/src/App.vue:1-3`** — just `<router-view />`; global CSS reset `:11-15`, `#app` font/colour from
  tokens `:17-26`, print background `:35-39`.
- **`frontend/src/router/index.js:3`** — `ResearchView` imported eagerly (entry chunk). Routes `:5-21`: `/` →
  `ResearchView` (name `Research`); `/research` → redirect `/`; catch-all `/:pathMatch(.*)*` → redirect `/`
  (comment `:16-17`: legacy MiroFish routes removed). `createWebHistory()` + `scrollBehavior → {top:0}`
  (`:23-27`). Any deep link (e.g. `/report/x`) silently lands on the input page.
- **`frontend/src/styles/tokens.css:9-80`** — global `:root` design tokens (colours `--color-*`, fonts
  `--font-sans/--font-mono`, type scale `--fs-*`, spacing `--sp-*`, radius, 4 shadows, motion `--ease`,
  `--dur-1..3`), `accent-color`. `:83-86` global `:focus-visible` ring; `:89-92` selection; `:95-114`
  scrollbars; `:117-125` `prefers-reduced-motion` collapses all animations/transitions.

### i18n — `frontend/src/i18n.js`

- `STORAGE_KEY = 'drf_locale'` (`:11`); `DOC_TITLES` zh/en (`:13-16`).
- `initialLocale()` (`:18-29`): persisted `localStorage['drf_locale']` if `'en'|'zh'`; else derive from
  `navigator.language` (`/^zh/i` → `zh`, anything else → `en`); the final `return 'zh'` (`:28`) is only reached
  if `navigator` access throws.
- `locale` = `ref(initialLocale())` (`:31`) — module singleton shared by every component.
- `syncDocumentLocale()` (`:34-38`): sets `<html lang>` to `en`/`zh-CN` and `document.title`; run once at module
  init (`:47`) and on every `setLocale` (`:40-44`, which also persists to localStorage, errors swallowed).
- `L(zh, en)` (`:50-52`): returns `en` when locale is `en` (falls back to `zh` if `en == null`), else `zh`.
  Because it reads `locale.value`, any template calling `L()` re-renders on toggle. There are no message
  catalogs: every UI string is an inline `L('中文','English')` pair.
- UI locale is independent of **report content language** (report/dossier language toggles are separate state;
  see ForecastReport/DossierViewer).

### API client — `frontend/src/api/index.js`

- `service = axios.create({ baseURL: VITE_API_BASE_URL || '/', timeout: 300000, headers: {Content-Type: json} })`
  (`:4-12`). 5-minute timeout applies to every call unless overridden.
- Request interceptor (`:15-23`) is a pass-through (no auth header is ever attached — the SPA has no way to send
  the backend's `X-API-Token`).
- Response interceptor success path (`:26-37`): returns **`response.data` (the JSON body)**, not the axios
  response. If the body has `success === false` (explicitly present and falsy) it rejects with
  `new Error(res.error || res.message || 'Error')`. Bodies without a `success` key (e.g. text/markdown, the
  `sections-partial` shape) pass through unchanged. Consequence for every caller: `res.data` is the backend's
  `data` field.
- Error path (`:38-62`): logs; if the backend body has `error`/`message`, overwrites `error.message` with it
  (`:55-59`) so UIs show the real reason (e.g. the preflight checklist); keeps `error.response` so callers can
  branch on status (404/409).
- `apiUrl(path)` (`:68-72`): `(VITE_API_BASE_URL || '')` without trailing slashes + path (leading `/` ensured).
  Used for `<img src>`, `<a href>`, and `fetch()` downloads that bypass axios.
- `requestWithRetry(fn, maxRetries=3, delay=1000)` (`:75-86`): exponential backoff 1s/2s; **unused anywhere**
  (several modules explicitly forbid retrying non-idempotent POSTs).

### API modules (every function → method + path; backend handler in brackets)

`frontend/src/api/research.js` (all paths under `/api/research`, blueprint prefix `backend/app/__init__.py:204`):

| Function (file:line) | Method + path | Backend | Used by |
|---|---|---|---|
| `researchChartUrl(pid, rel)` `:12-17` | GET `/api/research/<pid>/artifact/chart_<urlencoded file>` (URL only; only `charts/<file>` one level deep, else `''`) | `backend/app/api/research.py:779` | DossierViewer `<img>` |
| `runPipeline(data)` `:28-34` | POST `/run` body `{prompt, mode, depth, max_rounds?, language?, model?}` (non-idempotent, never retried, comment `:22-24`) | `research.py:50` | ResearchView |
| `cancelPipeline(pid)` `:41-46` | POST `/<pid>/cancel` | `research.py:132` | ResearchView, PipelineHistory |
| `resumePipeline(pid)` `:53-58` | POST `/<pid>/resume` | `research.py:147` | ResearchView |
| `continuePipeline(pid)` `:65-70` | POST `/<pid>/continue` | `research.py:184` | ResearchView |
| `forkScenario(pid, overlay)` `:78-84` | POST `/<pid>/scenario` | `research.py:219` | **unused** |
| `getArtifact(pid, name)` `:92-97` | GET `/<pid>/artifact/<name>` | `research.py:779` | **unused** (as XHR) |
| `getPreflight(mode='full')` `:104-110` | GET `/preflight?mode=` | `research.py:355` | ResearchView |
| `deletePipeline(pid)` `:117-122` | DELETE `/<pid>` | `research.py:260` | PipelineHistory |
| `cleanPipelines(statuses=['failed','cancelled'])` `:129-135` | POST `/clean` body `{statuses}` | `research.py:287` | PipelineHistory |
| `getPipelineStatus(pid)` `:142-147` | GET `/status/<pid>` | `research.py:306` | ResearchView poll |
| `listPipelines()` `:152-154` | GET `/list` | `research.py:337` | PipelineHistory |
| `getDossier(pid)` `:160-165` | GET `/<pid>/dossier` | `research.py:389` | ResearchView |
| `editDossier(pid, payload)` `:172-178` | PUT `/<pid>/dossier` body `{report}` | `research.py:690` | DossierViewer |
| `requestResearchTranslation(pid, lang)` `:187-189` | POST `/<pid>/dossier/translations/<lang>` | `research.py:555` | DossierViewer |
| `getResearchTranslation(pid, lang)` `:198-200` | GET `/<pid>/dossier/translations/<lang>` | `research.py:593` | DossierViewer |
| `researchPdfUrl(pid, lang?)` `:209-212` | GET `/<pid>/dossier/pdf[?lang=]` (href) | `research.py:636` | DossierViewer link |
| `runResolutionMonitor()` `:220-222` | POST `/resolution-monitor/run` (202 started / 409 inflight; never retried) | `research.py:342` | SettingsMenu |
| `getProgressLog(pid, lines=200, scope='tail')` `:230-236` | GET `/<pid>/progress?lines=&scope=tail\|full` | `research.py:871` | ResearchView (always passes `lines=500`) |

`frontend/src/api/graph.js` (prefix `/api/graph`):

| Function | Method + path | Backend | Used by |
|---|---|---|---|
| `generateOntology(formData)` `:14-23` | POST `/ontology/generate` multipart | `graph.py:121` | **unused** |
| `buildGraph(data)` `:30-36` | POST `/build` | `graph.py:259` | **unused** |
| `getTaskStatus(taskId)` `:43-48` | GET `/task/<id>` | `graph.py:533` | **unused** |
| `getGraphData(gid, options)` `:59-66` | GET `/data/<gid>` with params from `graphRequestParams` (default `{top_k:0, slim:'true'}`; `{full:'true'}` when `full:true`) | `graph.py:576` | ResearchView, GraphPanel |
| `getGraphNodeDetail(gid, uuid)` `:68-73` | GET `/data/<gid>/node/<uuid>` | `graph.py:642` | GraphPanel |
| `getGraphEdgeDetail(gid, uuid)` `:75-80` | GET `/data/<gid>/edge/<uuid>` | `graph.py:659` | GraphPanel |
| `getGraphNeighbors(gid, uuid, depth=1)` `:91-97` | GET `/data/<gid>/neighbors/<uuid>?depth=` | `graph.py:621` | GraphPanel |
| `getProject(id)` `:104-109` | GET `/project/<id>` | `graph.py:35` | **unused** |

`frontend/src/api/report.js` (prefix `/api/report`):

| Function | Method + path | Backend | Used by |
|---|---|---|---|
| `generateReport` `:11-13` | POST `/generate` | `report.py:267` | **unused** |
| `getReportStatus` `:19-21` | POST `/generate/status` | `report.py:468` | **unused** |
| `getAgentLog(rid, from)` `:28-30` | GET `/<rid>/agent-log?from_line=` | `report.py:1895` | **unused** |
| `getConsoleLog(rid, from)` `:37-39` | GET `/<rid>/console-log?from_line=` | `report.py:2001` | **unused** |
| `getReport(rid)` `:45-47` | GET `/<rid>` | `report.py:543` | ForecastReport |
| `chatWithReport` `:53-55` | POST `/chat` | `report.py:1478` | **unused** |
| `getVizManifest(rid)` `:65-67` | GET `/<rid>/viz-manifest` | `report.py:1358` | ForecastReport |
| `getSectionsPartial(rid)` `:74-76` | GET `/<rid>/sections-partial` | `report.py:1681` | ForecastReport |
| `getReportTranslationMd(rid, lang)` `:84-87` | GET `/<rid>/full_report.<lang>.md` (`responseType:'text'`) | `report.py:757` | ForecastReport |
| `requestReportTranslation(rid, lang, force)` `:94-100` | POST `/<rid>/translations/<lang>[?force=1]` | `report.py:804` | ForecastReport |
| `getReportTranslationStatus(rid, lang, taskId)` `:103-107` | GET `/<rid>/translations/<lang>/status[?task_id=]` | `report.py:977` | ForecastReport |
| `reportMarkdownUrl(rid, lang?)` `:110-115` | GET `/<rid>/full_report.<lang>.md` or `/<rid>/download` | `report.py:757` / `:709` | ForecastReport `fetch` |
| `reportPdfUrl(rid, lang?)` `:124-127` | GET `/<rid>/pdf[?lang=]` | `report.py:1037` | ForecastReport `fetch` |
| `getForecast(rid, lang?)` `:142-144` | GET `/<rid>/forecast[?lang=]` | `report.py:585` | ForecastReport |
| `reportAssetUrl(rid, rel)` `:153-156` | GET `/<rid>/<rel>` i.e. `/<rid>/charts/<file>` | `report.py:1279` | ForecastReport `<img>`/links |

`frontend/src/api/simulation.js` (prefix `/api/simulation`) — 22 exports; **only 5 are used** (all by
SimulationView): `getSimulationProfilesRealtime` `:52-54` → GET `/<sid>/profiles/realtime?platform=`
(`simulation.py:1064`); `getSimulationPosts(sid, platform, limit=50, offset=0)` `:121-125` → GET
`/<sid>/posts` (`simulation.py:2133`); `getSimulationComments(..., limit=200)` `:134-138` → GET `/<sid>/comments`
(`simulation.py:2211`); `getAgentStats` `:158-160` → GET `/<sid>/agent-stats` (`simulation.py:2104`);
`getRunStatus` `:102-104` → GET `/<sid>/run-status` (`simulation.py:1746`). Unused: create `:10`, prepare `:18`,
prepare/status `:26`, get `:34`, profiles `:43`, config `:60`, config/realtime `:69`, list `:77`, start `:86`,
stop `:94`, run-status/detail `:110`, timeline `:146`, actions `:167`, close-env `:175`, env-status `:183`,
interview/batch `:191`, history `:200`.

`frontend/src/api/settings.js`: `getLlmSettings` `:4-6` → GET `/api/settings/llm` (`settings.py:25`);
`setLlmSettings(data)` `:12-14` → POST `/api/settings/llm` (`settings.py:30`; persists provider/key at runtime);
`testLlmSettings(data)` `:21-23` → POST `/api/settings/llm/test` with `timeout: 45000` (`settings.py:151`; makes a
minimal real LLM call for API providers, CLI check for CLI providers).

### View — `frontend/src/views/ResearchView.vue`

**Template**
- Navbar `:4-22`: brand; locale toggle button (`toggleLocale`, `:8`), settings gear (`showSettings=true`, `:9`),
  History button toggles drawer (`:15`).
- History drawer `:25-40`: `<PipelineHistory :active-id=pipelineId @select=selectPipeline @deleted=onRunDeleted>`
  (`:35`) — mounted with `v-if`, so it remounts (and reloads the list) on every open. Scrim closes it (`:39`).
- `<SettingsMenu v-if="showSettings" @close @changed=onProviderChanged>` (`:43`); `<ConfirmDialog ref=confirmDlg>`
  (`:46`).
- **Setup section** (`v-if="!pipelineId"`, `:50-140`): prompt textarea (`:68-69`), 3 example chips (`:71-74`,
  text truncated to 24 chars by `exShort`), mode segmented control full/research_only (`:80-86`), depth
  quick/standard/deep (`:87-92`), round cap numeric input only in full mode (`:93-96`), "Advanced" collapsible
  with research language + research model selects (`:100-118`), preflight banners (`:121-129`), start button
  disabled unless `canStart` (`:132-136`), error line (`:137`).
- **Run section** (`v-else`, `:143-224`): pipeline-id chip (first 8 chars, click-to-copy, `:148-152`), status
  title (`:154`), `<RunVitals>` (`:155-157`), actions (`:159-171`): Cancel only while `status==='running'`,
  Resume when failed/cancelled, "Continue to full pipeline" when `canContinue`, History, New (`reset`). Prompt
  card (`:174-177`). Layout: sticky rail with `<StageTimeline>` (`:180-182`) + tabbar (`:185-191`, disabled tabs
  are not clickable) + tab bodies all mounted with `v-show` (`:193-219`): `ResearchConsole` (`:194-195`),
  `DossierViewer :editable="canContinue"` (`:196-197`), graph wrapper (`:198-216`: `GraphPanel` only once
  `graphData` exists, else spinner / "Load knowledge graph" button / placeholder), `SimulationView
  :simulation-id` (`:217`), `ForecastReport :report-id` (`:218`). Page error line `:223`.

**Script — state & constants**
- localStorage keys: `ACTIVE_PIPELINE_KEY='drf_active_pipeline'` (`:250`), legacy `'mirofish_active_pipeline'`
  (`:252`).
- Inputs (`:255-265`): `prompt`, `mode='full'`, **`depth='deep'` default** (`:257`), `depths` (`:258`),
  `maxRounds=null`, `starting`, `error`, `showSettings`.
- Advanced (`:268-277`): `researchLanguage=''` (Default/`Chinese`/`English`/`auto`), `researchModel=''`,
  `DEERFLOW_MODELS = ['claude','codex','minimax','deepseek','qwen','glm','kimi']` (`:271`).
- Run state (`:333-351`): `pipelineId`, `status='running'`, `globalProgress`, `currentStage`, `stages`,
  `graphId`, `simulationId`, `reportId`, `runPrompt`, `logLines`, `logSourceCount`, log-history flags
  (`Hydrated`, `Finalized`, `InitialSnapshotAttempted`, `FinalSnapshotAttempts`, `Loading`, `Error`), `dossier`,
  `showHistory`. `liveVitals`, `runTiming {createdAt, updatedAt, resumedAt}` (`:357-358`). Tabs/graph
  (`:361-365`): `activeTab='log'`, `userPickedTab`, `graphData`, `graphLoading`, `graphMax`.
- Poll constants (`:382-398`): `POLL_FAILURE_THRESHOLD=4` (`:386`), `MAX_FINAL_SNAPSHOT_ATTEMPTS=2` (`:387`),
  `POLL_MIN_MS=2500` (`:391`), `POLL_MAX_MS=12000` (`:392`); module-level `pollTimer`, `pollActive`,
  `pollDelay`, `lastFingerprint`, `visibilityHandler`, `pollInFlightGeneration`, `pollGeneration`,
  `dossierFetched`, `pollFailures`, `connErrorShown`.

**Script — functions**
- `checkPreflight()` `:283-295`: GET preflight for current mode; `preflightReady = !!res.data.ready`,
  `preflightErrors = res.data.errors || []`; **on request failure treats as ready** (`:288-291`, real errors are
  caught by `/run`). Always sets `preflightChecked=true`.
- `canContinue` `:299-301`: `pipelineId && status==='completed' && mode==='research_only'`.
- `continueToFull()` `:302-322`: POST continue; adopts returned `pipeline_id` (or same), sets `mode='full'`,
  `status='running'`, clears `liveVitals` (stale terminal block, comment `:312-313`), saves active key,
  `startPolling()`. Does **not** reset `dossier`/`dossierFetched` or the log-final flags.
- `seedActorNames` `:368-372`: `dossier.actors.actors[].name` → passed to GraphPanel `seed-actors`.
- `logHistoryMeta` `:374-380`: `{sourceCount, totalExact, finalized, loading, error}` for ResearchConsole.
- `pollFingerprint()` `:402-407`: `status#globalProgress#currentStage#<stage:status|...>#liveLogRevision(logLines)`.
- `stageLabel` `:409-414`, `statusTitle` `:420-425` (completed → "Research complete" or "Done · forecast ready";
  failed; cancelled; else "Running · <stage>").
- `canStart` `:417-419`: non-empty prompt AND (`!preflightChecked || preflightReady`).
- `tabs` `:427-437`: Live log (always), Dossier enabled when `dossier.has_report` or research stage
  `completed` (badge = actor count), Graph when `graphId`, Simulation when `simulationId`, Forecast when
  `reportId`.
- `pickTab(key)` `:442-448`: ignores disabled tabs; marks `userPickedTab`; lazily calls `fetchGraph()` on
  first graph view.
- Auto-tab watch `:450-454`: unless the user picked a tab, jumps to `report` when `reportId` appears, else to
  `dossier` when `dossier.has_report`.
- `start()` `:456-475`: guards; POST run with `{prompt.trim(), mode, depth, max_rounds||undefined,
  language||undefined, model||undefined}`; on success `beginPipeline(res.data.pipeline_id, prompt)`; on error
  shows `e.message` (backend preflight text via interceptor).
- `beginPipeline(id, initialPrompt)` `:477-490`: sets id/prompt, resets log state, persists active key,
  `startPolling()`.
- `applyProgressLogResponse(resp, {finalized})` `:492-506`: requires `data.lines` array. "Exact" iff
  `scope==='full' && total_exact===true && truncated===false` → **replace** `logLines`, mark hydrated,
  set finalized flag, clear error. Otherwise **merge** via `mergeProgressLines`. `logSourceCount = max(prev,
  data.source_count)`. Returns `exact`.
- `requestProgressLog(id, scope)` `:508-521`: `getProgressLog(id, 500, scope)`; errors → `null` (for `full`
  also sets `logHistoryError`; e.g. backend 413 when the full log exceeds its cap).
- `refreshFullResearchLog()` `:523-540` (console "Reload all recorded events"): labels the snapshot final only
  if terminal-ness was observed **before** the request (`:529-532`); bumps final-attempt counter to ≥1.
- `finalizeResearchLog(id, gen)` `:542-550`: up to `MAX_FINAL_SNAPSHOT_ATTEMPTS` (2) full reads; stops when
  one is exact; abandons if generation/pipeline changed.
- `cancel()` `:556-575`: ConfirmDialog (danger) → POST cancel; status flip is left to polling.
- `resume()` `:577-598`: POST resume; adopt id; `status='running'`; clear vitals; reset `logHistoryFinalized`
  and final attempts (resumed producer may append); persist; `startPolling()`.
- `startPolling()` `:601-619`: `stopPolling()`, `pollActive=true`, `pollGeneration++`, delay reset to 2.5s,
  fingerprint cleared, installs one `visibilitychange` handler (on visible: delay → 2.5s and poll now),
  `scheduleNext(0)`.
- `stopPolling()` `:621-629`: deactivates, bumps generation (late responses discarded), clears timer, removes
  visibility handler.
- `scheduleNext(delay)` `:633-638` → `setTimeout(runPoll(generation), delay)`.
- `runPoll(gen)` `:640-660`: hidden tab → no request, reschedule at 12s (`:642-646`); same-generation poll
  still in flight → reschedule 2.5s (`:647-650`); else `await poll(gen)`, release in-flight marker only if it is
  still ours (`:654-657`), then `scheduleNext(pollDelay)`.
- `poll(gen)` `:662-759` (the heart):
  1. Choose log scope (`:668-672`): `full` once (first poll, until hydrated/attempted); `tail` while research is
     not completed (or no lines yet); `null` (no log request) afterwards.
  2. `Promise.all([getPipelineStatus, log request or null])` (`:673-678`); discard if stale (`:679`).
  3. Success resets failure counter and clears a shown connection error (`:680-681`).
  4. Copy `d.status`, `global_progress`, `current_stage`, `stages`, `mode` (if present), `prompt` (if string),
     `live` (object only, else null), `runTiming` from `created_at/updated_at/options.resumed_at`, and sticky
     `graph_id/simulation_id/report_id` (only set when truthy) (`:682-698`).
  5. Apply log response as non-final (`:704`); if `needsFinalProgressSnapshot(...)` → `finalizeResearchLog`
     (`:705-707`).
  6. Adaptive backoff (`:710-716`): fingerprint changed → 2.5s; unchanged → `min(12000, round(delay*1.5))`
     (2.5 → 3.75 → 5.625 → 8.438 → 12 s).
  7. Dossier fetch once when research completes (`:718-726`; `dossierFetched` set before the call, failure is
     swallowed and not retried until terminal).
  8. Terminal (`completed|failed|cancelled`, `:728-741`): `stopPolling()`, remove active key, fetch dossier if
     still missing, on `failed` show first failed stage's `error` or `d.error`.
  9. Errors (`:742-758`): HTTP 404 → stop polling, drop active key, `status='failed'`, "pipeline no longer exists".
     Others → count; at ≥4 consecutive failures show "Lost connection to the backend (retrying): …" but keep
     polling at the current delay.
- `fetchGraph(force)` `:761-773`: GET graph overview (default params → `top_k=0&slim=true`), `graphData =
  res.data || {nodes:[],edges:[]}`; failure writes the page-level `error`.
- `selectPipeline(id)` `:775-780`: same id → just close drawer; else `resetState()` + `beginPipeline(id)` (prompt
  comes from status `d.prompt`).
- `copyPipelineId()` `:786-815`: Clipboard API, fallback hidden textarea + `execCommand('copy')` (non-secure
  context such as http://LAN); "Copied" for 1.6s.
- `resetState()` `:817-829`: stops polling and clears every run field (including graph, dossier,
  `dossierFetched`, tab). Does not reset `mode`, `pollFailures`, `connErrorShown`, or preflight state.
- `reset()` `:830-834`: `resetState`, `pipelineId=''`, remove active key → setup page.
- `onRunDeleted(id)` `:837-839`: if the deleted run is the one on screen → `reset()`.
- `onMounted` `:841-857`: restore `drf_active_pipeline` (one-time migration from the MiroFish key, `:846-852`);
  if found → `beginPipeline(saved)` (resumes watching across reloads), else `checkPreflight()`.
- `watch(mode)` `:859`: re-run preflight on mode change only when no pipeline is open.
- `onUnmounted` `:860-863`: stop polling, clear copy timer.
- Styles `:866-1016`; responsive breakpoints `1080px` (single column, rail not sticky, `:982-985`) and `640px`
  (`:987-1003`); print CSS hides nav/rail/tabbar/actions (`:1007-1015`).

### Component — `StageTimeline.vue` (purely presentational, no API, no emits)

- Props `:121-139`: `stages` object `{name:{status,progress,message,started_at,finished_at,error}}`,
  `currentStage`, `mode`, `globalProgress`.
- Order `:142-143`: full = `research, ontology, graph, prepare, run, report` (matches backend stage names,
  `backend/app/services/pipeline_orchestrator.py:87-92`); research_only = `research` only.
- `stageMeta` `:146-156` bilingual label/desc; `VALID_STATUS` `:158` = pending/running/completed/failed/cancelled
  (anything else normalises to `pending`, `:194`).
- `clampPct` `:176-180` (0–100 int, NaN→0), `truncate` `:182-187`, `normalizeStage` `:190-206`.
- `elapsed(stage)` `:235-243`: `finished_at - started_at` seconds, 1 decimal under 10s.
- Template branches: running → sub-progress bar + message truncated 80 (`:68-79`); completed → "Done · Ns" +
  message (60) (`:82-88`); failed → `error || message` in red (`:91-93`); else (pending **and cancelled**) →
  "Waiting…" (`:96-98`). The empty state (`:104-107`) is unreachable because `orderedStages` is never empty.

### Component — `RunVitals.vue` (presentational; no API)

- Props `:71-80`: `live` (raw `data.live`), `status`, `createdAt`, `updatedAt`, `resumedAt`.
- `model` = `buildRunVitalsModel(live, {status, createdAt, updatedAt, resumedAt})` (`:82-87`); renders nothing
  when `null` (`:2`).
- Elapsed keeps ticking: `liveReceivedAtMs` stamped on every new `live` object (`:93-94`); a 1s `setInterval`
  runs only while non-terminal with elapsed present (`:96-108`); display = `elapsedSeconds + floor((now -
  receivedAt)/1000)` (`:110-118`).
- ETA `~` + "approx" badge (`:10-18`, `:120-123`); liveness chip ok/stale/dead → "active"/"still thinking"/
  "process down" with tooltip heartbeat age · last progress age · PID (`:126-143`); spend tokens/cost
  (`:146-153`); budget bar with remaining tokens and red when `critical` (`:43-50`, `:154-164`).

### Component — `ResearchConsole.vue`

- Props `:85-95`: `logLines`, `historyMeta`; emits `refresh` (`:95`, wired to `refreshFullResearchLog`).
- `toolCallCount` = lines containing `[tool]` (`:104-106`). Filters `:109-129`: all / `[tool]` / `[result]` /
  `[error]` or `[warn]`.
- Paging: `RENDER_PAGE_SIZE=2000` lines per page (`:134`); First/←/→/Latest (`:150-181`); `followLatestPage`
  keeps the last page selected as new lines arrive (`:240-248`).
- History badge text (`:189-194`): final → "All recorded events · final"; error → "Recorded history
  unavailable"; hydrated → "Recorded snapshot + live tail"; else "Loading recorded history…".
- Colouring by substring (`:197-206`): `[tool]` blue, `[ok]`/`[done]` green, `[error]` red, `[warn]` amber,
  `[stage]`/`[init]` orange, `[result]` grey.
- Auto-scroll only if within 48px of the bottom (`:211`, `:213-217`, `:240-248`); "Jump to bottom" button
  (`:68-75`, `:237`).

### Component — `DossierViewer.vue`

- Props `:261-269`: `dossier` (body of GET dossier), `pipelineId`, `editable` (true only for a completed
  research_only run); emits `saved-continue` (`:271`).
- Internal tabs (`:600-617`): Research Report, Key Actors (count), Situation Brief (only if non-empty), Relationships
  (only if any), Markets (only if `prediction_markets` object exists), Sources (count).
- Report panel (`:21-88`): rendered with `renderMarkdown(reportMarkdown, {resolveUrl: researchChartUrl(pid,
  rel), citations: citationTitles})` (`:461-473`) — research charts `charts/x.png` load from
  `/api/research/<pid>/artifact/chart_x.png`; `[Sn]` superscripts get hover titles from `sources[n-1]`
  (`:438-445`). No interactive-twin links and no chart gallery in the dossier.
- Bilingual research report (`:25-62`, `:277-296`, `:455-459`, `:475-596`):
  - `targetLang = detectTranslationTarget(dossier.report)` (`:294-296`) — CJK-majority → `en`, else `zh`.
  - Toggle Source/target (`:26-43`); `switchReportLang(lang)` (`:574-579`) fetches GET translation if not
    cached.
  - `loadResearchTranslation(lang, {trigger})` (`:521-544`) and `generateResearchTranslation()` (`:554-572`)
    read **`res.data.data`** (`:528`, `:560`) — see Surprises (suspected bug: always `{}`).
  - Re-poll every 4s while status is `generating` (`scheduleTranslationPoll`, `:546-552`).
  - PDF link (`:53-61`): `researchPdfUrl(pid, activeLang)`; disabled (href `javascript:void(0)`) when a target
    language is selected but not cached (`:506-519`).
  - Identity guard watch (`:584-596`): any change of `pipelineId` or report text bumps a version, stops
    polling, resets language/cache/status.
- Edit & continue (`:64-80`, `:298-329`): hidden when `dossier.sealed` (lock badge with explanation, `:65`);
  `saveAndContinue` → PUT dossier `{report}` → emit `saved-continue` → parent `continueToFull`.
- Actors (`:91-145`, accessors `:334-400`): grid with influence pill (`high/medium/low` or 高/中/低, `:654-668`),
  type/role/stance/memory; key events prefer `dossier.timeline` then `actors.key_events` (`:345-353`); hot
  topics chips.
- Brief `:362-377` (current_situation, context, dynamics, fault_lines, catalysts); relationships `:380-384`
  with `REL_META` labels/sign colours (`:620-641`).
- Markets `:411-436`, `:194-221`: rows require `market_id` and non-null `implied_yes_prob`; empty title
  distinguishes `status.empty_reason==='transport_failure'`.
- Sources `:403-409`, `:670-681` (string or `{title,url}`; href falls back to `title`).
- Unused dossier fields: `quantitative`, `contested`, `charts` (returned by `backend/app/api/research.py:429-436`).

### Component — `SimulationView.vue`

- Prop `simulationId` (`:198-200`); state (`:203-211`) with default `platform='twitter'`.
- `loadAll()` `:496-582`: if no id → clear everything; else `Promise.allSettled` of 5 GETs (`:513-519`):
  realtime profiles (platform), posts (limit 60), comments (limit 200), agent-stats, run-status. Stale guard on
  id/platform change (`:522-525`). Each result independently degrades to empty; error banner only when **all
  five** failed (`:573-578`). Then `scheduleAutoRefresh()`.
- `scheduleAutoRefresh()` `:594-601`: 10s re-poll **only** while `runner_status` is `running` or `starting`.
- Triggers: `onMounted` (`:603-605`), `watch(simulationId)` (`:607-612`), platform toggle (`:584-588`),
  Refresh button (`:30-43`).
- Display helpers: profile name/type/snippet fallbacks (`:243-265`); post author via `user_id ?? agent_id ??
  author_id ?? id` mapped through `userMap` built from profiles (`:230-240`, `:274-283`); replies grouped by
  `post_id` and sorted oldest-first (`:342-367`); relative times (`:370-397`); hashed avatar colours
  (`:406-419`); round badge `"<current_period_end> · r/N"` in calendar temporal mode else `"r / N"`
  (`:433-446`); stat tiles = every finite numeric top-level key of agent-stats `data` (`:476-487`).

### Component — `ForecastReport.vue`

- Prop `reportId` (`:271-273`). Main state (`:275-313`): `md` (primary markdown), `meta` (whole report body),
  `vizManifest`, `forecastByLang` cache, `activeLang` (null = source), `langMdCache`, translation/export
  flags, `partialSections`; module vars for poll timers/versions; `exportRequestGate =
  createLatestRequestGate()` (`:313`).
- Render states (`:4-56`): loading → error with Retry → **progressive** (`isGenerating`: no `md` and status in
  pending/planning/generating, or no status but partial sections, `:316-323`) → empty "will appear here once
  generated" (`!currentMd`) → full report.
- `load()` `:325-373`: bumps `loadVersion`, cancels translation poll/section poll/exports, resets language
  state. Empty `reportId` → clear. Else GET report; `md = data.markdown_content || ''`, `meta = data`. With a
  body → `loadVizManifest` + `loadForecast(viewLang)`; without → `startPolling()`.
- `loadVizManifest` `:376-385` (array or `[]`), `loadForecast(rid, ver, lang)` `:389-407` (dedupes in-flight by
  `version:rid:lang`; any failure (404/409/network) caches `null` → dashboard hidden).
- Report body: `currentMd` = cached translation when `activeLang` set, else `md` (`:410-415`).
  `renderMarkdown(currentMd, {resolveUrl: reportAssetUrl, citations: citationsMap, interactiveHref})`
  (`:476-488`). `citationsMap` parses `[Sn]` list items under a References/Sources/参考/来源/文献 heading
  (fence-aware, 180-char tooltip, `:447-473`). `interactiveHref` returns the `.html` twin URL only when the
  manifest contains it (`:425-442`).
- Section nav: `extractHeadings(currentMd)` (`:490-497`), indent 12px/level (`:1032-1036`), smooth
  `scrollIntoView` by heading id (`:1038-1048`). Title = first H1 else first heading (`:998-1004`).
- Header controls (`:91-144`): status pill (raw `meta.status`, `:1006-1017`); "Generate/Retry <lang>"
  (`translationAction`, `:519`, `:549-558`); "Update translation" (`translationUpdateAction` requires
  `translation_status.available && outdated && can_update`, `:523-530`); language toggle when
  `reportLanguageOptions(meta)` yields >1 option (`:112-123`, `:515-517`); residual-lines note (`:534-541`);
  issue/error text (`:543-547`); Download Markdown / Download PDF (`downloadArtifact`); Copy Markdown
  (`:1050-1072`).
- `switchLang(key)` `:560-588`: only to keys present in `langOptions`; null → source; cached → instant; else GET
  `full_report.<lang>.md` as text and cache; errors to `translationError`.
- Translation generation (`:590-733`): `generateTranslation(force)` → POST translations (`?force=1` when
  updating) → `reportTranslationPollOutcome(data, taskId)`: available → `activateCompletedTranslation` (reload
  report, verify the language is now an option, switch to it, "<lang> version is ready"); terminal →
  `finishTerminalTranslation` (error text via `terminalTranslationError`, `:616-634`); else requires a `task_id`
  and polls GET status every **1.5s** (`pollTranslation`, `:665-694`). `updateTranslationState` merges status into
  `meta.translation_status` except during an "Update translation" run (`:596-614`, flag `translationUpdateRun`).
- `downloadArtifact(kind)` `:746-801`: `fetch(href)` (Markdown: `full_report.<lang>.md` or `/download`; PDF:
  `/pdf[?lang]`) with `AbortController` gate; non-OK → JSON `error` or "Export failed (status)"; PDF bytes must
  start with `%PDF-` (`hasPdfMagic`); filename from `Content-Disposition` (sanitised) else
  `<rid>[.<lang>].<ext>`; downloads via a blob object URL + temporary `<a download>`.
- Chart gallery (`:206-235`, `:804-818`): `normalizeVizGallery(manifest)` folded into cards, minus charts
  already embedded in the current markdown (`filterVizGalleryByMarkdown`), caption localised to Chinese when
  `viewLang==='zh'`; image card with optional "Interactive ↗" link, or an HTML-only card linking to the Plotly
  page.
- Forecast dashboard (`:160-201`, `:822-901`): `fc` = forecast for `viewLang`, falling back to the source-lang
  or `''` entry (`:822-827`); top 6 scenarios by probability (`:836-843`); shown only if ≥1 scenario
  (`:846`); headline; confidence badge low/medium/high/other + rationale tooltip (`:853-871`); ensemble
  agreement / n_runs / mean σ (`:874-887`); up to 6 market-divergence tiles with `exceeds_10pp` highlight and
  signed pp delta (`:890-901`). `<BinaryForecastTable :forecast="fc">` (`:204`).
- `watch(viewLang)` `:1077-1081` lazily loads the localized forecast for a new view language.
- Progressive polling `pollOnce` `:915-971`: (1) GET `sections-partial` unless it 404'd before (accepts
  top-level `{sections}` or `{data:{sections}}`); (2) GET report: refresh `meta`; when a body appears set `md`,
  force `activeLang=null`, and on the first body load manifest + forecast; stop when status `failed`, or
  `completed|failed` **and** the translation status is terminal; else re-arm in **3s** (`:969`).
  `completedPartials`/`writingSectionLabel` render finished sections and "Writing section N: title…"
  (`:974-996`).
- Partial-report warning when `meta.partial` (or non-empty `failed_sections`) (`:147-155`, `:1020-1030`).
- Lifecycle `:1074-1087`: load on mount and on `reportId` change; cleanup on unmount.

### Component — `BinaryForecastTable.vue`

- Prop `forecast` (`:84-86`); `rows = binaryForecastRows(forecast)` (`:89`); renders nothing without rows
  (`:3`). Collapsible (default open, `:88`). Columns statement (ellipsis; tooltip adds adjustment rationale,
  `:92-94`), probability + optional `p_low–p_high` interval with source tooltip (`:96-101`), confidence chip
  (`:103-109`), market anchor (implied % linked to safe http(s) URL, signed divergence, tooltip with question /
  equivalence / match confidence / price at research / end date, `:111-121`) and "market-influenced" badge with
  prior→revised and anchor-removed/restored state (`:123-138`).

### Component — `PipelineHistory.vue`

- Prop `activeId` (`:116-118`); emits `select`, `deleted`, `cancelled` (`:120`; parent does not listen to
  `cancelled`).
- `load()` `:216-229`: GET list → `data.pipelines`; never throws; on mount (`:231`) and after each action.
  No periodic refresh.
- Row (`:58-105`): status badge, relative time, 2-line prompt, progress bar (accepts 0–1 or 0–100,
  `:249-259`); keyboard Enter/Space selects. Inline actions: running/in_progress/pending → Cancel (`:148-167`),
  else Delete (`:170-189`); header "Clear failed (N)" → POST clean, emits `deleted` per returned id
  (`:192-211`). All destructive actions go through `ConfirmDialog` (`:130-133`).
- `statusOf` `:262-274`: running|in_progress|pending → Running; completed|complete|done|success → Completed;
  failed|error|**cancelled|canceled → "Failed"**; else raw/Unknown.
- `timeAgo` `:284-315`: numbers (s vs ms by `<1e12`) or ISO strings; naive ISO strings are treated as UTC by
  appending `Z` (`:293-295`).

### Component — `SettingsMenu.vue`

- On mount GET settings (`:156-171`): `providers`, `current`, `has_api_key`; selects the current provider.
- Interface language segmented control (`:11-17`) calls `setLocale`.
- Provider cards (`:28-42`) show "requires API key" vs "local CLI subscription" and the research model
  (`deerflowModelFor`: backend `deerflow_model`, else fallback map `:129-132`, `:141`).
- Key area for `needs_key` providers (`:45-58`): password input (blank keeps a configured key for the current
  provider), optional Base URL/Model with placeholders from hard-coded `DEFAULTS` (`:133-140`).
- `canSave` `:148-152` (key required unless current provider already has one); `canTest = canSave` (`:154`).
- `testConnection()` `:173-191`: POST test (45s timeout) with provider (+ key/base/model for key providers);
  shows ✓ latency/model/detail or ✗ error. Never persists.
- `save()` `:193-215`: POST settings; clears key input; emits `changed` (parent no-op, `ResearchView.vue:440`).
- Maintenance (`:75-89`, `:218-250`): POST resolution monitor; 2xx with `data.started` → ok; 409 or `inflight`
  → "already running"; other errors → error text; note auto-clears after 6s.
- `watch(selected)` clears the last test result (`:253`).

### Component — `ConfirmDialog.vue`

- Promise-based replacement for `window.confirm` (`:28-38`). `open(opts)` (`:51-62`) resolves any pending dialog
  as `false`, sets title/message/labels/danger, focuses the confirm button, returns a Promise. `choose(ok)`
  (`:64-69`). Scrim click / Esc / ✕ → `false`. Exposed via `defineExpose({open})` (`:71`). Used by ResearchView
  (cancel) and PipelineHistory (cancel/delete/clean).

### Component — `GraphPanel.vue` (D3 force graph)

- Props (`:330-337`): `graphData`, `loading`, `currentPhase`, `isSimulating`, `seedActors`. ResearchView passes
  only `graph-data`, `loading`, `seed-actors` (`ResearchView.vue:199-201`), so the "updating live" / "simulation
  finished" overlays (`:52-78`, `:380-386`) never appear in this app. Emits `refresh`, `toggle-maximize`
  (`:363`).
- Tunables (`:321-328`): `GRAPH_UI_MAX_NODES` = `VITE_GRAPH_UI_MAX_NODES` or 400; `EDGE_LABELS_AUTO_OFF_EDGES=300`;
  `LOD_LABEL_MIN_ZOOM=0.8`; `DRAG_REHEAT_MAX_NODES=300`; `RESIZE_DEBOUNCE_MS=200`.
- Seed highlighting (`:340-361`): NFKC+lowercase+trim name match against dossier actor names → dashed orange
  ring (`:1565-1574`) and a "Researched" legend item (`:283-286`).
- Legend/type colours (`:448-461`): type = first label ≠ `Entity`; `assignTypeColors` (deterministic hash).
- Search (`:464-508`, scene API `:1746-1779`): substring match on normalised names; Enter cycles matches; focus
  pans/zooms (400ms transition) and draws a pink ring.
- Time filter (`:511-537`, `:1545-1556`, `:1781-1797`): slider over distinct `valid_at` timestamps of rendered
  edges (hidden when the slim payload has no time fields); hides edges whose `valid_at` > cutoff; expired edges
  (`invalid_at` set) are dashed and faded (`:994-996`, `:1391-1392`).
- Detail panel (`:97-258`): node/edge selection immediately shows slim data, then GET node/edge detail and merges
  (`selectNodeItem` `:563-592`, `selectEdgeItem` `:594-621`); self-loop groups expand per item with lazy edge
  detail (`:389-444`); `detailSelectionVersion` discards stale responses.
- Focus mode (big graphs) (`:623-657`, `:765-900`): `resolveRenderData` uses `graphPayloadMeta`; if the payload is
  truncated or larger than the cap, render a bounded subset: base ids from the server overview (already
  truncated), or a server `top_k=400&slim=true` fetch (`maybeFetchServerFocus`, `:717-744`, falls back to
  client top-K by degree, `:747-762`), plus seeds, expanded neighbours and the active node, all capped by
  `boundedFocusNodeIds` (`:813-821`). Clicking a node in focus mode calls GET neighbors (depth 1; falls back to
  local edges on failure, `:832-900`). "Load full graph" → GET `full=true` (`:670-699`); "Back to focus mode"
  (`:701-704`).
- `synchronizeGraphState()` `:904-943`: on graph id change or overview revision change, drops all focus/full caches
  and closes details; on id change also resets edge-label toggle, viewport, search and time filter.
- `renderGraph()` `:1008-1812`: saves previous node positions and zoom transform; rebuilds the SVG; seeds node
  positions from previous layout or backend `positions` (`buildPositionLookup`, `:947-980`); radius by
  sqrt(degree) 6–18px (`:1056-1086`); groups self-loops into one per node and curves parallel edges
  (`:1090-1189`); forces link distance `150 + (pairTotal-1)*50`, charge −400, collide 50, centre + x/y 0.04
  (`:1197-1210`); low alpha (0.3 / 0.08) when most nodes kept positions (`:1214-1219`); arrow markers
  (`:1226-1255`); zoom scale 0.1–4 with rAF batching and label LOD below 0.8× (`:1257-1290`); viewport label
  culling on zoom end / simulation end (`:1521-1543`); drag (`:1586-1646`: graphs >300 nodes move only the dragged
  node without reheating); click highlight + detail + neighbour expansion (`:1647-1665`).
- Re-render triggers (`:1816-1842`): graphData identity / node count / edge count change, edge-label toggle,
  window resize (200ms debounce), mount. Cleanup `:1844-1856`.

### Pure utilities (`frontend/src/utils/`)

- **`markdown.js`** — dependency-free, escape-first Markdown renderer. `escapeHtml` (`:17-23`, `& < > "`);
  `slugify` (`:26-33`, keeps `\w`, CJK 一-龥, spaces→`-`, 80 chars, `'h'` fallback); `safeAssetUrl` (`:38-43`:
  http(s)/data and `/…` pass; other schemes rejected; relative → `resolve()` or `''`). Citation regexes
  `CITE_RE`/`REF_HEADING_RE`/`REF_ITEM_RE` (`:48-50`); `detectRefAnchors` (`:60-71`) decides whether `[Sn]`
  superscripts become `#ref-Sn` links. `renderInline` (`:79-129`): images → `<img class=md-img loading=lazy>`
  only when `resolveUrl` given (else alt text), with optional interactive twin link labelled
  "交互版 Interactive ↗"; citations → `<sup class=md-cite>`; links (`citation:` prefix stripped; external
  http(s) opens new tab; other relative links resolved or `#`); bold/italic/code. `renderTable` (`:131-149`) wraps
  in `.md-table-wrap`. `renderMarkdown` (`:153-281`) block order: fenced code, HTML comments dropped until `-->`
  (pipeline markers such as `<!-- viz:… -->`, `:193-198`), tables, headings (id = slug), hr, blockquote, lists
  (References items get `<li id="ref-Sn">`, first occurrence only), paragraphs. `extractHeadings` (`:287-298`).
- **`reportLanguages.js`** — translation trust model. `verifiedTranslationContext` (`:29-51`) requires
  `translation_status.report_id == meta.report_id`, status `available` + `available===true`, supported distinct
  source/target, `requested_lang` (if any) == target, sha256 `markdown_sha256`, and a `translation` marker whose
  lang/source/path/sha agree. `isVerifiedTranslationRow` (`:53-65`) additionally requires row `report_id`,
  `source_markdown_sha256`, `path=full_report.<lang>.md`, `citations_path=citations.<lang>.json`,
  `final_audit_path=final_audit.<lang>.json`. `normalizeReportTranslations` (`:67-79`, dedup by lang);
  `reportLanguageOptions` (`:81-93`: `[{key:null, code:source}, …targets]`); `reportTranslationIssues`
  (`:95-115`, dedup, max 12); `reportTranslationAction` (`:117-133`: only when `can_generate===true` and target not
  available; `retry = status !== 'missing'`); `reportTranslationPollOutcome` (`:135-217`: available → terminal;
  active statuses need matching `task_id` (missing → `interrupted/task_missing`, mismatch →
  `invalid/task_mismatch`); success-without-artifact → terminal; known failures → terminal; unknown → terminal
  `invalid`); `createLatestRequestGate` (`:219-272`); `downloadFilenameFromDisposition` (`:274-287`);
  `hasPdfMagic` (`:289-294`).
- **`vizManifest.js`** — `safeChartPath` (`:4-15`: rejects absolute, `\`, `%`, control chars, `..`; must start
  with `charts/` and have ≥2 segments); `chartAssetKind` (`:17-27`: extension wins; type only for extensionless);
  `normalizeVizGallery` (`:43-75`: fold PNG/HTML twins and schema-v2 `path`+`png_path` by stem; prefer PNG);
  `filterVizGalleryByMarkdown` (`:77-95`: drop cards whose image is embedded or whose HTML is linked; a bare
  `<!-- viz: -->` marker does not count); `ZH_CHART_CAPTIONS` (`:100-117`, 16 fixed captions);
  `localizeChartCaption` (`:119-123`).
- **`liveProgress.js`** — `liveLogRevision` (`:7-18`: `"<length>:<FNV-1a of last 4 lines>"`);
  `mergeProgressLines` (`:41-89`: occurrence-count dedupe + chronological merge by ISO timestamp prefix
  `:20`); `needsFinalProgressSnapshot` (`:92-96`).
- **`runVitals.js`** — `HEARTBEAT_FRESH_S=90` (`:17`); formatters (`:40-81`); `deriveLiveness` (`:94-102`:
  terminal → null; `owner_alive===false` → dead; `stale===true` → stale; heartbeat age <90 → ok else stale;
  `owner_alive===true` → ok; else null); `buildRunVitalsModel` (`:129-204`: terminal elapsed =
  `(resumed_at||created_at) → updated_at`; ETA only for non-terminal and >0; spend only if tokens or cost >0;
  budget only with positive limit, `critical` when ratio >0.9; returns null if nothing renderable).
- **`binaryForecasts.js`** — strict `num` (`:19-26`); `formatProbability` (`:37-41`, 1 decimal %);
  `formatDivergence` (`:48-56`, tone from rounded pp); `safeMarketUrl` (`:59-62`, http(s) only); `confidenceLevel`
  (`:65-69`); interval valid only if `0≤p_low≤p_high≤1` (`:76-87`); anchor dropped if neither implied prob nor
  market id (`:93-111`); influence model independent of anchor (`:118-129`); rows need a non-empty statement
  (`:136-153`); keys `"<id|bf>-<index>"`.
- **`graphPayload.js`** — `DEFAULT_GRAPH_UI_MAX_NODES=400` (`:2`, must match backend
  `Config.GRAPH_UI_MAX_NODES`, `backend/app/config.py:1313`); `graphRequestParams` (`:4-11`); `graphPayloadMeta`
  (`:13-38`); `graphPayloadRevision` (`:42-59`); `boundedFocusNodeIds` (`:73-103`: priority active → seeds →
  expanded → base, each ranked by degree, hard cap).
- **`graphStyle.js`** — 8-colour palette (`:12-21`); FNV-1a `hashTypeName` (`:24-32`); `assignTypeColors`
  (`:46-69`, linear probing in sorted order); `nodeRadius` (`:76-82`).
- **`researchTranslation.js`** — `detectTranslationTarget` (`:14-20`) is the only export used in app code
  (`DossierViewer.vue:259`); `createLangState/onReportIdentity/storeTranslation/selectLang/activeMarkdown`
  (`:26-65`) are exercised only by tests.

### Tests (`frontend/tests/*.test.mjs`, run with `node --test`)

- `markdown.test.mjs` (HTML-comment markers dropped, kept inside fences); `graphPayload.test.mjs` (default params,
  bounded focus keeps centre/seed, revision order-insensitive); `graphStyle.test.mjs` (deterministic colours,
  radius curve); `researchTranslation.test.mjs` (pure state helpers); `liveProgress.test.mjs` (revision changes on
  rolling tail, overlap merge, late concurrent event insertion, final-snapshot rule); `vizManifest.test.mjs`
  (twin folding, traversal rejection incl. `%2e%2e`, caption localisation); `binaryForecasts.test.mjs`;
  `reportLanguages.test.mjs` (only verified rows become toggles; poll outcomes; request gate; filename/PDF magic);
  `runVitals.test.mjs`; `devServer.test.mjs` (no `--host` in npm scripts; default host `127.0.0.1`; `xfwd`
  true; boots a real Vite server and asserts it answers on loopback only — it overrides the proxy target, so the
  real `localhost:5001` target is not exercised, `tests/devServer.test.mjs:117-128`).
- No component tests (no Vue test utils); Vue files are untested.

---

## Control flow

1. **Boot**: `main.js:22-26` → router → `ResearchView` mounted → `onMounted` (`ResearchView.vue:841-857`):
   saved active pipeline → `beginPipeline` → `startPolling`; else `checkPreflight` (GET preflight).
2. **Start**: Start button → `start()` (`:456`) → POST `/api/research/run` → `beginPipeline(id)` (`:477`) →
   `startPolling()` (`:601`) → `scheduleNext(0)` → `runPoll` → `poll` (`:662`).
3. **Each poll** (`:662-759`): parallel GET status + GET progress (full once, then tail while research runs) →
   update reactive state → (maybe) final exact log snapshot (`:705-707`) → adaptive delay → (once) GET dossier →
   terminal handling. `runPoll` re-arms with `pollDelay` (`:659`).
4. **Reactive fan-out** from poll state:
   - `stages/currentStage/globalProgress/mode` → `StageTimeline` (`:181`); `liveVitals/runTiming` → `RunVitals`.
   - `logLines` → `ResearchConsole` (merge/replace in `applyProgressLogResponse`, `:492`).
   - `dossier` (after research completes) → `DossierViewer`, `seedActorNames` → `GraphPanel`, auto-switch to the
     Dossier tab (`:450-454`).
   - `graphId` → enables Graph tab; graph data only on demand (`pickTab` `:447`, Load button `:209`).
   - `simulationId` (set by backend at prepare start, `backend/app/services/pipeline_orchestrator.py:12777`) →
     `SimulationView` watch → `loadAll()`.
   - `reportId` → auto-switch to Forecast tab; `ForecastReport` watch → `load()` → progressive `pollOnce` loop until
     the body is published.
5. **Terminal**: `poll` stops itself (`:728-741`). ForecastReport and SimulationView keep their own timers
   independently (3s / 1.5s / 10s); DossierViewer has its own 4s translation poll.
6. **User actions**: Cancel (`:556`) → POST cancel → polling observes `cancelled`. Resume (`:577`) / Continue
   (`:302`) → POST → restart polling. Dossier edit → PUT dossier → `saved-continue` → `continueToFull`.
   History select (`:775`) → `resetState` + `beginPipeline`. New (`:830`) → setup page.
7. **Tab visibility**: hidden document → status poll skips network and re-checks every 12s (`:642-646`); visible
   → immediate poll at fast cadence (`:608-615`). Other components' timers do not pause when hidden.

### Polling cadence summary

| Loop | Interval | Stop condition | Anchor |
|---|---|---|---|
| Pipeline status (+ progress log) | 2.5s, ×1.5 per unchanged poll up to 12s; reset to 2.5s on any change; 12s no-request heartbeat while hidden | terminal status, 404, `stopPolling` | `ResearchView.vue:391-392`, `:640-660`, `:710-716` |
| Progress log scope | `full` once, then `tail` (`lines=500`) while research not completed; final `full` ≤2 attempts | research completed / terminal | `:668-672`, `:387`, `:542-550` |
| Run-vitals elapsed ticker | 1s (local, no network) | terminal / no elapsed | `RunVitals.vue:96-108` |
| Report sections + report body | 3s | report `failed`, or `completed|failed` with terminal translation status | `ForecastReport.vue:915-971` |
| Report translation task | 1.5s | outcome terminal/available, error | `ForecastReport.vue:665-694` |
| Research-report translation | 4s while `generating` | not generating | `DossierViewer.vue:546-552` |
| Simulation feed | 10s while `runner_status` ∈ {running, starting} | other runner status | `SimulationView.vue:594-601` |
| History list | on drawer open + after actions | — | `PipelineHistory.vue:216-231` |

---

## Data & artifacts

The frontend writes no files. Persistent client state:

| Key | Store | Content | Anchor |
|---|---|---|---|
| `drf_locale` | localStorage | `'en'` / `'zh'` | `frontend/src/i18n.js:11`, `:42` |
| `drf_active_pipeline` | localStorage | pipeline id being watched (cleared on terminal/404/reset) | `ResearchView.vue:250`, `:488`, `:730`, `:746`, `:833` |
| `mirofish_active_pipeline` | localStorage (read once, migrated, deleted) | legacy id | `ResearchView.vue:252`, `:846-852` |

Key payload contracts consumed (backend body `data`):
- **Pipeline status** (`GET /api/research/status/<pid>`): `status`, `global_progress`, `current_stage`, `stages{name:
  {status, progress, message, started_at, finished_at, error}}`, `mode`, `prompt`, `graph_id`, `simulation_id`,
  `report_id`, `error`, `created_at`, `updated_at`, `options.resumed_at`, `live{elapsed_s, eta_s, stale,
  last_progress_age_s, owner_pid, owner_alive, heartbeat_age_s, spend_so_far{tokens,cost_usd}, budget{limit_tokens,
  spent_tokens, remaining_tokens}}` (`ResearchView.vue:682-698`; backend `research.py:306-334`).
- **Progress log**: `{scope, lines[], total_exact, truncated, source_count}` (`ResearchView.vue:492-506`; backend
  `research.py:902-914`; tail lines clamped to `MAX_PROGRESS_LINES=500`,
  `backend/app/services/research_progress.py:69`, `:502`).
- **Dossier**: `{report, actors{actors[], key_events[], situation_brief{}, relationships[], hot_topics[],
  central_question, as_of_date}, sources, timeline, prediction_markets{markets[], as_of, status}, has_report, sealed,
  quantitative, contested, charts}` (`backend/app/api/research.py:422-441`).
- **Report**: `markdown_content` (empty while unpublishable), `status`, `partial`, `failed_sections`,
  `translation_status{report_id, source_lang, target_lang, requested_lang, status, available, can_generate,
  can_update, outdated, markdown_sha256, issues, translation{…}}`, `translations[]`, `publishable`,
  `publication_issues` (`backend/app/api/report.py:45-71`).
- **Forecast**: `data.forecast{scenarios[{name, probability, resolution_criteria}], headline, confidence,
  confidence_rationale, ensemble{n_runs, agreement, scenarios[{stdev}]}, market_comparison{comparisons[{statement,
  model_probability, market_implied_yes_prob, divergence, exceeds_10pp}]}, binary_forecasts[…]}`
  (`ForecastReport.vue:822-901`, `utils/binaryForecasts.js:1-16`).
- **Viz manifest**: rows `{path, png_path?, type, caption, id|name}` (`utils/vizManifest.js:43-75`).
- **Graph**: `{graph_id, nodes[{uuid, name, labels[], attributes, summary, created_at}], edges[{uuid, source_node_uuid,
  target_node_uuid, name, fact_type, fact, episodes, created_at, valid_at, invalid_at}], total_node_count,
  total_edge_count, truncated, positions?}` (`utils/graphPayload.js:13-38`, `GraphPanel.vue:947-1189`).

Important in-memory structures: `logLines` (unbounded accumulated research log, `ResearchView.vue:342`);
`forecastByLang` (`ForecastReport.vue:287`); `langMdCache` (`:291`); GraphPanel module-level `extraNodes/
extraEdges/expandedNodeIds/serverFocusData` (`GraphPanel.vue:635-649`).

---

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `VITE_API_BASE_URL` (build-time) | unset → axios baseURL `'/'`, `apiUrl` prefix `''` | absolute API origin when backend is cross-origin | `frontend/src/api/index.js:7`, `:69` |
| `VITE_GRAPH_UI_MAX_NODES` (build-time) | 400 (`DEFAULT_GRAPH_UI_MAX_NODES`) | focus-mode node budget in GraphPanel | `GraphPanel.vue:321-324`, `utils/graphPayload.js:2` |
| `FRONTEND_HOST` (dev-server env) | `127.0.0.1` | Vite listen host; non-loopback exposes UI but backend rejects LAN API calls without a token the SPA cannot send | `frontend/vite.config.js:13`; `README.md:1638` |
| Vite port / strictPort / open | 3000 / true / true | dev server port fixed, auto-opens browser | `vite.config.js:20-22` |
| Proxy target | `http://localhost:5001` (hard-coded) | must match backend `FLASK_PORT` (default 5001, `backend/run.py:48`) | `vite.config.js:25` |
| Axios timeout | 300000 ms | all requests; settings test overrides to 45000 | `api/index.js:8`, `api/settings.js:22` |
| Poll min/max | 2500 / 12000 ms | status poll cadence | `ResearchView.vue:391-392` |
| Poll failure threshold | 4 | consecutive failures before connection banner | `ResearchView.vue:386` |
| Final log snapshot attempts | 2 | exact `full` reads at research completion | `ResearchView.vue:387` |
| Progress lines | 500 | tail size requested | `ResearchView.vue:512` |
| Console page size | 2000 lines | DOM bound | `ResearchConsole.vue:134` |
| Heartbeat freshness | 90 s | liveness chip ok vs stale | `utils/runVitals.js:17` |
| Report poll / translation poll / dossier translation poll / sim refresh | 3000 / 1500 / 4000 / 10000 ms | see cadence table | `ForecastReport.vue:969`, `:684`; `DossierViewer.vue:551`; `SimulationView.vue:599` |
| Graph tunables | 300 edges (labels off), 0.8 zoom LOD, 300 nodes drag reheat, 200 ms resize | render performance | `GraphPanel.vue:325-328` |
| Hard-coded research models | claude, codex, minimax, deepseek, qwen, glm, kimi | Advanced → Research model select | `ResearchView.vue:271` |
| Hard-coded provider placeholders | per provider base URL/model | Settings Advanced placeholders | `SettingsMenu.vue:133-140` |

`FRONTEND_DIST` (backend env) chooses which built SPA Flask serves (`backend/app/__init__.py:28-33`).

---

## External calls

- **HTTP via axios** (`frontend/src/api/*.js`) to same-origin `/api/*` (dev: Vite proxy → Flask :5001). Complete
  table in the Walkthrough. Server-side LLM/subprocess side effects are triggered by: POST run
  (`ResearchView.vue:461`), resume (`:582`), continue (`:307`), PUT dossier + continue (`DossierViewer.vue:321`),
  research translation POST (`DossierViewer.vue:559`), report translation POST (`ForecastReport.vue:708`),
  settings test (`SettingsMenu.vue:184`), resolution monitor (`SettingsMenu.vue:233`).
- **`fetch()`** for exports: Markdown/PDF downloads with `Accept` header and AbortController
  (`ForecastReport.vue:760-763`).
- **Browser-driven GETs**: `<img src>` for report charts (`/api/report/<rid>/charts/…`, via `reportAssetUrl`) and
  research charts (`/api/research/<pid>/artifact/chart_…`, `api/research.js:16`); `<a href>` research PDF
  (`DossierViewer.vue:53-61`); interactive Plotly HTML links (new tab).
- **External links** (user clicks, `rel=noopener`): dossier sources (`DossierViewer.vue:232-237`), market URLs
  (`DossierViewer.vue:204`, `BinaryForecastTable.vue:49-55`), markdown http(s) links (`utils/markdown.js:115-122`).
- **Browser APIs**: `navigator.clipboard` / `document.execCommand('copy')` (`ResearchView.vue:786-815`,
  `ForecastReport.vue:1050-1072`); `localStorage`; `visibilitychange`; `URL.createObjectURL`.
- No WebSocket/SSE, no direct LLM/provider calls, no subprocesses, no DB.

---

## Cross-module edges

**Into this slice**
- `backend/app/__init__.py:88`, `:221-243` serves `frontend/dist` (built SPA) with history-mode fallback to
  `index.html`; unknown `/api/*` stays JSON 404.
- Root `package.json:11`, `:15-16` — `npm run dev` runs backend + `cd frontend && npm run dev`; `npm run build`
  builds the SPA.
- The backend auth gate (`backend/app/__init__.py:154-172`) is the only server code that reasons about the dev
  proxy (`xfwd`).
- No Python code imports frontend code; utils are consumed only by components and tests.

**Out of this slice** — every endpoint listed in the API tables. Grouped by backend module:
`backend/app/api/research.py` (run/cancel/resume/continue/status/list/preflight/dossier GET+PUT/dossier
translations/dossier pdf/artifact/progress/delete/clean/resolution-monitor), `backend/app/api/report.py`
(report GET, forecast, viz-manifest, sections-partial, full_report.<lang>.md, download, translations POST + status,
pdf, charts), `backend/app/api/graph.py` (data, neighbors, node, edge), `backend/app/api/simulation.py`
(profiles/realtime, posts, comments, agent-stats, run-status), `backend/app/api/settings.py` (llm GET/POST, llm/test).

Internal component graph: `ResearchView` → {`StageTimeline`, `RunVitals`, `ResearchConsole`, `DossierViewer`,
`GraphPanel`, `SimulationView`, `ForecastReport` → `BinaryForecastTable`, `PipelineHistory` → `ConfirmDialog`,
`SettingsMenu`, `ConfirmDialog`}; all import `i18n.js`.

---

## Invariants, gates, validation

- **Non-idempotent POSTs are never retried** (run, ontology, build, report generate/chat, sim create/prepare/start,
  interview, resolution monitor) — comments `api/research.js:22-24`, `:216-218`; `api/graph.js:7`;
  `api/report.js:5`; `api/simulation.js:3-4`. `requestWithRetry` exists but is unused (`api/index.js:75`).
- **Backend error text surfaces**: interceptor replaces `error.message` with backend `error`/`message`
  (`api/index.js:55-59`); `success:false` 2xx bodies reject (`:31-34`).
- **Start gate**: non-empty prompt and preflight ready (once checked) (`ResearchView.vue:417-419`); backend
  re-validates mode/depth/language/model and preflight on `/run` (`backend/app/api/research.py:66-109`).
- **Stale-response guards**: `pollGeneration` + pipeline id check (`ResearchView.vue:679`, `:743`);
  `loadVersion`/`languageRequestVersion`/`translationPollVersion` (`ForecastReport.vue:305-307`); DossierViewer
  `researchLangVersion` (`:283`, `:584-596`); SimulationView id/platform guard (`:522-525`); GraphPanel request
  versions (`:643-648`) and `detailSelectionVersion` (`:372`).
- **Log exactness**: only a `full`, `total_exact`, untruncated snapshot replaces the accumulated view
  (`ResearchView.vue:495-500`); a snapshot is labelled final only if terminal-ness was observed before it was
  requested (`:526-539`, `:701-707`).
- **Translation trust**: a language toggle appears only for a backend-verified, identity- and hash-bound row
  (`utils/reportLanguages.js:29-79`); translation tasks are bound to `task_id` (`:156-185`).
- **Export integrity**: PDF must start with `%PDF-` (`utils/reportLanguages.js:289-294`,
  `ForecastReport.vue:774-776`); filenames sanitised (`reportLanguages.js:285`); stale exports aborted
  (`ForecastReport.vue:756-758`).
- **HTML safety**: markdown is escaped before markup (`utils/markdown.js:17-23`, `:169`); only known URL schemes
  pass (`:38-43`, `:117-119`); interactive links only from validated manifest paths
  (`ForecastReport.vue:436-442`, `utils/vizManifest.js:4-15`); market URLs http(s) only
  (`utils/binaryForecasts.js:59-62`).
- **Graph render budget**: rendered nodes never exceed `GRAPH_UI_MAX_NODES` in focus mode
  (`utils/graphPayload.js:94-97`); initial requests are always slim overviews (`utils/graphPayload.js:4-11`).
- **Destructive actions** go through a confirm dialog (`ResearchView.vue:558-565`,
  `PipelineHistory.vue:130-133`); delete is hidden for running rows (`PipelineHistory.vue:90-103`).

---

## Failure modes & recovery

- **Backend down / network error during a run**: polling continues at current delay; after 4 consecutive failures a
  "Lost connection (retrying)" banner shows and clears on the next success (`ResearchView.vue:751-757`, `:681`).
- **Pipeline deleted / unknown id (404)**: polling stops, active key removed, status shown as failed
  (`ResearchView.vue:744-750`). History deletion of the viewed run resets to the setup page (`:837-839`).
- **Browser reload mid-run**: `drf_active_pipeline` restores the run and resumes polling (`:841-857`); full log
  re-hydrated by the first `full` request (`:669-672`).
- **Huge research log**: backend `full` may return 413; console shows "Recorded history unavailable" and continues
  with tail merges (`ResearchView.vue:514-516`, `ResearchConsole.vue:191`).
- **Preflight endpoint failure**: treated as ready; `/run` returns the real checklist (`ResearchView.vue:288-291`).
- **Report not publishable / failed**: `markdown_content` is empty (`backend/app/api/report.py:56-58`); the
  progressive loop stops and the UI shows the generic empty state (see Surprises); forecast/viz requests 409 →
  hidden (`ForecastReport.vue:400-404`).
- **sections-partial missing (404)**: falls back to report polling only (`ForecastReport.vue:930-933`).
- **Translation interrupted by backend restart**: `task_missing` → "interrupted" with retry (`reportLanguages.js:157-166`,
  `ForecastReport.vue:618-620`).
- **Graph endpoints missing (old backend)**: server focus/neighbor probes fail once and fall back to client top-K /
  local expansion for the session (`GraphPanel.vue:733-740`, `:855-860`).
- **Simulation data partially missing**: each of 5 requests degrades independently; banner only when all fail
  (`SimulationView.vue:572-578`).

---

## Surprises

1. **Suspected bug — research-report translations never display.** `DossierViewer.vue:528` and `:560` read
   `res.data.data`, but the axios interceptor already returns the JSON body (`api/index.js:28`, `:36`) and the
   backend returns `{success, data:{status, available, report, …}}` (`backend/app/api/research.py:574-591`,
   `:626-633`). So `data` is always `{}`: GET sets status `'unavailable'`; POST (which really starts a backend
   translation thread) sets `'generating'`, polls once after 4s, flips to `'unavailable'`, and stops. The cached
   translation and the language PDF link stay unavailable. `ForecastReport.vue:670`, `:710` use the correct
   `res.data` shape. The tested `researchTranslation.js` state helpers (`:26-65`) are not used by the component.
2. **Suspected bug — SimulationView rarely auto-refreshes.** `simulation_id` is published at the start of the
   prepare stage (`backend/app/services/pipeline_orchestrator.py:12777`). SimulationView loads once
   when the id appears (`SimulationView.vue:607-612`), when `run-status` is `idle` (`backend/app/api/simulation.py:1775-1786`).
   The 10s auto-refresh is armed only for `running|starting` (`SimulationView.vue:598-600`), and the id never changes
   again, so the feed stays at the prepare-time snapshot until the user clicks Refresh or switches platform.
3. **Suspected UX gap — unpublishable or failed reports look "not generated yet".** A completed-but-unpublishable
   report has empty `markdown_content` (`backend/app/api/report.py:56-58`), and a failed report has no body. Neither
   matches `isGenerating` (`ForecastReport.vue:320-323`), so the panel shows "Forecast report will appear here once
   generated…" (`:53-56`). `publication_issues`, `draft_withheld` and the failed status are never shown (no frontend
   reference to them).
4. **Suspected bug — stale dossier after Edit & Continue.** `continueToFull` (`ResearchView.vue:302-322`) keeps the
   old `dossier` and `dossierFetched=true`, and `poll` refetches only when `!dossierFetched` or `!dossier.value`
   (`:718`, `:731`). The Dossier tab keeps showing the pre-edit report.
5. **Suspected UX bug — ForecastReport resets language every 3s while translation metadata is pending.**
   `pollOnce` sets `activeLang.value = null` on every poll that sees a body (`ForecastReport.vue:947-951`) and keeps
   polling until translation status is terminal (`:956-962`). A user who switches language during that window is
   pushed back to the source every 3s.
6. **Cancelled shown as "Failed" in history** (`PipelineHistory.vue:270-271`), and cancelled stages render the
   "Waiting…" body under a "Cancelled" pill (`StageTimeline.vue:96-98`; backend sets per-stage `cancelled`,
   `pipeline_orchestrator.py:13368`).
7. **Heading-anchor mismatches (suspected)**: `extractHeadings` strips `*_\`` before slugifying but `renderMarkdown`
   slugifies the raw text (`utils/markdown.js:214-217` vs `:293-294`), so a heading containing `_` gets a different
   id in the nav and the body (nav click does nothing). `extractHeadings` also does not skip fenced code, so `# …`
   lines inside code blocks appear in the nav. Duplicate headings produce duplicate ids.
8. **Large dead API surface**: 17 of 22 `api/simulation.js` exports, 4 of 8 `api/graph.js` exports, 5 of 15
   `api/report.js` exports, `forkScenario` and `getArtifact` (`api/research.js:78`, `:92`), and `requestWithRetry`
   (`api/index.js:75`) are never called. GraphPanel's `currentPhase`/`isSimulating` overlays are unreachable in this
   app (`GraphPanel.vue:52-78`). `StageTimeline` empty state is unreachable (`:104-107`). SimulationView's
   `STAT_LABELS` keys (`:455-466`) never match the agent-stats payload `{agents_count, stats[]}`
   (`backend/app/api/simulation.py:2114-2118`); only an "Agents Count" tile renders.
9. **Drift: hard-coded lists vs backend**: research model list omits `antigravity`
   (`ResearchView.vue:271` vs `backend/app/config.py:1544`); Settings `DEFAULTS` placeholders (`SettingsMenu.vue:133-140`)
   are a second source of truth (backend has `default_base/default_model` in `PROVIDER_META` but `provider_info()`
   does not send them, `backend/app/config.py:880-893`).
10. **Comment/code drift**: `ResearchView.vue:400-401` says the rolling tail is 400 lines; the request is 500
    (`:512`) and the backend cap is 500 (`research_progress.py:69`). `GraphPanel.vue:1200` says +40 per parallel edge;
    code adds 50 (`:1203`). Backend `sections-partial` docstring says "前端 2s 轮询" (`backend/app/api/report.py:1683`);
    the frontend polls every 3s (`ForecastReport.vue:969`).
11. **Doc-vs-code drift**: `DRF_ARCHITECTURE.md:1645-1667` describes routes `/` Home, `/process/:projectId`,
    `/simulation/...`, `/report/...`, `/interaction/...`, a `store/pendingUpload.js`, "everything is `setInterval`
    polling", and Step 4 pulling `agent-log`/`console-log`. The code has a single route plus redirects
    (`router/index.js:5-21`), no `src/store/`, adaptive `setTimeout` polling (`ResearchView.vue:600-660`), and no
    callers of `getAgentLog`/`getConsoleLog`. `DRF_ARCHITECTURE.md:1790` lists `store` among frontend paths.
    `ARCHITECTURE.md:430-452` says axios baseURL is `localhost:5001` with three API modules and a 6-route table;
    the code uses `VITE_API_BASE_URL || '/'` (`api/index.js:7`) and five API modules. `README.md:291`, `:1526-1533`,
    `:1747` are accurate.
12. **Stale built SPA**: `frontend/dist` (gitignored, `frontend/.gitignore:11`) was built 2026-08-18, older than several
    sources (ForecastReport, DossierViewer, SettingsMenu, markdown.js, vizManifest.js, api/report.js). Flask at :5001
    serves that stale build (`backend/app/__init__.py:88`); only the Vite dev server (:3000) reflects the current source.
13. **LAN mode cannot authenticate**: `xfwd` makes LAN clients non-loopback to the backend gate, which then requires
    `X-API-Token` (`backend/app/__init__.py:161-171`); the SPA never sends it (`api/index.js:15-23`). Documented in
    `README.md:1638`, but the `vite.config.js:7-8` comment ("applies APP_API_TOKEN") reads as if it would work.
14. **Proxy target uses `localhost`** (`vite.config.js:25`), the spelling the same file avoids for the listen host
    (`:9-12`); the dev-server test overrides the target (`tests/devServer.test.mjs:126`), so the real target is
    untested. Unverified whether this misbehaves with an IPv4-only Flask on macOS.
15. **Unbounded memory**: `logLines` accumulates every merged tail line for the life of the view
    (`ResearchView.vue:502`); only rendering is paged (`ResearchConsole.vue:134-141`).
16. **Preflight not re-run after "New"** when the page was opened on a saved run: `reset()` (`ResearchView.vue:830-834`)
    does not call `checkPreflight`, so `preflightChecked` may stay false and the start gate is open until the mode is
    toggled (`:859`).
17. **Depth default differs from backend**: the UI always sends `depth='deep'` (`ResearchView.vue:257`, `:464`), so
    backend `Config.DEERFLOW_RESEARCH_DEPTH` (`backend/app/api/research.py:71`) never applies to UI runs.
18. **Unused dossier data**: `quantitative`, `contested`, `charts` from GET dossier (`backend/app/api/research.py:429-436`) are not
    rendered; research charts appear only when embedded as `charts/<file>` in the markdown.
19. **Markdown renderer edge cases (suspected, minor)**: bold/italic regexes run after link HTML is generated, so a
    URL containing `__x__` gets `<strong>` injected into its `href` (`utils/markdown.js:115-126`); protocol-relative
    `//host` links pass the `/` check as "internal" (`:117`); text after `-->` on a comment line is dropped
    (`:193-198`).
20. **Locale-independent formatting**: graph dates, simulation numbers and market volumes always use `en-US`
    (`GraphPanel.vue:525`, `:544`; `SimulationView.vue:491`; `DossierViewer.vue:695`); report status pills show raw
    backend status strings (`ForecastReport.vue:1006-1009`).
