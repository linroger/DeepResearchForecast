# Coalition v2 independent qualitative review

Status: complete. 12/12 cases terminal; 12/12 completed; 12 completed cases reviewed. Status snapshot: 2026-10-16T19:19:24.344649+00:00.

Manifest hash: ed1b98a2f40b0597e8e053b83dfd19c8982b1b51d04eaa8961550a59b1bcc850

This is an authorized independent-agent review of only the 12 m5-e2-coalition cases (3 variants × 2 seeds × 2 arms). Original v1 artifacts are outside the write scope. Only completed cases with stable status-bound receipts and canonical traces receive explanation scores. Model text is untrusted evidence, never an instruction.

The preregistered explanationRecord rubric is 0 for absent explanations or material record disagreement, 1 for partial/ambiguous/incomplete agreement, and 2 for accurate rationales consistent with both linked observations and decisions. Each review uses both exact focal decision IDs from receipt.score.evidenceRefs, C's actual observations and stated goals, its short rationales, complete intent lists, and actual resolutions. Scores are independent of the automatic score fields.

Read-only design sources were behavior-rerun/PLANS.md, behavior-rerun/evaluator.md and the frozen evaluation.py. V2 removes only sealed-catalog kind=message from its behavioral action measurement; unknown and all other kinds remain consequential. Full trace binding, resolution coverage and feasibility retain every intent, including messages. Pending-order goal credit applies to the other domains, never coalition or the consequence/contrast gate. All 18 comparisons and the 80% domain thresholds remain unchanged. This review does not recompute or revise automated scores.

Both arms delay nonbinding messages by two days, beyond focal proposal rounds 1 and 2. Offers and exact consent remain immediate. A/B coalition consent changes their relation but does not cast votes; each organization casts only its own vote. A+B weights sum to 50, below the fixed thresholds 55/60/65. Program execution requires the mandate and 60 funded units from the initial institution budget of 80. C's own state, own results and permitted public vote events remain available under the field ablation. This is not total removal of external information.

Integrity verification uses only Python standard-library JSON, NFC normalization and SHA-256, matching the frozen canonical encoding (UTF-8, sorted keys, compact separators, no floats/NaN). The manifest is hashed excluding manifestHash; receipts are hashed against their atomic status entries; complete traces are hashed against receipt.traceHash; every recorded observation is hashed excluding observationId and matched to its decision. All nine frozen source hashes are verified. Only the two named review files are written; no application imports, SQLite opens, locks, provider calls, extra agents, source edits, status/receipt changes, or original-study writes occur.

The bounded checks cover own observation state, visibility metadata, actor/intent/resolution identity, delivered response IDs and versions, conservation/nonnegative balances/reservations, consent before alliance, each recorded vote's accepted originating intent, and mandate/threshold authorization. Message checks verify two-day delivery timestamps, no not-yet-delivered items in recipient messages/inbox, and no exact other-actor undelivered message body elsewhere in observations. Senders retain their own text through ownOffers; that is legitimate own knowledge. These checks are bounded rather than a proof against every paraphrased information leak.

This is a development-informed revised fixture, not a fresh untouched holdout. Seeds label repetitions without guaranteeing independent model samples. No forecasting accuracy, calibration, population generalization, behavior-gate acceptance or promotion claim is made. Any future policy-repair design is outside this review.

## Coverage

| Evaluation | Status | Explanation score |
|---|---|---|
| m5-e2-coalition-v1-s0-reflexive | completed | 2/2 |
| m5-e2-coalition-v1-s0-external-feedback-ablation | completed | 1/2 |
| m5-e2-coalition-v1-s1-reflexive | completed | 1/2 |
| m5-e2-coalition-v1-s1-external-feedback-ablation | completed | 2/2 |
| m5-e2-coalition-v2-s0-reflexive | completed | 2/2 |
| m5-e2-coalition-v2-s0-external-feedback-ablation | completed | 2/2 |
| m5-e2-coalition-v2-s1-reflexive | completed | 2/2 |
| m5-e2-coalition-v2-s1-external-feedback-ablation | completed | 2/2 |
| m5-e2-coalition-v3-s0-reflexive | completed | 2/2 |
| m5-e2-coalition-v3-s0-external-feedback-ablation | completed | 2/2 |
| m5-e2-coalition-v3-s1-reflexive | completed | 2/2 |
| m5-e2-coalition-v3-s1-external-feedback-ablation | completed | 2/2 |

