# Independent spending integration review

**Status:** Final spending code/offline review accepted on the17 frozen production pins. All concrete P1/P2 findings and technical verification gates are closed; coordinator documentation/delivery reconciliation remains separate. **Date:** 2026-10-29. **Scope:** Approved code-only, offline review of `codex/target-run-spending` against base `0d46ccbf`.

This reviewer owns only this file. No application code, provider/network calls, paid execution, deployment, scheduler activation, production data reads, commits or pushes are authorized. Existing owner receipts are historical evidence; current conclusions require source hashes and focused scenario evidence. The separate world-model overhaul remains a draft and is outside this review.

## Review brief and acceptance

Trace actual common admission, required ledger, parent/child physical calls, stop propagation, cancellation, resume, fork, deletion and completion. Check shared module/context identity, child operation registration, held parent lock, immutable authorization/source/routes, SDK retries and timeout workers, and private launcher isolation. Pair negative actual-call cases with valid controls. Retained maxima, observed usage, unknown transport outcomes and verified billing remain distinct.

The review will use the existing isolated offline runner, new `/private/tmp` evidence roots and exact allowlisted fixtures. Broad owner suites will not be rerun. Overall feature acceptance remains open until SB-02, SB-05, SB-08 and SB-12 prove the real producer paths.

## Progress

- Read the approved plan, frozen contracts, current handoff and initial owner reports. Concurrent changes are present; source-state drift must be recorded.
- Read the guard's isolation, source hashing and explicit child registration interfaces before running application code.
- Completed this checkpoint's lifecycle/child/export/launcher trace and focused checks. The P1 request-authority mismatch remains open. The launcher test defect was corrected concurrently by its owner and narrowly rechecked. Actual private bootstrap/composition is still owner work; this checkpoint does not wait for or replace it.

## Findings and evidence

### P1 — Mutable saved request could replace immutable authorization; closed by frozen-byte rereview below

`backend/app/services/run_spending.py:74–85` compares the normalized pipeline fields only with `state.options["spending_request_v1"]`, another mutable saved value. It does not compare either with the manifest's immutable `request_sha256`. `resume_bound` advances the generation using the original manifest proof without validating the saved request first. Changing both saved copies therefore passes the actual execution scope and permits physical calls for a different question under the original authorization.

Confirmed with the existing isolated guard and an in-memory debugger probe of the existing lifecycle fixture, with no source/test file edits. Common `PipelineOrchestrator.start` bound the valid request; `pipeline_scope` admitted a valid real `LLMClient.chat` → OpenAI SDK → HTTP MockTransport call. After changing the prompt and saved request copy, the same path dispatched again. Saving the changed state and calling actual `PipelineOrchestrator.resume` with the original request proof advanced to generation 2 and admitted a third call for the changed question. The fake HTTP callback independently observed committed attempt counts 1, 2 and 3. Full retained maximum was 360000 micro-USD under an unchanged 1000000 cap; no cap bypass or actual billing claim is made.

Evidence: `/private/tmp/run-spending-integration-review-request-20261029-03/request-binding-proof.json` and `request-binding-probe.txt`. Original request hash `01eeac051359c3e0d859f31b8738e9a351c4f363540fca33179fa77c255e1898`; admitted changed request hash `fbf263f69784e9f2c67fc9a76fb84103f92eb9b8df96768bf27c28a66a7ba835`. Reviewed runtime adapter hash `194277fe7071fcf09cfc8d57b5964dc51038e4300db3970b7b100d0fc8c6a881`; shared core `8036fc5428ee3f26470e500688b1690412c90ab8308e3bb9e6bb52c54f0efdf2`; parent SDK adapter `206874c1d4b1515c6e22e5804c49a0c384c5cc24f94dfe8140acea70658df878`; orchestrator `f9a0f2581ad659f1c612e10e8a1dbe5d0df5f31c2bf24a096c9b28d6c70413b8`.

The probe's JSON assertions succeeded. The enclosing existing test subsequently failed its original launched-thread count because the probe intentionally added a resume. That JUnit failure is instrumentation interference, not the defect's assertion and not a clean suite pass. Reproduction: run the prescribed interpreter/guard with a fresh evidence directory, `-q -s --trace backend/tests/test_run_spending_lifecycle.py::test_direct_start_binds_before_launch_and_cannot_start_twice`; stop immediately before its duplicate-start assertion, then execute the saved probe text in `dict(globals(), **locals())`, supplying `REVIEW_SOURCE` as the probe text for the receipt. The review receipt, actual HTTP callback entries and mismatch hashes establish the defect independently of the enclosing test's later assertion.

Required correction: validate the normalized saved request against immutable authority before resume changes generation and at execution admission. Regression must pair unchanged-request actual SDK sends with changed prompt/path/period/seed denials before transport. The initial probe in `…request-20261029-02` used a response fixture with the wrong served model and correctly halted unknown; it is a fixture mistake, not evidence for this finding. The corrected probe explicitly returns the admitted model.

### P2 — Launcher checkpoint regression was stale; corrected during review

Focused gate `/private/tmp/run-spending-integration-review-20261029-01` returned **12 passed, 1 failed**. `test_child_preserves_validated_checkpoint_and_count_budget_controls` calls `launcher.child_controls` without the new required `argv` argument, raising `TypeError` at `backend/tests/test_run_spending_launcher.py:258`. The current function also validates the registered pipeline handoff and resume switches/generation, so this test needs real coordinator argv and matching authority metadata, not just an added arbitrary argument. Existing tests and the historical 65-case launcher gate do not prove the current checkpoint boundary.

The passing focused cases cover shared module/ledger identity, actual child model/search/scrape adapters, timeout halt, lost context, nested tool workers, typed-stop propagation, registered child operation export, OpenAI SDK JSON/body matching, actual common start/configured child command, and parent lock/interrupt cleanup. The child model factory in these repository tests remains a test double; installed LangChain and a private process are separate evidence obligations.

