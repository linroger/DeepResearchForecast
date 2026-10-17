# V3 actor policy implementation

Status: the original policy slice's 25 SDK cases and exact-source independent review are closed per the coordinator's 2026-10-17 report. The bounded candidate-output repair extension passed the verified 668-case integration gate and remains frozen. Current independent review, broader feature acceptance and promotion remain pending.

This slice implements the approved [contract](contract-proposal.md) and [plan](PLANS.md) in `policy.py`, a new `test_world_consistency_v3_policy.py`, and this note only. The starting policy SHA-256 is `90e85195a407860b3d8c157176d0dee3e50b49da3202899d3805a69a0db39440`, including the parent's safe SDK transport diagnostics.

The actor interface remains `reservation(observation, *, feedback=None, review=None)` and `decide(observation, *, feedback=None, review=None)`. An explicitly pinned `actor-consistency-v3` revision uses a standalone prompt and returns the validated `checks` assessment unchanged. The parent-owned `assessment_status(assessment, *, mode)` derives the aggregate result; this adapter adds no aggregate field and does not override unknown or inconsistent verdicts. The existing request mode and serialized observation are captured before dispatch.

The optional exact `policy.responseFormat="json_object"` pin is retained as `_response_format` and emitted as `response_format={"type":"json_object"}` by the shared transport for actor candidate, actor revision, and modeler requests. An absent pin preserves old wire behavior. The original actor, v1 and v2 prompt constants, modeler message producer, strict parser, metering, two-attempt ownership, output limits, pricing and safe diagnostics remain unchanged.

The new file contains 25 parametrized cases using the real SDK with the existing mock HTTP boundary: the three verdicts; invalid or extra assessment fields and malformed JSON with known usage retained; exact old-mode wire and immutable request binding; explicit/absent format pins for actor and modeler; bounded UTF-8 reservation and no dispatch on preflight errors; and preservation of the sanitized one-dispatch HTTP status failure. The verdict fixtures deliberately retain positive prose with unknown/inconsistent verdicts to check that prose cannot override typed status derivation. The parent still owns withholding and durable admission tests. Prompt assertions verify the requested general distinctions and scope of visible evidence, not model reasoning quality or live behavior.

Static verification completed without application imports or execution: both Python files parse with `ast.parse`; the new test file contains 25 cases and has no duplicate test names or imported-fixture parameter shadowing; the scoped `git diff --check` passed. An exact source comparison against the starting policy, removing only the added v3 constant/branch and optional format initialization/dispatch additions, reproduced the entire original source byte-for-byte. This preserves the parent's safe diagnostics, old constants, request binding, parser, metering and all other existing code. These are static findings, not runtime test results. No tests, provider calls, commits or delegation were performed by this worker.

Historical initial-v3 frozen SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `backend/app/services/world_simulation/policy.py` | `42cf70612409e9ffda290ace5c943abd1fa7e0abb6c798a6ed83917983a71af1` |
| `backend/tests/test_world_consistency_v3_policy.py` | `4d238419f582403d4ba7d6b3d43669667d4c62513d4012365981df53002afec1` |

At the initial freeze, parent guarded runtime verification and exact-source independent review were pending. The subsequent results are recorded below. This worker keeps source and tests frozen. No live behavior improvement, full release gate success or default promotion is claimed.

## Historical runtime and source closure

On 2026-10-17 the coordinator reported that the first combined backend gate had 691 passing checks, including all 25 new v3 policy SDK cases and the core/legacy checks. Its 19 failures were attributed to ancestor-directory reads blocked by the profile-file guard, not to this policy slice. That first combined run therefore was not an all-green gate. A separate guard-repair run passed 213 checks, including all profile and fresh-launch cases, with no source drift reported; Parfit closed the guard review. These are separate run counts and are not additive unique coverage.

Epicurus's v3 cross-flow source review reported no findings against policy SHA-256 `42cf70612409e9ffda290ace5c943abd1fa7e0abb6c798a6ed83917983a71af1`, test SHA-256 `4d238419f582403d4ba7d6b3d43669667d4c62513d4012365981df53002afec1`, and the parent-owned core hashes. This worker independently rehashed the two owned Python files when recording this closure; both still match the frozen values. The runtime counts and reviewer conclusions above are attributed to the coordinator's report; no raw evidence-directory path was supplied in that message, and this worker did not rerun tests or independently inspect runtime artifacts.

No policy or test correction was required. The broader final gate still awaits the parent's actual-child test/browser work and default-consumer review. This note closes only the bounded policy runtime/source-review slice and does not establish full-feature acceptance, live behavior quality or permission to promote a default. No provider calls, runtime checks, source/test edits or commits were performed for this note update.

Budget and live execution remain parent-owned. The user has raised the total authorization to US$40, with US$20.249527044336 remaining at phase14 closure as reported by the parent. This slice makes no new budget allocation and does not alter historical results or promotion status.

## Candidate-output repair extension freeze

The [approved candidate-repair contract](candidate-repair-contract.md) is implemented without changing the public reservation/decision signatures. `StrictHTTPPolicy.candidate_repair` exposes `CANDIDATE_REPAIR_MODE` or `None`, using the parent-owned validating helper. An explicitly pinned v3 error-context request carries only the validated `schemaVersion`, `actorId`, `observationId` and closed `errorCode`. It uses a separate quoted context prefix and an instruction that no usable candidate exists; it does not embed malformed candidate text, exception messages, attempt IDs or hidden state. The unchanged original observation and the complete system/context text enter the existing byte-bound reservation before dispatch. Review mode, repair pin and request input are captured before HTTP; the final decision/assessment validation remains the existing v3 path.

