# Early FRED/BLS adapter review

Reviewed 2026-10-11 17:33 UTC (2026-10-12 Asia/Shanghai). This is a static, read-only review of the changing main-branch API against `fred-bls-study.md` and the approved integration contract. Only this review file is written. No application/vendor imports, tests, providers, MCP processes, network, code/config edits, or additional agents were used. Examples below are deterministic counterexamples and positive acceptance controls reasoned from source; they were not executed.

**Verdict:** seven concrete fixes remain before accepting FRED/BLS retrieval as authoritative persisted quantitative evidence. Missing-to-zero, native FRED transformations and ordinary-text BLS error rejection already have substantive protections; retain those protections.

## Snapshot identity and drift

All finding locations below use the pinned `deerflow_bridge/data_sources.py` snapshot:

- **SHA-256:** `3a322316798428b2ec3d040c57408f8c06dc9c318d00ee3e44ec380f5825a38e`
- **Bytes / lines:** 83962 / 1532.
- **Pinned at UTC:** 2026-10-11T17:33:26.181955+00:00.
- Earlier reads at 17:31 UTC saw SHA `a9cf1717394d2c3792706538bf50c5bcdf89630120a137c6d5380267ff06852a` (1508 lines). The file changed during review; the later snapshot adds discovery code and shifts subsequent lines by 24. Findings were re-anchored and checked against the pinned snapshot rather than mixing locations.
- The API remains under concurrent development. A later byte change invalidates line anchors and requires rechecking affected findings; this is an early review, not a final frozen-source approval.

**Final drift recheck, 17:38:15 UTC:** the current module is SHA `511e152c647a17c71f4972170a52082c8cb5b850d3a3786532ce342fc65aed4e` (1552 lines). A complete text diff against the pinned snapshot contains only directory-containment changes and SDMX unit-validation changes. None changes the seven reviewed FRED/BLS findings; their later locations move by 20 lines. The selected test file also changed to SHA `95798955788d537cfa3fb3730eb3693f7516076b8bb21193ad889fff2d898c66`; test references below describe the inspected earlier snapshot and carry no passing-test claim.

| Finding | Current-module anchor at final recheck |
|---|---|
| R1 | Footnote copy 1287–1288; shared projection classification remains 224–226 |
| R2 | BLS per-chunk ID accounting 1271–1289; successful merge 1290–1303 |
| R3 | FRED count/offset/cardinality boundary 1178–1182 |
| R4 | Metadata overlay 1098–1103 and FRED metadata 1183–1188 |
| R5 | Default date window 940–945 |
| R6 | Weekly YoY lookup 1124–1126; stats lookup remains 234 |
| R7 | Rejected-key fallback classifier 1174–1176 |

Read scope: normalization/data model/render helpers, selected persistence/cache/request paths, shared decoder, complete FRED/CSV/BLS adapter paths and relevant first-party tests/fixtures. Other-provider adapters and downstream renderers were not comprehensively reviewed.

## Must-fix findings

### R1 — [P1] BLS preliminary values are explicitly presented as publisher projections

**Location:** `data_sources.py:1267-1268` copies footnote codes into `Observation.flag`; `224-226` treats any standalone `P` as projected; `246,287,299` count/render it as a projection.

The current first-party BLS fixture already contains `{"code":"P","text":"Preliminary"}` for March 2024, value 4.2. The adapter discards the explanatory text, retains `P`, and the shared renderer then labels the historical value `projection`. This is a concrete semantic change in the existing fixture path, not an assumed live-provider response. A local growth transform propagates the same code into derived rows.

**Counterexample:** feed that fixture through `get("bls:LNS14000000", start="2024-01-01", end="2024-12-31")`, then render its dataset page/brief. Source flow produces a March historical preliminary observation labeled projection and increments `projection_count`.

**Required fix:** normalize status codes in their provider context, retaining the original code/text as provenance. Distinguish preliminary/revised observations from forecasts. It is acceptable to keep preliminary values ineligible for automatic resolution; that conservative policy must not relabel them as forecasts.

**Positive acceptance control:** the same March row is displayed as preliminary, remains numeric 4.2, and does not increment publisher-projection count. An explicitly classified publisher forecast still renders as projection. Existing `test_data_sources.py:103,300-303` checks flag preservation/conservative resolution but does not catch the incorrect display label.

### R2 — [P1] A missing BLS series in one year chunk can become a cached successful partial history

**Location:** `data_sources.py:1251-1269`, especially the missing equality check after collecting `seen`; `1270-1283` accepts any accumulated rows.

