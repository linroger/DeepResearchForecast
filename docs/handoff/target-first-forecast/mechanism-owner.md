# Target mechanism and actor runtime owner report

Status: Part-2 implementation frozen; one separately owned linear report-consumer integration check remains pending. Part-1 acceptance is retained below. Scope is the deterministic runtime, its tests and this report only. The coordinator owns the shared handoff and core case validator.

## Request and acceptance

Implement the frozen `run_paths` and `actor_observation` APIs with a whitelisted resolution DAG, bounded per-path draws, actor decision rights, cumulative capacity, independently authenticated consent, delayed effects, persistent plans, cadence and triggers, private information and delayed releases. Classify terminal predicates and emit baseline, sensitivity, dated signposts and deterministic replay metadata with simulation weight fixed at zero.

The acceptance scenarios cover causal interventions against matched baseline draws; replay and independence from research weights; invalid graph/predicate/numeric rejection; rights, capacity, consent, lag and irreversible controls; private observations and release calendars; and typed signal effects. Tests use the existing main offline audit runner with the primary interpreter and `-I -S -B`, with a fresh canonical `/tmp` evidence directory on each run. No provider calls, service changes, commits or pushes are authorized.

## Plan and ownership

1. Compile and validate the pure mechanism DAG in `target_mechanisms.py` (delegated compiler owner).
2. Implement safe observations and actor loop in `target_actors.py` and `target_simulation.py` (runtime owner).
3. Exercise public APIs in `test_target_simulation.py` (delegated test owner).
4. Review exact source, run guarded scenarios and record evidence and supported semantics here.

Only these files and this report may be changed by this ownership group. Existing unrelated changes must remain untouched. The full design already has user authorization in `PLANS.md`.

## Decisions and constraints

The runtime will use local seeded RNG only, never global RNG state. A callback receives a constructed typed allowlist, never the original case, research assessments, scenario labels, weights or private rationale. Consent claims in an action alone do not establish another actor's authorization. Baseline uses each path's identical sampled initial state and parameters with no actor activity or callback. Offline structural validity does not establish provider realism or forecasting lift.

## Verification and remaining work

Implementation and fresh acceptance evidence are pending. The scoped report will be updated with exact template semantics, findings, checks and limits before delivery.

## Updates

- 2026-10-27: Read the frozen request, plan, contracts, coordinator handoff and audit runner. Confirmed isolated checkout base `6ab52f7746bf7ec55e9f9921c71ba4ab08e33c01`; created this scoped continuity record and delegated disjoint compiler/test files.

## Frozen supported template semantics

Inputs are positional in `inputNodeIds`. Parameter keys are exact; there is no expression evaluation or permissive fallback. The engine evaluates each DAG once per period; equations do not implicitly compound or feed outputs back into primitive nodes. Actor edits persist on primitive nodes, while computed nodes are always recomputed. Cycles, duplicate writers, invalid references and nonfinite outputs are rejected.

| Kind | Inputs | Parameters | Result |
|---|---|---|---|
| `growth` | `[base, rate]` | `{}` | `base * (1 + rate)` |
| `sum` | One or more | `{}` | Sum of inputs |
| `product` | One or more | `{}` | Product of inputs |
| `linear` | One or more | `coefficients`: list aligned with inputs; `intercept`: scalar | Intercept plus weighted sum |
| `supply_demand` | `[supply, demand]` | `{}` | Demand minus supply; positive means shortage |
| `adoption` | `[current, capacity]` | `rate`: scalar in `[0,1]` | `current + rate * (capacity-current)`; requires `0 <= current <= capacity` |
| `regulatory_milestone` | `[]` | `milestonePeriod`, `before`, `after`: scalars | Before while period is below threshold, after otherwise; fractional threshold switches at its ceiling |

A scalar is a finite literal or uniform bounded prior `{low, high, basis?, gap?, sourceIds?}`. Prior provenance inherits from its mechanism unless supplied. Assumed bases require a nonempty gap. The runtime rejects a prior `value` field, rather than silently ignoring a purported central estimate. Parameters and null-valued initial nodes draw once per path. Numeric initial values stay fixed even when a sensitivity range is present. Equal bounds consume no randomness. Each path uses a local seed derived from the run seed and its index. Linear draws use flat keys `coefficient:<nodeId>` in the returned parameter map.

