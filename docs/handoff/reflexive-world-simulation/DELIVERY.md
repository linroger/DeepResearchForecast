# Reflexive world simulation: delivery and evaluation

> Current continuation: release work is in progress under the [current record](behavior-rerun/semantic-consistency/release-readiness/CURRENT_STATE.md). V4 preserves bounded private review fields while retaining strict action/verdict controls; it is not yet accepted by a fresh full behavior study. The historical full study remains 16/18 comparisons and world-v1 remains opt-in. All 17 live phases are closed with conservative exposure USD20.074838955664 of the amended USD40 total, leaving USD19.925161044336 before any new run. Earlier delivery statements below are historical evidence.

The `world-v1` engine implements the requested evolving-world feedback loop on `codex/reflexive-world-simulation`, based on main `8852ce123fa15a6b4f4c3e6e4e492435c0e3137b`. Implementation commit: `e902aedb1a8307c024da950060c4d7bb30f34220`. It is available by explicit opt-in. The live behavior gate did not pass, so `oasis-legacy` remains the default and the overall feature's promotion flag remains false. This delivery does not claim calibrated forecasts or validated general realism.

The [source-linked architecture report and diagrams](ARCHITECTURE.md) explain research, the DeerFlow harness, actor ontology, Graphiti, world simulation and forecasting end to end. The [implementation contract](implementation-contract.md) documents executable interfaces. The [handoff](handoff.md) preserves decisions, failures, review closures and follow-up instructions.

## What changed

- **Concrete world and time.** Accounts, capacity, rules, alliances, projects, commitments and events evolve through typed mechanisms. Flows and delayed effects advance between decision periods. Events retain causal references.
- **Actors with bounded knowledge and authority.** Research-derived or explicitly assumed roles include goals, values, beliefs, incentives, capabilities and constraints. Each actor sees its own state and permitted facts/options. Counterparties consent independently; speech cannot move resources, cast someone else's vote or waive constraints.
- **Reflexive decisions.** Actors propose from a common opening snapshot, recipients respond, the kernel resolves feasible actions and commits the next world. Subsequent observations contain permitted consequences and the actor's own action results. Reflection has provenance and priority changes require declared triggers.
- **Recovery and budgets.** Immutable input pins, SQLite fencing, atomic commits and durable request receipts prevent duplicate effects and renewed retry allowances. Explicit tariffs/output limits bound supported HTTP requests, including malformed replies and unknown calls. Each stable decision slot has at most two attempts.
- **Integrated consumers.** Pipeline/API lifecycle, cancellation, forks, seeds, committed status, EN/ZH world UI, reports, charts, chat, translation and export use the same result identity. Fresh worlds fairly rotate overflowing recipient inboxes; saved generations retain their prior queue behavior.
- **Evidence separation.** Graphiti remains observed-research memory. Hypothetical world events stay in the simulation store. `diagnostic_only` permits a conditional report appendix; `no_update` omits simulation reasoning/plots. Both keep simulated outcomes out of probability-generating evidence.

## Live model evaluation

The preregistered synthetic study used the existing GLM-5.3 HTTP configuration and fixed four-period investment/supply, trade/policy and coalition/institution cases. It paired reflexive runs with a targeted external-field ablation. The original 36-case matrix, scores and failure denominator are preserved in the [frozen report](live-evidence/report.json) and [preregistration](live-evidence/preregistration.json).

| Domain | Completed / planned | Rubric points | Paired contrasts | Verdict |
|---|---:|---:|---|---|
| Investment/supply | 12 / 12 | 84 / 96 (87.5%) | 5 passed, 1 failed | Rubric passed; contrast requirement not fully met |
| Trade/policy | 12 / 12 | 47 / 96 (48.95%) | 6 failed | Failed |
| Coalition/institution | 6 / 12 | 48 / 96 (50%) | 2 passed, 4 incomplete | Incomplete after transport failures |
| Total | 30 / 36 | Original per-domain denominators retained | 7 passed, 7 failed, 4 incomplete | No default promotion |

Three independent agents reviewed all 30 completed cases and both focal decisions in each. They verified bound observations, decisions, receipts and traces. Their [investment](live-evidence/qualitative-review-investment.md), [trade](live-evidence/qualitative-review-trade.md) and [coalition](live-evidence/qualitative-review-coalition.md) reports distinguish invalid attempts rejected by the engine from accepted physical/authority/structured-privacy violations; no such accepted violation was found within their bounded completed-trace checks. This is not a general security proof or a review of every failed partial trace.

