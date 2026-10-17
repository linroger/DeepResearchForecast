# Phase 15 independent qualitative review draft

Reviewer: Epicurus (independent-agent).

Manifest: `8c1ba3116350aa474e1712646928296888f55c180cf6f2f5df3e03c420a8f8fc`. Live source: `/private/tmp/drf-world-consistency-v3-20261017`.

## Result

**8 completed rows reviewed; 8 qualitative passes; 0 qualitative failures. Four known failed calls remain in the 12-call denominator. The confirmation is incomplete, not passed.** All eight stored action matches remain true and unchanged. No row contains withheldReview, so no withheld decision or assessment is available to analyze.

Both completed investment-mismatch repetitions correct the historical candidate from 3/3 to 2 goods for 2 currency. Both investment controls and both trade controls preserve their valid choices. One coalition-wait control and one coalition-opposition-after-trigger control completed and pass. Neither premature-coalition-opposition repetition completed, so this phase supplies no accepted correction for that retained error and receives no substitute credit from earlier phases.

All eight final decisions, rationales, state updates and 32 per-check verdict/explanation pairs were compared with the exact saved actorPayload and the preregistered caseId/repeat labels and criteria. No material goal, arithmetic, timing, authority, consent, source or actual-intent contradiction was established in the completed rows. Four consistent verdicts were not treated as proof of prose correctness; their explanations were read independently.

A wording caveat is retained for coalition-opposition-after-trigger-r1: 'The only condition' is imprecise, but within the timing check it describes the opposing vote's objective trigger. The same row's goal check explicitly names both wait and vote branches. It is not read as a blanket assertion that all other constraints are absent. Current-period phrases in the investment/trade rows are similarly read at the observed snapshot; none explicitly guarantees persistence throughout the future interval. These bounded readings do not regrade any earlier phase.

## Recorded failure grounds before any further fix

- `coalition-opposition-before-trigger-r0`: `invalid_assessment`; saved message: "Unsupported assessment check fields"; known usage USD 0.007160000000, 2722 tokens.
- `coalition-wait-before-trigger-r0`: `invalid_assessment`; saved message: "Unsupported assessment check fields"; known usage USD 0.006182000000, 2513 tokens.
- `coalition-opposition-after-trigger-r0`: `invalid_assessment`; saved message: "Unsupported assessment check fields"; known usage USD 0.006514000000, 2605 tokens.
- `coalition-opposition-before-trigger-r1`: `invalid_review_response`; saved message: "The bounded revision did not produce an admissible response."; known usage USD 0.006914000000, 2681 tokens.

The three invalid_assessment records establish rejection at the assessment check-object/field-shape boundary. They do not establish which field was missing or extra, what any unsupported field was named, or even the exact rejected object shape. The invalid_review_response record establishes review-envelope rejection without preserving the particular defect. No raw malformed bodies, final decisions or assessments are retained in these four rows. No field names, aggregate-status echoes, citation fields, semantic outcomes or narrower failure causes are inferred.

The evidence therefore supports a remaining response-shape reliability problem, with all four failures clustered in coalition contexts. That clustering is descriptive, not a causal diagnosis. It does not justify dropping fields, weakening the validator, regrading failures, or changing semantic criteria based on guessed output contents. There is no retained unknown/inconsistent per-check payload here to explain a semantic withholding decision.

## Coverage and accounting

| Preregistered context | Completed / attempted | Qualitative passes |
|---|---:|---:|
| Investment rationale/action disagreement | 2/2 | 2 |
| Coalition opposition before trigger | 0/2 | 0; both failed |
| Investment current-purchase control | 2/2 | 2 |
| Coalition wait control | 1/2 | 1 |
| Coalition opposition-after-trigger control | 1/2 | 1 |
| Trade current-period-order control | 2/2 | 2 |

Journal actual/exposure totals USD 0.103072000000, including USD 0.026770000000 for failed calls. Unknown exposure is zero. These are saved metering values, not independent billing verification. No replacement calls or credited discarded rows are assumed. This directed saved-context study is not fresh candidate generation, proof of the candidate-error repair branch, a full36 pass, default promotion, general model reliability or forecast calibration.

## Per-row findings and exact bindings

### investment-rationale-action-disagreement-r0

**PASS for this completed row.**

Pass against the correction label and actual observation: final price 2/quantity 2 replaces the candidate's 3/3 terms, matching capacity 3 minus 1, cash 28/reserved 0 and visible bounds. The prior 2/2 offer is accepted with a settled historical commitment, so the matching-pending-offer wait condition is unmet. Rationale, belief, plan and all four check verdicts/explanations agree. The shortened historical interaction identifier is an unambiguous prose locator, not an executable reference. No new consent, settlement or guaranteed later turn is claimed.

Canonical complete journal-row SHA-256: `d867af6ef416350785847bf29095c8480858ef298741f5ab25a49064fc6bcb17`.

### investment-consistent-current-purchase-r0

**PASS for this completed row.**

Preserves the valid control: capacity 5 minus 1 yields 4 goods for total price 4, within cash 25/reserved 0 and option bounds. Both prior offers are accepted with settled commitments; no current matching pending offer activates the wait condition. Rationale and all four consistent check explanations agree with the actual proposal and retain producer consent as contingent. Current-period absence wording describes the observed pending-offer state, not a guarantee that the ensuing period cannot change. No state updates or hidden authority claims are added.

