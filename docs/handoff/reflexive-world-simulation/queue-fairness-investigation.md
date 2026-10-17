# RW17 queue fairness investigation

**Status:** Exact approved four-module patch applied after phase5; permanent tests added. Stable for coordinator freeze; validation gates remain pending.
**Date:** 2026-10-17 (Asia/Singapore).
**Worktree:** `/Users/rogerlin/.codex/worktrees/reflexive-world-simulation/DeepResearchForecast`, branch `codex/reflexive-world-simulation`.

## Result and scope

The reported starvation is real. With two pending offers, `maxInboxItems=1`, and valid empty response decisions, the same offer is presented repeatedly because both `lastResponseRound` values remain zero. A second real-controller scenario confirms that the shared scalar also couples recipients: one recipient's explicit deferrals can continually demote a shared offer for another recipient who has never been shown it.

The [approved patch](queue-fairness-proposal.patch) is a 104-line unified diff against four frozen modules: `contracts.py`, `observations.py`, `kernel.py`, and `service.py`. It was first verified only in a temporary copy, then applied byte-exactly to the live worktree after the user confirmed phase5 completion and Epicurus approval. The original [test draft](queue-fairness-test-draft.py) remains unchanged as review evidence. The permanent `backend/tests/test_world_queue_fairness.py` retains its 16 self-contained cases; the separate historical 36-case benchmark is preserved as receipt evidence below. The guard, existing tests and unrelated runtime files were not edited. No providers, network calls, commits, or other agents were used.

## Meaningful red evidence

Evidence root: `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-queue-fairness-8r08y17a`.

| Scenario | Actual real-controller result | Verdict and receipts |
| --- | --- | --- |
| Buyer proposes two purchase offers in round 1; producer submits `intents=[]` in each required response slot; cap is one. | Rounds 1 and 2 both show `2d5f49845c21568595cdb521b3091f9d`; the other pending offer is `7b43b1a6caf55ffe882ea719655cc126`. Both cursors remain zero; both persisted response decisions are valid empty lists. | Behavioral red: 1 failure, 0 collection/setup errors. `red-evidence/junit.xml`, `red-evidence/completed.json`, `red-console.log`; exact trace at `red-evidence/pytest-tmp/test_two_offers_empty_required0/fairness-red-trace.json`. |
| One shared offer addresses producer and financier; another addresses only financier. Producer explicitly defers the shared offer, while financier submits empty response intents. | Financier sees `173e95ab9d005a55aa1cdc453e8cb799` in all three rounds. Exclusive offer cursor stays 0; shared offer cursor reaches 3 even though financier has not seen it. | Behavioral red: 1 failure, 0 collection/setup errors. `multi-red-evidence/junit.xml`, `multi-red-evidence/completed.json`, `multi-red-console.log`. |

Both run the unchanged `run_round`, real Store, real observation projection and real reducer. Only actor policy responses are offline scripted fixtures. The first red spec has no new policy pin; the second also uses the legacy unpinned spec. They are not import failures, synthetic-only helper assertions, or failed required policy calls.

## Narrow compatibility design

1. **Optional sealed policy pin:** accept only `interactionQueuePolicy='presented-v1'` when the field is explicitly present. `validate_spec` never inserts a default. Missing means the old scalar ordering and old replay semantics, including the known fairness limitation. Explicit null, false, unknown versions and malformed values reject.
2. **Enable on fresh preparation only:** `WorldSimulationService.prepare_model` adds the pin after compilation and before sealing a genuinely new generation. Loading existing prepared files performs no migration. Forks retain the parent's pin or its absence because the existing fork clones the parent specification and does not call fresh preparation.
3. **Recipient-specific presentation accounting:** proposed reducer-owned root state is `interactionQueueState[actorId][interactionId] = round`. The reducer deterministically reconstructs the same staged response inbox used by the controller. Only persisted normalized response decisions count as presentation opportunities; an empty response still counts. Proposal inbox displays do not consume a second service turn.
4. **Overflow-only mutation:** cursor entries are written only if that recipient's eligible pending queue is larger than `maxInboxItems`, and only for offers actually included in that response inbox. A failed required response never reaches commit and adds no cursor. Actors with no overflow receive no queue state. Expired, undelivered and otherwise ineligible offers do not qualify.
5. **Private cursor placement:** the cursor sits outside interactions and outside actor states. Existing closed projections already omit this root state from every actor prompt and public/actor API view. The tests verify actual `build_observation` and `read_result` outputs, including a hidden cursor sentinel. No new private scheduling map is copied into an interaction envelope.
6. **Legacy field compatibility:** `lastResponseRound` remains the existing response metadata. It continues to order legacy queues and is ignored by the `presented-v1` scheduler. Removing that existing field from old prompts/API payloads would conflict with the requested exact old-spec compatibility and is deliberately not bundled into this proposal.

