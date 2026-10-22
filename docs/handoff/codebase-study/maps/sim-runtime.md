# sim-runtime — Simulation manager, runner, IPC

Scope: three files on branch `main`, read from the on-disk checkout on 2026-10-11:

| Short prefix | File | Lines |
|---|---|---|
| `mgr:N` | `backend/app/services/simulation_manager.py` | 1,544 |
| `run:N` | `backend/app/services/simulation_runner.py` | 3,021 |
| `ipc:N` | `backend/app/services/simulation_ipc.py` | 732 |

All other anchors use the full repo-relative `path:line`. I read every line of the three files. Code outside the slice is cited only to explain how the slice gets called, or what a call out of it does.

---

## Purpose & position in the pipeline

This slice covers stages 4 and 5 of the DRF pipeline: **PREPARE** (build the simulation environment) and **RUN** (execute it). It also covers the post-run **interview channel** that the REPORT stage uses.

1. **`SimulationManager`** (`mgr:727-1544`) owns `uploads/simulations/<sim_id>/state.json`. PREPARE works like this:
   - Read and filter graph entities (`ZepEntityReader`).
   - Make sure every eligible dossier actor has an entity (`ensure_dossier_actor_entities`, `mgr:224`).
   - Choose the agent pool (`select_agent_pool`, `mgr:351`).
   - Seal per-actor research-context packs.
   - Generate OASIS personas (`OasisProfileGenerator`) and the LLM-driven `simulation_config.json` (`SimulationConfigGenerator`).
   - Seal the exact config bytes, plus the cast/context/role authority files, into `simulation_config_manifest.json` (`build_simulation_config_seal`, `mgr:52`).
2. **`SimulationRunner`** (`run:266-3021`) is a class-level singleton (every method is a `@classmethod`; state lives in class dicts, `run:291-307`). [verifier: not every method — `_read_log_tail` and `_missing_platform_completions` are `@staticmethod` (run:988,1001); the other 39 are classmethods] It owns `run_state.json` and does the following:
   - Re-validates the PREPARE seal at the runner boundary (`run:497-759`).
   - Launches `backend/scripts/run_{parallel|twitter|reddit}_simulation.py` as a detached process group (`run:907-953`).
   - Tails `{twitter,reddit}/actions.jsonl` from a daemon monitor thread (`run:1011-1146`). Results go into `SimulationRunState`, and parsed actions are optionally forwarded to the graph-memory updater (`run:1279-1280`).
   - Decides COMPLETED/FAILED/STOPPED.
   - Reclaims orphans after a backend restart (`run:1519`), handles stop and cleanup, and writes `run_summary.json` for the report stage (`run:2025`).
3. **`simulation_ipc`** (`ipc:1-732`) is a filesystem mailbox protocol (`ipc_commands/`, `ipc_responses/`, `env_status.json`). After a simulation finishes its rounds, the subprocess stays alive in "command-wait mode". The backend, mainly the report agent, uses this channel to interview agents (`interview`, `batch_interview`) and to `close_env`.

Upstream: `pipeline_orchestrator.py` (`create_simulation`/`prepare_simulation` at `backend/app/services/pipeline_orchestrator.py:12776,12811`; `reseal_simulation_config` at `:12925`; `start_simulation` at `:12989`) and the Flask API (`backend/app/api/simulation.py`). Downstream: the REPORT stage reads `run_summary.json` and the action logs, and interviews agents through IPC (`backend/app/services/zep_tools.py:2065`).

---

## Walkthrough (source order)

### A. `backend/app/services/simulation_manager.py`

#### Imports / module constants (`mgr:1-35`)
- Imports `ZepEntityReader`, `OasisProfileGenerator`, `SimulationConfigGenerator`, and actor-context helpers (`ACTOR_CONTEXT_VERSION="actor-context/v1"`, `ACTOR_INTELLIGENCE_VERSION="actor-intelligence/v1"`; see `backend/app/services/actor_context.py:26,28`) and `write_json_atomic` (`mgr:17-30`).
- Logger name: `mirofish.simulation` (`mgr:32`).
- `SIMULATION_CONFIG_MANIFEST_VERSION = "simulation-config-manifest/v1"` (`mgr:35`).
- Unused imports: `shutil`, `FilteredEntities`, `OasisAgentProfile`, `SimulationParameters` (`mgr:11,19-21`).

#### `_canonical_json_sha256(value)` (`mgr:38-42`)
SHA-256 of `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",",":"), allow_nan=False)`. Used for the dossier fingerprint and for the config canonical hash.

#### `_file_sha256(path)` (`mgr:45-49`)
Byte SHA-256 of a file. Raises `ValueError("sealed artifact is missing: <basename>")` if the path is not a file.

#### `build_simulation_config_seal(sim_dir, *, simulation_id, actor_cast_manifest_sha256, actor_context_manifest_sha256, actor_role_manifest_sha256)` (`mgr:52-134`)
- Reads the raw bytes of `simulation_config.json` and computes `config_sha` (`mgr:61-64`). The config must parse to a dict (`mgr:65-67`). If the config carries a `simulation_id`, it must equal the argument; otherwise it raises "simulation config identity mismatch" (`mgr:68-70`).
- Bindings: `actor_cast_manifest` (`actor_cast_manifest.json`) and `actor_context_manifest` (`actor_context_manifest.json`):
  - When an expected SHA is given, the file must exist and match. Otherwise it raises "... fingerprint mismatch" (`mgr:90-94`).
  - When no SHA is given but the file exists, it is bound anyway, so a discovered authority file is never silently left out (`mgr:95-98`).
- Role manifests: `actor_role_manifest_sha256` must be a dict (`mgr:104-105`). Each `{platform: sha}` must name `reddit` → `reddit_profiles_roles.json` or `twitter` → `twitter_profiles_roles.json` and have a non-empty SHA that matches the file on disk (`mgr:100-116`).
- Writes `simulation_config_manifest.json` atomically (indent 2, `allow_nan=False`). Fields: `{schema_version, simulation_id, simulation_config_file:"simulation_config.json", simulation_config_sha256, simulation_config_canonical_sha256, bindings}` (`mgr:118-133`).
- Returns `(config_sha, sha256(manifest file))` (`mgr:134`).

#### `validate_simulation_config_seal(sim_dir, *, expected_manifest_sha256=None, expected_config_sha256=None, expected_simulation_id=None, require=False)` (`mgr:137-221`)
- If the manifest is missing: raises "simulation config manifest is missing" when `require` is set or either expected SHA is given. Otherwise it returns `{}`, the legacy/unsealed pass (`mgr:146-150`).
- Checks, in order:
  1. Manifest SHA (`mgr:151-153`).
  2. Manifest is a dict (`mgr:156-157`).
  3. `schema_version` equals v1, else "stale" (`mgr:158-159`).
  4. Identity (`mgr:160-163`).
  5. The config file name is fixed (`mgr:164-165`).
  6. Config byte SHA vs the manifest (`mgr:171-172`).
  7. Config byte SHA vs the caller's expectation (`mgr:173-174`).
  8. Canonical SHA (`mgr:178-181`).
  9. Config `simulation_id` vs the manifest (`mgr:182-186`).
  10. Cast and context bindings; a `None` binding is skipped (`mgr:191-201`).
  11. Every role binding (`mgr:203-219`).
- Returns the manifest dict with an extra `manifest_sha256` key (`mgr:220-221`).

#### `ensure_dossier_actor_entities(entities, actors)` (`mgr:224-318`) — LOOP-011 cast guarantee
- Uses `extract_actor_rows`, `is_agent_eligible`, `match_actor`, and `normalize_name` from `backend/app/utils/actors.py` (`mgr:236-242`).
- `matched_actor_names` holds the normalized names of dossier rows that some existing entity matches (`mgr:248-253`).
- For each dossier row (`mgr:255-310`):
  - `actor_id` is the row's `actor_id`/`id`, or `"actor_" + sha256(normalized name)[:16]` (`mgr:258-262`).
  - Ineligible rows get `status="context_only"` (`mgr:269-273`).
  - Already-matched rows get `status="candidate"` (`mgr:274-278`).
  - Any other eligible row gets a synthetic `EntityNode`:
    - `uuid = "dossier-" + sha256(actor_id\0name)[:24]`.
    - `labels=["Entity", row.type or "Organization"]`.
    - `summary` = description, role, or "Dossier actor: <name>".
    - `attributes` carry `dossier_actor_id`/`dossier_actor_name` plus `archetype`, `simulation_tier`, `role_class`, and `influence` when present.
    - No edges (`mgr:280-309`).
- Returns `(entities + stand-ins, manifest)`. The manifest is `{schema_version:"actor-cast/v1", dossier_sha256 (canonical; "" if actors is not a dict), dossier_actor_count, eligible_actor_count, decisions[]}` (`mgr:312-318`).

#### `_dossier_uses_current_actor_intelligence(actors)` (`mgr:321-348`)
Returns True if `actors.actor_intelligence_contract.schema_version == "actor-intelligence/v1"` (`mgr:333-339`), or if any actor row has `intelligence.schema_version` equal to v1 (`mgr:343-348`). Non-dict input returns False.

#### `select_agent_pool(entities, actors=None, graph_priors=None)` (`mgr:351-599`)
Returns a new list and does not mutate the input (`mgr:399`). An empty input is returned as-is (`mgr:400-401`).
- Centrality prior: active only when `Config.GRAPH_CENTRALITY_PRIORS` (default true, `backend/app/config.py:1269`) is set and `graph_priors` is a non-empty dict. Names are looked up after `normalize_name`, missing names get 0.0, and the prior contributes `0.5 * centrality` to rank keys (`mgr:405-416,456,480`).
- Caps: `_oasis_max = Config.OASIS_MAX_AGENTS` (default 80, `backend/app/config.py:1354`) and `_cast_max = Config.ACTOR_CAST_MAX` (default 20, `backend/app/config.py:1362`). A bad value falls back to 20 (`mgr:418-422`).
- `_matched` maps `id(entity)` to its dossier row (`mgr:424-425`).
- Rank modes:
  - Salience ranking requires `SIM_SALIENCE_RANKING` and at least one matched row with a dict `salience` (`mgr:427,432-437`).
  - Tier ranking requires `SIM_TIER_ELIGIBILITY` and at least one matched row with `archetype` or `simulation_tier` (`mgr:428,442-449`).
  - Legacy key: `(matched, influence + 0.5*centrality, degree)` (`mgr:451-456`).
  - Full key: `(matched, eligible, salience*tier_weight + 0.5*centrality, influence, degree)`, with tier weights `{1:1.0, 2:0.85, 3:0.5, 4:0.3}` (`mgr:458-481`).
- **Path 1, actor-intelligence/v1 authority** (`mgr:489-522`). Keeps only entities that are matched and eligible, de-duplicated by `actor_id_for(row)` with the best-ranked node kept. It **ignores ACTOR_CAST_MAX and OASIS_MAX_AGENTS** and never adds unmatched graph nodes.
- **Path 2, cast discipline (the default)** (`mgr:525-578`). Applies when `cast_max > 0`, `(oasis_max <= 0 or cast_max < oasis_max)`, and at least one entity matched.
  - Keeps matched and eligible entities.
  - If every matched entity is ineligible, it falls back to keeping all of them with a warning (`mgr:539-546`).
  - De-duplicates alias nodes by the normalized name of the matched actor (`mgr:557-567`).
  - Sorts and truncates to `cast_max` (`mgr:569-571`).
- **Path 3, legacy T3.13** (`mgr:581-599`). Effective cap = min of the positive values among (oasis_max, cast_max). If the pool already fits, it returns everything. Otherwise it keeps every matched entity and fills by rank up to the cap. **No alias de-duplication here.**

#### Enums and `SimulationState` (`mgr:602-724`)
- `SimulationStatus` (`mgr:602-611`): `created|preparing|ready|running|paused|stopped|completed|failed`.
- `PlatformType` (`mgr:614-617`): `twitter|reddit`. Nothing references it.
- `SimulationState` dataclass (`mgr:620-664`), grouped by purpose:
  - Identity: `simulation_id`, `project_id`, `graph_id`.
  - Platforms: `enable_twitter` and `enable_reddit`, both default True.
  - Status and counts: `status`, `entities_count`, `profiles_count`, `entity_types`.
  - Actor-role fields: `actor_role_contract_version`, `actor_role_count`, `actor_cast_manifest_sha256`, `actor_role_manifest_sha256` (dict).
  - Actor-context fields: `actor_context_contract_version`, `actor_context_count`, `actor_context_manifest_sha256`, `actor_context_report_sha256`, `actor_context_actors_sha256`.
  - Config seal: `simulation_config_sha256`, `simulation_config_manifest_sha256`.
  - Config generation: `config_generated`, `config_reasoning`.
  - Run progress: `current_round`, `twitter_status`, `reddit_status`.
  - Bookkeeping: `created_at`, `updated_at`, `error`.
