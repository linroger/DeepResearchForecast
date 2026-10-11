# BIS / IMF adapter, deadline and anchor review

Review date: 2026-10-12 Asia/Shanghai. This is a read-only static review; only this document was written. No application/vendor imports, tests, servers, providers or network calls were run. The scenarios below are control-flow deductions and proposed acceptance checks, not executed reproductions.

**Four actionable findings:** direct resolution admits incomplete periods; direct resolution does not enforce vintage availability at `as_of`; unknown-status WEO values become observed chart points; and `get_many` does not enforce one deadline across preflight and provider startup. The native BIS/IMF request/response defenses reviewed below are substantially aligned with the source study.

## Revision and drift qualification

Initial `data_sources.py` snapshot at host UTC `2026-10-11T17:31:11.655430+00:00` was 1,508 lines, SHA-256 `a9cf1717394d2c3792706538bf50c5bcdf89630120a137c6d5380267ff06852a`. A concurrent revision at `2026-10-11T17:35:05.665246+00:00` was 1,532 lines, SHA-256 **`3a322316798428b2ec3d040c57408f8c06dc9c318d00ee3e44ec380f5825a38e`**. Its entire diff was inspected: it adds BIS/Treasury discovery in `search()`, and shifts later line numbers by 24. Adapter, deadline and resolver implementations are unchanged between these snapshots. All `DS` line references below use the latter hash. This is review of identified bytes while the API is finalizing, not acceptance of future edits or current working-tree state after those observations.

Completion-time drift check at `2026-10-11T17:39:47.454686+00:00` found SHA-256 **`511e152c647a17c71f4972170a52082c8cb5b850d3a3786532ce342fc65aed4e`**, 1,552 lines. The full additional diff was inspected: it changes `_directory_fd` traversal and tightens contradictory SDMX unit-code/label rejection. The findings' resolver, projection/status-consumer and `get_many`/hub control flows remain unchanged; none of F1–F4 was removed by that diff. The directory implementation is not independently accepted by this review. DS line numbers remain anchored to `3a3223...`: in the `511e15...` revision, lines after the directory helper and before the unit addition shift by +14, and lines after the unit addition shift by +20. Other directly reviewed source hashes in the table below still matched at the completion check. Subsequent edits may change this assessment.

| ID | Exact reviewed source / reference | SHA-256 and read depth |
|---|---|---|
| DS | [data_sources.py](/Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_sources.py) | `3a322316798428b2ec3d040c57408f8c06dc9c318d00ee3e44ec380f5825a38e`; effective inspected ranges 1–320, 400–1144, 1284–1366, established by original snapshot reads plus the complete concurrent diff |
| HUB | [data_mcp.py](/Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_mcp.py) | `56c5679b20749f7bd1313cd263191fc2fd1477bafa00fdfb8dda1265b1c5fde6`; 1042–1105 freshly read; other relevant launch/result boundaries retained from the prior study |
| BACKEND | [official_data.py](/Users/rogerlin/Downloads/DeepResearchForecast/backend/app/services/official_data.py) | `c3e4fa5501a23288a540ee0370549dd6147195852222d0d6e2a35d1ba23942d8`; 66–78 and 80–168 |
| CHART | [render_data.py](/Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/skills/data-visuals/scripts/render_data.py) | `d384b385832434da0c9fc1a08eaabcc9f9b40f3c34b416ec6083e96c7095f4dc`; 515–715, 804–828, 855–883, 1060–1095; only the relevant status-consumer path was traced |
| CONTRACT | [integration-contract.md](/Users/rogerlin/Downloads/DeepResearchForecast/docs/handoff/main-quantitative-integration-20261012/integration-contract.md) | `a95e56687aa83d74f51c1ed7690333119fc31948ed3b6d9da168a84c948c70f8`; 1–56 |
| STUDY | [bis-imf-study.md](/Users/rogerlin/Downloads/DeepResearchForecast/docs/handoff/main-quantitative-integration-20261012/bis-imf-study.md) | `c917f34d1e957bd6e796de15f17845d6fec2ba98217988de2dd9561b3820c374`; prior authored study retained, 116–171 freshly read |
| RECEIPT | [bis-imf-coverage.json](/Users/rogerlin/Downloads/DeepResearchForecast/docs/handoff/main-quantitative-integration-20261012/bis-imf-coverage.json) | `18ede0f9b90149f713631a7854f2960bd6c7ae2c1d928003a250d1d530dd2b83`; metadata extracted to compare vendor/catalog hashes, not a fresh whole-file semantic review |

