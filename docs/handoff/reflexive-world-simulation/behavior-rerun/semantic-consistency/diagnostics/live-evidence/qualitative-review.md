# Phase 9 directed diagnostic replay: independent qualitative review

Reviewer: Epicurus (independent-agent).

Manifest: `68a737cf23135ddb84310c35c69fce5cac14f7485159a30e42f09317695c0b89`.

## Bounded verdict

Twelve revision calls were attempted. Ten completed with correct consequential-action matches, and two failed. All ten completed actions and rationales are consistent with their saved observations. Six completed rows pass the combined decision-and-assessment qualitative review; four investment rows fail because their model-selected evidence paths cite the communicate option while discussing purchase inputs or the purchase option. The action matches remain true and are not rescored.

The qualitative passed flag covers the requested review of both final decisions and assessments. A path that resolves is not necessarily relevant evidence: the four failures below distinguish correct behavior from incorrect action-schema references. This review does not impose a new runtime validation rule or change the scorer.

Investment action/rationale disagreement is corrected in both completed repetitions: final quantity and total price are 2/2, consistent with capacity 3 minus one. Both repetitions nevertheless retain an assessment-reference defect. The retained premature coalition-opposition context has zero completed responses in this phase; neither failed call receives correction credit. Its successful Phase 8 repetition is not substituted into this phase.

All eight completed positive-control repetitions preserve their consequential choices. The two investment controls have incorrect assessment references; the two coalition-wait, two coalition-opposition-after-trigger, and two trade controls pass qualitative review. No material remaining action/rationale, conditional-timing, arithmetic, consent, or settlement false claim was found in the ten completed decisions. One minor single-objective/two-clause wording imprecision is noted for coalition-wait-before-trigger-r1.

This phase remains incomplete on its twelve-call denominator and also contains four completed-row assessment-quality findings. It is not a passing gate. The actor observations/candidates match Phase 8 exactly; the diagnostic instrumentation does not establish a behavioral improvement. This is not a fresh-generation study, full-world causal result, promotion approval, or calibration claim.

## Coverage

| Context | Completed / attempted | Correct consequential choices | Qualitative passes / completed |
|---|---:|---:|---:|
| Investment rationale/action disagreement | 2/2 | 2 | 0/2: wrong option references |
| Coalition opposition before trigger | 0/2 | No accepted final decisions | 0/0: both calls failed |
| Investment consistent current purchase | 2/2 | 2 | 0/2: wrong option references |
| Coalition wait before trigger | 2/2 | 2 | 2/2 |
| Coalition opposition after trigger | 2/2 | 2 | 2/2 |
| Trade current-period order | 2/2 | 2 | 2/2 |

## Concrete assessment-reference findings

In every investment observation, options[0] is communicate with a text input; options[1] is purchase with quantity bounds 1-10 and price bounds 1-20. The following references therefore point to the wrong action even though they resolve structurally:

- investment-rationale-action-disagreement-r0: assessment.checks[0] (goal_alignment), evidencePaths[1] = ["options",0,"templateId"]; assessment.checks[2] (quantity_consistency), evidencePaths[2] = ["options",0,"inputs"].
- investment-consistent-current-purchase-r0: assessment.checks[2] (quantity_consistency), evidencePaths[2] = ["options",0,"inputs"].
- investment-rationale-action-disagreement-r1: assessment.checks[0] (goal_alignment), evidencePaths[2] = ["options",0,"inputs"].
- investment-consistent-current-purchase-r1: assessment.checks[0] (goal_alignment), evidencePaths[2] = ["options",0,"templateId"].

All referenced row locations are under journal.json cases[evaluationId]. The corresponding true option data is under preregistration.json cases[].actorPayload.observation.options. These are observed defects in completed assessments; they do not identify why either failed response was rejected.

## Failed calls and diagnostic limits

- `coalition-opposition-before-trigger-r0`: code `invalid_assessment`; saved message: "Assessment indexes must identify actual unique records"; known cost USD 0.007180000000; tokens 2466.
- `coalition-opposition-before-trigger-r1`: code `policy_invalid_response`; saved message: "The bounded revision did not produce an admissible response."; known cost USD 0.007036000000; tokens 2442.

