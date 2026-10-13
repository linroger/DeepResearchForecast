# Review of eac717b — findings and adversarial verdicts (exported from workflow wf_443ed4cc-922)


## review:providers: Provider fidelity + data layer (deerflow_bridge/data_sources.py, data_catalog.py, data_mcp.py, data_tools.py text contract, backend/app/services/offic

### P-UNITS BUG (critical) — On HEAD 78 of 104 wb+bis catalog entries are unfetchable: unit checks compare free-text metadata with SDMX codes through an incomplete fuzzy normalizer
- Location: deerflow_bridge/data_sources.py:737-773 (_sdmx_units), :788-824 (_wb_unit_parts/_wb_units), :1671 (COMP_BREAKDOWN_1 V_LST); data_catalog.py wb/bis entries (~1030-1475)
- Evidence: Live probe probe_units.py captured the real native fields for every wb and bis entry (units_wb.jsonl, units_bis.jsonl, per-entry table in unit_table.md, appended to the notes file). This goes beyond K2, whose 30/19 counts were measured WITH the scratch patch. On HEAD:

- wb: all 54 fail. Every IMF_WEO_* row carries COMP_BREAKDOWN_1='V_LST', which is rejected as 'ambiguous disaggregations'. Unit code vs metadata mismatches:
  - PC vs 'Percentage change'
  - PC_A vs '%'
  - PT_GDP vs '%'
  - PT_LF vs '% of total labor force'
  - PS vs 'Unit'
  - USD vs 'current US$'
  - MTCO2E vs 'Mt CO2eq'
  - KWH vs 'kilowatt-hour (kWh) per capita'
- bis: 24 of 50 fail:
  - WS_CREDIT_GAP: native 770 'Percentage of GDP' vs catalog 'Percentage points of GDP'
  - WS_TC: generic 367 'Per cent'; the denominator is the key dimension UNIT_TYPE=770
  - WS_DSR: 367 'Per cent' vs 'Per cent of income'
  - WS_LONG_CPI: 771 'Year-on-year changes, in per cent'
  - WS_CBTA: XDC 'Domestic currency (...)' x10^9 plus a CURRENCY dimension
  - WS_GLI: USD 'US dollar' x10^6 vs 'US dollar, millions'. The suffix scale word is never stripped (the regex at :762 needs a trailing space), and singular 'dollar' does not match 'dollars'.
- Native labels are sometimes less precise or wrong, and _wb_units returns the native label:
  - KWH 'Kilowatt hour (KWh)' drops 'per capita'
  - 'US Dollars' drops 'current'
  - IMF_WEO_LUR is labelled PT_POP 'Percentage of population', but it is an unemployment rate (share of the labour force)
- The catalog itself is wrong for wb:IMF_WEO_NGDPD ('U.S. dollars'; native is billions).
- Confirmed through the real adapter (probe_head_wb.py):
  - wb:IMF_WEO_NGDPD/USA -> 'Data360 returned ambiguous disaggregations'
  - wb:WB_WDI_SP_POP_TOTL/USA -> 'unit code and metadata disagree'
  - bis:WS_GLI -> 'Native SDMX unit label contradicts the canonical units'
- Impact: The World Bank provider is 100% unusable from the catalog, and about half of BIS (credit, debt service, long CPI, central bank assets, global liquidity) is too. The cross-country history and official projections the planner is steered to never reach research, charts or reports. Even after alias patches, the displayed units would be wrong for the unemployment-rate, electricity-per-capita and GDP-per-capita series. Mismatches between catalog and native units also make data anchors written with catalog units fail validate_data_anchor.
- Fix: 1. Pin the verified native unit identity per catalog entry instead of adding more aliases:
   - Add CatalogEntry.native_unit=(code, multiplier) plus optional BIS dimension pins (WS_TC UNIT_TYPE=770; WS_CBTA CURRENCY=<ccy>; WS_XRU CURRENCY_label/COLLECTION), filled from unit_table.md.
   - In _wb_units/_sdmx_units, require an exact (code, mult[, dims]) match, store the native code/label/metadata in provenance, and return the curated entry.units.
2. For non-catalog ids, use a codelist map plus scale words:
   - PC, PC_A, PT_GDP, PT_LF, PT_POP, PS, USD, MTCO2E, KWH, 367, 368, 770, 771
   - Treat metadata 'Unit', 'Number' and '%' as uninformative.
   - Fail closed only on multiplier conflicts.
3. Accept a uniform COMP_BREAKDOWN_1='V_LST' and record the vintage.
4. Catalog fixes:
   - Keep credit-gap units as 'Percentage points of GDP'. The scratch patch's native text makes format_value print '%'.
   - Change wb:IMF_WEO_NGDPD to 'Billions of U.S. dollars'.
   - Use 'Percent change per annum' for the WDI growth series.
5. Tests: replay the captured rows as fixtures, parametrized over CATALOG (every wb/bis entry has a pin and passes); a drifted code or multiplier must fail closed.

### P-FRED429 BUG (high) — FRED 429 is terminal: no keyless-CSV fallback, no adapter pacing, flagged non-retryable, and the failure is cached for the run
- Location: deerflow_bridge/data_sources.py:1361-1369, :1187-1188, :880; datamcps/fred-mcp-server-main/src/common/fred-client.ts:160-215 and src/fred/series.ts:64-68; data_tools.py:283-284,330-333; research_gateway.py:3720-3729
- Evidence: - A 429 is classified as 'operational', so the adapter raises; the CSV fallback only runs for auth errors.
- The vendored server retries 3 times with 0-1/0-2/0-4 s jitter (about 7 s max). Its 120-token bucket starts full, and every fred_get_series spends 2 upstream requests (observations plus series info).
- Offline repro (offline/repro_fred.py b): a fake hub returning the real 429 text gives DataError(retryable=False) and makes 0 CSV calls. retryable is only True for TimeoutError/OSError, and no consumer reads it (git grep).
- Downstream, data_tools caches the request as 'failed' ('prior request failed ... no refresh'), and the gateway caches 'DATA_UNAVAILABLE: provider returned no usable dataset.' for the run.
- K2 live sweep: 11 of 61 FRED ids got 429 under a burst.
- An existing test (test_data_sources.py:820-828) codifies the no-fallback behaviour.
- Impact: Under concurrent runs or a large prefetch, headline FRED series (oil, gas, trade, debt ratios) silently drop out of the research. Agents cannot recover within the run.
- Fix: - Treat 429/5xx/timeouts as operational and fall back to _fred_csv (a separate fredgraph endpoint that needs no key). Record route='fred_csv' and provenance.fallback_reason. This is safe for catalog ids, whose metadata comes from the catalog.
- Mark 429/5xx/timeout/quota errors retryable=True.
- Add a process-wide FRED token bucket in DataSources (about 50 series/min) shared by get and get_many.
- Consumers (data_tools._run, gateway._data_call) must not cache retryable failures.
- Update test 820 to cover two cases: 429 recovers through CSV, and 429 plus a CSV failure gives a retryable DataError that is re-attempted on the next call.

### P-SNAP GAP (high) — historical_snapshot drops every resolution_safe=False / 'unknown' row: simulation agents and the graph never see oil, yields, FX, debt or World Bank history
- Location: backend/app/services/official_data.py:271-272 and :287-290; consumers pipeline_orchestrator.py:12862-12869 (graph chunks) and simulation_config_generator.py:1970-1980 (world brief)
- Evidence: - Offline repro (offline/repro_daily.py): fred:DCOILWTICO through the real adapter (keyless route, fake CSV) has provenance.resolution_safe False, and historical_snapshot({'series':[it]}, as_of='2026-10-14') returns ''.
- resolution_safe=False is set for every daily-aggregated series (28 catalog entries, including DGS10, T10Y2Y, DCOILBRENTEU, DTWEXBGS and debt_to_penny from the core ids) and for every wb row. wb flags are always 'unknown', which the snapshot also rejects.
- test_official_data_downstream.py:297-304 codifies the exclusion.
- Impact: Auto-resolution safety is conflated with display safety. The public statistical baseline injected into the simulation and the knowledge graph omits the most forecasting-relevant market prices and all WDI history, so official data barely reaches the simulation stage of the forecast workflow.
- Fix: - Introduce a separate display-safe rule:
  - Allow aggregated rows rendered as 'monthly mean/end of daily closes'.
  - Allow WDI periods up to the last complete year, rendered as 'status not supplied'.
  - Keep excluding WEO/GEP projections, partial months and rows without retrieval evidence.
- Keep resolution_safe for the resolver only.
- Test: a snapshot of DCOILWTICO + wb:WB_WDI_SP_POP_TOTL/USA + wb:IMF_WEO_NGDP_RPCH/USA renders the first two with qualifiers and excludes the WEO row.

### P-DIGEST GAP (high) — catalog_digest gives no relevant series for typical DRF forecasting topics and pads with US headline macro
- Location: deerflow_bridge/data_catalog.py:1742-1759 (catalog_digest, _CORE_IDS filler), :1505-1511 (_PRIORITY_MIN_CONCEPT)
- Evidence: Offline digest_quality.py over 8 questions:
- 0 keyword matches for China NEV share (ZH), global semiconductor sales and US grid battery storage. For these the digest is the same 16 US headline ids (CPI, payrolls, Fed funds, 10Y, Brent...).
- The datacenter-electricity question matches only WDI kWh/capita, BLS electricity prices and a spurious fred:PCEC96.
- The tariff question matches only total receipts and USAspending awards.
- Good matches occur only for the Fed-rate, China GDP and Brent questions.
- Impact: The planner's data plan for DRF's own demo themes (datacenter, EV, storage, AI/semis, tariffs) is noise or empty. This directly undercuts 'make sure the agents know to query the data sources' for the topics the product forecasts.
- Fix: - When fewer than about 5 entries are picked, fill with geography-matched and topic-adjacent entries instead of _CORE_IDS.
- Add an explicit line: 'No curated series matched; use data_search with English concept terms (FRED and Data360 search cover ~800k series)'.
- Extend the catalog (P-BREADTH).
- Test: the China EV digest excludes fred:PAYEMS and includes the hint.

### P-BREADTH IMPROVEMENT (high) — Catalog lacks quantitative anchors for semiconductors/AI, datacenter electricity, storage, US-China trade and tariffs
- Location: deerflow_bridge/data_catalog.py (CATALOG, USGOV_RECIPES); data_mcp.py:86-87,392-395 (EIA module only loaded with EIA_API_KEY)
- Evidence: Live probe_breadth.log:
- FRED search verified fred:IPG3344S (IP semiconductors, M, 1972-2026-08), CAPUTLG3344S, A34SNO, A34SVS, PCU33443344, NASDAQSOX, IMPCH (US goods imports from China) and B235RC1Q027SBEA (federal customs duties, Q).
- Treasury MTS table 3 line_code_nbr=110 'Customs Duties' (2026-08 = $12.84bn); lines 20, 30 and 360 hold individual taxes, corporate taxes and gross interest.
- FRED search found no monthly US electricity generation or consumption series.
- Neither EIA_API_KEY nor BLS_API_KEY is set, so the usgov eia module is never loaded.
- Catalog searches for 'semiconductor', '半导体', 'AI capex' and 'customs duties' return no hits.
- Impact: No official quantitative baseline is available for the most common DRF forecast topics, so the reports' data visualizations fall back to generic macro.
- Fix: - Add the verified FRED ids above with EN+ZH keywords (半导体, 芯片, 关税, 中美贸易, 数据中心, 用电量, 储能, 新能源汽车).
- Add a usgov recipe treasury/mts_customs_duties (same as mts_receipts with filter line_code_nbr:eq:110), plus individual and corporate tax recipes.
- Document a free EIA key and add EIA recipes: retail electricity sales total/commercial (the datacenter proxy), net generation by source, and EIA-860M battery storage capacity.
- Pin native units for the new entries (P-UNITS) and include them in the live smoke.

### P-WEOSTATUS IMPROVEMENT (high) — Every WEO and World Bank observation is 'unknown': no latest value, no history/projection split, nothing for the data pack or snapshot
- Location: deerflow_bridge/data_sources.py:192-205 (Series.__post_init__ forces flags), :280-281, :1593-1595, :1667-1675; report_agent._build_data_pack consumes it
- Evidence: - K2 sweep: latest=None for every wb and imf:WEO id.
- Live probe_imf.log: the imf server returns only country/indicator/frequency/time_period/obs_value, with no status attribute. It ignores start/end years (52 rows, 1980-2031, for a 2020-2031 request).
- Data360 rows have no OBS_STATUS (units_wb.jsonl). Data360 metadata does include date_released/date_last_update.
- The data pack therefore prints 'Latest historical value: unavailable' for all of them.
- Impact: The official projections (WEO, GEP), which are the key benchmark forecasts, cannot be split into history and projection in charts, briefs or reports. WDI history is not quotable as 'latest'.
- Fix: Use deterministic, conservative status rules:
- WDI (WB_WDI_*, which publishes no projections): years before the retrieval year are 'observed', with provenance.status_basis set.
- WEO/GEP: take the vintage year from the imf vintage flow name or the Data360 date_released. Years at or after the vintage year are 'projection', vintage year-1 is 'estimate', and earlier years are 'observed (revisable)'. Set projection_from and keep resolution_safe=False.

Bump NORMALIZATION_POLICY_VERSION, because __post_init__ re-applies flags. Test with the captured WEO rows: 2026+ projection, 2025 estimate, 2024 and earlier observed; latest is non-null.

### P-DAILY BUG (medium) — Daily->monthly aggregation marks every month '(partial)', reports the partial current month as the observed latest value, and averages step and stock series
- Location: deerflow_bridge/data_sources.py:1280-1296 (complete=False hard-coded), :324-328 (_display_period), :289-307 (series_stats)
- Evidence: Offline repro_daily.py (real adapter, keyless route, fake CSV for full Jul-Sep plus 7 Oct days):
- The table shows '2026-07 (partial) ... 2026-10 (partial)', all 'observed'.
- series_stats.latest is 2026-10-01 = 73.43, a 7-day mean.

Live keyless DGS10 shows the same: latest 2026-10-01 = 5.2667. The issue affects 28 daily catalog ids, including DFEDTARU/DFF/SOFR (a mid-month cut gives a fractional monthly mean) and debt_to_penny (a stock averaged).
- Impact: Agents and reports quote a few-day mean as the month's value and as 'latest'. Full months look unreliable. Policy-rate and debt questions get misleading values and never auto-resolve.
- Fix: - Compute complete as covered_start==month start, covered_end==month end and month end < retrieval date.
- Flag the partial current month as 'preliminary' so stats exclude it.
- Record provenance.latest_daily {date, value} and show it in the page and brief.
- Make aggregation per-series: eop for policy targets and stocks (DFEDTARU, DFF, SOFR, debt_to_penny, debt_held_public), avg for prices and yields. Prefer FRED server-side aggregation (P-FREDCAP), whose complete months can be resolution-safe.
- Test: only October is labelled partial; latest observed = September; latest_daily = the last October close.

### P-REDACT BUG (medium) — Secret scrubbing replaces any env value whose name matches token/key/secret; short numeric values corrupt observation dates and fail every fetch
- Location: deerflow_bridge/data_sources.py:930-935 (_redact), :1340-1352 (_finish.scrub over the whole series dict); compare data_mcp.py:124,180 (_MIN_SECRET_LEN=4)
- Evidence: - Offline repro_daily.py: DataSources(env={..., 'LLM_MAX_TOKENS': '20'}).get('fred:DCOILWTICO') returns DataError('Unrecognized observation period'). Every '20' in '2026-07-01' became '[redacted]'.
- backend/app/config.py:21 load_dotenv(override=True) puts .env into os.environ.
- This repo's .env has REPORT_AGENT_SECTION_MAX_TOKENS=16384, and the shell has CLAUDE_CODE_MAX_OUTPUT_TOKENS (5 digits).
- ML environments commonly set HF_HUB_DISABLE_IMPLICIT_TOKEN=1, which would break every series.
- Impact: Depending on the environment, all official data fails, with an unrelated error message.
- Fix: - Redact only credential-like keys (*_API_KEY, *_TOKEN, *_SECRET, *_PASSWORD, plus the known provider keys).
- Require len >= 8, not purely digits, and not true/false.
- Never scrub observation date/value fields.
- Test: env X_MAX_TOKENS=20 and HF_HUB_DISABLE_IMPLICIT_TOKEN=1 still fetch; a 12-character FRED key echoed in notes is redacted.

### P-SYMLINK BUG (medium) — A symlinked ancestor of the output or cache dir silently disables dataset persistence, caching and all keyless BLS
- Location: deerflow_bridge/data_sources.py:374-382 (_safe_path checks path and all parents), :402-411 (O_NOFOLLOW_ANY on the absolute path); used by write_dataset_files :523-571, _cached/_save_cache :1113-1145, _bls_quota :1431
- Evidence: Offline:
- write_dataset_files([s], tempfile.mkdtemp()) on macOS returns {'error': 'Official data persistence failed'}, because /var -> /private/var; the resolved path works.
- DataSources(cache_dir='/tmp/...').get('bls:CUUR0000SA0') returns DataError('Symlink artifacts are not accepted') with 0 hub calls.
- Tests pass only because pytest tmp_path is a realpath.
- Impact: With DATA_SOURCES_CACHE_DIR under /tmp, a symlinked checkout, home or uploads volume, or macOS temp dirs: no datasets.json (charts and reports lose official data), no cache, and BLS unusable. Only a generic warning is logged.
- Fix: - Resolve the trusted root once and apply the no-symlink rule only to components below the root, using a dir_fd walk with O_NOFOLLOW (as the non-Darwin branch already does).
- On Darwin, apply O_NOFOLLOW_ANY to the resolved root.
- Log the concrete reason.
- Test: persistence, cache and quota work through a symlinked parent; a symlink inside data/ is still rejected.

### P-FREDCAP BUG (medium) — Long daily windows always fail with 'history exceeds bound' although the result is aggregated to monthly anyway
- Location: deerflow_bridge/data_sources.py:1375-1376 (API route), :1413-1414 (CSV route); aggregation only later in _finish :1280
- Evidence: - Offline repro_fred.py (a): keyless fred:DGS10 with start=2000-01-01 returns DataError('FRED CSV observation limit exceeded'). The API route raises 'FRED history exceeds bound; narrow start/end' for counts above 5000.
- The vendored tool supports frequency and aggregation_method avg/sum/eop (fred tools.ts:46-50).
- Impact: Agents cannot get long histories of yields, oil, FX or VIX (multi-decade context for forecasts). The real reason is hidden by P-TEXT.
- Fix: - For native-daily series with windows longer than about 3 years, request server-side monthly aggregation: API frequency='m', aggregation_method='avg' (or 'eop' per P-DAILY); CSV route fq=Monthly&fam=avg.
- Record provenance.aggregation.
- Test: DGS10 since 2000 returns about 320 monthly rows.

### P-SEARCH BUG (medium) — search() returns early on weak catalog matches, so live FRED and Data360 search is never consulted for specific concepts
- Location: deerflow_bridge/data_sources.py:1005-1009 (early return), :1010-1017 (FRED search); data_catalog.py _MIN_HIT_SCORE=1.0 with +2 topic boosts
- Evidence: Live probe_breadth.log:
- search('半导体出口') returns EXPGSC1, EIUIQ, NE_EXP_GNFS_ZS/CHN, BOPGSTB, IMPGSC1, EIUIR, with no semiconductor series.
- search('high-technology exports China') returns generic China trade and FX.
- search('semiconductor'), which has 0 catalog hits, correctly reaches FRED: PCU33443344, NASDAQSOX, IPG3344S.
- FRED hits carry note 'undefined'.
- v3 seeding takes the first returned line blindly (linear_research.py:4369-4373).
- Impact: Wrong series are auto-fetched and cited for any concept outside the 277-entry catalog that shares a topic word.
- Fix: - Count only catalog hits with concept score >= 4.0 toward the early return.
- Query live FRED and Data360 search for the remainder and append weak catalog matches last.
- Translate ZH concept terms to English for provider search (glossary from TOPICS and catalog keywords).
- Drop 'undefined'/'null' notes.
- Test with a fake FRED search payload: a semiconductor id outranks generic exports for '半导体出口'.

### P-WBGEO BUG (medium) — Data360 search pins countries by raw substring match ('urban'->AUS, 'carbide'->IND, 'usage'->USA) and drops country-agnostic hits
- Location: deerflow_bridge/data_sources.py:1022 (alias substring match), :1026-1028 (keeps a hit only if covers_country has exactly one entry)
- Evidence: Offline:
- 'urban population growth' -> ['AUS']
- 'silicon carbide wafer exports' -> ['IND']
- 'electricity usage per capita' -> ['USA']
- 'fedex shipping volumes' -> ['USA']

catalog._parse_query correctly finds no geography for any of these. The wrong code is sent as required_country and baked into the id wb:<idno>/<ISO3>.
- Impact: Mis-pinned country series get fetched and cited, via the blind first-hit seeding. Queries without a country return almost no Data360 hits.
- Fix: - Use catalog._parse_query(query).geos (word-boundary plus ZH).
- With 0 geos, emit WLD when covered; with more than one, emit one hit per geo.
- Test: the four queries above produce no spurious country.

### P-TEXT GAP (medium) — Tool text contract hides actionable failure reasons, caches failures permanently, and drops search notes and geography
- Location: deerflow_bridge/data_tools.py:313-333 and :326; mirrored in research_gateway.py:3716-3729
- Evidence: - Any DataError becomes 'DATA_UNAVAILABLE: official-data request or evidence persistence failed' and is stored as status 'failed'. Later identical calls return 'prior request failed ... no refresh'.
- The gateway caches 'provider returned no usable dataset.' for the run.
- Search lines are '{series} — {title} · {units} · {frequency} · {coverage}', with no SearchHit.note (e.g. 'Discovery metadata; fetch before citing', 'Negative values are deficits.') and no geography.
- Impact: Agents cannot self-correct when a fix is easy: narrow the window, choose another transform, use a valid usgov recipe, or wait out a quota. Transient errors become permanent for the run.
- Fix: - Map DataError to a bounded allowlisted reason taxonomy with a short hint: invalid_window, unsupported_transform, unknown_recipe, rate_limited_retry_later, quota_exhausted, not_found, provider_unavailable.
- Do not cache retryable failures.
- Append geography and note[:120] to search lines.
- Test: a too-long daily window returns 'DATA_UNAVAILABLE[invalid_window]: narrow start/end', and a retry after a fake 429 re-calls the provider.

### P-FIXTURES GAP (medium) — Synthetic fixtures hide every real-payload failure; replace them with captured payloads and add a gated live smoke
- Location: backend/tests/fixtures/data_sources/README.md + provider_responses.json; backend/tests/test_data_sources.py:213-214, 472-478, 820-828; test_official_data_downstream.py:297-304
- Evidence: - The README says the values are 'invented test data'.
- The wb fixture uses UNIT_MEASURE 'PT'/'Percent' and no COMP_BREAKDOWN_1. The real codes are PC, PC_A, PT_GDP, PS, USD, MTCO2E, KWH, plus V_LST.
- The WS_TC test only checks truncation.
- Two tests codify defects found here: the 429 no-fallback and the resolution_safe snapshot exclusion.
- Impact: The test suite is green while 78 catalog entries fail live (P-UNITS). Future provider drift will also go unnoticed.
- Fix: - Commit trimmed real captures from this review (units_wb.jsonl, units_bis.jsonl, the IMF rows in probe_imf.log, the MTS rows) as fixtures/data_sources/real/<provider>/<series>.json with the capture date.
- Add a parametrized test that replays every catalog entry's native attributes and asserts the catalog units.
- Add an opt-in DRF_LIVE_DATA_SMOKE=1 script (FRED paced at 30/min or less, BLS excluded) that re-captures and diffs the native unit, scale and dimension fields.

### P-ROUTE IMPROVEMENT (medium) — Prefer fast routes for duplicated concepts; IMF costs about 60 s for the first series and runs serially inside a 150 s data phase
- Location: deerflow_bridge/data_sources.py:1569-1587 (_fetch_imf defs + fetch), :880 (IMF semaphore 1); data_mcp.py:231; linear_research.py:4353 (150 s data deadline); data_catalog search ranking
- Evidence: - Live probe_imf.log: imf_get_parameter_defs took 24.7 s and imf_fetch_data 36.0 s for one WEO series. The parameter names (country/indicator/frequency) are the catalog dims.
- Search ranks imf:PCPS/G001.PCOPP.USD.M (13.0) above fred:PCOPPUSDM (10.5) for 'copper price'.
- WEO country series exist both as imf:WEO_* and as wb:IMF_WEO_*; Data360 answers in 2-8 s per call.
- Impact: A few IMF ids can consume the whole data phase, so other series time out.
- Fix: - Add catalog preferred/alternates links (PCPS <-> FRED IMF mirrors, imf:WEO <-> wb:IMF_WEO) and prefer the fast route in search and digest.
- Hard-code IMF parameter names per flow and call imf_get_parameter_defs only on a mismatch.
- Test: the 'copper price' digest lists the FRED id first, and an IMF fetch makes a single call.

### P-FREDVINTAGE IMPROVEMENT (medium) — Use the FRED tool's ALFRED vintage support for point-in-time resolution and back-tests
- Location: deerflow_bridge/data_sources.py:1358-1394 (vintage_status hard-coded), :668-714 (resolve_data_anchor); datamcps/fred-mcp-server-main/src/fred/tools.ts:51-52
- Evidence: - The tool exposes output_type 1-4 (4 = initial release only) and vintage_dates.
- The adapter never uses them and records 'vintage_status: not supplied by native handler'.
- resolve_data_anchor needs retrieval after the period ends and cannot resolve 'as first reported' questions.
- Impact: First-print questions (advance GDP, first CPI or payroll prints) cannot auto-resolve, and back-tests cannot reproduce what a forecaster knew.
- Fix: - Add get(..., vintage='YYYY-MM-DD'|'initial') for fred ids: pass vintage_dates / output_type=4, set Series.vintage and provenance.vintage_status='alfred'.
- resolution_monitor uses 'initial' for first-release questions.
- Test with a recorded ALFRED fixture.

### P-BLSQUOTA IMPROVEMENT (medium) — Keyless BLS (20 requests/day, no BLS_API_KEY) is a bottleneck; route headline BLS ids to their FRED equivalents
- Location: deerflow_bridge/data_sources.py:1424-1451 (_bls_quota); data_catalog.py BLS entries
- Evidence: - BLS_API_KEY is unset and today's quota is exhausted.
- The catalog already holds exact FRED equivalents:
  - LNS14000000 = UNRATE
  - CES0000000001 = PAYEMS
  - CUSR0000SA0 = CPIAUCSL
  - CUSR0000SA0L1E = CPILFESL
  - JTS000000000000000JOL = JTSJOL
  - CES0500000003 = CES0500000003
- Same-ID FRED mirrors do NOT exist: fredgraph CSV returned 404 for CUUR0000SA0, LNS14000000, WPUFD4, CES0000000001 and JTS...JOL (verified live).
- Impact: BLS series fail for the rest of the day after about 20 chunk requests across all runs.
- Fix: - Add fred_equivalent to these entries.
- On quota or unavailability, return a hint naming the FRED id, or prefer the FRED id in search and digest while BLS is keyless.
- Document the free BLS v2 key (500/day).

### P-ZHRANK BUG (low) — ZH numerals and missing ZH keywords mis-rank: '美国十年期国债收益率' ranks DGS2 above DGS10; '电力需求' finds no electricity series
- Location: deerflow_bridge/data_catalog.py:1580-1627 (_cjk_bigrams/_parse_query), DGS2/DGS10 entries :727-735, WB_WDI_EG_USE_ELEC_KH_PC :1403-1407
- Evidence: Offline search_quality.py:
- DGS2 and DGS10 tie at 15.0. Their title_zh bigrams are identical once the digits break the CJK run, and catalog order puts DGS2 first.
- '电力需求' returns bls:CUUR0000SEHF01 and oil series.
- Impact: The v3 seeder would fetch the 2-year yield for a 10-year question.
- Fix: - Normalize CJK numerals in _parse_query (十->10, 两/二->2, 三十->30).
- Add the keywords 十年期国债, 两年期国债, 电力需求 and 用电需求.
- Add ranking assertions.

