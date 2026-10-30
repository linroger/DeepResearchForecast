# Independent acceptance review

**Status:** Complete. Both original P2 findings and all four composed-gate context failures are closed; final gate verified at 718 passed / 0 failed / 0 skipped. **Date:** 2026-10-28. **Baseline:** `e0b233779a08493603360ddd4b5f4ba12a0183bf`. **Branch:** `codex/target-first-acceptance`.

## Scope and ownership

This reviewer owns only this file. The task is to review the actual receipt-bound ontology to PREPARE cast seal to configuration, world seed, and decision consumers; exact identity ambiguity; rollback and missing-ontology compatibility; direct API and integration-seed callers; and the saved-world replay tool's coverage, invalid-input handling, preservation, and aggregate privacy. The live budget document is reviewed only for alignment of its stated blockers with the authorized scope.

No source edits, production saved-root reads or writes, provider/network probes, paid calls, schedulers, commits, or pushes are authorized. Any necessary tests must use the unchanged `backend/scripts/main_offline_pytest.py` with the deployment interpreter's `-I -S -B` flags and a new canonical `/private/tmp` evidence directory. The parent's broader manager/PREPARE/API checks will not be duplicated.

## Acceptance and plan

1. Read the stage handoff, plan, owner records, live-readiness proposal, and the baseline diff.
2. Trace actual caller paths and record only actionable P1/P2 findings with a concrete scenario and source lines.
3. Inspect focused tests and use a narrow guarded check only where it resolves an identified uncertainty.
4. Reconcile findings after owners freeze, then record exact source hashes and evidence limits.

## Findings

### Closed P2 — present invalid ontology receipt becomes legacy absence

**Source:** `backend/app/services/pipeline_orchestrator.py:7341-7343`; supporting loader at `:1131-1145`; public consumer at `backend/app/api/simulation.py:644-654`.

`load_preparation_ontology()` calls the general best-effort manifest loader, then treats `.get("ontology") is None` as optional absence. This accepts a present `{"ontology": null}` receipt and a present malformed manifest (the general loader returns `{}` on parse failure) as `None`. A bound secondary simulation can still have valid consumed research-core proof, so the direct API reaches fresh PREPARE with no ontology keyword and silently retains legacy text inference. The new hash/path rejection only handles non-null entries after this early return. This contradicts the new helper's explicit rule that a present invalid receipt cannot silently change decision rights.

**Requested narrow fix:** distinguish a genuinely absent manifest/key from a present invalid manifest/value; reject invalid present data before graph/persona dispatch, preserve the absent-key and explicit `legacy` paths, and cover null/malformed receipts through the direct API. This is source-traced evidence; a new runtime reproduction has not yet been executed by this reviewer.

**Closure:** the parent reports three failing public-API cases before repair. The repaired helper at `pipeline_orchestrator.py:7343-7367` uses `_research_data_read()` for bounded no-follow manifest reads, rejects invalid present roots/entries, returns `None` only for absent file/key or explicit rollback, and compares the entire manifest after reading the ontology. The reviewer independently executed the three repaired public-API cases plus the two missing-ontology/rollback cases and positive exact-owner case: **6 passed** in 13.93 seconds, `/private/tmp/drf-acceptance-independent-review-20261028-r5`. Each invalid public-API case asserts HTTP 409 and zero profile-model dispatches. No open finding remains at this boundary.

Both reproduced P2 findings are closed with focused independent verification and final source reconciliation against the C5 and replay owner freezes.

### Closed P2 — malformed raw pre-state is silently normalized and counted as checked

**Source:** `backend/scripts/replay_saved_world.py:303-318`, `:344-348`; normalizing consumer `backend/app/services/world_model.py:2939-2945`.

A supplied `arbiter-raw/v1` fixture can contain duplicate `agent_id` rows inside `pre_arbiter_world`. The raw-prestate validator checks only that the six collections contain dictionaries and that the round is contiguous; it does not enforce the unique actor IDs already required for final state at `replay_saved_world.py:107-108`. `WorldModel.from_dict()` then silently overwrites the duplicate identity. The aggregate still reports `input_status=valid_structural`, `raw.status=checked`, and `raw.replayed=1`, although the supplied pre-state was not faithfully admitted. A conflicting duplicate can change the actor class/rights used by validation. Duplicate variable and interaction IDs have the same normalization hazard.