## Actor lifecycle and callback contract

`decision_provider(observation)` takes exactly one detached dictionary. It may return an action, a list, `{"actions": [...]}`, or `None`. It is invoked only for `llm` actors on cadence, a rising observed trigger, or a newly received signal. With no callback, the transparent direct-lever rule controller uses an objective on the same lever node to select an endpoint; matching received signals instead supply a credibility-weighted expectation within that lever's bounds. It does not claim to optimize indirect objectives. Persistent initial plans and typed commitments run independently of cadence, once due and their observed condition holds.

Actions are `{actorId, leverId, value, consents?}` with optional `kind="lever"`. The accepted additional action kinds are:

- `commitment`: own `leverId`, `value`, future `duePeriod`, optional typed `condition`; creates a persistent plan. Capacity is checked and spent when the plan executes, so a commitment can later fail visibly.
- `consent`: `actorId`, `forActorId`, `leverId`, `value`; an independent same-period exact-value authorization. Self-asserted `consents` in the requesting action do not authorize another actor. Every required counterparty must consent from its own decision context and see the controlled node.
- `signal`: `actorId`, `nodeId`, `value`, nonempty `recipients`, optional future `duePeriod` (default next period). Sender and recipients must currently observe that node. Signals update next-period beliefs and can trigger reconsideration; they never edit state directly. Credibility is updated from final truth at the claimed period, after recipient release lags, using a bounded normalized absolute-error score.

Actions reserve cumulative capacity at `abs(value-current) * cost`. Lags delay effects; horizon-exceeding effects remain explicit pending entries. Irreversible levers lock the direction of their first nonzero accepted move. Conflicting simultaneous writes and writes against outstanding delayed effects are blocked. Actor decisions are collected before applying any same-period proposals. Malformed callback fields or a callback failure create typed blocked records without exposing raw payloads or exceptions. Each baseline shares the corresponding path's initial values and parameter draws but has no plans, rule actions, signals or callback calls.

Public observations use history at or before `period-releaseLagPeriods`; own private nodes use current available history, and rivals' private nodes never appear. A raw value map is accepted only as a period-zero snapshot. Later observations require dated history so unreleased current truth cannot substitute for an absent release. Observations omit free-form research text, source passages, actor names/bases, assessments, scenario identifiers/labels/probabilities and other actors' plans. Only typed objective/control data is exposed.

`cancel_check()` is called before paths, periods, callbacks and sensitivity work. A truthy return raises `SimulationCancelled`; hook-raised exceptions propagate. A cancelled call returns no partial success record. Replay metadata includes per-path seeds, structural/decision/output hashes and the explicit requirement to replay the same callback outputs; arbitrary nondeterministic callbacks cannot be made deterministic by an RNG seed.

Sensitivity is a bounded structural endpoint contrast on each primitive-node range and scalar-parameter range with all other draws fixed to the first path and actors disabled. Signposts include terminal ranges, target settlement release date, earliest planned effects and actor trigger predicates with model dates. Neither sensitivity nor simulation shares are promoted into evidence-only forecast authority.

## Progress and corrections

- 2026-10-27: Implemented compiler, actor boundary and closed-loop runtime. Added cancellation and fixed-repository bridge loading after coordinator integration guidance. The macOS audit runner needs `/private/tmp/...`, because `/tmp` is a symlink; the earlier shorthand in this document is superseded.
- 2026-10-27: Corrected a potential commitment `condition=None` observation crash, validated callback identifiers before dictionary lookup, prevented direct rule actions from overriding pending plans, and moved credibility scoring after final-period propagation. These corrections are undergoing scenario verification.
- 2026-10-27: Guarded initial import/admission smoke passed (1 selected test), evidence `/private/tmp/drf-target-runtime-smoke-20261027-01`. This is not runtime scenario acceptance. Test worker resumed after a connection failure before its first file save; independent runtime review is active.

