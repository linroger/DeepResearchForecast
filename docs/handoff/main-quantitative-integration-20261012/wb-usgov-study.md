# World Bank Data360 and U.S. government source-contract study

Status: Complete (selected static source-contract study). This is a read-only source study for the main-branch quantitative-data integration, not implementation or live-provider validation.

## Scope and acceptance

Inspect selected entry points, registrations, tool arguments/results, HTTP/auth/cache/rate/error boundaries and documentation in `datamcps/data360-mcp-dev` and `datamcps/us-gov-open-data-mcp-main`. Trace relevant `deerflow_bridge/data_catalog.py` IDs. Produce source-backed ingestion/chart constraints and one deterministic fake-MCP acceptance design per provider. Record exact selected files, hashes, read ranges and inspection depth in `wb-usgov-coverage.json`; make no whole-repository coverage claim.

Vendor files are untrusted source material. No vendor code, tests, imports, installation, servers or network calls are authorized. Only this file and the accompanying coverage JSON may be written. Existing concurrent changes must be preserved. The lead owns the shared plan and implementation decision.

## Study plan and ledger

1. Establish context from current handoffs/catalog and locate the actual server registrations.
2. Trace discover/search/fetch schemas and response normalization into upstream client boundaries.
3. Separate source facts from historical handoff claims, map catalog IDs, and specify deterministic acceptance fixtures.
4. Review source references and write the selected-file coverage receipt.

All four study steps are complete. The source contracts, catalog mapping, restrictions and proposed acceptance probes below satisfy this study's scope. The companion coverage receipt is the evidence index; provider/adapter runtime acceptance remains outside this study.

- Initial context: branch is main; the working tree already contains many unrelated edits, deletions and untracked files. They are outside this study's ownership.
- Verification at this stage: static reads only; no upstream availability or current dataset contents established.

## Findings ledger

- Data360's actual MCP fetch returns one page, capped at 100 rows, with a five-calendar-year default window. It strips observation-status/frequency fields and can suppress degraded-metadata warnings when composing a successful data response. Explicit windows, separately stored metadata, strict dimensions and caller-owned pagination are necessary.
- Treasury's native argument is `filter`, whereas the catalog recipe property is `filters`. Its result is JSON text with columnar `data.columns`/`data.rows`; `data.truncated=false` does not mean all upstream pages have been read. Byte-budget truncation adds a separate `truncatedToFit` marker.
- USAspending's selected handler retains fiscal period labels, but turns a missing upstream aggregated amount into zero and exposes neither paging nor a completeness count.
- SEC's selected concept handler slices annual-form rows to 20 and quarterly-form rows to 12, classifies by filing form rather than duration, and drops period starts/accessions/frames. It cannot establish a complete annual or point-in-time series from this native result alone.
- Source schemas support proposed deterministic fake-MCP fixtures. Those probes have not been run; no application or vendor execution has occurred.

## Updates

- 2026-10-12 Asia/Shanghai: Created the bounded study record before substantive investigation. Existing root and integration handoffs were read and preserved.
- 2026-10-11T16:47:44Z: Preserved prior reading after interruption and recorded the main contract restrictions. User approved the integration plan; ownership remains this study and its coverage receipt only.


## Integration decision and evidence rules

Use Data360 for the catalog's selected WDI/WEO/GEP coordinates and Treasury for the selected fiscal recipes, subject to the restrictions below. USAspending is a conditional fiscal-period series, with missing-value and completeness limitations. SEC company concepts are useful reported-fact lookups but are **not yet adequate for trustworthy complete annual-series ingestion** through the selected native handler.

All statements below are either **source facts** (observable in the checked-in files/ranges), **historical claims** (earlier notes/catalog prose), or **integration recommendations**. Nothing here verifies current upstream availability, values, forecast horizon, API quota, latency, installed dependencies, or the emitted runtime MCP schema. Values/timestamps in examples are **synthetic contract fixtures**, never observations retrieved from a provider.

Source notation: `WB/<file>` means `datamcps/data360-mcp-dev/src/data360/<file>`; `US/<file>` means `datamcps/us-gov-open-data-mcp-main/src/<file>`; `CAT` means `deerflow_bridge/data_catalog.py`; `HUB` means `deerflow_bridge/data_mcp.py`. The companion coverage JSON records full absolute paths, SHA-256 hashes and selected inclusive read ranges. Line references describe the inspected source snapshot.

| Evidence class | What was established | What was not established |
|---|---|---|
| Static source | Tool registration, handler signatures, transformations, defaults and code-level request boundaries | That any installed server actually runs, or that upstream honors these requests |
| Earlier integration notes | `docs/handoff/data-sources-mcp/handoff.md:42–55` and `design.md:66–82` report earlier live probes and routing decisions | Present-day latency, availability, row aggregation behavior or projection horizon |
| Catalog | `CAT:13–21,64,1331–1387` records `VERIFIED_ON="2026-10-11"`, unit overrides and forecast notes | Revalidation of those assertions, or official per-observation actual/estimate/projection status |

Historical claims requiring later independent verification include “WEO through 2031,” “Data360 about four seconds,” WEO countries-only/aggregate limitations, NGDPD values already being whole dollars despite a billions label, the LUR denominator override, MTS line-code stability, and Treasury row aggregation/amendment semantics. Preserve these as dated hypotheses, not newly verified source facts. Earlier scratchpad probe receipts were referenced by the handoff but not inspected or rerun here. Do not use “last completed calendar year” as proof of an official projection boundary.

## 1. Entry, registration and transport boundaries

