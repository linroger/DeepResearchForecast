# Handoff — backtest mode: measurable forecast accuracy without hindsight leakage

**Last Updated (UTC):** 2026-10-20T15:40Z
**Status:** In Progress
**Current Focus:** implement the cutoff module and its search/fetch integration.

The words MUST, SHOULD and MAY are used as in RFC 2119.

## 1) Request & Context
- **Request (from the session that started this one, 2026-10-20):** make DeepResearchForecast's forecast accuracy measurable without hindsight leakage; design it, record the design, implement it. Build a backtest mode, opt-in and off by default so live runs stay byte-identical: (1) an as-of cutoff through the v3 research engine for search/fetch (provider date filters where available, page dates otherwise; undated sources recorded and excluded in strict mode), official data (observations and vintages at or before the cutoff) and markets (price history at the cutoff, never current prices); (2) document model-knowledge leakage, add `knowledge_cutoff` to golden questions and report post-cutoff questions separately; (3) a driver that runs a question set end to end at a cheap backtest profile, maps binary forecasts to golden ids and writes `eval_report.json` with Brier, log score, ECE and an ablation flag set (research only, + markets, + simulation, + world channel); (4) forward testing: document and test `RESOLUTION_MONITOR_AUTORUN_HOURS`, plus a 2–12-week question template.
- **Constraints:** never modify the deployment checkout `/Users/rogerlin/Downloads/DeepResearchForecast` or its uploads (live pipelines on 5001/5013; reading its ledger is fine); use its venv `backend/.venv/bin/python`; run suites on frozen rsync copies without `backend/uploads`; no paid runs and no pushes without the owner's approval; `git` with `env -u GH_TOKEN -u GITHUB_TOKEN`.
- **Branch:** `claude/goofy-leakey-15afc1` (worktree `.claude/worktrees/goofy-leakey-15afc1`), cut from `main` ac48891.
- **Design:** [design.md](design.md) (recorded before any code).

## 2) Requirements → Acceptance Checks
| Req | Acceptance check | Expected | Evidence |
|---|---|---|---|
| R0 live byte-identical | Without `backtest_v1`, every touched function returns what it returned before (search payload/cache key, fetch path, data request/key, market rows, report re-quote, ledger append, research env) | identical outputs; full plain suite green | targeted "no policy" tests + plain suite |
| R1a search cutoff | Firecrawl payload carries `tbs cdr:1,cd_max` + `news`; rows dated after the cutoff dropped; undated rows kept+flagged (lenient) / dropped (strict); cache keys namespaced | fixture payloads with dated, undated and after rows | `test_backtest_cutoff.py`, `test_backtest_search_fetch.py` |
| R1b fetch cutoff | archive capture ≤ cutoff read instead of the live page; capture after cutoff rejected; live page modified after cutoff refused; undated page refused in strict, flagged in lenient; audit lines written | fake CDX + fake fetch | `test_backtest_search_fetch.py` |
| R1c plan date | v3 plan as-of = cutoff; invalid policy fails the run; work-dir identity carries the tag | engine fixture | `test_backtest_engine.py` |
| R1d official data | FRED API args carry `vintage_dates`; windows end at the cutoff; strict lag rule; projections dropped; cache key differs | fake MCP hub | `test_backtest_official_data.py` |
| R1e markets | research snapshot searches all events, keeps markets open at the cutoff, prices from history at the cutoff, strips post-cutoff fields; report does not re-quote or fall back | fake Gamma/CLOB | `test_backtest_markets.py` |
| R2 knowledge cutoff | golden questions carry `knowledge_cutoff`; scorer splits post/pre model cutoff and unknown | golden set + scorer tests | `test_golden_eval.py` |
| R3 driver | id mapping (golden_id, proposition_id, id, lexical, negation refusal, ambiguity); per-arm Brier/log/ECE + deltas; resumable run manifest with fake transport; paid run refused without confirmation | offline fakes | `test_backtest_eval.py` |
| R4 forward testing | autorun on with the documented setting starts the loop; forward template validated (14–84 days); forward-score over resolution files | offline | `test_backtest_eval.py`, `test_resolution_autorun.py` |
| R5 isolation | backtest forecasts not appended to the production ledger; monitor skips backtest reports; `forecast.json` has a `backtest` block | report agent + monitor tests | `test_backtest_report_stage.py` |
| R6 suite | plain backend suite on a frozen rsync copy: 0 failures apart from the 19 known `test_legacy_official_data.py` errors | | §8 |
| R7 docs | README EN/ZH line-aligned describe backtest mode | `wc -l` equal; section present in both | §8 |

