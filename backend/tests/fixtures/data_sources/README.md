# Official-data provider fixtures

Every provider payload here is a real response of the vendored MCP servers under `datamcps/`,
captured 2026-10-11 to 2026-10-14 through the data hub with the data layer's own requests.
Payloads are trimmed, never edited: windows are narrow, Data360 indicator metadata keeps only the
fields the adapter and the vintage rules read (`idno`, `database_id`, `database_name`, `name`,
`indicator_name`, `measurement_unit`, `periodicity`, `date_released`, `date_last_update`,
`version_statement`, `time_periods`), and IMF rows before a cut-off year are dropped (the IMF
server ignores `start_year`/`end_year`) with `row_count`/`total_rows_before_cap` set to the kept
rows. Fixtures are not evidence of current upstream availability.

## `provider_responses.json`

The shared `payloads` fixture of `test_data_sources.py`, one payload per provider key. Tests that
need a contradiction, a gap or a failure mutate a copy.

| Key | Tool call | Notes |
|---|---|---|
| `fred` | `fred_get_series` UNRATE 2024 | API route (keyed) |
| `bls` | `get_multiple_series` LNS14000000 2025–2026 | October 2025 `-` with footnote 9 (lapse in appropriations); January 2026 footnote 12 (population controls) |
| `bis` | `fetch_dataset` WS_CBPOL `M.US` 2024 | full SDMX row columns with labels |
| `imf_defs`, `imf` | `imf_get_parameter_defs` / `imf_fetch_data` PCPS `G001.POILBRE.USD.M` | rows from 2023 |
| `wb`, `wb_metadata` | `data360_get_data` page / `data360_get_metadata` WB_WDI GDP growth USA 2015–2025 | `UNIT_MEASURE` PC_A, metadata unit `%` |
| `treasury` | `treasury_query_fiscal_data` MTS table 3 line 520, 2024 | |
| `spending` | `usa_spending_over_time` fiscal years from FY2023 | FY2027 is partial at capture |

## `real/providers/*.json`

Replay files for `test_data_sources_normalization.py`: `{captured_at, clock, series, request,
calls: [{provider, tool, args, response | error}]}`. Tests replay a file at its `clock`, so default
windows produce the recorded arguments. Captures: FRED UNRATE 2024 and 2025 (October 2025 null),
DGS10 daily (open October month), DFEDTARU daily across the 2025 FOMC cuts; BLS CES0000000001 +
LNS14000000 batch (code P preliminary payrolls); BIS WS_CBPOL US, WS_TC `770` credit, WS_XRU yen;
IMF PCPS Brent and the live WEO flow with the default projection window; Data360 WDI GDP growth
USA, IMF WEO real GDP growth CHN (default window, `COMP_BREAKDOWN_1=V_LST` rows), IMF WEO NGDPD USA
(whole-dollar values labelled `UNIT_MULT=9`) and GEP GDP growth CHN (version date 2025-02-25);
Treasury MTS deficit, Debt to the Penny daily and USAspending fiscal years.

## Directory index of `real/`

Every file under `real/` is listed here with the tests that read it. Normalized rows record
their normalization policy: policy 2 is the eac717b data layer (every aggregated month stored
`complete: false`; `observation_kind` re-derives completeness for those months, the rule
`forecast_extractor` applies), policy 3 is the current one.

| Path | What it holds | Read by |
|---|---|---|
| `providers/*.json` | raw MCP replay files (formats below) | `test_data_sources_normalization.py`, `test_data_sources_providers.py`, `tests/official_data_replay.py` (downstream helpers) |
| `catalog-native-units-2026-10-12.json` | distinct native unit attributes (`UNIT_MEASURE`, label, `UNIT_MULT`, row dimensions) for every curated `wb:` and `bis:` entry | `test_data_sources_normalization.py`, `test_data_catalog.py` |
| `catalog-usgov-recipes-2026-10-12.json` | live usgov responses for every Treasury MTS, EIA and BEA catalog recipe | `test_data_catalog.py` |
| `stored_v2/*.json` | trimmed policy-2 rows retrieved 2026-10-11 (DGS10 and Debt to the Penny daily-to-monthly, BIS policy rate, Data360 WEO China) with `head_page`/`head_brief`, the bytes the eac717b renderer produced: stored rows re-render byte for byte | `test_data_sources_interfaces.py`, `test_data_sources_normalization.py`, `test_official_data_downstream.py` |
| `forecast_carrier-2026-10-11.json` | 12-row policy-2 carrier (FRED, BIS, Data360, IMF, Treasury) as the forecast stage loads it | `test_forecast_extractor_official.py`, `test_report_visualizer_official.py` |
| `forecast_history_v3-2026-10-11.json` | policy-3 rows (UNRATE, DGS10, WDI GDP growth USA) with complete/partial periods, for empirical base rates | `test_forecast_extractor_official.py`, `test_report_visualizer_official.py` |
| `report_bundle-2026-10-11.json` | the same 12 series plus research `sources` and a DEXCHUS row, as a published report receives them | `test_report_official_publication_real.py`, `test_forecast_extractor_official.py`, `test_report_visualizer_official.py` |
| `v3_engine/series-2026-10-11.json` | 13 policy-2 rows of a v3 research run | `test_v3_official_data.py`, `test_official_data_downstream.py` |
| `v3_engine/series-2026-10-12.json` | 3 policy-3 rows of the live v3 run (DFEDTARU with an open month, BIS CPI year-on-year, WEO CPI to 2027) | `test_v3_official_data.py`, `test_official_data_downstream.py`, `test_orchestrator_research_wiring.py` |
| `gateway/series-2026-10-11.json` | 5 policy-2 rows as the v3 research tools store them (shared Data360 WEO page) | `test_research_gateway_official_data.py` |
| `legacy/series-2026-10-11.json` | 7 policy-2 rows as the legacy data tools receive them | `test_legacy_official_data.py` |
| `visuals/current/*.json`, `visuals/legacy/*.json` | one normalized row per file, current and policy-2, as the research chart renderer reads them | `test_data_visuals_official.py` |
| `downstream/fred_gepucurrent_stored.json` | a stored policy-3 GEPUCURRENT row (exact WEO/GEP prefixes) | `test_official_data_downstream.py`, `test_forecast_extractor_official.py` |
| `downstream/fred_cpi_yoy_unpublished_period_error.json` | the live `DataError` for an ended month FRED has not published yet | `test_official_data_downstream.py` |
| `agent_usage/carriers-2026-10-13.json` | six live policy-3 carriers fetched through the data layer for the six agent-usage audit questions (US CPI and the Fed, US data-center electricity, China NEV share, the ECB deposit facility rate, global semiconductor sales, 2027年中国GDP): FRED, BIS, Data360 (WEO, GEP, WDI), IMF PCPS and usgov EIA/BEA rows with values, statuses, periods and daily-aggregation provenance verbatim; verbose metadata dropped, web sources are placeholders that only fix `[S#]` positions | `test_official_data_agent_usage.py` |

