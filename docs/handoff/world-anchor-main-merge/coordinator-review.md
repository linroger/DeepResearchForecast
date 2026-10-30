# Independent review of orchestration, admission and deployment

Updated: 2026-10-30T08:44:50Z (16:44 Asia/Shanghai), after independent C1/I1 exact-source closure. Initial review: 08:11:42Z (16:11 Asia/Shanghai).

**Disposition: C1 and I1 are closed for the exact source and regression hashes recorded below. No new concrete finding remains in this review's scope.** The original findings and initial source hashes are retained as history. Closure combines independent source inspection with review of the owners' recorded behavioral evidence; it is not whole-merge approval or Git-delivery verification.

## Reviewed identity and scope

- Worktree: `/Users/rogerlin/.codex/worktrees/world-anchor-main-merge/DeepResearchForecast`.
- Branch: `codex/world-anchor-main-merge`.
- Ours/main, observed as HEAD: `f773f61bee4eed6e2c3be23e546d114ff2a786e8`.
- Feature, observed as MERGE_HEAD: `43efe06defc78de9bedda73d1708ba4c750a6150`.
- Merge base recorded by the coordinator: `6ab52f7746bf7ec55e9f9921c71ba4ab08e33c01`.
- Reviewed the merge handoff and preparation, research, native, report and reflexive owner notes. Their test results are owner-reported context; this review does not independently attest those runs.

The review compared current source against both parents, with emphasis on `pipeline_orchestrator.py`, `run_spending.py`, `target_acceptance_run.py`, `simulation_manager.py`, the atomic default, bridge deployment and private FMP closure. Supporting target and research consumers were read to trace the actual interfaces. Source inspection used Git read commands, text reads/searches and SHA-256 checks. No application imports, tests, providers, delegation, Git mutation or production edits were performed. This document is the sole file written by this reviewer.

## Critical issues

### C1 — [P1, CLOSED] Completed target research bypassed the new FMP capture integrity boundary

The following is the original finding against target pipeline `256600a8369bd1b99b2b49440b17603c7f6d6e3b4086995e8fd85c5953fa647e` and target research `d932cc42ab0d013a9286f4962c5edc0306fab88b6ac2a2e0f0518923c6ce3696`. See the dated closure below for the accepted correction and current line references.

**Primary location:** `backend/app/services/pipeline_orchestrator.py:13831-13834`, where target execution returns before the ordinary research reuse/integrity path. The corresponding receipt omission is `backend/app/services/target_pipeline.py:71-77`.

**Trigger and consequence.** An ordinary, nonprivate `target-first-v1` run can now use main's FMP integration. After its research stage is complete, changing or removing an FMP response file does not invalidate the target research receipts. A resume can accept the unchanged typed case and continue downstream; a scenario fork copies the case and target receipts without the FMP capture files. This drops main's requirement that the exact captured response remain available and authenticated for reuse. Private spending profiles correctly disable FMP; this finding concerns the ordinary target route introduced by composing the parents.

**Current source trace:**

1. `deerflow_bridge/linear_research.py:5466-5468` configures FMP and advertises its tools before the target dispatch at `6121-6126`. `_configure_fmp` returns early only for a private spending context (`5475-5477`); ordinary target runs are not excluded.
2. Target sources are projected by `deerflow_bridge/target_research.py:61-81`. The projection retains the correlation URL and passage but omits `fmp_capture`, provider eligibility and the capture-file proof. Target finalization writes this projection to `sources.json` at `848-864`.
3. `backend/app/services/target_pipeline.py:71-77` seals only the case, estimators, target evidence, library, library publication and report for research. `target_evidence` at `438-452` contains official data, markets and news context, but no FMP capture closure.
4. `validate_stage` at `101-114` therefore never reads FMP files. Saved-target preflight uses those receipts and the case at `275-282`; completed research reuse at `378-381` skips the research child. Neither path reopens FMP captures.
5. Fork admission at `146-163` captures only those stage receipts, and `isolate_target_fork` at `190-197` copies only their file set. The ordinary fork's FMP copy/validation in `pipeline_orchestrator.py:9925-9957` is bypassed by the target early return at `9908-9911`.

