# WB/USgov adapter fidelity review

Status: Static review complete; changes required before fidelity acceptance. This is a version-bound review of `deerflow_bridge/data_sources.py` against `wb-usgov-study.md`; the API may change concurrently.

Scope: metadata preservation, pagination/truncation, fiscal periods, observation/projection uncertainty, USAspending missing-to-zero loss and SEC lossy facts. Trace only immediate consumers needed to determine chart/resolution authority. No provider/network calls, code edits, test execution, vendor re-study or further agents. This review file is the only owned write.

Acceptance: record concrete actionable findings with exact line references and SHA-256 of inspected application source; distinguish present safeguards from remaining gaps, and recheck hashes before delivery.

## Review ledger

- Initial inspection: the API file is untracked and integration work is ongoing. Existing work is preserved.
- Plan: inspect selected adapter/common-consumer code, compare against the existing study, trace any authority bypass, and produce a bounded review receipt.

## Verdict

**Changes are required before WB/USgov fidelity can be accepted end to end.** Fresh WB and USAspending fetches now disable automatic resolution, and fresh SEC fetches fail explicitly, but the uncertainty does not survive every chart path. Treasury still admits historical resolution without source-availability evidence. The findings below are static control-flow conclusions with concrete synthetic acceptance scenarios; none was executed.

Primary reviewed source: `deerflow_bridge/data_sources.py`, SHA-256 **`511e152c647a17c71f4972170a52082c8cb5b850d3a3786532ce342fc65aed4e`**. Initial inspection used `a9cf1717394d2c3792706538bf50c5bcdf89630120a137c6d5380267ff06852a`; concurrent work changed the file first to `3a322316798428b2ec3d040c57408f8c06dc9c318d00ee3e44ec380f5825a38e`, then to the final reviewed hash above. WB/USgov handlers are at lines 1384/1452 in the final snapshot. Cache, finalization, observation/manifest/resolution boundaries and both adapters were refreshed after drift. Code line references below use that newer snapshot. This is a version-bound review, not acceptance of future edits.

No vendor files were reread. The source-contract baseline is the existing [study](wb-usgov-study.md), especially lines 119–130, 189–211, 230–232 and 281–287. Earlier live claims remain unverified.

## Findings

### R1 — [P1] Unknown publisher values become observed in research charts; WDI also becomes historical in report/snapshot consumers

**Adapter evidence:** `data_sources.py:1428–1450` assigns `unknown` only to WEO/GEP observations, leaves WDI flags empty, and sets `resolution_safe=false` for every WB series. USAspending emits `unknown`, `native_missingness="lost; do not resolve"` and a prose warning at lines 1458–1465. These flags protect direct resolution but do not prohibit chart admission.

**Consumer evidence:** Research `render_data.py:585–654` discards every observation flag except recognized projection flags and does not retain notes or provenance. `_Series.latest_observed` (554–557) and `_segments` (858–873) treat every value without a projection boundary as observed. Bundle/Plotly labeling uses “Observed” / “实际值” (160–162, 803–821, 1170–1201). The actual caller `deerflow_research.py:16271–16289` admits any nonempty loaded datasets and launches this renderer without a fidelity filter.

Report classification is better: `forecast_extractor.py:1521–1535` classifies explicit `unknown` as an unclassified publisher value. It nevertheless classifies the adapter's empty WDI flag as a historical observation. `official_data.py:136–153` similarly excludes explicit unknown/WEO/GEP but ignores the WDI series' `resolution_safe=false` and admits its blank flags.

**Concrete scenario:** Fetch a WEO/GEP series with two nonmissing `unknown` rows, or USAspending rows including an upstream-normalized zero. Persist it through the existing manifest. Research charts turn those rows into the observed segment and mark the latest as observed, removing the native-loss warning. A WDI estimate whose status was stripped gets a blank flag and becomes historical in report factual statements and the public historical snapshot.

**Required outcome:** Preserve and render explicit unknown/estimate/missingness-lost classes, or skip the unsupported exhibit. Assign WB observation status unknown when source status is unavailable, including WDI, unless a separate source-backed policy establishes historical status. A resolution-only boolean is not a sufficient chart-fidelity contract. USAspending zeros must retain their unverified missingness and must never receive an observed label or feed observed-only statistics. Do not convert unknown to projection just to avoid the observed segment.

