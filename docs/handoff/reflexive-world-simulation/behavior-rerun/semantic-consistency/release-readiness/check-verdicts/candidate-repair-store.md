# Candidate-output repair: bounded store slice

**Status:** Bounded store integration accepted — all 68 store cases passed in the 668-test parent gate. Source/test freeze continues; broader and frontend gates remain parent-owned.
**Started (UTC):** 2026-10-17T15:58:50Z.
**Last updated (UTC):** 2026-10-17T16:07:33Z.
**Authority:** `candidate-repair-contract.md` in this directory.

## Scope and preservation

Only `backend/app/services/world_simulation/store.py`, new `backend/tests/test_world_candidate_repair_store.py`, and this document are owned. No application imports, tests, providers, commits, or delegation are permitted. The user's total budget is parent-managed and does not authorize this worker to run calls.

The starting working store already contains parent-owned v3 aggregate derivation and private withheld-revision retention. Its SHA-256 is `6594bd30fb06bfb23af42b7e6cfd70860c5786f22794104fab85dbf052a4b68b`. The parent methods are preserved, with original source-segment hashes:

- `_validated_withheld_consistency`: `aae0f9a94214253914668b01698990c6ed5beab4725e64ddfc1e72cfafaa5104`.
- `withheld_consistency_receipt`: `9c276c94a4e996da5ac70536e6bf2c0b83bd1865ba8c32e7f2a9bf598c31ec97`.

## Plan and acceptance

1. Gate repair on the exact new v3 pin, a known-metered failed candidate, an explicit trusted `repair_eligible=True`, a permitted error code, and no candidate/assessment payload.
2. Persist the eligibility marker only in the hashed safe-error receipt. Derive review context from verified original observation and failed attempt; never persist or forward raw failed output.
3. Bind the one remaining revision to the first failed attempt ID and exact review-input hash. Retain the original two-slot-attempt budget and all unknown/failed exposure behavior.
4. Add read/reopen, corruption, stale/fence, atomicity, old-pin-absent, valid-candidate, and parent-withheld compatibility tests.
5. Perform AST/static checks only, verify parent-method preservation, and freeze hashes for the parent guard.

## Interface decisions

Revision budget metadata uses `reviewInputKind` with `candidate` or `candidate_error`, only when the new pin is present. Successful repair receipts expose `reviewInput`, `reviewInputHash`, and `reviewInputKind`; their `candidate` and `candidateHash` are None because the first request did not produce a usable candidate. Valid-candidate receipts retain those candidate fields. Old modes and pin-absent receipts retain their original shape. Parent-owned withheld retention and accessor remain intact.

`finish_consistency_attempt(..., repair_eligible=False)` preserves all prior call sites; the controller should pass the new keyword only when true. Incoming error JSON still accepts exactly `code` and `message`, so a caller cannot smuggle the eligibility marker through an error object. The explicit flag validates pin, stage, failed status, known usage, allowed code, and absent payloads before adding `candidateRepairEligible: true` to the sanitized hashed receipt. An old completed unmarked failure cannot be upgraded afterward, and a marked failure cannot be silently unmarked by a conflicting repeat.

`consistency_review_input(slot)` returns a detached successful normalized candidate or the shared helper's exact server-derived error context. `consistency_state(slot).candidate` remains None for a failed candidate. Revision reservation still uses ordinal two in the original slot and binds the first attempt ID plus the digest of that exact review input. Reading state, receipts, budgets, or reopening verifies both the eligibility marker and the predecessor/context relation. Unknown, failed, reserved, or succeeded second attempts cannot reopen allowance. An exact repeated completion performs no writes.

The parent-owned `_validated_withheld_consistency` and `withheld_consistency_receipt` source segments remain byte-identical to their recorded starting hashes. Parent v3 derived-status checks and private evidence retention are retained. The existing withheld accessor continues to expose its original fields; its legacy `candidateHash` names the stored bound review-input digest, including the error context when the first attempt was an eligible failure. Such evidence remains withheld, never admitted, publicly exported, or scored as a success.

## Authored store tests

Sixteen test functions expand to 68 cases. They cover:

