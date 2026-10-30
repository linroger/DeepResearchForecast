# World Anchor private launcher owner

Status: Launcher implementation and the released-source paired private research/publication/adoption proof are complete. Broader World Anchor root-gate acceptance and delivery remain coordinator work. The current execution assignment changed only private harness/evidence and this note; production launcher cc9e662c remains frozen. No real provider calls, deployment, scheduler, commit or push was authorized or performed.

2026-10-30 completed assignment: Execute the private v2 process/publication integration proof using only private harness/evidence and this note. The production launcher remains frozen at cc9e662c. Both final controls cover actual child `linear.run` entry with omitted control, extraction and independent review through real SDK/opaque captures, completion publication, and parent adoption using real APIs with HTTP MockTransport only.

Current result: After the coordinator's explicit final shared release, both private actor controls passed on that released runtime source. Actor-positive exits 0 with ready target output; missing-authority exits 2 as expected, with an authenticated non-ready completion and no assessment. All 172 staged repository files and 424 runtime pins per control remain exact. Four later test-only changes are recorded as unused global-reference drift. Runtime02 and earlier numeric evidence remain historical; no final result is attributed to those older snapshots.

2026-10-30 final execution release: The coordinator explicitly released the shared source after record R1/R4/R5 closure. Final actor-positive and missing-authority controls executed in new private roots, using the coordinator's full source-before.json and record candidate-hold.json. Runtime02 stays historical. Final verification and independent review confirm matching released/pre/staged/post runtime-source hashes, real producer captures, selected-budget linkage, parent adoption and termination for both controls.

## Intent and acceptance

Extend the delivered private full target-first launcher to the frozen core v2 contract without changing v1/off request shape, runtime schema or behavior. A v2 request has exactly the seven existing fields plus the complete private world_anchor object. The one scope, source-policy identity, and immutable 20-model/150000-token/8-catalog/12-follow-up maxima (or lower approved limits) are pinned; singleton catalog-query and follow-up-round limits are one. No environment flag or public selector creates that authority.

Preserve strict prompt UTF-8/content equality, LF-only qualification, source/import/dependency verification, fixed R/control/request.json, and explicit/implicit partial target-v3 resume refusal. Positive and negative guarded scenarios must reach real core authorization/binding/participant/preflight boundaries with fake HTTP only. Run all unchanged v1 launcher tests as a compatibility gate.

## Concrete interface

- v1 prepare specs and runtime descriptors remain unchanged, with exactly seven request fields and no anchor artifacts.
- New `target-acceptance-prepare/v2` is the existing preparation spec plus exactly `anchor_budget`; its request must contain the full eighth field. Preparation remains provider-free and creates no authorization or ledger.
- New `target-acceptance-runtime/v2` retains the existing descriptor keys, pins `control/anchor_budget.json`, and keeps byte-identical control/runtime and spend/runtime descriptor copies. The authorization must use `target-run-spending/v2`, exactly match the prepared budget and full request, and include all source/runtime hashes.
- `check_request(request)` accepts only exact v1 or v2 shapes. `check_anchor_budget(budget, request, model)` validates the private object and conservative profile before runtime creation/imports.
- `qualify_manifest(core, checked, manifest)` validates the core manifest, exact v1/v2 pairing, budget/request/source equality, and closed route profile before credential/client use.
- Child v2 validates/activates its existing registered binding, calls `validate_bound_request` and `preflight_anchor_profile` before application imports, then runs unchanged argv. Scope selection travels only through the required core binding and fixed request carrier, not a new environment selector.
- Parent common start owns bind_pipeline. Coordinator must call core preflight immediately after binding and before worker/client construction; launcher performs the same conservative envelope check before application import because the core preflight requires an already bound run. Research-root registration must grant exactly scope_entry_ids=[the manifest scope] if entry is intended.

## Dependencies and ownership boundary

Frozen core: d7691253c4f842b0355113f39930ec0ace4671ae35ed608b533daddbcd6322df. Exact interfaces are budget-contract-proposal.md sections 2/4/5/8. Franklin owns core; Poincare owns the actual loaded child request check, scope barriers and gateway capture integration; coordinator owns start/registration/adoption lifecycle. No owner edits another's files.

