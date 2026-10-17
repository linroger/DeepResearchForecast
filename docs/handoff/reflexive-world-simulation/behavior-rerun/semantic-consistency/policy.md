# Bounded actor consistency-revision transport

**Status:** Complete — runtime closure, fixture correction and independent policy review accepted. **Base:** `95ebd04`. **Ownership:** policy.py, test_world_consistency_policy.py and this note only.

The user approved the opt-in contract in [contract.md](contract.md) and [PLANS.md](PLANS.md). The coordinator supplies review.py, PolicyResponse.assessment, controller/store stage handling and evaluator integration. This worker performs source inspection and static AST checks only; no application imports, runtime tests, providers, commits or delegation are authorized here.

## Confirmed interface

`StrictHTTPPolicy.decision_review` exposes parent-validated None or `actor-consistency-v1`. Actor `reservation(observation, *, feedback=None, review=None)` and `decide(...)` each preserve the existing one-dispatch boundary. Review is a normalized own candidate bound to the original actor/observation; the store owns full normalized identity validation. Simultaneous non-None feedback/review is rejected to avoid mixing repair and revision modes.

The original user observation remains byte-equivalent. Revision instructions and the canonical own candidate are explicitly quoted as untrusted data in the system message before exact byte reservation. Both inputs are captured before RPC with no shared mutable request state or caller reread. Candidate metadata is contextual data, never new authority. No case, rubric, expected-answer, evaluator, hidden-world or provider/pricing metadata is added to the prompt.

Revision output is exactly `{decision, assessment}`. The adapter binds only final outer execution IDs, runs existing public grammar, then delegates assessment bindings to the parent's validate_assessment against the original observation and final decision. Known usage is retained on malformed output or invalid assessment. A structurally valid unresolved assessment may return; controller/store own the clear-only admission rule. Ordinary candidate responses have assessment=None. Modeler and shared SDK, pricing, usage and retry behavior stay unchanged.

## Focused acceptance

Actual SDK/mock HTTP cases cover unchanged legacy/candidate wire, mode/candidate preflight, exact revision envelope and four-check assessment, input/output reservation, malformed/invalid assessment usage, final-intent binding, public grammar, privacy, mutation and concurrent actor isolation. These validate protocol and evidence-path bindings, not the truth of model-written explanations. The parent owns runtime gates and directed-case evaluation.

## Progress

- Read the frozen contract and parent pure validators. Confirmed candidate placement and explicitly bounded input validation with coordinator before editing. Parent review.py and PolicyResponse.assessment are now present; shared files will not be edited.
- Implemented the exact pinned mode and optional review API. Original observation text stays in the user message; generic revision instructions and canonical own-candidate JSON are system-message data included before byte reservation. Candidate binding and simultaneous repair/review rejection occur before dispatch. Revision shape, public grammar and parent assessment binding are checked after metering with usage retained on failure. Valid unresolved assessments are returned for coordinator denial. No review state is shared between calls.
- Added 35 dedicated actual-SDK/mock HTTP cases covering unchanged ordinary/candidate wire, pin and own-candidate rejection, exact quote/output exposure, envelope and assessment errors, final-intent/evidence binding, public grammar, mutation/concurrency/privacy and modeler preservation. Existing policy-test helpers are reused without edits; no further domain proof was added.
- Static syntax/whitespace passed. AST inspection confirms shared `_StrictHTTPTransport` and `StrictHTTPModeler` are unchanged from `95ebd04`. No application imports, tests, providers, commits or agents were run by this worker. Runtime verification and the parent directed contexts remain coordinator-owned.
- Frozen policy SHA-256: `2dce58234161b07eb8ac25c1bae82c88b938b375d5eaaca9c924894e69a670c3`.
- Frozen new-test SHA-256: `e65fcf5805735e9921fbc817e74d5424b976f300cbc869420d03bd69650d3ad6`.
- Stop source edits pending the coordinator's combined gate; only a concrete regression warrants reopening. No runtime acceptance or live semantic-correctness claim is made yet.

## First integration receipt and fixture-only correction

The first coordinator integration gate completed with **853 passed in 165.81 seconds**, including all **35 new consistency-policy cases** and **216 existing policy cases**, with zero failures/errors/skips and no drift across **532 frozen files**. The current production hash matches that tested snapshot: `2dce58234161b07eb8ac25c1bae82c88b938b375d5eaaca9c924894e69a670c3`. This worker inspected the run summary, JUnit and console output. Evidence: [integration summary](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-consistency-integration-first-20261017T122252Z-tldty5gf/verification-summary.json), [JUnit](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-consistency-integration-first-20261017T122252Z-tldty5gf/evidence/junit.xml), and [console](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-consistency-integration-first-20261017T122252Z-tldty5gf/console.log).

After gate completion, the coordinator authorized only the minimal F811 fixture-import correction. Replaced imported fixture symbols with a module import and explicit fixture assignments; fixture discovery and all test bodies are preserved. Production was not edited. Static AST parsing passes. The corrected test hash is `8e61ab7040629b20643977671a2a35f9c4092830d1773ae1202f0252120f404f`; the earlier 853-pass receipt covers the previous test-import spelling, so final focused acceptance of the alias fix remains coordinator-owned alongside its evaluator fixes. No application imports, tests, providers, commits or agents were run by this worker. Files are frozen again.

## Final closure

The coordinator's final review-closure gate completed with **345 passed in 7.65 seconds**, including **35 new consistency-policy SDK cases** and **216 existing policy cases**, with zero failures, errors or skips and no drift across **532 frozen files**. This worker independently inspected the run summary, JUnit, completion receipt and current owned source hashes. The alias correction is included in the tested snapshot:

| Owned source | Accepted SHA-256 |
|---|---|
| `backend/app/services/world_simulation/policy.py` | `2dce58234161b07eb8ac25c1bae82c88b938b375d5eaaca9c924894e69a670c3` |
| `backend/tests/test_world_consistency_policy.py` | `8e61ab7040629b20643977671a2a35f9c4092830d1773ae1202f0252120f404f` |

Evidence: [closure summary](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-consistency-review-closure-20261017T122724Z-8xzy9o2w/verification-summary.json), [closure JUnit](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-consistency-review-closure-20261017T122724Z-8xzy9o2w/evidence/junit.xml), [guard completion](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-consistency-review-closure-20261017T122724Z-8xzy9o2w/evidence/completed.json), and [console output](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-consistency-review-closure-20261017T122724Z-8xzy9o2w/console.log).

The coordinator confirmed independent policy-core review has no findings and its evaluator P1/P2 findings are closed. This accepts the pinned revision transport, exact byte accounting and known-usage failures, unchanged ordinary requests/modeler behavior, final-decision assessment bindings, and immutable/private input handling. Structural assessment validity is not proof that its natural-language reasoning is correct; unresolved revisions remain unadmitted by the coordinator/store. No policy-owned finding remains open.

Runtime, source and pricing are frozen for the coordinator's **12 directed revision calls**, bounded by **US$1.25 from the original remaining authorization**. This is not a new budget, reset, full-matrix behavioral-gate result or promotion authorization. No directed live outcome is claimed in this note. World-v1 remains opt-in and original evidence is preserved.

Only this scoped note was changed for closure. No code, fixture, pricing or runtime edits; no new tests, providers, commits or agents. Stop this worker's scope. Reopen only for a concrete regression or explicit authorized change after respecting the live-source freeze.

- 2026-10-17: Verified the final 345-pass receipt and exact source bindings, recorded coordinator-confirmed independent review closure and the bounded directed-call freeze, and closed the policy slice without runtime work.