## 3) Plan & Decomposition
1. `deerflow_bridge/backtest_cutoff.py` (pure, stdlib) — the policy, dates, verdicts, filters, Wayback lookup, observation rule, market as-of rule, audit sink. Highest uncertainty (date parsing, CDX semantics), no dependencies, so first.
2. Search (`search_tools.py`) and fetch/search rendering (`research_gateway.py`), engine wiring (`linear_research.py`).
3. Official data (`data_sources.py`).
4. Markets in the bridge (`deerflow_research.py`) and the report agent.
5. Backend policy (`backtest_mode.py`), orchestrator admission + research env, SDK API, report agent knobs (markets, simulation effect, pinned target, ledger skip), world-channel knob, resolution-monitor skip.
6. Golden `knowledge_cutoff` + scorer split.
7. Driver (`backend/scripts/backtest_eval.py`) + forward template.
8. README EN/ZH, frozen plain suite, commit.

## 4) To-Do & Progress Ledger
- [x] Map the code paths (research engine, search/fetch, data, markets, report, ledger, monitor) — 2026-10-20.
- [x] Verify the free public APIs the design depends on (no paid calls): Wayback CDX `to=…&limit=-1&fastLatest=true` returns the last capture at or before `to`; Polymarket Gamma `public-search` without `events_status` returns closed events with `startDate`, `closedTime`, current `outcomePrices` (the outcome, so it must be stripped); CLOB `prices-history?market=…&startTs=…&endTs=…&fidelity=60` returns hourly points up to `endTs` (Trump YES at 0.59 on 2024-11-01 23:00 UTC); Firecrawl docs: `tbs` supports `cdr:1,cd_min:MM/DD/YYYY,cd_max:MM/DD/YYYY`, news rows carry `date`; deployed FRED MCP build accepts `vintage_dates`.
- [x] Design recorded ([design.md](design.md)).
- [ ] Steps 1–8 of §3.

## 5) Findings, Decisions, Assumptions
- **Finding:** every golden question resolved by 2025-02-09, before the training cutoff of any model the pipeline uses in 2026, so the whole retrospective set measures, at best, an upper bound of skill. Decision: report the knowledge split explicitly; clean numbers come from forward testing.
- **Finding:** the report stage re-quotes market prices live (PM-3) and falls back to a live market search; both leak the outcome in a retrospective run. Decision: backtest reports never contact the market API.
- **Finding:** the Gamma API returns resolved markets with `outcomePrices` `["1","0"]`: a field copied from a resolved market reveals the answer. Decision: the as-of market row is rebuilt from an allow-list, never by deleting fields from the live row.
- **Decision:** one parent-owned env var for the research child, removed from ambient env on every launch (live runs cannot inherit it).
- **Decision:** backtest mode supports only the v3 research engine and the OASIS simulation engine; admission refuses others (fail closed).
- **Decision:** each ablation arm is its own pipeline (no stage sharing) in v1; cost noted as a follow-up.
- **Assumption:** Firecrawl's `cdr` filter limits results to pages Google dates within the range; falsification: own-date filtering runs on every row anyway, so a leaky provider filter cannot admit a dated-after row.

## 6) Issues, Mistakes, Recoveries
- (none yet)

## 7) Scenario-Focused Resolution Tests
- (filled as slices land)

## 8) Verification Summary
- (filled as slices land)

## 9) Remaining Work & Next Steps
- Paid live acceptance run: proposal to be written here once the code is in.

## 10) Updates to This File (append-only)
- 2026-10-20T15:40Z: created with request, requirements, plan, API verification and first decisions.