Concurrent owner update: the launcher test file changed from `b441478ce3573b717de97f8b22d31807a045f1be447dbb6d8ebdd50f5b791230` to `aeefd26cdd551fcc6f62f634a66d97d6e332f2c0a3399662a7f2fa94f04d79e3`. It now supplies actual parsed child argv, generation 2, and the pipeline-owned handoff path. `/private/tmp/run-spending-integration-review-launcher-fix-20261029-06` passed **5 checks in 1.56s**: the checkpoint valid/escaped-path case and four effective-profile drift denials. Exit 0, completed shutdown, no blocked events, preserved identity and no runner-tracked source drift. This closes the stale-test finding; the original failure remains preserved. Launcher production bytes also changed concurrently (see source identity below), so this is not a full launcher rereview or SB-12 acceptance.

## Additional verification and boundaries

- `/private/tmp/run-spending-integration-review-fences-20261029-04`: **6 passed in 2.62s**, exit 0, completed shutdown, preserved identity, no source drift or blocked audit events. Selected only clean-resume retention/stale response fence, registered-child exit prerequisite, committed environment adoption, concurrent old-reader/new-generation behavior, cancellation-before-event and estimator spending-stop propagation. The estimator fixture replaces the gateway and therefore does not alone close SB-05's actual raw-call requirement.
- `/private/tmp/run-spending-integration-review-cancel-20261029-05`: valid real SDK/mock-HTTP control followed by missing-ledger cancellation. The actual `PipelineOrchestrator.cancel` returned `cancelling` and signalled the installed event while the DB remained absent. Restoring the same inode did not clear the stop: the next execution scope raised `storage_unavailable`, no second HTTP callback occurred, and all 120000 micro-USD remained retained. `cancel-missing-ledger-proof.json` and `cancel-missing-ledger-probe.txt` record the scenario. The enclosing existing test passed; no real child kill was attempted or proven by this fixture.
- Read the supplied installed-LangChain proof `/private/tmp/run-spending-actual-langchain-20261029-02/actual-adapter-result.json`: eight actual ChatOpenAI/OpenAI SDK mock HTTP callbacks, eight ledger attempts, 66112 retained micro-USD, no extra cache calls. Its source hashes match current core and child adapters. The participant is `parent`, so this establishes the adapter path but not the separate-process child composition. This review did not rerun that owner proof.
- Guard accounting: focused run 01 blocked `uname` and one unregistered subprocess probe; no network event was recorded. The debugger probes each blocked one attempted `~/.pdbrc` read before execution; the file was not read. Owner LangChain proof 02 records two blocked socket constructions **and** two blocked subprocess attempts. None of these are zero-attempt receipts or successful provider access. The supplied billing evidence is synthetic/mock provider usage, never verified billed cost.

## Acceptance disposition and next bounded work

**Current disposition: accept the approved spending code/offline implementation for coordinator delivery.** The final closure section below supersedes the earlier pending-gate status: workflow-current05 proves the corrected actual producer composition and supported backend resume, composed-final-b passes all1201 selected cases, and the affected launcher comment-annotation gate passes86 on its current test bytes. Saved-state P1, child-request P1 and CR-qualification P2 remain closed. Arbitrary partial-research/child auto-resume remains unsupported. Startup06/07/08 and earlier owner totals stay historical; this verdict grants no live spending, deployment or scheduler authorization.

The next action is to integrate the final process-composition/bootstrap receipts on the reviewed core/coordinator pair, preserving the original red proof and the closure evidence. No provider tariff, paid execution, scheduler, deployment or production-read authorization follows from any of these offline results.

## Source identity at original checkpoint (historical)

The following production hashes were taken before the focused checks and matched at checkpoint close, except the explicitly moving launcher. Only this review Markdown was edited by this reviewer. Synthetic test artifacts and receipts were written only within the new guard-owned evidence directories. The lifecycle test changed concurrently from `3a12bf0c8a371675052f016b86b9b8158008b473ef3e973bfb8a061b34e050d4` at initial inventory to `08a54c5dcaa44ba7d91b8905672a3be9413a2ac0e28907a495e2d1279899d451` before the request reproduction; its own receipt records the latter. No uncommitted owner changes were reverted, staged or committed.

| Source | SHA-256 |
|---|---|
| `backend/app/services/run_spending.py` | `194277fe7071fcf09cfc8d57b5964dc51038e4300db3970b7b100d0fc8c6a881` |
| `backend/app/services/pipeline_orchestrator.py` | `f9a0f2581ad659f1c612e10e8a1dbe5d0df5f31c2bf24a096c9b28d6c70413b8` |
| `backend/app/services/target_pipeline.py` | `27d18001122197222a498b67ab048b9af1924740801df4aa6e29d202dc714b44` |
| `backend/app/services/target_simulation.py` | `90adc288b569cc5822117effe274fe5660a281ed97b41ce19ec65a66381e0903` |
| `backend/app/services/forecast_tournament.py` | `91e0236fe37ec633bd17ce0f16a6b420c2100607b96dc2e418d7ce13a7f5ad91` |
| `backend/app/utils/llm_client.py` | `206874c1d4b1515c6e22e5804c49a0c384c5cc24f94dfe8140acea70658df878` |
| `deerflow_bridge/run_spending.py` | `8036fc5428ee3f26470e500688b1690412c90ab8308e3bb9e6bb52c54f0efdf2` |
| `deerflow_bridge/research_gateway.py` | `dd678ec3961cc0f1ab6d2380182403ee3a93ec4bbe428150fe732a25a743b7fa` |
| `deerflow_bridge/linear_research.py` | `d2880630a845bab1640c38268ddb235a47d678006015df94133cc6b336e2d6ca` |
| `deerflow_bridge/search_tools.py` | `5a21e658d4445be846aea3c99fad6079923e637775fe6be30627620c0add4009` |
| `deerflow_bridge/cached_fetch.py` | `2fa98dcf79fdc6f24cee74b7d7c4c299d6e943a4947ed63e95b8205d1b58b94e` |
| Existing offline runner | `5046cf820fa468d8e8ffb2e3fdade1d20fca2f0bd56ee15eabdff51c223c02be` |

Launcher source was `641feba17718a14dabbd9d22ba2c840163bd89c56d88a51e9438acb9e7b0f147` during the initial trace and changed to `3c06361cd49c25a69b21f6660ae6cd2d10f53f1ee157bd6daac9d9cd06545408` by checkpoint close. Its current private-bootstrap proof is not frozen by this review. The existing runner tracks selected tests and redirected modules, not every imported production file; these explicit production hashes avoid treating its empty drift list as complete source coverage.

