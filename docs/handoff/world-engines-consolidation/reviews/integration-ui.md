# world-v1 review: Integration with the claude world model and the UI

- **Reviewed:** `codex/reflexive-world-simulation` at a6fbbc0 (read-only, 2026-10-18 +08), one of four parallel reviews.
- **Line numbers** refer to a6fbbc0 in the Codex worktree unless marked otherwise; the merged tree differs.
- **What was done with each finding** is recorded in [../handoff.md](../handoff.md) §5–§9.

---

I made no changes to the repo; everything below comes from scratch copies. The merge is mostly clean, but one Codex defect has to be fixed before or during the merge: with default settings, every completed report (ours and world-v1, old and new) returns 409 from the report API.

How I checked: a trial three-way merge (`git merge-file --diff3`) of base 8852ce1, ours dcff768 and Codex a6fbbc0; a syntax parse of the merged Python files; and a dedented diff of the block Codex re-indented. I also ran Codex's `contracts.canonical_json` on a meta.json shaped like a real one with telemetry. Line numbers below are from a6fbbc0 unless marked dcff768.

## 1. Per-file merge plan

| File | Text conflict | How to combine |
|---|---|---|
| `pipeline_orchestrator.py` | No | Codex wraps the OASIS PREPARE+RUN block under `if engine == "world-v1": _run_world_stages(...) else:`. After removing the indent it is byte-identical to base. Our three edits sit outside it, so they keep working: `_report_llm_preflight` (dcff768:8015, called at :13909) and the `world_model` summary in `_log_decision_channel_outcome` (dcff768:11365). The merged REPORT stage calls our `_report_llm_preflight()` for both engines, and Codex's inline 64-token probe goes away. Keep Codex's world-only `ReportAgent` construction (14366). Its world-only ensemble re-raise (14398) should change; see M4. |
| `report_agent.py` | No | The split already comes out right. `_build_signal_pack` returns "" for world-v1 runs, so our `_world_evolution_block` (dcff768:3736) is OASIS-only. The chart-input collection returns before our `world_state.json` read. Codex's world pathway appendix is only added for world-v1 reports. Our resilient binary extractor receives Codex's evidence-only input. Needs the B1 fix. |
| `report_visualizer.py` | No | Keep both. In Codex's world branch, also drop our `world_state` chart input next to its `pop("world_state_trajectory")`. |
| `simulation_runner.py` | No | Ours (append-mode log, `world_update` monitor events, rerun file list, `run_summary.world_model`) only runs on OASIS paths; Codex's engine checks sit at the top of each method. Fix M2. |
| `api/simulation.py` | No | Our `/world-state`, `/feed-rounds` and `round=` routes coexist with Codex's `/world`. Different file names on disk, so no collision. |
| `config.py` | No | Keep `DEFAULT_SIMULATION_ENGINE='oasis-legacy'`. |
| `frontend/src/api/simulation.js` | Yes, 2 hunks | Both sides added a 5th parameter. Use `getSimulationPosts/Comments(id, platform, limit, offset, round = null, options = {})` returning `service.get(url, {...options, params})`. Add `options` to `getFeedRounds` and `getWorldState`. Keep Codex's `getSimulation(id, options)` and `getWorldSimulation`. |
| `SimulationView.vue` | Yes, 6 hunks | See below. |
| `feature_list.json`, `agent-progress.txt` | Yes (both appended) | Keep both entries; world-v1 stays `passes:false`. |
| `README*.md` | No | Rename Codex's "Reflexive world simulation (explicit opt-in)" to "World engine v1 (experimental, opt-in)", and say the default OASIS engine is the reflexive world-state model. |

**`SimulationView.vue`:**
- Take Codex's structure: route by saved engine, `WorldSimulationView` for world-v1, request gate, immediate `flush:'sync'` watcher, no `onMounted`.
- Inside the `engine === LEGACY_ENGINE` branch keep `WorldStatePanel` and our period header and empty state.
- In `loadAll`, once the engine resolves to OASIS, fetch six calls together:
  - profiles;
  - posts with `(feedReq.limit, 0, feedReq.round, options)`;
  - comments with `(feedReq.commentLimit, 0, feedReq.round, options)`;
  - stats and run status;
  - `getFeedRounds(simId, plat, options)`.