**Requested narrow fix:** validate raw-prestate identity and required row shapes before passing it to the permissive runtime loader; reject malformed input with a fixed code and exit 2, preserve input hashes, and do not increment checked/replayed counts. Reuse the final-state identity checks where suitable. No new replay engine or historical reconstruction is requested.

**Evidence:** the controlled diagnostic below passed in `/private/tmp/drf-acceptance-independent-review-20261028-r4`, confirming that the current tool counts a duplicate-ID prestate as checked. It used no private inputs. The gate had one unknown-marker warning because documentation collection bypasses backend pytest configuration, and one contained external-read attempt; it is not a zero-attempt receipt.

## Verification and limits

Initial read-only inspection confirmed the requested branch and baseline. Concurrent parent and worker changes are present and are preserved. Historical owner test claims are context, not reviewer-executed proof.

**Replay closure:** `_validate_raw_prestate()` now validates actor, variable, interaction and relationship identities plus commitment/effect references before the runtime loader. The shared identity validator preserves final-state checks. Independent gate `/private/tmp/drf-acceptance-independent-review-20261028-r7` passed **19 cases** in 1.76 seconds: 16 malformed registry cases, two valid field/round-policy cases and missing-full-prestate coverage. Every negative asserts exit 2, fixed invalid-input output, no model-state load, unchanged bytes and no private canary. Normal shutdown, identity preservation, no blocked operations/probes and no source drift were verified. No further actionable P1/P2 was found in this repaired path.

### Positive findings and scope assessment

- The manager builds `agency_classifications` once at `simulation_manager.py:1033-1040`, adds it and selected-actor bases to the cast manifest, and writes/hashes that manifest at `:1066-1070`. Persona construction starts later at `:1141`; the hash is handed to its role proof at `:1146`. The executable configuration seal is correctly created after configuration generation at `:1375-1396`; the pre-persona seal is the cast/context authority, not a not-yet-created config.
- The exact map reaches `generate_config` at `simulation_manager.py:1273`, is applied before initial-post assignment at `simulation_config_generator.py:683-693`, and is forwarded to the world-seed builder. Seed class and capacity use the resolved class at `world_model_seed.py:1187-1222`. `WorldModel.from_seed` consumes it at `world_model.py:1174`, and `option_feasibility_problem` selects/checks the runtime class's action catalogue at `agent_decision.py:413-427`. The independent nine-case gate exercises this actual runtime path, reverse alias ambiguity, malformed map fallback and omitted-map serialization.
- Fresh primary preparation and integration-seed preparation both call the same receipt reader. The direct API consumes its bound pipeline ontology and checks already-prepared simulations before that reader. Missing ontology and explicit rollback add no classification/basis fields. No changed saved-config load path rewrites an existing run. The frozen worker's baseline byte comparison and private three-actor specimen are owner-executed evidence; this reviewer inspected their source/record but did not repeat private snapshot reads.
- The replay report explicitly says partial, conditional, and not full-trajectory equivalence. Missing raw capture/full prestate stays unavailable. Success outputs contain fixed aggregates, input/source hashes and fixed status codes; runtime exception messages are not serialized. The focused checks confirm preserved controlled inputs, output-newness/location constraints and private-canary exclusion. The separate 19-case repair gate closes the raw-prestate admission finding without upgrading conditional historical coverage.
- The live readiness document's scope is appropriate: existing post-response meter checks, broad estimator/actor exception handling and attempt-local callbacks do not establish a durable all-in cap. The proposed shared spending boundary is explicitly future opt-in work requiring approval; no implemented budget or live readiness is claimed. The separately approved failed free transport probe neither authorizes paid execution nor supplies model-provider acceptance.

### Reviewer-executed evidence