## Accepted P1 correction and frozen-byte regression criteria

2026-10-29 user update: P1 is accepted. The core owner is adding public `validate_bound_request(binding, request)` using the existing validated transaction and immutable manifest request hash. It must not rebind, raise/reset the cap or refresh allowance. The coordinator will check normalized actual state and the saved request copy before `resume_existing` and at `_run` admission before providers. These are planned corrections, not verified closure. The user will notify the source freeze; this reviewer will execute only the affected focused checks once that freeze is supplied.

Required regression evidence:

1. An unchanged normalized request passes common start and actual parent `LLMClient`/OpenAI SDK mock-HTTP dispatch. The parent-resume valid control must first have receipt-valid completed research and sealed case, evidence and estimators. After a recoverable non-spending pause and explicit matching core resume proof, only the supported downstream parent work resumes under the same immutable request, pipeline and cap, retaining all prior reservations. It must not launch or resume the research child.
2. Corrupt actual pipeline fields alone, `spending_request_v1` alone, and both together. Cover the reproduced changed-question case and bounded path/period/seed cases. Each negative fixture is independent because refusal can terminally halt authority. Assert zero additional raw HTTP callbacks and ledger attempts; do not repair the saved copy to make it agree.
3. Before-resume rejection must leave generation, immutable request hash, pipeline binding, cap and retained maxima unchanged. A terminal denial event/state is permitted. The original valid resume proof cannot authorize the corrupted request. Old-context attempts remain fenced, and an identical proof cannot be replayed as a fresh resume.
4. Exercise the actual Flask `POST /api/research/<pipeline_id>/resume` handler against a persisted bound pipeline whose saved request copy is corrupted, alongside an unchanged-request valid control. Both must otherwise satisfy the completed-research/sealed-artifact prerequisites, so an incomplete-research refusal cannot mask the immutable-request defect. Use the real common resume and execution admission hooks. Capture the API response, task/thread launch counts, before/after authority and HTTP callback counts; a failure in fixture setup or an unrelated preflight check is not proof of the new immutable-request guard.
5. Capture pre/post production and test hashes, JUnit/completion receipts, guard attempts and the raw mock-call/committed-attempt correspondence. Use the existing isolated runner with a fresh evidence root and exact fixture allowlisting. Keep the original red evidence immutable. Code/test-file ownership stays with the assigned owners; this reviewer writes only review.md and authorized temporary evidence.

The user also reports Carver's actual child-startup positive proof with eight rows and 66112 retained micro-USD. Its exact rerun is pending. This new report is acknowledged separately from the earlier standalone LangChain proof; this reviewer has not yet verified its artifact paths, child participant identity or frozen-byte coverage. SB-02/SB-12 remain open pending that evidence.

## SB-08 supported resume subset — user decision, 2026-10-29

The launcher review found that the existing v3 automatic resume path lacks a frozen checkpoint proof supplied by the actual producer. The user chose to fail closed for `_child --resume` and existing v3 handoff/checkpoint reuse. Do not synthesize a legacy checkpoint ID or infer provenance from an existing file or environment value. Fresh-profile behavior is unchanged; this restriction concerns reuse of prior research state, not the mere creation of the fresh run's handoff directory.

Parent clean resume is supported only after receipt-valid completed research, with sealed case, evidence and estimators. It additionally requires explicit core proof, the same immutable normalized request, pipeline identity, source/routes and cap, retained prior reservations, no unresolved unknown attempts, and verified exit of prior participants under the parent lock. Completed research does not mean a closed/completed spending authorization can reopen; terminal cancellation, unknown, exhaustion and closure remain terminal.

| Scenario | Required producer-path evidence |
|---|---|
| Fresh private child | Existing fresh-profile positive control still reaches actual mock SDK/tool calls with registered operation/source identity; no resume metadata is invented. |
| Explicit `_child --resume` | Refuse before child research/provider work, even if a plausible checkpoint ID and generation are supplied. No additional physical call or debit. |
| Implicit reuse of existing v3 handoff/checkpoint | Refuse the automatic reuse path without synthesizing provenance or falling back to an unbound/legacy run. No additional physical call or debit. |
| Parent resume with incomplete research | Deny before `core.resume_existing` advances generation or creates a resumed task/thread. Same cap and retained maxima; no child/provider invocation. |
| Parent resume with missing, changed or unsealed case/evidence/estimators | Deny before generation advance; a mutable completed-stage flag alone is insufficient. |
| Valid downstream parent resume | Verify completed research receipts and artifact seals, apply explicit matching core proof, retain the same request/pipeline/cap/debits, reuse research without child launch, and reach an actual parent SDK mock send for permitted remaining work. |

The earlier raw core resume checks and historical launcher checkpoint-carrier test remain evidence for their original scopes only. They do not prove partial-research resume is supported. The revised positive control must satisfy the sealed-research subset; acceptance wording and final SB-08 receipts must state this limitation explicitly. Implementation and focused regression results for this decision remain pending the announced source freeze.

## Frozen-byte P1 closure and updated evidence — 2026-10-29

**Verdict: close P1 for core `b54cac7c…` plus coordinator adapter `796a7a2e…`.** The original red proof remains intact. The core's public `validate_bound_request` at `deerflow_bridge/run_spending.py:622` uses the existing validated transaction, requires the bound pipeline identity and compares the canonical request hash with the immutable manifest. Success does not mutate binding, generation, state, cap or reservations. The coordinator's `_validate_state` first requires actual normalized fields to equal the saved copy, then invokes that validator (`backend/app/services/run_spending.py:87`). `pipeline_scope` calls it before execution/providers; `resume_bound` calls it before research-seal admission and before `resume_existing`. Thus saved-copy-only corruption fails equality, while matching corruption of both copies fails immutable authority.

The supported-resume check also verifies completed research through `target_pipeline.validate_stage`, whose required research receipts include case, evidence, estimators, library, library publication and research report. A completed-stage flag alone is insufficient. This satisfies the user's narrowed parent-resume precondition without admitting child/partial-research resume.

### Fresh independent focused execution

`/private/tmp/run-spending-integration-review-p1-closure-20261029-07` passed **7 cases in 3.74s**, exit 0, completed shutdown, preserved identity and no blocked audit events or tracked drift. It selected only:

