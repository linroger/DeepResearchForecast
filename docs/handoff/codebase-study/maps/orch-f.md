# orch-f — Orchestrator part F: artifact specs, reuse validation, ETA/heartbeat, manifests, telemetry, quality surfacing, synthesis recovery

Anchor legend: `PO:N` means `backend/app/services/pipeline_orchestrator.py:N`. Every other anchor is written as a path relative to the repo root. The slice is `PO:9500-11059` on branch `main`, read on 2026-10-11. Every line of the slice was read. Helpers outside the slice were read only to explain what the slice calls.

---

## Purpose & position in the pipeline

This slice is the support layer around the six-stage `_run` loop (`PO:11883`). It does not run a stage itself. It provides these pieces:

1. **One source of truth for each stage's deep-linkable files**: `_stage_artifact_specs` (`PO:9500`) and the viz helpers (`PO:9564-9628`). Three users share it: completion-time registration, reuse-time integrity checks and in-flight partial discovery (`PO:9501-9505`).
2. **Integrity manifest `handoff/manifest.json` (I-4-3)**: `_record_stage_artifacts` writes it (`PO:9745-9755`). `_validate_reuse`/`_reuse_ok` check it before any completed stage is reused (`PO:9798-9907`). [verifier: overstated — only GRAPH/PREPARE/RUN/REPORT go through `_reuse_ok` and legacy (no-contract) RESEARCH calls `_validate_reuse` directly (`PO:11948`); contract-backed RESEARCH is gated by `_validate_research_contract` (`PO:11920-11921`) and ONTOLOGY reuse is gated only on `project.ontology` (`PO:12312-12314`), so the `ontology` manifest row is never checked]
3. **RUN/simulation reuse and completion gates (DEFECT-1/DEFECT-2)**: `_run_reuse_ready`, `_sim_platform_completion_missing`, `_completed_sim_reusable`, `_require_run_completion_evidence` and `_publish_run_summary` (`PO:9909-10122`).
4. **Live/partial artifacts (I-4-6)**: provisional `<name>_partial` pointers, registered from progress callbacks (`PO:10126-10240`).
5. **Liveness (I-5-6/I-4-1)**: the ETA/staleness estimator, the status-API heartbeat block and the wall-clock heartbeat thread (`PO:10244-10370`).
6. **Reproducibility manifest `run.json` (I-8-1)**: `_write_run_manifest` and `_update_manifest` (`PO:10374-10426`).
7. **Telemetry fold-in**: research telemetry (I-5-7, `PO:10430`) and simulation-subprocess telemetry, recorded exactly once (DEFECT-3, `PO:10473`).
8. **Quality surfacing**: the research-quality scorecard and budget-degradation summary (I-0-3, `PO:10564`), an advisory forecast-confidence penalty (R2-RES-3, `PO:10645-10736`) and a decision-channel outcome summary (SIM-ADD-2, `PO:10738`).
9. **As-of anchor validation (R2-RES-7)**: `_validate_as_of_date` (`PO:10794`).
10. **Synthesis-only research recovery**: `_run_research_synthesis_recovery` (`PO:10841-11056`). It reruns only global synthesis from sealed evidence lanes. It allows at most 2 attempts and promotes a result only when it passes.

Callers: `_run`, the stage updater/completer (`PO:8949-9050`), the stage failure handlers (`PO:13359-13399`), and two API modules (`backend/app/api/research.py:306-330`, `backend/app/api/research.py:767` via `refresh_research_artifact_manifest` `PO:3444`). [verifier: both call sites are in one module, `backend/app/api/research.py`; the `heartbeat_status` call itself is at `backend/app/api/research.py:318`]

---

## Walkthrough (source order)

### `_stage_artifact_specs(state, stage)` — staticmethod, `PO:9499-9562`
- **What it does**: returns the candidate `(name, absolute_path)` list for one stage. It does **not** check whether files exist (`PO:9505`).
- **Input**: `PipelineState`, plus a stage constant (`STAGE_*`, `PO:87-92`).
- **Root**: `hd = state.handoff_dir or PipelineManager.handoff_dir(pipeline_id)` (`PO:9507`). For forks, `state.handoff_dir` points at the base pipeline's handoff (`PO:884-912`).
- **RESEARCH** (`PO:9509-9522`):

  | name | path |
  |---|---|
  | `report` | `handoff/research_report.md` |
  | `actor_dossier` | `handoff/actor_dossier.md` |
  | `dossier` | `handoff/actors.json` |
  | `timeline` | `handoff/timeline.json` |
  | `sources` | `handoff/sources.json` |
  | `quantitative` | `handoff/quantitative.json` |
  | `contested` | `handoff/contested.json` |
  | `prediction_markets` | `handoff/prediction_markets.json` |
  | `market_price_history` | `handoff/market_price_history.json` |
  | `prediction_market_candidates` | `handoff/prediction_market_candidates.jsonl` |
  | `research_budget` | `handoff/research_budget.json` |

  It then adds `_viz_artifact_specs(hd)`: `charts` and `datasets`.
- **ONTOLOGY**: `ontology` → `handoff/ontology.json` (`PO:9524`).
- **GRAPH**: `communities` → `handoff/communities.json`, plus `actor_graph_seed_manifest` → `handoff/actor_graph_seed_manifest.json` (`PO:9525-9530`). The filename constant is at `PO:111`.
- **PREPARE**: only when `state.simulation_id` is set. `sim_dir = Config.OASIS_SIMULATION_DATA_DIR/<sim_id>` (`PO:9532-9534`). Entries:
  - `initial_posts` → `simulation_config.json`. The name and file differ (`PO:9535`).
  - `simulation_config_manifest` → `simulation_config_manifest.json`.
  - Two `personas` alternatives: `twitter_profiles.csv` and `reddit_profiles.json` (`PO:9540-9541`).
  - `actor_cast` → `actor_cast_manifest.json`.
  - `twitter_actor_roles` → `twitter_profiles_roles.json`.
  - `reddit_actor_roles` → `reddit_profiles_roles.json` (`PO:9542-9550`).
- **RUN**: `run_summary` → `SimulationRunner.RUN_STATE_DIR/<sim_id>/run_summary.json`, only when `simulation_id` is set (`PO:9551-9555`).
- **REPORT**: only `report_viz_manifest` → `ReportManager._get_report_folder(report_id)/viz_manifest.json`, and only when `report_id` is set and `PIPELINE_VIZ_ARTIFACTS` is on (`PO:9556-9561`). The comment mentions `section_NN.md` (`PO:9557`), but sections are not specs. Only `_discover_partial_artifacts` scans them (`PO:10175-10186`). The report folder is `Config.UPLOAD_FOLDER/reports/<id>` (`backend/app/services/report_agent.py:11864`, `:11890-11892`).

### `_charts_manifest_path(hd)` — staticmethod, `PO:9564-9577`
- Returns `hd/charts.json` (canonical) unless that file is missing **and** the legacy `hd/charts/charts.json` exists. In that one case it returns the legacy path (`PO:9573-9577`).

### `_viz_artifact_specs(hd)` — staticmethod, `PO:9579-9596`
- If `PIPELINE_VIZ_ARTIFACTS` is false, returns `[]` (`PO:9591-9592`).
- Otherwise returns `[("charts", _charts_manifest_path(hd)), ("datasets", hd/data/datasets.json)]` (`PO:9593-9596`).
- Both files are optional. Every caller skips a missing file (docstring `PO:9587-9589`).

### `_viz_dynamic_artifact_specs(hd)` — staticmethod, `PO:9598-9620`
- Lists files directly inside `hd/charts/`. It does not recurse.
- Allowed extensions: `.png .svg .jpg .jpeg .webp .html` (`PO:9609`).
- It skips symlinks and non-regular files (`PO:9614-9616`).
- Names are `chart_<filename>`, sorted (`PO:9612-9617`).
- If the directory is missing or an `OSError` occurs, it returns `[]` (`PO:9607-9608`, `PO:9618-9619`).

### `_report_viz_dynamic_artifact_specs(report_dir)` — staticmethod, `PO:9622-9628`
- Same scan on `report_dir/charts`, with each name prefixed `report_`, giving `report_chart_<file>` (`PO:9625-9628`). The prefix keeps report chart keys separate from research chart keys.

### `_validate_report_viz_references(report_dir)` — staticmethod, `PO:9630-9679`
- **Purpose**: check that every chart file a report's `viz_manifest.json` declares is still a valid file under `charts/`.
- **Missing manifest** → `True`: visuals are optional (`PO:9640-9641`).
- **Manifest is a symlink** → `False` (`PO:9642-9643`).
- **Payload shape**: a list, or a dict with an `items` list. Anything else → `False` (`PO:9646-9651`).
- **Per item**: the item must be a dict (`PO:9655-9656`). For each of `path` and `png_path` (`PO:9657`), empty or `None` is skipped. Otherwise the value is rejected if any of these hold:
  - it is not a string, or contains a backslash, `%`, or a control character (ord <32 or 127) (`PO:9661-9663`);
  - after `.strip().removeprefix("./")`, its first part is not `charts`, it has fewer than 2 parts, or it contains an empty, `.` or `..` part (`PO:9664-9667`);
  - its extension is not in `{.png .svg .jpg .jpeg .gif .webp .html .mmd}` (`PO:9653`, `PO:9668`);
  - its realpath falls outside `realpath(report_dir/charts)`, it is not a regular file, it is 0 bytes, or any path component under `charts/` is a symlink (`PO:9670-9676`).
- **Errors**: `OSError`, `ValueError` or `TypeError` → `False`, which fails closed (`PO:9678-9679`).

### `_clear_report_attempt_artifacts(state)` — staticmethod, `PO:9681-9701`
- **When**: called only when a new REPORT attempt mints a new `report_id` (`PO:13265`).
- **In memory**: pops from `state.artifacts` every key that ends in `_partial` (**any stage**), plus `report_viz_manifest` and `report_chart_*` (`PO:9684-9690`).
- **On disk**: loads `handoff/manifest.json` and removes `report_viz_manifest` and `report_chart_*` rows. It rewrites the file only if something changed (`PO:9691-9699`).
- **Errors**: any exception is swallowed (`PO:9700-9701`).

### `_record_stage_artifacts(self, state, stage)` — `PO:9703-9755`
- **When**: called from `_complete_stage` (`PO:9044`), both for fresh completions and for `reused=True` completions. That call is wrapped in `try/except: pass` (`PO:9043-9046`).
- **`add_if(name, path)`** (`PO:9712-9718`): if the file exists and its size is >0, it:
  - sets `state.artifacts[name] = path`;
  - pops `state.artifacts[f"{name}_partial"]`;
  - appends the pair to `recorded`;
  - returns `True`.