### P-SEC BUG (low) — The SEC recipe is advertised to planners but always fails by design
- Location: deerflow_bridge/data_catalog.py:103 (usgov role printed in every digest), skills/data-sources/references/series-catalog.md:18 and :366; data_sources.py:1699-1702 and :188-189
- Evidence: - The role text says '... SEC company facts', and the recipe table shows the example AAPL/RevenueFromContract...
- But _fetch_usgov returns a DataError for sec, Series rejects usgov:sec/*, and SKILL.md says SEC is unavailable.
- Impact: Contradictory guidance; data budget is spent on guaranteed failures.
- Fix: - Remove SEC from the role and the rendered recipe table, or mark it unavailable.
- Optional improvement: a fixed-origin keyless fetch of data.sec.gov companyconcept (User-Agent with SEC_CONTACT_EMAIL), filtered to 10-K, fp=FY, ~365-day duration and the latest filed per period. This gives annual company revenue/capex series for AI and semiconductor forecasts.

### P-USGOV BUG (low) — usgov recipe semantics: debt stocks are averaged, and fiscal years are marked complete the day after they end
- Location: deerflow_bridge/data_sources.py:1280-1287 (mean aggregation for debt_to_penny), :1703-1727 (spending/total complete flag); data_catalog.py spending/total recipe
- Evidence: - Live: debt_to_penny latest = mean of 1-9 October.
- spending/total with an explicit start of 2007-10-01 marks FY2026 complete=True 12 days after year end, although the recipe note says recent years rise with late reporting.
- K2's 422 (default window starts before 2007-10-01) is confirmed live; with start=2007-10-01 the call succeeds.
- Impact: Debt-threshold questions see understated levels. A partial FY obligation total is presented as final.
- Fix: - Use eop aggregation for stock recipes.
- Add recipe min_start='2007-10-01' and clamp fetch_start in _fetch_usgov before the call (the K2 fix).
- Set complete only when today > end + ~120 days.
- Test: clock 2026-10-12 gives FY2026 complete=False.

### P-WBMETA IMPROVEMENT (low) — Each wb series persists about 23 KB of verbatim Data360 metadata (92% of the payload)
- Location: deerflow_bridge/data_sources.py:1691-1695 (provenance.metadata = full metadata)
- Evidence: Cache entries in scratchpad/fix/cache for WB_WDI_NY_GDP_MKTP_KD_ZG: the file is 25.3 KB, of which 23.3 KB is provenance.metadata. It is copied into data/*.json, candidate journals and the dataset.snapshot in sources.json (data_tools.py:175).
- Impact: Bloats artifacts and hashing; adds risk to downstream contexts.
- Fix: Keep a field whitelist (idno, database_id, indicator_name, measurement_unit, periodicity, date_last_update, date_released, source, license) plus a sha256 of the full metadata. Test: a wb Series dict is under 4 KB.

### P-PREWARM IMPROVEMENT (low) — v3 prewarms all six servers (~772 MB RSS) on every fresh run regardless of the data plan
- Location: deerflow_bridge/linear_research.py:4103-4109; deerflow_bridge/data_sources.py:912-920
- Evidence: Live probe_lifecycle.log:
- prewarm returns in 0.02 s; all six servers are ready within 1.55 s (warm).
- RSS: fred 90 MB, bls 91, bis 83, imf 116, wb 212, usgov 180 (772 MB total).
- close() takes 0.18 s and leaves no surviving process-group members, so the lifecycle itself is clean.
- Impact: Memory overhead per research process.
- Fix: Prewarm only providers referenced by the planner's data_needs and start the rest lazily. Test: a fred-only plan starts only fred.

### P-SCALE IMPROVEMENT (low) — Large raw values are rendered unscaled in pages, briefs, the data pack and the snapshot
- Location: deerflow_bridge/data_sources.py:310-321 (format_value)
- Evidence: debt_to_penny renders as 40269094993348.984.
- Impact: LLM arithmetic and EN/ZH scale-translation errors (billion vs 亿).
- Fix: Keep the exact table, but add a scaled companion in the Summary, brief and data pack (e.g. '≈ 40.27 trillion U.S. dollars'), derived from the units' scale words.

### P-CACHE BUG (low) — Unbounded in-process cache maps, no disk pruning, and get_many can still raise or mislabel errors
- Location: deerflow_bridge/data_sources.py:876-877 (_locks/_memory), :1143 (disk cache), :1191 and :1258-1259 (get_many)
- Evidence: - Offline: get_many([['fred:UNRATE']], deadline_s=5) raises TypeError (unhashable), and get_many(None) raises TypeError.
- An unexpected kwarg makes every id report 'Data request deadline exceeded' (retryable=True), because the TypeError is swallowed.
- The _memory/_locks maps grow per series x window x day forever, and cache files are never pruned.
- Impact: Memory growth in long-lived backend or resolution-monitor processes, and a violation of the never-raise contract.
- Fix: - Add an LRU cap (e.g. 512) and prune cache files older than 7 days.
- Validate ids and kwargs up front and return per-id DataErrors with the real reason.


#### Phase coverage
Data-layer stage -> official data use today (HEAD eac717b), with live/offline evidence in scratchpad/review/providers/:
1. Planner catalog digest (data_catalog.catalog_digest): used. 0 keyword matches for China NEV share, semiconductor sales and battery storage questions, so the digest falls back to the same 16 US headline ids. Datacenter-electricity and tariff questions match mostly irrelevant series. See P-DIGEST and P-BREADTH.
2. Discovery (DataSources.search, data_search tool): catalog search first, then FRED, Data360, BIS and Treasury. It returns early on weak topic-only catalog matches. Data360 country pinning uses substring matching. ZH ranking errors (P-SEARCH, P-WBGEO, P-ZHRANK). v3 seeding takes the first hit blindly (linear_research.py:4369-4373).
3. Retrieval (get/get_many through McpHub):
   - fred: OK, keyed and keyless (keyless CSV verified live). 429 is terminal (P-FRED429). Long daily windows fail (P-FREDCAP).
   - bis: 24 of 50 catalog ids fail on HEAD.
   - wb: 54 of 54 catalog ids fail on HEAD (P-UNITS).
   - imf: works but slow, about 60 s for the first series (P-ROUTE).
   - usgov: Treasury recipes OK. spending/total fails with its default window (K2). SEC is always refused but still advertised (P-SEC).
   - bls: not probed (quota exhausted; P-BLSQUOTA).
4. Normalization (units/status/periods): units are reconciled by a fuzzy normalizer against free-text metadata (P-UNITS). Every wb and WEO observation is labelled 'unknown' (P-WEOSTATUS). Daily series are aggregated to monthly means, every month is labelled '(partial)', and resolution_safe=False is forced (P-DAILY). Secret scrubbing can corrupt dates (P-REDACT).
5. Persistence (write_dataset_files/load_datasets, cache, BLS quota): works on realpath dirs. It silently fails when any ancestor of the target path is a symlink, e.g. macOS /tmp or /var (P-SYMLINK). wb rows carry about 23 KB of metadata each (P-WBMETA).
6. Evidence page/tool text (render_series_page, data_tools/gateway responses): pages are rendered. Failure reasons are hidden and failures are cached for the run. Search lines drop notes and geography (P-TEXT). Large values are shown unscaled (P-SCALE).
7. Backend consumption (official_data.load_official_data -> report data pack; historical_snapshot -> graph chunks and simulation world brief): the snapshot excludes every resolution_safe=False row and every 'unknown' row. So simulation and graph never see daily market series, debt or World Bank history (P-SNAP).
8. Resolution (validate/resolve_data_anchor via resolution_monitor): only non-aggregated, non-wb, non-WEO series can auto-resolve. There is no vintage or first-release support (P-FREDVINTAGE).
9. Hub lifecycle (data_mcp): clean. Prewarm returns in 0.02 s, all six servers are ready within 1.55 s (warm), total RSS is 772 MB, close() takes 0.18 s and leaves no surviving process-group members. All six servers are prewarmed regardless of the data plan (P-PREWARM).
10. Tests/fixtures: fixtures are synthetic. Two existing tests codify the 429 no-fallback and the snapshot exclusion (P-FIXTURES).


## review:downstream-ops: Downstream stages (ontology/graph, simulation, resolution/ledger/calibration), orchestration (stage flow, binding, fork/resume/seeds/parallel, artifac

### D1 BUG (high) — CI unit job stays red after K1: 25 more tests fail under plain pytest
- Location: backend/tests/test_main_offline_runner.py:22; backend/tests/test_deployment_sidecar_control_flow.py:82 (scripts/verify_deployment_fixtures.py:783); backend/tests/test_official_data_end_to_end.py:87; backend/tests/test_architecture_characterization.py:199; backend/tests/test_orchestrator_research_wiring.py (2 cases, failing at pipeline_orchestrator.py:13155); .github/workflows/ci.yml unit job
- Evidence: Plain run `cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider --continue-on-collection-errors -rf` gave 4804 passed, 29 failed, 11 xfailed and 1 collection error (test_data_sources.py, which is K1 and the only collection error). Output: scratchpad/review/full_suite.txt. These 25 fail in CI too: 19 MainOfflineControls tests call `self.fail("run via backend/scripts/main_offline_pytest.py")` in setUp. 2 sidecar tests hit `parser.error("Use an existing Python with -I -S -B")`. The E2E test asserts `MAIN_OFFLINE_EVIDENCE`. One characterization test still asserts ReportAgent never passes `quantitative_facts=`, but report_agent.py:3129 now passes `_data_pack`. 2 orchestrator state-machine tests fail with `ValueError: Simulation and research directories must already exist` from the new bind_simulation_research call. The other 4 failures depend on this machine only (demo deletions in the working tree, a stale deployed deer-flow config and skills); they pass or skip in CI.
- Impact: Every push/PR to main fails CI. CI runs `cd backend && uv run pytest -q`, so the collection error aborts first; once K1 is fixed these 25 failures still keep it red. Codex verified only through its custom runner.
- Fix: Tests that need the guarded runner should call `pytest.skip` (or carry a `guarded_runner` marker deselected by default through addopts) instead of self.fail or assert. Update the characterization test so it asserts the new contract (`quantitative_facts=` is the data pack). In test_orchestrator_research_wiring, patch SimulationManager.SIMULATION_DATA_DIR and create the sim dir (see D2). Add a CI-equivalent plain-pytest check to the delivery gate. Acceptance: plain `uv run pytest -q` is green.

### D2 BUG (medium) — Research-generation capture/binding is a hard, run-killing invariant, even when official data is disabled
- Location: backend/app/services/pipeline_orchestrator.py:12648-12650 (capture in RESEARCH), :13154-13158 (bind in PREPARE), :9122-9136 (seed); backend/app/services/official_data.py:82-128
- Evidence: Neither call is guarded. ValueError/OSError from a missing or relocated sim/handoff dir, an artifact over 16 MB, a symlinked artifact, or an in-memory report/sources mismatch with disk fails the whole pipeline. Both calls run even with DATA_SOURCES_ENABLED=false and no data/ directory: conftest forces it false, and the 2 test_orchestrator_research_wiring resume tests (PREPARE rebuild) still fail inside bind_simulation_research. This contradicts the Config contract ('服务未构建/无key/超时/崩溃一律降级…绝不使运行失败') and integration-contract.md ('A mismatched or malformed binding yields unavailable enrichment').
- Impact: An optional-enrichment provenance check can abort a long forecast run, including runs that use no official data.
- Fix: Wrap capture and bind in try/except, record state.options['official_data_binding']={'status':'unavailable','reason':…} and continue (official_data then resolves to None through the existing 'missing' path). Skip capture when data/datasets.json is absent and data is disabled. Tests: (1) resume with PREPARE rebuild completes; (2) an injected bind error gives a completed run with official_data=None and a diagnostic.

### G4 GAP (medium) — Hard 12-series ceiling applied in write order silently drops later series; v3 prefetch can exhaust all 12 slots before agents fetch
- Location: deerflow_bridge/data_sources.py:574-579 (load_official_data[:12]) and :528-562 (new rows appended last); backend/app/services/official_data.py:170; deerflow_bridge/research_gateway.py:3641 and :3755 (run cap 12 shared by data-seeder :3694 and agents); deerflow_bridge/linear_research.py:4356 (prefetch cap min(12, DATA_SOURCES_PREFETCH_MAX=12)); deerflow_bridge/deerflow_research.py:16207-16256 (legacy publishes all)
- Evidence: Report, forecast-anchor validation (forecast_extractor.py:1819-1823 → validate_data_anchor returns None when the series is absent), sim brief and manual report all read load_official_data(max_series=12), which keeps the first 12 manifest rows by insertion order, not by relevance. Legacy and the legacy parallel lanes have no 12 cap: each lane has a 50-call data budget and publishes every validated dataset, so series #13 and later, including anchored ones, vanish downstream with no diagnostic. In v3, prefetch and agents share one 12-dataset cap. With the default prefetch of 12, agent data_get calls can return 'DATA_BUDGET_EXHAUSTED: run dataset limit reached' even though README/.env.example advertise 24/50/90 data calls and never mention the 12-dataset cap.
- Impact: KIQ-specific series that agents fetch later, which are often the most decision-relevant, can be invisible to forecasts and resolution. Agent data tools can be mostly unusable in default v3 runs.
- Fix: Add a Config knob (e.g. DATA_SOURCES_MAX_SERIES, default 24) used by both producers and load_official_data. Rank consumer rows: anchored > cited in report > KIQ-linked > prefetch-only. Reserve agent slots in v3 (prefetch ≤ cap/2). Log dropped series counts. Document the cap. Test: a 15-series manifest whose anchor is on #15 still validates and resolves.

### G2 GAP (medium) — World Bank Data360 (WDI, IMF-WEO-via-Data360), USAspending and IMF WEO rows can never reach the simulation world brief or the graph snapshot
- Location: backend/app/services/official_data.py:277 (resolution_safe False → skip), :290 (WEO/GEP without projection_from → skip), :300 (only blank/observed flags); deerflow_bridge/data_sources.py:192-205 (wb/usgov forced unknown + resolution_safe False; WEO unknown when unflagged)
- Evidence: Repro scratchpad/review/repro/snapshot_providers.py gives: fred:UNRATE in_snapshot=True; wb:IMF_WEO_NGDP_RPCH/CHN flags=['unknown'] resolution_safe=False in_snapshot=False; imf:WEO/G001.NGDP_RPCH.A flags=['unknown'] in_snapshot=False. A live IMF probe (repro/live_weo.py, weo_attrs.py) returned all 13 WEO observations (2018-2030) as unknown, with attributes={}, raw_status={}, vintage='' and projection_from=''. So WEO history can never be used as history. A resolution-eligibility flag (resolution_safe) is being used as a context-visibility gate.
- Impact: For non-US, EM or global questions, simulation agents and the knowledge graph get no official numbers at all, while the report shows the same data as 'unclassified'. The sim world and the report diverge.
- Fix: Separate resolution eligibility from context visibility. Add a per-database fidelity policy: WB_WDI is a historical-only database, so periods before the retrieval year are observed. For WEO, take projection_from from the vintage (explicit WEO_YYYY_MON ids: ≤YYYY-2 observed, YYYY-1 estimate, ≥YYYY projection; live WEO uses the catalog vintage date). Alternatively render unknown-status rows in a separately labelled 'status unclassified by publisher feed' block. Keep resolution_safe=false for the monitor. Test: a WDI row appears labelled, and WEO projections never appear as history.

### D4 BUG (medium) — World brief truncation cuts the closing 'END UNTRUSTED RESEARCH DATA' delimiter around the official snapshot
- Location: backend/app/services/simulation_config_generator.py:1969-1979 and :1985; backend/app/services/actor_role_prompt.py:259-283
- Evidence: The snapshot budget is `max_chars - sum(len(part)+2) - 160`. delimit_untrusted_research_text adds about 222 chars (BEGIN line, instruction line, END line), and then `"\n\n".join(parts).strip()[:max_chars]` slices the tail. Repro scratchpad/review/repro/world_brief_sweep.py: 8 FRED rows, max_chars=1400, question length swept 40..400. The snapshot appeared in 52 briefs and the closing delimiter was truncated in 9; example tail: '...HOUST [S8] (flag: observed)\nEND UNTRUSTED RESEARCH '. run_parallel_simulation.py:643-654 injects world_brief into every agent prompt.
- Impact: The structural prompt-injection boundary around research-derived text is left open in all agents' system prompts for a sizeable share of budgets.
- Fix: Reserve the exact wrapper overhead (`len(delimit_untrusted_research_text(label,'x'))-1`), or wrap first and drop whole snapshot lines until the joined brief fits. Never slice after wrapping. Test: sweep budgets and assert BEGIN and END are both present or both absent.

### D5 BUG (medium) — Official snapshot silently vanishes from graph and world brief when data was retrieved after the as_of calendar day
- Location: backend/app/services/official_data.py:283-287; callers pipeline_orchestrator.py:12862-12866 and simulation_config_generator.py:1971-1974; as_of source deerflow_bridge/linear_research.py:4476, 6245-6249
- Evidence: A series is dropped when retrieved_at > end-of-day(as_of), and callers pass the raw actors['as_of_date']. In v3 that is the extraction LLM's value, or plan.as_of (the UTC date at run start, frozen across resumes). Repro scratchpad/review/repro/snapshot_midnight.py: same-day retrieval → present; retrieval at 2026-10-12T00:06Z with as_of 2026-10-11 → empty; as_of 2026-09-30 (LLM picks the last data month-end) → empty.
- Impact: Runs that cross UTC midnight, resumed runs, or an LLM-chosen as_of leave sim agents and the graph with zero official data while the report still shows it, with no diagnostic.
- Fix: For captures made by the same research run, judge availability against the research completion time (meta finished_at / run identity), not as_of end-of-day. Keep the strict retrieval≤cutoff rule only for explicit historical or backtest cutoffs. Record an excluded-row count in state.options. Test: after-midnight retrieval within the run is admitted, and an explicit backtest cutoff still excludes.

### G3 GAP (medium) — Stored official observations are never promoted into the structured quantitative plane (actors.json quantitative_facts / quantitative.json)
- Location: deerflow_bridge/linear_research.py:6242-6272 (quant only from LLM extraction); legacy _prepare_legacy_data deerflow_research.py:16356-16370; consumers backend/app/services/actor_context.py:1344, actor_role_prompt.py:814-846, report_agent.py:1891
- Evidence: No code path appends dataset rows to quantitative_facts. Per-actor context packs, per-actor role prompts, ReportAgent quantitative_facts_block, quantitative/metric-trajectory charts and recency annotations therefore see only numbers the LLM re-typed from report prose, never the exact hash-bound observations.
- Impact: Exact S1 official values do not reach the actor-level simulation knowledge or the structured report plane. Numbers can drift through LLM re-extraction.
- Fix: After dataset publication (v3 _publish_data, legacy _prepare_legacy_data), append deterministic rows: {metric: title, series: canonical id, value: latest observed, unit, as_of_date/period_end: period, value_type:'actual', source: provider_name, source_ref:'S<n>', origin:'official_data'}. Let them override LLM rows with the same series, and never add projection, unknown or preliminary values as actual. Test: datasets → quantitative.json holds the exact stored values with S#, and a relevant actor pack shows them.

### I1 IMPROVEMENT (high) — Deterministic statistical base rate (outside view) for every data-anchored binary forecast
- Location: backend/app/services/forecast_extractor.py:1819-1823 (anchor validation), :1082 and :3261-3272 (free-text base_rate_anchor); deerflow_bridge/data_sources.py:289-307 (series_stats has only latest/YoY/5y range); backend/app/services/report_visualizer.py official_series_* charts
- Evidence: Today official data reaches probability generation only as a context table (report_agent.py:2394-2445, passed at :3129) plus a validated anchor. base_rate_anchor remains LLM free text even when the exact series history is stored. backtest.py does not use official data.
- Impact: This is the quantitative core the user asked for. Each data-anchored binary would get an auditable outside view computed from official history, and model vs statistical baselines could be compared through data_resolutions.jsonl.
- Fix: For each validated data_anchor: set h = periods from the latest observed value to the anchor period. Over the stored history (n ≥ 30) compute the distribution of h-step changes, and p_base = share of latest+Δh that satisfies comparator/threshold. Store {method:'empirical_h_step', h, n, p_base, window} on the binary, inject it into the probability prompt as the base_rate_anchor candidate, draw quantile bands on the official threshold chart, and flag |p - p_base| > 0.25 in the confidence audit. Test: a synthetic random walk with a known crossing frequency.

### G1 GAP (medium) — Canonical actor-intelligence/v1 simulations (legacy engine and its parallel global-synthesis lane) receive no official data at all
- Location: backend/app/services/simulation_config_generator.py:1929-1936 (early return to _build_canonical_public_world_brief before the snapshot at :1969); backend/app/services/actor_context.py (no official-data input); backend/tests/test_official_data_downstream.py:118-127 pins the exclusion
- Evidence: _dossier_uses_canonical_intelligence is true for sealed legacy actors.json (deerflow_research.py:4004 writes actor_intelligence_contract; the legacy engine defaults to 3 parallel lanes plus legacy global synthesis). Canonical packs admit only LLM-extracted quantitative_facts (actor_context.py:1344). v3 strips the contract (linear_research.py:6273) and so uses the unversioned brief.
- Impact: With RESEARCH_ENGINE=legacy, simulation agents never see official statistics, although these are public, source-bound S1 evidence: exactly the 'explicitly-public, source-bound rows' the canonical brief admits.
- Fix: When building actor-context/v1 packs, emit official observations as sealed public rows (visibility=public, source_ref=S<n>, knowledge cutoff) and render them via historical_snapshot in _build_canonical_public_world_brief. Actor-private denial stays unchanged. Test: v1 dossier plus datasets → the brief contains the snapshot, and actor-private rows are still denied.

### D3 BUG (medium) — An invalid binding wipes all research context for manual report/chat; the binding pins an absolute handoff path
- Location: backend/app/services/pipeline_orchestrator.py:7096-7099 (invalid → return all-None); backend/app/services/official_data.py:107-108, 148 (absolute handoff_dir fingerprinted); consumers backend/app/api/report.py:387, :1561
- Evidence: Repro scratchpad/review/repro/binding_move.py: bind a sim, then move the install root (repo rename, backup restore, data dir change). load_research_dossier_for_simulation returns situation_brief/actors/research_report/actor_dossier all None (before the move all were present). Any later change to one of the six fingerprinted files has the same effect. test_official_data_consumers.py:195 even asserts research_report is None. The contract only required official-data enrichment to become unavailable.
- Impact: Manual reports and chat for bound simulations silently fall back to cold-graph blind search and lose the actor dossier and research report: a regression wider than the official-data feature.
- Fix: On an invalid binding, null only official_data and keep the dossier lookup. Store the handoff location relative to PIPELINE_DATA_DIR (or as pipeline_id + relative path) and resolve it at read time via PipelineManager.resolve_handoff_dir. Tests: relocation keeps the dossier; a tampered datasets.json nulls only official_data.

### G5 GAP (low) — Official-data resolutions never feed calibration or any user-facing surface
- Location: backend/app/services/forecast_ledger.py:439-510; backend/scripts/resolution_monitor.py:772-774 and :910-916 (summary omits data_brier); backend/app/services/report_agent.py:3408-3418 (historical_calibration uses scenario-only calibration_summary); README.md:1109-1115
- Evidence: data_resolutions.jsonl is read only to compute a per-run data_brier inside run_monitor output. The `summary` CLI prints only market_brier and scenario_calibration. forecast.json historical_calibration ignores binary official outcomes. No API or frontend shows them, and the README monitor section does not mention data_resolutions.jsonl.
- Impact: The first automated binary resolution source never closes the calibration loop, so the track record cannot inform confidence.
- Fix: Add data_brier_summary() to the `summary` CLI and to forecast.json historical_calibration (as a separate binary track record), surface it in the Settings→Maintenance monitor result, and document it. Test: a seeded data_resolutions.jsonl appears in summary and in the next forecast.

### I2 IMPROVEMENT (medium) — Official data-release calendar for sim scheduled events, monitor ETA and rerun triggers
- Location: datamcps/fred-mcp-server-main/src/fred/tools.ts:79-150 (no release-dates tool); backend/app/services/simulation_config_generator.py:724-737, 1030+ (events only from research key_events); backend/scripts/resolution_monitor.py resolve_official_forecasts (blind polling)
- Evidence: Scheduled sim events come only from timeline key_events. Pending anchors are refetched every monitor run until a value appears. scheduled_rerun has no data-release trigger.
- Impact: Simulated worlds miss scheduled market-moving releases (CPI, payrolls) inside the horizon. The monitor wastes quota and cannot say when an anchor will resolve.
- Fix: Add a release_calendar(series) capability: FRED series/release plus release/dates?include_release_dates_with_no_data=true (FRED_API_KEY), and the BLS schedule, cached in DATA_SOURCES_CACHE_DIR. Use it to (a) add dated 'scheduled release' events in SIM_TEMPORAL_MODE=calendar, (b) attach expected_release to pending anchors and skip provider calls before that date, (c) let scheduled_rerun re-forecast after an anchored series' release.

### I3 IMPROVEMENT (medium) — Seed typed indicator nodes into the knowledge graph instead of only a pipe-table text episode
- Location: backend/app/services/pipeline_orchestrator.py:12858-12869 (snapshot chunk); backend/app/services/ontology_generator.py:407-408 (signal/indicator archetype exists)
- Evidence: The graph receives one bounded text episode of at most 8 latest values ('Indicator | Value | Period | Units | Source'), and Graphiti's LLM extraction turns it into nodes. Actors get deterministic typed seeding (_seed_research_actors) but indicators do not.
- Impact: Report-agent graph tools (InsightForge/panorama) and sim graph memory cannot reliably retrieve exact indicator values or link them to geographies and actors.
- Fix: Seed one typed node per stored series (attributes: series id, latest value and period, units, frequency, source S#, provider; valid_at = observation period), add edges to matching geography/actor nodes, and keep the text episode for narrative. Test: a graph query by indicator name returns the exact value.

### DOC2 GAP (low) — feature_list.json marks the official-data feature passes:true on offline-only evidence
- Location: feature_list.json (feature_official_quantitative_research, added in eac717b); agent-progress.txt (2026-10-11 entries)
- Evidence: passes:true while live retrieval fails for 61/196 catalog series (K2), CI is red (D1), and the 'deployment wiring' step has only offline proof. That breaks the harness rule 'Don't mark passes: true unless it truly works'. agent-progress entries contain fused tokens ('and6372005', 'gate2025', 'the64unrelated').
- Impact: Misleading continuity state: the next session will not prioritise the live and CI breakage.
- Fix: Set passes:false, or split into offline and live entries, until a live smoke run and green plain-pytest CI exist. Fix the typos.

### B1 BUG (low) — A relative DATA_SOURCES_CACHE_DIR resolves to different directories in research vs backend/monitor, splitting caches and the keyless-BLS quota
- Location: deerflow_bridge/data_sources.py:873 (cwd-relative) vs deerflow_bridge/data_mcp.py:242-247 and backend/app/services/pipeline_orchestrator.py:1405-1421 (repo-relative); backend/app/services/resolution_autorun.py:44-48 (cwd=backend/scripts)
- Evidence: DataSources uses Path(env['DATA_SOURCES_CACHE_DIR']) as given, relative to the process cwd. The research child receives an absolute repo-relative path. The monitor subprocess runs with cwd=backend/scripts and Flask with cwd=backend. bls-quota.json lives in the cache dir (data_sources.py:1424-1443).
- Impact: Duplicate caches and two independent 20/day keyless-BLS counters, which can exceed BLS's per-IP limit.
- Fix: Resolve relative values against the repo root in DataSources too (reuse data_mcp._source_path). Test: the same env from two different cwds resolves to the same absolute directory.

### G6 GAP (low) — Simulations created outside the pipeline are never bound and so never get official data
- Location: backend/app/api/simulation.py:218 (create_simulation without binding); backend/app/services/pipeline_orchestrator.py:7096-7120
- Evidence: Only pipeline_orchestrator.py:9132 and :13155 call bind_simulation_research. A simulation created manually for a pipeline project gets status 'missing' and official_data None in the world brief, manual report and chat.
- Impact: Manual what-if simulations on pipeline projects lose the quantitative baseline.
- Fix: When the project belongs to a pipeline, bind the new simulation to that pipeline's current sealed generation at creation (same create-only semantics).

### G7 GAP (low) — The v3 official-data prefetch phase does not appear in the progress UI
- Location: deerflow_bridge/linear_research.py:4350-4395 (phase('data') with no research:v3:data stage/ok log); backend/app/services/research_progress.py:112-145 (unknown phases → None)
- Evidence: The data phase can run up to 150 s (IMF calls take 30-50 s) but emits only a warn line on failure. The progress estimator maps plan/gather/gap/synthesize/qa/finalize only.
- Impact: Progress sits at 9-10% with no status during prefetch, and operators cannot see data retrieval happening or failing.
- Fix: Emit '[stage] research:v3:data start (N series)' and '[ok] research:v3:data done (stored=k, failed=m)', add _V3_DATA_BAND=(10,13) and shift gather. Test: the progress parser maps the new lines.

### DOC1 GAP (low) — README (and its zh-CN mirror) omit downstream official-data behaviour and the v3 dataset cap
- Location: README.md:867-874 (Simulation config), :1109-1115 (Resolution monitor); README.zh-CN.md mirrored lines; .env.example:502
- Evidence: Neither the world-brief official snapshot, the graph 'Official statistical observations' episode, data_resolutions.jsonl/data_brier nor the 12-distinct-dataset v3 cap is documented. The two READMEs are otherwise in lockstep (both 1937 lines, identical knob mentions).
- Impact: Operators cannot tell what reaches simulation agents or where official outcomes are recorded.
- Fix: Add these facts to both READMEs in lockstep and to .env.example.

### H1 IMPROVEMENT (low) — Vendored datamcps tree: dangling out-of-tree symlink, non-runtime personal images, no upstream provenance record
- Location: datamcps/data360-mcp-dev/packages/mcp-ui-angular/.npmrc (symlink → ../../../vercel-ai-chatbot/frontend/.npmrc); datamcps/fred-mcp-server-main/assets/social/linkedin-*.jpg; datamcps/ (no VENDORED/provenance file)
- Evidence: `git ls-files -s` shows mode 120000 for .npmrc pointing outside the repo. Two LinkedIn headshots (about 560 KB) are committed. Nested upstream .github/workflows are inert. Licences are present for all six servers, no build outputs are committed, and hook litter (deerflow_bridge/logs, skills/forecast-visuals/scripts/logs) is git-ignored and filtered by runtime_skill_sync._SOURCE_NOISE_DIRNAMES.
- Impact: Supply-chain and licence hygiene: there is no way to track upstream security fixes, and the repo carries an out-of-tree link and irrelevant personal images.
- Fix: Remove the symlink and the social assets. Add datamcps/VENDORED.md (upstream URL, commit/tag, retrieval date, local patches: none, licence). Add a test that every vendored symlink resolves inside datamcps/.

### I4 IMPROVEMENT (low) — Live data-server health check in doctor --deep and a Settings test endpoint
- Location: scripts/doctor.sh:163-248 (file/node/key-name checks only); backend/scripts/preflight.py; backend/app/api/settings.py:151 (only /llm/test); backend/app/services/pipeline_orchestrator.py:7128 preflight_pipeline
- Evidence: setup_datamcps.sh --check reports all six 'up-to-date' (exit 0) while live calls fail for 61/196 catalog series (K2). Nothing exercises an MCP handshake.
- Impact: Broken providers are discovered only mid-research, as silent evidence gaps.
- Fix: doctor --deep plus POST /api/settings/data-sources/test: for each enabled provider, run MCP initialize + list_tools + one cached catalog fetch (FRED via keyless CSV, never BLS), and report ok/degraded/unavailable without secrets.

### I5 IMPROVEMENT (low) — Give simulation agents trend context, not just one latest point per series
- Location: backend/app/services/official_data.py:247-320; backend/app/services/report_agent.py:2420-2433 (report pack already computes YoY and the 5-year range)
- Evidence: historical_snapshot renders 'Indicator | Value | Period | Units | Source' with one latest observation.
- Impact: Agents argue from level only, missing direction and momentum.
- Fix: Add YoY change and 5y-range columns from series_stats (historical-only), within the existing budget.

### I6 IMPROVEMENT (low) — Frontend surfaces for official data (datasets, provider status, data outcomes)
- Location: frontend/src/utils/vizManifest.js:117-118 (only two caption translations added); backend/app/services/pipeline_orchestrator.py:9956 (datasets artifact) and :10554-10558 (CSV discovery)
- Evidence: grep finds no frontend consumer of the datasets artifact, data-source status or official resolution outcomes. Frontend: 92/92 unit tests pass and the isolated build passes.
- Impact: Users cannot inspect or download the underlying official series or see provider health, even though the data is meant to be integral to forecasts.
- Fix: Add a DossierViewer 'Official data' tab (datasets.json rows with series, latest value, units, S# and CSV download via the existing artifact endpoint), a Settings data-source card backed by I4, and monitor result rows for data outcomes.


#### Phase coverage
| Phase / step | Official data used today? | Where / notes |
|---|---|---|
| Research subprocess env + deploy sync | Yes | pipeline_orchestrator.py:1401-1424, 2430-2433 pass absolute DATA_SOURCES_*. data_* modules synced to deer-flow (:1359-1365). deer-flow/config.yaml is not auto-synced, but the bridge registers the tools at runtime (:1781-1790). |
| v3 data phase (plan→prefetch→gather) | Yes, with limits | Prefetch ≤12. One run-wide 12-dataset cap is shared with agents (G4). No progress band (G7). |
| Legacy / parallel lanes + global synthesis | Yes (legacy only; v3 forces 1 track) | Lane datasets travel as validated source snapshots. _finalize_data_series runs in synthesis, and _promote_research_contract copies data/. No 12 cap (G4 downstream truncation). |
| Research contract seal / promotion | Yes | data/ and charts/ are fingerprinted (pipeline_orchestrator.py:3621-3716) and promoted transactionally. |
| research_only mode | Partial (by design) | Dossier data baseline and charts are present. The pipeline stops before capture/binding. |
| Generation capture + sim binding | Yes, fail-closed | :12648 and :13154. Not degrade-safe (D2). Invalid binding nulls the whole dossier; absolute path (D3). |
| Ontology | Indirect only | Sees the report text, including its Official Data Baseline section. No dataset input or indicator typing (I3). |
| Graph build | Partial | One text episode, 'Official statistical observations' (≤8 series, latest point; :12858-12869). Excludes wb/WEO/usgov (G2) and anything retrieved after as_of day (D5). No typed indicator nodes (I3). Absent on graph reuse. |
| Sim PREPARE world brief, unversioned (v3) | Partial | historical_snapshot appended last (simulation_config_generator.py:1969-1979). Delimiter truncation bug (D4), G2/D5 exclusions, latest point only (I5). |
| Sim PREPARE world brief, canonical v1 (legacy) | No | Early return before the snapshot (G1). |
| Actor context packs / role prompts | No (LLM-extracted quantitative_facts only) | G3. |
| Sim scheduled events / calendar | No | No data-release events (I2). |
| Worldstate base rates / decision channel | No | Seeds come from LLM forecast_inputs only. |
| Main report / seed report / manual report + chat | Yes | :13691, :9236, api/report.py:387 and :1561 pass the bound official_data (data pack, official charts, caption audit). Capped at 12 series in write order (G4). |
| Forecast extraction / probabilities | Partial | Data pack as context plus validated data_anchor. No computed statistical base rate (I1). |
| Ensemble seeds / scenario forks | Yes | Seeds inherit the parent binding (:9122-9136). Forks re-bind at their own PREPARE against the shared handoff. |
| Manual (UI-created) simulations | No | Never bound (G6). |
| Resolution monitor | Yes | resolve_official_forecasts verified live against real FRED (UNRATE 2026-08 → resolved, 4.1; CPIAUCSL#yoy → resolved, 3.353). WB/usgov/WEO always manual. No release ETA (I2). |
| Forecast ledger / calibration / backtest / golden eval | Ledger only | data_resolutions.jsonl, but no calibration, summary CLI, report historical_calibration or backtest use (G5, I1). |
| Scheduled reruns | No | No data-release trigger (I2). |
| Artifact manifest / deep links | Yes | datasets index registered (:9956), CSV partial discovery (:10554). No frontend consumer (I6). |
| Ops: setup.sh / setup_datamcps --check | Yes | --check: all six up-to-date (exit 0), but file presence only. |
| Ops: doctor / preflight / Settings | Static only | Build/node/key-name checks; no live probe (I4). |
| Env docs / drift | Yes | check_env_drift --strict passes. Cache-dir resolution inconsistent (B1). |
| CI | Red | ruff F,E9 pass and compileall passes. Unit job: K1 collection error plus 25 runner-only/stale failures (D1). |
| Frontend | Captions only | 92/92 tests pass, isolated build OK. No datasets/status UI (I6). |
| Docs | Mostly | README/zh-CN in lockstep; downstream facts missing (DOC1). feature_list passes:true premature (DOC2). |
| Repo hygiene | Mostly | Licences present, no build outputs, hook litter ignored. Dangling .npmrc symlink, headshots, no provenance record (H1). |


## review:report: Forecast report path: report_agent official-data pack, prompts, grounding and chart placement; report_visualizer official builders; forecast_extractor

### RPT-1 BUG (high) — Publication stabilizer deletes true official-data sentences unless they repeat the 3 excerpt values or use the canonical machine format
- Location: backend/app/services/report_agent.py:2484-2497 (_report_citation_support falls back to excerpt-based _semantic_citation_support), :4457-4470, :8235+ (_stabilize_publish_markdown quantitative rewrite); deerflow_bridge/data_sources.py:349-352 (render_series_page 'change' formatted with series units)
- Evidence: Setup: real bundle with v3-shaped source excerpts built like linear_research._data_summary_lines (handoff3), then the real sequence _inject_visualizations -> _apply_report_lint -> _stabilize_publish_markdown -> _enforce_final_publish_audit (scripts drive_publish_claims2.py, outputs pub_claims3/4). All sentences below survived lint and were rewritten by stabilization (quantitative_rewrites=1):
- 'The unemployment rate peaked at 14.8% in April 2020 [S1].' The stored fred:UNRATE value for 2020-04-01 is 14.8. Sentence deleted.
- 'Real GDP reached 24,408 billion chained 2017 dollars in the second quarter of 2026 [S2].' The stored value is 24408.011. Sentence deleted.
- 'World GDP growth is 3.06% in 2026 according to the IMF [S9].' This is a stored publisher value with unknown status. Sentence deleted; it should be kept with its status label.
- 'Unemployment fell 0.2 percentage points from a year earlier [S1].' Citation stripped. The data pack itself says 'Year-over-year change: -0.2 percentage points [S1]', but the source excerpt says 'change -0.2% (-4.55%)', which mislabels a percentage-point change as percent.
- Kept: only claims that restate the excerpt's latest / year-earlier / 5-year-range values, and the robotic form 'fred:UNRATE: 4.2% on 2026-09-01 (historical observation, units: Percent)'. No prompt asks writers to use that form.
- Impact: Accurate quantitative prose drawn from stored official series is removed or loses its citation, which hollows out the quantitative side of the report. Writers can safely cite only three summary numbers per series.
- Fix: Add deterministic support backed by the carrier. When a cited source maps to a carrier row (source.dataset.series or official_source_tag), parse the claim's numbers and period. Treat the claim as supported when each number equals a stored observation of that series at the displayed precision. Accept the format_value rounding, thousands separators and billion/trillion scaling relative to the units. A value with projection or unknown status counts only when the sentence labels it as a projection or publisher value. Return False only for contradictions (e.g. a period that is stored but has a different value). Also fix data_sources.render_series_page so a change in percent units reads 'pp'. Regression test: the 7-sentence fixture keeps every exact-value sentence and its [S#] through _stabilize_publish_markdown, while a fabricated '15.2% in April 2020' is still removed.

### RPT-2 BUG (high) — Chinese primary reports with official charts fail the final publish audit unless the LLM language-purity pass translates the English chart titles
- Location: backend/app/services/report_agent.py:9330 and :9387-9400 (_render_viz_block uses the English manifest caption for alt text and the italic caption even when zh), :8553-8558 (any contamination line is a hard issue), :11809-11814 (purity pass is the only repair and needs an LLM); backend/app/services/report_visualizer.py:4584 (6-word title 'Official Series History and Forecast Thresholds')
- Evidence: drive_publish.py ran in Chinese on the real bundle and raised RuntimeError '最终发布完整性门未通过：最终 Markdown 含 8 行目标语言污染'. detect_language_contamination returned exactly these lines: 4 x '![Official Series History and Forecast Thresholds](charts/official_series_*.png)' and 4 x '*Official Series History and Forecast Thresholds*'. A 3-series bundle gave 6 lines. When a successful purity translation was simulated, the same report passed (hard_passed True). The English run passed. CHART_TITLES_ZH already maps this title to '官方序列历史与预测阈值', but it is applied only in the translation-variant path (report_agent.py:7788).
- Impact: Every Chinese-language forecast that has official data depends on an extra LLM call to publish. If MiniMax quota runs out or the purity mapping is malformed, the report is never marked completed.
- Fix: In _place_visualizations, when zh, map the manifest caption through report_visualizer.CHART_TITLES_ZH before calling _render_viz_block, covering both alt text and the italic caption. Also apply localize_chart_alt_text to the Visual Annex. Test: a zh report with an official carrier and an LLM that raises on any call reaches _enforce_final_publish_audit with hard_passed True.

### RPT-3 BUG (high) — Data anchors are effectively unreachable for realistic model output, which disables threshold charts, the 'Official series to watch' table and official auto-resolution
- Location: backend/app/services/forecast_extractor.py:1602-1680 (_data_anchor_matches_binary: the criterion prefix must equal the series ID, the suffix may only be '[in|for|on] <period>', and the statement prefix must be the ID, the English title or geography+title); :2970-2981 (prompt only says to 'include' the fields); :1078 (base prompt requires the criteria to name the SOURCE); title_zh is not among the labels
- Evidence: Probed _normalize_binaries on the real carrier with a valid anchor {fred:UNRATE >= 5 Percent 2027-06}.
- Rejected criteria: 'fred:UNRATE >= 5% in 2027-06 (source: FRED).', 'fred:UNRATE >= 5% in 2027-06, per the BLS release on FRED.', 'Resolves YES if fred:UNRATE >= 5% in 2027-06.'
- Rejected statements: 'The US unemployment rate >= 5% in June 2027', 'US unemployment rate reaches at least 5% in June 2027', '失业率 >= 5% 2027年6月', '美国失业率在2027年6月 >= 5%'.
- Accepted: only bare forms such as 'Unemployment Rate >= 5% in 2027-06' with 'fred:UNRATE >= 5% in 2027-06'.
- Downstream consumers re-run the same gate: report_visualizer.py:4326-4334, forecast_extractor.py:3817-3842 and the resolution monitor.
- Impact: In live runs the threshold lines, the watch table and data-based resolution will almost never appear, and Chinese reports essentially never get them. When an anchor does pass, the Part 1 headline table shows machine IDs instead of readable forecasts.
- Fix: Make the validated structured data_anchor authoritative. Keep validate_data_anchor and replace the exact-text match with a consistency check: the statement and criterion contain the threshold number, the comparator is compatible as a symbol or word (exceed / at least / below / 超过 / 不低于), the period matches, and there is no conflicting threshold or negation. Then append a canonical settlement sentence to resolution_criteria deterministically, e.g. 'Official resolution: fred:UNRATE ≥ 5 Percent for 2027-06 (FRED <url>)'. Add title_zh and US/USA/United States aliases to the labels. Put an exact worked example in the prompt. Tests: the 7 rejected variants anchor; the existing negation, compound and wrong-period counterexamples in test_report_official_data.py still fail.

### RPT-4 IMPROVEMENT (high) — No empirical outside view computed from official history for binaries or spine scenarios
- Location: backend/app/services/forecast_extractor.py:2891+ (extract_binary_forecasts), :3426+ (derive_forecast_spine), backend/app/services/report_agent.py:2394-2445 (_build_data_pack gives only latest value, YoY and 5-year range)
- Evidence: The spine prompt asks base_rate_anchor to cite a metric and date from the pack, but nothing computes a base rate. Probabilities for anchored thresholds (e.g. UNRATE >= 5 in 2027-06 with latest 4.2) come entirely from the model, even though 119 stored monthly observations are available. Charts show only a flat threshold line.
- Impact: This is the user's stated goal: give forecasts a quantitative aspect from official data. Deterministic base rates would calibrate binaries and give readers an auditable anchor.
- Fix: For each validated anchor and scenario metric range, compute from stored historical observations: how often the comparator held over the window; the empirical distribution of h-step changes (h = periods from the latest observation to the target); P(latest + Δ satisfies the threshold); and the distance to the threshold in historical σ. Store the result as data_anchor.empirical_base_rate {p, n, window, h, method}, excluding projections and partial periods. Feed it into the binary and spine prompts as the outside view, show it in the Part 1, resolution and brief tables, and draw an empirical quantile fan on the detail charts. Tests: a deterministic p on a fixed UNRATE fixture; projection points are excluded.

### RPT-5 BUG (medium) — Data pack truncated mid-row in the spine prompt and silently dropped beyond 3500 chars; rows have no human titles or geography
- Location: backend/app/services/report_agent.py:3129 -> forecast_extractor.py:3458/3482 (REPORT_SPINE_INPUT_CAP_FACTS=3000 while the pack is up to 3500, report_agent.py:2442); report_agent.py:2416-2418 (row label is the series ID only); :2437 (URL line repeated on every row)
- Evidence: Real 12-series carrier:
- The pack is 3490 chars with 11 rows; the 12th (usgov:treasury/mts_deficit) is dropped without any 'omitted' note.
- The spine prompt receives text cut at 'wb:IMF_WEO_NGDP_RPCH/USA: 2.32% on 2026-01-01 (', so the '(unclassified publisher value)' label is lost and the debt_to_penny row disappears.
- Rows show only IDs such as 'imf:WEO/G001.NGDP_RPCH.A' (which is World growth) with no title or geography, while each row spends about 80 chars on 'Transform: none. Source: <url>' that the [S#] tag already covers.
- Impact: The spine can mistake a publisher value for an actual and loses rows. Section writers can misidentify what an ID measures.
- Fix: Render the pack with an explicit budget that truncates only at row boundaries and adds 'N further series omitted: ids'. Pass a spine-sized pack or set cap_facts >= len(pack). Add title (title_zh for zh) and geography; drop the URL line when a tag exists; order rows anchored, then KIQ-linked, then cited. Test: a 12-row real-shaped carrier gives a spine prompt where every row's status suffix and an omission note are intact.

### RPT-6 BUG (medium) — Partial-period monthly averages of daily data are presented as the latest historical observation, and pack, charts, resolution table and simulation snapshot disagree
- Location: deerflow_bridge/data_sources.py:1280-1296 (every aggregated month complete=False, resolution_safe=False); backend/app/services/forecast_extractor.py:1521-1550 (official_observation_kind ignores provenance.periods and aggregation); report_agent.py:2402-2433; report_visualizer.py:4458-4464; forecast_extractor.py:3830-3836; backend/app/services/official_data.py:262-263
- Evidence: Real fred:DGS10, fred:T10Y3M and usgov:treasury/debt_to_penny have periods['2026-10-01'] covered_end 2026-10-11, short of end 2026-10-31 (retrieved 2026-10-11).
- The pack shows 'fred:DGS10 | 5.27% / 2026-10-01' as 'Latest historical value', and 'YoY 1.2048 pp' compares a partial month with a full one.
- In official_series_oaefafronmbbacta.png the 'Latest historical observation' diamond sits on the 7-trading-day October mean.
- The same report's resolution table shows 'Historical observation unavailable' for T10Y3M and debt_to_penny.
- historical_snapshot drops these rows entirely.
- Impact: The report treats a partial month as a measured fact, and the same report contradicts itself.
- Fix: Add a 'partial-period average' kind when covered_start > start or covered_end < end. In the data layer, set complete=True for fully covered past months. Exclude partial points from latest and YoY, label them '(partial)' with a distinct style, and describe the series as 'monthly mean of daily data'. Unify the semantics of the resolution block, the pack and the snapshot. Test: a carrier whose last month is partial gives a pack 'latest' equal to the last complete month, and the chart diamond is not on the partial point.

### RPT-7 GAP (medium) — IMF WEO/GEP publisher projections never reach the report: the default window ends today and the first fetched window is immutable
- Location: deerflow_bridge/data_sources.py:1098-1100 (finish = today when end is None); deerflow_bridge/research_gateway.py:3684-3686 (prefetch_data calls get_many without end), :3631-3641 (the first successful window is immutable for the run); deerflow_bridge/skills/data-sources/SKILL.md (no guidance to request projection years)
- Evidence: Real imf:WEO/G001.NGDP_RPCH.A provenance shows requested_end 2026-10-11, tool args end_year 2026 and delivered_end 2026-01-01. wb:IMF_WEO_NGDP_RPCH/USA ends in 2026, and the GEP series end in 2026 with n=5. Every observation has flag 'unknown' and projection_from is empty. The report pack shows 'unavailable' plus 'unclassified publisher value', and the charts only ever use the grey 'status unknown' lane; the 'Publisher projections' style never appears for real data.
- Impact: Publisher projections are the most decision-relevant WEO and GEP content for a forecast, and they never appear next to the model's own forecast.
- Fix: For projection-bearing flows (WEO*, GEP*, catalog entries flagged as projections), default end to today + 6 years or the forecast horizon in _request. Where the vintage is explicit, classify years >= the vintage publication year as projections. Tell research agents to request through the horizon. Test: a WEO request without end gets end_year >= current year + 5, and the chart renders a projection lane.

### RPT-8 BUG (medium) — Official chart selection is manifest-ordered: half the series are never charted and detail charts repeat dashboard panels; KIQ ranking is dead code
- Location: backend/app/services/report_visualizer.py:4571 (dashboard uses panels[:6]), :4577-4584 (detail charts ranked[:4] by thresholds, then kiqs); deerflow_bridge/data_sources.py:166 (Series.kiqs is never set by any producer; no kiqs= assignment in research_gateway, data_tools or linear_research)
- Evidence: Real 12-series run: the dashboard holds UNRATE, GDPC1, FEDFUNDS, T10Y3M, SAHMREALTIME and DGS10. The BIS policy rate, WDI growth, both WEO rows, debt and deficit appear in no exhibit, even though BIS, WDI and debt had anchored thresholds. With no forecast (pub_en run), the 4 detail charts are exact repeats of dashboard panels 1-4. Every datasets.json row has kiqs [].
- Impact: Cross-country providers (BIS, WB, IMF, usgov) are almost never visualized when FRED series were fetched first, and report space goes to duplicate charts.
- Fix: Populate Series.kiqs from the requesting KIQ in research_gateway.data_get and prefetch_data. Rank series by anchored, KIQ-linked, cited, then provider diversity. Make the dashboard cover all <=12 series (2-column small multiples or two pages). Emit detail charts only for series with an anchor or scenario band. Test: every carrier series appears in at least one exhibit, and no detail chart without a threshold duplicates a dashboard panel.

### RPT-9 GAP (medium) — Scenario numeric bins are never compared with official history: the band matcher cannot match real series
- Location: backend/app/services/report_visualizer.py:4353-4378 (annual only, no transform, units must be literally percent/%/percentage, metric must equal the normalized title, scope must equal the horizon year); forecast_extractor._extract_comparable_numeric_range; the spine prompt never asks for structured ranges
- Evidence: Only 6 of the 69 annual catalog entries have units 'Percent', and live they are stored as 'Percentage change per annum', so the units never match. _extract_comparable_numeric_range returns None for 'GDP (annual % growth) between -3% and 0% in 2027' and for 'GDP annual growth between -3% and 0% in 2027'. WEO units are 'Percent change'. _official_scenario_bands returned [] for the real WDI row.
- Impact: Scenario bins are never compared with official history in the charts, one of the explicit report questions.
- Fix: Have the spine emit an optional per-scenario metric_range {series, low, high, period, units}, validated against the carrier the way data_anchor is, and draw bands from it at the target period. Optionally annotate where each bin falls in the historical distribution. Test: a spine fixture with a fred:UNRATE monthly range draws its band.

### RPT-10 GAP (medium) — No deterministic official-indicator table in the report; plan and section prompts carry no data-use rules; chart placement is a broad keyword match
- Location: backend/app/services/report_agent.py PLAN/SECTION prompt templates (no 'official' rule anywhere above line 1540 or in 9900-11500), :2499-2525 (pack is only a prompt prefix), :8950 and :9408-9420 (placement keywords include 'data' and 'baseline'; all official charts go under the first matching heading)
- Evidence: Official numbers reach the report only through LLM transcription. The canonical sentence format used by official_data_statements is never requested. All 5 official charts were inserted together right after the first heading matching data, baseline, economic or indicator, ahead of that section's prose. The threshold charts are not placed next to Part 1 or the resolution section.
- Impact: Whether the report actually contains official numbers depends on the model, and those numbers are exposed to RPT-1 deletion.
- Fix: Inject a deterministic bilingual 'Key official indicators' markdown table (title, latest value and period, YoY, 5-year range, status, [S#]) as a fixed Part 2 or 'Quantitative baseline' section. Require the outline planner to include that section when a pack exists. Add a section rule that claims about listed indicators must use pack values, periods and tags. Place the dashboard in that section and the threshold charts beside Part 1 or the resolution section. Test: the table matches carrier values byte-for-byte and survives stabilization.

### RPT-11 GAP (medium) — Executive brief and digest contain no official data
- Location: backend/app/services/exec_brief.py:674-746 (_render_brief), :527-547 (_build_watch_block uses only binary dates), :340-358 (_find_scenario_chart picks only the scenario chart)
- Evidence: grep for 'official' or 'data_anchor' in exec_brief.py finds nothing. 'What to watch' lists statements with dates but no latest official value, threshold or source.
- Impact: The decision-maker deliverable has no quantitative baseline from official sources.
- Fix: Add a 'Key indicators' mini-table built from the data_anchor fields in forecast.json (series, latest_value and latest_date, threshold and period, source_url) and/or a persisted report-local snapshot (see RPT-12). Prefer anchored binaries in 'What to watch', shown as latest vs threshold. Optionally embed the official_indicators png_path. Test: a forecast with anchors produces brief rows; the zh labels are localized.

### RPT-12 GAP (medium) — Frontend Forecast Dashboard and binary table show no official indicators or data anchors; the report keeps no carrier copy and has no API; the gallery drops attribution
- Location: frontend/src/components/research/ForecastReport.vue:158-190 (dashboard has only scenario cards and market tiles); frontend/src/components/research/BinaryForecastTable.vue:23; frontend/src/utils/binaryForecasts.js:93-150 (market_anchor only); frontend/src/utils/vizManifest.js:43-75 (normalizeVizGallery keeps the caption but drops source_caption and provenance); backend: the report folder has no official_data snapshot and backend/app/api/report.py has no endpoint for it
- Evidence: The only frontend change in eac717b is two ZH caption strings in vizManifest.js. forecast.json already carries data_anchor {series, latest_value, latest_date, threshold, source_url}, but nothing renders it.
- Impact: The interactive Forecast Dashboard has no quantitative indicator view. The report is not self-contained for re-renders or audits, and fallback gallery cards show official charts with no source.
- Fix: Persist report-local official_data.json (the exact carrier used plus its sha256) during generate_report. Add GET /api/report/<id>/official-data. Add indicator tiles to FORECAST-DASH (latest, period, Δ, sparkline, source link) and a data-anchor column to BinaryForecastTable (latest vs threshold). Show source_caption on gallery cards. Tests: vitest for the anchor model and gallery attribution; an API test.

### RPT-13 BUG (medium) — backfill_report_visuals.py drops official exhibits and leaves orphan 'Source:' captions
- Location: backend/scripts/backfill_report_visuals.py:342-356 (_artifacts has no official_data), :368-388 (_offline_report_agent has no official_data), :87-135 (strip_generated_visuals removes the marker, image and italic title but not the following '*Source: …*' line)
- Evidence: Running strip_generated_visuals on the published real-bundle report removed the 5 official charts and kept all 5 '*Source: [fred](<https://fred.stlouisfed.org/series/UNRATE>) [S1]; Percent; M; SA*' lines. Rebuilding the manifest without official_data recreates no official charts, and the offline agent has no carrier, so the orphaned captions are audited as ordinary claims.
- Impact: Re-rendering visuals on any report that has official data silently removes the data visualizations and corrupts the prose.
- Fix: Load the carrier with official_data.load_official_data(handoff) (respecting the binding) into the artifacts and set agent.official_data. Make strip_generated_visuals also remove a following '*Source: …*' or '*来源：…*' line. Test: backfilling a report with official charts keeps 5 charts and their captions and passes _enforce_final_publish_audit.

### RPT-14 GAP (low) — Report chat, critique/premortem and fallback forecast extraction receive official data but never use it
- Location: backend/app/services/report_agent.py:11999-12040 (chat system prompt is report text plus tools; official_data passed at api/report.py:1561 is unused), :3197-3201 (fallback extract_structured_forecast gets no pack), backend/app/services/forecast_extractor.py:3878-3900 and :3987 (critique and premortem 'base-rate neglect' checks run without data; both are off by default)
- Evidence: Chat never reads self._data_pack. The report agent has no stored-data lookup tool (_define_tools, report_agent.py:9743-9824, lists only graph and simulation tools).
- Impact: Users asking chat about indicator values get answers drawn only from report text. Base-rate critique has no data to work with.
- Fix: Append self._data_pack to the CHAT system prompt, or add a read-only stored_official_data(series, period) tool that never fetches. Pass the pack to the critique, premortem and fallback extraction prompts.

### RPT-15 BUG (low) — Mislabeled YoY units for 'Per cent' series and inconsistent number formatting across pack, resolution table and chart labels
- Location: backend/app/services/report_agent.py:2426 (regex 'percent|%') vs deerflow_bridge/data_sources.py:315 ('per\s*cent|%'); forecast_extractor.py:3832-3836 (raw floats); report_visualizer.py:4472 and :4527 ('{threshold:g}'), :4480 (horizon annotation position); data_sources.py:316 (4 decimals for levels)
- Evidence: Real pack and charts:
- 'Year-over-year change: -0.25% Per cent per year [S7]': a BIS policy-rate change in percentage points rendered as a percent.
- '40269094993348.9844 / 2026-10-01' and 'Year-over-year change: 2307966401253.7656 U.S. dollars'.
- The resolution table shows '3.875 Per cent per year' where the pack shows '3.88%', plus '>= 5.0 Percent' and '> 45000000000000.0 U.S. dollars'.
- In official_series_mrsddaomqfkcltcp.png the label 'Model threshold > 4.5e+13 (2027-12); P(yes)=20%' overlaps the 'Forecast horizon' annotation.
- Impact: Misleading units, unreadable trillions and inconsistent values within one report; the pack's instruction to quote values exactly pushes these into prose.
- Fix: Share one percent regex. Show scaled values (e.g. '$40.27 trillion') and keep exact values in tables and CSV. Use format_value in the resolution block and chart labels. Anchor the horizon annotation at y=1.02 with yanchor bottom and put the threshold label on the left. Test: the BIS pack row reads 'percentage points' and resolution rows use format_value.

### RPT-16 GAP (low) — Datasets the research report did not cite cannot be cited in the forecast report; the watch table is untagged
- Location: backend/app/services/report_agent.py:2222-2260 (citation index built only from research sources.json, capped by REPORT_SOURCES_INDEX_MAX=60); deerflow_bridge/linear_research.py:6078-6118 (sources.json holds cited sources only); backend/app/services/forecast_extractor.py:3841 (watch table uses '[Source](<url>)' instead of [S#])
- Evidence: In the real run, the uncited dataset (usgov mts_deficit) would render as 'unindexed source' in the pack, and its chart caption has no tag. The 'Official series to watch' rows carry no citation marker.
- Impact: Writers cannot cite those stored series, so their numbers are dropped by grounding (see RPT-1).
- Fix: Append carrier datasets missing from sources to the report citation index (tier S1, source_origin official_data, dataset identity) and tag watch-table rows with the report's [S#].

### RPT-17 IMPROVEMENT (low) — Official exhibits are English-only and indistinguishable from one another
- Location: backend/app/services/report_visualizer.py:4441-4442 and :4554 (subplot titles from the English title), :4379-4385 (_OFFICIAL_STYLES English legends), :4584 (identical title and caption on every detail chart)
- Evidence: Every series in the bundle has a curated title_zh (e.g. fred:UNRATE '美国失业率'), but zh reports show English chart titles, legends and axis labels. All four detail charts share the alt text 'Official Series History and Forecast Thresholds'.
- Impact: Readability and accessibility for zh readers; figures cannot be told apart.
- Fix: Render zh variants (titles from title_zh, localized legends) for zh primary reports and translations. Include the series title in each chart's alt text and caption through a localized template, keeping translation numeric parity.


#### Phase coverage
Report workflow step | Official data used today?
1. Carrier hand-off | Main pipeline (pipeline_orchestrator.py:13691), seeds (:9236), manual generate (api/report.py:387) and chat (:1561) all call load_for_simulation. Data loads only when official_research_binding.json is valid. There is no report-local copy of the carrier (RPT-12).
2. Outline planning (report_agent.py:10175) | Data pack is prefixed. No instruction to plan a quantitative section (RPT-10).
3. Section writing, ReAct and native (:10806 / :10982) | Data pack is prefixed. No data-use rules and no stored-data lookup tool (RPT-10, RPT-14).
4. Forecast spine (:3129) | Pack is passed as quantitative_facts but cut at 3000 chars, mid-row (RPT-5). No computed base rates (RPT-4). Scenario bins are not linked to series (RPT-9).
5. Critique / premortem / fallback extraction | Not used (RPT-14). Critique and premortem are off by default.
6. Binary extraction (:3331) | Pack plus data_anchor instructions. Anchors are admitted only in robotic exact forms (RPT-3).
7. Part 1 binary table (forecast_extractor.py:3600) | No data or anchor column.
8. Part 2 synthesis (:9058) | Pack is included.
9. Resolution section (:5061 / forecast_extractor.py:3817) | 'Official series to watch' appears only when anchors exist. Values are unformatted (RPT-15) and partial-period handling is inconsistent (RPT-6).
10. Visualizations (:9197 -> report_visualizer.py:4558) | Dashboard of the first 6 series plus 4 detail charts. Thresholds rarely appear; scenario bands never match (RPT-7, RPT-8, RPT-9). PNGs were inspected: gaps, units and the latest-value marker render correctly, but the partial month is marked as historical and threshold labels collide.
11. Citation finalization / stabilization | Only excerpt-matching or canonical sentences survive; true stored values are deleted (RPT-1).
12. Final read-only audit | Caption audit passes in English, including the resolution block (verified on the real bundle). Chinese reports hard-fail on English chart titles unless the purity LLM succeeds (RPT-2).
13. Language purity | LLM-translates the English chart titles at a cost (RPT-2).
14. Translation variant | Chart alt text is localized. Chart images are English-only (RPT-17).
15. PDF | Embeds the static PNGs. OK.
16. Executive brief / digest | No official data (RPT-11).
17. Frontend | Embedded charts appear in the markdown only. Dashboard and binary table show no official data; gallery cards have no attribution (RPT-12).
18. Chat | Carrier is passed but unused (RPT-14).
19. Visual backfill script | Drops official charts and orphans their captions (RPT-13).
20. Tests | All 123 official-data report tests pass under plain pytest. There is no Chinese-publication test and no realistic-anchor test.


## review:legacy: Legacy research engine (deerflow_research.py data helpers/prompts/hooks, data_tools.py), harness/config/runtime registration and deployment, data-sour

### L10 BUG (high) — Legacy multi-lane global synthesis cannot promote research when any lane captured official data (dataset page/file paths point to lane-local files)
- Location: deerflow_bridge/deerflow_research.py:16207-16281 (_finalize_data_series rewrites only dataset.file for selected rows), _copy_official_source_fields ~1934-1946; backend/app/services/pipeline_orchestrator.py:6619 (merge_sources_union), ~11850 and 11284 (synthesis_dir = tempfile.mkdtemp), 3541-3549 (read(dataset['page'])), 11942 (_promote_research_contract outside the retry try)
- Evidence: Lane export, seed_manifest_sources and merge_fetched_into_sources all copy the whole `dataset` dict, including page='data/candidates/<d>.txt' and, for non-selected duplicates, file='data/candidates/<d>.json'. These paths are relative to the LANE directory. Global synthesis runs in a fresh tempdir with no data/candidates. Repro (scratchpad/review/live/global_sim.py, real FRED/BIS/Data360 data via the cache): _finalize_data_series succeeds, then `po._research_data_artifacts(global_run)` raises `FileNotFoundError: [Errno 2] No such file or directory: 'candidates'`. tests/test_official_data_promotion.py only covers a single directory where the candidate files exist.
- Impact: With RESEARCH_ENGINE=legacy and RESEARCH_PARALLEL_TRACKS>1 (legacy default 3), a run where any lane called data_get fails at promotion after the full multi-lane research and global synthesis. _promote_research_contract is outside the retry block, so the research stage fails. This is critical for that mode.
- Fix: In _finalize_data_series, for every validated official row (transported or local), materialize the hash-verified evidence locally before publishing. Write row['content'] to safe_path(out_dir, dataset['page']) and json(snapshot) to the candidate file path when absent, after checking sha256 == content_sha256. Alternatively, rewrite dataset.page and dataset.file to newly written content-addressed files under data/. Also apply this to non-selected duplicate generations. Test: build a global-synthesis-like directory containing only transported rows (as in global_sim.py), run _finalize_data_series, then assert pipeline_orchestrator._research_data_artifacts and _research_contract_validation_errors succeed. Add a test_loop010_global_synthesis case with one dataset per lane.

### L1 BUG (high) — Legacy provisional citation numbers are 77-78 digit integers that the model must copy verbatim
- Location: deerflow_bridge/data_tools.py:103-104 (provisional_number), 241 (_response header); remap in deerflow_research.py:~1960-1979 (_remap_data_citations) and 4917-4930
- Evidence: provisional_number = 1_000_001 + int(sha256(...).hexdigest(), 16). A live data_get('fred:UNRATE') returned `[S14522892398752624327499412159504749267802964205158540285629542408177232544544] Unemployment Rate — fred.stlouisfed.org ...` (scratchpad/review/live/legacy_sim.log). A one-digit mis-copy survived _prepare_legacy_data unchanged in the scratch run (legacy_finalize.log). In a real run, finalize_report_citations strips such markers as dangling, so the citation silently disappears.
- Impact: Every official-data citation costs about 35 tokens and is error-prone to copy. A mis-copy loses the citation on exactly the quantitative claims the integration exists to support, leaving uncited numbers for judges and audits, and pollutes notes and fan-out absorption.
- Fix: Assign short provisional ids under the admission lock in candidate-journal order. For example, use a reserved namespace `[D1]`, `[D2]` (add D to the citation regexes for remap only), or `S9001+k`. Keep the URL/page-hash binding in the journal row and remap by journal row, not by digit string. Keep provisional_source_number as an internal integer only. Tests: provisional id <= 6 chars; remap of [D1] to the final S#; collision across lanes handled by URL.

### L2 GAP (high) — Legacy data budget is 4 calls (searches included) per thread_id, and the lead agent plus all task subagents share one thread_id
- Location: deerflow_bridge/data_tools.py:304 (RESEARCH_LINEAR_DATA_CALLS_PER_KIQ default 4 keyed by agent), 372/379 (agent = configurable.thread_id); deer-flow/backend/packages/harness/deerflow/tools/builtins/task_tool.py:253-314 (subagents inherit parent thread_id); deer-flow client.py:208-216
- Evidence: Live repro (legacy_sim.py): 1 data_search + 3 data_get on thread 'thread-main', then the 5th call returned `DATA_BUDGET_EXHAUSTED: official-data call limit reached`. The standard legacy run uses a single main thread for all passes. Design §6 intended per-KIQ budgets (quick 3 / standard 4 / deep 5) for v3, but the legacy engine has no KIQ identity.
- Impact: A whole standard-depth legacy run (lead plus delegated scoped researchers) can retrieve about 2-3 official series, which defeats 'make sure the agents know to query the data sources' and the quantitative aspect of forecasts.
- Fix: Use separate legacy knobs: per-thread 12-16 data_get calls plus 8 data_search calls (searches are cheap and catalog-first), and keep the 50-call run total. Do not charge catalog-only search hits. Key subagent budgets by task id when available (runtime.context tool_call_id or the subagent name) instead of the parent thread_id. Test: 10 gets on one thread succeed; the total cap is still enforced.

### L3 BUG (high) — Default request window ends 'today', so IMF WEO/World Bank GEP projections are never retrieved; WEO/GEP rows are all 'unknown', so research charts never show projections
- Location: deerflow_bridge/data_sources.py:1098-1100 (finish = today when end is None); skills/data-visuals/scripts/render_data.py:578-601 (_status: every wb row and every imf:WEO row -> 'unknown'); data_tools.py:296-299 (window lock prevents recovery)
- Evidence: Live: wb:IMF_WEO_NGDP_RPCH/CHN tool args end_year=2026, 25 obs 2002-2026, while metadata time_periods end 2031. imf:WEO/G001.NGDP_RPCH.A cache also has end_year 2026 and all flags 'unknown'. GEP returns n=5. series_stats latest=None, so the page Summary is empty. The rendered charts (scratchpad/review/live/run_en/charts/data_wb_imf_weo_ngdp_rpch_chn_*.png, data_compare_wb_imf_weo_ngdp_rpch.png) show 25 years as one dotted 'Unknown status' line, with no latest label and no projection segment. The catalog and skill promise 'IMF WEO by country to 2031'. Codex's renderer acceptance used a synthetic series with explicit projection flags.
- Impact: The most forecast-relevant official numbers (publisher outlooks) are silently dropped, and actual history is visually discredited. The projection shading/dashing feature never triggers on real WEO/GEP data in either engine.
- Fix: (a) In DataSources._request, when end is None and the series belongs to a projection family (catalog flag on WEO/GEP/IMF WEO vintages), default finish to today + 6 years or to the metadata horizon. Mention `end` in the skill and tool docs. (b) Add a deterministic, defensible status rule in data_sources: any observation whose period is not complete at retrieved_at (period end > retrieval date) cannot be observed, so classify it as 'projection' (publisher outlook). Keep other wb rows 'unknown' as the contract requires, but render them solid with an 'unverified status' note instead of a dotted line. Test with the captured real payload, not a synthetic fixture.

### L4 GAP (medium) — Legacy engine has no deterministic official-data prefetch; DATA_SOURCES_PREFETCH_MAX is unused there
- Location: backend/app/services/pipeline_orchestrator.py:1423 (forwarded); deerflow_bridge/linear_research.py:4356 (only consumer); deerflow_research.py main() around 17195-17400
- Evidence: grep shows DATA_SOURCES_PREFETCH_MAX is read only by v3. In legacy, official data enters only if the LLM chooses to call data tools, with a 4-call budget (L2) and bare tool schemas (L14).
- Impact: Legacy research and forecasts can complete with zero official series. This contradicts the requirement to adapt the deep-research workflow so it uses the data sources during the process.
- Fix: After _reset_fetched_sources and client registration, run a bounded prefetch. Pick catalog hits for the brief (data_catalog search on question terms or the market/KIQ terms already extracted), up to DATA_SOURCES_PREFETCH_MAX, and call get_many(deadline). Capture through data_tools._capture into the candidate journal without charging agent budgets. Inject an 'OFFICIAL DATA ALREADY RETRIEVED' block (render_series_brief plus provisional ids) into pass-0 and deep-phase prompts. Record meta.data_sources.prefetch. Test with a fake provider: the journal holds the prefetched rows, the prompt contains the block, and finalization charts them.

### L5 GAP (medium) — The core deep-research skill and several legacy prompts never mention the official-data tools
- Location: deerflow_bridge/skills/deep-research/SKILL.md:25-31 (core loop lists only web_search/web_fetch/prediction_market_search), 60-72 (forecast requirements), references/source-tradecraft.md:21 (Macro row), references/final-dossier-contract.md:38-51; deerflow_research.py:10697 (build_scoped_worker_prompt), 5315 (coverage top-up), 5355 (gap-closing)
- Evidence: grep finds no data_search/data_get/data-sources in deep-research SKILL.md or its references. _official_data_prompt_block() is injected only into build_research_prompt and build_deep_phase_prompt. The scoped-worker, top-up and gap-closing passes ask for exact numbers with units and as-of dates, which is precisely what data_get provides.
- Impact: The skill that every legacy pass and scoped worker activates ('/deep-research') steers agents to web pages for statistics. Official series are underused, and the final dossier contract never asks for an official-data baseline.
- Fix: Add to SKILL.md core loop step 2: 'For official statistics (macro, labor, prices, rates, fiscal, cross-country), call data_search then data_get; see data-sources'. Add 'official series baselines/projections' to the forecast requirements. Map the source-tradecraft Macro row to the providers. Add an 'Official data baseline' item to final-dossier-contract.md. Inject _official_data_prompt_block() into build_scoped_worker_prompt, build_coverage_topup_prompt and build_gap_closing_prompt. Keep the test_loop010 wording rules and add prompt-content regression tests.

### L11 BUG (medium) — Chinese legacy research gets English data charts and an English baseline heading
- Location: deerflow_bridge/deerflow_research.py:16764 and 18359 (pass args.target_language), 16301 and 16369 (str(lang).lower().startswith('zh')); backend/app/api/research.py:44 (_VALID_LANGUAGES = {'Chinese','English','auto'})
- Evidence: The orchestrator passes --target-language Chinese. 'chinese'.startswith('zh') is False, so render_data.py runs with --lang en and the heading '## Official Data Baseline' is used. v3 maps correctly (linear_research.py:5620: 'zh' if self.language == CHINESE).
- Impact: Chinese dossiers get English chart titles and captions and an English section heading, which conflicts with the bilingual product and the report translation integrity work.
- Fix: Normalize the language once: zh if the value lowercased is in {'zh','zh-cn','chinese','中文'} or starts with 'zh'. For 'auto', detect from the report's CJK ratio (as pipeline_orchestrator.py:12468 does). Use the normalized value for both calls. Test _prepare_legacy_data(lang='Chinese') to check for the zh heading and that --lang zh is passed.

### L7 BUG (medium) — Official Data Baseline table violates the status/period contract and is not localized
- Location: deerflow_bridge/deerflow_research.py:16369-16387 (_prepare_legacy_data)
- Evidence: Live output (scratchpad/review/live/legacy_finalize.log):
- FRED UNRATE shows 'Status not supplied' while the page says 'observed'.
- WEO CHN shows 'Latest stored value 4.41% | 2026-01-01 | unknown'.
- Periods are raw ISO start dates (annual '2026-01-01'), and usgov fiscal rows would show start dates, although data_sources._display_period (data_sources.py:324) produces 'FY2025'/'2026'.
- The projection test `flag in {'p',...} or projection_from <= date` lets projection_from override explicit unknown/preliminary flags, and maps raw 'p' to 'Publisher projection' (the contract says BLS P means preliminary).
- Header and status strings are English and use English titles even when title_zh exists.
- Impact: The deterministic baseline, which is the one official-data block guaranteed in the dossier, can present unknown or preliminary values as the latest fact, mislabel fiscal periods and contradict the chart and page.
- Fix: Build rows from data_sources helpers: use the observation kind (the same function as series_stats/_observation_kind), latest observed separately from the next publisher projection (two columns), and _display_period for the period. Use title_zh and localized headers/status when lang is zh. Add a 'Change vs year earlier' column from series_stats. Test with BLS 'preliminary', a WEO unknown row, a usgov fiscal row and zh.

### L8 BUG (medium) — Data360/WEO series titles lack geography, producing identical chart titles, annex headings and reference titles for different countries
- Location: deerflow_bridge/data_sources.py (wb title from Data360 metadata name); render_data.py _series_bundle/_manifest_title; deerflow_research.py embed_chart_refs
- Evidence: Live: wb:IMF_WEO_NGDP_RPCH/CHN and /USA both have the title 'Gross domestic product (GDP), Constant prices, Percent change' in the tool header, References entries ([S5]), the Visual Annex '### ...' heading and the PNG title. The footer credits 'World Bank Data360' for IMF WEO numbers. The catalog row title includes ': China'.
- Impact: Readers and the model cannot tell which economy a figure or citation refers to without decoding series ids, and the publisher of the projections (IMF) is misattributed.
- Fix: In the wb adapter, append the geography name (catalog title or metadata ref_country name) when the title lacks it, and keep authoring_entity (IMF) as the provider_name prefix ('IMF WEO via World Bank Data360'). The renderer should append geography from Series.geography when the title has none. Test that the two-country WEO titles differ.

### L12 BUG (medium) — data_tools holds its process lock and file lock across the provider call, serializing all official-data calls and failing cross-process callers after 5 s
- Location: deerflow_bridge/data_tools.py:83-100 (_admission), 274-330 (_run performs sources.search/get inside `with _admission(root)`)
- Evidence: Repro (scratchpad/review/live/lock_demo.py, fake 3 s provider, no network): 3 threads took 9.0 s total (3/6/9 s). A second process sharing the artifact directory got 'DATA_UNAVAILABLE: official-data tools busy; retry later' after 5.0 s while the first held the lock for 8 s. Real IMF calls take 30-50 s.
- Impact: Parallel KIQ workers and subagents block on each other for every data call, and separate processes receive spurious unavailability. Agents usually treat this as a gap and stop using data.
- Fix: Split _run into three steps: (1) under the lock, validate state, check the cache/journal and mark the request pending, charging the budget; (2) release the lock and call the provider (data_sources already singleflights by key); (3) re-acquire the lock to capture and mark ok/failed. Waiting identical requests should poll the pending entry. Test: 3 threads with a 3 s fake finish in about 3 s; a cross-process caller does not get 'busy'.

### L6 GAP (medium) — The series catalog reference is cut by read_file truncation, hiding the id-grammar sections
- Location: deerflow_bridge/skills/data-sources/references/series-catalog.md (67,515 chars, 366 lines; grammar sections at lines 327-366); deer-flow/config.yaml sandbox read_file_output_max_chars: 50000
- Evidence: Head-truncation at 50,000 chars ends around line 272, inside the wb section. The rest of wb, all usgov rows, and the 'BIS dataflows (ids are bis:<FLOW>/<KEY>)', 'IMF dataflows' and 'usgov recipes' sections are not shown on a plain read_file. SKILL.md gives neither line ranges nor these grammars.
- Impact: Agents cannot learn how to form BIS/IMF keys or usgov recipe ids, so they depend on data_search hits and waste the tight data budget.
- Fix: Move the three grammar sections to the top of the catalog (or into SKILL.md), split the per-provider tables into references/<provider>.md, and state the sizes and line ranges in SKILL.md. Add a test that every reference file is under 45,000 chars.

### L14 IMPROVEMENT (medium) — Legacy data tool schemas are bare, and empty optional args are rejected
- Location: deerflow_bridge/data_tools.py:369-380 (docstrings), 341 (provider ''), 355-357 (start/end '')
- Evidence: In the deer-flow venv, data_get_tool.args has untitled strings with no descriptions or enums, and the description is 'Retrieve and store an official series. Quote its exact values and provisional source reference.' The data_search description has no provider list. provider='' returns 'unknown provider' and start='' returns 'dates must use YYYY-MM-DD'.
- Impact: The model does not know the id grammar, providers, transform values ('yoy','pct'), that `end` is needed for projections, or partial-date formats, so the first calls often fail or are mis-specified.
- Fix: Use @tool(parse_docstring=True) with Google-style Args sections: series grammar examples per provider, provider enum, transform enum, end (use a future year for WEO/GEP projections), and accepted date forms (YYYY, YYYY-MM, YYYY-MM-DD). Normalize ''/'none' to None and lowercase the transform. Test the args schema contents and the empty-string handling.

### L15 IMPROVEMENT (medium) — Re-requesting a captured series with another window returns DATA_UNAVAILABLE instead of the stored evidence
- Location: deerflow_bridge/data_tools.py:296-299
- Evidence: Live: data_get('fred:UNRATE', start='2020-01-01') after a default fetch returned 'DATA_UNAVAILABLE: series already captured with a different window; use the original request'. The second agent cannot know the original request.
- Impact: Workers that independently need the same official series lose access to evidence that is already stored and free.
- Fix: Return _response(existing_row) with a one-line note on the stored coverage. This is free and keeps one generation per run. Optionally allow a strictly wider window as a new generation only when the old one has no in-text citations yet. Test that the second agent receives the stored page with the same provisional id.

### L16 BUG (medium) — Percent formatting loses policy-rate precision, and percent-unit changes are labelled as % instead of pp (data API, visible on legacy pages and table)
- Location: deerflow_bridge/data_sources.py:310-321 (format_value 2-decimal round), 346 (change line)
- Evidence: Live BIS US page:
- 'Latest: 3.88%' for 3.875 and 'Year earlier: 4.12%' for 4.125 (round-half-even), with history rows '3.62%' for 3.625.
- Summary line 'change -0.25% (-6.06%)'.
- UNRATE: 'change -0.2% (-4.55%)'.
The baseline table repeats 3.88%.
- Impact: Agents quote policy rates that were never set (3.62% or 3.88% instead of the 3.50-3.75 or 3.75-4.00 midpoint) and describe percentage-point moves as percent changes. Both errors matter for threshold forecasts.
- Fix: Keep up to 3-4 significant decimals, trimming zeros, so 3.875 stays 3.875. For changes in percent-unit series, emit 'pp' ('-0.25 pp'), and add a separate relative % only when meaningful. Coordinate with page-number verification in v3 (page_number_set). Test 3.875, 4.125 and 3.625 rendering and the pp label.

### L13 BUG (medium) — test_official_data_end_to_end hard-fails under plain pytest (same class as K1)
- Location: backend/tests/test_official_data_end_to_end.py:87 (assert os.environ.get('MAIN_OFFLINE_EVIDENCE')); also tests/test_v3_official_data.py:31 reads it
- Evidence: `cd backend && .venv/bin/python -m pytest -q tests/test_official_data_promotion.py tests/test_official_data_end_to_end.py tests/test_loop010_research_contracts.py tests/test_wave9_citations.py tests/test_loop010_global_synthesis.py` produced `FAILED tests/test_official_data_end_to_end.py::test_guarded_mcp_to_promoted_research_and_report_png` with `assert None`; all other tests passed.
- Impact: The CI/npm test path is red even after the K1 import fix.
- Fix: Replace the assert with pytest.skip('requires backend/scripts/main_offline_pytest.py guarded runner') when MAIN_OFFLINE_EVIDENCE is unset, or set a temporary evidence dir from tmp_path. Audit the other new tests for the same pattern.

### L9 IMPROVEMENT (medium) — Cross-economy comparison members also get single charts, so the chart cap drops other indicators
- Location: deerflow_bridge/skills/data-visuals/scripts/render_data.py:738-751 (_select), 1391-1418 (_compare_groups), main() 1858-1880
- Evidence: Live render (5 BIS policy rates, 2 WEO growth series, UNRATE, CPI yoy): it wrote 8 singles, including 5 near-duplicate per-country policy-rate charts, plus 2 compare charts. fred:CPIAUCSL#yoy was 'dropped (over the chart cap (--max 8))'. The bridge embeds all of them in the Visual Annex.
- Impact: Chart spam with low marginal information, while distinct forecast-relevant indicators are dropped.
- Fix: Compute compare groups before selection. A group consumes one slot, and its members are not charted individually unless they are KIQ-linked or cited in the prose. Then fill the remaining cap. Test that 5 BIS rates + CPI yoy + UNRATE gives 1 compare + 2 singles.

### L17 GAP (medium) — Legacy run telemetry does not record official-data usage or failures
- Location: deerflow_bridge/deerflow_research.py:17394 (meta['data_tool_registration']), 16360 (meta['data_sources'] only when rows exist); data_tools.py state file not surfaced
- Evidence: meta gets only the registration status and, if datasets exist, {series_count,status:'stored'}. There are no provider readiness, call/failure/budget-exhausted counts or busy errors, and no degradation event when data was enabled but nothing was captured. v3 records meta.data_sources.providers, data_stats and a degradation event (linear_research.py:4105, 6363, 6410).
- Impact: Operators cannot tell whether legacy agents ever tried the data tools, hit the 4-call cap, or saw provider failures, which blocks tuning L2/L4 and diagnosing outages.
- Fix: At the end of the run, read data_tool_state.json and the journal and write meta.data_sources {enabled, providers (DataSources.providers()), calls, by_agent, failed, budget_exhausted, busy, captured, finalized}. Append a _RESEARCH_FLAGS degradation event when data was enabled and zero series were finalized. Test with a fake provider.

### L18 IMPROVEMENT (low) — Research data charts lack forecast-useful chart types, localized labels, data-driven captions and placement at the point of use
- Location: deerflow_bridge/skills/data-visuals/scripts/render_data.py (_caption 1660-1700, _series_bundle/_compare_bundle, _status_segments); deerflow_research.py:16388-16392 (embed into Visual Annex only)
- Evidence: Live PNGs in scratchpad/review/live/run_en|run_zh|run2/charts:
- Captions are boilerplate ('Official series from FRED; latest observation marked.').
- In zh charts the y-axis units ('Per cent per year', 'Percentage change') and the provider names are untranslated.
- EN WEO compare labels are ISO3 codes (CHN/USA).
- The BIS title repeats 'Monthly' in the title and subtitle.
- The mts_deficit monthly chart is unreadable seasonal noise.
- There is no cross-section latest-value bar/dot chart, indexed (=100) growth overlay, rolling-12m sum/average or derived YoY for index levels, although chart-patterns.md describes them.
- Legacy appends data figures after References instead of beside the relevant section (v3 inserts '### Figure:' in sections).
- Impact: The visuals are accurate but convey little argument, and zh readers see mixed-language charts.
- Fix: Add digit-free, data-driven takeaways from stored observations ('rising over the past year', 'highest since <period words>'). Localize unit and provider strings for zh. Use geography names for labels. Add bar/dot cross-section, indexed-growth and rolling-12m variants, with deterministic derivations labelled 'computed from stored observations'. In legacy, insert figures under the section whose text cites the series' S#, falling back to the annex. Test each variant and zh text with golden manifest rows.

### L19 IMPROVEMENT (low) — Artifact bloat from inline plotly HTML twins and full snapshots in sources.json
- Location: render_data.py:1617-1641 (_write_html include_plotlyjs=True); deerflow_research.py _copy_official_source_fields; data_sources write_dataset_files (provenance)
- Evidence: Each charts/data_*.html is about 4.86 MB, so 10 data charts total 47 MB (du). Each dataset row in sources.json is 15-23 KB (full page plus a snapshot including Data360 metadata with a 200-country ref_country list). datasets.json is 77 KB for 9 series.
- Impact: Larger research contracts, slower promotion and hashing, bigger demo exports, and bigger sources.json consumed by downstream prompts and the UI.
- Fix: Write one shared charts/plotly.min.js (include_plotlyjs='directory') or make HTML twins opt-in for data charts. Trim provenance.metadata to the needed fields (drop ref_country and long definitions). Keep the snapshot hash and point to the series file instead of duplicating it in sources.json, adjusting validated_source accordingly.

### L20 GAP (low) — Dataset sources can fall outside the 100-entry synthesis SOURCE INDEX and lose their citations
- Location: deerflow_bridge/deerflow_research.py:~2015-2021 (_merge_shared_fetched_sources appends newly merged data rows after web rows), 4729-4735 (RESEARCH_CITATION_INDEX_MAX=100), 6998-7000 (pinned index), 4929-4930 (remap to '' when absent)
- Evidence: Code path (not live-run): data rows not previously in _FETCHED_SOURCES sort after the current web rows. With more than 100 fetched pages before a dataset is merged, build_citation_index excludes it, and _remap_data_citations(report, data_rows, _PINNED_CITATION_INDEX) maps its provisional id to ''.
- Impact: In long deep runs, official-data claims written in synthesis lose their [S#] and the synthesis never sees datasets in its routed index.
- Fix: Always pin all validated official rows into the citation index, outside the cap or reserving slots, and route them to sections by series terms. Test with 120 web rows plus 2 datasets: both datasets are pinned.

### L21 GAP (low) — Visual contract counts any data_* chart as satisfying both quant_metrics and metric_trajectories
- Location: deerflow_bridge/deerflow_research.py:16094-16118 (satisfied = ids | {'quant_metrics','metric_trajectories'} if data_ids)
- Evidence: One unrelated US unemployment chart satisfies a 'regional comparison' (quant_metrics) requirement and a 'cost curve/deployment trajectory' (metric_trajectories) requirement.
- Impact: The visualization contract can pass without the requested comparison or trajectory being shown.
- Fix: Map data charts by kind. A data_compare_* chart satisfies quant_metrics/regional. A single series with at least 8 points in the brief's metric family satisfies metric_trajectories. Test both cases.

### L22 GAP (low) — No dataset panel, series list or CSV download in the research UI or the demo export
- Location: frontend/src/components/research/DossierViewer.vue:458-470 (markdown-only rendering); frontend/src/utils/vizManifest.js (only two caption translations added); backend/scripts/export_demo_site_data.py (charts only)
- Evidence: grep finds no dataset/official handling in frontend/src beyond vizManifest captions. The data/datasets.json artifact is registered ('datasets'), but nothing renders it, and the CSVs are never linked.
- Impact: Users cannot inspect or download the official series that underpin the forecast. Quantitative grounding is visible only as static PNGs and one table.
- Fix: Add an 'Official data' tab to DossierViewer. Read the datasets artifact and show series, provider, units, latest observed, the next projection, an S# link and a CSV download through new chart_/data_ artifact routes. Have the demo exporter copy datasets.json and the CSVs. Add a component test with a fixture manifest.

### L23 GAP (low) — Deployed runtime is stale until the next launch, and the deployed config.yaml never gains the data tool entries
- Location: deer-flow/ (gitignored): no data_*.py, no skills/public/data-*; deer-flow/config.yaml tools/loop_detection/scoped-researcher; setup.sh:713-716 (never updates an existing config); scripts/doctor.sh
- Evidence: `ls deer-flow` shows deerflow_research.py from Sep 28 and no data modules or data skills. A dry run of runtime_skill_sync into scratch deployed data-sources and data-visuals (including scripts/render_data.py, with logs/ excluded). data_tools imports in the deer-flow venv (StructuredTool data_search/data_get). The deployed config lacks data_search/data_get and the scoped-researcher whitelist; it relies on in-memory _register_legacy_data_tools. doctor.sh does not report this.
- Impact: Behaviour depends on the launch-time sync and runtime registration. Any manual deer-flow run, or a registration failure (meta.data_tool_registration 'unavailable'), silently removes the data tools.
- Fix: Have doctor.sh check deployed parity (data modules, skills, and whether the deployed config contains data_search/data_get) and print the exact remediation. Optionally add a setup.sh '--merge-config' step that idempotently inserts the tool and subagent entries. Surface meta.data_tool_registration in the pipeline UI when it is not ready.


#### Phase coverage
LEGACY ENGINE PHASES, and whether official data is used there today (code read plus live/scratch repros):
1. Brief/KIQ planning before pass 0: NO. There is no deterministic prefetch, no catalog digest and no data_needs. DATA_SOURCES_PREFETCH_MAX is forwarded by pipeline_orchestrator.py:1423, but only linear_research.py:4356 reads it. (GAP L4)
2. Pass 0 / single-pass / evidence-only prompts (build_research_prompt, deerflow_research.py:5088-5175): YES. _official_data_prompt_block() names the tools and the skill path, but gives no id grammar and no hint about the projection window.
3. Deep phase prompts (build_deep_phase_prompt:5209): YES, same block.
4. Coverage top-up (5315) and gap-closing (5355) passes: NO. These passes explicitly hunt "a specific number with its as-of date and unit". (GAP L5)
5. KIQ fan-out scoped workers (build_scoped_worker_prompt:10697): NO prompt guidance. The tools are present.
6. scoped-researcher `task` subagents: YES. Runtime in-memory registration adds the tools, the data-sources skill and a system-prompt marker. The data budget is shared with the parent thread_id: 4 calls including searches. (L2)
7. deep-research SKILL.md core loop and source-tradecraft (the skill activated for every pass and worker): NO mention of data_search/data_get. (GAP L5)
8. data-sources skill: present. The catalog reference is truncated by read_file at 50k chars, which hides the wb/usgov rows and the BIS/IMF/usgov id grammar. (L6)
9. Tool calls (data_tools.py): bounded and persisted. 77-digit provisional citations (L1). The admission lock is held across provider calls (L12). Window lock (L15). Bare schemas (L14).
10. Synthesis SOURCE INDEX: PARTIAL. Dataset rows are included only within the 100-entry cap (L20). There is no "official data captured" digest block for synthesis (v3 has one).
11. finalize_report_citations: YES. It remaps provisional ids by URL; mis-copied ids are stripped.
12. Report judge/refine/triangulation top-up: NO data awareness.
13. Structured extraction (quantitative.json/actors/timeline): NO deterministic promotion of stored observations. It relies on the LLM re-extracting from prose.
14. Stage 3 prediction markets: N/A.
15. Stage 4 (_prepare_legacy_data, deerflow_research.py:16356): YES. It finalizes datasets, adds an Official Data Baseline table and runs render_data.py, with data_* figures embedded in a Visual Annex after References. Bugs: L7 table, L8 titles, L11 zh, L3 projections.
16. forecast-visuals render.py: preserves data_* rows (verified). The visual audit counts data charts (L21).
17. Actor-intelligence sealing: YES. Dataset rows are admitted with Track-B receipt scopes removed.
18. Evidence-only lanes: YES (_finalize_data_series).
19. Legacy global synthesis + promotion: BROKEN. Transported rows reference lane-local data/candidates files, and promotion raises FileNotFoundError. (L10)
20. Extract-only salvage: YES (_prepare_legacy_data).
21. Research contract promotion/hashing of data/: YES for single-dir runs (verified on a real-data scratch run).
22. Meta/telemetry: MINIMAL. Only data_tool_registration and series_count/status are recorded: no provider status, call counts or degradation event. (L17)
23. Deployment: modules and skills are synced at the next launch (verified by a dry run of runtime_skill_sync). The deployed config.yaml is never updated; tools are registered in-memory. The deployed deer-flow/ is currently stale. (L23)
24. Frontend DossierViewer: figures and the table render through markdown (charts/*.png|html resolve). There is no dataset panel or CSV download. (L22)
25. Demo exporter: copies the data charts; datasets are not exported.


## review:v3: v3 deep-research engine, every phase (deerflow_bridge/linear_research.py, deerflow_bridge/research_gateway.py), plus the shared data_sources/data_cata

### V3-01 BUG (high) — Need-to-series resolution picks the wrong country when the geography is an ISO3 code — the format the catalog digest itself prints
- Location: deerflow_bridge/linear_research.py:4366-4380 (query = need.query + need.geography; the top hit is taken with `matches.split(' — ',1)[0]` and no geography or score check); deerflow_bridge/data_catalog.py:145-164 (GEOGRAPHIES aliases include 'usa' but not chn/jpn/emu/deu/gbr/ind/...); data_catalog.py `_digest_line` prints geography as ISO3
- Evidence: search_catalog('policy rate CHN') returns bis:WS_CBPOL/M.US first. 'inflation JPN' returns fred:CPIAUCSL (US CPI). 'unemployment rate EMU' returns fred:UNRATE. 'GDP growth DEU' returns imf:WEO/G163 (euro area). With country names ('policy rate China', 'inflation Japan') the correct series ranks first. The planner digest shows geography as '(..., M, CHN)', so the planner is likely to emit ISO3 codes.
- Impact: A China, Japan or euro-area KIQ is seeded with US data under 'OFFICIAL DATA ALREADY RETRIEVED'. `_finish_kiq` then adds a deterministic VERIFIED fact from it, and the digest and baseline table publish it. The number verifier cannot catch this, because the value really is on the cited page.
- Fix: Map ISO3 codes and EA/EU/US/UK to country names via GEOGRAPHIES before searching (or make `_parse_query` recognise ISO3). In phase_data, reject a hit whose catalog geography differs from the need's geography (allow WLD only for global needs), require a concept score of at least `_PRIORITY_MIN_CONCEPT` for query-resolved needs, and try the 2nd and 3rd hits before giving up. Tests: {query:'policy rate', geography:'CHN'} resolves to bis:WS_CBPOL/M.CN; {query:'inflation', geography:'JPN'} never resolves to a US series.

### V3-02 BUG (high) — Official evidence loses its country: digest lines, KIQ facts, baseline table and References omit it for World Bank/Data360 and IMF CPI series
- Location: linear_research.py:4453-4462 (`_data_summary` uses series.title), 4836-4846, 5098-5100, 5650-5661; research_gateway.py:3761 (register_dataset uses series.title as the ledger/References title); root cause data_sources.py:1688 (the Data360 indicator_name overrides the curated catalog title, which includes the country)
- Evidence: Probe scratchpad/review/probe/url_collision.py on real cached wb:IMF_WEO_NGDP_RPCH/USA, /DEU and /CHN produced three digest lines with the identical title 'Gross domestic product (GDP), Constant prices, Percent change' and different values (2.32%, 0.79%, 4.41%), and three References with identical titles. In the live sweep cache, 24/24 wb series and the imf:CPI rows have provider titles without a country; the catalog titles do include it ('...: China').
- Impact: For cross-country questions writers receive indistinguishable numbers, so misattributed growth or inflation figures are likely and cannot be detected.
- Fix: Build a display label (title + ' — ' + geography name) whenever the title lacks the country, and use it in `_data_summary`, the baseline table and the register_dataset title. Better still, have `DataSources._base` keep the curated catalog title or append the geography. Test: three same-indicator WB fixtures yield three distinct lines and references.

### V3-03 BUG (high) — QA check `data_numbers_consistent` rejects correct statements, including the engine's own baseline table rows
- Location: linear_research.py:5727-5734 (`_data_signed_values`), 5736-5763 (`_data_checks`), 5566-5574 (data checks run after `_repairs`, so there is no repair)
- Evidence: Probes check_numbers.py, debug_numbers.py and self_table.py, on real cached series through the real ResearchTools/SourceLedger. 'US unemployment was 4.2% in September 2026 [S1]' fails because ('+','=2026') is missing: strip_dates=True removes every date from the page but keeps a bare year in the prose. 'US unemployment was 4.2% [S1]' passes. 11 of 12 sentences that quote the displayed value exactly fail. The engine's own table row '| Gross Domestic Product | 32563.03 Billions of Dollars | ... [S2] |' fails its own check: the scale word turns the value into 32563030000000, while the page writes 32563.03. The same happens for GDP, GDPC1, PAYEMS, RSAFS, M2SL, WALCL and HOUST (6 of 7 scaled-unit rows). The KIQ verifier (postprocess_notes) marks the same sentences VERIFIED.
- Impact: meta.research_qa.passed is false on essentially every run that uses official data, since ENGINE_CORE requires 'number, unit, as-of date or period'. The check therefore cannot signal real errors, and nothing repairs them. This is the user-requested test 'quoting a value as displayed verifies', and it fails.
- Fix: Compute the page's signed values without date stripping (or strip consistently and ignore 4-digit years from 1900-2100 in the prose). Ignore scale words that belong to the series' units label, or compare against page values scaled by the unit. Exempt the deterministic baseline rows or generate them in a form that passes. Add a bounded rewrite of failing lines before sealing. Tests: the 12 exact-quote sentences pass, the rounded ones fail, and `_embed_data_exhibits` output passes `_data_checks`.

### V3-04 BUG (high) — One malformed or transiently failed data call blocks that series or query for the whole run; empty optional strings always fail
- Location: research_gateway.py:3607-3614 (search key 'search:'+(provider or '') treats '' and None as the same key, and provider '' is passed through); data_sources.py:999-1003 (provider '' selects an empty set and returns []); research_gateway.py:3616-3647 (start/end '' are passed through; the cache key 'get:'+identity ignores the window); 3704-3747 (`_data_call` caches every outcome, including DataError, ProviderCallTimeout and 429); data_sources.py:1087-1089 (end='2026' becomes 2026-01-01)
- Evidence: `data_search('US unemployment rate', provider='')` returns NO_DATA_MATCH. A later search for the same query by another agent, with no provider, returns the cached NO_DATA_MATCH; a fresh run returns fred:UNRATE. `data_get('fred:UNRATE', start='', end='')` produces DataError('Unrecognized observation period'), shown as 'provider returned no usable dataset.'. A later valid `data_get('fred:UNRATE')` by K2 gets the same cached failure. `_request(start='2020-01', end='2031')` maps end to 2031-01-01, so a monthly series loses Feb-Dec of the end year. The schema's transform enum includes '', which encourages models to send empty strings.
- Impact: One sloppy optional argument (common in tool calls) or one 429 or timeout removes a headline series from every agent for the rest of the run.
- Fix: Normalise ''/whitespace to None for provider, start, end and transform (DataSources.search should treat '' as all providers). Validate provider against PROVIDERS and list the valid ids in the error. Cache only successes and deterministic invalid-input errors, keyed by the full argument tuple, and never cache retryable failures. Map a bare-year end to the year's last day. Tests: both sequences above succeed on the second call, and end='2026' keeps 2026-09.

### V3-05 BUG (high) — `_data_value_status` ignores the normalized flag vocabulary: every BIS value is labelled 'publisher-flagged value: observed' and demoted to REPORTED
- Location: linear_research.py:4439-4451, used at 4453-4462, 4841-4844, 5098-5100, 5659, 6110
- Evidence: Contract flags are observed/unknown/preliminary/estimate/projection, and Series.__post_init__ maps BIS 'A' to 'observed'. All 31 BIS series in the sweep cache are flagged 'observed'. Probe flags.py on bis:WS_CBPOL/M.CH gives '0% Per cent per year (2026-09-01; publisher-flagged value: observed)' with projected=True; notes_verify.py shows the deterministic BIS fact tagged REPORTED. WB and WEO values show as 'publisher-flagged value: unknown'.
- Impact: All BIS facts (policy rates, credit gaps, debt-service ratios, property prices) lose VERIFIED status. The digest, baseline table and sources excerpt carry a meaningless label, and grounding signals undercount official evidence.
- Fix: Use data_sources._observation_kind (or a public wrapper): observed maps to ('stored observation', False), and preliminary, estimate, projection and unknown get proper labels with True. Test with a real BIS fixture (expect VERIFIED) and a WB fixture (expect a 'status unknown' label).

### V3-06 GAP (high) — IMF WEO and WB GEP projection paths never reach the forecast horizon: prefetch and data_get windows end today
- Location: data_sources.py:1087-1089 (finish = today when end is None) and 1324 (later observations dropped); linear_research.py:4381 and research_gateway.py:3683 (no end is passed); KIQ trailer 4927-4929 and the data_needs schema 4600 have no end or window field
- Evidence: In the sweep cache, all 20 WEO/GEP series end at 2026-01-01 with requested_end 2026-10-11; wb:WB_GEP_NYGDPMKTPKDZ/USA has only 5 observations (2022-2026). A live `get('imf:WEO/USA.NGDP_RPCH.A', end='2031-12-31')` returned rows to 2031 in 34 s (status 'unknown'), so the fix is feasible.
- Impact: The most forecast-relevant official asset, the publisher projection path to 2030/31, is dropped from every v3 run. The projection segment and label machinery downstream never receives WEO/GEP projections.
- Fix: Pass end = min(plan horizon year-end, today + 6 years) for projection families (imf:WEO*, wb:IMF_WEO_*, wb:WB_GEP_*), or default `end` for them in DataSources._request. Add an optional end to data_needs and tell agents about it. Test: a WEO fixture with rows to 2031 keeps 2027-2031 as projection or unknown and shows them separately in the baseline table.

### V3-07 GAP (high) — Every resumed attempt permanently skips official-data acquisition, even if the crash happened before the data phase ran
- Location: linear_research.py:4084-4100 (resumed: freeze_data, status 'stored_only', return), 4345-4349 (phase_data: `if self.resumed ...: set_phase('data','done','skipped_resume')`), 979-995 (resumed is true for any retry with the same identity)
- Evidence: From the code path. If index.json was never written (crash during plan or during the IMF-bound data phase), data_enabled is False, so agents get the web-only schema and no data. If it was written, resumed agents are shown the data tools, but every new data_get answers 'DATA_UNAVAILABLE: providers disabled or evidence frozen'.
- Impact: Resumes are routine in this pipeline (watchdog, SIGTERM, provider outages), and official data silently disappears from the resumed report while agents waste steps on frozen tools.
- Fix: Freeze only evidence that is already pinned. Run phase_data on resume when gather has not started. While gather is partial, allow new data_get calls for unfinished KIQs (new sids) and freeze at synthesize as today. Keep `_check_data_reuse` for sealed artifacts. Tests: a resume after a plan crash fetches data; a mid-gather resume lets an unfinished KIQ fetch a new series.

### V3-08 GAP (high) — Official series never reach forecast_inputs (indicators/base_rates) or quantitative.json deterministically
- Location: linear_research.py:6293-6296 (`forecast_inputs()` returns base_rates [], drivers [], indicators []), 6241-6243 and 6595-6622 (quantitative rows come only from LLM extraction of report prose), 476-487 (`_T_FACTS` has a free-text series field)
- Evidence: backend/app/services/report_agent.py:3401 and 5057 read `extract_forecast_inputs(actors)['indicators']` into forecast.json and the 'Indicators to Watch' block (forecast_extractor.py:3802-3817). The research charts quant_metrics and metric_trajectories read quantitative.json. For v3 runs the indicators are always empty, and official values reach quantitative.json only if the LLM copies them, without series id, status or dataset link.
- Impact: The quantitative backbone the user asked for does not flow into the structured forecast inputs, the indicator and resolution tables, or the quantitative charts.
- Fix: In `_write_structured`, add one deterministic quantitative row per stored dataset: metric, canonical series id, latest historical value, unit, as_of_date, value_type taken from the status, geography, provider, source_url, positional source_ref, source_origin 'official_data' and dataset file, plus projection-year rows when present. Populate forecast_inputs.indicators with {indicator, series, latest_value, latest_date, units, frequency, date_or_trigger: next expected release, source_ref}. Optionally flag LLM quant rows that cite a dataset S# with a different value. Test: two stored datasets produce two quant rows and two indicators.

### V3-09 BUG (high) — test_official_data_end_to_end fails outright under plain pytest (the CI path)
- Location: backend/tests/test_official_data_end_to_end.py:87 (`assert os.environ.get('MAIN_OFFLINE_EVIDENCE')`), :95-96 (`from deerflow_bridge import ...`, the K1 import pattern)
- Evidence: `cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider` over the 15 v3 and official-data files gives 1 failure, this test; all others pass (scratchpad/review/v3run/plain.txt). Under the Codex runner with the documented allowlist it passes (runner2.txt: 29 passed).
- Impact: The npm/CI test run stays red even after K1 is fixed.
- Fix: Call pytest.skip (or use a marker that skips unless MAIN_OFFLINE_EVIDENCE is set) instead of asserting, and import the bridge through sys.path like the other bridge tests.

### V3-10 GAP (medium) — Prefetch depends entirely on the planner volunteering data_needs; there is no catalog fallback
- Location: linear_research.py:409-421 (the `_T_PLAN` JSON shape has no data_needs), 4599-4605 (a single trailing sentence), 1157-1166 (`fallback_kiqs` sets no data_needs), 4362-4380
- Evidence: From the code path. Deterministic fallback plans (outage or unusable plan), and plans that copy the printed JSON shape, carry zero data_needs. phase_data then ends 'no_needs_or_unavailable' without a single provider call, even though catalog_digest(question) has already ranked relevant series.
- Impact: The data phase often does nothing, and official data appears only if agents choose to call the tools.
- Fix: When data is enabled, add data_needs to the shape inside the last message. When no KIQ has needs, or the plan is a fallback, derive needs from search_catalog(kiq.question + question) hits with score at least `_PRIORITY_MIN_CONCEPT` (top 1-2 per data-kind KIQ, cap 6), using the corrected geography handling from V3-01. Test: the fallback plan for 'US inflation outlook 2027' prefetches CPIAUCSL and PCEPILFE.

### V3-11 BUG (medium) — Agent notes can tag projection or unknown-status official values as VERIFIED
- Location: linear_research.py:4830-4846 (`_finish_kiq`: the generic postprocess_notes verifier checks numbers only; status is applied only to the deterministic summary fact)
- Evidence: Probe notes_verify.py on real wb:IMF_WEO_NGDP_RPCH/DEU, where every row is 'unknown' and 2026 is a WEO projection: 'Germany real GDP growth per IMF WEO is 0.79% for 2026 [S4] (VERIFIED)' stays VERIFIED.
- Impact: This violates the contract that projections and estimates are never promoted to VERIFIED observations. Writers then state IMF projections as plain fact.
- Fix: After postprocessing, downgrade to REPORTED any VERIFIED fact whose sids are all dataset sids, unless every matched number belongs to an observation whose kind is 'observed'. Test with the WEO fixture (expect REPORTED) and a FRED observed fact (stays VERIFIED).

### V3-12 BUG (medium) — A dataset persistence failure leaves an orphan dataset ledger row that breaks every later resume; the error leaks 'StopIteration'; a symlinked ancestor directory always fails
- Location: research_gateway.py:3750-3775 (register_dataset at 3761 runs before write_dataset_files at 3766; `next(...)` at 3768 raises StopIteration on the error manifest), 3557-3588 (restore_data marks such rows invalid); linear_research.py:4127-4132; data_sources.py:374-382 (`_safe_path` rejects any symlinked ancestor)
- Evidence: Probe orphan.py with out_dir under a symlinked directory. Attempt 1: data_get returns 'DATA_UNAVAILABLE: StopIteration; use another source.' and the ledger keeps dataset row 1 with fetched=False. Attempt 2: restore_data gives invalid_data_sids()=={1}, so `_check_data_reuse` raises official_data_evidence_corrupt on any resume after gather.
- Impact: One transient write failure (disk full, permissions, a symlinked uploads volume, macOS /tmp or /var) makes the run unresumable. On hosts whose output path has a symlinked ancestor, no dataset can be stored at all.
- Fix: Persist first and register second, or roll back the ledger row on failure. Check manifest.get('error') and return a clear DATA_UNAVAILABLE message. Make restore_data ignore dataset rows that were never fetched. Resolve the output root before the symlink-ancestor check, so only symlinks inside out_dir are rejected. Tests: a forced write failure leaves no invalid sid; a symlinked parent still stores data.

### V3-13 BUG (medium) — web_fetch of a shared origin URL silently returns another series' dataset page
- Location: research_gateway.py:3945-3954 (`fetch` returns the first dataset row whose canonical URL or source_url matches); shared origins at data_sources.py:1598 (one IMF URL per dataflow), 1689 (one Data360 URL per indicator, no country), FRED base plus #yoy/#pct variants, usgov recipes
- Evidence: Probe url_collision.py: after storing WB NGDP_RPCH for USA, DEU and CHN, `fetch('https://data360.worldbank.org/en/indicator/IMF_WEO_NGDP_RPCH', focus='China GDP growth')` returns the USA page ([S1], 'Geography: USA'). Fetching the IMF WEO landing page, which also appears in normal web search results, returns the World series.
- Impact: An agent researching China receives, and may cite, US data, and the real web pages at those URLs become unreachable.
- Fix: Map only exact dataset identity URLs to dataset pages. For a bare source_url shared by more than one stored series, return a disambiguation list of series ids or fall through to a real fetch. Test: two series sharing a source_url, and fetch(source_url) does not silently return either page.

### V3-14 GAP (medium) — The data phase runs serially on the critical path, its window cannot fit IMF fetches, and provider work is not bound to caller deadlines
- Location: linear_research.py:4352-4381 (window = min(150 s, 8% time share); per-need data_search calls run one after another before prefetch); data_sources.py:880 (IMF/BLS semaphores = 1), 994-1064 (search never sets `_local.deadline`; only the hub's per-call timeout applies: 60 s default, higher for IMF), 1147-1188 (`get` takes no deadline; an agent data_get waits on locks and semaphores without a timeout and keeps the provider slot after `_call_within` gives up at ≤90 s)
- Evidence: Live probe (scratchpad/review/live/timing.txt, fresh cache): a 7-series prefetch with an 88 s window took the full 88.0 s and lost imf:PCPS/G001.PCOPP.USD.M ('Data request deadline exceeded') because it queued behind imf:WEO on the single IMF slot. wb:IMF_WEO_NGDP_RPCH/USA failed with the known K2 error. A single IMF WEO get took 34 s.
- Impact: Up to 150 s of pure waiting before any KIQ starts. A second IMF series is routinely lost in quick runs. A stalled agent call blocks other agents' IMF/BLS access, and its later success stays cached as a failure.
- Fix: Start prefetch_data in the background at the end of planning and run `_run_seeds` concurrently, joining before agents launch. Prefer the faster wb:IMF_WEO_* equivalents once K2 is fixed. Add a deadline_s to DataSources.get and search that sets `_local.deadline`. Do not cache a ProviderCallTimeout. Tests: a fake 40 s IMF provider with 2 IMF ids completes within 150 s; get with a deadline releases the semaphore.

### V3-15 GAP (medium) — Prefetch can use up the whole fixed 12-dataset run cap, locking agents out of official data
- Location: research_gateway.py:3641-3642, 3672, 3755 (hard-coded 12); linear_research.py:4356 (DATA_SOURCES_PREFETCH_MAX defaults to 12); the per-preset call budgets at 4027 never raise the dataset cap
- Evidence: Probe cap.py: 12 series prefetched, all stored; agent K3's data_get of a 13th series returns 'DATA_BUDGET_EXHAUSTED: run dataset limit reached.'
- Impact: With 7-10 KIQs × up to 3 needs, the cap fills routinely. Gap follow-ups and data-kind agents cannot add series, and deep runs get the same 12 as quick runs.
- Fix: Move the dataset cap into ToolLimits and scale it by preset (e.g. 10/16/24). Clamp prefetch to about 60% of the cap. Test: a full prefetch leaves slots for agents.

### V3-16 GAP (medium) — The gap phase cannot see data coverage, and follow-ups cannot request data
- Location: linear_research.py:5069-5084 (`_coverage_matrix` has no data dimension), 441-450 (`_T_GAP` has no data_needs), 5056-5060 (follow-up Kiq built without data_needs), 4925-4933 (the data block appears only for data_index[kiq.id], which is empty for every G*F* follow-up), 4981-4983 (capacity ignores the data budget)
- Evidence: From the code path. The coverage line holds only facts, verified count, sources, open questions and leads.
- Impact: Missing base rates or indicators are never routed to the data tools, and follow-up agents search the web again for numbers already stored in the run.
- Fix: Add a per-KIQ line 'data: n stored [ids] / k failed' and a run-level stored-series list to the coverage matrix. Accept optional data_needs on follow-ups and prefetch them (bounded) before gather_kiqs. Show all stored series briefs to follow-up agents, since cached data_get calls are free. Tests: the coverage text includes the data line, and a follow-up's data_needs are prefetched and seeded.

### V3-17 GAP (medium) — Synthesis, executive summary and critique get no structure or instruction for using official data
- Location: linear_research.py:5098-5100 (the digest gets a bare list: latest value and year-earlier only, with no trajectory, 5-year range or projection path), 534-547 (`_SECTION_RULES` says nothing about official data), 5434-5449 (exec summary sees only section leads), 457-461 (`_T_CRITIQUE`), 5684-5685 (the baseline section is appended after all analysis)
- Evidence: From the code path. The writer prompt has no official-data rule, and the exec summary context never contains official numbers.
- Impact: Official series are treated as ordinary bullets. Base rates and trends are not anchored on the stored history, the summary's key numbers rarely use the official baseline, and the critique cannot flag contradictions with stored data.
- Fix: Label the digest block 'OFFICIAL DATA (stored series; cite exactly)' and give each series a compact trajectory (last 5-10 periods, 5-year range, latest historical value versus the publisher projection path). Add a static `_SECTION_RULES` bullet: anchor current-state, base-rate and trend claims on these series and label projections as the publisher's. Pass official headline lines to `_exec_summary`. Add 'contradicts stored official data' to the critique. Place the baseline after the current-state section. Static rules and last-message text keep the prompt-cache layout intact.

### V3-18 IMPROVEMENT (medium) — Provider failure reasons are discarded; telemetry cannot explain missing data; partial failure and 'enabled but unused' raise no quality event
- Location: research_gateway.py:3736-3739 (any DataError becomes 'provider returned no usable dataset.'), 3688-3698 (every prefetch failure becomes '...within the data deadline.'), 3590-3594 (data_stats records counts only); linear_research.py:6362-6363
- Evidence: Probe: DataError('HTTP 429 rate limited; retry after 60s') reaches the agent as 'provider returned no usable dataset.'. A Data360 validation failure in prefetch is reported as a deadline failure, which is the wrong cause.
- Impact: Agents cannot adapt (retry later, choose another id, or use data_search), and operators cannot see live failures like K2 per run. Runs where official data was enabled but never used, or mostly failed, look healthy.
- Fix: Surface the already-redacted DataError.message (≤300 chars) and its retryable flag in the tool output. Record meta.data_sources.failures as [{series, reason, retryable, by}] plus requested/stored counts per KIQ. Add research events 'official data enabled but unused' and 'k of n requested series unavailable' when k/n ≥ 0.5. Test: a fake reason appears in both the tool output and meta.

### V3-19 IMPROVEMENT (medium) — Agents get little guidance on when and how to use official data
- Location: linear_research.py:231-297 (ENGINE_CORE never mentions official series or data tools, and its VERIFIED rule says 'a page you fetched'); research_gateway.py:3377-3387 (data tool schemas lack parameter descriptions, a provider enum and id/date formats); linear_research.py:4925-4933 (no catalog hints in the KIQ task); 3817-3818 and 3835-3836 (error texts still say only web_search/web_fetch exist)
- Evidence: From the code. 3 of the 6 default KIQs are data-kind (baseline, leading indicators, base rates), yet an agent must spend a data_search call before it knows any id. Agents shown seeded official values tend to tag them REPORTED because nothing says the stored values count as fetched evidence.
- Impact: Fewer and later official series per KIQ, data calls wasted on discovery and invalid providers, and verifiable official facts left as REPORTED.
- Fix: Add a static ENGINE_CORE paragraph on official series: quote value, unit, period and geography exactly; values from data_get or the 'already retrieved' block count as fetched; never present projections as observed. Give the schemas descriptions, a provider enum and id/date examples. Append the top-5 search_catalog(kiq.question) ids to data-kind KIQ tasks in the last message. Update the stale error texts. These changes keep the prompt-cache layout intact.

### V3-20 IMPROVEMENT (medium) — v3 tests use synthetic fixtures that hide the real-payload defects
- Location: backend/tests/test_v3_official_data.py:87-126 (one FRED-shaped 'Percent' series with flags '' or 'projection' and a title without a country), 267-300 (the QA check is exercised only with bare numbers and no periods)
- Evidence: V3-02, V3-03, V3-05 and V3-06 all pass the current suite (29/29 green through the runner, scratchpad/review/v3run/runner2.txt).
- Impact: These defects will come back unnoticed after any fix.
- Fix: Add real normalized series captured from the live sweep (fred:GDP, fred:UNRATE, bis:WS_CBPOL/M.US, wb:IMF_WEO_NGDP_RPCH/{USA,CHN}, imf:WEO/G001.NGDP_RPCH.A, usgov:treasury/mts_deficit) as fixtures. Drive `_finish_kiq`, `_embed_data_exhibits`, `_data_checks` and `_source_rows` with them, using sentences in the ENGINE_CORE value + unit + period form.

### V3-21 GAP (low) — Chinese runs get English official-data exhibits, and the curated Chinese titles are never used
- Location: linear_research.py:5650-5661 (English table header, status labels and series.title), 5672-5673 (literal '### Figure:' and an English default caption), 4453-4462; no use of title_zh anywhere in linear_research.py or research_gateway.py
- Evidence: All 135 cached live series carry title_zh, and grep finds no title_zh use in v3.
- Impact: Chinese reports contain an English table and English labels under a Chinese heading.
- Fix: Localise the header, status labels and 'Figure' through `_TEXT`, and use title_zh (plus geography) when the language is Chinese. Test: a zh engine renders a Chinese baseline table.

### V3-22 IMPROVEMENT (low) — Baseline table and digest formatting problems
- Location: linear_research.py:4453-4462, 5650-5661
- Evidence: Probe self_table.py on real series showed: duplicated units ('4.2% Percent', '0% Per cent per year'); ISO start dates as periods for quarterly and annual series ('2026-04-01', '2026-01-01'); a yearly change of '0% (missing).' with a trailing period; an unscaled '-166796952277.38 U.S. dollars'; a 'Latest stored value' that is the last row even when that row is a WEO current-year projection or a partial-month mean of daily data (fred:T10Y2Y October 2026 built from about 8 days, provenance complete=False) labelled as a stored observation.
- Impact: Readers and writers can misread the current state, for example taking a projection or a partial month for a complete observed value.
- Fix: Drop the unit suffix when the value is already formatted with %, show quarter or year periods, and show 'latest historical' and 'publisher projection (year)' separately. Mark partial periods, and scale large currency values while keeping the exact verifiable value.


#### Phase coverage
| # | Phase / step | Official data used today? | How / where | Gaps |
|---|---|---|---|---|
| 0 | Engine init | Yes | `_configure_data` (linear_research.py:4084-4112) creates DataSources lazily and calls `prewarm()`, which does not block. Live, the servers were ready 0.5-2 s after prewarm. One tools object is chosen per run (4060). | Resumed runs never set up providers (V3-07) |
| 1 | Scope (plan:scope) | No | Scout queries are web-only | The catalog is not consulted |
| 2 | Plan / replan | Partial | The last message adds a short trailer, the provider statuses and `catalog_digest(question)` (4599-4605). `_normalize_kiqs` and `Kiq.from_dict` keep `data_needs`. | The JSON shape has no `data_needs` key and the fallback plan has none (V3-10). The digest prints geography as ISO3 codes, which triggers V3-01. |
| 3 | Data prefetch | Yes | `phase_data` (4335-4396): each need resolves to the top hit, then `prefetch_data` runs `get_many` within min(150 s, 8% time share). Results become durable pages, ledger ids and index.json. | Wrong country (V3-01); window ends today (V3-06); serial, with one IMF slot (V3-14); fills the 12-dataset cap (V3-15); skipped on resume (V3-07); failure reasons lost (V3-18) |
| 4 | Seeds | Yes | `_run_seeds` adds `data_index` rows to each KIQ's seeds (4903-4905) | Follow-up KIQs get none (V3-16) |
| 5 | Gather / KIQ agents | Yes | `data_search` and `data_get` tools with per-preset call budgets (quick 24/3, standard 50/4, deep 90/5). Agents see an "OFFICIAL DATA ALREADY RETRIEVED" block, get one deterministic summary fact per dataset they were shown (4836-4846), and data calls count towards the novelty rule. | BIS values mislabelled (V3-05); projections tagged VERIFIED (V3-11); cache poisoning and empty arguments (V3-04); little guidance and stale tool texts (V3-19) |
| 6 | Gap review + follow-ups | No | The coverage matrix and the gap template have no data dimension | V3-16 |
| 7 | Synthesis digest | Partial | An "OFFICIAL DATA SERIES" block (latest value + year-earlier value) is appended to the persisted digest (5098-5100) | Titles have no country (V3-02); no trend or projection path (V3-17) |
| 8 | Section writers | No | They see only the digest; `_SECTION_RULES` says nothing about official data | V3-17 |
| 9 | Executive summary | No | Written from section leads only (5440-5448) | V3-17 |
| 10 | QA | Yes | `_prepare_data_exhibits` publishes datasets.json and renders up to 8 charts. `_embed_data_exhibits` places figures in sections that share the chart's KIQ and adds a baseline table. Citations are renumbered to positions, then `_data_checks` runs and hashes are sealed. | The check rejects correct statements and the engine's own table, and no repair is attempted (V3-03); formatting (V3-22); Chinese output (V3-21) |
| 11 | Critique (deep preset) | Partial | Sees the digest | No check against the stored official data (V3-17) |
| 12 | sources.json | Yes | Rows get source_origin `official_data`, the dataset file and a summary excerpt | Duplicate titles and URLs across countries (V3-02, V3-13); `date` is null |
| 13 | quantitative.json, timeline.json, actors.json `forecast_inputs` | No | Only the LLM extraction from report text feeds these; `forecast_inputs` indicators and base_rates are hard-coded empty (6293-6296) | V3-08 |
| 14 | research_quality / degradation | Partial | Official rows count as fetched for grounding (6050, 6302). The only degradation event fires when no rows exist and failures occurred (6362). | V3-18 |
| 15 | Research charts + Visual Annex | Partial | `data_*` charts count as decision charts; data charts beyond the cap of 8 go to the Visual Annex after QA | Quantitative charts lack official rows (V3-08) |
| 16 | Telemetry / meta | Partial | meta.data_sources records status, providers, calls, failures, cached, series_count, route_counts and per_agent; phase seconds are recorded | No per-series failure reasons (V3-18) |
| 17 | Resume | Partial | The stored data is replayed and the seal is verified | No new data can be fetched on any resume (V3-07); orphan ledger rows break resume (V3-12) |
| 18 | Chinese (zh) runs | Partial | The heading is "官方数据基线" and charts are rendered with lang=zh | Table, labels and titles stay English; `title_zh` is never used (V3-21) |
| 19 | Prompt-cache invariants | OK | One tools object is bound on prime, regular, wide and forced-final turns. ENGINE_CORE is unchanged. The catalog digest, provider statuses, data trailer and data blocks appear only in the last message, and the digest is persisted byte-identical. | None found |
| 20 | Overhead | Measured | Planner: +880-1,110 tokens per plan call. Agent calls: +682 chars of tool schema (cached). KIQ task: +~300 chars, plus 390-820 chars per seeded series. Each `data_get` adds 1.7-9.4k chars to the agent's append-only context. Digest: ~250 chars per series. The data phase runs serially for up to min(150 s, 8%); 88 s was observed live. The QA chart subprocess can take up to 180 s and is not bounded by the QA deadline. Prewarm spawns 5-6 MCP processes per run. | V3-14 |

Test runs:
- Plain pytest over the 15 v3 and official-data files: 1 failure (V3-09); every other test passed.
- Codex runner without the script allowlist: 1,116 passed, 10 failed, 13 errors. All failures and errors were caused by the runner's guard: it blocked subprocess-based performance tests, fixtures that call `os.environ.clear`, and the renderer and MCP server launches.
- Codex runner with the documented allowlist (official_data_mcp.py and render_data.py): 29/29 passed.
- Live probe, with no BLS calls and 3 FRED calls: see V3-06 and V3-14.


## verify:v3: v3 deep-research engine (linear_research.py, research_gateway.py) plus the shared data_sources/data_catalog behaviour v3 depends on, at HEAD bc2520a. 

- VERDICT V3-01: **CONFIRMED** (high) — Reproduced with vv3/v01.py against the real catalog. ISO3 queries resolve to the wrong country: 'policy rate CHN' gives bis:WS_CBPOL/M.US; 'inflation JPN' gives fred:CPIAUCSL; 'unemployment rate EMU' gives fred:UNRATE; 'GDP growth DEU' and 'GDP growth CHN' give imf:WEO/G163 (euro area); 'credit gap CHN' gives the US credit gap; 'CPI inflation IND' gives wb:IMF_WEO_PCPIPCH/USA. With country names the right series ranks first. catalog_digest prints geography as ISO3 ('(Per cent per year, M, CHN)'). phase_data (linear_research.py:4366-4377) takes the first line of the search output with no geography or score check. Scope: this only fires on the query path. The planner trailer (4600) also accepts a catalog id, and an id bypasses the search. When it does fire, wrong-country data is seeded and then gets a deterministic fact.
  - corrected fix: Normalise the need's geography before searching: map ISO3 codes and EA/EU/UK/US to GEOGRAPHIES[code][0], or let _parse_query accept whole-word ISO3 tokens. In phase_data, keep a hit only if catalog.lookup(hit).geography equals the requested geography (WLD only for global needs). Hits outside the catalog have no geography, so accept one only if its title contains the country name. Walk hits 1-3 before giving up. Tests: {query:'policy rate', geography:'CHN'} resolves to bis:WS_CBPOL/M.CN, and {query:'inflation', geography:'JPN'} never resolves to a USA series.
- VERDICT V3-02: **CONFIRMED** (high) — data_sources.py:1688 passes title=metadata.indicator_name. _base (1265-1268) applies it with values.update and so overwrites the curated catalog title, which carries the country. In the sweep cache every wb:IMF_WEO_*, WB_WDI_* and WB_GEP_* title lacks the country, and imf:CPI/BRA has none either, although the catalog title ends ': Brazil'. _data_summary, the baseline table and register_dataset (research_gateway.py:3761) all use series.title. The Data360 source_url has no country either, so the writers' digest and SOURCE INDEX cannot tell USA, DEU and CHN apart. Only the KIQ brief (render_series_brief) shows the id with its country code.
- VERDICT V3-03: **PARTIAL** (medium) — The mechanics are confirmed. vv3/v03.py: 'US unemployment was 4.2% in September 2026 [S1]' fails, while '4.2%', '4.2% in 2026-09' and '4.2% (2026-09-01)' pass. The prose's signed set contains ('+','=2026') because 'September 2026' is not stripped, but strip_dates removes every year from the page. vv3/v03b.py: the engine's own baseline rows fail for GDP (Billions of Dollars), PAYEMS (Thousands of Persons) and WALCL (Millions). The severity is lower than claimed because qa.passed and the failures list are consumed nowhere. A grep of backend/app and deerflow_bridge finds only meta.research_qa and a log line, so nothing is gated or blocked. The cost is a check that only produces false positives, so it is medium, not high.
  - corrected fix: Do not drop date stripping wholesale. Feeding '2026-09-01' to _number_values_at unstripped would add spurious signed values ('-','=9') to the page set and weaken the sign check. Instead, in _data_checks add {('+', '='+year)} for every year in the cited series' observation dates and coverage to signed_pages. When series.units contains thousand/million/billion/trillion, also add each page value multiplied by that scale. Then confirm that the rows emitted by _embed_data_exhibits pass _data_checks, which becomes a regression test. Treat the LLM rewrite of failing lines as optional, because the check runs after renumbering. Record the failing lines in meta instead.
- VERDICT V3-04: **CONFIRMED** (high) — Reproduced in vv3/v04.py with the real DataSources and a fake hub that returns 429. data_search(provider='') returns NO_DATA_MATCH because DataSources.search computes {''} & allowed = empty. A later provider=None search by K2 reuses the key 'search::...' and gets the cached NO_DATA_MATCH, while a direct search returns fred:UNRATE first. data_get(start='', end='') raises ValueError('Unrecognized observation period'), which is cached under 'get:fred:UNRATE', and a later clean data_get by K2 returns the same failure. A transient 429 on fred:PAYEMS is cached too: K2's call made no hub call. _request(end='2026') gives end 2026-01-01, so a monthly series loses February to December of that year.
  - corrected fix: As proposed, with one precision. Map a bare-year end to YYYY-12-31 only inside _request's end handling, not in the shared _period(), which also normalises starts and anchors. Normalise '' to None in data_search and data_get before building keys. Never write a DataError with retryable=True, a ProviderCallTimeout or an 'is still running' result into _data_cache.
- VERDICT V3-05: **PARTIAL** (medium) — Confirmed. vv3/v03b.py shows the BIS baseline row labelled 'publisher-flagged value: observed'. _status_flag maps BIS 'A' to 'observed', and _data_value_status (linear_research.py:4439-4451) treats any non-empty flag as projected=True, so the deterministic BIS fact is tagged REPORTED. WB and WEO rows read 'publisher-flagged value: unknown', although the normaliser set that flag, not the publisher. The impact is mislabels and an undercount of VERIFIED facts. No wrong number is published, so the severity is medium. data_sources._observation_kind already implements the correct mapping, and render_series_brief uses it, so v3's labels contradict the KIQ brief.
  - corrected fix: Replace _data_value_status with a wrapper over data_sources._observation_kind: 'observed' gives ('stored observation', False). 'preliminary', 'estimate', 'projection' and 'unknown' get explicit labels with True; for 'unknown' say 'status not supplied by publisher'. Also treat any observation dated after series.retrieved_at as a projection. Tests: a BIS fixture yields VERIFIED, and a WB WEO fixture yields 'status not supplied' and REPORTED.
- VERDICT V3-06: **CONFIRMED** (high) — data_sources.py:1098 sets finish = today when end is None, and _finish (1277-1279) drops observations dated after end. In the sweep cache all 20 WEO/GEP series end at 2026-01-01, and the GEP series have only 5 rows. The reviewer's live_weo.txt shows imf:WEO/G001 extended to 2030 with every flag 'unknown' and projection_from ''. Neither phase_data (4381) nor the agent schema passes an end.
  - corrected fix: Three additions to the proposal. (a) The research_gateway data_get stored window is immutable per identity (3626-3634), so the prefetch itself must request the extended end; agents cannot extend it later. (b) Once rows run to 2031, values[-1] becomes the 2031 projection. _data_summary, the baseline table and render_series_page's 'Latest' must therefore use the last observation dated on or before the retrieval date, and list later rows as 'publisher projection (year)'. WEO rows are all 'unknown', so classify any period after the retrieval date as a projection whatever its flag. (c) plan.horizon is free text, so parse a 4-digit year and default to the current year plus 5. Test: a WEO fixture with rows to 2031 keeps 'latest historical' at 2025 or 2026 and shows 2027-2031 as projections.
- VERDICT V3-07: **CONFIRMED** (medium) — _open_work_dir (linear_research.py:979-995) returns resumed=True for any state with the same identity, including a crash before planning. _configure_data (4093-4097) then freezes data and sets data_enabled to saved_enabled, which is False when index.json is missing. The run gets the web-only schema and no catalog in the planner, and phase_data (4345-4349) is marked skipped_resume. On a mid-gather resume, new data_get calls return 'providers disabled or evidence frozen' (uncached). Resume is a supported path (pipeline_orchestrator.py:511, POST /api/research/<id>/resume). The severity is medium because only resumed attempts are affected.
  - corrected fix: Keep the freeze when the data phase is done and the run is past gather; that is where evidence is pinned. When state shows the data phase not done, run the normal enabled configuration (providers, prewarm, data schema) and then phase_data. Never flip a run whose first attempt recorded status 'disabled' or 'unavailable' to enabled. Keep _check_data_reuse unchanged.
- VERDICT V3-08: **PARTIAL** (medium) — The v3 artefacts are as described: forecast_inputs() (6293-6296) hard-codes empty base_rates, drivers and indicators, and quantitative.json comes only from LLM extraction. But 'never reach forecast' overstates the gap. Forecasting reads datasets.json directly through the official_data carrier: claim corroboration and tags in report_agent.py (2311, 2397, 2447-2489), the 'Official series to watch' block in forecast_extractor.render_resolution_block (from validated binary data_anchors, around 3819), report_visualizer._official_chart_panels and _run_official_data (4316, 4558), and the historical_snapshot in simulation_config_generator (1969). The real gap is the 'Indicators to Watch' table and forecast.json indicators, which come only from forecast_inputs, plus the quantitative.json and quant charts.
  - corrected fix: Fill forecast_inputs.indicators deterministically in _write_structured, after QA, using the positional citation order from qa.citation_order. Each row gets {indicator, series, latest_value, latest_date (latest historical, per V3-06), units, frequency, date_or_trigger: 'next <frequency> release after <latest period>', source_ref}. Deduplicate against binary data_anchors so the resolution block does not list a series twice. If official rows are added to quantitative.json, tag them source_origin 'official_data' and have quant_metrics and metric_trajectories skip series already drawn as data_* charts.
- VERDICT V3-09: **CONFIRMED** (high) — Reproduced: `cd backend && .venv/bin/python -m pytest tests/test_official_data_end_to_end.py` raises AssertionError 'Use the documented guarded runner' at line 87. CI runs `cd backend && uv run pytest -q` (.github/workflows/ci.yml:38), and npm test runs `cd backend && uv run pytest`, so the suite stays red after K1 is fixed.
- VERDICT V3-10: **CONFIRMED** (medium) — The _T_PLAN JSON shape (409-421) has no data_needs. The only prompt is one trailing sentence (4600). fallback_kiqs (1157-1166) builds Kiq objects without data_needs, so fallback plans make phase_data finish with 'no_needs_or_unavailable'.
  - corrected fix: As proposed: add data_needs to the plan shape only in the data-enabled trailer, the last message. Add a deterministic catalog fallback that applies V3-01's geography handling and score >= _PRIORITY_MIN_CONCEPT. Charge those calls to a seeder allowance that does not drain the agents' global data-call budget (see missed M1).
- VERDICT V3-11: **CONFIRMED** (medium) — vv3/v11.py on the real wb:IMF_WEO_NGDP_RPCH/DEU, whose 2026 row has kind 'unknown' and is a current-year projection: 'German GDP growth is 0.79% [S1] (VERIFIED)' and 'IMF WEO projects ... 0.79% in 2026' both stay VERIFIED. The full-precision value 0.790622 becomes UNVERIFIED, so matching works on displayed values only. This violates the contract line 'must preserve projection/estimate labels' (integration-contract.md:21).
  - corrected fix: After postprocess_notes in _finish_kiq: for each VERIFIED fact whose sids are all dataset sids, map its numbers to observation rows on the cited page. If any matched row has kind other than 'observed', or is dated after the retrieval date, downgrade the fact to REPORTED unless the text already contains a projection or estimate word. Test with the WEO DEU fixture (expect REPORTED) and FRED UNRATE (stays VERIFIED).
- VERDICT V3-12: **CONFIRMED** (medium) — Reproduced without a symlink in vv3/v12.py. After the first dataset was stored, the run's data/ directory was made read-only; the second data_get returned 'DATA_UNAVAILABLE: StopIteration; use another source.' The ledger kept (sid 2, fetched=False, fred:GDP). A fresh restore_data gives invalid_data_sids={2}, and K2's retry got the cached StopIteration. On any resume after a KIQ has started, _check_data_reuse raises _EngineFailure('official_data_evidence_corrupt'), which fails the run. That breaks design.md §1.1 ('nothing fails a run because a data source is ... broken'). The symlink part also holds: v3 never resolves out_dir (linear_research.py:4000), and _safe_path rejects any symlinked ancestor, for example /tmp or /var on macOS.
  - corrected fix: As proposed. Make restore_data treat fetched=False dataset rows as never exposed and exclude them from _invalid_data_sids; this is safe because no agent ever received a sid for them. In _safe_path, resolve only the trusted root and reject symlinks only below it.
- VERDICT V3-13: **CONFIRMED** (medium) — fetch() (research_gateway.py:3946-3949) returns the first dataset row whose canonical URL or source_url matches. The Data360 source_url is per indicator with no country (data_sources.py:1689), and IMF uses one URL per dataflow, so fetching a shared URL returns whichever country was stored first.
  - corrected fix: Do not fall through to a real HTTP fetch. The code states the invariant explicitly ('Dataset origins/identities always resolve to the pinned dataset page ... Never fall through to fresh HTTP evidence'). Instead: an exact identity URL (canonical, with drf_series) returns its page. A source_url shared by more than one stored series returns a deterministic list of '[S<n>] <series id> — <title> (<geography>)' and asks the agent to fetch one by marker or call data_get with the id. A source_url held by a single series keeps today's behaviour.
- VERDICT V3-14: **CONFIRMED** (medium) — A correction to the framing first: get_many already runs 8 workers (data_sources.py:1245), so the prefetch is parallel except for the single IMF and BLS slots. What is serial is the data_search calls for query needs, and the whole phase blocks gather. The live timing.txt shows 88.0 s, with imf:PCPS lost behind imf:WEO. Agent data_get runs inside a _call_within daemon thread, so the thread-local deadline is None there: lock.acquire(timeout=-1) and semaphore.acquire(None) wait without limit, and the gateway caches the ProviderCallTimeout.
  - corrected fix: Set the deadline inside the worker thread, because _local is thread-local: the lambda passed to _call_within must set and clear _local.deadline itself. Better, add a deadline_s parameter to get and search that does this. If prefetch overlaps the seed web searches, attach the data rows to seeds (linear_research.py:4903-4905) only after the join, and mark phase 'data' done before gather starts.
- VERDICT V3-15: **CONFIRMED** (medium) — The cap of 12 is hard-coded at research_gateway.py:3641, 3672 and 3755. DATA_SOURCES_PREFETCH_MAX defaults to 12 and is clamped to at most 12 (linear_research.py:4356). Once prefetch stores 12 datasets, every new agent data_get returns DATA_BUDGET_EXHAUSTED.
  - corrected fix: Scale the cap through ToolLimits by preset and clamp prefetch to about 60% of it. The downstream loader also truncates: load_official_data(max_series=12) (data_sources.py:574-580, backend official_data.py:170) keeps only the first 12 manifest rows. Raise or prioritise that limit together with the cap, or forecasting silently loses the extra series. Charts stay capped at 8.
- VERDICT V3-16: **CONFIRMED** (medium) — _coverage_matrix (5069-5084) has no data dimension. Follow-up Kiq objects are created with kind 'general' and no data_needs (5061-5065). _kiq_task shows the data block only for data_index[kiq.id], which is empty for every G*F* follow-up.
  - corrected fix: As proposed, emitting the coverage data line and the follow-up data text only when data is enabled, so disabled prompts stay byte-identical (design.md §1.2). Bound follow-up prefetch by the seeder allowance from missed M1.
- VERDICT V3-17: **CONFIRMED** (medium) — Confirmed from the code. _SECTION_RULES (500-510) and _T_CRITIQUE (457-461) say nothing about official data. _exec_summary (5440-5448) sees only section leads, and the digest block holds only the latest and year-earlier values.
  - corrected fix: The proposed static _SECTION_RULES bullet would break design.md §1.2: _SECTION_RULES is sent in every writer task, including runs with data disabled, which must stay byte-identical. Append the official-data rule in section_task, the exec task and the critique task only when self._data_rows() is non-empty; those are last-message text, so the cache layout is also preserved. Digest trajectory lines are fine because digest.md is built once and persisted.
- VERDICT V3-18: **ACCEPT_IMPROVEMENT** (medium) — This serves the goal: agents cannot react to failures, and operators cannot see K2-style failures per run. DataError.message is already redacted by _redact (env secrets replaced, capped at 300 chars; data_sources.py:930-938), so surfacing it is safe if only DataError.message is used and gateway-level str(exc) never is. Pass it through _clean_web_text, since it is provider text. Also record per-series failures in meta.
- VERDICT V3-19: **ACCEPT_IMPROVEMENT** (medium) — Worthwhile, but the fix needs correcting. Editing ENGINE_CORE would change prompts in disabled runs and break design.md §1.2. Put the official-data guidance in the data-enabled KIQ trailer (around 4927) and in the descriptions of AGENT_TOOLS_WITH_DATA_SCHEMA, which is only bound when data is enabled: a provider enum, id and date formats, and that data_get output counts as a fetched page. Make the stale texts conditional on data_enabled: 'UNKNOWN_TOOL: only web_search and web_fetch are available.' (around 3850) and the INVALID_TOOL_CALL hint (3820).
- VERDICT V3-20: **ACCEPT_IMPROVEMENT** (medium) — V3-02, V3-03, V3-05, V3-06 and V3-11 all pass the current synthetic suite. Captured normalised series from the sweep cache are safe to commit as fixtures: a grep for api_key and registrationkey found nothing. Drive the real _finish_kiq, _embed_data_exhibits, _data_checks and _source_rows with them.
- VERDICT V3-21: **CONFIRMED** (low) — There is no title_zh use in linear_research.py or research_gateway.py (grep). The baseline table header and status labels are English literals (5650-5661), and so is '### Figure:' (5672).
- VERDICT V3-22: **ACCEPT_IMPROVEMENT** (low) — Reproduced in vv3/v03b.py output: '4.2% Percent', '3.88% Per cent per year', ISO period starts, a trailing '(-4.55%).', '-166796952277.38 U.S. dollars', and 'publisher-flagged value: observed'. Reuse data_sources._display_period and _observation_kind, which render_series_brief already uses. Keep the exact verifiable value next to any scaled display so the V3-03 check still passes.
- MISSED V3-M1 (BUG, medium) The data seeder spends the agents' global data-call budget; in quick runs agents can be left with about one data call for the whole run — at research_gateway.py:3596-3605 (_reserve_data: 'data-seeder' is exempt from the per-agent cap but counts against max_data_calls_total), 3607-3614 and 3704-3717 (each seeder data_search reserves a call), 3641-3643 (prefetch reserves one call per series); linear_research.py:4027 (quick 24/3, standard 50/4, deep 90/5), 4362-4380 (one data_search per query-only need)
  - evidence: vv3/m_budget.py with quick limits ToolLimits(max_data_calls_total=24, max_data_calls_per_agent=3) and the real ResearchTools: 12 seeder searches plus prefetch of 11 series used 23 of 24 calls. The next agent data_get('fred:T10Y2Y') returned 'DATA_BUDGET_EXHAUSTED: write notes from stored evidence.' Even with no searches, a full 12-series prefetch takes half of the quick budget.
  - fix: Give the seeder its own allowance (prefetch cap plus query needs) outside max_data_calls_total. Alternatively, reserve a call only when a provider is actually contacted: catalog-only searches in DataSources.search return before any network call when the catalog yields at least 'limit' hits. Test: quick limits, 12 needs prefetched, and every KIQ agent can still make max_data_calls_per_agent calls.
- MISSED V3-M2 (BUG, medium) The World Bank native search guesses the country by raw substring, which forces the wrong required_country — at deerflow_bridge/data_sources.py:1019-1021 (countries = [code ... if any(a.lower() in query.lower() ...)], then required_country=countries[0] and areas=countries)
  - evidence: Probe: 'Latin America remittances' gives ['USA'] with 0 catalog hits, so the WB path runs with required_country USA. 'North Korea missile exports' gives KOR (South Korea). 'Indiana manufacturing employment' and 'arbitrage spreads' give IND. 'usage of electricity' gives USA, and 'urban population growth' gives AUS (via 'rba'). The code comment says the country 'must be explicit, never guessed'. The path runs whenever catalog and FRED hits number fewer than 6, which is likely without a FRED key.
  - fix: Use catalog._parse_query(query).geos, which matches on word boundaries via _term_hit, instead of substring tests. Omit required_country when no single country is detected. Tests: 'Latin America remittances' sends no required_country; 'North Korea' never maps to KOR.
- MISSED V3-M3 (BUG, low) The data-chart renderer subprocess in QA is not bounded by the QA or run deadline — at deerflow_bridge/linear_research.py:5501 and 5613-5621 (_prepare_data_exhibits calls bridge _render_data_charts); deerflow_bridge/deerflow_research.py:16122-16128 and 16300-16302 (subprocess.run with timeout=_charts_timeout(), default 180 s)
  - evidence: From the code path. QA can overrun the run time budget by up to 180 s, because the renderer timeout ignores the QA deadline.
  - fix: Pass min(_charts_timeout(), qa_deadline.remaining() minus a small reserve) to the renderer. If the time left is under a few seconds, skip charts; the stored table is already the documented fallback.
- MISSED V3-M4 (GAP, low) data_get silently ignores a new start or end window for a series already stored, so base-rate KIQs cannot get longer history — at deerflow_bridge/research_gateway.py:3626-3634 ('The first successful window is immutable evidence ... even with new bounds'); data_sources.py:1100 (default history: 10 years for M/Q, 25 for A)
  - evidence: From the code path. After a prefetch stores fred:UNRATE for 2016-2026, an agent's data_get('fred:UNRATE', start='1990-01') returns the same stored page and gives no sign that the requested window was not fetched. Base-rate questions (for example, recession frequency) need longer history than the 10-year default.
  - fix: When the requested start or end lies outside the stored coverage, prefix the output with a one-line note: 'run already holds <id> for <coverage>; the requested window was not refetched'. Let the prefetch for base-rate KIQs (kind 'data', base-rate wording) request a longer start, for example 30 years for monthly series, capped at 240 observations, through need.start.

## verify:legacy: Legacy research engine (deerflow_research.py data helpers, prompts and hooks; data_tools.py), harness/runtime registration, data-sources/data-visuals/

- VERDICT L10: **CONFIRMED** (high) — I reproduced this with the UNPATCHED repo modules (vlegacy/g10.py). Lane rows from live/legacy_run went through export_fetched_sources_for_manifest, then seed_manifest_sources, then sources.json in a fresh dir, then _finalize_data_series. Finalization succeeds and rewrites dataset.file to data/<slug>.json, but dataset.page stays 'data/candidates/<d>.txt'. pipeline_orchestrator._research_data_artifacts(glob_dir) then raises FileNotFoundError 'candidates'. _promote_research_contract (pipeline_orchestrator.py:11942) runs after the 2-attempt retry loop, and its validation error raises, so the research stage fails after the full spend. Global synthesis is on by default for n>1 (:11443). Legacy is forced whenever the pinned actor policy requires it (:6288). The synthesis-recovery path (:11285) has the same exposure.
  - corrected fix: Materialize the evidence in _finalize_data_series for every validated_source row whose dataset.page or dataset.file does not exist under out_dir. Use NEW content-addressed paths: data/candidates/<sha256(page)>.txt holding row['content'] after checking it against content_sha256, and data/candidates/<sha256(raw)>.json holding the canonical json.dumps(snapshot, sort_keys=True, ensure_ascii=False, allow_nan=False). Rewrite row['dataset'] to these paths. Do NOT reuse the lane-relative path. data_tools._capture names candidates by sha256(series id)[:24] (data_tools.py:216-219), so two lanes that captured the same series with different windows yield two URL-distinct rows with the SAME paths. Writing the first and keeping the second would fail 'research dataset source snapshot mismatch' (_research_data_artifacts:3541-3549). Write everything with tools.safe_path and atomic writes. Test: two lanes with the same series and different windows, plus one other series; global dir with transported rows only; assert _research_data_artifacts and _research_contract_validation_errors return cleanly.
- VERDICT L1: **PARTIAL** (medium) — The bug is real. provisional_number = 1_000_001 + int(sha256) (data_tools.py:103-104) gives 77-78 digit [S#]. legacy_finalize.log shows a one-digit mis-copy surviving _prepare_legacy_data, and finalize_report_citations later strips it as dangling. I lowered the severity because deep (the default depth) synthesis cites through the pinned small-number SOURCE INDEX, which includes official rows via _merge_shared_fetched_sources. The long ids bite in quick/standard in-turn reports, notes and fan-out absorption, and when a dataset falls outside the index cap (L20).
  - corrected fix: Short ids must stay unique across lanes. Global synthesis unions every lane's transported rows (_legacy_data_sources). _remap_data_citations (deerflow_research.py:1978) and _remap_lane_citations (:7517) RAISE ValueError when one provisional number maps to two URLs, so per-run sequential ids (S9001+k or D1, D2, ...) would crash the merge. Options: (a) a lane-qualified short form such as [D<k>] in the journal, with the transported row's provisional id dropped once _remap_lane_citations has translated lane text to global numbers; or (b) a short hash (for example 6 base-32 chars of the page hash) checked for collisions in the journal. In either case, change the collision handling from raise to strip-plus-diagnostic. Tests: id length <= 8; [Dk] maps to the final S#; two lanes both with D1 merge without a ValueError.
- VERDICT L2: **PARTIAL** (medium) — Confirmed: the budget key is configurable.thread_id (data_tools.py:372,379), and task subagents inherit the parent thread_id (task_tool.py:261-263; executor.py:593-595). The claim that the whole run shares one thread is wrong for the default depth. DEERFLOW_RESEARCH_DEPTH defaults to 'deep' (backend/app/config.py:1159), and deep runs every phase on its own thread ({tid}-phase-i, -forecast-, -adaptive-, -fallback-; deerflow_research.py:13041-13295). Each KIQ fan-out worker also gets its own thread (:10766), and each outer lane has its own state dir (pipeline_orchestrator.py:2446). The '4 calls total' starvation applies only to depth=standard, which uses one thread plus same-thread top-ups (12619-12676). Within a deep phase, the lead and its task subagents still share 4 calls, searches included.
  - corrected fix: Add legacy-specific knobs, e.g. LEGACY_DATA_GETS_PER_THREAD (default 8-10) and LEGACY_DATA_SEARCHES_PER_THREAD (default 6). Keep the 50 per-lane total. Charge a search only when DataSources.search actually made a provider call, which happens when catalog hits are fewer than limit (data_sources.py:1005-1009). Leave subagent keying as is unless a stable per-task id is exposed: the executor's run_config carries only the parent thread_id.
- VERDICT L3: **PARTIAL** (high) — Confirmed for WEO by live probes (patched scratch module; cache in vlegacy/cache_v). With end=2031-12-31, wb:IMF_WEO_NGDP_RPCH/CHN returns 2007..2031 including 2027-2031, while the default end of today stops at 2026. imf:WEO/G001.NGDP_RPCH.A behaves the same way, 2007..2031 in 60.7 s (vlegacy/weo_imf.log). All flags stay 'unknown', so even explicitly fetched projections render as one dotted 'Unknown status' line (verified in run_zh data_compare PNG). REFUTED for GEP: with end 2031, wb:WB_GEP_NYGDPMKTPKDZ/CHN still returns n=5 for 2022..2026, and the Data360 metadata time_periods end is 2026. That is the publisher horizon, not the window.
  - corrected fix: (a) In DataSources._request, when end is None and the series is a projection family (wb IMF_WEO_*, imf:WEO*, WEO vintages), set finish = min(metadata/catalog horizon, today + 6y). ALSO anchor the default begin on min(today, finish) - N years. The probe shows begin = finish - 25y moved history from 2002 to 2007 once finish was 2031. Mention `end` in SKILL.md and the tool docstrings. (b) Status rule: an observation whose period end is after retrieved_at cannot be observed, so classify it as 'projection' (publisher outlook/estimate, period incomplete) in both _observation_kind and render_data._status. Keep the other wb history 'unknown', but draw it solid with an 'unverified status' note. Test with the captured real payload.
- VERDICT L4: **CONFIRMED** (medium) — DATA_SOURCES_PREFETCH_MAX is read only at linear_research.py:4356, and deerflow_research.py has no catalog digest and no get_many prefetch. Official data enters a legacy run only when the LLM chooses to call the tools.
  - corrected fix: The proposal as written would break the tools. A prefetch that writes candidate rows without data_tool_state.json makes every later call fail with 'missing budget state for existing evidence' (data_tools.py:277-278). Any later agent data_get of a prefetched series whose request key is not in state.cache returns 'already captured with a different window' (296-299). Write the prefetch through a helper that, under _admission, appends the journal row AND a state.cache entry keyed by the canonical default request {series,start:None,end:None,transform:None}, with an agent bucket 'prefetch' so sum(agents)==calls still holds. Alternatively land L15 first. Keep prefetch deadline-bounded and exception-swallowing, inject nothing when disabled or empty so prompts are byte-identical, and record meta.data_sources.prefetch.
- VERDICT L5: **CONFIRMED** (medium) — grep finds no data_search/data_get/data-sources in skills/deep-research (SKILL.md core loop :25-31; source-tradecraft Macro row :21). _official_data_prompt_block is injected only at 5108/5137/5175/5256. build_scoped_worker_prompt (10697), coverage top-up (5315) and gap-closing (5355) omit it. Deep adaptive gap-closing and fan-out workers run on isolated threads with compact notes, so they never see the block, even though the gap prompt explicitly asks for 'a specific number with its as-of date and unit'.
  - corrected fix: As proposed. Keep the block placed after the fixed '/deep-research' preamble lines so the cache prefix is unchanged, and make it empty when data is disabled or registration is not ready.
- VERDICT L11: **CONFIRMED** (medium) — The API accepts {'Chinese','English','auto'} (api/research.py:44, sdk.py:63). The orchestrator passes '--target-language Chinese' (pipeline_orchestrator.py:2324), and 'chinese'.startswith('zh') is False at 16301 and 16369. The bridge already has a correct predicate at deerflow_research.py:5907 (any of chinese/mandarin/中文/汉语/zh).
  - corrected fix: Reuse the existing predicate from :5907 as one helper for both the renderer --lang and the baseline heading. For 'auto' or None, use the CJK ratio of the report. Add a regression test of _prepare_legacy_data(lang='Chinese') that checks for the zh heading and that --lang zh is passed.
- VERDICT L7: **CONFIRMED** (medium) — In legacy_finalize.log, the FRED row shows 'Status not supplied' while the page says observed, and the periods are raw ISO dates. Code at 16377-16380 maps raw 'p' to 'Publisher projection'. BLS P is stored raw (see _observation_kind, data_sources.py:276) and is preliminary per the skill contract. The projection_from override also beats an explicit unknown flag. And once L3 is fixed, 'Latest stored value' would show the 2031 WEO projection, because it takes the last non-null observation regardless of kind.
  - corrected fix: As proposed. Also derive 'latest observed' only from rows that _observation_kind classifies as observed, and show the next publisher projection in its own column.
- VERDICT L8: **CONFIRMED** (medium) — _fetch_wb passes title=metadata indicator_name/name (data_sources.py:1688), and _base lets the metadata override the catalog title, which carries the geography (1267-1268). The CHN and USA WEO rows therefore share one title in References, the annex and the PNG titles. provider_name comes from PROVIDERS['wb'].
  - corrected fix: As proposed. Prefer the catalog title when the catalog entry exists. Otherwise append the geography name. Note this changes page bytes, so take the same page-hash versioning care as L16.
- VERDICT L12: **PARTIAL** (low) — Serialization is confirmed: _run holds _LOCK (an RLock) and flock across sources.get/search (data_tools.py:274-330), and live/lock_demo shows 8/16/24 s for 3 threads. A real IMF WEO call took 60.7 s, blocking every other in-process data call for that long, and in-process waiters block on the RLock with no timeout. However, task subagents run in in-process threads (executor.py:192 ThreadPoolExecutor), and each lane has its own artifact dir. The cross-process 'busy after 5 s' path does not occur in the legacy topology, and nothing fails: wall time is extended.
  - corrected fix: Reserve, release, then commit as proposed. However, the current code treats a cached 'pending' entry as 'prior request failed' (data_tools.py:287-288), so concurrent identical requests must wait on a per-key Event or condition instead of reading pending as a failure. The commit step must re-run the _capture existing-series check.
- VERDICT L6: **PARTIAL** (low) — Measured: series-catalog.md is 67,515 chars. The head-truncation cut at 50,000 ends at line 272, so the usgov rows and the BIS/IMF/usgov grammar sections (lines 304-366) are hidden. However, deer-flow _truncate_read_file_output appends 'Use start_line/end_line to read a specific range' (sandbox/tools.py:1312), so recovery is possible, and data_search returns ready ids.
  - corrected fix: Move the three id-grammar sections to the top of the catalog or into SKILL.md, and state the line ranges in SKILL.md. The per-provider split and the size test are optional.
- VERDICT L14: **ACCEPT_IMPROVEMENT** (medium) — Verified in the deer-flow venv (vlegacy/schema.py). The args are untitled strings with no descriptions or enums. provider='' returns 'unknown provider', and start='' or '2020' returns 'dates must use YYYY-MM-DD'. Better schemas directly improve the first-call success of the tools the user wants agents to use, at low cost. The tool schema is part of the cached prefix, so the change costs a one-time cache miss only.
  - corrected fix: As proposed, plus a provider enum and accepted partial dates normalized to YYYY-MM-DD before the request key is computed, so cache keys stay canonical.
- VERDICT L15: **ACCEPT_IMPROVEMENT** (medium) — Confirmed live (legacy_sim.log): a different window on a captured series returns DATA_UNAVAILABLE. Returning the stored page costs nothing and keeps one generation.
  - corrected fix: Return _response(existing_row) with a coverage note and no budget charge. Reject the optional 'wider window as new generation' part: load_candidates raises on a duplicate series id (data_tools.py:147-148), the whole journal then becomes invalid, and every official row in the run is lost. Supporting a second generation would need a journal identity redesign.
- VERDICT L16: **CONFIRMED** (medium) — format_value uses f'{n:.2f}' for percent units (data_sources.py:316), so 3.875 renders as 3.88 and 4.125 as 4.12 under round-half-even. The change line formats yoy_change with series.units, giving '%' instead of pp (:346). Both are visible in the live BIS and UNRATE pages.
  - corrected fix: As proposed, with one invariant added. The page bytes are hashed into content_sha256 and the provisional id, and validated_source/load_candidates re-render and compare them (data_tools.py:145,187-195; research_gateway.py:3581). Changing the format therefore invalidates resumed lanes, transported rows and synthesis-recovery manifests from older code. Version the page format (store page_format in the snapshot and keep the old renderer for validation), or explicitly accept and log the drop.
- VERDICT L13: **CONFIRMED** (high) — Plain `.venv/bin/python -m pytest -q tests/test_official_data_end_to_end.py` fails at :87 with 'AssertionError: Use the documented guarded runner'. CI runs `cd backend && uv run pytest -q` (.github/workflows/ci.yml:38), so CI stays red after the K1 fix. test_v3_official_data.py:31 is benign because it only writes when the variable is set.
  - corrected fix: Use pytest.skip when MAIN_OFFLINE_EVIDENCE is unset, or default the evidence dir to tmp_path.
- VERDICT L9: **ACCEPT_IMPROVEMENT** (low) — Confirmed in render_en.log: 8 singles were written, including 5 per-country BIS policy-rate charts, plus 2 compare charts, and fred:CPIAUCSL#yoy was dropped by --max 8. _select runs before _compare_groups (render_data.py:738-751, main ~1868). Better use of the cap directly serves the goal of forecast-relevant visuals.
- VERDICT L17: **CONFIRMED** (low) — Legacy meta has only data_tool_registration (17398) and, when rows exist, {series_count,status} (16360). v3 records providers, data_stats and degradation (linear_research.py:4086-4112, 4396).
  - corrected fix: Derive the counts from data_tool_state.json (calls, agents, per-key status) and the journal at finalization. Call DataSources.providers() only when an instance already exists in-process, so finalization never starts the hub (data_sources.py:889-893).
- VERDICT L18: **ACCEPT_IMPROVEMENT** (low) — I accept a narrowed scope. The zh compare PNG (run_zh/charts/data_compare_wb_imf_weo_ngdp_rpch.png) has the English y-axis 'Percentage change' and the English provider 'World Bank Data360'. Legacy places all data figures in an annex after References, while v3 places them in sections. Point-of-use placement (by the cited S# section, falling back to the annex), zh unit/provider localization and the cross-section latest-value chart that chart-patterns.md:16 already prescribes directly serve 'reports include data visualizations'. Defer the indexed and rolling variants.
- VERDICT L19: **ACCEPT_IMPROVEMENT** (low) — Confirmed: each data_*.html is about 4.86 MB (include_plotlyjs=True, render_data.py:1624). The demo exporter copies markdown-linked assets, '[Interactive version](charts/...html)' included, into docs/, so a demo commits about 5 MB per data chart. report_visualizer.py:2739-2811 already uses include_plotlyjs='directory'.
  - corrected fix: Accept only the HTML-twin part (a shared plotly.min.js or opt-in twins; check that the research contract chart set and the artifact routes serve the shared js). Reject moving the snapshot out of sources.json to a file reference: that reintroduces exactly the lane-local file dependency that breaks L10. Trimming provenance.metadata (ref_country etc.) is acceptable with page/hash versioning.
- VERDICT L20: **CONFIRMED** (low) — Confirmed by code path only. New data rows sort after prior rows in _merge_shared_fetched_sources (2021-2023). build_citation_index stops at RESEARCH_CITATION_INDEX_MAX=100 (4802), and finalize_report_citations maps a provisional id to '' when its URL is not in the pinned index (4930-4931). The baseline table and chart captions still cite datasets, so only in-prose citations are lost.
- VERDICT L21: **CONFIRMED** (low) — deerflow_research.py:16105 adds both quant_metrics and metric_trajectories whenever any data_* id exists, and every data_* id counts toward the decision-chart minimum (16103).
- VERDICT L22: **PARTIAL** (low) — The facts are confirmed: no dataset/official handling in frontend/src; the 'datasets' artifact is registered only at pipeline_orchestrator.py:9956; the exporter copies charts only. Reports do include data figures and a baseline table, so the user's 'reports include visualizations' requirement is met. This is a nice-to-have transparency feature (download/inspect), not a workflow gap.
- VERDICT L23: **PARTIAL** (low) — Mostly refuted as an impact. _sync_deerflow_bridge_if_stale (pipeline_orchestrator.py:1504-1640) runs before every research subprocess (:2275, 11217, 11477), syncs data_mcp/data_catalog/data_sources/data_tools (:1365) and the skills fail-closed, and the in-memory registration is deliberate (it never mutates config.yaml). Registration failure is logged with plog 'warn' and recorded in meta.data_tool_registration. Remaining value: a doctor.sh parity check and showing registration status in the UI.
- MISSED M1 (BUG, medium) A transient official-data failure (e.g. FRED 429) is cached as 'failed' for the whole run, is never retried by any agent, and the failure reason is discarded — at deerflow_bridge/data_tools.py:283-288 (cached status != 'ok' -> permanent DATA_UNAVAILABLE), 317-328 (DataError.retryable ignored; generic message), 304-307 (the failed call still consumes budget)
  - evidence: Repro vlegacy/retry.py with a fake provider that first returns DataError('FRED HTTP 429 rate limited', retryable=True). Agent 'a' gets 'official-data request or evidence persistence failed'. Agent 'b' with the same args gets 'prior request failed or was interrupted; no refresh performed'. Provider calls = 1. A typo id ('fred:UNRATEX') returns the same generic text, so the agent cannot self-correct. The request key excludes the agent, so one agent's transient failure blocks the series for the whole lane. K2 shows real FRED 429s under bursts, and the data layer has no 429 retry (data_sources.py:1364 only classifies). A 'pending' entry left by a killed process also blocks the key on resume.
  - fix: Store retryable and the redacted reason in the cache entry (DataError.message is already redacted by _error/_redact). On a cached 'failed' entry that is retryable, allow up to N (e.g. 2) re-attempts after a backoff (e.g. 20 s by wall clock), charging the budget each time. Treat a 'pending' entry older than the provider timeout as failed-retryable. Return a short reason class to the agent (invalid id / not found / rate limited, retry later / provider down) so it can correct ids or wait. Tests: retryable then success yields a captured row; a non-retryable failure stays cached; the typo returns 'invalid or unknown series'.
- MISSED M2 (GAP, medium) Legacy synthesis (single-thread, multipart sections and multi-lane global synthesis) never injects the stored official series, unlike v3 — at deerflow_bridge/deerflow_research.py synthesize_from_thread (:8406), multipart section prompts (~6990-7010 build only the routed SOURCE INDEX; render_citation_index_block omits excerpts), global synthesis via --synthesis-manifest (subagents=False, no data tools); compare linear_research.py:5098-5100 ('OFFICIAL DATA SERIES' appended to the synthesis digest)
  - evidence: grep finds no render_series_brief or series_stats use and no official-data block in any legacy synthesis or section prompt (official_data references only at 1940-2082, 5075-5256, 8173, 16200). In deep and multi-lane modes the synthesizer sees official numbers only if a worker happened to copy them into notes. The deterministic Official Data Baseline table is appended after synthesis, so the narrative and forecast reasoning may never discuss the official baselines or projections.
  - fix: Before synthesis, build a deterministic block from _legacy_data_sources(): render_series_brief(series, sid) with the FINAL pinned [S#] (latest observed, year-earlier change, next publisher projection, units, period labels), capped at about 12 series and 4k chars. Append it after the stable prompt prefix in synthesize_from_thread, the multipart section prompts (routed by series terms) and global synthesis. Empty when there are no rows, so prompts are byte-identical when disabled. Test: a fake journal with 2 series puts the block, with the final S numbers, into the prompts.

## verify:providers: Provider fidelity + data layer (data_sources.py, data_catalog.py, data_mcp.py, data_tools.py text contract, official_data.py, fixtures) — adversarial 

- VERDICT P-UNITS: **CONFIRMED** (critical) — Core bug confirmed, but one sub-claim is refuted.

Reproduction:
- Replaying the captured native attributes through HEAD _wb_units/_sdmx_units (verify/replay_units.py): 54/54 wb fail (52 'unit code and metadata disagree', 27 V_LST 'ambiguous disaggregations') and 24/50 bis fail ('label contradicts canonical units').
- A fresh live run through the real adapter (verify/live_units.log) gives:
  - wb:WB_WDI_SP_POP_TOTL/USA: 'unit code and metadata disagree'
  - wb:IMF_WEO_NGDPD/USA: 'ambiguous disaggregations'
  - wb:WB_WDI_EG_USE_ELEC_KH_PC/USA: disagree
  - bis:WS_GLI and bis:WS_CREDIT_GAP: label contradicts
  - bis:WS_CBPOL/M.US: OK (control)
- _wb_units returns the native label (data_sources.py:817-821). The regex at :762 needs a trailing space, so it never strips the 'millions' suffix.
- The scratch patch turns credit-gap units into 'Percentage of GDP'. format_value treats 'Percentage' as percent, so it would print '%'.

REFUTED sub-claim: that 'catalog is wrong for wb:IMF_WEO_NGDPD; native is billions'.
- Live raw Data360 (verify/live_ngdpd.log): IMF_WEO_NGDPD/USA 2024 OBS_VALUE=29298025000000 with UNIT_MULT=9 and label 'billion US Dollars'.
- WDI NY_GDP_MKTP_CD/USA 2024 = 29298013000000 with UNIT_MULT=0.
- So the values are WHOLE dollars and the native multiplier is false. The catalog's 'U.S. dollars' and its note (data_catalog.py:1370-1374) are correct.
- The proposed change to 'Billions of U.S. dollars' would mislabel by 1e9.

Overlap with K2 (same root cause). New here: the counts on HEAD, the label-imprecision cases, and the scratch-patch regressions.
  - corrected fix: Keep the pin approach.
- Add CatalogEntry.native_unit=(code, mult) plus BIS dimension pins.
- On an exact match, return the curated entry.units and store the native code, label and metadata in provenance.
- Pin wb:IMF_WEO_NGDPD/* as (USD, 9) and KEEP the catalog units 'U.S. dollars'. Do NOT change them to billions.
- Non-catalog Data360 ids with UNIT_MULT != 0: never derive scale words from the multiplier. For the IMF_WEO database, ignore the multiplier, or fail closed unless a magnitude cross-check passes.
- Treat metadata 'Unit', 'Number' and '%' as uninformative.
- Accept a uniform COMP_BREAKDOWN_1='V_LST' and record the vintage.
- Keep credit-gap units 'Percentage points of GDP'.
- Tests:
  - Replay units_wb.jsonl/units_bis.jsonl for every wb/bis CATALOG entry.
  - Assert wb:IMF_WEO_NGDPD/USA yields units 'U.S. dollars' with value ~2.93e13.
  - A drifted code or multiplier fails closed.
- VERDICT P-FRED429: **PARTIAL** (medium) — Mechanism confirmed offline (verify/v_fred.py):
- A hub returning 'FRED API error (429)' gives DataError(retryable=False) after 1 hub call and 0 CSV calls.
- git grep shows no consumer of DataError.retryable.
- data_tools stores status 'failed' ('prior request failed ... no refresh', data_tools.py:288).
- The gateway caches 'provider returned no usable dataset.' under 'get:'+identity (research_gateway.py:3643, 3736-3738), so retrying with a different window also gets the cached failure.

Severity is lower than stated:
- No CSV on 429 is a deliberate Codex rule (fred-bls-review.md R7:109-119, metadata authority and route).
- The vendored server already retries 3x with jitter, honours Retry-After (fred-client.ts:198-206) and keeps a 120 req/min bucket per process.
- A single run (12 prefetch + 50 calls max, 2 upstream requests per series) seldom exceeds that. The K2 burst came from a sweep; the realistic trigger is concurrent runs sharing one key.

The proposed in-process token bucket duplicates the server's.
  - corrected fix: - On 429/5xx/timeout, fall back to _fred_csv ONLY for catalog ids, which have curated title and units. Record route='fred_csv' and provenance.fallback_reason='rate_limited'.
- For non-catalog ids, return DataError(retryable=True).
- Set retryable=True for 429, 5xx, timeout and quota errors.
- Neither data_tools._run nor gateway._data_call caches a retryable failure (count it, but let the next call re-attempt).
- Drop the DataSources token bucket. If cross-process pacing is wanted, use a file-locked counter like _bls_quota.
- Replace test_data_sources.py:820-828 with three cases:
  - catalog id + 429 -> CSV route with fallback_reason
  - non-catalog id + 429 -> retryable error with 0 CSV calls
  - a retry after the error re-calls the provider
- VERDICT P-SNAP: **CONFIRMED** (high) — Offline (verify/v_daily.py): fred:DCOILWTICO through the real keyless adapter gives resolution_safe False, and historical_snapshot(..., as_of='2026-10-14') returns ''.

Code:
- official_data.py:271-272 skips any resolution_safe=False row.
- :287-290 rejects 'unknown' flags.

Consumers confirmed:
- pipeline_orchestrator.py:12862-12869 (graph chunks)
- simulation_config_generator.py:1970-1980 (default v3 world brief)

test_official_data_downstream.py:297-304 passes and codifies the exclusion.

Scope note: monthly/quarterly FRED, observed BLS, BIS (including WS_XRU FX), Treasury FX and GFDEGDQ188S still reach the snapshot. Excluded are the 28 daily ids (5 of the 16 core ids) and every wb row.
  - corrected fix: Base display safety on explicit provenance, not on dropping the resolution_safe check.
- Admit a resolution_safe=False row only when provenance.aggregation is present (render as 'monthly mean of daily closes') or provenance.database_id=='WB_WDI' (periods up to the last complete year, render as 'status not supplied').
- Keep excluding: WEO/GEP rows, partial months, rows with no stated reason (the existing fred:UNRATE resolution_safe=False test case must stay excluded), and rows retrieved after the cutoff.
- Add the positive test: DCOILWTICO plus WDI rendered with qualifiers, and the WEO row excluded.
- VERDICT P-DIGEST: **CONFIRMED** (high) — verify/v_digest.py reproduces it.
- Picks with score >= 4.0:
  - 0 for China NEV share (EN and ZH), global semiconductor sales, US battery storage and AI capex.
  - Datacenter electricity: WDI kWh/capita, fred:PCEC96, BLS electricity CPI.
  - Tariff: FEDFUNDS, DFF and BIS EER (spurious 4.0 scores).
- The digest is then padded with the 16 US/global _CORE_IDS (data_catalog.py:1742-1759).
- The planner prompt (linear_research.py:4600-4605) allows a 'query' data_need but gives no hint when nothing matched.
  - corrected fix: As proposed:
- Fill a short pick list with entries matching the question's geography and topic before falling back to _CORE_IDS.
- When no picks match, append one line telling the planner to use data_needs.query with English concept terms. On a keyless FRED setup, note that FRED search is unavailable.
- Test: the China EV digest excludes fred:PAYEMS and contains the hint.
- VERDICT P-BREADTH: **ACCEPT_IMPROVEMENT** (high) — probe_breadth.log verifies the series:
- FRED IPG3344S, CAPUTLG3344S, A34SNO/A34SVS, IMPCH, B235RC1Q027SBEA, NASDAQSOX and PCU33443344.
- MTS table 3 line_code_nbr=110 'Customs Duties' (2026-08 = $12.84bn).

The catalog has no semiconductor, tariff or US-China-trade anchors. The usgov eia module only loads with EIA_API_KEY (data_mcp.py:86-87, 392-395), and that key is unset; even with it set, no usgov recipe could reach EIA. This directly serves DRF's demo themes (datacenter, EV, storage).
  - corrected fix: Phase 1 (keyless, cheap):
- Add the verified FRED ids with EN+ZH keywords and native-unit pins.
- Add usgov recipes for mts_customs_duties (line_code_nbr:eq:110), individual taxes (20) and corporate taxes (30).

Phase 2:
- Add EIA recipes, but advertise them in the catalog, digest and skill ONLY when EIA_API_KEY is set, to avoid repeating P-SEC.
- Include every new id in the gated live smoke.
- VERDICT P-WEOSTATUS: **ACCEPT_IMPROVEMENT** (high) — Confirmed:
- __post_init__ forces 'unknown' on every wb row and on WEO rows without a status (data_sources.py:192-205).
- The IMF server returns only 5 columns with no status (probe_imf.log).
- report_agent._build_data_pack (report_agent.py:2405-2412) therefore shows 'unavailable' as the latest historical value for every WEO and wb series.
- Data360 metadata carries date_released and date_last_update.

Splitting the official projection benchmarks into history and projection is central to the user's goal. The proposed fix's 'bump NORMALIZATION_POLICY_VERSION' is insufficient, though:
- __post_init__ re-applies on every from_dict.
- render_series_page output is re-validated by equality on restore (research_gateway.py:3581) and in the legacy strict load_candidates check (data_tools.py:145, 187).
- Reclassifying already-stored imf:WEO rows would drop resumed runs' official evidence and make the legacy data tools fail closed.
  - corrected fix: Gate the new status inference on stored provenance normalization_policy_version >= 3, which is set at fetch time. Older carriers keep the current behaviour and re-render byte-identically.

Status rules:
- WB_WDI: years before the retrieval year are 'observed', with status_basis recorded.
- WEO/GEP: years at or after the vintage year (from Data360 date_released, else the retrieval year) are 'projection'; the year before is 'estimate'; earlier years are 'observed' with status_basis='inferred_from_vintage'.

Keep resolution_safe=False for wb and WEO.

Tests:
- Captured WEO rows: 2026+ projection, 2025 estimate.
- An old-policy stored row re-renders unchanged.
- VERDICT P-DAILY: **CONFIRMED** (medium) — verify/v_daily.py (real adapter, keyless route, fake CSV for Jul-Sep plus 7 October days):
- Every month has complete=False and renders '(partial)'.
- All rows are 'observed'.
- series_stats.latest = 2026-10-01 73.43, a 7-day mean.

Code:
- data_sources.py:1280-1296 hard-codes complete False and uses the arithmetic mean for every daily recipe, including DFEDTARU, DFF, SOFR and debt_to_penny.
  - corrected fix: As proposed, implemented at fetch time in _finish only, so stored rows re-render unchanged:
- Compute complete per month and flag only the open current month 'preliminary'.
- Add provenance.latest_daily, rendered only when present.
- Use eop aggregation for policy targets and stocks.

Caveat: an adapter- or server-aggregated monthly mean must stay resolution_safe=False unless the anchor is explicitly defined on the monthly mean. Daily questions need native daily retrieval.
- VERDICT P-REDACT: **PARTIAL** (low) — Mechanism confirmed (verify/v_daily.py): env LLM_MAX_TOKENS=20 or HF_HUB_DISABLE_IMPLICIT_TOKEN=1 gives DataError('Unrecognized observation period'). The research subprocess inherits the full os.environ (pipeline_orchestrator.py:2349).

The stated exposure is overstated. A name-only scan of the shell and .env (verify/envscan.py) finds only two matching keys, CLAUDE_CODE_MAX_OUTPUT_TOKENS and REPORT_AGENT_SECTION_MAX_TOKENS. Both are 5 digits and never occur in dates or URLs; a fetch with 16384 succeeded. So the bug is latent in this environment. It becomes total and misleading when a value like '1', '20' or '2000' is set (the last breaks every year-2000 row).
  - corrected fix: As proposed:
- Redact only credential-shaped keys (*_API_KEY, *_TOKEN, *_SECRET, *_PASSWORD, plus the provider keys).
- Require length >= 8, not all digits, and not true/false.
- Never scrub Observation date/value.
- Tests:
  - X_MAX_TOKENS=20 and HF_HUB_DISABLE_IMPLICIT_TOKEN=1 still fetch.
  - A 12-character FRED key echoed in notes is redacted.
- VERDICT P-SYMLINK: **PARTIAL** (low) — Reproduced (verify/v_symlink.py):
- write_dataset_files through a symlinked parent returns the error manifest, and load_datasets returns 0 rows.
- BLS with a symlinked cache dir gives 'Symlink artifacts are not accepted' with 0 hub calls.

Not triggered by default:
- The default cache path comes from Path(__file__).resolve() (data_sources.py:872).
- Neither the repo nor backend/uploads is a symlink.
- The pipeline's mkdtemp synthesis dirs are created inside handoff_dir (pipeline_orchestrator.py:11285, 11836).

Only an operator-configured symlinked DATA_SOURCES_CACHE_DIR or checkout triggers it.
  - corrected fix: As proposed:
- Resolve the configured root once and enforce no-symlink only below it.
- Log the concrete containment reason.
- Keep rejecting symlinks inside data/.
- VERDICT P-FREDCAP: **PARTIAL** (low) — Not 'always'. verify/v_cap.py (fake CSV that honours cosd/coed):
- DGS10 from 2007 fails; from 2008 it succeeds (5000 rows is about 19.2 years of business days).
- DFF, a 7-day series, from 2013 fails (about 13.7 years).

Both consumers request max_obs=240, so even after the fix delivery is capped at 240 months (20 years). The gain is turning an error with a hidden reason into a trimmed success.
  - corrected fix: - For native-daily requests whose window exceeds the row cap, request server-side monthly aggregation: API frequency='m' with aggregation_method per series (avg for prices and yields, eop for targets and stocks); CSV fq=Monthly&fam=avg|eop.
- Include the aggregation in the cache key and provenance.
- Keep resolution_safe=False.
- Otherwise return the invalid_window reason (P-TEXT).
- VERDICT P-SEARCH: **CONFIRMED** (medium) — - catalog._ranked('半导体出口') returns 18 hits >= 1.0. The top is EXPGSC1 at 6.8; the rest are topic-only matches at 2.0-2.8.
- search() returns early at limit 6 (data_sources.py:1008-1009) and never reaches FRED.
- 'data center electricity' returns BLS electricity CPI and oil series.
- The v3 seeder takes the first line blindly (linear_research.py:4369-4373).
- probe_breadth.log shows FRED notes of 'undefined'.
  - corrected fix: As proposed:
- Count only catalog hits with concept score >= 4.0 toward the early return. This needs _ranked scores, because search_catalog drops them.
- Append weak catalog hits after live FRED and Data360 hits.
- Map ZH concept terms to English via catalog keywords before provider search.
- Drop 'undefined'/'null' notes.
- The seeder should prefer a hit whose catalog concept score is >= 4.0, or skip the seed.
- VERDICT P-WBGEO: **CONFIRMED** (medium) — Reproduced via the alias substring test:
- 'urban' -> AUS (alias 'rba')
- 'carbide' -> IND ('rbi')
- 'usage' -> USA ('usa')
- 'fedex' -> USA ('fed')

_parse_query finds no geography for any of these.

It is stronger than reported. The vendored Data360 server populates covers_country only when a country is requested (datamcps/data360-mcp-dev/src/data360/api.py:882-903) and returns None otherwise. The adapter (data_sources.py:1026-1028) then keeps no hit, so country-agnostic queries get ZERO Data360 hits, not 'almost none'.
  - corrected fix: - Use catalog._parse_query(query).geos.
- With 0 geos, call with required_country='WLD'. The proposed 'emit WLD when covered' cannot work, because covers_country is None without a requested country.
- With several geos, pass a semicolon list and emit one hit per covered geo.
- Test: the four queries produce no spurious country, and 'battery storage capacity' returns a WLD-pinned hit from a fake payload.
- VERDICT P-TEXT: **CONFIRMED** (medium) — Code confirmed:
- data_tools.py:319/328 map any DataError to the generic 'official-data request or evidence persistence failed', and :288 returns 'prior request failed' on reuse.
- Search lines at :314 and research_gateway.py:3730-3731 omit note and geography.

Two further problems:
- The gateway's failure cache key is 'get:'+identity with no window (research_gateway.py:3643), so even a narrower-window retry returns the cached failure.
- prefetch_data labels every failure 'within the data deadline' (:3690), including deterministic unit and 422 failures.
  - corrected fix: As proposed:
- Return an allowlisted reason taxonomy and never echo raw provider text.
- Do not cache retryable failures.
- Key failure caching on identity+window, or don't cache invalid_window.
- Give prefetch the same taxonomy.
- Search lines add geography and note[:120].
- Changing tool text does not affect any audit.
- VERDICT P-FIXTURES: **PARTIAL** (medium) — Confirmed: the README calls the values invented test data, the wb fixture uses UNIT_MEASURE 'PT'/'Percent' (provider_responses.json:169-192), and both cited tests pass under the Codex runner (ev-verify-providers-01: 6 passed). But K2 already states the synthetic-fixture, no-live-smoke root cause. What is new here is only the fix vehicle: captured real fixtures replayed over every catalog entry, plus a gated live smoke.
  - corrected fix: - Commit trimmed real captures: units_wb.jsonl, units_bis.jsonl, the IMF rows, the MTS rows, and the NGDPD rows with UNIT_MULT=9.
- Add a parametrized test over CATALOG.
- Add an opt-in DRF_LIVE_DATA_SMOKE=1 script (FRED paced at 30/min or less, no BLS) that diffs native code, multiplier and dimensions.
- VERDICT P-ROUTE: **ACCEPT_IMPROVEMENT** (medium) — Evidence:
- probe_imf.log: imf_get_parameter_defs 24.7 s plus fetch 36.0 s.
- data_mcp.py notes 30-50 s IMF calls.
- The IMF semaphore is 1 (data_sources.py:880) and the data phase is capped at 150 s (linear_research.py:4353).
- Ranking confirmed: imf:PCPS copper scores 13.0 vs fred:PCOPPUSDM 10.5. Both carry the same IMF PCPS data.

Preferring the fast route makes it more likely official series land during the time-boxed data phase.
  - corrected fix: - Add preferred/alternate links and rank the fast mirror first in search and digest.
- Instead of hard-coding parameter names, persist imf_get_parameter_defs results per flow in the disk cache with a TTL of about 7 days; re-fetch on a mismatch.
- Test: a second DataSources instance fetching an IMF series makes exactly one hub call.
- VERDICT P-FREDVINTAGE: **REJECT_IMPROVEMENT** (low) — The tool does support output_type and vintage_dates (fred/series.ts:60-61). But first-release resolution and back-tests sit outside the user's stated goal, which is quantitative research, agent querying and report visualizations. The change also touches the resolver's availability-proof model (resolve_data_anchor's docstring rejects unauthenticated vintage claims). Worth filing as a follow-up, not doing now.
- VERDICT P-BLSQUOTA: **ACCEPT_IMPROVEMENT** (low) — BLS_API_KEY is unset, the 20/day keyless counter is shared across runs (data_sources.py:1424-1451), and today's quota is exhausted. All six BLS-to-FRED pairs exist in the catalog. Cheap and improves reliability.
  - corrected fix: - Add fred_equivalent for the six pairs. Note that bls:CUUR0000SA0 maps to CPIAUCNS, which is not in the catalog.
- providers() should report bls as 'quota_exhausted' when keyless and the count is 20 or more today, so the planner's 'Providers:' line reflects it.
- Surface the FRED equivalent through the P-TEXT quota_exhausted reason, because raw DataError text never reaches agents today.
- Document the free BLS v2 key.
- VERDICT P-ZHRANK: **CONFIRMED** (low) — _ranked('美国十年期国债收益率'): DGS2 and DGS10 tie at 15.0 and DGS2 sorts first by catalog order; the two title_zh bigram sets are identical. '电力需求' returns BLS electricity CPI and oil series.
  - corrected fix: As proposed:
- Normalize CJK numerals.
- Add the keywords 十年期国债, 两年期国债, 电力需求 and 用电需求.
- Add ranking assertions.
- VERDICT P-SEC: **CONFIRMED** (low) — PROVIDERS['usgov'].role (data_catalog.py:101-103) ends with 'SEC company facts' and is printed in every digest header and in series-catalog.md:18. Meanwhile _fetch_usgov refuses sec (data_sources.py:1699-1702) and Series rejects usgov:sec/* (:188-189).
  - corrected fix: - Remove 'SEC company facts' from the role text and the rendered recipe table, then regenerate series-catalog.md.
- The keyless SEC companyconcept route is optional later work.
- VERDICT P-USGOV: **CONFIRMED** (low) — - Live (verify/live_units.log): spending/total with start=2007-10-01 marks FY2026 (2025-10-01) complete=True on 2026-10-12, 12 days after year end.
- The default window gives HTTP 422 (K2).
- debt_to_penny is a 'D' recipe, so _finish averages it (data_sources.py:1280-1287).
- Impact is limited: spending rows are already flagged 'unknown' and resolution_safe False.
  - corrected fix: As proposed:
- Add recipe min_start and clamp fetch_start (the K2 fix).
- Set complete only when today > end + ~120 days.
- Use eop aggregation for stock recipes (shared with P-DAILY).
- VERDICT P-WBMETA: **REJECT_IMPROVEMENT** (low) — Size confirmed from cached rows: 12-23 KB of provenance.metadata per wb series. But provenance never reaches any prompt (no report_agent, report_visualizer or simulation consumer reads it). This is artifact hygiene only and does not serve the user's goal. If done later, the whitelist must keep date_released and date_last_update, which P-WEOSTATUS needs.
- VERDICT P-PREWARM: **REJECT_IMPROVEMENT** (low) — Lifecycle is clean: warm-ready in 1.55 s, close in 0.18 s, no leaked processes. _call already starts a provider lazily on demand (data_sources.py:955-959). Prewarming only planned providers saves memory but adds nothing to official-data integration.
- VERDICT P-SCALE: **ACCEPT_IMPROVEMENT** (low) — format_value prints raw 14-digit dollar values (debt_to_penny, WEO NGDPD 29298025000000). The data pack is pinned into every section prompt, and EN/ZH scale errors are a known risk. The claim audit uses exact canonical statements (report_agent.py:2465-2474), so an extra companion line does not break audits.
  - corrected fix: Do NOT change render_series_page. Its text is hash-bound and re-validated by equality on restore (research_gateway.py:3581, data_tools.py:145). Put a magnitude-derived companion (e.g. '≈ 40.27 trillion U.S. dollars' / '≈40.27万亿美元') in render_series_brief, report_agent._build_data_pack and historical_snapshot only. Derive the scale from the value's magnitude, never from units text or provider multipliers (see the NGDPD false UNIT_MULT).
- VERDICT P-CACHE: **PARTIAL** (low) — The get_many TypeErrors reproduce (verify/v_fred.py) but cannot be reached from real callers. The only caller, gateway prefetch_data, passes de-duplicated, parsed string ids and max_obs only. In-memory map growth does not matter in practice: v3 research runs in a Popen subprocess per run (pipeline_orchestrator.py:2496), and resolution_monitor is a short-lived script. The only real part is that disk cache files under backend/uploads/.data_cache are never pruned; default windows end 'today', so new keys appear daily.
  - corrected fix: Prune cache files older than about 7 days when DataSources is constructed. The LRU cap and up-front validation are optional.
- MISSED M1 (GAP, high) The default window ends at the retrieval date, so every official projection (WEO, GEP) is silently dropped — at deerflow_bridge/data_sources.py:1099 (finish = today when end is None), :1100-1101, :1586 and :1620 (end_year from req end), :1279/:1324 (_finish drops dates after end); research_gateway.py:3683 (prefetch never passes end); linear_research.py:4363-4374; skills/data-sources/SKILL.md:11 (no guidance)
  - evidence: Offline, with a fake IMF hub returning 1980-2031 and the clock at 2026-10-12 (verify/v_weo_end.py):
- get('imf:WEO/G001.NGDP_RPCH.A') with no end returns 2002..2026 only (end_year=2026 is sent).
- With end='2031-12-31' it returns ..2031.

The digest advertises 'IMF WEO by country to 2031' and 'World Bank Global Economic Prospects'. But the v3 seeder calls get_many without end, and neither the tool description nor SKILL.md tells agents to pass a future end. wb:IMF_WEO_*/WB_GEP_* use the same end_year=current year, so they truncate the same way once P-UNITS is fixed.
  - fix: - In _request, when the entry or flow is a projection family (imf:WEO*, wb IMF_WEO/WB_GEP, or entry.topics containing 'projections') and end is None, default finish to Dec 31 of the current year + 6, or to the provider's maximum. Keep begin at 25 years before today.
