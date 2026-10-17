# V4 lossless review-field helpers

**Status:** Frozen helper bytes verified against the parent's green first v4 combined gate; note-only receipt and quote inspection recorded below. No new code/test edits or live calls are authorized here. The earlier proposal status in PLANS.md is superseded by the approved [contract](contract.md) and the coordinator's implementation release.

Ownership is limited to `backend/app/services/world_simulation/review.py`, new `backend/tests/test_world_consistency_v4_review.py`, and this note. No application imports, test execution, providers, commits or delegation are authorized for this worker. Other workers own policy and durable integration; the parent owns fresh-admission profiles and runtime gates.

Frozen API: `MODE_V4="actor-consistency-v4"`; `normalize_v4_assessment_output(raw_assessment) -> canonical_assessment`; `validate_assessment(..., mode=MODE_V4)` and `assessment_status(..., mode=MODE_V4)` accept canonical form only. Failures use typed `invalid_assessment`. The explicit candidate-repair pin can apply to v3 or v4 with the same two-attempt limit. Fresh normalization is a separate entrypoint and must not be invoked on stored/replayed canonical assessments.

The implementation will preserve every raw noncontrol member under its original key, including a raw member named fields. It will enforce the approved control keys, reserved-key comparison-only rules and exact depth/node/member/key/canonical-byte/string bounds. Failure rejects the whole output; no partial fields, invented explanation, inferred verdict or semantic interpretation is allowed. A syntactically clear assessment is not proof of correct reasoning.

The starting `review.py` SHA-256 is `3d2eab97b4020ab6c5f66dca8d5bf3fc0dd85c74655877a1c07f5ace27bc22ad`. The complete existing diagnostic suffix hashes to `09c2e6b36e8152cb363305dd98d227d456f941e764ff8451a6a914828134df3b`. Static verification will check unchanged diagnostic/legacy validators, the narrow shared-mode additions, AST syntax and Ruff F/E9. Approximately fifteen bounded test functions will be authored for coordinator execution.

## Restored-session freeze checkpoint — 2026-10-17T17:49:43Z

After disconnect/resume, the coordinator explicitly froze all current v4 code/test bytes and reported that parent AST checks had completed. This worker verified only the two owned file hashes and updated this note. No source or test edit, application import, AST/lint execution, test run, provider request, commit or delegation occurred during this checkpoint. The earlier planned owner static verification is not represented as completed; the parent-reported AST check is distinct from runtime acceptance.

| Frozen owned file | SHA-256 |
|---|---|
| `backend/app/services/world_simulation/review.py` | `7ee619187133ce68a4504e5936ece3d2a6c54b97b03cb6889df9967806368358` |
| `backend/tests/test_world_consistency_v4_review.py` | `a679b2557aa5d10c165387500b142bbee820f334d263165fe321ebcfad6fea49` |

The API above remains the consumer contract: fresh-only `normalize_v4_assessment_output`, canonical-only v4 validation/status, and explicitly pinned v3/v4 candidate repair with the same two attempts. The authored tests cover reconstruction, original key/value preservation, canonical idempotence, control/reserved-key rejection, exact bounds, old-mode separation and candidate-repair admission. They remain pending the parent's execution; no pass or independent review closure is claimed here.

Wait for the parent's combined gate receipt and concrete failures before making any code/test correction. Parent owns all execution, the separate high/8192 profile preflight and fresh-admission integration. The coordinator reports all seventeen live phases closed, conservative total exposure USD20.074838955664 and USD19.925161044336 remaining from the approved USD40, with no provider active. These are coordinator-reported continuity figures, not a budget audit performed by this worker or authorization for new calls. Only note updates are permitted while this freeze remains in effect.

## First v4 guarded receipt and quote inspection — 2026-10-18 Asia/Singapore

Verified existing evidence at `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-v4-lossless-first-20261017T174905Z-zrav9nc5/evidence`. The console records **528 passed in 20.95s**; JUnit records 528 cases, zero failures/errors/skips, and suite time 20.946 seconds. The sibling verification summary records exitCode 0, `sourceDrift=[]`, and 553 files, matching the manifest entry count. These are one run's respective time reports, not separate runs.

