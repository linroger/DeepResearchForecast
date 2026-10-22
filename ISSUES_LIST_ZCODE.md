# ISSUES_LIST_ZCODE.md — DeepResearchForecast Report Quality Audit

**Date:** 2026-10-17 · **Branch:** `claude-reflexive-world-state-model`
**Scope:** The 5 most recent completed runs, audited end-to-end by a 12-agent parallel team plus independent verification of every load-bearing claim.

| Run | Pipeline | Report | Domain | Result |
|---|---|---|---|---|
| Japan PM 2027 | `pipe_22b62e7b8346` | `report_ed7fe8803054` | Politics (JP) | completed, gates green — 18 issues found |
| Brent Q2 2027 | `pipe_3dcd66754cdc` | `report_4798b00211eb` | Commodity | completed, gates green — 12 issues found (3×P0) |
| US–China trade | `pipe_d569f211eb14` | `report_0f2e07d62a34` | Geopolitics | completed, gates green — 22 issues found |
| UK Burnham | `pipe_4eb5ce9557ff` | `report_b7d936251d21` | Politics (UK) | completed, gates green — 18 issues found |
| France budget | `pipe_41c155a33733` | `report_ea833f1e0f3b` | Politics (FR) | completed, gates green — 22 issues found |

**Key takeaway:** every gate passed on every run, yet all five reports contain material defects. The audit layer certifies things the reader actually experiences as broken. The defects cluster in five pipeline layers: (1) publish-gate thresholds, (2) the quantitative-grounding repair pass, (3) simulation-vs-forecast reconciliation, (4) citation handling, (5) frontend rendering.

---

## Part 0 — User-reported symptoms → root causes

| Symptom reported | Root cause (verified) | Issue # |
|---|---|---|
| "Graphs don't make sense and aren't additive" | `worldstate_trajectory.html` (sim-derived) and `scenario_probabilities.html` (forecast spine) both claim to show the horizon distribution and disagree by 22–57pp in **all five** runs. Within any single chart probabilities *do* sum to 1 — the failure is cross-chart reconciliation, not summation. | SYS-3 |
| "Superscript citations don't link to the correct sources" | Superscripts display the source's **original tag number** (`[S44]`→"44") while References are numbered by **first-appearance order** (S44 = row "15."). 104/108 markers carry a number contradicting the list row they jump to; matching by number lands on a genuinely wrong source. Plus scattered writer-LLM mis-tagging. | SYS-4, CIT-1 |
| `market_price_history_1.html` "only looks at <1 day of history — remove it" | Confirmed: exactly **0.9992 days** (1,421 one-minute ticks, 5 unique prices, 0.2pp band). Polymarket CLOB `/prices-history` `interval` is a *lookback window*, not a bucket size — `interval="1d"` returns only the trailing 24h. **Removed** (code + all artifacts; see Part 5). | SYS-5 (resolved) |
| Screenshot: truncated table statements, dead CONFIDENCE column, em-dash MARKET ANCHORs, bloated cell, "4.3% ↗ Δ -1.3pp" | CSS `nowrap`+ellipsis on statements; backend never emits per-row `confidence`; 9/10 rows carry no `market_anchor`; DATA ANCHOR cell stacks 6 sub-rows; the `↗` is the generic external-link affordance, not a direction arrow — it sits beside a negative Δ chip that is colored red as if an error. | UI-1..UI-4 |
| Screenshot: "Simulated World Variables (indexed, seed=100)" plummets then scribbles | Indexing is `value/seed×100` (all lines start at 100 by construction); Japan's lone variable genuinely drops 63.8%→41.2% approval in the first simulated half-month; contradictory "if bill passes/stalls" branches drawn at the same x; 12–18 unrotated 10-char labels collide. Shipped charts were rendered by **stale pre-fix code** despite a post-fix server restart (deployment hazard). | CH-3, SYS-17 |
| Screenshot: sidebar overlap, "报告完成" in English UI | StageTimeline CSS overflow + hardcoded Chinese stage messages bypassing i18n. | UI-8, UI-9 |

> Note on the screenshot's "Polymarket 'Japan PM on March 31, 2027' … yes $0.91": that string does **not exist** in any Japan artifact (grepped forecast.json, market_comparison.json, agent_log.jsonl, official_data.json). The only anchored market is F4 "Sanae Takaichi out as Prime Minister of Japan in 2026?" at 4.3¢. The $0.91/`March 31` cell was likely rendered from a stale/cached page state — treated as an open provenance question, not a data issue.

---

## Part 1 — Systemic (cross-run) issues

### SYS-1 [P0] Publish-gate citation floor is effectively disabled
`.env:116` sets `REPORT_PUBLISH_GATE_MIN_COVERAGE=0.05` while the code default is `0.75` (`backend/app/config.py:179`) and three `getattr(...)` fallbacks use `0.5` (`report_agent.py:4728, 5047, 10847`). France cleared the bar by 0.003 with **521 of 550** quantitative claims unsourced. Resolved coverage per run: Japan 0.09, Brent 0.597, US-China 0.123, UK 0.066, France 0.053.
**Fix:** pick one threshold source of truth; raise `.env` to at least 0.3; make the gate read only `Config`.

