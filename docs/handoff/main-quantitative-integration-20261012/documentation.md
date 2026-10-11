# Data-MCP integration documentation

**Last updated (UTC):** 2026-10-11T19:47:01Z
**Status:** Complete; generation-binding addendum closed after caller review.

## Request, ownership, and acceptance

Document the approved current data-MCP integration in `README.md`, `README.zh-CN.md`, and `.env.example`, plus this owned report. Preserve unrelated content and concurrent edits, including the existing authorized example foundation. No implementation changes, private `.env`/secret reads, provider calls, deployment, dependency installation, or Git operations belong to this sidecar. The user approved the plan and explicitly authorized coordination with McClintock.

Acceptance is met by matching EN/ZH descriptions of six-provider retrieval; v3 planning/prefetch and legacy permission-aware tools; persisted quantitative sources and both report chart paths; disabled/unavailable/resumed modes; exact-period anchors and conservative availability; SEC/projection/normalization limits; setup/configuration; and the actual IMF default timeout. All changed defaults/behavior were checked against current source and independently rereviewed.

## Changed sections

| Owned file | Changed sections |
| --- | --- |
| `README.md` and `README.zh-CN.md` | Architecture producer/consumer table; new Stage 1 official quantitative-data subsection; research artifact table; Stage 6 optional `data_anchor`, official chart family and best-effort format handling; installation/data-server maintenance; official-data configuration and credential table. |
| `.env.example` | Official-data section only: fresh-run/resume/error behavior, actual IMF timeout, bridge call budgets, working chart controls, normalization/availability/SEC limits, credential-header comments. Existing credential placeholders and unrelated sections remain intact. |
| This report | Scope, changed sections, source map, audit/correction history, coordination and independently verified receipts, validation and remaining boundaries. |

No other file was edited by this documentation sidecar.

## Source references

Function names are stable locators; line numbers can shift under sibling source changes.

| Topic | Source references inspected |
| --- | --- |
| Configuration and transport | `backend/app/config.py:1477`–`1498`; `deerflow_bridge/data_mcp.py:72` provider IDs, `:79` IMF minimum, `_call_timeout_from`, `default_server_specs`, `McpHub.call`. |
| Setup and assembly | `package.json` `setup:datamcps`; `scripts/setup_datamcps.sh` build/check/force/skip recipes; `setup.sh:599` module assembly and `:747` data-server step; `runtime_skill_sync.py` required skills. |
| Provider fidelity and normalization | `deerflow_bridge/data_sources.py` `Series.__post_init__`, `search`, `_finish`, `_fetch_fred`, `_fred_csv`, `_bls_quota`, `_bls_batch`, `_fetch_imf`, `_fetch_wb`, `_fetch_usgov`; `data_catalog.py` canonical grammar/recipes. |
| Persisted evidence | `data_sources.py` `load_datasets`, `write_dataset_files`, `load_official_data`: immutable JSON/CSV generations, hashes, source/transform identity and bounded loading. |
| v3 planning/tools/citations | `linear_research.py:4027` budgets, `_configure_data`, `phase_data`, `_prepare_data_exhibits`, `_finalize_data_citations`; `research_gateway.py` `AGENT_TOOLS_WITH_DATA_SCHEMA`, `_reserve_data`, `data_get`. |
| Legacy tools/permissions/citations | `deerflow_research.py:4964` `_register_legacy_data_tools`, `_official_data_prompt_block`, `_finalize_data_series`, `_render_data_charts`, `_prepare_legacy_data`; `data_tools.py` `_run`, `_capture`, `_limit`. |
| Runtime procedures and research figures | `deerflow_bridge/skills/data-sources/SKILL.md`, its series catalog, `skills/data-visuals/SKILL.md`; actual `skills/data-visuals/scripts/render_data.py` `_default_max`, `_parse_args`, `main`, `_drop_stale_rows`, `_select`, `_compare_groups`. |
| Forecast context and figures | `official_data.py` `historical_snapshot`; `report_agent.py:2286` `_build_data_pack` and prompt consumers; `forecast_extractor.py:1521` `official_observation_kind`, `:1587` `_data_anchor_matches_binary`; `report_visualizer.py` `_run_official_data` and `build_all`; orchestrator carrier wiring. |
| Resolution and availability | `data_sources.py` `validate_data_anchor`, `_period_complete_at`, `resolve_data_anchor`; `backend/scripts/resolution_monitor.py:353` `resolve_official_forecasts`: exact-period queries, post-fetch implicit cutoff, unchanged explicit cutoff, dry-run and typed outcomes. |

