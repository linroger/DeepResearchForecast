# Research merge owner

Updated: 2026-10-30 (Asia/Shanghai). Branch: `codex/world-anchor-main-merge`.
Status: Research implementation and independent review are complete. The frozen affected gate passed 282 tests with one existing separate-reference skip; the focused 37-case gate is included in that coverage. The coordinator confirmed closure of Hubble's C1/I1 review and the report/native affected reviews. Git staging, commit, push and merge are coordinator-owned. No further source changes or test runs are pending for this owner.

The coordinator also reports that its producer148 gate passed all nine omitted-control scenarios and the busy-store negative. That is coordinator-owned evidence; this note's direct acceptance evidence remains the linked frozen 282-case receipt. Earlier 331-case and composed results are historical for files changed afterward.

### Final frozen source and fixture hashes

| File | SHA-256 |
| --- | --- |
| `deerflow_bridge/linear_research.py` | `61180887db6292975ff3cfc2feee02e8bba1ee75971071757fd601d8a858c615` |
| `deerflow_bridge/research_gateway.py` | `e86ac279eb000fc0221af3e0eb2003231ca14ba9e97901128056af08582041e4` |
| `deerflow_bridge/cached_fetch.py` | `2e0a5dc1395114a3ccfdb94929fbd9bc60a97e27b2a17b85dca7b8c161ef6d0d` |
| `deerflow_bridge/deerflow_research.py` | `1c9fce49f4b9324e389c4b54e3a9c269090a9e83ea60ee01e8e6ab3ac7a84606` |
| `backend/app/services/target_pipeline.py` | `4585a688ebf20fb74dff13814229fd239c20a5dff458768e1243f3c5da44acf4` |
| `deerflow_bridge/target_research.py` | `0666fc8fb6baf55f2e62c420515d112b4229b002165f482110165738e229f420` |
| `backend/tests/test_world_anchor_main_merge_target_fmp.py` | `2dc19ba4149ec09e0297cf58b1ce79e9a5a84674fe763e0a163e4b251c63b07f` |
| `backend/tests/test_world_anchor_main_merge_research.py` | `cb8e3f2290870fa8f6ae2fd81364eeca19b10b6109445ac6320555595ff996eb` |

## Request and acceptance criteria

Own `deerflow_bridge/linear_research.py`, `research_gateway.py`, `cached_fetch.py`, `deerflow_research.py`, the new `backend/tests/test_world_anchor_main_merge_research.py`, and this note. Preserve main's research assessment, forecast tasks and official FMP capture/replay while retaining target, spending and World Anchor authority. Private v1/v2 spending permits only qualified model and Firecrawl routes. The coordinator owns Git delivery and shared import readiness.

The coordinator subsequently authorized a bounded C1 repair in `backend/app/services/target_pipeline.py`, `deerflow_bridge/target_research.py` for capture provenance, and new `backend/tests/test_world_anchor_main_merge_target_fmp.py`. During the 107-module composed hold, only the new unselected test was written/run; production and the F811 fixture-import cleanup waited for release. Acceptance added initial FMP generation admission, completed target reuse rejection after response-byte tamper or complete capture deletion, and exact provider-free fork copying. The completed repair preserves typed case authority and World Anchor publication.

## Plan and progress

Read the merge, World Anchor, spending, FMP, binder and research-grounding handoffs. Checked base `6ab52f77`, ours `f773f61b`, theirs `43efe06d`; the only textual conflict in the research slice was the KIQ exception boundary. Both `SpendingStop` propagation and fatal FMP capture-integrity errors survive. Automatic merges were reviewed against both parents, focused regressions were added, and guarded verification passed. No changes to read-only `search_tools.py` or `fmp_research.py` were needed. `cached_fetch.py` retains its automatically merged bytes.

## Findings and decisions

The merged FMP configuration and `ResearchTools.fmp_query` omitted the spending guard present on news/official-data tools. The constructor also omitted `fmp_store` from its rejected private-profile dependencies. This was an unsupported route before model-level schema rejection could protect the run. The engine now disables FMP before creating a store; the gateway rejects direct FMP dispatch and injected stores in both private profiles. Ordinary nonprivate FMP remains enabled.

The legacy CLI now rejects a private spending invocation before legacy setup can acquire context or FMP. Direct legacy FMP preparation also rejects required/bound contexts. Normal target/v3 dispatch remains responsible for activating and validating its immutable binding.