Current byte hashes were also checked against the prior study for BIS `src/index.ts` (`72e397a9629de558fcb758f4b1dafde4cbe5185e775dbe97f63a40ddbdc272d8`), BIS `src/server.ts` (`7d151a9e75a6746a7531308abc045ef11403a980339673abd772221bf7376c07`), IMF `imf_data_mcp/__init__.py` (`a71c26d447639c303fd633f3bf578aefc7173866acd90e0c01d3766deb2e33ca`), IMF `tests/test_tools.py` (`8dac5bbe423916e6cec6a6742768bbbf4dbbebc0153d84703d577e15045ec533`), catalog (`5c0d1eaf04142e60b6bfd3db8a8b7f3a53fdc2213c65c6be26f1a934d667fecb`), and hub. All matched. Vendor source reading is inherited from the exact-hash study, not repeated execution or live verification. Shared/root handoffs were read for continuity and left unchanged. Whole-repository coverage is not claimed.

## F1 — [P1] Direct resolution accepts an unfinished month, quarter or year

**Location:** [resolve_data_anchor](/Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_sources.py:577), DS:577–587; `_anchor_period`, DS:505–528; `_period`, DS:75–87.

The resolver checks `valid["period"] > cutoff`, where the stored period is its representative **start date**. It never computes the end of the observation interval. `_anchor_period` ensures that the input identifies an exact month/quarter/year but does not establish that this interval has finished. Consequently, a finite observation with an accepted actual/revised/blank flag resolves whenever its start is before `as_of`, even when most of the interval is still in the future. There is no mandatory `resolution_safe=True` check; only an explicit False blocks it.

Static counterexamples, assuming a matching series/units/threshold and an accepted observation status:

| Frequency / anchor | Stored date | `as_of` | Current control-flow outcome |
|---|---|---|---|
| Monthly `bis:WS_CBPOL/M.US`, period `2026-10` | `2026-10-01` | `2026-10-12` | Can return `resolved` before October ends |
| Quarterly `bis:WS_CREDIT_GAP/Q.US.P.A.C`, period `2026-Q4` | `2026-10-01` | `2026-10-12` | Can return `resolved` before Q4 ends |
| Annual `imf:WEO/USA.NGDP_RPCH.A`, period `2026`, explicit accepted actual flag | `2026-01-01` | `2026-10-12` | Can return `resolved` before the year ends |

These examples do not assert that the live providers currently publish such rows. They demonstrate the public resolver cannot defend its exact-historical-observation invariant using its existing guards. Daily aggregation is explicitly marked unsafe elsewhere (DS:1090–1099), which does not protect native M/Q/A inputs. BACKEND:73–77 directly delegates to this helper; the backend historical snapshot filter is not on that call path.

**Required correction / stopping condition:** freeze the period-completion rule in the shared API and enforce it inside the direct resolver. Derive interval boundaries from frequency and explicit calendar metadata, including fiscal annual start month; do not use the representative date as a completion date. Before interval completion, return pending/manual without outcome. Completion alone still does not prove publication or historical availability; F2 remains independent.

**Acceptance checks to add, not run here:** direct calls for all three rows above must produce no outcome. Positive controls must use a completed interval plus eligible, available observation metadata. Repeat through the public backend wrapper so callers cannot bypass the guard.

## F2 — [P1] A future vintage can resolve an earlier `as_of`

**Location:** DS:573–587, 1356–1362; `Series` fields DS:143–164 and `from_dict` DS:194–199.

`resolve_data_anchor` never consults `retrieved_at`, `vintage`, a release/availability timestamp, or `provenance["vintage_availability"]`. The IMF adapter explicitly stores `vintage_availability:"not supplied"` and an exact vintage ID, but that uncertainty does not prevent resolution. Exact series/version identity is preserved; point-in-time eligibility is not enforced.

For a completed 2024 observation in `imf:WEO_2026_APR_VINTAGE/USA.NGDP_RPCH.A`, an accepted actual flag and `as_of="2025-12-31"` satisfy all current resolver guards, even though the selected edition is later than the cutoff. The same issue permits a later revised latest-flow observation to resolve an earlier historical cutoff. A current retrieval of old periods is not a snapshot of what was available then.

BACKEND:132–139 has a stricter snapshot rule for later-retrieved editions and missing WEO/GEP boundaries, but the direct resolver does not call it. Also, the backend snapshot looks for top-level `available_at`/`vintage_date`, whereas `Series.from_dict` drops unknown top-level fields and no such fields exist in the canonical dataclass. Availability cannot safely be added ad hoc to a mapping and assumed to survive the resolver/persistence round trip.

