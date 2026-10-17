# Fresh-run backend integration handoff

**Status:** Scoped P1 finding closed against coordinator-reported integration GREEN; source/tests frozen, broader release gates pending.
**Date:** 2026-10-17.
**Current focus:** Preserve the source/test freeze while the coordinator runs broad all-world/affected-legacy and frontend/browser gates.

## Request and constraints

Implement the authorized backend portion of `default-api-contract.md` using the v3 helper described in section 9 of `default-audit.md`. Ownership is limited to Config, pipeline orchestration, research and SDK routes, preflight, scheduled reruns, batch runs, the new `test_world_fresh_launch.py`, and this record. Other workers own the helper, transport, modeling core, frontend and release gates. No runtime/app imports, test execution, providers, commits or delegation are authorized here. The coordinator performs guarded verification and any default activation. The fresh default remains `oasis-legacy`.

## Requirements and acceptance evidence

| Requirement | Authored scenario / required evidence |
|---|---|
| Fail before any pipeline side effect | Real Flask POST and direct `start`, with storage/task/thread/model boundaries observed; missing/invalid policy, null engine and round overrides must reject without changes. |
| Pin detached configuration and one safety snapshot | Real start persists policy and admission digest; mutate the source after admission and verify saved bytes; HTTP MockTransport records no requests during admission. |
| Consistent readiness | Short/full GET and script report use the same resolver and selected mode/model/engine; POST revalidates regardless of earlier GET. No policy/path/credential leak. |
| Deferred research-only and safe continuation | No profile/auth construction for research-only; failed continuation leaves saved bytes and registries unchanged; saved explicit metadata wins; missing historical engine remains legacy. |
| Direct callers remain compatible | SDK forwards optional fields, schedules pin saved/legacy selection, batch anchor/children explicitly use legacy and world-parent reuse fails before writes. |
| Existing world hook consumes admitted options | Reuse an existing lifecycle fixture if it supports a bounded admission-to-world-stage scenario without changing other tests. |

## Plan and decisions

1. Read the frozen API, audit and current producer/caller paths. This source inspection is complete.
2. Integrate resolution before directory/task/state/thread creation. Keep the general `preflight_pipeline(mode, model)` interface and historical reader unchanged.
3. Connect sanitized simulation readiness to the API and environment report. Fresh POST and direct callers must re-resolve at `start` rather than trust a prior readiness result.
4. Add guarded test scenarios in the owned new file. Use existing fixture data and real routes/start, replacing only environmental and dispatch boundaries.
5. Review the owned diff and perform static AST/lint checks only. Freeze the files for the coordinator; report unexecuted acceptance explicitly.

## Progress and issues

- Source review confirmed that start currently creates directories/tasks before storing raw caller dictionaries, continuation changes state before world validation, and SDK/schedules/batches omit engine fields.
- The helper's source now requires shared `MODE_V3` and `responseFormat=json_object`. It rejects all full-world round overrides and constructs/closes transport without dispatch. Its internals remain outside this worker's ownership.
- No implementation verification or runtime acceptance has occurred in this worker.

## Remaining work and verification

The coordinator's guarded scenario run remains pending. Full behavior, live/paid tests, browser checks and default promotion belong to the parent and are not implied by static readiness.

## Updates

- 2026-10-17: Created the scoped continuity record before implementation; recorded ownership, frozen interfaces and scenario acceptance criteria.

## Frozen implementation checkpoint — 2026-10-17

Config adds `DEFAULT_SIMULATION_ENGINE` with source default `oasis-legacy` and `WORLD_POLICY_SPEC_PATH` unset. `start()` distinguishes omission using the helper's `UNSET`, captures safety once, resolves before directories/tasks/saves/thread registration, and persists detached options plus `simulation_admission_v1`. Historical `_simulation_engine`, manager and runner defaults were not modified.

The shared `_fresh_simulation_options` adapter is used by `start()` and `simulation_readiness()`. POST and SDK invoke authoritative start; they deliberately do not consume an earlier readiness snapshot or perform a second simulation resolution. GET and script pair simulation readiness with the unchanged `preflight_pipeline(mode, model)` signature. Short GET now checks the selected research model as well as engine; full reports retain existing environment fields and checks. Simulation metadata contains only engine/default/admission status/source/digest or a safe error code. The existing explicitly requested deep probes remain separate from cheap readiness. General research preflight now also reports unsupported model names rather than silently passing them.