**Parent comparison.** Main has no target early return. Its ordinary reuse path calls `_validate_research_contract` (main line 13635), whose FMP closure validates both captured bytes and the exact artifact set (main lines 4047 onward; merged lines 4070-4076). Main's `official_data.py:93-96` also binds every capture into the consumed generation. The feature supplies the target fast path and its receipt list but contains no FMP integration. Both `target_pipeline.py` and `target_research.py` are unchanged from the feature parent, so the new provider was never incorporated into that consumer contract.

**Required correction.** Extend target research admission, saved reuse and fork capture to pin and validate the complete FMP generation, including the response files and `fmp_research_binding.json`. Preserve explicit vendor/capture provenance so deleting the entire capture tree cannot make the run appear to have never used FMP. Retain the private-profile prohibition.

**Suggested regression, not executed:** complete target research with a synthetic immutable FMP capture, retain all target receipts, then change one response byte and separately remove the entire capture tree. Saved reuse must reject both before any downstream model call. A valid scenario fork must carry and revalidate the identical captured bytes without reacquiring the provider.

## Important issues

### I1 — [P2, CLOSED] Task-model calls preceded the enabled anchor's actual cast admission

The following is the original finding against manager `47a850fa27d4b054d74f59f3b81d700e34a4fb2b70c205ca9cae33a0adfa81af`. See the dated closure below for the accepted correction and current line references.

**Primary location:** `backend/app/services/simulation_manager.py:1128-1129`; the later rejecting boundary is `1209-1211`.

**Trigger and consequence.** In calendar mode, pass a valid, ready anchor context and otherwise valid research inputs whose selected actor cannot be joined to the anchor registry. The new early check at `1089-1093` accepts the context, then `admit_forecast_task` sends extraction and review requests before `bind_actor_cast` rejects the selected actor. A request that was deterministically inadmissible under the feature's cast contract can therefore spend two task-model calls before failing. This is premature work, not a claim that the private spending ledger can be bypassed.

**Current source trace:**

1. `world_anchor.validate_anchor_context` at `240-255` authenticates the pack and engine readiness. It checks a join only if the context already has `_join_bytes`; a freshly loaded research context has no actual simulation cast join yet.
2. `SimulationManager.prepare_simulation` calls this limited check at `1089-1093`, then invokes task admission at `1129`.
3. `simulation_config_generator.py:551` and `566` dispatch extraction and review through `_call_task_json`, whose provider call is at `501-503`.
4. Selection and cast construction occur later. The manager calls `bind_actor_cast` at `1211`; `world_anchor.py:458-466` rejects selected names without one exact retained registry alias. Thus this rejection comes after the task requests.

**Parent comparison.** Main introduces the early task call at its `simulation_manager.py:1069`, but has no anchor cast boundary. In the feature, the cast join is at `1120-1122`, before profile generation and before configuration generation, and there is no task-extraction model call ahead of it. The merge preserved both operations but placed the new calls before the feature admission check. The new merge regression at `backend/tests/test_world_anchor_main_merge_preparation.py:194-204` covers only `anchor_context={}`; it cannot detect an authentic context with an incompatible selected cast.

**Required correction.** For enabled anchors, establish the applicable deterministic cast/registry admission before task-model dispatch, either through a preflight or by coordinating the ordering of those checks. Preserve main's task extraction/review, immutable research admission and reprepare revocation; simply removing task admission is not a valid resolution.

**Suggested regression, not executed:** use a real valid anchor context, a calendar task, and a selected actor absent from its retained aliases. Assert the typed join rejection and zero task/profile/config model calls. Pair it with a valid join that still executes main's task extraction/review and seals both preparation authorities.

## Suggestions

No additional merge-introduced suggestion is raised in the requested scope. Both findings now have independently reviewed source corrections and recorded red/green evidence. This reviewer remains restricted to source and evidence inspection, without application imports or test execution.

## Positive notes and boundaries with no additional finding

