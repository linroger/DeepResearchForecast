# Store owner handoff

**Status:** Complete (owned core slice). **Updated:** 2026-10-29. Scope is the approved code/offline slice; no actual paid authorization, deployment, network, scheduler, commit or push.

## Request and constraints
Implement a strict stdlib manifest, immutable lifetime spending ledger, quote validation, operation/process context, physical dispatch, lifecycle and independent-process acceptance in the assigned module/tests. Other owners integrate real transports and pipeline/launcher. Preserve all unrelated files.

## Requirements and acceptance
SB-01 is two independent USD0.60 claims under USD1 with exactly one admitted and durable committed maxima. SB-06 covers precommit rollback, postcommit unknown preservation, no duplicate replay and transaction crash. SB-11 separates missing/provider/estimated usage from retained USD and denies unknown/subscription pricing. Supporting checks cover source/route/cap drift, missing DB, consumed registry, bound identity, generation/participants/lock/resume, late observations, sanitized errors and module identity.

## Plan and progress
1. Publish frozen JSON shapes/signatures before implementation (done: contracts.md frozen store API section).
2. Write meaningful failing scenario tests, then stdlib implementation with WAL/FULL immediate transactions.
3. Execute guarded fresh-evidence core/process tests and fix findings.
4. Obtain independent read-only review and document exact evidence and integration limits.

## Decisions and assumptions
Actual model/tool payload validation belongs to adapters; generic dispatch commits quote from the final validated envelope before send. Quotes use exact decimal rational arithmetic rounded upward to microUSD. Every maximum is retained forever. Missing usage does not mean zero. Unknown transport outcomes halt the whole run. Synthetic fixture evidence cannot qualify a real tariff. Source hashes and outside-runtime consumed registry are mandatory.

## Issues and remaining work
Implementation and behavioral red/pass receipts pending. Coordinator owns overall handoff and issue11. This owner will not alter other sections of contracts.md.

## Scenario evidence
Pending first guarded run. No success claim yet.

## Next-session prompt
Continue only the assigned spending store slice in codex/target-run-spending, read this file and contracts.md, preserve other owners, use existing guarded runner with exact child fixture registration, no provider/production/commit/push action.

## Updates
- 2026-10-29: Read approved plan, contracts, ownership and current store patterns; published exact API before adapter implementation.

### First core acceptance
The missing-feature baseline `/private/tmp/drf-spending-store-red-20261029-01` failed the explicit module-presence check; it is not a behavioral accounting red. The implemented core then passed50 synthetic checks in8.86s under `/private/tmp/drf-spending-store-core-20261029-02`, with the exact `backend/tests/fixtures/run_spending_child.py` registered. Cases include two independent600000-microUSD claims against1000000, precommit/aftercommit/after-send process exit, durable maxima, exact currency, source/registry/ledger drift, resume/fencing, unknown outcomes and async tool dispatch. Final review and additional adversarial checks remain pending; this is not full SB-01–SB-12 integration acceptance.

Test-only isolation names are `_REQUIRED`, `_ACTIVE_AUTH`, `_LOCAL_STOPS`, `_binding`, `_operation`, as specified in contracts.md. No production reset exists.

### Behavioral red receipts and corrections
- `/private/tmp/drf-spending-store-red-20261029-03`: two behavioral failures proved that joined-child unknown attempts did not halt immediately and restored thread context could re-enable admission. Child exit now persists unknown; missing thread context sets a lifetime local stop.
- `/private/tmp/drf-spending-store-red-20261029-05`: two failures proved removal of an imported environment carrier could preserve eligibility and nested logical keys lost ancestry. Imported carriers are now pinned and nesting hashes the parent carrier.
- `/private/tmp/drf-spending-store-red-20261029-07`: five failures reproduced source-restoration replay, discarded usage overrun evidence, unhashable route-kind raw errors, lock-open path-bearing errors and repeated-slash endpoint acceptance. These are corrected; usage breaches preserve sanitized observations and retain full maxima.
- `/private/tmp/drf-spending-store-red-20261029-10`: first-activation pin loss, explicit-binding bypass and parent environment transition failures were reproduced. The symlink-loop case also exposed that the unchanged guard cannot remove a self-loop because it resolves deletion targets. That fixture is now a bounded injected resolution failure plus separate real-symlink controls; no guard was changed.
- `/private/tmp/drf-spending-store-red-20261029-11`: repaired-corrupt-registry replay was reproduced with the unexpected-send marker checked outside dispatch. The earlier broad `pytest.raises` could be satisfied when dispatch converted an inner `pytest.fail`; all denied-send fixtures now assert an external marker in teardown. This is a test-harness correction, not additional evidence from the earlier green run.
- `/private/tmp/drf-spending-store-core-20261029-12` and `-13`: only the expected error-code assertion for a sidecar symlink failed; `_path` was catching its own RuntimeError-subclass SpendingStop. It now preserves that typed stop before normalizing raw resolution failures.

