# scripts-ops-1 — Backend ops scripts I

Scope (all read in full, 4,203 lines): `backend/scripts/preflight.py` (513), `batch_runs.py` (841), `scheduled_rerun.py` (938), `resolution_monitor.py` (704), `check_env_drift.py` (327), `process_diagnostics.py` (118), `disk_usage_report.py` (108), `reclaim_report_space.py` (192), `replay_zep_dead_letters.py` (161), `architecture_baseline.py` (301). Branch `main`, checkout on disk. All anchors are `path:line` relative to the repo root.

## Purpose & position in the pipeline

These ten scripts are operator tools that sit beside the research → graph → simulation → report pipeline. None of them is a pipeline stage. They fall into four groups:

| Group | Scripts | Relationship to the pipeline |
|---|---|---|
| Readiness and config hygiene | `preflight.py`, `check_env_drift.py` | Run before a pipeline. `preflight.py` wraps `preflight_pipeline()` (the same check POST /run uses) and adds optional live probes. `check_env_drift.py` is a static, stdlib-only lint over `config.py`, `.env.example` and the repo-root `.env`. |
| In-process pipeline drivers | `batch_runs.py`, `scheduled_rerun.py` | Import `PipelineOrchestrator` and start pipelines **inside the script's own Python process**. They do not call the HTTP API (`backend/scripts/batch_runs.py:63-77`, `backend/scripts/scheduled_rerun.py:71-74`, `backend/app/services/pipeline_orchestrator.py:7969-7978`). |
| Post-publication monitoring and repair | `resolution_monitor.py`, `replay_zep_dead_letters.py` | Run against finished reports or simulations. The resolution monitor re-quotes Polymarket anchors and writes market resolutions to the ledger. The replay script resubmits graph-feedback episodes that failed and were dead-lettered. |
| Disk, process and fixture utilities | `disk_usage_report.py`, `reclaim_report_space.py`, `process_diagnostics.py`, `architecture_baseline.py` | Stdlib-only (no `app` import). They work on the filesystem or process table. `architecture_baseline.py` and `process_diagnostics.py` are Foglamp WP0A tooling (`backend/scripts/architecture_baseline.py:2`, `backend/scripts/process_diagnostics.py:2`). |

Only three of these scripts are called from inside the backend:
- `preflight.environment_report`, imported by `GET /api/research/preflight?format=full` (`backend/app/api/research.py:367-382`).
- `resolution_monitor.py`, run as a subprocess by `resolution_autorun` (`backend/app/services/resolution_autorun.py:43-47`).
- `check_env_drift.py` and `preflight.py`, run by `scripts/doctor.sh` (`scripts/doctor.sh:114-130`, `scripts/doctor.sh:241-266`).

## Walkthrough (source order)

### 1. `backend/scripts/preflight.py` — environment readiness engine (EXECPLAN2 I-8-0)

- **Module docstring** (`backend/scripts/preflight.py:1-42`). States the design goal: one Python source of truth shared by `doctor.sh`, the POST /run gate and the Settings UI. Documents the CLI forms and exit codes: 0 = ready, 1 = blocking problem, 2 = ready with warnings (`backend/scripts/preflight.py:35-37`).
- **Path bootstrap** (`backend/scripts/preflight.py:56-59`). `ROOT` is three `dirname`s above the file (the repo root). `ROOT/backend` is put at the front of `sys.path`, so `app` imports work from either cwd.
- **Imports** (`backend/scripts/preflight.py:61-62`): `Config` and `preflight_pipeline`. Importing `app.config` loads the repo-root `.env` with `override=True` unless `DRF_TEST_PROCESS=1` (`backend/app/config.py:18-24`).
- **Severity constants** `ok`/`warn`/`bad` (`backend/scripts/preflight.py:65-67`).
- **`environment_report(mode="full", model=None, *, deep=False, pull=False)`** (`backend/scripts/preflight.py:73-152`).
  - `df_model` = `model`, else `Config.DEERFLOW_MODEL`, else `"claude"`, then stripped and lower-cased (`:101`).
  - Each string from `preflight_pipeline(mode, model)` becomes a check `{id:"pipeline.<i>", severity:"bad", ok:False, message:err, fix:err}` (`:107-118`). What `preflight_pipeline` checks (`backend/app/services/pipeline_orchestrator.py:6779-6852`):
    - graph backend importability (falkordblite / kuzu / external FalkorDB), full mode only;
    - the report/sim LLM key and the `claude`/`codex` CLI on PATH, full mode only;
    - `DEERFLOW_DIR/deerflow_research.py` exists;
    - the research-model key env var or CLI/OAuth credentials.
  - Then `_append_placeholder_checks` (`:122`).
  - When `deep`, every `(level, message)` from `deep_probes()` is appended as `{id:"deep.<len(checks)>", severity:level, fix:None}` (`:124-137`).
  - Returns `{provider, deerflow_model, graph_backend, venv_python=sys.executable, deerflow_dir, data_dir=GRAPHITI_DATA_DIR, embed_model, mode, ready=(exit_code!=1), exit_code, checks}` (`:139-152`).
- **`_append_placeholder_checks(checks, df_model)`** (`backend/scripts/preflight.py:155-189`).
  - Does nothing if `Config._is_placeholder` is not callable (`:162-164`).
  - Adds `placeholder.llm_api_key` (severity bad) when `LLM_API_KEY` is a placeholder value (`:167-176`). This check runs regardless of `mode` and regardless of whether the provider needs a key. See Surprises.
  - Adds `placeholder.<key_env lower>` (bad) when `DEERFLOW_KEY_ENV[df_model]` names an env var whose value is a placeholder (`:179-189`).
  - The placeholder set is `{'your_zep_api_key_here','your_zep_api_key','your_api_key','your_api_key_here','changeme','xxx','...'}`, matched after strip and lower-casing (`backend/app/config.py:1585-1592`).
- **`deep_probes(model=None, *, pull=False)`** (`backend/scripts/preflight.py:195-208`). A generator that yields, in this order, the results of `_probe_llm_provider`, `_probe_deerflow_model(model)`, `_probe_embed_model(pull)` and `_probe_free_disk`.
- **`_live_openai_compat(label, provider, api_key, base_url, model)`** (`backend/scripts/preflight.py:211-267`). Sends one bounded chat completion.
  - No key → `bad` (`:213-214`).
  - Runs the SSRF guard `validate_safe_url(base_url, block_private=APP_BLOCK_PRIVATE_URLS)`. Rejection → `bad` (`:217-222`). The guard resolves DNS (`backend/app/utils/security.py:110-135`).
  - Missing `openai` SDK → `warn` (`:224-227`).
  - Client: `timeout=25`, `max_retries=0` (`:229`). For `kimi`, adds a `User-Agent` header from `Config.LLM_USER_AGENT`, default `claude-cli/1.0.0` (`:231-234`).
  - Request: prompt `"Reply with exactly: pong"`, `temperature=0`, `max_tokens=16` (`:236-241`). Adds `extra_body` from `Config._DISABLE_THINKING_EXTRA_BODY[provider]` when present (`:243-245`).
  - Kimi temperature is forced to `0.6` when thinking is disabled, otherwise `1.0` (`:248-250`).
  - On an exception, maps `status_code` 401/403/404/429 to a Chinese hint. It never echoes the upstream error text (`:255-265`).
  - On success → `ok`, with latency in ms (`:266-267`).
- **`_live_cli(label, cli)`** (`backend/scripts/preflight.py:270-274`). Only checks `shutil.which(cli)`. No credential call.
- **`_probe_llm_provider()`** (`backend/scripts/preflight.py:277-291`).
  - Provider not in `PROVIDER_META` → `warn` (`:281-283`).
  - Provider with `openai_compat=False` → CLI check: `claude` for `claude-cli`, otherwise `codex` (`:284-286`).
  - Otherwise base = `LLM_BASE_URL`, else `meta.default_base`, else `https://api.openai.com/v1`; model = `LLM_MODEL_NAME`, else `meta.default_model`, else `gpt-4o-mini` (`:287-291`).
- **`_probe_deerflow_model(model)`** (`backend/scripts/preflight.py:294-316`).
  - `claude`/`codex` → CLI check (`:301-303`).
  - Unknown model → `warn` (`:304-306`).
  - Otherwise: key env = `meta.key_env`, else `DEERFLOW_KEY_ENV`, else `<MODEL>_API_KEY`. Base = env `<MODEL>_BASE_URL`, else `default_base`. Model = env `<MODEL>_MODEL`, else `default_model` (`:308-312`).
  - Missing key → `bad` (`:313-315`). Otherwise one live completion (`:316`).
- **`_embed_cached(name)`** (`backend/scripts/preflight.py:319-338`). Uses `huggingface_hub.try_to_load_from_cache` against `name` and `sentence-transformers/<name>`, looking for `modules.json`, `config_sentence_transformers.json` or `config.json`. Returns True/False, or None when the HF hub library is missing.
- **`_probe_embed_model(*, pull)`** (`backend/scripts/preflight.py:341-371`). Checks `GRAPHITI_EMBED_MODEL`, default `paraphrase-multilingual-MiniLM-L12-v2` (`backend/app/config.py:1026`).
  - cached → `ok`; unknown → `warn`; not cached and no `pull` → `warn` that suggests `doctor.sh --deep --pull`.
  - With `pull`: instantiates `SentenceTransformer(embed)`, which downloads about 470 MB (`:359-371`).
- **`_probe_free_disk()`** (`backend/scripts/preflight.py:378-408`).
  - Checks `GRAPHITI_DATA_DIR` and `UPLOAD_FOLDER`. For each, walks up to the nearest existing ancestor and deduplicates by path.
  - Under 2 GiB free → `bad`, under 5 GiB → `warn`, otherwise `ok` (`:403-408`).