**Acceptance scenario, not run:** Native-shaped WB/USAspending fixtures → `get` → `write_dataset_files` → both chart consumers and `historical_snapshot`. Assert no observed/history classification or latest-observed marker for uncertain points, and a visible fidelity diagnostic/caption. The report path's existing unclassified category is a safeguard to reuse.

### R2 — [P1] Treasury can resolve a historical cutoff using a later or not-yet-published revision

**Evidence:** Treasury `data_sources.py:1518–1529` creates blank-flag observations, supplies catalog units/frequency, and omits `resolution_safe=false` or an availability/vintage policy. `resolve_data_anchor:591–601` only compares normalized observation period to `as_of`; it does not compare retrieval time, source receipt `fetchedAt`, release time, or revision availability. The backend wrapper delegates unchanged (`official_data.py:73–77`). The historical-snapshot function has a retrieval-cutoff check, but that check is not part of resolution.

**Concrete scenario:** A current MTS response contains a revised March 2024 value. Its record date is normalized to 2024-03-01 at adapter lines 1511–1513. Calling resolution with `as_of="2024-03-15"` can resolve the March value even though the month has not ended, using a later-retrieved dataset. A later Treasury FX amendment can similarly be selected from today's response and compared against an earlier cutoff. Blank status and an old period do not establish availability at the cutoff.

**Required outcome:** Return manual/pending without adequate cutoff-specific availability/revision evidence. An explicit publisher revision/release policy is necessary before automatic settlement; receipt fetch time is not automatically a release timestamp. Keep current-value retrieval, period identity and historical knowledge availability distinct.

**Acceptance scenario, not run:** Build a valid Treasury Series from a fake native response retrieved after the cutoff; a known monthly/quarterly period starts before cutoff but ends/releases later. Direct and backend resolution must not return resolved. Also test later revisions of already completed periods. Preserve direct resolution refusal for WB/USAspending.

### R3 — [P2] Cached or persisted data bypasses new unsupported-provider/fidelity checks

**Evidence:** `data_sources.py:953–974,985–1015` accepts an unexpired, self-hashed cached Series and returns it before the WB/USgov adapters. The cache key at 948–949 includes identity/window/max_obs, with no normalizer/fidelity-policy version. `Series.from_dict` validates the data model but does not enforce WB/USAspending safety or SEC refusal. `load_datasets:429–450` likewise admits a hash-consistent persisted Series with no current provider-fidelity check.

**Concrete scenario:** An earlier-format but otherwise valid cache entry or dataset generation contains a SEC annual Series, or a WB/USAspending Series with blank flags and no safety provenance. The current fresh SEC branch is never reached on cache hit, and persisted artifacts can reach charts/resolution directly. This is a conditional migration/cache scenario, not a claim that such an artifact was found in saved runs; no cache or saved-run contents were inspected.

**Required outcome:** Apply the current fidelity policy at cache/artifact admission and consumer boundaries, with a versioned migration/rejection strategy for older normalized generations. Hash correctness proves byte integrity, not semantic fidelity. Preserve the explicit fresh SEC DataError while also rejecting cached lossy SEC annual/as-of authority.

**Acceptance scenario, not run:** Seed a deterministic old-policy cache and a hash-consistent manifest with each unsupported Series. Require rejection or preserved explicit limited status before chart/resolution, without starting a provider. A cache hit must not restore an authority the native adapter refuses.

### R4 — [P2] Fiscal-year labels and partial-period meaning are lost in display and transformations

**Evidence:** USAspending `data_sources.py:1458–1465` requests arbitrary caller dates, stores `periodStart` as the Observation date, assigns frequency A, and stores fiscalPeriod strings in a separate unkeyed provenance list. It does not validate periodStart against fiscalPeriod or record whether each fiscal year is fully covered. `_finish:1109,1142` filters/trims observations by period start but does not realign that label list or mark partial periods. `_display_period:263–264,render_series_page:287` prints the calendar start year. Research `render_data.py:465–469` repeats the calendar-year label; its internal Series does not retain fiscal metadata. Report axes use ISO period starts with frequency A and captions omit the fiscal label (`report_visualizer.py:4456,4502,4563–4571`).

