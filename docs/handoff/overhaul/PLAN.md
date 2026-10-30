# PLAN.md — DeepResearchForecast overhaul: one world model, one workflow

**Status:** Draft for the owner's approval. No code has been written.
**Date:** 2026-10-28. **Base:** `main` f773f61 (shared with a Codex process; compare-and-swap only).
**Supersedes:** the draft "first ten remedies" PLANS.md of 2026-10-27, whose slices reappear here as Phase A and the early slices of Phases B–F.
**Companions:** first-principles review parts 1–2, the remedy register, the integrated-workflow design (2026-10-27/28), ADR 0001–0003.
**The key words MUST, SHOULD and MAY are used as in RFC 2119.**

---

# Part I — Scope, principles, invariants

## I.1 What this plan builds

A single workflow that turns a question into a calibrated, explained forecast by (1) establishing the present state of the world and collecting future-facing evidence through target-led research, (2) grounding actors' identities, incentives, constraints, levers and beliefs in a provenance-layered world model, (3) simulating how those actors act and how the world evolves through explicit mechanisms up to the horizon, (4) estimating the target with several estimators of different error structure and combining them under a declared, measured rule, and (5) publishing views of the world model that a decision-maker can use, then monitoring, resolving and learning.

## I.2 Principles

1. **The world model is the hub.** Every phase reads and writes one typed store. Prose is a view rendered at the end and never parsed back.
2. **The forecast is computed, then explained.** The target is a node with an identity; estimators propagate uncertainty through structure; LLMs build and justify structure, decide for discretionary actors, and explain results. No LLM is asked to intuit a probability from a digest.
3. **Record classes never merge silently.** observed, inferred, assumed, simulated, forecast, resolved. Every query names the classes it accepts.
4. **Every agent step has a contract.** Fixed context layout, a typed output schema, deterministic validation, a repair path, a deterministic fallback, a budget and a test.
5. **Every behaviour change ships behind a flag** whose previous value is byte-identical to today, with a test that proves it, until its acceptance passes.
6. **Nothing is believed until outcomes resolve against it.** Measurement is part of the design.

## I.3 Invariants carried forward

I-1 agents never see our scenario shares or any forecast-class record; I-3 unknown outcome power stays unknown; I-11 simulated records never merge with observed or forecast records; I-16 hollow runs yield stubs, not narrative; I-21 no probability policy is promoted without held-out prospective evidence; ADR 0003's RW-11 byte-level isolation test, extended rather than bypassed. New: **I-30** no actor is handed analyst-inferred claims about itself as its own knowledge; **I-31** every number in published prose resolves to a typed row; **I-32** every mechanism parameter has a basis (claim, reference class or stated assumption); **I-33** the simulation is conditioned on structure and evidence, never on any estimator's probabilities.

## I.4 Operating constraints

One branch per slice in its own worktree; the deployment checkout and its `backend/uploads` are never written; suites run on frozen rsync copies; guarded modules under `backend/scripts/main_offline_pytest.py`; `main` advances by compare-and-swap; pushes fast-forward with `env -u GH_TOKEN -u GITHUB_TOKEN`; no paid run, network probe or scheduled job without explicit approval; records in `docs/handoff/overhaul/handoff.md` plus ADR amendments where published-probability inputs change.

---

# Part II — The world model store

## II.1 Record classes and layers

| Class | Writers | Readers |
|---|---|---|
| **observed** | research (claims, calendar, intentions, indicators, third-party forecasts), data channels, outcome monitor | everyone |
| **inferred** | research synthesis, actor-intelligence extractor, conflict detector | compile, estimation, views; never an actor about itself |
| **assumed** | model compile, prior elicitor, human review | compile, simulation, estimation, views |
| **simulated** | the simulation only | estimation (conditionals), views, scorers; actors (within information set) |
| **forecast** | estimation layer only | views, journal, scorers; never actors |
| **resolved** | resolution monitor only | scorers, views, libraries |

## II.2 Storage

`backend/uploads/pipelines/<pid>/world_model/`:
- `world_model.sqlite` (WAL) — the live store during a run: one table per schema (Appendix A), every row carrying `record_class`, `run_id`, `phase`, `created_at`, `provenance` (claim ids or step id), `hash`. The query contract (II.4) is implemented as SQL views over these tables. Chosen over JSONL for queryability by agents and over Graphiti because the graph is a projection of this store, not the other way round.
- `exports/<phase>/*.jsonl` — sealed exports at each phase boundary (canonical JSON, sorted keys), hashed into `manifest.json`; these are what reuse, resume and replay read. World-v1's seal discipline (`artifacts.seal_inputs`) is reused.
- `agent_io/<step_id>/<call_n>.json` — every agent call's input hash, output, validation result and repair history, so any step can be replayed without the provider.

## II.3 Schemas (index; fields in Appendix A)

`forecast-contract/v1`, `resolution-tree/v1`, `claim/v1`, `calendar-event/v1`, `intention/v1`, `third-party-forecast/v1`, `indicator/v1`, `base-rate/v1`, `hazard/v1`, `actor-dossier/v1`, `mechanism/v1`, `assessment/v1`, `domain-ontology/v1`, `compiled-world/v1`, `plan/v1`, `decision/v1`, `action/v1`, `effect/v1`, `event/v1`, `path/v1`, `estimator/v1`, `aggregation/v1`, `crux/v1`, `signpost/v1`, `card/v1`, `outcome/v1`, `registry-entry/v1`.

## II.4 The query contract

Typed functions over the store, each taking `(classes_allowed, as_of_period, actor_scope)`:

`identity(actor)`, `levers(actor)`, `beliefs(actor)`, `claims_about(entity, topic, since)`, `statements_by(actor, since)`, `commitments(actor, status)`, `history(variable, k)`, `events_aimed_at(actor, since)`, `offers_pending(actor)`, `red_lines_crossed(actor)`, `calendar(window)`, `expectations(actor)`, `tree(node | subtree)`, `mechanisms(variable)`, `estimators(target)`, `outcomes(target)`.

The **information-set filter** `visible(record, actor, t)` admits: observed records whose release date ≤ t (per the observation model); the actor's own actor-known dossier items; simulated records the actor produced, received or could observe publicly by t; never inferred records about the actor itself (I-30), never other actors' private rationale, plans or beliefs, never forecast-class records (I-1). Estimators and views use `actor_scope=analyst`, which admits everything but still labels classes.

---

# Part III — The workflow, step by step

Every agent step below is specified by: **Kind** (agent | deterministic | gate), **Trigger**, **Context** (ordered blocks with token caps; the first two blocks are the cached prefix), **Output** (schema), **Validation and repair**, **Fallback**, **Model** (tier, temperature, max output), **Budget** (calls and tokens per run, estimated), **Tests**. The context layout for every agent call is `[CORE_<family>][CONTRACT][SNAPSHOT_<phase>][TASK]`: `CORE` is the fixed system text for the step family (cached across runs), `CONTRACT` is the run's contract rendering (cached across the run), `SNAPSHOT` is a phase-shared block (cached within the phase), `TASK` is the step payload. All agent replies are JSON unless stated; replies are parsed strictly (no duplicate keys, no floats where integers are required) and validated against the schema before anything is written.

## Phase 0 — Admission and contract