The core preflight checks the full enforceable route input ceiling plus declared inclusive output (at most 2000), without making a reservation. Actual attempt admission performs the atomic debit. An oversized profile fails before client construction; no token estimate or clipped context substitutes for a bound. A nonempty tool route list is a closed allowlist, and an empty list grants no calls. Qualification of real catalog adapters and additional credential routes remains a separate explicit requirement; no real tariff/account qualification is inferred.

Coordinator confirmed the initial credential injection stays exactly LLM_API_KEY and FIRECRAWL_API_KEY (plus the existing same-key provider alias). There is currently no qualified live catalog mapping, so the launcher refuses catalog routes/nonempty catalog allowlists at manifest qualification before credential loading or application setup. Prepared structural policy may record such IDs for review, but it cannot authorize their execution. Core/binder synthetic catalog tests remain supported independently. The coordinator owns preflight immediately after bind and the research-root scope-entry grant.

## Progress

- Read the approved plan and frozen v2 core contract; preserved concurrent edits.
- Published this spec/descriptor interface before implementation and coordinated the parent/child seams.
- Implementation is complete. The unchanged v1 gate passed 86 cases at `/private/tmp/world-anchor-launcher-v1-01`; the new owner suite passed 138 cases. The final combined gate passes all 224 cases.
- Bounded delegation: Euler implemented only new `backend/tests/test_world_anchor_launcher.py` and returned ownership; Halley performed read-only launcher review. This owner retained launcher source and this note. Neither child edited another owner's files.

## Final verification and frozen source

Exact invocation: `/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/world-anchor-launcher-final-01 -q --tb=short -x backend/tests/test_run_spending_launcher.py backend/tests/test_world_anchor_launcher.py`.

Result: **224 passed in 23.27 seconds**, comprising all **86 unchanged v1 launcher tests** and **138 new v2 tests**, with no failures/errors/skips. [JUnit](/private/tmp/world-anchor-launcher-final-01/junit.xml) and [completion receipt](/private/tmp/world-anchor-launcher-final-01/completed.json) record exit 0, completed shutdown, preserved identity, no source drift, no child processes or contained-library probes, and only the three expected application storage/log redirects. No network/process attempts are recorded. Ruff and scoped whitespace checks pass. `git diff --exit-code -- backend/tests/test_run_spending_launcher.py` confirms the delivered v1 test source is unchanged.

| File | SHA-256 |
|---|---|
| backend/scripts/target_acceptance_run.py | cc9e662c1d906a491472422acdfcf60ac0bad8b743334f2ad18feaf6cf4b4043 |
| backend/tests/test_world_anchor_launcher.py | ca66500f5827b83eb937918e46552c2f15e81c2238b28af1d4d46e37ec9722ad |
| backend/tests/test_run_spending_launcher.py, unchanged | 1045fa456b2578c2ef2d1a9521314727da7bc7bc2853720d66aa2f8670b9145d |
| deerflow_bridge/run_spending.py, frozen external dependency | d7691253c4f842b0355113f39930ec0ace4671ae35ed608b533daddbcd6322df |

Scenarios cover exact eighth-field/private budget schemas, strict integers and lower immutable limits, all maxima and singleton limits, schema pairing, request/control/runtime tampering, unqualified/oversized profiles, prepared-versus-approved policy equality, unmapped catalog refusal, and follow-up subsets. Child ordering proves activation, immutable full-request validation and core preflight happen before execution setup/script. Positive controls use actual core authorization, SQLite ledger, participant/scope context and `dispatch` with HTTPX MockTransport. They inspect the retained model/token/USD dimensions before POST; a second physical attempt beyond the model or token limit is denied with no second POST and no refund.

The new child bootstrap tests are in-process and use setup/script spies plus the existing synthetic interpreter fixture. They establish the exercised launcher/core control boundary, not provisioned v2-process startup, SDK deployment or end-to-end anchor publication. Earlier v1 actual-runtime receipts remain historical v1 evidence, not v2 delivery proof. Parent post-bind preflight, research-root entry grant, phase barriers/capture, Poincare's actual loaded eighth-field validation, and composed producer/publication proof remain their owners' explicit integration tasks. No launcher-side stage entry, allowance renewal, generic credential forwarding or resume entrypoint was introduced.

