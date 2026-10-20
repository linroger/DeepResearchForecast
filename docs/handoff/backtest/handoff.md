# Handoff — backtest mode: measurable forecast accuracy without hindsight leakage

**Last Updated (UTC):** 2026-10-20T18:10Z (2026-10-21 02:10 +08)
**Status:** Complete for the offline scope; the paid live acceptance run and forward testing await the owner's approval (§9).
**Current Focus:** none in this session; next step is the live run proposed in §9.

The words MUST, SHOULD and MAY are used as in RFC 2119.

## 1) Request & Context
- **Request (from the session that started this one, 2026-10-20):** make DeepResearchForecast's forecast accuracy measurable without hindsight leakage; design it, record the design, implement it. Build a backtest mode, opt-in and off by default so live runs stay byte-identical: (1) an as-of cutoff through the v3 research engine for search/fetch (provider date filters where available, page dates otherwise; undated sources recorded and excluded in strict mode), official data (observations and vintages at or before the cutoff) and markets (price history at the cutoff, never current prices); (2) document model-knowledge leakage, add `knowledge_cutoff` to golden questions and report post-cutoff questions separately; (3) a driver that runs a question set end to end at a cheap backtest profile, maps binary forecasts to golden ids and writes `eval_report.json` with Brier, log score, ECE and an ablation flag set (research only, + markets, + simulation, + world channel); (4) forward testing: document and test `RESOLUTION_MONITOR_AUTORUN_HOURS`, plus a 2–12-week question template.
- **Evidence behind the request (2026-10-20):** the production ledger holds 200 forecasts, none resolved, only 2 resolving before 2026-10-20; `golden_eval.py` never ran the pipeline; the as-of date was a prompt line only.
- **Constraints:** never modify the deployment checkout `/Users/rogerlin/Downloads/DeepResearchForecast` or its uploads (live pipelines on 5001/5013; reading its ledger is fine); use its venv `backend/.venv/bin/python`; run suites on frozen rsync copies without `backend/uploads`; no paid runs and no pushes without the owner's approval; `git` with `env -u GH_TOKEN -u GITHUB_TOKEN`.
- **Branch:** `claude/goofy-leakey-15afc1` (worktree `.claude/worktrees/goofy-leakey-15afc1`), cut from `main` ac48891; 12 commits (§10), not pushed, not merged.
- **Design:** [design.md](design.md), recorded before any code and amended once (§5, the `--extract-only` rule).

## 2) Requirements → Acceptance Checks
| Req | Acceptance check | Result | Evidence |
|---|---|---|---|
| R0 live byte-identical | Without `backtest_v1`, each touched path returns what it did before: Firecrawl payload and rows, search/fetch rendering, research env, data request and key, market params and rows, report re-quote, ledger append, extractor prompt, world seed | met | live-path tests in every `test_backtest_*` module; plain suite (§8) |
| R1a search cutoff | Firecrawl gets `tbs=cdr:1,cd_max:<as-of>` + `news`; every provider's rows dated from fields and URL; after-cutoff rows dropped; undated dropped (strict) / kept and flagged (lenient); keys carry the policy tag | met | `test_backtest_cutoff.py` (search fixture with 7 dated/undated/late rows), `test_backtest_search_fetch.py` |
| R1b fetch cutoff | archive capture ≤ cutoff read instead of the live page; captures after the cutoff never trusted; live page modified after the cutoff refused and remembered; undated page refused (strict) / flagged (lenient); the archive route keeps the source deny list; a dead archive is skipped after 3 failures | met | `test_backtest_search_fetch.py`, `test_backtest_cutoff.py` |
| R1c plan date and engine | v3 plan/brief/meta as-of = cutoff; unusable policy fails the run before any model call; tools without the cutoff refused; work-dir identity tagged | met | `test_backtest_engine.py`; real research child in `test_backtest_pipeline.py` |
| R1d official data | FRED API args carry `vintage_dates`; windows end at the cutoff; strict release lag on current revisions; provider fiscal period end wins; nothing-known → `invalid_window`; cache isolated | met | `test_backtest_official_data.py`; live FRED CSV in `free-endpoint-smoke-2026-10-21.json` |
| R1e markets | research snapshot searches all events, keeps markets open at the cutoff, prices from CLOB history at the cutoff, rebuilds rows from an allow-list; charts end at the cutoff; report never re-quotes or falls back; markets-off arm sees none | met | `test_backtest_markets.py`, `test_backtest_report_stage.py`; live Polymarket in the smoke file |
| R2 model knowledge | every golden question has `knowledge_cutoff` (validated after `as_of_date`); scorer reports post/pre model cutoff and unknown | met | `test_golden_eval.py` (+5 tests) |
| R3 driver | request admissible; id mapping (golden_id, proposition_id, id, guarded lexical; refuses other candidates, negation, ambiguity); per-arm Brier/log/ECE/accuracy + knowledge split + paired deltas; resumable runs; paid run refused without `--confirm-paid` and above 8 pipelines | met | `test_backtest_eval.py` (23 tests) |
| R4 forward testing | autorun at 24 h fires once after its delay then waits a day; forward questions checked for 14–84 days and an unattended source; forward-score over market and official-data resolutions | met | `test_backtest_eval.py` |
| R5 isolation | backtest `forecast.json` marked; never appended to the production ledger; today's track record not attached; monitor skips it; driver scores only reports whose cutoff matches | met | `test_backtest_report_stage.py`, `test_backtest_eval.py` |
| R6 suite | plain backend suite on a frozen rsync copy: 0 failures apart from the 19 known `test_legacy_official_data.py` errors | met at the final HEAD (§8) | `/Users/rogerlin/Downloads/drf-guarded-runs/` dirs in §8 |
| R7 docs | README EN/ZH describe backtest mode, line-aligned | met: 2,029 lines each, structural line check clean | `README.md` / `README.zh-CN.md` "Backtest mode: accuracy without hindsight" |