Research-only requests defer profile/auth validation. Continuation validates the saved engine before changing mode or stages. A new admission marked `source=deferred,status=deferred` may read the operator profile at first full admission; saved explicit specs/policies never use ambient replacements. Pinned safety controls that full admission. Historical unpinned continuations stay legacy. Existing resume/fork paths are unchanged. A first-full world continuation must satisfy the current v3 contract; it does not silently upgrade an explicit v1/v2 policy. Historical world state without a policy/safety pin is rejected, not reconstructed.

Research/SDK launch and research continuation catch `WorldError` as sanitized structured 400/409 responses containing `error_code`; provider messages, exception details and tracebacks are not serialized. Schedules pass their saved engine, with absent pins explicitly legacy, and refuse world schedules without a saved spec/policy. This is compatibility plumbing, not acceptance of a new world scheduling workflow. Batch anchors and children explicitly select legacy; world-parent batch reuse is rejected before child side effects. The batch API remains legacy-only.

### Authored scenario evidence awaiting execution

`backend/tests/test_world_fresh_launch.py` contains 16 test functions with parameterized cases. They use real Flask research/SDK routes, real start/save/load and the shared admission/MockTransport fixtures. Cases cover missing/invalid profiles, null engine, round rejection, unsupported CLI transport, prompt-only configured launches, detached explicit policy, one safety capture, legacy default/override, research-only deferral, short/full/script parity with selected model, POST revalidation after GET, continuation failure without saved-byte/task/registry changes, saved-policy precedence and historical legacy continuation, error sanitization, schedules and batch boundaries.

The lifecycle fixture scenario starts through actual fresh admission, then calls the existing `_run_world_stages` with fixture research. It uses the real modeling/compiler/seal path and stops at `_wait_world_simulation`, before actor dispatch. This is an authored preparation integration check, not full pipeline/research/actor/REPORT acceptance. It requires the parent guard to execute. The fixture substitutes unrelated general preflight environment checks and thread/task dispatch, so it does not prove live environment readiness.

### Static verification and review notes

- All eight Python files below passed `ast.parse` and compilation to in-memory code objects; none was executed or imported as an application module.
- `ruff check --no-cache --select F,E9` passed for the new test, research/SDK APIs, preflight, schedules and batches. The large orchestrator and Config received AST/compile and scoped diff review, not an asserted full lint pass.
- `git diff --check` passed for the seven tracked implementation files. Source inspection checked before-side-effect ordering, omission/null distinction, detached persistence, one captured safety snapshot, saved selection behavior and API error handling.
- Static review caught incomplete thread/task substitutes in the new fixture and a batch test that would have waited for a parked worker; those were corrected before freezing. The unrelated graph wait is now explicitly substituted in the batch selection test.
- Removed pre-existing unused `traceback` and `Callable` imports in the owned SDK/scheduler files after the scoped lint check reported them.
- No pytest collection/execution, app/runtime imports, providers, live credentials, commits or delegation occurred. Other workers' files were neither edited nor reverted.

### Frozen SHA-256 receipt

| Owned Python file | SHA-256 |
|---|---|
| `backend/app/config.py` | `5fa9964eeabdc9c9a8db8935d5bdd7514bc67d23e037f8b1ea8c4270dbba206c` |
| `backend/app/services/pipeline_orchestrator.py` | `65cc749501731b243842988d8261cf5f9b1a26b681341dae53f6c6100d100400` |
| `backend/app/api/research.py` | `5615344d966c8695715420d9ea2368f0eafe0b5f03c5f1cb59eb117a35b418db` |
| `backend/scripts/preflight.py` | `70a0c1709d91901df24258f442804e82459b22c27b7c3550bd120739330db9a2` |
| `backend/app/api/sdk.py` | `d299a814cafd3e110996b291e70f2a06b1882bdd58f4ae6fd3384da4c4232ec4` |
| `backend/scripts/scheduled_rerun.py` | `928a1dc7db8467b7e8b02c4e2b7a1e6e2ab635cde6e38ea8b1ebe9d422dc5a29` |
| `backend/scripts/batch_runs.py` | `125c6093afc2076fa463d85ff14bc9ad584f241b46d74f3e60c23cc4cde78135` |
| `backend/tests/test_world_fresh_launch.py` | `05b8540ae738e4ac169168d3af2de9d2368749a4f7f92e491cedc2a0698d8503` |

Dependency readback matched the coordinator's frozen helper `246fc70737d112b6d0da4b80d6559715ab75ac4e39b8b9d448824f8f814f01b0` and helper tests `a80ef587fc5c899f9927d050df41298527a02125a3861c186673052cb998bce7`. These dependency files were read only.

