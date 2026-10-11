# CR-1 canonical shared-world denial fix

Status: Complete for CR-1 on 2026-10-12. Final acceptance: 35 passed with independent review closure; no new plan approval required.

## Request, ownership and acceptance
Honor explicit `actor_knows=false` at top level or in qualifiers when compiling common canonical world context. A denied claim must not reappear through another admitted actor pack's matching claim identity or full normalized text. Allowed public evidence remains available. All candidate packs must retain real identity, intelligence and dossier-source binding checks.

Only `_canonical_public_world_rows` and a narrowly required same-canonical helper in `simulation_config_generator.py`, new `backend/tests/test_canonical_world_brief_denials.py`, and this note are writable. No actor_context/orchestrator/runner/provider/saved-run/Git edits or operations. The coordinator owns CR-2/CR-3 and may change unrelated generator regions.

## Plan and checks
1. Reuse the established actor-context fixture and real on-disk pack producer/validator; also exercise the existing real bridge-finalizer fixture. Capture behavioral red before runtime code edits.
2. Validate admitted packs first, collect explicit denials globally, then filter public rows by stable identity and full NFKC/casefold/whitespace-normalized text before display truncation. Cover identity/text alias chains without widening public admission.
3. Run the frozen offline runner, inspect receipts and source hashes, and request independent review of only the owned code/tests.

## Initial source state
- Frozen runner: `53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa`.
- Generator: `24af7cb84c403c18444ea4b0564327b2377f247db091a03fb7a77dac7c6e1ad2`.
- Actor context: `17f12e5ba2b8f02309ab3ba65a08ee14afe93383217e5707ccf941efea1a0dbf`.

## Progress, decisions and evidence
The current selector validates pack identity/intelligence/dossier hashes but admits public rows without consulting explicit false flags. The existing actor-context producer preserves both raw intelligence and the denied epistemic partition, so this consumer must apply the denial before sharing.

## Remaining work
Capture red, implement, verify, obtain independent review, and return exact proof. Other caller findings remain coordinator-owned.

## Updates
- 2026-10-12: Created this scoped continuity record before tests or implementation.

### Initial red fixture correction
The first red attempt (`/private/tmp/drf-main-caller-authority-red-20261012-01`) had 19 behavioral failures, seven positive/control passes, and one producer-fixture failure. That final case modified only the raw actors Plan B, so the real finalizer correctly refused disagreement with the Plan A dossier ledger. The fixture now injects access flags into their shared raw-claim builder so both real producer paths agree. No production code has changed yet. The first receipt has no blocked attempts or source drift; it is retained and is not counted as full producer-path red acceptance.

### Behavioral red and implementation
Corrected red command: `backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-main-caller-authority-red-20261012-02 -q backend/tests/test_canonical_world_brief_denials.py`.

Result: 20 behavioral failures, seven positive/validation-control passes, zero errors/skips, 1.697 seconds. The real bridge finalizer and parent admission now succeed; its produced and disk-validated packs emit four public rows instead of only the two allowed current-action rows, proving denied knowledge reaches the shared consumer. No blocked operations, source drift or child processes; identity preserved and complete shutdown.

The implementation changes only `_canonical_public_world_rows`. It validates and collects admitted packs, indexes each complete claim ID and normalized text, accumulates literal false denials independent of visibility, closes connected identity/text aliases, then applies the existing public/source/evidence filters after excluding denied claims. Missing packs do not contribute denials; malformed supplied packs still fail validation. Full-text matching precedes the existing 520-character display sanitization.

### First green
`/private/tmp/drf-main-caller-authority-green-20261012-01`: all 27 tests passed in 1.65s, zero failures/errors/skips. Completion receipt records no blocked operations, source drift or children, preserved identity and complete shutdown. The real bridge producer -> parent reception -> context artifact write/read/hash validation -> shared brief path passes alongside identity/text alias, ordering, exact-boolean and tamper controls. Independent reviewer `01a12c41-b14e-7760-b421-3d84ca89d5b8` is reviewing the owned selector and tests.

The next receipt also binds the orchestrator and shared actor utilities used by the real producer fixture, and extends checks to selected pre-existing context/source-binding and canonical-official-data routing regressions. No unrelated application paths or vendor runtime will be executed.