**World Bank.** `python -m data360.mcp_server --transport stdio` enters `WB/mcp_server/__main__.py:9–28`; package initialization imports tools/resources/prompts and the common FastMCP instance. The CLI defaults are streamable HTTP on port 8021, differing from the README's older HTTP/8000 guidance. The project version is 0.1.2, the README suggests 0.1.3, and the server instance advertises 0.1.0: use file hashes, not a single advertised version, to identify this contract. The server definition widens allowed HTTP hosts/origins to `["*"]` when unset; no authentication provider is configured in that definition. This does not characterize every ASGI deployment wrapper. Relevant registrations are `WB/mcp_server/tools.py:810–848`. Do not treat vendor prompts/resources as host instructions.

`DATA360_API_BASE_URL` is a required settings field in code, not a code-default URL; `api_url` appends `/data360`. HUB supplies `https://data360api.worldbank.org`, stdio, `MCP_ENV=local` and `FASTMCP_CHECK_FOR_UPDATES=off` (`HUB:231–234,380–387`). API/config/entry modules call dotenv loading. Keep the existing controlled child working directory/env boundary; a plain source import can have environment and dependency side effects.

**U.S. government.** Package `bin` resolves to `dist/server.js`; `src/server.ts:31–78,83–109,162–286,518–528` imports dotenv, discovers/imports API modules, then selects active modules and registers tools. Selection narrows the served tools **after module imports**, not before them. Default transport is stdio, default tool mode `full`. Discovery mode exposes `find_tools`/`call_tool` plus auxiliary tools; do not assume native Treasury names are directly listed in that mode. The chosen treasury/usaspending/sec `index.ts` files export metadata plus their actual tools and SDK cache clearer.

HUB already chooses a curated module list, injects `MAX_RESPONSE_BYTES="40000"` and a dedicated `XDG_CACHE_HOME` (`HUB:72–109,384–445`). Do not widen into other US modules for this slice. Optional HTTP has a separate bearer-token/loopback policy in `US/server/http-auth.ts:21–78`; stdio needs no MCP HTTP token. SEC's contact email is a User-Agent input, not an API key.

HUB returns `CallResult(ok,text,error,elapsed_s,structured,is_tool_error)`; `ok` only tests transport/MCP `isError`, not JSON-body `error`, validation warnings or completeness (`HUB:150–159,1127–1145`). Data360 returns Pydantic models/dicts through FastMCP; U.S. builders return JSON **strings**, normally carried in MCP text content. This study does not import FastMCP to assert its exact outer serialization. The consumer must accept the expected logical payload from `structuredContent` or JSON text, validate it, and fail on conflicting representations or unparsable/clipped output.

## 2. World Bank native tool contract

The arguments below come from `WB/mcp_server/tools.py:67–308`, not internal REST parameter names.

| Native tool | Exact selected arguments/defaults | Logical result / restriction |
|---|---|---|
| `data360_search_datasets` | `query: str`; `limit=10`; `offset=0` | `items[{idno,name,description,data_classification,data_last_updated,economies_count,time_period}]` plus count/total_count/offset/has_more/next_offset/error |
| `data360_search_indicators` | `query=null,required_country=null,limit=5,offset=0,queries=null,query_groups=null,result_layout="merged",dedupe=true,database=null` | Single-query `indicators`; multi-query merged or `results` grouped by query; per-group errors possible |
| `data360_get_metadata` | Required `database_id,indicator_id`; `select_fields=null,fetch_disaggregation=true,required_country=null` | `indicator_metadata,disaggregation_options,error,stale` |
| `data360_get_disaggregation` | Required `database_id,indicator_id`; `required_country=null` | `{"dimensions":[...]}` or `{"error":"..."}` |
| `data360_get_data` | Required `database_id,indicator_id`; `country_code=null,disaggregation_filters=null,start_year=null,end_year=null,limit=50,offset=0,ref_area_filter="member_economies_only",year=null` | `data,metadata,count,total_count,offset,has_more,next_offset,error,failed_validation` |
| `data360_find_codelist_value` | Required `codelist_type,query`; `limit=5` | List of code/label match dictionaries; use codes, not guessed country names, in fetch |
| `data360_list_indicators` | Required `database_id` | List of indicator strings; no pagination argument. Code raises HTTP failures despite docstring suggesting empty list on errors |
| `data360_get_data_api_url` | Required `database_id,indicator_id`; `country_code=null,start_year=null,end_year=null,disaggregation_filters=null,year=null` | URL string; metadata lookup still makes HTTP requests; not a fetch receipt or complete-dataset guarantee |

Single search must choose `query`, `queries`, or `query_groups`. A one-element `queries` list is actually rewritten to `query` by the wrapper, despite its stricter prose. The internal SearchRequest validates limit 1–50 and sanitizes punctuation; do not pass internal aliases such as `skip`, `select_fields` or `odata_options` to the MCP search wrapper. `required_country` supports semicolon-separated codes/names; `country_code` is the fetch argument. Multi-query has a different result model and candidate/dedup counts, not one dependable global observation cursor. Prefer single-query discovery in the initial adapter.

Source trace: search POST uses `/data360/portal/v1/public_data360_search` with `site,query_string,types,data_classification,skip,items_per_page`; indicator search adds resolved `economy_codes` and database names. Search normalizes both legacy nested and flat V3 records (`WB/api.py:590–784`). Search can redirect to primary `database_id/idno`, with `primary_source_of`; title/coverage originally came from the search record and must be checked against separate metadata. Search's `covers_country=true` may be inferred from a single-country V3 filter rather than an observed nonmissing row (`WB/api.py:818–993,1397–1493`). Search metadata is discovery evidence, not a value.

