# Actor protocol and grounding clarification

**Status:** Complete — guarded runtime acceptance and prompt source review closed. **Base:** `327ce89`, initially clean. **Date:** 2026-10-17 Asia/Singapore.

## Request and boundaries

The user requested a behavior rerun that preserves the original failed/incomplete study and keeps the engine opt-in until the new gate passes. This worker owns only `backend/app/services/world_simulation/policy.py`, `backend/tests/test_world_policy.py` and this new note. Evaluator, study design, runtime execution, release documentation, schemas and observations belong to other owners. No provider calls, application/test execution, commits or delegation are authorized here. The coordinator runs guarded checks. Original evidence is read-only; no scores, denominators, traces or case statuses are rewritten.

## Evidence and approved proposal

The original qualitative reviews dated 2026-10-16 identify general protocol and grounding problems:

- [Investment review](../live-evidence/qualitative-review-investment.md): several responses supplied offer parameters where consent requires an empty parameter object; one response mistyped an interaction ID; two later requests exceeded the declared quantity maximum. Another explanation claimed prior identical terms when the amounts differed and attributed a current capacity value to a message that reported a different quantity. These were rejected intents or explanation disagreements, not demonstrated unauthorized physical transitions.
- [Trade review](../live-evidence/qualitative-review-trade.md): unsupported speech claimed a standing offer and reserved inventory; some explanations conflated historical and current values or failed to acknowledge conflicting permitted sources. Many waits after the stated one-good objective was fulfilled were legitimate. This does not justify manufacturing a recurring actor objective to satisfy an action proxy.
- [Coalition review](../live-evidence/qualitative-review-coalition.md): an actor described a proposal to an unsupported counterparty; another confused waiting for authorization with exercising its own available vote. Recorded coalition consent did not itself cast votes or authorize spending. Failed provider cases remain unscored; the review does not establish a behavioral cause for those failures.

Before edits, the coordinator approved a minimal general prompt clarification: operation-dependent parameters and exact same-record offer IDs; proposal/consent/reservation/settlement/vote/authority distinctions; and attributed, temporally accurate factual claims. The prompt must contain no domain-specific expected actions, case IDs, evaluation-arm labels, rubric answers or invented authority. No schema or observation change is needed.

## Implementation and acceptance plan

Only `_SYSTEM` will change in production. For execute/propose/counter, the model is told to follow the visible input schema and bounds. Accept/reject/defer/withdraw require omitted or empty parameters even when the template declares required proposal inputs; response references must copy all identifiers from the same visible protocol record. Grounding instructions distinguish current observations, historical records and attributed actor claims, and require support before claiming consent, reservation, execution or authority. A separate vote remains an independent actor action.

| Requirement | Planned evidence |
|---|---|
| Clarification reaches actual model request | Inspect the real SDK's mock-HTTP system payload in protocol scenarios. |
| Correct consent despite required proposal fields | SDK proposal and metadata-only acceptance pass through the real validator/kernel and settle exactly the offered transfers. |
| Counteroffer remains a new unaccepted proposal | SDK counter changes permitted terms without creating consent, holds or settlement. |
| Existing rejection boundaries remain | Wrong interaction ID/version, copied or altered consent parameters and over-maximum quantity still yield explicit rejected resolutions. |
| Consent differs from voting/authority | SDK coalition consent changes its declared relation only; a later separate vote records only that actor's vote. |
| Original study preserved | Compare the original evidence hashes below before handoff. |

Fake SDK-boundary outputs demonstrate protocol handling, not that a real model will comply with the prompt or improve its explanations. Behavioral improvement requires the coordinator's new preregistered study and independent review. Transport, pricing, metering, request-bound identities and the durable two-attempt allowance stay unchanged.

## Original evidence hashes

All paths below are relative to `docs/handoff/reflexive-world-simulation/live-evidence/`.