- Mention in the data_get description that projection series need an explicit future end.
- Test: the default get of imf:WEO/G001.NGDP_RPCH.A includes the 2031 row, labelled projection under P-WEOSTATUS.
- MISSED M2 (BUG, critical) Data360 IMF_WEO_NGDPD carries a false UNIT_MULT=9; HEAD _wb_units would label whole-dollar values 'billion US Dollars' (a 1e9 error), and the scratch patch already does — at deerflow_bridge/data_sources.py:804-824 (_wb_units returns the native label, :817-821); scratchpad/fix/data_sources.py (scratch patch accepting V_LST)
  - evidence: - Live raw rows (verify/live_ngdpd.log): IMF_WEO_NGDPD/USA 2024 OBS_VALUE=29298025000000 with UNIT_MULT 9 and label 'billion US Dollars'.
- WDI NY_GDP_MKTP_CD/USA 2024 = 29298013000000 with UNIT_MULT 0. So the values are whole dollars.
- The reviewer's scratch cache (scratchpad/fix/cache) already holds wb:IMF_WEO_NGDPD/USA with units='billion US Dollars' and 2024=29298025000000.0.
- On HEAD it is masked only by the V_LST rejection.
- The P-UNITS proposal to change the catalog to billions would bake the error in.
- BIS multipliers are genuine (WS_CBTA US 6738.19 at mult 9 is about $6.7T).
  - fix: - Pin (USD, 9) for wb:IMF_WEO_NGDPD/* and emit the curated 'U.S. dollars'.
- For non-catalog IMF_WEO ids, ignore UNIT_MULT, or fail closed unless a magnitude check agrees.
- Never return the native Data360 label as display units for pinned entries.
- Regression test with the captured row: units 'U.S. dollars', value ~2.93e13.
- MISSED M3 (BUG, medium) Hash-bound re-render invariant: any change to render_series_page or to __post_init__ flag policy invalidates stored official evidence — at deerflow_bridge/research_gateway.py:3581 (restore requires render_series_page(series) == page); deerflow_bridge/data_tools.py:145 (strict load_candidates) and :187 (validated_source); data_sources.py:190-205 (fidelity re-applied on every from_dict)
  - evidence: - Restoring stored datasets drops any row whose re-rendered page differs.
- The legacy load_candidates(strict=True) raises 'candidate evidence mismatch'. _run then returns 'stored evidence or request state failed validation' for every later data call in that run.
- P-WEOSTATUS (reclassifying stored imf:WEO rows), P-SCALE (a new Summary line) and any format_value tweak would therefore strip official evidence from resumed or legacy runs.
  - fix: - Version-gate render and status changes on stored provenance normalization_policy_version, which is set at fetch time.
- Keep render_series_page byte-stable for older carriers.
- Add a test: a stored v2 row re-renders identically after the change.
- MISSED M4 (BUG, low) The gateway registers the ledger dataset and page before persistence; a persistence failure raises StopIteration and leaves an orphan ledger row — at deerflow_bridge/research_gateway.py:3761-3768 (_store_dataset)
  - evidence: - register_dataset() and the page write happen before write_dataset_files.
- When persistence fails (e.g. a symlinked out dir, or any OSError), it returns {'series': [], 'error': ...}.
- next(row for row in manifest['series'] ...) has no default, so it raises StopIteration.
- _data_call reports 'DATA_UNAVAILABLE: StopIteration; use another source.' and prefetch passes silently. The ledger keeps a registered, unfetched dataset source.
  - fix: - Check manifest.get('error') before using it, and use next(..., None).
- On failure, skip registration, or roll it back (mark it invalid) and return the provider_unavailable/persistence reason.
- Test with write_dataset_files patched to return an error manifest.
- MISSED M5 (GAP, low) Data360 discovery admits only the WB_WDI, IMF_WEO and WB_GEP databases; hits from every other database are silently dropped — at deerflow_bridge/data_catalog.py:217 (WB_DATABASES), :569-575 (wb_database); data_sources.py:1029 (parse_series_id rejects other prefixes)
  - evidence: - wb_database() returns None for any indicator outside the three prefixes, so parse_series_id fails.
- search() then silently drops hits from Data360's other databases, even when Data360 search matches a sector concept relevant to DRF topics.
- Code-level evidence only; the set of databases search returns was not probed live.
  - fix: - After the unit pinning (P-UNITS) lands, allow additional verified annual databases through an explicit allowlist with per-database unit and status policy.
- Meanwhile, report dropped-database hits as 'not fetchable' in the search note instead of discarding them.

## verify:report: Forecast report path: verification of RPT-1 to RPT-17, covering report_agent official-data pack, citation support, stabilization, chart placement and 

- VERDICT RPT-1: **CONFIRMED** (high) — Reproduced in probe2.py by calling _report_citation_support directly on the real carrier and sources.
- A true stored value ('14.8% in April 2020'; fred:UNRATE 2020-04-01 = 14.8) returns False, exactly like the fabricated '15.2%'. The predicate cannot tell true stored data from fabrication outside the 3 excerpt values.
- Mechanisms: _SEMANTIC_NUMBER_RE splits '24,408' into {'24','408'}. '0.2 percentage points' gives '0.2' but the excerpt gives '0.2%', because render_series_page (data_sources.py:349) formats a percentage-point change with the series units.
- Worse (probe7.py): lines copied verbatim from the data pack fail support. These include the YoY lines for UNRATE, FEDFUNDS, DGS10, GDPC1 and BIS, and the 5-year-range line, even though the pack tells writers to 'Quote stored values exactly with their source marker'.
- With a v3-shaped excerpt built by the real linear_research._Engine._data_summary (probe6.py), the true WEO claim '3.06% in 2026' is still False. Annual WEO excerpts have no latest, year-earlier or range lines at all.
- Whether the sentence is deleted or only loses its marker depends on resolved coverage. _repair_final_quantitative_grounding removes it only when coverage < REPORT_PUBLISH_GATE_MIN_COVERAGE; above that the [S#] is stripped. Either way it is a defect.
  - corrected fix: Add carrier-backed support, used both in _report_citation_support (repair and final audit) and in _quantitative_semantic_decision (so uncited true claims get the right tag instead of being deleted).
- Resolve the cited source to a carrier row through official_source_tag/dataset identity.
- Parse (number, period) pairs and require each number to equal the stored value AT THAT PERIOD (allowing format_value rounding, thousands separators and billion/trillion scaling). Never accept a match against an arbitrary observation.
- Derived numbers must equal the series_stats outputs: YoY change in pp or percent, and the 5-year min/max.
- Values with unknown, projection or estimate status count only when the clause carries a status word.
- Return False only for a stored-period contradiction; otherwise fall through to _semantic_citation_support. Inert when official_data is None, so output is byte-identical when disabled.
- Fix render_series_page to label the change in pp for percent units.
- Tests: pack lines and true historical sentences keep [S#] through _stabilize_publish_markdown and _enforce_final_publish_audit; '15.2% in April 2020' and '4.2% in April 2020' are still removed or unsupported.
- VERDICT RPT-2: **PARTIAL** (medium) — Mechanism confirmed. _place_visualizations passes the English manifest caption to _render_viz_block (report_agent.py:9330, 9387-9400). The title 'Official Series History and Forecast Thresholds' is 47 chars with 5 spaces, so it trips _LATIN_PROSE_RE (report_lint.py:149). Without a purity LLM the zh report hard-fails; my DEXCHUS zh run showed the same title lines.

The severity is overstated, though. _apply_language_purity always runs in production (report_agent.py:11809-11814), and these segments contain no numbers, so a working provider translates them and the report passes. The real exposure is publication depending on LLM availability for deterministic text. The same applies to pre-existing long English chart titles such as 'Forecast Revisions Across Published Vintages'. The reviewer's fix also misses the more serious caption-units deadlock; see MISSED-1.
  - corrected fix: In _place_visualizations, when zh, map EVERY manifest caption (not only official ones) through report_visualizer.CHART_TITLES_ZH before _render_viz_block, so both the alt text and the italic caption are localized. Keep titles digit-free. Combine with the MISSED-1 fix (exempt canonical official source-caption lines from contamination detection and from purity rewriting); otherwise zh reports with long-unit series still cannot publish. Test: a zh primary report, with an LLM stub that raises on every call, reaches _enforce_final_publish_audit with hard_passed True for both a 'Percent' carrier and a DEXCHUS carrier.
- VERDICT RPT-3: **CONFIRMED** (high) — Reproduced with probe1.py on the real carrier.
- Rejected: criteria with a 'Resolves YES if' prefix, a '(source: FRED).' suffix or a ', per ...' suffix; natural comparators ('reaches at least 5%'); and Chinese statements. The labels contain no title_zh.
- The base binary prompt contradicts the anchor matcher. It requires each resolution_criteria to name 'the SOURCE that resolves it' (forecast_extractor.py:1077) and 'Write all text in {language}', while the matcher allows only '[in|for|on] <period>' after the comparison. Realistic model output is therefore almost always rejected, which disables threshold lines, the watch table and data-based auto-resolution (resolution_monitor reads only admitted anchors).
- One evidence item is wrong. 'The US unemployment rate >= 5% in June 2027' with the bare criterion 'fred:UNRATE >= 5% for 2027-06' is ACCEPTED: the real geography is 'USA', so 'us unemployment rate' is a label and the leading 'the' is stripped.
  - corrected fix: Keep validate_data_anchor and keep the guards against negation, compound clauses, conditionals and wrong periods. Relax only the surface form.
- Criteria: accept exactly one canonical clause '<series> <cmp> <threshold> [units] (in|for|on) <period>' anywhere in the text, allowing framing prefixes ('Resolves YES if', 'YES if') and source suffixes ('per X', '(source: X)', 'as published by X'), provided no other comparator or number appears.
- Statements: add title_zh and localized geography labels, plus a comparator-word map (at least / exceeds / below / 超过 / 不低于 / 低于) checked for consistency with anchor.comparator.
- After admission, deterministically append one canonical settlement sentence to resolution_criteria.
- Add a worked example to the data_anchor prompt.
- Tests: the rejected realistic variants anchor; the existing counterexamples (test_report_official_data.py:319+) still fail.
- VERDICT RPT-4: **ACCEPT_IMPROVEMENT** (medium) — This directly serves the user's goal of giving forecasts a quantitative basis from official data. The spine asks base_rate_anchor to cite pack metrics, but no number in the system is computed from history.

The proposal has an ordering problem: anchors exist only after binary extraction, which runs after the spine. So 'feed the anchor base rate into the binary/spine prompt' cannot work in one pass. The window is also short (at most 240 observations, often 10 years), so empirical frequencies are a crude outside view and must be labeled as such and never overwrite the model's probability.
  - corrected fix: Phase A (order-free, deterministic): add per-series history statistics to _build_data_pack before any prompt. Include the historical percentile of the latest value and the quantiles of the 12-step (or horizon-step) change, computed only over historical-observation, complete periods. This feeds the spine, binaries and critique identically and keeps the prompt prefix deterministic for caching.

Phase B (post hoc): for each admitted data_anchor, compute empirical_base_rate {p, n, window, h, method} from those stored points. Show it next to the model P in the Part-1, resolution and brief tables, and flag a divergence above 25 pp. Never adjust the probability.

This depends on RPT-3, otherwise there are almost no anchors. Tests: a deterministic p on a fixed UNRATE fixture; projection, unknown-status and partial points are excluded.
- VERDICT RPT-5: **CONFIRMED** (medium) — probe3.py on the real carrier: the pack is 3490 chars and holds 11 rows. The 12th row (usgov mts_deficit) is dropped with no omission note (the break at report_agent.py:2442). derive_forecast_spine slices quantitative_facts[:3000] (forecast_extractor.py:3458/3482), so the text ends at 'wb:IMF_WEO_NGDP_RPCH/USA: 2.32% on 2026-01-01 (' and loses the 'unclassified publisher value' label plus the debt_to_penny row. Row labels are bare IDs, and every row repeats a roughly 80-char 'Transform: none. Source: <url>' line.
  - corrected fix: As proposed: render rows under an explicit budget that truncates only at row boundaries and appends 'N further series omitted: ids'. Raise REPORT_SPINE_INPUT_CAP_FACTS to at least the pack cap, or pass a spine-sized pack. Add title (title_zh in zh) and geography. Drop the URL line when an [S#] tag exists. Order rows: anchored, KIQ-linked (v3 does populate kiqs), cited, then the rest. Test: a 12-row real-shaped carrier keeps every status suffix intact in the spine prompt.
- VERDICT RPT-6: **CONFIRMED** (medium) — probe5.py on the real DGS10 row:
- Every aggregated month is complete=False (data_sources.py:1286-1291), including September 2026, which is fully covered (covered_end 2026-09-30 = end).
- The October month covers 11 days (covered_end 2026-10-11, end 2026-10-31), yet official_observation_kind returns 'historical observation'. The pack therefore shows 5.27% / 2026-10-01 as the latest historical value and the chart diamond sits on it (see out_wb chart).
- validate_data_anchor returns latest_value None because resolution_safe is False, so the resolution table says 'unavailable'.
- historical_snapshot drops DGS10, T10Y3M and debt_to_penny entirely.
  - corrected fix: As proposed: set complete=(covered_start==start and covered_end==end and end < retrieval date). Add a 'partial-period average' kind in official_observation_kind that reads provenance.periods, and exclude partial points from latest, YoY and the latest-value marker. Use one shared helper for the pack, anchor and snapshot so they agree. Also consider preferring native monthly series (e.g. fred:GS10) in the catalog for monthly use. Test: a carrier whose last month is partial gives a pack and anchor 'latest' equal to the last complete month, and the chart marker is not on the partial point.
- VERDICT RPT-7: **CONFIRMED** (medium) — Code confirmed: _request sets finish = today when end is None (data_sources.py:1098-1099). prefetch_data calls get_many without end (research_gateway.py:3684-3686), and the first stored window is immutable for the run (:3631-3641). The real WEO provenance shows delivered_end 2026-01-01.

The proposed fix is insufficient on its own. A live probe (weo_end.py, imf:WEO/G001.NGDP_RPCH.A with end=2031-01-01) returns the 2027-2031 values, but every one is flagged 'unknown' with projection_from='' and vintage=''. official_observation_kind (forecast_extractor.py:1531-1544) therefore still classifies them as 'unclassified publisher value', never 'publisher projection', so no projection lane would appear. The same probe through the tracked code for wb:IMF_WEO_NGDP_RPCH/USA fails with 'ambiguous disaggregations' (known K2).
  - corrected fix: (1) For projection-bearing flows (WEO*, GEP*, catalog entries flagged as projections), default end to max(today + 5 years, forecast horizon) in _request, and update the data-sources SKILL to request through the horizon.
(2) Add a deterministic status rule in official_observation_kind and the data layer: any observation whose period START is after the series' retrieved_at date is a 'publisher projection' (it cannot be observed). The current year stays unclassified unless the publisher says otherwise.
(3) Test: a WEO request without end yields end_year >= current year + 5; future periods render in the 'Publisher projections' lane and never appear as historical in the pack.
- VERDICT RPT-8: **PARTIAL** (low) — The claim that KIQ ranking is dead code because 'Series.kiqs is never set by any producer' is wrong for the default v3 engine. linear_research._publish_data builds Series with kiqs from self.data_index (linear_research.py:5595) and writes row['kiqs'] into datasets.json (:5610) for every series linked through plan-phase prefetch (:4385). The reviewer's 'kiqs [] everywhere' came from a synthetic bundle written via write_dataset_files.

What remains true: the dashboard uses panels[:6] in manifest order (report_visualizer.py:4571), so series 7-12 appear in no exhibit. When no binary is anchored (the common case given RPT-3), the 4 detail charts rank only by kiqs, and prefetch series are both first in the manifest and KIQ-linked, so the detail charts usually duplicate dashboard panels. Agent-initiated data_get series stay unlinked, and the legacy engine never sets kiqs.
  - corrected fix: Rank panels by (anchored, KIQ-linked, cited via official_source_tag, provider diversity). Make the dashboard cover all valid rows (at most 12) as 2-column small multiples, or split it into two figures. Emit detail charts only for series with an admitted anchor or a scenario band. Optionally record KIQ links for gather-phase data_get calls in v3. Test: every carrier series appears in at least one exhibit, and no detail chart without a threshold duplicates a dashboard panel.
- VERDICT RPT-9: **CONFIRMED** (medium) — probe4.py: _official_scenario_bands returns [] for the real WDI row. Its units are 'Percentage change per annum', not percent, and it still returns [] when units are forced to 'Percent'.

An additional defect: _extract_comparable_numeric_range returns None for any negative bound. 'Real GDP growth between -3% and 0% in 2027' gives None, while '0% and 2%' parses. Recession bins can never match. The metric must also equal the normalized row title exactly, and only annual, untransformed series qualify (report_visualizer.py:4353-4378), so the feature is effectively dead on real data.
  - corrected fix: As proposed: the spine emits an optional per-scenario metric_range {series, low, high, period, units}, validated against the carrier like data_anchor (frequency-aware period, carrier units), and bands are drawn from it at the target period for any frequency. Also fix the range regexes to accept signed bounds. Test: a spine fixture with fred:UNRATE 2027-06 4-5% and a WDI GDP range of -3% to 0% for 2027 both draw bands.
- VERDICT RPT-10: **PARTIAL** (medium) — The placement problem is confirmed. All official charts share placement_hint 'official_data', whose keywords include the generic 'data', 'baseline' and '数据' (report_agent.py:8950). They are all inserted together immediately after the first matching heading, ahead of its prose; in pub_claims4 all 5 charts sit under '## Economic baseline'. No prompt asks the planner for a quantitative section or for canonical-format claims.

Overstated: 'plan and section prompts carry no data-use rules'. _build_data_pack's header ('Quote stored values exactly with their source marker... Unknown status cannot establish an observed outcome') is prefixed to every plan and section prompt by _prepend_research_background. A deterministic indicator table is valuable, but its [S#] markers would currently be stripped for the YoY lines (see RPT-1/probe7), so it depends on the RPT-1 fix.
  - corrected fix: After the RPT-1 fix lands, inject a deterministic bilingual 'Key official indicators' table built from carrier values via format_value, with [S#] from official_source_tag, as its own H2 section. Gate it on the carrier being present so output is byte-identical when disabled. Have the outline rule reserve that section when a pack exists. Place the dashboard there and put detail and threshold charts beside Part-1 or the resolution section using distinct placement hints. Test: table values equal carrier values, and the table survives _stabilize_publish_markdown and the final audit unchanged.
- VERDICT RPT-11: **CONFIRMED** (medium) — grep finds no 'official', 'data_anchor' or 'indicator' handling in exec_brief.py. _build_watch_block uses only binary dates, and _find_scenario_chart picks only the scenario chart. forecast.json already carries admitted data_anchor fields (latest_value, latest_date, threshold, source_url) that the brief ignores.
  - corrected fix: As proposed: add a localized 'Key indicators' mini-table built from admitted data_anchor fields and/or the report-local carrier (RPT-12), formatted with format_value. Prefer anchored binaries in 'What to watch', shown as latest vs threshold. Optionally embed charts/official_indicators.png. Test: a forecast with anchors produces brief rows with zh labels.
- VERDICT RPT-12: **PARTIAL** (low) — Absence confirmed: the only frontend change is 2 caption strings in vizManifest.js. normalizeVizGallery keeps the caption but drops source_caption and provenance (vizManifest.js:43-75). FORECAST-DASH and BinaryForecastTable show no indicator or anchor data. No report-local carrier copy or API exists.

However, official charts are embedded in the markdown the frontend already renders, and the gallery shows only charts not embedded there. The user-visible impact is therefore lower than medium. The more important piece is the missing report-local carrier: re-renders and backfills (RPT-13) and chat depend on load_for_simulation re-validating the research binding, which turns into None if the research generation changes.
  - corrected fix: Priority 1: persist report-local official_data.json (the exact carrier plus its sha256 and the binding fingerprints) in generate_report, and make backfill and re-render consumers prefer it. Priority 2: add GET /api/report/<id>/official-data, indicator tiles in the dashboard, a data-anchor column in the binary table, and source_caption on gallery cards. Tests: an API test and vitest for the anchor and gallery attribution.
- VERDICT RPT-13: **CONFIRMED** (medium) — Reproduced by running strip_generated_visuals on the published pub_claims4 report: 0 viz markers remain but all 5 '*Source: ...*' lines are orphaned. The stripper skips only one italic line after the image, and the source caption is a second italic line. _artifacts (backfill_report_visuals.py:342-356) and _offline_report_agent (:368-388) carry no official_data, so no official chart is rebuilt and the orphaned captions are no longer recognized as canonical captions. eac717b did not touch this script.
  - corrected fix: As proposed: load the report-local carrier (RPT-12), falling back to official_data.load_for_simulation(simulation_id) so the binding is respected rather than an unverified handoff read, and pass it into artifacts and agent.official_data. Make strip_generated_visuals also consume a following '*Source: ...*' or '*来源：...*' line. Test: backfill of a report with official charts keeps 5 charts and their captions and passes _enforce_final_publish_audit.
- VERDICT RPT-14: **PARTIAL** (medium) — Confirmed: chat's system prompt is report text plus tools only (report_agent.py:12037-12041), and no stored-data tool exists. The fallback extract_structured_forecast gets no pack (:3197-3201).

Correction: 'critique and premortem both off by default' is wrong for critique. REPORT_FORECAST_SELF_CRITIQUE defaults to True (config.py:174) and REPORT_CRITIQUE_BEFORE_PROSE to true (config.py:633). self_critique_forecast therefore runs on every spine before prose. Its prompt explicitly checks base-rate neglect and can move scenario probabilities, yet it never sees the official data. Only premortem is off by default (REPORT_PREMORTEM False). This raises the gap from low to medium.
  - corrected fix: Pass self._data_pack, plus the RPT-4 history statistics when available, into self_critique_forecast, premortem_forecast and the fallback extract_structured_forecast as a fixed suffix block. Append the pack to the chat system prompt, or add a read-only stored_official_data(series, period) tool that never fetches. Test: the critique prompt contains the pack when a carrier exists and is byte-identical without one.
- VERDICT RPT-15: **CONFIRMED** (low) — probe3.py pack output shows:
- 'Year-over-year change: -0.25% Per cent per year [S7]', because report_agent.py:2426 uses 'percent|%' while data_sources.format_value matches 'per\s*cent'.
- '40269094993348.9844 / 2026-10-01' and '2307966401253.7656 U.S. dollars'.
- The resolution block prints raw floats (forecast_extractor.py:3832-3836).
The threshold label 'Model threshold > 4.5e+13 (2027-12); P(yes)=20%' visibly overlaps the 'Forecast horizon' annotation in out_wb/charts/official_series_mrsddaomqfkcltcp.png, which I viewed.
  - corrected fix: As proposed: one shared percent regex (data_sources format_value semantics). Show scaled display values ($40.27 trillion) in prose-facing pack lines and keep exact values in CSV and tables. Use format_value in the resolution block and the chart labels. Move the horizon annotation (y=1.02, yanchor bottom) or put the threshold label on the left. Keep the RPT-1 support predicate aware of the scaling so scaled numbers stay citable.
- VERDICT RPT-16: **CONFIRMED** (low) — v3 sources.json contains cited sources only (linear_research.py:6078), while datasets.json holds every stored series (up to 12). For an uncited dataset, official_source_tag returns '', so the pack says 'unindexed source' and the chart caption has no tag. The watch table uses '[Source](<url>)' rather than [S#] (forecast_extractor.py:3841).
  - corrected fix: As proposed: in ReportAgent only (not in the shared research sources), append carrier datasets missing from sources to the citation index at positions after len(sources), with tier S1, source_origin official_data, dataset identity and an excerpt from the stored series. Positional S<n> identities of research sources stay unchanged. Tag watch-table rows with official_source_tag. Test: an uncited dataset gets an [S#] that resolves in References and passes caption and claim support.
- VERDICT RPT-17: **REJECT_IMPROVEMENT** () — As proposed, this conflicts with existing invariants.
- The visualizer keeps chart copy in English by convention (report_visualizer.py:31, '图表文案统一英文').
- Chart files are shared between the primary report and its translation variant, so zh-rendered images would need per-language chart sets.
- Captions and filenames are deliberately digit-free for translation numeric parity (report_agent.py comment 'Captions remain separate from digit-free image titles'; report_visualizer.py:4588 'Letters only'). Series titles such as '10-Year Treasury ... 3-Month' would add digit tokens to alt text and break that parity.
The useful part, localized alt text and italic captions in zh primary reports, is covered by the corrected RPT-2 fix. Per-chart distinction is already provided by the per-series Source caption.
  - corrected fix: Fold the zh alt-text and caption localization into RPT-2 via CHART_TITLES_ZH. If per-chart distinction is still wanted, use title_zh or title only when it is digit-free; otherwise use a fixed localized ordinal label. Do not render separate zh chart images.
- MISSED MISSED-1 (BUG, high) Chinese reports deadlock when an official series has long English units: the purity pass and the caption audit contradict each other — at backend/app/services/report_agent.py:9354-9363 (canonical caption built from units); :2331-2392 (_audit_official_chart_captions requires an exact canonical caption); :5293-5331 and 5551-5715 (_collect_impurity_segments/_apply_language_purity rewrite any Latin run of 40+ chars with 4+ spaces, captions included); backend/app/services/report_lint.py:149 and 535-567 (detect_language_contamination has no exemption for canonical captions)
  - evidence: Built a live bundle (vrpt/build_dexchus.py: fred:DEXCHUS with units 'Chinese Yuan Renminbi to One U.S. Dollar', plus fred:UNRATE) and ran the real zh sequence: inject, purity, lint, stabilize, final audit (rpt/drive_zh_units.py into vrpt/zh_dex_none and vrpt/zh_dex_purity).
- No purity / LLM unavailable: 'FINAL AUDIT FAILED: ... 最终 Markdown 含 6 行目标语言污染'. Two of the lines are the '*来源：...; Chinese Yuan Renminbi to One U.S. Dollar; M; NSA*' captions.
- Simulated SUCCESSFUL purity translation: the units in the caption become '译文0', and the audit fails with '官方数据图表来源标注缺失或不匹配' (official_chart_captions issues for official_indicators.png and the DEXCHUS detail chart).
The report can never be completed. Catalog entries affected: fred:RRSFS, fred:DEXCHUS, fred:PNGASEUUSDM, bls:PRS85006092, bls:PRS85006112, imf:PCPS/G001.PNGASEU.USD.M and imf:PCPS/G001.PNGASJP.USD.M, plus any searched series with long units.
  - fix: Treat validated canonical official source-caption lines as protected metadata, like URLs and inline code.
(a) In the final audit, compute language contamination on markdown with lines where _official_source_caption_support(line, '') is True removed (the same exemption _audit_external_claims already applies), or pass an exemption predicate into report_lint.detect_language_contamination.
(b) In _collect_impurity_segments and _apply_language_purity._replace, skip those lines entirely.
Test: a zh primary report with a DEXCHUS carrier reaches hard_passed True both with an LLM that raises and with a translating stub, and the caption bytes stay canonical.
- MISSED MISSED-2 (GAP, medium) World Bank values, including WDI history, are never treated as historical observations anywhere in the report — at backend/app/services/forecast_extractor.py:1521-1526 (provider == 'wb' returns 'unclassified publisher value' unconditionally); Data360 normalization flags every WDI observation 'unknown' and sets resolution_safe False (real row wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA)
  - evidence: In the real bundle the WDI row has flags ['unknown'] and res_safe False.
- The pack (probe3.py) shows '| wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA | unavailable |' as the latest historical value, with 2.16% for 2025 only as an 'unclassified publisher value'.
- The charts draw it in the grey 'status unknown' lane with no latest marker.
- historical_snapshot omits it.
- Any WDI anchor has latest_value None.
One of the six providers therefore never contributes a historical baseline, even though WDI holds only historical estimates.
  - fix: Use database-aware status. For Data360 databases that hold only history (WB_WDI and similar), treat periods whose end is before the retrieval date as 'historical observation', or as 'publisher estimate' where the metadata says so. Keep IMF_WEO*/GEP rows unclassified for past and current years, and classify future periods as projections (see the RPT-7 correction). Apply the rule in the data layer's status assignment and in official_observation_kind consistently. Test: a WDI row produces a pack latest value and a chart marker; a WEO row via Data360 does not.