### Coordinator handoff

Run the combined guarded backend suite including `test_world_fresh_launch.py`, the frozen helper tests and existing world lifecycle/engine compatibility tests. Retain individual failures and source hashes before releasing any worker for repairs. Pay particular attention to the new composed preparation fixture and compatibility tests whose old assumptions predate fresh admission. Do not activate the default from this checkpoint. This worker is frozen pending concrete coordinator feedback.

- 2026-10-17: Finished the scoped implementation/test checkpoint, recorded static checks, full source hashes and unexecuted acceptance boundaries; froze runtime and test edits at coordinator request.

## Coordinator release for composed actor acceptance — 2026-10-17

The coordinator reported receipt `drf-profile-traversal-green-20261017T145819Z-b0x1_20r`: 213 tests passed in 13.44 seconds, including 23 guard controls and all helper/fresh-launch tests, with no drift across 543 files. The coordinator also reported a clean independent guard review. These are coordinator-reported results, not tests executed by this worker. The initial profile failures were traced to read-only root-directory traversal in the guard; the secure profile reader and this worker's production files remained unchanged.

The coordinator has released only this test file and handoff for a narrow extension. Replace the composed preparation stopping point with actual `run_child` execution through the existing fake-Popen/real-SDK fixture. Preserve the modeler transport, provide a plain actor candidate followed by a v3 checked revision via MockTransport, and verify native JSON wire bodies, exact call counts, durable receipts, RUN completion and consistent world generation across seals/results/API. Also author export of actual configured-world, explicit-legacy and missing-profile preflight GET envelopes under the guard evidence root for isolated browser acceptance. No runtime work or production edits are authorized. New acceptance remains pending until the coordinator executes the extension.

## Composed-child extension frozen — 2026-10-17

The existing `test_admitted_options_reach_existing_world_prepare_hook` name is retained for coordinator selectors, but its intentional early stop has been removed. It now calls the actual `_run_world_stages` through modeling, compile/seal, runner, service launch, the lifecycle fixture's fake `Popen` invoking real `run_child`, real controller/store and committed result API. Research is supplied by the existing fixture and the background research thread remains parked. The modeler `_build_client` is unchanged; the actor `_build_client` uses a real OpenAI SDK with MockTransport. A read-only wrapper around HTTP send records actual bodies while preserving the fixture's `b.sent` tracking.

The scenario asserts zero dispatch during initial admission and exactly three dispatches overall: one modeler call, one plain actor candidate and one revision envelope with all four v3 checks marked consistent. It verifies exact actor system/user messages and candidate binding, native `response_format={"type":"json_object"}` on all three requests, fixed model/output limit/n/stream fields, two succeeded durable review stages with known usage, real SQLite horizon commit, PREPARE and RUN completion, closed actor clients, and unchanged admitted policy/admission metadata. The launch-time sealed world must remain identical after execution. Sealed spec, saved simulation, runtime projection, result manifest and API result must share the same generation; subsequent reads must not dispatch.

Added `test_export_real_preflight_responses_for_browser`. During the coordinator guard it obtains actual Flask GET envelopes using real simulation admission and synthetic profile/auth. Unrelated general environment preflight remains the launch fixture's explicit substitute. It writes **`guard.root / "research-preflight-browser-fixture.json"`**, containing:

- `schemaVersion: research-preflight-browser-fixtures/v1`.
- `responses.configured_world`, `responses.explicit_legacy`, and `responses.missing_profile`.
- Each entry has `method`, `path`, `query`, `status`, and the full actual response `body` for the isolated browser server.

The configured default is patched to world only inside the fixture. The missing-profile response remains HTTP 200 with `success=true`, `data.ready=false`, and `simulation_admission.error_code=world_configuration_required`, matching the existing GET contract. The fixture asserts no profile path, raw policy or credential content is exported, no pipeline starts and no HTTP dispatch occurs. The JSON file has not been generated by this worker because generating an actual response requires the coordinator's runtime execution.

Static validation passed: AST parsing and in-memory compilation without execution, plus `ruff check --no-cache --select F,E9 backend/tests/test_world_fresh_launch.py`. The file now contains 17 test functions with parameterized scenarios. All seven production-file SHA-256 values were re-read and match the earlier table exactly, preserving the production bytes covered by the reported 213-test receipt. No new runtime result is claimed.