- Replace both stale-response guards with `request.isCurrent()`. Read all six results, run Codex's engine-identity check, then our feed-rounds handling.
- The simulation-change watcher resets Codex's state plus `selectedRound`, `feedRounds` and `feedPeriodLabel`.

**Codex-only files merge as-is, except:**
- **`frontend/tests/world-simulation.test.mjs` will break.** Its test harness has no entries for `./WorldStatePanel.vue`, `../../utils/feedRounds`, `getFeedRounds` or `getWorldState`, and its posts stub (line 417) expects options as the 5th argument. Update it to six arguments and add the stubs.
- **`ResearchView.vue`:** it lists "World simulation" first and labels our engine "Social simulation (legacy)". Reorder and relabel: "Reflexive world · OASIS (default)", then world-v1 as experimental.

## 2. Defects in the Codex integration code

**BLOCKER**
- **B1 — every completed report returns 409.**
  - *Cause:* `report_agent.py:98` (`read_report_world`) reads `meta.json` with Codex's strict world reader (`read_json` → `canonical_json`), which rejects any float. Report telemetry is on by default (`REPORT_TELEMETRY` and `LLM_TELEMETRY_ENABLED` are both True), so the final save (13486, written at 13522) puts `duration_s`, `est_cost_usd` and `latency_ms` floats into `meta.json`. My probe confirmed `canonical_json` raises `invalid_json` on that shape.
  - *Effect:* `api/report.py:26-40` adds a `before_request` hook that runs this check on all 22 non-DELETE `/<report_id>/…` routes. Each one returns 409 "World result integrity verification failed". That covers report body, sections, progress, charts, download, PDF and translations, for OASIS and world-v1 reports, historical ones included.
  - *Same root cause also breaks:* the sealed-forecast loader (13839), used by the SDK `/api/v1/forecast/<id>` and the exec brief; the PDF fingerprint (14648); translation regeneration and audits on existing reports (8064, 8286, 9090, 9197); and chart building on existing reports (`report_visualizer.py:5001`), so `backfill_report_visuals.py` fails too. Generation itself survives only because the floats are written last.
  - *Why Codex's tests missed it:* `test_world_report_consumers.py:62-68` turns `REPORT_TELEMETRY` off, and that module is skipped in normal pytest anyway.
  - *Fix:*
    - When no metadata is passed, read `meta.json` with the normal lenient reader (`ReportManager._read_report_meta` / `json.load`).
    - Return early for reports with no world-v1 engine, no `world_result_ref` and no `world_result*.json` files, after a lenient check of the simulation's engine pin.
    - Read the engine pin leniently in `load_simulation_world` too (line 59); keep the strict reader for world files only.
    - Add a plain-pytest test: an OASIS report with telemetry floats gets 200 from the report API, the SDK forecast and the PDF path.

**MAJOR**
- **M1 — full re-verification on every report request.** The `before_request` hook re-verifies the world on every request. For world reports that means reading and re-rendering the whole SQLite result (`results.py:121-136`), then re-hashing the result files and every chart including the plotly bundle (`report_agent.py:89-114`). The chart route repeats it (`api/report.py:1381`). A page with N charts costs O(N²) hashing, and every `/progress` poll pays it too. Fix: cache the result keyed on file inode/size/mtime, skip status/progress/log routes, and hash only the requested chart on chart fetches.
- **M2 — shutdown can orphan OASIS processes.** `simulation_runner.py:2466-2469` stops world children first, with no try/except and before `_cleanup_done` is set. If one `WorldSimulationService.stop` raises (e.g. `missing_engine_pin`), the OASIS process cleanup never runs. Fix: catch per simulation and run it after the OASIS cleanup.
- **M3 — world runs lose official data.** World simulations are never bound to their research generation: `_run_world_stages` (create at 8572) and the seed/fork children never call `bind_simulation_research`. The dossier loader only sets official data for bound simulations (7259), so world reports and the evidence-only probability input get none. Fix: pass `research` into `_run_world_stages` and bind as OASIS PREPARE does (13818-13825); bind seed and fork children with the parent's generation.
- **M4 — the world seed ensemble spends money for nothing.** `_maybe_run_seed_ensemble` (9331-9350) runs N−1 extra world simulations plus N−1 full reports, then discards their forecasts without aggregating. Any seed failure re-raises (14398), failing a pipeline whose main report already succeeded. Fix: skip the ensemble for world-v1, or aggregate it; never fail after the main report.

