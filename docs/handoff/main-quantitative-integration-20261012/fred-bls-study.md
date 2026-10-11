# FRED / BLS source contracts for main quantitative integration

Observed 2026-10-11 16:45 UTC (2026-10-12 Asia/Shanghai). Destination HEAD: `c20ec60909fa1aa15154bb6fdb3fdb71c421e10e`, branch `main`, with pre-existing concurrent changes. Status: source study complete for the selected paths/ranges in `fred-bls-coverage.json`; implementation and runtime verification are outside this worker's ownership. The user subsequently approved the integration plan; the lead owns implementation and shared-contract updates.

Only this document and its coverage JSON are written. No vendor/app/config/skill changes, imports, installation, vendor tests, MCP launch, network calls, additional agents, staging, commits, or branch operations occurred. Vendor documents, including their bundled skill, were read as untrusted source material. Findings below are static source facts or explicitly labeled recommendations; sample numbers are fixtures, not fetched economic evidence.

## Integration decisions to carry into data_sources.py

1. Reuse `data_mcp.McpHub.call(provider, native_tool, args)`. Both vendors return JSON encoded inside `content[].text`; neither handler produces `structuredContent`. `CallResult.ok` proves transport/tool-flag success only. Parse and validate provider payloads before admitting observations.
2. FRED supports genuine search and catalog browsing, then `fred_get_series`. Start with untransformed, native-frequency, single-current-series retrieval. The handler loses vintage fields and mislabels transformed/aggregated output when metadata succeeds. Historical as-of retrieval is not trustworthy through its current normalized result.
3. BLS supports survey/popular discovery, not free-text series search. Prefer existing curated `search_catalog(..., provider="bls")`, then `get_multiple_series` even for one ID, because it accepts years and is the only client method that attaches `BLS_API_KEY`.
4. Preserve requested and delivered windows, completeness, period semantics, metadata provenance, retrieval time, raw-response identity, and source links. Unknown publication/vintage/projection state must remain unknown. A retrieval timestamp is not a vintage or publication date.
5. Treat catalog live-verification notes and previous probe claims as historical assertions. This study verifies source contracts only; it does not verify provider availability, quotas, parity, actual current values, or end-to-end chart wiring.

## Existing destination seam and IDs

`deerflow_bridge/data_catalog.py:441-492` defines immutable `CatalogEntry` with `series`, title/Chinese title, units, frequency, seasonal adjustment, geography, notes, topics/keywords and source URL. `native` splits once after `:`. `lookup` normalizes provider case, strips surrounding quoting/whitespace and uppercases FRED/BLS native IDs (`1513-1538`). It returns only curated entries; it is not a provider existence check. `search_catalog` ranks bilingual concepts with optional provider restriction (`1648-1719`), and `catalog_digest` emits a bounded planner list (`1742-1759`).

| Existing catalog ID | Native call for a bounded history | Metadata / link from current catalog |
|---|---|---|
| `fred:UNRATE` | `fred_get_series({"series_id":"UNRATE","observation_start":"2024-01-01","observation_end":"2024-12-31","units":"lin","sort_order":"desc","limit":12,"offset":0})` | Percent, M, SA; `https://fred.stlouisfed.org/series/UNRATE` (`678-681`) |
| `fred:GDP` | Same tool with `series_id="GDP"`, explicit dates, `units="lin"` | Billions of Dollars, Q, SAAR; preserve annual-rate basis (`597-599`) |
| `fred:CPIAUCSL` | Same tool with `series_id="CPIAUCSL"`, no server growth transform | Index 1982-1984=100, M, SA; index level, not inflation percentage (`658-663`) |
| `fred:DGS10` | Same tool with `series_id="DGS10"`; daily native frequency unless an explicit derived aggregation is requested | Percent, D, NSA (`731-735`) |
| `bls:CUUR0000SA0` | `get_multiple_series({"series_ids":["CUUR0000SA0"],"start_year":"2024","end_year":"2024"})` | Index 1982-84=100, M, NSA; `https://data.bls.gov/timeseries/CUUR0000SA0` (`854-858`) |
| `bls:CUSR0000SA0` | Same tool with `series_ids=["CUSR0000SA0"]` | M, SA; catalog says FRED mirror is `fred:CPIAUCSL` (`859-862`) |
| `bls:LNS14000000` | Same tool with `series_ids=["LNS14000000"]` | Percent, M, SA; catalog says FRED mirror is `fred:UNRATE` (`943-945`) |
| `bls:CES0000000001` | Same tool with this ID | Thousands of persons, M, SA; catalog says FRED mirror is `fred:PAYEMS` (`952-955`) |
| `bls:LASST060000000000003` | Same tool with this ID | Catalog title says California, but `_bls` assigns geography `USA` to every BLS entry (`489-492`, `979-987`). Preserve a subnational label; do not present this as the national rate. |
| `bls:CIU1010000000000A`, `bls:PRS85006092` | Same tool with each exact ID | Quarterly measures with different change/annualization semantics (`989-1001`); do not normalize every BLS period as a month. |