**Native request examples** — each object is a separate tool call:
```json
[
  {"tool":"data360_search_datasets","arguments":{"query":"World Development Indicators","limit":5,"offset":0}},
  {"tool":"data360_search_indicators","arguments":{"query":"GDP growth","required_country":"CHN","database":"IMF_WEO","limit":5,"offset":0}},
  {"tool":"data360_get_metadata","arguments":{"database_id":"IMF_WEO","indicator_id":"IMF_WEO_NGDP_RPCH","required_country":"CHN","fetch_disaggregation":true}},
  {"tool":"data360_get_disaggregation","arguments":{"database_id":"IMF_WEO","indicator_id":"IMF_WEO_NGDP_RPCH","required_country":"CHN"}},
  {"tool":"data360_get_data","arguments":{"database_id":"IMF_WEO","indicator_id":"IMF_WEO_NGDP_RPCH","country_code":"CHN","start_year":2024,"end_year":2027,"limit":2,"offset":0,"ref_area_filter":"none"}}
]
```

**Synthetic logical result examples**, using source-defined field names:
```json
{
  "indicators":[{"idno":"IMF_WEO_NGDP_RPCH","database_id":"IMF_WEO","database_name":"World Economic Outlook","name":"Fixture real GDP growth","truncated_definition":"Synthetic contract data","periodicity":"Annual","latest_data":"2027","time_period_range":"2024-2027","covers_country":{"CHN":true},"requested_country":"CHN","dimensions":null,"primary_source_of":null}],
  "required_country":"CHN","country_names":{"CHN":"China"},
  "count":1,"total_count":1,"offset":0,"has_more":false,"next_offset":null,"error":null
}
```
```json
{
  "indicator_metadata":{"idno":"IMF_WEO_NGDP_RPCH","database_id":"IMF_WEO","name":"Fixture real GDP growth","periodicity":"Annual","measurement_unit":"Percent change","sources_note":"Synthetic provenance note","database_name":"World Economic Outlook"},
  "disaggregation_options":[{"field_name":"TIME_PERIOD","field_value":["2024","2025","2027"]},{"field_name":"REF_AREA","count":1,"queried":{"CHN":true}}],
  "error":null,"stale":false
}
```
```json
{
  "data":[{"TIME_PERIOD":"2025","REF_AREA":"CHN","OBS_VALUE":"null","UNIT_MEASURE":"PT","claim_id":"00000002"},{"TIME_PERIOD":"2024","REF_AREA":"CHN","OBS_VALUE":"4.0","UNIT_MEASURE":"PT","claim_id":"00000001"}],
  "metadata":{"idno":"IMF_WEO_NGDP_RPCH","database_id":"IMF_WEO","periodicity":"Annual","measurement_unit":"Percent change","database_name":"World Economic Outlook"},
  "count":2,"total_count":3,"offset":0,"has_more":true,"next_offset":2,"error":null,"failed_validation":null
}
```
The corresponding disaggregation-only result is `{"dimensions":[...]}`, **not** `disaggregation_options`. This fixture deliberately has a missing value and a coverage gap; `latest_data` is not proof that every requested period has a value. Search's declared `EnrichedIndicator` has no `unit` field, even though enrichment tries passing one; fetch metadata separately (`WB/models.py:172–236; api.py:959–971`).

### Metadata, missingness, paging and time restrictions

