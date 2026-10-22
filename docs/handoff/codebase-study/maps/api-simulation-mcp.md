# api-simulation-mcp — Simulation HTTP API and MCP servers

Slice files (every line read):

| File | Lines | Role |
|---|---|---|
| `backend/app/api/simulation.py` | 2871 | Flask blueprint `simulation_bp`: 32 HTTP routes for entity reads, simulation lifecycle (create → prepare → start/stop → close-env), live monitoring, SQLite feed reads, interviews |
| `backend/app/mcp/__init__.py` | 24 | Package docstring + `__all__ = ["kg_server", "sim_server"]` |
| `backend/app/mcp/kg_server.py` | 358 | stdio FastMCP server `drf-kg`: 6 knowledge-graph tools wrapping `ZepToolsService` |
| `backend/app/mcp/sim_server.py` | 312 | stdio FastMCP server `drf-simulation`: 3 simulation tools wrapping `SimulationRunner` |

Branch studied: `main` checkout on disk. Line anchors are `path:line` relative to the repo root.

---

## Purpose & position in the pipeline

- **HTTP API.** `simulation.py` is the "Step 2/Step 3" HTTP surface inherited from MiroFish (`backend/app/api/simulation.py:1-3`). It is mounted at `/api/simulation` (`backend/app/__init__.py:202`; blueprint object `backend/app/api/__init__.py:8`, module import `backend/app/api/__init__.py:15`). The handlers are thin. They validate JSON or query input and then delegate to `SimulationManager` (state.json, profile and config preparation), `SimulationRunner` (OASIS subprocess, run_state.json, actions.jsonl, file IPC interviews), `ZepEntityReader` (graph entities) and `OasisProfileGenerator` (LLM personas). The handlers return `{"success": bool, "data"|"error": ...}` envelopes.
- **In-repo callers.** The automated pipeline (`pipeline_orchestrator.py`) does **not** call these HTTP routes. It drives `SimulationManager` and `SimulationRunner` directly. A grep for importers of `app.api.simulation` finds only `backend/tests/test_simulation_trajectory_api.py:96`. The Vue SPA uses only 5 of the routes (see Cross-module edges).
- **MCP servers.** `kg_server.py` and `sim_server.py` expose the knowledge graph and the simulation to the **DeerFlow 2.0 harness** (the research subprocess) as stdio MCP servers. They use the official `mcp` SDK's `FastMCP` (`backend/app/mcp/__init__.py:1-22`). They are registered in `deerflow_bridge/extensions_config.json:3-38`. The orchestrator renders and deploys that file into `deer-flow/` (`backend/app/services/pipeline_orchestrator.py:1379-1407, 1556-1578`). The orchestrator points the research subprocess at it only on runs where a graph already exists (fork/continue/resume), via `DEER_FLOW_EXTENSIONS_CONFIG_PATH` + `DRF_MCP_KG_GRAPH_ID` (`backend/app/services/pipeline_orchestrator.py:2414-2423`). See Surprises S-1 for evidence that deer-flow may discover the file without that env var.
- **Shared design rule for both MCP servers** (`backend/app/mcp/__init__.py:12-18`):
  - Startup and `tools/list` never touch FalkorDB, Graphiti or the simulation IPC.
  - Heavy imports are lazy. [verifier: imprecise. `python -m app.mcp.*` first imports the `app` package, and its `__init__` imports Flask, flask_cors and `Config` at process start; importing `Config` runs `load_dotenv(override=True)`. Only `app.services.*` (FalkorDB, Graphiti, IPC) is lazy (backend/app/__init__.py:15-18; backend/app/config.py:12-24)]
  - Every tool returns structured `{"ok": False, "error": ...}` instead of raising.
  - Each tool is bounded by `asyncio.wait_for`.

---

## Route catalog (all 32 routes; prefix `/api/simulation`)

| # | Method | Path | Handler (`backend/app/api/simulation.py:`) | Services called | Threads / subprocesses | Frontend caller |
|---|---|---|---|---|---|---|
| 1 | GET | `/entities/<graph_id>` | `get_graph_entities` :47-89 | `ZepEntityReader().filter_defined_entities` | — | none |
| 2 | GET | `/entities/<graph_id>/<entity_uuid>` | `get_entity_detail` :92-122 | `ZepEntityReader().get_entity_with_context` | — | none |
| 3 | GET | `/entities/<graph_id>/by-type/<entity_type>` | `get_entities_by_type` :125-159 | `ZepEntityReader().get_entities_by_type` | — | none |
| 4 | POST | `/create` | `create_simulation` :164-236 | `ProjectManager.get_project`, `SimulationManager().create_simulation` | — | wrapper only (`frontend/src/api/simulation.js:11`) |
| 5 | POST | `/prepare` | `prepare_simulation` :399-675 | `_check_simulation_prepared`, `SimulationManager.get_simulation/_save_simulation_state/prepare_simulation`, `ProjectManager.get_project/get_extracted_text`, `ZepEntityReader.filter_defined_entities`, `TaskManager` | **daemon `threading.Thread(target=run_prepare)`** :647-648 | wrapper only (:19) |
| 6 | POST | `/prepare/status` | `get_prepare_status` :678-788 | `_check_simulation_prepared`, `TaskManager.get_task` | — | wrapper only (:27) |
| 7 | GET | `/<simulation_id>` | `get_simulation` :791-821 | `SimulationManager.get_simulation/get_run_instructions` | — | wrapper only (:35) |
| 8 | GET | `/list` | `list_simulations` :824-850 | `SimulationManager.list_simulations` | — | wrapper only (:79) |
| 9 | GET | `/history` | `get_simulation_history` :912-1023 | `SimulationManager.list_simulations/get_simulation_config`, `SimulationRunner.get_run_state`, `ProjectManager.get_project`, `_get_report_id_for_simulation` | — | wrapper only (:201) |
| 10 | GET | `/<simulation_id>/profiles` | `get_simulation_profiles` :1026-1061 | `SimulationManager.get_profiles` | — | wrapper only (:44) |
| 11 | GET | `/<simulation_id>/profiles/realtime` | `get_simulation_profiles_realtime` :1064-1171 | direct file reads | — | **used** (`SimulationView.vue:514`) |
| 12 | GET | `/<simulation_id>/config/realtime` | `get_simulation_config_realtime` :1174-1291 | direct file reads | — | wrapper only (:70) |
| 13 | GET | `/<simulation_id>/config` | `get_simulation_config` :1294-1327 | `SimulationManager.get_simulation_config` | — | wrapper only (:61) |
| 14 | GET | `/<simulation_id>/config/download` | `download_simulation_config` :1330-1356 | `SimulationManager._get_simulation_dir`, `flask.send_file` | — | none |
| 15 | GET | `/script/<script_name>/download` | `download_simulation_script` :1359-1408 | `flask.send_file` | — | none |
| 16 | POST | `/generate-profiles` | `generate_profiles` :1413-1482 | `ZepEntityReader.filter_defined_entities`, `OasisProfileGenerator().generate_profiles_from_entities` (**synchronous LLM**) | generator-internal parallelism only | none |
| 17 | POST | `/start` | `start_simulation` :1487-1682 | `SimulationManager`, `_check_simulation_prepared`, `SimulationRunner.get_run_state/stop_simulation/cleanup_simulation_logs/start_simulation`, `ProjectManager.get_project` | **`subprocess.Popen` of `backend/scripts/run_*_simulation.py` + daemon monitor thread**, both inside `SimulationRunner.start_simulation` (`backend/app/services/simulation_runner.py:943-978`) | wrapper only (:87) |
| 18 | POST | `/stop` | `stop_simulation` :1685-1741 | `SimulationRunner.stop_simulation`, `SimulationManager._save_simulation_state` | kills the process group (`simulation_runner.py:1680-1704`) | wrapper only (:95) |
| 19 | GET | `/<simulation_id>/run-status` | `get_run_status` :1746-1801 | `SimulationRunner.get_run_state` | — | **used** (`SimulationView.vue:518`) |
| 20 | GET | `/<simulation_id>/run-status/detail` | `get_run_status_detail` :1804-1901 | `SimulationRunner.get_run_state/get_all_actions` | — | wrapper only (:111) |
| 21 | GET | `/<simulation_id>/actions` | `get_simulation_actions` :1904-1955 | `SimulationRunner.get_actions` | — | wrapper only (:168) |
| 22 | GET | `/<simulation_id>/timeline` | `get_simulation_timeline` :1958-1995 | `SimulationRunner.get_timeline` | — | wrapper only (:151) |
| 23 | GET | `/<simulation_id>/trajectory` | `get_simulation_trajectory` :2006-2101 | direct file read | — | **none** (no `trajectory` reference in `frontend/src` apart from an i18n label at `frontend/src/utils/vizManifest.js:113`) |
| 24 | GET | `/<simulation_id>/agent-stats` | `get_agent_stats` :2104-2128 | `SimulationRunner.get_agent_stats` | — | **used** (`SimulationView.vue:517`) |
| 25 | GET | `/<simulation_id>/posts` | `get_simulation_posts` :2133-2208 | `sqlite3` on `{platform}_simulation.db` | — | **used** (`SimulationView.vue:515`) |
| 26 | GET | `/<simulation_id>/comments` | `get_simulation_comments` :2211-2292 | `sqlite3` on `{platform}_simulation.db` | — | **used** (`SimulationView.vue:516`) |
| 27 | POST | `/interview` | `interview_agent` :2297-2423 | `SimulationRunner.check_env_alive/interview_agent` | blocks the request thread polling the file IPC | none |
| 28 | POST | `/interview/batch` | `interview_agents_batch` :2426-2561 | `SimulationRunner.check_env_alive/interview_agents_batch` | blocks (timeout scaled up) | wrapper only (:192) |
| 29 | POST | `/interview/all` | `interview_all_agents` :2564-2664 | `SimulationRunner.check_env_alive/interview_all_agents` | blocks | none |
| 30 | POST | `/interview/history` | `get_interview_history` :2667-2736 | `SimulationRunner.get_interview_history` (sqlite `trace` table) | — | none |
| 31 | POST | `/env-status` | `get_env_status` :2739-2801 | `SimulationRunner.check_env_alive/get_env_status_detail` | — | wrapper only (:184) |
| 32 | POST | `/close-env` | `close_simulation_env` :2804-2871 | `SimulationRunner.close_simulation_env`, `SimulationManager._save_simulation_state` | sends a `close_env` IPC command | wrapper only (:176) |

Werkzeug ranks static segments above converters, so `/list` (:824) and `/history` (:912) match their own handlers even though `/<simulation_id>` (:791) is registered first. This follows from Werkzeug's routing rules and was not tested here.

---

## Walkthrough (source order)

### `backend/app/api/simulation.py`

**Module header (1-19).** Imports `Config`, `ZepEntityReader`, `OasisProfileGenerator`, `SimulationManager`/`SimulationStatus`, `SimulationRunner`/`RunnerStatus` and `ProjectManager` (:6-17). Logger name `mirofish.api.simulation` (:19). `RunnerStatus` is imported but never referenced in the module.

**`INTERVIEW_PROMPT_PREFIX` / `optimize_interview_prompt` (22-42).**
- The constant is a Chinese instruction (:24). Roughly: "answer me directly in text without calling any tool, combining your persona and all past memories and actions."
- `optimize_interview_prompt(prompt)` returns falsy prompts unchanged (:37-38). It is idempotent: a prompt that already starts with the prefix is returned as-is (:40-41). Otherwise it prepends the prefix (:42).
- Used by `/interview` (:2390), `/interview/batch` (:2525-2529) and `/interview/all` (:2632). The MCP `sim_interview_agents` tool does **not** use it.

