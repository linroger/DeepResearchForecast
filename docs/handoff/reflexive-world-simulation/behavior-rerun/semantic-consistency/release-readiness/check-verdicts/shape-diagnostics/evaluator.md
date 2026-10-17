# Controlled revision-shape diagnostics: evaluator slice

**Status:** First guarded GREEN passed, including all 11 evaluator cases; exact-source independent review closure remains pending. Source/tests frozen; notes-only updates.
**Started (UTC):** 2026-10-17T16:30:50Z.
**Last updated (UTC):** 2026-10-17T16:39:10Z.
**Authority:** Approved release in `contract.md` and bounded `PLANS.md` in this directory.

## Scope and staged implementation

Own only `backend/app/services/world_simulation/consistency_evaluation.py`, new `backend/tests/test_world_review_shape_evaluation.py`, and this document. Preserve all parent uncommitted work. Do not edit store/review/policy/controller or other files. No application imports, runtime/tests/providers, commits, or delegation are permitted. Phase 16 is closed; budget and any later calls remain parent-owned. Production edits require a parent-returned meaningful red receipt.

The initial regression uses the actual OpenAI SDK with `httpx.MockTransport`, existing `StrictHTTPPolicy`, captured directed inputs, and real `run_evaluation`. The first v3 assessment check has an unsupported known schema field. Assertions first establish a failed `invalid_assessment` row, trustworthy known usage, the fixed safe validator message, twelve total requests without retry, and no admission/score/withheld payload. The intended RED is then the missing `reviewShape` field, rather than a missing helper or import.

After red confirmation, implement the optional private wrapper bound to code/usage, manifest/case, original observation/candidate, revision purpose, validated shape, and wrapper hash. Validate the optional field during journal recovery without requiring it on old rows. Diagnostic getter/build failures must preserve the original error, known charge, and existing safe message. No diagnostic may affect prompts, requests, acceptance, retries, scores, or prices.

## Verification

This worker has not executed the regression or imported application code. AST parsing of the authored test passed. Final scope is approximately ten bounded SDK/journal cases, including mismatched modes/metering/bindings, tampering, reopen, optional failure, and old-row compatibility.

Frozen RED checkpoint:

- Test selector: `backend/tests/test_world_review_shape_evaluation.py::test_real_sdk_known_invalid_v3_check_records_private_bound_shape`.
- Test SHA-256: `11b3e0c055f7d46fa33eb2cc5541e431441cb621c5bf05799def0240fbfd3650`.
- Unchanged production evaluator SHA-256: `00f9fff941ce561a534e66fdc77ee5663ef54f5973c56aeb84005c58c1c7a1fd`.

The parent should run that selector under the guard and return the failure receipt. Production implementation remains gated on confirmation that the failure is the missing private shape wrapper after the known-charged SDK validator error. The two Python files remain stable while awaiting that gate.

## Confirmed RED and implementation release

The parent returned `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-v3-shape-diagnostics-red-20261017T163228Z-rhtdpzxb/evidence` and explicitly released evaluator production edits. This worker independently read its saved JUnit XML and verification summary. The result was one failure in 1.439 seconds, exit code 1, 546 frozen files, and no source drift. The failure is exactly the missing `reviewShape` after the earlier assertions proved a known-charged SDK `invalid_assessment` failure. Both starting Python hashes matched the RED checkpoint at release. No production edit preceded the parent receipt.

## Implemented boundary

After the existing metering checks record known usage, the evaluator optionally asks `revision_shape_diagnostic(error)` for origin-validated evidence. Only failed v3 revisions with the closed diagnostic error codes, matching unchanged code/usage, and no withheld review are eligible. Any getter, shape validator, or wrapper-construction exception omits the optional diagnostic while retaining the original error code, safe message, charge, and consumed allowance. No raw diagnostic exception text is logged or stored.

