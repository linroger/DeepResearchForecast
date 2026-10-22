# e2e-run — End-to-end trace of one pipeline run

From the button in the Vue SPA, through the Flask route and `PipelineOrchestrator`, every stage
(research subprocess → ontology → graph → prepare → simulation subprocess → report with forecast
extraction, visuals, publish audit and translation), to the terminal state. For each hop it also
shows how the frontend sees progress. It covers both run modes (`full`, `research_only`) and every
entry point (`start`, `resume`, `resume(force)`, `continue_to_full`, `fork`, boot-time
`reconcile_orphans`).

Read-only study of branch `main`, HEAD `c20ec60`, on 2026-10-11. I read the code directly at
every hop. The per-slice maps in `docs/handoff/codebase-study/maps/` were used only for
navigation, and each map claim repeated here was re-checked against the code.

---

## 0. Anchor basis — read this first

- **`po:N`** is `backend/app/services/pipeline_orchestrator.py` and **`cfg:N`** is
  `backend/app/config.py`, both **as committed at HEAD `c20ec60`** (13,492 and 1,656 lines).
- **Why HEAD and not the working tree?** While this trace was being written (about 23:20–23:28
  CST), another session was editing the working tree of exactly these two files. It was adding a
  data-MCP layer: `_DEPLOYED_BRIDGE_MODULES` gained `data_mcp.py`, `data_catalog.py`,
  `data_sources.py` and `data_tools.py`, and `config.py` gained a 31-line block. The on-disk
  `pipeline_orchestrator.py` grew from 13,492 to 13,496 to 13,559 lines during the session
  (`git diff --stat`, `wc -l`). Anchors into a file that is moving are useless, so the trace is
  pinned to the committed bytes. Those are also the bytes every map in `maps/` was written
  against.
- **Working-tree offsets at 23:28 CST** (from `git diff -U0` hunk headers; they may have moved
  again since):
  - `po`: HEAD lines ≤1357 are unchanged; 1358–1361 are +3; 1362–1364 are +4; 1365–2365 are +63;
    ≥2366 are +67. For example, `_run` is `po:11883` at HEAD and was line 11950 on disk at
    23:40 CST.
  - `cfg`: lines ≤1467 are unchanged; ≥1468 are +31.
- **The in-flight edit touches one hop of this trace.** It adds
  `_data_sources_subprocess_env()`, and `DeerFlowResearchRunner._run_attempt` calls
  `env.update(...)` with it, so the research child receives `DATA_SOURCES_*` env (working tree
  only; this is not in HEAD). Everything below describes HEAD behaviour.
- **Every other file cited is byte-identical to HEAD on disk**, checked with `git diff --quiet
  HEAD` over the API, report, simulation, research-progress, bridge, scripts and frontend files
  used here. Those anchors are therefore plain on-disk anchors with full repo-relative paths.
- **Abbreviations**:
  - `RV` = `frontend/src/views/ResearchView.vue`
  - `FR` = `frontend/src/components/research/ForecastReport.vue`
  - `SV` = `frontend/src/components/research/SimulationView.vue`
  - `RA` = `backend/app/api/research.py`
  - `RG` = `backend/app/services/report_agent.py`
  - `SR` = `backend/app/services/simulation_runner.py`
  - `SM` = `backend/app/services/simulation_manager.py`
  - `DR` = `deerflow_bridge/deerflow_research.py`
  - `LR` = `deerflow_bridge/linear_research.py`
  - `RPS` = `backend/scripts/run_parallel_simulation.py`

---

## 1. Topology at a glance

```
Browser SPA (Vite :3000 proxies /api → localhost:5001, frontend/vite.config.js:23-31)
 RV.start() ──POST /api/research/run──────────────▶ RA.run_pipeline (RA:50)
                                                      ├─ preflight_pipeline (po:6779)   [local checks only]
                                                      └─ PipelineOrchestrator.start (po:7920)
                                                           ├─ save pipeline_state.json (po:7968 → po:945)
                                                           └─ Thread(target=_run) (po:7970-7978)
 RV.poll() ─GET /api/research/status/<pid>──────────▶ RA.pipeline_status (RA:306) — reads the state file + `live`
           ─GET /api/research/<pid>/progress────────▶ RA.get_progress_log (RA:871) — research_progress.log tail/full
 tab bodies (always mounted, RV:193-218): Dossier GET /<pid>/dossier · Graph GET /api/graph/data/<gid>
           · Simulation 5×GET /api/simulation/<sid>/… · Forecast GET /api/report/<rid> + /sections-partial

_run daemon thread (po:11883)
 RESEARCH  DeerFlowResearchRunner.run → Popen <deer-flow>/deerflow_research.py (stdout → upd)      po:12047
           └ child: main (DR:16570) → v3 linear_research.run (LR:6326) | legacy engine
 ONTOLOGY  OntologyGenerator.generate (LLM)                                                        po:12346
 GRAPH     GraphBuilderService create/seed/add_text_batches/wait/resolve/prune (Graphiti, LLM)     po:12496-12731
 PREPARE   SimulationManager.create_simulation + prepare_simulation (LLM) + overlay/seed + reseal  po:12776-12938
 RUN       SimulationRunner.start_simulation → Popen backend/scripts/run_parallel_simulation.py    po:12989
           poll get_run_state every 5 s; RUN completion-evidence gate                              po:13005-13136
 REPORT    LLM preflight → ReportAgent.generate_report (forecast.json, charts, audit, en/zh)       po:13250-13328
 [seed ensemble] → _enforce_pipeline_health → status=completed                                     po:13335-13357
```

---

## 2. Hop-by-hop: a fresh `full` run started from the UI

### H1 — the user clicks Start (frontend)

1. `start()` (RV:456) runs only when `canStart` is true. That requires a non-empty prompt and,
   once preflight has been checked, `preflightReady` (RV:417-419). The preflight result comes
   from `checkPreflight()` → GET `/api/research/preflight` (RV:283-295; RA:355). It is treated as
   ready if the request itself fails (RV:288-291).
2. The SPA calls `runPipeline({prompt, mode, depth, max_rounds, language, model})` (RV:461-468).
   That is a single non-idempotent POST that is never retried (`frontend/src/api/research.js:28-34`).
   The UI always sends `depth` and defaults it to `'deep'` (RV:257).
3. The axios instance (`frontend/src/api/index.js:7-8`) has `baseURL`
   `VITE_API_BASE_URL || '/'` and a 300 s timeout. Its response interceptor returns the JSON
   **body** and rejects bodies with `success:false` (`frontend/src/api/index.js:26-37`).
4. In dev, Vite proxies `/api` to `http://localhost:5001` with `xfwd` (`frontend/vite.config.js:23-31`).
   Flask serves on `FLASK_HOST`/`FLASK_PORT`, default 127.0.0.1:5001 (`backend/run.py:47-57`).
   The `/api/*` auth gate lets loopback through and demands `X-API-Token` from anyone else
   (`backend/app/__init__.py:154-172`).

### H2 — Flask route `POST /api/research/run`

`run_pipeline` (RA:50). The blueprint is mounted at `/api/research` (`backend/app/__init__.py:204`).
The route does the following in order:
- requires a prompt (RA:61-63);
- requires `mode ∈ {full, research_only}` (RA:65-67, `_VALID_MODE` RA:42);
- defaults `depth` to `Config.DEERFLOW_RESEARCH_DEPTH`, which is `deep` (RA:69-71; cfg:1159),
  and validates it against `{quick, standard, deep}`;
- requires `max_rounds` to be an int (RA:75-80);
- accepts `language` or `research_language` from `{Chinese, English, auto}`, mapping `auto` to `""`
  (RA:86-90);
- checks `model` against `Config.SUPPORTED_DEERFLOW_MODELS` (RA:91-98; cfg:1544).

