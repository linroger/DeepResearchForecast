> Final status note: The final implementation, independent review and subsequent linear-fixture closure below supersede the initial read-only status.

# Mechanism and research slice audit

**Last updated:** 2026-10-28T05:43:05Z. **Status:** Owned implementation and focused verification complete. Parent integration and composed acceptance are tracked by the coordinator.

This review covers slices 3 (C8/C11), 5 (B1), 6 (A4/C3), 9 (C1/C5/C6), 10 (G4/D1), and A3. The initial authority is commit `5b9b92157b8a5699c6e702cd8e3e3766eaadf02a` in the isolated first-ten-remedies worktree. The coordinator independently verified all 537 delivered manifest entries. The original read-only assignment was expanded explicitly to implement MR-1/MR-2 in the four source files and one test module listed below. No unowned file was edited by this reviewer. Deployment files, saved runs, providers, services and the scheduler remain outside the work. Parent-owned pipeline/report/API wiring and their fixture repairs are separate changes.

## Reproduced baseline findings

The source line references in this section refer to the initial baseline. Both findings were reproduced before implementation; their fixes and current file hashes appear below.

### MR-1 — Dimensional and seed-identity checks have no production admission consumer (P1)

Slice B1 explicitly requires consistent units and current-value identities. The implementation has those checks in `backend/app/services/target_mechanisms.py:610`, but its docstring says compilation does not invoke them. `deerflow_bridge/target_research.py:321` admits the case through the schema validator alone. `backend/app/services/target_pipeline.py:25` accepts only paths/periods/seed, and its actual run call at line 465 supplies no `model_validation`. `backend/app/services/target_simulation.py:525` defaults this argument to `off`; only lines 555–557 invoke validation. The final report at `backend/app/services/target_report.py:182` also only schema-validates the case and checks paths through the compiler. A dimensionally invalid model therefore reaches the ordinary report consumer without a validation result.

This is not a missing compiler implementation. Existing `backend/tests/test_target_simulation.py:1322` explicitly proves strict validation rejects a bad identity while the default runtime accepts it. `:1345` proves million-versus-billion and currency mismatches are detectable. The missing behavior is admission/consumption on the real route. A narrow correction should validate supported dimensions and seed identities at typed case admission, distinguish missing evidence/unsupported units from known contradictions, and bind any diagnostic policy in persisted inputs. Do not globally flip unrelated legacy behavior or discard valid evidence merely because a unit cannot yet be parsed.

### MR-2 — Settlement scenarios can classify an unrelated node (P2)

`deerflow_bridge/forecast_case.py:475–486` validates references and overlap but does not require scenario predicates to reference `resolution.targetNodeId`. `backend/app/services/target_actors.py:57–83` repeats the same rule. `_shares` in `backend/app/services/target_simulation.py:457` classifies whatever node the scenario references, while `targetValue` and the target summary independently use the settlement target. `backend/app/services/target_report.py:143–146` explicitly admits both the arbitrary scenario node and the target, and lines 168–171 only recheck the same classification. Thus a malformed planner case can publish scenario diagnostics unrelated to the declared target, contrary to slice A4/C3's target-distribution requirement.

The bounded reproduction below changes the scenario predicates' node references from spending to trend in the existing fixture. The spending target is above 280, but all paths classify as “Below 280” because trend is below 280. Schema admission and the runtime accepted this. The initial report attempt correctly rejected the driver binaries for missing settlement contracts; the extended reproduction supplied explicit driver contracts and then passed through the report, distinguishing that separate gate from target binding. The legacy reducer already enforced the intended invariant in `backend/app/services/worldstate.py:180–191`, making the discrepancy with the target-first route concrete. The correction binds settlement scenarios to the resolution target at case admission. Driver conditions remain supported as binaries, triggers, and conditional-table predicates.

## Historical bounded reproduction

