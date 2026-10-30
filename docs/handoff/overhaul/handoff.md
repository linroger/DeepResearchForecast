# One-world-model overhaul reconciliation

**Status:** The broad architecture remains a draft awaiting approval. The separately approved spending and World Anchor prerequisites are implemented and accepted offline.
**Updated:** 2026-10-30 (Asia/Shanghai).

## Request and source authority

[PLAN.md](PLAN.md) preserves the supplied 445-line proposal; [source.json](source.json) records its source and hash. It supersedes the old first-ten roadmap as a planning reference. It does not authorize saved-run migration, paid calls or a new workflow-controller cutover. Its `main f773f61` baseline predates delivered work and must not be used to discard that work.

The spending implementation was delivered in `c2736d36`, with its closing record in `9916b3be`. The incremental World Anchor implementation was delivered in `8bc53cc50a84faf002782c5fd17caba0e766a03d` on `codex/world-anchor`. See the [World Anchor handoff](../world-anchor/handoff.md) and [verification](../world-anchor/verification.md) for current acceptance and operational limits. These deliveries do not approve or complete the whole overhaul.

## Reuse and remaining architecture

Retain the typed case contracts, authenticated receipt/replay discipline, deterministic target mechanisms and graph projections, zero-weight estimator policy, publication/translation boundaries, and verified cast/context fixes. World Anchor now adds retained evidence, bounded extraction and review, explicit gaps, scoped actor/public views and tested consumer adapters. Those components do not constitute the proposed general SQL record store or capability-scoped query API.

Map Phase A to current source before implementing it again. B1 remains the next architecture-dependent foundation once its contracts are approved. The existing pipeline state and controller remain workflow authority.

## Decisions required before B1

1. Pin one evidence/model-store authority per run. Begin with optional shadow persistence and exports; do not silently perform the ADR 0001 workflow cutover.
2. Bind host-issued reader capabilities to run, generation, actor, path, clock and permitted fields. Query arguments may narrow access but cannot request analyst privilege. SQL views alone do not grant authorization.
3. Preserve strict I-30 behavior for enabled World Anchor actors, including whole-request exclusion of analyst self-inference. Actor-generated beliefs remain simulated and owner/path scoped. Broader adoption must preserve historical off-mode contracts explicitly.
4. Keep publication, retrieval, vintage, effective and observation times distinct. Missing dates stay unknown. Generation and path belong in cache identity.
5. Define atomic store/export publication and recovery. Export manifests must bind a committed snapshot, code, policy, RNG and exact attempt inputs/outputs without mixing generations after a crash.

[invariants-review.md](invariants-review.md) retains the further estimation, lookahead, publication-fence and causal-order questions. The proposed computed-probability principle still needs reconciliation with authoritative LLM posterior steps. Preserve the current identity policy and treat a replacement as shadow until its promotion criteria pass. Simulation-derived cruxes and conditional cards must not enter ordinary narrative or critic inputs indirectly.

## Spending and verification boundary

The durable spending ledger remains an independent control authority. World exports, replay and forks cannot rewind it. The initial private profile covers one qualified model family and Firecrawl; it does not implement every future agent family or per-phase monetary allocation. World Anchor adds retained stage counters to that same authority. Source-policy packet bounds are not model-native tokenizer qualification.

The dated budget review preserves earlier planning observations. Current offline receipts supersede its old implementation-status statements only for the delivered slices. No live tariff, provider budget, deployment, scheduler or empirical forecast-quality approval follows from these tests.

Before B1 code, obtain approval for the reconciled contracts and a bounded producer → store → sealed export → authorized query slice. Preserve the supplied draft, reviews, current source pins and private evidence. This document is architecture reconciliation, not a new overhaul acceptance claim.
