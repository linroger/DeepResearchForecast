# drf2 — drf2/ (harness driver, engines, skills, config)

Scope: every tracked file under `drf2/` on branch `main` (31 tracked files, ~4,980 lines; `.DS_Store` files ignored). All anchors are `path:line` relative to the repo root. Facts outside the slice are anchored where they were used to resolve a call; they are not mapped in depth.

File inventory (lines): `drf2/README.md` (173), `drf2/CLEANUP_LOCAL.md` (27), `drf2/driver/{__init__ 36, legacy 25, state 236, manifest 141, gates 226, ensemble 126, harness_client 295, pipeline 336, cli 227}.py`, `drf2/config/{config.yaml 441, extensions_config.json 44, market_tools.py 248}`, `drf2/engines/kg/{__init__ 9, server 173, tools 402}.py` + `README.md` (58) + `requirements.txt` (5), `drf2/engines/simulation/{__init__ 15, server 214, jobs 430}.py` + `README.md` (53) + `requirements.txt` (4), and 7 skills under `drf2/skills/custom/*/SKILL.md` (60–261 lines each).

## Purpose & position in the pipeline

`drf2/` ("DRF-2") is a **pre-cutover, not-live** rebuild of the forecasting pipeline on top of the vendored DeerFlow 2.0 "super-agent harness" (`deer-flow-2.0.0/`, untracked and gitignored, `.gitignore:93`). The tree's own README calls itself "scaffold, pre-cutover" and states that the legacy system (`backend/app`, `backend/scripts`, `deerflow_bridge/`) "remains the working pipeline" (`drf2/README.md:3-7`, `drf2/README.md:173`). It also states that "No live end-to-end run has been performed through the harness" (`drf2/README.md:170-172`).

It has four parts:
1. **Pipeline Driver** (`drf2/driver/`): a deterministic stage state machine (`research → ontology → graph → prepare → run → report`, `drf2/driver/state.py:25`) with atomic state persistence, a sha256 artifact manifest for resume, and file-reading health gates. It sends each knowledge stage as one harness "run" over HTTP (`drf2/driver/harness_client.py:56-142`). It drives the OASIS simulation through a simulation-engine HTTP client (`drf2/driver/harness_client.py:193-236`). It pools multi-seed forecasts with legacy ensemble math (`drf2/driver/ensemble.py:19-25`).
2. **Two stdio MCP engine servers** (`drf2/engines/kg`, `drf2/engines/simulation`): thin wrappers that lazily import the legacy Graphiti/FalkorDB stack (`drf2/engines/kg/tools.py:60-96`) and the legacy `SimulationRunner` (`drf2/engines/simulation/jobs.py:40-43`). The harness spawns them through `drf2/config/extensions_config.json:3-33`.
3. **Seven DeerFlow-2.0-format skills** (`drf2/skills/custom/*/SKILL.md`): methodology prompts for research, actor dossiers, ontology, KG construction, simulation design, forecast reports and prediction markets.
4. **Harness config** (`drf2/config/config.yaml`): model routing (claude-sonnet / MiniMax-M3), tools, four custom sub-agents, and skills. It also includes a config-reflected Polymarket tool (`drf2/config/market_tools.py`).

**Relationship to the live app.** Nothing in `backend/app`, `deerflow_bridge/` or `frontend/` imports `drf2`. `git grep drf2 -- backend/app deerflow_bridge frontend` finds only comments in `deerflow_bridge/market_tools.py:3,42`, which says that file was *adapted from* `drf2/config/market_tools.py`. The edges run the other way: `drf2` imports legacy modules (`drf2/driver/legacy.py:18-25`, `drf2/driver/state.py:22`, `drf2/driver/gates.py:32`, `drf2/driver/ensemble.py:19-25`, `drf2/engines/simulation/jobs.py:40-43`, `drf2/engines/kg/tools.py:66,79,92,171`). The only executable entry points outside `drf2` are:
- the pytest suites `backend/tests/test_drf2_{driver,kg,simulation,skills_config}.py`
- an opt-in `SETUP_DRF2=1` block in `setup.sh:738-814`, which only installs `mcp` into `backend/.venv` and prints instructions

Top-level docs call drf2 "Optional, not-yet-live (pre-cutover)" (`README.md:445`, `README.md:1673`) or "older/parallel driver lineage … (historical)" (`ARCHITECTURE_MAP.md:96`, `DRF_ARCHITECTURE.md:151,353`).

**Bottom line:** a parallel, experimental path that is not wired into the live Flask/Vue app. Several of its integration contracts are unfinished (see Surprises).

## Walkthrough (source order)

### drf2/README.md
- Status banner, §1 layout and §2 prerequisites (`drf2/README.md:1-50`). The prerequisites are the `deer-flow-2.0.0/` harness with its own env, `backend/.venv` for the engines, FalkorDB, `MINIMAX_API_KEY`, claude-cli credentials for `ClaudeChatModel`, and `PYTHONPATH` including the repo root.
- §3.1: the engines are stdio MCP servers that the harness spawns. The pinned tool surface is 8 `kg_*` tools plus 5 `sim_*` tools (`drf2/README.md:54-70`).
- §3.2: start the harness with `DEER_FLOW_CONFIG_PATH` / `DEER_FLOW_EXTENSIONS_CONFIG_PATH` and run `make dev` (gateway :8001, UI :3000, nginx :2026) (`drf2/README.md:72-84`).
- §3.3 describes two drive modes (`drf2/README.md:86-101`):
  - chat with the lead agent using the four custom sub-agents;
  - the Pipeline Driver.
- §3.4: intended stage flow and model routing (`drf2/README.md:103-116`).
- §4: offline verification via `backend/tests/test_drf2_skills_config.py`, plus import smoke paths (`drf2/README.md:118-149`).
- §5 "honesty section": done vs. TODO (`drf2/README.md:151-173`).

### drf2/CLEANUP_LOCAL.md
- Operator notes listing untracked local junk that was deliberately not deleted: `deer-flow/` (~962MB), `graphiti-0.29.2/`, `log/`, `SwiftMandarin/`, and `logs/` ("MAY CONTAIN SECRETS") (`drf2/CLEANUP_LOCAL.md:7-13`).
- It keeps `deer-flow-2.0.0/` as the vendored DeerFlow 2.0 source drop (`drf2/CLEANUP_LOCAL.md:17-19`).
- It explains why `backend/scripts/run_twitter_simulation.py` / `run_reddit_simulation.py` were kept: the single-platform branches of `simulation_runner.py` still use them (`drf2/CLEANUP_LOCAL.md:23-27`).
- It references branch `deerflow2-redesign` and REDESIGN.md §4 (`drf2/CLEANUP_LOCAL.md:5`).

### drf2/driver/__init__.py
- Package docstring: the driver "only sequences [the harness] and verifies artifacts deterministically (never via LLM)" (`drf2/driver/__init__.py:1-5`).
- It re-exports state/manifest/gates/ensemble/harness_client/pipeline symbols (`drf2/driver/__init__.py:7-36`). Importing the package therefore runs every submodule's `ensure_backend_importable()` and legacy `app.*` import.

### drf2/driver/legacy.py
- `_BACKEND_DIR` = `<repo>/backend`, computed from `__file__` (`drf2/driver/legacy.py:15`).
- `ensure_backend_importable()` (`drf2/driver/legacy.py:18-25`) is idempotent. If `importlib.util.find_spec("app")` is None, it inserts `backend/` at `sys.path[0]`. If `app` is still not importable, it raises `ImportError`.
  - Side effect: mutates `sys.path`.
  - Importing any `app.*` module runs `backend/app/__init__.py`, which imports Flask at module level (`backend/app/__init__.py:15-18`).

### drf2/driver/state.py
- On import it calls `ensure_backend_importable()` and imports `app.utils.atomic.write_json_atomic` (`drf2/driver/state.py:19-22`; callee at `backend/app/utils/atomic.py:53`).
- `SCHEMA_VERSION = 1`; `STAGES = ("research","ontology","graph","prepare","run","report")` (`drf2/driver/state.py:24-25`).
- `_STAGE_TRANSITIONS` (`drf2/driver/state.py:28-33`):
  - pending→running
  - running→completed|failed
  - failed→running
  - completed→running (allowed so a stage can be forcibly rebuilt when its manifest fails)
  - **running→running is not allowed.**
- `_PIPELINE_STATUSES` (`drf2/driver/state.py:34`) is defined but never referenced (dead). "cancelled" is never set anywhere.
- `utcnow()` returns an ISO-8601 UTC string (`drf2/driver/state.py:37-38`).
- `IncompatibleStateSchema(RuntimeError)` is raised when the file's schema version is greater than the driver's (`drf2/driver/state.py:41-49`). `InvalidTransition(RuntimeError)` (`drf2/driver/state.py:52-53`).
- `StageRecord` dataclass (`drf2/driver/state.py:56-76`):
  - Fields: `name`, `status` (pending|running|completed|failed), `message`, `error`, `health` (unknown|ok|degraded|failed), `issues[]`, `started_at`, `finished_at`, `attempts`, `reused`, `artifacts{name→abspath}`.
  - `from_dict` ignores unknown keys, for forward compatibility (`drf2/driver/state.py:73-76`).
- `DriverState` dataclass (`drf2/driver/state.py:79-179`):
  - Fields: `pipeline_id`, `question`, `schema_version`, `status`, `current_stage`, `thread_id`, `created_at`, `updated_at`, `error`, `seeds[]`, `options{}`, `stages{}`.
  - `new()` mints `uuid4().hex[:12]` when no id is given, sets `thread_id=f"drf2-{pid}"`, and creates all 6 StageRecords (`drf2/driver/state.py:94-99`).
  - `_stage` raises `KeyError` for an unknown stage name (`drf2/driver/state.py:102-105`). `_transition` enforces the transition table (`drf2/driver/state.py:107-114`).
  - `start_stage` resets `started_at`, `finished_at`, `error` and `reused`; increments `attempts`; and sets pipeline `status="running"` (`drf2/driver/state.py:116-125`).
  - `complete_stage` sets health, issues and message (default "完成") and merges artifacts (`drf2/driver/state.py:127-138`).
  - `fail_stage` sets stage `health="failed"`, pipeline `status="failed"`, and `error=f"[{name}] {error}"` (`drf2/driver/state.py:140-147`).
  - `mark_stage_reused` only applies to a completed stage; it sets `reused=True` and a Chinese message (`drf2/driver/state.py:149-157`).
  - `mark_completed` (`drf2/driver/state.py:159-162`). `to_dict`/`from_dict` (`drf2/driver/state.py:165-179`).
- `_MIGRATIONS = {}`: an empty migration chain (`drf2/driver/state.py:183`). `_ID_RE = ^[A-Za-z0-9._-]{1,64}$` (`drf2/driver/state.py:185`).
- `StateStore(base_dir)` (`drf2/driver/state.py:188-236`):
  - Layout: `<base>/<pid>/state.json`, `manifest.json`, and `artifacts/` (the last is a path helper that is never used by the pipeline) (`drf2/driver/state.py:199-209`).
  - `_validate_id` raises `ValueError` on an id that fails `_ID_RE` (`drf2/driver/state.py:194-197`).
  - `save` writes atomically (`drf2/driver/state.py:211-213`).
  - `load` json-loads with no error swallowing. It refuses newer schemas and runs migrations up to the current version; a missing migration raises `IncompatibleStateSchema` (`drf2/driver/state.py:215-230`).
  - `exists` returns False on an invalid id (`drf2/driver/state.py:232-236`).