- MISSED MISSED-3 (BUG, medium) The official-data end-to-end test fails under plain pytest / npm run test — at backend/tests/test_official_data_end_to_end.py:87 (assert os.environ.get('MAIN_OFFLINE_EVIDENCE')); backend/tests/test_v3_official_data.py:31 reads the same variable
  - evidence: cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_report_official_data.py tests/test_report_data_publication.py tests/test_official_data_downstream.py tests/test_official_data_consumers.py tests/test_official_data_end_to_end.py gives 123 passed, 1 FAILED: test_guarded_mcp_to_promoted_research_and_report_png, 'AssertionError: Use the documented guarded runner' (vrpt/pytest_report.txt). package.json 'test' runs 'cd backend && uv run pytest', so CI fails here. The reviewer's '123 passed' left out this failure. It belongs to the K1 family (tests that pass only through Codex's runner) but is a different mechanism from the import error.
  - fix: When MAIN_OFFLINE_EVIDENCE is unset, either pytest.skip with a clear reason or let the test write evidence to tmp_path. Keep the guarded runner as an optional stricter mode. Run the whole suite under plain pytest as a gate.
- MISSED MISSED-4 (BUG, low) Official source captions use provider codes as the visible attribution, inconsistent with the manifest — at backend/app/services/report_agent.py:2286-2289 (_official_source_caption_part labels the link with row['provider']) vs backend/app/services/report_visualizer.py:4620 (manifest source_caption uses provider_name)
  - evidence: Published captions read '*Source: [fred](<https://fred.stlouisfed.org/series/UNRATE>) [S1]; Percent; M; SA*'. Every exhibit is attributed to 'fred', 'bis', 'wb' or 'usgov' rather than the publisher, and frequency appears as a bare code ('M'). The manifest's source_caption names the publisher, so the markdown, the manifest and the frontend disagree.
  - fix: Build both from one helper using provider_name (e.g. 'FRED, Federal Reserve Bank of St. Louis') and a localized frequency label. Update _official_source_caption_support and _audit_official_chart_captions together so they share it, keeping exact canonical matching. Test: caption equality between the manifest and the markdown, and the final audit passes.