Coordinator integration prompt: use the exact spec/runtime/interface above against frozen d769 core; preflight immediately after common-start bind before workers, grant only the declared scope to the research root, and validate the fixed eight-field request in the actual child. Keep stage entry/seal/finish/handoff on committed core APIs. Run composed guarded fake-transport/publication acceptance on exact final source; do not launch providers or infer a paid qualification from these receipts. This owner made no commit or push.

## Updates

- 2026-10-30: Resumed verification preparation in codex/world-anchor. Confirmed the old /private/tmp startup directory is absent, while its durable private archive and the pinned dependency tar remain available. Reuse will be by verified copy into a fresh private root. Coordinating current control/scope/publication interfaces directly with Poincare; no production edits are authorized in this phase.

## Provisional actual-process harness, 2026-10-30

Private harness and durable evidence root:
`/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-v2-process-provisional-20261030-01`.

Files are `stage.py`, `process_harness.py`, `http_fixtures.py`, source snapshots, staging notes, and copied runtime evidence. Faraday implemented only the private HTTP fixture module. James performed read-only harness and receipt review. Repository production and test files were not changed; the launcher still hashes to cc9e662c1d906a491472422acdfcf60ac0bad8b743334f2ad18feaf6cf4b4043.

### Scope and real execution path

The harness reuses verified CPython and dependency files from the durable Startup09 archive. It stages exact application/bridge hashes, computes the builtin `source_policy_hash()` from the staged stdlib-only binder, and pins that value in both the private request8 and anchor budget. The initial fixture authorization and immutable core binding are synthetic and established with real stdlib core APIs before the R-only offline Guard. The real app `bind_start` then revalidates the same ID/request idempotently under the unchanged Guard.

The parent drives real `pipeline_scope`, `research_child_scope` and `configure_child` APIs. The registered child receives only its declared scope-entry capability. An exact hashed fixture, wrapped by the unchanged offline runner with `-I -S -B`, enters the frozen launcher `main/_child` using the actual production arguments. The actual upstream research script and full `linear.run` execute with `world_anchor_control` omitted. The observer wraps the actual bare binder module's factory without replacing its result. ChatOpenAI, OpenAI SDK, ModelGateway, the producer callbacks, core receipts, source admission and publication are real; only HTTP responses come from MockTransport. This does not claim execution of the parent launcher's full six-stage `run()` flow or a live model's semantic accuracy.

The HTTP observer matches each committed unknown attempt by request hash, current logical operation, participant, generation, admission epoch, route, scope and session, and requires a unique match. The parent requires distinct extraction/review attempts and joins actual HTTP hashes to stored observations and published provider, dispatch, transport and decoded-response artifacts. It also requires the numeric fixture's base=176 GW and other=80 GW to survive as reviewed/bound observations. Unsupported text or null-identity demands return empty proposals and retain gaps; the fixture does not manufacture numeric rows for them.

### Observed provisional run

Executed runtime: `/private/tmp/world-anchor-v2-process-provisional-20261030-02/runtime`.

Durable copy: [runtime02-evidence](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-v2-process-provisional-20261030-01/runtime02-evidence). The [copy manifest](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-v2-process-provisional-20261030-01/runtime02-copy-manifest.json) has SHA-256 `4762330b45b8dcc3b7f1c5d3b06b6c4bdc3602ff81794ffd756fe7dade338cbd`; all **653 regular files** were copied and rehashed against the executed tree. This is archival integrity, not a relocated execution or resumable-ledger claim.

The [result](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-v2-process-provisional-20261030-01/runtime02-evidence/integration-result.json) records `status=passed`, `source_status=provisional`, and **200.82 seconds** for this named numeric process exercise. The [capture reconciliation](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-v2-process-provisional-20261030-01/runtime02-evidence/capture-reconciliation.json) verifies **31 unique HTTP requests and 31 ledger attempts**: 14 other model calls, 13 tool calls, two anchor extraction calls and two independent review calls. The anchor scope retains four model attempts, **40,000 token-envelope units** and **48,000 micro-USD**; the whole synthetic run retains **1,026,032 micro-USD**. These are fixture reservations, not real expenditure or invoices.