### drf2/driver/manifest.py
- `sha256_file` streams 1 MiB chunks and returns None on `OSError` (`drf2/driver/manifest.py:27-39`).
- `probe_artifact`: a `.json` file must parse to a dict or list; any other file must be non-empty (`drf2/driver/manifest.py:42-50`).
- `ArtifactManifest(path)` (`drf2/driver/manifest.py:53-141`) maps name → `{path, sha256, bytes, stage, recorded_at, schema_ok}`.
  - `_load` treats a missing or corrupt file as empty (`drf2/driver/manifest.py:61-68`). `save` writes atomically (`drf2/driver/manifest.py:70-71`).
  - `record` returns None if the file is missing, so a missing optional artifact is not an error (`drf2/driver/manifest.py:73-91`).
  - `record_stage` records a batch, saves, and returns only `{name: abspath}` for files that exist (`drf2/driver/manifest.py:93-101`).
  - `verify_stage` (`drf2/driver/manifest.py:103-138`):
    - empty manifest → `(True, [])` (falls back to existence-based reuse);
    - merges the passed specs with every entry already registered for that stage;
    - skips unregistered names;
    - fails on the first problem only (each check ends in `break`): missing file, unreadable file, byte-size change, sha256 mismatch, or probe failure.
  - `names_for_stage` (`drf2/driver/manifest.py:140-141`).

### drf2/driver/gates.py
- Provenance docstring citing `pipeline_orchestrator.py` line numbers (`drf2/driver/gates.py:1-17`). Those line numbers are stale; see Surprises.
- Imports legacy `app.services.forecast_extractor._binary_quality` (`drf2/driver/gates.py:30-32`; callee `backend/app/services/forecast_extractor.py:1599`).
- `GateResult(name, status pass|degraded|fail, issues, meta)`. Its `hard_fail` property is `status == "fail"` (`drf2/driver/gates.py:35-44`).
- `_read_text` / `_read_json` return ""/None on error (`drf2/driver/gates.py:47-60`).
- `LLM_ERROR_MARKERS` (`drf2/driver/gates.py:65-71`): "The configured LLM provider", "LLM request failed", "unprocessable_entity", "new_sensitive", "Error code: 4", "Error code: 5". It is a copy of `backend/app/services/pipeline_orchestrator.py:2748-2754`.
- `research_gate(handoff_dir, min_report_chars=400, quality_floor=0.0)` (`drf2/driver/gates.py:74-109`):
  - Reads `research_report.md`. Empty → **fail**. Shorter than `min_report_chars` → **fail**. Shorter than 400 chars *and* containing an error marker → **fail** (`drf2/driver/gates.py:79-91`).
  - A non-empty `actor_dossier.md` that is shorter than the floor or contains a marker → **degraded** issue, with `meta.dossier_degraded` (`drf2/driver/gates.py:94-99`).
  - `meta.json.research_quality.score` below `quality_floor` (only when the floor is above 0) → **degraded** (`drf2/driver/gates.py:102-108`).
- `hollow_sim_gate(sim_dir=None, *, summary=None, run_state=None)` (`drf2/driver/gates.py:112-158`):
  - Reads `run_summary.json` / `run_state.json` from `sim_dir` when no dicts are passed.
  - A missing summary is an issue.
  - `simulation_health` ∈ {hollow, errored, llm_degraded, truncated} is an issue.
  - A `run_state.error` is an issue. `current_round < total_rounds` (or `total_simulation_rounds`) means truncated.
  - `organic_action_count == 0` means hollow.
  - **Never returns "fail"**: the only outcomes are degraded or pass (`drf2/driver/gates.py:158`).
- `binary_conviction_gate(forecast_path, min_count=10)` (`drf2/driver/gates.py:161-186`):
  - A missing or unparsable `forecast.json` → degraded.
  - Keeps only binaries whose probability is finite and in [0,1]. If none remain → degraded.
  - Otherwise calls `_binary_quality` and returns pass iff `q["passed"]`, else degraded. **It never returns fail.**
  - Legacy pass criteria: `n>=min_count`, `stdev>=0.12`, `midband_share<=0.40`, `conviction>=3`, `sharp>=int(0.8n)` using each binary's `criteria_sharp` flag (`backend/app/services/forecast_extractor.py:1626-1632`).
- `deliverable_gate(report_dir, structured_forecast_required=True, min_report_bytes=2000)` (`drf2/driver/gates.py:189-226`):
  - Counts `section_*.md` placeholders. A section is a placeholder if it contains "生成失败", or "本章节" together with "失败", or if its stripped length is under 200.
  - `forecast.json` is acceptable only if it has non-empty `scenarios` or `binary_forecasts`.
  - Measures `full_report.md` size.
  - **fail** if any of: all sections are placeholders, forecast missing (when required), report missing, or report under `min_report_bytes`.
  - **degraded** if only some sections are placeholders.

### drf2/driver/ensemble.py
- Imports the legacy pooling primitives `_ensemble_agreement`, `_extremized_logodds`, `_mean`, `_norm_name`, `_stdev` (`drf2/driver/ensemble.py:19-25`; callees `backend/app/services/ensemble.py:27,118,139,143,348`). It deliberately does not call legacy `aggregate_forecasts` (`backend/app/services/ensemble.py:150`), because that function reads a global Config (`drf2/driver/ensemble.py:4-8`).
- `aggregate_ensemble(forecasts, extremize_a=None)` (`drf2/driver/ensemble.py:28-100`):
  - With 0 runs it returns `{"n_runs":0,"scenarios":[],"agreement":None,"schema_version":1}`.
  - Buckets scenarios by `_norm_name(name)`. Each bucket collects probabilities, a union of `key_drivers`, and the first `resolution_criteria` seen.
  - Per bucket: `mean_probability`, `stdev`, `min`, `max`, `support`, `support_ratio`, and the first 8 sorted drivers.
  - The point estimate is the extremized log-odds pool if `a` is set, otherwise the arithmetic mean. Point estimates are then renormalized to sum to 1.
  - `p_low`/`p_high = probability ± stdev`, clipped to [0,1].
  - Sorted by probability, descending.
  - Output keys: `n_runs`, `scenarios`, `agreement` (legacy TV distance), `agreement_spread = max(0, 1-2*mean(stdev))`, `extremize_a`, `headline`/`horizon` from `runs[0]`, `schema_version:1`.
  - Binary forecasts are **not** pooled; only scenarios are.
- `fan_out(seeds, run_one, extremize_a)` (`drf2/driver/ensemble.py:103-126`):
  - Runs seeds sequentially. Each seed's exception (or a non-dict return) is recorded as `{"ok":False,"error":"Type: msg"}` without aborting the remaining seeds.
  - Returns `{seeds, results{str(seed)→{ok,error?}}, n_ok, aggregate}`.

### drf2/driver/harness_client.py
- Module docstring (`drf2/driver/harness_client.py:1-18`):
  - The transport is the Runs API, polled rather than consumed via SSE `join`.
  - Embedded `DeerFlowClient` is marked **TODO-for-cutover**.
  - The RUN stage is not a harness run; the driver polls with a stall watchdog.
- `TERMINAL_RUN_STATUSES = {"success","error","timeout","interrupted"}` (`drf2/driver/harness_client.py:30`). This matches `deer-flow-2.0.0/backend/packages/harness/deerflow/runtime/runs/schemas.py:6-14`.
- `HarnessError` (`drf2/driver/harness_client.py:33`). `RunResult(run_id, status, error, elapsed_s)`, where `.ok` means `status=="success"` (`drf2/driver/harness_client.py:37-46`).
- `Harness` Protocol: `ensure_thread`, `run_stage(stage, prompt, timeout_s, context)`, `artifact_path(relpath)` (`drf2/driver/harness_client.py:49-53`).
- `RunsApiHarness` (`drf2/driver/harness_client.py:56-142`):
  - Defaults: `user_id="default"`, `poll_interval_s=5.0`, `http_timeout_s=60.0`, and an injectable `sleep`.
  - `_request` uses `urllib.request` with JSON bodies. It adds an `Authorization: Bearer` header when `api_key` is set. HTTPError → `HarnessError` with up to 400 chars of body. URL, timeout or OS errors → `HarnessError`. A non-JSON response → `HarnessError` (`drf2/driver/harness_client.py:73-91`).
  - `ensure_thread` sends `POST /api/threads {"thread_id"}`, which is idempotent on the harness side (`drf2/driver/harness_client.py:94-96`).
  - `start_run` sends `POST /api/threads/{tid}/runs` with `input.messages=[{role:user, content:prompt}]`, `on_disconnect:"continue"`, `multitask_strategy:"reject"`, and an optional `context`. A missing `run_id` raises (`drf2/driver/harness_client.py:98-111`).
  - `poll_run` loops `GET /api/threads/{tid}/runs/{run_id}` until the status is terminal. On a driver-side timeout it makes a best-effort `POST …/cancel` and returns `status="timeout"` (`drf2/driver/harness_client.py:113-129`).
  - `run_stage = start_run + poll_run` (`drf2/driver/harness_client.py:131-134`).
  - `artifact_path` returns `workspace_root/users/{uid}/threads/{tid}/user-data/outputs/{relpath}`. It raises `HarnessError` if `workspace_root` is unset (`drf2/driver/harness_client.py:136-142`).
  - The routes exist in the vendored harness: `deer-flow-2.0.0/backend/app/gateway/routers/thread_runs.py:142,215,227` and `threads.py:247`.
- `DryRunHarness` dataclass (`drf2/driver/harness_client.py:145-175`):
  - Records `(stage, prompt)`, calls `stage_effects[stage](workspace, prompt)`, and returns `stage_statuses.get(stage,"success")`.
  - `artifact_path = workspace/relpath`.
- `SimEngineError` (`drf2/driver/harness_client.py:183`). `SimEngine` Protocol: `sim_start(config, seed)`, `sim_status(id)`, `sim_stop(id)` (`drf2/driver/harness_client.py:187-190`).
- `HttpSimEngine(base_url, http_timeout_s=60)` (`drf2/driver/harness_client.py:193-236`):
  - Expected contract: `POST {base}/simulations` with body `{"config": <dict>, "seed"?}` → `{"sim_id"|"simulation_id"}`; `GET {base}/simulations/{id}`; `POST …/{id}/stop`.
  - `sim_stop` swallows errors.
  - The docstring says "TODO-for-cutover: pin these paths once drf2/engines/simulation lands its API" (`drf2/driver/harness_client.py:196-199`). No such HTTP API exists (see Surprises).
- `DrySimEngine` (`drf2/driver/harness_client.py:239-262`) replays the `statuses` list. Its cursor resets on each `sim_start` and clamps to the last element. It records `started` and `stopped`.
- `poll_simulation(engine, sim_id, timeout_s, stall_s=1800, interval_s=30, clock, sleep)` (`drf2/driver/harness_client.py:265-295`):
  - Returns as soon as the status has a truthy `completed` or `error`.
  - Tracks `current_round` against a sentinel. If the round is unchanged for more than `stall_s`, it calls `sim_stop` and returns `{"completed":False,"error":"stall watchdog: …", **other status keys}`.
  - If total elapsed exceeds `timeout_s`, it calls `sim_stop` and returns a timeout error.
  - Otherwise it sleeps `interval_s`.

### drf2/driver/pipeline.py
- On import: `ensure_backend_importable()` and `write_json_atomic` (`drf2/driver/pipeline.py:31-32`).
- `STAGE_SKILLS` maps research→`deep-research`, ontology→`ontology-generation`, graph→`kg-construction`, prepare→`simulation-design`, report→`forecast-report`. There is no skill for `run` (`drf2/driver/pipeline.py:37-43`).
- `STAGE_ARTIFACTS` lists required (R) and optional (O) artifacts per stage (`drf2/driver/pipeline.py:46-55`):

  | Stage | Required | Optional |
  |---|---|---|
  | research | `research_report.md` | `actor_dossier.md`, `actors.json`, `sources.json`, `timeline.json`, `meta.json` |
  | ontology | `ontology.json` | `actors.json` |
  | graph | `kg_build_summary.json` | — |
  | prepare | `simulation_config.json` | `agent_profiles.json` |
  | run | `run_summary.json` | — |
  | report | `full_report.md`, `forecast.json` | — |