Each reply rejects unexpected/duplicate IDs, but never verifies `seen == set(gathered)` for that chunk. Checking nonempty accumulated history after all chunks does not detect omission from one chunk. The output carries requested/delivered dates but no record of which series/chunks were absent, and `get/get_many` then cache it as a normal success.

**Counterexample:** request `bls:LNS14000000` for 2010–2024. Return a synthetically successful 2015–2024 reply with `Results.series=[]`, then a successful 2010–2014 reply containing a valid 2014 M01 value. The adapter returns a Series from the older chunk and persists it for the full request rather than recognizing that the requested ID was omitted from the newest chunk. The same failure occurs for one omitted ID in a multi-ID batch.

**Required fix:** account for every requested ID in every chunk before merging. Reject an omitted ID or retain a typed, explicit incomplete-coverage result that consumers cannot treat as fully admitted evidence. Do not equate ordinary observation gaps or discontinued history with a missing series record; a returned series with an explicitly empty data list is a distinct case.

**Positive acceptance control:** replies contain each requested ID once per chunk; all legitimate periods merge, including explicit missing values. A genuinely absent requested ID produces an explicit per-series error/incomplete status with no cached false success. Extend the existing chunking test at `test_data_sources.py:190-207`, whose fake currently always returns every ID.

### R3 — [P1] FRED ignores page identity/cardinality and accepts incomplete native pages

**Location:** `data_sources.py:1158-1162`.

The adapter verifies series ID and rejects only `total_observations > 5000`. It does not require the source handler's `data_offset` to equal requested offset 0, check `data_limit`, require a nonnegative integer count, or compare expected count with `len(data)`. Since the native request uses offset 0 / limit 5000 and rejects counts above that limit, every accepted response should be demonstrably complete for that bounded query.

**Counterexample:** retain the first-party FRED fixture's `total_observations=3,data_offset=0,data_limit=5000`, but return only March's one row. That still becomes a cached Series. Alternatively return all remaining rows with `data_offset=1`: the skipped first row is ignored. Missing a data row is not the same as returning a row with a null value; the native formatter preserves explicit null rows.

**Required fix:** validate count/offset/limit and page cardinality against the exact request. Fetch additional pages under an explicit bounded contract, or reject inconsistent/partial responses. Reject absent/invalid count metadata rather than defaulting it to zero. Preserve completeness evidence and cap disposition in provenance.

**Positive acceptance control:** the existing fixture with three data rows, count 3, offset 0 and limit 5000 is accepted; its February null remains a row. A count of 5001 is explicitly rejected as bounded-history overflow. A count of 3 with one returned row is not admitted or cached as complete.

**Source-study basis:** FRED `src/fred/series.ts:72-89` exposes `total_observations,data_offset,data_limit` directly from the HTTP result; these fields are available and are not lifetime metadata coverage.

### R4 — [P2] FRED metadata failure replaces known units with the native placeholder "Value"

**Location:** `data_sources.py:1078-1083,1163-1168`.

The vendor deliberately returns observations even if its separate metadata lookup fails. Its fallback is `units:"Value"`, `frequency:"Unknown"`, `seasonal_adjustment:"Unknown"` and a generic title. The adapter's nonempty metadata overlay accepts `"Value"` and overwrites curated units such as `Percent` for UNRATE. Frequency/seasonal placeholders normalize to empty and thus retain the catalog values, leaving an internally inconsistent mixture whose default authority is `provider_and_curated_catalog`.

**Counterexample:** use the ordinary UNRATE data fixture, replacing native units/frequency/seasonal/title with the vendor's documented fallback literals. The result retains M/SA from the catalog but loses Percent to Value; it can still be written and cited. Automatic anchors then reject it as unknown units, and charts/pages lose their correct quantitative label despite known curated metadata.

**Required fix:** recognize native fallback sentinels as unavailable metadata; retain curated units with explicit field-level/route-level authority, or fail closed when neither source can establish the units. Do not let a placeholder outrank meaningful units. Invalidate affected persistent cache generations when changing this interpretation.

**Positive acceptance control:** fallback UNRATE yields Percent/M/SA from the curated catalog with honest metadata-origin notes; an uncatalogued series keeps genuinely unknown units rather than acquiring invented units. Real provider metadata remains authoritative when supplied and validated. Local `#yoy/#pct` results keep their derived units and `original_units`.

**Source-study basis:** FRED `src/fred/series.ts:79-83,106-115`; its native metadata helper is best-effort. No vendor/source change or live claim is needed to trigger this path.

### R5 — [P2] End-only historical requests compute their default start from today's date

