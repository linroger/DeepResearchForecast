# orch-a — Orchestrator part A: state model, outage breaker, PipelineManager, DeerFlow bridge sync, research budget

Scope: `backend/app/services/pipeline_orchestrator.py` lines 1-2098 (branch `main`, on-disk checkout as of 2026-10-11).
All anchors are `path:line` relative to the repo root; bare `:N` means `backend/app/services/pipeline_orchestrator.py:N`.
Anything outside 1-2098 is cited only to explain how this slice is used.

---

## Purpose & position in the pipeline

This slice is the bottom layer of the 13,492-line orchestrator module. It holds no stage logic. It provides:

1. **Stage vocabulary and progress bands.** Six stage names (`:87-92`) and the global 0-100 bands for each one (`:95-105`).
2. **Run-state model and persistence.** `StageState`/`PipelineState` dataclasses (`:659-758`) and `PipelineManager` (`:860-1221`). `PipelineManager` owns `uploads/pipelines/<id>/pipeline_state.json`: schema versioning and migration, a per-pipeline lock, atomic writes, the heartbeat writer, terminal-state writers used by orphan recovery, the artifact-manifest I/O, delete and list.
3. **Run-level control signals.** `PipelineCancelled` and `ProviderOutageHalt` (`:248-271`) both subclass `BaseException`. The slice also defines the per-run LLM provider-outage circuit breaker (`_RunOutageBreaker`, `:446-523`) and a process-wide monkeypatch probe on `LLMClient.chat` that feeds it (`:597-644`).
4. **Admission-time policy pins.** These are written into `state.options`: `safety_policy_v1` (`:776-800`) and `actor_intelligence_policy_v1` (`:803-852`).
5. **DeerFlow subprocess plumbing.** This covers interpreter detection (`:1229-1245`), process-group kill (`:1248-1263`), and the drift guard `_sync_deerflow_bridge_if_stale` (`:1441-1745`). Before every research launch, the drift guard redeploys the tracked `deerflow_bridge/` sources into the gitignored `deer-flow/` runtime: modules, skills, middlewares, the rendered MCP `extensions_config.json`, and three code overlays.
6. **Graph-ingestion text hygiene.** `_strip_data_uri_images`/`_graph_research_chunks` (`:1274-1338`) are used by the graph stage.
7. **LOOP-007 research tool-budget plumbing.** This covers budget epochs per pipeline task (`:1815-1966`), the pre-spawn exhaustion check (`:1764-1798`), the env contract injected into research children (`:1748-1761`, `:1986-2032`), and DEFECT-2 spend flushing for failed research attempts (`:2035-2096`).

Callers are the `PipelineOrchestrator` class later in the same file (`start` `:7920`, `resume` `:8107`, `fork` `:8280`, `_run` `:11883`, stage methods), the Flask API (`backend/app/api/research.py`, `backend/app/api/sdk.py`), several services, and several scripts (see "Cross-module edges").

---

## Walkthrough (source order)

### Module header and imports (`:1-80`)
- The docstring (`:1-24`) describes the original six-step design: research → ontology → graph → prepare → run → report. In that design DeerFlow runs as a subprocess in its own venv, the orchestrator runs on a background daemon thread, and progress goes both to the global `TaskManager` and to `uploads/pipelines/<id>/pipeline_state.json`.
- Imports (`:26-78`) pull in most of the backend service layer: `GraphBuilderService`, `OntologyGenerator`, `ReportAgent/ReportManager`, `SimulationManager`, `SimulationRunner`, `ZepGraphMemoryManager`, `TextProcessor`, the actor utilities, and `parse_as_of`. Importing this module is therefore heavy.
- `logger = get_logger('mirofish.pipeline')` (`:80`).

### Stage constants and bands (`:87-105`)
- `STAGE_RESEARCH="research"`, `STAGE_ONTOLOGY`, `STAGE_GRAPH`, `STAGE_PREPARE`, `STAGE_RUN`, `STAGE_REPORT` (`:87-92`).
- `STAGE_BANDS` (`:95-102`) gives each stage's global percentage range: research 0-30, ontology 30-40, graph 40-60, prepare 60-72, run 72-92, report 92-100.
- `RESEARCH_ONLY_BANDS = {research: (0,100)}` (`:105`) applies when `mode == "research_only"`.
- Consumers are `start` (`:7941`, which builds `state.stages` from the band keys) and `_global_from_stage` (`:8893-8900`), which maps a stage's local 0-100 into its band. `_recompute_dynamic_bands` (`:8902-8946`) can rescale graph/prepare/run/report into `state.options["dynamic_bands"]`. `backend/scripts/batch_runs.py:65,293` also imports `STAGE_BANDS`.

### Actor-intelligence constants (`:107-240`)
These constants are defined here but consumed by the actor-reception code in other slices (lines ~3144-7177).
- Schema and version strings: `ACTOR_INTELLIGENCE_SCHEMA_VERSION="actor-intelligence/v1"` (`:107`), `ACTOR_INTELLIGENCE_POLICY_VERSION="actor-intelligence-policy/v1"` (`:108`), the lineage filename and schema (`:109-110`), and the graph-seed manifest filename and schema plus the readback schema (`:111-113`).
- `ACTOR_INTELLIGENCE_DIMENSIONS` (`:114-132`) has 17 dimensions. `_ACTOR_BEHAVIOR_READY_FAMILIES` (`:133-145`) groups them into 5 families. [verifier: the 5 families cover only 12 of the 17 dimensions; `operational_preferences`, `alliances`, `opponents_competitors`, `track_record` and `knowledge_state` belong to no family (`backend/app/services/pipeline_orchestrator.py:133-145`)]
- Evidence-sanitizer regexes: `_ACTOR_UNSAFE_EVIDENCE_CONTROL_PATTERNS` (`:150-203`) has 11 prompt-injection patterns (role-switch, "system prompt", ignore/override, exfiltration, tool invocation, "write only…", BEGIN/END UNTRUSTED, markdown role headers). There is also a fragment pattern (`:204-209`), the sentinel `STAGE1BLOCKBOUNDARY<12 hex>` (`:210-212`), and the replacement text (`:147-149`).
- Qualifier and attribute key whitelists (`:213-231`), visibility values (`:232-236`), and the dossier ledger HTML-comment regex `<!-- ACTOR_INTELLIGENCE_LEDGER_V1 {...} -->` (`:237-240`).

### `PIPELINE_SCHEMA_VERSION = 2` (`:245`)
v1 is a legacy file with no `schema_version`. v2 adds an explicit `schema_version` and the `artifacts['run_manifest']` pointer (comment `:242-244`).

### Control-signal exceptions (`:248-290`)
- `PipelineCancelled(BaseException)` (`:248-255`) is a user cancellation. It subclasses `BaseException` so it passes through the many `except Exception` resilience layers in the stages and reaches the cancel handler in `_run`.
- `ProviderOutageHalt(BaseException)` (`:258-271`) is the DEFECT-1 run-level stop. It has the same passthrough rationale. `_run` catches it (`:13377-13380`) and turns it into the existing recoverable `status='failed'` checkpoint through `_halt_for_provider_outage` (`:9766-9793`).
- `IncompatiblePipelineSchema(RuntimeError)` (`:274-290`) is raised by `resume` (`:8131`), `continue_to_full` (`:8232`) and `fork` (`:8293`) when the state file was written by newer code. It carries `pipeline_id` and `file_version`. Its message suggests `PIPELINE_STRICT_SCHEMA=false`. Because it is a `RuntimeError`, the API maps it to HTTP 409 (`backend/app/api/research.py:177-178`, `:212`, `:253`).

### Time and PID helpers (`:293-347`)
- `_utcnow()` (`:293-294`) returns a tz-aware UTC ISO string.
- `_BOOT_ID = uuid4().hex` (`:300`) is a per-process boot id. It is persisted as `owner_boot_id` and compared in `_orphan_is_dead` (`:7828`).
- `_parse_iso(ts)` (`:303-314`) returns `None` on bad input and coerces naive timestamps to UTC.
- `_age_seconds(ts)` (`:317-322`) returns `now - ts`, clamped to ≥0, or `None`.
- `_pid_alive(pid)` (`:325-347`) probes with `os.kill(pid, 0)`. `ProcessLookupError` means dead. `PermissionError` means alive (conservative). Other `OSError`, invalid or ≤0 pid mean dead.

### DEFECT-1 outage breaker (`:350-656`)
- The design comment (`:350-363`): `llm_client` fails fast when its own primary breaker is cooling down and no fallback exists. This breaker aggregates such failures per run. In scope are in-process LLM calls (ontology, graph, prepare, report, and in-process research merge). Research and simulation subprocesses are **not** instrumented. Only their stage-level failures are counted at the orchestrator boundary.
- `_PROVIDER_OUTAGE_FAST_FAIL_PREFIX = "LLM_OUTAGE_HALT"` (`:365`).
- `_PROVIDER_OUTAGE_CONNECTION_MARKERS` (`:369-376`) has 20 lowercase substrings: "apiconnectionerror", "timed out", "econnreset", "getaddrinfo", "sslerror", and others. [verifier: the tuple has 19 entries, not 20 (AST count of `backend/app/services/pipeline_orchestrator.py:369-376`)]
- `_outage_halt_threshold()` (`:379-396`): a non-zero integer in env `LLM_OUTAGE_HALT_CONSECUTIVE` wins. Otherwise it falls back to `Config.LLM_OUTAGE_HALT_CONSECUTIVE` (default 10, `backend/app/config.py:69`); if that attribute is missing, the default is 10. A value ≤0 disables the breaker (`:534-536`).
- `_classify_provider_outage(exc)` (`:399-443`) returns `"auth" | "circuit_breaker" | "quota" | "connection" | None`:
  - It returns `None` for `PipelineCancelled`/`ProviderOutageHalt` (`:407`), for `utils.telemetry.BudgetExceeded` (`:409-414`), for empty text (`:416`), and for the breaker's own fast-fail text starting with `LLM_OUTAGE_HALT` (`:418-419`; this prevents self-feeding).
  - It returns `"auth"` if `llm_client._is_deterministic_auth_error(exc)` (`:428-429`). That helper matches "authenticationerror", 401 patterns and similar (`backend/app/utils/llm_client.py:198-208`).
  - It returns `"circuit_breaker"` if the text contains `熔断冷却`, `circuit-breaker` or `回退提供方不可用` (`:433-434`).
  - It returns `"quota"` if `llm_client._is_quota(exc)`. That helper matches "429", "rate_limit", "rate limit", "quota" or "usage limit" anywhere in the text (`backend/app/utils/llm_client.py:145-149`).
  - It returns `"connection"` if the exception type name contains "connection" or "timeout" (`:437-440`), or if any connection marker matches (`:441-442`).
  - If the `llm_client` helpers cannot be imported, it falls back to the local fingerprints only (`:420-427`).
