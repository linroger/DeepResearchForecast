# Fix and finish slice results (exported from workflows wf_3445b548-3b6 and wf_05e3b908-45d)


## fix:A0 (wf_3445b548-3b6)

Slice A0 is done. It adds the shared data-layer interfaces in deerflow_bridge/data_sources.py, and the existing provider behaviour is unchanged.

K1: backend/tests/test_data_sources.py now imports `data_sources` and `data_mcp` by bare name (deerflow_bridge is put on sys.path, as in test_research_gateway.py). Before the fix, plain pytest stopped with a collection error (`ModuleNotFoundError: deerflow_bridge`). The lazy-import test now checks that the bare module and the module object are the same thing, instead of importing the package.

§1.1 / P-TEXT (data-layer part):
- `DataError` gains a `code` field (default "provider_error"; an unknown code becomes provider_error) and `unavailable_text()`, which returns `DATA_UNAVAILABLE[<code>]: <message>`.
- New `DataFailure(ValueError)` carries a code. `_request`, `_finish`, `_remaining`, the BLS quota check, BLS omitted/empty series and the SEC recipe now raise it with the right code.
- `_failure_class(exc)` sorts everything else into a code. It uses the exception type (TimeoutError, OSError, urllib HTTPError status) or ordered regexes over hub and provider text. The text patterns are the real FRED 429 tool text from the vendored fred-client.ts, FRED's unregistered-key message, BLS's invalid-key and daily-threshold messages, and the hub's timeout, starting, circuit and closed messages.
- `_error(sid, exc)` is the only place DataErrors are built. The message is redacted, at most 300 characters, and always ends with a hint that survives truncation. For rate_limited, quota_exhausted, key_invalid, provider_unavailable and timeout, the hint names the catalog's `fred_equivalent` (a bare id or `fred:`, and the `#transform` is carried over) or its `preferred` id.
- Retryable codes: rate_limited, timeout and provider_unavailable (except a closed hub or disabled sources).
- The `write_dataset_files` failure manifest now carries `"code": "persistence_failed"`.

§1.3 helpers: `is_percent_units`, `format_value` (new rule: percents up to 3 decimals; levels 4 decimals, or 4 significant digits below 1), `format_change` (signed, "pp" for percent units), `scaled_value` (magnitude only, en/zh), `series_label`, `observation_kind` (adds "partial"), `latest_observed`, and `format_series_value`.

M3, a deviation from the brief: rows fetched by HEAD already carry `normalization_policy_version` = 2. I checked every row in the live cache. So "new rows get version 2" would have changed every stored HEAD page. Instead I raised `NORMALIZATION_POLICY_VERSION` to 3 (this also invalidates old provider-cache entries, which A1's normalization changes need anyway) and added `_DISPLAY_POLICY_VERSION` = 3.
- Rows below version 3, or with no version, render exactly as before through `_legacy_format_value` and `_observation_kind`.
- Version-3 rows use `series_label` in the page heading and brief header, the new `format_value`, `format_change` ("change -0.25 pp."; levels show "+100 (+10%)"), and `observation_kind` in the status column.
- Golden fixtures: four real trimmed stored rows, with the page and brief bytes produced by the HEAD module, are in backend/tests/fixtures/data_sources/real/stored_v2/.

§1.2: `catalog_field(entry_or_series, name)` reads native_unit, native_dims, aggregation, status_policy, fred_equivalent, preferred, min_start and requires_key with getattr, validates the type and falls back to a default. It works with the old catalog and with slice B's new fields (I checked B's in-progress CatalogEntry types).

RPT-8 (data-layer part): `Series.kiqs` must be a list. It is cleaned, de-duplicated and capped at 20, and round-trips through to_dict, from_dict, write_dataset_files, load_datasets and load_official_data. Writes now add new KIQ ids to the stored ones (prior first) instead of replacing them.

Deadlines: `get(..., deadline_s=None)` and `search(..., deadline_s=None)` set a thread-local deadline through `_bounded()`. A nested bound can only shorten an outer one, and the previous value is restored afterwards. With None, hub calls are made exactly as before (no timeout or deadline arguments). A spent bound returns a timeout error; an invalid one returns invalid_input, both before any provider work.

Not done here (A1's scope): `_base` keeping the curated title (F10/L8, beyond `series_label`), units and status policies, daily completeness, and the `load_official_data` ranking.

Done:
- K1
- P-TEXT (data-layer: DataError codes/hints/retryable)
- fix-plan §1.1 DataError taxonomy
- fix-plan §1.3 public helpers (series_label, observation_kind, latest_observed, format_value, format_change, scaled_value)
- M3 (normalization_policy_version display gate; stored v2 rows re-render byte-identically)
- RPT-8 (data-layer: Series.kiqs round-trip and accumulate)
- fix-plan §1.2 optional CatalogEntry field reading via getattr (catalog_field)
- F12 data-layer part (get/search deadline_s)
- L16/RPT-15 helper part (format_value percent precision, format_change pp) wired into v3-policy rendering
Not done:
- F10/L8 _base curated title: Assigned to A1. series_label and the v3 page/brief heading are done here; _base still lets the provider title override the curated one.
- P-SCALE wiring: scaled_value is provided; adding the companion to render_series_brief, the report data pack and the snapshot belongs to A1, G1 and H.
- RPT-6/P-DAILY: A1 scope. series_stats still uses _observation_kind, so a partial month can still be 'Latest'. A1 should switch version-3 rows to observation_kind behind the _display_current gate and set complete=True for fully covered months.
- G4 load_official_data ranking/cap/omitted: A1 scope; not touched.
Interfaces:
All in data_sources.py, imported by bare name.

Errors:
- DATA_ERROR_CODES: tuple of 13 codes (§1.1)
- @dataclass DataError(series: str, message: str, retryable: bool = False, code: str = "provider_error"); .unavailable_text() -> str returns "DATA_UNAVAILABLE[<code>]: <message>"
- class DataFailure(ValueError).__init__(message: str, code: str = "provider_error", retryable: bool | None = None); retryable defaults to code in {rate_limited, timeout, provider_unavailable}
- _failure_class(exc) -> tuple[code, retryable]
- DataSources._error(sid, exc) -> DataError. The old third retryable parameter is removed; classification decides it.
- DataSources._hint(sid, code) -> str

Display and helpers:
- NORMALIZATION_POLICY_VERSION = 3 (was 2); _DISPLAY_POLICY_VERSION = 3
- _display_current(series) -> bool. Gate for any later display or status change, so rows below version 3 keep their page bytes.
- _legacy_format_value(value, units="")
- is_percent_units(units: str) -> bool
- format_value(value, units="") -> str. New rule: 3.875 -> "3.875%", 4.2 -> "4.2%", 0.04567 -> "0.04567".
- format_change(delta, units="") -> str: "-0.25 pp", "+0.1 pp", "0 pp", "+100"
- scaled_value(value, units="", lang="en") -> str: "≈ 40.27 trillion U.S. dollars"; zh "≈40.27万亿美元"; "" when |value| < 1e9, for percent units, or when the units already contain a scale word
- format_series_value(value, series: Series) -> str: value text that matches that row's stored page
- catalog_field(entry_or_series: CatalogEntry | str | None, name) -> validated value or default. Names: native_unit (tuple[str, int] | None), native_dims (dict), aggregation ("avg" | "eop" | ""), status_policy, fred_equivalent, preferred, min_start, requires_key. KeyError for any other name.
- series_label(series_or_row: Series | Mapping, lang="en") -> str: curated title (zh: title_zh), a transform suffix for yoy/pct, then " — <geography name>" when the title does not already name it (zh uses the Chinese geography alias). Never raises.
- observation_kind(obs: Observation | Mapping, series: Series | Mapping) -> one of "observed", "preliminary", "estimate", "projection", "unknown", "partial". "partial" means the provenance.periods entry has complete=False or covered bounds that differ from start/end; projection and estimate take precedence. Never raises (returns "unknown").
- latest_observed(series: Series | Mapping) -> Observation | None

Fetching:
- DataSources.get(series, *, start=None, end=None, transform=None, max_obs=240, deadline_s: float | None = None) -> Series | DataError
- DataSources.search(query, *, provider=None, limit=6, deadline_s: float | None = None) -> list[SearchHit]
- DataSources._bounded(deadline_s) -> previous deadline

Stored datasets:
- Series.kiqs: must be a list (else ValueError); cleaned to at most 40 characters each, de-duplicated, capped at 20
- write_dataset_files adds new KIQ ids to the stored ones (prior first)
- The failure manifest includes "code": "persistence_failed"
Tests:
Red before:
- K1: `cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_data_sources.py` raised ERROR collecting (ModuleNotFoundError: No module named 'deerflow_bridge').
- New test_data_sources_interfaces.py run against the HEAD modules (copied into scratch fix2/A0/head_bridge; log at scratch fix2/A0/redrun/red_vs_head.txt): 55 failed, 12 passed. The 12 that pass on HEAD are the stored-v2 byte-identity goldens and the unchanged level-formatting cases; they are meant to pass both before and after.

Green after:
- `cd backend && .venv/bin/python -m pytest -q -o addopts="" -p no:cacheprovider tests/test_data_sources.py tests/test_data_sources_config.py tests/test_data_sources_interfaces.py`: 237 passed (in-tree, with slice B's catalog).
- Plain `pytest -q tests/test_data_sources.py` (the CI form): green.
- Same tests against my data_sources plus the HEAD catalog copy: 212 passed.
- Related suites (test_data_mcp, test_data_mcp_deadline, test_v3_official_data, test_legacy_official_data, test_official_data_consumers/downstream/promotion, test_report_official_data, test_report_data_publication, test_research_gateway, test_resolution_monitor, test_data_visuals_render/status, test_forecast_extractor, test_report_visualizer): 997 passed. An earlier run had one teardown error: the source-frozen guard in test_v3_official_data tripped because files were being edited during the run. It did not recur on the rerun.

Lint: `uvx ruff check --select F,E9 --ignore F401,F841,F541 deerflow_bridge/data_sources.py backend/tests/test_data_sources.py backend/tests/test_data_sources_interfaces.py`: All checks passed.
Live checks:
One live BLS call (1 of the 5 allowed), through with_data_keys.sh, with the key redacted before the response was saved to scratch fix2/A0/live/bls_key_response.json. The configured BLS_API_KEY now returns REQUEST_SUCCEEDED, so it is valid now and there was no real invalid-key payload to capture. The key_invalid tests therefore use BLS's documented "The key:<k> provided by the User is invalid." message, in both raw and redacted form. The FRED 429 text comes from the vendored fred-client.ts and series.ts error format. Stored-row fixtures come from the reviewer's normalized live cache (retrieved 2026-10-11).
Open issues:
- A1: series_stats still uses _observation_kind, so a partial month can still be the Summary 'Latest'. Version-3 pages now show 'partial' in the status column. Gate any series_stats or __post_init__ status-policy change (P-WEOSTATUS, P-DAILY) on _display_current(series) so rows below version 3 keep their page bytes.
- A1: until P-DAILY sets complete=True for fully covered months, every month of a daily-aggregated version-3 row is 'partial' and latest_observed() returns None for it (conservative; this is HEAD's provenance, which stores complete=False for every daily-aggregated month).
- D (linear_research._data_summary) and E (deerflow_research): the digest now uses the new format_value while summary lines come from the page. For rows restored from before this change, use format_series_value(value, series) so the digest matches the cited page.
- C/E consumers: show DataError.unavailable_text() and do not cache errors where retryable is True.
- D: test_v3_official_data builds DataError(ids[1], 'deadline', True), which now gets code provider_error; pass code='timeout' if the code is shown.
- Bumping NORMALIZATION_POLICY_VERSION to 3 invalidates all old provider-cache entries, so the first run after merge refetches.
- B's in-tree data_catalog.py was briefly not importable (_wb() missing native_unit) while being edited; the in-tree runs above were done after it imported cleanly again.

## fix:T (wf_3445b548-3b6)

Slice T (CI, ops, hygiene). All work is in the files fix-plan §2 assigns to T, plus one new test file. Nothing was staged or committed.

D1 (T part), L13 and MISSED-3: under plain pytest, tests that need the guarded runner now skip with a reason instead of failing.
- backend/pyproject.toml registers a `guarded_runner` marker.
- backend/tests/conftest.py adds `pytest_collection_modifyitems`. It skips marked tests unless MAIN_OFFLINE_EVIDENCE is set; backend/scripts/main_offline_pytest.py sets that variable.
- test_main_offline_runner.py has to stay runnable via `--self-test` without pytest, so it does this in `setUp` instead. It calls `skipTest` when MAIN_OFFLINE_EVIDENCE is unset and fails loudly when the variable is set but the guard is missing.
- `@pytest.mark.guarded_runner` is on test_parent_supervisor_cannot_accept_failed_owned_worker (its sidecar `main()` needs `-I -S -B`) and on the end-to-end test.
- The end-to-end test no longer asserts on the variable. It now imports the bridge modules by bare name (`data_mcp`, `data_sources`, `research_gateway`, `linear_research`, `deerflow_research`) instead of `from deerflow_bridge import`, as invariant 6 requires.
- Found while verifying under the runner: test_network failed with "AF_UNIX path too long" when the evidence directory path was long. CPython checks the 104-byte limit before the audit event fires. The test now binds a relative socket name after `chdir` into its work directory.

Characterization pin (lead L6): test_characterizes_structured_spine_omissions now describes the current contract.
- `base_distribution=` is still never passed (the strict WP6 xfails are unchanged).
- `quantitative_facts=` is passed. A behavioural check uses a real ReportAgent with `derive_forecast_spine` captured. With an official-data carrier, quantitative_facts contains the stored value "4.25" and the "[S1]" marker. With no carrier it is "", so the prompt does not change.
- The check does not depend on exact pack text, so G1's RPT-5 re-render of the data pack will not break it.

I4 (backend and doctor): new `probe_data_sources()` and `POST /api/settings/data-sources/test` in backend/app/api/settings.py.
- Each probe builds a private McpHub + DataSources over the default server specs. Its env is os.environ plus `pipeline_orchestrator._data_sources_subprocess_env()`, so it sees the same settings as a research run. Both objects are closed afterwards, and only one probe runs at a time.
- For each enabled provider it runs the MCP handshake (initialize + list_tools via `hub.start`). For fred, bis, imf, wb and usgov it then fetches one catalog sample through `DataSources.get_many`, cache first: fred:UNRATE, bis:WS_CBPOL/M.US, imf:WEO/G001.NGDP_RPCH.A, wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA and usgov:treasury/debt_to_penny.
- BLS gets the handshake only, so no data request is made and the 20/day keyless quota is untouched.
- Each provider gets a state of ok, degraded, unavailable or disabled. Keyless FRED or BLS is reported as degraded with a hint naming the missing key.
- key_invalid is reported only for a configured FRED or BLS key, from DataError code `key_invalid` or a `providers()` status of `key_invalid`. A 401/403 on a keyless route is not treated as a bad key.
- Responses list key names with set / not set / invalid, never values. Configured key values and api_key / registrationkey / userid query parameters are redacted from all text.
- The budget is 75 s. I first used 45 s, but a cold IMF call measured 59.5 s live, so IMF always timed out at 45 s. After one success the IMF sample comes from cache for 24 h.
- Provider failures are reported in their row and never raised. A missing data layer gives unavailable rows, not a 500. The endpoint returns 409 when a probe is already running and 500 on an internal error. It sits behind the same app-level loopback/token gate as /llm/test.

scripts/doctor.sh `--deep` runs the same probe as a new advisory block after the preflight block.
- The embedded Python program sends backend stdout logging to stderr and prints level<TAB>message lines.
- Problems are reported as deep warnings (exit 2) and never block.
- The header and the `--help` line range (now 3-34) are updated.

DOC2: feature_official_quantitative_research is now `passes: false`, with a note that live verification by the lead is pending. No other entry, description or step was changed.

Done:
- D1 (slice-T part: runner-only tests skip under plain pytest; orchestrator fixture part belongs to slice H)
- L13
- MISSED-3
- L6/characterization pin (test_architecture_characterization.py: quantitative_facts= is the official data pack)
- I4 (backend probe + POST /api/settings/data-sources/test + doctor.sh --deep data probe)
- DOC2
- extra: test_main_offline_runner test_network failed under long evidence roots (AF_UNIX 104-byte limit); fixed with a relative bind
Not done:
- D1 (orchestrator part): The 2 test_orchestrator_research_wiring failures (fake create_simulation never makes the sim dir) belong to slice H, per the task.
- MISSED-M3 docs part: Recording plain and runner receipts in final-verification.md and in the handoff gate checklist is the lead's docs work. My receipts are listed in tests_run.
- I4 frontend card: Belongs to slice G3. The response shape is given in interfaces.
- H1 vendored datamcps hygiene: The task assigned to me did not include it, and verdicts.md marks H1 REJECT_IMPROVEMENT.
Interfaces:
HTTP: POST /api/settings/data-sources/test (no request body). On success it returns 200 {"success": true, "data": {"enabled": bool, "providers": {"fred"|"bls"|"bis"|"imf"|"wb"|"usgov": {"state": "ok"|"degraded"|"unavailable"|"disabled", "detail": str (redacted, at most 400 chars), "latency_s": float, "keys": {KEY_NAME: "set"|"not set"|"invalid"}}}, "deadline_s": 75.0, "elapsed_s": float}}. Flask jsonify sorts the provider keys. `keys` holds FRED_API_KEY for fred, BLS_API_KEY for bls, EIA_API_KEY/BEA_API_KEY/CENSUS_API_KEY for usgov, and {} for the others. Other responses: 409 {"success": false, "error": ...} when a probe is already running; 500 on an internal error. It uses the same app-level loopback/X-API-Token gate as /llm/test. Worst-case duration is about 82 s (75 s budget + 2 s grace + 5 s close), so G3's frontend timeout should be at least 90 s.

Python (backend/app/api/settings.py): `probe_data_sources(*, env: Mapping | None = None, deadline_s: float | None = None, clients: Callable[[dict], tuple[hub, data_sources]] | None = None) -> dict` returns the `data` object above and raises `DataProbeBusy(RuntimeError)` when a probe is already running. The hub needs start(names, wait=None), status() and close(timeout=); data_sources needs providers(), get_many(ids, *, deadline_s) and close(). Module constants: _DATA_TEST_DEADLINE_SECONDS=75.0 and _DATA_PROBE_SAMPLES.

Dependencies on other slices: settings.py imports `pipeline_orchestrator._data_sources_subprocess_env` (H must keep that name) and `official_data.data_api()`. It reads DataError `.code`/`.message` and Series `.observations`/`.route` by duck typing.

pytest: marker `guarded_runner`. Marked tests are skipped unless MAIN_OFFLINE_EVIDENCE is set.

doctor.sh: the `--deep` mode runs the embedded `DOCTOR_DATA_PROBE` Python program and renders ok/warn lines prefixed "data <provider>:".
Tests:
All paths below are under /private/tmp/claude-501/-Users-rogerlin-Downloads-DeepResearchForecast/52225542-51e1-41e1-b738-38d44834da7e/scratchpad.

RED, before the changes:
- `cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider` on test_main_offline_runner.py, test_deployment_sidecar_control_flow.py, test_official_data_end_to_end.py and test_architecture_characterization.py gave 23 failed: 19 MainOfflineControls, 2 sidecar parent, 1 end-to-end MAIN_OFFLINE_EVIDENCE assert, 1 stale characterization pin. Saved in fix2/T/red_plain.txt.
- At HEAD the endpoint did not exist: a HEAD copy of the app returned 405 for POST /api/settings/data-sources/test and had no `probe_data_sources` (fix2/T/red_endpoint.txt).
- Under the runner with a long evidence path, test_network failed with "OSError: AF_UNIX path too long" (fix2/T/runner_01.txt).

GREEN, plain pytest (CI path): `.venv/bin/python -m pytest -p no:cacheprovider -o addopts="" -q` on the four files above, plus test_settings_data_sources_probe.py, test_settings_endpoint_fallback.py, test_settings_provider_info.py and test_data_sources_config.py, gave 59 passed, 22 skipped (all with the guarded-runner reason), 11 xfailed, 0 failed.

GREEN, guarded runner: `backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir fix2/T/ev-final-01 --allow-python-script backend/tests/fixtures/official_data_mcp.py --allow-python-script deerflow_bridge/skills/data-visuals/scripts/render_data.py -q` on the 5 slice test files gave 49 passed, 11 xfailed, EXIT 0.
- The end-to-end evidence reads stage=complete, source_unchanged=True, identity_preserved=True.
- `--self-test` ran 19 tests OK. fix2/T/runner_02.txt shows 24 passed for the controls and sidecar tests.

Lint: `uvx ruff check --select F,E9 --ignore F401,F841,F541` on all touched Python files passed. `bash -n scripts/doctor.sh` passed, and `bash scripts/doctor.sh --help` prints the updated header.
Live checks:
Live probes ran through live/with_data_keys.sh with DRF_TEST_PROCESS=1, so only data keys were loaded, and DATA_SOURCES_CACHE_DIR under fix2/T/. No LLM calls were made. BLS data calls: 0. FRED data calls: 1 in total; later probes used the cache. Paths are under the scratchpad dir above.

1. fix2/T/live_probe.log: `probe_data_sources()` run twice with the earlier 45 s budget.
   - fred, bls, bis and usgov were ok. fred, bis and usgov fetched live on the first probe and came from cache on the second.
   - imf timed out at 45 s (DATA_UNAVAILABLE[timeout]).
   - wb was degraded: "Data360 unit code and metadata disagree". That message is also in HEAD's data_sources.py, so it is the known P-UNITS bug that slices A and B own.
   - No key values leaked.
2. fix2/T/live_samples.log: wb:WB_WDI_SP_POP_TOTL/USA and wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA failed with the same unit error; wb:IMF_WEO_NGDP_RPCH/CHN failed with "ambiguous disaggregations". A cold imf:WEO/G001.NGDP_RPCH.A call succeeded in 59.5 s, which is why the budget is now 75 s.
3. fix2/T/doctor_block.log: doctor's `--deep` data block only, rendered with the same level<TAB>message protocol and skipping the paid preflight LLM probe.
   - 6 clean lines, with no backend log noise on stdout.
   - fred, bls, bis and usgov ok (cache); imf ok live in 60.08 s; wb a degraded deep warning.
Open issues:
- The wb probe sample, and every WDI/WEO wb series tried live, fails at the current tree with 'Data360 unit code and metadata disagree' or 'ambiguous disaggregations'. These are the P-UNITS bugs slices A and B own. After they land, the lead should re-run `POST /api/settings/data-sources/test` or `scripts/doctor.sh --deep` (or fix2/T/doctor_block.sh under the scratchpad dir) and expect wb to be ok.
- G3's frontend call to /api/settings/data-sources/test needs a timeout of at least 90 s. The existing /llm/test call uses 45 s, which is too short because a cold IMF sample takes 34-60 s.
- test_official_data_end_to_end asserts exact renderings: '4.2%' in the data pack, tool_output_sids == (2, [2]), at least 2 official items, and caption formats. These passed under the runner at the current mid-edit tree. Slices A1, C, D, G1 and G2 change these paths, so the lead must re-run the end-to-end test under the guarded runner after all slices land. Its SOURCES hash-drift assertion also fails if other agents edit those files while it runs.
- The new characterization check and test_report_official_data.py both rely on ReportAgent._define_tools, _locate_timeline and _locate_handoff_dir as monkeypatch seams. G1 must keep those names.
- settings.py imports the private `_data_sources_subprocess_env` from pipeline_orchestrator.py. H must keep that function name.
- feature_official_quantitative_research is now passes:false. The lead re-evaluates it after live verification. README and agent-progress docs for the new endpoint and doctor probe are the lead's (fix-plan §2).

## fix:B (wf_3445b548-3b6)

Slice B (catalog and data-sources skill) is finished. Every change follows fix-plan §1.2. I edited only B-owned files, plus the two fixture files the task told me to add under the A-owned fixtures directory (the fixture filenames are listed under open_issues).

P-UNITS (catalog part) and verifier M2: CatalogEntry gained optional fields that default to current behaviour: native_unit, native_dims (read-only, excluded from equality and hashing), aggregation, status_policy, fred_equivalent, preferred, min_start, and requires_key (one field beyond §1.2, used to gate EIA/BEA entries). Every wb and bis entry now pins (UNIT_MEASURE, UNIT_MULT) from live captures.
- BIS pins are set per flow: WS_TC also pins UNIT_TYPE=770; WS_XRU pins ("",0) plus CURRENCY and COLLECTION; WS_CBTA pins (XDC,9) plus CURRENCY; WS_EER pins (882,0) because its rows carry no UNIT_MULT; WS_GLI pins (USD,6).
- WB pins are set per entry. IMF_WEO entries also pin COMP_BREAKDOWN_1=V_LST.
- Status policy: WDI is history_only, IMF_WEO and imf:WEO* are weo_vintage, WB_GEP is gep_vintage.
- Units: wb:IMF_WEO_NGDPD keeps 'U.S. dollars' with pin (USD,9). WDI GDP growth and CPI growth are now 'Percent change per annum'. The credit gap stays 'Percentage points of GDP' and LUR stays 'Percent of labor force'.
- Aggregation: every daily FRED entry defaults to avg; DFEDTARU, the new DFEDTARL, WALCL, debt_to_penny and debt_held_public are eop.
- spending/total gets min_start 2007-10-01.

P-BLSQUOTA (catalog part): fred_equivalent covers 29 BLS ids, each checked live (same title, units and adjustment). CUUR0000SA0 maps to CPIAUCNS. FRED has no CUSR0000SAM, so that entry has no mirror.

P-ROUTE (catalog part): preferred links are PCOPP→fred:PCOPPUSDM, PNGASEU→fred:PNGASEUUSDM, imf:WEO/USA.NGDP_RPCH.A→wb:IMF_WEO_NGDP_RPCH/USA, and the two BEA growth recipes→their FRED mirrors. Search and digest list the fast route directly ahead of the slow one. _CORE_IDS now uses fred:PCOPPUSDM.

P-BREADTH: added 14 FRED entries, 4 Treasury MTS recipes and EIA/BEA recipes, all checked live (EIA and BEA with keys); the full id list is in live_checks. FRED ids: IPG3344S, CAPUTLG3344S, IPG334S, A34SNO, A34SVS, PCU33443344, NASDAQSOX, IMPCH, EXPCH, B235RC1Q027SBEA, DPCERL1Q225SBEA, DFEDTARL. Petroleum and natural-gas spot prices already exist through FRED (DCOILWTICO, DCOILBRENTEU, DHHNGSP), so I added no EIA duplicates.
- MTS lines 110 (customs duties; net of refunds, so July 2026 is −$8.5bn), 20, 30 and 360, checked from 2015-03 to 2026-08.
- EIA recipes: electricity_sales and electricity_price (by state and sector), net_generation by fuel, crude_production (MCRFPUS2), and generating_capacity (BAT/SOL/WND/ALL).
- BEA recipes: real_gdp_growth, real_pce_growth, personal_income, nominal_pce, and value_added_by_industry (51/514/334/22).
- 29 EIA/BEA entries are advertised only when EIA_API_KEY or BEA_API_KEY is set (P-BREADTH verdict).
- Recipe schema: every recipe now has one uniform shape built by _recipe(); kind is one of treasury, usaspending, sec, eia, bea_nipa, bea_industry. The existing Treasury and USAspending field values are unchanged byte for byte.
- BEA limits found live: the tools drop units and return at most 8 observations per line (5 for the industry table). Monthly NIPA tables therefore cannot be read completely, so I defined only quarterly BEA recipes.
- Added ZH keywords and topics (technology, autos; energy and trade extended).

P-SEARCH (catalog part): new search_catalog_scored() returns CatalogHit(entry, score, concept, coverage, strong). A hit is strong when it is the series id itself, or when concept ≥ 4.0, coverage ≥ 2/3, the geography fits, and no named tenor contradicts it. Coverage counts EN words and CJK characters and ignores question framing and digits. Also added english_query() (ZH→EN glossary for English-only FRED search).

P-ZHRANK: _parse_query converts Chinese numerals (十年期→10年期). Added keywords 十年期国债, 两年期国债, 电力需求 and 用电需求. A tenor rule stops DGS2 being strong for a 10-year query. Uppercase ISO3, EA and EU tokens now parse as geographies (helps F22), and query_geographies() exposes this for P-WBGEO and F22. CJK topic terms consume their characters, so 能源 inside 新能源汽车 no longer triggers energy. Keywords are deduped by stemmed form, which removes double scoring.

P-DIGEST: the digest no longer pads with _CORE_IDS. When fewer than 6 entries match, a 'RELATED SERIES' section adds same-economy and same-theme entries, world benchmarks, then the theme anywhere for global questions, then the named country's headline series. When no hit is strong, it adds a hint to search with English concept terms, which is FRED-key aware. EIA/BEA role text and entries appear only when their keys are set. The ≤6000-char budget is exact.

P-SEC: removed SEC from the usgov role. The sec recipe stays resolvable but is marked enabled=False and is never rendered or advertised.

M5 (catalog part): WB_UNSUPPORTED_NOTE gives the search note text, and the index page documents which Data360 databases are fetchable.

L6: I split the catalog reference (the verifier left this optional; the task asked for it). references/series-catalog.md keeps its path, so the README link still works, and is now the index: providers, id grammar, BIS/IMF dataflows and the recipe summary. Each provider has its own page, catalog-<provider>.md, and every file is under 40k chars. render_catalog_files() plus `--write-markdown [DIR]` regenerate them, and a test checks they stay in sync.

SKILL.md: rewritten within an 8 KB cap I set; frontmatter is unchanged (name and description). It now covers per-provider pages, English search terms, the six statuses, the DATA_UNAVAILABLE[code] actions, the provider-choice table (keys, BLS quota and FRED mirrors, IMF fast routes, EIA/BEA keys, SEC unavailable), WEO/GEP projections and the default end, daily avg/eop aggregation, USAspending and MTS semantics, scaled values, and citation rules.

K3: added backend/tests/test_data_catalog.py with 37 tests. The unit pins and recipes are checked against real captured responses.

Done:
- P-UNITS (catalog pins + canonical units for all 54 wb / 50 bis entries)
- M2 (wb:IMF_WEO_NGDPD keeps 'U.S. dollars' with pin (USD, 9))
- §1.2 CatalogEntry fields: native_unit, native_dims, aggregation, status_policy, fred_equivalent, preferred, min_start (+ requires_key)
- P-WEOSTATUS/MISSED-2 catalog part (status_policy per entry)
- P-DAILY/P-USGOV catalog part (aggregation eop/avg; spending min_start)
- P-BREADTH (semiconductors, trade/tariffs, MTS 110/20/30/360, EIA and BEA recipes, ZH keywords)
- P-SEARCH catalog part (search_catalog_scored / CatalogHit.strong, english_query)
- P-ZHRANK
- P-DIGEST
- P-ROUTE catalog part (preferred links + fast-route-first ordering)
- P-SEC
- P-BLSQUOTA catalog part (fred_equivalent for 29 BLS ids, skill guidance)
- M5 catalog part (WB_UNSUPPORTED_NOTE + docs)
- L6 (per-provider reference files < 40k chars, generator + sync test)
- SKILL.md guidance refresh
- K3 (backend/tests/test_data_catalog.py)
- F22 helper (uppercase ISO3/EA/EU parsing + query_geographies)
Not done:
- P-SEARCH (DataSources.search flow): Slice A2 owns data_sources.py. It needs to count only CatalogHit.strong toward the early return, query FRED with english_query(), pass env=self._env, and drop 'undefined' notes.
- P-ROUTE (IMF parameter-definition disk cache): Slice A2 owns data_sources.py. The catalog side (preferred links and ordering) is done.
- P-BLSQUOTA (providers() quota_exhausted status and quota hint): Slice A2 owns data_sources.py. It should read entry.fred_equivalent.
- M5 (search note wiring): Slice A2 should attach catalog.WB_UNSUPPORTED_NOTE to Data360 hits from databases outside WB_DATABASES instead of dropping them.
- EIA/BEA adapter: Slice A2 owns data_sources.py. Recipes are defined and checked live; until the adapter lands, data_sources._fetch_usgov sends EIA/BEA kinds down the Treasury path and returns a DataError (it never raises into a stage).
- F22 (phase_data need→series resolution): Slice D owns linear_research.py. The catalog now parses uppercase ISO3 tokens and exposes query_geographies() and CatalogHit.strong for that slice.
Interfaces:
data_catalog (bare-name import):

CatalogEntry new fields:
- native_unit: tuple[str, int] | None = None — (UNIT_MEASURE code, UNIT_MULT) as the rows carry them. An absent UNIT_MULT reads 0; an absent UNIT_MEASURE reads "". When set, the adapter requires exact equality and displays entry.units, never the native label.
- native_dims: Mapping[str, str] (read-only, compare=False) — every returned row must carry these values.
- aggregation: "avg" | "eop" | "".
- status_policy: "" | "history_only" | "weo_vintage" | "gep_vintage".
- fred_equivalent: str — "fred:<ID>" or "".
- preferred: str — a catalog id or "".
- min_start: str — "YYYY-MM-DD" or "".
- requires_key: str — an env var name or "".

Constants:
- AGGREGATIONS, STATUS_POLICIES.
- STRONG_CONCEPT_SCORE = 4.0.
- WB_UNSUPPORTED_NOTE: str.
- REFERENCE_INDEX = "series-catalog.md".

CatalogHit(entry, score: float, concept: float, coverage: float, strong: bool) — frozen dataclass.

Functions:
- search_catalog_scored(query: str, *, provider: str | None = None, limit: int = 8, env: Mapping[str, str] | None = None) -> list[CatalogHit]
- search_catalog(query, *, provider=None, limit=8, env=None) -> list[CatalogEntry] (same as before, with an added env kw)
- catalog_digest(question: str, *, limit: int = 40, env: Mapping[str, str] | None = None) -> str
- english_query(query: str) -> str
- query_geographies(query: str) -> frozenset[str]
- recipe_available(recipe: Mapping, *, env=None) -> bool
- entry_available(entry, *, env=None) -> bool
- render_catalog_files() -> dict[str, str]. It replaces render_catalog_markdown(), which has been removed.
- main(["--write-markdown", DIR?]) writes every reference file.
- For all functions above, env=None means os.environ; DataSources should pass env=self._env. Entries whose key is missing are filtered out of search and the digest; lookup() still resolves them.

resolve_usgov_recipe(native): unchanged signature. A parameter is now validated by recipe["param_pattern"] (full match). The sec recipe still resolves but has enabled=False.

USGOV_RECIPES: every recipe has exactly these keys: kind, title, title_zh, tool, tool_args, endpoint, api_url, fields, filters, sort, date_field, value_field, period_format, param_field, param_facets, param_format, param_examples, param_pattern, tiebreak_field, facets, units_field, native_units, line_description, max_obs_per_call, frequency, seasonal_adjustment, units, source_url, notes, aggregation, min_start, requires_key, enabled.

How the adapter (slice A2) calls each kind:
- eia: call tool eia_query with {**tool_args, facets: "k=v; k2=v2" (recipe facets plus param_facets taken from the "."-split param), start, end, length≤5000, offset}. Rows come back newest first. Every row must carry the facet values, and row[units_field] must equal native_units. period_format is YYYY-MM or YYYY.
- bea_nipa: call bea_gdp_national with {**tool_args, year: "<y1>,<y2>"}. Use 2-year chunks so a line never exceeds max_obs_per_call=8. The output columns are [description, observations(JSON string)]; exactly one row must match line_description. Periods look like YYYYQn. The tool returns no units, so use the curated units.
- bea_industry: call bea_gdp_by_industry with {**tool_args, industry: param, year: one year} (max 5 observations). Exactly one row must come back. Periods look like 2025QI..QIV.
- treasury: unchanged.
- usaspending: same as before; clamp the window to min_start.
Tests:
cd /Users/rogerlin/Downloads/DeepResearchForecast/backend && .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_data_catalog.py → 37 passed.

RED evidence: the same test file run against HEAD's data_catalog.py, SKILL.md and series-catalog.md (copied into scratch dir fix2/B/red_head1) gave 34 failed, 2 passed. This ran before I added the 'broad' digest case. Output is in fix2/B/red_head.txt.

Regression runs (all green, no failures):
- tests/test_data_catalog.py tests/test_data_sources.py tests/test_data_sources_config.py tests/test_settings_data_sources_probe.py → all passed (216 dots).
- tests/test_data_sources_interfaces.py tests/test_data_catalog.py → 105 passed.
- tests/test_legacy_official_data.py tests/test_official_data_consumers.py tests/test_official_data_downstream.py tests/test_official_data_promotion.py tests/test_v3_official_data.py → all passed.
- tests/test_official_data_end_to_end.py → passed or skipped (1 s).

Lint: cd /Users/rogerlin/Downloads/DeepResearchForecast && uvx ruff check --select F,E9 --ignore F401,F841,F541 deerflow_bridge/data_catalog.py backend/tests/test_data_catalog.py → All checks passed.
Live checks:
All live calls ran through scratchpad/live/with_data_keys.sh, with DATA_SOURCES_CACHE_DIR under scratchpad/fix2/B/. Probe scripts and logs are in scratchpad/fix2/B/.

1. probe1/2 (EIA): eia_browse/eia_query on retail-sales (sales in 'million kilowatt hours', price in 'cents per kilowatt-hour'; states TX/VA/CA/GA/AZ; sectors ALL/COM/IND/RES; 2001-01..2026-07), electric-power-operational-data (generation in 'thousand megawatthours'; fueltype codes; sector 99), petroleum/crd/crpdn (series MCRFPUS2 in MBBL/D), and state-electricity-profiles/capability (BAT 2024 = 27,020 MW).
2. probe1 (BEA/MTS): truncation found — bea_gdp_national caps output at 8 observations per line; the industry table at 5 per call with roman quarters. MTS lines 110/20/30/360 checked over 138 months.
3. probe3/4 (FRED, paced): metadata of 13 new FRED ids and 25 candidate BLS→FRED mirrors. CUSR0000SAM, CES3000000001 and LNU04000000 do not exist on FRED under those ids. BLS was not called.
4. probe5/6: live BIS rows for all 50 bis entries confirm every pin. Every MTS, EIA and BEA catalog entry (36) was called with arguments built from its recipe dict, and identity, units and line matches were confirmed. One transient EIA HTTP 500 on US.COM price succeeded on retry.
5. End to end through the current working-tree DataSources: get() returned data for fred:IPG3344S, fred:IMPCH, fred:DFEDTARL, usgov:treasury/mts_customs_duties and usgov:treasury/mts_interest_gross. search('customs duties') ranks usgov:treasury/mts_customs_duties first.

No paid LLM calls were made.
Open issues:
- Fixture ownership: the task told me to put fixtures under backend/tests/fixtures/data_sources/real/, which fix-plan §2 assigns to slice A. I used two uniquely named files there (catalog-native-units-2026-10-12.json and catalog-usgov-recipes-2026-10-12.json). The lead should stage them with slice B.
- Slice A2 must implement the eia, bea_nipa and bea_industry kinds of _fetch_usgov from the recipe fields. Until then, EIA/BEA ids return a DataError. Treat EIA HTTP 5xx as retryable: a transient 500 happened during the live probe.
- Slice A1/A2 must read native_unit with absent UNIT_MULT = 0 and absent UNIT_MEASURE = '' (WS_XRU rows have no UNIT_MEASURE; WS_EER rows have no UNIT_MULT). DataSources.search should pass env=self._env to search_catalog_scored so key gating follows the instance's environment.
- Slice D can pass env= to catalog_digest; the default os.environ also works. With keys present the digest lists many EIA lines for electricity questions, but it stays within the 6,000-char cap.
- The lead's docs pass: design.md and integration-contract mention render_catalog_markdown and a single series-catalog.md. It is now render_catalog_files(), with series-catalog.md as the index plus catalog-<provider>.md pages. The README link to series-catalog.md still resolves.
- Possible follow-up (not done): EIA STEO publisher projections (route 'steo', seriesId facet) would add official short-term forecasts, but need a status policy rule for months after the release.

## fix:C (wf_3445b548-3b6)

Slice C (v3 data tools in deerflow_bridge/research_gateway.py) is finished. The previous attempt's work was kept. The file it left behind failed at runtime: `calendar` and `date` were never imported (ruff F821), and that is fixed. The remaining fixes were finished and every one has tests.

- **F13 / V3-M1 (dataset cap per preset, seeder budget):**
  - `ToolLimits.max_datasets` is the run cap (default 16). `rg.dataset_cap(depth, env)` gives quick 10, standard 16 and deep 24. `DATA_SOURCES_MAX_SERIES` overrides it, clamped to `MAX_RUN_DATASETS` = 200.
  - Prefetch may store at most `max_prefetch_datasets` = 60 % of the cap.
  - The seeder ("data-seeder") has its own allowance, `max_seeder_data_calls` = 3 × the prefetch cap. It never spends the agents' `max_data_calls_total`.
  - The seeder's own `data_get` calls also count toward the prefetch cap. Concurrent seeder requests are counted through `_seeder_pending`.
  - `restore_data` marks seeder-registered rows, so a resumed run counts them against the same cap.
- **F14 / P-TEXT (failure reasons reach the agent):**
  - A DataError is shown as `DATA_UNAVAILABLE[<code>]: <message>`, the data layer's redacted reason plus its hint.
  - Other exceptions are mapped to a code with `data_sources._failure_class` and their text is never shown.
  - Prefetch uses the same codes instead of "within the data deadline".
  - Search lines now add the geography (via `series_label`), units, frequency, coverage and the first 120 characters of the note.
  - `data_stats` adds `seeder_calls`, `dataset_cap`, `prefetch_cap`, `failed_requests` (at most 40 entries of request/code/retryable/by/reason) and `per_kiq` (requested/stored/failed per KIQ).
- **F19 (one bad call no longer blocks a series or query):**
  - An empty or blank `provider`, `start`, `end` or `transform` is treated as not given.
  - `provider` is checked against the six providers.
  - A bare year, month or quarter is turned into a date inside the gateway, and an end bound means its last day (`end="2026"` becomes 2026-12-31). A malformed or reversed window gets `invalid_input` without a provider call.
  - Answers are cached by series, transform and window. Retryable failures, budget stops, persistence failures and empty searches (NO_DATA_MATCH) are not cached.
- **V3-M4:** a request outside the stored window gets the stored page with a NOTE on line 2. Line 1 stays the `[S<n>]` header the engine reads. The note takes `intentional_delivery_trim` and `requested_end` into account.
- **RPT-8 (producer side):** prefetch takes `kiqs` and `windows` maps, and `data_get` takes a `kiqs=` argument. KIQ links are added to `Series.kiqs` and written to the run manifest; the page and its hash do not change.
- **F9 / M4 (persistence failures):**
  - `_store_dataset` never raises. It checks `manifest.get('error')` and no longer leaks StopIteration.
  - On failure it removes the row it just registered, through the new `SourceLedger.forget_dataset(sid)`. A sid is never handed out twice in the process.
  - `restore_data` ignores dataset rows that were never marked fetched.
  - A series whose stored copy failed validation is never fetched again in the same run.
  - Deviation from the plan: I took out the attempt-1 `pages_dir` resolve, because A1's `_safe_path` already resolves the root. The symlinked-parent test passes either way.
- **F11 (shared publisher pages):** `fetch()` uses the new `_dataset_for_url`. A dataset's own identity URL returns its page. A source URL shared by more than one stored series returns a `DATASET_CHOICE` list (line 0 has no `[S` marker; the list lines are `- [S<n>] <id> — <label>`). A source URL with a single series keeps the old behaviour. Nothing falls through to a web fetch.
- **F10:** ledger and References titles use `series_label`, so for example the IMF WEO GDP growth rows read "…: China".
- **F20 (schema):**
  - The data tool schema now has descriptions, a provider enum, `transform` enum `[yoy, pct]`, ID-format examples (each one parses) and the YYYY[-MM[-DD]] window format.
  - It is still static text.
  - The web-only schema is byte-identical to HEAD (sha256 pinned in a test).

Done:
- F9
- M4
- F11
- F13
- V3-M1
- F14
- P-TEXT (consumer: codes + reasons, no retryable caching, prefetch codes, search lines with geography/note)
- F19
- V3-M4
- F20 (schema part)
- RPT-8 (producer: kiqs on prefetch and data_get)
- F10 (ledger titles via series_label)
Interfaces:
Module research_gateway (exported in `__all__`):
- `DATASET_CAPS = {"quick": 10, "standard": 16, "deep": 24}`, `MAX_RUN_DATASETS = 200`, `DATA_SEEDER = "data-seeder"`, `DATA_PROVIDERS = ("fred", "bls", "bis", "imf", "wb", "usgov")`.
- `dataset_cap(depth: str, env: Mapping[str, Any]) -> int`: `DATA_SOURCES_MAX_SERIES` overrides; invalid values fall back to the preset; clamped to [0, 200].

`ToolLimits`:
- New field `max_datasets: int = 16` (0..200).
- Properties `max_prefetch_datasets` (= max_datasets*3//5) and `max_seeder_data_calls` (= 3*max_prefetch_datasets).
- Seeder calls never count toward `max_data_calls_total` or the per-agent limits.

`ResearchTools`:
- `data_get(series, *, start=None, end=None, transform=None, agent_id, deadline=None, kiqs: Sequence[str] | None = None) -> str`. Default `kiqs` is `(agent_id,)`, or `()` for the seeder. Seeder gets count toward the prefetch cap.
- `prefetch_data(identities, *, deadline, kiqs: Mapping[str, Sequence[str]] | None = None, windows: Mapping[str, Sequence[str | None]] | None = None) -> dict[str, str]`. Answers are keyed by the IDs as passed; the stored window is immutable per run.
- `data_stats()` adds `seeder_calls`, `dataset_cap`, `prefetch_cap`, `failed_requests` (list of {request, code, retryable, by, reason}) and `per_kiq` ({KIQ: {requested, stored, failed}}).

`SourceLedger.forget_dataset(sid) -> bool`: drops only unfetched dataset rows.

Tool text contract:
- Failures: `DATA_UNAVAILABLE[<code>]: <message>`.
- Budget: `DATA_BUDGET_EXHAUSTED: ...`; the prefetch limit text is `DATA_BUDGET_EXHAUSTED: prefetch limit reached; ...`.
- `NO_DATA_MATCH: ...` is not cached and not counted as a failure.
- A `data_get` page keeps line 0 = `[S<n>] ...` header; an optional `NOTE: ...` follows on line 1.
- Search lines are `<id> — <series_label> · units · freq · coverage · note[:120]`.
- `web_fetch` of a shared origin returns `DATASET_CHOICE: ...` (line 0 has no `[S` marker) followed by `- [S<n>] <id> — <title>` lines.
Tests:
Green (CI path, `cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider`):
- tests/test_research_gateway_official_data.py: 30 passed.
- tests/test_research_gateway.py + tests/test_research_gateway_official_data.py + tests/test_v3_official_data.py + tests/test_official_data_end_to_end.py + tests/test_research_engine_v3*.py: 985 passed, 1 skipped (guarded-runner test). Log: scratchpad/fix2/C/run5.txt.
  - Earlier, D's test_prefetch_reserves_each_id_and_reuses_batch_results failed because of the intended change that the seeder no longer counts toward max_data_calls_total. D has since switched it to max_datasets=2 and it passes.

Red before (HEAD gateway): scratchpad/fix2/C/tools/run_with_head.py binds `git show HEAD:deerflow_bridge/research_gateway.py` to the bare name `research_gateway` and runs the new file. 29 of 30 fail, each for the intended reason: missing interfaces, generic failure text, cached failures, raw windows, no window note, StopIteration, an invalid unfetched row, a refetched rejected copy, the shared origin returning another country's page, identical titles, and no provider enum. Log: scratchpad/fix2/C/red_head_final.txt and red_head.txt. The only test green on HEAD is test_run_directory_below_a_symlinked_parent_stores_datasets, a regression test whose fix lives in A1's `_safe_path`.

ruff: `uvx ruff check --select F,E9 --ignore F401,F841,F541 deerflow_bridge/research_gateway.py backend/tests/test_research_gateway_official_data.py backend/tests/test_research_gateway.py` reports all checks passed. Before this attempt it reported F821 for `calendar`/`date`, left by the killed attempt.
Live checks:
Live run of /private/tmp/claude-501/-Users-rogerlin-Downloads-DeepResearchForecast/52225542-51e1-41e1-b738-38d44834da7e/scratchpad/fix2/C/tools/live_check.py through with_data_keys.sh, with DATA_SOURCES_CACHE_DIR=scratchpad/fix2/C/live/cache. Output: scratchpad/fix2/C/live/live_check2.txt.

Calls made: FRED 2 gets, Data360 3, BIS 1, and catalog-only searches. No BLS or IMF calls.

Results (8.4 s total):
- `data_search` with `provider=""` returned catalog hits with geography and notes.
- Prefetch stored fred:UNRATE, wb:IMF_WEO_NGDP_RPCH/USA, /DEU, /CHN and bis:WS_CBPOL/M.US. The ledger titles carry the country ("...: Germany" and so on).
- K1 asked for 1990..2026 on fred:UNRATE and got the stored page plus a NOTE that the window was not refetched.
- K2 got fred:PAYEMS with a bare-year end.
- An invalid transform returned `unsupported_transform`.
- `web_fetch` of the shared Data360 page returned DATASET_CHOICE listing S2, S3 and S4. The single-series FRED page returned [S1].
- Manifest KIQ links were {UNRATE: [K1], CHN: [K2, K3], PAYEMS: [K2]}.
- `restore_data` brought back all 6 series with no invalid sids. Stats: calls 8 (seeder 7), failures 0.

Environment caveat: the first attempt used backend/.venv, which now has mcp 2.3.0. Every MCP server then exited during startup, and the gateway correctly showed `DATA_UNAVAILABLE[timeout]` (live_check.txt). The successful run used deer-flow/backend/.venv/bin/python (mcp 1.27.0), as A1 recorded.
Open issues:
- backend/.venv has mcp 2.3.0 (A1 found this; it came from a uv.lock change in another session). Every data MCP server exits at startup under it, so live runs through backend/.venv fail; deer-flow/backend/.venv works. The lead should restore the HEAD lock's mcp version.
- D (engine): meta.data_sources now also gets seeder_calls, dataset_cap, prefetch_cap, failed_requests and per_kiq, including in disabled runs, because the engine calls data_stats() unconditionally at finalize. If meta.json for disabled runs must keep the old keys, D should skip that update when data is disabled.
- D (engine): drop or lower the DATA_SOURCES_PREFETCH_MAX <=12 clamp in phase_data so it stays within limits.max_prefetch_datasets. Long-history or projection-horizon seeds (V3-M4 / F2) can use prefetch_data(windows=...) or data_get(..., agent_id=rg.DATA_SEEDER, kiqs=[...]).
- linear_research.py (D) still contains the stale text 'UNKNOWN_TOOL: only web_search and web_fetch are available.' (the engine part of F20).
- The fixture builder for backend/tests/fixtures/data_sources/real/gateway/series-2026-10-11.json is in scratchpad/fix2/C/tools/build_fixture.py. The A-owned fixtures README does not mention the new gateway/ directory yet.

## finish:D (wf_05e3b908-45d)

Role D (v3 engine) is finished. Every assigned finding is implemented and has a test: F1, F2, F4, F5, F6/G3, F7, F8, F12, F15, F16, F17, F18, F20 (engine part), F22, G7, V3-M3 and V3-M4. A review of D's own diff plus a live run (real FRED, BIS and World Bank servers, scripted model, no LLM calls) turned up seven more defects. All seven are fixed and tested. The live run for "Will US CPI inflation fall below 2.5% year over year by December 2027, and how will the Federal Reserve policy rate evolve?" completed (rc=0, 18.3 s; the data phase took 8.6 s on a cold cache). A check script confirmed 69 of 69 points end to end: planner needs resolved to the right series, the data phase stored them, KIQ tasks showed them, the scripted data_get calls worked, and the stored values appear in the digest, sections, QA, baseline table, figures, sources.json, quantitative.json and forecast_inputs.indicators. With official data disabled, a full scripted run produces byte-identical model requests (27 calls) and the same 6 artifacts as the HEAD engine. Against the HEAD engine, 26 tests fail for the expected reasons (22 new, 4 updated). The owned and related suites pass (run4: 1,036 passed, 1 skipped) and ruff is clean.

Done:
- Confirmed each assigned finding is implemented and tested in backend/tests/test_v3_official_data.py: F1 BIS/status labels, F2 WEO projection window and latest value, F4 numeric QA check, F5 resume rules, F6/G3 quantitative rows and indicators, F7 planner data_needs and catalog fallback, F8 demotion to REPORTED, F15 gap coverage and follow-up data, F16 official digest block, F17 Chinese exhibits, F18 baseline table, F20 agent guidance, F22 geography resolution, G7 progress band, V3-M3 chart deadline, V3-M4 long-history windows. F12 is covered by routing, catalog resolution, concurrent searches and the slow-provider rule; measured cold data phase 8.57 s for 6 series.
- Red check against the HEAD engine and HEAD research_progress (fix3/D/tools/run_with_head.py): 26 failures for the expected reasons, in fix3/D/red_head_final.txt.
- Fix: official rows used to be in quantitative.json before the research charts ran, so the chart renderer would re-plot WEO projection paths. They are now added by _attach_official_quant() after _render_research_charts, as the legacy engine does. It never raises, records quantitative_count and official_quantitative_count in meta, and sets as_of_date to the retrieval date (the source as-of date); period_end is the period measured.
- Fix: _official_indicators never raises (a data problem cannot fail finalize).
- Fix: the fallback found no series for compound questions (the CPI/Fed question gave none). _catalog_seeds now also searches each clause, using the same split as legacy _PREFETCH_CLAUSE_RE, takes one series per provider after routing, and uses slow IMF series only for slots nothing faster fills. Without BLS_API_KEY, BLS headline series go to their FRED copy (fred_equivalent). The CPI question now seeds wb:IMF_WEO_PCPIPCH/USA, fred:CPIAUCSL and bis:WS_LONG_CPI/M.US.771.
- Fix: _catalog_need now needs a strong catalog hit. Before, 'Atlanta Fed wage tracker' resolved to the BIS policy rate and 'sticky price inflation' silently became CPIAUCSL.
- Fix: _data_hit treats a FRED, BLS or usgov hit whose title names no place as US data for a country need (FRED titles only name non-US places). Live: query need 'sticky price index' for the United States now resolves through a live FRED search to fred:CORESTICKM159SFRBATL; before, it was rejected.
- Fix (found live): a VERIFIED finding quoting a single-digit value such as '4%' was never checked. Demotion now covers those values and uses the period the finding names (data_named_periods handles '2026-09', 'September 2026', 'Q2 2026', '2026年9月' and years, with strict month names). '4% in 2026-09' stays VERIFIED; '4% in October 2026' (an open month) becomes REPORTED.
- Fix (found live): data_view used the open, partial month as the latest value, contradicting the fix2 design note. The latest value is now the newest non-projection, non-partial point, matching the page's 'Latest' line. The newest daily value appears separately ('latest daily value 4% (2026-10-12)', Chinese 最新日度值). Old policy-2 rows render unchanged.
- Fix (found live): units like 'Per cent, year-on-year change' rendered as '3.397% , ...'; they now read '3.397% year-on-year change'.
- Fix: _data_as_of() replaces int(plan.as_of[:4]) for the base-rate start and data windows.
- Updated the research_progress module and class docstrings for the official-data band.
- Proof that disabled-data runs are unchanged: fix3/D/tools/prompt_identity.py runs a full scripted engine with data disabled and one worker. Current and HEAD engines give identical model calls (messages, tool bindings, kwargs) and identical research_report.md, sources.json, quantitative.json, actors.json, timeline.json and contested.json.
- Live run, real servers, no LLM: fix3/D/live_run. 9 series stored (6 prefetched; T10YIE and PCEPILFE#yoy from K3's own data_get calls; bis:WS_CBPOL/M.XM from the gap follow-up prefetch), 0 failures, FRED 4 series plus 1 live search, no BLS or IMF calls. WEO window ends at 2027 with statuses 2024 observed, 2025 estimate, 2026-27 projection. fred:FEDFUNDS for the base-rate KIQ holds the newest 240 months. K4's request for CPIAUCSL from 1996 got the stored page with a note that the window was not refetched. QA data_numbers_consistent, data_exhibits and sections_in_order passed; the baseline section sits after the first analytical section; 8 data figures are embedded and on disk. sources.json has 9 official rows; quantitative.json has official 'actual' rows equal to the stored observations plus 2 WEO forecast rows; there are 9 indicators. The research charts did not re-plot official series.
- New real fixture from the live run: backend/tests/fixtures/data_sources/real/v3_engine/series-2026-10-12.json (DFEDTARU with a partial open month, BIS year-on-year CPI, WEO CPI to 2027; current policy; no keys in api_url). Builder: fix3/D/tools/build_fixture_1012.py.
- New tests: test_compound_question_seeds_its_clauses_and_keyless_bls_routes_to_fred, test_a_finding_is_verified_only_for_the_observed_point_it_quotes, test_an_open_month_is_not_the_latest_value_and_the_latest_daily_value_is_shown. Extended: the named-country, finalize-quantitative and full-engine tests.
Not done:
- B-catalog-framing: data_catalog.py belongs to B. 'how will the Federal Reserve policy rate evolve' gets no strong hit because 'evolve' counts as a concept term (coverage 0.5), and catalog_digest tells the planner 'No catalog series answers this question directly' for compound questions. The v3 clause fallback recovers the CPI clause but not the Fed clause.
- A2-P-SEARCH: deerflow_bridge/data_sources.py belongs to A (the P-SEARCH item is in fix-plan §3 A2, which never ran). DataSources.search still returns early on weak catalog hits, so live FRED/Data360 search is not consulted for concepts the catalog partly matches (live: 'Atlanta Fed wage growth tracker' returned only weak catalog hits in 0.0 s).
- forecast-visuals-skip: Not D's file. forecast-visuals render.py would still plot official_data rows if another producer wrote them before the charts. The v3 engine now avoids this by ordering, as legacy does.
Tests:
From backend/: .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_v3_official_data.py tests/test_research_engine_v3*.py tests/test_live_research_progress.py tests/test_research_gateway.py tests/test_research_gateway_official_data.py tests/test_start_script_progress.py tests/test_official_data_end_to_end.py. Final run4: EXIT 0, 1,036 passed, 1 skipped (fix3/D/run4.txt). Runs 2 and 3 also had every test pass but showed one teardown ERROR: the source_receipt fixture saw another agent edit deerflow_bridge/data_sources.py during the run. Also passed: test_bridge_extensions_config.py, test_deerflow_bridge_sync_guard.py, test_bridge_overhaul_v3.py. Red check against the HEAD engine and progress module: 26 expected failures (fix3/D/red_head_final.txt). ruff (F,E9) clean on the three changed Python files. Disabled-data prompt identity check (fix3/D/prompts_current.json vs prompts_head.json): identical.
Live checks:
Command: with_data_keys.sh backend/.venv/bin/python fix3/D/tools/live_v3_full.py fix3/D/live_run fix3/D/live_cache_final2 (cold cache), then fix3/D/tools/verify_live.py, result in fix3/D/live_verify.txt: RESULT PASS, 69/69. Scratchpad root is /private/tmp/claude-501/-Users-rogerlin-Downloads-DeepResearchForecast/52225542-51e1-41e1-b738-38d44834da7e/scratchpad. Run: rc=0, 18.3 s; phases data 8.57 s, gather 1.41 s, gap 1.28 s, qa 2.43 s, finalize 4.13 s. Artifacts in fix3/D/live_run: research_report.md (with Official Data Baseline and 8 figures), sources.json (9 official_data rows), quantitative.json (official actual and forecast rows plus 1 extracted row), actors.json (forecast_inputs.indicators for 9 series), timeline.json, contested.json, charts.json, charts/data_*.png and .html (8 series) plus timeline, data/datasets.json with 9 series CSV/JSON files, meta.json (data_sources stats: 11 calls, 0 failures, dataset_cap 16, prefetch_cap 9, per_kiq), engine_log.txt (research:v3:data start (6 series) / done (stored=6, failed=0); follow-up official data stored=1), model_calls.json (every scripted model request), v3/ (plan.json, digest.md with the OFFICIAL DATA block, kiq/*.json and *.md with findings, qa.json, qa_report.md, sources_ledger.json, state.json, pages/, data/, sections/). Live stored values: BIS US CPI 3.397% year-on-year (2026-08); CPIAUCSL 334.131 (2026-08); Fed target upper limit 4% (2026-09, latest daily 4% on 2026-10-12); FEDFUNDS 3.75% (2026-09); IMF WEO CPI 2.73% (2025 estimate), projections 3.228% (2026) and 2.141% (2027); sticky CPI 2.701% (2026-08); core PCE 3.008% year-on-year (2026-08); 10-year breakeven 2.351% (2026-09); euro-area policy rate 2.5% (2026-09). Live calls: FRED about 10 per cold run plus 2 search probes; BLS 0; IMF 0.
Open issues:
- For the lead or A: the new fixture backend/tests/fixtures/data_sources/real/v3_engine/series-2026-10-12.json sits in the fixtures folder A owns (it is next to D's existing series-2026-10-11.json); please mention it in fixtures/data_sources/README.md.
- For A: series_label adds no geography to FRED series found through search, e.g. 'Sticky Price Consumer Price Index less Food and Energy' has no '— United States'. Catalog series are fine.
- Concurrency: another agent kept editing deerflow_bridge/data_sources.py during the runs (22:32 and 22:33), which tripped the source_receipt teardown in test_v3_official_data.py. Run4, after the edits stopped, passed cleanly. The lead's full-suite run should happen with no slices editing.
- Behaviour change for downstream readers: in v3 quantitative.json, official 'actual' rows now use as_of_date = retrieval date and period_end = measured period (the same as legacy). The official rows are written after research charts render; meta.quantitative_count includes them.
- Possible to-do for B: P-BLSQUOTA. providers() does not report BLS quota state; v3 routes keyless BLS headline series to FRED copies based only on whether BLS_API_KEY is set.
- D's working notes: fix3/D-notes.md. Tools are in fix3/D/tools/: live_v3_full.py, verify_live.py, prompt_identity.py, run_with_head.py, build_fixture_1012.py.

## finish:H (wf_05e3b908-45d)

Role H is finished. Every finding I was asked to confirm is implemented and covered by tests: D2, D3, D4, D5, G1, G2/P-SNAP, G4, G5, G6, I5, L10 (orchestrator part), downstream M1 and downstream M2. The one exception is G5's forecast.json field, which needs a change in report_agent.py, a file G1 owns. Live checks ran on real FRED, BIS, World Bank and US Gov data and found two real defects in my files, both now fixed with regression tests that fail without the fix. First, the resolution monitor marked a period as "manual" and "degraded" when the period had ended but the agency had not yet published the value. Second, when K research lanes are merged without a global synthesis, the merged meta.json kept only lane 1's start and finish times, so data captured by a later lane past UTC midnight was dropped from the simulation brief and graph snapshot. I also made the official-data snapshot clearer for simulation agents and documented the new settings in .env.example. All 297 tests in my files and the monitor, ledger and autorun files pass. ruff is clean and check_env_drift.py --strict exits 0. In a wider run of 68 files that touch my modules, 6 tests failed, all in files other slices were editing at the time; none of them goes through code I changed.

Done:
- Confirmed implemented and tested (existing tests from the earlier H attempt plus fix3 additions). D2: capture or bind failures degrade to an unbound simulation, recorded in state.options['official_data_binding'] (test_orchestrator_research_wiring: binding failure [capture|bind], and a test that a binding conflict still fails closed). D3: bindings now store the handoff path relative to the pipelines root (schema 2); an invalid binding drops only official_data and the dossier is still found through the pipeline lookup (consumers tests: 5 mutations, relocation, schema-1 relocation and rebind). D4: the world brief budgets the delimited snapshot block whole and never slices it (sweep test). D5: the research run window decides availability (7 cutoff cases plus the run-window reader). G1: the canonical brief gets the official block (canonical-denials [True/False] and a downstream test). G2/P-SNAP: whether a row can be shown is now separate from whether it can resolve a forecast (tests on replayed real payloads). G4: Config.DATA_SOURCES_MAX_SERIES caps the series count (consumers cap test). G5: monitor summary, per-report _summary_row counts and the ledger's official_data_track_record (test). G6: bind_project_simulation and the create endpoint (5 tests). I5: YoY change and 5-year range columns. L10: _merge_track_research_data (3 promotion tests). M1: exact WEO/GEP id prefixes (GEPUCURRENT test). M2: _anchor_period_bounds (4 cases).
- The canonical world-brief denials test from the NEXT list already existed: test_official_statistics_join_the_canonical_brief_without_reopening_denials[True|False].
- New fix (resolution monitor): when a fetch comes back without a usable series, retryable errors are now 'pending' (temporarily unavailable); not_found and invalid_window are 'pending' until a grace period after the period end (daily/weekly 30 days, monthly 120, quarterly 210, annual 730), then 'manual'; any other error is 'manual' with its code in the reason. Before this, an ended but unpublished period was 'manual' and degraded on every run. Live proof: an anchor on CPI year-over-year for 2026-09 now shows pending with degraded False. A new real fixture holds the live error capture. 6 tests, 5 of which fail without the fix.
- New fix (orchestrator, non-global lane merge): the merged meta.json now takes the earliest lane start and the latest lane finish (it previously used lane 1 only), so every lane's own captures stay inside the run window. 1 new test on real FRED captures, which fails without the fix; the end-to-end test was refactored into a shared _merge_two_real_lanes helper.
- Snapshot improvements (official_data.py): the Period column now follows the series frequency (annual '2025', quarterly '2024-Q4', monthly '2026-09'); before, a monthly value printed as '2026-09-01' sat next to aggregated months printed as '2026-09'. YoY and 5-year range cells for dollar-sized values now read like '≈ 40.17 trillion'. The relative YoY change is now measured against the absolute prior value, as series_stats does; the earlier formula value/prior-1 gave the wrong sign for negative values such as deficits. The latest-daily note now carries a scaled value. 2 new tests, both fail on the old variant; 7 existing period assertions updated to the new format.
- .env.example: documented E's LEGACY_DATA_GETS_PER_THREAD=8 and LEGACY_DATA_SEARCHES_PER_THREAD=6. Clarified that the prefetch cap is now min(DATA_SOURCES_PREFETCH_MAX, 60% of the run's dataset cap) in v3 (6, 9 or 14 by depth) and min(value, 6) on the legacy baseline lane. Removed the outdated 'legacy per-question cap 4'. Refreshed the notes on inferred status and daily-to-monthly aggregation, and documented data_resolutions.jsonl and official_data_brier.
- Live check A (real MCP servers): 10 of 12 series stored (FRED x5, World Bank WDI and WEO, BIS policy rate, Treasury Debt to the Penny, USAspending).
- Live check B (offline replay of that stored data): the binding is stored as the relative path 'pipe_live/handoff'; the production lookups return 10 series plus the run window; the graph-episode snapshot holds 8 rows with qualifiers, trends and aggregation notes; an as_of date before the run started excludes every row; both the unversioned and canonical world briefs have matching BEGIN/END markers; a sweep of 639 briefs found no unmatched markers; the binding still resolves after moving the whole install.
- Live check C (resolution monitor on real data): unemployment 2026-09 > 4, CPI YoY 2026-08 >= 3 and the US policy rate 2026-09 < 4 all resolved; the 2026-10 monthly and 2026 annual anchors stayed pending without a fetch; the aggregated-daily and WDI anchors went to manual; Brier 0.129 recorded; monitor_report.md has the 'Official data outcomes' table; a second run recorded nothing new and did not refetch resolved outcomes.
Not done:
- G5-forecast-json: forecast_ledger.official_data_track_record() exists, is tested, and returns None until something resolves, so output is unchanged when nothing has. Exposing it in forecast.json historical_calibration needs a change in report_agent.py, which G1 owns; nothing calls it yet.
- EIA/BEA live: The usgov EIA and BEA recipes fail live in the data layer (data_sources.py, owned by A/A2). The EIA call fails because the 'route' argument is undefined; BEA returns 'No data exists for the Year/Frequencies passed'. Not fixable in H's files.
Tests:
All commands ran from backend/ with .venv/bin/python -m pytest -q -p no:cacheprovider. My files plus the monitor, ledger and autorun files (test_official_data_{consumers,downstream,promotion}, test_orchestrator_research_wiring, test_canonical_world_brief_denials, test_research_contract_finalization, test_resolution_monitor, test_forecast_ledger, test_resolution_autorun): 297 collected, all pass (scratchpad fix3/H/owned_run3.txt). A wider run over 68 test files that reference my modules, excluding test_export_demo_site_data: 6 failures, all in files other slices were editing at that moment. These were 4 FRED-fallback tests in test_data_sources.py (data_sources.py was modified at 22:33), test_report_data_publication::test_structured_forecast_and_real_api_publish_without_bypass (G1), and test_report_visualizer_official::test_detail_chart_draws_thresholds_fan_bands_in_a_recent_window (G2). None goes through H code. Before/after proof for the fix3 changes: each change was swapped out temporarily, the new tests failed (red_fix3.txt 2 failed, red_fix3_window.txt 1 failed, red_fix3_monitor.txt 5 failed), and the files were restored and checked with cmp. ruff (F,E9) passes on every touched file; check_env_drift.py --strict exits 0.
Live checks:
All logs are under the scratchpad at fix3/H/. live_fetch.log: real MCP fetch run through with_data_keys.sh, with the cache in scratch and about 7 FRED calls spaced 2.5 s apart; no BLS or native IMF calls. live_downstream.log and live_downstream2.log: binding, lookups, graph snapshot, world briefs (unversioned and canonical), the 639-brief marker sweep and the relocation check; offline, no provider or LLM calls. live_monitor.log: resolution monitor against live FRED, BIS and World Bank, with the ledger and report in scratch. live_monitor_unpublished.log: CPI YoY 2026-09 comes back pending, not degraded. No paid LLM calls were made and no keys were printed.
Open issues:
- G1 (report_agent.py): not yet wired to put forecast_ledger.official_data_track_record(d) into forecast.json historical_calibration as a separate 'official_data_track_record' field. Omit the field when the function returns None so output stays unchanged.
- A/A2 (data_sources.py): when BIS has no data for a window, the error comes back as provider_error (the text says the result is 'genuinely empty') instead of not_found. A BIS anchor waiting for publication therefore shows manual rather than pending in the monitor.
- A/A2: the usgov EIA (eia_query 'route' undefined) and BEA ('No data exists for the Year/Frequencies passed') recipes fail live.
- A/G2: validate_data_anchor accepts anchors on series that can never auto-resolve (aggregated daily data, World Bank series). The monitor refetches them on every run and they always end as manual. Consider rejecting them or flagging them as not auto-resolvable.
- The README is owned by A: backend/tests/fixtures/data_sources/README.md does not yet list real/downstream/ (fred_gepucurrent_stored.json and the new fred_cpi_yoy_unpublished_period_error.json).
- Other slices' tests were red during my run (see tests_run); the lead should re-run them once those slices finish.
- Edge case: a resumed v3 run rewrites meta.json started_at to the resume time, so its research window starts at the resume. Captures from the first run that crossed UTC midnight are then judged with the strict cutoff. This is rare and was left as is.

## finish:G1 (wf_05e3b908-45d)

G1 is finished. All ten assigned findings (RPT-1, RPT-2 + MISSED-1, RPT-5, RPT-10, RPT-11, RPT-12 backend, RPT-13, RPT-14, RPT-16, MISSED-4) are implemented and tested. Most of the code was already in place from fix2 M1–M3. This session I checked each finding, fixed the gaps I found, and wrote the missing tests. The new end-to-end tests use the real bundle `backend/tests/fixtures/data_sources/real/report_bundle-2026-10-11.json` in English and Chinese, with a model stub that raises on every call and no purity pass. Each run goes `_persist_official_data` → Part 1 → `_insert_official_indicators_section` → `_inject_visualizations` → three-part skeleton (its model call fails and the report is left unchanged) → `_append_resolution_section` → `_apply_report_lint` → `_stabilize_publish_markdown` → `_enforce_final_publish_audit` (`hard_passed`) → `save_report`. Both languages pass the final audit with zero language-contamination lines. The tests check that the Key official indicators table equals the stored values, that every chart has its source caption and that Chinese reports show Chinese chart titles. They also check that the six exact-value official sentences keep their [S#], that the anchored watch table is tagged, that `official_data.json` is saved with its sha256, and that `GET /api/report/<id>/official-data` returns the indicators. The new tests fail (red) against HEAD and against the current tree with only my four files reverted to HEAD, and pass now. A live run on six freshly fetched series also published cleanly in both languages. Without official data, every prompt I touched is byte-identical to HEAD.

Done:
- Checked every assigned finding in the fix2 code and its tests: RPT-1 (claims checked against the stored series), RPT-2 + MISSED-1 (Chinese chart titles; official caption and table lines exempt from purity and contamination checks), RPT-5 (data pack keeps whole rows and names omitted series), RPT-10 (Key official indicators section, outline rule, charts placed in that section), RPT-11 (executive brief indicators and anchored watch lines), RPT-12 backend (official_data.json with sha256 and research binding, GET /api/report/<id>/official-data behind the publication gate, lang=en|zh), RPT-13 (backfill keeps the stored data and removes orphan Source lines), RPT-14 (data pack passed to chat, critique, premortem and fallback extraction), RPT-16 (uncited datasets get an [S#] after the research sources), MISSED-4 (one caption helper using the provider name and a localized frequency)
- RPT-16 completed: 'Official series to watch' rows now carry this report's [S#]. `_append_resolution_section` passes `source_index`, and the new `_official_watch_line_support` accepts a row only if it is byte-identical to the row rebuilt from the forecast, the stored data and the citation index.
- RPT-1 hardened: new `_official_carrier_support` returns False when a claim names a different country from the cited series. `_quantitative_semantic_decision` no longer lets an excerpt-based tag through when the stored series contradicts the claim. Before this, 'China's unemployment rate was 4.2% in September 2026.' was tagged with the US UNRATE source [S1].
- Year-over-year changes for point-unit series no longer show a relative percent: the Sahm indicator now reads '-0.23' instead of '-0.23 (-100%)'
- `_spine_facts_budget` default changed from 3000 to 3500 to match derive_forecast_spine's facts cap
- No-data safety (fix contract §0.1): new `_OFFICIAL_ROW_ERRORS`; a stored row that cannot be summarized is skipped in the data pack, citation index, indicator table and watch check, so the agent constructor and the report never fail on it. The indicator-row and watch-row lookups are now cached.
- New test file backend/tests/test_report_official_publication_real.py: 18 test functions, 26 cases. Covers end-to-end EN/ZH publication, the indicator table, chart captions, exact-value sentences, the watch table, the report-local data file and API (including a tampered digest, lang=fr → 400, unpublished → 409, missing → 404), the executive brief and digest in EN/ZH, the Chinese DEXCHUS report with no purity pass (RPT-2/MISSED-1), claims checked against the stored series in EN/ZH, the citation repair on uncited claims (S1, S13, the China claim, Chinese), whole-row packs with an omission note, the spine/critique/premortem/fallback data pack, outline and chat prompts, a backfill run on a published report (RPT-13), strip_generated_visuals, the no-official-data case, and a malformed stored row
- Updated test_report_data_publication.py::test_structured_forecast_and_real_api_publish_without_bypass: the S1 count now equals charts plus the tagged watch rows, and every watch row must end with [S1]
- Red-before evidence: (a) the new test file run on a HEAD export (fix3/G1/head) fails 25/25 then-existing cases; the published-fixture ones error at setup on G2's new _normalize_binaries(language=) argument, the rest fail on missing methods or behaviour. (b) Run on the current tree with only my four files at HEAD (fix3/G1/g1revert), it also fails 25/25: missing _persist_official_data, unsupported true sentences, '最终 Markdown 含 1 行目标语言污染' (one contaminated line) in the Chinese report, missing [S1]/[S13] and the China claim tagged S1, a leftover Source line, the API route returning 404, and missing budget/plan-rule/pack arguments. (c) The watch-table, China-claim and malformed-row tests also fail against the fix2 state before this session.
- Prompt identity: a script dumped every prompt I touched (outline, spine, critique, premortem, fallback extraction, post-hoc critique, chat), plus the sources index and resolution section, with no official data, in both the HEAD export and the working tree. The dumps are byte-identical (fix3/G1/probe/prompts_head.json vs prompts_work2.json).
- Live check (fix3/G1/live/run1.log, with_data_keys.sh, scratch cache): fetched fred:UNRATE, fred:SAHMREALTIME, fred:DGS10, bis:WS_CBPOL/M.US, wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA and usgov:treasury/mts_deficit in 8.5 s (3 FRED calls, no BLS). EN and ZH reports both passed the final audit with zero contamination and passing caption checks; the claim was kept, all 10 binaries anchored, the watch rows were tagged, and there were no model calls. The live WDI row now shows as historical (2.161%, 2025).
Tests:
cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider on all 50 test files that touch report_agent, exec_brief, backfill_report_visuals, report_lint or api/report (test_export_demo_site_data.py excluded as instructed), plus tests/test_report_official_publication_real.py, test_forecast_extractor.py, test_forecast_extractor_official.py and test_report_visualizer_official.py. Final run after the last edit: exit 0, no failures or errors (about 1,180 tests; 13 xfail and 1 skip were already there). Red-before runs are in fix3/G1/red_head.txt and fix3/G1/red_g1revert.txt. `uvx ruff check --select F,E9 --ignore F401,F841,F541` on all touched and owned files: All checks passed. The full suite was not run (lead's job).
Live checks:
fix3/G1/live/live_publish.py run through scratchpad/live/with_data_keys.sh with DATA_SOURCES_CACHE_DIR=fix3/G1/live/cache. Six live series fetched in 8.5 s, then EN and ZH reports published with every model call raising: final audit passed with zero contamination lines and passing caption checks, the exact claim survived, the watch rows were tagged, and no model was called. Output: fix3/G1/live/run1.log, final_English.md, final_Chinese.md.
Open issues:
- Already true at HEAD and not changed: the citation-repair pass adds the marker after the sentence's final punctuation ('...August 2026. [S13]', Chinese '...亿美元。 [S13]'). Moving it before the punctuation would change existing behaviour outside this slice.
- By design, an uncited Chinese claim that contradicts the stored series (e.g. '失业率在2020年4月达到15.2%的峰值。') stays in the report without a citation and counts against the coverage gate; it is not deleted. A cited contradicted claim always loses its marker. I did not add deletion of uncited claims because a word-based match could delete true statements about related series such as U-6 or youth unemployment.
- G2's anchor matcher rejects two natural phrasings: 'The 10-year minus 3-month Treasury spread < 0% in June 2027' (EN) and '联邦基金有效利率在2027年12月 < 3%' (ZH). These binaries publish without an anchor; the matcher is G2's code.
- Already true at HEAD: if one source is cited more than 20 times (REPORT_MAX_CITATIONS_PER_SOURCE), the overuse repair may strip [S#] from chart caption lines that contain no numbers, and the caption audit would then fail.
- Lead action: commit backend/tests/test_report_official_publication_real.py (new, untracked) together with the real fixture directory it reads (backend/tests/fixtures/data_sources/real/, also untracked).

## finish:G2 (wf_05e3b908-45d)

G2 is finished. All eight findings assigned to forecast math and report charts are implemented, tested and checked against real data: RPT-3, RPT-4/I1 (contract section 1.8), RPT-6, RPT-8, RPT-9, RPT-15, MISSED-2 (consumer side) and downstream M1.

The two G2 test files the earlier attempt mentioned were never written, so I wrote them:
- /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_forecast_extractor_official.py (72 cases)
- /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_report_visualizer_official.py (11 cases)

They use the real carrier, the policy-3 history fixture, the report bundle and replayed provider captures.

Bugs fixed during the review:
- In the anchor matcher, the unit 'Percent' matched the start of 'percentage points', so a wrong proposition was anchored.
- Common Chinese criteria and statement forms never anchored: '于/在' between the comparison and the period, '判定为是' before a source, and a title qualifier such as '（月均）'.
- Units with a scale word ('Billions of Chained 2017 Dollars') could not anchor. '$24.5 trillion' now compares as 24500.
- A 4-digit number inside the comparison (a threshold, or the '2017' in the units) was read as a second period.
- Scenario bands were never drawn on series with no complete history, so the WDI detail chart was empty.
- Detail-chart slots went to scenario-range-only series before series with settleable thresholds.

Chart changes, made after looking at the renders:
- Detail charts zoom to recent history instead of being flattened by the 2020 spike.
- Legend order is fixed, and the threshold tag in the plot margin is short ('> 45 trillion').
- The legend shows 'empirical base rate: insufficient history' when the history is too short.
- The forecast-horizon line is solid, so it no longer looks like the dotted unknown-status data line.
- The static (matplotlib) fallback uses constrained layout, an outside legend, two-line titles and 40T/-200B axis ticks. A Chinese scenario name uses a CJK font, or the chart is skipped.

Evidence:
- Against the original code, 60 of the 83 new tests fail. The 23 that pass are the guard cases that keep the original rejections.
- With official data absent, every prompt and table I touched is byte-identical between the original code and now (same sha256).
- The 32 related test files pass except one H downstream test, which fails the same way with the original G2 modules.
- I rendered the real 2026-10-11 carrier in English and Chinese with both Plotly and matplotlib, and a live policy-3 carrier, and looked at every official chart.

Done:
- RPT-3: anchors are admitted from natural English and Chinese statements and realistic criteria. Negation, compound, conditional, deadline, wrong-period, second-number, wrong-geography and wrong-unit statements are still rejected. One canonical settlement sentence is appended in the report language and is idempotent.
- New fix: the unit 'Percent' no longer matches the start of 'percentage points' (that let a wrong anchor through).
- New fix: Chinese criteria with '于/在', '判定为是' before a source, and titles with a trailing qualifier such as '（月均）' now anchor.
- New fix: scaled units such as 'Billions of Chained 2017 Dollars' anchor ('$24.5 trillion' = 24500). Digits inside the comparison or the units are not read as periods. Unit mentions in prose are treated as description, not as a second number.
- RPT-4/I1 (section 1.8): the empirical h-step base rate is checked against an independent brute-force calculation on the real UNRATE fixtures. It is computed from complete history only (fewer than 30 samples gives no base rate). It appears in the empirical fan, the outside-view prompt block, the Part 1 table column, the watch table and the divergence flag (difference over 25 pp). Projections, estimates and partial periods are excluded, proven on a replayed WEO capture.
- RPT-6: partial periods are labelled and drawn as open circles, separate from history. The latest-observation marker uses the last complete month. Completeness is re-derived for policy-2 rows.
- RPT-8: the dashboard covers every carried series in two columns and splits into a second figure past 12. Detail charts exist only for anchored or banded series, thresholds first, capped at 6, and series over the cap are recorded in the manifest's skipped list.
- RPT-9: metric_range is validated in the spine and kept through the critique. Bands are drawn for monthly and annual series, including series with no complete history. Past periods are not drawn. Signed ranges parse.
- RPT-15: values use format_value and the scaled value in tables, settlement sentences and chart labels. The horizon label sits above the plot area and threshold tags sit in the right margin.
- MISSED-2 (consumer side): a policy-3 WDI row is classified as history and anchors with a base rate. Policy-2 WDI rows keep their original semantics.
- Downstream M1: status uses exact prefixes. fred:GEPUCURRENT is history; the GEP capture splits into history, estimate and projection.
- Red-before run against the original modules: 60 failed and 23 passed. All 83 pass now.
- Absent-data proof: prompts and tables with official data absent are byte-identical between the original and current code.
- Live check: 7 series fetched through the current data layer (3 FRED calls, 0 BLS) and charts rendered from them.
- Visual check: every official chart from the real fixture (English and Chinese, Plotly and matplotlib) and from the live carrier was opened and reviewed until it was publication-grade.
- Progress notes: /private/tmp/claude-501/-Users-rogerlin-Downloads-DeepResearchForecast/52225542-51e1-41e1-b738-38d44834da7e/scratchpad/fix3/G2-notes.md
Not done:
- RPT-16 watch-row [S#] tags: render_resolution_block(source_index=...) is implemented and tested, but report_agent._append_resolution_section (G1's file) does not pass source_index, so the [S#] tags never reach the report.
- Legacy snapshot agreement: official_data.historical_snapshot (H's file) calls api.observation_kind directly. For daily-to-monthly rows stored under policy 2, the snapshot shows no history while the pack, charts and anchors show 2026-09. Rows stored under policy 3 agree.
Tests:
- Owned files plus the closest report test files (9 files): 359 passed.
- 32 dependent test files (about 950 tests: report official data and publication, visualizer, exec brief, downstream, consumers, monitor and others): all pass except tests/test_official_data_downstream.py::test_snapshot_separates_display_safety_from_resolution_safety, which expects '| FY2026 |'. It fails the same way with the original G2 modules, and its source and test files were being changed by other slices at the time.
- Red-before run of the new tests against the original modules: 60 failed, 23 passed. Logs: scratchpad/fix3/G2/red_run.txt and red_run_full.txt.
- ruff (F,E9) on the four owned files: all checks passed.
Live checks:
Live data, fetched through the wrapper script with a cache under scratchpad/fix3/G2/live, policy 3 (3 FRED calls, 0 BLS, IMF via Data360):
- fred:UNRATE, 240 months
- fred:DGS10, 70 months, current month partial
- fred:GDPC1, 66 quarters
- bis:WS_CBPOL/M.US, 201 months
- usgov:treasury/debt_to_penny, 46 months
- wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA, 36 years, history
- wb:IMF_WEO_NGDP_RPCH/USA, 30 years, with estimate and projections to 2031

Charts were rendered from this carrier in English (Plotly) and Chinese (matplotlib) and every chart was viewed. Every renderable anchor (5 of 6) was admitted with a base rate. The 6th uses fred:FEDFUNDS, which was not fetched.

The real 2026-10-11 fixture was rendered in all four language and renderer combinations (scratchpad/fix3/G2/final_*); summary sheets are sheet_final_*.png.
Open issues:
- Lead: G1 should pass source_index=self._citation_index (or the equivalent RPT-16 index) to render_resolution_block in report_agent._append_resolution_section, so watch rows carry [S#].
- Lead: H's historical_snapshot treats daily-to-monthly months in policy-2 stored rows as partial, while forecast_extractor.official_observation_kinds re-derives completeness for them. Policy-3 rows agree. Either H calls the shared helper, or the data layer adds the same legacy rule.
- Lead: an H downstream test (test_snapshot_separates_display_safety_from_resolution_safety, expects FY2026) fails independently of G2. The files involved were being modified by other slices during this session.

## finish:G3 (wf_05e3b908-45d)

G3 (frontend) is complete. It adds:
- official-indicator tiles on the Forecast Dashboard (latest value and period, year-over-year change, sparkline, source link, [S#] tag, CSV export of the stored observations);
- a data-anchor column in BinaryForecastTable;
- official-source attribution on chart gallery cards;
- an Official Data tab in the research dossier;
- a data-source test card in Settings.

Everything works in EN and 中文 through the existing L() i18n system. The number formatters match the backend's data_sources format_value/format_change/scaled_value exactly, including how exact rounding ties are handled. A test checks that the frontend reproduces every display string the real official-data endpoint returns. The test fixtures are real responses captured through the actual Flask routes from a real-bundle publication, not invented payloads. When a report has no official data, the rendered markup is identical to HEAD's apart from invisible comment nodes. Frontend unit tests: 124/124 pass with 0 Vue warnings. The build succeeds (output went to a scratch folder; frontend/dist is gitignored anyway).

Done:
- RPT-12 frontend: new frontend/src/utils/officialData.js with pure helpers. They cover: number formatters that match the Python data layer (including half-to-even rounding of exact ties); period, frequency and observation-kind labels; safe links; indicator tile models; sparkline geometry; a series index (label and [S#]); CSV export of the report's stored observations; dossier dataset rows; and parsing of the data-source test response.
- ForecastReport.vue: loads GET /api/report/<id>/official-data per display language (cached, guarded against stale responses, and silently hidden on 404, 409 or available:false). The Forecast Dashboard now shows official indicator tiles even when there are no scenario cards. Each tile shows the exact latest value, a '≈ 40.09 trillion U.S. dollars' line for very large values, units, period and frequency, year-over-year change, a projection or unclassified badge, a sparkline, the provider link, the [S#] tag, and a CSV button. Chart gallery cards show the official source attribution (series title, provider link, [S#], units, frequency, seasonal adjustment).
- BinaryForecastTable.vue and binaryForecasts.js: a data-anchor column appears only when at least one forecast has a data_anchor. Each cell shows the series label (link plus the report's [S#]), the comparator, threshold and period, the latest observation against the threshold (a 'meets threshold' chip or the gap, in pp or 个百分点), and the empirical base rate p with n and the model-minus-base-rate gap. The gap is highlighted when it exceeds 25pp, the same threshold the backend quality check uses. A tooltip adds the window, steps ahead, σ distance and the p10–p90 range. The column fits the 760px report column.
- vizManifest.js: gallery cards keep source_caption and provenance. chartAttribution() builds entries from provenance first and falls back to parsing the audited caption, and it localizes frequency and 'adjustment unknown' for zh. A test checks that the entries rebuild the audited source_caption exactly for both the EN and the ZH manifests.
- L22 (dossier official-data list): DossierViewer gets an Official Data tab built from data/datasets.json via GET /api/research/<pid>/artifact/datasets. It lists label, geography, series id, KIQs, latest observed value and period, units and frequency, coverage, observation count, provider link and [S#]. The manifest is requested only when the pipeline status lists the 'datasets' artifact, so there are no 404s. Chart and CSV links appear only when status.artifacts registers chart_<file> or dataset_<file> (or its _partial key), so no link is ever dead. ResearchView now passes those artifact names to the dossier. I also added a fallback to the Report tab when a conditional tab disappears.
- I4 frontend: testDataSources() calls POST /api/settings/data-sources/test with a 120 s timeout. SettingsMenu gets an 'Official data sources' card: one row per provider in fixed order (FRED, BLS, BIS, IMF, World Bank Data360, US Gov Open Data) with a state chip, latency, detail text and key names marked set / not set / invalid (never key values), plus a summary line and distinct messages for a 409 busy response, data sources disabled, and network failure.
- Tests: tests/sfcHarness.mjs compiles the real .vue script and template with @vue/compiler-sfc and renders through the Vue server renderer. New: officialData.test.mjs (15), dossierOfficialData.test.mjs (5, runs the real component setup), forecastReportOfficialData.test.mjs (6, server-renders ForecastReport and BinaryForecastTable with real payloads), settingsDataSources.test.mjs (2, server-render). binaryForecasts.test.mjs and vizManifest.test.mjs each gained 2 tests; existing gallery-shape tests were updated for the new fields; the dossierTranslationEnvelope harness gained the new imports.
- Real fixtures: frontend/tests/fixtures/official/ (with a README) holds official-data EN and ZH, forecast binaries, the official viz manifests (EN and ZH reports), a v3 datasets.json, and a live probe plus a live endpoint body. All were captured through the real Flask routes by fix3/G3/export_fixtures.py and scanned for key values (none found).
- Visual check in the browser pane using a scratch Vite harness with the API mocked by the real fixtures, EN and 中文. Several layout fixes came out of it. CSV downloads were checked by intercepting the click, so no real file was downloaded.
Not done:
- L22-csv-after-full-runs: In a full pipeline the dossier CSV button cannot appear, and neither can the series chart link when a chart was never rendered. Dataset CSVs are registered only as dataset_<file>_partial during research scans, those keys are removed at PREPARE, and nothing registers them at research completion. The frontend already lights the links up as soon as status.artifacts lists them, but the backend fix is in pipeline_orchestrator.py, which slice H owns.
- L22-demo-exporter: The other half of L22 (the demo exporter copying datasets) is outside frontend/src and was not part of the G3 assignment.
Tests:
- `npm --prefix frontend run test:unit`: 124/124 pass (baseline was 92), 0 Vue warnings. Output: scratchpad/fix3/G3/unit_final.txt.
- `npm --prefix frontend run build -- --outDir scratchpad/fix3/G3/fe-dist --emptyOutDir`: exit 0, no warnings (build_final.txt).
- Before/after check: I ran the new tests against the HEAD versions of the components, copying in only the new utils so failures are behavioural. All 17 new behavioural tests fail and the 12 existing ones pass (red_head_final.txt).
- Parity check (scratchpad/fix3/G3/parity_absent.mjs): with no official data and no data anchors, the rendered ForecastReport markup equals HEAD's once comment nodes (source comments and empty v-if placeholders) are stripped.
- ruff: not applicable (no repo Python files changed).
- Backend pytest was not run: no backend files changed (the full suite belongs to the lead).
Live checks:
POST /api/settings/data-sources/test through the real Flask route, run with with_data_keys.sh and DATA_SOURCES_CACHE_DIR=fix3/G3/cache: HTTP 200, 61.3 s wall. All six providers came back ok:
- fred 1.42 s (live, 118 observations)
- bls 0.34 s (handshake only, no BLS data request)
- bis 1.36 s
- imf 60.96 s (30 observations to 2031)
- usgov 4.65 s
- wb 6.9 s (WDI now returns 24 observations; it was degraded in T's earlier probe)

The script checked that no key value appears in the response. The body is saved as fixture data_sources_probe.endpoint.json and is covered by a unit test. Provider calls: one FRED, one BIS, one IMF, one WB and one usgov sample, zero BLS data calls, no paid LLM calls.

UI check in the browser pane (scratch Vite harness, API mocked with the real fixtures): the dashboard tiles, data-anchor column, gallery attribution, dossier Official Data tab and Settings probe card render correctly in EN and 中文. CSV buttons produce blob downloads named fred_UNRATE.csv and the research CSV file name; this was verified by intercepting the click, so no real download happened.
Open issues:
- Slice H (pipeline_orchestrator.py) should register dataset_<csv> and the data_*.png charts at research completion (_record_stage_artifacts). Today CSVs exist only as live-scan _partial keys, which are removed at PREPARE. Until that lands, the dossier CSV link appears only for research-only runs that a scan caught.
- In the real v3 run backend/uploads/pipelines/pipe_261de6107490, datasets.json references charts/data_*.png files that were never rendered. The charts folder holds only the timeline, market and metric charts. The dossier hides those links correctly, but slices F/D should confirm on a fresh run that series charts are now rendered.
- The README and feature docs for the new UI surfaces (dashboard tiles, data-anchor column, dossier Official Data tab, Settings data-source test) are still to be written; per the fix plan they belong to the lead.
- Scratch evidence and tooling in scratchpad/fix3/G3/: export_fixtures.py, live_probe_endpoint.py, parity_absent.mjs, redtree/, visual/, the build and unit logs, and progress notes in fix3/G3-notes.md.

## finish:A2 (wf_05e3b908-45d)

A2 (data layer, providers) is done. In the final whole-catalog live run of backend/scripts/datamcp_smoke.py, all 288 requested ids came back ok and the script exited 0: fred 82/82, wb 54/54, bis 50/50, usgov 51/51 (including all 21 EIA and 8 BEA recipes), bls 45/45 and imf 6/6. The other 34 IMF ids were skipped by the default cap of 6. Run time was 393.5 s. Every id was served by its MCP server, every unit matched the catalog, and no fallback route was needed. BLS used 2 batched calls in that run and 7 in the whole session. The related test files (23, including the 3 new ones) give 1472 passed and 1 skipped. On the pre-A2 code, 43 of the new or updated tests fail and 11 pass; the 11 are controls and the smoke script's selection tests.

Done:
- EIA and BEA usgov adapters: the old adapter sent Treasury-style arguments, so all 29 EIA/BEA recipes failed. The adapter now dispatches on the recipe kind (treasury, usaspending, sec, eia, bea_nipa, bea_industry).
- EIA: eia_query is paged with length/offset (200 rows, about 22 kB, inside the usgov 40 kB response limit). Every row must carry the recipe's facet values and its verified unit text, and duplicate periods fail. An empty answer is reported as not_found.
- BEA: tables are read in year chunks that stay under the tool's per-line cap (NIPA 2 years per call, industry 1 year per call, newest first). Industry quarters such as 2025QIV are parsed. The NIPA line must match exactly once. A year BEA has not published yet ('Invalid year' or 'No data exists') is skipped and recorded in provenance.chunks.
- A keyed EIA/BEA recipe whose key is missing returns unknown_recipe without calling the provider.
- P-FRED429 (following the verifier's correction): a 429, 5xx or timeout falls back to the keyless fredgraph CSV for catalog ids only, recorded as route fred_csv with provenance.fallback_reason. Other ids return a retryable error. If the CSV also fails, the error is retryable and names both failures. Receipts describe only the route that delivered the data.
- FRED pacing lives in the hub, which is one per process: ServerSpec.max_calls_per_minute and a rolling-minute window. The FRED default is 50 calls a minute (about 100 upstream requests, under the key's 120); DATA_SOURCES_FRED_PER_MINUTE sets 1-120. A call that cannot get a slot within its deadline fails fast as rate_limited.
- A FRED key the provider rejects is remembered for the process; every DataSources in the process then uses the CSV route and providers() reports key_invalid.
- A FRED MCP server that is down (not built, or crashed past its restart) also falls back to the CSV route when a key is set.
- FRED 'The series does not exist' (HTTP 400) is now unknown_series. The frequency parser now reads FRED labels such as 'Daily, 7-Day'.
- P-FREDCAP: a long daily window now uses FRED's own monthly aggregation (catalog avg or end-of-period; API frequency=m, CSV fq=Monthly) for older months and native daily data for the last 24 months. The open month stays partial and the last daily value is kept. Ids not in the catalog that overflow one 5000-row page are refetched the same way. provenance.server_aggregation records what was done.
- BLS: a rejected key now makes the hub respawn the BLS server without the key (new McpHub.restart_without), and the request is retried once under the keyless quota; providers() reports key_invalid. Per-series notices ('No Data Available … Year', 'Unable to get Catalog Data …') are kept in chunk notices instead of failing the whole batch; the second one is what broke 20 ids in the first live run. 'Invalid Series' is reported as unknown_series for that id only.
- P-USGOV: a fiscal year counts as complete only 120 days after it ends (FY2026 shows as partial at 2026-10-12).
- Search (P-SEARCH, P-WBGEO, V3-M2): search now runs in this order: strong catalog hits, live FRED search, Data360 search, BIS/Treasury discovery, weak catalog hits last. A Chinese query is translated to English for provider search, and 'undefined'/'null' notes are dropped. Data360 countries come from whole-word geography names; no country means WLD, several are sent as a ';' list with one hit per covered country. EIA/BEA entries are only found when their key is set. An empty Data360 result is no longer logged as a failure.
- Notes: for catalog FRED ids, the curated notes now win over FRED's notes, which move to provenance.provider_notes. The monthly-aggregation note is placed first so it survives the 400-character cut.
- Small additions: DataSources.hub_status(); restart_without marks a still-queued launch as replaced so it never starts a second child with the old key.
- backend/scripts/datamcp_smoke.py (new): paced live sweep with --providers, --series, --max-per-provider (default imf=6, picked across IMF datasets), --bls-start (default one-year chunk), --cache-dir (default a fresh temp dir), --deadline and --report (JSON). Exit 0 only when every requested id is ok, 1 otherwise, 2 for usage errors. Ids whose key is not configured are reported as skipped.
- Fixtures: 11 new real captures in backend/tests/fixtures/data_sources/real/providers/ (EIA, BEA, long DGS10 via API and CSV, BLS messages and rejected key, FRED error texts and search, Data360 search by geography, BEA unpublished year). README.md documents them and the real/legacy, real/gateway, real/visuals and real/downstream directories (E's open note).
- Tests: new test_data_sources_providers.py (33), test_data_mcp_pacing.py (7) and test_data_sources_smoke.py (7). test_data_sources.py now has the verifier's three FRED fallback cases; test_data_sources_normalization.py's redaction test was updated for the notes change.
Not done:
- E-data_tools-catalog-short-circuit: Not my file. deerflow_bridge/data_tools.py _catalog_answer still answers from any 6 catalog hits, weak ones included, so the legacy engine never reaches live search for vague queries. It should use search_catalog_scored and require CatalogHit.strong, to match DataSources.search.
- D-seeder-strong-hit: Not my file. linear_research.py takes the first data_search line. That line is now a strong catalog hit when one exists, otherwise a live FRED or Data360 hit. The verifier asked that the seeder prefer a strong catalog hit or skip the seed.
- H-env-example: Not my file. .env.example should document DATA_SOURCES_FRED_PER_MINUTE (default 50, range 1-120; FRED tool calls per rolling minute for each process's hub).
Tests:
All commands were run from backend with .venv/bin/python -m pytest -q -p no:cacheprovider. Related files, 23 of them (test_data_catalog, test_data_sources, test_data_sources_providers, test_data_sources_smoke, test_data_mcp_pacing, test_data_sources_normalization, test_data_mcp, test_data_sources_config, test_data_visuals_official, test_data_mcp_deadline, test_data_sources_interfaces, test_forecast_extractor_official, test_legacy_official_data, test_official_data_consumers, test_official_data_downstream, test_official_data_end_to_end, test_report_official_data, test_report_official_publication_real, test_report_visualizer_official, test_research_gateway_official_data, test_settings_data_sources_probe, test_v3_official_data, test_research_gateway): 1472 passed, 1 skipped, exit 0 (scratchpad fix3/A2/related3.txt). The three new files re-run after the last edit: 47 passed. Red-before check: fix3/A2/run_with_before.py loads HEAD data_mcp.py (my changes are the only diff from HEAD) and a pre-A2 data_sources.py rebuilt by make_before.py (function positions match the original file). Against it the new or updated tests give 43 failed and 11 passed; the 11 are controls and the smoke script's selection tests (fix3/A2/red_before_final.txt). Separately, the 'superseded launch' assertion fails when the restart_without fix is removed (run_noowner.py). ruff check --select F,E9 is clean on all touched files.
Live checks:
All live calls went through scratchpad/live/with_data_keys.sh, with DATA_SOURCES_CACHE_DIR under scratchpad/fix3/A2.
- Probes (fix3/A2/probe/*.json): EIA paging and the response-size limit, BEA future and unpublished years, FRED monthly aggregation on both API and CSV, FRED 400 texts for a missing series and an unregistered key, BLS rejected key and per-series messages, Data360 search with WLD and multiple countries.
- Captures for the fixtures (fix3/A2/capture.py): all 7 replays came back ok.
- Smoke run 1 (fix3/A2/smoke1.log): 268/288 ok. The 20 failures were one BLS batch rejected whole by the harmless 'Unable to get Catalog Data' notice; fixed, and the 20 ids then gave 20/20 with 1 BLS call (smoke3.log).
- Live search (live_search.log):
  - '半导体出口' returns FRED semiconductor export price indexes (IY3344, IQ21320).
  - 'battery storage capacity' returns EIA battery capacity first, then a Data360 world-level hit.
  - 'urban population growth' on Data360 returns world-level ids.
  - '美国十年期国债收益率' returns fred:DGS10 first.
- Final whole-catalog run (fix3/A2/smoke_final.log and smoke_final_report.json): 288/288 ok, exit 0, 393.5 s. Tool calls: fred 82, bls 2, bis 50, imf 11, wb 108, usgov 133. Every route was mcp and every unit matched the catalog.
- BLS calls this session: 7 of the 10 allowed. FRED was paced at 30 calls a minute in the smoke runs.
- No paid LLM calls.
Open issues:
- DataSources.search now calls live providers whenever there are fewer strong catalog hits than the limit, as the verifier asked. A search therefore costs 1 to 4 provider calls (about 1-8 s) where it used to cost none for weak catalog matches. Consumers with search budgets (C and E) should know this.
- In the final run, usgov:spending/total has no 'latest observed' value. This is the existing A1 status policy (the feed loses missing amounts, so every row is 'unknown' and not resolution-safe), not a fetch failure.
- BEA quarterly industry recipes cost one call per year: a default 10-year window is 10 usgov calls, about 0.3 s each live.

# Glue + agent-usage audit results (exported from workflow wf_6fa7895f-0c8)


## glue:E

Role E is done. In legacy `data_search`, a weak catalog match no longer stands in for live provider search. Before, `data_tools._catalog_answer` answered for free whenever the catalog had any 6 hits, including weak ones. Almost every economic query has 6, so legacy agents never got to live FRED or Data360 search. 'Atlanta Fed wage tracker' returned the BIS policy rate, and 'semiconductor exports' returned a semiconductor production index.

The search is now free only when 6 or more STRONG catalog hits fill the answer. That is exactly the case where `DataSources.search` itself returns before calling a provider: same `search_catalog_scored` call, limit=50, the instance's own environment and the same provider filter. Every other query falls through to the charged `DataSources.search`, which lists strong hits first, then live provider results, then weak hits.

Two small follow-ons in the same file:
- **Exhausted search budget:** the `DATA_BUDGET_EXHAUSTED` message now also lists any strong catalog series for the query. Showing them costs no provider call. Weak matches are never listed.
- **Tool descriptions:** the `data_search` docstring and `DataSearchArgs` now say usgov includes EIA and BEA, ask for short English terms (FRED search is English-only, matching the data-sources skill and the v3 schema), and describe the real result order.

When official data is disabled, nothing changes in prompts or registration, because the tools are not registered then.

Live check through the real providers: 'policy rate' answered free with no provider call. 'Atlanta Fed wage tracker' now returns the actual Atlanta Fed wage-growth-tracker series (`fred:FRBATLWGT...`). 'semiconductor exports' returns `fred:IY3344` export price indexes. 'US unemployment rate' returns its 3 strong catalog series, then live FRED results.

Done:
- Replaced data_tools._catalog_answer with _strong_catalog and _catalog_lines. A search is answered free only when there are at least _SEARCH_HITS (6) strong hits in allowed providers, using the same call DataSources.search makes: search_catalog_scored(query[:300], provider=..., limit=50, env=getattr(sources, '_env', None)). Otherwise the charged DataSources.search runs.
- Added a shared _SEARCH_HITS = 6 constant, used by both the free catalog answer and the charged search (`_fetch` limit and slice), so the two always render the same number of lines.
- When the search budget is exhausted, the denial still lists any strong curated series under the note 'Curated catalog series matching this query (no live search ran):'. Weak-only queries keep the plain denial text.
- Tool text: DataSearchArgs.provider now lists 'usgov (U.S. Treasury, USAspending, EIA, BEA)'. DataSearchArgs.query asks for short English terms, since live FRED search reads English only. The data_search_tool docstring names EIA and BEA and says 'Curated catalog series that answer the query come first, then live provider search results'.
- New tests in backend/tests/test_legacy_official_data.py: weak catalog matches never replace live search (3 cases: vague, specific but uncatalogued, partly strong), the exhausted-budget listing, the description wording, and an end-to-end test through a real DataSources whose hub replays the real capture fixtures/data_sources/real/providers/fred_errors_and_search.json. That last test covers both paths: the free answer equals DataSources.search output with no provider call, and the charged path makes exactly one fred_search call that is reused when repeated.
- Red before the fix: against a copy of the pre-change data_tools.py (glue/E/before/), all 6 new tests failed and the existing control test 'policy rate is free' passed (glue/E/red_before_new.txt). After the fix all of them pass.
Tests:
All commands ran from backend with `.venv/bin/python -m pytest -q -p no:cacheprovider`.
- tests/test_legacy_official_data.py: 76 passed.
- 13 related files: 464 passed, exit 0 (output in scratchpad glue/E/related.txt). The files were test_legacy_official_data, test_data_sources_config, test_official_data_end_to_end, test_v3_official_data, test_loop010_global_synthesis, test_loop010_research_contracts, test_bridge_extensions_config, test_bridge_market_tools, test_bridge_overhaul_v3, test_bridge_prediction_markets, test_bridge_search_and_cache, test_data_sources_providers and test_data_catalog.
- Red check: the new tests run against a copy of the pre-change data_tools.py in glue/E/before/ gave 6 failed and 1 control passed (glue/E/red_before_new.txt).
- Lint: `uvx ruff check --select F,E9 --ignore F401,F841,F541` on data_tools.py and the test file: All checks passed.
Live checks:
I ran glue/E/live/live_search.py through scratchpad/live/with_data_keys.sh. DATA_SOURCES_CACHE_DIR and DEERFLOW_RUN_ARTIFACT_DIR were under glue/E/live/; the log is glue/E/live/live_search.log. It made 4 provider calls (FRED 3, Data360 1), no BLS or IMF calls and no LLM calls.
- **'policy rate':** answered free with 0 provider calls, 6 BIS WS_CBPOL lines.
- **'semiconductor exports':** 1 FRED search, returned fred:IY3344, IQ21320 and other export price indexes.
- **'Atlanta Fed wage tracker':** 1 FRED search, returned the FRBATLWGT* wage-growth-tracker series. The old code returned bis:WS_CBPOL/M.US.
- **'US unemployment rate':** the 3 strong catalog series (fred:UNRATE, wb:IMF_WEO_LUR/USA, bls:LNS14000000), then FRED UNRATENSA, U6RATE and CCSA.
- **'battery storage capacity' (provider wb):** 1 Data360 search, a world-level hit first.
- **tool_stats:** 4 calls, all searches, 0 failures.
Open issues:
- Budget impact: before, nearly every legacy search was free because weak matches filled the 6 slots. Now any query without 6 strong hits is charged against LEGACY_DATA_SEARCHES_PER_THREAD (default 6) and the per-lane total RESEARCH_LINEAR_MAX_DATA_CALLS_TOTAL (default 50). That is the charging rule the L2 verdict asked for (charge only when DataSources.search calls a provider). The .env.example note (H's file) that searches answered from the catalog are not charged is still accurate.
- _strong_catalog reads the DataSources instance's private `_env` with getattr. That keeps the key gating for EIA/BEA entries identical to DataSources.search, and falls back to os.environ for fakes that lack it. data_tools already reads data_sources._SINGLETON the same way. If slice A adds a public accessor, this read should switch to it.
- The deployed copy deer-flow/data_tools.py already differs from the bridge source. I did not edit it because I don't own it; pipeline_orchestrator._sync_deerflow_bridge_if_stale re-syncs it before each research launch. I did not touch deerflow_bridge/config.yaml, the deployed deer-flow/config.yaml or skills/deep-research, because none needed a change for this fix.
- Seen in the live run, not in my files: data_search('battery storage capacity', provider='wb') got only one fetchable Data360 hit. Weak catalog CO2 and electricity rows filled the other 5 slots. That ordering is slice A2's search design.

## glue:H

Role H finished all four leftovers. Two of them needed code or doc changes; for the other two the code was already correct, so I added tests and pinned the facts the existing test relies on.
(1) Full pipelines now register each dataset CSV under a formal `dataset_<file>` key when research completes. Before, a CSV only had a `_partial` key from the live scan, and PREPARE deletes `_partial` keys, so the dossier's CSV links disappeared. The live scan and the completion step now get the CSV list from one helper. It lists only the CSVs that data/datasets.json names, so older copies left on disk are not registered, and it skips symlinks.
(2) .env.example now documents DATA_SOURCES_FRED_PER_MINUTE and every other environment setting the official-data code reads for the data servers. A new test fails if one is missing.
(3) The FY2026 test no longer depends on today's date. Its expectations come from the capture time recorded in the fixture, not the system clock. The whole test file passes with the system clock moved forward 0, 120, 400 and 800 days, and the test now checks the capture time and fiscal-year completeness it relies on.
(4) historical_snapshot already uses the shared data_sources.observation_kind, which now includes slice A's completeness rule for policy-2 rows. A new test checks 29 real rows: the snapshot, the report pack and charts (official_latest_observed) and the anchors (data_sources.latest_observed) all report the same latest observation.
Every new test failed before the change and passes after: 7 failures for (1), 1 for (2) (9 settings undocumented), and 3 for (4) when slice A's rule is disabled. The 13 related test files (421 tests) pass with 1 skip. ruff is clean and check_env_drift.py --strict exits 0. A live check with real FRED and BIS data went through scan, completion, PREPARE cleanup and the artifact API; G3's dossier helper (datasetManifestRows) then linked a CSV for all three series. Notes: /private/tmp/claude-501/-Users-rogerlin-Downloads-DeepResearchForecast/52225542-51e1-41e1-b738-38d44834da7e/scratchpad/glue/H-notes.md.

Done:
- Leftover 1 (pipeline_orchestrator.py): new `PipelineOrchestrator._dataset_artifact_specs(hd)` lists `("dataset_<file>", path)` for the CSVs named in data/datasets.json. It skips symlinks, non-regular files, paths outside data/ and duplicates, and returns [] for a missing, malformed or symlinked manifest; it never raises. `_record_stage_artifacts` (research stage) now registers these CSVs and clears their `_partial` keys; `datasets` and the chart files, including data_*.png and .html, were already registered there. `_discover_partial_artifacts` uses the same helper instead of listing every *.csv. The integrity manifest gets these files as entries, the same as charts.
- Leftover 1 tests (test_orchestrator_research_wiring.py), built on the real v3 fixture series-2026-10-12.json written twice so an older CSV stays on disk: test_research_completion_registers_dataset_csvs_that_outlive_prepare, test_registered_dataset_csv_is_served_to_the_dossier (Flask route returns the CSV), test_dataset_specs_list_only_current_regular_csvs, and test_dataset_specs_degrade_to_nothing_without_a_usable_manifest[absent|malformed|not_a_manifest|symlink]. I also updated test_viz_present_files_surface_as_partials to use a real manifest. Before the change these fail 7 times (scratchpad glue/H/red/red_task1.txt): no dataset keys registered, and the route returns 404.
- Leftover 1 check on the saved run: run read-only on pipe_261de6107490/handoff, the helper lists all 8 of its CSVs.
- Leftover 2 (.env.example): documented DATA_SOURCES_FRED_PER_MINUTE (default 50, range 1-120, one rate limit per process, invalid value falls back to 50, fails fast as a retryable rate_limited error). Also documented the FRED server settings that are passed through when set (FRED_API_TIMEOUT_MS 30000, FRED_API_MAX_RETRIES 3, FRED_API_RETRY_BASE_DELAY_MS 500, FRED_RATE_LIMIT_PER_MINUTE 120, FRED_CACHE_TTL_MS 60000, FRED_CACHE_MAX_ENTRIES 500; defaults taken from datamcps/fred-mcp-server-main/src/common/config.ts), IMF_APP_NAME (sent as imfp's User-Agent) and DATA360_API_BASE_URL.
- Leftover 2 test (test_official_data_consumers.py): test_every_official_data_env_knob_is_documented_in_env_example scans the data layer, data tools, research gateway and data-visuals renderer for environment reads, plus data_mcp's per-server *_ENV_KEYS allowlists, and checks each against .env.example. Before the change it fails with 9 undocumented settings (red_task2.txt). check_env_drift.py --strict exits 0.
- Leftover 3 (test_official_data_downstream.py): test_snapshot_separates_display_safety_from_resolution_safety already took every date from the fixture's recorded capture time (2026-10-11T22:08Z) and a fixed as_of. I added assertions that pin the retrieval date and the FY2025 complete / FY2026 partial flags. With a pytest plugin that moves the system clock forward 0, 120, 400 and 800 days, all 90 downstream tests pass (red/shift_probe2.txt). The expectations match the 120-day fiscal-year settle rule: FY2025 is shown as 'status not supplied' and FY2026 is still partial.
- Leftover 4 (test_official_data_downstream.py): test_snapshot_pack_charts_and_anchors_share_one_latest_observation covers 29 real rows: every policy-2 row from stored_v2 and v3_engine/series-2026-10-11, plus policy-3 replays and series-2026-10-12. It asserts that the report pack's latest value (forecast_extractor.official_latest_observed) equals data_sources.latest_observed, and that the snapshot's Value and Period cells show the same latest observation. With slice A's completeness rule disabled, 3 cases fail (stored DGS10, Debt to the Penny, T10Y2Y), which is the mismatch G2 reported (red_task4.txt). No change to official_data.py was needed.
Not done:
- prune-superseded-dataset-partials: A `dataset_<old>.csv_partial` key from a CSV that a mid-run refetch replaced stays in status.artifacts until PREPARE or the next report attempt; in research-only runs it stays. It does no harm, because the dossier only looks up names from the current datasets.json, so I left it. If wanted, the research completion step could drop dataset_ keys that are not current.
- fork-dataset-fallback: In backend/app/api/research.py (not an H file), the fallback for an unregistered artifact name rebuilds only chart_ paths. Forks get their keys registered once they run, through _complete_stage(reused=True), so I did not add a dataset_ fallback.
Tests:
From backend/: `.venv/bin/python -m pytest -q -p no:cacheprovider` on test_official_data_consumers, test_official_data_downstream, test_official_data_promotion, test_orchestrator_research_wiring, test_research_contract_finalization, test_canonical_world_brief_denials, test_resolution_monitor, test_forecast_ledger, test_resolution_autorun, test_data_sources_interfaces, test_research_round3_parent, test_research_fork_handoff and test_official_data_end_to_end: 421 collected, exit 0, 1 skip (scratchpad glue/H/related_run1.txt). After the last docstring edit I re-ran test_orchestrator_research_wiring and test_official_data_consumers: exit 0.
Red checks (scratchpad glue/H/red/): red_swap.py loads a pre-change copy of the orchestrator (7 failed, red_task1.txt); red_env.py points the new test at the pre-change .env.example (9 undocumented, red_task2.txt); red_legacy_rule.py disables slice A's completeness rule (3 failed, red_task4.txt). shift_clock.py moves the system clock forward 0/120/400/800 days, and test_official_data_downstream passes every time (shift_probe2.txt).
`uvx ruff check --select F,E9 --ignore F401,F841,F541` on the 4 touched Python files: all checks passed. `backend/scripts/check_env_drift.py --strict`: exit 0. I did not run the full suite (that is the lead's job).
Live checks:
Command: `with_data_keys.sh .venv/bin/python scratchpad/glue/H/live/live_artifacts.py glue/H/live/run1`, with DATA_SOURCES_CACHE_DIR set to glue/H/live/cache. It fetched fred:UNRATE (33 observations), fred:DGS10 (22) and bis:WS_CBPOL/M.US (33) in 10.7 s, with 2 FRED calls, 0 BLS and 0 IMF, and wrote them the way research does. Steps after that:
- The live scan registered 3 `dataset_*.csv_partial` keys.
- Research completion registered the 3 formal `dataset_<file>.csv` keys, and they were still there after the PREPARE cleanup of `_partial` keys.
- GET /api/research/<pid>/artifact/dataset_<file> returned 200 with a `date,value` CSV for all 3.
- Fed the returned datasets.json and the registered names to G3's frontend helper (`node glue/H/live/dossier_rows.mjs` with frontend/src/utils/officialData.js datasetManifestRows): all 3 rows got a csvArtifact (4.2% 2026-09; 4.989% 2026-09; 3.875% 2026-09).
Logs: run1.log and run1_dossier.txt. The script calls create_app(), which started backend housekeeping (graph GC deleted=0, orphan-pipeline sweep); afterwards no pipeline state or graph DB file under backend/uploads had changed. No paid LLM calls were made and no keys were printed.
Open issues:
- Lead, about pipe_261de6107490: this Claude session's hooks write logs/52225542-.../pre_tool_use.json and post_tool_use.json inside that pipeline folder, because it is the session's working directory. My scripts did not write them; they are not part of the run's evidence.
- D (linear_research.py): on a v3 resume whose gather phase is already done, meta.data_sources is rewritten to {status: stored_only, calls: 0}. That erases the first attempt's provider statistics, which is why pipe_261de6107490 reports 0 data calls even though 8 FRED series were prefetched. Consider keeping or merging the earlier attempt's stats.
- F/D: pipe_261de6107490 has no charts/data_*.png even though datasets.json points at them. My change registers any data chart that exists at research completion; a fresh run should confirm the series charts are actually produced on resume and finalize.
- Already true before this work, in a rare legacy setup (parallel lanes without global synthesis): _merge_track_research_data merges the lanes' data/ folders but not their charts/. The merged report's chart image links can be broken, and the dossier hides the series chart links.
- C (research_gateway.dataset_cap): DATA_SOURCES_MAX_SERIES=0 sets the research dataset cap to 0, while Config clamps the same value to at least 1 for downstream use and .env.example documents 1-200. Small inconsistency, not in my files.
- backend/app/services/official_data.py still has an unused public wrapper series_stats(). For policy-2 rows it returns the raw data-layer stats, which can include an open, partial month. I left it in place; consider removing it, or making it match latest_observed, if nothing starts using it.

## glue:D

Role D finished all five leftovers in deerflow_bridge/linear_research.py, and each one has tests in backend/tests/test_v3_official_data.py. Final run of the owned and related suites: 1,040 passed, 1 skipped (the guarded-runner test). ruff is clean. The 5 new tests fail on the engine as it was before this session, each for the intended reason, and pass now. With official data disabled, a full scripted run makes the same 27 model calls as the HEAD engine plus HEAD gateway and writes the same 39 artifacts, meta.json included; only wall-clock timing values differ.

(1) Need resolution: a query need is now seeded only from a strong catalog match in the need's own geography. The data phase no longer runs provider searches to pick seeds. Needs it cannot resolve are passed to the KIQ agent as an explicit line in its task. The follow-up path follows the same rule.
(2) The stale 'UNKNOWN_TOOL: only web_search and web_fetch are available.' text was already fixed. When data tools are bound the reply now names data_search and data_get; the web-only reply is unchanged. Tests now pin both texts exactly.
(3) Prefetch cap: DATA_SOURCES_PREFETCH_MAX is clamped to limits.max_prefetch_datasets and now applies to the whole run, not to each batch. Gap follow-up batches only use the slots the data phase left, so the gateway no longer refuses requests and counts them as failures. Series already stored are linked at no cost.
(4) Disabled runs: meta.json data_sources keeps exactly the key set a data-free run had at HEAD. That covers status 'disabled' and also a resumed disabled run, whose status is 'stored_only'.
(5) Investigation of pipe_261de6107490 (read-only):
- The first attempt planned with explicit FRED IDs and prefetched 8 series for K1, K3 and K4.
- At QA (22:00:04) the chart renderer exited with code 1. render_data.py was being edited at the time: its hash was 9b15bd47… at run start, then 0010b279…, and it is 39ebc776… now. The baseline table was published without figures, and QA sealed that.
- The 22:08 pipeline resume reused every phase through QA and ran finalize only. meta.json is rewritten on every attempt, so it shows data_sources.status 'stored_only' and calls 0. No agent ran in that attempt.
- Nothing on disk records whether first-attempt agents called the data tools. All 8 stored series came from the prefetch, and the gateway logs no data tool lines.
- The current render_data.py rendered all 8 real stored series from a scratch copy (exit 0, 1.7 s).
- A full-engine test reproduces the case: an agent outage right after the data phase, then a resume. The resumed attempt configures the providers again, every agent call has the data tools bound, K1 gets its seeded series and fetches a new one, and the real renderer draws both series at QA, embedded in the report. On the HEAD engine this test fails: the resume is stuck at 'stored_only'.
- To make agent data use traceable after a resume, KIQ records now store stats.data {calls, stored, failed} and meta.kiqs gains data_calls, summed across attempts. Both are written only in data-enabled runs.

Also improved: a base-rate KIQ of any kind (the real run's K7 was 'general') now gets catalog series hints and the 30-year history window. The gap prompt, shown only in data-enabled runs, now says that a query need no catalog series answers is left to the follow-up's agent.

Done:
- Leftover 1: _data_requests(kiqs, *, fallback) seeds a query need only from a strong catalog match in the need's geography (_catalog_need: search_catalog_scored(...).strong and entry.geography in the need's codes). Provider-search seeding was removed, along with the _data_hit label heuristics and _DATA_US_PROVIDERS. New _open_needs(kiq) adds the line 'Official data the plan asked for that no catalog series answers (find a series with data_search, check its title and geography, then data_get it): <query> (<geography>)' to the data-enabled KIQ task.
- Leftover 2: confirmed already done. The data-bound UNKNOWN_TOOL and INVALID_TOOL_CALL replies name the data tools, and the web-only texts are unchanged. Tests now pin both exactly.
- Leftover 3: new _prefetch_cap() (DATA_SOURCES_PREFETCH_MAX clamped to limits.max_prefetch_datasets). New series fill only the slots earlier batches left; series already stored are linked at no cost. Tested with DATA_SOURCES_PREFETCH_MAX=99 on the quick preset: 6 stored, and a follow-up batch causes no prefetch-limit failures.
- Leftover 4: attach_telemetry adds only _DATA_STATS_BASE_KEYS (calls, failures, cached, series_count, route_counts, per_agent) to meta.data_sources when data is not enabled. A full run and a resumed run were checked, plus an identity comparison against the HEAD engine with the HEAD gateway.
- Leftover 5: forensics above. New full-engine test test_resume_after_the_data_phase_keeps_data_tools_for_unfinished_kiqs_and_renders_charts_at_qa uses the real deerflow_research._render_data_charts and render_data.py. It fails on the HEAD engine because the resume is stuck at stored_only.
- Agent data use now survives a resume: KIQ record stats.data {calls, stored, failed} via _kiq_data_use and _kiq_data_outcome (_coverage_data refactored to share it), and meta.kiqs.data_calls. Both are written only in data-enabled runs.
- Base-rate KIQs of any planned kind get catalog hints (_kiq_data_text) and the long-history window (_data_windows), and receive question-level seeds (_catalog_seeds).
- Gap prompt (data-enabled only) now says that a query no catalog series answers is left to the follow-up's agent. _need_text docstring updated to match.
- Updated test expectations that went stale after the concurrent B and A edits: (a) the compound CPI and Fed question now also seeds the policy-rate clause (bis:WS_CBPOL/M.US, fred:FEDFUNDS); (b) the baseline table shows the last complete month (T10Y2Y 0.34% for 2026-09) and never the open partial month. observation_series now takes its provider from the series ID.
Not done:
- progress-log-data-tool-lines: The gateway (C's file) logs data failures but no tool or success lines. I chose not to add engine-side log lines because they would duplicate C's failure lines. Agent data use is persisted in the KIQ records and meta.kiqs.data_calls instead. A [tool] data_get line belongs in research_gateway.py.
- re-render-charts-on-resume-after-sealed-qa: This is intentional. Once QA has passed, the report and its official-data artifacts are sealed by hash, so a finalize-only resume cannot re-render charts that failed at QA. That is why the real run keeps its table-only exhibit.
Tests:
From backend/: .venv/bin/python -m pytest -p no:cacheprovider tests/test_v3_official_data.py tests/test_research_engine_v3*.py tests/test_live_research_progress.py tests/test_start_script_progress.py tests/test_research_gateway.py tests/test_research_gateway_official_data.py tests/test_official_data_end_to_end.py → 1040 passed, 1 skipped (guarded runner), exit 0. Log: scratchpad/glue/D/run3.txt.

An earlier run (run2) hit a source_receipt teardown error because I edited linear_research.py while it was running. The clean rerun is run3.

Red checks: scratchpad/glue/D/tools/run_with_engine.py binds the pre-session engine copy (glue/D/before/linear_research.py). Result: 7 failures, the 5 new tests for their intended reasons (provider-search seeds, follow-up prefetch-limit failures, no hints for a general base-rate KIQ, extra meta keys when disabled, missing stats.data) plus 2 callers of the new _data_requests signature (red_before.txt, red_before_final.txt). Bound to the HEAD engine, the resume test fails at status 'stored_only' (red_head_resume.txt).

Before my edits, the test file already had 2 failures, caused by concurrent A and B changes. Both are fixed as described in done.

ruff (F,E9 with the standard ignores) is clean on linear_research.py, research_progress.py and test_v3_official_data.py.

Disabled-data identity check (tools/prompt_identity.py, scripted model, DATA_SOURCES_ENABLED=false), current engine against the HEAD engine with the HEAD gateway: quick depth, 22 model calls identical; standard depth with a gap round, 27 calls identical; 39 artifacts identical apart from timing fields, meta.data_sources included.
Live checks:
Renderer: the current render_data.py was run with backend/.venv/bin/python over a scratch copy of pipe_261de6107490/handoff/data. It exited 0 and wrote 8 PNG/HTML charts in 1.7 s (glue/D/realrun1).

Live engine run: scratchpad/glue/D/tools/live_resume.py, run through live/with_data_keys.sh with DATA_SOURCES_CACHE_DIR set to a fresh glue/D/live_cache2, real FRED/BIS MCP servers, scripted model, no LLM calls. Result in glue/D/live_summary2.json, log in live_run2.log.
- Attempt 1 (agent outage): rc 2. Plan and data phases done, gather failed. The data phase stored fred:DFEDTARU, bis:WS_CBPOL/M.US (the 'policy rate'/USA query need, resolved from the catalog) and fred:FEDFUNDS from 1996-01-01 (the long window, requested for the general-kind base-rate KIQ). The 'Atlanta Fed wage tracker' need made no provider search.
- Attempt 2 (resume): rc 0, data_sources status 'enabled', all 13 agent calls had the data schema bound. K1's task had its seeds plus the open-need line 'Atlanta Fed wage tracker (USA)'. K2 got hints and the long-history line. K1's live data_get of fred:UNRATE returned [S28]. QA rendered 4 real PNG charts, all embedded in the report. KIQ stats.data was K1 {calls 1, stored [DFEDTARU, WS_CBPOL/M.US, UNRATE]}; meta.kiqs.data_calls was 1.
- Provider calls: 4 series fetched live (3 FRED, 1 BIS), no BLS or IMF calls, no searches.
Open issues:
- The session's harness hooks created backend/uploads/pipelines/pipe_261de6107490/logs/52225542-51e1-41e1-b738-38d44834da7e/ (pre_tool_use.json, post_tool_use.json) because the session's working directory is that run dir. I did not create it and did not touch it. The lead may want to remove it so the run stays pristine.
- deerflow_bridge/data_sources.py and data_catalog.py were edited by other roles during this session (mtime 20:49), which made two expectations in my test file stale; I have updated them. The lead's full-suite run should happen after A and B finish. The source_receipt fixture in test_v3_official_data.py fails at teardown if any hashed source changes mid-run.
- For C (research_gateway.py): agent data_get and data_search calls write no [tool] line to the progress log, and successes no [result] line; only failures are logged. Engine-side telemetry now lives in the KIQ records and meta.kiqs.data_calls.
- The live run's QA flagged data_numbers_consistent: 5 lines. These come from the scripted writer citing a dataset source next to an invented '176 GW' figure. That is correct QA behaviour, not a defect.
- Working notes: scratchpad/glue/D-notes.md. Tools in scratchpad/glue/D/tools/: run_with_engine.py (red checks), prompt_identity.py (disabled-data identity, optional HEAD gateway and PI_DEPTH), live_resume.py (live resume check).

## glue:G1

G1 is finished. Of the two leftovers, (1) turned out to be already done in the working tree, and (2) is now implemented. Doing (1) also surfaced a real publication failure, which I fixed in my own file.

(1) RPT-16: _append_resolution_section in report_agent.py already passes source_index=self._citation_index_or_fallback() to render_resolution_block, so G2's note was out of date. I proved the existing tests catch its absence: a scratch pytest plugin dropped source_index for that one caller only, and 3 tests failed (test_report_data_publication::test_structured_forecast_and_real_api_publish_without_bypass, plus test_anchored_watch_table_is_tagged_and_canonical in English and Chinese). I also replayed the real run report_583a1a77d9dd read-only with the current code. Its watch row, published untagged, now ends with [S39], which matches its stored source tag, and _official_watch_line_support accepts it.

(2) G5: _finalize_structured_forecast now adds forecast_ledger.official_data_track_record() to forecast.json as historical_calibration.official_data_track_record. It sits next to the scenario summary {n_resolved, mean_brier, calibration_error}; when no scenario has resolved, that summary shows n_resolved 0. It is never merged into the scenario Brier or the confidence_rationale note. When the function returns None, nothing is added, so forecast.json is unchanged. Any error is caught and skipped, as the scenario calibration code already does.

New defect, caused by RPT-16 tags: each anchored binary adds a tagged watch row, and those rows count toward REPORT_MAX_CITATIONS_PER_SOURCE (20). With 12 anchors on one series plus 7 prose citations, the report went over the cap. The repair then stripped [S1] from that series' detail-chart caption, and the final audit refused publication ('官方数据图表来源标注缺失或不匹配' – the official chart's source caption is missing or doesn't match). The Chinese report also failed for one line of target-language contamination. The fix: lines that are byte-identical to the canonical official text (chart captions, indicator rows and watch rows) are now left out of the per-source count. This applies in both _audit_semantic_citations and _repair_overused_citations, the same way References entries are already excluded. Ordinary prose is still capped. Without official data both functions behave exactly as before.

Done:
- Leftover 1 (RPT-16): checked that report_agent._append_resolution_section already passes source_index=self._citation_index_or_fallback() to render_resolution_block. Red proof: plugin scratchpad/glue/G1/plugins/g1_no_source_index.py drops source_index only for that caller, and 3 tests fail (glue/G1/red_source_index.txt); they pass with the current code.
- Leftover 1 replay on real evidence: probe/replay_watch.py rebuilt the watch section of report_583a1a77d9dd read-only. The fred:UNRATE row now ends with '[Source](<https://fred.stlouisfed.org/series/UNRATE>) [S39]', matching official_data.json source_tags, and _official_watch_line_support returns True. The published row had no tag.
- Leftover 2 (G5): report_agent._finalize_structured_forecast writes historical_calibration.official_data_track_record = forecast_ledger.official_data_track_record(). It sits beside the scenario calibration_summary (n_resolved 0 when no scenario has resolved), never enters the scenario Brier or confidence_rationale, and is left out when the function returns None, so output is unchanged. Exceptions are caught and skipped.
- New test test_report_official_publication_real.py::test_forecast_json_keeps_the_official_data_track_record_separate[English|Chinese]. It uses the real bundle and the real resolution_monitor.run_monitor to settle 2 past-period fred:UNRATE anchors on the stored 4.2 value (Brier 0.09 and 0.16, mean 0.125). It checks that the field is absent before anything resolves, that the field is the only change to forecast.json once data outcomes exist, and that a resolved scenario keeps its own Brier with the binary record beside it. Red before the change: KeyError 'historical_calibration' in EN and ZH (glue/G1/red_track_record.txt, red_track_record_final.txt via plugin g1_no_track_record.py).
- New defect fixed: canonical official lines (exhibit captions, Key official indicators rows, Official series to watch rows) no longer count toward or get stripped by the per-source citation cap, in both _audit_semantic_citations and _repair_overused_citations. Prose is still capped.
- New test test_report_official_publication_real.py::test_canonical_official_lines_do_not_count_toward_the_per_source_cap[English|Chinese]: 12 UNRATE anchors plus 7 true prose claims. It checks hard_passed, both official captions intact, 12 tagged watch rows, no overused source, and all prose kept. It also checks that 14 more cited prose lines are still flagged (count 21 > 20) and that exactly 1 is stripped while every watch row is untouched. Red without the fix (glue/G1/red_cap.txt) and red with only the audit-side exemption (red_cap_repair_only.txt), in EN and ZH.
- Updated the test module docstring to list G5.
- Live check (glue/G1/live/live_g1.py, run.log): fred:UNRATE and fred:FEDFUNDS fetched live in 2.8 s (4 FRED calls in total including the monitor refetches, 0 BLS). The monitor settled 2 past-period anchors, and the EN and ZH forecast.json both carry official_data_track_record {n_resolved 2, mean_brier 0.125}. Heavily anchored EN and ZH reports with 22 [S1] in the body pass the final audit, with captions 2/2 and 12 tagged watch rows. The only model call is the expected failing Part-2 synthesis call.
Not done:
- anchor-coverage-real-run: Outside G1's files. In the real run report_583a1a77d9dd, only 1 of 11 binaries (F11, fred:UNRATE) carries a data_anchor. F1-F9 are about fred:DFEDTARU and F10 about CPIAUCSL, and none of them is anchored, for example equality statements ('is 4.25%') and criteria phrased as 'reads 4.50%'. Anchor extraction and matching belong to G2 (forecast_extractor.py), so I did not change them. With no input data_anchor, _normalize_binaries does not infer anchors from the criteria.
Tests:
All from backend/ with .venv/bin/python -m pytest -p no:cacheprovider.

1) The owned files test_report_official_publication_real.py, test_report_data_publication.py and test_report_official_data.py, after the last edit: 107 passed (glue/G1/owned_final.txt).

2) After the fix, all 49 test files that reference report_agent/ReportAgent (test_export_demo_site_data excluded), plus test_forecast_ledger, test_official_data_downstream, test_resolution_monitor, test_exec_brief, test_sessionb_downstream_gates and test_wave9_citations: 1124 passed, 1 skipped, 11 xfailed, exit 0 (glue/G1/owned_run2.txt).

3) Red-before runs:
- red_source_index.txt: 3 RPT-16 tests fail without the source_index wiring.
- red_track_record.txt and red_track_record_final.txt: the G5 test fails in EN and ZH.
- red_cap.txt: the cap test fails in EN and ZH without the fix.
- red_cap_repair_only.txt: the cap test fails in EN and ZH with only half of the fix.

4) uvx ruff check --select F,E9 --ignore F401,F841,F541 on report_agent.py and the test file: All checks passed.

The full suite was not run (the lead runs it).
Live checks:
scratchpad/glue/G1/live/live_g1.py was run through scratchpad/live/with_data_keys.sh with DATA_SOURCES_CACHE_DIR=scratchpad/glue/G1/live/cache; output is in live/run.log, live/final_English.md and live/final_Chinese.md.
- Fetch: fred:UNRATE (latest 4.2, 2026-09) and fred:FEDFUNDS (latest 3.75, 2026-09) came back in 2.8 s; the second run hit the cache. There were 4 FRED calls in total including the monitor refetches, and 0 BLS calls.
- Track record: resolution_monitor.run_monitor settled F1 and F2 for 2026-09, giving official_data_track_record {n_resolved 2, mean_brier 0.125}. It appears in the EN and ZH forecast.json under historical_calibration, next to the scenario summary with n_resolved 0.
- Publication: the EN and ZH reports with 12 anchors on fred:UNRATE and 7 true prose claims both passed the final audit with hard_issues=[]. Official captions passed 2/2, and there were 22 [S1] in the body with no overused source. All 12 watch rows were tagged [S1] and support-validated, and all prose was kept.
- Real-run replay (read-only): the report_583a1a77d9dd watch row now carries [S39].
Open issues:
- Lead: commit backend/tests/test_report_official_publication_real.py (untracked, new since the earlier G1 slice) together with backend/tests/fixtures/data_sources/real/.
- Decision to note: when official outcomes exist but no scenario forecast has resolved, historical_calibration is {n_resolved: 0, mean_brier: null, calibration_error: null, official_data_track_record: {...}}. This keeps one consistent shape for readers. No code or frontend reads historical_calibration today (grep found none).
- G2 (forecast_extractor): the real Fed-funds run anchored only 1 of 11 binaries. The DFEDTARU equality and 'reads X%' statements and the CPIAUCSL index-level binary were not anchored, so the report shows one watch row and the monitor can settle only one forecast. Worth checking whether the extraction prompt or matcher should support equality anchors for policy-target step series.
- Pre-existing and unchanged: a REPORT_FORECAST_LEDGER run with the default ledger_dir writes to backend/uploads/pipelines/_forecast_ledger/ledger.jsonl (modified 2026-10-12 23:19), and tests that call _finalize_structured_forecast without monkeypatching ledger_dir append there. My new test redirects ledger_dir to tmp.

## glue:B

Role B is finished. The catalog now frames compound and varied forecasting questions correctly.

For the CPI/Fed example ("Will US CPI inflation fall below 2.5% ... and how will the Federal Reserve policy rate evolve through 2027?"), CPI and policy-rate series (fred:FEDFUNDS, fred:DFEDTARU, bis:WS_CBPOL/M.US) are now all strong hits. The planner digest lists them first, the two clauses taking turns, and drops the 'No catalog series answers this question directly' line. It also no longer pads the list with 11 other economies' policy rates and 5 other countries' WEO CPI series.

Changes, all in deerflow_bridge/data_catalog.py unless noted:
- Words that name nothing a series measures no longer count as concept terms:
  - movement verbs and hedges (evolve, change, trend, path, trajectory, develop, move, respond, …)
  - month names and other calendar words
  - units (TWh, GW, barrel, tonne, …)
  - Chinese equivalents (变化, 走势, 趋势, 如何, 如果, …)
  - new stopwords: where, through, while, …
- Compound questions are split into clauses (sentence ends, ; :, ', and/but/or', 'and' before a question word, and the CJK commas ，、; "U.S." and "2.5%" are not split). Each clause is ranked on its own; a clause naming no economy inherits the question's. Each clause's strong matches take turns at the top, then the whole question's other strong matches, then everything else by score.
- "Direct" digest matches must be keyword-level matches that explain part of the clause in the asked-about economy (or a world benchmark). The related section always appears: up to 8 entries when there are fewer than 6 direct matches, otherwise 4.
- Related-list rules:
  - global or place-less questions need the entry's main theme to match;
  - a country's headline series appear only when the question names no theme;
  - ties go to entries whose every theme the question names.
- When only some clauses are answered, the digest names the unanswered ones.
- Multi-word English topic terms now consume their words, so "new energy vehicles" no longer triggers the energy topic (no oil-price padding) and "policy rate" / "exchange rate" no longer trigger the interest-rate topic. NEV/NEVs were added to the autos topic.
- A stopword that modifies a compound term stays a concept word ("data" in "data center"). The head word stays generic ("rate" in "policy rate").
- gdp增速 and 经济增速 keywords were added to the World Bank GEP and WDI growth series.
- skills/data-sources/SKILL.md tells agents to search each part of a compound question separately, and that verbs and dates are not search terms.

Tests (backend/tests/test_data_catalog.py): 9 new cases, including the six required questions. All 9 fail against a rebuilt copy of the catalog as it was before this session and pass now. test_data_catalog.py: 46 passed. 13 related test files: 1275 passed. ruff is clean.

Done:
- Movement verbs, hedges, calendar words and units (EN and ZH) no longer count as concept terms; 'where', 'through' and similar added to stopwords
- Compound questions are split into clauses and ranked clause by clause; a clause without its own geography inherits the question's; the clauses' strong matches take turns at the top (search_catalog_scored / CatalogHit fields describe the best clause)
- Digest: direct section restricted to in-geography keyword matches that explain part of the question (no other economies' series); related section always shown (8, or 4 beside 6+ direct matches); place-less related entries must share the main theme; a country's headline series only when the question names no theme; ties go to entries whose every theme the question names
- Digest search line names the unanswered clauses when only some are answered; the original 'No catalog series answers this question directly' line is unchanged for questions nothing answers
- Multi-word English topic terms consume their words: 'new energy vehicles' no longer triggers energy; NEV terms added to autos; 'policy rate' / 'exchange rate' no longer trigger the interest-rate topic
- A stopword that modifies a compound term counts in queries and titles ('data' in 'data center'), so US electricity use per capita is no longer a false strong hit for data-center questions; the head word 'rate' stays generic (the yuan exchange-rate query keeps DEXCHUS strong)
- ZH growth-rate keywords (gdp增速, 经济增速) on WB_GEP and WDI GDP growth entries, so the GEP and WDI China growth series are now strong hits for 2027年中国GDP增速会低于4%吗
- SKILL.md: tells agents to search each part of a compound question separately; verbs and dates are not search terms (6,889 bytes, under the 8 KB cap)
- Tests: test_movement_verbs_dates_and_units_are_not_concept_terms, test_compound_questions_rank_every_clause, test_digest_frames_diverse_forecasting_questions[6 questions: US inflation+Fed, US data-center power 2030 with EIA retail sales (commercial sector) and generation, China NEV share 2027, euro-area policy rate 2026, global semiconductor sales 2030, 2027年中国GDP增速会低于4%吗], test_digest_names_the_clauses_no_catalog_series_answers, plus the SKILL.md phrase check
Not done:
- CJK-and-split: Deliberate: 和 / 及 are not clause boundaries, matching English 'and' (split only before a question word). So '失业率和GDP增长' stays one weak clause, while the ZH list separator 、 and punctuation ，？；。 do split.
- keyless-datacenter-related: Without EIA_API_KEY the data-center digest still lists the US gasoline (GASREGW) and Henry Hub natural gas (DHHNGSP) price series under RELATED. They are the same economy and theme (the energy topic is broad), and the digest still shows the search line. With the key the digest is focused: retail sales, consumption, generation; no prices.
Tests:
All commands run from backend with .venv/bin/python -m pytest -q -p no:cacheprovider.

- tests/test_data_catalog.py: 46 passed (37 existing + 9 new). Reference files are still in sync with the generator, because keywords and topics are not rendered.
- Red check: scratchpad/glue/B/make_before.py rebuilds the catalog as it was at session start (2537 lines, same as the original) into glue/B/before/. A pytest plugin (-p oldcat_plugin) pins it as the bare-name data_catalog. All 9 new cases fail against it (glue/B/red_final.txt). The original SKILL.md lacks the new phrase (checked by reverse replacement).
- 26 related test files (data_catalog, data_mcp*, data_sources*, data_visuals*, forecast_extractor_official, legacy_official_data, official_data_*, report_official*, report_visualizer_official, research_gateway*, settings_data_sources_probe, v3_official_data): 1698 passed, 1 skipped, exit 0 (glue/B/related_full.txt).
- Re-run after the last code edit, 13 consumer files (data_catalog, data_sources, data_sources_interfaces, data_sources_providers, research_gateway, research_gateway_official_data, v3_official_data, legacy_official_data, forecast_extractor_official, report_official_data, official_data_consumers, official_data_downstream, settings_data_sources_probe): 1275 passed, exit 0 (glue/B/final_related.txt).
- Baseline before my edits: 1 failure from another slice's in-progress edit, test_legacy_official_data::test_data_search_description... (E's data_tools docstring); it passed in later runs.
- ruff check --select F,E9 --ignore F401,F841,F541 on data_catalog.py and test_data_catalog.py: all checks passed. New lines stay within 120 characters.
Live checks:
Run through scratchpad/live/with_data_keys.sh (FRED, EIA and BEA keys present) with DATA_SOURCES_CACHE_DIR=scratchpad/glue/B/cache; log in scratchpad/glue/B/live_check.log.

- DataSources.search on the CPI/Fed question returned wb:IMF_WEO_PCPIPCH/USA, bis:WS_CBPOL/M.US, fred:CPIAUCSL, fred:FEDFUNDS, bls:CUUR0000SA0 and fred:DFEDTARU in 0.02 s. All six came from the catalog with no provider call, because there were at least as many strong hits as the limit.
- DataSources.search('US data center electricity demand') put usgov:eia/electricity_sales/US.COM, VA.COM and TX.COM first, then live search ran (10.4 s).
- DataSources.get('fred:FEDFUNDS') returned 33 observations; the latest is 2026-09 = 3.75 Percent.
- catalog_digest with the live environment lists FEDFUNDS, DFEDTARU and WS_CBPOL/M.US with no search line.

Calls: one FRED get and one live search round (FRED/Data360). No BLS, no IMF, no paid LLM calls.
Open issues:
- Change for consumers (no edits needed): search_catalog_scored marks clause-level strong hits for compound questions, so v3 _catalog_seeds and legacy _legacy_prefetch_ids now also seed the policy-rate series. D has already updated test_v3_official_data.py::test_compound_question_seeds_its_clauses_and_keyless_bls_routes_to_fred to expect ['wb:IMF_WEO_PCPIPCH/USA', 'bis:WS_CBPOL/M.US', 'fred:CPIAUCSL', 'bis:WS_LONG_CPI/M.US.771', 'fred:FEDFUNDS']; it passes with this catalog and fails with the old one. test_legacy_official_data::test_pre_pass_picks_strong_clause_matches_by_their_fastest_route still gets fred:UNRATE first.
- The planner digest now always has a RELATED section (at most 4 entries beside 6 or more direct matches), so it is slightly longer but still capped at 6,000 characters. A new search line can name unanswered clauses (each quoted at most 120 characters). The digest is only built when official data is enabled, so prompts without official data are unchanged.
- For the lead's docs pass: design.md and integration-contract still describe single-query ranking. The catalog now ranks compound questions clause by clause (see the search_catalog_scored and catalog_digest docstrings).
- Not my file, still open from earlier slices: data_tools.py _catalog_answer (E) answers from any six catalog hits through search_catalog, weak ones included. It should require CatalogHit.strong, as DataSources.search does.
- Scratch evidence may be wiped. It is in scratchpad/glue/B/ (probe.py, probe2.py, make_before.py, before/, red_final.txt, related_full.txt, final_related.txt, live_check.py/.log) and the notes in scratchpad/glue/B-notes.md.

## glue:G2

G2 is finished. Both leftovers are fixed in backend/app/services/forecast_extractor.py, and each has a regression test that fails against the earlier code and passes now.

(1) Anchor matcher. Both reported phrasings now anchor: 'The 10-year minus 3-month Treasury spread < 0% in June 2027' and '联邦基金有效利率在2027年12月 < 3%' (the Chinese one with Chinese criteria such as '若fred:FEDFUNDS于2027年12月低于3%，判定为是'). A real binary from pipeline run pipe_261de6107490 had also lost its anchor: 'The US CPI index level (CPIAUCSL, SA) is at least 337.0 …'. That shape now anchors too. The bugs behind these were:
- Missing series aliases: the bare series id ('T10Y3M'), capitalised acronyms ('CPI'), shorthand with digits ('10y3m') and title words in any order ('10-year minus 3-month Treasury', '10Y-3M', '10-year/3-month').
- Chinese dates written with spaces ('2027 年 12 月') were not read.
- Chinese characters were treated as word characters. This broke '达到5%及以上' / '为5%或以上', and an id written with no space between Chinese characters ('若fred:FEDFUNDS于').
- The criteria accepted only symbol comparators, not words ('低于', 'is below'), and did not accept '当…时', '观察期 2027-12' or '月度值'.
- Unsupported comparator forms: 'at or above/below', 'in excess of', '不到', full-width ＜／％, and 'negative'/'below zero'/'为负' meaning below zero.

Every negation, compound, wrong-period, deadline, wrong-geography and wrong-tenor counterexample is still rejected. I also added a check for words that name a related but different series: 'core', 'real', 'market-implied', 'youth', 'TIPS', 'lower bound' versus 'upper bound', '实际', '青年', '隐含'. These are allowed only when the series' own names carry them. This fixes five wrong anchors the earlier code accepted, for example 'youth unemployment rate' on fred:UNRATE and 'real 10-year Treasury yield' on fred:DGS10.

(2) New public helper official_auto_resolvable(row). _admit_data_anchor now sets anchor['auto_resolvable']. It is False for daily data averaged or sampled to months, World Bank Data360 rows, USAspending fiscal totals and IMF WEO rows (including WEO rows stored before the current status rules). The anchor is still kept for charts and watch tables, and the probability is unchanged. On every stored and replayed real row I tested, the flag matches what the data layer's resolve_data_anchor does: False exactly when every period comes back 'manual'.

Nothing changes when official data is absent: the extraction prompts, outputs, Part 1 table and resolution section are byte-identical to the earlier code in English and Chinese (same sha256). No prompt text was edited. report_visualizer.py needed no code change; a new test shows natural-phrasing anchors now reach the detail charts.

Done:
- Leftover 1: 'The 10-year minus 3-month Treasury spread < 0% in June 2027' now anchors to fred:T10Y3M, through title words in any order with tenors normalised ('10-year', '10y', 'ten-year' all read as '10y'). Implemented in _anchor_title_windows and _anchor_tokens.
- Leftover 1: '联邦基金有效利率在2027年12月 < 3%' anchors with Chinese criteria. Fixed along the way: Chinese characters next to the id, word comparators in criteria, '当…时', '观察期', '月度值'.
- Series aliases (_anchor_identifier_spans): the bare id is matched with exact case (UNRATE, T10Y3M, CPIAUCSL); catalog acronyms are matched in capitals (CPI, PCE, NFP); catalog shorthand containing digits is matched in any case (10y3m, u-6, 2s10s).
- Periods: Chinese dates with spaces (2027 年 12 月, 2027 年第四季度), '月份', '号', 'Q4' written next to Chinese characters, 'June, 2027'.
- Comparators: at or above/over/higher than, at or below/under/lower than, in excess of, 不到; zero-sign words negative/below zero/为负 (< 0) and positive/为正 (> 0), with 'non-negative' excluded; full-width ＜＞＝％ and full-width digits read as ASCII; fixed the CJK lookbehind in the postfix pattern so '达到5%及以上' parses.
- Check for words naming a related series (_anchor_foreign_qualifier): core, real, nominal, youth, TIPS, implied, futures, forward, upper vs lower bound/limit, 核心, 实际, 名义, 青年, 广义, 隐含, 期货, 远期, 上限, 下限. A word is allowed when the series' own names carry it; 'real' is also allowed for constant-price series. This fixes 5 wrong anchors the earlier code accepted.
- Leftover 2: public official_auto_resolvable(row) plus anchor['auto_resolvable'] on every admitted anchor. Its agreement with resolve_data_anchor is tested on 14 real sources.
- Tests added to backend/tests/test_forecast_extractor_official.py: the two reported phrasings, 12 accepted statement forms, 6 criteria forms, 21 rejected statements, 6 rejected criteria, the federal funds target range upper/lower limit, CPI acronym and bare id, the auto_resolvable flag on admitted anchors, flag versus resolver agreement on 14 sources, and the watch table keeping an anchor that cannot be settled automatically. Red against the earlier module: 46 failed / 94 passed. Green: 140 passed.
- Test added to backend/tests/test_report_visualizer_official.py: natural-phrasing anchors reach the detail charts, including T10Y3M with auto_resolvable False. Red: 1 failed / 11 passed. Green: 12 passed.
- Absent-data parity (scratchpad/glue/G2/absent_parity.py): prompts, outputs, Part 1 table and resolution section have the same sha256 under the earlier and new code, in English and Chinese.
- Self-review fixes: token offsets now index the original text (no case-folded offsets), the extra blank line is gone, and every new line is within 120 characters.
Not done:
- monitor-skip: Per the task, the resolution monitor (backend/scripts/resolution_monitor.py) has no owner this round, so I only added the flag. To act on it, resolve_official_forecasts should skip the fetch when anchor.get('auto_resolvable') is False and record status 'manual' with a reason such as 'Series cannot settle automatically (daily aggregation / status-stripping feed)'. Forecasts saved before this change have no flag; for those the monitor can call forecast_extractor.official_auto_resolvable(row) on the stored carrier row.
- head-period-criteria: Criteria that put the period before the series id ('Resolves YES if the December 2027 value of fred:FEDFUNDS < 3%') and criteria with a parenthetical description ('fred:T10Y3M (monthly average) < 0%') are still rejected. This fails safe (no anchor), and the extraction prompt's worked example uses the supported form.
- bare-yishang-yixia: A bare '以上'/'以下' ('降至3%以下') deliberately does not anchor, because whether it includes the threshold is ambiguous. '及以上/或以上/及以下/或以下' and '低于/不低于' are supported.
Tests:
All runs from backend with .venv/bin/python -m pytest -p no:cacheprovider. Baseline before any edit, 9 files (both extractor files, all three visualizer files, report_official_data, report_official_publication_real, official_data_downstream, report_data_publication): 417 passed, exit 0. After the edits, same 9 files: exit 0. Every test file that imports forecast_extractor or report_visualizer (34 files, test_export_demo_site_data excluded) plus test_resolution_monitor: 1072 passed, 1 skipped, 11 xfailed, 0 failed, exit 0. The 6 owned files after the last edit (test_forecast_extractor, test_forecast_extractor_official, test_report_visualizer, test_report_visualizer_axes, test_report_visualizer_official, test_report_zh_presentation): 325 passed. Red-before: a pytest plugin (scratchpad/glue/G2/redplugin/red_orig.py) loads the pre-change forecast_extractor in place of the edited one. test_forecast_extractor_official gives 46 failed / 94 passed under it and 140 passed now; test_report_visualizer_official gives 1 failed / 11 passed under it and 12 passed now. uvx ruff check --select F,E9 --ignore F401,F841,F541 on the owned source and test files: All checks passed. The full suite was not run (the lead's job).
Live checks:
Ran scratchpad/glue/G2/live/live_check.py through scratchpad/live/with_data_keys.sh, with DATA_SOURCES_CACHE_DIR=scratchpad/glue/G2/live/cache, no LLM calls and no keys printed. It fetched fred:T10Y3M, fred:FEDFUNDS, fred:UNRATE, fred:DFEDTARU and wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA through the current data layer in 18.5 s (4 FRED calls, 1 World Bank, 0 BLS). Every case below came out as expected:
- EN spread phrasing: anchored, auto_resolvable False, latest 0.896 (2026-09), base rate 0.117.
- ZH fed funds with '若fred:FEDFUNDS于…低于3%': anchored, True.
- ZH '美国失业率在 2027 年 6 月为5%或以上': anchored, True.
- 'upper bound of the federal funds target range' on DFEDTARU: anchored, False.
- 'lower bound' counterexample: not anchored.
- WDI 'US GDP growth is negative in 2027': anchored, False.
Log: scratchpad/glue/G2/live/live_run.log.
Open issues:
- For the lead or the monitor's next owner: make resolve_official_forecasts honour anchor['auto_resolvable'] is False (no fetch; status 'manual' with a reason), so aggregated-daily, World Bank, WEO and USAspending anchors stop being refetched on every run. For forecasts saved before this change, use forecast_extractor.official_auto_resolvable(row) on the stored row.
- For G3 (frontend) or G1 (exec brief), optional: the data-anchor column and exec-brief watch lines could show 'manual settlement' when data_anchor.auto_resolvable is False. Nothing in G1's or G3's code changed in this round.
- Concurrent edits: deerflow_bridge/data_sources.py moved by about 60 lines while I worked (another slice). My code uses only its public API (Series.from_dict, catalog.lookup, GEOGRAPHIES, query_geographies, validate_data_anchor/resolve_data_anchor), and the flag-versus-resolver test will catch any future change to which rows the data layer marks resolution-unsafe.
- Progress notes: scratchpad/glue/G2-notes.md. Evidence (pre-change module copy, red/green summaries, live log, parity script): scratchpad/glue/G2/. The scratchpad can be wiped; this result holds the summary.

## glue:A

All five Role A leftovers are done and tested. Every new test fails against a copy of data_sources.py with my changes reverted and passes now. My 9 owned test files pass (479 tests). Across 32 related test files, 1957 pass and 1 is skipped (not the full suite). The live whole-catalog smoke run returned 288 of 288 series ok and exited 0.

(1) A BIS window with no observations came back as provider_error. Two causes: the hub cuts BIS's "ARE valid ... genuinely empty result" text short, and no failure pattern matched it. Fix: `_call` now raises provider tool errors as `_ToolFailure`, a ValueError whose `.detail` holds the full scrubbed text; str() is unchanged. `_fetch_bis` turns BIS's own diagnosis (`_bis_failure`) into not_found for a valid key with nothing in the window, or unknown_series for a key BIS never published. Example not_found message: "BIS publishes this series but has no observations from 2026-09-01 to 2026-09-30; its most recent observation is 2026-08", plus the first clause of BIS's note. The resolution monitor now shows an unpublished BIS period as pending instead of manual; a test checks this through `_unusable_fetch_status`.

(2) A FRED series fetched by the API route that is not in the catalog now gets geography USA only when FRED's own tags confirm it. The check is a fred_search by series id with tag_names nation;usa, and the exact id must be in the results; `provenance.geography_basis` records it. `series_label` now gives "Sticky Price Consumer Price Index less Food and Energy — United States", while NIKKEI225 and California series get no geography. The lookup is best effort and never fails the fetch. It is capped at the smaller of 5 s and half the remaining deadline, because a review showed that without the cap it could make the fetch hit its deadline. Data360 needed no change: stored rows already carry the country from the id, and search lines take it from the id.

(3) `observation_kind` and `latest_observed` now apply the same completeness rule that `forecast_extractor._official_legacy_periods` applies, but only to calendar months of rows stored under policy below 3 (a version that is a bool counts as not legacy). A month counts as complete when its coverage is the whole month and either a later month is stored or the row was retrieved more than 7 days after the month ended. On the stored policy-2 DGS10 and Debt to the Penny rows, the data layer, `forecast_extractor.official_observation_kinds` and `official_data.historical_snapshot` now all report 2026-09 as the latest month and the open month 2026-10 as partial. Before, the snapshot showed no history for these rows. Stored pages still re-render byte for byte, because pages for policy-2 rows use the private `_observation_kind`.

(4) The fixtures README now indexes every entry in real/ with the tests that read it, with policy versions checked against the files. A new test, `test_fixture_readme_indexes_every_real_capture`, keeps the index complete. The README also lists the three new 2026-10-13 captures.

(5) Whole-catalog smoke run: 288 of 288 ok, 379.3 s. Per provider: fred 82/82, bls 45/45 (2 batched calls), bis 50/50, usgov 51/51, wb 54/54, imf 6/6 with 34 skipped by the cap of 6. All routes were mcp, every unit matched the catalog, and no fallback was used. The only series with no latest observed value is usgov:spending/total, which is the existing status policy.

Scratch notes (may be wiped): /private/tmp/claude-501/-Users-rogerlin-Downloads-DeepResearchForecast/52225542-51e1-41e1-b738-38d44834da7e/scratchpad/glue/A-notes.md. Evidence files are under scratchpad/glue/A/.

Done:
- (1) BIS empty or unpublished window now returns DataError not_found (with the latest published period and the first clause of BIS's note); a key BIS never published returns unknown_series. Tested through a replay of a real capture, and checked that resolution_monitor._unusable_fetch_status reports pending.
- (2) FRED series found by search get geography USA (and the label '— United States') only when FRED's tags nation;usa confirm the exact id. The lookup is best effort and capped at min(5 s, half the time left). Data360 already labels rows by the id's country.
- (3) observation_kind and latest_observed re-derive completeness for policy-2 calendar months using forecast_extractor's rule (whole-month coverage, and a later stored month or retrieval more than 7 days after month end). The data layer, the forecast extractor's labels and the historical snapshot now all report 2026-09 as the latest month on real policy-2 rows, and stored pages still re-render byte for byte.
- (4) Fixtures README has a full index of real/ (providers, stored_v2, legacy, gateway, visuals, downstream, v3_engine, report bundle, forecast carrier, forecast_history_v3, catalog files) with the tests that read each, plus the 2026-10-13 captures; a new test keeps the index complete.
- (5) backend/scripts/datamcp_smoke.py run over the whole catalog: 288/288 ok, exit 0, 379.3 s; tool calls fred 82, bls 2, bis 50, imf 11, wb 108, usgov 133; all routes mcp, units match the catalog, no fallbacks; 34 IMF ids skipped by the cap.
- New real fixtures: backend/tests/fixtures/data_sources/real/providers/bis_empty_window_and_unknown_key.json, fred_search_discovered_national_geography.json, fred_search_discovered_untagged_geography.json (checked: no key values in them).
Not done:
- interim-v3-daily-rows: Some rows in the evidence run pipe_261de6107490 were stored while slices were mid-edit: fred:DFEDTARU, DFEDTARL and T10YIE are labelled normalization_policy_version 3 but have the old daily shape (no aggregation_method or latest_daily, every month complete=False). latest_observed() therefore returns None for the Fed target range in that run. I deliberately did not re-derive completeness for them. Changing their status would change render_series_page for these policy-3 rows, and both research_gateway.restore_data and data_tools require the re-rendered page to match the stored page byte for byte, so the rows would become invalid on resume. All 8 of that run's v3 pages still re-render identically with the current code. Recommendation: treat these as artifacts of the mid-edit window and re-run, rather than adding a special case.
- data360-non-catalog-geography-names: For a Data360 country code outside catalog.GEOGRAPHIES (14 economies), series_label shows the code (e.g. '— VNM'). Using the REF_AREA_NAME the provider returns would make series_label differ from render_data._series_label (Role F's copy, which a parity test compares). The clean fix is for B to extend data_catalog.GEOGRAPHIES and for F to mirror it.
Tests:
All runs from backend/ with .venv/bin/python -m pytest -q -p no:cacheprovider.

Before my edits, my 9 owned files plus test_data_catalog passed.

After the edits:
- My 9 owned files (test_data_sources, _config, _interfaces, _normalization, _providers, _smoke, test_data_mcp, _deadline, _pacing): 479 passed.
- Owned files plus test_resolution_monitor, test_official_data_downstream and test_research_gateway_official_data, run with the default addopts (the CI form): exit 0.
- 32 related files: 1957 passed, 1 skipped. These are all test_data_* files, test_forecast_extractor(_official), test_report_visualizer_official, test_report_official_data, test_report_official_publication_real, test_report_data_publication, test_official_data_{consumers,downstream,promotion,end_to_end}, test_research_gateway(_official_data), test_v3_official_data, test_legacy_official_data, test_resolution_monitor, test_orchestrator_research_wiring, test_canonical_world_brief_denials, test_settings_data_sources_probe and test_exec_brief. Log: scratchpad/glue/A/related2.txt.
- An earlier related run had 3 failures in test_v3_official_data (D's file). One was D's baseline-table assertion, which D has since updated to expect the 2026-09 latest month this change produces. Two came from B's data_catalog.py while it was mid-edit (NameError `_ranked`). All 3 pass on re-run.

Red-before check: scratchpad/glue/A/tools/make_before.py rebuilds data_sources.py with my edits reverted, and tools/run_with_before.py binds the bare name `data_sources` to that copy. Result: 10 new or updated tests fail and 16 controls pass (red_before_final.txt). The deadline-cap test also fails against a copy without the cap. The README index test fails against the HEAD README (18 entries missing).

ruff (`uvx ruff check --select F,E9 --ignore F401,F841,F541`) on data_sources.py, data_mcp.py, both test files and datamcp_smoke.py: all checks passed.
Live checks:
All live calls went through scratchpad/live/with_data_keys.sh using backend/.venv (mcp 1.30.0, works), with caches under scratchpad/glue/A/. No paid LLM calls were made and no key values were printed.

- BIS probe (bis_empty_probe.json): 3 raw fetch_dataset calls plus 2 gets. Captured the 'ARE valid ... genuinely empty result' text for WS_LONG_CPI M.US.771 in 2026-09 (latest published 2026-08), the WS_CBPOL M.US future-month text with BIS's note, and the 'never published' text for M.ZZ. Before the fix the data layer returned provider_error.
- FRED tag probe: CORESTICKM159SFRBATL returned 1 hit; NIKKEI225 and CAUR returned 0; UNRATE returned 16 substring matches including the exact id.
- Fixture capture through the working-tree adapter: 4 FRED calls.
- Live check through DataSources (live_verify.json):
  - bis:WS_LONG_CPI/M.US.771 for 2026-09: not_found, latest 2026-08.
  - bis:WS_CBPOL/M.DE: not_found, latest 1998-12, note 'discontinued as Germany joined the euro area'.
  - bis:WS_CBPOL/M.ZZ: unknown_series.
  - bis:WS_CBPOL/M.US: latest 3.875 (2026-09).
  - fred:PCETRIM12M159SFRBDAL: geography USA, label 'Trimmed Mean PCE Inflation Rate — United States'.
- Whole-catalog smoke (smoke/report.json, smoke.log): 288/288 ok, exit 0, 379.3 s.
  - Per provider: fred 82, bls 45 (2 batched calls), bis 50, usgov 51, wb 54, imf 6 (34 skipped by the cap).
  - All routes mcp, units match the catalog, no fallbacks.
  - BLS calls this session: 2 (budget 5). FRED was paced at 30 calls per minute in the smoke run, and no other FRED calls overlapped with it.
Open issues:
- Lead: the evidence run pipe_261de6107490 stored DFEDTARU, DFEDTARL and T10YIE during the mid-edit window. They are labelled policy 3 but every month is complete=False and aggregation_method is missing, so latest_observed() is None and the pack, charts and anchors have no latest Fed target range value for that run. Its pages still re-render identically with the current code, so a resume will not invalidate them. Re-running is the clean fix; the data layer deliberately does not re-derive completeness for these rows, because that would break the byte-identity check on resume.
- D, C and E: a FRED series fetched by id that is not in the catalog now costs one extra paced FRED call (the tag lookup, capped at min(5 s, half the time left), and cached together with the series). Tests that count FRED calls for such ids must allow a fred_search call; I updated my own overflow test accordingly.
- F and B: series_label shows the code for Data360 countries outside data_catalog.GEOGRAPHIES (e.g. '— VNM'). Extending GEOGRAPHIES (B), mirrored in render_data._GEOGRAPHIES (F), would fix series_label, charts and snapshots together.
- Lead: the not_found change also helps v3 agents. A discontinued or unpublished BIS key now returns a short reason with the latest period and BIS's note, instead of a cut-off 'user_error: ...' text.
- Lead: please stage the 3 new fixture files under backend/tests/fixtures/data_sources/real/providers/ together with test_data_sources_providers.py. The whole real/ directory is still untracked.

## audit:U2-legacy

U2-legacy: I checked how agents in the legacy engine get and use official data, rendering the real prompts for the six questions in every phase. I made 7 changes, each with a test that fails on the old code and passes now. The biggest gap: the parallel deep phases 2–4 (primary-evidence, actors, contradictions), the fan-out scoped workers, the top-up/gap/triangulation/refine passes and delegated task subagents never saw which official series the run had already stored. Only the opening prompt carried the pre-pass brief.

What changed, and the verdict per phase × question:

| Phase | Q1 CPI/Fed | Q2 data centres | Q3 China NEV | Q4 ECB rate | Q5 semis | Q6 中国GDP |
|---|---|---|---|---|---|---|
| P0 pre-pass storage (unchanged) | B+: 6 stored (WEO CPI to 2031, BIS midpoint, CPIAUCSL, FEDFUNDS, CPIAUCNS, DFEDTARU); CPI stored as index levels and SA/NSA duplicated | without the EIA key: none stored; with it: 3 EIA commercial sales (US/VA/TX) | correctly none (no provider covers it) | BIS euro-area rate (it is the deposit rate since 18 Sep 2024, but the label does not say so) | correctly none | WEO China, 2027 = 4.033% |
| P1 opening prompt | B → A- | B → A- | C (no stop rule) → B+ | B → A- | C → B+ | B → A- |
| P2 deep phases (2–4 isolated) | C → A- (6-line index) | C → A- (3 lines) | C → B+ | C → A- | C → B+ | C → A- |
| P3 fan-out workers / P4 top-up and gap | C → A- | C → A- | C → B+ | C → A- | C → B+ | C → A- |
| P5 task subagents | C+ → B+ | C+ → B+ | C+ → B | C+ → B+ | C+ → B | C+ → B+ |
| P6 triangulation / refine | C → B+ | C → B+ | C → B | C → B+ | C → B | C → B+ |
| P7 synthesis official block (unchanged) | A | A | n/a | A | n/a | A |
| P8 tool schemas | B+ → A- | same | same | same | same | same |
| P9 skills | B → A- | same | same | same | same | same |
| P10 finalization (unchanged) | A: 6 charts, English baseline table, citations renumbered | A | n/a | A | n/a | A: Chinese baseline heading, 1 chart |

The improvements come from 7 changes:
- **Stored-series index (fixes P2–P4, P6):** a list of series already stored this run is now added to the deep-phase, fan-out worker, top-up, gap, triangulation and refine prompts. Each line shows the id, label and units, the latest observed value with its period, any newer value that is not a confirmed observation, and the publisher projection years, read from the stored series. It has no citation marker, because a stored id is returned free by `data_get` and the agent should read the page before citing.
- **When-to-use guidance (fixes P1 and every worker prompt):** the official-data paragraph now says when to use the tools (official statistics and base rates, rather than copying numbers from web pages). It gives the request shape: an early `start` for history, and the latest 240 observations are kept. It also says to stop after one search when no provider covers a concept. It now explicitly allows reading the data-sources skill file, which conflicted with the deep opening prompt's `read_file` rule.
- **Subagent budget (P5):** deer-flow `task` subagents run on the lead's thread_id, so they were using up the lead's per-thread data budget. Their calls now go to their own bucket. I confirmed in the deer-flow venv that the subagent tag reaches the real bound tool.
- **Subagent instructions (P5):** subagents now get the same when-to-use guidance, plus a note that stored ids named in their brief are free.
- **Tool schema (P8):** the `data_get` start field states the 240-observation bound.
- **data-sources skill (P9):** the date rule was wrong. It now says `YYYY`, `YYYY-MM` or `YYYY-MM-DD` covering the whole period, which I checked against both engines. It also gives the base-rate start rule, and the skill description now lists prices, rates, trade, energy, base rates and outlooks.
- **deep-research skill (P9):** base rates now point to long official history via `data_get`. The file stays under its 7,000-character cap at 6,983, after I removed one sentence explaining why the core is short.

Evidence:
- **Real run `pipe_261de6107490`:** this was a v3 run, not legacy. Every topic's tool stats show web calls only. The labour-market and base-rate topics (K4, K7) never fetched a series, so agents leaned on the prefetched series.
- **Prompt rendering:** before/after renders over the real stored pre-pass series are in `render/compare/<q>/` and `summary.json`.
- **Byte-identical when data is off:** 192 prompts are byte-identical before and after when official data is disabled or unregistered, even with stored series present.
- **Deployment:** a dry run of the skill sync deploys all six skill bundles, and the edited SKILL.md files come out byte-identical. `data_tools.py` and `deerflow_research.py` are copied by `_sync_deerflow_bridge_if_stale` at the next launch. The two `config.yaml` copies are identical and both register `data_search`/`data_get` and list them, plus the data-sources skill, for scoped-researcher; I did not edit `config.yaml`.

Notes are in `/private/tmp/claude-501/-Users-rogerlin-Downloads-DeepResearchForecast/52225542-51e1-41e1-b738-38d44834da7e/scratchpad/glue/U2-legacy-notes.md`.

Done:
- Index of stored series (_official_data_stored_block) added after the official-data paragraph in the deep-phase, top-up, gap-closing, scoped-worker, report-refine and triangulation prompts. It is bounded to 12 lines and 240 characters per line, has no citation marker, never fails a prompt, and is empty when data is off, nothing is stored or the stored-series file is unreadable.
- Official-data prompt paragraph rewritten: when to use the tools (official statistics and base rates, not numbers copied from web pages), the request shape (early start, latest 240 observations kept, WEO/GEP projection years), one search then stop when no provider covers a concept, and explicit permission to read the data-sources skill file.
- data_tools._agent_key: deer-flow task subagents (tagged subagent:<name>) now use their own per-thread budget instead of the lead's. The run-wide cap still applies. Verified with the real bound tool inside a langgraph agent in the deer-flow venv (bucket_probe.py).
- Runtime instructions for the scoped-researcher subagent now include when to use the data tools, the early start for history, and that stored ids named in a brief are free.
- data_get schema: the start description gives the early-start rule and the 240-observation bound.
- data-sources SKILL.md: date grammar corrected (YYYY / YYYY-MM / YYYY-MM-DD covering the whole period, checked in both engines); base-rate early start and 240 bound; skill description broadened. 7,092 bytes, under the 8,000 cap.
- deep-research SKILL.md: base rates now point to long official history via data_get. 6,983 characters, within the 7,000 cap; headings unchanged.
- 8 new tests in backend/tests/test_legacy_official_data.py. On a copy with the pre-edit owned files, exactly the 7 tests that need my changes fail and the 76 existing tests pass (red_before_final.txt). After the changes: 83 passed.
- Rendered the legacy prompts for all 6 questions in every phase (opening standard and deep, the 5 deep phases, top-up, gap, scoped worker, refine, triangulation, synthesis official block), with the real pre-pass run live: about 11 provider calls, no paid LLM calls. Before/after renders are in render/compare.
- Proved byte-identical prompts when data is disabled or unregistered: 192 prompts, before vs after, with stored series present (identity_check.py).
- Rendered the data tool schemas as deer-flow binds them (tool_schemas.py) and read the SKILL.md files and references agents read.
- Confirmed deployment: the skill sync dry run deploys all 6 bundles byte-identically; data_tools.py and deerflow_research.py are synced by _sync_deerflow_bridge_if_stale; both config.yaml copies are identical with data tool and scoped-researcher registrations.
- Ran legacy finalization on the real stored series: Q1 has 6 series, 6 charts, the English baseline table and provisional ids renumbered to positional [S2]/[S7]; Q6 has the Chinese heading 官方数据基线 and 1 chart.
Not done:
- prefetch-selection-redundancy: Q1's pre-pass spends a slot on CPIAUCNS (the not-seasonally-adjusted twin of CPIAUCSL) and stores no year-over-year CPI series (BIS WS_LONG_CPI is skipped). Choosing one series per provider (as v3 does) would drop the series an existing test requires and would lose DFEDTARU (the upper bound) on Fed questions, so I left the selection unchanged. Agents can request fred:CPIAUCNS#yoy, and the stored page says so.
- per-subagent-budget: deer-flow passes no per-task id to a subagent's tool calls (only the parent thread_id and the subagent:<name> tag), so concurrent subagents of one thread share one bucket, now separate from the lead's.
- final-dossier-contract: Not edited: it is embedded in every final synthesis prompt, so changing it would break byte-identical prompts when data is off. The synthesis official-data block already carries the citation and projection rule whenever series exist.
- tool-description-indentation: The bound tool descriptions keep the docstring's indentation. market_tools has the same pattern; this is cosmetic, so I left it.
Tests:
- **Owned test file:** `cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_legacy_official_data.py` gives 83 passed.
- **Red check:** the same file on a scratch copy with the pre-edit owned files gives 7 failed (exactly the new tests that need my changes) and 76 passed.
- **Related files (44):** every test referencing deerflow_research, data_tools or the three skills, plus the test_bridge*, test_loop010*, drf2 skills config, session-B skill hygiene and data catalog tests: 1957 passed, 1 skipped, exit 0 (`glue/U2-legacy/related_run2.txt`).
  - An earlier run had 3 failures in `test_v3_official_data.py` while another agent was editing linear_research.py and that test file at the same time.
  - Those 3 tests pass on rerun and do not depend on my files.
- **ruff** (`--select F,E9 --ignore F401,F841,F541`) on deerflow_research.py, data_tools.py and test_legacy_official_data.py: all checks passed.
- **Scripts:**
  - `identity_check.py`: 192 prompts byte-identical before and after when data is disabled or unregistered.
  - `bucket_probe.py` (deer-flow venv): a call tagged as a subagent goes to its own bucket.
  - Skill-sync dry run: deployed SKILL.md files identical.
  - `finalize_probe.py`: finalization works on the real stored series.
Live checks:
Real legacy pre-pass (`_prefetch_legacy_data`) for the 6 questions, with only the FRED/BLS/BEA/EIA keys exported and DATA_SOURCES_CACHE_DIR in scratch (`glue/U2-legacy/render/live.log`). About 11 provider calls: no BLS, no IMF, no LLM.

| Question | Stored | Time |
|---|---|---|
| Q1 CPI/Fed | 6/6 | 10.1 s |
| Q2 data centres | 3/3 EIA commercial sales (US/VA/TX) | 7.8 s |
| Q3 China NEV | 0 (nothing in the catalog answers it) | — |
| Q4 ECB rate | 1/1 BIS euro-area rate | 0.9 s |
| Q5 semis | 0 | — |
| Q6 中国GDP | 1/1 WEO China | 8.1 s |

- **Q4:** the stored provenance confirms BIS reports the deposit facility rate since 18 Sep 2024.
- **Catalog queries:** `search_probe.py` ran agent-style data_search queries against the catalog only, with no provider calls.
- **Real run `pipe_261de6107490`:** read only, never modified. It is a v3 run; every topic's tool stats show 0 data calls, and the 8 stored FRED series were all prefetched, none fetched by agents.
Open issues:
- Catalog (slice B, data_catalog.py): bis:WS_CBPOL/M.XM needs a note that BIS reports the ECB deposit facility rate from 18 Sep 2024 (before that, the main refinancing rate). Today Q4 agents cannot tell from the label. fred:ECBDFR is also not in the catalog.
- Catalog (slice B): 'US electricity retail price' is answered free with 6 or more EIA retail electricity *sales* ids; the price concept is not matched. 'fed funds rate history' has 0 strong matches. Q2's power-price clause gets no strong match, so the pre-pass stores only consumption.
- .env.example (slice H): LEGACY_DATA_GETS_PER_THREAD and LEGACY_DATA_SEARCHES_PER_THREAD now apply per thread, with a thread's delegated task subagents sharing one separate bucket. The docs should say so.
- Lead: README / agent-progress should mention the stored-series index on legacy isolated-thread prompts and the separate subagent data budget.
- The deployed deer-flow/ copy (data_tools.py, deerflow_research.py, skills) still holds the old files on disk; it is re-synced automatically at the next pipeline launch. Both config.yaml copies are already identical.

# Final round results (exported from workflow wf_302352f3-26b)


## final:V

Role V is done. In Chinese v3 runs, the summary, critique and digest headlines, the deterministic findings, the baseline-table rows and the dossier excerpts now show units in Chinese, e.g. '4.96% 年变化率', '32563.03 十亿美元', '3.875% 年率', '3.397% 同比变化率' and '-166796952277.38 美元 (≈-1667.97亿美元)'. Before, they read '4.96% change per annum', '32563.03 Billions of Dollars' and so on.

All of these texts go through one function, `data_value_text`, which now calls a new `data_unit_text(units, value_text, language)`. Its English path is the old rule, unchanged. Its Chinese path:
- looks the published unit up with `data_units_zh`, a copy that imports nothing of the chart renderer's `render_data._units_zh` (same table, index-base and chained-dollar rules);
- drops the '（%）' when the value already ends in '%';
- shows nothing for a plain percent ('Percent' gives '4.2%', as in English);
- shows a unit outside the table exactly as English does.

The format stays 'value + space + label', the same shape as English, so only the label changes. Every number, period, status and the stored page are byte-identical, and English output is byte-identical. A parity test keeps the copy equal to the renderer's.

Fallback-seed check (from U1): the limitation is real, so I added a comment and changed no behaviour. A question- or clause-level catalog match is linked to the first data KIQ, whichever KIQ it measures. Reproduced with 'Will the US unemployment rate rise above 5% by the end of 2027, and will the Fed cut the federal funds rate below 3%?': fred:FEDFUNDS went only to the unemployment KIQ, and the funds-rate KIQ got only its own match, DFEDTARU. The impact is low: every KIQ task still lists every stored series, and reading one with data_get is free.

One more edit outside the zh task, in my own test file. Another role's (CAT) in-progress `data_catalog.py` change made `test_kiq_hints_measure_the_kiqs_own_question_and_name_fast_routes` fail. It fails the same way with the pre-change `linear_research.py`, so my edit did not cause it. The catalog now ranks core CPI and core PCE (the new 'core inflation' keyword) ahead of the IMF WEO CPI series. I loosened the first-rank check to what the test is for: the WEO CPI series is still among the hints, and every hint is a headline or core price series. The checks that keep policy-rate, BLS and IMF ids out are unchanged.

Notes are in scratchpad/final/V-notes.md and evidence is under scratchpad/final/V/; both may be wiped, so this result holds the summary.

Done:
- deerflow_bridge/linear_research.py: added `_DATA_UNITS_ZH` plus `_DATA_UNITS_INDEX_RE`, `_DATA_UNITS_MONTH_BASE_RE` and `_DATA_UNITS_CHAINED_RE`, copies of render_data's `_UNITS_ZH` and its three regexes (no import of the renderer). Added `data_units_zh(units)` with the same rules as `render_data._units_zh`.
- deerflow_bridge/linear_research.py: new `data_unit_text(units, value_text, language)`. English is the old rule byte for byte. Chinese uses the vocabulary label, drops '（%）' after a '%' value, shows nothing for a bare percent and keeps the English rule for units outside the table. `data_value_text` uses it, so the digest line, headline, outlook headline (summary and critique), findings, table row, dossier excerpt and the other-series list in KIQ tasks all localize.
- Kept on purpose: 'pp' changes and the ASCII ' (≈…)' companion (number formatting; an existing zh test pins '-0.2 pp'). The quantitative.json 'unit' field and actors indicator 'units' keep the published unit, since they are structured data for downstream code. The stored page and render_series_brief are not touched.
- Fallback seeds: confirmed the limitation is real (proto/seed_probe3.txt) and added a comment in `_catalog_seeds`, with no behaviour change. In the deterministic fallback plan (one 'baseline data' KIQ) the assignment is correct; the limitation only shows when the plan has several data KIQs and no data_needs.
- backend/tests/test_v3_official_data.py: added `test_chinese_official_text_names_units_in_chinese_and_changes_nothing_else`. It runs all 29 captured v3_engine rows (2026-10-11 stored and re-normalized, plus 2026-10-12). It pins the zh headlines, checks English is unchanged with the vocabulary switched off, and checks each zh text equals the old zh text with only the unit label swapped. It also checks every number list is identical, the page keeps 'Units: <published>', and pins the fallback and edge cases.
- backend/tests/test_v3_official_data.py: added `test_chinese_unit_labels_are_the_chart_renderers`. It checks the table and regexes equal render_data's, and that `data_units_zh` matches `render_data._units_zh` for every catalog and recipe unit, every 'units' string in the real fixtures and the edge cases.
- backend/tests/test_v3_official_data.py: added `test_chinese_run_summary_critique_digest_and_findings_quote_chinese_units`, a real Chinese engine over 8 captured series. Summary and critique headlines and the digest OFFICIAL DATA block are in Chinese units with no English unit words. The 7 observed findings stay VERIFIED against the English stored page. `_data_checks` accepts exact Chinese quotes, the engine's own headlines and the Chinese baseline table, and rejects a wrong scale ('32563.03亿美元', '159044万人') or a wrong value.
- backend/tests/test_v3_official_data.py: loosened the first-rank check in `test_kiq_hints_measure_the_kiqs_own_question_and_name_fast_routes` (see summary).
Not done:
- zh-pp-change-wording: Changes such as '-0.25 pp' are left as is in Chinese text. They are number formatting from `data_sources.format_change`, not a series unit, and an existing Chinese table test pins them. The report side uses '个百分点'; changing v3 needs a decision from the lead because it touches number-check matching.
- fallback-seed-reassignment: As instructed, the U1 fallback-seed issue is only documented in a code comment. Matching question-level seeds to each data KIQ's own question (`_kiq_catalog_series`) would fix it.
tests_run:
All runs: cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider.

- Final run over 12 files (test_bridge_extensions_config, test_bridge_overhaul_v3, test_deerflow_bridge_sync_guard, test_official_data_end_to_end, test_research_engine_v3, test_research_engine_v3_round2, test_research_gateway, test_research_gateway_official_data, test_v3_official_data, test_orchestrator_research_wiring, test_official_data_downstream, test_data_visuals_official): 1076 passed, 1 skipped, exit 0 (scratchpad/final/V/related_run4.txt).
- Earlier runs:
  - run1: 1 failure, `test_geography_table_mirrors_the_catalog` in test_data_visuals_official. CAT had edited `data_catalog.py` GEOGRAPHIES and render_data had not caught up yet; it passed in later runs.
  - run3: 1 failure, the KIQ-hint test, which fails the same way with the pre-change `linear_research.py` (CAT's catalog change). I loosened that check and run4 passed.
- Red before: a pytest plugin (scratchpad/final/V/redplugin/v_before.py) binds `linear_research` to the copy taken at session start. With it, 3 of the 4 `-k chinese` tests fail (the 3 new ones) and the existing Chinese test passes (red_before_final.txt). All 4 pass on the current code.
- ruff (`--select F,E9 --ignore F401,F841,F541`) on both owned files: All checks passed.
- Before/after rendering dump (tools/dump.py): 64 renderings. English is identical (32/32), page sha256 is identical, and Chinese numbers are identical.
- Finding-tag probe (proto/facts_probe.py): 78 deterministic findings, English and Chinese, from v3, legacy and report-bundle rows (incl. GDPC1 chained dollars, CPIAUCSL index, SAHM points, DEXCHUS FX, Debt to the Penny). VERIFIED/REPORTED tags are identical before and after.
- With official data disabled, U1's prompt_identity.py compared the pre-change and current engine. Standard: 27 calls; deep: 30 calls. Messages, tools, kwargs and order are identical, and so are the artifacts and meta.data_sources (identity/pi_*_{before,after}.json).

The full suite was not run, as instructed.
live_checks:
scratchpad/final/V/live/live_zh_units.py was run through scratchpad/live/with_data_keys.sh with DATA_SOURCES_CACHE_DIR=scratchpad/final/V/live/cache. BLS_API_KEY was removed for the run, so no BLS, IMF or LLM calls were made, and no key value was printed.

It fetched 8 series live in 5.6 s: fred:GDP, PAYEMS, CPIAUCSL and GDPC1 (4 FRED calls), bis:WS_CBPOL/M.US, the World Bank WDI China growth and WEO China series, and usgov:treasury/mts_deficit. For each series it rendered every v3 text with the pre-change and current module. Result: ALL_OK (live/live_run.log).
- English is identical.
- Chinese numbers are identical.
- Chinese finding tags are identical (VERIFIED; the WEO estimate and projection stay REPORTED).
- Every page still shows 'Units: <published>'.
- Example Chinese headlines: '32563.03 十亿美元', '159044 千人', '334.131 指数（1982-1984=100）', '24408.011 十亿美元（2017年链式美元）', '3.875% 年率', '4.96% 年变化率', '4.959% 变化率', '-166796952277.38 美元 (≈-1667.97亿美元)'.
Open issues:
- Lead / CAT: CAT's in-progress data_catalog.py change (the 'core inflation' keyword) now ranks fred:CPILFESL and fred:PCEPILFE ahead of wb:IMF_WEO_PCPIPCH/USA for a 'US CPI and core inflation' KIQ. I loosened the first-rank check in my test to its intent. If CAT's later edits change ranking again, run test_v3_official_data.py again.
- CAT / catalog: with the fallback seeding (no data_needs), 'Will the ECB cut its deposit rate below 2% by mid-2027 …' seeds no series. search_catalog_scored marks no entry strong; bis:WS_CBPOL/M.XM scores concept 6.0 but strong=False, so only the KIQ hint path offers it. CAT's planned fred:ECBDFR and deposit-rate work may fix this; please re-check.
- Lead: with official data the Chinese report text changes. Chinese runs now quote units such as '4.96% 年变化率'. The official-data number checks accept these and reject wrong Chinese scales (亿 vs 十亿, 万 vs 千), proven in the new engine test. Prompts with official data disabled are byte-identical.
- F and V: render_data._UNITS_ZH and linear_research._DATA_UNITS_ZH must change together. The parity test in test_v3_official_data.py fails if they drift. A unit outside the table falls back to the published unit in both, and today all 96 catalog and recipe units are in the table.
- Lead: stage backend/tests/test_v3_official_data.py together with deerflow_bridge/linear_research.py.

## final:L

Role L reviewed all 10 edits the U2-legacy rerun made before it died on a 403 error. The rerun's last edit (clause-level #yoy selection) was complete: green now, and red against the rerun's own earlier whole-brief version. I found and fixed 3 bugs in the rerun's logic, each with a test that fails on the start state and passes now.
- (1) BEA keeps its default window in the pre-pass. `_legacy_prefetch_starts` gave usgov:bea/* a 30-year start. A live probe showed this fails: BEA's GDP-by-industry recipe rejects years before 2005 ("Invalid year: 2004", provider_error), so the pre-pass lost the series. A 30-year NIPA window also took 16 sequential calls.
- (2) A weekly index is never turned into #yoy. "Will US financial conditions tighten as inflation rises in 2027?" pre-fetched fred:NFCI#yoy, which the data layer rejects because it does not compute a year-over-year rate for weekly series. The stored-series index also offered that route. The new helper `_yoy_index_level` handles both places.
- (3) `data_tools._window_note` no longer flags a forecast-horizon end. A stored window that ran to its retrieval date holds everything published, but `data_get(id, end="2027")` still got "not refetched; longer history needs another series".
I added coverage for rerun behaviours that had no test: the delivery-trim branch of the window note, the line bound dropping whole parts, all six isolated worker builders passing the question, and the "12-month" rate phrasing. Eight mutation checks are all caught by the tests.
I re-rendered the legacy prompts for the six audit questions after a live pre-pass with the real catalog: 16 provider calls, no failures, no BLS/IMF/LLM calls. Every isolated worker prompt (deep phases, top-up, gap-closing, scoped worker, refine, triangulation) carries the question's stored-series index, and the opening prompts carry the pre-pass brief. With official data off, all 96 prompts are byte-identical across HEAD, pre-rerun, start and final in both disabled and unregistered modes.
Before → after per question (pre-rerun → final):
- Q1 CPI/Fed. Before: CPI stored as index levels (334.131) in default windows; the daily Fed target held 2 years. After: CPIAUCSL#yoy 3.353% and CPIAUCNS#yoy 3.397% for Aug 2026, each with 240 observations from 2006-09. DFEDTARU from 2008-12, BIS rate and FEDFUNDS from 2006-10, WEO CPI from 1996 with 2027 = 2.141% shown to isolated threads. 6/6 stored in 19.1 s.
- Q2 data centres. Five series (EIA commercial electricity sales for US, VA and TX, EIA retail price, CPI electricity) now hold 240 months from 2006-08. The index offers `data_get fred:CUUR0000SEHF01#yoy`.
- Q3 China NEV share and Q5 semiconductor sales. Correctly nothing stored; the official-data paragraph rules out proxy series.
- Q4 ECB rate. fred:ECBDFR (newly added by the catalog owner) and BIS euro-area rate, 240 months each.
- Q6 China GDP. WEO from 1996 with 2027 = 4.033% shown to isolated threads; also World Bank GEP and WDI.
- Synthesis and finalization unchanged: Q1 6 charts, Q2 5, Q4 2, Q6 3 with the Chinese baseline heading; citations renumbered to positional [S<n>].
Index lines now carry seasonal adjustment (SA/NSA twins are told apart), where the stored history starts, and the projection value for the year the question names.

Done:
- Reviewed every rerun edit; all correct as intended except the three fixed below. data_tools: _window_note coverage rule (matches v3) and prefetch_impl(starts=) with fallback to the default window. deerflow_research: the 'transform yoy' and 'related series is context, never a stand-in' wording, the scoped-researcher yoy clause, and the _official_data_stored_block(question) rewrite (SA/NSA marker, 'stored from', question-year projection values, yoy route, label capped at 120 chars, whole parts within 320 chars). Also: question passed at all 6 call sites, _legacy_prefetch_starts, the _PREFETCH_RATE_RE clause-level #yoy selection, and meta history_starts (no consumers).
- Rerun's unfinished last step verified: its own test run r2_run3 passed (EXIT=0); the clause-level assertion fails on the rerun's intermediate whole-brief version (final/L/red_mid.txt) and passes now.
- Fix 1: _legacy_prefetch_starts skips usgov:bea/* (docstring states why). Live evidence in final/L/live/bea_probe.log: value_added_by_industry/334 with start 2004 -> provider_error 'Invalid year: 2004'; real_gdp_growth from 1996 -> 16 calls in 9.6 s.
- Fix 2: new _yoy_index_level(units, frequency) (index units, never weekly), used by _legacy_prefetch_ids for #yoy and by the stored-index yoy route.
- Fix 3: data_tools._window_note checks the end side only when the stored window ended before its retrieval date (cut_short); an unparseable retrieved_at keeps the old rule.
- New tests in backend/tests/test_legacy_official_data.py: test_pre_pass_keeps_the_default_bea_window (real BEA 514 capture replayed through a real DataSources), test_weekly_index_is_never_given_a_year_over_year_route, test_a_forecast_horizon_end_is_no_window_gap, test_rows_the_delivery_bound_dropped_were_never_stored, test_stored_index_leaves_out_a_whole_part_that_overflows_the_line. _worker_prompts(question) now checks that all 6 isolated builders carry the question's index; added a '12-month change' #yoy assertion; _replay_sources takes env and clock. Catalog-dependent assertions are relaxed so new catalog entries do not break them.
- Red/green: final/L/red_start1.txt (start-state owned files) -> exactly the 3 fix tests fail. final/L/red_prerun.txt (pre-rerun files) -> the rerun's 8 tests plus my 3 fail, nothing else. final/L/mutants.txt -> 8/8 mutants caught (question dropped in one caller, trim branch removed, line cut, stop at overflow, weekly index route, weekly prefetch yoy, BEA history start, v3-style end rule).
- Re-rendered the legacy prompts for the 6 audit questions after a live pre-pass with keys (final/L/render/prompts/<q>/*.txt, render/summary.json): opening standard/deep/evidence-lane, 5 deep phases, top-up, gap-closing, scoped worker, refine, triangulation, synthesis official block. The index is in every isolated prompt; all index lines are 254 chars or fewer.
- Byte-identity with official data off (final/L/identity_check.txt): 96 prompts in disabled and unregistered modes identical across HEAD, pre-rerun, start and final, with a stored journal present. HEAD was given its own deep-research skill beside it; without that, the module cannot find final-dossier-contract.md.
- Finalization over copies of the live journals (final/L/finalize_probe.log): Q1 6 series / 6 charts, Q2 5/5, Q4 2/2, Q6 3/3 with the zh heading; provisional citations renumbered.
- Deployment: deer-flow/deerflow_research.py and deer-flow/data_tools.py are stale now and are re-copied by pipeline_orchestrator._sync_deerflow_bridge_if_stale before each research launch (data_tools.py is in its module list). Skills unchanged by me.
- Notes: /private/tmp/claude-501/-Users-rogerlin-Downloads-DeepResearchForecast/52225542-51e1-41e1-b738-38d44834da7e/scratchpad/final/L-notes.md
Not done:
- sa-nsa-twin-slot: Q1's pre-pass still spends one of 6 slots on both CPIAUCSL#yoy (SA) and CPIAUCNS#yoy (NSA, the BLS headline basis). The rerun chose to label the twins SA/NSA in the index rather than drop one, and existing tests require both. I kept that choice; deduplicating them is a behaviour change worth a separate decision.
- v3-window-note-parity: research_gateway._window_note (v3, owned by role V) has the same false positive on a forecast-horizon end. Not my file; the legacy rule now differs from v3 only by the cut_short condition.
- default-after-explicit-window: Like v3, a default request (no start/end) after a narrower explicit stored window gets no coverage note. The pre-pass now stores open-ended 30-year windows, so the common case is held. Covering the rare case would mean copying the data layer's per-frequency default-window rules, so I left it.
tests_run:
All runs from backend with `.venv/bin/python -m pytest -q -p no:cacheprovider`.
- Owned set: test_legacy_official_data.py (94 tests), test_loop010_global_synthesis.py, test_loop010_research_contracts.py, test_deerflow_bridge_sync_guard.py, test_data_visuals_official.py, test_data_visuals_render.py, test_data_visuals_status.py. 262 tests, 0 failures, 0 errors (final/L/junit_owned.xml).
- Related set: 46 files (every test referencing deerflow_research, data_tools or the owned skills, plus test_bridge*, test_loop010*, skill hygiene, data catalog and data visuals). Exit 1 with exactly 4 failures, all from the catalog owner's data_catalog.py edit at 02:02, which is still in progress and none of which involve my changes:
  - test_data_catalog.py ×3: zh tenor ranking, movement verbs, reference files not yet regenerated.
  - test_v3_official_data.py::test_kiq_hints_measure_the_kiqs_own_question_and_name_fast_routes: CPILFESL now outranks WEO CPI.
  - Log: final/L/related_run1.txt.
- Red checks:
  - red_start1.txt: only the 3 fix tests fail.
  - red_prerun.txt: the rerun's 8 tests plus my 3 fail.
  - red_mid.txt: the clause-level #yoy assertion fails on the rerun's intermediate version.
  - mutants.txt: 8 of 8 mutants caught.
- ruff: `uvx ruff check --select F,E9 --ignore F401,F841,F541` on deerflow_research.py, data_tools.py and test_legacy_official_data.py. All checks passed.
- Not run: the full suite (left to the lead).
live_checks:
All runs used scratchpad/live/with_data_keys.sh with DATA_SOURCES_CACHE_DIR under scratchpad/final/L/cache; no BLS, IMF or LLM calls.
- BEA probe (final/L/live/bea_probe.log):
  - usgov:bea/value_added_by_industry/334 with start/end 2004: 1 call, DataError provider_error "Invalid year: 2004".
  - usgov:bea/real_gdp_growth from 1996: 122 quarters, 16 chunk calls, 9.6 s.
- Six-question live pre-pass and prompt render (final/L/live_render.log, render/summary.json): 16 provider calls, 0 failures.

| Question | Stored | Time | Series |
|---|---|---|---|
| Q1 CPI/Fed | 6/6 | 19.1 s | WEO CPI, BIS US policy rate, CPIAUCSL#yoy, FEDFUNDS, CPIAUCNS#yoy, DFEDTARU; 30-year starts; 240 obs kept from 2006 (DFEDTARU from 2008-12) |
| Q2 data centres | 5/5 | 16.2 s | EIA commercial sales US/VA/TX, EIA retail price, CPI electricity (fred:CUUR0000SEHF01); from 2006-08 |
| Q3 China NEV | 0 | 0 s | correct: no provider covers it |
| Q4 ECB rate | 2/2 | 1.6 s | fred:ECBDFR, bis:WS_CBPOL/M.XM |
| Q5 semis | 0 | 0 s | correct: no provider covers it |
| Q6 中国GDP | 3/3 | 4.7 s | WEO 1996–2031 (2027 = 4.033%), GEP, WDI 1996–2025 |

- Pre-rerun vs final selection and index over the same journals: final/L/compare_index.txt.
Open issues:
- Catalog owner: usgov:bea/value_added_by_industry needs min_start 2005-01-01. Without it, an agent's data_get with an earlier start fails with provider_error 'Invalid year' (live evidence in final/L/live/bea_probe.log). The legacy pre-pass now avoids this by keeping BEA's default window.
- Catalog owner: the bis:WS_CBPOL/M.XM label still does not say BIS reported the main refinancing rate before 18 Sep 2024 (deposit facility rate after). fred:ECBDFR is now in the catalog and pre-fetched for Q4, which mitigates this.
- Catalog owner, in progress: data_catalog.py edited at 02:02 currently breaks 3 tests in test_data_catalog.py and test_v3_official_data.py::test_kiq_hints_measure_the_kiqs_own_question_and_name_fast_routes. The same owner also edited my skills/data-visuals/scripts/render_data.py at 02:03, extending _GEOGRAPHIES to mirror data_catalog.GEOGRAPHIES. That edit is legitimate and equality-tested (test_data_visuals_official passes with it), so I did not revert it.
- V (v3 owner): research_gateway._window_note should get the same cut_short end rule as legacy, so data_get(id, end=<forecast year>) on a series stored through its retrieval date is not told 'not refetched; longer history needs another series'.
- test_legacy_official_data.py::test_agents_learn_the_year_over_year_route_for_index_levels asserts two sentences of skills/data-sources/SKILL.md, which the catalog owner owns. If that owner rewrites those lines, update the assertion.
- Lead: README / agent-progress should mention that the legacy pre-pass stores 30-year base-rate history (BLS and BEA keep default windows) and stores CPI-type index levels as #yoy when the question asks about a rate.

## final:R

Role R has finished. First I confirmed and checked what the earlier U3 attempt left. Then I ran the audit again on the six real carriers (backend/tests/fixtures/data_sources/real/agent_usage/carriers-2026-10-13.json), with live data, and fixed eight more weaknesses. Each fix has a regression test that fails on the pre-change code and passes now.

**U3 leftovers.** Both were already complete in the tree:
- the elision-helper unit test (test_long_publisher_paths_keep_the_horizon_year);
- the world-brief header and canonical-brief tests.
All 580 tests in the owned files passed at the start.

**What the fresh audit found and fixed:**
- **Units with a scale word but no "of" (bug).** In "Million kilowatt-hours" and "Thousand megawatt-hours", the anchor matcher read the scale word as part of the number. So no anchor on an EIA series could ever be admitted, which ruled out every anchor for Q2's core metric. The report's stored-series claim check (RPT-1) had the same bug: it marked the true claim "150,578.728 million kilowatt-hours in July 2026 [S4]" as contradicted and would strip its [S#].
- **Year at the end of a sentence (bug).** An annual year followed by a full stop ("… in 2027.") was not read as a period. Every annual binary written as a normal sentence lost its anchor, and claims ending "… in 2024." could not be checked.
- **Provider name with digits.** A criterion citing "(source: … World Bank Data360)" was rejected because of the digits in "360".
- **Chinese growth wording.** "实际GDP增速" did not match a "增长率" series, and acronym keywords such as "gdp增速" were filtered out. Q6's headline binary could not anchor.
- **FRED series stored without a geography.** fred:ECBDFR was rejected against "ECB" statements. The matcher now falls back to the catalog's geography, then to the one place its title names.
- **Binary prompt.** It never said how to name the metric in the statement, so anchors were silently dropped when the title is long or the statement says "增速". It now says: use the listed title or a short form of it; otherwise put the canonical ID in parentheses after a plain name.
- **Outside-view window.** "16-period change quantiles" did not say which window the numbers describe. Lines now read "16-month change to the horizon 2027-12 (n=101)", or "12-month change (a standard window, not the horizon; n=105)", with Chinese equivalents. All eight Q2 series still fit within 3,600 characters.
- **Magnitude in the agents' pack.** A value stored in thousands or millions now carries the amount it stands for: "58522249 (≈ 58.52 billion U.S. Dollars)" next to the $1-trillion question in Q5. Published tables and the API are unchanged, so the frontend's matching of backend number formats still holds.
- **Section prompts.** Sections that receive the outside view are now told how to quote it: as this report's own calculation, without an [S#], because the citation audit checks every marker against stored values.
- **World briefs.** The snapshot had room for two or three rows, and all of them went to the question's first clause: Q1 showed no policy rate, Q2 no power price. Rows now take turns by question clause, using the new forecast_extractor.official_question_mention and SimulationConfigGenerator._official_data_for_question.

**Prompts are unchanged when official data is absent.** I rendered outline, section, spine, critique, pre-mortem, binary, chat, world brief and canonical brief for all six questions (54 prompts). All 54 are byte-identical to both the pre-U3 code and the HEAD versions of the owned modules. The English and Chinese real-bundle publication tests still pass.

**Judgement, pre-U3 → final** (U3 and R work together; the prompt × question letter grades are my judgement, informed by measurements of the rendered prompts):

| Prompt | Q1 CPI/Fed | Q2 data centres | Q3 China NEV | Q4 ECB rate | Q5 semis | Q6 中国GDP |
|---|---|---|---|---|---|---|
| Outline | B- → A- | C+ → A- | C → B+ | B- → A- | C → B+ | C+ → A- |
| Section (indicator) | C+ → A- | C+ → A- | C → B+ | C+ → A- | C → B+ | C+ → A- |
| Forecast spine | B- → A | C+ → A | C+ → B+ | B → A | C+ → B+ | B- → A- |
| Binary extraction | C+ → A- | D → A- | C → B+ | C+ → A- | D → B+ | D → A- |
| Critique / pre-mortem | C+ → A- | C+ → A- | C → B+ | C+ → A- | C → B+ | C+ → A- |
| Report chat | B- → A- | B- → A- | B- → B+ | B- → A- | C+ → A- | C → A- |
| Simulation world brief | F → B+ | F → B+ | F → B | F → B+ | F → B | F → B |
| Canonical world brief | F → A- | F → A- | F → A- | F → A- | F → A- | F → B+ |

Why the grades moved:

**Outline**
- *Before:* the pack showed only the last publisher value (2031), day-precision periods and no daily-aggregation note. The plan rule forced indicator sections even for tangential series (Q3, Q5), and the Chinese report got an English pack.
- *After:* full publisher path through the horizon year, reader periods, end-of-month vs monthly-mean basis, a relevance rule, a Chinese pack, and magnitude companions (Q2, Q5).

**Indicator section**
- *Before:* pack only.
- *After:* pack plus the outside view with explicit windows and the quoting rule.

**Spine**
- *Before:* outside view capped at 2,400 characters, which dropped two series each in Q1 and Q2; index and level series had no percent changes.
- *After:* every series fits, percent changes for levels and indexes, explicit windows, magnitudes.

**Binary extraction**
- *Before:* duplicated header and optional anchors, with no month-end, naming or exact-value rules. Q2 EIA, Q5 annual ("… in 2027.") and Q6 增速 anchors were impossible, and in the real run four DFEDTARU binaries and the CPIAUCSL binary went unanchored.
- *After:* one header, mandatory anchors, end-of-month and deadline rules, the naming rule with the ID fallback, and the matcher fixes.
- *Probe of natural core binaries:* at the U3 state, Q2, Q5 and the Q6 WDI case were all rejected and some Q1/Q4 cases failed. After R's fixes, 13 of 16 natural binaries anchor; the three still rejected name their metric in words the matcher cannot recognise, which is what the new ID-in-parentheses rule covers. All 8 phrasings that follow the new naming guidance anchor.
- *Remaining caps:* Q3 and Q5 stay at B+ because no stored series measures NEV share or global semiconductor sales.

**Critique / pre-mortem**
- *Before:* no outside view.
- *After:* pack plus outside view, kept whole under a 9,000-character cap.

**Chat**
- *Before:* English pack in the Chinese report, day-precision periods.
- *After:* Chinese pack, reader periods, publisher path, daily basis, magnitudes.

**World brief**
- *Before:* 0 rows for every question.
- *U3:* 2–3 rows, first clause only.
- *Now:* 2–3 rows covering both clauses of Q1 and Q2; the canonical brief carries 4–6 rows.
- *Caps:* Chinese worlds still get an English snapshot body (H's renderer).

Done:
- Checked U3 leftovers: elision-helper test, world-brief header test and downstream canonical test already present and green (580/580 in owned files at start)
- Built real per-question rendering (final/R/render_prompts.py) of outline, indicator section, spine, critique, premortem, binary extraction, chat, world brief and canonical brief for the six questions from the live 2026-10-13 carriers, plus a probe of natural core binaries (probe_anchor.py) and stage-by-stage matcher debugging
- forecast_extractor.py: _ANCHOR_UNIT_SCALE_RE and _anchor_comparisons/_anchor_unit_ok handle scale words without 'of' ('Million kilowatt-hours'); an amount written without its scale word on scaled units ('$70,000,000', '160,000 kilowatt-hours') is rejected
- forecast_extractor.py: an annual year at sentence end ('in 2027.') is a period ((?!\d|\.\d|%)); 'Data360' digits ignored in the source suffix and statement remainder; _anchor_row_geography (stored -> catalog -> single title geography)
- forecast_extractor.py: anchor labels accept acronym+2-CJK keywords ('gdp增速') and 增长率<->增速 variants
- forecast_extractor.py: binary prompt now states how to name the metric (listed title / short form / plain name + canonical ID in parentheses)
- forecast_extractor.py: outside view names its window (EN '16-month change to the horizon 2027-12 (n=101)' / '12-month change (a standard window, not the horizon; n=105)'; ZH equivalents); new _official_index_text
- forecast_extractor.py: new public official_question_mention(question, row) -> (clause, position)
- report_agent.py: _OFFICIAL_UNIT_SCALE_RE accepts 'Million kilowatt-hours' (RPT-1 claim check of EIA units); a year at sentence end is a claim period
- report_agent.py: agents' data pack gives values stored in thousands/millions their magnitude (rescale=True); published displays unchanged
- report_agent.py: section outside-view block carries an EN/ZH note on quoting computed base rates (this report's calculation, no [S#])
- simulation_config_generator.py: _official_data_for_question orders snapshot rows by question clause (round-robin), used by the world brief and the canonical brief
- Tests in backend/tests/test_official_data_agent_usage.py: magnitude companion, outside-view window, naming rule, 16 core-binary anchor cases, year-at-sentence-end, 7 claim-check cases, world-brief clause coverage, snapshot ordering; U3 tests updated for the new wording and the section note; test_forecast_extractor_official.py outside-view assertion updated
- Red-before: 38/78 cases fail against the reconstructed pre-R modules (final/R/preR, verified to render byte-identically to the start state); the 40 that pass are guard cases and earlier U3 tests
- Absent-data identity: 54/54 prompts byte-identical to pre-U3 and to HEAD owned modules
- Live check on three real series (EIA, FRED ECBDFR, WDI China)
Not done:
- zh-world-brief-snapshot-body: In Chinese worlds the official snapshot body stays English (row labels, 'Indicator | Value ...' header, '(status inferred; ...)'). It is rendered by official_data.historical_snapshot (H's file), which has no language parameter; I only own the Chinese framing header above it.
- live-llm-validation: No paid LLM calls are allowed, so the effect of the new prompt rules (naming rule, section quoting note) on real model output is untested. Their deterministic side (matcher, claim checker, rendered prompts) is tested.
- published-magnitude-companion: Kept out deliberately. The '≈ 58.52 billion' companion appears only in the agents' pack, because published displays are mirrored exactly by frontend/src/utils/officialData.js (G3, not my file). Turning it on for published tables needs _official_value_display(rescale=True) and formatOfficialDisplay changed together.
tests_run:
All commands ran from backend/ with .venv/bin/python -m pytest -q -p no:cacheprovider; runner and JUnit outputs are in scratchpad/final/R/.
- **Start state** (10 owned files): 580 passed (t_owned0.txt).
- **Final owned set** (12 files: test_official_data_agent_usage, test_official_data_downstream, test_report_official_data, test_report_official_publication_real incl. the EN and ZH real-bundle publication tests, test_forecast_extractor, test_forecast_extractor_official, test_report_visualizer, test_report_visualizer_axes, test_report_visualizer_official, test_canonical_world_brief_denials, test_report_data_publication, test_exec_brief): 643 passed, 0 failed (t_owned_final.txt).
- **Wide run**: all 80 test files that reference report_agent, forecast_extractor, exec_brief, actor_context, simulation_config_generator or report_visualizer, excluding test_export_demo_site_data. 1,965 passed, 12 skipped, 0 failed (t_wide1.txt).
- **Red check**: plugin final/R/r_swap.py loads the reconstructed pre-R modules (final/R/preR). 38 of 78 cases fail, all on new behaviours; the passing ones are guards and earlier U3 tests (t_red2.txt).
- **ruff** (`--select F,E9 --ignore F401,F841,F541`) on the three source files and two test files: all checks passed.
- **Prompt identity**: render_prompts.py with official data absent gives 54/54 byte-identical prompts against renders/before (pre-U3) and against HEAD's owned modules (final/R/head, R_ABSENT_ONLY=1).
- The full suite was not run (the lead runs it).
live_checks:
Ran scratchpad/final/R/live/live_check.py through scratchpad/live/with_data_keys.sh, with DATA_SOURCES_CACHE_DIR=scratchpad/final/R/live/cache. It made 3 provider calls in 6.8 s (EIA 1, FRED 1, World Bank 1; no BLS, no IMF, no LLM). Log: final/R/live/run1.log. It fetched usgov:eia/electricity_sales/US.COM (117 observations, 'Million kilowatt-hours'), fred:ECBDFR and wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN.
- **Anchors:** all three were admitted:
  - 'US commercial-sector retail electricity sales are at least 160,000 million kilowatt-hours in July 2030', with an empirical base rate of 0.406;
  - 'The ECB deposit facility rate averages below 2% in December 2026';
  - '2027年中国GDP增速低于4%'.
- **Claim check:** the true claim '150,578.728 million kilowatt-hours in July 2026' is supported, and a 20% wrong one is rejected.
- **Displays:** the published display stays '150578.728'; the agents' pack shows '150578.728 (≈ 150.58 billion kilowatt-hours)'.
- **Outside view:** reads '53-month change to the horizon 2030-12 (n=64)'.

The six question carriers were not refetched; the committed fixture of live 2026-10-13 data was enough.
Open issues:
- H (official_data.historical_snapshot): add a language parameter so Chinese worlds get a Chinese snapshot body. simulation_config_generator already knows `english` and would pass it through.
- Catalog concurrency: deerflow_bridge/data_catalog.py changed twice during this session (01:59 and 02:02; ECBDFR entry, WEO/WDI China keywords). My tests rely on fairly stable keywords: the CPI acronym, 'policy rate'/'federal reserve', 'power price', 'electricity consumption', 'data center electricity' and 'gdp增速'. If role B or CAT removes any of them, the clause-coverage or ordering tests in test_official_data_agent_usage.py need updating. Run it after the catalog role finishes.
- Matcher recall: natural wordings that use neither title words nor catalog names still lose their anchor, e.g. 'year-on-year consumer price inflation' or 'industrial production of semiconductors'. The prompt now tells the model to add the canonical ID in parentheses; catalog keywords (B) could also be widened.
- Empirical base rate for not-seasonally-adjusted monthly series (EIA) pools h-step changes from every starting month, so it mixes seasons, which is a limitation of contract §1.8. Same-month samples would leave fewer than 30, so I left it as is.
- Coverage: DFEDTARU, T10YIE and NASDAQSOX have only 24 stored months (the default window), so they get no base rate. A longer history request for them belongs to the research prefetch (D/C). Q3 (NEV share) and Q5 (global semiconductor sales) have no stored series that measures the headline metric.
- The section quoting note (computed quantiles without [S#]) is untested against a real LLM run. In the next live report, watch how it interacts with the coverage and quantitative-grounding repair.
- backend/tests/fixtures/data_sources/README.md does not index real/agent_usage/ yet. That belongs to role CAT; I added no new fixtures.
- Lead: commit backend/tests/test_official_data_agent_usage.py, backend/tests/test_forecast_extractor_official.py and backend/tests/fixtures/data_sources/real/agent_usage/ (all untracked). Scratch evidence: scratchpad/final/R/ (render_prompts.py, judge_metrics.py/.txt, probe_anchor.py, r_swap.py, preR/, head/, renders/{before,start,final,head}) and the notes file scratchpad/final/R-notes.md.

## final:CAT

Role CAT is finished: all seven task items are done. Owned and related tests pass: 2533 passed, 1 skipped, across the owned files plus 30 related downstream files. The live smoke checks pass for FRED (83/83) and the EIA recipes (21/21).

What changed:
- The fixtures README now indexes real/agent_usage/, so its guard test passes. The guard test now also checks each file inside agent_usage/.
- Publisher names (World Bank, IMF, WTO, OECD, United Nations and their Chinese names, plus WEO/GEP/WDI/WSTS) no longer count as places or concepts; keyword scoring still sees them. The Q6 question that cites the IMF and the World Bank in Chinese now resolves to China only.
- fred:ECBDFR is in the catalog, checked against FRED's live metadata. The euro-area deposit-rate question now ranks it first and strong, with the BIS euro-area rate second. The BIS euro-area entry now says BIS reports the deposit facility rate only from 18 Sep 2024 (main refinancing rate before), matching the live BIS COMPILATION attribute.
- A price question is no longer answered strongly by a sales or consumption series, and the reverse holds too. 'electricity retail price' now strongly matches exactly the four EIA price recipes.
- History and sourcing words ('history', 'according to', the Chinese for 'drawing on', 'constraints', 'buildout') no longer count as concepts. 'fed funds rate history' now matches fred:FEDFUNDS first and strong.
- Phrases joined by 'and' or 'or' inside a clause can now answer that clause, so the Q2 power-price clause gets strong price hits (EIA price US.ALL and BLS CUUR0000SEHF01).
- Strong matches now lead in single-clause queries too, and a world aggregate no longer answers a country question when the catalog has the same statistic for that country.
- data_catalog.GEOGRAPHIES grows from 14 to 54 economies (every required one plus 13 more), with English and Chinese names. The longest alias wins (Hong Kong, Indonesia and 'Taiwan, China' no longer also match China or India). render_data mirrors the table and its parity test passes.
- DataSources.search moves FRED, Data360, BIS/Treasury-discovered and weak catalog results that share no concept with the query to the end, with the note 'Not matching: its title shares no concept with the query'. Arms exports and mobile subscriptions now come last for 'global semiconductor sales', and energy shares for the NEV query.
- SKILL.md (7,772 bytes, under the 8 KB cap) and the reference files are updated. Every new test fails against the pre-change modules and passes now.

Decisions and where this differs from what you might expect:
- Results that share no concept with the query are marked and moved to the end, not dropped, so a hit with a synonym title is still available.
- I updated four existing assertions:
  - The Chinese 10-year Treasury test: the 10-year TIPS yield, which was already strong, now ranks second.
  - The euro policy-rate test: ECBDFR is also strong now.
  - The battery-storage Data360 test: its world hit is now marked as not matching.
  - The series-label fallback test: FRA is now a named economy, so the unknown-code example uses KEN.
- VERIFIED_ON stays 2026-10-12, and the reference index now says ids added later were verified on the day they were added.
- I made a few keyword additions beyond the brief, which the tests cover: real-GDP Chinese keywords for the WEO, GEP and WDI growth series, removal of the WDI keyword 'historical growth', 'global gdp growth' for the IMF world GDP series, and 'federal funds target range' for the BIS US rate. I also added energy topic phrases such as 'electricity consumption', so electricity questions no longer pull in consumer-spending series.

Done:
- (1) The fixtures README indexes agent_usage/carriers-2026-10-13.json and the new search_relevance_2026-10-14.json capture. The guard test now also checks agent_usage/*.json. It fails against the old README and passes now.
- (2) Publisher and organisation names are removed before geography, topic and concept parsing; keywords and bigrams still see the original text. Q6 with the IMF/World Bank clause resolves to {CHN} and stays one clause. Chinese sourcing words such as 'drawing on' and 'according to' are framing words.
- (3) fred:ECBDFR: ECB Deposit Facility Rate for Euro Area, Percent, daily, NSA, EMU, end-of-period aggregation, priority series, keywords include the Chinese term for deposit facility rate. Checked live: FRED metadata, smoke run, and DataSources.get gives 2026-09 = 2.5, where FRED's monthly average was 2.375. The BIS euro-area entry has the 18 Sep 2024 note and the Chinese deposit-rate keyword. The deposit-rate question ranks ECBDFR then BIS euro-area, both strong.
- (4) A price/quantity mismatch blocks a strong match. 'electricity retail price' is strong only for the four EIA price recipes; 'fed funds rate history' gives FEDFUNDS first and strong; the Q2 power-price clause has strong EIA price US.ALL and BLS CUUR0000SEHF01 hits via phrase splitting. A phrase match never lowers a clause's score.
- (5) GEOGRAPHIES grows from 14 to 54 codes, including every required one (VNM, IDN, MEX, BRA, TUR, SAU, ZAF, KOR, AUS, CAN, RUS, ARG, THA, MYS, PHL, PAK, BGD, EGY, NGA, POL, NLD, ESP, ITA, FRA, CHE, SWE, SGP, TWN, HKG). Each has English and Chinese names; the longest alias wins, and each English name reads back as its own code. render_data._GEOGRAPHIES mirrors it and the parity test passes. Checked live: labels for Data360 VNM, TWN, HKG and TUR rows now name the economy.
- (6) New catalog.concept_terms and shares_concept work through the Chinese-to-English glossary, treat measure words as generic, and treat qualifying words of compound topic terms ('energy' in 'new energy vehicle') as modifiers. DataSources.search lists non-matching FRED, Data360, discovery and weak catalog results last with OFF_CONCEPT_NOTE. Replay tests use real captured payloads, including the arms-exports case.
- (7) SKILL.md adds guidance on publishers vs places, naming the measure, 'Not matching' results, and the BIS euro-area rate before and after Sep 2024 vs fred:ECBDFR (7,772 bytes, under 8,000). The reference files are regenerated and the sync test passes.
- Search and digest tests cover the six audit questions; extra tests cover geographies, publishers, ECB, price vs quantity, framing, phrases, world aggregates, concept judging and the Chinese glossary.
- Live smoke runs: FRED 83/83, EIA 21/21, and the 9 ids whose keywords or notes changed 9/9.
tests_run:
All runs used: cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider.

Baseline before my edits (10 owned test files): only test_fixture_readme_indexes_every_real_capture failed.

After the edits:
- Owned plus 30 related files (data_catalog, data_sources*, data_visuals*, data_mcp*, forecast_extractor(_official), legacy_official_data, official_data_*, official_data_agent_usage, report_official*, report_visualizer_official, research_engine_v3*, research_gateway(_official_data), resolution_monitor, settings_data_sources_probe, v3_official_data, orchestrator_research_wiring, canonical_world_brief_denials, exec_brief): 2533 passed, 1 skipped, exit 0. Log: scratchpad/final/CAT/related_run3.txt.
- After two last test-only edits, the four main owned test files: 270 passed.

Check against the pre-change code: a pytest plugin (scratchpad/final/CAT/redplugin/before_cat.py) loads the pre-change data_catalog and data_sources under both import names. Against it, 36 new or updated tests fail (red_before.txt). The README guard fails against the old README.

An earlier related run had 5 failures in test_official_data_agent_usage and test_forecast_extractor_official. Another session was editing forecast_extractor.py and that test file at the time (02:06–02:08). With the pre-change modules the forecast_extractor failure still occurred and the 4 agent_usage failures did not reproduce; with my modules the agent_usage tests pass on rerun. All of these pass in the final run.

ruff (uvx ruff check --select F,E9 --ignore F401,F841,F541) on data_catalog.py, data_sources.py, render_data.py and the 3 changed test files: all checks passed. Every line I added is at most 120 characters.
live_checks:
All live calls went through scratchpad/live/with_data_keys.sh, with cache directories under scratchpad/final/CAT/. No key values were printed or saved, no BLS calls were made, there was 1 IMF call, and no paid LLM calls.

1. FRED metadata for ECBDFR and ECBMRRFR (live_meta.py): ECBDFR is 'ECB Deposit Facility Rate for Euro Area', Percent, 'Daily, 7-Day', not seasonally adjusted.
2. Recorded DataSources.search for 9 agent-style queries: 9 fred_search, 9 data360_search_indicators, 9 BIS search_dataflows and 9 Treasury searches, saved to live_search.json. Data360 returned 'Arms exports', 'Top 500 supercomputers', 'High-technology exports' and 'Mobile cellular subscriptions' for 'global semiconductor sales'. FRED returned other average prices (beef, eggs, gasoline) for 'US electricity retail price'. A trimmed copy is the fixture real/providers/search_relevance_2026-10-14.json.
3. live_verify.py through DataSources:
   - fred:ECBDFR: end-of-period, latest observed 2026-09 = 2.5, latest daily 2026-10-13 = 2.5.
   - bis:WS_CBPOL/M.XM: the new note is attached; latest 2026-09 = 2.5.
   - Labels: wb:IMF_WEO_NGDP_RPCH VNM, TWN and HKG read '… — Vietnam / Taiwan, China / Hong Kong SAR, China' (Chinese 越南 / 中国台湾 / 中国香港); wb WDI GDP growth for TUR reads '— Türkiye'.
   - Searches: 'US power price' lists BLS CUUR0000SEHF01 and EIA price US.ALL first. The Chinese NEV-share query lists fred:TOTALSA first and the rest marked 'Not matching'. 'euro area deposit facility rate' lists ECBDFR and BIS euro-area first, then Data360, EER and Treasury FX results marked 'Not matching'.
4. backend/scripts/datamcp_smoke.py:
   - --providers fred: 83 requested, 83 ok (126 s); fred:ECBDFR n=25, latest 2026-09 = 2.5 Percent.
   - --series with all 21 usgov:eia ids: 21/21 ok (37 s).
   - --series with the 9 ids whose keywords or notes changed (bis M.US and M.XM, wb GEP CHN, wb WDI growth CHN/USA/IND/WLD, wb WEO CHN, imf WEO G001.NGDP_RPCH.A): 9/9 ok (63 s).

Reports and logs are in scratchpad/final/CAT/smoke/.
Open issues:
- Ranking change for v3 and legacy (no code change needed there): the catalog now puts strong matches first in single-clause queries and splits phrases joined by 'and'/'or'. Pre-passes and seeds will now also pick: fred:ECBDFR for the ECB question, a power-price series for Q2, and no world WDI aggregate for China GDP questions. A KIQ like 'US CPI and core inflation' now has more strong hits, ranked by the clause's best score. test_v3_official_data and test_legacy_official_data pass as they stand.
- Moving off-concept results to the end is a word-overlap rule. A hit whose title uses only a synonym (for example 'jobless rate' against 'Unemployment, total') is marked 'Not matching' and listed last, but still returned and fetchable.
- Display names chosen for the new economies: 'Taiwan, China' / 中国台湾 and 'Hong Kong SAR, China' / 中国香港 (World Bank style), and 'Türkiye'. Change them in data_catalog.GEOGRAPHIES together with the render_data mirror if you want different names; the parity test enforces that both match.
- For the lead's docs pass: SKILL.md now covers publishers vs places and 'Not matching' results, and the reference index now says ids added later were verified on the day they were added. design.md and the integration contract do not mention concept_terms, shares_concept or OFF_CONCEPT_NOTE yet.
- Please stage the untracked fixture backend/tests/fixtures/data_sources/real/providers/search_relevance_2026-10-14.json together with test_data_sources_providers.py.
- Notes: scratchpad/final/CAT-notes.md; evidence and scripts: scratchpad/final/CAT/ (probe.py, live_search.py and .json, live_verify.py and .json, smoke/, red_before.txt, related_run3.txt, baseline/). The scratchpad can be wiped; this result holds the summary.
## Round 6 — final adversarial review+fix `wf_2ffd3b93-7e7` (2026-10-14)

Six area reviewer-fixers, each followed by an independent verifier. Five reviewers finished (data, v3, legacy, report, frontend). The downstream reviewer and all five verifiers died on an API 403 at about 04:13 +08:00. Some of them had already edited files: downstream in `official_data.py`, `simulation_config_generator.py`, `settings.py`, `doctor.sh` and tests; verify:report added `_empirical_seasonal_share`; verify:frontend added the seasonal-basis display. Round 7 re-runs the missing pieces.

### review:frontend

I reviewed the frontend part of the official-data integration: every new or changed file under frontend/src and frontend/tests. I found and fixed four real defects. Each was reproduced first with a failing test or probe, and each fix came with a regression test.

1. **Base-rate flag wrong at exactly 25pp.** In the data-anchor column, a model probability exactly 25 points below its base rate was highlighted as "over 25pp, flagged by the quality check", but the backend does not flag it. Example: probability 0.3 vs base rate 0.55, which computes as -0.25000000000000006.
2. **Wrong year labels for fiscal-year data.** The research dossier showed fiscal-year spending data (usgov:spending/total) as "2022 – 2026" when it covers FY2023–FY2027. The report itself already uses the FY labels.
3. **Indicator tile arrow contradicted its own text.** When two equal monthly values differ only by float noise, the tile showed "▲ YoY 0 pp".
4. **Screen readers could miss the data-source test result.** The Settings result area was only created at the moment the result appeared, so screen readers might not announce it.

Results:
- **Regression check:** With no official data, the report and forecast table render exactly as they do at HEAD, in English and Chinese, whether the endpoint returns available:false or 404.
- **Backend response shapes:** All four match what the frontend reads: the report official-data endpoint, the Settings data-source test, the research file endpoints and the forecast data anchors.
- **Timeout:** The data-source test call waits 120 s; the backend worst case is about 82 s.
- **Interface coverage:** Every new label has Chinese and English text, and the error, empty and loading states all handle failure without breaking the page.
- **Security:** I found no unsafe links or raw HTML, and the committed test data contains no API keys.

The build output went to the scratchpad only; frontend/dist was not touched. I did not stage or commit anything and made no paid LLM calls.

Open items I left unchanged (details in the notes file):
- The backend forecast code labels a fiscal-year forecast period as "2025" instead of "FY2026". The data-anchor column copies those backend labels, so the fix belongs in the backend file that formats the anchor period (the forecast extractor), not in the frontend.
- The existing market-check message in Settings has the same screen-reader issue as #4; that code predates this change.
- The CSV buttons all have the same accessible name, "CSV".
- The download helper releases the file link on the next tick, the same as the existing report download.
- Numbers of 1e21 or more format differently from the Python backend.
- Fork pipelines have no Official Data tab in the dossier.

Full notes: /private/tmp/claude-501/-Users-rogerlin-Downloads-DeepResearchForecast/52225542-51e1-41e1-b738-38d44834da7e/scratchpad/review2/frontend-notes.md

- **FE-1** (medium, fixed): Base-rate divergence flag disagrees with the backend quality check at the 25pp boundary. Location: frontend/src/utils/binaryForecasts.js baseRateModel (gap = model - p). Fix: Added a new exported helper, officialData.roundHalfEven(value, digits), which matches Python's round() using the existing exact half-to-even code. The gap is now roundHalfEven(model - p, 4). Tests: binaryForecasts.test.mjs 'base-rate divergence is flagged exactly like binary_quality at the 25pp boundary' (failed before the fix) and officialData.test.mjs 'roundHalfEven mirrors Python round() on the exact binary value' (expected values printed by CPython).
- **FE-2** (medium, fixed): Research dossier labels US federal fiscal-year series by the calendar year of the fiscal-year start (off by one). Location: frontend/src/utils/officialData.js officialPeriodLabel / datasetManifestRows. Fix: officialPeriodLabel(date, frequency, provenance) now uses the provenance.periods fiscal label (own-property lookup), exactly like the backend. datasetManifestRows passes row.provenance when building the latest period and coverage. New real fixture: tests/fixtures/official/datasets_manifest.usaspending_fy.json (data-layer output, documented in the fixtures README). Test 'fiscal-year datasets read FY labels like the report' (failed before the fix).
- **FE-3** (low, fixed): Official indicator tile shows an up/down arrow next to a '0 pp' change caused by float noise. Location: frontend/src/utils/officialData.js officialIndicatorTile changeDirection. Fix: The direction now comes from the displayed, rounded and signed change text: '+' means up, '-' means down, anything else is flat. This is the same rule formatDivergence already uses. Test 'the change arrow follows the displayed change, never float noise' (failed before the fix: expected flat, got up).
- **FE-4** (low, fixed): Data-source probe summary is not reliably announced to screen readers. Location: frontend/src/components/research/SettingsMenu.vue (probe summary span). Fix: The polite live region is now always rendered; only its text and colour class change. Test settingsDataSources.test.mjs 'the probe summary lives in a polite live region that exists before the result arrives' (failed before the fix).
- **FE-N1** (low, not_fixed): Data-anchor period for a fiscal-year series reads '2025' instead of 'FY2026'. Location: frontend/src/utils/binaryForecasts.js dataAnchorModel (mirrors backend forecast_extractor._official_period_text). Fix: Left as is so it stays consistent with forecast.json and the backend tables. The fix belongs in the backend forecast extractor's period formatting (_official_period_text, slice G2); the frontend would then follow.

Files changed: frontend/src/utils/officialData.js, frontend/src/utils/binaryForecasts.js, frontend/src/components/research/SettingsMenu.vue, frontend/tests/officialData.test.mjs, frontend/tests/binaryForecasts.test.mjs, frontend/tests/settingsDataSources.test.mjs, frontend/tests/fixtures/official/datasets_manifest.usaspending_fy.json, frontend/tests/fixtures/official/README.md

Tests run: - `npm --prefix frontend run test:unit`: baseline 124/124; after the fixes 129/129 pass, 0 fail, 0 Vue warnings. The 5 new tests are the boundary flag, roundHalfEven, fiscal labels, change arrow and live region; 4 of them failed before their fixes (roundHalfEven is a new helper with no before state). Output: scratchpad/review2/frontend/unit_final.txt.
- `npm --prefix frontend run build -- --outDir <scratchpad>/review2/frontend/fe-dist-final --emptyOutDir`: exit 0, no warnings; frontend/dist was not touched.
- Parity check (scratchpad/review2/frontend/parity_absent.mjs): HEAD vs working-tree ForecastReport and BinaryForecastTable markup is byte-identical with comments stripped, in English and Chinese, for both available:false and 404 from the official-data endpoint (4 renders, 0 warnings).
- Backend probes, read-only through backend/.venv:
  - `_binary_quality` boundary flags;
  - `official_period_label` on the replayed USAspending manifest;
  - `official_indicator_summary` on a float-noise row;
  - re-deriving the fixture indicators with the current backend (identical for UNRATE and WEO; the debt series differs only because the fixture data was trimmed).
- ruff not needed: no repository Python file changed.

### review:v3

I reviewed the uncommitted v3 changes and both assigned open items. I fixed two defects, each with a regression test that fails before the fix and passes after it. I also corrected two docstrings.

1. **Window note (open item 1, fixed).** `research_gateway._window_note` now uses the legacy `cut_short` end rule. Before, a series stored with its default window (which runs up to the retrieval date) still got "NOTE … was not refetched" on `data_get(id, end="2027")`; now that call returns the stored page unchanged. Applying the legacy rule exactly would have created a new false negative in v3, because v3 prefetches IMF WEO / World Bank GEP projection paths only up to the forecast horizon. The real v3 row `wb:IMF_WEO_PCPIPCH/USA` (stored through 2027, retrieved 2026-10-12; the publisher path runs to 2031) would have lost its note for `end=2031`. So the end side is also noted when the last stored point is after the retrieval date. The legacy `data_tools._window_note` (not my file) has the same false negative in one rare case: an agent first stores a WEO/GEP path with an explicit future end, then asks for a later end.

2. **ECB fallback seed (open item 2, not a defect).** With fallback seeding and no planner `data_needs`, "Will the ECB cut its deposit rate below 2% by mid-2027?" already seeds `{'fred:ECBDFR': ['K1']}`, because the catalog now has ECBDFR. I pinned this in an existing test. Side note for the catalog owner: phrased as "European Central Bank deposit facility rate…", the question ranks `bis:WS_CBPOL/M.XM` as strong and ECBDFR as not strong, so it seeds the BIS series instead. BIS reports the main refinancing rate before 18 Sep 2024.

3. **Resume with providers down (new finding, fixed; this was a regression).** At HEAD, every resumed attempt kept the series an earlier attempt had stored. The working tree reconfigures providers on a resume that is not pinned. If they are unavailable then (`sources.enabled()` is False or `get_data_sources` raises), `data_enabled` became False even though series were stored and seeded. Unfinished KIQs then lost their "OFFICIAL DATA ALREADY RETRIEVED" seeds and the data tools. The new `_Engine._keep_stored_data()` handles this: when the earlier attempt recorded data as enabled or stored rows exist, it freezes the tools, sets `data_enabled=True` and status `stored_only`. Without stored evidence, the run stays unavailable.

Nothing changes when official data is disabled: the fixes only touch data-enabled resumes and data_get notes. Prompt-cache layout and secret handling are unchanged. ruff is clean. 1624 tests passed and 1 was skipped across 24 related test files; I did not run the full suite.

- **V3-WIN-1** (low, fixed): v3 data_get with a forecast-horizon end gets a false 'not refetched' note for a series stored with its default window. Location: deerflow_bridge/research_gateway.py:_window_note. Fix: The end side is noted only when the stored window was cut short: held_end < retrieval date (the legacy data_tools rule), or the last stored point is after the retrieval date (a projection path stored to the horizon), or retrieved_at is unreadable. Tests: test_research_gateway_official_data.py::test_a_forecast_horizon_end_is_no_window_gap_unless_the_stored_window_was_cut_short and ::test_a_projection_path_stored_to_the_horizon_notes_a_later_end (uses the real v3_engine/series-2026-10-12.json WEO row).
- **V3-SEED-ECB** (info, not_a_defect): Fallback seeding for the ECB deposit-rate question. Location: deerflow_bridge/linear_research.py:_catalog_seeds. Fix: Already correct with the catalog's fred:ECBDFR; pinned in test_v3_official_data.py::test_plan_without_data_needs_seeds_strong_catalog_series. Catalog-owned observation: the wording 'European Central Bank deposit facility rate' marks bis:WS_CBPOL/M.XM strong and ECBDFR not strong.
- **V3-RESUME-1** (medium, fixed): A resumed v3 attempt with providers unavailable drops the official data an earlier attempt stored (regression vs HEAD). Location: deerflow_bridge/linear_research.py:_Engine._configure_data. Fix: New _Engine._keep_stored_data(). It runs after configuration when the attempt is resumed, data_enabled is False and the status is 'unavailable'. If the saved index was enabled or stored rows exist, it calls freeze_data(), sets data_enabled=True and status 'stored_only'. Without stored evidence the run stays unavailable. Test: test_v3_official_data.py::test_a_resume_whose_providers_are_unavailable_keeps_the_stored_series[no_provider, factory_error]; both params failed before the fix.
- **V3-DOC-1** (low, fixed): Misleading docstrings. Location: deerflow_bridge/research_gateway.py:ResearchTools.prefetch_data; deerflow_bridge/linear_research.py:_Engine._configure_data. Fix: Docstring wording only.
- **V3-OBS-1** (info, not_a_defect): Provider series titles appear without untrusted-text delimiters in the KIQ 'Other official series' list and the writer pointers. Location: deerflow_bridge/linear_research.py:_kiq_data_text, _section_data_lines. Fix: Not changed. The text is official metadata at the same trust level as before; delimiting it would only change data-enabled prompt wording.

Files changed: /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/research_gateway.py, /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/linear_research.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_research_gateway_official_data.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_v3_official_data.py

Tests run: All runs used `cd backend && .venv/bin/python -m pytest -p no:cacheprovider` (bare-name bridge imports).
- Baseline: the 11 owned files (test_v3_official_data, test_research_engine_v3*, test_research_gateway, test_research_gateway_official_data) exited 0 (review2/v3/baseline.txt).
- run1, after the window and resume fixes, 22 files (owned plus test_bridge_overhaul_v3, test_bridge_extensions_config, test_data_catalog, test_data_mcp, test_deerflow_bridge_sync_guard, test_official_data_consumers, test_official_data_end_to_end, test_orchestrator_research_wiring, test_live_research_progress, test_research_fork_handoff, test_loop010_global_synthesis): 1432 passed, 1 skipped.
- run2, final code, the same set plus test_official_data_agent_usage and test_official_data_downstream: 1624 passed, 1 skipped, exit 0 (review2/v3/run2.txt).
- Red checks:
  - The forecast-horizon test fails against a copy of the gateway with the fix reverted (review2/v3/red/research_gateway_pre.py, loaded with sys.modules).
  - The projection-path test fails against the plain legacy rule and passes against the pre-review code.
  - The resume test failed for both params before `_keep_stored_data`.
- `uvx ruff check --select F,E9 --ignore F401,F841,F541` on research_gateway.py, linear_research.py, research_progress.py and both changed test files: all checks passed.
- No live provider or paid LLM calls; probes used real captured fixtures.
- Notes: /private/tmp/claude-501/-Users-rogerlin-Downloads-DeepResearchForecast/52225542-51e1-41e1-b738-38d44834da7e/scratchpad/review2/v3-notes.md; probes and logs in scratchpad/review2/v3/.
- I did not run the full suite.

### review:data

Data area final gate: all three assigned open items are handled, and one more defect was found in data_mcp.py and fixed. Each fix was reproduced first with a test that failed on the old code and passes now, and checked live. Afterwards, the owned test files plus 21 downstream test files gave 2061 passed, 1 skipped.

(1) BEA value added by industry: added min_start 2005-01-01 to the usgov:bea/value_added_by_industry recipe in deerflow_bridge/data_catalog.py; the catalog entries inherit it. A request starting in 2004 is now moved to 2005 and makes one BEA call. A window that ends before 2005 is refused as invalid_window, naming 2005-01-01, without any call. Before, it ended in provider_error 'Invalid year: 2004'.

(2) bis:WS_CBPOL/M.XM: the note was already present and tested. The catalog note, the SKILL.md table row and catalog-bis.md all say BIS reports the ECB deposit facility rate from 18 Sep 2024 and the main refinancing rate before. test_data_catalog.py checks it against the live COMPILATION capture.

(3) FRED daily series now default to ten years instead of about 24 months. This applies only when no start is given. The last 24 months are still fetched as native days, with the same request as before. Older months come from FRED's own monthly aggregation (average, or end of period for policy targets). The change is in DataSources._request and DataSources._fred_split in deerflow_bridge/data_sources.py, using a new req["default_window"] flag. Pages stay bounded: one daily page of about 528 rows plus one monthly page of 96 rows. Explicit windows are unchanged. Treasury daily series (debt_to_penny, debt_held_public) keep two years, because Treasury cannot aggregate server-side. SKILL.md gains one sentence on the new default.

(4) Additional defect: McpHub._call in deerflow_bridge/data_mcp.py took a FRED rate slot before checking whether the call would be refused. Refused calls (hub closed, server not built, circuit open) therefore used up slots. With a long deadline they could also wait up to 60 s for a free slot, only to be refused. They then reported a misleading 'local rate limit' error. The rate check now runs after that check.

Live check (paced, no keys printed, cache in scratchpad review2/data/live_cache; 8 FRED calls, 1 usgov, no BLS/IMF/LLM):
- DFEDTARU, T10YIE and NASDAQSOX each return 121 months (2016-10 to 2026-10): 120 observed plus the open month as partial.
- BAMLH0A0HYM2, which FRED keeps for only about 3 years, degrades cleanly to 37 months.
- BEA industry 334 with start 2004 made one call, for 2005.

Not changed, recorded in the notes file:
- Catalog clause splitting slows down sharply on very long whitespace runs: about 1.2 s for 10k spaces. Agent queries are capped, so only a pathological research question would hit it.
- A FRED server that is not built, with a key set, still shows the hub error in providers(), the same as HEAD, even though the CSV fallback works.
- Treasury daily series still have only two years, so they still get no empirical base rate.
- An earlier related run showed 61 failures from a NameError (_SNAPSHOT_TITLE) in backend/app/services/official_data.py, which another session was editing at the time. On rerun all 241 tests in those 4 files passed.

Full notes: /private/tmp/claude-501/-Users-rogerlin-Downloads-DeepResearchForecast/52225542-51e1-41e1-b738-38d44834da7e/scratchpad/review2/data-notes.md

- **DATA-1** (medium, fixed): BEA quarterly GDP-by-industry window not clamped to its first year (2005). Location: deerflow_bridge/data_catalog.py USGOV_RECIPES['bea/value_added_by_industry']. Fix: The recipe now has min_start='2005-01-01', and its catalog entries inherit it through _usgov(). The request window is clamped by the existing _min_start logic. A window that ends before 2005 gives invalid_window naming 2005-01-01, with no provider call. Live: one BEA call (2005), requested_start 2005-01-01.
- **DATA-2** (low, not_a_defect): bis:WS_CBPOL/M.XM note on the deposit facility rate from 18 Sep 2024. Location: deerflow_bridge/data_catalog.py _CBPOL_NOTES['XM']; skills/data-sources/SKILL.md; references/catalog-bis.md. Fix: Already in place (role CAT); no change needed.
- **DATA-3** (medium, fixed): FRED daily catalog series store only ~24 months under the default window, so they get no empirical base rate. Location: deerflow_bridge/data_sources.py DataSources._request (default years) and DataSources._fred_split. Fix: FRED daily series now get the ten-year default that monthly series have; non-FRED daily (Treasury) keep two years. req['default_window'] = start is None. _fred_split cuts a defaulted daily window at the latest 24 months even when it would fit one page. The daily request is therefore the same as the old default, and older months come from FRED's own monthly aggregation (API frequency=m or CSV fq=Monthly, catalog avg/eop). Explicit windows are unchanged. SKILL.md has one sentence on this. Live: DFEDTARU (eop), T10YIE and NASDAQSOX each return 121 months (120 observed plus 1 partial); ICE BAMLH0A0HYM2 degrades to 37 months.
- **DATA-4** (low, fixed): FRED rate-limit slot taken before the hub checks whether to refuse the call. Location: deerflow_bridge/data_mcp.py McpHub._call. Fix: The rate check (_RateWindow.admit) now runs after _admit()'s refusal check, so refused calls neither use a slot nor wait for one. The existing pacing tests still pass.
- **DATA-5** (low, not_fixed): Catalog clause/conjunct splitting is quadratic on long whitespace runs. Location: deerflow_bridge/data_catalog.py _CONJUNCT_RE/_CLAUSE_RE in _conjuncts/_query_parts. Fix: Not changed. Agent queries are capped at 300/600 chars, so only a pathological research question would hit it. A fix that keeps _CLAUSE_RE's exact behaviour is not trivial; recorded for the lead.

Files changed: deerflow_bridge/data_sources.py, deerflow_bridge/data_catalog.py, deerflow_bridge/data_mcp.py, deerflow_bridge/skills/data-sources/SKILL.md, backend/tests/test_data_sources_providers.py, backend/tests/test_data_mcp_pacing.py

Tests run: All runs from backend with .venv/bin/python -m pytest -p no:cacheprovider (pyproject addopts already adds -q).
- Red-before: the 6 new tests failed on the pre-fix code:
  - BEA clamp: DataError provider_error 'Invalid year: 2004'.
  - Both default-window parametrizations: the daily request did not match the expected one.
  - Default windows by provider: start 2024-10-01 instead of 2016-10-01.
  - Refused-call pacing: 2nd error was 'local rate limit ...'.
- The 10 owned files after the data_sources/data_catalog fixes: 575 passed (scratchpad review2/data/own_run1.txt). These are test_data_sources, _config, _interfaces, _normalization, _providers, _smoke, test_data_mcp, _deadline, _pacing and test_data_catalog.
- Owned files plus 21 related downstream files after all fixes: 2061 passed, 1 skipped, rc 0 (review2/data/final_run.txt). The related files are canonical_world_brief_denials, data_visuals_official/render/status, exec_brief, forecast_extractor_official, legacy_official_data, official_data_agent_usage/consumers/downstream/end_to_end/promotion, orchestrator_research_wiring, report_official_data, report_official_publication_real, report_visualizer_official, research_gateway, research_gateway_official_data, resolution_monitor, settings_data_sources_probe and v3_official_data.
- An earlier related run showed 61 failures from a NameError (_SNAPSHOT_TITLE) in official_data.py, which another session was editing at the time. Rerunning those 4 files gave 241 passed.
- After the last cosmetic edits (shorter SKILL.md sentence, restored blank line in data_mcp):
  - test_data_catalog, test_data_mcp_pacing and the legacy skill test: 95 passed.
  - test_legacy_official_data and test_data_mcp: 117 passed.
  - test_data_sources_providers: 51 passed.
- ruff check --select F,E9 --ignore F401,F841,F541 passed on all touched and owned files; py_compile was clean.
- Live checks through scratchpad/live/with_data_keys.sh (cache review2/data/live_cache; no keys printed; 8 FRED calls, 1 usgov, 0 BLS, 0 IMF, no LLM). Log: review2/data/live_check.log, 'EXIT=0'.
- A scan of the fixtures, the skill directory and the owned modules and tests found none of the 4 configured provider keys.

### review:report

Final quality gate for the report area of the uncommitted official-data work. I handled both assigned open items and fixed two further real defects plus one test that a concurrent change broke. Every fix was reproduced first, either by a probe or by a test that fails when the old behaviour is restored, and each has a regression test.

1) Seasonal base rate for monthly series that are not seasonally adjusted (NSA). The bias is real and large. On the live EIA commercial electricity sales row (NSA, 117 months to 2026-07), the 5-month change from July to December has a median of -21,842 million kWh over the 9 July starts, but +63 when all 112 start months are pooled.
- Fix in forecast_extractor.py: a new helper, _empirical_season, applies only to monthly NSA series whose step count is not a multiple of 12 and that are not year-over-year transforms. It uses only starts in the same calendar month when they give at least 30 samples (the binding floor in contract §1.8). Otherwise it pools all start months and records seasonal_basis='all_start_months'.
- The seasonal basis is shown everywhere the rate appears: the base rate itself, the fan, metric ranges, the outside view (short form 'seasons pooled', so Q2's 8 series still fit in 3600 characters), the Part 1 table cell, the watch table, the exec-brief watch line, and the chart threshold, band and fan legend labels (both Plotly and matplotlib).
- A pooled-season rate no longer raises the 25 pp divergence flag.
- Output is byte-identical for seasonally adjusted or unknown series, for yoy transforms and for steps that are multiples of 12.
- Honest limit: carrier rows keep at most 240 observations, so a monthly series has at most 20 same-month starts. With the floor at 30, current stored runs always take the disclosed fallback. The docstring says so. A rendered chart (scratchpad review2/report/detail_test.png) shows that the pooled fan is still seasonally flat, so this needs an owner decision.

2) Anchor-matcher recall.
- New _anchor_keyword_windows: every word of a multi-word catalog keyword must appear, singular or plural and in any order, in one run joined only by 'of'/'the' and the series' own title words. Negation and conjunction words, number words and place names may never sit inside the run.
- 'cpi' also matches 'consumer prices' and 'ppi' matches 'producer prices', following the catalog's own pairing on 15 of 19 CPI entries.
- Overlapping metric spans now merge into one.
- Now anchored: 'year-on-year / annual consumer price inflation' (BIS, and IMF WEO via 'cpi'), 'industrial production of semiconductors', 'semiconductor industrial production', '10-year breakeven inflation expectations'.
- Still rejected: negation, 'and' compounds, deadlines, wrong periods, other places, PPI/PCE wording, 'core'.
- 'industrial production growth' already anchored on INDPRO#yoy through the exact keyword (probe).
- A cross-series probe of 2,040 statements found no new false class; the only new admissions are same-concept (the CPI family, and 'policy rates' as the plural of an existing keyword).

3) New defect (existed before this work): 'US CPI inflation expectations are below 2.5% …' anchored on realized CPI. 'expectations?' and '通胀预期' are now sibling qualifiers, allowed only when the series' own names carry them (MICH, T10YIE, T5YIFR).

4) New defect: exec-brief official values had no units. '58522249' for semiconductor shipments, which is $58.5 billion in Thousands of U.S. Dollars, read as a bare number, as did '150578.728' for EIA sales. The indicator table, the anchored watch line and the digest now show the stored value plus its units and the data layer's magnitude note. Percent series are unchanged.

5) Test drift from a concurrent change: H's official_data.historical_snapshot now renders Chinese labels. That broke two q6 cases of test_world_brief_shares_its_budget_with_the_official_snapshot in my test file. The assertion now uses the brief's language and treats full-width and ASCII parentheses alike.

Notes file: the harness blocks report files in subagents, so this summary is the full account. Scratch probes are in scratchpad/review2/report/: probe_season.py, probe_anchor.py, probe_expect.py, probe_cross.py, probe_indpro.py, probe_brief_units.py, probe_mpl.py, and redplugin/red_before.py.

- **RPT-R2-1** (high, fixed): Empirical base rate, fan and outside view pool every start month for NSA monthly series (mixes seasons). Location: backend/app/services/forecast_extractor.py:_empirical_changes/_empirical_season/_empirical_outlook/official_empirical_fan/official_outside_view_block/_base_rate_cell/_official_watch_row/_binary_quality; report_visualizer.py:_official_threshold_label/_official_band_label/_official_fan_label; exec_brief.py:_anchor_watch_line. Fix: Same-calendar-month starts are used when they give at least EMPIRICAL_MIN_SAMPLES (contract floor of 30); otherwise all start months are pooled with seasonal_basis='all_start_months', disclosed in EN and ZH in every table, brief, prompt and chart label, and excluded from the divergence flag. Output is unchanged for SA or unknown series, yoy transforms and h%12==0. With the 240-observation carrier bound, current runs always take the disclosed fallback. Tests: test_nsa_monthly_base_rate_says_when_it_pools_the_seasons, test_seasonal_basis_is_absent_for_adjusted_or_unknown_series, test_long_nsa_history_uses_same_calendar_month_starts, test_seasonal_basis_is_disclosed_wherever_the_rate_is_shown, test_fan_and_threshold_say_when_they_pool_the_seasons.
- **RPT-R2-2** (medium, fixed): Anchor matcher rejects natural metric wordings (year-on-year consumer price inflation, industrial production of semiconductors). Location: backend/app/services/forecast_extractor.py:_anchor_keyword_windows/_anchor_singular/_ANCHOR_ACRONYM_KEYWORDS/_anchor_metric_spans. Fix: Keyword windows: every word of a multi-word catalog keyword appears, singular or plural and in any order, joined only by of/the and the series' own title words, with no blocker or place word inside. 'cpi' also matches 'consumer prices' and 'ppi' matches 'producer prices'; overlapping spans merge. The 20-case test test_natural_metric_wordings_keep_their_anchor_and_counterexamples_do_not keeps negation, compound, deadline, wrong-period, wrong-place, PPI and core counterexamples rejected. A cross-series probe of 2,040 statements found no new false class.
- **RPT-R2-3** (medium, fixed): Inflation-expectations statements anchored on realized CPI (existed before this work). Location: backend/app/services/forecast_extractor.py:_ANCHOR_QUALIFIER_RE/_anchor_foreign_qualifier. Fix: 'expectations?' and '通胀预期' are now sibling qualifiers, allowed only when the anchored series' own names carry them (plural-tolerant check). Covered by RECALL_CASES in test_official_data_agent_usage.py.
- **RPT-R2-4** (medium, fixed): Executive brief shows official levels without units. Location: backend/app/services/exec_brief.py:_build_indicators_block/_anchor_watch_line/_render_digest (new _official_amount). Fix: Non-percent values now show the published value, its units and the data layer's magnitude note. Percent series are unchanged; cell caps were widened. Test: test_executive_brief_values_carry_their_units (fails when the old behaviour is restored).
- **RPT-R2-5** (low, fixed): World-brief test asserted an English label after H made the Chinese snapshot body Chinese. Location: backend/tests/test_official_data_agent_usage.py:test_world_brief_shares_its_budget_with_the_official_snapshot. Fix: The assertion now uses series_label in the brief's language and treats full-width and ASCII parentheses alike.
- **RPT-R2-6** (medium, not_fixed): Frontend neither shows seasonal_basis nor stops flagging divergence for pooled-season rates. Location: frontend/src/utils/binaryForecasts.js (G3, outside my area). Fix: G3: show the caveat when seasonal_basis is present and skip divergence for 'all_start_months'.
- **RPT-R2-7** (medium, not_fixed): Pooled fallback still draws a seasonally flat fan and base rate for strongly seasonal NSA series. Location: backend/app/services/forecast_extractor.py:_empirical_season (contract §1.8 floor). Fix: Owner decision: lower the floor for same-month samples, request longer stored history, or adopt a seasonal decomposition. Under the binding 30-sample floor, disclosure is the compliant fix.
- **RPT-R2-8** (low, not_fixed): Remaining matcher recall gaps. Location: deerflow_bridge/data_catalog.py (B) / forecast_extractor matcher. Fix: Catalog owner can add the keyword. The title phrase would need a title-continuation span rule; I judged that riskier than the gain for this gate.
- **RPT-R2-9** (low, not_fixed): usgov provider_name names Treasury/USAspending for EIA and BEA rows. Location: deerflow_bridge/data_sources.py (A, outside my area). Fix: Data layer: give a recipe-specific provider_name to EIA/BEA rows.

Files changed: /Users/rogerlin/Downloads/DeepResearchForecast/backend/app/services/forecast_extractor.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/app/services/report_visualizer.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/app/services/exec_brief.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_forecast_extractor_official.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_report_visualizer_official.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_official_data_agent_usage.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_report_official_data.py

Tests run: All runs from backend/ with `.venv/bin/python -m pytest -q -p no:cacheprovider -o addopts=""`.
- Baseline: the 13 owned files (report_official*, report_data_publication, forecast_extractor*, report_visualizer*, report_zh_presentation, official_data_agent_usage, wave9_report_focus, architecture_characterization, exec_brief) exited 0.
- After the fixes, owned set: 591 passed, 11 xfailed.
- Wide set: 78 test files that touch forecast_extractor, report_visualizer, exec_brief, report_agent, simulation_config_generator or official_question_mention, excluding test_export_demo_site_data. 1958 passed, 1 skipped, 11 xfailed, 0 failed (t_wide2.txt). The earlier wide run had 2 q6 world-brief failures caused by H's concurrent change; they were fixed in the test.
- Red-before: plugin scratchpad review2/report/redplugin/red_before.py restores the old behaviour. 12 new tests fail under it: 7 matcher cases, 4 seasonal tests and the exec-brief units test. The guard tests pass under it.
- ruff (`--select F,E9 --ignore F401,F841,F541`) on all 7 changed files: all checks passed.
- compileall on the 3 source files: OK.
- matplotlib detail chart rendered for the EIA seasonal case (detail_test.png).
- No live provider calls and no LLM calls. The full suite was not run.

### review:legacy

I reviewed the legacy area: the uncommitted diffs of data_tools.py, deerflow_research.py, skills/deep-research/** and skills/data-visuals/** (including all of render_data.py), plus the area's tests. config.yaml and runtime_skill_sync.py have no changes, and config.yaml is byte-identical to deer-flow/config.yaml. I found three real defects and reproduced each one before fixing it. I also handled both open items.

**Defects fixed**
- **Chart status for old stored rows (render_data.py `_period_metadata`):** for daily-to-monthly rows stored under policy below 3, the renderer counted a month as complete when it was fully covered and ended before retrieval. The data layer's rule (`data_sources._legacy_month_complete`) also needs the month to be settled: either a later stored period exists, or retrieval came more than 7 days after month end. A probe showed the gap: on a legacy DGS10 row whose last month is September, retrieved 2026-10-03, the data layer says partial but the chart marked September as the latest observed value. The parity test had also left fred_dgs10 out. The renderer now follows the data layer's rule exactly.
- **Wrong default window in the `data_get` tool text (data_tools.py `DataGetArgs.start`):** it said daily series default to 2 years. The data layer gives FRED daily series 10 years; only daily series outside FRED (Treasury) get 2. The text now says so, and a new test reads the real windows from `DataSources._request`.
- **Date-dependent test:** `test_pre_pass_stores_base_rate_history_because_stored_windows_are_fixed` asserted that start="2000" lies inside a stored history that begins 30 years before today. From 2031 that history starts in 2001, so the test would fail; a probe confirmed the coverage note appears. The test now uses the stored start year plus 4.

**Open items**
- **SKILL.md assertions:** the data-sources SKILL.md checks no longer match exact sentences. A new helper requires all key terms in one paragraph, step, bullet or table row, case-insensitive. A negative check requires every item that names `YYYY-MM-DD` to also name `YYYY-MM`, so the old wrong "Dates use `YYYY-MM-DD`" rule is still caught. The helper has its own test.
- **Parity tests:** the geography table already had an equality test, but the title rule was only checked for the geographies in the test fixtures. I added a test over all 54 catalog geographies, plus an unknown code and an empty one, in English and Chinese. A mutant renderer without the U.K. rule fails only this new test. The Chinese-unit parity test in test_v3_official_data.py (not my file) already compares the tables, the regexes and every captured unit, and it passes.

**Checked and left alone**
- A probe over all 94 real fixture series (5,986 points) shows the renderer's status matches `data_sources.observation_kind` everywhere, before and after the fix; the fixed edge case is not in the fixtures.
- An earlier identity check showed prompts are byte-identical with data off. The prompt builders are unchanged since then, and my edits do not touch any prompt.
- The legacy pre-pass brief block reaches the opening prompt without an untrusted wrapper. It holds curated or official publisher text, bounded in size, and follows the legacy Polymarket-block convention; v3 does wrap its copy.
- `_response` escapes only the lowercase `</official-data>` tag; this is unchanged from HEAD.
- `DataSources.search` hides provider failures, so a legacy search that hits a rate limit is cached as a normal "no match". This is the data layer's API.
- When data is disabled, `meta.data_sources` records status "disabled". This is by design and tested, and v3 does the same.
- The deployed copies under deer-flow/ are stale by design and are re-synced at the next launch.

Notes: /private/tmp/claude-501/-Users-rogerlin-Downloads-DeepResearchForecast/52225542-51e1-41e1-b738-38d44834da7e/scratchpad/review2/legacy-notes.md

- **L-R1** (medium, fixed): Research chart marks an unsettled legacy month as the latest observed value. Location: deerflow_bridge/skills/data-visuals/scripts/render_data.py:_period_metadata. Fix: Only months stored with complete=False in rows whose policy version is not a bool are re-judged. A month counts as complete when its coverage spans the whole month and it is settled, either by a later stored period or by retrieval more than 7 days after month end. This is the same rule as data_sources._legacy_month_complete. The legacy parity test now includes fred_dgs10, and the legacy-months test uses the canonical rule.
- **L-D1** (low, fixed): data_get tool text misstates the default window for FRED daily series. Location: deerflow_bridge/data_tools.py:DataGetArgs.start. Fix: The text now reads '(10 years; 25 for annual series, 2 for daily series outside FRED)'. The new test test_data_get_schema_states_the_data_layer_default_windows reads the year counts from a real DataSources._request (FRED monthly and daily 10, WDI 25, Treasury daily 2) and checks the description against them.
- **L-T1** (low, fixed): Legacy pre-pass test depends on the current year. Location: backend/tests/test_legacy_official_data.py:test_pre_pass_stores_base_rate_history_because_stored_windows_are_fixed. Fix: The 'inside the stored history' start is now str(int(year) + 4), which stays inside the stored history in any year.
- **L-O1** (low, fixed): Exact-sentence assertions on data-sources SKILL.md (open item). Location: backend/tests/test_legacy_official_data.py (test_skills_state_the_request_grammar_and_base_rate_use_the_tools_implement, test_agents_learn_the_year_over_year_route_for_index_levels). Fix: New helpers _skill_items and _skill_states require all key terms in one paragraph, step, bullet or table row, case-insensitive. A negative check requires every item naming `YYYY-MM-DD` to also name `YYYY-MM`. The helper has its own test, and it was verified to catch the old 'Dates use `YYYY-MM-DD`' rule.
- **L-O2** (low, fixed): Geography label parity covered only fixture geographies (open item). Location: backend/tests/test_data_visuals_official.py. Fix: New test test_chart_titles_name_every_catalog_geography_as_the_data_layer_does covers all 54 catalog codes, plus KEN and an empty code, with 10 titles in English and Chinese against data_sources.series_label. The mutant fails it. The table equality test and the Chinese-unit parity test in test_v3_official_data.py both pass.
- **L-N1** (info, not_a_defect): Legacy pre-pass brief block is not wrapped as untrusted. Location: deerflow_bridge/deerflow_research.py:_prefetch_legacy_data. Fix: No change. The content is strong curated-catalog matches with catalog or official-publisher notes, capped at 900 characters per series and 3,600 in total. It follows the same convention as the legacy Polymarket pre-pass block. Recorded as possible hardening.

Files changed: /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/skills/data-visuals/scripts/render_data.py, /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_tools.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_data_visuals_official.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_legacy_official_data.py

Tests run: All runs from backend with `.venv/bin/python -m pytest -p no:cacheprovider`.
- **Baseline before any edit:** the 13 area files passed (exit 0).
- **After the fixes:**
  - The 13 area files (test_bridge_* ×5, test_data_visuals_official/render/status, test_deerflow_bridge_sync_guard, test_legacy_official_data, test_loop010_* ×2, test_runtime_skill_sync): 482 passed, 0 failed.
  - Those 13 plus the related files test_v3_official_data, test_official_data_end_to_end, test_data_sources_config, test_sessionb_research_viz, test_sessionb_skill_hygiene and test_drf2_skills_config: 645 passed, 1 skipped, 0 failed (scratchpad review2/legacy/junit_final.xml).
- **test_official_data_consumers.py** (another area's file): 1 failure, `test_legacy_thread_budgets_and_fred_pacing_are_documented_as_they_behave`. It expects new .env.example wording; that test file was edited at 03:49 by another session and .env.example has not changed since 10-13. The parts that exercise data_tools (`_limit`, `_agent_key`) pass.
- **Red checks:**
  - The pre-fix renderer, loaded through a -p plugin, fails exactly test_legacy_last_month_settles_a_week_after_it_ends[2026-10-03-partial].
  - The U.K.-rule mutant fails only the new all-geography test.
  - The old start="2000" assertion gets a coverage note once the history starts in 2001 (a probe of the year-2031 case).
  - The old tool description lacks both phrases the new schema test asserts.
- **Probes:**
  - All 54 geographies × 9 titles × en/zh: 0 label mismatches.
  - Renderer status vs data_sources over 94 real fixture series (5,986 points): 0 mismatches.
  - Pre-pass id selection takes ≤ 0.2 s.
- **ruff:** `uvx ruff check --select F,E9 --ignore F401,F841,F541` on the touched files: all checks passed.
- No live provider or LLM calls were made.


## Round 7 — re-run of the 403-killed pieces + residual fixes + integration gate `wf_974c76ce-ca8` (2026-10-14)

The downstream reviewer re-ran, then verifiers for data, v3, legacy, report and frontend, each with assigned residual fixes. In the seasonal_profile contract, NSA monthly base rates use a same-month seasonal mean plus pooled residuals. After that came a downstream verifier and a whole-tree integration gate. All 8 agents completed.

### r7:downstream

I reviewed and fixed the downstream area (round 7 re-run). The work the round-6 downstream reviewer left when it died is complete and coherent: settings.py, doctor.sh, official_data.py, simulation_config_generator.py, .env.example and its three test files. I did not need to revert anything. Open items (a), (b) and (c) were already implemented; I checked each against the code. I fixed one defect, (d): the end-to-end test was failing.

(a) Done. historical_snapshot takes a language. "zh", "Chinese" or "中文" give a Chinese snapshot body; any other value gives English. simulation_config_generator passes "en" or "zh" based on _english_output(), on both the canonical brief and the older brief path. English output is byte-identical: I re-ran the dead reviewer's probe over 39 real fixture rows (232 outputs), and the result's sha 00215a6b… matches its pre-edit snapshot en_before.json. Tests cover the Chinese body.

(b) Done and checked against the code. LEGACY_DATA_GETS_PER_THREAD (default 8) and LEGACY_DATA_SEARCHES_PER_THREAD (default 6) are limits per research thread (deer-flow thread_id), with values clamped to 0–40. Subagents that a thread starts through the task tool share one separate bucket per subagent type: data_tools._agent_key keys it as thread/subagent:<name>, and the deer-flow executor tags runs subagent:{config.name}. The DATA_SOURCES_FRED_PER_MINUTE text (allowed range 1–120, falls back to 50, counted per hub) matches data_mcp._fred_calls_per_minute, _RateWindow and the CSV fallback codes.

(c) Done. The endpoint's worst case is _DATA_TEST_MAX_SECONDS = 90 s: a 75 s budget, 2 s grace, and 13 s to close the private hub (McpHub.close: 5 s timeout + 1 + 2 + 2 + 1 + 2 s join). This is documented in settings.py, and doctor.sh says "up to ~90s". The frontend waits 120 s, and a test ties all three values together. I found no unbounded step.

Live check of the real probe (scratch cache; one call each to FRED, BIS, IMF and WB; BLS handshake only):
- First run: 61.6 s (IMF took 61.3 s on a cold cache).
- Second run: 16.5 s. FRED, BIS, IMF and WB all came "(from cache)" with no new provider calls.
- usgov showed degraded both times: Node's fetch to api.fiscaldata.treasury.gov times out on this machine, while curl gets 200. This is a network or environment issue outside my area, and the probe reports it correctly.
- No key values appeared in the output.

(d) Fixed. The guarded runner now passes (1 passed, EXIT=0, run twice, the second time after a concurrent forecast_extractor edit).

Checked and not a defect: two lanes storing the same series as different generations merge consistently. The manifest and the kept source both come from lane 1. The orphaned lane-2 file is harmless because the merged handoff has no sealed research contract.

For the lead, outside my area (not fixed):
1. test_official_data_agent_usage.py::test_outside_view_states_level_changes_in_percent_and_keeps_every_series fails in a wide run. forecast_extractor.py was edited at 04:29 by the concurrent report work (EMPIRICAL_SEASONAL_SHARE), and that changed the EIA US.COM outside-view numbers.
2. Doc nit: the doctor.sh header still calls --deep "a deliberate ~15s gate"; the data-probe bullet itself says up to ~90 s.
3. G6, approved in an earlier verdict: manual simulations now receive the research dossier even when official data is disabled.

Notes: /private/tmp/claude-501/-Users-rogerlin-Downloads-DeepResearchForecast/52225542-51e1-41e1-b738-38d44834da7e/scratchpad/review3/downstream-notes.md. Probes and logs are in scratchpad/review3/downstream/. I did not stage or commit anything and made no LLM calls.

- **DS7-E2E-1** (medium, fixed): Guarded end-to-end test asserted that only chart captions cite [S1]; the report also cites [S1] on every 'Official series to watch' row. Location: backend/tests/test_official_data_end_to_end.py:290. Reproduction: Ran the guarded runner command for test_official_data_end_to_end.py (evidence: scratchpad/review3/downstream/e2e.txt). It failed with: AssertionError: assert 12 == 2 (citation_body_markers.counts.S1 vs len(official)). The published full_report.md has 2 chart-caption [S1] markers plus 10 watch-table rows that end in '[Source](<url>) [S1]'. The report-area change added official_source_tag to _official_watch_row; HEAD rows had no [S#]. The final audit shows 0 dangling markers, so the report behaves as designed and the test expectation was out of date. Fix: The assertion now finds the 10 watch rows, checks there is one per anchored binary and that each ends in '[S1] |', and asserts counts == {'S1': len(official) + len(watch_rows)} with dangling == []. The guarded runner then passed (1 passed, EXIT=0; e2e2.txt) and passed again after a concurrent forecast_extractor edit (e2e3.txt). Under plain pytest the test is still skipped.
- **DS7-A** (info, not_a_defect): Open item (a): Chinese snapshot body for Chinese simulation worlds; English unchanged. Location: backend/app/services/official_data.py:383-623; backend/app/services/simulation_config_generator.py:_official_snapshot_block. Reproduction: The dead reviewer's snapshot_dump probe was re-run over 39 real fixture rows (232 outputs). Default and explicit language='en' both give sha 00215a6b…, identical to its pre-edit en_before.json. The tests test_chinese_snapshot_localizes_its_words_and_keeps_every_figure and test_chinese_world_brief_carries_a_chinese_snapshot_body[False/True] pass. Fix: Already implemented by the round-6 edit and complete: language= with a zh vocabulary that NFKC leaves unchanged, and the generator passes 'en' or 'zh' from _english_output().
- **DS7-B** (info, not_a_defect): Open item (b): .env.example documents per-thread legacy budgets, the per-type subagent bucket and FRED pacing. Location: .env.example:502-516. Reproduction: Checked against data_tools._limit, _budget_denial and _agent_key (thread/subagent:<name>), the deer-flow subagents/executor.py tags [f'subagent:{config.name}'], data_mcp._fred_calls_per_minute and _RateWindow, and the data_sources _FRED_FALLBACK_CODES. test_legacy_thread_budgets_and_fred_pacing_are_documented_as_they_behave passes. Fix: Already precise. No change.
- **DS7-C** (info, not_a_defect): Open item (c): the data-source test endpoint's worst case is bounded at about 90 s and documented. Location: backend/app/api/settings.py:205-225, 343-460; scripts/doctor.sh:23-25. Reproduction: Walked through McpHub.close: 5 s timeout + 1 s terminate + 2 s TERM grace + 2 s cancel grace + 1 s terminate + 2 s join = 13 s. Bound = 75 + 2 + 13 = 90 s. The frontend timeout is 120000 ms, and doctor says 'up to ~90s'. The live probe took 61.6 s cold and 16.5 s warm. Fix: Already implemented by the round-6 edit (the hub is closed first, using the probe's own bound), and test_endpoint_bound_is_documented_and_within_its_clients_timeouts guards it.
- **DS7-OBS-1** (low, not_fixed): Outside view test fails because of a concurrent report-area forecast_extractor edit (not my area). Location: backend/tests/test_official_data_agent_usage.py:346 / backend/app/services/forecast_extractor.py:1837-1912 (EMPIRICAL_SEASONAL_SHARE). Reproduction: In a wide run of 30 related test files, test_outside_view_states_level_changes_in_percent_and_keeps_every_series fails. The EIA US.COM line now reads '...profile): p10 -23623.212 ... as % change: p10 -19.784%...' but the test expects 'p10 -12.993%, median +5.636%, p90 +32.981%'. forecast_extractor.py was modified at 04:29 by the concurrent report work. Fix: Owned by the report area (forecast_extractor / test_official_data_agent_usage): either update the expectation to the seasonal-profile output or adjust the change.
- **DS7-OBS-2** (low, not_fixed): doctor.sh header still describes --deep as a ~15s gate. Location: scripts/doctor.sh:15-17. Reproduction: The header text says the deep checks surface 'in a deliberate ~15s gate'. The official-data probe it now includes can add up to about 90 s (its own bullet says so). Fix: Documentation nit, left as is per the rules (style). Suggest '~15s gate, plus up to ~90s for the advisory official-data probe'.
- **DS7-OBS-3** (info, not_a_defect): Live probe: usgov Treasury sample degraded on this machine (network). Location: environment (datamcps us-gov server: node fetch). Reproduction: probe_data_sources live: usgov DATA_UNAVAILABLE[provider_unavailable] 'fetch failed'. node -e fetch(api.fiscaldata.treasury.gov) → ETIMEDOUT, also with --dns-result-order=ipv4first. curl gets 200 in 1.7 s. Fix: An environment or network issue outside this area. The probe reports it correctly as degraded and does not cache the retryable failure.

Files changed: /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_official_data_end_to_end.py

Tests run: All runs from backend/ with .venv/bin/python -m pytest -q -p no:cacheprovider unless noted.
- Baseline, 11 area test files (official_data_consumers, downstream, promotion, end_to_end, orchestrator_research_wiring, canonical_world_brief_denials, research_contract_finalization, settings_data_sources_probe, data_sources_config, main_offline_runner, deployment_sidecar_control_flow): EXIT=0. The skips are runner-only tests.
- Guarded runner, item (d): `backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir <scratch>/review3/downstream/e2e-evidence* --allow-python-script backend/tests/fixtures/official_data_mcp.py --allow-python-script deerflow_bridge/skills/data-visuals/scripts/render_data.py -q backend/tests/test_official_data_end_to_end.py`.
  - Before the fix: 1 failed (assert 12 == 2).
  - After the fix: 1 passed, EXIT=0.
  - Re-run after the concurrent 04:29 forecast_extractor edit: 1 passed.
- Wide run, 30 files: the area files plus official_data_agent_usage, forecast_ledger, resolution_monitor, settings_endpoint_fallback, settings_provider_info, simulation_config_seal, actor_cast_discipline, actor_context_runtime, audit_fixes_prepare, calendar_event_bucketing, data_sources_interfaces, prompt_injection_boundaries, sim_context_persona, sim_config_v1_provenance, sim_reaction_phase, temporal_mode_contract, sessionb_sim_additivity, sim_config_incentives, sim_market_priors. Result: everything passed except one report-area test, test_official_data_agent_usage::test_outside_view_states_level_changes_in_percent_and_keeps_every_series, which fails because of the concurrent forecast_extractor edit (not my file).
- `uvx ruff check --select F,E9 --ignore F401,F841,F541` on all 21 area .py files: all checks passed.
- `bash -n` on doctor.sh, setup_datamcps.sh, setup.sh and init.sh: OK. `doctor.sh --help` prints the full header.
- Probes:
  - English snapshot byte-identity: 232 outputs, sha matches the pre-edit dump.
  - Two lanes storing the same series as different generations (probe_merge_dup.py): consistent, and finalize returns None.
  - Node fetch versus curl to the Treasury API.
- Live probe through with_data_keys.sh with a scratch DATA_SOURCES_CACHE_DIR, run twice: 1 FRED call total, BLS handshake only, no LLM calls, and no key values in the output.

### r7:data

I verified the data area as the independent round-7 checker, fixed residuals r1 to r4, and found and fixed one new defect. One test outside my area now fails as an expected result of r1 and needs a two-line update by the lead (DATA-R7-3).

Round-6 data fixes. I re-checked each one against the code, the tests and live probes:
- DATA-1 (BEA quarterly data starts in 2005): fix holds.
- DATA-3 (FRED daily series default to ten years): fix holds. A live probe (4 FRED calls) shows FRED's own monthly aggregation returns null for the partial first month of series FRED only keeps a few years of (SP500 2016-10; ICE high-yield spread 2023-10). So the server-built older months never present a partial month as observed. One harmless side effect: an explicit window equal to the default shares the default's cache key but uses a different fetch plan. Both results are correct and say how they were built, so I left it.
- DATA-4 (refused calls no longer take a FRED rate slot): fix holds.
- DATA-2 (BIS euro-area note): I agree it was not a defect.
- The "providers() shows the FRED hub error while the CSV fallback works" item: I agree it is not a defect, because data_tools only drops providers marked disabled or closed.

Residual fixes:
- **r1 (RPT-R2-9):** EIA, BEA, Treasury and USAspending rows now carry their own publisher name. data_catalog.py gains USGOV_PUBLISHERS and provider_name(); data_sources._base uses it. Rows already stored keep their stored name and re-render byte for byte (no policy-version bump). Every consumer reads the stored field.
- **r2 (DATA-5):** catalog clause splitting is now linear. _CONJUNCT_RE only starts a match at the start of a whitespace run. _query_parts shortens each whitespace run before splitting, keeping only the information the split depends on. 160,000 random queries gave 0 differences from the old code. 10k–50k whitespace queries now take 0.03–0.16 s; before, 10k took 1.2 s and 50k would take about 30 s.
- **r3 (RPT-R2-8):** "headline inflation" and "整体通胀" are on every all-items CPI entry (those keyed with cpi, consumer prices or hicp), and on no core or PCE entry. The report probe statement now anchors. Headline wording names only headline CPI rows, core wording only core rows.
- **r4 (ECBDFR):** fred:ECBDFR gains the keywords "deposit facility", "european central bank" and "存款便利". Every deposit-facility wording, in English and Chinese, now ranks ECBDFR first and strong, with the BIS euro-area rate second and strong. A first try that also added "欧洲央行" put ECBDFR first for the Chinese main-refinancing-rate wording, so I dropped it. Main-refinancing wording still leads with BIS.

New defect fixed (DATA-R7-1): when an explicit window opens before a FRED daily series' history (SP500 and the ICE spreads start mid-month), local monthly aggregation counted the first month as complete and observed, using only the last few days. That month is now partial. A live check confirmed BAMLH0A0HYM2 2023-10 (covered from 2023-10-16) and SP500 2016-10 (covered from 2016-10-13) are partial. Months that open late only because of weekends or holidays stay complete.

Found, not fixed (DATA-R7-2): questions like "China's central bank … policy rate" mark the BIS central-bank total-assets series strong, and the legacy pre-pass fetches every strong hit. Every simple fix I tried broke other questions (shown by a before/after comparison over all 8,026 test strings), so it needs a decision on scoring.

Required follow-up outside my area (DATA-R7-3): because of r1, one test in backend/tests/test_official_data_downstream.py, test_chinese_snapshot_localizes_its_words_and_keeps_every_figure, now fails. It needs two expected strings changed:
- line 531: 'U.S. Government Open Data [S8]' becomes 'U.S. Treasury Fiscal Data [S8]'
- line 537: 'U.S. Government Open Data [S7]' becomes 'USAspending.gov [S7]'

Live usgov calls (Treasury, EIA) failed with "fetch failed" in the us-gov node child during my check, while curl reached Treasury; the data layer returned a retryable error without crashing. r1 is proven by replaying the real captures instead. The key scan found no provider key in the owned files or logs.

Notes: /private/tmp/claude-501/-Users-rogerlin-Downloads-DeepResearchForecast/52225542-51e1-41e1-b738-38d44834da7e/scratchpad/review3/data-notes.md

- **DATA-1** (medium, fixed): BEA GDP-by-industry window not clamped to 2005 (round-6 fix). Location: /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_catalog.py USGOV_RECIPES['bea/value_added_by_industry'] min_start. Reproduction: Re-ran test_bea_industry_window_is_clamped_to_its_first_quarterly_year and read _min_start/_request: a 2004 start becomes one 2005 call; a window ending before 2005 gives invalid_window. Confirmed. Fix: Verified the round-6 fix (min_start 2005-01-01 inherited by catalog rows); no change needed.
- **DATA-2** (low, not_a_defect): bis:WS_CBPOL/M.XM deposit-facility note. Location: /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_catalog.py _CBPOL_NOTES['XM']. Reproduction: Note, SKILL.md row and catalog-bis.md all state 'DFR from 18 Sep 2024, MRO before', and a test checks this against the live COMPILATION capture. Fix: Agree with round 6. The ranking side is handled by R4.
- **DATA-3** (medium, fixed): FRED daily default window ten years via server monthly aggregation (round-6 fix). Location: /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_sources.py DataSources._request/_fred_split/_fred_window. Reproduction: Live probe review3/data/probe_first_month.py (4 FRED calls): FRED's monthly avg returns null for the partial first month of licence-limited series (BAMLH0A0HYM2 2023-10 null, daily opens 2023-10-16; SP500 2016-10 null, daily opens 2016-10-13). So the server-built older months never present a partial month as observed. Its tests pass. Fix: Confirmed. Observation only: the cache key leaves out default_window, so an explicit start equal to the default begin shares the default plan's cache entry. Both plans give correct values with accurate provenance.
- **DATA-4** (low, fixed): FRED rate slot taken before the hub refuses the call (round-6 fix). Location: /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_mcp.py McpHub._call. Reproduction: Code read: _RateWindow.admit now runs after _admit's refusal. The only side effect of _admit (launching an idle server) is harmless. test_data_mcp_pacing passes. Fix: Confirmed; no change.
- **DATA-5** (low, fixed): Catalog clause/conjunct split quadratic on long whitespace runs (r2). Location: /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_catalog.py _CONJUNCT_RE, _SPACE_RUN_RE, _clause_space, _query_parts. Reproduction: search_catalog_scored(' '*10000+'x') took 1.16 s (clause 0.53 s + conjunct 0.60 s); '\n '*5000+'x' took 0.9 s; 'cpi'+10k spaces+'and inflation' took 0.58 s. Fix: _CONJUNCT_RE gets (?<!\s) on both alternatives, which is exactly equivalent. _query_parts splits a copy in which each whitespace run is cut down to the kind of its first character plus the kinds the rest holds; clause texts are whitespace-normalised, so outputs are identical. 160,000 random queries (seeds 1-5) gave 0 differences; 10k-50k whitespace now takes 0.03-0.16 s. Test test_clause_and_conjunct_splits_are_linear_and_split_as_before (2000 seeded queries against the old regexes, plus a 2 s bound); it fails on the old code.
- **RPT-R2-9** (low, fixed): usgov EIA/BEA/Treasury/USAspending rows carried the generic gateway provider_name (r1). Location: /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_catalog.py USGOV_PUBLISHERS/provider_name; /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_sources.py DataSources._base. Reproduction: Every fetched usgov row had provider_name 'U.S. Government Open Data (Treasury Fiscal Data, USAspending, EIA, BEA)'. Replaying 6 real usgov captures with the old _base fails 6 new tests (review3/data/red_r1.txt). Fix: Each recipe kind now maps to its agency: Treasury Fiscal Data, USAspending.gov, EIA, BEA, SEC. The short forms (before ' (') match render_data._SOURCE_PREFIXES; other providers are unchanged. Every consumer (render_series_page, report_agent, report_visualizer, official_data snapshot, exec_brief, v3 and legacy facts, frontend) reads the stored field, so stored rows re-render byte-identically. Tests: test_usgov_rows_name_the_agency_that_publishes_them[6] and test_publisher_names_of_other_providers_and_stored_usgov_rows_are_unchanged.
- **RPT-R2-8** (low, fixed): 'US headline inflation ...' had no catalog keyword on CPI entries (r3). Location: /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_catalog.py CPI entries, _imf_cpi, _WEO_CPI_KW, WDI CPI. Reproduction: Report probe: 'US headline inflation is below 2.5% in December 2027.' on bis:WS_LONG_CPI/M.US.771 got no anchor. Search 'US headline inflation' was strong only for CPIAUCSL; '美国整体通胀' had no strong hit. Fix: Added 'headline inflation' and '整体通胀' to every all-items CPI entry keyed with cpi, consumer prices or hicp (CPIAUCSL already had the English term); no core or PCE entry was touched. Now: the anchor probe passes; headline wording names only headline CPI rows; core wording only core rows; 'headline PCE inflation' only PCE. Only headline queries changed rank. Test test_headline_inflation_names_the_all_items_cpi_family_only fails on the old catalog.
- **R4-ECBDFR** (low, fixed): Deposit-facility wording ranked BIS euro-area rate strong but ECBDFR weak or second. Location: /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_catalog.py fred:ECBDFR keywords. Reproduction: 'European Central Bank deposit facility rate': BIS XM strong, ECBDFR concept 13, coverage 0.5, not strong. 'ECB deposit facility rate' and '欧洲央行存款便利利率' ranked BIS above ECBDFR. Fix: ECBDFR keywords gain 'deposit facility', 'european central bank' and '存款便利'. All five deposit-facility wordings now rank ECBDFR first and strong with a strictly higher score; main-refinancing wordings still lead with BIS. Tests: test_deposit_facility_wording_ranks_the_ecb_deposit_rate_first[5] (fails on old) and test_main_refinancing_wording_still_leads_with_the_bis_euro_area_rate (guard).
- **DATA-R7-1** (medium, fixed): Partial first month of a daily history that opens mid-month was marked complete/observed. Location: /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_sources.py DataSources._monthly, _LATE_FIRST_DAY_DAYS. Reproduction: probe_partial_first_month.py: real DGS10 capture cut to open 2026-08-17, start=2026-07-01, gives 2026-08 'observed' with covered_start 2026-08-01, complete True (an 11-day mean shown as the August mean). Live, the same applies to explicit windows such as BAMLH0A0HYM2 start=2020 or SP500 start=2015, while FRED's own monthly aggregation nulls or omits that month. Pre-existing logic, not a round-6 regression. Fix: If the first native day is more than 7 days after the first month's covered start, that month is covered from the first day, so it becomes complete False ('partial'). Weekend or holiday openings and server-built months dated the 1st are unaffected. Live: BAMLH0A0HYM2 2023-10 and SP500 2016-10 are now partial, later months observed. Test test_a_history_opening_mid_month_leaves_that_month_partial fails on the pre-fix copy.
- **DATA-R7-2** (low, not_fixed): Central-bank total-assets series (bis:WS_CBTA) marked strong for central-bank rate questions. Location: /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_catalog.py _concept/_match scoring. Reproduction: 'Will China's central bank cut its policy rate in 2027?', 'US central bank interest rate' and 'Will the European Central Bank cut rates in 2027?' mark WS_CBTA strong: title words central+bank (2.0) plus the policy topic (2.0) = 4.0, coverage 2/3. deerflow_research._legacy_prefetch_ids takes every strong hit, so the legacy pre-pass fetches the balance sheet. v3 seeding is unaffected (one per provider, BIS policy rate first). The strong-match scoring is new in the uncommitted diff. Fix: Not applied. A before/after comparison over 8,026 test strings (corpus_before.json vs corpus_cb.json) showed that treating 'central bank' as a publisher removes the false strongs but loses every strong match for 'Will the European Central Bank cut rates in 2027?' ('rates' is a stopword) and for the CBPOL chart titles. A 'strong needs a keyword' rule would remove many legitimate title or bigram matches. Needs a scoring decision: a rate-vs-stock measure signal that also sees stopword 'rate(s)'.
- **DATA-R7-3** (low, not_fixed): Downstream test hard-codes the old usgov gateway name for freshly replayed rows. Location: /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_official_data_downstream.py:531,537 (downstream-owned). Reproduction: Related 21-file run: 1 failed, 1535 passed, 1 skipped. test_chinese_snapshot_localizes_its_words_and_keeps_every_figure expects 'U.S. Government Open Data [S8]' / '[S7]', but _real_carrier replays the usgov captures through DataSources, so the cells now read 'U.S. Treasury Fiscal Data [S8]' and 'USAspending.gov [S7]', as r1 intends. Fix: Outside my area, so not edited. Lead to replace the two strings: line 531 'U.S. Government Open Data [S8]' with 'U.S. Treasury Fiscal Data [S8]', and line 537 'U.S. Government Open Data [S7]' with 'USAspending.gov [S7]'. I verified both new lines with a direct historical_snapshot call.
- **DATA-OBS-PROVIDERS** (info, not_a_defect): providers() shows the FRED hub error when the server is not built but the CSV fallback works. Location: /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_sources.py DataSources.providers. Reproduction: Code read: data_tools._strong_catalog only excludes providers marked disabled or closed; linear_research only records the status; the settings probe makes live calls. Fix: Status display only; fetching still works.
- **DATA-OBS-TREASURY-DAILY** (low, not_fixed): Treasury daily series keep a 2-year default (no empirical base rate). Location: /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_sources.py DataSources._request. Reproduction: Fiscal Data has no server-side aggregation and 100-row pages; ten years would be about 25 pages per series. Fix: Known limitation; needs an owner decision (for example month-end filtering).

Files changed: /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_catalog.py, /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_sources.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_data_catalog.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_data_sources_providers.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_data_sources_normalization.py

Tests run: All runs from backend with .venv/bin/python -m pytest -p no:cacheprovider. Logs are in scratchpad/review3/data/.

Owned tests:
- The 10 owned files (test_data_catalog, test_data_mcp, _deadline, _pacing, test_data_sources, _config, _interfaces, _normalization, _providers, _smoke): 576 passed before my changes (own_base.txt); 592 passed at the end (own_run3.txt), including 16 new tests.

Tests that fail on the old code:
- r1: with the old _base, the publisher tests give 6 failed, 1 passed (the 1 is a guard) (red_r1.txt).
- r2/r3/r4: a plugin loads the old catalog (redplugin/red_before_catalog.py); the new catalog tests give 7 failed, 1 passed (the 1 is the main-refinancing guard).
- DATA-R7-1: a plugin loads the pre-fix data_sources (redplugin/red_before_ds.py); the new test fails with ('2026-08-01', True).

Related downstream tests:
- 21 files (canonical_world_brief_denials, data_visuals_official/render/status, exec_brief, forecast_extractor_official, legacy_official_data, official_data_agent_usage/consumers/downstream/end_to_end/promotion, orchestrator_research_wiring, report_official_data, report_official_publication_real, report_visualizer_official, research_gateway, research_gateway_official_data, resolution_monitor, settings_data_sources_probe, v3_official_data): 1535 passed, 1 skipped, 1 failed (related_run1.txt).
- The one failure is the expected r1 expectation in test_official_data_downstream.py (DATA-R7-3).

Probes:
- Random equivalence probe (probe_split_equiv.py), seeds 1-5: 160,000 queries, 0 differences.
- Ranking before/after (probe_rank.py, rank_before/r4/r3r4.json): only the headline and deposit-facility queries changed.
- Anchor probe: the headline statement now anchors; headline/core/PCE separation checked with probe_headline_anchor.py.
- Before/after comparison over the 8,026-string test corpus for the rejected central-bank trial: corpus_before.json vs corpus_cb.json.

Lint and secrets:
- ruff --select F,E9 --ignore F401,F841,F541 on all touched files: clean. py_compile: clean.
- Key scan of owned files, fixtures and live logs: 0 hits (4 keys present).

Live checks (with_data_keys.sh, no keys printed, caches in review3/data/; no BLS, IMF or LLM calls):
- 4 FRED calls for the first-month probe.
- 2 FRED calls for DATA-R7-1 (live_check.log).
- 4 usgov calls (Treasury, EIA) failed with 'fetch failed' upstream and degraded cleanly.
- 2 keyless fredgraph CSV curl requests.

### r7:v3

I verified the round-6 v3 review and confirmed two new defects, both now fixed with regression tests.

Round-6 items:
- **V3-RESUME-1:** the fix is correct and needed. I turned `_keep_stored_data` into a no-op with a pytest plugin (review3/v3/red/nokeep_plugin.py), and both parameters of its test then failed.
- **V3-WIN-1:** correct as far as it goes, but it missed a case (V3-WIN-2 below).
- **V3-DOC-1:** docstring change only; it is accurate.
- **V3-SEED-ECB and V3-OBS-1:** I agree they are not defects.

New defects:
1. **V3-HZN-1 (medium):** `_Engine._data_horizon` used the first year in the plan's horizon that is not in the past. Real v3 plans in backend/uploads often give the horizon as a range ("2026–2028" 30 times, "2026–2030", "2026-07-08 → 2031-12-31", "2026-01-01 to 2040-12-31"). For those, the forecast year resolved to 2026. IMF WEO and World Bank GEP projection paths were then fetched only to 2026-12-31, and a stored window cannot be extended later in the run, so the summary and critique saw no projections past 2026. It now uses the latest named year that is not past, still capped at as-of year + 6.
2. **V3-WIN-2 (low-medium; the round-6 fix was incomplete):** `research_gateway._window_note` gave no "not refetched" note when a projection path had been stored only through the retrieval year. This happens with a plan horizon of "2026" or "2026-12-31" (both appear in real plans), or when an agent first asks with end="2026". In that case no stored point is after the retrieval date and the stored end is not before it, so an agent asking end="2028" silently got a page ending in 2026. The end side is now also treated as cut short when the series has `projection_from` and its stored end is before the end of the sixth year after retrieval, which is the data layer's default end for these series.

Other checks:
- **Disabled-data output unchanged (§0.2):** I ran a full scripted v3 engine with official data disabled, once with HEAD's linear_research/research_gateway and once with the current files including my fixes, in English and in Chinese with gap follow-ups (probes/diff_disabled.py). Model calls, the tools JSON, log lines and every artifact match. The only differences are source numbering from thread order, hex ids and timings; meta.data_sources is identical.
- **Display robustness:** every engine display rendered for all 110 captured real series in EN and ZH without an exception.
- **Progress estimator:** the new v3 log lines do not trigger any legacy progress milestone.
- **Prompt cache (§0.3):** ENGINE_CORE is untouched, the tools object is picked once per run, the digest is built once and persisted, and data text sits only in task messages.

Cross-area items for the lead (not my files):
- **(a)** `data_tools._window_note` says it matches the gateway rule but lacks the new `projection_from` check, so the legacy engine still has the same blind spot.
- **(b)** `test_official_data_agent_usage.py::test_outside_view_states_level_changes_in_percent_and_keeps_every_series` fails in the current tree. It is about forecast_extractor's seasonal-profile text (report area; that file was modified at 04:39 by another agent) and does not touch linear_research or research_gateway.

Noted but not fixed (low or style):
- A concurrent request for the same series with a different window gets a "retry once" timeout answer without its window ever being tried.
- `_BASE_RATE_RE` is broad: "历史" and "historical" match ordinary questions.
- After a crash before `data/index.json` is written, `_data_requests` can count fewer used prefetch slots than the gateway does. The gateway then refuses the extra requests with the prefetch-limit text; this never fails a run.

My notes are in review3/v3-notes.md.

- **V3-HZN-1** (medium, fixed): Forecast horizon of a range horizon resolves to its first year, so WEO/GEP projection paths are prefetched only to the current year. Location: deerflow_bridge/linear_research.py:_Engine._data_horizon (~line 5232). Reproduction: Plan as_of 2026-10-12 with horizon '2026–2028' (real backend/uploads plans: 30x; also '2026-07-08 → 2031-12-31', '2026-01-01 to 2040-12-31', '2026-07-06 至 2028-12-31'): _data_horizon() returned 2026, and phase_data requested wb:IMF_WEO_NGDP_RPCH/USA with end=2026-12-31. probes/horizon_probe.py; new test failed for the 5 range params before the fix. Fix: Use max(named years >= as_of year, default as_of+5), capped at as_of+DATA_PROJECTION_YEARS; docstring updated. Regression test backend/tests/test_v3_official_data.py::test_a_projection_path_is_prefetched_through_the_end_of_a_horizon_range (9 real horizon shapes, asserts _data_horizon and the WEO prefetch end).
- **V3-WIN-2** (low, fixed): Round-6 _window_note fix incomplete: no 'not refetched' note for a projection path stored only through the retrieval year. Location: deerflow_bridge/research_gateway.py:_window_note (~line 3638). Reproduction: Real current-policy row wb:IMF_WEO_PCPIPCH/USA (retrieved 2026-10-12, projection_from 2026-01-01) as the data layer returns it for end=2026 (last obs 2026-01-01, requested_end 2026-12-31), stored via prefetch_data with window (None, '2026') as v3 does for horizon '2026'. data_get(end='2028') returned the stored page with no NOTE line (cut_short False because last <= retrieved and held_end >= retrieved), although the publisher's path runs to 2027 and beyond. Fix: cut_short also holds when the series has projection_from and held_end < the end of (retrieval year + _DATA_PROJECTION_END_YEARS=6), which is data_sources' default end for a projection family. Rows without projection_from behave as before (checked against all real fixtures with probes/window_all.py). Regression test backend/tests/test_research_gateway_official_data.py::test_a_projection_path_stored_to_the_retrieval_year_notes_a_later_end (failed before the fix).
- **V3-RESUME-1** (medium, fixed): (round 6) Resumed attempt with providers unavailable dropped stored official data. Location: deerflow_bridge/linear_research.py:_Engine._configure_data/_keep_stored_data. Reproduction: Re-verified: with _keep_stored_data turned into a no-op by a pytest plugin, test_a_resume_whose_providers_are_unavailable_keeps_the_stored_series fails for both params; with the fix it passes. Exception path and no-stored-evidence path also checked. Fix: Round-6 fix confirmed correct; no change needed.
- **V3-WIN-1** (low, fixed): (round 6) False 'not refetched' note for a forecast-horizon end on a default-window series. Location: deerflow_bridge/research_gateway.py:_window_note. Reproduction: Re-verified against the data layer's window rules (default end = UTC retrieval date; a projection family defaults to +6y) and all real stored rows (probes/window_all.py): default-window rows give no note for end=2026, 2027 or 2031; cut-short and projection rows are noted. The incomplete part is reported as V3-WIN-2. Fix: Round-6 fix kept; completed by V3-WIN-2.
- **V3-DOC-1** (info, fixed): (round 6) Docstring corrections. Location: deerflow_bridge/research_gateway.py:prefetch_data; deerflow_bridge/linear_research.py:_configure_data. Reproduction: Read both docstrings against the code: prefetch is called in the plan phase and before gap follow-up workers start; a resumed run that recorded data as disabled stays disabled. Fix: Accurate; no change.
- **V3-SEED-ECB** (info, not_a_defect): (round 6) ECB deposit-rate fallback seeding. Location: deerflow_bridge/linear_research.py:_catalog_seeds. Reproduction: Independent decision: the seeding follows the catalog's strong matches; the ranking of the 'European Central Bank deposit facility rate' wording belongs to the catalog owner. Fix: 
- **V3-OBS-1** (info, not_a_defect): (round 6) Provider series labels outside untrusted delimiters in the KIQ 'other series' list and writer pointers. Location: deerflow_bridge/linear_research.py:_kiq_data_text, _section_data_lines. Reproduction: Independent decision: the labels are curated catalog titles or official publisher metadata, already cleaned by the data layer; the digest, exec and critique headline blocks are delimited. No injection path could be reproduced from official metadata, and changing it would alter data-enabled prompt text without a demonstrated defect. Fix: 
- **X-LEGACY-WIN** (low, not_fixed): Legacy data_tools._window_note says it matches the gateway rule but lacks the new projection_from check. Location: deerflow_bridge/data_tools.py:_window_note (legacy area, not my file). Reproduction: Same scenario as V3-WIN-2 on the legacy tools: a WEO/GEP path stored with end at the retrieval year, then a later end, gives no note. Fix: For the legacy owner: add the same clause (projection_from and held_end < end of retrieval year + 6).
- **X-REPORT-SEASONAL** (medium, not_fixed): test_official_data_agent_usage outside-view test fails in the current tree (report area). Location: backend/tests/test_official_data_agent_usage.py::test_outside_view_states_level_changes_in_percent_and_keeps_every_series; backend/app/services/forecast_extractor.py (not my files). Reproduction: cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_official_data_agent_usage.py : the EIA electricity sales line ends with a seasonal-profile '% change' quantile set (p10 -19.784%) instead of the expected 'p10 -12.993%, median +5.636%, p90 +32.981%'. The test uses forecast_extractor only, and forecast_extractor.py was modified at 04:39 by another agent (round-6 verify:report seasonal share). Fix: For the report-area verifier: reconcile _empirical_seasonal_share output with this test or update the expectation.

Files changed: /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/linear_research.py, /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/research_gateway.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_v3_official_data.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_research_gateway_official_data.py

Tests run: All runs used `cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider`.
- Baseline, the 11 owned files: exit 0 (review3/v3/baseline.txt).
- run1, after the horizon fix: owned files plus test_live_research_progress.py and test_start_script_progress.py, exit 0 (run1.txt).
- New tests failed before their fixes: test_a_projection_path_is_prefetched_through_the_end_of_a_horizon_range (the 5 range params) and test_a_projection_path_stored_to_the_retrieval_year_notes_a_later_end (no NOTE line). Both pass after the fixes; test_research_gateway_official_data.py is 34/34.
- run2, after both fixes: owned files, the 2 progress files and 13 related files (test_bridge_overhaul_v3, test_bridge_extensions_config, test_data_catalog, test_data_mcp, test_deerflow_bridge_sync_guard, test_official_data_consumers, test_official_data_end_to_end, test_orchestrator_research_wiring, test_research_fork_handoff, test_loop010_global_synthesis, test_official_data_agent_usage, test_official_data_downstream, test_legacy_official_data). Exit 1 from a single failure in the report area (test_official_data_agent_usage::test_outside_view_states_level_changes_in_percent_and_keeps_every_series). Everything else passed (run2.txt).
- Red check for V3-RESUME-1: the plugin that turns `_keep_stored_data` into a no-op makes both params fail.
- Probes, all in scratchpad/review3/v3/probes:
  - horizon_probe.py: real horizon strings.
  - window_all.py: window notes over all real stored rows.
  - render_all.py: 110 real series × EN/ZH displays, no exceptions.
  - diff_disabled.py: full scripted v3 runs with official data disabled, HEAD vs current lr/rg, EN and ZH with gap follow-ups. Calls, tools, log and artifacts are equal apart from thread-order source numbering, hex ids and timings.
- `uvx ruff check --select F,E9 --ignore F401,F841,F541` on linear_research.py, research_gateway.py, research_progress.py and both test files: all checks passed.
- No live provider calls and no paid LLM calls; the full suite was not run.

### r7:legacy

I was the independent adversarial verifier for the round-6 legacy reviewer-fixer. I re-tested every fix it reported, decided its not_a_defect items myself, and looked for anything it missed in the uncommitted legacy diff.

**Round-6 fixes: all hold up.**
- L-R1: chart status for old stored months matches the data layer. I compared the renderer against `data_sources.observation_kind` on 140,616 points: every visuals fixture, 12 policy-version values (absent, None, bools, strings, floats, ints), 6 retrieval stamps (a +08:00 timezone, the exact end+7-day boundary, garbage), trimmed and untrimmed. There were 0 mismatches.
- L-D1: the `data_get` tool text now matches the data layer's default windows (25 years for annual, 2 for daily series outside FRED, 10 otherwise).
- L-T1: the pre-pass test no longer depends on the year.
- L-O1 and L-O2 (the SKILL.md assertion helpers and the all-geography title test) are sound and pass when run alone.

**Real defects found and fixed: 2, each failing first, then fixed with a regression test.**
- **W1 (window note gap, the item the v3 reviewer flagged):** confirmed with the real stored row `wb:IMF_WEO_PCPIPCH/USA` (stored to an explicit 2027 end, retrieved 2026-10-12). After that, a request for an end of 2031 got the stored page back with no "not refetched" note. `data_tools._window_note` now uses the same rule as v3 (adds `or last > retrieved`). Across 5,832 synthetic cases, legacy and v3 now make the same note decision every time.
- **O1 (missed by round 6):** in `data_tools._admit`, a request whose earlier attempt had failed got that failure replayed even after the same series had been stored by another request. The failure was permanent for non-retryable errors, or lasted the 20 s backoff for retryable ones. Example: `fred:UNRATE` with start 1996 fails, the default window then stores it, and repeating the 1996 request still returned `DATA_UNAVAILABLE`. This broke the stored-series list's promise that a stored id is returned free, and differed from v3, which checks stored series before cached results. The stored-series check now runs right after the cached-success check, which keeps its tamper validation, and before the failure and pending replay. The repeat now returns the stored page with a window note and makes no extra provider call.
- Red check: I ran the test file against copies of `data_tools.py` with each fix reverted. Each copy fails exactly its own new test(s).

**Items left as they are:**
- I agree with the reviewer's not_a_defect calls on L-N1 (pre-pass brief not wrapped as untrusted: curated, bounded, same convention as the market block) and on recording `meta.data_sources {"status":"disabled"}` (v3 did the same at HEAD; meta.json is telemetry).
- Noted only:
  - The static deep-research SKILL.md now names `data_search`/`data_get` even when official data is disabled. This was the assigned L5 design; earlier identity checks treated skill files as static.
  - `data_tools._response` escapes only a lowercase `</official-data>`. This was already in HEAD and is not part of the diff.
- Other checks:
  - 0 exceptions from the baseline table, quantitative rows, series briefs and labels across the 110 real fixture rows.
  - The renderer runs end to end on legacy and mixed fixtures at chart caps 0, 1, 3 and 12, with digit-free titles and captions.
  - Faking the clock to 2031 and 2040 turned up no year-dependent test. The 28 rendering tests that fail under the fake also fail with it set to 2026; the fake date class breaks matplotlib.
  - `config.yaml` and `runtime_skill_sync.py` are unchanged. `config.yaml` is byte-identical to `deer-flow/config.yaml`.

**One failure outside my area:** `test_official_data_agent_usage.py::test_outside_view_states_level_changes_in_percent_and_keeps_every_series` fails. It tests `forecast_extractor.official_outside_view_block`; `forecast_extractor.py` was changed at 04:29, apparently by the concurrent report verifier. It does not involve `data_tools`.

Notes and probes: `/private/tmp/claude-501/-Users-rogerlin-Downloads-DeepResearchForecast/52225542-51e1-41e1-b738-38d44834da7e/scratchpad/review3/legacy-notes.md`; artifacts in `scratchpad/review3/legacy/` (`probes/`, `red/`, `timetravel/`, `baseline.txt`, `final.txt`).

- **W1** (low, fixed): Legacy window note missing for a later end after a projection path was stored to an explicit future end (v3 parity). Location: deerflow_bridge/data_tools.py:_window_note. Reproduction: Real v3_engine row wb:IMF_WEO_PCPIPCH/USA (requested_end 2027-12-31, last obs 2027-01-01, retrieved 2026-10-12): data_get_impl(id, end='2027') then data_get_impl(id, end='2031'). The second call returned the stored page with no 'not refetched' note (probe review3/legacy/probes/window_probe.py). Test test_a_projection_path_stored_to_an_explicit_end_notes_a_later_end failed before the fix. Fix: cut_short also holds when the last stored point is after the retrieval date (or last > retrieved), matching research_gateway._window_note; docstring updated. Across 5,832 synthetic cases, legacy and v3 make the same note decision every time.
- **O1** (medium, fixed): Cached failure of one window is replayed even though the series identity is already stored. Location: deerflow_bridge/data_tools.py:_admit. Reproduction: data_get_impl('fred:UNRATE', start='1996') fails (provider_error or rate_limited), then data_get_impl('fred:UNRATE') stores [S745224596], then data_get_impl('fred:UNRATE', start='1996') returns 'DATA_UNAVAILABLE[provider_error]: ...' forever (or '(Retry allowed in about 19 s.)' for retryable failures) instead of the stored page (probe review3/legacy/probes/failure_order_probe.py). v3 _data_call checks identity in self._datasets before _data_cache. Fix: Moved the stored-identity check for get requests between the cached-ok branch (binding validation kept first) and the failed/pending replay; removed the later duplicate. Regression test test_a_stored_series_answers_a_window_whose_own_request_failed[provider_error-False|rate_limited-True]; both cases fail against a pre-fix copy loaded through a pytest plugin.
- **L-R1** (medium, fixed): (round 6) Renderer marks an unsettled legacy month as latest observed. Location: deerflow_bridge/skills/data-visuals/scripts/render_data.py:_period_metadata. Reproduction: Re-verified: renderer vs data_sources.observation_kind over 140,616 points (all visuals fixtures x 12 policy-version values x 6 retrieval stamps incl. timezone, end+7-day boundary and garbage, x trimmed/untrimmed): 0 mismatches. Fix: Round-6 fix verified correct; no change needed.
- **L-D1** (low, fixed): (round 6) data_get schema text misstated the default window for FRED daily series. Location: deerflow_bridge/data_tools.py:DataGetArgs.start. Reproduction: Re-verified against DataSources._request: 25 years for annual, 2 for daily series outside FRED, 10 otherwise. Fix: Round-6 fix verified; no change needed.
- **L-T1** (low, fixed): (round 6) Date-dependent pre-pass test. Location: backend/tests/test_legacy_official_data.py:test_pre_pass_stores_base_rate_history_because_stored_windows_are_fixed. Reproduction: Re-verified: year+4 is always at or after requested_start. A fake-clock run of the area tests for 2031 and 2040 finds no year-dependent test (the failures under the fake clock are the same set as with the fake set to 2026, i.e. artifacts of the fake date class in matplotlib). Fix: Round-6 fix verified; no change needed.
- **L-N1** (info, not_a_defect): Legacy pre-pass brief block not wrapped as untrusted. Location: deerflow_bridge/deerflow_research.py:_prefetch_legacy_data. Reproduction: Independently reviewed: content is strong curated-catalog matches with catalog or official-publisher notes, at most 900 characters per series and 3,600 in total; same convention as the legacy Polymarket block. No harmful input could be reproduced. Fix: No change (agree with the round-6 reviewer).
- **TEL-1** (info, not_a_defect): meta.data_sources records status 'disabled' when official data is off. Location: deerflow_bridge/deerflow_research.py:_record_legacy_data_telemetry. Reproduction: v3 at HEAD (linear_research.py:4086) already records {'status':'disabled'}; meta.json is timestamped telemetry, not a content artifact. Fix: No change.
- **OBS-1** (info, not_fixed): Static deep-research SKILL.md names data_search/data_get even when official data is disabled. Location: deerflow_bridge/skills/deep-research/SKILL.md. Reproduction: The always-injected skill body mentions the data tools whatever DATA_SOURCES_ENABLED is set to. This was the assigned L5 fix, and earlier identity checks treated skill files as static assets. Fix: Design trade-off from L5; would need dynamic skill rendering. Recorded for the lead.
- **OBS-2** (info, not_fixed): _response escapes only a lowercase </official-data> closing tag. Location: deerflow_bridge/data_tools.py:_response. Reproduction: Code inspection; already in HEAD and not part of the uncommitted diff. v3 uses delimit_untrusted plus neutralization. No realistic provider text was found to reproduce it. Fix: Possible hardening: escape the tag case-insensitively. Not changed because it is outside the diff and could not be reproduced.

Files changed: /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_tools.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_legacy_official_data.py

Tests run: All runs used `cd backend && .venv/bin/python -m pytest -p no:cacheprovider`.
- **Baseline before any edit:** the 13 area files exited 0 (review3/legacy/baseline.txt).
- **After both fixes:** test_legacy_official_data.py: 99 passed.
- **Final run:** the 13 area files (test_legacy_official_data, test_data_visuals_official/render/status, test_loop010_global_synthesis/research_contracts, test_bridge_extensions_config/market_tools/overhaul_v3/prediction_markets/search_and_cache, test_runtime_skill_sync, test_deerflow_bridge_sync_guard) plus test_v3_official_data, test_official_data_end_to_end, test_official_data_consumers, test_research_gateway_official_data, test_data_sources_config, test_sessionb_research_viz, test_sessionb_skill_hygiene and test_drf2_skills_config: 712 passed, 1 skipped, EXIT=0 (review3/legacy/final.txt).
- **Red checks:** pytest `-p` plugins load pre-fix copies of data_tools.py (test_restart_dedup is deselected because its importlib.reload re-executes the real file). The copy without the ordering fix fails exactly the 2 new O1 cases. The copy without the window fix fails exactly test_a_projection_path_stored_to_an_explicit_end_notes_a_later_end.
- **Probes:**
  - Window-note decisions, legacy vs v3: 5,832 cases, 0 mismatches.
  - Renderer vs canonical status: 140,616 points, 0 mismatches.
  - Presentation helpers over 110 real fixture rows: 0 exceptions.
  - Renderer end to end on legacy and mixed fixtures in en/zh at chart caps 0, 1, 3 and 12: all titles and captions digit-free.
  - Fake clock at 2031 and 2040: no year-dependent test (same 28 matplotlib artifacts as with the fake set to 2026).
- **ruff** `--select F,E9 --ignore F401,F841,F541` on data_tools.py and test_legacy_official_data.py: all checks passed.
- `cmp deerflow_bridge/config.yaml deer-flow/config.yaml`: identical.
- **Failure outside my area:** test_official_data_agent_usage.py::test_outside_view_states_level_changes_in_percent_and_keeps_every_series fails in forecast_extractor (changed at 04:29 by the concurrent report verifier); it does not involve data_tools.
- No live provider calls and no LLM calls.

### r7:report

I verified the round-6 report fixes and the dead round-6 verifier's partial `_empirical_seasonal_share` fix, implemented r1 (RPT-R2-7, the `seasonal_profile` basis) and r2 (FE-N1, fiscal-year labels), and fixed three defects that round 6 missed. Each defect was reproduced first. I did not stage or commit anything, made no LLM calls, and made 8 live FRED calls (well within the limits). Notes: `scratchpad/review3/report-notes.md`.

**r1 – seasonal_profile, built exactly to the lead's contract (forecast_extractor.py)**
- New helpers `_empirical_profile` and `_empirical_sample`, and a new `seasonal_profile` branch in `_empirical_season`. The base rate, fan, metric ranges and the outside view (including its "% change" line) all use `_empirical_sample`.
- Order of rules: no basis for a series that is not monthly NSA, a yoy transform, h % 12 == 0, or a measured seasonal share below 0.25. Then `same_calendar_month` when it gives at least 30 changes. Then `seasonal_profile`: start months with at least 3 changes get a mean s(m), the latest month m* needs at least 5 changes, the sample is s(m*) + r_t, and it needs at least 30 values. Otherwise `all_start_months`.
- One choice of mine: a history too short to measure the seasonal share (share None) never gets a profile; it keeps the disclosed `all_start_months`.
- Wording, EN and ZH, full and short, is exactly as in the contract. The visualizer fan legend uses the short form for the profile.
- The 25 pp divergence flag stays on for the profile.
- Byte-identity check (`scratchpad/review3/report/snapshot.py`): 4,619 outputs compared before and after. They cover base rates for h = 1..60 with both comparators, fans, and outside views (EN/ZH, capped and uncapped) on every real carrier, plus synthetic 40- to 480-month series. 948 outputs changed, and every one of them carries the profile marker. No outside-view line count changed, so Q2 still fits under 3,600 characters.
- Stored EIA US.COM case, July to December (h = 5, n = 112):
  - median change −21,855 million kWh, against −21,842 over the 9 July starts and +63 when all starts are pooled.
  - The fan now falls from 150.6k in July to a 123.8k November trough.
  - The base rate is 0% (it was 65% when pooled).
- Chart evidence (before = pooled, after = profile), all in `scratchpad/review3/report/charts/`:
  - `profile_static/charts/official_series_qcfeaencsdnrfbon.png` and `pooled_static/…` (matplotlib)
  - `profile_plotly/…` and `pooled_plotly/…` (Plotly, `.png` and `.html`)

**r2 – FE-N1 (fiscal-year labels)**
- The FY2026 anchor period (stored as 2025-10-01) now reads "FY2026" in:
  - the settlement sentence: "for FY2026" / "观察期 FY2026"
  - the watch table
  - the chart threshold and band legend labels
  - the exec brief, which now reads the report's own stored official data
- New helper `official_fiscal_label` takes the label from the stored provenance period record. For a fiscal year not stored yet it uses the data layer's own rule (FY = start year + 1).

**Partial verifier fix (_empirical_seasonal_share)**
- The 0.25 threshold is sound. A profile needs at least 61 months of history, and at that length random walks reach 0.25 in ≤1.35% of runs (iid, AR, heavy-tailed and step-like changes); at 96+ months, in none.
- The short-history (None) path is conservative and is tested.
- Defect found: one shock hides a real seasonal swing (see RPT-R3-1). Fixed by computing the share on ranks.

**Tests (backend/.venv pytest, -p no:cacheprovider)**
- Owned set of 13 files, final run: 641 passed, 11 xfailed, exit 0. A visualizer assertion added during that run was checked separately and passes.
- Wider set of 76 files that use these modules (test_export_demo_site_data.py excluded): 1943 passed, 1 skipped, 11 xfailed, 1 failed. The failure is `test_official_data_downstream.py::test_chinese_snapshot_localizes_its_words_and_keeps_every_figure`. It expects the provider name "U.S. Government Open Data" but now gets "U.S. Treasury Fiscal Data", because another agent changed `deerflow_bridge/data_sources.py` at 04:48. It is not caused by my changes.
- Each new regression test fails when the old behaviour is restored (`redplugin/red_before.py`, RED=season/fy/subset/rank: 8, 6, 9 and 1 failing tests).
- ruff F,E9 on all 6 changed files: all checks passed. py_compile: OK.

**For the frontend verifier and the lead (outside my files)**
- `binaryForecasts.js` does not know `seasonal_profile`, so no caveat is shown; its flag stays on, which is consistent with the backend. `BinaryForecastTable.vue` needs the profile wording.
- The fixture `binary_forecast.eia_nsa_pooled.json` is now stale: the backend gives `seasonal_profile` and p = 0.0 for that anchor. A pooled case needs a history cut to the last 60 months (n = 55).
- `dataAnchorModel` should take the period label from the carrier's provenance.

- **RPT-R2-7** (medium, fixed): Pooled fallback drew a seasonally flat fan and base rate for strongly seasonal NSA monthly series. Location: backend/app/services/forecast_extractor.py:_empirical_profile/_empirical_season/_empirical_sample/_empirical_outlook/official_empirical_fan/official_outside_view_block; report_visualizer.py:_official_fan_label. Reproduction: Stored EIA US.COM row, anchor >=140000 in 2026-12 (h=5): before, the fan stayed flat around 150k (median 150,641) and the base rate was 65% (seasonal_basis all_start_months), although December values never reach 140k. Rendered pooled_static/official_series_*.png. Fix: Added the contract's 'seasonal_profile' sample: s(m*) + r_t over start months with at least 3 changes; m* needs at least 5 changes and the sample at least 30. Wording is in EN/ZH, full and short, across the base rate, fan, metric ranges, outside view (including the % change line), Part 1 cell, watch table, exec brief and Plotly/matplotlib labels; the divergence flag stays on. Now n=112, median change -21,855, base rate 0%, and the fan falls to the November trough. Every output that does not take the new branch is byte-identical (snapshot.py, 4,619 outputs). Tests: test_nsa_monthly_base_rate_uses_the_seasonal_profile, test_seasonal_profile_is_disclosed_wherever_the_rate_is_shown, test_outside_view_percent_change_uses_the_seasonal_profile, test_short_or_unmeasured_nsa_history_pools_the_seasons_and_says_so, test_pooled_seasons_are_disclosed_and_never_flag_divergence, test_fan_and_threshold_say_which_seasonal_basis_they_use[2 cases], test_seasonal_profile_fan_draws_the_seasonal_swing.
- **RPT-R3-1** (medium, fixed): Seasonal-share test swamped by one shock: strongly seasonal NSA series were treated as non-seasonal (unadjusted seasons pooled, not disclosed). Location: backend/app/services/forecast_extractor.py:_empirical_seasonal_share (round-6 verifier's partial fix). Reproduction: Live FRED NSA data from 2016-11 (3 calls): raw epsilon squared is -0.001 for UNRATENSA, 0.186 for PAYNSA and 0.217 for CPIAUCNS, all below 0.25, because of the April 2020 spike. The series were treated as non-seasonal, so their seasonal swing was pooled into a plain sample with no caveat. Fix: The share is now computed on ranks (Kruskal-Wallis epsilon squared, tied changes share their average rank): UNRATENSA 0.47, PAYNSA 0.66, CPIAUCNS 0.33. Stored carriers stay on the same side of 0.25: EIA 0.44-0.93 and HICP 0.54 above; FEDFUNDS -0.03, ECBDFR -0.09 and PPI 0.07 below. False-positive rate on simulated random walks of at least 61 months is at most 0.75%. Test test_one_shock_does_not_hide_a_seasonal_swing uses the 118 live UNRATENSA values inline (October 2025 shutdown gap included).
- **FE-N1** (low, fixed): Fiscal-year anchor period shown as the calendar year of the fiscal-year start ('2025' for FY2026). Location: backend/app/services/forecast_extractor.py:_official_watch_row/_anchor_settlement_sentence; report_visualizer.py:_official_threshold_label/_official_band_label; exec_brief.py:_anchor_watch_line/_build_watch_block/_render_brief. Reproduction: Replayed real USAspending capture (usgov:spending/total), anchor 2025-10-01: the watch table showed '/ 2025', the settlement sentence 'for 2025', and the exec brief '(2025)'. Fix: New official_fiscal_label and official_anchor_period_text read the stored us_federal_fiscal_year label records; a fiscal year not stored yet gets FY<start year + 1>, the data layer's rule. Visualizer labels receive the row being charted; the exec brief loads the rows of the report's own official_data.json (_official_rows). Test test_fiscal_year_anchor_reads_its_fy_label_everywhere covers everything up to an ExecBriefBuilder.build of a temporary report.
- **RPT-R3-2** (medium, fixed): Fiscal-year anchors admitted on calendar-year wording; correct 'FY2026' wording always rejected. Location: backend/app/services/forecast_extractor.py:_anchor_target/_anchor_periods/_anchor_mention_matches/_anchor_criteria_ok/_anchor_statement_ok. Reproduction: probe_fy2.py: 'US federal award spending exceeds $7 trillion in 2025.' was ADMITTED on the FY2026 period (Oct 2025 to Sep 2026) with 'for 2025'. 'in FY2026' and 'in fiscal year 2026' were always dropped. Fix: For a fiscal-year row the target period is ('FY','FY2026'). FY/fiscal year/财年 mentions are read only for such anchors; the exact start date 2025-10-01 is accepted; a bare year no longer matches. Calendar rows are unchanged. Stored forecasts can be re-normalized again and keep their anchor. Test test_fiscal_year_anchor_is_named_by_its_fiscal_year (8 cases).
- **RPT-R3-3** (medium, fixed): Component and subgroup wordings anchored on the headline series. Location: backend/app/services/forecast_extractor.py:_ANCHOR_SUBSET_RE/_anchor_foreign_qualifier. Reproduction: probe_matcher_cmp.py: 'US consumer price inflation of services / for urban wage earners' was ADMITTED on BIS headline CPI. 'The US unemployment rate for Black workers / of college graduates' and '美国女性失业率…' were ADMITTED on fred:UNRATE, which settles automatically. Recall gains from round 6 made more of these wordings match. Fix: Added component and subgroup qualifiers (EN/ZH). As with the existing qualifiers, a word is allowed only when the series' own names carry it, in singular or plural. A self-recall probe of 842 statements built from each row's own keywords and titles gave 638 admitted both before and after the change. 11 RECALL_CASES added; 9 of them fail under the old code.
- **RPT-R2-1** (high, fixed): (round 6) NSA monthly base rate mixed the seasons. Location: backend/app/services/forecast_extractor.py:_empirical_season. Reproduction: Re-checked: SA, unknown-adjustment, yoy and whole-year (h%12==0) samples still carry no basis; disclosure works in every display. Fix: Round-6 disclosure confirmed. Its pooled fallback is now replaced by seasonal_profile where the data allow (RPT-R2-7).
- **RPT-R2-2** (medium, fixed): (round 6) Anchor matcher recall via keyword windows. Location: backend/app/services/forecast_extractor.py:_anchor_keyword_windows. Reproduction: Re-probed the negation, compound, deadline, place, PPI/PCE and excluding/less/ex wordings: all still rejected. The component/subgroup gap was found and fixed as RPT-R3-3. Fix: Verified; the remaining gap is fixed as RPT-R3-3.
- **RPT-R2-3** (medium, fixed): (round 6) Inflation-expectations wording anchored on realized CPI. Location: backend/app/services/forecast_extractor.py:_ANCHOR_QUALIFIER_RE. Reproduction: 'US consumer price inflation expectations are above 3%' is dropped; the RECALL_CASES pass. Fix: Verified, no change.
- **RPT-R2-4** (medium, fixed): (round 6) Exec-brief official values without units. Location: backend/app/services/exec_brief.py:_official_amount. Reproduction: Re-checked the indicator table, watch line and digest: units are shown; percent values are unchanged. Fix: Verified, no change.
- **RPT-R2-5** (low, fixed): (round 6) World-brief test drift. Location: backend/tests/test_official_data_agent_usage.py. Reproduction: Test passes. Fix: Verified. I also updated test_outside_view_states_level_changes_in_percent_and_keeps_every_series: its EIA 2030-12 line now takes the seasonal profile (% median -13.594% against the pooled +5.636%).
- **RPT-R2-6** (medium, not_fixed): Frontend does not show seasonal_basis (now including seasonal_profile). Location: frontend/src/utils/binaryForecasts.js SEASONAL_BASES; frontend/src/components/research/BinaryForecastTable.vue; frontend/tests/fixtures/official/binary_forecast.eia_nsa_pooled.json. Reproduction: SEASONAL_BASES lacks 'seasonal_profile', so the caveat is dropped. The fixture's EIA case now gets seasonal_profile with p=0.0 from the backend. Fix: Outside my area (frontend). Add 'seasonal_profile' with the contract wording and keep the divergence flag on. Regenerate the fixture; a pooled case needs a 60-month history (n=55).
- **RPT-R3-4** (low, not_fixed): Fiscal-year anchors are rarely created: the prompt asks for YYYY|YYYY-MM-DD and the data pack shows FY labels, not the start date 2025-10-01. Location: backend/app/services/forecast_extractor.py binary prompt; deerflow_bridge/data_sources.py _anchor_period. Reproduction: observation '2026' or 'FY2026' fails validate_data_anchor for a fiscal_start_month=10 row; only '2025-10-01' is valid. Fix: Recall gap. Decision for the lead or prompt owner: accept 'FY2026' in validate_data_anchor (data layer), or name the start date in the pack.
- **RPT-R3-5** (low, not_fixed): Fan legend for a fan with mixed bases shows only one basis. Location: backend/app/services/report_visualizer.py:_official_fan_label. Reproduction: EIA anchor beyond 2031-07: steps up to about 60 take seasonal_profile and later steps take all_start_months; the legend says 'start months pooled'. Fix: Cautious wording kept on purpose (round-6 precedence). Style-level note.
- **RPT-R2-8** (low, not_fixed): (round 6) Remaining matcher recall gaps. Location: deerflow_bridge/data_catalog.py. Reproduction: As reported in round 6. Fix: Owned by the catalog.
- **RPT-R2-9** (low, not_fixed): (round 6) usgov provider_name for EIA and BEA rows. Location: deerflow_bridge/data_sources.py. Reproduction: data_sources.py was changed at 04:48 by another agent. test_official_data_downstream::test_chinese_snapshot_localizes_its_words_and_keeps_every_figure now fails: it expects 'U.S. Government Open Data' but gets 'U.S. Treasury Fiscal Data'. Fix: Outside my area. The downstream test owner must update the expectation.

Files changed: /Users/rogerlin/Downloads/DeepResearchForecast/backend/app/services/forecast_extractor.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/app/services/report_visualizer.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/app/services/exec_brief.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_forecast_extractor_official.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_report_visualizer_official.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_official_data_agent_usage.py

Tests run: Every run is from backend/ with `.venv/bin/python -m pytest -q -p no:cacheprovider`.
- Owned set baseline (13 files): exit 0.
- Owned set final: 641 passed, 11 xfailed, exit 0 (scratchpad/review3/report/t_owned_final.txt).
- Wider set of 76 files that use the report modules, excluding test_export_demo_site_data.py: 1943 passed, 1 skipped, 11 xfailed, 1 failed (t_wide.txt). The failure is test_official_data_downstream::test_chinese_snapshot_localizes…, caused by another agent's provider_name change in data_sources.py, not by this work.
- Red-before (redplugin/red_before.py with RED=season/fy/subset/rank): 8, 6, 9 and 1 new tests fail when the old behaviour is restored.
- Byte-identity snapshot (snapshot.py, 4,619 outputs): every changed output carries the seasonal_profile marker, and the snapshot is unchanged by the switch to a rank-based share.
- Self-recall probe (842 statements): 638 admitted both before and after the qualifier change.
- Null simulations: raw-share version in null_sim.py, rank-based version in null_sim_rank.py.
- Live FRED, 8 calls in total (the key was never printed): 3 for the seasonal share of CPIAUCNS, UNRATENSA and PAYNSA, then 5 for the raw-versus-rank comparison of UNRATENSA, PAYNSA, CPIAUCNS, RSXFSN and HOUSTNSA.
- Charts rendered with matplotlib and Plotly (scratchpad/review3/report/charts).
- `uvx ruff check --select F,E9 --ignore F401,F841,F541` on the 6 changed files: all checks passed. py_compile: OK.

### r7:frontend

I independently verified the frontend area (frontend/src/**, frontend/tests/**) as the adversarial verifier for round 6. I checked the round-6 reviewer's four fixes and the partial work left by the dead round-6 verifier, did tasks r1, r2 and r3, and looked for defects the reviewer missed.

**Round-6 fixes (FE-1 to FE-4) hold up.** I re-ran the dead verifier's formatter comparison against the current Python data layer: 3,013 values checked across format_value, format_change, scaled_value (en and zh) and round(v, 4), with 0 mismatches. With official data absent, the report and forecast table markup is still byte-identical to HEAD (4 renders, English and Chinese).

**Dead verifier's seasonal-basis display:** the code is coherent. Its fixture was not: under the new contract backend, the same EIA input now produces 'seasonal_profile', so the fixture no longer matched the recipe in its README. I replaced it with a real 'all_start_months' case from a committed carrier (the Monthly Treasury Statement balance at a 13-month horizon).

**r1 (seasonal_profile):** the frontend now accepts the new basis and shows the exact EN/ZH full wording in the base-rate cell and tooltip. The 25 pp flag stays on for it and is off only for 'all_start_months'. It is tested against real backend output for the EIA carrier: profile rate 0%, model 40%, and the backend flags it at +40 pp. A further test reads the backend's wording table, so EN/ZH drift between frontend and backend fails a test.

**r2 (accessible names):** report tile CSV buttons now read 'Download <label> as CSV' / '下载<label> CSV'. In the dossier, each CSV button and each 'Chart' link names its series and geography. When two series share a label (the catalog has four such pairs, e.g. FEDFUNDS and DFF), the series id is appended.

**r3 (fork pipelines):** not a defect, no change. A fork starts with an empty artifact list, but when it reuses the base research it registers 'datasets' and the dataset CSVs. A probe using the real fork() confirmed this, and the dossier already loads the tab when 'datasets' appears on a later status poll.

**Missed defects I found and fixed:**
- The Settings hint said the data-source test takes up to about 80 s; the backend worst case is now 90 s.
- Round-6 'not_fixed' FE-N1 is now a frontend defect. The round-7 backend already writes 'FY2027' in the report tables and settlement sentence for a 2026-10-01 fiscal-year anchor, but the data-anchor cell still showed '2026'. I mirrored the backend's rule, including its FY<start year + 1> rule for fiscal years not yet stored. On 192 standard-date cases (13 of them fiscal-year labels) the output matches the backend exactly.

**Checks:** all frontend unit tests pass (140/140, 0 Vue warnings), and the build into the scratchpad finished with no warnings; frontend/dist was not touched. The 3 backend test files that read frontend files pass (24 tests). All 4 new fixtures regenerate byte-for-byte from the current backend.

Notes: /private/tmp/claude-501/-Users-rogerlin-Downloads-DeepResearchForecast/52225542-51e1-41e1-b738-38d44834da7e/scratchpad/review3/frontend-notes.md (probes are in review3/frontend/probe/).

- **FE3-R1** (medium, fixed): New seasonal_basis 'seasonal_profile' not recognised: no disclosure in the data-anchor cell or tooltip. Location: frontend/src/utils/binaryForecasts.js (SEASONAL_BASES), frontend/src/components/research/BinaryForecastTable.vue (SEASONAL_BASIS_TEXT). Reproduction: The current backend gives the EIA US.COM anchor (probability 0.4) seasonal_basis 'seasonal_profile' with p 0 and flags it at +40 pp. The frontend whitelist dropped that value, so seasonalBasis was '' and nothing was disclosed. The new tests failed before the fix (expected 'seasonal_profile', got ''; expected 1 da-season line, got 0). Fix: Added 'seasonal_profile' to the whitelist, plus the exact EN/ZH full wording in the table. The flag rule is unchanged: off only for all_start_months. Real fixture binary_forecast.eia_nsa_profile.json, plus a test that checks the frontend wording against the backend's EMPIRICAL_SEASONAL_BASIS_TEXT. That test catches a one-character difference.
- **FE3-R2** (low, fixed): Per-series CSV buttons (and dossier Chart links) all had the same accessible name. Location: frontend/src/components/research/ForecastReport.vue (ot-csv), frontend/src/components/research/DossierViewer.vue (dt-file), frontend/src/utils/officialData.js. Reproduction: Server-rendered report: 3 tile buttons named just 'CSV'. Dossier: 8 'CSV' buttons and 8 'Chart ↗' links with the same name. The catalog has 4 (title, geography) pairs that share a label, e.g. 'Federal Funds Effective Rate'/USA. Fix: New helper distinctSeriesNames: uses the label, and appends the series id only when two entries share a label. Names: 'Download <label> as CSV' / '下载<label> CSV' (shows 'Downloading … as CSV…' while busy), and 'Open the <label> chart' / '打开<label>图表'. Tests cover the helper, the report tiles (EN and ZH) and the dossier (EN, ZH and busy state).
- **FE3-R3** (info, not_a_defect): Fork pipelines and the dossier Official Data tab. Location: backend/app/services/pipeline_orchestrator.py fork()/_run/_complete_stage (read only); frontend/src/components/research/DossierViewer.vue. Reproduction: probe review3/frontend/probe/fork_datasets.py: the real fork() (with its background run stubbed), then the research-reuse step the fork's run reaches. The fork's artifacts go from [] to ['dataset_fred_UNRATE.csv','datasets','report'], and the status endpoint returns all of them. Fix: No change. Forks register the shared research's official-data artifacts when they reuse it, so the tab appears. The existing dossier test already covers 'datasets' showing up on a later status poll.
- **FE3-V2** (low, fixed): The dead verifier's all_start_months fixture could no longer be reproduced from its README recipe. Location: frontend/tests/fixtures/official/binary_forecast.eia_nsa_pooled.json (removed), README.md, binaryForecasts.test.mjs, forecastReportOfficialData.test.mjs. Reproduction: review2/frontend-verify/probe/nsa_anchor.py on the current backend prints seasonal_basis: seasonal_profile, p 0.0 for the same input that the fixture records as all_start_months, p 0.6518. Fix: A scan of all committed real carriers found that all_start_months with n >= 30 still occurs for usgov:treasury/mts_deficit at h 13-18. New fixture binary_forecast.mts_nsa_pooled.json: h 13, n 59, p 0.2373, model 0.6, not flagged by the backend. Tests and README updated; the stale file was removed.
- **FE3-N1** (medium, fixed): Fiscal-year data-anchor period read '2026' while the report says 'FY2027'. Location: frontend/src/utils/binaryForecasts.js dataAnchorModel; frontend/src/utils/officialData.js (officialSeriesIndex, new officialAnchorPeriodLabel). Reproduction: probe/fy_fixture.py replays the real USAspending capture into _normalize_binaries. For anchors on 2026-10-01 and 2027-10-01 the backend's official_anchor_period_text and settlement sentence say FY2027 and FY2028, but the frontend cell showed '2026' and '2027'. The new test failed before the fix (expected 'FY2027', got '2026'). Fix: officialAnchorPeriodLabel mirrors the backend rule, including FY<start year + 1> for fiscal years not yet stored. officialSeriesIndex now carries the stored carrier row's provenance, and dataAnchorModel uses it for the period, latest period and base-rate window. Without the report carrier it falls back to the calendar year. 192 standard-date backend cases, 0 mismatches. Real fixtures added.
- **FE3-S1** (low, fixed): Settings hint gave the old 80 s worst case for the data-source test. Location: frontend/src/components/research/SettingsMenu.vue. Reproduction: The hint said 'takes up to about 80 s' / '最长约 80 秒'. Backend _DATA_TEST_MAX_SECONDS = 75+2+5+8 = 90 (asserted by test_settings_data_sources_probe; doctor.sh says ~90s). The new test, which reads those constants from backend/app/api/settings.py, failed before the fix. Fix: Changed the hint to 90 s in EN and ZH, with a test that recomputes the bound from the backend constants.
- **FE3-V1** (info, not_a_defect): Round-6 fixes FE-1..FE-4 and the dead verifier's display of pooled-season rates without a flag. Location: frontend/src/utils/officialData.js, binaryForecasts.js, SettingsMenu.vue, BinaryForecastTable.vue. Reproduction: Formatter comparison against current Python: 3,013 values, 0 mismatches. 25 pp boundary cases match _binary_quality. The live region always exists. An unknown basis is flagged like the backend. HEAD parity without official data: 4 renders identical. Fix: No change needed; confirmed correct.

Files changed: frontend/src/utils/binaryForecasts.js, frontend/src/utils/officialData.js, frontend/src/components/research/BinaryForecastTable.vue, frontend/src/components/research/ForecastReport.vue, frontend/src/components/research/DossierViewer.vue, frontend/src/components/research/SettingsMenu.vue, frontend/tests/binaryForecasts.test.mjs, frontend/tests/forecastReportOfficialData.test.mjs, frontend/tests/dossierOfficialData.test.mjs, frontend/tests/officialData.test.mjs, frontend/tests/settingsDataSources.test.mjs, frontend/tests/fixtures/official/README.md, frontend/tests/fixtures/official/binary_forecast.eia_nsa_profile.json (new), frontend/tests/fixtures/official/binary_forecast.mts_nsa_pooled.json (new), frontend/tests/fixtures/official/binary_forecasts.usaspending_fy.json (new), frontend/tests/fixtures/official/official_data.usaspending_fy.en.json (new), frontend/tests/fixtures/official/binary_forecast.eia_nsa_pooled.json (removed: stale, untracked)

Tests run: - `npm --prefix frontend run test:unit`: 131/131 at start, 140/140 at the end, 0 failures, 0 Vue warnings (scratchpad/review3/frontend/unit_final.txt). 9 new tests, each red before its fix (except the parity guards, which were mutation-checked).
- `npm --prefix frontend run build -- --outDir scratchpad/review3/frontend/fe-dist-final --emptyOutDir`: exit 0, no warnings; frontend/dist was not touched.
- HEAD vs working-tree parity without official data (review2/frontend/parity_absent.mjs): ok, 4 renders.
- Backend tests that read frontend files (`.venv/bin/python -m pytest -p no:cacheprovider tests/test_report_zh_presentation.py tests/test_settings_data_sources_probe.py tests/test_spa_serving.py`): 24 passed.
- Read-only probes, no network and no LLM calls:
  - fmt_fuzz: 3,013 values, 0 mismatches;
  - fork_datasets.py: fork registers 'datasets';
  - nsa_profile.py and mts_pooled.py: real seasonal_profile and all_start_months outputs;
  - basis_scan.py: all committed carriers;
  - fy_anchor.py and fy_fixture.py: 240 backend fiscal-year period cases, 0 mismatches on standard dates;
  - all 4 new fixtures regenerate byte-identically from the current backend.
- ruff was not run: no repository Python file changed.

### r7:verify-downstream

I verified the downstream reviewer-fixer's work. Its one fix (DS7-E2E-1) holds, and I agree with its not_a_defect calls on (a), (b) and (c). I found and fixed three more defects in the downstream area; each fix comes with a regression test that failed before the fix.

1. **DSV-1:** the area's own test was failing. The concurrent data-area change (USGOV_PUBLISHERS in data_catalog.py, edited 04:52) names the publishing agency on usgov rows. Snapshot source cells now read 'U.S. Treasury Fiscal Data [S8]' and 'USAspending.gov [S7]'. I checked the new output with a probe and updated the two Chinese-snapshot expectations in test_official_data_downstream.py.
2. **DSV-2:** canonical world briefs could lose a claim's labels. When official data shares a canonical v1 brief, the fair-share trimming cut a public evidence line mid-sentence with '…'. That dropped its '[contested; not established fact]' label and/or its '[sources=…]' binding, which the canonical contract requires every shared row to keep. A probe found 40 such cuts across English and Chinese runs, claim counts and lengths. The fix adds a whole_lines mode, used only by the canonical caller: lines that do not fit are skipped, never cut.
3. **DSV-3:** Chinese briefs lost whole clauses. A Chinese situation paragraph was cut back to its last space, giving '截至 2026 年 9…' (12 characters out of 60+ of room). Chinese text has spaces only around numbers and Latin words, so the last space can be far back. A Latin word inside Chinese prose could also be split mid-word ('，Fed…'). The fix drops only a split trailing word and treats CJK characters as boundaries.

Both trimming fixes run only when official data is present, so briefs without official data stay byte-identical.

I re-ran the guarded end-to-end runner after the catalog change: it passes. watch_rows all end '[S1] |', dangling is [], and the count is 2 chart captions + 10 watch rows.

Things checked and found correct:
- D2 (degrade on capture or bind failure; ResearchBindingConflict re-raised). The fix plan's invariant §0.1 overrides the verdict's suggestion to keep the in-memory/disk mismatch fail-closed. Unbound is the same as the behaviour before simulations were bound to research.
- The seed binding path is unchanged and still fail-closed, but a failed seed is skipped and never fails the run.
- D3 relocation and schema 1/2 bindings. The realpath change in handoff_dir does not affect report_agent, which reads only pipeline_id and files.
- D4/D5 budgeting and cutoff.
- L10 merge.
- _dataset_artifact_specs.
- The monitor's _anchor_period_bounds and pending/manual statuses; data_* summary rows appear only when official statuses exist.
- forecast_ledger.official_data_track_record.
- Settings probe API signatures and bounds.
- doctor.sh help line range (3-34) and the guarded_runner marker registration.
- check_env_drift --strict.

The reviewer's OBS-1 (agent_usage outside-view test) now passes; the report area fixed it meanwhile. No live provider calls and no LLM calls. Nothing staged or committed.

Notes are in scratchpad/review3/downstream-verify-notes.md; probes and logs are in scratchpad/review3/downstream-verify/.

- **DSV-2** (medium, fixed): Canonical v1 world brief with official data cuts a public evidence line mid-sentence, dropping its contested label and source binding. Location: backend/app/services/simulation_config_generator.py:_fit_official_brief / _trim_brief_part (called from _build_canonical_public_world_brief). Reproduction: probes/probe_canonical_trim.py runs real packs from _produce_and_validate with 1-8 contested public claims of 120-300 chars, a real 8-series carrier and max_chars 1400, in English and Chinese. It found 40 brief lines like '- Alpha Systems / knowledge_state: CLAIM2 word0 … word37…' that have neither '[contested; not established fact]' nor '[sources=…; as-of=…]'. At HEAD the canonical brief only ever kept whole lines, and its docstring says contested rows 'retain their uncertainty label in the brief'. This happens only when official data is present. Fix: _trim_brief_part(text, limit, *, whole_lines=False) and _fit_official_brief(..., whole_lines=False) gained a whole_lines mode: a line that does not fit is skipped, never cut. The canonical caller passes whole_lines=True; the legacy path is unchanged. New test test_canonical_world_brief_denials.py::test_official_snapshot_room_never_cuts_a_canonical_evidence_line[True/False] failed 2/2 before the fix and passes after. It checks that every shared CLAIM line is a whole line from the no-official-data brief and ends with '[contested; not established fact] [sources=…]'. The probe now finds 0 cut lines.
- **DSV-3** (low, fixed): Legacy Chinese world brief with official data cuts a situation paragraph back to its last space ('截至 2026 年 9…'), losing nearly all of it. Location: backend/app/services/simulation_config_generator.py:_trim_brief_part (cut branch). Reproduction: probes/probe_zh_situation2.py builds a Chinese legacy brief from a real 9-series carrier and a situation_brief paragraph '截至 2026 年 9 月，美国通胀持续回落，' + Chinese sentences, with max_chars 1400 or 2000. 7 sweep cases end the paragraph at '截至 2026 年 9…' (12 characters) even though there were 60 or more characters of room. head.rsplit(None, 1) cuts back to the LAST space, and Chinese prose has spaces only around numbers and Latin words. A Latin word right after Chinese text was also split mid-word ('…表示，Fed…'). This happens only when official data is present. Fix: The cut now drops only a word that the cut actually splits: a trailing run of non-space, non-CJK characters, and only when the next character continues that run. CJK and full-width characters count as boundaries, so Chinese is cut at the character. English results are unchanged except that a complete last word is no longer dropped. New test test_official_data_downstream.py::test_chinese_situation_brief_is_cut_at_a_character_not_back_to_its_first_space failed before the fix ('截至 2026 年 9…') and passes after. It covers the brief-level scenario, a 200-character Chinese cut, a Latin word inside Chinese and the English word-boundary cut. test_official_data_agent_usage's existing English and Chinese trim tests still pass.
- **DSV-1** (low, fixed): The area's Chinese-snapshot test was failing after the concurrent data-area per-recipe usgov provider_name change. Location: backend/tests/test_official_data_downstream.py:531,537. Reproduction: Baseline run of the 11 area files (verify baseline.txt): test_chinese_snapshot_localizes_its_words_and_keeps_every_figure failed. The source cell now reads 'U.S. Treasury Fiscal Data [S8]' instead of 'U.S. Government Open Data [S8]', because data_catalog.USGOV_PUBLISHERS (04:52) names the publishing agency. probes/probe_zh_lines.py confirmed the English and Chinese outputs: 'U.S. Treasury Fiscal Data [S8]' and 'USAspending.gov [S7]'. The data verifier's notes record this as the expected result of its change. Fix: Updated the two expectations to 'U.S. Treasury Fiscal Data [S8]' and 'USAspending.gov [S7]'. The test passes.
- **DS7-E2E-1** (medium, fixed): (reviewer fix, verified) The guarded end-to-end test's [S1] count now includes the 'Official series to watch' rows. Location: backend/tests/test_official_data_end_to_end.py:290. Reproduction: Re-ran the guarded runner after the catalog change and again after my changes: 1 passed (e2e.txt), then 32 passed together with the canonical tests (e2e2.txt). In the evidence full_report.md, 2 chart captions and 10 watch-table rows end in '[Source](<url>) [S1] |', and the References list one S1. Fix: Agree with the reviewer's assertion: counts == {S1: len(official) + len(watch_rows)}, dangling == [], and 10 watch rows ending '[S1] |'.
- **DS7-A/B/C** (info, not_a_defect): (reviewer not_a_defect, re-decided) Chinese snapshot language; legacy per-thread budget and FRED pacing docs; data-source probe bound of about 90 s. Location: backend/app/services/official_data.py; .env.example:502-520; backend/app/api/settings.py. Reproduction: (a) The Chinese snapshot tests pass. Any language other than zh/Chinese/中文 gives the English text. (b) data_tools._limit is min(40, max(0, int)) and falls back to the default on ValueError, matching the .env text. (c) The McpHub.start/close, DataSources.get_many/providers APIs and the route field all exist with the signatures settings.py uses. Bound: 75 + 2 + 5 + 8 = 90 s, under the 120 s frontend timeout. The guarded runner controls pass (24 passed). Fix: No change needed.
- **D2-degrade-scope** (info, not_a_defect): Capture and bind degrade the in-memory/disk mismatch too, although the verdict suggested keeping it fail-closed. Location: backend/app/services/pipeline_orchestrator.py:12851-12857, 13366-13380. Reproduction: In the code, `except Exception` around capture_research_generation and around bind_simulation_research catches everything except ResearchBindingConflict. Fix: The fix plan's invariant §0.1 is binding and wins over the verdict: integrity checks degrade to 'official data unavailable' with a recorded reason. An unbound simulation gets official_data None and the pipeline dossier lookup, which is the behaviour before binding existed. The seed path (_run_one_seed) stays fail-closed, but a failed seed is skipped and never fails the run.
- **DOC-1** (info, not_fixed): Doc nits: DATA_SOURCES_MAX_SERIES ranking text omits 'anchored first'; doctor.sh header still says '~15s gate'; DATA_SOURCES_MAX_SERIES=0 is handled differently in each layer. Location: .env.example:517-518; backend/app/config.py:1496-1499; scripts/doctor.sh:15-17. Reproduction: data_sources.load_official_data ranks anchored > cited > KIQ-linked > rest, but the .env and Config comments list only 'cited > KIQ-linked > rest'. With the out-of-range value 0, Config clamps to 1, the data layer uses 24 and v3 dataset_cap uses 0. Fix: Style or documentation only, left as is under the rules. Suggested wording: '锚定 > 研究报告引用 > 关键问题关联 > 其余'.

Files changed: /Users/rogerlin/Downloads/DeepResearchForecast/backend/app/services/simulation_config_generator.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_canonical_world_brief_denials.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_official_data_downstream.py

Tests run: All runs from backend/ with .venv/bin/python -m pytest -q -p no:cacheprovider unless noted. Logs are in scratchpad/review3/downstream-verify/.
- Baseline, 11 area files: EXIT=1, with 1 failure (DSV-1) caused by the concurrent catalog change (baseline.txt).
- DSV-1: after the expectation update, `-k chinese` passes.
- DSV-2: the new canonical test failed 2/2 before the fix and passes after. probe_canonical_trim.py went from 40 cut lines to 0.
- DSV-3: the new downstream test failed before the fix and passes after. probe_zh_situation2.py showed 7 cases of '截至 2026 年 9…' before the fix.
- Wide run of 30 files after both fixes, EXIT=0 (wide1.txt): the area files plus official_data_agent_usage, forecast_ledger, resolution_monitor, settings_endpoint_fallback, settings_provider_info, simulation_config_seal, actor_context_runtime, audit_fixes_prepare, calendar_event_bucketing, prompt_injection_boundaries, sim_context_persona, sim_config_v1_provenance, sim_reaction_phase, temporal_mode_contract, sessionb_sim_additivity, sim_config_incentives, sim_market_priors, sim_realism_item20 and actor_role_prompt.
- Final run of 18 files, EXIT=0 (final.txt).
- Guarded runner (`backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir <scratch> --allow-python-script backend/tests/fixtures/official_data_mcp.py --allow-python-script deerflow_bridge/skills/data-visuals/scripts/render_data.py -q ...`):
  - test_official_data_end_to_end: 1 passed after the catalog change (e2e.txt).
  - e2e + canonical: 32 passed after my fixes (e2e2.txt).
  - test_main_offline_runner + test_deployment_sidecar_control_flow: 24 passed (runner.txt).
- `uvx ruff check --select F,E9 --ignore F401,F841,F541` on the 3 changed files: all checks passed.
- `check_env_drift.py --strict`: EXIT=0.
- No live provider calls, no LLM calls, nothing staged or committed.

### r7:integration-gate

I ran the whole-tree integration gate on the round-7 tree. Once three cross-area defects were fixed, the tree passes every gate. Each defect was reproduced first with failing tests, then fixed minimally.

**Final evidence (scratchpad/review3/gate/):**
- Full backend suite (full3.txt): 5970 passed, 22 skipped, 11 xfailed, 2 failed. The 2 failures are the accepted demo-asset tests in test_export_demo_site_data.py.
- The first run (full.txt) had one more failure: test_official_data_downstream::test_chinese_snapshot_localizes_its_words_and_keeps_every_figure (data-r1 per-recipe provider_name × a downstream test that expected the old name). The concurrent downstream verifier fixed it at 05:06 (DSV-1); I did not touch that file.
- Frontend: 140/140 unit tests pass; the build to a scratch outDir succeeds with no warnings.
- Static checks:
  - ruff F,E9: clean on all 59 changed or new .py files.
  - compileall: exit 0.
  - check_env_drift --strict: exit 0.
  - init.sh: exit 0 (read first; it only runs compileall and a node check).
- The guarded-runner e2e passed twice (1 passed, exit 0), the second time after my fixes.

**Seams checked:**
- **Seasonal basis:** backend and frontend agree with the contract. Same three values, exact EN/ZH full and short wording. The 25 pp flag is off only for all_start_months, on both sides.
- **Per-recipe provider_name:** every consumer reads the stored row field: report_agent, report_visualizer, exec_brief, the official_data snapshot (split at ' ('), the v3 and legacy quantitative rows, and the frontend's officialData.js and vizManifest.js. Sources use the domain or series_label, so they are unaffected.
- **FY anchor label:** the backend period cases are identical to the ones the frontend verifier used. Frontend vs backend: 0 mismatches on canonical dates.
- **Frontend fixtures:** all 4 round-7 fixtures regenerate byte for byte from the fixed backend.
- **Official data disabled:** a scripted v3 run matches HEAD in rc, model-call count, tools, artifact keys and log. The only differences are thread-order [S#] numbering and phase timings.
- **DATA-R7-1 partial first month:** data_sources, render_data and forecast_extractor agree on the partial month.
- **Diff scan:** no TODO/FIXME, no debug prints (the data_catalog CLI prints are intentional), no absolute scratch or home paths. Every .env credential value was checked against all 267 changed or untracked files and the diff, without printing any value: 0 hits.

**Defects fixed:**
- **GATE-1:** catalog r4 made 'european central bank' an ECBDFR keyword, and the anchor matcher uses every multi-word keyword as a metric name. ECB main refinancing and marginal lending statements were then admitted on ECBDFR (BIS XM already had this). Fixed with sibling-rate qualifiers.
- **GATE-2:** r3's generic 'headline inflation' / '整体通胀' names let PCE, PPI, producer-price and wholesale headline-inflation statements anchor on CPI-family rows. '整体通胀' also took the 通胀 of 通胀预期, so inflation-expectations statements anchored too. Fixed with a price-measure check (either spelling of the measure allowed when the row's names carry it) and a (?!预期) lookahead.
  - Probe evidence: only the sibling statements flip; the report's self-recall probe (842 statements, 638 admitted) is byte-identical before and after; the PPI-row guard statements are unchanged.
- **GATE-3:** this is the v3 reviewer's cross-area item (a). Legacy data_tools._window_note lacked V3-WIN-2's projection_from clause. Parity probe over 77,760 cases: 2,880 mismatches before the fix, 0 after.

**Noted, not fixed (not combined-change seams):**
- BIS US CBPOL's 'federal reserve' keyword admits 'Federal Reserve discount rate' statements (probes/fed_sibling.py). This existed before round 7 and is the same pattern as GATE-1.
- report_agent._official_provider_label falls back to the gateway name for usgov rows that have no stored provider_name.
- The doctor.sh header still says '~15s'.
- DATA-R7-2 (bis:WS_CBTA marked strong for central-bank rate questions) needs a scoring decision.
- New fixtures carry relative 'scratchpad/...' provenance text (not machine paths).

Notes: /private/tmp/claude-501/-Users-rogerlin-Downloads-DeepResearchForecast/52225542-51e1-41e1-b738-38d44834da7e/scratchpad/review3/gate-notes.md. I did not stage or commit anything and made no LLM or provider calls.

- **GATE-1** (medium, fixed): Catalog r4 keyword 'european central bank' on fred:ECBDFR made ECB main-refinancing / marginal-lending statements anchor on the deposit facility rate. Location: backend/app/services/forecast_extractor.py _ANCHOR_QUALIFIER_RE (with deerflow_bridge/data_catalog.py ECBDFR keywords). Reproduction: probes/ecb_anchor.py (OLD=1 strips the r4 keywords). Statement 'The European Central Bank main refinancing rate is below 2% in December 2027.' with data_anchor fred:ECBDFR: dropped before r4, ADMIT after. Same for 'marginal lending facility rate'. BIS XM was already affected (EN and ZH 欧洲央行主要再融资利率). Red: 4 of 6 new RECALL_CASES in test_official_data_agent_usage.py (q4_ecb_dfr) failed before the fix. Fix: Added refinancing|marginal[\s-]+lending|再融资|边际贷款|边际借贷 to the sibling qualifiers: a statement may use one only when the anchored series' own names carry it. The new cases pass. The ecb probe flips only the 4 sibling statements. Self-recall probe (842 statements / 638 admitted) is byte-identical.
- **GATE-2** (medium, fixed): Catalog r3 generic 'headline inflation'/'整体通胀' names let PCE/PPI/producer-price/wholesale headline inflation and 整体通胀预期 anchor on CPI-family rows. Location: backend/app/services/forecast_extractor.py _anchor_metric_spans and _anchor_foreign_qualifier (new _ANCHOR_PRICE_MEASURES). Reproduction: probes/pce_anchor.py (OLD=1 strips r3 keywords) on BIS US/XM CPI and WEO PCPIPCH/USA. 'US PCE headline inflation is below 2.5% in December 2027.', 'US producer price headline inflation ...', '... as measured by the PCE price index ...', '美国PCE整体通胀...', '美国PPI整体通胀...' and '美国整体通胀预期...' are dropped before r3 and ADMIT after. Red: 6 of 10 new RECALL_CASES failed before the fix. Fix: CJK labels ending in 通胀 get a (?!预期) lookahead, so they never take the 通胀 of 通胀预期. Added a price-measure check (PCE / personal consumption expenditures / 个人消费支出; PPI / producer prices / wholesale / 生产者价格 / 出厂价格 / 批发) that is allowed when the row's names carry either spelling. Plain headline wordings stay admitted (r3 intent kept). The PPI-row guards are unchanged and self-recall is identical.
- **GATE-3** (low-medium, fixed): Legacy data_tools._window_note lost parity with the gateway after V3-WIN-2 (no 'not refetched' note for a projection path stored only through the retrieval year). Location: deerflow_bridge/data_tools.py _window_note. Reproduction: New test test_legacy_official_data.py::test_a_projection_path_stored_to_the_retrieval_year_notes_a_later_end uses the real WEO row trimmed to 2026: data_get end=2026, then end=2028, returns the stored page with no note (failed before the fix). Parity probe probes/window_parity2.py: 2,880 of 77,760 legacy-vs-v3 decisions mismatched before the fix. Fix: Added _PROJECTION_END_YEARS = 6 and the gateway's clause to cut_short: projection_from and held_end < (retrieval year + 6)-12-31. Docstring updated. The parity probe shows 0 mismatches; the 5 data_tools test files pass (223 passed).
- **DATA-R7-3/DSV-1** (low, fixed): Downstream zh snapshot test hard-coded the old usgov gateway name after data r1. Location: backend/tests/test_official_data_downstream.py:531,537. Reproduction: Full suite #1: test_chinese_snapshot_localizes_its_words_and_keeps_every_figure failed (source cell is now 'U.S. Treasury Fiscal Data [S8]'). Fix: Fixed at 05:06 by the concurrent round-7 downstream verifier (DSV-1). I confirmed it passes in full suites #2 and #3 and did not edit the file.
- **GATE-N1** (low, not_fixed): Pre-existing analog of GATE-1: BIS US CBPOL keyword 'federal reserve' admits 'Federal Reserve discount rate' / 'interest rate on reserve balances' statements. Location: backend/app/services/forecast_extractor.py qualifier lists / deerflow_bridge/data_catalog.py BIS US keywords. Reproduction: probes/fed_sibling.py: all three statements ADMIT on bis:WS_CBPOL/M.US. Fix: Not a combined-change seam (it predates round 7), so it is out of the gate's scope. Suggested: add 'discount rate' and 'reserve balances'/'IORB' to the sibling qualifiers.
- **GATE-N2** (low, not_fixed): report_agent._official_provider_label fallback uses the usgov gateway name for rows without a stored provider_name. Location: backend/app/services/report_agent.py:3006. Reproduction: Code reading only. Every stored Series carries provider_name, so this only affects hand-made rows. Fix: Style/consistency only: the fallback could call catalog.provider_name(provider, native).
- **GATE-N3** (info, not_a_defect): Accepted pre-existing failures. Location: backend/tests/test_export_demo_site_data.py. Reproduction: 2 demo-asset failures in every full run; another session deleted the demo assets. Fix: Accepted per the task.

Files changed: /Users/rogerlin/Downloads/DeepResearchForecast/backend/app/services/forecast_extractor.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_official_data_agent_usage.py, /Users/rogerlin/Downloads/DeepResearchForecast/deerflow_bridge/data_tools.py, /Users/rogerlin/Downloads/DeepResearchForecast/backend/tests/test_legacy_official_data.py

Tests run: All paths below are under scratchpad/review3/gate/.
- Full backend suite, three runs (`.venv/bin/python -m pytest -q -p no:cacheprovider`):
  - full.txt: 5949 passed, 3 failed (2 accepted demo-asset failures + DATA-R7-3, later fixed by DSV-1).
  - full2.txt: 5969 passed, 2 failed.
  - full3.txt (final, with all fixes): 5970 passed, 22 skipped, 11 xfailed, 2 failed (only the accepted test_export_demo_site_data failures).
- Frontend: `npm --prefix frontend run test:unit` 140/140, run twice. `vite build --outDir scratch` exit 0, no warnings.
- Guarded runner `main_offline_pytest.py ... test_official_data_end_to_end.py`: 1 passed, exit 0, run twice (e2e.txt, e2e2.txt).
- ruff F,E9 on all 59 modified/new .py files: clean. compileall (scratch pycache prefix): exit 0. `check_env_drift.py --strict`: exit 0. `bash init.sh`: exit 0.
- Targeted test runs:
  - 26 test files touching forecast_extractor: 1142 passed, exit 0 (fe_run2.txt).
  - 5 data_tools test files: 223 passed, exit 0.
  - New recall cases and the new legacy test: red before each fix, green after.
- Probes (probes/):
  - ecb_anchor.py, pce_anchor.py, ppi_guard.py; the report's probe_selfrecall.py (842/638, identical).
  - window_parity2.py: 0 of 77,760 mismatches; 2,880 with the pre-fix legacy rule.
  - fy_parity.mjs: 0 canonical mismatches.
  - partial_seam.py.
  - v3 diff_disabled.py vs HEAD baseline.
  - fixture regeneration: 4/4 byte-identical.
  - secret_scan.py: 0 hits, values never printed.