- **Private FMP environment closure:** `run_spending.configure_child` at `421-454` disables FMP and removes `FMP_API_KEY` after ordinary environment construction. `pipeline_orchestrator.py:2597-2605` applies that closure immediately before `Popen`. It also replaces any detected `uv`/wrapper command with the private descriptor's interpreter and isolated child launcher.
- **Private parent and child setup:** `target_acceptance_run.py:454-460` accepts exactly the model and Firecrawl credentials; `463-488` fixes `FMP_ENABLED=false`; `491-553` returns only selected child controls; `694-709` reconstructs the runtime environment. No FMP override or credential forwarding was found in these paths.
- **Private research dispatch:** `linear_research.py:5472-5477` closes FMP before store creation; `research_gateway.py:4497-4499` rejects injected stores and `4552-4553` rejects dispatch. The legacy CLI rejects private non-v3 execution at `deerflow_research.py:18843-18847`, before legacy context/FMP preparation. The KIQ exception boundary at `linear_research.py:4280-4285` preserves both spending stops and fatal capture-integrity failures.
- **Preparation authorities:** main's research admission and reprepare revocation remain at `simulation_manager.py:1085-1115`. Native preparation binds and validates anchor sources before constructing the separate research preparation at `961-983`. Config sealing and validation retain both research-preparation and World Anchor bindings. No additional defect was found in those inspected checks.
- **Atomic default:** `backend/app/config.py:1254-1256` and the runner's `_world_arbiter_repair` at `3831-3841` agree on atomic behavior; explicit saved field/round settings take precedence in the runner. The environment example also states atomic. This is source agreement, not a replay test.
- **Deployment delta:** the `setup.sh:610` copy list and orchestrator `_DEPLOYED_BRIDGE_MODULES` at `1398-1405` retain both parents' anchor/spending/target and FMP additions. Main's FMP requirements copy and post-sync provisioning remain at `setup.sh:636-637` and `754-761`, with the orchestrator requirements sync at `1664-1666`. No merge-introduced omission was found in that delta; no clean installation was executed.

## Initial reviewed working-tree hashes

The first twelve source files below were hashed before and after the detailed review and were unchanged. Supporting files were hashed at review close. These hashes, rather than either parent commit alone, identify the reviewed merge resolutions. Later owner edits require an affected-path re-review.

| Path | SHA-256 |
| --- | --- |
| `backend/app/services/pipeline_orchestrator.py` | `2b8205e27ee920b8d4580c190fed800ae70f86fb4541cc71e082652666f2524a` |
| `backend/app/services/run_spending.py` | `d02c02f057be3a599cb849b43d17de6a67ae62a7975be6e49184ae43926c2d8d` |
| `backend/scripts/target_acceptance_run.py` | `72fbded1c76ddb864e298624090fd416cb98801671eb694eb8525fef5751084b` |
| `backend/app/services/simulation_manager.py` | `47a850fa27d4b054d74f59f3b81d700e34a4fb2b70c205ca9cae33a0adfa81af` |
| `backend/app/config.py` | `e262cf7fb79b2fbe00fef24393f3f7c5f53fa84821abdec0604c139c1dfe4325` |
| `setup.sh` | `3951b6136ec7ce135432c65d5e1f531c4956e1b3169b34591c452ad0c33ec16b` |
| `deerflow_bridge/research_gateway.py` | `e86ac279eb000fc0221af3e0eb2003231ca14ba9e97901128056af08582041e4` |
| `deerflow_bridge/deerflow_research.py` | `1c9fce49f4b9324e389c4b54e3a9c269090a9e83ea60ee01e8e6ab3ac7a84606` |
| `deerflow_bridge/linear_research.py` | `61180887db6292975ff3cfc2feee02e8bba1ee75971071757fd601d8a858c615` |
| `deerflow_bridge/cached_fetch.py` | `2e0a5dc1395114a3ccfdb94929fbd9bc60a97e27b2a17b85dca7b8c161ef6d0d` |
| `deerflow_bridge/fmp_research.py` | `aad88e158bf3b243a8cb0a6f56afc4a135aa833a20544a2ca58f5c026c0d17ca` |
| `deerflow_bridge/search_tools.py` | `bd600f1b6ec41ee34cc0a208491d79ffd9968f74097bb8ff92741b18091fed4a` |
| `backend/app/services/target_pipeline.py` | `256600a8369bd1b99b2b49440b17603c7f6d6e3b4086995e8fd85c5953fa647e` |
| `deerflow_bridge/target_research.py` | `d932cc42ab0d013a9286f4962c5edc0306fab88b6ac2a2e0f0518923c6ce3696` |
| `backend/app/services/simulation_config_generator.py` | `cc7a5403c9c17486a6a66f1011b8a827af11eaf02db8e5b06ffec7b5047eb50b` |
| `backend/app/services/world_anchor.py` | `a26021efb3556bae4e86ffa4f8f5c956db537ba76d2e3888e4517084684ea880` |
| `backend/app/services/official_data.py` | `87654feeca820cf4232785b78fb2225311235224c260d6e97d6f221c37ce500a` |
| `backend/scripts/run_parallel_simulation.py` | `3d19be782523cf6052a8a3ba753a59012c92bcf17f5846c731a6bc984d0ad94d` |
| `.env.example` | `413829c6123f6ffaf996c18d61e723d112e32ffe317bdfaa86cded71c6cb195a` |

