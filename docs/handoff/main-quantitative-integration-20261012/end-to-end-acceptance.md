# Official data end-to-end acceptance

Status: Complete for the owned integrated acceptance. The final real-publication chain passed with no admission bypass, through actual MCP transport, research promotion, report finalization, Flask APIs and demo export. The final receipt below binds all 21 selected source files. Earlier bypass and hub-hold records are historical. Whole-project acceptance remains lead-owned. Main working bytes and integration-contract.md are authoritative. Ownership is limited to this report, backend/tests/test_official_data_end_to_end.py and backend/tests/fixtures/official_data_mcp.py, plus the earlier explicitly authorized `_kiq_task` compatibility correction described below. No production source was changed during this final publication upgrade.

Publication upgrade: after the owner froze report_agent.py at `9fa39c55ff1ef585d1ca81e98efa11ecccf201e00e2ab5affc158512bdecab13` with 210 passing publication/compatibility cases and closed static review, the candidate ran the complete `_apply_report_lint` → `_stabilize_publish_markdown` → `_enforce_final_publish_audit` → `save_report` sequence. `/private/tmp/drf-main-official-e2e-publication-candidate-20261012-01` passed one case and proved actual publishability, ten normalized synthetic binaries, structured-forecast validity, publication-gate success and both S1 captions before any legacy override. Only after that proof was the override removed. The subsequent final run below exercises real admission in every API/export check.

## Current final acceptance — real publication without bypass

Evidence root: `/private/tmp/drf-main-official-e2e-no-bypass-final-20261012-01`. **One integrated test passed, zero failures/errors/skips, in 4.28 seconds.** There is no `ReportManager.is_publishable` patch in the final test. `official-data-end-to-end.json` records `mode="real publication; no admission bypass"`, `bypass_applied=false`, actual `publishable=true` with no reasons, and the complete real audit. The structured forecast is required and valid (two scenarios, ten binaries); the professional publication gate is enabled and passed with no issues. Both official-chart captions pass the manifest-bound check and the body retains exactly two S1 markers.

The real Flask detail response exposes the exact published Markdown; download returns its exact bytes; the visualization-manifest response preserves producer items/captions/provenance; and every official PNG response matches its file bytes. Actual report and dossier exporters preserve PNG bytes, rebased paths, source captions, citations and all Markdown text apart from the prescribed path prefixes. The research promotion seal and visualization manifest remain unchanged by publication, serving and export. The real final audit remains unchanged after API/export operations. Model and graph call counts are zero; the synthetic provider transcript has one tool call, with the repeated data_get served from durable run evidence.

All 21 recorded source hashes match before/after; runner `source_drift=[]`. The exact final test SHA-256 is `b6c11fc9eafb1227dddf75bb0c8ee0d2a4a11df77c996b5055d6cc86f9fcd64d`; fixture remains `21fafc475c656af79572c7e949253596bd76b30519c868d30bde49ce7a7b1e57`; report-agent SHA matches the approved freeze above. No source/test edits followed this receipt; only this report was updated. All other tested hashes are in the integration JSON.

`completed.json`, `junit.xml`, the integration JSON, and child receipts `process-62134.json` / `process-62135.json` were inspected. Both allowed children exit zero, complete shutdown, preserve identity and record no blocked child operations. Parent activity includes two denied font/metadata subprocess probes, eighteen denied font-directory reads and two denied process-group cleanup attempts. These remain explicitly nonzero blocked attempts; no network, credential or saved-data attempt is recorded. Parent identity and shutdown checks pass.