- `to_dict()` (`mgr:666-699`) is the full form persisted to `state.json`. `to_simple_dict()` (`mgr:701-724`) is the API form; it leaves out platforms, `current_round`, timestamps, `actor_cast_manifest_sha256`, and `actor_context_actors_sha256`. [verifier: incomplete list — it also omits `config_reasoning`; "platforms" means both `enable_twitter`/`enable_reddit` and `twitter_status`/`reddit_status` (mgr:701-724 vs mgr:666-699)]

#### `SimulationManager` (`mgr:727-1544`)
- `SIMULATION_DATA_DIR = <services>/../../uploads/simulations`, i.e. `backend/uploads/simulations` (`mgr:739-742`). `__init__` creates the directory and starts a **per-instance** `_simulations` cache (`mgr:744-749`).
- `_get_simulation_dir(id)` (`mgr:751-755`) joins the ID onto the data dir and **always calls `os.makedirs`**, even for read-only lookups.
- `_save_simulation_state(state)` (`mgr:757-770`) bumps `updated_at`, then, while holding `SimulationRunner._run_state_lock` (shared class-level RLock, `run:307`), writes `state.json` with `write_json_atomic` and refreshes the instance cache.
- `_load_simulation_state(id)` (`mgr:772-824`) returns the cached instance if present. Otherwise it reads `state.json` (returns None if absent) and rebuilds `SimulationState` with defaults for missing keys. `json.load` errors propagate.
- `create_simulation(project_id, graph_id, enable_twitter=True, enable_reddit=True)` (`mgr:826-860`) sets `simulation_id = "sim_" + uuid4().hex[:12]`, status CREATED, and saves.

#### `prepare_simulation(...)` (`mgr:862-1316`)
Parameters: `simulation_id`, `simulation_requirement`, `document_text`, `defined_entity_types=None`, `use_llm_for_profiles=True`, `progress_callback=None`, `parallel_profile_count=3`, `actors=None`, `graph_priors=None`, `max_rounds=None`, `research_language=None`. Raises `ValueError` if the state does not exist (`mgr:902-904`). It sets PREPARING and saves (`mgr:907-908`).

1. **Read** (`mgr:913-925`): `ZepEntityReader().filter_defined_entities(graph_id, defined_entity_types, enrich_with_edges=True)`. Progress callbacks are `("reading", 0|30|100, msg)`.
2. **Cast** (`mgr:931-975`):
   - Calls `ensure_dossier_actor_entities`, then `select_agent_pool`.
   - Each selected entity is re-matched to its dossier row, and decisions are marked `selected` with `entity_uuid`.
   - An ineligible-but-selected row gets the reason "selected by the all-context safety fallback".
   - **Any eligible dossier actor left out of the selection raises `RuntimeError("eligible dossier actors missing from simulation cast: ...")`** (`mgr:960-968`).
   - Writes `actor_cast_manifest.json` with `selected_actor_count` and `selected_actor_names` (`mgr:969-975`), then computes `actor_cast_sha`.
3. **Actor context** (`mgr:982-1013`): if any actor rows were selected, calls `build_actor_context_artifacts(sim_dir, actors, rows, document_text)`, which writes `actor_context/` and `actor_context_manifest.json` (`backend/app/services/actor_context.py:1437,1490`). It then immediately runs `validate_actor_context_artifacts` (`mgr:994-1002`) and records the version, count, and SHAs on state. Otherwise those fields are cleared.
4. **Empty gate** (`mgr:1026-1030`): `filtered_count == 0` sets status FAILED with the error "没有找到符合条件的实体…", saves, and **returns** without raising.
5. **Profiles** (`mgr:1046-1144`):
   - Builds `OasisProfileGenerator(graph_id, persona_language="en" if research_language starts with "en" else None)` and attaches the role/context binding SHAs (`mgr:1050-1058`).
   - Profiles are saved in real time to `reddit_profiles.json` when Reddit is enabled, otherwise to `twitter_profiles.csv` (`mgr:1072-1079`).
   - `generate_profiles_from_entities(..., parallel_count, actors, actor_context_packs)` (`mgr:1081-1091`).
   - `last_generation_stats["role_prompts"]` must equal the cast manifest's `selected_actor_count`, else `RuntimeError("actor role coverage mismatch")` (`mgr:1093-1102`).
   - The role contract version comes from `actor_role_prompt.ROLE_CONTRACT_VERSION` (`"actor-role/v2"`, `backend/app/services/actor_role_prompt.py:30`).
   - Saves the Reddit JSON and the Twitter CSV; OASIS requires CSV for Twitter (`mgr:1123-1136`).
6. **Config** (`mgr:1155-1186`): calls `SimulationConfigGenerator().generate_config(...)` with `actors`, `actor_context_packs`, `max_rounds`, and `research_language`.
7. **Audience fill** (`mgr:1193-1221`):
   - Selects `agent_configs` whose `entity_type == SimulationConfigGenerator.AUDIENCE_ENTITY_TYPE` (`"Audience"`, `backend/app/services/simulation_config_generator.py:3803`).
   - Calls `generate_audience_profiles(cfgs, start_user_id=len(profiles))`, appends the results, and re-saves both profile files.
   - Any exception is logged as a warning and skipped, which means audience agents are never activated.
8. Writes `simulation_config.json` with `write_text_atomic` (`mgr:1224-1229`).
9. **Role/context closure** (`mgr:1242-1276`). When `actor_role_count > 0`:
   - Context count must equal role count.
   - Re-validates the context artifacts.
   - For each enabled platform profile, runs `OasisProfileGenerator.validate_role_prompt_manifest` and records the SHA of `<profile stem>_roles.json` in `actor_role_manifest_sha256` (`backend/app/services/oasis_profile_generator.py:2643-2645`).
10. **Seal** (`mgr:1278-1298`): `build_simulation_config_seal`, then `validate_simulation_config_seal(require=True)`.
11. Sets status READY and saves (`mgr:1301-1307`).
- Any exception logs a traceback, sets FAILED with `error=str(e)`, saves, and **re-raises** (`mgr:1309-1316`).

#### `reseal_simulation_config(simulation_id)` (`mgr:1318-1350`)
Rebuilds and re-validates the seal over the current config bytes, using the state's cast/context/role SHAs, then saves the state. The orchestrator uses it after legitimate PREPARE-owned config mutations such as a scenario overlay or a WorldState seed (`backend/app/services/pipeline_orchestrator.py:12925`).

#### `validate_prepared_simulation_config(simulation_id)` (`mgr:1352-1452`)
Read-only re-check used for PREPARE reuse (`backend/app/services/pipeline_orchestrator.py:12747`).
- Discovers `*_profiles_roles.json` and requires each `actor_role_count` to be an `int` ≥ 0 using `type(..) is int`; platforms must agree on count and version (`mgr:1370-1395`).
- Requires state and disk to agree on role count, role version, context manifest presence, and context count (`mgr:1401-1422`).
- Rejects a half-set fingerprint pair (`mgr:1426-1427`).
- "Current actor contract" means any of: context present, a role version other than `actor-role/v1`, or the state's context version equals v1. In that case both fingerprints are required (`mgr:1428-1445`). [verifier: also true when `state.actor_context_count > 0` or any role manifest sets `actor_context_required` (mgr:1428-1441)]
- Delegates to `validate_simulation_config_seal(require=current or any SHA)` (`mgr:1446-1452`).

#### Accessors (`mgr:1454-1544`)
- `get_simulation` (`mgr:1454-1456`) loads the state.
- `list_simulations(project_id=None)` (`mgr:1458-1474`) skips dot-names and non-directories, loads each state, and optionally filters by project.
- `get_profiles(id, platform="reddit")` (`mgr:1476-1507`):
  - Twitter reads `twitter_profiles.csv` via `csv.DictReader`, defensively: any error returns `[]`.
  - Other platforms `json.load` `<platform>_profiles.json` with **no** try/except.
  - Raises `ValueError` if the simulation is missing.
- `get_simulation_config` (`mgr:1509-1518`) returns the parsed `simulation_config.json` or None.
- `get_run_instructions` (`mgr:1520-1544`) returns paths plus `python …/run_{twitter,reddit,parallel}_simulation.py --config <path>` commands, and Chinese instructions saying to use `uv run`.

### B. `backend/app/services/simulation_runner.py`

#### Module header (`run:1-34`)
- Imports `ZepGraphMemoryManager` and `SimulationIPCClient` (`run:24-25`). The `CommandType`, `IPCResponse`, `asyncio`, and `Union` imports are unused.
- Logger: `mirofish.simulation_runner` (`run:27`).
- Module-global `_cleanup_registered` (`run:30`) and `IS_WINDOWS` (`run:33`).

#### Data classes (`run:36-263`)
- `RunnerStatus` (`run:36-45`): `idle|starting|running|paused|stopping|stopped|completed|failed`. PAUSED is never entered (docstring, `run:274-275`).
- `AgentAction` (`run:48-72`): `round_num`, `timestamp`, `platform`, `agent_id`, `agent_name`, `action_type`, `action_args`, `result`, `success`.
- `RoundSummary` (`run:75-98`): **never instantiated**. `SimulationRunState.rounds` stays empty, so `rounds_count` is always 0 (`run:130,262`).
- `SimulationRunState` (`run:101-263`):
  - Progress: `current_round`/`total_rounds`, `simulated_hours`/`total_simulation_hours`.
  - Per-platform: `*_current_round`, `*_simulated_hours`, `*_running`, `*_actions_count`, `*_completed`.
  - Recent actions: `recent_actions`, capped at `max_recent_actions=50` (`run:134`).
  - Timestamps and error: `started_at`, `updated_at`, `completed_at`, `error`.
  - Process tracking: `process_pid`, `process_pgid`.
  - **`twitter_enabled`/`reddit_enabled`**: the authoritative enabled set (`run:150-151`).
  - Graph memory: `graph_memory_requested`, `graph_memory_active`, `graph_memory_error` (`run:154-156`).
  - Truncation: `rounds_truncated_from`/`_to` (`run:160-161`).
  - Resume: `resumed_from_round` (`run:165`).
  - Calendar fields: `temporal_mode`, `calendar_unit`, `current_period_end`, `horizon_date` (`run:170-173`).
  - `options` dict (`run:177`).
  - A non-serialized `_lock: RLock` (`run:185-187`).
  - `add_action` (`run:189-202`) prepends the action under the lock, truncates the list to 50, and bumps the platform counter. Any non-twitter platform counts as reddit.
  - `to_dict`/`_to_dict_unlocked` (`run:204-253`) compute `progress_percent = current/max(total,1)*100` rounded to 1 decimal place. The calendar keys appear only when `temporal_mode` is set, and `options` only when non-empty.
  - `to_detail_dict` (`run:255-263`) adds `recent_actions` and `rounds_count`. This is the form persisted to `run_state.json`.

#### `SimulationRunner` class state (`run:266-307`)
- `RUN_STATE_DIR` is `backend/uploads/simulations`, the same path as `SimulationManager.SIMULATION_DATA_DIR` and `Config.OASIS_SIMULATION_DATA_DIR` (`backend/app/config.py:1080`), each computed independently (`run:279-282`).
- `SCRIPTS_DIR` is `backend/scripts` (`run:285-288`).
- Class dicts (`run:291-302`): `_run_states`, `_run_state_last_save`, `_processes`, `_action_queues`, `_monitor_threads`, `_stdout_files`, `_stderr_files`, `_graph_memory_enabled`.
- `_run_state_lock = threading.RLock()` (`run:307`) is shared with the manager and the API (`backend/app/api/simulation.py:369`).

#### `get_run_state(id)` (`run:309-319`)
Returns the in-memory object if present. Otherwise it calls `_load_run_state` and caches the result. Once cached, it is **never re-read from disk**.

#### `join_monitor_thread(id, timeout=30.0)` (`run:321-338`)
Returns True if there is no thread or the thread has exited, False on timeout. It never raises.

#### `_load_run_state(id)` (`run:340-419`)
- Rebuilds `SimulationRunState` from `run_state.json`.
- When `twitter_enabled`/`reddit_enabled` keys are absent, the fields are set to **`None`**, not `False` (`run:379-386`).
- Restores `recent_actions` (`run:402-414`).
- Any exception logs an error and returns None.

#### `_save_run_state(state, force=False)` (`run:421-448`)
- Always replaces `_run_states[id]` under `_run_state_lock`.
- Writes `run_state.json` with `to_detail_dict()` through `write_json_atomic`, using the default `fsync=True`.
- The write happens when `force` is set, the state is terminal, `interval <= 0`, or `interval` seconds have passed since the last write. `interval = Config.SIM_RUNSTATE_SAVE_INTERVAL`, which **does not exist in `Config`**, so the getattr default 0 applies and every call writes (`run:436-448`).

