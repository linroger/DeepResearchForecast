# BIS / IMF contracts for main quantitative integration

Status: source study complete; implementation and runtime verification are outside this worker's ownership. User approved the integration plan during this study; this worker still writes only this file and `bis-imf-coverage.json`. Checkout observed on `main`, HEAD `c20ec60909fa1aa15154bb6fdb3fdb71c421e10e`, with substantial pre-existing changes preserved. Local task date: 2026-10-12 Asia/Shanghai; receipt timestamps use the host's UTC clock.

## Decision for the lead

Implement BIS and IMF adapters in the existing bridge-owned `data_sources.py` design, using local MCP names below. BIS's generic `fetch_dataset` is the quantitative ingestion path; its `bis_credit_gap` convenience output loses precision and can turn missing observations into zero. IMF requires discovery of parameter names/codes, payload-level error detection, exact returned-dimension checks, and post-fetch period filtering. Neither server establishes historical point-in-time availability or a reliable actual/projection boundary. Preserve unknown metadata explicitly.

Do not make prior observed IMF latency, filter widening, ignored windows, mirror parity, or BIS row ordering into current guarantees. The deterministic scenarios below validate the adapter's defenses; they do not validate the live providers.

## Scope, reading receipts, and evidence types

Success criteria were to identify registration/transport, exact native tools and envelopes, discovery-to-fetch mappings for current catalog IDs, normalization and reliability limits, and one deterministic fake-MCP scenario per source. All are covered below. No vendor import, install, test, server, network call, application/config/skill edit, branch operation, or extra agent was performed. Test files were read as text only. Shared handoffs were read, not edited; this assigned study is the worker's continuity record.

`bis-imf-coverage.json` records exact absolute paths, SHA-256, bytes, line counts, inspected ranges, depth, substantive notes, and exclusions. Coverage is selected-file coverage, not whole-repository coverage or a claim that dependencies were reviewed. Source abbreviations used below resolve to these files and their frozen receipt hashes:

| ID | Source |
|---|---|
| B1 | [BIS implementation](/Users/rogerlin/Downloads/DeepResearchForecast/datamcps/mcp-bis-main/src/index.ts) |
| B2 | [BIS stdio registration](/Users/rogerlin/Downloads/DeepResearchForecast/datamcps/mcp-bis-main/src/server.ts) |
| I1 | [IMF implementation and registration](/Users/rogerlin/Downloads/DeepResearchForecast/datamcps/imf-data-mcp-main/imf_data_mcp/__init__.py) |
| I2 | [IMF mocked test examples, not executed](/Users/rogerlin/Downloads/DeepResearchForecast/datamcps/imf-data-mcp-main/tests/test_tools.py) |
| C | [Existing catalog](/Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_catalog.py) |
| H | [Existing MCP hub](/Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_mcp.py) |
| D | [Prior data-source design](/Users/rogerlin/Downloads/DeepResearchForecast/docs/handoff/data-sources-mcp/design.md) |
| P | [Prior data-source handoff](/Users/rogerlin/Downloads/DeepResearchForecast/docs/handoff/data-sources-mcp/handoff.md) |

Source facts below mean behavior visibly defined in these bytes. Static risks are deductions from that behavior, not reproduced defects. Illustrative result shapes and fixture numbers are labeled; no example is a new live response.

## BIS: registration and native contracts

The package declares `@pipeworx/mcp-bis` version `0.1.2`. `bin/cli.js:13–17` registers `tsx` and imports `src/server.ts`; B2:11–39 registers exactly four tools over stdio. A successful handler result is `content:[{type:"text",text:JSON.stringify(result,null,2)}]`; thrown exceptions become text with `isError:true`. No `structuredContent` or output schema is supplied by B2. The gateway in `server.json`/README is a different deployment surface: do not use gateway-prefixed names or its extra tools for this local adapter.