| Receipt | Result and interpretation |
|---|---|
| `/private/tmp/drf-acceptance-independent-review-20261028-r1` | Nine focused existing cases passed; no skips, blocked operations or discovery probes; only three expected storage redirects. |
| `r2`, `r3` at the same prefix | Documentation diagnostic stopped at test-fixture import before application execution; not behavioral evidence. |
| `r4` at the same prefix | One controlled diagnostic reproduced the duplicate-actor raw-prestate bug. One unknown-marker warning and one denied read of `<IDENTITY>/.pdbrc`; no source drift. |
| `r5` at the same prefix | Six focused parent-consumer cases passed. Normal shutdown, preserved identity and no source drift. Import activity attempted one socket, four subprocess launches and 20 external reads; all were blocked. Contained discovery includes `fc-list`, `system_profiler` and 18 font-directory scans. These attempts are disclosed, not described as zero probes. |

No provider connection, production saved-root access, paid call, scheduler, commit, or source edit was performed by this reviewer. The only repository write is this review file; test outputs reside in fresh private evidence roots. Full historical trajectory/raw acceptance and live-provider acceptance remain outside these results.

### Historical controlled diagnostic before repair

This retained transcript records the controlled r4 reproduction against pre-repair script hash `ef5ac51bca0c0dc83dc91a1e69ab79bdd65b98609f2f9c32ef11420712dd3c6a`. The prefix `r4>` denotes historical input, not an executable current doctest. Current behavior is tested by `test_raw_prestate_rejects_invalid_registries_before_model_load`; the repaired tool rejects this payload. All app execution remains restricted to the unchanged guarded runner.

```text
r4> from copy import deepcopy
r4> from pathlib import Path
r4> import importlib.util
r4> spec = importlib.util.spec_from_file_location("review_replay_fixtures", Path.cwd() / "backend/tests/test_saved_world_replay.py")
r4> fixtures = importlib.util.module_from_spec(spec)
r4> spec.loader.exec_module(fixtures)
r4> tool = fixtures.replay.__wrapped__()
r4> payload = fixtures._controlled()
r4> raw = fixtures._raw_fixture(payload)
r4> raw["pre_arbiter_world"]["actors"].append(deepcopy(raw["pre_arbiter_world"]["actors"][0]))
r4> payload["arbiter_raw.jsonl"] = [raw]
r4> result = tool.analyze(payload)
r4> (result["input_status"], result["raw"]["status"], result["raw"]["replayed"])
('valid_structural', 'checked', 1)

```

## Updates

- 2026-10-28: Created the review record before detailed source inspection. Read the requested stage documents and initial source diff. Final closure awaits owner freeze and source-hash verification.
- 2026-10-28: Traced map insertion before cast hashing and persona generation, map propagation into configuration/seed, and `WorldModel.from_seed` consumption by action decision-right checks. Reported the present-null/corrupt-manifest fallback as an actionable P2; preserved concurrent owner changes.
- 2026-10-28: The independent focused gate `/private/tmp/drf-acceptance-independent-review-20261028-r1` passed nine existing scenario checks in 1.93 seconds. Added a controlled diagnostic for raw-prestate duplicate identity; guard receipt inspection and the diagnostic run are pending.
- 2026-10-28: Diagnostic r2 stopped at fixture import because documentation-only collection does not load the backend test path setup. Added the explicit backend import path; no application scenario ran in r2 and no source was changed.
- 2026-10-28: Diagnostic r3 also stopped before application execution. The actual cause was the installed regular `tests` package taking precedence over the repository's implicit namespace; backend conftest normally binds that namespace. The diagnostic now loads the exact fixture source by path, without changing the guard or production source.
- 2026-10-28: Diagnostic r4 reproduced malformed raw-prestate acceptance. Reported the second actionable P2. Inspected r1/r4 guard receipts: normal shutdown and identity preservation, no source drift; r1 has only three expected storage redirects, while r4 also contains one blocked external read. All receipt-listed source hashes still matched at this check.
- 2026-10-28: Parent reports a 3/3 public-API red reproduction for the null/corrupt ontology receipt finding and a strict-reader repair; fresh source review and closure are pending.
- 2026-10-28: Independently rechecked the strict reader and completed the six-case r5 gate. Closed the ontology-receipt finding with actual public-API rejection/no-dispatch evidence and missing/rollback controls. The raw-prestate finding remains open. Added the full consumer/seal trace, live-scope assessment and truthful guard-event accounting.