| Artifact | SHA-256 |
|---|---|
| `qualitative-review-investment.md` | `321c92d6556fb6dfecabe62f088673cb26d55eb1fa4c4c1f3666a17460faad5d` |
| `qualitative-review-trade.md` | `c9b616de640a240760bdf628465e9f4fe676e81a8f1fc5a780f717b0fad39153` |
| `qualitative-review-coalition.md` | `5a7b734f492884ba50f192a51a0db44e77f416c7428bbe838dcc37f54ee56e10` |
| `qualitative-review-investment.json` | `099a0acb205e64fe68364712470174422fb7e96f6e78586b333c3d61dd6a2ede` |
| `qualitative-review-trade.json` | `fe94aa966724b7ad93f09e0556d0f7f48be8c46d07eff582efacc75d79b8416f` |
| `qualitative-review-coalition.json` | `26c6c6a0ea5de9df9f9f15a75742fcf875b8a01d2c9346b3a4089c92e00e9298` |
| `qualitative-review.json` | `f6c8a27dc861d9d06938d8ca7dc7e9eaf6e4e9cb3e019589395414bdf7441efe` |
| `preregistration.json` | `8b395d04703541fc8f57c42bcc7091c5bc6742ad13e2a6f607c4e35b0c19a717` |
| `report.json` | `8c1a3e5df850152d2cb6b6876f230a4823c3d0548c53b1a3f131e6fbee975cea` |
| `closure.json` | `4833ff883c7356e8dd56ba9b63bf0a61c5c1e453b90623a01666c7f156c53242` |

## Progress and next step

- 2026-10-17: Verified the requested worktree and clean `327ce89` base, read the saved qualitative evidence and current response/kernel contract, sent the concrete proposal before editing, and received approval for this prompt-only scope.
- 2026-10-17: Implemented the approved generic protocol/grounding wording in `_SYSTEM` and nine parametrized SDK/validator/kernel cases. Positive cases cover acceptance with omitted/empty parameters despite required proposal fields, a counteroffer remaining unaccepted without resource holds, and coalition consent followed by a separate own vote. Negative controls preserve rejection of copied/altered consent terms, a one-character wrong ID, wrong version and over-maximum quantity. Prompt assertions inspect the actual mock-HTTP wire payload separately from the deterministic transition checks; they do not assert improved real-model behavior.
- Static source inspection passed: both Python files parse, no trailing whitespace was introduced, and the production AST excluding `_SYSTEM` is identical to `327ce89`. All ten original evidence files listed above remain byte-identical to that base. These are source/evidence checks, not runtime test execution. No providers, tests, commits or delegation were run by this worker.
- Frozen policy SHA-256: `f44d2faab9c0d1471d76da7e038d28f74b7fa0f205ce48537f8b1bd95077ee67`.
- Frozen policy-test SHA-256: `6b5ee6702f1f4499764168debe80d00250b642f012d81b638d0765b748330f57`.
- Next: coordinator runs the focused guarded policy/kernel checks and integrates with the separately owned evaluator-v2 study. Only a new runtime regression warrants source changes. The engine remains opt-in; original outcomes and scores remain preserved. No runtime acceptance or behavioral improvement is claimed here.

## Final acceptance and closure

The coordinator's first behavior-v2 runtime gate completed with **351 passed in 51.55 seconds**, including **161 policy tests**, zero failures, errors or skips, and no source drift across **519 frozen files**. This worker independently inspected the run summary, JUnit, completion receipt and current source hashes. Both owned Python files match the initial frozen implementation and the tested snapshot:

| Owned source | Accepted SHA-256 |
|---|---|
| `backend/app/services/world_simulation/policy.py` | `f44d2faab9c0d1471d76da7e038d28f74b7fa0f205ce48537f8b1bd95077ee67` |
| `backend/tests/test_world_policy.py` | `6b5ee6702f1f4499764168debe80d00250b642f012d81b638d0765b748330f57` |

Evidence: [frozen-run summary](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-behavior-v2-first-20261016T184024Z-lfnuv1gs/verification-summary.json), [JUnit results](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-behavior-v2-first-20261016T184024Z-lfnuv1gs/evidence/junit.xml), [guard completion](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-behavior-v2-first-20261016T184024Z-lfnuv1gs/evidence/completed.json), and [console output](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-behavior-v2-first-20261016T184024Z-lfnuv1gs/console.log). The receipt records three storage redirects and two blocked SDK metadata subprocess probes, with no recorded network attempts. Those blocked attempts remain part of the evidence; this is not an OS-sandbox or zero-attempt claim.

The coordinator confirmed Epicurus approved the prompt delta. The owned prompt and deterministic SDK/validator/kernel regressions are accepted with no remaining policy finding. Correct protocol and rejection controls pass; these fixtures do not establish that a live model will obey the prompt, improve factual explanations or pass the behavioral study. The engine remains opt-in, and original study outcomes are preserved. The evaluator-v2 study, further review and promotion decision remain coordinator-owned.

Only this new note was changed for closure. No source edits, new test execution, provider calls, commits or delegation were performed. Stop this worker's scope here; reopen only for a concrete new regression or an explicitly authorized change.

- 2026-10-17: Verified the 351-pass receipt and exact frozen source bindings, recorded coordinator-confirmed Epicurus approval, and closed the owned policy slice without code/test/live work.