## Independent review and acceptance progress

- The first runtime gate failed six tests before runtime execution because the synthetic verified claim text did not exactly appear in its source passage. The fixture was repaired without weakening core provenance validation.
- The next gate passed 23 scenarios (`/private/tmp/drf-target-runtime-20261027-04`). A subsequent expanded gate passed 50 scenarios (`/private/tmp/drf-target-runtime-20261027-05`), including delayed public releases, private-node exclusion, detached one-argument callbacks, exact-value independent consent and stale/forged consent rejection, rising triggers, signal recipient isolation and scoring delays, persistent plans and commitments.
- Independent runtime review identified three source-traced defects: infeasible sibling proposals vetoed valid writes through the conflict set; `{}` was accepted as an unconditional commitment predicate; and an infeasible sensitivity endpoint aborted valid fixed paths. The first two are now covered in the expanded green gate. Feasibility now filters the conflict set using the common starting state, then rechecks cumulative budgets at application. Every non-None condition is validated. Sensitivity retains completed paths and marks infeasible endpoints explicitly with null endpoint/delta values. Only mechanism validation exceptions are converted to diagnostic findings; cancellation hook exceptions propagate.
- Additional guardrails preview downstream mechanism constraints before accepting a lever edit and revalidate lagged effects at maturity. A newly infeasible delayed effect is blocked, its reserved capacity is refunded and its earlier irreversible direction is restored. Delayed plans transition to applied when their effects mature. Baselines carry no active plans. Actor loops now receive an explicit allowlisted decision case with assessments, scenario classifiers and research prose removed before entry.
- The production consumer smoke (`/private/tmp/drf-target-runtime-consumer-20261027-03`) reached runtime and report generation, then failed in the coordinator-owned report progress-callback arity. This is reported upstream, not repaired outside the ownership set. It is not recorded as a full-pipeline pass.

Final frozen-source acceptance, backend-only import, adversarial validation and review closure are still pending at this point in the record.

- 2026-10-27: Gate06 passed 69 scenarios (`/private/tmp/drf-target-runtime-20261027-06`), including matched no-decision baselines, exact callback-tape replay, causal signal/credibility counterfactuals, unchanged paths and observations after research-weight/label mutations, cancellation between callbacks and backend-only bridge import. Receipts for gates04–06 show exit zero, completed shutdown, preserved identity, no source drift in runner-tracked sources and no recorded blocked-operation attempts. Runtime sources will additionally be hashed around the final gate because the runner does not automatically register every imported pure module.
- 2026-10-27: Independent reviewer rechecked all three fixes and found no remaining concrete blocker; its own 50-scenario run passed at `/private/tmp/target-runtime-review-20261027-r1-1d2a8c76`. This source review does not by itself count the later edge scenarios as passed.

Terminal classification uses the supplied inequalities (inclusive `between`) without renormalization. The `other` scenario ID is reserved for unmatched mass. Predicates on different nodes are conservatively rejected because this single-predicate grammar cannot prove their regions disjoint; adjacent strict/non-strict bounds on the same node are supported. An infeasible sensitivity endpoint is explicitly `status="infeasible_endpoint"`, with that endpoint and delta null; a finite-endpoint difference exceeding finite float range is `nonfinite_contrast`. These are diagnostic findings, not repaired parameter draws.


## Final scoped acceptance (2026-10-27)

