# api-core — Research, graph and report HTTP APIs

Slice: `backend/app/api/research.py` (921 lines), `backend/app/api/graph.py` (725 lines), `backend/app/api/report.py` (2176 lines). Branch `main`, read in full from disk on 2026-10-11.

Anchor convention: `research.py:N`, `graph.py:N` and `report.py:N` mean `backend/app/api/<file>:N`. Every other anchor is a full path relative to the repo root.

The slice has **61 routes**: 18 under `/api/research`, 14 under `/api/graph` and 29 under `/api/report`. The full catalog is in the route tables at the start of each walkthrough section.

## Purpose & position in the pipeline

These three Flask blueprints are the HTTP surface for the staged forecasting pipeline. They do almost no domain work themselves. They validate the request, check publication or state gates, call into services (`PipelineOrchestrator`/`PipelineManager`, `GraphBuilderService`, `ReportAgent`/`ReportManager`, `ExecBriefBuilder`), and, for long jobs, start a daemon `threading.Thread` and return a task id for polling.

- **`/api/research`** (`research_bp`, registered at `backend/app/__init__.py:204`) is the main entry point. `POST /run` starts the whole research → ontology → graph → prepare → run → report pipeline through `PipelineOrchestrator.start` (`research.py:109`). Its other routes handle lifecycle (cancel, resume, continue, fork, delete, clean), status and progress polling, the research dossier (read, edit, translate, PDF), and stage artifact deep links.
- **`/api/graph`** (`graph_bp`, `backend/app/__init__.py:201`) is MiroFish's original manual project → ontology → graph flow: multipart upload, LLM ontology, then a background graph build. It also hosts the read side that the UI's graph panel uses for every pipeline: `/data/<graph_id>` plus neighbors, node and edge detail. It has GC and delete endpoints.
- **`/api/report`** (`report_bp`, `backend/app/__init__.py:203`) has the manual report-generation path (`POST /generate`, ReACT `ReportAgent` in a thread) and the read side for every report. That read side covers metadata, the structured forecast, Markdown, bilingual variants, PDF, exec brief/digest, charts and the viz manifest, progressive sections, agent and console logs, and chat. Almost every customer-facing read sits behind the **publication barrier** (`ReportManager.publication_status`, `backend/app/services/report_agent.py:12435`) or the **draft-exposure gate** (`_draft_exposure_gate`, `report.py:153`).

Cross-cutting gates applied by the app factory, not by this slice:

- **Auth.** Every `/api/*` request from a non-loopback address, or one carrying forwarded headers, needs `X-API-Token == Config.APP_API_TOKEN`. Without a token it fails closed with 403 (`backend/app/__init__.py:154-172`). [verifier: forwarded headers only downgrade trust when one of the forwarded client addresses is non-loopback (`backend/app/__init__.py:80-81,161`); a configured token that does not match gives 401, not 403 (`backend/app/__init__.py:169-171`); OPTIONS requests bypass the gate (`backend/app/__init__.py:156-157`)]
- **CORS.** `/api/*` is limited to `APP_CORS_ORIGINS` (`backend/app/__init__.py:111-116`; default list at `backend/app/config.py:45-48`).
- **Traceback stripping.** When `FLASK_DEBUG` is off, a `traceback` key in any JSON response is removed (`backend/app/__init__.py:189-196`). The many `"traceback": traceback.format_exc()` fields in this slice are therefore only visible in debug mode.
- **No global `errorhandler`.** A grep of `backend/app` finds none, so an uncaught exception in a handler that lacks a try/except becomes Flask's default HTML 500, not the `{"success": false}` JSON envelope.
- **Upload cap.** `MAX_CONTENT_LENGTH = 50 MiB` (`backend/app/config.py:1047`) is loaded through `app.config.from_object` (`backend/app/__init__.py:89`).

## Walkthrough (source order)

### A. `backend/app/api/research.py` — `/api/research`

| # | Method | Path | Handler | Background work | Primary service call |
|---|---|---|---|---|---|
| 1 | POST | `/run` | `run_pipeline` research.py:50 | pipeline thread (via orchestrator) | `PipelineOrchestrator.start` research.py:109 |
| 2 | POST | `/<pipeline_id>/cancel` | `cancel_pipeline` research.py:132 | — | `PipelineOrchestrator.cancel` research.py:136 |
| 3 | POST | `/<pipeline_id>/resume` | `resume_pipeline` research.py:147 | pipeline thread | `PipelineOrchestrator.resume` research.py:164 |
| 4 | POST | `/<pipeline_id>/continue` | `continue_pipeline` research.py:184 | pipeline thread | `PipelineOrchestrator.continue_to_full` research.py:199 |
| 5 | POST | `/<pipeline_id>/scenario` | `fork_scenario` research.py:219 | pipeline thread (new id) | `PipelineOrchestrator.fork` research.py:240 |
| 6 | DELETE | `/<pipeline_id>` | `delete_pipeline` research.py:260 | — (sync rmtree + graph GC) | `PipelineOrchestrator.delete_pipeline` research.py:269 |
| 7 | POST | `/clean` | `clean_pipelines` research.py:287 | — | `PipelineOrchestrator.clean_terminal` research.py:299 |
| 8 | GET | `/status/<pipeline_id>` | `pipeline_status` research.py:306 | — (polling) | `PipelineManager.load` + `heartbeat_status` research.py:314-318 |
| 9 | GET | `/list` | `list_pipelines` research.py:337 | — | `PipelineManager.list_pipelines` research.py:339 |
| 10 | POST | `/resolution-monitor/run` | `run_resolution_monitor` research.py:342 | thread → subprocess | `resolution_autorun.trigger_once` research.py:350 |
| 11 | GET | `/preflight` | `preflight` research.py:355 | — | `preflight_pipeline` / `scripts/preflight.environment_report` |
| 12 | GET | `/<pipeline_id>/dossier` | `get_dossier` research.py:389 | — | file reads |
| 13 | POST | `/<pipeline_id>/dossier/translations/<lang>` | `start_research_translation` research.py:555 | translation thread (LLM) | `_run_research_translation` research.py:585-587 |
| 14 | GET | `/<pipeline_id>/dossier/translations/<lang>` | `get_research_translation` research.py:593 | — (polling) | file reads |
| 15 | GET | `/<pipeline_id>/dossier/pdf` | `get_research_pdf` research.py:636 | — (sync pandoc/xelatex) | `ReportManager.export_document_pdf` research.py:677 |
| 16 | PUT | `/<pipeline_id>/dossier` | `edit_dossier` research.py:690 | — | atomic writes + `refresh_research_artifact_manifest` |
| 17 | GET | `/<pipeline_id>/artifact/<name>` | `get_artifact` research.py:779 | — (file serving) | registry lookup in `pipeline_state.json` |
| 18 | GET | `/<pipeline_id>/progress` | `get_progress_log` research.py:871 | — (polling) | `merged_research_progress_tail/_full` research.py:896-900 |

**Module docstring** (research.py:1-15) lists only 9 routes. It omits continue, scenario, preflight, resolution-monitor, dossier PUT, translations, pdf and artifact; see Surprises.

**Module constants** (research.py:41-47).
- `_VALID_DEPTH = {"quick","standard","deep"}`
- `_VALID_MODE = {"full","research_only"}`
- `_VALID_LANGUAGES = {"Chinese","English","auto"}`
- `MIN_DOSSIER_CHARS = 400`: the minimum size for a human-edited research report. The comment says it mirrors the orchestrator's research_report ≥ 400 reuse guard.

**1. `run_pipeline`** (research.py:50-129). `POST /api/research/run`.
- Body (JSON, parsed silently, research.py:62): `prompt` (required, stripped, else 400 at research.py:64-65); `mode` (default `full`, lowercased, must be in `_VALID_MODE`, research.py:67-69).
- `depth` defaults to **`Config.DEERFLOW_RESEARCH_DEPTH`**, which is `'deep'` (`backend/app/config.py:1159`) and not the "standard" the docstring claims (research.py:58). It is validated against `_VALID_DEPTH` (research.py:71-73).
- `max_rounds` is int-coerced, else 400 (research.py:75-80). There is no range check.
- `language` is accepted under either key, `language` or `research_language` (research.py:86). It must be in `_VALID_LANGUAGES` (research.py:87-88). `'auto'` is turned into `''`, which means "do not pass `--target-language`" (research.py:89-90). A missing value stays `None`, which means use the Config default.
- `model` is lowercased and must be in `Config.SUPPORTED_DEERFLOW_MODELS` = `('claude','codex','minimax','deepseek','qwen','glm','kimi','antigravity')` (research.py:91-98; `backend/app/config.py:1544`).
- `project_name` is passed through unvalidated (research.py:112).
- **Preflight gate:** `preflight_pipeline(mode, model)`. Any errors give 400 with `error` (a bulleted string) and `preflight_errors` (a list) (research.py:101-107). `preflight_pipeline` (`backend/app/services/pipeline_orchestrator.py:6779`) runs cheap local checks only (no network, per its docstring at `backend/app/services/pipeline_orchestrator.py:6780-6783`).
- On success it calls `PipelineOrchestrator.start(...)` (research.py:109-117) and returns `{success, data:{pipeline_id, task_id, mode, status}}` (research.py:118-126).
- `start` (`backend/app/services/pipeline_orchestrator.py:7920-7979`):
  - mints `pipe_<12 hex>`;
  - creates dirs and an in-memory `TaskManager` task of type `pipeline:<mode>`;
  - stores `options` (`project_name`, `depth`, `max_rounds`, `research_language`, `research_model`), pins the `actor_intelligence_policy_v1` and `safety_policy_v1` snapshots, and saves `pipeline_state.json`;
  - starts the daemon thread `pipeline-<id>` running `_run`.
- Any exception gives 500 with `error` and `traceback` (research.py:127-129).
- A non-string `prompt`, `mode`, `depth` or `language` raises `AttributeError` on `.strip()`, which the outer except catches and returns as 500, not 400.

**2. `cancel_pipeline`** (research.py:132-144). Calls `PipelineOrchestrator.cancel(pipeline_id)`.
- `not_found` → 404; `not_running` → 409 (research.py:137-140); otherwise 200 with `{ok, status}`, where `status ∈ {cancelling, cancelled}`.
- Semantics (`backend/app/services/pipeline_orchestrator.py:7982-8016`), under `_lifecycle_lock`:
  - If the pipeline's thread is alive in this process, it sets the cancel `Event` and returns `cancelling`.
  - If not (an orphan after a restart), it calls `mark_failed(..., status="cancelled")`, fails the task, and returns `cancelled`.