## I1 exact-fix closure — 2026-10-30

**Closed. No new finding in the exact I1 correction.** Both merge parents remain unchanged from the identities recorded above.

The manager now leaves `admitted_task` unset at `simulation_manager.py:1129` and preserves the original early admission only when `anchor_context is None` (`1130-1131`). For enabled anchoring, the actual selected cast binds at `1213`, then the single task admission runs at `1215`, before actor-context and profile generation. The existing join validator remains authoritative. Research-input admission, same-ID preparation checks, revocation, task/config equality checks and both seals remain intact.

I independently reconstructed the preceding manager bytes in memory by reversing only those two changes. Their SHA-256 exactly matches the originally reviewed `47a850fa27d4b054d74f59f3b81d700e34a4fb2b70c205ca9cae33a0adfa81af`, establishing that this is the complete production delta. No file was reverted or executed.

### Behavioral evidence inspected

- **Red:** [completed.json](/private/tmp/world-anchor-main-merge-cast-preflight-20261030-01/completed.json) and [JUnit](/private/tmp/world-anchor-main-merge-cast-preflight-20261030-01/junit.xml) record one failure and one pass, zero errors/skips, in 17.724 seconds. The failure is the intended assertion: an authentic ready anchor rejected `Unregistered Vendor` with `invalid_anchor_join` only after `FORECAST TASK EXTRACTION` and `FORECAST TASK REVIEW`, totaling two model calls. The valid-cast positive already passed. The receipt records exit 1, completed shutdown, preserved identity and no drift across 167 pins.
- **Green:** [completed.json](/private/tmp/world-anchor-main-merge-cast-preflight-20261030-02/completed.json) and [JUnit](/private/tmp/world-anchor-main-merge-cast-preflight-20261030-02/junit.xml) record **96 passed, zero failures/errors/skips, in 50.590 seconds**, exit 0, completed shutdown, preserved identity and no drift across 177 pins. Both new tests pass. The negative requires the typed rejection, failed/unprepared state, no executable config and zero recorded model calls. The positive reopens a real published context without a prebound dummy join, performs extraction/review exactly once each, and verifies the actual selected actor, C5 classification, task/calendar agreement and both preparation seals.
- The same green JUnit also records passing off-mode unresolved-task ordering, failed reprepare revocation, task/report endpoint agreement, native source-mismatch rejection and combined native manager/runtime/result/replay/fork cases. These are inspected recorded results, not tests rerun by this reviewer.

The scripted fixture intercepts the profile and config/task model boundaries while retaining real admission, selection, join and sealing code. The new regression file is byte-identical in the red receipt, green receipt and current checkout. The existing preparation-test cleanup is limited to fixture imports/re-exports: independently reversing those changes reconstructs the prior `f2302431f524d328d3b3268b89bd2cc5cfffb005e25bf19186c2e8ed3e3e62bb` file, and all nine top-level function/class ASTs are identical.

### Exact closure hashes