**Required correction / stopping condition:** freeze one canonical availability location and meaning, preserve it through serialization, and enforce it in direct resolution. An edition provably later than cutoff must not resolve; unknown availability must not be inferred from observation period or retrieval date. An earlier `retrieved_at` can establish possession by a cutoff for that archived payload; a later retrieval alone cannot establish earlier availability. Add a completed-period positive control with explicit eligible edition/availability evidence, separate from period completion and status checks.

**Important existing defense:** IMF blank WEO statuses become `unknown` (DS:1351–1355), and the direct resolver refuses those flags (DS:579–580). F2 concerns accepted actual/revised statuses and missing temporal eligibility; it does not claim the current resolver accepts an explicit `unknown` flag.

## F3 — [P1] Unknown WEO statuses become observed chart points

**Location:** DS:1351–1362 and `_projected`, DS:224–226; CHART:610–624, 551–558, 804–821, 858–873, 1064–1089.

The IMF adapter correctly sets a missing WEO status to `unknown` and avoids inventing `projection_from`. However, `_projected` is binary: unknown is False. `series_stats` includes every finite value in latest/range calculations and counts unknown values as zero projections (DS:229–246). That does not itself label those statistics historical, but consumers must retain the distinction.

The existing chart loader demonstrably loses it: it stores only `(date,value)` points, retaining observation flags solely when their exact text matches its projection flag set. With `flag:"unknown"` and empty `projection_from`, no projection boundary is derived (CHART:610–624); `is_projection` is False for every point; `_segments` puts every value into the observed run; and `latest_observed` returns the last unknown value. `_bundle` uses that point for the latest observed value label. Thus correctly preserved adapter uncertainty becomes an observed solid line/latest marker in the public data chart consumer. Explicit native status codes not translated into the renderer's flag vocabulary have a related compatibility risk.

**Required correction / stopping condition:** preserve per-observation status across the normalized-data-to-chart boundary. Actual, estimate/projection and unknown need separate eligibility/rendering behavior; unknown must not default to observed or be converted into a guessed projection cutoff. Either omit unknown values from historical exhibits with an explicit diagnostic or show a separately labeled unknown segment. Do not treat `projection_from=""` as proof that every value is historical.

**Acceptance check to add, not run here:** persist a WEO series with two finite `unknown` observations and no cutoff, load it through the actual renderer, and assert that neither the history line nor latest-observed annotation represents those points as actual. Retain positive actual and explicit-projection controls. Renderer changes require its owner's handoff; this review makes no renderer edits.

## F4 — [P2] `get_many` deadline excludes cache preflight and cannot stop late provider startup

**Location:** [get_many](/Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_sources.py:1006), DS:1006–1076; `_call`, DS:770–784; HUB:1068–1089.

Two related budget gaps remain:

1. The absolute deadline is created before a synchronous loop over up to 200 IDs, but that loop runs `_request` and `_cached` without a remaining-time check. `_cached` can read a local artifact synchronously (DS:933–954 in this revision). Only after all preflight work does the method submit jobs and wait with the remaining timeout. A 50 ms budget with a 200 ms cache read therefore cannot return within budget, and later cache probes can continue after expiry. Cached results can be accepted after the cutoff because this path never rechecks it.
2. Worker-local deadline checks guard lock/semaphore admission and surround hub calls; the wait/shutdown path does avoid waiting for all running jobs. However, pending `Future.cancel()` does not cancel an already running worker. HUB waits independently for `start_timeout + grace` and then invokes the native tool using the original relative call timeout. Startup time is not deducted from that timeout. A worker admitted just before deadline can therefore wait through cold start and issue a BIS/IMF tool call after `get_many` has returned deadline errors. The adapter's post-call `_remaining()` rejects the late response, but it runs after the provider work. IMF's single provider semaphore can remain occupied during that overrun.

This is not a claim that every `get_many` call waits for worker completion: DS:1067–1076 explicitly cancels queued futures and uses `shutdown(wait=False)`. The findings are the unbounded synchronous preflight and the mismatch between caller-return deadline and provider-work deadline. Nor does this static review claim an OS/thread cancellation guarantee is feasible.

**Required correction / stopping condition:** clarify whether the contract promises only bounded return latency, or also no new provider work after expiry. Check the absolute deadline between preflight/cache operations, bound or move blocking cache work off the caller, and carry the same absolute budget through startup and tool dispatch. Coordinate any hub contract change with its owner. Do not describe cancelling a future as cancelling its already running provider request.