## Audit findings and coordinated fixes

The following chart descriptions are **pre-fix history**, superseded by the verified behavior below.

1. The IMF transport minimum was already 120 seconds, while the example and Config comment said 90. Docs/example now use 120; the user corrected the Config comment. General default remains 60 and Config minimum 5. The 900-second bound applies to the configured transport default only; explicit caller timeouts replace it and may be shorter or longer.
2. **Pre-fix:** `REPORT_DATA_CHARTS` had no production consumer. McClintock (`01a12bdd-924f-7f33-b8e0-bf7a6849d591`) wired the official chart builder to skip this family when false.
3. **Pre-fix:** zero research cap was clamped to one. McClintock implemented zero as disable and addressed the independently flagged matplotlib ordering edge. Zero now executes before dataset loading and its matplotlib requirement, removes only renderer-owned `data_` manifest rows, preserves files/foreign rows, and returns 2. Positive caps count single-series figures with at most two compatible comparisons extra; v3 embeds at most eight returned figures.

Temporary limitation wording was used while these fixes were pending. Final EN/ZH/example text now describes verified behavior. Report false retains other chart families and stored-data writer context, records `skipped.builder=official_indicators` with `reason=report_data_charts_disabled`, and fresh manifest generation drops old official rows. It does not promise a visible snapshot table in the finished report.

Independent reviewer `01a12c26-865b-7c22-bd88-4df30e870c14` identified seven further documentation corrections. Each was independently checked and corrected in both languages: all Data360 observations currently have unknown status and cannot automatically resolve; BLS excludes M13/Q05/S03 summaries while retaining native A01; native daily values become monthly available-value means with possible partial months and cannot automatically resolve; explicit timeouts can exceed the configured default; the forecast snapshot is writer context; official HTML/PNG pairing is best effort; and failed rebuilds can leave older usable outputs.

Final rereview accepted the README/example wording and EN/ZH meaning, including chart controls. Its remaining P3 was to supersede stale pre-fix/pending descriptions in this report; this final record does so while preserving the red history and update ledger.

## Behavioral red/green evidence

All three completed/JUnit records below were read directly.

| Evidence directory | Result |
| --- | --- |
| `/private/tmp/drf-renderer-controls-red-v1` | Exit 1; three behavioral failures, 74 deselected. Env zero and CLI zero rendered data charts; report false still produced official exhibits. |
| `/private/tmp/drf-renderer-controls-green-v1` | Worker green: exit 0; five passed, 74 deselected, zero failures/errors. Includes env/CLI zero × matplotlib present/absent and report false retaining the scenario chart. |
| `/private/tmp/drf-documentation-controls-green-v1` | Sidecar's independent current-byte run: exit 0; five passed, 76 deselected in 2.65 seconds, zero failures/errors. Extra deselections reflect the current test files. |

Exact independent command, from the repository root:

```bash
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-documentation-controls-green-v1 -q \
  backend/tests/test_data_visuals_status.py backend/tests/test_report_official_data.py \
  -k 'zero_chart_cap or data_charts_flag'
```

The red and worker-green commands use the same invocation with their respective evidence directory. Green receipts preserve identity and have no tracked source drift. They record two denied process probes (`fc-list`, `system_profiler`) and 18 denied font-directory reads; these are contained library discovery attempts, not zero probes. There are no network events. This CPython audit-hook boundary is not an OS sandbox; guards were not weakened and no child script was allowlisted for this focused run.