The final frozen-source gate passed **86 tests, zero failures, zero errors, zero skips**, in 2.14 seconds. The exact invocation from `/Users/rogerlin/.codex/worktrees/target-first-forecast/DeepResearchForecast` was:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-target-runtime-final-20261027-07 -q backend/tests/test_target_simulation.py
```

Evidence: [completion receipt](/private/tmp/drf-target-runtime-final-20261027-07/completed.json), [JUnit](/private/tmp/drf-target-runtime-final-20261027-07/junit.xml), [before/after source manifest](/private/tmp/drf-target-runtime-final-20261027-07/source-manifest.json). The receipt reports completed shutdown, preserved identity, no recorded blocked-operation attempts and no runner-tracked source drift. Explicit hashes of all three runtime modules, the test module, core validator, bridge loader and runner also remained identical before and after the gate. The audit boundary is CPython hooks, not an OS sandbox.

| Owned source | SHA-256 |
|---|---|
| `backend/app/services/target_simulation.py` | `45c91699e17c697973e25b5e78a5bdc88f5aff34a05905077c418da6e39fda40` |
| `backend/app/services/target_actors.py` | `4f4e2d5d08c0da4d345b4c3d9f18fd0fd08ef548d40c725c5a46d4e20b80a35e` |
| `backend/app/services/target_mechanisms.py` | `3aac75a39dc519532f5e485ac92b0319ffdb9bd1e0deaf54863f9c0320e58260` |
| `backend/tests/test_target_simulation.py` | `8fcbdfd0c9d042902d786e6357ab2fba4fba7f014e7ebee5e6fd22985566df1c` |

The independent review closed all three concrete findings at these runtime source hashes. Its final expanded run passed 82 tests before the final four whitelist/date checks were added: `/private/tmp/target-runtime-review-20261027-r2-f84c39a1/`. The final 86-test gate additionally proves rejected arbitrary expressions/extra parameters/coefficient mismatch and exact target release/plan-effect dates. Invalid DAGs, duplicate writers, unresolved references, overlapping predicates and nonfinite numbers fail before callback invocation. Infeasible adoption sensitivity and delayed-effect capacity refund tests pass.

Only five paths were created by this ownership group: the three runtime modules, `backend/tests/test_target_simulation.py`, and this report. All remain unstaged/uncommitted per explicit instruction. No coordinator handoff, core validator, primary checkout, unrelated edits, services or providers were changed by this group. No commits or pushes were made.

## Remaining integration and model limits

There is no remaining runtime acceptance item in this assigned slice. The earlier full-consumer smoke failed at the separately owned report progress-callback arity; this group did not fix it or claim complete pipeline acceptance. Coordinator/report/core owners retain their wider integration gates.

The implemented templates are bounded structural assumptions, not calibrated domain models. No model provider, live service, empirical forecasting lift or prospective outcome gate was exercised. Simulation weight remains exactly zero. Numeric initial values are fixed; uncertainty requires null-valued bounded nodes or parameter priors. Same-period consent must be supplied independently by each required counterparty; free-text negotiations, coalitions, offer matching and automatic consent-request transport are not implemented by this contract. The default rule controller acts only on directly matching objectives; discretionary policy is the optional safe callback. Signal score is a normalized numeric error, not a probabilistic Brier score. No stochastic hazard-time process is implied by per-path bounded draws. Callback reproducibility requires the same callback response tape. Cancellation is checked between units of runtime work and callbacks; it cannot preempt a callback while that callback is executing.

Next-session prompt: Read this report and the frozen contracts. Preserve the five scoped source hashes above while integrating the coordinator's pipeline/report path. Re-run the guarded 86-test suite after any runtime edits, and obtain a separate producer-to-report receipt after the coordinator's report progress-callback issue is repaired. Keep provider realism and forecast-quality claims separate from offline structural acceptance.

- 2026-10-27: Final scoped acceptance recorded; all runtime review findings closed; final 86-test gate and unchanged source hashes captured. Ownership preserved and no publication/service actions performed.

## Part 2 extension brief (2026-10-27)

Status: In progress under explicit part-2 authorization. The ownership set remains the same five files; prior acceptance is preserved above as historical evidence. No core case-schema change is proposed: calculator/identity controls, intervention/conditioning requests, model validation and supplied hindcast snapshots are optional runtime inputs.

The bounded plan is to add actor-visible one-step options, opaque callback identifiers with an explicit named-ID placebo, paired structural interventions and observational conditioning tables, optional dimensional/seed checks, and dated supplied-snapshot hindcast diagnostics. Acceptance must prove hidden-state invariance of calculator output, safe identity round trips, paired-draw differences, observational selection without mutation, explicit infeasible/empty cases, unit and identity rejection, and historical-cutoff rejection. No historical episodes will be invented; synthetic fixtures establish validator behavior only. No probability promotion or new provider is authorized.

The compiler owner extends only `target_mechanisms.py`; the test owner extends only `test_target_simulation.py`; the runtime owner extends `target_actors.py`, `target_simulation.py` and this record. API coordination: `run_paths` keeps all existing parameters and adds optional `lookahead`, `identity_mode`, `interventions`, `conditions`, `model_validation`, `hindcast_snapshots`. Callback default identities become opaque as explicitly requested; `identity_mode="named"` preserves declared-ID callback compatibility for placebo/legacy use. Public `actor_observation` preserves named-ID defaults and accepts the optional calculator/identity controls. Human name/source fields remain excluded in both modes.

### Supplied specimen receipts and factual vintage rows

The user explicitly authorized read-only inspection of the primary saved specimen. The following SHA-256 values were captured before the extension tests; the files are not test inputs and will be rehashed to prove preservation. Guarded tests use only the minimal copied numbers in the owned test file, not primary uploads.

| Saved file under `backend/uploads/pipelines/pipe_9d9b84efcd3d/handoff/` | SHA-256 |
|---|---|
| `sources.json` | `d8d0cfaa5df86f09e5afad4f2d890c3c154c2c61269dbc3a20bd6bf80551931f` |
| `quantitative.json` | `356257872ffbde3c86e61834321f8513d1838ad4e696e8bff4e0b525a9de4187` |
| `v3/plan.json` | `18a707aa56f79e5f0a0f1ebdecb80a22e6a1fd279332e6909864a4cf952b7395` |

The two source records have `date=null` in their saved metadata. Publication dates below come from explicit press-release datelines in the fetched excerpts, not retrieval dates. Both are Gartner publisher documents even though the old pipeline classified them generically as tier S3. No source text or metadata was rewritten.

| Source row / publication date | Reference year | USD billion | Factual type | Published growth |
|---|---|---:|---|---|
| `sources[22]`, 2024-08-28 | 2024 | 183.9 | Publisher estimate | — |
| `sources[22]`, 2024-08-28 | 2025 | 212 | Publisher forecast | 15.1% |
| `sources[0]`, 2025-07-29 | 2024 | 193 | Later publisher estimate | — |
| `sources[0]`, 2025-07-29 | 2025 | 213 | Publisher forecast | — |
| `sources[0]`, 2025-07-29 | 2026 | 240 | Publisher forecast | 12.5% |

The original source IDs are `src_dbcf16fe0a8df481` and `src_6d9b82fe4fcd5b60`. Their recorded fetched-content hashes are respectively `12ed4e3cf3c903e3a4af2d11a414c7a67166c76c47a32a7a40e94a134ffbe6ae` and `26232adfbbb91a49d4f46cc5fffc313aac06396fc410ed3db19648e7488ab7d7`.

These rows support **publisher-vintage arithmetic consistency**: `183.9 × 1.151 = 211.6689` versus published rounded 212, and `213 × 1.125 = 239.625` versus published rounded 240. A 0.5-billion tolerance is an explicit rounding allowance, not an uncertainty interval or accuracy claim. The 2024 estimate changed from 183.9 to 193 across vintages; neither row is treated as a settled outcome. The later 247.5-billion number in the saved quantitative file is from an Elisity secondary estimate/forecast and is excluded from primary-observation validation. Repeating 12.5% growth from the 240-billion 2026 forecast to produce a 270-billion 2027 baseline is an explicit extrapolation assumption, not a Gartner 2027 forecast.

The question in the saved plan targets industry evolution through end-2027. The no-decision 2027 baseline and declared-rate intervention will exercise causal accounting for that target; no realized 2027 observation, historical actor-policy validation or prospective forecast skill is available from these rows.

### Frozen runtime wire clarification for coordinator/report owner

No callback observation or opaque identity metadata is inserted into decision rows. Decision rows always require `period`, `actorId`, `status`, `reason`. Optional typed fields are `kind`, `leverId`, `value`, `nodeId`, `duePeriod`, `planId`, and (for an accepted current/delayed lever proposal) **`effectivePeriod`, `cost`, `remainingCapacity`**. These last three fields predate part 2 and must be admitted explicitly by the report consumer rather than accepting arbitrary fields. Lag-maturity rows retain only the ordinary `_record` fields.

Every runtime path has exactly `pathId`, `seed`, `parameters`, `initialValues`, `trajectory`, `decisions`, `plans`, `pendingEffects`, `signals`, `credibility`, `remainingCapacity`, `targetValue`. `trajectory` rows are `{period, values}`. `plans` maps actor IDs to typed plan rows plus `status`. `pendingEffects` rows contain typed lever action fields (`kind`, `actorId`, `leverId`, `value`, optional `consents`/`planId`) plus `effectivePeriod`, `reservedCost`, `previousDirection`. Signal rows contain `actorId`, `nodeId`, `value`, `recipients`, `period`, `duePeriod`, `resolved`, and after scoring `score`, `resolvedPeriod`. These are records, not additional numeric forecast authority.

Part-2 `replay` adds only `identityMode` (opaque|named) and `lookahead` (boolean). All other replay fields retain their earlier meanings. Optional root additions are `modelValidation`, `interventionTables`, `conditionalTables`, `hindcastValidation`; none belongs in decision rows or unconditional probabilities. Callback-only `options` and opaque identifiers are decoded before runtime actions enter the record. The coordinator owns any edit to `contracts.md`; this report freezes the mechanism-owner interface without touching shared contracts. Integration04's strict decision allowlist omission was reported by the coordinator and is not ignored or bypassed.

### Part 2 acceptance progress and integration findings

The first expanded gate passed 96 tests and found one cancellation-hook exception misclassification: a caller-raised `MechanismValidationError` at a sensitivity checkpoint was mistaken for an infeasible model endpoint. The cancellation boundary now preserves the exact caller exception through field-repair handlers; the all-checkpoints regression passes.

Gate03 passed 118 tests, including publisher-vintage consistency, private lookahead, opaque references, paired interventions, conditional subsets, unit/seed checks and the eight-actor LLM roster cap. Two actual report-consumer tests still failed at that point: the growth fixture needed its typed binary probability synchronized with its amended assessment; the linear consumer still compared flattened runtime coefficients against case-level parameter keys. The fixture correction is local. The production linear allowlist correction belongs to the report owner and has been reported, not bypassed. Tests call actual `build_target_report` and `register_comparison`; they do not substitute a fake consumer.

The publisher-vintage snapshot now uses a separate `model` envelope (`asOf`, `horizon`, `targetNodeId`, `nodes`, `mechanisms`, `sources`). It is deliberately not an archived `forecast-case/v1`: the saved document was actually retrieved in 2026, so relabelling that retrieval as 2024/2025 would fabricate point-in-time evidence. Model source publication and node vintage must precede the publication-era cutoff; actual retrieval must precede the evaluation cutoff. The realized-outcome branch continues to require a core-validated archived `case`, with retrieval available by its own historical cutoff and a post-horizon realized observation. Both branches keep prospective skill unmeasured.

Cost boundary: cases with more than eight `decisionRule.kind="llm"` actors are rejected before callbacks. The coordinator owns the per-run `target_decision_budget_v1 {max_calls:128}` capped/cached closure and its explicit depletion diagnostics. Empty callback actions are hold. The runtime does not create another provider client or global provider switch. Offline callback counts are process-contract evidence, not measured live-token/cost savings.

### Part 2 API and semantic freeze

Public runtime signature adds optional keyword arguments:

```python
run_paths(case, *, paths=32, periods=12, seed=0, decision_provider=None,
          cancel_check=None, lookahead=False, identity_mode="opaque",
          interventions=None, conditions=None, model_validation="off",
          hindcast_snapshots=None)