Exactly one `PendingProducerControl` factory call was observed. The completion manifest was published, the original handoff packet retained, the parent adopted admission epoch 2 with no active scope, lifecycle became ready, and the same spending ledger closed. Both numeric values have explicit-support review records and bound observations. Nineteen published producer files match their manifest hashes. Independent read-only review confirmed these successful-path receipts.

Captured source snapshot SHA-256: `34f799bc74a44c1e97f711019fd3c193f91fc8e549cdd5950b4623de9ecceaf9`, recorded in `source-snapshot.json` and the runtime context. Its binder was `4e9c23d6e3e5c171e5a9a3a7a2d542b93f9e3b5328b13809a9a2a8a6080fa55b`; linear was `62258f4d7f679c1f828a2523f84fd4757591fc2c609f2424bdbbce386b4e8c50`; target research was `4ef5b40470b60fd2b1a9b9caad48b00486b67c8dd00fce9cfe0a9499a1a4435e`. The builtin policy hash was `565cd91c3cf974dd22b87cad8bb9fd41540fd90d961c354085bea7e7fb212cb7`. These are historical snapshot identities; newer owner hashes do not retroactively validate this run.

The child preserved the original hard exit after writing bounded observations. Its guard receipt intentionally has `shutdown_complete=false`, because interpreter unwinding did not occur; the parent verified actual exit 0 and joined the process. The parent receipt has completed shutdown, preserved identity and no source drift. Two socket-construction probes and two process-discovery probes were denied. No external request was admitted, and these denied attempts are not described as zero attempts.

### Harness findings and repairs

Initial staging under the durable home directory was refused before runtime creation because an ancestor `.env` exists. It was neither read nor modified. The runtime was moved to a fresh canonical `/private/tmp` area with a private 0700 parent; Python/dependency copies remain durable. The frozen launcher and Guard were not weakened.

Read-only review found four harness issues: observing the wrong module alias, insufficient producer/HTTP reconciliation, ambiguous same-body attempt attribution, and altered shutdown semantics. The first three and successful hard-exit behavior have executed evidence in runtime02. A remaining observation-write failure could skip the hard exit; the latest template now puts the saved original exit in an unconditional `finally`. [shutdown-boundary-check.json](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-v2-process-provisional-20261030-01/shutdown-boundary-check.json) records five isolated function-level cases reaching the exit sentinel, including observation, guard and stdout/stderr failures. This repair has source/function evidence only and is not attributed to runtime02.

The current template also verifies the new parent budget link: the artifact selected by `pack.metering` must reference a raw budget whose canonical hash equals the ledger-authenticated completion's `budget_receipt_sha256`, and its four counters must match the retained core scope. It requires actual adoption to persist `options.world_anchor_scope_completion` equal to the original completion packet. These newer assertions await the next actual-process run on frozen dependencies.

### Bounded blockers and next action

1. Producer source was reopened for canonical scale validation, actor demand and candidate-actor handling. Source-policy instructions and batching are changing; recompute the builtin hash after the final freeze.
2. The initial Firecrawl path lost primary-source metadata; a later review found contradictory search/fetch metadata could retain the first primary tier. Poincare's enabled-only merge/preservation fixes now have the reported 341-case owned gate and closed review, covering both arrival orders, cache/alias/reload controls and off/v1 behavior. The private actor process rerun still awaits whole-source release. Primary status must come through the actual metadata path; never infer it from a hostname or seed the ledger.
3. The pure owner is repairing stale-meter rollback and accepted-evidence enforcement. The coordinator has wired the selected budget/completion link and its trusted saved metadata; its final affected gate remains to be supplied.
4. The fresh actor HTTP fixture is now prepared from the exact passing source function. The positive source explicitly states sole authority and all nine native controls; the negative source omits sole authority. Static copying and template assertions are complete, but installed-SDK actor execution has not been run.

Ready-to-use next prompt: Read this note and obtain the final pure, core, producer, tool and parent source hashes and their passing gates. Keep launcher cc9e662c frozen. Update only the private HTTP fixture to the proven actor/primary-metadata contract, then stage a fresh runtime with a recomputed builtin policy hash and unique synthetic authorization identity. Run the current private harness once under the unchanged Guard. Verify actual omitted-control creation, actor and numeric extraction/review captures, publication, selected-budget cross-link, parent adoption, exact source stability, retained counters, hard exit and elapsed time. Preserve runtime02 and all earlier evidence as historical. No provider calls, production changes, installs, commits or pushes are authorized by this proof assignment.

