# Synthetic provider responses

These deliberately small values are invented test data, not live observations. Shapes follow the actual handlers inspected on 2026-10-12:

- FRED: `src/fred/series.ts` (`getSeriesData`), flat JSON text, current native units/frequency.
- BLS: `src/tools/series.ts` (`get_multiple_series`), unchanged BLS JSON, explicit status and `Results.series`.
- BIS: `src/index.ts` (`fetchDataset`), dynamic SDMX-code rows, exact flow/version, truncation flag.
- IMF: `imf_data_mcp/__init__.py`, parameter definitions and fetch JSON text with nested `params` inputs; fixture dimensions follow the catalog PCPS key and discovered parameter names.
- Data360: `src/data360/api.py` (`get_data`, `_strip_data_row`) and `models.py` (`IndicatorDataResponse`), page cursor and stripped row fields.
- U.S. government: `src/apis/{treasury,usaspending,sec}/tools.ts` plus `src/shared/response.ts`, columnar tables/time series or `record` envelope.

All paths above are relative to the corresponding vendor under `datamcps/`. Source studies and selected-file hashes are in `docs/handoff/main-quantitative-integration-20261012/*-study.md` and accompanying coverage JSON. Fixtures are not evidence of upstream availability or production values.