#### `start_simulation(simulation_id, platform="parallel", max_rounds=None, enable_graph_memory_update=False, graph_id=None, sim_seed=None, resume=None)` (`run:450-986`)
1. **Platform validation**: anything other than `twitter|reddit|parallel` raises `ValueError` (`run:474-477`).
2. **Already-running guard** (`run:482-488`): if the existing state is RUNNING or STARTING **and** `_is_simulation_alive`, it raises "模拟已在运行中". Otherwise it warns and allows the re-run. COMPLETED, STOPPING, FAILED, and STOPPED states are not checked at all.
3. **Config presence**: `uploads/simulations/<id>/simulation_config.json` must exist (`run:491-495`).
4. **Integrity gate (LOOP-011)** (`run:501-759`). Every `OSError`, `ValueError`, `TypeError`, and `JSONDecodeError` is wrapped into `ValueError("角色提示词完整性校验失败: …")`. The checks:
   - Discovers `reddit_profiles_roles.json` and `twitter_profiles_roles.json`, records their byte SHAs, and parses `actor_role_count` (via `int()`, which must be ≥ 0), `role_contract_version`, and `actor_context_required` (`run:514-548`).
   - Platforms must agree on count and version (`run:549-552`).
   - If role manifests exist, `state.json` must exist and must report a matching role count and version (`run:557-574`).
   - Context manifest presence and count must agree with state; context requires roles; a non-v1 role version requires `actor_context_required`; and so on (`run:575-606`).
   - Context fingerprints must be present (`run:607-618`).
   - The state's `actor_role_manifest_sha256` must equal the on-disk SHA set exactly (`run:619-633`).
   - "Current v1 authority" (context > 0, or a role version other than `actor-role/v1`) requires a config seal. It then calls `validate_simulation_config_seal` and captures the manifest SHA for `--config-seal` (`run:634-668`).
   - The cast manifest's `selected_actor_count` must equal the role count (`run:669-683`).
   - When roles exist: the cast manifest SHA must match state (`run:684-688`); context artifacts are re-validated against state SHAs (`run:690-711`); every requested platform must have a role manifest (`run:721-732`); and every prepared platform's role manifest SHA and role-prompt manifest are validated (`run:733-757`).
5. **Resume decision (RUN-7)** (`run:764-786`):
   - The flag is `Config.SIM_RESUME`, default false (`backend/app/config.py:590`).
   - When `resume is None`, it resumes only if the flag is set, a previous state exists, and that state is not COMPLETED. An explicit `resume` overrides.
   - Non-parallel platforms never resume, because the single-platform scripts have no `--resume` argument.
   - `_resume_checkpoint_round` returns the checkpoint round or None.
   - When not resuming, it calls `_rotate_stale_action_logs`.
6. **Round accounting** (`run:788-849`):
   - `total_hours = time_config.total_simulation_hours` (default 72) and `minutes_per_round` (default 60).
   - **Calendar mode** applies when `temporal_config.mode == "calendar"`. Then `total_rounds = temporal_config.n_rounds`, falling back to the hours formula. A positive `max_rounds` is *ignored* for accounting and sets `options.max_rounds_ignored=True` (`run:808-823`).
   - **Hours mode**: `total_rounds = int(total_hours*60/minutes_per_round)`, capped by a positive `max_rounds`, with `rounds_truncated_from`/`_to` recorded (`run:824-833`).
   - Builds a STARTING state and saves it (`run:835-851`).
7. **Graph-memory hook** (`run:854-871`):
   - Records `graph_memory_requested`.
   - If requested without a `graph_id`, it raises `ValueError` *after* the STARTING state was saved.
   - `ZepGraphMemoryManager.create_updater(sim_id, graph_id)` (`backend/app/services/zep_graph_memory_updater.py:655-676`) starts a worker thread. On failure, `graph_memory_active=False` and `graph_memory_error` is set; startup continues.
8. **Script choice** (`run:875-893`): `run_twitter_simulation.py`, `run_reddit_simulation.py`, or `run_parallel_simulation.py`. Sets `*_running=True` and `*_enabled=True` for the chosen platforms. A missing script raises `ValueError`.
9. Creates an unused `Queue` in `_action_queues` (`run:896-897`).
10. **Launch** (`run:907-953`):
    - Command:
      ```
      [sys.executable, <scripts>/<script>, --config <abs sim_dir>/simulation_config.json]
        + [--config-seal <manifest_sha>]   (parallel script only, when a seal was validated)
        + [--max-rounds N]                 (if max_rounds > 0; also passed in calendar mode)
        + [--resume]                       (if resume active)
      ```
    - Opens `simulation.log` in mode `'w'` (truncating it, even on resume) and passes it as stdout, with stderr redirected to stdout.
    - Env is a copy of `os.environ` plus `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`, `SIM_SEED=<int>` (only when `sim_seed` is given), and `SIM_RESUME=true` (when the flag is on or resume is active).
    - `cwd=sim_dir`, `start_new_session=True`.
11. Records `process_pid` and `process_pgid` (via `os.getpgid`; None on Windows), sets RUNNING, saves, and starts the daemon monitor thread `_monitor_simulation` (`run:959-976`).
12. Any exception during launch sets FAILED with `error` and re-raises (`run:980-984`).

#### `_read_log_tail(path, max_bytes=2000)` (`run:988-999`)
Reads the last `max_bytes` bytes, decoded as UTF-8 with replacement. Errors return "".

#### `_missing_platform_completions(state)` (`run:1001-1009`)
Lists enabled platforms that are missing `*_completed`.

#### `_monitor_simulation(id)` (`run:1011-1146`) — daemon thread
- Paths: `<sim>/twitter/actions.jsonl` and `<sim>/reddit/actions.jsonl` (`run:1017-1018`).
- While `process.poll() is None`: tail each existing log, `_save_run_state`, `sleep(2)` (`run:1030-1045`).
- After the process exits it does a final tail (`run:1048-1051`), then resolves the terminal state (`run:1063-1104`):
  - An existing terminal state (COMPLETED, FAILED, or STOPPED) is kept.
  - STOPPING becomes STOPPED.
  - `exit_code == 0` with every enabled platform completed becomes COMPLETED.
  - Anything else becomes FAILED. With `exit_code == 0` the error reads "进程退出码为 0，但启用平台未产出 simulation_end (<platforms>)" plus the log tail. With a non-zero exit code it reads "进程退出码: N, 错误: <2000-byte tail>".
  - [verifier: ordering matters — the final tail (run:1048-1051) runs before `status_before_exit` is read (run:1057), and any `simulation_end` parsed there already promotes STARTING/RUNNING to COMPLETED inside `_read_action_log` (run:1205-1212). So a child that exits non-zero after writing every `simulation_end` is kept COMPLETED, and the `exit_code == 0 and all_platforms_completed` branch (run:1079) is effectively unreachable from STARTING/RUNNING]
- Clears `*_running`, saves, and calls `_mark_env_stopped` (`run:1106-1112`).
- On a thread exception: FAILED with the exception text (`run:1114-1118`).
- `finally` (`run:1120-1146`): if graph memory is enabled, calls `ZepGraphMemoryManager.stop_updater` (which flushes) and pops the flag. It then pops `_processes` and `_action_queues` and closes and pops the stdout/stderr handles. These pops are keyed by `simulation_id` only, not by process identity.

#### `_read_action_log(log_path, position, state, platform)` (`run:1148-1287`)
- Gets the graph updater when enabled (`run:1169-1172`).
- Seeks to `position` and reads line by line (`run:1175-1177`):
  - **`event_type == "simulation_end"`** (`run:1189-1221`), under `state._lock`: sets `<platform>_completed=True` and `<platform>_running=False`. If all enabled platforms are complete **and** the status is STARTING or RUNNING, it sets COMPLETED with `completed_at`. Otherwise it only logs, and never promotes STOPPING, STOPPED, or FAILED.
  - **`round_end`** (`run:1224-1254`), under the lock: per-platform `*_current_round` takes the max, `*_simulated_hours` is overwritten, overall `current_round` takes the max, `simulated_hours = max(both)`, and `current_period_end` advances to the lexicographic max of ISO `period_end`.
  - Any other `event_type` (`simulation_start`, `round_start`, …) is ignored (`run:1256`).
  - Lines without an `event_type` become an `AgentAction`. `state.add_action` is called and `current_round` bumped under the lock. Outside the lock, `graph_updater.add_activity_from_dict(action_data, platform)` is called (`run:1258-1280`).
  - A JSON decode error on a line is silently skipped, **and the position still advances past it** (`run:1282-1284`).
- Returns `f.tell()`. On any other exception it logs a warning and returns the **old** position (`run:1285-1287`).

#### Re-run hygiene (`run:1289-1385`)
- `_STALE_DERIVED_ARTIFACTS` (`run:1292-1307`): `run_summary.json`, `world_state_trajectory.json`, `decisions.jsonl`, `emergent_metrics.json`, `twitter_/reddit_emergent_metrics.json`, `twitter_/reddit_dynamics_summary.json`, `ipc_telemetry.jsonl`, `llm_health.json`, `llm_fallback.jsonl`, `sim_llm_telemetry.json`.
- `_rotate_stale_action_logs(sim_dir)` (`run:1309-1337`): renames `<plat>/actions.jsonl` → `actions.prev.jsonl` and `<plat>/checkpoint.json` → `checkpoint.prev.json`, and renames each derived artifact → `<name>.prev`. Only the latest `.prev` is kept, because `os.replace` overwrites. OSError only produces a warning. It does **not** touch the SQLite DBs; the script recreates them.
- `_current_config_hash(sim_dir)` (`run:1339-1354`): `sha256(json.dumps(config, ensure_ascii=False, sort_keys=True, default=str))`. This is byte-identical to the script's `_config_hash` (`backend/scripts/run_parallel_simulation.py:3764-3773`). Errors return "".
- `_resume_checkpoint_round(sim_dir)` (`run:1356-1385`): returns the max `completed_round` ≥ 1 across `<plat>/checkpoint.json`. A platform is skipped when its `config_hash` is non-empty and differs from the current config hash. Corrupt files are skipped. Returns None when nothing is usable.

#### `_check_all_platforms_completed(state)` (`run:1387-1416`)
- The enabled set comes from `state.*_enabled`.
- If both are falsy (False or legacy None), it falls back to "`<plat>/actions.jsonl` exists" (`run:1404-1407`).
- Returns False if any enabled platform is incomplete. Otherwise it returns True only if at least one platform is enabled.

#### Process identity and orphan reclaim (`run:1418-1566`)
- `_RUN_SCRIPT_NAMES` (`run:1419-1423`) lists the three script file names.
- `_orphan_cmdline(pid)` (`run:1425-1439`) runs `ps -p <pid> -o command=` with a 5 s timeout. It returns None on Windows or on failure.
- `_pid_is_our_simulation(pid, sim_id)` (`run:1441-1455`): the command line must contain a script name **and** the `simulation_id`; the absolute `--config` path contains it. On Unix, an unknown command line returns False (conservative). On Windows it falls back to `os.kill(pid, 0)` liveness.
- `_is_simulation_alive(state)` (`run:1457-1471`): an own `Popen` that is alive returns True. Otherwise it needs a persisted pid that passes `os.kill(pid, 0)` and the identity check.
- `_kill_orphan_simulation(state)` (`run:1473-1517`):
  - Returns True when there is no pid, the pid is dead, or the pid belongs to another process.
  - On Unix: `killpg(pgid or getpgid(pid), SIGTERM)`, `sleep(1.0)`, then SIGKILL if the process is still alive.
  - On Windows: `taskkill /F /T`.
  - Returns True only if the pid is gone at the end.
- `reconcile_orphans()` (`run:1519-1566`):
  - **Port probe**: when `Config.SIMULATION_RECLAIM_PORT_PROBE` (default true, `backend/app/config.py:498-500`) is set, it TCP-connects to `127.0.0.1:$FLASK_PORT` (default 5001) with a 0.2 s timeout. If something answers, another backend is running and it returns without reclaiming anything (`run:1531-1543`).
  - For every directory under `RUN_STATE_DIR` that is not in `_processes`: if `run_state.runner_status` is RUNNING, STARTING, STOPPING, or PAUSED, it kills the orphan, sets FAILED with `error="后端在运行中被中断（进程重启），该模拟已回收为失败。"`, saves, syncs `state.json` status to `failed`, and marks the env stopped. [verifier: "kills" is overstated — the boolean from `_kill_orphan_simulation` is discarded (run:1553), so the run is marked FAILED and env stopped even when the kill could not be confirmed (run:1513-1515) or the pid failed the identity check and was left alone (run:1493-1494)]
  - Errors are logged per simulation and never propagate.
  - Called at app start (`backend/app/__init__.py:131`) unless `TESTING` or `DRF_TEST_PROCESS=1` (`backend/app/__init__.py:122-125`).

#### `_mark_env_stopped(id)` (`run:1568-1589`)
If the sim dir exists, atomically writes `env_status.json = {status:"stopped", twitter_available:false, reddit_available:false, timestamp}`. It never raises.