These are mappings from current source, not independently verified equivalences. FRED and BLS mirror IDs must remain separate provider identities until matching measure, SA, units, periods, vintage and values have been checked. Catalog FRED geography also has explicit non-USA overrides (FX `775-798`, global commodities `799-822`); do not infer USA from the provider name.

The hub owns process resolution and errors, not quantitative interpretation. Its current layouts point at FRED `build/index.js` and BLS `dist/index.js`, concurrency 4/2 (`data_mcp.py:222-226`). Its result has `ok`, joined/redacted `text`, `error`, `elapsed_s`, optional `structured`, and `is_tool_error` (`150-159`). `_to_call_result` joins text and marks failure only for oversize or `isError` (`1127-1145`). It will mark a BLS plain `Error: ...` reply as `ok=True`; the adapter must reject it. Keep native tool names separate from canonical `provider:native` series IDs.

## FRED: registration, discovery and fetch

Selected authority: `datamcps/fred-mcp-server-main/src/index.ts`, `src/fred/{tools,search,series,browse}.ts`, `src/common/{request,fred-client,config,cache,rate-limiter,errors,logger}.ts`. Relative anchors in this section refer to that vendor root.

`package.json:2-5,17-18` declares version 1.2.0 and `build/index.js`. `createServer` reads package version and registers exactly three tools (`src/index.ts:32-46`, `src/fred/tools.ts:77-161`). Default transport is stdio; `--http` or `TRANSPORT=http` chooses streamable HTTP (`src/index.ts:225-251`). The wrapper is a testability wrapper, not the package entrypoint (`src/index.wrapper.ts:13-92`).

| Tool | Exact public argument contract | Handler result / limitation |
|---|---|---|
| `fred_search` | Optional `search_text`; `search_type`=`full_text`/`series_id`; `tag_names`, `exclude_tag_names`; `limit` 1..1000, default 25; `offset` >=0, default 0; `order_by`=`search_rank`,`series_id`,`title`,`units`,`frequency`,`seasonal_adjustment`,`realtime_start`,`realtime_end`,`last_updated`,`observation_start`,`observation_end`,`popularity`; `sort_order`=`asc`/`desc`; `filter_variable`=`frequency`/`units`/`seasonal_adjustment`; `filter_value` string. | Calls `series/search`; JSON `{total_results,showing,results:[{id,title,units,frequency,seasonal_adjustment,observation_range,last_updated,popularity,notes}]}`. Search notes truncated at 200 characters; no geography, vintage or series URL field (`src/fred/search.ts:66-109`). |
| `fred_browse` | Required `browse_type`=`categories`/`releases`/`sources`/`category_series`/`release_series`; optional numeric `category_id`,`release_id`; `limit` 1..1000 default 50, `offset` >=0 default 0; string `order_by`; `sort_order`=`asc`/`desc`; optional `filter_variable` and `filter_value` as above. | `categories` -> `{categories:[{id,name,parent_id}]}`; others use `total_releases`/`total_sources`/`total_series`, `showing`, and corresponding list. Releases/sources retain `link`; category/release series omit SA and notes (`src/fred/browse.ts:50-280`). |
| `fred_get_series` | Required string `series_id`; optional string `observation_start`,`observation_end`; `limit` 1..100000; `offset` >=0; `sort_order`=`asc`/`desc`; `units`=`lin`,`chg`,`ch1`,`pch`,`pc1`,`pca`,`cch`,`cca`,`log`; `frequency`=`d`,`w`,`bw`,`m`,`q`,`sa`,`a`,`wef`,`weth`,`wew`,`wetu`,`wem`,`wesu`,`wesa`,`bwew`,`bwem`; `aggregation_method`=`avg`/`sum`/`eop`; numeric `output_type` 1..4; string `vintage_dates`. | Calls `series/observations` and best-effort `series` metadata concurrently; returns the flat JSON shown below (`src/fred/series.ts:39-116`). There is no separately registered metadata tool. |

