# Fresh HTTP v4 assessment normalization

Status: implementation is frozen after phase17 closure and approval of the [v4 contract](contract.md). The first 528-case guarded integration receipt has been independently verified. Exact-source review and the parent-owned profile/admission release decisions remain pending.

Ownership is limited to `backend/app/services/world_simulation/policy.py`, the new `backend/tests/test_world_consistency_v4_policy.py`, and this note. The policy baseline SHA-256 is `790285e696d701f1ebaa55ad4a4e9f45397db405006098fd76954a467d03402b`. Mill owns the shared v4 constants, normalizer and canonical validators. Other owners retain controller/store/evaluator/admission work. This worker does not change the separate high-effort/8192-token profile or its feasibility checks.

The public policy interface is unchanged. Explicit v4 revision requests retain the exact preferred v3 prompt and repair suffix. Only fresh HTTP v4 assessment output is normalized through `normalize_v4_assessment_output(raw_assessment)`, then validated using the review mode captured before dispatch. Each canonical check retains every original parsed non-control field under `fields`, including a raw field named `fields`; reconstruction must reproduce the original parsed check. No explanation, control value or semantic verdict is invented. Candidate repair extends to the explicit v4 pin under the existing two-attempt rules, and v3 shape diagnostics remain v3-only.

Fifteen actual-SDK/mock-HTTP cases are written. They cover exact raw-check reconstruction with missing explanations, extra and contradictory data, preserved raw `fields` keys, all three explicit verdicts, canonical validation without repeated normalization, reserved/member/byte/depth/control/float rejection with known usage, byte-identical v3/v4 preferred and repair requests, immutable before-RPC mode/observation capture, unchanged None/old-mode/modeler paths, and two explicit failed calls without an automatic third dispatch. A separate control confirms explanation-based shape diagnostics remain v3-only. The parent owns durable controller/store/reopen and attempt-cap integration evidence.

Static verification passed: policy and new tests parse with `ast.parse`; the new file contains 15 statically counted cases with no duplicate test names or imported-fixture parameter shadowing; scoped whitespace checks are clean. Removing only v4 import/mode support and the fresh-normalization branch reproduces the accepted policy baseline byte-for-byte. All prompt constants, candidate-origin handling, v3 diagnostic capture/getter, parser acceptance, transport, native JSON settings, pricing and metering therefore retain their prior source bytes. The existing v3 test file remains `69debc3b7d9541945a0799e0dc9713f9dacf0c3da4ab988dc01ca2480b08a2de`, and the existing shape-policy test remains `99e90964bbae9c5122c1d6119c338b7bf014e10896bafa9be2ef33b9a34fa44a`; neither was edited. Mill's new helper signatures and implementation were inspected as source only.

Frozen SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `backend/app/services/world_simulation/policy.py` | `5c4297f49b5ae5744da146e3ec8dd596dfc07d295f3641998b992ab6f4ce90d3` |
| `backend/tests/test_world_consistency_v4_policy.py` | `b12ac7878efa99612e981b60a4f776c8789d980f5549308cfa367ea87c8d4e1a` |

The coordinator has been notified that these bytes are ready for the guarded gate and independent source review. The parent runs all tests; this worker performed no application imports, runtime tests, provider calls, commits or delegation. Representation admission is not semantic approval. The historical results, remaining factual failures and full behavior gate are unchanged, and no live success or default-promotion claim is made.

## Restored checkpoint

After the transient disconnect and user resume, the coordinator confirmed that the current v4 sources were AST-checked and are being frozen for the combined guarded run. This worker independently rehashed the owned policy and SDK test; both still match the full frozen hashes above. No code or test changes were made on resume, and the accepted precision rules in `contract.md` remain the implementation contract. Await parent-reported gate failures or an explicit correction before any further source/test edit.

The coordinator reports all 17 live phases closed, no active provider, cumulative exposure US$20.074838955664 and US$19.925161044336 remaining under the approved total US$40. This is the parent's reconciled checkpoint, not a new allowance. All runtime tests, high-effort/8192-token profile preflight and fresh-admission work remain parent-owned. This update changes only this note; no tests, provider calls, commits or delegation were performed.

## First guarded v4 integration receipt

Independently inspected the supplied artifacts at `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-v4-lossless-first-20261017T174905Z-zrav9nc5/evidence`. The [JUnit receipt](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-v4-lossless-first-20261017T174905Z-zrav9nc5/evidence/junit.xml) records 528 tests with zero failures, errors or skips; the console reports 528 passed in 20.95 seconds. This includes all 15 v4 SDK cases, 35 v4 helper cases, 12 v4 integration cases, fresh admission/launch checks, and existing v3, shape-diagnostic, store and candidate-repair scopes.

The [verification summary](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-v4-lossless-first-20261017T174905Z-zrav9nc5/verification-summary.json) reports exit code zero and no source drift across 553 files. Both owned policy/test files match the manifest, frozen source copies and current hashes above. `completed.json` confirms successful shutdown, three storage redirects, two blocked subprocess attempts and 464 allowed directory traversals; its stated boundary is CPython audit hooks, not an OS sandbox.

The coordinator reports one Ruff finding, an unused `digest` import in the separately owned v4 integration test, with a narrow test-only correction requested from Poincare. That is distinct from this passing runtime receipt and requires no policy or owned SDK-test edit. The coordinator also reports profile-quote checks passed and directs independent reviewers to `v4-profile-quotes.json` for the explicit high-effort/8192 bound and no-HTTP evidence. Those profile conclusions remain parent/reviewer-owned; bounded quotes for the tested inputs do not guarantee feasibility over an arbitrary future trajectory.

No production or owned-test changes were made for this receipt update. Exact-source independent review remains pending, and this gate does not establish live reasoning quality, a full-study pass or default promotion. All historical failures remain unchanged; this worker performed no runtime tests, provider calls or commits.

Updates:

- 2026-10-18: Read the exact approved contract, confirmed the frozen helper interface, captured the accepted policy baseline and recorded the bounded fresh-HTTP integration plan.
- 2026-10-18: Implemented only v4 mode support and fresh-response normalization, wrote 15 SDK cases, verified ASTs/source isolation/test hygiene/whitespace and sent frozen hashes to the parent. Stopped for guarded runtime verification and independent review.
- 2026-10-18: Restored after disconnect, confirmed the policy/test hashes unchanged and recorded the coordinator's combined-gate freeze and reconciled 17-phase budget checkpoint. Note-only update; waiting for parent gate results before any source/test edits.
- 2026-10-18: Independently verified the first 528-pass/20.95-second v4 integration receipt, zero failures/errors/skips, no drift across 553 files and matching current/frozen owned hashes. Recorded the separate parent-reported lint correction and profile-review boundary; edited only this note.

## Coordinator closure — 2026-10-17T18:13:24.562385+00:00

Exact-source independent review is closed with no production findings. The separate profile capability-source gap is resolved by the persistent public snapshot. Broad regression passed1526checks with no drift553; final206check snapshot refreshes source-bound launch metadata after an admission docstring-only correction with unchanged executable AST. See review-closure.json and offline-final/. This closes implementation verification, not live behavior acceptance or default promotion. Source/tests are frozen for the next preregistered confirmation.