The following examples ran the actual schema validator, runtime, and report consumer with a copied, synthetic repository fixture before fixes. A passing transcript means the original defects were reproduced, not fixed. The second guarded run passed in 1.35 seconds. This is a historical transcript, not the post-fix acceptance command; use the test module below for current verification. No fixture was altered and no provider was called. The exact historical command was:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-mechanism-review-20261028-02 --doctest-glob=mechanism-review.md docs/handoff/first-ten-remedies/mechanism-review.md
```

```pycon
>>> import json
>>> from copy import deepcopy
>>> from pathlib import Path
>>> from deerflow_bridge.forecast_case import validate_case
>>> from app.services.target_mechanisms import validate_model
>>> from app.services.target_simulation import run_paths
>>> from app.services.target_report import build_target_report
>>> fixture = json.loads(Path('backend/tests/fixtures/target_case.json').read_text())
>>> case = deepcopy(fixture)
>>> case['actors'] = []
>>> private = next(n for n in case['nodes'] if n['nodeId'] == 'ai')
>>> private['visibility'] = 'public'
>>> _ = private.pop('ownerActorId')
>>> dimensional = deepcopy(case)
>>> next(n for n in dimensional['nodes'] if n['nodeId'] == 'base')['units'] = 'USD million'
>>> _ = validate_case(dimensional)
>>> validate_model(dimensional)['status']
'failed'
>>> simulation = run_paths(dimensional, paths=1, periods=1, seed=0)
>>> 'modelValidation' in simulation
False
>>> round(simulation['paths'][0]['targetValue'], 2)
282.5
>>> report = build_target_report(dimensional, simulation)
>>> bool(report['forecast'])
True
>>> wrong_target = deepcopy(case)
>>> for scenario in wrong_target['scenarios']:
...     scenario['predicate']['nodeId'] = 'trend'
>>> for scenario in wrong_target['scenarios']:
...     wrong_target['binaries'].append({'binaryId': 'driver-' + scenario['scenarioId'], 'question': 'Synthetic trend predicate ' + scenario['scenarioId'], 'predicate': deepcopy(scenario['predicate']), 'probability': wrong_target['assessments'][-1]['scenarioWeights'][scenario['scenarioId']], 'sourceIds': ['S1'], 'resolution_contract': {'kind': 'named_source_event', 'publisher': 'Synthetic statistics', 'event': 'Reported trend growth ' + scenario['predicate']['operator'] + ' 280 fraction', 'deadline': '2027-12-31'}})
>>> _ = validate_case(wrong_target)
>>> simulation = run_paths(wrong_target, paths=1, periods=1, seed=0)
>>> round(simulation['paths'][0]['targetValue'], 2), simulation['scenarioShares']
(282.5, {'below': 1.0, 'above': 0.0, 'other': 0.0})
>>> report = build_target_report(wrong_target, simulation)
>>> bool(report['forecast'])
True

