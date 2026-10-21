# Context propagation audit and repair plan

The user requested checking context within every workflow stage and across all stage boundaries, ensuring failures are found and resolved. This authorizes source tracing, guarded deterministic probes and small necessary fixes. It does not authorize new providers, paid/live model runs, service deployment, default-engine promotion, speculative redesign, or changing unrelated primary-checkout work.

## Invariants

- The admitted question, language, information cutoff, horizon, selected policy and attempt identity survive every required handoff.
- Evidence identity, units, time, epistemic status and source/capture lineage remain bound to the exact consumed generation. Required proof failures cannot silently degrade into another generation.
- Actor IDs, goals, constraints and permitted knowledge reach the correct actor; private/denied evidence and scenario shares cannot enter an unauthorized prompt through an alternate route.
- Bounded context selection and compaction disclose omissions; stage-specific prompts include the context required by their contract rather than merely persisting an unused JSON field.
- Prepared configuration, roles, simulation state/observations and commitments remain consistent across rounds, restart, fork and seeds. New data cannot be adopted by a saved run without valid invalidation/rebinding.
- Reports, summaries, chat, localized content, API and exports use the consumed research/simulation context and current publication seal; they cannot silently substitute a fresh provider capture or stale report artifact.

## Execution

1. Freeze current-main authority and preserve the unrelated dirty primary checkout. Build a context contract/coverage map: producer → persisted artifact → consumer → actual prompt/rendered use → cutoff/access/reuse guard.
2. Parallel bounded stage audits: v3 research; legacy research; ontology/graph; prepare/actor/persona; default simulation; opt-in world-v1; report/publication. Coordinator owns admission, orchestration, lifecycle and cross-stage reconciliation.
3. For each concrete defect, record a meaningful failing reproducer, make a small repair within owned files, verify the actual consumer and restart/negative controls where relevant. Keep source-only suspicions distinct from reproduced failures. Resolve shared-file ownership before edits.
4. Reconcile every stage boundary and alternate path (research-only/continue, direct/manual API, resume/fork/seed/ensemble, backtest, off modes, chat/translation/export). Integrate targeted fixes and run the relevant combined gate on frozen bytes. External model/provider/graph/platform responses may be scripted; actual production methods and durable contracts remain real. State substitution limits explicitly.
5. Independent review, exact source hashes and passing receipts must cover the final implementation. Record residual limits honestly; tests cannot prove absence of all possible semantic/model failures.
6. Commit only owned paths, integrate with current main without discarding concurrent commits, push normally and verify the remote SHA. Preserve primary concurrent edits and all historical red receipts.

## Ownership

Coordinator: pipeline_orchestrator.py, API admission/lifecycle and final cross-stage tests/docs. Stage workers receive explicit disjoint production paths and own their stage notes/tests. Shared helpers require coordinator agreement before editing. No worker mutates Git, primary checkout, production uploads or credentials.