- Complete eligible-failure → reviewed-final → real commit → read-only reopen with preserved failure metering and private safe context.
- All 13 allowed codes, eight forbidden origin/integrity/transport codes, strict known-failed candidate-only eligibility, spoofed marker input, nonboolean flags, and payload/usage rejection.
- Exact idempotent marked/unmarked repeats, no retroactive promotion of a completed failure, pin-absent v1/v2/v3 behavior and exact legacy receipt/budget shape, and the valid-candidate path under the new pin.
- Invalid pin/mode rejection before database creation; simulated crash/reopen after a marked failure; unknown candidate denial; every second-attempt status preventing a third request.
- Corrupt markers, context hashes, original observation, usage and predecessor IDs, including semantic rejection after recomputing content hashes; forged marker on a pin-absent generation.
- Atomic known-usage/marker rollback, stale fences and rounds, concurrent second-ordinal reservation, and run-wide exposure bounds.
- Six parent-withheld compatibility cases covering unknown/inconsistent assessments after an old valid candidate, new-pin valid candidate, or repaired failed candidate. All remain private, unadmitted, durable, and exhausted.

## Verification and updates

No application imports, tests, providers, commits, or delegation ran in this worker. Both owned Python files passed standard-library AST parsing. Static whitespace checks passed. The two parent-owned withheld-method source hashes matched their starting values after implementation. Shared review helpers are consumed by their specified interfaces; the parent confirmed its actor/observation label fix and owns integration verification.

Frozen Python checkpoint:

- `backend/app/services/world_simulation/store.py`: `22ab45b88e02a9bce663da134b73cfa5557661eed47bbf3284dd168d7ed27e6e`.
- `backend/tests/test_world_candidate_repair_store.py`: `b0917f3534b5f56711d40b6b567ebdacf0a72cc995c7d2654686f44847b66854`.

### Parent combined integration acceptance

The parent completed the frozen guarded integration gate with evidence at `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-candidate-repair-integration-first-20261017T160659Z-6nouqkvj/evidence`. This worker independently inspected the saved JUnit XML, verification summary, source manifest, and the relevant frozen parent test source, without running application code or tests.

- Full gate: **668 passed**, **0 failures**, **0 errors**, **0 skipped**. JUnit records **8.233 seconds**; the parent reported 8.24 seconds.
- Owned candidate-repair store suite: **68 passed**, with zero failures/errors/skips.
- Parent candidate-repair controller suite: **21 passed**, with zero failures/errors/skips.
- Verification summary: `exitCode: 0`, **545 frozen files**, `sourceDrift: []`.
- Current store and owned test hashes exactly match the frozen manifest and the checkpoint hashes above.

The prior coverage handoff distinguished the six positive withheld-compatibility cases in this worker's suite from additional parent-owned negative cases. The parent gate now includes five passing `test_withheld_review_tampering_rejects_even_with_recomputed_receipt` cases: missing decision, missing assessment, derived-clear assessment, changed error code, and unknown charge. The inspected frozen source mutates the retained private record, recomputes its hash, and requires read-only reopen to reject it. Those are parent test additions, not newly claimed coverage inside this worker's 68 cases.

The bounded store slice is accepted for this integration gate. The broader all-world/affected-legacy gate and frontend/browser checks are next under parent ownership. This does not establish live-provider behavior, full behavioral success, assessment truth, or readiness for default promotion. No paid calls were made. After acceptance, only this scoped note was updated; source and tests remain frozen and this worker stops without runtime/provider/commit work.

- 2026-10-17T15:58:50Z: Read the exact contract and parent-modified store, recorded preservation hashes, and stated the receipt/budget interface before implementation.
- 2026-10-17T16:03:32Z: Implemented explicit-pin repair eligibility, bound review input, revision linkage and audit labels; authored 68 scenarios; verified AST/static checks and unchanged parent withheld methods. Confirmed exact `reviewInputKind` naming and optional-keyword compatibility, and froze the owned Python checkpoint for parent execution.
- 2026-10-17T16:07:33Z: Independently verified saved integration results (668 total, 68 owned store cases, 21 parent controller cases, zero failures/errors/skips), 545-file no-drift receipt, and matching current/frozen hashes. Recorded five passing parent-owned rehashed withheld-record negative cases. Updated only this note and retained the source/test freeze pending broader parent gates.