### A-00 Contract drafter — agent
**Trigger.** Admission of a question (SPA, SDK, backtest). **Context.** `CORE_contract` (what a target, settlement, predicate are; refuse to invent) · the question, language, as-of, options (≤ 1k tokens) · the official-data catalog's best 20 series matches with units and frequencies (≤ 1.5k) · the reference-class library's 10 nearest entries (≤ 1k) · scout snippets if available (≤ 2k). **Output.** `forecast-contract/v1` candidate: `targets[] {id, kind quantity|event, metric, unit, geography, period, settlement {source, series_id?, publisher?, release_calendar?}, current_hint}`, `horizon {as_of, horizon_date, period_length, basis}`, `scenarios[] {name, predicate {target_id, op, bounds, conjuncts[]}}` (provisional), `binaries_seed[] {statement, node_hint, contract_hint}`, `key_entities[]`, `open_questions[]`. **Validation.** ISO dates; horizon after as-of; predicates parse and partition the target range (gaps and overlaps rejected); every target has a settlement source or an explicit `settlement: none` with reason. **Repair.** One retry with the validator's messages. **Fallback.** Today's `admit_forecast_task` horizon binding plus a single quantity target with `settlement: none`. **Model.** strong, T 0.2, ≤ 2k out. **Budget.** 1–2 calls. **Tests.** The specimen question yields the Gartner 2027 target with a Gartner settlement; a yield question yields DGS10 with FRED; a malformed horizon is rejected.

### A-01 Contract reviewer — agent
**Trigger.** After A-00. **Context.** `CORE_review` · the question verbatim · the candidate contract. Nothing else. **Output.** `{verdict: accept|revise, issues[] {field, problem, suggestion}}`. **Validation.** Issues must name contract fields. **Fallback.** Accept with `reviewed: false`. **Model.** strong, T 0. **Budget.** 1 call. **Tests.** A contract that silently narrows a multi-target question is flagged; a correct one is accepted.

### A-02 Contract validator — deterministic
Applies reviewer fixes, resolves settlement series against the catalog, computes `period_length` from the fastest-mechanism rule (default month for ≤ 24-month horizons, quarter beyond, day for ≤ 60-day horizons), stamps `contract_hash`, writes the contract (observed/inferred classes as appropriate). Backwards compatible: `forecast_task_v1` is emitted as a projection.

### G0 Contract gate — optional human gate
Renders the contract as one screen; edits are recorded as `assumed` with the reviewer as source. Default off; on for the first ten runs of the new workflow.

## Phase 1 — Research

### R-00 Channel prefetch — deterministic
Markets, news and official data fetched asynchronously at admission with per-channel budgets (news 60 s, markets 30 s, data 150 s), each writing `channel_health {status, as_of, rows, error}`; last-good snapshot cache (age ≤ 7 days) used when live fails, flagged `stale`.

### R-01 Scout — agent (existing, unchanged in kind)
4–6 searches, digest ≤ 6k chars, used only by A-00 (hints) and R-02.

