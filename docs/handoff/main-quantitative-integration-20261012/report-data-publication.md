# Official-data report publication boundary

Status: Complete and source-frozen, 2026-10-12. Production defect reproduced, guarded final acceptance passed, and independent review closed. This owned record preserves the root/shared handoffs.

## Request and acceptance

Reproduce the E2E scratch-report observation that real official-chart caption citations disappeared and final audit found a duplicate-sentence lint change. Compare the fixture call order with real report generation before attributing a production defect. Exercise actual stored source metadata, generated charts, citation finalization, stabilization/lint and final publication audit without bypassing publishability. Invalid source markers must still be rejected, and chart manifest/source captions must remain coherent.

Allowed changes are a new `backend/tests/test_report_data_publication.py`, this report, and narrow `report_agent.py` / `report_lint.py` changes only if the production sequence proves a substantive defect. Report visualizer, renderer, pipeline, providers, runner and other owners' tests remain frozen. No live/model/provider calls, saved-run access, installs, service operations or commits. The referenced `/private/tmp/drf-main-integration-discovery-20261012-01` files are synthetic test evidence explicitly supplied for this investigation.

## Plan and progress

1. Coordinate Ohm's exact prior sequence and inspect current production finalization (done).
2. Add a meaningful reproduction through the complete real finalization sequence, with valid and bogus citation controls.
3. If the failure is a fixture-stage omission, correct only this owned test; otherwise capture red, apply a bounded production fix, then rerun.
4. Capture guarded evidence, source hashes and independent review of any production change; report publication proof separately from API/export isolation.

## Evidence and updates

- 2026-10-12: Requested prior fixture call order from Ohm (`01a12bdd-912c-7702-a15b-8973e00da94f`). Located the synthetic report, its actual citations/audit files and the current E2E test. No application import or production change yet.

## Findings and current implementation

Ohm confirmed the discovery fixture omitted deterministic lint and stabilization. That omission explains its final `lint.changed` hard failure, but it does not explain away the caption loss. The complete real production order reproduced a separate defect: initial lint reduced two identical chart attributions to one, semantic citation repair stripped the remaining valid marker, and the stabilized report then passed the final audit with no chart citation left.

Only `backend/app/services/report_agent.py` has a production patch. Generated chart source lines are now repeatable figure metadata; their complete provider/URL/tag/unit/frequency/adjustment parts are checked against the canonical official-data carrier and current source index. Generic URL metadata still cannot support arbitrary prose. Canonical metadata—including numeric index-base years—is preserved by quantitative repair, while all markers and semantic checks still inspect the complete report body. Mixed indexed/unindexed attributions preserve legitimate tags without inventing missing ones. The final read-only audit binds embedded official figures to manifest provenance and their canonical captions; stripping a bogus marker cannot make a missing attribution publishable. Renderer, visualizer, pipeline, runner, shared helpers and report_lint remain untouched.

## Evidence ledger

- `/private/tmp/drf-report-publication-red-v1`: four fixture setup errors because an optional Config flag was not declared. Corrected fixture setup only; this is not behavioral red.
- `/private/tmp/drf-report-publication-red-v2`: one behavioral failure and three passes. Actual charts and the production lint/stabilize/audit sequence changed S1 counts from two to one to zero; final audit and real publishability nevertheless passed. `publication-stages.json` preserves the before/after Markdown and audit.
- `/private/tmp/drf-report-publication-units-red-v1`: real multi-series captions lost “Chained 2017 Dollars” and their citations in quantitative repair. `/private/tmp/drf-report-publication-unindexed-red-v1`: a canonical unindexed neighbor caused a legitimate indexed dashboard citation to be stripped.
- `/private/tmp/drf-report-publication-attribution-red-v1`: bogus S999 markers were removed by normal repair, after which the broken chart attribution was silently accepted. The new final caption-integrity check closes this boundary.
- `/private/tmp/drf-report-publication-green-v3`: eight focused cases passed. This includes real PNGs, exact source-ledger-shaped rows, complete lint/stabilization/final-audit ordering, no publishability bypass, mixed/numeric-unit attribution, bogus-marker rejection, and a structured forecast with ten normalized synthetic binaries, enabled publish gate, and real Flask detail/download/chart responses.
- `/private/tmp/drf-report-publication-compat-v1`: 204 tests passed across publication, official data, bilingual, citation lint, repair/reflection, market evidence and visualization API suites.
- Added metadata-tamper controls rejected changed units, frequency, URL and extra factual prose. Extra prose was correctly rejected by the earlier quantitative convergence gate; its initial test expected the later caption-specific error too narrowly. This is a test-expectation correction, not a relaxed production guard.

## Independent review and remaining work

Reviewer `01a12be7-fa2d-7543-9573-c1449f529942` confirmed the canonical attribution approach, mixed-unindexed fix and numeric-metadata handling. Its final P2 finding was that the new caption scan, unlike the initial marker scan, did not skip fenced examples. `/private/tmp/drf-report-publication-fence-red-v1` reproduced both errors: example-only attribution incorrectly passed, and a real caption plus its fenced example incorrectly failed. The caption scan now uses the existing Markdown fence parser before heading/caption checks. Independent static review closed with no remaining P1/P2 findings; the reviewer did not run tests or edit files.

## Final verification and freeze