- `class _RunOutageBreaker` (`:446-523`) is thread-safe through `self._lock`.
  - State: `run_id`, `threshold=max(1,int(threshold))`, `consecutive`, `tripped`, `tripped_at`, `last_reason`, `last_error` (truncated to 300 chars).
  - `record_success()` (`:464-467`) resets `consecutive` **only if not tripped**. Once tripped, the breaker stays tripped for that attempt.
  - `record_provider_failure(exc, reason)` (`:469-488`) is a no-op returning False once tripped. Otherwise it increments the counter. At `consecutive >= threshold` it sets `tripped=True` and `tripped_at` and logs ERROR. It returns True only on the call that trips.
  - `note_failure(exc)` (`:490-495`) classifies the exception and counts only provider-level failures. Non-provider failures neither count nor reset.
  - `fail_fast_message()` (`:497-502`) returns `"LLM_OUTAGE_HALT: run <id> …"`. `halt_message()` (`:504-512`) names `Config.LLM_PROVIDER`, the count, the reason and the last error, and gives the resume route `POST /api/research/<id>/resume`.
  - `snapshot()` (`:514-523`) returns a dict with keys `consecutive_failures, threshold, tripped, tripped_at, reason, last_error`. `_halt_for_provider_outage` persists it into `state.options["provider_outage_halt"]` (`:9780-9786`).
- Registry functions:
  - The registry itself is `_RUN_OUTAGE_LOCK` plus the dict `_RUN_OUTAGE_BREAKERS: run_id → breaker` (`:526-527`).
  - `_register_outage_breaker(run_id)` (`:530-539`) creates a **fresh** breaker per attempt, so counts never carry over between attempts. When the threshold is ≤0 it removes any existing entry and returns `None`.
  - `_outage_breaker_for(run_id)` (`:542-546`) and `_clear_outage_breaker(run_id)` (`:549-551`) are plain lookup and removal.
  - `_current_outage_breaker()` (`:554-577`) resolves the calling thread's breaker in this order:
    1. The telemetry contextvar `get_run_context()[0]` (`backend/app/utils/telemetry.py:62-63`).
    2. If there is no contextvar, the single entry of `active_run_ids()` when exactly one exists (`backend/app/utils/telemetry.py:66-69`).
    3. If still ambiguous, the single registered breaker when exactly one exists.
    4. Otherwise `None`.
  - `_note_provider_stage_failure(run_id, exc)` (`:580-591`) is a best-effort, never-raising feed for subprocess-stage failures. It is called for parallel research-track failures (`:11258`), global synthesis attempts (`:11548`) and synthesis-only recovery attempts (`:10982`).
- `_install_llm_outage_probe()` (`:597-644`) is idempotent and self-healing. It is guarded by `_LLM_PROBE_LOCK` and keyed on the function attribute `_drf_outage_probe`, not on a process flag. It replaces `LLMClient.chat` with `_outage_probed_chat`, which behaves as follows:
  - It passes straight through when `self._is_fallback` is set, because the outer primary call already counts once (`:621-622`). It also passes through when no breaker resolves (`:623-625`).
  - If the breaker is tripped, it raises `RuntimeError(fail_fast_message())` **without making any provider call** (`:626-627`).
  - Otherwise it calls the original. `PipelineCancelled` is re-raised uncounted (`:630-631`). Any other `BaseException` is classified and counted, then re-raised (`:632-634`). Success calls `record_success()` (`:635`).
  - It preserves `__name__/__qualname__/__doc__` and stores the original on `_drf_outage_probe_orig` (`:638-643`).
  - The probe is installed from `_run` only when a breaker was registered (`:11891-11892`). It is never uninstalled in production.
- `_uninstall_llm_outage_probe()` (`:647-656`) is a test helper that restores the original.

### `StageState` (`:659-679`)
- Fields:
  - `name`
  - `status` (the comment `:662` lists pending/running/completed/failed/skipped; `cancelled` is also written, see `:1016`)
  - `progress` (0-100, stage-local)
  - `message`
  - `started_at`
  - `finished_at`
  - `error`
- `from_dict` (`:669-679`) uses tolerant defaults. `progress` is coerced with `int(… or 0)`.

### `PipelineState` (`:682-758`)
The dataclass has 24 fields:
- `pipeline_id`, `prompt`.
- `schema_version` (defaults to `PIPELINE_SCHEMA_VERSION`).
- `mode` (`full`/`research_only`).
- `status` (comment `:689` lists pending/running/completed/failed; the code also writes `cancelled`, e.g. `:13361`, `:8008`).
- `global_progress`, `current_stage`, `task_id`.
- Downstream IDs: `project_id`, `graph_id`, `simulation_id`, `report_id`.
- `handoff_dir`.
- `research_pid`: the in-flight research process-group leader, used by orphan kill.
- `owner_pid`, `owner_boot_id`, `heartbeat_at`: I-4-1 liveness.
- `last_progress_at`: I-5-6 staleness.
- `error`, `created_at`, `updated_at`.
- `options: dict`: the bag for pins, budgets, health, flags.
- `stages: dict[str, StageState]`.
- `artifacts: dict[str, str]`: T6.3 deep-link pointers from stage to handoff-relative file.

Methods:
- `to_dict()` (`:720-722`) is `dataclasses.asdict`, which recursively turns `StageState` into dicts.
- `from_dict()` (`:724-758`) requires `data["pipeline_id"]` (KeyError otherwise). It defaults every other field. A missing `schema_version` becomes 1. Missing timestamps become now. `options` and `artifacts` default to `{}`. **Unknown top-level keys are silently dropped.** The comment at `:726` notes that `safety_policy_v1` rides inside `options`, so it needed no schema bump.

### Foglamp WP1 safety pin (`:761-800`)
- `SAFETY_POLICY_VERSION="safety-policy/v1"` (`:773`).
- `capture_safety_policy_v1(origin)` (`:776-800`) snapshots the current `Config` values:
  - `sim_graph_feedback`, `sim_typed_feedback_edges`, `sim_interview_graph_feedback` (all default False; `config.py:1385-1392`)
  - `n_forecast_seeds` (≥1)
  - `report_spine_selfconsistency_k` (≥1)
  - `ensemble_extremize_a` (falls back to 1.0)
  - `simulation_forecast_effect` (default `"diagnostic_only"`)

  It also records `version`, `origin` and `pinned_at`. `start` writes it as `options["safety_policy_v1"]` with origin `"admission"` (`:7967`). `resume` writes it with origin `"resume_reconstructed_safe"` when the pin is absent (`:8188-8190`). `_pinned_safety` reads it back.

### Actor-plane policy pin (`:803-852`)
- `capture_actor_intelligence_policy_v1(origin, *, required=None)` (`:803-824`) returns `{version, origin, pinned_at, required, schema_version}`. `required` defaults to `Config.DEERFLOW_DUAL_TRACK` (default True).
- `ACTOR_PLANE_UNSUPPORTED_BY_V3 = "research_engine_v3_emits_unsealed_actor_plane"` (`:829`).
- `admission_actor_intelligence_policy_v1()` (`:832-852`) resolves the engine with `resolve_research_engine()`, which is defined later at `:5906` and defaults to `"v3"`. It pins `required = dual_track and engine == "legacy"` and adds `research_engine`. It sets `not_required_reason = ACTOR_PLANE_UNSUPPORTED_BY_V3` when dual-track was requested on a non-legacy engine. This prevents every v3 full run from failing at actor reception after the research spend (IF-2). It is written by `start` (`:7962-7964`).