`PolicyFailure` is ineligible by default. Only controlled, already-metered actor-candidate response parsing and public-input grammar failures can receive an opaque local origin receipt. `is_candidate_output_failure(error)` checks the exact failure type, closed error code, receipt identity and unchanged captured usage/code. Bare code plus usage, fabricated Boolean markers or mutated marked usage/code do not qualify. Unexpected parser/runtime errors, identity errors, unknown usage, transport errors, modeler errors and revision errors remain unmarked. This classifier identifies origin; the parent separately enforces the policy pin, durable attempt lineage and unused second-call limit. The adapter adds no automatic retry or third-call allowance.

Twelve SDK/mock-HTTP cases were appended, bringing this file to 37 cases. They cover malformed and public-grammar-invalid first responses followed by a separately requested reviewed response; exact context privacy and reservation; unchanged successful-candidate wire with/without the new pin; malformed/foreign/unpinned contexts; immutable context/mode/observation capture; input/context overflow; spoofed or mutated origins; ineligible unknown/internal/modeler/revision errors; and the v3/two-attempt pin requirements. Unknown final verdicts are returned unchanged for parent withholding. These tests are authored but not executed by this worker. Parent controller/store tests own durable repair admission, crash/reopen and the no-third-call proof.

Static checks passed: both Python files parse; the test file has 37 statically counted cases without duplicate test names or imported-fixture parameter shadowing; scoped whitespace checks are clean. Source comparisons against the accepted initial-v3 freeze confirm unchanged old prompt constants, safe diagnostics and `PolicyFailure` constructor, shared transport before dispatch (including native JSON pin/pricing/bounds), public grammar implementation, modeler class and all original 25 test bytes. The extension changes only the additional context/marker helpers, actor request/capture plumbing and controlled failure classification sites.

Current frozen SHA-256 values for parent integration verification:

| File | SHA-256 |
| --- | --- |
| `backend/app/services/world_simulation/policy.py` | `934fcf3a2d30371d2d465302b615c1c256c2cb4a2bc6a1edc74c7f6d6e702683` |
| `backend/tests/test_world_consistency_v3_policy.py` | `19f7320fb8b36a9053d89c41d63b9e7417c3b7ffd6f02469fe348eaca092f32e` |

The earlier runtime/source closure applies to the initial-v3 hashes, not this extension. The extension's first guarded integration result is recorded below; current independent review remains pending. No application imports, test execution, provider calls, commits, delegation or budget changes were performed by this worker. An initially flagged identifier-label concern was clarified by the parent as API explicitness/diagnostic specificity, not a reproduced TypeError; the parent owns that helper change and regression.

## Candidate-repair integration receipt

Independently inspected the coordinator's first combined integration artifacts at `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-candidate-repair-integration-first-20261017T160659Z-6nouqkvj/evidence`. The [JUnit receipt](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-candidate-repair-integration-first-20261017T160659Z-6nouqkvj/evidence/junit.xml) records 668 tests with zero failures, errors or skips; console output reports 668 passed in 8.24 seconds. This includes all 37 current v3 SDK cases, 216 original policy cases, 68 new candidate-repair store cases and 21 parent controller cases, alongside existing consistency/store/v3 and admission/fresh-launch scopes.

The [verification summary](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-candidate-repair-integration-first-20261017T160659Z-6nouqkvj/verification-summary.json) reports exit code zero and no source drift across 545 files. The frozen source manifest, copied policy/test bytes and current owned files all match the extension hashes above. `completed.json` confirms completed shutdown and exit code zero; its guard counters record three storage redirects, two blocked subprocess attempts and 464 allowed directory traversals. The guard identifies its boundary as CPython audit hooks, not an OS sandbox.

No policy/test correction was needed after this gate, and no source/test edits or reruns were performed for this receipt update. It closes the bounded integration check only. Independent reviewers are still closing current findings; the broader all-world/affected-legacy gate and frontend browser work remain parent-owned next steps. This receipt does not establish live behavior success, a full-study pass or default promotion. No paid calls were made by this worker.

Updates:

- 2026-10-17: Read the frozen contract and parent review interfaces; recorded ownership, preservation baseline and acceptance checks before implementation.
- 2026-10-17: Implemented the isolated v3 prompt/branch and optional native JSON format pin, wrote 25 focused SDK cases, verified AST and exact preservation outside the approved additions, and froze the two Python hashes above for parent verification.
- 2026-10-17: Recorded the coordinator's historical first-gate and guard-repair results and Epicurus's no-findings exact-source closure; independently confirmed both owned Python hashes unchanged. Broader acceptance and promotion remain parent-owned and pending.
- 2026-10-18: Began the approved [candidate-output repair extension](candidate-repair-contract.md), limited to this note, the same policy module and its v3 SDK test file. The adapter will expose the optional string pin, separately quote a validated closed error context, and mark only known-metered actor-candidate output-validation failures. The parent owns shared helpers, controller admission, durable attempts and runtime verification. No runtime execution or provider work is authorized for this worker.
- 2026-10-18: Completed and froze the bounded extension and 12 additional SDK cases after static/source-preservation checks. Sent exact policy/test hashes to the parent for the combined guarded integration gate; no further code/test changes are planned absent an authorized finding.
- 2026-10-18: Independently verified the 668-pass first integration receipt, zero failure/error/skip counts, no source drift across 545 files and matching current policy/test hashes. Updated only this note; independent review and broader acceptance remain pending.