| Path | SHA-256 |
| --- | --- |
| `backend/app/services/simulation_manager.py` | `dbe67dfb07ad31ef8cd928d44ee562bce95e5b0120c8df9421fcdd21e2bf33a1` |
| `backend/tests/test_world_anchor_main_merge_cast_preflight.py` | `5ede58d5ab3fac3537f5e2a06d28efd384270d910a950b4c7149868f03386e24` |
| `backend/tests/test_world_anchor_main_merge_preparation.py` | `e52cd22b45ddddd2bb08240554bef5e8f82d6139cb4eb944fd8b48d35a5b2973` |
| Red `completed.json` | `f36311737fda4ac13502c76fc80191bfbc276f2b1267091c5011a8df8799deff` |
| Red `junit.xml` | `16568d778f09975e6eee644079070247a71066cc7aa9a84b4d50e6c2a429caea` |
| Green `completed.json` | `e1bd477bfdf932381a726111dcfea503f618d8b1acfc519e7c2d97fe93d05856` |
| Green `junit.xml` | `a33ba4e1d7e1514c53705404e32bd63344df254b2f667ce3366815fabfa485f7` |

The current manager, both test files, config generator, actor context, anchor adapter and official-data adapter all match the green receipt. Rehashing all 177 recorded pins found 175 still matching; `backend/app/services/target_pipeline.py` and `deerflow_bridge/target_research.py` have changed after that run during the separate C1 repair. The receipt's zero in-run drift therefore supports this I1 closure but does not verify those later C1 bytes or the current combined tree.

Both guards recorded one denied socket creation, four denied subprocess launches and 20 denied external reads. These remain blocked attempts, not zero attempted operations or live-provider evidence. This rereview performed only static source/AST/hash inspection and receipt parsing, with no application imports, test execution, source edits or Git mutation. Only this review document was updated.

## C1 exact-fix closure and I1 reconfirmation — 2026-10-30

**C1 closed. I1 remains closed. No new concrete defect was identified in either exact fix.** HEAD and MERGE_HEAD still identify the two parents recorded at the start of this review.

### Producer and public consumer trace

- `deerflow_bridge/target_research.py:856` freezes and validates FMP through the existing engine API before target publication. `_export_sources` at `455-477` retains the exact capture metadata in exported `sources.json`, validates ledger/store/source identities and rejects a reserved capture URL whose provenance disappeared. The typed case source schema stays unchanged.
- `backend/app/services/target_pipeline.py:68-121` validates the full captured generation against the question, joins exported source metadata back to the typed case and capture store, and rechecks the bytes before returning a hash map. Missing entire trees remain detectable through retained declarations/correlation identities. The capture store uses `env={}` and replay mode; the helper does not acquire a provider. Private spending contexts still reject an imported FMP generation.
- Initial admission at `target_pipeline.py:519-530` runs before case/evidence publication and downstream method work. It persists a separate `target_fmp_evidence.json` carrier and pin, leaving the existing report evidence's five-key schema intact. Previously admitted cases cannot silently acquire a replacement generation.
- Research receipt enumeration at `174-175` uses the recorded capture set. Validation at `193-218` requires agreement among the option pin, carrier, current generation and manifest entry set. The public resume/continue/scenario preflight reaches this check at `398-399`. The report preparation API also reaches it through `backend/app/api/report.py:619-622`; its five-key check at `654-657` remains compatible with the separate carrier.
- Fork execution at `target_pipeline.py:290-335` compares the parent with the captured fork proof before copying, verifies every copied file hash, derives the child pin from the exact copied carrier, validates that carrier against the copied capture tree, rejects a conflicting child pin, rechecks the parent proof, and validates the installed child before saving it. Mutable parent options alone cannot replace the captured generation.

### Evidence independently inspected

The retained behavioral [red completion](/private/tmp/world-anchor-main-merge-target-fmp-red-20261030-02/completed.json) and [JUnit](/private/tmp/world-anchor-main-merge-target-fmp-red-20261030-02/junit.xml) record **9 failures and 2 passes in 6.041 seconds**. These are the initial-admission, six HTTP reuse and valid-fork failures described in C1, with the unchanged capture-validator controls passing. The earlier red01 fixture failure was not used as behavioral evidence.

