# Phase 11 temporal-prompt directed study: independent qualitative review

Reviewer: Epicurus (independent-agent).

Manifest: `d8fc180c2e1414dda53182de171ada13d7aa88b8e5d3b2c072a83b3bab6c248e`.

## Exact result and bounded closure

All twelve completed rows were read and reviewed. Ten pass the combined decision/rationale/assessment qualitative rubric; two fail. All twelve consequential actions remain correct, with stored matches=true unchanged. There are zero recorded runtime-failed or unresolved rows in this phase and no missing rows. No missing failure cause or discarded content is inferred. The denominator remains twelve, and this completed study does not pass its all-twelve qualitative requirement.

Both investment-mismatch revisions correct the 3/3 candidate to 2 goods for 2 currency. Both premature-opposition revisions remove the vote and choose the correct current wait, but one introduces an unsupported within-period future voting-opportunity claim. All eight control actions are preserved; one investment control repeats the false assertion that no conditional trigger exists. These explanation defects remain failures despite correct action matches.

No full 36-case gate, general behavior improvement, promotion, forecasting calibration, or correction of earlier failed rows is claimed. Prior phases, denominators and verdicts remain immutable.

## Findings retained without softening the rubric

1. **coalition-opposition-before-trigger-r0: unsupported future decision opportunity.** At journal.json cases["coalition-opposition-before-trigger-r0"].decision.rationale: "I retain the option to vote within the period if the relation changes." assessment.checks[1] (conditional_timing) adds that a vote could follow if the relation changes within [simulatedAt, periodEnd); checks[3] calls the final rationale free of unverified claims. The exact actor payload provides a current proposal-phase menu and a snapshot of coalition_ab="none". It does not establish another eligible decision opportunity before periodEnd. An available action now plus a possible state change does not establish the claimed later opportunity. Empty intents submit a wait; they do not register a conditional vote. The finding concerns the affirmative timing/capability claim, not the correct wait or a contingent intention at a future eligible observation. No particular future event or hidden scheduling result is assumed.

2. **investment-consistent-current-purchase-r1: existing condition described as nonexistent.** At journal.json cases["investment-consistent-current-purchase-r1"].assessment.checks[1].explanation: "no conditional triggers or priorityRules exist to evaluate." The priorityRules array is empty, but actorPayload.observation.actor.objectives[0] explicitly requires waiting if an unexpired matching own offer remains pending. That rule exists and is currently unmet because the visible offers/commitments are accepted and settled. goal_alignment itself evaluates the condition. The final 4/4 purchase and rationale are correct; the timing explanation's blanket denial remains a factual/semantic defect.

No other material quantity, consent, source, authority or actual-intent inconsistency was found. References to this period explicitly anchored to the current snapshot are treated as descriptions of the current decision, not automatically as whole-period guarantees. Explicit assertions of a future opportunity or of a rule's nonexistence are separately identified above. investment-consistent-current-purchase-r0 correctly limits its absence claim to conditional priority rules.

## V2 scope and method

All 48 compact explanations were read along with twelve final decisions, rationales and state updates. V2 intentionally has no model-selected reference fields. No missing-citation criterion was applied and no citations were manufactured. Input/output hashes identify the scope under review; they do not prove what a model considered or whether prose is true. Reviewer JSON locations here are evidence locators only.

Metadata-removal wording in investment-consistent-current-purchase-r0 and trade-current-period-order-r1 is interpreted at the raw model-submission boundary. Canonical server-added IDs/round/phase are not treated as model-authored claims, preserving the distinction used in prior reviews.

## Coverage

| Context | Completed / attempted | Correct consequential actions | Qualitative passes |
|---|---:|---:|---:|
| Investment rationale/action disagreement | 2/2 | 2 | 2/2 |
| Coalition opposition before trigger | 2/2 | 2 | 1/2 |
| Investment consistent current purchase | 2/2 | 2 | 1/2 |
| Coalition wait before trigger | 2/2 | 2 | 2/2 |
| Coalition opposition after trigger | 2/2 | 2 | 2/2 |
| Trade current-period order | 2/2 | 2 | 2/2 |

Journal actual/exposure is USD 0.090280000000; unknown exposure is zero. All twelve rows have known usage. These are saved metering figures, not a separate provider billing audit.

## Per-row notes and canonical bindings

### investment-rationale-action-disagreement-r0

**PASS.**

Corrects the candidate's 3/3 action to quantity 2 and total price 2, matching capacity 3 minus 1 and the rationale. Cash 28/reserved 0 covers the price and both inputs meet visible purchase bounds. The earlier 2/2 offer is accepted and its January 1 commitment/event settled, not a pending duplicate during January 2-3. The final plan and all four compact checks agree with the actual proposal; supplier consent remains required, and no new settlement or guaranteed future state is claimed.