- `DEFAULT_STAGE_TIMEOUTS_S`: research 3600, ontology 1800, graph 3600, prepare 1800, report 3600 (`drf2/driver/pipeline.py:57-59`).
- `DEFAULT_GATE_CONFIG`: `min_report_chars 400`, `research_quality_floor 0.0`, `binary_min_count 10`, `min_report_bytes 2000`, `structured_forecast_required True` (`drf2/driver/pipeline.py:60-66`).
- `DEFAULT_SIM_CONFIG`: `timeout_s 4h`, `stall_s 1800`, `interval_s 30` (`drf2/driver/pipeline.py:67-69`).
- `build_stage_prompt(stage, question, out_subdir="")` (`drf2/driver/pipeline.py:72-84`) builds:
  - a first line `/{skill} {question}`, the strict slash-activation syntax;
  - a line "Stage: X. Write ALL deliverables to /mnt/user-data/outputs[/sub]/ with EXACTLY these filenames:";
  - one bullet per required file (marked REQUIRED) and per optional file;
  - "Previously produced stage artifacts are in /mnt/user-data/outputs/ — read, do not rewrite them."

  It passes no graph_id, no sim_id, and no run_summary location.
- `PipelineDriver.__init__` shallow-merges gate, timeout and sim configs over the defaults and stores `extremize_a` (`drf2/driver/pipeline.py:90-102`).
- `run(question, pipeline_id, seeds)` creates a new state (this **overwrites** any existing `state.json` for that id), saves it, and calls `_run_stages` (`drf2/driver/pipeline.py:105-110`).
- `resume(pid)` loads the state. If it is already completed it returns as is. Otherwise it sets `status="running"`, clears `error`, and calls `_run_stages` (`drf2/driver/pipeline.py:112-118`).
- `status(pid)` returns the stored dict (`drf2/driver/pipeline.py:120-121`).
- Helpers (`drf2/driver/pipeline.py:124-145`):
  - `_manifest` opens `<pid>/manifest.json`.
  - `_artifact_specs(stage, subdir)` returns keys `"{stage}:{rel}"` mapped to harness artifact paths for all required and optional files.
  - `_missing_required` checks each required file's existence.
  - `_outputs_dir` returns the resolved outputs path.
- `_stage_gate(stage, subdir)` (`drf2/driver/pipeline.py:147-164`):
  - research → `research_gate`.
  - report → `deliverable_gate` combined with `binary_conviction_gate`. Status: fail if deliverable failed; otherwise degraded if either gate has *any* issues; otherwise pass. Meta includes `binary_quality`.
  - ontology, graph and prepare → always pass. The only checks are required-file presence and manifest recording.
- `_run_stages(state)` (`drf2/driver/pipeline.py:167-209`) is the main loop:
  - Calls `ensure_thread`, copies `harness.thread_id` into state, and opens the manifest.
  - For each stage in order:
    - A completed stage not finished in this session is checked with `verify_stage`. If it verifies → `mark_stage_reused` and continue. Otherwise it logs a warning and falls through to a rebuild.
    - A stage completed in this session is skipped (the ensemble completes both run and report).
    - Dispatch:
      - `run` with seeds → `_execute_ensemble`, then marks run and report done.
      - `run` without seeds → `_execute_run`.
      - every other stage → `_execute_harness_stage`.
  - Any exception: every stage with status "running" is failed with `Type: msg`, the pipeline is set to failed, state is saved, and the loop returns.
  - After each stage it saves. If `state.status=="failed"` it returns.
  - At the end → `mark_completed`.
- `_execute_harness_stage` (`drf2/driver/pipeline.py:212-232`):
  - `start_stage` and save; build the prompt; `harness.run_stage(timeout=stage_timeouts_s[stage])`.
  - A non-ok run → `fail_stage`.
  - A missing required file → `fail_stage`.
  - A gate `hard_fail` → `fail_stage` ("gate failed: …", issues joined with "；").
  - Otherwise record the manifest and complete the stage with health ok or degraded.
- `_sim_once(seed, subdir)` (`drf2/driver/pipeline.py:234-262`):
  - Raises `RuntimeError` if no `sim_engine` is configured.
  - Reads `simulation_config.json` from the outputs **root**, regardless of subdir.
  - `sim_start(cfg_dict, seed)`, then `poll_simulation`.
  - Writes `final["run_summary"]` (if it is a dict) to `[subdir/]run_summary.json`. Otherwise it copies `final["sim_dir"]/run_summary.json` if that exists.
  - If there is an `error`, no summary and no `sim_dir` → raises `RuntimeError("simulation failed with no artifacts")`.
  - Returns `hollow_sim_gate(...)`.
- `_execute_run` (`drf2/driver/pipeline.py:264-274`): `start_stage("run")`, `_sim_once(None)`, fail if `run_summary.json` is missing, then record and complete with the gate's health.
- `_execute_ensemble` (`drf2/driver/pipeline.py:276-336`):
  - Starts both run and report.
  - Per seed `_one(seed)` (`drf2/driver/pipeline.py:285-304`):
    - creates `seed-<n>/` and runs `_sim_once(seed, subdir)`;
    - runs the report harness stage with prompt subdir `seed-<n>`;
    - a non-ok run → raise;
    - `deliverable_gate` on the seed dir; a hard fail → raise;
    - returns the parsed `seed-<n>/forecast.json`. No conviction gate runs per seed.
  - `fan_out` runs the seeds and the result goes into `state.options["ensemble"]`.
  - If `n_ok==0`: run is failed and report is set to failed directly, bypassing `_transition`.
  - Otherwise: write `ensemble_forecast.json` at the outputs root; record report specs (`report:ensemble_forecast.json` plus each seed's report files) and run specs (each seed's `run_summary.json`); complete run and report as degraded if any seed failed or reported issues.

### drf2/driver/cli.py
- Usage docstring and exit codes: 0 completed, 1 failed, 2 usage/config error (`drf2/driver/cli.py:1-13`).
- `DEFAULT_BASE_DIR = ".drf2/pipelines"`, relative to the CWD (`drf2/driver/cli.py:28`).
- `_load_driver_config(path)` (`drf2/driver/cli.py:31-44`):
  - A missing file prints "config not found … (using defaults)" to stderr and returns `{}`.
  - It imports `yaml` lazily. A YAML error → `SystemExit` with a message.
  - Returns the `driver:` section, or `{}`.
- Dry-run fixtures:
  - `_subdir_from_prompt` parses the `seed-N` subdir out of the "deliverables" line (`drf2/driver/cli.py:52-59`).
  - `_dry_fixture_forecast` returns 2 scenarios (0.6/0.4) and 10 binaries with `criteria_sharp: True` and probabilities `[0.85,0.8,0.75,0.72,0.25,0.2,0.15,0.55,0.62,0.35]` (`drf2/driver/cli.py:62-77`).
  - `_dry_effects` writes plausible artifacts for each stage. `research_report.md` gets 60 lines and `meta.json` gets score 0.9 (`drf2/driver/cli.py:80-106`).
  - `_dry_sim_engine` returns two statuses; the second carries `organic_action_count 42` (`drf2/driver/cli.py:109-114`).
- `_build_driver(dcfg, store, dry_run, thread_id)` (`drf2/driver/cli.py:120-147`):
  - Dry run: workspace `<base>/dry-workspace/<thread_id>`, sim config `{interval 0, timeout 60, stall 30}`.
  - Live: requires `driver.harness.base_url`, otherwise `SystemExit`. Builds `RunsApiHarness` from `driver.harness.{user_id, workspace_root, api_key, poll_interval_s}`. Builds `HttpSimEngine(driver.sim_engine.base_url)` only if that is set, otherwise the engine is `None`. `sim_cfg = driver.sim`.
  - Both modes pass `gates`, `stage_timeouts_s` and `ensemble.extremize_a`.
- `_print_summary` prints JSON with each stage's status, health, reused and issues. Returns 0 iff completed (`drf2/driver/cli.py:150-156`).
- `main(argv)` (`drf2/driver/cli.py:159-223`):
  - Global `--config` defaults to `drf2/config/config.yaml`, relative to the CWD. `--base-dir` is also global.
  - Subcommands:
    - `run --question [--pipeline-id] [--seeds 1,2,3] [--dry-run]`
    - `resume --pipeline-id [--dry-run]`
    - `status --pipeline-id`
  - `status` returns 2 if the pipeline is not found.
  - `run` returns 2 on bad `--seeds`. Its thread id is `driver.harness.thread_id` or `drf2-{pid}`.
  - `resume` reuses `prior.thread_id`.

### drf2/config/config.yaml (DeerFlow 2.0 harness config, `config_version: 14`)
- `config_version: 14`, log level, `token_usage` on (`drf2/config/config.yaml:15-20`).
- Models:
  - `claude-sonnet`: `deerflow.models.claude_provider:ClaudeChatModel`, model `claude-sonnet-4-6`, `max_tokens 16000`, timeout 600, 2 retries, prompt caching on, thinking budget 4096 (`drf2/config/config.yaml:33-51`).
  - `minimax-m3`: `deerflow.models.patched_minimax:PatchedChatMiniMax`, `MiniMax-M3`, `api_key: $MINIMAX_API_KEY`, `base_url https://api.minimax.io/v1`, `max_tokens 8192`, `temperature 1.0`, adaptive thinking (`drf2/config/config.yaml:53-72`).
  - Both classes exist in the vendored tree (`deer-flow-2.0.0/backend/packages/harness/deerflow/models/claude_provider.py:44`, `patched_minimax.py:98`).
- Tool groups web, file:read, file:write and bash (`drf2/config/config.yaml:78-82`). Tools (`drf2/config/config.yaml:84-132`):
  - `web_search` (DDG, max 5) and `web_fetch` (Jina, 10s);
  - `prediction_market_search` → `drf2.config.market_tools:prediction_market_search_tool` (`drf2/config/config.yaml:99-101`);
  - ls, read_file, glob (200), grep (100), write_file, str_replace, bash.
- `tool_search.enabled: true` defers the MCP tool catalogs (`drf2/config/config.yaml:135-136`).
- `tool_output` externalization: from 12000 chars, head 2000 / tail 1000 preview, `.tool-results` dir, `read_file` exempt (`drf2/config/config.yaml:139-150`).
- `suggestions` off (`drf2/config/config.yaml:152-153`).
- `loop_detection` warn 3, hard 5, per-tool frequency 30/50. Overrides: web_search/web_fetch/kg_search 80/150, kg_add_episode 120/240 (`drf2/config/config.yaml:155-176`).
- `safety_finish_reason` (`drf2/config/config.yaml:178-179`). `uploads` limits (`drf2/config/config.yaml:185-190`).
- `sandbox: LocalSandboxProvider` with **`allow_host_bash: true`** (`drf2/config/config.yaml:192-197`).
- `subagents` (`drf2/config/config.yaml:207-376`): default timeout 1800s; general-purpose 2700s / 250 turns. Custom agents:

  | Sub-agent | Model | max_turns | Timeout | Skills | Lines |
  |---|---|---|---|---|---|
  | `researcher` | claude-sonnet | 250 | 2700 | deep-research, actor-ontology-research, prediction-markets | `drf2/config/config.yaml:215-254` |
  | `ontology-builder` | minimax-m3 | 120 | 1200 | ontology-generation, kg-construction | `drf2/config/config.yaml:256-297` |
  | `sim-configurer` | minimax-m3 | 80 | 900 | simulation-design | `drf2/config/config.yaml:299-332` |
  | `forecaster` | claude-sonnet | 150 | 2700 | forecast-report, prediction-markets, deep-research | `drf2/config/config.yaml:334-376` |

  Tool whitelists:
  - `researcher`: web + market + file tools + `kg_search` / `kg_get_entities`.
  - `ontology-builder`: file tools + all 8 kg tools.
  - `sim-configurer`: file tools + four kg tools + `sim_start` / `sim_status`. Its system prompt says to "submit it with sim_start … and return the sim_id" (`drf2/config/config.yaml:311-314`).
  - `forecaster`: file, web and market tools + four kg tools + `sim_results` / `sim_interview_agents`.