#### `_sync_state_json_status(id, status)` (`run:1591-1606`)
A read-modify-write of `state.json` (`status`, `updated_at`) under `_run_state_lock`, using an atomic write. It does nothing if the file is missing.

#### `_terminate_process(process, id, timeout=10)` (`run:1608-1662`)
- Windows: `taskkill /PID /T`, wait up to `timeout`, then `taskkill /F /T`. If taskkill fails, it falls back to `terminate()`/`kill()`.
- Unix: `killpg(getpgid(pid), SIGTERM)`, `wait(timeout)`, then `killpg(SIGKILL)` and `wait(5)`.

#### `stop_simulation(id)` (`run:1664-1730`)
- Raises `ValueError` if the state is missing or the status is not RUNNING, PAUSED, or STARTING. **COMPLETED cannot be stopped**, even while the command-mode process is alive (`run:1667-1674`).
- Sets STOPPING and saves.
- Then:
  - With a live `Popen`: `_terminate_process`. If that throws, it falls back to `terminate()`/`kill()`.
  - With a `Popen` that has already exited: counted as terminated.
  - With no `Popen`: `_kill_orphan_simulation` (`run:1680-1705`).
- If termination is confirmed: STOPPED, `*_running=False`, `completed_at`, and `_mark_env_stopped`. Otherwise: **FAILED** with "停止失败：进程仍可能存活（无法确认终止）。" (`run:1707-1717`). [verifier: "confirmed" is weaker than it sounds — after `_terminate_process` raises, a successful `process.kill()` sets `terminated=True` without any wait (run:1695-1697); the orphan path returns True for `process_pid=None` or a pid that fails the identity check without killing anything (run:1481-1494), and uses a 1 s SIGTERM grace rather than the 10 s Popen grace (run:1501-1506 vs run:1654-1661)]
- Saves, then stops the graph updater if one was enabled (`run:1718-1727`).
- It does **not** touch `state.json`. The API sets it to `PAUSED` (`backend/app/api/simulation.py:1721`).

#### Action-history readers (`run:1732-2023`)
- `_read_actions_from_file(file_path, default_platform, platform_filter, agent_id, round_num)` (`run:1732-1799`) reads the whole file. It skips lines with an `event_type` and lines without `agent_id`, takes the platform from the record or `default_platform`, applies filters, and skips JSON errors.
- `get_all_actions(id, platform=None, agent_id=None, round_num=None)` (`run:1801-1860`) reads the per-platform files. If nothing is found, it falls back to the legacy root `actions.jsonl`. It sorts by `timestamp` string, newest first.
- `get_actions(..., limit=100, offset=0)` (`run:1862-1894`) slices `get_all_actions` after a **full read**.
- `get_timeline(id, start_round=0, end_round=None)` (`run:1896-1973`) groups by round: twitter/reddit counts, the active-agent set, `action_types` counts, and min/max timestamps, compared as strings (XRUN-9). Output is sorted by round.
- `get_agent_stats(id)` (`run:1975-2023`) gives per-agent totals, per-platform counts, `action_types`, and first/last timestamps, sorted by `total_actions` descending.

#### `write_run_summary(id, communities=None)` (`run:2025-2298`)
- Inputs: `get_agent_stats`, `get_timeline`, `get_all_actions`. On failure it returns None (`run:2037-2045`).
- `action_volume_by_round` (`run:2048-2056`).
- `top_posts` (`run:2062-2082`): the first 25 `CREATE_POST`/`QUOTE_POST` actions with `round_num > 0` and no `is_scheduled_event`, sorted by (round, timestamp) ascending, with content truncated to 280 characters and the timestamp dropped. This is a chronological sample, not an engagement ranking (RUN-13).
- `peak_round` is the max of `total_actions` (`run:2084`). [verifier: `peak_round` is the whole `action_volume_by_round` bucket dict `{round_num, total_actions, active_agents_count, action_types}` with the largest `total_actions` (or None), not a number (run:2048-2056,2084)]
- Organic actions: `{CREATE_POST, QUOTE_POST, REPOST, CREATE_COMMENT, LIKE_POST, LIKE_COMMENT, DISLIKE_POST, DISLIKE_COMMENT}` with `round > 0` and not scheduled. `seed_count = total - organic` (`run:2092-2104`).
- Reads `run_state.json` **from disk** for `current_round`, `total_rounds` (or `total_simulation_rounds`), `error`, and `current_period_end` (`run:2106-2121`).
- `rounds_executed = current_round` if it is an int, else the number of timeline buckets. `truncated = current < total` (`run:2122-2124`).
- `simulation_health` (`run:2125-2132`): `errored` if the run state has an error, else `hollow` if the organic count is 0, else `truncated`, else `ok`. If any platform in `llm_health.json` is `degraded`, `ok` becomes `llm_degraded` (`run:2136-2147`).
- `agent_dynamics` comes from `<plat>_dynamics_summary.json` (`run:2151-2161`).
- `simulated_hours = agent_dynamics.simulated_hours_from_rounds(rounds_executed, config.time_config.minutes_per_round)`, defaulting to 60 minutes (`run:2166-2187`).
- When `SIM_ORGANIC_RATIO_DETECTOR` is on (default true), it builds per-platform, per-round post/comment/like buckets, excluding `is_engagement_sample`, and calls `detect_organic_ratio_collapse(buckets, SIM_ORGANIC_RATIO_MIN_CONSECUTIVE=3)` (`run:2192-2213`).
- Summary keys (`run:2215-2231`): `simulation_id`, `agent_count`, `total_actions`, `organic_action_count`, `seed_action_count`, `rounds_executed`, `simulated_hours`, `rounds_with_organic_actions`, `total_rounds`, `truncated`, `simulation_health`, `peak_round`, `top_agents` (the first 15 entries of `agent_stats`), `action_volume_by_round`, `top_posts`.
- Calendar mode adds `temporal_mode`, `calendar_unit`, `total_periods`, `simulated_span_days`, `horizon_date`, `horizon_source`, `horizon_defaulted`, and `coverage_end`. `coverage_end` is `current_period_end`, or else `round_dates[rounds_executed-1].period_end` (`run:2234-2263`).
- Optional keys: `error` (300 characters), `llm_health`, `agent_dynamics`, `communities`, `organic_ratio_warnings` (`run:2264-2274`).
- Writes `run_summary.json` via `.tmp` + `os.replace` (no fsync). Write failures only warn. Returns the dict (`run:2276-2298`).

#### `cleanup_simulation_logs(id)` (`run:2300-2385`)
- Force-restart cleanup. It deletes `run_state.json`, `simulation.log`, `stdout.log`, `stderr.log`, `twitter_simulation.db`, `reddit_simulation.db`, `env_status.json`, every derived artifact and its `.prev`, and `<plat>/{actions.jsonl, actions.prev.jsonl, checkpoint.json, checkpoint.prev.json}`. It then drops `_run_states[id]`.
- It keeps the config, profiles, manifests, and `ipc_*` directories.
- Returns `{success, cleaned_files, errors}`. Called by the API's force path (`backend/app/api/simulation.py:1604`).

#### Shutdown (`run:2387-2579`)
- `cleanup_all_simulations()` (`run:2390-2494`):
  - Runs once per process (`_cleanup_done`, `run:2388,2398-2400`), and silently does nothing if there are no processes and no updaters.
  - Calls `ZepGraphMemoryManager.stop_all()` and clears the flags.
  - For each live `Popen`: pre-publishes STOPPING with `error="服务器关闭，模拟被终止"` unless the state is already terminal (`run:2429-2438`); `_terminate_process(timeout=5)`; marks STOPPED only if the state was not terminal; syncs `state.json` to the durable status; and marks the env stopped (`run:2455-2468`).
  - Closes handles and clears `_processes` and `_action_queues`.
- `register_cleanup()` (`run:2496-2579`):
  - Runs once (module global).
  - In Flask debug mode it registers only in the reloader child (`WERKZEUG_RUN_MAIN=='true'`) (`run:2511-2517`).
  - Registers `atexit` and signal handlers for SIGTERM, SIGINT, and SIGHUP (Unix). The handler calls the cleanup, then chains to the original handler.
  - Chaining for SIGHUP: an original handler of `SIG_DFL` leads to `sys.exit(0)`. [verifier: any non-callable original, including `SIG_IGN`, leads to `sys.exit(0)` (run:2540-2546). The handler is installed unconditionally (run:2573-2574), so a backend started under `nohup` (SIGHUP ignored) now cleans up all simulations and exits on SIGHUP]
  - Chaining for other signals: if the original was `SIG_IGN`, the handler returns. Otherwise it resets the signal to `SIG_DFL` and re-sends it to itself with `os.kill(getpid(), signum)` (`run:2547-2561`). [verifier: refuted — the check is `signal.getsignal(signum) is signal.SIG_IGN`, which reads the *current* disposition; at that point it is `cleanup_handler` itself (installed at run:2569-2574), so an original SIG_IGN is never honored and the handler always resets to SIG_DFL and re-sends (run:2554-2558)]
  - When not on the main thread, a `ValueError` limits it to atexit only.
  - Called from `backend/app/__init__.py:129` and `backend/app/services/pipeline_orchestrator.py:7873`. [verifier: `pipeline_orchestrator.py:7873` is a docstring line inside `PipelineOrchestrator.register_cleanup` (def at :7870) that mentions this method; it does not call it. The only caller is `backend/app/__init__.py:129`]
- `get_running_simulations()` (`run:2581-2590`) lists IDs whose own `Popen` is alive.

#### Interview helpers (`run:2592-3021`)
- `check_env_alive(id)` (`run:2594-2610`): False if the sim dir is missing. Otherwise `SimulationIPCClient(sim_dir).check_env_alive()`. Constructing the client **creates `ipc_commands/` and `ipc_responses/`**.
- `get_env_status_detail(id)` (`run:2612-2646`): reads `env_status.json`, defaulting to stopped/false/None.
- `interview_agent(id, agent_id, prompt, platform=None, timeout=60.0)` (`run:2648-2710`):
  - Raises `ValueError` if the sim is missing or the env is not alive.
  - Calls `send_interview`, which may raise `TimeoutError`; that is not caught here.
  - Returns `{success:True, agent_id, prompt, result, timestamp}` when the response status is `completed`. Otherwise `{success:False, …, error, timestamp}`.
- `_scale_interview_timeout(timeout, n)` (`run:2712-2737`):
  - `per_agent = Config.INTERVIEW_TIMEOUT_PER_AGENT` (default 30, `backend/app/config.py:601`).
  - If `per_agent <= 0` or `n <= 0`, the timeout is returned unchanged.
  - Provider = env `LLM_PROVIDER` or `Config.LLM_PROVIDER` or `claude-cli`.
  - `cap = env OASIS_CLI_SEMAPHORE` (default '8') for `claude-cli`/`codex-cli`, otherwise `env OASIS_SEMAPHORE` (default **'30'**). A non-integer value sets 8.
  - `concurrency = max(1, cap//2)`.
  - Returns `max(timeout, 60 + per_agent*ceil(n/concurrency))`.
- `interview_agents_batch(id, interviews, platform=None, timeout=120.0)` (`run:2739-2802`) runs the same liveness check, scales the timeout (never down), calls `send_batch_interview`, and returns `{success, interviews_count, result|error, timestamp}`.
- `interview_all_agents(id, prompt, platform=None, timeout=180.0)` (`run:2804-2862`) builds `[{agent_id, prompt}]` from `simulation_config.json.agent_configs[*].agent_id`, which includes audience agents, and delegates to the batch call. It raises `ValueError` when the config or agents are missing.
- `close_simulation_env(id, timeout=30.0)` (`run:2864-2910`): if the env is not alive, returns `{success:True, message:"环境已经关闭"}`. Otherwise it calls `send_close_env`. **A `TimeoutError` is also reported as `success:True`.**
- `_get_interview_history_from_db(db_path, platform_name, agent_id=None, limit=100)` (`run:2912-2968`) uses SQLite: `SELECT user_id, info, created_at FROM trace WHERE action='interview' [AND user_id=?] ORDER BY created_at DESC LIMIT ?`. It parses `info` JSON into `{agent_id, response, prompt, timestamp, platform}`. Errors are logged and return a partial result.
- `get_interview_history(id, platform=None, agent_id=None, limit=100)` (`run:2970-3021`) queries `<plat>_simulation.db` for one or both platforms, sorts by timestamp descending, and limits the total only when both platforms were queried.

### C. `backend/app/services/simulation_ipc.py`