### SYS-2 [P0] "Quantitative grounding repair" amputates finished reports to buy coverage
`report_agent.py::_repair_final_quantitative_grounding` (~L4988) deletes every numeric fragment lacking a resolvable `[S#]`. On Brent it removed **587 sentences + 9 table cells** (console_log.txt:459: "coverage 0.041→0.597, citations_added=45, sentences_removed=587"). Verified consequences: the published report **omits the 70% CI ($83–118) and P(touch $100) the prompt explicitly asked for** (present in section_01.md, deleted from full_report.md); the consolidated scenario table's probability/range columns are all "—"; ~59% of analysis missing with mid-sentence truncations ("Where would prices land? Morgan [S26]." — full_report.md:303). The post-repair audit then certifies `hard_passed: true`.
**Fix:** whitelist authored headline/scenario/deterministic-forecast numbers; cap removals (fail if >N% of claim units removed); treat cleared summary-table cells as hard failure; run the grounding audit on the pre-repair draft.

### SYS-3 [P0] Two "scenario" charts disagree on the horizon distribution — all five runs
`worldstate_trajectory.html` (from the world-state simulation) terminates at shares wildly different from `scenario_probabilities.html` (from forecast.json) over the same horizon date:
Japan 84.0 vs 58 · Brent **97.1 vs 40** · US-China 67.1 (for a state that isn't even in the scenario set) vs 42 · UK 55.1 vs 35 · France 83.1 vs 50 (terminal values verified from embedded plotly JSON). In US-China and France the trajectory's state taxonomy cannot be mapped to the forecast's scenarios at all. Start values also diverge (Japan t0 0.55 vs 0.58).
**Fix:** render the trajectory chart from `forecast.json` scenarios (or clearly caption it "pre-spine internal simulation, discounted — see Ch. N"); enforce numeric reconciliation in the audit (both charts live in the "scenarios" section).

### SYS-4 [P0] Citation superscript numbering contradicts References numbering
`frontend/src/utils/markdown.js:108-110` renders `[S44]` as sup-link labeled **44** (the source's original tag index), while `report_agent.py:9461-9468` numbers References by first-appearance display order (`1. [S13] …`). The anchor jump `#ref-S44` is tag-correct, but 104/108 superscripts across the 5 reports display a number that contradicts the landed row; manual number-matching yields a wrong source in 6/10/15/8/6 cases per report (e.g. Japan sup "3" = CSIS analysis sits beside list row 3 = S12 BIS CPI).
**Fix:** render sup labels from `citations.json` display numbers, or number References by tag order.

### SYS-5 [P0 → RESOLVED] market_price_history charts useless; removed 2026-10-17
Every chart was ~24h of near-flat minute-ticks (Japan: 1,421 ticks, 5 unique prices, 0.2pp total variation; France _1: 1,412 ticks, **1** unique price) rendered on a hardcoded [0,1] y-axis as a flat line, titled with bare forecast IDs ("F4"). Root cause: `interval="1d"` is a lookback window (`deerflow_bridge/deerflow_research.py::_pm_fetch_price_history`, default at `PREDICTION_MARKETS_PRICE_HISTORY_INTERVAL`), the `days=90` client trim can only shorten it, and the y-range [0,1] flattens single-digit probabilities.
**Action taken:** full removal — generation code (report_visualizer.py builders + wiring, report_agent.py handoff_dir pinning, pipeline_orchestrator.py merge/write, deerflow_bridge fetch machinery), tests (5 files updated), and all artifacts across every report dir (files, markdown embeds en+zh, viz_manifest entries, audit fingerprints recomputed). Backend restarted. Its only unique content (model vs market point comparison) survives in `model_vs_market_table.md`, the binary dotplot, and the markdown table.

### SYS-6 [P1] Citation stripping deletes resolvable markers and leaves punctuation debris
Japan: 457 `[S#]` markers in section drafts → 96 in the final report (361 silently deleted, including 36/38 `[S3]`, 20/22 `[S45]`); France: "checked=482 remapped=0 **stripped=444**". Residue everywhere: " )" orphans (Japan ×7, France ×16, UK ×3, US-China ×6), glued em-dashes, and UK's garbled `_src~Sources cited: _` artifact (full_report.md:490, from a stripped source list).
**Fix:** only strip markers that fail verification; collapse enclosing punctuation when stripping; add lint rules for ` )` and `^_src~`.

### SYS-7 [P0] US-China Chinese translation failed but left a half-published bundle
`full_report.zh.md` absent; `full_report.zh.rejected.md` (151KB) present; `translation_status.zh.json` frozen at `status="failed", progress=100` with stale message; yet `forecast.zh.json` (8 untranslated fields incl. binary statements) and `final_audit.zh.json` (hashing the *rejected* file — sha verified) were written. 16 translation calls killed by GLM content filter (error 1301).
**Fix:** quarantine rejected artifacts out of the report dir; make the zh audit hash only the published file; make status terminal-state consistent.

### SYS-8 [P1] Proposition dedup and joint-coherence checks are missing (US-China)
Five pairs of near-duplicate binary questions priced up to 20pp apart (F9 40% vs F17 60% — same AI-export-control event; F7 35% vs F16 40% — same statutory-ban event; F10 65% vs F14 75% — differs only at exactly 200.0), plus exact duplicate rows F5/F15 (both "agreement operative", 42%) — each pair got a different `proposition_id`, so key-based dedup never merged them. Also logically impossible jointly: F3 (70%) requires "no statutory ban" while the ban is priced 35–40%; F2 (25%) must be ≥ P(ban). "17 forecasts" is effectively 13 distinct.
**Fix:** semantic near-duplicate clustering before finalization; pairwise implication/monotonicity constraints in `binary_quality`.

### SYS-9 [P1] Stale/expired/mislabeled prediction-market usage
France F6: market "Will the 2026 United Left primary be canceled?" at 0.9375 **closed 2026-10-12**, four days before research, yet used as a "live" anchor; two prose passages invert its polarity ("primary proceeding at 94%"). UK anchor URL has a corrupted slug (`andy-burnham-out-as-uk-pm-byptptpt-…`). `market_comparison.json` schema records no `fetched_at`; `market_anchor_integrity` has no freshness check and passed with 0 issues.
**Fix:** record fetch timestamps; reject/handle expired markets; polarity check between market question wording and report claim.

### SYS-10 [P1] forecast.json headline is not derived from final scenarios
Japan: headline string contains stale "(~22%)" while scenarios say 27% — both appear in one sentence (full_report.md:81; verified). France: headline "≈60%" vs scenarios 0.50/0.25/0.25 in the same file.
**Fix:** regenerate `headline` deterministically from the final `scenarios[]` after red-team recalibration.

### SYS-11 [P1] Vacuous "passed" checks undermine the audit
`market_anchors.passed=true` with `anchored_count=0` (Brent, US-China); `semantic_citations` records `matched/unmatched/coverage = null` with `passed=true` (all runs); US-China `binary_quality.issues` flags "all forecasts share a single theme" (theme_cardinality=1) yet `passed=true` with a 40% "Other/Status Quo" residual vs 42% modal. UK F2's market anchor was *removed* (`removed_market_anchors`) rather than reconciled.
**Fix:** empty-input checks should be "skipped", not "passed"; advisory issues above thresholds should block.

### SYS-12 [P2] Telemetry/attribution integrity
Japan and Brent share a **byte-identical** `unattributed_process` cost block (16 calls, $0.125412) and identical-to-the-second `created_at` — batch-rewritten run metadata. Resumed runs show research/ontology/graph as 0 tokens with nonzero wall time. Every run is a paid retry ($9.90–$12.08 cumulative).
**Fix:** per-run attribution keys; don't rewrite `created_at` on resume.

### SYS-13 [P2] forecast.json schema drift across runs
All `schema_version=1`, yet `residual_scenario_added`, `quality.repair`, `binary_forecasts[].scenario_membership`, France-only `scenarios[].metric_range`, US-China-only `binary_extraction_recovery` (duplicated top-level and inside `binary_quality.recovery`). zh audit JSON is a different schema from en (559–756 vs 201–209 key paths, no `publish_gate`).
**Fix:** version the schema when fields change; emit one audit schema for both languages.

### SYS-14 [P2] Translation pipeline silently degrades
36 skeleton-fallback warnings across runs ("整块候选…占位符漂移"); Brent published "available/passed" with 2 unresolved untranslated `adjustment_rationale` fields; US-China 15 "保留原文" fallbacks (pre-rejection).
**Fix:** count fallbacks in the zh audit; block publication above a fallback threshold.

### SYS-15 [P2] Recurring stub/degenerate columns and sections
"Discriminates scenario" column "—" in all rows (US-China, UK, France, Japan); "Publisher value (status)" all "—" (US-China, France); US-China binary-table Theme column = "ai" for all 17 rows; US-China's "Weighing the Prediction-Market Anchors" section describes anchor weighting its own artifacts say never happened (`anchored_count: 0`, forecast.json).
**Fix:** drop unpopulated columns; gate boilerplate sections on actual data presence.

### SYS-16 [P2] Orphaned/unembedded artifacts
`charts/world_variables.png` exists + manifest-listed but **never embedded** in the markdown (Japan, Brent, US-China — dangling `<!-- viz:charts/world_variables.html -->` comment with no image line; the numeric-repair pass likely ate the image line, e.g. Brent zh:181). `charts/model_vs_market_table.md` orphaned in Japan & UK. Brent's summary blockquote (`> {summary}`) missing from assembled report.
**Fix:** exempt viz image/caption lines from stripping; embed or delete orphans.

### SYS-17 [P1] Deployment hazard: stale-code rendering despite post-fix restart
Shipped Japan/Brent `world_variables.html` (19 points, x0="seed", duplicate labels) is **impossible under current code** — verified by executing `world_variable_series()` against the same `world_state.json`: it yields 12 clean points, x0="2026-10-16". The rendering server (started 03:34, after fix commit `0e57c77` at 02:50) still produced pre-fix charts; `.claude/worktrees/*` contain pre-fix copies of `report_visualizer.py` and are the prime suspect for a wrong-cwd spawn. Current backend (restarted 20:0x) is verified on canonical cwd.
**Fix:** fail fast on version-pin mismatch (render provenance stamp in chart HTML); purge stale worktrees; re-render affected report charts.

### SYS-18 [P3] Known pre-existing test failures
`test_world_variables_html_skips_zero_seed_and_sets_chronological_category_order` fails on unmodified HEAD (zero-seed variables plotted; "period N" fallback labels mixed with quarter labels — the test encodes behavior that was never implemented). Plus 2 known failures in `test_orchestrator_research_wiring.py`.

---

## Part 2 — Chart-by-chart verdicts (50 charts audited)

| Chart family | Verdict | Details |
|---|---|---|
| scenario_probabilities | OK (5/5) | Sums exactly 1.0, matches forecast.json. Label truncation: Brent "…discontinuou…", UK "…GM mayora…" hide scenario-defining ranges (P2). US-China's 40% "Other/Status Quo" catch-all is a coin-flip residual (P2). |
| binary_forecast_dotplot | OK (5/5) | All 61 model probabilities match forecast.json; market diamonds match market_comparison.json. |
| worldstate_trajectory | **BROKEN (5/5)** | SYS-3. |
| world_variables | MISLEADING (4/5) | SYS-17 + CH-3: branch contradictions at same x; heterogeneous units on one seed=100 axis (Brent mixes $/bbl spot, 4 futures, OVX vol index — OVX seed 49.13 vs prices ~$100); Japan indexes to the stale 63.8% Feb-2026 approval peak while the report's current value is 42.4%; 2-point series; cramped unrotated labels (12–18 × 10-char, 11px, no tickangle — report_visualizer.py:3227-3229); single line under a plural title (1 of 12 Japan variables qualifies). |
| timeline_lanes | MISLEADING (2/5) | Japan: 1979/1980 outliers stretch a 2024–2030 timeline across 50.35y — 15/18 events crushed into 4.8% of axis; dots staggered off lane ticks (Supply-Chain dots float at y=1.6/1.8 vs lane 2.0; "Other" at 2.6/2.8; Policy above the topmost lane); elections mis-filed under "Geopolitics", party merger under "Supply Chain & Economics", cabinet inauguration under "Other"; 38.7% of canvas is a text list duplicating the dots; 8/18 events hover-only (invisible in PNG). US-China/UK: milder era-mixing; none of the 5 charts marks the forecast horizon. |
| metric_trajectories | DEGENERATE/REDUNDANT (4/4) | Japan: 3 points that are a rounded strict subset of official_indicators' 26-obs GDP panel. Brent: 2 points. France: 2 points **with a sign flip** (deficit +5.4 here vs net lending −5.447 in official_series — no sign-convention note; the 5.8 (2024) value isn't even in official_data). UK: 3 of 4 traces single points; a "share" axis holding counts (9 mayors, 2 bills). |
| market_price_history | REMOVED | SYS-5. Was: 24h flat lines titled "F4"/"F13"; France _1 constant (1 unique value). |
| official_series / official_indicators | OK* | Data matches official_data.json to the decimal (WTI correctly labeled, horizon vlines correct). Defects: every official_series chart carries a vestigial all-`null` "Model threshold…" legend trace that plots nothing (7/7 files, P2); Japan official_indicators has an empty 4th subplot (axes domains defined, zero traces — P1); UK series end 2024-01 vs 2029-08 horizon (5.5y gap, unlabeled); Brent OVX panel n=1. |
| quantitative_claims / regional_comparison | REDUNDANT | 2–3 dots/bars duplicating table rows; Brent labels the same unit two ways ("USD per barrel" vs "Dollars per Barrel") on different as-of dates; Brent "latest" 114.159 (Sep mean) lags official_data's Oct partial 126.977 by $12.8/bbl (P2). |
| model_vs_market (chart) | REDUNDANT | France's version duplicates the 3 paired diamonds already on the dotplot. |

---

## Part 3 — Citation integrity detail

- **Dead links (HEAD-checked):** Japan S28 nippon.com **404**; Brent S47 summitcapnews.com **unreachable**; Japan S45 asahi 503; France S43 sudouest 307→final. Bot-blocked 401/403 (reuters/japantimes/argus/piie etc.) are fine for human readers.
- **Writer-LLM mis-tagging (P1):** Brent :134 attack/peak claim → S5 = EIA STEO chapter; :301 Saudi-strategy claim → S1 = FRED series; :84 FRED claim → S12 = rigzone news; :303 → S26 = **facebook.com** post; France "Reuters reported…" → S59 = ideal-investisseur.fr blog; Japan "Brookings reads…" → S32 = Jiji poll. Root: `report_agent.py:5847` keeps "unverifiable" markers by design, and writers attach plausible-but-wrong tags.
- **Hybrid-token leak (P2):** UK `[S54-adjacent reporting]` renders raw (no regex matches the old grammar).
- **Quality noise (P3):** duplicate titles for different URLs (Brent S4/S5 "Short-Term Energy Outlook"); junk titles ("13 May 2026", "Federal Register"); facebook/LinkedIn/aggregator sources in tier S2/S3.
- **Latent (P3):** `DossierViewer.vue:535-542` builds hover titles positionally — diverges from backend scheme if the source list is filtered.

---

## Part 4 — Frontend / UI issues (from screenshot)

- **UI-1 [P0]** STATEMENT truncated mid-word: `BinaryForecastTable.vue:330-336` `nowrap`+ellipsis, 320px (200px in 5-col mode). Fix: 2-line clamp + expandable row detail (statement + adjustment_rationale + resolution_criteria).
- **UI-2 [P0]** CONFIDENCE column structurally dead: backend never emits per-row `confidence` (`_BINARY_FORECAST_INSTRUCTIONS` has no such key); column can only show a constant or dashes. Fix: remove it or derive a real signal (p_high−p_low, ensemble spread).
- **UI-3 [P0]** MARKET ANCHOR 9/10 em-dash: only anchored rows carry `market_anchor`; full-width dash column for one populated row; duplicated emptiness in the markdown Part-1 table. Fix: collapse column below ~30% anchor density (pattern already exists via `hasDataAnchors`); header chip "1/10 anchored".
- **UI-4 [P0]** "4.3% ↗ Δ -1.3pp": the `↗` at `BinaryForecastTable.vue:57` is the external-link affordance, not direction; sits beside a red `.delta-neg` chip (`--color-err`) as if negative divergence were an error. Fix: styled external-link icon; color by `exceeds_10pp` magnitude; tooltip "model 3.0% vs market 4.3% (Δ −1.3pp)".
- **UI-5 [P1]** DATA ANCHOR bloated cell stacks up to 6 sub-rows (`.da-series/.da-threshold/.da-latest/.da-state/.da-base/.da-season`) in a 180–206px column while siblings are single-line. Fix: one summary line + rich tooltip.
- **UI-6 [P1]** No sorting/row interaction; `resolution_criteria` and `adjustment_rationale` reachable only via native `title` tooltips.
- **UI-7 [P1]** `chip-low` unstyled (only medium/high have styles).
- **UI-8 [P1]** Sidebar: `.rail` sticky without `max-height/overflow-y` (ResearchView.vue:973) — long timelines clip; `.st-sub-msg/.st-done-msg` nowrap + hard 80/60-char JS truncation (StageTimeline.vue:77,87); label/pill overflow ~252px column; redundant eyebrow "◇ Pipeline progress · PIPELINE".
- **UI-9 [P1]** Mixed language: hardcoded Chinese stage messages rendered raw (`pipeline_orchestrator.py:13948` "报告完成", :13715 "模拟完成", :12876 "研究完成", :2752, :1070) — dynamic backend strings bypass `i18n.js` entirely; same for raw `meta.status`.
- **UI-10 [P2]** Same 10 forecasts rendered twice on one page (Vue table + markdown Part-1 table) — double drift risk.
- **UI-11 [P3]** Fixed `min-width: 640/740px` tables force horizontal scroll for empty columns; no `<colgroup>`/`table-layout: fixed`.

---

## Part 5 — Actions taken in this session (beyond documentation)

1. **market_price_history fully removed** (SYS-5): `report_visualizer.py` (builders, wiring, fallback, helpers, title map), `report_agent.py` (`handoff_dir` pinning + `_locate_handoff_dir`), `pipeline_orchestrator.py` (merge fn, contract file, artifact spec, meta count, handoff write), `deerflow_bridge/deerflow_research.py` (PM-6 snapshot hook, `_collect_market_price_history`, `_pm_yes_leg_token`, `_pm_fetch_price_history`, `_pm_parse_price_history`, `PRICE_HISTORY_FILENAME`). Tests updated in 5 files (14 test functions + helpers removed; `test_build_all_includes_html_when_plotly` count 6→5). All artifact files deleted across every report dir; markdown embeds removed (en+zh, 6 files); viz_manifest entries cleaned (8 manifests); `final_audit*.json` `markdown_sha256/disk_sha256/markdown_chars` recomputed for the 3 edited reports so the publishable gate stays green. Backend restarted and health-verified; `/api/report/<id>/forecast` serves all three edited reports.
2. **Verified** the world-variable stale-render claim empirically (current function executed against the shipped sim data → 12 clean points; shipped chart has 19), and confirmed `test_world_variables_html_skips_zero_seed…` fails on unmodified HEAD.
3. **Spot-verified** all P0 claims directly (Brent CI deletion, empty scenario cells, Japan 22%/27% sentence, threshold knobs, US-China F9/F17, Brent trajectory 0.971 vs 0.40).

## Part 6 — Recommended fix priority

1. **SYS-2** repair-pass guardrails (stop deleting answer-critical content) — highest reader impact.
2. **SYS-1** gate threshold unification (one source of truth; raise `.env` floor).
3. **SYS-3** trajectory/scenario reconciliation (re-render from spine or caption as discounted).
4. **SYS-4** citation numbering unification (display-numbered sups or tag-ordered References).
5. **SYS-8** proposition dedup + joint coherence in `binary_quality`.
6. **SYS-6/SYS-16** citation-strip hygiene + viz-line exemption + orphan cleanup.
7. **SYS-7** zh-failure quarantine; **SYS-10** headline regeneration; **SYS-9** market freshness/polarity.
8. **UI-1..4** table rendering pass; **UI-9** i18n for stage messages.
9. **SYS-17** render-provenance stamp + worktree purge + re-render of shipped charts.
10. Chart-family work: timeline_lanes axis clamping/lane pinning; metric_trajectories removal or merge into official_indicators; degenerate-chart suppression (fold into markdown tables when <2 qualifying series).

---

# Part 7 — Log audit of the six recent runs (2026-10-20/21)

Method: 7-agent parallel audit (2 per-run log miners, incident-taxonomy auditor for the 2026-10-17/18 quartet, global backend-log scanner, simulation-log auditor, translation-pipeline specialist, code root-causer). 214 flagged backend-log lines, zero HTTP 5xx, zero route errors. **Status markers: ✅ FIXED this session · 📋 documented only (needs decision/bigger change) · ⛔ provider limitation.**

## Operational bugs — FIXED

| # | Issue | Evidence | Fix applied |
|---|---|---|---|
| LOG-1 ✅ | **Sticky provider breaker across resume.** Process-level `_CB_STATE` cooldown never reset on resume; the one probe it admits after cooldown is llm_client's own synthetic fast-fail (zero network), classified `circuit_breaker`, feeding the fresh run breaker → 10 instant failures → new attempt re-trips in seconds → only a backend restart clears it. OPEC+ lost whole attempts (23–208× `LLM_OUTAGE_HALT`). | `llm_client.py:110-191,474-491`; `pipeline_orchestrator.py:430-434` | `reset_provider_circuit_breakers()` added; called from `resume()` before thread start. Regression test added. |
| LOG-2 ✅ | **Orphan reclaimer trusts heartbeat over owner liveness.** Killed backend + restart within the 120 s heartbeat window → "存活证据…暂不回收" forever (reconcile runs only at startup), and `resume()` refuses until a manual cancel. Observed on all three 10-18 zombies. | `pipeline_orchestrator.py:8334-8340` | Dead `owner_pid` (os.kill ESRCH) now → dead immediately regardless of heartbeat freshness. Live-owner + stale-heartbeat unchanged. Regression test (dead & live child pids). |
| LOG-3 ✅ | **Heartbeat freshness ≠ liveness in status API.** Wall-clock heartbeat thread beats by design during long silent stages; consumers can't distinguish "running" from "wedged"/"residue". | `heartbeat_status()` | New composite `live` (owner alive AND heartbeat fresh) + `progress_stale` flag (`PIPELINE_PROGRESS_STALE_S`, default 1800 s) + config knob. |
| LOG-4 ✅ | **Failed report attempts listed as deliverables.** Every gate-aborted attempt mints an indexed folder; `list_reports()` ships them to the frontend (7 dirs for OPEC+). | `report_agent.py:16330+`, `_sim_index.json` | `list_reports(include_failed=False)` default + `get_report_by_simulation` prefers non-failed. Forensic dirs kept. Regression test added. |
| LOG-5 ✅ | **"转回退提供方" logged 26× while no fallback is configured** (`.env LLM_FALLBACK_PROVIDER=` empty; deliberate per handoff). Misleads outage triage. | `llm_client.py:541` | Config check moved before the log; honest "回退提供方未配置，保留原始错误" variant. |
| LOG-6 ✅ | **Advisory `.lock` files never unlinked** — 15 accumulated (translation + pdf-manifest). | `_advisory_file_lock` | Unlink-on-release while holding flock (POSIX-safe). Existing 15 deleted. |
| LOG-7 ✅ | **Zombie PROCESSING translation task bricks retry forever.** Worker dying inside the failure handler leaves an unbounded in-memory "in-flight" task; every POST returns 202 until restart. | `report.py:_active_translation_task` | 15-minute recency bound (ISO `updated_at`); stale in-flight tasks no longer short-circuit retry. |
| LOG-8 ✅ | **Stale message on failed translation status** ("running isolated translation publication audit" on `status=failed`). | `report_agent.py:9228+` | Explicit `message=` on both inline failure writes. |
| LOG-9 ✅ | **`simulation.log` truncated on every relaunch** — a resumed run's pre-resume history (why it stopped) is unrecoverable. | `simulation_runner.py:_open_main_log` | Old log archived to `simulation.<ts>.log` instead of deleted. |
| LOG-10 ✅ | **Translation worker threads drop run context** → metering falls into `_global` bucket (warnings at 20/100/500 calls; per-run cost attribution distorted). | `research.py:586`, `report.py:_launch_translation_thread` | Both spawns now run under `contextvars.copy_context()`. |
| LOG-11 ✅ | **Malformed tool-call JSON silently swallowed** — model omits a closing brace; parser drops the call; loop re-issues the same query up to 3× and misdiagnoses the leftover text as "pollution". | `_parse_tool_calls` (`report_agent.py`) | Parse failure now logs a visible warning with the malformed payload excerpt. |
| LOG-12 ✅ (reverted) | Contamination tolerance vs failed-call double-punishment. Initially relaxed tolerance by failed-call count; **reverted** after `test_report_bilingual` encoded the stricter fail-closed semantics (degraded variants must not publish). The residual double-count stays visible as two issues on one root cause. | — | Not changed by design; see LOG-15 for the real lever. |

## Documented (needs decision or larger change)

| # | Issue | Evidence |
|---|---|---|
| LOG-13 📋 | **No fallback provider at all** (empty `LLM_FALLBACK_PROVIDER`): 429 bursts permanently drop sim decisions (NVIDIA in sim_06de), content-filter 1301 kills zh translations with no alternate route. A dormant local gemini-proxy config exists at `.env:68-70`. **Decision needed: enable a fallback provider?** | `sim_06de440f5bea/simulation.log:129`; EU-China zh ×2 attempts |
| LOG-14 📋 | **zh translation retries are futile by construction for deterministic 1301** — same provider, same prompt, no compliance ladder for translation calls (section generation has one; `_translate_markdown_unit` doesn't). Needs either a translation-side compliance ladder or provider switch. | EU-China: byte-identical failure signatures 2 attempts 18 min apart |
| LOG-15 ✅ | **Whole-variant zh retries re-buy ~$1.60** with zero caching of accepted chunks; USD/JPY was rejected over ONE numeric token ("2026" 137→136). **FIXED 2026-10-21**: chunk-scoped numeric surgical retry (enumerates exact missing/extra tokens, one bounded call, replaced only on verified parity) + whole-variant veto graded by relative damage (≤ max(2, 0.5%) → recorded warning with diff detail; larger → hard issue). `REPORT_TRANSLATION_NUMERIC_TOLERANCE_RATIO` knob. Regression tests added. | `report_b1e898afce83` audit |
| LOG-16 ✅ (partial) | **Telemetry integrity**: FIXED — `tool_calls: 0, sections: []` (context-local per-section tool counting now works in concurrent mode; honest minimal entries with tool_calls/duration); sim/context propagation (new `ContextThreadPoolExecutor` at graphiti embedder + LLM-io pools, ens-seed pool, decision-elicit pool; sim subprocess pins `set_run_context(simulation_id)` at loop start so asyncio/to_thread/platform workers inherit). STILL OPEN: reclaimed-pipeline zeroed ledgers, `previous_attempt` double-count, by-stage rollups recorded as single calls. | 6/6 runs |
| LOG-17 ✅ | **`min_tool_calls` floor discards complete early answers** — 8/12 chapters written twice (~18% of stage output, ~25k tokens) in the AI-datacenter run. **FIXED 2026-10-21**: a clean, length-qualified (≥2000 chars) early Final Answer carrying ≥3 [S#] citation markers is accepted as dossier-grounded evidence and bypasses the floor (knobs `REPORT_EARLY_FA_MIN_CITATIONS` / `REPORT_EARLY_FA_MIN_CHARS`; defaults replicate the old behavior when raised). | `report_agent.py` REACT 情况1 |
| LOG-18 📋 | **Sim env idles up to 66 min after pipeline completion** (meter wall 80 min vs 14 min run stage). | env_status.json vs run_state.json |
| LOG-19 📋 | **`world_model.behaviour` all zeros** (rounds_scored=0) — scoring stage never wired. Arbiter validation problems and max_change_ratio clamps are silent (only in world_state_history.jsonl). | 6/6 sims |
| LOG-20 📋 | Connection-error chapter retries restart the full ReACT loop (5 duplicate reruns EU-China; interviews re-run at 60 s each). Checkpointing iterations would halve stage cost under provider flakiness. | console 03:22/03:26 |
| LOG-21 📋 | Duplicate save/log lines (章节已保存 ×2, 大纲已保存 ×2, 引用最终化 ×6-7 with admitted lint oscillation "仅 lint 在附录再生成上振荡"). | all runs |
| LOG-22 📋 | Abandoned attempts never terminalize `progress.json` (stuck "planning"/"generating 1/13" forever); meta timestamps inconsistent (completed_at < audit time; run_state updated_at < completed_at). | OPEC+ attempt dirs |
| LOG-23 ⛔ | Provider-side: 429/1302 storms under ≥2 concurrent heavy stages; 1301 content filter deterministic on China-trade content; single-key concurrency cap ~4-5 streams. | backend.out.log patterns 1-4 |

**Verification:** 172 tests green across the affected suites (`test_report_bilingual`, `test_orchestrator_outage_halt` (+2 new), `test_audit_fixes_report`, `test_wave9_report_focus`, `test_calibration_rigor`, `test_report_viz_and_pdf`, `test_parallel_research_merge`); 4 new regression tests added; backend restarted on the fixed code.

## Part 8 — SIM→报告影响与世界变量真实性（2026-10-22，用户提出）

| # | Issue | 根因 | 处置 |
|---|---|---|---|
| SIM-1 ✅ | **模拟对最终概率零影响**（用户观察属实）：信号包在 `diagnostic_only` 政策下被标注「不得据此调整概率」；`base_distribution` 锚点基础设施存在但生产调用方从不传入（休眠）；二元抽取仅 `legacy_prompt` 特性化 fixture 放行。 | Foglamp WP1 隔离设计（循环佐证顾虑）矫枉过正 | **SIM-RECONCILE**：`_simulation_anchor_inputs()` 读决策通道 outcome.shares → 骨架 band/advisory 双模式锚定（band=模拟完整覆盖预测期→概率带约束+证据分歧；advisory=短窗遗留→机制先验）；R2-CAL-18 分歧自动加宽区间/降信心；`simulation_anchor`/`horizon_divergence` 落 forecast.json 审计；spine block 钉「模拟对照」行进每章提示词。 |
| SIM-2 ✅ | **期限错配**：sim_3ec25e64209e 日历模式仅覆盖 2026-10-23..31（9 天，新闻窗伪命中），报告骨架判定日 2028-12-31（26 个月）——模拟对所问问题不可比。 | 配置期 horizon 抽取命中研究文本里的近端日期 | 判定日单一权威：band 模式（span≥SIM_HORIZON_MIN_DAYS=60）下骨架 horizon 强制=模拟 horizon（分歧留痕 `horizon_divergence`）；advisory 记录 coverage 缺口。配置期 60 天下限此前已修（新闻窗拒绝→LLM 兜底）。 |
| SIM-3 ✅ | **世界变量轨迹不真实**（用户：无人机发射强度 9 天 -38%？）：①单调复合——每日「会谈前适度降温」-8% 无均值回归无限复合；②pending effect 落地路径完全绕过钳制（r3 单轮 337→180，-46%）；③未来日期效应提前生效（"talks begin ~Nov 10–17" 在 10-25 当轮生效）。 | 仅有的每轮 0.5 步长钳制不足以约束累计漂移 | 三道防线（`world_model.py`，settings 三旋钮可调/可关）：软回归 κ=0.15 向研究锚点；硬累计漂移 ≤±35%；未来日期门槛→按时间线转 pending（due=max(due_periods, 日期折算)）。effect 路径补传全套钳制。damped 标记进 history cause（chart hover 可见）。 |

**验证**：新增 `tests/test_sim_reconciliation.py`（11 测试）；16 个受影响套件 326+ 测试全绿；`world_model` 系 6 个陈旧断言按新契约更新；`test_official_data_agent_usage` 的 `_locate_handoff_dir` 误删已复原。

## Part 9 — pipe_a19a0d5a4d39 复盘（FOMC 跑，2026-10-22）

| # | Issue | 根因 | 处置 |
|---|---|---|---|
| PM-NET-1 ✅(代码侧) | **该跑 0 个 Polymarket 市场不是「没有对应市场」而是根本没连上**：16/16 检索词全部 TLS 悬挂（TCP 可连、TLS 永不完成 = SNI 级阻断；当日 15s 死线 0 完成 0 异常）。对照：10-21 14:21 本地同机成功取 3 市场，10-17 取 20——网络可达性随 VPN/代理状态间歇波动；2026-07-12 的 pipe_91aaf91f6392 同病（33 transport failures）。 | 环境（网络阻断），代码无法修复连通性 | ① `PREDICTION_MARKETS_API_BASE`/`PREDICTION_MARKETS_CLOB_BASE` env 旋钮（bridge + utils 两处客户端）可指向本地代理/镜像；② DeadlineHang:tls-or-connect 显式错误类 + payload 携带 circuit/deadline 旗标 + 人类可读 `reason`；③ 报告期读到 transport_failure 空快照时显式告警。**运行前提：跑的时候 VPN/代理需可达 polymarket。** |
| PM-DATE-1 ✅ | **检索词年份锚定到 2025**：LLM 派生提示词未钉当前日期，模型按训练期"当前年"产出 10/16 条 2025（已判定）市场检索词（"Fed rate cut December 2025"…），即使网络可达也只会命中已关闭市场。 | `build_market_queries_prompt` 无日期锚 | 提示词钉 TODAY + 「只检索今天及以后判定的事件；horizon 内只锚定剩余会议日」。 |
| RUN-KILL-1 ✅(已定位) | **管线 51% 处失败**：research(质量0.77/82源)→ontology→graph 全部完成或近完成，14:26 本地后端进程重启（当日修复工作）→ orphan reclaimer 判 owner 死亡标记 failed。error 字段自带说明。 | 后端重启的附带伤害 | 无代码缺陷；research/graph 工件完好，VPN 恢复后可 cancel-then-resume 续跑（跳过 research）。 |

**验证**：`test_bridge_prediction_markets.py` +3 测试（日期锚提示词 / 死线悬挂归因 / base URL env 覆盖），连同 `test_parallel_research_merge` 共 98 测试全绿。