### R-02 Tree builder — agent
**Trigger.** After the contract. **Context.** `CORE_research` (the existing ENGINE_CORE, extended with tree rules) · CONTRACT · scout digest (≤ 2.5k tokens) · catalog matches with current values and vintages (≤ 1.5k) · reference-class hits (≤ 1k) · mechanism template catalogue names and signatures (≤ 800). **Output.** `resolution-tree/v1`: `target_id`, `nodes[] {id, label, kind quantity|rate|event|state, parent, relation identity|driver|indicator, expression?, unit, current {value, vintage, sid?} | null, status settled|contested|unknown, sensitivity 1–5 with reason, actors[] {name, lever_hint}, indicators[] {name, source_hint, cadence}, settlement_hint}`. **Validation.** Units consistent along identities; every node has a status; the target node exists with `relation: identity` children or a stated reason it cannot be decomposed; ≤ 40 nodes; identity expressions parse and, where all inputs have current values, hold within 10% (else the node is `contested` with the residual recorded). **Repair.** One retry with validator messages. **Fallback.** A two-level default tree (target; drivers from the planner's KIQ templates) flagged `tree_fallback`. **Model.** strong, T 0.2, ≤ 4k out. **Budget.** 1–2 calls. **Tests.** The specimen yields spending = base × (1+g) with ≥ 4 g-terms, each with status; a contradictory identity is flagged.

### R-03 Planner — agent (revised)
**Trigger.** After R-02. **Context.** CORE · CONTRACT · tree (compact rendering, ≤ 3k) · the six future-evidence kinds and where each goes (≤ 400) · data catalog matches (≤ 1k) · method-skill menu (existing). **Output.** `plan/v1-research`: `kiqs[] {id, node_ids[], question, kind general|actor|data|calendar|adversarial, strategies[] publisher_first|data_first|primary_document|adversarial|second_language, queries ≤ 3, data_needs ≤ 3, why}`, `actor_kiqs[] {actor, intentions_and_calendar: true}`, `hazard_kiq`, `settlement_kiq` (one per target: fetch the publisher's latest value, definition, release calendar). The outline is **not** produced here; it is derived deterministically from the tree in R-13. **Validation.** Every pivotal node (sensitivity ≥ 4) has ≥ 1 KIQ; the adversarial KIQ exists; counts within preset. **Fallback.** Today's plan prompt with node ids assigned by lexical match. **Model.** strong, T 0.3. **Budget.** 1 call. **Tests.** Coverage of pivotal nodes; adversarial KIQ present; settlement KIQ per target.

### R-04 KIQ investigator — agent (existing tool-using agent, typed notes)
**Trigger.** Per KIQ, fan-out after a prime call. **Context.** CORE · CONTRACT (the brief) · KIQ task: node(s) with current status, strategies, seed rows (≤ 6 web, ≤ 4 context, data rows), budget text, method-skill notes. **Tools.** `web_search`, `web_fetch`, `data_search`, `data_get`, `news_search`, `market_compare` (unchanged). **Output.** Notes in the existing markdown-with-markers format extended with typed sections, each line carrying `[S#]` and a date: `## FACTS` (tagged), `## CALENDAR` (date, event, source), `## INTENTIONS` (actor, statement, date, source), `## FORECASTS_BY_OTHERS` (author, target, value, vintage), `## INDICATORS` (name, latest, cadence), `## BASE_RATES` (reference class, frequency, basis), `## HAZARDS` (event, probability, window, source), `## CONFLICTS`, `## OPEN`, `## DISCOVERED`. **Validation.** `postprocess_notes` extended: each typed line must parse and cite a shown source; dates ISO or a named period. **Fallback.** Deterministic notes from read pages (existing). **Model.** strong, T 0.3. **Budget.** 7–12 KIQs × 5–9 steps (existing presets). **Tests.** Typed sections round-trip to `claim/v1`, `calendar-event/v1`, `intention/v1`, `third-party-forecast/v1`, `indicator/v1`, `base-rate/v1`, `hazard/v1`.

### R-05 Claim verifier — agent, bounded
**Trigger.** For each fact tagged VERIFIED or REPORTED that supports a pivotal node (sensitivity ≥ 4), after gather. **Context.** `CORE_verify` (judge support only; no outside knowledge) · the claim text · the cited passage(s) (≤ 1.2k tokens each, the passage selected at verification time) · the entity, metric, period and unit the claim asserts. **Output.** `{verdict: supports|contradicts|insufficient, span, mismatch: entity|period|metric|modality|none}`. **Validation.** Span must be a substring of the passage. **Fallback.** `verdict: insufficient`, tag unchanged, `passage_supports: null`. **Model.** fast, T 0, ≤ 300 out. **Budget.** ≤ 60 calls per run (cap; pivotal claims first). **Tests.** Right-number/wrong-entity, wrong-period, reversed-relation, target-as-actual fixtures are `contradicts`/`insufficient`; genuine support passes.

### R-06 Conflict detector — deterministic
Normalises quantitative claims by metric, period, unit and geography; flags differences beyond tolerance across origins and against official series; writes `inferred` conflict records and the `contested` list; origin clustering fills `independent`.

### R-07 Gap reviewer — agent (revised)
**Trigger.** After gather, per round within preset. **Context.** CORE · CONTRACT · tree with per-node status, sensitivity, fact and verified counts, single-origin pivotal claims (≤ 2.5k) · conflicts (≤ 1k) · open questions (≤ 1k) · questions already investigated · remaining budget. **Output.** `{verdict: continue|complete, stop_reason: sufficient|budget|inaccessible|rejected, follow_ups[] {node_id, question, strategy, why}}`. **Validation.** Follow-ups name nodes; Jaccard dedup against existing KIQs. **Fallback.** `complete` with `stop_reason: budget`. **Model.** strong, T 0.2. **Budget.** 1–2 calls. **Tests.** A planted empty pivotal node gets a follow-up; `stop_reason` recorded.

### R-08 Actor intelligence extractor — agent, per actor
**Trigger.** After gap rounds, for each actor in the registry (tree actors ∪ planner actors ∪ cast candidates), capped at 20. **Context.** `CORE_actor` (schema; actor-known vs analyst-inferred rule; cite claim ids; never invent levers or authority) · CONTRACT · the upper-ontology actor schema (≤ 600) · the tree's nodes that name this actor (≤ 800) · all claims mentioning the actor or its aliases, typed, with claim ids, dates and sources (≤ 12k tokens, most recent and pivotal first). **Output.** `actor-dossier/v1`: `identity {upper_type, subtype, mandate, decision_process {who, rule, cadence}}`, `objectives[] {text, priority, basis claim_ids, class}`, `constraints[]`, `levers[] {name, variable_hint, range, unit, lag, reversibility, authority sole|shared|consent|vote, basis}`, `beliefs[] {proposition, confidence, basis}`, `values_style {risk_tolerance, time_preference, reactivity, instruments}`, `red_lines[] {predicate_text, basis}`, `intentions[] {statement, date, due, basis}`, `relationships[] {counterparty, kind, valence, basis}`, `track_record[] {commitment, kept|broken|pending, basis}`, every item `class: actor_known|analyst_inferred`. **Validation.** Every item cites ≥ 1 claim id that exists; levers with `authority` other than `sole` name the co-holder; no item without a class. **Repair.** One retry listing uncited items. **Fallback.** The legacy flat fields (`goals`, `constraints`, `incentives`) mapped with `class: analyst_inferred` and `basis: legacy`. **Model.** strong, T 0.2, ≤ 3k out. **Budget.** 8–20 calls. **Tests.** The specimen's CISA dossier yields the CIRCIA lever with `authority: shared (OMB)`, the "continues to work on the final rule" intention dated, and `stated_vs_revealed` as `analyst_inferred`.

### R-09 Mechanism elicitor — agent, per edge group
**Trigger.** After R-08, for each tree edge (driver → term) grouped by template. **Context.** `CORE_mechanism` (templates and their parameters; bind to claims or declare an assumption; units) · CONTRACT · the edge (source, target, units, current values) · the template catalogue entry (signature, parameter list, typical ranges from the library) · claims about this relation (quantities, elasticities, past episodes; ≤ 4k) · reference-class rows (≤ 1k). **Output.** `mechanism/v1`: `edge_id, template identity|elasticity|reaction|delay|threshold|hazard|adoption, form (expression), parameters[] {name, point, low, high, unit, basis {kind claim|reference_class|assumption, ids[], note}}, onset_periods, completion_periods, applicability, confidence`. **Validation.** Dimensional check of the form; parameters within template bounds; every parameter has a basis (I-32); an `assumption` basis requires a note. **Fallback.** Template defaults with wide library ranges and `basis: assumption`, flagged `mechanism_gap`. **Model.** strong, T 0.2, ≤ 1.5k out. **Budget.** 6–20 calls. **Tests.** Mandate-term elasticity binds to a claim where one exists; a missing elasticity yields a wide assumed prior, never a failure.

### R-10 Assessment (prior → posterior) — agent
**Trigger.** After R-09. **Context.** CORE · CONTRACT (with predicates) · the plan-time prior (if any) labelled · tree with statuses and current values (≤ 3k) · pivotal claims with verification flags (≤ 6k) · base rates (≤ 1k) · conflicts (≤ 1k) · hazards (≤ 600) · third-party forecasts (≤ 800). **Output.** `assessment/v1`: `version, prior[] {scenario, p}, posterior[] {scenario, p, delta, reasons[] {claim_ids, direction, weight}}, base_rate_used, cruxes[] {proposition, would_move_to, evidence_that_settles}`. **Validation.** Posterior sums to 1 ± 0.005 over the predicates; every delta beyond 0.02 has ≥ 1 cited reason; total mass moved ≤ cap unless a `definition_change` is declared (then `version` increments and comparability is marked false). **Fallback.** Posterior = prior with `reasons: []` and `assessment_status: fallback`. **Model.** strong, T 0.2, ≤ 2k out. **Budget.** 1 call (+1 retry). **Tests.** Duplicated evidence → no change; decisive counter-evidence fixture → justified change; definition change → version bump.

### R-11 Research writer — agent (existing section writers), **R-12 Research QA** — existing
Unchanged in kind; the digest is built from typed records; the scenario block renders the posterior; `fix_scenario_weights` enforces the posterior.

### R-13 Finalize projection — deterministic
Writes observed/inferred records from the typed notes (claims with passages, calendar events, intentions, forecasts by others, indicators, base rates, hazards), the tree, dossiers, mechanisms, assessment; derives the outline; renders `research_report.md`; exports `sources.json` with cited passages and dates; makes **no LLM calls**.

## Phase 2 — Ontology and graph

### O-01 Domain instantiation — agent
**Trigger.** After R-13. **Context.** `CORE_ontology` (the upper ontology, versioned; rules: no new semantics, subtypes only) · CONTRACT · actor registry (names, upper type hints from dossiers; ≤ 1.5k) · tree variables (≤ 1.5k) · mechanism templates used (≤ 500) · relationship kinds observed (≤ 300). **Output.** `domain-ontology/v1`: `actors[] {name, upper_type, subtype, lever_types[]}`, `lever_types[] {name, variable_kind, unit, authority_default, range_hint}`, `variable_kinds[]`, `relationship_kinds[]`, `population_aggregates[] {name, drives_variable, reaction_template}`. **Validation.** Every upper type exists; every lever type maps to a variable kind in the tree or a declared aggregate. **Fallback.** Upper types from `agency_class` inference, no subtypes. **Model.** strong, T 0.1. **Budget.** 1 call. **Tests.** The specimen yields `CyberInsurer ⊂ Firm` with an underwriting lever; no sentence-shaped edge types.

### G-01 Projection — deterministic
Builds the graph from the store: actors, variables, claims (as evidence nodes with sids and dates), relationships, mechanisms, calendar events, commitments; every edge carries `record_class`, `claim_ids`, `date`. Zero LLM calls. Layered: observed/inferred/assumed; the simulated layer is appended during Phase 4.

### G-02 Supplement extraction — agent, optional (`GRAPH_MODE=extract_uncovered`)
Only over research text chunks not covered by any claim (coverage by sid and passage overlap); output claims with sids; capped at 20 chunks. Default off.

### G-03 Entity resolution — deterministic (existing embeddings resolver, unchanged). **G-04 Views** — the GraphPanel and overlays read the projection with a class toggle.

## Phase 3 — Compile

### C-01 Adequacy assessor — agent
**Trigger.** After G-01. **Context.** `CORE_compile` · CONTRACT · tree summary with sensitivities (≤ 2k) · actors with levers and authority (≤ 3k) · mechanism summary (≤ 1.5k) · calendar (≤ 800). **Output.** `adequacy/v1`: `strategic_interaction {matters: bool, why, terms_affected[]}`, `actors[] {name, decision_rule rule_based|optimising|discretionary, reaction_template?, parameters?, why}`, `population_aggregates[]`, `period_length_recommendation`, `k_paths_recommendation`, `discretionary_count`. **Validation.** Discretionary count ≤ 8; every rule-based actor names a template; every term with sensitivity ≥ 4 that an actor can move has at least one actor assigned. **Fallback.** All actors with documented levers `discretionary` up to 8, the rest rule-based `hold`. **Model.** strong, T 0.1. **Budget.** 1 call. **Tests.** A commodity-price question with no pivotal actor yields `matters: false`; the specimen yields CISA, the Commission, two or three labs and one or two vendors as discretionary, insurers and buyers rule-based.

### C-02 Parameter binder — deterministic
Binds every mechanism parameter to a claim (typed quantity with matching unit and period) or a reference-class row; unbound parameters go to C-03.

### C-03 Prior elicitor — agent, per unbound parameter
**Context.** `CORE_prior` (ranges, not points; cite reasoning; label assumption) · CONTRACT · the parameter, template and units · claims and reference-class rows about the relation (≤ 2k). **Output.** `{low, high, mode?, unit, rationale, comparable_cases[]}` written as `assumed`. **Validation.** low < high within template bounds. **Fallback.** Template library range. **Model.** fast, T 0.3. **Budget.** ≤ 20 calls. **Tests.** Ranges inside bounds; rationale present.

### C-04 Predicate finaliser — deterministic (agent fallback)
Takes the contract's predicates, checks the partition against the target's compiled range, attaches indicator conjuncts to variables. If the contract has no predicates (legacy admission), one agent call proposes thresholds from the assessment's scenario theses, validated for partition.

### C-05 Observation model builder — deterministic
For each variable: visibility (public, owner-private, noisy-to-rivals), release lag and calendar from the data channel or the claim's publication cadence; for each actor: private signals it owns.

### C-06 Compile checks — deterministic
Dimensional consistency; identities on current values; hindcast of the last one or two vintages within stated ranges; baseline run (no decisions, no shocks) reproduces the trend path; gap list. Produces `compiled-world/v1` and the one-page review sheet.

### G1 Compiled-world review — human gate (optional; default on for the first ten runs)
Edits recorded as `assumed` with the reviewer as source and re-validated by C-06.

## Phase 4 — Simulation

### S-00 Plan seeder — agent, per discretionary actor, once
**Context.** `CORE_actor_decide` (you are this institution; decide as it would; typed outputs; no outside knowledge beyond the brief) · CONTRACT (period, horizon, calendar; **no predicates, no probabilities**) · brief rendered by the query contract with `actor_scope=self`: identity, objectives, constraints, levers with ranges and authority, beliefs seed (from dossier), intentions with credibility, relationships, calendar window, observable variables with current values (≤ 5k tokens). **Output.** `plan/v1`: `steps[] {lever, value, period, condition?}`, `triggers[] {predicate over observable variables/events, action}`, `beliefs[] {variable, forecast {p10, p50, p90} | proposition, confidence}`, `expectations[] {counterparty, expected_action, by_period}`, `public_statement?`. **Validation.** Levers exist and are within authority and range; triggers reference observable items only; beliefs reference known variables. **Repair.** One retry listing violations. **Fallback.** Plan = stated intentions as steps, no triggers, beliefs = current values. **Model.** strong, T 0.4, ≤ 1.5k out. **Budget.** 5–8 calls. **Tests.** An actor without authority over a lever cannot plan it; triggers parse.

### S-01 Observation renderer — deterministic
Per actor per period: visible variables (release lag applied), events, statements, offers, calendar window, expectation checks, episodic recall (top-k by relevance), as a typed observation with a digest hash.

### S-02 Belief updater — deterministic
Beliefs about variables move toward observed releases; beliefs about counterparties move with credibility-weighted signals; credibility recomputed from typed commitments versus realised lever settings.

### S-03 Trigger evaluator — deterministic
Fires triggers whose predicates hold; schedules actors due by cadence, by offers pending, by events aimed at them, or by fired triggers.

### S-04 Option enumerator and lookahead — deterministic
For each actor due: admissible options = lever settings on a grid within range, authority and capacity; responses to pending offers; signals; coalition acts; `revise_plan`; `hold`. For each option (≤ 8), the engine's k-period lookahead (k = 2 by default) on the actor's objective variables with other actors frozen on their plans and shocks at their expected value. Output: the option table.

### S-05 Decision agent — agent, per actor due
**Context.** `CORE_actor_decide` · CONTRACT (clock only) · the observation (≤ 3k) · identity summary (≤ 800) · plan and triggers fired (≤ 600) · option table with lookahead (≤ 1.5k) · pending offers with typed terms and the proposer's credibility (≤ 800) · expectation checks (≤ 300) · episodic recall (≤ 800). Total ≤ 8k tokens. **Opaque ids** for all actors by default (`SIM_OPAQUE_IDENTITIES=true`). **Output.** `decision/v1`: `actions[] {type lever_set|commit|offer|accept|counter|reject|withdraw|signal|coalition|hold, lever?, value?, period?, terms? {lever, value, due, condition}, counterparty?, signal? {kind announce|threaten|promise|deny|claim, proposition}}`, `plan_revision? {steps, triggers}`, `belief_updates[]`, `expectations[]`, `public_statement`, `private_rationale`, `confidence`. **Validation.** Every action admissible per S-04 or a `custom` with a typed lever and value; terms typed; statements bounded; language rule. **Repair.** One retry with violations. **Fallback.** Execute the plan's due step; else `hold`; status `fallback` recorded (I-16 analogue: never masquerades as a choice). **Model.** strong, T 0.4, ≤ 1.2k out. **Budget.** discretionary actors × decision occasions (triggers + cadence) × path-divergence factor; target ≤ 120 calls per run, enforced by a per-run cap after which plans execute without re-decision (recorded). **Tests.** Scripted-LLM scenarios: trigger fires → decision occasion; off-menu action rejected; fallback never counted as a choice.

### S-06 Feasibility judge — deterministic (agent only for `custom`)
Checks authority, capacity, consent state, timing; the character guard: violations of the actor's own declared constraints or red lines are returned once for reconsideration, then rejected; inferred-style contradictions are logged only. For `custom` actions one agent call (`CORE_judge`, fast, T 0) normalises to a typed lever edit or rejects with a reason.

### S-07 Mechanism engine — deterministic
Order per period: apply accepted lever settings (with lags into the delay queue) → settle due commitments and offers → fire scheduled events → draw shocks (S-09) → propagate identities, elasticities, reaction functions and thresholds → conserve resources → evaluate the target and predicates → detect red-line crossings and breaches → emit events with causes. No LLM.

### S-08 Effect estimator — agent, bounded
**Trigger.** Only when an accepted action touches a variable with no bound mechanism, or a shock's effect has `direction_only`. **Context.** `CORE_effect` (size conservatively; typed; cite the mechanism template; no narrative) · CONTRACT (clock) · the action or shock · the variable's unit, current value, recent path (≤ 300) · the parameter prior (≤ 200) · comparable past episodes from claims (≤ 800). **Output.** `effect/v1 {variable, delta | new_value | range, onset, duration, confidence, rationale ≤ 200 chars}`. Sampled twice at T 0.3; on disagreement beyond the prior's half-width the range is widened to cover both. **Validation.** Within the parameter prior's bounds × 2; never crosses zero unless the template allows. **Fallback.** Prior's mode. **Model.** fast, T 0.3. **Budget.** ≤ 40 calls per run. **Tests.** Disagreement widens; out-of-bounds clipped and logged.

### S-09 Shock sampler — deterministic (existing `fire_shocks`, extended to per-path streams and dated windows).

### S-10 Event and commitment settlement — deterministic (existing kernel rules with typed terms, grace period, symmetric breach).

### S-11 Discourse aggregate — deterministic (optional agent)
Public salience and sentiment scalars updated from counts of signals, events and red-line crossings; optionally one fast call per period summarising public statements into the two scalars (`SIM_DISCOURSE=rule|llm|off`). The OASIS feed is not in the loop; it MAY run as a narrative layer for the record (`SIM_NARRATIVE_FEED=off` default).

### S-12 Path manager — deterministic
K paths; per-path parameter draws from the assumed priors and per-path shock streams (`world_paths.path_rng`); decision reuse across paths when an actor's observation digest is identical, else re-elicitation (counted against the S-05 cap); turning points recorded where paths diverge.

### S-13 Record compiler and gate — existing (`simulation_record`, `simulation_record_gate`), extended with paths, conditionals and the strategic premium; sees the simulated layer only.

## Phase 5 — Estimation

### E-01 Reference-class forecaster — agent
**Context.** `CORE_forecaster_rc` (reason from reference classes and vintages; output a distribution over the predicates; list cruxes; no narrative) · CONTRACT (predicates) · base rates (≤ 1.5k) · vintages and revisions of the target (≤ 1k) · tree summary (≤ 1.5k) · third-party forecasts (≤ 800). **Output.** `estimator/v1 {source: reference_class, distribution[] {scenario, p}, binaries[] {id, p}, rationale, cruxes[]}`. **Validation.** Sums to 1; cruxes name propositions. **Model.** strong, T 0.3. **Budget.** 1 call.

### E-02 Trend forecaster — deterministic (persistence, drift of vintages, historical error bands). **E-03 Structural Monte Carlo** — deterministic (engine without actors, parameter and shock draws). **E-04 Strategic simulation** — deterministic read of Phase 4 outputs (predicate masses, conditionals, strategic premium). **E-05 Market-implied** — deterministic from exact-equivalence anchors.

### E-06 Adversarial forecaster — agent
**Context.** `CORE_forecaster_adv` (your job is the strongest case for each tail; name the path and the evidence that would make it visible early) · CONTRACT · the research posterior only (not other estimators) · pivotal claims and conflicts (≤ 4k) · hazards (≤ 600) · tree (≤ 1.5k). **Output.** `estimator/v1 {source: adversarial, distribution, tail_paths[] {scenario, path, enabling_assumptions, early_indicators}, cruxes[]}`. **Model.** strong, T 0.5. **Budget.** 1 call.

### E-07 Aggregator — deterministic
Pools estimators in weighted log-odds under `aggregation_policy_v1` pinned at admission (default: research posterior 1.0, all others 0 as shadow lanes; extremize 1.0; floor 0.03); writes `aggregation/v1` with every estimator's distribution, the pooled one, and a divergence table (per scenario, per estimator). I-21: weights change only through the outcome-blind promotion gate.

### E-08 Crux consolidator — agent
**Context.** `CORE_crux` · all estimators' cruxes and the assessment's cruxes (≤ 3k) · signposts from the simulation (≤ 1k). **Output.** `crux/v1[] {proposition, estimators_affected[], direction, evidence_that_settles, observable_by, signpost?}`, deduplicated and ranked by the pooled probability mass they could move. **Model.** fast, T 0.1. **Budget.** 1 call. Feeds key uncertainties, the watchlist, follow-up research and monitors.

## Phase 6 — Views and publication

### V-01 Card renderer — deterministic
`card/v1`: contract, pooled probabilities with every estimator and bands, update-ledger summary (prior → posterior), cruxes, signposts with dates, conditional tables from the simulation, input health, quality grade and disclosures.

### V-02 Evidence appendix, V-03 Model view, V-04 Simulation record view — deterministic renderings from the store.

### V-05 Narrative writer — agent, per section (derived from the tree's branches)
**Context.** `CORE_writer` (prose only; every number is a token `{{N:row_id}}` or `{{P:estimator:scenario}}`; every factual sentence carries `[S#]`; no simulation vocabulary outside the record view; language rule first) · CONTRACT · the section's typed evidence block: claims for its nodes with sids and dates, ranked by relevance (≤ 6k) · the estimator table as tokens (≤ 600) · the assessment's reasons for this section's nodes (≤ 800) · outline brief (≤ 400). No graph tools by default (`REPORT_WRITER_TOOLS=off`); optional typed retrieval returning claims with sids. **Output.** Markdown section with tokens and markers. **Validation.** Tokens resolve; every number is a token or inside a token; markers resolve; language purity. **Repair.** One critic pass (V-06) then one rewrite. **Fallback.** A deterministic section from the evidence block (bullet facts with markers). **Model.** strong, T 0.4, ≤ 3k out. **Budget.** 8–12 sections.

### V-06 Section critic — agent, fast
Checks token discipline, unsupported claims, repetition against neighbouring sections (now with their evidence blocks), contradiction with the card. Returns PASS or one instruction. T 0, ≤ 400 out.

### V-07 Integrity audit — deterministic
Hard failures only: a number not resolving to a row; a quote not verbatim; simulated vocabulary outside the record view; prose scenario mismatch; probability sum off. Epistemic shortfalls become `quality.grade` and disclosures (never a raise). Track-record freeze and journal registration as today.

### V-08 Translation — deterministic numbers and dates (rendered per language from rows), agent prose with the existing composed path; partial status restored.

### V-09 Publication — deterministic (seal, journal, exports).

## Phase 7 — Monitors, outcomes, memory

**M-01 Signpost and calendar monitor** (deterministic, scheduled): when a release lands or a signpost fires → **M-02 incremental re-research** (R-04 on the affected nodes, bounded) → **M-03 posterior update** (R-10 rerun with the delta logged) → card re-rendered with a diff. **M-04 Outcome resolver** (deterministic lanes: official data, exact-market, named-source event; manual lane with evidence and contract hash). **M-05 Scorer** (per estimator, per lane; Brier, log, calibration bins; promotion gate). **M-06 Behavioural registry updater** (deterministic comparison of typed lever settings; one fast agent call per named-source event to classify whether the documented action matches the simulated one). **M-07 Library updaters** (reference classes from resolved series; mechanism parameter ranges from hindcasts and outcomes; actor registry entries).

---

# Part IV — Kernel contracts

## IV.1 Action grammar (`action/v1`)
`lever_set {lever, value, effective_period}` · `commit {lever, value, due, condition}` · `offer {counterparty, terms {lever, value, due, condition}[], expires}` · `accept|counter|reject|withdraw {offer_id, terms?}` · `signal {kind announce|threaten|promise|deny|claim, proposition {variable|lever, value|direction}, audience public|counterparty}` · `coalition {propose|join|leave, members, joint_terms, enforcement}` · `hold`. Every action carries `actor, period, path, status accepted|rejected|flagged, reason`.

## IV.2 Mechanism forms (`mechanism/v1.template`)
`identity` (expression over inputs) · `elasticity` (Δy = β·Δx with onset, completion, decay) · `reaction` (y = f(x) rule with thresholds and cadence) · `delay` (queue with lag) · `threshold` (state switch) · `hazard` (per-period rate over a window, effects) · `adoption` (logistic with ceiling). Parameters carry priors with bases; per-path draws are fixed for the path.

## IV.3 Engine order (per period, per path)
S-01 → S-02 → S-03 → S-04 → S-05/S-06 → S-07 (levers → settlements → scheduled → shocks → propagate → conserve → target and predicates → red lines and breaches → events) → S-08 only for unmodelled edges → S-11 → S-12 bookkeeping → record. Deterministic steps are pure functions of (state, decisions, RNG stream) and are replayed byte-for-byte in the replay harness.

## IV.4 Observation model
Per variable: `visibility public|owner|noisy`, `release_lag_periods`, `release_calendar`; per actor: private signals. `visible(record, actor, t)` as in II.4.

## IV.5 Paths
`SIM_WORLD_PATHS=K` (default 4 when strategic interaction matters, 1 otherwise); per-path parameter draws and shock streams; decision reuse by observation digest; turning points; outputs per path and aggregated.

## IV.6 Replay and determinism
All agent outputs persisted with input hashes (II.2); `replay --from agent_io` reproduces a run without the provider; changed kernel settings replay saved decisions (open-loop sensitivity); RNG streams keyed by (seed, path, period).

---

# Part V — Estimation and aggregation (summary of contracts)

`estimator/v1` is the single shape for E-01…E-06; `aggregation/v1` records policy, inputs, pooled output and divergence; the journal stores all estimators so `forward-score` scores each lane; the simulation's conditionals and tails are published regardless of weight; promotion of any weight follows the outcome-blind gate (frozen policy at T, shadow-applied, promoted only on a prospective paired lift with a CI excluding zero and n ≥ 30 in the lane).

---

# Part VI — Views and publication (summary)

Five layers (card, evidence, model, record, narrative) rendered from the store; tokens for every number; `quality.grade` and disclosures; hard failures for integrity only; the simulation visible only in the record view and the card's conditional table, under its banner; input health on the card; the exec brief rendered from the card.

---

# Part VII — Monitors, outcomes, memory (summary)

Monitor on at 24 h; lanes: official data, exact market, named-source event, manual; incremental updates with logged deltas; per-estimator scoring; three libraries (reference classes, mechanisms, actors) written only from resolved records; the forward cohort as the prospective evaluation track.

---

# Part VIII — Cross-cutting

- **Provenance.** Every row cites claim ids or a step id; every claim has a source, date and passage; classes are explicit everywhere; the information cutoff is enforced at the store (no observed record dated after as-of in a backtest).
- **Caching layout.** `[CORE_<family>][CONTRACT][SNAPSHOT_<phase>][TASK]` for every agent family; CORE and CONTRACT identical across a run; SNAPSHOT identical within a phase; provider-side prompt caching enabled where supported; the in-process LRU remains for exact repeats.
- **Telemetry.** Every agent step meters calls, tokens, cached tokens, latency and cost under `(phase, step_id)`; research and simulation child usage folded into the pipeline's `by_stage`; attribution preserved across resumes; budgets per phase in the RunSpec; the run halts gracefully at budget with a typed reason.
- **Concurrency.** KIQ agents and decision agents fan out under the shared provider lease; graph projection is single-threaded and fast; the engine is pure and parallel across paths.
- **Failure handling.** Every agent step has a deterministic fallback that is recorded as such (never counted as a judgement); content-filter refusals route to the fallback provider when configured and otherwise to the deterministic fallback; the run never fails on an epistemic shortfall.
- **Prompt security.** All data blocks are wrapped as untrusted; instructions inside data are ignored by contract (existing ENGINE_CORE rule, applied to every family).
- **Opaque identities.** Decision, judge and effect prompts use opaque ids by default; a per-run map renders names in records and views.

---

# Part IX — Implementation plan

Each slice: scope → acceptance → rollback flag → estimate. Flags default to today's behaviour until the slice's acceptance passes, then flip. Phase A reproduces the earlier "first ten" hotfixes; later phases build the hub.

## Phase A — Stop losing work; start the loop (2 weeks, parallel worktrees)
- **A1** Publication gates degrade (`REPORT_PUBLISH_GATE_MODE=grade|fail`). Acceptance: low-spread set publishes at grade C; integrity still fails. 2–3 d.
- **A2** Research prior reaches the spine with an update table (`REPORT_SPINE_RESEARCH_PRIOR`); simulated shares start uniform (`SIM_SHARE_PRIOR`). 1–2 d.
- **A3** Arbiter repair-by-field, private expectations out, raw responses persisted, deliveries beside moves, capacity binds, terms-based due dates with grace, symmetric breach, decision prompt without the OASIS template, budgets module (`SIM_WORLD_ARBITER_REPAIR`). 3–4 d.
- **A4** Markets probe and cache, `inputs_health`, monitor on at 24 h, near-anchor lane, named-source-event lane and manual API, dead ledger reader removed, `forward_cohort.py propose --dry-run` (`RESOLUTION_MONITOR_AUTORUN_HOURS`, `FORECAST_MARKET_NEAR_RESOLUTION`, `PREDICTION_MARKETS_CACHE`). 3–5 d.
- **A5** Telemetry: research and simulation usage folded into `by_stage`, report phase meters, attribution across resumes. 2 d.

## Phase B — The store and the contract (2 weeks)
- **B1** `world_model.sqlite` + schemas + sealed exports + `agent_io` persistence + the query contract as SQL views; `forecast_task_v1` kept as a projection. Acceptance: round-trip of every schema; byte-stable exports; replay of a saved agent call. 5–7 d.
- **B2** A-00/A-01/A-02 contract steps and G0 (`ADMISSION_CONTRACT=v1|legacy`). Acceptance: specimen and yield questions produce correct targets and settlements; predicates partition. 3–4 d.
- **B3** R-00 channel prefetch with health (`CHANNELS_ASYNC`). 2 d.

## Phase C — Research as a producer of typed records (3–4 weeks)
- **C1** R-02 tree builder + R-03 planner revision (`RESEARCH_V3_TREE`). Acceptance: specimen tree with ≥ 4 terms and statuses; KIQs carry node ids; adversarial and settlement KIQs present. 5 d.
- **C2** R-04 typed notes sections + R-13 projection into observed records (claims with passages and dates; calendar; intentions; forecasts by others; indicators; base rates; hazards) (`RESEARCH_TYPED_NOTES`). Acceptance: every typed line round-trips; `sources.json` excerpts are the cited passages; finalize makes no re-extraction calls. 5–6 d.
- **C3** R-05 claim verifier (bounded) + R-06 conflict detector + origin independence + dates at fetch (`RESEARCH_CLAIM_VERIFY`). Acceptance: the four mismatch fixtures; `independent` and dates populated. 4–5 d.
- **C4** R-07 gap reviewer revision with tree and stop reasons. 2 d.
- **C5** R-08 actor intelligence extractor (`RESEARCH_ACTOR_DOSSIERS=v1|legacy`). Acceptance: CISA fixture; every item cites a claim and carries a class. 4 d.
- **C6** R-09 mechanism elicitor + template library v1 (identity, elasticity, reaction, delay, threshold, hazard, adoption) (`RESEARCH_MECHANISMS`). Acceptance: every parameter has a basis; gaps are wide priors. 5 d.
- **C7** R-10 assessment prior → posterior enforced by QA (`RESEARCH_POSTERIOR=shadow|live`). Acceptance: duplicate/decisive/definition-change fixtures. 3 d.

## Phase D — Ontology and graph as projection (2 weeks)
- **D1** Upper ontology v1 + O-01 domain instantiation (`ONTOLOGY_MODE=upper|legacy`). Acceptance: specimen subtypes; no sentence edge types. 3–4 d.
- **D2** G-01 projection builder + layered graph + typed retrieval returning claims with sids and dates; `GRAPH_MODE=projection|extract|extract_uncovered`. Acceptance: zero-LLM rebuild of the specimen in under a minute; every retrieved fact carries `[S#]`; GraphPanel loads. 5–6 d.
- **D3** Lever-based salience replaces centrality priors in cast selection. 2 d.

## Phase E — Compile (2 weeks)
- **E1** C-01 adequacy assessor + decision-rule assignment + reaction-function templates for rule-based actors and population aggregates (`SIM_COMPILE=v1|legacy`). 4 d.
- **E2** C-02/C-03 parameter binding and prior elicitation; C-04 predicates; C-05 observation model; C-06 checks (hindcast, baseline); the review sheet and G1. 5–6 d.

## Phase F — The simulation (5–7 weeks)
- **F1** Mechanism engine (S-07) with the delay queue, conservation, derived target and predicate evaluation; arbiter writes to derived variables rejected; `SIM_WORLD_MECHANISMS`. Acceptance: an `impose_measure` of magnitude m moves its bound variable after `lag` with the arbiter off; replaying the specimen's decisions moves the target; baseline reproduces trend. 7–9 d.
- **F2** Shares from predicates; votes retired (`SIM_SHARE_SOURCE=predicates|power_votes|votes`). Acceptance: votes X, target Y → shares follow Y. 2 d.
- **F3** Typed action grammar, typed offer terms, consent, commitments, credibility as a weight, red lines as predicates; feasibility judge and character guard (S-06). 6–8 d.
- **F4** Observation renderer, belief updater, trigger evaluator, option enumerator with lookahead (S-01…S-04). 6–8 d.
- **F5** Plan seeder and decision agent (S-00, S-05) with opaque identities; per-run decision cap; fallbacks (`SIM_DECISION_MODE=plans|moves`, `SIM_OPAQUE_IDENTITIES`). Acceptance: decision calls fall 5–10× on the specimen; `fulfill` share < 10%; off-menu rejected; fallback never counted. 6–8 d.
- **F6** Effect estimator (S-08) with double sampling; discourse aggregate (S-11); OASIS feed out of the loop (`SIM_DISCOURSE`, `SIM_NARRATIVE_FEED`). 4 d.
- **F7** Closed-loop paths with per-path draws and decision reuse (S-12); replay harness; conditionals and strategic premium into the record (S-13). 5–6 d.
- **F8** Lever-based cast selection with class bases; `cast_underspecified` handling (`SIM_CAST_SELECTION`). 3 d.

## Phase G — Estimation and views (3 weeks)
- **G1** `estimator/v1`, E-02/E-03/E-05 deterministic forecasters, E-07 aggregator with pinned policy, journal lanes (`REPORT_TOURNAMENT`). Acceptance: default policy byte-identical to the spine; RW-11 extended. 5 d.
- **G2** E-01/E-06 agent forecasters and E-08 crux consolidator. 3 d.
- **G3** Binaries from tree nodes with contracts (`FORECAST_BINARIES_SOURCE=tree|prose`). 3–4 d.
- **G4** Views: card, evidence, model, record; narrative writer with tokens (V-05) and critic (V-06); integrity audit (V-07); writer tools off by default (`REPORT_WRITER=views|legacy`). Acceptance: numbers byte-identical to rows; no epistemic failures; simulated vocabulary only in the record view. 6–8 d.
- **G5** Translation numbers from rows; partial status. 2 d.

## Phase H — Loop and evaluation (ongoing, 2 weeks to stand up)
- **H1** Monitors M-01…M-03 (incremental updates with logged deltas). 4 d.
- **H2** Scorers per estimator; promotion gate; forward cohort start (paid, approval). 3 d.
- **H3** Libraries M-07 and the behavioural registry M-06. 4 d.
- **H4** Hindcast harness (two episodes) and placebo arms (frozen brief, shuffled roles, named vs opaque). 5 d.

## Dependency graph
```
A1..A5 (independent) ─┐
B1 ─► B2 ─► C1 ─► C2 ─► C3 ─► C7
      │          └─► C5 ─► C6 ─► E1 ─► E2 ─► F1 ─► F2
      │                               └─► F3 ─► F4 ─► F5 ─► F6 ─► F7
      └─► D1 ─► D2 ─► D3 ─► F8
C7 + F2 ─► G1 ─► G2 ; C1 ─► G3 ; G1 + F7 ─► G4 ─► G5
A4 + G1 ─► H1 ─► H2 ; F7 ─► H4 ; H2 ─► H3
```
Calendar: A in weeks 1–2; B weeks 2–4; C weeks 4–8; D weeks 6–8 (parallel with C); E weeks 8–10; F weeks 10–17; G weeks 14–17 (overlapping F); H weeks 17–19 and ongoing. Roughly four to five months of focused work with parallel worktrees, each slice independently mergeable behind its flag.

## Cost after the overhaul (per standard run, estimated)
Research 80–120 agent calls (~1.5M tokens, mostly cached prefixes); actor intelligence 8–20; mechanisms 6–20; compile 1 + ≤ 20 priors; simulation ≤ 8 plans + ≤ 120 decisions + ≤ 40 effects + record (~0.6–0.8M); estimation 3–4 agent calls; views 10–14 writer calls + critics (~0.3M). Total ≈ 2.5–3M tokens against today's 8–15M (graph 5–12M, simulation 3.3M, report 0.3M, research unrecorded), with the graph stage at zero LLM calls by default.

---

# Part X — Evaluation plan

- **Unit and contract tests** per step (schema round-trips, validation, repair, fallback, byte-identity under the old flag value).
- **Scenario tests with scripted models** for the loop: trigger → decision → judge → engine → event → observation; information-set leakage negatives (an actor never sees inferred claims about itself or any forecast record); opaque-id rendering.
- **Replay** of saved runs through the engine under changed settings (open-loop sensitivity) and of saved agent calls (no provider).
- **Hindcasts** on two documented episodes for mechanisms and actor rules (debugging, never pooled with prospective scores).
- **Placebo arms** (frozen brief, shuffled roles, named vs opaque) with L1 distance of decision-kind distributions against seed-to-seed variance.
- **Prospective cohort** scored per estimator and lane; promotion only through the outcome-blind gate.
- **Ablations by forks**: research-only, structural-only, strategic, markets, with equal total budget.

---

# Part XI — Risks

| Risk | Mitigation |
|---|---|
| Mechanism compilation produces assumptions, not models | template library; binding to typed quantities; wide priors with gaps listed; the human review gate; observable-milestone domains first |
| LLM actors stay unrealistic | rule-based classes for predictable actors; lookahead; character guard; opaque ids; hindcasts; behavioural registry |
| Schema sprawl | one upper ontology, one estimator shape, one action grammar; schemas versioned and exported; round-trip tests |
| Performance of the store | SQLite WAL with views; exports for sealing; the engine is pure Python over small state |
| Parallel-branch drift | each slice merges `main` before its suite; merge order in the handoff; compare-and-swap |
| Cost overruns in simulation | per-run decision cap; triggers; decision reuse across paths; rule-based actors |
| Owner's uncommitted translation work | translation slice aligns with the working tree's path rather than around it |
| Measurement lag | hindcasts and placebo arms in weeks; the forward cohort as the only source of weight changes |

---

# Part XII — Owner decisions

| ID | Decision | Recommendation |
|---|---|---|
| O-1 | Approve the hub architecture (store + record classes + query contract) as the target | Yes |
| O-2 | SQLite store per run with sealed JSONL exports | Yes |
| O-3 | Upper ontology replaces per-run invented types | Yes |
| O-4 | Graph default `projection` once D2 passes | Yes |
| O-5 | OASIS feed out of the decision loop; optional narrative layer | Yes |
| O-6 | Opaque identities default in decision and adjudication prompts | Yes, with the named placebo arm |
| O-7 | Human gates G0 and G1 on for the first ten runs | Yes |
| O-8 | Decision call cap per run (120) | Yes |
| O-9 | Phase A hotfix decisions (grade gate, uniform share prior, monitor on, probe) | As in the earlier PLANS §11 |
| O-10 | Paid runs: one per phase C/F/G for confirmation; the forward cohort | Separate approvals |

---

# Appendix A — Schemas (field lists)

- **forecast-contract/v1** `targets[], horizon{as_of, horizon_date, period_length, basis}, scenarios[]{name, predicate}, binaries_seed[], key_entities[], contract_hash, reviewed`.
- **resolution-tree/v1** `target_id, nodes[]{id, label, kind, parent, relation, expression, unit, current{value, vintage, sid}, status, sensitivity, actors[], indicators[], settlement_hint}, validation{identity_residuals[], gaps[]}`.
- **claim/v1** `id, text, entity, metric, period, unit, value, sids[], passage{sid, start, end, text}, date_observed, date_published, tags{citation_resolves, numbers_on_page, passage_supports}, record_class, origin_cluster, node_ids[]`.
- **calendar-event/v1** `date, event, actor?, source sid, certainty scheduled|expected`.
- **intention/v1** `actor, statement, date, due?, lever_hint, source sid, credibility_basis`.
- **third-party-forecast/v1** `author, target_id, value|distribution, vintage, horizon, source sid`.
- **indicator/v1** `name, node_id, latest{value, date}, cadence, source`.
- **base-rate/v1** `reference_class, outcome_frequency, n, window, basis sids[]`.
- **hazard/v1** `event, probability, window{start, end, text}, source sid, effects[]{variable, change|direction}, recurring`.
- **actor-dossier/v1** as in R-08.
- **mechanism/v1** as in R-09.
- **assessment/v1** as in R-10.
- **domain-ontology/v1** as in O-01.
- **compiled-world/v1** `variables[], actors[]{dossier_ref, decision_rule, reaction?, levers[]}, mechanisms[], calendar[], hazards[], predicates[], observation_model, parameters_draw_spec, gaps[], checks{dimensional, identities, hindcast, baseline}`.
- **plan/v1**, **decision/v1**, **action/v1**, **effect/v1** as in Phase 4.
- **event/v1** `period, path, kind scheduled|action|consequence|emergent|shock|red_line|breach, actors[], effects[], cause`.
- **path/v1** `k, parameter_draws, shock_realisations, states_by_period, target_by_period, predicate_mass_by_period, turning_points[]`.
- **estimator/v1**, **aggregation/v1**, **crux/v1** as in Phase 5.
- **signpost/v1** `indicator, condition, expected_by, scenarios_affected[], source`.
- **card/v1** as in V-01.
- **outcome/v1** `target_id|binary_id, lane, value, resolved_at, evidence, adjudication`.
- **registry-entry/v1** `actor, lever, simulated_setting, realised_setting, period, match, source`.

# Appendix B — Flags introduced

`ADMISSION_CONTRACT`, `CHANNELS_ASYNC`, `RESEARCH_V3_TREE`, `RESEARCH_TYPED_NOTES`, `RESEARCH_CLAIM_VERIFY`, `RESEARCH_ACTOR_DOSSIERS`, `RESEARCH_MECHANISMS`, `RESEARCH_POSTERIOR`, `ONTOLOGY_MODE`, `GRAPH_MODE`, `SIM_COMPILE`, `SIM_WORLD_MECHANISMS`, `SIM_SHARE_SOURCE`, `SIM_DECISION_MODE`, `SIM_OPAQUE_IDENTITIES`, `SIM_DISCOURSE`, `SIM_NARRATIVE_FEED`, `SIM_CAST_SELECTION`, `SIM_WORLD_PATHS`, `REPORT_TOURNAMENT`, `FORECAST_BINARIES_SOURCE`, `REPORT_WRITER`, `REPORT_PUBLISH_GATE_MODE`, `REPORT_SPINE_RESEARCH_PRIOR`, `SIM_SHARE_PRIOR`, `SIM_WORLD_ARBITER_REPAIR`, `RESOLUTION_MONITOR_AUTORUN_HOURS`, `FORECAST_MARKET_NEAR_RESOLUTION`, `PREDICTION_MARKETS_CACHE`. Each documented in `.env.example` and the drift check; each with a byte-identity test for its legacy value.