2026-10-30 coordinator hold: Producer-owned fixes and their final gate are ready. The private harness still requires the coordinator's final shared pure/native/publication pins before staging or an actual-process rerun.

### Prepared actor fixture; no process execution yet

The private router at `http_fixtures.py` supports `scalar`, `actor`, and `actor_missing_authority` through explicit harness arguments. Its SHA-256 is `2e75fc447f3b030d5799bb07d10e8792ba35229df4c2f70adf95c221a14bb6e0`. `page_text(today, scenario)` emits the exact actor wording copied from `test_world_anchor_binding.py::test_production_linear_run_omitted_control_uses_fixed_v2_carriers`. Search items and scraped metadata carry `publication_type=government_report`, the supplied day, and `origin_cluster=capacity-agency`. Planning actors remain empty; only the existing findings reply adds primary C3 and the complete candidate actor. Extraction handles every requirement in a two-requirement batch, while unsupported research notes remain gaps.

The copied candidate actor contains capacity 1, cadence 1 period, release lag 0 periods, credibility 1, and a dispatch lever with minimum 0 GW, maximum 10 GW, cost 1 capacity/GW, lag 0 and reversibility true. The authority row is produced only for the variant whose source explicitly says the agency has sole authority. The missing-authority response omits that row and cannot approve it in review.

The function text SHA-256 is `58f2fe6fb750b7aebef9cf640bca84f82a524df81658d2c3720d0a2f7679d7e4`. Whole-file hashes advanced from the supplied `000467d1…` through the worker's `65f6f4be…` to the later `177e2001…` as tests changed, but the copied function text remained identical. [actor-fixture-static-copy.json](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-v2-process-provisional-20261030-01/actor-fixture-static-copy.json) records the exact observed hashes and equality of the candidate actor literal. Verification used AST/literal comparison only; neither application code nor the fixture was executed.

The next stage will pin `private_http_case.json` in the runtime source manifest, including scenario, supplied day and fixture-source identity. The parent template checks all nine required control bindings and their independent reviews, the bound authority observation, compiled primary authority claim links, and native actor values. The negative variant expects exit 2, blocked target readiness, an authority gap and no target-assessment call. Original completion and trusted saved scope-completion metadata remain independently checked. These assertions are not claimed by historical runtime02.

Read-only review found and closed two additional template proof gaps. Each selected actor observation is now joined through its exact review and proposal to the captured extraction/review attempts, row identity and artifact hashes. The authority check follows the approved authority selector into retained UTF-8 bytes, then checks the compiled claim's exact ID, base node, passage, primary native-source mapping and base-node incidence. The saved target plan must have an empty actor list. Reviewer James confirmed those narrow fixes in template SHA-256 `437035b3605439eb83f6d4313d74ef8ab9a7ef2046923f761ce997ed03afea35`. This is static/source-review closure only; no updated fixture, staging or process run has occurred.

The candidate builtin policy was independently recomputed from the owner's retained `source-policy-evidence.json` as `a6c9d2f68ccca99db60a6d881540361d0008675f3b8b430b419b4f1582e77c71`. It explicitly qualifies a 65,536-byte serialized packet bound, not model-native tokenizer fit, while retaining full-route token accounting. Source-policy hashing will be recomputed from the actual staged final source again after release.

The producer-owned final gate was read as **341 passed, zero failures/errors/skips**. The owner reports Kant's review closed and these final owned pins: binder `d125131d66369007239891ce7e40ccf2fc234e704365784a8657e00d664e21c5`, search `bd600f1b6ec41ee34cc0a208491d79ffd9968f74097bb8ff92741b18091fed4a`, fetch `cc56c1b9dbcdb74583f5c16262e4c898a02dbe4a56986f2a6bc5d85bf910e1c2`; linear, target and gateway retain the previously supplied candidate values. Durable owner evidence is under `evaluations/world-anchor-producer-final-20261030-01`. These owned pins do not replace the coordinator's final shared pure/native/publication release, which is still required before the next process proof.

## Final released-source private controls