- **PREPARE** (`PO:9720-9727`) loops over the specs. For a `personas` entry it runs `if add_if(...): break`. Other entries go through `add_if` directly. *Suspected bug:* the `break` leaves the **whole** loop, so the entries after the first existing persona file are never recorded: the reddit persona file, `actor_cast`, `twitter_actor_roles` and `reddit_actor_roles`. See Surprises.
- **Other stages**: `add_if` for every spec (`PO:9728-9730`).
- **RESEARCH extra** (when viz is on): registers the `_viz_dynamic_artifact_specs(hd)` chart files again at completion. Charts are rendered at the very end of the subprocess, so registration must not depend on a lucky progress scan (`PO:9732-9738`).
- **REPORT extra** (when `report_id` is set and viz is on): registers `report_chart_*` files (`PO:9739-9743`).
- **Integrity manifest** (`PO:9745-9755`): runs if anything was recorded and `PIPELINE_VALIDATE_ARTIFACTS` is on. It loads `handoff/manifest.json` (`PipelineManager.load_artifact_manifest`, `PO:1113-1126`). For each recorded pair it sets `manifest[name] = _manifest_entry_for(name, path, stage)` (`PO:7452-7472`):
  - fields: `{path, sha256, bytes, produced_by_stage, produced_at, schema_ok}`;
  - `sha256` is streamed in 1 MiB chunks (`PO:7401-7417`);
  - `schema_ok` comes from `_probe_artifact_schema` (`PO:7420-7449`).

  The manifest is then written atomically (`PO:1129-1133`). A write failure is only logged at debug level (`PO:9754-9755`).
- **Side effects**: mutates `state.artifacts` in memory; the caller saves. Writes `handoff/manifest.json`.

### `_fail_stage(self, state, stage, error)` — `PO:9757-9764`
- Sets `stages[stage]` to `status="failed"`, sets `error`, and sets `finished_at=_utcnow()`.
- Calls `PipelineManager.save(state)`, then `self._flush_run_telemetry(state)` (W9-3: so the spend of a failed run is persisted; `PO:7575-7614`).
- It does not touch `state.status`; the caller does.
- **Real callers**: `PO:9788` and `PO:13386`. The other grep hits are comments.

### `_halt_for_provider_outage(self, state, task_manager, error)` — `PO:9766-9794`
- **Purpose**: turns a `ProviderOutageHalt` (a `BaseException`, `PO:258-271`) into the existing resumable `failed` checkpoint.
- **Sets**:
  - `state.status="failed"` and `state.error=str(error)` (`PO:9777-9778`);
  - `state.options["provider_outage_halt"] = {**breaker.snapshot(), provider: Config.LLM_PROVIDER or "unknown", halted_at, halted_stage: current_stage, resume: "POST /api/research/<id>/resume"}` (`PO:9779-9786`).
- **Then**:
  - `_fail_stage(current_stage)` if a stage is current (`PO:9787-9788`);
  - `save` (`PO:9789`);
  - `task_manager.fail_task(task_id, msg)`, with exceptions swallowed (`PO:9790-9794`).
- **Caller**: `except ProviderOutageHalt` in `_run` (`PO:13377-13380`).

### `_validate_reuse(self, state, stage) -> bool` — `PO:9798-9885` (I-4-3)
1. Loads `handoff/manifest.json`. If it is empty or missing, it returns `True` (the legacy existence-based reuse), with one exception: for REPORT with a `report_id`, it returns `_validate_report_viz_references(report_folder)` (`PO:9811-9816`).
2. Groups the candidate paths from `_stage_artifact_specs` by logical name, so `personas` has 2 alternatives (`PO:9824-9826`).
3. For each name:
   - **No dict entry** in the manifest → skipped (optional or old manifest) (`PO:9829-9831`).
   - **Identity check**: if the entry has a `path`, its realpath must be one of the current candidates' realpaths. If it is not, the function logs "belongs to another attempt", sets `ok=False` and breaks (`PO:9833-9847`). This stops an old simulation's valid `run_summary` from satisfying a new attempt (`PO:9818-9823`).
   - **Entry without a path** (very old manifest) → every candidate is tried (`PO:9848-9851`).
   - **Per path tried**: it must exist; `bytes` must equal the size when `bytes` is an int; `sha256` must match when both the recorded and the recomputed hash are present. A recomputed `None` skips the hash comparison. Then `_probe_artifact_schema(name, path)` must pass (`PO:9853-9872`). The probe requires:
     - `actors.json`: a dict with an `actors` list;
     - `ontology.json`: non-empty `entity_types`;
     - `communities.json`: a list;
     - any other JSON: parseable as a dict or list;
     - non-JSON: non-empty (`PO:7430-7447`).
   - **No path matched** → a warning, `ok=False`, break (`PO:9873-9879`).
4. If everything passed and the stage is REPORT with a `report_id`, it also runs `_validate_report_viz_references` (`PO:9880-9884`).

Exceptions propagate to the caller. The research legacy path calls this method **directly** (`PO:11947-11948`); GRAPH, PREPARE, RUN and REPORT go through `_reuse_ok`.

### `_reuse_ok(self, state, stage) -> bool` — `PO:9887-9907`
- If `PIPELINE_VALIDATE_ARTIFACTS` is false, returns `True` (`PO:9895-9896`).
- Otherwise returns `_validate_reuse(...)`.
- On any exception it **fails closed**: it sets `state.options["artifact_validation_error"] = {stage, error[:300], at}`, logs a warning and returns `False` (`PO:9897-9907`).
- **Callers**:

  | stage | anchor |
  |---|---|
  | GRAPH | `PO:12398` |
  | PREPARE | `PO:12741` |
  | RUN (disk reuse) | `PO:12836` |
  | RUN (config gate) | `PO:12852` |
  | RUN (stage) | `PO:12957` |
  | REPORT | `PO:13233` |

### `_run_reuse_ready(state, sim_state) -> bool` — staticmethod, `PO:9909-9939`
- `False` if `simulation_id` is missing or `sim_state` is `None` (`PO:9919-9921`).
- `False` if `sim_state.simulation_id` differs (`PO:9922-9923`).
- `False` unless the status value equals `SimulationStatus.COMPLETED.value` (`PO:9924-9927`).
- A missing `run_summary.json` → `True`: a legacy run, whose summary is backfilled later (`PO:9929-9932`).
- An existing summary must be a dict, its `simulation_id` must be in `(None, "", sim_id)`, and `_probe_artifact_schema` must pass (`PO:9933-9939`).
- **Callers**: `PO:12851` and `PO:12952`.

### `_sim_platform_completion_missing(sim_id, run_state=None) -> list[str]` — staticmethod, `PO:9941-9974`
- **Enabled platforms**: read from `run_state.twitter_enabled/reddit_enabled` (`PO:9954-9955`). If both are false, it falls back to "an `actions.jsonl` exists" for each platform (`PO:9956-9958`). If still neither is enabled, it returns `["<no-platform-evidence>"]`, failing closed (`PO:9959-9960`).
- **Per enabled platform**, either piece of evidence counts:
  - `run_state.<platform>_completed` is true (`PO:9965-9968`); or
  - `_actions_simulation_end_present(sim_dir/<platform>/actions.jsonl)` (`PO:9969-9972`). This reads the last 256 KiB and looks for a JSON line with `event_type == "simulation_end"` (`PO:7490-7519`).

  Platforms with neither are returned in the list.

### `_completed_sim_reusable(self, state, sim_state) -> (bool, reason)` — `PO:9976-10057` (DEFECT-1)
The checks run in order. The first failure returns `(False, reason)`.
1. Knob off → `sim_resume_reuse_completed_disabled` (`PO:9995-9996`). The knob comes from `_sim_reuse_completed_enabled`: an explicit env `SIM_RESUME_REUSE_COMPLETED` wins, then `Config` (default on) (`PO:7475-7487`).
2. No sim id or no `sim_state` → `no_simulation_identity`. Id mismatch → `simulation_identity_mismatch` (`PO:9997-10001`).
3. `RUN_STATE_DIR/<sim_id>` is not a directory → `simulation_dir_missing` (`PO:10002-10004`).
4. The run state is `STARTING`/`RUNNING` and `SimulationRunner._is_simulation_alive(rs)` is true → `simulation_process_still_running`. If the liveness probe raises → `simulation_liveness_unknown` (`PO:10005-10014`).
5. `_sim_platform_completion_missing` is non-empty → `missing_simulation_end:<platforms>` (`PO:10015-10017`).
6. An existing `run_summary.json` that is not a dict, belongs to another simulation, or fails the probe → `run_summary_invalid`, `run_summary_identity_mismatch` or `run_summary_schema_invalid` (`PO:10018-10026`).
7. No expected manifest or config sha on `sim_state` **and** no `simulation_config_manifest.json` file → `no_config_seal_identity` (`PO:10027-10035`).
8. `validate_simulation_config_seal(sim_dir, expected_manifest_sha256, expected_config_sha256, expected_simulation_id=sim_id, require=True)` (`PO:10036-10044`; `backend/app/services/simulation_manager.py:137-171`). An `OSError`, `ValueError`, `TypeError` or `JSONDecodeError` → `config_seal_mismatch:<msg[:160]>` (`PO:10045-10046`).
9. If `reddit_runtime_system_messages.json` exists and carries a `simulation_config_manifest_sha256` that differs from the sealed `manifest_sha256` → `runtime_attestation_seal_mismatch` (`PO:10047-10054`). The subprocess writes this file (`backend/scripts/run_parallel_simulation.py:685`).
10. All checks pass → `(True, "")`. Any other exception → `reuse_check_error:<msg>` (`PO:10055-10057`).

- **Caller**: `PO:12835`, only when PREPARE is reused and the RUN bit is not completed (`PO:12831-12836`).

### `_require_run_completion_evidence(self, state, sim_id, run_state, summary_published)` — `PO:10059-10084` (DEFECT-2)
- If `_sim_platform_completion_missing` is non-empty, it raises `RuntimeError("模拟未产出完成证据…simulation_end…")` (`PO:10073-10079`).
- If `summary_published` is false, it raises `RuntimeError("…run_summary.json 缺失或结构无效…")` (`PO:10080-10084`).
- **Caller**: `PO:13134`. It runs for both fresh and reused RUNs. It is used with `rs`, or with a re-read `get_run_state` on reuse (`PO:13130-13136`).

### `_publish_run_summary(self, state, simulation_id, *, communities=None, regenerate) -> bool` — `PO:10086-10122`
- `summary_exists` = the file exists, is non-empty and passes the probe (`PO:10103-10106`).
- `SimulationRunner.write_run_summary(sim_id, communities=...)` is called only when `regenerate` is true or no valid summary exists (`PO:10107-10108`). Reuse is therefore read-only, which avoids overwriting a valid summary with a "0 agents/0 rounds" one (`PO:10096-10099`).
- After that, the file must be valid. If not, it returns `False` (`PO:10110-10112`).
- **On success**:
  - `state.artifacts["run_summary"]` is set and `save` is called (`PO:10114-10115`);
  - if validation is on, it upserts the `run_summary` manifest row **without a try/except** (`PO:10116-10121`);
  - returns `True`.
