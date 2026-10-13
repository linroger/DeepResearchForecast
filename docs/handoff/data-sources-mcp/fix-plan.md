# Fix contract — official-data integration review of eac717b (2026-10-12)

Binding for every fix agent. It supplements `design.md` and
`docs/handoff/main-quantitative-integration-20261012/integration-contract.md`;
where they disagree, THIS file wins. Finding ids refer to the review files in
the session scratchpad (`review/*-findings.md`, `review/report-findings-from-journal.md`,
`review/lead-findings.md`) and their adversarial verdicts (`review/*-verify.md`).

## 0. Non-negotiable invariants

1. A data problem never fails a research run, a pipeline, a report or a
   simulation. Integrity checks degrade to "official data unavailable" with a
   recorded reason; they never raise into a stage.
2. Prompts, tool lists and artifacts are byte-identical to today when official
   data is disabled or absent (prove with a test where you touch a prompt).
3. v3 prompt-cache layout: ENGINE_CORE static (no `$`, `{`, dates), one tools
   object per run, volatile text only in the last message, digest built once.
4. Stored observations are authoritative; model-transcribed numbers never
   override them. Projections/estimates/unknown-status values are never
   presented or verified as observed history.
5. Secrets: never logged, never in tool text; redact only real credentials.
6. Plain `cd backend && .venv/bin/python -m pytest` (the CI path) must pass.
   Never import `deerflow_bridge` as a package in tests; use the bare-name
   `sys.path` convention (see tests/test_research_gateway.py:28-32).
7. Tests use captured REAL payload shapes, not invented ones, wherever a
   provider shape matters (captures live in the review scratch dirs; commit
   trimmed copies under `backend/tests/fixtures/data_sources/real/`).
8. Stage only your own files; never `git add -A`; do not commit (the lead
   commits). Do not touch other sessions' files (root handoff.md,
   .zcodeignore, backend/uv.lock, docs/handoff/codebase-study*, docs/demos
   deletions).

## 1. Shared interfaces (owners in brackets)

### 1.1 `DataError` taxonomy [data layer]
`DataError(series: str, message: str, retryable: bool = False, code: str = "provider_error")`
with `code` ∈ {`invalid_input`, `invalid_window`, `unsupported_transform`,
`unknown_series`, `unknown_recipe`, `rate_limited`, `quota_exhausted`,
`key_invalid`, `provider_unavailable`, `not_found`, `timeout`,
`persistence_failed`, `provider_error`}. `message` is agent-facing, ≤ 300
chars, redacted, and ends with a short actionable hint. `retryable=True` for
rate limits, timeouts, 5xx and transient transport errors. Consumers MUST NOT
cache retryable failures and MUST show `code` + `message` to the agent:
`DATA_UNAVAILABLE[<code>]: <message>`.

### 1.2 Catalog entry fields [catalog] → consumed by [data layer]
`CatalogEntry` gains (all optional, defaults keep current behaviour):
- `native_unit: tuple[str, int] | None` — pinned (native unit code, unit multiplier) verified live; when present the adapter requires exact equality and returns `entry.units` (never the native label).
- `native_dims: Mapping[str, str]` — pinned key dimensions (e.g. BIS `UNIT_TYPE: "770"`, `CURRENCY: "USD"`, WS_XRU `COLLECTION: "A"`).
- `aggregation: "avg" | "eop" | ""` — how native-daily data becomes monthly (`eop` for stocks and policy targets, `avg` for prices/yields).
- `status_policy: "" | "history_only" | "weo_vintage" | "gep_vintage"` — deterministic status rules for providers whose feeds strip status (§1.4).
- `fred_equivalent: str` — FRED id carrying the same series (BLS headline ids) for quota/outage hints.
- `preferred: str` — a faster/equivalent catalog id to route to (e.g. `imf:PCPS/...COPP` → `fred:PCOPPUSDM`; `imf:WEO/<cc>...` → `wb:IMF_WEO_...`).
- `min_start: str` — earliest valid start (USAspending 2007-10-01).