#### Module helpers (`ipc:1-115`)
- `_CANCEL_SUFFIX=".cancel"` and `_PROCESSING_SUFFIX=".processing"` (`ipc:27-28`). `_IPC_TELEMETRY_FILENAME="ipc_telemetry.jsonl"` (`ipc:33`).
- `_ipc_telemetry_enabled()` (`ipc:36-46`) returns `Config.IPC_TELEMETRY_ENABLED`. The docstring says "默认关" (default off), but **Config defaults it to True** (`backend/app/config.py:358`). Import errors return False.
- `_append_jsonl(path, record)` (`ipc:49-62`) is a best-effort append. It swallows `OSError`, `TypeError`, and `ValueError`.
- `_percentile(sorted, pct)` (`ipc:65-79`) uses the nearest-rank method.
- `_MIN_STALE_SWEEP_SECONDS = 300.0` (`ipc:84`). `_sweep_stale_files(dir, max_age)` (`ipc:87-114`) removes `*.json`, `*.cancel`, and `*.processing` files whose mtime is older than `max_age`. It does not match `.tmp-*` temp files.

#### Wire types (`ipc:117-184`)
- `CommandType` (`ipc:117-121`): `interview|batch_interview|close_env`.
- `CommandStatus` (`ipc:124-129`): `pending|processing|completed|failed`.
- `IPCCommand` (`ipc:132-155`): `{command_id, command_type, args, timestamp}`.
- `IPCResponse` (`ipc:158-184`): `{command_id, status, result, error, timestamp}`. `from_dict` raises `KeyError` or `ValueError` on malformed data.

#### `SimulationIPCClient(simulation_dir)` (`ipc:187-544`) — backend side
- `__init__` (`ipc:194-207`): `commands_dir=<sim>/ipc_commands`, `responses_dir=<sim>/ipc_responses`; both are created.
- `send_command(command_type, args, timeout=60.0, poll_interval=0.5)` (`ipc:209-341`):
  1. Sweeps both directories for files older than `max(2*timeout, 300 s)` (`ipc:234-236`).
  2. `command_id = uuid4()`. Writes `ipc_commands/<id>.json` atomically (`ipc:238-255`).
  3. Polls `ipc_responses/<id>.json` every 0.5 s until `timeout` (`ipc:263-306`). Once the response is found and parsed, it deletes `<id>.json`, `<id>.processing`, `<id>.cancel`, and the response; records telemetry (`completed` or `failed`); and returns the `IPCResponse`.
     - A `JSONDecodeError` or `KeyError` while parsing logs a warning and keeps polling.
     - A `ValueError` from an unknown `status` is **not caught**.
  4. On timeout: records telemetry `timeout`; writes `<id>.cancel` atomically, containing `{command_id, cancelled_at}`; removes `<id>.json`; raises `TimeoutError` (`ipc:308-341`).
- `send_interview(agent_id, prompt, platform=None, timeout=60.0)` (`ipc:343-376`): args `{agent_id, prompt[, platform]}`.
- `send_batch_interview(interviews, platform=None, timeout=120.0)` (`ipc:378-406`): args `{interviews[, platform]}`.
- `send_close_env(timeout=30.0)` (`ipc:408-422`): empty args.
- `check_env_alive()` (`ipc:424-439`): `env_status.json.status == "alive"`. A missing or bad file returns False.
- `_record_ipc_telemetry(...)` (`ipc:441-472`) appends `{ts, command_id, command_type, agent_id, platform, latency_ms (1 dp), status, poll_count, timeout_s}` to `<sim>/ipc_telemetry.jsonl`.
- `summarize(simulation_dir)` (classmethod, `ipc:474-544`) returns `{count, completed, failed, timeout, timeout_rate, p50_ms, p95_ms, by_command{...}}`. A missing or unreadable file returns zero values. **No production or test caller.**

#### `SimulationIPCServer(simulation_dir)` (`ipc:547-732`) — intended script side, **unused**
- `start()` (`ipc:577-582`) sweeps and sets env status `alive`. `stop()` (`ipc:584-589`) sweeps and sets `stopped`. `_update_env_status` (`ipc:591-597`) writes `{status, timestamp}` atomically, with no `*_available` keys.
- `poll_commands()` (`ipc:599-672`):
  - Lists `*.json` sorted by mtime.
  - If a `.cancel` exists, deletes the command and the marker.
  - Atomically claims the command with `os.rename(<id>.json → <id>.processing)`, then re-checks for `.cancel`.
  - Parses and returns an `IPCCommand`. A corrupt claim file is deleted.
- `send_response(response)` (`ipc:674-716`):
  - If `.cancel` exists, or neither `<id>.json` nor `<id>.processing` exists, the client is gone: it cleans up the markers and writes nothing.
  - Otherwise it writes `ipc_responses/<id>.json` atomically and deletes the command, claim, and cancel files.
- `send_success`/`send_error` (`ipc:718-732`) are wrappers.
- The real scripts **do not use this class**:
  - `backend/scripts/run_parallel_simulation.py:840-939` has its own `ParallelIPCHandler`. It reads commands in place without a `.processing` claim, honors `.cancel`, and writes `env_status` with `twitter_available`/`reddit_available`.
  - `backend/scripts/run_twitter_simulation.py:153-212` and `backend/scripts/run_reddit_simulation.py:153` have an `IPCHandler` with non-atomic writes and no `.cancel` handling.
  - The class is only re-exported by `backend/app/services/__init__.py:31-33`.

---

## Control flow

```
create  : API POST /create (backend/app/api/simulation.py:217-218) or orchestrator (pipeline_orchestrator.py:8774, :12776)
          → SimulationManager.create_simulation (mgr:826) → state.json{status:created}
prepare : SimulationManager.prepare_simulation (mgr:862)  [API backend/app/api/simulation.py:619; orchestrator :8790, :12811]
          PREPARING → read entities → ensure_dossier_actor_entities (mgr:931) → select_agent_pool (mgr:938)
          → actor_cast_manifest.json (mgr:973) → build/validate actor context (mgr:986-1002)
          → profiles (mgr:1081) + role coverage check (mgr:1099) → save profiles (mgr:1123-1136)
          → SimulationConfigGenerator.generate_config (mgr:1165) → audience profiles (mgr:1193-1221)
          → simulation_config.json (mgr:1226) → role manifests SHAs (mgr:1242-1274)
          → seal + validate (mgr:1278-1298) → READY (mgr:1301)
(orch)  : optional config mutation → reseal_simulation_config (mgr:1318; orchestrator :12925)
          PREPARE reuse → validate_prepared_simulation_config (mgr:1352; orchestrator :12747)
start   : SimulationRunner.start_simulation (run:450) [orchestrator :12989/:8808; API backend/app/api/simulation.py:1640]
          already-running guard (run:482) → integrity gate (run:501-759) → resume decision/rotate (run:764-786)
          → round accounting (run:788-849) → STARTING saved (run:851) → graph updater (run:854-871)
          → Popen (run:943) → RUNNING saved (run:965-967) → monitor thread (run:970-976)
monitor : _monitor_simulation (run:1011) every 2 s: _read_action_log ×2 (run:1032-1041) + _save_run_state (run:1044)
          simulation_end on all enabled platforms → COMPLETED while process still alive (run:1205-1212)
          orchestrator poll loop sees COMPLETED (pipeline_orchestrator.py:13049) → join_monitor_thread(30 s) + stop_updater
          (pipeline_orchestrator.py:13085-13097) → write_run_summary via _publish_run_summary (pipeline_orchestrator.py:10108)
          [verifier: the join + stop_updater fence runs only when sim_graph_feedback is pinned on (default
          SIM_GRAPH_FEEDBACK=false) and graph_id is set (pipeline_orchestrator.py:13082-13083)]
command : subprocess enters command-wait mode (backend/scripts/run_parallel_simulation.py:6029-6070), env_status=alive;
          report agent interviews → interview_agents_batch (run:2739) → SimulationIPCClient.send_batch_interview (ipc:378)
          → send_command (ipc:209) file mailbox; subprocess exits on close_env or after SIM_IDLE_CLOSE_MIN (default 60 min,
          backend/app/config.py:588) idle → monitor post-exit branch keeps COMPLETED (run:1063-1073), env_status=stopped (run:1112)
stop    : stop_simulation (run:1664) → STOPPING → terminate pgroup (run:1608) → STOPPED / FAILED
restart : app start → register_cleanup (run:2496) + reconcile_orphans (run:1519) [backend/app/__init__.py:129-131]
shutdown: SIGTERM/SIGINT/SIGHUP/atexit → cleanup_all_simulations (run:2390)
force   : API force restart → stop_simulation + cleanup_simulation_logs (backend/app/api/simulation.py:1592,1604)
```

Notes on ordering:
- The orchestrator's RUN poll loop works like this (`backend/app/services/pipeline_orchestrator.py:13001-13060`):
  - It polls `get_run_state` every 5 s, and exits on COMPLETED (`:13049`) or raises on FAILED/STOPPED (`:13051`).
  - An inline stall check and an independent disk watchdog thread (`_spawn_run_stall_watchdog`, `:9113`) both call `stop_simulation` after `PIPELINE_RUN_STALL_S` (default 1800 s) without round progress. The watchdog reads `run_state.json` from disk, which stays fresh only because the save interval is effectively 0 (`run:436`).
- **Lifecycle split**: COMPLETED means "simulation result is authoritative" (`run:1200-1204`). It does not mean the process exited.
  - The parallel script stays alive for interviews until `close_env`, the idle timeout, a stop, or server cleanup.
  - `join_monitor_thread(timeout=30)` therefore usually times out while graph feedback is on. The orchestrator logs a warning and continues (`backend/app/services/pipeline_orchestrator.py:13085-13090`).

---

## Data & artifacts

All paths live under `backend/uploads/simulations/<sim_id>/` (`mgr:739-742`, `run:279-282`).

| Path | Writer (anchor) | Reader(s) | Format / key fields |
|---|---|---|---|
| `state.json` | `_save_simulation_state` (`mgr:757-770`), `_sync_state_json_status` (`run:1591-1606`), API (`backend/app/api/simulation.py:369`) | manager load (`mgr:772`), runner gate (`run:501-508`) | `SimulationState.to_dict()` (`mgr:666-699`) |
| `actor_cast_manifest.json` | `prepare_simulation` (`mgr:971-973`) | seal (`mgr:77-98`), runner gate (`run:669-688`) | `{schema_version:"actor-cast/v1", dossier_sha256, dossier_actor_count, eligible_actor_count, decisions[{actor_id, actor_name, eligible, synthetic_entity, status, reason, entity_uuid?}], selected_actor_count, selected_actor_names}` (`mgr:312-318,969-970`) |
| `actor_context_manifest.json`, `actor_context/` | `build_actor_context_artifacts` (`backend/app/services/actor_context.py:1437,1490`) | seal, gate | external format (actor_context slice) |
| `reddit_profiles.json` | profile generator (`mgr:1075,1124-1128,1205-1210`) | scripts; `get_profiles` (`mgr:1501-1507`) | JSON list |
| `twitter_profiles.csv` | profile generator (`mgr:1078,1132-1136,1211-1216`) | scripts; `get_profiles` (`mgr:1487-1499`) | CSV (OASIS requirement) |
| `{reddit,twitter}_profiles_roles.json` | `OasisProfileGenerator` (`backend/app/services/oasis_profile_generator.py:2643-2645`) | seal (`mgr:100-116`), gate (`run:518-548,733-757`), `validate_prepared…` (`mgr:1370-1391`) | `{actor_role_count:int, role_contract_version, actor_context_required, …}` |
| `simulation_config.json` | `prepare_simulation` (`mgr:1225-1226`) (and orchestrator mutations) | runner (`run:788-849`), scripts, `interview_all_agents` (`run:2834-2843`), `write_run_summary` (`run:2171-2179`) | `time_config.{total_simulation_hours, minutes_per_round}`, `temporal_config.{mode, n_rounds, unit, horizon_date, as_of_date, round_dates[].period_end, horizon_source, horizon_defaulted}`, `agent_configs[].{agent_id, entity_type}` |
| `simulation_config_manifest.json` | `build_simulation_config_seal` (`mgr:126-133`) | `validate_simulation_config_seal` (`mgr:146`); script re-validates (`backend/scripts/run_parallel_simulation.py:1336-1337`) | `simulation-config-manifest/v1` (`mgr:118-125`) |
| `run_state.json` | `_save_run_state` (`run:447`) | `_load_run_state` (`run:343`), `write_run_summary` (`run:2112-2119`), orchestrator disk watchdog | `SimulationRunState.to_detail_dict()` (`run:209-263`) |
| `simulation.log` | subprocess stdout+stderr (`run:924-947`) | `_read_log_tail` (`run:1087-1088`) | text; truncated per launch |
| `twitter/actions.jsonl`, `reddit/actions.jsonl` | scripts (`backend/scripts/action_logger.py:80-130`) | monitor (`run:1017-1051`), history readers (`run:1825-1855`) | JSONL; actions `{round, timestamp, agent_id, agent_name, action_type, action_args, result?, success?, platform?}`; events `{event_type: simulation_start|round_end{round, simulated_hours?, period_end?, actions_count}|simulation_end{total_rounds, total_actions}}` |
| `<plat>/checkpoint.json` | script (when `SIM_CHECKPOINT`) | `_resume_checkpoint_round` (`run:1370-1384`) | `{completed_round, config_hash, …}` |
| `*.prev` (actions/checkpoints/derived) | `_rotate_stale_action_logs` (`run:1309-1337`) | human forensics | one generation kept |
| `twitter_simulation.db`, `reddit_simulation.db` | OASIS in subprocess (cwd=sim_dir, `run:945`) | `_get_interview_history_from_db` (`run:2912-2968`) | SQLite; `trace(user_id, action, info, created_at)` |
| `env_status.json` | script handler (`backend/scripts/run_parallel_simulation.py:872-879`), `_mark_env_stopped` (`run:1582-1587`), unused `SimulationIPCServer` (`ipc:591-597`) | `check_env_alive` (`ipc:424-439`), `get_env_status_detail` (`run:2612-2646`) | `{status:"alive"|"stopped", twitter_available?, reddit_available?, timestamp}` |
| `ipc_commands/<uuid>.json` (+ `.cancel`, `.processing`) | client (`ipc:254-255,325-330`) | script handler | `IPCCommand` (`ipc:140-146`) |
| `ipc_responses/<uuid>.json` | script handler | client (`ipc:260-268`) | `IPCResponse` (`ipc:167-174`) |
| `ipc_telemetry.jsonl` | client (`ipc:441-472`) | `summarize` (unused) | JSONL telemetry rows |
| `run_summary.json` | `write_run_summary` (`run:2276-2283`) | orchestrator `_publish_run_summary` (`backend/app/services/pipeline_orchestrator.py:10100-10112`), report stage | see `run:2215-2274` |
| `llm_health.json`, `<plat>_dynamics_summary.json` | scripts | `write_run_summary` (`run:2136-2161`) | `{platforms:{<p>:{degraded,…}}}` / dict |