**Current test SHA-256:** `10d9b43c3b2d7b2a72139da2549bdfdaba1b0ab7ef0e0548a39fab2b8df38993`. This supersedes only the earlier test hash `05b8540a…`; all production hashes remain unchanged. The extension and this document are frozen pending coordinator feedback.

- 2026-10-17: Recorded the coordinator's accepted 213-test/guard-control receipt, extended the composed scenario through the actual actor child and committed API result, authored guarded browser-fixture export, checked static syntax/lint and unchanged production hashes, and froze again without runtime execution.

## P1 candidate authority review: RED-test phase — 2026-10-17

The coordinator confirmed that `_run_world_stages` can load `handoff/world_modeling_candidate.json` even when fresh admission has already pinned `world_policy_spec`. The service uses the raw candidate instead of its separate policy argument, allowing the artifact to replace admitted review/JSON/budget authority. The initial 213-test production receipt is historical evidence and did not exercise this conflict.

The current release is test-first only: author behavioral conflicts for v2 review, missing JSON format, increased token/USD ceilings and an unbound candidate, plus a matching-authority positive case. Run actual fresh admission and the actual existing preparation hook, observe simulation creation/seal boundaries, and stop before actor dispatch so the coordinator's RED run needs no provider activity. The matching case must seal the admitted policy/limits unchanged. Existing `test_world_lifecycle.py::test_pipeline_saved_candidate_runs_same_compiler` remains the unmodified historical compatibility control. No production patch is authorized until the coordinator has captured the RED receipt.

### RED checkpoint ready for coordinator

Added an `admitted_handoff_candidate` fixture using actual configured fresh admission and real `_run_world_stages`, with spies that call the real simulation creation and seal functions. It stops at the actor-run boundary. Five parameterized negatives under `test_fresh_handoff_candidate_cannot_replace_admitted_authority` require a `WorldError` before creation/sealing/HTTP, no assigned simulation ID, unchanged simulation artifact bytes, unchanged candidate file and unchanged admitted policy/metadata. Mutations are `v2_review`, `missing_json_format`, `increased_tokens`, `increased_usd`, and `unbound` (no policy/limits/effect authority). The current bug is expected to cross the observed boundaries; the assertion reports the reached boundaries. This expectation has not been executed by this worker.

`test_fresh_handoff_candidate_matching_admitted_authority_is_allowed` requires the matching candidate to reach real creation/sealing, mark PREPARE completed, preserve admitted policy/limits/effect exactly and preserve the source candidate bytes. It makes no modeling or actor request. This positive prevents a blanket candidate ban from satisfying the negatives. The historical control in `test_world_lifecycle.py` is unchanged.

Static checks passed: AST parsing/in-memory compilation without execution and Ruff F/E9 for the owned test file. It now has 19 test functions, including five cases in the new negative parameterization. **Frozen test SHA-256:** `c8ccf3b0a5eb0eb63fc70ea711d8352eee99d5f95014b17359f55686caf06761`. **Unchanged production orchestrator SHA-256:** `65cc749501731b243842988d8261cf5f9b1a26b681341dae53f6c6100d100400`.

Coordinator selection: the two new `test_fresh_handoff_candidate_*` tests (or `-k handoff_candidate` within the owned file), together with `test_world_lifecycle.py::test_pipeline_saved_candidate_runs_same_compiler`, using the existing guarded runner. Capture RED evidence before releasing the production patch. No runtime/provider work, production edits, service edits, other-test edits, commits or delegation occurred during this checkpoint.

- 2026-10-17: Added the five candidate-authority negatives and matching positive, checked static syntax/lint, confirmed production hash unchanged, and froze for the coordinator's RED run.

## P1 production repair released after RED — 2026-10-17

The coordinator reported the RED gate at `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-fresh-candidate-binding-red-20261017T151651Z-h5oxllxf/evidence`: all five negative cases failed after crossing simulation creation, sealing and the actor boundary; the matching positive and historical control passed (2 passed, 5 failed, 37 deselected, 25.33 seconds; no drift across 543 files). This is coordinator-reported execution evidence. The coordinator then released only the orchestrator, owned test and this document for the production repair, with no runtime/provider work.

The repair will validate a fresh handoff candidate against the whole admitted profile and its recorded digest before simulation creation. A present but invalid/deferred admission record or missing candidate authority will fail closed; absent admission records preserve the historical saved-candidate behavior. Full policy comparison includes any optional future `candidateRepair` pin without a special-case allowlist or synthesized default. Matching policy/limits/effect must remain eligible for real preparation.