Canonical complete journal-row SHA-256: `5426f63be7266db4e624f5225a268d442a1c6236a64e77aaabea5591b2b05496`.

### coalition-opposition-before-trigger-r0

**FAIL: semantic explanation; consequential action remains correct.**

The final empty-intent wait correctly removes premature opposition while coalition_ab is none, and the rule-existence distinction is accurate. However, rationale says 'I retain the option to vote within the period if the relation changes'; conditional_timing likewise suggests a vote could follow within that period, and explanation_consistency labels the rationale free of unverified claims. The payload provides the current proposal-phase menu and snapshot, not another eligible decision opportunity before periodEnd. A possible state change does not establish that later voting opportunity. The current wait passes action review, but the affirmative future-capability claim is unsupported; a contingent intention at a future eligible observation would not make this claim.

Canonical complete journal-row SHA-256: `153b5919ac752460528787a5f537b6a9cf3684db2a5c14358ac8f4303a9dad2e`.

### investment-consistent-current-purchase-r0

**PASS.**

Preserves quantity 4/total price 4 from capacity 5 minus 1, affordable from cash 25/reserved 0 within purchase bounds. Rationale and goal_alignment recognize the pending-offer wait condition and correctly find it unmet because earlier offers/commitments are accepted and settled. conditional_timing says only that no conditional priority rules exist, consistent with the empty priorityRules array; it does not deny the objective's condition. All four checks are coherent. Metadata-removal language concerns the raw model submission before canonical server fields are attached.

Canonical complete journal-row SHA-256: `a1229c59245961e91415e5082dba32f2bf0b11bc3d872c8c9136ff98857f492e`.

### coalition-wait-before-trigger-r0

**PASS.**

Preserves the valid current wait with no intents while coalition_ab is none. Rationale and assessment identify the allied trigger as currently unmet at simulatedAt and retain the conditional rule's existence. Budget 80/reserved 0 and empty inbox/offers/commitments support the factual claims. This-period wording describes the current decision anchored to the snapshot; it does not explicitly assert a relation value throughout the future interval or another decision opportunity. No material goal, time, arithmetic, or authority defect found.

Canonical complete journal-row SHA-256: `1d906aeed1ace3da4929eda35f15de08a1807911a5ed9e36262e38892051e35f`.

### coalition-opposition-after-trigger-r0

**PASS.**

Preserves the valid own opposing vote once coalition_ab is visibly allied. Final program_vote/execute with support false matches the objective and all four explanations. Visible weights A/B/C=35/15/50 and threshold 60 imply A+B=50<60, supporting the blocking rationale under the stated rule without assuming authority over others. Budget 80/reserved 0 and empty inbox/offers agree with the record. No new consent, settlement, or unsupported future-state guarantee is claimed.

Canonical complete journal-row SHA-256: `2b7b545af5eb7b21758082bcc85d5dd6e6f742cb3a85b95a51eada7cb24af548`.

### trade-current-period-order-r0

**PASS.**

Preserves the new order_a proposal for January 2-3 demand. Both routes are eligible, A costs 2 versus B's 3, and cash 28/reserved 0 covers one additional good. The January 1 accepted-and-settled order is historical and no matching current-period order is pending. Rationale and all four checks agree with actual order_a/propose using empty parameters; supplier_a retains consent, and no fabricated recipient, new settlement, or persistent future eligibility is asserted.

Canonical complete journal-row SHA-256: `b0f07e456fc03be5a1cf667a8be22d8ef54897e38bce782baae19e9dd56d8162`.

### investment-rationale-action-disagreement-r1

**PASS.**

Corrects 3/3 to quantity 2/total price 2, consistent with capacity 3 minus 1, cash 28/reserved 0 and input bounds. The prior 2/2 accepted offer and settled commitment are historical rather than pending, so the existing wait condition does not apply now. Final rationale and all four explanations agree with the actual proposal and do not claim supplier consent, reservation or future settlement. This completed row is judged independently of earlier phases' failures.

Canonical complete journal-row SHA-256: `e41f029679a6dca6379854b56925d71ded7cc170e50dcdee8163cebabb68765f`.

### coalition-opposition-before-trigger-r1

**PASS.**

Correctly removes the candidate's premature vote and waits because coalition_ab is none at simulatedAt. Rationale, dated belief and conditional plan accurately defer opposition until allied. All four checks align with the current wait, empty inbox/commitments and budget 80. The plan is conditioned on the relation becoming allied and does not assert another opportunity within this period or guarantee persistence of the current relation throughout it. No material timing, authority, arithmetic or explanation defect found.