The r0 message establishes only that the assessment index rule rejected the response. It does not identify which check, objectiveIndices versus intentIndices, or the bad type/value/duplicate. The r1 code is policy_invalid_response, not invalid_assessment; its generic message provides no narrower cause. Neither failed row contains a final decision/assessment or retained raw response. No missing contents, specific invalid index, malformed-JSON cause, or semantic success is inferred. Both failures stay in the twelve-call denominator and receive no qualitative-review entry.

Journal actual/exposure is USD 0.102118000000; unknown exposure is zero. USD 0.014216000000 of known usage belongs to the two failed calls and remains included. These figures describe journal metering, not independent provider billing.

## Individual review notes and bindings

### investment-rationale-action-disagreement-r0

**FAIL: assessment-reference accuracy; action remains correct.**

Final action and rationale correct the retained mismatch: capacity 3 minus 1 yields quantity 2/total price 2, within cash 28 and the purchase bounds; the earlier accepted offer is settled rather than pending. However, the assessment cites options[0].templateId in goal_alignment and options[0].inputs in quantity_consistency. Those resolve to communicate and its text schema, not purchase or its price/quantity bounds (options[1]). The final decision is behaviorally correct, but the model-selected evidence references misidentify its action schema, so the combined decision-and-assessment qualitative review fails.

Canonical full journal-row SHA-256: `702c2ea45549d7e0387b845085ea3aaad22cb7cdafe57899c71d4152126251e7`.

### investment-consistent-current-purchase-r0

**FAIL: assessment-reference accuracy; action remains correct.**

The final purchase control is preserved: quantity 4/total price 4 matches capacity 5 minus 1, cash 25 covers it, and historical accepted/settled 2/2 and 3/3 offers are not pending duplicates. Rationale correctly retains supplier consent. Assessment quantity_consistency nevertheless cites options[0].inputs while asserting purchase quantity 1-10 and price 1-20 bounds; this path resolves only to communicate's text input. Purchase bounds are at options[1].inputs. This is an assessment-reference defect, not an arithmetic or action-selection failure; qualitative review fails.

Canonical full journal-row SHA-256: `80141573d7b4ff2d67d9a5b014248fdeca10a904bc19eaac9872244618cb0c79`.

### coalition-wait-before-trigger-r0

**PASS.**

Preserved the valid wait control: coalition_ab is none, so the objective's allied trigger is unmet and final intents are empty. Budget 80/reserved 0, program_authorized false, and empty inbox/offers/commitments support the rationale and all four assessment explanations. The check's wording about not being allied is evaluated only in this observed none state; no broader policy for other relation states is inferred. No material timing, arithmetic, or explanation conflict is present.

Canonical full journal-row SHA-256: `9cf49c0ea3c23416656413d724bdd74a65725070a29abad8f9cb2d782f42fa3f`.

### coalition-opposition-after-trigger-r0

**PASS.**

Preserved the valid opposing-vote control: coalition_ab is allied now, and the final sole intent is program_vote/execute with support false. Objective timing, own-actor authority, visible weights 35/15/50, threshold 60, and institutional budget 80 agree with the rationale and assessment. The referenced option is correctly options[1], and inbox/ownOffers are empty. Budget preservation is presented as the purpose of voting no, without fabricating a completed funding outcome.

Canonical full journal-row SHA-256: `c78410ef2f360b20ebba574daaa7bd78f5c523134bab6f7e3c87e66b7534e7dd`.

### trade-current-period-order-r0

**PASS.**

Preserved the valid current-period order_a proposal. Both routes are eligible; A costs 2 versus B's 3, cash is 28 with 0 reserved, and the prior accepted order's commitment and dated settlement event are January 1, before the current January 2-3 demand period. No pending matching current-period order exists. Final intent, rationale, and four assessment explanations agree with the additional-good objective and supplier-consent condition; the purchase option references are correctly route A.

Canonical full journal-row SHA-256: `18e6ddc2cfb0bee3085ebd8438a8c372a3802a39b8866e4c4202a209d5918346`.

### investment-rationale-action-disagreement-r1

**FAIL: assessment-reference accuracy; action remains correct.**