All these number schemas lack `.int()`, date fields lack format validation, and the handler does not validate a date interval or vintage syntax. Validate dates/integers/window ordering in the adapter. `output_type` descriptions in the vendor are not independent official API documentation; this study does not establish exact upstream semantics for all vintage formats.

Concrete MCP search invocation, using the ID present in the vendor's static fixture:

```json
{"method":"tools/call","params":{"name":"fred_search","arguments":{"search_text":"gdp","limit":25,"offset":0,"order_by":"search_rank","sort_order":"desc"}}}
```

Source-derived fixture result envelope (`test/unit/fred/handlers.test.ts:27-43,174-192` plus actual formatter `src/fred/search.ts:88-108`; not an executed test):

```json
{"content":[{"type":"text","text":"{\"total_results\":1,\"showing\":\"1-1\",\"results\":[{\"id\":\"GDP\",\"title\":\"Gross Domestic Product\",\"units\":\"Billions of Dollars\",\"frequency\":\"Quarterly\",\"seasonal_adjustment\":\"Seasonally Adjusted Annual Rate\",\"observation_range\":\"1947-01-01 to 2024-04-01\",\"last_updated\":\"2024-06-27\",\"popularity\":93,\"notes\":\"Featured measure of U.S. output.\"}]}"}]}
```

JSON inside `text` is pretty-printed in the handler; whitespace is compressed here for readability. It is not the raw upstream `seriess` response. A notes-absent row can become literal `"undefined"` because the formatter concatenates `undefined + ""` (`search.ts:100`); do not treat that as a substantive caveat.

The inspected API documentation (`docs/api-reference/fred-get-series.mdx:173-201,220-241`) instead illustrates nested `series`/`observations`/`metadata` and correctly relabeled transformed units. Those examples do not match the implemented flat formatter and must not become adapter fixtures. Its generic aggregation advice at `122-134` also needs measure-specific review: summing annualized GDP levels can produce a misleading total. Preserve stock/flow/rate and SAAR semantics in derived charts.

Concrete fetch invocation (args valid under the registered schema):

```json
{"method":"tools/call","params":{"name":"fred_get_series","arguments":{"series_id":"GDP","observation_start":"2024-01-01","observation_end":"2024-12-31","units":"lin","sort_order":"asc","limit":100000,"offset":0}}}
```

Source-derived fixture result (`test/unit/fred/handlers.test.ts:27-62,196-217`, `src/fred/series.ts:71-97`):

```json
{"content":[{"type":"text","text":"{\"series_id\":\"GDP\",\"title\":\"Gross Domestic Product\",\"units\":\"Billions of Dollars\",\"frequency\":\"Quarterly\",\"seasonal_adjustment\":\"Seasonally Adjusted Annual Rate\",\"observation_range\":\"1947-01-01 to 2024-04-01\",\"total_observations\":2,\"data_offset\":0,\"data_limit\":100000,\"source\":\"Federal Reserve Economic Data (FRED)\",\"notes\":\"Featured measure of U.S. output.\",\"data\":[{\"date\":\"2024-01-01\",\"value\":28624.069},{\"date\":\"2024-04-01\",\"value\":null}]}"}]}
```

