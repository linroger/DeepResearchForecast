# Completion plan: simulation and forecast provenance

The user authorized completing and verifying the attached architecture and Claude's existing implementation on 2026-10-23. This is continuation of that approved plan, not a new architecture or probability-policy change.

## Intent and boundaries
Recover the committed S0–S4 implementation, close actual fidelity/information-flow/UI gaps, and verify the research → ontology → graph → preparation → simulation → report boundary. Preserve unrelated Mandarin repair work in the primary checkout. The simulation remains diagnostic-only by default, with a separate period-by-period record and one deterministic labelled report bridge; no_update omits the bridge. No model calibration or engine promotion is part of this change.

## Implementation and checks
1. Recover `claude/sim-provenance-impl` at 579c1acf in an isolated managed worktree; record existing assets and test infrastructure.
2. Audit and fix record compilation/gating/API publication and dashboard consumers in disjoint work streams. Validate healthy, hollow, malformed, stale, bilingual and engine-adapter scenarios.
3. Locally close simulation input paths in outline, section, critique, repair and probability consumers. Strengthen the two-simulation invariance tests through publication, including no-spine and no_update paths.
4. Run the existing guarded offline backend runner, frontend scenario tests and production build, plus independent review on the tested bytes. Replay copied real artifacts if available; never overwrite saved runs.
5. Update ADR/design/handoff/feature progress with exact evidence and remaining live-only limits; deliver owned commits and reconcile the feature into the active application without losing unrelated dirty work.

## Acceptance
- A healthy committed simulation produces a faithful, public-only record; invalid/stale records are not served.
- Different simulated trajectories cannot alter research-driven prompts/probabilities or report prose outside the deterministic bridge.
- diagnostic_only produces exactly one validated bridge; no_update produces none, and the simulation record remains accessible.
- The record and bridge render through actual API/frontend consumers in both language modes; tests and build apply to the delivered source.
- Source delivery, deterministic verification and provider-backed validation are reported separately.