- **Windows:** neither bound means current calendar year minus four through current year; end-only means the five-year window ending there; start-only means through max(start,current year); reversed bounds are swapped. `year` fills only bounds that were not supplied. Native fetch has no `auto_resolve_time_range` argument. Always send both bounds and validate order before the call; a forecast fetch needs an explicit future end year (`WB/api.py:2069–2215`).
- **One raw page:** limit defaults 50 and is capped at 100. Upstream request uses `skip=offset,top=limit+1`, trims the sentinel row, computes next_offset from upstream rows, **then** sorts that page descending and may filter geography. No upstream ordering/snapshot token is requested. Sort all gathered observations only after paging. Continue on `has_more` even when filtered `count=0`; verify monotonic cursor progress, repeated-page fingerprints, bounded budgets and all page receipts. `total_count` can be null or count rows excluded later (`WB/api.py:2296–2386`).
- **Country/dimensions:** wrapper default member-economy filtering applies only when REF_AREA is unpinned; use `ref_area_filter="none"` for an explicitly selected aggregate. Disaggregation REF_AREA is summarized as count/sample or count/queried, never a complete code list; FREQ/INDICATOR and trivial totals are stripped. Unknown filters pass through; invalid known values are dropped with `failed_validation`, potentially widening the requested series. FREQ is silently skipped. Reject unsupported filters and unresolved dimension ambiguity in the adapter (`WB/api.py:363–438,456–587`).
- **Conflicting geography:** code sets `country_code` into params before `params.update(effective_disagg)`; an explicit REF_AREA in disaggregation can overwrite it despite the docstring's precedence claim. Do not send conflicting values. `failed_validation` can also contain a harmless pinned-country filter note, so distinguish warnings by meaning; do not indiscriminately treat every note as an invalid filter.
- **Units/raw values:** rows retain OBS_VALUE without numeric conversion. Core kept fields include TIME_PERIOD, REF_AREA/name, UNIT_MEASURE/name, UNIT_MULT, claim_id; selected nontrivial SEX/AGE/URBANISATION/COMP_BREAKDOWN_1/2 survive. Fields such as FREQ, OBS_STATUS, confidentiality/status flags, vintage, and COMP_BREAKDOWN_3 do not survive the allowlist. Retain raw strings, parse only finite numeric values, preserve JSON null and literal null/nan/none/blank as missing, and reject booleans/nonfinite values. Do not use zero for missing (`WB/api.py:164–245,363–381,2322–2359`).
- **Scale:** UNIT_MEASURE_NAME may be prefixed thousand/million/billion/trillion according to UNIT_MULT; the fetch does **not** numerically rescale OBS_VALUE. Do not apply a multiplier twice. Conflicts with catalog unit overrides remain conflicts until verified; magnitude alone is not authority. Frequency comes from metadata, not a retained row FREQ. A catalog A value cannot resolve a contrary or absent provider frequency.
- **Metadata degradation:** metadata has `stale` and `error`; its cache is 24 hours with retained last-good snapshots and a 30-second degraded cooldown. Fetch tolerates nonfatal metadata errors, and returns only the metadata dictionary with `error=null`; the outer stale/error warning can be lost. Store the separate metadata-tool result and its retrieval time. Dimensions cache 10 minutes; disaggregation cache 24 hours; these are not vintages (`WB/api.py:70–148,1752–1944,2227–2261`).
- **As-of/projections:** dataset search optionally exposes `data_last_updated`, but the selected data tools have no vintage/release/as-of selector or dependable retained observation-status flag. Latest metadata, observation period, source update time, official forecast vintage and DRF retrieval time are different fields. Preserve WEO/GEP as projection-capable datasets with per-point status unknown unless source-backed separately; WDI may contain estimates/revisions. Local snapshot hashes prevent later accidental mutation, not historical look-ahead.
- **Links:** catalog human URL is `https://data360.worldbank.org/en/indicator/<indicator>`. Persist the exact native request and all page payload hashes plus metadata/source notes; record official original producer (IMF/World Bank) separately from Data360 delivery. URL tool builds `/data360/data` with top at least 1000 and no paging; it neither honors a configured data_url override nor resolves omitted time bounds like get_data. It still fetches metadata, and its filters can override REF_AREA. It is unsuitable as sole evidence of the fetched dataset (`WB/api.py:2480–2590`).
- **Avoid aggregate-only proof:** internal _fetch_all_pages stops after 50 × 100 rows or a later body error, then returns `has_more=false,total_count=len(collected)` without a partial marker. Raised errors may instead abort. Prefer caller-controlled raw paging for auditable charts; do not infer completeness from a summary/ranking result (`WB/api.py:2600–2703`).

### World Bank HTTP/client boundary

No selected data request attaches an API key. Search, metadata and dimensions use marked read-only POSTs; data is GET. Split interactive timeouts are connect/pool 3s and read/write 8s, with up to three attempts, backoff base 0.3s/max 2s and retry statuses 429/502/503/504. The 16s retry budget checks whether to schedule another attempt, not a hard cancellation deadline for the whole tool; metadata, dimensions and data can each consume separate request budgets. Retry-After is not interpreted by this transport. No proactive token bucket is present in the inspected client; do not invent an official quota (`WB/config.py:76–204; http_client.py:90–203`).

Background codelists use a separate pool/read timeout (30s)/retry budget (60s); label loading waits at most two seconds inline and can return raw codes while refresh continues. Database labels use bundled fallback data and background refresh. These labels are conveniences, not a frozen official revision (`WB/config.py:212–261; providers.py:34–73,883–971`). Errors may arrive as JSON-body error fields, raised Data360MCPError, or partial metadata. HTTP error text strips HTML and truncates messages; do not assume error_code survives MCP framing (`WB/errors.py:61–109,113–219,339–367`).

## 3. U.S. government native contracts

### Discovery and common result decoding

With full mode use `treasury_list_datasets({})`, `treasury_search_datasets({"query":"debt"})`, then `treasury_get_endpoint_fields({"endpoint":"/v2/accounting/od/debt_to_penny"})`. Search/list use a **bundled endpoint catalog**, not live discovery of the entire current government API. The field tool performs a one-row upstream request and returns `data.items[{name,label,type,format}]`, with `meta.endpoint,totalRecords` (`US/apis/treasury/tools.ts:16–101; sdk.ts:1444–1477`).

In discovery mode:
```json
[
  {"tool":"find_tools","arguments":{"query":"treasury debt","module":"treasury","limit":8}},
  {"tool":"call_tool","arguments":{"name":"treasury_query_fiscal_data","arguments":{"endpoint":"/v2/accounting/od/debt_to_penny","fields":"record_date,tot_pub_debt_out_amt","sort":"-record_date","page_number":1,"page_size":2}}}
]
```
`find_tools` returns JSON `{summary,dataType:"list",data:{items:[{name,module,title?,description,inputSchema,note?}]}}`. inputSchema is generated from Zod in input mode with `$schema` removed; conversion failure falls back to `{type:"object"}`, so an empty schema is not proof that the data tool takes no arguments. It defaults query empty/limit8, validates limit 1–25, and requires query or module. `call_tool` defaults arguments to {}, validates through the same registry, then returns the underlying tool's JSON text. Use canonical prefixed names; deprecated Treasury aliases may add a separate non-JSON note block (`US/server/discovery.ts:28–45,100–162; tool-registry.ts:158–201; apis/treasury/meta.ts:14–20`).

