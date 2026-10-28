# Target research fixture/date repair

**Last updated (UTC):** 2026-10-28T04:23:15Z
**Status:** Complete for the fixture/date and signal-child repairs
**Current focus:** Hand both frozen passing test sources and evidence to the coordinator for broader integration acceptance.

## 1. Request and context

Resume the research owner's frozen implementation after the calendar rolled from October 27 to October 28. The case cutoff MUST remain 2026-10-27. Own only `backend/tests/test_target_research.py` and this record. Preserve peer edits. Do not edit production source, other tests or coordinator records; do not invoke git, providers, network probes or services. The existing owner report and topic handoff are the implementation authority.

## 2. Requirements and acceptance checks

| Requirement | Scenario and expected result | Evidence |
|---|---|---|
| Hermetic retrieval date | Real SourceLedger and ResearchTools generate the fixed October 27 retrieval/fetch timestamp, then the real engine persists an accepted case. | Guarded test receipt and persisted case/ledger. |
| Future sources remain invalid | The same real tool path accepts October 27 and rejects an explicitly October 28 retrieval against the unchanged case cutoff. | Valid control and negative test with the precise validation error. |
| Next-day robustness | Simulated later ambient wall dates cannot change gateway timestamps or case admission; monotonic clocks remain real. | Parameterized date controls and fixture implementation review. |
| Genuine integration status | Run the full target research suite without deselecting producer/runtime/report acceptance. | JUnit, completion receipt, source manifests and drift comparison. |
| Scoped static quality | Ruff F,E9 passes on the owned Python test. | Captured lint output. |

## 3. Plan and decomposition

First capture the current owned test and relevant producer/runtime/report source hashes and reproduce a real producer date failure under the guard. Next patch only the gateway's module-local wall clock within the fixture, retaining real ledger/tool behavior and the unchanged case validator. Add valid and future controls. Finally run the actual full suite with the primary interpreter and `-I -S -B`, obtain independent read-only review, inspect guard activity and record current source hashes. A remaining report defect belongs to the report owner.

## 4. Progress ledger

- [x] Read root continuity, research owner and coordinator handoff, existing fixtures and ledger date validation.
- [x] Capture baseline hashes and reproduce date failure. Baseline: 18 failed, 43 passed in 4.21 seconds.
- [x] Repair fixture clock and add adversarial date controls. Validation and independent review are pending.
- [x] Run guarded target research acceptance and Ruff. All 65 tests pass; Ruff F,E9 passes.
- [x] Reconcile the 12 source hashes before and after acceptance. No drift occurred.
- [x] Check the original consumer scenario. Producer, persistence, runtime and report assertions all pass against the report owner's current source.
- [x] Close independent review against the frozen test hash. Reviewer Raman found no blocking findings; two additional coverage suggestions are recorded below.

## 5. Findings, decisions and assumptions

`install_target_fixture` freezes only `linear_research._utc_date`. SourceLedger independently calls `research_gateway.time.gmtime()` when registering and fetching a source. The validator correctly rejects retrieval after case.asOf. The existing SourceLedger `clock` argument controls monotonic flush timing, so passing a historical epoch there would target the wrong boundary. Production provenance and validation must remain unchanged.

## 6. Issues, mistakes and recoveries

The original fixture leaks the ambient retrieval date. Prior October 27 receipts are historical and do not establish October 28 test success. No production defect is inferred from that leak. This diagnosis was recorded before implementation; the fixture-only repair is now verified below.

The first date-control run passed both valid cases but its two negative cases failed in the new test's timestamp assertion: production rejects future retrieval immediately after source registration, before fetch, so these rows correctly lack `fetched_at`. The assertion was corrected to require the exact retrieval timestamp for every row, fetch timestamps for fetched rows, and at least one real fetched row in each valid control. The future cases must still reach the precise source-availability rejection. This is a test assertion correction, not a production relaxation. The original receipt remains at `date-controls/`.

## 7. Scenario-focused tests