Example browse calls are `fred_browse({"browse_type":"categories"})`, `fred_browse({"browse_type":"category_series","category_id":125,"limit":50,"offset":0})`, and `fred_browse({"browse_type":"sources","limit":50,"offset":0})`. Category ID 0 is falsy: passing 0 to `categories` uses `category`, not `category/children`; `category_series` rejects 0 as missing (`tools.ts:89-102`, `browse.ts:50-57`). The `categories` handler ignores pagination arguments. No automatic traversal or pagination exists in these handlers.

### FRED metadata and ingestion hazards

- **Missing:** `"."` -> `null`; everything else uses JS `parseFloat`. Malformed numeric text can yield a numeric prefix or NaN; JSON serialization converts non-finite numbers to null. A received null cannot reliably distinguish explicit missing from parse failure (`series.ts:72-75`). Keep missing values, reject non-finite values, and record that this route loses raw lexical evidence. Zod response schemas are defined but not applied with `.parse()` in the inspected request/handlers.
- **Units/frequency:** Metadata wins over requested transformations. `units="pc1"` can return percentages labeled with original index units; `frequency="m"` can return monthly data labeled Daily. `aggregation_method`, `output_type`, selected units/frequency and sort order are not echoed in the result (`series.ts:77-89`). Track effective metadata from explicit request semantics or defer transformations to a separate derived-series step. Keep original units and transformation recipe alongside effective units.
- **Time coverage:** `observation_range` usually describes the metadata series' full lifetime, not delivered rows. `total_observations` is upstream `count`, not `len(data)`. Save `data_offset`, `data_limit`, requested bounds, actual returned min/max dates and whether all pages were obtained. Explicit descending requests plus ascending final normalization prevent an upstream default from selecting only the oldest values. Loop offsets only under an explicit bounded budget; otherwise mark partial coverage.
- **Vintage/as-of:** The HTTP observation shape includes `realtime_start/end`, but the handler maps each row to only `{date,value}` (`request.ts:42-65`, `series.ts:72-75`). Search also discards realtime fields; metadata lookup's `last_updated` is itself discarded by the fetch response (`search.ts:139-152`, `series.ts:77-89`). There are no registered `realtime_start/end` args. Multiple-vintage rows can therefore become ambiguous duplicate dates. Reject ambiguous duplicates and unsupported historical-as-of claims; do not deduplicate with last-write-wins. Merely recording `vintage_dates` in the request is not proof of delivered vintage correctness.
- **Source/projection:** `source` is a provider display string, not the original statistical producer or a citation URL. Use catalog URL or a validated ID-based FRED series URL. Preserve publisher/underlying producer separately when known. FRED includes third-party market series and model/expectations series (e.g. catalog `MICH`, `RECPROUSM156N`, `T5YIFR`); provider presence alone does not make every number a government observation or an official forecast. Native result has no geography or projection flag. Do not infer observation/forecast status solely from dates or extend a historical line into the forecast horizon.

### FRED HTTP/auth/cache/rate/error boundaries

`src/common/fred-client.ts:74-124` requires a nonempty `FRED_API_KEY` before checking cache; every tool uses this pipeline. GET URL is `https://api.stlouisfed.org/fred/<endpoint>` with appended `api_key` and `file_type=json`. Never persist an unredacted URL. The process-shared client (`request.ts:16-27`) caches successful raw HTTP JSON and coalesces concurrent identical requests. Cache identity redacts the key, so credential rotation does not segregate cached values. Query construction order also affects the URL-string cache key. This is not durable observation provenance.