The runner does not automatically hash the dynamically imported renderer/report builder, so this sidecar separately hashed both production files, both test files and Config before its run and rehashed afterward. All five matched:

```text
47ec79476d0f0f1825a4c5cc888bd697676dafffd0eecaa781b9aa9f027ecace  deerflow_bridge/skills/data-visuals/scripts/render_data.py
7002f50d7249e40c93d31deace8359b06921d68c37575260052021867b821a92  backend/app/services/report_visualizer.py
ec4ddc09f3e25a3211c665a7aa37e0d37d2ebfdbbab9ac3ebfaa57b954ca45e6  backend/tests/test_data_visuals_status.py
bc31720149e31b4dd6390bead0c09b5b3de902f44515cdd0aa1b6302f94083c3  backend/tests/test_report_official_data.py
d431b5a0399a4f9306fd6f4cfadd0703e5e47bd9879ee608ee00faff23c4a1b1  backend/app/config.py
```

The control owner explicitly froze those control changes. Full renderer/report file review and later unrelated styling remain the implementation owner's acceptance boundary; this is documentation and focused-control evidence, not whole-integration acceptance.

## Documentation validation and preservation

| Check | Result |
| --- | --- |
| Standard-library AST/default checks, without importing the app | Exit 0: nine Config/example defaults, six providers, IMF default minimum 120, v3 budgets 24/3–50/4–90/5, legacy 50/4, explicit timeout override, working controls, setup and skill paths. |
| EN/ZH parity | Exit 0: 42 matching inline workflow tokens, 37 configuration tokens, and independent semantic rereview. |
| Markdown/links/whitespace | Exit 0: 52 balanced fence markers in each README, valid new local links/config anchors, no trailing whitespace. |
| Unrelated content | Exit 0: reverse only exact owned replacements in memory, then reproduce all three baseline hashes below. No restoration/write or Git operation was used. |
| `python3 backend/scripts/check_env_drift.py --strict --json` | Exit 0; `missing_from_env_example=[]`. Informational subprocess-only entries are source-backed; bridge budget keys are labelled as bridge reads. This default check does not read private `.env`. |
| `bash -n scripts/setup_datamcps.sh` | Exit 0. |
| Separate `bash -n setup.sh` | Exit 0. |

Baseline SHA-256:

```text
75dce808774bc92d9380af02104f07275eaf32276c3b5735d91b3a0ba2b1e0f0  README.md
0a8fd02f9d84a7b76ad67d5b9fd16c79eada4210351d0f7d09723861ae289fe9  README.zh-CN.md
d46d68b2ec2052df614f08e3bba144fc753141103715a2326211b89a48450b4f  .env.example
```

Final documentation SHA-256:

```text
829fa0b104e10363c60fbaedc12fff669de5f98baa13afdb61d4ccf327c39fb5  README.md
5a3a95945137001b61bb610c759f9114bf99a8bb4ef70501cf22085e658b2644  README.zh-CN.md
5a20add60d6c690c9fc3198d849b0de9c851ddecf39f57e47f6efdb32f69c041  .env.example
```

The first line patch could not match a substring inside a chart-table row; it left only the six preceding intended edits applied. Subsequent replacements were prevalidated for a unique occurrence before writing. Two report-only patches rejected stale timestamp contexts without applying changes; this final report was reconciled while preserving its update ledger. No implementation file was touched.

## Remaining work and practical limits

No remaining work for the previously accepted documentation slice. The generation-binding addendum below is now closed after caller-fix review. The owning integration session can review these four paths and rerun the recorded checks if implementation/defaults change. Full-file freeze/review and broader integration acceptance remain with implementation owners. Live provider availability, statistical release coverage and deployed behavior were not tested.

No application build was needed for documentation edits. The focused guarded code-control test was justified by the new accepted behavior described in the docs. README setup/build/check commands were documented, not executed; no private configuration, secrets, provider calls, installs, Git state or deployment was changed.