| Tool | Top-level MCP arguments | Result contract from source |
|---|---|---|
| `list_curated_flows` | optional `topic:string`; exact, case-sensitive topic match | `{count,topics,flows:[{flow_ref,topic,title}],note}`; local table, no HTTP |
| `search_dataflows` | required nonblank `query:string`; optional `limit:number`, default 25, clamp 1–100 | `{total_matched,returned,dataflows:[{flow_ref,id,version,name}]}`; substring of lowercase name or ID; no continuation token |
| `fetch_dataset` | required nonblank `flow_ref:string`; optional `key:string` default `""`, `start_period:string`, `end_period:string`, `limit:number` default 5000 | normally `{flow_ref,source_url,columns,truncated,count,rows}`; row cells are strings; byte overflow adds `note` |
| `bis_credit_gap` | required nonblank `country:string`; optional `start_period`, `end_period`, `limit:number` default 20, clamp 1–400 | success includes `found,country,country_name,flow_ref,source_url,frequency,borrowing_sector,units,definition,latest,returned,total_quarters_available,quarters`; unsuccessful resolution returns `found:false` with a reason/hint |

Anchors: B1:735–880,1220–1278,1361–1464. Schemas use `number`, not bounded integers; generic fetch does not validate positivity, finiteness, integer limits, key dimensions, or period syntax/order. `reqStr` checks whitespace but returns the original string. The adapter should enforce its own limits and exact key grammar rather than depending on TypeScript casts.

Native discovery and fetch examples, derived from B1's table/handlers and C's IDs:

```json
{"name":"list_curated_flows","arguments":{"topic":"rates"}}
{"name":"search_dataflows","arguments":{"query":"policy","limit":10}}
{"name":"fetch_dataset","arguments":{"flow_ref":"BIS,WS_CBPOL,1.0","key":"M.US","start_period":"2024-01","end_period":"2024-12","limit":5000}}
{"name":"fetch_dataset","arguments":{"flow_ref":"BIS,WS_CREDIT_GAP,1.0","key":"Q.US.P.A.C","start_period":"2024-Q1","end_period":"2024-Q4","limit":5000}}
{"name":"bis_credit_gap","arguments":{"country":"US","start_period":"2024-Q1","end_period":"2024-Q4","limit":4}}
```

The first call's table-defined result contains two flows, `BIS,WS_CBPOL,1.0` and `BIS,WS_CBTA,1.0`, with topic `rates`. An illustrative generic fetch payload is below. `4.25` is a synthetic fixture value, not a BIS observation. Search results use `dataflows` rather than `flows` and carry registry versions; their live matches/counts are unknown.

```json
{"flow_ref":"BIS,WS_CBPOL,1.0","source_url":"https://stats.bis.org/statx/srs/data/WS_CBPOL","columns":["FREQ","FREQ_label","REF_AREA","REF_AREA_label","TIME_PERIOD","OBS_VALUE"],"truncated":false,"count":1,"rows":[{"FREQ":"M","FREQ_label":"Monthly","REF_AREA":"US","REF_AREA_label":"United States","TIME_PERIOD":"2024-01","OBS_VALUE":"4.25"}]}
```

The fetch payload's column set is dynamic. `labels=both` causes `planColumns` to fold a display header following an uppercase SDMX header into `<ID>_label`; other columns pass through. No fixed unit/status/date schema is guaranteed (B1:902–964,1250–1263). Preserve raw code and label columns, including any unit, scale, observation-status, break, compilation, or revision attributes actually present. Missing CSV cells become `""`.

### BIS HTTP, errors, and boundedness

`BASE_URL` is `https://stats.bis.org/api/v2`. `buildDataUrl("BIS,WS_CBPOL,1.0","M.US")` constructs `/data/dataflow/BIS/WS_CBPOL/1.0/M.US`; start/end map to `startPeriod`/`endPeriod`, with `format=csv&labels=both`. Empty/`all` omits the key; `+` is intentionally left in the path for OR. Reject arbitrary URL/query/path characters in catalog keys before dispatch. The adapter can record this constructed, secret-free URL as a request receipt, but native generic results do not return it (B1:952–964,1220–1226).