**210 tests passed in 9.20 seconds** in `/private/tmp/drf-report-publication-final-v1`: 14 new publication scenarios and 196 existing official-data, bilingual, publication-barrier, citation-lint, repair/reflection, market-evidence and visualization-API checks. There were no skips or failures. `source-freeze.json` records the full command and before/after hashes, with `drift=[]`; a subsequent check also found no drift. `completed.json` confirms exit zero, complete shutdown, preserved identity variables and no tracked source drift. `junit.xml` and `test-output.txt` preserve the results.

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-report-publication-final-v1 -q backend/tests/test_report_data_publication.py backend/tests/test_report_official_data.py backend/tests/test_report_bilingual.py backend/tests/test_report_publication_barrier.py backend/tests/test_report_lint_citations.py backend/tests/test_report_repair_and_reflection.py backend/tests/test_report_market_evidence.py backend/tests/test_report_viz_manifest_api.py
```

Repeat only with a fresh nonexistent evidence directory. The guard recorded two blocked font-discovery subprocess probes, eighteen blocked font-directory reads and three blocked `os.kill` attempts in the broader test lifecycle. No network, credential-path or saved-data attempts were recorded. This is a CPython audit boundary, not an OS sandbox.

The structured positive case has **two scenarios, ten normalized synthetic binary forecasts, structured forecast required, publish gate enabled/passed, and two official chart captions checked/passed**. It calls the real final audit, `ReportManager.publication_status`/`is_publishable`, and Flask detail/download/manifest/PNG endpoints without a publication override or fabricated passing audit. The forecast probabilities are fixtures; this is deterministic publication proof, not model-quality or live-generation proof. Its `final_audit.json` records Markdown SHA-256 `be4c591aa7fa209aa5f0ec46083b92e890ef46a213144a2756f3a27dad23a245` and forecast SHA-256 `0aefbddc5129baf01e2ca51d161578470f6c23d48074faf36ec1712acdcd6505`.

The negative cases reject nonexistent S999, a real but mismatched S2, changed URL/units/frequency, added factual prose, missing attribution after citation repair, and fenced-only attribution. A legitimate caption plus its fenced example remains publishable. The original missing-stabilizer case is separately characterized; duplicate ordinary prose continues to require stabilization and is not exempted by the fix.

| Exact changed path | Final SHA-256 |
|---|---|
| `backend/app/services/report_agent.py` | `9fa39c55ff1ef585d1ca81e98efa11ecccf201e00e2ab5affc158512bdecab13` |
| `backend/tests/test_report_data_publication.py` | `dc6ecb67e5303698bc220f43ecab6ccc9caa232af976ca622e4d29a783ba263c` |
| `docs/handoff/main-quantitative-integration-20261012/report-data-publication.md` | This final documentation record |

`report_lint.py` was not changed (SHA-256 `a42a0ebe793bfb1a7cebcebba21f330e886752be5755b142ce48722a87341a83`). Renderer, visualizer, forecast extractor, pipeline, providers and runner remained frozen. `ruff check --target-version py311` passed for report_agent.py, report_lint.py and the new test.

## Handoff and limits

Ohm and the lead received the production freeze hash and green/review results. The local 210-test receipt above is distinct from the separately owned integrated transport/research/promotion/export run; its subsequent verified completion is recorded below. No saved reports were replayed or modified; no live provider/model calls, dependency installs, restarts or commits occurred.

Next-session prompt: "Use report_agent.py at the recorded freeze hash, preserve unrelated main changes, and run the coordinator-owned integrated report flow through initial lint, stabilization, final read-only audit and save before testing APIs/exports. Keep real publication checks enabled. Treat figure attribution as exact canonical metadata, never a blanket exemption for Source lines or arbitrary facts. Re-run the focused publication suite if this boundary changes."

- 2026-10-12: Final 210-test acceptance and zero-drift source freeze captured; independent review closed, Ruff passed, and Ohm/lead notified to resume integrated verification. Only the three owned paths listed above changed.

## Verified integrated no-bypass completion

Independently read Ohm's `completed.json`, JUnit and `official-data-end-to-end.json` under `/private/tmp/drf-main-official-e2e-no-bypass-final-20261012-01`. The single integrated case passed with no failures/errors/skips. It uses actual MCP SDK transport to the synthetic fixture server, real stored-data research/promotion/chart paths, and the complete report sequence `lint → stabilize → enforce final audit → save`.

The receipt explicitly records `bypass_applied=false`, real `publishable=true` with no reasons, ten normalized binary forecasts, structured forecast required/valid, and the publish gate enabled/passed. Both official captions pass their integrity audit and the body retains exactly two S1 markers; citations.json and References agree. Real Flask detail/download/PNG/manifest handling and report/dossier exports passed. No model or graph-service calls occurred.

All 21 before/after source hashes agree. The integrated test hash is `b6c11fc9eafb1227dddf75bb0c8ee0d2a4a11df77c996b5055d6cc86f9fcd64d`; report_agent remains `9fa39c55ff1ef585d1ca81e98efa11ecccf201e00e2ab5affc158512bdecab13`. Both guarded children exited zero, shutdown completed, and identity variables were preserved. Recorded denied attempts include font discovery and two process-group cleanup calls; these are not described as zero probes. No production bytes changed in this confirmation.

- 2026-10-12: Verified and recorded the independently executed integrated no-bypass result. The publication boundary is closed through APIs and exports for the synthetic acceptance scenario; live provider/model quality remains outside this proof.