The exact-candidate [focused completion](/private/tmp/world-anchor-main-merge-target-fmp-fix-20261030-03/completed.json) and [JUnit](/private/tmp/world-anchor-main-merge-target-fmp-fix-20261030-03/junit.xml) record **37 passes in 12.642 seconds**, zero failures/errors/skips, completed shutdown and no registered drift. All nine original failing case names are present and passing. Current hashes match all 12 recorded pins. The expanded tests cover altered response bytes, complete capture removal, provenance escalation, wrong-question captures, a valid but expanded generation, parent damage after fork admission, altered parent/child pins, a newly resealed parent, exact provider-free fork preservation, absent-FMP compatibility and real target producer export through the MCP SDK with fixture HTTP responses. The paired 16-case private-research suite also passes.

The completed eight-module [acceptance receipt](/private/tmp/world-anchor-main-merge-target-fmp-acceptance-20261030-01/completed.json) and [JUnit](/private/tmp/world-anchor-main-merge-target-fmp-acceptance-20261030-01/junit.xml) record **282 passes and one skip in 138.016 seconds**, zero failures/errors, exit 0, completed shutdown, preserved identity and no registered drift. All **24 recorded source pins** still match the checkout. Its modules cover the new target/FMP regression, private research, target pipeline, public reuse, target producer, FMP research, World Anchor target and World Anchor pipeline.

The single skip is `test_world_anchor_target.py::test_archived_off_reference_bytes_rng_and_calls`, with the explicit reason that archived source is supplied through stdin in a separate off-reference gate. It is not counted as passing or independently closed by this review. The parent receipt records three storage/log redirects and two allowed guarded import-layout children; both child receipts show exit 0, completed shutdown, preserved identity, no drift and no audit events. No live-provider verification is claimed.

The research-suite fixture cleanup is also verified: reversing only its import/re-export changes in memory reproduces original hash `57518353983b511e12e8a08b46add405440199239a71e4f774e3526a368fa453`, and all nine function/class ASTs remain identical.

### Exact C1 closure hashes

| Path | SHA-256 |
| --- | --- |
| `backend/app/services/target_pipeline.py` | `4585a688ebf20fb74dff13814229fd239c20a5dff458768e1243f3c5da44acf4` |
| `deerflow_bridge/target_research.py` | `0666fc8fb6baf55f2e62c420515d112b4229b002165f482110165738e229f420` |
| `backend/tests/test_world_anchor_main_merge_target_fmp.py` | `2dc19ba4149ec09e0297cf58b1ce79e9a5a84674fe763e0a163e4b251c63b07f` |
| `backend/tests/test_world_anchor_main_merge_research.py` | `cb8e3f2290870fa8f6ae2fd81364eeca19b10b6109445ac6320555595ff996eb` |
| Red02 `completed.json` | `3e7a85ba5a5682289e7d4125cf221198bf732aff1c2e6f1e71f7747e85b7f87b` |
| Red02 `junit.xml` | `ef98474d80b8fc766f88a515742ad23ac97931daee721f3613173781eacc54e6` |
| Focused03 `completed.json` | `826f8adc56e7adc40cad9be12fa0bfd631a9852d417334ad9f0a592fb8a50ebe` |
| Focused03 `junit.xml` | `a0d9e73aa26dd5f7ec71e72a0b9ba56060f04ec9000d9aa539805a5e15d53520` |
| Acceptance01 `completed.json` | `68b25ccb652c9719629bdcf535e5735be8b2feb6ad76fed78db78561fb0a052d` |
| Acceptance01 `junit.xml` | `b0b7ac72df9780f000bf27d37362e04f6c562739d25982a369ab882d621608ee` |

I1's manager, unchanged red/green regression, preparation-test cleanup, config generator, actor-context adapter, anchor adapter and official-data adapter were rehashed against its 96-pass receipt and all still match. The C1 acceptance also pins the same accepted manager `dbe67dfb07ad31ef8cd928d44ee562bce95e5b0120c8df9421fcdd21e2bf33a1`. It does not rerun the I1 regression module; the earlier inspected 96-pass result remains the behavioral evidence for that finding.

## Remaining work

No further correction is requested for C1 or I1 on these exact hashes. The coordinator retains responsibility for other review findings, the separate archived-off gate, final combined-tree acceptance and Git delivery. Later changes to a reviewed path require an affected-path recheck. This reviewer performed no application imports, test execution, source edits, delegation or Git mutation; only this review document was updated. No deployment, remote-delivery or whole-merge acceptance is claimed here.