Then:
- `preflight_pipeline(mode, model)` (RA:101; po:6779) runs only local checks. Any error returns
  HTTP 400 with `preflight_errors` (RA:102-107).
- `PipelineOrchestrator.start(...)` (RA:109-117) returns
  `{pipeline_id, task_id, mode, status}` at once (RA:118-126). An exception returns 500 with a
  traceback (RA:127-129).
- `backend/app/api/sdk.py:136` (`/api/v1/run`, mounted only when `API_V1_ENABLED`,
  `backend/app/__init__.py:211-212`) and the in-process CLIs `backend/scripts/batch_runs.py:444`
  and `backend/scripts/scheduled_rerun.py:693` call the same `start`.

### H3 — `PipelineOrchestrator.start` (po:7920-7979)

1. `pipeline_id = "pipe_" + uuid4().hex[:12]`, then `PipelineManager.ensure_dirs` creates
   `<PIPELINE_DATA_DIR>/<pid>/handoff/` (po:7932-7933; `PIPELINE_DATA_DIR` = `backend/uploads/pipelines`,
   cfg:1581; po:875-885).
2. It creates an in-memory task `pipeline:<mode>` (po:7935-7939; `TaskManager`,
   `backend/app/models/task.py:54,73`).
3. Stages come from `RESEARCH_ONLY_BANDS` when mode is `research_only`, otherwise from the six
   `STAGE_BANDS` (po:7941-7942). The global bands are research 0-30, ontology 30-40, graph 40-60,
   prepare 60-72, run 72-92 and report 92-100 (po:95-102). research_only uses research 0-100
   (po:105).
4. It builds `PipelineState(status="running", task_id, handoff_dir, stages)` (po:7944-7952) and
   sets these options: `project_name`, `depth`, `max_rounds`, `research_language`, `research_model`
   (po:7953-7961).
5. It pins two admission policies:
   - `actor_intelligence_policy_v1` (po:7962-7964; built at po:832-853). Under the default v3
     engine it pins `required=False` with a `not_required_reason`. Only legacy plus dual-track
     pins `required=True` (po:843-852).
   - `safety_policy_v1 = capture_safety_policy_v1("admission")` (po:7967; po:776).
6. `PipelineManager.save(state)` (po:7968) writes `pipeline_state.json` atomically under the
   per-pipeline lock (po:945-956).
7. It registers the cancel `Event` and starts the daemon thread `pipeline-<pid>` with
   `target=cls._run` (po:7970-7978), then returns.

### H4 — The SPA starts observing

1. `beginPipeline(id)` (RV:477-490) resets the log state, stores `drf_active_pipeline` in
   localStorage and calls `startPolling()` (RV:601-619).
2. `runPoll` (RV:640-660) runs `poll()` and re-arms itself with an adaptive delay. While the
   document is hidden it skips the request and re-checks every 12 s (RV:642-646).
3. `poll()` (RV:662-759), in order:
   1. Picks a log scope (RV:668-672): `full` once, `tail` while research is not completed, and
      no log request afterwards.
   2. Fetches in parallel (RV:673-678):
      - `GET /api/research/status/<pid>` (`frontend/src/api/research.js:142`).
      - `GET /api/research/<pid>/progress?lines=500&scope=…` (`research.js:230`; RV:512).
   3. Copies `status`, `global_progress`, `current_stage`, `stages`, `mode`, `prompt` and `live`
      from the response (RV:682-695). It also copies `graph_id`, `simulation_id` and `report_id`,
      **sticky only when truthy** (RV:696-698).
   4. Merges or replaces the log lines and, at the research/terminal boundary, takes one exact
      final snapshot (RV:704-707; `frontend/src/utils/liveProgress.js:92`).
   5. Backoff (RV:710-716): any change in the state fingerprint (RV:402-407) resets the delay to
      `POLL_MIN_MS` = 2.5 s. Otherwise the delay grows ×1.5 up to `POLL_MAX_MS` = 12 s
      (RV:391-392).
   6. Fetches `GET /<pid>/dossier` once, when research first reports completed (RV:718-726).
   7. On `completed`, `failed` or `cancelled` it stops polling and clears the active key. On
      failure it shows the failed stage's `error` (RV:728-741).
   8. A 404 response ends polling as "pipeline no longer exists" (RV:744-750). Four or more
      consecutive non-404 errors show a connection banner while polling continues (RV:752-757).
4. Backend side of those reads:
   - `GET /status` (RA:306-334) reads `pipeline_state.json` from disk (so it survives a backend
     restart). It adds a computed `live` block from `PipelineOrchestrator().heartbeat_status`
     (RA:318; po:10302). That block holds:
     - elapsed, ETA and staleness from `estimate_eta` (po:10244). `stale` means more than
       `PIPELINE_STALE_S` = 300 s since `last_progress_at` (po:10284-10289; cfg:461);
     - owner pid liveness and heartbeat age (po:10310-10313);
     - in-process spend (po:10314-10325).

     A `budget` sub-block is added when `LLM_RUN_BUDGET_TOKENS` > 0 (RA:319-326; cfg:64 default
     0). The response sets `Cache-Control: no-store` (RA:331-333).
   - `GET /progress` (RA:871-921) merges the root `handoff/research_progress.log` with
     `handoff/track_N/research_progress.log` (`backend/app/services/research_progress.py:418-445`)
     as a bounded tail (`:500`) or an exact full snapshot (`:520`). It returns 413 when the
     snapshot exceeds the cap (RA:918-919).

### H5 — `_run` preamble (po:11883-11900)

1. `self = cls()` gives fresh per-attempt state (po:11884), and `TaskManager()` is fetched
   (po:11885).
2. `set_run_context(pipeline_id)` attributes every LLM call on this thread to the pipeline
   (po:11887-11888). The contextvar does not reach the research or OASIS subprocesses.
3. Outage breaker: `_register_outage_breaker` creates it (po:11891; po:530) and
   `_install_llm_outage_probe` wraps `LLMClient.chat` (po:11892; po:597).
4. Telemetry and manifest:
   - `_init_telemetry_flush` (po:11894; po:7557).
   - `_write_run_manifest` writes `run.json` and sets `artifacts.run_manifest` (po:11897; po:10374).
5. `_start_heartbeat` (po:11900; po:10331-10371):
   - pins `owner_pid`, `owner_boot_id` and `heartbeat_at` in memory;
   - starts daemon `pipeline-hb-<pid>`, which calls `PipelineManager.touch_heartbeat` every
     `PIPELINE_HEARTBEAT_INTERVAL_S` = 30 s (cfg:458; po:10354-10366).
   - The loop waits one interval before its first beat (`while not stop.wait(interval)`,
     po:10354), even though the comment at po:10353 says it beats immediately. The first
     persisted heartbeat therefore comes from the first stage-updater save.

### H6 — the stage updater: the only progress and cancel plumbing

Each stage builds `upd = self._make_stage_updater(state, STAGE_X)` (po:8949-9007). Every call to
`upd(local_pct, message)` does the following, in order:
1. If the cancel Event is set, raises `PipelineCancelled` (po:8961-8963).
2. If the run's outage breaker has tripped, raises `ProviderOutageHalt` (po:8967-8969). Both
   classes derive from `BaseException` (po:248, po:258), so the many inner `except Exception`
   blocks cannot swallow them.
3. Marks the stage `running`, sets progress, message and `started_at`, and **sets
   `state.current_stage`** (po:8970-8979).
4. Refreshes `last_progress_at` and `heartbeat_at` (po:8984-8987).
5. Recomputes `global_progress` from the static or dynamic bands (po:8988-8990; `_global_from_stage`
   po:8894).
6. Registers in-flight `*_partial` artifacts and calls `PipelineManager.save` (po:8993-8994).
7. Runs an opportunistic telemetry flush (po:8996-8999).
8. Calls `TaskManager.update_task` (po:9000-9005).