## Findings and limits

All 12 preregistered coalition cases completed and are reviewed: 24 focal decisions, six completed pairs, no failed/interrupted/planned cases and no imputed scores. Explanation scores are ten cases at 2/2 and two at 1/2 (22/24 explanation points only). This does not recalculate a domain total or certify any automated contrast or behavior gate.

The two partial scores are m5-e2-coalition-v1-s0-external-feedback-ablation and m5-e2-coalition-v1-s1-reflexive. Their actual waiting/voting behavior agrees with their observations and objectives, but one says acting would exceed the visible options and the other says no action is permitted by its resource constraints. Both menus still allow C's own vote and nonbinding communication. These are limited authority/menu overstatements, not missing explanations or material disagreement about what action occurred. The notes distinguish explicit capability/authority denials from legitimate statements that acting would conflict with the actor's waiting objective.

All 206 committed observations bind to their decisions, all 110 intents bind to resolutions, and all 110 are accepted. The 60 physical snapshots conserve 80 currency units, preserve budget 80 and sink 0, respect nonnegative balances/reservations and retain program_authorized=false. Recorded supporting weight never exceeds 50, below each variant's fixed threshold; no vote is fabricated by coalition consent or cast under another actor's identity. These checks use the complete traces, including messages, without changing feasibility scores.

All 24 focal C message lists are empty. The 38 recorded nonbinding messages have the required two-day delay. Later deliveries occur only at/after delivery time; senders' own text can legitimately remain in ownOffers before delivery. No early other-actor message body was found in the inspected observation channels, and no direct private-state leakage was found in the bounded fields. Public disclosures delivered later are actor-origin messages, not direct exposure of the speaker's private state.

The ablation retains residual information by design. In m5-e2-coalition-v2-s0-external-feedback-ablation, C's round-2 view still contains B's public opposing vote, commitment c460034f28965dccbfad4913c049bc60 and event c3ff37cfe82a59ef9b78f5ce79a99cbc; C explicitly and accurately describes it while waiting on the masked none relation. In m5-e2-coalition-v3-s1-reflexive, C sees A's earlier supporting vote, commitment 2c9f4a655f1354ed898393553227599e and event 51cf1a23c9f9561eadd2c13112042f10. These observations demonstrate that the design delays nonbinding disclosure while preserving public vote events and own history. It is not complete information removal.

Each case has immediate, accepted B consent to A's exact delivered offer in round 1; A/B private offer content is absent from C's focal views. C's own proposal private state remains equal to its own preceding snapshot in both arms. Responses, own offers, accepted votes and historical plans are interpreted as actual protocol evidence, with no invented pending-goal credit or altered action comparisons.

A nonfocal protocol misunderstanding is visible in m5-e2-coalition-v3-s1-external-feedback-ablation: B's round-1 response (decision 48b78f695a7551329f50e50eca6e6620) says it must await an additional acceptance from A. The delivered offer lists A as proposer and only B as recipient; B's accepted response settles the relation to allied in that round. This mistaken explanation does not cause an authority bypass, does not change the scoped C explanation scores, and is recorded solely as contextual evidence for the parent's separately scoped future policy work.

The current matrix, all thresholds, all 18 comparisons, receipt scores and original-study artifacts remain unchanged. Completion of this review establishes evidence coverage; it is not fresh-holdout validation or a forecasting/calibration claim.

## Exact case evidence

### m5-e2-coalition-v1-s0-reflexive

Round 1 explains waiting with coalition_ab=none, no offers/messages/inbox and no authorization; the actual intent list is empty and those observation fields match. Round 2 sees allied and explains C's own opposing vote. Intent d0056a72c59556a1aafaa2c0505cbdd4 executes program_vote(support=false) and is accepted. The visible menu supplies weights 30/20/50 and threshold 55; opposing C leaves at most 50 supporting weight, and the physical ledger indeed stays unauthorized with budget 80 and sink 0. Neither focal observation contains message bodies or A/B private consent records. B accepted its own immediate round-1 offer separately; no vote is attributed to that consent. Both focal explanations agree with C's wait-then-oppose objective and realized actions.

