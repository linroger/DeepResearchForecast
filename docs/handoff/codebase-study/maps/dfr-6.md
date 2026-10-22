# dfr-6 — deerflow_research.py part 6: prediction-market snapshot, visuals contract, chart embedding, engine resolution, main()

Scope: `deerflow_bridge/deerflow_research.py` lines 15064-17986 (branch `main`, checkout HEAD `c20ec60`). Every line of the slice was read. Helpers outside the slice were read only to explain what a call does; they are anchored, but they belong to other maps. All paths are relative to the repo root.

## Purpose & position in the pipeline

- This slice is the tail of the research bridge. The orchestrator spawns it as a subprocess (`backend/app/services/pipeline_orchestrator.py:2206`, `:2251-2264`) and points it at a handoff directory with `--out-dir`. The process writes the file-based handoff contract that the graph, simulation and report stages read (module docstring `deerflow_bridge/deerflow_research.py:7-14`).
- The slice has five parts:
  1. **Prediction-market collection** (15064-15788). It runs a bounded, concurrent Polymarket Gamma search (`_pm_snapshot`), applies an LLM relevance gate, merges in markets the agent found mid-research, writes `prediction_markets.json`, upserts a "Prediction Market Signals" section into `research_report.md`, and fetches CLOB price history into `market_price_history.json`. A pre-research variant (`_pm_initial_snapshot`) feeds a pricing block into the pass-0 prompt.
  2. **Research visuals** (15791-16022). It decides when the question demands charts (`_visual_contract_requirements` / `_visual_contract_audit`), runs the bundled `forecast-visuals/scripts/render.py` in a subprocess, and embeds the PNGs into the report as a "## Visual Annex" (`embed_chart_refs`).
  3. **Extract-only salvage** (16025-16358). `run_extract_only` skips research and rebuilds `actors.json`/`timeline.json`/`quantitative.json`/`contested.json`/`sources.json` from an existing report. It then runs markets and charts, and seals actor intelligence when a dossier exists.
  4. **Engine selection and environment hygiene** (16361-16562). It maps `RESEARCH_ENGINE` to v3 or legacy, presets empty defaults for every `$VAR` in DeerFlow's `config.yaml`, and dispatches to `linear_research.run` inside a failure boundary.
  5. **`main()`** (16570-17973) plus the `__main__` hard exit (17976-17986). It covers CLI parsing, the preflight checks, the legacy engine's Stage 1 (research, with dual-track, evidence-only and global-synthesis variants), the judge gates, Stage 2 (structured extraction and analytics), triangulation top-up, Stage 3 (markets), Stage 4 (charts), and the final actor-intelligence seal.
- The v3 engine (`deerflow_bridge/linear_research.py`) calls back into this slice for markets and charts: `bridge_call("_collect_prediction_markets", ...)` at `deerflow_bridge/linear_research.py:5548-5551` and `bridge_call("_render_research_charts", ...)`. `bridge_call` swallows every exception (`deerflow_bridge/linear_research.py:4080-4091`).

## Walkthrough (source order)

### Prediction-market snapshot

**`_pm_snapshot(queries, per_query=8, max_total=20, min_volume=200, max_per_event=3, diagnostics=None)` — 15064-15184**
- Purpose: one bounded, concurrent catalog search with a run-level deadline and a transport circuit breaker. The docstring explains why: an earlier serial loop could take about 17 minutes during an outage (15067-15073).
- Strips and drops empty queries (15078).
- Env knobs, all degrade-safe on `ValueError`:
  - `PREDICTION_MARKETS_WORKERS`: default 4, clamped to 1..8 (15079-15083).
  - `PREDICTION_MARKETS_DEADLINE_SECONDS`: default 15, minimum 1.0 (15084-15088).
  - `PREDICTION_MARKETS_TRANSPORT_FAILURE_BREAK_AT`: default 3, minimum 1 (15089-15093).
- Each query is fetched with `_polymarket_get("/public-search", {"q", "limit_per_type": per_query, "events_status": "active"})` (15099-15106). The call is plain stdlib urllib against `https://gamma-api.polymarket.com` (14507). It sends a browser-like UA (14514), uses an 8 s per-request timeout and makes 2 attempts by default, with jittered backoff on 429/5xx/URLError (14878-14925). On final failure it raises a `RuntimeError` with `.error_class` and `.http_status` attached (14921-14925).
- The `ThreadPoolExecutor` gets `min(workers, max(1, len(queries)))` threads (15109). All futures are submitted up front (15110-15113). The loop runs `cf.wait(FIRST_COMPLETED)` until the deadline (15115-15128).
  - Each failure is recorded as `"<error_class>[:<http_status>]"` in `error_classes` (15139-15146).
  - **Circuit:** when `successful == 0 and failures >= threshold`, the loop breaks (15147-15148).
  - Pending futures are cancelled (15149-15150) and the executor is shut down with `wait=False, cancel_futures=True` (15151-15152). Requests already running keep going in the background.
- Results are processed in submission order so the output is deterministic despite concurrent completion (15154-15155). For every event and market the row is normalized with `_pm_normalize_market`. That function drops rows that are closed, lack a price, have a price outside the open interval (0,1), or fall below `min_volume` (14978-15000). The first market_id seen wins (15161-15170).
- Rows are sorted by volume descending (15171), then passed through `_pm_cap_per_event`: at most `max_per_event` rows per `event_title`, truncated to `max_total` (15047-15061, call at 15184).
- `diagnostics` (when a dict is passed) is updated with:
  - `attempted_query_count`, `successful_query_count`, `transport_failure_count`;
  - `transport_error_classes` when there were errors;
  - `transport_circuit_open=1` when the circuit opened;
  - `deadline_exhausted=1` when fewer futures completed than were submitted (15172-15183).

**`_PM_SECTION_HEADING = "Prediction Market Signals"` — 15187**

**`_strip_markdown_h2_section(report, title)` — 15190-15217**
- Pure function. Removes every `## <title>` block up to the next `#`/`##` heading or EOF. `###` sub-headings belong to the block and are removed with it (the boundary regex `^#{1,2}[ \t]` cannot match `###`, 15199).
- Lines starting with a triple-backtick fence toggle fence state (15204-15208). A `##` line inside a fence neither starts nor ends a block, and fence lines inside a skipped block are dropped too. Used to upsert machine-owned sections (15713).

