# Approved quantitative integration contract

Status: implementation authority following the user's approval of PLANS.md on 2026-10-12. This supplements `../data-sources-mcp/design.md`; the existing public signatures and series grammar remain authoritative except for the explicit clarifications below. Workers MUST consult this file and update it through the coordinator before changing shared interfaces.

## Shared module API

`deerflow_bridge/data_sources.py` is the shared, stdlib-only-at-import API. It imports `data_catalog`/`data_mcp` using the same bare-module/package-compatible convention as the bridge. It supplies the prior design's `Observation`, `Series`, `SearchHit`, `DataError`, `DataSources`, `get_data_sources`, `parse_series_id`, `series_stats`, `format_value`, `render_series_page`, `render_series_brief`, `write_dataset_files`, `load_datasets`, and `load_official_data`.

- `Observation(date: str, value: float | None, flag: str = "")`; dates are normalized ISO period starts, finite numbers only, explicit gaps retained. A series also retains `geography` and `vintage` when known; absent metadata remains unknown rather than inferred from the retrieval date.
- `Series` and the other public classes follow design §5.2. `to_dict`/`from_dict` round-trip the normalized schema, and additive metadata has empty defaults for compatibility.
- `DataSources(...).search(...)`, `.get(...)`, `.get_many(...)`, `.providers()`, `.prewarm()`, `.close()` retain design §5.3 signatures. `get` supports both `start` and `end`. Invalid inputs/unavailable provider results return `DataError` instead of leaking exceptions/secrets. Operational errors are explicit and do not become empty successful series.
- `get_data_sources(*, env=None)` remains lazy; importing modules never starts a server or provider request. Add `reset_data_sources_for_tests()` for isolated tests.
- `write_dataset_files(series_list, out_dir, *, citations=None)` atomically writes the series JSON, CSV, then `data/datasets.json`. Rows include `sha256` and `csv_sha256` for the exact persisted bytes. Series identity includes transform, and safe slugs include a deterministic hash suffix when normalization could collide. It returns the manifest object. `citations` maps canonical series IDs to integer source IDs or `S<n>` strings. Callers may carry additive `kiqs` lists.
- `load_datasets(out_dir)` returns manifest rows with loaded observation dictionaries, validating containment, no symlinks, hashes and matching series identity. Missing/corrupt manifests or rows are unavailable; never fabricate data or silently substitute fresh external data. Log a bounded warning for corrupt artifacts.
- `load_official_data(handoff_dir, *, max_series=12)` returns `None` without valid data, otherwise `{schema_version:1,series:[...]}` with at most 240 newest observations per series and the manifest provenance fields. It performs no network calls.

## Tool and citation boundary

V3 keeps `AGENT_TOOLS_SCHEMA` unchanged for disabled data. The enabled schema adds `data_search(query,provider?)` and `data_get(series,start?,end?,transform?)`. Select one stable tools object per run, including final-note and retry turns. Per-agent/global budgets and dedup/singleflight are enforced before provider calls. Search metadata is not fetched evidence. Successful fetches store the exact deterministic dataset page, register one source ledger identity, and expose `[S<n>]` to the requesting/seeded KIQ.

Dataset identity must distinguish transformed series; origin URLs remain human-usable and credential-free. Final citation renumbering updates dataset manifest and captions before sealing. No generic VERIFIED assertion is manufactured merely because a dataset was prefetched: deterministic quantitative statements may be generated only from stored observations and must preserve projection/estimate labels and the existing evidence semantics.

## Research chart boundary

The legacy owner implements `_render_data_charts(out_dir: Path, *, plog=None, question="", lang="en") -> list[dict]` and `_finalize_data_series(out_dir: Path, *, plog=None) -> list[dict]` as in design §9. V3 can call the renderer through `bridge_call` and uses shared dataset persistence directly. Failures yield an explicit bounded diagnostic and no broken image link. Chart paths remain flat `charts/data_<slug>.png` with optional HTML twins; the existing renderer owns only `data_*` rows and preserves all other charts.

## Report boundary

