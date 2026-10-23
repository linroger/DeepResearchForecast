# Pipeline improvement ideas — reflexive simulation, deep research, evaluation, systems

> Follow-up: [first-principles review](first-principles-review.md) rechecks the current source, corrects several earlier shortcuts, and provides a proposed architecture and testable sequence. The historical measurements and effort estimates below are not fresh verification.

**Status:** proposals, 2026-10-23. Nothing here is implemented or decided.
**Method:** four specialist readers (world-model realism, deep research, forecasting/evaluation, systems) each read the relevant code and handoff records and proposed ranked ideas with file anchors, cost, validation and risks. This document is the synthesis and ranking; the panel's raw output is in the session's workflow journal `wf_fddb743c-a0e`. Load-bearing claims marked ✓ were re-checked against the tree on 2026-10-23; claims marked (panel) were not independently re-verified.

The key words MUST, SHOULD and MAY are to be interpreted as described in RFC 2119. Nothing below re-litigates ADR 0003 (simulation output is a gated `simulated` record; the report's probabilities are research-only).

---

## 0. The one finding that orders everything else

The system has a complete scoring stack and no scores.

- The production ledger holds 214 forecasts and zero resolved outcomes ✓. `forecast_ledger.due_for_resolution` has no runtime caller ✓. `RESOLUTION_MONITOR_AUTORUN_HOURS` defaults to 0 ✓ and the monitor visits only the ten newest reports (panel).
- The backtest driver and its four ablation arms exist and have never run (docs/handoff/backtest/handoff.md §4). The golden set is 30 questions, 80% YES, 17 of them elections or sports, all resolved before any 2026 model's training cutoff, so every retrospective score is an upper bound (docs/handoff/backtest/design.md §6).
- Most binaries cannot be settled by a machine: in the twelve most recent `forecast.json` files, 142 binaries carry 26 official-data anchors and 9 market anchors; the rest are `unanchored_binary`, which the feedback journal refuses to score even manually (panel, `forecast_feedback.py`).
- The simulation has no measurement loop at all: nothing it produces is ever compared with the world, every realism iteration was judged by gates and review, and the world-v1 gate is still "promotion withheld".
- Every calibration knob is dead or unmeasured: `REPORT_RECALIBRATE_FROM_LEDGER` is not defined in config, `REPORT_SPINE_SELFCONSISTENCY_K=1`, `ENSEMBLE_EXTREMIZE_A=1.0`, `N_FORECAST_SEEDS=1`, all waiting for a "WP14 PromotionDecision" that exists only as a comment (panel).

Until outcomes flow, every other improvement is judged by taste. The highest-value program is therefore not a better prompt or a richer kernel; it is closing the loop so that the next hundred decisions about prompts and kernels can be measured. Ideas are ranked below with that in mind: feedback loops first, deterministic zero-LLM wins second, model-side changes third.

---

## 1. Close the measurement loop (cross-cutting)

### 1.1 Standing prospective forward cohort — weekly short-horizon questions, paired arms, auto-resolved
**Today.** Forward testing is a template with two example entries and a `forward-check`/`forward-score` CLI; nothing proposes questions, starts runs or watches outstanding reports.
**Proposal.** `backend/scripts/forward_cohort.py`: `propose` mines resolvable questions from sources already wrapped in the code (Polymarket markets closing in 14–84 days above the volume floor; FRED/BLS release calendar for series the data layer can settle), balanced by category and by market-implied YES/NO; `start` submits each question as a pair of arms (`research_only`, `production`) at the quick profile, N per week capped; the monitor gains `--outstanding` driven by `list_outstanding_published_questions`; `forward-score` reports per-arm paired Brier/log deltas with bootstrap CIs and ECE. Cohort files live under `docs/handoff/backtest/forward/`.
**Effect.** First clean, memorisation-free calibration numbers in six to eight weeks, and a paired estimate of whether Stage 5 plus markets beat research alone.
**Cost.** 3–4 days; about twelve quick pipelines a week, owner-approved. **Validate.** `propose --dry-run` on a frozen fixture yields ≥6 valid questions; after eight weeks n_resolved ≥ 40 with every started question terminal (I-20). **Risk.** The cohort's short-horizon, market-settled questions differ from production's multi-year geopolitics; keep it as its own track and never pool it with production rows.

### 1.2 Resolvable by construction — resolution contracts, an anchorable-share gate, a scored manual lane
**Today.** `_binary_quality` passes a set when 80% of rows match a number+date+metric regex; it never asks whether a row can be settled. `/api/v1/resolve` settles scenarios only.
**Proposal.** A typed `resolution_contract` per binary (`official_data` series/comparator/threshold/period, `polymarket` market id, or `named_source_event` publisher/event/deadline) requested in the extraction prompt and validated deterministically with the existing anchor validators; `anchorable_share` in `binary_quality` with a soft gate at 0.5 and one bounded top-up draw over the frame's official indicators; a `manual_binary` lane in `forecast_feedback` with `POST /api/v1/resolve-binary/<report_id>` requiring evidence text and the exact contract hash, scored separately.
**Effect.** The resolvable denominator rises from roughly a quarter to more than half of binaries, tripling feedback per run. **Cost.** 2–3 days; at most one extra LLM call per report. **Risk.** Goodhart toward what FRED and Polymarket measure; keep unanchored rows allowed and visibly counted.

### 1.3 Settlement-anchor scoping in research — the question's settlement source is researched, not guessed at report time
**Today.** The research scope returns only the restated question, horizon, scout queries and entities; nothing in the engine mentions resolution ✓. The data anchor is chosen at report time by the extractor from prose.
**Proposal.** Add an optional `resolution` object to the scope (settlement source, metric, comparator, threshold, observation period, units), resolve it deterministically to a catalog series before planning, keep one "settlement baseline" KIQ whose agent must fetch the publisher's latest value, release calendar and definition, and emit `forecast_inputs.anchors` that the extractor prefers over an LLM-chosen anchor when it passes validation. Record `anchor_status` in meta.
**Effect.** Pairs with 1.2: anchors become research-grounded, and unit and "by YEAR" ambiguities are stated before the forecast is written. **Cost.** No extra LLM calls, ~2 days. **Risk.** A mis-resolved series would settle wrongly; keep the one-stored-observation rule and never let a web-only anchor settle.

### 1.4 Simulated variable trajectories resolved against realised official series — a monthly signal that needs no forecast ledger
**Today.** The seed drops official series ids at seed time (panel, `world_model_seed.py`); K-path quantiles are reported but never scored; live seeds hold 0–3 official variables although dossiers name up to 20 indicators.
**Proposal.** Carry `series_id`, provider, frequency and the as-of observation on every official seed variable; add a `simulation-variable-resolution/v1` job to the resolution monitor that fetches each realised observation once a simulated period end has passed and scores path-0 error, p10–p90 coverage and CRPS per variable per period against a persistence baseline, writing only to the evaluation ledger, tagged simulated. First consumer: per-variable clamps derived from each series' own historical volatility instead of the global constants.
**Effect.** The first continuous accuracy signal for the simulation, resolving monthly instead of in years, and the only realistic route to the held-out evidence ADR 0003 demands before promotion. **Cost.** 3–5 days, zero LLM calls. **Risk.** Thin while seeds hold few official variables; never feed realised values back into a live run.

### 1.5 Affordable ablation — arms as forks of one research run, clustered golden questions, bootstrap CIs
**Today.** Each (question, arm) is a full pipeline, so a 30-question four-arm study is 120 pipelines. `PipelineOrchestrator.fork` already shares research, ontology and graph.
**Proposal.** Run `research_only` once per question cluster (≤4 same-as-of golden questions pinned together, which the pinned-questions rule already supports), then create the simulation and world-channel arms as forks with an arm overlay and all simulation→graph feedback pinned off; add paired bootstrap CIs and a sign test to `_paired_delta` and refuse to print "better" when the CI covers zero.
**Effect.** Cost per scored question falls three to four times; the first ablation result exists with honest uncertainty. **Cost.** 2–3 days plus one paid run of 10–12 quick pipelines. **Risk.** Forked arms share research randomness, which hides research-stage sensitivity; say so in the report.

### 1.6 Reference forecasters and skill scores in every scorer
**Today.** Scorers return raw Brier and log score; the market price at research time is stored on every market resolution row and never scored itself.
**Proposal.** Compute, per scored row, Brier for p=0.5, leave-one-out cohort climatology, the market at research/cutoff, and the parsed `base_rate_anchor` (extend the parser to "k of n" and "k/n" with Laplace smoothing), and report Brier skill scores with paired bootstrap CIs per reference and per lane. **Effect.** "0.18" becomes "beats the market by 0.03 ± 0.04 on 22 anchored questions". **Cost.** 1–2 days, no LLM. **Risk.** A skill score shown to the model would be an outcome channel; keep it in scorers and track-record metadata only (I-21).

### 1.7 Golden set v2 — post-cutoff, class-balanced, horizon- and domain-matched, with negated twins
**Proposal.** A curation script that builds ≥60 questions from resolved Polymarket markets after the model's documented training cutoff plus official-release threshold questions, enforcing ~50/50 YES/NO, 1–12 month horizons, production's category mix, and a negated twin for one in five questions to measure acquiescence. **Cost.** 1–2 days. **Risk.** If the vendor cutoff is unknown every row lands in `unknown`.

### 1.8 Outcome-blind policy promotion gate and per-lane reliability priors — the only sanctioned feedback into prompts (needs an ADR amending 0002 §5)
**Proposal.** `policy_promotion.py`: a candidate policy (recalibration slope, extremising factor, K draws, a skill revision hash) is frozen at time T, shadow-applied to every later report (a `shadow_probability` beside `probability`, never published), and promoted only when the prospective cohort resolved after T shows a paired skill lift with a CI excluding zero and n ≥ 30 in the lane; the decision is an immutable `PromotionDecision` pinned into the run policy at admission. The only prompt-side feedback is a deterministic, per-lane reliability line computed from rows resolved before the run's as-of ("monetary-policy binaries you priced 60–80% resolved YES 55% of the time, n=22"), rendered by code, with byte-identical absence below n=20 and no question or outcome text.
**Effect.** Every dead calibration knob becomes a measured, reversible loop, and I-21 becomes enforceable by construction. **Cost.** 3–5 days; needs outcomes from 1.1–1.4 first.

---

## 2. Reflexive world-state simulation

The panel's diagnosis, checked against the three saved live runs: the simulated share path is a head count because no run declares `outcome_power` and unknown power is substituted by a declared-neutral 1.0 ✓; the decision step is dominated by cheap talk (100% communication or coalition moves in one run, option ruts of two to five distinct options over nine rounds); consent mechanics manufacture breaches because every accepted agreement falls due the next period regardless of its terms (panel, `world_model.resolve_interaction`), so three of three and six of seven agreements were breached; the arbiter's `scenario_pressure` is an unaudited LLM opinion weighted at 0.35 while the seed's `scenario_indicators` are never read; K paths spread sampling noise, not strategic uncertainty; and the validated arbiter update is not persisted, so no replay harness can exist for the default kernel.

Ranked:

### 2.1 Persist the validated arbiter update and build a kernel replay harness
Store the validated `arbiter_update` and raw problems per round and per path (2–3 KB a round); add `backend/scripts/world_kernel_replay.py` that rebuilds the world from the sealed seed, replays saved decisions and updates through the deterministic kernel under overridden settings (clamp, pressure weight, TTL, due-date rule, outcome power) and reports trajectory, share and breach deltas, with a byte-identity check against the saved state when settings are unchanged. **Why first.** It is the validation substrate for every other kernel idea; "realism" arguments become measured deltas on real trajectories. **Cost.** 2–3 days, no LLM. **Risk.** Open-loop only; replayed decisions do not react to a changed world, so deltas understate second-order effects.

### 2.2 Agreement obligations due from the terms' own dates; mechanical breaches accounted separately
Parse dates and durations in offer `terms` to set `due_round`, keep today's rule as fallback with `due_basis ∈ {terms, default}`, split breach cause into `withdrawn` versus `lapsed_default_due`, expose `mechanical_breach_share`, and leave obligations due after the horizon `open`. **Why.** Track records and reputation are the credibility channel the arbiter now weighs; today they are dominated by an artefact. **Cost.** 1–2 days, no LLM. **Validate.** Replay (2.1) the saved runs and count reclassified breaches.

### 2.3 Outcome power from documented resolution authority instead of the uniform fallback
The v3 frame emits per actor `resolution_authority ∈ {decides, vetoes, implements, influences, none}` only when a report line states the actor's decision right (line-checked like risks); the seed maps it to a declared tier with a recorded basis; the run summary reports `power_known_share` and the Herfindahl concentration of committed weight; the after-action record states the basis beside its share table. **Why.** Simulated shares start to reflect who can settle the question rather than how many personas talk. **Cost.** 2–3 days plus one paid frame check. **Risk.** Mislabelled authority; mitigated by the citing-line requirement, and "none" actors keep deciding.

### 2.4 Decision-quality diagnostics and placebo arms
Deterministic per-run diagnostics: cheap-talk share, per-actor option entropy and longest rut, capacity utilisation, incentive consistency (does the scenario an actor pushes appear under its `gains_if` rather than `loses_if`), hold-by-status. Then a pre-registered placebo harness on one seed: public brief frozen at round 1 (no reflexivity), role briefs shuffled across the cast, and `recent_discourse` emptied; report the L1 distance of decision-kind distributions and share trajectories between the real arm and each placebo against seed-to-seed variance. **Why.** If the no-discourse arm shows no effect, the OASIS audience (most of the ~1.3M simulation tokens) can shrink; if the frozen-brief arm shows no effect, the reflexive loop carries no information and prompt work is targeted at that. **Cost.** Diagnostics 1–2 days; placebo runs are paid.

### 2.5 Indicator-derived scenario pressure as a deterministic check on the arbiter
The frame emits each indicator's direction per scenario only when a report line states it; the seed binds indicators to tracked variables; the kernel derives `indicator_pressure` from realised variable movement; the run records per-round agreement between arbiter and indicator pressure, and `SIM_WORLD_PRESSURE_SOURCE=arbiter|indicators|both` selects what enters the share step (default unchanged). **Why.** Persistent disagreement flags the LLM's prior being laundered into the share path; the indicators arm gives the world-channel ablation a research-grounded variant. **Cost.** 2–3 days plus one paid frame check.

### 2.6 Structured, scoreable expectations — an actor-foresight Brier
Add an optional structured form `{actor, kind, p}` to `expected_reactions` in the same decision call, score it next period against the realised option kind against a base-rate predictor, and surface `foresight` beside `track_record` in briefs and the arbiter prompt. **Why.** The perception side of reflexivity becomes a number; if actors cannot beat the base rate, the expectations channel is noise and can be removed. **Cost.** 1–2 days, no extra LLM calls.

### 2.7 Decision-side branching at one pivotal round so K paths carry strategic uncertainty
Pick at most one pivotal round per run by a fixed documented score (open offers, red lines at stake, irreversible options on principals' menus); in that round elicit one extra decision sample per principal at higher temperature and feed it to the upper half of the paths, path 0 unchanged and byte-identical; name the branch round as the record's turning point. **Cost.** 2–3 days plus one decision call per principal per run. **Risk.** The pivot rule editorialises; fix, document and test it as ADR 0003 did for decisive moves.

---

## 3. Deep research

The panel's diagnosis, checked: scenario weights are fixed at plan time from at most six scout searches and a 6,000-character digest ✓, enforced on every restatement by `fix_scenario_weights` ✓, and the forecast spine reads them; the number check runs only when the agent tagged a fact VERIFIED ✓, so across 19 stored runs 1,416 facts were never checked and 810 REPORTED facts that cite a fetched page could have been; `sources.json` rows are written with `date=None` ✓ and `independent=None` (panel), so independence and freshness, which ADR 0002 names as ledger authority, are unimplemented; frame base rates and drivers are copied unverified and saturate their caps in every stored run (panel); no deterministic check exists for the numbers writers put in final prose.

Ranked:

### 3.1 Evidence-based tags — number-check every fact that cites a fetched page, promote confirmed facts, fix the annotated-tag regex
Accept `(VERIFIED — reason)` forms in the tag regex and strip the parenthetical; run the page-number check for every fact whose cited sources include a fetched page; promote a REPORTED fact to VERIFIED only when every cited source is fetched and every number is on those pages; never demote REPORTED to UNVERIFIED; count promotions and mismatches in meta. **Why first.** Hundreds more findings per corpus become plainly statable at zero model cost, and agents' tagging errors stop deciding what gets verified. **Cost.** About a day. **Validate.** Replay over the 19 stored runs' KIQ records and pages; hand-check 50 promotions and 50 flags.

### 3.2 Prose-number provenance — a deterministic QA check that every number in the final report is on the page it cites
Split the report into cited sentences, check each number against the union of its cited fetched pages (snippets for snippet-only sources), emit confirmed/unconfirmed counts and offending sentences, add an advisory `number_provenance` QA check and a quality-score component, and route unconfirmed sentences into the existing bounded repair path. **Why.** Catches writer drift and recomputation at the number level, which is exactly what a forecast consumer anchors on. **Cost.** 2–3 days, no LLM in audit mode.

### 3.3 Evidence-conditioned scenario frame — a shadow posterior scored against the plan-time prior before it ever replaces the frame (needs an ADR)
After gather and gap rounds, one JSON call laid out with the same cached prefix the writers use returns, for the same scenario names, a posterior weight set with cited rationale and the base rate it leans on, under deterministic bounds (sum 100, floor 2, total mass moved capped, markers must resolve). Phase 1 persists `frame_prior` and `frame_posterior` in `plan.json` with the report byte-identical; Phase 2 adopts the posterior before synthesis only after a prospective paired lift. **Why.** The research-only probability authority becomes a function of the evidence the run paid for rather than of six snippets; today the gold run restates its scout-time 45/25/20/10 verbatim. **Cost.** One extra mostly-cached call per run, 3–4 days, then a backtest of two research-only arms. **Risk.** Anchoring toward narrative scenarios; caps, floors and shadow-first mitigate.

### 3.4 Source-origin independence clusters driving the coverage matrix and gap review
Deterministic origin clustering at finalize (eTLD+1, collapsed by shared shingles across fetched pages or by named-publisher attribution in the fact text); per-KIQ `single_origin_pivotal=N` in the coverage matrix with a gap rule that spends follow-ups on corroborating load-bearing numbers; `independent` filled in `sources.json`; an independence component in the quality score. **Why.** Forecast inputs stop resting on one echo chain unnoticed; today zero of 1,047 VERIFIED facts cite two distinct domains (panel). **Cost.** 2–3 days, no LLM.

### 3.5 Freshness captured at fetch and search time
Capture dates before HTML is stripped (Last-Modified, article:published_time, JSON-LD, `<time>`), date every live search row, render "(dated …)" or "(undated)" in seed rows, SOURCE INDEX and digest lines, add a stale-pivotal rule when a stored official series is newer than a cited fact, and a freshness quality component. Today date extraction runs only under a backtest policy, and only 5.5% of stored live pages still contain a date after stripping (panel). **Cost.** About 2 days, no LLM.

### 3.6 Line-checked base rates and drivers plus a deterministic official base rate at research time
Extend the risks discipline to base rates and drivers (keep a row only when its numbers stand on a report line carrying its marker); where a stored series and an explicit comparator exist, compute the share of h-step changes crossing the threshold deterministically and emit it as an official base-rate row and digest line. **Why.** The spine stops receiving quota-filled base rates, and where official history exists the outside view is computed, not narrated. **Cost.** 1–2 days.

### 3.7 Deterministic numeric-disagreement detector
Normalise `quantitative.json` rows by metric, period and unit; flag conflicts across origins and against stored official series; carry KIQ-level conflicts into `contested.json`; add `conflicts_unresolved` to the coverage matrix; render conflicted metrics as ranges in the spine's quantitative block. **Cost.** 1–2 days.

---

## 4. Systems, cost and robustness

### 4.1 Make content-filter rejections request-scoped
A GLM 400/1301 content filter currently counts toward the provider-wide 422 breaker ✓ (`_cb_record_422` in `LLMClient.chat`), whose synthetic fast-fail is then classified as a provider outage and counted toward the run halt; the code's own docstring records the 2026-10-18 incident. Do not record content-filter errors against the breaker unless a fallback provider is configured, type the fast-fail's cause, exclude `content_filter` from outage classification, and keep a separate high-threshold counter for a moderation-wide outage. **Cost.** 1–2 days. **Why first.** It removes the dominant whole-run killer on the default provider.

### 4.2 Truthful run forensics
Write a config snapshot hash, the pin-divergence table, the dirty-file count and the bridge source hash into `run.json`; replace the synthetic one-row research telemetry with the engine's own usage totals including cached tokens and a cached-read rate in cost estimation (panel: one run's `telemetry.json` prices 1.6M input tokens at full rate although 1.32M were cache reads). **Cost.** 1–2 days.

### 4.3 One cross-process provider lease for every LLM call site
Promote the research engine's SQLite model lease to a provider-keyed shared limiter used by the report stage, translation pool, OASIS agents, graph executor and world model, honouring Retry-After for every process, so 429 storms become bounded waiting instead of breaker trips and run halts. **Cost.** 2–3 days.

### 4.4 Disk-persistent content-addressed LLM cache and section-level report resume
Success-only disk tier for `LLMCache`; `generate_report` resumes from `section_NN.md` whose outline and prompt-prefix hashes match; spine, extraction and translation inputs persisted so a failed later phase re-runs only itself. **Why.** A killed or gate-failed report costs only the missing phases, and byte-level isolation tests such as ADR 0003's T1 become cheap to run offline. **Cost.** 3–4 days.

### 4.5 Typed research bundle feeding graph and report (Foglamp WP7 direction)
Assemble `research_bundle/v1` once from the typed files v3 already writes; project actors, relationships, timeline and quantitative rows into the graph deterministically before LLM extraction (which then runs only on uncovered chunks); render one byte-stable evidence header for every section prompt instead of nine prose packs. **Why.** Graph wall time and report prompt-cache misses fall, and one place where research numbers enter prompts removes a class of drift the lint repairs after the fact. **Cost.** 5–8 days. **Risk.** Making the bundle authoritative would need an ADR 0002 amendment; keep it a projection.

### 4.6 Per-run append-only `events.jsonl` as the WP16A shadow record
Stage transitions, reuse verdicts with manifest detail, resume/fork/cancel commands, classified provider errors, breaker and budget events, with a projection test that rebuilds the status view from events. **Cost.** 2–3 days.

### 4.7 Make the plain suite a binary gate
Fixture errors become skips when `deer-flow/` is absent; a skip budget by reason; env-drift checks as tests; demo-bundle tests gated on `docs/demos` changes; the Kaleido launch flake skipped on its specific error class. Today's frozen-copy run is 7,707 passed, 9 failed, 19 errors, 1,668 skipped, and all failures pre-date this branch. **Cost.** About a day.

---

## 5. Suggested sequencing

| Weeks | Work | Why this order |
|---|---|---|
| 1 | 3.1 tags and number checks · 2.2 agreement due dates · 4.1 content-filter scoping · 4.2 forensics · 4.7 suite gate | Zero-LLM, high certainty, each removes a known artefact or incident class |
| 2–3 | 1.3 settlement-anchor scoping → 1.2 resolution contracts → 1.1 forward cohort · 1.6 skill scores · 1.5 forks for ablation | Builds the feedback loop; by week 8 real outcome numbers exist |
| 3–4 | 2.1 arbiter-update persistence and replay → 2.3 outcome power → 2.4 diagnostics and one placebo set · 1.4 variable-level resolution | Makes the simulation measurable before changing it further |
| 5–6 | 3.3 evidence-conditioned frame in shadow mode · 3.2 prose-number provenance · 3.4 independence · 3.5 freshness | Research-quality signals that can later be correlated with resolved Brier |
| after outcomes | 1.8 promotion gate (ADR) · 1.7 golden v2 · 4.3–4.6 structural | Promotion only with held-out evidence (I-21) |

## 6. What was not re-verified

The `resolve_interaction` due-date rule, the exact research telemetry collapse (`calls=1`, dropped `cached`), the `independent=None` write site, the 1,416 never-checked facts and the 0-of-1,047 two-domain figure are the panel's measurements on stored artifacts and were not independently recomputed here. Each proposal above names the replay or test that would confirm it before any code lands.