Search fetches `/structure/dataflow/BIS/all/latest?detail=allstubs` with `Accept:application/vnd.sdmx.structure+json;version=2.0.0`. It reads the full registry then slices matching results. This is flow discovery, not a general series/codelist/DSD tool. Native tools cannot generally enumerate valid codes and dimension order before fetching; the catalog supplies the supported key layouts. Error diagnostics sometimes query structures but expose prose, not a reusable schema result (B1:848–879,1179–1209).

All normal HTTP calls use a 25-second abort signal. Diagnostic fetches use 8-second bounds, and country lookup uses 12 seconds. `fetchBounded` clears its timer after receiving the response; this does not independently bound subsequent body reading. Non-curated 404 diagnosis can add a registry request plus further key/structure/last-observation requests; a tool call can exceed one HTTP timeout. There is no retry loop, token/key auth header, provider rate limiter, or response cache in the inspected BIS implementation. The README's “no quota” claim is not proof of an unlimited live service (B1:270,420–492,692–696,989–1217,1323–1341).

Generic non-2xx data fetches throw. A 404 is labeled `user_error:` after best-effort diagnosis, including genuinely empty periods; other statuses yield summarized `BIS data error`. Search uses `httpError` and `parseJson`, which summarize failed/invalid JSON and markup. Generic successful fetch does not validate that HTTP 200 is actually CSV: HTML can become a bogus header/row. Do not infer retryability or caller fault solely from vendor prose. Native `bis_credit_gap` treats any fetch 404 as `country_not_covered`, even with a requested time window; that classification is less reliable than an explicit coverage check (B1:284–394,1226–1254,1386–1415).

The generic success body is capped after the streaming chunk crosses 6 MiB, then its last newline is used to discard a possibly partial final line. It can overshoot by one chunk; a newline inside a quoted CSV field is not necessarily a safe record boundary. The no-stream fallback is not capped. The row limit keeps the upstream prefix, with no sorting or “latest” guarantee. A header-only result carries `count:0`; completely empty CSV returns only `{flow_ref,columns:[],count:0,rows:[]}`, without `source_url`/`truncated`. No page cursor/offset is exposed. Split bounded periods, check `truncated`, deduplicate on full series key plus period, and never call a capped prefix complete merely because it sorts correctly locally (B1:1023–1043,1250–1278,1467–1504).

`bis_credit_gap` uses broad key `Q.<country>...`, groups only by period/type, rounds to two decimals, sorts newest first, and discards the byte-cap overflow flag. It can collapse distinct borrower/lender series if multiple keys are returned. `Number("")` is zero, so an empty `OBS_VALUE` can become a fabricated zero; nonfinite values are skipped. Its declared units distinguish ratio/trend percent of GDP from gap percentage points. Use the exact generic catalog key for evidence-grade ingestion and retain original precision (B1:1281–1290,1382,1407,1427–1464).

## IMF: registration and native contracts

The package declares `imf-data-mcp` version `0.2.0`, Python ≥3.11, `imfp>=1.3.0`, `pandas>=2.0.0`, `pydantic>=2.0.0`, and `mcp[cli]>=1.9.1`. Its console entry points to `imf_data_mcp:main`; module `__main__.py` calls the same function. I1 constructs `FastMCP("imf_mcp")`, decorates five tools, and calls `mcp.run()`. The transport/envelope details delegated to the MCP dependency were not executed or independently reviewed.

Four tool handlers take a single Pydantic argument named `params`: send **`{"params":{...}}`**, not README-style flattened fields. This nesting follows the Python signatures and should be checked against `tools/list` in the future fake-MCP/SDK contract test; no live schema dump was obtained. `imf_list_databases` takes no arguments. Input models strip whitespace and forbid extra model fields; nested `filters` keys themselves are not an allowlist (I1:50–107,137–161,199–238,309–358).