**Naming/placement choice for review:** `interactionQueueState` is the proposed private root cursor container, not an additional policy variant. The exact `presented-v1` value comes from the requested design. Any wider removal of legacy response fields, migration of old generations, alternate policy name, or new configuration surface requires confirmation before widening; none is implemented here.

## Temporary green verification

Final candidate receipts: `candidate-semantic-evidence/junit.xml`, `candidate-semantic-evidence/completed.json`, and `candidate-semantic-console.log` under the evidence root.

**33 tests passed:** 17 proposal cases plus the 16 unchanged existing controller cases. The proposal cases cover empty-response rotation, recipient independence, no-overflow prompt equality, unchanged unpinned replay, reopen/resume, failed-slot non-commit, delivery/expiry exclusion, private cursor omission from real views, invalid version refusal, fresh preparation, old/new fork inheritance, and the 36-case exact compatibility comparison.

The compatibility test executes all **36 existing M5 specifications** through offline scripted policies. Their specifications stay unpinned and byte-identical. For each case, baseline and candidate match hashes of:

- Full actor observation payloads, including observation IDs, sorted only by stable round/phase/actor keys.
- Initial and committed history, complete committed rounds/decisions, final state and semantic revisions.
- Events, resolutions, and budget ledgers including slots, attempt ordinals, statuses, reservations, usage and aggregate exposure.

Only random `attemptId` values are excluded from budget-ledger comparison. They are execution UUIDs, not semantic replay data. No field in observations, world histories, decisions or semantic revisions is normalized away.

The baseline reference is `baseline-semantic-evidence/pytest-tmp/queue-baseline-reference.json`; the matching candidate receipt is `candidate-semantic-evidence/pytest-tmp/queue-candidate-benchmark.json`. Their `cases` mappings are exactly equal. The reference file SHA-256 is `1cb6b06a035976fb15af6803e0f9930d1de3d8a28633a5bdfd26269ab9614c98`.

Single-run timings for the 36 unpinned cases were **6.085 seconds baseline** and **6.498 seconds candidate**. These are contemporaneous wall-clock samples, not an isolated performance claim. The legacy path takes an immediate no-op return from the new presentation helper; the comparison proves unchanged inputs/results, not statistically equivalent latency. The whole final 33-test run took 10.15 seconds.

## Guard and freeze evidence

The source copy follows the existing bounded snapshot wrapper's allowlisted source roots and suffixes. Saved data, credentials, logs, caches, symlinks and oversized files were excluded. Application imports and tests ran only through the copied, unchanged `backend/scripts/main_offline_pytest.py` with the existing interpreter:

```text
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir <new canonical evidence directory> -q <selected temporary test files>
```

Final candidate selection was `backend/tests/test_queue_fairness_proposal.py backend/tests/test_world_controller.py`. The baseline benchmark selected `backend/tests/test_queue_baseline_benchmark.py`. Test draft execution requires the baseline reference beside the temporary test file; its receipt and the baseline capture source remain in the evidence root.

All four meaningful receipts (two reds, corrected baseline, final candidate) have `source_drift: []`, preserved identity variables, and only these three guard events: one redirect each for `app.config`, `app.utils.logger`, and `app.services.simulation_manager`. They recorded no network/process/file-denial attempts. This is the existing trusted-CPython boundary, not a new sandbox or provider evaluation.

The guard SHA-256 is identical in original, baseline and candidate:

```text
b2bd4469cdeb5f94097aafc5b81b0bf634fefd2fe1810dd3b3d0c0d42ff0a15b
```

**During the frozen sidecar, all 514 captured original production/script/existing-test files rehashed unchanged.** The later authorized integration changes only the four listed production modules. `original-source-manifest.json` and `final-source-verification.json` preserve the sidecar's exact names and hashes. Manifest SHA-256: `1eb02daf74a598db9d1085c0e3df21869bece79287d1d34b67af3ff50add7aca`.

| Module | Original frozen SHA-256 | Approved candidate and integrated SHA-256 |
| --- | --- | --- |
| contracts.py | `aca700b29cb866d34bd47171fa0ac9ae5f8e42f4c38cc34680026d2a22ebc678` | `781ecb0fb4f8a30f8f4bbe0fa72069cf31c56d464d30bd1d1660cedd87b61857` |
| observations.py | `86ffd8ec7a15400f2ee90fbcc13c5d59b3628c98c5a34f52c61cafd53509a7f2` | `80e87afcbfbf6d2a39c859e0061238e318df2bcb3e45b7ae9f3c4847b7381e39` |
| kernel.py | `25844f944213eb59c1f02431b87b921429c7063a0432bcec69169df65165f6c9` | `15eacdbdc81bdee09ac0a1a18e6289f8f3f03d7a2a4756d55b1cd9ee7946de74` |
| service.py | `efaecc4090717edccd0dded7a59a2e96746b6d738ee470853c50a6acc7732d70` | `df105588782b46609e5b344d414085382a233d6ef161f366fdb126a564c1abe5` |