- Four prompt/path/period/seed mutations of actual state and saved copy. Each valid `LLMClient` → actual OpenAI SDK → HTTP MockTransport call succeeded first; the changed request then raised `binding_conflict`, with one physical callback and one retained 120000-micro-USD reservation.
- Changed-request resume denial before generation advancement or a new launched thread.
- Incomplete/unsealed-research resume denial before generation advancement.
- Real target-pipeline research sealing followed by a controlled recoverable compute failure, then explicit same-cap resume retaining prior debits and denying an unaffordable next attempt.

The last case uses the existing deterministic research/method fixtures and a direct store attempt; it is not by itself real parent SDK proof across resume. The separate HTTP/SDK probe below supplies that boundary. The reported 17-case owner lifecycle gate, 93-case core gate and 78-case launcher gate were also inspected from their JUnit/completion receipts, not rerun broadly. Their counts, successful exit/shutdown and guard activity match the owner reports. Core crash fixtures' intentional exit71/72/73 remain expected outcomes.

### Actual HTTP resume plus SDK pre/post control and copy-corruption denial

Evidence: `/private/tmp/run-spending-integration-review-api-closure-20261029-08/api-request-binding-proof.json` and `api-request-binding-probe.txt`.

The independent in-memory probe used the existing lifecycle fixture under the unchanged isolated guard; no source or test file was edited. It performed a real parent SDK/mock-HTTP send, executed the actual target pipeline to seal research, and injected a recoverable compute failure. It then called the real Flask `POST /api/research/<pipeline_id>/resume` route with unmodified preflight and common resume hooks. The valid response was **200** and generation advanced from 1 to 2 under the same manifest, pipeline and 1000000-micro-USD cap. A copied old-generation context raised `stale_generation` before HTTP, while the current context successfully sent through the real SDK. The two callbacks independently read committed `unknown` attempt rows before returning their synthetic responses; total retained maximum was **240000 micro-USD**.

Running the resumed target pipeline reused the sealed research without a second research acquisition and reached the controlled compute failure again. The probe changed **only the persisted `spending_request_v1.prompt`**, leaving actual prompt, valid research receipts and six artifact hashes intact, and supplied a fresh matching proof for the current generation. The real HTTP handler returned **409 with `binding_conflict`**. Generation stayed 2; the launch count stayed 2; physical sends/attempts stayed 2; cap, manifest, pipeline and retained240000micro-USD were unchanged. Only the terminal state became `halted_error`, as expected. This is the actual request-copy corruption proof, not an unrelated preflight rejection.

The corrected probe is saved as text for reproduction. Its initial invocation omitted a local `hashlib` import in receipt collection after the first compute failure; the import was added in the in-memory namespace and execution continued from that point without replaying a send or changing application code. To leave the enclosing original duplicate-start check meaningful, its debugger-local `bound` and baseline launch count were refreshed to the current generation/count before continuation. The probe's own assertions and JSON receipt establish closure; the enclosing existing test also passed. Guard completion is exit0 with preserved identity and no tracked drift; one attempted `~/.pdbrc` read was denied, and no network event was recorded. No fresh-process restart or actual research child is claimed by this probe.

### Private startup06 evidence and source-coverage limit

Read actual startup06 parent/app/child result and completion receipts. App and child exited0 under private `-I -S -B` execution. The child has 28 actual harness origins, preserved argv/ownership metadata, eight mock HTTP calls/eight observations and **66112micro-USD** retained. Participant `research-bootstrap` has a persisted operation hash and a verified exit receipt; the parent closes the same ledger. This is stronger than the earlier standalone parent-participant LangChain proof. The long research stage is deliberately replaced by the bounded actual SDK/tool exercise; it is not a whole research workflow run.

All process receipts report completed shutdown, preserved identity and no tracked drift. The child receipt contains two denied socket-construction probes and two denied process-discovery probes; these are not zero attempted operations or provider charges.

**Remaining source alignment:** hashing the staged files confirms both private core copies are `b54cac7c…` and the launcher is current `a074dfe3…`, but `startup06/runtime/app/backend/app/services/run_spending.py` is **`194277fe…`**, the pre-P1 coordinator adapter. Current worktree adapter is **`796a7a2e…`**. Startup06 therefore proves actual bootstrap and child adapters on its recorded tree, not private execution of the repaired coordinator. Final composition/private acceptance must include the repaired adapter hash (or an explicitly bounded supplementary private proof of that adapter). Do not relabel startup06 as exact-source full-feature acceptance merely because its core hash is current.

### Refreshed source hashes

The following hashes matched before and after this rereview's focused execution. Unchanged production files in the original checkpoint table were rehashed and still match that table; changed/current identities are listed here. Startup06's older coordinator copy is excluded from the current-pair closure.

| Source | Current SHA-256 |
|---|---|
| `deerflow_bridge/run_spending.py` | `b54cac7c001c5f46106e3593e7a5ad4f66a6711488bd5679fee0f35ec889f9d5` |
| `backend/app/services/run_spending.py` | `796a7a2ec63001b1bd62e077db527956be4211f2f94a80123e393f90660ac01a` |
| `backend/app/services/pipeline_orchestrator.py` | `f9a0f2581ad659f1c612e10e8a1dbe5d0df5f31c2bf24a096c9b28d6c70413b8` |
| `backend/app/api/research.py` | `38276efdd90fee13caf3c7deeb8577dd4192dc97fdf602a940e8b6255ad58dbf` |
| `backend/tests/test_run_spending_lifecycle.py` | `1d0c54fccbcd791db35d0c5e03bf42658e6e0e9904e0f99497edf92045541d7f` |
| `backend/scripts/target_acceptance_run.py` | `a074dfe3de5ec26f3f570796da9dac758c67cb87e779cf062e3c338c86a7c17b` |
| `backend/tests/test_run_spending_launcher.py` | `5ffdb7eb39da1ce2decabe2c3eab4654a9a989684f7458f48d8edfc618c20971` |

No new application-code P1/P2 was established in this narrow correction rereview. Final process composition, restart and source-aligned private acceptance remain open; P1 closure does not imply one-feature completion or live/billing authorization.

## Process-composition interface follow-up — 2026-10-29