| Tool | MCP arguments | Handler's returned string content |
|---|---|---|
| `imf_list_databases` | `{}` | JSON array of database records; cap 200 with a non-JSON truncation suffix if exceeded |
| `imf_search_databases` | `{"params":{"keyword":"price"}}` | JSON array of matching database records; no matches is `{"message":"No databases found matching 'price'."}`; default table cap 500 |
| `imf_get_parameter_defs` | `{"params":{"database_id":"CPI"}}` | JSON array of `{parameter,description}` from `imfp.imf_parameter_defs`; default table cap 500 |
| `imf_get_parameter_codes` | `{"params":{"database_id":"CPI","parameter":"country","search":"austria"}}` | object keyed by parameter, arrays of `{input_code,description}`; silent cap 300 per parameter |
| `imf_fetch_data` | `{"params":{"database_id":"CPI","start_year":2022,"end_year":2023,"filters":{"country":["AUT"],"frequency":["A"]},"max_rows":500}}` | JSON object with dynamic `columns` and `rows`; ordinary shape shown below |

`keyword` is 2–100 characters; database ID 1–60; optional code parameter 1–60; code search ≤100. Fetch years individually accept 1900–2100; there is no `start_year<=end_year` check. `filters` is `dict[str,list[str]]`; unknown or empty lists are not validated against a code registry. `max_rows` accepts null or 1–5000, default 500; null also falls back to 500 (I1:83–94,137–148,199–225,309–345,412).

I2:15–33 supplies mocked discovery and observation records. Combining that fixture with I1:411–429 gives this **source-derived fixture result**, not live data:

```json
{"database_id":"CPI","columns":["country","frequency","time_period","obs_value"],"row_count":2,"total_rows_before_cap":2,"truncated":false,"rows":[{"country":"AUT","frequency":"A","time_period":"2022","obs_value":5.8},{"country":"AUT","frequency":"A","time_period":"2023","obs_value":7.7}]}
```

The fixture parameter-definition response is `[{"parameter":"country","description":"Country"},{"parameter":"frequency","description":"Frequency"}]`. Its filtered country-code response is `{"country":[{"input_code":"AUT","description":"Austria"}]}`. These are useful contract fixtures, not proof that every IMF dataset has those dimensions or current codes. Some I1 docstrings still use `ref_area`, `freq`, or `commodity`; discovery and actual returned columns must override those examples (I1:176–181,256–261,383–387; I2:20–33).

### IMF dependency, errors, and boundedness

Each handler offloads synchronous `imfp` calls through `asyncio.to_thread`. Fetch passes `database_id` positionally, `start_year`/`end_year` as named values including None, and expands `filters` into keyword arguments. No wrapper HTTP URL builder/client, auth configuration, local cache, rate limiter, retry policy, HTTP timeout, or network cancellation guarantee exists in I1. HTTP auth, base URL behavior, query serialization, server paging, retries, scaling, and status parsing live in `imfp`, whose source is absent from the selected corpus. The README describes SDMX 3.0 at data.imf.org and roughly 10 requests/5 seconds with automatic retries; those are dependency/upstream claims, not verified current boundaries (I1:14–32,73–78,183–194,265–274,389–400; IMF README:3–10,110–113).

The checked-in `uv.lock:148–173` still describes `imf-data-mcp 0.1.0` with `requests`; its header requires Python ≥3.12. Static TOML metadata parsing found zero `imfp` and zero `pandas` package entries. This conflicts with the 0.2.0 pyproject and import surface. Do not infer an installed dependency version or transport behavior from this lock. Lead-owned setup must resolve and record the actual dependency environment under the approved plan; no installation or lock repair was attempted here.