- `skills.path: drf2/skills` (relative), `container_path: /mnt/skills` (`drf2/config/config.yaml:382-384`).
- `title` and `summarization` use minimax-m3. Summarization triggers at 60000 tokens, keeps 10 messages, and preserves recent skills (`drf2/config/config.yaml:386-410`).
- `memory` off, with `token_counting: char` (`drf2/config/config.yaml:413-422`). `agents_api` and `skill_evolution` off (`drf2/config/config.yaml:424-428`).
- `database: sqlite`, `.deer-flow/data` (`drf2/config/config.yaml:434-436`). `run_events: jsonl`, 10240 max trace content, token tracking (`drf2/config/config.yaml:438-441`).
- **No `driver:` section.** The CLI's live mode therefore cannot start from this file as-is (see Surprises). The harness tolerates extra top-level keys (`extra="allow"`, `deer-flow-2.0.0/backend/packages/harness/deerflow/config/app_config.py:132`), so a `driver:` block could be added.

### drf2/config/extensions_config.json
- `drf2-kg` (`drf2/config/extensions_config.json:3-19`):
  - stdio, command `/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python` (absolute, machine-specific), args `-m drf2.engines.kg.server` (**no `--graph-id`**).
  - env: PYTHONPATH (repo root and `backend/`), `MINIMAX_API_KEY`, `FALKORDB_HOST`, `FALKORDB_PORT`, `GRAPHITI_DATA_DIR` as `$VAR` placeholders.
- `drf2-simulation` (`drf2/config/extensions_config.json:20-33`): stdio, same python, `-m drf2.engines.simulation.server`, env PYTHONPATH and `MINIMAX_API_KEY`.
- All 7 skills are enabled (`drf2/config/extensions_config.json:35-43`).

### drf2/config/market_tools.py (config-reflected tool; self-contained, never imports `backend/app`)
- Constants (`drf2/config/market_tools.py:27-37`): `POLYMARKET_BASE_URL = https://gamma-api.polymarket.com`, `_TRANSIENT_STATUS = {429,500,502,503,504}`, `DEFAULT_MIN_VOLUME 200`, `PER_QUERY 8`, `MAX_TOTAL 20`, `MAX_PER_EVENT 3`, `TIMEOUT 15s`.
- `_coerce_float` returns None for NaN or bad values (`drf2/config/market_tools.py:40-48`). `_as_list` parses JSON-string lists (`drf2/config/market_tools.py:51-61`). `_yes_price` reads the "Yes" index of outcomes/outcomePrices (`drf2/config/market_tools.py:64-73`).
- `_http_get(path, params)` (`drf2/config/market_tools.py:76-101`):
  - Lazy `httpx`; missing → None.
  - Up to 2 attempts. A transient status on attempt 1 → retry. `httpx.TransportError` → retry. Any other exception → stop.
  - Logs a warning and returns None on failure. It never raises.
- `normalize_market` drops a market that is closed, lacks an id or question, has a yes-price outside the open interval (0,1), or has volume below min (`drf2/config/market_tools.py:104-138`). Output: `{market_id, exchange:"polymarket", question, implied_yes_prob (4dp), volume, liquidity, event_title, matched_query}`.
- `_cap_per_event`: at most `max_per_event` per event title (or per market_id when there is no title), then truncate to `max_total`. A value ≤0 means uncapped (`drf2/config/market_tools.py:141-156`).
- `snapshot_for_queries` (`drf2/config/market_tools.py:159-201`):
  - Default fetch is `GET /public-search?q=&limit_per_type=&events_status=active`, flattening `events[].markets[]`.
  - Each query fails independently.
  - Dedupes by market_id (first query wins), sorts by volume descending, then applies the per-event cap.
- `prediction_market_search_impl(queries:str)` splits on newlines and commas, caps at 6 queries, and returns JSON text `{queries, markets, note}` (`drf2/config/market_tools.py:204-218`).
- `prediction_market_search_tool` is a `langchain_core` `@tool`. It is `None` when langchain is absent, as in the backend venv (`drf2/config/market_tools.py:226-248`).

### drf2/engines/kg/__init__.py, README.md, requirements.txt
- The package docstring says `drf2` and `drf2.engines` are namespace packages with no `__init__.py` (`drf2/engines/kg/__init__.py:1-9`). This is true: neither `drf2/__init__.py` nor `drf2/engines/__init__.py` exists.
- requirements: `mcp>=1.24.0` only (`drf2/engines/kg/requirements.txt:5`).
- README: run command, a registration example that *includes* `--graph-id`, a tool→legacy mapping table, and the error contract `KG engine error [tool]: …` (`drf2/engines/kg/README.md:9-58`).

### drf2/engines/kg/server.py
- Puts the repo root on sys.path (`drf2/engines/kg/server.py:32-34`) and imports `tools`.
- `SERVER_NAME="drf2-kg"` and `INSTRUCTIONS` (`drf2/engines/kg/server.py:38-48`).
- `_TOOL_SPECS` holds 8 `(name, fn, description)` tuples: `kg_add_episode`, `kg_search`, `kg_get_entities`, `kg_get_edges`, `kg_causal_paths`, `kg_n_hop_subgraph`, `kg_trace_cascade`, `kg_centrality_priors` (`drf2/engines/kg/server.py:52-132`).
- `build_server(default_graph_id)` (`drf2/engines/kg/server.py:135-153`):
  - Imports `mcp.server.fastmcp.FastMCP` lazily. A missing SDK raises an `ImportError` that points at `requirements.txt`.
  - Sets the default graph id if one is given.
  - Registers each spec with `server.tool(name, description)(fn)`. The functions are **synchronous**.
- `main` parses `--graph-id` (default "") and runs `server.run(transport="stdio")` (`drf2/engines/kg/server.py:156-169`).

### drf2/engines/kg/tools.py
- Module state (`drf2/engines/kg/tools.py:24-37`):
  - `_REPO_ROOT`, `_BACKEND_DIR`;
  - `_DEFAULT_GRAPH_ID=""`;
  - `_services` dict guarded by an `RLock`;
  - `_MISSING_GRAPH_MSG`, a Chinese parameter-error string.
- Graph-id helpers (`drf2/engines/kg/tools.py:40-47`):
  - `set_default_graph_id`.
  - `_resolve_graph_id(graph_id)`: an explicit, stripped value wins; otherwise the process default.
- `_ensure_backend_importable` puts `backend/` on sys.path (`drf2/engines/kg/tools.py:50-57`).
- Lazy singletons, each locked (`drf2/engines/kg/tools.py:60-96`):
  - `_zep_tools()` → `ZepToolsService()` (`backend/app/services/zep_tools.py:466`);
  - `_graphiti_runtime()` → `get_runtime()` (`backend/app/services/graphiti_client/runtime.py:2381`);
  - `_graph_builder()` → `GraphBuilderService()` (`backend/app/services/graph_builder.py:1061`).
- Small helpers (`drf2/engines/kg/tools.py:99-128`):
  - `_err` returns `"KG engine error [tool]: Type: msg"`.
  - `_json` uses `ensure_ascii=False, default=str`.
  - `_clamp(value, lo, hi, fallback)`.
  - `_causal_edge_names` reads `ZepToolsService._CAUSAL_EDGE_NAMES` = `[CAUSES, ENABLES, CONSTRAINS, TRIGGERS, ACCELERATES]` (`backend/app/services/zep_tools.py:2666`).
  - `_resolve_entity` calls the private `svc._resolve_entity_name` (`backend/app/services/zep_tools.py:2668`) and falls back to the raw name.
- `_invalidate_read_caches(gid)` (`drf2/engines/kg/tools.py:131-146`) calls `svc.invalidate_search_cache(gid)`. It then pops the **private** `_nodes_cache[gid]` and `_edges_cache[(gid,True|False)]` entries under `svc._cache_lock` (`backend/app/services/zep_tools.py:498-507,558`). Failures are swallowed.
- Tools. Every tool returns `str` and folds exceptions into `_err`. A missing graph_id returns `_MISSING_GRAPH_MSG` without raising.
  - `kg_add_episode(body, name="episode", graph_id, source_description, reference_time)` (`drf2/engines/kg/tools.py:152-188`):
    - An empty body → error string.
    - `reference_time` is parsed with `app.utils.dates.parse_as_of` (`backend/app/utils/dates.py:38`). If unparseable, the episode is written without a timestamp and a note is added.
    - Calls `rt.add_episode(gid, name, body, source_type="text", source_description or "drf2-kg-mcp", reference_time)` (`backend/app/services/graphiti_client/runtime.py:463`), then invalidates caches.
    - Returns `"episode 已写入图谱 {gid}: uuid=…"`.
  - `kg_search(query, graph_id, limit=10, scope="edges", as_of)` (`drf2/engines/kg/tools.py:191-220`): scope is normalized to edges|nodes and limit clamped to 1..50. Calls `svc.as_of_search(...)` (`backend/app/services/zep_tools.py:918`) and returns `.to_text()`.
  - `kg_get_entities(graph_id, entity_type, limit=50)` (`drf2/engines/kg/tools.py:223-243`): `get_entities_by_type` or `get_all_nodes`. Limit clamped to 1..500. Lines are `- {node.to_text()} [uuid=…]`.
  - `kg_get_edges(graph_id, node_uuid, include_temporal=True, limit=50)` (`drf2/engines/kg/tools.py:246-273`): `get_node_edges` or `get_all_edges`, same formatting.
  - `kg_causal_paths(source, target, graph_id, max_hops=4, limit=20, causal_only=True, as_of)` (`drf2/engines/kg/tools.py:276-323`):
    - Resolves both names. `max_hops` is clamped to 1..6 and `limit` to 1..100.
    - Runs `rt.causal_paths` with the causal edge filter. If that returns no paths, it retries with `edge_types=None` and the note "无纯因果路径…".
    - JSON payload: `graph_id`, `source`, `target`, `causal_only`, `path_count`, `paths`, `note?`.
  - `kg_n_hop_subgraph(center, graph_id, max_hops=2, causal_only=False, limit=60, as_of)` (`drf2/engines/kg/tools.py:326-361`): hops clamped to 1..4, limit to 1..300. JSON `{graph_id, center, causal_only, edge_count, edges}`.
  - `kg_trace_cascade(graph_id, source, target, center, causal_only=True)` passes straight through to `svc.trace_cascade` (`drf2/engines/kg/tools.py:364-386`; `backend/app/services/zep_tools.py:2719`).
  - `kg_centrality_priors(graph_id)` calls the **private** `GraphBuilderService._get_graph_info(gid).to_dict()` (`drf2/engines/kg/tools.py:389-402`; `backend/app/services/graph_builder.py:2456`).

### drf2/engines/simulation/__init__.py, README.md, requirements.txt
- `__init__` eagerly imports `SimulationJobService` (`drf2/engines/simulation/__init__.py:13-15`). Importing the package therefore imports `SimulationRunner`.
- requirements: `mcp>=1.2` (`drf2/engines/simulation/requirements.txt:4`).
- README covers the file contract `<run_root>/<sim_id>/{simulation_config.json, run_state.json, twitter|reddit/actions.jsonl, run_summary.json, env_status.json, ipc_*}` and the tool table (`drf2/engines/simulation/README.md:8-47`).