`_complete_stage` (po:9009-9049) sets `completed`/100, keeps the original timestamps when the stage
was reused, records stage artifacts plus the integrity manifest `handoff/manifest.json` (po:9043-9046;
po:9703), saves, and flushes telemetry. **The SPA sees exactly what these two writers put on
disk.** No progress reaches the SPA by any other route.

---

## 3. Numbered stage table

| # | Stage | Entry (call → definition) | Inputs | Outputs (artifacts) | Gates (reuse / admission / completion) | Typical failure handling |
|---|---|---|---|---|---|---|
| 0 | Preamble | `_run` po:11883 | `PipelineState` | `run.json`, `run_telemetry.json` merge base, heartbeat fields | — | wrapped by the outer try/finally po:11901/13393 |
| 1 | RESEARCH (parent) | `DeerFlowResearchRunner.run` po:12047 → po:2114 → `_run_attempt` po:2143 | prompt, `options.depth/research_language/research_model`, `state.graph_id` (only on fork/continue/resume), budget epoch | via child: `handoff/research_report.md`, `sources.json`, `actors.json`, `timeline.json`, `quantitative.json`, `contested.json`, `prediction_markets.json`, `charts/` + `charts.json`, `meta.json`, `research_progress.log`, `research_budget.json`; parent: `cast_reconciliation.json` (if merged) | reuse decision po:11919-11959 (contract valid + judge quality, or stage bit + `_validate_reuse`); pre-launch budget gate po:12038-12046; `RESEARCH_MIN_REPORT_CHARS` and error-marker guard po:2631-2645; contract finalize po:12267; actor reception (full mode only) po:12274-12286 | watchdog SIGKILL → salvage if the report is fresh, plus an extract-only child (po:2583-2618); non-zero exit, missing or short report → `RuntimeError` (po:2619-2645) → generic handler; cancel kills the process group within ~1 s (po:2464-2471, po:2578) |
| 1a | RESEARCH (child, v3 default) | `main` DR:16570 → `_dispatch_v3_engine` DR:16903/16516 → `linear_research.run` LR:6326 → `_Engine.execute` LR:4186 | CLI args, env contract built by the parent | `sources.json` then `research_report.md` (LR:5541-5542), the structured four files (LR:5546; LR:5709), markets (LR:5548), charts (LR:5550), `meta.json` | engine needs ≥`MIN_REPORT_CHARS` (LR:5530-5533); credential preflight → exit 3 (DR docstring :33-40) | every failure → exit 2 with `meta.status=failed` (LR:6345-6356; DR:16535-16541); `os._exit` (DR:17986) |
| 1b | RESEARCH post-process (parent) | po:12079-12292 | `research` dict | `options.research_lint/cast_reconciliation/research_quality/dossier_coverage/forecast_confidence_penalty/actor_intelligence_reception`; `forecast_inputs` injected for pre-v1 casts | lint is audit-only unless the report is manifest-owned and not judge-bound (po:12097-12136) | observability errors only warn; a sealed-v1 audit error and reception errors raise |
| 1c | research_only exit | po:12294-12305 | — | `status=completed`, `global_progress=100` | no health gate | — |
| 2 | ONTOLOGY | `OntologyGenerator().generate` po:12346 → `backend/app/services/ontology_generator.py:539` | `[actor_dossier.md]` (legacy only) + `report_md`, prompt, `_actors_to_context(actors)` (+ `ontology_seed_block`) | project JSON (`ProjectManager`), `handoff/ontology.json` (po:12381-12386) | reuse iff `project.ontology` is truthy (po:12312) | LLM error → generic handler (stage `ontology` failed) |
| 3 | GRAPH | `GraphBuilderService` po:12458 | report (and dossier) chunks, ontology, actors, `as_of` | FalkorDB graph, `project.graph_id`, `state.graph_id` (po:12727-12730), optional `communities.json`, `entity_merges.json`, `graph_prune.json`, `graph_priors*.json`, `actor_graph_seed_manifest.json` | reuse: stage bit + `graph_id` + `_reuse_ok` + v1 seed readback + entity count > 0 (po:12392-12441); v1 seed hard checks post-seed and post-mutation (po:12527-12534, 12644-12651) | optional sub-steps only warn; seed or contract errors raise; a failed build leaves the half-built graph id unrecorded |
| 4 | PREPARE | `SimulationManager.create_simulation` po:12776 (`SM:826`) + `prepare_simulation` po:12811 (`SM:862`) | `project_id`, `graph_id`, `report_md`, actors, `graph_priors.json`, `max_rounds`, `research_language` | `backend/uploads/simulations/<sim>/`: `state.json`, `simulation_config.json` (+ `world_state_seed`), `simulation_config_manifest.json`, `twitter_profiles.csv`, `reddit_profiles.json`, role manifests, `actor_cast_manifest.json`, actor-context packs | reuse: stage bit + sim exists + `_reuse_ok` + config seal (po:12740-12764); RUN-reuse probe before any mutation (po:12831-12853); mandatory reseal after a mutation (po:12924-12927) | prepare errors set the sim to FAILED (SM:1313-1315) and re-raise → stage failed; overlay and seed injection errors only warn; reseal error raises |
| 5 | RUN | `SimulationRunner.start_simulation(platform="parallel")` po:12989 → `SR:451` → Popen `RPS` (SR:943) | sealed config, personas | `<sim>/twitter|reddit/actions.jsonl`, `run_state.json`, `*_simulation.db`, `run_summary.json` (po:13108), `world_state_trajectory.json`, `llm_health.json` | reuse via stage bit or disk reuse (po:12941-12969); poll loop: COMPLETED/FAILED/STOPPED/stall (po:13005-13061); **completion evidence gate** (po:13130-13136) | FAILED/STOPPED/lost state/stall → `RuntimeError`; spend booked once (po:13062-13068, 13123); the independent disk watchdog stops a wedged sim (po:9113-9159) |
| 6 | REPORT | LLM preflight po:13250 → `ReportAgent(...)` po:13311 → `generate_report` po:13320 (`RG:11113`) | graph, sim, actors, sources, `report_md`, `quantitative/contested/timeline/graph_priors*` | `backend/uploads/reports/<rid>/`: `meta.json`, `outline.json`, `progress.json`, `section_NN.md`, `full_report.md`, `forecast.json`, `charts/` + `viz_manifest.json`, `citations.json`, `final_audit.json`, `full_report.<lang>.md` (+ `citations.<lang>.json`, `final_audit.<lang>.json`), `telemetry.json` | reuse keyed on the persisted report: not FAILED + health not failed + not forced + `_reuse_ok` (po:13195-13244); final read-only audit inside the agent raises (RG:11578; RG:8423-8435) | agent catches → `status=FAILED` (RG:11684-11699) → orchestrator raises (po:13326-13327); a preflight failure is attributed to RUN (see §8 F4) |
| 7 | Seed ensemble | `_maybe_run_seed_ensemble` po:13335 → po:8529 | `n_forecast_seeds` (pinned; cfg:303 default 1) | `ensemble_forecast.json` sidecar (handoff + report dir) | runs only when the pinned seed count > 1 | cancel re-raised; other errors warn (po:13336-13340) |
| 8 | Health gate + publish | `_enforce_pipeline_health` po:13345 → po:9445 | report dir, sim dir, graph options | `options.pipeline_health`; then `status=completed`, `global_progress=100`, task completed (po:13346-13356) | report health `failed` → raise (po:9493-9494); gated by `PIPELINE_HEALTH_GATE` (cfg:167) | → generic handler → failed |
| 9 | Terminal handlers + finally | po:13359-13392, po:13393-13492 | — | final `run_telemetry.json`, `telemetry.json`, `reports/<rid>/telemetry.md`, `options.llm_telemetry` | — | cancel / outage / generic handlers set status and call `fail_task`; finally always stops the heartbeat and deregisters the thread |