### Current verification and byte identity
The current complete core gate is `/private/tmp/drf-spending-store-final-20261029-14`: **77 passed in11.24s**. It uses the unchanged `backend/scripts/main_offline_pytest.py` and exact allowlisted child fixture. The prior71-pass receipt (`-09`) is historical; later source corrections are covered by77cases. Source-only Ruff passed for all three owned Python files. No live provider, scheduler, production-data, commit or push operation was performed.

| Owned source | SHA-256 at the77-case gate |
|---|---|
| `deerflow_bridge/run_spending.py` | `4d6b8ccc2250ce09318ff045a6db52f523321855492d678bf7b2ba7b223afeb2` |
| `backend/tests/test_run_spending_store.py` | `fea756d1d163acfe5f87dc853ad79d76aaa2b6d72bbf5c94aa5ebcc10c0dde96` |
| `backend/tests/fixtures/run_spending_child.py` | `45694e278d498b844969aabed87f63ff3b099739120bf0eec763df2baef52198` |

Proven scenarios include independent creator races (one consumed authorization), independent0.60+0.60 claims under1.00 (exactly one send), precommit crash rollback, postcommit/no-send and post-send/no-result retention, no missing-DB recreation, no cap reset across clean generation resume, late fences, cancellation ordering, source/route/registry/DB drift, fixed-code exceptions, immutable attempt/observation behavior, credential qualification and raw usage classification. Private authority/attempt/event timestamps are stored in UTC. The fork-hook descriptor rule is tested directly because actual fork is prohibited by the guard; actual cross-process scenarios use registered spawn/exec children.

### Integration contract deltas
The coordinator must register a research participant inside the same operation exported to that child. `bind_pipeline`/`resume_existing` adopt only their committed parent descriptor transition into environment/context; coordinator code must not reset pins or mutate the carrier independently. Both explicit and implicit admission validate imported environment pins. Test fixtures add `_ENV_PIN=None` to the existing private resets. Runtime has no reset API.

Core is currently frozen for adapter/launcher validation. Independent reviewer Beauvoir identified five initial and four follow-up findings; fixes and executable regression receipts are above. Final rereview remains pending. Parent/child/launcher producer-consumer acceptance is owned by the coordinator and respective transport owners; the core77-case receipt is not a claim of full SB-01–SB-12 integration or paid-provider readiness.


### Final acceptance and independent review closure
The final authoritative owned-core receipt is `/private/tmp/drf-spending-store-final-20261029-16`: **78 passed in11.88s, zero failures/errors/skips**. Its completion receipt has exit0, completed shutdown, seven exact registered child launches, zero blocked guard events, no source drift, and preserved identity paths. Parent-process crash fixtures intentionally exited71/72/73 in the corresponding child cases; these are expected test outcomes, not provider execution.

The prior77-case run remains historical. Final additional regression `/private/tmp/drf-spending-store-red-20261029-15` reproduced the concurrent environment-adoption reader race. `_check_env_pin` now takes the same RLock as the writer for snapshot, comparison and denial; the passing barrier proves an old-generation reader waits and gets `stale_generation` without halting generation2.