- **Caller**: `PO:13108`, with `regenerate=not run_stage_done`, wrapped in a try/except that only logs (`PO:13101-13117`).

### `_discover_partial_artifacts(state, stage) -> list[dict]` — staticmethod, `PO:10126-10206` (I-4-6)
- **Helper `_stat(name, path)`** (`PO:10138-10155`): records an entry only if `path` is non-empty, not already seen, exists, and has size >0. It dedupes **by path**. Each entry is `{name, path, bytes, mtime (UTC ISO), provisional: True}`.
- **Step 1**: every stage spec (`PO:10157-10159`).
- **Step 2, stage-specific** (`PO:10161-10186`):
  - RESEARCH: `research_report` (the same file as spec `report`, so it is deduped away) and `research_progress` → `handoff/research_progress.log`.
  - RUN: `run_state` → `RUN_STATE_DIR/<sim>/run_state.json`, plus `actions_twitter` and `actions_reddit` → `<sim>/<plat>/actions.jsonl`.
  - REPORT: each `section_*.md` in the report folder, sorted, with the name equal to the filename minus `.md`.
- **Step 3, viz** (`PO:10187-10203`):
  - RESEARCH: chart files plus `dataset_<file>.csv` from `handoff/data/`.
  - REPORT: `report_chart_*`.
- **Errors**: anything raised in steps 2-3 is swallowed (`PO:10204-10205`). Step 1 exceptions are not caught here. `_register_partial_artifacts` catches them instead (`PO:10227-10230`).

### `_register_partial_artifacts(self, state, stage)` — `PO:10208-10240`
- `PIPELINE_LIVE_ARTIFACTS` off → no-op (`PO:10216-10217`).
- **Throttle**: at most one scan per stage every `PIPELINE_PARTIAL_SCAN_EVERY_S` seconds (default 10). The timestamp is kept per instance in `self._partial_scan_at` (`PO:7540`), deliberately not in `state.options` (`PO:10218-10226`).
- For each discovered item it sets `state.artifacts[f"{name}_partial"] = path`, unless a formal `name` key already exists (`PO:10231-10240`).
- It does not save. The caller `update()` saves right after (`PO:8993-8994`).

### `estimate_eta(self, state) -> dict` — `PO:10244-10300` (I-5-6)
- **Output keys**: `elapsed_s`, `eta_s`, `eta_approximate=True`, `stale=False`, `last_progress_age_s` (`PO:10252-10258`).
- **Anchor**: `state.options["resumed_at"]` if parseable, else `created_at` (ORCH-7, `PO:10259-10266`). `resumed_at` is set by `resume()` (`PO:8182`).
- **Terminal states** (`completed`, `failed`, `cancelled`): `elapsed = anchor_age - age(updated_at)`. It is `None` if either is missing or the timestamps are inverted, which freezes the true run duration (`PO:10267-10277`). Non-terminal: `elapsed = anchor_age` (`PO:10278-10279`).
- `last_progress_age_s` comes from `last_progress_at or updated_at` (`PO:10283-10286`).
- `stale` (non-terminal only) = `age > PIPELINE_STALE_S` (default 300) (`PO:10287-10289`).
- **ETA**:
  - terminal → `0` (`PO:10291-10292`);
  - else `prog = clamp(global_progress, 0, 100)`. When `elapsed > 0` and `0 < prog < 100`: `eta = min(elapsed*(100-prog)/prog, PIPELINE_ETA_CAP_S)` (default 7200) (`PO:10294-10299`).
- No I/O beyond reading the clock.

### `heartbeat_status(self, state) -> dict` — `PO:10302-10327`
- Starts from `estimate_eta` and adds:
  - `owner_pid`;
  - `owner_alive` = `_pid_alive(owner_pid)`, which probes with `os.kill(pid, 0)`; `EPERM` counts as alive (`PO:325-347`). It is `None` when there is no owner (`PO:10310-10311`);
  - `heartbeat_age_s` (`PO:10312-10313`).
- If `LLM_TELEMETRY_ENABLED`, it reads `LLMMeter.snapshot(pipeline_id)["total"]`. It adds `spend_so_far={tokens, cost_usd}` only when tokens or cost are non-zero (in-process data only) (`PO:10314-10326`).
- **Caller**: the status API builds a fresh `PipelineOrchestrator()` and puts the result under `data["live"]`, plus an optional `budget` block (`backend/app/api/research.py:316-328`). The frontend reads these keys in `frontend/src/utils/runVitals.js:97-154`.

### `_start_heartbeat(self, state) -> Optional[threading.Event]` — `PO:10331-10370` (I-4-1)
- `PIPELINE_HEARTBEAT_ENABLED` off → returns `None` and writes no owner (`PO:10339-10340`).
- Pins `state.owner_pid=os.getpid()`, `owner_boot_id=_BOOT_ID` (a per-process uuid, `PO:300`) and `heartbeat_at=now` **in memory only** (`PO:10342-10347`).
- Starts the daemon thread `pipeline-hb-<id>`. Its loop is `while not stop.wait(interval)`, with interval `PIPELINE_HEARTBEAT_INTERVAL_S` (default 30). Each pass:
  - calls `PipelineManager.touch_heartbeat(pid)`, which takes the per-pipeline lock, does a load → modify → atomic write with `fsync=False`, and returns `False` unless the status is `running` (`PO:1078-1101`);
  - **exits the thread** when that returns `False`;
  - then calls `_maybe_flush_run_telemetry`, which flushes only after ≥`PIPELINE_TELEMETRY_FLUSH_EVERY_CALLS` new calls (`PO:7616-7632`) (`PO:10348-10369`).
- Returns the stop `Event`. `_run`'s `finally` sets it (`PO:13395-13396`).

### `_write_run_manifest(self, state)` — `PO:10374-10391` (I-8-1)
- `RECORD_RUN_MANIFEST` off → return (`PO:10380-10381`).
- Writes `redact_secrets(_build_run_manifest(state))` atomically to `pipelines/<id>/run.json` (`PO:10385-10386`; `PO:915-917`). The skeleton is described in `PO:7306-7379`.
- Sets `state.artifacts["run_manifest"]` (`PO:10388-10389`).
- Any exception is logged at debug level (`PO:10390-10391`).
- **Caller**: once per `_run` start (`PO:11897`).

### `_update_manifest(self, state, stage, total_rounds=None, temporal=None)` — `PO:10393-10426`
- `RECORD_RUN_MANIFEST` off → return (`PO:10402-10403`).
- Reads `run.json`. If it is missing or not a dict, rebuilds the skeleton (`PO:10407-10411`).
- For ONTOLOGY, GRAPH and REPORT: `resolved[stage] = {provider: Config.LLM_PROVIDER, model_name: Config.LLM_MODEL_NAME}` (`PO:10413-10414`; `PO:7388-7393`).
- `total_rounds` → `resolved.simulation.total_rounds` (`PO:10415-10417`). `temporal` copies `calendar_unit`, `n_rounds` and `horizon_date` (`PO:10418-10422`).
- Stamps `updated_at`, then writes atomically after a second `redact_secrets` pass (`PO:10423-10424`). Exceptions are logged at debug level.
- **Callers**:

  | context | anchor |
  |---|---|
  | ONTOLOGY | `PO:12309` |
  | GRAPH | `PO:12391` |
  | RUN progress, when the total changes | `PO:13041` |
  | REPORT | `PO:13187` |

### `_record_research_telemetry(self, state, telemetry)` — `PO:10430-10469` (I-5-7)
- Non-dict input → return; the resume path passes `None` (`PO:10439-10440`).
- Always stores `state.options["research_telemetry"]` and saves (`PO:10441-10445`).
- If telemetry is enabled and `tokens_in` or `tokens_out` is >0: calls `LLMMeter.record` once, with:
  - `provider="claude-cli"` when the model is `claude` or `codex`, otherwise the model name (`PO:10457`);
  - `latency_ms = wall_s*1000`;
  - `stage="research"`, `run_id=pipeline_id` (`PO:10446-10467`).
- **Caller**: `PO:12205`. Failed research attempts are metered by the `DeerFlowResearchRunner.run` wrapper instead (`PO:2114-2141`).

### `_record_sim_run_telemetry(self, state, simulation_id)` — `PO:10473-10560` (DEFECT-3)
- Reads `RUN_STATE_DIR/<sim>/sim_llm_telemetry.json`. A missing file or a non-dict → return (`PO:10494-10499`).
- **Dedupe token**: `meter_run_token`, or else the file's sha256 (`PO:10500-10501`). If `state.options["sim_llm_telemetry_recorded"]` already matches `(simulation_id, token)`, it returns (`PO:10502-10506`).
- Parses the fields: `provider` falls back to the claude-cli mapping (`PO:10508-10518`).
- **Stores**:
  - the summary in `state.options["sim_llm_telemetry"]`: `provider, model, calls, errors, prompt/completion/total tokens, by_source, wall_s`;
  - the **marker before metering**, in `sim_llm_telemetry_recorded = {simulation_id, meter_run_token, recorded_at}`;

  then saves (`PO:10519-10539`).
- If telemetry is enabled and tokens are >0: `LLMMeter.record(stage="run")`, plus an info log (`PO:10540-10558`).
- Everything is wrapped in a debug-level `except` (`PO:10559-10560`).
- **Callers**: the failure hook in the RUN loop (`PO:13067`) and the completion boundary (`PO:13123`). The producer side is `backend/scripts/run_parallel_simulation.py:2040-2048`.

### `_surface_research_quality(self, state, handoff_dir) -> Optional[dict]` — `PO:10564-10641` (I-0-3)
- Reads `handoff/meta.json` (`PO:10577-10581`) and `rq = dict(meta["research_quality"] or {})` (`PO:10582`).
- Reads `handoff/research_budget.json` (`PO:10583`). If it is a dict:
  - `denials` = the sum of numeric `global.denied_*` counters (`PO:10585-10589`);
  - `budget_summary = {degraded, denials, attempts, search_network, fetch_network, limits}` goes into `state.options["research_budget"]` and `meta["research_budget"]` (`PO:10590-10599`);
  - if `degraded` or `denials`: sets `rq["degraded"]=True` and appends a reason to `rq["degradation"]` (`PO:10600-10611`);
  - it **writes `meta.json` back only if `research_contract_manifest.json` is absent**, because sealed metadata must not be mutated (`PO:10612-10621`).