Suggested next-session prompt: “Read this documentation report and the four owned doc changes, preserve concurrent work, and reconcile documentation only if final reviewed implementation/defaults differ. Keep exact-period/historical-availability limits and EN/ZH parity. Do not infer whole-integration acceptance from the focused documentation control gate.”

## Final renderer acceptance update (2026-10-11T18:38:01Z)

The final renderer/status/fiscal/control evidence at `/private/tmp/drf-renderer-status-final-v1` supersedes the earlier statement that this slice's full-file acceptance was pending. This sidecar independently read `completed.json`, `junit.xml`, `source-freeze.json` and the owning `renderer-status-fix.md` report. The gate has **120 passed, zero failures/errors/skips**, exit 0, preserved identity, and a 12-file before/after freeze with `drift=[]`. All six current renderer-owner source/test hashes match that final freeze.

The final receipt includes four exact allowlisted renderer children; the missing-matplotlib compatibility child returned its expected exit 3. All five process receipts preserved identity and recorded no network events. The same two process probes and 18 font-directory probes remained denied attempts. The owning report records independent static-review closure with no remaining P1/P2. This sidecar verified existing evidence; it did not rerun or alter the implementation.

Final owner hashes relevant to this documentation:

```text
6da38d8598753c28f7d6bb50a81c912892990162b0113f841fe65c5c27707136  deerflow_bridge/skills/data-visuals/scripts/render_data.py
7002f50d7249e40c93d31deace8359b06921d68c37575260052021867b821a92  backend/app/services/report_visualizer.py
724163cde4fb9cbb7c5fe7f629e92f8bfcb521d1211087baadbc14c54691253d  backend/tests/test_data_visuals_status.py
87534390e82ff91d99e74fee2f5debc0b776a82878117909e3c2d9a3a6a5eddc  backend/tests/test_report_official_data.py
```

The report visualizer is byte-identical to the sidecar's focused control run. The renderer owner identifies the later renderer changes as legend-marker and blank-WEO policy refinements; the controls are unchanged, and final acceptance covers those refinements. README/example behavior remains accurate and their three final hashes above are unchanged. The exact final command, tests, lint-baseline limits and reviewer closure are in `renderer-status-fix.md` and the final `source-freeze.json`.

Broader current integration is still a separate coordinator gate: the owning report notes later shared MCP-hub/integration-contract changes after its freeze. This update claims final acceptance only for the frozen renderer/status/fiscal/control slice, not those later cross-slice bytes.

## Generation-binding addendum (2026-10-11T18:48:09Z) — closed after caller review

The user reported a new bounded caller fix under review and authorized a brief same-generation/manual-older explanation. Added one matching paragraph to each README after persisted evidence/citations. It explains PREPARE binding for primary/extra-seed simulations, association-first report/chat/context lookup, unavailable enrichment if a newer generation replaces the original handoff, and legacy dossier lookup without official data for older unbound simulations. No internal binding-file inventory was added to the user-facing README. No `.env.example` or implementation edit is needed.

Source inspected: `backend/app/services/official_data.py:83` `bind_simulation_research`, `:112` `simulation_research_binding`, `:164` `load_for_simulation`; `pipeline_orchestrator.py:7082` `load_research_dossier_for_simulation`, `:9128` extra-seed binding and `:13146` primary PREPARE binding; manual report/chat callers in `backend/app/api/report.py:378` and `:1552`; simulation context caller in `simulation_config_generator.py:624`; generation contract in `integration-contract.md`. The implementation checks the original report/actor/source/dossier/seal/dataset-manifest hashes, including explicit absence, rather than relying on a mutable path alone.

The supplied `/private/tmp/drf-main-generation-green-20261012-02` completed/JUnit receipts were independently read: **46 tests, exit 0, zero failures/errors, no tracked source drift, preserved identity**. Its tests cover official-data consumers/downstream and extra-seed callers. This is current green evidence, **not final caller-fix acceptance**; the user explicitly says implementation review is pending. Earlier renderer/status/fiscal/control acceptance and the existing documentation validation remain historical accepted evidence.