- 2026-10-28T10:41:44.321427+00:00: Closing hash verification caught a concurrent addition of a real WorldModel/action-menu assertion in the parent test file. Ran only that changed case in `/private/tmp/drf-acceptance-independent-review-20261028-r6`: one passed in 12.74 seconds. Current source hashes match the r6 receipt, with normal shutdown and preserved identity. Its contained import attempts match r5 (one socket, four subprocess launches, 20 external reads); no guard relaxation occurred. No production/helper changes were made by this reviewer.

## Interim source snapshot before replay repair

Captured at 2026-10-28T10:41:44.321427+00:00 after the C5 owner reported its final freeze and the parent supplied the repaired reader and runtime-consumer assertion. The four C5 Python digests match the owner freeze; the parent source matches the independently executed r6 receipt. Replay-tool approval remains conditional on resolving the open P2; any correction needs a new focused check and hash snapshot.

| Source | SHA-256 |
|---|---|
| `.env.example` | `1662c2f55f954ff26225a56fe7533762d802623c571d0681476b86cff48c673c` |
| `backend/app/config.py` | `406cf338c01c218cecf9db7dda0bfcc05201b534c18c18e995862f58fd0a2032` |
| `backend/app/api/simulation.py` | `84dd4c8f2ef598a5425d114877806eac2779818a641f68e05dc7033b5abfd26c` |
| `backend/app/services/pipeline_orchestrator.py` | `5c3054be0d77247164e752d741110ac0f0998b3779a49c27360625730bfc1325` |
| `backend/app/services/simulation_manager.py` | `bb0a5d95cc52f5e07531993db31863e819c21e9e622846cdc59b8f16bd6cc33a` |
| `backend/app/services/agency_classification.py` | `9405c796d19d43fc0d52e0f272e5531d4d4667df9a6e6a7904fb87739242b4ba` |
| `backend/app/services/simulation_config_generator.py` | `8de3804f77f7bfd49b7d4a514e508ffaece36ecce159e349f2ba654475d1c541` |
| `backend/app/services/world_model_seed.py` | `30832cbf1f70afe49d74c225dbce3f25f0f77c531c51b0d15bd4425cff64d606` |
| `backend/scripts/replay_saved_world.py` | `ef5ac51bca0c0dc83dc91a1e69ab79bdd65b98609f2f9c32ef11420712dd3c6a` |
| `backend/tests/test_agency_classification.py` | `a95dc5409f399580240f205b98910830a944abca390bd39337d3b388f3ea73ec` |
| `backend/tests/test_agency_preparation_consumers.py` | `4ee0d2f4d27e8695ae77730de7ae9e8451c82c62a60cd8dafb9c127cd26cc3a0` |
| `backend/tests/test_saved_world_replay.py` | `3478ac32b9c6cde36271ca7c6133a4aa2da5ce8878b1b57d5d8ca84f167f3c42` |
| `backend/app/services/world_model.py` | `805c5f67e26176de9ac722145aa4662627b8c9d58a8d522fa6c1a3997752067a` |
| `backend/app/services/agent_decision.py` | `17a458fa6acadd5d4646b5d256e33f51f41826f54879676412fc74ee3722a244` |
| `backend/app/services/world_update.py` | `507ba97936dc306f3f7e009235811e08c1a3969066d49fd769bb85526e2832f6` |
| `backend/scripts/main_offline_pytest.py` | `5046cf820fa468d8e8ffb2e3fdade1d20fca2f0bd56ee15eabdff51c223c02be` |

**Historical next review prompt, now fulfilled:** Re-read this review and the replay owner record. Address only malformed raw-prestate identity/row admission; add a guarded CLI regression asserting fixed invalid-input output, exit 2, unchanged inputs and no private text. Re-run the controlled raw case to retain valid field-versus-round behavior, then return the final frozen replay source/test hashes for closure. Preserve all other owner files and keep live-budget implementation/paid execution outside this review.

- 2026-10-28T10:42Z: Concurrent replay-owner work has added targeted raw-prestate regression cases. The table above is an interim snapshot, not final replay approval. Keep the second finding open until the repair and its source freeze are inspected; no reviewer source edits are authorized or performed.