The user requested Carver's exact-current startup07 rerun and Confucius's actual post-research backend-resume extension. Production source remains frozen unless a concrete finding requires a change. P1 remains closed for the reviewed b54/796 pair; this follow-up concerns final evidence coverage.

The current workflow interface correctly separates `_resume` / `proof_scope="core_resume_with_real_parent_transport"` from `_backend_resume` / `proof_scope="backend_resume_after_sealed_research"`. The former proves only store takeover plus the raw parent adapter and receives no full SB-08 credit. The new backend path invokes actual `PipelineOrchestrator.resume` and `_run` in a different PID, checks real research/prepare artifact receipts, forbids re-running research and estimator producers, captures scheduled-worker counts, and compares artifact hashes. Its new tests are still owner work; this reviewer read the source but did not execute or accept their pending receipts.

### SB-08 coverage gap: current backend negative cannot distinguish retained from reset allowance

At workflow-test hash `af468947b7f3568f4a85750df2e2fa05defe4de7e6731938112bb64c1bdab8aa` and child-fixture hash `782401f2d9b1a534043bf06eb5745c3d49a8f4ebf2efcb30a98dbe4f0031bd36`, `test_fresh_pid_backend_resume_requires_sealed_research_and_retains_cap` uses cap `1.00`, retains600000micro-USD, then expects `budget_exhausted` at the actual actor callback. `_prepare(..., resume=True)` prices both input and output at USD1000/million with input ceiling100. The real `target_pipeline._decision_provider` fixes output at1800 (`target_pipeline.py:328`), so that attempt's quote is1900000micro-USD. It exceeds both remaining400000 and the entire1000000 cap. The zero-send result therefore cannot show that retention, rather than an inherently unaffordable request, caused this backend denial.

This is a source-level test-coverage finding, not an observed runtime defect or a claim that debits were lost. Required acceptance correction: make the negative quote affordable against the original cap but unaffordable after the real earlier debit, and pair it with a fresh-process, sealed-research backend-resume control that actually sends. For example, keeping this tariff and real1800-token actor request, a2000000 cap with600000 already retained leaves1400000: the1900000 quote then distinguishes retained allowance from a reset. Use a separate sufficiently funded valid control, preserving immutable per-run caps and full raw-call/committed-row checks. Do not change a live fixture's cap, invent checkpoint provenance, or substitute the core-only restart result for this missing backend control.

Final integration will require startup07's complete parent/child receipts and staged coordinator hash796a7a2e…, the workflow's exact source hashes, raw parent/registered-child attempts reconciled with one ledger, actual backend resume/reuse and old-generation fencing, and the supported-subset negative/valid controls above. Startup07 has been requested but is not marked accepted here without its completed evidence. No broad suite or partial owner fixture was run in this interface update.

Coordinator-accepted synthetic test correction, 2026-10-29: Confucius is implementing a backend-resume negative with cap2000000micro-USD, prior retained600000, remaining1400000 and the unchanged production actor request quoting1900000 under the fictitious test tariff. The paired valid control uses cap5000000 and must reach actual SDK dispatch and report publication after sealed-research resume. All amounts, caps and tariffs in these scenarios are fictitious test inputs only; coordinator test instructions are not human paid-run authorization. The only human approval is the2026-10-29 code/offline implementation approval, which authorizes no live USD2/USD5 cap or other expenditure. The production output maximum must not change to accommodate the test. The core-only600000+600000-under1000000 case remains separately labeled store recovery evidence. This is an accepted test-coverage correction; no production source defect or lost debit is implied. Await exact-current startup07 and the corrected workflow's frozen receipts before integrating or granting further acceptance.

## Child prompt scope and CR input qualification — 2026-10-29

The separately reported child prompt-file gap is distinct from the closed saved-state P1. At launcher hash a074dfe3…, `child_argv` and `child_controls` validated location/options, while actual `deerflow_research.main` read the mutable file with UTF-8 `Path.read_text(...).strip()` and passed that question into v3. The parent compared the resulting case question only after research returned. A stale/incorrect producer file was therefore a real scope boundary; no malicious-administrator assumption is needed. This review traced that source path without duplicating Carver's assigned negative reproduction.

Current source inspection shows exact prompt-file qualification in the launcher: size matches the approved UTF-8 encoding, bytes decode strictly, and the resulting string must equal the immutable approved prompt. It does not strip, replace invalid bytes, normalize Unicode or rewrite rejected content. A separate child in-memory request guard is now present in `linear_research.py`; its changed hash must also be included in final private proof. These observations are not yet independent final runtime acceptance.

**Coordinator-directed bounded input qualification:** the actual research script's text read normalizes CRLF and CR. Rather than silently rewriting an approved request, `check_request` now rejects any CR character before preparation creates the runtime and before any authorization exists. LF multiline Unicode remains supported and must arrive unchanged. This narrows admitted input only; it changes neither cap arithmetic nor route scope and grants no paid-run authority.

The source contains two CR/CRLF preparation negatives asserting no runtime root is created, an exact LF multiline Unicode `child_argv` control asserting unchanged bytes, and valid/mismatched/invalid-UTF8/newline/BOM prompt-file cases. The latter uses an instrumented script/core-dispatch substitute; it is not the actual private script/SDK proof by itself. Final closure must include the actual script-read/in-memory question path and valid real-SDK/mock-HTTP control on the new bytes, together with zero-dispatch negatives. Preserve prior receipts without treating them as evidence for a later source hash.

Source identities observed in this update:

| Source | SHA-256 |
|---|---|
| Launcher with CR qualification | `61e48f2685de6f8b987dcf1abcb9639f67032326c3fe8c61f3c2a85379f3748d` |
| Launcher tests | `468da02c7aa498838c190d1e48bae5b6794ba71086bf465baf551c46f6d06847` |
| Child linear engine | `54c489fbe41e424689fc2722cf2376a8eb0f934c2abdd0bdb611932378bde44c` |
| Actual research script | `844ac35d58d4fe43b5f00c0947c20b7373dc25217b175a0989a4b3b97136bdb8` |
| Parent orchestrator | `38d0800566d78a7df2dca810abd4e2a36ba77bc2eacb1e36c667898b36d09bc7` |
| Coordinator adapter | `796a7a2ec63001b1bd62e077db527956be4211f2f94a80123e393f90660ac01a` |
| Shared core | `b54cac7c001c5f46106e3593e7a5ad4f66a6711488bd5679fee0f35ec889f9d5` |