Source defaults are 30s request timeout, 3 retries (up to 4 attempts), 500ms base jitter backoff, token bucket capacity 120 per minute, cache TTL 60s and max 500 (`config.ts:47-57`). These are implementation defaults/comments, not newly verified provider quotas. Cache/throttle are created lazily and retain their initial config until reset (`fred-client.ts:138-158`). Retry handles fetch errors, 429 and >=500; other HTTP errors fail immediately. Integer-seconds `Retry-After` adds a sleep before the next backoff; HTTP-date Retry-After is not parsed. The timeout wraps the fetch promise, with its timer cleared before the response body JSON is consumed, and excludes throttle/backoff wait (`161-236`). An adapter/hub deadline is still necessary. HTTP 2xx JSON is neither schema-validated nor inspected for semantic error fields. Error bodies are included in thrown messages; handler wrapping to generic `Error` loses typed retryability/status (`series.ts:98-103`, `search.ts:110-115`). Do not classify retryability by message text alone as a guaranteed vendor contract.

Optional inbound HTTP has `/mcp` POST/GET/DELETE sessions, `/healthz`, capacity 503 and missing/expired session 400/404 (`src/index.ts:79-219`); idle transports are swept (`src/http/session-manager.ts:17-101`). The inspected express path contains no application authentication middleware and defaults to all interfaces. Use the existing stdio hub seam for this integration. A healthy MCP session or health endpoint does not prove FRED authentication or data access.

## BLS: registration, discovery and fetch

Selected authority: all four files under `datamcps/bls_mcp-main/src/`; README and bundled catalog are documentation, not validation of live data. The package declares version 1.0.0 and entry `dist/index.js`. `src/index.ts:7-26` constructs `Client(process.env.BLS_API_KEY)`, registers six tools, then connects stdio. No HTTP MCP listener is defined.

| Tool | Exact public args | HTTP behavior / result |
|---|---|---|
| `get_all_surveys` | `{}` | GET `/surveys`; upstream JSON passed through |
| `get_survey` | `{"survey_abbreviation":"CU"}`; exactly two uppercase letters | GET `/surveys/CU`; upstream JSON passed through |
| `get_popular_series` | `{}` or `{"survey":"CU"}`; optional exactly two uppercase letters | GET `/timeseries/popular` with optional `survey`; description promises 25 popular series, not a complete search index |
| `get_single_series` | `{"series_id":"CUUR0000SA0"}` | GET `/timeseries/data/CUUR0000SA0`; tool description says past three years; no date or key parameter attached |
| `get_latest_series` | `{"series_id":"LNS14000000"}` | Same GET with `latest=true`; no key parameter attached |
| `get_multiple_series` | Required `series_ids`: 1..50 strings; optional four-digit string `start_year`,`end_year`; optional booleans `catalog`,`calculations`,`annual_average`,`aspects` | POST `/timeseries/data/`; key is injected into payload only here. Args map to `seriesid`,`startyear`,`endyear`,`catalog`,`calculations`,`annualaverage`,`aspects`, plus environment-owned `registrationkey`. |

Schema anchors: `src/tools/series.ts:21-121`, `src/tools/surveys.ts:21-75`. Series ID regex is `^[A-Z0-9_#-]+$`; no semantic validation, key-dependent array bound, maximum year span, chronological bound check or empty-known-series check exists. IDs with `#` pass regex but direct GET interpolation does not URL-encode the ID (`client.ts:60-80`), so avoid treating the regex as sufficient URL/identity validation.

Exact dated fetch invocation:

```json
{"method":"tools/call","params":{"name":"get_multiple_series","arguments":{"series_ids":["CUUR0000SA0","LNS14000000"],"start_year":"2024","end_year":"2024"}}}
```

Corresponding HTTP JSON before credential injection is `{"seriesid":["CUUR0000SA0","LNS14000000"],"startyear":"2024","endyear":"2024"}`. For registered metadata, add MCP `"catalog":true`; do not expose or accept registration keys as agent tool args. For an annual summary request, the MCP arg is `annual_average`, not upstream `annualaverage`.