In-memory structures:
- Manager: one `_simulations` cache per `SimulationManager` instance (`mgr:749`). The API creates a fresh instance per request (`backend/app/api/simulation.py:217,455,795,…`).
- Runner: class-level dicts (`run:291-302`), plus the `_run_state_lock` RLock (`run:307`), the `SimulationRunState._lock` RLock per state (`run:185-187`), and the `_cleanup_done` flag (`run:2388`).
- Graph memory: `ZepGraphMemoryManager._updaters` (`backend/app/services/zep_graph_memory_updater.py:651`).

---

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `SIM_RESUME` | false | Auto-resume a non-COMPLETED run from its checkpoint (parallel only); also injects `SIM_RESUME=true` into the child env | `backend/app/config.py:590`; `run:764-781,938-939` |
| `SIM_RUNSTATE_SAVE_INTERVAL` | **not defined in Config** → 0 | Would throttle `run_state.json` writes; today every save writes | `run:436-448` |
| `SIMULATION_RECLAIM_PORT_PROBE` | true | Skip orphan reclaim if `127.0.0.1:$FLASK_PORT` answers | `backend/app/config.py:498-500`; `run:1531-1543` |
| `FLASK_PORT` (env) | 5001 | Port used by the reclaim probe | `run:1534` |
| `INTERVIEW_TIMEOUT_PER_AGENT` | 30 | Batch interview timeout scaling; ≤0 disables | `backend/app/config.py:601`; `run:2722-2726` |
| `LLM_PROVIDER` (env, then Config) | `claude-cli` | Selects which semaphore sizes the interview concurrency | `run:2727`; `backend/app/config.py:750` |
| `OASIS_CLI_SEMAPHORE` (env) | '8' | Interview concurrency for CLI providers (`cap//2`) | `run:2730`; `backend/app/config.py:1088` |
| `OASIS_SEMAPHORE` (env) | runner falls back to **'30'** (Config default is 24) | Interview concurrency for HTTP providers | `run:2732`; `backend/app/config.py:1091` |
| `IPC_TELEMETRY_ENABLED` | **True** | Append per-command telemetry to `ipc_telemetry.jsonl` | `backend/app/config.py:358`; `ipc:36-46` |
| `ACTOR_CAST_MAX` | 20 | Cast cap and path selection in `select_agent_pool` (ignored under v1) | `backend/app/config.py:1362`; `mgr:419-422,525-529` |
| `OASIS_MAX_AGENTS` | 80 | Path selection and legacy cap | `backend/app/config.py:1354`; `mgr:418,581` |
| `GRAPH_CENTRALITY_PRIORS` | true | Adds 0.5×centrality to rank keys | `backend/app/config.py:1269`; `mgr:405-416` |
| `SIM_SALIENCE_RANKING` | True | Salience-weighted rank key (only when salience is present) | `backend/app/config.py:1516`; `mgr:427,435` |
| `SIM_TIER_ELIGIBILITY` | True | Tier eligibility flag in the rank key | `backend/app/config.py:1513`; `mgr:428,447` |
| `ACTOR_EXCLUDE_MEDIA` | true | Indirect: media actors become tier 3 and fail `is_agent_eligible` | `backend/app/config.py:1368`; docstring `mgr:365-372` |
| `SIM_AUDIENCE_AGENTS` | 0 | Indirect: the config generator emits Audience agents; manager adds rule-based profiles | `backend/app/config.py:1372-1374`; `mgr:1188-1221` |
| `SIM_ORGANIC_RATIO_DETECTOR` / `SIM_ORGANIC_RATIO_MIN_CONSECUTIVE` | true / 3 | Organic collapse warnings in `run_summary` | `backend/app/config.py:626-627`; `run:2192-2213` |
| `SIM_IDLE_CLOSE_MIN` (script side) | 60 | How long the subprocess lingers in command mode after COMPLETED | `backend/app/config.py:588`; `backend/scripts/run_parallel_simulation.py:6049-6066` |
| `SIM_GRAPH_FEEDBACK` (caller side) | false | Whether the orchestrator passes `enable_graph_memory_update=True` | `backend/app/config.py:1385`; `backend/app/services/pipeline_orchestrator.py:12985-12989` (also `:8804-8807`) |
| Child env injected | — | `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`, `SIM_SEED=<int>` (only with `sim_seed`), `SIM_RESUME=true` | `run:929-939` |
| `WERKZEUG_RUN_MAIN`, `FLASK_DEBUG` (env) | — | Which process registers the cleanup handlers | `run:2511-2517` |
| `DRF_TEST_PROCESS` / app `TESTING` | — | Disables `register_cleanup` and `reconcile_orphans` at app start | `backend/app/__init__.py:122-131` |

---

## External calls

| Call | Kind | Anchor |
|---|---|---|
| `subprocess.Popen([sys.executable, scripts/run_*_simulation.py, --config, …], cwd=sim_dir, start_new_session=True)` | subprocess (OASIS sim; makes LLM calls inside) | `run:943-953` |
| `ps -p <pid> -o command=` | subprocess (identity check) | `run:1431-1434` |
| `taskkill` (Windows) | subprocess | `run:1497-1498,1625-1638` |
| `os.killpg(SIGTERM/SIGKILL)` / `os.kill(pid,0)` | signals | `run:1501-1506,1654-1661,1467,1489` |
| `socket.create_connection(("127.0.0.1", FLASK_PORT), 0.2)` | local TCP probe | `run:1538` |
| `sqlite3.connect(<plat>_simulation.db)` | DB read | `run:2929-2947` |
| `ZepGraphMemoryManager.create_updater/get_updater/stop_updater/stop_all` → `add_activity_from_dict` | graph writes (FalkorDB/Graphiti via the Zep-compatible layer; network) on a background worker | `run:860,1124,1172,1280,1723,2413`; `backend/app/services/zep_graph_memory_updater.py:350-372,655-711` |
| `ZepEntityReader().filter_defined_entities` | graph read | `mgr:916-925` |
| `OasisProfileGenerator.generate_profiles_from_entities` | LLM (persona generation, optional) | `mgr:1081-1091` |
| `SimulationConfigGenerator().generate_config` | LLM (config generation) | `mgr:1165-1178` |
| `build_actor_context_artifacts` / `validate_actor_context_artifacts` | file I/O (actor_context slice) | `mgr:986-1002,1247-1254`; `run:699-711` |
| File-mailbox IPC (`ipc_commands`/`ipc_responses`) | IPC to the subprocess, which runs the LLM interviews | `ipc:209-341` |

---

## Cross-module edges

**Callers into this slice**
- `backend/app/__init__.py:129,131`: `register_cleanup`, `reconcile_orphans`.
- `backend/app/services/pipeline_orchestrator.py`:
  - Manager: `create_simulation`/`prepare_simulation` (`:8772-8790` ensemble seed; `:12776,12811` main), `validate_prepared_simulation_config` (`:12747`), `reseal_simulation_config` (`:12925`), `validate_simulation_config_seal` (`:10038`).
  - Runner: `start_simulation` (`:8808,:12989`), `stop_simulation` (`:8825,8842,9151,13010,13057`), `get_run_state` (`:8829,13014,13131,13144`), `join_monitor_thread` (`:8858,13085`), `write_run_summary` (`:8864,10108`), `_check_all_platforms_completed` (mirrored at `:9942-9960`), `_is_simulation_alive` (`:10011`), `RUN_STATE_DIR` (many), `register_cleanup` (`:7873`). [verifier: the orchestrator does not call `SimulationRunner.register_cleanup`; `:7873` is a docstring in its own `register_cleanup` (def `:7870`). The only caller is `backend/app/__init__.py:129`]
- `backend/app/api/simulation.py`:
  - `SimulationManager()` instances at `:217,455,795,835,950,1037,1307,1334,1565,1718,2848`.
  - `prepare_simulation` (`:619`), `start_simulation` (`:1640`), `stop_simulation` (`:1592,1715`), `cleanup_simulation_logs` (`:1604`).
  - Readers: `get_all_actions`/`get_actions`/`get_timeline`/`get_agent_stats` (`:1859,1932,1975,2112`).
  - Interviews and env: `check_env_alive`/`interview_*`/`get_interview_history`/`get_env_status_detail`/`close_simulation_env` (`:2383-2842`).
  - `_run_state_lock` (`:369`).
- `backend/app/api/report.py:305,1525`: `SimulationManager()`.
- `backend/app/services/zep_tools.py:2065` (`interview_agents_batch`); `:2461-2497,2774-2807` (timeline, stats, actions).
- `backend/app/services/report_agent.py:1717-1721`: `SimulationIPCClient(sim_dir).check_env_alive()`.
- `backend/app/mcp/sim_server.py:88-175`: run state, env status, timeline, stats, interviews, `SimulationIPCClient.check_env_alive`.
- `backend/scripts/run_parallel_simulation.py:1336-1337`: imports `validate_simulation_config_seal` and re-checks the seal in the child.
- `backend/scripts/test_pipeline_resume.py:11,248-261`: `_rotate_stale_action_logs`.

**Calls out of this slice**
- `backend/app/services/zep_entity_reader.py` (`ZepEntityReader`, `EntityNode`), `backend/app/utils/actors.py` (`extract_actor_rows`, `match_actor`, `is_agent_eligible`, `influence_weight`, `salience_score`, `entity_simulation_tier`, `normalize_name`).
- `backend/app/services/actor_context.py` (`actor_id_for`, `build/validate_actor_context_artifacts`, `context_binding_by_actor_id`).
- `backend/app/services/oasis_profile_generator.py` (`generate_profiles_from_entities`, `generate_audience_profiles`, `save_profiles`, `validate_role_prompt_manifest`, `_role_manifest_path`), `backend/app/services/actor_role_prompt.py` (`ROLE_CONTRACT_VERSION`).
- `backend/app/services/simulation_config_generator.py` (`generate_config`, `AUDIENCE_ENTITY_TYPE`).
- `backend/app/services/zep_graph_memory_updater.py` (`ZepGraphMemoryManager`).
- `backend/app/services/agent_dynamics.py` (`simulated_hours_from_rounds`, `classify_organic_action`, `detect_organic_ratio_collapse`).
- `backend/app/utils/atomic.py` (`write_json_atomic`, `write_text_atomic`).
- `backend/scripts/run_*_simulation.py` (subprocess).

---

## Invariants, gates, validation

