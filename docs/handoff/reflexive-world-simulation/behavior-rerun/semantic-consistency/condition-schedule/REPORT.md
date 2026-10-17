# Condition and decision-opportunity explanation repair

The user requested fixing the two retained explanation errors and rerunning the confirmation within the original remaining budget. This change adds a specific review procedure to `actor-consistency-v2`: examine conditions in objectives and constraints separately from `priorityRules`, and separate world changes from an actor's opportunity to make another decision. All previous study outcomes remain immutable. `world-v1` stays opt-in until the full behavior gate passes.

## Evidence and correction

The preceding [phase 11 review](../temporal-clarification/live-evidence/qualitative-review.md) found two failures despite correct actions. One investment assessment inferred that no conditions existed when only the `priorityRules` array was empty. One coalition rationale inferred a later voting opportunity within the current period from a current menu and a possible world change. Both failures are retained in that study's 10/12 qualitative result.

Only [`_REVIEW_SYSTEM_V2`](../../../../../../backend/app/services/world_simulation/policy.py) changed in production. It now requires reviewing conditional clauses in objectives and constraints independently of structured priority rules and visible terms. The model must distinguish existing conditions that are met, unmet or unknown, and summarize their relevant basis without contradicting another check. An empty rule list does not establish that other visible fields contain no conditions.

The same instruction distinguishes the current action menu from future decision opportunities. A plan or a wait does not register a contingent action or reserve another turn. Future intentions can depend on a later eligible observation and its menu, without promising an opportunity before `periodEnd`. The prompt also avoids claiming that later action is impossible. Unknown future consent or fulfillment alone does not make a present proposal inconsistent; known affordability, authority and protocol constraints still apply. These checks cover rationale, state updates and message claims as well as assessment explanations.

This distinction follows the [controller's actual round sequence](../../../../../../backend/app/services/world_simulation/controller.py): one proposal collection, responses to delivered offers, then state resolution. A current observation does not reveal another arbitrary within-period proposal opportunity. The change adds no scheduling fact or hidden information to the observation.

V1/None behavior, observations, candidate bytes, review schema, explanation bounds, controller/store/kernel, modeler, pricing, model, reasoning effort, output limit and two-call allowance are unchanged. No response censor, prose rewriting, expected action, case identifier, forced wait or forced clear verdict was introduced. The model remains responsible for its generated explanation, which is independently assessed.

## Final confirmation outcome

The twelve fixed calls produced eleven completed decisions and one withheld `consistency_unresolved` response. All eleven completed decisions matched the action expectations, and all eleven passed independent qualitative review of the rationale, state updates and four assessment texts. There were no unknown charges or replacement calls.

| Context | Completed / planned | Qualitative passes |
|---|---:|---:|
| Investment quantity/rationale mismatch |2/2|2|
| Coalition action before its trigger |1/2|1; the other response was withheld|
| Current investment purchase control |2/2|2|
| Coalition wait control |2/2|2|
| Coalition opposition after trigger control |2/2|2|
| Current-period trade control |2/2|2|
| Total |11/12|11|

Both investment mismatch revisions corrected 3/3 to 2/2. The completed coalition correction removed the premature vote and deferred reevaluation to a future eligible observation, without claiming an additional within-period turn. All eight controls preserved their valid actions. The completed investment explanations recognized the pending-offer wait condition separately from empty priorityRules. The independent review found no material semantic contradiction in the eleven completed rows.

The reviewer retained wording caveats: an overly broad statement about other triggers, an imprecise description of conditional constraints, unclear shorthand for prior offer terms and an awkward wait sentence. These were interpreted in the context of each complete decision and were not taken as denial of the conditions that those same rows explicitly evaluated. The [full review](live-evidence/qualitative-review.md) records the interpretations; the outcome does not endorse every phrase as precise or guarantee future adherence.

`coalition-opposition-before-trigger-r1` remains failed with `consistency_unresolved`. Its discarded decision and assessment were not retained, so neither their correctness nor the reason for uncertainty is inferred. It receives no qualitative review or assumed action credit. The denominator remains twelve, making the diagnostic gate **incomplete, not passed**. The latest full world study remains 16/18 required comparisons; no fresh full study was substituted and `world-v1` remains opt-in.

The [frozen report](live-evidence/report.json), [journal](live-evidence/journal.json) and [review bindings](live-evidence/qualitative-review.json) preserve every outcome. A separate frozen-source guarded summary check asserts the incomplete denominator and exclusion of the withheld response. See [closure.json](live-evidence/closure.json).

## Budget and preservation

This confirmation consumed USD0.096112 of known tariff-based exposure, including USD0.006288 for the withheld response, and zero unknown exposure. Across all twelve phases, conservative exposure is **USD19.009480955664**, leaving **USD5.990519044336** of the original USD25 authorization. This includes earlier conservative unknown/interruption ceilings and is not audited billing. Reservation quotes are not additional spending. [The global ledger](../../../live-budget.json) has no active phase or provider process.

All 416 earlier artifacts remained byte-identical, and all 535 accepted source files were unchanged throughout dispatch and independent review. The original phase 11 two explanation failures remain failed, and all earlier phase reports/reviews are preserved. The repair, fixed confirmation and review are complete; the all-twelve confirmation gate and full behavior release gate are not passed. No further repetition or budget reset is authorized by this record.

## Verification

Two new actual-SDK request regressions first failed on the previous prompt because the specific review instructions were absent: two failed, thirteen deselected, no source drift. This is request-contract red evidence; phase 11 provides the actual semantic failure evidence. The tests cover both clear and unresolved responses, unchanged observation/candidate payloads, exact UTF-8 reservation bounds and known usage. They do not prove that a live model follows the prompt.

The final focused gate passed **376 tests in 9.35 seconds**, with zero failures/errors/skips and no drift across 535 frozen files. It includes ordinary/v1/v2 policy, controller, store, directed evaluator and launch/replay tests. AST comparison shows production outside the v2 prompt assignment is identical to `d59cb43`. Independent design and exact-source reviews closed with no findings. Ruff F/E9 and source whitespace checks passed. The guard recorded three storage redirects and two blocked SDK metadata process probes, with no recorded network attempts; it is a CPython audit boundary, not an OS sandbox.

Receipts: [verification](verification.json), [source manifest](offline/source-manifest.json), [green JUnit](offline/junit.xml), [red JUnit](red-junit.xml). Raw red XML retains its captured assertion whitespace; it was not reformatted.

## Confirmation scope

The separately preregistered phase uses the same six saved contexts twice: two original failure contexts and four controls. Only the actor review instruction changed. The twelve calls include every outcome, with no replacement calls or regrading of prior results. The maximum is USD1.25 within the original remaining USD6.086631044336, not a new authorization. The strict diagnostic gate still requires twelve correct actions and twelve complete independent qualitative passes.

This is directed revision of saved candidates, not fresh candidate generation or a full world trajectory. Even a passing result cannot replace the unchanged 36-case behavior gate or establish forecast calibration. The [architecture report](../../../ARCHITECTURE.md) and [consistency implementation report](../REPORT.md) describe the wider workflow and its limits.
