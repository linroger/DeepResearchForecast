# Handoff.md — consolidating the two world engines (claude reflexive world model × Codex world-v1)

**Last Updated (UTC):** 2026-10-17T19:45Z
**Status:** Complete — merged into `main` as 609d5fa and pushed (`legacy/main` f78397e..609d5fa)
**Current Focus:** none in this record; the world-v1 follow-up plan is in §9.

Interpret MUST/SHOULD/MAY per RFC 2119.

## 1) Request & Context
- **Owner's words (2026-10-18 02:21 +08):** first "Yes. After the OPEC+ run finishes, merge claude-reflexive-world-state-model and refs/heads/claude/zealous-fermi-496656, refs/heads/claude/epic-villani-949705, refs/heads/claude/dazzling-varahamihira-e0bba5 into main via a test worktree with the suites run, then push main.", then, interrupting: "actually, review the world-v1 from the codex world state branch, review it, and consolidate it with the current claude world state branch and combine them and then merge it into the main".
- **Reading adopted:** the follow-up approvals stand (nothing retracted them); the new instruction adds the Codex `world-v1` engine — reviewed and combined with the claude world model — to what goes into `main`. The merge waits for the OPEC+ run, as the first message asked.
- **The two engines:**
  - *claude reflexive world model* (default): runs inside the OASIS social simulation — `world_model.py`, `agent_decision.py`, `world_update.py`, `world_model_seed.py`, `_ReflexiveWorldCoordinator` in `run_parallel_simulation.py`, `/world-state`, `/feed-rounds`, World State panel and per-period feed; consent rule, modelling gaps and behaviour diagnostics already ported from world-v1 (merge round of 2026-10-17, `docs/handoff/world-state-merge/handoff.md`); live-validated twice.
  - *Codex world-v1* (opt-in, `simulation_engine: "world-v1"`): a separate engine that replaces the social simulation for a run — typed ledger world, compiler from research evidence, round controller with proposal/response phases, deterministic kernel, fenced SQLite store, strict budgeted HTTP policy, decision review/consistency modes, `/world` API, WorldSimulationView, conditional report appendix. Branch `codex/reflexive-world-simulation`, tip a6fbbc0 (15 commits on old main 8852ce1). Its delivery keeps it opt-in.
- **Constraints:** the deployment checkout (`/Users/rogerlin/Downloads/DeepResearchForecast`) serves running pipelines from its working tree (ports 5001 and 5013) and carries another process's uncommitted edits, so all work happens in the worktree `/Users/rogerlin/Downloads/drf-world-consolidation` (branch `claude/world-engines-consolidation`); OASIS stays the default engine (`DEFAULT_SIMULATION_ENGINE=oasis-legacy`); Codex's guarded tests run through `backend/scripts/main_offline_pytest.py` on a frozen copy; `git push` and `gh` run with `env -u GH_TOKEN`; side-session branches are never pushed themselves.
- **Changes since start (dated deltas):**
  - 2026-10-18 03:06 +08: the OPEC+ run failed at its report publication gate (report_03808b57d7fb: one scenario probability inconsistent with the skeleton, one body probability not matching forecast.json).
  - 2026-10-18 03:12 +08: another session resumed it on :5013 (report_11f6161e92c9 generating).
  - 2026-10-18 03:21:45 +08: the run completed (`report_11f6161e92c9`); the merge gate is met.

## 2) Requirements → Acceptance Checks
| Requirement | Acceptance check | Evidence |
|---|---|---|
| R1 follow-ups merged | merge the three approved branches; world/translation suites | §4 (06ae11b, e51d621, ecf4cf3), §8 |
| R2 world-v1 reviewed | four parallel read-only reviews (core engine; persistence and lifecycle; model-facing; integration and UI) with every finding triaged | `reviews/*.md`; triage in §5 and §9 |
| R3 engines combined | both engines selectable in one tree; the simulation tab routes by the saved engine; report/API keep both paths; OASIS default unchanged | §5 decisions, §7 scenarios, coexistence tests |
| R4 suites | full plain backend suite, all guarded tests under the runner, frontend tests, build, ruff, env drift, compileall | §8 |
| R5 merged into main | after the OPEC+ run: merge into `main`, push `main` | 609d5fa on `legacy/main` (§4) |

