# Phase 8 directed consistency replay: independent qualitative review

Reviewer: Epicurus (independent-agent).

Manifest: `9969cb8b2f3cdb2e3d638ba07e74775398af67975fe7c773bfd02390451a34f1`.

## Bounded verdict

All nine completed final decisions and assessments pass this qualitative review against their exact saved actor observations and candidates. The denominator remains twelve attempted revision calls: nine completed and three known failures. This is not a passing twelve-case gate, a fresh-generation study, a full-world causal evaluation, promotion approval, or a calibration claim.

Both retained errors are corrected in their one completed repetition each: investment-rationale-action-disagreement-r1 changes the action from 3 goods/3 currency to 2/2 and aligns its rationale and belief; coalition-opposition-before-trigger-r0 replaces the premature opposing vote with an explicit wait while coalition_ab is none. Each of these contexts also has one failed repetition, so neither has two demonstrated successful corrections.

All seven completed repetitions of the four positive-control contexts preserve their valid consequential choices. The investment 4/4 control has one completed and one failed repetition; coalition wait, coalition opposition after the trigger, and trade route A each have two completed repetitions.

No material remaining explanation/action mismatch, wrong conditional timing, arithmetic error, fabricated consent, or new-settlement claim was found among the nine completed rows. One minor wording imprecision is retained in the per-row note: coalition-wait-before-trigger-r0 says "Both objectives" for two clauses of its single objective; it adds no new goal and does not change the verdict.

## Coverage and denominator

| Context | Qualitatively accepted / attempted | Completed behavior |
|---|---:|---|
| Investment rationale/action disagreement | 1/2 | r1 corrects 3/3 to 2/2; r0 failed validation. |
| Coalition opposition before trigger | 1/2 | r0 waits with coalition none; r1 failed validation. |
| Investment consistent current purchase | 1/2 | r0 preserves 4/4; r1 failed validation. |
| Coalition wait before trigger | 2/2 | Both retain empty intents while coalition is none. |
| Coalition opposition after trigger | 2/2 | Both retain own opposing vote when allied. |
| Trade current-period order | 2/2 | Both retain the new route A proposal for current demand. |

The journal records twelve actual calls with known usage totaling USD 0.102994000000; unknown exposure is zero. Known failed-call usage is USD 0.028964000000, included in the total. These are journal metering figures, not an independent billing reconciliation.

## Failed rows retained without inferred causes

- `investment-rationale-action-disagreement-r0`: `invalid_assessment`, known cost USD 0.010612000000, tokens 3860.
- `coalition-opposition-before-trigger-r1`: `invalid_assessment`, known cost USD 0.006988000000, tokens 2434.
- `investment-consistent-current-purchase-r1`: `invalid_assessment`, known cost USD 0.011364000000, tokens 4644.

The failed rows retain no final decision, assessment, or detailed validation message. They receive no qualitative-review entry and no assumed correction or preservation credit. This review does not infer the missing validation reason or the contents of a discarded response.

## Per-row findings and bindings

### coalition-opposition-before-trigger-r0

**Verdict: pass for this completed row.**

Corrected the retained premature-opposition error. observation.actor.objectives[0] requires waiting while coalition_ab is none; world.relations.coalition_ab.value is none. The final decision removes the candidate's opposing vote, submits no intents, and explains the unmet allied trigger. Empty inbox/ownOffers/commitments support the absence of pending obligations. The four assessment checks align with this final wait; no resource expenditure, fabricated restriction, or premature outcome is claimed.

Canonical journal-row SHA-256: `dd1ae07275ebf4bf529f4ec2c1ff61ec571c07d45561d3df2989323feb241c14`.

### investment-consistent-current-purchase-r0

**Verdict: pass for this completed row.**

Preserved the valid purchase control: capacity 5 minus 1 yields quantity 4 for total price 4, exactly matching the final purchase/propose intent, rationale, and assessment. buyer_cash is 25 with 0 reserved; both terms are within visible input bounds. Prior 2/2 and 3/3 offers are accepted and their commitments/events show historical settlement, so neither is a pending duplicate. The current proposal remains contingent on producer consent, with no new settlement claim.

Canonical journal-row SHA-256: `ee46e98ffb9512bd4f3f70f4e0e99f6fa5223ce600d991bea75fb9b0ed677b1c`.

### coalition-wait-before-trigger-r0

**Verdict: pass for this completed row.**

Preserved the valid wait control. coalition_ab is none, program_authorized is false, and the objective's allied condition is unmet. Empty intents and the rationale respect that condition; the assessment explicitly distinguishes choosing to wait from lacking a voting capability. Budget 80/reserved 0 and empty inbox/offers/commitments support the factual claims. Minor wording: 'Both objectives' describes clauses of the single supplied objective, without introducing a different goal or changing the decision.

Canonical journal-row SHA-256: `79b2b4bf21dc1f359db4026b9a6f4f06302a60a162bb80c2d4ad51b4f899688e`.

### coalition-opposition-after-trigger-r0