- If there is neither `rq` nor a budget → returns `meta or None` (`PO:10622-10623`).
- Otherwise:
  - `state.options["research_quality"]=rq`;
  - if `RESEARCH_QUALITY_GATE` is on, `floor>0` and `score<floor`, it sets `state.options["research_quality_warning"]` and logs a warning. The run continues; this is not a hard failure;
  - saves (`PO:10624-10640`).
- Returns `meta`. The caller puts it in `research["meta"]` before `_finalize_research_contract` (`PO:12210-12213`, `PO:12267`).

### `_compute_forecast_confidence_penalty(meta, dossier_coverage) -> (float, dict)` — staticmethod, `PO:10645-10714` (R2-RES-3)
The penalty is the sum of these components, rounded and capped at 0.3 (`PO:10714`):
- **`research_quality`** = `min(0.15, floor - score)`, when `floor>0` and `score<floor`. The floor is `Config.RESEARCH_QUALITY_FLOOR` (`PO:10663-10674`). This component does **not** check `RESEARCH_QUALITY_GATE`.
- **`research_budget`** = 0.05 when `meta.research_budget.degraded` or `denials` is set (`PO:10676-10680`).
- **`source_tier_mix`** = `(1 - weighted_mean)*0.1` over the `meta.source_tiers` counts (`PO:10682-10699`). Weights (`PO:6509-6526`):
  - `s1`=1.0, `s2`=0.7, `s3`=0.4;
  - everything else, including `s4` and `s_unknown`, = 0.2;
  - so the maximum is 0.08.
- **`dossier_coverage`** = 0.05 per weak signal, max 0.10 (`PO:10701-10712`). Weak signals:
  - actors present but `pct_actors_with_incentives < 0.34`;
  - `n_relationships == 0` (this also fires when the key is missing);
  - relationships present but `pct_edges_valenced < 0.2`.

### `_surface_forecast_confidence_penalty(self, state, handoff_dir)` — `PO:10716-10736`
- Reads `meta.json` **after** finalization and `state.options["dossier_coverage"]` (set at `PO:12218`). Calls the function above. [verifier: the assignment `state.options["dossier_coverage"] = cov` is at `PO:12219`]
- Writes `state.options["forecast_confidence_penalty"]` and `..._components`, logs at info level when >0, and saves (`PO:10723-10734`). Exceptions are logged at debug level.
- **Caller**: `PO:12273`.
- Nothing reads this value. The docstring says the gate is deferred (`PO:10720-10722`), and no consumer exists in `backend/app` or `frontend/src` (grep).

### `_log_decision_channel_outcome(self, state, simulation_id)` — `PO:10738-10790` (SIM-ADD-2)
- `sim_dir = Config.OASIS_SIMULATION_DATA_DIR/<sim>` (`PO:10746-10747`).
- `scenarios` = the non-blank entries of `simulation_config.json.world_state_seed.scenarios` (`PO:10748-10755`).
- Reads `world_state_trajectory.json`. `produced` = a non-empty `trajectory` (`PO:10756-10757`).
- Builds the summary `{scenarios_seeded, trajectory_produced, leader, leader_share, converged_at}` into `state.options["decision_channel_summary"]`, then saves (`PO:10761-10772`).
- **Logs**:
  - info with the top-4 outcome shares when a trajectory was produced (`PO:10773-10781`);
  - a warning when scenarios were seeded but no trajectory exists (`PO:10782-10786`);
  - a warning when nothing was seeded (`PO:10787-10790`).
- **Caller**: `PO:13181`, wrapped in try/debug.

### `_validate_as_of_date(actors, sources) -> (Optional[datetime], Optional[str])` — staticmethod, `PO:10794-10837` (R2-RES-7)
- `run_dt` = now (UTC). `max_src` = the latest `parse_as_of(s["date"])` across the source dicts (`PO:10808-10816`). `parse_as_of` accepts dates, `YYYY-MM-DD`, `YYYY/MM/DD`, CJK formats, `YYYY-MM` and `YYYY` (`backend/app/utils/dates.py:38-58`).
- `parsed = parse_as_of(actors.as_of_date)` (`PO:10817-10818`). It is rejected, with a note, if:
  - it is later than `run_dt` (`PO:10821-10823`);
  - it is earlier than `max_src` (`PO:10824-10826`);
  - it is a non-empty raw value that fails to parse (`PO:10827-10828`).
- **Return values**:

  | case | returns |
  |---|---|
  | valid | `(parsed, None)` (`PO:10829-10830`) |
  | otherwise, if `max_src` exists | `(min(max_src, run_dt), note)` (`PO:10831-10832`) |
  | raw absent and no sources | `(None, None)` (`PO:10833-10835`) |
  | invalid and no sources | `(run_dt, note)` (`PO:10837`) |

- **Caller**: GRAPH seeding, gated by `VALIDATE_AS_OF_DATE` (default true). A note goes to `state.options["as_of_date_correction"]`. An exception falls back to a plain parse (`PO:12512-12524`).

### `_run_research_synthesis_recovery(self, state, handoff_dir, upd, manifest_path) -> dict` — `PO:10841-11056`
1. `_sync_deerflow_bridge_if_stale(Config.DEERFLOW_DIR)` (`PO:10856`). This syncs the tracked `deerflow_bridge/` into the deployed `deer-flow/` and fails closed (`PO:1441-1455`). Its return value is ignored.
2. **Precondition**: the evidence manifest must be a dict with `version >= 3`, a non-empty `lanes` list and a dict `actor_dossier`. Otherwise it raises `RuntimeError` (`PO:10857-10873`).
3. **Budget epoch**: `_synthesis_recovery_budget_epoch` reuses the current epoch when the previous synthesis-only recovery failed and its ledger is not exhausted. Otherwise `_activate_research_budget_epoch` opens a new epoch, capped by `RESEARCH_BUDGET_MAX_EPOCHS` (default 3) [verifier: it first returns the epoch already bound to the same `task_id` (`PO:1840-1849`); a new epoch is opened only for a new task id, and the cap raises at `PO:1851-1856`] (`PO:10874-10876`; `PO:1926-1966`; `PO:1815-1923`). If `_research_budget_exhaustion` reports a saturated global cap, it raises (`PO:10877-10883`; `PO:1764-1798`).
4. **Concurrency**: `model_concurrency = research_model_concurrency_cap(1, RESEARCH_GLOBAL_SUBAGENT_CAP (9), RESEARCH_GLOBAL_MODEL_CONCURRENCY (0))`. With the defaults that is 1+9 = 10 (`PO:10884-10889`; `PO:5845-5854`).
5. **Market candidates**: unions the lines of `handoff/prediction_market_candidates.jsonl` and `handoff/track_*/prediction_market_candidates.jsonl`, deduped by exact stripped line (`PO:10891-10905`).
6. **Callbacks**: `_spawn` persists `research_pid` (`PO:10907-10909`). `_progress` clamps to 1..99 and prefixes `[仅综合恢复]` (`PO:10911-10915`).
7. **Up to 2 attempts** (`PO:10922`):
   - `mkdtemp(".synthesis-recovery-<n>-", dir=handoff_dir)`; writes the market lines into it; then `upd(2, …)` (`PO:10924-10935`).
   - `DeerFlowResearchRunner.run(...)` (`PO:10937-10958`) with `subagents=False`, `max_concurrent_subagents=1`, `dual_track=False`, `shared_actor_track=False`, `budget_lane_id="global-synthesis-recovery"` and `synthesis_manifest_path=manifest_path`. The runner then adds `--synthesis-manifest` and forces the legacy engine (`PO:2268-2269`, `PO:2297`).
   - A non-zero `exit_code` raises (`PO:10959-10963`). On success it sets `final_res`/`source_dir` and breaks.
   - **`PipelineCancelled`**: preserves the progress log (outcome `cancelled`), runs `rmtree` on the staging directory and re-raises (`PO:10967-10976`).
   - **Other `Exception`**: records the error and computes `provider_blocked = _synthesis_provider_unavailable(detail)`. That uses marker strings such as `rate limit`, `token plan`, `2056` and `auth_unavailable` (`PO:1969-1983`). It also calls `_note_provider_stage_failure`, which feeds the run outage breaker (`PO:580-591`). It preserves the log plus the candidate/judge sidecars into `handoff/research_attempts/global_synthesis_<n>_failed_<uuid>.*` (`PO:3078-3137`), runs `rmtree` on the staging directory and logs. If the provider is blocked, it stops retrying (`PO:10977-11000`).
8. Sets `state.research_pid = None` (`PO:11002`).
9. **Failure**: `state.options["synthesis_recovery"] = {attempted, passed: False, evidence_manifest, attempts, errors, blocked_by_provider}`, then saves and raises one of two `RuntimeError`s, provider-blocked or "two consecutive quality-gate failures" (`PO:11003-11022`).
10. **Success**:
    - `_promote_research_contract(source_dir, handoff_dir, meta_patch={parallel_research, synthesis_recovery})`. It stages the files, swaps them in with rollback, and writes the manifest last (`PO:11040-11047`; `PO:3492-3503`).
    - Then `rmtree` on the staging directory; sets `state.options["parallel_research"]` (architecture `parallel_evidence_single_global_synthesis`, `synthesis_only_recovery=True`) and `["synthesis_recovery"]` (passed); saves (`PO:11024-11051`).
    - Returns `_load_research_handoff(handoff_dir)`, which raises if the report is under 400 chars (`PO:3857-3887`), with `exit_code=0` and `research_telemetry` taken from the candidate (`PO:11052-11056`). [verifier: `_promote_research_contract` (`PO:11040-11047`) is outside any try; if promotion validation raises (`PO:3571-3576`), the `.synthesis-recovery-*` staging dir is not removed and `synthesis_recovery` is not recorded, so the epoch-reuse rule in `_synthesis_recovery_budget_epoch` (`PO:1938-1966`, needs `passed is False`) will not apply on the next resume]
- **Caller**: `PO:11971`, when the contract is invalid or fails quality, or when there is no root report but `handoff/evidence_synthesis_manifest.json` exists (`PO:11916-11959`).

---

## Control flow

**Start of `_run`** (`PO:11883`):
1. `_init_telemetry_flush` (`PO:11895`).
2. `_write_run_manifest` (`PO:11897`).
3. `hb_stop = _start_heartbeat` (`PO:11900`).

**RESEARCH**:
1. **Reuse decision** (`PO:11905-11959`):
   - report ≥400 chars, and a contract that is valid and passes quality → reuse;
   - contract invalid or failing quality, and an evidence manifest exists → synthesis recovery;
   - no contract but the stage bit is completed → `_validate_reuse(STAGE_RESEARCH)` (legacy; **not** via `_reuse_ok`) (`PO:11947-11948`);
   - no report, but an evidence manifest → synthesis recovery (`PO:11955-11959`).