The coordinator supplies `backend/app/services/official_data.py` as the backend import adapter. Backend consumers use its `load_official_data`, `validate_data_anchor`, `resolve_data_anchor`, and `get_data_sources` wrappers; it loads only the fixed repository bridge namespace lazily and does no provider work at import. Report and forecast-extractor owners MUST use `.official_data` rather than adding separate path/import helpers. It also supplies `historical_snapshot(official_data, *, as_of=None, max_series=8, max_chars=3500)` for bounded public context and `load_for_simulation(simulation_id)` for caller lookup.

Resolution helper returns `{status: 'resolved'|'pending'|'manual', reason: str, series: str, observation?: {date,value,flag}, outcome?: bool}`; only resolved includes outcome. Model-supplied latest values or units never override stored metadata. An anchor preserves observation period, comparator and transform; resolution refuses projections and unknown/mismatched units or periods.

`ReportAgent.__init__(..., official_data: dict | None = None)` stores `self.official_data`; absent data leaves existing behavior intact. The orchestrator main report, seed report and manual report API pass `load_official_data(...)` at construction. The agent's context pack and `_collect_viz_artifacts` use this same object. It never fetches from a provider during report generation or publication.

`report_visualizer.build_all` consumes `arts['official_data']`. It renders actual stored historical values, explicit missing gaps and publisher-projection segments, matching units/frequency/seasonality for comparisons. Report-owned visual rows carry source/provenance and follow existing path/manifest rules. Structured forecast `data_anchor` is optional and validated against an available series; thresholds and probabilities are model forecast annotations, visually separated from observations.

## Downstream anchors and snapshots

Shared helper `validate_data_anchor(anchor, official_data) -> dict | None` accepts only known series, finite threshold, comparator in `>,>=,<,<=`, a recognized exact observation period and matching transform/units. It enriches from canonical metadata, not model-supplied values. `resolve_data_anchor(anchor, series, *, as_of=None) -> dict` returns a typed status (`resolved`, `pending`, `manual`) plus reason and observation evidence; projections, absent/mismatched periods or ambiguous metadata cannot resolve a forecast.

Simulation receives only bounded public historical snapshots and retains its current actor-denial/visibility rules and diagnostic forecast policy. Resolution is integrated through existing opt-in/manual mechanisms without activating any schedule or mutating saved runs during development.

## Write ownership

| Owner | Files |
|---|---|
| Actor fix | actor_context.py; test_actor_context_runtime.py; test_actor_roster_producer_consumer.py |
| Dossier fix | DossierViewer.vue; researchTranslation.js and its focused frontend regressions |
| Data API | data_sources.py; test_data_sources.py; optional provider fixtures under a new dedicated fixture directory |
| V3 | research_gateway.py; linear_research.py; dedicated test_v3_official_data.py |
| Legacy/skills | data_tools.py; deerflow_research.py; bridge config.yaml; project data-sources SKILL.md and data-visuals guidance; dedicated legacy tests |
| Report | report_agent.py; report_visualizer.py; forecast_extractor.py; dedicated official-data report/visual tests |
| Verification | main_offline_pytest.py and focused runner controls |
| Coordinator | orchestrator/manual report API wiring; simulation snapshot and resolution/ledger wiring; deployment/config reconciliation; bilingual docs; shared contract and integration tests |

Existing foundation files are not blanket writable. Request a coordinator handoff before altering hub/catalog/renderer APIs or another owner's files. All owners preserve unrelated dirt, use isolated deterministic acceptance, and report red/green evidence and limits. No worker commits, launches a paid model run, resumes saved work or inspects finharness branches.

## Provider fidelity and fiscal periods — 2026-10-12 owner-authorized addition

The Data API owner publishes `resolution_instant(value, date_end=True)` as the public wrapper of the existing UTC parser. The private alias remains compatible. Date-only values use the end of their UTC day when `date_end=True` and midnight when false; ISO timestamps preserve their instant/offset, with unzoned timestamps interpreted as UTC.

Normalized nonempty observation flags are `observed`, `unknown`, `preliminary`, `estimate`, and `projection`. `projection` means an explicitly classified publisher forecast. Preliminary and estimated values are not forecasts. At the data API boundary, BLS raw `P` means `preliminary`, never projection; original provider codes/text remain in `Series.provenance.raw_status`, a mapping from normalized observation date to a list of `{code,text}` objects. Explicit revised/actual/normal statuses normalize to `observed` where the source meaning is established. Unrecognized statuses normalize to `unknown`.

