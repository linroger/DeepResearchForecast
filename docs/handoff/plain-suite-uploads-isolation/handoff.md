# The plain suite stays out of the checkout's `backend/uploads` (2026-10-21)

**Status:** Complete on branch `claude/eloquent-shannon-5a149e`: one commit on `main` 31a3e31, which merges 7b429c8 with `claude/practical-jang-ea953c` (main's 8 plain-suite fixes). The work was first done on 7b429c8 and then rebased; the rebase applied cleanly. Nothing pushed or merged. `main` advances only by compare-and-swap, so merging is the owner's call.

## 1) Request

Make the backend plain suite (`backend/tests`) write nothing into the checkout's own `backend/uploads/`. `Config.PIPELINE_DATA_DIR` defaults to `backend/uploads/pipelines`, and `forecast_ledger.ledger_dir()` falls back to `PIPELINE_DATA_DIR/_forecast_ledger`. So a test that published through `ReportManager.save_report` (with `REPORT_FORECAST_LEDGER` on, the default) and did not set its own ledger appended to the checkout's `published_forecasts.jsonl`. In the deployment checkout, that file is the live ledger. This closes the follow-up in `docs/handoff/main-plain-suite-fixes/handoff.md` §5 (on `claude/practical-jang-ea953c`).

## 2) Before: what wrote there

A diagnostic pytest plugin (not committed) listed every new or changed path under `backend/uploads` after each test. Run over the whole plain suite on a frozen `git archive` of `main` 7b429c8, it found 9 tests in 5 modules writing there, and nothing at collection time:

| Test(s) | Left behind | Root it came from |
|---|---|---|
| `test_news_context_reports.py::test_real_report_sequence_seals_context_and_api_markdown_export[False/True]` | `reports/report_context_sequence/{agent_log.jsonl,console_log.txt}` | `ReportLogger` / `ReportConsoleLogger` build their paths from `Config.UPLOAD_FOLDER` at runtime. The module redirects only `ReportManager.REPORTS_DIR`. |
| `test_news_report_metadata.py::test_mixed_official_and_context_metadata_…[Chinese/English]` | `reports/report_mixed_metadata/{agent_log.jsonl,console_log.txt}` | same |
| `test_official_data_consumers.py::test_manual_create_endpoint_binds_pipeline_projects` | an empty `simulations/` | `SimulationManager()` creates `SimulationManager.SIMULATION_DATA_DIR`, a class attribute that copied its path at import. |
| `test_report_data_publication.py::test_structured_forecast_and_real_api_publish_without_bypass` | one line in `pipelines/_forecast_ledger/published_forecasts.jsonl` | the `ledger_dir()` fallback |
| `test_report_official_publication_real.py`: 4 publishing tests | more lines in the same ledger | same. This is also why `::test_backfill_keeps_official_exhibits_captions_and_audit` fails on `main`. |

Run alone on a fresh frozen `main`, each of the first four modules leaves its files behind too.

## 3) Change

`backend/tests/conftest.py` gains an autouse fixture, `_no_checkout_uploads`, in the style of `_no_prediction_market_network`. For every test it points the storage roots at a fresh `<pytest basetemp>/checkout-uploads/<n>/uploads`, laid out like production:

- `Config.UPLOAD_FOLDER` → that root, `Config.PIPELINE_DATA_DIR` → `…/pipelines`, `Config.OASIS_SIMULATION_DATA_DIR` → `…/simulations`.
- `Config.FORECAST_LEDGER_DIR` is set to `""`, so the ledger resolves to `…/pipelines/_forecast_ledger`.
- `ReportManager.REPORTS_DIR` → `…/reports`, and `SimulationManager.SIMULATION_DATA_DIR` and `SimulationRunner.RUN_STATE_DIR` → `…/simulations`.

Tests that set their own directories still override all of these, because their fixtures and bodies run after conftest's autouse fixtures, on the same `monkeypatch`.

Decisions:
- **Per-test root outside `tmp_path`, not created up front.** Some tests build their own `tmp_path / "uploads"` trees (`test_export_demo_site_data.py`, `test_research_contract_finalization.py`), so a shared name inside `tmp_path` could collide. Leaving the directory uncreated means each test starts the way a fresh checkout does, with no `uploads/`. The frozen-archive runs already show the code handles that.
- **`FORECAST_LEDGER_DIR` is cleared, not pinned.** An empty value is the production default, and it keeps the ledger following `PIPELINE_DATA_DIR`. 25 test modules set `PIPELINE_DATA_DIR`, and each keeps its ledger exactly where it was. Only the checkout-default case moves. The consequence: a test that switches `PIPELINE_DATA_DIR` partway through moves to a fresh journal, as it did before. For the backfill test, practical-jang's per-module pin (4ef5cd3, in `main` 31a3e31) is the precise fix. A one-off check on the rebased copy confirmed that it overrides this fixture: inside that module, `ledger_dir()` is the module's own `<tmp_path>/forecast-ledger`.
- **Class attributes are patched directly, and their modules are imported.** `REPORTS_DIR`, `SIMULATION_DATA_DIR` and `RUN_STATE_DIR` copied their paths at import, so patching `Config` alone does not reach them. Importing the modules (about 0.3 s, once per process) means a test that imports them inside its body still gets the redirect. If a module raises `ImportError`, that root is skipped: a module that cannot be imported cannot write there either.
- **No-op under the guarded runner** (`MAIN_OFFLINE_EVIDENCE` set). `scripts/main_offline_pytest.py` already redirects these roots into its evidence directory at import time and denies writes outside it, so guarded runs behave exactly as before.
- **No test depends on the shared default.** The tests that read the ledger back (`test_oddsense_workflow.py`, `test_forecast_feedback_sdk.py`, `test_forecast_feedback_workflow.py`, `test_foglamp_containment.py`) each set `FORECAST_LEDGER_DIR` themselves. No module-, class- or session-scoped fixture sets any of these roots. The full runs below confirm it: no test changed outcome except the expected ones.

Regression check: `test_runtime_lifecycle_isolation.py::test_storage_roots_stay_out_of_the_checkout_uploads` asserts that none of the seven roots (including `ledger_dir()`) resolves into the checkout's `backend/uploads`. It fails on `main` with the fixture absent and passes with it. It skips under the guarded runner, where the fixture does nothing.

## 4) Verification

All runs use frozen `git archive` copies in this session's scratchpad (no `deer-flow/`, so the 19 `test_legacy_official_data.py` errors are expected) and the deployment venv. The full runs use `/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -m pytest -p no:cacheprovider --junitxml=<file>` from `backend/`. The rows marked "this branch alone" ran on the pre-rebase commit (on 7b429c8, `backend/` tree `a071b725`). The rebased commit's `backend/` tree is `095be4ca`, byte-identical to the merged tree in the next-to-last row.

| Run | Result | `backend/uploads` after |
|---|---|---|
| Whole plain suite, `main` 7b429c8 (with the probe) | `8 failed, 7486 passed, 1497 skipped, 11 xfailed, 19 errors` | ledger, two report log folders, an empty `simulations/` (§2) |
| The 5 modules from §2, each alone, this branch | 14, 15, 4, 21 and 32 passed | none after any of them |
| The same modules alone on a fresh `main` (first four) | all pass | the files in §2 |
| Whole plain suite, this branch alone (with the probe) | `7 failed, 7488 passed, 1497 skipped, 11 xfailed, 19 errors`; the probe recorded no write at any point | none |
| Whole plain suite, this branch merged with `claude/practical-jang-ea953c` (`git merge-tree`, clean; exact command, no probe) | `7495 passed, 1497 skipped, 11 xfailed, 19 errors`; JUnit `tests=9022 failures=0 errors=19` | none |
| **Final:** whole plain suite, the rebased commit on `main` 31a3e31 (exact command, no probe) | `7495 passed, 1497 skipped, 11 xfailed, 19 errors in 410.36s`; JUnit `tests=9022 failures=0 errors=19`; every test's outcome is the same as in the merged run | none |

- **Per-test JUnit diffs.** From `main` to this branch, exactly two outcomes change: `test_backfill_keeps_official_exhibits_captions_and_audit` goes from failure to passed (its module no longer shares a ledger), and the new regression test is added. The 7 failures left on this branch alone are the rest of main's known 8, which practical-jang fixes. From this branch to the merge, exactly those 7 go from failure to passed. Nothing else changes.
- **Against `main` 7b429c8**, the final run changes exactly 9 outcomes: the 8 known failures now pass, and the new test is added.
- **Kaleido.** `test_wave9_visualizer.py::test_kaleido_png_pair_standalone_builder` passed in all three full runs.
- **Exit hang.** The branch-alone run hung after its summary and was killed once its JUnit file existed. The merged and final runs exited on their own within 8 s of writing their JUnit files. The hang is pre-existing and intermittent.
- **Guarded runner.** `-I -S -B scripts/main_offline_pytest.py` on `test_runtime_lifecycle_isolation.py`, `test_world_browser_fixture.py` and `test_oddsense_feedback_merge.py` gave 6 passed and 1 skipped (the new test, with its reason), and left no `backend/uploads`. The whole guarded suite was not run, because the fixture returns before touching anything there.
- **Ruff.** `uvx ruff@0.17.1 check --select F,E9 --ignore F401,F841` passes on both touched files.

## 5) Follow-ups (not done here)

- **Paths built from `__file__` at call time** cannot be redirected by an attribute: `app/api/simulation.py` (reports and simulation paths at about lines 910, 2498 and 2580), `app/services/zep_tools.py` (about line 2222) and `PipelineOrchestrator._sim_dir`. No test writes through them today (the probe recorded nothing), but a future test could. Routing them through `Config` would close this.
- **Child processes** import a fresh `Config`, whose defaults point at the checkout. Tests that run app code in a subprocess must pass their own directories, as `test_forecast_feedback_sdk.py` and `test_forecast_feedback_workflow.py` do.
- **Unchanged from the earlier record:** the plain suite's exit hang and the flaky Kaleido launch.