actor_observation(case, state, actor_id, *, period=0,
                  lookahead=False, identity_mode="named")
validate_hindcasts(case, snapshots, *, paths=32, periods=12,
                   seed=0, cancel_check=None)
```

Opaque callback identity is the new explicit default; names, decision-basis prose, source IDs/passages and scenario content never enter either identity mode. All actor/node/lever/plan references, including keys in numeric maps and nested consent/signal/condition references, are reversible opaque tokens. Records retain declared identities. Named mode preserves declared IDs for the requested placebo and existing callback clients; it does not add human-name fields. Public observation keeps its earlier named-ID default for compatibility.

`lookahead=True` adds `options` for each own lever's minimum, observed current value and maximum. Each option contains a typed action, evaluation/effect periods, consent requirements, information/parameter basis, preliminary feasibility status, visible objective/baseline values, objective deltas and a normalized directional score. The one-step projection uses only the actor's visible belief values and **declared prior midpoints**, never true path draws or rival-private seeds. Computed outputs must themselves be in the visible supplied domain; unobserved zero-input milestones cannot reconstruct a private rival state. Missing visible dependencies produce `unavailable`; observed budget failure produces `blocked`; lags beyond one step produce unchanged one-step predictions with an explicit lag reason. Consent and complete feasibility remain runtime checks, not promises made by the calculator.

`interventions` accepts at most 32 `{interventionId, settings}` rows, each with 1–16 `{actorId, leverId, value, period?}` settings. Settings must reference declared levers, respect their bounds, use a requested period within the run, and cannot collide on a node/effective period. The table uses each baseline's exact initial and parameter draws and honors lever lags, with actor policies disabled. It is labelled `intervention`, `structural_do_under_declared_equations`, and `feasibility: not_assessed` because forced do-settings do not establish consent, capacity or strategic response. Model-infeasible paths remain explicit; their mass is not dropped and renormalized. `conditions` accepts `{conditionId,predicate,period?}` rows and selects from the already-produced factual paths. Its table is explicitly `observational_conditioning`, with no causal interpretation; empty subsets produce null summaries/shares. Neither table invokes a callback or changes unconditional forecast authority.

`model_validation` is off, diagnostic or strict. The compiler exposes `validate_model(case, strict=False, seed_tolerance=1e-8)` and records dimension/scale checks and local period-zero seed checks. Unit vocabulary is deliberately bounded: fraction/ratio/1/dimensionless; percent/%; unit/units/count/counts; USD/EUR/CNY; million/billion scale modifiers; explicit `*`, `/` and parentheses. No implicit products, powers, arbitrary unit names or expression evaluation are accepted. Scales are exact rational values: a percent is not a fraction, and USD million is not USD billion. Linear coefficients are dimensionless and intercepts inherit output units. Unsupported units and inconsistent fixed seeds fail strict mode. Missing output/input seeds or uncertain parameter priors remain explicitly unmeasured; midpoint values are never fabricated as seed evidence. Seed tolerance is absolute, not relative.

Each optional hindcast snapshot declares `snapshotId`, `kind`, `evidenceKind`, a dated `model` (publisher consistency) or core-validated `case` (realized outcome), `comparison`, optional nonnegative `tolerance` and optional `sourceReceipt`. The comparison carries target node/value, value kind, reference date, publication date and source identity/URL/title. Publisher comparisons must have been published **by the model's own cutoff**, preventing later revisions from masquerading as earlier-vintage consistency. The source receipt carries path/hash/rowIndex but causes no file read. Publisher source acquisition date 2026-10-27 in the copied fixture is this session's saved-artifact inspection date; the original web retrieval timestamp is unknown and is not invented. The standalone validator is bounded to 12 supplied snapshots, 256 paths and 120 periods, runs no actor policies or callbacks, and reports arithmetic/range consistency separately from unmeasured prospective skill. Retrospective diagnostics should be kept separate from outcome-free forward preregistration; this runtime does not relax the report owner's enrollment integrity gate.

The new publisher comparison-cutoff regression closes the independent reviewer’s part-2 P1 finding. The scoped Ruff F/E9 gate initially found only `visible_nodes` imported but unused; that import was removed without touching peer files.


## Part 2 frozen-source result (2026-10-27)

The final owned-source acceptance command was:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-target-part2-final-20261027-06 -q backend/tests/test_target_simulation.py
```