### drf2/engines/simulation/jobs.py
- Puts `backend/` on sys.path and imports `RunnerStatus` and `SimulationRunner` at module import (`drf2/engines/simulation/jobs.py:34-43`).
- `_DEFAULT_HEARTBEAT_STALE_SECONDS = 180.0` (`drf2/engines/simulation/jobs.py:48`). `_DYNAMICS_SUMMARY_FILES` = twitter/reddit `*_dynamics_summary.json` (`drf2/engines/simulation/jobs.py:51-54`).
- `_heartbeat_stale_seconds()` reads env `DRF2_SIM_HEARTBEAT_STALE_S`; an invalid or ≤0 value falls back to 180 (`drf2/engines/simulation/jobs.py:57-66`).
- `_read_json` returns dicts only, else None (`drf2/engines/simulation/jobs.py:69-78`). `_iso_age_seconds` (`drf2/engines/simulation/jobs.py:81-92`).
- `SimulationJobService` is stateless; its methods are class methods (`drf2/engines/simulation/jobs.py:95-430`).
  - `run_root()` = `abspath(SimulationRunner.RUN_STATE_DIR)`, i.e. `backend/uploads/simulations`. This is **shared with the live app** (`drf2/engines/simulation/jobs.py:105-108`; `backend/app/services/simulation_runner.py:279-282`).
  - `_sim_dir(sim_id)` rejects ids that are not a plain basename, or that are `.` / `..` (`drf2/engines/simulation/jobs.py:110-115`).
  - `resolve(sim_id|config_path)` (`drf2/engines/simulation/jobs.py:117-155`):
    - The two arguments are mutually exclusive.
    - A `sim_id` must have a `simulation_config.json`.
    - A `config_path` must be a JSON object.
    - If `config_path` is `<run_root>/<x>/simulation_config.json`, the existing dir `<x>` is reused.
    - Otherwise it creates `drf2sim_<YYYYmmdd_HHMMSS>_<6hex>` and copies the config into it.
  - `start(...)` calls `SimulationRunner.start_simulation(simulation_id, platform="parallel", max_rounds, sim_seed, resume)` (`backend/app/services/simulation_runner.py:451-460`). It never passes `enable_graph_memory_update`/`graph_id`. Returns `{success, sim_id, sim_dir, run_state, note}` (`drf2/engines/simulation/jobs.py:159-190`).
  - `stop(sim_id)` requires the dir to exist, then calls `SimulationRunner.stop_simulation` (`drf2/engines/simulation/jobs.py:192-199`).
  - `_process_alive` uses the private `SimulationRunner._is_simulation_alive`. An exception returns None ("unknown") (`drf2/engines/simulation/jobs.py:203-213`).
  - `_assess_health(state, env_status)` (`drf2/engines/simulation/jobs.py:215-264`):
    - RUNNING / STARTING / STOPPING with a dead process → `crashed`.
    - Heartbeat older than the threshold → `stale_heartbeat`.
    - Otherwise running → `ok`.
    - COMPLETED → `completed` or `completed_with_errors`.
    - FAILED → `failed`; STOPPED → `stopped`; anything else → the raw status value.
    - `interview_ready = env_status=="alive" and process_alive`.
  - `status(sim_id)` (`drf2/engines/simulation/jobs.py:266-308`):
    - With no run_state it returns `{found:False, health:not_found}`.
    - Otherwise it returns `{success, found, health, env_status, progress{runner_status, current_round, total_rounds, progress_percent, twitter_/reddit_current_round, *_completed, resumed_from_round}, action_counts{twitter, reddit, total}, run_state}`.
  - `results(sim_id)` (`drf2/engines/simulation/jobs.py:312-360`):
    - Reads `run_summary.json`. If it is missing and the job is terminal, it calls `SimulationRunner.write_run_summary` once (`backend/app/services/simulation_runner.py:2026`).
    - Reads the dynamics summaries.
    - Returns `{partial: not terminal, run_summary, dynamics_summary, run_summary_regenerated, runner_status?, run_error?, note?}`. A `simulation_health` other than ok produces a note that the report must disclose the degradation.
  - `interview(...)` (`drf2/engines/simulation/jobs.py:364-430`):
    - Requires `env_status=="alive"`.
    - If the process is confirmed dead, it calls the private `SimulationRunner._mark_env_stopped` and raises.
    - Timeout is floored at 5s.
    - Mode dispatch: `interviews[]` → `interview_agents_batch`; `agent_id` + `prompt` → `interview_agent`; `prompt` only → `interview_all_agents`; anything else → `ValueError` (`backend/app/services/simulation_runner.py:2649,2740,2805`).
    - Adds `sim_id` and `elapsed_seconds` to the result.

### drf2/engines/simulation/server.py
- Puts the repo root on sys.path. It imports `mcp.server.fastmcp.FastMCP` at **module level**, unlike the KG server, and then `SimulationJobService` (`drf2/engines/simulation/server.py:29-36`).
- Logs to stderr only, because stdout carries the stdio protocol (`drf2/engines/simulation/server.py:39-41`).
- `mcp = FastMCP("drf2-simulation", instructions=…)` (`drf2/engines/simulation/server.py:43-52`). `_error_payload` returns `{"success":False,"error":"Type: msg"}` (`drf2/engines/simulation/server.py:55-57`).
- Async tools, each wrapping a job method in `asyncio.to_thread` and catching every exception:
  - `sim_start(config_path, sim_id, platform="parallel", max_rounds, sim_seed, resume)` (`drf2/engines/simulation/server.py:60-101`)
  - `sim_status(sim_id)` (`drf2/engines/simulation/server.py:104-127`)
  - `sim_results(sim_id)` (`drf2/engines/simulation/server.py:130-149`)
  - `sim_stop(sim_id)` (`drf2/engines/simulation/server.py:152-169`)
  - `sim_interview_agents(sim_id, prompt, agent_id, interviews, platform, timeout=120)` (`drf2/engines/simulation/server.py:172-208`)
- `__main__` logs `run_root` and runs `mcp.run(transport="stdio")` (`drf2/engines/simulation/server.py:211-214`). **There is no HTTP transport.**

### drf2/skills/custom/* (DeerFlow 2.0 SKILL.md format: YAML frontmatter `name`, `description`, `allowed-tools`, then a markdown body)
- **deep-research** (`drf2/skills/custom/deep-research/SKILL.md:1-222`):
  - allowed tools: web, file, `tool_search`, `kg_search`, `kg_get_entities`, `prediction_market_search` (`:4-15`).
  - Body sections:
    - principles, including "≤2 attempts" and "never fabricate sources" (`:20-30`);
    - KIQ decomposition (`:32-44`) and search craft (`:46-70`);
    - S1–S4 tiers and 8 signal checks (`:72-105`); Admiralty-style evidence ledger (`:107-121`);
    - verification (`:123-131`), adversarial analysis (`:133-141`), forecast-oriented research including `prediction_market_search` (`:143-153`);
    - temporal awareness (`:155-157`), budget (`:159-168`), obstacle playbook (`:170-180`);
    - synthesis gate (`:182-193`).
  - Output contract (`:195-204`): a structured handoff carrying the actor graph, situation brief, tiered sources, quantitative table and contested claims. It says "A downstream structured-extraction pass converts all of these into … `actors.json`, `sources.json` …" (`:204`).
  - Failure modes (`:206-222`).
- **actor-ontology-research** (`drf2/skills/custom/actor-ontology-research/SKILL.md:1-261`):
  - Actor/source/context triage and role classes (`:42-64`). Salience (`:66-76`). **Hard cast cap of 20** (`:78-80`).
  - Per-actor profile standard (`:84-111`). Relationship network with typed vocabulary and valence (`:115-135`). Evolution (`:139-149`).
  - 4-pass workflow (`:153-169`). AI-judge loop with at most 3 refinement rounds (`:173-186`).
  - Rubric: 8 dimensions; pass when none is below 3, dimensions 1/3/4/8 are each ≥4, and the mean is ≥4 (`:190-213`).
  - Output structure (`:217-229`). Downstream mapping (`:233-246`).
- **ontology-generation** (`drf2/skills/custom/ontology-generation/SKILL.md:1-146`):
  - Two templates, social_opinion and general_forecast, with an auto-select rule (`:29-38`).
  - Dossier seeding budget: `max(2, 8−seed_count)` new types, ≤10 total (`:40-49`).
  - Design rules, including the ≤20-actor discipline and reserved attribute names (`:51-69`).
  - JSON contract for `ontology.json` (`:71-105`) with classification metadata (`:109-123`). It says "The Pipeline Driver / graph stage applies it to the KG engine deterministically" (`:27`).
  - Checklist and failure modes (`:125-146`).
- **kg-construction** (`drf2/skills/custom/kg-construction/SKILL.md:1-99`):
  - Fixed build order, ontology first, applied by the driver (`:23-30`).
  - Chunking: ~500 chars with ~50 overlap, batches of 3–10, reference_time = content date (`:32-40`).
  - Entity-resolution rules, including an alias-merge path and an `entity_merges.json` audit (`:42-49`).
  - Causal-edge admission (`:51-60`). Retrieval playbook (`:62-74`).
  - Stage artifact `kg_build_summary.json` (`:76-78`). Gate (`:80-88`).
- **simulation-design** (`drf2/skills/custom/simulation-design/SKILL.md:1-130`):
  - allowed tools include `sim_start`, `sim_status`, `sim_results`, `sim_interview_agents` (`:4-18`).
  - 8-field `persona_design` (`:31-55`), with a **pool hard cap of 20** (`:51`).
  - World brief ≤~1400 chars (`:57-65`). Seed posts (`:67-75`). Round = 1 simulated hour; activity profiles; scheduled events clamped to the budget (`:77-85`). Follow graph (`:87-95`).
  - `simulation_config.json` contract (`:97-107`).
  - Says to run `sim_start` then poll `sim_status` (`:109`). Gate and failure modes (`:111-130`).
- **forecast-report** (`drf2/skills/custom/forecast-report/SKILL.md:1-121`):
  - Three-part brief (`:24-32`).
  - Binary contract: ≥10 forecasts, each with id, statement, probability 0.02–0.98, resolution_criteria, resolution_source, theme, horizon_year, base_rate_anchor, adjustment_rationale and source (`:34-52`).
  - Conviction rules: stdev ≥0.12, ≥3 calls at ≥0.70 or ≤0.30 (`:53-59`). Contrarian framing at 40–50% (`:61-63`).
  - Market anchoring with an explained >10pp divergence (`:65-72`). Scenario spine of 2–5 scenarios summing to ~1 (`:78-80`). Provenance discipline (`:86-92`).
  - Must write both `full_report.md` and `forecast.json` (`:99`). Gate (`:101-110`).
- **prediction-markets** (`drf2/skills/custom/prediction-markets/SKILL.md:1-60`): what markets are and are not (`:13-17`), query craft (`:19-29`), filtering rules that mirror `market_tools.py` (`:31-40`), anchor usage and the divergence rule (`:42-48`), failure modes (`:50-60`).

## Control flow

