# Renderer status and fiscal-label fix

Status: Complete for this bounded slice, 2026-10-12. This is the owned continuity record; shared/root handoffs are preserved.

## Request and boundaries

Correct the research renderer so unknown, preliminary, estimated and explicitly forecast values retain their actual status, and fiscal periods retain their canonical labels. Keep stored values, units and gaps intact. Initial ownership is `deerflow_bridge/skills/data-visuals/scripts/render_data.py`, new `backend/tests/test_data_visuals_status.py`, and this report. The lead additionally authorized only `official_observation_kind` in `backend/app/services/forecast_extractor.py` and regressions in `backend/tests/test_report_official_data.py` for the analogous preliminary-status boundary. Existing report source/prose/anchor rules remain frozen.

No vendor/live/provider calls, saved-run access, installs, service operations, runner edits or commits. The independent E2E worker owns its integrated test and fixture. Runtime verification uses the existing guarded runner and an exact allowlist for this renderer CLI.

## Plan and acceptance

1. Obtain Galileo's exact status and fiscal metadata contract before implementation; inspect current renderer and reviewer findings.
2. Add synthetic behavioral red tests through real loading/plot traces/latest markers, including noncontiguous status changes and fiscal labels.
3. Apply the smallest renderer/status-classifier changes; preserve manifest ownership and established shape/path rules.
4. Run the real CLI with guarded subprocess permission, inspect actual PNGs, execute bounded compatibility checks and obtain independent review.

Success requires no unknown/preliminary/estimate value labelled observed or forecast, no explicit forecast promoted to historical, exact fiscal labels on supported period displays, unchanged values/missingness/units, and retained sibling manifest rows. Evidence consists of red/green JUnit and guard receipts, source hashes, inspected PNGs and independent review.

## Findings and coordination

- Current `_load_series` discards all non-projection observation flags; `_Series.latest_observed` treats every non-projection number as observed. The current caption promises a latest-observed marker even for unknown-only values.
- Current renderer keeps only a single projection cutoff, so one isolated forecast flag can incorrectly reclassify later known actuals.
- Fiscal metadata is not retained in the internal renderer series. Annual display uses the calendar start year.
- Galileo (`01a12bdd-9095-7d81-9c13-917029de4fda`) supplied the frozen fields before implementation. The intake findings above describe the pre-fix state.

## Verification and updates

- 2026-10-12: Read current renderer, existing renderer tests, relevant provider-review findings and root handoff. Confirmed renderer is pre-existing untracked work; preserve its existing content. No runtime tests or source edits yet.

## Authorized scope deltas and implementation

- The lead authorized fiscal tick labels, hover labels and provenance captions in `backend/app/services/report_visualizer.py`, plus its preliminary style entry, `REPORT_DATA_CHARTS` gate and explicit `zip(strict=...)` in the official functions. Values, dates, thresholds and report prose/anchor rules remain unchanged. `backend/app/services/report_agent.py` is untouched by this task.
- The lead also authorized only two fixture identity/provider changes in `backend/tests/test_data_visuals_render.py`. A compatibility run identified the exact obsolete selectors `test_projection_segment_is_dashed_shaded_and_labelled` and `test_projection_boundary_falls_back_to_projection_flags`. Both now use `fred:SYNTHETIC_GROWTH` / `Synthetic FRED fixture`; values, flags, dates and assertions remain intact. Explicit unknown-WB regressions remain in the new test file. Real WB data was not relabelled observed.
- Galileo froze the contract in `integration-contract.md` under “Provider fidelity and fiscal periods.” Canonical flags are observed/unknown/preliminary/estimate/projection. Explicit nonhistorical status overrides the projection cutoff, observed/cutoff contradictions become unknown, raw BLS P becomes preliminary and other raw P is unknown. WB and USAspending remain unknown regardless of legacy flags/cutoffs. Fiscal metadata is keyed by ISO start date in `provenance.periods` and includes label/start/end/covered interval/completeness.
- Research loading now retains point status and fiscal metadata. Distinct status traces and markers preserve values and gaps, avoid latest-observed labels on uncertain values, and bound projection shading to the actual classified segments. Full and partial fiscal labels remain tied to their date identity. Invalid/missing USAspending fiscal metadata is skipped with a diagnostic; partial fiscal totals are omitted from automatic cross-economy overlays.
- Report changes consume the same status rules and fiscal labels on native date axes, hover and manifest provenance. Preliminary is separately labelled, never forecast. Fiscal display changes do not modify eligibility, stored numbers, model thresholds or the shared API.
- `REPORT_DATA_CHARTS=false` omits official report charts with `report_data_charts_disabled`, retaining other report exhibits. Research ENV cap zero or CLI `--max 0` clears stale `data_` manifest rows and returns exit two, including when Matplotlib is unavailable; foreign rows and underlying files remain. Positive caps still count single-series charts, with up to two compatible comparisons additional.