The successful result envelope is exactly the pass-through expression below (`src/tools/series.ts:106-115`, `src/client.ts:83-95`):

```javascript
{ content: [{ type: "text", text: JSON.stringify(upstreamJson, null, 2) }] }
```

The vendor types the body as `unknown` and contains no successful response-shape fixture or validation. Consequently this source study cannot honestly supply a source-verified concrete successful BLS `Results.series` payload. A native invocation example must not be mistaken for evidence that a particular live response schema was observed. The proposed fake payload later in this document is explicitly synthetic.

A concrete result that *is* determined by source is the caught HTTP 429 path (`client.ts:43-55`, `tools/series.ts:5-18`; surveys use the same wrapper):

```json
{"content":[{"type":"text","text":"Error: Rate limit exceeded. Registered users get higher limits — provide a BLS_API_KEY.\nConsider setting BLS_API_KEY for higher rate limits."}]}
```

It has no `isError:true`. Non-429 Axios errors become `Error: BLS API error: <statusText or message>`; other errors become `Unexpected error: <String(error)>`, also without `isError`. A 2xx upstream error document is returned unchanged. The adapter must distinguish transport success, a wrapped text error, provider status/messages, missing requested series, empty results and usable observations.

### BLS auth/rate/time/metadata boundaries

- `src/client.ts:3,32-40` uses Axios base `https://api.bls.gov/publicAPI/v2`, 30s timeout and Accept JSON. It defines no retries, throttler, cache, request coalescing, window chunking or pagination. `registrationKey` is stored at construction and attached only to POST. Environment presence does not guarantee registered behavior for GET discovery/latest calls.
- README `65-76,185-187` and startup messages claim unregistered 25 queries/day, 25 IDs, 10 years versus registered 500/day, 50 IDs, 20 years. These limits are documentation claims, not enforced or live-verified here. Schema permits 50 IDs regardless of auth and does not bound years. Prior handoff's claim of oldest-first silent truncation remains a historical probe claim; do not reproduce it as a fresh measured fact. Defensively request <=25 IDs and <=10 inclusive years absent verified registration, newest window first under a budget; preserve warnings and incomplete coverage. A conservative local counter is a local policy, not an accurate shared-IP quota ledger.
- Year-only arguments cannot express a month/day window. Convert exact dates to covering year chunks, then filter normalized periods back to the requested interval. Track request count/budget and returned IDs/year coverage; returned gaps alone do not prove quota truncation. No automatic page cursor exists. For registered spans, increasing chunks/batches requires deliberate auth policy, not simply truthiness of an environment string.
- No result normalization is performed: number strings, period codes/names, footnotes, `latest`, optional catalog/calculations/aspects and provider messages are retained only if upstream supplies them. A proposed BLS normalizer must preserve original year/period identity, missing markers and preliminary/revised footnotes. Map monthly, quarterly and annual-summary periods explicitly; never turn `M13` into a thirteenth month, silently mix annual averages into monthly lines, or map `Q01` to January without a quarter-aware period type. These are acceptance requirements, not observations of this server's live response.
- No vintage/as-of args exist and no publication timestamp/projection schema is guaranteed by the wrapper. Latest retrieval is not a historical snapshot. Store retrieval time separately, keep upstream revision/footnote evidence when present, and refuse historical point-in-time claims without actual evidence.
- No canonical source URL is synthesized by the vendor. Catalog `_bls` constructs `https://data.bls.gov/timeseries/<ID>`; prefer validated IDs and retain survey/measure/local-area metadata. Existing catalog is useful but not a complete or automatically official metadata source. Its unconditional USA geography needs a subordinate area field for LAUS.
- Documentation conflicts require evidence-aware precedence: bundled `skills/bls-query/references/series-catalog.md:112-116` calls `WPSFD4` Finished Goods / NSA and `WPUFD49116` Final Demand; destination catalog `918-934` instead gives Final Demand / SA and Final Demand less foods, energy and trade services. Preserve the destination's reviewed entries as curated metadata with verification provenance pending; do not assert either set was independently reverified now or copy the vendor catalog wholesale.