`reviewShape` has exactly the contract's wrapper fields: schema version, manifest/case IDs, revision purpose, original observation/candidate hashes, error code, known usage, validated shape, and receipt hash. Recovery validates the closed shape schema and reconstructs the wrapper from the existing server case and failed row; canonical comparison checks every field and rejects Boolean/integer substitutions. Partial, mismatched, unknown-metered, completed, other-code, withheld, or old-mode wrappers reject before summary or resume dispatch. Old rows without the optional field remain valid.

The wrapper stays private to the failed journal row. No diagnostic enters observations, prompts, review input, admitted decisions, scores, or reports. The reservation, dispatch, retry, pricing and scoring behavior is unchanged. A diagnostic is evidence of JSON structure only, not evidence that a response is semantically valid.

## Authored bounded checks and frozen implementation

Five test functions expand to **11 cases**: the original real-SDK failure with a bound private shape and no redispatch; old failed rows without shape; three grouped corruption scenarios covering all wrapper bindings, strict shape validity and illegal row states; four exclusion cases for old review mode, unknown usage, validated withheld review and a copied/unmarked original failure; and getter/wrapper failures that must preserve the original known charge and safe message. Corruption checks recompute receipt hashes where appropriate and require rejection before report replacement or any additional calls. Transport remains the real SDK over existing MockTransport fixtures.

Both owned Python files passed standard-library AST parsing, and static whitespace checks passed. AST source comparison against the RED snapshot confirmed byte-identical `preregister`, `_actions`, `_matches`, `_summarize`, `_error_message`, `_withheld_review`, and `_validate_withheld_review` function bodies. Existing parent pricing/criteria and withheld-diagnostic work were preserved.

Frozen Python hashes:

- `backend/app/services/world_simulation/consistency_evaluation.py`: `2752509d92022bcab19b3e02070580b02ff72ee0825370ff8334e7064ee48698`.
- `backend/tests/test_world_review_shape_evaluation.py`: `5452e7d31e05961a9ff29c7691c25c7de378e0095ecb1bc39aaae7af5b669123`.

### First guarded GREEN and remaining gate

The parent receipt is `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-v3-shape-diagnostics-first-20261017T163814Z-hji9d75i/evidence`. This worker independently read its saved JUnit XML, verification summary, and source manifest and compared current owned Python hashes:

- **453 passed**, **0 failures**, **0 errors**, **0 skipped**. JUnit time is **13.884 seconds**; parent reported 13.89 seconds.
- All **11 evaluator shape-diagnostic cases passed**, with zero failures/errors/skips.
- `exitCode: 0`, **548 frozen files**, and `sourceDrift: []`.
- Both current owned Python hashes exactly match the frozen manifest and the checkpoint above.
- The parent separately reports Ruff F/E9 clean across all six newly owned Python files; this worker did not run Ruff or tests.

The offline implementation gate has passed. Exact independent review closure against the frozen source is still required before a bounded diagnostic, and no independent-review pass is claimed in this note. The parent reports freshly emitted directed/full-36 manifests, but the full-36 run is not authorized. The reported global remaining budget is USD 20.036201044336; this records the parent's accounting rather than new spending permission.

This change only adds private structural diagnostics. It does not alter admission, acceptance, prompts, retry allowances, pricing, or scores, and it is not a new behavioral fix or proof of live/full-behavior success. After this receipt check, only this scoped note was updated. Source/tests remain frozen, and the worker stops without runtime, providers, commits, or delegation.

## Updates

- 2026-10-17T16:30:50Z: Read the approved design, shared contract, existing evaluator and real-SDK test transport; authored the known-charged missing-diagnostic regression. Production evaluator remains untouched pending parent RED evidence.
- 2026-10-17T16:35:29Z: Verified the meaningful parent RED and release, implemented optional server-bound failed-row shape persistence and strict recovery validation, authored 11 bounded cases, checked AST/static and preservation evidence, and recorded frozen implementation hashes for parent execution.
- 2026-10-17T16:39:10Z: Independently verified the 453-test first GREEN, all 11 evaluator cases, zero failures/errors/skips, 548-file no-drift receipt, and matching current/frozen hashes. Recorded parent-reported lint results and the still-required independent review closure. Updated only this note and retained the source/test freeze; no live or full-36 authorization is inferred.