## Evidence so far

- `/private/tmp/drf-renderer-status-red-v1`: three genuine failures through load/latest/trace/caption behavior before the patch.
- `/private/tmp/drf-renderer-status-red-v2`: 21 failures, three passes and fifty deselections across status/fiscal fixtures, including actual permitted renderer CLI execution.
- `/private/tmp/drf-renderer-controls-red-v1`: three failures proving ENV/CLI zero still rendered and the report flag was ignored.
- `/private/tmp/drf-renderer-zero-dependency-red-v1`: two failures and two passes proving cap-zero cleanup depended incorrectly on Matplotlib availability.
- `/private/tmp/drf-renderer-status-green-v1`: 101 passed, two expected obsolete WB projection-fixture failures identified above. The real CLI emitted PNGs and preserved foreign manifest rows. Inspected the fiscal PNG: FY2024 and FY2025 (partial), unknown-status legend, USD unchanged; the synthetic fixture publisher label was subsequently corrected to USAspending.
- `/private/tmp/drf-renderer-controls-green-v1`: all five control cases passed. Exact command: `backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-renderer-controls-green-v1 -q backend/tests/test_data_visuals_status.py backend/tests/test_report_official_data.py -k 'zero_chart_cap or data_charts_flag'`. Tesla received this receipt and is independently validating documentation; this worker has not edited documentation-owner files.
- Ruff with `--target-version py311`: `/private/tmp/drf-renderer-status-ruff-v2.json` has only pre-existing report_visualizer findings (66 C408, five B905 outside the official functions). No findings in new/changed scopes after explicit zip strictness and fixture-import cleanup. Unrelated baseline lint was left alone.
- Independent reviewer `01a12be7-fa2d-7543-9573-c1449f529942` began the bounded review after these initial results. Its closure and final acceptance are recorded below.

## Final acceptance

