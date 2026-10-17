# Bounded consistency store journal

**Status:** Complete — final guarded closure passed, all 41 store scenarios passed, and independent core review reported no findings. Source is frozen; worker stopped.
**Started (UTC):** 2026-10-17T12:08:46Z.
**Last updated (UTC):** 2026-10-17T12:29:16Z.
**Authority:** `contract.md` in this directory; accepted opt-in design.

## Scope and invariants

This worker owns only `backend/app/services/world_simulation/store.py`, new `backend/tests/test_world_consistency_store.py`, and this document. It will not edit shared contracts, review/controller/compiler/evaluator code, run application imports/tests/providers, delegate, or commit. Existing unrelated changes remain intact.

Only specs explicitly pinned to `actor-consistency-v1` get a private additive journal. Existing old-mode schema, receipts, budgets, semantic revisions and replay requirements remain unchanged. A pinned store with a missing or damaged journal fails closed; opening never repairs it. Both candidate and revision use the existing original-slot attempt ledger and its two-call/run-exposure limits.

## Implementation and acceptance plan

1. Add the pinned-only journal with integrity hashes binding immutable spec, slot, observation, stage, attempt, metering and stage payload.
2. Reserve candidate/revision atomically with original-slot attempt admission. A revision requires a durable successful candidate; unknown or failed stages cannot be replaced.
3. Finalize candidate usage and private draft together, or revision usage/assessment/final decision together. Verify journal integrity on state/decision reads and load; prevent ordinary APIs from bypassing pinned admission.
4. Add focused tests for atomic failure/retry, final receipt privacy, stale/fenced writes, integrity tampering, no migration for old stores, crash resume, unknown exposure, concurrent reservation, and exactly two stage purposes.
5. Perform AST-only validation and report frozen hashes for the parent's guarded run.

## Interface decisions

An invalid or unresolved payload submitted as a successful revision is rejected without a partial write. The controller must finalize that same reserved attempt as failed using the known usage and no decision/assessment. This preserves explicit success/failure semantics and the journal payload contract. Legacy `reserve_attempt`, `finish_attempt`, and `save_decision` reject in pinned mode; controller uses the new atomic APIs instead. Failure messages are private sanitized diagnostics, never model output or provider exception dumps.

The parent additionally requested `consistency_receipt(slot)`. It is implemented as a separate private read API, returning None until a verified successful revision exists. The canonical detached receipt contains `mode`, `slot`, `observationId`, `observationHash`, `candidate`, `candidateHash`, `finalDecisionId`, `finalDecisionHash`, `assessment`, `receiptHash`, and `stages`. Each stage has `attemptId`, `stage`, `status`, `usage`, and `reserved` (`tokens`, `costUsd`). This does not add candidate/assessment/audit fields to public result exports. `consistency_state()` retains exactly `candidate`, `candidateAttempt`, and `reviewAttempt`; its attempts expose `attemptId`, `status`, `stage`, and optional `errorCode`.

The existing SQLite schema version and old tables are unchanged. Only a newly initialized pinned store creates `consistency_journal`. Existing pinned stores must already have its exact column set. Read/load validation binds every attempt to its stage, observation, normalized decision, canonical metering, and predecessor, and verifies its digest. A committed decision must retain its matching successful revision proof. Budget admission and stage reservation share one `BEGIN IMMEDIATE` transaction, and purpose is persisted before dispatch.

Completion writes metering before journal payload and final slot admission within one transaction, so an injected failure at either later boundary rolls everything back. Exact completed repeats verify the active fence and all canonical payload fields but perform no INSERT/UPDATE/DELETE; an exact repeat after round commit is also read-only. New writes remain restricted to the next uncommitted round. Unknown reservations remain fully exposed; each failed/unknown stage consumes its original allowance and cannot be replaced.

Error input must have exactly string `code` and `message`; codes use a bounded lowercase identifier vocabulary. The store retains the code but replaces opaque messages with a fixed safe diagnostic. This avoids persisting provider/model exception strings. It does not alter old-mode error handling or budget output.

## Authored verification coverage

Fifteen test functions expand to 41 scenarios. They cover draft privacy; final receipt and metering closure; real round commit and read-only reopen; all three legacy API bypasses; reserved/failed/unknown candidate and revision recovery; stage sequencing and no third attempt; simulated crash/takeover; rollback after attempted usage/journal/final writes; rollback of reservation before purpose insertion; idempotent no-DML repeats and conflicts; unresolved/malformed/wrong-identity/over-reservation final payloads; nine journal/observation/usage/final receipt tampering cases; forged direct-final commit denial; stale fence/round controls; budget and purpose races on shared/separate connections; old-mode no-migration/output compatibility; and invalid review pin/attempt-limit rejection before database creation.