Current status: README addition drafted; actual caller/source review and EN/ZH semantic checks passed. Removing exactly the new paragraph from each README reproduces its previously accepted hash; both still have 52 balanced fence markers and no trailing whitespace, and .env.example is unchanged. Caller-fix review is now closed; no further documentation changes are required. Do not infer whole-integration acceptance or live provider proof.


Accepted addendum hashes (README bytes unchanged at closure):

```text
956d33f37f0177f4cc714ac3f6d82da56b98db8659615fd821ae2ec6af108d77  README.md
6db1da6ef9a6389b5f173620865026fc1c43d3c03f6a60e652958e9ef03c4548  README.zh-CN.md
```

## Generation-binding addendum closure (2026-10-11T19:47:01Z)

The lead confirms all caller/generation reviews are closed, including GB1 refusal of a changed generation before simulation creation and the independent 12/probe checks. The lead also reports the final 2025-test gate and the real published-report E2E passed. These final acceptance results are lead-supplied; this sidecar has not rerun or independently re-inspected those new final receipts. The earlier independently inspected 46-test receipt remains historical evidence rather than the final acceptance claim.

The generation-binding documentation addendum is now closed. Its previously checked README semantics remain unchanged. Per the lead's explicit instruction, only this owned report is updated: README.md, README.zh-CN.md and .env.example receive no further edits, documentation checks are not rerun, and Git/commit ownership remains with the lead. No remaining work for this documentation sidecar.

## Updates

- 2026-10-11T17:58:29Z: Created the owned sidecar report with scope, acceptance checks, plan, and baseline hashes.
- 2026-10-11T18:09:35Z: Completed source inspection, bounded bilingual drafts and initial source/default/parity/preservation validation, including the three concrete timeout/chart-control discrepancies. Recorded changed sections, source map and patch recovery. Independent review is in progress.
- 2026-10-11T18:14:18Z: User accepted the chart-control defects and authorized coordination with McClintock. Marked both limitations temporary, recorded supplied behavioral red evidence and intended zero-cap behavior, and retained accurate cutoff wording. Awaiting verified green fixes before final chart-control wording.
- 2026-10-11T18:26:21Z: Verified supplied red JUnit/completed receipts directly (three failures, preserved identity, no tracked source drift). Denied font/process probes are attempts, not zero probes. Source contains both narrow control fixes, pending green. Flagged zero-cap/matplotlib ordering to McClintock. Applied all seven independent documentation-review corrections in both languages and requested rereview; expanded the source map without changing implementation.
- 2026-10-11T18:33:08Z: Finalized the documentation record after independent rereview accepted EN/ZH/example wording. Recorded verified red/green controls, before/after source hashes, passing final static/parity/preservation checks, superseded pre-fix claims and preserved this full update ledger. Marked only this bounded documentation sidecar complete.
- 2026-10-11T18:38:01Z: Independently verified final 120-test renderer acceptance, current owned hashes and source-freeze/JUnit/process receipts; recorded static-review closure and superseded the pending slice-acceptance note. README/example bytes unchanged; no tests rerun or implementation edits.
- 2026-10-11T18:48:09Z: Added brief matching same-generation/manual-older README paragraphs after inspecting actual binding/caller paths and the 46-test green receipt. Marked only the new addendum pending caller review; no final implementation acceptance claimed.
- 2026-10-11T18:48:49Z: Verified exactly one new paragraph per README, matching generation/manual-older meaning, preserved prior accepted bytes, balanced fences and unchanged .env.example. Addendum remains pending caller-fix review; no code tests rerun.
- 2026-10-11T19:47:01Z: Closed the generation-binding addendum using lead-confirmed caller/generation review closure and final 2025-test/published-report E2E acceptance. Updated only this report; READMEs/example unchanged, no checks rerun, no Git operations.