This section supersedes the preparation holds above. The coordinator explicitly released the shared snapshot after record R1/R4/R5 review closure. The release reference is [source-before.json](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-final-20261030-01/source-before.json); record production pins come from [candidate-hold.json](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-record-review-R145-20261030/candidate-hold.json). Preparation verified all 703 release pins, the record hold and closure identity, and the builtin source-policy hash before creating either runtime.

Final durable root: `/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-v2-process-final-20261030-01`.

| Observed result | Actor-positive | Missing authority |
|---|---:|---:|
| Child exit | 0 | 2, expected refusal |
| Parent harness exit | 0 | 0 |
| Elapsed process time | 254.04 seconds | 245.54 seconds |
| HTTP requests and unique ledger attempts | 41 | 40 |
| Extraction / independent review attempts | 7 / 7 | 7 / 7 |
| Anchor model attempts retained | 14 | 14 |
| Anchor token-envelope units retained | 140,000 | 140,000 |
| Catalog / follow-up attempts | 0 / 0 | 0 / 0 |
| Anchor maximum retained | 168,000 micro-USD | 168,000 micro-USD |
| Whole synthetic run maximum retained | 1,146,032 micro-USD | 1,106,032 micro-USD |
| Selected actor observations joined to captures | Nine controls plus authority | Nine controls; authority is a no_candidate gap |
| Target assessment calls | 1 | 0 |
| Target readiness | ready | blocked |

Both runs meet the separate 300-second performance target. The harness's emergency execution timeout is 900 seconds and does not change any spending limit. Actual retained dimensions stay within the immutable 20/150,000/8/12 maxima. These are synthetic reservation amounts and HTTP responses, not real expenditure, invoices or live model accuracy evidence.

The actual frozen launcher child, upstream CLI and full linear engine automatically constructed `PendingProducerControl` with the control argument omitted. The same pinned source-policy hash appears in both fixed carriers and the factory observation. The target identity declaration is persisted and source-bound. The actor entered through the gathered findings; the saved target plan had no actors. The parent used real lifecycle, participant, handoff-adoption and completion APIs.

Each control has 59 verified producer artifact files. All fourteen anchor capture chains join unique HTTP attempts to committed ledger rows, provider JSON fingerprints, opaque dispatch facts, transport records and decoded extraction/review responses. Selected observations join their own review/proposal/row and captured attempts. The positive authority check follows the independently reviewed selector into exact retained UTF-8 bytes, then verifies the compiled claim ID, base node, passage, primary source mapping and node incidence. The missing-authority control has no admitted authority observation, reports `E_NOT_READY: target-first-v1`, and emits no final forecast case.

The pack-selected metering summary leads to the raw budget whose canonical hash matches the ledger-authenticated completion. All four counters agree with the retained scope. Actual parent adoption saves the identical `world_anchor_scope_completion`, adopts admission epoch 2 and leaves no active scope. Both synthetic spending ledgers are closed. In the negative control, pipeline status is failed while lifecycle ready denotes an authenticated published completion; executable target readiness remains blocked.

### Evidence and exact-source qualification

- [Final verification](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-v2-process-final-20261030-01/final-verification.json), SHA-256 `4dc0b9285d380091fdb807306107e8770e447cf2d5821871cde990fcff4dd8e3`.
- [Actor result](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-v2-process-final-20261030-01/actor/runtime-evidence/integration-result.json), [capture reconciliation](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-v2-process-final-20261030-01/actor/runtime-evidence/capture-reconciliation.json), and [source-after report](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-v2-process-final-20261030-01/actor/source-after.json).
- [Missing-authority result](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-v2-process-final-20261030-01/actor_missing_authority/runtime-evidence/integration-result.json), [capture reconciliation](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-v2-process-final-20261030-01/actor_missing_authority/runtime-evidence/capture-reconciliation.json), and [source-after report](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-v2-process-final-20261030-01/actor_missing_authority/source-after.json).
- Copy manifests verify 712 actor files and 702 negative files against the executed runtime bytes. Their SHA-256 values are `3bfeb13c372ed7e679926a28c273abac1c520e7e154c46f84965dcc0e57659f6` and `6d2dfb99a7d4ee102d1d3a4851c76a6eee2a4aabc8511b556d3ef930958612a1`. Archives are read-only evidence, not relocated execution or resumable-ledger claims.