**Verdict: pass for this completed row.**

Preserved the valid opposing-vote control. coalition_ab is allied in the current January 2-3 period, activating the objective's vote condition; the final sole intent is program_vote/execute with support false. The visible description gives A/B/C weights 35/15/50 and threshold 60, so A+B=50 cannot reach passage without C's support. The budget-preservation explanation is consistent with those rules and makes no claim that a new settlement has already occurred. Assessment and final intent agree.

Canonical journal-row SHA-256: `6e1c35dd1a91ce03a87f4edcaa0dc9e70cddd252cb31e431fc71e8580114d69b`.

### trade-current-period-order-r0

**Verdict: pass for this completed row.**

Preserved the valid current-period route A proposal. Both eligibility rules are true; visible prices are A=2 and B=3, and importer_cash is 28 with 0 reserved. The prior accepted order's commitment and dated settlement event are January 1, before the current January 2-3 period; the objective requires an additional good now, with no pending current-period duplicate. Final order_a/propose with empty parameters matches the option, candidate, rationale, and assessment, and remains subject to supplier consent.

Canonical journal-row SHA-256: `f621c66cd17db9873b835a91336ba5ec84838a15b4f85cf47bab6501d8d54ee6`.

### investment-rationale-action-disagreement-r1

**Verdict: pass for this completed row.**

Corrected the retained action/rationale mismatch: the candidate's purchase terms 3/3 become quantity 2 and total price 2, consistent with visible capacity 3 minus 1. buyer_cash 28/reserved 0 covers the price and both inputs meet visible bounds. The earlier 2/2 offer is accepted and its commitment/event show historical settlement, so the pending-offer wait condition does not apply. Final rationale, added belief, and all assessment checks agree with the revised proposal and do not claim new consent or settlement.

Canonical journal-row SHA-256: `528bc5834c3f9f6436f4a4c1f31b93de4700686058689c52c1eca2f44a72557a`.

### coalition-wait-before-trigger-r1

**Verdict: pass for this completed row.**

Preserved the valid wait control. The single objective requires waiting while coalition_ab is none, as observed; the final decision has no intents and explains the inactive vote trigger. Budget 80/reserved 0, program_authorized false, and empty inbox/offers/commitments support the rationale and assessment. Voting remains an available choice rather than a falsely asserted missing capability. No material goal, timing, arithmetic, or explanation conflict found.

Canonical journal-row SHA-256: `f356b43c17d3ffcf5fbb680ed1244bab11781bb0e6d9f22863f819f9f7316fec`.

### coalition-opposition-after-trigger-r1

**Verdict: pass for this completed row.**

Preserved the valid opposing-vote control after coalition_ab becomes allied. The final sole program_vote/execute intent has support false and is correctly timed to the current observation. Visible weights 35/15/50, threshold 60, and budget 80 support the numerical statements; C's weight 50 alone is below the passage threshold. Rationale describes the submitted opposing vote and the empty inbox/offers accurately. No counterpart authority, already-achieved funding result, or invented condition is claimed.

Canonical journal-row SHA-256: `e448f50fdb02f940024b841793c4e56d8348c92dc217fccc924527642bfb1486`.

### trade-current-period-order-r1

**Verdict: pass for this completed row.**

Preserved the valid current-period route A proposal. The January 1 accepted-and-settled order is historical relative to January 2-3 and does not meet the explicit recurring demand. Both routes are eligible, A costs 2 versus B's 3, and cash 28/reserved 0 covers the proposed order. Stock 1 and the settled commitment/event support the historical account statements. Final action, rationale, and assessment agree on one new order_a proposal subject to supplier consent, without claiming it has settled.

Canonical journal-row SHA-256: `d181c2269ab4a29af0d0c22842e545f59d1ca5541e92f0ff22d715b0bd55189d`.

## Evidence and method

Inputs: [preregistration.json](preregistration.json) (`cases[].actorPayload.observation` and `candidateDecision`) and [journal.json](journal.json) (`cases[evaluationId].decision`, `assessment`, and row accounting). All nine completed decisions, their state updates, and all four assessment checks per row were read. Repeated contexts were checked to have identical saved actor payloads. Verdicts came from the visible objectives, time bounds, actions, account values, offers, commitments, and events, not the stored `matches` flag or hidden scenario data.

Each resultHash covers the complete corresponding journal row using recursive NFC normalization of string keys/values and UTF-8 JSON with sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, followed by SHA-256. The manifest digest was independently recomputed using the same standard-library-only procedure, excluding manifestHash. No application modules, SQLite, providers, tests, or delegates were used.

- Raw preregistration.json SHA-256: `e50cb753ae96997552710d6ad89993a7ba37af80b13d0ea897a41db953f474b7`.
- Raw journal.json SHA-256: `60a956f599339db35104bfa44a35b51e98263b7a624e4db6174656ba823d0840`.

Only qualitative-review.json and qualitative-review.md were written. Source files, manifest, journal, original receipts, budget ledger, and report were not edited. The coordinator owns budget/report closeout.