The final detail PNG was visually inspected after adding structured forecasts. It retains the two genuine missing-data gaps and the stored historical line, while displaying synthetic model thresholds as separate red dashed lines and an explicit forecast horizon. Its SHA-256 is `eb3b1a7b05e696a6c5dee94c840e8c003ebaecb0d09b4dade9bf17a5472b7476`; its demo copy and HTTP response have identical bytes. The overview and research PNGs retain the previously inspected hashes `58fbc0e3a1199bff975a67d897bdd30bd14699ffad969ae04f35e8eee5114c54` and `f7d9f8e3ef9234f02299f77ad7e77a6d3c9cca4fb15f4953e5028124611ba8ff`. Final paths, HTTP hashes and export locations are indexed in the receipt. These remain synthetic test forecasts, not live model/provider quality evidence.

Reproduction (choose a new nonexistent evidence directory for another run):

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-main-official-e2e-no-bypass-final-20261012-01 \
  --allow-python-script backend/tests/fixtures/official_data_mcp.py \
  --allow-python-script deerflow_bridge/skills/data-visuals/scripts/render_data.py \
  -q backend/tests/test_official_data_end_to_end.py
```

The lead and publication owner were notified of this final no-bypass receipt and exact test hash. The sections below preserve prior investigation/isolation evidence and do not describe an active bypass or hold.

The approved scenario connects a synthetic FRED stdio server through the real McpHub, DataSources, V3 data_get/source ledger, dataset persistence and pages, research renderer, research promotion/seal, backend carrier loader, ReportAgent and ReportVisualizer. It must produce real research and report PNGs from the same stored observations. Only unrelated model/graph dependencies may be replaced. No network, live model, saved-run access, service operation, installation or production edit is allowed.

The lead subsequently accepted the images and extended this same single test through the real Flask report visualization-manifest and chart-asset endpoints, then through the demo exporter. The original small real-audit attempt failed in the lead's broad discovery run; details follow. The final extension uses the expressly authorized **ReportManager.is_publishable-only bypass**, scoped to one synthetic report ID with no translations. Actual ReportManager.save_report/get_report, Flask handlers, exporters, persistence and renderers remain real; no passing audit is manufactured, and the receipt records actual non-publishability before the bypass. It asserts exact manifest fields, PNG response bytes, copied report and research images, rebased paths and preserved captions/citations. All generated reports and demo files stay under the test's scratch directory. One extended-chain run was launched after the documented API/render/hub freeze, with the passing result below; no repeated intermediate extended-chain runs were launched.

## Historical API/export isolation receipt — superseded by real publication

`/private/tmp/drf-main-official-e2e-api-export-20261012-01`: **one test passed, zero failures/errors/skips in 4.80 seconds**. The actual Flask `/api/report/report_official_data/viz-manifest` response preserves all original items and skipped reasons; each chart asset response has `image/png` MIME and the exact source PNG bytes. Actual `export_report` and `export_dossier` copy those PNGs byte-for-byte into scratch namespaces. Reversing the prescribed link prefixes recovers the entire original report/dossier Markdown, proving caption, citation and prose preservation. The two source-caption lines both retain S1. Report and promoted research manifests remain unchanged by serving/exporting.

The authoritative index is `official-data-end-to-end.json` in that evidence root. It records 21 unchanged before/after source hashes, HTTP asset hashes, exported paths/languages/captions, actual pre-bypass nonpublishability, zero model/graph calls and unchanged identity variables. `completed.json`, `junit.xml` and child receipts were inspected. Parent: two allowed children; two denied metadata/font subprocess probes, eighteen denied font-directory reads and two denied process-group cleanup attempts. MCP PID 43951 and renderer PID 43953 both exit zero, finish shutdown and record no blocked child events. No network, credential or saved-data attempt is recorded.

Tested hashes: test `f5a28e6a6281184e8c093a2476f2c8c08e3f27c84739a896c2217b2219f217d8`; fixture `21fafc475c656af79572c7e949253596bd76b30519c868d30bde49ce7a7b1e57`; narrow linear-research patch `c4bd06148dbb341d804482a04352b1351c5baf3c0c6446ea931408ff0c6d42d6`; hub `010c1c0841a9173bf4d418050453fad4d5033f56a02994cb9de93f5222925765`; API `419663c3bbd0d1a790212ed229023b6f5b171e9e74adecff16adc4b04f001511`; renderer `6da38d8598753c28f7d6bb50a81c912892990162b0113f841fe65c5c27707136`.

All three PNG hashes match the lead-approved, visually inspected image bytes. The current artifacts live under `.../pytest-tmp/test_guarded_mcp_to_promoted_r0/`: research PNG in `research/charts/`; report PNGs in `reports/report_official_data/charts/`; identical demo copies in `site/demos/official-data-fixture/{charts,research-charts}/`. The exporter publishes Markdown/assets, not an invented extra visualization JSON file; API item equality and image hashes bind the same original manifest to the exported files.

Historical sequence: after this run, the lead reopened hub review and temporarily held further transport gates. On the latest lead update, that hold is lifted: replacement hub `0b65ca3e` has closed review, guarded 173-case verification and native 13-case replacement verification. Those replacement results are reported by the lead, not newly rerun by this worker. The receipt above remains evidence for its captured `010c1c` snapshot, not proof that it ran against the replacement. The lead will include this test in the combined gate after GB1 and publication review; no duplicate E2E run is planned here. The independent static review of the API/export isolation found no blocking authenticity issue. Actual report publication remains excluded from this bypassed test's claim.

## Discovery compatibility correction and publication boundary

The lead authorized one additional production edit: `_Engine._kiq_task` in `deerflow_bridge/linear_research.py` now returns its original web-only task when `getattr(self, "data_enabled", False)` is false. This avoids touching all data-only attributes on preexisting SimpleNamespace callers and leaves the enabled full-engine path unchanged. Meaningful red is the existing failing `test_research_engine_v3_text.py::test_kiq_task_seed_rows_are_delimited_untrusted_data` in `/private/tmp/drf-main-integration-discovery-20261012-01`. Focused green `/private/tmp/drf-main-v3-kiq-compat-20261012-01` passed that test plus disabled/enabled official-data controls: **3/3**, no blocked attempts, preserved identity and completed shutdown. No existing tests were edited.

The discovery receipt also records the integrated test reaching real publication audit and failing `hard_passed` solely on deterministic lint readiness. Its scratch `reports/report_official_data/full_report.md` confirms that real citation finalization removed both generated S1 caption markers; `final_audit.json` records `duplicate_sentences_removed=1` and `lint.changed=true`. This was immediately reported to the lead. Stabilization alone cannot prove caption/citation preservation because it may delete the duplicate attribution line. No report/lint production edit is authorized to this worker. The allowed admission-only bypass therefore isolates the requested API/export boundary while preserving the original real renderer captions and their assertions. This acceptance will not claim to fix or validate that publication defect.

### Exact handoff sent to McClintock

Sent directly to `01a12bdd-924f-7f33-b8e0-bf7a6849d591`, as requested by the lead. Failing test SHA in discovery is `c9d48eedcde5120ed7984350212bc0187622f2f1fd71b3aa65198de0cf62b4cd`; the current test differs because it now isolates admission. The original body is preserved in discovery `junit.xml` at the failure on the `audit["hard_passed"]` assertion.

Failure artifact base: `/private/tmp/drf-main-integration-discovery-20261012-01/pytest-tmp/test_guarded_mcp_to_promoted_r0/`.

- `promoted/sources.json` and `promoted/data/datasets.json`, plus the manifest-referenced series file.
- `reports/report_official_data/viz_manifest.json`.
- `reports/report_official_data/official-data-acceptance.md`: original renderer/placement output, two S1 source-caption lines.
- `reports/report_official_data/full_report.md`: after citation finalization, both markers removed.
- `reports/report_official_data/final_audit.json`: actual failed read-only audit.

Exact order after carrier/PNG production: `_place_visualizations` → write `official-data-acceptance.md` → set `REPORT_STRUCTURED_FORECAST=False` → construct completed Report → `ReportManager.save_report` → `agent._finalize_citations_for_publish` → `ReportManager.save_report` → verify not yet publishable → `agent._audit_final_published_markdown` → failing hard-pass assertion. **The fixture omitted `_stabilize_publish_markdown` and preceding deterministic lint**, and did not execute full `generate_report`. This omission must be distinguished from the independently observed caption-marker loss before deciding on a production patch.

Both original captions were `Source: [fred](<https://fred.stlouisfed.org/series/UNRATE>) [S1]; Percent; M; SA`. Both finalized captions omit `[S1]`. The sole source has title `Synthetic Unemployment Rate`, origin `official_data`, tier S1, `dataset.series=fred:UNRATE`, Percent/M/SA, and file `data/fred_unrate_9d03984317fdea12.e57d4d23f8e34a28.json`. Its `content_sha256` is `090472b5094e5cb8952a5b27afc060c9bfdd37cb81b0c625fa2372f934d4bd0b`; it has a numeric summary excerpt, not a full `content` field. The report visualization manifest retains S1 in both `source_caption` and provenance.

The audit has `read_only=true`, `disk_matches_memory=true`, `hard_passed=false`, and the sole hard issue `最终 Markdown 在发布后仍会被确定性编辑 lint 改写`. It reports zero remaining citation markers, `uncited=["S1"]`, empty citation artifact tags, zero semantic checks, and `duplicate_sentences_removed=1`. At handoff, the separate publication owner was to distinguish the omitted fixture stage from a production defect. The lead now reports that McClintock reproduced actual caption loss through the full stabilization sequence: the audit can pass with S1 absent, and a narrow production patch is underway. This worker made no report/lint changes. The admission-only bypass stays explicitly scoped to API/export delivery; replacing it awaits publication-regression proof and a subsequent lead instruction.

The extension's independent static review found no blocking authenticity issue after that explicit boundary decision. Bypass declaration and the real pre-bypass nonpublishability are recorded before handler/export work so failed-run evidence is also clear. The final receipt points to and hashes `full_report.md`. Dossier export has the same full-text restore-prefix comparison as report export, preserving captions, references and prose. The API/export runtime pass is the recorded isolation receipt above; it does not establish production publication admission.

Acceptance will record current source hashes before/after, MCP request arguments and child identity, artifact hashes across promotion, citation/units/gap consistency, model-call count, renderer outputs and guard receipts. The actual PNGs will be visually inspected. Any boundary failure will be reported immediately and preserved without editing production outside ownership.

## Progress

- Read current integration contract, source promotion tests and report/data transport tests. Confirmed main and that the three newly owned paths did not exist.
- Reuse the frozen guarded runner with only the new fixture script and existing data renderer explicitly allowed. One integrated test will own a fresh synthetic artifact tree.

## Executed evidence

The first run passed the one integrated test in 3.92 seconds. Evidence root: `/private/tmp/drf-main-official-e2e-20261012-01`. `completed.json`, `junit.xml`, both child receipts and `official-data-end-to-end.json` were inspected. The latter records all sixteen source hashes before/after, the actual child request and response digest, dataset carrier, promotion seal/files, chart paths and hashes, and zero model/graph calls. Sources were unchanged throughout the run; identity variables and shutdown were preserved in parent and children.

Final strengthened acceptance: `/private/tmp/drf-main-official-e2e-20261012-02` passed **one test, zero failures/errors/skips** in 4.42 seconds. Independent review identified two narrow assertion gaps, now closed: the full ordered fixture date/value sequence is independently checked before and after promotion, and promoted research captions/source IDs plus source-series/file/page-hash identities are asserted explicitly. The real ReportVisualizer panel's dates and historical values also match the complete expected sequence. Its JUnit, completion, child receipts and integration receipt were inspected. All sixteen source hashes remained unchanged. Current test SHA-256 is `53780c9abc0d046d5d116158656ecc7dc769d43f0382aed91d624ad67d7dcac0`; fixture SHA-256 is `21fafc475c656af79572c7e949253596bd76b30519c868d30bde49ce7a7b1e57`.

Latest acceptance after the renderer owner's changes: `/private/tmp/drf-main-official-e2e-20261012-03` passed **one test, zero failures/errors/skips** in 4.02 seconds. Before/after hashes are unchanged for all sixteen files; renderer SHA-256 is `ff11c5f3a606a0165af1e36b26405fc271af4630e33cf642ebb6d5e6ba2daeeb`. Test and fixture hashes remain those above. All three PNGs are byte-identical to the visually inspected images. This refresh supersedes `-02` for the current renderer and retains the same complete chain and assertions.

**Final captured acceptance:** `/private/tmp/drf-main-official-e2e-20261012-04` passed **one test, zero failures/errors/skips** in 3.85 seconds after further shared-source changes. Its sixteen before/after hashes match. The tested DataSources SHA-256 is `e46a9779789f71d71f746ebe6f60d3eb305fdf4d0492011e45942e47f5b841a4` and renderer SHA-256 is `3213114685dab6f7b6a6a3791db7a4ecfdb43fb62474ccccda426e47758ca4a6`; immediate post-run reads matched both. Test and fixture bytes remain unchanged. Independent review verified this receipt, source stability, child completion and the strengthened assertions, and approved closure of the test/fixture scope. Subsequent production changes and the all-slice final freeze remain the coordinator's responsibility; no claim of an indefinitely frozen shared checkout is made.

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-main-official-e2e-20261012-04 \
  --allow-python-script backend/tests/fixtures/official_data_mcp.py \
  --allow-python-script deerflow_bridge/skills/data-visuals/scripts/render_data.py \
  -q backend/tests/test_official_data_end_to_end.py
```

Use a fresh nonexistent canonical evidence directory for another run. The fixture is a real low-level MCP server using the installed SDK. It exposes the native FRED `fred_get_series` schema and JSON text content. McpHub launches it as a separate guarded child, initializes it and lists/calls its tool. DataSources parses that actual transport result. No API, transport, persistence, promotion, or rendering method is replaced.

The scenario uses eighteen invented monthly values, including two explicit gaps. It verifies one actual MCP request (the second data_get is a stored read), binds the native response digest to DataSources provenance, and validates the exact source page/hash. It closes the provider client before publication. V3's actual publication methods persist the root datasets, invoke the real research chart subprocess, embed the chart and remap ledger S2 to published S1. Real research promotion copies the manifest-listed bytes into a validated seal. The backend loader returns an identical carrier, which can regenerate the original source-page bytes. The scratch V3 page is not artificially copied into the published tree by this test.

ReportAgent receives that exact promoted carrier, renders its data context and passes the same object through `_collect_viz_artifacts`. ReportVisualizer creates real PNGs using the production static-chart configuration; `_place_visualizations` embeds existing paths and the final citation. Report rendering leaves the promoted seal valid and unchanged. Only model and graph dependencies use no-call sentinels. This scenario does not test freeform LLM narrative generation, live FRED availability, other provider transports, or report deployment.

### Images inspected

All paths below are relative to `/private/tmp/drf-main-official-e2e-20261012-01/pytest-tmp/test_guarded_mcp_to_promoted_r0/`:

- `research/charts/data_fred_unrate_9d03984317fdea12.png` and its byte-identical promoted copy.
- `report/charts/official_series_tdkntsonlrfdealm.png`.
- `report/charts/official_indicators.png`.

Visual inspection confirmed the synthetic title, percent units, monthly/seasonally-adjusted context, matching plotted values, visible breaks for August 2024 and February 2025, and the latest value of 4.2 percent in June 2025. Report Markdown carries the source URL and S1 reference. No interpolation bridges either gap. Both report PNGs are distinct real outputs (overview and detail), though the single-series input naturally gives them similar plots.

### Guard activity and boundary observations

The parent allowed exactly two guarded child launches: synthetic MCP server PID 631 and research renderer PID 661. Both returned zero and have successful child receipts with no blocked operations. The parent blocked two font/metadata subprocess probes (fc-list and system_profiler), eighteen font-directory reads, and two `os.killpg` attempts during MCP shutdown. Those cleanup attempts were denied; the actual child still exited zero, the hub reported closed, and final shutdown completed. This is a recorded guard/lifecycle limitation, not zero-attempt evidence. No network, credential or saved-data attempt appears in the receipts. No functional data/promotion/report boundary failure was reproduced, and no production edit was made.

The final run has the same guard counts; its children are MCP PID 6790 and renderer PID 6791. Both exit zero, preserve identities, finish shutdown and record no blocked child operations. Final PNG hashes match the corresponding visually inspected first-run files exactly; copies under the final `...-02/pytest-tmp/test_guarded_mcp_to_promoted_r0/` tree are therefore the same inspected image bytes.

Run `-03` likewise has the same parent guard counts. Its MCP child is PID 11337 and renderer child is PID 11338; both returned zero with completed shutdown and preserved identity. The corresponding `-03` image tree contains the same inspected PNG bytes and is the preferred current artifact set.

The final `-04` receipt has the same parent guard counts, no source drift and successful shutdown. Its MCP child PID 12849 and renderer child PID 12851 returned zero with preserved identities and empty event maps. All three final PNG hashes were directly recomputed and match the original inspected image bytes. Prefer `/private/tmp/drf-main-official-e2e-20261012-04/pytest-tmp/test_guarded_mcp_to_promoted_r0/` for the delivered image artifacts. The final integration JSON records their absolute paths/hashes and is the authoritative evidence index.

## Compatibility exclusions to document

| Exact prior excluded node ID | Reason | Smallest safe fixture solution |
|---|---|---|
| `backend/tests/test_research_gateway.py::test_r3_neutralize_is_linear_on_whitespace_runs` | `_r3_isolated("whitespace")` launches Python `-c`. | Use one exact, hashed Python probe script with an argparse choice `whitespace`; reuse `_r3_timing_probe` and keep existing timing assertions/timeouts. |
| `backend/tests/test_research_gateway.py::test_r3_fetch_and_search_of_whitespace_padded_text_stay_fast` | `_r3_isolated("tools")` launches Python `-c`. | The same script, bounded choice `tools`. |
| `backend/tests/test_research_gateway.py::test_r3_passage_and_reasoning_regexes_are_linear` | `_r3_isolated("boilerplate")` launches Python `-c`. | The same script, bounded choice `boilerplate`. |
| `backend/tests/test_research_gateway.py::test_r3_quantity_detection_is_linear_on_long_digit_runs` | `_r3_isolated("quantity")` launches Python `-c`. | The same script, bounded choice `quantity`. |
| `backend/tests/test_research_engine_v3.py::test_main_dispatches_research_engine_v3_end_to_end` | `restore_environ` teardown calls `os.environ.clear()`, attempting to delete protected identity variables. | Restore changed non-identity keys individually; assert HOME/home/CODEX_HOME/USERPROFILE stayed identical and never set/delete them. Preserve the real main-dispatch scenario. |

The timing replacement should be a single repository fixture such as `backend/tests/fixtures/research_gateway_timing_probe.py`, explicitly allowed through `--allow-python-script`. It should accept only the four literal case names, call the existing probe, emit JSON and execute under the runner's guarded child interpreter. Do not permit `-c`, arbitrary executable strings, shell commands or general dynamic Python input. This retains process isolation and the original performance tests without widening the guard. These are recommendations only: no additional fixture or existing-test edit was made in this task.