- **`_exit_code_for(checks)`** (`backend/scripts/preflight.py:414-420`). Any `bad` → 1; else any `warn` → 2; else 0.
- **`_render_text(report)`** (`backend/scripts/preflight.py:423-458`). Uses ANSI colours only on a TTY (`:425`). Prints a header with provider, model and backend, then one line per check (marked ✓, ⚠ or ✗) with the fix. The fix is printed only if it differs from the message (`:446`). Ends with a summary line and returns the exit code.
- **`main(argv)`** (`backend/scripts/preflight.py:461-509`).
  - Flags: `--json`, `--mode {full,research_only}` (default `full`), `--model`, `--deep`, `--pull` (`:466-483`).
  - **`--deep --json`** streams JSONL `{"level","message"}`, one object per deep probe and **only the deep probes**. The return value is the worst probe level: 1 for bad, 2 for warn (`:491-500`).
  - `--json` alone prints the full `environment_report` document and returns its `exit_code` (`:504-507`).
  - With no flags it renders text (`:509`).

### 2. `backend/scripts/batch_runs.py` — multi-question batches sharing one graph (I-9-3)

- **Docstring** (`backend/scripts/batch_runs.py:1-44`).
  - Claims research, ontology and graph run once for the anchor prompt `prompts[0]` (`:4-5`).
  - Describes two modes: the default (each question runs its own simulation) and `shared_simulation` (`:15-21`).
  - Documents the knobs `BATCH_SHARED_SIMULATION` and `BATCH_MAX_FANOUT` (`:23-29`).
  - CLI: `run --prompt … [--depth] [--max-rounds] [--shared-simulation] [--wait]`, `status <batch_id>`, `list` (`:31-41`).
- **Bootstrap** (`backend/scripts/batch_runs.py:59`). Puts `backend/` (`scripts/..`) on `sys.path`. Imports come from `pipeline_orchestrator`, `ensemble.aggregate_forecasts`, `ReportManager` and `write_json_atomic` (`:61-80`).
- **Constants** (`backend/scripts/batch_runs.py:87-96`).
  - `_BATCHES_SUBDIR="_batches"` and `_BATCH_ID_RE_PREFIX="batch_"`.
  - `_POLL_INTERVAL_S=5.0`.
  - `_WAIT_TIMEOUT_S` = `float(os.environ.get("BATCH_WAIT_TIMEOUT_S","14400"))`, read at import (`:94`).
  - `_TERMINAL_STATUSES` (`:96`) is never used (dead).
- **`BatchManager`** (`backend/scripts/batch_runs.py:108-183`). File-backed and stateless.
  - `new_id()` returns `batch_<12 hex>` (`:116-117`).
  - `_validate_id` requires the `batch_` prefix and rejects `/`, `\`, `..` and any character outside alphanumerics, `_` and `-` (`:120-131`).
  - Record path: `Config.PIPELINE_DATA_DIR/_batches/<id>/batch.json`, which resolves to `backend/uploads/pipelines/_batches/...` (`backend/app/config.py:1581`).
  - `save()` stamps `updated_at` and `schema_version=PIPELINE_SCHEMA_VERSION` (2, `backend/app/services/pipeline_orchestrator.py:245`), then writes atomically (`:143-148`).
  - `load()` returns None for a bad id, a missing file, a decode error or JSON that is not a dict (`:151-163`).
  - `list_batches()` returns a summary row per batch, sorted by `created_at` descending (`:166-183`).
- **`_wait_for_graph(pipeline_id, cancel=None)`** (`backend/scripts/batch_runs.py:191-229`). Blocking poll every 5 s until the anchor has `graph_id` and `stages.graph.status=="completed"`. It raises `RuntimeError` on:
  - cancellation;
  - timeout, when `_WAIT_TIMEOUT_S` > 0;
  - a missing record or incompatible schema;
  - `failed`/`cancelled` before the graph exists;
  - `completed` without a graph.
- **`fork_question(base_pipeline_id, question, *, batch_id, shared_simulation, max_rounds)`** (`backend/scripts/batch_runs.py:237-366`).
  - Validation (`:268-277`): the base must exist (`FileNotFoundError` otherwise), its schema must be compatible, `graph_id` must be set, and shared mode needs `simulation_id`.
  - Builds a new `PipelineState` (`:279-287`): `pipe_<12hex>`, `prompt=question` (overriding the anchor prompt), `mode="full"`, `project_id=None`, the base `graph_id`, and the **base `handoff_dir`**.
  - Marks only RESEARCH and GRAPH as completed. ONTOLOGY stays pending (`:293-298`).
  - Options (`:300-314`): `base_pipeline_id`, `project_name`, plus `depth`, `research_language` and `research_model` copied from the base; `batch_id` and `max_rounds` when given.
  - Shared mode (`:316-327`) also marks PREPARE and RUN completed, sets `simulation_id` to the base value, adds `shared_simulation` and `shared_simulation_from`, and sets `current_stage=REPORT`. Non-shared mode sets `current_stage=ONTOLOGY` (`:329`).
  - Creates a `TaskManager` task of type `pipeline:full:batch_question` (`:337-347`) and saves `status="running"` (`:348-350`).
  - Under `PipelineOrchestrator._lifecycle_lock`, registers a cancel event and starts a **daemon** thread `pipeline-batch-<id>` running `PipelineOrchestrator._run` (`:352-361`).
- **`start_batch(prompts, *, mode="full", project_name, depth, max_rounds, language, model, shared_simulation=None, cancel=None)`** (`backend/scripts/batch_runs.py:374-532`).
  - Strips the prompts and drops empty ones; empty input → `ValueError`. `mode != "full"` → `ValueError` (`:411-415`).
  - `shared_simulation` defaults to `Config.BATCH_SHARED_SIMULATION`. `max_fanout = Config.BATCH_MAX_FANOUT`, default 8, clamped to at least 1 (`:417-421`).
  - Runs `preflight_pipeline(mode, model)` once. Any error → `RuntimeError` (`:424-426`).
  - Extra prompts beyond `max_fanout` go into `skipped[]` with a reason and a logged warning (`:433-441`).
  - Anchor: `PipelineOrchestrator.start(prompt=anchor, mode="full", …)` (`:444-452`). Then the anchor's options are best-effort tagged with `batch_id` and `batch_role="anchor"` (`:454-462`).
  - The record is saved with `status="preparing"` (`:464-483`).
  - Waits for the anchor's graph. On failure: record `failed`, append the error, re-raise (`:486-492`).
  - In shared mode with extra prompts, also waits for the simulation. If that fails it **downgrades to non-shared** instead of failing the batch (`:495-507`).
  - Sets `status="running"`, then calls `fork_question` for each extra prompt. One failed fork is logged into `errors[]` without stopping the others, and the record is saved after each prompt (`:510-526`).
  - Returns the record without waiting for children to finish (`:532`).
- **`_wait_for_simulation(pipeline_id, cancel)`** (`backend/scripts/batch_runs.py:535-562`). Same poll and timeout pattern as `_wait_for_graph`. Succeeds when the anchor RUN stage is completed and `simulation_id` is set.
- **`_child_view(child)`** (`backend/scripts/batch_runs.py:570-606`).
  - Loads the child pipeline state. A missing record gives `status="missing"`.
  - Projects `status, global_progress, current_stage, report_id, simulation_id`.
  - Reads `uploads/reports/<report_id>/forecast.json` when it exists (`:597-605`).
- **`_aggregate_status(child_views)`** (`backend/scripts/batch_runs.py:609-622`). No children → `empty`. Any child `running`, `preparing` or `None` → `running`. All `completed` → `completed`. Otherwise → `partial`.
- **`batch_status(batch_id)`** (`backend/scripts/batch_runs.py:625-668`).
  - Writes the aggregated status back into `batch.json` unless the record is already `failed`. Errors on that write are swallowed (`:642-647`).
  - Feeds every child `forecast.json` into `ensemble.aggregate_forecasts` to build `combined.ensemble` (`:649-650`).
  - Returns a view with counts, children, `skipped`, `errors` and `combined` (`:652-668`).
- **CLI** (`backend/scripts/batch_runs.py:676-837`).
  - `_cmd_run` takes prompts from `--prompt` (repeatable) plus `--prompts-file`, one prompt per line with `#` comments. A read error → 2; no prompts → 2 (`:677-690`).
  - `--shared-simulation` maps to `True`, otherwise `None`, which means "use Config" (`:692`).
  - `ValueError` or `RuntimeError` from `start_batch` → exit 1 (`:703-705`).
  - Prints JSON or text, and runs `_wait_and_report` if `--wait` (`:721-723`).
  - `_wait_and_report` polls every 10 s until `completed` or `partial`, with **no timeout**. Exit 0 only if `completed` (`:726-740`).
  - `status` and `list` are read-only views (`:743-792`).
  - Parser (`:795-829`): `--depth {quick,standard,deep}`, `--language {Chinese,English,auto}`, and the other `run` flags. `main` maps `--language auto` to `""`, which means "let the model choose", matching `api/research.py` (`:832-837`).

### 3. `backend/scripts/scheduled_rerun.py` — scheduled reruns and drift detection (I-9-6)

- **Docstring** (`backend/scripts/scheduled_rerun.py:1-46`).
  - Schedule records live at `uploads/schedules/<id>/schedule.json`.
  - A daemon tick scans schedules and launches `PipelineOrchestrator.start`.
  - Drift compares `forecast.json` scenario probabilities and also checks `actors.json` and `communities.json`.
  - Lists the CLI subcommands `add|list|show|enable|disable|delete|run-once|tick|daemon|diff` (`:36-45`).
- **Bootstrap** (`backend/scripts/scheduled_rerun.py:65-67`). Imports `Config`, `ensemble._norm_name`, `PipelineManager`, `PipelineOrchestrator`, `ReportManager` and `write_json_atomic` (`:69-77`).
- **Knob readers** (`backend/scripts/scheduled_rerun.py:96-145`). Each reads the knob with `getattr(Config, NAME, default)`.

  | Knob | Clamp / handling | Script fallback |
  |---|---|---|
  | `SCHEDULER_ENABLED` | read as bool | False |
  | `SCHEDULER_TICK_SECONDS` | at least 5 | 60 |
  | `SCHEDULER_MAX_CONCURRENT` | at least 1 | 1 |
  | `SCHEDULER_DEFAULT_MAX_RUNS` | at least 0 | 0 |
  | `DRIFT_PROB_THRESHOLD` | must be in (0,1], else 0.15 | 0.15 |
  | `DRIFT_WEBHOOK_URL` | stripped; empty → None | None |

  The defaults in the comment block at `:88-93` are documentation only. Config's real defaults apply because Config defines most of these keys (`backend/app/config.py:440-445`).