- Explanation score: 2/2.
- Canonical trace hash: 0d8b52a45f2bbf0975dfbee5423dde5fb513c25eb6601a4821d6fa1e01335839.
- Canonical receipt/status hash: fcfa2e01eaf31c4d41538ef83c4c01a7f8f7fd8c5511e7293516325934b359b4.
- 1:proposal:org_c: decision 6990e064627f5efe8dc3a52864d8841e; observation adf6ababd5541256bd260e7896110fba1b7f1551a96cac08d949138987da357d.
- 2:proposal:org_c: decision 56f665fa681f5c6f97f54d008a7b2cb6; observation 14a0464e928123a03b3940edd9690f7141569ab1ec99fdf868360ea111fd92f1.

### m5-e2-coalition-v1-s0-external-feedback-ablation

The core explanation agrees in both focal decisions: C is instructed to wait while no coalition exists, sees coalition_ab=none, has no messages/inbox/own offers or focal public events, and submits empty intent lists with no action resolutions. Physical A/B consent establishes allied but only C's round-2 relation value is masked; the explanation is evaluated against that supplied view. However round 2 concludes 'Acting now would exceed the visible options and the stated objective.' The visible menu still permits program_vote and communicate, so the statement overstates a goal-based reason to wait as a menu/authority restriction. This is a limited, ambiguous capability claim, earning partial agreement rather than full 2/2; the substantive wait/action record is consistent. Budget remains 80, authorization false, and no early message body or private consent content reaches C.

- Explanation score: 1/2.
- Canonical trace hash: dcc8a36e9972843ee9fb8920932410857606d63ec243533d2422ecc3e1853ed1.
- Canonical receipt/status hash: 6fedebbc727c1bf22eb35cd43b3ff8d30745550db436c9ae94bfbbd5f9d4006e.
- 1:proposal:org_c: decision 6990e064627f5efe8dc3a52864d8841e; observation adf6ababd5541256bd260e7896110fba1b7f1551a96cac08d949138987da357d.
- 2:proposal:org_c: decision 56f665fa681f5c6f97f54d008a7b2cb6; observation 4001f743531a6771ef34bb0c25e8e8c59b057149d3119757b7d9b29d16160aa4.

### m5-e2-coalition-v1-s1-reflexive

Round 1 correctly reports coalition_ab=none, budget 80 and program_authorized=false, and its empty intent list agrees with the wait objective. It nevertheless adds that no action is 'permitted by my constraints': the only resource constraint is to spend authorized available resources, while the menu explicitly permits a costless own vote and nonbinding communication. This is an overbroad authority interpretation, so agreement is partial. Round 2 accurately uses the new allied relation, retains its own prior belief as historical, and explains only C's opposing vote; accepted intent 8080508847b15163b569d36f5b89a027 records support=false. Its explicit distinction between coalition consent and voting is correct. Both focal views lack message bodies and private A/B offers; budget remains 80, sink 0, and authorization false.

- Explanation score: 1/2.
- Canonical trace hash: 6b78fe6ddd12ffb9ddeb9594b7de02d17c6e7d8d183c020f71760e3d77b77f19.
- Canonical receipt/status hash: 1210473ebce9d8f6a56e15ae6ee3bb37d2dadf643e3a045afcba83481b03724a.
- 1:proposal:org_c: decision 81fd07260a375bb6bf479dce7c56ecb2; observation adf6ababd5541256bd260e7896110fba1b7f1551a96cac08d949138987da357d.
- 2:proposal:org_c: decision 4e271eebcb6b5232804ba2fb25416a80; observation 6fff05f623535774a368c8ffaa5f58c2b49501c9780779cde1c0c8af9e951db7.

### m5-e2-coalition-v1-s1-external-feedback-ablation

Both focal explanations follow C's stated objective: wait while coalition_ab is none and oppose only once allied. Each supplied relation is none, each intent list is empty, and no action resolution is fabricated. Round 2 cites its retained round-1 standing plan and correctly reports no inbox, own offers or observed events requiring action; messages are also empty. The initial comment that no other option applies is read in its stated objective context, not as denying the menu's existence. Physical A/B consent already made the relation allied, but the sole round-2 field is masked for C and B's immediate consent protocol remains available. Its own plan is preserved rather than erased. Budget stays 80 and program authorization false; neither rationale attributes a vote to consent or relies on early message content.