## 3) Plan & Decomposition (as executed)
1. `deerflow_bridge/backtest_cutoff.py` first: the policy, dates and verdicts carry every other slice and had the most uncertainty (date formats, CDX semantics).
2. Research side: search (`search_tools.py`), the v3 tool layer (`research_gateway.ResearchTools`), the engine (`linear_research.py`).
3. Official data (`data_sources.py`).
4. Markets in the bridge (`deerflow_research.py`).
5. Backend: `backtest_mode.py`, admission and research env (`pipeline_orchestrator.py`), SDK route, report agent, extractor, world seed, resolution monitor.
6. Golden `knowledge_cutoff` and the scorer split.
7. Driver and forward template.
8. Docs, gates, frozen suites, mutation check, free-endpoint smoke.

## 4) To-Do & Progress Ledger
- [x] Map the code paths; verify the free public APIs (Wayback CDX, Gamma `public-search` without `events_status`, CLOB `prices-history` with `startTs`/`endTs`, Firecrawl `tbs` docs, deployed FRED MCP `vintage_dates`).
- [x] Design recorded (`design.md`).
- [x] Slice 1–2 (234f2be): cutoff module, search, fetch, engine; deploy lists (`_DEPLOYED_BRIDGE_MODULES`, `setup.sh`, `init.sh`).
- [x] Slice 3 (813d5c4): official data.
- [x] Slice 4 (91ae12c): research-stage markets.
- [x] Slice 5 (b1c4b60): pipeline policy, arms, report stage, world channel, monitor.
- [x] Slice 6 (8f33085): golden `knowledge_cutoff` + split.
- [x] Slice 7 (61dfb8b): driver + forward template.
- [x] Docs (b54d5b7), review fixes (b98c41f, 34b49b1, 1ca1831), this handoff.
- [x] Gates, plain and guarded suites, mutation check, free-endpoint smoke (§8).
- [ ] Paid live acceptance run — needs the owner (§9).
- [ ] Forward testing switched on in the deployment — the owner's configuration decision (§9).

