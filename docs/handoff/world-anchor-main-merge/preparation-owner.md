# Preparation merge owner

Updated: 2026-10-30, 16:32 Asia/Shanghai. Branch: `codex/world-anchor-main-merge`.
Status: Released I1/P2 correction and fixture alias cleanup are implemented. Focused closure passed 96 cases with 177 source pins stable. Exact source is held for independent review; prior composed results are historical for these bytes.

## Request and acceptance criteria

Own only `backend/app/services/simulation_config_generator.py`, `backend/app/services/simulation_manager.py`, automatically merged `backend/app/services/actor_context.py`, the new `backend/tests/test_world_anchor_main_merge_preparation.py`, the subsequently assigned `backend/tests/test_world_anchor_main_merge_cast_preflight.py`, and this note. Preserve main's source admission, ResearchPreparation, forecast task, immutable preparation generation and revocation alongside optional World Anchor context/case, C5 classifications, actual actor join, source identity seal and native fork binding. No staging, commits, pushes, providers, primary writes, service operations or delegation belong to this slice.

## Plan and progress

Compared base/stage 2/stage 3 for all eight conflict hunks and traced callers and consumers. Resolved both authority markers in serialization and config sealing, both native preparation inputs, and all generator/seed arguments. Reviewed the automatic actor-context merge. Added nine composed regression cases. Captured an actual ordering regression, repaired it, and ran seven focused producer/consumer suites. Owned source is stable for coordinator integration/review.

## Interface requirements

- `SimulationConfigGenerator.generate_config` and `_build_world_model_block` retain positional-compatible `preparation_context`, followed by keyword-only `agency_classifications`, `forecast_case`, and `anchor_context`. Optional values are forwarded only when present.
- `SimulationManager.prepare_world_simulation` accepts both `preparation_context` and `anchor_context` and forwards each conditionally to `WorldSimulationService.prepare_model`. Preparation creation/source validation and anchor source binding both run.
- `SimulationManager.prepare_simulation` retains feature arguments `ontology`, `anchor_context`, and `forecast_case`; it derives main's preparation from admitted bound research before profile generation. The coordinator must retain those optional arguments at all applicable API/orchestrator call sites.
- `build_world_model_seed` must accept `preparation_context`, `agency_classifications`, `forecast_case`, and `anchor_context` together. Main's admitted forecast-task calendar remains authoritative and must agree with anchor cutoff/horizon.
- Native forks bind child research before loading anchored child input seals. The composed regression verifies both preparation and anchor source authorities survive a fork, with a fresh seed/generation and unchanged parent artifacts.

## Findings and decisions

Stage 2 is main `f773f61`; stage 3 is World Anchor `43efe06d`; base is `6ab52f77`. Both config serialization markers and both config-seal bindings are retained. Main's immutable same-ID research admission and rejected PREPARE revocation remain intact.

The automatic actor-context merge required no manual changes. AST comparison confirms all 42 main functions/classes remain unchanged. Against the feature parent, the only changed shared function is `build_actor_context_pack`, retaining main's explicit sparse native report-section policy. The fresh anchor payload function remains exactly the feature implementation. Existing roster identity and audience projections are preserved.

**Reproduced merge regression:** main's new early task extraction ran before feature anchor validation. An invalid supplied anchor dispatched both task-model requests and reached a cast write before rejection. The manager now authenticates enabled anchor context inside the existing research-admission/revocation block, before task extraction. The regression verifies zero model calls and no new preparation artifacts. Absent anchoring adds no validation call.

**Shared fixture follow-up:** feature `test_agency_classification._generator` still needs to answer task extraction/review through main's existing `tests.forecast_task_fakes.task_protocol`; its event-only response is incompatible with the merged calendar admission contract. This was reported to the coordinator and lies outside this owner's files. Production task admission must remain intact.

The new composed fixtures use real manager, source binding, research preparation, task admission, C5 classification, selected actor join, config seals, native preparation and native fork/reload. Graph/model responses are scripted. The source replacement test first confirms main's create-only binding API rejects rebinding, then adversarially edits report plus mutable binding and verifies the earlier anchor config seal still rejects it. The World Anchor source identity intentionally uses consumed core fingerprints, while ResearchPreparation also retains optional dataset/contract sentinels.

## Verification

All four owned Python files parse. Owned-path `git diff --check` passed. No application imports occurred before the shared syntax check/start notice; all runtime checks used the unchanged guard and provisioned interpreter.

