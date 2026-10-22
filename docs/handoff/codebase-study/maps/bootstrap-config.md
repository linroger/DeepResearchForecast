# bootstrap-config — App bootstrap, Config, models, auth, settings/SDK API

Branch `main` at commit `c20ec60`, read from disk on 2026-10-11. Paths are relative to the repo root. Every claim below cites `file:line`. Where something is inferred and was not executed, it is labelled **suspected** or **unverified**.

Slice files (3,512 lines, all read in full): `backend/run.py` (62), `backend/app/__init__.py` (260), `backend/app/config.py` (1656), `backend/app/models/__init__.py` (9), `backend/app/models/project.py` (309), `backend/app/models/task.py` (184), `backend/app/utils/__init__.py` (9), `backend/app/utils/security.py` (156), `backend/app/utils/logger.py` (153), `backend/app/utils/atomic.py` (77), `backend/app/api/__init__.py` (22), `backend/app/api/settings.py` (186), `backend/app/api/sdk.py` (356), `backend/app/services/__init__.py` (73).

---

## Purpose & position in the pipeline

This slice is the process shell that every pipeline stage runs inside. It does not run research, graph building, simulation or reporting itself.

1. **Entry point.** `backend/run.py:25-57` validates configuration, builds the Flask app, optionally starts the resolution-monitor scheduler, and serves on `FLASK_HOST:FLASK_PORT` (default `127.0.0.1:5001`).
2. **App factory.** `create_app` (`backend/app/__init__.py:84-260`) does the following, in order:
   - registers CORS;
   - runs startup lifecycle hooks: orphan simulation and pipeline reconciliation, graph garbage collection, and shutdown signal handlers;
   - installs the `/api/*` auth gate and request logging;
   - mounts five blueprints, plus `/api/v1` when enabled;
   - serves `/health` and the built Vue SPA from `frontend/dist`.
3. **`Config`.** `backend/app/config.py:27-1638` is the single configuration surface: about 399 class attributes plus 13 classmethods. It loads `<repo>/.env` once at import with `override=True` (`config.py:12-24`). The research subprocess, graph, simulation and report stages all read it. It also switches the LLM provider at runtime through `Config.apply_provider` (`config.py:913-976`), which the settings API exposes.
4. **Models.**
   - `Project` / `ProjectManager` (`models/project.py`) persist a legacy "project" record (uploaded files → ontology → graph) to `uploads/projects/<id>/project.json`. The orchestrator's ONTOLOGY stage creates one per pipeline (`backend/app/services/pipeline_orchestrator.py:12311-12325`).
   - `TaskManager` (`models/task.py`) is an in-memory, process-local task registry used for progress polling.
5. **Utilities.** `utils/security.py` handles secret redaction, `.env` value sanitization and SSRF URL validation. `utils/logger.py` handles logging to console and a rotating file. `utils/atomic.py` provides the tmp-file + fsync + `os.replace` writers that roughly 20 modules use for artifact and state files.
6. **Settings API.** `api/settings.py`, mounted at `/api/settings`, lets the UI read, switch and connectivity-test the LLM provider.
7. **SDK API.** `api/sdk.py`, mounted at `/api/v1` only when `API_V1_ENABLED=true`, is a thin, versioned alias over the orchestrator, `PipelineManager`, `ReportManager` and `backtest` for headless clients.

---

## Walkthrough (source order)

### backend/run.py

| Block | Lines | Behavior |
|---|---|---|
| Windows UTF-8 shim | `run.py:9-16` | On `win32` only: `os.environ.setdefault('PYTHONIOENCODING','utf-8')` and reconfigures stdout/stderr to UTF-8 with `errors='replace'`. Runs before any app import. |
| `sys.path` insert | `run.py:19` | Puts `backend/` first on `sys.path` so `import app` resolves. |
| Imports | `run.py:21-22` | `from app import create_app` triggers the whole import chain: `app/__init__.py` → `app.config` (dotenv load + env `setdefault`s), `app.utils.logger` (through `utils/__init__.py`, which eagerly imports `FileParser` and `LLMClient`), `app.utils.security`. |
| `main()` validate | `run.py:28-34` | `Config.validate()`. If it returns any error, prints `配置错误:` and each error, then `sys.exit(1)`. This is the **only** caller of `Config.validate()` in `backend/app`, `backend/scripts` or `run.py` (grep). |
| Build app | `run.py:37` | `create_app()`. This runs the destructive lifecycle hooks (orphan reconcile, graph GC) **before** the port is bound. |
| Resolution autorun | `run.py:41-42` | `app.services.resolution_autorun.start()`. It starts a daemon thread only when `RESOLUTION_MONITOR_AUTORUN_HOURS > 0` (`resolution_autorun.py:94-101`). The first run is after 60 s, then once every N hours, each as a subprocess `python backend/scripts/resolution_monitor.py run --all-recent` with a 15-minute timeout (`resolution_autorun.py:28,43-48,105-111`). Only the production entry point calls this; `create_app()` never does. |
| Host/port | `run.py:47-49` | `FLASK_HOST` default `'127.0.0.1'`; `FLASK_PORT` default `5001` (bare `int()`, so a non-numeric value raises); `debug = Config.DEBUG`. |
| Exposure warning | `run.py:50-54` | When the host is not in `('127.0.0.1','localhost','::1')` and `APP_API_TOKEN` is empty, prints a warning only and does not exit. The warning says the APIs are open without auth, but the gate actually fails closed with 403 (see Surprises). |
| Serve | `run.py:57` | `app.run(host, port, debug, threaded=True)` uses the Werkzeug dev server in threaded mode. With `debug=True`, Flask enables the reloader and the debugger. |

### backend/app/__init__.py