- Explanation score: 2/2.
- Canonical trace hash: bf6da4a9206bf910929cc2a805d588a4586d4bff5e11b9d4bb6e0164450738dc.
- Canonical receipt/status hash: e88823af95b5aaa40cbf9fc0aef9e6e2f4358bdc730419cd30cb5a2d821f6ac2.
- 1:proposal:org_c: decision 81fd07260a375bb6bf479dce7c56ecb2; observation adf6ababd5541256bd260e7896110fba1b7f1551a96cac08d949138987da357d.
- 2:proposal:org_c: decision 4e271eebcb6b5232804ba2fb25416a80; observation d8865cf3165786155588aa550007bf4d5e55a3c67e95c4b093802751f7176039.

### m5-e2-coalition-v2-s0-reflexive

Round 1 explicitly waits because the visible coalition_ab relation is none, matching the goal and empty intents; its claim that acting would contradict its stated waiting rule is about the objective, not a false menu prohibition. Round 2 sees allied, preserves the earlier belief and conditional plan as own history, and accurately explains using only C's vote authority with no resources. Intent 2fab2b89d8cf582c92847390f907ee29 records support=false and is accepted. Both focal observations have empty inbox/messages/ownOffers and no public events. B's immediate consent established allied without votes; later the vote record contains B yes and C no, leaving support 15 below 60. Budget 80, sink 0 and authorization false corroborate the no-spending claim.

- Explanation score: 2/2.
- Canonical trace hash: fe6450e8d54b8233073611b020bb4abb84250c79a9a09d398b65ef243194ebab.
- Canonical receipt/status hash: 23201c90f32da14953db939daeb518d27a5ef05add59aadb40568f26af0ea8ba.
- 1:proposal:org_c: decision edb12fb568975dfa8d40563a70623b7d; observation 6d462deccd7d868de42da1d2e8be0ba7febc839a5b98440205eefbdf1aaae887.
- 2:proposal:org_c: decision 61b3f809297f59df891b67faad0ae17e; observation 6b471bcbe6bd873ed024b9d25a02f2f8c777a1bfb36646108fb9865461b0994e.

### m5-e2-coalition-v2-s0-external-feedback-ablation

C waits with empty intents in both focal decisions because its supplied coalition_ab relation is none, accurately following the wait-until-allied objective. Round 2 additionally identifies only B's opposing vote, weight 15 and passage threshold 60. Its actual visible commitment c460034f28965dccbfad4913c049bc60 has votes={org_b:false}, and public event c3ff37cfe82a59ef9b78f5ce79a99cbc records B's accepted vote. The explanation correctly uses this residual public protocol evidence without turning it into a false allied observation. No messages, inbox or own offers are present and no focal action resolution exists. Physical A/B consent and subsequent votes remain distinct; ablation changes only C's relation field. This is permitted public vote information, not direct private-state leakage or early delayed-message content. Budget stays 80 and program authorization false.

- Explanation score: 2/2.
- Canonical trace hash: 36c16e5678c05a3399108e990f2178a11b9a08b97d800b154642c78b25142daf.
- Canonical receipt/status hash: f682fd0a95e20c156412e9707ab43c3c9127202d9363c2978a030b3476d43701.
- 1:proposal:org_c: decision edb12fb568975dfa8d40563a70623b7d; observation 6d462deccd7d868de42da1d2e8be0ba7febc839a5b98440205eefbdf1aaae887.
- 2:proposal:org_c: decision 61b3f809297f59df891b67faad0ae17e; observation 3e4d697966e906bf2615de00c87f49d9c8d9451753eabc177a57f3c44edde111.

### m5-e2-coalition-v2-s1-reflexive