- 2026-10-28: Independently verified the repaired raw-prestate admission in r7: 19 passed, no skips, no blocked operations/probes, no source drift and preserved identity. Closed the second P2, retained the original red diagnostic as historical evidence, and left final hash reconciliation pending the replay owner freeze. The concurrent temporal test adjustment is outside this review assignment and is not covered by this approval.

## First closure and frozen sources (before composed context repair)

**Closed at 2026-10-28T10:48:22.356413+00:00.** The replay owner explicitly froze the repaired source/test files in `replay-owner.md` section “P2 repair source freeze”. All eight entries in its retained source-freeze receipt match the current workspace, and all sources recorded by reviewer gates r6/r7 match. The four C5 Python files retain their owner-frozen hashes. There are no remaining actionable P1/P2 findings in the assigned ontology/classification/replay scope.

The reviewer inspected the replay owner’s final `completed.json`, `junit.xml`, `preservation.json`, and `source-freeze.json` under `/private/tmp/drf-replay-prestate-20261028-final`. They record 40 passing cases, zero failures/errors/skips, normal shutdown, no blocked operations and no source drift. The preservation receipt records all 100 frozen files matching and identical historical aggregate semantics. These are owner-executed specimen checks, independently inspected; the reviewer did not read production saved roots or rehash private input bodies. The reviewer’s own repair check is r7 (19 passing controlled cases).

| Source | SHA-256 at first closure |
|---|---|
| `.env.example` | `1662c2f55f954ff26225a56fe7533762d802623c571d0681476b86cff48c673c` |
| `backend/app/config.py` | `406cf338c01c218cecf9db7dda0bfcc05201b534c18c18e995862f58fd0a2032` |
| `backend/app/api/simulation.py` | `84dd4c8f2ef598a5425d114877806eac2779818a641f68e05dc7033b5abfd26c` |
| `backend/app/services/pipeline_orchestrator.py` | `5c3054be0d77247164e752d741110ac0f0998b3779a49c27360625730bfc1325` |
| `backend/app/services/simulation_manager.py` | `bb0a5d95cc52f5e07531993db31863e819c21e9e622846cdc59b8f16bd6cc33a` |
| `backend/app/services/agency_classification.py` | `9405c796d19d43fc0d52e0f272e5531d4d4667df9a6e6a7904fb87739242b4ba` |
| `backend/app/services/simulation_config_generator.py` | `8de3804f77f7bfd49b7d4a514e508ffaece36ecce159e349f2ba654475d1c541` |
| `backend/app/services/world_model_seed.py` | `30832cbf1f70afe49d74c225dbce3f25f0f77c531c51b0d15bd4425cff64d606` |
| `backend/scripts/replay_saved_world.py` | `d29c4b0c244fe4bc15cc87b604a49e69ce8b391a30671da2a5123e1739438947` |
| `backend/tests/test_agency_classification.py` | `a95dc5409f399580240f205b98910830a944abca390bd39337d3b388f3ea73ec` |
| `backend/tests/test_agency_preparation_consumers.py` | `4ee0d2f4d27e8695ae77730de7ae9e8451c82c62a60cd8dafb9c127cd26cc3a0` |
| `backend/tests/test_saved_world_replay.py` | `1d474ccbe029e1924ad4b5e17d3dac56b7a5b07e474b3ad2efe70d088611ade5` |
| `backend/app/services/world_model.py` | `805c5f67e26176de9ac722145aa4662627b8c9d58a8d522fa6c1a3997752067a` |
| `backend/app/services/agent_decision.py` | `17a458fa6acadd5d4646b5d256e33f51f41826f54879676412fc74ee3722a244` |
| `backend/app/services/world_update.py` | `507ba97936dc306f3f7e009235811e08c1a3969066d49fd769bb85526e2832f6` |
| `backend/scripts/main_offline_pytest.py` | `5046cf820fa468d8e8ffb2e3fdade1d20fca2f0bd56ee15eabdff51c223c02be` |

The approval is limited to these bytes and this scope. The concurrently modified temporal regression test is outside the assignment. Historical replay remains conditional (64/199 local action checks and 16 matched lapse-event checks), with zero historical raw responses replayed. The live-budget design remains a separate unimplemented proposal and paid execution remains outside this review.