The study demonstrates concrete model-driven interactions, including investment with delayed capacity changes, counterpart consent and settlement, and opposing coalition votes after observed alliance formation. It also exposes limitations:

1. Many trade actors bought their single required good in the first period and then legitimately waited. The preregistered proxy expected later route-specific purchases, so it does not cleanly measure their response after goal fulfillment. Scores were not regraded.
2. Some explanations misread quantities, prior agreement status or source attribution. Mechanism enforcement does not make model reasoning reliable.
3. The ablation hides a particular external record field. Public actor messages remain available and sometimes communicate related changes; it is not removal of all external information.
4. Six coalition cases failed or were stopped after transport failures. They remain in the denominator, and no recovery run was substituted for them.
5. Seed labels identify matched repetitions; they do not establish independent statistical samples. Synthetic behavior is not forecast calibration.

No additional batch was launched to seek a passing result. A future behavior study should preregister a continuing decision need aligned with the stimulus, define the intended information intervention explicitly, and preserve these results as development evidence.

## Budget and verification boundaries

The final batch recorded 625 attempts, including 37 retries. Its measured usage at the pinned conservative tariffs was USD4.158586, with USD0.726470 retained for unknown exposure: USD4.885056 total. Across all five development/evaluation phases, the conservative consumed ceiling is **USD9.222150955664**, leaving **USD15.777849044336** unused from the original USD25 authorization. Earlier interruption ceilings are retained. These are exposure estimates, not audited provider billing. Cumulative reservation quotes are audit telemetry and are not added to actual plus unresolved exposure. The [global ledger](live-budget.json) is closed, with no active output authorized for dispatch.

Verification receipts are indexed in [offline-verification.json](offline-verification.json). Historical gates include 615 combined checks before live contract repairs, 496 checks after reflection repair, and focused source-bound closures for exposure budgeting, bounded error feedback and request-owned execution envelopes. Counts from separate runs must not be added as unique coverage. The final combined gate passed **691 tests in97.24s**, with no failures, errors, skips or source drift across515files. A subsequent reviewed project-filter correction passed **73 lifecycle/admission/reuse tests in9.33s**, also with no drift. Only simulation_manager.py and its lifecycle test changed between those gates; all other captured source hashes match. New-code Ruff F/E9, diff whitespace checks and the existing init.sh smoke check pass.

The unchanged UI sources match the accepted 24-case compiled Vue/reactivity/SSR suite and production build. [Browser evidence](browser-evidence/receipt.json) covers real Vue components with frozen real Flask responses: EN/ZH, current/earlier rounds, public/actor/analyst views, keyboard focus, mobile layout and legacy feeds. This is isolated component/browser acceptance, not a live complete research-to-report browser run. The guarded backend runner is a CPython audit boundary, not an OS sandbox; deliberate blocked controls and native discovery probes are reported explicitly.

The queue-fairness policy was integrated after the frozen live batch. Sixteen permanent offline cases exercise fairness, recipient independence, privacy, failure/reopen and old/new preparation/fork behavior. A saved 36-case scripted comparison verifies identical semantic/observation results for old unpinned specs. This change has offline proof; it was not silently included in the original live-model source claim.

## Running and continuing

Use `simulation_engine: "world-v1"` through the existing research or direct simulation APIs with a model candidate or explicit supported `world_policy_spec`. Preparation compiles research/actor evidence and pins the resulting generation. Missing mechanism parameters fail as modeling gaps rather than being invented. [Synthetic examples](../../../backend/app/services/world_simulation/examples.py) illustrate supported mechanisms; [policy.py](../../../backend/app/services/world_simulation/policy.py) defines the strict metadata/transport requirements. Unsupported opaque CLI transports are not admitted to this budgeted mode.

Read results through `GET /api/simulation/<id>/world` and the existing research simulation tab. The result supports public, actor and analyst projections plus round/revision selection. Edit a sealed model by creating a new generation or fork; do not reseal saved simulations in place.

The [final independent review](final-review.json) closed the queue/list changes with no remaining findings in that scope. Remaining work is explicit in [implementation-issues.json](implementation-issues.json): stronger preregistered model-behavior evidence, empirical forecast validation before predictive claims, and remote publication after authentication is repaired. The original primary checkout's unrelated changes are preserved. No deployment or default promotion is part of this delivery.