**MINOR**
- `cancel()` on an orphaned world pipeline (8754-8760) stops each simulation without try/except. A deleted seed simulation raises, so the pipeline stays "running".
- `fork()` (9116-9124) creates and seals the world child before the pipeline directories and task exist, so a later failure leaves an orphan simulation. It also copies no `simulation_admission_v1`.
- `ReportAgent.__init__` (2410) always calls `load_simulation_world`. That raises on simulation ids outside the identifier pattern, on symlinked simulation directories, and on any float or duplicate key in a legacy `state.json`.
- The `before_request` hook doesn't catch `TypeError` (gives 500), and it also gates OPTIONS preflight requests.
- Every simulation get/list call fully re-verifies each completed world run (`simulation_manager.py:1559`), including on every SimulationView refresh.
- The world-v1 view never auto-refreshes while a run is in progress; `loadAll` returns before scheduling the refresh.

## 3. Changes to OASIS runs even when world-v1 is not selected

1. The B1 breakage above, including historical reports.
2. Every new pipeline's options gain `simulation_engine:"oasis-legacy"`, `world_spec:null`, `world_policy_spec:null` and a `simulation_admission_v1` record. Forks and batch children get pinned to `oasis-legacy`.
3. `state.json`, `GET /api/simulation/<id>` and the list endpoint gain four `world_*`/engine fields. `run_state.json` and `/run-status` gain `simulation_engine`, so hours-mode `run_state.json` is no longer byte-identical.
4. The runner and manager re-read `state.json` before every `get_run_state`, start, stop, interview and env-status call; the manager's in-memory cache is no longer used. The new id-pattern and no-symlink checks now raise where nothing did before. Startup orphan cleanup logs an error for stray entries such as macOS `.DS_Store`, and skips runs whose `state.json` is unreadable.
5. Admission changes:
   - Preflight rejects research models outside `SUPPORTED_DEERFLOW_MODELS`.
   - `continue` preflights with the saved model.
   - The preflight response gains engine fields.
   - An explicit `"simulation_engine": null` returns 400.
   - `/prepare` ValueErrors return 400 instead of 404.
6. The shutdown cleanup ordering problem (M2), if a world child ran in the same backend process.
7. Frontend:
   - SimulationView first fetches `/api/simulation/<id>` (20 s timeout) on every load, including the 10 s auto-refresh and every period click. Any failure or unknown engine replaces the whole OASIS view with an error and Retry, and a run-status engine mismatch aborts the load.
   - ResearchView now blocks Start until a preflight succeeds; before, a preflight error did not block. The round-cap field stays hidden until the preflight confirms `oasis-legacy`.
8. Report construction and loading a completed report now add a strict `state.json` read plus checks for world files, and `get_report_by_simulation` reads every `meta.json` twice.

## Codex's tests and the guarded runner

35 of Codex's 36 `test_world_*` modules are marked `guarded_runner` at module level. The base `conftest.py` skips them unless `MAIN_OFFLINE_EVIDENCE` is set, so plain pytest (CI) skips them all, including every integration test. Only `test_world_compiler.py` (37 pure compiler tests) runs. Setting the variable by hand runs them without the guard, which is unsafe: some depend on runner fixtures or real storage paths, and `test_main_offline_runner.py` fails on purpose in that case.

The guard (`backend/scripts/main_offline_pytest.py`) is a Python audit hook, not an OS sandbox. It runs with `-I -S -B` and blocks:
- network sockets;
- subprocesses other than hash-pinned scripts;
- exec, fork, and kill of non-children;
- reads of `.env`, credential and home files;
- writes outside the evidence directory;
- environment changes;
- SQLite files outside the evidence directory.

It also redirects the Config, SimulationManager and logger storage folders into the evidence directory. The upshot is that CI has no coverage of these integration hunks, and B1 slipped through because of that. I'd add unguarded plain-pytest and `node --test` checks for the OASIS report API with telemetry on, the default-engine dispatch, and SimulationView routing.