| Final owned Python source | SHA-256 |
|---|---|
| `deerflow_bridge/run_spending.py` | `25a7999148dbbabe9271250f8e312c7b70c144b7722a33ac32035e44a048da30` |
| `backend/tests/test_run_spending_store.py` | `f25f0cbb6ed4f836f877fb011fcbf5fd5b5ae55acd67998c9f9f819f69cc5d77` |
| `backend/tests/fixtures/run_spending_child.py` | `45694e278d498b844969aabed87f63ff3b099739120bf0eec763df2baef52198` |

Independent reviewer Beauvoir (`01a185ae-94ad-75f2-9767-9f6da9667894`) re-read this exact final core hash and confirmed no outstanding core-store findings. The reviewer made no edits, ran no tests/providers, and independently inspected the existing red/final receipts. Ruff passed for all three final Python files. User ownership and no-commit/no-push boundaries were preserved.

The owned slice is complete. Remaining work belongs to the coordinator: freeze and run the final combined pipeline/launcher/transport acceptance on these bytes, record overall SB-01–SB-12 coverage, and preserve the separate future operational approval gate. The core does not validate a real tariff or spend authorization. `account_sha256` is exactly SHA-256 of the UTF-8 credential and detects selection drift only; billing/account/tariff qualification still requires independent owner-reviewed basis evidence. Registry/ledger restoration or missing storage cannot renew allowance.

### Final next-session prompt
Use codex/target-run-spending, read contracts.md and the coordinator handoff, preserve this reviewed store hash unless a concrete regression is reproduced, and complete composed offline acceptance with the exact registered child fixture. Retain full run lock ownership; bind/resume perform committed parent carrier adoption internally; do not mutate/reset environment pins. Register child participants under the exact root operation exported to them. No live provider, scheduler, production root/upload, commit or push action is authorized by this core delivery.

### Updates
- 2026-10-29: Published API before adapter implementation; implemented strict store and guarded process scenarios.
- 2026-10-29: Preserved behavioral red receipts and closed independent review findings across source identity, usage evidence, carrier lifecycle, fixed-code errors and process fencing.
- 2026-10-29: Completed78-case final core gate and independent exact-byte review; marked only the owned core slice complete.

### Parent environment operation follow-up
The coordinator removed its post-bind `os.environ.update(export_environment(bound))`, because exporting an implicit thread-local root operation into an already pinned parent carrier would change `DRF_RUN_SPENDING_OPERATION`. Added the exact initial-parent-env-without-operation → root-operation → bind scenario, then verified parent context, credential route qualification, absence of the parent environment operation key, and explicit registered-operation export to a detached child environment.

The focused red receipt `/private/tmp/drf-spending-store-envop-red-20261029-17` exposed a prerequisite: operation metadata could not wrap the first bind because `operation()` rejected the prepared state. The correction permits only the lock-owning parent with an empty pipeline ID and a running matching-PID participant to establish preparation operation metadata. All route qualification, context admission, reservation and send paths continue to require an active committed pipeline. Negative checks prove zero dispatch before bind and rejection without the parent lock.

Fresh authoritative core gate `/private/tmp/drf-spending-store-envop-final-20261029-18`: **81 passed in16.75s**. Ruff passed for all owned Python sources. Prior78-case receipts remain historical evidence for the earlier core hash; the new gate covers the updated code and all prior scenarios.

- Core SHA-256: `8036fc5428ee3f26470e500688b1690412c90ab8308e3bb9e6bb52c54f0efdf2`.
- Store tests SHA-256: `06a51a24ea18b630b7a5a009779f8c23f55ece80aed5acb78d46a438a15e72ec`.
- Child fixture SHA-256 unchanged: `45694e278d498b844969aabed87f63ff3b099739120bf0eec763df2baef52198`.
- Independent reviewer reopened for this narrow change; final follow-up verdict pending.
- 2026-10-29: Added requested parent/no-operation carrier regression, closed the prepared-operation prerequisite, and recorded81-case guarded evidence. No provider, production, commit or push activity.
- 2026-10-29: Independent follow-up review closed with no new findings on core hash `8036fc5428ee3f26470e500688b1690412c90ab8308e3bb9e6bb52c54f0efdf2`. Reviewer confirmed preparation restriction, unchanged absent parent environment operation, detached child export, and all81 passing receipt cases. Owned slice remains complete.