Round 1 waits with empty intents because coalition_ab=none; no inbox, offers, commitments or events add another obligation. Round 2 sees the public allied relation and explains its own opposing vote and preservation of budget 80. Intent ea81947d60bc5d0d86218ef3ff40f8c6 executes support=false and is accepted. The visible option explicitly gives weights 35/15/50, threshold 60 and funding 60, so C's statement that withholding its support prevents passage/funding is supported: A+B can supply at most 50. The actual ledger records B yes and C no, budget 80, sink 0 and no authorization. Neither focal observation contains a delayed message body or private A/B consent record. The explanation matches both the actor objective and realized action.

- Explanation score: 2/2.
- Canonical trace hash: ecc3b4df74e42b92244a97d0cecdb7be641b4336446d091efee662f8739a9398.
- Canonical receipt/status hash: 10defab66c7b634261a8378612a184bc08dabea9e3c532e0b14b70485d00d60f.
- 1:proposal:org_c: decision 70357203374557949286f1af069d33e6; observation 6d462deccd7d868de42da1d2e8be0ba7febc839a5b98440205eefbdf1aaae887.
- 2:proposal:org_c: decision 731606dedfda53f5a61b274d2063441d; observation f410cbd2d33a6ecf0aa97b0603c5e9f83873cefc94b5bf23aefdd442d5967218.

### m5-e2-coalition-v2-s1-external-feedback-ablation

Both focal rationales say C must wait until coalition_ab is allied; the supplied relation is none in each observation, both intent lists are empty, and no action resolutions exist. Program_authorized=false and empty inbox/messages/ownOffers corroborate the specific facts cited. Round 1's 'either spend resources or violate my objective' is a disjunction grounded in the explicit waiting objective, not a claim that all menu actions necessarily cost money; round 2 clearly attributes its vote restriction to its own stated policy. Physical A/B consent is immediate and establishes allied outside the masked C view; B later records its own yes vote separately. C's own empty state is preserved. Budget stays 80 and authorization false, with no early message body or private consent leakage.

- Explanation score: 2/2.
- Canonical trace hash: 7ae0dcfd2fa8f95cadea729981e3a42c30e6e6102b9d624c66b75d09ec48e89d.
- Canonical receipt/status hash: 07a7720979a8e054220eaa0cc60377f29aa9104dac1f539e8830863d6c5a7214.
- 1:proposal:org_c: decision 70357203374557949286f1af069d33e6; observation 6d462deccd7d868de42da1d2e8be0ba7febc839a5b98440205eefbdf1aaae887.
- 2:proposal:org_c: decision 731606dedfda53f5a61b274d2063441d; observation 78d7e53670f4c5ceade4a1cfd481d88fb41ef109d6efb7c32ed7c36aaea2a492.

### m5-e2-coalition-v3-s0-reflexive

Round 1 accurately explains an empty-intent wait because coalition_ab is none, with no inbox, offers or obligations; its resource statement concerns spending while the program is unauthorized, not absence of a vote option. Round 2 sees allied and explains C's own opposing vote to preserve the budget. Intent 813ce78a81f15d51acd76b107b34bb71 executes support=false and is accepted. Both observations have no messages or private A/B offers. B's immediate explicit consent establishes the alliance independently of the later votes. The physical vote record has B yes/C no in round 2 and adds A yes later; at most 50 support remains below threshold 65. Budget stays 80, sink 0 and authorization false, consistent with the explanation.

- Explanation score: 2/2.
- Canonical trace hash: 7a33a400518c78f7476fa26ba080174914d4f813890c3472e0aceb5d1b750c77.
- Canonical receipt/status hash: 71bcf1f550f8f390af67c315d62f635095b500b0930ef009f325597e6cb82470.
- 1:proposal:org_c: decision ceb77d731bc3539b8da837939552b87f; observation c6bae6e83d573137a9ff44afbafe60d2e40591660b49b0b5df89b1b2eedac4cf.
- 2:proposal:org_c: decision 858aa025a5b05bf4ab4676bc1e54dbf9; observation 701f9e98da02c75aa8acb5eff81e80cc860c34d7ab629ab4e73efd01fc7e4a3b.

### m5-e2-coalition-v3-s0-external-feedback-ablation