Decode tables by the **returned columns on each page**, not fixed positions or one shared page-one schema. Shared conversion turns undefined/null/empty string into null, drops all-null columns, and leaves numeric strings as strings. Table total is upstream total, while truncated only tracks the local row cap (10,000), not unread upstream pages. Empty results become `{summary,dataType:"empty",data:null}`, and Treasury's table builder discards the requested meta on an empty page. Lists cap items at 1000 (`US/shared/response.ts:99–158,400–485`).

The server wraps results with `meta.sources[{url,fetchedAt,cached?,method?}]`, then applies its UTF-8 budget. Cached fetch time is the original upstream fetch time. Source lists deduplicate by method+URL, cap at ten, and omit POST bodies; preserve native arguments/body reconstruction separately. Budget shortening can cut rows, columns, source arrays or strings and adds `truncatedToFit`; `data.truncated` may also be true. Stats/totals/recordsReturned may describe the **pre-shortened** rows. Reduce page size and refetch the same page before advancing. If clipping yields unparsable text, reject it. `code_mode` calls raw registry output and cannot substitute for complete raw observations/provenance (`US/server/serve-tool.ts; sources.ts; response-budget.ts; shared/request-context.ts`).

### Treasury fiscal data

Exact native `treasury_query_fiscal_data` arguments:
```json
{
  "endpoint":"/v1/accounting/mts/mts_table_3",
  "fields":"record_date,line_code_nbr,src_line_nbr,classification_desc,current_month_rcpt_outly_amt",
  "filter":"line_code_nbr:eq:520,record_date:gte:2025-01-01,record_date:lte:2025-03-31",
  "sort":"-record_date",
  "page_number":1,
  "page_size":2
}
```
Required endpoint is string; fields/filter/sort are optional strings. page_number is positive integer; page_size is positive integer ≤10,000. The schema's optional page fields have no defaults inserted; the SDK omits absent page params, while descriptions state upstream defaults page1/size100. Always send them explicitly. SDK translates to query parameters `format=json,fields,filter,sort,page[number],page[size]` on its fixed Fiscal Data base URL. Native spelling is **filter**, never recipe spelling **filters** (`US/apis/treasury/tools.ts:104–147; sdk.ts:1481–1495`).

Synthetic text-JSON payload for that call:
```json
{
  "summary":"Query /v1/accounting/mts/mts_table_3: 2 returned, 3 total, page 1 of 2",
  "dataType":"table",
  "data":{
    "columns":["record_date","line_code_nbr","src_line_nbr","classification_desc","current_month_rcpt_outly_amt"],
    "rows":[["2025-03-31","520","71","Fixture deficit","-10"],["2025-02-28","520","72","Fixture deficit","null"]],
    "total":3,"truncated":false
  },
  "meta":{
    "endpoint":"/v1/accounting/mts/mts_table_3","recordsReturned":2,"totalPages":2,
    "sources":[{"url":"https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/mts/mts_table_3?format=json&fields=record_date%2Cline_code_nbr%2Csrc_line_nbr%2Cclassification_desc%2Ccurrent_month_rcpt_outly_amt&filter=line_code_nbr%3Aeq%3A520%2Crecord_date%3Agte%3A2025-01-01%2Crecord_date%3Alte%3A2025-03-31&sort=-record_date&page[number]=1&page[size]=2","fetchedAt":"2026-10-11T16:00:00.000Z"}]
  }
}
```

The MCP handler drops raw Fiscal Data `meta.labels,dataTypes,dataFormats` and `links.self/first/prev/next/last`; field discovery must be recorded separately. It retains totalPages and total-count as data.total; it does **not** return page_number structurally. Caller owns the page counter, requested date bounds and request fingerprint. Continue to totalPages, verify pages/totals consistently, and mark incomplete on any failed/clipped page. Neither `data.truncated=false` nor one latest record proves a complete time series. There is no vintage/as-of input, release timestamp, projection flag, frequency or geography normalization in this handler; attach catalog/verified field metadata with its provenance and retrieval time.

Record row keys before any collapse. Catalog MTS recipes include line_code_nbr, src_line_nbr and classification_desc expressly to avoid unwanted upstream aggregation; the selected SDK merely forwards fields and does not enforce this behavior. Verify row-key/aggregation expectations later rather than claiming them proven here. Select the intended row (130 receipts/490 outlays/520 surplus-deficit), preserve sign and NSA monthly meaning, and never sum subtotal/total classifications. Debt stock, monthly flow, cost-of-outstanding-debt rate and quarter-end accounting FX are different quantities. FX's smallest-effective_date policy is the catalog's chosen quarter-end view, not an as-of selector; retain all amendments and define the selection policy.

### USAspending selected series

`usa_spending_over_time` has optional `group` enum month/quarter/fiscal_year, `start_date,end_date,agency,state,keyword` strings, and `award_type` enum contracts/grants/loans/direct_payments. Default group month; omitted dates become today minus three years through today. Exact catalog-total call:
```json
{"tool":"usa_spending_over_time","arguments":{"group":"fiscal_year","start_date":"2024-10-01","end_date":"2025-09-30"}}
```
SDK POSTs `/api/v2/search/spending_over_time/` with `{"group":"fiscal_year","filters":{"time_period":[{"start_date":"2024-10-01","end_date":"2025-09-30"}]}}`. Optional filters use awarding top-tier agency name, award codes, place-of-performance state (not recipient geography), and keywords. Handler emits date/value/fiscalPeriod columns, **not** the SDK's fiscalYear/month/quarter columns (`US/apis/usaspending/tools.ts:158–187; sdk.ts:471–514`).