Handlers usually catch exceptions and return JSON `{"error":...}` **as a successful string result**, often with `hint`/`available_parameters`. Hub `CallResult.ok` checks transport and MCP `isError`, not this nested error field (H:1127–1145). Therefore `data_sources.py` must decode text and reject error payloads even when transport is green. A no-data fetch returns `{message,row_count:0,rows:[]}`, without columns/database/truncated; distinguish this from an invalid payload and from a dependency failure (I1:402–409,431–442).

Database search uses pandas `.str.contains(keyword,case=False,na=False)` with regex semantics; code search is literal lowercase substring over code/description. Invalid search regex is caught as an error, not an empty match. `_format_table` appends prose after the JSON array when capped; code arrays silently truncate at 300, with no completeness marker or cursor. Handle those discovery outputs as partial or refine the query, never assume a complete code list (I1:35–45,122–132,290–304).

Fetch downloads/materializes the dependency DataFrame before `head(cap)`. `total_rows_before_cap` counts that DataFrame, not necessarily the complete upstream dataset. The wrapper does not validate returned dimension values, sort, post-filter years, or expose pagination. Narrow filters and year chunks reduce risk but are not proof the dependency honors them. Post-filter exact dimensions and native periods; reject an unexpected code set rather than silently accepting a broadened series. A truncated payload still cannot establish complete data for the desired interval after filtering (I1:389–429).

`_df_to_records` attempts missing-value conversion using `df.where(pd.notna(df),None)`. For a numeric dtype, pandas may retain NaN; `json.dumps` permits nonstandard NaN/Infinity unless configured otherwise. Fetch also uses `default=str`, potentially turning unsupported scalar types into strings. These are static serialization risks, not executed reproductions. Use strict numeric validation: preserve null/missing and raw values, reject nonfinite JSON numeric tokens, and never zero-fill them (I1:25–27,416–429). Dates, units, scale, status, release/vintage and source links are not normalized or added by the wrapper; they survive only if present in DataFrame columns.

## Catalog IDs → exact adapter calls

C:165–213 defines flow versions/agencies/ordered dimensions. C:495–508 creates source links and derives frequency from the first BIS key component or last IMF component. C:1012–1319 supplies the selected entries; C:1513–1538 canonicalizes provider/native case. Existing entries are useful curated assertions; their `VERIFIED_ON="2026-10-11"`/“verified live” prose does not substitute for new runtime verification.

| Existing ID | Native MCP mapping | Metadata/guard |
|---|---|---|
| `bis:WS_CBPOL/M.US` | `fetch_dataset` with `flow_ref:"BIS,WS_CBPOL,1.0",key:"M.US",start_period,end_period,limit` | key dims `FREQ.REF_AREA`; catalog geography USA; XM maps EMU, CN maps CHN |
| `bis:WS_CREDIT_GAP/Q.US.P.A.C` | `fetch_dataset` with `flow_ref:"BIS,WS_CREDIT_GAP,1.0",key:"Q.US.P.A.C"` and bounds/cap | five dims; retain P/A/C, quarter and raw precision; unit percentage points of GDP |
| `bis:WS_TC/Q.CN.P.A.M.770.A` | `fetch_dataset` with `flow_ref:"BIS,WS_TC,2.0",key:"Q.CN.P.A.M.770.A"` and bounds/cap | seven dims, including market valuation, percent GDP, break adjustment; version must be 2.0 in this catalog |
| `bis:WS_XRU/M.XM.EUR.A` | `fetch_dataset` with `flow_ref:"BIS,WS_XRU,1.0",key:"M.XM.EUR.A"` and bounds/cap | EUR per USD and monthly average per catalog, not usual USD per EUR |
| `imf:PCPS/G001.POILBRE.USD.M` | `imf_fetch_data`, `params.database_id:"PCPS"`; candidate discovered filter map below | WORLD aggregate, Brent USD/barrel, monthly; USD is transformation code, not a country |
| `imf:WEO/G001.NGDP_RPCH.A` | `imf_fetch_data`, `params.database_id:"WEO"`; candidate `country:["G001"],indicator:["NGDP_RPCH"],frequency:["A"]` | World GDP growth, annual; agency IMF.RES lives in catalog citation metadata, not a native tool argument |
| `imf:WEO_2026_APR_VINTAGE/CHN.NGDP_RPCH.A` | same fetch tool, exact database ID `WEO_2026_APR_VINTAGE`; candidate `country:["CHN"],indicator:["NGDP_RPCH"],frequency:["A"]` | preserve vintage in identity/cache/artifacts; never fall back silently to WEO latest |
| `imf:CPI/USA.CPI._T.YOY_PCH_PA_PT.M` | same fetch tool, database `CPI`; map five ordered components via discovered parameter names | candidate `country,index_type,coicop_1999,type_of_transformation,frequency`; retain `_T` and YOY transformation |