---

## 4. Stage-by-stage detail

### 4.1 Stage 0 — RESEARCH

**Reuse decision (po:11903-11959).**
- `handoff_dir = state.handoff_dir or PipelineManager.handoff_dir(pid)` (po:11904). A fork
  carries the base pipeline's handoff (po:8306).
- `_report_candidate`: `research_report.md` stripped to ≥400 characters (po:11905-11909).
- With a contract manifest (`research_contract_manifest.json`, po:3140):
  - it needs `_validate_research_contract` (po:11921; po:3418);
  - and `_research_contract_quality_errors` (po:11930; po:3216).
- Without a contract it needs a completed stage bit plus `_validate_reuse` (po:11947-11949;
  po:9798). `_validate_reuse` returns True when no `handoff/manifest.json` exists
  (po:9811-9816).
- A report with no contract and no stage bit is not reused (po:11950-11954).
- An evidence manifest alone triggers synthesis-only recovery (po:11955-11959).
- On reuse: `upd(95)` followed by `_load_research_handoff` (po:11961-11962; po:3857).

**Fresh path (po:11964-12078).**
1. `upd(1, "准备深度研究…")` (po:11965).
2. `_persist_research_pid` saves the child pid so `reconcile_orphans` can kill it later
   (po:11966-11968).
3. Branch selection:
   - Synthesis recovery → `_run_research_synthesis_recovery` (po:11971; po:10841).
   - Otherwise `research_engine_for_run(state.options)` (po:11983; po:5937) picks `legacy` only
     when the pinned policy has `required is True`. In every other case it takes
     `resolve_research_engine()`, which reads `Config.RESEARCH_ENGINE`, default `v3`
     (cfg:1187).
   - `research_outer_track_count` (po:11984-11988; po:5955) is **always 1 for v3**, so
     `_run_parallel_research_tracks` (po:11990; po:11060) runs only on the legacy engine with
     `RESEARCH_PARALLEL_TRACKS` > 1 (cfg:1196, default 3).
4. Single lane:
   1. Checkpoint lineage → resume flag (po:11995-12019; po:2974).
   2. Concurrency envelope (po:12020-12032).
   3. `_activate_research_budget_epoch` (po:12037; po:1815).
   4. **Pre-launch exhaustion gate** (po:12038-12046).
   5. `DeerFlowResearchRunner.run(...)` with `on_progress=upd` and the pipeline's cancel event
      (po:12047-12075).

**Inside `DeerFlowResearchRunner` (parent side).**
1. `run` (po:2114-2140) is a spend wrapper. On any exception it books the tokens already burned
   (`_flush_failed_research_attempt_spend`, po:2035) and re-raises.
2. `_run_attempt` (po:2143):
   1. Requires `deer-flow/deerflow_research.py` to exist (po:2207-2210).
   2. **Redeploys the bridge** with `_sync_deerflow_bridge_if_stale(deerflow_dir)` (po:2211;
      po:1441).
   3. Writes the prompt to a 0600 temp file in `handoff/` (po:2244-2250).
   4. Builds `cmd`: the deer-flow interpreter (`_detect_deerflow_python`, po:1229) plus
      `--prompt-file`, `--out-dir <handoff>`, `--model`, `--depth`, and optionally
      `--target-language`, `--subagents`, `--resume`, `--evidence-only` and
      `--synthesis-manifest` (po:2251-2269).
   5. Computes the watchdog budget: explicit timeout, else `.env` `DEERFLOW_RESEARCH_TIMEOUT`, else
      `Config.deerflow_depth_budget(depth)` (po:2277-2283). That budget is
      `{quick: 900, standard: 7200, deep: 21600}` s (cfg:1553), multiplied by 1.5 when dual-track,
      subagents or fan-out is on (cfg:1559-1576).
   6. Env contract: `RESEARCH_ENGINE` (po:2301) and, for v3, `DEERFLOW_RESEARCH_TIMEOUT` (po:2307).
      It also sets skill-sync proof env (po:2313-2319), budget env (`_configure_research_budget_env`,
      po:1986) and `RESEARCH_MODEL_LEASE_DB` (po:2408-2410). The KG MCP wiring
      (`DEER_FLOW_EXTENSIONS_CONFIG_PATH`, `DRF_MCP_KG_GRAPH_ID`) is set **only when `kg_graph_id`
      is non-empty** (po:2414-2424), which never happens on a first run.
   7. `on_progress(2, "启动深度研究子进程…")` (po:2426). Then `subprocess.Popen(cmd, cwd=deerflow_dir,
      stdout=PIPE, stderr=STDOUT, start_new_session=True)` (po:2428-2437), tracked in `_live_procs`
      (po:2438), with `on_spawn(pid)` (po:2441).
   8. A `threading.Timer(budget)` watchdog (po:2451-2458) and a cancel-watcher thread that kills
      the process group within ~1 s of a cancel (po:2462-2472).
   9. **Progress channel:** the parent reads the child's **stdout** line by line (po:2493). A
      `ResearchProgressEstimator` (po:2477; `backend/app/services/research_progress.py:147`,
      `observe` `:345`) maps `[tool]`, `[result]`, `[stage]`, `[ok]`, `[done]`, `[error]` and
      `[init]` lines to a monotonic, phase-banded local percentage. Each such line calls
      `on_progress(local, _tail(line))`, which is `upd` (po:2499-2531; `_tail` strips the
      timestamp/kind prefix, po:2739-2744). `[usage]` lines only add up tokens (po:2511-2525).
   10. Tail handling:
       - stdout EOF with a 30 s wait timeout leads to a salvage decision (po:2534-2565).
       - A watchdog timeout with a fresh artifact is salvaged; an `--extract-only` child runs
         when `actors.json` is missing (po:2583-2613). A timeout without a fresh artifact raises
         (po:2614-2618).
       - A non-zero exit raises (po:2619-2620). A missing, empty or too-short report, or a short
         report containing LLM error markers, raises (po:2621-2645; markers po:2748).
   11. Returns `{report, report_path, evidence_pack, actor_dossier, actors, sources, timeline,
       exit_code, research_telemetry}` after `on_progress(100, …)` (po:2681-2696).

**Inside the child (`deer-flow/deerflow_research.py`, deployed copy of DR).**
1. `ProgressLog` appends `<iso> [kind] message` to `research_progress.log` **and** echoes it to
   stdout (DR:4418-4470; filename DR:874). The parent consumes stdout; the SPA reads the file
   through `/progress`.
2. `main()` (DR:16570) resolves the engine from env (`_resolve_research_engine` DR:16381, called at
   DR:16678) and runs the credential preflight. The v3 path then dispatches through
   `_dispatch_v3_engine` (DR:16903; DR:16516-16563), which turns any exception into
   `meta.status=failed` and exit 2.
3. `linear_research.run` (LR:6326-6379) → `_Engine.execute` (LR:4186-4199) runs, in order:
   - `phase_plan` (LR:4203), `replan_after_outage`, `load_followups`
   - `phase_gather` (LR:4396)
   - `phase_gap` (LR:4637)
   - `phase_synthesize` (LR:4808)
   - `phase_qa` (LR:5166)
   - `phase_finalize` (LR:5526)
4. `phase_finalize` writes, in this order:
   1. `sources.json` **before** `research_report.md`, so a salvaged report always has its sources
      (LR:5537-5542).
   2. actors/timeline/quantitative/contested (LR:5546; LR:5709).
   3. prediction markets via the bridge's `_collect_prediction_markets` (LR:5548; DR:15476).
   4. research charts via `_render_research_charts` (LR:5550; DR:15931), which runs the
      forecast-visuals `render.py` and embeds a Visual Annex.
   It then sets `meta.status=completed` (LR:5565).