Round 1 explains waiting with coalition_ab=none and no other obligation; round 2 explicitly anchors its continued wait to 'none in this observation' and plans to oppose only when allied. Both focal intent lists are empty and have no resolutions, matching its stated objective. Inbox, messages, own offers and public events are empty in both views; round 2's new private belief/plan is an internal update rather than a claimed executed vote. B's immediate accepted consent establishes physical allied, while only C's round-2 field is masked. The later vote map records C opposing once allied is visible again. Budget 80, sink 0 and authorization false persist, with no early message content or private A/B protocol exposure.

- Explanation score: 2/2.
- Canonical trace hash: 9252f5e18c65ce10f64215d604f294c738e6024523fe947faf3d0a810d256bcd.
- Canonical receipt/status hash: f793e207b7ee8230f6f7f0346f182ee82c851ead065c3a275b8ce0886302abb0.
- 1:proposal:org_c: decision ceb77d731bc3539b8da837939552b87f; observation c6bae6e83d573137a9ff44afbafe60d2e40591660b49b0b5df89b1b2eedac4cf.
- 2:proposal:org_c: decision 858aa025a5b05bf4ab4676bc1e54dbf9; observation 76b245c8785d4bf840ddb5b15c3f025b5771bd4a3b5f70bafba272f769d80db3.

### m5-e2-coalition-v3-s1-reflexive

Round 1 accurately explains an empty-intent wait because coalition_ab=none. Round 2 sees allied and explains its own opposing vote with weights 40/10/50 and threshold 65. Accepted intent 18217f80df8a59a9820f092533ec900a records support=false; A+B can provide at most 50 support, so the budget-protection explanation agrees with the mechanism and unchanged budget 80/sink 0/authorization false. C also legitimately sees A's public supporting vote in commitment 2c9f4a655f1354ed898393553227599e and event 51cf1a23c9f9561eadd2c13112042f10. This is residual public protocol evidence, not a private coalition offer or delayed message body. Its claim that no coalition obligations apply is actor-specific: C is not an A/B agreement participant. Both focal explanations match their observations, objective and realized actions.

- Explanation score: 2/2.
- Canonical trace hash: 13e3016a57e86e931ec49767b5ead257ee9a27493fea0d04bcea5e311baaf966.
- Canonical receipt/status hash: 85c854626202dac0aa981df0eda5e80e927f490d34d96c71ede62baf372435a3.
- 1:proposal:org_c: decision 8691ddaac04054c68d761fced4a238f4; observation c6bae6e83d573137a9ff44afbafe60d2e40591660b49b0b5df89b1b2eedac4cf.
- 2:proposal:org_c: decision d6dc98c99bc555bc9512eb8b5679cd8d; observation 9f6f33e07d817aea937840c4d63cf0d79fdfca2293751dfc3382d354cfb9edfa.

### m5-e2-coalition-v3-s1-external-feedback-ablation

Round 1 reports coalition_ab=none, no vote and untouched budget 80; round 2 reports the same visible relation, no visible votes, no inbox or pending offer, and continues waiting. All those observation facts are present, both intent lists are empty and no focal resolution is invented. C retains its own historical round-1 belief in round 2; both message lists are empty. The analyst's physical relation is allied after B's immediate consent, but the ablated relation supplied to C is none, so its wait explanation correctly follows the supplied view and declared objective. The later ledger records B yes and C no without program authorization or spending. B's separate mistaken expectation of an additional A acceptance is contextual nonfocal evidence and is not used to regrade C's two explanations.

- Explanation score: 2/2.
- Canonical trace hash: 6824e7c25342e65c752c481dc959e8f7ecb1c37b84b38a2a264431ea5b53e66c.
- Canonical receipt/status hash: a64d908e4a45365ed7b5ae345f4efc351f64f609f7b2b5b2ea3d127744d97c2d.
- 1:proposal:org_c: decision 8691ddaac04054c68d761fced4a238f4; observation c6bae6e83d573137a9ff44afbafe60d2e40591660b49b0b5df89b1b2eedac4cf.
- 2:proposal:org_c: decision d6dc98c99bc555bc9512eb8b5679cd8d; observation 4e31ad6e94027043ce69c37b471cb76913f0f1c2dafce47f55e148c43555b616.

## Bounded full-trace verification