The run includes 35 v4 review-helper cases, 15 v4 SDK-policy cases, 12 v4 integration cases, 190 admission cases, 46 fresh-launch cases, 39 v3-policy cases, 34 shape-helper cases, 12 shape-policy cases, 11 shape-evaluator cases, 41 consistency-store cases, 21 repair-controller cases, 68 repair-store cases and four parent v4 consumer/profile cases. Their counts sum to the single 528-case gate. Current helper/test bytes, the copied frozen sources and the manifest all match the two hashes recorded above. Source and tests were not edited for this note.

The completed guard receipt reports shutdown complete, identity preserved, three storage/logger redirects, two blocked subprocess events and 464 allowed directory-traversal events. It contains no network event category. These are CPython audit-hook observations, not an OS sandbox guarantee or a claim that process probes were never attempted.

### High/8192 reservation evidence

Read `evidence/v4-profile-quotes.json` and its frozen producer, `source/backend/tests/test_world_consistency_v4.py:85`. The producer loads the explicit profile, asserts v4 and candidate-repair pins, high reasoning effort and 8,192 output tokens, creates a real SDK/strict policy with a recording MockTransport that raises on dispatch, computes reservations, and asserts that the recorded call list remains empty before writing the quote artifact. The corresponding directed SDK tests also assert `reasoning_effort="high"` and `max_tokens=8192` in captured fixture request bodies. This is concrete offline configuration/wire evidence, not live-provider behavior.

The twelve directed reservations total **USD0.990360000000**, below their USD1.25 ceiling. The largest individual reservation is USD0.092240000000 / 29,736 tokens. The artifact records `providerCalls=0`, `fullCaseOpeningRequestsFit=true` and `completeTrajectoryCostGuaranteed=false`.

For the full36 specification, the producer checks each actor's initial proposal observation with three bounded request forms: candidate generation, revision of a validated synthetic wait candidate, and candidate-error repair context. Each individual opening quote fits its case's token/USD ceilings. This does not sum all rounds, cover later observations, prove two requests jointly fit every future slot, or guarantee completion of the full trajectory. The emitted full36 preregistration is not authorization to launch it. The profile's sourced pricing/transport assertions were consumed as pinned inputs; this note does not independently reverify vendor pricing or reasoning-token guarantees.

### Preservation and remaining gates

A read-only AST source comparison against the pre-edit hashes recorded during implementation confirms unchanged source text for `_validate_v3`, candidate error-context helpers, legacy index/evidence helpers, and both shape-diagnostic helpers. Removing only the added v4 branches from the source text of `validate_assessment` and `assessment_status` yields their exact pre-edit hashes. The entire diagnostic block also matches its recorded pre-edit hash. The older temporary v3 snapshot was unavailable during this check, so the comparison used those already-recorded hashes rather than claiming a fresh comparison with that deleted snapshot. Shared mode registration and candidate-repair support are the intentional v4 additions.

No remaining finding was identified in this owner's bounded helper/receipt check. This is not independent review of self-authored code and does not establish a semantic reasoning fix, live/full-behavior pass or default promotion. The coordinator reported one unused-import Ruff finding in another worker's new test and assigned its narrow correction there; this worker made no change to that file or to production sources. Parent owns any fresh gate needed after that correction, independent review, profile authorization and live evaluation. No tests, application imports, providers, commits or delegation were executed by this worker; only the helper note was updated.

## Coordinator closure — 2026-10-17T18:13:24.562385+00:00

Exact-source independent review is closed with no production findings. The separate profile capability-source gap is resolved by the persistent public snapshot. Broad regression passed1526checks with no drift553; final206check snapshot refreshes source-bound launch metadata after an admission docstring-only correction with unchanged executable AST. See review-closure.json and offline-final/. This closes implementation verification, not live behavior acceptance or default promotion. Source/tests are frozen for the next preregistered confirmation.