All 172 copied repository application/bridge/bootstrap files match their released, pre-stage, staged, post-run and archived hashes. All 424 runtime pins per control, mirrored runtime descriptors, interpreter and dependency inventories match. The full 703-file reference was stable at staging. After the coordinator's root-gate repairs, 699 remain current: `test_run_spending_launcher.py`, `test_world_anchor_records.py`, `test_world_anchor_reflexive.py` and `test_world_anchor_budget_completion.py` changed only outside these runtimes. None was staged or imported; the exact before/after hashes are retained in both source-after reports. The initial two-drift reports are preserved as `source-after-initial.json` and `final-verification-initial.json` (SHA-256 `d77ff0758a550162d272b232261e62dc54c3bffcee5a5b76991c54fd16995c3e`). The three-drift reports are preserved as `source-after-three-unused-deltas.json` and `final-verification-three-unused-deltas.json` (SHA-256 `da96af58f53dd5490ebf536a993df693ad997300f6b29b04df69bf8c22156d0c`). Do not describe the whole current checkout as 703/703 unchanged.

The fourth change adds only `pytestmark = pytest.mark.guarded_runner` to the budget-completion test. Its release hash is `dce4a033deb488bfc4ee4e8d62d2ec4c2e2ed5d1be2abec3d0e87f128b688608`; its updated hash is `738e2766ac764c8fe6af90656ad700484ea2b51b52b6504b82e6e4db1b3f6c2e`. [Unused-reference update 04](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-v2-process-final-20261030-01/unused-release-update-04.json) records absence from both source/runtime manifests and all four Guard source inventories, unchanged result/archive identities, and rechecked 172/424 pins. Only the reports' `unused_release_drift` fields changed. No runtime was restaged and no process was rerun; the coordinator owns the separate guarded-test rerun.

The verifier initially assumed no WAL remained after hard exit. That was a verifier-only failure. It was corrected to reconstruct hash-verified DB/WAL/SHM copies in private scratch and open that copy read-only, preserving all originals. SQLite reconciliation confirms attempt identity, counts, retained amounts, closed run state and released owner without modifying the evidence ledger.

Each child retains the production hard exit and has `shutdown_complete=false` in its own guard receipt. Parent wait independently proves exit 0 or the expected exit 2, and the parent guard completes shutdown. Each child records two denied socket-construction and two denied process-discovery attempts; these remain blocked attempts, not zero-attempt claims. No external provider connection is admitted. Parent receipts record one allowed exact fixture child, preserved identity and no source drift.

Independent read-only review found no mismatch in executed source, captures, publication, selected observations, authority provenance, parent adoption, termination or archive integrity. James reviewed both the three-drift and final four-drift report updates: only `unused_release_drift` changed; both result files, archive manifests, timings, SQLite inputs and observation joins retain their previously verified identities. The added tests are absent from both runtime manifests and all four parent/child Guard source inventories. The final review independently rechecked all 712 actor and 702 missing-authority archived files against their manifests and original runtime bytes, plus the 172 copied repository and 424 runtime pins per control. Neither process was rerun for these report updates. Broader root-gate acceptance on the repaired tests remains coordinator work. This owner changed no production source, installed no dependencies, and made no commit or push.

- 2026-10-29: Created the bounded launcher v2 brief, exact interface and verification plan. No new approval for provider execution is implied.
- 2026-10-29: Added exact v2 request/spec/runtime/budget pinning, lower immutable limits within hard maxima, conservative profile checks, schema-paired manifest qualification and pre-import bound-child preflight. All 86 unchanged v1 launcher tests pass; Ruff passes. No v1 test source was edited.
- 2026-10-29: Independent static review found no actionable launcher defect. Corrected the note to state that successful profile preflight checks the envelope without reserving capacity; only actual attempt admission debits it. New v2 execution evidence remains pending.
- 2026-10-29: Euler delivered only the new test file, with 138 guarded passes and no remaining bounded review findings. This owner ran and inspected the final combined 224-case gate on unchanged launcher/core bytes. Source freeze and receipts were sent for integration; live catalog/credential mapping and provisioned v2 publication remain outside this owner slice.
- 2026-10-29: Halley independently verified all four final hashes, the combined JUnit/completion receipts and retained-before-POST control, confirming no outstanding focused findings. This closes only the documented offline launcher slice; no provider qualification or composed publication is claimed.