## 5) Findings, Decisions, Assumptions
- **Finding:** all 30 golden questions resolved by 2025-02-09, before any 2026 model's training cutoff: the retrospective set can only give an upper bound on skill. Decision: the knowledge split is reported, never hidden; clean numbers need forward testing or a post-cutoff question set (§9).
- **Finding:** the report stage re-quoted market prices live (PM-3) and fell back to a live market search, and it attached today's track record to every forecast: three leaks in a retrospective run. Decision: a backtest report never contacts the market API and skips the track-record note.
- **Finding:** Gamma returns resolved markets with `outcomePrices` `["1","0"]`. Decision: the as-of market row is built from an allow-list (`backtest_cutoff.as_of_market_row`), never by deleting fields from the live row. Pinned by a mutation (§8).
- **Finding:** the archive route bypassed the fetch layer's source deny list (the capture's host is `web.archive.org`). Fixed in b98c41f: the original URL is checked first.
- **Finding (live, 2026-10-21 01:51 +08):** `web.archive.org` CDX answered 429 and then timed out for this network (`x-nid: tencent`), though it answered normally at 23:40 +08. Decision (1ca1831): 8 s per lookup, one retry after Retry-After (capped at 10 s), a process-wide circuit after 3 consecutive failures, and the archive status in every fetch's audit row. Consequence: when the archive is throttled, strict mode keeps only pages dated by their own metadata, URL or search hit.
- **Finding:** `/api/v1` is mounted only with `API_V1_ENABLED=true` (default false); the driver needs it on the backend it talks to.
- **Decision:** the cutoff is pinned per pipeline (`options.backtest_v1`) and reaches the research child as one parent-owned variable, `DRF_BACKTEST_POLICY`, removed from the ambient environment on every launch. Alternatives rejected: a process-wide `.env` switch (would cut the resolution monitor's data and every live run on that backend).
- **Decision:** backtest mode supports only the v3 research engine and the OASIS engine; admission, the orchestrator and the bridge each refuse the rest (fail closed). The `--extract-only` salvage stays allowed because it reads no web content (design amended).
- **Decision:** the "+simulation" arms use `legacy_prompt`, the only setting that lets the simulation move probabilities; Foglamp reserves it for evaluation, which this is, and backtest forecasts never reach the production ledger.
- **Decision:** each arm is its own pipeline in v1 (no stage sharing); cost noted in §9.
- **Decision:** strict mode is the default and drops undated sources; Firecrawl web rows carry no date, so strict research leans on dated news rows, URL dates and archive captures. Lenient mode exists for comparison.
- **Assumption A1:** Firecrawl's `cdr` filter limits results to pages dated within the range. Falsification: own-date filtering runs on every row anyway, so a leaky provider filter cannot admit a row dated after the cutoff; it can only admit undated rows, which strict mode drops. Untested live (Firecrawl is paid).
- **Assumption A2:** FRED `vintage_dates=<as-of>` with the default output type returns the values as of that date. Offline test uses a fake hub; the deployed MCP build forwards the parameter; a live check needs the FRED key (part of the proposed run).
- **Residual leakage (documented, not removed):** model memory; live pages without a capture can be edited silently after their stated date; search titles are current titles; non-FRED official data are current revisions; market lifetime volume (ranking only) includes post-cutoff trading.

## 6) Issues, Mistakes, Recoveries
- **Plain-suite failure at b54d5b7:** `test_official_data_consumers.py::test_seed_report_receives_only_valid_persisted_official_generation` ×2 — the test swaps `ReportAgent` for a `SimpleNamespace`, and the orchestrator called `agent.set_backtest_policy` unconditionally. Fix (1ca1831): `_pin_report_backtest` calls the setter only when the agent has it; real agents still receive the explicit value (live reports skip the lookup scan). Guard: the module passes in the final plain run.
- **Mutation script quoting slip** (a literal newline inside a string) — caught by the script's own `compile`; rerun clean.
- **Test-fixture mistakes caught by the code, not the other way round:** a too-terse lexical-match fixture (the 0.75 overlap guard refused it, as designed); an expected-drop count that forgot the open month dated on the as-of day; a five-fetch test that hit the per-agent fetch budget.

## 7) Scenario-Focused Resolution Tests
- **"A retrospective run reads the outcome."** Repro: a 2024-11-01 question; search returns "Winner declared" (dated 2024-11-06) and a recap "3 days ago"; fetch returns a page modified 2024-11-08; Gamma returns the resolved market at 1.0. Change: backtest mode. Post-change: the model never sees the late rows (`test_backtest_engine.py` asserts they are absent from every prompt and from `sources.json`), the page is refused, the market is priced 0.59 from history at the cutoff. Verdict: resolved offline; live for markets (smoke file).
- **"A live run inherits a cutoff."** Repro: `DRF_BACKTEST_POLICY` set in the parent environment. Post-change: the real research child of a live pipeline sees none (`test_a_live_child_never_inherits_an_ambient_policy`). Verdict: resolved.
- **"A backtest pollutes the production track record."** Post-change: no ledger append, no monitor rows, `forecast.json` marked. Verdict: resolved.
- **"Accuracy cannot be computed."** Post-change: `backtest_eval.py score` writes Brier, log score, ECE, accuracy per arm with the knowledge split and paired deltas from run records (`test_cmd_score_writes_report_and_markdown`). Verdict: resolved offline; first real numbers need the live run.

## 8) Verification Summary
- **New tests:** 159 (154 in eight new modules + 5 in `test_golden_eval.py`) — `test_backtest_cutoff.py` 60, `test_backtest_search_fetch.py` 15, `test_backtest_engine.py` 4, `test_backtest_official_data.py` 7, `test_backtest_markets.py` 6, `test_backtest_pipeline.py` 24, `test_backtest_report_stage.py` 15, `test_backtest_eval.py` 23.
- **Mutation check** ([mutation-check.log](mutation-check.log)): each guard broken in turn must fail its test — ambient-policy removal, search row filter, provider date filter, tool-layer search cut, fetch admission, archive route, plan date, data observation cut, FRED vintage, market allow-list, market eligibility, report re-quote, production-ledger skip, monitor skip, archive circuit breaker, deny list on the archive route, extract-only allowance, legacy research refusal, markets-off env: all killed.
- **Free-endpoint smoke** ([free_endpoint_smoke.py](free_endpoint_smoke.py) → [free-endpoint-smoke-2026-10-21.json](free-endpoint-smoke-2026-10-21.json), no LLM, no keys): Polymarket as-of snapshot of the 2024 election — Trump YES 0.59, Harris 0.4105 at 2024-11-01 23:00 UTC, `price_basis: clob_history_at_cutoff`, no resolved field; FRED keyless CSV for UNRATE — last observation 2024-08 under the strict lag (3 dropped); Wayback — `unavailable:HTTPError:429` (see §5).
- **Gates (HEAD 1ca1831 and later):** `uvx ruff@0.17.1 check --select F,E9 --ignore F401,F841,F541 backend/app backend/scripts deerflow_bridge` and `--select F,E9` on the new modules pass; local `ruff check app` reports the same counts per changed file as the base commit (no new findings); `check_env_drift.py --strict` exit 0; `compileall` OK.
- **Suites on frozen rsync copies without `backend/uploads`, deployment venv:**
  - `20261021-014438-backtest-plain` (HEAD b54d5b7): 8,243 tests, 19 known `test_legacy_official_data.py` errors, **2 failures** (`test_official_data_consumers.py`, §6).
  - `20261021-014552-backtest-guarded` (HEAD b54d5b7, the 55-module list of the previous baseline): 1,611 tests, 1,608 passed, 3 failed — the known guard failures (`test_deployment_sidecar_control_flow.py` ×2, `test_official_data_end_to_end.py::test_guarded_mcp_to_promoted_research_and_report_png`).
  - Final runs at the final HEAD: see the closing entry of §10.

## 9) Remaining Work & Next Steps
- **Paid live acceptance run (owner's approval).** Purpose: mechanics on real artifacts, not a skill estimate (both questions resolved before the model's cutoff). Proposal:
  1. A second backend from this branch on :5011 with `API_V1_ENABLED=true`, `DRF_TEST_PROCESS=1` (no orphan reclamation; it skips `.env`, so export the provider keys first) and its own `DEERFLOW_DIR` copy of `deer-flow/` (the drift guard syncs this branch's bridge modules into `DEERFLOW_DIR`; it must never be the deployment's).
  2. `backtest_eval.py run --ids fed-2024-09-cut,us-pres-2024-trump --arms research_only,markets --base-url http://127.0.0.1:5011 --run-dir <dir> --confirm-paid` — 4 quick pipelines (4 simulation rounds each).
  3. Acceptance: each research handoff's `backtest_audit.jsonl` shows search drops and the archive status; `sources.json` holds nothing dated after the as-of date; `prediction_markets.json` (markets arm) has `backtest.price_basis = clob_history_at_cutoff` and no `prediction_markets.json` in the research-only arm; `forecast.json` has the `backtest` block and a `golden_id` row; the second backend's production ledger gains no row; `backtest_eval.py score --model-knowledge-cutoff <model's cutoff>` writes `eval_report.json`.
  4. Watch: strict mode with Firecrawl web rows undated may starve research (then compare a `--lenient` run); Wayback throttling (§5).
- **Forward testing (owner's configuration decision).** In the deployment: `RESOLUTION_MONITOR_AUTORUN_HOURS=24` and `RESOLUTION_MONITOR_RECENT_N` ≥ the number of open short-horizon reports (backtest reports also occupy the recent-N window, though the monitor skips them). Write questions from `backend/tests/eval/forward_questions_template.json`, check with `forward-check`, start one live pipeline per question with the printed prompt, score monthly with `forward-score`.
- **Follow-ups (not started):** share research and graph between arms (fork after the graph) to cut cost per question; a golden set resolved after the pipeline model's training cutoff (the model's cutoff must come from its vendor documentation); provider date filters for Serper and Tavily; a vintage route for BLS/BEA where the publisher offers one.
- **Risks:** strict-mode starvation (likely with Firecrawl; mitigation: lenient comparison, archive); a throttled archive (mitigated by the circuit; lenient mode as fallback); `legacy_prompt` arms flagged by Foglamp warnings in logs (expected, evaluation only).

## 10) Updates to This File (append-only)
- 2026-10-20T15:40Z: created with request, requirements, plan, API verification and first decisions.
- 2026-10-20T18:10Z: rewritten at completion of the offline scope: requirement results, decisions, live findings (archive 429, deny-list gap), issues, scenario tests, verification, live-run proposal. Commits on the branch: 234f2be, 813d5c4, 91ae12c, b1c4b60, 8f33085, 61dfb8b, b54d5b7, b98c41f, 34b49b1, 1ca1831 (+ this handoff).