Synthetic result:
```json
{
  "summary":"Federal spending over time: 1 periods, grouped by fiscal_year (fiscal periods; periodStart is the calendar month each begins)",
  "dataType":"timeseries",
  "stats":{"count":1,"min":120,"max":120,"mean":120,"first":{"date":"2024-10","value":120},"last":{"date":"2024-10","value":120},"change":0,"changePct":0,"cagrPct":null,"trend":null},
  "data":{"columns":["periodStart","amount","fiscalPeriod"],"rows":[["2024-10",120,"FY2025"]],"total":1,"truncated":false},
  "meta":{"group":"fiscal_year","sources":[{"url":"https://api.usaspending.gov/api/v2/search/spending_over_time/","method":"POST","fetchedAt":"2026-10-11T16:00:00.000Z"}]}
}
```
Fiscal month1=October of prior calendar year; FY2025 starts 2024-10; fiscal quarter1=Oct–Dec. Preserve period type and fiscal label, rather than labeling this as calendar-year 2024 (`sdk.ts:110–143`). No paging, total-period count or upstream revision marker is exposed. data.total is just the mapped result length. Fixed dates/group and budget checks are essential; short requests can include partial fiscal periods. Missing results become an empty list, and **`Number(r.aggregated_amount || 0)` converts absent/null/blank amounts to zero**. That information is already lost before MCP; a bridge parser cannot recover it. An observed zero cannot be certified as nonmissing solely from this result. Do not present coverage/missingness-sensitive statistics as authoritative without an additional source-backed validation path. Catalog describes obligations rather than budget outlays; retain that distinction and its source, and do not equate this with Treasury MTS totals.

### SEC selected company-concept template

Exact native call:
```json
{"tool":"sec_company_concept","arguments":{"cik":"0000320193","concept":"RevenueFromContractWithCustomerExcludingAssessedTax","taxonomy":"us-gaap"}}
```
`cik,concept` are required strings; taxonomy enum us-gaap/ifrs-full/dei/srt defaults us-gaap. Numeric CIK is padded to ten digits. Ticker/name resolution queries EDGAR entity search and uses exact ticker match or the first name match; persist resolved identity, and do not treat a fuzzy first hit as established company identity (`US/apis/sec/sdk.ts:418–426`).

Synthetic result:
```json
{
  "summary":"Fixture company — RevenueFromContractWithCustomerExcludingAssessedTax (Fixture revenue): 2 annual + 0 quarterly observations [USD]",
  "dataType":"record",
  "record":{"entityName":"Fixture company","concept":"RevenueFromContractWithCustomerExcludingAssessedTax","label":"Fixture revenue","unit":"USD","annual":[{"period":"2024-09-28","value":100,"fy":2024,"filed":"2024-11-01"},{"period":"2024-09-28","value":110,"fy":2025,"filed":"2025-11-01"}],"quarterly":[]},
  "meta":{"sources":[{"url":"https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/RevenueFromContractWithCustomerExcludingAssessedTax.json","fetchedAt":"2026-10-11T16:00:00.000Z"}]}
}
```
HTTP404 is converted into dataType empty, not a numeric zero or generic tool error. SDK chooses USD if present, otherwise the first unit; native arguments cannot select a unit. Classification is by form prefix: 10-K/20-F/40-F (including amendments) versus 10-Q. Then it takes last20/last12 **rows in upstream order**, without date sorting, unique-period counting, a truncation marker or paging/date filters. Handler drops start/end distinction (end becomes period), form, accession, frame, description, cik and taxonomy from its record (`US/apis/sec/sdk.ts:322–349; tools.ts:201–235`).

Consequences: do not label last20 annual-form rows as 20 annual observations. A 10-K can include quarterly comparisons; rows with the same end date may describe different duration starts. “Latest filed per period” alone cannot safely disambiguate these. As-of filtering filed ≤cutoff is necessary for hindsight control but cannot reconstruct discarded earlier rows. Missing-start/accession provenance and silent slicing make complete annual/as-of charts unsupported through this result. Return an explicit unsupported/limited result until a reviewed contract can preserve those fields and period semantics. Use record.unit, not the generic catalog template's dollars/A assumptions (EPS/shares/other concepts differ). A company series is entity-specific, not automatically a USA macro series.

### U.S. HTTP/auth/cache/rate/error boundaries

Selected Treasury and USAspending clients have no API-key configuration. SEC supplies a User-Agent derived from package version and optional SEC_CONTACT_EMAIL; it warns once if email is absent, but does not refuse the request. This establishes code behavior, not guaranteed SEC access or current government policy.

Per-client configured token buckets: Treasury10/s burst20; USAspending5/s burst15; SEC data10/s burst10 (its search has a separate bucket). These are **local pacing choices**, not verified official quotas and not aggregate cross-process enforcement. Shared client defaults attempt timeout30s, deadline max(45s,timeout), retries2 (three attempts); USAspending sets timeout60s/deadline60s. Retry statuses 429/502/503/504 and transport exceptions use backoff; Retry-After >20s fails rather than sleeping inside the tool. Body read/JSON parsing errors surface after fetchRetry. Token acquisition itself is not deadline-cancelled, so caller-owned overall budgets remain needed (`US/shared/client.ts:123–189,221–325,338–351`).