5. The process exits with `os._exit(main())` (DR:17980-17986).
6. Legacy engine (pinned `required=True`, or `RESEARCH_ENGINE=legacy`): `run_research_stage`
   (DR:12331) for Track A and `run_actor_ontology_stage` (DR:14133) for Track B. See maps dfr-1..6.

**Post-processing in the parent (po:12079-12292).**
- Research lint (po:12084-12147). It is audit-only for single-lane/v3 runs because no contract
  manifest exists (po:12097-12099).
- Cast reconciliation (po:12156-12203).
- Telemetry (po:12205; po:10430) and the optional embedder warm-up (po:12208).
- Research-quality surfacing (po:12210-12213; po:10564) and dossier coverage (po:12215-12233).
- `forecast_inputs` fallback parse (po:12235-12261; po:5752).
- `_finalize_research_contract` (po:12267; po:3607). It is a no-op without a contract manifest,
  and the only writers of that manifest are the synthesis/parallel paths (po:11040, po:11581).
- Advisory confidence penalty (po:12273).
- **Actor-intelligence reception** in full mode (po:12274-12286; po:5668). Under the default v3
  admission the policy has `required=False`, so it records the reason and passes.
- `_complete_stage(RESEARCH)` (po:12287-12292).

**research_only exit (po:12294-12305).** It sets `status=completed` and `global_progress=100`,
saves, completes the task and returns. There is no health gate, no reception check and no
`telemetry.md`. The `finally` block still runs.

### 4.2 Stage 1 — ONTOLOGY (po:12307-12387)

1. `upd` plus `_update_manifest`, which pins the provider/model into `run.json`
   (po:12308-12309; po:10393).
2. **Reuse** when `ProjectManager.get_project(project_id).ontology` is truthy (po:12311-12314).
   `ontology.json` is not integrity-checked on this path.
3. Otherwise:
   1. If there is no project yet: `upd(10)`, then `create_project`, set the prompt, save the
      extracted text, save, and record `state.project_id` (po:12316-12326;
      `backend/app/models/project.py:133,168`).
   2. `upd(40, "生成本体（LLM）…")` (po:12328).
   3. `OntologyGenerator().generate(document_texts=[dossier]? + [report_md], …, template=None,
      central_question, actors)` (po:12346-12360).
   4. Keeps the rich ontology dict (po:12366-12374) and saves the project (po:12375-12377).
   5. Writes `handoff/ontology.json` atomically (po:12381-12386).
   6. `_complete_stage` (po:12387).
4. Under v3 no `actor_dossier.md` is produced: `linear_research.py` has no reference to it, and
   the parent reads the file from the handoff at po:2659-2660. `document_texts` is therefore
   `[report_md]` (po:12349).

### 4.3 Stage 2 — GRAPH (po:12389-12731)

1. **Reuse** (po:12392-12455) requires all of the following:
   - a completed stage bit and a `graph_id` (po:12392-12394);
   - `_reuse_ok(GRAPH)` (po:12398-12401);
   - for sealed v1 actors only, a seed-manifest readback (po:12402-12426);
   - `ZepEntityReader().filter_defined_entities` count > 0 (po:12427-12441).

   It then re-registers the ontology in memory and completes the stage (po:12442-12455).
2. **Build**:
   1. `upd(5)` (po:12457).
   2. Report and dossier chunks (po:12462-12472).
   3. Chunk-source choice (po:12484-12494). Note: `GRAPH_CHUNK_SOURCE` defaults to
      `dossier_only` (cfg:481), but with no dossier (every v3 run) the code falls through and
      ingests **report chunks only**, without recording `options.graph_chunk_source`.
   4. `_recompute_dynamic_bands(chunk_count)` (po:12495; po:8904).
   5. `create_graph` (po:12496; `backend/app/services/graph_builder.py:1221`) and `set_ontology`
      (po:12499-12502).
   6. `as_of` validation (po:12512-12523; po:10795).
   7. `_seed_research_actors` (po:12524; po:7184) and the post-seed contract check
      (po:12527-12534; po:7080).
   8. `add_text_batches` with progress `upd(10 + ratio·55)` (po:12539-12546;
      `graph_builder.py:2288`).
   9. Ingest-loss ratio → `options.graph_ingest_degraded_ratio` (po:12551-12567).
   10. `_wait_for_episodes` with progress `upd(65 + ratio·33)` (po:12569-12572;
       `graph_builder.py:2427`).
   11. Optional communities (`GRAPH_BUILD_COMMUNITIES`, default off), entity resolution (default
       on) and pruning (default on) (po:12576-12637; `backend/app/services/zep_entity_resolver.py:480`;
       `backend/app/services/graph_pruner.py:244`).
   12. Post-mutation v1 seed check (po:12644-12651).
   13. Duplicate-name detection (po:12660-12685).
   14. Integrity, priors and `graph_priors*.json` (po:12689-12725).
3. **`state.graph_id` is first set at the very end** (po:12730), or at po:12444 on reuse. The SPA's
   Graph tab therefore unlocks only once GRAPH has completed (RV:432). The graph created at
   po:12496 is not referenced from state while it is being built.

### 4.4 Stage 3 — PREPARE (po:12733-12938)

1. **Reuse** (po:12740-12767) needs a completed stage bit, an existing sim state,
   `_reuse_ok(PREPARE)` and `validate_prepared_simulation_config` (`SM:1352`).
2. **Rebuild**:
   1. `upd(5)`, then `create_simulation(project_id, graph_id, twitter=True, reddit=True)`
      (po:12775-12776; `SM:826`).
   2. **`state.simulation_id` is set and saved right away** (po:12777-12782). This is what unlocks
      the SPA's Simulation tab.
   3. `prepare_cb` maps the manager's `(stage, progress, message)` to `upd(5..99, "stage: message")`
      (po:12784-12785).
   4. Persona fan-out is 16 for openai-compatible providers, otherwise 3 (po:12789, 12804, 12816).
   5. `max_rounds` is passed only when given explicitly, or in non-calendar mode (po:12809-12810;
      `SIM_TEMPORAL_MODE` default `calendar`, cfg:1067).
   6. `prepare_simulation(...)` (po:12811-12821) runs `SM:862-1316`:
      1. status PREPARING (`SM:907`);
      2. stage 1, entity read and filter (`SM:912`);
      3. cast manifest and actor-context packs (`SM:972-987`);
      4. stage 2, profiles (`SM:1032-1144`);
      5. stage 3, LLM config generation (`SM:1146-1186`);
      6. audience agents (`SM:1188`);
      7. **config seal** built and validated (`SM:1281-1299`);
      8. status READY (`SM:1301`).
3. **RUN-reuse probe before any mutation** (po:12831-12853): `_completed_sim_reusable`
   (po:9976) and `_run_reuse_ready` (po:9910). This keeps the sealed config bytes of an
   already-completed run untouched.
4. **Mutations**, only when `not _run_already_done`:
   - the fork scenario overlay (po:12855-12871; po:8353);
   - the WorldState seed (po:12878-12917), injected unconditionally in calendar mode.
5. **Reseal** after a mutation (po:12924-12927; `SM:1318`). A reseal failure raises.
6. `_complete_stage(PREPARE)` comes **after** the mutations (po:12933-12938), so the stage's
   integrity hash covers the final config.

### 4.5 Stage 4 — RUN (po:12940-13183)

1. **Reuse** (po:12941-12972):
   - The stage bit counts only when PREPARE itself was reused (po:12948-12951).
   - It also needs `_run_reuse_ready` (po:12952-12955) and `_reuse_ok(RUN)` (po:12957-12960).
   - Alternatively the disk-reuse result from the PREPARE probe is used (po:12963-12969).
