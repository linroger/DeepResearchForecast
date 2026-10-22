# Trace: failure-recovery — failure, cancellation, resume and recovery paths

Cross-cutting trace over the whole DRF pipeline (branch `main`, studied 2026-10-11, read-only).
It maps every failure and recovery path. For each one it gives the trigger, where it is detected
(file:line), the state transition, what is kept and what is thrown away, and what the UI shows.

## Anchor legend and a caveat about line numbers

| Prefix | File (repo-relative) |
|---|---|
| `po:` | `backend/app/services/pipeline_orchestrator.py` (**git HEAD `c20ec60`, 13,492 lines**, see caveat) |
| `ra:` | `backend/app/services/report_agent.py` |
| `sr:` | `backend/app/services/simulation_runner.py` |
| `sm:` | `backend/app/services/simulation_manager.py` |
| `api-r:` | `backend/app/api/research.py` |
| `api-rep:` | `backend/app/api/report.py` |
| `cfg:` | `backend/app/config.py` |
| `init:` | `backend/app/__init__.py` |
| `dr:` | `deerflow_bridge/deerflow_research.py` |
| `lr:` | `deerflow_bridge/linear_research.py` |
| `rps:` | `backend/scripts/run_parallel_simulation.py` |
| `salv:` | `scripts/salvage_orphaned_pipelines.py` |
| `RV:` | `frontend/src/views/ResearchView.vue` |

**Line-number caveat (observed during this study).** Another session edited
`backend/app/services/pipeline_orchestrator.py` while this trace was being written. It left an
uncommitted change at working-tree lines 1356-1365 that adds 4 lines (four new bridge modules in
`_DEPLOYED_BRIDGE_MODULES`; check with `git diff HEAD -- backend/app/services/pipeline_orchestrator.py`).
Every `po:` anchor here is checked against `git show HEAD:backend/app/services/pipeline_orchestrator.py`.
Those numbers match all the slice maps. In the current working tree, any `po:` anchor at or above
about 1365 is **+4**. The diff touches only a comment and a tuple literal, so no behavior described
here changes. The other files cited here have no working-tree changes (`git status`).

---

## 0. State model (what "failed / cancelled / running" mean)

| Item | Values / meaning | Anchor |
|---|---|---|
| Pipeline `status` | `pending/running/completed/failed/cancelled`. The comment lists only four; `cancelled` is also written. | po:689 (comment); written at po:1016, po:8008, po:13361 |
| Stage `status` | `pending/running/completed/failed/cancelled` | po:662; `_reset_stage_attempt` po:3839-3854 |
| Control signals | `PipelineCancelled(BaseException)`, `ProviderOutageHalt(BaseException)`. Both deliberately pass through every `except Exception` layer. | po:248-255, po:258-271 |
| Writers of `uploads/pipelines/<id>/pipeline_state.json` | `PipelineManager.save` (atomic, per-id lock), `mark_failed`, `mark_salvaged_completed`, `touch_heartbeat` (fsync off), plus the offline salvage script | po:944-956, po:992-1021, po:1023-1075, po:1077-1099, salv:199 |
| In-process registries | `_threads`, `_cancel_events`, `_lifecycle_lock`. They are process-local, so "running" on disk does **not** imply a live thread. | po:7530-7536 |
| Task store | `TaskManager` is an in-memory singleton. Task ids do not survive a restart, so `complete_task`/`fail_task` on old ids are no-ops. | `backend/app/models/task.py:54-71` (per orch-e map; not re-read here) |

---

## 1. Master table