**3. `resume_pipeline`** (research.py:147-181).
- `PipelineManager.load` returns `None` → 404 (research.py:151-153).
- Preflight runs with the stored mode (research.py:154-160). [verifier: it is called without `model`, so the research-model credential check uses `Config.DEERFLOW_MODEL`, not the pipeline's stored `options.research_model` (research.py:154; `backend/app/services/pipeline_orchestrator.py:6834`)]
- Body `{force?: bool}` (research.py:163). `force=true` allows resuming a *completed* pipeline whose `options.pipeline_health.status ∈ {degraded, failed}`; only REPORT is reset (`backend/app/services/pipeline_orchestrator.py:8143-8165`).
- `FileNotFoundError` → 404. `RuntimeError` → 409; this includes `IncompatiblePipelineSchema`, which subclasses `RuntimeError` (`backend/app/services/pipeline_orchestrator.py:274`), and the "still running" and "already completed" cases. Anything else → 500 (research.py:175-181).
- Returns `{pipeline_id, task_id, mode, status, resumed:true}`.
- Side effects (`backend/app/services/pipeline_orchestrator.py:8107-8211`): a new task id `pipeline:<mode>:resume`; `resume_count` is incremented; a safety policy is pinned if missing; the same pipeline id is reused; the thread is `pipeline-resume-<id>`.
- A running pipeline whose owner process is dead is reclaimed in place (`backend/app/services/pipeline_orchestrator.py:8132-8142`).

**4. `continue_pipeline`** (research.py:184-216). Turns a completed `research_only` pipeline into a `full` one.
- Always preflights with `mode="full"` (research.py:192).
- `continue_to_full` (`backend/app/services/pipeline_orchestrator.py:8214-8277`) requires `mode == research_only`, `status == completed`, and a non-empty `research_report.md` under the **static** handoff dir. Any other case raises `RuntimeError` → 409.
- It flips the mode, resets the non-research stages, sets `current_stage = ontology`, and starts the thread `pipeline-continue-<id>`.
- Returns `{..., continued:true}`.

**5. `fork_scenario`** (research.py:219-257). A what-if fork at PREPARE.
- The base must exist (404 otherwise, research.py:227-229). `label` is required and must be non-blank (400, research.py:231-232). Preflight runs with `full` (research.py:233).
- The whole JSON body is passed as `overlay` to `PipelineOrchestrator.fork` (research.py:240). The API does not validate overlay fields.
- `fork` (`backend/app/services/pipeline_orchestrator.py:8280-8350`):
  - requires `base_state.graph_id` (`RuntimeError` → 409 otherwise);
  - mints a new `pipe_` id that **shares the base's handoff dir**;
  - marks research, ontology and graph completed and starts `pipeline-scenario-<new_id>`;
  - int-coerces `overlay.max_rounds` and silently ignores bad values.
- Returns `{pipeline_id, base_pipeline_id, task_id, label, status}` (research.py:241-250).

**6. `delete_pipeline`** (research.py:260-284). `DELETE /api/research/<id>[?force=1|true|yes]`.
- `delete_pipeline` (`backend/app/services/pipeline_orchestrator.py:8043-8086`) maps to these responses:
  - `still_running` (a live thread in this process) → 409;
  - `not_found` → 404;
  - `has_dependents` (forks whose `options.base_pipeline_id` equals this id), unless `force` → 409 with `data.dependents` (research.py:274-280);
  - otherwise it deletes and returns 200 with `{ok, status:"deleted"}`.
- Side effects: `shutil.rmtree(uploads/pipelines/<id>)` (`backend/app/services/pipeline_orchestrator.py:1200`). A persisted-`running` orphan is marked cancelled first and its research PIDs are killed (`:8071-8078`). On success the orchestrator calls `_gc_stale_graphs()` (`backend/app/services/pipeline_orchestrator.py:8085`), which can **delete graphs** from the graph store.
- Pipeline ids are regex-validated (`^pipe_[A-Za-z0-9_-]+$`, `backend/app/services/pipeline_orchestrator.py:865-872`). A malformed id makes `load` return `None` (`:1137-1140`) → 404, so this route is traversal-safe.

**7. `clean_pipelines`** (research.py:287-303). Body `{statuses?}`, default `["failed","cancelled"]` (research.py:292).
- `statuses` must be a non-empty list whose items are all in `{failed, cancelled}`; otherwise 400 (research.py:293-298).
- `clean_terminal` (`backend/app/services/pipeline_orchestrator.py:8089-8104`) calls `delete_pipeline(pid)` with `force=False` for each matching pipeline, so bases with forks are skipped. Returns `{deleted:[...], skipped:[...]}`.

**8. `pipeline_status`** (research.py:306-334). The main polling endpoint.
- Reads `pipeline_state.json` through `PipelineManager.load`; `None` → 404 (research.py:314-316). Because the state is on disk, it survives a backend restart.
- It then adds a computed `live` block, best effort (research.py:317-330):
  - `PipelineOrchestrator().heartbeat_status(PipelineState.from_dict(data))` returns `elapsed_s/eta_s/eta_approximate/stale/last_progress_age_s` (from `estimate_eta`), `owner_pid`, `owner_alive`, `heartbeat_age_s`, and, when telemetry has non-zero data **in this process**, `spend_so_far{tokens,cost_usd}` (`backend/app/services/pipeline_orchestrator.py:10302-10327`).
  - If `Config.LLM_RUN_BUDGET_TOKENS > 0` (default 0, `backend/app/config.py:64`), it adds `live.budget{limit_tokens, spent_tokens, remaining_tokens}` (research.py:319-326).
  - Any exception only drops `live`, logged at debug level (research.py:329-330).
- Response headers: `Cache-Control: no-store, max-age=0`, `Pragma: no-cache` (research.py:332-333).
- A state file written by a **newer** schema loads as a minimal sentinel dict carrying `__incompatible_schema__` (`backend/app/services/pipeline_orchestrator.py:1152-1163`). This endpoint returns that sentinel with 200, even though the `load()` comment says the API should map it to 409.

**9. `list_pipelines`** (research.py:337-339). Returns `{pipelines:[{pipeline_id,status,prompt,global_progress,created_at,report_id}]}`, newest first (`backend/app/services/pipeline_orchestrator.py:1204-1221`). Every call parses every state file. There is no pagination.

**10. `run_resolution_monitor`** (research.py:342-352).
- `resolution_autorun.trigger_once()` (`backend/app/services/resolution_autorun.py:63-80`) dedupes in-flight runs with a module-level flag and lock, then starts the daemon thread `resolution-monitor-once`.
- That thread runs the subprocess `[sys.executable, backend/scripts/resolution_monitor.py, "run", "--all-recent"]` with a **15-minute timeout** (`backend/app/services/resolution_autorun.py:28,37-62`).
- Responses: 202 `{started:true}`, or 409 `{inflight:true}`.

**11. `preflight`** (research.py:355-386). `GET /api/research/preflight?mode=&format=&deep=&model=`.
- An unknown `mode` is coerced to `full` (research.py:364-366).
- With `format=full`, it prepends `backend/scripts` to `sys.path` **permanently** (research.py:372-376), imports `preflight.environment_report`, and returns its structured document (research.py:377-381).
  - `deep=1|true|yes` adds live credential, embed-cache and disk probes, which may make network calls (`backend/scripts/preflight.py:93-94`).
  - `model` is passed through **without** the `SUPPORTED_DEERFLOW_MODELS` check used by `/run`.
  - Any import or runtime error logs a warning and falls back to the compact response (research.py:382-383).
- Compact response: `{ready, errors, mode}` from `preflight_pipeline(mode)`. The `model` arg is ignored in this branch (research.py:385-386).

**12. `get_dossier`** (research.py:389-441).
- Uses `PipelineManager.resolve_handoff_dir(pipeline_id)` (research.py:392). For forks this resolves to the base's shared handoff dir when `state.handoff_dir` realpath-resolves under `PIPELINE_DATA_DIR`; otherwise it falls back to `uploads/pipelines/<id>/handoff` (`backend/app/services/pipeline_orchestrator.py:888-912`). A missing dir → 404 (research.py:393-394).
- Reads `research_report.md`, `actors.json`, `sources.json`, `timeline.json`, `quantitative.json`, `contested.json`, `prediction_markets.json` and `charts.json` (research.py:407-414). An unreadable file gives `None`; undecodable JSON gives `None` (research.py:396-420).
- Returns `{report, actors, sources, timeline, quantitative, contested, prediction_markets, charts, has_report, sealed}`. `sealed` comes from `research_dossier_is_sealed(handoff)` (research.py:438-439; `backend/app/services/pipeline_orchestrator.py:3423-3441`): true if the research contract manifest, an actor-intelligence lineage file, or `actors.json.actor_intelligence_contract` exists.
- Research dossiers are **not** behind any publication audit.
- There is no try/except. A malformed pipeline id makes `resolve_handoff_dir` raise `ValueError` (`backend/app/services/pipeline_orchestrator.py:895`, via `_validate_id` at `:868-872`), which becomes an HTML 500, not a 404 (suspected; see Surprises).

**Research translation helpers** (research.py:444-552).
- `_RESEARCH_TRANSLATION_LANGS = ("en","zh")` (research.py:444). There is a process-local lock and an in-flight set of `(pipeline_id, lang)` (research.py:445-446).
- `_research_report_paths(handoff, lang)` (research.py:449-457) returns `research_report.md`, `research_report.<lang>.md`, `research_report.final_audit.<lang>.json`, `research_report.translation.<lang>.json` (the status file) and `research_report.<lang>.pdf`.
- `_research_source_sha` (research.py:460-466) is the SHA-256 of the source bytes, or `None`.
- `_write_research_status` (research.py:469-477) writes atomically (tmp + `os.replace`) and only warns on `OSError`. `_read_research_status` (research.py:480-487) returns a dict or `None`.
- `_run_research_translation(pipeline_id, lang)` (research.py:490-552) is the **background worker**:
  - It builds a bare `ReportAgent.__new__` with a fresh `LLMClient()`, `output_language="English"` and `_forecast_spine=None` (research.py:510-513), then calls `translate_research_markdown(md, label="research::<pid>")` (research.py:514).
  - That method auto-detects the source and target languages and runs the LLM chunk translation, contamination repair and lint-to-fixed-point (`backend/app/services/report_agent.py:7732-7821`).
  - If the detected `tgt` differs from the requested `lang`, it records `failed` with "requested language is not this report's translation target" (research.py:515-520). This check runs **after** the LLM spend.
  - If the result is unavailable, it writes the audit sidecar and a `failed` status with up to 12 issues (research.py:522-531).
  - If the result is available, it writes the audit and then the variant Markdown atomically, then the status `{status:"available", source_sha256, target_lang, source_lang}` (research.py:532-543).
  - Any exception gives a `failed` status with the exception type name (research.py:544-549). `finally` removes the in-flight key (research.py:550-552).

**13. `start_research_translation`** (research.py:555-590).
- `lang` is lowercased and must be `en` or `zh` (400 otherwise). A missing handoff or source → 404 (research.py:559-567).
- If the status is `available`, its `source_sha256` matches the current source, and the variant exists, it returns 200 with that status (research.py:569-574).
- If the key is already in the in-flight set, it returns 202 `generating` (research.py:575-579).
- Otherwise it adds the key, writes a `generating` status with `owner: "pid:<os.getpid()>"`, starts the daemon thread, and returns 202 (research.py:580-590).
- Deduplication is **per process only**. It ignores a `generating` status written by another live process. Unlike the report translation route, there is no file lock or lease.

**14. `get_research_translation`** (research.py:593-633). A polling endpoint.
- If the status is `generating` but `ReportManager._translation_owner_alive(owner)` is False, it reports `interrupted` (research.py:606-615). That check returns False only when a `pid:N` owner no longer exists (`backend/app/services/report_agent.py:12137-12149`).
- It returns the variant Markdown only when the status is `available`, the SHA matches, and the file exists (research.py:617-625).
- Response: `{status, available: bool(report_md), issues, source_lang, target_lang, report}` (research.py:626-633).
- After the dossier is edited, `status` can still read `"available"` while `available` is false.

**15. `get_research_pdf`** (research.py:636-687). `?lang=en|zh` is optional; any other value → 400.
- With `lang`, it needs a hard-passed status with a matching SHA and an existing variant, or it returns 409 fail-closed (research.py:652-661). It renders `research_report.<lang>.md` to `research_report.<lang>.pdf`.
- Without `lang`, it renders `research_report.md` to `research_report.pdf` (research.py:665-668).
- It calls `ReportManager.export_document_pdf(md, handoff, out_pdf, label)` synchronously (research.py:677). That method returns `None` when `REPORT_PDF_EXPORT` is off or the Markdown is blank. Otherwise it rewrites chart paths, pre-renders Mermaid, **unlinks the existing PDF**, renders with pandoc+xelatex (falling back to PyMuPDF) and runs a content-integrity gate (`backend/app/services/report_agent.py:13597-13640`).
- An exception → 500 `{code:"pdf_internal_error"}`. No output → 500 "PDF 生成失败", even when the cause is the disabled flag, where the report PDF route returns 503. Success → `send_file(..., as_attachment=True, download_name="research_report[.<lang>].pdf")` (research.py:684-687).
- There is no cache and no lock: every GET rebuilds.

**16. `edit_dossier`** (research.py:690-774). `PUT /api/research/<id>/dossier` with body `{report?: str, actors?: any}`.
- Allowed only when `(status=="completed" and mode=="research_only")` or `(status in {failed,cancelled} and stages.graph.status != "completed")`; otherwise 409 (research.py:706-714).
- A missing handoff dir → 404 (research.py:717-719). A sealed dossier → 409 `{sealed:true}` with a bilingual message (research.py:720-732).
- A `report` string shorter than `MIN_DOSSIER_CHARS` (400) after stripping → 400 (research.py:736-744).
- Writes are atomic via tmp + `os.replace` (research.py:746-751) to `research_report.md` and/or `actors.json`. `actors` can be any JSON value; there is no schema check (research.py:758-760). If nothing was written → 400 (research.py:764-765).
- It then calls `refresh_research_artifact_manifest(pipeline_id, handoff, wrote)`, which updates the `handoff/manifest.json` entries with new sha/bytes and `human_edited_at` so that resume reuse accepts the edit (`backend/app/services/pipeline_orchestrator.py:3444-3474`). If the refresh fails → 500, explicitly saying the edit was written but may be re-run over (research.py:766-773).
- Returns `{updated:[...]}`.

**17. `get_artifact`** (research.py:779-868). A stage-artifact deep link.
- The pipeline must exist (404 otherwise). The lookup is `state.artifacts[name]`, whose values are **absolute paths** written by `_record_stage_artifacts` / `_register_partial_artifacts` (`backend/app/services/pipeline_orchestrator.py:9703-9755,10217-10247`). [verifier: `_register_partial_artifacts` spans `backend/app/services/pipeline_orchestrator.py:10208-10240` (10242+ is `estimate_eta`); the partial names themselves come from `_discover_partial_artifacts` at `:10157-10206`]
- Fallbacks for `chart_*` names (research.py:787-800): first `artifacts[name+"_partial"]`; then, for fork pipelines whose registry is empty, `<resolved handoff>/charts/<rest>` if that path exists.
- A missing path → 404 (research.py:801-802).
- Asset extensions `.png/.svg/.jpg/.jpeg/.webp/.html` are served as raw bytes with a mimetype (research.py:806-815). For `chart_*` names only, it **re-validates at serve time** (research.py:816-833). Each of these gives 404:
  - the basename differs from the name suffix;
  - the realpath basename differs;
  - the path is a symlink;
  - it is not a regular file;
  - it is outside `realpath(handoff)/charts`.
- `.html` files have the sibling `plotly.min.js` inlined (`inline_plotly_bundle`, `backend/app/utils/chart_html.py:30-49`) and get `CSP: sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; …; connect-src 'none'` plus `nosniff` and `no-referrer` (research.py:836-852). `.svg` gets `CSP: sandbox; script-src 'none'` (research.py:853-859).
- Any other extension is read as UTF-8 text. `.json` is parsed and returned as `{name, content}` (research.py:861-866). Any exception → 500.
- `report_chart_*` and `section_NN_partial` keys are **not** re-validated or gated; see Surprises.

**18. `get_progress_log`** (research.py:871-921). `?scope=tail|full&lines=N`.
- The pipeline must exist (404). A `ValueError` from `resolve_handoff_dir` → 404 (research.py:882-887). A bad `scope` → 400 (research.py:888-890). `lines` falls back to 200 if not an int (research.py:891-894).
- `tail` calls `merged_research_progress_tail(handoff, limit)`, which clamps `limit` to [1, 500] (`backend/app/services/research_progress.py:502`). It reads at most 256 KiB from the end of each file (`:70,395-415`) and merges root, `track_N` and `research_attempts/*.log` sources chronologically with dedup (`:418-517`).
- `full` reads everything and raises `ResearchProgressLimitError` above 16 tracks, 16 attempts or 64 MiB total. That error → **413** (research.py:918-919; limits at `backend/app/services/research_progress.py:67-72`).
- Response: `{scope, lines, returned, total (exact only for full; None for tail), total_exact, snapshot_exact, event_fidelity:"summarized_progress_events", source_count, truncated}`, with no-store headers (research.py:902-917).

### B. `backend/app/api/graph.py` — `/api/graph`

| # | Method | Path | Handler | Background work | Primary service call |
|---|---|---|---|---|---|
| 1 | GET | `/project/<project_id>` | `get_project` graph.py:35 | — | `ProjectManager.get_project` |
| 2 | GET | `/project/list` | `list_projects` graph.py:54 | — | `ProjectManager.list_projects` |
| 3 | DELETE | `/project/<project_id>` | `delete_project` graph.py:69 | — | `ProjectManager.delete_project` (rmtree) |
| 4 | POST | `/project/<project_id>/reset` | `reset_project` graph.py:88 | — | `ProjectManager.save_project` |
| 5 | POST | `/ontology/generate` | `generate_ontology` graph.py:121 | — (sync LLM) | `OntologyGenerator.generate` graph.py:216-221 |
| 6 | POST | `/build` | `build_graph` graph.py:259 | `build_task` thread graph.py:374-512 | `GraphBuilderService` (create/ontology/add/layout) |
| 7 | GET | `/task/<task_id>` | `get_task` graph.py:533 | — (polling) | `TaskManager.get_task` |
| 8 | GET | `/tasks` | `list_tasks` graph.py:552 | — | `TaskManager.list_tasks` (**broken**, see Surprises) |
| 9 | GET | `/data/<graph_id>` | `get_graph_data` graph.py:576 | — (UI polls) | `GraphBuilderService.get_graph_data` |
| 10 | GET | `/data/<graph_id>/neighbors/<node_uuid>` | `get_graph_neighbors` graph.py:621 | — | `get_node_neighborhood` |
| 11 | GET | `/data/<graph_id>/node/<node_uuid>` | `get_graph_node_detail` graph.py:642 | — | `get_node_detail` |
| 12 | GET | `/data/<graph_id>/edge/<edge_uuid>` | `get_graph_edge_detail` graph.py:659 | — | `get_edge_detail` |
| 13 | POST | `/gc` | `gc_stale_graphs` graph.py:676 | — (sync deletes) | `GraphBuilderService.gc_stale_graphs` |
| 14 | DELETE | `/delete/<graph_id>` | `delete_graph` graph.py:700 | — | `GraphBuilderService.delete_graph` |

- **`allowed_file(filename)`** (graph.py:25-30). The extension, lowercased with the dot stripped, must be in `Config.ALLOWED_EXTENSIONS = {'pdf','md','txt','markdown'}` (`backend/app/config.py:1049`).
- **Project routes** (graph.py:35-116). Projects live at `uploads/projects/<project_id>/project.json` (`backend/app/models/project.py:105-120`). `ProjectManager` does **no id validation** (`backend/app/models/project.py:113-115`).
  - `get_project` → 404 if missing. A corrupt JSON file raises outside any try/except, giving an HTML 500.
  - `list_projects?limit=50` returns `{data:[...], count}`, newest first.
  - `delete_project` calls `shutil.rmtree(uploads/projects/<id>)` (`backend/app/models/project.py:236-242`); false → 404.
  - `reset_project` sets status to `ontology_generated` if an ontology exists, else `created`, and clears `graph_id`, `graph_build_task_id` and `error` (graph.py:101-110). It does **not** delete the graph or stop an in-flight build thread.
- **`generate_ontology`** (graph.py:121-254). Multipart form: `files[]`, `simulation_requirement` (required → 400), `project_name` (default `'Unnamed Project'`), `additional_context`.
  - No files → 400 (graph.py:167-172).
  - It creates a project and then, for each allowed file, `ProjectManager.save_file_to_project`, which saves it under a random 8-hex name plus the original extension (`backend/app/models/project.py:245-276`). It then runs `FileParser.extract_text` and `TextProcessor.preprocess_text`, and concatenates the results with `=== <filename> ===` headers (graph.py:183-200). Files with disallowed extensions are skipped silently.
  - If no file was processed, the project is deleted → 400 (graph.py:202-207).
  - It saves `extracted_text.txt` (graph.py:211) and then makes a **synchronous LLM call**, `OntologyGenerator().generate(document_texts, simulation_requirement, additional_context)` (graph.py:216-221).
  - It stores `{entity_types, edge_types}` and `analysis_summary`, sets the status to `ontology_generated` (graph.py:228-234), and returns `{project_id, project_name, ontology, analysis_summary, files, total_text_length}`.
  - An exception → 500. A project created before the failure is **left behind** in `created` state.
- **`build_graph`** (graph.py:259-528). JSON body `{project_id (required), graph_name?, chunk_size?, chunk_overlap?, force?}`.
  - The `Config.ZEP_API_KEY` check (graph.py:287-294) is effectively dead. The key defaults to the sentinel `'local-graphiti'` (`backend/app/config.py:1038`).
  - Missing `project_id` → 400; unknown project → 404. Status `created` → 400. Status `graph_building` without `force` → **400** (not 409) with `task_id` (graph.py:318-329).
  - `force` resets `graph_building`, `failed` or `graph_completed` back to `ontology_generated` (graph.py:332-336).
  - `chunk_size` and `chunk_overlap` default to `project.chunk_size or Config.DEFAULT_CHUNK_SIZE` (graph.py:340-341). Because `Project.chunk_size` defaults to **500** and `chunk_overlap` to **50** (`backend/app/models/project.py:49-50`), the Config defaults of 2500/250 (`backend/app/config.py:1055-1057`) are never used here. See Surprises.
  - Missing extracted text or ontology → 400 (graph.py:348-361).
  - It creates the task with `TaskManager().create_task(f"构建图谱: {graph_name}")`, so the task_type string is the label (graph.py:364-365). It saves the project as `graph_building` and starts the daemon thread `build_task` (graph.py:511-512).
  - Returns `{project_id, task_id, message}`.
  - **`build_task`** (graph.py:374-508) reports this progress ladder through `task_manager.update_task`:

    | Progress | Step | Anchor |
    |---|---|---|
    | 5 | `TextProcessor.split_text` | graph.py:388-397 |
    | 10 | `builder.create_graph(name)`, which mints `mirofish_<16 hex>`; `project.graph_id` is saved | graph.py:401-410; `backend/app/services/graph_builder.py:1221-1231` |
    | 15 | `set_ontology` | graph.py:413-418 |
    | 15→55 | `add_text_batches(graph_id, chunks, batch_size=3, progress_callback)` | graph.py:429-440 |
    | 55→90 | `_wait_for_episodes`, now a no-op that reports 1.0 because local Graphiti ingest is synchronous | graph.py:443-457; `backend/app/services/graph_builder.py:2427-2443` |
    | — | `compute_layout(graph_id)` if `GRAPH_LAYOUT_PRECOMPUTE`, which persists `positions.json` | graph.py:460-461 |
    | 95 | `get_graph_data` | graph.py:464-469 |
    | 100 | project → `graph_completed`; task `completed` with result `{project_id, graph_id, node_count, edge_count, chunk_count}` | graph.py:472-492 |

    Any exception sets the project to `failed` with `error`, and the task to `failed` with the traceback in `error` (graph.py:494-508).
  - This manual path does **not** seed actors, prune, or run community detection the way the orchestrator's graph stage does.
- **`get_task` / `list_tasks`** (graph.py:533-563). Both use the in-memory singleton `TaskManager` (`backend/app/models/task.py:54-71`), so tasks are lost on restart.
  - `get_task` returns `task.to_dict()` (404 if missing).
  - `list_tasks` calls `t.to_dict()` on each element, but `TaskManager.list_tasks` already returns **dicts** (`backend/app/models/task.py:164-170`). The route therefore raises `AttributeError` (an HTML 500) whenever at least one task exists. Suspected bug.
- **`_parse_bool_arg(name, default)`** (graph.py:568-573). `1/true/yes/on` → True; empty → default.
- **`get_graph_data`** (graph.py:576-618). Query `top_k`, `min_degree` (int; an unparsable value becomes `None`), `slim`, and `full`, which nulls `top_k` and `min_degree` (graph.py:596-601).
  - `filter_subgraph` treats `top_k <= 0` as `Config.GRAPH_UI_MAX_NODES` (default 400, `backend/app/config.py:1313`). It sorts by degree descending, then name, and keeps induced edges (`backend/app/services/graph_builder.py:805-846`).
  - `slim` keeps only `uuid/name/labels` for nodes and `uuid/name/fact_type/source/target uuids+names/valid_at/invalid_at` for edges (`backend/app/services/graph_builder.py:838-856`).
  - Raw nodes and edges come from a 60 s in-process TTL cache keyed `<graph_id>|raw` (`GRAPH_UI_CACHE_TTL_S`, `backend/app/services/graph_builder.py:2597-2610`; `backend/app/config.py:1315`).
  - Response `data`: `{graph_id, nodes, edges, node_count, edge_count, total_node_count, total_edge_count, truncated, positions?}` (`backend/app/services/graph_builder.py:2711-2723`).
- **`get_graph_neighbors`** (graph.py:621-639). Query `depth` (default 1, clamped to [1, 3]) and `slim` (default **true**). A BFS capped at `GRAPH_UI_MAX_NODES` nodes, keeping the center node (`backend/app/services/graph_builder.py:2725-2785`). An unknown `node_uuid` returns 200 with an empty `nodes` list, not 404.
- **`get_graph_node_detail` / `get_graph_edge_detail`** (graph.py:642-673). A linear scan of the cached raw graph; not found → 404 (`backend/app/services/graph_builder.py:2787-2801`).
- **`gc_stale_graphs`** (graph.py:676-697). Body `{retain?}`, int-coerced; a bad value raises `ValueError` → 500, not 400.
  - The service (`backend/app/services/graph_builder.py:2821-2868`) keeps graphs referenced by pipeline or project state plus the `retain` newest unreferenced graphs (default `GRAPH_RETAIN_COUNT=5`, `backend/app/config.py:1318`), and deletes the rest.
  - It skips the whole run if any active pipeline has no `graph_id` yet. It returns an audit `{total, retain, kept, deleted, failed, skipped_reason}`.
  - Destructive, with no dry-run.
- **`delete_graph`** (graph.py:700-725). Calls `client.graph.delete(graph_id)` and invalidates the UI cache (`backend/app/services/graph_builder.py:2870-2873`). It does **not** check whether a pipeline or project still references the graph.

### C. `backend/app/api/report.py` — `/api/report`

| # | Method | Path | Handler | Gate | Background work / external |
|---|---|---|---|---|---|
| 1 | POST | `/generate` | `generate_report` report.py:267 | — | `run_generate` thread (LLM ReACT) report.py:368-445 |
| 2 | POST | `/generate/status` | `get_generate_status` report.py:468 | — | polling (TaskManager) |
| 3 | GET | `/<report_id>` | `get_report` report.py:543 | payload withholding | — |
| 4 | GET | `/<report_id>/forecast` | `get_report_forecast` report.py:585 | publishable → else 409 | — |
| 5 | GET | `/by-simulation/<simulation_id>` | `get_report_by_simulation` report.py:630 | payload withholding | — |
| 6 | GET | `/list` | `list_reports` report.py:669 | payload withholding | — |
| 7 | GET | `/<report_id>/download` | `download_report` report.py:709 | publishable → else 409 | file serving |
| 8 | GET | `/<report_id>/full_report.<lang>.md` | `get_report_translation_md` report.py:757 | publishable(lang) → else 409 | file serving |
| 9 | POST | `/<report_id>/translations/<lang>` | `generate_report_translation` report.py:804 | `can_generate` → else 409 | `run_translation` thread (LLM) report.py:896-963 |
| 10 | GET | `/<report_id>/translations/<lang>/status` | `get_report_translation_status` report.py:977 | — | polling |
| 11 | GET | `/<report_id>/pdf` | `get_report_pdf` report.py:1037 | flag 503 / publishable 409 | pandoc/xelatex subprocess (sync) |
| 12 | GET | `/<report_id>/exec-brief` | `get_report_exec_brief` report.py:1106 | flag 404 / publishable 409 | deterministic build (no LLM) |
| 13 | GET | `/<report_id>/exec-brief.pdf` | `get_report_exec_brief_pdf` report.py:1166 | flags 404 / publishable 409 | pandoc subprocess (sync) |
| 14 | GET | `/<report_id>/digest` | `get_report_digest` report.py:1225 | flag 404 / publishable 409 | deterministic build |
| 15 | GET | `/<report_id>/charts/<path:filename>` | `get_report_chart` report.py:1279 | publishable 409 + path checks | file serving |
| 16 | GET | `/<report_id>/viz-manifest` | `get_report_viz_manifest` report.py:1358 | publishable 409 | — |
| 17 | DELETE | `/<report_id>` | `delete_report` report.py:1450 | — | rmtree |
| 18 | POST | `/chat` | `chat_with_report_agent` report.py:1478 | **none** | sync LLM ReACT |
| 19 | GET | `/<report_id>/progress` | `get_report_progress` report.py:1580 | **none** | polling |
| 20 | GET | `/<report_id>/sections` | `get_report_sections` report.py:1621 | draft gate | polling |
| 21 | GET | `/<report_id>/sections-partial` | `get_report_sections_partial` report.py:1681 | draft gate | polling |
| 22 | GET | `/<report_id>/section/<int:section_index>` | `get_single_section` report.py:1787 | draft gate → 409 | — |
| 23 | GET | `/check/<simulation_id>` | `check_report_status` report.py:1838 | — | — |
| 24 | GET | `/<report_id>/agent-log` | `get_agent_log` report.py:1895 | draft gate (field redaction) | polling |
| 25 | GET | `/<report_id>/agent-log/stream` | `stream_agent_log` report.py:1964 | draft gate | — |
| 26 | GET | `/<report_id>/console-log` | `get_console_log` report.py:2001 | draft gate (line redaction) | polling |
| 27 | GET | `/<report_id>/console-log/stream` | `stream_console_log` report.py:2051 | draft gate | — |
| 28 | POST | `/tools/search` | `search_graph_tool` report.py:2091 | — (debug) | `ZepToolsService.search_graph` |
| 29 | POST | `/tools/statistics` | `get_graph_statistics_tool` report.py:2139 | — (debug) | `ZepToolsService.get_graph_statistics` |

Report files live in `uploads/reports/<report_id>/` (`ReportManager.REPORTS_DIR`, `backend/app/services/report_agent.py:11864,11890-11892`). `_get_report_folder` does **no id validation**.

**Gate helpers (report.py:26-262).**
- `_withhold_outline_drafts(outline)` (report.py:26-42) keeps the outline skeleton. Every dict section gets `content:""` and `draft_withheld:True`.
- `_report_publication_payload(report)` (report.py:45-71) builds the shared metadata payload for `/<id>`, `/by-simulation` and `/list`:
  - `report.to_dict()` (fields at `backend/app/services/report_agent.py:564-587`) plus `publishable` and `publication_issues` from `publication_status`.
  - `draft_withheld = not publishable`. When withheld, `markdown_content` is set to `""` and the outline section prose is stripped (report.py:55-58).
  - `translation_status` from `ReportManager.translation_status(report_id, report=report)`.
  - `translations` is replaced with `[verified]` only if the verified entry has `available`, `audit_verified`, `source_markdown_sha256`, `markdown_sha256` and `final_audit_sha256`; otherwise `[]` (report.py:62-70). The `translations` list stored in meta.json is discarded.
- `_publication_rejection(report_id, lang=None, publication=None)` (report.py:74-83) is the shared 409 `{success:false, error:"报告尚未通过最终发布审计", publishable:false, publication_issues}`.
- `_AGENT_LOG_DRAFT_FIELDS` (report.py:90-95) defines the fields redacted from agent-log details: `section_content`/`section_complete` → `content`, `llm_response` → `response`, `react_thought` → `thought`. `_REPORT_IN_PROGRESS = (PENDING, PLANNING, GENERATING)` (report.py:96).
- `REPORT_IN_PROGRESS_STALE_SECONDS = 30*60` (report.py:105). `_REPORT_ACTIVITY_FILES = {meta.json, progress.json, outline.json, agent_log.jsonl, console_log.txt}` plus `section_*.md` (report.py:109-111,127-128).
- `_report_last_activity(report_id)` (report.py:120-138) returns the newest mtime of those files, or `None`. `_report_generation_live` (report.py:141-150) is True iff `abs(now - last) <= 1800`, so a far-future mtime also counts as not live.
- **`_draft_exposure_gate(report_id)`** (report.py:153-190) returns `(withhold, report, publication)`:
  - `get_report` and `publication_status` exceptions are treated as a missing report or as unpublishable with the reason "report metadata (meta.json) could not be loaded" (report.py:163-172).
  - A `None` report with a publishable status is forced to unpublishable (report.py:173-180).
  - For an in-progress status, `live = _report_generation_live`. If not live, it appends the reason "report generation stalled: no generator activity for over 30 minutes" (report.py:181-188).
  - **`withhold = not live and not publishable`** (report.py:189).
- `_withhold_console_log_drafts(lines)` (report.py:204-218). For lines containing one of four audit/revision markers (`引用接地审计`, `概率一致性审计`, `统计合理性审计`, `反思修订已采纳`), it cuts the line at the marker's separator and appends " [draft excerpt withheld …]" (report.py:195-201). Other lines pass through unchanged.
- `_withhold_agent_log_drafts(logs)` (report.py:221-232) drops the draft fields and sets `details.draft_withheld=True`. `_gate_agent_log` (report.py:235-244) returns `(logs, {publishable, publication_issues, draft_withheld})`.
- `_active_translation_task(report_id, lang)` (report.py:247-257) returns the newest in-memory `report_translate` task with matching metadata and status `pending` or `processing`.
- `_launch_translation_thread(target)` (report.py:260-262) is a seam that tests monkeypatch to run the worker synchronously.

**1. `generate_report`** (report.py:267-465). Body `{simulation_id (required), force_regenerate?}`.
- An unknown simulation (`SimulationManager().get_simulation`) → 404 (report.py:305-312).
- Without `force_regenerate`, an existing completed **and publishable** report short-circuits with `{report_id, status:"completed", already_generated:true}` (report.py:315-328).
- Then: project missing → 404; `graph_id` from `state.graph_id or project.graph_id` missing → 400; `project.simulation_requirement` missing → 400 (report.py:331-350).
- It mints `report_<12 hex>` (report.py:353-354) and creates task `report_generate` with metadata `{simulation_id, graph_id, report_id}` (report.py:357-365).
- Thread `run_generate` (report.py:368-441):
  - `load_research_dossier_for_simulation(simulation_id)` scans every pipeline state for a matching `simulation_id` and returns the `situation_brief/actors/sources/research_report` (`backend/app/services/pipeline_orchestrator.py:6744-6776`).
  - `ReportAgent(graph_id, simulation_id, simulation_requirement, situation_brief, actors, sources, research_report)` (report.py:379-387). It does not pass the `quantitative/contested/timeline_events/graph_priors/scenario_spine/charts_manifest` args that the orchestrator path passes (`backend/app/services/pipeline_orchestrator.py:13285-13311`). [verifier: the pipeline REPORT stage passes `quantitative`, `contested`, `timeline_events`, `graph_priors`, `graph_priors_structural`, `scenario_label` and `base_simulation_id`, but neither `scenario_spine` nor `charts_manifest` (`backend/app/services/pipeline_orchestrator.py:13285-13311`); `scenario_spine` is passed only to forecast-seed agents (`:8877-8881`)]
  - `agent.generate_report(progress_callback, report_id)` makes the LLM and graph calls. Progress messages are `"[stage] message"`.
  - `ReportManager.save_report(report)` (report.py:404).
  - If `force_regenerate` and publishable, it deletes the other reports for the simulation (report.py:412-420).
  - It completes the task with `{report_id, simulation_id, status:"completed"}` only if publishable; otherwise it fails it with `report.error`, the publication reasons, or a default message (report.py:422-437).
- The response is immediate: `{simulation_id, report_id, task_id, status:"generating", already_generated:false}` (report.py:447-457).
- There is **no in-flight dedupe**: two POSTs start two generations. `force_regenerate` is not bool-coerced, so the string `"false"` is truthy.

**2. `get_generate_status`** (report.py:468-538). This is **POST** (the generate docstring at report.py:273 says GET). Body `{task_id?, simulation_id?}`.
- A publishable completed report for `simulation_id` → `{status:"completed", progress:100, already_completed:true}` (report.py:497-511).
- Otherwise `task_id` is required (400); an unknown task → 404. Returns `task.to_dict()` (report.py:513-531).

**3. `get_report`** (report.py:543-582). 404 if `get_report` returns `None`; otherwise `_report_publication_payload`.

**4. `get_report_forecast`** (report.py:585-627).
- 404 if the report is missing. Not publishable → 409. A `lang` outside `en`/`zh` → 400.
- With no `lang`: `load_structured_forecast`, which returns `forecast.json` only if the hard-passed final audit (policy version `REPORT_FINAL_AUDIT_POLICY_VERSION=3`, `backend/app/config.py:195`) records it present and valid with a matching SHA-256 (`backend/app/services/report_agent.py:11912-11965`).
- With `lang`: `load_localized_forecast`, which uses `forecast.<lang>.json` only if its `localization.source_forecast_sha256` equals the sealed SHA (`backend/app/services/report_agent.py:11973-12002`).
- Returns `{report_id, simulation_id, forecast, available, localization}`.
- There is no try/except.

**5. `get_report_by_simulation`** (report.py:630-666). `ReportManager.get_report_by_simulation` uses the sim index fast path, then a full scan, and returns the newest by `created_at`, **publishable or not** (`backend/app/services/report_agent.py:14353-14399`). 404 includes `has_report:false`.

**6. `list_reports`** (report.py:669-706). `?simulation_id&limit=50`. Each report goes through `_report_publication_payload`, which means several `publication_status` calls per report, each re-hashing the Markdown.

**7. `download_report`** (report.py:709-752).
- 404 if missing, 409 if not publishable. Sends `full_report.md` as `<id>.md`.
- The in-memory fallback for a missing file (report.py:730-738) is effectively unreachable: publication already requires `full_report.md` to exist (`backend/app/services/report_agent.py:12471-12477`).

**8. `get_report_translation_md`** (report.py:757-801). `GET /<id>/full_report.<lang>.md`.
- An invalid `lang` → **404** (not 400). Report missing → 404. Variant file missing → 404. Not `is_publishable(report_id, lang)` → 409.
- Sends the file as an attachment with mimetype `text/markdown`.
- Variant publication additionally requires: the primary is publishable; the language audit and the citation map match the primary SHA and language; and meta.json `translations` contains an identity row (`backend/app/services/report_agent.py:12533-12592`).

**9. `generate_report_translation`** (report.py:804-974). Retries or regenerates one bilingual variant.
- `lang` must be `en` or `zh` (400). The report must exist (404). `?force=1|true|yes` regenerates a published variant (report.py:827).
- The dedupe order:
  1. An active in-memory task → 202 with the task's status (report.py:848-851).
  2. `translation_status == "generating"` → 202 (report.py:852-854).
  3. Under `ReportManager._translation_generation_lease(report_id, lang)`, a per-key `threading.Lock` plus an advisory file lock on `translation_status.<lang>.json.lock` (`backend/app/services/report_agent.py:12096-12103`), it re-reads the state:
     - available and not force → 200;
     - an active task → 202;
     - generating → 202;
     - not `can_generate` → 409 (report.py:856-874). `can_generate` requires the primary to be publishable and `REPORT_BILINGUAL` to be on (`backend/app/services/report_agent.py:12213-12216`).
- Still inside the lease, it creates task `report_translate` with `{report_id, lang}` and persists the runtime status `pending` with `source_markdown_sha256`, `task_id`, `owner=pid:<pid>` and progress 0 (report.py:876-894).
- Worker `run_translation` (report.py:896-961) calls `ReportManager.generate_translation_variant(report_id, lang, progress_callback, force=regenerate)`. That method re-acquires the same lease for the whole LLM run, and refuses if the primary changed during the run (`backend/app/services/report_agent.py:12353-12432`).
  - `available` and `updated` → runtime `available` and task complete.
  - Otherwise → runtime `failed` with up to 12 issues and task failed.
  - An exception → runtime `failed` and task failed.
- The response is 202 `{...state, available:false, status:"pending", task_id, progress:0}` (report.py:964-974).

**10. `get_report_translation_status`** (report.py:977-1032). `?task_id=`.
- If a task id is given and found, its metadata must match the report and lang (409 otherwise). The response merges the durable state with the task fields. `available` is true only if the task completed with `result.available` and `result.updated` (report.py:990-1020).
- Otherwise it returns the durable `translation_status`, overlaid with any active task (report.py:1021-1032).
- The durable status machine (`backend/app/services/report_agent.py:12162-12334`) has these states: `not_found`, `unsupported`, `source_language`, `available` (with `outdated`/`can_update` against `_TRANSLATOR_VERSION`), `generating`, `interrupted`, `failed`, `stale`, `invalid`, `blocked`, `disabled`, `missing`.
  - `generating` is trusted while the owner `pid:N` is alive and the status is at most 1 h old. A non-pid owner is trusted for at most 15 min (`backend/app/services/report_agent.py:12271-12279`). Otherwise the state is `interrupted`.

**11. `get_report_pdf`** (report.py:1037-1101).
- Report missing → 404. An explicit non-empty invalid `lang` → 400. An empty `?lang=` means primary (report.py:1060-1067).
- `REPORT_PDF_EXPORT` off → 503 `pdf_export_disabled` (report.py:1069-1074). Not `is_publishable(report_id, lang)` → 409.
- It calls `ReportManager.export_pdf(report_id, lang)`, which has a content-addressed cache, per-(report, lang) process locks plus an advisory lock, pandoc+xelatex with a PyMuPDF fallback for simple Markdown, and an integrity audit (`backend/app/services/report_agent.py:13461-13480`; locks at `:11876-11880,12151-12159`).
- `None` → 503 `pdf_build_failed`. Success → attachment `<id>[.<lang>].pdf`. Any exception → 500 `pdf_internal_error` with no detail (report.py:1095-1101).

**12-14. Exec brief, exec-brief PDF, digest** (report.py:1106-1274).
- Flags: `REPORT_EXEC_BRIEF` (and `REPORT_PDF_EXPORT` for the PDF) off → **404** (report.py:1120-1124, 1177-1182, 1235-1239). Report missing → 404.
- `lang` is silently normalised. An invalid value falls back to primary, unlike `/pdf` (report.py:1133-1134, 1191-1192).
- Publication is checked for that lang (409). Digest checks primary only (report.py:1248).
- `ExecBriefBuilder.build(report_id, report_dir)` derives `exec_brief[.<lang>].md` and `digest.md` deterministically, **with no LLM**, and caches by mtime (`backend/app/services/exec_brief.py:3,553-612`). `build_pdf` exports `exec_brief[.<lang>].pdf` with an mtime cache (`backend/app/services/exec_brief.py:824-860`).
- A missing output → 404. Files are sent as attachments `<id>.exec_brief[.<lang>].md|pdf` and `<id>.digest.md`.

**15. `get_report_chart`** (report.py:1279-1355). File serving with **per-request path safety**:
1. The report must exist (404) and be publishable (409) (report.py:1288-1294).
2. `reports_root = realpath(REPORTS_DIR)`, `report_dir = realpath(folder)`, `charts_dir = realpath(report_dir/charts)` (report.py:1295-1297).
3. The raw `filename` is rejected with 404 if any of these hold (report.py:1298-1311):
   - it is empty;
   - it starts with `/`;
   - it contains `\` or `%`;
   - it contains control characters (`<32` or `127`);
   - any segment is empty, `.` or `..`;
   - its extension is not in `{.png,.svg,.jpg,.jpeg,.gif,.webp,.html}`;
   - `report_dir` is outside `reports_root`;
   - `charts_dir` is outside `report_dir`;
   - `charts_dir` is missing or is a link. That last check is a no-op on a realpath; see Surprises.
4. `candidate = join(charts_dir, *parts)`. Its realpath must be inside `charts_dir`, must be a regular file, and **no path component under `charts_dir` may be a symlink** (report.py:1312-1318).
5. `.html` gets the plotly bundle inlined and the sandbox CSP (`allow-scripts`, `connect-src 'none'`) plus `nosniff` and `no-referrer`. `.svg` gets `CSP: sandbox; script-src 'none'` (report.py:1319-1347).
6. Any exception → 404, so path details are not leaked (report.py:1349-1355).

**16. `get_report_viz_manifest`** (report.py:1358-1447).
- Report missing → 404. Not publishable → 409. No `viz_manifest.json` → `{schema_version:1, data:[], count:0, skipped:[]}` (report.py:1412-1419).
- A dict manifest gives `schema_version` (int, default 2), `items` and `skipped` (a list). A list manifest is schema 1 (report.py:1422-1434).
- `safe_chart_path` (report.py:1364-1377) keeps only relative POSIX paths with no `..`, `\`, `%` or control characters whose first part is `charts`, after stripping `./`. Rows with a bad `path` are dropped. A bad `png_path` is removed (report.py:1379-1398).

**17. `delete_report`** (report.py:1450-1473). `ReportManager.delete_report` calls `shutil.rmtree(uploads/reports/<id>)`, or removes the legacy `<id>.json` and `<id>.md`, and updates the sim index (`backend/app/services/report_agent.py:14450-14478`). There is no in-progress check and no id validation (see Surprises).

**18. `chat_with_report_agent`** (report.py:1478-1575). Body `{simulation_id, message, chat_history?}`. It validates the simulation, project and graph id (400/404), builds a `ReportAgent` with the dossier, and runs a synchronous `agent.chat(message, chat_history)` (report.py:1551-1562). That is a ReACT LLM loop with graph tools (`backend/app/services/report_agent.py:11727`). Returns `{response, tool_calls, sources}` per the docstring. The route has **no publication gate**; unlocking is decided client-side from `/check`. [verifier: no current frontend code calls `/chat` or `/check`; `chatWithReport` is defined at `frontend/src/api/report.js:53-54` but never imported (the only importer of `api/report` is `frontend/src/components/research/ForecastReport.vue:245-249`), so `interview_unlocked` is advisory and unused]

**19. `get_report_progress`** (report.py:1580-1618). Returns the raw `progress.json` (`backend/app/services/report_agent.py:14060-14068`), or 404 if missing. Ungated: it contains titles and status, not prose.

**20. `get_report_sections`** (report.py:1621-1678).
- Draft gate: if withheld, `sections=[]`; otherwise `get_generated_sections`, which returns every `section_*.md` sorted with `{filename, section_index, content}` (`backend/app/services/report_agent.py:14071-14100`).
- `is_complete = status==COMPLETED and publishable`.
- Returns `{report_id, sections, total_sections, is_complete, publishable, publication_issues, draft_withheld}`.

**21. `get_report_sections_partial`** (report.py:1681-1784). Progressive publication.
- The gate runs first. If withheld, it returns `{sections:[], done, publishable, publication_issues, draft_withheld:true}` without reading any section files (report.py:1710-1720).
- Otherwise each section file becomes `{index, title, status:"completed", content_md}`. `title` is the first `#{1,6}` heading, else `Section N` (report.py:1722-1744).
- If `progress.json.current_section` is set, not yet completed, and the status is not completed or failed, it appends a `{status:"generating", content_md:""}` placeholder at `max(index)+1` (report.py:1746-1763).
- `done = publishable` (report.py:1711). The docstring at report.py:1701 still says done means `full_report.md` exists.
- An exception → 500 with a stable `{sections:[], done:false}` shape (report.py:1776-1784).

**22. `get_single_section`** (report.py:1787-1833). If the gate withholds → 409 (`_publication_rejection` with the gate's publication). Otherwise it reads `section_<NN>.md` (404 if missing). The `<int:>` converter rejects negative or non-integer indices at routing.

**23. `check_report_status`** (report.py:1838-1890). Returns `{has_report, report_status, report_id, interview_unlocked = publishable, publishable, publication_issues}` for the newest report of a simulation.

**24-27. Agent and console logs** (report.py:1895-2086). All four read the whole file on every call.
- `/agent-log?from_line=` (report.py:1895-1961): `ReportManager.get_agent_log` parses the JSONL from `from_line`, skipping bad lines, and always returns `has_more:false` (`backend/app/services/report_agent.py:13826-13872`). The gate redacts fields and adds `publishable/publication_issues/draft_withheld`.
- `/agent-log/stream` (report.py:1964-1996): the same, for all lines, plus `count`.
- `/console-log?from_line=` (report.py:2001-2048): plain-text lines (`backend/app/services/report_agent.py:13765-13810`). When withheld, it redacts the marker lines and adds `draft_withheld:true`. When not withheld, the key is absent, and `publishable` is never included.
- `/console-log/stream` (report.py:2051-2086): always includes `draft_withheld`.
- A nonexistent report returns 200 with empty logs and `draft_withheld:true` from the gate.

**28-29. Debug tools** (report.py:2091-2176).
- `POST /tools/search {graph_id, query, limit=10}` → `ZepToolsService().search_graph(...)` → `result.to_dict()` (report.py:2116-2127; signature at `backend/app/services/zep_tools.py:613-620`).
- `POST /tools/statistics {graph_id}` → `get_graph_statistics(graph_id)` (`backend/app/services/zep_tools.py:1407`).
- They are reachable from loopback with no extra guard.

## Control flow

**Main pipeline polling loop (frontend):**

1. `POST /api/research/run` (`frontend/src/api/research.js:28-34`) → research.py:50 → `PipelineOrchestrator.start` starts `_run` on a daemon thread (`backend/app/services/pipeline_orchestrator.py:7970-7978`). The API returns at once with `pipeline_id` and `task_id`.
2. The UI polls `GET /api/research/status/<id>` (`frontend/src/api/research.js:142-147`) → research.py:306, which reads `pipeline_state.json` from disk plus the computed `live` block.
3. In parallel it polls `GET /api/research/<id>/progress?scope=tail&lines=200` (`frontend/src/api/research.js:228-235`) → research.py:871.
4. Once research completes: `GET /<id>/dossier` (research.py:389), chart deep links `GET /<id>/artifact/chart_<file>` built by `researchChartUrl` (`frontend/src/api/research.js:12-17`), the optional translations POST and poll pair (research.py:555/593), and `GET /<id>/dossier/pdf` (research.py:636).
5. Graph panel: `GET /api/graph/data/<graph_id>?top_k=0&slim=true` (`frontend/src/api/graph.js:59-66`; the defaults `top_k=0` and `slim=true` come from `frontend/src/utils/graphPayload.js:4-10`), then node, edge and neighbors detail on click (`frontend/src/api/graph.js:68-101`).
6. The report stage writes `reports/<rid>/` while the orchestrator runs. The UI polls `GET /api/report/<rid>/sections-partial` (`frontend/src/api/report.js:74-76`), `agent-log` and `console-log` with `from_line` (`frontend/src/api/report.js:28-38`), and `GET /api/report/<rid>` (`frontend/src/api/report.js:45-47`). [verifier: wrong for agent-log/console-log. `getAgentLog`/`getConsoleLog` are defined but never imported; `ForecastReport.vue` imports only `getReport, getVizManifest, getSectionsPartial`, the translation helpers, the URL builders and `getForecast` (`frontend/src/components/research/ForecastReport.vue:245-249`), and a grep of `frontend/src` finds no other `agent-log`/`console-log` use]
7. Once the report is publishable: `GET /forecast` (`frontend/src/api/report.js:142-144`), `/viz-manifest` (`:66`), `/charts/<file>` built by `reportAssetUrl` (`:153-156`), `/full_report.<lang>.md` (`:86`), `/download` (`:113`), `/pdf` (`:125`), and a translation retry with POST and status polling (`:96,104`).

**Lifecycle actions:**
- cancel → `PipelineOrchestrator.cancel` sets the Event.
- resume, continue and fork → orchestrator classmethods that each create a new task and a new `_run` thread under `_lifecycle_lock` (`backend/app/services/pipeline_orchestrator.py:8120,8222,8344`). [verifier: only resume and continue do all their work under the lock; fork loads the base, creates its task and saves state outside the lock and takes it only to register and start the thread (`backend/app/services/pipeline_orchestrator.py:8288-8348`)]
- delete and clean → `delete_pipeline` → rmtree → `_gc_stale_graphs`.

**Manual MiroFish flow (legacy; `frontend/src/api/graph.js:14-49`, `frontend/src/api/report.js:11-21`):**

`POST /api/graph/ontology/generate` (sync LLM) → `POST /api/graph/build` (thread) → poll `GET /api/graph/task/<task_id>` → simulation routes (outside this slice) → `POST /api/report/generate` (thread) → poll `POST /api/report/generate/status` → reads.

**Ordering inside gates:**
- Report read routes usually check, in order: existence (404), a feature flag (503 or 404, depending on route), publication (409), then the build or serve step. `/pdf` checks the flag before publication (report.py:1069-1077). `/charts` and `/viz-manifest` have no flag. [verifier: `/exec-brief`, `/exec-brief.pdf` and `/digest` check the flag *before* existence (report.py:1120-1131, 1177-1189, 1235-1246); only `/pdf` does existence → lang → flag → publication (report.py:1051-1077)]
- Draft routes call `_draft_exposure_gate` **before** touching section files (report.py:1709-1720).

## Data & artifacts

**Pipeline side (`uploads/pipelines/<pipeline_id>/`, `backend/app/config.py:1581`):**
- `pipeline_state.json` is read by status, list, cancel, resume, edit and artifact. Key fields: `status`, `mode`, `stages{name:{status,progress,...}}`, `options{research_language, research_model, depth, max_rounds, base_pipeline_id, scenario_overlay, pipeline_health, ...}`, `artifacts{name: absolute path}`, `handoff_dir`, `task_id`, `report_id`, `simulation_id`, `graph_id`, and owner/heartbeat fields (`backend/app/services/pipeline_orchestrator.py:683-757`).
- `handoff/` holds the files read by the dossier route (`research_report.md`, `actors.json`, `sources.json`, `timeline.json`, `quantitative.json`, `contested.json`, `prediction_markets.json`, `charts.json`) plus:
  - files **written by this slice**: `research_report.md` and `actors.json` on edit, and the translation sidecars `research_report.<lang>.md`, `research_report.final_audit.<lang>.json`, `research_report.translation.<lang>.json` (status: `{status, available, source_sha256, owner?, target_lang?, source_lang?, issues[]}`), `research_report[.<lang>].pdf` (research.py:449-457, 667);
  - `handoff/manifest.json`, refreshed on edit;
  - progress logs `research_progress.log`, `track_N/research_progress.log` and `research_attempts/*.log`;
  - `charts/` (research chart assets).
- Forks share the base's `handoff/` (`backend/app/services/pipeline_orchestrator.py:8306`).

**Graph side:**
- `uploads/projects/<project_id>/` contains `project.json`, `files/<8hex>.<ext>` and `extracted_text.txt` (`backend/app/models/project.py:113-130,245-283`).
- The graph store is local Graphiti on embedded FalkorDB by default, under `GRAPHITI_DATA_DIR` (`backend/app/config.py:1018,1021-1024`).
- `GRAPHITI_DATA_DIR/layouts/<graph_id>/positions.json` is written by `compute_layout` (`backend/app/services/graph_builder.py:859-861`).

**Report side (`uploads/reports/<report_id>/`):**
- Generator outputs: `meta.json`, `outline.json`, `progress.json`, `section_NN.md`, `full_report.md`, `agent_log.jsonl`, `console_log.txt`, `final_audit[.<lang>].json`, `citations[.<lang>].json`, `forecast.json`, `forecast.<lang>.json`, `full_report.<lang>.md`, `translation_status.<lang>.json` (+ `.lock`), `full_report[.<lang>].pdf` plus a PDF manifest, `exec_brief[.<lang>].md|pdf`, `digest.md`, `viz_manifest.json` and `charts/`.
- `_sim_index.json` sits at the reports root (`backend/app/services/report_agent.py:11868`).
- This slice writes, directly or through the services it triggers: the translation runtime status (report.py:884-894), exec-brief, digest and PDF outputs (lazy builds), and the full report folder via `save_report` (report.py:404).

**In-memory structures:**
- The `TaskManager` singleton dict (`backend/app/models/task.py:54-71`) is lost on restart. It holds the graph build, report generation and translation tasks.
- `_research_translation_inflight` set (research.py:446).
- `PipelineOrchestrator._threads/_cancel_events` (`backend/app/services/pipeline_orchestrator.py:7530-7531`).
- The graph UI TTL cache (`backend/app/services/graph_builder.py:755-789`).
- `resolution_autorun._inflight` (`backend/app/services/resolution_autorun.py:29-30`).

## Config / env knobs

| Name | Default | Effect in this slice | Anchor |
|---|---|---|---|
| `FLASK_DEBUG` | False | When false, the `traceback` key is stripped from JSON errors | `backend/app/config.py:35`; `backend/app/__init__.py:189` |
| `APP_API_TOKEN` | "" | Non-loopback callers need `X-API-Token`; with no token they get 403 | `backend/app/config.py:43`; `backend/app/__init__.py:163-171` |
| `APP_CORS_ORIGINS` | localhost/127.0.0.1 on :3000 and :5001 | CORS allowlist for `/api/*` | `backend/app/config.py:45-48` |
| `DEERFLOW_RESEARCH_DEPTH` | `deep` | Default `depth` for `/run` | `backend/app/config.py:1159`; research.py:71 |
| `SUPPORTED_DEERFLOW_MODELS` (constant) | 8 models | `/run` model allowlist | `backend/app/config.py:1544`; research.py:92 |
| `LLM_RUN_BUDGET_TOKENS` | 0 | When > 0, `/status` adds `live.budget` | `backend/app/config.py:64`; research.py:319 |
| `LLM_TELEMETRY_ENABLED` | true | Enables `live.spend_so_far` | `backend/app/config.py:58`; `backend/app/services/pipeline_orchestrator.py:10314` |
| `PIPELINE_STRICT_SCHEMA` | true | Newer-schema state loads as a sentinel; resume, continue and fork → 409 | `backend/app/config.py:352`; `backend/app/services/pipeline_orchestrator.py:1156` |
| `PIPELINE_HEARTBEAT_STALE_S` | 120 | Orphan-death test in resume | `backend/app/config.py:459`; `backend/app/services/pipeline_orchestrator.py:8135` |
| `PIPELINE_STALE_S` | 300 | `live.stale` | `backend/app/config.py:461` |
| `PIPELINE_LIVE_ARTIFACTS` / `PIPELINE_PARTIAL_SCAN_EVERY_S` | true / 10 s | Whether `*_partial` artifact keys exist for `/artifact` | `backend/app/config.py:464-465` |
| `PIPELINE_VIZ_ARTIFACTS` | true | Whether `chart_*` / `report_chart_*` keys are registered | `backend/app/config.py:470` |
| `RESOLUTION_MONITOR_AUTORUN_HOURS` | 0 | Periodic monitor; the manual route ignores it | `backend/app/config.py:290` |
| `ZEP_API_KEY` | sentinel `local-graphiti` | Makes the "ZEP_API_KEY未配置" guards dead | `backend/app/config.py:1038`; graph.py:287,590,706 |
| `MAX_CONTENT_LENGTH` (constant) | 50 MiB | Upload cap | `backend/app/config.py:1047` |
| `ALLOWED_EXTENSIONS` (constant) | pdf, md, txt, markdown | Ontology upload filter | `backend/app/config.py:1049` |
| `DEFAULT_CHUNK_SIZE` / `DEFAULT_CHUNK_OVERLAP` | 2500 / 250 | Intended fallback for `/build`, but shadowed by the Project defaults 500/50 | `backend/app/config.py:1055-1057`; graph.py:340-341 |
| `GRAPH_LAYOUT_PRECOMPUTE` | true | `/build` persists `positions.json` | `backend/app/config.py:1321`; graph.py:460 |
| `GRAPH_UI_MAX_NODES` | 400 | `top_k<=0` cap; neighbors BFS cap | `backend/app/config.py:1313` |
| `GRAPH_UI_CACHE_TTL_S` | 60 | Raw graph cache for the `/data*` routes | `backend/app/config.py:1315` |
| `GRAPH_RETAIN_COUNT` | 5 | `/gc` default retain | `backend/app/config.py:1318` |
| `GRAPH_CAST_CHUNK_FILTER` | true | Applies in `add_text_batches`; a no-op for manual builds because no cast is registered | `backend/app/config.py:1335`; `backend/app/services/graph_builder.py:2309-2311` |
| `REPORT_PDF_EXPORT` | true | Off: `/pdf` → 503, exec-brief.pdf → 404, research `/dossier/pdf` → 500 | `backend/app/config.py:244`; report.py:1069; research.py:681 |
| `REPORT_EXEC_BRIEF` | true | Off: exec-brief, exec-brief.pdf and digest → 404 | `backend/app/config.py:273` |
| `REPORT_BILINGUAL` | true | Off: translation `can_generate=false` → 409 | `backend/app/config.py:704`; `backend/app/services/report_agent.py:12214-12216` |
| `REPORT_FINAL_AUDIT_POLICY_VERSION` (constant) | 3 | The publication barrier requires this policy version | `backend/app/config.py:195` |
| `REPORT_TRANSLATION_CALL_TIMEOUT_S` | 240 | Per-call timeout for research and report translation | `backend/app/config.py:713`; `backend/app/services/report_agent.py:7741-7743` |
| `REPORT_IN_PROGRESS_STALE_SECONDS` (module constant, not env) | 1800 | Draft-gate liveness window | report.py:105 |
| `MIN_DOSSIER_CHARS` (module constant) | 400 | Minimum size for a dossier edit | research.py:47 |
| `API_V1_ENABLED` | false | Mounts `/api/v1` (sdk.py), which reuses the same services | `backend/app/config.py:388`; `backend/app/__init__.py:210-212` |

## External calls

- **LLM (synchronous, inside the request thread):**
  - `OntologyGenerator.generate` (graph.py:216-221).
  - `ReportAgent.chat` (report.py:1562).
  - `/run` makes none; preflight is local (`backend/app/services/pipeline_orchestrator.py:6780-6783`). `GET /preflight?format=full&deep=true` runs `environment_report(deep=True)` live probes (`backend/scripts/preflight.py:93-94`).
- **LLM (background daemon threads):**
  - `ReportAgent.generate_report` (report.py:398-401).
  - `ReportManager.generate_translation_variant` (report.py:904-914).
  - `translate_research_markdown` (research.py:514).
  - `GraphBuilderService.add_text_batches`, Graphiti entity extraction (graph.py:435-440).
  - The whole pipeline `_run`: research subprocesses, simulation and report (research.py:109, 164, 199, 240).
- **Subprocess:**
  - `resolution_monitor.py run --all-recent`, 15-minute timeout (`backend/app/services/resolution_autorun.py:42-46`). It only hits public Gamma endpoints, per its docstring (`backend/app/services/resolution_autorun.py:12`).
  - pandoc/xelatex for the report PDF, research PDF and exec-brief PDF. Paths: `ReportManager._PANDOC_BIN=/opt/homebrew/bin/pandoc`, `_XELATEX_BIN=/Library/TeX/texbin/xelatex`, with a PATH fallback (`backend/app/services/report_agent.py:12604-12605`).
  - Mermaid `mmdc` pre-render when it is on PATH (`backend/app/services/report_agent.py:13465`).
  - Orphan research PID kills on delete (`backend/app/services/pipeline_orchestrator.py:8075-8078`).
- **Graph DB:** `Zep` shim → local Graphiti/FalkorDB for `create_graph`, `set_ontology`, `add_text_batches`, `fetch_all_nodes/edges`, `delete`, `list_graph_ids`, `graph_last_created_at` (`backend/app/services/graph_builder.py:19,1072,2597-2615,2821-2873`). Also `ZepToolsService.search_graph/get_graph_statistics` (report.py:2116-2123, 2160-2163).
- **OS signals:** `os.kill(pid, 0)` liveness probes for translation owners (`backend/app/services/report_agent.py:12144`) and pipeline owners via `_pid_alive` (`backend/app/services/pipeline_orchestrator.py:10311`).

## Cross-module edges

**Inbound (who calls this slice):**
- `backend/app/api/__init__.py:7-17` creates the blueprints and imports the three modules for their route side effects. `backend/app/__init__.py:200-205` registers them under `/api/graph`, `/api/report` and `/api/research`.
- Frontend clients:
  - `frontend/src/api/research.js` has a client function for all 18 research routes (lines 12-235).
  - `frontend/src/api/graph.js` calls `/ontology/generate`, `/build`, `/task/<id>`, `/data/<id>`, `/data/<id>/node|edge|neighbors/...` and `/project/<id>` (lines 14-109).
  - `frontend/src/api/report.js` calls `/generate`, `/generate/status`, `/agent-log`, `/console-log`, `/<id>`, `/chat`, `/viz-manifest`, `/sections-partial`, `/full_report.<lang>.md`, `/translations/<lang>` (+`/status`), `/download`, `/pdf`, `/forecast` and `/charts/*` (lines 11-156).
  - A grep of `frontend/src` finds **no frontend caller** for: `/api/graph/project/list`, DELETE `/project/<id>`, `/project/<id>/reset`, `/tasks`, `/gc`, `/delete/<id>`; or `/api/report/by-simulation`, `/list`, `/exec-brief*`, `/digest`, DELETE `/<id>`, `/progress`, `/sections`, `/section/<n>`, `/check/<sim>`, `/agent-log/stream`, `/console-log/stream`, `/tools/*`.
  - The exec-brief Markdown itself links to `/exec-brief`, `/exec-brief.pdf`, `/digest`, `/download` and `/pdf` (`backend/app/services/exec_brief.py:811-818`).
- `backend/scripts/export_demo_site_data.py:645-654` can read `/api/graph/data/` from a running backend.
- Tests:
  - `backend/tests/test_report_bilingual.py` imports `app.api.report._report_publication_payload` (`backend/tests/test_report_bilingual.py:806`).
  - `backend/tests/test_report_draft_exposure.py` patches `REPORT_IN_PROGRESS_STALE_SECONDS`.
  - Route tests include `test_report_publication_barrier.py`, `test_chart_serve_inline.py`, `test_report_sections_partial.py`, `test_agent_log_publication_gate.py`, `test_dossier_edit_continue.py`, `test_live_research_progress.py`, `test_status_live_block.py`, `test_research_fork_handoff.py`, `test_resolution_autorun.py` and `test_report_viz_manifest_api.py` (all in `backend/tests/`).
- `backend/app/api/sdk.py` (`/api/v1`) does **not** import this slice. It calls the same services directly and mirrors `/run`, `/list` and `/dossier` (`backend/app/api/sdk.py:44-49,80,177,190`).

**Outbound (what this slice calls):**
- `backend/app/services/pipeline_orchestrator.py`: `PipelineManager` (`load`, `list_pipelines`, `resolve_handoff_dir`), `PipelineOrchestrator` (`start`, `cancel`, `resume`, `continue_to_full`, `fork`, `delete_pipeline`, `clean_terminal`, `heartbeat_status`), `PipelineState.from_dict`, `preflight_pipeline`, `refresh_research_artifact_manifest`, `research_dossier_is_sealed`, `load_research_dossier_for_simulation`.
- `backend/app/services/research_progress.py`: `merged_research_progress_tail/_full`, `ResearchProgressLimitError`.
- `backend/app/services/resolution_autorun.py`: `trigger_once`.
- `backend/scripts/preflight.py`: `environment_report`.
- `backend/app/services/report_agent.py`: `ReportAgent` (constructor, `generate_report`, `chat`, `translate_research_markdown`), `ReportManager` (about 25 methods, including private ones such as `_get_report_folder`, `_translation_generation_lease`, `_set_translation_runtime_status`, `_translation_owner_alive` and `_TRANSLATION_LANGS`), `ReportStatus`.
- `backend/app/services/exec_brief.py`: `ExecBriefBuilder`.
- `backend/app/services/graph_builder.py`: `GraphBuilderService`.
- `backend/app/services/ontology_generator.py`: `OntologyGenerator`.
- `backend/app/services/text_processor.py`: `TextProcessor`.
- `backend/app/utils/file_parser.py`: `FileParser`.
- `backend/app/services/zep_tools.py`: `ZepToolsService`.
- `backend/app/services/simulation_manager.py`: `SimulationManager.get_simulation` (`:1454`).
- `backend/app/models/project.py`: `ProjectManager`, `ProjectStatus`.
- `backend/app/models/task.py`: `TaskManager`, `TaskStatus`.
- `backend/app/utils/chart_html.py`: `inline_plotly_bundle`.

## Invariants, gates, validation

- **Publication barrier** (`backend/app/services/report_agent.py:12435-12594`). A report is customer-publishable only when all of these hold:
  - meta status is `completed`, with no failed or partial sections;
  - the Markdown exists and the final audit hard-passed, at policy version 3, with no hard issues and a matching Markdown SHA;
  - the publish gate passed;
  - the structured forecast, scenario contract and citation-artifact contracts are valid where required;
  - the forecast SHA matches.

  Variants additionally need a publishable primary and matching identity and citation metadata. Report routes that require it: forecast, download, full_report.<lang>.md, pdf, exec-brief, exec-brief.pdf, digest, charts, viz-manifest (report.py:602,725,785,1076,1136,1194,1248,1293,1407). generate, generate/status and check also use it to decide "completed".
- **Draft exposure gate.** Draft prose is served only when publishable, or while the status is pending, planning or generating and generator activity happened within 30 minutes (report.py:153-190). It applies to `/sections`, `/sections-partial`, `/section/<n>`, `/agent-log*` and `/console-log*`. Metadata routes withhold `markdown_content` and the outline prose when not publishable (report.py:55-58).
- **Fail-closed research translation.** A variant is published only after a hard-passed isolated audit. It is served only when the source SHA matches the current `research_report.md` (research.py:532-543, 617-625). The research PDF for a `lang` requires the same (research.py:652-661).
- **Dossier edit gate.** Edits require the right state (research.py:710-714), an unsealed dossier (research.py:720-732) and at least 400 characters (research.py:736-744). The manifest refresh is mandatory (research.py:766-773).
- **Identifier validation.** Pipeline ids must match `^pipe_[A-Za-z0-9_-]+$` (`backend/app/services/pipeline_orchestrator.py:865-872`). Report ids, project ids, task ids and graph ids are **not** validated. Path containment exists only on the report charts route (report.py:1301-1318), the research `chart_*` serve path (research.py:820-833), the viz-manifest path normaliser (report.py:1364-1377) and `resolve_handoff_dir` (`backend/app/services/pipeline_orchestrator.py:905-911`).
- **Concurrency.**
  - `_lifecycle_lock` serializes cancel, resume, continue and delete; fork takes it only for thread registration.
  - The report translation lease is a thread lock plus an advisory file lock. The research translation has only a process-local set.
  - The report PDF has per-(report, lang) locks. The research PDF has none.
- **Polling responses are cache-busted** on `/status` and `/progress` (research.py:332-333, 915-916).
- **Sandbox CSP** is applied by extension to every served `.html` and `.svg` asset on both file-serving routes (research.py:845-859; report.py:1331-1347).

## Failure modes & recovery

- **Restart loses in-memory tasks.** `GET /api/graph/task/<id>` and `POST /api/report/generate/status` with only a `task_id` → 404 after a restart (`backend/app/models/task.py:54-71`).
  - Pipelines survive: `/status` reads disk, and on boot the factory reconciles orphans (`backend/app/__init__.py:139-141`).
  - A report generation thread that dies leaves meta in an in-progress status. The draft gate stops exposing drafts after 30 minutes without activity (report.py:181-188). A rerun needs `POST /generate` with `force_regenerate` only if a publishable report already exists; otherwise a plain POST regenerates.
  - Translations orphaned by a restart are reported as `interrupted`, through a dead-pid check on both the research and report paths (research.py:606-615; `backend/app/services/report_agent.py:12271-12295`). The user retries with POST.
- **Resume paths.**
  - A failed or cancelled pipeline → `POST /resume`. A completed but degraded one → `POST /resume {"force":true}`. A stuck `running` with a dead owner is reclaimed in place (`backend/app/services/pipeline_orchestrator.py:8132-8142`).
  - Research-only → `POST /continue`. A newer-schema state → 409; upgrade, or set `PIPELINE_STRICT_SCHEMA=false`.
- **The PDF build fails closed.** Report: 503 `pdf_build_failed`. Research: 500. Exec brief: 404.
- **The progress `full` snapshot is too large** → 413 rather than a silently truncated result (research.py:918-919). A log changing mid-read → `RuntimeError` → 500 (`backend/app/services/research_progress.py:546-555`).
- **Graph build failure.** The project goes to `failed` with `error` and the task to `failed` with the traceback (graph.py:494-508). Recovery is `POST /build {"force":true}`. A graph created before the failure is left in the store until `/gc` runs.
- **Ontology generation failure** leaves a `created` project with its uploaded files (graph.py:249-254).
- **Uncaught exceptions → HTML 500** on routes without a try/except: `get_dossier` with a malformed id (research.py:392); research translations and PDF with a malformed id (research.py:562,599,646); `list_projects`/`get_project` with a corrupt project.json; `GET /api/graph/tasks` (graph.py:557-561); `get_report_forecast` (report.py:585-627); and the research status `live` block, which is guarded.

## Surprises

1. **Suspected bug: `GET /api/graph/tasks` always 500s once any task exists.** `TaskManager.list_tasks` returns `[t.to_dict() ...]`, which is already a list of dicts (`backend/app/models/task.py:170`). The route calls `.to_dict()` again (graph.py:561), giving an `AttributeError` outside any try/except. Report's `_active_translation_task` uses the same method correctly as dicts (report.py:249-251). No frontend caller exists.
2. **Suspected path traversal on unvalidated ids (destructive).** Werkzeug's default converter accepts `.` and `..` as a segment value. A scratch Flask 3.1.2 / Werkzeug 3.1.4 app routed both `DELETE /api/report/%2E%2E` and `DELETE /api/report/..` to `report_id=".."`; nothing in the repo was touched.
   - `ReportManager.delete_report` then runs `shutil.rmtree(os.path.join(REPORTS_DIR, report_id))` with no validation (`backend/app/services/report_agent.py:14454-14458`). With `".."` that is `uploads/`; with `"."` it is every report.
   - `DELETE /api/graph/project/..` does the same through `ProjectManager.delete_project` (`backend/app/models/project.py:236-241`).
   - The attack surface is limited to loopback or token holders by the auth gate (`backend/app/__init__.py:154-172`), and to same-origin callers by CORS preflight. Not exercised against real code.
3. **Suspected publication-gate bypass through the research artifact route.** During the REPORT stage the orchestrator registers `section_NN_partial` → `reports/<rid>/section_NN.md` (`backend/app/services/pipeline_orchestrator.py:10175-10186`) and `report_chart_*` keys (`:9739-9743, 10198-10203`). These are cleared only at the next simulation or report attempt (`:9682-9691, 12778-12781`).
   - `GET /api/research/<pid>/artifact/section_01_partial` serves the draft Markdown as text (research.py:861-866) without `_draft_exposure_gate`, even for a report that failed its final audit.
   - `report_chart_*` names skip both the report publication check and the symlink/containment re-validation, which runs only for names starting with `chart_` (research.py:816).
   - No test covers this (a grep of `backend/tests` finds no artifact-route test for `section_*_partial`).
4. **The manual graph build ignores the `DEFAULT_CHUNK_SIZE=2500` / `DEFAULT_CHUNK_OVERLAP=250` bump.** `Project` dataclass defaults are 500/50 (`backend/app/models/project.py:49-50`), so `project.chunk_size or Config.DEFAULT_CHUNK_SIZE` (graph.py:340-341) always picks 500. [verifier: overstated. A request-supplied `chunk_size` wins, and the route persists whatever it used into `project.chunk_size` (graph.py:340-345,371), so a later build without the field reuses that stored value; 500 is what you get for a project that never received one (`backend/app/models/project.py:49-50,95-96`). The Config 2500/250 fallback is indeed unreachable unless project.json holds a falsy value] The `build_graph` docstring also says 500/50 (graph.py:268-269). That makes about 5× more episodes than the CHUNK-1 rationale intends (`backend/app/config.py:1052-1054`).
5. **The research translation may spend LLM tokens and then discard the result.** The target language is auto-detected from the source, and the requested `lang` is compared only after the full translation (research.py:514-520). `POST .../translations/en` on an English dossier therefore translates to zh, then records `failed`. The report path rejects this case before spending, through `translation_status` → `source_language` (`backend/app/services/report_agent.py:12202-12206`). `output_language` is hard-coded to `"English"` for every research translation (research.py:512); whether that matters downstream was not verified.
6. **The research translation and research PDF lack the concurrency controls the report equivalents have.** Translation dedupe is only an in-process set (research.py:575-580), with no file lease, so two backend processes can translate concurrently. The research PDF has no lock and no cache, and `export_document_pdf` unlinks the output before rendering (`backend/app/services/report_agent.py:13625`), so concurrent GETs can race. Contrast `_pdf_locks` (`backend/app/services/report_agent.py:11876-11880`).
7. **Inconsistent HTTP codes across sibling routes.**
   - Invalid `lang`: 400 on `/pdf`, `/forecast` and `/translations`; 404 on `/full_report.<lang>.md` (report.py:766-770); silent fallback on `/exec-brief*` (report.py:1133-1134).
   - PDF disabled: 503 on the report PDF (report.py:1069-1074), 404 on the exec-brief PDF, 500 on the research PDF (research.py:681-682).
   - "Already building": 400 on `/build` (graph.py:324-329).
   - Malformed pipeline id: 404 on `/status`, `/progress` and DELETE, but HTML 500 on `/dossier`, `/dossier/translations` and `/dossier/pdf` (research.py:392, 562, 599, 646, from `resolve_handoff_dir` raising at `backend/app/services/pipeline_orchestrator.py:895`).
8. **Dead or no-op code.**
   - The `ZEP_API_KEY` guards (graph.py:287-294, 590-594, 706-710) can never fire, because of the sentinel at `backend/app/config.py:1038`.
   - `os.path.islink(charts_dir)` runs on a realpath'd directory and is always False (report.py:1297, 1307).
   - The download route's in-memory fallback (report.py:730-738) is unreachable behind the publication gate.
   - `_wait_for_episodes` is a no-op shim, yet `/build` still reserves the 55→90 % progress band for it (graph.py:443-457).
9. **Doc-vs-code drift inside the slice.**
   - The research.py module docstring lists 9 of the 18 routes (research.py:5-14).
   - `run_pipeline` says depth defaults to `standard`; it is `deep` (research.py:58 vs `backend/app/config.py:1159`).
   - The `generate_report` docstring says `GET /api/report/generate/status`; the route is POST (report.py:273, 454 vs 468).
   - The sections-partial docstring says `done` means `full_report.md` exists; the code uses publishable (report.py:1701 vs 1711).
   - The `PipelineState.artifacts` comment says values are handoff-relative filenames, but the registry and `get_artifact` use absolute paths (`backend/app/services/pipeline_orchestrator.py:716-718` vs `:9714`; research.py:801).
   - `PipelineManager.load` says the API maps the incompatible sentinel to 409; `/status` returns it with 200 (`backend/app/services/pipeline_orchestrator.py:1153-1155`; research.py:314-334).
10. **The manual report path is weaker than the pipeline report path.** `/api/report/generate` and `/chat` build `ReportAgent` without `quantitative/contested/timeline_events/graph_priors/scenario_spine/scenario_label`, and use `project.simulation_requirement` instead of `state.prompt` (report.py:379-387, 1552-1560 vs `backend/app/services/pipeline_orchestrator.py:13285-13311`). [verifier: `scenario_spine` does not belong in this list. The pipeline REPORT stage does not pass it either; only forecast-seed agents get it (`backend/app/services/pipeline_orchestrator.py:8877-8881`). The real gap is quantitative, contested, timeline_events, graph_priors, graph_priors_structural, scenario_label and base_simulation_id (`:13285-13309`)] `load_research_dossier_for_simulation` also loads `actor_dossier`, which neither route uses (`backend/app/services/pipeline_orchestrator.py:6752,6767,6771`).
11. **`/api/report/chat` has no publication gate.** The interview unlock is enforced only client-side through `/check` (report.py:1868-1869). [verifier: not even client-side today. No frontend code calls `/check` or `/chat` (`chatWithReport` at `frontend/src/api/report.js:53-54` is never imported), so `interview_unlocked` is advisory only] `/tools/search` and `/tools/statistics` are debug endpoints left live.
12. **There are no dedupe or in-flight guards** on `POST /api/report/generate` (report.py:357-445) or on `POST /api/graph/build` with `force` (graph.py:332-336). Either can double-spend LLM calls. `reset_project` does not stop an in-flight build thread; that thread later overwrites the reset with `graph_completed` and a new `graph_id` (graph.py:409-410, 472-473).
13. **The preflight route mutates `sys.path` process-wide.** It inserts `backend/scripts` at index 0 on the first `format=full` call (research.py:375-376). No current module-name collision was found among `backend/scripts/*.py`, but every later import in the server process searches that directory first.
14. **Efficiency.**
    - `/api/research/list` parses every `pipeline_state.json` on each call (`backend/app/services/pipeline_orchestrator.py:1204-1221`).
    - `/api/report/list` runs `publication_status` several times per report, re-hashing the Markdown (report.py:51, 59; `backend/app/services/report_agent.py:12213-12217`).
    - The agent-log and console-log routes re-read the whole file on every poll, even with `from_line` (`backend/app/services/report_agent.py:13798, 13856`).
    - `POST /clean` triggers a graph GC pass for every deleted pipeline (`backend/app/services/pipeline_orchestrator.py:8085, 8100`).
15. **Response shapes are uneven.**
    - `/console-log` includes `draft_withheld` only when withholding and never includes `publishable` (report.py:2033-2035). `/agent-log` always includes all three gate fields (report.py:1947-1948).
    - `get_research_translation` can return `status:"available"` with `available:false` after an edit (research.py:626-628).
    - `_report_publication_payload` replaces the meta.json `translations` list with at most one verified row (report.py:63-70).

## Verification

Adversarial pass on 2026-10-11, branch `main`, against the code on disk. I re-read all three slice files in full, plus every cited service anchor. I also re-ran two behaviour probes in a scratch directory outside the repo with `backend/.venv` (Flask 3.1.2 / Werkzeug 3.1.4). Nothing in the repo was executed or modified, apart from this file.
- Probe 1: Werkzeug routes `DELETE /api/report/..`, `/api/report/%2E%2E`, `/api/report/.` and `/api/report/%2e` to `report_id=".."` or `"."`.
- Probe 2: a non-silent `request.get_json()` with no body or a non-JSON body raises `UnsupportedMediaType` (415) or `BadRequest`. The route's broad `except` then turns that into a 500.

**Verdict counts (48 checked).** 38 confirmed, 9 imprecise, 1 refuted, 0 unverifiable.

| Group | Checked | Confirmed | Imprecise | Refuted | Unverifiable |
|---|---|---|---|---|---|
| Key claims | 15 | 14 | 1 | 0 | 0 |
| Surprises | 13 | 12 | 1 | 0 | 0 |
| Spot-checks of Walkthrough, Control-flow and map-only Surprise statements | 20 | 12 | 7 | 1 | 0 |

Every non-confirmed item is listed below and annotated inline where it appears in the map.

The 12 confirmed spot-checks:
- route counts of 18, 14 and 29;
- no global `errorhandler`;
- pipeline DELETE is traversal-safe;
- the newer-schema sentinel returns 200 on `/status`;
- `status:"available"` can appear with `available:false` after an edit;
- `filter_subgraph` semantics;
- the neighbors route returns 200 for an unknown node;
- the download fallback is unreachable;
- the translation trust windows are 1 h for a `pid:` owner and 15 min otherwise;
- `done = publishable` in `sections-partial`;
- `research.js` has a client for all 18 research routes;
- a restart loses in-memory tasks.

### Non-confirmed items, with corrections

1. **Key claim, preflight ordering (imprecise).** The claim says every `/run`, `/resume`, `/continue` and `/scenario` request runs `preflight_pipeline` "first". Preflight actually runs after input and existence checks, so a request that fails one of them never reaches it:
   - `/run`: prompt, mode, depth, max_rounds, language and model are validated before preflight (research.py:63-98).
   - `/resume`, `/continue`, `/scenario`: the pipeline is loaded first, and a missing one returns 404 (research.py:151-153, 188-190, 227-229).
   - `/scenario` also requires a label first (400, research.py:231-232).

   `/resume` passes no `model`, so it checks credentials for `Config.DEERFLOW_MODEL`, not the run's stored `research_model` (research.py:154; `backend/app/services/pipeline_orchestrator.py:6834`). The rest of the claim is correct: the 400 response carries both `error` and `preflight_errors`, and `/continue` and `/scenario` use `mode="full"`.
2. **Surprise 11 / map Surprise 10 and 11, manual report context (imprecise).** Two parts need correcting:
   - `scenario_spine` is not a gap. The pipeline REPORT stage does not pass it either (`backend/app/services/pipeline_orchestrator.py:13285-13311`); only forecast-seed agents receive it (`:8877-8881`). The real gap is `quantitative`, `contested`, `timeline_events`, `graph_priors`, `graph_priors_structural`, `scenario_label` and `base_simulation_id`.
   - "The interview unlock is client-side via `/check`" is wrong. No frontend code calls `/check` or `/chat`: `chatWithReport` (`frontend/src/api/report.js:53-54`) is never imported, and the only importer of `api/report` is `frontend/src/components/research/ForecastReport.vue:245-249`.

   The rest of the surprise is correct: `/chat` is ungated, `/tools/*` are live, and the manual path uses `project.simulation_requirement`.
3. **Map Control flow step 6 (refuted, for the agent-log/console-log part).** "The UI polls … `agent-log` and `console-log` with `from_line`" is wrong. `getAgentLog` and `getConsoleLog` exist (`frontend/src/api/report.js:28-38`), but nothing imports them, and a grep of `frontend/src` finds no other `agent-log` or `console-log` reference. The UI does poll `sections-partial` and `GET /<rid>` (ForecastReport.vue:245-249).
4. **Map Cross-cutting gates, auth (imprecise).** Forwarded headers only downgrade trust when a forwarded client address is non-loopback (`backend/app/__init__.py:80-81,161`). A wrong token gives 401, not 403 (`:169-171`). OPTIONS requests bypass the gate (`:156-157`).
5. **Map research route 17 anchor (imprecise).** `_register_partial_artifacts` is at `backend/app/services/pipeline_orchestrator.py:10208-10240`, not 10217-10247. The partial names come from `_discover_partial_artifacts` (`:10157-10206`).
6. **Map report route 1 (imprecise).** The orchestrator does not pass `scenario_spine` or `charts_manifest` to `ReportAgent` (`backend/app/services/pipeline_orchestrator.py:13285-13311`). Same root cause as item 2.
6b. **Map report route 18, `/chat` (imprecise).** "Unlocking is decided client-side from `/check`" is wrong: no frontend code calls `/check` or `/chat` (`frontend/src/api/report.js:53-54`; ForecastReport.vue:245-249). Same finding as the second part of item 2, counted separately because the statement appears in the Walkthrough.
7. **Map Lifecycle actions (imprecise).** Fork creates its task and saves state outside `_lifecycle_lock`. It takes the lock only to register and start the thread (`backend/app/services/pipeline_orchestrator.py:8288-8348`).
8. **Map Ordering inside gates (imprecise).** `/exec-brief`, `/exec-brief.pdf` and `/digest` check the feature flag before the report-existence check (report.py:1120-1131, 1177-1189, 1235-1246).
9. **Map Surprise 4, chunk size (imprecise).** "Always picks 500" is overstated:
   - A request-supplied `chunk_size` wins.
   - The route saves the value it used into `project.chunk_size` (graph.py:340-345, 371), so a later build without the field reuses that stored value.
   - 500 applies only to a project that never received a value.

   The underlying claim holds: the Config 2500/250 fallback is unreachable unless project.json holds a falsy value.

### Nuances on confirmed items (no correction needed)

- **Progress tail.** `lines=0` falls back to 200, not 1, because of `int(limit or 200)` (`backend/app/services/research_progress.py:502`). Negative values clamp to 1.
- **Publication barrier.** The SHA is computed over the UTF-8 re-encoding of the text-mode read, so universal-newline translation applies. It is not a raw-bytes hash (`backend/app/services/report_agent.py:12472-12478`).
- **Traversal-to-rmtree (key claim and Surprise 2).** I re-verified the routing behaviour. `os.path.join(REPORTS_DIR, "..")` exists and is a directory, so `shutil.rmtree` is reached (`backend/app/services/report_agent.py:14454-14458`). The same holds for `ProjectManager.delete_project` (`backend/app/models/project.py:236-241`). The destructive effect was not exercised.

### Omissions (significant behaviour the map does not mention)

1. **`/resume` preflight ignores the per-run research model.** See item 1 (research.py:154; `backend/app/services/pipeline_orchestrator.py:6834`).
2. **Non-silent `request.get_json()` returns 500 for a body-less or non-JSON POST** on `/api/graph/build` (graph.py:297), `/api/report/generate` (report.py:293), `/generate/status` (report.py:491), `/chat` (report.py:1506), `/tools/search` (report.py:2104) and `/tools/statistics` (report.py:2150). Flask raises 415 or 400, and the broad `except` converts it to a 500. All research.py routes use `silent=True`.
3. **The current SPA uses only part of the report and graph client surface.**
   - `ForecastReport.vue` imports only `getReport`, `getVizManifest`, `getSectionsPartial`, the translation helpers, the URL builders and `getForecast` (`frontend/src/components/research/ForecastReport.vue:245-249`).
   - `GraphPanel.vue` and `ResearchView.vue` use only the graph-data, node and neighbors helpers (`frontend/src/components/GraphPanel.vue:306-310`; `frontend/src/views/ResearchView.vue:232`).
   - The manual MiroFish clients (`generateOntology`, `buildGraph`, `getTaskStatus`, `generateReport`, `getReportStatus`, `chatWithReport`, `getAgentLog`, `getConsoleLog`) are unreferenced.
4. **The research artifact route also bypasses the report gate for other REPORT-owned keys.** It serves `report_viz_manifest`, the report's `viz_manifest.json` returned as parsed JSON (`backend/app/services/pipeline_orchestrator.py:9556-9561`). It also serves run-stage `*_partial` keys (`run_state`, `actions_twitter`, `actions_reddit`; `:10167-10174`). None of these pass through any publication or draft gate (research.py:861-866). This extends Surprise 3.
5. **The bounded tail silently drops progress sources beyond 16 tracks or 16 preserved attempts.** It does not set `truncated` for dropped sources (`backend/app/services/research_progress.py:439,462,506-517`). Only `scope=full` raises 413 for this.
6. **`/api/graph/build` does not coerce or validate body fields.** `force` is not bool-coerced, so the string `"false"` is truthy (graph.py:316). `chunk_size` and `chunk_overlap` are not int-validated, so a bad value surfaces only later as a failed task inside the build thread (graph.py:340-345, 393-397).