2. `_run_research_synthesis_recovery` (`PO:11971`), or the parallel/single research path in the next slice.
3. `_record_research_telemetry` (`PO:12205`).
4. `_surface_research_quality` (`PO:12210`).
5. `dossier_coverage` (`PO:12217`).
6. `_finalize_research_contract` (`PO:12267`).
7. `_surface_forecast_confidence_penalty` (`PO:12273`).

**ONTOLOGY**: `_update_manifest` (`PO:12309`).

**GRAPH**:
1. `_update_manifest` (`PO:12391`).
2. `_reuse_ok(GRAPH)`. Failure sets `resumed_stage_validation="graph_rebuilt_manifest_mismatch"` (`PO:12398-12401`).
3. `_validate_as_of_date` while seeding actors (`PO:12514`).

**PREPARE**:
1. `_reuse_ok(PREPARE)`. Failure sets `prepare_rebuilt_manifest_mismatch` (`PO:12741-12744`).
2. If PREPARE was reused and the RUN bit is missing: `_completed_sim_reusable` + `_reuse_ok(RUN)` → `_sim_disk_reuse` (`PO:12831-12847`).
3. `_run_already_done` = disk reuse, **or** RUN completed + `_run_reuse_ready` + `_reuse_ok(RUN)` (`PO:12848-12853`). [verifier: the second branch also requires `_prepare_reuse` (`PO:12849-12850`)]

**RUN**:
1. Prepare identity changed → `run_rebuilt_prepare_identity_changed` (`PO:12949-12951`).
2. `_run_reuse_ready` fails → `run_rebuilt_simulation_state_mismatch` (`PO:12952-12955`).
3. `_reuse_ok(RUN)` fails → `run_rebuilt_manifest_mismatch` (`PO:12957-12960`).
4. Disk reuse applies → `run_reused_completed_simulation` (`PO:12963-12965`).
5. In the progress loop: `_update_manifest(RUN, total_rounds, temporal)` (`PO:13041`). Any exception in the loop goes through `_record_sim_run_telemetry`, then is re-raised (`PO:13062-13068`).
6. `_publish_run_summary` (`PO:13108`).
7. `_record_sim_run_telemetry` (`PO:13123`).
8. `_require_run_completion_evidence` (`PO:13134`).
9. `_complete_stage(RUN)` (`PO:13170`).
10. `_log_decision_channel_outcome` (`PO:13181`).

**REPORT**:
1. `_update_manifest` (`PO:13187`).
2. For an existing report: `_reuse_ok(REPORT)`. Failure sets `report_rebuilt_artifact_validation` (`PO:13233-13240`). [verifier: before this, the ORCH-1 deliverable health check `_assess_report_health` drops the reuse candidate when PIPELINE_HEALTH_GATE is on and health is `failed` (it sets `report_rebuilt_broken_deliverable`, `PO:13211-13222`), and `force_report_regen` skips reuse (`PO:13224-13226`)]
3. For a new attempt: `_clear_report_attempt_artifacts` (`PO:13265`), then a new `report_id`.

**Terminal handlers**:
- `ProviderOutageHalt` → `_halt_for_provider_outage` (`PO:13377-13380`).
- Generic `Exception` → `_fail_stage` (`PO:13381-13386`).
- `finally` → `hb_stop.set()` (`PO:13395-13396`).

**Every progress tick** (`update`, `PO:8958`):
1. Checks for cancel or outage → raise (`PO:8961-8969`).
2. Stamps `last_progress_at` and `heartbeat_at` (`PO:8984-8987`).
3. `_register_partial_artifacts` (`PO:8993`).
4. `save` (`PO:8994`).
5. `_maybe_flush_run_telemetry` (`PO:8997`).

**Every stage completion** (`_complete_stage`, `PO:9009`):
1. `_record_stage_artifacts` (`PO:9044`).
2. `save`.
3. `_flush_run_telemetry` (`PO:9048-9050`).

**Out of band**:
- The heartbeat thread loops every 30s on `touch_heartbeat` and `_maybe_flush_run_telemetry` (`PO:10352-10366`).
- `GET /api/research/status/<id>` → `heartbeat_status` → `estimate_eta` (`backend/app/api/research.py:306-328`).

---

## Data & artifacts

| Artifact | Path pattern | Format / key fields | Written by (slice) | Read by (slice) |
|---|---|---|---|---|
| Integrity manifest | `uploads/pipelines/<id>/handoff/manifest.json` (static path, `PO:1108-1110`) | `{<name>: {path, sha256, bytes, produced_by_stage, produced_at, schema_ok[, human_edited_at]}}` (`PO:7465-7472`, `PO:3469`) | `_record_stage_artifacts` `PO:9746-9753`, `_publish_run_summary` `PO:10116-10121`, `_clear_report_attempt_artifacts` `PO:9691-9699` | `_validate_reuse` `PO:9811` |
| Run manifest | `uploads/pipelines/<id>/run.json` (`PO:915-917`) | `schema_version, pipeline_id, mode, created_at, updated_at, repo_git_sha, deerflow_ref, resolved{research, ontology, graph, report, simulation}, graph{}, env_fingerprint, redacted_flag` (`PO:7331-7374`) | `_write_run_manifest` `PO:10386`, `_update_manifest` `PO:10424` | `_update_manifest` `PO:10408` |
| Pipeline state | `uploads/pipelines/<id>/pipeline_state.json` | `artifacts{name→path}`, `options{…}`, `owner_pid`, `owner_boot_id`, `heartbeat_at`, `last_progress_at`, `research_pid` | `PipelineManager.save` (called throughout), `touch_heartbeat` | status API |
| Research handoff files | `handoff/{research_report.md, actors.json, …}` (see specs) | md/json/jsonl | (bridge / other slices) | specs, `_load_research_handoff` |
| Research meta | `handoff/meta.json` | `research_quality{score, degraded, degradation[]}`, `research_budget`, `source_tiers` | `_surface_research_quality` `PO:10619` (only if no contract manifest) | `PO:10578`, `PO:10724` |
| Research budget telemetry | `handoff/research_budget.json` | `{epoch, degraded, limits{attempts_global, search_global, …}, global{attempts, search_network, fetch_network, denied_*}, lanes}` (`PO:1899-1921`) | (epoch activation, outside slice) | `PO:10583`, `PO:1775` |
| Research contract manifest | `handoff/research_contract_manifest.json` (`PO:3140`, `PO:3321-3322`) | checksum manifest | `_promote_research_contract` | existence check `PO:10616` |
| Evidence synthesis manifest | `handoff/evidence_synthesis_manifest.json` (`PO:11916-11917`) | `version>=3, lanes[], actor_dossier{}` | bridge | `PO:10857-10873` |
| Synthesis staging | `handoff/.synthesis-recovery-<n>-XXXX/` | temp generation | `PO:10924-10931` | promoted, then `rmtree` |
| Failed synthesis sidecars | `handoff/research_attempts/global_synthesis_<n>_<outcome>_<uuid12>.log` (+ `.research_report.md`, `.…judge.json`, `.meta.json`) | text/md/json | `_preserve_research_attempt_progress` `PO:3097-3132` | — |
| Charts index | `handoff/charts.json` (legacy `handoff/charts/charts.json`) | JSON | renderer | specs |
| Datasets index / csv | `handoff/data/datasets.json`, `handoff/data/*.csv` | JSON / CSV | renderer | specs / partial scan |
| Research chart assets | `handoff/charts/*.{png,svg,jpg,jpeg,webp,html}` | binary/html | renderer | `chart_<file>` keys |
| Report viz | `uploads/reports/<rid>/viz_manifest.json`, `charts/*` | list or `{items:[{path, png_path, …}]}` | report agent | `PO:9639-9679` |
| Report sections | `uploads/reports/<rid>/section_*.md` | md | report agent | partial scan `PO:10184-10186` |
| Sim config & seal | `uploads/simulations/<sid>/{simulation_config.json, simulation_config_manifest.json, actor_cast_manifest.json, *_profiles*.{csv,json}}` | json/csv | prepare | specs, seal check, decision channel |
| Run outputs | `uploads/simulations/<sid>/{run_summary.json, run_state.json, <plat>/actions.jsonl, sim_llm_telemetry.json, reddit_runtime_system_messages.json, world_state_trajectory.json}` | json/jsonl | sim subprocess / runner | `PO:9929-9939`, `PO:9953-9973`, `PO:10018-10054`, `PO:10494`, `PO:10756` |

**In-memory structures**:
- `state.artifacts`: formal keys plus `<name>_partial` keys.
- `self._partial_scan_at: dict[stage→epoch_s]` (`PO:7540`).
- `PipelineOrchestrator._cancel_events: dict[pid→Event]` (`PO:7531`), which synthesis recovery uses.

**`state.options` keys set in this slice**:
- `provider_outage_halt`
- `artifact_validation_error`
- `research_telemetry`
- `sim_llm_telemetry`, `sim_llm_telemetry_recorded`
- `research_budget`, `research_quality`, `research_quality_warning`
- `forecast_confidence_penalty`, `forecast_confidence_penalty_components`
- `decision_channel_summary`
- `synthesis_recovery`, `parallel_research`
- `synthesis_recovery_budget_reused` (helper `PO:1958`)

