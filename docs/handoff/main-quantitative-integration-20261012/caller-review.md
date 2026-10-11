# Official-data caller review

Status: Review complete on 2026-10-12; three actionable findings remain open for the coordinator.

## Scope and constraints
The user requested review of `_run_one_seed`, the main REPORT constructor, `load_research_dossier_for_simulation`, manual report generate/chat, graph historical snapshots and SimulationWorldBrief. Acceptance is correct handoff-generation propagation and preserved canonical-v1 actor authority.

Quoted ownership and exclusions: “Own new docs/handoff/main-quantitative-integration-20261012/caller-review.md only. No source/provider/savedruns/runner edits.” The combined MCP-to-ReportAgent acceptance belongs to Ohm and is outside this sidecar. Coordinator code is frozen except comment/config and current new core-policy work. This note is the only file this sidecar may write; findings are returned to the coordinator for implementation.

## Method and existing evidence
Trace current source call paths and actor/context gates, inspect the supplied `/private/tmp/drf-main-seed-data-20261012-01` receipt/JUnit and four consumer cases plus ensemble controls, and bind reviewed source hashes before/after review. Do not infer main/manual/graph/brief execution coverage from the seed-only scenarios.

## Updates
- 2026-10-12: Created the owned review note before investigating caller behavior.

## Actionable findings

### CR-1 — P1: canonical shared world context ignores explicit actor knowledge denial

Location: `backend/app/services/simulation_config_generator.py:1665`, especially the visibility-only admission at lines 1709–1717. `_canonical_public_world_rows` reads the complete `actor_intelligence.dimensions` from validated packs. It checks source references, excludes analyst inference, and admits public visibility, but never checks either `raw.actor_knows` or `raw.qualifiers.actor_knows`. `_build_canonical_public_world_brief` publishes those rows to every actor; `_build_context` also uses that same builder at line 1986. The actor-local policy in `actor_context.py:970–987` explicitly makes JSON `false` override visibility. Pack construction preserves the complete intelligence object (`actor_context.py:1405`), so the shared selector can reintroduce a claim denied by the actor-local projection.

Concrete source-slice result: a source-bound `verified_fact` claim with `visibility="public"`, `source_refs=["S1"]`, and `actor_knows=false` was emitted in the canonical world brief as `DENIED_MARKER [sources=S1]`. Repeating with `qualifiers.actor_knows=false` produced the same result. The actual `_validated_canonical_context_pack` and dossier hash-binding method ran in the source-slice probe with matching synthetic fingerprints; this was not a bypass around those selector checks. It was not a full producer admission or simulator run.

Action: apply the explicit-denial policy before public sharing. Collect denials across admitted packs before building common knowledge so an allowed duplicate in another pack cannot reintroduce denied evidence. Cover top-level false, qualifier false, and duplicate claim identity/text across packs, with an allowed-public positive control. Keep analyst/modeler-only evidence excluded. This is an existing selector defect exposed by the requested authority review; passing the new `official_data` field does not itself cause it. `_build_world_brief` correctly returns through the canonical branch at lines 1880–1887 before the new legacy statistical block, but that early return does not fix the selector defect.

### CR-2 — P2: extra-seed simulations cannot resolve their official-data handoff

Location: `backend/app/services/pipeline_orchestrator.py:7101`, with the creation/preparation sequence at lines 9115–9139. The helper matches only a pipeline's top-level `simulation_id`. `_run_one_seed` creates a new seed simulation and immediately prepares it without registering that ID as a child of the parent research generation. `SimulationConfigGenerator.generate_config` calls `load_for_simulation(simulation_id)` at line 624, which delegates straight back to this primary-only lookup (`official_data.py:53–55`). Therefore unversioned extra-seed world briefs receive no official-data snapshot, even though the direct seed ReportAgent constructor correctly loads the parent's handoff at orchestrator lines 9218–9221.

The gap persists for subsequent manual report generation/chat: `app/api/report.py:378–387` and `1552–1561` both use this helper for the seed ID. Completed extra-seed IDs exist in `ensemble_checkpoint.json` and `ensemble_forecast.json.extra_runs` (orchestrator lines 9002–9010 and 9059–9062), but the resolver never consults them; the checkpoint is also written only after the seed has already prepared and reported.