For BIS the remaining catalog layouts map to the same generic tool: DSR=`FREQ.BORROWERS_CTY.DSR_BORROWERS`; SPP=`FREQ.REF_AREA.VALUE.UNIT_MEASURE`; EER=`FREQ.EER_TYPE.EER_BASKET.REF_AREA`; LONG_CPI=`FREQ.REF_AREA.UNIT_MEASURE`; CBTA=`FREQ.REF_AREA.COMP_METHOD.UNIT_MEASURE.CURRENCY.TRANSFORMATION`; GLI=`FREQ.CURR_DENOM.BORROWERS_CTY.BORROWERS_SECTOR.LENDERS_SECTOR.L_POS_TYPE.L_INSTR.UNIT_MEASURE`. Use C:167–194 as the adapter table and validate returned key columns. Searching arbitrary flows does not supply safe series IDs without such layout evidence.

For IMF, parameter names are dependency-defined. The mappings above are **conditional catalog-to-native mappings**, not observed `tools/list` or live parameter results. Discover `imf_get_parameter_defs`, then `imf_get_parameter_codes` for the specific database; match dimensions by meaning and retain the actual returned spelling. Do not blindly lowercase uppercased SDMX dimensions or globally substitute `ref_area`/`freq`. For PCPS, if discovery confirms the catalog-derived names, the full native call is:

```json
{"name":"imf_fetch_data","arguments":{"params":{"database_id":"PCPS","start_year":2024,"end_year":2024,"filters":{"country":["G001"],"indicator":["POILBRE"],"data_transformation":["USD"],"frequency":["M"]},"max_rows":5000}}}
```

For monthly/quarterly caller windows send enclosing integer years then filter returned native periods locally. Current metadata includes WEO 2026 April and 2025 October; `imf_flow_info` also recognizes other APR/OCT vintage-shaped names syntactically (C:556–566). That does not prove a database exists; require discovery or a documented unavailable result. IMF citation pages are `https://data.imf.org/en/datasets/IMF.RES:PCPS`, `.../IMF.RES:WEO`, and `.../IMF.STA:CPI`; a vintage uses the WEO page plus the exact vintage ID. Do not invent an imfp HTTP request URL from the catalog.

## Quantitative ingestion and chart invariants to freeze