Consumers preserve these five categories. A null numeric value remains a missing gap regardless of its flag. An explicit `unknown`, `preliminary`, `estimate`, or `projection` flag takes precedence over `projection_from`; the cutoff must not turn unknown or preliminary data into a forecast or actual history. Legacy blank flags use `projection_from` when present, otherwise retain the previous observed interpretation only for sources whose fidelity policy permits it. An explicitly observed row conflicting with a publisher projection cutoff is unavailable/unknown, never an observed point. Legacy BLS `P` is preliminary; ambiguous raw `P` from any other source is unknown unless the producer has explicitly mapped it. Historical-only statistics, snapshots and latest-observed annotations exclude unknown, preliminary, estimate and projection values. An exhibit may show them in separately labeled segments; if it cannot retain their distinction it skips them with a bounded diagnostic. No interpolation joins across a missing or omitted-status segment.

Data360 observations, including WDI, normalize to `unknown` because the inspected native handler strips status. USAspending observations are `unknown` because the handler can replace missing amounts with zero. Both retain `resolution_safe=false`. Old cached/persisted generations must not bypass current provider fidelity rules; SEC complete annual/as-of series remain unavailable even when supplied by an older cache or manifest.

Clarification: WB/USAspending provider fidelity overrides legacy blank flags and legacy `projection_from` on both sides of that cutoff. `Series.from_dict` normalizes all their observations to unknown; an unauthenticated cutoff or supplied flag cannot restore status that the native handler discarded. The legacy blank/cutoff fallback above applies only to other providers whose current fidelity policy permits it.

For USAspending `group=fiscal_year`, the canonical per-observation interval is keyed by normalized start date in `Series.provenance.periods`. Every retained observation has the shape below; metadata is trimmed/reordered by date identity, never by parallel list position. `complete` means the query and retrieval cover the entire fiscal interval; it does not certify observation status, vintage availability, or original missingness. `covered_start`/`covered_end` describe the actual requested portion of that interval. `fiscal_start_month=10` remains in provenance. Incomplete periods may be shown only as labeled partial fiscal aggregates and may not be compared with complete annual amounts in growth transforms. Display and captions use `label` (`FY2025`), never the start date's calendar year (`2024`).

```json
{
  "series":"usgov:spending/total",
  "frequency":"A",
  "observations":[{"date":"2024-10-01","value":124.5,"flag":"unknown"}],
  "provenance":{
    "resolution_safe":false,
    "fiscal_start_month":10,
    "native_missingness":"lost; do not resolve",
    "periods":{
      "2024-10-01":{
        "calendar":"us_federal_fiscal_year",
        "label":"FY2025",
        "start":"2024-10-01",
        "end":"2025-09-30",
        "covered_start":"2024-10-01",
        "covered_end":"2025-09-30",
        "complete":true
      }
    }
  }
}
```

This fixture is synthetic. Current request/Series/SearchHit/result signatures stay unchanged. The renderer/report owner implements display/status consumption, and the coordinator implements historical snapshot/monitor consumption. The Data API owner implements producer normalization, artifact/cache admission and period-label persistence.

## Simulation research-generation binding

Before primary or extra-seed PREPARE, the coordinator records `official_research_binding.json` under that simulation directory. It binds the simulation ID and parent pipeline ID to the canonical handoff path and exact hashes of research report, actor/source/dossier files, research seal and dataset manifest (including explicit absence). Rebinding an existing simulation to different research is refused. Manual/report/context lookup resolves this association before scanning primary pipeline IDs. A mismatched or malformed binding yields unavailable enrichment; an old unbound simulation may retain legacy dossier lookup but MUST NOT adopt newly discovered official data without generation proof. The parent primary simulation ID remains unchanged when registering an extra seed. Dataset files retain their existing per-file integrity checks. Canonical actor context still uses its sealed pack-only policy.

Generation binding MUST compare the consumed generation, not recapture a replacement at PREPARE. Full pipelines capture after research finalization/reception and before graph work. Extra seeds inherit the primary simulation binding; changed primary proof rejects the seed before preparation, and legacy unbound parents do not mint new official-data authority. Report/source input checks and before/after fingerprints prevent capture from blessing differing in-memory versus disk inputs.