**GET `/entities/<graph_id>` → `get_graph_entities` (47-89).**
- Guard: `if not Config.ZEP_API_KEY` → 500 (:59-63). This guard is dead code because the key defaults to the sentinel `'local-graphiti'` (`backend/app/config.py:1038`).
- Query `entity_types` (comma list, :65-66); `enrich` defaults to `"true"` (:67).
- Calls `ZepEntityReader().filter_defined_entities(graph_id, defined_entity_types, enrich_with_edges)` (:71-76) and returns `result.to_dict()` (:78-81).
- Any exception → 500 with `traceback` (:83-89). `traceback` fields are stripped in non-DEBUG mode by the app-wide `after_request` hook (`backend/app/__init__.py:186-196`).

**GET `/entities/<graph_id>/<entity_uuid>` → `get_entity_detail` (92-122).** Same dead key guard (:96-100). `reader.get_entity_with_context(graph_id, entity_uuid)` (:102-103). `None` → 404 (:105-109).

**GET `/entities/<graph_id>/by-type/<entity_type>` → `get_entities_by_type` (125-159).** `reader.get_entities_by_type(graph_id, entity_type, enrich_with_edges)` (:137-142). Returns `{entity_type, count, entities}` (:144-151).

**POST `/create` → `create_simulation` (164-236).**
- Body `project_id` is required → 400 (:196-201).
- Unknown project → 404 (:203-208).
- `graph_id` = body value or `project.graph_id`; if missing → 400 "call /api/graph/build first" (:210-215).
- `SimulationManager().create_simulation(project_id, graph_id, enable_twitter=True default, enable_reddit=True default)` (:217-223). The service generates `sim_<12 hex>` and writes `state.json` with status `created` (`backend/app/services/simulation_manager.py:846-860`).
- Returns `state.to_dict()` (:225-228). The docstring claims `max_rounds` etc. are LLM-generated (:169).

**`_check_simulation_prepared(simulation_id)` (239-396)**, the readiness predicate used by `/prepare`, `/prepare/status` and `/start`.
1. `sim_dir = Config.OASIS_SIMULATION_DATA_DIR/<id>` (:258). A missing directory → `(False, {"reason": ...})` (:261-262).
2. Required files: `state.json`, `simulation_config.json`, `reddit_profiles.json`, `twitter_profiles.csv` (:265-270). Any missing → `(False, {missing_files, existing_files})` (:282-287). Twitter-only and Reddit-only simulations still require both profile files.
3. Reads `state.json` and takes `status` and `config_generated` (:290-297).
4. **Role integrity gate** (LOOP-011), run only when `actor_role_count > 0` (:299-300):
   - sha256 of `actor_cast_manifest.json` must equal `state.actor_cast_manifest_sha256` (:301-307).
   - `actor_role_manifest_sha256` must be a dict (:308-310).
   - For each profile file, the sha256 of the adjacent `*_roles.json` (path from `OasisProfileGenerator._role_manifest_path`, `backend/app/services/oasis_profile_generator.py:2643-2645`) must match the per-platform fingerprint (:311-324).
   - `OasisProfileGenerator.validate_role_prompt_manifest(...)` must pass (:325-329).
   - Any `OSError`, `ValueError` or `TypeError` → `(False, {"reason": "角色提示词完整性校验失败", "error": ...})` (:330-334). The reason string means "role prompt integrity check failed".
5. Prepared iff `status in ["ready","preparing","running","completed","stopped","failed"]` **and** `config_generated` (:347-348). `"paused"` and `"created"` are not in the list.
6. Side effect: if status is `preparing`, it rewrites `state.json` to `status="ready"` with a new `updated_at`. The write is atomic (`write_json_atomic`) and holds `SimulationRunner._run_state_lock` (:360-374). Failures only log a warning (:373-374).
7. Returns `(True, {status, entities_count, profiles_count (len of reddit_profiles.json list), entity_types, config_generated, created_at, updated_at, existing_files})` (:376-386). Otherwise `(False, {reason, status, config_generated})` (:387-393). Any outer exception → `(False, {"reason": "读取状态文件失败: ..."})` ("failed to read the state file", :395-396).

**POST `/prepare` → `prepare_simulation` (399-675).**
- Body fields: `simulation_id` required (:448-453); `force_regenerate` default False (:465); `entity_types` (:507); `use_llm_for_profiles` default True (:508); `parallel_profile_count` default **5** (:509). The service default is 3 (`backend/app/services/simulation_manager.py:870`).
- Unknown simulation → 404 (:455-462).
- Unless forced, `_check_simulation_prepared` short-circuits with `{status:"ready", already_prepared:true, prepare_info}` (:469-484).
- The project must exist (404, :489-494) and must have a non-empty `simulation_requirement` (400, :497-502). `document_text = ProjectManager.get_extracted_text(...) or ""` (:505).
- **Synchronous preview** (:513-528): `ZepEntityReader().filter_defined_entities(graph_id, entity_types, enrich_with_edges=False)` sets `state.entities_count` and `state.entity_types` so the UI can show an expected agent count immediately. Failure is logged and ignored (:526-528). The preview does not apply the dossier stand-ins or the `select_agent_pool` cap used by the real prepare (`backend/app/services/simulation_manager.py:921-940`), so the preview count can differ from the final count.
- `TaskManager().create_task(task_type="simulation_prepare", metadata={simulation_id, project_id})` (:531-538). `TaskManager` is an in-memory process singleton (`backend/app/models/task.py:54-71`).
- Sets `state.status = PREPARING` and saves it (:541-542).
- **Background job `run_prepare` (:545-644):**
  - Marks the task `PROCESSING`, progress 0 (:547-552).
  - Defines `progress_callback(stage, progress, message, **kwargs)` (:558-617). It maps per-stage progress onto overall percent with `stage_weights` = reading 0-20, generating_profiles 20-70, generating_config 70-90, copying_scripts 90-100 (:560-565). Unknown stage → (0,100).
  - The callback builds `progress_detail` = `{current_stage, current_stage_name, stage_index, total_stages=4, stage_progress, current_item, total_items, item_description}` (:592-601) and a message `"[i/4] <name>: cur/total - msg"` (:604-610). It then calls `task_manager.update_task` (:612-617).
  - Calls `manager.prepare_simulation(simulation_id, simulation_requirement, document_text, defined_entity_types, use_llm_for_profiles, progress_callback, parallel_profile_count)` (:619-627). This is the LLM-heavy step: graph read, persona generation, config generation, seals.
  - On return → `complete_task(task_id, result=result_state.to_simple_dict())` (:630-633).
  - On exception → `fail_task` + reload state + `FAILED` + `error` + save (:635-644).
- `threading.Thread(target=run_prepare, daemon=True).start()` (:647-648).
- Response: `{simulation_id, task_id, status:"preparing", already_prepared:false, expected_entities_count, entity_types}` (:650-661).
- `ValueError` → 404 (:663-667); other exceptions → 500 (:669-675).

**POST `/prepare/status` → `get_prepare_status` (678-788).**
- If `simulation_id` is given and `_check_simulation_prepared` passes → `{status:"ready", progress:100, already_prepared:true, prepare_info}` (:715-728). This call can promote preparing→ready (see above).
- No `task_id`:
  - with `simulation_id` → `{status:"not_started", progress:0}` with success=true (:731-743);
  - otherwise 400 (:744-747).
- Unknown task (for example after a backend restart, because tasks live only in memory): if `simulation_id` is prepared → `ready` (:752-768); else 404 (:770-773).
- Otherwise returns `task.to_dict()` plus `already_prepared: False` (:775-781). Task dict fields: `task_id, task_type, status, created_at, updated_at, progress, message, progress_detail, result, error, metadata` (`backend/app/models/task.py:37-51`).
- Exceptions → 500 without a traceback (:783-788).

**GET `/<simulation_id>` → `get_simulation` (791-821).** 404 if there is no state (:798-802). Returns `state.to_dict()`. When status is `READY`, it adds `run_instructions` from `manager.get_run_instructions` (:807-808). Those instructions are absolute local paths plus `uv run python …/run_*_simulation.py --config …` commands (`backend/app/services/simulation_manager.py:1520-1544`). [verifier: imprecise. The `commands` dict holds plain `python …/run_*_simulation.py --config …` strings. Only the free-text `instructions` field says `uv run python` (backend/app/services/simulation_manager.py:1530-1543)]

**GET `/list` → `list_simulations` (824-850).** Optional `project_id` filter. Returns `data: [state.to_dict()], count`.

**`_get_report_id_for_simulation(simulation_id)` (853-909).**
- Scans `backend/uploads/reports/*/meta.json`; the path is hard-coded relative to `__file__`, not taken from `Config` (:871).
- Collects reports whose `meta.simulation_id` matches (:878-898) and returns the `report_id` with the latest `created_at` string (:904-905).
- Swallows per-file and overall errors and returns `None` (:897-898, 907-909).

**GET `/history` → `get_simulation_history` (912-1023).**
- `limit` defaults to 20 (:948). Takes `manager.list_simulations()[:limit]` (:951). `list_simulations` iterates `os.listdir` unsorted (`backend/app/services/simulation_manager.py:1458-1474`).
- Per simulation:
  - `simulation_requirement` and `total_simulation_hours` from `simulation_config.json`. Recommended rounds = `int(total_hours*60/max(minutes_per_round,1))` (:959-972).
  - `current_round`, `runner_status` and `total_rounds` from `SimulationRunner.get_run_state`. Uses `run_state.total_rounds` when > 0, else the recommended value (:975-984).
  - The project's first 3 file names (:987-994) and the latest `report_id` (:997).
  - Hard-coded `"version": "v1.0.2"` (:1000) and `created_date = created_at[:10]` (bare `except`, :1003-1007).

**GET `/<simulation_id>/profiles` → `get_simulation_profiles` (1026-1061).** Query `platform` defaults to `reddit`. `manager.get_profiles`:
- Twitter → `csv.DictReader` rows of `twitter_profiles.csv`.
- Otherwise → JSON `{platform}_profiles.json` (`backend/app/services/simulation_manager.py:1476-1507`).
- `ValueError` (unknown simulation) → 404 (:1049-1053).

**GET `/<simulation_id>/profiles/realtime` (1064-1171).** Reads files directly while generation is in progress.
- `reddit` → `reddit_profiles.json`. **Any other value** → `twitter_profiles.csv` (:1109-1112).
- Returns file mtime (:1121-1122) and the parsed rows. A parse failure (file mid-write) → `[]` (:1124-1134).
- Reads `state.json` for `is_generating = (status=="preparing")` and `total_expected = entities_count` (:1140-1149).
- 404 only if the simulation directory is missing (:1102-1106).

**GET `/<simulation_id>/config/realtime` (1174-1291).**
- Reads `simulation_config.json` if present and tolerates mid-write parse errors (:1212-1229).
- From `state.json`, derives `is_generating`, `config_generated` and `generation_stage`: `generating_config` if `profiles_generated`, else `generating_profiles`; `completed` when status is ready (:1236-1254).
- When a config exists, adds a `summary` of `{total_agents, simulation_hours, initial_posts_count, hot_topics_count, has_twitter_config, has_reddit_config, generated_at, llm_model}` (:1268-1278).

**GET `/<simulation_id>/config` (1294-1327).** `manager.get_simulation_config` → 404 if absent, else the full JSON.