The final checks use the real engine, SourceLedger, ResearchTools and case admission with scripted search/fetch/model inputs. The four controls pass: under simulated ambient dates 2026-10-28 and 2030-01-01, actual October 27 registration/fetch timestamps persist unchanged and cases settle at 176 GW; October 28 registration timestamps fail specifically with `S1: source is unavailable at asOf or publication follows retrieval`. Future rejection happens before fetch and leaves neither a final case nor a research report. The valid controls require a real fetch and verify both raw ledger and typed persisted timestamps. They also verify unchanged stdlib gmtime, monotonic timing and explicit epoch conversion.

`test_evidence_updates_mechanism_through_persistence_runtime_and_report` remains selected and passes in 0.285 seconds: the producer persists coefficient `[2.0]` with its binding proof, real `run_paths` yields target 352 on every path, and the real report retains coefficient `[2.0]`. The report owner's current `_validate_paths` derives parameter fields from `compile_model(case).draw_parameters(Random(0))`, which accepts the runtime's `coefficient:base` shape. The earlier report-owned failure is no longer reproducible against these exact bytes; this repair did not edit report source or its acceptance assertion.

## 8. Verification summary

The final command, run from the assigned worktree with the provisioned primary interpreter, was:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-target-research-date-20261028-6n2z9oa5/acceptance -q backend/tests/test_target_research.py
```

Result: **65 passed in 6.97 seconds**, with zero failures, errors, skips or deselections. The 61 original scenarios remain present and four date controls were added. Ruff command: `/Users/rogerlin/.pyenv/shims/ruff check --select F,E9 backend/tests/test_target_research.py`; exit code 0 and `All checks passed!` are captured in `ruff-final.txt`.

Evidence root: `/private/tmp/drf-target-research-date-20261028-6n2z9oa5`.

| Artifact | Meaning |
|---|---|
| `baseline/junit.xml`, `baseline/completed.json`, `baseline-console.txt` | Before repair: 18 failed, 43 passed. |
| `date-controls/junit.xml`, `date-controls-console.txt` | First assertion iteration: two valid controls passed; two negative controls failed on the corrected fetch-field expectation. |
| `acceptance/junit.xml`, `acceptance/completed.json`, `acceptance-console.txt` | Final 65-case acceptance, exit 0 and completed guard shutdown. |
| `source-hashes-before.json`, `test-before.py`, `test-fixture.patch` | Original source and exact test-only change without using git. |
| `source-hashes-acceptance-before.json`, `source-hashes-acceptance-after.json` | All 12 tracked producer, case, runtime, report, runner and fixture/test hashes; exact equality before/after the run. |
| `independent-review.json` | Read-only review by Raman, agent `01a180a4-e761-7f82-9078-44471229058f`, against the exact frozen test hash; no blocking findings. |
| `acceptance/pytest-tmp/` | Actual generated ledgers, cases, mechanism binding proofs and research artifacts. |

The completed receipt records `identity_preserved: true`, `shutdown_complete: true`, empty `source_drift`, no registered/executed child scripts, and only three storage redirects (`app.config`, `app.utils.logger`, `simulation_manager`). The event streams contain no network, subprocess or blocked events. The boundary is CPython audit hooks, not an OS sandbox; no claim of live-provider quality or production deployment follows.

Exact SHA-256 identities relevant to the handoff:

| Source | SHA-256 |
|---|---|
| Owned test before repair | `694c9c4a1f4cfa86dc0881028f22234521f7623168316b46e3ea213be144b06a` |
| Owned test frozen for acceptance | `71c43f06f98578bf4bd8353adce61cd368bf440bf6152a61111b6c59c2424eb5` |
| `deerflow_bridge/target_research.py` | `e65b6f0db0fd9edb118f3b2f004a2269cbe8dee74ebd1e188b31c025f7a0f98f` |
| `deerflow_bridge/research_gateway.py` | `ddc1700b328d4acca0235d308f4c6ff738b9988da5d3caabdce57f18801f44af` |
| `deerflow_bridge/forecast_case.py` | `f5653615b1ac7211b7ea7232243cfa3798ff551f021a46a58dca3786ddd2cfbe` |
| `backend/app/services/target_simulation.py` | `de5132b2d2bfdbd98fcd6e7c234d5e049108255289d3122546636afe7b310db8` |
| `backend/app/services/target_mechanisms.py` | `3c2c801f41f51acbe726ea85e6bc8f31228e5bda577c9b59a96545bf7046bce4` |
| Report owner's `backend/app/services/target_report.py` | `ebeb1dcd577b5c729ec4cd2e071c34152ec5feb42b876fd77b5b96dbe83d26d0` |
| Guarded runner | `5046cf820fa468d8e8ffb2e3fdade1d20fca2f0bd56ee15eabdff51c223c02be` |

## 9. Remaining work and next steps

No fixture or producer/runtime/report defect remains in this selected suite. Independent review is closed with no blocking findings. The coordinator's broader integration gate and other owners' acceptance remain separate. No production modification, git operation, provider call, live probe, service activation or changes to peer tests were performed.

The reviewer suggested two optional additional regressions, without identifying a validation defect: (1) valid October 27 registration followed by explicit future `retrieved_at` in fetched provider metadata, to isolate post-fetch metadata admission; (2) changing only a persisted retrieval instant within October 27 on resume, to isolate provenance authentication from cutoff rejection. These were deliberately not added after the passing source was frozen for the coordinator. Current negative controls establish future rejection at registration; current positive controls establish real fetched timestamp persistence. The additional scenarios are not claimed as tested by this repair.

Next-session/coordinator prompt: Read this record and its final receipt. Verify `backend/tests/test_target_research.py` is still SHA-256 `71c43f06f98578bf4bd8353adce61cd368bf440bf6152a61111b6c59c2424eb5`, then rerun the original producer and mechanism scenarios or the full suite with a NEW evidence directory. Retain AS_OF=2026-10-27 and future-source rejection. The report shape fix is already green against report hash `ebeb1dcd577b5c729ec4cd2e071c34152ec5feb42b876fd77b5b96dbe83d26d0`; do not report its older failure as current. Obtain fresh acceptance for later source changes.

## 10. Updates

- 2026-10-28: Created before test edits with ownership, date invariants, boundary diagnosis and acceptance plan.
- 2026-10-28T03:56Z: Baseline guarded run reproduced 18 failures and 43 passes. Evidence root is `/private/tmp/drf-target-research-date-20261028-6n2z9oa5`; `baseline/junit.xml`, `baseline/completed.json` and `baseline-console.txt` preserve the failure. `source-hashes-before.json` and `test-before.py` capture the starting source. The fixture now shadows only `research_gateway.time` with a namespace retaining original timing functions and a controlled no-argument `gmtime`; explicit epoch conversion still delegates to stdlib. Four real-engine controls pair October 27 success with October 28 rejection under simulated October 28 and January 2030 ambient dates. No production file was edited.
- 2026-10-28: First control run: two valid controls passed; two negative controls exposed the new assertion's incorrect expectation of a fetch after early source rejection. Corrected only the owned test assertion and retained the failed receipt.
- 2026-10-28T03:57:21Z: Final actual target suite passed all 65 scenarios in 6.97 seconds. Full 12-file hash comparison showed no drift; final Ruff F,E9 passed. Recorded all guard activity, the frozen test hash and current report success, and sent the test hash/evidence to the coordinator through the current conversation.
- 2026-10-28: Independent read-only reviewer Raman confirmed the exact frozen hash and found no blocking findings. Recorded the two optional coverage suggestions and closed this fixture-only repair without changing the accepted test source.

## 11. Signal-child fixture repair — new authorized slice

**Started (UTC):** 2026-10-28T04:18:13Z. **Status:** Complete, verified on final source.

The user reports broad gate 149 at `/private/tmp/drf-target-broad-20261028-04`: 5,163 passed, 17 failed and two skipped. The only two research failures are the round-three real SIGINT/SIGTERM scenarios. Ownership now additionally includes `backend/tests/test_research_engine_v3_round3_robust.py`; all earlier production, provider, service and git restrictions remain. This section supersedes the earlier two-file ownership limit only for that explicitly granted module.

The broad JUnit traceback shows `_child` passing the checkout's `backend/` as subprocess cwd. The guard requires child cwd inside its writable evidence root, so launch fails with `GuardViolation: main offline guard blocked external_write` before either signal scenario executes. The generated temporary script is also not registered yet. Existing `Guard.allow_python_script(path)` hashes an exact trusted script, and GuardedPopen verifies that hash and wraps the child in the same runner before executing it. These APIs and the runner source must remain unchanged.

Acceptance criteria: reproduce both failures under a fresh guard; write the generated fixture in pytest tmp, register only that exact file after writing and before launch, use tmp cwd, and assert child guard installation before app/test imports. Preserve real `os.kill`, SIGINT restoration, no queued KIQs, no calls after cancellation, SIGTERM exit/status and closed progress-log assertions. Keep registration conditional so ordinary pytest remains supported. Run both signal cases and the complete owned module via the primary `-I -S -B` runner, then inspect every child receipt and exact source hashes. If real signal behavior fails, report the concrete production issue without replacing signals with mocks.

Evidence root: `/private/tmp/drf-target-signal-fixture-20261028-9l_4cywu`. `broad-baseline-extract.json` retains the two source tracebacks and original JUnit SHA-256. `source-hashes-before.json` and `test-before.py` capture the original module, unchanged clock fixture, guard and relevant engine sources.

Plan: reproduce the two launch denials, make the minimal `_child`/prelude fixture repair, run the real signal cases, run all module cases, and obtain scoped independent review and Ruff F,E9. Only this newly owned module and this continuity record will be edited.

- [x] Extract the two actual broad JUnit failures and inspect exact guard admission/wrapping behavior.
- [x] Reproduce both failures in a fresh guarded run. Both were denied with `external_write` in 2.17 seconds, before any child started.
- [x] Adapt exact temporary child registration and cwd without guard changes. Verification is pending.
- [x] Pass both real signal scenarios and the full module under the guard. Final module: 51 passed in 11.67 seconds, zero skips or deselections.
- [x] Review, lint, compare hashes and close this slice with reproducible evidence. No independent findings, Ruff F,E9 passes and no tracked source drift.

Signal-slice update: the fresh baseline is retained at `baseline/{junit.xml,completed.json}` and `baseline-console.txt`. `_child` now registers only its final generated `child.py` when an existing guard is present, then uses pytest's temporary directory as cwd. The generated prelude checks that the inherited guard is configured, with isolated/no-site/no-bytecode flags, before importing the engine fixture or application. Plain runs take the same subprocess route with no guard API requirement. Real signal delivery and all existing scenario assertions remain unchanged.

The first post-launch gate (`signals/`) reached both children but still failed both scenarios: each child receipt recorded one `blocked:process:os.kill`, because the existing guard permits a parent to signal its registered live child but denies nonzero self-signals. Both runs completed instead of cancelling; that is not evidence of a production signal defect because signal delivery was denied. The guard remains unchanged. The fixture now uses a temporary request file written by the first in-flight model call; the parent waits for that file and delivers the requested real SIGINT/SIGTERM with `Popen.send_signal` to its registered child. The worker still waits for real cancellation, and every original scenario assertion remains intact. Child lifetime retains the original 240-second bound, with kill/communicate cleanup on failure. This same parent-delivery path works with ordinary subprocess.Popen when the guard is absent; no signal handler or cancellation state is mocked.

The parent-delivery focused gate passed both original signal scenarios in 7.14 seconds at `signals-parent-delivery/`. Self-review then made request publication atomic (`.pending` followed by replace), preventing the parent from observing an empty file between creation and write completion. This later fixture byte state is captured in `source-hashes-acceptance-before.json` and will be accepted by the full module run; the earlier focused green remains historical evidence for the immediately preceding bytes.

### Final signal-slice verification and source freeze

The final source passed the complete **51-case module in 11.67 seconds**, with zero errors, failures, skips or deselections. Both preserved signal scenarios passed in that run: SIGINT in 2.219 seconds and SIGTERM in 2.464 seconds. Command:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-target-signal-fixture-20261028-9l_4cywu/module -q backend/tests/test_research_engine_v3_round3_robust.py
```