The crash test closes the temporary connection without orderly writer release and simulates proven process death; it does not kill or launch a host process. Tests never involve a provider or original run database. All future runtime execution belongs to the parent guard.

## Verification

No application imports, tests, providers, delegates, or commits ran in this worker. Standard-library AST parsing passed for the two owned Python files; static whitespace checks passed. Parent-owned edits to contracts/compiler/controller/evaluation and the new review module were observed and preserved.

Frozen owned Python hashes at 2026-10-17T12:13:54Z:

- `backend/app/services/world_simulation/store.py`: `e5a3b7792c1095cbfbbad5d2fd2de0a93dbfda8b7b07b30fa9377498b02890e7`.
- `backend/tests/test_world_consistency_store.py`: `3095d4c691920b26b6b0bc21b53fc0857e08429d965cd0ee5e6ab0e366833b8e`.

### First guarded core acceptance

The parent ran the frozen core gate with evidence at `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-consistency-core-first-20261017T121931Z-s69xvk8s/evidence`. This worker independently read the saved JUnit XML, verification summary, and source manifest, and hashed the two current owned Python files without importing them or executing tests.

| Suite | Passed | Failures / errors / skipped |
| --- | --- | --- |
| New consistency store | 41 | 0 / 0 / 0 |
| New consistency controller | 25 | 0 / 0 / 0 |
| Existing store | 44 | 0 / 0 / 0 |
| Existing controller | 16 | 0 / 0 / 0 |
| Historical replay and public grammar | 28 | 0 / 0 / 0 |
| **Total** | **154** | **0 / 0 / 0** |

The saved runtime is **7.338 seconds** (7.34 seconds rounded). The verification summary records `exitCode: 0`, `files: 531`, and `sourceDrift: []`. Both current owned Python hashes exactly match the frozen source manifest and the hashes recorded above. This verifies execution of the 41 journal scenarios alongside existing store/controller compatibility and historical replay checks; it is not a live-provider or semantic-truth claim.

At the first core gate, implementation and acceptance were complete while Epicurus's independent static review was still in progress. The final closure below supersedes that pending-review status. Only this scoped `store.md` acceptance record was changed after inspecting the receipts; this worker has performed no own runs or commits.

### Final closure and stop

The final parent receipt is `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-consistency-review-closure-20261017T122724Z-8xzy9o2w/evidence`. This worker independently read the saved JUnit XML, verification summary, and source manifest:

- **345 passed**, **0 failures**, **0 errors**, **0 skipped**, in **7.647 seconds** (7.65 seconds rounded).
- All **41 consistency-store cases passed** with zero failures/errors/skips.
- `exitCode: 0`, **532 frozen files**, and `sourceDrift: []`.
- Frozen store SHA-256 remains `e5a3b7792c1095cbfbbad5d2fd2de0a93dbfda8b7b07b30fa9377498b02890e7`; the test hash remains `3095d4c691920b26b6b0bc21b53fc0857e08429d965cd0ee5e6ab0e366833b8e`, matching the earlier core gate and the recorded source freeze.

The parent separately reports **853 broader tests passed in 165.81 seconds**, with this same store hash, and **independent core review completed with no findings**. Those two outcomes are parent-reported; this worker directly inspected the supplied final-closure receipt rather than running or independently locating the broader suite/reviewer artifacts.

The bounded STORE slice is complete. Source remains frozen for the parent-directed 12-call replay with a maximum of USD 1.25 from the original budget. This is a parent-run follow-up, not authorization for this worker to dispatch calls. This final update changes only the scoped note; the worker now stops without source changes, runtime/test/provider actions, or commits. Offline closure establishes the tested persistence/recovery behavior, not empirical truth of model assessments or results of the pending directed replay.

## Updates

- 2026-10-17T12:08:46Z: Read the frozen API and current store; established three-path ownership and the controller finalization integration rule before implementation.
- 2026-10-17T12:13:54Z: Implemented pinned-only journal, atomic stage/usage/admission, verified private state and final audit receipt, strict bypass rejection, and old-mode compatibility. Authored 41 cases, completed AST-only checks, and froze owned Python hashes for parent guarded execution.
- 2026-10-17T12:20:23Z: Independently verified saved guarded core results (154 passed, including all 41 consistency-store cases, zero failures/errors/skips, 7.338 seconds), 531-file no-drift receipt, and current-to-frozen owned Python hashes. Updated only this acceptance record; source freeze continues and independent static review remains pending.
- 2026-10-17T12:29:16Z: Finalized the note after verifying 345-test closure, all 41 store cases, zero failures/errors/skips, 532-file no-drift receipt, and unchanged frozen hashes. Recorded parent-reported 853-test broad acceptance and no-finding independent core review. Marked the slice complete and stopped under source freeze for the parent-directed bounded replay.