**Concrete scenario:** FY2025 starts 2024-10-01 and is displayed as “2024” in the dataset page/latest-point annotation. Requesting 2024-10-01 through 2025-03-31 yields a six-month portion of FY2025 but it is carried as an annual point; a year-over-year transform can compare partial and full fiscal years without a completeness marker. For a start inside a fiscal year, finalization can drop that year's partial aggregate because its periodStart precedes the requested start.

**Required outcome:** Preserve a per-observation fiscal label/start/end and period completeness, validate against the grouping, and either request complete aligned fiscal years or explicitly label partial aggregates. Annual display must say FY2025, not calendar 2024. Do not compare partial/full fiscal-year amounts as equivalent annual observations.

**Acceptance scenario, not run:** Full FY2025, truncated FY2025, and a start inside FY2024; run source-shaped fixtures through finalization, persisted reload, page, both chart paths and transforms. Check fiscal identity survives ordering/max_obs truncation and missingness remains explicit.

### R5 — [P2] WB can mint confident units/frequency from incomplete or contradictory metadata

**Evidence:** `data_sources.py:1387–1395,1412–1417` allows missing identity/periodicity fields via default-to-request identity and only rejects a recognized nonannual periodicity. `1440–1443` checks that each row attribute has one distinct value, but does not reconcile UNIT_MULT, UNIT_MEASURE, the row label and metadata measurement_unit. The returned frequency is always A. `_base:1098–1102` silently retains catalog values when a supplied metadata string is empty.

**Concrete scenario:** An incomplete native-shaped WB row supplies UNIT_MULT=6 and OBS_VALUE=2, but no row UNIT_MEASURE/UNIT_MEASURE_NAME, while metadata measurement_unit=Persons. The adapter can publish value 2 with unit Persons and keep exponent6 only in provenance. This is a deterministic incomplete-metadata case, not an observed live response; with a complete row unit code, the inspected vendor normally qualifies supported multiplier labels itself. Contradictory stable code/label metadata still passes the adapter's singleton check. Empty/unrecognized native periodicity is published as A rather than unavailable/unknown. Resolution is blocked by the existing WB flag, but charts and deterministic text still receive a confidently labeled numeric series.

**Required outcome:** Validate code/label/multiplier jointly and either preserve a verified scaled unit or convert values exactly once with explicit original-unit provenance. Unknown or contradictory units/frequency must cause an unavailable/limited result, not silent catalog confirmation. Missing metadata may legitimately be a degraded response; distinguish that from verified agreement. Do not claim that metadata has been verified merely because its field was omitted.

**Acceptance scenario, not run:** Missing label with exponent6; contradictory unit code/label; absent/unrecognized periodicity; valid million-people label. Assert no six-order scale error or automatic A fallback for unsupported metadata, while known qualified units remain valid.

### R6 — [P2] WB page termination can accept inconsistent/incomplete native pagination as success

**Evidence:** `data_sources.py:1398–1426` has useful repeated-page and increasing-cursor checks, but `if not payload.get("has_more")` accepts missing/null/false without checking count, offset, total_count consistency or explicit truncation flags. It does not reconcile the final collected row count against a supplied total. `_finish:1142–1150` further bounds observations with no explicit truncation/completeness field.

**Concrete scenario:** A valid-shaped final payload contains one row, count1, total_count3, has_more=false (or omits has_more). The branch returns a Series, and persistence provides no incomplete status. A producer changing the pagination envelope or reporting contradictory totals can thus supply a partial chart. This is a deterministic malformed/inconsistent-envelope scenario, not a newly observed live Data360 failure. Null total_count is valid in the original vendor contract and must remain supported.

**Required outcome:** Require a well-typed terminal/paging contract, reject explicit truncation, reconcile counts/offsets and totals when supplied, and retain separate native-completeness versus intentional max_obs-delivery bounds. Refuse unexplained missing paging signals rather than treating them as EOF. Continue valid empty-but-has_more pages and preserve the existing upper bound/repeated-page checks.

**Acceptance scenario, not run:** Missing has_more, inconsistent supplied total/count/offset, changing totals, explicit truncation, empty continuing page, and valid unknown-total termination. Only the last two valid cases may complete. A failed later page must return DataError, never a complete partial Series.

### R7 — [P2] Treasury FX geography is overwritten with USA, and metadata origin overstates provider validation