**Parent continuation:** Consolidate the owner and independent receipts, preserve private evidence, and complete any separately owned affected gate. Do not promote full historical equivalence or live-provider acceptance from this review. Reopen only if reviewed source hashes change or new concrete evidence contradicts these conclusions. No reviewer-owned source work remains.

- 2026-10-28T10:48:22.356413+00:00: Final reconciliation completed after owner freeze. Both P2 findings are closed, final hashes recorded, and only this review document was written in the repository.

## Composed-gate follow-up review

The parent requested a scope/source-impact review of the four failures in the 25-module composed gate: 702 passed, four failed and zero skipped. All four remain acceptance obligations; none may be excluded to obtain a passing result. Newton owns the bounded simulation-context investigation/repair, and the parent owns the ensemble expectation correction under ADR 0003. This reviewer still owns only this document. The research-budget plan remains pending approval, with no implementation authority.

Inspected the actual failing cases in `/private/tmp/drf-target-acceptance-composed-20261028-01/junit.xml`:

1. `test_seed_report_receives_scenario_owner_and_actual_baseline_prompt` expects simulated baseline differences in report-planning prompts. ADR 0003 explicitly removes those inputs under diagnostic-only policy; owner identity and the deterministic bridge remain required.
2. `test_public_reactions_reach_next_decision_without_private_payload` expects the entire system message to equal the old role string. The privacy/public-reaction assertions pass before that obsolete placement assertion.
3. `test_canonical_pack_role_seed_reaches_only_the_correct_actor_prompt` rejects an admitted own-actor motivation in the user message. Its actor-isolation, denied-plan and legacy-field exclusion assertions pass; the repair must preserve those checks rather than broadly admitting private data.
4. `test_question_language_and_world_clock_reach_actual_decision_calls` loses the configured forecast-question sentinel. This requires tracing the current strategic system/user prompt boundary and distinguishing obsolete placement from actual loss of task context.

Acceptance requires source-backed classification of each failure, narrow owner diffs, all four failing scenarios re-executed under the unchanged guard, privacy and role/decision boundary invariants retained, and final frozen hashes. The parent owns the repeated composed gate; this reviewer will not duplicate all 25 modules.

### Interim source assessment

ADR 0003 decisions 6–7 explicitly prohibit simulated baseline differences in default report section/planning prompts. The parent changed only the ensemble regression: constructor scenario/base ownership remains asserted, the scenario label remains present, the simulation-diff sentinel must be absent, and `scenario_diff()` must not be called. This closes the failed expectation against the existing production contract without modifying report production code.

`agent_decision.py:986-1002` intentionally retains only fenced role-dossier data in the user message and builds a dedicated JSON-only strategic system message. `test_target_legacy_integrity.py:217` already verifies that platform-tool and response-method instructions cannot cross that boundary. Thus the old system-message equality and user-message motivation exclusion are not appropriate contracts; actor-scoped knowledge and denied-data exclusions remain the important assertions. The new question path must consume explicit sealed task/world metadata rather than admitting the entire legacy platform prompt or undifferentiated world brief.

Reviewer gate `/private/tmp/drf-acceptance-independent-review-20261028-r8` passed two cases in 2.10 seconds: the corrected ensemble scenario and existing strategic-prompt boundary. This does not close the three pending simulation cases or supersede the parent’s required composed gate.

Read-only byte comparison confirmed that the pre-repair `agent_decision.py`, `run_parallel_simulation.py`, `report_agent.py`, and `test_context_audit_simulation.py` all equal `e0b23377`. This establishes that the current class/replay slice did not introduce those paths; it does not waive any of the four failures. The r8 guard receipt confirms normal shutdown, identity preservation, no blocked operations and no source drift.

## Final context closure and delivery hash list

**Closed at 2026-10-28T11:11:34.484499+00:00.** The final 25-module composed gate is verified: **718 tests passed, zero failures, zero errors and zero skips**, in **95.887 seconds**. The run is `/private/tmp/drf-target-acceptance-composed-20261028-02`, against frozen source `/private/tmp/drf-target-acceptance-release-men0ydbb`. All **552** entries in `final-source-before.json` match both the current workspace and the tested frozen source. The launcher confirms all private fixtures were staged and reports no source drift.

