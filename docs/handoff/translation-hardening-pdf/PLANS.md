# Unified translation-system redesign and language-aware export

**Date:** 2026-10-26 (Asia/Shanghai)
**Status:** Approved by the user; implementation in progress.
**User direction:** Rearchitect the whole translation system for robustness and efficiency instead of accumulating patches.
**Design authority:** [architecture.md](architecture.md).
**Evidence:** [findings.md](findings.md), [saved-failure-evidence.json](saved-failure-evidence.json), [diagnostic-probes.json](diagnostic-probes.json).
**Continuity:** [handoff.md](handoff.md). [initial-repair-plan.md](initial-repair-plan.md) is superseded history.

## Intended result
One durable translation service serves documents, structured report fields, graph content and both simulation engines. One frontend controller owns progress/retry/reconnection. Source-bound reviewed generations are shared by the UI and English/Mandarin PDF export. Work that passed is reusable; translation and review resume independently. Canonical artifacts, accepted historical translations and visibility boundaries are preserved.

## Delivery slices

1. **Freeze contracts and build durable core.** Implement typed snapshot/unit/job/attempt/receipt/error contracts, transactional SQLite persistence and fenced single-host job ownership. Separate execution state, content availability and coverage. Characterize existing consumers and preserve fixtures. Acceptance: idempotent starts, short transactions, crash/restart at every persisted stage, stale-owner rejection, unknown-call accounting and no read-time provider acquisition.
2. **Replace translation execution.** Reuse/refactor the current parsed Markdown and semantic receipt logic into a staged executor with token-aware bounded batching, per-entry response admission, durable candidate checkpoints, review-only recovery and one focused content repair. Acceptance: valid/invalid protocol, semantic rejection, provider outage/refusal, budget controls, exact call counts and unchanged immutable facts.
3. **Migrate document and structured adapters.** Move report/dossier bodies and display fields into the service; add validated legacy/v1 import and generation-based publication. Existing endpoints become compatibility adapters. Acceptance: replay the20/22 and21/22 saved-failure shapes, translate only missing sections, retry dashboard-only work without body regeneration, preserve source/accepted bytes, and prove publication crash-window reconciliation.
4. **Migrate graph and simulation adapters.** Bind complete visible inventories to exact source/view contexts; replace fixed graph truncation with resumable pagination; include OASIS/world-v1 views, provenance prose, and the default completed SimulationRecord through the same Simulation control. Acceptance: no stale UUID/revision reuse, no private/public mixing, complete tail progress and all visible prose represented.
5. **Consolidate UI and PDF consumers.** Introduce one translation composable/status component and one artifact-language resolver. Replace divergent polling and retry logic in each tab. Extend existing PDF routes/buttons to consume immutable accepted snapshots, use atomic dependency-bound caches and show explicit export language plus inline errors. Acceptance: all-control matrix including disconnect/reconnect/unmount; real English/Mandarin PDFs with tables/charts/citations and visual inspection.
6. **Cut over, remove duplicate paths, and deliver.** Reconcile all current callers, remove retired route-level worker/state code and obsolete active generation branches, retain explicit historical readers only. Run guarded backend scenarios, frontend tests/build, real PDF checks and independent source review. Check process ownership, activate safely, and perform bounded observed recovery of the reported translations with the existing provider where available. Deliver scoped commits and remote publication with exact evidence and any external limits.

## Ownership and working-tree preservation
The current checkout contains extensive pre-existing work. Preserve it as the baseline; do not replace it with HEAD or stage unrelated files. Core ownership: contracts/store/executor. Adapter ownership: document/report and graph/simulation with disjoint files or coordinated sequential integration. UI ownership: common controller and component migration. PDF ownership: resolver/export integration coordinated with report adapter changes. Independent review owns no production files. Assign concrete write sets only after plan approval; shared large files are integrated sequentially.

## Acceptance, scope and tradeoffs
The scenario matrix in architecture.md is the completion contract. No production fact checks or semantic-review requirements are removed to achieve apparent success. SQLite is local standard-library infrastructure already used in this app, not a new hosted dependency. Single-host durability is the target; distributed multi-host scheduling is out of scope. Existing provider configuration stays in use. The design includes the default simulation record because translation must follow the active Simulation view; it adds no unrelated ontology/log translation feature.

Export means the report language currently displayed, with a visible Mandarin/English label. It uses existing admitted content and does not initiate translation. Final PDF acceptance includes real rendering, not only mocked routes.

Performance evidence is deterministic call reduction on unchanged/retry fixtures plus observed stage metrics; no unsupported live speed or cost claims. Every accepted unit is retained across normal retry. The task is complete only after all migrated controls and output consumers use the unified service and the relevant scenario matrix passes on reviewed bytes. Interrupted external provider acceptance is reported separately.