## Prior handoff claims: disposition

| Historical assertion | Evidence location | What this source study establishes |
|---|---|---|
| Servers were built/probed live, and vendor tree matched an earlier copy | `docs/handoff/data-sources-mcp/handoff.md:40-44` | Not repeated or validated; selected current source hashes are the authority here. |
| Keyless FRED `fredgraph.csv` matched keyed observations on DGS10/UNRATE; shell profile has a key | Same `52` | FRED's native MCP client requires a key. No CSV route exists in the inspected vendor handlers; no parity/auth/environment claim is verified. A fallback is a separately specified adapter route with its own provenance and metadata limits. |
| BLS keyless oldest-first truncation/25-ID truncation | Same `53`, design `70-71,264-267` | Source lacks client-side protective chunking. Actual truncation/order/quota behavior remains unverified. |
| Every catalog ID was live verified on 2026-10-11 | `data_catalog.py:13-16,64`, design `160` | A date constant and assertion, not an attached per-series proof. Keep as historical metadata provenance, not a new acceptance result. |
| A `data_sources.py` API, dataset pack and charts should exist/work | Design `195-279`; current parent handoff `9-13,21-24` | Proposed/partial integration design. This provider study neither implements it nor certifies downstream artifacts. |

The previous design's single `Observation(date,value,flag)` shape is insufficient for multi-vintage FRED data; its source-level `Series` model lacks explicit requested/delivered coverage and metadata authority. The lead should freeze these decisions in the approved shared contract before implementation relies on them. This document is input to that contract, not a competing API authority.

## Minimal deterministic fake-MCP acceptance specifications

These probes are proposed, **not run**. Use a fake hub returning `CallResult`-compatible objects for adapter unit checks, then the existing first-party fake stdio fixture as the transport seam. `backend/tests/fixtures/fake_mcp_server.py:23-83` currently provides `echo`, `fail`, `table`, delay/crash/env helpers; it does not implement provider-shaped tools. Reuse or narrowly extend that fixture during the lead's implementation rather than launching/importing vendors. A fake response verifies the adapter's specified behavior, not upstream API fidelity.

### FRED probe F1: catalog/search -> paged fetch -> stored series -> chart input

1. Use `fred:GDP` and the source fixture above. The fake records exact calls. For search, require `fred_search` with `search_text="gdp"`, bounded `limit`, explicit `offset`; return the source-derived `{total_results,showing,results}` inside MCP text. Confirm the adapter uses `results[].id`, not raw upstream `seriess`.
2. For an explicit 2024 window, assert `fred_get_series` uses `series_id="GDP"`, `observation_start/end`, `units="lin"`, `sort_order="desc"`, integer bounded `limit` and offset. Return two synthetic pages using the actual normalized flat keys, total 2, limit 1, offsets 0/1, latest missing quarter then earlier numeric quarter. If configured for full coverage, require a second bounded call; if budget forbids it, require `partial` with requested/delivered coverage instead of claiming completeness.
3. Admit ascending periods `2024-01-01=28624.069`, `2024-04-01=null`, units Billions of Dollars, quarterly/SAAR, catalog citation and a fixed retrieval timestamp. Full-lifetime metadata `1947-...` must not replace delivered-window coverage. Chart input retains the gap, source, units, period basis and observed/unknown classification; replaying the stored snapshot gives the same input without a new provider call.
4. Negative variants: plain malformed JSON; mismatched returned `series_id`; non-finite numeric values; empty page before advertised count; duplicate dates carrying different values; a transformed/aggregated request returned with original metadata; vintage/as-of request that cannot retain row vintage. Require explicit rejection or qualified unsupported/partial status, never a silently accurate-looking chart. Changed transform/window/vintage requests must not reuse an incompatible cache entry.

### BLS probe B1: curated discovery -> exact POST args -> envelope/period validation