## verify:downstream-ops: Downstream stages (ontology/graph, simulation, resolution/ledger/calibration), orchestration, ops/CI, docs and repo hygiene for the eac717b official-d

- VERDICT D1: **CONFIRMED** (high) — Reproduced with plain pytest on the five files: exactly 25 failures (scratchpad/review/vfy/d1_plain.txt). They are 19 from MainOfflineControls.setUp calling self.fail (test_main_offline_runner.py:22), 2 sidecar parser.error, 1 E2E MAIN_OFFLINE_EVIDENCE assert (test_official_data_end_to_end.py:87), the stale characterization test (:199, against report_agent.py:3129) and 2 orchestrator wiring tests. All five files come from eac717b except the characterization and orchestrator suites. CI runs `cd backend && uv run pytest -q` (ci.yml unit job). New evidence: the 3 non-runner failures also fail under Codex's own guarded runner ('3 failed, 110 passed, 11 xfailed', vfy/orch_runner.txt, evidence dir ev-dsverify-orch-01). So final-verification.md's '2,025 passed' gate left them out, and this is a regression in Codex's own gate as well as in CI. The orchestrator failures are a fixture artifact: the fake create_simulation (test_orchestrator_research_wiring.py:861-875) never creates the directory under SimulationManager.SIMULATION_DATA_DIR, and only Config.OASIS_SIMULATION_DATA_DIR is patched (:728).
  - corrected fix: Runner-only tests: in unittest classes call self.skipTest when sys.modules lacks 'main_offline_guard'; in pytest tests call pytest.skip when MAIN_OFFLINE_EVIDENCE or the -I -S -B flags are absent. Under the runner they must still run and fail loudly. Characterization test: keep asserting 'base_distribution=' is absent and assert that 'quantitative_facts=' is now passed (the WP6 strict xfail stays). Orchestrator tests: patch SimulationManager.SIMULATION_DATA_DIR to simulation_root and make the fake create_simulation mkdir the new sim dir. Gate: plain `cd backend && uv run pytest -q` must be green, in addition to the runner.