TTL30min caches for the selected clients persist on disk under XDG_CACHE_HOME or the normal home cache, layout v3; files 0600/directories0700, atomic replacement, expired entries are misses and fallback is bounded process memory. Cache identity excludes env-backed credentials and includes public POST body, but provenance source URLs omit POST body. Preserve original fetchedAt and separate DRF retrieved_at; neither is source release/vintage. Redirect cache roots with XDG_CACHE_HOME, without changing HOME. Configured env auth elsewhere is omitted when missing, and errors may include a truncated upstream body; redact host-side as well (`US/shared/client.ts:353–495,513–538; shared/disk-cache.ts:1–166,239–279`).

## 4. Mapping existing catalog IDs to native requests

This is a contract mapping, not a claim that a complete consumer adapter exists.

| Catalog ID / family | Native mapping | Required interpretation |
|---|---|---|
| `wb:IMF_WEO_NGDP_RPCH/CHN` | database=IMF_WEO, indicator=IMF_WEO_NGDP_RPCH, country_code=CHN → data360_get_metadata/disaggregation/get_data | Explicit historical+future bounds; annual percent change; official projection status/vintage not exposed per row |
| `wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN` | database=WB_WDI, indicator=WB_WDI_NY_GDP_MKTP_KD_ZG, country_code=CHN | WDI GDP growth; distinguish estimates/revisions and missing years |
| `wb:WB_WDI_SP_POP_TOTL/WLD` | database=WB_WDI, indicator=WB_WDI_SP_POP_TOTL, country_code=WLD, ref_area_filter=none | Explicit world aggregate; do not sum countries and their aggregates together |
| `wb:WB_GEP_NYGDPMKTPKDZ/EMU` | database=WB_GEP, indicator=WB_GEP_NYGDPMKTPKDZ, country_code=EMU | Coverage/horizon must come from returned metadata/data, not old catalog prose |
| `usgov:treasury/debt_to_penny` | treasury_query_fiscal_data; endpoint /v2/accounting/od/debt_to_penny; fields record_date,tot_pub_debt_out_amt | D, dollar stock, USA; explicit dates/page/sort |
| `usgov:treasury/debt_held_public` | same endpoint; fields record_date,debt_held_public_amt | Different debt definition; do not conflate with total public debt |
| `usgov:treasury/mts_receipts` / mts_outlays / mts_deficit | endpoint /v1/accounting/mts/mts_table_3; fields from _MTS_FIELDS; filter line_code_nbr:eq:130 /490 /520 | M, NSA, dollars; preserve all row-key fields and deficit sign |
| `usgov:treasury/avg_interest_rate/Treasury Bills` | endpoint /v2/accounting/od/avg_interest_rates; fields record_date,security_type_desc,security_desc,avg_interest_rate_amt; filter security_desc:eq:Treasury Bills | Case-preserved parameter, percent, monthly; cost of outstanding debt, not market yield |
| `usgov:treasury/fx/China-Renminbi` | endpoint /v1/accounting/od/rates_of_exchange; fields record_date,country_currency_desc,exchange_rate,effective_date; filter country_currency_desc:eq:China-Renminbi | Q accounting FX; keep amendments/effective_date; units foreign currency per USD |
| `usgov:spending/total` | usa_spending_over_time(group=fiscal_year,start_date=...,end_date=...) | A fiscal periods, USD award amounts; partial-period/missingness limitations |
| `usgov:sec/AAPL/RevenueFromContractWithCustomerExcludingAssessedTax` | sec_company_concept(cik=AAPL,concept=RevenueFromContractWithCustomerExcludingAssessedTax,taxonomy=us-gaap) | Template only, absent from CATALOG entries; resolved CIK/unit/duration/as-of provenance required |

Trace: `CAT:215–438,511–552,569–575,1323–1476,1513–1538`. wb_database derives the first two underscore components and allows only WB_WDI/IMF_WEO/WB_GEP; discovered datasets outside that set cannot be routed by that helper without an explicit future decision. lookup only returns a curated entry, not any syntactically valid discovered ID. The SEC template can resolve through resolve_usgov_recipe while lookup still returns None. Recipe keys match case-insensitively; suffix parameters preserve case for native filters. Do not lowercase Treasury security/currency names.

For Treasury, compose catalog `filters` plus parameter field filter and BOTH date bounds into native `filter`; pass page_number and page_size, retaining all declared fields. Preserve source_url (human citation) separately from api_url/native request; URLs are not interchangeable. WB/USgov catalog frequency/unit/geography values are curated metadata claims, with validation status recorded. HUB's current registration supports transport and result delivery; it does not itself normalize these native payloads or verify their semantics.

## 5. Minimal deterministic fake-MCP acceptance probes

**Proposed, not executed.** These are fixture/probe specifications for the lead's implementation tests. Run against a bridge-owned fake MCP session/stdio fixture; list only the selected source tool schemas and assert every tools/call name/argument object. No vendor import/process/build/dependency/network should be involved. Use fixed UTC time 2026-10-11T16:00:00Z, fixed synthetic rows and deterministic native-result serialization. Test JSON text and structuredContent handling; isError=false must not mask body error, truncation or missing metadata.