---

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `PIPELINE_VIZ_ARTIFACTS` | true | Includes charts/datasets/report-viz in the specs and in dynamic registration | `backend/app/config.py:470`; `PO:9558`, `PO:9591`, `PO:9735`, `PO:10189` |
| `PIPELINE_VALIDATE_ARTIFACTS` | true | Writes manifest rows; `_reuse_ok` validates (off → reuse without checks) | `backend/app/config.py:466`; `PO:9746`, `PO:9895`, `PO:10116` |
| `PIPELINE_LIVE_ARTIFACTS` | true | Enables `_partial` registration | `backend/app/config.py:464`; `PO:10216` |
| `PIPELINE_PARTIAL_SCAN_EVERY_S` | 10 | Throttle for the partial scan, per stage | `backend/app/config.py:465`; `PO:10219` |
| `PIPELINE_STALE_S` | 300 | Staleness threshold for `live.stale` | `backend/app/config.py:461`; `PO:10288` |
| `PIPELINE_ETA_CAP_S` | 7200 | Upper clamp on the ETA | `backend/app/config.py:462`; `PO:10298` |
| `PIPELINE_HEARTBEAT_ENABLED` | true | Owner pinning + heartbeat thread | `backend/app/config.py:457`; `PO:10339` |
| `PIPELINE_HEARTBEAT_INTERVAL_S` | 30 | Heartbeat period | `backend/app/config.py:458`; `PO:10348` |
| `PIPELINE_TELEMETRY_FLUSH_EVERY_CALLS` | 20 (getattr fallback) [verifier: also defined in Config, default 20 (`backend/app/config.py:490`); 0 disables (`PO:7624-7625`)] | Incremental telemetry flush, also on the heartbeat | `PO:7621` |
| `LLM_TELEMETRY_ENABLED` | true | `spend_so_far`; synthetic research/run meter records | `backend/app/config.py:58`; `PO:10314`, `PO:10446`, `PO:10540` |
| `RECORD_RUN_MANIFEST` | true | `run.json` write/update | `backend/app/config.py:426`; `PO:10380`, `PO:10402` |
| `MANIFEST_CAPTURE_VERSIONS` | false (getattr) [verifier: also defined in Config, default false (`backend/app/config.py:472`)] | Package versions in `run.json` | `PO:7375` |
| `RESEARCH_QUALITY_GATE` | false | Enables only the soft `research_quality_warning` | `backend/app/config.py:348`; `PO:10627` |
| `RESEARCH_QUALITY_FLOOR` | 0.45 (Config) / 0.0 (getattr fallback in code) | Warning floor; penalty floor (always active) | `backend/app/config.py:351`; `PO:10628`, `PO:10667` |
| `SIM_RESUME_REUSE_COMPLETED` (env overrides Config) | true | Allows reuse of a completed simulation on disk | `backend/app/config.py:596`; `PO:7481-7487`, `PO:9995` |
| `VALIDATE_AS_OF_DATE` | true | Gates `_validate_as_of_date` at the call site | `backend/app/config.py:477`; `PO:12512` |
| `RESEARCH_GLOBAL_SUBAGENT_CAP` | 9 | Synthesis-recovery model concurrency envelope | `backend/app/config.py:1205`; `PO:10884` |
| `RESEARCH_GLOBAL_MODEL_CONCURRENCY` | 0 (derive) | Explicit concurrency override | `backend/app/config.py:1212`; `PO:10888` |
| `RESEARCH_BUDGET_MAX_EPOCHS` | 3 | Cap on budget epochs (may raise during recovery) | `backend/app/config.py:543`; `PO:1851-1856` |
| `DEERFLOW_MODEL` | `claude` | Fallback model name for research telemetry | `backend/app/config.py:1156`; `PO:10454` |
| `DEERFLOW_DIR` | (config) | Bridge sync target | `PO:10856` |
| `OASIS_SIMULATION_DATA_DIR` | `backend/uploads/simulations` | PREPARE specs + decision channel | `backend/app/config.py:1080`; `PO:9534`, `PO:10747` |
| `SimulationRunner.RUN_STATE_DIR` | `backend/uploads/simulations` (class constant) | RUN specs, reuse, telemetry | `backend/app/services/simulation_runner.py:279-282` |
| `LLM_PROVIDER` / `LLM_MODEL_NAME` | (config) | Stamped into `run.json` resolved stages and the outage halt | `PO:7391-7392`, `PO:9782` |
| `LLM_RUN_BUDGET_TOKENS` | 0 | (API side) adds `live.budget` | `backend/app/config.py:64`; `backend/app/api/research.py:318` [verifier: the read is at `backend/app/api/research.py:319`] |

---

## External calls

- **Subprocess**: `DeerFlowResearchRunner.run(...)` in synthesis recovery (`PO:10937`). It starts the DeerFlow research child with `--synthesis-manifest`, the legacy engine and the budget env (`PO:2268-2269`, `PO:2297`). The child makes the LLM calls; the slice itself makes **no direct LLM/HTTP calls**.
- **Filesystem sync into `deer-flow/`**: `_sync_deerflow_bridge_if_stale` (`PO:10856`).
- **Process probes**:
  - `os.kill(pid, 0)` via `_pid_alive` (`PO:10311`, `PO:339-347`);
  - `SimulationRunner._is_simulation_alive(rs)` (`PO:10011`);
  - `SimulationRunner.get_run_state(sim_id)` (`PO:10005`).
- **Simulation services**:
  - `SimulationRunner.write_run_summary` (`PO:10108`), which aggregates `actions.jsonl` (`backend/app/services/simulation_runner.py:2026-2040`);
  - `validate_simulation_config_seal` (`PO:10036-10044`).
- **In-process meter**: `LLMMeter.snapshot` (`PO:10317`) and `LLMMeter.record` (`PO:10459`, `PO:10545`) (`backend/app/utils/telemetry.py:231`, `:273`). [verifier: order is reversed — `record` is `backend/app/utils/telemetry.py:231` and `snapshot` is `:273`; likewise `write_text_atomic` is `backend/app/utils/atomic.py:20` and `write_json_atomic` is `:53`]
- **Persistence**: `PipelineManager.save`, `touch_heartbeat`, `load_artifact_manifest`, `write_artifact_manifest`, `manifest_path`, `handoff_dir` (`PO:884-1133`). `write_json_atomic`/`write_text_atomic` (`backend/app/utils/atomic.py:20`, `:53`). `redact_secrets` (`backend/app/utils/security.py:35`).
- **Task book**: `task_manager.fail_task` (`PO:9792`).
- **Breaker**: `_outage_breaker_for(...).snapshot()` (`PO:9779-9781`) and `_note_provider_stage_failure` (`PO:10982`).
- **Research contract**: `_promote_research_contract` (`PO:11040`) and `_load_research_handoff` (`PO:11052`).

---

## Cross-module edges

**Into the slice**:
- `backend/app/api/research.py:316` calls `PipelineOrchestrator().heartbeat_status(...)`, which calls `estimate_eta`. [verifier: the call is at `backend/app/api/research.py:318`]
- `backend/app/api/research.py:767` calls `refresh_research_artifact_manifest` (`PO:3444-3474`), which uses `_stage_artifact_specs` (`PO:3460`). It refreshes manifest rows after a human edits `research_report.md` or `actors.json`, so `_validate_reuse` accepts the edit.
- `backend/app/api/research.py:779-800` (`GET /<id>/artifact/<name>`) serves the `state.artifacts` pointers this slice writes. It accepts a `chart_*_partial` fallback.
- `backend/scripts/run_parallel_simulation.py:2040-2048` documents the `sim_llm_telemetry.json` producer contract that `_record_sim_run_telemetry` reads.
- `frontend/src/utils/runVitals.js:97-154` consumes `live.stale`, `heartbeat_age_s`, `eta_s` and `spend_so_far`. [verifier: incomplete — it also reads `owner_alive` (`=== false` yields 'dead', `frontend/src/utils/runVitals.js:96`), `elapsed_s` (:138), `budget` (:164-168), `last_progress_age_s` and `owner_pid` (:191-192)]
- Internal callers are listed in Control flow.

**Out of the slice**:
- `PipelineManager` (`PO:860-1133`).
- `SimulationRunner` (`backend/app/services/simulation_runner.py`).
- `SimulationStatus`/`validate_simulation_config_seal` (`backend/app/services/simulation_manager.py:137`).
- `ReportManager._get_report_folder` (`backend/app/services/report_agent.py:11890`).
- `LLMMeter` (`backend/app/utils/telemetry.py`).
- `parse_as_of` (`backend/app/utils/dates.py:38`).
- `DeerFlowResearchRunner` (`PO:2099+`).
- Budget-epoch helpers (`PO:1764-1983`).
- Contract helpers (`PO:3078-3137`, `PO:3321`, `PO:3492`, `PO:3857`).

---

## Invariants, gates, validation

- **One source of truth for specs**: record, validate and discover all derive from `_stage_artifact_specs` (`PO:9501-9505`, `PO:9722-9730`, `PO:9825`, `PO:10158`). The edit API does too (`PO:3460`).
- **Recorded only if non-empty**: a file is registered or manifested only if it exists with size >0 (`PO:9713`, `PO:7457-7464`).
- **Formal keys win**: a formal key always beats `_partial`. Registration pops `<name>_partial` (`PO:9715`). Partial registration skips names already present (`PO:10238-10239`).
- **Reuse validation**:
  - no manifest → reuse allowed (backward compatible) (`PO:9812-9816`);
  - an unregistered artifact → not checked (`PO:9830-9831`);
  - a registered artifact that is missing, changed, or fails the schema probe → reuse rejected (`PO:9873-9879`);
  - the declared path is not among the current candidates → rejected (`PO:9840-9846`);
  - a validator exception (via `_reuse_ok`) → rejected (`PO:9899-9907`).
- **RUN reuse identity**: same `simulation_id` and `SimulationStatus.COMPLETED` (`PO:9919-9927`). Disk reuse additionally needs per-platform `simulation_end`, a valid summary, a valid seal and attestation agreement (`PO:9994-10055`).
- **Completion gate (both fresh and reused RUN)**: every enabled platform has `simulation_end`, and the summary is published, or the stage raises (`PO:10073-10084`).
- **Reuse never rewrites a valid summary**: `regenerate=False` with a valid file → no rewrite (`PO:10107-10108`).
- **Exactly-once simulation metering**: keyed on `(simulation_id, meter_run_token)`. The marker is persisted before metering, so the failure mode is under-counting, never double-counting (`PO:10500-10506`, `PO:10531-10553`).
- **Penalty range**: the confidence penalty stays in [0, 0.3] (`PO:10714`). It is observation-only and nothing gates on it.
- **As-of bounds**: the anchor is never after the run date and never before the newest source date (`PO:10821-10826`). When it is corrected, the fallback is also clamped to `run_dt` (`PO:10832`). [verifier: the second bound does not hold when a source is future-dated: `max_src > run_dt` makes the fallback `run_dt`, which is earlier than the newest source date (`PO:10831-10832`; see Surprise 12)]
- **Synthesis recovery** (`PO:10863-10883`, `PO:10922`, `PO:11040`, `PO:10975`, `PO:10990`):
  - requires a v3 evidence manifest and an unexhausted budget;
  - allows ≤2 attempts;
  - promotes only after a zero-exit attempt;
  - staging directories are removed on handled failure.
- **Heartbeat thread**: never writes after the status leaves `running` (`PO:1088-1089`, `PO:10356-10358`).

---

## Failure modes & recovery

