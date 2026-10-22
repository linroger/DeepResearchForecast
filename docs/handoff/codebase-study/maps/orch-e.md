# orch-e — Orchestrator part E: PipelineOrchestrator lifecycle, scenario overlays, seed ensemble, stage updates, health checks

**Slice:** `backend/app/services/pipeline_orchestrator.py` lines 7527-9499 (branch `main`, on-disk checkout, studied 2026-10-11).

**Anchor legend.** `po.py:NNNN` means `backend/app/services/pipeline_orchestrator.py:NNNN`. Every other anchor uses its full repo-relative path. Line numbers come from the file as it is on disk; the file is 13,492 lines long.

---

## Purpose & position in the pipeline

`PipelineOrchestrator` (po.py:7527) is the process-level controller for the unified pipeline research → ontology → graph → prepare → run → report (po.py:87-102). This slice holds the class header and every piece of it except the main `_run` body (po.py:11883, mapped elsewhere) and the artifact/manifest helpers that follow at po.py:9500+. Specifically it holds:

1. **Lifecycle entry points**, called from the Flask API (`backend/app/api/research.py`) and from CLI scripts: `start` / `cancel` / `delete_pipeline` / `clean_terminal` / `resume` / `continue_to_full` / `fork`. Each one creates or mutates `uploads/pipelines/<id>/pipeline_state.json` and spawns a daemon thread that runs `_run`. [verifier: only `start`, `resume`, `continue_to_full` and `fork` spawn a `_run` thread (po.py:7970-7978, 8202-8210, 8267-8275, 8344-8348); `cancel` only sets the Event or marks the record cancelled (po.py:8000-8016), and `delete_pipeline`/`clean_terminal` delete records (po.py:8079, 8100)]
2. **Process lifecycle hooks**, called from `create_app()` (`backend/app/__init__.py:140-141`): `reconcile_orphans`, which reclaims or salvages `running` pipelines left behind by a dead process at boot, and `register_cleanup`, which kills DeerFlow research subprocess groups on SIGINT/SIGTERM/SIGHUP/atexit.
3. **Run telemetry incremental flush** (W9-3): `_init_telemetry_flush`, `_flush_run_telemetry`, `_maybe_flush_run_telemetry`.
4. **Scenario (what-if) overlay** application to a generated `simulation_config.json`: `apply_scenario_overlay_to_config`.
5. **Multi-seed ensemble** (NEXTSTEPS P0-3), which runs after the main report: `_maybe_run_seed_ensemble` and `_run_one_seed`, plus helpers `_infer_horizon_date`, `_agreement_to_confidence`, `_read_report_forecast` and `_pinned_safety`.
6. **Progress plumbing**: `_global_from_stage`, `_recompute_dynamic_bands` (T6.7), `_make_stage_updater` (the high-frequency cancel/outage checkpoint) and `_complete_stage`.
7. **RUN-stage support**: `_reconcile_completed_simulation_state`, `_sim_dir` and `_spawn_run_stall_watchdog` (an independent disk-reading watchdog).
8. **Deliverable health gate (S1)**: `_assess_report_health`, `_assess_run_health` and `_enforce_pipeline_health`. The gate runs after the report (and the optional ensemble), just before `_run` marks the pipeline `completed` (po.py:13345-13346).

---

## Walkthrough (source order)

### Class header — `PipelineOrchestrator` (po.py:7527-7536)
- Docstring: "串联 research → ontology → graph → prepare → run → report" (po.py:7528).
- **Class-level (process-wide) registries:**
  - `_threads: dict[str, threading.Thread]` (po.py:7530) maps pipeline_id to the live `_run` thread. Entries are popped in `_run`'s `finally` (po.py:13491).
  - `_cancel_events: dict[str, threading.Event]` (po.py:7531) holds one Event per in-flight pipeline. Entries are popped at po.py:13492.
  - `_cleanup_registered: bool = False` (po.py:7532) makes `register_cleanup` idempotent.
  - `_lifecycle_lock: threading.Lock` (po.py:7536) serializes the "read state → decide → write state / start thread" critical section of `cancel`, `delete_pipeline`, `resume` and `continue_to_full`, and the thread registration in `fork`. The comment says it exists so that two concurrent POST /resume calls cannot each start a `_run` thread (po.py:7533-7535).
- `_run` is a classmethod that builds `self = cls()` per run (po.py:11884), so every `__init__` field below is **per-run-attempt instance state**.

### `__init__` (po.py:7538-7546)
- `_partial_scan_at: dict[str, float]` (po.py:7540) is a per-stage throttle timestamp for the in-flight partial-artifact scan (used outside this slice by `_register_partial_artifacts`, po.py:10208).
- W9-3 telemetry state: `_tel_lock` (Lock, po.py:7542), `_tel_path` (po.py:7543), `_tel_prev` (po.py:7544), `_tel_prev_cum` (po.py:7545) and `_tel_last_flush_calls = 0` (po.py:7546).
- The API also builds an orchestrator just to call `heartbeat_status` (`backend/app/api/research.py:318`), so construction must stay cheap.

### W9-3 run-telemetry incremental flush (po.py:7548-7632)
The comment block (po.py:7549-7555) gives the motivation. `LLMMeter` is an in-memory accumulator, and `run_telemetry.json` used to be written only once, in `_run`'s `finally`, so a SIGTERM'd run lost all of its token/cost accounting. The fix fixes the merge base at the attempt's start, so repeated flushes never double-count.

#### `_init_telemetry_flush(state)` (po.py:7557-7573)
- Sets `_tel_path = <PIPELINE_DATA_DIR>/<pid>/run_telemetry.json` (po.py:7559) and resets prev/cum/last-calls (po.py:7560-7562).
- Reads the existing file. If it is a dict whose `total.calls` is truthy (po.py:7565), it stores `_tel_prev = {total, report_id, status}` (po.py:7566-7570) and `_tel_prev_cum = prev.cumulative_total or prev.total or {}` (po.py:7571).
- Any exception is ignored, which is the same as treating the next write as the first (po.py:7572-7573).
- Called once per attempt at the start of `_run` (po.py:11894).

#### `_flush_run_telemetry(state, *, final=False, extra=None)` (po.py:7575-7614)
- Does nothing if `_tel_path` is unset (po.py:7582-7584).
- Holds `_tel_lock` (po.py:7587) while it:
  1. takes `LLMMeter.snapshot(pipeline_id)` (po.py:7589) and adds `pipeline_id`, `status` and `report_id` (po.py:7590-7594), then merges `extra` (po.py:7595-7596);
  2. adds `in_flight: True` when `final` is False (po.py:7597-7598);
  3. when a previous attempt exists, writes `previous_attempt` and computes `cumulative_total[k] = round(base[k] + cur[k], 6)` for the keys `calls, cached, prompt_tokens, completion_tokens, total_tokens, latency_ms, cost_usd` (po.py:7599-7610);
  4. writes `write_json_atomic(tpath, data, fsync=final)` (po.py:7611), so only the final write is fsynced;
  5. records `_tel_last_flush_calls = total.calls` (po.py:7612).
- Any exception is only logged at debug level (po.py:7613-7614).
- Callers:
  - `_maybe_flush_run_telemetry` (po.py:7632);
  - the end of the ensemble window (po.py:8760);
  - `_complete_stage` (po.py:9049);
  - `_fail_stage` (po.py:9764);
  - the `_run` finally, with `final=True` and `extra` carrying `report_telemetry` and `sim_llm_health` (po.py:13430).

#### `_maybe_flush_run_telemetry(state)` (po.py:7616-7632)
- Does nothing without `_tel_path` (po.py:7618-7619).
- `n = Config.PIPELINE_TELEMETRY_FLUSH_EVERY_CALLS` (default 20; po.py:7621, `backend/app/config.py:490`). A value of `n <= 0` turns incremental flushing off (po.py:7624-7625).
- Flushes when `LLMMeter.snapshot().total.calls - _tel_last_flush_calls >= n` (po.py:7628-7632).
- Called from the stage updater on every progress callback (po.py:8997) and from the heartbeat thread on every beat (po.py:10364).