```

## Slice disposition

| Slice | Disposition and producer → consumer evidence | Acceptance boundary |
|---|---|---|
| A3 | Delivered. `worldstate.py:195` seals explicit uniform/research policy; `pipeline_orchestrator.py:14568` uses it for new legacy preparation. The independent route strips assessments in `forecast_case.py:663` and `target_simulation.py:84`. `simulation_record.py:935` labels the prior. | Fresh affected checks pass: `test_world_state_seed_prior.py:26,42,49`; full target runtime includes probability/label independence at `test_target_simulation.py:692`. Policy-free saved seeds retain old semantics. |
| 3, C8/C11 | Delivered in the legacy kernel: public-only arbiter inputs (`world_update.py:114`); field/round repair and raw capture (`:679,:865`); separate delivery attempts, capacity admission and lag; term-based obligations and batched grace-period breaches (`world_model.py:2606`); red lines first (`:2799`); dedicated JSON decision system prompt (`agent_decision.py:609`). | Existing source tests include `test_target_legacy_integrity.py:53,73,217,309,353,395,424,451,517`. Exact saved-specimen zero-failed-round replay and both specimen breach reclassifications have not been performed in this assignment. Those are missing artifact-specific offline acceptance, not proof that the implementation is absent and not empirical forecast-skill claims. |
| 5, B1 | Equivalent alternate architecture delivered: `target_research.py:595` plans the typed case; `:438` derives node-specific questions and `:637` gathers typed findings; `:673` prioritizes unresolved gaps; `:689` binds mechanisms; `:751` persists `forecast_case.json`. The case replaces separate `tree.json` and prose reconstruction. MR-1 identified a real validation-consumer gap despite this architecture. | New `admit_model` and admission runtime tests close the owned validation gap. Parent wires production case/report admission. Node IDs occur in target research questions/why and findings; a second legacy tree/flag implementation is unnecessary. The coordinator owns fresh producer acceptance. |
| 6, A4/C3 | Delivered target DAG and terminal predicate shares (`target_simulation.py:227,457`), plus legacy derived-write guards (`world_model.py:1234`, `world_update.py:382`). Unknown outcome power and failed resolutions freeze/zero contributions (`worldstate.py:359`). MR-2 repaired target binding at the schema and defensive runtime boundary. | Fresh `test_world_share_sources.py` passes including unanimous opposing votes, missing power, rollback and actual loop scenarios; the full core/runtime compatibility suites pass. |
| 9, C1/C5/C6 | Equivalent alternate architecture delivered: whitelist compiler, lever-only cast admission (`forecast_case.py:526`), private dated observations (`target_actors.py:94`), cumulative capacity/consent/lag (`target_simulation.py:194`), persistent plans, cadence, triggers and signals (`:270`). It does not require the legacy agency-class catalogue to act as the structural model. | Full runtime tests pass, including lag, capacity, consent, private observations, hidden-input invariance, plans, seeded replay and paired interventions. Literal reclassification of the supplied specimen and measured 5–10× decision-call reduction have not been established. Live actor realism and prospective lift remain empirical gates. |
| 10, G4/D1 | Equivalent alternate architecture delivered: authoritative typed case, graph projection (`forecast_case.py:696`) carrying node source IDs/vintages; deterministic pipeline graph (`target_pipeline.py`, graph stage); receipt/owner-checked graph API (`api/graph.py:134`). The report consumes the typed case directly rather than retrieving facts through a prose graph. | Existing source tests `test_forecast_case.py:195`, `test_target_ui_api.py:78,145,185` and coordinator pipeline/UI evidence cover the alternate consumer route. The literal specimen under-one-minute graph benchmark was not rerun. No Graphiti rewrite is justified by these findings. |

## Implementation and integration contract

1. `target_mechanisms.admit_model(case)` is pure and returns `policy: known-contradictions/v1`, `dimensionChecks`, `seedChecks`, and a truthful overall status: `passed`, `unmeasured`, or `unsupported`. Every known failed check raises `MechanismValidationError`. A missing seed or unsupported unit is retained explicitly, never promoted to a passed check. An unsupported unit cannot hide a separately provable dimensional mismatch within a growth or additive equation, or an independent seed contradiction.
2. `run_paths(..., model_validation="admission")` checks before actor callbacks and stores the result as `modelValidation`. The explicit `off`, `diagnostic`, and `strict` APIs retain their documented controlled-experiment behavior. This is an additive hook, not a global legacy default change.
3. `forecast_case.validate_case` rejects settlement scenarios on any node other than `resolution.targetNodeId`. `target_actors.validate_scenarios` independently enforces the rule when a resolution is supplied. Legacy reducers already prebind the target and still work. Binaries, trigger conditions, plan conditions, and conditional-table predicates may reference drivers.
4. Parent-owned integration calls `admit_model` immediately after reading the frozen case, before evidence/library/publication work; executes with admission mode; and recomputes validation in `build_target_report`, including `simulation=None`. A new-policy simulation receipt must equal recomputation. No new `target_input` key or user-controlled bypass is needed: the current case hash/full structural projection bind the deterministic input, and the receipt names the fixed policy. Existing saved JSON is not rewritten. Existing valid saved simulations without receipts can be read after case revalidation. Historical contradictory models now fail visibly at new consumption rather than being silently rewritten.
5. The parent was notified that report diagnostics must expose unsupported/unmeasured cases even without a simulation receipt; otherwise research-only consumption would hide the evidence gap. Fully validated old cases may keep their previous report shape. The parent has reported integration applied; its final consumer gate remains its own evidence.

## Focused verification and exact evidence

| Check | Result | Receipt |
|---|---|---|
| Initial baseline report-embedded repro | MR-1 reproduced; MR-2 schema/runtime reproduced, report correctly stopped at the separate missing-driver-contract guard | `/private/tmp/drf-mechanism-review-20261028-01/junit.xml` |
| Extended baseline repro with explicit driver contracts | 1 doctest passed; both defects reached the report consumer | `/private/tmp/drf-mechanism-review-20261028-02/junit.xml` |
| New regression module before implementation | 14 failed. Failures include absent helper/mode and missing target binding; two initial test-construction mistakes were corrected rather than counted as product defects | `/private/tmp/drf-first-ten-model-admission-red-20261028-01/junit.xml` |
| New helper/scenario tests plus selected structural and legacy reducer checks | 74 passed in 14.79 seconds, including all 16 new cases | `/private/tmp/drf-first-ten-model-admission-green-20261028-01/junit.xml` |
| Full affected target runtime and case-contract modules | 286 passed in 2.45 seconds, with existing fixtures and tests unchanged | `/private/tmp/drf-first-ten-model-admission-compat-20261028-01/junit.xml` |
| Ruff `--no-cache --select F,E9` on the five owned Python files | Passed | Current tool output; no source changes afterward |
| Independent bounded source review | No findings against baseline `5b9b9215`; no reviewer writes or test claims | Reviewer `01a18105-419b-7b90-9d4d-897c49764367` |

The current commands use the required interpreter and unchanged audit runner. The focused command selected `test_first_ten_model_admission.py`, three dimensional/identity test functions in `test_target_simulation.py`, two case-contract functions, `test_world_state_seed_prior.py`, and `test_world_share_sources.py`. The compatibility command selected only `test_target_simulation.py` and `test_forecast_case.py`. The two pass counts overlap and are not a unique-case total. No broad baseline suite, producer suite, or coordinator-owned baseline gate was duplicated.

All completed receipts report shutdown complete, identity preserved and no recorded source drift. The compatibility run had **zero blocked-operation attempts**. The focused run imported the legacy loop/OASIS path and recorded denied import-time probes: one socket construction, four subprocess attempts and twenty external reads, including font/system discovery. They stayed denied; this is not zero attempted probes and not live transport evidence. The two report-doctest runs each had one denied `.pdbrc` read from doctest/PDB setup. No guard was relaxed.

The red module initially used a nonexistent legacy reducer method name and a single-scenario fixture with obsolete assessment weights. Those harness errors were corrected to the actual `step_from_source` API and a coherent one-scenario prior, preserving the intended behavior assertions. No existing assertion or controlled fixture was weakened. The parent subsequently reported five existing `test_target_report.py` linear fixtures with inconsistent seed identities exposed by production admission; those fixtures and their repairs are parent-owned, not modified here. All 21 new combined model tests passed in the parent's intermediate gate according to its message; its final receipt is pending outside this owner report.

## Frozen owned source

| File | SHA-256 |
|---|---|
| `deerflow_bridge/forecast_case.py` | `ab8aa052a1ac8b12537de141cdb0900632442f11d0081c94cfa9c2a8c39d9573` |
| `backend/app/services/target_mechanisms.py` | `fba619848e9698f458bdabf5d82d44ddd55a1d68baa2d0dcd43ec5768c36bd59` |
| `backend/app/services/target_simulation.py` | `6b8623edf4f87d0891a452a0a53fd3406ffae55321541319b9e6dd679895689a` |
| `backend/app/services/target_actors.py` | `4ce4fb562b8779199336510d6b8f83fe16f839e1797264ef89c5682db1142040` |
| `backend/tests/test_first_ten_model_admission.py` | `b4e15bd6627d2adcc629aee0a60e81b41c0aa08a509c6b7b74f3f9fb6472c6be` |

Only these five Python files and this owner report were written. The coordinator owns commits, shared handoff, issues, integration files, consumer tests and the final frozen gate. The remaining artifact-specific offline and empirical acceptance limits in the matrix should remain explicit; no additional implementation defect is claimed from missing specimen evidence alone.

## Updates

- 2026-10-28: Read the supplied first-ten plan, current architecture/contracts/acceptance, root and scoped handoffs, owner evidence, and relevant producers/consumers. Isolated two concrete admission gaps and embedded their bounded reproduction in this owned report.
- 2026-10-28: Extended baseline reproduction after the independent missing-driver-contract report gate; both defects then reached the report consumer.
- 2026-10-28: Received explicit implementation ownership, added targeted regressions, implemented known-contradiction admission and settlement target binding, and communicated the pure integration contract to the parent.
- 2026-10-28T05:43:05Z: Froze owned source after 74-case focused and 286-case compatibility gates, Ruff, diff check and independent no-findings review. Recorded denied probes and parent-owned integration/fixture limits without claiming final composed acceptance.
