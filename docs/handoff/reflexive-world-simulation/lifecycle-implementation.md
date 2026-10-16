# Lifecycle implementation working record

Status: Complete including coordinator legacy-source follow-up. Owner: lifecycle worker. Updated: 2026-10-16T16:19:01.884567+00:00.

## Request and constraints
Implement approved world-v1 admission through the existing manager, runner, direct APIs and pipeline, with the pipeline retaining stage authority. Own only simulation_manager.py, simulation_runner.py, pipeline_orchestrator.py, api/simulation.py, api/research.py, test_world_lifecycle.py and this record. Preserve concurrent edits and the M0 API guard. No providers, unguarded application imports, commits or implementation subagents.

## Requirements and acceptance
| Requirement | Observable check | Evidence |
|---|---|---|
| Saved engine and input identities | API prepare compiles/seals and start rejects mismatched/unknown/tampered identities | Guarded lifecycle tests |
| World lifecycle | Runner dispatches start/status/stop to the real service and rejects interviews | Guarded service/process fixtures |
| Pipeline authority | Real PREPARE/RUN methods complete only after frozen result verification, resume reuses without world writes | Guarded pipeline scenarios |
| Reader consistency | GET returns one result view and stale cursor conflicts without writes | API tests and directory hashes |
| Immutable fork/seed | New identities with independent baselines; parent bytes unchanged | Fork/seed scenarios |

## Plan and progress
1. Read contracts and current producer/consumer paths (done).
2. Add manager pins and service dispatch before legacy mutations (done).
3. Add pipeline world PREPARE/RUN and engine-aware fork/seed paths (done).
4. Exercise actual boundaries with provider/process fakes under the existing guard (done; final gate below).
5. Request one bounded read-only review, resolve findings and freeze evidence (done; same reviewer confirmed closure).

## Findings and decisions
The world service is coordinator-owned and its exact class methods are pinned by implementation-contract.md. The world model must be supplied in options or a saved modeling candidate; absence is a readiness failure. The report owner resolves world context from simulation state; lifecycle passes the real simulation ID without adding optional constructor fallbacks. Existing social mutation and completion paths must be bypassed in world mode. Legacy omitted engine remains oasis-legacy until the live gate.

## Issues and recovery
The final scoped gate passes and independent review findings are closed. The historical failures and the blocked wider gate below remain part of the evidence record. No application execution occurred outside the guarded runner.

## Scenario checks and verification
The final guarded gate ran the real API, manager, runner, service, compiler, SQLite controller, result reader, and pipeline PREPARE/RUN methods. HTTP and process scheduling were faked; the process fake invokes the actual child entry with the admitted manifest SHA, launch identity and inherited launch lock. Public pipeline resume/fork scheduling uses a deferred thread boundary. The broader research, graph, and report production lifecycle and live provider behavior are outside this slice proof.

## Remaining work
No implementation item remains within the assigned lifecycle slice. Coordinator has been notified that the owned code/test files are stable for combined integration testing. Full release/live evaluation, broader research-to-report acceptance, and the blocked OASIS-import gate remain coordinator-owned. No commits or provider calls were made.

## Updates
- 2026-10-16: Created working record after reading the approved contract, existing handoff, runtime/consumer design and owned lifecycle boundaries.

- 2026-10-16T15:54Z: First guarded run reached 17 passing tests and five failures. Four real API/pipeline child failures exposed observation `messages` missing from the policy allowlist; coordinator notified. One failure exposed stale world admission pins in a reused manager cache, now changed to reload world state. Receipt: /private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-lifecycle-first-20261016T155307Z-vaw_7nik/evidence/. No network/process attempt counters; three safe storage/config redirects. Compiler files drifted concurrently, so this is behavioral red evidence only.