**A. Deterministic driver (CLI).**
1. `python -m drf2.driver.cli run --question Q [--seeds …] [--dry-run]` → `main` (`drf2/driver/cli.py:159-209`).
2. `_load_driver_config` reads the `driver:` section of `--config` (`drf2/driver/cli.py:31-44`).
3. `StateStore(base_dir)` (`drf2/driver/cli.py:184`).
4. `_build_driver` (`drf2/driver/cli.py:120-147`) produces a `PipelineDriver`.
5. `PipelineDriver.run` → `DriverState.new` → `store.save` → `_run_stages` (`drf2/driver/pipeline.py:105-110,167-209`).
6. `_run_stages`: `harness.ensure_thread()` (`POST /api/threads`), then loop over STAGES:
   - research / ontology / graph / prepare: `_execute_harness_stage` → `build_stage_prompt` → `RunsApiHarness.run_stage` (`POST runs`, poll `GET runs/{id}`) → `_missing_required` → `_stage_gate` (only research and report have semantic gates) → `manifest.record_stage` → `complete_stage` (`drf2/driver/pipeline.py:212-232`).
   - run, no seeds: `_execute_run` → `_sim_once` → `HttpSimEngine.sim_start` → `poll_simulation` → write `run_summary.json` → `hollow_sim_gate` (`drf2/driver/pipeline.py:234-274`).
   - run, with seeds: `_execute_ensemble` → `fan_out(seeds, _one)`. Each `_one` runs `_sim_once(seed, seed-N)`, a report harness run in `seed-N/`, and `deliverable_gate`. Then `aggregate_ensemble` → `ensemble_forecast.json` (`drf2/driver/pipeline.py:276-336`).
   - report (no seeds): `_execute_harness_stage("report")` → `deliverable_gate` + `binary_conviction_gate`.
7. `_print_summary` → exit 0/1 (`drf2/driver/cli.py:150-156`).
8. `resume`: `store.load` → `PipelineDriver.resume`. Completed stages whose manifest verifies are marked reused; the rest re-run (`drf2/driver/pipeline.py:112-118,174-184`).

**B. Harness-native chat mode (no driver).** The operator starts the DeerFlow 2.0 gateway with `DEER_FLOW_CONFIG_PATH=drf2/config/config.yaml` (`drf2/README.md:74-80`). The lead agent delegates to the custom sub-agents `researcher → ontology-builder → sim-configurer → forecaster` (`drf2/config/config.yaml:214-376`). These call:
- the MCP tools spawned from `extensions_config.json`, i.e. `kg_*` (`drf2/engines/kg/server.py:151-152`) and `sim_*` (`drf2/engines/simulation/server.py:60-208`);
- `prediction_market_search` (`drf2/config/config.yaml:99-101`).

The skills are loaded from `skills.path` (`drf2/config/config.yaml:383`).

**C. Engine call chains.**
- KG: an MCP `tools/call` reaches a FastMCP sync function (`drf2/engines/kg/tools.py:152-402`), which goes through a lazy singleton into the legacy ZepToolsService / GraphitiRuntime / GraphBuilderService. Runtime ops execute on the runtime's own background asyncio loop via `run_coroutine_threadsafe` (`backend/app/services/graphiti_client/runtime.py:224-245`).
- Simulation: an MCP tool calls `asyncio.to_thread(SimulationJobService.*)`, which calls `SimulationRunner.*` classmethods. Those spawn `backend/scripts/run_parallel_simulation.py` as a detached process group (`drf2/engines/simulation/jobs.py:170-183`).

## Data & artifacts

| Artifact | Path pattern | Writer | Reader | Format / key fields |
|---|---|---|---|---|
| Driver state | `<base_dir>/<pid>/state.json` (base default `.drf2/pipelines`, CWD-relative; not gitignored) | `StateStore.save` (`drf2/driver/state.py:211-213`) | `StateStore.load` (`drf2/driver/state.py:215-230`) | `DriverState.to_dict`: `schema_version`, `pipeline_id`, `question`, `status`, `current_stage`, `thread_id`, `seeds`, `options.ensemble`, `stages{name→StageRecord}` |
| Manifest | `<base_dir>/<pid>/manifest.json` | `ArtifactManifest.save` (`drf2/driver/manifest.py:70-71`) | `verify_stage` (`drf2/driver/manifest.py:103-138`) | `{"<stage>:<rel>": {path, sha256, bytes, stage, recorded_at, schema_ok}}` |
| Stage outputs | `<workspace_root>/users/<uid>/threads/<tid>/user-data/outputs/<rel>` (sandbox `/mnt/user-data/outputs/`) | harness agent (LLM) per prompt (`drf2/driver/pipeline.py:72-84`) | gates and manifest | filenames per `STAGE_ARTIFACTS` (`drf2/driver/pipeline.py:46-55`) |
| `research_report.md`, `actor_dossier.md`, `meta.json` | outputs root | research stage | `research_gate` (`drf2/driver/gates.py:79,94,102`) | markdown; `meta.json.research_quality.score` |
| `forecast.json` | outputs root or `seed-N/` | report stage | `deliverable_gate`, `binary_conviction_gate`, ensemble loop (`drf2/driver/pipeline.py:303-304`) | `binary_forecasts[] {probability, criteria_sharp?, theme?, …}`, `scenarios[] {name, probability, key_drivers, resolution_criteria}` |
| `run_summary.json` | outputs root or `seed-N/` | driver `_sim_once` via `write_json_atomic` (`drf2/driver/pipeline.py:246-253`) | `hollow_sim_gate`, manifest | legacy run summary: `organic_action_count`, `simulation_health` |
| `ensemble_forecast.json` | outputs root | `_execute_ensemble` (`drf2/driver/pipeline.py:320-321`) | — | `aggregate_ensemble` output (`drf2/driver/ensemble.py:90-100`) |
| `section_*.md` | report dir | (legacy convention; no DRF-2 skill writes them) | `deliverable_gate` (`drf2/driver/gates.py:194-200`) | markdown |
| Dry-run workspace | `<base_dir>/dry-workspace/<thread_id>/…` | `_dry_effects` (`drf2/driver/cli.py:80-106`) | the pipeline | fixture files |
| Sim dir | `backend/uploads/simulations/<sim_id or drf2sim_YYYYmmdd_HHMMSS_xxxxxx>/` | `SimulationJobService.resolve`/`start` (`drf2/engines/simulation/jobs.py:151-155`) and the legacy runner | status/results/interview | `simulation_config.json`, `run_state.json`, `*/actions.jsonl`, `run_summary.json`, `env_status.json`, `{twitter,reddit}_dynamics_summary.json`, `ipc_commands/`, `ipc_responses/` (`drf2/engines/simulation/README.md:8-17`) |
| KG data | Graphiti/FalkorDB group `graph_id` | `kg_add_episode` (`drf2/engines/kg/tools.py:177-184`) | the other kg tools | Graphiti episodes, nodes, edges |
| Harness DB / events | `.deer-flow/data` (sqlite), jsonl run events | DeerFlow harness (`drf2/config/config.yaml:434-441`) | — | — |

In-memory structures:
- `_services` singleton registry (`drf2/engines/kg/tools.py:31-32`).
- `DryRunHarness.prompts` (`drf2/driver/harness_client.py:158`).
- `DrySimEngine.started` / `stopped` (`drf2/driver/harness_client.py:245-246`).
- `done_now` set in `_run_stages` (`drf2/driver/pipeline.py:171`).
- Ensemble buckets (`drf2/driver/ensemble.py:40-57`).

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| CLI `--config` | `drf2/config/config.yaml` (CWD-relative) | source of the `driver:` section | `drf2/driver/cli.py:161` |
| CLI `--base-dir` / `driver.base_dir` | `.drf2/pipelines` | state root | `drf2/driver/cli.py:162,184,28` |
| `driver.harness.base_url` | none (live runs require it) | gateway URL | `drf2/driver/cli.py:129-132` |
| `driver.harness.user_id` | `default` | workspace path segment | `drf2/driver/cli.py:135` |
| `driver.harness.workspace_root` | None (→ `HarnessError` on artifact access) | host path to the harness data dir | `drf2/driver/cli.py:136`, `drf2/driver/harness_client.py:139-140` |
| `driver.harness.api_key` | None | Bearer header | `drf2/driver/cli.py:137`, `drf2/driver/harness_client.py:78-79` |
| `driver.harness.poll_interval_s` | 5.0 | run poll interval | `drf2/driver/cli.py:138` |
| `driver.harness.thread_id` | `drf2-<pid>` | overrides the thread used for runs | `drf2/driver/cli.py:202` |
| `driver.sim_engine.base_url` | None (→ RUN stage raises) | HttpSimEngine base | `drf2/driver/cli.py:139-140`, `drf2/driver/pipeline.py:236-237` |
| `driver.sim.{timeout_s,stall_s,interval_s}` | 14400 / 1800 / 30 | `poll_simulation` budget and watchdog | `drf2/driver/pipeline.py:67-69,242-244` |
| `driver.gates.{min_report_chars, research_quality_floor, binary_min_count, min_report_bytes, structured_forecast_required}` | 400 / 0.0 / 10 / 2000 / True | gate thresholds | `drf2/driver/pipeline.py:60-66` |
| `driver.stage_timeouts_s.<stage>` | research 3600, ontology 1800, graph 3600, prepare 1800, report 3600 | per-stage `poll_run` timeout | `drf2/driver/pipeline.py:57-59` |
| `driver.ensemble.extremize_a` | None (arithmetic mean) | log-odds extremizing factor | `drf2/driver/cli.py:142-147`, `drf2/driver/ensemble.py:59-62` |
| `DRF2_SIM_HEARTBEAT_STALE_S` | 180 | stale-heartbeat threshold in `sim_status` | `drf2/engines/simulation/jobs.py:57-66` |
| KG `--graph-id` | "" | process default graph | `drf2/engines/kg/server.py:161-167` |
| `MINIMAX_API_KEY` | env | MiniMax model and engine env passthrough | `drf2/config/config.yaml:57`, `drf2/config/extensions_config.json:13,30` |
| `FALKORDB_HOST`, `FALKORDB_PORT`, `GRAPHITI_DATA_DIR` | env passthrough | legacy KG backend (`backend/app/config.py:1021-1032`) | `drf2/config/extensions_config.json:14-16` |
| `PYTHONPATH` (engine env) | absolute `<repo>:<repo>/backend` | import resolution | `drf2/config/extensions_config.json:12,29` |
| `DEER_FLOW_CONFIG_PATH`, `DEER_FLOW_EXTENSIONS_CONFIG_PATH` | (operator) | point the harness at drf2 configs | `drf2/README.md:76-77` |
| `SETUP_DRF2` | 0 | `setup.sh` installs `mcp` into backend/.venv | `setup.sh:750` |
| harness `skills.path` | `drf2/skills` (relative to the harness project root/CWD) | skill discovery | `drf2/config/config.yaml:383` |
| harness `sandbox.allow_host_bash` | true | bash on host | `drf2/config/config.yaml:194` |
| harness `subagents.custom_agents.*.timeout_seconds` | 2700 / 1200 / 900 / 2700 | sub-agent budgets | `drf2/config/config.yaml:254,297,332,376` |
| harness `summarization.trigger.tokens` | 60000 | context compression | `drf2/config/config.yaml:395-397` |
| Polymarket defaults | min_volume 200, per_query 8, max_total 20, max_per_event 3, timeout 15s, ≤6 queries | market filtering | `drf2/config/market_tools.py:33-37,208` |

## External calls