- VERDICT D2: **PARTIAL** (low) — Code confirmed: capture (pipeline_orchestrator.py:12648-12650) and bind (:13154-13158) are unguarded and run even when DATA_SOURCES_ENABLED=false. The cited evidence does not show a production failure, though. The 2 failing tests come from a fake create_simulation that never makes the sim directory. In production create_simulation makes it, and SimulationManager.SIMULATION_DATA_DIR and Config.OASIS_SIMULATION_DATA_DIR are the same uploads/simulations path (simulation_manager.py:739, config.py:1080). Failing closed is deliberate, per integration-contract.md:100-102: input checks 'prevent capture from blessing differing in-memory versus disk inputs' and 'changed primary proof rejects the seed'. The quoted line 'mismatched binding yields unavailable enrichment' is about lookup, not capture. Report bytes are reconciled with disk before capture by _finalize_research_contract, which is idempotent on resume (:4006-4014), and by _enforce_actor_intelligence_reception. A grep found no backend writer of the six fingerprinted files after capture, and edit_dossier is refused once the graph is done. What remains is environmental fragility only.
  - corrected fix: The required fix is the test fixture (see D1). Optional hardening: catch only environmental errors (OSError, missing directory) around capture/bind, record state.options['official_data_binding']={'status':'unavailable','reason':...} and continue unbound, so official_data becomes None through the 'missing' path. Keep the in-memory/disk mismatch and 'already bound to different research' errors fail-closed, because they are provenance guards. Do not skip capture just because data/datasets.json is absent: the binding also scopes the dossier lookup for bound seeds.