### `reconcile_orphans()` — classmethod (po.py:7636-7735)
Runs once at backend boot, inside `create_app()` and **before the port is bound** (`backend/app/__init__.py:140`; `run.py` calls `app.run` at `backend/run.py:57`). It is also called by `backend/scripts/scheduled_rerun.py:596`.
1. **Port probe (ORCH-2)** (po.py:7656-7668). If `Config.PIPELINE_RECLAIM_PORT_PROBE` (default true, `backend/app/config.py:495`) is set, it opens a TCP connection to `127.0.0.1:$FLASK_PORT` (default 5001) with a 0.2 s timeout. If the connection succeeds, another backend is assumed to be serving, so it logs a warning and **returns immediately**. That skips orphan reclaim and graph GC entirely.
2. Gets the `TaskManager()` singleton (po.py:7669). Reads `hb_enabled = PIPELINE_HEARTBEAT_ENABLED` (default true, po.py:7670) and `stale_s = PIPELINE_HEARTBEAT_STALE_S` (default 120, po.py:7671).
3. For each `PipelineManager.list_pipelines()` entry with `status == "running"` whose id is not in `cls._threads` (po.py:7672-7677):
   - **Liveness check (I-4-1)**: when `hb_enabled` and `_orphan_is_dead(...)` is False, it logs and skips (po.py:7679-7684). When the heartbeat is disabled, every running pipeline without a thread counts as an orphan.
   - **Salvage path (W9-1)**: when `PIPELINE_SALVAGE_COMPLETED_ORPHANS` (default true, `backend/app/config.py:486`) is set and `_orphan_completed_report(full_state)` returns non-None (po.py:7689-7691), it calls `PipelineManager.mark_salvaged_completed(pid, note)` (po.py:7695; implementation po.py:1024-1075). That sets the status to completed, `pipeline_health` to degraded and `ensemble_done=True`. [verifier: `pipeline_health.status` becomes degraded only when the block is missing or "ok"; an existing non-ok status (e.g. "failed" left by a previous attempt's health gate, which `resume` never clears) is preserved, so a salvaged run can read completed + health failed (po.py:1044-1050). Salvage also never runs `_assess_report_health`, so a report that would hard-fail the S1 gate (missing/failed final audit, placeholders, <2000 bytes) is still salvaged (po.py:7748-7769)] It then kills `research_pid` and each `options.research_track_pids` (po.py:7702-7704) and calls `task_manager.complete_task(..., salvaged=True)` (po.py:7705-7714), then `continue`.
   - **Fail path**: `PipelineManager.mark_failed(pid, "后端在运行中被中断（进程重启），该管线已标记为失败。")` (po.py:7716-7717). If that returns True, it reloads the state, kills `research_pid` and the track PIDs (po.py:7721-7725), and calls `task_manager.fail_task` (po.py:7726-7731).
4. Calls `cls._gc_stale_graphs()` (po.py:7733).
5. The whole body is wrapped in `except Exception`, which logs an error and never blocks boot (po.py:7734-7735).

### `_orphan_completed_report(data, report_dir=None)` — staticmethod (po.py:7737-7770)
Pure predicate that tests can call directly. It returns `{"report_id", "report_dir"}` only when **all** of these hold:
- `data` is a dict with a truthy `report_id` (po.py:7748-7752);
- `stages.report.status == "completed"` (po.py:7753-7755);
- `report_dir` is either given or resolves through `ReportManager._get_report_folder` (po.py:7756-7760);
- `full_report.md` is a non-empty file (po.py:7761-7766);
- `forecast.json` parses to a non-empty dict (po.py:7767-7769).

Otherwise it returns None.

### `_gc_stale_graphs()` — staticmethod (po.py:7772-7806)
- `retain = Config.GRAPH_RETAIN_COUNT` (default 5, `backend/app/config.py:1318`). A value of `retain <= 0` skips GC (po.py:7780-7785).
- Calls the module-level `graph_builder.gc_stale_graphs` if it exists. Otherwise it calls `GraphBuilderService(api_key=Config.ZEP_API_KEY).gc_stale_graphs` (po.py:7790-7795). On disk only the method form exists (`backend/app/services/graph_builder.py:2821`), so the fallback is always taken.
- Logs the audit dict (`total`, `kept`, `deleted`, `skipped_reason`) (po.py:7796-7802).
- `ImportError`/`AttributeError` produce a debug log. Any other exception produces a warning and is swallowed (po.py:7803-7806).
- Callers: `reconcile_orphans` (po.py:7733) and `delete_pipeline` (po.py:8085).

### `_orphan_is_dead(pipeline_id, stale_s)` — classmethod (po.py:7808-7840)
Evidence-based liveness check. It is conservative: it prefers to miss a reclaim rather than kill a live pipeline.

| Condition | Result | Anchor |
|---|---|---|
| state unreadable, or `INCOMPATIBLE_KEY` sentinel present | dead (True) | po.py:7818-7821 |
| `owner_boot_id == _BOOT_ID` (this process wrote it, but it is not in `_threads`) | dead | po.py:7828-7829 |
| `owner_pid` alive (`os.kill(pid,0)`; EPERM counts as alive, po.py:325-348) | dead iff heartbeat is not fresh (`heartbeat_at` age > `stale_s` or missing) | po.py:7831-7833 |
| owner pid missing or dead, and `heartbeat_at` missing/unparseable | dead unless `updated_at` age ≤ `stale_s` (ORCH-2 grace) | po.py:7837-7839 |
| owner pid missing or dead, and heartbeat present | dead iff heartbeat age > `stale_s` | po.py:7840 |

`_BOOT_ID` is a per-process uuid (po.py:300). Callers: `reconcile_orphans` (po.py:7679) and `resume` (po.py:8136).

### `_kill_orphan_research(pipeline_id, pid)` — staticmethod (po.py:7842-7867)
- Returns if `pid` is falsy or not an int (po.py:7845-7850).
- Runs `ps -p <pid> -o command=` as a subprocess with a 5 s timeout (po.py:7853-7856).
- **PID-reuse guard**: it returns unless `returncode == 0` **and** the command line contains `deerflow_research.py` **and** contains the `pipeline_id` (po.py:7860-7863). The pipeline id is present because `--out-dir .../<pid>/handoff` appears in the command line.
- Sends `os.killpg(os.getpgid(pid), SIGTERM)` (po.py:7864). `ProcessLookupError`, `PermissionError`, `OSError` and `SubprocessError` are all swallowed (po.py:7866-7867).

### `register_cleanup()` — classmethod (po.py:7869-7917)
- Idempotent (po.py:7877-7878).
- In Flask debug mode (`FLASK_DEBUG=1` or `WERKZEUG_RUN_MAIN` set), it only registers in the reloader child (`WERKZEUG_RUN_MAIN=='true'`). The parent sets the flag and returns (po.py:7881-7885).
- Registers `atexit.register(DeerFlowResearchRunner.cleanup_all)` (po.py:7888). `cleanup_all` sends SIGTERM to the process group of each live research `Popen` (po.py:2106-2111).
- Captures the previous SIGINT/SIGTERM/(SIGHUP) handlers (po.py:7890-7896). The installed `cleanup_handler` runs `cleanup_all` and then chains:
  - a callable previous handler is invoked; this is normally SimulationRunner's, since it registers first at `backend/app/__init__.py:129`;
  - `SIG_IGN` makes the handler return;
  - otherwise it restores `SIG_DFL` and re-sends the signal to itself (po.py:7898-7908).
- A `ValueError` (not on the main thread) is swallowed (po.py:7915-7917).
- It **does not** touch persisted pipeline state. Orphaned `running` states are left for the next boot's `reconcile_orphans`.

### `start(prompt, *, mode="full", project_name, depth, max_rounds, language, model)` — classmethod (po.py:7919-7979)
- `pipeline_id = "pipe_" + uuid4().hex[:12]` (po.py:7932); `ensure_dirs` creates `<PIPELINE_DATA_DIR>/<id>/handoff` (po.py:7933).
- Creates an in-memory task: `TaskManager().create_task(task_type=f"pipeline:{mode}", metadata={pipeline_id})` (po.py:7935-7939).
- Stages: `RESEARCH_ONLY_BANDS` (research only) when `mode == "research_only"`, otherwise all six `STAGE_BANDS` stages (po.py:7941-7942; bands at po.py:95-105).
- Builds `PipelineState(status="running", task_id, handoff_dir, stages)` (po.py:7944-7952).
- Sets these options (po.py:7953-7961):
  - `project_name` (default `"研究预测 <id>"`);
  - `depth` (default `Config.DEERFLOW_RESEARCH_DEPTH`, which is `deep`; `backend/app/config.py:1159`);
  - `max_rounds`;
  - `research_language`, which is tri-state: None means the Config default, `""` means auto, and any other value overrides;
  - `research_model`.
- Pins `actor_intelligence_policy_v1 = admission_actor_intelligence_policy_v1()` (po.py:7962-7964; definition po.py:832-853).
- Pins `safety_policy_v1 = capture_safety_policy_v1("admission")` (po.py:7967; definition po.py:776-805).
- `PipelineManager.save(state)` (po.py:7968), then creates the cancel Event, starts a daemon thread named `pipeline-<id>` running `cls._run`, and registers it in `_threads` (po.py:7970-7978).
- Returns immediately. `_lifecycle_lock` is not taken; the id is fresh.

### `cancel(pipeline_id)` — classmethod (po.py:7981-8016)
Runs under `_lifecycle_lock` (po.py:7993):
- no state → `{"ok": False, "status": "not_found"}` (po.py:7995-7996);
- status is not `running` → `not_running` (po.py:7997-7998);
- the Event and a live thread both exist → `event.set()` and return `cancelling` (po.py:8000-8005). Cancellation actually takes effect at the next cancel point: the stage updater (po.py:8961-8963), the RUN poll loop, the seed loops, or the research runner.
- Otherwise the pipeline is an orphan: `mark_failed(pid, "已被用户取消", status="cancelled")`, then `TaskManager().fail_task`, then return `cancelled` (po.py:8008-8016). **No liveness check is made** before this; see Surprises.

The API maps the result to 404, 409 or 200 (`backend/app/api/research.py:132-144`).

### `_dependent_forks(pipeline_id)` — classmethod (po.py:8018-8040)
- Scans `list_pipelines()`. For each other id, it reads `options.base_pipeline_id`. `list_pipelines()` rows never contain `options` (po.py:1204-1222), so the code always falls back to a full `PipelineManager.load(pid)` (po.py:8032-8035).
- Collects ids whose `base_pipeline_id == pipeline_id` (po.py:8036-8037). Errors are swallowed and the method returns what it has so far (po.py:8038-8040).

### `delete_pipeline(pipeline_id, force=False)` — classmethod (po.py:8042-8086)
Runs under `_lifecycle_lock` (po.py:8055):
- a live thread → `still_running` (po.py:8056-8058);
- no state → `not_found` (po.py:8059-8061);
- `force=False` with dependent forks → `{"status": "has_dependents", "dependents": [...]}` (po.py:8062-8070);
- persisted `running` with no thread (orphan) → `mark_failed(..., "已被用户删除", status="cancelled")`, then kill the research PID and track PIDs (po.py:8071-8078);
- `PipelineManager.delete(pid)` removes the whole `<PIPELINE_DATA_DIR>/<id>/` tree with `rmtree(ignore_errors=True)` (po.py:8079; implementation po.py:1185-1201). On success it pops the registries and runs graph GC **while still holding the lifecycle lock** (po.py:8080-8085).
- Returns `deleted`, or `not_found` if the directory still exists after rmtree (po.py:8086).
- It does **not** delete `uploads/reports/<report_id>` or `uploads/simulations/<sim_id>`.

### `clean_terminal(statuses=("failed","cancelled"))` — classmethod (po.py:8088-8104)
- For each listed pipeline whose status is in `statuses`, it calls `delete_pipeline(pid)` without force, so bases that have forks are skipped (po.py:8096-8101).
- Returns `{deleted, skipped}` (po.py:8104). The API restricts `statuses` to failed/cancelled (`backend/app/api/research.py:291-299`).

### `resume(pipeline_id, force=False)` — classmethod (po.py:8106-8211)
Runs entirely under `_lifecycle_lock` (po.py:8120):
1. A live thread → `RuntimeError("管线仍在运行，无法恢复")` (po.py:8122-8124). A missing state → `FileNotFoundError` (po.py:8126-8128). A newer schema → `IncompatiblePipelineSchema`, which is a RuntimeError subclass and becomes HTTP 409 (po.py:8129-8131; class po.py:274).
2. **ORCH-3(a)** status `running`: if `_orphan_is_dead(pid, PIPELINE_HEARTBEAT_STALE_S)`, it calls `mark_failed(..., status="cancelled")`, reloads and continues. Otherwise it raises RuntimeError (po.py:8132-8142).
3. **ORCH-3(b)** status `completed`: allowed only when `force` is set and `options.pipeline_health.status` is degraded or failed. Otherwise it raises RuntimeError, with a hint about `force=true` when health is degraded (po.py:8143-8151).
4. `PipelineState.from_dict`, `ensure_dirs`, and `setdefault` for every band stage (po.py:8153-8157).
5. Forced completed resume: `_reset_stage_attempt(REPORT)`, `current_stage = REPORT`, and `options.force_report_regen = now` (po.py:8159-8165). The REPORT reuse guard consumes that flag (po.py:13224). [verifier: it is popped only when an existing report was found and survived the health guard (short-circuit `existing_report is not None and state.options.pop(...)`, po.py:13224); if the guard already rejected the report (po.py:13216-13222) the flag stays in `options`, is persisted, and will force a regeneration on a later resume]
6. If `current_stage`'s status is failed or cancelled, it is reset with `_reset_stage_attempt`, which sets pending/0/""/None and clears timestamps (po.py:8167-8171; helper po.py:3839-3854).
7. Creates a new task `pipeline:<mode>:resume` with `resumed_from_task_id` (po.py:8173-8178). Sets `status = "running"`, `error = None`, `research_pid = None`, `options.resumed_at = now`, and increments `options.resume_count` (po.py:8179-8183).
8. **Foglamp WP1 1B**: if `safety_policy_v1` is missing (the pipeline was admitted before WP1), it pins `capture_safety_policy_v1("resume_reconstructed_safe")` and logs a warning. It never reconstructs legacy unsafe defaults (po.py:8188-8199).
9. Saves, then starts the daemon thread `pipeline-resume-<id>` (po.py:8200-8211). The id stays the same; skipping completed or reusable stages happens inside `_run`.

### `continue_to_full(pipeline_id)` — classmethod (po.py:8213-8277)
Runs under `_lifecycle_lock` (po.py:8222):
- Preconditions: no live thread (po.py:8223-8225), state exists (po.py:8227-8229), compatible schema (po.py:8230-8232), `mode == "research_only"` (po.py:8233-8234), `status == "completed"` (po.py:8235-8236), and a non-empty `handoff/research_report.md` (po.py:8238-8241). A failed precondition raises RuntimeError (409 at the API). [verifier: a missing state raises FileNotFoundError (404 at the API, `backend/app/api/research.py:210-211`), not RuntimeError (po.py:8227-8229); the schema check raises `IncompatiblePipelineSchema`, a RuntimeError subclass (po.py:8230-8232, 274)]
- Sets `state.mode = "full"`. RESEARCH is forced to completed/100; every other `STAGE_BANDS` stage is reset to pending (po.py:8245-8253).
- Creates task `pipeline:full:continue` (po.py:8255-8259). Sets `status = running`, `current_stage = ONTOLOGY`, and `options.continued_to_full_at` (po.py:8260-8264). Saves and starts the thread `pipeline-continue-<id>` (po.py:8265-8277).
- It does not re-pin `safety_policy_v1`, unlike `resume`. A research_only pipeline started under WP1 already carries the pin from `start`.

### `fork(base_pipeline_id, overlay)` — classmethod (po.py:8279-8350)
T4.6 what-if scenario. A new pipeline reuses the base's project, graph and handoff, and re-runs only prepare, run and report.
- Base must exist (FileNotFoundError), be schema-compatible, and have a `graph_id` (RuntimeError "基础管线尚未建图") (po.py:8288-8296). **The base's status is not checked.**
- `label = overlay.label or "情景"` (po.py:8298); `new_id = pipe_<hex12>` (po.py:8299).
- New `PipelineState(mode="full", project_id, graph_id from base, handoff_dir = base.handoff_dir or handoff_dir(base))` (po.py:8300-8307). The fork **shares the base's handoff directory**.
- RESEARCH, ONTOLOGY and GRAPH are set to completed/100 so they hit the reuse guards. The other stages are fresh (po.py:8309-8314).
- `options = {scenario_overlay, scenario_label, base_pipeline_id, project_name}` (po.py:8315-8320). It copies `actor_intelligence_policy_v1` from the base when present (po.py:8321-8326) and `max_rounds` from the overlay as an int (po.py:8327-8331).
- **Not carried over:** `safety_policy_v1`, `research_language`, `depth` and `research_model`. [verifier: the base's own `options.max_rounds` is also not carried; `max_rounds` comes only from the overlay (po.py:8327-8331). By contrast `backend/scripts/batch_runs.py:300-306` does copy `depth`, `research_language` and `research_model` from the base]
- Creates task `pipeline:full:scenario` (po.py:8334-8338). Sets `status = running` and `current_stage = PREPARE`, then saves (po.py:8339-8342). Only the thread registration runs under `_lifecycle_lock` (po.py:8344-8348).
- API: `backend/app/api/research.py:219-257` requires a non-empty `label` and runs preflight first. `backend/scripts/batch_runs.py:247-350` duplicates this logic with a prompt override and a shared-simulation mode.

### `apply_scenario_overlay_to_config(config, overlay)` — staticmethod (po.py:8352-8458)
A deterministic, in-place edit of a generated `simulation_config.json` dict. It returns the same dict.
- `by_name` maps `normalize_name(entity_name)` (NFKC, lowercase, punctuation and whitespace stripped; `backend/app/utils/actors.py:145`) to the agent config (po.py:8360-8362).
- `influence_overrides{name: weight}` sets `agent.influence_weight = float(weight)`. Bad floats are skipped silently (po.py:8364-8371).
- `stance_overrides{name: stance}` sets `agent.stance = str(stance)` (po.py:8372-8376).
- `injected_events[]` (po.py:8378-8457):
  - Ensures `config.event_config.scheduled_events` exists (po.py:8380-8381).
  - **Calendar mode**: when `config.temporal_config.mode == "calendar"`, it uses `round_dates` (po.py:8384-8388).
  - The fallback poster is the agent with the highest `influence_weight`, computed **after** the overrides above. If there are no agents, the poster is `agent_id = 0` with an empty name (po.py:8390-8392).
  - It counts existing rows flagged `is_scenario_injection` by canonical JSON key: `sort_keys`, compact separators (po.py:8393-8407).
  - Per event, the round starts as `int(ev.round or 0)` (po.py:8412). In calendar mode it is **replaced** by a date-based mapping:
    - no parseable `date` → round 0, with a warning (po.py:8414-8418);
    - `sim_timeline.round_for_date` hit → that round (po.py:8420-8423);
    - date after the last `period_end` → last round (po.py:8424-8426);
    - otherwise, such as a date before as_of → round 0 (po.py:8427-8429).
  - Builds the row `{round, content, date, poster_agent_id, poster_name, is_scenario_injection: True}`. An unmatched poster falls back to the fallback poster (po.py:8430-8437).
  - **Idempotent re-apply**: a row is appended only when the existing count of identical rows is below the requested count. Re-running PREPARE does not duplicate rows, while intentional duplicates inside the overlay are kept (po.py:8438-8456).
- `as_of_shift`, which is documented in the `fork` docstring, is **never read** (see Surprises).
- Caller: the PREPARE stage of `_run`, only when `options.scenario_overlay` is set and the RUN is not already done. The caller re-reads the config and writes it with tmp + `os.replace`; any exception skips the whole overlay with a warning (po.py:12825, 12855-12871).

### `_infer_horizon_date(prompt, actors)` — staticmethod (po.py:8461-8486)
- Text is `prompt + "\n" + actors.central_question` (po.py:8469-8471).
- `as_of = parse_as_of(actors.as_of_date)`, or today (po.py:8475-8479). Delegates to `sim_timeline.extract_horizon(text, as_of)`, which returns `hr.horizon_date` (YYYY-MM-DD) or None (po.py:8479-8480; extractor `backend/app/utils/sim_timeline.py:266`).
- On any exception it falls back to a regex `(?<!\d)(20\d{2})(?!\d)` and returns `max(year)-12-31`, or None (po.py:8481-8486).
- Caller: PREPARE world-state seed injection (po.py:12897).

### `_agreement_to_confidence(agreement)` — staticmethod (po.py:8488-8499)
- `≥ 0.75` → "high"; `≥ 0.45` → "medium"; otherwise "low".
- A non-float, including `None`, which `aggregate_forecasts` returns when fewer than two consensus buckets exist (`backend/app/services/ensemble.py:159-165`), → "medium".

### `_read_report_forecast(report_id)` — staticmethod (po.py:8501-8514)
Reads `uploads/reports/<report_id>/forecast.json`. A missing file or any exception returns None. The folder comes from `ReportManager.REPORTS_DIR = UPLOAD_FOLDER/reports` (`backend/app/services/report_agent.py:11864`).

### `_pinned_safety(state, key, default)` — staticmethod (po.py:8516-8527)
- Returns `state.options.safety_policy_v1[key]`, or `default` when the pin or the key is missing or None. It never raises.
- Callers:
  - seed count (po.py:8541);
  - seed graph feedback (po.py:8804, 8856);
  - main RUN graph feedback (po.py:12985);
  - RUN confluence fence (po.py:13082).

### `_maybe_run_seed_ensemble(state, project, graph_id, actors, research, report_md)` (po.py:8529-8760)
Runs N-1 additional prepare→run→report lanes on the **same graph** with different seeds, then aggregates their `forecast.json` files.

**Gates** (any one returns early):
- `n_seeds = max(1, int(_pinned_safety("n_forecast_seeds", Config.N_FORECAST_SEEDS)))` (po.py:8539-8545). The default is 1 (`backend/app/config.py:303`), so by default the method returns immediately;
- `mode != "full"`;
- `Config.REPORT_STRUCTURED_FORECAST` is off (ambient, not pinned);
- `options.ensemble_done` is set (po.py:8546-8549);
- `project`, `graph_id` or `report_id` is missing (po.py:8550-8551);
- the primary forecast has no `scenarios` (po.py:8553-8556).

**Setup:**
- `forecasts = [primary_fc]` (po.py:8557). `base_seed = Config.SIM_SEED` (default 0, po.py:8559).
- `max_rounds = options.max_rounds`. Otherwise it is None in calendar mode, or `OASIS_DEFAULT_MAX_ROUNDS` (36) in hours mode (po.py:8562-8564).
- `seed_jobs = [(k, base_seed + k*7919) for k in 2..n_seeds]` (po.py:8567). With base 0 and n = 3, the seeds are 15838 and 23757.
- A cancel already set raises `PipelineCancelled` (po.py:8568-8570).
- **Scenario spine (W9-5)**: `[{name, resolution_criteria}]` taken from the primary scenarios and pinned to every seed's ReportAgent (po.py:8574-8582).
- **Checkpoint (W9-2)**: `<handoff>/ensemble_checkpoint.json` is read into `_done_seeds[seed]` (po.py:8587-8597). `_persist_ckpt()` writes `{schema_version: 1, pipeline_id, primary_report_id, n_seeds_requested, completed[], updated_at}` atomically; a failure only warns (po.py:8600-8613).
- `options.ensemble_wall.started_at` (po.py:8615) and telemetry stage `"ensemble"` (po.py:8617).
- `seed_conc = clamp(ENSEMBLE_SEED_CONCURRENCY, 1, 3)`, default 2 (po.py:8626-8629).

**`_do_seed(k, seed)`** (po.py:8631-8672):
- Sets the run context `(pipeline_id, "ensemble")`, because the worker threads do not inherit contextvars (po.py:8639-8642).
- If the checkpoint holds this seed **and** its report still has scenarios, it reuses the seed: appends `{..., resumed_from_checkpoint: True}` and returns (po.py:8643-8654).
- Otherwise it calls `_run_one_seed(...)` (po.py:8655-8658). Under `_ckpt_lock` it records `{k, seed, simulation_id, report_id, has_forecast, completed_at}` and persists the checkpoint (po.py:8659-8665). It then calls `touch_heartbeat` (po.py:8666-8669), appends to `extra_runs`, and appends the forecast if it has scenarios (po.py:8670-8672).

**Execution:**
- **Serial** when `seed_conc <= 1` or there is only one job (po.py:8675-8691). Per seed it checks cancel, sets the REPORT stage message `"多种子集成 k/N（种子 s）…"`, refreshes the in-memory heartbeat when `owner_boot_id` is set, saves, and runs `_do_seed`. `PipelineCancelled` re-raises; any other exception warns and skips.
- **Parallel** otherwise (po.py:8692-8711): a `ThreadPoolExecutor(max_workers=seed_conc, thread_name_prefix="ens-seed")` with `as_completed`. The first `PipelineCancelled` is remembered and re-raised after the pool drains (po.py:8706-8711).

**Aggregation:**
- Fewer than two forecasts → `ensemble_done = True`, save, return. No file is written (po.py:8712-8716).
- Otherwise it calls `ensemble.aggregate_forecasts(forecasts)` and adds `n_seeds_requested`, `extra_runs` and `confidence` (po.py:8717-8722).
- It writes `ensemble_forecast.json` to the handoff directory and registers `artifacts.ensemble_forecast` (po.py:8728-8732). It also writes a copy into the **primary report folder** (po.py:8733-8738).
- It sets `options.ensemble_done = True` and `options.ensemble = {n_runs, agreement, confidence}`, then saves (po.py:8739-8745).
- **The primary `forecast.json` and `full_report.md` are deliberately NOT modified.** The output is a "sensitivity sidecar", so the final audit fingerprints stay valid (po.py:8723-8727).

**`finally`** (po.py:8746-8760): sets `ensemble_wall.finished_at`, refreshes the in-memory heartbeat, saves, restores telemetry stage `report`, and calls `_flush_run_telemetry`.

**Caller:** `_run` after the REPORT stage and before the health gate (po.py:13333-13340). `PipelineCancelled` propagates; any other exception warns and leaves the main report unaffected.

### `_run_one_seed(state, project, graph_id, actors, research, report_md, *, seed, max_rounds, scenario_spine=None)` (po.py:8762-8889)
1. `SimulationManager().create_simulation(project_id, graph_id, twitter=True, reddit=True)` (po.py:8772-8776).
2. Persona fan-out is `PARALLEL_PROFILE_COUNT` (default 16) when the provider is openai-compatible (`Config.PROVIDER_META[LLM_PROVIDER].openai_compat`), otherwise 3 (po.py:8773, 8780, 8794).
3. Reads `<handoff>/graph_priors.json` (W9-5 parity with the main PREPARE) (po.py:8783-8789).
4. Calls `prepare_simulation(sim_id, simulation_requirement=prompt, document_text=report_md, parallel_profile_count, actors, graph_priors, max_rounds, research_language=options.research_language)` (po.py:8790-8799). **No progress_callback is passed.**
5. `run_kwargs = {platform: "parallel", sim_seed: seed, max_rounds?}`. When the pinned `sim_graph_feedback` is on (default off, `backend/app/config.py:1385`), it also adds `enable_graph_memory_update=True` and `graph_id` (po.py:8800-8807). Then `SimulationRunner.start_simulation(...)` (po.py:8808).
6. Poll loop with a 5 s sleep (po.py:8822-8854):
   - cancel → `stop_simulation` + `PipelineCancelled` (po.py:8823-8828);
   - `get_run_state` returns None → RuntimeError (po.py:8829-8831);
   - a round change resets the stall timer (po.py:8832-8835);
   - COMPLETED → break (po.py:8836-8837);
   - FAILED or STOPPED → RuntimeError (po.py:8838-8839);
   - **inline stall watchdog**: more than `PIPELINE_RUN_STALL_S` (default 1800 s) without a round change → `stop_simulation` + RuntimeError (po.py:8813-8815, 8840-8845);
   - heartbeat touch every `PIPELINE_HEARTBEAT_INTERVAL_S` (default 30 s) (po.py:8817-8821, 8848-8853).
7. When feedback is on: `join_monitor_thread(timeout=30)` and `ZepGraphMemoryManager.stop_updater` (po.py:8856-8862). Then `SimulationRunner.write_run_summary(sim_id)`, with errors swallowed (po.py:8863-8866).
8. `rid = report_<hex12>` (po.py:8867). Builds `ReportAgent(graph_id, simulation_id, simulation_requirement, situation_brief(actors), actors, sources, research_report, [scenario_spine])`. A `TypeError` triggers a retry without the spine (po.py:8868-8887).
9. `agent.generate_report(report_id=rid)`, then returns `(sim_id, rid, _read_report_forecast(rid))` (po.py:8888-8889).

### Progress helpers

#### `_global_from_stage(mode, stage, local_pct, dynamic_bands=None)` — staticmethod (po.py:8893-8901)
- The base table is `RESEARCH_ONLY_BANDS` when mode is research_only, otherwise `STAGE_BANDS`.
- `dynamic_bands` is used when present and mode is not research_only (po.py:8895-8897).
- `band = bands.get(stage) or base.get(stage, (0, 100))`. `local_pct` is clamped to 0..100 and the result is `int(lo + (hi - lo) * pct / 100)`, truncated (po.py:8898-8901).
- Static bands: research 0-30, ontology 30-40, graph 40-60, prepare 60-72, run 72-92, report 92-100 (po.py:95-102).

#### `_recompute_dynamic_bands(state, chunk_count=None, total_rounds=None, section_count=None, temporal=None)` — staticmethod (po.py:8903-8947)
- Research and ontology stay static. The 40→100 range is re-split across **graph, prepare, run and report** (po.py:8917-8918, 8935-8946).
- Weights:
  - graph = `chunk_count or 20`;
  - prepare = 8.0;
  - run = `(total_rounds or 24) * 1.5`;
  - report = `(section_count or 6) * 6` (po.py:8931-8934).
- Each signal falls back to the previous `options.cost_signals`. Calendar fingerprint keys `calendar_unit`, `n_rounds` and `horizon_date` from `temporal` are carried along (po.py:8920-8930).
- Segment ends are rounded with `int(round(...))`, and `report[1]` is forced to 100 (po.py:8941-8946). The result is stored in `options.dynamic_bands` (po.py:8947).
- Example with all defaults: graph [40,52], prepare [52,57], run [57,78], report [78,100]. This was computed by replaying the formula.
- Callers: GRAPH stage after chunking with `chunk_count` (po.py:12495), and the RUN poll loop the first time `total_rounds > 0` with `total_rounds` and `temporal` (po.py:13039-13040). **`section_count` is never passed by any caller.**

#### `_make_stage_updater(state, stage)` → `update(local_pct, message)` (po.py:8949-9007)
- On creation it sets the telemetry stage contextvar to `stage` (po.py:8952-8956).
- Each `update()` call, in order:
  1. **Cancel checkpoint**: raises `PipelineCancelled("管线已被用户取消")` if the Event is set (po.py:8961-8963).
  2. **Outage checkpoint (DEFECT-1)**: raises `ProviderOutageHalt(breaker.halt_message())` if the run's breaker has tripped (po.py:8967-8969). Both exceptions are `BaseException` subclasses (po.py:248, 258), so they pass through `except Exception` layers.
  3. Upserts the StageState: `status="running"`, `progress` clamped to 0..100, `message`, and `started_at` if it is unset. Sets `current_stage = stage` (po.py:8970-8979).
  4. Sets `last_progress_at = now`, and `heartbeat_at = now` when `owner_boot_id` is set. This prevents the save from overwriting a fresher heartbeat written by the heartbeat thread (po.py:8984-8987).
  5. Sets `global_progress` through `_global_from_stage` using the dynamic bands (po.py:8988-8990).
  6. Calls `_register_partial_artifacts(state, stage)` (po.py:8993; po.py:10208), then `PipelineManager.save(state)` (po.py:8994).
  7. Calls `_maybe_flush_run_telemetry`, swallowing errors (po.py:8996-8999).
  8. Calls `TaskManager.update_task(task_id, progress=global, message="[stage] msg")` (po.py:9000-9005).
- Callers: one updater per stage in `_run` (po.py:11903, 12308, 12390, 12734, 12941, 13186).

#### `_complete_stage(state, stage, message="完成", *, reused=False)` (po.py:9009-9049)
- Sets `status=completed`, `progress=100` and `message` (po.py:9026-9029).
- `reused=True` preserves the original attempt timestamps:
  - if both are missing, both are set to now (zero duration);
  - if only `started_at` is missing, it is set to `finished_at`;
  - if only `finished_at` is missing, it is set to `started_at` (po.py:9031-9037).
- `reused=False` sets `finished_at = now` (po.py:9038-9039).
- Then: `global_progress` for 100% of the stage (po.py:9040-9042); `_record_stage_artifacts` with errors swallowed (po.py:9043-9046; po.py:9703); save (po.py:9047); `_flush_run_telemetry` (po.py:9049).

### `_reconcile_completed_simulation_state(sim_state, run_state=None, run_summary=None)` — staticmethod (po.py:9051-9099)
Projects the authoritative terminal RUN fields onto the API-facing `SimulationState`. Before this, records could show "completed" with round 0 and both platforms `not_started`.
- `status = SimulationStatus.COMPLETED` (po.py:9065).
- `current_round = max(run_state.current_round, run_summary.rounds_executed, default 0)`, with each value clamped to ≥ 0 (po.py:9066-9075).
- Per platform (twitter, reddit), with `enabled` taken from `run_state.<p>_enabled` or else `sim_state.enable_<p>`:
  - disabled → "disabled";
  - an explicit `<p>_completed` flag → "completed" or "incomplete";
  - otherwise the existing status is kept unless it is ""/"not_started", in which case it becomes "unknown" (po.py:9076-9098).
- `error = run_state.error or None` (po.py:9099).
- Caller: `_run` after the RUN completion-evidence gate, for both fresh and reused runs. It is followed by `sim_manager._save_simulation_state` (po.py:13157-13160).

### `_sim_dir(sim_id)` — staticmethod (po.py:9108-9111)
Returns `normpath(<po.py dir>/../../uploads/simulations/<sim_id>)`, which is `backend/uploads/simulations/<sim_id>`. That is the same physical directory as `SimulationRunner.RUN_STATE_DIR` (`backend/app/services/simulation_runner.py:279-282`) and `Config.OASIS_SIMULATION_DATA_DIR` (`backend/app/config.py:1080`), reached through three different expressions.

### `_spawn_run_stall_watchdog(pipeline_id, sim_id, stall_s)` (po.py:9113-9159)
Background (QUALITY-OPT C1/C2): the inline poll watchdog cannot fire while `get_run_state` is blocked on a wedged simulation's IPC.
- Returns a control dict `{"stop": False}`. With `stall_s <= 0` it returns that dict and starts no thread (po.py:9124-9126).
- The daemon thread `run-stall-wd-<sim8>` (po.py:9158):
  - wakes every 30 s and exits when `ctl.stop` is set (po.py:9132-9135);
  - reads `run_state.json` from disk and exits if `completed` or `error` is truthy (po.py:9138-9143);
  - resets the timer whenever `current_round` changes (po.py:9144-9146);
  - otherwise, once more than `stall_s` has passed, logs an error, calls `SimulationRunner.stop_simulation(sim_id)` and exits (po.py:9147-9154).
- All exceptions are swallowed (po.py:9155-9156).
- Caller: the main RUN stage (po.py:13001). The caller sets `_wd_ctl["stop"] = True` in a `finally` on every exit path (ORCH-6, po.py:13070). **Seed lanes do not use it.**

### `_assess_report_health(report_id)` → `(health, issues, meta)` (po.py:9161-9349)
`health` is one of "ok", "degraded" or "failed".
- No `report_id` → `("failed", ["no report_id was produced"], {})` (po.py:9169-9170). An unresolvable folder → failed (po.py:9171-9174).
- **Section placeholders** (po.py:9175-9193): over `section_*.md`, a section counts as a placeholder if it contains the exact failure template `"（本章节生成失败："` (ORCH-1). It also counts if its stripped body is shorter than 200 chars **and** has no chart marker (`![`, `<img`, `<svg`, ```` ```mermaid ````).
- **forecast.json** (po.py:9194-9247): `fc_ok = bool(scenarios or binary_forecasts)`. These `forecast.quality` signals become *degraded* issues (`q_issues`):
  - `quote_provenance.ungrounded` (S2);
  - `numeric_consistency.mismatch_count` (S11);
  - `implausible_stats.count` (S12);
  - `lint.leakage_flags`;
  - `binary_quality.passed == False` (A3/A4);
  - `sim_insensitivity.issue` (XRUN-1c);
  - `scenario_count_drift` (XRUN-16);
  - `quality.issues[]`.

  `quality.hard_issues[]` become *hard* issues. A parse error sets `fc_ok = False`.
- **Final read-only audit** (po.py:9248-9323), when `REPORT_FINAL_READ_ONLY_AUDIT` is on (default on, `backend/app/config.py:190-193`):
  - a missing `final_audit.json` is a hard issue;
  - otherwise each of the following adds a hard issue:
    - `policy_version != REPORT_FINAL_AUDIT_POLICY_VERSION`, which is 3 (`backend/app/config.py:195`);
    - `hard_passed is not True`;
    - `disk_matches_memory is not True`;
    - `publish_gate.enabled` while the gate did not pass;
    - `structured_forecast.required` while it is not valid;
    - `structured_forecast.required` while `scenario_contract` is not valid;
    - `markdown_sha256 != sha256(full_report.md)`;
    - `forecast_sha256 != sha256(forecast.json)`;
    - each entry in `publish_gate.hard_issues`.
  - The final hard issues go into both the hard and degraded lists. `publish_gate.epistemic_issues` go into the degraded list only.
  - `meta.final_audit` records `{read_only, markdown_sha256, forecast_sha256, disk_matches_memory, hard_passed}`. An unreadable or invalid audit file is a hard issue.
- **Verdict** (po.py:9324-9348). The result is "failed" (hard) if any of these holds:
  - every section is a placeholder (`total > 0`);
  - `forecast_ok` is False while `REPORT_STRUCTURED_FORECAST` is on;
  - `0 < len(full_report.md) < 2000` bytes;
  - any hard quality issue exists.

  Otherwise the result is "degraded" if there is any issue, and "ok" if there are none. `meta` holds `sections`, `placeholder_sections`, `forecast_ok`, `full_report_bytes`, `final_audit`, `quality_issues` and `hard_quality_issues`.
- Callers: `_enforce_pipeline_health` (po.py:9453), and the REPORT reuse guard, where a failed result triggers a fresh report with a new id (po.py:13215-13222).

### `_assess_run_health(sim_id, graph_id=None)` → `(health, issues, meta)` (po.py:9351-9443)
- No `sim_id` → `("ok", [], {})` (po.py:9357-9358).
- Counts rows in the `post` and `comment` tables of `reddit_simulation.db` and `twitter_simulation.db`, opened read-only with sqlite `mode=ro` URIs (po.py:9362-9377).
- XRUN-11: prefers `run_summary.json.organic_action_count` as the "organic" count (`organic_source = "run_summary"`), and takes `simulation_health` from the same file (po.py:9381-9398). These come from `backend/app/services/simulation_runner.py:2126-2145, 2219-2226`.
- Reads `run_state.json`: `error`, and `truncated = current_round < total_rounds` (po.py:9399-9411).
- XRUN-6: counts non-blank lines in `Config.OASIS_SIMULATION_DATA_DIR/_zep_dead_letter/<graph_id>.jsonl` (po.py:9414-9423). That is the updater's dead-letter path (`backend/app/services/zep_graph_memory_updater.py:275-279`).
- Each of these adds an issue:
  - `simulation_health` in {hollow, errored, llm_degraded, truncated};
  - an error;
  - truncation;
  - a database exists while organic == 0 ("hollow");
  - dead letters > 0 (po.py:9428-9441).
- The result is **never "failed"**: "degraded" if there is any issue, otherwise "ok" (po.py:9442).

### `_enforce_pipeline_health(state)` (po.py:9445-9497)
- Does nothing when `PIPELINE_HEALTH_GATE` is off (default on, `backend/app/config.py:167`) (po.py:9448-9449).
- Report health goes into `health.stages.report`. If the report health is "failed", `hard_issues = issues` (po.py:9453-9456).
- If `simulation_id` is set, run health goes into `stages.run`. A non-ok run whose `stages.run.error` is empty gets the joined issues **written into `stages.run.error`**, while the run stage's status stays completed (po.py:9457-9461).
- Graph (KG-5/LOOP-003) is marked degraded when either of these holds:
  - `options.graph_ingest_degraded_ratio` is non-None; the message is "skipped N% of chunks (skipped/total)";
  - `options.graph_prune.degraded` is set (po.py:9463-9485).
- `health.status` is "failed" when there are hard issues, otherwise "degraded" when any stage is degraded or failed, otherwise "ok". It is written to `state.options.pipeline_health` (po.py:9486-9489).
- If the assessment itself raises, it warns and **returns without writing health or failing the run** (po.py:9490-9492).
- Hard issues → `raise RuntimeError("交付物健康检查失败（deliverable is broken）: ...")` (po.py:9493-9494). `_run` catches this, sets `status=failed`, calls `_fail_stage(current_stage)` and saves (po.py:13381-13390).
- Degraded → warning log only (po.py:9495-9497).
- Caller: `_run` immediately before `state.status = "completed"` (po.py:13345-13346). research_only pipelines exit at po.py:12294-12305 and never reach it.

---

## Control flow

**Process boot** (`backend/app/__init__.py:122-145`). This only runs when `TESTING` is off and `DRF_TEST_PROCESS != '1'`:
1. `SimulationRunner.register_cleanup()`, then `SimulationRunner.reconcile_orphans()` (`backend/app/__init__.py:129-131`).
2. `PipelineOrchestrator.reconcile_orphans()` (port probe → per-orphan salvage or fail → graph GC), then `PipelineOrchestrator.register_cleanup()`, which chains SimulationRunner's signal handler (`backend/app/__init__.py:140-141`).

**API → lifecycle** (`backend/app/api/research.py`, blueprint prefix `/api/research`, `backend/app/__init__.py:204`):

| Route | Method called | API line |
|---|---|---|
| `POST /run` | `start` | `backend/app/api/research.py:109` |
| `POST /<id>/cancel` | `cancel` | `backend/app/api/research.py:136` |
| `POST /<id>/resume` (body `force`) | `resume` | `backend/app/api/research.py:164` |
| `POST /<id>/continue` | `continue_to_full` | `backend/app/api/research.py:199` |
| `POST /<id>/scenario` | `fork` | `backend/app/api/research.py:240` |
| `DELETE /<id>?force=` | `delete_pipeline` | `backend/app/api/research.py:269` |
| `POST /clean` | `clean_terminal` | `backend/app/api/research.py:299` |

`backend/app/api/sdk.py:136` (`/api/v1`) also calls `start`. So do the CLI scripts `backend/scripts/scheduled_rerun.py:693` and `backend/scripts/batch_runs.py:444`.

**Thread model.** `start`, `resume`, `continue_to_full` and `fork` each register `_cancel_events[id]` and `_threads[id]` and start a daemon thread on `_run` (po.py:7970-7978, 8202-8210, 8267-8275, 8344-8348). `_run`'s `finally` pops both entries (po.py:13491-13492). Inside `_run`:
1. `_init_telemetry_flush` (po.py:11894).
2. The heartbeat thread starts (po.py:11900). It calls `_maybe_flush_run_telemetry` on every beat (po.py:10364).
3. Each stage builds an updater with `_make_stage_updater` (po.py:11903 …13186), calls `update()` repeatedly (cancel/outage checkpoint + save), and ends with `_complete_stage`. That call saves and flushes telemetry.
4. GRAPH stage: `_recompute_dynamic_bands(chunk_count)` (po.py:12495).
5. PREPARE stage: `apply_scenario_overlay_to_config` for forks (po.py:12863), and `_infer_horizon_date` for the world-state seed (po.py:12897).
6. RUN stage: `_spawn_run_stall_watchdog` (po.py:13001) runs in parallel with the inline watchdog. The poll loop calls `_recompute_dynamic_bands(total_rounds)` (po.py:13039). `_wd_ctl.stop` is set in `finally` (po.py:13070). Then `_reconcile_completed_simulation_state` (po.py:13157) and `_complete_stage(RUN)`.
7. REPORT stage: the reuse guard calls `_assess_report_health` (po.py:13215). The report is reused or generated, followed by `_complete_stage(REPORT)`.
8. `_maybe_run_seed_ensemble` (po.py:13335). For each seed it runs `_run_one_seed`, serially or through the ThreadPoolExecutor.
9. `_enforce_pipeline_health` (po.py:13345). Then `status = completed` (po.py:13346), or `failed` via the exception handler.
10. `finally`: `_flush_run_telemetry(final=True)` (po.py:13430), then `LLMMeter.reset`, then the registries are popped.

**Cancellation path.**
1. `cancel()` sets the Event (po.py:8003).
2. The next `update()` raises `PipelineCancelled` (po.py:8961-8963). The RUN or seed poll loops also check the Event (po.py:8823-8828) and call `stop_simulation` first.
3. `_run` catches the exception at po.py:13359. It sets `status = "cancelled"`. The current stage becomes cancelled unless it is already completed or at 100%.

---

## Data & artifacts

| Path pattern | R/W | Format / key fields | Anchor |
|---|---|---|---|
| `backend/uploads/pipelines/<pid>/pipeline_state.json` (`Config.PIPELINE_DATA_DIR`, `backend/app/config.py:1581`) | R/W | `PipelineState.to_dict()`: status, mode, current_stage, stages{}, options{}, artifacts{}, owner_pid/owner_boot_id/heartbeat_at/last_progress_at, task_id, report_id… | written by `save` po.py:7968, 8200, 8265, 8342, 8994, 9047; by `mark_failed` po.py:7717, 8008, 8074, 8137; by `mark_salvaged_completed` po.py:7695 |
| `backend/uploads/pipelines/<pid>/handoff/` | created | `ensure_dirs` | po.py:7933, 8154, 8333 |
| `backend/uploads/pipelines/<pid>/run_telemetry.json` | R/W | LLMMeter snapshot (`run_id, total, by_stage, by_model, cost_estimated, cost_basis, fallback_attributed, unattributed_process`) + `pipeline_id, status, report_id`, `in_flight` (non-final), `previous_attempt{total,report_id,status}`, `cumulative_total{calls,cached,prompt_tokens,completion_tokens,total_tokens,latency_ms,cost_usd}` | po.py:7559-7611; snapshot shape `backend/app/utils/telemetry.py:273-300` |
| `<handoff>/research_report.md` | R | non-empty precondition for continue_to_full | po.py:8238-8241 |
| `<handoff>/graph_priors.json` | R | centrality priors passed to seed prepare | po.py:8785-8787 |
| `<handoff>/ensemble_checkpoint.json` | R/W | `{schema_version:1, pipeline_id, primary_report_id, n_seeds_requested, completed:[{k,seed,simulation_id,report_id,has_forecast,completed_at}], updated_at}` | po.py:8587-8613 |
| `<handoff>/ensemble_forecast.json` and `backend/uploads/reports/<primary_report_id>/ensemble_forecast.json` | W | `aggregate_forecasts` output (`n_runs, scenarios, agreement, schema_version…`) + `n_seeds_requested, extra_runs[{seed,simulation_id,report_id,resumed_from_checkpoint?}], confidence` | po.py:8717-8738 |
| `backend/uploads/reports/<rid>/forecast.json` | R | `scenarios`, `binary_forecasts`, `quality{…}`, `binary_quality` | po.py:8502-8514, 9195-9247 |
| `backend/uploads/reports/<rid>/section_*.md`, `full_report.md`, `final_audit.json` | R | placeholder scan; byte size; sha256 fingerprints; audit fields `policy_version, hard_passed, disk_matches_memory, publish_gate{enabled,passed,hard_issues,epistemic_issues}, structured_forecast{required,valid}, scenario_contract{valid}, markdown_sha256, forecast_sha256, read_only, hard_issues` | po.py:9175-9323 |
| `backend/uploads/simulations/<sim_id>/simulation_config.json` | (R/W by caller) | `agent_configs[].{entity_name,agent_id,influence_weight,stance}`, `event_config.scheduled_events[]`, `temporal_config{mode,round_dates[{period_start,period_end}]}` | po.py:8361-8457; caller write po.py:12856-12867 |
| `backend/uploads/simulations/<sim_id>/run_state.json` | R | `current_round`, `total_rounds`/`total_simulation_rounds`, `error` (the watchdog also reads a `completed` key that is never written; see Surprises) | po.py:9127-9143, 9401-9411 |
| `backend/uploads/simulations/<sim_id>/{reddit,twitter}_simulation.db` | R (sqlite ro) | `count(*)` of `post`, `comment` | po.py:9362-9377 |
| `backend/uploads/simulations/<sim_id>/run_summary.json` | R | `organic_action_count`, `simulation_health` | po.py:9385-9396 |
| `backend/uploads/simulations/_zep_dead_letter/<graph_id>.jsonl` | R | count of non-blank lines | po.py:9416-9421 |

**Important in-memory structures:**
- `_threads`, `_cancel_events` and `_lifecycle_lock` (po.py:7530-7536).
- Per-instance telemetry state (po.py:7542-7546).
- `options` keys written in this slice:
  - set at admission or resume: `safety_policy_v1`, `actor_intelligence_policy_v1`, `resumed_at`, `resume_count`, `force_report_regen`, `continued_to_full_at`;
  - fork metadata: `scenario_overlay`, `scenario_label`, `base_pipeline_id`;
  - progress: `dynamic_bands`, `cost_signals`;
  - ensemble: `ensemble_wall{started_at,finished_at}`, `ensemble_done`, `ensemble{n_runs,agreement,confidence}`;
  - health: `pipeline_health{status, stages{report,run,graph}}`.

  The status API returns `options` verbatim (`backend/app/api/research.py:314-332`).
- `TaskManager` is an **in-memory singleton** (`backend/app/models/task.py:54-71`). Task ids from a previous process do not exist after a restart.

---

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `PIPELINE_TELEMETRY_FLUSH_EVERY_CALLS` | 20 | incremental telemetry flush every N new LLM calls; ≤0 turns it off | `backend/app/config.py:490`; po.py:7621-7625 |
| `PIPELINE_RECLAIM_PORT_PROBE` | true | skip orphan reclaim and graph GC if `127.0.0.1:$FLASK_PORT` accepts a connection | `backend/app/config.py:495`; po.py:7656-7668 |
| `FLASK_PORT` (env) | 5001 | port used by the probe | po.py:7659 |
| `PIPELINE_HEARTBEAT_ENABLED` | true | evidence-based orphan check; when off, any running pipeline without a thread is an orphan | `backend/app/config.py:457`; po.py:7670, 7679 |
| `PIPELINE_HEARTBEAT_STALE_S` | 120 | heartbeat freshness window for `_orphan_is_dead` | `backend/app/config.py:459`; po.py:7671, 8135 |
| `PIPELINE_HEARTBEAT_INTERVAL_S` | 30 | seed-loop heartbeat cadence | `backend/app/config.py:458`; po.py:8818 |
| `PIPELINE_SALVAGE_COMPLETED_ORPHANS` | true | salvage orphans whose report is complete as completed(degraded) | `backend/app/config.py:486`; po.py:7689 |
| `GRAPH_RETAIN_COUNT` | 5 | graph GC keeps the N newest unreferenced graphs; ≤0 turns GC off | `backend/app/config.py:1318`; po.py:7781-7785 |
| `ZEP_API_KEY` | — | passed to `GraphBuilderService` for GC | po.py:7793 |
| `FLASK_DEBUG` / `WERKZEUG_RUN_MAIN` (env) | — | in debug mode, cleanup registers only in the reloader child | po.py:7881-7885 |
| `DEERFLOW_RESEARCH_DEPTH` | `deep` | default `options.depth` | `backend/app/config.py:1159`; po.py:7955 |
| `N_FORECAST_SEEDS` (pinned as `safety_policy_v1.n_forecast_seeds`) | 1 | ensemble size; ≤1 means no ensemble | `backend/app/config.py:303`; po.py:8541-8543 |
| `REPORT_STRUCTURED_FORECAST` | true | ensemble gate (ambient); a missing forecast is a hard health failure | `backend/app/config.py:162`; po.py:8547, 9334 |
| `SIM_SEED` | 0 | ensemble seed base | `backend/app/config.py:296`; po.py:8559 |
| `SIM_TEMPORAL_MODE` | `calendar` | in calendar mode the seed lanes get no default max_rounds | `backend/app/config.py:1067`; po.py:7296-7303, 8562-8563 |
| `OASIS_DEFAULT_MAX_ROUNDS` | 36 | seed max_rounds in hours mode | `backend/app/config.py:1063`; po.py:8563 |
| `ENSEMBLE_SEED_CONCURRENCY` | 2 (clamped 1..3) | parallel seed lanes | `backend/app/config.py:310`; po.py:8627 |
| `PARALLEL_PROFILE_COUNT` | 16 | seed persona fan-out (HTTP providers only; CLI providers use 3) | `backend/app/config.py:474`; po.py:8780, 8794 |
| `SIM_GRAPH_FEEDBACK` (pinned `sim_graph_feedback`) | false | seed sims write feedback into the graph and drain the monitor | `backend/app/config.py:1385`; po.py:8804-8807, 8856-8862 |
| `PIPELINE_RUN_STALL_S` | 1800 | inline seed watchdog; also the main-RUN disk watchdog interval passed by the caller [verifier: it is the disk watchdog's stall *threshold* (`stall_s`), not its interval; the watchdog polls on a fixed 30 s sleep (po.py:9133, 9147)] | `backend/app/config.py:355`; po.py:8813, 9126 |
| `LLM_PROVIDER` / `PROVIDER_META[*].openai_compat` | — | decides the seed persona fan-out | po.py:8773 |
| `REPORT_FINAL_READ_ONLY_AUDIT` | true | require and verify `final_audit.json` | `backend/app/config.py:190-193`; po.py:9250 |
| `REPORT_FINAL_AUDIT_POLICY_VERSION` | 3 (class constant, not env) | an audit with a stale policy is a hard issue | `backend/app/config.py:195`; po.py:9263-9269 |
| `PIPELINE_HEALTH_GATE` | true | turns the health gate on or off | `backend/app/config.py:167`; po.py:9448 |
| `PIPELINE_STRICT_SCHEMA` | true | when the state file is newer than the code, `load` returns a sentinel and resume/continue/fork raise `IncompatiblePipelineSchema` | `backend/app/config.py:352`; po.py:1154-1163, 8129-8131 |

---

## External calls

| Target | Kind | Anchor |
|---|---|---|
| `socket.create_connection(("127.0.0.1", port), timeout=0.2)` | local TCP probe | po.py:7663 |
| `ps -p <pid> -o command=` (timeout 5 s) | subprocess | po.py:7853-7856 |
| `os.killpg(os.getpgid(pid), SIGTERM)` | OS signal to the research process group | po.py:7864 |
| `DeerFlowResearchRunner.cleanup_all` (SIGTERM via `_kill_process_group`) | OS signal | po.py:7888, 7899; po.py:2106-2111 |
| `os.kill(os.getpid(), signum)` after restoring SIG_DFL | self-signal | po.py:7907-7908 |
| `GraphBuilderService(...).gc_stale_graphs(retain=)` → graph DB (FalkorDB/Graphiti runtime) | DB | po.py:7792-7795; `backend/app/services/graph_builder.py:2821-2867` |
| `SimulationManager.create_simulation` / `prepare_simulation` (LLM persona and config generation) | LLM (indirect) | po.py:8774-8799 |
| `SimulationRunner.start_simulation` (spawns the OASIS subprocess) / `get_run_state` / `stop_simulation` / `join_monitor_thread` / `write_run_summary` | subprocess and IPC | po.py:8808-8865, 9151 |
| `ZepGraphMemoryManager.stop_updater` | graph writer drain | po.py:8860 |
| `ReportAgent(...).generate_report(report_id=rid)` | LLM (multi-tool report) | po.py:8881-8888 |
| `ensemble.aggregate_forecasts` | pure computation | po.py:8717-8718; `backend/app/services/ensemble.py:150` |
| `sqlite3.connect("file:...?mode=ro", uri=True)` | local DB read | po.py:9368 |
| `LLMMeter.snapshot` / `set_run_context` / `set_stage` | in-process telemetry | po.py:7589, 7628, 8586-8619, 8640, 8954 |
| `TaskManager.create_task/update_task/complete_task/fail_task` | in-memory | po.py:7936, 8013, 8174, 8256, 8335, 9001, 7708, 7729 |

The slice itself makes **no direct HTTP or provider calls**. All LLM spend in this slice is indirect: seed-lane prepare, the OASIS simulation, and ReportAgent.

---

## Cross-module edges

**Callers into this slice:**
- `backend/app/__init__.py:140-141` → `reconcile_orphans`, `register_cleanup`.
- `backend/app/api/research.py`:
  - `start` (`:109`);
  - `cancel` (`:136`);
  - `resume` (`:164`);
  - `continue_to_full` (`:199`);
  - `fork` (`:240`);
  - `delete_pipeline` (`:269`);
  - `clean_terminal` (`:299`);
  - `PipelineOrchestrator()` for heartbeat status (`:318`).
- `backend/app/api/sdk.py:136` → `start`.
- `backend/scripts/scheduled_rerun.py:596, 693` → `reconcile_orphans`, `start`.
- `backend/scripts/batch_runs.py:444` → `start`. `backend/scripts/batch_runs.py:247-350` re-implements fork-like registration using the same registries.
- `backend/scripts/test_pipeline_resume.py:87-209` → resume, cancel, delete and clean.
- Internal callers from `_run` and its helpers, as listed in Control flow:
  - po.py:11894, 11903, 12287-12314, 12387, 12455, 12495, 12731, 12863, 12897, 12933, 13001, 13039, 13157, 13170, 13215, 13244, 13328, 13335, 13345, 13430;
  - the heartbeat thread at po.py:10364;
  - `_fail_stage` at po.py:9764.
- Tests that reference slice methods:
  - `backend/tests/test_wave9_orchestrator.py`: `_orphan_completed_report`, `_flush_run_telemetry`, `_init_telemetry_flush`;
  - `backend/tests/test_orchestrator_research_wiring.py`: `_assess_report_health`, `_reconcile_completed_simulation_state`, `apply_scenario_overlay_to_config`, `_complete_stage`, …;
  - `backend/tests/test_audit_fixes_infra.py`: `_orphan_is_dead`, `_assess_run_health`, `_enforce_pipeline_health`, `resume`, `_maybe_run_seed_ensemble`;
  - `backend/tests/test_runtime_lifecycle_isolation.py`: `reconcile_orphans`;
  - `backend/tests/test_foglamp_containment.py`: `_pinned_safety`;
  - `backend/tests/test_sim_resume_reuse.py`: `_complete_stage`;
  - `backend/tests/test_architecture_characterization.py` and `backend/tests/test_research_round3_parent.py`.

**Outbound from this slice:**
- `PipelineManager` (po.py:860-1222): `save`, `load`, `mark_failed`, `mark_salvaged_completed`, `touch_heartbeat`, `delete`, `list_pipelines`, `is_incompatible`, `handoff_dir`, `ensure_dirs`, `_dir`.
- Module helpers: `_BOOT_ID` (po.py:300), `_age_seconds` (po.py:317), `_pid_alive` (po.py:325), `_reset_stage_attempt` (po.py:3839), `_read_json` (po.py:2933), `_calendar_mode` (po.py:7296), `_outage_breaker_for` (po.py:542), `capture_safety_policy_v1` (po.py:776), `admission_actor_intelligence_policy_v1` (po.py:832).
- Sibling methods outside the slice: `_register_partial_artifacts` (po.py:10208), `_record_stage_artifacts` (po.py:9703), `_run` (po.py:11883).
- `ReportManager._get_report_folder` and `ReportAgent` (`backend/app/services/report_agent.py:11890`, `:1544-1621`).
- `SimulationManager`, `SimulationRunner`, `RunnerStatus`, `SimulationStatus`, `ZepGraphMemoryManager`.
- `utils.atomic.write_json_atomic` (`backend/app/utils/atomic.py:53`); `utils.telemetry` (`backend/app/utils/telemetry.py:42, 58, 273`); `utils.sim_timeline.round_for_date/extract_horizon` (`backend/app/utils/sim_timeline.py:491, 266`); `utils.actors.normalize_name/situation_brief`; `utils.dates.parse_as_of`.
- `ensemble.aggregate_forecasts`; `graph_builder.GraphBuilderService.gc_stale_graphs`; `models.task.TaskManager`.

---

## Invariants, gates, validation

- **One `_run` thread per pipeline per process.** `resume`, `continue_to_full` and `delete_pipeline` check `_threads[id].is_alive()` under `_lifecycle_lock` before acting (po.py:8122-8124, 8223-8225, 8056-8058).
- **Cancellation and outage halts are `BaseException`s.** They pass through `except Exception` layers and are raised from every progress callback (po.py:8961-8969; classes po.py:248, 258). The seed lanes re-raise `PipelineCancelled` explicitly (po.py:8688-8689, 8706-8711).
- **Schema compatibility.** `resume`, `continue_to_full` and `fork` refuse state files newer than `PIPELINE_SCHEMA_VERSION` (=2, po.py:245) (po.py:8129-8131, 8230-8232, 8291-8293).
- **Safety-policy pin.** New runs pin at admission (po.py:7967). Legacy resumes are pinned to the current safe policy, never to reconstructed legacy defaults (po.py:8188-8199). The containment-relevant reads in this slice go through `_pinned_safety` (po.py:8541, 8804, 8856). [verifier: only 2 of the 7 pinned policy keys (besides version/origin/pinned_at metadata) are ever read through the pin (`n_forecast_seeds`, `sim_graph_feedback`: po.py:8541, 8804, 8856, 12985, 13082). `simulation_forecast_effect`, `ensemble_extremize_a`, `report_spine_selfconsistency_k`, `sim_typed_feedback_edges` and `sim_interview_graph_feedback` (pinned at po.py:789-799) are read from ambient Config (`backend/app/services/report_agent.py:2386, 2867`; `backend/app/services/forecast_extractor.py:2821, 3251`; `backend/app/services/zep_graph_memory_updater.py:534, 575`; `backend/app/services/zep_tools.py:2156`)]
- **Fork reuse contract.** The base must have a `graph_id`. RESEARCH, ONTOLOGY and GRAPH are pre-marked completed so `_run` reuses them (po.py:8295-8314). Deleting a base that has forks is refused unless `force` is set (po.py:8062-8070).
- **Overlay idempotence.** Re-applying the same overlay to a config that already holds its injections adds nothing (po.py:8438-8456).
- **Ensemble does not mutate the audited deliverable.** It only writes the sidecar `ensemble_forecast.json` (po.py:8723-8738).
- **Ensemble resume idempotence.** A checkpointed seed whose report still has scenarios is not re-run (po.py:8643-8654).
- **Stage timing honesty.** `_complete_stage(reused=True)` never charges resume downtime to a stage (po.py:9031-9037). `_reset_stage_attempt` clears the timing on a real re-execution (po.py:3839-3854).
- **Health gate.** A broken deliverable makes the run `failed`, not `completed` (po.py:9493-9494). The conditions are: all sections placeholders, no forecast, a report under 2000 bytes, or any final-audit hard issue. [verifier: incomplete list: also a missing `report_id` or unresolvable folder (po.py:9169-9174) and any `forecast.quality.hard_issues[]` entry (po.py:9243-9245); the no-forecast rule applies only while `REPORT_STRUCTURED_FORECAST` is on (po.py:9334), and the audit rules only while `REPORT_FINAL_READ_ONLY_AUDIT` is on (po.py:9250)]
- **Final-audit binding.** `full_report.md` and `forecast.json` must hash to the values recorded in `final_audit.json` under audit policy version 3 (po.py:9263-9302).
- **Orphan reclaim is conservative.** It is skipped entirely if the backend port is in use (po.py:7656-7666), and a pipeline is skipped while its owner pid is alive with a fresh heartbeat (po.py:7831-7833).
- **Orphan kill is identity-checked.** The command line must contain both `deerflow_research.py` and the pipeline id (po.py:7860-7863).

---

## Failure modes & recovery

| Failure | Behavior | Recovery | Anchor |
|---|---|---|---|
| Backend killed mid-run | state stays `running`; the next boot's `reconcile_orphans` marks it failed, or salvages it if the report is complete | `POST /resume` | po.py:7672-7731 |
| Backend restarted **within `PIPELINE_HEARTBEAT_STALE_S` (120 s)** of a crash | owner pid is dead but the heartbeat is still fresh → `_orphan_is_dead` returns False → **not reclaimed at boot**; boot reclaim runs only once | `resume` re-checks liveness and reclaims in place once the heartbeat is stale; `cancel` marks it cancelled directly | po.py:7837-7840, 8132-8142, 8008 |
| Second backend started while the first serves the port | the probe detects the busy port and skips reclaim | none needed | po.py:7656-7666 |
| Interrupted during the ensemble, after the report completed | the orphan is salvaged as completed with health degraded and `ensemble_done=True` | — | po.py:7689-7715; po.py:1024-1075 |
| A seed lane fails (sim FAILED/STOPPED, stall, report error) | warning; the seed is skipped; fewer than two valid forecasts means no sidecar and `ensemble_done=True` | none (never retried on resume) | po.py:8690-8691, 8708-8709, 8712-8716 |
| Ensemble aggregation or other unexpected error | propagates to `_run`, which logs a warning; the main report is unaffected; `ensemble_done` is not set, so a resume retries [verifier: wrong recovery: after the warning `_run` proceeds to the health gate and marks the pipeline `completed` (po.py:13336-13346); a plain `resume` refuses completed pipelines (po.py:8143-8151), so the ensemble is only retried via `resume(force=True)` when `pipeline_health` is degraded/failed] | resume | po.py:8717; po.py:13336-13340 |
| Cancel during the ensemble | `PipelineCancelled` → pipeline `cancelled`, even though the main report is complete; the REPORT stage stays completed (XRUN-15) | resume reuses the report and the checkpointed seeds | po.py:8568-8570, 8678-8680; po.py:13359-13369 |
| Main simulation wedged on IPC | the disk watchdog calls `stop_simulation` after `stall_s`; the poll sees STOPPED → RuntimeError → stage failed | resume | po.py:9147-9154 |
| Report deliverable broken | `_enforce_pipeline_health` raises → status failed | resume; the REPORT reuse guard rejects the broken report and regenerates it | po.py:9493-9494; po.py:13213-13222 |
| Completed run with degraded or failed health | resume normally refuses | `resume(force=True)` resets only REPORT | po.py:8143-8165 |
| Health assessment itself throws | warning; no health block; the run is still marked completed [verifier: no *new* block is written, but any `pipeline_health` left by a previous attempt stays in `options` (nothing clears it on resume, po.py:8179-8183), so the completed run can show a stale health verdict] | — | po.py:9490-9492 |
| Telemetry write failure | debug log only | — | po.py:7613-7614 |
| Graph GC failure | warning or debug log only | — | po.py:7803-7806 |
| Overlay application throws (e.g., non-integer `round`) | the caller logs a warning and the **whole overlay is skipped** | fix the overlay and re-fork | po.py:8412; po.py:12855-12871 |

---

## Surprises

1. **Doc-vs-code drift: the ensemble no longer rewrites the primary forecast.**
   - The `_maybe_run_seed_ensemble` docstring says the agreement is "回写主 forecast.json" (po.py:8534-8535).
   - The ORCH-4 comment at the call site says the ensemble's confidence rewrite lands in the health-gated `forecast.json` (po.py:13331-13332).
   - The code writes only a sidecar and explicitly avoids touching `forecast.json` (po.py:8723-8738). The README matches the code ("The primary report and forecast are never rewritten", `README.md:1078`).
2. **Doc-vs-code drift: ensemble default seeds.** `DRF_ARCHITECTURE.md:1354` and `DRF_ARCHITECTURE.md:1685` say `N_FORECAST_SEEDS` defaults to 3. The code defaults to 1 (`backend/app/config.py:303`; Foglamp WP1). The line anchors in `DRF_ARCHITECTURE.md:278-287` are also stale: `_enforce_pipeline_health` is cited as `:4865-4917` but is actually at po.py:9445, and `_spawn_run_stall_watchdog` is cited as `:4533-4579` but is at po.py:9113.
3. **Doc-vs-code drift: `_recompute_dynamic_bands`.** The docstring says research, ontology **and prepare** stay static (po.py:8913). The code re-allocates prepare dynamically with weight 8.0 (po.py:8932-8935).
4. **Suspected: global progress can move backwards.** `_recompute_dynamic_bands` runs again at RUN start with `total_rounds`, which shrinks the graph and prepare bands that were already completed. Example replayed from the formula:
   - with `chunk_count=5`, prepare's band is [44,49];
   - after `total_rounds=200`, prepare becomes [41,42] and RUN starts at 42;
   - so `global_progress` drops from 49 to 42 (po.py:8931-8947, 13039).
5. **Dead parameter.** `section_count` is never passed by any caller, so the report weight is always `6*6` unless an earlier `cost_signals` value exists, and none sets it (po.py:8908, 8923, 8934; callers po.py:12495, 13039).
6. **Dead overlay key.** `as_of_shift` is documented in `fork` (po.py:8284) and the API docstring (`backend/app/api/research.py:224`), but nothing reads it.
7. **Likely bug: calendar mode discards an explicit `round` on injected events.** With `SIM_TEMPORAL_MODE=calendar` (the default, `backend/app/config.py:1067`) and a calendar `temporal_config`, any event without a parseable `date` is forced to round 0, even when the caller gave `round` (po.py:8412-8418). The documented overlay shape `injected_events[{round,poster_name,content}]` has no `date` (po.py:8284).
8. **Suspected: one bad injected event drops the entire overlay.** `int(ev.get("round", 0) or 0)` and `ev.get` on a non-dict are not guarded (po.py:8410-8412). The caller's `except` then skips influence and stance overrides as well (po.py:12870-12871).
9. **Suspected: fork does not carry `research_language`, `depth`, `research_model` or `safety_policy_v1`** (po.py:8315-8320).
   - PREPARE then reads `options.research_language` = None, which is the Config default (po.py:12820), so a fork of an English run may generate personas in a different language than its base.
   - `_pinned_safety` falls back to the ambient Config, which is currently safe.
   - `fork` also does not check the base's status, so a fork can share the handoff directory of a base that is still running (po.py:8288-8296).
10. **Suspected: ensemble checkpoint is not keyed to pipeline or primary report.** The checkpoint lives in `state.handoff_dir`. A fork shares the base's handoff (po.py:8306) and seeds are deterministic (`base_seed + k*7919`, po.py:8567). A fork running the ensemble would therefore load the base's `ensemble_checkpoint.json` and reuse the **base's** seed reports as `resumed_from_checkpoint`. The checkpoint's `pipeline_id` and `primary_report_id` are written but never validated on read (po.py:8589-8597, 8643-8654). Today this is masked by `N_FORECAST_SEEDS=1`.
11. **Suspected: seed lanes skip the main RUN path's safeguards.** Compared with the main RUN path, seed lanes have:
    - no independent disk watchdog: only the inline check, which cannot fire if `get_run_state` blocks;
    - no `_require_run_completion_evidence` (DEFECT-2) and no `_publish_run_summary`; they call `write_run_summary` directly;
    - no `_record_sim_run_telemetry`, so seed subprocess LLM spend is not metered into run telemetry;
    - no `_assess_report_health` on seed reports, so only a truthy `scenarios` admits a forecast;
    - no `ReportManager.save_report`; [verifier: wrong: `ReportAgent.generate_report` itself calls `ReportManager.save_report` (`backend/app/services/report_agent.py:11199, 11267, 11664, 11696`), so the main path's extra save at po.py:13322 is redundant. The real gap is that the seed lane never checks `report.status == FAILED` (main path raises at po.py:13326-13327) and only filters on truthy `scenarios`. Seed lanes also skip the scenario overlay and the calendar world-state seed injection that the main PREPARE applies (po.py:12855-12871, 12878-12911), and do not pass the research artifacts (quantitative/contested/timeline/graph_priors) to ReportAgent (po.py:13302-13311)]
    - no `scenario_label` passed to the seed ReportAgent for forks (po.py:8762-8889 compared with po.py:13001-13175, 13322-13325).

    `README.md:1076` says "Each lane produces a full, gated report". That is true only to the extent the report agent gates itself; the pipeline health gate is not applied to seed reports.
12. **Suspected: the cancel and outage checks are coarse inside seed lanes.** `prepare_simulation` and `generate_report` in a seed get no progress callback (po.py:8790-8799, 8888). A cancel during seed persona generation or report writing is only noticed in the next sim poll loop or after the lane ends. The outage breaker is never checked in the ensemble path. [verifier: `ProviderOutageHalt` is never raised there (its only raise site is po.py:8969), but the process-wide LLM probe still consults the run's breaker on every `LLMClient.chat` call (run context is set per seed at po.py:8640) and fails fast with a RuntimeError once tripped (po.py:623-627); each seed then fails, is skipped with a warning (po.py:8690-8691, 8708-8709), and the pipeline completes instead of halting]
13. **Stale key in the disk watchdog.** `_spawn_run_stall_watchdog` exits early on `rs.get("completed")` (po.py:9142), but `SimulationRunState.to_dict` writes no top-level `completed` key, only `runner_status`, `completed_at` and `twitter_completed`/`reddit_completed` (`backend/app/services/simulation_runner.py:209-244`). Normal termination therefore relies on the caller setting `ctl["stop"]` (po.py:13070).
14. **Dead fallback.** `ReportAgent` already accepts `scenario_spine` (`backend/app/services/report_agent.py:1552`), so the `except TypeError` retry in `_run_one_seed` (po.py:8884-8887) is unreachable for its stated purpose. It would also hide unrelated TypeErrors raised inside `ReportAgent.__init__` by silently dropping the spine.
15. **Dead fallback.** `graph_builder` has no module-level `gc_stale_graphs`, so `_gc_stale_graphs` always takes the `GraphBuilderService(...)` instance fallback (po.py:7790-7794; `backend/app/services/graph_builder.py:2821`).
16. **Effectively no-ops.** `reconcile_orphans` calls `task_manager.complete_task` and `fail_task` on task ids from a previous process. `TaskManager` is an in-memory singleton, so those ids no longer exist and `update_task` silently does nothing (po.py:7705-7714, 7726-7731; `backend/app/models/task.py:54-71, 128-130`).
17. **Suspected (multi-process): `cancel` and `delete_pipeline` treat any `running` pipeline without a local thread as an orphan, with no `_orphan_is_dead` check** (po.py:8007-8016, 8071-8078). By contrast, `resume` uses `_orphan_is_dead` (po.py:8136). In a multi-worker deployment, a live pipeline owned by another worker can be marked cancelled, and `delete_pipeline` can even rmtree it, while it keeps running.
18. **Suspected: graph GC runs while holding `_lifecycle_lock`** (po.py:8055, 8085). Graph enumeration and deletion against the graph DB block concurrent cancel, resume and continue calls. `clean_terminal` repeats GC once for every deleted pipeline (po.py:8100).
19. **Suspected: fork-of-fork edge case.** `_dependent_forks` only finds **direct** children (po.py:8036). A grandchild shares the root's handoff directory (po.py:8306). After the intermediate fork is deleted (allowed once the grandchild's own deps are gone) [verifier: the grandchild's `base_pipeline_id` is the intermediate fork, so the grandchild itself blocks deleting the intermediate (po.py:8036, 8062-8070); the intermediate can only go first with `force=True`, so this edge case needs a forced delete], the root can be deleted and its handoff rmtree'd while the grandchild still points at it.
20. **Mislabel.** `delete_pipeline` returns `status: "not_found"` when `PipelineManager.delete` fails (rmtree runs with `ignore_errors=True`), even though the record existed (po.py:8086; po.py:1199-1201).
21. **Suspected: the dead-letter health signal is graph-scoped, not run-scoped.** The dead-letter file is `_zep_dead_letter/<graph_id>.jsonl` (po.py:9416-9418). Any failed feedback write from another simulation on the same graph (the base, other forks, or seeds) degrades every later run's health until someone replays it.
22. **Suspected: `truncated` is flagged whenever `current_round < total_rounds`** (po.py:9408-9409). This may also catch legitimate early stops, for example convergence stops if they leave `total_rounds` unchanged. Not verified against the runner's early-stop bookkeeping.
23. **Suspected gap: a missing `full_report.md` is not by itself a hard failure.** The size check is `if fr_len and fr_len < 2000` (po.py:9337), and the sha check is skipped when the file is missing (po.py:9285). The failure is caught only indirectly, through a missing or failed final audit. [verifier: if a passing `final_audit.json` is present, a missing `full_report.md` is not caught at all: the markdown sha check is skipped when the file is absent (po.py:9285), `fr_len` is 0 so the size rule does not fire (po.py:9324, 9337), and with sections and forecast present the verdict can be "ok"]
24. **Health-assessment exception swallowing** (po.py:9490-9492). If an assessment helper raises, the run is marked `completed` with no `pipeline_health` block. [verifier: no new block is written, but a block from a previous attempt is never cleared on resume (po.py:8179-8183), so a stale verdict can remain (po.py:9489-9492)] That contradicts the S1 intent of "fail rather than falsely complete" (po.py:9102-9107).
25. **Side effect inside "assessment".** `_enforce_pipeline_health` writes the run-health issues into `stages.run.error` while the run stage stays `completed` (po.py:9460-9461). The UI may then show a completed stage that carries an error.
26. **Forced report regeneration keeps a stale ensemble.** `resume(force=True)` resets REPORT and sets `force_report_regen` but leaves `options.ensemble_done` set (po.py:8159-8165; gate po.py:8548). The new report gets a new `report_id`, but no ensemble runs for it, and the old sidecar in the handoff directory still describes the previous primary report.
27. **Possible lost history.** `_init_telemetry_flush` keeps the prior attempt's base only if `prev.total.calls` is truthy (po.py:7565). If a previous attempt made 0 calls but carried a `cumulative_total` from an even earlier attempt, that cumulative history is dropped on the next attempt.
28. **Unclosed handles.** `open(...)` is used without `with` in `_assess_report_health` (po.py:9180, 9206) and `_assess_run_health` (po.py:9404). There are also redundant local imports of modules already imported at module level (`threading` po.py:9123 vs po.py:40; `glob` po.py:9167 vs po.py:29).
29. **No pipeline-state cleanup on shutdown.** `register_cleanup` only kills research subprocesses (po.py:7888-7908). The pipeline state is left `running`, to be handled by the next boot's reconcile.

---

## Verification

Adversarial pass on 2026-10-11 against the on-disk `main` checkout. The verifier checked the reader's 15 key claims and 16 surprises line by line, then re-read about 40 further anchors from the Walkthrough, Control flow, Config, Failure-mode and Surprises sections. Every cited `po.py` line number that was sampled matches the file (13,492 lines). Inline `[verifier: …]` notes mark each statement found wrong or imprecise.

**Verdict counts (40 verdicts):** 26 confirmed, 13 imprecise, 1 refuted, 0 unverifiable.
- Key claims: 12 confirmed, 3 imprecise.
- Surprises: 14 confirmed, 2 imprecise.
- Other map statements that were flagged: 8 imprecise, 1 refuted. Statements spot-checked and found correct are not counted.

### Non-confirmed items and corrections

1. **Claim: orphan salvage sets `pipeline_health` to degraded (po.py:7689-7715). Imprecise.** `mark_salvaged_completed` downgrades only a missing or "ok" block. An existing "failed" block (for example, one left by an earlier attempt's health gate, which `resume` never clears) stays "failed" (po.py:1044-1050). Salvage also requires a truthy `report_id` (po.py:7750-7752) and that the orphan passes the `_orphan_is_dead` check (po.py:7679).
2. **Claim: what `fork` copies (po.py:8300-8331). Imprecise.** `max_rounds` is taken from the **overlay** and not from the base. The base's own `options.max_rounds` is dropped like the other options (po.py:8327-8331). `scenario_overlay` and `scenario_label` come from the overlay. Only `project_name` and the actor policy come from the base's options.
3. **Claim: `_assess_report_health` failure conditions (po.py:9248-9348). Imprecise.** The no-forecast rule applies only while `REPORT_STRUCTURED_FORECAST` is on (po.py:9334). The audit rules apply only while `REPORT_FINAL_READ_ONLY_AUDIT` is on (po.py:9250). The sha checks run only when the file exists (po.py:9285, 9294). Other hard triggers the claim leaves out: no `report_id` or an unresolvable folder (po.py:9169-9174), `disk_matches_memory`, the publish gate and the structured/scenario contracts (po.py:9272-9284), and `forecast.quality.hard_issues` (po.py:9243-9245). The placeholder rule is at po.py:9175-9193, which is outside the cited range.
4. **Surprise: seed lanes skip main-path safeguards (po.py:8762-8889). Imprecise.** "No `save_report`" is wrong, because `ReportAgent.generate_report` saves the report itself (`backend/app/services/report_agent.py:11199, 11264-11267, 11664, 11696`). The real gaps are these:
   - no `ReportStatus.FAILED` check (the main path checks at po.py:13326-13327);
   - no scenario overlay and no calendar world-state injection (po.py:12855-12871, 12878-12911);
   - no research artifacts passed to ReportAgent (po.py:13302-13311).
   The other listed gaps are confirmed.
5. **Surprise: health-gate gaps (po.py:9337, 9460-9461, 9490-9492). Imprecise.**
   - "No health block" after an assessment exception should read "no *new* block". A previous attempt's `pipeline_health` is never cleared on resume (po.py:8179-8183).
   - A missing `full_report.md` is not caught at all when a passing `final_audit.json` exists (po.py:9285, 9324, 9337).
6. **Map, Purpose item 1: "Each one … spawns a daemon thread". Imprecise.** Only `start`, `resume`, `continue_to_full` and `fork` spawn `_run` threads (po.py:7970-7978, 8202-8210, 8267-8275, 8344-8348).
7. **Map, resume step 5: "The REPORT reuse guard consumes that flag". Imprecise.** The flag is popped only when an existing report survived the health guard (short-circuit `and` at po.py:13224). Otherwise it persists in `options`.
8. **Map, continue_to_full: "A failed precondition raises RuntimeError". Imprecise.** A missing state raises FileNotFoundError, which becomes 404 (po.py:8227-8229; `backend/app/api/research.py:210-211`).
9. **Map, Config table: `PIPELINE_RUN_STALL_S` as the "disk watchdog interval". Imprecise.** It is the stall threshold. The poll interval is a fixed 30 s (po.py:9133, 9147).
10. **Map, Invariants: health-gate condition list. Imprecise.** The list is incomplete; see item 3.
11. **Map, Failure modes: an ensemble error means "a resume retries". Refuted.** The pipeline goes on to be marked `completed` (po.py:13336-13346), and a plain resume refuses completed pipelines (po.py:8143-8151). Only `resume(force=True)` with degraded or failed health re-enters REPORT and the ensemble.
12. **Map, Surprise 12: "The outage breaker is never checked in the ensemble path". Imprecise.** `ProviderOutageHalt` is never raised there (its only raise site is po.py:8969). However, the LLM probe fails fast on a tripped breaker (po.py:623-627) under the per-seed run context (po.py:8640). Seeds then fail and are skipped (po.py:8690-8691, 8708-8709), and the run completes instead of halting.
13. **Map, Surprise 19: fork-of-fork deletion. Imprecise.** The grandchild is itself a dependent of the intermediate fork (po.py:8036, 8062-8070). The scenario therefore needs `force=True` on the intermediate.
14. **Map, Surprise 23: a missing `full_report.md` is "caught only indirectly". Imprecise.** It is not caught when a passing audit exists; see item 5.

Notes on items marked confirmed:
- **Surprise 3 (progress can move backwards).** Replaying the formula reproduces it. With `chunk_count=5`, prepare is [44,49] and run is [49,75]. After `total_rounds=200`, prepare becomes [41,42] and run [42,94]. RUN first reports `upd(2)` against the old band (po.py:12974), then recomputes (po.py:13039), so `global_progress` drops from 49 to 42. Nothing clamps it to be monotonic (po.py:8988-8990, 10294).
- **Surprise 5 (calendar mode forces round 0).** Calendar configs do carry `temporal_config.mode="calendar"` and `round_dates` (`backend/app/utils/sim_timeline.py:73-85`; `backend/app/services/simulation_config_generator.py:796`). Round 0 is a valid 0-based firing round (`backend/scripts/run_parallel_simulation.py:2531-2532`).
- **Surprise 6 (one bad event drops the whole overlay).** Influence and stance edits are made in place on `_cfg`, but `_cfg` is written only after `apply_scenario_overlay_to_config` returns (po.py:12863-12867). An exception therefore discards them as well.
- **Surprise 14 (truncation flag).** A normally completed run is not flagged. `round_end` reports `round_num + 1` (`backend/scripts/run_parallel_simulation.py:5185-5186`), so `current_round == total_rounds` at completion. Whether early stops leave `total_rounds` unchanged was not verified.
- **Surprise 2 (doc drift).** `DRF_ARCHITECTURE.md:1353` also cites a stale range for `_maybe_run_seed_ensemble`: it gives `:7466-7473`, but the method is at po.py:8529.

### Omissions (important behavior the map did not cover)

1. **Salvage bypasses the S1 health gate.** `_orphan_completed_report` checks only for a non-empty `full_report.md` and a non-empty dict `forecast.json` (po.py:7761-7769). A report that `_assess_report_health` would hard-fail is salvaged as completed. Examples are a missing or failed `final_audit.json`, all-placeholder sections, or under 2000 bytes (po.py:7689-7715 vs 9248-9348).
2. **The safety pin is mostly unread.** `capture_safety_policy_v1` pins 7 policy keys plus version/origin/pinned_at metadata (po.py:785-800). Only `n_forecast_seeds` and `sim_graph_feedback` are ever read back through `_pinned_safety` (po.py:8541, 8804, 8856, 12985, 13082). These five keys are pinned but read from ambient Config elsewhere:
   - `simulation_forecast_effect`: `backend/app/services/report_agent.py:2386, 2867`;
   - `ensemble_extremize_a`: `backend/app/services/forecast_extractor.py:2821`;
   - `report_spine_selfconsistency_k`: `backend/app/services/forecast_extractor.py:3251`;
   - `sim_typed_feedback_edges`: `backend/app/services/zep_graph_memory_updater.py:534`;
   - `sim_interview_graph_feedback`: `backend/app/services/zep_graph_memory_updater.py:575` and `backend/app/services/zep_tools.py:2156`.
   The resume warning nevertheless advertises `simulation_forecast_effect` as part of the pinned safe policy (po.py:8191-8198).
3. **Fork ensembles would mix scenarios.** `_run_one_seed` never calls `apply_scenario_overlay_to_config` (po.py:8772-8808). In a fork with `N_FORECAST_SEEDS>1`, the primary lane runs the what-if overlay while the extra seeds run the unmodified base scenario, and their forecasts are pooled together (po.py:8712-8722). This is masked today by the default N=1.
4. **Seed lanes ignore a failed report status.** The seed lane admits a report as soon as its `forecast.json` has scenarios. Unlike the main path (po.py:13326-13327), it never checks `ReportStatus.FAILED` (po.py:8888-8889, 8671-8672).
5. **`force_report_regen` can persist.** The flag is popped only when an existing report survives the guards (po.py:13224). Otherwise it is saved with the state and forces a regeneration on a later, unrelated resume.
6. **Cross-slice:** with `REPORT_TELEMETRY_APPENDIX=true` (default false, `backend/app/config.py:395`), `_run`'s `finally` appends to `full_report.md` *after* the health gate (po.py:13475-13480). That breaks the `markdown_sha256` binding this slice enforces, so the next REPORT reuse guard would reject the report (po.py:9290-9293).