| Target | Kind | Anchor | Notes |
|---|---|---|---|
| DeerFlow 2.0 gateway `POST /api/threads` | HTTP (urllib) | `drf2/driver/harness_client.py:96` | idempotent thread create |
| `POST /api/threads/{tid}/runs` | HTTP | `drf2/driver/harness_client.py:107` | background run; LLM work happens server-side |
| `GET /api/threads/{tid}/runs/{rid}` | HTTP poll | `drf2/driver/harness_client.py:116` | every `poll_interval_s` |
| `POST …/runs/{rid}/cancel` | HTTP | `drf2/driver/harness_client.py:124` | on driver timeout, best effort |
| Sim engine `POST /simulations`, `GET /simulations/{id}`, `POST …/stop` | HTTP | `drf2/driver/harness_client.py:223,230,234` | **no server implements this** |
| Polymarket Gamma `GET https://gamma-api.polymarket.com/public-search` | HTTP (httpx) | `drf2/config/market_tools.py:87-88,172-173` | keyless; 1 retry on transient errors |
| Graphiti/FalkorDB (+ the LLM/embedder used inside the legacy runtime for extraction/search) | DB/LLM via legacy | `drf2/engines/kg/tools.py:177,211,231,302,345,378,399` | the drf2 code makes no direct LLM calls |
| OASIS subprocess `backend/scripts/run_parallel_simulation.py` | subprocess (legacy runner) | `drf2/engines/simulation/jobs.py:177-183` | detached process group; agents call LLMs |
| Interview IPC (file commands/responses) | filesystem IPC | `drf2/engines/simulation/jobs.py:412-423` | blocks up to `timeout` |
| MCP stdio transport | stdio JSON-RPC | `drf2/engines/kg/server.py:169`, `drf2/engines/simulation/server.py:214` | spawned by the harness |
| Model providers (Anthropic via claude-cli creds, MiniMax) | LLM (harness-side) | `drf2/config/config.yaml:33-72` | configured, not called by drf2 Python |

## Cross-module edges

Inbound (who calls into drf2):
- `backend/tests/test_drf2_driver.py` covers the state machine, manifest, gates, ensemble, poll watchdog, RunsApiHarness with fake HTTP, the dry-run pipeline including ensemble and resume, and the CLI (classes at `backend/tests/test_drf2_driver.py:38-655`).
- `backend/tests/test_drf2_kg.py` tests the tool registry, argument validation, pass-through, error surfacing and MCP integration with fake services (`backend/tests/test_drf2_kg.py:182-445`).
- `backend/tests/test_drf2_simulation.py` tests start, status, results, stop, interview and the MCP server tools with `FakePopen` (`backend/tests/test_drf2_simulation.py:137-500`).
- `backend/tests/test_drf2_skills_config.py` covers:
  - SKILL.md parsing with the real DeerFlow parser (skipped if `deer-flow-2.0.0` is absent) (`backend/tests/test_drf2_skills_config.py:34,218,256-297`);
  - config.yaml and extensions_config checks (`backend/tests/test_drf2_skills_config.py:299-439`);
  - tool-name drift guards that regex-scrape the engine sources (`backend/tests/test_drf2_skills_config.py:441-466`);
  - market_tools logic (`backend/tests/test_drf2_skills_config.py:492-570`);
  - bridge↔drf2 skill heading-subset drift (`backend/tests/test_drf2_skills_config.py:575-621`).
- `setup.sh:738-814` (opt-in `SETUP_DRF2=1`) installs requirements and prints commands.
- Runtime inbound edges, which exist only once deployed:
  - the DeerFlow 2.0 harness reflects `drf2.config.market_tools:prediction_market_search_tool` (`drf2/config/config.yaml:101`);
  - the harness spawns `-m drf2.engines.kg.server` / `-m drf2.engines.simulation.server` (`drf2/config/extensions_config.json:7-10,24-27`);
  - the harness loads skills from `drf2/skills` (`drf2/config/config.yaml:383`).
- No inbound import from `backend/app`, `deerflow_bridge/` or `frontend/`. `deerflow_bridge/market_tools.py:3` is a copy/adaptation, not an import.

Outbound (what drf2 calls):
- `backend/app/utils/atomic.write_json_atomic` (`drf2/driver/state.py:22`, `drf2/driver/manifest.py:24`, `drf2/driver/pipeline.py:32`)
- `backend/app/services/forecast_extractor._binary_quality` (`drf2/driver/gates.py:32`)
- `backend/app/services/ensemble._ensemble_agreement/_extremized_logodds/_mean/_norm_name/_stdev` (`drf2/driver/ensemble.py:19-25`)
- `backend/app/services/zep_tools.ZepToolsService`. Public: `as_of_search`, `get_entities_by_type`, `get_all_nodes`, `get_all_edges`, `get_node_edges`, `trace_cascade`, `invalidate_search_cache`. Private: `_resolve_entity_name`, `_cache_lock`, `_nodes_cache`, `_edges_cache`, `_CAUSAL_EDGE_NAMES` (`drf2/engines/kg/tools.py:66,116-146,211,231,260-263,378`).
- `backend/app/services/graphiti_client/runtime.get_runtime().add_episode/causal_paths/n_hop_subgraph` (`drf2/engines/kg/tools.py:79,177,302,345`)
- `backend/app/services/graph_builder.GraphBuilderService._get_graph_info` (private) (`drf2/engines/kg/tools.py:92,399`)
- `backend/app/utils/dates.parse_as_of` (`drf2/engines/kg/tools.py:171`)
- `backend/app/services/simulation_runner.SimulationRunner`. Public: `start_simulation`, `stop_simulation`, `get_run_state`, `get_env_status_detail`, `write_run_summary`, `interview_agent`, `interview_agents_batch`, `interview_all_agents`, `RUN_STATE_DIR`. Private: `_is_simulation_alive`, `_mark_env_stopped` (`drf2/engines/simulation/jobs.py:108,177,198,211,270,281,331,398,413-423`).
- DeerFlow 2.0 harness HTTP API (`drf2/driver/harness_client.py:94-134`). The `deerflow.*` classes are named in `config.yaml` (`drf2/config/config.yaml:35,55,88,94,106-132,193`).

## Invariants, gates, validation

- **Gates never consult an LLM.** They read files only (`drf2/driver/gates.py:1-8`).
  - `research_gate` and `deliverable_gate` can hard-fail (`drf2/driver/gates.py:83-91,210-225`).
  - `hollow_sim_gate` and `binary_conviction_gate` can only degrade (`drf2/driver/gates.py:158,185`).
  - ontology, graph and prepare have no semantic gate (`drf2/driver/pipeline.py:163-164`).
- **Required-artifact presence** is checked after every harness stage and after the single-seed run (`drf2/driver/pipeline.py:222-225,268-271`).
- **Stage transition legality**: illegal transitions raise `InvalidTransition` (`drf2/driver/state.py:107-114`).
- **Schema guard**: a state file from a newer schema is refused (`drf2/driver/state.py:220-222`). The migration chain is empty (`drf2/driver/state.py:183`).
- **Pipeline-id whitelist**: `^[A-Za-z0-9._-]{1,64}$` (`drf2/driver/state.py:185,194-197`). **Sim-id basename check** (`drf2/engines/simulation/jobs.py:113-114`).
- **Hash-verified reuse on resume**: a completed stage is reused only if `verify_stage` passes; an empty manifest degrades to trusting existence (`drf2/driver/manifest.py:103-106`, `drf2/driver/pipeline.py:174-182`).
- **Atomic writes** for state, manifest, run_summary and ensemble output (`drf2/driver/state.py:213`, `drf2/driver/manifest.py:71`, `drf2/driver/pipeline.py:248,252,321`).
- **Simulation watchdog**: no round advance within `stall_s` → `sim_stop` and an error; total time over `timeout_s` → `sim_stop` and an error (`drf2/driver/harness_client.py:286-294`).
- **KG input validation**: graph_id required (explicit or default), non-empty body/query/source/target/center, clamped limits and hops (`drf2/engines/kg/tools.py:160-164,199-206,289-290,338-339,108-113`).
- **Sim engine**: `config_path` must be a JSON object; `sim_id` and `config_path` are mutually exclusive; liveness is double-checked before an interview (`drf2/engines/simulation/jobs.py:128-144,388-403`).
- **Market anchor validity**: open, not closed, price strictly inside (0,1), volume ≥200, per-event cap (`drf2/config/market_tools.py:118-128,141-156`).
- **Skill-level invariants** (enforced only by prompt):
  - cast ≤20 (`drf2/skills/custom/actor-ontology-research/SKILL.md:78-80`);
  - entity types ≤10 (`drf2/skills/custom/ontology-generation/SKILL.md:46`);
  - persona pool ≤20 (`drf2/skills/custom/simulation-design/SKILL.md:51`);
  - ≥10 binaries with stdev ≥0.12 (`drf2/skills/custom/forecast-report/SKILL.md:36,53-59`).
- **Drift guards** (tests): the engine tool names must equal the sets pinned in the tests, config and skills (`backend/tests/test_drf2_skills_config.py:441-466`).

## Failure modes & recovery

- Harness HTTP error, network failure or non-JSON → `HarnessError` (`drf2/driver/harness_client.py:83-91`). Inside a stage this is caught by `_run_stages`, which marks running stages failed and saves (`drf2/driver/pipeline.py:195-202`). Recovery is `cli resume`.
- Run ends with error, timeout or interrupted → `fail_stage` with "run ended with status=…" (`drf2/driver/pipeline.py:219-221`). A driver timeout cancels the run on a best-effort basis (`drf2/driver/harness_client.py:122-128`).
- Missing required artifact → stage failed (`drf2/driver/pipeline.py:222-225`). Gate hard-fail → stage failed (`drf2/driver/pipeline.py:226-229`).
- Simulation:
  - error with no summary and no sim_dir → `RuntimeError` → the run stage fails (`drf2/driver/pipeline.py:255-257`);
  - hollow, truncated or errored with a summary → degraded, continue (`drf2/driver/pipeline.py:258-262,273`);
  - stall or timeout → `sim_stop` and an error (`drf2/driver/harness_client.py:286-294`).
- Ensemble: a per-seed failure is isolated (`drf2/driver/ensemble.py:113-120`). All seeds failed → run and report both failed (`drf2/driver/pipeline.py:309-319`).
- Corrupted or tampered artifact on resume → `verify_stage` fails, the stage is rebuilt (completed→running is allowed), and a message is recorded (`drf2/driver/pipeline.py:180-182`).
- Corrupt `state.json` → `json` exception propagates (no swallowing) (`drf2/driver/state.py:216-219`). Newer schema → `IncompatibleStateSchema`.
- KG tool failures are folded into text and never crash the stdio server (`drf2/engines/kg/tools.py:99-101`). Cache-invalidation failures are swallowed (`drf2/engines/kg/tools.py:145-146`).
- Sim tool failures become `{"success":False,"error":…}` payloads (`drf2/engines/simulation/server.py:55-57,99-101`).
  - Crashed or orphaned jobs are reported as health `crashed` with a hint to use `sim_start(resume=True)` (`drf2/engines/simulation/jobs.py:228-231`).
  - A stale "alive" env is marked stopped before an interview (`drf2/engines/simulation/jobs.py:394-403`).
  - A missing summary on a terminal job is regenerated once (`drf2/engines/simulation/jobs.py:329-332`).
- Polymarket failures return an empty market list with a note, never an exception (`drf2/config/market_tools.py:100-101,186-188,215-216`).
- CLI config parse error → exit 2. Missing `base_url` (live) → exit 2. Unknown pipeline → exit 2 (`drf2/driver/cli.py:179-191,203-207,212-221`).

## Surprises

1. **Not wired into the live app.** No import from `backend/app`, `deerflow_bridge` or `frontend`. The only entry points are tests and an opt-in `setup.sh` block. The README states that no live harness run has been performed (`drf2/README.md:170-172`; `setup.sh:750`).
2. **The driver's simulation contract has no server (suspected integration bug).**
   - `HttpSimEngine` expects HTTP `POST /simulations` with a config *dict*, plus `GET /simulations/{id}` returning top-level `completed`, `error`, `current_round`, `run_summary` and `sim_dir` (`drf2/driver/harness_client.py:193-236`, `drf2/driver/pipeline.py:245-262`).
   - The simulation engine only serves stdio MCP (`drf2/engines/simulation/server.py:214`). Its `sim_start` takes `config_path` / `sim_seed`, not a dict / `seed` (`drf2/engines/simulation/server.py:61-67`). Its status payload nests `current_round` under `progress` and has no `completed` key (`drf2/engines/simulation/jobs.py:283-308`).
   - Even an HTTP shim passing `status()` through verbatim would leave `current_round` as None forever. `poll_simulation` would then never see completion, and the stall watchdog would kill every sim after `stall_s` (1800s) (`drf2/driver/harness_client.py:279-290`).
   - The client itself carries a TODO saying these paths are not pinned (`drf2/driver/harness_client.py:199`).