- **`ScheduleStore`** (`backend/scripts/scheduled_rerun.py:157-295`).
  - `SCHEDULES_DIR = Config.UPLOAD_FOLDER/schedules`, fixed when the class is defined (`:161`). The id must match `^sched_[A-Za-z0-9_-]+$` and contain no `/`, `\` or `..` (`:164-174`). `SCHEMA_VERSION=1`.
  - `create(...)` (`:186-237`): the prompt must be non-empty and `interval_minutes` must be > 0, otherwise `ValueError`. `max_runs=None` → `default_max_runs()`.
  - The created record holds `schema_version, schedule_id, prompt, depth, options, project_name, research_language, research_model, interval_minutes, max_runs (0 = unlimited), enabled, created_at, updated_at, last_run_at=None, next_run_at=now, run_pipeline_ids=[], drift_history=[]`.
  - `save` writes atomically with `indent=2` (`:240-245`). `load` returns None on any error (`:248-260`). `delete` runs `shutil.rmtree(ignore_errors=True)` (`:263-273`). `list_schedules` sorts by `created_at` descending (`:276-286`). `set_enabled` (`:289-295`).
- **Drift helpers** (`backend/scripts/scheduled_rerun.py:303-358`).
  - `_forecast_path_for_pipeline` returns `uploads/reports/<report_id>/forecast.json` when the pipeline has a report and the file exists (`:303-312`).
  - `_load_json` accepts dicts only (`:315-323`).
  - `_actor_names` returns the first 12 `actors[].name` (`:326-337`).
  - `_coalition_labels` accepts a list, or a dict with `communities` or its values. Labels come from `name`, else `label`, else `summary`, else `id`; the first 12 are kept (`:340-358`).
- **`forecast_diff(prev, curr, *, threshold, prev_actors, curr_actors, prev_coalitions, curr_coalitions)`** (`backend/scripts/scheduled_rerun.py:361-471`). A pure function.
  - Scenarios are keyed by `_norm_name` (`:382-396`).
  - A matched scenario is flagged when `|Δp| >= threshold` (`:406-417`).
  - A new or dropped scenario always counts as drift and contributes its own probability to `max_prob_delta` (`:418-424`).
  - `new_actors`, `gone_actors` and `new_coalitions` are set differences (`:427-434`).
  - `drift` is true when there are scenario changes, new or dropped scenarios, new actors or new coalitions. **`gone_actors` does not count** (`:436-439`).
  - Builds a Chinese one-line summary (`:442-457`) and returns a dict with `schema_version:1` (`:459-471`).
- **`diff_pipelines(prev_pid, curr_pid)`** (`backend/scripts/scheduled_rerun.py:474-505`).
  - Loads both forecasts, plus `artifacts.dossier` (`handoff/actors.json`, `backend/app/services/pipeline_orchestrator.py:9512`) and `artifacts.communities` (`handoff/communities.json`, `:9526`).
  - Re-reads `communities` itself when the file is a top-level list (`:484-490`).
  - Adds `prev/curr_pipeline_id` and `has_prev/curr_forecast` to the result.
- **`fire_drift_webhook(url, payload, *, timeout=10.0)`** (`backend/scripts/scheduled_rerun.py:513-536`).
  - Runs `validate_safe_url` with `APP_BLOCK_PRIVATE_URLS`. If the URL is invalid it warns and returns False (`:515-521`).
  - Sends a JSON POST through `urllib.request.urlopen`. Returns True only on 2xx. URL or OS errors are swallowed and give False (`:522-536`).
- **`Scheduler`** (`backend/scripts/scheduled_rerun.py:556-780`). Class-level singleton made of `_thread`, `_stop_event` and `_lock`.
  - `maybe_start()` returns False unless `SCHEDULER_ENABLED`. If no thread is alive, it starts the daemon thread `scheduler` (`:569-585`). `stop()` sets the event (`:588-589`).
  - `_loop()` calls `PipelineOrchestrator.reconcile_orphans()` once (errors ignored), then repeats `tick()`, waiting `tick_seconds()` between ticks with `Event.wait` (`:592-605`).
  - `_running_pipeline_count()` counts **all** persisted pipelines with `status=="running"`, including runs a user started outside the scheduler (`:610-615`).
  - `_schedule_has_inflight(record)` is true when the schedule's latest pipeline is still `running` (`:618-624`).
  - **`tick(*, now=None, force_ids=None)`** (`:627-685`) checks each schedule in this order:
    1. skip if not enabled, unless forced (`:648-650`);
    2. due when forced, when `next_run_at` is missing, or when `now >= next_run_at` (`:653-656`);
    3. when `max_runs` is reached: auto-disable and save (`:659-666`);
    4. skip while the previous run is in flight (`:669-671`);
    5. when the global cap is reached, defer **without changing `next_run_at`** (`:674-679`);
    6. otherwise `_launch` (`:681-684`).
  - **`_launch(record, now)`** (`:688-732`) calls `PipelineOrchestrator.start(prompt, mode=options.mode or "full", project_name, depth, max_rounds=options.max_rounds, language=research_language, model=research_model)`. On an exception it sets `next_run_at = now + interval` and returns None (`:702-708`). On success it sets `last_run_at` and `next_run_at` and appends the pipeline id (`:713-717`). If a previous run exists, it starts the daemon thread `scheduler-diff-<sid>` → `_await_and_diff` (`:724-731`).
  - **`_await_and_diff(sid, prev, curr)`** (`:735-780`).
    - Polls every 30 s until the current pipeline reaches a terminal state or the deadline `max(600, DEERFLOW_RESEARCH_TIMEOUT + 1800)` s passes (`:738-746`).
    - Runs `diff_pipelines` and appends a `drift_history` entry (`{at, prev/curr_pipeline_id, drift, max_prob_delta, summary}`) to the schedule (`:748-766`).
    - When there is drift and a webhook URL, POSTs `{"event":"forecast_drift", schedule_id, prev/curr_pipeline_id, report}` (`:768-778`).
- **CLI `main`** (`backend/scripts/scheduled_rerun.py:838-934`).
  - `add` (`--prompt`, `--interval-minutes` required; `--depth`, `--max-runs`, `--project-name`, `--language`, `--model`, `--max-rounds`, `--disabled`). It prints the record, and `options` holds only `max_rounds` (`:842-855`).
  - `list` prints a compact JSON summary (`:857-871`). `show`, `enable`, `disable` and `delete` return 1 when the schedule is not found (`:873-892`).
  - `run-once` calls `Scheduler.tick(force_ids={sid})`. It returns 1 if nothing was triggered, for example because the concurrency cap was hit or a run is in flight (`:894-905`).
  - `tick` runs one pass and prints what it triggered (`:907-910`).
  - `daemon` returns 2 unless `SCHEDULER_ENABLED`. Otherwise it calls `maybe_start()` and sleeps in a loop until Ctrl-C (`:912-927`).
  - `diff` prints the `diff_pipelines` report (`:929-932`).

### 4. `backend/scripts/resolution_monitor.py` — MON-1 market re-quote and resolution tracking

- **Docstring** (`backend/scripts/resolution_monitor.py:1-26`). The script runs four steps: re-quote into `price_track.jsonl`, resolve and append to the ledger's `resolutions.jsonl`, build the needs-manual list, and write `monitor_report.md`. `--dry-run` writes nothing. CLI: `run <report_id|pipeline_id> [--dry-run]`, `run --all-recent [N]`, `summary`.
- **Bootstrap and imports** (`backend/scripts/resolution_monitor.py:39-45`): `Config` and `app.services.forecast_ledger as _ledger`.
- **Knobs** (`backend/scripts/resolution_monitor.py:55-80`).
  - `recent_n_default()` = `RESOLUTION_MONITOR_RECENT_N`, at least 1, default 10.
  - `lookback_days()` = `RESOLUTION_MONITOR_LOOKBACK_DAYS`, at least 0, default 0.
  - `drift_threshold()` = `RESOLUTION_MONITOR_DRIFT_THRESHOLD`, which must be in [0,1], otherwise 0.05.
  - The Config definitions are at `backend/app/config.py:282-284`.
- **Small helpers** (`backend/scripts/resolution_monitor.py:88-111`): `_coerce_float` (NaN → None), `_utcnow_iso`, `_today`, and `_read_json` (None on error).
- **`_report_folder(report_id)`** (`backend/scripts/resolution_monitor.py:119-122`) returns `ReportManager._get_report_folder` = `Config.UPLOAD_FOLDER/reports/<id>` with no id validation (`backend/app/services/report_agent.py:11864`, `:11890-11892`).
- **`resolve_report_id(id_)`** (`backend/scripts/resolution_monitor.py:125-143`). If `reports/<id>` is a directory, the id is a report id. Otherwise it is treated as a pipeline id and mapped through `PipelineManager.load(id).report_id`. No match → None.
- **`recent_report_ids(n, *, as_of=None)`** (`backend/scripts/resolution_monitor.py:146-171`). Calls `ReportManager.list_reports(limit=n)`, which is sorted by `created_at` descending (`backend/app/services/report_agent.py:14421-14447`). When the lookback is > 0, it then filters on `created_at[:10] >= as_of - lookback`. The limit is applied **before** the filter.
- **Pure functions** (`backend/scripts/resolution_monitor.py:180-323`).
  - `_ISO_DATE_RE` matches `20YY-MM-DD` (`:180`).
  - `anchored_forecasts(forecast)` keeps `binary_forecasts[]` entries whose `market_anchor.market_id` is non-empty (`:183-194`).
  - `binary_resolution_date(b)`: the first ISO date found in `resolution_criteria`, then `resolution_source`, then `statement`; otherwise `horizon_year`-12-31 for years 2000–2100; otherwise None (`:197-213`).
  - `build_price_rows(anchored)` builds `{market_id, question, implied_yes_prob, price_at_research (else implied_yes_prob), forecast_id, statement}` (`:216-235`).
  - `compute_movers(requoted, threshold)` skips `requote_failed` rows, keeps rows with `|price_delta| >= threshold`, and sorts by |Δ| descending (`:238-257`).
  - `build_resolution_records(...)` keeps markets that are resolved and have a `resolved_yes_price`. It sets `y = 1 if yes_price >= 0.5 else 0` and `brier = round((model_p - y)^2, 4)`. `market_p` = `price_at_research`, else `implied_yes_prob` (`:260-295`).
  - `detect_needs_manual(binaries, resolved_ids, as_of)` scans **all** binaries. A binary is listed when its resolution date is on or before `as_of` (string comparison) and its anchor market has not resolved (`:298-323`).
- **`render_monitor_md(...)`** (`backend/scripts/resolution_monitor.py:334-424`). Deterministic markdown with no LLM. Sections:
  - a "degraded" banner;
  - **Running score (from ledger)**: market Brier, scenario Brier and calibration error;
  - **Newly resolved markets** table;
  - **Biggest price movers since research** table;
  - **Needs manual resolution** table.

  `_cell` escapes `|` to `／` and removes newlines (`:330-331`).
- **Price track** (`backend/scripts/resolution_monitor.py:432-481`).
  - `price_track_path` = `<report_folder>/price_track.jsonl`.
  - `append_price_snapshot` appends one JSON line and warns on `OSError` (`:436-445`).
  - `read_price_track` tolerates bad lines (`:448-466`).
  - `_price_snapshot` produces `{at, report_id, markets:[{market_id, price_at_research, implied_yes_prob, price_delta, requote_failed}]}` (`:469-481`).
- **`run_monitor(report_id, *, forecast, report_folder, client, ledger_dir, dry_run, as_of, threshold, write_report=True)`** (`backend/scripts/resolution_monitor.py:489-608`). Every input can be injected for tests.
  - Default client: `PolymarketClient()` (`:507-509`).
  - Re-quote: `client.requote_markets(rows)`. An exception, or every row `requote_failed`, sets `degraded` (`:517-529`).
  - Resolutions: `client.fetch_resolutions(market_ids)`. An exception, or an empty result when there were ids, sets `degraded` (`:532-543`).
  - Builds the records and the needs-manual list (`:547-551`).
  - Unless `dry_run`: appends the price snapshot, then calls `_ledger.append_market_resolution(...)` for each record, which is idempotent on `(report_id, forecast_id, market_id)` (`:555-570`).
  - Always reads `calibration_summary` and `market_brier_summary` from the ledger (`:573-574`).
  - Writes `monitor_report.md` atomically unless `dry_run` or `write_report=False` (`:582-590`).
  - Returns a summary dict that includes the full markdown (`:592-608`).
- **CLI** (`backend/scripts/resolution_monitor.py:634-700`).
  - `run [report_id] [--all-recent [N]] [--dry-run]`. `--all-recent` alone uses `const=-1`, meaning the default N (`:644-645`). `--all-recent` takes precedence over a positional id (`:656-667`).
  - No recent reports → exit 1. Unknown id → 1. Neither given → 2.
  - A failure on one report is caught and printed as `{"report_id", "error"}`. **The exit code stays 0** (`:672-687`).
  - `summary` prints the ledger Brier and calibration with no network (`:694-699`).

### 5. `backend/scripts/check_env_drift.py` — .env.example drift and .env pin audit (I-8-5 / ENV-1)

- **Constants** (`backend/scripts/check_env_drift.py:39-100`).
  - `ROOT`, `CONFIG=backend/app/config.py`, `ENV_EXAMPLE=<root>/.env.example`, `ENV_FILE=<root>/.env` (`:39-42`).
  - `_IGNORE`: Flask, Python and infra vars plus `ZEP_API_KEY` (`:46-52`).
  - `_ENV_READ_RE` matches `os.environ.get('X'…` and `os.environ['X']` only, **not `os.getenv`** (`:54`).
  - `_ENV_DOC_RE` matches `X=` lines, **including commented `# X=` lines** (`:55`).
  - `_IGNORE_PATTERNS`: `LLM_<P>_DISABLE_THINKING` (`:60`).
  - `PERF_CRITICAL_VARS`: 13 throughput knobs (`:70-84`).
  - `_SECRET_SEGMENTS` (`:91`).
  - `_CONFIG_DEFAULT_RE` captures `os.environ.get('VAR', '<literal>'` across newlines (`:97-100`).
- **Functions.**
  - `config_env_vars()` regex-scans `config.py` source with no import, then removes ignored names (`:103-109`).
  - `documented_env_vars()` (`:112-116`).
  - `config_defaults(text)` keeps the first occurrence of each var (`:119-132`).
  - `parse_env_text(text)` (`:135-162`) parses dotenv-like text:
    - optional `export ` prefix;
    - matching surrounding quotes are stripped and the content kept verbatim;
    - for unquoted values, a space-prefixed `# comment` is dropped;
    - the last assignment wins.
  - `parse_env_file` (`:165-170`) and `example_values` (`:173-181`).
  - `is_secret(var)`: an underscore segment of the name is in {KEY, TOKEN, SECRET, PASSWORD, PASSWD, CREDENTIAL(S)} (`:184-188`).
  - `mask_value` returns `***` for secrets (`:191-195`).
  - `_normalize` strips whitespace and one layer of quotes and lower-cases only `true`/`false` (`:198-211`).
- **`find_divergent_pins(env_path, config_text, example_text)`** (`backend/scripts/check_env_drift.py:214-257`).
  - For each active `.env` pin, the reference is the `config.py` default, else the `.env.example` value (`:236-240`).
  - Skipped: ignored vars, pins with no known reference, pins whose reference is empty, and normalized matches (`:234-246`).
  - Each record is `{var, pinned (masked), current_default (masked), default_source, critical, secret}`, sorted critical first, then by name (`:247-257`).
- **`_render_pins`** (`backend/scripts/check_env_drift.py:260-284`). Emits JSON with `critical_count`, or a table with `‼` markers. Column widths are computed from masked values.
- **`main()`** (`backend/scripts/check_env_drift.py:287-323`).
  - `--pins` exits 1 only when `--strict` is set and a critical pin diverges (`:296-302`).
  - The default doc-drift mode reports `missing_from_env_example = read - documented` and `documented_but_unread`. It exits 1 only when `--strict` is set and something is missing (`:304-323`).

### 6. `backend/scripts/process_diagnostics.py` — process-tree dump (Foglamp WP0A)

- `FAULTHANDLER_SNIPPET` and `NO_HANDLER_REASON` (`backend/scripts/process_diagnostics.py:25-26`).
- `_read_process_table()` runs `ps -o pid=,ppid=,command= -ax` with `check=False` and parses `{pid: (ppid, command)}` (`:29-49`).
- `_children_of(pid, table)` builds the child tree recursively, sorted by pid (`:52-61`).
- `main` (`:64-114`).
  - `--install-faulthandler-snippet` prints the snippet and returns 0 (`:79-81`).
  - The target is `--pid`, else the script's own pid (`:83`).
  - Pid not in the table → error JSON, exit 2 (`:85-88`).
  - `--signal` → `os.kill(pid, SIGUSR1)`. `ProcessLookupError` or `PermissionError` are reported in the output (`:91-99`).
  - Output: sorted-key JSON `{children, cmdline, pid, pythonFaultStacks[, pythonFaultStacksReason]}`. No stacks are actually collected; only a note that SIGUSR1 was sent (`:103-114`).

### 7. `backend/scripts/disk_usage_report.py` — read-only disk report

- `BACKEND_ROOT` and `REPO_ROOT` come from the file location (`backend/scripts/disk_usage_report.py:14-15`).
- `AREAS` are hardcoded (`:17-24`): `backend/uploads/pipelines`, `backend/uploads/reports`, all of `backend/uploads`, `backend/logs`, `<repo>/deerflow_bridge/.cache` and `<repo>/logs`.
- `dir_size` walks without following symlinks and ignores `OSError` (`:27-38`). `human` formats B/KB/…/TB (`:41-46`). `top_children` returns the largest non-hidden entries (`:49-61`).
- `main` (`:64-104`).
  - Flag: `--top N` (default 10).
  - Prints the volume's free space from `statvfs`, with a LOW flag below 5 GiB (`:69-75`).
  - Prints each area. "uploads (other)" subtracts the two `uploads/` subareas already counted (`:77-90`).
  - Prints the total and a fixed block of "retention observations (NO action taken)" (`:92-103`).
  - Always exits 0. Deletes nothing and does not import `app`.

### 8. `backend/scripts/reclaim_report_space.py` — reclaim report disk space (dry-run by default)

- **Constants** (`backend/scripts/reclaim_report_space.py:34-41`):
  - `BACKUP_RE = ^\.codex-backup-\d{8}T\d{6}Z$`;
  - `SCRIPT_PREFIX="<script"`, `SCRIPT_CLOSE`;
  - `DIRECTORY_TAG='<script src="plotly.min.js"></script>'`;
  - `MIN_BUNDLE_CHARS=1_000_000`, `SIGNATURE_WINDOW=4_000`.
- `_reports_root()` = `backend/uploads/reports` (`:44-46`).
- `find_backup_dirs(root)`: directories exactly one level under `reports/<id>/` that are real (not symlinked) directories with a matching name (`:49-57`).
- `_dir_bytes` sums `lstat` sizes (`:60-68`).
- `purge_backups(root, apply)` measures first, prints `DELETE` or `would delete`, and runs `shutil.rmtree` only when `apply` (`:71-79`).
- `extract_inline_bundle(html)` (`:82-110`). Scans `<script …>…</script>` spans with `find`. A candidate has no `src=` in the tag, content of at least 1M chars, and `plotly.js` within the first 4 KB. **Exactly one** candidate is required. Returns the rewritten HTML and the bundle.
- `deinline_charts(root, apply)` (`:113-158`). For each `*/charts` directory:
  - skips HTML that already contains `DIRECTORY_TAG`;
  - skips when the rewrite would lose the figure payload (`Plotly.newPlot` or `plotly-graph-div` must remain);
  - skips when the bundle byte size differs from an existing `plotly.min.js`;
  - on `apply`, writes the bundle once per directory (tmp file + `os.replace`), then the HTML (tmp + `os.replace`);
  - returns `(converted, skipped, freed_chars)`.
- `main(argv)` (`:161-188`).
  - Flags: `--apply`, `--purge-backups`, `--deinline-charts`, `--root`. With neither operation flag, both run (`:169`).
  - A missing root → exit 1. Prints per-operation and total GB.
- When serving, the API re-inlines the sibling bundle through `app/utils/chart_html.inline_plotly_bundle` (`backend/app/utils/chart_html.py:30-49`).

### 9. `backend/scripts/replay_zep_dead_letters.py` — replay dead-lettered graph episodes (XRUN-6)

- **Docstring** (`backend/scripts/replay_zep_dead_letters.py:1-21`):
  - the dead-letter format, which matches `ZepGraphMemoryUpdater._write_dead_letter`;
  - replay goes through the same `graph.add` path;
  - a failed batch stops that file and the remainder is written back;
  - a fully replayed file is renamed to `.replayed-<ts>`;
  - running while no simulation is active is recommended.
- **Imports** (`backend/scripts/replay_zep_dead_letters.py:31-34`): `Config` and the `Zep` facade from `app.services.graphiti_client`.
- `DEFAULT_BATCH_SIZE=5` and `SEND_INTERVAL=0.5` (`:36-37`) mirror `ZepGraphMemoryUpdater.BATCH_SIZE`/`SEND_INTERVAL` (`backend/app/services/zep_graph_memory_updater.py:216`, `:225`).
- `_dead_letter_dir()` = `Config.OASIS_SIMULATION_DATA_DIR/_zep_dead_letter`, i.e. `backend/uploads/simulations/_zep_dead_letter` (`:40-41`; `backend/app/config.py:1080`).
- `_atomic_rewrite(path, lines)` writes a tmp file, fsyncs, then `os.replace` (`:44-52`).
- `replay_file(client, path, batch_size, dry_run, limit=0)` (`:55-117`).
  - Takes a snapshot of the non-blank lines. Records with a non-empty `combined_text` are replayable; other lines are kept as malformed (`:57-73`).
  - `dry_run` prints counts and returns without writing (`:77-80`).
  - Otherwise, for each batch: `client.graph.add(graph_id=…, type="text", data="\n".join(texts))`, then sleep 0.5 s. On the first exception it stops (`:84-97`). The `limit` check runs before each batch, so it can be exceeded by up to `batch_size-1`.
  - Lines kept: the unreplayed records, the malformed lines, and any lines appended during the run (detected by comparing line counts) (`:99-107`).
  - If anything is kept, the file is rewritten atomically. Otherwise it is renamed to `<file>.replayed-YYYYmmddTHHMMSS` (`:109-114`).
- `main()` (`:120-157`).
  - Arguments: positional `graph_id`, or `--all`, which takes every `*.jsonl` in the directory; `--dry-run`, `--batch-size`, `--limit`. With neither `graph_id` nor `--all`, `ap.error` exits 2 (`:122-136`).
  - Dry-run skips building `Zep()`, because the constructor starts the Graphiti runtime (`:143-144`; `backend/app/services/graphiti_client/client.py:355-357`).
  - Exit 1 if any file failed (`:145-157`).

### 10. `backend/scripts/architecture_baseline.py` — fixture capture, verify and compare (Foglamp WP0A)

- **Constants** (`backend/scripts/architecture_baseline.py:30-36`):
  - `SCHEMA_VERSION="baseline-manifest/v1"`;
  - `SECRET_PATTERNS`: `sk-…{20,}`, `AKIA…{16}`, and `api_key = '…{16,}'`.
- **Helpers** (`:39-86`).
  - `_emit` prints sorted, indented JSON with `ensure_ascii=False`.
  - SHA-256 of bytes or files (1 MiB chunks).
  - `_walk_regular_files` returns sorted relative POSIX paths, skipping symlinks.
  - `_inventory_hash` hashes path + size + `mtime_ns` for each file.
  - `_scan_for_secrets` returns the patterns that matched.
- **`cmd_capture`** (`:89-186`).
  - The source root must be absolute (`:91-93`), not a symlink (`:94-96`) and an existing directory (`:97-99`); otherwise exit 2. The fixture root must not equal the source root or sit inside it, otherwise exit 2 (`:104-106`).
  - Takes the pre-read inventory hash.
  - For each file: a secret hit → a `quarantined_secret` entry, and the file is **not copied**. Otherwise the file is copied to `fixture_root/rel` and a `captured` entry is recorded with `sourceSha256 == fixtureSha256` (`:115-147`).
  - Post-read inventory mismatch → exit 3 (`:149-160`).
  - Manifest `{files, fixtureRoot (relative to the manifest dir), inventoryHash, schemaVersion, sourceRootId=sha256(resolved path)}`. `capturedAt` is added only when `FOGLAMP_FAKE_NOW` is set (`:162-176`).
  - Prints a summary and exits 0.
- **`cmd_verify`** (`:196-233`). Loads the manifest (bad file or schema → 2). The fixture root comes from the argument or from the manifest's relative path. Only `captured` entries are re-hashed; mismatches are `missing` or `hash_mismatch` → exit 1.
- **`cmd_compare`** (`:236-269`). Compares a candidate tree with the manifest's `sourceSha256` for all entries, including quarantined ones. Reports `missing`, `extra` and `changed`; `identical` → 0, otherwise 1.
- **Parser and main** (`:272-297`). Subcommands are `capture`, `verify` and `compare`.

## Control flow

- **`preflight.py` CLI.** `main` (`backend/scripts/preflight.py:461`) branches:
  - `--deep --json` → `deep_probes` streamed as JSONL (`:491-500`);
  - otherwise `environment_report` (`:502`), which calls `preflight_pipeline` → `_append_placeholder_checks` → [`deep_probes`] → `_exit_code_for` (`:107-139`);
  - then either a JSON dump or `_render_text`.

  Through the API, `GET /api/research/preflight?format=full[&deep=true][&model=]` adds `backend/scripts` to `sys.path` and calls `environment_report(mode, model, deep)`. On any exception it falls back to the minimal `{ready, errors, mode}` (`backend/app/api/research.py:367-385`).
- **`batch_runs.py run`.** `_cmd_run` → `start_batch`:
  1. `preflight_pipeline` (`:424`);
  2. `PipelineOrchestrator.start(anchor)`, which starts the daemon thread `pipeline-<id>` (`:444`; `backend/app/services/pipeline_orchestrator.py:7969-7977`);
  3. `_wait_for_graph`, polling every 5 s (`:487`);
  4. [`_wait_for_simulation`] (`:497`);
  5. `fork_question` × N, each starting a daemon `_run` thread (`:513`);
  6. return.

  Then either `_wait_and_report`, which polls `batch_status` every 10 s (`:721-722`), or the process exits.
- **`scheduled_rerun.py`.**
  - `daemon`: `Scheduler.maybe_start` → `_loop` → `reconcile_orphans` → `tick` every `tick_seconds()` → `_launch` → `PipelineOrchestrator.start` + the `_await_and_diff` thread → `diff_pipelines` → `forecast_diff` → [`fire_drift_webhook`].
  - `tick` and `run-once` call `Scheduler.tick` once and return.
  - `diff` calls `diff_pipelines` directly.
- **`resolution_monitor.py run`.** `_cmd_run` → (`recent_report_ids` | `resolve_report_id`) → `run_monitor` for each report:
  - `build_price_rows` → `requote_markets` → `compute_movers`;
  - `fetch_resolutions` → `build_resolution_records` → `detect_needs_manual`;
  - writes the price track and ledger;
  - reads the ledger summaries → `render_monitor_md` → writes `monitor_report.md`.

  The backend runs it as `[sys.executable, resolution_monitor.py, "run", "--all-recent"]` with a 15-minute timeout and an in-flight guard. Triggers are `POST /api/research/resolution-monitor/run` and the optional `RESOLUTION_MONITOR_AUTORUN_HOURS` loop started from `run.py` (`backend/app/services/resolution_autorun.py:28`, `:38-60`, `:63-80`, `:88-117`; `backend/app/api/research.py:342-351`; `backend/run.py:41-42`).
- **`check_env_drift.py`.** `main` → (`find_divergent_pins` → `_render_pins`) | (`config_env_vars` + `documented_env_vars`).
- **`replay_zep_dead_letters.py`.** `main` → `Zep()` → `replay_file` per path.
- **`reclaim_report_space.py`.** `main` → `purge_backups` and/or `deinline_charts` → `extract_inline_bundle`.
- **`architecture_baseline.py`.** `main` → `args.func`, one of `cmd_capture`, `cmd_verify` or `cmd_compare`.
- **`process_diagnostics.py`.** `main` → `_read_process_table` → `_children_of`.
- **`disk_usage_report.py`.** `main` → `dir_size` / `top_children` for each area.

## Data & artifacts

| Script | Path pattern | R/W | Format / key fields |
|---|---|---|---|
| preflight | none written; reads `Config` / `.env` (through `app.config`), HF cache, `statvfs` | R | report dict `{provider, deerflow_model, graph_backend, venv_python, deerflow_dir, data_dir, embed_model, mode, ready, exit_code, checks[{id,severity,ok,message,fix}]}` (`backend/scripts/preflight.py:140-152`); with `--pull`, writes the HF model cache (`:362`) |
| batch_runs | `backend/uploads/pipelines/_batches/<batch_id>/batch.json` | R/W | `{batch_id, status(preparing→running→completed/partial/failed), anchor_prompt, anchor_pipeline_id, shared_simulation, max_fanout, created_at, updated_at, schema_version, options{depth,max_rounds,language,model,project_name}, children[{prompt,pipeline_id,role}], skipped[{prompt,reason}], errors[]}` (`backend/scripts/batch_runs.py:464-482`, `:145-148`) |
| batch_runs | `uploads/pipelines/<pipe_id>/pipeline_state.json` (through `PipelineManager.save`) | W | child states with `options.batch_id`, `base_pipeline_id`, `shared_simulation(_from)`; anchor options tagged with `batch_role` (`:300-327`, `:454-460`) |
| batch_runs | `uploads/reports/<report_id>/forecast.json` | R | structured forecast that feeds `aggregate_forecasts` (`:597-605`) |
| scheduled_rerun | `backend/uploads/schedules/<sched_id>/schedule.json` | R/W | see `create()` (`backend/scripts/scheduled_rerun.py:216-234`); `drift_history[{at,prev_pipeline_id,curr_pipeline_id,drift,max_prob_delta,summary}]` (`:757-765`) |
| scheduled_rerun | `reports/<rid>/forecast.json`, `handoff/actors.json`, `handoff/communities.json` | R | for drift (`:303-312`, `:479-491`) |
| resolution_monitor | `uploads/reports/<rid>/forecast.json` | R | `binary_forecasts[{id, statement, probability, horizon_year, resolution_criteria, resolution_source, market_anchor{market_id, question, implied_yes_prob, price_at_research}}]` (`backend/scripts/resolution_monitor.py:183-235`) |
| resolution_monitor | `uploads/reports/<rid>/price_track.jsonl` | append | `{at, report_id, markets[{market_id, price_at_research, implied_yes_prob, price_delta, requote_failed}]}` (`:469-481`) |
| resolution_monitor | `<ledger_dir>/resolutions.jsonl` (default `uploads/pipelines/_forecast_ledger/`, or `FORECAST_LEDGER_DIR`) | append (idempotent) | `{report_id, forecast_id, market_id, resolved_outcome, resolved_yes_price, model_p, market_p_at_research, brier_contribution, resolved_at, schema_version:1}` (`backend/app/services/forecast_ledger.py:23-30`, `:369-420`) |
| resolution_monitor | `uploads/reports/<rid>/monitor_report.md` | W (atomic) | markdown (`backend/scripts/resolution_monitor.py:583-587`) |
| check_env_drift | `backend/app/config.py`, `.env.example`, repo-root `.env` (`--pins` only) | R | regex/dotenv parse; output `{missing_from_env_example, documented_but_unread}` or `{divergent_pins[], critical_count}` |
| process_diagnostics | `ps` output | R | `{pid, cmdline, children[…], pythonFaultStacks, pythonFaultStacksReason?}` |
| disk_usage_report | `backend/uploads/**`, `backend/logs`, `deerflow_bridge/.cache`, `logs/` | R | stdout text |
| reclaim_report_space | `backend/uploads/reports/<id>/.codex-backup-*/` (deleted), `reports/<id>/charts/*.html` (rewritten), `charts/plotly.min.js` (created) | R/W/delete with `--apply` | |
| replay_zep_dead_letters | `backend/uploads/simulations/_zep_dead_letter/<graph_id>.jsonl` → rewritten or renamed `<graph_id>.jsonl.replayed-<ts>` | R/W | `{graph_id, platform, dead_lettered_at, combined_text, agent_name, action_type, round, timestamp}` (`backend/app/services/zep_graph_memory_updater.py:490-499`) |
| architecture_baseline | `--fixture-root/**` (copies), `--manifest` JSON | W | manifest `{files[{relativeLocator, sizeBytes, sourceSha256, fixtureSha256, lifecycleState, secretScan, transform}], fixtureRoot, inventoryHash, schemaVersion, sourceRootId, capturedAt?}` |

## Config / env knobs

| Knob | Default (effective) | Effect | Anchor |
|---|---|---|---|
| `--mode`, `--model`, `--deep`, `--pull`, `--json` (preflight CLI) | full / None / off | scope of checks; `--deep --json` = JSONL of deep probes only | `backend/scripts/preflight.py:466-483` |
| `APP_BLOCK_PRIVATE_URLS` | False | SSRF guard also rejects loopback/private ranges (preflight probes, drift webhook) | `backend/app/config.py:50`; `backend/scripts/preflight.py:220`; `backend/scripts/scheduled_rerun.py:518` |
| `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME`, `LLM_USER_AGENT` | `claude-cli`, …, `claude-cli/1.0.0` | target of the report/sim provider live probe | `backend/scripts/preflight.py:279-291`, `:233` |
| `DEERFLOW_MODEL`, `<MODEL>_API_KEY` / `DEERFLOW_KEY_ENV`, `<MODEL>_BASE_URL`, `<MODEL>_MODEL` | `claude` | research-model probe and placeholder check | `backend/scripts/preflight.py:297-316`; `backend/app/config.py:1546-1549` |
| `GRAPHITI_EMBED_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | embed-cache probe / pull | `backend/scripts/preflight.py:343` |
| `GRAPHITI_DATA_DIR`, `UPLOAD_FOLDER` | `backend/uploads/graphiti_db`, `backend/uploads` | disk probe targets | `backend/scripts/preflight.py:381-383` |
| `BATCH_SHARED_SIMULATION` | False | default batch mode | `backend/app/config.py:448`; `backend/scripts/batch_runs.py:417-418` |
| `BATCH_MAX_FANOUT` | 8 (minimum 1) | cap on forked questions; the rest go to `skipped[]` | `backend/app/config.py:447`; `backend/scripts/batch_runs.py:419-441` |
| `BATCH_WAIT_TIMEOUT_S` | 14400 s (≤0 disables) | wall-clock limit for the graph/sim waits; read from `os.environ` at import, not Config | `backend/scripts/batch_runs.py:94`, `:203`, `:541` |
| `SCHEDULER_ENABLED` | False | gates `daemon`/`maybe_start` only (not `tick`/`run-once`) | `backend/app/config.py:440`; `backend/scripts/scheduled_rerun.py:572`, `:913` |
| `SCHEDULER_TICK_SECONDS` | **300** from Config (script fallback 60, minimum 5) | daemon tick interval | `backend/app/config.py:441`; `backend/scripts/scheduled_rerun.py:126-127` |
| `SCHEDULER_MAX_CONCURRENT` | 1 | cap on all running pipelines counted during a tick | `backend/app/config.py:442`; `backend/scripts/scheduled_rerun.py:641-679` |
| `SCHEDULER_DEFAULT_MAX_RUNS` | 0 (unlimited); **not defined in Config, so only the script fallback exists** | default `max_runs` for `add` | `backend/scripts/scheduled_rerun.py:134-135` |
| `DRIFT_PROB_THRESHOLD` | 0.15 (must be in (0,1]) | scenario drift threshold (≥) | `backend/app/config.py:444`; `backend/scripts/scheduled_rerun.py:138-141`, `:411` |
| `DRIFT_WEBHOOK_URL` | empty → None | POST target for drift | `backend/app/config.py:445`; `backend/scripts/scheduled_rerun.py:770-778` |
| `DEERFLOW_RESEARCH_TIMEOUT` | 10800 | `_await_and_diff` deadline = max(600, value + 1800) | `backend/app/config.py:1165`; `backend/scripts/scheduled_rerun.py:738-740` |
| `RESOLUTION_MONITOR_RECENT_N` | 10 | default N for `--all-recent` | `backend/app/config.py:282`; `backend/scripts/resolution_monitor.py:69-70` |
| `RESOLUTION_MONITOR_LOOKBACK_DAYS` | 0 | age filter for recent reports | `backend/app/config.py:283`; `backend/scripts/resolution_monitor.py:73-74` |
| `RESOLUTION_MONITOR_DRIFT_THRESHOLD` | 0.05 (must be in [0,1]) | price-mover cutoff | `backend/app/config.py:284`; `backend/scripts/resolution_monitor.py:77-80` |
| `RESOLUTION_MONITOR_AUTORUN_HOURS` | 0 (off) | backend runs the monitor as a subprocess every N hours (not read by the script itself) | `backend/app/config.py:290`; `backend/app/services/resolution_autorun.py:96-100` |
| `PREDICTION_MARKETS_ENABLED`, `PREDICTION_MARKETS_REQUOTE_CHUNK` | True, 20 | PolymarketClient gate and batch size; disabled → every row `requote_failed`, no resolutions → `degraded` | `backend/app/utils/prediction_markets.py:225-227`, `:398` |
| `FORECAST_LEDGER_DIR` | `""` → `PIPELINE_DATA_DIR/_forecast_ledger` | ledger location | `backend/app/services/forecast_ledger.py:23-30` |
| `OASIS_SIMULATION_DATA_DIR` | `backend/uploads/simulations` | root of the dead-letter directory | `backend/app/config.py:1080`; `backend/scripts/replay_zep_dead_letters.py:40-41` |
| `ZEP_API_KEY` | `local-graphiti` | passed to the `Zep()` facade, which ignores it | `backend/app/config.py:1038`; `backend/scripts/replay_zep_dead_letters.py:144` |
| `FOGLAMP_FAKE_NOW` | unset | adds `capturedAt` to the baseline manifest | `backend/scripts/architecture_baseline.py:170-172` |
| `DRF_TEST_PROCESS` | unset | when `1`, `app.config` skips loading `.env` (affects every script that imports `app`) | `backend/app/config.py:18-24` |

## External calls

| Call | Where | Notes |
|---|---|---|
| OpenAI-compatible chat completion (1 request, `max_tokens=16`, timeout 25 s, 0 retries) | `backend/scripts/preflight.py:254` | `--deep` only, or API `?format=full&deep=true`. Spends tokens. Done once for the report LLM provider and once for the DeerFlow model. |
| DNS resolution in the SSRF guard | `backend/scripts/preflight.py:220`, `backend/scripts/scheduled_rerun.py:518` | `validate_safe_url` resolves every address of the host (`backend/app/utils/security.py:133-135`) |
| HuggingFace download of the embedding model (~470 MB) | `backend/scripts/preflight.py:360-362` | `--deep --pull` only |
| `shutil.which('claude'/'codex')` | `backend/scripts/preflight.py:272` | local only |
| Full pipelines: DeerFlow research subprocess, LLMs, Graphiti, OASIS subprocesses | `backend/scripts/batch_runs.py:444`, `:354-361`; `backend/scripts/scheduled_rerun.py:693` | by way of `PipelineOrchestrator._run` running in the script's process |
| HTTP POST to the drift webhook (urllib, 10 s timeout) | `backend/scripts/scheduled_rerun.py:522-533` | |
| Polymarket Gamma `/markets?id=…` (keyless), re-quote and resolutions | `backend/scripts/resolution_monitor.py:521`, `:536` → `backend/app/utils/prediction_markets.py:339-463` | batched in chunks of 20 |
| Graphiti `add_episode` through `Zep.graph.add`, which triggers graphiti_core LLM entity extraction and graph DB writes | `backend/scripts/replay_zep_dead_letters.py:90` → `backend/app/services/graphiti_client/client.py:200-208` → `backend/app/services/graphiti_client/runtime.py:463-491` | one episode per batch of 5 records; sleeps 0.5 s |
| `ps -o pid=,ppid=,command= -ax` subprocess | `backend/scripts/process_diagnostics.py:31-36` | |
| `os.kill(pid, SIGUSR1)` | `backend/scripts/process_diagnostics.py:93` | `--signal` only |
| `subprocess.run([python, resolution_monitor.py, run, --all-recent], timeout=900)` (inbound edge) | `backend/app/services/resolution_autorun.py:43-47` | |

`check_env_drift.py`, `disk_usage_report.py`, `reclaim_report_space.py` and `architecture_baseline.py` make no network or LLM calls.

## Cross-module edges

**Inbound (who calls into this slice):**
- `GET /api/research/preflight?format=full` → `preflight.environment_report` (`backend/app/api/research.py:367-382`). The frontend's `getPreflight` sends only `mode` and never `format=full` (`frontend/src/api/research.js:104-110`).
- `scripts/doctor.sh --deep` runs `backend/scripts/preflight.py --deep --json [--pull]` and turns the JSONL into TSV for its own rendering (`scripts/doctor.sh:241-266`). It runs `check_env_drift.py --strict` and `--pins --strict` (`scripts/doctor.sh:114-130`).
- CI runs `python3 backend/scripts/check_env_drift.py --strict` (`.github/workflows/ci.yml:21`). npm script `check:env` (`package.json:19`).
- `resolution_autorun` runs `resolution_monitor.py run --all-recent` as a subprocess (`backend/app/services/resolution_autorun.py:43`). It is reached from `POST /api/research/resolution-monitor/run` (`backend/app/api/research.py:342-351`) and from `run.py` startup (`backend/run.py:41-42`).
- The orchestrator's health check counts dead letters and tells operators to use `replay_zep_dead_letters.py` (`backend/app/services/pipeline_orchestrator.py:9411-9441`).
- Tests:
  - `backend/tests/test_env_drift_pins.py` (18 tests);
  - `test_forecast_diff.py` (5);
  - `test_reclaim_report_space.py` (6);
  - `test_resolution_monitor.py` (13);
  - `test_architecture_baseline_cli.py` (6);
  - `test_resolution_autorun.py` (6);
  - `test_audit_fixes_graph.py` loads the replay module with importlib (`backend/tests/test_audit_fixes_graph.py:311-347`).
- **No app code imports `batch_runs` or calls `Scheduler.maybe_start`.** A grep of `backend/app` and `backend/run.py` finds no caller. Both are CLI-only.

**Outbound:**
- `pipeline_orchestrator`: `preflight_pipeline` (`:6779`), `PipelineOrchestrator.start` (`:7920`), `_run` (`:11883`), `reconcile_orphans` (`:7637`), `_lifecycle_lock`/`_threads`/`_cancel_events` (`:7530-7535`), `PipelineManager.load/save/list_pipelines/ensure_dirs/handoff_dir/is_incompatible`, `PipelineState`, `StageState`, `STAGE_*`, `STAGE_BANDS`, `PIPELINE_SCHEMA_VERSION`.
- `app.models.task.TaskManager.create_task`, an in-memory singleton (`backend/app/models/task.py:54-73`).
- `ensemble.aggregate_forecasts` (`backend/app/services/ensemble.py:150`) and `ensemble._norm_name` (`:27-29`).
- `ReportManager._get_report_folder` and `list_reports` (`backend/app/services/report_agent.py:11890`, `:14421`).
- `forecast_ledger.append_market_resolution`, `calibration_summary`, `market_brier_summary` (`backend/app/services/forecast_ledger.py:369`, `:233`, `:423`).
- `PolymarketClient.requote_markets` and `fetch_resolutions` (`backend/app/utils/prediction_markets.py:339`, `:465`).
- `app.utils.atomic.write_json_atomic` and `write_text_atomic`, which create parent directories (`backend/app/utils/atomic.py:20-67`).
- `app.utils.security.validate_safe_url` (`backend/app/utils/security.py:110`).
- `graphiti_client.Zep` (`backend/app/services/graphiti_client/client.py:349-357`).
- Config attributes listed in the knobs table.

## Invariants, gates, validation

- **Exit-code contract (preflight).** 0, 1 or 2 by severity, shared by the text, JSON and JSONL forms (`backend/scripts/preflight.py:414-420`, `:491-500`). `ready = exit_code != 1` (`:149`).
- **The preflight probes never echo upstream exception text** (`backend/scripts/preflight.py:264-265`). The SSRF guard runs before any probe or webhook request (`:217-222`; `backend/scripts/scheduled_rerun.py:515-521`).
- **Batch id and schedule id path safety:**
  - batch ids need the `batch_` prefix and contain only alphanumerics, `_` and `-` (`backend/scripts/batch_runs.py:120-131`);
  - schedule ids must match the `^sched_[A-Za-z0-9_-]+$` regex (`backend/scripts/scheduled_rerun.py:164-174`).
  - There is **no** equivalent check on `report_id` in resolution_monitor (`backend/scripts/resolution_monitor.py:119-133`) or on `graph_id` in replay (`backend/scripts/replay_zep_dead_letters.py:130-131`).
- **Fan-out guardrail.** Prompts beyond `BATCH_MAX_FANOUT` are recorded in `skipped[]` instead of being dropped silently (`backend/scripts/batch_runs.py:433-441`).
- **Batch preflight.** A single `preflight_pipeline` runs before the anchor starts (`backend/scripts/batch_runs.py:424-426`).
- **Scheduler idempotence:**
  - a schedule is skipped while its last pipeline is `running` (`backend/scripts/scheduled_rerun.py:669-671`);
  - global cap (`:674-679`);
  - auto-disable at `max_runs` (`:661-666`);
  - a failed launch still advances `next_run_at`, so it is not retried every tick (`:702-708`).
- **Drift threshold.** Invalid values fall back to 0.15 (`backend/scripts/scheduled_rerun.py:138-141`). The resolution-monitor threshold falls back to 0.05 (`backend/scripts/resolution_monitor.py:77-80`).
- **Ledger idempotence.** At most one `resolutions.jsonl` row per `(report_id, forecast_id, market_id)`, under an in-process lock plus `fcntl.flock` (`backend/app/services/forecast_ledger.py:357-420`).
- **Resolution labelling.** A record is written only when `resolved=True` and `resolved_yes_price` is known; `y` is decided with a 0.5 cutoff (`backend/scripts/resolution_monitor.py:273-278`).
- **`--dry-run` in the resolution monitor skips every write** (price track, ledger, md), but it still makes the network calls (`backend/scripts/resolution_monitor.py:555`, `:583`).
- **Env-drift secrets.** Any var whose name contains a KEY/TOKEN/SECRET/PASSWORD/CREDENTIAL segment is masked as `***` everywhere in the output (`backend/scripts/check_env_drift.py:184-195`, `:249-250`).
- **Reclaim fail-closed rules** (`backend/scripts/reclaim_report_space.py:55`, `:107-108`, `:136-143`, `:164`):
  - backups must match the exact name regex, be real (not symlinked) directories, and sit one level under a report directory;
  - de-inlining needs exactly one inline bundle, the figure payload must survive, and the bundle byte size must match;
  - default mode is dry-run.
- **Dead-letter preservation.** Malformed lines and lines appended during the run are always kept. Files are archived, never deleted (`backend/scripts/replay_zep_dead_letters.py:99-114`).
- **Baseline integrity:**
  - absolute, non-symlink source root; fixture root not inside the source root;
  - pre/post inventory-hash check (exit 3);
  - secret-pattern quarantine (no copy);
  - schema-version check on load (`backend/scripts/architecture_baseline.py:91-106`, `:149-160`, `:120-133`, `:191-192`).

## Failure modes & recovery

- **preflight**
  - Any probe exception is turned into a `bad` or `warn` tuple. Nothing raises out of `deep_probes` except bugs (`backend/scripts/preflight.py:221-227`, `:255-265`, `:367-371`, `:399-401`).
  - The API falls back to the minimal response on any exception (`backend/app/api/research.py:383-384`).
  - doctor.sh has an inline fallback for when the script is missing (`scripts/doctor.sh:277-286`), and a safety net when `DEEP_LINES` is 0 (`scripts/doctor.sh:272`, `:501`).
- **batch_runs**
  - Anchor failure before the graph exists → batch `failed`, and `RuntimeError` propagates; the CLI exits 1 (`backend/scripts/batch_runs.py:488-492`, `:703-705`).
  - Shared-simulation wait failure → downgrade to non-shared (`:498-507`).
  - A failed fork is recorded in `errors[]` (`:523-525`).
  - A stuck anchor ends at `BATCH_WAIT_TIMEOUT_S` (`:207-208`).
  - `--wait` has **no timeout** (`:726-735`).
  - Failing to tag the anchor is ignored (`:461-462`).
- **scheduled_rerun**
  - `tick` exceptions are logged and the loop continues (`backend/scripts/scheduled_rerun.py:600-603`).
  - Launch failure → reschedule at the next interval (`:702-708`).
  - Diff failure → warning; no drift entry is written (`:748-752`).
  - Webhook failures are swallowed (`:534-536`).
  - On restart, the persisted `next_run_at` resumes the schedule, and the daemon's startup `reconcile_orphans` clears stale `running` pipelines (`:595-598`).
- **resolution_monitor**
  - Network failure → `degraded=True`, partial report, no exception (`backend/scripts/resolution_monitor.py:520-543`).
  - A failure on one report is captured and does not stop the batch (`:674-679`).
  - Failures writing the price track or md file are logged (`:443-445`, `:588-590`).
  - The backend wrapper enforces a 15-minute timeout and logs a non-zero exit (`backend/app/services/resolution_autorun.py:44-58`).
- **replay**
  - First failed batch → stop that file and write the remainder back so the next run continues from there (`backend/scripts/replay_zep_dead_letters.py:94-110`).
  - File-level exception → skip the file and count it as failed (`:150-153`).
- **reclaim** — unreadable files and ambiguous bundles are skipped with a printed reason (`backend/scripts/reclaim_report_space.py:122-143`).
- **architecture_baseline**
  - Exit 3 when the source changes mid-capture. Fixture files already copied stay on disk and no manifest is written (`backend/scripts/architecture_baseline.py:113-160`).
  - Unreadable source files or malformed manifest entries raise uncaught exceptions (traceback, exit 1) (`:117`, `:210-220`).

## Surprises

1. **Suspected bug — CLI-hosted pipelines die when the CLI exits.**
   - `PipelineOrchestrator.start`, `fork_question` and `_launch` all run `_run` in **daemon** threads inside the script process (`backend/app/services/pipeline_orchestrator.py:7969-7977`; `backend/scripts/batch_runs.py:354-361`; `backend/scripts/scheduled_rerun.py:693`).
   - `batch_runs.py run` without `--wait` returns right after forking (`backend/scripts/batch_runs.py:721-723`). Python then exits and kills the anchor's remaining stages and every child pipeline.
   - `scheduled_rerun.py tick` and `run-once` return right after `Scheduler.tick` (`backend/scripts/scheduled_rerun.py:894-910`), killing the just-launched pipeline and its `_await_and_diff` thread. This happens even though the docstring sells `tick` as cron-friendly (`:43`).
   - The killed pipelines stay `running` on disk until a backend restart runs `reconcile_orphans` (`backend/app/__init__.py:140`). Meanwhile they count toward `SCHEDULER_MAX_CONCURRENT` and keep `_schedule_has_inflight` true.
   - The `TaskManager` tasks these scripts create live only in the script's memory (`backend/app/models/task.py:54-71`).
2. **Doc-vs-code drift — batch ontology is regenerated, not reused.**
   - The batch docstring (`backend/scripts/batch_runs.py:4-5`) and the README (`README.md:1606`) say research, ontology and graph run once.
   - The code leaves ONTOLOGY pending with `project_id=None` (`backend/scripts/batch_runs.py:284`, `:289-298`). `_run` therefore creates a new project and ontology for each question (`backend/app/services/pipeline_orchestrator.py:12307-12320`).
   - The `fork_question` docstring says only REPORT runs in shared-simulation mode (`backend/scripts/batch_runs.py:251-253`). Ontology still runs there too, as the comment at `:320` admits. That is an extra LLM call per question.
3. **Suspected — batch children diverge from `PipelineOrchestrator.fork()`.**
   - `fork()` keeps the base's `actor_intelligence_policy_v1` (`backend/app/services/pipeline_orchestrator.py:8321-8326`). `start()` pins `safety_policy_v1` and the actor policy at admission (`:7962-7967`).
   - `fork_question` copies neither (`backend/scripts/batch_runs.py:300-314`). Children fall back to ambient Config for safety flags (`backend/app/services/pipeline_orchestrator.py:8517-8527`) and take the `legacy_run_without_pinned_policy` actor path (`:5678-5687`).
   - Children also share the anchor's `handoff_dir` (`backend/scripts/batch_runs.py:286`). Whether N concurrent children write ontology or prepare artifacts into that shared directory has not been verified.
4. **Stale anchors.** The batch docstring cites `:1392` and `:1476` as the orchestrator's research and graph reuse guards (`backend/scripts/batch_runs.py:7-8`, `:289-290`). Those lines now hold DeerFlow skill-sync code. The real guards are around `backend/app/services/pipeline_orchestrator.py:12394-12455` (graph) and `:12741-12852` (prepare/run).
5. **Questionable aggregation.** `batch_status` sends forecasts for **different questions** into `aggregate_forecasts` (`backend/scripts/batch_runs.py:649-650`). That function is built for N runs of the same question: it matches scenarios by name and renormalizes them to sum to 1 (`backend/app/services/ensemble.py:150-161`). The "combined ensemble" across questions therefore mixes unrelated scenario sets.
6. **Suspected false drift alert.**
   - `_await_and_diff` diffs as soon as the new run is `failed` or `cancelled`, or when the deadline `max(600, DEERFLOW_RESEARCH_TIMEOUT+1800)` passes, which is 12,600 s by default (`backend/scripts/scheduled_rerun.py:738-749`).
   - With no current forecast, every earlier scenario counts as "dropped", so `drift=True` (`:421-424`, `:436-439`) and the webhook fires (`:768-778`).
   - Deep research is budgeted at 21,600 s, or ×1.5 with fan-out (`backend/app/config.py:1553`, `:1559-1578`), so a slow but healthy deep run can produce a spurious "all scenarios vanished" alert.
7. **Knob drift in the scheduler.**
   - The comment block and fallback say `SCHEDULER_TICK_SECONDS=60` (`backend/scripts/scheduled_rerun.py:89`, `:127`), but Config defines 300 (`backend/app/config.py:441`).
   - `SCHEDULER_DEFAULT_MAX_RUNS` is still a ghost knob: it is absent from Config and `.env.example`, so setting it in `.env` has no effect (`backend/scripts/scheduled_rerun.py:134-135`).
   - `SCHEDULER_ENABLED` gates only `daemon` (`:913`). `tick` and `run-once` launch pipelines regardless, which contradicts README's "off by default" (`README.md:1091`) and `.env.example:491`.
   - `Scheduler` docstring says `maybe_start` may be called from `backend/app/__init__.py` ("见文末 skipped 说明"), but there is no such note at the end of the file and no caller.
8. **Scheduler cap counts all runs.** `_running_pipeline_count` counts every `running` pipeline, including ones a user started in the UI (`backend/scripts/scheduled_rerun.py:610-615`). With the default cap of 1, any manual run blocks every scheduled run. `gone_actors` is computed but never contributes to `drift` (`:430`, `:436-439`).
9. **Suspected inconsistency in preflight.**
   - `_append_placeholder_checks` marks a placeholder `LLM_API_KEY` as **blocking** even for `research_only` mode or key-less providers such as `claude-cli` (`backend/scripts/preflight.py:167-176`). `preflight_pipeline` checks the LLM key only in full mode with `needs_key` (`backend/app/services/pipeline_orchestrator.py:6815-6819`, key check at `:6818`).
   - So `?format=full` can say "not ready" while POST /run would accept the run. This contradicts the "can never disagree" claim at `backend/scripts/preflight.py:83-85`.
   - The docstring says the Settings UI renders `?format=full` (`:17-18`). The frontend never sends it (`frontend/src/api/research.js:104-110`).
   - `doctor.sh` comments say preflight.py "reuses the settings.py connectivity helpers" (`scripts/doctor.sh:231-233`, `:260-261`). preflight.py builds its own `OpenAI` client instead (`backend/scripts/preflight.py:224-254`).
10. **Doc bug — `process_diagnostics --signal` can kill the target.** The docstring says SIGUSR1 is "harmless unless the target cooperatively registered a faulthandler" (`backend/scripts/process_diagnostics.py:8-10`). On POSIX, SIGUSR1's default action is to terminate the process, so a target without a handler (any Python process that has not registered one) is killed. With the default `--pid` (the script itself), `--signal` would kill the script before it prints anything (`:83`, `:93`).
11. **Resolution-monitor quirks:**
    - The "Newly resolved markets" section lists **every** currently-resolved anchored market (`records`), not only the rows newly added to the ledger this run (`newly_recorded`) (`backend/scripts/resolution_monitor.py:372-386` vs `:554-570`). Old resolutions appear as "new" on every run.
    - The "Running score" in each report's `monitor_report.md` is ledger-wide, not per report (`:573-574`).
    - `_cmd_run` returns 0 even when individual reports failed (`:687`).
    - `resolve_report_id` does not validate the id, so an input such as `../pipelines` resolves to an existing directory, and `price_track.jsonl` / `monitor_report.md` are then written outside `reports/` (`:131-133`, `:557`, `:586`). Risk is low because this is CLI-only and the API only uses `--all-recent`.
12. **Replay quirks:**
    - `--limit` is checked before each batch, so it can overshoot by up to `batch_size-1` (`backend/scripts/replay_zep_dead_letters.py:85-86`).
    - There is a small window between reading the "appended during replay" lines (`:101-105`) and the `os.replace` (`:110`/`:113`). A dead-letter append in that window goes to the replaced inode and is lost. The docstring recommends running when no simulation is active.
    - `return 2` after `ap.error` is unreachable (`:135-136`).
    - Replay spends Graphiti LLM extraction on every episode (see External calls).
13. **`reclaim_report_space` accounting.**
    - `freed` counts characters, not bytes (`backend/scripts/reclaim_report_space.py:144`).
    - It ignores the ~4.6 MB `plotly.min.js` written once per charts directory (`:148-152`), so "reclaimed" is overstated by about one bundle per report.
    - In dry-run, `bundle_size` stays None, so later files in a directory are never size-checked and the "would rewrite" count can exceed what `--apply` actually does (`:118`, `:140`, `:148-152`).
14. **`check_env_drift` blind spots.**
    - Only `os.environ.get` and `os.environ[...]` in `config.py` are seen. `os.getenv` and env reads in other modules are not (`backend/scripts/check_env_drift.py:54`, `:103-109`). Script-level knobs such as `BATCH_WAIT_TIMEOUT_S` are only "documented but unread".
    - Commented `# X=` lines count as documented (`:55`).
    - `_normalize` treats `6` and `6.0` as divergent (`:198-211`).
15. **Dead and duplicated code.**
    - `_TERMINAL_STATUSES` is never used (`backend/scripts/batch_runs.py:96`).
    - `_wait_for_graph` and `_wait_for_simulation` duplicate the same poll loop (`backend/scripts/batch_runs.py:191-229` vs `:535-562`).
    - `_cfg_int` and `_cfg_float` are copied between `scheduled_rerun.py:100-111` and `resolution_monitor.py:55-66`.
    - `disk_usage_report.py` hardcodes `backend/uploads` instead of using `Config.UPLOAD_FOLDER` (`backend/scripts/disk_usage_report.py:17-24`). The paths agree today (`backend/app/config.py:1048`). It skips `deer-flow/` caches and HF caches.
16. **Doc drift in neighbouring modules.**
    - `forecast_ledger`'s docstring says `scheduled_rerun.py` can use `due_for_resolution` (`backend/app/services/forecast_ledger.py:11-12`). `scheduled_rerun.py` never calls it.
    - `test_forecast_diff.py:2` says "the rest of scheduled_rerun imports lazily". The script imports `PipelineManager`, `PipelineOrchestrator` and `ReportManager` at module top level (`backend/scripts/scheduled_rerun.py:69-77`).
17. **Branding drift.** preflight's argparse description and docstring still say "DeepAgentForecast" (`backend/scripts/preflight.py:2`, `:463`). That repository was archived; see the project memory.
