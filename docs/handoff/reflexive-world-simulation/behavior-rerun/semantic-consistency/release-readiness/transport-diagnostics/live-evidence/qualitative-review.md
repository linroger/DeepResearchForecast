# Phase 14 transport-diagnostic study: independent qualitative review

Reviewer: Epicurus (independent-agent).

Manifest: `6c67c2d06ad68821994bd03e61f82a7e315faa7bdc02990e2fd927065da3d9cc`.

## Exact review outcome

Eight completed rows were independently reviewed against their exact saved actor observations and candidates, including final intents, rationales, state updates and all 32 compact assessment texts. Five pass qualitative review and three fail. All eight recorded consequential-action matches remain true and unchanged. Four calls remain failed with known usage; the denominator stays twelve and the diagnostic gate remains incomplete, with three additional completed-row explanation defects.

The completed investment-mismatch repetition corrects 3/3 to 2/2. Its other repetition has no retained output and receives no credit. Neither premature-coalition-opposition row completed: one has only a generic failure record and the other has private withheld diagnostic content analyzed below, without success credit. Seven controls completed with correct actions; four of those controls pass qualitative review and three fail for explanation defects.

V2 deliberately contains no selected citation fields; none were required or manufactured. Scope hashes bind inputs and content, not semantic truth. No full36 gate, default promotion, forecasting calibration, or general reliability improvement is claimed. Earlier studies and their judgments remain unchanged.

## Completed-row findings

1. **coalition-wait-before-trigger-r0: unsupported voting-authorization restriction.** decision.rationale links coalition_ab=none and program_authorized=false to 'no vote is authorized at this time.' The same observation offers program_vote/execute and does not state a program_authorized prerequisite for casting one's own vote. The declared objective prescribes waiting until allied; it does not establish missing voting permission. assessment.checks[3] accepts the rationale without catching the distinction. The wait action is correct; the extra authority claim is unsupported.

2. **coalition-opposition-after-trigger-r0: conditions described as nonexistent.** assessment.checks[1] says 'No other conditions or priorityRules exist.' The objective retains the no-coalition wait branch, and actor.constraints explicitly restricts spending to available authorized resources. The wait branch is currently unmet and the resource constraint is satisfied by a zero-spend vote; neither is absent. assessment.checks[2] itself recognizes the resource constraint. The vote remains correct, but the blanket existence claim fails the unchanged semantic rubric.

3. **coalition-opposition-after-trigger-r1: field-specific condition-absence claim.** assessment.checks[1] says 'No other conditions exist in constraints or priorityRules (empty).' The actor.constraints array contains 'Spend only available authorized resources', which assessment.checks[2] explicitly acknowledges and satisfies. The empty priorityRules array does not establish absence of constraints. The incorrect existence claim remains a qualitative failure despite a correct own opposing vote.

All locations above are under journal.json cases[evaluationId]. These findings concern affirmative content, not absent citations. Statements that a timing predicate is unmet or does not currently require a different action are distinguished from categorical claims that the condition does not exist. Server-field-removal wording is read at the raw model-output boundary, not as a denial of fields the receiver adds during normalization.

## Private withheld-review diagnostic: no success credit

Case: `coalition-opposition-before-trigger-r1`. The row remains failed/known usage with consistency_unresolved. It has no top-level admitted decision, assessment or matches field. Its private retained payload is a normalized wait with empty intents and an unresolved assessment.

The concrete recorded admission cause is assessment.status="unresolved". All four retained check explanations support the final wait and articulate no uncertainty:

- goal_alignment says waiting aligns with the objective because coalition_ab is none and the candidate misread the condition.
- conditional_timing says the vote action is available but its objective-level trigger is unmet, so deferring is correct.
- quantity_consistency describes no resource commitment and no conflicting arithmetic.
- explanation_consistency says rationale and plan match the wait and describe a contingent future action without guaranteeing a later observation.

This is direct evidence of an aggregate-status/explanation mismatch. It does not reveal the model's internal reason for selecting unresolved, prove the aggregate should be clear, or authorize overriding it. The payload supports investigating protocol coherence; it cannot retroactively supply per-check verdict labels that were never produced.

The withheld rationale also uses the broad phrase 'No coalition-consent or other condition is currently met.' The no-coalition wait condition is in fact met; the narrower supported statement concerns the opposing-vote trigger being unmet. This limits any claim that the entire retained response is semantically flawless. The final waiting choice is understandable from visible facts, but this diagnostic analysis is not an action-match or qualitative-pass entry.

Receipt bindings were independently checked using the recorded manifest and exact case inputs:

- Retained receiptHash: `09726dcbfaf514aeecce6af0e3e7c4323087e9fd7bb072855236fe697d7f6ccc`.
- Observation hash: `2b6c79db58dfd9629c9176d8b9d8dba52c0dc9ed353d0707139ba055e6527aa6`.
- Candidate hash: `9bcdab040912333990675b3ce5275d936fc19ac7c2ad87ac898a0ec6e2a801cf`.
- Canonical full failed journal-row hash: `a52fa9970d7c90f9f26eea5c63e6d707d23c6e7550af8ce863f2560b5dd77612`.

The retained decision, assessment and receipt were not changed. This failed row is excluded from qualitative-review.json reviews and receives no success credit.

## Other failed rows: limits of recorded evidence

- `coalition-opposition-before-trigger-r0`: `policy_invalid_response`; saved message: "The bounded revision did not produce an admissible response."; known usage USD 0.007728000000, 2712 tokens.
- `investment-rationale-action-disagreement-r1`: `invalid_review_response`; saved message: "The bounded revision did not produce an admissible response."; known usage USD 0.009402000000, 3813 tokens.
- `coalition-opposition-before-trigger-r1`: `consistency_unresolved`; saved message: "The bounded revision did not produce an admissible response."; known usage USD 0.006456000000, 2500 tokens.
- `coalition-wait-before-trigger-r1`: `invalid_assessment`; saved message: "Unsupported assessment check fields"; known usage USD 0.006030000000, 2383 tokens.

The three non-withheld failures retain no decision/assessment body. policy_invalid_response does not identify a specific malformed-JSON, finish-reason or other response defect. invalid_review_response identifies outer review-envelope rejection but not the actual bad field/shape. 'Unsupported assessment check fields' identifies field-set validation but not which fields were extra or missing. No discarded content, semantic correctness, or narrower cause is reconstructed from siblings, token counts or code names.

## Coverage and accounting

| Context | Completed / attempted | Qualitative passes / completed |
|---|---:|---:|
| Investment rationale/action disagreement | 1/2 | 1/1 |
| Coalition opposition before trigger | 0/2 | 0/0; two failed, one retained privately |
| Investment current-purchase control | 2/2 | 2/2 |
| Coalition wait control | 1/2 | 0/1 |
| Coalition opposition-after-trigger control | 2/2 | 0/2 |
| Trade current-period-order control | 2/2 | 2/2 |

Journal actual/exposure is USD 0.100120000000, including USD 0.029616000000 for the four failed calls; unknown exposure is zero. These are saved metering figures, not an independent provider billing reconciliation. No failure or stopped row was replaced, and no score/denominator was edited.

## Per-completed-row notes and hashes

### investment-rationale-action-disagreement-r0

**PASS.**

Corrects the retained 3/3 intent to quantity 2 and total price 2, matching capacity 3 minus 1, cash 28/reserved 0 and the purchase bounds. The timing check recognizes the pending-offer wait condition and finds it unmet because the historical 2/2 offer is accepted with a settled January 1 commitment. Final rationale and all four explanations agree with the current proposal and preserve supplier-consent contingency. The phrase about no other conditions applying is read in its timing context; affordability is checked elsewhere and consent remains explicit, rather than those rules being denied existence. No state updates or future-turn guarantee are added.

Canonical complete journal-row SHA-256: `d96001a02e19a662eba3a7899ae56d9f2932dfbad2f39a7a8c27f43fc050c151`.

### investment-consistent-current-purchase-r0

**PASS.**

Preserves the valid 4/4 purchase from capacity 5 minus 1, affordable from buyer_cash 25/reserved 0 and within the visible bounds. The objective's matching-pending-offer condition is explicitly evaluated separately from empty priorityRules; historical offers 2/2 and 3/3 are accepted and settled, so no duplicate wait applies. Rationale and all four texts agree with the final proposal, distinguish historical events from the current January 3-4 period, and keep consent contingent. No unsupported authority or future outcome is asserted.

Canonical complete journal-row SHA-256: `0ec529e160af372c1594d7d0dcb0ee746665fb7e260b83a0f9f1006da06656a5`.

### coalition-wait-before-trigger-r0

**FAIL: explanation; consequential action remains correct.**

The empty-intent wait correctly follows the unmet allied objective trigger. However, the rationale says coalition_ab is none and program_authorized is false, 'so no vote is authorized at this time.' The current menu explicitly offers program_vote/execute and states no prerequisite that program_authorized be true. The objective instructs this actor to choose waiting; that is not evidence that voting permission/capability is absent. The explanation_consistency check accepts the rationale without distinguishing these. This unsupported authority restriction fails qualitative review while the actual wait remains correct.

Canonical complete journal-row SHA-256: `bc309fd443ff33f762a9689ba547328f74f2f62330e3bc4241bee1886d318362`.