### Stable base confirmation for composed gates
2026-10-29: Re-ran the full current81-case store suite at the coordinator's request, with the unchanged guard and exact child registration. `/private/tmp/drf-spending-store-freeze-20261029-19` passed **81 in11.63s**, with completed shutdown, exit0, seven registered child launches, no blocked guard events, no source drift and preserved identity paths. Pre/post hashes are identical: core `8036fc5428ee3f26470e500688b1690412c90ab8308e3bb9e6bb52c54f0efdf2`, tests `06a51a24ea18b630b7a5a009779f8c23f55ece80aed5acb78d46a438a15e72ec`, child `45694e278d498b844969aabed87f63ff3b099739120bf0eec763df2baef52198`. No source changed during this confirmation. Independent follow-up review already covers this exact core hash and all changes since the earlier25a79991 hash; no unreviewed post-final source change remains. Core stays frozen for child/parent/composed acceptance. This note is documentation only and does not claim overall feature completion.

### Installed LangChain adapter evidence received
2026-10-29: Read-only verification of `/private/tmp/run-spending-actual-langchain-20261029-01/actual-adapter-result.json` and `completed.json` confirms the actual ChatOpenAI/OpenAI SDK gateway/tool/store path with only HTTP MockTransport substituted: eight mock HTTP requests, eight distinct committed attempts,66112microUSD retained, and zero additional cache-hit calls. The result and guard source manifest both pin the unchanged core hash `8036fc5428ee3f26470e500688b1690412c90ab8308e3bb9e6bb52c54f0efdf2`. Guard completion is exit0 with completed shutdown, no source drift and preserved identity; it records two blocked socket-construction and two blocked subprocess attempts, so this is not a zero-attempt guard receipt.

Static inspection of `/private/tmp/run-spending-langchain-proof-20261029-01/proof.py` confirms `run_proof(root,binding)` first checks the supplied active context and uses its existing ledger; authorization creation is in the separate standalone fixture function. No proof or adapter was executed by this owner. The standalone receipt's attempts use participant `parent`; registration as a separate child and composition with parent estimator/actor calls remain coordinator-owned SB-02 acceptance. The core remains frozen; this update changes documentation only and does not imply live-provider or invoice proof.

### Second installed-adapter proof: probe attribution and count correction
2026-10-29: Read-only inspection of `/private/tmp/run-spending-actual-langchain-20261029-02` confirms the same eight HTTP MockTransport calls/eight retained attempts/66112microUSD and no extra cache-hit calls, with successful guard completion and no source drift. `probe-origins.jsonl` attributes the two blocked socket constructions to `urllib3.util.connection._has_ipv6` and `langchain_openai.chat_models._client_utils._filter_supported`. No connect/bind/DNS/send event appears in the guard event stream.

The reported claim that proof-02 has only two socket probes does not match its current complete receipt: both `completed.json` and `events-47724.jsonl` additionally record two blocked subprocess attempts, `uname` and an unregistered executable. Preserve four blocked attempts total for proof-02; the socket-only origin trace is not the full guard event count. This owner neither changed the guard nor reran the proof. Core remains unchanged at `8036fc5428ee3f26470e500688b1690412c90ab8308e3bb9e6bb52c54f0efdf2`. Launcher composition remains with Carver/coordinator; this is documentation only.

### Immutable request validation integration repair
2026-10-29: Coordinator reported a reproduced P1: comparing normalized actual state only with mutable `spending_request_v1` allowed both copies to change while still authorizing raw model calls. User explicitly approved the narrow public addition `validate_bound_request(binding, request) -> str`. It checks the existing validated transaction's immutable manifest request hash and nonempty matching pipeline binding, supports paused pre-resume validation, and performs no successful binding/generation/cap/state mutation. Mismatch or a noncanonical request persists fixed `binding_conflict`; stale-generation validation cannot halt the new owner. Coordinator owns calls before generation advance and provider execution.