1. Resolve `bls:CUUR0000SA0` through the current curated catalog. Assert there is no invented BLS search tool. If testing exploration, call `get_all_surveys({})`, `get_popular_series({"survey":"CU"})`, `get_survey({"survey_abbreviation":"CU"})`; successful body schema remains a separately frozen fixture contract.
2. Assert dated fetch uses `get_multiple_series({"series_ids":["CUUR0000SA0"],"start_year":"2024","end_year":"2024"})`, not `get_single_series` and not upstream spellings. Do not pass registered-only booleans in the keyless case. A synthetic success body for the normalizer can be:

```json
{"status":"REQUEST_SUCCEEDED","message":[],"Results":{"series":[{"seriesID":"CUUR0000SA0","data":[{"year":"2024","period":"M03","periodName":"March","value":"310.0","footnotes":[{"code":"P","text":"Synthetic preliminary fixture"}]},{"year":"2024","period":"M02","periodName":"February","value":"-","footnotes":[{}]},{"year":"2024","period":"M01","periodName":"January","value":"300.0","footnotes":[{}]},{"year":"2024","period":"M13","periodName":"Annual","value":"305.0","footnotes":[{}]}]}]}}
```

Wrap that body as `{content:[{type:"text",text:JSON.stringify(body)}]}` with no `isError`, matching the source's pass-through envelope. This fixture's success fields/markers are an explicit proposed consumer contract, **not** a vendor-provided fixture or a captured provider response; verify against official documentation/captured consented response separately before treating the schema as externally confirmed.

3. Expected adapter result: exact ID match, ascending M01/M02/M03, null missing month with missing status, preliminary annotation retained, M13 preserved separately or rejected under a monthly-only contract. Use catalog index units/M/NSA and its source URL with `metadata_origin="curated_catalog"`; do not display 310 as inflation percent. An exact February-March request filters January after year retrieval. A separate quarterly fixture for `CIU1010000000000A` exercises Q01/quarter boundaries and avoids a global monthly parser.
4. Negative controls: return the exact source-derived HTTP-429 text envelope above with `ok=True` at hub level; return a synthetic 2xx provider failure status/messages; omit one requested series from a two-ID reply; return an empty/malformed body or conflicting series ID. All must produce explicit errors or partial coverage, no observations/chart admission and no cached false success. A synthetic message `The key:fake-fixture-key provided by the User is invalid` tests redaction before persistence/reporting.
5. At a year-window boundary, assert <=10 inclusive years per conservative keyless chunk (`end-start+1<=10`), newest chunk first, disjoint bounds and deduplication by full period identity. Truncated data and warning messages must survive as incomplete evidence. Reusing a stored response must preserve request/response hash, metadata authority and retrieval timestamp rather than pretending a new fetch occurred.

## Stopping condition and remaining evidence

The selected entrypoints, registrations, tools, handlers, HTTP/auth/cache/rate/error boundaries and relevant docs are traced, and catalog-to-native examples are supplied. Exact paths, SHA-256s, line ranges and depth are in `fred-bls-coverage.json`; no whole-vendor or whole-destination coverage is claimed. Licenses observed: FRED package declares AGPL-3.0 with license header inspected; BLS has MIT LICENSE. These observations do not establish provider-data redistribution rights, and no vendor implementation was copied into app code.

Remaining evidence belongs to implementation acceptance: freeze success/error/partial response contracts and period/vintage rules; run the proposed fake-MCP consumer checks; verify chart/report/UI/export propagation; separately verify any live quotas, fallback parity, BLS success schema, revision metadata and cross-provider equivalence when authorized. No runtime or live success is claimed by this study.

Final receipt validation parsed all seven JSON examples and rehashed every selected source. Vendor files and selected application source bytes were unchanged. The shared parent `main-quantitative-integration-20261012/handoff.md` changed concurrently; its receipt retains the earlier context snapshot and explicitly flags the changed current hash. No provider contract conclusion depends on that mutable continuity snapshot.