1. **Cast completeness.** Every eligible dossier actor must be in the selected cast, or PREPARE raises (`mgr:960-968`). Under legacy cast discipline, more eligible actors than `ACTOR_CAST_MAX` therefore *fails* PREPARE rather than truncating silently.
2. **Role coverage.** Generated role prompts must equal `selected_actor_count` (`mgr:1093-1102`). Context count must equal role count (`mgr:1243-1246`, `run:603-606`, `mgr:1417-1418`).
3. **Config seal.** The exact bytes, the canonical JSON, the `simulation_id`, and the cast/context/role SHAs are bound in `simulation_config_manifest.json` (`mgr:52-134`). They are validated at PREPARE end (`mgr:1290-1298`), at PREPARE reuse (`mgr:1352-1452`), at the runner boundary (`run:634-668`), and in the child process (`backend/scripts/run_parallel_simulation.py:1336`). A run with actor-context or role v2+ cannot start without a state-bound seal (`run:651-654`).
4. **Role manifests on disk equal state.** The runner requires an exact dict equality between `actor_role_manifest_sha256` in state and the on-disk SHAs (`run:630-633,717-720`). Every requested platform must have a role manifest (`run:726-732`).
5. **Single runner per simulation.** STARTING/RUNNING is rejected only when a live, identity-verified process exists (`run:482-488`).
6. **Completion evidence.** COMPLETED requires a `simulation_end` from every enabled platform (`run:1205-1212`). Exit code 0 without that evidence becomes FAILED (`run:1089-1099`). An existing terminal state is never overwritten by a later process exit (`run:1063-1073`). A late `simulation_end` never promotes a STOPPING, STOPPED, or FAILED state (`run:1213-1221`).
7. **Truthful STOPPED.** STOPPED is set only when termination is confirmed; otherwise FAILED (`run:1707-1717`).
8. **Truthful graph memory.** `graph_memory_active` reports whether the updater was actually created, not whether it was requested (`run:854-871`).
9. **Process identity.** Kills by persisted pid require the command line to contain a script name and the `simulation_id` (`run:1441-1455`).
10. **Resume safety.** A checkpoint is ignored if its `config_hash` differs from the current config (`run:1378-1380`). Resume only works with the parallel script (`run:775-777`). COMPLETED runs are not auto-resumed (`run:765-770`).
11. **Consistent snapshots.** Counters are mutated and serialized under `SimulationRunState._lock` (`run:185-263,1190,1232,1271`). `run_state.json`/`state.json` writes are serialized by `_run_state_lock` (`run:307,442`; `mgr:768`).
12. **IPC cancel protocol.** On timeout the client writes `<id>.cancel` and removes `<id>.json` (`ipc:323-339`). The parallel script skips cancelled commands and suppresses orphan responses (`backend/scripts/run_parallel_simulation.py:902-939`).

---

## Failure modes & recovery