### 1.3 Display helpers [data layer]
- `series_label(series_or_row, lang="en") -> str`: curated title (zh: `title_zh`) plus " — <geography name>" when the geography is not already in the title. Every consumer that shows a series to a model or reader uses it (digest, KIQ briefs, ledger/References titles, baseline tables, packs, charts, snapshots).
- `observation_kind(obs, series) -> "observed"|"preliminary"|"estimate"|"projection"|"unknown"|"partial"` public wrapper; `partial` = an aggregated period not fully covered.
- `latest_observed(series) -> Observation | None` (excludes partial/projection/estimate/unknown).
- `format_value(value, units)`: percent-like units keep up to 3 decimals without trailing zeros (3.875 → "3.875%", 4.2 → "4.2%"); levels ≤ 4 significant decimals; `format_change(delta, units)` renders percent-unit changes as "pp".
- `scaled_value(value, units) -> str | ""`: "≈ 40.27 trillion U.S. dollars" companion for |value| ≥ 1e9 when the units carry no scale word.

### 1.4 Status semantics [data layer]
- WDI (`status_policy="history_only"`): periods before the retrieval year → `observed` (provenance `status_basis="WDI publishes history only"`).
- WEO/GEP (`weo_vintage`/`gep_vintage`): vintage year V = the explicit vintage flow year, else the release year from metadata, else the retrieval year; years ≥ V → `projection`, V−1 → `estimate`, earlier → `observed`; set `projection_from`. `resolution_safe` stays False for WEO/GEP.
- Daily→monthly: a month fully covered and ended before retrieval is complete (`observed`); the current month is `partial`. Provenance keeps `latest_daily {date, value}`.
- Projection families default `end` to retrieval date + 6 years when the caller passes none.

### 1.5 Dataset rows and run caps
- `Series.kiqs` is set by the requesting producer (v3 tools: requesting KIQ id; prefetch: needing KIQ ids).
- Run dataset cap = `ToolLimits.max_datasets` per preset (quick 10, standard 16, deep 24; env `DATA_SOURCES_MAX_SERIES` overrides); v3 prefetch ≤ 60 % of it.
- `load_official_data(handoff, max_series=None)` reads `DATA_SOURCES_MAX_SERIES` (default 24) and ranks rows: anchored > cited in the research report > KIQ-linked > prefetch-only, then manifest order; it records dropped ids in the returned carrier (`"omitted": [...]`).

### 1.6 Deterministic quantitative rows (v3 and legacy finalize)
For each stored dataset, append to `quantitative.json` one row
`{metric: series_label, series, value: latest_observed.value, unit, as_of_date,
period_end, value_type: "actual", geography, source: provider_name, source_url,
source_ref: "S<n>", source_origin: "official_data", dataset_file}` (and one
`value_type: "forecast"` row per publisher projection year, labelled with the
publisher), replacing LLM rows with the same `series`. `actors.json
forecast_inputs.indicators` gains `{indicator, series, latest_value,
latest_date, units, frequency, source_ref}` per dataset.

### 1.7 Report carrier persistence [report agent]
`generate_report` writes `reports/<id>/official_data.json` (the exact carrier
used + `sha256`); `GET /api/report/<id>/official-data` serves it (publication
gate as other report artifacts). Frontend consumes it.

### 1.8 Empirical base rate [forecast extractor]
For each validated `data_anchor`: `empirical_base_rate = {p, n, h, window,
method: "empirical_h_step", sigma_distance}` from historical observed points
only (≥ 30 h-step samples else omitted). Shown in prompts as the outside
view, in Part 1/resolution/exec-brief tables, and as a quantile fan on detail
charts.

## 2. Ownership (one owner per file)