### Context boundary and four-case closure

The final context change is limited to `agent_decision.py`, `run_parallel_simulation.py`, and `test_context_audit_simulation.py`. It adds optional task data to the user message using a string-only allowlist: question 400 characters, admitted world brief 3000, as-of date 40, and horizon 40. The coordinator selects explicit admitted config fields; `simulation_requirement` takes precedence over a different legacy seed question, invalid/missing questions fall back to the seed, and the world-brief switch remains effective. The canonical brief producer already filters source-bound public facts, so supplying this specific admitted field does not mean forwarding an arbitrary role prompt or the entire config. Scenario distributions, market maps and actor-private maps are excluded. Omitted, None and malformed contexts preserve the prior prompt bytes. No storage, decision-right, parser, provider, scheduler or world-kernel behavior was added.

AST comparison with `e0b23377` independently confirms that `build_decision_system_prompt`, `_decision_dossier` and `elicit_decision` are unchanged. Newton’s frozen three-file hashes match the current files. Its inspected owner gate records **87 passed / 0 skipped**. Reviewer gate `/private/tmp/drf-acceptance-independent-review-20261028-r9` independently passed **17 cases / 0 skipped** in 13.06 seconds, including the four original scenarios plus the new contract/privacy/bounds/fallback controls and the existing platform-instruction exclusion test. The guard directly records the test-file hash; the two imported implementation hashes were separately verified against the owner freeze.

| Initial failing scenario | Final acceptance and result |
|---|---|
| Ensemble seed report baseline prompt | Renamed `test_seed_report_retains_owner_without_simulation_in_prompt`; retains scenario/base owner binding, requires the scenario label and forbids querying or including simulated baseline differences per ADR 0003. Passed in the independent and final composed gates. |
| Public reactions and private-payload exclusion | Dedicated strategic system prompt remains; public reaction reaches the next decision, spoofed/private/share content and raw unstructured role do not. Passed in both gates. |
| Canonical pack/role/seed isolation | Own-actor inference is admitted only as labeled dossier evidence, remains absent from authoritative goals/plans and the other actor, and denied/legacy-field exclusions remain. Passed in both gates. |
| Forecast question/language/world clock | Actual configured question and admitted brief now reach the user channel, original wording wins over conflicting seed text, language and clock remain, and unrelated maps stay absent. Passed in both gates. |

All four initial failures were resolved and re-executed; none was skipped, excluded or reclassified as an acceptable failure. The private C5 three-actor proof, pre-change byte compatibility proof, and both saved replay specimen cases are explicitly present and passing in final JUnit. The previously parent-owned temporal compatibility case also passes in the composed gate; its hash below is recorded for delivery inventory, not a claim of a new production runner change.

### Final verification receipt and limits

`completed.json` confirms exit 0, completed shutdown, preserved identity and no tracked source drift. The composed run contains three expected app-storage redirects and contained import attempts: one socket construction, four process launches and twenty external reads were blocked. Discovery counters include `fc-list`, `system_profiler` and eighteen font-directory scans. These are blocked attempts, not successful provider/network calls and not a zero-attempt claim. This reviewer inspected receipts/source and wrote only this review document; private fixture bodies and production saved roots were not read during closure.

Historical replay remains conditional, with 64/199 local action checks, sixteen matched lapse-event checks and zero historical raw responses replayed. Offline gates do not establish full historical trajectory equivalence or live-provider acceptance. The research-budget design remains an unimplemented proposal pending approval; no paid execution, scheduling or promotion is authorized by this closure.

### Superseding final hashes

This table supersedes the earlier source snapshots, especially the pre-context-repair `agent_decision.py` hash. The complete 552-file source inventory remains in [final-source-before.json](final-source-before.json).