2. **Fresh run**:
   1. `upd(2)`; `run_kwargs={"platform":"parallel"}` plus an optional `max_rounds`
      (po:12974-12982).
   2. Graph feedback is enabled only through the pinned safety policy (po:12985-12988).
   3. `SimulationRunner.start_simulation` (po:12989), which runs `SR:451-993`:
      1. re-validates the role, context and cast manifests and the config seal (`SR:470-760`;
         `validate_simulation_config_seal` `SR:656`);
      2. picks `run_parallel_simulation.py` for `parallel` (`SR:884`);
      3. builds `cmd = [python, script, --config, …, --config-seal, …]`, plus optional
         `--max-rounds`/`--resume` (`SR:907-921`);
      4. `Popen(cwd=sim_dir, stdout=simulation.log, start_new_session=True)` (`SR:943-953`);
      5. saves `run_state` as RUNNING (`SR:964-966`);
      6. starts the monitor thread `_monitor_simulation` (`SR:970-976`; `SR:1012`).

      The monitor tails `twitter|reddit/actions.jsonl` every 2 s (`SR:1029-1045`). A
      `simulation_end` event on every enabled platform flips the runner to **COMPLETED while the
      child stays alive for IPC interviews** (`SR:1189-1212`). An exit 0 without
      `simulation_end` becomes FAILED (`SR:1086-1104`).
   4. Child process: `RPS` `main()` (`RPS:5779`) runs Twitter and Reddit concurrently
      (`asyncio.gather(..., return_exceptions=True)`, `RPS:5930-5936`), logs `simulation_end`
      (`RPS:5219`, `RPS:5770`), then waits for IPC commands (`RPS:6029`).
   5. Watchdogs:
      - the independent disk watchdog (po:13001; po:9113);
      - the inline stall timer, default 1800 s (po:12996-12998; cfg:355).
   6. **Poll loop every 5 s** (po:13005-13061):
      1. checks cancel first and stops the sim before raising (po:13007-13013);
      2. reads `get_run_state` (po:13014; `SR:310`);
      3. only on a round change: recomputes the dynamic bands the first time `total > 0`
         (po:13022-13042) and calls `upd(min(98, cur/total·100), "模拟轮次 cur/total")`
         (po:13043-13048);
      4. COMPLETED → break; FAILED or STOPPED → raise (po:13049-13052); stall → stop the sim and
         raise (po:13055-13060).
   7. `except BaseException` books the sim spend once and re-raises (po:13062-13068). `finally`
      retires the watchdog (po:13069-13070).
   8. Confluence barrier when feedback is on (po:13082-13095).
3. **Shared tail**, for fresh and reused runs alike:
   1. `_publish_run_summary` (po:13101-13117; po:10086).
   2. Sim spend (po:13123).
   3. **`_require_run_completion_evidence`**: every enabled platform needs `simulation_end`, and
      a valid summary must exist (po:13130-13136; po:10059).
   4. Reconcile the API-facing sim state (po:13142-13166).
   5. `_complete_stage(RUN)` (po:13170-13175).
   6. Decision-channel summary (po:13180-13183).

### 4.6 Stage 5 — REPORT (po:13185-13328) and the steps inside `ReportAgent.generate_report`

**Reuse (po:13186-13244).**
1. The reuse candidate is `ReportManager.get_report(state.report_id)`
   (`RG:14285`), falling back to `get_report_by_simulation` (`RG:14353`) (po:13195-13206).
2. A deliverable-health `failed` result rejects it (po:13211-13222).
3. `force_report_regen` rejects it (po:13224-13226).
4. `_reuse_ok(REPORT)` must pass (po:13227-13240).
5. Reuse then happens when the report's `status != FAILED` (po:13241-13244).

**Regenerate (po:13245-13328).**
1. **LLM preflight**: a uuid-salted "ping". On failure it raises "报告前置探测失败…"
   (po:13250-13261; `REPORT_LLM_PREFLIGHT` cfg:503).
2. `_clear_report_attempt_artifacts`, then mint `report_<hex12>`, set **`state.report_id`, and
   save** (po:13265-13268). This is what unlocks the SPA's Forecast tab.
3. `upd(5, "生成预测报告…")` (po:13269).
4. Fork context: `scenario_label` and `base_simulation_id` (po:13271-13279).
5. Build `ReportAgent(**_ra_kwargs, **_ra_artifacts)` (po:13285-13315; ctor `RG:1533`).
6. `report_cb` maps to `upd(5..99, "stage: message")` (po:13317-13318).
7. `generate_report` (po:13320), then `save_report` (errors ignored) and adopt the id
   (po:13321-13325). `status == FAILED` → `RuntimeError(report.error)` (po:13326-13327).
8. `_complete_stage(REPORT)` (po:13328).

**`generate_report` (RG:11113-11717), in order.**

| Step | Anchor | Output / effect |
|---|---|---|
| create folder, PENDING `meta.json` + `progress.json` | RG:11182, RG:11195-11199 | `GET /api/report/<rid>` stops returning 404 from here on |
| PLANNING; signal pack, market pack | RG:11202-11240 | prompt context |
| **forecast spine before prose** (`REPORT_FORECAST_SPINE_FIRST`) | RG:11243-11245 (def RG:2847) | early `forecast.json` spine |
| outline (`plan_outline`, progress `prog//5`) | RG:11248-11267 (def RG:9851) | `outline.json` |
| GENERATING; **concurrent section precompute** when `REPORT_SECTION_CONCURRENCY` > 1 (default 6, cfg:1535) | RG:11272-11303 (def RG:10064) | section bodies in memory |
| bookkeeping loop: `progress_callback("generating", 20+70·i/N, …)`, `save_section` | RG:11309-11324, RG:11413 | `section_NN.md` |
| resurrect placeholder sections; assemble; status COMPLETED (in memory) | RG:11473, RG:11489-11495 | `full_report.md` |
| **structured forecast extraction / calibration → `forecast.json`** | RG:11500-11505 (def RG:2951) | `forecast.json` (+ quality) |
| Part-1 binary table | RG:11508-11512 (def RG:8643) | report markdown |
| **visuals**: `_inject_visualizations` → `ReportVisualizer().build_all` | RG:11517-11521; RG:8882, RG:8906; `backend/app/services/report_visualizer.py:4313` | `charts/*`, `viz_manifest.json` |
| three-part skeleton, resolution section, language purity | RG:11525-11545 | markdown |
| editorial lint | RG:11549-11553 | `forecast.json` `quality.lint` |
| **citation finalizer / publish stabilizer** | RG:11555-11570 (def RG:7991) | References appendix, `citations.json` |
| **final read-only publish audit** (raises → FAILED path) | RG:11577-11578; RG:8423-8435 | `final_audit.json` |
| **bilingual translation** (`REPORT_BILINGUAL`, default true, cfg:704; failures only logged) | RG:11584-11589 (def RG:7414) | `full_report.<lang>.md`, `citations.<lang>.json`, `final_audit.<lang>.json` |
| persist final meta + `progress.json` "completed"; callback("completed", 100) | RG:11664-11674 | — |
| any exception → `status=FAILED`, save, progress "failed", **return** (no raise) | RG:11684-11699 | orchestrator raises at po:13326-13327 |

### 4.7 Seed ensemble, health gate, publish, finally

1. Seed ensemble: `_maybe_run_seed_ensemble` (po:13333-13340; po:8529) returns at once unless the
   pinned `n_forecast_seeds` is greater than 1 (cfg:303, default 1).
2. `_enforce_pipeline_health` (po:13345; po:9445-9497) does the following:
   - report health `failed` → raise;
   - run and graph degradation → `options.pipeline_health`;
   - an exception inside the assessment is swallowed (po:9490-9492).
3. **Publish** consists of `status="completed"`, `global_progress=100`, `PipelineManager.save` and
   `task_manager.complete_task` (po:13346-13356). The deliverable itself was already published to
   disk inside `generate_report`.
