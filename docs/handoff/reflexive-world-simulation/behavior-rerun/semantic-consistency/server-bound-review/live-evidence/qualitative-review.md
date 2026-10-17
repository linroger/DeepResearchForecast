# Phase 10 actor-consistency-v2: independent qualitative review

Reviewer: Epicurus (independent-agent).

Manifest: `1c120c359ba91644ec3713048a513d7c8138f9584735b98e252e085d5007986a`.

## Bounded verdict

Eleven completed rows were independently reviewed against their saved actor observations, candidates, final decisions, state updates, and all four compact assessment explanations. Nine pass the combined decision-and-assessment qualitative review. Two fail for factual/temporal overstatements in their conditional_timing explanations, while their final actions and rationales remain correct. All eleven stored consequential-action matches remain true and unchanged. One additional call failed consistency_unresolved; the denominator stays twelve.

The completed investment mismatch repetition corrects 3/3 to 2 goods for 2 currency. The other investment mismatch repetition is unresolved and receives no assumed decision or reason credit. Both completed premature-coalition-opposition revisions remove the vote and correctly wait now; one has the unsupported full-period explanation noted below. All eight completed positive-control repetitions preserve their valid consequential choices; one investment-control assessment incorrectly denies an existing conditional objective.

This is not a passing twelve-case diagnostic gate, a full-world gate, promotion approval, or a calibration result. No claim of a reliable improvement across phases follows from this bounded directed replay. Prior phases and their judgments remain separate.

## V2 scope and semantic review

V2 intentionally contains no objectiveIndices, intentIndices or evidencePaths. Their absence is not a defect, and this review does not manufacture citations or carry over v1 reference-field requirements. Server hashes identify the complete input/output scope; they do not establish which facts the model considered or prove its prose. The two failures below arise from the natural-language explanations themselves when compared with the actual actor observation. Reviewer source locations below are locators into saved JSON, not model-selected citation claims.

All 44 completed semantic explanations were read: goal_alignment, conditional_timing, quantity_consistency and explanation_consistency for each of eleven rows. The review includes rationale, submitted intents, beliefs/plans, resource arithmetic, pending-offer conditions, historical settlements and consent distinctions.

## Concrete findings

1. **investment-consistent-current-purchase-r0 — existing condition described as nonexistent.** At journal.json cases["investment-consistent-current-purchase-r0"].assessment.checks[1].explanation, the conditional_timing check says: "No priority rules or conditional triggers exist, so none apply." The actor priorityRules array is empty, but actorPayload.observation.actor.objectives[0] explicitly requires waiting if an unexpired matching own offer is pending. That condition exists but is not active because the visible prior offers are accepted and settled. The 4/4 purchase remains correct; the blanket explanation of conditional obligations is inaccurate.

2. **coalition-opposition-before-trigger-r1 — current observation extended to an entire period.** At journal.json cases["coalition-opposition-before-trigger-r1"].assessment.checks[1].explanation, the check says: "Period is [2030-01-01, 2030-01-02). coalition_ab='none' throughout". The actor observation establishes world.relations.coalition_ab.value="none" at simulatedAt="2030-01-01T00:00:00.000000Z". periodEnd bounds the decision period; it does not guarantee unchanged relations until January 2. There is no such guarantee in the visible payload. Waiting now is correct, but the whole-period factual claim is unsupported. This finding does not assert that a coalition actually forms later.

No other material fact/goal/time/arithmetic/intent-coherence issue was found in the completed rows. In particular, trade-current-period-order-r0 discusses its raw submitted intent having no server metadata; canonical server-added actor/intent IDs in the persisted decision are not treated as model-authored claims.

## Coverage and denominator

| Context | Completed / attempted | Correct consequential choices | Qualitative passes / completed |
|---|---:|---:|---:|
| Investment rationale/action disagreement | 1/2 | 1 | 1/1; r1 unresolved |
| Coalition opposition before trigger | 2/2 | 2 | 1/2; r1 temporal overclaim |
| Investment consistent current purchase | 2/2 | 2 | 1/2; r0 denies existing condition |
| Coalition wait before trigger | 2/2 | 2 | 2/2 |
| Coalition opposition after trigger | 2/2 | 2 | 2/2 |
| Trade current-period order | 2/2 | 2 | 2/2 |

## Unresolved call retained

`investment-rationale-action-disagreement-r1` remains status `failed`, errorCode `consistency_unresolved`, with saved message "The bounded revision did not produce an admissible response.". Known usage is USD 0.008440000000 and 3410 tokens.