The final parent receipt has exactly two `allowed:guarded_child` events and exactly two hash-bound allowed scripts. No blanket script scope was added. The SIGINT child receipt exits 0 after the test catches the real KeyboardInterrupt; its persisted metadata is `failed` with `v3 engine interrupted: KeyboardInterrupt`, and no KIQ file was committed. The SIGTERM child exits 143, persists `failed`/`terminated` with a finish timestamp, and the existing test confirms the progress log closes. Both tests retain agents exactly `["K1"]` and zero calls after stop; the SIGINT test also confirms handler restoration. Both parent and child receipts preserve identity, record complete shutdown and empty source drift. Their event streams contain no blocked operations or network events in the final run. Parent signalling is permitted by the existing guard and was not mocked.

Ruff F,E9 passes on both owned Python test modules; output is in `ruff-final.txt`. All eight tracked source hashes match before/after the final module run. All 28 original top-level test functions have identical ASTs to `test-before.py`, independently confirmed by reviewer Raman. Only the generated child prelude, launch/signal synchronization helper and its `time` import changed. Conditional use of the installed guard retains the ordinary pytest launch path; the ordinary path was reviewed statically, while runtime acceptance was performed under the guard.

| Source | SHA-256 |
|---|---|
| Round-three module before repair | `3e16f15fbfada7c3c9ad55fe338e72d421dc74f42b395115e5dbb743f65fc455` |
| Round-three module frozen after repair | `e060c8ac0c1469874615f51803a8e3723d7699dc49f7ae82f7aaba2aad1a6c99` |
| Guard, unchanged | `5046cf820fa468d8e8ffb2e3fdade1d20fca2f0bd56ee15eabdff51c223c02be` |
| Prior clock fixture, unchanged | `71c43f06f98578bf4bd8353adce61cd368bf440bf6152a61111b6c59c2424eb5` |
| Final SIGINT generated child | `0df781621d4a0bcb964551ec8ef24bca9b6f4e24b30a10c22ed533f4694637d8` |
| Final SIGTERM generated child | `bfe817fad2e8100477b4a062e18bc4339113ec11c08ee9155a7340d6531e4a2b` |

