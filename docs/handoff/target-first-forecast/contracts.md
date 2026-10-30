# Frozen implementation interfaces (v1)

This is the coordination contract for disjoint owners. Proposed changes must be reported to the coordinator before consumers diverge. External keys are lowerCamelCase; functions are snake_case. All modules must be safe at import and perform no provider or filesystem work until explicitly called.

## Case wire shape: forecast-case/v1

`schemaVersion="forecast-case/v1"`, `caseId`, `question`, `asOf` (ISO date), `revision` (positive int), `authority="target-first-v1"`.

`resolution`: {`targetNodeId`, `horizon` (ISO date), `settlementSource`: {`name`, `url`, `releaseLagDays`}, `units`, `comparatorPolicy` (text)}.

`nodes`: [{`nodeId`, `label`, `units`, `status`: settled|contested|unknown, `value`: finite number or null, `range`: {`low`,`high`}, `vintage`: date or null, `sourceIds`: list of string S# IDs, `claimIds`: list, `sensitivity`: nonnegative number, `evidenceAvailability`: 0..1, `retrievalCost`: positive number, `pivotal`: bool, `visibility`: public|private, `ownerActorId`: optional}]. Every used numeric node needs a value or a finite bounded range; unknowns have explicit parameter bases and no invented evidence. All targets/mechanism refs resolve. Range low<=high; source-grounded settled nodes have date and valid source references.

`sources`: [{`sourceId`, `url`, `title`, `publishedAt`: nullable ISO, `retrievedAt`: ISO, `originCluster`, `tier`: primary|secondary|social|unknown, `fetched`: bool, `passage`: string}]. Missing publication dates remain explicit unknowns; retrieval dates are never substituted. `claims`: [{`claimId`, `nodeId`, `sourceIds`, `passage`, `status`: verified|reported|contested|unknown}]. Verified pivotal claims require fetched primary evidence, never sole social origins.

`mechanisms`: [{`mechanismId`, `kind`, `outputNodeId`, `inputNodeIds`, `parameters`: object, `basis`: observed|estimated|assumed, `sourceIds`, `gap`: text when assumed}]. Supported template kinds and parameter keys are frozen by the mechanism owner and documented here. Start with growth (base * (1+rate)), sum, product, linear, supply_demand, adoption, regulatory_milestone. No arbitrary expression evaluation. Topological deterministic propagation; reject cycles and duplicate output writers.

`actors`: [{`actorId`,`name`,`decisionBasis`,`objectives`: [{`nodeId`,`direction`: increase|decrease,`weight`}],`constraints`: {`capacity`: finite nonnegative},`levers`: [{`leverId`,`nodeId`,`minimum`,`maximum`,`cost`,`lagPeriods`,`reversible`,`requiresConsent`: [actor IDs]}],`decisionRule`: {`kind`: rule|llm,`cadencePeriods`: positive int,`triggers`: [predicates]},`plans`: [{`planId`,`leverId`,`value`,`duePeriod`,`condition`: optional predicate}],`information`: {`nodeIds`: list,`releaseLagPeriods`: nonnegative int},`credibility`: 0..1}]. Cast membership derives from at least one documented lever; actor briefs exclude others' private nodes and all assessment/scenario probabilities.

`scenarios`: [{`scenarioId`,`label`,`predicate`: {`nodeId`,`operator`: lt|lte|gt|gte|between, `value`: number, or `low`,`high`}}]. Scenario shares are frequencies of terminal outcome regions only. Overlap rejected, unmatched mass is explicit other; no implicit renormalization or votes.

`assessments`: [{`assessmentId`,`version`, `kind`: prior|posterior, `scenarioWeights`: {scenario ID: probability 0..1}, `targetDistribution`: optional object, `updates`: [{`evidenceId`,`nodeId`,`direction`,`size`,`oldWeight`,`newWeight`,`scenarioId`,`reason`}]}]. Existing assessments are immutable. New definition set => case revision/version. Simulation projection excludes assessments, prose, scenario labels and probability weights; scenario predicates are used by the reducer output classifier, never actors.

`binaries`: [{`binaryId`,`question`,`predicate`,`probability`: 0..1,`sourceIds`}]. Binaries are explicit predicates, not prose extraction.

## Shared Python APIs

Core: `deerflow_bridge/forecast_case.py` owns `CaseValidationError(ValueError)`, `validate_case(case)->dict` (returns deep-copy normalized JSON, raises), `case_hash(case)->str`, `simulation_projection(case)->dict`, `report_projection(case)->dict`, `graph_projection(case)->dict`, `write_case(path, case)->str` (atomic, returns hash), `read_case(path, expected_hash=None)->dict`. Pure helpers; don't import the app.

Mechanisms: `backend/app/services/target_simulation.py` owns `run_paths(case, *, paths=32, periods=12, seed=0, decision_provider=None)->dict`, `actor_observation(case, state, actor_id, *, period=0)->dict`. Return {`schemaVersion`: target-simulation/v1, `caseId`, `caseHash`, `seed`, `paths`: [{`pathId`,`parameters`,`trajectory`: [{`period`,`values`}],`decisions`, `targetValue`}], `scenarioShares`, `targetSummary`, `sensitivity`, `signposts`, `simulationWeight`: 0.0}. Unknown edges are bounded assumptions, sampled once per path, and clearly labelled. Decision provider receives public/actor-visible structured observation only; callbacks return typed lever actions with `actorId`,`leverId`,`value`, optional `consents`. Baseline path does not invoke LLM. Mechanism module records template semantics and tests.

Research: `deerflow_bridge/target_research.py` exposes `build_case(plan, evidence, sources, *, question, as_of)->dict`, `research_priorities(case)->list`, `render_case_research(case)->str`. The plan supplies a `forecastCase` matching the wire shape. Research must obtain it after planning via existing budgeted gateway calls; never fabricate a target from generic numeric rows. New mode admission is `args.forecast_authority == "target-first-v1"`; backend passes `--forecast-authority target-first-v1`. Legacy mode remains default. Final case is persisted at `handoff/forecast_case.json` before completion and included in reuse identity. Author owns CLI propagation in deerflow_bridge/deerflow_research.py and child sync list in scripts if needed, coordinating with local orchestrator owner.

Report: `backend/app/services/target_report.py` owns `build_target_report(case, simulation=None)->dict` returning {`forecast`, `markdown`, `record`}. `forecast` uses existing forecast.json public shape but typed research assessment/binary rows are exact numeric authority. Simulation is fenced diagnostic data with zero weight. Report owner integrates optional constructor `forecast_case` and `target_simulation` inputs into ReportAgent so direct/manual consumers can preserve the same rule. New report path never calls the probability LLM/extractor. `register_comparison(path, case, simulation, *, enrolled_at)->dict` persists an immutable preregistration bound to case and policy before horizon/outcome; no runtime switch may grant nonzero weight.

Coordinator owns pipeline/API admission and orchestration, stage persistence, graph/preparation integration, acceptance fixture flow, README/handoff/delivery. Other owners must not edit these without coordination.

## Safety and migration

Authority is explicit and pinned. A declared typed mode with missing/invalid case fails visibly; it must not fall back to LLM-authored probabilities. Old modes do not silently adopt typed authority. Do not mutate historical runs. Prospective statistical lift and production provider realism are separate gates. User-facing documentation must say which has been executed.


## Final integration additions (2026-10-28)

- The core case admits optional `resolution_contract`/`scenario_membership` on binaries and `resolution_contract` on nodes as explicit legacy-adapter field names. Contract validation and stored-snapshot admission belong to the existing binary validators. A driver never inherits an unrelated target settlement source.
- Required research artifacts include `target_library.json`, `target_library_publication.json`, `target_evidence.json` and `target_estimators.json`. The pipeline pins their digests in saved options before downstream work. Source-aware mechanism templates are published only after case admission and remain inherited assumptions/estimates.
- `target_evidence` is `{schemaVersion:'target-evidence/v1',caseHash,official_data,markets,news_market_context}`. `markets` retains the native envelope, including status/cache/time metadata. Anchor consumers normalize its `markets` rows; estimator/health consumers retain envelope-level health. Frozen replay never refreshes these sources.
- `saved_estimators` is `{schema_version:'target-estimators/v1',case_id,case_hash,policy_hash,estimators}`. It contains the exact research authority and no simulation lane. `freeze_target_estimators` runs at most three upstream gateway calls; report replay validates the envelope and appends only current zero-weight simulation diagnostics. Ambient tournament flags cannot remove already admitted lanes.
- ReportAgent accepts optional `aggregation_policy`, `saved_estimators` and `target_evidence`; its target branch creates no provider client. Manual generation consumes the same sealed inputs and validates the decision budget.
- `target_input` also carries `decisionBudget:{max_calls}`. Runtime diagnostics may carry `decisionBudget:{maximumRequests,requests,cacheHits,exhausted}`, dimensional/seed checks, lookahead/opaque-identity metadata, paired intervention/conditioning tables and supplied-snapshot hindcast validation. These never author unconditional forecast probabilities.
- The mechanism compiler's scalar names are authoritative, including `coefficient:<nodeId>`. Report validation uses the compiler's exact keys/bounds rather than treating those valid names as unknown variables.
- Target forks admit verified parent research/ontology/graph receipts, pin exact input hashes, and install a private snapshot at the child's canonical `handoff/` path. Parent tampering before or after admission fails closed. Fork publications are characterization/evaluation records and do not create new prospective primary enrollments.
- Provider readiness applies before new LLM actor execution. A valid completed simulation can be reused for report-only regeneration without reopening a provider.