Patch SHA-256: `c48dbb6cb14719b3bc3e3546045865a5a2ed646e7865601e3be4422e593ae614`.
Test draft SHA-256: `98d38887f6aaf215af7614b6b62fc327da12cfd39e911701e55c5d30d0090e3e`.
The exported patch was reconstructed from baseline/candidate files and checked identical to the tested delta. It contains no guarded-runner or existing-test changes.

## Errors preserved and interpretation limits

The first candidate run (`candidate-evidence`) had **32 passes and one failed compatibility assertion** because the initial benchmark hashed random attempt IDs. Source inspection identified `uuid4().hex` execution identities as the mismatch. The comparison was corrected in temporary/new test code only, preserving all substantive budget fields. The original failed console/JUnit/completion receipt and initial benchmark remain untouched. Production candidate bytes did not change during this test correction.

The starvation reds remain real legacy behavior and are not turned into legacy replay changes. The proposed pin deliberately fixes only new prepared generations. The 36-case comparison uses deterministic offline policies; it neither repeats nor alters the live phase5 batch and makes no claim about live-model responsiveness. Review was performed locally by source/diff inspection; no other agents were dispatched, as requested.

## Parent integration boundary

Phase5 is complete and the user authorized the exact approved patch. The four integrated module hashes match the approved candidate column above. No production adaptation, default migration, fixture change, or unrelated fix was added. The coordinator owns the concurrent simulation-list status regression/fix and the combined source freeze and gates.

Permanent tests are in `backend/tests/test_world_queue_fairness.py`, SHA-256 `798cbdd8567430985190576c244044dae18320e2f859daa913df307b762d38e9`. They retain the reviewed waiting-response fairness, per-recipient independence, overflow-only state, prompt/view privacy, legacy replay, reopen, failed-slot, expiry/delivery, version rejection, fresh-preparation and fork scenarios. Only the historical benchmark, its file-reading/timing helpers and unused imports were removed from the draft when promoting it. There is no temporary absolute path or golden-file runtime dependency.

The exact 36-case comparison remains the saved sidecar evidence described above, including its baseline/candidate receipt paths, reference hash and comparison semantics. No new checked-in canonical fixture is needed for the permanent behavioral scenarios. The original draft and patch remain unchanged for review traceability.

No test, compilation, lint or smoke gate was run during this integration step, as requested. The earlier 33-pass temporary-source receipt is preserved as prior evidence, not relabeled as a new combined gate. Freeze and validate after the coordinator's list-status work is stable. Existing prepared generations/forks must retain their original policy choice; do not silently re-seal or migrate them.

## Updates

- 2026-10-17: Created the scoped record and froze 514 source/script/existing-test files. Guard unchanged.
- 2026-10-17: Confirmed the empty-response red through the real controller; both required slots committed valid empty intents while the second offer remained unseen.
- 2026-10-17: Confirmed the multi-recipient global-cursor red. Built the optional `presented-v1` proposal only in the temporary candidate.
- 2026-10-17: Preserved the first candidate's random-attempt-ID benchmark failure, corrected only the comparison, and obtained 33 passing tests plus exact 36-case semantic/observation compatibility.
- 2026-10-17: Exported the patch and test draft, recorded hashes and receipts, and reverified zero drift across all 514 original captured files. No runtime integration, live calls, agents or commits occurred.
- 2026-10-17: User confirmed phase5 is complete, no paid process is active, and Epicurus approved the exact proposal/test hashes and four candidate modules. Authorized applying only that four-module patch, adding a permanent queue-fairness test module without a temporary reference dependency, and updating this note. The coordinator owns the concurrent simulation-list status fix and the next freeze/gates. No tests, providers or commits are authorized in this integration step.
- 2026-10-17: Applied the approved patch after checking all four base hashes and the exact patch hash. All four resulting hashes equal the approved candidate hashes. Added the permanent 16-case test module without the temporary benchmark dependency, preserving the baseline36 comparison as historical receipt evidence. No gates, providers, agents, staging or commits were performed. Source is stable for the coordinator's combined freeze.

- 2026-10-16T18:21:03.693918+00:00: Coordinator integrated exact approved sources after live completion. Permanent16cases passed within final-combined691/97.24s, no drift515. All36historical unpinned semantic comparisons remain saved evidence. Epicurus independently verified candidate hashes and permanent-test promotion; no migration of old specs occurred.