| Slice | Files |
|---|---|
| A data layer | deerflow_bridge/data_sources.py, deerflow_bridge/data_mcp.py, backend/tests/test_data_sources*.py, backend/tests/test_data_mcp*.py, backend/tests/fixtures/data_sources/**, backend/scripts/datamcp_smoke.py |
| B catalog + data-sources skill | deerflow_bridge/data_catalog.py, deerflow_bridge/skills/data-sources/**, backend/tests/test_data_catalog.py |
| C v3 tools | deerflow_bridge/research_gateway.py, backend/tests/test_research_gateway*.py |
| D v3 engine | deerflow_bridge/linear_research.py, backend/app/services/research_progress.py, backend/tests/test_v3_official_data.py, backend/tests/test_research_engine_v3*.py |
| E legacy | deerflow_bridge/deerflow_research.py, deerflow_bridge/data_tools.py, deerflow_bridge/config.yaml, deer-flow/config.yaml (local), deerflow_bridge/skills/deep-research/**, backend/tests/test_legacy_official_data.py, test_loop010*, test_bridge* |
| F research charts | deerflow_bridge/skills/data-visuals/**, backend/tests/test_data_visuals*.py |
| G1 report agent | backend/app/services/report_agent.py, backend/app/services/exec_brief.py, backend/scripts/backfill_report_visuals.py, backend/app/api/report.py, backend/tests/test_report_official_data.py, test_report_data_publication.py |
| G2 forecast math + report charts | backend/app/services/forecast_extractor.py, backend/app/services/report_visualizer.py, backend/tests/test_report_visualizer*.py, test_report_zh_presentation.py, test_forecast_extractor*.py |
| G3 frontend | frontend/src/**, frontend/tests/** |
| H orchestration + downstream | backend/app/services/pipeline_orchestrator.py, backend/app/services/official_data.py, backend/app/services/simulation_config_generator.py, backend/app/services/actor_context.py, backend/scripts/resolution_monitor.py, backend/app/services/forecast_ledger.py, backend/app/api/simulation.py, backend/app/config.py, .env.example, backend/tests/test_official_data_{consumers,downstream,promotion}.py, test_orchestrator_research_wiring.py, test_canonical_world_brief_denials.py |
| T CI + ops + hygiene | backend/app/api/settings.py (data-source test endpoint only), backend/tests/conftest.py, backend/pyproject.toml (markers only), backend/tests/test_main_offline_runner.py, test_deployment_sidecar_control_flow.py, test_official_data_end_to_end.py, test_architecture_characterization.py, scripts/doctor.sh, datamcps/** (hygiene only), datamcps/VENDORED.md, feature_list.json |

Docs (README.md / README.zh-CN.md, agent-progress.txt) are updated by the
lead after all slices land.

## 3. Finding assignment (ids from the review files; apply the verifier's corrected_fix when present)

- **A1 data layer — normalization** (data_sources.py, data_mcp.py): P-UNITS (consume catalog pins; codelist fallback for non-catalog ids; fail closed only on multiplier conflicts), verifier M2 (Data360 IMF_WEO_NGDPD false UNIT_MULT=9: values are whole dollars), V_LST uniform-vintage acceptance, P-WEOSTATUS + MISSED-2 (status policies §1.4), M1/F2/RPT-7/L3 (projection default end), P-DAILY + RPT-6 (complete/partial, latest_daily), P-REDACT, P-SYMLINK (+F9 symlink part), B1, L16/RPT-15/P-SCALE (format_value/format_change/scaled_value), F10/L8 (`_base` keeps curated title; `series_label`), M3 (normalization_policy_version: stored rows re-render byte-identically), P-CACHE/P-NEVERRAISE, G4 data-layer part (load_official_data ranking/cap/omitted), RPT-8 (`Series.kiqs` round-trips), P-TEXT data-layer part (DataError codes), public helpers §1.3, K1 (test import fix in test_data_sources.py), P-FIXTURES (real fixtures).
- **B catalog + skill** (data_catalog.py, skills/data-sources/**): P-UNITS pins + unit corrections (WEO NGDPD stays "U.S. dollars" with pin (USD, 9); WDI growth "Percent change per annum"; credit gap stays "Percentage points of GDP"; LUR "Percent of labor force"), aggregation/status_policy/fred_equivalent/preferred/min_start fields, P-BREADTH (semiconductors, trade/tariffs, Treasury MTS customs duties and tax lines, EIA and BEA recipes — probe the usgov eia/bea tools live with the keys), P-SEARCH (catalog strength score API), P-ZHRANK, P-DIGEST, P-ROUTE, P-SEC (stop advertising SEC), P-BLSQUOTA hints, M5 (non-allowlisted Data360 dbs), L6 (split series-catalog.md under 40k chars per file), SKILL.md guidance refresh, K3 test_data_catalog.py.
- **A2 data layer — providers** (after A1 and B): P-FRED429 (CSV fallback, retryable, pacing), P-FREDCAP (server-side aggregation honouring `aggregation`), P-USGOV (eop stocks, spending min_start clamp, FY complete after +120 d), EIA/BEA usgov adapters for B's recipes, P-SEARCH/P-WBGEO/V3-M2 (search flow), invalid-key fallback (BLS key rejected → respawn bls server keyless; FRED key rejected → CSV route; `providers()` reports `key_invalid`), live smoke script `backend/scripts/datamcp_smoke.py` (paced; BLS ≤ 2 calls).
- **C v3 tools** (research_gateway.py): F9/M4, F11, F13 + V3-M1 (dataset cap per preset, prefetch ≤ 60 %, seeder allowance outside agent totals), F14/P-TEXT consumer (show code + reason; never cache retryable failures), F19, V3-M4 (note when a requested window was not refetched), F20 schema part (descriptions, provider enum, id grammar), RPT-8 producer (set kiqs), F10 (ledger titles via series_label).
- **D v3 engine** (linear_research.py, research_progress.py): F1, F2 (pass horizon where useful), F4, F5, F6/G3 (§1.6), F7, F8, F12, F15, F16, F17, F18, F20 engine part, F22, G7, V3-M3, V3-M4 (base-rate KIQs request longer history).
- **E legacy** (deerflow_research.py, data_tools.py, config.yaml + deployed copy, deep-research references): L1, L2, L4, L5, L7, L10 (bridge part: datasets portable into global synthesis), L11, L12, L14, L15, L17, L20, L21, legacy M1 (retryable not cached; reason classes), legacy M2 (official block in every synthesis prompt), G3 legacy part (§1.6), renderer timeout bounded by deadline.
- **F research charts** (skills/data-visuals/**): L3 (status lanes from the new statuses), L9, L18, L19, downstream M1 (exact WEO/GEP prefixes in render_data.py), series_label titles.
- **G1 report agent** (report_agent.py, exec_brief.py, backfill script, api/report.py): RPT-1, RPT-2 + MISSED-1, RPT-5, RPT-10, RPT-11, RPT-12 backend (§1.7), RPT-13, RPT-14, RPT-16, MISSED-4.
- **G2 forecast math + report charts** (forecast_extractor.py, report_visualizer.py): RPT-3, RPT-4/I1 (§1.8), RPT-6 consumer, RPT-8 (selection), RPT-9, RPT-15, MISSED-2 consumer, downstream M1 (forecast_extractor exact prefixes).
- **G3 frontend** (frontend/src/**): RPT-12 frontend (indicator tiles, anchor column with latest vs threshold and empirical p, gallery attribution), L22 partial (dossier official-data list with CSV links), I4 frontend (Settings data-source test card).
- **H orchestration + downstream** (pipeline_orchestrator.py, official_data.py, simulation_config_generator.py, actor_context.py, resolution_monitor.py, forecast_ledger.py, api/simulation.py, config.py, .env.example): D2, D3, D4, D5, G1, G2/P-SNAP (display-safe vs resolution-safe), G4 (Config knob + ranking callers), G5, G6, I5, L10 orchestrator part, downstream M1 (official_data.py prefixes), downstream M2 (monitor period bounds), orchestrator test fixtures (D1 part).
- **T CI + ops** (conftest, pyproject markers, runner-only tests, characterization test, doctor.sh, api/settings.py data-source test endpoint, feature_list.json): D1/L13/MISSED-3 (plain pytest green: runner-only tests skip unless the guarded runner set MAIN_OFFLINE_EVIDENCE), characterization update, I4 (doctor --deep probe + `POST /api/settings/data-sources/test` → `{providers: {name: {state, detail, latency_s}}}`), DOC2 (feature passes=false until the lead's live verification).
