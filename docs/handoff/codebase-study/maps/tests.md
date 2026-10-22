# tests — Backend test suite and test harness

Scope of this map: `backend/tests/` (180 `.py` files incl. `conftest.py`, plus `backend/tests/eval/` fixtures), `deerflow_bridge/patches/tests/` (6 `.py` files), and the pytest configuration in `backend/pyproject.toml`. Studied on branch `main`, working tree as on disk (2026-10-11). Nothing was executed except read-only shell inspection; test counts below are static AST counts of `def test_*` functions (parametrization expands them at run time), not a run result.

Reading method (honest disclosure): `conftest.py`, `backend/tests/eval/*`, all six `deerflow_bridge/patches/tests/*.py` files, `test_architecture_characterization.py`, `test_architecture_baseline_cli.py`, `test_config_optimization_defaults.py`, `test_runtime_lifecycle_isolation.py`, `test_eval_forecast_quality.py` and `test_foglamp_containment.py` were read line by line. For the other ~170 files every module docstring, import, fixture, class, test name/first docstring line, skip/xfail site, subprocess site and env-var mutation was extracted with an AST pass over the source, and the harness-relevant regions (imports, fixtures, gating helpers) were read directly. Individual assertions were not all read (the slice brief says "map rather than read every assertion").

## Purpose & position in the pipeline