3. **Possible double simulation start (suspected).** The prepare stage activates the `simulation-design` skill. Its `allowed-tools` include `sim_start`, and its body says to run `sim_start` then poll (`drf2/skills/custom/simulation-design/SKILL.md:15,109`). The sim-configurer sub-agent prompt likewise says to submit with sim_start (`drf2/config/config.yaml:311-314`). The driver's RUN stage then starts its own simulation (`drf2/driver/pipeline.py:241`). Nothing in the prepare prompt tells the agent not to start one (`drf2/driver/pipeline.py:72-84`).
4. **The ontology is never applied (doc-vs-code drift).** The ontology-generation and kg-construction skills, the ontology-builder prompt, and README §3.4 all say the Pipeline Driver applies `ontology.json` to the graph deterministically before ingestion (`drf2/skills/custom/ontology-generation/SKILL.md:27`, `drf2/skills/custom/kg-construction/SKILL.md:27`, `drf2/config/config.yaml:266-267`, `drf2/README.md:108-109`). In fact:
   - The driver only checks that `ontology.json` exists (`drf2/driver/pipeline.py:50,163-164`).
   - The KG MCP server exposes no set-ontology tool (`drf2/engines/kg/server.py:52-132`), although `GraphitiRuntime.set_ontology` exists (`backend/app/services/graphiti_client/runtime.py:442`).
5. **No graph_id plumbing (suspected).** The registered KG server has no `--graph-id` (`drf2/config/extensions_config.json:8-10`), even though the KG README's example includes it (`drf2/engines/kg/README.md:28`). No stage prompt or skill names a graph id (`drf2/driver/pipeline.py:72-84`). Every `kg_*` call therefore returns `_MISSING_GRAPH_MSG` (`drf2/engines/kg/tools.py:34-37,160-162`) unless the model invents an id.
6. **Skill claims that the engine does not implement.**
   - kg-construction says to "poll the tool's status response" for asynchronous episode processing (`drf2/skills/custom/kg-construction/SKILL.md:29`). `kg_add_episode` is synchronous and there is no status tool (`drf2/engines/kg/tools.py:176-186`).
   - The skill recommends "typed filters (edge types / entity types)" for `kg_search` (`drf2/skills/custom/kg-construction/SKILL.md:66`). `kg_search` has no such parameters (`drf2/engines/kg/tools.py:191-197`).
   - The skill describes an alias-merge path that writes `entity_merges.json` (`drf2/skills/custom/kg-construction/SKILL.md:48`). That audit is written by the legacy orchestrator, not by the `add_episode` path drf2 uses (`backend/app/services/pipeline_orchestrator.py:12593-12604`). This one is suspected.
7. **The conviction gate will likely always degrade on real runs (suspected).**
   - `_binary_quality` counts `criteria_sharp` flags, and a binary set passes only if at least 80% are set (`backend/app/services/forecast_extractor.py:1615,1631`). In legacy those flags are set by `_normalize_binaries`.
   - DRF-2 has no normalization step, and the forecast-report skill's field list never mentions `criteria_sharp` (`drf2/skills/custom/forecast-report/SKILL.md:40-51`).
   - Only the dry-run fixture sets it (`drf2/driver/cli.py:73`).
   - Separately, `_stage_gate` marks report health "degraded" whenever the conviction gate has *any* issue, even if it passed (`drf2/driver/pipeline.py:159-160`). The dry-run fixture has no `theme`, so `_binary_quality` appends "all forecasts share a single theme". The dry-run report is therefore "degraded", not "pass", despite the fixture comment "pass every gate" (`drf2/driver/cli.py:48-49`; `backend/app/services/forecast_extractor.py:1644-1645`).
8. **Resuming after a crash fails once (suspected bug).**
   - If the process died mid-stage, the stage stays `running`. On `resume`, `start_stage` attempts running→running, which `_STAGE_TRANSITIONS` forbids (`drf2/driver/state.py:30,107-111`).
   - The exception handler then fails the stage and the pipeline (`drf2/driver/pipeline.py:195-202`). Only a second `resume` (failed→running) proceeds.
9. **No downstream invalidation on rebuild (suspected).** When an upstream stage fails verification and is rebuilt, later completed stages are still reused if their own hashes verify. They are not invalidated, so stale downstream artifacts can mix with the new upstream (`drf2/driver/pipeline.py:172-184`).
10. **Ensemble resume asymmetry (suspected).** If `run` verifies but `report` does not, `report` is rebuilt as a plain single harness stage at the outputs root via `_execute_harness_stage`, not as an ensemble (`drf2/driver/pipeline.py:186-194`). No `run_summary.json` exists at the root in ensemble mode, and the per-seed and pooled outputs are not regenerated. The ensemble path also never runs `binary_conviction_gate` per seed (`drf2/driver/pipeline.py:296-302`). Binaries are not pooled at all (`drf2/driver/ensemble.py:42-57`).
11. **An expensive stage runs before a config error surfaces (suspected).**
    - If `driver.harness.workspace_root` is unset, `artifact_path` raises only *after* the harness stage has run, so a full research run is wasted before the stage fails (`drf2/driver/harness_client.py:139-140`, `drf2/driver/pipeline.py:217-222`). On resume, the same error occurs in `verify_stage`, outside the try block, and crashes the CLI (`drf2/driver/pipeline.py:175`).
    - With no `sim_engine.base_url`, research through prepare all run before the RUN stage raises (`drf2/driver/cli.py:140`, `drf2/driver/pipeline.py:236-237`).
12. **Shipped config cannot drive a live run.** `config.yaml` has no `driver:` section (`drf2/config/config.yaml:1-441`). `cli run` without `--dry-run` therefore exits 2 with "driver.harness.base_url missing", including the exact command that `setup.sh` prints (`drf2/driver/cli.py:131-132`; `setup.sh:808-809`).
13. **The README's `skills.path` claim is stale.** The README says `skills.path` is absolute (`drf2/README.md:82-84`). Commit `f8482a7` made it relative (`drf2/config/config.yaml:383`).
    - The harness resolves a relative path against `DEER_FLOW_PROJECT_ROOT` or the CWD (`deer-flow-2.0.0/backend/packages/harness/deerflow/config/skills_config.py:45-47`, `.../config/runtime_paths.py:7-16`).
    - So following README §3.2 (`cd deer-flow-2.0.0; make dev`) would look for `deer-flow-2.0.0/drf2/skills`. This consequence is suspected.
    - `extensions_config.json` still hard-codes absolute `/Users/rogerlin/...` paths (`drf2/config/extensions_config.json:6,12,23,29`).
14. **Docs reference a missing file.** `REDESIGN.md` is cited throughout (`drf2/README.md:4,35`, `drf2/driver/__init__.py:2`, `drf2/driver/legacy.py:1`, `drf2/config/market_tools.py:3`, `drf2/CLEANUP_LOCAL.md:5`) but no longer exists. It was removed in commit `5ee4215`.
15. **Stale line numbers and sizes in provenance comments.** `gates.py` cites `pipeline_orchestrator` at ~L820-845 / ~L3054 / ~L2464 / ~L2387 (`drf2/driver/gates.py:10-16`). The actual locations are `_surface_research_quality` :10564, `_assess_run_health` :9351 and `_assess_report_health` :9161 (`backend/app/services/pipeline_orchestrator.py:9161,9351,10564`). `state.py` says the orchestrator is "4.2K LOC" (`drf2/driver/state.py:4`); it is 13,492 lines.
16. **The "lightweight / Flask-free" claim is inaccurate.**
    - `gates.py` copies `LLM_ERROR_MARKERS` to avoid importing heavy services (`drf2/driver/gates.py:63-64`). Yet it imports `app.services.forecast_extractor` (`drf2/driver/gates.py:32`), which executes `backend/app/services/__init__.py`, and that eagerly imports `OntologyGenerator`, `GraphBuilderService`, `SimulationManager`, `SimulationRunner` and others (`backend/app/services/__init__.py:5-31`).
    - Any `app.*` import also runs Flask setup (`backend/app/__init__.py:15-18`). This contradicts "Legacy modules are reused by import (they are Flask-free)" (`drf2/README.md:36-37`).
    - The marker tuple is duplicated with `pipeline_orchestrator.py:2748-2754`, so it can drift.
17. **The KG server blocks its event loop.** The KG tools are sync functions registered on FastMCP (`drf2/engines/kg/server.py:151-152`). mcp 1.24.0 calls sync tools directly on the event loop (`backend/.venv/.../mcp/server/fastmcp/utilities/func_metadata.py`, `fn(**arguments_parsed_dict)`). Long Graphiti ops therefore stall the stdio server for their duration, up to the runtime's default op timeout (`backend/app/services/graphiti_client/runtime.py:224-233`). The simulation server avoids this with `asyncio.to_thread` (`drf2/engines/simulation/server.py:94`).
18. **Reliance on private legacy APIs.** The engines use private legacy APIs: `_resolve_entity_name`, `_cache_lock`, `_nodes_cache`, `_edges_cache`, `_get_graph_info`, `_is_simulation_alive` and `_mark_env_stopped` (`drf2/engines/kg/tools.py:126,141-144,399`; `drf2/engines/simulation/jobs.py:211,398`). These are brittle against legacy refactors.
19. **Shared simulation directory.** The simulation engine writes into the live app's `backend/uploads/simulations` (`drf2/engines/simulation/jobs.py:105-108`). DRF-2 jobs (`drf2sim_*`) and legacy sims share one namespace and the runner's class-level registry.
20. **Dead or unused items.**
    - `_PIPELINE_STATUSES` and its "cancelled" status (`drf2/driver/state.py:34`).
    - `StateStore.artifacts_dir` is never used by the pipeline (`drf2/driver/state.py:208-209`).
    - `Harness.run_stage(context=…)` is never passed by the pipeline (`drf2/driver/pipeline.py:217-218`).
    - `README.md:97-98` mentions an "embedded DeerFlowClient" transport that is only a TODO (`drf2/driver/harness_client.py:10-11`).
    - `README.md:99` says the driver "calls the engine tools directly for the health gates". The gates read files and never call the KG or sim MCP tools (`drf2/driver/gates.py:74-226`).
21. **Mismatch between the two drive modes.** The driver activates exactly one skill per stage on the lead agent via `/skill` (`drf2/driver/pipeline.py:37-43,77`). It never uses the four custom sub-agents, their per-stage model routing, or the `actor-ontology-research` / `prediction-markets` skills. The driver's research stage lists `actor_dossier.md` / `actors.json` as optional (`drf2/driver/pipeline.py:47-49`), but the `deep-research` skill never instructs writing them; it defers to "a downstream structured-extraction pass" that DRF-2 lacks (`drf2/skills/custom/deep-research/SKILL.md:204`). The research gate's `meta.json.research_quality` is likewise never produced by any DRF-2 skill (`drf2/driver/gates.py:102-108`).
22. **Inconsistent timeouts.** The driver's stage timeouts (research and report 3600s) differ from the sub-agent timeouts (2700s) and from the README's "45 min budget" (`drf2/driver/pipeline.py:57-59`, `drf2/config/config.yaml:254,376`, `drf2/README.md:105,114`).
23. **Thread reuse risk.** `run` always overwrites state for an existing `--pipeline-id` (`drf2/driver/pipeline.py:107-109`). A configured `driver.harness.thread_id` makes every pipeline share one harness thread, whose outputs dir then collides (`drf2/driver/cli.py:202`, `drf2/driver/harness_client.py:141-142`).