| Name | Lines | Behavior |
|---|---|---|
| warnings filter | `__init__.py:13` | Suppresses `resource_tracker` warnings before other imports. |
| `_frontend_dist_dir()` | `__init__.py:23-33` | Returns `abspath(FRONTEND_DIST)` if that env var is set and non-blank, otherwise `<repo>/frontend/dist` (three `dirname`s up from `app/__init__.py`). |
| `_strip_addr_port(value)` | `__init__.py:36-43` | Strips whitespace and `"` characters. `[v6]:port` becomes `v6`. If there is exactly one `:`, the port is dropped (`10.0.0.5:80` → `10.0.0.5`). Bare IPv6 (2+ colons) is returned unchanged. |
| `_is_loopback_addr(addr)` | `__init__.py:46-59` | Empty → False. `'localhost'` → True. Otherwise `ipaddress.ip_address`; an IPv4-mapped IPv6 address is unwrapped; returns `ip.is_loopback`. Unparseable values → **False** (fail-closed). |
| `_forwarded_client_addrs(headers)` | `__init__.py:62-74` | Collects every comma-split value of `X-Forwarded-For` and `X-Real-IP`, plus every `for=` parameter of RFC 7239 `Forwarded` (split on `,` then `;`). Empty strings are dropped. |
| `_has_forwarded_remote_client(headers=None)` | `__init__.py:77-81` | True if **any** forwarded address is not loopback. An unparseable value such as `unknown` or `_hidden` counts as remote. Defaults to `request.headers`. |
| `create_app(config_class=Config)` | `__init__.py:84-260` | Factory. Details follow. |
| Flask object | `__init__.py:88-89` | `Flask(__name__, static_folder=_frontend_dist_dir(), static_url_path='')` → Flask auto-registers the rule `/<path:filename>` with endpoint `static`. Then `app.config.from_object(config_class)` copies all UPPERCASE `Config` attributes, so `MAX_CONTENT_LENGTH=50MB` (`config.py:1047`) becomes Flask's request-size cap. |
| JSON | `__init__.py:93-94` | `app.json.ensure_ascii = False` (the Flask ≥2.3 provider API). |
| Logger | `__init__.py:97` | `setup_logger('mirofish')`. |
| Startup-log gating | `__init__.py:100-107` | `should_log_startup = not DEBUG or WERKZEUG_RUN_MAIN=='true'`, so startup lines are printed once under the reloader. |
| CORS | `__init__.py:111-116` | Reads the **class** attribute `Config.APP_CORS_ORIGINS`, not `app.config`. `'*'` means all origins. Otherwise a comma-split list; an empty list falls back to `["http://localhost:3000"]`. Applied only to `r"/api/*"`. |
| Lifecycle gate | `__init__.py:122-125` | `_runtime_lifecycle_enabled = not app.config['TESTING'] and DRF_TEST_PROCESS != '1'`. `backend/tests/conftest.py:19` sets `DRF_TEST_PROCESS=1` at import time. |
| Lifecycle hooks (prod) | `__init__.py:126-143` | In order: (1) `SimulationRunner.register_cleanup()`; (2) `SimulationRunner.reconcile_orphans()`; (3) `PipelineOrchestrator.reconcile_orphans()`; (4) `PipelineOrchestrator.register_cleanup()`. Order matters because (4) chains to the handler from (1). See Control flow. |
| Test branch | `__init__.py:144-145` | Logs `测试进程：已禁用破坏性运行时注册与孤儿回收` only. |
| `_auth_gate` (before_request #1) | `__init__.py:154-172` | 1) `OPTIONS` → allow (CORS preflight). 2) Path `/health`, or any path not starting with `/api/`, → allow (so SPA/static is never gated). 3) Remote is loopback **and** no forwarded header names a non-loopback client → allow. 4) No `Config.APP_API_TOKEN` → **403** `{"success":false,"error":"forbidden: API is loopback-only unless APP_API_TOKEN is configured"}`. 5) `hmac.compare_digest(X-API-Token header, token)` fails → **401** `{"success":false,"error":"unauthorized"}`. Every HTTP method is covered (GET too), not only mutations. Forwarding headers can only reduce trust (`__init__.py:148-151`). |
| `log_request` (before_request #2) | `__init__.py:175-181` | Logger `mirofish.request`. DEBUG `请求: METHOD path`. For JSON content types it parses the body (`get_json(silent=True)`) and DEBUG-logs `redact_secrets(body)`. It does not run when `_auth_gate` returned a response, because Flask stops at the first non-None `before_request`. |
| `log_response` (after_request) | `__init__.py:183-197` | DEBUG logs the status. When **not** `app.config['DEBUG']` and the response is JSON whose top level is a dict with a `traceback` key, that key is removed and the body re-serialized with `ensure_ascii=False`. Errors in this step are swallowed. This is the single point that strips tracebacks for all blueprints. |
| Blueprints | `__init__.py:200-205` | `graph_bp → /api/graph`, `simulation_bp → /api/simulation`, `report_bp → /api/report`, `research_bp → /api/research`, `settings_bp → /api/settings`. |
| Optional v1 | `__init__.py:210-214` | If `getattr(Config,'API_V1_ENABLED',False)`, registers `sdk_bp` at `/api/v1`. It inherits the `/api/*` gate and CORS. |
| `/health` | `__init__.py:217-219` | `{'status':'ok','service':'MiroFish Backend'}`. Never gated. |
| `_serve_spa(filename='')` | `__init__.py:228-248` | `health` or `api/...` → JSON 404 `not found: /<filename>`. An existing file inside dist (via `werkzeug.security.safe_join`) → `send_from_directory`. Anything else → `index.html` if present (history-mode fallback). With no dist built → **200** JSON `{"success":true,"service":"MiroFish Backend","hint":"frontend not built — run: cd frontend && npm run build"}`. |
| Static override | `__init__.py:254-255` | Replaces the view of the built-in `static` endpoint with `_serve_spa`, because a separate catch-all rule would be shadowed. Adds `/` as `spa_index`. |
| Return | `__init__.py:257-260` | Logs `MiroFish Backend 启动完成`. |

### backend/app/config.py — module level

| Block | Lines | Behavior |
|---|---|---|
| `.env` load | `config.py:12-24` | Path `<repo>/.env`, computed as `backend/app/../../.env`. If `DRF_TEST_PROCESS=='1'`, nothing is loaded. Else, if the root `.env` exists, `load_dotenv(path, override=True)`, so **`.env` values override variables already set in the process environment**. Else `load_dotenv(override=True)` with no path, which uses python-dotenv's upward search from the caller's directory. |
| `class Config` | `config.py:27-1638` | Every attribute is evaluated **once, at import**. Later changes to `os.environ` are not seen, except through `apply_provider`. Boolean knobs use `os.environ.get(X, default).strip().lower() == 'true'`, so only the string `true` (any case) enables a flag; `1`, `yes` and `on` all mean False. [verifier: one exception to the `.strip()` pattern: `DEBUG` is `os.environ.get('FLASK_DEBUG','False').lower() == 'true'` with no `.strip()` (config.py:35); the "only `true`" conclusion still holds (config.py:35,58)] Most integer knobs use `int(os.environ.get(X,'d') or 'd')` (an empty value falls back to the default), but about 20 use bare `int(os.environ.get(X,'d'))` (see Failure modes). |
| key-env defaults | `config.py:1647-1650` | For each `PROVIDER_META[*].key_env` (`KIMI_API_KEY`, `MINIMAX_API_KEY`, `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, `ZHIPUAI_API_KEY`), `os.environ.setdefault(key, '')`. This lets DeerFlow's `config.yaml` resolve `$VAR` placeholders for every stanza without raising. |
| GRAPHITI_MAX_COROUTINES export | `config.py:1656` | `os.environ.setdefault('GRAPHITI_MAX_COROUTINES', str(Config.GRAPHITI_MAX_COROUTINES))` (default 16). The reason is that `services/graphiti_client/runtime.py` reads the raw env with its own default of 8. [verifier: wrong. runtime.py now reads `int(os.environ.get("GRAPHITI_MAX_COROUTINES", "16"))` with a ValueError fallback to 16 (backend/app/services/graphiti_client/runtime.py:396-398). The "8" comes from the stale comment at config.py:1652-1653, so for the default value the setdefault is redundant. It only matters when `.env` sets a non-default value, and even then runtime.py would read it from os.environ anyway (config.py:1656)] |

### backend/app/config.py — classmethods

| Method | Lines | Behavior |
|---|---|---|
| `fast_model()` | `config.py:144-147` | `LLM_FAST_MODEL or LLM_MODEL_NAME`. Caller: `utils/llm_client.py:373`. |
| `strong_model()` | `config.py:149-152` | `LLM_STRONG_MODEL or LLM_MODEL_NAME`. Caller: `utils/llm_client.py:374`. |
| `context_window_for(provider)` | `config.py:154-157` | `PROVIDER_CONTEXT_WINDOWS[provider.lower()]` (openai 128000, kimi 256000, minimax 512000, deepseek 1000000, qwen 131072, glm 200000, claude-cli/codex-cli 200000; `config.py:131-141`), else `DEFAULT_CONTEXT_WINDOW` (32000). Callers: `report_agent.py:2361`, `oasis_profile_generator.py:1954`, `simulation_config_generator.py:1927`. |
| `reasoning_extra_body(provider=None)` | `config.py:825-843` | Uses an explicit provider, else `LLM_PROVIDER`. Returns `None` when the provider's disable flag is off (`LLM_KIMI_DISABLE_THINKING`, `LLM_MINIMAX_DISABLE_THINKING`, or `LLM_DISABLE_THINKING` for deepseek/qwen/glm). Otherwise returns `_DISABLE_THINKING_EXTRA_BODY[p]`: `{"thinking":{"type":"disabled"}}` for kimi, minimax, deepseek and glm; `{"enable_thinking":False}` for qwen; `None` for other providers (`config.py:817-823`). Callers: `utils/llm_client.py:893` (with a provider), `utils/oasis_llm.py:591` (without one). |
| `kimi_extra_body()` | `config.py:846-848` | Back-compat alias. **No callers** anywhere in `backend/` (grep). |
| `provider_info()` | `config.py:879-893` | `{current, deerflow_model, has_api_key, base_url, model_name, providers:[{id,label,needs_key,deerflow_model}]}`. The key itself is never returned. |
| `resolve_endpoint(provider, base_url=None, model=None)` | `config.py:895-910` | For both URL and model: explicit value > current configured value (**only if** `provider == LLM_PROVIDER`) > `PROVIDER_META` default > `https://api.openai.com/v1` / `gpt-4o-mini`. |
| `apply_provider(provider, api_key, base_url, model)` | `config.py:912-976` | See Control flow. Validates the provider against `SUPPORTED_LLM_PROVIDERS`. Requires a key for `needs_key` providers unless re-saving the current provider that already has a key. Sanitizes every field (`sanitize_env_value`). Validates `base_url` for SSRF (`validate_safe_url`, `block_private=APP_BLOCK_PRIVATE_URLS`). Under `_provider_lock` it mutates the class attributes `LLM_PROVIDER`, `_is_*` and `DEERFLOW_MODEL` (from `PROVIDER_META.deerflow_model`); for OpenAI-compatible providers also `LLM_BASE_URL`/`LLM_MODEL_NAME` (via `resolve_endpoint`) and `LLM_API_KEY`, mirrored into the provider's `key_env`. It then writes `os.environ` and calls `_persist_env`. Returns `provider_info()`. Raises `ValueError` with a Chinese message on bad input. |
| `_persist_env(updates)` | `config.py:978-1009` | Upserts keys into `<repo>/.env`. It replaces the first matching non-comment `KEY=` line, appends missing keys, and writes atomically (`write_text_atomic`). Values pass through `sanitize_env_value` and then `quote_env_value`. **All exceptions are swallowed** (`config.py:1008-1009`). |
| `report_section_target_chars()` | `config.py:1124-1136` | Parses `REPORT_SECTION_TARGET_CHARS` (`'lo-hi'`). Returns `(lo,hi)` when `0<lo<hi`, else `(3000,6000)`. |
| `deerflow_depth_budget(depth)` | `config.py:1558-1578` | `raw = DEERFLOW_DEPTH_BUDGETS.get(depth, DEERFLOW_RESEARCH_TIMEOUT)` with `{'quick':900,'standard':7200,'deep':21600}` (`config.py:1553`). Multiplied by 1.5 if any of `DEERFLOW_DUAL_TRACK`, `DEERFLOW_SUBAGENTS` or `RESEARCH_DEEP_FANOUT` is true; all three default to true, so the effective deep budget is 32400 s. Callers: `pipeline_orchestrator.py:2283,7318`. [verifier: 32400 s is the method's return value, not always the watchdog's budget. The research runner uses an explicit `timeout` argument first, then `Config.DEERFLOW_RESEARCH_TIMEOUT` whenever `DEERFLOW_RESEARCH_TIMEOUT` is non-blank in os.environ, and only then this method (pipeline_orchestrator.py:2278-2283). An unknown depth falls back to `DEERFLOW_RESEARCH_TIMEOUT` and is also multiplied by 1.5 (config.py:1569-1575). The run-manifest snapshot always records the method value (pipeline_orchestrator.py:7318)] |
| `_is_placeholder(value)` | `config.py:1590-1592` | True if the value is in `_PLACEHOLDER_VALUES` (`config.py:1585-1588`). Used by `scripts/preflight.py:162` via `getattr`. |
| `validate()` | `config.py:1594-1638` | Returns a list of error strings: (1) `LLM_PROVIDER` not supported; (2) `needs_key` provider without `LLM_API_KEY`; (3) `GRAPH_BACKEND` not in `auto/falkordblite/falkordb/kuzu`; (4) `DEERFLOW_MODEL` not in `SUPPORTED_DEERFLOW_MODELS`, while a missing model key env var is only **logged as a warning** to `mirofish.config`; (5) `OASIS_CLI_SEMAPHORE` / `OASIS_SEMAPHORE` not an int ≥ 1. |

### backend/app/models/project.py

| Name | Lines | Behavior |
|---|---|---|
| `ProjectStatus` | `project.py:17-23` | `created`, `ontology_generated`, `graph_building`, `graph_completed`, `failed`. |
| `Project` dataclass | `project.py:26-53` | Fields: `project_id`, `name`, `status`, `created_at`, `updated_at`, `files` (list of dicts), `total_text_length=0`, `ontology=None`, `analysis_summary=None`, `graph_id=None`, `graph_build_task_id=None`, `simulation_requirement=None`, **`chunk_size=500`**, **`chunk_overlap=50`**, `error=None`. |
| `to_dict` / `from_dict` | `project.py:55-98` | Straight field mapping. `from_dict` defaults the name to `Unnamed Project` and chunk values to 500/50. It calls `ProjectStatus(str)`, which **raises `ValueError` on an unknown status**. |
| `ProjectManager.PROJECTS_DIR` | `project.py:105` | `Config.UPLOAD_FOLDER/projects`, i.e. `backend/uploads/projects`. |
| path helpers | `project.py:107-130` | Directory `<PROJECTS_DIR>/<id>`, meta `project.json`, files `files/`, text `extracted_text.txt`. **No validation of `project_id`.** |
| `create_project(name)` | `project.py:132-165` | Id `proj_<uuid4 hex[:12]>`, ISO-local timestamps. Creates the directory and `files/`, then calls `save_project`. |
| `save_project(project)` | `project.py:167-178` | Sets `updated_at = now`, then `write_json_atomic(project.json, to_dict())` (tmp + fsync + replace, `indent=2`, `ensure_ascii=False`). |
| `get_project(id)` | `project.py:180-199` | Returns `None` if `project.json` is absent. Otherwise `json.load` + `from_dict`. **Corrupt JSON or an unknown status raises.** |
| `list_projects(limit=50)` | `project.py:201-223` | Calls `get_project` on every entry of `PROJECTS_DIR`, sorts by `created_at` descending (string compare), returns up to `limit`. Has no try/except, so one corrupt project fails the whole listing. |
| `delete_project(id)` | `project.py:225-242` | Returns False if the directory is absent. Otherwise `shutil.rmtree(project_dir)` (errors propagate). |
| `save_file_to_project(id, file_storage, original_filename)` | `project.py:244-276` | Saves as `<uuid4 hex[:8]><lowercased ext>`. Returns `{original_filename, saved_filename, path, size}`. |
| `save_extracted_text` / `get_extracted_text` | `project.py:278-294` | Plain, **non-atomic** `open('w')` write and read of `extracted_text.txt`. |
| `get_project_files(id)` | `project.py:296-308` | Lists regular files under `files/`. |

### backend/app/models/task.py

| Name | Lines | Behavior |
|---|---|---|
| `TaskStatus` | `task.py:14-19` | `pending`, `processing`, `completed`, `failed`. |
| `Task` dataclass | `task.py:22-51` | `task_id`, `task_type`, `status`, `created_at`/`updated_at` (datetime), `progress` 0-100, `message`, `result`, `error`, `metadata`, `progress_detail`. `to_dict` emits ISO timestamps and `status.value`. |
| `TaskManager.__new__` | `task.py:60-71` | Double-checked-lock **singleton**. `_tasks: Dict[str,Task]` and `_task_lock` are created once. **In memory only; nothing is persisted.** |
| `create_task(task_type, metadata)` | `task.py:73-99` | Id `str(uuid4())`, status PENDING. |
| `get_task` / `update_task` | `task.py:101-143` | `update_task` silently does nothing for an unknown id. Otherwise it updates `updated_at` and each non-None field. |
| `complete_task` / `fail_task` | `task.py:145-162` | COMPLETED + progress 100 + `任务完成`; FAILED + `任务失败` + error (progress unchanged). |
| `list_tasks(task_type)` | `task.py:164-170` | Optional type filter, newest first, returned as dicts. |
| `cleanup_old_tasks(max_age_hours=24)` | `task.py:172-183` | Drops COMPLETED/FAILED tasks older than the cutoff. **No callers** in `backend/app` or `backend/scripts` (grep), so the registry grows for the life of the process. |

### backend/app/models/__init__.py, utils/__init__.py, services/__init__.py, api/__init__.py

- `models/__init__.py:5-8` re-exports `TaskManager`, `TaskStatus`, `Project`, `ProjectStatus`, `ProjectManager`.
- `utils/__init__.py:5-8` **eagerly imports** `FileParser` and `LLMClient`. Importing anything under `app.utils` (even `app.utils.atomic`) therefore loads `llm_client.py`, which imports `app.config` (`utils/llm_client.py:22`), and that import triggers the `.env` load and env `setdefault` side effects.
- `services/__init__.py:5-38` **eagerly imports** ten service modules (ontology_generator, graph_builder, text_processor, zep_entity_reader, oasis_profile_generator, simulation_manager, simulation_config_generator, simulation_runner, zep_graph_memory_updater, simulation_ipc). Any `from .services.X import ...`, such as the one in `create_app`, pays this whole import.
- `api/__init__.py:7-11` creates blueprints `graph`, `simulation`, `report`, `research` and `settings`. Lines 13-17 import the route modules. Line 21 imports `sdk_bp` **unconditionally** (which imports `pipeline_orchestrator`, `report_agent` and `backtest`); only registration is conditional.

### backend/app/utils/security.py

| Name | Lines | Behavior |
|---|---|---|
| `_SECRET_KEY_RE` | `security.py:20-24` | Case-insensitive search for `api_key`/`api-key`/`apikey`, `secret`, `password`, `passwd`, `authorization`, `bearer`, `credential`, `token`, or `key`/`keys` bounded by start/end/`_`/`-`. |
| `_SECRET_TOKEN_RE` | `security.py:27-30` | Inline tokens: `sk-…` (8+ chars), `sk-cp-…`, `AIza…` (20+), `ghp_…` (20+). |
| `redact_secrets(obj)` | `security.py:35-53` | Recursive. A dict value whose key matches is replaced with `***REDACTED***`. Lists and tuples become lists. Strings are scrubbed of inline tokens. Returns a new object. |
| `redact_text(text)` | `security.py:56-60` | Scrubs inline tokens only. No production caller; used only in `backend/tests/test_utils_security.py`. |
| `sanitize_env_value(value)` | `security.py:68-80` | `None` → `''`. Any `[\x00-\x1f\x7f]` (including newlines) → `ValueError`. Returns the value stripped. |
| `quote_env_value(value)` | `security.py:83-94` | Empty values, or values containing whitespace, `#`, `=`, `"`, `'` or `\`, are double-quoted with `\` and `"` escaped. Other values are returned verbatim. |
| `_is_always_blocked(ip)` | `security.py:101-107` | link-local, multicast, reserved, unspecified. |
| `validate_safe_url(url, block_private=False)` | `security.py:110-156` | Requires http/https and a host. **Resolves DNS** with `socket.getaddrinfo(host, port or 443/80)` and checks every resolved address. Loopback is allowed unless `block_private`; always-blocked families are rejected; private ranges are rejected only when `block_private`. Raises `ValueError`. Returns the stripped URL. |

### backend/app/utils/logger.py

| Name | Lines | Behavior |
|---|---|---|
| `ClosedStreamSafeHandler` | `logger.py:12-31` | A `StreamHandler` that stays silent once its stream is closed (avoids noise from atexit and test teardown). |
| `_ensure_utf8_stdout` | `logger.py:34-44` | UTF-8 reconfiguration on win32 only. |
| `LOG_DIR` | `logger.py:48` | `backend/logs`. |
| `setup_logger(name='mirofish', level=DEBUG)` | `logger.py:51-116` | Creates the log directory, sets the level, `propagate=False`, and returns early if the logger already has handlers. Otherwise it adds (1) a `TimedRotatingFileHandler(backend/logs/mirofish.log, when='midnight', backupCount=30)` with suffix `%Y-%m-%d`, file level `LOG_LEVEL` (default INFO) and a detailed format; and (2) a console handler on stdout at INFO with a short format. |
| `get_logger(name)` | `logger.py:119-132` | Calls `setup_logger(name)` when the named logger has no handlers. **Each distinct name therefore gets its own file handler on the same `mirofish.log`.** There are 29 distinct names in `backend/app` and `backend/scripts` (grep). |
| module logger + helpers | `logger.py:136-153` | `setup_logger()` runs at import. `debug/info/warning/error/critical` wrap the `mirofish` logger. |

### backend/app/utils/atomic.py

| Name | Lines | Behavior |
|---|---|---|
| `write_text_atomic(path, text, encoding='utf-8', fsync=True)` | `atomic.py:20-50` | `makedirs(parent)`, then `tempfile.mkstemp(prefix='.tmp-', dir=parent)`, write, flush, optional `os.fsync`, `os.replace(tmp, path)`. On any `BaseException` the tmp file is unlinked and the exception re-raised. |
| `write_json_atomic(path, obj, ensure_ascii=False, indent=2, fsync=True, allow_nan=True)` | `atomic.py:53-77` | `json.dumps(..., default=str, allow_nan=True)` passed to `write_text_atomic`. |

### backend/app/api/settings.py (mounted `/api/settings`)

| Route / fn | Lines | Behavior |
|---|---|---|
| `GET /llm` → `get_llm_settings` | `settings.py:25-27` | `{"success":true,"data":Config.provider_info()}`. |
| `POST /llm` → `set_llm_settings` | `settings.py:30-49` | Body `{provider, api_key?, base_url?, model?}`. A missing provider → 400 `缺少 provider`. Calls `Config.apply_provider(...)`, which **persists to `.env`**. `ValueError` → 400 with the message; any other exception → 500 `internal server error` (details only in the log). |
| `_TEST_TIMEOUT_SECONDS` | `settings.py:54` | 25 s. |
| `_test_cli_provider(provider)` | `settings.py:57-74` | Picks `claude` or `codex`, depending on the provider. Missing from PATH → `{"ok":False,"error":...}`. Otherwise runs a **subprocess** `<cli> --version` (timeout 10 s) and keeps the first line, truncated to 120 chars; errors are ignored. Returns `{"ok":True,"detail":"<path> · <version>"}`. It does not test login or quota. |
| `_test_openai_compat_provider(provider, api_key, base_url, model)` | `settings.py:77-148` | No key → `ok:False`. `validate_safe_url(base_url, block_private=APP_BLOCK_PRIVATE_URLS)` (DNS lookup). Then `OpenAI(api_key, base_url, timeout=25, max_retries=0)`; for kimi it adds a `User-Agent: Config.LLM_USER_AGENT` header (default `claude-cli/1.0.0`, `config.py:803`). Sends one chat completion `"Reply with exactly: pong"` with `temperature=0` and `max_tokens=16`, plus `extra_body` from `_DISABLE_THINKING_EXTRA_BODY[provider]`, **always** taken from the dict regardless of the `*_DISABLE_THINKING` flags. For kimi the temperature is forced to 0.6 when thinking is disabled, else 1.0. An exception is mapped to `{ok:False,status_code,error:hint}` (401/403/404/429 hints, else a generic message); the raw error goes only to the log. Success → `{ok:True,latency_ms,model,reply[:80]}`. |
| `POST /llm/test` → `test_llm_settings` | `settings.py:151-186` | Provider defaults to `Config.LLM_PROVIDER`. Unknown → 400. CLI providers → `_test_cli_provider`. OpenAI-compatible providers use the supplied key, else the saved `LLM_API_KEY` **only if provider == current**. The endpoint comes from `Config.resolve_endpoint`. Always 200 with `data.ok` true/false; 500 only on an unexpected exception. **Nothing is persisted.** |

### backend/app/api/sdk.py (mounted `/api/v1` only if `API_V1_ENABLED`)

| Route / fn | Lines | Behavior |
|---|---|---|
| validation sets | `sdk.py:61-63` | `_VALID_DEPTH={quick,standard,deep}`, `_VALID_MODE={full,research_only}`, `_VALID_LANGUAGES={Chinese,English,auto}`. These duplicate `api/research.py:41-44`. [verifier: the research.py sets are at lines 40-43 (backend/app/api/research.py:40-43)] |
| `_ok` / `_err` | `sdk.py:66-73` | Envelope `{"success":true,"data":…}` or `{"success":false,"error":…}`. |
| `POST /run` → `v1_run` | `sdk.py:76-153` | Requires `prompt` (else 400). Then: mode (default `full`); depth (default `Config.DEERFLOW_RESEARCH_DEPTH`); `max_rounds` must parse as an int; language (`auto` → `''`, meaning no `--target-language`); model must be in `SUPPORTED_DEERFLOW_MODELS` and is lowercased. Then `preflight_pipeline(mode, model)`; on errors → 400 with `preflight_errors`. Then `PipelineOrchestrator.start(...)` → `{pipeline_id, task_id, mode, status}`. An exception → 500 with `str(e)`. |
| `GET /status/<pipeline_id>` | `sdk.py:156-170` | `PipelineManager.load` → raw `pipeline_state.json` dict, or 404. Unlike `/api/research/status`, no `live` block and no no-store headers (`api/research.py:314-334`). |
| `GET /list` | `sdk.py:173-183` | `{"pipelines": PipelineManager.list_pipelines()}` (all pipelines, unpaginated). |
| `GET /dossier/<pipeline_id>` | `sdk.py:186-220` | Reads `research_report.md`, `actors.json`, `sources.json` and `timeline.json` from the **static** `PipelineManager.handoff_dir(id)`. A missing directory → 404. An invalid id raises `ValueError` from `_validate_id` (`pipeline_orchestrator.py:868-872`) → 500. Corrupt JSON → 500. |
| `_forecast_path` / `_resolved_path` / `_load_forecast` | `sdk.py:223-235` | `uploads/reports/<id>/forecast.json`, `uploads/reports/<id>/resolved.json`, and `ReportManager.load_structured_forecast`, which only returns a forecast sealed by the final audit's SHA-256 (`report_agent.py:11912-11923`). `_forecast_path` itself has no caller. |
| `GET /forecast/<report_id>` | `sdk.py:238-280` | Report missing → 404. `ReportManager.publication_status(id).publishable` false → **409** with the reasons. No sealed forecast → 409. Otherwise returns `{report_id, simulation_id, forecast, resolved}`, reading `resolved.json` best-effort. |
| `POST /resolve/<report_id>` | `sdk.py:283-356` | Same 404/409 gates. `outcome` is taken from the body (or from `outcomes`: first list item, or the scalar). Empty → 400. `backtest.score_forecast(forecast, outcome)` gives a multi-class Brier score and log-loss (`backtest.py:41`). Writes `{report_id, simulation_id, outcome, scoring, resolved_at, forecast}` atomically to `resolved.json`, **overwriting** any earlier resolution. Returns `{report_id, outcome, scoring}`. |

---

## Control flow

**Production boot** (`python backend/run.py`):
1. `run.py:21` import → `config.py:18-24` loads `.env` (override) → `class Config` evaluates every knob → `config.py:1647-1656` env `setdefault`s → `logger.py:136` creates the `mirofish` logger → `utils/__init__.py:5-6` imports `FileParser` and `LLMClient`. [verifier: the last two steps run in the other order. `from .utils.logger import ...` (`__init__.py:19`) first executes `utils/__init__.py`, which imports `file_parser` and then `llm_client`. `llm_client` imports `.logger` (utils/llm_client.py:23), and that import is when `logger.py:136` runs (utils/__init__.py:5-6)]
2. `run.py:28` `Config.validate()` → exit 1 on any error.
3. `run.py:37` `create_app()`:
   - `__init__.py:88-116` Flask, config, JSON, logger, CORS.
   - `__init__.py:128-129` `SimulationRunner.register_cleanup()`. It installs SIGINT/SIGTERM/SIGHUP handlers that call `cleanup_all_simulations()` and chain to the previous handlers, and registers it with `atexit` (`simulation_runner.py:2497-2579`). Under debug it registers only in the reloader child, but it detects debug as `FLASK_DEBUG=='1'` or `WERKZEUG_RUN_MAIN` being set (`simulation_runner.py:2510-2517`).
   - `__init__.py:131` `SimulationRunner.reconcile_orphans()`. If something already accepts TCP on `127.0.0.1:$FLASK_PORT` within 0.2 s, it skips everything (`simulation_runner.py:1531-1543`). Otherwise each `uploads/simulations/<id>/run_state.json` in RUNNING/STARTING/STOPPING/PAUSED has its process group killed and is marked FAILED, with `state.json` synced and `env_status.json` set to stopped (`simulation_runner.py:1544-1564`).
   - `__init__.py:139-140` `PipelineOrchestrator.reconcile_orphans()`. It does the same port probe (`pipeline_orchestrator.py:7656-7668`). For each pipeline whose state is `running` and that is not in this process's `_threads`: if the heartbeat shows the owner may be alive, it is skipped (`_orphan_is_dead`, `pipeline_orchestrator.py:7679-7684,7809-7840`); if a completed report and forecast exist on disk, it is salvaged as `completed (degraded)`; otherwise it is marked `failed`. In both the salvage and the failed case, orphaned `deerflow_research.py` process groups are killed after a PID and command-line check, and `TaskManager.complete_task`/`fail_task` is called. Salvage is at `pipeline_orchestrator.py:7689-7715` and fail at `:7716-7731`. Finally `_gc_stale_graphs()` runs `graph_builder ... gc_stale_graphs(retain=GRAPH_RETAIN_COUNT)` (`pipeline_orchestrator.py:7733,7773-7806`).
   - `__init__.py:141` `PipelineOrchestrator.register_cleanup()`. It registers `atexit(DeerFlowResearchRunner.cleanup_all)` and a signal handler that runs `cleanup_all` and then chains to the previous handler, usually the SimulationRunner one (`pipeline_orchestrator.py:7870-7917`; atexit at `:7888`, handler at `:7898-7908`).
   - `__init__.py:154-197` request hooks; `200-214` blueprints; `217-255` health and SPA routes.
4. `run.py:42` resolution autorun (no-op by default).
5. `run.py:57` `app.run(threaded=True)` binds the port.

**Per-request** (`/api/...`): `_auth_gate` (`__init__.py:155`) → `log_request` (`__init__.py:176`) → blueprint view → `log_response` (`__init__.py:184`, strips `traceback` outside DEBUG) → CORS headers (flask-cors).

**Provider switch** (`POST /api/settings/llm`): `settings.py:37` → `Config.apply_provider` (`config.py:920-942` validation) → `with _provider_lock` (`config.py:945`) → `resolve_endpoint` (`config.py:947`) → mutate class attributes (`config.py:948-963`) → `os.environ[k]=v` (`config.py:973-974`) → `_persist_env` (`config.py:975`) → `provider_info()`. Pipelines already running keep the values they captured (`settings.py:8-9`). New DeerFlow subprocesses inherit `os.environ`.

**Connectivity test** (`POST /api/settings/llm/test`): `settings.py:164-179` → `_test_cli_provider` (PATH plus `--version`) **or** `_test_openai_compat_provider` (SSRF check plus one 16-token completion). [verifier: without a key (the supplied one, or the saved `LLM_API_KEY` only when provider == current) it returns `ok:false` before any SSRF check or request (settings.py:79-80,175-177). The thinking-disable `extra_body` is sent only for providers in `_DISABLE_THINKING_EXTRA_BODY`; plain `openai` gets none (settings.py:108-110; config.py:817-823)]

**SDK run** (`POST /api/v1/run`): `sdk.py:94-125` validation → `preflight_pipeline` (`pipeline_orchestrator.py:6779`) → `PipelineOrchestrator.start` (`pipeline_orchestrator.py:7920`), which creates `pipe_<12hex>`, a `TaskManager` task of type `pipeline:<mode>`, and a background thread.

---

## Data & artifacts

| Path | Format | Writer / reader in slice | Key fields / notes |
|---|---|---|---|
| `<repo>/.env` | dotenv | Read at `config.py:21`; upserted by `_persist_env` (`config.py:979-1009`) | `LLM_PROVIDER`, `DEERFLOW_MODEL`, plus for OpenAI-compatible providers `LLM_BASE_URL`, `LLM_MODEL_NAME`, `LLM_API_KEY` and the provider's `key_env` (`config.py:956-971`). Rewritten through `mkstemp`, so the file ends with mode 0600 (`atomic.py:37,44`). |
| `backend/uploads/projects/<proj_id>/project.json` | JSON (indent 2, non-ASCII kept) | `ProjectManager.save_project` (`project.py:168-178`) / `get_project` (`project.py:181-199`) | `Project.to_dict` fields (`project.py:57-73`). |
| `backend/uploads/projects/<proj_id>/files/<8hex><ext>` | Uploaded binary | `save_file_to_project` (`project.py:245-276`) | Original name kept in the returned dict only. |
| `backend/uploads/projects/<proj_id>/extracted_text.txt` | UTF-8 text | `save_extracted_text` / `get_extracted_text` (`project.py:279-294`) | Non-atomic. The orchestrator stores the research report here (`pipeline_orchestrator.py:12320`). |
| `backend/uploads/reports/<report_id>/resolved.json` | JSON | `v1_resolve` (`sdk.py:334-344`); read by `v1_forecast` (`sdk.py:264-271`) | `report_id`, `simulation_id`, `outcome`, `scoring`, `resolved_at`, `forecast` snapshot. Otherwise only read manually through `backend/scripts/forecast_tools.py backtest resolved.json` (`forecast_tools.py:15`). |
| `backend/uploads/reports/<report_id>/forecast.json` | JSON | Read through `ReportManager.load_structured_forecast` (`sdk.py:233-235`) | Sealed by the final-audit SHA. |
| `backend/uploads/pipelines/<pipe_id>/pipeline_state.json`, `handoff/{research_report.md,actors.json,sources.json,timeline.json}` | JSON / MD | Read by v1 status, list and dossier (`sdk.py:164,180,193-210`) | Owned by the orchestrator slice. |
| `backend/logs/mirofish.log` (+ `.YYYY-MM-DD`, 30 kept) | text log | `setup_logger` (`logger.py:91-103`) | File level from `LOG_LEVEL` (default INFO). |
| `<tmp>/.tmp-*` siblings | temp | `write_text_atomic` (`atomic.py:37`) | Removed on failure (`atomic.py:45-50`). Orphans can remain after SIGKILL. |
| In memory: `TaskManager._tasks` | dict id→Task | `task.py:69` | Lost on restart. |
| In memory: `Config` class attributes | class state | `config.py:27+` | Mutated at runtime only by `apply_provider` (`config.py:948-963`). |

Derived directories defined in Config: `UPLOAD_FOLDER = backend/uploads` (`config.py:1048`), `OASIS_SIMULATION_DATA_DIR = backend/uploads/simulations` (`config.py:1080`), `PIPELINE_DATA_DIR = backend/uploads/pipelines` (`config.py:1581`), `GRAPHITI_DATA_DIR = backend/uploads/graphiti_db` (`config.py:1021-1024`), `EMBED_DISK_CACHE_PATH = GRAPHITI_DATA_DIR/embed_cache.sqlite` (`config.py:1253-1256`), `RESEARCH_MODEL_LEASE_DB = UPLOAD_FOLDER/research_model_leases.sqlite3` (`config.py:1216-1219`), `DEERFLOW_DIR = <repo>/deer-flow` (`config.py:1148-1151`). `FORECAST_LEDGER_DIR` is empty by default, meaning `PIPELINE_DATA_DIR/_forecast_ledger` per the comment at `config.py:278`.

---

## Config / env knobs

Conventions: **bool** means only `true` (case-insensitive) enables the flag. **int\*** means a bare `int()` without an `or` fallback, so a set-but-empty value raises at import. A default in the form `env:'x'` is the raw string default. The effect notes paraphrase the code comment next to each knob; they are not verified against the consumers unless a consumer anchor is given.

### Env vars read outside `Config`
| Name | Default | Effect | Anchor |
|---|---|---|---|
| `FLASK_HOST` | `127.0.0.1` | Bind host | `run.py:47` |
| `FLASK_PORT` | `5001` | Bind port (bare int). Also the port probed by both orphan reconcilers | `run.py:48`, `simulation_runner.py:1534`, `pipeline_orchestrator.py:7659` |
| `FRONTEND_DIST` | unset → `<repo>/frontend/dist` | SPA static folder | `__init__.py:29-33` |
| `DRF_TEST_PROCESS` | unset | `1` skips `.env` load and the lifecycle hooks | `config.py:18`, `__init__.py:124` |
| `WERKZEUG_RUN_MAIN` | unset | Reloader-child detection for startup logs | `__init__.py:100` |
| `LOG_LEVEL` | `INFO` | File handler level | `logger.py:101` |
| `PYTHONIOENCODING` | setdefault `utf-8` on win32 | Console encoding | `run.py:11` |
| `X-API-Token` (header) | — | Compared to `APP_API_TOKEN` for non-loopback requests | `__init__.py:169-171` |

### Flask / exposure / storage
| Name | Default | Effect | Anchor |
|---|---|---|---|
| `SECRET_KEY` | `mirofish-secret-key` | Flask secret. No session use found in `backend/app` (grep) | `config.py:31` |
| `DEBUG` (env `FLASK_DEBUG`) | False | `app.run(debug=)`; keeps tracebacks in JSON responses when true | `config.py:35`, `run.py:49`, `__init__.py:189` |
| `JSON_AS_ASCII` | False | Legacy key, ignored by Flask 3.1; the real switch is `app.json.ensure_ascii` | `config.py:38`, `__init__.py:93-94` |
| `APP_API_TOKEN` | `''` | Empty → non-loopback `/api/*` gets 403; set → `X-API-Token` required for non-loopback | `config.py:43`, `__init__.py:163-171` |
| `APP_CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000,http://localhost:5001,http://127.0.0.1:5001` | CORS allowlist for `/api/*`; `*` = any origin | `config.py:45-48`, `__init__.py:111-116` |
| `APP_BLOCK_PRIVATE_URLS` | False | `validate_safe_url(block_private=)` in `apply_provider` and the LLM test | `config.py:50`, `config.py:940`, `settings.py:85` |
| `_provider_lock` | `threading.Lock()` | Serializes `apply_provider` writers | `config.py:54`, `config.py:945` |
| `API_V1_ENABLED` | False | Mount `/api/v1` | `config.py:388`, `__init__.py:210` |
| `MAX_CONTENT_LENGTH` | 50 MiB (constant) | Flask request cap | `config.py:1047` |
| `UPLOAD_FOLDER` | `backend/uploads` (constant) | Root for projects and reports | `config.py:1048`, `project.py:105` |
| `ALLOWED_EXTENSIONS` | `{pdf,md,txt,markdown}` | Upload filter in `api/graph.py:25-30` | `config.py:1049` |
| `PIPELINE_DATA_DIR` | `backend/uploads/pipelines` (constant) | Pipeline root | `config.py:1581` |
| `OASIS_SIMULATION_DATA_DIR` | `backend/uploads/simulations` (constant) | Simulation root | `config.py:1080` |

### LLM provider, client and context budgeting
| Name | Default | Effect | Anchor |
|---|---|---|---|
| `LLM_PROVIDER` | `claude-cli` | One of the 8 `PROVIDER_META` keys | `config.py:750` |
| `LLM_API_KEY` | None | Key for OpenAI-compatible providers | `config.py:782` |
| `LLM_BASE_URL` | Provider default (kimi `https://api.kimi.com/coding/v1`, minimax `https://api.minimaxi.com/v1`, deepseek `https://api.deepseek.com/v1`, qwen `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`, glm `https://api.z.ai/api/paas/v4`, else `https://api.openai.com/v1`) | Endpoint | `config.py:753-790` |
| `LLM_MODEL_NAME` | Provider default (`kimi-k2.7`, `MiniMax-M3`, `deepseek-chat`, `qwen-plus`, `glm-4.6`, else `gpt-4o-mini`) | Model | `config.py:757-798` |
| `LLM_USER_AGENT` | `claude-cli/1.0.0` | UA header for the Kimi gateway | `config.py:803` |
| `LLM_KIMI_DISABLE_THINKING` / `LLM_MINIMAX_DISABLE_THINKING` / `LLM_DISABLE_THINKING` | true / true / true | Gate `reasoning_extra_body` | `config.py:810-813` |
| `PROVIDER_META` | dict of 8 | label, needs_key, deerflow_model, openai_compat, default_base/model, key_env, `native_tools:False` for minimax | `config.py:858-877` |
| `SUPPORTED_LLM_PROVIDERS` | `tuple(PROVIDER_META)` | Validation set | `config.py:1139` |
| `LLM_TELEMETRY_ENABLED` | True | LLM meter on | `config.py:58` |
| `LLM_CACHE_ENABLED` | True | In-process exact-key LRU cache | `config.py:62` |
| `LLM_RUN_BUDGET_TOKENS` / `LLM_RUN_BUDGET_USD` | 0 / 0 | Per-run cap (0 = unlimited) → BudgetExceeded | `config.py:64-65` |
| `LLM_OUTAGE_HALT_CONSECUTIVE` | 10 | Consecutive provider failures before the run halts (≤0 disables) | `config.py:69` |
| `LLM_COST_PER_MTOK` | `''` | JSON price overrides | `config.py:73` |
| `LLM_HTTP2` / `LLM_HTTP_KEEPALIVE` | True / 128 | httpx client tuning | `config.py:79-80` |
| `LLM_TIERED_ROUTING` | True | fast/strong tier routing | `config.py:92` |
| `LLM_FAST_MODEL` / `LLM_STRONG_MODEL` | None / None | Tier model names, falling back to `LLM_MODEL_NAME` | `config.py:96-97` |
| `LLM_FAST_PROVIDER` / `LLM_FAST_BASE_URL` / `LLM_FAST_API_KEY` | None | Separate fast-tier provider | `config.py:101-103` |
| `LLM_CLI_ISOLATE_HOOKS` | true | claude CLI child runs with hooks disabled | `config.py:506` |
| `REPORT_LLM_PREFLIGHT` | true | ~10-token probe before the report stage | `config.py:503` |
| `ADAPTIVE_CONTEXT` | True | Window-aware truncation | `config.py:118` |
| `RESERVED_COMPLETION_TOKENS` | 8192 | Window reserve | `config.py:120` |
| `CONTEXT_ITEM_MAX_TOKENS` | 4096 | Per-item cap. **No reader found** (grep) | `config.py:122` |
| `PERSONA_CONTEXT_FLOOR_CHARS` | 3000 | Persona context floor | `config.py:125` |
| `SIM_WORLD_BRIEF_MAX_CHARS` | 3000 | World brief ceiling | `config.py:128` |
| `PROVIDER_CONTEXT_WINDOWS` / `DEFAULT_CONTEXT_WINDOW` | dict / 32000 | `context_window_for` | `config.py:131-142` |

### Research stage (DeerFlow / v3)
| Name | Default | Anchor |
|---|---|---|
| `DEERFLOW_DIR` | `<repo>/deer-flow` | `config.py:1148` |
| `DEERFLOW_PYTHON` | None (auto-detect `.venv`, then `uv run`) | `config.py:1153` |
| `DEERFLOW_MODEL` | `claude`; switched by `apply_provider` | `config.py:1156`, `config.py:954` |
| `SUPPORTED_DEERFLOW_MODELS` | claude, codex, minimax, deepseek, qwen, glm, kimi, antigravity | `config.py:1544` |
| `DEERFLOW_KEY_ENV` | minimax/deepseek/qwen/glm/kimi → key env | `config.py:1546-1549` |
| `DEERFLOW_RESEARCH_DEPTH` | `deep` | `config.py:1159` |
| `DEERFLOW_RESEARCH_LANGUAGE` | None (auto) | `config.py:1163` |
| `DEERFLOW_RESEARCH_TIMEOUT` | 10800 (int\*) | `config.py:1165` |
| `DEERFLOW_DEPTH_BUDGETS` | quick 900 / standard 7200 / deep 21600 (×1.5 effective) | `config.py:1553`, `config.py:1569-1576` |
| `DEERFLOW_DEEP_OPENING_RECURSION_LIMIT` | 400 (int\*) | `config.py:1556` |
| `DEERFLOW_SUBAGENTS` | true | `config.py:1168` |
| `DEERFLOW_DUAL_TRACK` | True | `config.py:1228` |
| `RESEARCH_ENGINE` | `v3` (`linear` alias; `legacy`/`deerflow`/`agentic`) | `config.py:1187` |
| `RESEARCH_DEEP_FANOUT` / `RESEARCH_FANOUT_WIDTH` | true / 8 | `config.py:1172-1174` |
| `RESEARCH_PARALLEL_TRACKS` | 3 (≥1) | `config.py:1196` |
| `RESEARCH_GLOBAL_SYNTHESIS` | true | `config.py:1200` |
| `RESEARCH_GLOBAL_SUBAGENT_CAP` | 9 (≥1) | `config.py:1205` |
| `RESEARCH_SUBAGENTS_PER_TRACK_MAX` | 5 (clamped 1-8) | `config.py:1207` |
| `RESEARCH_GLOBAL_MODEL_CONCURRENCY` | 0 (= derived) | `config.py:1212` |
| `RESEARCH_MODEL_LEASE_DB` | `uploads/research_model_leases.sqlite3` | `config.py:1216` |
| `RESEARCH_QUALITY_GATE` / `RESEARCH_QUALITY_FLOOR` | False / 0.45 | `config.py:348-351` |
| `ACTOR_SYNTH_MIN_CONTEXT_CHARS` / `RESEARCH_MIN_REPORT_CHARS` | 3000 / 400 | `config.py:510-511` |
| `RESEARCH_FETCH_ACCOUNTING_V2`, `RESEARCH_QUALITY_GROUNDING` | true, true | `config.py:512,514` |
| `RESEARCH_ASOF_MAX_LAG_DAYS` | 45 | `config.py:513` |
| `ACTOR_DOSSIER_JUDGE_STRICT`, `RESEARCH_COVERAGE_GATE_STANDARD` | false, false | `config.py:515-516` |
| `RESEARCH_MCP_KG`, `RESEARCH_TRACK_RECONCILE` | true, true | `config.py:521,525` |
| `RESEARCH_BUDGET_ENABLED` / `_ATTEMPTS_GLOBAL` / `_SEARCH_GLOBAL` / `_SEARCH_LANE` / `_FETCH_GLOBAL` / `_FETCH_LANE` / `_MAX_EPOCHS` | true / 1800 / 900 / 360 / 450 / 180 / 3 | `config.py:528-544` |
| `RESEARCH_NEGATIVE_CACHE_TTL_SECONDS` / `_RETRIES` | 600 / 1 | `config.py:545-548` |
| `RESEARCH_COMPACT_MERGED_DOSSIER` / `ACTOR_DOSSIER_MAX_CHARS` | true / 80000 | `config.py:551-554` |
| `REPORT_LINT` (research dossier lint) | true | `config.py:558` |
| `EMBED_WARM_AT_RESEARCH` / `VALIDATE_AS_OF_DATE` | false / true | `config.py:476-477` |
| `RESEARCH_BAN_PROCESS_NARRATION`, `RESEARCH_INLINE_CITATIONS`, `RESEARCH_DEDUP_SHINGLES` | true each | `config.py:1453,1456,1460` |
| `RESEARCH_CITATION_INDEX_MAX` | 100 | `config.py:1458` |
| `RESEARCH_CHARTS_MIN` / `_TIMEOUT` / `_PYTHON` | 3 / 180 / `''` | `config.py:1464-1467` |
| `PREDICTION_MARKETS_ENABLED` | true | `config.py:1423` |
| `PREDICTION_MARKETS_MAX` | 20 (legacy alias `ODDPOOL_MAX_MARKETS`) | `config.py:1425` |
| `PREDICTION_MARKETS_MIN_VOLUME` / `_MAX_PER_EVENT` / `_PER_QUERY` / `_MIN_RELEVANCE` | 200 / 3 / 15 / 5 | `config.py:1428-1438` |
| `PREDICTION_MARKETS_REQUOTE` / `_HORIZON_RETRY` | true / true | `config.py:1443,1449` |
| `ACTOR_CAST_MAX` / `ACTOR_EXCLUDE_MEDIA` | 20 / true | `config.py:1362,1368` |

### Ontology / persona preparation
| Name | Default | Anchor |
|---|---|---|
| `ONTOLOGY_TEMPLATE` | `social_opinion` | `config.py:360` |
| `ONTOLOGY_AUTO_SELECT`, `ONTOLOGY_RICH_SCHEMA`, `CAST_RECONCILE`, `ONTOLOGY_FROM_DOSSIER`, `ONTOLOGY_SEED_ADAPTIVE_BUDGET` | true each | `config.py:364,368,372,379,561` |
| `PERSONA_EGO_RETRIEVAL` | False | `config.py:380` |
| `PERSONA_BEHAVIORAL_DNA`, `PROFILE_ZEP_SKIP_WHEN_CONTEXT`, `PERSONA_FIELD_EXTRACTION` | true each | `config.py:383,387,566` |
| `PARALLEL_PROFILE_COUNT` | 16 | `config.py:474` |
| `SIM_EVENT_REACT_BUFFER`, `SIM_SCHEDULE_CLAMP_ROUNDS`, `SIM_RULE_FALLBACK_STANCE`, `SIM_SEED_POST_VARIANTS` | true each | `config.py:562-565` |

### Graph stage (Graphiti / FalkorDB behind a Zep-compatible layer)
| Name | Default | Anchor |
|---|---|---|
| `GRAPH_BACKEND` | `auto` (validated: auto/falkordblite/falkordb/kuzu) | `config.py:1019`, `config.py:1611` |
| `GRAPHITI_DATA_DIR` | `backend/uploads/graphiti_db` | `config.py:1021` |
| `GRAPHITI_EMBED_MODEL` / `GRAPHITI_EMBED_DIM` | `paraphrase-multilingual-MiniLM-L12-v2` / 384 (int\*) | `config.py:1026-1027` |
| `GRAPHITI_RERANKER` | `rrf` | `config.py:1029` |
| `FALKORDB_HOST` / `FALKORDB_PORT` | None / 6379 (int\*) | `config.py:1031-1032` |
| `ZEP_API_KEY` | `local-graphiti` sentinel | `config.py:1038` |
| `ZEP_MAX_RETRIES` / `ZEP_RETRY_DELAY_SECONDS` / `ZEP_RATE_LIMIT_BUFFER_SECONDS` / `ZEP_RATE_LIMIT_MAX_SLEEP_SECONDS` | 2 / 2.0 / 1.0 / 90.0 (all bare parse) | `config.py:1041-1044` |
| `DEFAULT_CHUNK_SIZE` / `DEFAULT_CHUNK_OVERLAP` | 2500 / 250 | `config.py:1055-1057` |
| `GRAPH_SEARCH_RECIPE` | `rrf` | `config.py:347` |
| `GRAPH_CHUNK_SOURCE` | `dossier_only` | `config.py:481` |
| `GRAPH_CHOKEPOINT_PRIORS` / `GRAPH_CHOKEPOINT_MAX_NODES` | false / 1500 (try/except; ≤0 → 1500) | `config.py:569-575` |
| `GRAPH_PRIORS_ALIAS_FOLD` / `GRAPH_MAX_SKIPPED_RATIO` | true / 0.3 | `config.py:576-577` |
| `SIM_TIER_FROM_ONTOLOGY` | false | `config.py:578` |
| `GRAPH_QUERY_MAX_CHARS` / `GRAPH_QUERY_CLAMP_SEMANTIC` | 0 (auto) / true | `config.py:580-581` |
| `GRAPH_SEED_FROM_ACTORS` | true | `config.py:1236` |
| `GRAPH_BUILD_CONCURRENCY` | 4 (int\*) | `config.py:1240` |
| `GRAPHITI_MAX_COROUTINES` | 16 (exported to env) | `config.py:1244`, `config.py:1656` |
| `GRAPH_LLM_EXECUTOR_WORKERS` / `EMBED_EXECUTOR_WORKERS` | 64 / 4 | `config.py:1247-1250` |
| `EMBED_DISK_CACHE_PATH` | `GRAPHITI_DATA_DIR/embed_cache.sqlite` | `config.py:1253` |
| `GRAPH_MAX_NODES` | 8000 | `config.py:1259` |
| `GRAPH_BUILD_COMMUNITIES` | false (label propagation can loop forever) | `config.py:1266` |
| `GRAPH_CENTRALITY_PRIORS` | true | `config.py:1269` |
| `GRAPH_COMMUNITY_RETRIEVAL` | follows `GRAPH_BUILD_COMMUNITIES` unless set | `config.py:1273-1277` |
| `GRAPH_RESOLVE_ENTITIES` / `_SIM_THRESHOLD` / `_MAX_NODES` | true / 0.88 / 1200 | `config.py:1282-1289` |
| `GRAPH_COMPONENT_WARN_RATIO` | 0.2 | `config.py:1293` |
| `GRAPH_PRUNE_ENABLED` / `GRAPH_MAX_ENTITIES` / `GRAPH_CORE_ACTOR_HOPS` / `GRAPH_PRUNE_MIN_CORE_COVERAGE` / `GRAPH_PRUNE_MIN_DEGREE` (deprecated) / `GRAPH_MAX_ENTITIES_PER_TYPE` | true / 400 / 2 / 0.8 / 2 / 150 (the integers are int\*) | `config.py:1297-1311` |
| `GRAPH_UI_MAX_NODES` / `GRAPH_UI_CACHE_TTL_S` | 400 / 60 | `config.py:1313-1315` |
| `GRAPH_RETAIN_COUNT` | 5 (also drives startup GC) | `config.py:1318`, `pipeline_orchestrator.py:7781` |
| `GRAPH_LAYOUT_PRECOMPUTE` | true | `config.py:1321` |
| `GRAPH_EPISODE_SCHEMA_RETRIES` / `GRAPH_INGEST_FALLBACK` | 1 / true | `config.py:1324-1326` |
| `GRAPH_CAST_CHUNK_FILTER` / `GRAPH_CHUNK_MAX_ATTEMPTS` | true / 2 | `config.py:1335-1342` |
| `GRAPHITI_REMOTE` / `GRAPHITI_OP_TIMEOUT_S` | false / 900 | `config.py:1345-1350` |

### Simulation stage (OASIS)
| Name | Default | Anchor |
|---|---|---|
| `SIM_SEED` | 0 (random) | `config.py:296` |
| `SIM_EMERGENT_METRICS` / `IPC_TELEMETRY_ENABLED` | False / True | `config.py:356-358` |
| `SIM_START_HOUR` / `SIM_RECENCY_CARRY` / `SIM_TWITTER_MODEL_FREE_FEED` / `SIM_TOOL_ARG_NORMALIZE` | 0 / false / true / true | `config.py:584-587` |
| `SIM_IDLE_CLOSE_MIN` / `SIM_LLM_ERROR_RATE_THRESHOLD` | 60 / 0.5 | `config.py:588-589` |
| `SIM_RESUME` / `SIM_RESUME_REUSE_COMPLETED` / `SIM_CHECKPOINT` | false / true / true | `config.py:590-600` |
| `INTERVIEW_TIMEOUT_PER_AGENT` | 30 | `config.py:601` |
| `SIM_CLI_TOOL_EMULATION` / `SIM_LLM_FALLBACK` | true / true | `config.py:602-603` |
| `SIM_MIN_FREE_DISK_GB` / `SIM_STEP_FAILURE_LIMIT` | 2 / 3 | `config.py:604-605` |
| `SIM_ENGAGEMENT_SAMPLER` / `SIM_ENGAGEMENT_RATE` | `auto` / 0.3 | `config.py:612-613` |
| `SIM_REACTION_PHASE` / `SIM_REACTION_SHARE` | true / 1.0 | `config.py:617-618` |
| `SIM_OUTPUT_LANGUAGE` | `''` | `config.py:620` |
| `SIM_MAX_FOLLOWS_PER_AGENT_ROUND` | 3 | `config.py:623` |
| `SIM_ORGANIC_RATIO_DETECTOR` / `_MIN_CONSECUTIVE` | true / 3 | `config.py:626-627` |
| `OASIS_DEFAULT_MAX_ROUNDS` | 36 (int\*) | `config.py:1063` |
| `SIM_TEMPORAL_MODE` | `calendar` | `config.py:1067` |
| `SIM_CALENDAR_TARGET_MAX_ROUNDS` / `_HARD_MAX_ROUNDS` / `SIM_HORIZON_DEFAULT_MONTHS` | 36 / 48 / 12 | `config.py:1069-1073` |
| `SIM_WORLD_DELTA` / `SIM_DECISION_CHANNEL_INBAND` / `WORLDSTATE_ENTROPY_MIX` | true each | `config.py:1075-1079` |
| `OASIS_CLI_SEMAPHORE` / `OASIS_SEMAPHORE` | 8 / 24 (validated ≥1) | `config.py:1088-1091`, `config.py:1634-1637` |
| `OASIS_TWITTER_ACTIONS` / `OASIS_REDDIT_ACTIONS` | lists. **No reader found**; the sim script has its own lists | `config.py:1094-1101`, `backend/scripts/run_parallel_simulation.py:214` |
| `OASIS_MAX_AGENTS` | 80 (int\*) | `config.py:1354` |
| `SIM_AUDIENCE_AGENTS` | 0 (legacy alias `SIM_AUDIENCE_SIZE`) | `config.py:1372` |
| `SIM_ACTIVITY_PROFILE` | `china_social` | `config.py:1378` |
| `SIM_GRAPH_FEEDBACK` / `SIM_TYPED_FEEDBACK_EDGES` / `SIM_INTERVIEW_GRAPH_FEEDBACK` | false / false / false | `config.py:1385-1392` |
| `SIM_WIRE_RECSYS` | false | `config.py:1395` |
| `SIM_AGENT_DYNAMICS` | true | `config.py:1399` |
| `SIM_SYNTH_SEED_POSTS` / `_MAX` | true / 10 | `config.py:1405-1406` |
| `SIM_WORLD_BRIEF` / `SIM_PERSONA_DESIGN` / `SIM_MARKET_PRIORS` | true each | `config.py:1409,1413,1419` |
| `SIM_DYNAMICS_MOOD_LR` / `_OPINION_LR` / `_FATIGUE_RATE` / `_FATIGUE_DECAY` | 0.25 / 0.15 / 0.20 / 0.10 | `config.py:1473-1476` |
| `SIM_DECISION_CHANNEL` | true | `config.py:1483` |
| `SIMULATION_FORECAST_EFFECT` | `diagnostic_only` (allowlist: diagnostic_only, no_update, validated_update, legacy_prompt; other values → diagnostic_only) | `config.py:1492-1497` |
| `SIM_DECISION_INERTIA` | 0.7 | `config.py:1498` |
| `SIM_CONVERGENCE_STOP` | true. **No reader found** | `config.py:1502` |
| `SIM_CONVERGENCE_EPS` / `_WINDOW` | 0.02 / 3 | `config.py:1503-1504` |
| `SIM_RESUME_FROM_ROUND` | false. **No reader found** | `config.py:1507` |
| `SIM_TIER_ELIGIBILITY` / `SIM_SALIENCE_RANKING` / `SIM_VALENCED_RELATIONS` | True each | `config.py:1513-1519` |

### Report stage (report agent, forecast, visuals, translation)
| Name | Default | Anchor |
|---|---|---|
| `REPORT_STRUCTURED_FORECAST`, `REPORT_FORECAST_SPINE_FIRST`, `REPORT_FORECAST_SELF_CRITIQUE` | True each | `config.py:162,171,174` |
| `REPORT_PUBLISH_GATE` / `_MIN_COVERAGE` | True / 0.75 | `config.py:178-179` |
| `REPORT_MAX_CITATIONS_PER_SOURCE` | 20 | `config.py:184` |
| `REPORT_FINAL_READ_ONLY_AUDIT` / `REPORT_FINAL_AUDIT_POLICY_VERSION` | True / 3 (constant) | `config.py:190-195` |
| `REPORT_RESOLUTION_SECTION` | True | `config.py:199` |
| `REPORT_VISUALIZER`, `REPORT_VIZ_MERMAID`, `REPORT_VIZ_CHARTS` | True each | `config.py:203-208` |
| `REPORT_VIZ_DPI` / `REPORT_VIZ_MAX_NODES` | 160 / 40 | `config.py:210-212` |
| `REPORT_VIZ_INTERACTIVE` / `REPORT_VIZ_PNG_EXPORT` | True / True | `config.py:217-221` |
| `REPORT_VIZ_TIMELINE_MAX_EVENTS` / `REPORT_VIZ_NETWORK_MAX_NODES` | 40 / 60 | `config.py:223-225` |
| `REPORT_VISUALIZATIONS` | True | `config.py:230` |
| `REPORT_VIZ_INTERACTIVE_EMBED` / `REPORT_VIZ_MERMAID_ANNEX_ONLY` | True / True. **No reader found** | `config.py:235-239` |
| `REPORT_PDF_EXPORT` / `REPORT_PDF_TIMEOUT` | True / 180 | `config.py:244-246` |
| `REPORT_CITATION_SINGLE_GRAMMAR` / `REPORT_SOURCES_INDEX_MAX` | true / 60 | `config.py:251-253` |
| `REPORT_CITATION_FINALIZER`, `REPORT_CITATION_REPAIR`, `REPORT_TRANSLATION_CITATION_PARITY`, `REPORT_PDF_CITATION_FOOTNOTES` | true each | `config.py:257-266` |
| `REPORT_EXEC_BRIEF` | True | `config.py:273` |
| `REPORT_PROJECTED_EDGES` | False | `config.py:294` |
| `FORECAST_EMIT_BINARY` / `BINARY_FORECASTS_MIN_COUNT` | True / 10 (≥1) | `config.py:317-318` |
| `FORECAST_BINARY_REQUIRE_SHARP` | True. **No reader found** | `config.py:320` |
| `REPORT_TELEMETRY` / `REPORT_TELEMETRY_APPENDIX` | True / False | `config.py:390-395` |
| `REPORT_SIGNAL_PACK`, `REPORT_COMPARISON_TABLE`, `REPORT_CAUSAL_SPINE`, `REPORT_RELATIONAL_ROSTER`, `REPORT_EVIDENCE_BLOCKS` | True each | `config.py:398-414` |
| `REPORT_KEY_METRICS_MAX` | 40 | `config.py:415` |
| `REPORT_CONTESTED_TABLE_MAX` / `REPORT_CHRONOLOGY_MAX_EVENTS` | 15 / 25. **No reader found** | `config.py:416-417` |
| `REPORT_KG_STRUCTURAL_SPINE` / `REPORT_SCENARIO_SPINE_PIN` | True / True. **No reader found** | `config.py:421-425` |
| `REPORT_ABORT_ON_LLM_OUTAGE` | true | `config.py:630` |
| `REPORT_SECTION_RETRY_MAX` / `_BACKOFF_S` | 2 / 8.0 | `config.py:631-632` |
| `REPORT_CRITIQUE_BEFORE_PROSE`, `FORECAST_BINARY_CONTRARIAN`, `FORECAST_SIM_SENSITIVITY`, `FORECAST_HORIZON_CHECK` | true each | `config.py:633-637` |
| `FORECAST_BINARY_THEMES` | `''` | `config.py:636` |
| `REPORT_QUOTE_AUDIT_V2`, `REPORT_COMPACT_RETRIEVAL_QUERY`, `REPORT_REPAIR_PASSES`, `REPORT_LANGUAGE_PURITY`, `REPORT_SECTION_REFLECTION` | true each | `config.py:647-658` |
| `REPORT_EDITORIAL_LINT`, `REPORT_SIMLEAK_REPAIR`, `REPORT_OUTLINE_TITLE_LINT`, `REPORT_SIGNAL_PACK_QUALITATIVE`, `REPORT_SECTION_LANG_ENFORCE`, `REPORT_SECTION_TRUNCATION_CONTINUE` | true each | `config.py:664-696` |
| `REPORT_SIMLEAK_MAX_LLM_PARAGRAPHS` | 12 | `config.py:670` |
| `REPORT_SECTION_LANG_MAX_FOREIGN_RATIO` | 0.25 | `config.py:680` |
| `REPORT_PURITY_RETRANSLATE_SEGMENTS` / `REPORT_PURITY_ESCALATION_MAX` | 8 / 12 | `config.py:683-688` |
| `REPORT_REVISION_MIN_RATIO` / `REPORT_SECTION_MIN_VALID_RATIO` | 0.6 / 0.4 | `config.py:691-694` |
| `REPORT_BILINGUAL` / `REPORT_TRANSLATION_CONCURRENCY` | true / 4 (≥1) | `config.py:704-706` |
| `REPORT_TRANSLATION_RESIDUAL_LINES` / `_CALL_TIMEOUT_S` / `_RESIDUAL_LINE_RETRIES` | 3 / 240 / 12 (each ≥0) | `config.py:710-715` |
| `FORECAST_MARKET_ANCHORING` / `_ANCHOR_MIN_EQUIVALENCE` / `_DIVERGENCE_REVISION` / `_DIVERGENCE_MIN_CONFIDENCE` | true / `near` / true / 0.6 | `config.py:721-733` |
| `FORECAST_EXTRACT_BUDGET` / `FORECAST_BINARY_EXTRACT_BUDGET` / `FORECAST_EXTRACT_HEAD_RATIO` / `FORECAST_EXTRACT_MAX_TOKENS` | 40000 / 48000 / 0.6 / 4096 | `config.py:738-742` |
| `REPORT_AGENT_MAX_TOOL_CALLS` / `REPORT_AGENT_MIN_TOOL_CALLS` / `REPORT_AGENT_MAX_TOOL_CALLS_CHAT` | 12 / 4 / 2 (int\*) | `config.py:1107,1523-1524` |
| `REPORT_AGENT_MAX_REFLECTION_ROUNDS` | 2. **No reader**; `report_agent.py:1507` hard-codes `MAX_REFLECTION_ROUNDS = 3` | `config.py:1108` |
| `REPORT_AGENT_TEMPERATURE` | 0.5 (bare float) | `config.py:1109` |
| `REPORT_AGENT_SECTION_MAX_TOKENS` / `REPORT_AGENT_TOOL_TURN_MAX_TOKENS` | 32768 / 8192 | `config.py:1113-1116` |
| `REPORT_SECTION_TARGET_CHARS` / `REPORT_SECTION_FLOOR_CHARS` | `3000-6000` / 2000 | `config.py:1121-1122` |
| `REPORT_THREE_PART_SKELETON` | true | `config.py:1471` |
| `REPORT_NATIVE_TOOLS` / `REPORT_SECTION_CONCURRENCY` / `REPORT_SECTION_CONTEXT_MODE` | true / 6 / `brief` | `config.py:1528-1539` |

### Ensemble and calibration
| Name | Default | Anchor |
|---|---|---|
| `N_FORECAST_SEEDS` | 1 (≥1) | `config.py:303` |
| `ENSEMBLE_SEED_CONCURRENCY` | 2 (clamped 1-3) | `config.py:310` |
| `FORECAST_PROB_FLOOR` | 0.03 | `config.py:325` |
| `REPORT_SPINE_SELFCONSISTENCY_K` | 1 (≥1) | `config.py:329` |
| `ENSEMBLE_EXTREMIZE_A` | 1.0 | `config.py:333` |
| `ENSEMBLE_SEMANTIC_ALIGN` / `ENSEMBLE_ALIGN_MIN_OVERLAP` | true / 0.34 | `config.py:340-341` |
| `REPORT_SPINE_ANCHOR_WORLDSTATE` | true | `config.py:344` |
| `FORECAST_ENSEMBLE_MODELS` / `_SPREAD_THRESHOLD` | `''` / 0.15 | `config.py:643-646` |

### Pipeline orchestration and lifecycle
| Name | Default | Anchor |
|---|---|---|
| `PIPELINE_HEALTH_GATE` | True | `config.py:167` |
| `PIPELINE_STRICT_SCHEMA` | True | `config.py:352` |
| `PIPELINE_RUN_STALL_S` | 1800 | `config.py:355` |
| `PIPELINE_HEARTBEAT_ENABLED` / `_INTERVAL_S` / `_STALE_S` | true / 30 / 120 | `config.py:457-459` |
| `PIPELINE_STALE_S` / `PIPELINE_ETA_CAP_S` | 300 / 7200 | `config.py:461-462` |
| `PIPELINE_LIVE_ARTIFACTS` / `_PARTIAL_SCAN_EVERY_S` / `_VALIDATE_ARTIFACTS` / `_VIZ_ARTIFACTS` | true / 10 / true / true | `config.py:464-470` |
| `RECORD_RUN_MANIFEST` / `MANIFEST_CAPTURE_VERSIONS` | True / false | `config.py:426,472` |
| `PIPELINE_SALVAGE_COMPLETED_ORPHANS` | true | `config.py:486` |
| `PIPELINE_TELEMETRY_FLUSH_EVERY_CALLS` | 20 | `config.py:490` |
| `PIPELINE_RECLAIM_PORT_PROBE` / `SIMULATION_RECLAIM_PORT_PROBE` | true / true | `config.py:495-500` |

### Operations scripts, monitoring, evaluation
| Name | Default | Anchor |
|---|---|---|
| `REPORT_FORECAST_LEDGER` / `FORECAST_LEDGER_DIR` | True / `''` | `config.py:277-278` |
| `RESOLUTION_MONITOR_RECENT_N` / `_LOOKBACK_DAYS` / `_DRIFT_THRESHOLD` | 10 / 0 / 0.05 | `config.py:282-284` |
| `RESOLUTION_MONITOR_AUTORUN_HOURS` | 0 (off) | `config.py:290`, `resolution_autorun.py:97` |
| `EVAL_ENABLED` / `GOLDEN_EVAL_LEDGER` | False / False | `config.py:431-435` |
| `SCHEDULER_ENABLED` / `_TICK_SECONDS` / `_MAX_CONCURRENT` | False / 300 / 1 | `config.py:440-442` |
| `DRIFT_PROB_THRESHOLD` / `DRIFT_WEBHOOK_URL` | 0.15 / `''` | `config.py:444-445` |
| `BATCH_MAX_FANOUT` / `BATCH_SHARED_SIMULATION` | 8 / False | `config.py:447-448` |
| `MODEL_COMPARISON_ENABLED` | False | `config.py:389` |

---

## External calls

| Target | Kind | Anchor | Notes |
|---|---|---|---|
| OpenAI-compatible `/chat/completions` at a user-chosen `base_url` | HTTP LLM call | `settings.py:119` | Only from `POST /api/settings/llm/test`. `max_tokens=16`, timeout 25 s, `max_retries=0`. |
| DNS `socket.getaddrinfo(host)` | network | `security.py:136` | Every `validate_safe_url` call (`apply_provider` with a `base_url`, and the LLM test). |
| `claude --version` / `codex --version` | subprocess | `settings.py:68-70` | Timeout 10 s; PATH lookup via `shutil.which` (`settings.py:60`). |
| TCP connect `127.0.0.1:$FLASK_PORT` | socket probe | `simulation_runner.py:1538`, `pipeline_orchestrator.py:7663` | Called from `create_app`. 0.2 s timeout. |
| `os.killpg` / `os.kill` of orphan simulation and research process groups | OS signals | `simulation_runner.py:1501,1506` (via `_kill_orphan_simulation`, called at `:1553`), `pipeline_orchestrator.py:7864` | Startup reconcile. Research kills require `deerflow_research.py` and the pipeline id in `ps -o command=` output (`pipeline_orchestrator.py:7853-7863`). |
| `ps -p <pid> -o command=` | subprocess | `pipeline_orchestrator.py:7854` | Orphan PID verification. |
| Graph DB (FalkorDB / Graphiti) `gc_stale_graphs` | DB | `pipeline_orchestrator.py:7773-7806` (call at `:7795`) | Startup graph GC; can delete graphs. |
| `python backend/scripts/resolution_monitor.py run --all-recent` | subprocess | `resolution_autorun.py:43-48` | Only when autorun > 0. The script calls the keyless Polymarket Gamma API (`resolution_autorun.py:12`). |
| `PipelineOrchestrator.start` → DeerFlow subprocesses | thread + subprocess | `sdk.py:136` | Via `/api/v1/run`. |
| Filesystem `.env` write | file | `config.py:1007` | `apply_provider`. |

---

## Cross-module edges

**Into this slice (callers)**
- `create_app`: `backend/run.py:37`, plus 17 test modules under `backend/tests/` (grep count).
- `Config.validate`: only `backend/run.py:28`.
- `Config.apply_provider`: only `backend/app/api/settings.py:37`. Mentions in `pipeline_orchestrator.py:7237` and `scripts/model_comparison.py:115` are comments.
- `Config.reasoning_extra_body`: `utils/llm_client.py:893`, `utils/oasis_llm.py:591`.
- `Config.fast_model` / `strong_model`: `utils/llm_client.py:373-374`.
- `Config.context_window_for`: `report_agent.py:2361`, `oasis_profile_generator.py:1954`, `simulation_config_generator.py:1927`.
- `Config.deerflow_depth_budget`: `pipeline_orchestrator.py:2283,7318`.
- `Config.report_section_target_chars`: `report_agent.py` (referenced at 947 and 1729).
- `Config._is_placeholder`: `scripts/preflight.py:162`.
- `ProjectManager` / `ProjectStatus`: `api/graph.py`, `api/simulation.py`, `api/report.py`, `services/pipeline_orchestrator.py` (`create_project` at `:12318`, `save_project` at `:12324,12377,12729`).
- `TaskManager`: `api/graph.py:538,557`, `api/simulation.py:750` [verifier: the simulation.py instantiations are at :531 and :749, and graph.py also uses it at :364 (backend/app/api/simulation.py:531,749; backend/app/api/graph.py:364)], `api/report.py:249,520,991`, `services/pipeline_orchestrator.py` (`start` and `reconcile_orphans`), `services/graph_builder.py`, `scripts/batch_runs.py`.
- `write_json_atomic` / `write_text_atomic`: 20 modules (grep), among them `report_agent`, `pipeline_orchestrator`, `simulation_runner`, `simulation_manager`, `simulation_ipc`, `oasis_profile_generator`, `actor_context`, `zep_tools`, `exec_brief`, `utils/telemetry`, `api/simulation`, `scripts/run_parallel_simulation.py`, `scripts/resolution_monitor.py`, `scripts/batch_runs.py`, `scripts/scheduled_rerun.py`, `scripts/model_comparison.py`, `scripts/backfill_report_visuals.py`.
- `redact_secrets`: `__init__.py:181`, `pipeline_orchestrator.py:10383,10405`. [verifier: 10383 and 10405 are the import lines. The calls are at pipeline_orchestrator.py:10385,10411,10424]
- `validate_safe_url`: `config.py:940`, `settings.py:85`, `scripts/scheduled_rerun.py:516`, `scripts/preflight.py:218`.
- `get_logger`: 29 distinct logger names across `backend/app` and `backend/scripts`.
- Frontend: `frontend/src/api/settings.js:5,13,22` calls `GET/POST /api/settings/llm` and `POST /api/settings/llm/test` (45 s timeout). The frontend has no `/api/v1` callers and never sends `X-API-Token` (`frontend/src/api/index.js:4-23`).

**Out of this slice**
- `SimulationRunner.register_cleanup` / `reconcile_orphans` (`services/simulation_runner.py:2497`, `:1520`).
- `PipelineOrchestrator.reconcile_orphans` / `register_cleanup` / `start` (`services/pipeline_orchestrator.py:7637`, `:7870`, `:7920`); `PipelineManager.load` / `list_pipelines` / `handoff_dir` (`:1136`, `:1204`, `:884`); `preflight_pipeline` (`:6779`).
- `ReportManager.get_report` / `publication_status` / `load_structured_forecast` / `_get_report_folder` (`services/report_agent.py:14285`, `:12435`, `:11912`, `:11890`).
- `backtest.score_forecast` (`services/backtest.py:41`).
- `resolution_autorun.start` (`services/resolution_autorun.py:88`).
- `openai.OpenAI` (`settings.py:89,119`).

---

## Invariants, gates, validation

1. **Loopback trust is the default.** Non-loopback `/api/*` requests get 403 unless `APP_API_TOKEN` is set, and 401 unless the header matches (constant-time compare) (`__init__.py:161-171`). Forwarding headers can only remove loopback trust (`__init__.py:77-81,161`). `OPTIONS`, `/health` and every non-`/api/` path are always allowed (`__init__.py:156-160`).
2. **No tracebacks reach clients outside DEBUG.** A top-level `traceback` key is removed from every JSON response (`__init__.py:189-196`).
3. **`/api/*` unknown GETs never return HTML.** They get a JSON 404 from `_serve_spa` (`__init__.py:229-235`), but see Surprises for non-GET methods. [verifier: `backend/app` registers no `errorhandler` (grep). So Werkzeug/Flask HTML error pages also reach `/api` clients for a 413 above `MAX_CONTENT_LENGTH` (config.py:1047), for a 405 on a known route with the wrong method, and for any exception a view does not catch]
4. **Lifecycle hooks never run in tests.** `TESTING` or `DRF_TEST_PROCESS=1` disables reconcile, GC and signal handlers (`__init__.py:122-145`). Tests also skip `.env` (`config.py:18-19`).
5. **Single owner on startup.** Both reconcilers skip entirely if something answers on `127.0.0.1:$FLASK_PORT` (`simulation_runner.py:1531-1543`, `pipeline_orchestrator.py:7656-7668`). Pipelines with fresh heartbeats are kept (`pipeline_orchestrator.py:7679-7684`).
6. **`.env` writes are injection-safe and atomic.** Control characters are rejected (`security.py:78-79`), values are dotenv-quoted (`security.py:91-94`), and the file is written via tmp + replace (`config.py:994,1007`).
7. **SSRF guard on operator-supplied base URLs.** Link-local (cloud metadata), multicast, reserved and unspecified addresses are always rejected; loopback and private addresses are rejected only with `APP_BLOCK_PRIVATE_URLS` (`security.py:140-155`).
8. **Startup config validation** covers provider, key, graph backend, DeerFlow model and semaphores ≥ 1 (`config.py:1594-1638`).
9. **`SIMULATION_FORECAST_EFFECT` allowlist.** Unknown values fall back to `diagnostic_only` (`config.py:1492-1497`).
10. **Clamps:** `N_FORECAST_SEEDS ≥ 1` (`config.py:303`), `ENSEMBLE_SEED_CONCURRENCY ∈ [1,3]` (`config.py:310`), `RESEARCH_SUBAGENTS_PER_TRACK_MAX ∈ [1,8]` (`config.py:1207`), `GRAPH_CHOKEPOINT_MAX_NODES > 0` (`config.py:574-575`).
11. **SDK publication gate.** `/api/v1/forecast` and `/api/v1/resolve` return 409 unless `ReportManager.publication_status().publishable` is true and a sealed forecast exists (`sdk.py:250-262,302-315`).
12. **Implicit CSRF barrier.** Every JSON route reads `request.get_json(silent=True)`, which returns `None` for non-JSON content types, so a cross-site "simple" `text/plain` POST arrives with an empty body (`settings.py:33`, `sdk.py:93`). This is inferred from Flask semantics. [verifier: the empty-body part is right, but this is not a CSRF barrier for routes that act on an empty body. A browser on the same machine passes the loopback gate (`__init__.py:161`), and CORS does not stop simple requests. `POST /api/research/clean` with no body defaults to deleting every failed and cancelled pipeline (backend/app/api/research.py:287-300). `POST /api/research/resolution-monitor/run` (research.py:342-352) and `POST /api/research/<id>/cancel` (research.py:132-144) also need no body]

---

## Failure modes & recovery

| Failure | Behavior | Anchor |
|---|---|---|
| Bad config at boot | `run.py` prints the errors and exits 1 | `run.py:28-34` |
| Non-numeric value for an int knob | `ValueError` at import of `app.config`, so the backend cannot start. For the ~20 int\*/bare-float knobs (e.g. `OASIS_MAX_AGENTS`, `GRAPH_BUILD_CONCURRENCY`, `DEERFLOW_RESEARCH_TIMEOUT`, `ZEP_*`, `REPORT_AGENT_*`), even an **empty** value raises | `config.py:1027,1032,1041-1044,1063,1107-1109,1165,1240,1300-1311,1354,1523-1524,1556` |
| Port already in use | Both reconcilers skip; then `app.run` fails to bind | `simulation_runner.py:1538-1541`, `pipeline_orchestrator.py:7663-7666` |
| Reconcile or GC exception | Logged; startup continues | `simulation_runner.py:1563-1566`, `pipeline_orchestrator.py:7734-7735`, `:7803-7806` |
| `apply_provider` bad input | `ValueError` → HTTP 400 | `config.py:921-942`, `settings.py:45-46` |
| `.env` persist fails | Swallowed silently; in-memory and `os.environ` changes stay, API reports success | `config.py:1008-1009` |
| Provider test failure | HTTP 200 with `data.ok=false` and a mapped hint | `settings.py:120-136` |
| SIGINT/SIGTERM/SIGHUP | Pipeline handler kills DeerFlow research groups, chains to the simulation handler, which kills simulations and then the original handler or `SIG_DFL` re-raise | `pipeline_orchestrator.py:7898-7908`, `simulation_runner.py:2528-2561` |
| Normal exit | `atexit` runs `cleanup_all_simulations` and `DeerFlowResearchRunner.cleanup_all` | `simulation_runner.py:2564`, `pipeline_orchestrator.py:7888` |
| Atomic write interrupted | Tmp file unlinked; the original file stays intact | `atomic.py:45-50` |
| Corrupt `project.json` / unknown status | `get_project` raises; `list_projects` fails entirely | `project.py:196-199,80`, `project.py:215-218` |
| Backend restart | All `TaskManager` tasks lost; `update_task` on a stale id is a silent no-op | `task.py:69,128-130` |
| `/api/v1/*` exceptions | 500 with `str(e)` in `error` (traceback stripped) | `sdk.py:151-153` and similar |

---

## Surprises

1. **Doc drift: default bind host.** `ARCHITECTURE.md:120-121` says `run.py` "runs threaded on `0.0.0.0:5001`", and `ARCHITECTURE_MAP.md:581` lists `FLASK_HOST` default `0.0.0.0`. The code defaults to `127.0.0.1` (`run.py:47`). `.env.example:99` shows `# FLASK_HOST=0.0.0.0`.
2. **Doc drift: CORS and auth.** `ARCHITECTURE.md:122` says create_app "enables permissive CORS". The code restricts origins to an allowlist (`__init__.py:111-116`), and that doc paragraph does not mention the auth gate, orphan reconcile or SPA hosting.
3. **Doc drift: ensemble and decision-channel defaults.** `DRF_ARCHITECTURE.md:1683-1685` lists `N_FORECAST_SEEDS (3)`, `ENSEMBLE_EXTREMIZE_A (2.0)` and `SIM_DECISION_CHANNEL (off)`. The code has 1 (`config.py:303`), 1.0 (`config.py:333`) and true (`config.py:1483`).
4. **Comment drift: auth scope.** `config.py:41-42` and `.env.example:232` say that once a token is configured, all `/api/*` *mutation* requests need it. In the code (`__init__.py:155-172`), loopback requests never need the token, and non-loopback requests need it for **every** method, GET included.
5. **Stale run.py warning.** `run.py:50-54` warns that a non-loopback bind without a token leaves "all mutating endpoints open to the network without auth". The gate actually rejects those requests with 403 (`__init__.py:163-168`), so the warning describes the reverse of what happens.
6. **`.env` overrides the shell environment.** `load_dotenv(..., override=True)` (`config.py:21,24`) means `FLASK_PORT=5002 python run.py` is ignored if `.env` sets `FLASK_PORT`. Setting variables inline for one run does not work for keys present in `.env`.
7. **Path traversal in `ProjectManager` (suspected).** `ProjectManager` does no id validation (`project.py:113-115`), unlike `PipelineManager._validate_id` (`pipeline_orchestrator.py:868-872`). `DELETE /api/graph/project/<project_id>` (`api/graph.py:69-74`) passes the id to `delete_project`, which does `shutil.rmtree(PROJECTS_DIR/<id>)` (`project.py:236-241`). If a request delivers `project_id == '..'` (for example `%2e%2e` or `curl --path-as-is`), Werkzeug should decode it into the route value, and `rmtree` would delete the whole `backend/uploads/` tree. Not executed. Reachable from loopback by default.
8. **Project chunk defaults shadow Config defaults.** `Project.chunk_size/overlap` default to 500/50 (`project.py:49-50,95-96`). `api/graph.py:340-341` uses `project.chunk_size or Config.DEFAULT_CHUNK_SIZE`, so the 2500/250 Config defaults (`config.py:1055-1057`) are never used on the legacy `/api/graph/build` path unless the request overrides them. The orchestrator path uses Config directly (`pipeline_orchestrator.py:1325-1326`).
9. **Shared log file with many handlers (suspected).** `get_logger` gives each of the 29 distinct names its own `TimedRotatingFileHandler` on the same `backend/logs/mirofish.log` (`logger.py:91-114,129-131`). On CPython 3.12.6 (the `backend/.venv` interpreter), `doRollover` returns early when the dated file already exists. After the first midnight, every handler except the one that rotated therefore keeps writing into yesterday's dated file and re-checks rollover on every record. Inferred from the stdlib source, not observed.
10. **Dead Config knobs.** No reader was found by grep in `backend/app`, `backend/scripts` or `deerflow_bridge` (`*.py`) for: `SIM_CONVERGENCE_STOP` (`config.py:1502`), `SIM_RESUME_FROM_ROUND` (`:1507`), `REPORT_AGENT_MAX_REFLECTION_ROUNDS` (`:1108`; `report_agent.py:1507` hard-codes 3), `FORECAST_BINARY_REQUIRE_SHARP` (`:320`), `REPORT_VIZ_INTERACTIVE_EMBED` (`:235`), `REPORT_VIZ_MERMAID_ANNEX_ONLY` (`:239`), `REPORT_CONTESTED_TABLE_MAX` (`:416`), `REPORT_CHRONOLOGY_MAX_EVENTS` (`:417`), `REPORT_KG_STRUCTURAL_SPINE` (`:421`), `REPORT_SCENARIO_SPINE_PIN` (`:425`), `CONTEXT_ITEM_MAX_TOKENS` (`:122`), `OASIS_TWITTER_ACTIONS` / `OASIS_REDDIT_ACTIONS` (`:1094-1101`). Setting these in `.env` has no effect. `kimi_extra_body()` (`config.py:846-848`) has no callers. `JSON_AS_ASCII` (`config.py:38`) is ignored by Flask 3.1.
11. **Provider lock only covers writers (suspected).** `_provider_lock` (`config.py:54,945`) serializes `apply_provider` calls, but readers such as `LLMClient` construction read `Config.LLM_PROVIDER`, `LLM_BASE_URL` and the others without the lock. A reader can see a torn pair (new provider, old base URL) between `config.py:948` and `config.py:958`. The comment at `config.py:52-53` says the lock prevents races with pipelines that are reading configuration.
12. **Provider switch quirks.**
    - `.env` persist failures are swallowed while the API reports success (`config.py:1008-1009`).
    - Switching to a CLI provider keeps the previous provider's `LLM_API_KEY` in memory. Switching back then demands a key again, because `keeps_existing_key` requires `provider == LLM_PROVIDER` (`config.py:926-928`).
    - Choosing `openai` sets the research model to `claude` (`config.py:861`).
13. **`/api/v1` drift from the SPA routes.**
    - `v1_dossier` uses the static `handoff_dir` (`sdk.py:193`), while `/api/research/<id>/dossier` uses `resolve_handoff_dir` (`api/research.py:392`). Fork pipelines therefore get an empty dossier through v1.
    - v1 `/run` does not accept the `research_language` alias that `/api/research/run` does (`api/research.py:86` vs `sdk.py:113`).
    - v1 `/status` omits the `live` block and the no-store headers (`api/research.py:314-334`).
    - `import traceback` (`sdk.py:39`) is unused.
    - The documented SDK client `sdk/deepagentforecast/client.py` (`sdk.py:32-34`) does not exist in the repo (find).
14. **Schema-version sentinel not mapped to 409.** `PipelineManager.load` returns an "incompatible schema" sentinel and its comment says the API maps it to 409 (`pipeline_orchestrator.py:922-926,1152-1163`). `/api/v1/status` returns it with HTTP 200 (`sdk.py:164-167`); so does `/api/research/status`.
15. **Port probe under the debug reloader (suspected).** With `FLASK_DEBUG=true`, Werkzeug 3.1.4 binds and listens in the reloader parent before it spawns the child (`werkzeug/serving.py:1088-1115` in `backend/.venv`). The child's `create_app` therefore sees the port answering and skips both reconcilers. After a code-change reload, pipelines orphaned by the killed child are not reconciled until a full restart. Separately, `register_cleanup` detects debug mode with `FLASK_DEBUG=='1'` (`simulation_runner.py:2512`, `pipeline_orchestrator.py:7882`), while `Config.DEBUG` uses `'true'` (`config.py:35`), so with `FLASK_DEBUG=true` the reloader parent also installs signal handlers.
16. **Stale task callbacks on restart.** `TaskManager` is in memory only (`task.py:60-71`), so the `fail_task`/`complete_task` calls in `PipelineOrchestrator.reconcile_orphans` (`pipeline_orchestrator.py:7706-7714,7727-7731`) always target ids that no longer exist after a restart, and silently do nothing (`task.py:129-130`). `cleanup_old_tasks` is never called, so tasks accumulate without bound.
17. **Non-atomic writes remain.** `save_project`'s docstring says the earlier project write was the only non-atomic write in the codebase (`project.py:169-173`), yet `save_extracted_text` in the same class is still a plain `open('w')` (`project.py:279-283`).
18. **Atomic writer output quirks.** `write_json_atomic` defaults to `allow_nan=True` and `default=str` (`atomic.py:60,73-74`). NaN or Infinity would be written as bare `NaN`, which `JSON.parse` rejects, and non-serializable objects are silently stringified. Files created through `mkstemp` keep mode 0600 after `os.replace` (`atomic.py:37,44`); that is POSIX `mkstemp` behavior and applies to every atomically written artifact, including `.env`.
19. **Over-broad redaction.** `_SECRET_KEY_RE` matches any key containing `token` (`security.py:21-22`), so request-log fields such as `max_tokens` or `prompt_tokens` are masked as secrets.
20. **DNS check is check-then-use (suspected).** `validate_safe_url` resolves the host once (`security.py:136`); the HTTP client resolves it again later (`settings.py:119`). The docstring says this defends against DNS rebinding (`security.py:133-134`), but there is a time-of-check/time-of-use gap.
21. **DNS rebinding against the loopback trust (suspected).** There is no Host-header allowlist anywhere in `create_app` (`__init__.py:84-260`). A browser page on an attacker domain rebound to 127.0.0.1 would arrive with `remote_addr` loopback and pass the gate (`__init__.py:161-162`).
22. **Non-ASCII token header (suspected).** `hmac.compare_digest` raises `TypeError` for non-ASCII `str` (`__init__.py:170`). A non-ASCII `X-API-Token` value (headers are decoded as latin-1) would produce a 500 instead of a 401.
23. **Unknown non-GET `/api/*` paths (suspected).** The SPA catch-all reuses Flask's GET-only `static` rule (`__init__.py:254`). A POST to an unknown `/api/foo` should match that rule's path with a disallowed method and produce Werkzeug's HTML 405, contradicting the "`/api/*` never returns HTML" comment (`__init__.py:224`).
24. **Eager imports.** `utils/__init__.py:5-6` and `services/__init__.py:5-38` import heavy modules as a side effect of importing any submodule. A script that imports only `app.utils.atomic` still loads `llm_client` and triggers `app.config`'s `.env` load (`utils/llm_client.py:22`).
25. **Mislabelled startup delay.** The resolution-autorun log line always says the first-run delay is 60 s (`resolution_autorun.py:116`), even when the caller passes a different `initial_delay_s` (`resolution_autorun.py:88-89`).
26. **LAN UI cannot authenticate.** The frontend never sends `X-API-Token` (`frontend/src/api/index.js:4-23`). When Vite is exposed with `FRONTEND_HOST`, every API call from a LAN browser therefore fails: `xfwd` marks it non-loopback (`frontend/vite.config.js:24-30`) and the gate returns 403 or 401.

---

## Verification

Adversarial pass on 2026-10-11 against the `main` checkout on disk. The pass was read-only apart from this file. Nothing was executed except greps, `sed`/`awk` reads, and an AST walk of `config.py`. The stdlib `logging/handlers.py` of the `backend/.venv` interpreter (CPython 3.12.6) and Werkzeug 3.1.4's `serving.py` were also read.

### Verdict counts

| Set | Checked | Confirmed | Imprecise | Refuted | Unverifiable |
|---|---|---|---|---|---|
| Key claims | 15 | 13 | 2 | 0 | 0 |
| Surprises | 16 | 16 | 0 | 0 | 0 |
| Extra spot-checks (Walkthrough, Control flow, Invariants, Cross-module) | 18 | 11 | 6 | 1 | 0 |
| **Total** | **49** | **40** | **8** | **1** | **0** |

The two suspected items rest on reading the code rather than on a run. The path traversal (Surprise 7) and the logging rollover (Surprise 9) are both consistent with the code; the rollover was checked against the stdlib source at `cpython-3.12.6/lib/python3.12/logging/handlers.py:439-441`.

### Non-confirmed statements, with corrections

1. **Refuted. `GRAPHITI_MAX_COROUTINES` default "8" in runtime.py** (Walkthrough, config module level). `runtime.py` now defaults to `"16"`, with a `ValueError` fallback to 16 (`backend/app/services/graphiti_client/runtime.py:396-398`). The "8" comes from the stale comment at `config.py:1652-1653`, so for the default value the `setdefault` at `config.py:1656` is redundant.
2. **Imprecise. Key claim: `/api/settings/llm/test` sends one completion with thinking disabled.** Without a key, the test returns `ok:false` before any SSRF check or HTTP call. The key is the one supplied, or the saved `LLM_API_KEY` only when provider == current (`settings.py:79-80,175-177`). The thinking-disable `extra_body` is sent only for kimi, minimax, deepseek, glm and qwen. Plain `openai` gets none (`settings.py:108-110`; `config.py:817-823`). Everything else in the claim is correct: no persistence, the 25 s timeout, `max_retries=0`, the CLI `--version` path with its 10 s timeout, and HTTP 200 with `data.ok`.
3. **Imprecise. Key claim: the effective deep budget is 32400 s.** That is the value `deerflow_depth_budget('deep')` returns (`config.py:1553,1569-1575`). The research watchdog uses an explicit `timeout` first, then `DEERFLOW_RESEARCH_TIMEOUT` whenever that variable is non-blank in `os.environ`, and only then the method (`pipeline_orchestrator.py:2278-2283`). The run-manifest snapshot always records the method value (`pipeline_orchestrator.py:7318`), so it can disagree with the watchdog when the env override is set.
4. **Imprecise. Control flow, boot step 1, import order.** `utils/__init__.py` runs before `logger.py:136`. `from .utils.logger import ...` (`__init__.py:19`) executes the package `__init__` first, which imports `file_parser` and then `llm_client`. `llm_client` imports `.logger` (`utils/llm_client.py:23`), and only then does `logger.py:136` run.
5. **Imprecise. Wrong anchor: `api/research.py:41-44`.** The duplicated `_VALID_*` sets are at `backend/app/api/research.py:40-43`.
6. **Imprecise. Wrong anchor: `TaskManager` at `api/simulation.py:750`.** The instantiations are at `api/simulation.py:531,749`, and there is another at `api/graph.py:364`.
7. **Imprecise. Wrong anchors: `redact_secrets` at `pipeline_orchestrator.py:10383,10405`.** Those are the import lines. The calls are at `:10385,10411,10424`.
8. **Imprecise. Invariant 3, "`/api/*` unknown GETs never return HTML".** This is true for unknown GETs. But `backend/app` registers no `errorhandler` (grep), so `/api` clients also get Werkzeug HTML for a 413 over `MAX_CONTENT_LENGTH` (`config.py:1047`), for a 405 on a known route with the wrong method, and for any exception a view does not catch.
9. **Imprecise. Invariant 12, "Implicit CSRF barrier".** The empty-body mechanism is real (`settings.py:33`, `sdk.py:93`), but it is no barrier for routes that act without a body. A malicious page in a browser on the same machine passes the loopback gate (`__init__.py:161`), and CORS does not block simple requests. `POST /api/research/clean` with an empty body defaults to deleting every failed and cancelled pipeline (`backend/app/api/research.py:287-300`). `POST /api/research/resolution-monitor/run` (`research.py:342-352`) and `POST /api/research/<id>/cancel` (`research.py:132-144`) also need no body.

Minor nuance on the Boolean-knob claim (key claim 6, still confirmed): `DEBUG` parses `FLASK_DEBUG` with `.lower()` but no `.strip()` (`config.py:35`). Every other `== 'true'` comparison in `config.py` (165 lines) applies `.strip().lower()` first.

### Spot-checks that held (selection)

- `backend/tests/conftest.py:19` sets `DRF_TEST_PROCESS=1`.
- There are exactly 29 distinct `get_logger`/`setup_logger` names in `backend/app` and `backend/scripts`.
- 20 modules in `backend/app` and `backend/scripts` import the atomic writers. A 21st, `deerflow_bridge/research_budget.py`, is outside those two directories.
- `services/__init__.py:5-38` imports ten modules.
- The `context_window_for` callers are at `report_agent.py:2361`, `oasis_profile_generator.py:1954` and `simulation_config_generator.py:1927`.
- `PipelineOrchestrator.start` mints `pipe_<12hex>` and a task of type `pipeline:<mode>` (`pipeline_orchestrator.py:7932,7936-7937`).
- The ONTOLOGY stage creates the project and stores the report in `extracted_text.txt` (`pipeline_orchestrator.py:12318-12324`).
- `Config.validate` has a single caller, `run.py:28`.
- 17 test modules reference `create_app`.
- The `Config` class has 398 distinct attributes and 13 methods (AST), consistent with the map's "about 399".
- The dead knobs have no reader outside `config.py`, `.env.example` and one defaults test.

### Omissions (significant behavior the map does not state)

1. **A provider switch can revert on restart.** `_persist_env` rewrites only the first matching `KEY=` line and leaves any later duplicate of the same key in place (`config.py:997-1006`). On the next import, `load_dotenv(override=True)` lets the later duplicate win (`config.py:21`), so the persisted provider or key silently reverts.
2. **`log_response` parses every JSON response.** It calls `response.get_json(silent=True)` on every JSON response outside DEBUG, not only on error responses, so large payloads are re-parsed on each request (`__init__.py:189-191`). It re-serializes only when a top-level `traceback` key exists.
3. **The startup port probe checks only `127.0.0.1`.** A live backend bound to `::1`, which `run.py` accepts as a loopback host (`run.py:50`), or to a specific LAN IP is not detected. A second backend would then run the destructive orphan kill and graph GC before failing to bind (`simulation_runner.py:1538`; `pipeline_orchestrator.py:7663`).
4. **The probe's early return also skips startup graph GC.** GC runs only at the end of `PipelineOrchestrator.reconcile_orphans`, inside the same `try`, after the probe (`pipeline_orchestrator.py:7656-7666,7733`).
5. **Debug mode runs `main()` twice.** With `FLASK_DEBUG=true`, `main()` runs in both the reloader parent and the child (`run.py:37-42,57`; Werkzeug `serving.py:1088-1115`):
   - The parent's `create_app` performs the initial reconcile and GC while the port is still free.
   - When `RESOLUTION_MONITOR_AUTORUN_HOURS>0`, two autorun schedulers start. In-flight de-duplication is per process (`resolution_autorun.py:29-30,63-69,88-117`).
6. **`create_app(config_class)` reads several settings from the global `Config`.** CORS origins, `APP_API_TOKEN` and `API_V1_ENABLED` come from the global class, not from `config_class` (`__init__.py:111,163,210`). A custom config class therefore changes only `app.config` (DEBUG, TESTING, MAX_CONTENT_LENGTH and the like).
7. **`/api/v1/resolve` persists any outcome.** It writes `resolved.json` even when the outcome matches no scenario, or when the forecast has no scenarios and scoring is `{"error":"no scenarios",...}`, and it overwrites any earlier resolution (`sdk.py:331-344`; `backtest.py:48-50`).
8. **More doc drift.** `DRF_ARCHITECTURE.md:1684` lists `REPORT_SPINE_SELFCONSISTENCY_K (5)`; the code default is 1 (`config.py:329`). `DRF_ARCHITECTURE.md:1189` says "default 5" as well.
9. **The runtime default comment in `config.py` is stale.** `config.py:1652-1653` still says `runtime.py` defaults `GRAPHITI_MAX_COROUTINES` to 8; the code reads 16 (`graphiti_client/runtime.py:396`).