Concrete source-slice result: a synthetic pipeline mapping for `sim_main` returned its carrier, while `sim_extra_seed` returned `official_data=None`. The supplied seed test replaces `prepare_simulation` with a no-op (`test_official_data_consumers.py:67–69`), so its valid/corrupt carrier assertions do not cover this lookup.

Action: bind each seed simulation to the parent's explicit handoff/generation before PREPARE, without replacing the parent's primary ID, and reuse that association for manual callers. A transient injected carrier can solve preparation, but manual lookup also needs a durable association. Add acceptance that the seed PREPARE lookup and manual generate/chat resolve the same generation, including after reload and with a distinct primary simulation ID. Canonical-v1 must retain its existing pack-only branch; the missing legacy baseline must not be repaired by injecting raw statistics into canonical actors.

### CR-3 — P2: manual lookup follows a mutable handoff instead of the simulation's research generation

Location: `backend/app/services/pipeline_orchestrator.py:7103–7113`. After matching a simulation ID, the resolver reads the current files at `handoff_dir`; it never checks a simulation-bound research generation, the research seal, or the simulation's stored report/actor fingerprints. `ReportAgent.__init__` stores the carrier directly at `report_agent.py:1613` and adds no lineage check. Dataset JSON/CSV hashes validate the internally consistent current dataset, not that it belongs to the simulation being explained.

Concrete trigger: create a scenario fork from research generation G1; `fork` deliberately shares the base handoff (`pipeline_orchestrator.py:8647–8652`). If that shared handoff is later legitimately replaced/resealed as G2, manual generate/chat for the still-existing G1 fork reads G2 data beside the G1 simulation. There need be no corrupt JSON or hash mismatch. A read-only source-slice probe held the simulation ID and handoff path constant, changed the synthetic current carrier from G1 to G2, and observed G2 returned on the second lookup. The probe establishes the missing caller binding; it does not claim that any saved run has this condition.

Action: record the consumed research/data generation with the simulation, resolve an immutable snapshot when available, and otherwise reject/omit enrichment on a generation mismatch instead of silently substituting current data. Apply the same association to seed registration in CR-2. Test a G1 simulation against a valid G2 replacement of the same handoff and require G1 data or an explicit unavailable result. Testing only corrupt data does not cover this case.

## Evidence and limits

The supplied JUnit `/private/tmp/drf-main-seed-data-20261012-01/junit.xml` contains six passes, zero failures/errors/skips, 0.971 seconds: four consumer cases and two ensemble helper controls. The completion receipt records exit 0, identity preserved, complete shutdown, no blocked events, no source drift, and no children. The four consumer cases exercise the real seed method with a substituted ReportAgent and substituted simulation/model execution, a manual dossier helper with a substituted dataset API, and a source merge. They do not execute manual Flask generate/chat, the main REPORT branch, graph ingestion, seed world-brief preparation, or real canonical public selection. The supplied receipt binds test/runner/config/logger/simulation-manager hashes but does not bind the orchestrator, manual API, official-data adapter or Data API hashes; this review's hashes below describe inspected bytes and do not retroactively extend that run's proof.

The source paths for main REPORT (`pipeline_orchestrator.py:13658–13670`), the direct seed constructor (`9218–9226`) and graph snapshots (`12843–12850`) consistently load the explicit active handoff, including a fork's shared handoff. No separate actionable wrong-directory finding was identified on those direct calls. Graph snapshots enter modeler research chunks; canonical profile construction switches to the sealed role path (`oasis_profile_generator.py:721`), canonical configuration context returns before graph summaries (`simulation_config_generator.py:1977–1991`), and raw official-data snapshots are excluded by the canonical world-brief early return. CR-1 is the remaining concrete actor-authority defect in that path.