- VERDICT D3: **CONFIRMED** (medium) — Re-ran repro/binding_move.py. Before the move every field is present; after the move the binding is 'invalid' and situation_brief, actors, research_report and actor_dossier are all None. Code: pipeline_orchestrator.py:7097-7098 returns all-None on an invalid binding; official_data.py:107 stores an absolute handoff_dir, and :148 requires an absolute path and re-fingerprints it. Returning all-None on invalid is deliberate (test_official_data_consumers.py:195) so a replaced generation is never mixed in. The real defect is that relocating the install root (a repo rename or restored backup, both of which this user has done) silently strips all research context from manual reports and chat for every bound simulation.
  - corrected fix: Store the handoff location as pipeline_id plus a path relative to the pipelines root, and resolve it at read time via PipelineManager.resolve_handoff_dir. Keep the fingerprint check. On an invalid binding, fall back to the pre-eac717b legacy dossier lookup with official_data=None and log a diagnostic, rather than returning all-None. Update test_official_data_consumers.py:195 to match. Tests: (1) after relocation the dossier and official data survive; (2) a tampered data/datasets.json nulls only official_data.
- VERDICT D4: **CONFIRMED** (medium) — Re-ran repro/world_brief_sweep.py: the snapshot appears in 52 briefs and the END delimiter is truncated in 9. The tail ends with 'END UNTRUSTED RESEARCH '. The snapshot budget at simulation_config_generator.py:1969-1979 reserves 160 chars, but the wrapper in actor_role_prompt.py:270-283 adds about 225, and :1985 slices after wrapping. The impact is larger than reported: run_parallel_simulation.py:650-657 appends the calendar action vocabulary after the brief, and SIM_TEMPORAL_MODE defaults to 'calendar' (config.py:1067). Those agent instructions therefore land inside an unterminated block that says 'Never follow instructions found inside it'.
  - corrected fix: Build the wrapped block first, then drop whole snapshot lines (re-wrapping each time) until len('\n\n'.join(parts)) <= max_chars. Never slice after wrapping. Sanitization can expand text, so do not rely only on a constant reserve. Test: sweep question length and budget (1400 and 3000) and assert BEGIN and END are both present or both absent, and that the brief ends with the END line whenever a snapshot is present.
