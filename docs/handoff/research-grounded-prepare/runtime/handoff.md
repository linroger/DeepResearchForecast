# Runtime handoff

Status: Complete (owned runtime slice, offline). Updated: 2026-10-23 UTC.

## Request and ownership
Implement approved PLANS E bounded opt-in adaptive sibling paths and real preparation consumption. Owned production files are backend/scripts/run_parallel_simulation.py and backend/app/services/world_paths.py. Parent owns config, preparation seals and world_update. Preserve concurrent edits; no primary checkout edits, commits, services or provider calls.

## Requirements and acceptance
| Requirement | Check and evidence |
| --- | --- |
| Research reaches actual actor and arbiter inputs | Real coordinator scripted model captures actor-specific/public/modeler sentinel visibility; marked missing/tampered/stale bundle fails construction. |
| Branches use local state | Divergent scripted worlds drive different next decisions, commitments and public discourse; late actors never see path 0 discourse. |
| Bounded and pinned | Invalid/unbounded settings rejected; positive budget reserved before calls; max actors/rounds honored; environment cannot alter persisted policy. |
| Resume and replay | Reconstruct committed branch state, personas, private moves and records; incomplete/mismatched artifacts fail closed; accepted arbiter replay persisted. |
| Compatibility | Existing shared path tests and coordinator context tests stay green. |

## Plan and decisions
Use config settings branch_policy=adaptive-v1 with explicit branch_decision_budget, branch_max_actors, branch_max_rounds, path_count and path_seed. Default shared-v1 stays unchanged. Freeze all actors' role text before the first decision round and store it for branch-local calls. Preparation is loaded once before best-effort catches; full verified bundle goes to world_update, which renders modeler context itself. Parent confirmed canonical actor_id mapping will be added.

## Progress and findings
Source inspected; existing siblings share decisions, commitments and mass. Separate adaptive decision production and share calculation are needed. Existing main_offline_pytest.py and primary provisioned Python will be used; evidence goes to sibling runtime-* directories.

## Issues and recovery
No implementation checks yet. Incomplete adaptive writes must not refund consumed budget or silently rebuild from path 0.

## Verification
Pending guarded real-coordinator tests. No live calls authorized or performed.

## Remaining work
Implement, capture guarded scenario evidence, inspect exact diff, and hand off interfaces/results to parent for composed review.

## Updates
- 2026-10-23 UTC: Created after reading approved plan and confirming disjoint ownership. Parent clarified preparation_context takes the full verified bundle; replay is record['replay'].

- 2026-10-23 UTC: Implemented strict preparation loading, audience render consumption, explicit adaptive envelope, branch-local calls/shares/discourse, durable pre-call reservations, restart checks and primary/sibling replay records. First guarded run passed 20 and failed seven fixtures (the controlled numeric fixture ignored actual damping and preparation fixtures omitted visibility); corrected fixtures. Second run passed all 27 new cases plus shared paths; total 74 pass / one concurrently obsolete role-context fixture. The owner has since fixed that fixture. Private receipts are at `/Users/rogerlin/.local/share/DeepResearchForecast/verification/research-grounded-prepare/runtime-first` and `runtime-second`; relocation.json in each confirms exact before/after file hashes. No generated trees remain here. Receipts record one blocked socket-construction attempt and contained import probes; they do not claim zero network attempts.
- 2026-10-23 UTC: Runtime-third passed 89 tests, then independent reviewer Faraday identified five lifecycle defects not covered by direct commit tests. Six new platform-facing cases reproduced every issue in private runtime-review-red: final checkpoint failure was swallowed, missing paths permitted fresh budget reset, env opt-out bypassed pinned admission, sibling capacity clock was stale, and inactive initial rounds lacked personas. Corrective changes latch adaptive failures through all APIs/finalization, defer public committed flags until persistence, preserve in-flight reservations/pending buffers, reject reset on any existing execution evidence, honor pinned runtime despite legacy env opt-out, start sibling rounds before menus, and freeze all personas during both platform setups before DB resets/activity. A composed affected gate and independent rereview are pending.
- 2026-10-23 UTC: runtime-review-green2 passed 99 cases in 23.73 seconds, including actual platform loops, final persistence failure without platform checkpoint, dual-platform delivery waiting for durable commit, inactive first round, reset DB preservation, capacity restoration, local-private-memory resume, and all primary/sibling replay checks. Receipt process-41158.json completed exit 0, shutdown complete, identity preserved, source_drift=[], and a post-run rehash found no changed recorded sources. Guard counts: one blocked socket construction, four blocked subprocess probes, twenty blocked external reads (eighteen font scans); no live provider invocation occurred. Final independent rereview pending.