Parent environment closure was source-reviewed after the 331-case gate. `run_spending.configure_child` now fixes `FMP_ENABLED=false` and removes `FMP_API_KEY` from the child environment. The orchestrator calls it only when a spending binding exists, after `_fmp_subprocess_env()` and immediately before `Popen`; the nonprivate path keeps the ordinary FMP controls and credential inheritance. The launcher function is named `controlled_environment` in this checkout; it fixes `FMP_ENABLED=false` for both private runtime versions. `setup_execution` reconstructs its environment from that map, validated child controls, two permitted credentials and spending carriers. Child controls cannot override FMP keys, and `check_credentials` permits only the model and Firecrawl keys. No new source-review finding was identified. This is static inspection of the parent deltas, not a claim that the earlier receipt exercised them.

Preferred no-forwarding regression: extend `test_actual_run_attempt_argv_and_metadata_are_accepted_without_rewrite` in `backend/tests/test_run_spending_launcher.py` (line 675 at review). Its existing `prepared` fixture, real `_run_attempt` and intercepted `Popen` exercise the actual child boundary for both fresh and resumed requests. Supply a synthetic ambient FMP key and set `Config.FMP_ENABLED=True`; inside its existing `capture` callback assert `kwargs["env"]["FMP_ENABLED"] == "false"` and `"FMP_API_KEY" not in kwargs["env"]`. Check afterward that the ambient synthetic key is unchanged. This directly tests removal and override after normal FMP environment construction. For a small direct v1/v2 launcher-value assertion, reuse `test_frozen_core_and_provider_free_v2_preparation` in `test_world_anchor_launcher.py`, which already compares both `controlled_environment` maps: assert both maps disable FMP and contain no FMP credential. No test source was changed or suite rerun for this review request.

Source traces: stage 1 KIQ handling had only generic tool errors; stage 2 added fatal `CaptureIntegrityError`; stage 3 added `SpendingStop` propagation. The resolution retains both before generic degradation. Automatically merged files have only index stage 0; their base/ours/theirs sources were read through their parent revisions. Main's FMP reserved-identity fetch remains ahead of cache/HTTP fallback. Feature metadata envelopes and representation-specific cache keys remain intact. `ModelGateway.fan_out` joins context-copied workers before scope transitions. `target_research.execute_target` gathers candidate actors before `run_anchor_stage`, validates admitted actor structure after binding, and retains the fixed-control production factory.

The new merge-specific suite covers private configuration, direct discovery and calls, the actual KIQ dispatch wrapper, injected stores, direct legacy preparation, missing binding and CLI rejection before legacy setup. It pairs these with fatal capture-corruption propagation and ordinary immutable FMP capture/replay. Existing producer, metadata, main assessment and FMP suites supply end-to-end controls.

## Verification

AST parsing passed for all four owned production files and the new test. All three parent versions of the automatically merged files parse. Scoped `git diff --check` passed. The coordinator received readiness and the unqualified-route finding. Application imports and tests must use `backend/scripts/main_offline_pytest.py` with `/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B`. Earlier feature/main receipts do not verify these merged bytes.

The full `backend/app` and `deerflow_bridge` AST scan subsequently found no import syntax blockers, and the coordinator received the isolated-test start notice. The first guarded run passed 16 cases in 3.52 seconds. [Completion](/private/tmp/world-anchor-main-merge-research-20261030-01/completed.json) and [JUnit](/private/tmp/world-anchor-main-merge-research-20261030-01/junit.xml) record exit 0, completed shutdown, no source drift, three storage/log redirects and no network/process events. This checks both private authority versions and the ordinary FMP control; broader behavior is not inferred from these 16 cases.

The combined command used the same interpreter/guard with new evidence root `/private/tmp/world-anchor-main-merge-research-20261030-02`, running the merge-specific test plus `test_fmp_research.py`, `test_research_assessment.py`, `test_world_anchor_binding.py`, `test_world_anchor_source_metadata.py`, `test_target_research.py`, `test_run_spending_child_transports.py` and `test_research_engine_v3.py`. It passed **331 tests in 82.99 seconds, with no failures or skips**. [Completion](/private/tmp/world-anchor-main-merge-research-20261030-02/completed.json) and [JUnit](/private/tmp/world-anchor-main-merge-research-20261030-02/junit.xml) record exit 0, completed shutdown, no source drift and preserved identity. The [event log](/private/tmp/world-anchor-main-merge-research-20261030-02/events-42283.jsonl) records three storage/log redirects and two blocked process attempts: `uname` discovery and the intentional `unregistered-executable` negative control. There were no network events or contained-library probes. This is offline behavior evidence, not live-provider qualification.