- **Manifest write failure in `_record_stage_artifacts`**: logged at debug level. Later reuse then has a weaker or no manifest and falls back to existence-based reuse (`PO:9754-9755`, `PO:9812-9816`).
- **Corrupted or tampered reuse artifact**: the stage is rebuilt, and `resumed_stage_validation` (or `report_rebuilt_artifact_validation` for REPORT) is stamped (`PO:12398-12401`, `PO:12741-12744`, `PO:12957-12960`, `PO:13233-13240`).
- **Hollow simulation** (rc=0, no `simulation_end`) or a missing/invalid summary: the RUN stage fails with a resumable `RuntimeError` (`PO:10075-10084`). Spend was already metered at `PO:13123`.
- **Provider outage**: `_halt_for_provider_outage` sets `failed` plus a breaker snapshot and the resume hint, so `POST /api/research/<id>/resume` continues the run (`PO:9777-9794`).
- **Synthesis recovery failure**: `synthesis_recovery.passed=False`, the error list is persisted, and a `RuntimeError` is raised. The next resume may reuse the same unexhausted budget epoch instead of spending a new one (`PO:11003-11022`, `PO:1938-1965`).
- **Budget exhausted before synthesis**: raises `research_budget_exhausted …` (`PO:10877-10883`). Epoch-cap exhaustion raises from `_activate_research_budget_epoch` (`PO:1851-1856`).
- **Telemetry and observability helpers** (`_record_*_telemetry`, `_surface_forecast_confidence_penalty`, `_log_decision_channel_outcome` via its caller, `_write_run_manifest`, `_update_manifest`, heartbeat): they swallow exceptions and log at debug level. The run is not affected. [verifier: not true of `_record_research_telemetry` — `int(telemetry.get("tokens_in"/"tokens_out"))` at `PO:10448-10449` sits outside any try and its caller `PO:12205` is unwrapped, so a non-numeric token count would fail RESEARCH; `_surface_research_quality` has the same gap (Surprise 21)]

---

## Surprises

1. **Suspected bug: PREPARE registration stops after the first persona file.** In `_record_stage_artifacts`, `if add_if("personas", path): break` (`PO:9722-9725`) leaves the whole spec loop. When `twitter_profiles.csv` exists, the entries after it are never added to `state.artifacts` or `handoff/manifest.json`: `reddit_profiles.json`, `actor_cast` (`PO:9542`), `twitter_actor_roles` (`PO:9545`) and `reddit_actor_roles` (`PO:9548`). Because unregistered names are skipped by `_validate_reuse` (`PO:9830-9831`), these seal-relevant files are never integrity-checked on reuse either. PREPARE reuse still runs `validate_prepared_simulation_config` (`PO:12745-12748`), which partly compensates. [verifier: the `break` also fires when only `reddit_profiles.json` exists. The compensation is substantive: the config seal hash-checks `actor_cast_manifest.json` and both `*_profiles_roles.json` whenever they are bound (`backend/app/services/simulation_manager.py:188-221`). That check runs on PREPARE reuse and on RUN disk reuse (`PO:10036-10044`). So these files are missing only from the handoff-manifest check, not from all integrity checks.]
2. **Suspected false failure: an unguarded manifest write in `_publish_run_summary`** (`PO:10116-10121`). If it raises, the caller's `except` (`PO:13116-13117`) leaves `_run_summary_published=False`. `_require_run_completion_evidence` then fails RUN with the misleading message "run_summary.json missing or invalid" (`PO:10080-10084`), even though a valid summary exists. `_record_stage_artifacts` wraps the same write in a try (`PO:9747-9755`).
3. **Suspected resource leak in synthesis recovery.** `upd(2, …)` (`PO:10932`) runs after `mkdtemp` (`PO:10924`) but outside the `try`. Separately, `ProviderOutageHalt` is a `BaseException` (`PO:258`) raised by the updater (`PO:8966-8969`), so it is caught by neither `except PipelineCancelled` (`PO:10967`) nor `except Exception` (`PO:10977`). In both cases the `.synthesis-recovery-*` staging directory is left in `handoff/`, no attempt log is preserved, and `state.research_pid` is not cleared (`PO:11002`). [verifier: confirmed. The `write_text_atomic` call (`PO:10927`) is also outside the try. The handled `PipelineCancelled` path also re-raises (`PO:10976`) before `research_pid` is cleared. `resume()` clears it later (`PO:8181`).]
4. **Over-broad cleanup**: `_clear_report_attempt_artifacts` claims to clear "REPORT-owned" pointers (`PO:9682`) but pops **every** `*_partial` key (`PO:9686`). That includes RUN and RESEARCH partials such as `actions_twitter_partial`, `run_state_partial` and `dataset_*_partial`, so those live deep links disappear when a new REPORT attempt starts.
5. **Dead entry**: the `research_report` partial (`PO:10165`) points at the same file as spec `report` (`PO:9510`). `_stat` dedupes by path (`PO:10139`), so `research_report` is never emitted. Separately, both `personas` alternatives share one name, so `personas_partial` is overwritten by whichever file is iterated last (`PO:10236-10240`).
6. **Extension sets differ**: dynamic chart registration allows `{.png,.svg,.jpg,.jpeg,.webp,.html}` (`PO:9609`), while report-viz validation also allows `.gif` and `.mmd` (`PO:9653`). A `.gif` or `.mmd` report chart is validated but never deep-linked.
7. **ETA is biased after a resume**: `elapsed` is anchored at `resumed_at` (`PO:10263-10266`), but `global_progress` includes work done before the resume. Linear extrapolation (`PO:10296`) therefore underestimates the remaining time for resumed runs. The value is labeled approximate.
8. **Heartbeat comment vs code**: the comment says it writes one beat immediately (`PO:10353`), but the loop waits `interval` first (`PO:10354`). The "first beat" is only the in-memory `state.heartbeat_at` (`PO:10345`), which persists at the next `save` (for example the first `upd`).
9. **`owner_alive` uses the PID only** (`PO:10311`). After a restart, a reused PID reads as alive. The orphan reconciler also uses `owner_boot_id` and heartbeat freshness (`PO:7808-7826`), so the API block can disagree with reconciliation. [verifier: confirmed. Note that the frontend maps `owner_alive === false` to 'dead' (`frontend/src/utils/runVitals.js:96`). A reused PID gives `true`, so the UI falls back to stale and heartbeat age instead.]
10. **The gate knob does not control the penalty**: `RESEARCH_QUALITY_FLOOR` is 0.45 in Config (`backend/app/config.py:351`), while the code's getattr fallback is 0.0 (`PO:10628`, `PO:10667`). The penalty's `research_quality` component (`PO:10670-10674`) therefore applies by default even though `RESEARCH_QUALITY_GATE` defaults to false (`backend/app/config.py:348`). The gate controls only the warning (`PO:10630`). [verifier: confirmed. `backend/app/config.py:349-350` says this is intended: the floor drives the warning and the confidence penalty, while the hard gate stays opt-in.]
11. **Write-only outputs**:
    - `forecast_confidence_penalty` and its components have no consumer in `backend/app` or `frontend/src` (grep; acknowledged at `PO:10720-10722`).
    - `research_quality`, `research_quality_warning` and `decision_channel_summary` are not read by the frontend either. The docstring says "供 StageTimeline / API 展示" (`PO:10568`), but they are only visible in the raw `options` of the status payload (`backend/app/api/research.py:315`).
12. **Suspected as-of edge case**: one future-dated source makes `max_src > run_dt`. A valid `as_of_date` that is earlier than that source is then rejected (`PO:10824-10826`), and the anchor falls back to `run_dt` (`PO:10832`).
13. **Inconsistent reuse gating for legacy research**: it calls `_validate_reuse` directly (`PO:11947-11948`), not `_reuse_ok`. It is therefore not disabled by `PIPELINE_VALIDATE_ARTIFACTS=false`, and a validator exception propagates instead of failing closed with an `artifact_validation_error` breadcrumb.
14. **REPORT reuse checks only the viz files**: the REPORT spec list contains only `report_viz_manifest` (`PO:9556-9561`). `full_report.md`/`forecast.json` are not hash-checked here; report reuse relies on `ReportManager` status (`PO:13241`) plus viz references. [verifier: incomplete. Reuse also passes the ORCH-1 deliverable health check `_assess_report_health` (`PO:13211-13222`; placeholder chapters or a missing forecast.json reject reuse when PIPELINE_HEALTH_GATE is on). The files are still not hash-checked.]
15. **Hard-coded provider names**: the synthesis-recovery failure message names "MiniMax … Antigravity/Quotio" (`PO:11015-11017`) whatever `LLM_PROVIDER` is configured.
16. **Defensive exit check**: synthesis recovery's `exit_code != 0` branch (`PO:10959-10963`) is effectively defensive. The runner already raises on non-zero exit unless a timeout was salvaged (`PO:2618-2619`).
17. **`resumed: True` on a fresh synthesis**: synthesis recovery returns `_load_research_handoff(...)`, which includes `"resumed": True` (`PO:3886`) even for a freshly synthesized generation. No consumer of `research["resumed"]` was found (grep), so it is harmless today but misleading.
18. **Forks split the manifest from the files**: `handoff/manifest.json` always uses the pipeline's own static handoff path (`PO:1108-1110`), while specs resolve against `state.handoff_dir` (`PO:9507`), which points at the base pipeline for forks. A fork's integrity rows therefore hash files that live in another pipeline's directory.
19. **Two roots for the same simulation directory**: `Config.OASIS_SIMULATION_DATA_DIR` (`backend/app/config.py:1080`; used at `PO:9534`, `PO:10747`) and `SimulationRunner.RUN_STATE_DIR` (`backend/app/services/simulation_runner.py:279-282`; used at `PO:9555`, `PO:9930`, `PO:10002`, `PO:10102`, `PO:10170`, `PO:10495`). Both resolve to `backend/uploads/simulations`, but they are independent constants.
20. **Runtime attestation is reddit-only**: `_completed_sim_reusable` checks only `reddit_runtime_system_messages.json` (`PO:10048-10054`). A twitter-only run relies on the config seal alone.
21. **Possible hard failure despite the docstring**: in `_surface_research_quality`, `dict(meta.get("research_quality") or {})` (`PO:10582`) and the `int(...)` conversions on budget counters (`PO:10593-10595`) are outside any try, and the caller does not wrap the call (`PO:12210`). A malformed `meta`/budget value could fail RESEARCH, despite the "永不硬失败" docstring (`PO:10572`).
22. **Doc-vs-code drift**:
    - Stale line anchors in `DRF_ARCHITECTURE.md:217-219`, `:309` and `ARCHITECTURE_MAP.md:449-452`:
      - `_stage_artifact_specs` cited as `:4920-4974`, actually `PO:9500`;
      - `_manifest_entry_for` cited as `:3127`, actually `PO:7452`;
      - `_validate_reuse` cited as `:5180-5254`, actually `PO:9798`;
      - `_start_heartbeat` cited as `:5447`, actually `PO:10331`.
    - `ARCHITECTURE_MAP.md:441` says "Every artifact is checksummed", and `DRF_ARCHITECTURE.md:1416` says manifest.json validates "everything above". In code, only spec-listed, existing, non-empty, actually recorded files are checksummed. See item 1 for the PREPARE gap. Research reuse is now keyed primarily on `research_contract_manifest.json` (`PO:11920-11946`), not `manifest.json`.
    - The `_write_run_manifest` comment mentions "GET /manifest" (`PO:10387`), but no such route exists. Only `/<id>/artifact/run_manifest` is available (`backend/app/api/research.py:779`).

---

## Verification

An adversarial verifier checked this map on 2026-10-11 against `backend/app/services/pipeline_orchestrator.py` on branch `main`, read-only. Each item was checked by opening the cited code. Inline `[verifier: …]` notes above mark the statements that were corrected.