Seven new core cases cover valid active/paused requests with unchanged retained600000microUSD, tampered actual+saved requests in active/paused state, persisted stop/no later send/no resume, unbound rejection, stale-generation fencing and malformed request sanitization. `/private/tmp/drf-spending-request-validation-red-20261029-20` records seven missing-API failures before implementation; it is not the coordinator's separate full-pipeline behavioral reproduction. Full current core gate `/private/tmp/drf-spending-request-validation-final-20261029-21` passed **88 in11.70s**. Ruff passed.

- New core SHA-256: `d11b6fd2ce7031345f71c1c94296b92267216bd55c4343ce69fa13ea88a204e1`.
- New store-test SHA-256: `920d2b28669d17ce4bb9befec4230b0d9f87a2918b92bbe75a865f4034775c42`.
- Existing child fixture is unchanged.
- Narrow independent review reopened; final freeze confirmation pending its verdict.
- Coordinator's newly reported five-case composed/fresh-PID actual-dependency result used the prior8036fc54 core and must remain an intermediate receipt. Current source moved because of this explicitly requested API addition; final composed acceptance needs a fresh gate after the new freeze.

### Request validator malformed-input closure
2026-10-29: Independent review identified invalid UTF-8 surrogate and excessive nesting paths outside the validator's promised binding-conflict normalization. The narrow fix catches `UnicodeError` and `RecursionError` alongside `SpendingStop` only around request hashing, inside the existing transaction. Expanded malformed-input cases cover object, surrogate and nesting for active and paused authorities, each with a retained600000microUSD prior attempt, unchanged1000000microUSD cap and generation1.

`/private/tmp/drf-spending-request-validation-red-20261029-22` records two surrogate failures and four passing cases. The initial nesting depth did not exceed the CPython C JSON encoder limit, so those early nesting passes were hash-mismatch checks, not recursion-failure proof. Final nesting cases now construct at least5000levels and explicitly establish that direct hashing raises RecursionError before checking the validator's fixed durable stop. The production catch is unchanged from the93-pass `-23` receipt; a fresh final `-24` gate covers the stronger test bytes. Source remains frozen pending final receipt/review confirmation.

### Serialization-test correction before final freeze
2026-10-29: The `-24` run recorded91passes and two test-assumption failures: even the enlarged nesting fixture did not cause this environment's encoder to raise RecursionError. The recursion-path test now explicitly injects that exception from `json.dumps` only for the exact malformed request object, leaving all guard and ledger serialization untouched. It is labeled serializer fault-injection evidence, not an observed natural nesting-limit failure. Production core remains unchanged at `b54cac7c001c5f46106e3593e7a5ad4f66a6711488bd5679fee0f35ec889f9d5`; no feature beyond immutable request validation was added. A fresh full93-case `-25` gate is the pending final receipt.

### Final immutable-request API acceptance and freeze
2026-10-29: `/private/tmp/drf-spending-request-validation-final-20261029-25` is the final authoritative core receipt: **93 passed in12.58s, zero failures/errors/skips**. Completion reports exit0, completed shutdown, seven exact registered child launches, no blocked guard events, no source drift and preserved identity. The full suite includes the pre-start root-operation/environment-adoption regressions. Source-only Ruff and owned-path whitespace checks passed.

Final frozen core: `b54cac7c001c5f46106e3593e7a5ad4f66a6711488bd5679fee0f35ec889f9d5`. Store tests: `8cd45da80f86ee2151841a1900435def5cbeb8668064496fe1a0cb2ec7cef345`. Child fixture unchanged: `45694e278d498b844969aabed87f63ff3b099739120bf0eec763df2baef52198`. Independent reviewer Beauvoir confirmed no outstanding findings in the exact core correction and revised tests, and independently read the final receipts. This source hash supersedes8036fc54/d11b6fd2 for final composed acceptance; their earlier receipts remain historical. No more core changes are pending/requested. Coordinator owns final lifecycle/actual-private-process composition and its immutable-request tampering regression. No provider, primary, scheduler, commit or push actions were performed here.