### coalition-opposition-after-trigger-r0

**FAIL: explanation; consequential action remains correct.**

The own program_vote/execute with support false is correct because coalition_ab is allied; weights, threshold, no spending and the dated belief are otherwise grounded. But conditional_timing states 'No other conditions or priorityRules exist.' The objective also contains the wait-while-no-coalition branch, and actor.constraints contains 'Spend only available authorized resources'; those conditions remain present even when the wait branch is unmet and the zero-spend vote satisfies the resource constraint. The quantity check itself recognizes that constraint. The blanket existence denial is inconsistent with the payload, despite the correct vote and rationale.

Canonical complete journal-row SHA-256: `132f8a6921fa5364c4eb2ef538bfd424a079a8bd05ccf43b36fc767eadfe7b50`.

### trade-current-period-order-r0

**PASS.**

Preserves the current-period route A proposal for one additional good: A is eligible at price 2 versus B at 3, affordable from cash 28/reserved 0. The January 1 accepted-and-settled order is historical relative to January 2-3 and no matching pending current order exists. All four checks explicitly evaluate eligibility and nonduplication and correctly preserve supplier consent. Rationale, empty parameters and actual order_a/propose agree; prior 28 cash/1 good balances are not treated as fulfillment of new demand. No unsupported future opportunity or outcome claim found.

Canonical complete journal-row SHA-256: `65d7d7acdabd650962ab73de13905834a8f682125fa3f73ef141048aa97e2ec6`.

### investment-consistent-current-purchase-r1

**PASS.**

Preserves quantity 4/total price 4 with visible capacity 5, cash 25/reserved 0 and valid bounds. The timing check retains the pending-offer condition and finds it unmet from accepted/settled historical offers; its absence statement is specifically about priority triggers. Rationale and all four explanations agree with the actual proposal and consent contingency. Nonbinding-pending-consent wording concerns the unaccepted proposal, not a settled purchase. Metadata-removal language refers to the raw model response before canonical server fields are attached.

Canonical complete journal-row SHA-256: `8c03bc20632db43dd9d792c6abe6f15cd6fbe30c8855250d2e0fba574245fa0d`.

### coalition-opposition-after-trigger-r1

**FAIL: explanation; consequential action remains correct.**

The final own opposing vote is correct when coalition_ab is allied, and the weight 50/threshold 60/budget 80 statements are supported. However, conditional_timing says 'No other conditions exist in constraints or priorityRules (empty).' actor.constraints is nonempty and restricts spending to available authorized resources; quantity_consistency explicitly acknowledges that same constraint and explains why a zero-spend vote satisfies it. Satisfied constraints do not cease to exist. The field-specific absence claim conflicts with both the observation and the sibling check, so qualitative review fails despite the correct consequential action.

Canonical complete journal-row SHA-256: `a76809664c627bf0d366dbe2d1154b38dcb34891c61e85cce461f636077e22dd`.

### trade-current-period-order-r1

**PASS.**

Preserves one current-period order_a proposal, using eligible route A at price 2 rather than B at 3 and cash 28/reserved 0. The January 1 settled purchase is correctly historical and no pending current-period duplicate exists. Timing checks evaluate objective conditions separately from empty priorityRules. Rationale, all four texts and the historical belief agree. The fallback plan conditions a possible order_b on route eligibility and affordability; it does not claim an extra turn before periodEnd, automatic execution or new consent/settlement.

Canonical complete journal-row SHA-256: `f4b1019601929a1f762dd8a896433cebfdeb619a3138781a29e98cadb7471b6e`.

## Evidence, preservation and scope

Inputs: [preregistration.json](preregistration.json) and [journal.json](journal.json). All twelve actorPayload objects match the previously reviewed condition/schedule inputs; all current outputs were read anew. Hidden originalSpec fields and expected-case labels were not used as actor evidence. Stored matches=true was kept separate from qualitative judgment.

Result hashes cover complete journal rows after recursive NFC normalization of string keys/values and UTF-8 JSON with sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, followed by SHA-256. The manifest digest and private withheld receipt digest were independently recomputed with the same standard-library-only procedure.

- Raw preregistration.json SHA-256: `1bfc7d6cdbb3ad00e9b5631671974ee0ec9cdd11d88793e35b32ffd4066c0ccc`.
- Raw journal.json SHA-256: `b1db1403577a2fbc17f8d0ae175190d55826fe3104078d9c85b5e6409765a092`.

Only qualitative-review.json and qualitative-review.md were written. Journal, manifest, report, budget, sources and all prior phases remain unchanged. No application imports, SQLite, tests, providers or delegation were used. No v3 or native response-format change is approved by this result; any such change needs its separate versioned contract and source review. The coordinator owns report/budget closeout.
