# Estimator and typed-binary owner handoff

Last updated: 2026-10-27. Status: in progress.

## Request and boundaries
Implement the approved part 2 A1/A2/F6/F7 in forecast_aggregator.py, forecast_tournament.py, forecast_extractor.py, actors.py and uniquely named tests. Other owners' files, commits, pushes, provider calls and service restarts are outside this worker's scope. The coordinator owns config and admission policy pinning; Turing owns report publication and integration.

## Acceptance and plan
1. Validate a versioned estimator and pinned policy. Default authority weight is one; every shadow weight is zero. Compare serialized scenario and binary rows before/after shadow changes. Reject simulation promotion. Exercise explicit log-odds policy math separately.
2. Produce bounded method-diverse diagnostics through an injected gateway, exact-market anchors and structural results. Missing inputs produce an explicit unavailable lane, never fabricated probabilities. The report owner calls the production API.
3. Render the research prior only under its flag; validate the typed prior/posterior update ledger against final published probabilities. Verify rollback prompts and retained priors.
4. Derive binaries from typed predicates and declared memberships with settlement contracts; no quotas or invented probabilities. Preserve the prose path. In grade mode expose sharpness issues without failing publication.
5. Run focused scenarios using the existing guarded offline runner, then request coordinator review/integration verification.

## Interface proposal sent to coordinator
- `default_aggregation_policy(authority="spine")` and `pin_aggregation_policy(policy=None, *, authority="spine")`.
- `run_forecast_tournament(forecast, *, case=None, simulation=None, llm=None, policy=None, enabled=None, markets=None)` returns a new forecast with estimators and aggregation metadata.
- `derive_binaries_from_tree(case, *, scenarios=None)` returns binary_forecasts and binary_quality.
- `derive_forecast_spine(..., research_prior=None)` accepts `{scenarioWeights: {name: p}, asOf: date}`.
- Flags requested: REPORT_TOURNAMENT, REPORT_SPINE_RESEARCH_PRIOR, REPORT_PUBLISH_GATE_MODE and FORECAST_BINARIES_SOURCE. Safe getattr defaults are used.

## Findings and risks
The supplied case currently contains explicit binary probabilities and predicates. Its settlement target is authoritative; a driver binary cannot inherit target settlement semantics. Method outputs are not proof of independent errors or forecast skill. Simulation remains diagnostic under every supported policy.

## Verification and remaining work
No implementation verification has run yet. Tests must exercise actual extractor/tournament entrypoints and the report owner's consumer. Run with a new /private/tmp evidence directory on every attempt.

## Updates
- 2026-10-27: Read approved contracts and current producers/consumers, recorded ownership and sent interfaces to the coordinator before implementation.