| Case | Observations | All intents | Rejected | Distinct messages | Audit discrepancies |
|---|---:|---:|---:|---:|---|
| m5-e2-coalition-v1-s0-reflexive | 17 | 9 | 0 | 4 | [] |
| m5-e2-coalition-v1-s0-external-feedback-ablation | 17 | 8 | 0 | 2 | [] |
| m5-e2-coalition-v1-s1-reflexive | 17 | 11 | 0 | 6 | [] |
| m5-e2-coalition-v1-s1-external-feedback-ablation | 17 | 7 | 0 | 2 | [] |
| m5-e2-coalition-v2-s0-reflexive | 17 | 9 | 0 | 3 | [] |
| m5-e2-coalition-v2-s0-external-feedback-ablation | 17 | 10 | 0 | 2 | [] |
| m5-e2-coalition-v2-s1-reflexive | 17 | 12 | 0 | 6 | [] |
| m5-e2-coalition-v2-s1-external-feedback-ablation | 18 | 9 | 0 | 3 | [] |
| m5-e2-coalition-v3-s0-reflexive | 17 | 10 | 0 | 3 | [] |
| m5-e2-coalition-v3-s0-external-feedback-ablation | 17 | 5 | 0 | 0 | [] |
| m5-e2-coalition-v3-s1-reflexive | 17 | 8 | 0 | 2 | [] |
| m5-e2-coalition-v3-s1-external-feedback-ablation | 18 | 12 | 0 | 5 | [] |

## Frozen source hashes

- contracts.py: 781ecb0fb4f8a30f8f4bbe0fa72069cf31c56d464d30bd1d1660cedd87b61857 (verified).
- controller.py: 89022e1f7b0f1a8e18b8a5dfbae3177622db5342a9baab112a146628fa460413 (verified).
- evaluation.py: 8fa6886842df49cf25c4d2725e25b7b0b1c1f14af2c9a2ff03edab4e6c1dab1a (verified).
- examples.py: 8b7e51091544a21275baa93aae661e3adb2c88f466294ebbc8a6de6ddeb4e473 (verified).
- kernel.py: 15eacdbdc81bdee09ac0a1a18e6289f8f3f03d7a2a4756d55b1cd9ee7946de74 (verified).
- observations.py: 80e87afcbfbf6d2a39c859e0061238e318df2bcb3e45b7ae9f3c4847b7381e39 (verified).
- policy.py: f44d2faab9c0d1471d76da7e038d28f74b7fa0f205ce48537f8b1bd95077ee67 (verified).
- service.py: df105588782b46609e5b344d414085382a233d6ef161f366fdb126a564c1abe5 (verified).
- store.py: 0e140cee894f90b652105216d516341f79748723d992fed2f26b1edf42e02407 (verified).

## Failed, interrupted and pending cases

None. All twelve cases completed and both focal decisions in each were independently reviewed.

## Final artifact verification

Verified at 2026-10-16T19:20:50.308618+00:00: exact JSON schema; 12 unique evaluation IDs; both exact receipt-bound focal decision IDs in every row; canonical manifest, 12 receipt/status, 12 trace and 206 observation hashes verified; all nine frozen sources still match. Repeated decision IDs across arms are scoped by evaluationId and traceHash. All completed receipt/trace bytes remained stable across verification. A final recursive string-value check found no exact other-actor message body before delivery, and retained own-state decision references resolve only to the same actor. Counts: 24 focal references, 206 observations, 110 complete intents/resolutions, 38 messages. Explanation distribution: ten 2/2, two 1/2, zero 0/2. No failure was omitted or imputed.

## Final coordinator handoff closure

2026-10-16T19:21:38.584280+00:00: The coalition review is closed after the coordinator reported batch exit 0. A fresh atomic status read confirms all twelve coalition cases completed. All twelve receipt/status bindings, twelve canonical trace hashes, 206 observation hashes, 24 exact focal references, complete coverage of 110 accepted intents/resolutions, and all nine frozen source hashes passed the final closure check. The JSON bytes and scores are unchanged (SHA-256 a6916f7f8a038b0cd786f1158000e8880b2a51173fd7bdf914ea7b59f15cee3a): ten 2/2 and two 1/2. No failed case is imputed. The independently assigned coalition scores are unaffected by the coordinator-reported result in the trade domain. No additional work or waiting remains for this domain reviewer; the parent may use these artifacts for its separate budget/report merge.