- The backend suite is an **offline-first regression harness** for the whole DRF pipeline: Stage-1 deep research (the `deerflow_bridge/*` scripts that run inside DeerFlow's venv, plus the v3 "linear" engine), Stage-2 knowledge graph (Graphiti/Zep compatibility layer), ontology/actor/profile/config preparation, Stage-3 OASIS simulation runtime (`backend/scripts/run_*_simulation.py`), Stage-4 report/forecast/visualization/translation/publication, the Flask API surface, telemetry/LLM-client infrastructure, maintenance scripts, and the experimental `drf2/` scaffold. The intent "no LLM/network" is declared in `backend/pyproject.toml:81-82` and `backend/tests/conftest.py:1-6`.
- It is wired into CI as the `unit` job (`.github/workflows/ci.yml:23-38`: `cd backend && uv run pytest -q`) and into `npm test` (`package.json:17`: `cd backend && uv run pytest`).
- `backend/tests/eval/` holds **fixtures for two opt-in quality harnesses that live in `backend/scripts/`**: a rubric LLM-judge (`backend/scripts/eval_forecast_quality.py:43-47` reads `rubric.md`, `baseline_scores.json`, `scenarios/*.json`) and a deterministic golden-question Brier/ECE scorer (`backend/scripts/golden_eval.py:60-61` reads `golden_questions.json`). The pytest suite only unit-tests their pure cores; the live judge is never run by pytest.
- A second, separate suite in `deerflow_bridge/patches/tests/` regression-tests DRF's overlays onto the vendored DeerFlow tree and must be run with **DeerFlow's own venv** (`deerflow_bridge/patches/tests/test_lead_agent_trim_none.py:3-5`, `test_subagent_runtime_contract.py:3-7`); it is not collected by the backend suite because `testpaths = ["tests"]` (`backend/pyproject.toml:84`).
- Characterization/architecture tests (Foglamp WP0/WP1) pin current unsafe-path behavior and future fixes as strict xfails (`backend/tests/test_architecture_characterization.py:1-19`).

Size at a glance (static): 179 `test_*.py` files + `conftest.py` in `backend/tests/`, **3,397 `def test_*` functions, ~76.7k lines**; 5 test files + `conftest.py` in `deerflow_bridge/patches/tests/` with 23 test functions. The most recent recorded full run on main is "backend 4,406 passed / 0 failed / 11 xfailed" (`agent-progress.txt:308`, 2026-09-30) — the 11 xfails equal the 11 strict-xfail markers in `test_architecture_characterization.py`.

## Walkthrough (source order)

### `backend/pyproject.toml` — pytest-relevant configuration

| item | value | anchor |
|---|---|---|
| Python | `requires-python = ">=3.12"` | `backend/pyproject.toml:7` |
| test deps (extra) | `[project.optional-dependencies] dev = pytest>=8.0.0, pytest-asyncio>=0.23.0, pipreqs>=0.5.0` | `backend/pyproject.toml:54-59` |
| test deps (uv group) | `[dependency-groups] dev = pytest>=8.0.0, pytest-asyncio>=0.23.0` (installed by `uv run`/`uv sync` by default) | `backend/pyproject.toml:72-76` |
| `testpaths` | `["tests"]` (relative to rootdir `backend/`) | `backend/pyproject.toml:84` |
| `addopts` | `"-q"` | `backend/pyproject.toml:85` |
| `filterwarnings` | `["ignore::DeprecationWarning"]` | `backend/pyproject.toml:86` |
| markers | **none registered**; no `asyncio_mode`; no `timeout` plugin config | `backend/pyproject.toml:83-86` |
| ruff | line-length 120, `select = F,E9,B,C4`, `ignore = F401,F841,B008` (CI uses a different ignore set, see Surprises) | `backend/pyproject.toml:90-97` |

Installed in `backend/.venv` at study time: pytest 8.2.0, pytest-asyncio 0.23.6, plotly 6.9.0, kaleido 1.3.0, matplotlib 3.11.0, mcp 1.24.0, graphiti_core 0.29.2, camel-oasis 0.2.5, PyYAML 6.0.3; **no langchain** (several tests rely on that absence, e.g. `backend/tests/test_claude_prompt_cache.py:31-38`).

### `backend/tests/conftest.py` (207 lines) — the only shared harness

1. **Module docstring** (`conftest.py:1-6`): declares the offline-first contract and the FakeLLMClient record/replay stub (EXECPLAN2 I-7-0 / I-7-4).
2. **`os.environ["DRF_TEST_PROCESS"] = "1"`** (`conftest.py:19`), executed at conftest import time, i.e. before any test module is imported. Consumers:
   - `backend/app/config.py:18-19`: when `DRF_TEST_PROCESS == '1'` the root `.env` is **not** loaded (otherwise `load_dotenv(project_root_env, override=True)` at `config.py:20-21`). So `Config` class attributes take code defaults in tests.
   - `backend/app/__init__.py:122-125`: `_runtime_lifecycle_enabled` is false when `app.config['TESTING']` or `DRF_TEST_PROCESS == '1'`, so `create_app()` skips `SimulationRunner.register_cleanup()`, `SimulationRunner.reconcile_orphans()` and `PipelineOrchestrator.reconcile_orphans()/register_cleanup()` (which send real OS signals and rewrite `uploads/` state). Pinned by `test_runtime_lifecycle_isolation.py:19-46` (no hook calls) and `:49-81` (marker absent ⇒ exactly `simulation-register, simulation-reconcile, pipeline-reconcile, pipeline-register`).
3. **`sys.path.insert(0, <backend dir>)`** (`conftest.py:22`): makes `import app…`, `import scripts.<x>` (namespace package `backend/scripts`) and `from tests.conftest import FakeLLMClient` (namespace package `backend/tests`, no `__init__.py`) importable.
4. **`class FakeLLMClient`** (`conftest.py:25-53`): constructor `(responses=None, json_responses=None, provider="fake", model="fake-1")`; `chat(messages, temperature=0.7, max_tokens=4096, response_format=None)` appends `{"kind":"chat","messages","temperature"}` to `.calls` and pops the next scripted string, else returns `"FAKE_RESPONSE"`; `chat_json(messages, temperature=0.3, max_tokens=4096)` likewise pops scripted dicts, else `{}`; `supports_native_tools()` → `False`. No network, no side effects. Imported directly (as `tests.conftest.FakeLLMClient`) by 14 test files (e.g. `test_architecture_characterization.py:33`, `test_foglamp_containment.py:35`, `test_forecast_extractor.py:31`).
5. **`_no_prediction_market_network`** (autouse, function scope; `conftest.py:56-67`): `monkeypatch.setenv("PREDICTION_MARKETS_ENABLED","false")` and, if `app.config` imports, `Config.PREDICTION_MARKETS_ENABLED = False`; import failure is swallowed (env var is the fallback). Tests needing the Polymarket client re-enable it and mock `httpx` (e.g. `enabled` fixtures at `test_prediction_markets.py:73`, `test_report_market_crosscheck.py:57`, `test_resolution_monitor.py:36`).
6. **`_no_ambient_firecrawl_key`** (autouse; `conftest.py:70-76`): `monkeypatch.delenv("FIRECRAWL_API_KEY")` so search/fetch routing does not drift to the paid Firecrawl backend; Firecrawl tests set a fake key and fake `httpx` (`test_sessionb_firecrawl.py:73`, `test_sessionb_firecrawl_guardrails.py:79`).
7. **`_no_ambient_research_engine_selection`** (autouse; `conftest.py:79-91`): deletes `RESEARCH_ENGINE` and `RESEARCH_LINEAR_MODE` because sim scripts imported by tests call `load_dotenv` themselves (see Surprises) and would otherwise reroute `deerflow_research.main()`.
8. **`fake_llm`** factory fixture (`conftest.py:94-99`): returns `lambda **kw: FakeLLMClient(**kw)`. Only consumer: `test_eval_forecast_quality.py:159`.
9. **`tmp_run_dir`** fixture (`conftest.py:102-107`): creates `<tmp_path>/run` and returns its path string. **No consumer** (dead fixture).
10. **`_BACKEND_LOGS_DIR`** (`conftest.py:122-123`) = `backend/logs`.
11. **`_quarantine_mirofish_log_handlers`** (autouse, **session** scope; `conftest.py:126-184`): creates `tmp_path_factory.mktemp("mirofish-logs")`, builds one shared `logging.FileHandler(<sink>/mirofish.log)` at DEBUG (falls back to `NullHandler` on any failure), repoints `app.utils.logger.LOG_DIR` (`backend/app/utils/logger.py:48`, read at call time by `setup_logger`, `logger.py:51-63`) to the sink dir, then for every existing logger named `mirofish` or `mirofish.*` removes and closes each handler whose `baseFilename` lies under `backend/logs` and attaches the shared sink. Never restores (session end == process end). Every step is wrapped in `try/except Exception: pass` so logging problems cannot fail the session. Motivation in comment `conftest.py:110-120` (a 3.2 MB rotated production log of pure pytest noise, 2026-07-22).
12. **`_isolate_telemetry_active_runs`** (autouse; `conftest.py:187-206`): calls `app.utils.telemetry._clear_active_runs()` (`backend/app/utils/telemetry.py:80-83`) before and after every test so the process-global FOG-TEL-1 single-active-run fallback registry cannot leak "active" runs between tests.

No `pytest_*` hook functions, no custom markers, no `pytest_collection_modifyitems`, no timeout handling are defined in either conftest.

### `backend/tests/eval/` — quality-harness fixtures (no tests in this directory)

| file | content | consumers |
|---|---|---|
| `backend/tests/eval/rubric.md` (56 lines) | Five 0–5 judge dimensions `groundedness`, `coverage`, `calibration`, `contradiction`, `citation_density`, strict-JSON reply shape, "temperature 0, average k=3, coarse thresholds ± tolerance vs baseline" (`rubric.md:3-10`); per-dimension anchors at 0/2/4/5 (`rubric.md:14-56`). | `eval_forecast_quality.parse_rubric` (`backend/scripts/eval_forecast_quality.py:176`), `test_eval_forecast_quality.py:111-122` |
| `backend/tests/eval/baseline_scores.json` (27 lines) | Per-scenario **floors** (not measured scores): us-iran-2026 g3.0/cov3.5/cal3.0/con3.0/cd1.0; memory-semi-2030 and china-storage-2035 g3.0/cov3.0/cal2.5/con3.0/cd1.0; `tolerance` 0.5 each; `_comment` says to replace via `run --update-baseline` (`baseline_scores.json:2-26`). A dimension fails when its k-pass mean < floor − tolerance. | `eval_forecast_quality.compare_vs_baseline`; `test_eval_forecast_quality.py:193-199` checks every scenario × dimension is present |
| `backend/tests/eval/scenarios/{us-iran-2026,memory-semi-2030,china-storage-2035}.json` (15–16 lines each) | `name`, `question`, `report_path` → committed demo report `docs/demos/<name>/report.md`, `expected_outcome {scenario, key_signals[], rationale}`, `created_date` 2026-06-15. All three report paths exist and are git-tracked. | `eval_forecast_quality.discover_scenarios/load_scenario/resolve_report_path`; `test_eval_forecast_quality.py:184-190` asserts each resolves to an existing file |
| `backend/tests/eval/golden_questions.json` (310 lines) | `_meta` (description, outcome semantics, schema, `count: 30`) + 30 resolved binary questions with `id, question, resolution_criteria, resolved_outcome, resolution_date, category, difficulty, as_of_date` (`golden_questions.json:2-7`). Composition: **24 YES / 6 NO**; categories elections 11, sports 6, monetary-policy 4, product-launch 3, markets 3, science-tech 1, legal-politics 1, awards 1; resolution dates 2024-02-02…2025-02-09. | `golden_eval.load_golden_set` (`backend/scripts/golden_eval.py:61`); `test_golden_eval.py:140-155` (≥25 questions, unique ids, bool outcome, criteria/as_of present, `as_of_date <= resolution_date`, both outcomes present); `test_architecture_characterization.py:297-312` and `test_foglamp_containment.py:415-426` assert it is answer-bearing (characterization of a leak) |

Eval harness constants used with these fixtures: `RUBRIC_DIMENSIONS` fixed order, `SCORE_MIN/MAX = 0/5`, `DEFAULT_TOLERANCE = 0.5`, `DEFAULT_K = 3` (`backend/scripts/eval_forecast_quality.py:51-56`); the live judge runs only with `Config.EVAL_ENABLED` or `--live` (`eval_forecast_quality.py:12-16`). `golden_eval.py` `DEFAULT_BINS = 10`, `_EPS = 1e-9` (`backend/scripts/golden_eval.py:63-64`); writing golden outcomes to the ledger is opt-in (`GOLDEN_EVAL_LEDGER=true … --to-ledger`, `golden_eval.py:33-36`).

### Characterization / architecture / config-pin tests (the invariant-pinning layer)

**`test_architecture_characterization.py` (321 lines, 25 tests)** — Foglamp WP0 slice 0B. Twelve "confirmed failure paths" each get a `test_characterizes_<name>` (passes only while it describes current behavior) and a `test_wp_<owner>_prevents_<name>` future regression; rows owned by not-yet-landed work packages are `@pytest.mark.xfail(strict=True)` so they turn the suite red (XPASS) the moment the owning module appears (`:3-12`). Uses synthetic fixtures + `inspect.getsource` shape checks (`:36-37`).

| # | path | characterization (what is pinned today) | paired future test | status |
|---|---|---|---|---|
| 1 | shared_graph_feedback | `AgentActivity.to_episode_text()` contains no sim/seed/run_id labels (`:41-54`) | imports `app.services.projections.graph_projection.ExperimentOverlay` (`:57-62`) | xfail strict (WP10) |
| 2 | market_descendant_reuse | `derive_forecast_spine(market_block=…)`, `extract_binary_forecasts(market_pack=…)`; `app.services.influence_lineage` absent (`:66-75`) | `influence_lineage.InfluenceCluster` (`:78-83`) | xfail strict (WP6) |
| 3 | social_to_institutional_laundering | `_build_round_decision_prompt` contains "投票/下单/站队/分配"; `app.domain.contracts` absent (`:87-96`) | `ActionProposal/FeasibilityResult/ExecutedAction` (`:99-105`) | xfail strict (WP11) |
| 4 | failure_false_convergence | 30 failed rounds ⇒ `WorldState.converged() is False`, `failed_rounds == 30` (`:109-117`) | `run_decision_channel` with raising LLM ⇒ `validity=invalid`, `forecast_effect=no_update`, not converged (`:120-132`) | **green** (WP1 landed) |
| 5 | visibility_to_outcome_power | `_build_active_roster` gives `outcome_power 1.0`, `outcome_power_known False` (`:136-143`) | `_outcome_power_map([{influence_weight:5}]) == {}` (`:146-150`); unknown power ⇒ S1 share stays 0.5 (`:153-165`) | green + xfail strict (WP11) |
| 6 | fork_seed_shared_mutation | `_run_one_seed` source calls `create_simulation(project.project_id, graph_id…)` with no "overlay"; `N_FORECAST_SEEDS ≥ 1` (`:169-178`) | `app.services.experiment_service.ExperimentService` (`:181-186`) | xfail strict (WP12) |
| 7 | structured_spine_omissions | spine accepts `base_distribution`/`quantitative_facts` but `ReportAgent._derive_and_pin_forecast_spine` source passes neither (`:190-199`) | `app.services.forecast_evidence_pack` (`:202-207`) | xfail strict (WP6) |
| 8 | dormant_typed_worldstate_anchor | `Config.REPORT_SPINE_ANCHOR_WORLDSTATE is True`, no `base_distribution=`, `legacy_prompt` gate present (`:211-218`) | same evidence-pack module (`:221-226`) | xfail strict (WP6) |
| 9 | edit_without_research_generation | `PipelineState` dataclass has no `research_generation_id/case_id/run_spec_id` (`:230-238`) | `app.services.research_generation_service` (`:241-246`) | xfail strict (WP4) |
| 10 | write_only_quality_and_late_health | in `PipelineOrchestrator._run` source, `self._enforce_pipeline_health(` appears after `self._maybe_run_seed_ensemble(` (`:250-258`) | `app.services.run_quality` (`:261-266`) | xfail strict (WP6) |
| 11 | disconnected_resolution_lifecycle | `append_market_resolution` does not flip ledger row `resolved` (`:270-285`) | `app.services.resolution_service` (`:288-293`) | xfail strict (WP13) |
| 12 | answer_bearing_golden_harness | golden fixture carries `resolved_outcome`; `app.evaluation.case_registry` spec is None (`:297-312`) | `app.evaluation.case_registry` (`:315-320`) | xfail strict (WP14) |

Verified on disk: none of `app/services/{influence_lineage,experiment_service,forecast_evidence_pack,research_generation_service,run_quality,resolution_service}.py`, `app/services/projections/`, `app/domain/`, `app/evaluation/` exist, so all 11 xfails currently fail as expected.

**`test_foglamp_containment.py` (426 lines, 19 tests)** — Foglamp WP1 containment red tests (`:1-20`): config-source regexes require `SIM_GRAPH_FEEDBACK`, `SIM_TYPED_FEEDBACK_EDGES`, `SIM_INTERVIEW_GRAPH_FEEDBACK` to default `'false'` (`:61-74`); `write_interview_fact`/`_write_typed_edges` refuse writes when gated (`:77-139`); `capture_safety_policy_v1("admission")` snapshot keys (`:142-157`) and `_pinned_safety` prefers the pinned value over ambient Config (`:160-178`); provider failure ⇒ `invalid/no_update/not converged`, 6 failed rounds (`:181-196`); abstained / silent / failed / equilibrium are four distinct accountings (`:199-236`); failed rounds freeze WorldState shares (`:239-249`); a settled EWMA plus one failed round is `inconclusive` and `CONVERGENCE_POLICY_V1["max_failed_rounds"] == 0` (`:252-263`); unexplained empty round ⇒ `silent` (`:266-273`); unknown outcome power ⇒ 1.0, not influence 50 (`:276-287`); config-source regexes `N_FORECAST_SEEDS '1'`, `REPORT_SPINE_SELFCONSISTENCY_K '1'`, `ENSEMBLE_EXTREMIZE_A '1.0'`, `SIMULATION_FORECAST_EFFECT 'diagnostic_only'` (`:290-300`); `epistemic_status == "elicited_model_projection"` (`:303-313`); `diagnostic_only` keeps "[Simulation quantitative signals]" out of binary-probability prompts while `legacy_prompt` restores it (`:316-342`); `no_update` empties the signal pack (`:345-352`); signal-pack header text requirements (`:355-369`); golden rows redirected to `_evaluation_ledger` (`:372-388`); calibration excludes golden/characterization/evaluation rows (`:391-412`).

**`test_config_optimization_defaults.py` (135 lines, 2 tests)** — pins 34 shipped `Config` defaults (`EXPECTED`, `:21-69`; e.g. `DEFAULT_CHUNK_SIZE 2500`, `GRAPH_BUILD_CONCURRENCY 4`, `GRAPH_MAX_NODES 8000`, `REPORT_SECTION_CONCURRENCY 6`, `OASIS_DEFAULT_MAX_ROUNDS 36`, `OASIS_SEMAPHORE 24`, `FORECAST_PROB_FLOOR 0.03`, `REPORT_SPINE_SELFCONSISTENCY_K 1`, `ENSEMBLE_EXTREMIZE_A 1.0`, `FORECAST_MARKET_DIVERGENCE_MIN_CONFIDENCE 0.6`, `RESEARCH_QUALITY_FLOOR 0.45`, `RESEARCH_ENGINE "v3"`). Mechanism `_load_code_defaults` (`:87-104`): spawns `sys.executable -c _CHILD` with `cwd=backend/`, an env stripped of every key starting with `LLM_ GRAPH OASIS REPORT SIM FORECAST ENSEMBLE ONTOLOGY RESEARCH IPC PROFILE ZEP EMBED DEFAULT_CHUNK`; the child (`:72-82`) replaces `dotenv.load_dotenv` with a no-op, pops the 34 keys, imports `app.config.Config` and prints `<<<JSON>>>{…}`. `test_degrade_safe_invariants` (`:113-134`): `GRAPH_BUILD_CONCURRENCY>1 ⇒ GRAPH_RESOLVE_ENTITIES`, `SIM_DECISION_CHANNEL ⇒ OASIS_DEFAULT_MAX_ROUNDS>0`, `GRAPHITI_OP_TIMEOUT_S>0`, `0<FORECAST_PROB_FLOOR<0.5`, `REPORT_SPINE_SELFCONSISTENCY_K>=1`.

Other config pins (in-process, so they rely on `DRF_TEST_PROCESS` suppressing `.env`): `test_audit_fixes_infra.py:25-102` (57 flags in `NEW_FLAGS_AND_DEFAULTS`; value assertion skipped for any name present in `os.environ`, `:98-99`), `test_wave9_orchestrator.py:529-543` (9 W9 flags, same skip rule), `test_report_section_concurrency_parity.py:33-45` (regex over `backend/app/config.py` source requires default `'6'`), `test_graph_cost_containment.py:135-138` (cast-chunk filter on, max attempts 2).

**Source-shape / wiring characterizations**: `test_sim_resume_reuse.py:378-411` asserts index order inside `inspect.getsource(PipelineOrchestrator._run)` (reuse probe < `SimulationRunner.start_simulation`, completion-evidence gate < `_complete_stage(STAGE_RUN)`, `_record_sim_run_telemetry` on both success and `except BaseException` boundaries); `test_temporal_mode_contract.py` (presence-keyed calendar dispatch, `:1-21`); `test_deerflow_bridge_sync_guard.py:213-235` parses `setup.sh` for its single bridge-copy loop and requires it to deploy every drift-guarded module; `test_drf2_skills_config.py:634-640` requires `setup.sh` to use `runtime_skill_sync.py`; `test_sessionb_report_prompts.py:71-95` compares prompt-template placeholder sets with `git show HEAD:backend/app/services/report_agent.py`.

### Per-file map of `backend/tests/test_*.py`

Columns: static `def test_*` count; "module(s) under test" from imports + docstrings; harness notes list file-relative line numbers where `skip`/`skipif`/`importorskip` and `xfail` appear, lines that mention `subprocess.`/`Popen` (this includes fakes, monkeypatches and docstrings, not only real launches — real launches are listed under External calls), Flask `test_client` use, and locally defined fixtures (first five). Shared harness patterns are explained after the tables.

#### Harness, meta, eval and script tests — 12 files, 164 static test functions, ~3520 lines

| file | lines | tests | module(s) under test / what it pins | harness notes |
|---|---:|---:|---|---|
| `backend/tests/test_architecture_baseline_cli.py` | 173 | 6 | `backend/scripts/architecture_baseline.py` CLI via subprocess: capture/verify/compare round-trip, byte-identical manifest, relative-root rejection (exit 2), secret-canary quarantine | subprocess@14,16,34 |
| `backend/tests/test_architecture_characterization.py` | 321 | 25 | Foglamp WP0 characterization suite: 12 failure paths x (characterize current behavior, strict-xfail future-WP fix); pins `decision_channel`, `forecast_extractor`, `forecast_ledger`, `report_agent`, `worldstate`, `pipeline_orchestrator` source shapes | xfail(strict)@8,57,78,99,153,181,202,221,241,261,288,315 |
| `backend/tests/test_backfill_report_visuals.py` | 379 | 13 | `backend/scripts/backfill_report_visuals.py` (via `scripts.` namespace import) language repair, visual strip/refresh, rollback | — |
| `backend/tests/test_config_optimization_defaults.py` | 135 | 2 | 34 shipped `app.config.Config` defaults re-read in a clean child interpreter + degrade-safe invariants | subprocess@96 |
| `backend/tests/test_env_drift_pins.py` | 232 | 18 | `backend/scripts/check_env_drift.py` (bare import from scripts/): config-default regexes, .env parsing, pin divergence, secret masking, exit codes | — |
| `backend/tests/test_eval_forecast_quality.py` | 200 | 15 | `backend/scripts/eval_forecast_quality.py` pure scoring + committed `tests/eval` rubric/scenario/baseline fixtures; only user of conftest `fake_llm` | — |
| `backend/tests/test_export_demo_site_data.py` | 897 | 28 | `backend/scripts/export_demo_site_data.py` publishable-run validation, asset copy/rebase; ALSO hash-checks the real `docs/demos/*/meta.json` bundles | fixtures: `healthy_publishable_run` |
| `backend/tests/test_foglamp_containment.py` | 426 | 19 | Foglamp WP1 containment red tests: graph-feedback flags default off, safetyPolicyV1 pin, typed round validity, diagnostic sim policy, golden-ledger isolation | — |
| `backend/tests/test_forecast_diff.py` | 58 | 5 | `backend/scripts/scheduled_rerun.forecast_diff` (pure) | — |
| `backend/tests/test_golden_eval.py` | 277 | 18 | `backend/scripts/golden_eval.py` Brier/log/ECE math, golden fixture integrity, `forecast_ledger.append_golden_result` bridge | — |
| `backend/tests/test_reclaim_report_space.py` | 121 | 6 | `backend/scripts/reclaim_report_space.py` backup whitelist, plotly de-inline, dry-run | — |
| `backend/tests/test_start_script_progress.py` | 301 | 9 | repo `scripts/start.sh` (run via `bash` in a tmp project with fake curl/lsof/python) + `scripts/watch_pipeline_progress.py`; reads real `frontend/vite.config.js` | subprocess@139,140,151,259 |

#### Stage 1 research: DeerFlow bridge (`deerflow_bridge/*`, legacy engine + tools + skills) — 30 files, 748 static test functions, ~17015 lines

| file | lines | tests | module(s) under test / what it pins | harness notes |
|---|---:|---:|---|---|
| `backend/tests/test_actor_dossier_judge.py` | 53 | 6 | `deerflow_bridge/deerflow_research.py` dossier_passes / build_judge_prompt | — |
| `backend/tests/test_actor_intelligence_producer.py` | 1629 | 42 | bridge (path-loaded as module fixture `dr`): actor-intelligence/v1 producer identity/normalizer/finalizer/receipt ledger | fixtures: `dr` |
| `backend/tests/test_audit_fixes_research.py` | 685 | 41 | bridge (path-loaded `deerflow_research_bridge`): RES-1..11 fetch accounting v2, synthesis context floor, as-of clamp, visuals; one test reads real `deer-flow/config.yaml` | skip@682; fixtures: `mod`, `_clean_state` |
| `backend/tests/test_bridge_extensions_config.py` | 197 | 11 | template render of `deerflow_bridge/extensions_config.json` by `pipeline_orchestrator` sync; concurrency of deploys | — |
| `backend/tests/test_bridge_market_tools.py` | 336 | 13 | `deerflow_bridge/market_tools.py` (path-loaded) snapshot capture, negative cache, singleflight | — |
| `backend/tests/test_bridge_overhaul_v3.py` | 1003 | 45 | bridge engine dispatch (`RESEARCH_ENGINE`), exit codes, credential preflight, failover circuit; also `pipeline_orchestrator` | fixtures: `isolated_environ`, `failover` |
| `backend/tests/test_bridge_prediction_markets.py` | 1295 | 74 | bridge pure helpers PM-1/INT-2/RQ-6: market query derivation, relevance gate, Polymarket GET retry (urllib patched) | — |
| `backend/tests/test_bridge_search_and_cache.py` | 332 | 21 | `deerflow_bridge/search_tools.py` provider selection + `cached_fetch.py` TTL/LRU cache | — |
| `backend/tests/test_claude_prompt_cache.py` | 470 | 13 | `deerflow_bridge/patches/models/claude_provider.py` cache_control placement (stubbed anthropic/langchain); byte-identity of patches vs deployed `deer-flow/` tree (git-status aware) | skip@438,441,469; subprocess@396 |
| `backend/tests/test_deerflow_bridge_sync_guard.py` | 690 | 16 | `pipeline_orchestrator._sync_deerflow_bridge_if_stale` on tmp trees: script/skill/module/overlay sync, fail-closed overlays; parses real `setup.sh` | skip@544,603 |
| `backend/tests/test_forecast_visuals_manifest.py` | 941 | 34 | `deerflow_bridge/skills/forecast-visuals/scripts/render.py` manifest merge + data prep | skip@808,913 |
| `backend/tests/test_loop007_research_budget.py` | 954 | 39 | `deerflow_bridge/research_budget.py` SQLite cross-process budgets/leases (real `multiprocessing` spawn), `cached_fetch`, `search_tools`, orchestrator forwarding | subprocess@372 |
| `backend/tests/test_loop010_global_synthesis.py` | 949 | 24 | bridge parallel evidence lanes -> one global synthesis, manifests, research contract; `pipeline_orchestrator` | subprocess@858,908 |
| `backend/tests/test_loop010_research_contracts.py` | 364 | 14 | bridge prompt/skill/summarization contracts (path-loaded) | fixtures: `research_module` |
| `backend/tests/test_multipart_synthesis.py` | 1007 | 81 | bridge SCALE-1 outline/section/stitch helpers (path-loaded) | fixtures: `mod` |
| `backend/tests/test_pipeline_actor_contract.py` | 1383 | 37 | parent-side actor-intelligence reception (`pipeline_orchestrator`) against bridge-produced bundles (path-loaded bridge) | fixtures: `dr` |
| `backend/tests/test_research_checkpoint.py` | 560 | 30 | bridge checkpoint write/load/plan + `--extract-only` routing; orchestrator checkpoint acceptance | subprocess@488 |
| `backend/tests/test_research_evidence_quality.py` | 275 | 21 | bridge evidence-quality analytics R2-RES-1/4/6/10/11 | — |
| `backend/tests/test_research_fanout.py` | 95 | 7 | bridge KIQ extraction + scoped worker prompts | — |
| `backend/tests/test_runtime_skill_sync.py` | 302 | 7 | `deerflow_bridge/runtime_skill_sync.py` manifest/prune/atomic stage/tamper verification; concurrent CLI syncs via subprocess | subprocess@209; fixtures: `skill_sync_module`, `research_bridge_module` |
| `backend/tests/test_sessionb_firecrawl.py` | 286 | 15 | `search_tools`/`cached_fetch` Firecrawl provider routing (fake httpx) | fixtures: `fake_httpx` |
| `backend/tests/test_sessionb_firecrawl_guardrails.py` | 293 | 16 | Firecrawl spend guardrails (search limit, maxAge, per-process ceilings) | fixtures: `fake_httpx`, `_clean_guardrail_state` |
| `backend/tests/test_sessionb_json_extract.py` | 288 | 16 | bridge `extract_json_object` salvage + compact recovery | — |
| `backend/tests/test_sessionb_judge_normalization.py` | 406 | 20 | bridge `_normalize_judge_scorecard`; 2 tests replay real `backend/uploads/pipelines/pipe_bef6879b2e94` attempts (skipif absent) | skip@297,315; fixtures: `_clean_strict_flag` |
| `backend/tests/test_sessionb_research_viz.py` | 392 | 14 | bridge quant enrichment + `deerflow_bridge/skills/forecast-visuals/scripts/render.py`; reads real `pipe_bef6879b2e94/handoff/quantitative.json` (skip if absent) | skip@58; fixtures: `bridge`, `renderer` |
| `backend/tests/test_sessionb_skill_hygiene.py` | 126 | 7 | `deerflow_bridge/skills/*/SKILL.md` size budget (<20,000 B), frontmatter, no dangling refs | — |
| `backend/tests/test_stage1_model_boundaries.py` | 712 | 17 | bridge Stage-1 prompt sanitizer, actor judge, global actor audit | — |
| `backend/tests/test_three_part_and_fetch_retry.py` | 232 | 11 | `report_agent` three-part skeleton (FakeLLMClient) + bridge dead-fetch retry policy | fixtures: `dfr`, `report_folder` |
| `backend/tests/test_wave9_research_quality.py` | 277 | 26 | bridge citation index / references / shingle dedup / chart refs (path-loaded) | fixtures: `mod` |
| `backend/tests/test_wave9_research_speed.py` | 483 | 30 | bridge gap-set convergence, search cache, report patching, degenerate-loop breaker; `claude_provider._calc_backoff_ms` with stubs | — |

#### Stage 1 research: engine v3 (`linear_research.py`, `research_gateway.py`) — 9 files, 366 static test functions, ~8426 lines

| file | lines | tests | module(s) under test / what it pins | harness notes |
|---|---:|---:|---|---|
| `backend/tests/test_research_engine_v3.py` | 1186 | 38 | `deerflow_bridge/linear_research.py` end-to-end with ScriptedModel + fake search/fetch + real bridge; defines shared fixtures reused by the v3_* files | fixtures: `_hermetic_env`, `bridge`, `restore_environ` |
| `backend/tests/test_research_engine_v3_hardening.py` | 336 | 11 | v3 F1/F2/F3/F12/F18/F21/F22 robustness (imports `test_research_engine_v3` as `v3`) | — |
| `backend/tests/test_research_engine_v3_residuals.py` | 334 | 20 | v3 percentage/unit/currency number verification; linear-time scans (perf_counter < 1-2 s) | — |
| `backend/tests/test_research_engine_v3_round2.py` | 938 | 33 | v3 review round 2 E1-E11 (writer truncation, extraction caps, tier labels); `research_progress` | — |
| `backend/tests/test_research_engine_v3_round3_loop.py` | 565 | 26 | v3 KIQ agent loop + notes parser C6/C12/C29-C31 | — |
| `backend/tests/test_research_engine_v3_round3_robust.py` | 713 | 28 | v3 degradation reporting, provider-unavailable resumability, SIGINT/SIGTERM handling | subprocess@473,476 |
| `backend/tests/test_research_engine_v3_round3_synth.py` | 896 | 40 | v3 synthesis/QA/citation normalizer | — |
| `backend/tests/test_research_engine_v3_text.py` | 260 | 14 | v3 weight fixing, number verification, injection filter, citation forms | — |
| `backend/tests/test_research_gateway.py` | 3198 | 156 | `deerflow_bridge/research_gateway.py` error classification, profiles, retries/fallback/quota, tools; isolated subprocess timing probes (largest file, 156 tests) | skip@407,411,1735,1736,2825; subprocess@2600,2601 |

#### Pipeline orchestrator, research API, lifecycle — 17 files, 263 static test functions, ~6246 lines

| file | lines | tests | module(s) under test / what it pins | harness notes |
|---|---:|---:|---|---|
| `backend/tests/test_audit_fixes_infra.py` | 658 | 32 | `llm_client` circuit breaker/fallback/CLI isolation, `telemetry` cost basis, `pipeline_orchestrator` ORCH-2/3/5/7; 60+ Config default pins | fixtures: `_clean_cb_state` |
| `backend/tests/test_dossier_edit_continue.py` | 149 | 5 | `/api/research` dossier edit vs Continue (sealed research refuses edits) | Flask test_client; fixtures: `pipeline`, `client` |
| `backend/tests/test_graph_research_boundary.py` | 51 | 2 | `pipeline_orchestrator` graph chunking strips prompt controls from Stage-1 prose | — |
| `backend/tests/test_live_research_progress.py` | 443 | 20 | `app.services.research_progress` + `/api/research` progress/status/dossier endpoints | Flask test_client |
| `backend/tests/test_orchestrator_outage_halt.py` | 349 | 13 | `llm_client`/`telemetry`/`pipeline_orchestrator` run-level provider-outage breaker (LLM_OUTAGE_HALT_CONSECUTIVE) | fixtures: `clean_outage_state` |
| `backend/tests/test_orchestrator_research_wiring.py` | 1939 | 79 | `pipeline_orchestrator` research-stage helpers: as-of validation, confidence penalty, report health, viz specs, engine selection; fake research subprocess; `create_app` | subprocess@1715,1735; Flask test_client |
| `backend/tests/test_parallel_research_merge.py` | 423 | 29 | `pipeline_orchestrator` PAR-2 track merge helpers (sources, reports, markets) | — |
| `backend/tests/test_research_contract_finalization.py` | 412 | 11 | `pipeline_orchestrator` postprocessed research contract seal | — |
| `backend/tests/test_research_dossier_translation.py` | 151 | 7 | `report_agent`/`report_lint` dossier translation section order + funding-rounds lint | — |
| `backend/tests/test_research_fork_handoff.py` | 163 | 10 | `PipelineManager.resolve_handoff_dir` + fork dossier/progress/chart endpoints | Flask test_client; fixtures: `client` |
| `backend/tests/test_research_round3_parent.py` | 205 | 4 | `pipeline_orchestrator` research lint audit-only on bridge-finalized reports; `report_lint` | — |
| `backend/tests/test_research_spend_flush.py` | 366 | 13 | `pipeline_orchestrator` failed/cancelled research attempt token flush (fake subprocess emitting [usage] lines) | subprocess@17,55; fixtures: `meter_run` |
| `backend/tests/test_resolution_autorun.py` | 123 | 6 | `app.services.resolution_autorun` scheduler + manual endpoint 202/409 (subprocess monkeypatched) | subprocess@60; Flask test_client |
| `backend/tests/test_runtime_lifecycle_isolation.py` | 116 | 3 | `create_app` skips destructive lifecycle hooks under DRF_TEST_PROCESS; `SimulationRunner.reconcile_orphans` port probe | — |
| `backend/tests/test_seed_ensemble.py` | 20 | 2 | `pipeline_orchestrator` seed-ensemble helpers | — |
| `backend/tests/test_status_live_block.py` | 133 | 5 | `/api/research/status/<id>` computed `live` block (heartbeat/eta/budget) | Flask test_client; fixtures: `client` |
| `backend/tests/test_wave9_orchestrator.py` | 545 | 22 | `pipeline_orchestrator` orphan salvage, `ensemble` semantic alignment, track reconcile, telemetry flush; repo `scripts/salvage_orphaned_pipelines.py` | — |

#### Stage 2 knowledge graph (Graphiti/Zep layer, MCP) — 8 files, 188 static test functions, ~4099 lines

| file | lines | tests | module(s) under test / what it pins | harness notes |
|---|---:|---:|---|---|
| `backend/tests/test_audit_fixes_graph.py` | 380 | 19 | `graph_builder` priors alias fold, ingest stats, graph-info integrity, ontology tier gate; `backend/scripts/replay_zep_dead_letters.py` (path-loaded) | — |
| `backend/tests/test_faction_brief.py` | 243 | 15 | `zep_tools` faction brief / tension matrix / insight forge; `oasis_profile_generator` community match | — |
| `backend/tests/test_graph_actor_v1_seed.py` | 768 | 18 | `graph_builder` actor-intelligence/v1 seed + `graphiti_client.client/runtime` attribute round-trip | — |
| `backend/tests/test_graph_cost_containment.py` | 434 | 22 | `graph_builder` cast chunk filter + attempt cap; `graphiti_client.llm_adapter` breaker fail-fast | skip@343 |
| `backend/tests/test_graph_optimizations.py` | 366 | 16 | edge-attr polarity, as-of predicate, Brandes chokepoints, `zep_paging` cap, `graphiti_client.embedder/llm_adapter` (importorskip graphiti_core) | skip@121,172,209,231,253,276… |
| `backend/tests/test_mcp_servers.py` | 494 | 32 | `app.mcp.kg_server` + `app.mcp.sim_server` tool registry/passthrough/timeouts + real stdio subprocess smoke (importorskip mcp) | skip@32; subprocess@461; fixtures: `_isolate_kg_state`, `_isolate_sim_state` |
| `backend/tests/test_wave9_kg.py` | 908 | 38 | `zep_paging` dedup/termination, `graph_pruner` keep-set planning + prune gate, `graphiti_client.runtime` | fixtures: `synthetic_graph` |
| `backend/tests/test_zep_entity_resolver.py` | 506 | 28 | `app.services.zep_entity_resolver` merge planning via fake runtime | — |

#### Ontology, actors, simulation preparation — 22 files, 341 static test functions, ~8661 lines

| file | lines | tests | module(s) under test / what it pins | harness notes |
|---|---:|---:|---|---|
| `backend/tests/test_actor_cast_discipline.py` | 531 | 36 | `app.utils.actors` media/tier gates, bridge `enforce_actor_cast`, ontology prompts, `simulation_manager.select_agent_pool`, audience agents | — |
| `backend/tests/test_actor_context_runtime.py` | 1378 | 27 | `actor_context` packs/gaps/manifests through `simulation_config_generator`, `oasis_profile_generator`, `simulation_runner` boundary (importorskip oasis for one test) | skip@929 |
| `backend/tests/test_actor_dossier_compactor.py` | 143 | 5 | `app.services.actor_dossier_compactor` | — |
| `backend/tests/test_actor_role_prompt.py` | 1360 | 30 | `actor_role_prompt` role contracts, sanitization, manifests; runner tamper rejection | — |
| `backend/tests/test_audit_fixes_ontology.py` | 214 | 22 | `ontology_generator` + `app.utils.actors` ONT-1/3/5/6/9/11, PREP-5 | fixtures: `gen` |
| `backend/tests/test_audit_fixes_prepare.py` | 408 | 21 | `simulation_config_generator` + `oasis_profile_generator` PREP-1..11 | — |
| `backend/tests/test_calendar_event_bucketing.py` | 226 | 10 | `simulation_config_generator` calendar event placement + `app.utils.sim_timeline` | — |
| `backend/tests/test_cast_reconcile.py` | 56 | 4 | `app.utils.actors` cross-track cast reconciliation | — |
| `backend/tests/test_dossier_coverage.py` | 47 | 3 | `app.utils.actors` dossier coverage gate | — |
| `backend/tests/test_oasis_v1_provenance.py` | 486 | 8 | `oasis_profile_generator` v1 persona boundary; `scripts.run_parallel_simulation` system-message attestation | — |
| `backend/tests/test_ontology_actors_optimizations.py` | 251 | 20 | `app.utils.actors` world-state seed parsing, `ontology_generator` sampling, `text_processor`, `file_parser` | — |
| `backend/tests/test_ontology_refinements.py` | 592 | 29 | `app.utils.actors` archetype/tier/salience/valence/follow-graph | — |
| `backend/tests/test_projected_edges.py` | 35 | 3 | `app.utils.actors` relationship-trajectory projection | — |
| `backend/tests/test_prompt_injection_boundaries.py` | 254 | 5 | sanitizers in `ontology_generator`, `simulation_config_generator`, `actor_role_prompt`, `zep_entity_reader` | — |
| `backend/tests/test_sessionb_forecast_provenance.py` | 278 | 10 | `forecast_extractor` source-provenance downgrade + `app.utils.actors` scenario parsing -> world-state seed | — |
| `backend/tests/test_sessionb_scenario_parser.py` | 116 | 6 | `app.utils.actors.forecast_inputs_from_report_markdown` multi-section robustness | — |
| `backend/tests/test_sim_config_incentives.py` | 71 | 5 | `simulation_config_generator` incentives + initial posts | — |
| `backend/tests/test_sim_config_v1_provenance.py` | 717 | 9 | `simulation_config_generator` canonical actor-context/v1 projection; `decision_channel` | — |
| `backend/tests/test_sim_context_persona.py` | 454 | 27 | `simulation_config_generator` world brief + `oasis_profile_generator` persona design + `run_parallel_simulation._inject_world_brief` | — |
| `backend/tests/test_sim_market_priors.py` | 261 | 16 | `simulation_config_generator` market block + `oasis_profile_generator` market hint | — |
| `backend/tests/test_sim_timeline.py` | 481 | 35 | `app.utils.sim_timeline` horizon extraction / calendar unit table / partition properties | — |
| `backend/tests/test_simulation_config_seal.py` | 302 | 10 | `simulation_manager` config seal -> `scripts.run_parallel_simulation` child load | — |

#### Stage 3 simulation runtime, decision channel, WorldState — 16 files, 266 static test functions, ~5630 lines

| file | lines | tests | module(s) under test / what it pins | harness notes |
|---|---:|---:|---|---|
| `backend/tests/test_agent_dynamics.py` | 116 | 9 | `app.services.agent_dynamics` affective state math | — |
| `backend/tests/test_audit_fixes_runloop.py` | 385 | 28 | `run_parallel_simulation` (bare import from backend/scripts) helpers RUN-1..14 + `agent_dynamics` | — |
| `backend/tests/test_audit_fixes_runner.py` | 1003 | 57 | `simulation_runner` stop/monitor/run_summary/log rotation + `oasis_llm` + `run_parallel_simulation` | fixtures: `sim_env` |
| `backend/tests/test_calendar_round_loop.py` | 548 | 7 | real `run_twitter_simulation` round loop on FakeEnv + sqlite (bare import), `decision_channel` | — |
| `backend/tests/test_decision_channel.py` | 148 | 10 | `app.services.decision_channel` orchestration with FakeLLMClient | — |
| `backend/tests/test_sessionb_sim_additivity.py` | 302 | 10 | report-scenario -> actors forecast_inputs -> world-state seed -> sim adjustment end-to-end (`pipeline_orchestrator`, `forecast_extractor`, `simulation_config_generator`) | — |
| `backend/tests/test_sim_meter_persistence.py` | 426 | 19 | `run_parallel_simulation` usage accumulator + `simulation_runner`/`pipeline_orchestrator` exactly-once metering | fixtures: `fresh_usage`, `meter_run`, `orch_env` |
| `backend/tests/test_sim_reaction_phase.py` | 721 | 19 | `run_parallel_simulation` reaction phase, output language; `simulation_config_generator` prompts | — |
| `backend/tests/test_sim_realism_item20.py` | 352 | 24 | `agent_dynamics` sampler/throttle/ratio detector + `run_parallel_simulation` runtime wiring | — |
| `backend/tests/test_sim_resume_reuse.py` | 411 | 22 | `pipeline_orchestrator._completed_sim_reusable` + run-completion gate + `_run` wiring characterization | fixtures: `isolated_runner` |
| `backend/tests/test_simulation_runner_throttle.py` | 61 | 3 | `simulation_runner` run_state.json write throttle | — |
| `backend/tests/test_simulation_trajectory_api.py` | 152 | 10 | `GET /api/simulation/<id>/trajectory` containment + caps (only /api/simulation route tested) | Flask test_client; fixtures: `client` |
| `backend/tests/test_temporal_mode_contract.py` | 565 | 15 | calendar vs hours dispatch across `simulation_runner`, `simulation_config_generator`, `report_agent`, `pipeline_orchestrator` (fake Popen) | subprocess@20,83,103; fixtures: `sim_env`, `no_subprocess` |
| `backend/tests/test_world_delta.py` | 115 | 9 | `app.services.world_delta` digest (no percentages) | — |
| `backend/tests/test_worldstate.py` | 120 | 14 | `app.services.worldstate` outcome model | — |
| `backend/tests/test_worldstate_calendar.py` | 205 | 10 | `worldstate` entropy floor + `decision_channel` calendar trajectory | — |

#### Stage 4 report, forecast, visuals, translation, publication — 46 files, 768 static test functions, ~17770 lines

| file | lines | tests | module(s) under test / what it pins | harness notes |
|---|---:|---:|---|---|
| `backend/tests/test_agent_log_publication_gate.py` | 115 | 4 | `/api/report/<id>/agent-log` draft withholding (`report_agent`) | Flask test_client; fixtures: `client_for` |
| `backend/tests/test_audit_fixes_report.py` | 697 | 28 | `report_agent` RPT-2..14 (section retry, outage abort, spine critique), `zep_tools`, `graphiti_client.cross_encoder/runtime` | — |
| `backend/tests/test_calibration_rigor.py` | 328 | 29 | `forecast_extractor`, `ensemble`, `backtest`, `forecast_ledger` R2-CAL calibration | — |
| `backend/tests/test_chart_serve_inline.py` | 119 | 8 | `app.utils.chart_html` plotly inlining + chart endpoint sandbox | Flask test_client; fixtures: `client` |
| `backend/tests/test_ensemble_backtest.py` | 72 | 6 | `ensemble` aggregation + `backtest` scoring | — |
| `backend/tests/test_exec_brief.py` | 460 | 20 | `app.services.exec_brief` brief/digest/PDF + exec-brief API (pandoc mocked) | Flask test_client; fixtures: `reports_tmp`, `client` |
| `backend/tests/test_final_publish_audit.py` | 553 | 16 | `report_agent` post-citation read-only final audit + publish stabilizer | — |
| `backend/tests/test_forecast_extractor.py` | 1525 | 62 | `forecast_extractor` citation audit, scenario contract, self-critique, ensemble pooling (62 tests) | — |
| `backend/tests/test_forecast_ledger.py` | 156 | 9 | `forecast_ledger` append/read/calibration/market resolution concurrency | — |
| `backend/tests/test_loop006_static_viz_fallbacks.py` | 299 | 10 | `report_visualizer` static matplotlib timeline/network fallbacks | skip@84,125,134,154,231,247… |
| `backend/tests/test_market_influence_boundary.py` | 362 | 18 | `forecast_extractor` market-influence stamping/reconcile + `report_agent` comparison block | — |
| `backend/tests/test_publish_gate.py` | 127 | 7 | `ReportAgent._apply_publish_gate` (static) | — |
| `backend/tests/test_report_bilingual.py` | 1315 | 38 | `report_agent` bilingual translation pipeline + `/api/report` translation/PDF endpoints | Flask test_client; fixtures: `reports_tmp`, `client` |
| `backend/tests/test_report_chart_quality.py` | 569 | 26 | `forecast_extractor` interval derivation + `report_visualizer` density gates | skip@35,263,350; fixtures: `_no_png_export` |
| `backend/tests/test_report_concurrent_sections.py` | 98 | 6 | `ReportAgent._generate_sections_concurrent` with stubbed sections | — |
| `backend/tests/test_report_draft_exposure.py` | 414 | 15 | `/api/report` detail/list/sections/console withholding of unpublishable drafts | skip@398; Flask test_client; fixtures: `reports_tmp`, `client` |
| `backend/tests/test_report_forecast_localization.py` | 355 | 8 | `report_agent` forecast localization + LLM cache bypass + forecast endpoint | Flask test_client; fixtures: `reports_tmp` |
| `backend/tests/test_report_lint_citations.py` | 381 | 23 | `app.services.report_lint` citation-safe lint rules | — |
| `backend/tests/test_report_market_crosscheck.py` | 468 | 24 | `report_agent` market cross-check render/requote, `forecast_extractor` binary normalization, `prediction_markets` | fixtures: `report_folder`, `enabled` |
| `backend/tests/test_report_market_evidence.py` | 129 | 6 | `report_agent` market pack in critique + quantitative grounding | — |
| `backend/tests/test_report_publication_barrier.py` | 309 | 10 | `/api/report` publication barrier (final audit fingerprint) + first-party forecast endpoint | Flask test_client; fixtures: `reports_tmp`, `client` |
| `backend/tests/test_report_repair_and_reflection.py` | 977 | 44 | `report_agent` RQ-2 repair passes + RQ-5 reflection; `report_lint` | — |
| `backend/tests/test_report_section_concurrency_parity.py` | 108 | 3 | REPORT_SECTION_CONCURRENCY default (regex on config.py source) + serial/concurrent parity | — |
| `backend/tests/test_report_sections_partial.py` | 179 | 6 | `/api/report/<id>/sections-partial` + charts route | Flask test_client; fixtures: `reports_tmp`, `client` |
| `backend/tests/test_report_spine_and_turns.py` | 353 | 18 | `report_agent` causal spine block, outline injection, ReAct turn budgets, report shape | — |
| `backend/tests/test_report_visualizer.py` | 937 | 51 | `app.services.report_visualizer` Mermaid/PNG/manifest (many matplotlib/plotly skipifs) | skip@407,425,443,464,531,602…; fixtures: `_no_png_export` |
| `backend/tests/test_report_visualizer_axes.py` | 124 | 4 | `report_visualizer` metric-trajectory axes + shared plotly bundle (module-level skipif no plotly) | module `pytestmark` skipif @23; skip@23; fixtures: `viz`, `trajectory_fig` |
| `backend/tests/test_report_viz_and_pdf.py` | 649 | 26 | `report_agent` visualization placement + `ReportManager` PDF export/content gate (pandoc path faked) | subprocess@351; fixtures: `_no_png_export`, `report_folder` |
| `backend/tests/test_report_viz_manifest_api.py` | 173 | 7 | `/api/report` viz manifest + chart sandbox headers | Flask test_client; fixtures: `client` |
| `backend/tests/test_report_zh_presentation.py` | 140 | 5 | `report_visualizer` Chinese titles + PDF labels; reads real `frontend/src/utils/vizManifest.js` | — |
| `backend/tests/test_sdk_publication_barrier.py` | 114 | 2 | `/api/v1` (API_V1_ENABLED forced) forecasts/calibration obey publication barrier | Flask test_client; fixtures: `client` |
| `backend/tests/test_sessionb_downstream_gates.py` | 288 | 8 | `report_agent._repair_overused_citations` + publish stabilizer convergence | fixtures: `reports_tmp` |
| `backend/tests/test_sessionb_forecast_charts.py` | 357 | 16 | `report_visualizer` forecast-data charts; 3 tests read real `pipe_bef6879b2e94`/`pipe_f23527f7d903` handoffs (skipif absent) | skip@39,290,312,336,349; fixtures: `_no_png_export` |
| `backend/tests/test_sessionb_report_prompts.py` | 290 | 15 | `report_agent` prompt dedup/tool floors/outline; compares templates to `git show HEAD` | skip@79; subprocess@74,78 |
| `backend/tests/test_sessionb_translation_reallm.py` | 330 | 5 | `report_agent` structure-preserving translation vs MiniMax-like drift (scripted) | — |
| `backend/tests/test_sessionb_translation_structure.py` | 344 | 9 | `report_agent` skeleton translator + shared PDF template; `report_lint` | — |
| `backend/tests/test_sessionb_viz_signal.py` | 224 | 11 | `report_visualizer` sunburst demotion + metric trajectories | skip@26,189; fixtures: `_no_png_export` |
| `backend/tests/test_smoke_realrun_residue.py` | 142 | 8 | `report_lint` leakage residue on real-run shapes | — |
| `backend/tests/test_translation_dates.py` | 311 | 14 | `app.services.translation_dates` date tokens; defines GlmLikeTranslator reused by 2 files | — |
| `backend/tests/test_translation_quantities.py` | 195 | 10 | `app.services.translation_quantities` amount magnitude tokens | — |
| `backend/tests/test_translation_robustness.py` | 384 | 13 | `report_agent` residual tolerance, orphaned translation jobs, `/api/research` dossier translation | subprocess@136; Flask test_client; fixtures: `reports_tmp` |
| `backend/tests/test_viz_manifest_provenance.py` | 71 | 4 | `report_visualizer._manifest_provenance` / `_persist_manifest` | — |
| `backend/tests/test_wave9_citations.py` | 715 | 29 | `app.utils.actors` sources index, `report_agent` citation finalize/repair, `forecast_extractor.validate_citation_markers` | fixtures: `reports_tmp` |
| `backend/tests/test_wave9_report_focus.py` | 655 | 42 | `report_lint` edge-dump/leakage rewrites + `report_agent` reflection guards | — |
| `backend/tests/test_wave9_report_integration.py` | 144 | 18 | `report_agent` key-metrics/contested/chronology/KG blocks | — |
| `backend/tests/test_wave9_visualizer.py` | 715 | 27 | `report_visualizer` plotly-first builders, manifest v2, kaleido PNG pair; reads real `pipe_f23527f7d903` (skipif) | skip@179,244,259,328,661,665…; fixtures: `_no_png_export` |

#### Infra utils and API surface — 15 files, 156 static test functions, ~2580 lines

| file | lines | tests | module(s) under test / what it pins | harness notes |
|---|---:|---:|---|---|
| `backend/tests/test_auth_gate_forwarded.py` | 97 | 8 | `app.__init__` auth gate loopback/X-Forwarded-For handling | Flask test_client; fixtures: `client` |
| `backend/tests/test_llm_fallback_model.py` | 205 | 6 | `app.utils.llm_client` fallback model inheritance + dual-outage fail-fast | fixtures: `_clean_llm_module_state` |
| `backend/tests/test_logger.py` | 19 | 1 | `app.utils.logger` closed console stream | — |
| `backend/tests/test_prediction_markets.py` | 873 | 48 | `app.utils.prediction_markets` Polymarket client (mock httpx) + `forecast_extractor` market_anchor | fixtures: `enabled`, `_no_backoff_sleep` |
| `backend/tests/test_resolution_monitor.py` | 338 | 13 | `scripts.resolution_monitor` + `prediction_markets` + `forecast_ledger` (mock httpx) | fixtures: `enabled` |
| `backend/tests/test_settings_endpoint_fallback.py` | 72 | 4 | `app.api.settings` endpoint resolution for test/save | Flask test_client; fixtures: `glm_configured` |
| `backend/tests/test_settings_provider_info.py` | 32 | 3 | `Config.PROVIDER_META` research models vs `deerflow_bridge/config.yaml` | — |
| `backend/tests/test_spa_serving.py` | 99 | 7 | `create_app` SPA static serving (`_frontend_dist_dir`, FRONTEND_DIST) | Flask test_client; fixtures: `dist_dir`, `client` |
| `backend/tests/test_telemetry.py` | 239 | 18 | `app.utils.telemetry` meter/cache/budget/cost/appendix + `llm_client` HTTP client | — |
| `backend/tests/test_telemetry_fallback_attribution.py` | 213 | 8 | `telemetry` single-active-run fallback attribution | fixtures: `_clean_slate` |
| `backend/tests/test_token_budget.py` | 156 | 14 | `app.utils.token_budget` | — |
| `backend/tests/test_utils_atomic.py` | 95 | 8 | `app.utils.atomic` | — |
| `backend/tests/test_utils_dates.py` | 35 | 5 | `app.utils.dates` | — |
| `backend/tests/test_utils_file_parser.py` | 44 | 5 | `app.utils.file_parser.split_text_into_chunks` defaults | — |
| `backend/tests/test_utils_security.py` | 63 | 8 | `app.utils.security` | — |

#### DRF-2 scaffold (`drf2/`) — 4 files, 137 static test functions, ~2304 lines

| file | lines | tests | module(s) under test / what it pins | harness notes |
|---|---:|---:|---|---|
| `backend/tests/test_drf2_driver.py` | 656 | 60 | `drf2/driver/*` state machine, manifest, gates, ensemble math, dry-run pipeline, CLI | — |
| `backend/tests/test_drf2_kg.py` | 446 | 20 | `drf2/engines/kg` MCP tools + real stdio subprocess (importorskip mcp) | skip@27; subprocess@419; fixtures: `_isolate_module_state` |
| `backend/tests/test_drf2_simulation.py` | 501 | 21 | `drf2/engines/simulation` jobs/IPC (FakePopen) + `simulation_runner` | subprocess@3,27,28,37; fixtures: `sim_env` |
| `backend/tests/test_drf2_skills_config.py` | 701 | 36 | `drf2/skills`, `drf2/config/*` validated with real deer-flow-2.0.0 parser via sys.modules shells (many skips); git-aware skill byte-identity vs `deer-flow/skills/public` | skip@218,242,252,447,457,582…; subprocess@155,158,179,182; fixtures: `deerflow_shell`, `deerflow_skill_modules`, `deerflow_config_modules`, `TestConfigYaml.cfg`, `TestExtensionsConfig.ext` |

Group totals check: 12+30+9+17+8+22+16+46+15+4 = 179 files; 164+748+366+263+188+341+266+768+156+137 = 3,397 static test functions.

### Shared harness patterns used across `backend/tests/` (no shared helper module; each file re-implements them)

1. **Bridge modules loaded without DeerFlow's venv.** `deerflow_bridge/*.py` import `deerflow`/`langchain` only inside functions, so the backend venv can import them. Two styles coexist:
   - *bare-name import after `sys.path.insert(0, <repo>/deerflow_bridge)`*: e.g. `test_bridge_prediction_markets.py:13-19` (`import deerflow_research as d`), `test_bridge_search_and_cache.py` (`import search_tools`, `import cached_fetch`), `test_loop007_research_budget.py:16-24` (`research_budget`), `test_research_engine_v3.py:26-38` (`deerflow_research`, `linear_research`, `research_gateway`);
   - *path load under a private module name via `importlib.util.spec_from_file_location`*: `test_audit_fixes_research.py:24-30` (`"deerflow_research_bridge"`, module-scoped fixture `mod`), `test_three_part_and_fetch_retry.py:17-27` (`"dfr_under_test"`), `test_bridge_market_tools.py:12-19` (`"loop009_market_tools"`), `test_forecast_visuals_manifest.py:14-29` (skill renderer `render.py`), `test_claude_prompt_cache.py:29-78` (`"cacheprobe_claude_provider"`). The same source file therefore lives in `sys.modules` under several names with independent module-global state.
2. **Stub third-party SDKs only for the load, then remove them**: `test_claude_prompt_cache.py:29-78` registers minimal `anthropic`, `langchain_anthropic`, `langchain_core.messages` modules, loads `patches/models/claude_provider.py`, and pops every stub it created so later suites (e.g. `test_stage1_model_boundaries.py`) still see `langchain_core` as absent (`:33-40`).
3. **Real DeerFlow 2.0 parser via `sys.modules` shells**: `test_drf2_skills_config.py:209-254` pre-registers empty packages `deerflow`, `deerflow.skills`, `deerflow.config` with `__path__` into `deer-flow-2.0.0/backend/packages/harness/deerflow`, imports only leaf modules, skips on `ImportError`, and pops all `deerflow*` modules at module teardown.
4. **Scripted chat model for the v3 engine**: `test_research_engine_v3.py` defines `_hermetic_env` (autouse; deletes every `RESEARCH_LINEAR_*` var and 10 exact names, `:42-53`), `bridge` (real bridge with `_collect_prediction_markets` and `_render_research_charts` replaced by recorders, `:55-74`), `FakePlog` (`:78-95`), `ScriptedModel` (`bind`/`bind_tools`/`invoke` recorder routed by a responder, `:98-133`), `World` content-routed responder (`:179`), and `run_engine(...)` which calls `linear_research.run(...)` with a `research_gateway.ModelGateway(model, …, sleep=lambda s: None)` and `ResearchTools(… search_fn=fake_search, fetch_fn=page_text …)` (`:389-411`). Seven sibling files reuse it with `import test_research_engine_v3 as v3` and re-export its fixtures by assignment (`test_research_engine_v3_hardening.py:23-29`); `test_translation_quantities.py:18` and `test_research_dossier_translation.py:19` likewise import `GlmLikeTranslator` from `test_translation_dates`. This works because pytest's default `prepend` import mode puts `backend/tests` on `sys.path` (no `__init__.py`).
5. **Flask API tests**: a per-file `client` fixture (14 copies, e.g. `test_report_publication_barrier.py:27-32`) calls `create_app()`, sets `app.config["TESTING"] = True` and returns `app.test_client()`; artifact roots are redirected first (`reports_tmp` fixture, 9 copies, e.g. `test_report_publication_barrier.py:18-24` → `monkeypatch.setattr(ReportManager, "REPORTS_DIR", tmp)`). The Werkzeug test client presents as loopback, so the `/api/*` auth gate passes without a token (the gate itself is tested in `test_auth_gate_forwarded.py`). `/api/v1` is only registered when `Config.API_V1_ENABLED` (`backend/app/__init__.py:210-212`), which `test_sdk_publication_barrier.py:16-25` forces on.
6. **Directory redirection by monkeypatch** (counts of `monkeypatch.setattr(<obj>, "<DIR>", …)` sites): `ReportManager.REPORTS_DIR` 30, `Config.PIPELINE_DATA_DIR` 32, `SimulationRunner.RUN_STATE_DIR` 20, `Config.UPLOAD_FOLDER` 15, `Config.GRAPHITI_DATA_DIR` 7, `Config.DEERFLOW_DIR` 6, `Config.OASIS_SIMULATION_DATA_DIR` 4, plus `FORECAST_LEDGER_DIR`, `SIMULATION_DATA_DIR`, `EMBED_DISK_CACHE_PATH`, `SimulationRunner.SCRIPTS_DIR`, `exporter.OUT_ROOT`.
7. **Heavy objects built with `Class.__new__(Class)` + attribute injection** instead of constructors (no LLM client creation): e.g. `SimulationConfigGenerator.__new__` (`test_audit_fixes_prepare.py:44`), `ReportAgent.__new__` (`test_foglamp_containment.py:350`), `ZepGraphMemoryUpdater.__new__` (`test_foglamp_containment.py:93`).
8. **Subprocess isolation for simulation/research launches**: `SimulationRunner` class registries are reset and `subprocess.Popen` replaced by `_FakeProc` with a no-op monitor thread (`test_temporal_mode_contract.py:66-106`; same convention in `test_audit_fixes_runner.py:31`, `test_drf2_simulation.py:62`); research launches patch `pipeline_orchestrator.subprocess.Popen` with a fake whose `stdout` is a list of lines such as `"[usage] tokens in=12000 out=3400 total=15400"` and stub `_sync_deerflow_bridge_if_stale` (`test_research_spend_flush.py:30-58`, `test_orchestrator_research_wiring.py:1702-1740`).
9. **`mirofish.*` loggers do not propagate** (`backend/app/utils/logger.py:70` sets `propagate = False`), so `caplog` cannot see them; tests attach their own handler (`test_temporal_mode_contract.py:123-131`, `_ListHandler`).
10. **PNG export disabled per file**: six files define an autouse `_no_png_export` that patches `ReportVisualizer._png_export_ok` to `False` to avoid launching Chromium via kaleido (`test_report_visualizer.py:17-22`; also `test_report_chart_quality.py:39`, `test_report_viz_and_pdf.py:29`, `test_sessionb_forecast_charts.py:52`, `test_sessionb_viz_signal.py:31`, `test_wave9_visualizer.py:172`).

### `deerflow_bridge/patches/tests/` (separate suite, DeerFlow venv)

- **`conftest.py` (23 lines)**: `ROOT = parents[3]` = repo root (`:10`); prepends `deer-flow/backend/packages/harness` and `deer-flow/backend` to `sys.path` (`:11-12`); installs a session-wide `MagicMock` as `sys.modules["deerflow.subagents.executor"]` with `SubagentExecutor/SubagentResult/SubagentStatus = MagicMock`, `MAX_CONCURRENT_SUBAGENTS = 3`, `get_background_task_result = MagicMock()` to break DeerFlow's circular eager imports (`:14-23`).
- **`test_client_usage_overlay.py` (137 lines, 5 tests)** — `apply_subagent_overlays.py` client usage overlay (LOOP-017 F1). Loads the overlay script by path (`:22-32`), builds a synthetic `deer-flow` tree whose `client.py` embeds the overlay's own `_CLIENT_USAGE_DECL_ORIGINAL/_BODY_ORIGINAL` blocks plus marker lines that make the context/executor sub-overlays skip (`:36-69`), `exec`s it to get `_account_usage` (`:72-75`). Pins: unpatched same-id 10→110 snapshot counts only 10 (`:78-85`); `apply()` returns `"applied"` then `"already_applied"` and swaps `counted_usage_ids` for `counted_usage_by_id` (`:88-94`); patched accounting records only the positive delta, zero for identical replays, never subtracts on shrink, full amount for id-less snapshots (`:97-120`); a renamed anchor raises `RuntimeError(match="drifted")` (`:123-127`); the deployed `deer-flow/…/client.py` must carry the overlay, skipped when absent (`:130-137`). Needs no DeerFlow imports.
- **`test_model_factory_metadata.py` (42 lines, 1 test)** — `deerflow.models.factory.create_chat_model` must not forward `context_window_tokens` to the provider class (`:18-42`).
- **`test_lead_agent_trim_none.py` (191 lines, 4 tests)** — lead-agent summarization overlay: explicit `trim_tokens_to_summarize=None` reaches the middleware as `None` (`:57-82`); `model_name=None` summary model inherits the active run model (`:85-116`); explicit summary model wins (`:119-150`); `build_middlewares` forwards `model_name` to `_create_summarization_middleware` (`:153-191`).
- **`test_subagent_runtime_contract.py` (369 lines, 5 tests)** — embedded-subagent safety overlay: `real_executor_module` fixture temporarily replaces 9 `deerflow.*` modules with mocks plus a fake `deerflow.skills.storage`, imports the real executor, and restores everything after (`:36-72`); `task_tool` inherits `model_name="minimax"` from `configurable` and passes it as `parent_model`/tool loader `model_name` (`:79-157`); an AIMessage with `additional_kwargs.deerflow_error_fallback` ⇒ `FAILED`, error `"LLM provider fallback inside subagent (reason=auth)"` (`:160-202`); all evidence tools `research_budget_exhausted` ⇒ `FAILED` `"Subagent evidence tools exhausted before any usable result"` (`:205-266`); earlier successful evidence survives a later denial ⇒ `COMPLETED` (`:269-326`); exact `SUBAGENT_OUTCOME: BLOCKED code=no_usable_evidence` ⇒ `FAILED` (`:329-369`).
- **`test_summarization_trim_env.py` (90 lines, 8 tests)** — `RESEARCH_TRIM_TOKENS_TO_SUMMARIZE` (`TRIM_TOKENS_ENV`, defined at `deerflow_bridge/patches/middlewares/summarization_middleware.py:32`) on `DeerFlowSummarizationMiddleware`: unset preserves explicit `None`, configured ints and LangChain's `_DEFAULT_TRIM_TOKEN_LIMIT` (`:36-55`); integer env overrides config (`:58-67`); `none`/`NULL`/` Full ` force `None` (`:70-74`); `abc`, `-5`, `0`, `1.5` ignored (`:77-83`); blank equals unset, `_resolve_trim_tokens_override() == (False, None)` (`:86-90`). It imports the **deployed** copy (harness path first on `sys.path`), so a forgotten re-sync of `patches/middlewares` fails it (`:11-13`).

## Control flow

**Backend suite startup (`cd backend && uv run pytest`)**
1. rootdir/inifile resolve to `backend/` + `backend/pyproject.toml` (`[tool.pytest.ini_options]`, `pyproject.toml:83-86`); `testpaths = ["tests"]`, `-q`.
2. `backend/tests/conftest.py` imports: sets `DRF_TEST_PROCESS=1` (`:19`) and prepends `backend/` to `sys.path` (`:22`).
3. Collection imports all 179 test modules in alphabetical order. Module-level imports run `app.config` (no `.env` because of step 2, `backend/app/config.py:18-19`), many `app.services.*`, bare-imported bridge modules, and the OASIS sim scripts; the first module that imports `run_parallel_simulation` at module scope (`test_audit_fixes_runloop.py:22`) triggers that script's own `load_dotenv(<repo>/.env)` without override (`backend/scripts/run_parallel_simulation.py:125-134`) — see Surprises. Module-level `pytestmark`/`importorskip` (e.g. `test_mcp_servers.py:32`, `test_drf2_kg.py:27`, `test_report_visualizer_axes.py:23`) skip whole files here.
4. First test setup: session fixture `_quarantine_mirofish_log_handlers` rewires `mirofish*` file handlers to a tmp sink (`conftest.py:126-184`).
5. Per test: autouse fixtures in definition order — `_no_prediction_market_network` (`:56`), `_no_ambient_firecrawl_key` (`:70`), `_no_ambient_research_engine_selection` (`:79`), `_isolate_telemetry_active_runs` (`:187`) — then file-local autouse fixtures (e.g. `_hermetic_env`, `_clean_cb_state` at `test_audit_fixes_infra.py:118-122`, `_no_png_export`), then the test body. Monkeypatches are undone at teardown; module-scoped fixtures (e.g. bridge `mod`, `dr`) persist for the file.

**How to run (exact commands, from the code/docs)**
- Whole backend suite: `npm test` from the repo root (`package.json:17` → `cd backend && uv run pytest`), or `cd backend && uv run pytest`, or with the existing venv `cd backend && .venv/bin/python -m pytest` (pytest 8.2.0 present in `backend/.venv`). Note `uv run` syncs `backend/.venv` to `pyproject.toml` (+ `dev` group) and, because `backend/uv.lock` is deleted in this working tree, would re-resolve and write a new lock.
- Subsets: `cd backend && uv run pytest tests/test_drf2_*.py` (`README.md:1714`); any single file/node id works the same way. No `-m <marker>` selection exists (no markers).
- CI: `.github/workflows/ci.yml:35-38` (`uv venv --python 3.12; uv pip install pytest python-dotenv; cd backend && uv run pytest -q`), plus lint (`ci.yml:18-21`) and `compileall` (`ci.yml:40-50`).
- Patch-overlay suite: `deer-flow/backend/.venv/bin/python -m pytest -q deerflow_bridge/patches/tests/<file>.py` after `python3 deerflow_bridge/patches/apply_subagent_overlays.py deer-flow` (`deerflow_bridge/patches/tests/test_subagent_runtime_contract.py:3-7`, `test_lead_agent_trim_none.py:3-5`, `test_summarization_trim_env.py:3-5`). `deer-flow/backend/.venv/bin/pytest` exists on this machine.
- Quality harnesses (outside pytest, spend real LLM credits for the judge): `EVAL_ENABLED=true python backend/scripts/eval_forecast_quality.py run --judge-provider <p> [--update-baseline]` and `python backend/scripts/golden_eval.py score-forecast-file --forecast <…>/forecast.json -o eval_report.json` (docstrings `backend/scripts/eval_forecast_quality.py:19-30`, `backend/scripts/golden_eval.py:19-41`).
- Not collected by the suite: six `backend/scripts/test_*.py` scripts (`test_deerflow_deep_research.py`, `test_graphiti_migration.py`, `test_graphiti_services.py`, `test_pipeline_resume.py`, `test_profile_format.py`, `test_zep_rate_limit.py`) run as `python backend/scripts/<file>` (`__main__` blocks); `test_graphiti_migration.py:7-8` requires a configured LLM provider.

## Data & artifacts

- **Read (committed fixtures)**: `backend/tests/eval/*` (above); `docs/demos/<name>/report.md` via eval scenarios; `docs/demos/*/meta.json` + every file listed in `artifact_sha256`, `report_assets`, `dossier_assets`, `*_languages` (`test_export_demo_site_data.py:660-672`, `:872-897`); `deerflow_bridge/skills/**` (`test_sessionb_skill_hygiene.py:25-31`, `test_drf2_skills_config.py`); `deerflow_bridge/config.yaml`, `deerflow_bridge/extensions_config.json`; `drf2/config/*`, `drf2/skills/**`; `setup.sh` (`test_deerflow_bridge_sync_guard.py:213-235`, `test_drf2_skills_config.py:634-640`); `scripts/start.sh`, `scripts/watch_pipeline_progress.py`, `frontend/vite.config.js` (`test_start_script_progress.py:11-18`, `:227-230`); `frontend/src/utils/vizManifest.js` (`test_report_zh_presentation.py:49-55`); `backend/app/config.py` source text (`test_foglamp_containment.py:40-46`, `test_report_section_concurrency_parity.py:27-45`).
- **Read (developer-local, gitignored; tests skip when absent)**: `backend/uploads/pipelines/pipe_bef6879b2e94/handoff/{quantitative.json,research_attempts/}` (`test_sessionb_judge_normalization.py:41-45`, `test_sessionb_research_viz.py:32-35`, `test_sessionb_forecast_charts.py:42-44`), `backend/uploads/pipelines/pipe_f23527f7d903/handoff/` (`test_sessionb_forecast_charts.py:46-48`, `test_wave9_visualizer.py:678-679`), `deer-flow/config.yaml` (`test_audit_fixes_research.py:21`, `:682`), deployed `deer-flow/backend/packages/harness/deerflow/{models,agents/middlewares}` (`test_claude_prompt_cache.py:419-470`), `deer-flow/skills/public` (`test_drf2_skills_config.py:642-701`), `deer-flow-2.0.0/backend/packages/harness/deerflow` (`test_drf2_skills_config.py:216-218`, `test_deerflow_bridge_sync_guard.py:544-553`). All exist on this machine (checked), all are gitignored (`.gitignore:71,84,93`), so CI's fresh checkout skips these.
- **Written**: only pytest `tmp_path`/`tmp_path_factory` dirs (reports, pipelines, run_state, ledgers, SQLite budget DBs `budget.sqlite3`, skill bundles, fake `deer-flow` trees, the log sink `mirofish-logs/mirofish.log`). Side effects outside tmp: `backend/logs/` is created by `setup_logger` at import (`backend/app/utils/logger.py:63`) and import-time log records emitted before the session fixture runs still go there; `.pytest_cache` and `__pycache__` under the run root.
- **In-memory structures that tests reset**: telemetry active-run registry (`conftest.py:196-205`), `llm_client._CB_STATE` circuit breaker (`test_audit_fixes_infra.py:118-122`), bridge `_fetched_sources` (`test_audit_fixes_research.py:33-37`), `SimulationRunner` class registries (`test_temporal_mode_contract.py:66-79`), `LLMMeter.reset(run_id)` (`test_research_spend_flush.py:60-73`).

## Config / env knobs

| name | default / value in tests | effect | anchor |
|---|---|---|---|
| `DRF_TEST_PROCESS` | forced `"1"` at conftest import | disables `.env` load in `app.config`; disables destructive lifecycle hooks in `create_app` | `backend/tests/conftest.py:19`; `backend/app/config.py:18`; `backend/app/__init__.py:122-125` |
| `PREDICTION_MARKETS_ENABLED` | forced `"false"` (+ `Config` attr False) per test | Polymarket client returns empty without HTTP | `conftest.py:62-65` |
| `FIRECRAWL_API_KEY` | deleted per test | search/fetch fall back to keyless providers | `conftest.py:76` |
| `RESEARCH_ENGINE`, `RESEARCH_LINEAR_MODE` | deleted per test | bridge dispatch only via explicit `monkeypatch.setenv` | `conftest.py:90-91` |
| `FAKE_*`, `START_MONITOR_INTERVAL_SECONDS=0.05`, `PATH` (fake curl/lsof) | set in child env | drive `scripts/start.sh` deterministically | `test_start_script_progress.py:122-131` |
| `FOGLAMP_FAKE_NOW` | removed from child env | deterministic baseline-CLI timestamps | `test_architecture_baseline_cli.py:15` |
| `PYTHONUNBUFFERED=1`, `PYTHONPATH=backend` | child env for MCP stdio smoke | `python -m app.mcp.*` imports | `test_mcp_servers.py:461-468`; `test_drf2_kg.py:419-426` |
| `RESEARCH_TRIM_TOKENS_TO_SUMMARIZE` | toggled by patches tests | DeerFlow summarization trim override | `deerflow_bridge/patches/tests/test_summarization_trim_env.py:36-90` |
| `EVAL_ENABLED`, `GOLDEN_EVAL_LEDGER` | not set by tests | gate the live judge / ledger writes of the eval scripts | `backend/scripts/eval_forecast_quality.py:13`, `backend/scripts/golden_eval.py:358-361` |
| `API_V1_ENABLED` (Config attr) | forced True in one fixture | registers `/api/v1` | `test_sdk_publication_barrier.py:20`; `backend/app/__init__.py:210` |
| `FRONTEND_DIST` | set to tmp dist | SPA serving root | `test_spa_serving.py` (fixture `dist_dir` `:21`); `backend/app/__init__.py:23-29` |

Beyond these harness knobs, ~200 distinct product env vars are toggled per test with `monkeypatch.setenv/delenv` (e.g. `RESEARCH_BUDGET_*` in `test_loop007_research_budget.py:29-45`, `SYNTHESIS_*` in `test_multipart_synthesis.py`, `SIM_*` in the simulation files, `LLM_FALLBACK_*` in `test_llm_fallback_model.py` and `test_audit_fixes_infra.py`); they are always restored by `monkeypatch`.

## External calls

- **LLM / provider APIs**: none intended. LLMs are `FakeLLMClient` (`conftest.py:25-53`), `ScriptedModel` (`test_research_engine_v3.py:98-133`), per-file fakes (`FakeModel`, `FakeOpenAIModel`, `ClaudeChatModel` stand-ins in `test_research_gateway.py`), or raising stubs (`FailingLLM`, `test_foglamp_containment.py:49-57`).
- **HTTP**: `httpx` is mocked in `test_prediction_markets.py`, `test_report_market_crosscheck.py`, `test_resolution_monitor.py`, `test_sessionb_firecrawl*.py`; `urllib.request` is patched in `test_bridge_prediction_markets.py` (Polymarket GET retry tests `:210-306`); `socket.create_connection` patched in `test_runtime_lifecycle_isolation.py:99-103`. `test_research_gateway.py:1735-1736` and `:2825` `importorskip("openai")`/`("httpx")` to build real client objects (not to send requests — not verified call by call).
- **Subprocesses actually spawned** (real child processes, offline):
  - `sys.executable` child for Config defaults (`test_config_optimization_defaults.py:96-99`);
  - `sys.executable backend/scripts/architecture_baseline.py capture|verify|compare` (`test_architecture_baseline_cli.py:14-22`);
  - `sys.executable -m app.mcp.kg_server|sim_server` and `-m drf2.engines.kg.server` stdio JSON-RPC smoke, timeout 120 s (`test_mcp_servers.py:461-468`, `test_drf2_kg.py:419-426`);
  - `bash scripts/start.sh` copies with fake `curl`/`lsof`/`python`, timeout 6 s (`test_start_script_progress.py:134-147`);
  - `git -C <repo> show HEAD:backend/app/services/report_agent.py` (`test_sessionb_report_prompts.py:71-79`), `git status --porcelain -- deerflow_bridge/patches` (`test_claude_prompt_cache.py:396-402`), `git ls-files -z`/`git status --porcelain -z -- deerflow_bridge/skills` (`test_drf2_skills_config.py:155-182`);
  - isolated `sys.executable -c "import test_research_gateway as T; …"` timing probes, timeout 60 s (`test_research_gateway.py:2593-2603`);
  - `multiprocessing.get_context("spawn").Process` workers racing on one SQLite budget DB (`test_loop007_research_budget.py:99-115` and following);
  - concurrent CLI skill syncs (`test_runtime_skill_sync.py:194-216`).
- **Databases**: SQLite (stdlib) for research budgets/leases and the fake OASIS trace DB (`test_calendar_round_loop.py`, `test_sim_realism_item20.py`); no FalkorDB/Graphiti backend is started (graph tests use fake runtimes/clients).

## Cross-module edges

**Who calls into this slice**: pytest only — `package.json:17`, `.github/workflows/ci.yml:38`, `README.md:1593`, `README.md:1714`. Outside pytest, `backend/scripts/eval_forecast_quality.py:43-47` and `backend/scripts/golden_eval.py:60-61` read `backend/tests/eval/*` at run time. `init.sh:11-21` is an unrelated compile-only smoke check (it does not run tests).

**What the slice reaches into**: 75 `backend/app` modules (most via direct import), `backend/scripts/{run_parallel_simulation,run_twitter_simulation,run_reddit_simulation,action_logger,architecture_baseline,backfill_report_visuals,check_env_drift,eval_forecast_quality,export_demo_site_data,golden_eval,preflight,reclaim_report_space,replay_zep_dead_letters,resolution_monitor,scheduled_rerun}.py`, repo `scripts/{start.sh,watch_pipeline_progress.py,salvage_orphaned_pipelines.py}`, every `deerflow_bridge/*.py` module (reference counts across test files: `deerflow_research` 33, `linear_research` 6, `research_budget` 7, `search_tools` 7, `cached_fetch` 6, `research_gateway` 5, `market_tools` 4, `runtime_skill_sync` 2), `deerflow_bridge/skills/**`, `deerflow_bridge/patches/{models/claude_provider.py, middlewares/summarization_middleware.py, apply_*_overlays.py}`, `drf2/driver/*`, `drf2/engines/{kg,simulation}`, `drf2/config`, `drf2/skills`.

**Coverage gaps (static reference analysis; "0" = no test file imports or names the module)**
- `backend/app/services/simulation_ipc.py` (732 lines) — 0 references (only reached indirectly through mocked `SimulationRunner`/MCP paths). Consumers: `backend/app/services/simulation_runner.py:25`, `backend/app/mcp/sim_server.py:94`, `backend/app/services/report_agent.py:1717`.
- `backend/app/api/graph.py` (725 lines, 14 routes) — no test hits `/api/graph/*` and none imports `graph_bp`.
- `backend/app/api/simulation.py` (2,871 lines, ~32 routes) — only `GET /api/simulation/<id>/trajectory` is exercised (`test_simulation_trajectory_api.py`).
- `backend/app/api/sdk.py` (356 lines) — exercised only through the publication-barrier pair in `test_sdk_publication_barrier.py:89-114`.
- `backend/app/models/project.py` (309 lines) — only monkeypatched (`ProjectManager.get_project` at `test_orchestrator_research_wiring.py:969`), never tested directly.
- `backend/app/services/requirement_spec.py` (105), `backend/app/utils/zep_rate_limit.py` (52; covered only by the non-collected `backend/scripts/test_zep_rate_limit.py`), `backend/app/services/graphiti_client/{falkor_driver.py (99), compat.py (56), ontology.py (47)}` — 0 references.
- Thinly covered large modules (1–2 test files each): `zep_tools.py` 2,854 lines (2 files), `actor_context.py` 1,601 (2), `zep_graph_memory_updater.py` 719 (2), `oasis_llm.py` 616 (1), `graph_pruner.py` 428 (1), `exec_brief.py` 927 (1), `app.mcp.sim_server` 312 (1).
- `deerflow_bridge/patches/middlewares/{loop_detection_middleware,title_middleware,tool_error_handling_middleware}.py` and `patches/models/credential_loader.py` — 0 references in either suite (only file-sync/byte-identity checks).
- `backend/scripts/{batch_runs (841 lines), model_comparison (524), disk_usage_report, forecast_tools, process_diagnostics}.py` — 0 references.
- Most heavily referenced: `report_agent` and `pipeline_orchestrator` (dozens of files each), `app.utils.actors`, `forecast_extractor`, `report_visualizer`.

## Invariants, gates, validation

- **Offline boundary**: no real LLM/network calls; enforced socially (docstrings) plus four autouse fixtures (`conftest.py:56-91`); there is no network-blocking plugin (e.g. no socket guard), so an unmocked HTTP call would really go out.
- **Process-lifecycle boundary**: pytest must never run orphan reconciliation or kill a live localhost simulator (`conftest.py:13-19`, `backend/app/__init__.py:118-125`, pinned by `test_runtime_lifecycle_isolation.py:19-81`; port-owned skip at `:92-114`).
- **Config defaults are a contract**: 34 defaults in a clean child (`test_config_optimization_defaults.py:107-110`) plus 57 + 9 in-process pins (`test_audit_fixes_infra.py:93-102`, `test_wave9_orchestrator.py:529-543`) plus Foglamp WP1 safety defaults by source regex (`test_foglamp_containment.py:61-74`, `:290-300`).
- **Architecture backlog as executable spec**: 11 strict xfails (`test_architecture_characterization.py`), each turning red on XPASS, so landing a WP module without removing its mark fails the suite.
- **Deployment parity**: bridge sources vs deployed `deer-flow/` copies must be byte-identical unless git-dirty (`test_claude_prompt_cache.py:415-470`, `test_drf2_skills_config.py:642-701`); `setup.sh` must deploy every drift-guarded module (`test_deerflow_bridge_sync_guard.py:224-235`); overlays fail closed on drift (`test_deerflow_bridge_sync_guard.py:322-376`, `deerflow_bridge/patches/tests/test_client_usage_overlay.py:123-127`).
- **Publication barrier**: report bodies/sections/agent-logs/SDK forecasts are withheld unless `final_audit.json` hard-passes for the exact markdown SHA-256 (`test_report_publication_barrier.py:54-67`, `test_report_draft_exposure.py`, `test_agent_log_publication_gate.py`, `test_sdk_publication_barrier.py:89-114`).
- **Eval fixture integrity**: golden set ≥25 unique ids, boolean outcomes, `as_of_date <= resolution_date`, both outcomes present (`test_golden_eval.py:140-155`); eval scenarios resolve to existing demo reports and baselines cover every scenario × dimension (`test_eval_forecast_quality.py:184-199`); malformed judge output can only fail a gate (`test_eval_forecast_quality.py:88-92`).
- **Skill size budget**: `deerflow_bridge/skills/actor-ontology-research/SKILL.md` < 20,000 bytes with six load-bearing headings (`test_sessionb_skill_hygiene.py:64-72`).
- **Gating catalogue**: optional-dependency skips — `matplotlib`/`plotly`/`kaleido` via `report_visualizer.{MATPLOTLIB,PLOTLY,KALEIDO}_AVAILABLE` (≈46 skip/skipif sites plus reusable `needs_plotly` markers across 8 report/visual files), `importorskip("mcp")` (`test_mcp_servers.py:32`, `test_drf2_kg.py:27`), `importorskip("graphiti_core")` (8 sites in `test_graph_optimizations.py`, `test_graph_cost_containment.py:343`), `importorskip("oasis")` (`test_actor_context_runtime.py:929`), `importorskip("openai"/"httpx")` (`test_research_gateway.py:1735-1736,2825`); environment skips for absent gitignored trees/artifacts (Data & artifacts) and for missing `git` (`test_sessionb_report_prompts.py:79`, `test_claude_prompt_cache.py:441`, `test_drf2_skills_config.py:648`); one policy-dependent skip (`test_report_draft_exposure.py:398`). There are **no slow/live markers**: "slow" work (Chromium/kaleido export, multiprocessing, stdio servers, bash) is either disabled by fixture or runs unconditionally.

## Failure modes & recovery

- **Developer `.env` leakage**: blocked for `Config` by `DRF_TEST_PROCESS`, but re-opened for raw `os.environ` reads by the sim scripts' own `load_dotenv` (Surprises #1). In-process default pins then silently skip any name present in the environment (`test_audit_fixes_infra.py:98-99`, `test_wave9_orchestrator.py:542-543`), weakening — not failing — the check on a dev machine.
- **Machine-state coupling**: deployment-parity tests fail when `deer-flow/` is stale (by design: "re-run ./setup.sh … or the orchestrator drift guard", `test_claude_prompt_cache.py:455-462`); demo-bundle tests fail when `docs/demos` files are missing (currently the case in this working tree, Surprises #2). Recovery = re-sync/restore, not test edits.
- **Optional deps missing** ⇒ skips (never failures) for plotting/MCP/graphiti/oasis; `lsof` missing ⇒ `assert real_lsof` failure, not a skip (`test_start_script_progress.py:99-100`).
- **Timing-sensitive assertions** can flake on slow hosts: `< 0.05 s` per regex probe (`test_research_gateway.py:2610-2614`), `< 1.0 s` / `< 2.0 s` linear-scan bounds (`test_research_engine_v3_residuals.py:101-105`, `:256-263`, `:304-309`; `test_research_engine_v3_round3_loop.py:111-113`), `< 2 s` (`test_mcp_servers.py:382-386`, `test_report_bilingual.py:1090-1098`), `< 5.0 s` (`test_bridge_overhaul_v3.py:815-817`), multiprocess lease ordering with `time.sleep(0.2)` (`test_loop007_research_budget.py:64-84`). Subprocess timeouts: 6 s (start.sh), 15–30 s (git), 60 s (gateway probes), 120 s (MCP stdio).
- **Logging hiccups never fail the session** (every quarantine step guarded, `conftest.py:131-183`); telemetry registry clearing tolerates an unimportable module (`conftest.py:196-206`).
- **Known historical issue** (doc claim, not verified in code): a full-suite teardown hang with live `kevent`/`os.read` threads (`DRF_ARCHITECTURE.md:1770-1772`); neither conftest contains any teardown/thread-reaping hook.

## Surprises

1. **(suspected isolation gap) Sim scripts reload the developer `.env` into the test process.** `run_parallel_simulation.py:125-134` (and `run_twitter_simulation.py:40-47`, `run_reddit_simulation.py:40-47`) call `load_dotenv(<repo>/.env)` at import; tests import them at module scope during collection (first: `test_audit_fixes_runloop.py:22`). `Config` attributes are already frozen to code defaults by then, but every `os.environ.get(...)` read at call time (bridge modules, `_env_int` helpers, `llm_client` fallbacks) sees `.env` values, and real credentials enter `os.environ`. `conftest.py:79-91` patches only `RESEARCH_ENGINE`/`RESEARCH_LINEAR_MODE` (plus `FIRECRAWL_API_KEY` at `:76`). The script also prints "已加载环境配置" during collection.
2. **(suspected current failures) Demo-bundle hash tests vs the dirty working tree.** `git status` shows 38 deleted files under `docs/demos/` (and `backend/uv.lock` deleted). A read-only re-check of `docs/demos/*/meta.json` `artifact_sha256` found missing files for datacenter-2030 (3), ev-2035 (13), grid-storage-2040 (10), quantum-2040 (5). `test_published_ev_markdown_assets_resolve_and_match_manifest_hashes` (`test_export_demo_site_data.py:660`) and `test_every_published_demo_bundle_matches_its_manifest` (`:872`) assert `artifact.is_file()` for each, so they should fail on this checkout until the files are restored (not run).
3. **CI comments contradict what CI runs.** `ci.yml:32-34` says only light deps for "telemetry/security/atomic/dates golden tests", but `:38` runs the full suite with `uv run`, which syncs the whole `backend/pyproject.toml` environment (sim/graph stack), making the root-level `uv venv`/`uv pip install pytest python-dotenv` (`:36-37`) effectively unused (suspected, based on uv's project-env semantics). The suite also imports `oasis`/`camel` via `run_parallel_simulation` (`test_audit_fixes_runloop.py:1-4`), so a light install could not run it.
4. **Lint config drift**: CI ignores `F401,F841,F541` and selects only `F,E9` over `backend/app backend/scripts deerflow_bridge` (`ci.yml:19`), while `pyproject.toml:95-97` selects `F,E9,B,C4` and ignores `F401,F841,B008`; `backend/tests/` is neither linted nor byte-compiled by CI (`ci.yml:19`, `:50`).
5. **Undeclared test dependencies**: `yaml` (PyYAML) is imported by 4 test files (`test_sessionb_skill_hygiene.py`, `test_drf2_skills_config.py`, `test_audit_fixes_research.py`, `test_loop010_research_contracts.py`) but is not in `backend/pyproject.toml` or `backend/requirements.txt` (arrives transitively); `mcp` is required by `test_mcp_servers.py`/`test_drf2_kg.py` but declared only in `backend/requirements.txt:46`, not `pyproject.toml`, so a `uv sync` removes it and those files silently skip. `pytest-asyncio` is declared (`pyproject.toml:57,75`) but unused: no `async def test_`, no asyncio marker; coroutines are driven with `asyncio.run`.
6. **Dead / duplicated harness**: `tmp_run_dir` (`conftest.py:102-107`) has no consumer; `fake_llm` has one (`test_eval_forecast_quality.py:159`) while 14 files import `FakeLLMClient` directly; fixtures are copy-pasted instead of shared — `client` ×14, `reports_tmp` ×9, `_no_png_export` ×6, `sim_env`/`enabled`/`report_folder`/`mod` ×3 each.
7. **`from tests.conftest import FakeLLMClient`** (14 files) imports conftest a second time as module `tests.conftest` (namespace package via `conftest.py:22`), re-executing its top level; `FakeLLMClient` from the two module objects are different classes (harmless today, breaks `isinstance` if ever used).
8. **Same source, many module objects**: `deerflow_research.py` is imported as `deerflow_research`, `deerflow_research_bridge`, `dfr_under_test`, and via fixtures `dr`/`mod`; `run_parallel_simulation` as both `run_parallel_simulation` and `scripts.run_parallel_simulation` (`test_oasis_v1_provenance.py`, `test_simulation_config_seal.py`). Each copy has independent module globals (caches, breakers), so state resets in one do not affect the other.
9. **Doc-vs-code drift**:
   - `conftest.py:72-73` and `test_config_optimization_defaults.py:7-12` still justify themselves with "`app.config` loads `.env` with `override=True`", which `backend/app/config.py:14-19` no longer does under `DRF_TEST_PROCESS` (the subprocess design is now belt-and-braces).
   - `test_audit_fixes_research.py:3-5` says "there is no other pytest coverage for the bridge"; 33 test files reference `deerflow_research`.
   - `DRF_ARCHITECTURE.md:1724-1726` says "1,500+ tests"; the latest log records 4,406 passed (`agent-progress.txt:308`).
   - `golden_questions.json:3` says questions are from "2024-2026"; all resolution dates are 2024-02-02…2025-02-09.
   - `test_drf2_skills_config.py:213` comment says the shell fixture must not pollute "the other 584 tests" — a stale count.
10. **Answer-bearing, YES-skewed golden set**: 24 of 30 outcomes are YES (`golden_questions.json`), so an always-high forecaster scores well on Brier; the suite itself characterizes the fixture as leaking outcomes (`test_architecture_characterization.py:297-312`, `test_foglamp_containment.py:415-426`), with the sealed replacement deferred to WP14.
11. **Tests that pass trivially on a clean checkout**: `test_placeholder_sets_unchanged_vs_head` compares the working-tree prompt templates with `git show HEAD` (`test_sessionb_report_prompts.py:71-95`), so it can only fail on uncommitted edits and always passes right after a commit.
12. **Machine-specific assumptions**: `test_start_script_progress.py:99-100` asserts `lsof` exists (fails, not skips, without it); `test_actor_context_runtime.py:929` and the real-artifact tests depend on local installs/uploads; several "offline" tests launch real child processes (see External calls), so the suite is not purely in-process.
13. **Out-of-suite "tests"**: six `backend/scripts/test_*.py` files look like tests but are outside `testpaths`, so `uv run pytest` never collects them; `backend/scripts/test_zep_rate_limit.py` is the only check of `app/utils/zep_rate_limit.py`.
14. **Log quarantine is partial**: the session fixture runs after collection, so records logged at import time land in the real `backend/logs/mirofish.log`; loggers outside the `mirofish` hierarchy are not redirected (`conftest.py:159-161`).
