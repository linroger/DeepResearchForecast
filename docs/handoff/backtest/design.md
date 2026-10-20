# Backtest mode — design (2026-10-20)

The words MUST, SHOULD and MAY are used as in RFC 2119.

## 1. Problem

DeepResearchForecast has never measured its own accuracy:

- The production ledger `backend/uploads/pipelines/_forecast_ledger/ledger.jsonl` holds 200 forecasts; none is resolved and only 2 resolve before 2026-10-20 (horizons run to 2040).
- `backend/scripts/golden_eval.py` scores a `forecast.json` against 30 resolved golden questions, but nothing runs the pipeline on them, and a retrospective run would read the outcome: the as-of date is only a prompt line (`linear_research.phase_plan` uses today's date), while search and fetch results, official-data observations and vintages, and prediction-market prices are all current.

A retrospective score without leakage control is meaningless, so every quality change so far was judged by gates and review, not by outcomes.

## 2. Goals and non-goals

Goals:

1. An opt-in **backtest mode**, pinned per pipeline, that cuts every external input of the pipeline at an as-of date. Off by default: a pipeline without it MUST behave byte for byte as before.
2. An honest account of what the cutoff cannot remove (the model's own training knowledge), measured per question.
3. A driver that runs a question set end to end at a cheap profile, maps the binary forecasts to the questions and writes `eval_report.json` (Brier, log score, ECE) per ablation arm.
4. A forward-testing path whose forecasts resolve within months.

Non-goals: the legacy research engine (backtest mode refuses it), the opt-in world-v1 simulation engine (refused too), sharing stages between ablation arms (each arm is its own pipeline; a cost follow-up), and a fresh post-training-cutoff question set (a follow-up; see §9).

## 3. The policy object

`state.options["backtest_v1"]`, pinned at admission (`backend/app/services/backtest_mode.py`):

```json
{"version": "backtest/v1", "as_of": "2024-11-01", "strict": true, "archive": "wayback",
 "arm": {"name": "markets", "markets": true, "simulation": false, "world_channel": false},
 "target": {"golden_id": "us-pres-2024-trump", "question": "…", "resolution_criteria": "…",
            "resolution_date": "2024-11-06"},
 "run_label": "…", "pinned_at": "…"}
```

- Admission (`PipelineOrchestrator.start(backtest=…)`, `POST /api/v1/run` field `backtest`) validates it and refuses: an as-of date that is not a past ISO date, a target that resolves on or before the as-of date, the legacy research engine, and the world-v1 simulation engine.
- The research stage re-checks the engine at launch and fails closed if it no longer resolves to v3.
- The research child receives one parent-owned variable, `DRF_BACKTEST_POLICY` (compact JSON: `as_of`, `strict`, `archive`, `audit_path`). The parent always removes an ambient value first, so a live pipeline can never inherit a cutoff and a backtest pipeline never inherits another one. The bridge's legacy engine path refuses to run when it is set.
- Cutoff instant: the end of the as-of day in UTC. A source dated on the as-of day is admissible.

## 4. Dates and verdicts (`deerflow_bridge/backtest_cutoff.py`)

One stdlib-only module, deployed beside the other bridge modules and imported by the backend through `official_data.bridge_module`:

- `parse_date` reads ISO dates and timestamps, RFC 2822, "Nov 5, 2024" / "5 November 2024", epoch seconds or milliseconds, and relative ages ("3 days ago", resolved against the wall clock: a relative age means "recent", hence after any past cutoff). It returns an interval with its precision (day, month or year).
- `verdict(dates, policy)`: `before` when the latest bound of the content date is at or before the cutoff, `after` when its earliest bound is after it, `undated` otherwise (no date, or a month or year that straddles the cutoff). A modification date counts: a page published before the cutoff but modified after it is `after`.
- `after` sources are always dropped. `undated` sources are kept and flagged in lenient mode and dropped in strict mode (the default).
- Every decision is appended to the audit file (`backtest_audit.jsonl` in the handoff) and the engine copies the counts into `research_meta.json` (`meta.backtest`).

## 5. What is cut, and how

| Input | Live behaviour | Backtest behaviour |
|---|---|---|
| Web search (`search_tools.web_search_impl`) | provider results, 6 h disk cache | Firecrawl gets the provider date filter `tbs=cdr:1,cd_max:MM/DD/YYYY` and the `news` source (news rows carry dates); every row of every provider is then classified from its own date fields and URL path; cache and negative-cache keys carry the as-of tag |
| Search rendering (`ResearchTools._render_search`) | title, URL, snippet | the same plus the row's date (or `undated`) |
| Fetch (`ResearchTools.fetch`) | live page | with `archive=wayback`, the last Wayback Machine capture at or before the cutoff (CDX API; its timestamp is the content date); otherwise the live page, dated from JSON-LD / meta tags / reader headers / labelled bylines, the URL path and the search hit; after → `FETCH_FAILED(published_after_cutoff)`, undated in strict mode → `FETCH_FAILED(undated_source)` |
| Plan date (`linear_research.phase_plan`) | today | the as-of date (it flows to the brief, data windows, recency annotations, `actors.as_of_date`, hence the simulation timeline) |
| Official data (`DataSources`) | windows end today; current revisions | windows end at the cutoff; FRED API requests `vintage_dates=<as_of>` (ALFRED: values as published then); every other route returns current revisions, admitted only for periods that ended by the cutoff (lenient) or ended a release lag before it (strict: D 1, W 7, M 45, Q 90, A 180 days); projections never pass; each series carries `provenance.backtest` |
| Prediction markets, research (`deerflow_research._collect_prediction_markets`) | active events, current prices | all events searched; a market is kept only if it had started and had not closed by the cutoff; its price is the last CLOB price-history point at or before the cutoff (within 7 days); post-cutoff fields are removed (closed flag, outcome prices, 1-day change, bid/ask, liquidity, resolution status); price-history charts end at the cutoff; agent-tool candidates are ignored |
| Prediction markets, report (`ReportAgent`) | re-quoted at current prices; live fallback search | research snapshot only: no re-quote, no fallback search |
| Ledger and monitor | forecasts appended to the production ledger; the resolution monitor re-quotes recent reports | `forecast.json` carries a `backtest` block; nothing is appended to the production ledger; the monitor skips backtest reports |

Residual leakage, documented rather than removed: the model's own training knowledge (§6); live pages without an archive capture can be edited silently after their stated date (lenient mode only; strict mode drops undated pages but trusts stated dates); search engines index pages by their current text, so titles of dated hits are current titles; current-revision official data (non-FRED routes); market lifetime volume, used for ranking, includes post-cutoff trading.

## 6. Model-knowledge leakage

The LLM itself may know outcomes that resolved before its training cutoff, and no input filter can remove that. Each golden question gets `knowledge_cutoff`: the first date its outcome was public. The scorer takes the model's training cutoff (`--model-knowledge-cutoff YYYY-MM-DD`) and reports three groups separately: `post_model_cutoff` (outcome public after the model's cutoff: clean), `pre_model_cutoff` (possibly memorised: an upper bound on skill) and, when the model's cutoff is unknown, every question as `unknown`. All 30 current golden questions resolved by 2025-02-09, so for any 2026 model the whole retrospective set is possibly memorised; clean numbers need the forward test (§8) or a question set that resolved after the model's cutoff.

## 7. Ablation arms and the driver

Arms are cumulative; each runs as its own pipeline:

| Arm | Markets | Simulation affects probabilities | World channel |
|---|---|---|---|
| `research_only` | off | off (`no_update`) | off |
| `markets` | on | off (`no_update`) | off |
| `simulation` | on | on (`legacy_prompt`) | off |
| `world_channel` | on | on (`legacy_prompt`) | on |

Knobs: markets off sets `PREDICTION_MARKETS_ENABLED=false` for the research child and removes the report's market pack; the simulation knob sets the report agent's simulation-forecast effect (Foglamp keeps `legacy_prompt` for evaluation only, which is what this is); the world-channel knob writes `settings.pressure_weight = 0` into the simulation's world block when off.

The report stage pins the target question as one binary forecast (`proposition_id` = golden id); the row is marked `golden_id`. The driver (`backend/scripts/backtest_eval.py`) maps forecasts to golden ids by `golden_id`, then `proposition_id`, then `id`, then a lexical fallback (token overlap ≥ 0.5 with a 0.1 margin over the runner-up, refused on a negation mismatch), and records the method.

Subcommands: `plan` (questions × arms, prompts, no network), `run` (SDK API runner against a backend URL; refuses without `--confirm-paid`; resumable `runs.jsonl` manifest), `score` (writes `eval_report.json` + markdown: per arm Brier, log score, ECE, accuracy, the knowledge-cutoff split, and each arm's paired difference from `research_only`), `forward-check` and `forward-score` (§8). Cheap profile: `depth=quick`, `max_rounds=4`, English.

## 8. Forward testing

- `RESOLUTION_MONITOR_AUTORUN_HOURS=24` (with `RESOLUTION_MONITOR_RECENT_N` large enough to keep every unresolved short-horizon report in the window) makes the backend re-run the keyless resolution monitor daily; it records market and official-data resolutions of live binaries.
- `backend/tests/eval/forward_questions_template.json`: questions that resolve 2–12 weeks after they are asked, each settled by a named Polymarket market or official series so the monitor resolves them without a human. `forward-check` refuses horizons outside 14–84 days and prints each pipeline prompt.
- `forward-score` scores the resolved live binaries (market and official-data resolutions) with the same Brier / log / ECE core.

## 9. Follow-ups (not in this change)

- A paid live acceptance run (proposal in the handoff, needs the owner's approval).
- Share research and graph between arms (fork after the graph) to cut the cost per question.
- Curate a golden set of questions resolved after the pipeline model's training cutoff.
- Provider date filters for Serper and Tavily (the deployment uses Firecrawl).