The failed row contains no retained final decision or assessment explanations. The recorded code establishes that the response did not clear consistency admission; it does not expose the unresolved semantic reason or justify giving its proposed action credit. No content is reconstructed from passing sibling rows. No qualitative-review entry is created for it, and it remains part of twelve attempted calls.

Journal actual/exposure totals USD 0.088024000000, including the unresolved call; unknown exposure is zero. These are saved metering values, not an independent provider billing reconciliation.

## Per-row review and canonical bindings

### investment-rationale-action-disagreement-r0

**PASS.**

Corrects the retained 3/3 action versus 2/2 rationale mismatch. Visible capacity 3 minus 1 gives quantity 2 and total price 2; cash 28/reserved 0 covers it and the purchase input bounds permit both. The prior 2/2 offer is accepted with a settled January 1 commitment, not a pending duplicate during January 2-3. Final action, rationale, and all four compact explanations agree. The abbreviated historical interaction ID appears only in prose and identifies the visible prior offer; no new consent, reservation, or settlement is asserted.

Canonical complete journal-row SHA-256: `b97e74b355afd94c29559e9c807bd2b1b9a6c29c4b4e0837799a9ab82f5d847d`.

### coalition-opposition-before-trigger-r0

**PASS.**

Corrects premature opposition by removing the candidate vote and waiting while coalition_ab is currently none. The objective requires an opposing vote only when allied; current inbox, offers, commitments and observed events are empty. The added belief accurately timestamps the current none state, and the added plan keeps voting conditional on a future allied observation. All four explanations agree with the final wait, visible budget 80/reserved 0 and the current trigger; no unavailable capability or future state is invented.

Canonical complete journal-row SHA-256: `402d2288367d11a3d5af71227a54a9ac53fea8477f7f3b2862c26494ce545446`.

### investment-consistent-current-purchase-r0

**FAIL: conditional-timing explanation; action remains correct.**

The valid control action is preserved: quantity 4/total price 4 matches capacity 5 minus 1, is affordable from cash 25/reserved 0, and does not duplicate the prior accepted/settled 2/2 and 3/3 offers. Rationale and the other checks are consistent. However, conditional_timing says 'No priority rules or conditional triggers exist, so none apply.' priorityRules is empty, but actor.objectives[0] explicitly contains the matching-pending-offer wait condition. That condition exists and is currently unmet; the explanation incorrectly denies its existence. This is an assessment factual/conditional-reasoning defect, not an incorrect purchase action.

Canonical complete journal-row SHA-256: `ccdf7463509a8b2a800ff576dfd15ed3a97f905d1cc10c14be622a504543e885`.

### coalition-wait-before-trigger-r0

**PASS.**

Preserves the valid empty-intent wait. coalition_ab is none at the January 1 observation, so the allied vote trigger is not met. Empty inbox/offers/commitments/events and budget 80/reserved 0 support the rationale and four explanations. The decision neither casts a premature vote nor claims a restriction on the available voting capability. No material goal, time, arithmetic, or explanation inconsistency found.

Canonical complete journal-row SHA-256: `2ce9f3a78dcbe55ed4eb656d27c5fb4b4670799c36d7231b356d713284d9a60a`.

### coalition-opposition-after-trigger-r0

**PASS.**

Preserves the valid own opposing vote once coalition_ab is allied. The sole program_vote/execute intent has support false and matches the current conditional objective. Visible weights 35/15/50, passage threshold 60 and budget 80/reserved 0 support the numerical statements; empty inbox/offers support the absence of other pending work. All four compact explanations agree with the final intent and do not claim that new funding, consent, or settlement has occurred.

Canonical complete journal-row SHA-256: `66d2da59f02d3e08fe876b0ce9c72b5b5150dc448696b5e3e19b2ed61a1826ad`.

### trade-current-period-order-r0

**PASS.**

Preserves one current-period order_a proposal. Both routes are eligible; A costs 2 versus B's 3, and cash 28/reserved 0 covers one good. The accepted-and-settled January 1 order is historical relative to January 2-3 and not a pending duplicate. Rationale, all four explanations, and the added plan to await supplier_a and avoid duplicates agree with the objective; supplier consent remains contingent. The explanation's no-server-metadata phrase concerns the submitted raw intent; server-added IDs in the saved canonical decision are not model-selected evidence or a contradiction.

