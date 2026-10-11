# Design — official data sources (six MCP servers) in deep research and forecasting

Status: v1, 2026-10-11. Binding contract for the implementation agents; every
interface named here is relied on by another slice. Change it only by editing
this file first.

Evidence base: scratchpad `datamcp/notes-{fred,bls,bis,imf,data360,usgov}.md`,
`datamcp/res-mcp-*.json` (live probes of every server) and `datamcp/map_*.txt`
(codebase maps). Scratchpad root:
`/private/tmp/claude-501/-Users-rogerlin-Downloads-DeepResearchForecast/52225542-51e1-41e1-b738-38d44834da7e/scratchpad/`.

## 0. Goals and non-goals

- Research agents (default v3 engine and legacy harness) query the six data
  MCP servers for official quantitative evidence; the workflow plans data needs
  and prefetches a quantitative baseline deterministically.
- Retrieved series are stored, citable (`[S#]`, tier 1), verifiable (numbers
  checked against the stored data page), and charted in the research dossier
  and in the forecast report (history + forecast overlay).
- Downstream: the forecast report gets an official-data pack and charts; binary
  forecasts can anchor to a series (`data_anchor`) and be auto-resolved; the
  simulation world brief gets an official-data snapshot.
- Skills: `data-sources` (how to use the providers) and `data-visuals` (how to
  chart official series; ships the deterministic renderer).
- Non-goals: editing third-party server code in `datamcps/` (zero edits);
  exposing hundreds of raw MCP tools to LLMs; registering raw servers in the
  harness `extensions_config.json` (fragile: always-on cwd loading, all-or-
  nothing tool loss on one crashing server, spawn-failure hang — see
  map_legacy-harness-skills.txt headline findings).

## 1. Invariants (MUST hold everywhere)

1. Nothing fails a run because a data source is missing, unbuilt, keyless,
   slow or broken. Every data API returns a value or a short actionable error
   text; no exception escapes to an engine phase.
2. Default behaviour with data disabled (`DATA_SOURCES_ENABLED=false`, or no
   built server) is byte-identical to today for prompts, tool lists and
   artifacts — except an informational `data_sources` status in meta.
3. Prompt-cache layout of v3 is unchanged: ENGINE_CORE static, brief.md built
   once, digest.md built once, exactly ONE tools-list object per run bound on
   every agent call (`AGENT_TOOLS_SCHEMA` stays exactly `[web_search,
   web_fetch]` and is used when data is off; a new constant
   `AGENT_TOOLS_WITH_DATA_SCHEMA` when on). Volatile data text only in the last
   message.
4. Model-transcribed numbers never become authoritative. Values shown,
   charted, used for anchors/resolution come from stored observations.
5. Secrets: API keys are passed to a server child only through its explicit
   env allowlist; never logged; BLS echoes an invalid key in tool output →
   redact `The key:\S+`. The us-gov server loads `.env` from its CWD → never
   spawn any server with cwd = repo root.
6. Third-party servers in `datamcps/` are run unmodified as separate
   processes. Build outputs are gitignored.
7. Deployment: every new bare-imported bridge module is listed in
   `_DEPLOYED_BRIDGE_MODULES` (pipeline_orchestrator.py), the single-line
   `for _tool_mod in` loop of setup.sh, and init.sh's compile list.
8. Tests are hermetic (no network, no built servers, no node in CI): a fake
   Python stdio MCP server fixture stands in; live checks are separate scripts
   or tests skipped when build outputs are absent.
9. Every new bridge module is importable in BOTH venvs: deer-flow venv (mcp
   1.27, no plotting libs) and backend venv (mcp 1.24, no langchain). Import
   `mcp` lazily (inside functions) so modules import even without it.
10. Chart files are flat `charts/<[A-Za-z0-9._-]+>` (frontend researchChartUrl,
    demo exporter, report chart API); chart titles/alt text/captions are
    digit-free at word boundaries where the report audits scan them, and short.

## 2. Provider registry (who serves what)

