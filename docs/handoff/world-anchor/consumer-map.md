# World Anchor consumer map — static inspection

Inspected2026-10-29; source-only, no runtime/test verdict. Locations refer to the current worktree and are not frozen forever.

| Boundary | Current source | Required new wiring |
|---|---|---|
| Flat variable extraction | world_model_seed.py:349 | Replace metric-slug-only identity with scoped entity/metric/period anchor IDs. |
| Seed typed target | world_model_seed.py:1058,1128 | Optional forecast_case already works; normal config caller at simulation_config_generator.py:2224 does not pass it. |
| Seed fallback | simulation_config_generator.py:796 | Anchor enabled must not be swallowed by broad catch-and-continue/None behavior. |
| Runtime persistence | world_model.py:670,1140 | Explicit variable/anchor metadata load, save, reload and projection fields. Extra seed keys are ignored today. |
| Real target propagation | world_model.py:1255; run_parallel_simulation.py:4643 | Admitted mechanism DAG and primitive state, preserved parameter draws, derived-write refusal. |
| Actual actor input | run_parallel_simulation.py:4419,4489; agent_decision.py:1004 | Filter every authorized channel before elicit_decision, including role evidence. |
| Existing C5 class authority | simulation_manager.py:1033; agency_classification.py:47,160; simulation_config_generator.py:684; world_model_seed.py:1183 | Reuse validated UUID mapping and sealed ontology basis. Unresolved basis differs from omitted map. |
| Strict I-30 gap | simulation_config_generator.py:3830,3948; test_context_audit_simulation.py:234 | Existing labeled self-inference is retained in actor user data. New anchor-v1 projection must exclude it, including indirect summaries; off mode preserves current contract. |
| Seed relationships/privacy | world_model_seed.py:139,1249 | Do not assume config's stricter canonical public projection has authenticated every raw seed pack/relationship. |
| Target-first run | target_pipeline.py:491,525; target_simulation.py:530 | RUN consumes the admitted case, not arbitrary target_input extensions. Bind before case seal. |
| Target visibility | target_actors.py:98; target_mechanisms.py:261; target_simulation.py:263 | Preserve actor ownership/release lag, no latent fallback, simultaneous observations before actions. |
| Calendar and hazards | simulation_config_generator.py:1119; world_model.py:1481,2552; world_update.py:74 | Event announcement is not a numeric effect; hazard direction alone cannot size a transition. |
| Indicators | world_model_seed.py:1091 | Current seed-only scenario_indicators have no runtime load consumer; add explicit observation/trigger/signpost path. |
| After-action record | simulation_record.py:394,667,825 | Explicit setup/period projection; provenance and private dossier fields must not leak or disappear. |
| Report fence | target_report.py:182; report_agent.py:3365,3539; ADR0003:103 | Redacted diagnostic provenance, simulationWeight0, RW-11 preserved. |
| Manifest/reuse | simulation_manager.py:60; target_pipeline.py:67 | Add exact anchor/join/generation artifacts to current seal and reuse checks. |

Requirements WA06/07/11/12/14 in PLANS.md test these boundaries. Merely emitting world_anchor.json is not feature acceptance.

## Compiled world-v1 is a separate consumer

The first consumer trace covered the OASIS reflexive coordinator and target-first runtime; it did not establish compiled world-v1 support. The follow-up confirms `_run_world_stages` at pipeline_orchestrator.py:8754 (dispatched after graph at14489) → prepare_world_simulation → WorldSimulationService.prepare_model at world_simulation/service.py:107 → compile_world_spec at world_simulation/compiler.py:657 → seal_inputs/world_input_manifest. Existing provenance admission at compiler.py:354 accepts source_claim, report_excerpt and scenario_assumption; it has no anchor-reference kind. Numeric qualifiers and field/target bindings must not be forged as actor claims. A bounded typed adapter/provenance extension can feed existing initialState/actionCatalog/scheduledEvents/flows and compiler-owned sourceBindings. Unsupported mechanisms retain modeling_gap rather than requiring a kernel rewrite. WA16 covers this separate path.