**Location:** `data_sources.py:920-925`.

When a caller supplies an end date but omits start, `finish` uses that date while `begin` subtracts the frequency-dependent lookback from `today`. Valid historical requests can therefore fail as inverted windows, or silently request a shorter history than the stated default lookback.

**Counterexample:** fix the clock to 2026-10-11 and call `get("fred:UNRATE", end="2010-12-31")`. The computed start is 2016-10-11, so the request is rejected before the provider despite both dates being in the supported year range. A daily series has the same problem with its two-year default.

**Required fix:** derive an omitted start from the effective requested end, or make an explicitly documented start requirement for historical end-only calls. With the current optional signature and advertised defaults, subtracting the lookback from `finish` gives the expected bounded history.

**Positive acceptance control:** the example creates a ten-year window ending 2010-12-31 (subject to the year floor), explicit start/end behavior stays unchanged, and a request with neither bound still ends at the fixed current date. Cache/request identity must use those final effective bounds.

### R6 — [P2] Weekly YoY silently returns missing values even when the comparison history exists

**Location:** `data_sources.py:1104-1106`; the same calendar-date assumption appears in `series_stats:234`.

YoY always shifts the exact observation date back 12 calendar months. For weekly data, that usually lands on a different weekday and therefore not on a weekly observation. This affects curated FRED weekly series such as ICSA: populated history becomes missing derived values rather than a correctly defined comparison or an explicit unsupported transform.

**Counterexample:** weekly fixture rows `2023-01-07=100` and `2024-01-06=120` for ICSA. The transformation looks for `2023-01-06`, misses the existing year-earlier weekly observation, and emits null under `Percent change from year ago`.

**Required fix:** define a supported weekly YoY alignment rule (e.g. an explicit 52-week convention with 53-week handling), retain that rule in provenance, and use it consistently for transforms/statistics. If the approved contract does not define a rule, reject weekly YoY explicitly rather than manufacturing an all-missing transformed series.

**Positive acceptance control:** under an approved 52-week rule, the two fixture rows produce 20%; a real missing denominator remains null, not zero. Monthly/quarterly exact-period comparisons remain unchanged. If unsupported by policy, the same weekly request returns a clear DataError.

### R7 — [P2] The rejected-key fallback classifier also matches quota/errors that merely mention an API key

**Location:** `data_sources.py:1154-1156`.

The regex accepts any `api.?key` occurrence, not only evidence of missing/rejected authentication. The source client includes upstream error bodies in its message, so a non-auth error mentioning the API key can unexpectedly switch the request to CSV. This hides the operational failure and changes metadata authority/route instead of returning the appropriate error.

**Counterexample:** fake FRED hub failure `FRED API error (429): rate limit exceeded for this API key`. It matches the fallback regex and calls the CSV transport. The same issue applies to other retryable failures whose diagnostic text mentions the key.

**Required fix:** use a deliberately narrow auth-failure predicate/typed classification, distinguishing missing/invalid authentication from rate limits, timeouts and provider failures. Until typed upstream status is retained, make known 429/timeout/5xx failures win over generic key wording. Keep explicit keyless routing as a separate route decision.

**Positive acceptance control:** no configured key goes directly to the injected CSV client; an explicit rejected-auth fixture takes the labeled CSV route. A synthetic 429 mentioning a key returns a bounded error and makes zero CSV calls. Keep the existing successful CSV header/origin/size/deadline tests.

## Positive protections observed; keep their controls

These are source-level observations, not passing-test claims:

| Boundary | Current protection and concrete positive control |
|---|---|
| Missing versus zero | `_number:64-72` maps None/`.`/`-`/empty/NA to None, rejects booleans/nonfinite/malformed numerics, and preserves `0`/`"0"` as numeric zero. `_finish:1094` averages only finite-present members and returns None for an all-null month. CSV persistence writes null as an empty cell (`467`), while explicit zero remains `0.0`. No missing-to-zero path was found in these reviewed FRED/BLS flows. |
| FRED transformed units | Native request explicitly uses `units="lin"` without frequency aggregation (`1150-1151`), avoiding the vendor's transformed-label defect. Shared transformation uses exact denominator presence, relabels units, adds canonical suffix and preserves original units (`1101-1121`). Positive monthly 100 -> 120 comparison yields 20%, while absent/zero denominator stays null. R4 is the separate native-metadata fallback defect. |
| Ordinary-text errors | `_call:785-802` rejects failed hub calls, raw `Error:`/`Unexpected error:`, malformed JSON and object errors. The source's ordinary-text BLS 429 envelope therefore cannot become observations. `_bls_batch:1244-1247` separately rejects failed API status and warnings. The current synthetic tests at `134-141` exercise this shape; no runtime result is claimed here. |
| Source URL and native query identity | FRED/BLS citation links use the validated exact native ID (`1165,1281`); `_url:53-61` removes credential query parameters/userinfo/fragment. FRED api_url includes date/units/sort/cap args; BLS generic POST URL is supplemented by exact `get_multiple_series` arguments in response receipts (`807,1242`). `source_url` is a human citation, not sufficient query identity by itself. |
| Request/cache separation | Cache key includes canonical provider/ID/transform, effective start/end and max_obs (`928-931`); changing a requested window or transform changes the key. Disk entries bind serialized series hashes; reads validate identity/TTL; cache replay preserves retrieval metadata (`933-963`). Native daily frequency drives the TTL even after monthly aggregation. There is no adapter/schema/catalog version in that key, so the API owner should explicitly invalidate old generations when fixing semantics or finalizing the schema; do not assume these fixes repair already-cached rows. |
| Keyless FRED containment | Fixed HTTPS host/path, no redirect/proxy use, bounded read and body deadline (`657-689`); expected series header and row/size caps (`1170-1196`). Explicit `.` survives as null; route and catalog/unknown metadata origin are recorded. This is local code evidence only; CSV availability/parity with keyed FRED was not reverified. |
| BLS batching/period caps | 25-ID batches (`1066`), newest-first disjoint chunks of at most ten inclusive years (`1237-1242,1269`), status/warning checks, exact ID rejection and explicit quarterly mapping. Annual summaries M13/Q05/S03 are excluded rather than coerced into ordinary months (`1260-1268`). R2 is the remaining omitted-ID hole. |

## Additional boundary requiring an explicit API decision

Daily FRED input is always averaged into months, then filtered against the original exact date start (`1089-1124`). A request `DGS10, start="2024-01-15", end="2024-01-31"` with valid daily observations buckets to 2024-01-01 and is then completely filtered out; a month-aligned start works. This is a concrete externally visible limitation. Decide whether daily requests retain native rows, accept only period-aligned bounds for monthly output, or expose aggregation/window intersection semantics explicitly. Avoid silently changing that policy while the API is being finalized. Current provenance does warn that partial months are possible and marks aggregation unsafe for exact resolution; this review does not assert that arbitrary partial-month means must be treated as full-month statistics.

## Evidence fingerprints and validation limits

| Source | SHA-256 / scope |
|---|---|
| `data_sources.py` | `3a322316798428b2ec3d040c57408f8c06dc9c318d00ee3e44ec380f5825a38e`; pinned findings above |
| `fred-bls-study.md` | `c977b1e1de4377358658e4ced1c13f760960a0f038781513f97d85369ba6cbe6`; prior source study reused |
| FRED `src/fred/series.ts` | `fee7f2502d8043bfd1fc0ac347ef0df23e32e6f4cbdd62a95159d2ee468d26a8`; rehash matches study |
| BLS `src/client.ts` | `31f8906bf14aa2fb090fe1255b92c220140ae15e676b893da656bbe233100117`; rehash matches study |
| BLS `src/tools/series.ts` | `8167dc3736ed521c568640d72e84d50cd937666852e8d85782c47fd85c8c877b`; rehash matches study |
| `data_catalog.py` | `5c0d1eaf04142e60b6bfd3db8a8b7f3a53fdc2213c65c6be26f1a934d667fecb`; rehash matches study |
| First-party `provider_responses.json` | `137db12893d0b1e8ded7b24537d32e14efbbaf78f057b497deb350b9b83787d4`; FRED/BLS payloads inspected, other payloads not analyzed |
| `test_data_sources.py` | `7444b323aafd7a4e9e710d4c63142a81efc8f165384a851a73a0e866ac8bbdb6`; selected ranges 1–144,155–209,290–307,360–374,428–455 read; not run |
| `integration-contract.md` | `a95e56687aa83d74f51c1ed7690333119fc31948ed3b6d9da168a84c948c70f8`; lines 1–50 read |
| Parent `handoff.md` | `13cd61d9b1c479d278874e90ec842e9cc35114a162ec4172bfd849a904d42261`; lines 1–69 read as context |

None of the existing tests is claimed green by this review. The required checks should be added/run by the Data API owner through the approved offline runner and fake hub. BLS success payloads remain synthetic consumer fixtures rather than newly verified official responses. Source facts from the earlier study and current local implementation are kept separate from any historic provider probe claims.