**GET `/<simulation_id>/config/download` (1330-1356).** `send_file(<sim_dir>/simulation_config.json, as_attachment=True)`. Uses `manager._get_simulation_dir`, which **creates** the directory if it is missing (`backend/app/services/simulation_manager.py:751-755`).

**GET `/script/<script_name>/download` (1359-1408).** Allow-list: `run_twitter_simulation.py`, `run_reddit_simulation.py`, `run_parallel_simulation.py`, `action_logger.py` (:1375-1380). Others → 400 (:1382-1386). Missing file → 404 (:1390-1394). Otherwise `send_file` from `backend/scripts` (:1372, 1396-1400).

**POST `/generate-profiles` (1413-1482).** Standalone persona generation that creates no simulation.
- `graph_id` required (:1429-1434). `use_llm` default True, `platform` default reddit (:1436-1438).
- `filter_defined_entities(..., enrich_with_edges=True)` (:1440-1445). Zero entities → 400 (:1447-1451).
- `OasisProfileGenerator().generate_profiles_from_entities(entities, use_llm)` runs **inside the request thread** (:1453-1457). It passes no `graph_id`, so there is no graph-context enrichment.
- Output format: reddit/twitter/`to_dict` (:1459-1464).

**POST `/start` → `start_simulation` (1487-1682).**
- Body fields:
  - `simulation_id` required (:1531-1536);
  - `platform` default `parallel`, must be twitter, reddit or parallel (:1538, 1558-1562);
  - `max_rounds`: `int()`-coerced and must be > 0 (:1544-1556);
  - `enable_graph_memory_update` default False (:1540);
  - `force` default False (:1541).
- Unknown simulation → 404 (:1566-1572).
- **Non-READY branch** (:1577-1618), run only when `state.status != READY`:
  - If `_check_simulation_prepared` passes:
    - If status is RUNNING and `run_state.runner_status == "running"` (:1583-1586): with `force`, call `SimulationRunner.stop_simulation` and only log on error (:1588-1594). Without `force` → 400 "already running" (:1595-1599).
    - With `force`: `SimulationRunner.cleanup_simulation_logs` deletes run_state, logs, DBs, env_status, derived artifacts and per-platform actions/checkpoints (`backend/app/services/simulation_runner.py:2301-2388`). Sets `force_restarted=True` (:1602-1607).
    - Resets `state.status = READY` and saves (:1610-1612).
  - Not prepared → 400 "not ready, current status …, call /prepare first" (:1613-1618).
  - When the status is already READY, `force` does nothing: cleanup happens only inside this branch.
- Graph memory: if requested, `graph_id` = `state.graph_id` or `project.graph_id`; missing → 400 (:1621-1637).
- `SimulationRunner.start_simulation(simulation_id, platform, max_rounds, enable_graph_memory_update, graph_id)` (:1640-1646). There is no `sim_seed`, and `resume=None`, so resume is decided by `Config.SIM_RESUME` (`backend/app/services/simulation_runner.py:459, 761-779`; `backend/app/config.py:590`). The runner:
  - validates the config seal and role manifests (`simulation_runner.py:495+`);
  - writes `run_state.json` (STARTING → RUNNING);
  - spawns `sys.executable backend/scripts/run_{twitter|reddit|parallel}_simulation.py --config <path> [--config-seal] [--max-rounds N] [--resume]` with `cwd=sim_dir`, stdout+stderr to `simulation.log` and `start_new_session=True` (`simulation_runner.py:873-958`);
  - starts the daemon monitor thread `_monitor_simulation` (`simulation_runner.py:970-976`).
- Saves `state.status = RUNNING` (:1649-1650).
- Response = `run_state.to_dict()` plus:
  - `max_rounds_applied`;
  - `graph_memory_update_enabled = run_state.graph_memory_active`, the **actual** activation rather than the request flag (:1655-1657);
  - `graph_memory_requested`, `graph_memory_error`, `force_restarted` and `graph_id` (:1652-1663).
- `ValueError` (for example "already running", seal mismatch, missing config) → 400 (:1670-1674).

**POST `/stop` → `stop_simulation` (1685-1741).**
- `SimulationRunner.stop_simulation(simulation_id)` (:1715). It raises `ValueError` unless the runner is RUNNING, PAUSED or STARTING (`simulation_runner.py:1673-1674`). It terminates the process group or kills a persisted orphan pgid, then writes STOPPED. If termination cannot be confirmed it writes FAILED (`simulation_runner.py:1680-1716`).
- The API then sets **`state.json` status = `PAUSED`** regardless of the runner outcome (:1718-1722).
- `ValueError` → 400 (:1729-1733).

**GET `/<simulation_id>/run-status` (1746-1801).** `SimulationRunner.get_run_state`. When there is no state, it returns a synthetic idle payload with zeros (:1775-1788). Otherwise `run_state.to_dict()`: `runner_status, current_round, total_rounds, progress_percent, per-platform rounds/hours/running/completed/actions counts, total_actions_count, timestamps, error, process_pid/pgid, *_enabled, graph_memory_*, rounds_truncated_*, resumed_from_round`, plus calendar fields when in calendar mode (`backend/app/services/simulation_runner.py:209-253`).

**GET `/<simulation_id>/run-status/detail` (1804-1901).**
- Optional `platform` filter.
- Reads all actions once via `SimulationRunner.get_all_actions` (twitter/ and reddit/ `actions.jsonl`, falling back to the legacy root `actions.jsonl`; sorted newest-first; `simulation_runner.py:1802-1860`) (:1859-1862).
- Derives `twitter_actions` and `reddit_actions` (:1865-1872) and `recent_actions` (actions whose `round_num == current_round`, :1875-1879) in memory.
- Adds `all_actions` and `rounds_count = len(run_state.rounds)` (:1882-1888). The response is unbounded: the full action history on every poll.

**GET `/<simulation_id>/actions` (1904-1955).** Query `limit` (default 100), `offset` (0), `platform`, `agent_id` (int) and `round_num` (int) → `SimulationRunner.get_actions`. That method reads **all** actions and slices `[offset:offset+limit]` (`simulation_runner.py:1863-1894`).

**GET `/<simulation_id>/timeline` (1958-1995).** Query `start_round` (0) and `end_round` → `SimulationRunner.get_timeline`. It returns per-round `{round_num, twitter_actions, reddit_actions, total_actions, active_agents_count, active_agents, action_types, first_action_time, last_action_time}` (`simulation_runner.py:1897-1973`).

**Trajectory constants (2000-2003).** `TRAJECTORY_MAX_BYTES = 5*1024*1024`; `TRAJECTORY_MAX_ROWS = 720`.