The final focused command was:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B \
  backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/world-anchor-main-merge-preparation-20261030-05 \
  -q --tb=short \
  backend/tests/test_world_anchor_main_merge_preparation.py \
  backend/tests/test_preparation_main_merge.py \
  backend/tests/test_preparation_integration.py \
  backend/tests/test_simulation_config_seal.py \
  backend/tests/test_actor_context_runtime.py \
  backend/tests/test_context_audit_prepare.py \
  backend/tests/test_agency_preparation_consumers.py
```

Result: **89 passed in 35.42 seconds**, exit 0, no skips, completed shutdown, identity variables preserved. [Completion receipt](/private/tmp/world-anchor-main-merge-preparation-20261030-05/completed.json) and [JUnit](/private/tmp/world-anchor-main-merge-preparation-20261030-05/junit.xml) record the evidence. At the conclusion of run 05, all four owned Python files matched these tested hashes. The manager hash below is historical and is superseded by the native error-order correction recorded later:

| File | SHA-256 |
| --- | --- |
| `simulation_config_generator.py` | `cc7a5403c9c17486a6a66f1011b8a827af11eaf02db8e5b06ffec7b5047eb50b` |
| `simulation_manager.py` | `9b997a159b61e0863769b161575b07c57481f9310cbb479813d37363dc4d5702` |
| `actor_context.py` | `de4394e005854a3cb9c6f842dca07121a537914f2270c08501595cb034596fb2` |
| `test_world_anchor_main_merge_preparation.py` | `f2302431f524d328d3b3268b89bd2cc5cfffb005e25bf19186c2e8ed3e3e62bb` |

The guard pinned 27 sources and recorded concurrent drift in **`world_model.py` only**. Therefore this gate proves the exercised owned slice but is not frozen combined-tree acceptance. The guard also recorded one blocked socket creation, four blocked subprocess launches (`uname`, an unregistered executable, `fc-list`, `system_profiler`), and 20 denied external reads, including 18 font-directory probes. These are denied attempts, not zero attempted operations or live-provider evidence. The OASIS import ran in the guard's quarantined directory.

Earlier receipts remain intact:

- [Run 01](/private/tmp/world-anchor-main-merge-preparation-20261030-01/completed.json): the invalid-anchor model-dispatch regression reproduced. Other failures were fixture setup and an overbroad native-fork equality assertion.
- [Run 02](/private/tmp/world-anchor-main-merge-preparation-20261030-02/completed.json): ordering and native-fork checks passed; the composed OASIS fixture lacked its required saved owner.
- [Run 03](/private/tmp/world-anchor-main-merge-preparation-20261030-03/completed.json): the fixture owner used an invalid pipeline ID. Replaced it with a real saved `pipe_merge` owner and matching anchor scope.
- [Run 04](/private/tmp/world-anchor-main-merge-preparation-20261030-04/completed.json): seven cases passed; two fixture assertions were corrected to distinguish core fingerprints from optional sentinels and to honor main's immutable binding API.

## Remaining work and continuation prompt

Coordinator: review the owned diff, retain both optional argument families at your call sites, repair the shared task-model fixture, and rerun the focused command after the reflexive owner freezes `world_model.py`. Then include these cases in final merged-tree acceptance. No remaining owned production defect is known from the completed checks. This owner has not staged, committed, pushed, merged, changed services or touched the primary/frozen worktrees.

Ready-to-use prompt: Continue preparation verification in `/Users/rogerlin/.codex/worktrees/world-anchor-main-merge/DeepResearchForecast` on `codex/world-anchor-main-merge`. Read this note, use the latest native correction manager hash below and retain the other three tested Python hashes unless a reproduced defect requires a change, obtain shared source stability, then run the recorded seven-module guard command with a new evidence directory. Verify all hashes, guard events and runtime results before closing combined-tree acceptance.

## Native manager typed-error correction (2026-10-30)

The native owner's 225-pass/one-failure gate reproduced `test_modified_report_cannot_use_an_unchanged_external_research_binding`: main's preparation adapter raised a raw `ValueError` before enabled native anchor source validation could emit its established typed binding error. The parent explicitly assigned the narrow correction. For an enabled anchor, the manager now binds the context to the simulation's consumed research and validates the supplied report, actor bundle and engine before compiling ResearchPreparation. Both later main and native service checks remain intact; absent anchoring retains the existing sequence. The existing typed-error assertion will remain unchanged. Verification will run that exact negative and both combined native/preparation modules under a fresh guard.

The unchanged existing negative and both complete combined modules passed **23 tests in 43.83 seconds**, with zero errors/skips, exit 0 and completed shutdown. This is current evidence for manager SHA-256 `47a850fa27d4b054d74f59f3b81d700e34a4fb2b70c205ca9cae33a0adfa81af`. All **166 source pins stayed stable**. The existing negative module also matches its pinned bytes; no typed-error assertion was changed.

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B \
  backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/world-anchor-main-merge-preparation-20261030-06 \
  -q --tb=short \
  backend/tests/test_world_anchor_world_v1.py::test_modified_report_cannot_use_an_unchanged_external_research_binding \
  backend/tests/test_world_anchor_main_merge_native.py \
  backend/tests/test_world_anchor_main_merge_preparation.py
```