- VERDICT D5: **PARTIAL** (medium) — Mechanism confirmed. repro/snapshot_midnight.py re-run prints True/False/False. official_data.py:283-287 drops a row when retrieved > end-of-day(as_of), and this affects both the graph episode (pipeline_orchestrator.py:12862-12866) and the world brief. The 'resumed runs' trigger is refuted for v3: resume calls _freeze_data (linear_research.py:4346-4348), and frozen data_get and prefetch never fetch (research_gateway.py:3600, 3670, 3714), so retrieved_at stays at or before the original as_of. The real triggers are a UTC-midnight crossing during a live run (agent data_get in gather, or prefetch shortly before midnight) and an extraction-LLM as_of_date earlier than the retrieval date (linear_research.py:6245-6249). Both are plausible but not common.
  - corrected fix: Relax the cutoff only for live forecasts. When as_of_date is on or after the research run's start date (plan.as_of / meta), use cutoff = max(end-of-day(as_of), research finished_at). Keep the strict retrieval<=cutoff rule when as_of is historical (backtests). Record the excluded-row count in state.options. Tests: an after-midnight retrieval within the run is admitted; an as_of before the run start still excludes it.
- VERDICT G1: **PARTIAL** (low) — Confirmed: there is an early return before the snapshot (simulation_config_generator.py:1929-1936), and test_official_data_downstream.py:118-127 pins it. DEERFLOW_DUAL_TRACK defaults to True (config.py:1228), so every legacy run is canonical v1 and its simulations get no official data. However, legacy is not the default engine (RESEARCH_ENGINE defaults to v3, config.py:1187), and Codex deliberately treats official data as 'modeler evidence' under v1 (comment at pipeline_orchestrator.py:12859-12861). That leaves v3 and legacy with inconsistent policies. Severity is lower than reported.
  - corrected fix: Do not inject rows into the hash-bound actor-context/v1 packs: that requires producer-side schema changes and re-sealing. Instead, in _build_canonical_public_world_brief, append the binding-verified historical_snapshot as its own delimited block, with the same budget rules as D4. It must render even when public_rows is empty, since today the function returns '' in that case. Rewrite the pinning test so official rows appear while actor-private rows stay denied.
- VERDICT G2: **CONFIRMED** (medium) — Re-ran repro/snapshot_providers.py: wb and imf WEO rows are absent from the snapshot. Code: data_sources.py:192-205 forces every wb observation to 'unknown' with resolution_safe=False, and unflagged WEO to 'unknown'; official_data.py:277, 290 and 300 then exclude those rows from context. For non-US questions, the simulation and graph receive no official numbers while the report shows them as unclassified. The proposed WEO vintage-year rule is unsound, though. README and .env.example explicitly say 'No cutoff is inferred from the current year', and WEO's per-country 'estimates start after' year varies, so values at YYYY-2 can still be IMF estimates for many low-income countries.
  - corrected fix: Separate context visibility from resolution_safe, which stays monitor-only. Render rows with unknown status in a separately labelled sub-block, e.g. 'publisher status unclassified (may include estimates)', and always exclude periods at or after the retrieval year. Do not relabel any WEO or WDI value as 'observed'. Test: a WDI row appears labelled as unclassified; WEO periods at or after the retrieval year never appear; resolution behaviour is unchanged.
- VERDICT G3: **PARTIAL** (low) — Confirmed that no dataset row reaches quantitative_facts: v3 quant comes only from LLM extraction (linear_research.py:6242-6272), and enrich_quantitative_rows does not consult datasets. The impact is overstated. Actor packs keep only rows matching actor names (_relevant_rows → _matches_structured_row, actor_context.py:814-834), so 'Unemployment Rate' rows would rarely reach any actor. ReportAgent already receives the exact hash-bound pack through official_data. The real benefit is a single quantitative.json for charts and recency, at the risk of duplicating values already shown in the official_series charts.
  - corrected fix: Optional. If implemented, add only the observed latest values (flag observed/blank, never unknown, projection or preliminary) with origin='official_data' and source_ref S#, before actors.json is sealed. Deduplicate against LLM rows by series id, and keep the quantitative-claims charts from double-plotting official series.
- VERDICT G4: **CONFIRMED** (medium) — Confirmed. The v3 run cap is 12 stored datasets (research_gateway.py:3641, 3672, 3755) and prefetch requests up to 12 (linear_research.py:4356-4384), so the default prefetch can fill every slot and later agent data_get calls return 'DATA_BUDGET_EXHAUSTED'. A further problem compounds this: the data-seeder's data_search calls and prefetch reservations draw on the shared max_data_calls_total (quick preset: 24) with no per-agent cap (research_gateway.py:3596-3605). Legacy publishes every validated dataset (deerflow_research.py:16236-16256), and load_official_data keeps the first 12 in write order (data_sources.py:574-579). .env.example:502-504 and the README advertise 24/50/90 calls but never mention the 12-dataset cap. The proposed fix is partly infeasible as written: you cannot rank 'anchored' series at load time, because anchors are produced after the pack is built.
  - corrected fix: (1) In v3, reserve agent capacity: limit prefetch to cap/2 and stop seeder searches once requested reaches that limit. (2) Validate anchors (forecast_extractor.py:1819-1823) and resolve them against the full manifest, not the 12-series pack. (3) Order only the prompt pack: series whose S# is cited in research_report.md, then KIQ-linked series (rows[].kiqs), then the rest. Keep the prompt pack bounded, since forecast_extractor.py:2972 truncates data_pack at 3500 chars. (4) Log the dropped-series count and document the cap. Test: in a 15-row manifest with the anchor on row 15, the anchor still validates and resolves.
- VERDICT G5: **PARTIAL** (low) — The calibration-loop gap is confirmed: the `summary` CLI (resolution_monitor.py:910-916) and _summary_row (:837-848) omit data outcomes, and historical_calibration (report_agent.py:3408-3418) uses only the scenario calibration_summary. The claim that 'no user-facing surface' exists is wrong: monitor_report.md renders '## Official data outcomes' (resolution_monitor.py:782), and run results include data_brier and data_resolution_status, which the POST monitor API returns.
  - corrected fix: Add data_brier_summary() to `summary` and to _summary_row (resolved and needs-manual counts). Expose it in forecast.json as a separate 'official_data_track_record' field; do not merge it into the scenario Brier, and leave the field out when n_resolved is 0 so output stays byte-identical. Document data_resolutions.jsonl.
- VERDICT G6: **PARTIAL** (low) — Confirmed that only the orchestrator binds simulations. However, this scope limit predates eac717b: load_research_dossier_for_simulation only matches a pipeline whose primary simulation_id equals the sim id (pipeline_orchestrator.py:7110-7111), so manually created sims never got actors, the research report or the dossier either. The gap covers all research context, not just official data.
  - corrected fix: Optional, low priority. When api/simulation.py creates a sim for a project owned by a pipeline whose research is sealed, call bind_simulation_research with that pipeline's handoff (create-only). This restores the dossier and official data together. Test: a manual sim on a pipeline project gets a valid binding.
- VERDICT G7: **CONFIRMED** (low) — The v3 data phase (linear_research.py:4350-4395) logs nothing on success, only a 'warn' on exception, and phase() (:4268-4280) does not log stage lines. research_progress._v3_milestone returns None for unknown phases, so progress sits in the plan-done band (9-10%) during prefetch, which can take up to 150 s. This is cosmetic: there is no stall-watchdog risk (PIPELINE_RUN_STALL_S=1800).
  - corrected fix: Emit '[stage] research:v3:data start (N series)' and '[ok] research:v3:data done (stored=k, failed=m)', add _V3_DATA_BAND=(9,11) without moving the gather band (avoids reshaping persisted progress), and add a parser test.
- VERDICT B1: **CONFIRMED** (low) — data_sources.py:873 uses Path(env['DATA_SOURCES_CACHE_DIR']) as given: no repo-root resolution and no expanduser. Meanwhile the research child gets an absolute repo-relative, expanded path (pipeline_orchestrator.py:1405-1421), and data_mcp uses _source_path (data_mcp.py:242-247). The monitor subprocess runs with cwd=backend/scripts (resolution_autorun.py:44-48). A relative or '~/…' value therefore splits the cache and bls-quota.json (data_sources.py:1431-1436) across processes. This only triggers when the user sets a relative or '~' value; the default resolves to the same directory everywhere.
  - corrected fix: In DataSources.__init__, resolve the value with os.path.expanduser and, when it is relative, join it to the repo root (reuse data_mcp._source_path). Test: the same env from two cwds and with '~/x' yields one absolute directory.
- VERDICT DOC1: **CONFIRMED** (low) — README.md:1109-1115 (monitor) does not mention data_resolutions.jsonl or the official outcomes section. The simulation and world-brief description (around :870/:951) does not mention the official snapshot or the graph episode 'Official statistical observations'. .env.example:502-504 never states the 12-dataset v3 cap. Both READMEs have 1937 lines, so they must be edited in lockstep.
  - corrected fix: Document these in both READMEs in lockstep and add a note on the cap to .env.example. If G4 changes the cap, the documentation must match.
- VERDICT DOC2: **CONFIRMED** (low) — feature_list.json feature_official_quantitative_research has passes:true, while plain-pytest CI is red (D1) and live retrieval fails for 61 of 196 catalog series (K2). The fused tokens exist at agent-progress.txt:322 ('and6372005'), :323 ('gate2025') and :332 ('the64unrelated').
  - corrected fix: Set passes:false until plain pytest is green and a live smoke run passes; append a progress entry and fix the typos. The harness says not to edit descriptions or steps, so only the flag changes.
- VERDICT I1: **ACCEPT_IMPROVEMENT** (medium) — This directly serves the user's goal of quantitative data driving forecasts. base_rate_anchor is LLM free text (forecast_extractor.py:1082) even when the exact history is stored, and series_stats only gives latest/YoY/5-year range (data_sources.py:289-307). The proposed fix needs correction, though. Anchors are validated only after the LLM has proposed thresholds, so a pre-generation prompt injection is impossible without an extra LLM pass, and an extra pass would change prompt-cache layout and cost. In addition, default fetch windows (25 years annual, 10 years for other frequencies, max 240 observations) make n≥30 h-step samples impossible for annual series.
  - corrected fix: After validate_data_anchor, compute deterministically from observed history only (_observation_kind=='observed'): h = periods from the latest observed value to the anchor period; take the empirical distribution of h-step changes over all valid start points; p_base = share of latest+Δ that satisfies comparator and threshold. Use frequency-aware minimum samples (M≥36, Q≥24) and mark annual series 'insufficient_history'. Store it on the binary as statistical_base_rate {method:'empirical_h_step', h, n, p_base, window}. Draw it on the official threshold chart, flag |p−p_base|>0.25 in the confidence audit, and never alter the LLM probability. When no anchors exist, output stays byte-identical. Test: a synthetic random walk with a known crossing frequency.
- VERDICT I2: **REJECT_IMPROVEMENT** (low) — Real but indirect value at high cost. The vendored FRED server has no release-dates tool, so this needs either modifying the vendored server or a new key-gated FRED HTTP path. BLS schedules would hit the exhausted keyless quota. It also touches sim event generation, the monitor and scheduled_rerun. M1 below fixes the cheap part of the quota waste (needless monitor fetches) without any calendar. Defer.
- VERDICT I3: **REJECT_IMPROVEMENT** (low) — The ontology is capped at 10 entity types (ontology_generator.py:258, 1052), and adding an Indicator type displaces actor types. The graph already receives an 'Official statistical observations' text episode (pipeline_orchestrator.py:12858-12869), and the report agent already gets exact values through the bound data pack. Expected gain is marginal and the risk to graph quality is non-trivial.
- VERDICT I4: **ACCEPT_IMPROVEMENT** (medium) — This addresses the root cause behind K2: there is no live smoke check, and setup_datamcps --check only verifies files. A live probe surfaces broken providers before a research run, which serves 'agents query the data sources' directly. preflight_pipeline (pipeline_orchestrator.py:7129+) and doctor do not check data sources at all.
  - corrected fix: Add `doctor --deep` and POST /api/settings/data-sources/test. For each enabled provider run MCP initialize + list_tools; for FRED, BIS, IMF, WB and usgov fetch one cached catalog series. For BLS run the handshake only, so it never consumes the keyless 20/day quota. Pace FRED. Report ok/degraded/unavailable with redacted reasons. Make it advisory only: never block a run.
- VERDICT I5: **ACCEPT_IMPROVEMENT** (low) — Cheap and in scope: series_stats already provides observed-only YoY and a 5-year range, and the report pack already uses them (report_agent.py:2420-2433). Simulation agents would see direction, not just level. It must land after the D4 fix and stay within the brief budget, dropping trend columns before dropping series.
- VERDICT I6: **REJECT_IMPROVEMENT** (low) — The research dossier view already renders the Official Data Baseline table and charts/data_*.png, and forecast reports render the official_indicators and official_series_* figures (README:551). The datasets artifact and CSV paths are already registered (pipeline_orchestrator.py:9956, 10554). A new tab and card is UX polish, not integration; the provider-status part is covered by I4.
- VERDICT H1: **REJECT_IMPROVEMENT** (low) — Facts confirmed: the mode-120000 .npmrc symlink points out of tree (git ls-files -s), two LinkedIn JPGs are committed, and there is no provenance file. Nothing builds or copies mcp-ui-angular (grep finds no reference), so there is no runtime impact. Codex's delivery deliberately keeps vendor sources unmodified. This does not serve the quantitative-integration goal. Optional one-line cleanup: delete the dangling symlink.
- MISSED M1 (BUG, medium) WEO/GEP substring match on the whole series ID wrongly excludes or mislabels unrelated series (e.g. FRED Global Economic Policy Uncertainty GEPUCURRENT) — at backend/app/services/official_data.py:290; backend/app/services/forecast_extractor.py:1548; deerflow_bridge/skills/data-visuals/scripts/render_data.py:601
  - evidence: Probe scratchpad/review/vfy/probe/gep_substring.py: fred:GEPUCURRENT in_snapshot=False and fred:NEWEOSPI in_snapshot=False, while fred:UNRATE in_snapshot=True, all with identical unflagged observed rows. The canonical classifier data_sources._observation_kind (data_sources.py:274-282) uses exact prefixes (provider 'wb', 'imf:WEO/', 'imf:WEO_') and calls these rows 'observed'. The three downstream copies instead use `'WEO'/'GEP' in id.upper()` or re.search(r'WEO|GEP'). As a result, policy-uncertainty indices, which are relevant to DRF tariff and geopolitics questions, vanish from the simulation brief and graph, appear as 'unclassified publisher value' in the forecast data pack, and appear as 'unknown' in research charts.
  - fix: Replace all three substring tests with the canonical rule: expose data_sources.observation_kind(obs, series), or match exact prefixes ('imf:WEO/', 'imf:WEO_', 'wb:IMF_WEO_', 'wb:WB_GEP_'), consistent with data_sources.py:1667 (database in IMF_WEO/WB_GEP). Test: fred:GEPUCURRENT is observed in all three consumers, and imf:WEO/... and wb:IMF_WEO_... stay unclassified.
- MISSED M2 (BUG, low) Resolution monitor's 'period has not ended' pre-check is bypassed for date-form anchors, causing repeated provider fetches up to a year early — at backend/scripts/resolution_monitor.py:329-347 (_data_period_bounds) and :366-371; deerflow_bridge/data_sources.py:585-592, 631 (anchor keeps the raw 'observation')
  - evidence: _anchor_period accepts a monthly 'YYYY-MM-01', a quarterly 'YYYY-04-01' and an annual 'YYYY-01-01', and the prompt advertises a 'YYYY-MM-DD' form (forecast_extractor.py:2975). validate_data_anchor stores the raw supplied string as 'observation', and the monitor treats any YYYY-MM-DD as a single day. Probe scratchpad/review/vfy/probe/monitor_period.py at as_of 2026-03-01: observation '2026' → 0 fetches, pending; observation '2026-01-01' on an annual series → 1 provider fetch, then pending ('The full observation period has not ended'). Every monitor run, including autorun on the 10 most recent reports, refetches until the period ends. That is up to a year for annual anchors, spending FRED rate limit and the keyless BLS 20/day quota.
  - fix: In resolve_official_forecasts, derive bounds from the validated anchor's normalized 'period' and 'frequency' (both stored by validate_data_anchor), using the same rule as data_sources._period_complete_at. Skip the fetch until the period is complete. Test: an annual anchor '2026-01-01' makes no fetch before 2027-01-01 and resolves after.
- MISSED M3 (BUG, medium) Codex's own delivery gate was not green: 3 tests fail under the guarded runner itself — at backend/tests/test_orchestrator_research_wiring.py (2 cases), backend/tests/test_architecture_characterization.py:199; docs/handoff/main-quantitative-integration-20261012/final-verification.md:9
  - evidence: `main_offline_pytest.py --evidence-dir .../ev-dsverify-orch-01 -q tests/test_orchestrator_research_wiring.py tests/test_architecture_characterization.py` gives '3 failed, 110 passed, 11 xfailed' (scratchpad/review/vfy/orch_runner.txt). final-verification.md reports a '2,025 passed; 15 explicitly separated' combined gate and lists the 15 separations (deployment/sidecar/demo), but not these. The verification record therefore overstates coverage. This is the process root cause behind D1, beyond the runner-only tests.
  - fix: Fix as in D1, then re-run both the full plain suite and the runner suite, record both receipts in final-verification.md, and add the plain-pytest CI command to the delivery gate checklist in the handoff.