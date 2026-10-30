# Forecast case contract owner

Status: Complete for the assigned core contract slice. Scope was initially only `deerflow_bridge/forecast_case.py`, `backend/tests/test_forecast_case.py`, and this report. The coordinator handoff is not edited.

## Request and acceptance
Implement the stdlib-only finite JSON case boundary, referential/provenance/uncertainty validation, immutable assessment history, deterministic hash and projections, and atomic read/write with replay/tamper checks. Verify valid research-to-simulation/report projection, reject malformed and tampered data, and preserve existing files on rejected updates.

## Plan
1. Validate the complete typed contract and references before exposing projections.
2. Add canonical hashes and atomic persistence with monotone revisions and append-only assessments.
3. Exercise positive and adversarial controls through the existing guarded runner, then request independent review.

## Interface clarifications for consumers
- The eight shared APIs and `CaseValidationError` retain the signatures in contracts.md.
- An unknown leaf (not a mechanism output) must carry explicit `basis: "assumed"` and nonempty `gap` in its node row, and a finite range. These optional node fields supply the required explicit parameter basis missing from the frozen row shape. Derived unknowns use their mechanism's basis/gap.
- Source publication dates stay nullable. No retrieval date is substituted.
- Simulation projection is a structural engine input, not an actor prompt. Actor-specific filtering remains the mechanism owner's responsibility; the projection strips narrative fields and assessment/binary probabilities.
- Tests must use `/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir <fresh canonical /tmp directory> backend/tests/test_forecast_case.py`.

## Constraints and remaining work
No providers, service restarts, commits, pushes, or writes outside the assigned files. This verifies offline contract behavior only, not forecast accuracy or live provider integration. Implementation and validation are in progress.

## Updates
- 2026-10-27: Read request, plan, contracts, handoff and runner before app imports; created scoped continuity report. Confirmed runner requires isolated/no-site/no-bytecode flags.

## Consumer API and validated fixture (2026-10-27)
The shared fixture is now `backend/tests/fixtures/target_case.json` (additional write scope explicitly authorized). `make_case()` in `backend/tests/test_forecast_case.py` returns a fresh copy. It is a synthetic 2027 spending case with base plus four growth contributions (trend, incident shock, regulation, AI), two mechanisms, two lever-owning actors, primary fetched synthetic evidence, prior/posterior ledger and binary predicates. The first guarded contract gate passed **85 tests** in 2.98s; completion receipt `/private/tmp/drf-target-contract-20261027-01/completed.json` records zero blocked events and no source drift.

`report_projection(case)` returns every validated case key plus `caseHash`, `assessment` (deep copy of the latest assessment), and `simulationWeight: 0.0`. `graph_projection(case)` returns `{schemaVersion,caseId,caseHash,nodes,edges}`; node rows have `uuid,name,labels,summary,attributes`, edge rows have `uuid,source_node_uuid,target_node_uuid,name,fact,attributes`. Private nodes/edges are excluded from this shared public graph. `simulation_projection` contains structural case identity, resolution target/horizon/units, numeric node records with visibility/owner, mechanisms, structured actors and unlabeled scenario predicates. It deliberately omits case revision, question, all narrative descriptions, source passages, binary probabilities, assessments and full-case hash so probability-only edits cannot change its bytes. Full-case identity remains available separately via `case_hash`.

Assessment directions are `increase|decrease|unchanged`; `size` is absolute probability change. Every posterior replays from the preceding weights with a valid source/claim evidence reference tied to the updated node. New case content at an existing path requires strictly increasing `revision`; existing assessment rows remain an exact immutable prefix. Scenario/resolution changes require a separately named revision file so historical probabilities are never rebound silently to different definitions. Without an externally pinned expected hash, a valid modified file cannot be authenticated merely from its own contents.

The macOS runner requires a canonical parent: use `/private/tmp/...`, not the `/tmp` symlink. Independent review is in progress; these initial hashes are evidence for the initial gate only.

## Review closure and second gate
Independent read-only review found four concrete issues: a bounded parameter could claim observed provenance while inheriting no sources; date truncation admitted publication after same-day retrieval; colon-concatenated graph edge identifiers could collide; and an exactly maximum-sized canonical payload became unreadable after adding a newline. All four now have regression tests and fixes. Mechanism arity/key validation also matches the mechanism owner's current seven-template library; bounded parameter priors deliberately reject an ignored central `value` key. Source/claim history is immutable on replacement, and verified claims must retain their passage in a fetched supporting source, with primary support for pivotal claims.

