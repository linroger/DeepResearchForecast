# Revision-shape diagnostic policy slice

Status: the approved [diagnostic contract](contract.md) is implemented and frozen. The first 453-case guarded integration receipt has been independently verified. The coordinator reports exact-source independent review closed with no findings and phase17 active under a source/test/pricing freeze; no phase17 outcome is claimed.

This worker owns only diagnostic capture/getter code in `backend/app/services/world_simulation/policy.py`, the new `backend/tests/test_world_review_shape_policy.py`, and this note. The starting policy SHA-256 is `4ab43abf110ad9cf70aed77a0b627bf8950c7c12f4fc41c967e4c44ea0af5030`. Prompts, parser acceptance, transport, pricing, candidate-output markers, schemas and attempt allowances remain unchanged. Mill owns pure shape helpers and Poincare owns the directed journal.

The new `revision_shape_diagnostic(error)` interface returns a detached validated shape or `None`. Only already-metered v3 revision envelope and assessment validation failures can carry a receipt. The receipt binds the original exception instance, error code, usage and shape integrity; transferring attributes to another exception must fail. Optional builder/getter failures must preserve the original typed failure, fixed safe message and known usage. No raw response, unknown key names, values, identifiers or prose is retained in the structural shape.

Twelve focused real-SDK/mock-HTTP cases are written in the new test file. They cover envelope/assessment/check structural capture and privacy, detached getters, original-instance binding despite copied attributes, code/usage/shape tampering, builder and capture/getter-validator failures, excluded origins and captured review mode. Candidate, modeler, parser, unknown-metering, transport, identity, legacy-mode, public-grammar and internal failures do not acquire a receipt; neither do bare errors or a PolicyFailure injected in place of a validator WorldError. The parent runs all tests. This worker performs only source/static checks, with no application imports, runtime tests, providers, commits or delegation.

The opaque origin uses a weak reference to the original PolicyFailure instance, plus snapshots of its code, canonical usage and validated structural shape. The getter requires that original instance and unchanged snapshots before validating and returning detached shape data. Capture uses local validation-site labels and the review mode captured before HTTP; no request-specific state is stored on the adapter. Optional diagnostic exceptions are contained without replacing the original typed failure, fixed message or usage. The existing candidate marker and its eligibility classifier are untouched.

Static verification passed: policy and new tests parse with `ast.parse`; there are 12 statically counted cases, no duplicate test names or imported-fixture parameter shadowing, and scoped whitespace checks are clean. Removing only the diagnostic import, marker, helpers and controlled capture additions reproduces the accepted policy baseline exactly. Thus prompt strings, parser acceptance, dispatch behavior, native JSON settings, pricing, metering, candidate markers and attempt behavior retain their prior source bytes. The existing v3 test file remains at SHA-256 `69debc3b7d9541945a0799e0dc9713f9dacf0c3da4ab988dc01ca2480b08a2de` and was not edited.

Frozen SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `backend/app/services/world_simulation/policy.py` | `790285e696d701f1ebaa55ad4a4e9f45397db405006098fd76954a467d03402b` |
| `backend/tests/test_world_review_shape_policy.py` | `99e90964bbae9c5122c1d6119c338b7bf014e10896bafa9be2ef33b9a34fa44a` |

The coordinator was notified that these bytes were ready for the combined guarded helper/policy/journal gate. Its first runtime result and subsequent coordinator-reported source-review closure are recorded below. Historical gates apply to their own frozen snapshots. The diagnostic is private failure evidence and grants no actor visibility, admission, score or extra call.

Phase16 is closed according to the coordinator: seven qualitative passes, five known shape failures, cost US$0.110254 and US$20.036201044336 remaining under the approved total US$40. Prior results remain unchanged. This diagnostic slice neither explains discarded responses nor authorizes further live calls or default promotion.

## First guarded integration receipt

Independently inspected the supplied artifacts at `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-v3-shape-diagnostics-first-20261017T163814Z-hji9d75i/evidence`. The [JUnit receipt](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-v3-shape-diagnostics-first-20261017T163814Z-hji9d75i/evidence/junit.xml) records 453 tests with zero failures, errors or skips; console output reports 453 passed in 13.89 seconds. This includes all 12 new policy SDK cases, 34 pure shape-helper cases, 11 journal cases, 39 prior v3 SDK cases and 216 original policy cases, together with current repair, withheld-diagnostic and evaluation checks.

The [verification summary](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-v3-shape-diagnostics-first-20261017T163814Z-hji9d75i/verification-summary.json) reports exit code zero and no source drift across 548 files. The manifest entries, frozen source copies and current owned policy/test bytes match the hashes above. `completed.json` confirms successful shutdown, three storage redirects and two blocked subprocess attempts; the guard identifies its boundary as CPython audit hooks, not an OS sandbox. The coordinator also reports Ruff F/E9 clean across all six newly owned source/test files; this worker did not rerun Ruff or inspect a separate Ruff artifact.

This closes the bounded first integration check without any source/test correction. Exact-source review was pending at this receipt update; its subsequent closure is recorded below. Current-code directed/full36 manifests have been emitted according to the coordinator, but the full36 run remains unauthorized. Diagnostics do not change prompts or acceptance, constitute a new behavior fix, or establish live/full-study success. The reported global remaining budget at this point was US$20.036201044336; this note update allocates or spends none of it. Only this scoped note was edited, with no runtime tests, provider calls or commits by this worker.

## Exact-source review closure and phase17 freeze

The coordinator reported exact-source independent review closed with no findings, followed by the diagnostic-only phase17 launch in session `25831`. Its output directory is `/private/tmp/drf-world-review-shape-diagnostics-20261017` and manifest SHA-256 is `a3e795fa22c7b4911fe249fb11ce28269089042265c01b6a42c553600e38e427`. The launch notice reports 465 prior files verified. These review/launch statements are attributed to the coordinator. A local read-only check confirms the owned policy/test hashes still match the frozen values above; this worker has not inspected in-flight artifacts.

Phase17 is limited to 12 fixed calls and at most US$1.25 within the approved total US$40, with US$20.036201044336 remaining at launch as reported by the coordinator. Its prompt, actor payload and pricing are unchanged from phase16. Its purpose is to capture structural failure categories, not to test a behavior fix or claim a pass. Source, tests and pricing remain frozen until phase closure. Workers perform no edits beyond scoped notes, runtime tests or provider calls.

After completion, the independent reviewer will examine structural-receipt binding, case coverage, accounting and failure taxonomy. No phase17 result, behavior improvement, full-study success or default promotion is claimed here. The full36 run remains unauthorized; await the parent's end-of-phase report and reconciled receipt before further work.

Updates:

- 2026-10-18: Read the approved exact interface, captured the policy baseline and recorded ownership, original-instance binding and acceptance requirements before implementation.
- 2026-10-18: Implemented controlled diagnostic capture/getter and exactly 12 focused SDK cases; verified source isolation, ASTs, test-name/fixture hygiene and whitespace. Sent frozen policy/test hashes to the parent and stopped for guarded runtime verification and independent review.
- 2026-10-18: Independently verified the first 453-pass/13.89-second integration receipt, zero failures/errors/skips, no drift across 548 files and matching current/frozen policy/test hashes. Recorded coordinator-reported Ruff results and pending exact-source review; edited only this note.
- 2026-10-18: Recorded the coordinator-reported exact-source review closure with no findings and phase17 diagnostic-only launch/freeze, including manifest, session and bounded budget. Reconfirmed local policy/test hashes unchanged; did not inspect in-flight artifacts or claim an outcome.