[Completion receipt](/private/tmp/world-anchor-main-merge-preparation-20261030-06/completed.json) and [JUnit](/private/tmp/world-anchor-main-merge-preparation-20261030-06/junit.xml) retain the exact result. The guard again recorded one denied socket creation, four denied subprocess attempts and 20 denied external reads, with the same contained discovery counts as run 05. No live-provider success is claimed. Manager AST and owned-path diff checks passed. Production/test source is now held stable for parent integration; no further local rerun is needed absent another change or failed requirement.

## Authentic-anchor cast admission review (I1/P2, 2026-10-30)

The coordinator authorized one new test file, `backend/tests/test_world_anchor_main_merge_cast_preflight.py`, while keeping production and existing pinned tests frozen for the composed gate. Hubble's I1/P2 distinguishes a valid ready context from an admissible actual selected cast. The new negative will use authenticated anchor publication/reload, a real calendar manager and a selected actor absent from retained aliases; a paired compatible-cast positive must still execute task extraction/review and seal both authorities. Only the new regression file and this note may change before release. Capture the behavioral red first, then propose the smallest conditional ordering correction. The existing fixture import lint cleanup remains planned but unapplied until release.

### I1/P2 red receipt and accepted plan

The new authentic-context test reproduced the defect: selected `Unregistered Vendor` was rejected with typed `invalid_anchor_join`, but the captured task requests already contained `FORECAST TASK EXTRACTION` and `FORECAST TASK REVIEW` (two model calls). The paired selected `Acme` positive passed and verified exactly those two task phases, task/calendar binding, C5, the actual actor join and both preparation seals. The context was reopened from the real publication with no prebound dummy join and authenticated as ready before manager entry.

[Completion receipt](/private/tmp/world-anchor-main-merge-cast-preflight-20261030-01/completed.json) and [JUnit](/private/tmp/world-anchor-main-merge-cast-preflight-20261030-01/junit.xml): **one failed, one passed in 17.72 seconds**, zero errors/skips, completed shutdown, **167 source pins unchanged**. The failed assertion specifically observed model calls, not an import/setup error. Denied guard attempts remain one socket creation, four subprocess launches and 20 external reads; no live-provider success is claimed. New test SHA-256: `5ede58d5ab3fac3537f5e2a06d28efd384270d910a950b4c7149868f03386e24`. Its AST check passed.

The coordinator accepted both the red/positive evidence and this exact patch plan:

1. Keep early task admission unchanged when `anchor_context is None`.
2. For enabled anchoring, defer the single task admission until immediately after the existing actual selected-cast `bind_actor_cast` succeeds, before actor context/profile generation. Initialize `admitted_task` without dispatch before that point.
3. Reuse the existing selection and join validator. Add no duplicate alias validator. Preserve research source admission, immutable same-ID checks, revocation, C5, config seals and later task/config equality checks.
4. On the coordinator's joint release, also apply the previously agreed fixture re-exports in `test_world_anchor_main_merge_preparation.py`; no assertions change.

**Hold remains active.** The plan is approved for implementation after release, not permission to edit during the composed gate. Manager remains `47a850fa27d4b054d74f59f3b81d700e34a4fb2b70c205ca9cae33a0adfa81af`; the existing preparation test remains `f2302431f524d328d3b3268b89bd2cc5cfffb005e25bf19186c2e8ed3e3e62bb`. The newly added cast-preflight test stays as written. Only this owner note was updated after the coordinator accepted the plan.

## I1/P2 implementation release (2026-10-30 16:30 Asia/Shanghai)