- 2026-10-16T16:04Z: Implemented automatic modeler arguments after coordinator extended the service contract. The direct API and pipeline forward explicit policy/budget, ontology and requirement; a source-backed compiler still owns admission. Guarded tests now exercise actual modeler and actor SDK calls using fake HTTP, and verify modeler charges reduce the actor budget. The child process fake forwards manifest SHA, launch ID and inherited launch lock exactly like the real child script.
- 2026-10-16T16:04Z: Independent bounded source review identified four P1 lifecycle gaps: repeated-resume artifact-pin replacement, cancellation at a progress callback, missing-engine downgrade during preparation, and seed checkpoint loss before report completion. All four have source fixes and scenario regressions; same reviewer is checking closure. A duplicate STOPPED enum declaration was corrected before the follow-up run.
- 2026-10-16T16:04Z: Combined gate reached 58 passing tests and one inherited source-characterization failure caused solely by hard-coded whitespace in test_sim_resume_reuse.py (outside this worker's ownership). The legacy behavioral tests passed. Receipt: /private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-lifecycle-admitted-child-20261016T160209Z-x0l6dh0z/evidence/. Source drift was empty. Coordinator notified to update that existing characterization without relaxing its ordering assertions.
- 2026-10-16T16:04Z: A broader attempted gate including test_simulation_config_seal.py was blocked during OASIS import by the guard's external-write denial. This is a blocked collection attempt, not passing or zero-attempt evidence. Receipt: /private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-lifecycle-third-20261016T155628Z-dq3gxiq9/evidence/. Guard behavior was preserved.


## Prior 62-test verification and review

The final immutable snapshot run passed **62 tests**, exit code 0, with **no source drift**. All six owned Python file hashes were rechecked against the snapshot manifest after the run. AST parsing and scoped `git diff --check` also passed. The test command was:

```sh
python3 docs/handoff/reflexive-world-simulation/run_offline.py \
  --python /Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python \
  --label lifecycle-final -q \
  backend/tests/test_world_lifecycle.py \
  backend/tests/test_world_engine_admission.py \
  backend/tests/test_sim_resume_reuse.py
```

Evidence directory: `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-lifecycle-final-20261016T160456Z-vvlrhr8n/evidence/`. The sibling `source-manifest.json` and `verification-summary.json` bind the frozen source and full invocation. `junit.xml` records the scenario outcomes; `completed.json` records successful shutdown and the CPython guard boundary. The guard observed zero network events and two blocked subprocess attempts: `uname` and `unregistered-executable`. The second label does not identify an executable; no claim of zero process attempts or OS sandboxing is made. The actual world child process was substituted at Popen; its production controller ran in-process under the guard.

Independent review agent `01a1456a-f82c-7273-94b7-af15ae53e7ea` confirmed closure of all five lifecycle findings. The final completed-seed pin issue was fixed using one read-only `_validate_world_seed` shared by first/recovery execution and completed ensemble reuse. Parameterized regressions reject changed generation, manifest SHA and simulation identity without new actor dispatch or world writes. The reviewer performed source review only and is now closed.

### Prior source hashes (62-test gate)

| Owned file | SHA-256 |
|---|---|
| `backend/app/services/simulation_manager.py` | `1d7b81eddd656328ebd30741aeba4c45aefc4364e8c5dc57cecc16b132b7335b` |
| `backend/app/services/simulation_runner.py` | `838dbc58658b82c31023363194138bfb77b17084c783e4ba3b8dedec7e6708a1` |
| `backend/app/services/pipeline_orchestrator.py` | `c2fd353bc539c7ac5895b165d5c827c18b8eb44c4d0625e1ee60228943713168` |
| `backend/app/api/simulation.py` | `71f40add130b36dd0efde0d5b13a37282129c9f5bb13b093680cb378495a1da1` |
| `backend/app/api/research.py` | `053cc0528027f416192531879e71ee44d304c6f02570b9a83ffc99554ac68ccd` |
| `backend/tests/test_world_lifecycle.py` | `84aa13cd8b7b482822be6149204240545142e6c4b2de59558e12c434c70fdb36` |

## Coordinator continuation prompt

Continue the combined world-v1 integration in this worktree using the lifecycle source hashes and receipt above. Preserve legacy admission until the live gate. The lifecycle source is stable; combine its real API/PREPARE/RUN/seed tests with the coordinator's service/modeler and report/UI gates. Keep the wider OASIS import failure and two blocked subprocess probes explicit when reporting guard evidence. Do not infer live provider behavior, end-to-end report acceptance or forecast quality from this scoped offline gate.

- 2026-10-16T16:07Z: Final 62-test gate passed without source drift; completed-seed reviewer finding closed; reviewer stopped; owned source stability and evidence path sent to the coordinator. Lifecycle slice marked complete, with no commit or provider execution.

- 2026-10-16T16:17Z: Coordinator identified an uncovered legacy producer-to-pipeline mismatch: sources.json is a JSON list while the world artifact reader only accepts objects. Reopened the lifecycle slice, reused the real legacy producer/seal fixtures and added a full PREPARE/RUN/reuse regression plus captured-source byte-tamper controls before changing source. Also auditing provisional result registration and explicit stale-export recovery. Previous 62-test evidence remains historical; no broader acceptance claim is carried forward.

- 2026-10-16T16:19Z: Reproduced the coordinator finding using the real legacy producer's persist_final_actor_intelligence_contract and research promotion, then the production pipeline method: sources.json list hit the world-object-only reader. Red receipt: /private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-lifecycle-legacy-red-20261016T161624Z-ku29poc2/evidence/ (3 failures, no drift). Replaced only the legacy envelope read with the existing _research_data_read bounded/no-symlink reader; source/dossier byte hashes must match consumed_generation when supplied, while the real compiler still validates legacy actor/source/dossier seals. World artifact schema is unchanged.
- 2026-10-16T16:19Z: Actual two-round controller tests confirm world_result_partial/world_result_manifest_partial do not count as completed RUN registration. With a committed final horizon and valid prior export, explicit service start recovers exports without another child/actor call. Corrupt prior bytes fail closed. SQLite read-only WAL mode may create empty WAL/shared-memory indexing sidecars; authoritative input/result/database bytes remain unchanged on rejection, and the test asserts zero WAL payload.
- 2026-10-16T16:19Z: The wider OASIS collection block is traced to installed oasis/social_platform/platform.py creating ./log and a FileHandler during module import. Existing conftest log quarantine executes as a fixture, after test module collection. Coordinator notified that an import-time bounded cwd/quarantine belongs in the existing guard/conftest owner scope; no lifecycle guard relaxation was made.


## Legacy follow-up acceptance (current)

The final combined follow-up gate passed **70 tests**: 46 lifecycle, 2 M0 and 22 legacy reuse. Exit code 0, no snapshot source drift, and all six owned Python hashes match the frozen source manifest on recheck. Scope is the real legacy producer → sealed source envelope → compiler → manager → runner/child → pipeline PREPARE/RUN/reuse, plus partial-export crash recovery and tamper rejection. HTTP/process boundaries remain faked; no application runtime ran outside the guard. This follow-up was self-reviewed against the producer and compiler contracts; the earlier independent review record applies to its earlier source state.

Current receipt: `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-lifecycle-legacy-final-20261016T161811Z-c__gqsk9/evidence/`. Reproduce with the same three-file command above and label `lifecycle-legacy-final`. Guard events are recorded below exactly; attempted blocked processes are not reported as zero attempts.

```json
{
  "redirect:app.config": 1,
  "redirect:app.utils.logger": 1,
  "redirect:app.services.simulation_manager": 1,
  "blocked:process:subprocess.Popen": 2
}
```

Current source hashes:

| Owned file | SHA-256 |
|---|---|
| `backend/app/services/simulation_manager.py` | `1d7b81eddd656328ebd30741aeba4c45aefc4364e8c5dc57cecc16b132b7335b` |
| `backend/app/services/simulation_runner.py` | `838dbc58658b82c31023363194138bfb77b17084c783e4ba3b8dedec7e6708a1` |
| `backend/app/services/pipeline_orchestrator.py` | `f3671708971cdeb4b7847b94f789c1238bca2be8df22ab6a4aee4f7496f7de44` |
| `backend/app/api/simulation.py` | `71f40add130b36dd0efde0d5b13a37282129c9f5bb13b093680cb378495a1da1` |
| `backend/app/api/research.py` | `053cc0528027f416192531879e71ee44d304c6f02570b9a83ffc99554ac68ccd` |
| `backend/tests/test_world_lifecycle.py` | `b326ce90630bbbdc374ac37fe8557dbb0725c2cff098632121785df8874ac2c3` |

- 2026-10-16T16:19:01.884748+00:00: Legacy list-source and partial-export follow-up complete; 70 tests passed with no source drift; AST/diff checks passed; coordinator notified of stable source and the existing OASIS collection boundary. No commits, providers, or edits outside the original owned files.

- 2026-10-16: User authorized a bounded verification-support extension to backend/scripts/main_offline_pytest.py and backend/tests/test_main_offline_runner.py only, plus this note. Implementing an exact-fullname oasis loader wrapper that delegates to the installed PathFinder loader under evidence/import-cwd/oasis and restores cwd in finally. Credential, network, outside-write and coordinator SQLite URI controls remain unchanged. Verification includes success/failure import restoration and the four requested legacy suites.


## OASIS import quarantine and required legacy proof (complete)

The user extended ownership only to `backend/scripts/main_offline_pytest.py`, `backend/tests/test_main_offline_runner.py` and this record for this verification repair. No application seam, dependency, or other test file changed in this extension.

`RedirectImports` now matches exactly `oasis`, obtains the installed spec directly from `PathFinder`, and wraps its original loader. The original module creation, source execution and resource-reader attributes remain delegated. Only `exec_module` runs with cwd temporarily set to `evidence/import-cwd/oasis`; `finally` restores the prior cwd on success and failure. Each execution records `quarantine:oasis_import_cwd`, and the installed OASIS entrypoint bytes are included in guard source hashes. Ordinary test execution keeps its original cwd. No guard permission was broadened: AST comparison proves the entire `Guard` class, including the coordinator's SQLite URI controls, is identical to the previous verified snapshot; the SQLite URI regression method is also unchanged.

New controls execute both the real installed OASIS import and a bounded loader fixture. The fixture proves delegation, relative-log quarantine, exact-package matching, successful and exceptional restoration, and continued credential/network/outside-write denial while the wrapper is active. The real import test confirms actual OASIS API exports and its retained file handlers beneath the evidence directory.

- Standalone `--self-test`: **22 passed**. Snapshot: `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-oasis-import-selftests-20261016T162226Z-qepwutqm/`. The broad snapshot wrapper detected a concurrent change to coordinator-owned evaluation.py only; both owned harness files matched their frozen hashes.
- Required legacy gate: **102 passed**, exit 0, no source drift, complete shutdown. Snapshot: `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-oasis-legacy-regression-20261016T162307Z-y_u3tv2f/`. JUnit, completed receipt, event stream and source manifest are retained. This closes the earlier OASIS collection blocker for the four explicitly requested suites.

Reproduce the combined gate:

```sh
python3 docs/handoff/reflexive-world-simulation/run_offline.py \
  --python /Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python \
  --label oasis-legacy-regression -q \
  backend/tests/test_simulation_config_seal.py \
  backend/tests/test_audit_fixes_runner.py \
  backend/tests/test_simulation_runner_throttle.py \
  backend/tests/test_simulation_trajectory_api.py \
  backend/tests/test_main_offline_runner.py
```

The guard controls intentionally attempt prohibited operations and inspect their denials. Nonzero blocked counters are expected test evidence, not zero attempts; no real provider was called. The combined receipt records:

```json
{
  "redirect:app.config": 1,
  "redirect:app.utils.logger": 1,
  "redirect:app.services.simulation_manager": 1,
  "blocked:network:socket.__new__": 2,
  "blocked:process:subprocess.Popen": 6,
  "quarantine:oasis_import_cwd": 3,
  "blocked:external_read": 20,
  "allowed:guarded_child": 3,
  "blocked:child_process_limit": 3,
  "blocked:credential_path": 6,
  "blocked:external_write": 10,
  "blocked:identity_environment": 1,
  "blocked:sqlite_uri": 9,
  "blocked:network:socket.getaddrinfo": 3,
  "blocked:network:socket.bind": 1,
  "blocked:saved_data": 1,
  "blocked:changed_child_script": 1
}
```

Harness hashes:

| File | SHA-256 |
|---|---|
| `backend/scripts/main_offline_pytest.py` | `b2bd4469cdeb5f94097aafc5b81b0bf634fefd2fe1810dd3b3d0c0d42ff0a15b` |
| `backend/tests/test_main_offline_runner.py` | `3bb35704225cf3744b5b04b0eaa739e5ea1a55785111ddaf439059acdd8114c9` |

- 2026-10-16T16:24:11.395568+00:00: OASIS quarantine and required legacy regression verification complete; 102 tests passed without drift, 22 standalone self-tests passed, guard/SQLite controls preserved by AST comparison. Coordinator notified ready. No application/dependency changes, provider calls or commits.

## Final list-status closure

The public list previously showed preparation READY after a world had completed or failed. Two real-child/API reds established the mismatch. Single-get and list now share `_project_world_status`, projecting the loaded state without writes. Independent review additionally found cross-project corruption could fail an unrelated filtered list; a real tamper red reproduced it. The final list filters saved project metadata before projection, and selected corrupt worlds still fail explicitly. Final lifecycle/admission/legacyreuse gate73passed9.33s, no drift515, at /private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-world-list-final-20261016T182017Z-ubafw52h/evidence. The full integration gate immediately before this narrow correction passed691checks; both receipts are preserved in offline-evidence/.