| # | Path | Trigger | Detection (file:line) | State transition | Preserved / discarded | UI sees |
|---|---|---|---|---|---|---|
| 1 | User cancel, live thread | `POST /api/research/<id>/cancel` | api-r:132-144 → `cancel` po:7982-8005 sets the Event (po:8003). The Event is checked at the stage updater (po:8961-8963), the RUN poll loop (po:13007-13013), the seed loops (po:8568-8570, po:8823-8828) and the research cancel watcher (po:2461-2473 → po:2577-2578). | `status=cancelled`. The current stage becomes `cancelled` **unless** it is already completed or at 100% (XRUN-15). | Everything on disk is kept. The research process group is SIGKILLed. The OASIS sim is stopped (`stop_simulation`) before the raise. | Polling sees terminal `cancelled` and stops (RV:728-731). Resume button appears (RV:554). History lists it as "Failed" (`frontend/src/components/research/PipelineHistory.vue:270-271`). |
| 2 | User cancel, orphan (no local thread) | same route | po:8007-8016 | `mark_failed(..., status="cancelled")` (po:8008), with XRUN-15 stage protection (po:1011-1017) | Disk kept. **No liveness check and no process kill** (contrast delete, po:8071-8078). | Same as #1 |
| 3 | Provider-outage breaker (DEFECT-1) | N consecutive provider-level `LLMClient.chat` failures in this process (default N=10) | Probe wraps `chat` (po:597-644). It classifies the failure (po:399-443) and trips (po:469-488). The halt is raised **only** at the stage updater (po:8967-8969). | `_halt_for_provider_outage`: `status=failed`, `options.provider_outage_halt={snapshot, provider, halted_at, halted_stage, resume}`, current stage `failed` (po:9766-9794) | Everything kept. Calls after the trip fail fast without any provider call (po:626-627). | Shows as a plain `failed` with `state.error` = halt message (RV:736-738). **`provider_outage_halt` is not read by the frontend** (grep of `frontend/src` finds no reference). |
| 4 | Generic stage exception | Any `Exception` escaping a stage | `_run` handler po:13381-13392 | `status=failed`, `error=str(e)`, `_fail_stage(current_stage)` (po:9757-9764). It sets the stage `failed` **even if that stage was already completed**. | Disk kept. Telemetry flushed (po:9764). | `failed` and the failed stage's error (RV:736-738) |
| 5 | S1 deliverable health gate | Broken report at DONE | `_enforce_pipeline_health` po:9445-9497, raise po:9493-9494, called at po:13345 | Through #4: `status=failed`. REPORT (the `current_stage`) is flipped from completed to `failed`. `options.pipeline_health.status=failed`. | Report dir kept. A resume rejects it and mints a new report (po:13211-13222). | `failed` + error text. **`pipeline_health` is never rendered** (no frontend reference). |
| 6 | RUN stall | No round advance for `PIPELINE_RUN_STALL_S` (1800 s) | Inline: po:13055-13060. Independent disk watchdog: po:9113-9159, which calls `stop_simulation` (po:9151), so the poll loop then sees `STOPPED` (po:13051-13052). | Through #4 → `failed` at RUN. Sim telemetry booked once (po:13062-13068). | Sim dir, actions and DB kept | `failed` |
| 7 | Research watchdog timeout | Depth budget exceeded (900/7200/21600 s ×1.5) | Timer po:2452-2459; ladder po:2583-2617 | A fresh report is **salvaged**: `returncode=0`, optional `--extract-only` child (po:2599-2612). Otherwise `RuntimeError` → #4. | Partial report kept. A stale artifact is never salvaged (po:2229-2240). | Progress message "研究超时，但报告已生成——打捞继续" (po:2592-2594) or `failed` |
| 8 | Backend crash/restart: pipelines | Process dies; state left `running` | Boot: `init:139-141` → `reconcile_orphans` po:7637-7735 (port probe po:7656-7668, liveness po:7808-7840) | Dead with a complete report → `completed` + health `degraded` (po:7689-7715). Dead otherwise → `failed` (po:7716-7731). Alive or fresh heartbeat → **left `running`** (po:7679-7684). | Research PIDs killed after identity check (po:7842-7867). Disk kept. | Polling resumes from localStorage. A run still `running` but with a dead owner shows a "process down" chip (`frontend/src/utils/runVitals.js:94-96`, `frontend/src/components/research/RunVitals.vue:130`). |
| 9 | Backend restart: simulations | `run_state.json` RUNNING/STARTING/STOPPING/PAUSED with no local Popen | `init:127-131` → `SimulationRunner.reconcile_orphans` sr:1519-1566 | run_state `FAILED`, `state.json` `failed`, env stopped (sr:1553-1560) | Kill attempted; its result is ignored (sr:1553). Logs and DB kept. | Seen through the pipeline RUN stage on resume |
| 10 | Shutdown signal (SIGINT/TERM/HUP) / atexit | Process exit | Pipeline handler po:7870-7917 chains to SimulationRunner's handler (registered first, init:129 vs init:141) | Research groups SIGTERMed (po:2105-2111). Sims STOPPING→STOPPED with "服务器关闭，模拟被终止" (sr:2391-2494, sr:2437). **Pipeline state not touched** (stays `running`). | Disk kept | Next boot → #8 |
| 11 | Boot salvage (W9-1) | Orphan whose REPORT stage is completed and whose report files exist | po:7689-7715 using `_orphan_completed_report` po:7737-7770 | `mark_salvaged_completed`: `completed`, `pipeline_health` degraded, `ensemble_done=True` (po:1023-1075) | Ensemble skipped for good | `completed`. Degradation is invisible in the UI (see #5). |
| 12 | Offline salvage script | Operator runs `scripts/salvage_orphaned_pipelines.py --apply` | salv:147-172 (scan), salv:76-104 (criteria) | `failed` (or `cancelled` with `--include-cancelled`) → `completed(degraded)` (salv:109-143) | Same fields as #11 | `completed` |
| 13 | Resume | `POST /api/research/<id>/resume` (UI shows it only for failed/cancelled) | api-r:147-182 → `resume` po:8106-8211 | `status=running`, same id, new task id; current failed/cancelled stage reset (po:8167-8171) | Completed stages reused behind integrity gates inside `_run` (section 3) | `running`; polling restarts (RV:577-600) |
| 14 | Force resume | `resume(force=True)` on a `completed` run whose health is degraded/failed | po:8143-8165 | REPORT reset, `force_report_regen` set, regenerated with a new id | Research/graph/sim reused. **No UI path**: `resumePipeline` sends no body (`frontend/src/api/research.js:53-58`). | — |
| 15 | Research checkpoint resume (legacy) / v3 phase resume | Re-entry into RESEARCH | po:11995-12019 (lineage) → `--resume` (po:2388-2403) → dr:16748-16780. v3: lr:973-995 | — | Legacy: LangGraph thread and completed passes. v3: `handoff/v3/` work dir when identity matches, otherwise archived to `v3.stale-*`. | Progress "检测到研究断点，续跑…" (po:12019) |
| 16 | Synthesis-only recovery (legacy multi-lane) | Contract invalid or fails quality, or root report missing while `evidence_synthesis_manifest.json` exists | po:11919-11959 → po:10841-11056 | Up to 2 attempts. Pass → promote. Fail → `RuntimeError` → #4. | Sealed lane packs reused. Forensics in `handoff/research_attempts/` (po:3078-3137). | `[仅综合恢复]` progress prefix (po:10911-10915) |
| 17 | Research budget epochs | Each research task id opens one ledger epoch | po:1815-1923, cap po:1851-1856 (default 3, cfg:543-544) | The 4th task id → `RuntimeError` → #4 | Earlier epochs archived | `failed` with "research budget epoch limit reached" |
| 18 | Report retries | Section exception / outage / broken audit | ra:10138-10183 (retry), ra:11395-11408 and ra:11459-11464 (outage abort), ra:11061-11111 (resurrection), po:13250-13261 (preflight), ra:8423-8435 (final audit) | Section → placeholder. Report → `FAILED` (ra:11684-11700). Orchestrator raises (po:13325-13327). | Failed report dir kept. Resume always mints a new `report_id` (po:13265-13268). | `failed` |
| 19 | Translation lock recovery | Restart during an on-demand translation | ra:12162-12335 (`interrupted`), api-r:606-615 (dossier) | Durable status read as `interrupted`; a retry is allowed | Published variant kept on failed regeneration (`keep_existing_on_failure`, ra:12403, ra:7637-7644) | "Retry translation" (`frontend/src/components/research/DossierViewer.vue:486-501`; `frontend/src/utils/reportLanguages.js:156-165`) |
| 20 | Simulation reuse | Resume reaching PREPARE/RUN | po:12734-12767, po:12831-12853, po:12941-12972. Runner-level `SIM_RESUME` sr:761-786. | Reuse, or a new sim / full rerun | See section 6 | Stage message "复用已有模拟结果…" (po:12971) |
| 21 | Seed ensemble failures | `N_FORECAST_SEEDS>1` only (default 1, cfg:303) | po:8529-8760 | A seed failure is skipped. Cancel → pipeline `cancelled` while REPORT stays completed. | `ensemble_checkpoint.json` reused on resume (po:8587-8654) | — |
| 22 | Delete / clean | `DELETE /<id>`, `POST /clean` | po:8042-8086, po:8088-8104 | Orphan `running` → marked `cancelled`, then `rmtree` | Report and sim dirs **not** deleted | History list refresh |

---

## 2. Lifecycle signals in detail

### 2.1 Cancellation (`PipelineCancelled`)

- **Entry.** `cancel()` holds `_lifecycle_lock` and returns `not_found` / `not_running` / `cancelling` /
  `cancelled` (po:7982-8016). The route (api-r:132-144) maps them to 404/409/200 (api-r:136-142).
- **Cancel points.**
  1. Stage updater, on every progress callback (po:8961-8963).
  2. Research subprocess: the watcher thread polls the Event every 1 s and SIGKILLs the process group
     (po:2461-2473). The runner then raises `PipelineCancelled("深度研究已取消")` (po:2577-2578).
     The `run` wrapper bills the tokens spent so far as `cancelled` (po:2134-2136).
  3. RUN poll loop, every 5 s: `stop_simulation` first, then raise (po:13007-13013).
  4. Seed ensemble (po:8568-8570, po:8678-8680, po:8823-8828).
  5. Synthesis recovery and the global-synthesis attempts keep the progress log as `cancelled`,
     remove the staging dir and re-raise (po:10967-10976; po:11521).
- **Latency gaps (verified).**
  - Report sections run concurrently by default (`REPORT_SECTION_CONCURRENCY=6`, cfg:1566).
    Concurrent body and tail sections get `progress_callback=_noop` (ra:10085-10089, ra:10108-10111).
    The first real `progress_callback` after that runs in the serial bookkeeping loop (ra:11318-11323).
    So a cancel is only noticed **after every concurrent section has finished**.
  - Seed lanes pass no progress callback to `prepare_simulation` or `generate_report` (orch-e map,
    po:8790-8799, po:8888).
- **Handler.** po:13359-13376 sets `status=cancelled` and `error`. It marks the current stage
  `cancelled` unless it is completed or at ≥100 (po:13363-13368), saves, and then calls
  `task_manager.fail_task`. The task store cannot tell cancel from failure.
- **Report side effect.** `generate_report` catches only `Exception` (ra:11684). A cancel or outage
  halt raised from its progress callback therefore leaves `meta.json` with the last saved status,
  which is `planning`. That status is saved at ra:11267 and is not rewritten until ra:11664.
  The API's draft gate treats such a report as in-progress and then stale after 30 minutes of
  inactivity (api-rep:96, api-rep:105, api-rep:180-189).

### 2.2 Provider-outage breaker (`ProviderOutageHalt`, DEFECT-1)

- **Registration.** One fresh breaker per `_run` attempt (po:11891-11892 → po:530-539). The
  threshold comes from `LLM_OUTAGE_HALT_CONSECUTIVE` (default 10, cfg:69; resolver po:379-396).
  A value ≤0 disables the breaker.
- **Probe.** It monkeypatches `LLMClient.chat` process-wide (po:597-644). Fallback clients pass
  straight through (po:621-622). A tripped breaker raises `RuntimeError("LLM_OUTAGE_HALT…")` with no
  provider call (po:626-627). Success resets the count unless the breaker has tripped (po:464-467).
- **Classification.** Counted kinds are auth, circuit-breaker, quota and connection. Cancel, budget,
  empty text and the breaker's own fast-fail text are excluded (po:399-443).
- **Scope gaps (verified).**
  - Research and simulation subprocesses are not instrumented (comment po:360-362). Only three
    orchestrator-boundary feeds exist: `_note_provider_stage_failure` at po:10982 (synthesis
    recovery), po:11258 (parallel tracks) and po:11548 (global synthesis).
  - The **default single-lane v3 research** call (po:12047-12075) feeds nothing. A provider outage
    during RESEARCH therefore ends through the generic handler (#4), not as an outage halt.
  - `chat_with_tools` bypasses the probe (orch-a map Surprise 11).
- **Halt point.** Only the stage updater raises `ProviderOutageHalt` (po:8967-8969). Calls made
  before the next progress callback fail fast and get swallowed by stage-local
  `except Exception` layers. In the report stage those failures turn into section placeholders.
- **Report preflight.** A tripped breaker makes the REPORT preflight's `chat` raise. That error is
  wrapped as a generic `RuntimeError` (po:13250-13261), so the run fails through #4 **without**
  `provider_outage_halt` (orch-h Surprise 15, confirmed).
- **Handler.** po:13377-13380 → po:9766-9794 (`status=failed`, evidence block, stage failed, save,
  `fail_task`). The `finally` clears the breaker (po:13488), so a resume starts at zero.
- **Recovery.** A plain `resume` (failed is accepted). `resume` does **not** clear
  `options.provider_outage_halt` (po:8179-8183), so the evidence from the previous attempt stays in
  `options` after a successful resume.

### 2.3 Generic failure path and stage attribution

- po:13381-13392 calls `_fail_stage(state, state.current_stage, …)`. It does **not** guard a stage
  that is already completed, unlike the cancel handler. `current_stage` changes only inside the
  updater (po:8979), so a failure raised before a stage's first `upd(...)` is charged to the
  *previous* stage.
- Verified instance: the REPORT rebuild path runs the LLM preflight before its first
  `upd(5, …)` (po:13250-13269). A preflight failure therefore flips the completed **RUN** stage to
  `failed`, and `resume` then resets RUN (po:8167-8171). RUN is rescued only by the disk-reuse
  probe (section 6) (orch-h Surprise 1, confirmed).
- `KeyboardInterrupt` / `SystemExit` have no handler. Status stays `running` until #8
  (po:13359-13392; `finally` po:13393).

### 2.4 Heartbeat, ETA and staleness

- **`_start_heartbeat`** (po:10331-10370) pins `owner_pid`, `owner_boot_id` (per-process uuid,
  po:300) and `heartbeat_at` in memory. The thread `pipeline-hb-<id>` then calls `touch_heartbeat`
  every `PIPELINE_HEARTBEAT_INTERVAL_S` (30 s, cfg:458), with `fsync=False`. The thread exits once
  the status is not `running` (po:1077-1099, po:10354-10358). The first touch comes only after one
  full interval (`while not stop.wait(interval)`, po:10354), even though the comment says it beats
  immediately (po:10353).
- **Updater refresh.** The stage updater also refreshes `heartbeat_at` and `last_progress_at`
  (po:8984-8987). The `finally` stops the thread (po:13395-13396).
- **Status API `live` block** (api-r:306-336):
  - `estimate_eta` (po:10244-10300) sets `stale` when there has been no progress for
    `PIPELINE_STALE_S` (300 s, cfg:461).
  - `heartbeat_status` (po:10302-10327) adds `owner_alive` (`os.kill(pid,0)`) and
    `heartbeat_age_s`.
- **UI liveness** (`frontend/src/utils/runVitals.js:94-102`): `owner_alive===false` → `dead`;
  `stale` → `stale`; heartbeat < 90 s (`runVitals.js:17`) → `ok`.

---

## 3. Resume semantics, stage by stage

There is no separate resume code path. `start`, `resume`, `continue_to_full` and `fork` all spawn
`_run` (po:7970-7978, po:8202-8210, po:8267-8275, po:8344-8348).

**Before `_run`, `resume` does the following** (po:8106-8211):
- It refuses a live thread (po:8122-8124) and a newer schema (po:8129-8131, 409).
- It reclaims a dead `running` orphan in place (`_orphan_is_dead` → `mark_failed(cancelled)`,
  po:8132-8142).
- It refuses `completed` unless `force` is set and health is degraded/failed (po:8143-8151).
- It resets only the current stage, and only if that stage is failed/cancelled (po:8167-8171).
- It mints a new task, sets `running`, clears `error` and `research_pid`, and records `resumed_at`
  and `resume_count++` (po:8173-8183).
- It pins a safe policy for pipelines admitted before WP1 (po:8188-8199).
- It does **not** clear `pipeline_health`, `provider_outage_halt`, `ensemble_done` or
  `resumed_stage_validation`.

| Stage | Reuse gate (in `_run`) | When rebuilt | Ids minted on rebuild | Anchor |
|---|---|---|---|---|
| RESEARCH | Root report ≥400 chars **and** either (contract manifest valid + judge quality) or (stage bit completed + `_validate_reuse`) | Otherwise research reruns: synthesis-only recovery when an evidence manifest exists, else a full research launch with checkpoint lineage | none (same handoff) | po:11902-11959, po:11960-12078 |
| ONTOLOGY | `project.ontology` truthy. **No integrity check.** | LLM ontology rerun (project reused) | none | po:12312-12314 (orch-h map) |
| GRAPH | stage bit + `graph_id` + `_reuse_ok` + v1 seed readback + entity count >0 | `create_graph` again. The old graph is left for GC. | new `graph_id` | po:12392-12455 (orch-h map) |
| PREPARE | stage bit + sim exists + `_reuse_ok` + config seal (`validate_prepared_simulation_config`) | `create_simulation` again. The old sim dir is orphaned. | new `simulation_id` | po:12734-12782; sm:1352 |
| RUN | prepare reused + RUN bit + `_run_reuse_ready` + `_reuse_ok`, **or** disk reuse (`_completed_sim_reusable`) | `start_simulation` on the same sim id. Logs rotated to `.prev` unless `SIM_RESUME`. | none | po:12941-12972, po:12831-12853; sr:761-786 |
| REPORT | Existing report (`state.report_id`, else newest by sim) with status `!= FAILED`, health not `failed`, not forced, `_reuse_ok` | Preflight, then `_clear_report_attempt_artifacts`, then generate | **always** a new `report_id` | po:13186-13328 |
| Ensemble | `n_seeds>1` and not `ensemble_done` | Checkpointed seeds reused | new seed sim/report ids | po:8546-8549, po:8643-8654 |
| DONE | S1 health gate | — | — | po:13345-13348 |

**Research-specific resume detail.**
- **Legacy lineage.** `_validated_research_checkpoint_lineage` (po:2974-3039) requires all of:
  `research_checkpoint.json` v2, matching question hash/depth/run id/lane `outer-track-1`, an
  `attempt_id` in this pipeline's budget-epoch allowlist, and a recomputed checkpoint identity.
  It then passes `--resume`. The runner overrides `RESEARCH_BUDGET_EPOCH=resume_attempt_id` and sets
  `RESEARCH_CHECKPOINT_ID` (po:2388-2403). The bridge re-plans with `plan_research_resume` (dr:1011)
  and reuses the LangGraph thread plus completed passes (dr:16748-16780). Any mismatch falls back
  to a full restart, logged in meta (dr:16777-16779).
- **v3 (default engine).** The bridge ignores the legacy checkpoint under v3 (dr:16741-16746). v3
  resumes from `handoff/v3/state.json` **whenever** the identity matches: question sha, depth,
  model, language and engine version (lr:3970-3975). `--resume` is not required.
  - A mismatched or unreadable work dir is archived to `v3.stale-<utc>` (lr:973-995).
  - Phases skip on `is_done` (lr:920, used at lr:4204, lr:4417, lr:4809, lr:5167).
  - `finalize` has no done-check and always rewrites `sources.json` then `research_report.md`
    (lr:5526-5545).
  - The v3 failure boundary always leaves `meta.status` terminal and returns 2 (lr:6326-6379).
  - On interrupts it calls `engine.cancel()` and re-raises (lr:6357-6364).
- **Single-lane reuse is length-plus-bit.** With no contract manifest (the v3/single-lane norm), a
  report without a completed stage bit is never reused (po:11950-11954). The resume relaunches the
  child, and the child's own v3 state makes that cheap.
- **Budget epoch cap.** A new task id opens a new epoch, so each resume that reaches fresh research
  consumes one. A 4th epoch raises (po:1851-1856). The same task id reuses its row (po:1840-1849).

---

## 4. Orphans: boot reconciliation, salvage, shutdown

### 4.1 Pipeline orphans (`PipelineOrchestrator.reconcile_orphans`, po:7637-7735)

1. **Port probe.** If `127.0.0.1:$FLASK_PORT` already accepts a connection, the whole reclaim and
   graph GC are skipped (po:7656-7668; `PIPELINE_RECLAIM_PORT_PROBE`, cfg:495).
2. **Candidates.** Every `running` pipeline not in `_threads` (po:7672-7677). One malformed
   `schema_version` raises out of `load` (`int()` sits outside the try, po:1151) and aborts the
   whole loop (orch-a verifier).
3. **Liveness** (`_orphan_is_dead`, po:7808-7840). The record is dead if any of these holds:
   - it is unreadable or incompatible (po:7818-7821);
   - its owner boot id is this process (po:7828-7829);
   - the owner pid is alive but the heartbeat is stale (po:7831-7833);
   - the owner pid is gone and the heartbeat is stale (or missing, falling back to `updated_at`)
     (po:7837-7840).

   The window is `PIPELINE_HEARTBEAT_STALE_S=120` (cfg:459).
4. **Salvage** (W9-1, po:7689-7715). This applies only when `stages.report.status=="completed"`,
   `full_report.md` is non-empty, and `forecast.json` is a non-empty dict (po:7737-7770). It then:
   - calls `mark_salvaged_completed` (po:1023-1075);
   - kills the research PIDs;
   - calls `complete_task` on the stale task id, which is a no-op.

   The check does **not** run `_assess_report_health` and does not look at the final audit or at
   `meta.json` status.
5. **Fail.** `mark_failed(…"后端在运行中被中断…")` (po:7716-7717), then research PID kill
   (po:7721-7725). The PID kill requires a command line containing `deerflow_research.py` **and**
   the pipeline id (po:7860-7863).
6. **Graph GC** (po:7733). The whole method never blocks boot (po:7734-7735).

**Verified gap: a restart within 120 s of a crash leaves the pipeline `running` with nobody
driving it.**
- The owner pid is dead but the heartbeat is fresh, so `_orphan_is_dead` returns False
  (po:7837-7840).
- Boot reconciliation runs only once. There is no periodic reconciler.
- The **simulation** reconciler in the same boot is not heartbeat-aware. It marks that pipeline's
  sim `FAILED` immediately (sr:1519-1566).
- The UI keeps polling a `running` run and shows a "process down" chip
  (`frontend/src/utils/runVitals.js:96`). The Resume button only appears for `failed`/`cancelled`
  (RV:554). The only UI exit is **Cancel**, which marks the orphan cancelled (po:8007-8016), then
  Resume. The `resume` API alone also works once the heartbeat goes stale (po:8132-8142).

### 4.2 Simulation orphans (`SimulationRunner.reconcile_orphans`, sr:1519-1566)

- It has its own port probe (`SIMULATION_RECLAIM_PORT_PROBE`, cfg:498-500; sr:1531-1543).
- Any active status not in `_processes` gets the following: kill attempt (result discarded),
  `FAILED`, `state.json` failed, env stopped (sr:1546-1560).
- `STOPPED` runs left by graceful shutdown are untouched.

### 4.3 Shutdown cleanup

- `init:129` registers SimulationRunner's handler first, and `init:141` registers the pipeline's.
  The pipeline handler therefore captures SimulationRunner's as `prev`.
- On a signal, the pipeline handler SIGTERMs live research groups (po:2105-2111, po:7898-7900),
  then chains to SimulationRunner's handler (po:7901-7902).
- SimulationRunner's handler stops sims to `STOPPED` (sr:2391-2494). Per the sim-runtime verifier,
  it always resets to `SIG_DFL` and re-sends the signal (sr:2554-2558).
- `atexit` also covers normal exit (po:7888).
- Pipeline state is never touched (po:7869-7917), so recovery is #8 at the next boot.

### 4.4 Offline salvage script (`scripts/salvage_orphaned_pipelines.py`)

- **Default and rule.** The default is a dry run. `--apply` rewrites the state (salv:175-205). The
  rule mirrors `_orphan_completed_report`: report stage completed, non-empty `full_report.md`,
  non-empty `forecast.json` dict (salv:76-104). It also adds a path-escape guard on `report_id`
  (salv:86-87).
- **Field mirror.** `salvage_state` mirrors `mark_salvaged_completed` field by field (salv:109-143
  vs po:1036-1072).
- **Race guard.** It only re-reads the state and skips anything that turned `running` (salv:195-198).
- **Differences from the in-process path (verified):**
  - **No schema check.** The script reads raw JSON (salv:156, salv:191) and writes it back
    (salv:199). `mark_salvaged_completed` refuses the incompatible sentinel (po:1034).
  - **No per-pipeline lock.** `PipelineManager._state_lock` is process-local anyway (po:933-942).
  - **Timestamp format.** It uses `…Z` (salv:44-45) instead of `isoformat()` (po:293-294).
  - **`--include-cancelled`** can turn a user-cancelled run into `completed`
    (salv:150, salv:222-226).
- **Exposure.** Like boot salvage, the script never checks deliverable health. A run failed by the
  S1 gate is **not** eligible, though: the generic handler flips REPORT to `failed` (po:13385-13386),
  which fails the `status=="completed"` test (salv:88-90).

---

## 5. Research failure and recovery (Stage 0)

| Failure | Detection | Result | Recovery |
|---|---|---|---|
| Bridge/skill/overlay sync unverifiable | po:2211 → po:1441-1745 | `RuntimeError` before spawn (fail-closed set). Some generic sync errors only warn (orch-a Surprise 2). | Fix `deerflow_bridge/`, then resume |
| Pre-launch budget saturated | po:12038-12046 | `RuntimeError` → #4 | Resume (new task → new epoch, cap 3) |
| User cancel | po:2461-2473, po:2577-2578 | `PipelineCancelled`. Spend flushed (po:2134-2136). | Resume |
| Watchdog, fresh artifact | po:2583-2612 | Treated as success. The `--extract-only` child runs only if `actors.json` is absent. Bounded by `RESEARCH_EXTRACT_ONLY_TIMEOUT` (600 s; po:3729-3808). Ignores cancel; tokens not metered (orch-b Surprise 10). | — |
| Watchdog, no fresh artifact | po:2613-2617 | `RuntimeError` → #4 | Resume (legacy checkpoint lineage / v3 state) |
| stdout EOF but group lingers >30 s (W9-4) | po:2534-2565 | Salvaged only if the artifacts survived. Otherwise raises. | — |
| Non-zero exit / missing / short / error-marker report | po:2618-2639 | `RuntimeError` → #4 | Resume |
| Failed attempt spend | po:2137-2140 → po:2035-2096 | Billed once to `stage=research` | — |
| Contract finalize inconsistency | po:3607-3726 | `RuntimeError` → #4. Promotion rollback is incomplete for staging-phase failures and `BaseException` (orch-b Surprises 6-7). | Resume |
| v1 actor reception (legacy-pinned only) | po:12274-12286 | `RuntimeError` → #4 | Upstream redo |
| Synthesis-only recovery | po:10841-11056 | ≤2 attempts. Stops early on provider-blocked markers (po:10980, po:10995-11000). Failure is recorded in `options.synthesis_recovery`, then raises (po:11003-11022). | Resume. Reuses the failed epoch if the ledger is not exhausted (po:1926-1966). |

`state.research_pid` is persisted on spawn (po:11966-11968) and cleared only on success
(po:12076-12078). Every failure path keeps it on disk until `resume` clears it (po:8181). The
orphan killer's identity check stops a reused PID from being killed (po:7860-7863).

---

## 6. Simulation reuse and resume (PREPARE / RUN)

1. **PREPARE reuse** (po:12734-12767). Needs the stage bit, a loadable sim, `_reuse_ok(PREPARE)`
   (manifest hashes) and the config seal (`validate_prepared_simulation_config`, sm:1352). Any miss
   → `create_simulation`, which mints a **new `simulation_id`** (po:12775-12776) and abandons the
   old sim dir.
2. **Disk-reuse probe** (DEFECT-1, `SIM_RESUME_REUSE_COMPLETED` default on, cfg:596). This runs when
   PREPARE is reused and the RUN bit is not completed, and it runs **before** any config mutation
   (po:12831-12853). `_completed_sim_reusable` (po:9976-10057) requires all of:
   - the same sim id;
   - no live process;
   - `simulation_end` evidence for each enabled platform;
   - a valid run_summary, if present;
   - the config seal;
   - runtime attestation sha equality.
3. **RUN reuse** (po:12941-12972). Recorded reasons when reuse is refused:
   `run_rebuilt_prepare_identity_changed`, `run_rebuilt_simulation_state_mismatch`,
   `run_rebuilt_manifest_mismatch`. Disk reuse promotes the stage to done with
   `run_reused_completed_simulation` (po:12963-12969).
4. **Fresh RUN.** `start_simulation(platform="parallel")` passes **no** `resume` argument
   (po:12989), so the runner decides by itself (sr:761-786):
   - With `SIM_RESUME` (default **false**, cfg:590), it resumes only if the previous state is not
     COMPLETED **and** a checkpoint whose config hash matches exists (sr:1356-1385). Otherwise it
     rotates `actions.jsonl` and derived artifacts to `.prev` (sr:1310-1337) and reruns from round 0.
   - The child writes per-round checkpoints whenever `SIM_CHECKPOINT` is on (default true,
     cfg:600; rps:3753-3757). It also re-checks the config hash on `--resume` (rps:4798-4805,
     rps:5351-5358).
5. **Completion evidence gate** (po:13130-13136 → po:10059-10084). Fresh and reused runs alike must
   show `simulation_end` and a published run_summary. Otherwise RUN fails.
6. **After a backend restart**, the boot sim reconciler has marked the run `FAILED` (sr:1553-1560).
   Disk reuse then fails on missing `simulation_end`, so with defaults the simulation **reruns
   fully**. A graceful shutdown leaves `STOPPED`, which behaves the same way.

---

## 7. Report retries and health enforcement

**Inside `ReportAgent.generate_report`:**
- **Section retry** (RPT-2). `REPORT_SECTION_RETRY_MAX=2` and `REPORT_SECTION_RETRY_BACKOFF_S=8`
  (cfg:631-632). The backoff is `min(8*attempt, 60)` s, then re-raise (ra:10138-10183). The caller
  writes `SECTION_FAILURE_PLACEHOLDER` (ra:1053; concurrent path ra:10085-10091).
- **Outage abort** (`REPORT_ABORT_ON_LLM_OUTAGE`, default true, cfg:630):
  - degraded outline + the first two sections failed → `RuntimeError` (ra:11402-11408);
  - every section a placeholder → `RuntimeError` before `forecast.json` is written (ra:11459-11464).
- **Resurrection** (SESSIONB-1). One more full retry per placeholder section before assembly
  (ra:11061-11111), gated by `getattr(Config,"REPORT_RESURRECT_FAILED_SECTIONS",True)` (ra:11471).
  That knob is **not defined** in `backend/app/config.py` or `.env.example` (grep), so it is a
  ghost knob that is always on.
- **Final read-only audit.** Any failure is re-raised as `RuntimeError` (ra:8423-8435; called at
  ra:11578).
- **Failure handling.** All of the above land in `except Exception` (ra:11684-11700): status
  `FAILED`, `meta.json` saved, progress `failed`.

**In the orchestrator:**
- **LLM preflight** (`REPORT_LLM_PREFLIGHT`, cfg:503): one `ping` (po:13250-13261).
- **Report status FAILED** → `RuntimeError` (po:13325-13327).
- **No in-run retry of the whole report.** Recovery is resume. A new `report_id` is minted every
  time (po:13265-13268), so failed report dirs accumulate.
- **Reuse guard ORCH-1.** A report whose health is `failed` is not reused
  (`report_rebuilt_broken_deliverable`, po:13211-13222). The guard runs only with
  `PIPELINE_HEALTH_GATE` (cfg:167), and an assessment exception counts as `ok` (po:13216-13217).
- **S1 gate** (po:9445-9497). It hard-fails when any of these holds:
  - no `report_id`;
  - every section is a placeholder;
  - no forecast;
  - `full_report.md` under 2,000 bytes;
  - a final-audit hard issue.

  Degraded findings only write `options.pipeline_health`. An exception inside the assessment is
  swallowed and the run completes (po:9490-9492).

**Suspected bug (verified at code level, not run): a run interrupted after the final audit can
complete with an unpublishable report.**
1. `meta.json` holds `status:"planning"` from ra:11267 until ra:11664. The in-memory status
   changes at ra:11272 and ra:11490 but is not saved.
2. Between the final audit (ra:11578) and that save, the auto-translation
   `_generate_bilingual_report` runs (ra:11584-11588). It is a multi-minute LLM job.
3. A crash or kill in that window leaves `final_audit.json` hard-passed and hash-bound, with
   `meta.json` still at `planning`. The REPORT stage is not completed, so boot salvage does not
   apply (po:7753-7755) and the run is marked `failed`.
4. On resume, REPORT reuse accepts any `status != FAILED` (po:13241). `_assess_report_health`
   never reads `meta.json` status (po:9161-9349: section files, forecast, final audit only).
5. The run therefore completes with a report that `publication_status` refuses, because it requires
   `status == completed` (ra:12457-12458).

---

## 8. Translation lock recovery

**On-demand report variants (`POST /api/report/<id>/translations/<lang>`, api-rep:804-975):**
1. **Fast dedupe.** The route first checks the in-memory task store (`_active_translation_task`,
   api-rep:247-257, api-rep:849-851) and the durable status `generating` (api-rep:852-854) before
   taking the lease.
2. **Lease.** `_translation_generation_lease` = a per-(report, lang) `threading.Lock` plus an `fcntl`
   flock on `translation_status.<lang>.json.lock` (ra:12087-12104, ra:13017-13032). The OS releases
   the flock when the process dies, so a crash leaves no held lock behind.
3. **Reservation** (under the lease): it writes the durable status `pending` with
   `owner="pid:<getpid>"` and `task_id` (api-rep:856-895). The worker thread calls
   `generate_translation_variant` (ra:12353-12432), which takes the lease again and holds it for the
   whole generation (ra:12374).
4. **Heartbeat.** `_generate_bilingual_report._progress` rewrites `generating` and refreshes
   `heartbeat_at`/`updated_at` on every progress tick (ra:7515-7524 → ra:12041-12066). Earlier
   fields such as `owner` are kept, because the writer merges into the existing payload
   (ra:12050-12051).
5. **Stale and interrupted detection** in `translation_status` (ra:12257-12296):
   - `pid:<n>` owner → stale when the pid is gone (`_translation_owner_alive`, ra:12138-12150) or
     the age is over 3,600 s;
   - no pid owner (for example the in-pipeline call from `generate_report`) → stale when the age is
     over 900 s;
   - stale → `status:"interrupted"`. `can_generate` keeps its publishable-based value, so a retry is
     allowed. A non-stale record → `generating` with `can_generate=False`.
6. **Older bytes.** An audit that belongs to older primary bytes → `stale` (ra:12315-12317).
7. **Kept vs discarded.** A failed force regeneration keeps the published variant and writes the
   rejected audit beside it (`keep_existing_on_failure`, ra:12403, ra:7637-7644). A failed first
   generation removes stale variant files (ra:7552-7570, ra:7645-7647) and keeps only
   `full_report.<lang>.rejected.md` for diagnosis (ra:7648-7651).
8. **UI.**
   - An active status without a matching task becomes `interrupted/task_missing`
     (`frontend/src/utils/reportLanguages.js:156-165`).
   - "Translation task was interrupted after the service restarted"
     (`frontend/src/components/research/ForecastReport.vue:617-620`).

**Research dossier translation (`/api/research/<id>/dossier/translations/<lang>`, api-r:444-626):**
- **Dedupe** uses only a process-local `_research_translation_inflight` set (api-r:445-446,
  api-r:575-580). There is no cross-process lease. On restart the set is empty, so a POST re-runs
  immediately. The POST never consults a durable `generating` status (api-r:568-580).
- **GET** reports `interrupted` when the `pid:` owner is dead (api-r:606-615). There is **no age
  bound**, unlike ra:12277, so a reused pid would keep it `generating`.
- **Writes.** Status, audit and variant files use fixed `<path>.tmp` names (api-r:469-475,
  api-r:523-525, api-r:536-538). Two writers in different processes could race on the same tmp.
  This is suspected and low-likelihood.
- **UI.** "Retry translation" for failed/interrupted
  (`frontend/src/components/research/DossierViewer.vue:486-501`).

---

## 9. What the UI can and cannot see

| Signal | Backend field | Rendered? | Anchor |
|---|---|---|---|
| Terminal status | `status ∈ completed/failed/cancelled` | Yes. Polling stops and the failed-stage error is shown. | RV:728-741 |
| Cancel | POST cancel; the status flip comes from polling | Yes (confirm dialog) | RV:556-575 |
| Resume | POST resume (no body) | Yes, only for failed/cancelled | RV:554, RV:577-600; `frontend/src/api/research.js:53-58` |
| Force resume of a degraded completed run | `force:true` body | **No** | `frontend/src/api/research.js:53-58` |
| Liveness / staleness | `live.owner_alive`, `live.stale`, `live.heartbeat_age_s` | Yes (ok/stale/dead chip) | `frontend/src/utils/runVitals.js:94-102`; `frontend/src/components/research/RunVitals.vue:130` |
| Stage cancelled | `stages[*].status=cancelled` | Yes ("已取消") | `frontend/src/components/research/StageTimeline.vue:158-166` |
| `pipeline_health` (degraded/failed) | `options.pipeline_health` | **No** (no reference in `frontend/src`) | grep |
| `provider_outage_halt` | `options.provider_outage_halt` | **No** (only the `error` string) | grep; RV:736-738 |
| Salvaged run | `options.salvaged_orphan_at`, `ensemble_skipped` | **No**. Shown simply as `completed`. | grep |
| Report crashed mid-generation | `meta.status ∈ pending/planning/generating` with no activity for 30 min | Drafts withheld + stale reason | api-rep:96, api-rep:105, api-rep:152-189 |

---

## 10. Surprises and suspected defects (all verified against code; none run)

1. **Concurrent working-tree edit** to `pipeline_orchestrator.py` during the study shifted on-disk
   line numbers by +4 after about line 1360 (see the legend). The maps' `po:` anchors are HEAD-exact.
2. **A run interrupted after the final audit completes on resume with an unpublishable report**
   (section 7; ra:11267, ra:11578-11591, ra:11664; po:13241; ra:12457-12458).
3. **Cancel and outage halt are blind during concurrent report-section generation.** Callbacks are
   `_noop` (ra:10085-10111) and concurrency defaults to 6 (cfg:1566).
4. **A `running` pipeline whose owner died less than 120 s before restart is never reclaimed at
   boot.** The UI offers no Resume, only Cancel (po:7837-7840; RV:554). The sim reclaim in the same
   boot is not heartbeat-aware (sr:1519-1566).
5. **Single-lane (v3) research failures never feed the outage breaker** (po:10982, po:11258 and
   po:11548 are the only feeds; po:12047-12075 has none).
6. **The generic handler flips an already-completed current stage to `failed`** (po:13385-13386).
   Examples are the S1 gate after a completed REPORT and the preflight charged to RUN. The cancel
   handler protects completed stages (po:13367).
7. **`resume` clears neither `provider_outage_halt` nor `pipeline_health`** (po:8179-8183), and the
   frontend reads neither. Health-gate exceptions are swallowed, so a stale verdict can survive.
8. **`REPORT_RESURRECT_FAILED_SECTIONS` is a ghost knob** (ra:11471; absent from `cfg` and
   `.env.example`).
9. **The salvage script has no schema-version guard and can resurrect user-cancelled runs**
   (salv:156, salv:191, salv:199; salv:150). Neither salvage path checks deliverable health or `meta.json` status
   (po:7737-7770; salv:76-104).
10. **The research dossier translation has no cross-process lease and no age bound** on a live-pid
    `generating` (api-r:445-446, api-r:606-615 vs ra:12098-12104, ra:12277).
11. **Confirmed from maps and re-read:**
    - the disk watchdog keys on a non-existent `completed` field (po:9142);
    - `PIPELINE_RUN_STALL_S=0` is coerced to 1800 (po:12996-12998);
    - the report preflight bypasses the outage handler (po:13250-13261);
    - cancel/delete treat any thread-less `running` record as an orphan without a liveness check
      (po:8007-8016, po:8071-8078).