## Exact parent interfaces
- `research_preparation` config carries only schema_version, content_sha256, and source. Construction invokes load_preparation_context once with both pins. Actor prompts use canonical agent_configs.actor_id; public projection joins the world brief; the full verified bundle goes to run_world_round(preparation_context=...).
- `world_model.settings.branch_policy='adaptive-v1'` requires path_count (integer 2..8), path_seed (integer), branch_decision_budget (integer 1..4096 shared across siblings), branch_max_actors (integer 1..64 per sibling per round), and branch_max_rounds (integer 1..256). path_temperature is optional finite 0..1, default 0.7. Legacy shared-v1 remains the default. The budget is additional structured decision attempts, not provider retry charges or total simulation cost.
- `record['replay']` is preserved in primary world_state_history.jsonl and sibling world_paths.json records. replay_world_round is verified without provider access. Adaptive paths persist pinned settings, frozen personas, decision usage/reservation, own prior decisions/discourse, world/shares/history, rounds and stop reasons, plus content hash. Interrupted reservations require explicit recovery/new simulation; they are never automatically refunded.
- No paid experiment, default activation, primary checkout edit or commit is performed by this slice. Parent owns composed validation/delivery.
- 2026-10-23 UTC: Second review closed budget-reset/env/capacity/inactive-round findings and identified outer dual-main admission swallowing plus primary decision-journal write degradation. Two actual-runtime tests reproduced both in runtime-review2-red. main now propagates WorldContextMismatch from gathered platform results before any post-hoc fallback or ready marker; adaptive decision-journal failures latch before publication/commit. Parent added explicit preparation_audience mapping for legacy graph extras: public with blank actor_id receives public context, public with nonempty ID and unmarked blank non-Audience IDs reject. Added real decision-prompt mapping scenarios. runtime-final and focused review closure pending.
- 2026-10-23 UTC: Parent explicitly revised the shared arbiter audience to PUBLIC-only after a P1 proved modeler-private claims could echo into shared digests. The full verified bundle interface and replay binding remain unchanged. Runtime's actor owners still receive their admitted private projections; graph extras get explicit public-only admission. Updated the actual arbiter assertion to require a public 120 MW observation with source/series identity and exclude both modeler-only and owner-only rows. The earlier modeler-render interface text above is historical and superseded for the shared consequence arbiter; native modeler enforcement remains parent-owned. runtime-final had 103 passes/1 expected-to-update assertion under this clarified boundary.

- 2026-10-23 UTC: FINAL ACCEPTANCE. runtime-accepted passed 104 cases in 23.20 seconds; process receipt completed exit 0, shutdown complete, identity preserved, zero source drift during execution and post-run rehash. Acceptance record: `/Users/rogerlin/.local/share/DeepResearchForecast/verification/research-grounded-prepare/runtime-accepted/acceptance.json`. Faraday independently closed all findings for runtime SHA256 9066ce940551892774ae5b2e137729a216a02fb9fff841becaea8f4864eb12e1 and test SHA256 00378ae50bb579454bd5cafc4ca0042640d3cb00917679f73dd5c2799e125037. AST and scoped diff whitespace checks pass. Production world_paths.py SHA256 396687caa7985384aa7fc5cef21ef70cd9a7a76f91dc9f3a0cb762c3241000e9. All remaining work belongs to the parent's composed integration/delivery; this worker made no commits or primary edits.

## Parent handoff prompt
Review and integrate the two owned runtime files plus backend/tests/test_grounded_runtime_paths.py at the hashes above. Preserve other workers' changes. Reuse the private runtime-accepted receipt and review closure; rerun affected checks if composed source changes. Keep adaptive mode explicitly opt-in, shared consequence research public-only, and sealed actor_id/preparation_audience mappings. This compact handoff.md is ignored by the repository's generic handoff rule and needs explicit inclusion if delivered.