**Evidence:** `data_sources.py:1525–1529` assigns geography="USA" to every Treasury recipe, overriding the catalog geography for parameterized FX entries such as China-Renminbi/Euro Zone-Euro. The source study's mapping identifies their reference geography as CHN/EMU. `_finish:1146` labels all such metadata `provider_and_curated_catalog` even though this adapter never calls treasury_get_endpoint_fields and uses recipe units/frequency directly.

**Concrete scenario:** Fetch `usgov:treasury/fx/China-Renminbi`; the stored/anchor-enriched geography is USA while the reference quantity is renminbi per USD. A downstream country match or caption can associate it with the wrong geography, and the metadata-origin string suggests a provider field validation that did not occur.

**Required outcome:** Preserve the selected recipe/catalog reference geography or explicitly separate publisher jurisdiction from reference geography. Mark units/frequency/row-selection assumptions as curated until source-backed field validation establishes them; provider origin of values alone does not verify all metadata.

**Acceptance scenario, not run:** China, euro-area and U.S. fiscal recipes retain the correct reference geography across persist/reload/anchor enrichment; metadata provenance distinguishes catalog assumptions from validated native metadata.

## Safeguards already present

| Boundary | Source-backed protection | Remaining limit |
|---|---|---|
| WB fetch | Explicit country/year bounds and ref_area_filter=none; separate metadata call; rejects stale/body errors, wrong geography, nontrivial breakdowns, inconsistent attribute sets, repeated pages and invalid cursors; 50-page limit | Does not establish lost status, missing metadata fidelity or all pagination consistency |
| Treasury paging | Native singular filter, row-key fields, both bounds, explicit page1-based paging; verifies endpoint/count/totalPages stability and final global row count | No source revision/availability guarantee; assumed metadata and FX geography need attention |
| U.S. byte truncation | _columnar rejects truncatedToFit/data.truncated and malformed/duplicate columns/row widths | Returns error rather than retrying smaller pages; this is safe degradation, not an authority defect |
| Missing numeric parsing | _number keeps null/blank/null-like strings missing and rejects bool/nonfinite values | Cannot recover a zero the USAspending vendor already manufactured |
| Fresh WB/USAspending resolution | provenance resolution_safe=false survives the Series and persistence; direct resolver returns manual | Chart/snapshot/cache policies are separate and inconsistent |
| Fresh SEC | Explicit DataError before a provider call; refuses lossy complete annual/as-of ingestion | Old cache/manifest generations need equivalent admission policy |
| Report unknown classification | Explicit unknown values become “Publisher values — status unknown,” distinct from historical observations | Research renderer drops the flags; blank WDI status is still promoted to historical |
| Persistence/receipts | JSON/CSV hashes, metadata consistency checks, source URL/original fetchedAt/cache/method receipts and normalized metadata are retained | Hashes prove integrity only. Raw native bodies are not persisted; _call hashes canonical reserialization and response_sha256 hashes receipts, so those are not original wire-byte/replay receipts |

## Existing test evidence and acceptance limits

Only selected test **source** was inspected. No tests were run and no green result is asserted.

- test_data_sources.py:210–220 checks WB paging and no inferred projection cutoff, but accepts metadata with neither identity nor frequency. It does not traverse the research renderer.
- Lines 373–391 check Treasury reordered columns/page counts/source fetchedAt; lines 478–480 assert byte-truncation error.
- Lines 401–410 check fresh USAspending manual resolution and fresh SEC refusal without a call. They do not establish fiscal display/partial-year semantics or cached/persisted SEC refusal.
- Lines 483–494 check repeated WB pages and wrong geography, not contradictory terminal totals or missing EOF fields.

The synthetic scenarios in R1–R7 are the requested next acceptance checks; execution belongs to the implementation/verification owners. These findings require fixes or explicitly accepted unsupported paths before claiming that uncertain values cannot become observed chart/resolution authority.

## Scope, ownership and continuity

Only wb-usgov-review.md was written. Application/vendor/config/skills, prior study/coverage, caches, saved runs and shared plan were not modified. No providers, network, imports, installation, test runners or new agents were used. No whole-repository coverage or live-data semantics are claimed. This review applies only to the recorded versions and selected ranges of the API and immediate consumers.