1. **Identity and provenance:** retain canonical catalog ID, provider, exact database/flow version and key/filter map, MCP tool/args, adapter-received payload hash, catalog metadata version, retrieved UTC time, and any upstream timestamp separately. Record that hub redaction precedes that payload hash (H:1139–1140); it is not a hash of unmodified wire bytes. Use the catalog's series-specific BIS URL while retaining the native generic `source_url`. A citation page is not proof of successful retrieval. Neither generic server supplies a standard `as_of`/publication-date contract.
2. **Periods and availability:** retain original period (`2024`, `2024-Q1`, `2024-01`), frequency, and deterministic period-start mapping for display. Period-start is not release date, observation availability, revision time, or vintage. A latest fetch clipped to old periods does not reconstruct what was known then; immutable WEO vintage ID plus archived payload supports a narrower edition claim, not exact release-date knowledge.
3. **Numeric and semantic integrity:** require finite numeric values or explicit missingness, preserve raw precision/status, and fail on conflicting duplicate full-key/period rows. Validate country/aggregate, full indicator/transformation and frequency before accepting observations. Keep percent, percentage points, percent change, currency levels, nominal/real, index base, seasonal/break adjustment and collection method distinct. No interpolation or silent blank-to-zero conversion.
4. **Units and scale:** store catalog units with their assertion provenance and retain upstream raw unit/scale columns. C:1230's “SCALE 9 is a display hint”/whole-dollar WEO claim needs confirmation before choosing a multiplier. C:1279–1287 explicitly disputes cobalt's label and infers lithium magnitude; quarantine level comparisons until authoritative unit evidence resolves them. Do not derive units from magnitude. Catalog notes about US policy midpoint, FX inversion, index bases, and CB assets billions are hypotheses to reconcile with returned metadata, not universal conversion rules.
5. **Projection and assumptions:** native data may mix actuals, estimates, projections and baseline assumptions. C:1183–1186's “after latest completed year” shortcut is inadequate for historical vintages and can misclassify prior estimates. Prefer provider per-observation status or verified edition-specific cutoff; otherwise label status unknown. WEO Brent assumption (C:1231–1234) is separate from historical PCPS Brent and from the system's forecast. A lone `projection_from` cannot represent mixed statuses; freeze how unresolved or mixed data are serialized and charted before claiming observed history.
6. **Completeness and chart eligibility:** track requested/returned window and truncation/partial discovery. Split bounded windows and retain newest observations only after completeness checks. Unsupported split/remaining byte or row truncation must produce a partial/error state, not a “latest” baseline. Charts must label units, actual frequency, geography, retrieval/vintage and status; break missing segments and distinguish official projections from application forecasts. Do not apply YoY again to a catalog series already in YoY percent change. Monthly average FX/commodities and end-period policy rates require different resampling choices; the prior D:260–262 generic daily averaging policy needs per-series semantics.

The existing hub already launches local BIS/IMF surfaces, sets IMF concurrency 1 and a minimum 120-second call deadline, and passes `IMF_APP_NAME`; these are code-defined local choices, not measured upstream requirements (H:74–120,222–230,366–388,440–483). The wrapper does not read `IMF_APP_NAME`; the dependency may. Reuse the hub and perform adapter-level parsing after `CallResult`; the hub's 16,000,000-character text limit is a last-resort transport bound, not an observation-budget or completeness guarantee.

## Historical claims separated from source facts

P:42–53 (dated 2026-10-11) reports prior live builds/probes, IMF 30–50 seconds, bad-code widening, ignored WEO/PCPS year windows, BIS oldest-first prefixes and ~6.6 MB requests, and a faster Data360 WEO mirror. Its referenced scratchpad probe artifacts were not inspected or replayed. D:73–80,263 and C:8,14–16,64,88–90,1215 repeat some of these assertions. They remain historical reports, not current acceptance evidence.

Source corroborates prefix capping without local sorting/window/code validation, delegated IMF requests, and BIS byte limits. Source alone does not prove the current upstream order, filter/window behavior, latency, scale interpretation, availability, or mirror parity. Vendor comments also contain dated live-verification stories; those comments were read as claims. Current task forbids network, so no such claims were reverified here.

## Minimal deterministic fake-MCP acceptance probes (specifications, not run)

Both probes belong in lead-owned application tests after interface freeze. Use an injected fake hub/session, with ambient provider startup disabled and no vendor imports. Serialize the native payload into MCP text, retaining `isError` semantics; assertions must reach normalized `Series`/`DataError`, persisted dataset metadata, and chart eligibility rather than stopping at a tool call. No new harness is required by this study.