### `PipelineManager` (`:860-1221`)
All methods are classmethods or staticmethods, and the class is file-backed.
- `_PIPELINE_ID_RE = ^pipe_[A-Za-z0-9_-]+$` (`:865`). `_validate_id` (`:867-872`) also rejects `/`, `\` and `..`, and raises `ValueError`. New IDs are `pipe_<12 hex>` (`:7932`, `:8299`). The comment `:863` refers to a `create()` method, but the method is actually `start` (`:7920`).
- Paths:
  - `_dir(id)` = `Config.PIPELINE_DATA_DIR/<id>` (`:874-877`). `PIPELINE_DATA_DIR = backend/app/../uploads/pipelines` (`backend/app/config.py:1581`).
  - `state_path` → `<dir>/pipeline_state.json` (`:879-881`).
  - `handoff_dir` → `<dir>/handoff` (`:883-885`).
  - `manifest_path` → `<dir>/run.json` (`:914-917`).
  - `artifact_manifest_path` → `<dir>/handoff/manifest.json` (`:1107-1110`).
  - `ensure_dirs` makes `<dir>/handoff` (`:919-921`).
- `resolve_handoff_dir(id)` (`:887-912`) handles forks (T4.6), which share their base's handoff:
  - It returns `state.handoff_dir` when that value is non-empty, differs from the static path, and its realpath lies under `realpath(PIPELINE_DATA_DIR)` according to `os.path.commonpath`.
  - Otherwise, including unreadable state, path escape, or `OSError/ValueError`, it returns the static `handoff_dir(id)`.
  - Invalid IDs still raise `ValueError` through the static call.
- `INCOMPATIBLE_KEY = "__incompatible_schema__"` (`:926`).
- The lock (ORCH-5) is the class-level dict `_state_locks` plus a guard lock (`:933-934`). `_state_lock(id)` (`:936-942`) lazily creates one `threading.Lock` per pipeline. It is **process-local**, so it serializes only this process's writers: the pipeline thread, the heartbeat thread and API threads.
- `save(state)` (`:944-956`): `ensure_dirs`, then it stamps `updated_at` and forces `schema_version = PIPELINE_SCHEMA_VERSION`, then calls `write_json_atomic(state_path, state.to_dict())` under the lock. Each write gets a unique mkstemp name with fsync and `os.replace` (`backend/app/utils/atomic.py:20-44,53-76`). Before that change, all three writers shared one fixed `.tmp` name and raced into `FileNotFoundError`.
- Migrations:
  - `_migrate_v1_to_v2(data)` (`:961-970`) only ensures `artifacts` is a dict.
  - `_migrations()` (`:972-975`) is the table `{1: _migrate_v1_to_v2}`.
  - `_migrate(data, from_version)` (`:977-990`) applies each step in order. If a step is missing it stops early (`break`), but it **still stamps** `schema_version = current`.
- `mark_failed(id, error, status="failed")` (`:992-1021`) is a lock-held read-modify-write on the raw JSON:
  1. It sets `status`, `error` and `updated_at`.
  2. For the current stage, XRUN-15 applies: a stage at ≥100% with no error becomes `completed`; otherwise it gets the same terminal status and the error.
  3. It writes atomically and returns False if the state could not be loaded.

  It is used by `reconcile_orphans` (`:7717`), by cancel of orphan pipelines (`:8008`), by delete (`:8074`) and by resume's dead-orphan reclaim (`:8137-8138`).
- `mark_salvaged_completed(id, note)` (`:1023-1075`) is W9-1. It refuses incompatible sentinels (`:1034`). It sets `status=completed`, `error=None` and `global_progress=100`, and changes `options.pipeline_health` from ok, or from missing, to `degraded`, appending `note` to `issues`. It also sets:
  - `options.ensemble_done = True`, so a later resume does not re-run the seed ensemble
  - `ensemble_skipped = note`
  - `salvaged_orphan_at`
  - report stage → `completed`, 100%, `error=None`, with `finished_at` filled in
  - a report-stage message containing `多种子集成` → rewritten to an honest text
  - `current_stage = report`

  It is used by `reconcile_orphans` (`:7695`).
- `touch_heartbeat(id, pid=None)` (`:1077-1099`) is a lock-held read-modify-write. It returns False (no-op) when the state is missing, incompatible, or `status != "running"`. Otherwise it sets `heartbeat_at = now`, and when `pid` is given also `owner_pid` and `owner_boot_id = _BOOT_ID`. It writes with `fsync=False`. It is called every `PIPELINE_HEARTBEAT_INTERVAL_S` (default 30s) by the heartbeat thread started in `_start_heartbeat` (`:10331-10369`). A False return ends that thread (`:10356-10358`).
- Artifact manifest (I-4-3, for reuse integrity):
  - `load_artifact_manifest` (`:1112-1126`) returns `{}` on a bad id, a missing file, corruption, or a non-dict.
  - `write_artifact_manifest` (`:1128-1133`) uses `write_json_atomic` but takes **no lock**.
- `load(id)` (`:1135-1172`):
  1. A bad id, a missing file, a JSON error or a non-dict returns `None`. [verifier: a non-numeric `schema_version` (e.g. `"v3"` or a list) is not handled: `int(data.get("schema_version") or 1)` sits outside the try, so `load` raises `ValueError`/`TypeError`, which propagates through `list_pipelines` (`:1210`) and aborts the whole `reconcile_orphans` loop (caught only by its outer handler) (`backend/app/services/pipeline_orchestrator.py:1151`, `:7734-7735`)]
  2. If `schema_version > 2` and `Config.PIPELINE_STRICT_SCHEMA` (default True, `config.py:352`), it returns the **sentinel** `{pipeline_id, status, schema_version, __incompatible_schema__: v}`.
  3. If `schema_version > 2` and not strict, it returns the raw data unmigrated.
  4. If `schema_version < 2`, it migrates. If migration throws, it returns the raw data.

  `load` is lock-free. Atomic replace guarantees whole-file reads.
- `is_incompatible(data)` (`:1174-1182`) returns the file version for a sentinel and `None` otherwise. A malformed sentinel returns `PIPELINE_SCHEMA_VERSION + 1`.
- `delete(id)` (`:1184-1201`) runs `shutil.rmtree(<dir>, ignore_errors=True)` and returns whether the directory is gone. A bad id or a missing directory returns False. It takes no lock and does no liveness check; the caller `delete_pipeline` (`:8043`) is responsible for refusing in-flight runs.
- `list_pipelines()` (`:1203-1221`) loads every entry of `PIPELINE_DATA_DIR`. Non-`pipe_*` directories such as `_forecast_ledger` fail `_validate_id`, so `load` returns `None` and they are skipped. It returns `{pipeline_id (dirname), status, prompt, global_progress, created_at, report_id}` sorted by `created_at` descending. This is O(N) full JSON loads plus migrations on every call.

### DeerFlow subprocess helpers (`:1229-1263`)
- `_detect_deerflow_python(deerflow_dir)` (`:1229-1245`) returns a command prefix. The order is:
  1. `[Config.DEERFLOW_PYTHON]` if it is set **and exists**. If it is set but missing, it falls through silently.
  2. `<deerflow>/backend/.venv/bin/python`.
  3. `<deerflow>/.venv/bin/python`.
  4. `["uv","run","--project","<deerflow>/backend","python"]`.

  It is called at `:2251` (research launch) and `:3768`.
- `_kill_process_group(proc, sig=SIGKILL)` (`:1248-1263`) calls `os.killpg(os.getpgid(proc.pid), sig)`. On `ProcessLookupError`/`OSError` it falls back to `proc.kill()`, which always sends SIGKILL. `None` is a no-op. It is used by `DeerFlowResearchRunner.cleanup_all` (SIGTERM, `:2110`) and by the research-run timeout and cancel paths (`:2454`, `:2468`, `:2542`, `:2569`).

### Graph-ingestion hygiene (`:1266-1338`)
- Regexes match Markdown `![alt](data:…)` (`:1268`), HTML `<img … src="data:…">` (`:1269-1270`) and the `alt` attribute (`:1271`).
- `_strip_data_uri_images(text)` (`:1274-1295`) replaces each data-URI image with its alt text, or with nothing for HTML images that have no alt. External-URL images are left untouched. Env `GRAPH_STRIP_DATA_URI_IMAGES` disables this only when it equals `"false"`. Any exception returns the original text.
- `_graph_research_chunks(text, label)` (`:1298-1338`):
  1. It strips data-URI images.
  2. It runs `sanitize_untrusted_research_text` on the **whole** document, so an injection split across a chunk boundary is still caught. The `max_chars` is `len(raw) + (newlines+1)*64`, so no evidence is truncated.
  3. It calls `TextProcessor.split_text(safe, Config.DEFAULT_CHUNK_SIZE (2500), Config.DEFAULT_CHUNK_OVERLAP (250))`.
  4. It wraps each chunk with `delimit_untrusted_research_text(f"{label} chunk i/N", chunk, max_chars=2*len(chunk))`, which adds `BEGIN/END UNTRUSTED RESEARCH DATA` framing (`backend/app/services/actor_role_prompt.py:259-282`).
  5. It drops empty chunks.

  It is called by the graph stage for the report and the dossier (`:12462-12470`).

### DeerFlow bridge deployment (`:1341-1745`)
- Error types:
  - `_DeerFlowSafetyOverlayError(RuntimeError)` (`:1341-1342`): a required overlay could not be enforced.
  - `_DeerFlowSkillSyncError(RuntimeError)` (`:1345-1346`): the skill bundle could not be deployed or verified.
- `_RUNTIME_SKILL_SYNC_HELPER_PATH` (`:1349-1351`) is an absolute path to `deerflow_bridge/runtime_skill_sync.py`. It is computed **at import** from this module's `__file__`.
- `_DEPLOYED_BRIDGE_MODULES` (`:1359-1362`) lists `market_tools.py, search_tools.py, cached_fetch.py, research_budget.py, linear_research.py, research_gateway.py`. The deployed `deerflow_research.py` imports these by bare name. The parity test against `setup.sh`'s loop is `backend/tests/test_deerflow_bridge_sync_guard.py:224-235`; `setup.sh:597` additionally copies `runtime_skill_sync.py`.
- Template tokens are `{{DRF_REPO_ROOT}}` and `{{DRF_BACKEND_PYTHON}}` (`:1368-1369`). The template `deerflow_bridge/extensions_config.json` uses them in `command` and `PYTHONPATH` (`deerflow_bridge/extensions_config.json:7,13,26,32`).
- `_mcp_backend_python(repo_root)` (`:1372-1376`) returns `sys.executable`, falling back to `<repo>/backend/.venv/bin/python`.
- `_render_bridge_extensions_config(src, repo_root)` (`:1379-1407`) loads the JSON and substitutes the tokens recursively in string values, so paths with quotes or backslashes stay valid JSON. It dumps with `indent=2` plus a trailing newline. Any leftover `{{…}}` raises `ValueError`. It returns bytes.
- `_deploy_rendered_extensions_config(rendered, dst)` (`:1410-1438`) returns False when `dst` already holds identical bytes. Otherwise it stages through `mkstemp(prefix=".extensions_config.", suffix=".tmp", dir=dirname(dst))`, then writes, `chmod 0644` and `os.replace`. It unlinks the temp file on any `BaseException`. It does not fsync. It returns True when written.
- **`_sync_deerflow_bridge_if_stale(deerflow_dir) -> dict`** (`:1441-1745`). It returns the skill-sync result dict, which `_run_attempt` forwards to the child as env `DRF_RUNTIME_SKILL_SYNC_REQUIRED=1` plus the JSON `DRF_RUNTIME_SKILL_SYNC` (`:2308-2319`). The steps are:
  1. `repo_root` is three directory levels above this file (`:1460`). `bridge_dir = <repo>/deerflow_bridge`.
  2. A missing `deerflow_bridge/deerflow_research.py` or `<deerflow>/deerflow_research.py` raises `_DeerFlowSkillSyncError` (`:1464-1467`). The guard therefore cannot bootstrap a fresh `deer-flow/`; `setup.sh` must run first.
  3. A missing helper raises `_DeerFlowSkillSyncError` (`:1473-1476`).
  4. **Skill sync** (`:1477-1497`): it loads the helper through `importlib.util.spec_from_file_location`, a fresh exec each call, and calls `sync_runtime_skills(<bridge>/skills, <deerflow>/skills/public, required_skills=DEFAULT_REQUIRED_SKILLS)`. The required skills are `actor-ontology-research, deep-research, forecast-visuals, prediction-markets` (`deerflow_bridge/runtime_skill_sync.py:46-51`). The helper takes the `fcntl.flock` cross-process lock `<deerflow>/skills/.drf-runtime-skill-sync.lock` (60s timeout, `deerflow_bridge/runtime_skill_sync.py:42,246-270,405-422`). It stages and verifies, then atomically swaps `skills/public`, and writes `.drf-runtime-skill-manifest.json`. Any exception is re-raised as `_DeerFlowSkillSyncError`. The outcome (`verified`/`updated`), the manifest hashes, the deployed path and the lazy-resource hashes are logged at INFO (`:1499-1510`).
  5. It builds copy pairs (`:1516-1551`):
     - the bridge entry script
     - the helper → `<deerflow>/runtime_skill_sync.py`
     - each existing `_DEPLOYED_BRIDGE_MODULES` source
     - every `deerflow_bridge/patches/middlewares/*.py` → `<deerflow>/backend/packages/harness/deerflow/agents/middlewares/`, sorted, and only if both directories exist
  6. **extensions_config.json** (`:1556-1578`). If rendering fails with `OSError`/`ValueError`, it logs WARNING and **removes** the deployed copy, which disables the KG MCP wiring at `:2414-2422`. If the deploy fails with `OSError`, it logs WARNING and leaves the old copy. A successful write adds `extensions_config.json` to `synced`.
  7. **Content-hash copy loop** (`:1579-1591`). It skips a pair when `dst` exists and `sha256(src) == sha256(dst)`. Otherwise it runs `makedirs` plus `shutil.copyfile`, which is non-atomic and unlocked. A copy failure on the helper raises `_DeerFlowSkillSyncError`. Any other copy failure re-raises the original exception, which then hits the generic handler (step 12). [verifier: the generic handler is described in step 13, not step 12; such an exit also skips the lead-agent overlay (step 8), not only the subagent overlay (`backend/app/services/pipeline_orchestrator.py:1590`, `:1599-1635`, `:1739-1745`)]
  8. **Lead-agent overlay** (LOOP-010, `:1599-1635`) runs only if the target `…/agents/lead_agent/agent.py` exists. A missing overlay script raises `_DeerFlowSafetyOverlayError`. It execs `patches/apply_lead_agent_overlays.py:apply(deerflow_dir)`. An exception there, or a status other than `applied`/`already_applied` (for example `missing`), raises `_DeerFlowSafetyOverlayError`. `applied` adds the target to `synced`.
  9. **Model-factory overlay** (`:1641-1659`) runs only if `patches/apply_model_factory_overlays.py` exists. It is treated as **optional**: a status other than `applied` is ignored, and exceptions are **not** retyped, so they reach the generic handler. This overlay strips the local `context_window_tokens` metadata from provider kwargs.
  10. **Subagent overlay** (`:1668-1716`) runs only if all three targets exist: `client.py`, `tools/builtins/task_tool.py` and `subagents/executor.py`. It follows the same strict rules as the lead-agent overlay.
  11. **config.yaml** (`:1721-1728`) is a drift **warning only**. It is never copied, which matches `setup.sh`'s never-clobber rule (`setup.sh:704-711`).
  12. If anything was synced, it logs WARNING telling the operator to re-run `./setup.sh` (`:1729-1734`). It returns `skill_sync_result`.
  13. Exception policy:
      - `_DeerFlowSafetyOverlayError` and `_DeerFlowSkillSyncError` are logged at ERROR and re-raised (`:1736-1738`). Research launch is refused (fail closed).
      - Any other exception is logged at WARNING. It becomes `_DeerFlowSkillSyncError` only if skill sync had not yet produced a result. Otherwise the function **returns the result and research proceeds** (`:1739-1745`).

  Call sites:
  - `DeerFlowResearchRunner._run_attempt` (`:2211`), on every research subprocess launch
  - the parallel-lane stage, once before admitting lanes (`:11116`)
  - synthesis-only recovery (`:10856`)

### Research budget, LOOP-007 (`:1748-2032`)
- `_RESEARCH_BUDGET_ENV_KEYS` (`:1748-1761`) lists 12 env names: `RESEARCH_BUDGET_{DB,TELEMETRY_PATH,LANE_ID,RUN_ID,EPOCH,ATTEMPTS_GLOBAL,SEARCH_GLOBAL,SEARCH_LANE,FETCH_GLOBAL,FETCH_LANE}` and `RESEARCH_NEGATIVE_CACHE_{TTL_SECONDS,RETRIES}`.
- `_research_budget_exhaustion(telemetry_path, expected_epoch=None) -> Optional[str]` (`:1764-1798`):
  - It reads the JSON snapshot. On `OSError`, `TypeError`, `ValueError` or a non-dict it returns `None`.
  - If `expected_epoch` is given and differs from `payload["epoch"]`, it returns `None`, so stale snapshots are ignored.
  - It checks, in order, `attempts_global↔global.attempts`, `search_global↔global.search_network`, `fetch_global↔global.fetch_network`. It returns the first limit name where `limit > 0 and count >= limit`.
  - Lane caps are not checked. The key names match the bridge exporter (`deerflow_bridge/research_budget.py:275-280,305,1348-1395`).
- `_budget_epoch_slug(value)` (`:1801-1803`) keeps `[A-Za-z0-9._-]`, strips `-` and `.` from the ends, defaults to `"task"` and caps at 80 chars.
- `_research_budget_attempt_ids(state)` (`:1806-1812`) returns the set of `epoch` strings in `options["research_budget_epochs"]`. Callers pass it as `expected_attempt_ids` for checkpoint-lineage validation (`:5709`, `:11191`, `:12010`).
- **`_activate_research_budget_epoch(state, handoff_dir) -> (db_path, telemetry_path, epoch)`** (`:1815-1923`) works as follows:
  1. `task_id = state.task_id or "initial-<pipeline_id>"` (`:1831-1833`).
  2. It makes `<handoff>/research_budget_epochs/`. `history = options.setdefault("research_budget_epochs", [])`, replaced with a new list if it is not a list (`:1834-1839`).
  3. **Re-entry**: if a history row has the same `task_id` and a non-empty `db_path`, it returns that row's paths and epoch with no write and no save (`:1840-1849`).
  4. **Cap**: `max_epochs = max(1, Config.RESEARCH_BUDGET_MAX_EPOCHS or 3)` (`config.py:543-544`). If `len(history) >= max_epochs` it raises `RuntimeError("research budget epoch limit reached; … increase RESEARCH_BUDGET_MAX_EPOCHS only with explicit cost approval")` (`:1851-1856`).
  5. Otherwise `ordinal = len+1` and `epoch = task_id`, and it makes `epoch_dir = <root>/epoch-{ordinal:03d}-{slug(task_id)}` (`:1858-1862`).
  6. If `<handoff>/research_budget.json` exists, it copies the file aside (`:1863-1879`). With a previous row, it goes to `<prev.epoch_dir>/final_research_budget.json` and sets `prev["telemetry_archive"]`. Without one, it goes to `<new epoch_dir>/legacy_research_budget.json` and sets `options["legacy_research_budget_telemetry"]`. An `OSError` becomes `RuntimeError`.
  7. `db_path = <epoch_dir>/research_budget.sqlite3`. It appends the row `{ordinal, epoch, task_id, epoch_dir, db_path, telemetry_path, created_at}` and sets `options["research_budget_epoch"] = row`. If a legacy root `<handoff>/research_budget.sqlite3` exists, it records `options["legacy_research_budget_db"]` (`:1881-1895`).
  8. It writes a fresh snapshot with `write_json_atomic(<handoff>/research_budget.json, …)`. The snapshot has `schema_version 1, run_id, epoch, created_at/updated_at` (epoch seconds), `degraded False`, `tool_budget_enabled True`, `limits{attempts_global 1800, search_global 900, search_lane 360, fetch_global 450, fetch_lane 180}`, `global {}` and `lanes {}` (`:1897-1921`).
  9. `PipelineManager.save(state)` (`:1922`).

  Callers are the parallel-lane path (`:11102`) and the single-track path (`:12037`). Each one immediately checks `_research_budget_exhaustion` and raises `research_budget_exhausted before track launch …` if a cap is saturated (`:11104-11110`, `:12038-12045`).
- `_synthesis_recovery_budget_epoch(state, handoff_dir)` (`:1926-1966`) reuses the **current** epoch instead of opening a new one when all of these hold:
  - `options["synthesis_recovery"]` has `attempted is True` and `passed is False`
  - `options["research_budget_epoch"]` is a dict with a non-empty `db_path`, `telemetry_path` and `epoch`
  - `_research_budget_exhaustion(telemetry, epoch)` is `None`

  In that case it records `options["synthesis_recovery_budget_reused"] = {epoch, ordinal, reused_at, reason}` and saves. Otherwise it delegates to `_activate_research_budget_epoch`. The caller is synthesis-only recovery (`:10875`).
- `_SYNTHESIS_PROVIDER_UNAVAILABLE_MARKERS` (`:1969-1978`) and `_synthesis_provider_unavailable(error)` (`:1981-1983`) do a case-folded substring test. The markers include `"modelprovidersunavailable"`, `"rate limit"`, `"token plan"`, `"quota exhausted"`, `"2056"` and `"no auth available"`. The caller (`:10980`) uses the result to stop the second synthesis-only attempt (`:10995-11000`).
- `_configure_research_budget_env(env, handoff_dir, *, budget_db_path, budget_lane_id, budget_telemetry_path, budget_run_id, budget_epoch)` (`:1986-2032`) mutates the child env dict in place:
  - When `Config.RESEARCH_BUDGET_ENABLED` is False, it pops all 12 keys and returns.
  - Otherwise it sets the following and pops any that are absent:
    - `RESEARCH_BUDGET_DB`: given path, default `<handoff>/research_budget.sqlite3`
    - `RESEARCH_BUDGET_TELEMETRY_PATH`: default `<handoff>/research_budget.json`
    - `RESEARCH_BUDGET_LANE_ID`: default `outer-track-1`
    - `RESEARCH_BUDGET_RUN_ID` and `RESEARCH_BUDGET_EPOCH`
    - the five caps and two negative-cache knobs, taken from `Config`
  - The caller (`:2379-2387`) may then override `RESEARCH_BUDGET_RUN_ID/LANE_ID/EPOCH` and `RESEARCH_CHECKPOINT_ID` for an explicit checkpoint resume (`:2388-2403`).

### Failed-attempt spend flush, DEFECT-2 (`:2035-2096`)
- `_flush_failed_research_attempt_spend(spend, attempt_status, run_id=None) -> bool`:
  - It returns False if `spend` is not a dict or is already flushed.
  - It sets `spend["flushed"] = True` **first**. This is the idempotency latch, even when nothing is recorded.
  - It returns False when `tokens_in` and `tokens_out` are both ≤0, or when `Config.LLM_TELEMETRY_ENABLED` is false.
  - Otherwise it calls `LLMMeter.record` with:
    - `provider = "claude-cli" if model in ("claude","codex") else model`, the same mapping as `_record_research_telemetry` (`:10430+`)
    - `model = spend.model` or `Config.DEERFLOW_MODEL` (default `'claude'`)
    - `latency_ms = (now - t_start)*1000`
    - `stage="research"`
    - `run_id` (when `None`, the meter falls back to the contextvar or the single active run; `backend/app/utils/telemetry.py:231-243`)
  - It logs a WARNING with the status and token counts, including `cached`, which the meter has no field for, and returns True.
  - Any exception logs at DEBUG and returns False, so it never amplifies the original failure.
- The caller is `DeerFlowResearchRunner.run` (`:2113-2140`). It allocates `spend`, calls `_run_attempt(…, _spend=spend)`, and flushes only on exception exits: `"cancelled"` for `PipelineCancelled` and `"failed(<ExcType>)"` for any other `BaseException`. Successful attempts are billed by the caller through `_record_research_telemetry`, so nothing is counted twice.

---

## Control flow

1. **Admission.** `PipelineOrchestrator.start` (`:7920-7980`) does the following:
   - generates `pipe_<12hex>` (`:7932`) and calls `PipelineManager.ensure_dirs` (`:7933`)
   - builds `stages` from `STAGE_BANDS`/`RESEARCH_ONLY_BANDS` (`:7941-7942`)
   - pins `actor_intelligence_policy_v1` (`:7962-7964`) and `safety_policy_v1` (`:7967`), then saves (`:7968`)
   - spawns the `_run` thread
2. **Attempt start.** `_run` (`:11883`) does the following:
   - calls `set_run_context(pipeline_id)` (`:11888`)
   - calls `_register_outage_breaker` and, if that returns a breaker, `_install_llm_outage_probe` (`:11891-11892`)
   - initializes telemetry and writes `run.json`
   - calls `_start_heartbeat` (`:10331-10369`), which stamps `owner_pid`, `owner_boot_id` and `heartbeat_at` in memory and starts a daemon thread that calls `PipelineManager.touch_heartbeat` every 30s
3. **Every progress callback.** `_make_stage_updater.update` (`:8958-9003`) does the following:
   - raises `PipelineCancelled` if the cancel event is set
   - raises `ProviderOutageHalt(breaker.halt_message())` if the run's breaker is tripped (`:8967-8969`)
   - updates the stage, `last_progress_at` and in-memory `heartbeat_at`, and `global_progress` through `_global_from_stage`
   - calls `PipelineManager.save(state)`
4. **In-process LLM calls.** Every `LLMClient.chat` goes through the probe, which counts failures and resets on success (`:620-636`). After a trip, calls fail fast with `LLM_OUTAGE_HALT…`. The next progress callback raises the halt. `_run` catches it (`:13377-13380`) and calls `_halt_for_provider_outage`, which sets `status=failed`, fills `options.provider_outage_halt`, fails the current stage, and saves (`:9766-9793`). The `_run` `finally` (`:13393+`) stops the heartbeat and calls `_clear_outage_breaker` (`:13488`).
5. **Research stage, legacy parallel lanes.** The sequence is:
   1. `_activate_research_budget_epoch` (`:11102`)
   2. `_research_budget_exhaustion` (`:11104`)
   3. `_sync_deerflow_bridge_if_stale` (`:11116`)
   4. per lane, `DeerFlowResearchRunner.run` → `_run_attempt`, which syncs again (`:2211`), detects the interpreter (`:2251`), configures the budget env (`:2379`), spawns, and sends skill-sync telemetry to the child (`:2308-2319`)
   5. on a lane exception, `_note_provider_stage_failure` (`:11258`)
   6. on an attempt exception, `_flush_failed_research_attempt_spend` (`:2134-2140`)

   The single-track path activates its epoch at `:12037-12045`. Global synthesis failures feed the breaker at `:11548`.
6. **Synthesis-only recovery.** The sequence is `_sync…` (`:10856`), then `_synthesis_recovery_budget_epoch` (`:10875`), then the exhaustion check (`:10877-10883`). Each failed attempt feeds `_synthesis_provider_unavailable` (`:10980`) and `_note_provider_stage_failure` (`:10982`).
7. **Graph stage.** `_graph_research_chunks(report_md, "Stage 1 research report")` and the matching call for the dossier (`:12462-12470`).
8. **Backend start.** `create_app` → `PipelineOrchestrator.reconcile_orphans` (`backend/app/__init__.py:140`; `:7637-7736`). For each `running` pipeline from `list_pipelines()` not in `_threads`: [verifier: reconciliation is skipped entirely when the Flask port (env `FLASK_PORT`, default 5001) already accepts connections, gated by `PIPELINE_RECLAIM_PORT_PROBE` (`backend/app/services/pipeline_orchestrator.py:7656-7668`); `_orphan_is_dead` runs only when `PIPELINE_HEARTBEAT_ENABLED`, otherwise every listed orphan is treated as dead (`:7679`); salvage is gated by `PIPELINE_SALVAGE_COMPLETED_ORPHANS` (`:7689`)]
   - `_orphan_is_dead` (`:7809-7840`) decides liveness using `_BOOT_ID`, `_pid_alive` and `_age_seconds` on `heartbeat_at`/`updated_at`, against `PIPELINE_HEARTBEAT_STALE_S=120`.
   - A dead run with a completed report is salvaged with `mark_salvaged_completed` (`:7695`). Any other dead run gets `mark_failed` (`:7717`).
9. **Resume, continue and fork.** `load` → `is_incompatible` → raise `IncompatiblePipelineSchema` (`:8130-8131`, `:8232`, `:8293`). Resume pins a `safety_policy_v1` if one is missing (`:8188-8190`).
10. **API reads.** The API reads through `PipelineManager.load`, `list_pipelines` and `resolve_handoff_dir` (`backend/app/api/research.py:151,314,339,392,502,562,…`).

---

## Data & artifacts

**On disk.** `Config.PIPELINE_DATA_DIR` = `backend/uploads/pipelines/` (`backend/app/config.py:1581`).

| Path | Writer (anchor) | Format / key fields |
|---|---|---|
| `<id>/pipeline_state.json` | `save` `:956`, `mark_failed` `:1020`, `mark_salvaged_completed` `:1074`, `touch_heartbeat` `:1098` (fsync=False) | JSON of `PipelineState.to_dict()` (24 fields, see `:682-718`); `schema_version: 2`; `stages{name→StageState}`; `options{…}`; `artifacts{stage→relpath}` |
| `<id>/run.json` | path only here (`:914-917`); written by `_write_run_manifest` (`:10374+`) | run reproducibility manifest (I-8-1) |
| `<id>/handoff/` | `ensure_dirs` `:919-921` | stage-to-stage handoff directory; forks point `state.handoff_dir` at the base's directory |
| `<id>/handoff/manifest.json` | `write_artifact_manifest` `:1128-1133` | I-4-3 artifact integrity manifest (sha256/bytes/stage/schema_ok per artifact, per the comment `:1102-1104`) |
| `<id>/handoff/research_budget.json` | `_activate_research_budget_epoch` `:1899-1921`, then the bridge exporter (`deerflow_bridge/research_budget.py:1348+`) | `{schema_version, run_id, epoch, created_at, updated_at, degraded, tool_budget_enabled, limits{…}, global{attempts, search_network, fetch_network}, lanes{…}}` |
| `<id>/handoff/research_budget_epochs/epoch-NNN-<slug>/research_budget.sqlite3` | path assigned `:1881`; opened by the bridge child through env `RESEARCH_BUDGET_DB` | SQLite tool-budget ledger (authoritative for admission) |
| `…/epoch-NNN-<slug>/final_research_budget.json` | `:1866-1871` (archived into the **previous** epoch dir) | copy of the prior snapshot |
| `…/epoch-NNN-<slug>/legacy_research_budget.json` | `:1866-1871` (when no previous row) | copy of the pre-epoch snapshot |
| `<id>/handoff/research_budget.sqlite3` | legacy root ledger; detected `:1893-1895`; default DB when no path is passed `:2007` | SQLite |
| `<deerflow>/deerflow_research.py`, `runtime_skill_sync.py`, the 6 bridge modules | `_sync_deerflow_bridge_if_stale` copy loop `:1579-1591` | byte copies of the `deerflow_bridge/` sources |
| `<deerflow>/backend/packages/harness/deerflow/agents/middlewares/*.py` | `:1541-1551` | byte copies of `deerflow_bridge/patches/middlewares/*.py` |
| `<deerflow>/extensions_config.json` | `_deploy_rendered_extensions_config` `:1410-1438` | rendered MCP server registry (opt-in through `DEER_FLOW_EXTENSIONS_CONFIG_PATH`) |
| `<deerflow>/skills/public/` (+ `.drf-runtime-skill-manifest.json`), `<deerflow>/skills/.drf-runtime-skill-sync.lock` | `runtime_skill_sync.sync_runtime_skills` (called `:1489`) | atomically swapped skill tree plus manifest |
| `<deerflow>/…/lead_agent/agent.py`, `models/factory.py`, `client.py`, `tools/builtins/task_tool.py`, `subagents/executor.py` | overlays applied in-process `:1622`, `:1655`, `:1701` | vendor files modified in place by the tracked overlay scripts |

**In-memory structures.**
- `_RUN_OUTAGE_BREAKERS: dict[run_id, _RunOutageBreaker]` plus `_RUN_OUTAGE_LOCK` (`:526-527`).
- The patched `LLMClient.chat`, which carries `_drf_outage_probe` and `_drf_outage_probe_orig` (`:641-643`).
- `PipelineManager._state_locks: dict[pipeline_id, Lock]` (`:933`). It is never pruned.
- `_BOOT_ID` (`:300`).
- The DEFECT-2 `spend` tally: `{tokens_in, tokens_out, tokens_total, tokens_cached, t_start, model, flushed}` (`:2124-2129`).

**`state.options` keys written in this slice:**
- `research_budget_epochs` (list of rows), `research_budget_epoch` (current row), `legacy_research_budget_telemetry`, `legacy_research_budget_db`, `synthesis_recovery_budget_reused`
- `pipeline_health`, `ensemble_done`, `ensemble_skipped`, `salvaged_orphan_at`
- through the pin helpers: `safety_policy_v1`, `actor_intelligence_policy_v1`

---

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `LLM_OUTAGE_HALT_CONSECUTIVE` (env, read directly and through Config) | 10 | consecutive provider-level failures before the breaker trips; ≤0 disables | `:379-396`, `backend/app/config.py:69` |
| `LLM_PROVIDER` | `claude-cli` | named in the halt message only | `:505`, `config.py:750` |
| `PIPELINE_STRICT_SCHEMA` | True | when on, newer-schema state files load as a sentinel (409 path); when off, they are read raw | `:1156`, `config.py:352` |
| `PIPELINE_DATA_DIR` (Config constant, not env) | `backend/uploads/pipelines` | root of all pipeline directories | `:877`, `config.py:1581` |
| `PIPELINE_HEARTBEAT_ENABLED` / `_INTERVAL_S` / `_STALE_S` | true / 30 / 120 | heartbeat thread cadence and orphan staleness (consumers of `touch_heartbeat` and `_age_seconds`) | `config.py:457-459`, `:10339-10348`, `:7670-7671` |
| `DEERFLOW_DIR` | `<repo>/deer-flow` | target of the bridge sync and of script lookup | `config.py:1148-1151`, `:2205-2211` |
| `DEERFLOW_PYTHON` | unset | explicit DeerFlow interpreter (used only if the path exists) | `:1234`, `config.py:1153` |
| `DEERFLOW_MODEL` | `claude` | model and provider label for spend flush | `:2070`, `config.py:1156` |
| `DEERFLOW_DUAL_TRACK` | True | actor-plane `required` pin (legacy engine only) | `:820`, `:844`, `config.py:1228` |
| `RESEARCH_ENGINE` | `v3` | engine for the actor policy pin (via `resolve_research_engine`) | `:843`, `:5906-5933`, `config.py:1187` |
| `SIM_GRAPH_FEEDBACK`, `SIM_TYPED_FEEDBACK_EDGES`, `SIM_INTERVIEW_GRAPH_FEEDBACK` | false | snapshotted into `safety_policy_v1` | `:789-792`, `config.py:1385-1392` |
| `N_FORECAST_SEEDS` | 1 | snapshotted (≥1) | `:793`, `config.py:303` |
| `REPORT_SPINE_SELFCONSISTENCY_K` | 1 | snapshotted (≥1) | `:794-795`, `config.py:329` |
| `ENSEMBLE_EXTREMIZE_A` | 1.0 | snapshotted (0 is coerced to 1.0) | `:796`, `config.py:333` |
| `SIMULATION_FORECAST_EFFECT` | `diagnostic_only` | snapshotted | `:797-799`, `config.py:1492-1494` |
| `GRAPH_STRIP_DATA_URI_IMAGES` (env only) | `true` | `"false"` disables data-URI image stripping before graph chunking | `:1284` |
| `DEFAULT_CHUNK_SIZE` / `DEFAULT_CHUNK_OVERLAP` | 2500 / 250 | graph episode chunking | `:1325-1326`, `config.py:1055-1057` |
| `RESEARCH_BUDGET_ENABLED` | true | false strips the 12 budget env keys from the child (epochs are **still** activated and capped) | `:2002-2005`, `config.py:528-529` |
| `RESEARCH_BUDGET_MAX_EPOCHS` | 3 | hard cap on budget epochs (one per pipeline task id) | `:1851-1856`, `config.py:543-544` |
| `RESEARCH_BUDGET_ATTEMPTS_GLOBAL` / `SEARCH_GLOBAL` / `SEARCH_LANE` / `FETCH_GLOBAL` / `FETCH_LANE` | 1800 / 900 / 360 / 450 / 180 | snapshot limits and child env | `:1908-1917`, `:2019-2028`, `config.py:530-539` |
| `RESEARCH_NEGATIVE_CACHE_TTL_SECONDS` / `_RETRIES` | 600 / 1 | child env | `:2029-2032`, `config.py:545-548` |
| `LLM_TELEMETRY_ENABLED` | True | gates the DEFECT-2 spend flush | `:2061`, `config.py:58` |
| Child env exported by this slice | — | `RESEARCH_BUDGET_DB/TELEMETRY_PATH/LANE_ID/RUN_ID/EPOCH` plus caps; `DRF_RUNTIME_SKILL_SYNC(_REQUIRED)` comes from the sync result | `:2006-2032`, `:2308-2319` |

---

## External calls

- **LLM / provider.** This slice makes no direct LLM call. It **monkeypatches** `backend/app/utils/llm_client.LLMClient.chat` process-wide (`:618-643`). A tripped breaker short-circuits the provider call (`:626-627`).
- **Telemetry.** `LLMMeter.record` (local accounting) at `:2079-2087`. It also reads `get_run_context` and `active_run_ids` (`:565-569`) and `BudgetExceeded` (`:410`).
- **Signals and processes.** `os.kill(pid, 0)` (`:340`); `os.killpg(os.getpgid(pid), sig)` and `proc.kill()` (`:1258-1261`). The command prefix for the DeerFlow subprocess comes from `_detect_deerflow_python` (`:1229-1245`), including `uv run --project …` as a fallback. The `Popen` itself happens outside the slice (`_run_attempt`, `:2143+`).
- **In-process code execution of tracked bridge scripts.** These are loaded through `importlib.util.spec_from_file_location`:
  - `deerflow_bridge/runtime_skill_sync.py:sync_runtime_skills` (`:1482-1493`)
  - `deerflow_bridge/patches/apply_lead_agent_overlays.py:apply` (`:1614-1622`)
  - `apply_model_factory_overlays.py:apply` (`:1647-1655`)
  - `apply_subagent_overlays.py:apply` (`:1693-1701`)

  Each one modifies files under `deer-flow/`.
- **Filesystem.** Atomic JSON writes through `backend/app/utils/atomic.write_json_atomic`; `shutil.copyfile`, `shutil.copy2`, `shutil.rmtree`; `tempfile.mkstemp`.
- **Network, HTTP and DB.** There are none directly. The SQLite ledger paths are only assigned here; the bridge child opens them.

---

## Cross-module edges

**Callers into this slice (from grep):**
- Same module:
  - `start` (`:7932-7968`); `cancel` (`:8008`); `delete_pipeline` (`:8074`); `resume` (`:8125-8200`); `continue_to_full` (`:8232`); `fork` (`:8293-8350`)
  - `reconcile_orphans` / `_orphan_is_dead` (`:7637-7840`); `_global_from_stage` (`:8893-8900`); `_make_stage_updater` (`:8958-9003`); `_halt_for_provider_outage` (`:9766-9793`); `_start_heartbeat` (`:10331-10369`)
  - research stage (`:10845-12045`); graph stage (`:12462-12470`); `_run` (`:11883-13492`)
  - `DeerFlowResearchRunner` (`:2099+`); `_parse_iso` used at `:3818-3829`
- `backend/app/api/research.py`:
  - `PipelineManager.load`: `:151`, `:188`, `:227`, `:314`, `:703`, `:782`, `:882`
  - `list_pipelines`: `:339`
  - `resolve_handoff_dir`: `:392`, `:502`, `:562`, `:599`, `:646`, `:717`, `:797`, `:820`, `:885`
  - `PipelineState.from_dict`: `:316` [verifier: the call is at `backend/app/api/research.py:318`]
  - `RuntimeError` → 409: `:177`, `:212`, `:253`
- `backend/app/api/sdk.py:164` (`load`), `:180` (`list_pipelines`), `:193` (static `handoff_dir`).
- `backend/app/services/report_agent.py:2585-2592,9007-9033`, `oasis_profile_generator.py:1416-1423` and `simulation_config_generator.py:1365-1372` scan `list_pipelines()` and `load()` to locate handoff directories.
- Scripts: `backend/scripts/batch_runs.py` (`PIPELINE_SCHEMA_VERSION`, `STAGE_BANDS`, `PipelineManager.load/save/is_incompatible/handoff_dir`; `:64-65,146,209-350,455-460`), `scheduled_rerun.py:305,480,613,623,742`, `resolution_monitor.py:138`, `model_comparison.py:147`, `test_pipeline_resume.py`.
- Tests: `backend/tests/test_orchestrator_outage_halt.py`, `test_deerflow_bridge_sync_guard.py`, `test_bridge_extensions_config.py`, `test_loop007_research_budget.py`, `test_loop010_global_synthesis.py`, `test_research_spend_flush.py`, `test_graph_research_boundary.py`, `test_foglamp_containment.py`, `test_orchestrator_research_wiring.py`, `test_research_fork_handoff.py`, `test_wave9_orchestrator.py`, `test_status_live_block.py`.

**Calls out of this slice:**
- `..config.Config`
- `..utils.atomic.write_json_atomic` (`:954-956`, `:1019-1020`, `:1073-1074`, `:1097-1098`, `:1131-1133`, `:1897-1899`)
- `..utils.telemetry` (`BudgetExceeded`, `get_run_context`, `active_run_ids`, `LLMMeter`)
- `..utils.llm_client` (`LLMClient`, `_is_quota`, `_is_deterministic_auth_error`)
- `..services.actor_role_prompt` (`sanitize_untrusted_research_text`, `delimit_untrusted_research_text`)
- `..services.text_processor.TextProcessor.split_text`
- `resolve_research_engine` (`:5906`)
- `deerflow_bridge/runtime_skill_sync.py`
- `deerflow_bridge/patches/apply_{lead_agent,model_factory,subagent}_overlays.py`

---

## Invariants, gates, validation

- **ID safety.** Every path derivation goes through `_validate_id` (`:867-877`), so IDs from URLs cannot escape `PIPELINE_DATA_DIR`. `load` and `delete` turn a bad id into None or False (`:1137-1140`, `:1194-1197`).
- **Schema gate.** Every `save` stamps v2 (`:949`). `load` migrates older files and returns the sentinel for newer ones in strict mode (`:1151-1172`). State-rewriting operations raise `IncompatiblePipelineSchema` (`:8131`, `:8232`, `:8293`). `touch_heartbeat` and `mark_salvaged_completed` refuse sentinels (`:1087`, `:1034`). **`mark_failed` does not** (see Surprises).
- **Write serialization.** Each in-process read-modify-write writer holds `_state_lock(id)` (`:955`, `:1000`, `:1032`, `:1085`). Every write is atomic: a unique temp file followed by `os.replace` (`backend/app/utils/atomic.py:37-44`).
- **Heartbeat liveness.** A heartbeat is written only while `status == "running"` (`:1089-1090`). Stale or alive decisions are made outside the slice (`:7809-7840`).
- **Outage breaker.**
  - The threshold is ≥1 when enabled (`:456`).
  - The breaker is fresh per attempt (`:537-538`) and cleared in `_run` `finally` (`:13488`).
  - It stays tripped once tripped (`:466`, `:473`).
  - It never counts its own fast-fail text (`:418-419`), cancellations, budget errors, or non-provider errors.
- **Bridge fail-closed set.** Research does not launch when any of these hold:
  - the entry scripts are missing (`:1464-1467`)
  - the skill helper is missing or sync fails (`:1473-1497`)
  - the helper copy fails (`:1586-1589`)
  - the lead-agent or subagent overlay is missing, raises, or returns an unexpected status when its targets exist (`:1606-1631`, `:1685-1710`)
- **Extensions config.** Rendered output must contain no leftover `{{…}}` placeholder (`:1404-1406`).
- **Budget.**
  - At most `RESEARCH_BUDGET_MAX_EPOCHS` epochs per pipeline (`:1851-1856`); one epoch per task id, and re-entry reuses it (`:1840-1849`).
  - The pre-spawn guard rejects launches when any global cap is saturated for the current epoch (callers `:11104-11110`, `:12038-12045`, `:10877-10883`).
- **Spend accounting.** Exactly once per failed attempt (`:2054-2056`), and never on success (`:2130-2140`).
- **Policy pins.** New admissions always carry `safety_policy_v1` and `actor_intelligence_policy_v1` (`:7962-7967`). v3 engine admissions pin `required=False` with a disclosed reason (`:845-851`). [verifier: this holds only for `start`; `fork` creates a new pipeline without any `safety_policy_v1` and copies `actor_intelligence_policy_v1` only when the base has one (`backend/app/services/pipeline_orchestrator.py:8300-8326`), so `_pinned_safety` falls back to ambient Config for forks (`:8517-8527`). Non-legacy engines always pin `required=False`, but `not_required_reason` is added only when `DEERFLOW_DUAL_TRACK` is on (`:847-851`)]

---

## Failure modes & recovery

| Failure | Behavior | Recovery |
|---|---|---|
| Provider outage (≥N consecutive quota/auth/connection/breaker failures, no success in between) | The breaker trips, LLM calls fail fast with `LLM_OUTAGE_HALT…`, the next progress callback raises `ProviderOutageHalt`, and the run becomes `status=failed` with `options.provider_outage_halt` (`:469-488`, `:8967-8969`, `:9766-9793`) | `POST /api/research/<id>/resume` after the provider recovers; resume reuses completed stages (message `:504-512`) |
| Newer-schema state file (strict mode) | `load` returns the sentinel; resume, continue and fork raise `IncompatiblePipelineSchema` → HTTP 409 (`:1156-1163`, `:8131`, `backend/app/api/research.py:177`) | upgrade the backend, or set `PIPELINE_STRICT_SCHEMA=false` (fields may be lost) |
| Corrupt or unreadable state JSON | `load` returns `None`, which looks like "not found" (`:1144-1147`) | manual repair |
| Migration exception | the raw, unmigrated dict is returned (`:1167-1171`); the next `save` stamps v2 | automatic |
| Concurrent writes from heartbeat, main thread and API | serialized by the per-id lock (`:933-956`) | — |
| Backend crash with the pipeline left `running` | at startup `reconcile_orphans` → `mark_salvaged_completed` (report complete) or `mark_failed` (`:7695`, `:7717`) | resume |
| Bridge entry script, skill helper or skill bundle missing or broken | `_DeerFlowSkillSyncError` is raised before spawn, so the research stage fails (`:1464-1497`, `:1736-1738`) | fix `deerflow_bridge/` or re-run `./setup.sh` |
| Lead-agent or subagent overlay fails | `_DeerFlowSafetyOverlayError` is raised before spawn (`:1606-1631`, `:1685-1710`) | inspect upstream vendor drift and re-run `setup.sh` |
| Any other sync exception (non-helper copy failure, model-factory overlay exception, config digest failure) | WARNING only; the cached `skill_sync_result` is returned and research **launches** (`:1739-1745`) | — (see Surprises) |
| `extensions_config.json` template broken | WARNING; the deployed copy is removed; the KG MCP wiring is skipped (`:1563-1570`, `:2414-2422`) | fix the template |
| Budget epoch cap reached | `RuntimeError("research budget epoch limit reached …")` (`:1852-1856`) | raise `RESEARCH_BUDGET_MAX_EPOCHS` only with explicit cost approval |
| Budget snapshot shows a saturated global cap | the caller raises `research_budget_exhausted before track launch …` (`:11104-11110`) | an explicit resume (new task id → new epoch) |
| Failed, timed-out or cancelled research attempt | tokens are still billed through `_flush_failed_research_attempt_spend` (`:2134-2140`) | — |
| Telemetry snapshot archive fails | `RuntimeError("could not archive prior research budget telemetry")` (`:1876-1879`) | filesystem fix |

---

## Surprises

1. **Suspected bug: `mark_failed` can destroy a newer-schema state file.** `mark_failed` (`:992-1021`) does not check `INCOMPATIBLE_KEY`, unlike `touch_heartbeat` (`:1087`) and `mark_salvaged_completed` (`:1034`). Consider a state file written by newer code that is persisted as `running`. In strict mode, `load` returns the 4-key sentinel, which still includes `status`. `_orphan_is_dead` treats an incompatible file as dead (`:7819-7821`). Salvage is skipped because there is no `report_id` (`:7750-7752`), so `reconcile_orphans` calls `mark_failed` (`:7717`). That writes the **sentinel stub** (pipeline_id/status/schema_version/`__incompatible_schema__`/error/updated_at) over the full newer file. This defeats the "never downgrade-overwrite" intent at `:923-926`.
2. **Suspected: the sync guard does not fully fail closed.** Several failures fall into the generic `except Exception` at `:1739-1745`:
   - a failure to copy a *non-helper* module, such as `deerflow_research.py` or `linear_research.py`, which re-raises at `:1590`
   - any exception from the optional model-factory overlay (`:1647-1655`), which is not retyped
   - a config.yaml digest error

   The guard then logs a warning and returns `skill_sync_result`, so research launches on stale code. Worse, the generic exit **skips the later required subagent safety overlay** (`:1668-1716`) and the config drift check. [verifier: understated: a copy failure at `:1590` also skips the required lead-agent overlay (`backend/app/services/pipeline_orchestrator.py:1599-1635`), because the copy loop runs before both overlays] This contradicts the docstring's "must fail closed before launch" (`:1450-1454`).
3. Required safety overlays are enforced only when their vendor target files exist (`:1606`, `:1685`). If upstream moves `agent.py`, `client.py`, `task_tool.py` or `executor.py`, the overlay is skipped silently with no error.
4. Bridge module copies use plain `shutil.copyfile` with no lock and no atomic rename (`:1584`). Skills (flock plus atomic swap) and `extensions_config.json` (mkstemp plus replace) are atomic. With two pipelines in one process, a child could import a half-written module during a drift resync (suspected, low likelihood).
5. `setup.sh` deploys `deerflow_bridge/patches/models/*.py` (`setup.sh:618-620`), but the launch-time guard never resyncs them, so provider patches can drift. `setup.sh` also never renders or deploys `extensions_config.json`; only the orchestrator does (`:1556-1578`).
6. **Suspected:** `RESEARCH_BUDGET_ENABLED=false` only strips the child env (`:2002-2005`). `_activate_research_budget_epoch` still creates epochs, still enforces `RESEARCH_BUDGET_MAX_EPOCHS` (`:1851-1856`), and still writes `tool_budget_enabled: True` into the snapshot (`:1906`). On explicit resume, `_run_attempt` re-injects `RESEARCH_BUDGET_RUN_ID/LANE_ID/EPOCH` after the pop (`:2388-2395`), although `RESEARCH_BUDGET_DB` stays unset.
7. **Suspected (fail-open guard):** on explicit checkpoint resume, the child gets `RESEARCH_BUDGET_EPOCH = resume_attempt_id`, the *prior* epoch (`:2395`). The bridge stamps its snapshot `epoch` from that env (`deerflow_bridge/research_budget.py:1351`). A later `_research_budget_exhaustion(path, current_epoch)` in the same task then sees a mismatch and returns `None` (`:1781-1782`). The SQLite ledger remains authoritative for admission. [verifier: the stamping mechanism is real, but no in-tree caller re-checks a snapshot last written by a resumed child against the same epoch: the lane and single-track checks run right after activation writes a fresh current-epoch snapshot (`backend/app/services/pipeline_orchestrator.py:1899-1921`, `:11104`, `:12038`); synthesis-only recovery runs only at research-stage entry when an earlier attempt left an evidence manifest, i.e. in practice under a later task id (`:11955-11975`) and its children get no `resume_attempt_id` (`:10951`). The observable effect today is that the archived `final_research_budget.json` can carry the prior epoch label (`:1863-1873`); treat the fail-open as hypothetical]
8. **Suspected policy drift:** `capture_safety_policy_v1("resume_reconstructed_safe")` simply snapshots the *current ambient* `Config` (`:789-799`). Nothing forces safe values. Despite the docstring (`:780-783`) and the resume log ("以安全收容政策执行", `:8191-8199`), an operator who sets `SIM_GRAPH_FEEDBACK=true` gets an "unsafe" pin labelled safe.
9. `ensemble_extremize_a` uses `float(... or 1.0)` (`:796`), so a configured `ENSEMBLE_EXTREMIZE_A=0` is pinned as 1.0.
10. **Suspected cross-run attribution in the outage breaker:** `_current_outage_breaker` falls back to "the only active telemetry run" or "the only registered breaker" (`:567-576`). LLM calls with no run context therefore get attributed to the single running pipeline's breaker: API-thread calls such as translation, interviews or the LLM settings test, and worker threads of another run that has no breaker. They can trip it, and once it is tripped they are fast-failed with `LLM_OUTAGE_HALT`. This contradicts the docstring's "rather undercount than cross-pollute" (`:558-559`).
11. The probe only wraps `LLMClient.chat`. `LLMClient.chat_with_tools` calls `client.chat.completions.create` directly (`backend/app/utils/llm_client.py:714`) and bypasses the breaker: it neither counts, resets, nor is fast-failed. That method's own fallback to ReAct goes through `chat()`.
12. `_outage_halt_threshold`'s defensive `try/except` on env parsing (`:387-390`) is moot: `config.py:69` already does `int(os.environ['LLM_OUTAGE_HALT_CONSECUTIVE'])` at import, so a non-integer value crashes the backend at import time.
13. `_kill_process_group(proc, SIGTERM)` falls back to `proc.kill()`, which is SIGKILL, when `killpg` fails (`:1259-1263`). The "gentle" `cleanup_all` (`:2110`) can therefore hard-kill.
14. The `"2056"` marker in `_SYNTHESIS_PROVIDER_UNAVAILABLE_MARKERS` (`:1975`; the MiniMax token-plan code) is a bare substring and matches any error text containing "2056", such as a port or byte count. That would stop synthesis retries early. This is suspected and low-impact.
15. Constants are duplicated across the process boundary. `ACTOR_INTELLIGENCE_SCHEMA_VERSION` is a literal here (`:107`), in `backend/app/utils/actors.py:190` and in `deerflow_bridge/deerflow_research.py:2579`. [verifier: understated: the literal `"actor-intelligence/v1"` also appears in `backend/app/services/actor_context.py:28` (as `ACTOR_INTELLIGENCE_VERSION`), `backend/app/services/simulation_config_generator.py:3285,3290`, `backend/app/utils/actors.py:33` and inside this module at `backend/app/services/pipeline_orchestrator.py:2886`] `ACTOR_INTELLIGENCE_DIMENSIONS` (`:114-132`) duplicates `deerflow_bridge/deerflow_research.py:2580-2598`; the two are identical today, so this is a drift risk only.
16. The status comments are stale. `StageState.status` (`:662`) and `PipelineState.status` (`:689`) omit `cancelled`, which is written at `:1016`, `:8008` and `:13361`. The `PipelineManager` comment refers to `create()` (`:863`), but the method is `start` (`:7920`).
17. A minor lost-update remains. `save()` blind-writes the in-memory `heartbeat_at`. It is refreshed in memory only by progress callbacks (`:8985-8986`), so non-progress saves such as `:1922` and `:1964` can roll back a fresher `heartbeat_at` written by `touch_heartbeat`. [verifier: the progress-callback refresh is at `backend/app/services/pipeline_orchestrator.py:8986-8987`; it is not the only refresh: the seed-ensemble code refreshes before its saves (`:8683-8684`, `:8696-8697`, `:8750-8751`) and `_start_heartbeat` stamps it once (`:10345`). The regression via `:1922`/`:1964` still holds] The next tick, ≤30s later, repairs it. The lock prevents interleaving, but not this semantic regression.
18. Outside the slice but tied to the heartbeat: `_beat` waits a full interval before the first `touch_heartbeat` (`:10354`), although its comment (`:10353`) says it beats immediately ("立即落一拍"). The first beat reaches disk only through the next `save`.
19. `sdk.py:193` uses the static `PipelineManager.handoff_dir`, not `resolve_handoff_dir`. The SDK dossier endpoint therefore reads the empty fork-local directory for forks, which is exactly the problem `resolve_handoff_dir` (`:887-894`) was added to fix.
20. Housekeeping:
    - `PipelineManager._state_locks` grows without bound (`:933`).
    - `delete` re-imports `shutil` locally (`:1191`) although it is imported at `:35`.
    - `import importlib.util` is repeated four times inside the sync function (`:1479`, `:1611`, `:1645`, `:1690`).
    - The skill helper module is re-executed from disk on every research launch (`:1482-1488`).
21. `list_pipelines` reports the directory name as `pipeline_id` (`:1213`) and fully loads and migrates every state file on each call. Several services call it in loops (`report_agent.py:2585`, `9007`, `9026`).
22. Doc-vs-code drift:
    - `ARCHITECTURE_MAP.md:131,135,741` and `DRF_ARCHITECTURE.md:194,198,201,309,356` cite stale anchors: PipelineState `:210-284` (actual `:682-758`), PipelineManager `:292-626` (actual `:860-1221`), lock `:341-361` (actual `:928-956`), sync guard `:703` (actual `:1441`), `_start_heartbeat` `:5447` (actual `:10331`).
    - `DRF_ARCHITECTURE.md:356-361` describes "the three tool modules + `research_budget.py`", per-file `skills/*/SKILL.md` syncing, and "two patches". The code syncs 6 modules, deploys skills through the manifest/flock/atomic-swap helper, and applies three overlays (lead-agent, model-factory, subagent).
    - Both docs say state writes are "tmp + fsync + os.replace", but heartbeat writes use `fsync=False` (`:1098`).
23. Test gap (hedged): a grep of `backend/tests` and `backend/scripts` found no test exercising `INCOMPATIBLE_KEY`, `_migrate_v1_to_v2` or the `PIPELINE_STRICT_SCHEMA` bypass. Fixtures only write the current `PIPELINE_SCHEMA_VERSION` (e.g. `backend/tests/test_research_fork_handoff.py:33`).
24. `deerflow_bridge/logs/<uuid>/{chat,pre_tool_use,post_tool_use}.json` is gitignored (`.gitignore:61`) [verifier: the matching pattern is `logs/` at `.gitignore:60`; `/logs/` at `.gitignore:61` is root-anchored and does not match `deerflow_bridge/logs/`] and contains agent transcripts that mention these symbols. Repo-wide greps return noise from it.

---

## Verification

Adversarial verification on 2026-10-11 against the on-disk `main` checkout, read-only. Bare `:N` anchors mean `backend/app/services/pipeline_orchestrator.py:N`.

**Verdict counts** (15 key claims, 20 surprises, 19 extra Walkthrough/Control-flow statements spot-checked):

| Group | Confirmed | Imprecise | Refuted | Unverifiable |
|---|---|---|---|---|
| Key claims | 12 | 3 | 0 | 0 |
| Surprises | 16 | 4 | 0 | 0 |
| Spot checks | 12 | 7 | 0 | 0 |
| **Total** | **40** | **14** | **0** | **0** |

### Non-confirmed claims and surprises, with corrections

1. **Claim: `touch_heartbeat` is a no-op unless the persisted status is `running`.** Imprecise. It also returns False when the state is missing or is the incompatible-schema sentinel. A newer-schema file that is still `running` is therefore never touched (`:1086-1090`). The Walkthrough text at the `touch_heartbeat` bullet is correct.
2. **Claim: `_classify_provider_outage` uses 20 connection text markers.** Imprecise. `_PROVIDER_OUTAGE_CONNECTION_MARKERS` has 19 entries (`:369-376`, AST count). The order auth → circuit_breaker → quota → connection is correct (`:428-442`).
3. **Claim: `_activate_research_budget_epoch` creates `…/epoch-NNN-<slug>/research_budget.sqlite3`.** Imprecise. It creates only the epoch directory (`:1862`) and assigns `db_path` (`:1881`). The SQLite file is created later by the bridge child through `RESEARCH_BUDGET_DB`. Re-entry reuse also requires a non-empty `db_path` on the matching row (`:1848`). The snapshot limits come from `Config` (defaults 1800/900/360/450/180), not from literals (`:1907-1918`).
4. **Surprise 2 (sync guard not fully fail-closed).** Imprecise, because it is understated. A non-helper copy failure at `:1590` exits before **both** required overlays: lead-agent (`:1599-1635`) and subagent (`:1668-1716`). A model-factory exception (`:1647-1655`) skips only the subagent overlay and the config check.
5. **Surprise 7 (resume epoch fail-open).** Imprecise. The mechanism is real: `RESEARCH_BUDGET_EPOCH=resume_attempt_id` (`:2395`), and the bridge stamps `epoch` from that env (`deerflow_bridge/research_budget.py:1351`). However, no in-tree caller re-checks such a snapshot against the same epoch:
   - The lane and single-track checks follow a fresh current-epoch snapshot write (`:1899-1921`, `:11104`, `:12038`).
   - Synthesis-only recovery runs at research-stage entry on a later attempt (`:11955-11975`), and its children get no `resume_attempt_id` (`:10951`).

   The concrete effect today is that the archived `final_research_budget.json` can carry the prior epoch label (`:1863-1873`).
6. **Surprise 15 (duplicated constants).** Imprecise, because it is understated. Beyond the three constant definitions, the literal `"actor-intelligence/v1"` also appears at:
   - `backend/app/services/actor_context.py:28`
   - `backend/app/services/simulation_config_generator.py:3285,3290`
   - `backend/app/utils/actors.py:33`
   - `:2886`

   `ACTOR_INTELLIGENCE_DIMENSIONS` is identical in both files (AST compare, 17 entries).
7. **Surprise 17 (`save` regresses `heartbeat_at`).** Imprecise anchor and an overstated "only". The progress-callback refresh is at `:8986-8987`. Other in-memory refreshes exist at `:8683-8684`, `:8696-8697`, `:8750-8751` (seed ensemble) and `:10345` (`_start_heartbeat`). The regression via the saves at `:1922` and `:1964` still holds. The `_beat` first-tick delay is confirmed (`:10353-10354`).

### Non-confirmed spot checks (inline notes added above)

- `_ACTOR_BEHAVIOR_READY_FAMILIES`: its 5 families cover 12 of the 17 dimensions, not all of them (`:133-145`).
- `load` step 1: a non-numeric `schema_version` raises out of `load`, because `int()` sits outside the try (`:1151`). This propagates through `list_pipelines` (`:1210`) and aborts `reconcile_orphans` (`:7734-7735`).
- Sync step 7: the generic handler is step 13, not step 12. Such an exit also skips the lead-agent overlay (`:1590`, `:1599-1635`).
- Control flow 8 omits three gates:
  - the port-probe skip, `PIPELINE_RECLAIM_PORT_PROBE` (`:7656-7668`)
  - the heartbeat-disabled path, where every orphan is treated as dead (`:7679`)
  - the `PIPELINE_SALVAGE_COMPLETED_ORPHANS` gate (`:7689`)
- The `PipelineState.from_dict` call in the API is at `backend/app/api/research.py:318`, not `:316`.
- The Policy-pins invariant holds only for `start`:
  - `fork` pins no `safety_policy_v1`, and copies the actor policy only when the base has one (`:8300-8326`).
  - `not_required_reason` requires dual-track to be on (`:847-851`).
- `.gitignore:61` should be `.gitignore:60` (`logs/`). `/logs/` is root-anchored.

**Spot checks confirmed:**
- `_note_provider_stage_failure` call sites: `:11258`, `:11548`, `:10982`
- `_kill_process_group` call sites: `:2110`, `:2454`, `:2468`, `:2542`, `:2569`
- sync call sites: `:2211`, `:11116`, `:10856`
- `_research_budget_attempt_ids` callers: `:5709`, `:11191`, `:12010`
- `mark_failed` callers: `:7717`, `:8008`, `:8074`, `:8137`
- skill-sync helper details: the 4 required skills, the lock file, and the 60s timeout (`deerflow_bridge/runtime_skill_sync.py:42,46-51,246-270,410-422`)
- extensions template tokens (`deerflow_bridge/extensions_config.json:7,13,26,32`)
- the parity test (`backend/tests/test_deerflow_bridge_sync_guard.py:224-235`) and `setup.sh:597`
- `_detect_deerflow_python` order (`:1234-1245`)
- `resolve_handoff_dir` containment logic (`:895-912`)
- the progress-callback halt (`:8967-8969`)
- `_run` `finally` (`:13393-13488`)

**Confirmed with notes:**
- **Surprise 1 is confirmed and has a wider reach.** The comment at `:7820` explicitly routes incompatible files to `mark_failed`. The same stub overwrite is also reachable through a user cancel of an orphan (`:8008`) and through delete (`:8074`, which deletes right after). `resume` is safe because it checks `is_incompatible` first (`:8129-8131`).
- **Surprise 9 is confirmed but cosmetic today.** The pinned `ensemble_extremize_a` is never read back. Only `:796` references the key. `backend/app/services/ensemble.py:206` and `backend/app/services/forecast_extractor.py:2821` read ambient `Config` directly.
- **Claim 9 is confirmed.** One extra nuance: the generic handler raises `_DeerFlowSkillSyncError` if `skill_sync_result` is still `None` (`:1741-1744`).

### Omissions (significant behavior the map did not cover)

1. **Unhandled non-numeric `schema_version`.** `load` raises on a non-numeric `schema_version` (`:1151`). One malformed state file therefore breaks `list_pipelines` and the API list, and skips orphan reconciliation for every pipeline (`:7672`, `:7734-7735`).
2. **Forks get no safety pin.** Scenario forks are new pipelines with no `safety_policy_v1` (`:8300-8342`). Their containment flags follow ambient `Config` through `_pinned_safety` (`:8517-8527`). The pin-on-reload guarantee described in the comment at `:761-771` therefore does not cover forks.
3. **The sentinel overwrite has more entry points.** It is not limited to `reconcile_orphans`: cancel of an orphan (`:8008`) and delete (`:8074`) also call `mark_failed` on a sentinel without an `INCOMPATIBLE_KEY` check (`:1000-1021`).
4. **Overlay scripts use a fixed temp name** (hedged, low likelihood). Each overlay script stages through `<target>.tmp`:
   - `deerflow_bridge/patches/apply_lead_agent_overlays.py:120-123`
   - `deerflow_bridge/patches/apply_model_factory_overlays.py:46-49`
   - `deerflow_bridge/patches/apply_subagent_overlays.py:282-285`

   This is the shared-temp-name pattern that the state writer (`:950-953`) and `_deploy_rendered_extensions_config` (`:1413-1417`) were fixed to avoid. Two pipelines that run `_sync_deerflow_bridge_if_stale` concurrently in one process against an unpatched vendor tree could race. The parallel-lane path pre-syncs once (`:11116`), which narrows but does not remove this risk across pipelines.
5. **The extremize pin is decorative.** The pinned `ensemble_extremize_a` (`:796`) is never consumed. The ensemble code reads `ENSEMBLE_EXTREMIZE_A` from ambient `Config` (`backend/app/services/ensemble.py:206`, `backend/app/services/forecast_extractor.py:2821`), so a service reload can change extremization for an admitted run despite the pin.