Result: **127 passed, 1 failed, 0 errors, 0 skips**, 128 collected (42 more than the part-1 gate). The sole failure is `test_actual_runtime_output_reaches_strict_report_and_registration[linear]`: `target_report._validate_paths` rejects compiled `coefficient:<nodeId>` fields because it compares them to the case-level `coefficients` key. Growth passes through both the real report producer and immutable comparison registration. This is not an all-green integration result; the report owner's correction and coordinator combined gate remain required. The report consumer should use the compiler's exact scalar keys/bounds (`compile_model(case).parameter_bounds`) rather than broadly allowing arbitrary outcome-bearing fields.

Evidence: [completed receipt](/private/tmp/drf-target-part2-final-20261027-06/completed.json), [JUnit](/private/tmp/drf-target-part2-final-20261027-06/junit.xml), [source manifest](/private/tmp/drf-target-part2-final-20261027-06/source-manifest.json). The guard recorded completed shutdown, preserved identity and no blocked-operation attempts. Explicit before/after hashes confirm the four owned Python files were unchanged. The concurrently owned `target_report.py` changed during the final run, so that dependency is explicitly marked drifted and must be rehashed in the coordinator's combined gate. No other measured dependency drifted.

Ruff passed with `/Users/rogerlin/.pyenv/shims/ruff check --no-cache --select F,E9` on only the three owned runtime modules and the owned test module. No peer source was edited to clear lint or the report-consumer failure.