Canonical complete journal-row SHA-256: `c500255d3bef32237008809c7e96fd92e707d694708cdedb03eb73b801486068`.

### coalition-opposition-before-trigger-r1

**FAIL: conditional-timing explanation; action remains correct.**

The final decision correctly removes the premature opposing vote and waits while coalition_ab is currently none; rationale explicitly waits for a future observation. However, conditional_timing states: 'Period is [2030-01-01, 2030-01-02). coalition_ab='none' throughout'. The saved observation establishes none at simulatedAt January 1 only; it contains no guarantee that the relation persists for the entire ensuing period. This unsupported full-period claim fails the requested temporal-explanation review even though waiting now and the other three explanations are consistent. No hidden future event or actual later state is assumed.

Canonical complete journal-row SHA-256: `32de0489cdc752e2f97a204b13cb7559224599ff811c86d94d6b572ff7923aea`.

### investment-consistent-current-purchase-r1

**PASS.**

Preserves the valid 4/4 purchase control: capacity 5 minus 1 equals quantity 4 and total price 4; cash 25/reserved 0 covers it, within visible bounds. Prior commitments settled on January 1 and 2 are historical at January 3, and no matching pending offer activates the wait condition. All four explanations, the rationale, and the added dated belief agree with the final proposal. Consent is correctly contingent; no new settlement or reservation is claimed.

Canonical complete journal-row SHA-256: `cd9dd663d28955b58ec86eb69e3270ff0b0dcf5bd22eb7e0bc5633746d576d95`.

### coalition-wait-before-trigger-r1

**PASS.**

Preserves the valid wait while the visible coalition relation is none. The final empty intents and rationale respect the objective's allied condition. Current budget 80/reserved 0, empty inbox/offers/commitments, and lack of scheduled obligations support all four explanations. The statement that the relation remains none is read at the current observation, without an explicit whole-future-period guarantee. No material action, goal, timing, arithmetic, or explanation mismatch found.

Canonical complete journal-row SHA-256: `8f3d0800057a2bf5dc766eb7f3510ea2bbac42b9e34fe61a6fd022d4edc19f98`.

### coalition-opposition-after-trigger-r1

**PASS.**

Preserves the valid own opposing vote when coalition_ab is allied. The final support=false vote and all four explanations match current time and objective. With visible A/B/C weights 35/15/50 and threshold 60, A+B sum to 50, so C's opposing choice prevents reaching that threshold under the stated voting rule. This supports the budget-preservation rationale without assigning C authority over others. Empty inbox/offers and budget 80/reserved 0 are accurately described; no completed funding outcome is asserted.

Canonical complete journal-row SHA-256: `f5c9bec8e1b276fc813c78246120b16143881cef2f1a9bcbe76ef6325df973f8`.

### trade-current-period-order-r1

**PASS.**

Preserves the valid current-period route A order: one additional good at price 2 rather than eligible route B's 3, affordable from cash 28/reserved 0. The January 1 settled order and stock balance 1 are historical, so the recurring-demand objective calls for a new proposal during January 2-3; no pending current-period duplicate exists. Final action, rationale, dated belief and all four explanations agree, retaining supplier-consent contingency and no unsupported settlement or priority-change claim.

Canonical complete journal-row SHA-256: `d88fc7397e33acfb6006622a53a6f156daf3212d0c52db630629ce039f5081fc`.

## Evidence and method

Inputs: [preregistration.json](preregistration.json) and [journal.json](journal.json). All twelve actorPayload observation/candidate objects were checked against Phase 9 and are identical; the eleven completed v2 outputs were read anew. No hidden originalSpec fields or expected-case answers were used as actor evidence. Stored matches=true was kept separate from independent qualitative judgment.

Result hashes cover the entire saved journal row using recursive NFC normalization of string keys and values, UTF-8 JSON with sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, and SHA-256. The manifest hash was independently recomputed with the same standard-library-only procedure excluding manifestHash.

- Raw preregistration.json SHA-256: `add05455cd341cc73f7dba1a3111a23d923881d6b8c4be19203ada9b983e8297`.
- Raw journal.json SHA-256: `df6363c542a7c17c81cc93daed6220cdfdedf87bff83a8f7d0aed376fdb276df`.

Only qualitative-review.json and qualitative-review.md were written. Manifest, journal, source, ledger, prior evidence, and report were not edited. No application imports, SQLite, test execution, provider calls or delegation were used. The coordinator owns report/budget closeout; no further paid replication is requested by this review.