**Acceptance checks to add, not run here:** a slow fake cache path must not continue an unbounded preflight past budget; a controlled cold-start fake hub must issue no new native fetch after expiry if that is the frozen contract; timed-out work must not create a successful returned/cached series. Record worker lifetime/admission separately from caller return latency.

## Adapter checks that align with the vendor source

These are static confirmations of code paths, not passing runtime tests:

| Concern | Current behavior and evidence | Review conclusion |
|---|---|---|
| BIS native names and shape | DS:1313–1327 calls `fetch_dataset` with `{flow_ref,key,start_period,end_period,limit:5000}` and checks exact `flow_ref`; versions come from `BIS_FLOWS`. No use of `bis_credit_gap`. DS:857–868 now calls `search_dataflows` and maps returned flow refs to complete curated series IDs. | Matches studied local native names; avoids convenience rounding/blank-zero path and fabricated arbitrary keys. |
| Oldest/prefix limit | `limit` is the native cap 5000, rather than user `max_obs`. DS:1286–1291 rejects `truncated` before normalization; `Series` sorts observations, and DS:1122 keeps the newest requested observations only after window filtering. IMF uses `max_rows:5000`. | A provider-declared capped prefix cannot become an accepted newest baseline. No subdivision/retry is implemented; callers get explicit error. Upstream paging completeness beyond exposed native metadata remains unverified. |
| Dimension mismatch | DS:1293–1305 requires every requested dimension and an exact case-insensitive code match, checks native period precision, and requires `OBS_VALUE`. Conflicting same-period observations are rejected by `Series` (DS:176–184). | Wrong country/indicator/transformation/frequency is rejected instead of silently accepted. |
| IMF nested params and aliases | DS:1333–1348 discovers definitions with `{"params":{"database_id":flow}}`; unambiguous supported aliases select actual discovered parameter spelling; fetch uses nested `params`, enclosing integer years, filters and max rows. DS:1348–1350 checks database/vintage identity. | Matches source signatures. Code-list prevalidation is not performed, but returned-dimension validation blocks a successful widened-series result. SDK-generated wire schema remains unverified here. |
| Error payloads | DS:781–802 rejects unsuccessful MCP results, decodes one/two JSON string layers, and rejects truthy `error`/`isError` objects. IMF no-data objects lack the expected database ID and therefore become errors. | Transport success alone does not become quantitative evidence. |
| Missing/nonfinite values | DS:64–72 retains explicit missing lexemes as None, rejects bool/nonfinite numeric values; DS:306–307 uses `allow_nan=False` for canonical serialization. | BIS blanks do not become zero. Nonstandard numeric NaN/Infinity cannot silently survive the response digest. String `"NAN"` is intentionally treated as missing. |
| Local period window | `_finish`, DS:1089 and 1122, clips native period-start dates locally after fetch; IMF passes enclosing integer years. | Defends against a wider native response. Inclusive coarse end-period semantics still need an explicit contract: `end="2024"` becomes January 1, rather than an entire calendar-year upper bound. This is a contract clarification, not an additional ranked finding here. |
| Vintage identity | IMF's exact vintage flow appears in ID, request database, response comparison, `Series.vintage`, request cache key and persisted metadata. Latest WEO is not silently substituted. | Identity protection is present; temporal eligibility still needs F2. |
| Unknown status in direct resolution | WEO blanks become `unknown`; resolver status allowlist refuses unknown and recognized projection/estimate flags. | Direct unknown-status rejection is present. The display-consumer loss is F3. |

The studied IMF lock/dependency mismatch, unit/scale ambiguities and historical live latency/filter claims are not resolved by this review. `_sdmx_units` rejects explicit contradictory unit/scale metadata but falls back to catalog units when native attributes are absent (DS:612–642). This does not independently verify the catalog's disputed cobalt/lithium units or WEO scaling. Do not promote these source-study gaps into live verification claims.

## Handoff and verification limits

The required next work is owner-scoped fixes/contract decisions for F1–F4, followed by deterministic direct-helper and real-consumer checks. No test suite, provider or application code was executed by this reviewer; no bug fix is claimed. The source study's prior live-probe summaries remain historical and were not replayed. No new agents or generic assets were created, and the shared handoff/contract/study/coverage files were preserved.

This review is tied to the hashes above. Later edits require rechecking the affected functions and their consumers; a fresh hash alone cannot transfer this review to a different revision.
