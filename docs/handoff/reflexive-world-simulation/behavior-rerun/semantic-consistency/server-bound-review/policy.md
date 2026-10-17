# Actor consistency v2 transport slice

**Status:** Complete — broad runtime acceptance and independent production-delta review closed. **Ownership:** policy.py, NEW test_world_consistency_v2_policy.py and this note only.

Phase nine closed with all twelve requests terminal, ten reviewed responses and a guarded summary pass. The coordinator reported US$18.735064955664 cumulative exposure and US$6.264935044336 remaining under the original authorization. These are coordinator-reported budget figures, not independently audited billing. No new budget or provider work is authorized for this worker.

The edit hold was respected until the explicit phase-nine closure message. [PLANS.md](PLANS.md) records the approved design. The parent owns MODE_V2/REVIEW_MODES, mode-specific assessment validation with v1 default, persistence/audit binding, controller and evaluator integration. This worker performs static source checks only; no application imports, test execution, providers, commits or additional agents.

## Scope and invariants

- Preserve literal `_SYSTEM`, `_REVIEW_SYSTEM` and candidate-prefix constants, ordinary/no-review wire, v1 revision wire/schema, old stores and shared SDK/modeler behavior.
- Add an explicitly pinned `actor-consistency-v2` branch with a standalone unambiguous outer `{decision, assessment}` response instruction and every existing inner action/visibility/protocol rule.
- V2 assessment checks contain only kind/explanation, exactly four distinct mandated kinds, clear/unresolved status and the existing 400-character explanation bound. No selected references/indexes, guessed values, normalization or truncation. Extra fields fail through parent validation with known usage retained.
- Capture the pinned mode before RPC and pass that local value into both request construction and returned assessment validation. Observation and candidate remain captured before RPC. No shared mutable per-call state.
- Review all supplied objectives, conditions/time, arithmetic and the complete final decision while preserving legitimate discretion and unresolved uncertainty. This is not an optimization oracle or proof that natural-language reasoning is correct.
- The parent server audit binds the whole immutable observation, candidate and final-decision hashes as scope, not model-selected evidence or truth proof. No private/evaluator context enters the prompt.

## Bounded checks and next step

Approximately twelve real-SDK/mock-HTTP cases will cover v2 wire and exact bounds, compact-schema and mode-substitution failures with known usage, clear/unresolved results, before-RPC input/mode capture, and unchanged ordinary/v1 requests. No new domain proof is added; the parent owns controller/store and directed runtime checks.

Pre-edit literal hashes: `_SYSTEM` `b35a1b0a7053ef95f1bf457c4d56bace3ca6de3b8a07e2714dac8b9ef11382ba`; `_REVIEW_SYSTEM` `b2ad82d72790da7b0fd6d260af7f16fd2e58f3acee463ef436fc29eb752d344f`; `_REVIEW_CANDIDATE_PREFIX` `0fb6dd5524ff936caf7e84d2c72eb7d01f277b246d2e62beb089806ae59253aa`.

Freeze only these owned source/test bytes after static checks. Runtime acceptance and source review remain pending until the parent records them; no live behavioral result or full-study gate success is claimed.

## Frozen implementation

Implemented the distinct mode branch using parent MODE_V2/REVIEW_MODES and mode-specific validate_assessment. V2 builds a standalone outer-envelope system message with the complete existing action-rule suffix; v1 retains its literal system/revision strings and original concatenation. The request's mode is captured before RPC and passed explicitly through private request construction and post-response assessment validation. A changed instance flag during HTTP cannot change the response protocol. No reference/index field is generated, guessed, normalized or truncated by this adapter.

Exactly 12 dedicated actual-SDK/mock HTTP cases were added. They cover clear/unresolved wire and exact byte bounds, golden literal/v1/ordinary requests, forbidden reference/value/envelope extras and malformed compact checks with known usage, schema substitution across modes, caller observation/candidate/mode mutation during HTTP, and context rejection before dispatch. Existing shared test fixtures are reused with module aliases and explicit fixture assignments; no old tests or shared files were edited.

Static AST/whitespace checks passed. The three pre-edit literal hashes above are unchanged, and shared transport/modeler ASTs match the accepted v1 source snapshot. No runtime tests or application imports were executed by this worker.

- Frozen policy SHA-256: `b553f2103f2f8c18f20ed69aba1cfd3767bcf8708bba29da8c0b2509b965421e`.
- Frozen new-test SHA-256: `453e75fafeb47676af4c1ddef9c6193c9313dbf60120cb0494533e12ef967ebd`.
- Parent runtime/source review remains the next gate; no further case or domain-proof expansion is planned. Provider/pricing/native JSON-mode parameters and two-call limits remain unchanged.

## Runtime and source closure

The coordinator's v2 broad gate passed **882 tests in 130.43 seconds**, including all **12 dedicated v2-policy SDK cases**, with zero failures, errors or skips and no drift across **535 frozen files**. This worker independently inspected the run summary, JUnit, completion receipt and current owned source hashes; both match the first frozen implementation exactly:

| Owned source | Accepted SHA-256 |
|---|---|
| `backend/app/services/world_simulation/policy.py` | `b553f2103f2f8c18f20ed69aba1cfd3767bcf8708bba29da8c0b2509b965421e` |
| `backend/tests/test_world_consistency_v2_policy.py` | `453e75fafeb47676af4c1ddef9c6193c9313dbf60120cb0494533e12ef967ebd` |

Evidence: [broad-gate summary](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-consistency-v2-release-20261017T125633Z-94djanpo/verification-summary.json), [JUnit results](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-consistency-v2-release-20261017T125633Z-94djanpo/evidence/junit.xml), [guard completion](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-consistency-v2-release-20261017T125633Z-94djanpo/evidence/completed.json), and [console output](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-consistency-v2-release-20261017T125633Z-94djanpo/console.log).

The coordinator confirmed Epicurus's production-delta review has no findings; its remaining correction concerns documentation specificity only. The owned adapter and twelve SDK cases are accepted. The parent subsequently added a helper/test-only actual-SDK directed-v2 journal/resume scenario; its separate focused gate is not represented as complete by this broad receipt or by this worker. The owned production/test bytes remain unchanged.

The audit binds the complete immutable original observation, candidate and canonical final decision as **scope**. V2 does not select evidence paths or assert that every referenced fact was logically verified, and a structurally clear assessment is not proof of correct prose, arithmetic or goal interpretation. Literal v1 prompt hashes and ordinary/v1 wire controls remain accepted; the distinct compact v2 schema does not retroactively alter v1 assessments or old journals. No full-study behavioral-gate or promotion claim follows from this closure.

Source and pricing remain frozen for the coordinator's upcoming twelve v2 revision calls, capped at **US$1.25 within the reported US$6.264935044336 original-budget remainder**. No additional authorization or replacement attempts are created. The coordinator owns the focused journal/resume gate, live launch and subsequent review. This note claims no live v2 outcome.

Only this scoped note was changed for closure. No source/test/helper/pricing edits, application imports, runtime checks, provider calls, commits or agents were performed. Stop this worker's scope here; reopen only for a concrete regression or explicit authorized change after respecting the source freeze.

- 2026-10-17: Verified the 882-pass broad receipt and exact owned source bindings, recorded coordinator-confirmed Epicurus production closure, and separated scope-binding evidence from semantic/live claims and the parent's later focused gate.