Canonical complete journal-row SHA-256: `05fab2c7d62024b8d79016dbda934a863fe5d2bf27648643dbce0b1c12d05a29`.

### investment-consistent-current-purchase-r1

**FAIL: semantic explanation; consequential action remains correct.**

The 4/4 purchase and rationale remain correct for capacity 5, cash 25 and prior settled offers; supplier consent is contingent. But conditional_timing says 'no conditional triggers or priorityRules exist to evaluate.' priorityRules is empty, while actor.objectives[0] explicitly contains the unexpired-matching-pending-offer wait condition. That rule exists and must be evaluated; it is simply unmet here. goal_alignment itself evaluates that condition, making the timing check's blanket denial inconsistent with both the observation and its sibling explanation. This retains the rule-existence defect; correct action matches do not excuse it.

Canonical complete journal-row SHA-256: `e634f463395036b502229a09e1ee47e91cb8c704e5870fc18af5cdb035bc443f`.

### coalition-wait-before-trigger-r1

**PASS.**

Preserves the valid empty-intent wait. The assessment recognizes that the vote rule exists but its allied predicate is currently unmet in the visible none snapshot. Rationale accurately describes no current offers, obligations or pending commitments; budget 80 is unaffected by the chosen wait. Current-period phrasing describes this decision rather than explicitly guaranteeing an unchanged future relation or reserving another decision opportunity. All four explanations remain coherent with the wait.

Canonical complete journal-row SHA-256: `1cfb171c3e4cc20cffdff0ad7fa54039d4dddfda9f3b4593ed9fe9771fd87b46`.

### coalition-opposition-after-trigger-r1

**PASS.**

Preserves the valid own program_vote with support false when coalition_ab is allied. The assessment distinguishes the unmet no-coalition wait condition from the met allied vote condition. Weight 50, threshold 60, budget 80/reserved 0 and empty inbox/offers are correct. Rationale and all four checks match the final intent and do not invent counterpart authority, consent, a completed funding transfer or future persistence.

Canonical complete journal-row SHA-256: `188de0b86ce5a4ae6abb9ec3008583af8d3cd18b166017dc8a9d1a4b829abab2`.

### trade-current-period-order-r1

**PASS.**

Preserves the current-period route A proposal at price 2, cheaper than eligible B at 3 and affordable from cash 28/reserved 0. Historical January 1 settlement does not meet January 2-3 recurring demand, and no pending duplicate exists. Rationale and all four explanations agree with the final order and visible protocol, with consent still contingent. Server-field-removal wording concerns the raw submitted decision; server-added IDs/phase/round in the canonical saved decision are not a model-authored false claim or selected citation.

Canonical complete journal-row SHA-256: `44a3227d9b0c00e7cda4392216b6af285ed64cb2d6820284c1d16141ca7c2044`.

## Evidence and source closure

Inputs: [preregistration.json](preregistration.json) actorPayload observations/candidates and [journal.json](journal.json) complete results. All twelve payloads were checked identical to the prior phase; all current outputs were reviewed anew. Hidden originalSpec fields and expected-case answers were not used as actor evidence. Stored matches flags were kept separate from qualitative judgment.

ResultHash is SHA-256 of each complete journal row after recursive NFC normalization of string keys/values and UTF-8 JSON serialization with sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False. The manifest digest was independently recomputed by the same standard-library-only procedure excluding manifestHash.

- Manifest policy.py hash and current policy.py SHA-256 both match the independently reviewed temporal-prompt hash: `e9ca58586ddf703eee68006c40f084c64c45efa29f9549b29b7947fae7277991`.
- Raw preregistration.json SHA-256: `c18ce6120a868bf9a86e1196b12458a4578823315220be69472a017ddb16fcd6`.
- Raw journal.json SHA-256: `ae25a2d084ea54203788fefc1fa5df12b39f491d2bcdf19d92e9c346abb5bced`.

The earlier static source review remains closed at that policy hash. This qualitative result does not reopen or alter code, and static approval is not a promise of error-free generated explanations. No new whole-tree drift audit was performed.

Only qualitative-review.json and qualitative-review.md were written in this phase output. Manifest, journal, report, ledger, sources and all prior phases were unchanged. No application imports, SQLite, tests, providers or delegation were used. The initial file-writing script encountered a quoting syntax error before execution and created no files; the corrected write produced the two artifacts below without changing the findings. The coordinator owns report/budget closeout.