**BIS probe: exact key, prefix truncation, and missingness.** Request `bis:WS_CBPOL/M.US` for January–March 2024. Fake hub asserts `call("bis","fetch_dataset",{flow_ref:"BIS,WS_CBPOL,1.0",key:"M.US",start_period:"2024-01",end_period:"2024-03",limit:<frozen adapter cap>})`. Return the generic source shape with three M/US rows, periods out of order, values `"4.25"`, `""`, and `"4.50"`, dynamic unit/status columns, and `truncated:false`. Expect sorted native-period observations `[4.25,null,4.50]`, USA/M identity, correct unit/citation/retrieved receipt, and a broken chart segment. Repeat with `truncated:true` and only the prefix: expect bounded subdivision or explicit partial/error with no complete/latest claim. Negative controls: wrong `REF_AREA:"CN"`, malformed successful HTML-shaped columns, nonfinite value, and MCP `isError:true` must not yield usable evidence. Independently assert credit-gap ingestion dispatches `Q.US.P.A.C` via `fetch_dataset`; it must never consume `bis_credit_gap`'s rounded/blank-zero output. Synthetic fixture values above are not provider observations.

**IMF probe: nested params, code/window validation, and payload error.** Fake `imf_get_parameter_defs`/`imf_get_parameter_codes` return the I2 country/frequency fixtures, then fetch CPI/AUT annual 2022–2023 with exact nested `params`, `filters:{country:["AUT"],frequency:["A"]}`, `max_rows:5000`. Return I2's two observations in the I1 fetch envelope; expect two normalized annual observations, retained country/frequency, and catalog/fixture-derived metadata. Add an out-of-window 2021 row with `truncated:false`: post-filter it. Add a DEU row or conflicting duplicate: reject identity/integrity rather than accepting a widened query. Return text `{"error":"not found","hint":"Check codes"}` with MCP transport success: expect `DataError`. Return `truncated:true` with only earlier rows: expect partial/error or bounded requery, never fabricated requested years. Return null and NaN variants: preserve null and reject/quarantine nonfinite values without zero fill. A compact WEO-vintage variant must keep `WEO_2026_APR_VINTAGE` in fetch args/cache/output and leave projection status unknown absent an explicit fixture status/cutoff; it must not use today's year or substitute latest WEO.

These probes establish adapter behavior under controlled payloads. A later authorized live `tools/list`/bounded series probe is still needed to confirm IMF FastMCP wire schemas, dependency versions/HTTP behavior, supported flow versions/codes, returned metadata, and live completeness. No such runtime success is claimed here.

## Remaining work and handoff

The lead can freeze adapter field names and partial/unknown semantics using these notes, then implement within the approved shared plan. Resolve the IMF lock/dependency mismatch, discover actual IMF filter names, and retain the historical-vs-current evidence distinction. The main study gaps are imfp/SDK dependency implementation, upstream release/status/scale metadata and live response behavior. Wider application consumers, renderer implementation and other vendors were intentionally not expanded into this assignment.

Files changed by this worker: this study and its coverage receipt only. Source/test/docs reading and metadata hashing/static TOML parsing are the evidence collected; no runtime tests were run. No vendor or application fixes, generic assets, or commits are part of this worker's output. Final receipt checking found 20 of 21 selected file identities unchanged, including every selected vendor file, catalog, hub and prior design. The shared main-integration handoff changed concurrently after its refreshed reading; its original read hash/ranges are retained and explicitly marked stale context. It is not authority for any provider contract here, and no shared changes were overwritten.

Updates: initial reading completed before the interruption; 2026-10-12 Asia/Shanghai user approved the integration plan and requested completion under unchanged ownership; prior reading was preserved and only the shared handoff's changed approval lines were refreshed. Final source hashes/ranges and local receipt validation are recorded in `bis-imf-coverage.json`.