| Frozen owned Python file | SHA-256 |
|---|---|
| `backend/app/services/target_simulation.py` | `de5132b2d2bfdbd98fcd6e7c234d5e049108255289d3122546636afe7b310db8` |
| `backend/app/services/target_actors.py` | `3144e1d7654588716b9ee10fa42cbab0f62d8c0b0af9e50c97f10ea3710c1bd6` |
| `backend/app/services/target_mechanisms.py` | `3c2c801f41f51acbe726ea85e6bc8f31228e5bda577c9b59a96545bf7046bce4` |
| `backend/tests/test_target_simulation.py` | `73e06b2d884c3520cb9d18e5b986abfbba46e9db4d2e1a4914cc62a424f6cec0` |

All three user-designated primary saved files were rehashed and exactly match the initial receipt: `sources.json`, `quantitative.json`, `v3/plan.json`. The copied publisher rows pass both vintage arithmetic checks within the explicit 0.5-billion rounding tolerance. The source-linked 2027 diagnostic baseline is 270 billion under the stated repeated-12.5% assumption; the same-draw 15% lever intervention is 276 billion, a 6-billion structural difference. These numbers are not a fresh publisher forecast, observed outcome, policy-feasible prediction, or measured skill improvement.

Additional acceptance covers default opaque references and named-ID placebo, all nested signal/consent/plan identity round trips, rejected raw named references, visible-belief midpoint lookahead, hidden primitive and hidden computed rival invariance, capacity/lag option disclosure, paired do-settings versus noncausal path conditioning, empty and model-infeasible subsets, unit/scale and seed checks, publisher/model versus realized/archive admission, later-vintage rejection, callback exception propagation at every checkpoint, source-linked 2027 accounting, and eight-actor roster admission. The independent reviewer closed its publisher revision-cutoff finding after the targeted fix. Early worker streams disconnected; their saved source was reviewed and integrated locally, not counted as completed verification.

Remaining work is the report-owner linear scalar allowlist correction followed by the coordinator's actual runtime/report/registration combined gate. `contracts.md` remains coordinator-owned; the exact optional API and wire shapes are frozen above for that update. Real-world realized-outcome accuracy, two-to-three historical actor-policy episodes, conditional calibration, prospective lift and live provider/token savings remain **unmeasured**. Only supplied publisher-vintage arithmetic was exercised on real saved facts; the realized-outcome branch's positive case is explicitly synthetic. No probability promotion, model/network provider invocation, service restart, commit or push occurred.

Next-session prompt: Preserve the frozen owned source hashes, update the separately owned report scalar-key validation using compiled parameter bounds, then run the complete owned test file plus coordinator integration tests under the guarded runner. Rehash all peers after the combined gate, keep the saved primary file receipts unchanged, and never describe the publisher-vintage consistency results as realized forecast skill.