The coordinator reports startup08 as historical following this input qualification. Final private acceptance now requires a fresh root staged from the newly frozen launcher/child sources and the stable parent38d080/coreb54/coordinator796 set, with pre/staged/post hashes and complete guard/process receipts. Startup07/08 are not relabeled as current proof. No independent test suite, private runtime or provider was executed in this update; only source and existing records were inspected.

## Startup09 independent closure — 2026-10-29

**Verdict: close the child prompt/request P1 and CR/CRLF input-qualification P2 for the bounded code/offline profile.** The separate saved-state P1 remains closed. Accept startup09's exact-source private bootstrap/import/child-transport proof at the hashes below. This does not close the pending composed workflow, grant full SB-08 credit to core-only restart, expand routes/inputs, or authorize paid execution. The parallel workflow-packaging audit is outside this review.

### Independent source and receipt checks

Read `/private/tmp/run-spending-private-startup-09/exact-source-before.json`, `exact-source-after.json`, `runtime/actualimports.json`, `runtime/private-startup-result.json`, all four process receipts and final `runtime/completed.json`. Independently rehashed each of the twelve listed current and staged files and compared them with both recorded hash sets: **12/12 match**. Verified all eight recorded service origins are inside R/app and freshly hash to the recorded values. Also checked the deployed child copies of `run_spending.py` and `linear_research.py`; they match the current reviewed sources.

The parent/app/child/import-probe receipts all report exit0, completed shutdown, preserved identity and no tracked source drift. Parent records two explicitly allowed fixture launches. App and the supplementary import probe record no attempted-operation events. Child `process-4421.json` records **two denied socket-construction probes plus two denied subprocess-discovery probes**. These remain blocked attempts, not absent activity or successful provider requests.

Independently opened startup09's SQLite ledger read-only: pipeline `pipe-private-startup`, generation1, immutable synthetic cap1000000, state `closed`; **8 distinct attempt IDs, total retained66112micro-USD**. All eight belong to registered participant `research-bootstrap`: six model attempts retaining6112, one search retaining50000 and one scrape retaining10000. Every outcome is `response_observed`; the child has an operation hash and verified exit receipt. The reported usage is synthetic provider-reported usage, not invoice evidence. The auxiliary import receipt reports the closed ledger unchanged; no new provider exercise was performed by this reviewer.

### Actual-consumer fidelity

Read the staged/current private fixture. It executes the real research script main/CLI and prompt-file read, then calls the real `linear_research.run` with that consumed question. `_validate_spending_request` executes before the substituted bounded `AdapterExercise` engine is constructed. The engine constructor asserts the consumed question equals the immutable checked request. Its transport exercise uses actual harness configuration, bound factory, installed ChatOpenAI/OpenAI SDK, gateway, Firecrawl and ledger with HTTP MockTransport. The child receipt confirms `in_memory_request_checked_before_engine=true`, unchanged argv, isolated/no-site execution, eight raw mock calls/eight attempts, retained66112, and no additional cache calls.

The long research engine is bounded by a test substitute. This proves the actual question-consumption/admission boundary plus real SDK/tool adapters, not a full research run or parent-estimator/actor workflow. Actual imports of eight parent services establish private origin compatibility, not execution of every imported method.

### Fresh focused reviewer gate and preserved owner evidence

`/private/tmp/run-spending-integration-review-child-closure-20261029-10` passed **17 checks in4.18s**, with zero failures/errors/skips. Its completion receipt reports exit0, completed shutdown, preserved identity, no tracked source drift and no blocked audit events. Selected only:

- Five fully bound prompt-file variants: valid, same-length different question, invalid UTF-8, trailing newline and BOM. Invalid files fail before imports/script/send, leave bytes unchanged and create no attempt. The valid instrumented script/core-dispatch control commits one attempt before its fake send.
- CR and CRLF preparation refusal before a runtime root exists, plus the exact LF multiline Unicode/unchanged-byte argv control.
- Seven actual `linear_research.run` loaded-request negatives (question, missing carrier, model, depth, language, authority and output directory), all before gateway construction/attempts; the approved-scope validation control leaves authority and carrier unchanged.
- The existing real-engine transport-stop control, which reaches its model-call seam with valid scope and then preserves the typed unknown-outcome stop.

The reviewer did not rerun the whole86-case launcher or706-case child owner suites. Inspected the original prompt red01 JUnit/completion (**four failures, one passing valid control**) and final prompt-green-04 (**86 passed in9.678s**, no failures/errors/skips, clean completion and no blocked events). The early prompt red/green uses an instrumented runpy/core-dispatch seam; the startup09 positive supplies actual script/installed-SDK fidelity. The fresh focused gate confirms both early and actual in-memory denial boundaries on current bytes. Startup08 and earlier evidence remain unchanged and explicitly historical.

### Final source identities for this closure

These critical sources matched before and after the reviewer's focused gate; the twelve-file startup09 map additionally covers the unchanged target/tournament services. The historical61e48f launcher snapshot above is superseded only for current acceptance, not erased.

| Source | SHA-256 |
|---|---|
| Launcher | `478b2ba636c437c3e707d39453b66ee73bf43e40b84dad09aacb5cf3d2c25612` |
| Launcher tests/private fixture | `468da02c7aa498838c190d1e48bae5b6794ba71086bf465baf551c46f6d06847` |
| Child linear engine | `54c489fbe41e424689fc2722cf2376a8eb0f934c2abdd0bdb611932378bde44c` |
| Child transport tests | `685a48678de1231b5295da1e014a65668409008540d0a947d42d6e4449c4ff65` |
| Parent orchestrator | `38d0800566d78a7df2dca810abd4e2a36ba77bc2eacb1e36c667898b36d09bc7` |
| Coordinator adapter | `796a7a2ec63001b1bd62e077db527956be4211f2f94a80123e393f90660ac01a` |
| Shared core | `b54cac7c001c5f46106e3593e7a5ad4f66a6711488bd5679fee0f35ec889f9d5` |