At the 331-case checkpoint, all five then-owned Python files matched their receipt hashes, and AST/whitespace checks passed. The following snapshot is historical: its four production hashes remain current, while the merge-test hash was superseded by the function-AST-preserving fixture alias cleanup.

On the coordinator's shared-test release, all five hashes were checked again and still matched that 331-case receipt; AST parsing passed again. No redundant suite was run. The final reviewed hashes are listed at the top of this note.

| File | SHA-256 |
| --- | --- |
| `deerflow_bridge/linear_research.py` | `61180887db6292975ff3cfc2feee02e8bba1ee75971071757fd601d8a858c615` |
| `deerflow_bridge/research_gateway.py` | `e86ac279eb000fc0221af3e0eb2003231ca14ba9e97901128056af08582041e4` |
| `deerflow_bridge/cached_fetch.py` | `2e0a5dc1395114a3ccfdb94929fbd9bc60a97e27b2a17b85dca7b8c161ef6d0d` |
| `deerflow_bridge/deerflow_research.py` | `1c9fce49f4b9324e389c4b54e3a9c269090a9e83ea60ee01e8e6ab3ac7a84606` |
| `backend/tests/test_world_anchor_main_merge_research.py` | `57518353983b511e12e8a08b46add405440199239a71e4f774e3526a368fa453` |

## C1 repair history

C1 was reproduced as a merge finding: target research stage receipts and fork copying omitted the FMP capture generation. The new test uses the real orchestrator, FMP CaptureStore and official capture validators with only synthetic research/model/provider replies. The first attempt at `/private/tmp/world-anchor-main-merge-target-fmp-red-20261030-01` failed before reaching C1 because the fixture appended a source without advancing the typed case revision. That fixture-only failure is retained and is not behavioral red evidence.

After the legitimate typed revision transition was added, [red02 completion](/private/tmp/world-anchor-main-merge-target-fmp-red-20261030-02/completed.json) and [JUnit](/private/tmp/world-anchor-main-merge-target-fmp-red-20261030-02/junit.xml) record **9 failures and 2 passes in 6.04 seconds**, with completed shutdown, no source drift and only three storage/log redirects. There were no network/process events. Two initial-admission cases reach `_method_gateway` after response tamper or whole capture deletion. Six completed resume/continue/scenario cases return HTTP 200 after those mutations. The valid fork completes but its captured-artifact map is empty instead of retaining the exact response, capture manifest and binding. The two unchanged production FMP-validator controls reject the same damaged generations. These are consumer failures, not missing-import or fixture failures.

The accepted initial repair plan was:

1. In `target_research.py`, close and validate FMP through the existing engine/store API before final publication. Keep the closed typed case source schema unchanged. Enrich only exported `sources.json` rows from exact retained ledger/capture identities using the existing `fmp_research.metadata` projection, preserving vendor eligibility, capture path/hash and correlation identity. Ordinary non-FMP exports remain unchanged.
2. In `target_pipeline.py`, validate the full FMP generation before freezing case/evidence or entering downstream method work, using `official_data.fmp_capture_artifacts` and the existing question-bound `CaptureStore` proof. Detect retained declarations/correlation identities when the entire capture tree is missing. Record the complete artifact-hash map and capture provenance in optional target evidence; do not infer absence from an empty directory scan.
3. Extend target research stage receipt enumeration and validation with the recorded FMP file set and its exported source carrier. Compare the present validated generation with that recorded set on saved reuse. The existing `capture_fork_source` and `isolate_target_fork` must then copy those exact bytes, with pre/post validation and no provider acquisition. Preserve historical off generations with no FMP fields and keep the private dispatch prohibitions intact.
4. After release, apply the narrow F811 fixture alias cleanup, turn the nine red cases green, add the producer/export and old-off controls needed by the final implementation, and run the affected target/FMP/private suites under a new guard root. The coordinator will decide how to incorporate the corrected bytes into final composed acceptance.

The reproduced production hashes were `256600a8369bd1b99b2b49440b17603c7f6d6e3b4086995e8fd85c5953fa647e` (`target_pipeline.py`) and `d932cc42ab0d013a9286f4962c5edc0306fab88b6ac2a2e0f0518923c6ce3696` (`target_research.py`). The held original merge test was `57518353983b511e12e8a08b46add405440199239a71e4f774e3526a368fa453`. No production or previously selected test was edited during reproduction or the composed hold.