**120 tests passed in 15.59 seconds** under `/private/tmp/drf-renderer-status-final-v1`, with no failures or skips. The exact command is recorded in `source-freeze.json` and reproduced below; the before/after hashes have `drift=[]`. `completed.json`, `junit.xml`, `test-output.txt` and five `process-*.json` receipts preserve the actual run. All five processes completed and retained identity variables. Four exact renderer children were allowed; the missing-Matplotlib compatibility child returned the expected exit three. Across all receipts the guard contained two font-discovery subprocess attempts and eighteen font-directory reads. No network, credential-path or saved-data attempt is recorded. These are CPython audit receipts, not an OS-sandbox claim.

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-renderer-status-final-v1 --allow-python-script deerflow_bridge/skills/data-visuals/scripts/render_data.py -q backend/tests/test_data_visuals_status.py backend/tests/test_report_official_data.py backend/tests/test_data_visuals_render.py backend/tests/test_report_visualizer_axes.py backend/tests/test_report_zh_presentation.py
```

Use a new nonexistent evidence directory for repetition. Do not reuse any receipt directory.

| Changed source/test | SHA-256 at final acceptance |
|---|---|
| `deerflow_bridge/skills/data-visuals/scripts/render_data.py` | `6da38d8598753c28f7d6bb50a81c912892990162b0113f841fe65c5c27707136` |
| `backend/app/services/forecast_extractor.py` | `6701eee178e9b34da7e9704cc7bdc56e395b8b256d37a8d9b826aa082174adac` |
| `backend/app/services/report_visualizer.py` | `7002f50d7249e40c93d31deace8359b06921d68c37575260052021867b821a92` |
| `backend/tests/test_data_visuals_status.py` | `724163cde4fb9cbb7c5fe7f629e92f8bfcb521d1211087baadbc14c54691253d` |
| `backend/tests/test_report_official_data.py` | `87534390e82ff91d99e74fee2f5debc0b776a82878117909e3c2d9a3a6a5eddc` |
| `backend/tests/test_data_visuals_render.py` | `f360fa16c8c50b1fd1148ee48011143836ac6ac3e714ef48b0247aa0bd1af9a1` |

`report_agent.py` remains byte-identical to the prior report-slice acceptance (`49cd75ed...`). The six paths above plus this report are the exact changed paths for this task. The independent E2E fixture/test, shared API, MCP hub, runner, README files and `.env.example` were not edited by this worker.

### Review and image checks

The independent reviewer found one P2 comparison-legend issue: unknown and preliminary points had different plotted markers but identical legend line keys. `/private/tmp/drf-renderer-legend-red-v1` reproduced the missing marker. The corrected handles now retain their `x` and triangle markers, and the final gate checks the real Matplotlib legend objects. Galileo's finalized blank-WEO/vintage policy exposed a second legacy-cutoff path; `/private/tmp/drf-renderer-weo-policy-red-v1` captured two behavior failures before guards were added to both renderer and report status classification. The reviewer then confirmed no remaining P1/P2 findings in the bounded review. It was static review; this worker independently ran the runtime checks.

Inspected the actual CLI PNGs in `/private/tmp/drf-renderer-status-green-v2/pytest-tmp/test_real_cli_renders_status_a0/run/charts/`: `data_usgov_spending_total.png` shows FY2024 and FY2025 (partial), the supplied USD values, an unknown-status legend and correct synthetic USAspending source footer. `data_imf_weo_usa_ngdp_rpch_a.png` shows unknown values with the supplied missing gap intact and no latest-observed marker. Final CLI rerendering uses the same rendering path; the legend refinement is covered by the dedicated comparison check.

Ruff command: `ruff check --target-version py311 --output-format json` over the six source/test paths, saved as `ruff.json` in the final evidence directory. Exit one is entirely the untouched report_visualizer baseline (66 C408 and five B905 outside the official-data functions). New/changed scopes have no Ruff findings. Scoped `git diff --check` passed.

### Integration boundary and handoff

The final run includes the frozen API policy bytes recorded in `source-freeze.json`. A post-run check found later independent changes to the shared MCP hub and integration-contract document, while all owned source/test hashes remained unchanged. Those later cross-slice bytes belong in the coordinator's final integration gate; they are not silently claimed by this receipt. Tesla independently passed the five control cases and completed bilingual docs without code changes.

Next-session prompt: "Read renderer-status-fix.md and its final source-freeze receipt. Preserve unrelated main changes and the report prose/anchor rules. Complete coordinator-owned integration using current shared dependencies. Re-run this bounded gate only if renderer/status/fiscal/control semantics or shared contracts change. Retain provider uncertainty and do not reinterpret preliminary as forecast or FY labels as calendar years. No live/provider proof is claimed by these synthetic fixtures."

- 2026-10-12: Closed independent review; finalized status/fiscal/control fixes, compatibility fixture alignment, actual PNG inspection, zero-drift 120-test acceptance and lint-baseline reconciliation. No commits, live calls, saved-run access, installs or service restarts were performed.