The read-only probes used `backend/.venv/bin/python -I -S -B` with stdlib only. They parsed current source into ASTs and executed only the extracted lookup function and six canonical selector/binding methods in memory. Pipeline persistence, artifact reads and the Data API were synthetic in-memory adapters; formatting, identity extraction and hashing helpers were controlled stand-ins. No application module was imported, no provider was invoked, no saved run was opened, and no probe artifact was written. The first probe stopped because its restricted import adapter rejected `__future__`; permitting that stdlib import allowed the probe to complete. These are narrow source-behavior demonstrations, not guarded producer-to-consumer acceptance or proof that the complete actor producer admits the synthetic fixture.

Observed probe output:

```json
{"caller_slice":{"main_first":{"generation":"G1"},"extra_seed":null,"same_sim_after_handoff_change":{"generation":"G2"}}}
{"authority_slice":"top_level","denied_marker_published":true}
{"authority_slice":"qualifier","denied_marker_published":true}
```

## Coordinator follow-up
The three findings above remain open; this sidecar implements no fixes. CR-1 needs a real producer/pack-to-world-brief regression, CR-2 needs seed ownership propagated before PREPARE and through manual lookup, and CR-3 needs simulation-to-data generation binding. The broader combined MCP-to-ReportAgent acceptance remains with Ohm. Re-review changed caller/authority bytes after corrections, and use a fresh frozen-runner evidence directory for any new runtime acceptance.

## Source-hash proof

All inspected caller/authority files and test/runner files below were rehashed at review close. The only changed file during the hash interval was `deerflow_bridge/data_sources.py`, which is concurrently owned producer/policy work outside this sidecar. Its initial hash was `7654daf5d2e313e6d18c214d1fb958d3cc4135aa7b4a99c67b15494272e493ed`; the closing hash is recorded below. The findings concern stable caller/selector bytes and do not claim approval of the changing Data API.

| File | Closing SHA-256 |
| --- | --- |
| `backend/app/services/pipeline_orchestrator.py` | `4626ae8250ca982ebf6e6af37e62d4587fd087b0d959b10862592979d396b6ac` |
| `backend/app/api/report.py` | `a8eaf7ef5fe9098e45f6f0a4a632c1437e34ed5193a8e093c5613dada5d725bd` |
| `backend/app/services/official_data.py` | `6f22895f3da115db61346387a9576b3b2200fea86255778a77b662f507eda8ac` |
| `backend/app/services/simulation_config_generator.py` | `24af7cb84c403c18444ea4b0564327b2377f247db091a03fb7a77dac7c6e1ad2` |
| `backend/app/services/actor_context.py` | `17f12e5ba2b8f02309ab3ba65a08ee14afe93383217e5707ccf941efea1a0dbf` |
| `backend/app/services/simulation_manager.py` | `f0ba8c46f915dc204e5975133eeb51d8a07525829d8ceec5c36e765d0f4f0f59` |
| `backend/app/services/oasis_profile_generator.py` | `78ede1941fc9ff3ed648e764ac5e6bfc8955469f280d9419d30ecdc364139cfe` |
| `backend/app/services/report_agent.py` | `49cd75ed321e891b18f5d09a2cc712dadf09ce6460a0374afa4ba97dfff66a5b` |
| `deerflow_bridge/data_sources.py` | `419663c3bbd0d1a790212ed229023b6f5b171e9e74adecff16adc4b04f001511` |
| `backend/tests/test_official_data_consumers.py` | `29d9f91533fb48f6a4d8f075fbd7810f3ead9fccd81729455c3b8698776d403d` |
| `backend/tests/test_seed_ensemble.py` | `09c0a2ab55975b2fd907f8000798b90b521ccab210430fdeedc3f7405d3b47ab` |
| `backend/tests/test_official_data_downstream.py` | `159a80a32808cfdb370e4688d7fb8101a8d908b22015ffd5c8cbee8b39f7949a` |
| `backend/scripts/main_offline_pytest.py` | `53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa` |

- 2026-10-12: Completed caller tracing, source-slice counterexamples, supplied receipt inspection, and closing source-hash comparison. Wrote only this note; no source/test/runner changes, new runtime test runs, provider calls, saved-run access or Git operations. Three findings returned without implementation.