Canonical complete journal-row SHA-256: `6314e19ad29e5667c416d6f1c2f43429b373b4fc257c3e275aa89be4502f0d52`.

### trade-current-period-order-r0

**PASS for this completed row.**

Preserves one current-period order_a proposal: both routes are eligible, A costs 2 versus B's 3, and cash 28/reserved 0 covers one good. The accepted-and-settled January 1 order is historical relative to January 2-3 and does not meet additional demand. No pending current-period duplicate exists. Rationale and all four consistent checks agree with the visible route prices, eligibility, time and actual empty-parameter proposal, subject to supplier consent. No settlement or future eligibility is assumed.

Canonical complete journal-row SHA-256: `70765bd3ce1310fddfe000862bab90683996577bf81ca4e3635c41d97d97a782`.

### investment-rationale-action-disagreement-r1

**PASS for this completed row.**

Corrects 3/3 to quantity 2/total price 2, matching capacity 3 minus 1, cash 28/reserved 0 and the purchase bounds. The historical 2/2 offer is accepted/settled rather than pending, so the objective's existing wait condition does not apply now. Rationale and all four check verdicts/explanations agree with the final proposal and distinguish past settlement from the new offer. The candidate inconsistency is between its rationale and parameters; the final row resolves that mismatch without assuming new consent or settlement.

Canonical complete journal-row SHA-256: `927532613f2ea3c698ef77a9f46b6303303167dfb549b35e68045219a405e09d`.

### investment-consistent-current-purchase-r1

**PASS for this completed row.**

Preserves the valid 4/4 purchase control with capacity 5, cash 25/reserved 0 and valid input bounds. The timing check evaluates the pending-offer condition separately from empty priorityRules: both differently sized prior offers are accepted/settled, not pending. Rationale and all four consistent checks describe the actual proposal, historical commitments and current target accurately. Producer consent remains contingent. No unsupported denial of objective conditions, future turn, or completed outcome is found.

Canonical complete journal-row SHA-256: `7eeb3a94a311e30f7aa5a86e40d23a1a923f7f18768ad1660c9b6ad5c40c08b6`.

### coalition-wait-before-trigger-r1

**PASS for this completed row.**

Preserves the valid wait control. coalition_ab is none at simulatedAt, so the opposing-vote objective trigger is unmet; empty intents and wait status agree. The spending constraint remains recognized and satisfied by no resource use, with budget 80/reserved 0 and empty inbox/offers/commitments. The belief records the current relation, and the plan conditions reassessment on a future observation and continued action availability without promising its timing. All four consistent check texts are supported; no missing-permission claim is introduced.

Canonical complete journal-row SHA-256: `33f0515c9933728dca550c153c4deeab0e1167d8293150e25dc98f20f24cbdbd`.

### coalition-opposition-after-trigger-r1

**PASS for this completed row.**

Preserves the valid own program_vote/execute with support false after coalition_ab is observed allied. The goal check explicitly retains both the no-coalition wait branch and the allied vote branch; weight 50, threshold 60 and budget 80 are grounded. Rationale, dated belief and four consistent checks agree with the submitted vote. 'The only condition' in conditional_timing is imprecise but is read as this vote's objective trigger, not denial of all constraints: the full row expressly recognizes the other wait branch. No blanket field-absence claim, future-state guarantee or extra decision opportunity is asserted.

Canonical complete journal-row SHA-256: `9c0affe06e5756b65f966b21b42a4a92a747a4bb210a25ffb6ec2ed0c3e7e315`.

### trade-current-period-order-r1

**PASS for this completed row.**

Preserves one route A proposal for this period's additional good. A is currently eligible at price 2, cheaper than B at 3 and affordable from cash 28/reserved 0. Historical January 1 settlement and stock 1 are not counted as fulfillment of January 2-3 demand; no pending current-period duplicate exists. Rationale and all four consistent checks match the actual order_a proposal and retain supplier-consent contingency. The final explanation distinguishes the empty inbox from the nonempty ownOffers list with no pending current-period item.

Canonical complete journal-row SHA-256: `c7052a3a94a2c79acbe804b5529cf92ffd20c0b08611cb9af2168d76b3c6263d`.

## Method and preservation

Inputs were the live-output preregistration.json and journal.json. Case labels were used to distinguish corrections from controls; actor facts came from actorPayload. The saved actor inputs were checked against the previous study and were unchanged. No hidden originalSpec facts or discarded response contents were invented. No selected-reference requirement was imposed on v3; scope bindings are not citations or proof of semantic truth. Metadata-removal claims refer to the raw model response before canonical server fields are added.

ResultHash covers the entire corresponding journal row using recursive NFC normalization of string keys/values, UTF-8 JSON with sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, and SHA-256. The manifest digest was independently recomputed with the same standard-library-only procedure excluding manifestHash.

- Raw preregistration.json SHA-256: `ff9941eb4cf81bba4fe67ddfb42b4b39b79ba5438999a6fc6bb29c39017802e8`.
- Raw journal.json SHA-256: `8746bdb876e17023344deff04e912b0f213bd793f0bbd6e0749e15b6c86f74fe`.

Only check-verdicts/review-draft.json and review-draft.md were written. The live output, journal, manifest, report, source, budget and earlier phases were left unchanged. No application imports, SQLite, tests, provider calls, delegation or further runtime work occurred. The coordinator owns final review placement and report/budget closeout.