| id | server (datamcps/…) | launch | key env | role |
|---|---|---|---|---|
| fred | fred-mcp-server-main/build/index.js | node | FRED_API_KEY (required by server; keyless degrade = fredgraph.csv for observations + catalog metadata) | US macro, labor, rates, energy prices, FX, trade; 800k series; free-text search |
| bls | bls_mcp-main/dist/index.js | node | BLS_API_KEY optional (keyless 25 q/day/IP, 10 y, 25 ids) | US CPI/PPI detail, average prices, payrolls, JOLTS, ECI, LAUS; no search (catalog) |
| bis | mcp-bis-main/bin/cli.js | node (tsx) | none | policy rates, credit/GDP gap, debt service, property prices, FX/REER, CB assets |
| imf | imf-data-mcp-main/.venv/bin/imf-data-mcp | venv console script | none (IMF_APP_NAME=DeepResearchForecast) | WEO vintages, PCPS commodity prices, CPI; SLOW (30-50 s/call) → prefetch only by default |
| wb | data360-mcp-dev/.venv/bin/python -m data360.mcp_server --transport stdio | venv python | none (DATA360_API_BASE_URL=https://data360api.worldbank.org, MCP_ENV=local, FASTMCP_CHECK_FOR_UPDATES=off) | World Bank WDI, IMF WEO (fast route, projections to 2031), WB GEP, emissions, energy; 7-21 s cold start |
| usgov | us-gov-open-data-mcp-main/dist/server.js --modules treasury,usaspending,sec,fdic,federal-register (+eia/bea/census only when their key is set) | node ≥22 | optional per module | US fiscal (debt, MTS deficit, interest rates, Treasury FX), federal spending, SEC fundamentals, FDIC, Federal Register events |

Routing rules: FRED first for US macro/rates/energy prices; BLS for detailed
US price/labor series FRED lacks and as authority; BIS for cross-country
policy rates/credit/property/FX; wb (Data360) for annual cross-country history
and IMF WEO / WB GEP projections; imf for PCPS commodity prices, IMF CPI and
WEO vintage revisions; usgov for Treasury fiscal and spending data and dated
policy events.

## 3. Module `deerflow_bridge/data_mcp.py` — MCP hub (slice A1)

Process-wide, thread-safe stdio MCP client hub. Stdlib-only at import; `mcp`
imported lazily.

```python
@dataclass(frozen=True)
class ServerSpec:
    name: str                     # 'fred' | 'bls' | 'bis' | 'imf' | 'wb' | 'usgov' | test names
    command: str                  # absolute path (node / venv python / console script)
    args: tuple[str, ...]
    env: Mapping[str, str]        # explicit child env additions (keys only when non-empty)
    cwd: str                      # NEVER the repo root; a DRF-owned scratch dir
    start_timeout: float = 45.0
    call_timeout: float = 60.0
    max_concurrency: int = 4
    unavailable_reason: str | None = None   # set by default_server_specs when not runnable

@dataclass
class CallResult:
    ok: bool                      # transport ok AND not isError
    text: str                     # joined text content ("" on failure)
    error: str | None             # short reason (≤300 chars), secrets redacted
    elapsed_s: float
    structured: Any = None        # structuredContent when present
    is_tool_error: bool = False   # server answered isError=True (text holds its message)

def default_server_specs(*, env: Mapping[str, str] | None = None,
                         datamcps_dir: str | Path | None = None,
                         work_dir: str | Path | None = None) -> dict[str, ServerSpec]
    # Resolves DATA_SOURCES_DIR (default <repo>/datamcps found relative to this
    # file in BOTH the source tree (deerflow_bridge/..) and the deployed tree
    # (deer-flow/..)), DATA_SOURCES_NODE (default shutil.which('node'), then
    # ~/.local/bin/node), per-server entry files; marks a spec unavailable
    # (reason "not built: run npm run setup:datamcps" / "node not found" /
    # "node >= 22 required" for usgov) instead of omitting it. Honors the
    # DATA_SOURCES allowlist (comma list, default all six). usgov module list
    # adds eia/bea/census only when EIA_API_KEY/BEA_API_KEY/CENSUS_API_KEY are
    # non-empty. Child env: per-server allowlist (fred: FRED_API_KEY + FRED_*
    # tunables; bls: BLS_API_KEY; imf: IMF_APP_NAME default DeepResearchForecast;
    # wb: DATA360_* fixed values; usgov: its key names + MAX_RESPONSE_BYTES=40000,
    # XDG_CACHE_HOME=<drf cache>, HIDE nothing) — only non-empty values; PATH gets
    # node's directory prepended.

class McpHub:
    def __init__(self, specs: Mapping[str, ServerSpec], *, errlog_dir: str | Path | None = None,
                 clock=time.monotonic): ...
    def start(self, names: Iterable[str] | None = None, *, wait: float | None = None) -> None
        # background prewarm; wait=None returns immediately; wait=s blocks ≤ s
    def status(self) -> dict[str, dict]
        # {name: {"state": "unavailable"|"idle"|"starting"|"ready"|"failed"|"closed",
        #         "error": str|None, "tools": [names], "ready_s": float|None, "calls": int,
        #         "failures": int}}
    def tool_names(self, name: str) -> list[str]
    def call(self, name: str, tool: str, args: Mapping[str, Any], *,
             timeout: float | None = None) -> CallResult   # never raises
    def close(self, timeout: float = 5.0) -> None            # idempotent, kills children
def get_hub(*, env=None) -> McpHub     # process-wide lazy singleton; atexit close
def reset_hub_for_tests() -> None
```

Behaviour: one daemon thread with one asyncio loop; one owner task per server
(enter/exit `stdio_client` + `ClientSession` in the same task; initialize +
list_tools; wait on a close event). Lazy start on first `call`/`start`.
Per-server semaphore. A crashed/failed server: state failed; ONE automatic
restart attempt on the next call after ≥5 s backoff; then calls fail fast with
the recorded error (circuit open) for the rest of the process. Server stderr
goes to `errlog_dir/<name>.stderr.log` (append, created lazily) or devnull —
never to the parent's stdout. Child cwd per spec. Spawn failure must not hang
(guard every await with timeouts; the harness probe saw `asyncio.run` hang in
`_cancel_all_tasks` — our loop is long-lived, so cancel owner tasks with
bounded waits on close). `close()` sets close events, waits ≤ timeout, then
terminates any surviving child process group.

## 4. Module `deerflow_bridge/data_catalog.py` — curated catalog (slice A2)

Pure data + tiny helpers, stdlib only. ≥ 120 entries, every id verified live.

```python
@dataclass(frozen=True)
class CatalogEntry:
    series: str              # canonical fetchable id, see §5 grammar, e.g. "fred:UNRATE"
    title: str               # official title (English)
    title_zh: str            # Chinese title
    units: str               # e.g. "Percent", "Index 1982-1984=100", "Billions of Chained 2017 Dollars"
    frequency: str           # "D"|"W"|"M"|"Q"|"A"
    seasonal_adjustment: str # "SA"|"NSA"|"SAAR"|""
    geography: str           # ISO3 or "WLD"/"USA"/group code
    topics: tuple[str, ...]  # e.g. ("inflation","prices")
    keywords: tuple[str, ...]  # lowercase EN + ZH search terms
    notes: str = ""          # pitfalls (e.g. "ICE: ~3-year history only")
    source_url: str = ""     # human page (citation); derived by data_sources if empty
CATALOG: tuple[CatalogEntry, ...]
def lookup(series: str) -> CatalogEntry | None          # case-insensitive on provider prefix + id rules
def search_catalog(query: str, *, provider: str | None = None, limit: int = 8) -> list[CatalogEntry]
def catalog_digest(question: str, *, limit: int = 40) -> str
    # compact deterministic list for the planner: providers overview + the most
    # relevant entries "fred:UNRATE — Unemployment Rate (Percent, M, SA, USA)"
```

Coverage: macro (GDP, CPI/PCE, core, IP, retail, housing, sentiment, M2),
labor, rates/curve/spreads/breakevens/mortgage, FX/dollar, energy (WTI, Brent,
Henry Hub, gasoline, EU gas, electricity prices where available), commodities
(copper, lithium, cobalt via IMF PCPS), cross-country policy rates/credit
gap/DSR/house prices/REER (BIS), WEO GDP/inflation/unemployment/debt/current
account projections for USA, CHN, JPN, DEU, GBR, IND, EUR area, World (wb route
`wb:IMF_WEO/IMF_WEO_NGDP_RPCH/USA` style), WDI structural (population, GDP
per capita, CO2, electricity use), US fiscal (debt to the penny, MTS deficit,
average interest rate, federal spending), BLS detail (average prices, PPI
final demand with the corrected labels from notes-bls.md).

## 5. Module `deerflow_bridge/data_sources.py` — unified API (slice A5)

Stdlib-only at import (uses data_mcp, data_catalog). This is the ONLY layer
the engines, tools, report side and resolver call.

### 5.1 Series id grammar (agent-facing, one string)

`<provider>:<native>` with provider ∈ {fred, bls, bis, imf, wb, usgov}:
- `fred:UNRATE`
- `bls:LNS14000000`
- `bis:WS_CBPOL/M.US` (flow id / full SDMX key; version resolved via curated list; WS_TC → 2.0)
- `bis:WS_CREDIT_GAP/Q.US.P.A.C`
- `imf:PCPS/G001.POILBRE.USD.M`, `imf:WEO/USA.NGDP_RPCH.A`, `imf:WEO_2026_APR_VINTAGE/USA.NGDP_RPCH.A`, `imf:CPI/USA.CPI._T.YOY_PCH_PA_PT.M`
- `wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA`, `wb:IMF_WEO_NGDP_RPCH/CHN` (indicator id / ISO3; database derived from the indicator prefix)
- `usgov:treasury/debt_to_penny`, `usgov:treasury/mts_deficit`, `usgov:treasury/avg_interest_rate/Treasury Notes`, `usgov:treasury/fx/Euro Zone-Euro`, `usgov:spending/total`, `usgov:sec/<CIK|TICKER>/<us-gaap concept>` (curated recipes keyed by the part after `usgov:`; unknown recipes → error text listing valid ones)

`parse_series_id(text) -> tuple[str, str] | None` accepts surrounding
whitespace/backticks and case-insensitive provider; returns None when invalid.

### 5.2 Data model

```python
@dataclass
class Observation: date: str; value: float | None; flag: str = ""   # ISO "YYYY-MM-DD" (period start), flag e.g. "P","projection"
@dataclass
class Series:
    series: str            # canonical id "fred:UNRATE" (+ "#yoy" suffix when transformed)
    provider: str          # fred|bls|bis|imf|wb|usgov
    provider_name: str     # "FRED (Federal Reserve Bank of St. Louis)" etc.
    title: str; title_zh: str
    units: str             # after transform
    frequency: str         # D|W|M|Q|A
    seasonal_adjustment: str
    observations: list[Observation]     # ascending, gaps kept as None, bounded
    source_url: str        # human citation page (valid http(s), 2+ label host)
    api_url: str = ""      # reproducible machine URL when known (no secrets)
    retrieved_at: str = "" # ISO UTC
    last_updated: str = "" # upstream revision timestamp when known
    transform: str = ""    # "" | "yoy" | "pct"
    projection_from: str = ""  # ISO date: observations on/after are projections (WEO/GEP)
    notes: str = ""        # ≤ 400 chars caveats
    route: str = ""        # "mcp" | "fred_csv" | "cache"
    def to_dict(self) -> dict; @classmethod from_dict(...)
@dataclass
class SearchHit: series: str; title: str; units: str; frequency: str; coverage: str; provider: str; note: str = ""
@dataclass
class DataError: series: str; message: str; retryable: bool = False   # message is agent-facing, ≤ 300 chars
```

### 5.3 API

```python
class DataSources:
    def __init__(self, hub: McpHub | None = None, *, env: Mapping[str,str] | None = None,
                 cache_dir: str | Path | None = None, providers: Iterable[str] | None = None,
                 clock=time.time, http_get=None)   # http_get injectable for the FRED CSV route
    def enabled(self) -> bool                       # DATA_SOURCES_ENABLED and ≥1 provider usable
    def providers(self) -> dict[str, str]           # {"fred": "ready"|"keyless"|"<reason>", ...}
    def prewarm(self) -> None                       # hub.start(usable providers) in background
    def search(self, query: str, *, provider: str | None = None, limit: int = 6) -> list[SearchHit]
        # catalog matches first (exact keyword/geo), then live provider search
        # (fred_search, data360_search_indicators, treasury_search_datasets,
        # bis list_curated_flows/search_dataflows→curated keys), deduped; never raises
    def get(self, series: str, *, start: str | None = None, end: str | None = None,
            transform: str | None = None, max_obs: int = 240) -> Series | DataError
        # default window: last 10 years (A: 25 y, D: 2 y aggregated to monthly when the
        # provider allows, else last max_obs); daily series are aggregated to monthly
        # (FRED frequency=m avg; others locally) so pages stay small. Validates returned
        # codes (IMF), trims to window client-side (IMF/BIS ignore windows), keeps the
        # NEWEST max_obs, handles BLS 10-year chunking newest-first and 25-id batching,
        # BLS keyless daily quota (persisted counter, stop at 20/day), FRED keyless CSV
        # route when FRED_API_KEY is absent or rejected. Disk cache (TTL: D/W 6 h,
        # M/Q 12 h, A 24 h) keyed by (series, start, end, transform).
    def get_many(self, ids: Sequence[str], *, deadline_s: float, **kw) -> dict[str, Series | DataError]
        # parallel with per-provider concurrency (imf 1, bls batched), stops at deadline
    def close(self) -> None
def get_data_sources(*, env=None) -> DataSources    # process singleton (uses get_hub)
```

### 5.4 Rendering helpers (shared by v3 tools, legacy tools, ledger pages)

- `series_stats(series) -> dict`: latest {date,value}, previous-year value and
  change (abs and %), 5-year min/max with dates, 10-year CAGR when level
  series, observation count, first/last date, projection count.
- `format_value(value, units) -> str`: deterministic display (percent units →
  `"4.2%"` style with ≤2 decimals; index/levels ≤ 4 significant decimals;
  thousands kept without separators? — choose ONE rule and use it everywhere so
  agents quote exactly what verification reads; test that every rendered cell
  passes `linear_research.page_number_set`/`_number_on_pages` for the same text).
- `render_series_page(series) -> str`: the stored page text used for number
  verification and shown (bounded) to agents. ≤ 12,000 chars. Layout:
  ```
  # <title>
  Provider: <provider_name> · Series: <native id> · Units: <units> · Frequency: <label> · Seasonal adjustment: <sa>
  Source: <source_url> · Retrieved: <date> · Coverage shown: <first> to <last> (<n> observations)
  [Projections: values from <date> onward are <publisher> projections.]
  ## Summary
  - Latest: <v> (<period>)
  - Year earlier: <v> (<period>); change <+x> (<+y%>)
  - 5-year range: <min> (<period>) to <max> (<period>)
  ## Observations (<units>)
  | Period | Value |
  | 2026-09 | 4.2% |
  ```
  Percent-unit cells carry `%`; currency/scale units are stated in the caption
  line "Values in <units>" so unit-class verification works.
- `render_series_brief(series, sid: int | None) -> str`: ≤ 900 chars agent
  summary (header line + summary + last 8 observations).
- `write_dataset_files(series_list, out_dir, *, citations: Mapping[str,int] | None = None) -> dict`:
  writes `out_dir/data/<slug>.json` (Series.to_dict), `out_dir/data/<slug>.csv`
  (`date,value`), and `out_dir/data/datasets.json` manifest:
  ```json
  {"schema_version": 1, "generated_at": "...", "series": [
    {"series": "fred:UNRATE", "slug": "fred_unrate", "provider": "fred", "title": "...",
     "title_zh": "...", "units": "...", "frequency": "M", "seasonal_adjustment": "SA",
     "source_url": "...", "api_url": "...", "retrieved_at": "...", "last_updated": "...",
     "transform": "", "projection_from": "", "observations": 120,
     "first": "2016-10-01", "last": "2026-09-01", "latest": {"date": "...", "value": 4.2},
     "file": "data/fred_unrate.json", "csv": "data/fred_unrate.csv",
     "kiqs": ["K1"], "source_id": "S12", "chart": "charts/data_fred_unrate.png"}]}
  ```
  `slug` = lowercase `[a-z0-9_]` derived from `series` (≤ 60 chars, unique).
- `load_datasets(out_dir) -> list[dict]` (manifest rows + loaded observations),
  tolerant of missing/corrupt files (returns []).

## 6. Agent tools (v3 + legacy share the same text contract)

- `data_search(query, provider?)` → lines (no [S#]): `fred:UNRATE — Unemployment Rate · Percent · monthly · SA · 1948-01→2026-09` (+ one-line note). Empty → `NO_DATA_MATCH: try a broader concept or another provider (fred, bls, bis, imf, wb, usgov).`
- `data_get(series, start?, transform?)` → first line is the source header
  `[S<n>] <title> — <domain> (tier 1) — dataset <series>, <units>, <freq>, <n> obs, <first>–<last>`
  then the bounded page excerpt (summary + table, wrapped as untrusted data).
  Errors → `DATA_UNAVAILABLE: <reason>` / `DATA_BUDGET_EXHAUSTED: ...`.
- Budgets (v3 preset knobs): `data_calls_per_kiq` quick 3 / standard 4 / deep 5,
  `max_data_calls_total` quick 24 / standard 50 / deep 90; env
  `RESEARCH_LINEAR_DATA_CALLS_PER_KIQ`, `RESEARCH_LINEAR_MAX_DATA_CALLS_TOTAL`.
  A `data_search` and a `data_get` each cost one data call; cached repeats are free.

## 7. v3 engine integration (slice B; files research_gateway.py, linear_research.py)

1. `research_gateway.py`: `AGENT_TOOLS_WITH_DATA_SCHEMA` constant (web_search,
   web_fetch, data_search, data_get); ToolLimits `max_data_calls_total`,
   `max_data_calls_per_agent`; ResearchTools gains `data_sources` (a
   DataSources or None) and `data_search()/data_get()` with run-level dedup,
   singleflight, budgets, counters; SourceLedger `register_dataset(url, title,
   series, agent_id, *, tier="S1")` → row via='data', fetched=True after the
   page is stored (pages/<sha16>.txt) with `dataset` sub-dict {series,
   provider, units, frequency, slug}; canonical URL = series source_url +
   `?drf_series=<series>` only when needed to keep transforms distinct.
2. `linear_research.py`:
   - Plan: `_T_PLAN` KIQ items gain optional `data_needs: [{series?, query,
     geography?}]` (≤ 3 per KIQ); planner task gets `catalog_digest()` and a
     provider overview when data is enabled (volatile last message). `Kiq.data_needs`
     round-trips; old plan.json loads with [].
   - New phase `"data"` in PHASES after "plan" (time share ~0.08, wall cap
     min(150 s, share)): resolve needs → ids (explicit `series` if parseable &
     usable; else top catalog/search hit by deterministic score); `get_many`;
     register ledger rows; persist `v3/data/index.json` {kiq: [sids]} +
     series JSONs; seed each KIQ's dataset sids into its shown set; always ends
     `done` (status note `disabled`/`no_needs`/`skipped_resume`). Hub prewarm
     starts at engine init (background) when enabled.
   - KIQ task: when enabled, a delimited "OFFICIAL DATA ALREADY RETRIEVED"
     block (briefs with [S#]) + data-tool usage/budget lines. ENGINE_CORE may
     gain ONE static sentence about official-data tools (no conditions, no
     `$`/`{`/dates).
   - Dispatch: `_execute` counts data tools toward MAX_TOOL_CALLS_PER_STEP;
     `_call_tool` routes them; `tool_output_sids` treats `data_get` like
     `web_fetch` (header sid = fetched/shown); data_search novelty per distinct
     query; `_watch_tool` wraps them.
   - Evidence: dataset page text drives the existing VERIFIED machinery.
     `_finish_kiq` adds deterministic VERIFIED facts for each dataset the KIQ
     used/was seeded with: "<title>: <latest> (<period>); <yoy line> [S#]".
   - Digest: an "OFFICIAL DATA SERIES" block (one line per dataset with latest
     values and [S#]) when digest.md is first built.
   - Charts + figures: at the start of QA (`_run_qa`, before renumbering) call
     `bridge_call("_render_data_charts", out_dir, plog=..., question=...)`
     (implemented in deerflow_research.py by slice C; returns the list of chart
     manifest rows) after `write_dataset_files`; insert `### Figure: <title>`
     blocks (image + italic caption with `[S#]`) into the section covering the
     dataset's KIQ (≤ 2 per section), and an `## Official Data Baseline`
     (zh `## 官方数据基线`) section before References with the indicator table
     (series, latest, period, change, source [S#]) and the remaining figures
     (≤ 8 figures total). sections_in_order accepts this heading.
   - QA: new checks `data_numbers_consistent` (sentences citing a data sid only
     contain numbers present on that dataset page) and `data_exhibits` (when
     datasets exist, ≥1 figure or the baseline table is present, and every
     embedded chart path exists).
   - Finalize: `write_dataset_files` (with final positional source ids),
     sources.json rows for datasets carry `source_origin: "official_data"`,
     an `excerpt` of "Latest: …; Year earlier: …; 5-year range: …" lines (+ a
     Chinese line when the run language is zh), and `dataset` {series,
     provider, units, frequency, file}. meta gains `data_sources` {providers
     status, series count, calls, failures, route counts}. Degradation event
     when data was enabled but every provider failed.
   - Resume: ENGINE_VERSION and identity unchanged; phase data skipped (done)
     when gather is already done; v3/data artifacts persisted before `done`.

## 8. Charts (slice A4: skill `data-visuals`)

`deerflow_bridge/skills/data-visuals/scripts/render_data.py --dir <out_dir>
[--max N] [--lang en|zh]`: reads `out_dir/data/datasets.json` + series files,
writes `out_dir/charts/data_<slug>.png` (matplotlib, Agg, deterministic, 2x
DPI) and `out_dir/charts/data_<slug>.html` (plotly self-contained when plotly
is importable; else omitted), plus up to 2 grouped comparison charts
`data_compare_<units-slug>.png` when ≥ 2 series share units+frequency (e.g.
policy rates across economies). Style mirrors report_visualizer's palette and
CJK font stack. Each chart: observed line, latest point marker + label,
projection segment dashed + shaded (projection_from), gaps broken (no
interpolation), y-axis label = units, footer "Source: <provider_name>, <native
id> · retrieved <date>". Titles digit-free where possible (series title from
source is allowed in the image; the manifest `title`/`caption` must avoid bare
years: use "latest" wording instead of dates). Merges `out_dir/charts.json`
under the same `charts.json.lock` protocol as forecast-visuals render.py,
owning ids with prefix `data_` only (keeps all others). Manifest rows: {id,
title, caption, source_data: "data/datasets.json", data_class:
"official_statistics", path, html_path, series: [...]}. Exit 0 = ≥1 chart, 2 =
no data, 3 = no matplotlib. Prints a JSON summary on stdout.

## 9. Legacy engine (slice C; deerflow_research.py, config.yaml, new data_tools.py)

- `deerflow_bridge/data_tools.py`: `data_search_impl(query, provider=None) -> str`,
  `data_get_impl(series, start=None, transform=None) -> str` (never raise;
  same text contract; append provenance rows to
  `$DEERFLOW_RUN_ARTIFACT_DIR/data_series_candidates.jsonl` like market_tools);
  LangChain `@tool` wrappers `data_search_tool`, `data_get_tool` (None without
  langchain).
- config.yaml: register both tools; scoped-researcher tools whitelist + skills
  [deep-research, prediction-markets, data-sources]; loop_detection overrides
  (30/45). Copy to the local deployed deer-flow/config.yaml; improve the drift
  warning to name missing tools.
- Prompts: quantitative phase line and build_research_prompt mention the data
  tools + `/mnt/skills/public/data-sources/SKILL.md` (read_file pointer;
  respect test_loop010 wording rules). available_skills adds data-sources and
  data-visuals.
- Bridge helpers (used by BOTH engines):
  - `_render_data_charts(out_dir: Path, *, plog=None, question: str = "", lang: str = "en") -> list[dict]`:
    runs render_data.py with `_charts_python()` (timeout RESEARCH_CHARTS_TIMEOUT),
    returns the `data_*` manifest rows that exist on disk; never raises.
  - `_finalize_data_series(out_dir: Path, *, plog=None) -> list[dict]`: legacy
    finalizer: reads data_series_candidates.jsonl, re-fetches nothing (uses the
    stored series JSON paths recorded by data_tools), writes datasets via
    `write_dataset_files`, appends dataset rows to sources.json (tier S1,
    official_data) when absent. Called before `_render_research_charts` /
    `_render_data_charts` in Stage 4 and the extract-only path.
  - `_DECISION_VISUAL_IDS` gate counts any `data_*` chart as satisfying
    `quant_metrics`/`metric_trajectories` demand.
- Fix the harness-litter deploy: runtime_skill_sync `_is_source_noise` ignores
  `logs/` and `.claude/` dirs (slice A3).

## 10. Forecast report (slice D1 visualizer + D2 agent/orchestrator/extractor)

- Orchestrator: `_ra_artifacts["official_data"] = load_official_data(handoff_dir)`
  (manifest rows + observations, bounded) in the main REPORT stage, the manual
  API path and ensemble seeds; ReportAgent gains `official_data: dict | None =
  None` IN THE SAME CHANGE (TypeError fallback trap).
- `official_data` shape (single contract for orchestrator → ReportAgent →
  `_collect_viz_artifacts` → visualizer → resolver/world brief):
  `{"schema_version": 1, "series": [<datasets.json row> + {"observations":
  [{"date","value","flag"}] (≤ 240 newest), "source_id": "S<n>" (positional
  id in handoff sources.json, when resolvable)}]}`, produced by
  `data_sources.load_official_data(handoff_dir, *, max_series=12)` (slice A5
  adds it next to `load_datasets`; returns None when there is no manifest).
  ReportAgent stores it as `self.official_data` and passes it to the
  visualizer as `arts["official_data"]`; binaries (with `data_anchor`) reach
  the visualizer through the existing forecast artifacts.
- ReportAgent: `_data_pack` ("Official data snapshot" table: series, latest,
  period, YoY, 5y range, units, [S#] resolved via the citation index by URL;
  ≤ 3,500 chars; '' when absent) added to `_prepend_research_background` next
  to `_market_pack`, plus the instruction to quote values exactly as listed
  with their [S#]. `_official_data_corroborated_claim` keeps exact-value data
  sentences from deletion by the quantitative-grounding repair.
- Spine/binaries: `derive_forecast_spine(..., quantitative_facts=<official
  digest>)`; `extract_binary_forecasts(..., data_pack=...)` with prompt rule:
  when a binary concerns a listed series add `data_anchor {series,
  comparator: ">"|">="|"<"|"<=", threshold: number, observation: "YYYY-MM" |
  "YYYY-Qn" | "YYYY", transform: ""|"yoy"}`; `_normalize_binaries` validates
  against the snapshot (unknown series → anchor dropped) and backfills
  `latest_value`, `latest_date`, `units`, `source_url` from stored data.
- Visualizer (`report_visualizer.build_all`): builders
  `official_indicators` (small-multiples dashboard of up to 6 key series,
  native date axis) and `official_series_<slug>` (one per anchored or
  most-cited series, ≤ 4: history line, last observation marker, horizon
  vline at the forecast horizon, dashed threshold hline(s) from binary
  data_anchors with probability labels, shaded numeric scenario bands when
  parseable via `_extract_comparable_numeric_range`, projection shading for
  WEO). Fixed titles in CHART_TITLES_ZH and frontend ZH_CHART_CAPTIONS;
  placement_hint "official_data" with `_VIZ_PLACEMENT_KEYWORDS` entries;
  matplotlib fallback; digit-free titles/captions/filenames.
- "How to Verify This Forecast" (authored heading, exempt from grounding):
  an "Official series to watch" table (series, latest, threshold, link).

## 11. Other integrations (slice E)

- Resolution: `resolution_monitor.py` gains a data-anchored resolver: for
  binaries with `data_anchor` whose observation period has been published,
  fetch via `DataSources.get` (keyless routes allowed), compute outcome and
  Brier, write via new idempotent `forecast_ledger.append_data_resolution`
  keyed (report_id, forecast_id, "data:<series>"); exclude them from
  `detect_needs_manual` when resolved; unpublished → pending; failures →
  manual with reason.
- Simulation world brief: `simulation_config_generator._build_world_brief`
  appends an "Official data snapshot" block (≤ 8 series, latest values with
  period and source name) when handoff datasets exist — public facts, no
  forecast numbers, respects the existing leakage rules.

## 12. Configuration (slice A3)

Config (backend/app/config.py, inline style; all documented in .env.example
under a new section after the Polymarket section; `check_env_drift.py
--strict` must pass):

| Name | Default | Meaning |
|---|---|---|
| DATA_SOURCES_ENABLED | true | master switch for research/report data use |
| DATA_SOURCES | fred,bls,bis,imf,wb,usgov | provider allowlist |
| DATA_SOURCES_DIR | "" (= <repo>/datamcps) | vendored servers root |
| DATA_SOURCES_NODE | "" (= which node) | node binary |
| DATA_SOURCES_CACHE_DIR | "" (= backend/uploads/.data_cache) | disk cache + quota file |
| DATA_SOURCES_CALL_TIMEOUT | 60 | per-call seconds (imf uses max(this, 90)) |
| DATA_SOURCES_PREFETCH_MAX | 12 | max series prefetched in the data phase |
| DATA_SOURCES_CHARTS_MAX | 8 | max data figures in the dossier |
| REPORT_DATA_CHARTS | true | official-data charts in the forecast report |

The orchestrator forwards `DATA_SOURCES_*` (resolved absolute DATA_SOURCES_DIR,
DATA_SOURCES_NODE, DATA_SOURCES_CACHE_DIR) to the research subprocess env.
API keys (FRED_API_KEY, BLS_API_KEY, EIA_API_KEY, BEA_API_KEY, CENSUS_API_KEY,
DATA_GOV_API_KEY, SEC_CONTACT_EMAIL) are not Config attributes (SERPER
precedent) — documented in .env.example; inherited via os.environ.
`backend/tests/conftest.py` autouse: DATA_SOURCES_ENABLED=false and the key
names deleted, unless a test opts in.

Build: `scripts/setup_datamcps.sh` (idempotent; per server; warn-and-continue;
SETUP_DATAMCPS=0 opt-out): bls `npm ci && npm run build`; fred `pnpm install
--frozen-lockfile --ignore-scripts && pnpm run build` (fallback `npm install`);
bis `npm install` (no build); usgov `npm ci` (prepare builds; skip with
warning on node < 22); imf `uv venv --python 3.12 .venv && uv pip install
--python .venv/bin/python . "mcp[cli]>=1.9.1,<2"` (never `uv sync`: stale
lock); wb `uv sync --directory` (python ≥ 3.11). Root package.json
`setup:datamcps`; setup.sh step after the DeerFlow venv step; doctor.sh section
(build outputs, node version, key NAMES set). `datamcps/` sources are
committed (licences MIT/Apache-2.0/AGPL-3.0, compatible), build outputs and
hook litter ignored.