4. Exception handlers (po:13359-13392):
   - `PipelineCancelled` → `cancelled`. The current stage becomes `cancelled` unless it is already
     completed or at 100.
   - `ProviderOutageHalt` → `_halt_for_provider_outage` (po:9766) → `failed` plus
     `options.provider_outage_halt`.
   - `Exception` → `failed` plus `_fail_stage(state.current_stage)` (po:9757).
5. `finally` (po:13393-13492):
   1. stops the heartbeat;
   2. writes the final `run_telemetry.json` (po:13430);
   3. writes stage `telemetry.json` and `options.llm_telemetry`, then saves (po:13443-13459);
   4. writes `telemetry.md` when completed (po:13464-13474);
   5. `LLMMeter.reset` (po:13483);
   6. clears the breaker (po:13488);
   7. pops `_threads` and `_cancel_events` (po:13491-13492).

---

## 5. Entry points and run modes

| Entry | Trigger (frontend / API) | Orchestrator | State mutation before `_run` | What `_run` then does |
|---|---|---|---|---|
| **start** (`full`) | RV:456 → `research.js:28` → RA:50 | po:7920 | fresh stages, options, pinned policies (po:7941-7967) | all stages; first `upd` sets `current_stage` (it is `""` until then, po:691) |
| **start** (`research_only`) | same, with mode toggle RV:80-86 | po:7920 | only the `research` stage (po:7941) | RESEARCH, then early exit po:12294-12305; `global_progress` uses research 0-100 (po:105) |
| **resume** | Resume button only when failed/cancelled (RV:554, RV:577-598) → `research.js:53` (no body) → RA:147 (preflight with the stored mode, RA:153-161) | po:8107-8211 under `_lifecycle_lock` | live thread → 409; running → reclaim only if `_orphan_is_dead`, else 409 (po:8132-8142); completed → refused unless `force` and health degraded/failed (po:8143-8151); resets `current_stage` if failed/cancelled (po:8166-8170); new task, `resume_count++`, safety pin backfilled if missing (po:8173-8199) | same `_run`; each stage reuses its persisted work behind integrity gates; a new budget epoch for research (max `RESEARCH_BUDGET_MAX_EPOCHS`, cfg:543) |
| **resume(force=true)** | **API only**: `{"force":true}` (RA:163); the SPA never sends it (`research.js:53-58`) | po:8159-8164 | resets REPORT, sets `current_stage=report` and `options.force_report_regen` | earlier stages are reused; REPORT reuse is skipped once (po:13224-13226) |
| **continue_to_full** | "Continue to full pipeline" when completed + research_only (RV:299-301, RV:302-322), also after a dossier edit (DossierViewer `saved-continue`) → `research.js:65` → RA:184 (preflight full) | po:8214-8277 | requires research_only + completed + non-empty `research_report.md` (po:8233-8241); flips mode to `full`, keeps RESEARCH completed and resets the rest; `current_stage=ontology` (po:8245-8264) | RESEARCH goes through the reuse path (for v3: stage bit + `_validate_reuse`; an edited dossier passes because `refresh_research_artifact_manifest` re-records it, po:3444; RA:767); **reception now runs** because the mode is full (po:12274) |
| **fork** (what-if) | **API/CLI only**: `forkScenario` is exported but unused by the SPA (`research.js:78`); RA:219 needs a `label` (RA:231-232) | po:8280-8350 | new id; shares the base `project_id`/`graph_id`/**`handoff_dir`** (po:8300-8307); marks RESEARCH/ONTOLOGY/GRAPH completed (po:8309-8314); options = overlay/label/base id/project name plus the actor policy (po:8315-8331); `current_stage=prepare` (po:8341) | RESEARCH and GRAPH reuse checks run against the fork's **own empty** `handoff/manifest.json` (po:1107-1110, 9811-9816), so they pass vacuously; PREPARE creates a new sim and applies the overlay (po:12855-12871); REPORT gets `scenario_label`/`base_simulation_id` (po:13271-13279) |
| **boot reconcile** | process start (`backend/app/__init__.py:140-141`) | `reconcile_orphans` po:7637 | a `running` pipeline with no thread and dead evidence is salvaged to completed when its report is complete (po:7689-7715), otherwise marked failed (po:7716-7731) | no `_run`; the user resumes |
| **CLI drivers** | `backend/scripts/batch_runs.py:444` (start; fork-like lanes :247-350), `backend/scripts/scheduled_rerun.py:693` | `start` in-process | — | same `_run`, in the script's process |

Variations inside a mode, which change what RESEARCH does but not which stages run:
- **depth** is `quick`, `standard` or `deep`. It sets the watchdog budget (cfg:1553-1576) and the
  engine preset.
- **engine** is v3 (default) or legacy. Legacy runs when the policy is pinned `required=True`
  (po:5937-5952), or when `RESEARCH_ENGINE=legacy` and the policy does not require it.

---

## 6. How the frontend observes each stage

All observation is HTTP polling. There is no SSE or WebSocket. Tab bodies are mounted with
`v-show` (RV:193-218), so `SimulationView`/`ForecastReport` react to prop changes even while
hidden.

| Stage | Main signal (status poll → `StageTimeline` RV:181, `RunVitals`) | Extra channel | Tab unlock (RV:427-437) |
|---|---|---|---|
| (queued) | `status=running`, all stages pending, `current_stage=""` → title "Running…" (RV:420-425) | — | Live log |
| RESEARCH | per research stdout line: `stages.research.progress` (estimator) + `_tail(line)` message; `global_progress` 0-30 (0-100 for research_only) | `GET /progress`: one `full` hydration, then `tail` until research completes; then one final exact snapshot (RV:668-672, 704-707) | Dossier once `stages.research.status == completed`; dossier fetched once (RV:718-726); auto-switch to Dossier (RV:450-454) |
| ONTOLOGY | `upd(10)`, `upd(40)`, then 100 | — | — |
| GRAPH | `upd(5)`, `upd(8)` seed, `10..65` ingest, `65..98` episode wait, `99` post-steps | — | Graph tab only after `state.graph_id` (po:12730); data fetched lazily on tab pick or button (RV:442-448, RV:761-773) |
| PREPARE | `upd(5)`, then `prepare_cb` "stage: message" 5..99 | — | Simulation tab as soon as `simulation_id` is saved (po:12777-12782) → `SV` `loadAll()` once (SV:496, SV:607-612) |
| RUN | `upd` only on round change: "模拟轮次 cur/total" | `SV` re-polls every 10 s **only while** `runner_status ∈ {running, starting}` (SV:594-601) | — |
| REPORT | `upd(5)`, then `report_cb` "planning/generating…: msg" 5..99 | `FR` `load()` → `GET /api/report/<rid>`; while there is no body it polls `sections-partial` + report every 3 s (FR:915-971); after completion it waits for a terminal translation status | Forecast tab when `report_id` appears (po:13267-13268); auto-switch to Forecast (RV:450-454) |
| DONE | `status=completed`, `global_progress=100` → `stopPolling` (RV:728-741) | `FR` keeps its own 3 s/1.5 s timers until done | — |

**Liveness (`RunVitals`).** The `live` block (po:10302) drives the chip (`frontend/src/utils/runVitals.js:84-100`):
- `owner_alive === false` → dead;
- `stale === true` (more than 300 s without an `upd`) → "still thinking";
- otherwise the heartbeat age decides.

---

## 7. Cancel, outage, failure and crash paths

| Event | Where it is observed | Effect |
|---|---|---|
| User cancel | `POST /<pid>/cancel` (RV:556-575 → RA:132 → po:7982-8016) sets the Event | RESEARCH: the cancel watcher kills the process group in ≤1 s (po:2462-2471) → `PipelineCancelled` (po:2578). Other stages: next `upd` (po:8961-8963). RUN: top of the 5 s poll, after `stop_simulation` (po:13007-13013). Handler → `cancelled` (po:13359-13376). |
| Provider outage | breaker trips through the `LLMClient.chat` probe (po:597) | raised only from `upd` (po:8967-8969) → `_halt_for_provider_outage` (po:13377-13380). `chat()` calls made before the next `upd` fail fast as ordinary `RuntimeError`s. |
| Stage exception | any `Exception` | `failed` + `_fail_stage(current_stage)` (po:13381-13392). The SPA shows the failed stage's error (RV:738-740). |
| Backend crash | — | state stays `running`; the next boot runs `reconcile_orphans` (po:7637), or `resume` reclaims it in place once the owner is dead (po:8132-8142) |
| SPA reload | `onMounted` restores `drf_active_pipeline` and resumes polling (RV:841-857) | — |

---

## 8. Findings (code-level; none runtime-verified)

- **F1 — Concurrent section generation silences the REPORT stage (new).**
  - **Cause.** With the default `REPORT_SECTION_CONCURRENCY=6` (cfg:1535), `generate_report`
    pre-generates every body and tail section in `_generate_sections_concurrent` (RG:11300-11303).
    Those calls get a `_noop` progress callback (RG:10082-10089, RG:10106-10109). Sections are
    written to disk, and `progress_callback` (→ `report_cb` → `upd`) fires, only in the
    bookkeeping loop afterwards (RG:11309-11324, RG:11413). For the whole precompute window:
    - `PipelineCancelled` and `ProviderOutageHalt` cannot be raised;
    - `last_progress_at` stays frozen, so `live.stale` turns true after 300 s
      (po:10288-10289);
    - `sections-partial` has no `section_NN.md` to show.
  - **Effect.** A user cancel is honored only after all sections have been generated.
- **F2 — Forecast tab can latch a 404 error (suspected race, new).**
  - **Cause.** The orchestrator saves the new `report_id` (po:13266-13268) before `ReportAgent`
    is built (po:13311). The report folder and `meta.json` appear only later
    (RG:11182, RG:11199). `GET /api/report/<rid>` returns 404 while `meta.json` is missing
    (`backend/app/api/report.py:564-569`).
  - **Effect.** If a status poll lands in that window, `ForecastReport.load()` shows an error
    panel with a manual Retry and does not poll (FR:365-369, FR:10-13). It reloads only when the
    id changes (FR:1075).
- **F3 — Under the default v3 engine the dossier plumbing is inert (new).**
  - **Cause.** v3 writes no `actor_dossier.md` (no reference in `deerflow_bridge/linear_research.py`)
    and no research contract manifest (its only writers are po:11040, po:11581).
  - **Effect.** Ontology sees `[report_md]` only (po:12349). The graph ingests report chunks even
    though `GRAPH_CHUNK_SOURCE=dossier_only` (po:12484-12494; cfg:481). Research lint is
    audit-only (po:12097-12099). Research reuse falls back to the stage bit plus
    `_validate_reuse` (po:11947-11949).
- **F4 — REPORT preflight failure is charged to RUN (confirmed, orch-h Surprise 1).**
  - **Cause.** No `upd` runs between `_make_stage_updater(REPORT)` (po:13186) and the preflight
    (po:13250-13261). `current_stage` is therefore still `run`, and the generic handler fails RUN
    (po:13385-13386).
  - **Effect.** `resume` then resets RUN (po:8166-8170). Only the disk-reuse probe saves the
    simulation from being re-run (po:12831-12842).
- **F5 — SimulationView goes stale during RUN (confirmed, frontend Surprise 2).**
  - **Cause.** `simulation_id` appears during PREPARE (po:12777-12782), while `run-status`
    reports `idle` because no `run_state` exists yet (`backend/app/api/simulation.py:1775-1786`).
    The 10 s refresh is armed only for `running`/`starting` (SV:598-600), and the id never
    changes again (SV:607-612).
  - **Effect.** The feed stays at its PREPARE-time snapshot until the user refreshes manually.
- **F6 — The SPA cannot force-resume or fork (new).**
  - **Cause.** `resumePipeline` posts no body (`frontend/src/api/research.js:53-58`), and Resume
    shows only for failed/cancelled runs (RV:554). `forkScenario` is never called
    (`research.js:78`).
  - **Effect.** Completed-but-degraded regeneration (po:8143-8165) and what-if forks are
    API/CLI-only.
- **F7 — `task_id` is write-only from the UI's point of view (new).**
  - **Cause.** `/run`, `/resume` and `/continue` return `task_id` (RA:118-126), and `_run` updates
    the in-memory `TaskManager` on every `upd` (po:9000-9005). The SPA reads only `pipeline_id`
    (RV:469, RV:583, RV:307) and never polls a task.
  - **Effect.** Pipeline progress is observable only through `pipeline_state.json`.
- **F8 — Terminal status is visible before the final telemetry saves (new, low impact).**
  - **Cause.** `completed` is saved at po:13346-13348. `artifacts.run_telemetry` and
    `options.llm_telemetry` are saved later, in `finally` (po:13431-13434, po:13453-13459). The
    SPA stops polling on the first terminal status it sees (RV:728-731).
  - **Effect.** A live session never sees `llm_telemetry`; reopening the run does.
- **F9 — Research progress is persisted per stdout line (new, observational).**
  - **Cause.** Every progress-kind line of the child calls `upd` (po:2499-2531). Each `upd` does a
    full atomic `pipeline_state.json` rewrite plus a `TaskManager` update (po:8993-9005), with no
    throttle.
- **F10 — Global progress can move backwards (confirmed, orch-e Surprise 4).**
  - **Cause.** RUN's first `upd(2)` uses the old band. The band is then recomputed with
    `total_rounds` (po:12974, po:13039-13040; po:8904-8947), and nothing clamps
    `global_progress` (po:8988-8990).
- **F11 — The research child's progress is consumed in two places (doc drift).**
  - **Cause.** The bridge docstring says the parent "tails `research_progress.log`"
    (`deerflow_bridge/deerflow_research.py:19-21`). In fact the parent reads child **stdout**
    (po:2493), and the log file is read only by `GET /progress`
    (`backend/app/services/research_progress.py:418-445`).
- **F12 — Docstring drift in `research.py` (new).**
  - The module docstring says `GET /status` returns "聚合的五阶段进度" (five stages) (RA:11), but
    there are six stages (po:87-102).
  - The `/run` docstring says depth defaults to `standard` (RA:58); it defaults to `deep`
    (RA:71; cfg:1159). The api-core map already notes this second point.
- **F13 — Concurrent working-tree edits (process finding).** `pipeline_orchestrator.py` and
  `config.py` were being modified by another session during this study (§0). The new
  `_DEPLOYED_BRIDGE_MODULES` entries name `data_catalog.py`, `data_sources.py` and
  `data_tools.py`, but only `deerflow_bridge/data_mcp.py` exists in `git status` (untracked) at
  23:28 CST. Not verified: whether `_sync_deerflow_bridge_if_stale` would fail on the missing
  modules if a run started now.

---

## 9. Map cross-check

- Every cited claim from orch-a…orch-h, api-core, frontend, sim-runtime and linear-2 that this
  trace depends on was re-read and holds at HEAD. That includes the orch-h verifier corrections
  (`current_stage` also set by resume(force)/continue/fork; the outage breaker seen in RUN only
  on round change) and the orch-e corrections (only start/resume/continue/fork spawn `_run`).
- **Anchor drift versus disk:** all map line numbers for `pipeline_orchestrator.py` after
  HEAD:1357 and for `config.py` after HEAD:1467 no longer match the on-disk working tree (§0
  offsets). This is caused by concurrent uncommitted edits, not by map errors.
- None of the maps records F1, F2, F3, F6, F7, F8 or F9.