**`_pm_render_section(markets, as_of)` — 15220-15249**
- Deterministic markdown:
  - `## Prediction Market Signals`;
  - a blockquote disclaimer ("calibration anchors, not ground truth");
  - `### Prediction Market Signals (Polymarket)`;
  - a 5-column table `# | Market question (market_id) | Venue | Implied P(yes) | Volume`. [verifier: the header row is literally `| # | Market question | Venue | Implied P(yes) | Volume |`; the ` (market_id)` suffix appears only inside each data row's question cell (deerflow_bridge/deerflow_research.py:15231, 15241-15244)]
- Questions are truncated to 160 chars. `|` is replaced with the full-width `／` and newlines with spaces (15235-15236). The probability is formatted as `NN%` and volume as a comma-grouped integer; a missing value prints `—` (15238-15248).

**`_pm_env_caps()` — 15252-15268**
- Returns `(max_total, min_volume, max_per_event)`:
  - `PREDICTION_MARKETS_MAX`, falling back to the legacy `ODDPOOL_MAX_MARKETS`, then to 20;
  - `PREDICTION_MARKETS_MIN_VOLUME`, default 200;
  - `PREDICTION_MARKETS_MAX_PER_EVENT`, default 3.
- Invalid values fall back to the defaults. The pre-pass snapshot and the final refresh share it so the two cannot drift (15253-15254).

**`_pm_per_query()` — 15271-15277**
- `PREDICTION_MARKETS_PER_QUERY`, default 8, clamped to 1..50.

**`_pm_render_pricing_block(markets, as_of, limit=8)` — 15280-15297**
- PM-4: a compact "CURRENT MARKET PRICING ..." block for the pass-0 prompt. It lists at most `limit` markets as `- <question[:140]>: market prices YES at NN%, volume $V`. With no markets it returns `""`.
- Stored through `_set_market_pricing_block` (1261-1263) and read by `_market_pricing_prompt_block()` (4505-4509) when the research prompt is built.

**`_MARKET_REPORT_STOPWORDS` / `_market_report_tokens(text)` — 15300-15312**
- Lowercase `[a-z0-9]+` tokens of at least 2 chars, minus a small stopword set. Only ASCII tokens count, so CJK title text never produces tokens.

**`_market_is_cited_in_report(report, market, report_tokens=None)` — 15315-15358**
- Fail-closed check of whether the report used a tool-discovered market. It returns True when any of these holds:
  - (a) the market's `url` or `event_url` appears verbatim in the lowercased report (15327-15331);
  - (b) the `market_id` is at least 6 chars and appears in the report (15332-15334);
  - (c) the question plus event_title tokens overlap the report tokens in at least 4 places (15336-15348);
  - (d) the overlap is at least 2 **and** the fetched probability appears in one of six forms: `NN%`, `NN.N%`, `NN.NN%`, `NN percent`, `NN.N percent` or `NN.NN percent` (15350-15358).

**`_load_tool_market_candidates(out_dir, max_bytes=4_000_000)` — 15361-15406**
- Reads `prediction_market_candidates.jsonl` (constant at 14504). The agent's `prediction_market_search` tool writes this file (`deerflow_bridge/market_tools.py:59`).
- If the file is larger than `max_bytes`, it seeks to the last 4 MB and discards the first partial line (15370-15376). Any `OSError` returns `[]` (15377-15378).
- Each JSONL record is `{captured_at, queries, markets:[...]}`. Malformed lines are skipped (15382-15388).
- Each market row is copied and tagged with `captured_via="prediction_market_search"`, `captured_at` and `tool_queries` (15397-15402). A later observation of the same market_id replaces the earlier one, while the first-seen order is kept (15403-15406).

**`_merge_market_rows(primary, secondary)` — 15409-15427**
- Merges by market_id. Secondary rows are visited first, then primary rows. Field updates from primary win, and first-seen order holds, so secondary-only IDs come first. [verifier: every secondary ID (including IDs also present in primary) keeps its first-seen slot ahead of all primary-only IDs; shared IDs are not moved behind them (deerflow_bridge/deerflow_research.py:15413-15427)]
- The `overwrite` tuple element is always True (15413), which makes it a dead parameter.

**`_pm_resolve_queries(question, hot_topics, actor_names, model_name, plog)` — 15430-15439**
- When `PREDICTION_MARKETS_LLM_QUERIES` (default true) is set and a model name is present, it calls `derive_market_queries_llm`: one bare, tool-free LLM call labelled `prediction-market-query-derivation`, which asks for 10-16 queries shaped like market titles (14754-14770; prompt at 14690-14710).
- It falls back to the deterministic `_pm_derive_queries` (14608-14646: at most 12 queries of at most 5 words, with at least 2 slots reserved for actor names) [verifier: the reservation is `min(2, len(actors))` slots, so 0 or 1 when fewer actors exist; actors may then fill beyond the reserve from the full budget (deerflow_bridge/deerflow_research.py:14633-14641)] when the LLM path is empty or fails.

**`_pm_initial_snapshot(question, model_name, plog)` — 15442-15473**
- PM-4 pre-research snapshot. It uses question-derived queries only (no actors yet) (15445). The caps come from `_pm_env_caps` and `_pm_per_query` (15448-15453).
- When no markets come back:
  - If every query failed at the transport level (attempted > 0, 0 successes, and failures, circuit or deadline), it sets the module global `_PM_TRANSPORT_UNAVAILABLE=True` together with the error classes (15455-15465; setter at 1271-1274).
  - It logs a `warn` that includes the error classes and returns `[]` (15466-15470).
- On success it clears the flag (15471). It then calls `score_market_relevance`, a batched bare LLM call labelled `prediction-market-relevance` that returns `{market_id: 0-10}` (14837-14870), and applies `_apply_relevance_gate` with `_pm_min_relevance()`. The threshold comes from `PREDICTION_MARKETS_MIN_RELEVANCE`, then `PM_MIN_RELEVANCE`, default 5 (14773-14781).
- The gate (14816-14834) drops rows scoring below the threshold. It keeps unscored rows, and with empty scores it keeps everything (fail-open). The result is sorted by (relevance, volume) descending.

**`_collect_prediction_markets(out_dir, question, report, meta, plog, model_name="claude")` — 15476-15730** (Stage 3; also called by extract-only and v3)
1. `PREDICTION_MARKETS_ENABLED=false` → logs a warn and returns **without writing any file** (15484-15486).
2. Loads `hot_topics`, actor names and `context_entities` names from `actors.json` when present. All errors are swallowed (15488-15507).
3. Loads tool candidates (15508).
4. **Transport short-circuit:** when the pre-pass set `_PM_TRANSPORT_UNAVAILABLE` and there are no tool candidates, it writes `prediction_markets.json` with `markets: []`, `no_relevant_markets: true`, `reason: "pre-pass transport circuit open"` and `status.empty_reason: "transport_failure"`. It also hard-codes `transport_failure_count: 1` and adds `transport_error_classes` when known. It sets `meta.prediction_markets_count=0` and returns (15509-15541).
5. **Query choice:** when tool candidates exist and `PREDICTION_MARKETS_REFRESH_WITH_TOOL_CANDIDATES` is false (the default), `queries=[]`, so no deterministic refresh runs. Otherwise queries come from `_pm_resolve_queries` with hot topics and actors (15542-15548).
6. **No queries and no tool candidates:** it writes an explicit empty marker (`reason: "no derivable queries"`, `empty_reason: "no_derivable_queries"`) and returns (15549-15562).
7. **Refresh:** `_pm_snapshot(queries, ...)` with the shared caps (15563-15568). `initial_all_transport_failed` is computed from **this refresh's** diagnostics, not the pre-pass (15569-15578).
8. **Canonical relevance decision (LOOP-009):** `combined = _merge_market_rows(refreshed, tool_candidates)` (15582).
   - When the scorer returns scores, it applies the gate (15585-15588).
   - When the scorer returns `{}`, it keeps refreshed rows (historical fail-open) plus any tool candidate that passes `_market_is_cited_in_report`. The result is sorted by volume, and kept tool rows get `report_cited=True` (15589-15610). [verifier: a tool candidate whose market_id also came back in the refresh is kept by the refreshed-ID test with no citation check and is NOT tagged `report_cited` (15594-15597, 15601, 15608-15610). The citation test runs on the passed-in report BEFORE the old PM section is stripped (15598-15602 vs 15713), so on extract-only salvage a prior machine-written PM table (which prints each market_id, 15241-15244) can self-certify tool rows. Tool rows carry the shared event URL (deerflow_bridge/market_tools.py:133-139), so citing one event page vouches for every sibling market of that event (15328-15331)]
   - It logs whether any agent-vetted tool candidates were preserved (15611-15622). An empty combined set logs a warn (15623-15624).
9. **Horizon degradation (PM-HZ):** when there are no markets, the refresh did not fully fail at the transport level, and `PREDICTION_MARKETS_HORIZON_RETRY` (default true) is set, it walks `degrade_market_queries(queries)`. The stages are `year_stripped`, then `event_level` (14649-14689).
   - Each stage reruns `_pm_snapshot` and adds its diagnostics to the totals (15632-15647).
   - The relevance gate is **fail-closed** here: an empty score map discards the stage (15650-15653).
   - The first stage with surviving rows wins. Those rows are tagged `horizon_degraded=<stage>` and the loop breaks (15654-15664).
10. Re-caps per event and in total after reconciliation (15667).
11. Builds the payload: `as_of`, `source:"polymarket"`, `queries`, `markets`, plus optional `tool_candidates_seen`, `registry_sources`, `horizon_degraded` and `degraded_queries` (15668-15675). `status` holds the counts and `empty_reason`, which is one of `all_candidates_irrelevant`, `transport_failure` or `no_equivalent_market` (15676-15696).
12. **Empty result:** writes the file with `no_relevant_markets: true`, sets `meta.prediction_markets_count=0` and returns without a report section (15697-15705).
13. **Non-empty result:**
    - Writes the JSON (15706-15707).
    - Upserts the report section: it strips any earlier `## Prediction Market Signals` block from the **passed-in `report` string**, then appends the new section and atomically writes `research_report.md` (15712-15715).
    - Sets `meta.report_chars`, `prediction_markets_count` and `prediction_markets_as_of` (15717-15719).
14. **PM-6 price history:** if `PREDICTION_MARKETS_PRICE_HISTORY` (default true) is set, it calls `_collect_market_price_history` and records `meta.prediction_market_price_history_count`. Any exception only logs (15724-15730).

**`_pm_yes_leg_token(m)` — 15733-15749**
- Picks the YES-leg CLOB token, never a blind index 0. Order: an explicit `clob_yes_token_id` (set by normalize at 15041-15044); otherwise the index of `"yes"` in `outcomes` within `clob_token_ids`; otherwise `""` and the caller skips the market (fail-closed).

**`_collect_market_price_history(out_dir, markets, plog)` — 15752-15788**
- Env: `PREDICTION_MARKETS_PRICE_HISTORY_MAX` (default 20), `PREDICTION_MARKETS_PRICE_HISTORY_DAYS` (default 90), `PREDICTION_MARKETS_PRICE_HISTORY_INTERVAL` (default `"1d"`) (15759-15767).
- Processes markets **serially**, at most `cap` of them. Markets without a market_id or CLOB ids are skipped, and so are markets whose YES leg cannot be found (with a warn) (15769-15777).
- Each fetch calls `_pm_fetch_price_history(yes_token, interval, days)`, which does `GET https://clob.polymarket.com/prices-history?market=<token>&interval=<interval>` with a 15 s timeout. Any failure becomes `[]`. Points are trimmed client-side to the last `days` days as `[{t:int, p:float4}]` (14962-14975, 14928-14959).
- When every series is empty it writes nothing and returns 0 (15781-15783). Otherwise it writes `market_price_history.json` as `{market_id: [{t,p}]}` and returns the series count (15784-15788).

### Research visuals (WAVE9-RQ4)

**`CHARTS_MANIFEST_FILENAME = "charts.json"`, `_DECISION_VISUAL_IDS = {timeline, quant_metrics, metric_trajectories, forecast_revisions, market_probabilities}` — 15798-15805**
- These are the five `forecast_domain` producers of `render.py` (`deerflow_bridge/skills/forecast-visuals/scripts/render.py:2059-2081`).

**`_visual_contract_requirements(question)` — 15808-15825**
- `explicit` is True if the casefolded question contains any of: "visualization(s)", "visualisation(s)", "chart(s)", "figure(s)", "可视化" or "图表". These are substring tests.
- The required IDs are regex-driven:
  - cost curve / deployment trajectory / deployment path / time series → `metric_trajectories`;
  - regional comparison / regional benchmark / cross-region → `quant_metrics`;
  - forecast revision / published forecast → `forecast_revisions`;
  - policy milestone / dated milestone / inflection timeline → `timeline`;
  - market-implied / prediction-market / market probability → `market_probabilities`.

**`_visual_contract_audit(question, charts)` — 15828-15851**
- Returns a dict:
  - `enabled` = `RESEARCH_CHARTS_MIN > 0` (default 3, 4656-4665);
  - `explicitly_requested`, `required_ids`;
  - `rendered_decision_ids` (manifest ids ∩ decision set) and `rendered_diagnostic_ids` (every other id, including `actor_network` and agent-made charts);
  - `minimum_decision_charts` = `RESEARCH_CHARTS_MIN` if explicit, else 0;
  - `missing_required_ids`, `decision_chart_shortfall`;
  - `passed` = `not enabled or not explicit or (no missing ids and shortfall == 0)` (15850).
- Required IDs only matter when the question is explicit.

**`_charts_timeout()` — 15854-15860**
- `RESEARCH_CHARTS_TIMEOUT`, default 180 s. Invalid or non-positive values become 180.

**`_charts_python()` — 15863-15873**
- Interpreter choice: `RESEARCH_CHARTS_PYTHON` if that path exists, else `<repo>/backend/.venv/bin/python` (`Path(__file__).resolve().parents[1]`) if it exists, else `sys.executable`. Only existence is checked.

**`_DIAGNOSTIC_CHART_IDS = {"source_quality"}` / `_is_diagnostic_chart(entry)` — 15878-15888**
- An entry is diagnostic if its id is in that set or its `data_class == "diagnostic"`.

**`embed_chart_refs(report_text, charts)` — 15891-15928** (pure)
- Keeps manifest entries with a non-empty `path` (15896-15897) and drops diagnostic entries (15901). It also drops entries whose `](path)` already appears in the report, because the agent may already have placed the figure in context (15905-15906). With nothing left it returns the input unchanged (15907-15908).
- A `## Visual Annex` header is added only if the substring `"## Visual Annex"` is not already present (15909).
- Each entry renders as `### title`, then `![title](path)` for a `.png` path plus `[Interactive version](html_path)` when present, or only `[Interactive version](path)` for HTML-only entries, then an optional `_caption_` (15910-15927). The annex is appended after `rstrip()` of the report (15928).

**`_render_research_charts(out_dir, meta, plog, question="")` — 15931-16022** (Stage 4; also extract-only and v3)
- `RESEARCH_CHARTS_MIN <= 0` → stores an audit with `enabled=False` in `meta.chart_quality_gate` and returns it (15945-15948).
- Probes for the renderer in the source layout `skills/forecast-visuals/scripts/render.py` and the deployed layout `skills/public/forecast-visuals/scripts/render.py` (15951-15956). If neither exists it logs a warn and returns the empty audit (15957-15961).
- Runs `subprocess.run([py, render.py, "--dir", out_dir], capture_output=True, text=True, timeout=_charts_timeout())`. It passes no cwd or env, so both are inherited (15963-15969). [verifier: only `subprocess.TimeoutExpired` is caught around the call (15970); an `OSError` from launching the interpreter (for example an existing but non-executable `RESEARCH_CHARTS_PYTHON`, which `_charts_python` only checks for existence at 15868) and a `UnicodeDecodeError` from re-reading a non-UTF-8 report (16013, caught only as `OSError` at 16019) propagate to the caller instead of returning an empty audit. In legacy main the caller then keeps its default empty audit (17885-17890), which fails for an explicit-visuals question even if charts rendered]
  - Timeout → empty audit (15970-15974).
  - Non-zero exit → empty audit, with the last stderr or stdout line logged (15975-15980). `render.py` exits 2 when nothing could be rendered and 3 when neither plotly nor matplotlib is available (render.py:44, 2026-2030, 2127-2132).
- Reads `charts.json`. If it is missing, unreadable, not a list, or empty, the result is the empty audit (15981-15998).
- Sets `meta.charts_count = len(charts)`, which counts every manifest entry, including diagnostic and agent-made ones (15999). Computes the audit and stores it in `meta.chart_quality_gate`, with a warn if it failed (16000-16009).
- Re-reads `research_report.md` from **disk**, applies `embed_chart_refs`, and atomically rewrites it if anything changed, updating `meta.report_chars`. An `OSError` only logs (16010-16020). Returns the audit (16022).

### Extract-only salvage (ITEM-14)

**`_withhold_unsealed_actor_intelligence(obj, plog)` — 16030-16060**
- Only for report-only mode, meaning no dossier. It pops the top-level `actor_intelligence_contract` marker and every per-actor `intelligence` dict. Otherwise the parent would treat the unsealed `actors.json` as sealed v1 and fail closed (16033-16041).

**`run_extract_only(question, out_dir, args, meta, plog, write_meta) -> int` — 16063-16358**
- Reads `research_report.md` and `actor_dossier.md` if present (16096-16099). `sealed_contract_mode = bool(dossier.strip())` (16106).
- **Lineage gate:** when actors are enabled and either a dossier exists or `actor_intelligence_lineage.json` is a file, it calls `validate_actor_artifact_lineage(out_dir, question, depth)` (4002). On `ActorIntelligenceFinalizationError` it sets meta to failed and returns **2** before any model call (16107-16124).
- **Source ledger:** an existing `sources.json` is kept byte-for-byte, because `[S#]` citations index row positions (16131-16146).
- Sets `meta.extract_only=True` (16147).
- **Extraction** (when actors are enabled):
  - The input is the dossier plus the report under a "补充" header, or the report alone (16155-16162).
  - Calls `extract_complete_structured_tool_free(input, target_language, model, depth, plog)` (9116), which returns `(raw, obj, failed_candidates, recovery_used)` (16163-16171).
  - Report-only mode strips the intelligence markers (16172-16173).
  - Persists rejected candidates (16174-16181) and records `meta.structured_extraction_recovery` when the compact recovery path was used (16182-16187).
  - `obj is None` → records `extraction_failure` (16188-16199).
  - Otherwise:
    - sources: keep the prior ledger, or use the model rows marked `source_origin="cited"` with `ok` removed (16201-16225);
    - `enforce_actor_cast` (non-fatal) (16226-16229);
    - writes `actors.json` and computes its sha256 (16230-16236);
    - sets meta counts (16237-16240);
    - writes `timeline.json` from `key_events` (16241-16245);
    - writes `quantitative.json`, enriched by `RESEARCH_QUANT_ENRICH` and reconciled by `RESEARCH_QUANT_RECONCILE` (16246-16263);
    - writes `contested.json`, including reconcile disagreements (16264-16268);
    - writes `sources.json` only when no prior ledger existed (16269-16273).
  - Any exception becomes `extraction_failure` (16274-16278).
- **Fail-closed before markets and charts:** an extraction failure sets meta failed and returns **2** (16279-16287).
- Markets: `_collect_prediction_markets(...)`; errors are non-fatal (16289-16294). Charts: `_render_research_charts(...)`; errors are non-fatal and **the audit result is ignored** (16296-16302).
- Re-reads the final report (16307-16310).
  - No dossier → `meta.actor_contract_mode="report-only"` and a warn; there is no seal (16312-16325).
  - Dossier present → `persist_final_actor_intelligence_contract(required=True, require_current_extraction=True, expected_unsealed_actors_sha256=<sha>)` (4131) and `meta.actor_contract_mode="sealed"`. Its failure gives exit **2** (16326-16352).
- Completes with `meta.status="completed"` and returns **0**. `plog` is closed on every return path (16354-16358).

### Engine selection, env hygiene, dispatch

**`_PROVIDER_KEY_ENVS` — 16366-16372**
- `minimax→MINIMAX_API_KEY`, `deepseek→DEEPSEEK_API_KEY`, `qwen→DASHSCOPE_API_KEY`, `glm→ZHIPUAI_API_KEY`, `kimi→KIMI_API_KEY`.

**`_V3_ENGINE_NAMES = {v3, linear}`, `_LEGACY_ENGINE_NAMES = {legacy, deerflow, agentic}` — 16374-16375**
- `_CONFIG_ENV_REF_RE` matches `$VAR` and `${VAR}` with upper-case names (16378).

**`_resolve_research_engine(plog=None)` — 16381-16400**
- Lowercases `RESEARCH_ENGINE`. Unset or empty → `"legacy"`; a v3 alias → `"v3"`; an unknown value → logs a `warn` (first 64 chars) and returns `"legacy"`.

**`_legacy_only_mode(args)` — 16403-16415**
- Returns `"--extract-only"`, `"--evidence-only"` or `"--synthesis-manifest"` when that flag is set, else `""`. These lane contracts always run on the legacy engine.

**`_SALVAGE_VOLATILE_META_KEYS = {status, error, traceback, finished_at}` — 16419; `_prior_v3_meta(out_dir)` — 16422-16430**
- Returns the existing `meta.json` only when its `research_engine == "v3"`.

**`_deerflow_config_candidates(config_arg)` — 16433-16458**
- Resolution: an explicit `--config` alone; else `DEER_FLOW_CONFIG_PATH` alone; else `config.yaml` under `DEER_FLOW_PROJECT_ROOT` (if set), the bridge's own directory and the cwd, deduplicated. This mirrors the order DeerFlow's `AppConfig.resolve_config_path` uses, according to the docstring.

**`_config_env_references(path)` — 16461-16478**
- Collects `$VAR` names from non-comment YAML lines. Whole-line `#` comments are skipped, and trailing `\s#...` comments are cut. Read errors return an empty set.

**`_preset_provider_env_defaults(config_arg)` — 16481-16497**
- For every name in `_PROVIDER_KEY_ENVS` and every reference found in any existing candidate config, runs `os.environ.setdefault(name, "")` when the name is unset. Returns the sorted list of names it defaulted. The reason: DeerFlow's `resolve_env_variables` raises on any unset `$VAR`, even in stanzas for models that are not selected (16484-16488).

**`_bridge_module()` — 16500-16513**
- Returns `sys.modules[__name__]` when its `main is main`. Otherwise it returns a `types.ModuleType` snapshot of `globals()`, for harnesses that loaded the file without registering it.

**`_dispatch_v3_engine(question, out_dir, args, meta, plog, write_meta) -> int` — 16516-16562**
- Imports `linear_research` and calls `run(..., bridge=_bridge_module())` (16525-16531).
- A non-int (or bool) return value raises `TypeError` (16532-16534).
- Any `Exception`, including an import failure, → meta failed with `error="v3 engine failed: ..."` and a traceback, and rc=2 (16535-16541).
- A `BaseException` (KeyboardInterrupt or SystemExit) → marks meta failed only if it is not already failed, writes meta, and re-raises (16542-16551).
- On normal return, if meta is not terminal it sets `completed`/`failed` from rc and writes meta (16552-16559).
- `plog.close()` always runs, in `finally` (16560-16561).

### `main()` — 16570-17973 (ordered)

1. **CLI** (16571-16599):
   - mutually exclusive and required: `--prompt` or `--prompt-file`;
   - `--out-dir` (required);
   - `--model` (default `$DEERFLOW_RESEARCH_MODEL` or `"claude"`);
   - `--depth` ∈ {quick, standard, deep}, default `standard` (`DEPTH_PRESETS` keys);
   - `--thread-id`;
   - `--target-language` (default `$DEERFLOW_RESEARCH_LANGUAGE`);
   - `--no-actors`, `--subagents`, `--config`, `--resume`, `--extract-only`, `--evidence-only`, `--synthesis-manifest`.
2. `--evidence-only` together with `--synthesis-manifest` → `parser.error`, which is an argparse `SystemExit(2)` (16600-16601). Sets `os.environ["RESEARCH_EVIDENCE_ONLY"]="true"/"false"`, which is read at 4994 and 12349 (16602-16603).
3. Resolves the question from the file (`.strip()`) or inline. An empty question prints `ERROR` to stderr and returns **3**. Nothing is written yet; `out_dir` has not been created (16605-16612).
4. `out_dir = Path(...).expanduser().resolve()`, then `mkdir(parents=True, exist_ok=True)` (16614-16615). Atomically writes `prediction_requirement.txt` = question + "\n" (16620).
5. `plog = ProgressLog(out_dir/research_progress.log)`. The log is opened in append mode and echoes to stdout (4418-4469) (16622).
6. **Runtime skill sync:** `runtime_skill_sync_telemetry()` (480-515). This requires `DRF_RUNTIME_SKILL_SYNC` when `DRF_RUNTIME_SKILL_SYNC_REQUIRED` is set; otherwise the bundle is recorded as `standalone-unverified`. [verifier: `standalone-unverified` applies only when the payload is absent and not required (493-502). Whenever a payload is present, required or not, it is parsed and verified, and invalid JSON or a verification failure raises, which main turns into exit 3 (503-515, 16623-16647)]
   - On exception: writes a minimal failed `meta.json`, logs the error, prints it, and returns **3** (16623-16647).
   - Logs the verified manifest hashes and per-skill lazy-resource hashes, or a warn when the bundle is unverified (16648-16675).
7. **Engine:** `requested_engine = _resolve_research_engine(plog)`; `use_v3_engine = requested == "v3" and not legacy_only_mode`. A v3 request combined with a legacy-only flag logs that it is being routed to legacy (16678-16688).
8. **Skill activation telemetry:** `skill_activation_estimate()` (445-477), then the mode:
   - v3 → `none`;
   - extract-only → `none`;
   - synthesis-manifest → `resource-read` of `deep-research/references/final-dossier-contract.md`;
   - otherwise `slash` with `activated=True`.
   - Logs the slash payload size or the resource read (16689-16728).
9. `_reset_fetched_sources()` clears the fetched sources, flags, market pricing block, initial PM markets and transport flag, the pinned citation index, the delegation flag and the actor-track thread id (1311-1323) (16729). `_set_agentic_delegation(--subagents)` (16733). `thread_id = --thread-id or "research-<uuid12>"` (16734).
10. **Resume planning:**
    - v3 with `--resume` → only a log line, since v3 resumes from its own phase state (16741-16746).
    - Legacy with `--resume`, not extract-only, and `RESEARCH_CHECKPOINT` true: `load_research_checkpoint` → `plan_research_resume(ckpt, question, depth, expected run/attempt/lane from RESEARCH_BUDGET_RUN_ID/EPOCH/LANE_ID, expected_checkpoint_id=RESEARCH_CHECKPOINT_ID)` (16747-16760).
    - If the plan resumes: reuse its `thread_id` and completed passes, `seed_validated_resume_sources`, and adopt the prior `evidence_pack.md` if it parses and is not control-failure-only. `resume_info` is recorded (16761-16776). If not, `resume_info = {resumed: False, reason}` (16777-16779).
11. **Meta:**
    - Base fields: `status:"running"`, `thread_id`, `model`, `depth`, `question`, `started_at`, `target_language`, `skill_activation`, `runtime_skill_sync`, `workflow_mode` (evidence_only / global_synthesis / full) and `research_engine` (16780-16796).
    - `meta.resume` (16797-16798).
    - Extract-only of a v3 handoff merges the prior v3 meta minus volatile keys, forces `research_engine:"v3"` and adds `salvage:{mode:"extract_only", engine:"legacy", started_at}` (16799-16809).
    - Deep legacy runs record `deep_research_phases`, with the opening limit from `DEERFLOW_DEEP_OPENING_RECURSION_LIMIT` (default 300) and each phase from `_phase_budget` (16810-16820).
    - `write_meta()` atomically writes `meta.json`, and is first called here (16822-16825).
12. `logging.basicConfig(level=WARNING)` (16828). `_preset_provider_env_defaults(args.config)` (16836).
13. `_preflight_fail(msg, error)`: sets meta failed, writes meta, logs an error, closes plog, prints to stderr, returns **3** (16838-16844).
14. **Extract-only gate:** the existing report must have at least `_extract_only_min_chars()` characters after strip (`RESEARCH_EXTRACT_ONLY_MIN_CHARS`, default 400, 956-965); otherwise exit **3** (16849-16858).
15. **Credential preflight:**
    - A provider-keyed model with an empty key → exit **3** (16864-16869).
    - `claude`: needs `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_AUTH_TOKEN`, or a non-expired credential from `deerflow.models.credential_loader.load_claude_code_credential()`; otherwise exit **3** (16870-16884).
    - `codex`: needs `load_codex_cli_credential()`, or if that import fails, the existence of `$CODEX_AUTH_PATH` / `~/.codex/auth.json`; otherwise exit **3** (16885-16896).
16. **v3 dispatch** → `return _dispatch_v3_engine(...)` (16902-16903).
17. **Legacy try block** (16905-17958):
    - `--extract-only` → `return run_extract_only(...)` (16908-16909).
    - Imports `deerflow.client.DeerFlowClient` and builds it with `config_path`, `model_name`, `thinking_enabled=True`, `subagent_enabled=--subagents` and a skills whitelist {deep-research, actor-ontology-research, prediction-markets, forecast-visuals} (16911-16930).
    - **Resume verification:** completed passes without a durable pack → `collect_thread_evidence_parts(client, thread_id)`. If that is empty, it starts a fresh thread id, clears the skip set, and records `stale_thread_id` and `replacement_thread_id` in meta (16937-16963).
    - **PM pre-pass:** runs when not evidence-only, not synthesis-manifest, and both `PREDICTION_MARKETS_ENABLED` and `PREDICTION_MARKETS_PREPASS` are true (default true). `_pm_initial_snapshot` → `_set_initial_pm_markets` and `_set_market_pricing_block`. Failures are non-fatal (16969-16980).
    - **Stage 1** initial state (16988-16999): `dossier` is read from an existing `actor_dossier.md` only for synthesis-manifest, or for resume when not evidence-only. Then one of three branches runs:
      - **(a) `--synthesis-manifest`** (17000-17115):
        - `load_evidence_manifest` and `load_manifest_actor_dossier`, then `actor_dossier_synthesis_blocks` and `seed_manifest_sources` → `synthesize_from_evidence_parts`, then `_finalize_and_judge_report(context="global pre-judge")`.
        - If the scorecard is valid, not passing and has gaps: sanitize the gaps (at most 24000 chars), `pack_context_for_section(..., 60000, max_blocks=12)` and `run_incremental_report_patch(..., "global-judge-refine")`, then judge again.
        - It always writes the forensic sidecars `research_report_refinement_candidate.md` and `research_report_refinement_candidate_judge.json` (17089-17100). The patch is adopted only if `_report_scorecard_adoptable` (11579-11597) passes. [verifier: not always. The sidecars are written only when the patch returned a non-empty candidate that differs from the report (17071); they are then written whether or not the candidate is adopted (17089-17111)]
      - **(b) dual-track** when `_should_run_actor_track` is true, i.e. `DEERFLOW_DUAL_TRACK` (default true; 2282-2297) (17116-17237):
        - Track A is `run_research_stage(client, ..., thread_id, resume_completed, out_dir, resume_evidence_pack)`. Track B is `run_actor_ontology_stage(client, ..., thread_id+"-actor", out_dir)`.
        - `dual_workers = min(2, RESEARCH_MODEL_CONCURRENCY_GLOBAL//1)`. `RESEARCH_SEQUENTIAL_DUAL_TRACK=true` forces 1 (17120-17128).
        - Concurrent mode: Track A's join is bounded by `RESEARCH_TRACK_A_WALL_SECONDS` (default 10800, minimum 60). A Track A timeout propagates as a lane failure.
        - In evidence-only mode, Track A's pack is published durably before the Track B join (17189-17207).
        - Track B's join is bounded by `RESEARCH_TRACK_B_WALL_SECONDS`. A Track B timeout or exception leaves `dossier=""` and the run continues on a single track (17208-17221). The executor is shut down with `wait=False` (17223).
        - Sequential mode has no wall-clock bound (17224-17235).
      - **(c) single track:** `run_research_stage` (17238-17257).
    - **Evidence-only end** (17259-17383):
      - The pack is either the stage output or `render_evidence_pack([report])`, merged with the resumed pack. Sources come from `export_fetched_sources_for_manifest()`.
      - Zero sources with `RESEARCH_EVIDENCE_LANE_REQUIRE_SOURCES` (default true), or a pack containing only control failures → exit **2** (17273-17292). [verifier: both triggers need zero fetched sources. The condition is `not source_rows and (require_sources or control_failure_only)`, so a control-failure-only pack that has sources does not fail here (17275-17277)]
      - Writes `evidence_pack.md` and `sources.json` (17293-17294).
      - If `DEERFLOW_DUAL_TRACK` is set, the dossier must be usable. That means non-degraded (400 chars), not a control failure, and `actor_dossier_coverage_audit(... required_receipt_purpose="track-b", required_receipt_thread_id=_ACTOR_TRACK_THREAD_ID ...)` must report `accountable`. Otherwise exit **2** (17295-17341).
      - A usable dossier is written to `actor_dossier.md` and `actor_dossier_coverage.json`, with hashes in meta (17342-17365).
      - Completed, telemetry flushed, exit **0** (17366-17383).
    - **Safety-net synthesis:** if not synthesis-manifest, the stripped report is shorter than `_synthesis_trigger_chars(depth)` (deep: `SYNTHESIS_TRIGGER_CHARS_DEEP` = 15000; otherwise 4000; 667-678), and it is not a content-moderation block (`new_sensitive`/`unprocessable_entity`), run `synthesize_from_thread`. The result is adopted only if it is longer (17398-17407).
    - **RES-1 minimum length:** `RESEARCH_MIN_REPORT_CHARS`, default 400, or 2000 for deep (0 disables). An empty or too-short report → meta failed, exit **2** (17414-17428).
    - **LLM-error sentinel:** `looks_like_llm_error(report)` → exit **2** (17434-17439).
    - `unwrap_markdown_fence`, then `finalize_report_citations` (non-fatal) (17441-17447).
    - **Judge binding:** `judge_required = synthesis_manifest or (deep and RESEARCH_REPORT_JUDGE)` (17448-17451). It re-judges unless the report equals the last judged bytes with a valid scorecard (17452-17469). If `_judge_input_matches_report` fails, it writes `research_report_failure_candidate.md` and `..._judge.json` and raises `RuntimeError`, which becomes exit 2 (17470-17489).
    - Writes `research_report.md`, then `_record_persisted_report_identity`, which sets `meta.persisted_report_sha256` and `report_chars` (11790-11801). When the judge is required, `_persist_report_judge` writes `research_report_judge.json` with `_judged_prose.sha256` and sets `meta.research_report_judge`; a failure raises (17490-17505).
    - **Judge FAIL gate:** `judge_required and not report_passes(...)` → `meta.research_report_quality_gate = {passed: False, verdict, scores, gaps[:20]}`, meta failed, telemetry flushed, exit **2** (17506-17536).
    - **RES-8 dossier guard:** `_is_degraded_artifact(dossier, _min_report)` (10047-10057) → dossier cleared (17541-17543). A non-empty dossier is unwrapped and written to `actor_dossier.md`, `_live_actor_dossier_coverage_audit` is written to `actor_dossier_coverage.json`, and its hashes plus `actor_dossier_judge_sha256` go into meta (17548-17573).
    - **Stage 2 extraction** (17578-17834; skipped with `--no-actors`):
      - The input is the dossier plus the report, or the report alone. INT-1 appends `_pm_render_section(_INITIAL_PM_MARKETS)` when the pre-pass found markets (17586-17603).
      - Calls `extract_complete_structured_tool_free`. Rejected candidates are persisted, and recovery is recorded in meta (17604-17626).
      - `obj is None` → only a warn here; the final seal will fail (17627-17633).
      - Otherwise, in order:
        - source grounding via `merge_fetched_into_sources` (`RESEARCH_GROUND_SOURCES`) (17640-17651);
        - `_clamp_asof_reference` for the as-of date (17655-17659);
        - `RESEARCH_STALE_DAYS` (default 365) and `RESEARCH_RECENCY_WEIGHTING` (17660-17664);
        - `enforce_actor_cast` (17669-17672);
        - `actors.json` with its sha256 (17676-17682);
        - meta counts (17683-17686);
        - `timeline.json` (17689-17693);
        - `quantitative.json`: enrich, then reconcile, then recency annotation, then `flag_implausible_quant` (17697-17726);
        - `contested.json` (17730-17734);
        - `sources.json` with freshness and the `source_diversity` histogram (17735-17753).
      - **research_quality** (17759-17828):
        - reads `research_report_judge.json` as judge_sc;
        - `compute_coverage_gaps` (`RESEARCH_COMPLETENESS_PROBE`);
        - `audit_triangulation` (`RESEARCH_TRIANGULATION_AUDIT`) → `meta.single_origin_loadbearing`;
        - grounding ratio (`RESEARCH_QUALITY_GROUNDING`), halved after a "refused tool-free fabrication" flag, with a quant penalty of at most 0.15;
        - `compute_research_quality`;
        - folds `_RESEARCH_FLAGS` into `degraded`/`degradation`;
        - `RESEARCH_QUALITY_FLOOR` (default 0.45) only logs a warn.
      - Any exception in Stage 2 is logged as a warn (17829-17834).
    - **SCALE-5 triangulation top-up:** deep only, not synthesis-manifest, flagged claims exist, and `RESEARCH_TRIANGULATION_TOPUP` is true. `run_triangulation_topup` runs, and the result is adopted through `_adopt_judged_report_candidate(stage="triangulation-topup")` only if it is at least as long; meta identity is refreshed. Errors are non-fatal (17840-17869).
    - **Stage 3:** `_collect_prediction_markets(out_dir, question, report, ...)`, then `write_meta`. Errors are non-fatal (17875-17879).
    - **Stage 4:** `_render_research_charts`. Errors are non-fatal. `finally` refreshes the report identity and writes meta (17885-17894). A failed audit:
      - with `RESEARCH_VIZ_GATE_STRICT=true` → meta failed, exit **2**;
      - by default → `meta.visual_contract_shortfall` plus a warn, and the run continues (17896-17926).
    - **Final actor boundary:** re-reads the report from disk. Unless `--no-actors`, it calls `persist_final_actor_intelligence_contract(required=True, require_current_extraction=True, expected_unsealed_actors_sha256=...)`. Any raise → outer except → exit 2 (17933-17946).
    - Then: `meta.status="completed"`, `_research_budget.export_telemetry(force=True)`, a `done` log line, plog closed, return **0** (17948-17958).
18. **Outer except:** meta failed with error and traceback, telemetry flush, plog error and close (all guarded), stderr print plus traceback, return **2** (17960-17973).
19. **`__main__`:** flushes stdout and stderr, then `os._exit(rc)`. This skips the joins of non-daemon threads (wedged provider stream workers) and every atexit handler (17976-17986). [verifier: only when `main()` returns. A `BaseException` escaping `main()`, such as argparse's `SystemExit(2)` (16601), uncaught pre-try errors, or the v3 `KeyboardInterrupt`/`SystemExit` that `_dispatch_v3_engine` re-raises (16542-16551; v3 SIGTERM raises `RunTerminated(SystemExit(143))`, deerflow_bridge/linear_research.py:838-843, 6358-6364), never reaches `os._exit` at 17986, so normal interpreter shutdown still joins non-daemon threads]

## Control flow

- **Process entry:** `__main__` → `main()` → `os._exit` (17976-17986).
- **Before work:**
  - argparse → question → `prediction_requirement.txt` → `ProgressLog` → skill-sync check (exit 3 on failure);
  - `_resolve_research_engine` + `_legacy_only_mode` → telemetry → `_reset_fetched_sources` → resume plan → meta written → `_preset_provider_env_defaults`;
  - extract-only gate → credential preflight (16570-16896).
- **Dispatch** (one of three):
  - v3 → `_dispatch_v3_engine` → `linear_research.run` (16902-16903, 16516-16562). v3 calls back into `_collect_prediction_markets` and `_render_research_charts` (`deerflow_bridge/linear_research.py:5548-5551`).
  - extract-only → `run_extract_only` (16909): extraction → `_collect_prediction_markets` → `_render_research_charts` → optional seal.
  - legacy research: client → resume verification → `_pm_initial_snapshot` → Stage 1 (manifest | dual | single) → [evidence-only exit] → safety net → length and error gates → judge → report write → judge-FAIL gate → dossier write → Stage 2 → triangulation top-up → Stage 3 (`_collect_prediction_markets`) → Stage 4 (`_render_research_charts` → `embed_chart_refs`) → viz gate → final seal → completed.
- **Market internals:**
  - `_collect_prediction_markets` → `_load_tool_market_candidates` → [`_pm_resolve_queries` → `derive_market_queries_llm` | `_pm_derive_queries`] → `_pm_snapshot` → `_polymarket_get` → `_pm_normalize_market` → `_pm_cap_per_event`;
  - then → `_merge_market_rows` → `score_market_relevance` → `_apply_relevance_gate` | `_market_is_cited_in_report` → [`degrade_market_queries` loop] → write → `_strip_markdown_h2_section` + `_pm_render_section` → `_collect_market_price_history` → `_pm_yes_leg_token` → `_pm_fetch_price_history`.
- **Report mutation order on disk** (legacy):
  1. judged report written (17490);
  2. possible triangulation rewrite (17850-17864);
  3. PM section upsert (15712-15715);
  4. Visual Annex append (16014-16016);
  5. re-read for the seal (17933-17935).
- The judge's `_judged_prose.sha256` binds the pre-annex bytes. `meta.persisted_report_sha256` is refreshed to the final bytes (17892).

## Data & artifacts

All files live in `--out-dir`, the handoff directory. Writes are atomic: temp file, fsync, `os.replace` (76-95).

| File | Written / read | Anchor | Content |
|---|---|---|---|
| `prediction_requirement.txt` | W | 16620 | question + "\n" |
| `research_progress.log` | W (append) | 16622, 4426-4469 | `<iso> [kind] msg`; kinds used here: init/stage/ok/warn/error/resume/done |
| `meta.json` | W (many times) | 16822-16825 | status, thread_id, model, depth, question, started_at/finished_at, target_language, skill_activation, runtime_skill_sync, workflow_mode, research_engine, resume, deep_research_phases, report_chars, persisted_report_sha256, research_report_judge, research_report_quality_gate, actor_dossier_*, actors_count, relationships_count, has_situation_brief, timeline_count, quantitative_count, contested_count, sources_count, source_tiers, sources_fetched, source_freshness, quant_freshness, quant_unit_warnings, quant_implausible, source_diversity, coverage_gaps, single_origin_loadbearing, research_quality, research_degradation, triangulation_topup_applied, prediction_markets_count/as_of, prediction_market_price_history_count, charts_count, chart_quality_gate, visual_contract_shortfall, extract_only, salvage, actor_contract_mode, error/traceback |
| `research_report.md` | W/R | 17490, 15715, 16016 | judged dossier + `## Prediction Market Signals` + `## Visual Annex` |
| `research_report_judge.json` | W (via helper) / R | 17493-17503, 17764-17769 | scorecard + `_judged_prose{sha256,chars,stage,scope}` |
| `research_report_failure_candidate.md` / `_judge.json` | W | 17474-17485 | forensic copies when the judge is not bound to the final bytes |
| `research_report_refinement_candidate.md` / `_judge.json` | W | 17089-17100 | forensic copies of the global-refine attempt |
| `actor_dossier.md`, `actor_dossier_coverage.json` | W/R | 17344-17352, 17550-17558, 16993-16999 | Track B dossier + coverage audit |
| `actor_dossier_judge.json` | R (hashed) | 17362-17365, 17568-17571 | written by the Track B stage (14456) |
| `actors.json` | W/R | 17676-17682, 16230-16236, 15491-15505 | full extracted object (actors, relationships, key_events, quantitative_facts, contested_claims, situation_brief, hot_topics, context_entities) |
| `timeline.json`, `quantitative.json`, `contested.json`, `sources.json` | W | 17689-17753, 16241-16273 | promoted rows |
| `evidence_pack.md` | W/R | 17293, 17189-17196, 16765-16770 | evidence lane pack (`# Internal Evidence Lane Pack`) |
| `prediction_markets.json` | W | 15531-15534, 15558-15559, 15701-15707 | `{as_of, source, queries, markets[], status{attempted, query_count, successful_query_count, transport_failure_count, tool_observation_count, refresh_candidate_count, candidate_count, selected_count, empty_reason, transport_error_classes?}, no_relevant_markets?, reason?, tool_candidates_seen?, registry_sources?, horizon_degraded?, degraded_queries?}` |
| market row | — | 15015-15045 | market_id, exchange, question, implied_yes_prob, volume, liquidity, event_title, matched_query, url/event_url, end_date, one_day_price_change, best_bid/ask, outcomes, outcome_prices, clob_token_ids, clob_yes_token_id; plus relevance_score, captured_via, captured_at, tool_queries, report_cited, horizon_degraded |
| `prediction_market_candidates.jsonl` | R (last 4 MB) | 15361-15406 | `{captured_at, queries, markets}` per line |
| `market_price_history.json` | W | 15784-15785 | `{market_id: [{t:int, p:float}]}` |
| `charts.json` + `charts/*.png|html` | W by render.py, R here | 15981-15988; render.py:2095-2126 | `[{id,title,caption,source_data,data_class,path,html_path?}]` |
| `research_checkpoint.json` | R | 16748 | resume plan input |
| `actor_intelligence_lineage.json` | existence check | 16107 | decides the extract-only lineage validation |
| DeerFlow `config.yaml` | R | 16491-16493 | `$VAR` scan |

In-memory module globals used by this slice:
- `_PM_TRANSPORT_UNAVAILABLE` / `_PM_TRANSPORT_ERROR_CLASSES` (1226-1229, set at 1271-1274);
- `_INITIAL_PM_MARKETS` (1225);
- `_MARKET_PRICING_BLOCK` (1224);
- `_RESEARCH_FLAGS` (1201);
- `_ACTOR_TRACK_THREAD_ID` (1195);
- `_research_budget`, an optional `research_budget` module (66-73).

`_reset_fetched_sources()` resets all of these at the start of each run (1311-1323).

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| PREDICTION_MARKETS_WORKERS | 4 (1..8) | snapshot thread count | 15080 |
| PREDICTION_MARKETS_DEADLINE_SECONDS | 15 (≥1) | run-level snapshot deadline | 15085 |
| PREDICTION_MARKETS_TRANSPORT_FAILURE_BREAK_AT | 3 (≥1) | circuit threshold (with 0 successes) | 15090, 15147 |
| PREDICTION_MARKETS_HTTP_TIMEOUT_SECONDS | 8 (≥0.5) | per-request timeout (Gamma) | 14887-14891 |
| PREDICTION_MARKETS_HTTP_ATTEMPTS | 2 (1..5) | attempts per request | 14893-14896 |
| PREDICTION_MARKETS_MAX / ODDPOOL_MAX_MARKETS | 20 | max markets kept | 15256-15257 |
| PREDICTION_MARKETS_MIN_VOLUME | 200 | volume floor | 15261 |
| PREDICTION_MARKETS_MAX_PER_EVENT | 3 | per-event cap (≤0 disables) | 15265, 15050 |
| PREDICTION_MARKETS_PER_QUERY | 8 (1..50) | Gamma `limit_per_type` | 15274 |
| PREDICTION_MARKETS_MIN_RELEVANCE / PM_MIN_RELEVANCE | 5 | relevance floor 0-10 | 14773-14781 |
| PREDICTION_MARKETS_LLM_QUERIES | true | LLM query derivation | 15435 |
| PREDICTION_MARKETS_ENABLED | true | master switch (pre-pass + Stage 3) | 15484, 16972 |
| PREDICTION_MARKETS_PREPASS | true | pre-research snapshot + pass-0 pricing block | 16973 |
| PREDICTION_MARKETS_REFRESH_WITH_TOOL_CANDIDATES | false | also refresh when tool candidates exist | 15542-15543 |
| PREDICTION_MARKETS_HORIZON_RETRY | true | degraded-query retry ladder | 15631 |
| PREDICTION_MARKETS_PRICE_HISTORY | true | CLOB history | 15725 |
| PREDICTION_MARKETS_PRICE_HISTORY_MAX / _DAYS / _INTERVAL | 20 / 90 / "1d" | history caps | 15760, 15764, 15767 |
| RESEARCH_CHARTS_MIN | 3 (0 disables rendering) | chart minimum when visuals are explicit | 4656-4665, 15837, 15945 |
| RESEARCH_CHARTS_TIMEOUT | 180 | render.py timeout | 15857 |
| RESEARCH_CHARTS_PYTHON | (auto) | render interpreter | 15867 |
| RESEARCH_CHARTS_INCLUDE_DIAGNOSTICS / _CONTEXT | off | read by render.py (inherited env) | render.py:2017-2024 |
| RESEARCH_VIZ_GATE_STRICT | false | chart shortfall becomes exit 2 | 17909 |
| RESEARCH_ENGINE | unset → legacy (bridge) | v3/linear vs legacy/deerflow/agentic | 16389-16400 |
| DEER_FLOW_CONFIG_PATH / DEER_FLOW_PROJECT_ROOT | — | config candidates for the env scan | 16445-16452 |
| MINIMAX/DEEPSEEK/DASHSCOPE/ZHIPUAI/KIMI _API_KEY | preset "" | preflight + hygiene | 16366-16372, 16864-16869 |
| ANTHROPIC_API_KEY / CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_AUTH_TOKEN | — | claude preflight | 16871-16872 |
| CODEX_AUTH_PATH | ~/.codex/auth.json | codex preflight fallback | 16890-16891 |
| DRF_RUNTIME_SKILL_SYNC(_REQUIRED) | — | skill provenance (exit 3 on failure) | 480-515, 16623-16647 |
| DEERFLOW_RESEARCH_MODEL / DEERFLOW_RESEARCH_LANGUAGE | claude / none | CLI defaults | 16576, 16579 |
| RESEARCH_EVIDENCE_ONLY | written by main | read by prompt/stage code | 16602, 4994, 12349 |
| RESEARCH_CHECKPOINT | true | legacy resume switch | 911-913, 16747 |
| RESEARCH_CHECKPOINT_ID, RESEARCH_BUDGET_RUN_ID/EPOCH/LANE_ID | — | resume identity | 16754-16759, 916-928 |
| DEERFLOW_DEEP_OPENING_RECURSION_LIMIT | 300 (bridge) | meta deep phase record | 16814-16815 |
| RESEARCH_EXTRACT_ONLY_MIN_CHARS | 400 | extract-only gate | 956-965, 16852 |
| DEERFLOW_DUAL_TRACK | true | Track B ownership | 2282-2297, 17116, 17295 |
| RESEARCH_MODEL_CONCURRENCY_GLOBAL | 12 | dual_workers = min(2, slots) | 4538-4545, 17120 |
| RESEARCH_SEQUENTIAL_DUAL_TRACK | false | force sequential A then B | 17127 |
| RESEARCH_TRACK_A_WALL_SECONDS / _B_ | 10800 (≥60) | join timeouts (concurrent mode only) | 17169-17181, 17209-17210 |
| RESEARCH_EVIDENCE_LANE_REQUIRE_SOURCES | true | evidence lane needs fetched sources | 17273-17274 |
| SYNTHESIS_TRIGGER_CHARS_DEEP | 15000 (deep) / 4000 const | safety-net trigger | 660-678, 17402 |
| RESEARCH_MIN_REPORT_CHARS | 400 (2000 deep); 0 disables | minimum report length | 17414-17419 |
| RESEARCH_REPORT_JUDGE | true | deep final judge required | 17450 |
| RESEARCH_GROUND_SOURCES | true | fetched-URL grounding | 17640 |
| RESEARCH_STALE_DAYS | 365 | recency annotation | 17661 |
| RESEARCH_RECENCY_WEIGHTING | true | freshness annotation | 17664 |
| RESEARCH_QUANT_ENRICH / RESEARCH_QUANT_RECONCILE | true / true | quant enrichment / reconcile | 17701, 17709, 16249, 16255 |
| RESEARCH_SOURCE_DIVERSITY | true | jurisdiction histogram | 17740 |
| RESEARCH_COMPLETENESS_PROBE / RESEARCH_TRIANGULATION_AUDIT | true / true | coverage gaps / single-origin audit | 17770, 17775 |
| RESEARCH_QUALITY_GROUNDING | true | grounding component | 17786 |
| RESEARCH_QUALITY_FLOOR | 0.45 | warn only | 17820-17826 |
| RESEARCH_TRIANGULATION_TOPUP | true | deep top-up pass | 17844 |

## External calls

- **HTTP (keyless, stdlib urllib):**
  - Gamma `GET https://gamma-api.polymarket.com/public-search?q=..&limit_per_type=..&events_status=active` (15101-15103; base at 14507; transport at 14878-14925);
  - CLOB `GET https://clob.polymarket.com/prices-history?market=<token>&interval=<interval>`, 15 s timeout (14962-14975, 15778).
- **LLM (bare, tool-free, via `_bare_synth_invoke`, 6602):**
  - market query derivation (14754-14770);
  - market relevance scoring (14837-14870), called up to 1 + 2 times per `_collect_prediction_markets` (15585, 15650) and once in the pre-pass (15472).
  - Legacy main also drives these through callees:
    - DeerFlow client research turns: `run_research_stage` 12331, `run_actor_ontology_stage` 14133;
    - `synthesize_from_thread` 8140, `synthesize_from_evidence_parts` 7998;
    - `judge_research_report` via `_finalize_and_judge_report` 11730-11749;
    - `run_incremental_report_patch` 12142;
    - `extract_complete_structured_tool_free` 9116;
    - `run_triangulation_topup` 12259.
- **Subprocess:** `[py, skills/(public/)forecast-visuals/scripts/render.py, --dir, out_dir]`, 180 s timeout (15966-15969).
- **Imports at runtime:**
  - `deerflow.client.DeerFlowClient` (16912);
  - `deerflow.models.credential_loader.load_claude_code_credential` / `load_codex_cli_credential` (16875, 16887);
  - `linear_research` (16526);
  - `runtime_skill_sync` (508, inside `runtime_skill_sync_telemetry`).
- **DB:** none directly. `_research_budget.export_telemetry(force=True)` flushes cross-process lease telemetry (17374-17376, 17531-17533, 17953-17955, 17964-17966).

## Cross-module edges

**Callers into this slice** (from grep):
- `backend/app/services/pipeline_orchestrator.py:2251-2264`: the main research subprocess. It always sets `RESEARCH_ENGINE` explicitly to `v3` or `legacy` (`:2295-2301`) and forces legacy for evidence-only and synthesis-manifest. For v3 it exports `DEERFLOW_RESEARCH_TIMEOUT`.
- `pipeline_orchestrator.py:3768-3776`: the `--extract-only` salvage subprocess. It reuses `prediction_requirement.txt` as `--prompt-file` and is bounded by `RESEARCH_EXTRACT_ONLY_TIMEOUT` (default 600).
- `pipeline_orchestrator.py:2618-2619`: any non-zero exit is a failure unless the timeout was salvaged. The parent does not tell 2 from 3.
- `deerflow_bridge/linear_research.py:5548-5551` calls `_collect_prediction_markets` and `_render_research_charts` through `bridge_call`. It ignores the returned chart audit.
- Tests that exercise the slice:
  - `backend/tests/test_bridge_prediction_markets.py`: `_pm_snapshot` 168/188/255; `_pm_render_pricing_block` 489; `_market_is_cited_in_report` 1146; `_load_tool_market_candidates` 1169; `_pm_yes_leg_token` 1261; `_collect_market_price_history` 1292.
  - `backend/tests/test_bridge_overhaul_v3.py`: `_resolve_research_engine` 128/135/1002; `_config_env_references` 340; `_deerflow_config_candidates` 348; `_preset_provider_env_defaults` 366; `_strip_markdown_h2_section` 848.
  - `test_wave9_research_quality.py` and `test_sessionb_research_viz.py`: `embed_chart_refs`, `_visual_contract_requirements`.
  - `test_audit_fixes_research.py:73-85`: `_visual_contract_audit`.
  - `test_research_checkpoint.py` and `test_actor_intelligence_producer.py`: `run_extract_only`.

**Calls out of the slice:**
- Market helpers 14539-15061.
- Judge helpers 11394-11830.
- Extraction and analytics: 2129, 2497, 9116, 9187-9913.
- Actor intelligence: 3926, 4002, 4131, 13456, 13883.
- Evidence and resume: 997, 1011, 7115-7171, 7337-7998, 10025-10031.
- Skill telemetry: 445, 480.
- `ProgressLog` 4418.

## Invariants, gates, validation

- **Exit codes** (docstring 34-41):
  - 0 = success: legacy complete (17958), evidence lane (17383), extract-only (16358), v3 rc 0.
  - 3 = preflight failure: empty question (16612), skill sync (16647), extract-only report too small (16854), missing credential (16866, 16880, 16893).
  - 2 = runtime, judge or contract failure (17292, 17340, 17428, 17439, 17536, 17918, 17973, 16124, 16287, 16352, 16541).
- `meta.json` is written as soon as the meta dict exists (16825). Every handled terminal path sets `status` and `finished_at` before returning. `_dispatch_v3_engine` guarantees a terminal status (16552-16559).
- The credential preflight and env hygiene always run before the v3 dispatch or any client construction (16836-16903).
- A report is published only if:
  - it reaches the minimum length (17421);
  - it is not an LLM error string (17434);
  - when the judge is required, the judge was bound to exactly these bytes (17470) and passes (17506).
- Market rows must have a price strictly inside (0,1), be open, and reach the minimum volume (14988-15000). The YES leg is never guessed (15741-15749).
- `prediction_markets.json` is always written once Stage 3 passes the enabled check: with markets, with an empty marker, or with the transport short-circuit (15531, 15558, 15701, 15706).
- Degraded-horizon candidates are fail-closed when no scores come back (15651-15653). Agent-tool candidates are fail-closed without scores unless cited (15594-15603).
- Diagnostic charts never enter the report (15901). The annex never duplicates a path already in context (15905-15906).
- The actor seal happens after the last report mutation (17928-17946; 16304-16337). Extract-only fails closed before markets and charts (16279-16287).

## Failure modes & recovery

- **Polymarket outage:**
  - The pre-pass opens the circuit, then Stage 3 skips its refresh and writes a `transport_failure` marker (15455-15465, 15509-15541).
  - Each snapshot is bounded by the 15 s deadline (15115-15121).
  - Price history has no overall deadline: it runs serially with a 15 s timeout and up to 2 attempts per market (15769-15780, 14966-14973).
- **Relevance scorer failure:** fail-open for deterministic rows; fail-closed for tool rows (unless cited) and for degraded rows (15589-15610, 15651).
- **Renderer missing, timing out or failing:** an empty audit; the run continues unless strict (15957-15998, 17896-17926).
- **Track B failure or timeout:** `dossier=""` and the run continues on a single track (17211-17237). But with actors enabled, the final seal requires an accountable dossier (4266-4281), so the legacy run still exits 2 at 17937-17946 (see Surprises). [verifier: correct for a Track B failure in dual-track mode, because the Track B result always overwrites `dossier` (17209-17221, 17232-17235). See the Surprise 4 note for the single-track exceptions]
- **Track A timeout:** `concurrent.futures.TimeoutError` → outer except → exit 2 (17180-17181, 17960-17973). In evidence-only mode the pack was already published early (17189-17207).
- **Resume with a missing checkpoint context:** the run replays on a new thread (16937-16963).
- **Watchdog SIGKILL after the report is written:** the parent runs `--extract-only` (`pipeline_orchestrator.py:3734-3776`). That path keeps the v3 meta provenance (16799-16809).
- **Interpreter hang from wedged stream workers:** avoided by `os._exit` (17976-17986). [verifier: only on a normal return from `main()`. A v3 SIGTERM unwinds as `SystemExit(143)` re-raised through `_dispatch_v3_engine` (16542-16551), and `KeyboardInterrupt` unwinds the same way; neither reaches 17986, so non-daemon threads are joined at shutdown]

## Surprises

1. **Engine default diverges between bridge and parent.** Unset or unknown `RESEARCH_ENGINE` resolves to **legacy** in the bridge (16389-16400) but to **v3** in the orchestrator (`pipeline_orchestrator.py:5906-5935`). `README.md:461` and `.env.example:140` both say v3 is the default. Orchestrated runs are safe because the parent always sets the variable explicitly (`pipeline_orchestrator.py:2301`). A direct CLI run without the variable silently uses legacy.
2. **Suspected: the price-history window is 1 day, not 90.** The default `interval="1d"` (15767) is a CLOB **look-back window**; the backend documents it as "回看窗口档位: 1h/6h/1d/1w/1m/max" at `backend/app/utils/prediction_markets.py:425`. The client-side 90-day trim (14938-14958) therefore removes nothing, yet the log says "≤90d @ 1d" (15786-15787), and `README.md:689` and `DRF_ARCHITECTURE.md:559` promise a 90-day series. This is not verified against the live API.
3. **Suspected: the legacy full path does not fail closed early when extraction fails.** When `obj is None` it only warns (17627-17633). It then still runs triangulation top-up, market LLM calls and network fetches, and chart rendering, and only fails at the final seal (17936-17946, which raises on the empty fingerprint at 4199-4205). `run_extract_only` deliberately fails closed before markets and charts (16279-16287). [verifier: triangulation top-up does NOT run. It needs `meta.single_origin_loadbearing` (17841-17844), which is set only inside the `obj is not None` branch (17775-17778). Markets and charts do still run. In a fresh out_dir the seal fails earlier, on the missing actors.json (4164-4166). The empty-fingerprint failure (4198-4205) applies only when a stale actors.json from an earlier attempt exists, and charts may then render from those stale files]
4. **Suspected: the single-track degrade cannot succeed with actors enabled.** The log says "continuing single-track" (17221, 17237, 17542), but with actors enabled and no `--no-actors`, `persist_final_actor_intelligence_contract` requires an accountable dossier (4266-4281). A legacy run whose Track B failed, or that runs with `DEERFLOW_DUAL_TRACK=false`, therefore ends with exit 2. Extract-only has an explicit report-only mode for this case (16312-16325); main does not. [verifier: overstated for `DEERFLOW_DUAL_TRACK=false`. A single-track run with `--resume` (not evidence-only) seeds `dossier` from an existing actor_dossier.md (16993-16999), and the single-track branch never overwrites it (17238-17257). A `--synthesis-manifest` run takes its dossier from the manifest (17003-17005). Either can still pass the seal. The Track-B-failure case holds as stated]
5. **Dead branch.** The `else` branch at 17238-17245 logs "evidence-only: optional Track B is disabled" only when `DEERFLOW_DUAL_TRACK` is true. That branch is only reached when `_should_run_actor_track`, which reads the same flag (2297), is false, so the message can never print.
6. **`deadline_exhausted` is mislabelled.** It is set whenever `len(completed) < attempted` (15182-15183). That includes the early circuit break at 15147, so an open circuit also reports `deadline_exhausted=1`.
7. **The transport short-circuit hard-codes `transport_failure_count: 1` and `query_count: 0`** (15518-15521), whatever the pre-pass actually attempted.
8. **`PREDICTION_MARKETS_ENABLED=false` writes no `prediction_markets.json` at all** (15484-15486). Every other empty path writes an explicit marker (the "PM-HZ always write" contract at 15550-15551 and 15698-15699).
9. **Partial relevance scores pass unscored rows.** `_apply_relevance_gate` keeps rows that have no score (14822-14828). The "fail-closed" treatment of tool and degraded candidates therefore only applies when the score map is entirely empty (15586, 15651), not when the LLM omits some IDs.
10. **The visual "explicit" detection uses substring matches** (15810-15813). "chart" matches "charter"/"chartered", and "figure" matches "figure out" and "sales figures". Such questions demand at least 3 decision charts, which yields `visual_contract_shortfall` (a warn), or exit 2 under `RESEARCH_VIZ_GATE_STRICT`.
11. **Annex placement on re-runs.** `embed_chart_refs` detects an existing annex with a substring test (15909). It then appends new entries at the end of the report with no header. If an earlier `## Visual Annex` is followed by a freshly upserted `## Prediction Market Signals` section (15713-15714 appends at EOF), the new `### chart` entries land under the market section. This is suspected and only happens in salvage or resume flows. [verifier: the mechanism is real (15713-15714, 15909, 15928), but it is narrower than stated. Legacy `--resume` regenerates the report in Stage 1, so it carries no prior annex; the extract-only salvage path (it reads the report from disk at 16096-16097) is the one exposed. Only charts whose `](path)` is not already in the report get appended (15905-15906), so only a newly rendered chart id lands misplaced]
12. **`_market_is_cited_in_report` docstring drift.** The docstring says title tokens must be backed by the exact probability (15321-15322), but 4 or more overlapping tokens are enough on their own (15347-15348). The token set is ASCII-only (15310), so markets cited only in a Chinese-language report rarely match unless the URL or ID appears.
13. **`_merge_market_rows` has a dead `overwrite` flag**, always True (15413).
14. **Doc and default drift in `.env.example`:**
    - `PREDICTION_MARKETS_PER_QUERY=15 (8→15)` at `.env.example:458`; the bridge default is 8 (15274).
    - `PREDICTION_MARKETS_HTTP_TIMEOUT_SECONDS=3 # 默认只试 1 次` at `.env.example:650`; the code defaults to 8 s and 2 attempts (14887-14896).
    - "连续 transport failures" (consecutive failures) at `.env.example:653`; the code counts total failures with zero successes (15147).
    - `RESEARCH_MIN_REPORT_CHARS=400` at `.env.example:528`; the deep default is 2000 when unset (17414).
    - These knobs read in the slice are not documented in `.env.example`: `RESEARCH_VIZ_GATE_STRICT`, `RESEARCH_SEQUENTIAL_DUAL_TRACK`, `RESEARCH_TRACK_A/B_WALL_SECONDS`, `PREDICTION_MARKETS_PREPASS`, `PREDICTION_MARKETS_LLM_QUERIES`, `PREDICTION_MARKETS_REFRESH_WITH_TOOL_CANDIDATES`, `PREDICTION_MARKETS_HTTP_ATTEMPTS`.
15. **Opening recursion limit defaults differ.** `meta.deep_research_phases` uses a bridge default of 300 (16815). Orchestrated runs receive `Config.DEERFLOW_DEEP_OPENING_RECURSION_LIMIT` (default 400, `backend/app/config.py:1556`; `pipeline_orchestrator.py:2321-2322`), and the orchestrator comment there still says "默认 220".
16. **argparse exit-code collision.** argparse usage errors, including the `--evidence-only`/`--synthesis-manifest` conflict (16600-16601), exit with **2**, the code documented as "report not produced". Failures before the try block exit **1** with a traceback and no meta: an unreadable `--prompt-file` (16607), `mkdir` (16615), or `ProgressLog` open (16622).
17. **Legacy extract-only replaces the prior meta.** Only a **v3** prior meta is merged into salvage meta (16422-16430, 16799-16809). A legacy handoff's earlier `meta.json` (judge summary, research_quality, persisted_report_sha256 and so on) is overwritten by a fresh meta at 16825.
18. **Low-confidence race.** An abandoned Track B worker after a wall-clock timeout (17211-17218, `shutdown(wait=False)` at 17223) keeps using the shared client and module-global collectors while main continues to Stage 2. It may also write `actor_dossier_judge.json` late (14456). This has not been observed; it is inferred from the code.
19. **Background work is abandoned at exit.** `__main__` uses `os._exit` (17986), so any thread still running from `_pm_snapshot` (15151-15152) or Track B is killed without cleanup, and atexit handlers do not run. This is intended (17978-17983).
20. **`meta.charts_count` overcounts.** It counts every manifest entry, including diagnostic and pre-existing agent entries (15999), and the "embedded N chart(s)" log uses the same count (16018). The real number embedded can be smaller.

## Verification

Adversarial verification on 2026-10-11 against `main` as checked out on disk. All anchors are `deerflow_bridge/deerflow_research.py` unless another path is given. The verifier was read-only apart from this file: it ran no backend, pipeline, network or LLM calls. Inline `[verifier: ...]` notes above mark each statement it corrected.

**Verdict counts (51 verdicts):**

| Group | Confirmed | Imprecise | Refuted | Unverifiable |
|---|---|---|---|---|
| Key claims (15) | 13 | 2 | 0 | 0 |
| Key surprises (16) | 12 | 3 | 0 | 1 |
| Spot-checks of Walkthrough/Control flow (20) | 13 | 7 | 0 | 0 |

**Non-confirmed key claims:**
- **Fail-open market fallback (claim 4).** A tool candidate whose ID also came back in the refresh is kept with no citation check and is not tagged `report_cited` (15594-15610). The citation test also accepts title-token overlap of 2 or more plus the exact probability, not only URL, ID or 4 or more tokens (15350-15358).
- **`_render_research_charts` never raises (claim 9).** Only `TimeoutExpired` is caught around `subprocess.run` (15965-15974). An `OSError` launching the interpreter, or a `UnicodeDecodeError` re-reading the report (16013; only `OSError` is caught at 16019), propagates to the caller.

**Non-confirmed key surprises:**
- **Legacy extraction failure (surprise 3).** The triangulation top-up does not run when extraction fails, because it needs `meta.single_origin_loadbearing` (17841-17844), which is only set when extraction succeeds (17775-17778). In a fresh out_dir the seal fails on the missing actors.json (4164-4166) before the fingerprint check (4198-4205).
- **Single-track degrade (surprise 4).** This is overstated for `DEERFLOW_DUAL_TRACK=false`. A resumed single-track run keeps an existing actor_dossier.md (16993-16999, 17238-17257), and a synthesis-manifest run uses the manifest dossier (17003-17005). The Track-B-failure case holds.
- **Annex placement (surprise 11).** The mechanism is real, but legacy `--resume` regenerates the report, so in practice only extract-only salvage (16096-16097) is exposed, and only for chart paths not already referenced (15905-15906).
- **Price history (surprise 2): unverifiable offline.** Every code anchor checks out: the default is `"1d"` (15767); the backend docstring calls the value a look-back window (`backend/app/utils/prediction_markets.py:425`); `README.md:689` and `DRF_ARCHITECTURE.md:559` promise 90 days. Whether the live CLOB API returns only one day needs a live call.
- **Nuance on surprise 6.** `deadline_exhausted` is mislabelled on a circuit break only when futures were still pending. If every submitted query had already completed, it is not set (15182-15183).

**Non-confirmed spot-checks:**
1. **PM table header.** The header has no ` (market_id)`; only the data rows do (15231, 15241-15244).
2. **`_merge_market_rows` order.** All secondary IDs, shared ones included, keep their first-seen slots ahead of primary-only IDs (15413-15427).
3. **Actor query reservation.** `_pm_derive_queries` reserves `min(2, len(actors))` slots, not "at least 2" (14633-14634).
4. **Skill sync.** A payload that is present is always verified, even when not required; bad JSON or a verification failure means exit 3 (493-515).
5. **Global-refine sidecars.** They are written only when the patch produced a changed, non-empty candidate (17071, 17089-17100).
6. **Evidence lane failure.** Both triggers need zero fetched sources: `not source_rows and (...)` (17275-17277).
7. **`os._exit` hard exit.** It only runs when `main()` returns. `BaseException` paths skip it: argparse `SystemExit`, uncaught pre-try errors, and the v3 `KeyboardInterrupt`/`SystemExit(143)` that is re-raised at 16542-16551 (`deerflow_bridge/linear_research.py:838-843, 6358-6364`).

**Omissions (important behavior the map does not state):**
1. **Self-certifying citations on salvage.** In the no-scores fallback, `_market_is_cited_in_report` runs on the passed-in report before the old `## Prediction Market Signals` section is stripped (15598-15602 vs 15713). That old table prints every market_id and question (15241-15244). On extract-only salvage, tool candidates listed in a prior machine-written table therefore count as "cited".
2. **Shared event URLs.** Rows set `url`/`event_url` to the event page (15009-15013; `deerflow_bridge/market_tools.py:133-139`). The check is a plain substring test (15328-15331). Citing one event page therefore vouches for every sibling market in that event, and a longer slug URL also matches a shorter one it contains.
3. **Hard exit only on normal return.** `os._exit` runs only when `main()` returns (17977-17986). The SIGTERM, KeyboardInterrupt and argparse paths go through normal interpreter shutdown, which joins non-daemon threads.
4. **Further uncaught failures outside any try.**
   - Resume planning I/O, such as the evidence-pack `read_text` at 16767, runs before meta exists.
   - The extract-only gate's `read_text` (16851) runs after meta.json was written as `running` (16825). A non-UTF-8 report there exits 1 with meta stuck at `running`.
   - No outer handler covers 16648-16903 (only skill sync is wrapped, at 16623-16647).
5. **Suspected: Stage 2 can fail after actors.json is written.** An exception after actors.json is written and fingerprinted (17676-17682) still lets the seal match the fingerprint, despite the "will fail closed" warning (17829-17834). For example, `reconcile_quantitative` at 17710 has no guard of its own, unlike extract-only (16255-16259). quantitative.json, contested.json and sources.json may then be missing or stale. The source-bound dossier audit in the seal (4266-4281) may still catch a missing ledger.
6. **No horizon retry for tool-only runs.** When only tool candidates exist (`queries=[]`, 15544-15548), `degrade_market_queries([])` yields no stages (14675-14687), so the run gets no horizon-degradation retry.
7. **render.py exit 2 is treated as a failure.** render.py exits 2 when this run produced no new chart, even though it still rewrites and merges an existing charts.json (`deerflow_bridge/skills/forecast-visuals/scripts/render.py:2120-2132`). The bridge treats that as a failure (15976-15980): it returns the empty audit and embeds nothing.
8. **`_extract_only_min_chars` docstring drift.** The docstring says invalid or non-positive values fall back to 400, but the code clamps non-positive values to 1 (956-965).