No outstanding P1/P2 remains from this child-request/input-qualification/private-source review. Final composed SB-02/SB-05/SB-08 workflow acceptance remains separate. Only this review file was edited in the repository; fresh test evidence was confined to the new guard-owned temporary directory. No production-source edits, provider access, private-runtime reprovisioning, scheduling, deployment or commits were performed.

## Final current spending gate list and reviewer verdict — 2026-10-29

**Final verdict: ACCEPT for the approved code/offline spending scope at the frozen production manifest below. No concrete source P1/P2 or technical spending acceptance gap remains.** Subsequent World Anchor implementation and the parallel workflow-packaging audit are separate work. This reviewer made no production/test-source edits, ran no new suites in this final closure interval, and performed no commits, provider calls, deployment or scheduling. Coordinator delivery documentation and Git/issue reconciliation are not asserted complete by this verdict.

### Closed current gates

| Gate | Exact evidence | Result / scope |
|---|---|---|
| Frozen production identity | `/private/tmp/run-spending-final-source-20261029.json` | All17 files freshly rehashed and unchanged; manifest SHA-256 `d103d25ec45d898dfadb2c60faf81efe3f5046ac38bd6a9c1d52f6af5ecbdd6c`. |
| Full selected integration/compatibility | `/private/tmp/run-spending-composed-final-20261029-b` | **1201 passed in67.484s**, zero failures/errors/skips; exit0, completed shutdown, preserved identity, no tracked drift. Includes93 core,83 parent,61 child,18 lifecycle,86 launcher and the selected target/legacy tests. |
| Actual registered-child/parent composition and backend restart | `/private/tmp/run-spending-workflow-current-20261029-05` | **8 passed in49.274s**; all8 registered children exit0. Every one of the8 case receipts has the same15-file source map, freshly matched to current sources with no differences. |
| Private bootstrap and question-consumption boundary | Startup09 receipts described above | Actual private app/child exit0;12 pins/8 private service origins; actual in-memory guard before bounded SDK engine;8 attempts/66112 retainedmicro-USD/closed ledger. Production sources still match. Fixture-byte annotation caveat below. |
| Fresh-import fixture correction | `/private/tmp/run-spending-import-isolation-green-20261029-a` | **3 passed in1.445s**: canonical alias identity, foreign-source collision denial and backend-only fresh import. No core/app/guard change. |
| Current launcher-test annotations | `/private/tmp/run-spending-launcher-final-lint-20261029-a` | **86 passed in10.045s** on current test hash1045fa45…; exit0, complete shutdown, no blocked events or tracked drift, preserved identity. |

Composed-final-a is preserved as **1200 passes plus1 fixture failure**. The failing test artificially deleted the `deerflow_bridge` package aliases but left short alias `run_spending`, so its newly executed same-source core correctly raised the duplicate-identity denial. The test-only repair uses one predicate to snapshot/remove/restore both aliases, asserts fresh aliases share one object, cleans newly imported aliases in `finally`, and asserts original objects and sys.path are restored. Reviewed test hash: `93cb587ae874bfa4cdec7777613ddefa2a9a4ff521066c82cce25e3ace2ba065`. Production core duplicate/foreign-source denial is unchanged and still exercised negatively. B pins the repaired test and closes the integrated failure.

### Corrected workflow proof accepted on current sources

Workflow-final04 was behaviorally valid for its earlier source snapshot but had later drift in orchestrator, linear engine and child tests. Current05 resolves that gap with current38d080/54c489/685a486 sources. Independently read its eight case receipts and reconciled each raw-entry/verified journal with the read-only SQLite attempts: zero violation records, equal entry/verified/attempt counts, exact unique attempt-ID sets, and matching reserved totals. No negative probe added an unaccounted entry.

| Actual producer scenario | Verified current05 result |
|---|---|
| Methods + registered child model/search/scrape + actors, then budget stop |8 raw entries,85216micro-USD retained; all later parent/child sends denied. |
| Same composition, lost parent operation context |8 entries,85216 retained; halt reaches independent child. |
| Actor exhaustion after methods/child |6 entries,76016 retained; typed actor stop, no degraded successful continuation. |
| Child tool unknown outcome |5 entries,66016 retained; no later raw send. |
| Core-only fresh-PID recovery |600000 retained under1000000, next600000 denied, old generation fenced. Kept as store-only evidence. |
| Actual backend retained-balance denial |Real sealed research/prepare reused in fresh PID;1900000 actor quote fits original2000000 but exceeds remaining1400000; zero resumed sends, generation2. |
| Actual backend funded control/publication |Fresh PID reaches one SDK actor send at unchanged1800 output maximum;2500000 total retained under5000000; all stages complete, local report publishable, ledger closed. |
| Actual backend request tamper |`binding_conflict` before generation advance or scheduling; generation1, zero workers/resumed sends,600000 retained. |

These are fictitious test tariffs/caps, never human spending authorization. Backend fixtures execute real `resume` and `_run` with scheduling parked; initial research/method content is scripted, while receipts/sealing/reuse, actor/SDK admission and local publication are real. Core-only recovery is not used to claim full SB-08. Resume support remains limited to completed receipt-valid sealed research; partial child reuse stays denied.

Current05 aggregate process events retain8 blocked socket-construction and8 blocked process-discovery probes, plus8 allowed exact fixtures. B retains1 blocked socket-construction and2 blocked process-discovery probes, plus11 allowed exact fixtures. Its deliberate crash controls exit71/72/73 as expected; these are not failed tests or provider executions. Startup09's2+2 blocked child probes remain separately recorded. None is relabeled zero attempted activity or billed cost.

### Test-byte annotation caveat; Startup09 behavior preserved

Startup09 actually executed launcher fixture hash `468da02c7aa498838c190d1e48bae5b6794ba71086bf465baf551c46f6d06847`. The current file is `1045fa456b2578c2ef2d1a9521314727da7bc7bc2853720d66aa2f8670b9145d`, covered by the later86-case gate. Independently compared the full current file with Startup09's staged copy: the only differences are **three `# noqa: F401` comment insertions across two import patterns**, with the actual imports retained, and `ast.dump(..., include_attributes=False)` is identical for the complete files. The supplied annotation receipt `/private/tmp/run-spending-launcher-lint-annotation-20261029.json` describes two annotations; the observed three insertion locations are recorded here for precision. This is a documentation-count discrepancy only, not a code or acceptance defect.