| Probe | Native fixture transcript | Observable stopping condition and negative control |
|---|---|---|
| WB-1 raw paging/metadata | metadata/disaggregation fixtures above; get_data offset0/limit2 returns above page; offset2 returns 2027 value5.0, count1, total3, has_more=false,next_offset=null | Exactly offsets0,2 with unchanged CHN/indicator/bounds; stored raw3 rows, chronological chart points 2024=4,2025=missing,2027=5; no interpolated2026. Separate metadata receipt, row hashes and request hashes. Projection status remains unknown without a distinct fixture-backed official release policy |
| WB-1 negative variants | Page1 body error, stale metadata with error, invalid filter warning, repeated next_offset, page2 isError=true, contradictory REF_AREA, nonfinite/bool values | No authoritative complete chart/anchor from partial or ambiguous data; no numeric zero for missing; conflict rejected before tools/call. Add all-aggregate empty filtered page with has_more=true to prove pagination continues. Stale metadata stays visible |
| US-T1 Treasury | Query above page1; page2 contains January value "-3", global total3/totalPages2. Permute returned columns on page2. Field discovery is separate listResponse | Exactly native filter (not filters), page1 then2, correct bounds/row keys; two finite values and one missing, negative sign intact; source URLs/original fetchedAt preserved. Every page reconciled before complete=true |
| US-T1 truncation variant | Page1 says recordsReturned2 but only1 row remains and truncatedToFit is present; smaller page_size fixture succeeds | Refetch page1 with smaller page_size before advancing, restarting paging consistently if page size changes; never skip omitted rows. Tool error, malformed JSON, empty inconsistent page, missing value column and changing totals cause explicit incomplete/error outcome |
| US-A1 fiscal mapping | usa_spending_over_time explicit FY window returns one-row fixture above; variant includes fiscal quarter FY2025 Q1 with periodStart2024-10 | Stored A/FY2025 amount120, no calendar-year2024 relabel; POST arguments preserved because source URL omits filters. A wrapper zero without upstream missingness proof remains flagged/limited, never certified as a nonmissing official observation |
| US-S1 limited concepts | sec_company_concept numeric CIK returns duplicate-period fixture above; negative variants empty404, non-dollar unit, all returned filings after cutoff | Retain reported facts/retrieval provenance without claiming complete annual history; refuse complete annual/as-of chart. Dedup alone must not turn unknown-duration records into annual values. No-data stays empty; unit follows record.unit. No rows after historical cutoff admitted |

For WB add a unit-scale fixture with OBS_VALUE="2", UNIT_MULT="6", UNIT_MEASURE_NAME="million people": retain raw2 and exponent6; normalized base-person value, if explicitly chosen, is2,000,000 exactly once. A row with no trustworthy unit/frequency must not inherit silent chart certainty.

These fixtures prove adapter behavior only. They cannot prove live endpoint availability, actual Treasury aggregation, a projection horizon, SEC missing duration fields recovered, or distinguish a USAspending server-created zero from a true zero. Future source-side/live validation must be separately authorized and labeled.

## 6. Required ingestion/chart invariants for the shared implementation

1. Persist native request, provider/dataset/indicator or recipe/entity identity, requested bounds, each page/offset, raw payload and SHA-256, metadata payload/hash, DRF retrieved_at, original upstream fetchedAt/cache flag where supplied, and completion/failure reason. Never declare the study's source hashes to be hashes of observations.
2. Keep source period, source release/update time, forecast vintage, historical as-of cutoff and local snapshot time distinct. Unknown means unknown. Never use current WEO/GEP projections, later SEC restatements or current Treasury amendments to auto-resolve a historical cutoff without appropriate evidence.
3. Preserve raw values/missingness and original units/multipliers. Validate finite numerics and all series dimensions before sorting/dedup; reject unexplained duplicate periods. Choose explicit fiscal/calendar and stock/flow semantics. Do not use rounded vendor stats or model-transcribed values as observation authority.
4. Charts use stored complete validated observations; show missing gaps, source captions and verified unit/frequency. Distinguish actuals, estimates, official projections and DRF model/simulation forecasts only when their status is grounded. Unknown status receives an explicit label; date alone is insufficient. Reconcile forecast overlays to the same unit/geography/period basis.
5. Source missing/unavailable/unsupported/partial is an explicit result. A failed page never becomes an empty complete series. Saved-run reuse requires frozen request/input/provenance identity; current latest-data calls cannot silently replace an earlier snapshot.

## Verification and remaining work

This study used read-only file inspection and stdlib hashing only. It did not run/import/install vendor code, tests, MCP servers or dependencies, and did not call a network endpoint. No app/config/vendor/skill/branch changes were made. Only the two owned study files were written; unrelated concurrent working-tree changes were preserved.

The coverage receipt identifies selected files/ranges, including full reads of some small boundary files, not whole-vendor or whole-app coverage. Unread provider modules, generated dist/runtime dependencies, UI/chart implementations, tests and original live-probe scratchpads are outside this evidence. Exact emitted wire framing remains unverified until the fake transport/adapter acceptance is implemented; live data semantics remain a separate later validation task.

The user approved the shared integration plan during this study. Implementation belongs to the lead and authorized implementation owners; this document supplies the provider constraints to incorporate, without altering the shared plan or implementing an adapter.

**Next-session prompt:** “Read wb-usgov-study.md and wb-usgov-coverage.json. Implement the approved bounded provider adapters against their frozen shared contract. Start with WB-1 and US-T1 deterministic native-result fixtures, keep native/body errors and partial pages visible, retain metadata/status uncertainty, and leave unsupported SEC annual/as-of and USAspending missingness claims explicit. Preserve concurrent changes and do not treat the historical probes as live acceptance.”

## Closing updates

- 2026-10-12 Asia/Shanghai: Completed selected source-contract tracing, catalog mappings, synthetic native examples, and four source-specific deterministic acceptance specifications. No provider execution or live validation is claimed.
- 2026-10-11T16:55:39Z: Rehashed the 40 selected evidence files with no observed drift and parsed all 11 JSON examples. These are source/artifact checks, not executions of the proposed fake-MCP probes. The coverage receipt records final inclusive read ranges and separate source-depth labels.