### Verdict counts

| Group | Checked | Confirmed | Imprecise | Refuted |
|---|---|---|---|---|
| Key claims | 15 | 11 | 4 | 0 |
| Surprises | 16 | 14 | 2 | 0 |
| Other spot-checks (Walkthrough, Control flow, tables) | 23 | 11 | 12 | 0 |
| **Total** | **54** | **36** | **18** | **0** |

Nothing was refuted. The suspected bugs all hold up in the code: the PREPARE `break`, the unguarded manifest write in `_publish_run_summary`, the staging-dir leak in synthesis recovery, the over-broad `*_partial` purge, the legacy research path that bypasses `_reuse_ok`, the as-of rejection caused by a future-dated source, and the fork manifest split.

### Non-confirmed key claims, with corrections

1. **PREPARE `break` (claim 2 and Surprise 1): imprecise.**
   - The `break` at `PO:9724-9725` fires when *either* persona file exists, including the case where only `reddit_profiles.json` exists. So `actor_cast`, `twitter_actor_roles` and `reddit_actor_roles` are never put into `state.artifacts` or `handoff/manifest.json`.
   - "Never integrity-checked on reuse" is overstated. The simulation-config seal hash-checks `actor_cast_manifest.json` and both `*_profiles_roles.json` files whenever the seal binds them (`backend/app/services/simulation_manager.py:188-221`).
   - That seal check runs on PREPARE reuse, through `validate_prepared_simulation_config` (`PO:12745-12748`; `backend/app/services/simulation_manager.py:1446-1452`), and on RUN disk reuse (`PO:10036-10044`). The files are missing only from the handoff-manifest check.
2. **`_completed_sim_reusable` (claim 5): imprecise.**
   - The claim leaves out the `no_config_seal_identity` check (`PO:10027-10035`).
   - Process liveness is probed only when `runner_status` is STARTING or RUNNING (`PO:10007-10014`).
   - Not every exception yields `reuse_check_error`. Seal errors (`OSError`/`ValueError`/`TypeError`/`JSONDecodeError`) return `config_seal_mismatch:…` (`PO:10045-10046`). A liveness-probe exception returns `simulation_liveness_unknown` (`PO:10013-10014`). Only other exceptions reach `reuse_check_error` (`PO:10056-10057`).
   - The attestation comparison needs both SHAs to be non-empty (`PO:10053`).
   - The Walkthrough itself states all of this correctly.
3. **`_record_sim_run_telemetry` (claim 12): imprecise.**
   - Wrong as stated: "a provider of 'claude' or 'codex' is mapped to 'claude-cli'". A non-empty provider other than `unknown` is kept as-is.
   - The `claude-cli` mapping is a fallback. It applies only when the provider is empty or `unknown`, and it is keyed on the **model** (`PO:10512-10514`). The Walkthrough line "provider falls back to the claude-cli mapping" is correct.
   - The marker is persisted through a `save` whose failure is swallowed (`PO:10536-10539`). If that save fails, metering still proceeds with only an in-memory marker.
4. **Synthesis recovery (claim 15): imprecise.**
   - Failed and cancelled attempts are preserved only when the staging dir contains `research_progress.log`; the sidecars are copied only in that case (`PO:3094-3096`).
   - A successful-exit candidate whose promotion fails (`PO:11040-11047`; validation raises at `PO:3571-3576`) propagates an exception. In that case `synthesis_recovery.passed=False` is not recorded and the staging dir is not removed.
5. **Surprise 14 (REPORT reuse): imprecise.** Report reuse also goes through the ORCH-1 deliverable health check `_assess_report_health`. When PIPELINE_HEALTH_GATE is on and health is `failed`, reuse is dropped and `report_rebuilt_broken_deliverable` is set (`PO:13211-13222`). `force_report_regen` also skips reuse (`PO:13224-13226`). Both happen before `_reuse_ok(REPORT)` (`PO:13233`). The point that `full_report.md`/`forecast.json` are not hash-checked still stands.

**Confirmed with nuance:**
- Surprise 3: `write_text_atomic` (`PO:10927`) is also outside the try. The handled `PipelineCancelled` path re-raises (`PO:10976`) before `research_pid` is cleared (`PO:11002`). `resume()` later clears it (`PO:8181`).
- Surprise 8 (RESEARCH_QUALITY_FLOOR applies by default): this is intended per `backend/app/config.py:349-350`.
- Surprise 16 (`owner_alive` from the PID only): the frontend maps `owner_alive === false` to 'dead' (`frontend/src/utils/runVitals.js:96`). A reused PID reads as alive, so the UI falls back to stale and heartbeat age.
- Claim 11 (heartbeat exit): `touch_heartbeat` also returns False when the state file is missing or incompatible (`PO:1087-1088`).

### Non-confirmed map statements found by spot-check

1. **Purpose item 2**: "check it before any completed stage is reused".
   - Only GRAPH, PREPARE, RUN and REPORT use `_reuse_ok`. Legacy (no-contract) RESEARCH calls `_validate_reuse` directly (`PO:11948`).
   - Contract-backed RESEARCH uses `_validate_research_contract` (`PO:11920-11921`).
   - ONTOLOGY reuse checks only `project.ontology` (`PO:12312-12314`).
2. **Purpose "two API modules"**: both call sites are in `backend/app/api/research.py`. The `heartbeat_status` call is at `:318`, not `:316`.
3. **`dossier_coverage` "set at `PO:12218`"**: the assignment is at `PO:12219`.
4. **Budget epoch "opens a new epoch"**: `_activate_research_budget_epoch` first returns the epoch already bound to the same `task_id` (`PO:1840-1849`).
5. **Control flow PREPARE step 3**: the stage-bit branch of `_run_already_done` also requires `_prepare_reuse` (`PO:12849-12850`).
6. **Control flow REPORT step 2**: omits the ORCH-1 health gate and `force_report_regen` (`PO:13211-13226`).
7. **Cross-module edges**: `heartbeat_status` is called at `backend/app/api/research.py:318`, not `:316`. `LLM_RUN_BUDGET_TOKENS` is read at `:319`, not `:318`.
8. **runVitals consumers**: the list is incomplete. The frontend also reads `owner_alive` (`frontend/src/utils/runVitals.js:96`), `elapsed_s` (`:138`), `budget` (`:164-168`), `last_progress_age_s` and `owner_pid` (`:191-192`).
9. **Invariant "as-of never before newest source date"**: this fails with a future-dated source. The fallback is then `run_dt`, which is earlier than `max_src` (`PO:10831-10832`).
10. **Failure modes "telemetry helpers swallow exceptions"**:
    - `_record_research_telemetry` runs `int(...)` on `tokens_in`/`tokens_out` outside any try (`PO:10448-10449`).
    - Its caller is unwrapped (`PO:12205`), so malformed telemetry would fail RESEARCH.
11. **Config table**:
    - `PIPELINE_TELEMETRY_FLUSH_EVERY_CALLS` is defined in Config (`backend/app/config.py:490`, default 20). A value of 0 disables it (`PO:7624-7625`).
    - `MANIFEST_CAPTURE_VERSIONS` is defined in Config (`backend/app/config.py:472`). Neither knob is getattr-only.
12. **External-calls anchors are swapped**:
    - `LLMMeter.record` is `backend/app/utils/telemetry.py:231` and `snapshot` is `:273`.
    - `write_text_atomic` is `backend/app/utils/atomic.py:20` and `write_json_atomic` is `:53`.

**Spot-checks confirmed as written:**
- `_charts_manifest_path` fallback (`PO:9573-9577`).
- `_validate_report_viz_references` rules (`PO:9639-9679`).
- The `_reuse_ok` caller table (`PO:12398`, `:12741`, `:12836`, `:12852`, `:12957`, `:13233`).
- The terminal-elapsed freeze in `estimate_eta` (`PO:10267-10277`).
- The `_record_research_telemetry` provider mapping (`PO:10457`).
- Synthesis model concurrency = 10 (`PO:5845-5854`).
- `--synthesis-manifest` forces the legacy engine (`PO:2268-2269`, `PO:2295-2300`).
- Surprise 17: `resumed: True` (`PO:3886`); no consumer was found.
- Surprise 19: two simulation roots (`backend/app/config.py:1080`; `backend/app/services/simulation_runner.py:279-282`).
- Surprise 20: the attestation is reddit-only (`backend/scripts/run_parallel_simulation.py:685`).
- Surprise 21: `_surface_research_quality` is unguarded (`PO:10582`, `PO:10593-10595`, caller `PO:12210`).

### Omissions (significant behavior the map does not cover)

1. **Dynamic chart rows are written to the integrity manifest but never validated.**
   - `_record_stage_artifacts` writes `chart_*` and `report_chart_*` rows into `handoff/manifest.json` (`PO:9732-9743`, `PO:9749-9752`).
   - `_validate_reuse` iterates only the static spec names (`PO:9824-9831`), so those rows are never hash-checked.
   - Report charts are covered only indirectly, by `_validate_report_viz_references`.
2. **ONTOLOGY reuse never consults the manifest.** It is decided by `project.ontology` alone (`PO:12312-12314`), so the recorded `ontology` row (spec `PO:9524`) is never verified.
3. **Promotion failure in synthesis recovery is unhandled.**
   - `_promote_research_contract` (`PO:11040-11047`) can raise after rolling back (`PO:3571-3597`). The `.synthesis-recovery-*` source dir is then left behind, and `synthesis_recovery` is not recorded.
   - On the next resume, `_synthesis_recovery_budget_epoch` (`PO:1938-1966`) then does not reuse the epoch. That spends a new epoch against `RESEARCH_BUDGET_MAX_EPOCHS`.
4. **`_probe_artifact_schema` fails open and dispatches by filename.**
   - It returns True on any unexpected exception (`PO:7448-7449`).
   - It picks its probe by file basename, not by artifact name (`PO:7433-7445`).
   - This weakens the "schema probe must pass" leg of `_validate_reuse`.
5. **`_record_research_telemetry` is not exception-safe.** Its `int()` conversions sit outside any try (`PO:10448-10449`), and the caller is unwrapped (`PO:12205`).
6. **REPORT reuse has more gates.** The ORCH-1 deliverable health gate and `force_report_regen` both precede `_reuse_ok(REPORT)` (`PO:13207-13226`).
7. **The `_validate_reuse` docstring is wrong about its callers.** It says the method is called only when PIPELINE_VALIDATE_ARTIFACTS is on (`PO:9809`), but the legacy research path calls it unconditionally (`PO:11947-11949`).
8. **Attempt logs are preserved only conditionally.** Sidecars are preserved only if the staging dir has `research_progress.log` (`PO:3094-3096`). A runner that fails before writing that log leaves no forensic trace.