Final action and rationale correct the mismatch to quantity 2/total price 2 from visible capacity 3 minus 1. Cash 28, accepted historical 2/2 offer, and its settled commitment support acting rather than waiting. The quantity check correctly cites the purchase price input. However, goal_alignment includes options[0].inputs, which is communicate's text schema, as evidence for the purchase proposal; purchase is options[1]. The behavior and prose are correct, but this unrelated model-selected action-schema reference remains an assessment defect, so qualitative review fails.

Canonical full journal-row SHA-256: `6da4deb0655dd7fef14b9108317a5d3307671b7a86a7343e644812bdf6c5813e`.

### investment-consistent-current-purchase-r1

**FAIL: assessment-reference accuracy; action remains correct.**

Preserved the valid 4/4 purchase control with capacity 5, cash 25/reserved 0, no matching pending offer, and explicit supplier-consent contingency. Timing and quantity explanations are consistent, and the quantity check correctly uses options[1].inputs. Goal_alignment instead cites options[0].templateId while claiming the intent matches the visible purchase option; the cited value is communicate. The action and rationale remain correct, but the assessment misidentifies the referenced option, so qualitative review fails.

Canonical full journal-row SHA-256: `0dbd45a5849b6c7c7191a386be998ed58b46068c737aa1e4de27b2f880727870`.

### coalition-wait-before-trigger-r1

**PASS.**

Preserved the valid empty-intent wait while coalition_ab is none. Program authorization is false, budget is 80 with 0 reserved, and no inbox/own offers/commitments require action. Rationale and all four checks match the observed conditional goal and explicitly distinguish a wait choice from missing capability. The phrase 'Both objectives' refers imprecisely to clauses of the single supplied objective; it introduces no new goal and has no material effect on this row.

Canonical full journal-row SHA-256: `beda7e13f0c71c238a98818d49dab87f63ad150a38fb0a5dc62f4a8b92f15340`.

### coalition-opposition-after-trigger-r1

**PASS.**

Preserved the valid own opposing vote after coalition_ab is allied. The single program_vote intent has support false; its timing and rationale match the conditional objective. Weight 50, threshold 60, budget 80, and empty inbox/offers are supported by the visible records and correctly selected vote option. Assessment references and explanations remain consistent with the final action, with no invented counterpart authority, new condition, or already-completed funding claim.

Canonical full journal-row SHA-256: `5e3e9870c283330e05dc72e70f3c6c28f444c7837873a1f2094edcfcd5ebef40`.

### trade-current-period-order-r1

**PASS.**

Preserved the valid route A proposal for one additional good during January 2-3. Both routes are eligible; price 2 is cheaper than 3 and affordable from cash 28/reserved 0. The January 1 accepted-and-settled prior order is historical and not a pending current-period duplicate. Rationale and assessment describe the actual order_a intent subject to supplier consent. The arithmetic 28-2=26 is conditional on settlement, not a claim that it already happened. No material goal, timing, or explanation error found.

Canonical full journal-row SHA-256: `43685fca14342b2b653c7a204d95cccdb9957c41e78c347129278f2d8db6a2f7`.

## Evidence and method

Inputs: [preregistration.json](preregistration.json) actorPayload observations/candidates and [journal.json](journal.json) completed final decisions, state updates, all four assessment checks per row, and recorded failure diagnostics. Verdicts were independently compared with the visible actor objectives, period bounds, options, cash/reservations, offers, commitments, and events. Correct action matches were not treated as sufficient proof of assessment accuracy. The twelve actorPayload objects were compared with Phase 8 and were identical; all Phase 9 outputs were reviewed anew.

Each resultHash covers the entire saved journal row: recursive NFC normalization of string keys/values, UTF-8 JSON with sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, followed by SHA-256. The manifest hash was recomputed with the same standard-library-only procedure excluding manifestHash.

- Raw preregistration.json SHA-256: `f34e76fd65b157e4f38406b8f571dd14e19ecb3767e9cffe5920f5fb4c49e359`.
- Raw journal.json SHA-256: `6f46863f46cebb7bc8cd25bf351368692f23cbdbb0a85f4df1ed6219057a2c5f`.

Only qualitative-review.json and qualitative-review.md were written. Manifest, journal, source, ledger, and report were not edited. No application imports, SQLite, providers, tests, or delegation were used. The coordinator owns report/budget closeout.