**Next-session prompt:** “Read wb-usgov-review.md and verify source hashes. Resolve R1/R2 first with deterministic producer-to-chart/resolution tests, then preserve cache policy, fiscal labels/completeness, WB units/paging fidelity and Treasury reference geography. Maintain fresh SEC refusal and explicit USAspending missingness limits. If implementation has drifted, refresh the implicated ranges before treating a finding as current.”

## Review updates

- 2026-10-12 Asia/Shanghai: Began a bounded static review against the completed WB/USgov study. Preserved the concurrent dirty checkout and created this sole review artifact.
- 2026-10-11T17:34:25Z: Detected primary API drift from a9cf1717… to 3a322316…, followed by 511e152c…; reread affected/cited boundaries and bound the findings to 511e152c… . The seven findings refer to the refreshed source, with no runtime/provider claims.


## Source-hash and read-range receipt

All ranges are selected, 1-based and inclusive; a whole-file hash does not mean whole-file review. Hashes cover file bytes, not provider observations. Supporting files were inspected only at the immediate consumer/test-context boundaries listed below. Multiple primary-source rows record concurrent snapshots; final finding citations use the 511e152c… snapshot.

| File | SHA-256 | Selected read ranges |
|---|---|---|
| `deerflow_bridge/data_sources.py` | `a9cf1717394d2c3792706538bf50c5bcdf89630120a137c6d5380267ff06852a` | 1–306, 400–657, 692–822, 861–1162, 1340–1491 |
| `docs/handoff/main-quantitative-integration-20261012/integration-contract.md` | `a95e56687aa83d74f51c1ed7690333119fc31948ed3b6d9da168a84c948c70f8` | 1–56 |
| `backend/app/services/official_data.py` | `c3e4fa5501a23288a540ee0370549dd6147195852222d0d6e2a35d1ba23942d8` | 63–168 |
| `deerflow_bridge/skills/data-visuals/scripts/render_data.py` | `d384b385832434da0c9fc1a08eaabcc9f9b40f3c34b416ec6083e96c7095f4dc` | 140–168, 460–481, 519–660, 672–732, 755–792, 795–829, 858–899, 1034–1093, 1155–1203 |
| `backend/app/services/report_visualizer.py` | `c72bc1e0e62a53041052404bc86e3090bafb95d41e5d55cd6982ea23e259bede` | 4316–4342, 4386–4582 |
| `backend/app/services/forecast_extractor.py` | `88e6ae4a61291bf95e10b182ecf2bf22e4b7b52cd92dfd74eff8fb8999072802` | 1457–1555, 1587–1637 |
| `backend/tests/test_data_sources.py` | `7444b323aafd7a4e9e710d4c63142a81efc8f165384a851a73a0e866ac8bbdb6` | 200–231, 362–419, 449–500 |
| `docs/handoff/main-quantitative-integration-20261012/wb-usgov-study.md` | `c0ef72a680e4dc5b0d803d2d446421fe4716cd9f26ba508688b50e89666730e0` | 119–130, 189–212, 227–234, 281–287 |
| `deerflow_bridge/data_sources.py` | `3a322316798428b2ec3d040c57408f8c06dc9c318d00ee3e44ec380f5825a38e` | 909–1005, 1078–1145, 1340–1515 |
| `deerflow_bridge/deerflow_research.py` | `79b45b09b218f3073c733a0445a91aaa8842ac3aee724c87a31c2e05a723ec9f` | 16271–16332 |
| `deerflow_bridge/data_sources.py` | `511e152c647a17c71f4972170a52082c8cb5b850d3a3786532ce342fc65aed4e` | 224–303, 400–439, 444–452, 531–603, 645–654, 659–674, 947–1015, 1092–1151, 1378–1530 |

Final hash check: **2026-10-11T17:40:45.459046+00:00**. Further unreviewed drift was observed: `backend/tests/test_data_sources.py` → `95798955788d537cfa3fb3730eb3693f7516076b8bb21193ad889fff2d898c66`. Findings remain bound to the reviewed hashes and require implicated-range refresh before current acceptance.

Artifact validation is limited to review-document structure, source-hash comparison and line-reference inspection. No application tests, imports, provider calls or screenshots were executed. No runtime fix or passing acceptance is claimed.