| Source | Final SHA-256 |
|---|---|
| `.env.example` | `1662c2f55f954ff26225a56fe7533762d802623c571d0681476b86cff48c673c` |
| `backend/app/config.py` | `406cf338c01c218cecf9db7dda0bfcc05201b534c18c18e995862f58fd0a2032` |
| `backend/app/api/simulation.py` | `84dd4c8f2ef598a5425d114877806eac2779818a641f68e05dc7033b5abfd26c` |
| `backend/app/services/pipeline_orchestrator.py` | `5c3054be0d77247164e752d741110ac0f0998b3779a49c27360625730bfc1325` |
| `backend/app/services/simulation_manager.py` | `bb0a5d95cc52f5e07531993db31863e819c21e9e622846cdc59b8f16bd6cc33a` |
| `backend/app/services/agency_classification.py` | `9405c796d19d43fc0d52e0f272e5531d4d4667df9a6e6a7904fb87739242b4ba` |
| `backend/app/services/simulation_config_generator.py` | `8de3804f77f7bfd49b7d4a514e508ffaece36ecce159e349f2ba654475d1c541` |
| `backend/app/services/world_model_seed.py` | `30832cbf1f70afe49d74c225dbce3f25f0f77c531c51b0d15bd4425cff64d606` |
| `backend/app/services/agent_decision.py` | `a2a02beedcda35a85b8490f3704b5ffd2a86d7a0972fa164ef4daa3c38d4c13b` |
| `backend/scripts/run_parallel_simulation.py` | `c525ac98df86daf500cc1bf0b9a348e01e3948479776c0ae574f29530007524f` |
| `backend/scripts/replay_saved_world.py` | `d29c4b0c244fe4bc15cc87b604a49e69ce8b391a30671da2a5123e1739438947` |
| `backend/tests/test_agency_classification.py` | `a95dc5409f399580240f205b98910830a944abca390bd39337d3b388f3ea73ec` |
| `backend/tests/test_agency_preparation_consumers.py` | `4ee0d2f4d27e8695ae77730de7ae9e8451c82c62a60cd8dafb9c127cd26cc3a0` |
| `backend/tests/test_saved_world_replay.py` | `1d474ccbe029e1924ad4b5e17d3dac56b7a5b07e474b3ad2efe70d088611ade5` |
| `backend/tests/test_context_audit_simulation.py` | `2dcc5bd74d8a63ca0a6bc32198a04dc5e9542c17dd0af36c5c82eba9c2063ffd` |
| `backend/tests/test_context_audit_ensemble.py` | `0c65cc2e8b433f7828e4cf78174dffcf02da86beee7def62ff4537dfd85407e1` |
| `backend/tests/test_temporal_mode_contract.py` | `1ac639c9dc3ce4c77b382b74038737ab2cd655c13aa0df6fbb2ac61f533ffc62` |
| `backend/app/services/world_model.py` | `805c5f67e26176de9ac722145aa4662627b8c9d58a8d522fa6c1a3997752067a` |
| `backend/app/services/world_update.py` | `507ba97936dc306f3f7e009235811e08c1a3969066d49fd769bb85526e2832f6` |
| `backend/scripts/main_offline_pytest.py` | `5046cf820fa468d8e8ffb2e3fdade1d20fca2f0bd56ee15eabdff51c223c02be` |

Receipt identity hashes:

| Receipt | SHA-256 |
|---|---|
| `final-source-before.json` | `9a51aadf4533c714021c12ec4e36a9b17993cfdc04a26ed2f408825c329ee4df` |
| `composed-02/completed.json` | `043586ca1a1770db9afda555ddcf28165214401ed1a0504aabbf299b892d6c7f` |
| `composed-02/junit.xml` | `339261009f1374099ac12bcf4a9601875516f2837cbf0a56830dd7f9235b7a53` |
| `composed-02/composed-launcher-receipt.json` | `b29b3bcdde8476d94ccfbd0e9b9a6e67268fb48e33d9066a741909ef67a2deec` |

**Disposition:** No remaining actionable P1/P2 in the reviewed agency, replay and context-repair scope. The final composed gate is green on the reconciled source. The parent can finish separately owned documentation/evidence delivery without further production source changes. Reopen this review only if reviewed source bytes change or new concrete failures appear.

- 2026-10-28T11:11:34.484499+00:00: Updated final context closure and superseding source hashes after independently inspecting the 718-case composed gate, all four repaired scenarios, private-fixture presence, and both copies of the 552-file source manifest. Only `review.md` was modified by this closure.