Do not label Startup09 as an execution of the new1045 fixture bytes, and do not discard its actual app/child behavior evidence. Its executed fixture bytes remain468da, the full executable AST is unchanged, the new fixture bytes independently pass86 cases, and launcher production478b plus all17 frozen production files remain byte-identical. This closes the affected current-test gate without inventing a second private startup run.

### Final critical pins and delivery boundary

| Source | Final SHA-256 |
|---|---|
| Shared core | `b54cac7c001c5f46106e3593e7a5ad4f66a6711488bd5679fee0f35ec889f9d5` |
| Coordinator adapter | `796a7a2ec63001b1bd62e077db527956be4211f2f94a80123e393f90660ac01a` |
| Orchestrator | `38d0800566d78a7df2dca810abd4e2a36ba77bc2eacb1e36c667898b36d09bc7` |
| Child linear engine | `54c489fbe41e424689fc2722cf2376a8eb0f934c2abdd0bdb611932378bde44c` |
| Launcher production | `478b2ba636c437c3e707d39453b66ee73bf43e40b84dad09aacb5cf3d2c25612` |
| Parent transport | `206874c1d4b1515c6e22e5804c49a0c384c5cc24f94dfe8140acea70658df878` |
| Workflow tests | `ff8bd9880e05d17e2073dcbc1f2132545a69ccad8d7b20e7dc8437e80071be5c` |
| Workflow child fixture | `362e8cbd0f89a87365c0e7a9f675f0ecbb9ed11b35d33470de5c288cd1af2402` |
| Current launcher tests | `1045fa456b2578c2ef2d1a9521314727da7bc7bc2853720d66aa2f8670b9145d` |
| Backend-import test file | `93cb587ae874bfa4cdec7777613ddefa2a9a4ff521066c82cce25e3ace2ba065` |
| Unchanged offline guard | `5046cf820fa468d8e8ffb2e3fdade1d20fca2f0bd56ee15eabdff51c223c02be` |

**Remaining technical gate list: none for this frozen, approved offline spending scope.** Coordinator should reconcile the stale handoff status/evidence summary and issue11/delivery record, preserve the red/history receipts and source freeze, and record whatever separately authorized Git delivery is performed before beginning overlapping World Anchor work. Those administrative actions are outside this reviewer's sole-file ownership; no commit/push or issue mutation is claimed. Future live tariffs, account classification, credentials and numeric spending authorization remain separate operational prerequisites, not missing offline code gates.

## Updates

- 2026-10-29: Created the review record before scenario execution. The coordinator's handoff and every implementation file remain outside this reviewer's write ownership.
- 2026-10-29: Reported and recorded the actual-send immutable-request P1 early. Preserved initial malformed mock-response probe and later debugger assertion interference accurately.
- 2026-10-29: Verified six lifecycle/fence controls and the missing-ledger cancellation negative/valid-control probe. Reviewed the supplied eight-call installed-LangChain receipt with blocked-attempt accounting intact.
- 2026-10-29: Observed concurrent owner correction of the launcher test, confirmed five focused cases, recorded moving launcher hashes, and delivered this checkpoint with one open P1 and SB-02/05/08/12 acceptance still open.
- 2026-10-29: Recorded the user's accepted P1 correction, exact pre/post-resume SDK and actual HTTP corruption regression criteria, and reported new child-startup proof. Awaiting the announced source freeze before executing correction acceptance; no additional suites or code edits were made in this update.
- 2026-10-29: Applied the user's conservative SB-08 scope decision: reject explicit/implicit child research resume without producer checkpoint proof; permit parent resume only after receipt-valid completed research and sealed case/evidence/estimators under explicit core proof and unchanged immutable authority. Updated positive/negative regression prerequisites while preserving fresh-profile behavior and historical receipts. This is a review-contract update, not an implementation or test-pass claim.
- 2026-10-29: Re-read frozen b54 core and 796 coordinator correction; independently passed seven affected lifecycle cases and the actual HTTP/SDK pre/post-resume/corrupt-copy probe. Closed P1 for those bytes, refreshed hashes, verified owner17/93/78 receipts and actual private child evidence, and identified startup06's old coordinator snapshot as a remaining exact-source acceptance limit. No code edits, broad suite reruns, providers, production reads or commits were performed.
- 2026-10-29: Reviewed the in-progress composition interface. Preserved the explicit distinction between core-only restart and actual backend resume. Reported the backend negative's non-discriminating1900000 quote under1000000 cap and required an affordable-control/retained-balance pair before full SB-08 credit. Recorded the requested startup07 alignment gate; no implementation or test-pass claim was added.
- 2026-10-29: Recorded the coordinator-accepted synthetic cap2/prior0.6/quote1.9 backend negative and cap5 actual-SDK/publication control, with unchanged production maximum and separately scoped core-only recovery. These fictitious test caps/tariffs are not human paid-run authorization; the only human approval remains code/offline implementation on2026-10-29. No further test or acceptance action taken while awaiting the exact frozen proofs.
- 2026-10-29: Recorded the child prompt-file source boundary and current exact-byte guard, then the coordinator-directed CR rejection before authorization with unchanged LF multiline Unicode support. Verified the stated stable parent38d080/coreb54/coordinator796 identities, captured moving launcher/child hashes, and kept startup08 historical pending a new frozen-source private root. This is input qualification, not cap/route expansion or new spending approval.
- 2026-10-29: Independently matched startup09's twelve current/staged/before/after source pins and eight private service origins, inspected all process and ledger evidence, and passed17 focused prompt/scope/CR controls. Closed the child-request P1 and CR-qualification P2 for launcher478b/linear54c/parent38d/coreb54/service796; preserved startup08 as historical and kept composed workflow acceptance and the parallel packaging audit separate.
- 2026-10-29: Source-reviewed the alias-isolation test-only repair and its3-case gate; independently verified current05's8 workflow receipts/raw-entry/ledger joins and all17 frozen production hashes; read B's1201-pass completion. Verified current launcher test1045 is full-AST-identical to Startup09 fixture468da and its86-case affected gate is green, noting three comment insertion locations rather than the receipt's two-pattern shorthand. Closed final offline spending review with no technical gates remaining; coordinator delivery and subsequent World Anchor work remain separate.