## P1 repair frozen for GREEN verification — 2026-10-18 (Asia/Singapore)

The production change is confined to `_run_world_stages` in the owned orchestrator. It tracks whether raw input came from the handoff candidate. When that path has a `simulation_admission_v1` key, it requires the versioned record to be ready and both the saved profile and raw candidate to contain explicit `policy`, `limits` and `forecastEffect`. It compares the existing canonical digest of the entire saved profile and the candidate's full authority projection with the recorded `profile_sha256`. Failures use `WorldError` code `input_binding_mismatch` before world creation, policy/effect mutation, preparation or sealing. Candidate envelopes are also required to be objects before unwrapping.

The comparison is exact canonical JSON identity, including every nested policy/limit field and JSON type. It neither merges nor synthesizes fields and does not load an ambient profile. Any future admitted `candidateRepair` field is automatically covered by this whole-policy digest comparison. Matching candidates proceed through the existing preparation path. An absent admission record retains the historical saved-candidate path; prepared-world reuse and direct supplied raw-spec paths are not changed by this narrow repair.

The five coordinator-confirmed RED cases and matching positive remain intact. The same negative parameterization also now checks a changed forecast effect, missing forecast effect and changed additional policy field (`reasoningEffort`), bringing it to eight negative cases. The historical control remains in its original unedited file. These additional cases and the patched implementation have not been executed by this worker.

Static validation passed for both changed Python files: AST parsing and compilation to unexecuted in-memory code objects. Ruff F/E9 passed for the test; Ruff F821/F822/F823 passed for the orchestrator. The orchestrator's scoped `git diff --check` passed. Source review confirmed that the new checks precede `create_simulation` and do not touch the historical engine default. No runtime tests, application imports, provider activity, service edits, other-file edits, commits or delegation occurred.

| Current frozen file | SHA-256 |
|---|---|
| `backend/app/services/pipeline_orchestrator.py` | `2631b943d15f3fc95f5136202f124ee665ba785cb5c6e06dd0d31e13a835c767` |
| `backend/tests/test_world_fresh_launch.py` | `2224a92d8e4780dca01fa9f111f8defae5b53da6070af9b9934495efe9bbd8b2` |

These supersede the preceding orchestrator/test hashes. The original 213-test receipt remains historical; the repaired production bytes require a new coordinator guard receipt. Next step: rerun `test_fresh_handoff_candidate_*` plus the historical lifecycle control under the guard, then the relevant fresh-admission/composed-child suite as coordinated. The default remains `oasis-legacy`. All owned edits are frozen pending that receipt.

- 2026-10-18 (Asia/Singapore): Applied the released P1 authority binding, extended effect/whole-policy negative coverage, checked static syntax/lint/whitespace and froze the new source/test hashes for coordinator GREEN verification.

## Bounded P1 closure after integration GREEN — 2026-10-18 (Asia/Singapore)

The coordinator reported **668 passed in 8.24 seconds, with no drift across 545 files**, at [the integration evidence directory](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-candidate-repair-integration-first-20261017T160659Z-6nouqkvj/evidence). The reported selection covered current policy/store/parent repair tests, the updated fresh helper, this fresh-launch suite including the real-child fixture and P1 candidate binding, and existing policy/review/store/v3 controls. This worker did not run the gate or independently execute its tests; the execution result is attributed to the coordinator.

The owned P1 finding is now closed within that guarded offline scope. Its RED evidence showed conflicting candidates crossing creation/sealing/the actor boundary; the repaired check binds complete candidate policy/limits/effect to both the saved profile and admission digest before world creation, with matching and historical controls retained. The whole-policy binding includes `candidateRepair` when admitted. This is a bounded regression closure, not an independent review sign-off, live-provider result, full behavior-study pass or default-promotion decision.

Only this note changed after the GREEN report. The orchestrator/test hashes remain frozen at `2631b943d15f3fc95f5136202f124ee665ba785cb5c6e06dd0d31e13a835c767` and `2224a92d8e4780dca01fa9f111f8defae5b53da6070af9b9934495efe9bbd8b2`. Broad all-world/affected-legacy verification and frontend/browser acceptance remain coordinator-owned next gates. No paid calls or default activation are authorized; `oasis-legacy` remains the source default.

- 2026-10-18 (Asia/Singapore): Recorded the coordinator's 668-pass/no-drift GREEN receipt and closed the owned P1 within its tested offline scope. Kept source/tests frozen and retained the broader release and live-behavior limitations.