**GET `/<simulation_id>/trajectory` (2006-2101).** Returns `world_state_trajectory.json`, the decision-channel output.
- Character check first: rejects empty, `.`, `..`, any `/` or `\`, and control characters (code < 32 or 127) → 404 (:2030-2037).
- Realpath containment: `commonpath([sim_dir, sim_root]) == sim_root` and `sim_dir != sim_root`, else 404 (:2038-2045).
- Symlinked or missing file → 404 "not generated yet" (:2047-2052). Size > 5 MiB → **413** (:2053-2057). JSON `ValueError` → 500 (:2059-2067).
- Accepts either `{trajectory:[...]}` or a bare list and keeps only dict rows (:2070-2073). Over 720 rows → keeps the **last** 720 and sets `truncated` (:2074-2077).
- Passes through only the scalar keys `schema_version`, `converged` and `settled_round` (:2086-2091).
- Covered by `backend/tests/test_simulation_trajectory_api.py`.

**GET `/<simulation_id>/agent-stats` (2104-2128).** `SimulationRunner.get_agent_stats`. Returns per-agent `{agent_id, agent_name, total_actions, twitter_actions, reddit_actions, action_types, first/last_action_time}` sorted by total_actions descending (`simulation_runner.py:1976-2023`).

**GET `/<simulation_id>/posts` (2133-2208).**
- `platform` default reddit, `limit` 50, `offset` 0 (:2146-2148).
- DB path = `os.path.join(dirname(__file__), '../../uploads/simulations/<id>') / f"{platform}_simulation.db"`. This is hard-coded rather than taken from `Config`, and `platform` is not validated (:2150-2156).
- Missing DB → success with `posts: []` and a message (:2158-2167).
- Runs `SELECT * FROM post ORDER BY created_at DESC LIMIT ? OFFSET ?` and `SELECT COUNT(*) FROM post` (:2175-2184). `sqlite3.OperationalError` (table missing) → empty result (:2186-2188).
- `conn.close()` is not in a `finally` (:2190).

**GET `/<simulation_id>/comments` (2211-2292).** Same pattern on the `comment` table. Platform-selectable since the fix noted at :2233-2236, which previously read only Reddit. Optional `post_id` filter (:2256-2268). No total count.

**POST `/interview` (2297-2423).**
- Body: `simulation_id`, `agent_id` (not None), `prompt` (all required, 400 otherwise, :2357-2373); `platform` ∈ {twitter, reddit} or absent (:2376-2380); `timeout` default **60** (:2355).
- `SimulationRunner.check_env_alive` checks that `env_status.json` has `status == "alive"` (`backend/app/services/simulation_ipc.py:424-439`). If not → 400 (:2383-2387).
- Prompt prefixed (:2390). Calls `SimulationRunner.interview_agent(...)`, which writes an IPC command file and polls for the response every 0.5 s until timeout (`simulation_ipc.py:209-322`) (:2392-2398).
- The HTTP envelope's `success` mirrors `result.success` while keeping status 200 (:2400-2403). `ValueError` → 400 (:2405-2409); `TimeoutError` → **504** (:2411-2415).

**POST `/interview/batch` (2426-2561).**
- `interviews` must be a non-empty list (:2484-2488). Each item needs `agent_id` and `prompt`; an item-level `platform` is validated (:2498-2515).
- Default `timeout` **120** (:2476). The runner raises it to at least `60 + INTERVIEW_TIMEOUT_PER_AGENT × ceil(n / max(1, sem//2))` (`simulation_runner.py:2713-2737`; `INTERVIEW_TIMEOUT_PER_AGENT` default 30, `backend/app/config.py:601`).
- Prompts are prefixed per item (:2525-2529).
- `TimeoutError` → 504 (:2549-2553).

**POST `/interview/all` (2564-2664).** Default `timeout` **180** (:2603). `SimulationRunner.interview_all_agents` builds `[{agent_id, prompt}]` from `simulation_config.json` `agent_configs` and delegates to the batch path (`simulation_runner.py:2805-2862`).

**POST `/interview/history` (2667-2736).** Body `simulation_id` (required), `platform` (None means both), `agent_id` and `limit` (default 100) → `SimulationRunner.get_interview_history`. It runs `SELECT user_id, info, created_at FROM trace WHERE action='interview' …` per platform DB, merges newest-first and caps at `limit` (`simulation_runner.py:2913-3019`).

**POST `/env-status` (2739-2801).** `check_env_alive` + `get_env_status_detail` (which reads `env_status.json`; default `{status:"stopped", twitter_available:false, reddit_available:false}`, `simulation_runner.py:2613-2646`). Returns `{simulation_id, env_alive, twitter_available, reddit_available, message}`.

**POST `/close-env` (2804-2871).**
- `timeout` default **30** (:2834).
- `SimulationRunner.close_simulation_env` sends a `close_env` IPC command. It treats an already-closed env and a response timeout as success (`simulation_runner.py:2865-2910`).
- The API then sets **`state.json` status = `COMPLETED`** unconditionally (:2848-2852).
- `success` mirrors the result (:2854-2857).

### `backend/app/mcp/__init__.py`

Docstring only (1-22), plus `__all__ = ["kg_server", "sim_server"]` (:24).
- States the design contract: FastMCP over stdio, consumed by the deer-flow 2.0 harness (:3-10).
- Lazy heavy dependencies: startup and `tools/list` never touch FalkorDB, Graphiti or the IPC (:13-15).
- Structured errors bounded by `asyncio.wait_for` (:16-18).
- Importing a module without the `mcp` SDK fails only at `build_server()`/`main()` (:20-21).

### `backend/app/mcp/kg_server.py` (`drf-kg`)

- **Bootstrap (28-42).** Inserts the backend directory into `sys.path` when started outside `backend/` (:36-40). `SERVER_NAME = "drf-kg"` (:42).
- **`INSTRUCTIONS` (44-55).** LLM-facing server description listing the tools, the optional `graph_id` and the structured-error contract.
- **Module state.** `_DEFAULT_GRAPH_ID = ""` (:58), `_SERVICE = None` (:61) and `_SERVICE_ERROR = None` (:62) form a lazy singleton.
- **`_default_graph_id()` (65-67).** Module value, else env `DRF_MCP_KG_GRAPH_ID` (stripped).
- **`_timeout_seconds()` (70-76).** `float(env DRF_MCP_KG_TIMEOUT or "60")`. Invalid or non-positive values → 60. An empty string (what deer-flow substitutes for an unset `$VAR`) → 60.
- **`_resolve_graph_id(graph_id)` (79-87).** Per-call value, else the default. Raises `ValueError` ("缺少 graph_id …", meaning "graph_id is missing") if both are empty.
- **`_get_service()` (90-104).**
  - Returns the cached service.
  - If an earlier construction failed, re-raises `RuntimeError(_SERVICE_ERROR)` immediately (:96-97). **The failure is cached for the life of the process: no retry.**
  - Otherwise lazy-imports and constructs `app.services.zep_tools.ZepToolsService()` (:99-101). Construction builds the Graphiti `Zep` shim and the `GraphitiRuntime` singleton, which starts a daemon `graphiti-loop` thread (`backend/app/services/zep_tools.py:490-495`; `backend/app/services/graphiti_client/client.py:355-357`; `backend/app/services/graphiti_client/runtime.py:187-192`).
- **`_error_payload(exc, graph_id)` (107-112).** `{"ok": False, "error": "<Type>: <msg>", "graph_id"?}`.
- **`_guarded(impl, graph_id, *args)` (115-140).** The single execution path for every KG tool.
  - Resolves the gid and gets the service. Both run synchronously on the event loop, **outside** the timeout.
  - Then `await asyncio.wait_for(asyncio.to_thread(impl, svc, gid, *args), timeout=_timeout_seconds())` (:128-131).
  - Success → `{"ok": True, "graph_id": gid, "result": <impl return>}` (:132).
  - Timeout → `{"ok": False, "graph_id", "error": "TimeoutError: … <N>s …"}` (:133-138). The worker thread keeps running after the timeout.
  - Other exceptions → `_error_payload` (:139-140).
  - The note at :120-123 explains why the tools are explicitly-typed module-level async functions and not a `functools.wraps` decorator: FastMCP builds the JSON schema by reflecting on the signature.
- **Sync implementations (143-216).** Each takes `(svc, graph_id, ...)`.
  - `_impl_search(query, limit=10, scope="edges", as_of=None)`: `as_of` truthy → `svc.as_of_search(...)`, else `svc.search_graph(...)`; returns `res.to_text()` (:145-152).
  - `_impl_trace_cascade(source="", target="", center="", causal_only=True)` → `svc.trace_cascade(...)`, which returns text (:155-159; service at `backend/app/services/zep_tools.py:2719`).
  - `_impl_entity_summary(entity_name)` → `svc.get_entity_summary(...)` (:162-164).
  - `_impl_get_entities(entity_type=None, limit=50)`: filtered by `get_entities_by_type` or all via `get_all_nodes`. Truncates to `max(1, int(limit))`. Each row is `{uuid, name, type = first label not in ("Entity","Node"), summary}` (:167-178).
  - `_impl_centrality(top_k=20)`:
    - degree counted over all edges' `source_node_uuid`/`target_node_uuid` (:186-193);
    - `degree_centrality = round(d/max_deg, 4)` (:201);
    - top `max(1, top_k)` sorted descending; the name falls back to `uuid[:8]` (:195-204);
    - merged with `get_graph_statistics` → `{total_nodes, total_edges, entity_types, top_by_degree_centrality}` (:205-211).
    - Deterministic; no LLM.
  - `_impl_statistics()` → `svc.get_graph_statistics(graph_id)` (:214-216).
- **Tool functions (223-253).** `kg_search(query, limit=10, scope="edges", as_of=None, graph_id=None)`, `kg_trace_cascade(source="", target="", center="", causal_only=True, graph_id=None)`, `kg_entity_summary(entity_name, graph_id=None)`, `kg_get_entities(entity_type=None, limit=50, graph_id=None)`, `kg_centrality_priors(top_k=20, graph_id=None)` and `kg_graph_statistics(graph_id=None)`. Each one only calls `_guarded`.
- **`_TOOL_SPECS` (257-314).** `(name, fn, English description)` triples. The descriptions are the LLM-facing tool docs (keywords for deferred `tool_search`).
- **`build_server(default_graph_id="")` (317-337).** Lazy-imports `mcp.server.fastmcp.FastMCP`. A missing SDK → `ImportError` that points at `backend/requirements.txt` (:323-329). Sets `_DEFAULT_GRAPH_ID` if one is given (:331-332). Creates `FastMCP("drf-kg", instructions=INSTRUCTIONS)` and registers each spec via `server.tool(name=, description=)(fn)` (:334-336).
- **`main(argv)` (340-354).** argparse `--graph-id` (:345-349). The default gid is the CLI value, else env `DRF_MCP_KG_GRAPH_ID` (:351). It is captured before any `app.*` import, so before `Config` runs `load_dotenv(override=True)`. [verifier: refuted. The harness launches `python -m app.mcp.kg_server`, so Python imports the `app` package before `main()` runs. `backend/app/__init__.py:18` imports `.config`, which runs `load_dotenv(..., override=True)` at module level (backend/app/config.py:16-24). The repo `.env` is therefore already applied when `main()` reads `DRF_MCP_KG_GRAPH_ID` (backend/app/mcp/kg_server.py:351). The same holds for `sim_server.py:306`.] Then `server.run(transport="stdio")`: stdout carries JSON-RPC and logs go to stderr (:353-354).

### `backend/app/mcp/sim_server.py` (`drf-simulation`)

- **Bootstrap (25-39).** Same `sys.path` fallback (:35-37). `SERVER_NAME = "drf-simulation"` (:39). `INSTRUCTIONS` (:41-51).
- **`_DEFAULT_SIM_ID` / `_default_sim_id()` (54-58).** Module value, else env `DRF_MCP_SIM_ID`.
- **`_default_timeout()` (61-67).** `DRF_MCP_SIM_TIMEOUT`, default and fallback 120.
- **`_resolve_sim_id` (70-76).** `ValueError` if neither a per-call nor a default id is set.
- **`_error_payload(exc, sim_id)` (79-83).** `{"ok": False, "error": ..., "sim_id"?}`.
- **`_sim_dir(sim_id)` (86-88).** `SimulationRunner.RUN_STATE_DIR/<sim_id>` = `backend/uploads/simulations/<id>` (`backend/app/services/simulation_runner.py:279-282`).
- **`_env_alive(sim_id)` (91-100).** False if the directory is missing. Otherwise `SimulationIPCClient(sim_dir).check_env_alive()`. The constructor **creates `ipc_commands/` and `ipc_responses/`** (`backend/app/services/simulation_ipc.py:202-207`). Any exception → False.
- **`_impl_status(sim_id)` (105-117).** Returns `{found: state is not None or dir exists, run_state: state.to_dict()|None, env_status: SimulationRunner.get_env_status_detail(sim_id), interview_ready: _env_alive(sim_id)}`.
- **`_impl_results(sim_id, top_agents=20)` (120-149).**
  - `get_run_state`, `get_timeline` (full) and `get_agent_stats`, the latter re-sorted by `total_actions` and cut to `max(1, top_agents)` (:123-129).
  - Optional `run_summary.json`; parse or OS errors → None (:131-138).
  - `partial = runner_status not in ("completed","failed","stopped")`; `"unknown"` if there is no state (:140-141).
  - Returns `{sim_id, partial, runner_status, timeline, agent_stats, run_summary}` (:142-149).
- **`_impl_interview(sim_id, prompt, agent_id, interviews, platform, timeout)` (152-184).**
  - Missing directory → `{ok:false, "ValueError: 模拟不存在"}` ("simulation does not exist", :157-158).
  - `_env_alive` false → `{ok:false, "EnvironmentNotAlive: …"}` immediately (:160-165).
  - Mode precedence:
    1. `interviews` truthy → `SimulationRunner.interview_agents_batch` (:167-169);
    2. `agent_id is not None and prompt` → `interview_agent` (:170-173);
    3. `prompt` → `interview_all_agents` (:174-176);
    4. otherwise → a "need interviews / agent_id+prompt / prompt" error (:177-181).
  - Returns `{"ok": True, "sim_id", "result": payload}`. `payload.success` may still be False when the IPC response failed (:182). Exceptions, including the inner IPC `TimeoutError`, → `_error_payload` (:183-184).
- **`_run_guarded(fn, sim_id, timeout, *args)` (189-197).** `asyncio.wait_for(asyncio.to_thread(fn, sim_id, *args), timeout)`. Timeout → `{ok:false, "TimeoutError: …"}`; other exceptions → `_error_payload`.
- **`build_server(default_sim_id="")` (200-292).** Lazy `FastMCP` import with the same ImportError guidance (:205-211). Sets `_DEFAULT_SIM_ID` (:213-214). Registers three closures with `@server.tool`:
  - `sim_status(sim_id=None)` (:218-236): resolves the sim_id (an error is returned as `_error_payload`), then `_run_guarded(_impl_status, sid, _default_timeout())`. Because `_impl_status` returns a bare dict with no `ok` key, the result is wrapped as `{ok:True, sim_id, result}` (:236).
  - `sim_results(sim_id=None, top_agents=20)` (:238-255): same pattern with `_impl_results`.
  - `sim_interview_agents(sim_id=None, prompt=None, agent_id=None, interviews=None, platform=None, timeout=None)` (:257-290):
    - `inner_timeout` = `timeout` if > 0, else `_default_timeout()` (:284);
    - **`outer_timeout = inner_timeout + 30.0`** (:286);
    - `_run_guarded(_impl_interview, sid, outer_timeout, prompt, agent_id, interviews, platform, inner_timeout)` (:287-290).
- **`main(argv)` (295-308).** argparse `--sim-id`, else env `DRF_MCP_SIM_ID`; then `server.run(transport="stdio")`.

---

## Control flow

**A. HTTP lifecycle (manual / SPA-driven).**
1. `POST /create` (:164) → `SimulationManager.create_simulation` writes `state.json` with status `created` (`backend/app/services/simulation_manager.py:826-860`).
2. `POST /prepare` (:399):
   - `_check_simulation_prepared` short-circuit (:469-486);
   - entity-count preview (:513-528);
   - `TaskManager.create_task` (:531);
   - status PREPARING (:541-542);
   - **daemon thread** `run_prepare` → `SimulationManager.prepare_simulation`. The service saves PREPARING again, reads entities, generates personas (LLM), generates the config (LLM), seals it and saves READY (`simulation_manager.py:901-1303`).
3. Client polls `POST /prepare/status` (:678) with `task_id` and/or `simulation_id`.
4. `POST /start` (:1487) → `SimulationRunner.start_simulation` → `subprocess.Popen` (`simulation_runner.py:943`) + `_monitor_simulation` thread (`simulation_runner.py:970-976`) → `state.json` RUNNING (:1649-1650).
5. Poll endpoints during the run: `GET /<id>/run-status` (:1746), `/run-status/detail` (:1804), `/actions` (:1904), `/timeline` (:1958), `/agent-stats` (:2104), `/posts` (:2133), `/comments` (:2211) and `/trajectory` (:2006). They read `run_state.json`, `*/actions.jsonl`, the SQLite DBs and `world_state_trajectory.json`.
6. After the platforms finish, the subprocess may stay in "command mode" with `env_status.json` = alive. Interview endpoints (:2297, :2426, :2564) write IPC command files and poll the responses.
7. `POST /close-env` (:2804) asks the subprocess to exit gracefully → `state.json` COMPLETED. `POST /stop` (:1685) instead kills the process group → `state.json` PAUSED.

**B. MCP launch chain.**
1. `_sync_deerflow_bridge_if_stale(deerflow_dir)` (`backend/app/services/pipeline_orchestrator.py:1441`) renders `deerflow_bridge/extensions_config.json` through `_render_bridge_extensions_config`. That function substitutes `{{DRF_BACKEND_PYTHON}}` with `sys.executable` (or `backend/.venv/bin/python`) and `{{DRF_REPO_ROOT}}` with the repo root, and rejects leftover `{{…}}` tokens (`pipeline_orchestrator.py:1365-1407`). The result is installed atomically at `deer-flow/extensions_config.json` (`pipeline_orchestrator.py:1410-1437, 1556-1578`). A broken template removes the deployed copy and skips MCP wiring without failing the sync (`pipeline_orchestrator.py:1563-1571`).
2. `DeerFlowResearchRunner.run(..., kg_graph_id=...)` (`pipeline_orchestrator.py:2114, 2156`). When `kg_graph_id` is set and `Config.RESEARCH_MCP_KG` is on (default true, `backend/app/config.py:521`), it sets `DEER_FLOW_EXTENSIONS_CONFIG_PATH=<deer-flow>/extensions_config.json` and `DRF_MCP_KG_GRAPH_ID=<graph_id>` in the research subprocess env (`pipeline_orchestrator.py:2414-2423`). The subprocess starts with `cwd=deerflow_dir` (`pipeline_orchestrator.py:2430`). `kg_graph_id=state.graph_id` is passed at `pipeline_orchestrator.py:10946, 11205, 11500, 12059`. `DRF_MCP_SIM_ID` is never set by the orchestrator.
3. The legacy bridge engine builds `deerflow.client.DeerFlowClient` (`deerflow_bridge/deerflow_research.py:16912-16926`). Its tool assembly calls `get_available_tools(...)` with `include_mcp=True` by default. That function loads `ExtensionsConfig.from_file()` and `get_cached_mcp_tools()` (`deer-flow/backend/packages/harness/deerflow/tools/tools.py:44-46, 118-127`).
4. deer-flow resolves `$VAR` env entries with `os.getenv`; an unset variable becomes `""` (`deer-flow/backend/packages/harness/deerflow/config/extensions_config.py:170-190`).
5. The MCP SDK `stdio_client` spawns each enabled server as `<python> -m app.mcp.{kg,sim}_server`. The child env is a minimal safe set plus the server's `env` block (`deer-flow/backend/.venv/lib/python3.12/site-packages/mcp/client/stdio/__init__.py:127`), i.e. `PYTHONPATH`, `DRF_MCP_*`, `FALKORDB_*`, `GRAPHITI_DATA_DIR`, `MINIMAX_API_KEY` (`deerflow_bridge/extensions_config.json:12-20, 31-36`).
6. In the child, `main()` → `build_server()` → `FastMCP.run("stdio")`. `initialize` and `tools/list` are answered with no backend contact. The first `tools/call` lazily imports `app.services.*`; `backend/app/config.py:12-24` then loads the repo `.env` with `override=True`. [verifier: imprecise. The `.env` load happens at child startup, not on the first `tools/call`: `-m app.mcp.*` imports `backend/app/__init__.py`, which imports Flask, flask_cors and `.config` (backend/app/__init__.py:15-18). The first `tools/call` lazily imports only `app.services.*`.]
7. Bridge `config.yaml` has `tool_search.enabled: false` (`deerflow_bridge/config.yaml:892-893`), so the MCP tools are bound to the agent directly rather than deferred.

---

## Data & artifacts

All simulation paths are under `backend/uploads/simulations/<simulation_id>/`. That directory is `Config.OASIS_SIMULATION_DATA_DIR` (`backend/app/config.py:1080`), `SimulationManager.SIMULATION_DATA_DIR` (`backend/app/services/simulation_manager.py:740-743`) and `SimulationRunner.RUN_STATE_DIR` (`backend/app/services/simulation_runner.py:279-282`). The same path is hard-coded again at `backend/app/api/simulation.py:2150-2153, 2228-2231`.

| Artifact | Format / key fields | Read by (slice) | Written by (slice) |
|---|---|---|---|
| `state.json` | `SimulationState.to_dict()`: `status` (created/preparing/ready/running/paused/stopped/completed/failed), `config_generated`, `entities_count`, `entity_types`, `actor_role_count`, `actor_cast_manifest_sha256`, `actor_role_manifest_sha256{twitter,reddit}`, seals, timestamps, `error` (`simulation_manager.py:621-699`) | `_check_simulation_prepared` :290-297; realtime endpoints :1140-1149, :1236-1254 | preparing→ready promotion :369-370; status writes via `_save_simulation_state` at :542, :644, :1612, :1650, :1722, :2852 |
| `simulation_config.json` | LLM config: `agent_configs[]`, `time_config{total_simulation_hours, minutes_per_round}`, `event_config{initial_posts, hot_topics}`, `twitter_config`/`reddit_config`, `simulation_requirement`, `generated_at`, `llm_model` | :959-968, :1219-1278, :1308, :1336; `interview_all_agents` reads `agent_configs` | — (prepare thread via the service) |
| `reddit_profiles.json` / `twitter_profiles.csv` | persona list (JSON) / OASIS CSV | :350-357, :1119-1134; `get_profiles` | — |
| `reddit_profiles_roles.json` / `twitter_profiles_roles.json` | role manifest (`schema_version actor-role-manifest/v2`, `actor_role_count`, `role_contract_version`) | sha256 + validation :311-329 | — |
| `actor_cast_manifest.json` | cast manifest | sha256 :301-307 | — |
| `run_state.json` | `SimulationRunState` (see the run-status fields) | via `SimulationRunner.get_run_state` (cached in the class dict `_run_states`) | runner; deleted by force cleanup |
| `twitter/actions.jsonl`, `reddit/actions.jsonl` (legacy `actions.jsonl`) | one `AgentAction` per line: `round_num, timestamp, platform, agent_id, agent_name, action_type, action_args, result, success` | detail/actions/timeline/agent-stats; MCP `sim_results` | subprocess |
| `twitter_simulation.db`, `reddit_simulation.db` | OASIS SQLite: `post`, `comment`, `trace` (`action='interview'`, `info` JSON with `prompt`/`response`) | `/posts` :2175-2184, `/comments` :2256-2270, `/interview/history` | subprocess |
| `env_status.json` | `{status: alive/stopped, twitter_available, reddit_available, timestamp}` | `check_env_alive`; `/env-status`; MCP `_env_alive`/`sim_status` | subprocess; runner `_mark_env_stopped` |
| `ipc_commands/<uuid>.json`, `ipc_responses/<uuid>.json`, `.processing`/`.cancel` markers | file IPC mailbox | — | `SimulationIPCClient` (`simulation_ipc.py:202-207, 254-341`); directories are created even by liveness probes |
| `world_state_trajectory.json` | `{trajectory:[{round, shares{...}, ...}], schema_version, converged, settled_round}` or a bare list | `/trajectory` :2047-2091 | decision channel (runner side) |
| `run_summary.json` | run accounting (organic vs seed, `simulation_health`, …) | MCP `_impl_results` :131-138 | runner `write_run_summary` |
| `simulation.log` | subprocess stdout+stderr | — | runner Popen |
| `backend/uploads/reports/<report_id>/meta.json` | `{report_id, simulation_id, created_at, status}` | `_get_report_id_for_simulation` :871-898 | report agent |
| `backend/scripts/{run_twitter,run_reddit,run_parallel}_simulation.py`, `action_logger.py` | scripts | `/script/<name>/download` :1372-1400 | — |
| `deerflow_bridge/extensions_config.json` → `deer-flow/extensions_config.json` | `{mcpServers:{drf-kg, drf-simulation:{enabled, type:"stdio", command, args:["-m","app.mcp.*"], env, description}}, skills:{}}` | deer-flow harness | orchestrator render/deploy |

**In-memory structures.**
- `TaskManager._tasks`: a process-wide dict, lost on restart (`backend/app/models/task.py:63-71`).
- `SimulationManager._simulations`: a per-instance cache. Every request creates a new `SimulationManager()`, so the cache is effectively per-request. The `run_prepare` closure keeps its instance.
- `SimulationRunner._run_states`, `_processes`, `_monitor_threads`, `_graph_memory_enabled`, `_run_state_lock` (RLock): class-level dicts and lock (`backend/app/services/simulation_runner.py:290-307`).
- `kg_server._SERVICE` / `_SERVICE_ERROR` / `_DEFAULT_GRAPH_ID` (:58-62).
- `sim_server._DEFAULT_SIM_ID` (:54).
- `ZepToolsService._nodes_cache` / `_edges_cache`: permanent per-instance graph caches (`backend/app/services/zep_tools.py:498-499, 1152-1184`).

---

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `ZEP_API_KEY` | sentinel `'local-graphiti'` | Truthiness guard on the 3 entity routes (always passes) | `backend/app/config.py:1038`; used `backend/app/api/simulation.py:59, 96, 129` |
| `Config.OASIS_SIMULATION_DATA_DIR` | `backend/uploads/simulations` | Root for `_check_simulation_prepared`, the realtime endpoints and `/trajectory` | `backend/app/config.py:1080`; used :258, :1100, :1203, :2038 |
| `SIM_RESUME` | false | Decides resume when `/start` passes `resume=None` | `backend/app/config.py:590`; `simulation_runner.py:761-779` |
| `INTERVIEW_TIMEOUT_PER_AGENT` | 30 | Scales up batch/all interview timeouts | `backend/app/config.py:601`; `simulation_runner.py:2713-2737` |
| `OASIS_CLI_SEMAPHORE` / `OASIS_SEMAPHORE`, `LLM_PROVIDER` | 8 / 30, `claude-cli` | Concurrency term in the interview timeout scaling | `simulation_runner.py:2726-2733` |
| `APP_API_TOKEN` | `""` | `/api/*` is loopback-only unless set; then requires the `X-API-Token` header [verifier: imprecise. Loopback requests without forwarding headers always pass with no token. The token is checked only for non-loopback or forwarded requests (backend/app/__init__.py:161-171)] | `backend/app/config.py:43`; `backend/app/__init__.py:154-172` |
| Flask `DEBUG` | off | When off, the `traceback` keys returned by these handlers are stripped | `backend/app/__init__.py:186-196` |
| `DRF_MCP_KG_GRAPH_ID` / `--graph-id` | `""` | Default graph for `kg_*` tools; empty → every call must pass `graph_id` | `backend/app/mcp/kg_server.py:67, 345-351` |
| `DRF_MCP_KG_TIMEOUT` | 60 s | Per-call `wait_for` bound for KG tools (≤0, invalid or empty → 60) | `backend/app/mcp/kg_server.py:70-76` |
| `DRF_MCP_SIM_ID` / `--sim-id` | `""` | Default simulation for `sim_*` tools | `backend/app/mcp/sim_server.py:58, 300-306` |
| `DRF_MCP_SIM_TIMEOUT` | 120 s | `wait_for` bound for status/results; inner interview timeout default (outer = +30 s) | `backend/app/mcp/sim_server.py:61-67, 284-286` |
| `RESEARCH_MCP_KG` | true | Orchestrator sets the deer-flow extensions env + `DRF_MCP_KG_GRAPH_ID` when a graph exists | `backend/app/config.py:521`; `backend/app/services/pipeline_orchestrator.py:2414` |
| `DEER_FLOW_EXTENSIONS_CONFIG_PATH` | unset | deer-flow config path priority #2 | `deer-flow/backend/packages/harness/deerflow/config/extensions_config.py:118-121` |
| `DEER_FLOW_PROJECT_ROOT` | unset → CWD | deer-flow project root for auto-discovery of `extensions_config.json` | `deer-flow/backend/packages/harness/deerflow/config/runtime_paths.py:7-16` |

**Hard-coded constants.**

| Constant | Value | Anchor |
|---|---|---|
| `TRAJECTORY_MAX_BYTES` / `TRAJECTORY_MAX_ROWS` | 5 MiB / 720 | :2002-2003 |
| Interview timeouts: single / batch / all / close-env | 60 / 120 / 180 / 30 s | :2355, :2476, :2603, :2834 |
| `/history` limit | 20 | :948 |
| `/history` version string | `v1.0.2` | :1000 |
| `/actions` limit | 100 | :1926 |
| `/posts` and `/comments` limit | 50 | :2147, :2225 |
| `/interview/history` limit | 100 | :2707 |
| `parallel_profile_count` | 5 | :509 |
| Prepare stage weights | — | :560-565 |
| Script allow-list | — | :1375-1380 |
| kg tool defaults: `limit` / `scope` / `top_k` | 10 / `edges` / 20 | `kg_server.py:223-248` |
| `kg_get_entities` limit | 50 | `kg_server.py:240` |
| sim `top_agents` | 20 | `sim_server.py:249` |

---

## External calls

| Kind | Where | Notes |
|---|---|---|
| LLM (persona + config generation) | `/prepare` background thread → `SimulationManager.prepare_simulation` (:619-627) | Long-running; the provider is chosen by `OasisProfileGenerator` (`oasis_profile_generator.py:362-374`) |
| LLM (persona generation, synchronous) | `/generate-profiles` (:1453-1457) | Blocks the Flask request thread |
| LLM (agents answering in character) | interview routes → file IPC → OASIS subprocess | Request blocks up to the (scaled) timeout |
| Graph DB (local Graphiti / FalkorDB via the Zep-shaped shim) | entity routes (:71-76, :102-103, :137-142), `/prepare` preview (:515-521), `/generate-profiles` (:1440-1445); MCP `kg_*` tools via `ZepToolsService` | The `kg_search` description mentions cross-encoder reranking (`kg_server.py:261`); not verified here |
| Graph writes + LLM extraction | `/start` with `enable_graph_memory_update` → `ZepGraphMemoryManager.create_updater` | `simulation_runner.py:852-866` |
| Subprocess | `/start` → `subprocess.Popen([sys.executable, backend/scripts/run_*_simulation.py, ...], cwd=sim_dir, start_new_session=True)` | `simulation_runner.py:943-954` |
| Process kill | `/stop` and `/start force` → `SimulationRunner.stop_simulation` (process-group terminate, kill or orphan kill) | `simulation_runner.py:1680-1704` |
| SQLite | `/posts` (:2169-2190), `/comments` (:2250-2275), `/interview/history` (`simulation_runner.py:2913-2968`) | Read-only queries; connections opened per request |
| File IPC | `check_env_alive`, `interview_*`, `close_simulation_env` | Polls every 0.5 s (`simulation_ipc.py:214, 306`) |
| MCP stdio JSON-RPC | `FastMCP.run(transport="stdio")` | `kg_server.py:354`, `sim_server.py:308` |

---

## Cross-module edges

**Into this slice.**
- **Flask registration:** `backend/app/__init__.py:200-202`; blueprint defined at `backend/app/api/__init__.py:8`, module imported at :15.
- **Frontend:**
  - `frontend/src/api/simulation.js` defines 22 wrappers (`grep -c "export const"`) over `/api/simulation/*` (:11-201).
  - The only importer is `frontend/src/components/research/SimulationView.vue:190-196`. It imports 5 wrappers: `getSimulationProfilesRealtime`, `getSimulationPosts`, `getSimulationComments`, `getAgentStats`, `getRunStatus`. It calls them in one batch at `SimulationView.vue:514-518`, with `posts` limit 60 and `comments` limit 200.
- **Tests:**
  - `backend/tests/test_simulation_trajectory_api.py` (the only HTTP test of this blueprint);
  - `backend/tests/test_mcp_servers.py` (unit tests at :138-420; real stdio subprocess smoke tests at :489-493);
  - `backend/tests/test_bridge_extensions_config.py` (template render/deploy, :45-110).
- **MCP spawners:** the deer-flow harness, via `deer-flow/extensions_config.json` rendered from `deerflow_bridge/extensions_config.json:3-38`. Orchestrator wiring is at `backend/app/services/pipeline_orchestrator.py:1365-1437, 1552-1578, 2196-2199, 2411-2423`.
- **No backend Python module imports the route functions** (grep for `app.api.simulation` / `from .simulation import` finds only the trajectory test).

**Out of this slice.**
- `SimulationManager` (`backend/app/services/simulation_manager.py`): `create_simulation` 826, `prepare_simulation` 862, `get_simulation` 1454, `list_simulations` 1458, `get_profiles` 1476, `get_simulation_config` 1509, `get_run_instructions` 1520, `_get_simulation_dir` 751, `_save_simulation_state` 757.
- `SimulationRunner` (`backend/app/services/simulation_runner.py`): `RUN_STATE_DIR` 279, `_run_state_lock` 307, `get_run_state` 310, `start_simulation` 451, `stop_simulation` 1665, `get_all_actions` 1802, `get_actions` 1863, `get_timeline` 1897, `get_agent_stats` 1976, `cleanup_simulation_logs` 2301, `check_env_alive` 2595, `get_env_status_detail` 2613, `interview_agent` 2649, `interview_agents_batch` 2740, `interview_all_agents` 2805, `close_simulation_env` 2865, `get_interview_history` 2971.
- `SimulationIPCClient` (`backend/app/services/simulation_ipc.py:187`; `check_env_alive` 424).
- `ZepEntityReader` (`backend/app/services/zep_entity_reader.py:175`; `filter_defined_entities` 319, `get_entity_with_context` 501, `get_entities_by_type` 581).
- `OasisProfileGenerator` (`backend/app/services/oasis_profile_generator.py:275`; `generate_profiles_from_entities` 2255, `_role_manifest_path` 2643, `validate_role_prompt_manifest` 2794, `to_reddit_format` 176, `to_twitter_format` 205).
- `ProjectManager` (`backend/app/models/project.py:181, 286`).
- `TaskManager` (`backend/app/models/task.py:54`).
- `write_json_atomic` (`backend/app/utils/atomic.py:53`).
- `ZepToolsService` (`backend/app/services/zep_tools.py:466`; `search_graph` 613, `as_of_search` 918, `get_all_nodes` 1142, `get_all_edges` 1187, `get_entities_by_type` 1307, `get_entity_summary` 1335, `get_graph_statistics` 1407, `trace_cascade` 2719).

---

## Invariants, gates, validation

- **Readiness gate:** four required files, `config_generated`, a status in the prepared list and, for researched casts, role/cast manifest fingerprints that match `state.json` (:239-396). The runner re-checks the config seal and role manifests at its own boundary on start (`simulation_runner.py:495+`, comment LOOP-011). So `/start` cannot launch a tampered or partial preparation even if the API gate passes.
- **Start-time input validation:** platform enum (:1558-1562), positive integer `max_rounds` (:1544-1556), and `graph_id` required for graph memory (:1621-1635).
- **"Already running" protection:** the API checks `run_state.runner_status == "running"` (:1586). The runner also refuses only when a live process exists (`simulation_runner.py:478-487`). [verifier: imprecise. On the `force` path the runner guard is bypassed. `cleanup_simulation_logs` deletes `run_state.json` and evicts the `_run_states` entry before `start_simulation` runs (backend/app/api/simulation.py:1602-1607, 1640; backend/app/services/simulation_runner.py:2337, 2376-2377). `existing` is then `None`, so the liveness check at `simulation_runner.py:482-485` never runs.]
- **Interview gates:**
  - liveness (`env_status.json` alive) before every interview (:2383, :2518, :2625; MCP `sim_server.py:160`);
  - platform enum on single, batch and all (:2376-2380, :2491-2495, :2618-2622);
  - per-item `agent_id`/`prompt` presence for batch (:2498-2515).
  - MCP `sim_interview_agents` checks none of the item fields or the platform.
- **`/trajectory` path containment and bounded output** (:2030-2091). This is the only route in the file that sanitizes `simulation_id` for path use.
- **Script download allow-list** (:1375-1386).
- **Atomic, locked state writes:** `state.json` promotions use `write_json_atomic` under `SimulationRunner._run_state_lock` (:367-370). That is the same lock `SimulationManager._save_simulation_state` takes (`simulation_manager.py:768-770`).
- **MCP invariants:**
  - Tools never raise to the protocol layer: every path returns a dict with `ok` (`kg_server.py:115-140`; `sim_server.py:189-197, 229-236, 249-255, 280-290`).
  - Startup and listing never import `app.services.*`; FastMCP is lazy-imported in `build_server` (`kg_server.py:317-337`; `sim_server.py:200-216`).
  - The graph/sim id must resolve per call or from the default, or a structured `ValueError` payload is returned (`kg_server.py:79-87`; `sim_server.py:70-76`).
- **Template render invariant:** no leftover `{{…}}` placeholders, and no machine-specific paths in the tracked template (`pipeline_orchestrator.py:1403-1406`; `backend/tests/test_bridge_extensions_config.py:45-51`).

---

## Failure modes & recovery

| Failure | Behavior | Anchor |
|---|---|---|
| Prepare raises in the background thread | Task FAILED with the error; `state.json` status `failed` + `error` | :635-644 |
| Prepare finds 0 entities | The service returns a FAILED state **without raising**, so the API marks the task **COMPLETED** with `result.status="failed"` | `simulation_manager.py:1026-1030`; :630-633 |
| Backend restart during or after prepare | The task disappears (in-memory). `/prepare/status` with `task_id` only → 404. With `simulation_id`, the file-based readiness check recovers | :752-773; `task.py:63-71` |
| Prepare preview entity read fails | Logged; the count stays at its previous value; prepare continues | :526-528 |
| `/start` on a running sim without `force` | 400 | :1595-1599 |
| `/start force` cannot stop the process | Only a warning; it still resets to READY and calls `start_simulation`, which raises `ValueError` "already running" if the process is alive → 400 [verifier: refuted. `force` always runs `cleanup_simulation_logs` first, which deletes `run_state.json` and evicts the cache (simulation_runner.py:2337, 2376-2377). `start_simulation` then sees `existing=None`, skips the liveness check at :482-485, and launches a second subprocess while the unkilled one may still be running (backend/app/api/simulation.py:1602-1612, 1640-1646)] | :1591-1594; `simulation_runner.py:483-485` |
| `/stop` cannot confirm termination | Runner records FAILED; the API still writes `state.json` PAUSED | `simulation_runner.py:1713-1717`; :1718-1722 |
| Interview against a dead env | 400 (HTTP) / `EnvironmentNotAlive` (MCP) immediately. The runner marks `env_status.json` stopped whenever it confirms process death, to avoid full-timeout waits | :2383-2387; `sim_server.py:160-165`; `simulation_runner.py:1569-1589, 1112` |
| Interview response timeout | HTTP 504. The IPC client writes a `.cancel` marker so the subprocess can skip the work | :2411-2415; `simulation_ipc.py:322-341` |
| MCP KG backend unavailable at first call | `{ok:false, "RuntimeError: 知识图谱后端不可用…"}` ("knowledge-graph backend unavailable"); **cached forever** for that server process [verifier: imprecise. Only a `ZepToolsService()` construction or import failure is cached. Construction does not contact FalkorDB because `GraphitiRuntime.__init__` sets `_falkor_client = None` lazily (backend/app/services/graphiti_client/runtime.py:187-196). A FalkorDB outage therefore surfaces per call inside the impl and is retried on the next call] | `kg_server.py:96-104` |
| MCP call exceeds the timeout | Structured `TimeoutError`; the thread-pool worker keeps running in the background | `kg_server.py:133-138`; `sim_server.py:193-195` |
| `mcp` SDK missing | `build_server` raises `ImportError` with install guidance, so the stdio server dies at startup | `kg_server.py:323-329`; `sim_server.py:205-211` |
| Broken extensions template | Deployed copy removed; KG MCP wiring skipped; research proceeds | `pipeline_orchestrator.py:1563-1578, 2420-2423` |
| Corrupt or mid-write profile/config files | Realtime endpoints return empty or `None` instead of 500 | :1132-1134, :1227-1229 |
| Missing SQLite DB or table | Success with empty lists | :2158-2167, :2186-2188, :2240-2248, :2272-2273 |

---

## Surprises

1. **S-1 (suspected): the "opt-in" MCP registration probably is not opt-in.**
   - The template comment says the harness loads the file only when `DEER_FLOW_EXTENSIONS_CONFIG_PATH` points at it (`deerflow_bridge/extensions_config.json:2`; also `backend/app/services/pipeline_orchestrator.py:1552-1554`).
   - But the file is deployed to `deer-flow/extensions_config.json`. deer-flow's resolver falls back to `<project_root>/extensions_config.json`, where project root = CWD unless `DEER_FLOW_PROJECT_ROOT` is set (`deer-flow/backend/packages/harness/deerflow/config/extensions_config.py:122-125`; `runtime_paths.py:7-16`). It also falls back to `<deer-flow>/extensions_config.json` (`extensions_config.py:127-136`).
   - The research subprocess runs with `cwd=deerflow_dir` (`pipeline_orchestrator.py:2430`), and nothing in `backend/app` or `deerflow_bridge` sets `DEER_FLOW_PROJECT_ROOT` (grep).
   - So on legacy-engine `DeerFlowClient` runs, both servers are likely spawned and their 9 tools bound even on first runs, with an empty default graph or sim id. Not verified by running.
   - The default v3 linear engine (`deerflow_bridge/linear_research.py`) contains no `mcp` reference (grep), so it probably does not use these tools at all.
2. **S-2 (suspected bug): `/stop` then `/start` is a dead end.** `/stop` writes `state.json` status `paused` (:1721). `_check_simulation_prepared` does not count `"paused"` as prepared (:347). The runner's monitor thread never rewrites `state.json` on exit (`_sync_state_json_status` is called only at `simulation_runner.py:1560, 2467`). So a later `/start`, even with `force=true`, returns 400 "not ready, current status: paused" until the simulation is re-prepared. `SimulationStatus.PAUSED` is also described as legacy and never entered on the runner side (`simulation_runner.py:274-275`). The API is the only writer.
3. **S-3 (suspected bug): readiness can flip to "ready" mid-regeneration.** `/prepare` with `force_regenerate=true` on an already-prepared simulation saves status `preparing` while `config_generated` is still `true` from the previous run. `prepare_simulation` never resets it (`simulation_manager.py:901-907`; flag set again at :1228). The old files still exist. Any concurrent `/prepare/status` poll that carries `simulation_id` therefore passes `_check_simulation_prepared`, rewrites `state.json` to `ready` (:360-372) and reports `already_prepared`, while the background thread is still regenerating personas. The same applies to a FAILED prepare saved with `config_generated=true`.
4. **S-4 (suspected bug): stale `run_state` in `sim_server`.** `SimulationRunner.get_run_state` returns the class-level `_run_states` cache once loaded and never re-reads `run_state.json` (`simulation_runner.py:310-319`). In the MCP server process nothing else updates that cache, so after the first call `sim_status.run_state` and `sim_results.partial`/`runner_status` stay frozen. `timeline` and `agent_stats` are fresh because they re-read `actions.jsonl`. The unit tests monkeypatch `get_run_state` and would not catch this (`backend/tests/test_mcp_servers.py:351-376`).
5. **S-5 (suspected): MCP outer watchdog shorter than the scaled IPC timeout.** `sim_interview_agents` uses outer = inner + 30 s (`sim_server.py:286`). The batch and all-agents runner paths raise the inner timeout to `60 + 30·ceil(n/concurrency)` (`simulation_runner.py:2713-2737, 2777-2781`). For example, 80 agents with the default CLI semaphore 8 (concurrency 4) gives 660 s. The MCP tool therefore returns `TimeoutError` at 150 s while the worker thread and the agents keep answering for minutes. No `.cancel` marker is written until the inner timeout elapses.
6. **S-6: KG service construction failure is permanent per process.** For example, FalkorDB is not up yet on the first call: `_SERVICE_ERROR` is cached and never retried (`kg_server.py:96-97, 103-104`). [verifier: imprecise example. Construction never contacts FalkorDB: `Zep()` only calls `get_runtime()`, and `GraphitiRuntime.__init__` starts the loop with `_falkor_client = None` (backend/app/services/graphiti_client/client.py:355-357; backend/app/services/graphiti_client/runtime.py:187-196). A down FalkorDB fails individual calls and is not cached. The permanent cache applies to import or construction errors such as a missing dependency or a bad `Config`.] `ZepToolsService` node and edge caches are also permanent per instance (`zep_tools.py:1152-1184`), so `kg_get_entities`, `kg_centrality_priors` and `kg_graph_statistics` return snapshot data for the life of the server. Service construction also runs outside the `wait_for` bound (`kg_server.py:126-127`).
7. **S-7: MCP and HTTP interview logic diverge.**
   - MCP does not prepend `INTERVIEW_PROMPT_PREFIX` (compare :2390 with `sim_server.py:167-176`).
   - MCP does not validate `platform` or batch items.
   - MCP `ok:true` wraps a payload whose own `success` may be false (`sim_server.py:182`).
   - A third, different interview prefix exists in `backend/app/services/zep_tools.py:2038-2049`.
8. **S-8 (suspected): the 0-entity prepare reports task "completed"** (see Failure modes). Clients that look only at `task.status` will treat a FAILED preparation as done (`simulation_manager.py:1026-1030`; :630-633).
9. **S-9: dead and drifted code paths.**
   - The `ZEP_API_KEY` guards can never fire (sentinel at `config.py:1038`; :59, :96, :129).
   - The `"copying_scripts"` stage weight (:564) is never emitted; the service emits only reading, generating_profiles and generating_config.
   - `config/realtime` branches on `state_data["profiles_generated"]` (:1247), a key `SimulationState.to_dict()` never writes (`simulation_manager.py:666-699`; repo-wide grep finds it only at :1247). `generation_stage` therefore never reports `generating_config`.
   - `RunnerStatus` is imported but unused (:15).
10. **S-10: unused HTTP surface.**
    - Only 5 of 32 routes are reachable from the shipped UI (`SimulationView.vue:190-196`). The `/trajectory` docstring claims the Step3 chart polls it (:2010-2011), but no frontend code references it.
    - 17 of the 22 wrappers in `frontend/src/api/simulation.js` have no importer.
11. **S-11: side-effecting "reads".**
    - `SimulationManager._get_simulation_dir` `os.makedirs` the directory. So `GET /<id>`, `/config`, `/config/download`, `/profiles` and every POST that calls `manager.get_simulation` with an unknown id create an empty `uploads/simulations/<id>/` directory (`simulation_manager.py:751-755, 772-779`).
    - `check_env_alive` (HTTP `/env-status`, MCP `sim_status`) creates `ipc_commands/` and `ipc_responses/` (`simulation_ipc.py:202-207`). This contradicts "pure file reads" in the `sim_status` description (`sim_server.py:224`) and in `DRF_ARCHITECTURE.md:1573-1574`.
    - `_check_simulation_prepared` writes `state.json` (:360-372) even when reached from the polling endpoint `/prepare/status`.
12. **S-12 (suspected, low risk because `/api` is loopback-only by default per `backend/app/__init__.py:154-172`): inconsistent path hardening.**
    - `/trajectory` sanitizes `simulation_id`.
    - `/posts` and `/comments` interpolate an unvalidated `platform` into a DB filename (:2155, :2237).
    - POST bodies pass a raw `simulation_id` into `os.path.join` + `makedirs` (via `SimulationManager`).
    - `GET /<id>` returns absolute server paths in `run_instructions` (`simulation_manager.py:1520-1544`, dict built from :1526).
13. **S-13: `/history` truncates an unsorted list.** `list_simulations()[:limit]` comes from raw `os.listdir` order (:951; `simulation_manager.py:1462`) [verifier: anchor off by one; `os.listdir` is at backend/app/services/simulation_manager.py:1463], so "latest 20" is not guaranteed. It also scans every report `meta.json` once per simulation (:997 → :878-898), and the version is hard-coded to `v1.0.2` (:1000).
14. **S-14: the same simulation-data path is defined four ways:** `Config.OASIS_SIMULATION_DATA_DIR`, `SimulationManager.SIMULATION_DATA_DIR`, `SimulationRunner.RUN_STATE_DIR`, and the literals in `/posts` and `/comments` (:2150-2153, :2228-2231). The reports directory is likewise a literal (:871). The trajectory test monkeypatches only `Config.OASIS_SIMULATION_DATA_DIR` (`backend/tests/test_simulation_trajectory_api.py:20`) [verifier: anchor off by one; the `setattr` is at backend/tests/test_simulation_trajectory_api.py:19], so the other routes would not follow such an override.
15. **S-15 (suspected env drift): `mcp>=1.10.0` is declared only in `backend/requirements.txt:46`, not in `backend/pyproject.toml`** (grep finds no `mcp` dependency there). A `uv sync`-built backend venv could lack the SDK, and both servers would then fail at `build_server` with ImportError. The rendered `command` is `sys.executable` of the backend (`pipeline_orchestrator.py:1372-1376`). [verifier: refuted as a risk. `mcp` is not declared directly, but `backend/pyproject.toml:35` pins `camel-ai==0.2.78`, which hard-depends on `mcp`. The HEAD `backend/uv.lock` (deleted in the working tree) lists `{ name = "mcp" }` under camel-ai's `dependencies` and locks mcp 1.24.0. `backend/.venv` contains `mcp-1.24.0.dist-info`. A uv-synced venv therefore has the SDK. The only real gap is that the direct `>=1.10.0` floor is not enforced.]
16. **S-16: `.env` override inside MCP children.** Children inherit a minimal env plus the explicit `env` block. On the first tool call, `backend/app/config.py:21` runs `load_dotenv(..., override=True)`, so repo `.env` values override harness-passed values that are read later. `DRF_MCP_KG_TIMEOUT` and `DRF_MCP_SIM_TIMEOUT` are read per call; the default ids are captured earlier in `main()` and are unaffected (`kg_server.py:351`; `sim_server.py:306`). [verifier: refuted on timing. `load_dotenv(override=True)` runs at child startup, because `-m app.mcp.*` imports `backend/app/__init__.py`, which imports `.config` (backend/app/__init__.py:18; backend/app/config.py:16-24). It runs before `main()` reads `DRF_MCP_KG_GRAPH_ID` or `DRF_MCP_SIM_ID`. So any `DRF_MCP_*` key in the repo `.env` overrides the harness-passed value for the default ids as well as the timeouts.]
17. **S-17: doc-vs-code drift.**
    - `EXTERNAL_INTEGRATIONS_MAP.md:523` says MCP servers are launched by `subprocess.Popen("python -m app.mcp.*")`. They are actually spawned by deer-flow's MCP client (the `mcp` SDK `stdio_client`), never by DRF code.
    - `ARCHITECTURE_MAP.md:793` says all sim calls are bounded by `DRF_MCP_SIM_TIMEOUT`, but interviews use inner + 30 s.
    - `DRF_ARCHITECTURE.md:1566` cites `trace_cascade` at `zep_tools.py:2716`; it is at :2719.
    - `DRF_ARCHITECTURE.md:91` and `ARCHITECTURE_MAP.md:39` say the servers are consumed "on scenario re-runs" (see S-1).
18. **S-18: minor.**
    - `/posts` and `/comments` do not close SQLite connections in `finally` (:2190, :2275).
    - `/interview*` accept a non-numeric `timeout` and a non-int `agent_id` without validation; a bad `timeout` surfaces as a 500 from the IPC loop. [verifier: imprecise. The single `/interview` route returns 500 from the IPC client (`timeout * 2.0`, backend/app/services/simulation_ipc.py:234). The batch and all routes go through `_scale_interview_timeout` first. A non-numeric string raises `ValueError` there and returns 400 (simulation_runner.py:2737). A numeric string passes, then fails the `float > str` comparison and returns 500 (simulation_runner.py:2777)]
    - `/start force` on a simulation whose status is already READY does not clean old logs (:1577).
    - `/close-env` sets COMPLETED even if the close failed or the run had FAILED (:2848-2852).
    - `/generate-profiles` runs LLM persona generation synchronously in the request thread (:1453-1457).

---

## Verification

An adversarial verifier re-read the cited code on the `main` checkout on 2026-10-11, without running it. Scope:
- every key claim and surprise in the reader's summary (15 claims, 14 surprises);
- more than 20 further statements from the Walkthrough, Control flow, knob tables and failure table;
- a skim of the slice for omissions.

Inline `[verifier: …]` notes above mark each statement found wrong or imprecise.

**Verdict counts (40 verdicts):** 27 confirmed, 9 imprecise, 4 refuted, 0 unverifiable.
- **Summary list (29 items):** 27 confirmed, 1 imprecise (C5), 1 refuted (S-15).
- **Extra spot-check verdicts (11 items, all non-confirmed):** 8 imprecise, 3 refuted.

S-1 is confirmed only by reading the static chain. It was not run-verified. The chain:
1. The research subprocess runs with `cwd=deerflow_dir` (`backend/app/services/pipeline_orchestrator.py:2429-2431`).
2. deer-flow's resolver falls back to `<project_root>/extensions_config.json`, where the project root is the CWD (`deer-flow/backend/packages/harness/deerflow/config/extensions_config.py:122-136`; `runtime_paths.py:7-16, 34-41`).
3. The rendered `deer-flow/extensions_config.json` exists and has both servers `enabled: true`.
4. `DeerFlowClient._get_tools` calls `get_available_tools` with `include_mcp=True` by default (`deer-flow/backend/packages/harness/deerflow/client.py:284-288`; `tools/tools.py:44-46, 118-127`).
5. Nothing in DRF sets `DEER_FLOW_PROJECT_ROOT`. `deerflow_bridge/deerflow_research.py:16449` only reads it.

### Non-confirmed items and corrections

1. **C5, imprecise.** The summary claim says `/start force=true` stops a live run and calls `cleanup_simulation_logs`. Correction:
   - Both actions happen only inside the `state.status != READY` branch, and only after `_check_simulation_prepared` passes.
   - The stop additionally requires `state.status == RUNNING` and `run_state.runner_status == "running"` (`backend/app/api/simulation.py:1577-1607`).
   - The Walkthrough itself states this correctly at "When the status is already READY, `force` does nothing".
2. **S-15, refuted.** The claim is that `mcp` is missing from pyproject, so a uv venv may lack the SDK. Correction:
   - `backend/pyproject.toml:35` pins `camel-ai==0.2.78`.
   - camel-ai hard-depends on `mcp`: HEAD's `backend/uv.lock` lists `mcp` in camel-ai's `dependencies` and locks mcp 1.24.0.
   - `backend/.venv` has `mcp-1.24.0.dist-info`.
   - Only the direct `>=1.10.0` floor (`backend/requirements.txt:46`) is missing from pyproject.
3. **Walkthrough `kg_server.main`, refuted.** The map says the default graph id is captured "before any `app.*` import, so before … `load_dotenv`". Correction:
   - `-m app.mcp.kg_server` imports the `app` package first.
   - `backend/app/__init__.py:18` imports `.config`, which runs `load_dotenv(override=True)` at module level (`backend/app/config.py:16-24`).
   - So the repo `.env` is applied before `kg_server.py:351` (and `sim_server.py:306`) read the id.
4. **S-16, refuted (timing).** The `.env` override does not happen on the first tool call. It happens at child startup, through the `app` package import, so `.env` `DRF_MCP_*` keys override the harness-passed default ids as well as the timeouts (`backend/app/__init__.py:18`; `backend/app/config.py:16-24`).
5. **Failure row "/start force cannot stop the process", refuted.** The map says `start_simulation` would raise "already running". Correction:
   - `cleanup_simulation_logs` deletes `run_state.json` and evicts `_run_states` (`backend/app/services/simulation_runner.py:2337, 2376-2377`).
   - So `existing` is `None` at `simulation_runner.py:482`, and the liveness guard at :484-485 never runs.
   - A second OASIS subprocess can be launched while the unkillable first one survives (`backend/app/api/simulation.py:1588-1612, 1640-1646`).
6. **Control flow B.6, imprecise.** The `.env` load is attributed to the first `tools/call`. It happens at startup through `backend/app/__init__.py:15-18`, which also imports Flask and flask_cors.
7. **Design rule "Heavy imports are lazy", imprecise.** Flask, flask_cors and `Config` (with the `.env` load) are imported at server start. Only `app.services.*` is lazy (`backend/app/__init__.py:15-18`).
8. **S-6 example and failure row "MCP KG backend unavailable at first call", imprecise.** Correction:
   - `ZepToolsService()` construction never contacts FalkorDB, because `GraphitiRuntime.__init__` leaves `_falkor_client = None` (`backend/app/services/graphiti_client/runtime.py:187-196`; `client.py:355-357`).
   - FalkorDB outages fail per call and are retried on the next call.
   - Only import or construction errors are cached in `_SERVICE_ERROR`.
9. **Invariant "Already running protection", imprecise.** The runner-side guard is bypassed on the `force` path for the reason in item 5.
10. **`APP_API_TOKEN` knob, imprecise.** Loopback requests without forwarding headers always pass. The token is required only for non-loopback or forwarded requests (`backend/app/__init__.py:161-171`).
11. **`GET /<id>` run_instructions, imprecise.** The `commands` values are plain `python …` strings. `uv run python` appears only in the `instructions` text (`backend/app/services/simulation_manager.py:1530-1543`).
12. **S-18 bad `timeout`, imprecise.**
    - Single `/interview` with a string `timeout` returns 500 from the IPC client (`backend/app/services/simulation_ipc.py:234`).
    - On batch and all, a non-numeric string returns 400, through `ValueError` in `_scale_interview_timeout` (`simulation_runner.py:2737`).
    - On batch and all, a numeric string returns 500 from the `float > str` comparison (`simulation_runner.py:2777`).
13. **Minor anchor drift, imprecise.**
    - S-13 `os.listdir` is at `simulation_manager.py:1463`, not 1462.
    - S-14 `setattr` is at `backend/tests/test_simulation_trajectory_api.py:19`, not 20.

### Omissions (significant behavior the map did not cover)

1. **`/start force` can create a duplicate run.** When `stop_simulation` cannot confirm termination, it records FAILED and does not raise (`backend/app/services/simulation_runner.py:1708-1718`). The API then runs `cleanup_simulation_logs`, which:
   - removes `run_state.json`, `env_status.json` and the `_run_states` cache entry;
   - lets `start_simulation` `Popen` a second subprocess and overwrite `_processes[simulation_id]`.

   The orphan keeps running untracked (`backend/app/api/simulation.py:1588-1612`; `simulation_runner.py:2337-2377, 482-485, 966`).
2. **MCP children load Flask and the repo `.env` at startup.** The `-m app.mcp.*` entry point pulls in `backend/app/__init__.py` (Flask, flask_cors, `Config`), so `.env` values (`load_dotenv(override=True)`) apply before `main()`. As a result:
   - `.env` `DRF_MCP_KG_GRAPH_ID` or `DRF_MCP_SIM_ID` would override the orchestrator-provided id.
   - `.env` FALKORDB_* values replace the `""` that the harness substitutes for unset `$VAR`s (`backend/app/__init__.py:15-18`; `backend/app/config.py:16-24`; `backend/app/mcp/kg_server.py:351`; `backend/app/mcp/sim_server.py:306`).
3. **HTTP `/prepare` can never produce a researched cast.** It calls `prepare_simulation` without `actors`, `graph_priors`, `max_rounds` or `research_language` (`backend/app/api/simulation.py:619-627`). The orchestrator passes all four (`backend/app/services/pipeline_orchestrator.py:8790-8799`). So HTTP-prepared simulations always end with `actor_role_count=0` and skip the role-integrity gate in `_check_simulation_prepared` (:299-334).
4. **MCP `sim_id` is unsanitized.** `_sim_dir` joins an LLM-supplied `sim_id` straight onto `RUN_STATE_DIR` (`backend/app/mcp/sim_server.py:86-88`). As a result:
   - `..` ids resolve outside the simulations root.
   - `_env_alive` then creates `ipc_commands/` and `ipc_responses/` inside any existing directory (`sim_server.py:91-100`; `backend/app/services/simulation_ipc.py:202-207`).
   - S-12 covers only the HTTP side.
5. **More doc drift.** `DRF_ARCHITECTURE.md:89` and `ARCHITECTURE_MAP.md:37` cite the OASIS `Popen` at `simulation_runner.py:685-695`. It is at `backend/app/services/simulation_runner.py:943-954`.