| Failure | Behavior | Anchor |
|---|---|---|
| No entities after filtering | PREPARE sets FAILED and **returns** (no raise) | `mgr:1026-1030` |
| Any other PREPARE exception | FAILED with `error`, then re-raised | `mgr:1309-1316` |
| Audience profile generation fails | Warning only; audience agents in config have no profiles | `mgr:1220-1221` |
| Integrity/seal mismatch at start | `ValueError("角色提示词完整性校验失败: …")`; no process launched; run_state not touched | `run:758-759` |
| `enable_graph_memory_update` without `graph_id`, or missing script | `ValueError` **after** STARTING was persisted; no process | `run:851,856-857,892-893` |
| Updater creation fails | Run proceeds; `graph_memory_active=False`, `graph_memory_error` set | `run:864-868` |
| Popen fails | FAILED, `error`, re-raise | `run:980-984` |
| Child exits non-zero, or 0 without `simulation_end` | FAILED with log tail [verifier: only if some enabled platform's `simulation_end` was never parsed; once all were read (even in the post-exit final tail) the status is already COMPLETED and is kept regardless of exit code (run:1048-1067,1205-1212)] | `run:1083-1104` |
| Monitor thread exception | FAILED with exception text | `run:1114-1118` |
| Malformed action line | Skipped; position advances | `run:1282-1284` |
| Backend restart mid-run | `reconcile_orphans` kills the orphan pgroup and marks FAILED in run_state and state.json, env stopped | `run:1519-1566` |
| Second backend starting while the first is alive | Port probe skips the reclaim | `run:1531-1543` |
| Stop cannot confirm the kill | FAILED "停止失败…" | `run:1713-1717` |
| Server shutdown | Non-terminal runs become STOPPED (via STOPPING); terminal results are preserved; env stopped | `run:2390-2494` |
| Interview to a dead env | `ValueError` before sending (env_status not alive) | `run:2683-2684,2772-2773` |
| Interview timeout | `TimeoutError` propagates from `send_command`; `.cancel` written so the child skips the work | `ipc:308-341` |
| Batch interview too slow | Timeout scaled up by batch size and concurrency | `run:2712-2737,2776-2779` |
| `close_env` times out | Reported as success [verifier: the timeout path in `send_command` also writes `<id>.cancel` (ipc:323-330); ParallelIPCHandler handles one command at a time (backend/scripts/run_parallel_simulation.py:1219-1258) and drops a cancelled command it has not yet read (:902-912), so a close_env queued behind a long batch interview is discarded and the env stays alive despite `success:True`] | `run:2905-2910` |
| Re-run after failure | Logs and derived artifacts rotated to `.prev` (unless resuming) | `run:783-784,1309-1337` |
| Force restart via API | `cleanup_simulation_logs` deletes run artifacts but keeps config/profiles | `run:2300-2385` |
| `run_summary` aggregation or write failure | Returns None or the partial summary; write failure only warns | `run:2043-2045,2296-2297` |

---

## Surprises

1. **`SimulationIPCServer` is dead code; the docs say otherwise.** The real servers are script-local handlers with different semantics:
   - The parallel script has no `.processing` claim (`backend/scripts/run_parallel_simulation.py:881-919`).
   - The single-platform scripts have no `.cancel` handling and write non-atomically (`backend/scripts/run_twitter_simulation.py:169-212`).
   - `SimulationIPCServer` (`ipc:547-732`) is only re-exported (`backend/app/services/__init__.py:31-33`), and no test references `simulation_ipc`.
   - `ARCHITECTURE.md:303` and `ARCHITECTURE_MAP.md:692` describe `SimulationIPCServer` as the script side. That is doc drift.
2. **`SimulationIPCClient.summarize` has no caller.** IPC telemetry is written (default on) but never read in production. It is only rotated (`run:1301`).
3. **Telemetry default contradicts its docstring.** `_ipc_telemetry_enabled` says "default off" (`ipc:37`), but `Config.IPC_TELEMETRY_ENABLED` defaults to `'True'` (`backend/app/config.py:358`).
4. **`SIM_RUNSTATE_SAVE_INTERVAL` is a ghost knob.** It is read through getattr (`run:436`) but not defined in `backend/app/config.py`, so the throttle documented at `run:292-294,423-428` never applies unless something sets the attribute at runtime. Every 2 s monitor tick also does an fsync'd atomic write (`write_json_atomic` default `fsync=True`, `backend/app/utils/atomic.py:59`), against the ATOMIC-1 advice for high-frequency status files.
5. **The interview concurrency fallback differs from Config.** `_scale_interview_timeout` reads `os.environ` with fallback `'30'` for `OASIS_SEMAPHORE` (`run:2732`), while `Config.OASIS_SEMAPHORE` defaults to 24 (`backend/app/config.py:1091`).
6. **COMPLETED ≠ process exited.** After `simulation_end` the child stays alive in command mode for up to `SIM_IDLE_CLOSE_MIN` (60 min). [verifier: 60 min of *idle* time — every processed IPC command resets `last_command_at`, so an interviewed child can live longer (backend/scripts/run_parallel_simulation.py:1231,1247,1257,6060-6061)]
   - `join_monitor_thread(timeout=30)` in the orchestrator's "fence" will normally time out when graph feedback is on (`backend/app/services/pipeline_orchestrator.py:13085-13090`).
   - `ARCHITECTURE_MAP.md:273` claims RUN's exit condition includes `env_status.json = stopped`. That is drift.
7. **Suspected: re-starting a COMPLETED simulation whose child is still in command mode can corrupt runner bookkeeping.**
   - The already-running guard only checks STARTING/RUNNING (`run:483`), so a second process is launched in the same `cwd` while the first is alive.
   - The old monitor thread's `finally` pops `_processes[sim_id]` and closes `_stdout_files[sim_id]` by ID (`run:1131-1140`); those entries now belong to the new process.
   - On exit, the old thread also calls `_save_run_state(old_state)`, which overwrites `_run_states[sim_id]` and `run_state.json` (`run:1108,443`).
   - The API force path does not kill a COMPLETED-but-alive child either: `stop_simulation` rejects COMPLETED (`run:1673-1674`), and `cleanup_simulation_logs` only deletes files.
   - [verifier: confirmed, and it starts before the old child exits — the old monitor thread keeps looping while its child lingers and calls `_save_run_state(old_state)` every 2 s (run:1030-1045), re-installing the old COMPLETED object in `_run_states` and `run_state.json` during the new run. On old-child exit it also calls `_mark_env_stopped` (run:1112) and, if `_graph_memory_enabled[sim_id]` is set, `stop_updater` (run:1122-1128), which now hit the new run's env status and graph updater]
8. **Suspected: a partial trailing line in `actions.jsonl` is dropped permanently.** The tailer advances `position` past lines that fail `json.loads` (`run:1282-1284`). If the reader catches a line mid-write (for example, an entry larger than one buffered write), both fragments are discarded.
   - A related case: a `UnicodeDecodeError` from a split multibyte character at EOF is caught by the outer handler, which returns the *old* position (`run:1285-1287`). Actions already added in that pass would then be counted twice, and fed to graph memory twice, on the next poll.
9. **Suspected: early `ValueError`s leave a STARTING `run_state.json` with no process.** This happens for a missing `graph_id` (`run:856-857`) or a missing script (`run:892-893`). In the missing-script case an already-started graph updater thread is also leaked (`run:860`). Recovery comes only from a later start (the guard sees no live process) or from `reconcile_orphans` at restart. [verifier: confirmed; additionally `_rotate_stale_action_logs` has already run (run:783-784), so a start that fails here has also renamed the previous run's `actions.jsonl`, `run_summary.json`, etc. to `.prev`]
10. **Suspected race: `stop_simulation` during STARTING.** If the STARTING state is persisted but `Popen` has not happened yet, `_kill_orphan_simulation` sees `process_pid=None` and returns True, so the state becomes STOPPED (`run:1703-1711`). `start_simulation` then launches the process and overwrites the state with RUNNING (`run:965-967`).
11. **The lock does not prevent lost updates on `state.json`.** `_run_state_lock` serializes writers, but `SimulationManager._save_simulation_state` writes its *cached* `SimulationState` object (`mgr:768-770`), not a read-modify-write. A long-lived manager instance can overwrite a terminal status written by `_sync_state_json_status` (`run:1599-1604`).
12. **Legacy enabled flags load as `None`, not `False`** (`run:379-386`), although the dataclass types them as `bool` (`run:150-151`). The comment says this lets "terminal reconciliation fall back to the API-facing SimulationState", but `_check_all_platforms_completed` falls back to file existence instead (`run:1404-1407`). The SimulationState fallback, if any, lives in the orchestrator. [verifier: refuted — the orchestrator mirror `_sim_platform_completion_missing` also falls back to `actions.jsonl` existence (backend/app/services/pipeline_orchestrator.py:9954-9958), and nothing else in `backend/app` reads `twitter_enabled`; no SimulationState fallback exists]
13. **Calendar mode logs that `max_rounds` is ignored but still passes `--max-rounds` to the child** (`run:817-823` vs `run:916-917`). The parallel script ignores it in calendar mode (`backend/scripts/run_parallel_simulation.py:2614-2616`). I did not verify whether the single-platform scripts are calendar-aware. [verifier: resolved — they are not. `run_twitter_simulation.py:833-835` and `run_reddit_simulation.py:823-825` compute hours-mode rounds and truncate by `--max-rounds` with no `temporal_config` handling, so a single-platform calendar run with `max_rounds>0` executes fewer rounds than `run_state.total_rounds` and `write_run_summary` reports it `truncated` (run:2123-2130). The parallel script also falls back to `len(round_dates)` before the hours formula when `n_rounds` is missing (run_parallel_simulation.py:2611-2613), while the runner goes straight to the hours formula (run:812-816)]
14. **`simulation.log` is opened with `'w'` on every start, including resumes** (`run:925`). Pre-crash log context is lost on resume, even though the action logs and DB are preserved.
15. **Dead or vestigial code.**
    - `RoundSummary` and `SimulationRunState.rounds` are never populated (`run:75-98,130`), so `rounds_count` is always 0.
    - `_action_queues` is created but never consumed (`run:896-897`).
    - `PlatformType` is unused (`mgr:614-617`).
    - Unused imports: `run:11,16,25`; `mgr:11,19-21`.
    - `RunnerStatus.PAUSED` is never entered by the runner (`run:274-275`). `SimulationStatus.PAUSED`, by contrast, *is* written by the API stop handler while the runner says STOPPED (`backend/app/api/simulation.py:1721`), so the two status models disagree after a stop.
16. **Duplicated integrity logic with subtly different checks.** The runner gate parses `actor_role_count` with `int()`, which accepts `"3"` or `3.9` (`run:536-540`). `validate_prepared_simulation_config` demands `type(...) is int` (`mgr:1381-1383`). The two re-implement the same closure separately (`run:514-757` vs `mgr:1367-1452`).
17. **Read paths create directories.**
    - `SimulationManager._get_simulation_dir` always calls `os.makedirs` (`mgr:754`), so `get_simulation("<anything>")` creates `uploads/simulations/<anything>/`.
    - `SimulationIPCClient.__init__` creates `ipc_commands/` and `ipc_responses/` on every liveness check (`ipc:206-207`, used by `run:2609`).
    - IDs are joined into paths unvalidated in this slice. I did not verify whether the API validates them; no validation helper turned up in `backend/app/api/simulation.py`.
18. **Suspected: the legacy T3.13 path does no alias de-duplication** (`mgr:585-592`). `prepare_simulation` appends one `selected_actor_rows` entry per matched entity (`mgr:944-948`), but counts `selected_actor_count` by unique name (`mgr:949,969`). Alias duplicates could therefore trip the role-coverage or context-count checks (`mgr:1099-1102,994-1002`). I did not verify how the profile generator counts `role_prompts`. [verifier: PREPARE does fail, but earlier than suggested — the duplicate rows reach `build_actor_context_artifacts`, which raises `ValueError("duplicate selected actor_id in context build")` (backend/app/services/actor_context.py:1443-1446) before role coverage is checked; prepare then sets FAILED and re-raises (mgr:1309-1316). Reaching this path needs an unversioned dossier with `ACTOR_CAST_MAX<=0` or `ACTOR_CAST_MAX>=OASIS_MAX_AGENTS` (mgr:525-529,581-583)]
19. **`get_actions` pagination reads entire JSONL files on every call** (`run:1886-1894`), as do the timeline and stats readers. The cost is O(total actions) per API poll.
20. **`get_profiles` handles errors unevenly.** It is defensive for the Twitter CSV but raises on a half-written Reddit JSON (`mgr:1493-1507`), even though `reddit_profiles.json` is the file written in real time during generation (`mgr:1074-1076`).
21. **`_sweep_stale_files` never collects orphaned `.tmp-*` files** that `write_text_atomic` leaves when a writer crashes (`ipc:102-107`; `backend/app/utils/atomic.py:37`).
22. **Stale anchors in docs.**
    - `ARCHITECTURE_MAP.md:37` and `DRF_ARCHITECTURE.md:89` cite `simulation_runner.py:685-695` for the `Popen`; it is at `run:943-953`.
    - `ARCHITECTURE_MAP.md:244` and `DRF_ARCHITECTURE.md:778` cite `ensure_dossier_actor_entities` at `simulation_manager.py:33`; it is at `mgr:224`.
    - `ARCHITECTURE_MAP.md:275` says the runner is "~1700 lines"; it is 3,021.

---

## Verification

An adversarial verifier re-checked this map on 2026-10-11 against the on-disk `main` checkout. The pass was read-only: this file is the only one edited. Every non-confirmed statement also carries an inline `[verifier: …]` note at the place it occurs.

### Verdict counts

| Set | Checked | Confirmed | Imprecise | Refuted |
|---|---|---|---|---|
| Key claims handed to the verifier | 15 | 12 | 3 | 0 |
| Surprises handed to the verifier | 15 | 13 | 2 | 0 |
| Extra spot-checks (Walkthrough, Control flow, tables) | 26 | 16 | 7 | 3 |

The 16 confirmed spot-checks were: data dir path (`mgr:739-742`), `get_run_state` never re-reads disk (`run:309-319`), the already-running guard (`run:482-488`), calendar accounting incl. fallback (`run:808-833`), `simulation.log` opened `'w'` (`run:925`), `round_end` handling (`run:1224-1254`), rotation (`run:1309-1337`), `_check_all_platforms_completed` (`run:1399-1416`), `_pid_is_our_simulation` (`run:1442-1455`), `_mark_env_stopped` (`run:1569-1589`), `cleanup_all_simulations` (`run:2391-2494`), `close_simulation_env` (`run:2865-2910`), `_sweep_stale_files` ignores `.tmp-*` (`ipc:101-107`), the `.processing` claim (`ipc:642-648`), app-start gating (`backend/app/__init__.py:122-131`), and the stall-watchdog default 1800 s (`backend/app/config.py:355`).

### Non-confirmed key claims

1. **`select_agent_pool`: "Otherwise the default cast-discipline path truncates to ACTOR_CAST_MAX"** (imprecise). The cast-discipline path only runs when `ACTOR_CAST_MAX > 0`, `ACTOR_CAST_MAX < OASIS_MAX_AGENTS` (or `OASIS_MAX_AGENTS <= 0`), and at least one entity matched (`mgr:525-529`). Otherwise the legacy T3.13 path runs: it caps at min(positive caps), keeps every matched entity, and does no alias de-duplication (`mgr:581-599`). The v1-path part of the claim is correct (`mgr:489-522`).
2. **`stop_simulation` sets STOPPED "only when termination is confirmed (SIGTERM to the process group, then SIGKILL after 10s)"** (imprecise). The accepted states and the FAILED message are right. However:
   - The fallback `process.kill()` sets `terminated=True` without waiting (`run:1695-1697`).
   - The orphan path returns True without killing anything when `process_pid` is None (the STARTING-before-Popen race) or when the pid fails the identity check (`run:1481-1494`).
   - The 10 s grace applies only to the own-`Popen` path (`run:1654-1661`). The orphan path waits 1 s (`run:1501-1506`).
3. **`reconcile_orphans`: every active orphan "is killed …, marked FAILED"** (imprecise).
   - The port probe only runs when `SIMULATION_RECLAIM_PORT_PROBE` is set (default true, `run:1531`; `backend/app/config.py:498-500`).
   - The return value of `_kill_orphan_simulation` is discarded (`run:1553`). The run is marked FAILED and `env_status` is set to stopped even when the kill was not confirmed (`run:1513-1515`) or the pid was left alone after the identity check failed (`run:1493-1494`).

### Non-confirmed surprises

4. **"COMPLETED ≠ exited; the `join_monitor_thread(timeout=30)` fence normally times out"** (imprecise).
   - The fence runs only when `sim_graph_feedback` is pinned on (`SIM_GRAPH_FEEDBACK` defaults to false) and `graph_id` is set (`backend/app/services/pipeline_orchestrator.py:13082-13083`).
   - `SIM_IDLE_CLOSE_MIN` is an idle timer that every processed IPC command resets (`backend/scripts/run_parallel_simulation.py:1231,1247,1257,6060-6061`). It is not a hard 60-minute cap.
   - The doc drift at `ARCHITECTURE_MAP.md:273` is confirmed.
5. **"Legacy T3.13 path does no alias de-duplication → role/context coverage checks could fail"** (imprecise). The missing de-duplication is real (`mgr:585-592`), but the failure comes earlier than stated. Duplicate rows reach `build_actor_context_artifacts`, which raises `ValueError("duplicate selected actor_id in context build")` (`backend/app/services/actor_context.py:1443-1446`). Prepare then records FAILED and re-raises (`mgr:1309-1316`).

### Wrong or imprecise spot-checks (beyond the handed-in claims)

- **Refuted:** "if the original was `SIG_IGN`, the handler returns". The code checks the *current* disposition, which is `cleanup_handler` itself, so an original SIG_IGN is never honored (`run:2554-2558`, `run:2569-2574`).
- **Refuted:** "`register_cleanup` is called from `pipeline_orchestrator.py:7873`" (Walkthrough and Cross-module edges). That line is a docstring in `PipelineOrchestrator.register_cleanup` (def `:7870`). The only caller is `backend/app/__init__.py:129`.
- **Refuted:** "The SimulationState fallback, if any, lives in the orchestrator". The orchestrator mirror also falls back to `actions.jsonl` existence (`backend/app/services/pipeline_orchestrator.py:9954-9958`). No SimulationState fallback exists.
- **Imprecise:** "every method is a `@classmethod`". `_read_log_tail` and `_missing_platform_completions` are `@staticmethod` (`run:988,1001`).
- **Imprecise:** the `to_simple_dict` omission list leaves out `config_reasoning` and the `*_status` fields (`mgr:701-724`).
- **Imprecise:** the "current actor contract" definition is missing `state_context_count > 0` and `actor_context_required` (`mgr:1428-1441`).
- **Imprecise:** "`peak_round` is the max of `total_actions`". It is the whole bucket dict with the largest `total_actions`, or None (`run:2048-2056,2084`).
- **Imprecise:** Control flow "→ join_monitor_thread(30 s) + stop_updater" is gated by graph feedback (`backend/app/services/pipeline_orchestrator.py:13082-13083`).
- **Imprecise:** failure-mode row "child exits non-zero → FAILED" is true only if some enabled platform's `simulation_end` was never parsed (see omission O1).
- **Imprecise:** "SIGHUP with an original `SIG_DFL` leads to `sys.exit(0)`". Any non-callable original, `SIG_IGN` included, exits (`run:2540-2546`), and the handler is installed unconditionally (`run:2573-2574`). A `nohup`-started backend therefore loses its SIGHUP immunity.

### Confirmed, with added or corrected detail

- **Claim on post-exit resolution:** confirmed as written. The ordering nuance is recorded as omission O1.
- **Surprise "restart a COMPLETED sim with a live child":** confirmed, and the damage begins *before* the old child exits.
  - The old monitor thread calls `_save_run_state(old_state)` every 2 s while the old child lingers (`run:1030-1045`). That re-installs the old COMPLETED object over the new run's state in `_run_states` and `run_state.json`.
  - When the old child exits, the old thread also calls `_mark_env_stopped` (`run:1112`) and `stop_updater` (`run:1122-1128`), and both now act on the new run.
- **Surprise "early ValueErrors leave STARTING":** confirmed. Also, `_rotate_stale_action_logs` has already moved the previous run's logs and summary to `.prev` by then (`run:783-784`).
- **Surprise "calendar mode still passes `--max-rounds`":** confirmed, and the open question is resolved.
  - The single-platform scripts have no `temporal_config` handling and do truncate by `--max-rounds` (`backend/scripts/run_twitter_simulation.py:833-835`; `backend/scripts/run_reddit_simulation.py:823-825`).
  - So a single-platform calendar run executes fewer rounds than `run_state.total_rounds`, and its summary says `truncated` (`run:2123-2130`).

### Omissions (significant behavior the map did not cover)

- **O1. A non-zero exit after all `simulation_end` events is reported COMPLETED.**
  - The post-exit final tail (`run:1048-1051`) runs before `status_before_exit` is read (`run:1057`).
  - Parsing `simulation_end` already promotes STARTING/RUNNING to COMPLETED (`run:1205-1212`), and the post-exit block keeps that state (`run:1063-1073`).
  - So the exit code is ignored once every enabled platform has written `simulation_end`, and the `exit_code==0 and all_platforms_completed` branch (`run:1079`) is effectively dead.
- **O2. A timed-out `close_env` cancels itself while reporting success** (suspected race).
  - On timeout, `send_command` writes `<id>.cancel` (`ipc:323-330`), and `close_simulation_env` reports `success:True` (`run:2905-2910`).
  - `ParallelIPCHandler` processes one command at a time (`backend/scripts/run_parallel_simulation.py:1219-1258`) and drops cancelled commands it has not read yet (`:902-912`).
  - A `close_env` queued behind a long batch interview is therefore discarded, and the env stays alive.
- **O3. A short command's stale sweep can delete another request's in-flight command** (suspected race).
  - `send_command` sweeps `ipc_commands/` for files older than max(2×*its own* timeout, 300 s) (`ipc:234-236`).
  - `ParallelIPCHandler` reads commands in place with no claim (`backend/scripts/run_parallel_simulation.py:892-917`). Its `send_response` suppresses the reply when the command file is gone (`:932-939`).
  - Scaled batch timeouts routinely exceed 300 s (`run:2712-2737`). A concurrent 60 s interview can then delete a batch command that is still being processed. The batch's response is suppressed and its client times out.
- **O4. The history readers catch only `JSONDecodeError`** (`run:1796-1797`).
  - A `UnicodeDecodeError` from a multibyte character split at EOF while the child is writing (the logger writes `ensure_ascii=False`, `backend/scripts/action_logger.py:81-82`) propagates out of `get_all_actions`/`get_actions`/`get_timeline`/`get_agent_stats`.
  - In that case `write_run_summary` returns None (`run:2037-2045`).
  - Separately, `write_run_summary` reads every action file three times: `get_agent_stats` (`run:1985`), `get_timeline` (`run:1916`), and `get_all_actions` (`run:2042`).
- **O5. `prepare_simulation` never clears a previous `state.error`.** It only ever sets it (`mgr:1028,1314`). A re-prepare that succeeds returns READY (`mgr:1301-1302`) still carrying the old error string, which the API form exposes (`mgr:723`).
- **O6. The runner and the parallel script fall back differently in calendar mode when `n_rounds` is missing.** The runner uses the hours formula (`run:812-816`). The script uses `len(round_dates)` first (`backend/scripts/run_parallel_simulation.py:2606-2613`). `run_state.total_rounds` can then disagree with the rounds the child actually runs, which affects `truncated` and health.