### Implementation after composed release

The first focused fix gate passed 134 and failed 5 because `ReportAgent` correctly enforces the closed five-field `target_evidence` schema. The coordinator accepted a separate optional `target_fmp_evidence.json` carrier instead. It binds the case, research question, exact FMP artifact set and exported source bytes through existing `CaptureStore`, `official_data.fmp_capture_artifacts`, a saved carrier digest and stage receipts. Initial admission validates before downstream method work. Completed reuse refuses missing, changed, expanded or unrecorded generations. No-FMP cases create neither the carrier nor its state key, and keep the report evidence bytes unchanged.

The second focused fix gate passed 144 and failed 2. Valid fork exposed the orchestrator's deliberate option allowlist; the repair stays in `isolate_target_fork`. It validates the captured parent fork proof, copies its exact receipt-owned files, derives the optional binding from that copied carrier, compares it to the validated parent binding and independently reconstructed capture generation, rechecks the parent proof, and validates the local child before saving adoption. Neither mutable parent options nor a conflicting child option can replace the captured generation. No orchestrator allowlist was changed. The other failure was a producer-test call using the planner's zero-fetch quota; the fixture now uses an admitted agent quota and the real FMP SDK through HTTP MockTransport.

`target_research` freezes FMP before final publication and enriches only exported sources from the exact retained ledger/capture identity. Typed case sources stay on their closed schema, and vendor eligibility remains explicit. The fixture alias cleanup is applied; every test/helper function AST is unchanged. Critical Ruff selectors plus F811 pass with Python 3.12 semantics.

[Focused fix03 completion](/private/tmp/world-anchor-main-merge-target-fmp-fix-20261030-03/completed.json) and [JUnit](/private/tmp/world-anchor-main-merge-target-fmp-fix-20261030-03/junit.xml) record **37 passed in 12.64 seconds**, no failures/skips, completed shutdown, no source drift and only three storage/log redirects. This includes all original C1 negatives; bound-question and source-provenance negatives; valid-but-expanded artifact membership; post-admission parent damage; parent/child metadata tampering; a valid resealed parent generation that must not replace an already captured fork; exact positive fork bytes; no-FMP compatibility; actual producer-to-FMP-SDK-to-export behavior with mocked HTTP; and both private spending versions' existing route denials. The initial/intermediate reds remain preserved.

The eight-module affected run at `/private/tmp/world-anchor-main-merge-target-fmp-acceptance-20261030-01` passed **282 tests with 1 existing skip in 138.02 seconds**: both merge research suites, target pipeline/reuse/research, FMP research, World Anchor target and composed World Anchor pipeline. [Completion](/private/tmp/world-anchor-main-merge-target-fmp-acceptance-20261030-01/completed.json) and [JUnit](/private/tmp/world-anchor-main-merge-target-fmp-acceptance-20261030-01/junit.xml) record exit 0, complete shutdown, no source drift, three storage/log redirects and two explicitly registered child interpreters, both exiting 0. There were no network or blocked-process events and no contained-library probes. The single skip is `test_archived_off_reference_bytes_rng_and_calls`, handled through the coordinator's separate stdin reference gate. Budget completion was not selected. The four changed C1/fixture hashes at the top of this note match this receipt; final AST, critical Ruff/F811 and whitespace checks passed. The coordinator subsequently confirmed the frozen acceptance remained stable and Hubble's review closed.

## Remaining work

There is no remaining implementation, test or review work in the research owner's assigned scope. The coordinator confirmed that Hubble's C1/I1 review and the affected report/native reviews are closed, and that producer148 covers all nine omitted-control scenarios plus the busy-store negative. No spending core or spending tests were edited by this owner.

Git staging, commit, push and merge remain coordinator-owned. Preserve the original red, intermediate correction receipts, accepted receipts and exact frozen hashes above. No additional source edits, test runs or broad reruns are authorized for this owner during staging.

Next-session prompt: Read this finalized note and the frozen acceptance receipts for delivery context. The research implementation and independent review are complete. Preserve the closed target evidence schema, typed case authority, optional FMP carrier, exact capture/source membership, bound question and authenticated fork adoption. Continue only coordinator-owned Git delivery unless the user explicitly reopens this scope.

No staging, commits, pushes, provider calls, service restarts, primary writes or further delegation were performed by this owner.