The coordinator released the composed hold after its 107-module run completed with 4,442 passes, one unrelated research/spending failure, two skips and three separate-process deselections; all 861 original pins matched. That run is historical for the following narrow correction. Only the accepted enabled-only task-admission deferral and fixture alias cleanup are authorized here. The original red receipt and the new cast-preflight regression remain unchanged. Focused closure and exact source hashes are required before independent rereview.

### Current I1/P2 focused closure

After the explicit release, `prepare_simulation` now initializes `admitted_task` without dispatch and keeps early extraction/review only for absent anchoring. Enabled requests execute the one admission immediately after the existing real `bind_actor_cast` succeeds. No alias validator was duplicated. Source admission and same-ID immutability checks, failed PREPARE revocation, C5 construction, later task/config equality checks and both seals remain in place.

The fixture cleanup imports `test_context_audit_prepare` and `test_target_simulation` under module aliases, then re-exports their fixture objects. An AST comparison confirmed that every existing test function/class body stayed identical. The new cast-preflight file stayed byte-identical to the red run.

Current gate: **96 passed in 50.59 seconds**, zero failures/errors/skips, exit 0, completed shutdown and **177 source pins unchanged**. [Completion receipt](/private/tmp/world-anchor-main-merge-cast-preflight-20261030-02/completed.json) and [JUnit](/private/tmp/world-anchor-main-merge-cast-preflight-20261030-02/junit.xml) retain the evidence. The original [red receipt](/private/tmp/world-anchor-main-merge-cast-preflight-20261030-01/completed.json) remains unchanged.

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B \
  backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/world-anchor-main-merge-cast-preflight-20261030-02 \
  -q --tb=short \
  backend/tests/test_world_anchor_main_merge_cast_preflight.py \
  backend/tests/test_world_anchor_main_merge_preparation.py \
  backend/tests/test_preparation_main_merge.py \
  backend/tests/test_preparation_integration.py \
  backend/tests/test_simulation_config_seal.py \
  backend/tests/test_actor_context_runtime.py \
  backend/tests/test_context_audit_prepare.py \
  backend/tests/test_agency_preparation_consumers.py \
  backend/tests/test_root_forecast_task.py::test_unresolved_goal_fails_before_graph_or_persona_work \
  backend/tests/test_root_forecast_task.py::test_failed_reprepare_cannot_reuse_old_ready_task \
  backend/tests/test_root_forecast_task.py::test_real_prepare_seals_task_and_child_report_use_same_endpoint \
  backend/tests/test_world_anchor_world_v1.py::test_modified_report_cannot_use_an_unchanged_external_research_binding \
  backend/tests/test_world_anchor_main_merge_native.py::test_combined_public_manager_runtime_result_replay_and_native_fork
```

Both new merge test modules passed `ruff check --no-cache --select F,E9`. Changed-file AST and scoped `git diff --check` passed. Guard attempts remained denied: one socket creation, four subprocess launches, 20 external reads. Identity variables were preserved; no live-provider success is claimed.

Exact current hashes for independent review:

| File | SHA-256 |
| --- | --- |
| `simulation_manager.py` | `dbe67dfb07ad31ef8cd928d44ee562bce95e5b0120c8df9421fcdd21e2bf33a1` |
| `simulation_config_generator.py` | `cc7a5403c9c17486a6a66f1011b8a827af11eaf02db8e5b06ffec7b5047eb50b` |
| `actor_context.py` | `de4394e005854a3cb9c6f842dca07121a537914f2270c08501595cb034596fb2` |
| `test_world_anchor_main_merge_preparation.py` | `e52cd22b45ddddd2bb08240554bef5e8f82d6139cb4eb944fd8b48d35a5b2973` |
| `test_world_anchor_main_merge_cast_preflight.py` | `5ede58d5ab3fac3537f5e2a06d28efd384270d910a950b4c7149868f03386e24` |
| Supporting `world_anchor.py` | `a26021efb3556bae4e86ffa4f8f5c956db537ba76d2e3888e4517084684ea880` |
| Supporting `official_data.py` | `87654feeca820cf4232785b78fb2225311235224c260d6e97d6f221c37ce500a` |

These hashes supersede earlier manager/preparation-test hashes for current review. All matched the focused receipt after execution. Independent rereview remains with the coordinator. No broader rerun, unrelated spending fix, Git operation or delegation was undertaken. Production and test source are now held stable for review.