Gate command (run from the assigned worktree):

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-target-contract-20261027-02 -q backend/tests/test_forecast_case.py
```

Result: **98 passed in 2.51s**. Receipt: `/private/tmp/drf-target-contract-20261027-02/completed.json`. Exit 0, shutdown complete, no source drift, identity preserved; events were only the expected app-config/logger storage redirects. No blocked/network/process/provider attempts were recorded. This is a CPython audit boundary, not an OS sandbox. Scoped whitespace check passed.

Verified hashes:
- `deerflow_bridge/forecast_case.py`: `45ec49fc93ffa7381cc39cb4035d97cbe73bb4d2e0278615f2f04d0e6689807e`
- `backend/tests/test_forecast_case.py`: `937238df41899d3f4adc3b556566cb136cfaa4e3f721bdb6317c1adb2f376992`
- `backend/tests/fixtures/target_case.json`: `c6f5cf744d627ffd467e90406c39d7e2fee07216af6e7675aa7712fc1f57d35b`

Report/graph schemas above are frozen. No schema expansion for the newly supplied second attachment was made. The source of dated evidence remains the producer's responsibility; validation establishes structure, joins and retained-passage provenance, not external factual truth. Research must update a node's basis when evidence changes an explicit assumption into an observed estimate; the validator preserves supplied basis rather than fabricating it. A full engine projection contains private numeric state and is explicitly not an actor prompt. The mechanism owner's actor boundary must filter it per actor.


## Final completion — 2026-10-27
The final narrow review finding was UTC conversion overflow at Python's supported datetime boundaries. `_date` now translates both ValueError and OverflowError into CaseValidationError, with lower/upper bound regressions. Independent reviewer Lovelace confirmed all five findings closed by source review of the final implementation and test hashes. No unresolved core findings remain.

Final command:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-target-contract-20261027-03 -q backend/tests/test_forecast_case.py
```

**100 passed in 1.51s.** Final receipt: `/private/tmp/drf-target-contract-20261027-03/completed.json`; JUnit: `/private/tmp/drf-target-contract-20261027-03/junit.xml`. Exit 0; shutdown complete; source drift empty; identity preserved; no blocked or network/process events. Only app-config/logger storage redirects were recorded. The exact tested source was rehashed after the run. The fixture remained byte-identical across all three parent gates.

Final source hashes (supersede earlier gate hashes):
- `deerflow_bridge/forecast_case.py`: `ac02f61c36a8c3ece19686d32d0a8042806a3f993a99b12567dc3607525dc84d`
- `backend/tests/test_forecast_case.py`: `e1a0881f78f9ecb797cc2f4de1b230570dc5b5ad4b8e6dafe4db3ad59cfaf2ba`
- `backend/tests/fixtures/target_case.json`: `c6f5cf744d627ffd467e90406c39d7e2fee07216af6e7675aa7712fc1f57d35b`

Exactly four assigned paths were created/edited: the three paths above and `docs/handoff/target-first-forecast/contract-owner.md`. The additional fixture path was explicitly authorized after the initial assignment. No coordinator handoff or other owner's code was edited; no providers, services, commits, or pushes were invoked. Existing unrelated worktree edits are preserved. No second-attachment schema changes were attempted.

Handoff to coordinator: use the frozen report/graph schemas and `make_case()` fixture; retain the explicit actor-specific privacy boundary and externally pinned case hashes. Integration and second-attachment follow-up remain coordinator-owned. This completion establishes the exercised offline contract only, not live-provider quality, production publication, or prospective forecasting lift.

## F6 explicit legacy-adapter extension — 2026-10-27 (in progress)
The coordinator authorized optional `binary.resolution_contract`, `binary.scenario_membership`, and `node.resolution_contract` for the part-two estimator integration. These exact snake_case names are an explicit legacy forecast adapter exception to the lowerCamelCase core convention; no aliases are silently synthesized. Resolution contracts discriminate named_source_event, official_data, and polymarket. Core validation checks structural types, finite numbers, and references only; detailed source/market/series equivalence validation remains with the existing extractor validators. Driver binaries with no explicit contract must remain absent/unanchored rather than inheriting the target settlement.

Plan: inspect existing adapter validators; coordinate with Boyle (`01a17ccc-f33b-7603-ba10-a770e75835f4`); admit only the three requested optional fields; verify preservation, malformed controls, absence/no-inheritance, fixture stability and probability-isolated simulation projection under the guarded runner; request narrow independent review.