Each normalized file records its own capture (`captured`, `capture` or `policy`) in its header.

## Provider routes (`test_data_sources_providers.py`, captured 2026-10-12)

Replay files in `real/providers/` (same format; a replay answers only the exact recorded
request, so the adapter must issue the same arguments at the capture clock):

| File | What it pins |
|---|---|
| `usgov_eia_sales_us_com_paged.json` | `eia_query` retail sales US commercial 2025, captured with a 5-row page (`patches`) — three pages, `data.total` 12 |
| `usgov_eia_capacity_bat.json`, `usgov_eia_crude_production.json` | annual capability rows (`stateId`, `capability-units`); crude production pinned by facet `series=MCRFPUS2` (`units` column `MBBL/D`) |
| `usgov_bea_real_gdp_growth.json` | `bea_gdp_national` T10101, years `2025,2026` then `2024` (8-observation cap per line) |
| `usgov_bea_value_added_514.json` | `bea_gdp_by_industry` industry 514, one year per call, roman quarters (`2025QIV`) |
| `fred_dgs10_long_split_api.json`, `fred_dgs10_long_split_csv.json` | DGS10 since 2010: native daily for the latest 24 months plus FRED's own monthly means before (API `frequency=m&aggregation_method=avg`; CSV `fq=Monthly&fam=avg`) |

Live texts and payloads without a series replay:

- `fred_errors_and_search.json`: the hub error for a nonexistent FRED id (`The series does not
  exist`) and for an unregistered key (`api_key is not registered`), and `fred_search`
  "semiconductor exports".
- `bls_messages_and_rejected_key.json`: a keyed request answering `No Data Available for Series …
  Year: 2027` and `Invalid Series for Series …`, and the `REQUEST_NOT_PROCESSED` answer to an
  unregistered key (key echo redacted by the hub). Observation lists trimmed to two rows.
- `wb_search_geographies.json`: `data360_search_indicators` with `required_country` `WLD`,
  `USA;CHN` and none (`covers_country` is only set for requested economies).
- `usgov_bea_unpublished_year.json`: the BEA error for a year not yet published (`Invalid year`).

## Empty BIS windows and FRED geography (`test_data_sources_providers.py`, captured 2026-10-13)

| File | What it pins |
|---|---|
| `bis_empty_window_and_unknown_key.json` | mcp-bis tool errors (`error` = the hub's clipped reason, `text` = the full isError text): `WS_LONG_CPI M.US.771` for 2026-09, an ended month BIS had not published (`ARE valid … genuinely empty result … most recent published observation is 2026-08`), `WS_CBPOL M.US` for a future month (with BIS's own series note) and the never-published key `M.ZZ`. The data layer reports `not_found` and `unknown_series`, so the resolution monitor keeps an unpublished period pending |
| `fred_search_discovered_national_geography.json` | `fred_get_series` for CORESTICKM159SFRBATL (outside the catalog) and `fred_search` by series id with `tag_names=nation;usa`, which returns the exact id: geography `USA` |
| `fred_search_discovered_untagged_geography.json` | the same two calls for NIKKEI225, whose title names no economy and which FRED does not tag `nation;usa`: geography stays unknown |

## Search relevance (`test_data_sources_providers.py`, captured 2026-10-14)

| File | What it pins |
|---|---|
| `search_relevance_2026-10-14.json` | the live discovery requests `DataSources.search` issued (limit 6) for agent `data_search` queries of the six audit questions — `fred_search`, `data360_search_indicators`, BIS `search_dataflows` and `treasury_search_datasets` for "global semiconductor sales", "new energy vehicle sales share" (also with China), "US electricity retail price", "euro area deposit facility rate" and "fed funds rate history". Data360 answers loosely ("Arms exports", "Mobile cellular subscriptions" for semiconductor sales; energy and CO2 shares for NEV share); FRED answers price queries with other average prices (ground beef, eggs). Results sharing no concept with the query are listed last with the `OFF_CONCEPT_NOTE` mark. FRED rows keep id/title/units/frequency/adjustment/range/notes, Data360 rows idno/database/name/periodicity/coverage |

`backend/scripts/datamcp_smoke.py` re-runs the whole catalog live (paced FRED, batched BLS, capped
IMF) and writes a JSON report; it is the way to refresh these captures' expectations.