### Expanded acceptance and source proof
Command:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-main-caller-authority-green-20261012-02 -q backend/tests/test_canonical_world_brief_denials.py backend/tests/test_actor_context_runtime.py::test_pack_relevance_is_actor_specific_bounded_and_audited backend/tests/test_actor_context_runtime.py::test_epistemic_access_never_turns_inference_into_actor_knowledge backend/tests/test_actor_context_runtime.py::test_context_manifest_detects_pack_tampering_and_missing_selected_pack backend/tests/test_actor_context_runtime.py::test_current_v1_batch_requires_sealed_context_before_profile_work backend/tests/test_actor_context_runtime.py::test_current_v1_batch_rejects_context_object_changed_after_sealing backend/tests/test_official_data_downstream.py::test_public_snapshot_does_not_bypass_canonical_actor_authority backend/tests/test_actor_roster_producer_consumer.py::test_real_producer_roster_passes_parent_and_context
```

Result: 35 passed in 1.92s, zero failures/errors/skips. Receipt: `/private/tmp/drf-main-caller-authority-green-20261012-02/completed.json`; JUnit: `/private/tmp/drf-main-caller-authority-green-20261012-02/junit.xml`. No blocked events, source drift or child processes; identity preserved and shutdown complete. All bound sources were rehashed after the run and still matched. The runner is a CPython audit boundary, not an OS sandbox; this is offline fixture proof, not live-provider or OASIS process execution.

| Requirement | Exercised evidence |
| --- | --- |
| Top-level and qualifier false override public/true | Both locations tested with opposite true at the other location |
| Global denial independent of actor order | Matching identity, exact text, normalized text and chained identity/text aliases, both actor orders |
| No truncation-based conflation | Distinct complete claims sharing a 520-character prefix retain the allowed claim |
| Existing public admission remains intact | Allowed public positive control; None/true/string false/numeric zero are not JSON-false denials |
| Real source/pack authority | Actual context files produced, hashed, reloaded and validated for every case; altered intelligence/dossier binding refuses; missing unadmitted pack cannot veto |
| Real upstream producer integration | Existing bridge finalizer and parent admission fixtures feed denied/allowed claims through actual disk-validated context packs and both shared brief/config context |
| Existing canonical boundaries | Selected existing context/provenance and raw-official-data exclusion regressions pass |

Bound SHA-256 values:

- Generator: `7fb09a8d5ccb67c00ba9728b1b48054a074a1e3d660e90e3de9b9ededd98c806`.
- Owned method only: `d0c94ae10bba1ab53ad279cc47e41e1f3f86464cc4b8892d6ca008eeefee8532` (UTF-8 exact source from `def _canonical_public_world_rows` through its last statement, including the final newline; decorator excluded).
- New tests: `8338af95fed10370038f4d357c43b722eb77b70a2ae8d2f5e9266653e9757f0c`.
- Actor context: `17f12e5ba2b8f02309ab3ba65a08ee14afe93383217e5707ccf941efea1a0dbf`.
- Frozen runner: `53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa`.

The receipt also binds the unchanged existing fixtures, actor role/utility helpers, bridge producer and orchestrator used by the real producer case. The method digest permits coordinator changes elsewhere in the generator to be distinguished from a change to this reviewed slice.

### Independent review correction
Reviewer `01a12c41-b14e-7760-b421-3d84ca89d5b8` found no runtime correctness or authority regression in the method, but requested explicit absence assertions for every denied original/alias in both rendered outputs. The 16 cross-pack cases already asserted exact selector rows and allowed rendered content; they now also assert every original/alias is absent after full Unicode/case/whitespace normalization from both the actual shared brief and configuration context. This is a test-strengthening change; production code is unchanged. A fresh run and rereview follow.

### Final corrected acceptance
The same expanded command above, with fresh evidence directory `/private/tmp/drf-main-caller-authority-green-20261012-03`, passed all 35 cases (27 new and eight pre-existing parameterized controls) in 1.938 seconds. JUnit reports zero failures/errors/skips. The completion receipt records exit 0, no blocked events, no source drift or children, identity preserved and complete shutdown. A closing read of every bound source matched its receipt hash.

The final new-test SHA-256 is `93ae6e801c896db4a4b8d70f2d96fd217623338310c405ac7cf6b9231475f755`. Generator, method, actor-context and frozen-runner hashes above are unchanged. Historical Green02 remains valid for its older test assertions; Green03 is the final acceptance evidence.

### Final review disposition and continuity
Independent rereview closed the P2 test-coverage finding and found no outstanding actionable defects inside CR-1. The reviewer independently read final JUnit (35 passes, 1.938 seconds), completion receipt and generator/test hashes. Reviewer method digest including the `@classmethod` decorator and trailing newline is `797368b12210db5fba6560a986361aae1da4a5a540cc48f7d84dbf09277cf144`; the earlier method-only digest deliberately excludes the decorator. JUnit SHA-256: `efc748bcc3ed4222fa11a6997127590532093442a741f2ccdccb77155ce8d2a7`. Completion receipt SHA-256: `27ca54325eeafd339ec18041d46cedc26834b91038c1d650a0f4dfbc008390ad`.

No CR-1 implementation work remains. Only the owned method, new tests and this note were edited. No actor_context, orchestrator, existing tests, runner or other generator methods were edited by this worker. No providers, saved runs, vendor runtime or Git operations were used. CR-2/CR-3 generation binding remains the coordinator's responsibility; this fix grants no new actor knowledge from raw official datasets.

Next-session prompt: "Read caller-authority-fix.md and Green03 evidence. CR-1 is accepted for the recorded method/test hashes. Preserve the global explicit-denial filter when integrating coordinator changes elsewhere in simulation_config_generator. Complete CR-2/CR-3 separately and rerun relevant caller/authority acceptance against any changed bytes."

- 2026-10-12: Marked CR-1 complete after corrected rendered-output assertions, 35 passing guarded cases, closing source rehash and independent rereview.