Within `/private/tmp/drf-target-signal-fixture-20261028-9l_4cywu`, `module/junit.xml` and `module/completed.json` are the final acceptance receipts; `module/process-68639.json` and `module/process-68872.json` are the SIGINT/SIGTERM child receipts. `verification-summary.json` reconciles baseline, the denied self-signal attempt, focused green, final module green, exact generated script hashes, metadata and source drift. `source-hashes-acceptance-before.json`/`source-hashes-acceptance-after.json` identify all eight frozen files. `test-fixture.patch` captures the exact change without git. `independent-review.json` records the no-findings read-only review at the final module hash.

No production signal defect was reproduced after correcting fixture delivery; no production or guard source was edited. This closes the two research fixture failures only, without claiming the broad gate's other 15 failures are resolved. No additional provider, network probe, service or git operation was performed. The earlier clock fixture source remains frozen and untouched.

Next coordinator prompt: Read section 11, verify module SHA-256 `e060c8ac0c1469874615f51803a8e3723d7699dc49f7ae82f7aaba2aad1a6c99` and unchanged guard hash, then rerun the broad gate with a NEW evidence directory. Keep the generated child registration exact and retain real parent-to-child signal delivery. Do not restore self-signals under this guard or weaken the queued-work/status assertions.

- 2026-10-28T04:23:15Z: Closed the signal-child slice after original red reproduction, exact child registration/tmp cwd repair, actual parent-delivered signals, atomic request publication, 51-case guarded acceptance, Ruff, hash reconciliation and independent review with no findings.