## 3) Plan
1. Consolidation worktree from the branch tip (dcff768); merge the three follow-ups. **Done.**
2. Merge `codex/reflexive-world-simulation` (a6fbbc0); resolve conflicts. **Done** (ad1c0ee).
3. Reviews in parallel with the merge; triage; fix what affects OASIS runs, the integration, or stops a world-v1 run cheaply and certainly. **Done** (§4–§6).
4. Docs: README (EN/ZH, line-aligned) — two engines and world-v1's known limits; review reports saved under `reviews/`. **Done.**
5. Suites as R4. **Done** (§8).
6. After the OPEC+ run: merge into `main`, push. **Done** (609d5fa).

## 4) To-Do & Progress Ledger
- [x] Worktree and follow-up merges — 06ae11b (zealous-fermi), e51d621 (epic-villani), ecf4cf3 (translation chain); conflicts resolved in date order; world + translation suites 261 passed, frontend 163 passed.
- [x] Codex merge — ad1c0ee; text conflicts in 5 files only (SimulationView.vue, api/simulation.js, report_agent.py, feature_list.json, agent-progress.txt); Codex's frontend harness extended; frontend 217 passed, build OK.
- [x] Docs — d7c8cd2 (two engines, routes, settings), 3fc88c8 (world-v1 known limits).
- [x] Reviews (4) — reports in `reviews/core-engine.md`, `reviews/persistence-lifecycle.md`, `reviews/model-facing.md`, `reviews/integration-ui.md`.
- [x] Fixes, one commit each:
  - 8f4be83 — plain-suite fixes after the merge (OASIS reports with unreadable meta.json no longer 409; two test stubs).
  - 3bc2caa — shutdown cleanup survives a failing world-v1 stop; default engine pinned by a test.
  - e5a7ae4 — world database published atomically (persistence B2).
  - a5ca0d7 — report meta.json read leniently in the world integrity check; API gate skips CORS preflight, maps TypeError to 409 (integration B1).
  - 4c05e97 — list rule: unloadable entries skipped, a list that selects a damaged world fails closed, history skips it (persistence B3, reconciled with world-v1's pinned rule).
  - 887909e — malformed `bundleId` rejected at decision admission (core B1).
  - 1bbe6df — pure kernel and grammar suites run in the normal gate (102 tests).
  - 98e9c91 — engine selector names and order.
- [x] Suites — §8.
- [x] Merge into `main` — 609d5fa, a `--no-ff` merge whose tree is byte-identical to the tested tip 9045c9d (parents f78397e and 9045c9d), made with `git commit-tree` + `git update-ref` (old-value checked) because no worktree has `main` checked out; pushed with `env -u GH_TOKEN git push legacy main` (f78397e..609d5fa); `git ls-remote` confirms. The merge changes nothing under `docs/` outside `docs/handoff/`, so the demo site's pages are unchanged. This record's final update is the commit after 609d5fa.

## 5) Findings, Decisions, Assumptions
- **Finding:** the Codex branch moved after the 2026-10-17 study (95ebd04 → a6fbbc0: decision review modes v2–v4, candidate repair, consistency controller, default/fresh admission, transport diagnostics); its worktree was clean at the merge. Something else wrote untracked files into the Codex worktree at 02:44 (`docs/handoff/reflexive-world-simulation/behavior-rerun/.../evidence-recovery/`); the branch tip did not move, and those files are not part of this merge.
- **Finding:** textually the two implementations barely overlap — the orchestrator, runner, manager and API merged without conflicts; the conflicts were the simulation tab and its API module.
- **Finding:** world-v1's strict reader accepts all 55 saved OASIS `state.json` files but rejects 30 of 72 saved report `meta.json` files, because report telemetry writes floats (`telemetry.totals.duration_s`, `est_cost_usd`, `latency_ms`). Probe: `strict_probe.py` (read-only, scratchpad), 2026-10-18 02:58 +08.
- **Finding:** Codex already checks the engine first at every completion-evidence and reuse gate (`_require_run_completion_evidence`, the run-summary and reuse checks), so world-v1's missing `run_summary.json` does not trip the OASIS gates (integration risk 4 in the persistence review: covered, no change).
- **Finding:** the world-v1 seed ensemble only runs when `n_forecast_seeds` > 1; the default is 1, so its cost and failure modes (integration M4) are dormant by default.
- **Finding:** the CI ruff gate passes with `uvx ruff` 0.17.1; the pyenv ruff 0.13.3 flags `BaseExceptionGroup` in `deerflow_bridge/data_mcp.py` (unchanged since 645e3c1) only because its default target version is older.
- **Decision:** the simulation tab first resolves the saved engine (Codex's routing and request gate); world-v1 runs render WorldSimulationView, OASIS runs keep the World State panel and the per-period feed. The selected period travels as `options.round` so Codex's request-options argument and its tests stay as they were.
- **Decision:** OASIS remains the default (`Config.DEFAULT_SIMULATION_ENGINE` defaults to `oasis-legacy`; pinned by `test_engine_coexistence.py`).
- **Decision (list rule):** entries that cannot be loaded at all (a Finder duplicate such as `sim_x copy`, a symlinked directory, a corrupt `state.json`, world artefacts under an OASIS pin) are skipped and logged — main itself failed the whole list on a corrupt `state.json`. A list that selects a world-v1 run failing integrity verification fails closed (world-v1's rule, pinned by `test_project_list_excludes_corrupt_unselected_world_before_projection`). The cross-project history index passes `skip_unverifiable_worlds=True`, logging and skipping such a run, so one damaged world cannot hide every other run. Alternative considered: a stub row with `status=failed` (the persistence review's suggestion); not taken because it changes the list contract that Codex's test pins.
- **Decision (report metadata):** `meta.json` is the report's own mutable record, not a world artefact, so `read_report_world` reads it as ordinary JSON; the world identity it names is still checked against the strictly read `world_result_ref.json` and the simulation's frozen result. Tampering with that identity still fails closed (guarded test).
- **Decision (scope of world-v1 fixes):** fixed now — defects that affect OASIS or the integration, and world-v1 defects with a small, certain fix and a regression test (atomic store creation, bundle-id admission). Deferred with a plan (§9) — engine redesigns that need their own study: real-dossier compilation, 429/1301 handling, v4 admission, PID-reuse liveness, boundary effects, visibility, ordering and performance. world-v1 stays opt-in and the README now states its known limits.
- **Decision (tests):** `test_world_kernel.py` (pure) and `test_world_public_grammar.py` (reads one checked-in fixture, writes only under `tmp_path`, forbids HTTP itself) no longer carry the `guarded_runner` mark, so the normal gate covers them; the guarded runner still runs them.
- **Decision (UI labels):** the selector lists the server default, then "Social simulation + reflexive world model" (`oasis-legacy`), then "World engine v1 (experimental)" (`world-v1`); zh: 社交模拟 + 反身世界模型 / 世界引擎 v1（实验性）. No label contains "OASIS" (a Codex test requires that while the preflight runs) and none claims "(default)", because an operator can change the server default.
- **Decision (world-v1 view refresh):** the world-v1 view has an explicit "Refresh latest" button and a fixed read cursor, so it does not auto-poll; left as designed (the integration review listed this as a minor).
- **Assumption:** the OPEC+ run is "finished" when its pipeline status is terminal and no session is resuming it. Check: `GET /api/research/status/pipe_fd2799f3ad41` on :5001 and :5013 plus the pipeline folder's mtimes. Result at 03:13 +08: running again on :5013 (report stage). Next action: re-check before merging.

## 6) Issues, Mistakes, Recoveries
- **My first list guard contradicted world-v1's pinned rule.** Symptom: the guarded rerun after 3bc2caa failed `test_project_list_excludes_corrupt_unselected_world_before_projection` (200 instead of 500). Root cause: the per-entry guard also swallowed projection (integrity) failures of selected worlds. Fix: 4c05e97 (skip only unloadable entries; history opts in to skipping). Guardrail: the guarded suite runs after every change to shared code paths, and `test_damaged_world_fails_a_list_that_selects_it_but_not_the_history` plus `test_history_endpoint_survives_a_damaged_world` pin both halves.
- **The first atomic-store version used `os.replace`.** Root cause: two creators racing on the same new world could swap the file under a writer that had already opened it. Fix: publish with `os.link` (fails if the path exists); the loser opens the winner's world. Regression check: `test_a_concurrent_creator_never_replaces_a_published_world` fails with `os.replace` (scratch copy) and passes with `os.link`.
- **8f4be83 fixed only the OASIS half of the 409.** Its fallback to `{}` for an unreadable `meta.json` let OASIS reports through but left world-v1 reports with telemetry at 409 ("Report lost its saved world identity"). Fix: a5ca0d7. Regression check: `test_report_telemetry_floats_in_meta_keep_world_reports_readable` (guarded) fails without the change and passes with it.
- **The plain suite printed no totals line.** Cause: `backend/pyproject.toml` already sets `addopts = "-q"`, so an extra `-q` makes it `-qq`, which suppresses pytest's final stats line; not a crash (exit 1 from the 19 known errors, JUnit complete). Guardrail: run the plain suite without `-q` and with `--junitxml` so totals are always recorded.
- **Shell traps (earlier in the session):** zsh mangled `$C:path` in `git show` (use `"${C}:path"`) and did not split `$TESTS` (use `${=TESTS}`), so one guarded run collected 0 tests; the hook blocks `rm -rf` outside `trees/`, so scratch copies use fresh directory names.

## 7) Scenario-Focused Resolution Tests
- **Report API 409 for reports with telemetry (integration B1).** Repro: a sealed world-v1 report whose `meta.json` holds `telemetry.totals` floats → `load_world_result` raised, every gated route 409. Change: a5ca0d7. After: verification passes, `/api/report/<id>`, `/world-result`, `/download` answer 200; a tampered `world_result_ref` in `meta.json` still answers 409. OASIS reports with the same floats: no world, 200. Verdict: resolved.
- **History outage from one damaged world (persistence B3).** Repro: a world-v1 run whose `world_spec.json` changed → `/api/simulation/history` 500 for everyone. Change: 4c05e97. After: history 200 without that run (error logged); `/list` and `/list?project_id=<its project>` 500 as world-v1 requires; `/list?project_id=<another project>` 200. Verdict: resolved.
- **Half-made world database (persistence B2).** Repro (review probe `sqlite_init_probe.py`): a reader during the first launch's init saw `application_id=0` and raised `unsupported_store`; a failed init left a 0-byte file forever. Change: e5a7ae4. After: readers get `missing_world` until publication; a failed init leaves nothing; the next attempt succeeds. Verdict: resolved.
- **Malformed bundle id stops a run for good (core B1).** Repro (review probe p1b): a policy emitting `"bundleId": "buy and expand"` → `run_round` fails, resume fails the same way, head stays at round 0. Change: 887909e. After: admission raises `invalid_intent`, the slot retries, the round commits, no saved decision carries the bad id. Verdict: resolved.
- **Shutdown orphaning OASIS processes (persistence M1).** Change: 3bc2caa. After: a failing world-v1 stop is logged and the OASIS teardown still runs. Verdict: resolved.

## 8) Verification Summary
- **Follow-up merges:** world + translation suites 261 passed; frontend 163 passed.
- **Codex merge:** frontend 217 passed (incl. Codex's 24 simulation-tab tests with the extended harness); build OK.
- **Final tree (98e9c91 code; 3fc88c8 changes only the READMEs, covered by the README-reading tests below):**
  - Plain backend suite (frozen copy, JUnit `tests=7875 errors=19 failures=0 skipped=1281`): 6,575 passed, 1,270 skipped, 11 xfailed, 19 errors, 0 failed. The 19 errors are `test_legacy_official_data.py`, which needs the untracked deer-flow checkout (`FileNotFoundError` for `deer-flow/backend/packages/harness/deerflow/config/tool_config.py`); the same 19 appear on the 02:36 run and in the pre-flight worktree. Against the 02:36 run (7 failed, 6,460 passed, 1,361 skipped, 11 xfailed, 19 errors): +17 tests are the new ones, the 7 failures are fixed, 98 kernel/grammar tests moved from skipped to passed, and 6 tests that read real handoff artifacts skip because the frozen copy excludes `backend/uploads`.
  - Guarded runner (frozen copy, every `guarded_runner` module plus the two unguarded world modules): 1,333 passed, 3 failed; `test_main_offline_runner.py` under the guard: 23 passed. The 3 failures (`test_deployment_sidecar_control_flow.py` ×2, `test_official_data_end_to_end.py::test_guarded_mcp_to_promoted_research_and_report_png`) are pre-existing on `main` under the guard: it blocks the data-MCP subprocess. Count check against the 02:32 run: 1,330 → 1,336 per module set = the 6 new tests.
  - Frontend: `npm run test:unit` 217 passed, 0 failed; `npm run build` OK.
  - Gates: `uvx ruff check --select F,E9 --ignore F401,F841,F541 backend/app backend/scripts deerflow_bridge` all checks passed; `check_env_drift.py --strict` exit 0; `compileall` OK.
  - Targeted: `test_engine_coexistence.py` 5 passed; `test_report_world_gate_oasis.py` 3 passed; `test_world_store_atomic_init.py` 3 passed; `test_world_kernel.py` 78 passed (plain); README-reading tests 83 + 20 passed.
- **Runbook — guarded run on a frozen copy:**
  ```bash
  RUN=/Users/rogerlin/Downloads/drf-guarded-runs/$(date +%Y%m%d-%H%M%S); mkdir -p "$RUN"
  rsync -a --exclude .git --exclude node_modules --exclude backend/uploads --exclude .venv --exclude __pycache__ --exclude .pytest_cache --exclude logs --exclude frontend/dist /Users/rogerlin/Downloads/drf-world-consolidation/ "$RUN/src/"
  cd "$RUN/src" && /Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir "$RUN/evidence" <test paths> -p no:cacheprovider
  ```
  The evidence directory MUST be new for each run; in zsh, split a list variable with `${=VAR}`.

## 9) Remaining Work & Next Steps
- **Deployment (owner's call):** the deployment checkout still serves `claude-reflexive-world-state-model` (dcff768) plus another process's uncommitted edits on ports 5001/5013; it does not run the merged code until someone switches it to `main` after those edits are settled.
- **world-v1 follow-up (not fixed here; owner decides when):**
  - *Stops a run:* PID-reuse writer liveness after a reboot (use the launch flock, SIGTERM → cancel-and-release, log pre-fence failures); boundary effects that raise in `_advance` (record `*_failed` events or tighten admission); any 429/1302 is terminal (classify with `llm_errors`, back off with Retry-After, share `model_call_lease`, stop resumably); mandatory v4 review makes `unknown`/`inconsistent` terminal; the per-round event limit kills a round; resume burns non-restorable attempts.
  - *Usable on real dossiers:* the compiler/modeler cannot cite v3 research (no claims, offsets plus SHA-256, JSON-parsable quotes), modeler requests exceed the pinned 60k input bound, no repair path, attempt rows lack error codes; NFKC rejects CJK names with full-width parentheses; 1301 handling; truncation and a `thinking: disabled` pin; bind world runs to their research generation so reports get official data.
  - *Correctness and privacy:* commitments, messages and hidden metrics leak beyond the parties; simultaneous-event order depends on the random generation id; `WorldError` subclasses `ValueError` (audit broad `except ValueError` in shared code).
  - *Bounds and cost:* observation growth, quadratic kernel cost, unbounded `/world` and export size, per-request re-verification of world reports, poll cost.
  - *Minor:* cancel/fork orphans, renderer-bound results (version the result manifest before any change to `results.py` rendering), seed ensemble when `n_forecast_seeds` > 1, the minors listed in each review.
- **Risks:** none of the deferred items affects OASIS runs; world-v1 remains opt-in, and an operator who selects it on a real dossier will hit the known limits the README states.
- **OPEC+ run:** completed at 2026-10-18 03:21:45 +08 (`report_11f6161e92c9`), so the merge gate is met.
- **Live check of the merged tree (03:24–03:30 +08, :5021, read-only, real uploads):** preflight ready with engine `oasis-legacy` and no errors; `/api/simulation/history` and `/list` 200 (55 each); all 76 report folders through `/api/report/<id>`: 73 × 200, 3 × 404 (test folders without `meta.json`, also 404 on the deployment), no 409; the dashboard's engine selector shows the new names and order, Start enables once a question is typed (not pressed); the OPEC+ simulation tab renders the OASIS view, world state and feed for 2027-01 (`round=4` requests 200); its report renders with all report requests 200.
- **Cleanup done:** the :5021 test backend is stopped and the consolidation worktree's `backend/uploads` symlink removed; the branch `claude/world-engines-consolidation` is fast-forwarded to `main`.

## 10) Updates to This File (append-only)
- 2026-10-17T18:40Z: created after the follow-up and Codex merges; reviews and suites running.
- 2026-10-17T19:25Z: reviews saved under `reviews/`; findings triaged; eight fix commits recorded (§4); final-tree suites recorded (§8); world-v1 follow-up plan (§9); the merge waits because the OPEC+ run was resumed on :5013 at 03:12 +08.
- 2026-10-17T19:35Z: plain-suite totals recorded from JUnit (the `-qq` trap in §6); OPEC+ run completed; live read-only check of the merged tree on :5021 recorded (§9).
- 2026-10-17T19:45Z: merged into `main` as 609d5fa and pushed; status Complete; deployment note and cleanup recorded (§9).
