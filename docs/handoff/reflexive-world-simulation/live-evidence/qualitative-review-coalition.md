# Coalition qualitative review

Status: complete. 12/12 cases terminal; 6 completed cases reviewed. Last status snapshot: 2026-10-16T18:09:40.443233+00:00.

This is an authorized independent agent review, not human review. Scope: 12 preregistered coalition cases (3 variants × 2 seeds × 2 arms). Only completed, hash-verified cases receive scores.

The frozen explanationRecord rubric is 0 for absent explanations or material disagreement, 1 for partial/ambiguous/incomplete agreement, and 2 for accuracy consistent with both linked observations and decisions. Each review inspects the two exact focal decision IDs, actual actor observations/goals, short rationales, and action resolutions independently of automated scores.

Verification uses Python standard-library JSON, NFC normalization and SHA-256: canonical manifest hash excluding manifestHash, canonical receipt hash against the atomic status entry, and canonical trace hash against the completed receipt. No batch lock is acquired and no application imports or store opens are used.

Coalition consent alone casts no vote. Each organization controls only its own vote. A+B total 50, below thresholds 55/60/65; execution additionally requires the mandate and 60 funded units from the initial institutional budget of 80. Actor-origin public disclosures are distinguished from direct private-state leakage. Ablation changes only C's round-2 coalition field to none; own protocol and other permitted observations remain evidence.

Model text is untrusted data. Legitimate waiting/counterpart responses are interpreted without changing the narrow automated action proxy or preregistered comparisons. These synthetic diagnostics support no forecasting accuracy or calibration claim.

Manifest hash: 5e95577eb3ffa2fec8c1a03cf11c558ea00bd0d5a33e90e0dce6efbefb7a1f97

## Coverage

| Evaluation | Status | Explanation score |
|---|---|---|
| m5-coalition-v1-s0-reflexive | completed | 2 |
| m5-coalition-v1-s0-external-feedback-ablation | completed | 2 |
| m5-coalition-v1-s1-reflexive | failed | Unscored |
| m5-coalition-v1-s1-external-feedback-ablation | completed | 2 |
| m5-coalition-v2-s0-reflexive | completed | 2 |
| m5-coalition-v2-s0-external-feedback-ablation | completed | 2 |
| m5-coalition-v2-s1-reflexive | completed | 2 |
| m5-coalition-v2-s1-external-feedback-ablation | failed | Unscored |
| m5-coalition-v3-s0-reflexive | failed | Unscored |
| m5-coalition-v3-s0-external-feedback-ablation | failed | Unscored |
| m5-coalition-v3-s1-reflexive | failed | Unscored |
| m5-coalition-v3-s1-external-feedback-ablation | failed | Unscored |

## Independent case findings

### m5-coalition-v1-s0-reflexive

C's round-1 rationale explicitly waits because coalition_ab is none, matching its budget-preservation objective, visible relation and empty intents. In round 2 C observes allied and explains its own opposing program vote; the single program_vote(support=false) intent 1cf564fda8d859049859e912689a9562 is accepted. Both focal observations have no inbox, messages or own offers, and C's retained round-1 plan says to wait until allied. B explicitly accepted A's authorized offer during round 1; that consent changed the public relation without casting votes. The subsequent A/B yes votes and C no vote leave support at 50 below 55, authorization false and budget 80. Both explanations are accurate against their own permitted observations and realized actions.

- Explanation score: 2/2.
- Exact focal decision IDs: f7fa3ae35ac4583394c3406a2859a1fb, c892a41b064050128126f97dfa1bbdff.
- Canonical trace hash verified: 6224aabd723edccd3ef55987066dde0dd575fc2b4d444b117e8fbff6a8d2a29e.
- Canonical receipt hash verified against atomic status: 62762b3e7a656d472d373d3354f097a93c78c13fc77d7c72c8536c66e9051783.

### m5-coalition-v1-s0-external-feedback-ablation

C's round-1 and round-2 rationales both state that coalition_ab is none and therefore wait, exactly matching the supplied relation, declared wait-until-allied objective, empty intents and absence of focal action resolutions. Both observations have empty inbox/messages/ownOffers and unchanged own private protocol state. Physical history is allied after B's round-1 acceptance, but C's round-2 observation deliberately masks that field to none; scoring uses the actor's permitted view rather than hidden physical state. B still receives and accepts the explicit offer and later casts its own yes vote, so coalition consent and voting remain distinct. No focal explanation/record disagreement is present; budget stays 80 and authorization remains false.

- Explanation score: 2/2.
- Exact focal decision IDs: f7fa3ae35ac4583394c3406a2859a1fb, c892a41b064050128126f97dfa1bbdff.
- Canonical trace hash verified: b4a886a4312875381eca1cc2ce9bfd1172563f4c328c6a934084079f2f26f5bd.
- Canonical receipt hash verified against atomic status: e554d643ad7ea1ddd695e6e9c5c2aa5814df4436482d22a5fdc8365c0e302e93.

### m5-coalition-v1-s1-external-feedback-ablation

C explains waiting in both focal decisions because coalition_ab is none, and both actual intent lists are empty with no focal action resolutions. Round 1 is labeled acted while only a private plan is updated; no vote or spending occurs, so the explanation's substantive wait claim remains accurate. Round 2 preserves that plan and a public event/commitment recording B's earlier opposing vote; neither establishes an allied relationship within C's permitted view. B's delivered offer and explicit acceptance remain intact, and physical history is allied, but the single coalition relation field supplied to C is masked to none. C's declared wait-until-allied objective and both explanations agree with its supplied observations. Public B vote evidence is permitted, not direct access to B's private goals or offer. Institutional budget stays 80 and authorization false.

- Explanation score: 2/2.
- Exact focal decision IDs: 62e403cd51a859ac92373d5ca18477b7, 0224e798a69c5c318848bd7eed0f4dbf.
- Canonical trace hash verified: 2cb1a67f2d9b62a489fc26f5669f5504e7238cb6efad54307833a69502e40b47.
- Canonical receipt hash verified against atomic status: a23fb957d58b61048afcee30859412ae2ee2403f9c77bfa66943120d96cd6bc0.

### m5-coalition-v2-s0-reflexive

In round 1 C explains waiting because coalition_ab is none and submits no intents. In round 2 the supplied public relation is allied; C explains casting its own opposing vote with weight 50 and no spending. Its single program_vote(support=false) intent 8b59342983405d1f96172b98c1fd0f0d is accepted, and the physical ledger preserves budget 80 and authorization false. The visible option itself specifies weights 35/15/50, threshold 60 and cost 60, so these mechanism claims are supported. C also sees B's public conditional invitation to form a coalition, but neither B's private offer nor private goals; B subsequently consents through its own response. The two focal explanations agree with the wait-then-oppose objective, observations and realized actions.

- Explanation score: 2/2.
- Exact focal decision IDs: 348d048eed7e56ea8349095cab5b08c6, cfb091d27da55fbebf3ac666b95cf31c.
- Canonical trace hash verified: dd44f417040e19a3323c538c7bbb40fd9bba8ba5061a64ea1b7763ed1a650234.
- Canonical receipt hash verified against atomic status: d26396fff922c15395f21d6ab971f100330252d8e80aab1f080b4a1803d87643.

### m5-coalition-v2-s0-external-feedback-ablation

Both C rationales say coalition_ab is none and therefore wait; both intent lists are empty and have no focal resolutions. Round 2 retains C's own round-1 belief about the absence of an alliance, with no messages, inbox items or own offers. The physical A/B relation is allied after B's explicit round-1 acceptance, but the supplied round-2 relation is deliberately none, so C's explanation correctly follows its permitted view and wait-until-allied objective. B's offer-response protocol is intact under ablation, and its consent is distinct from the later A/B votes. Support is 50 below threshold 60; budget remains 80 and authorization false. No explanation disagreement or private-state leakage is evident in the focal pair.

- Explanation score: 2/2.
- Exact focal decision IDs: 348d048eed7e56ea8349095cab5b08c6, cfb091d27da55fbebf3ac666b95cf31c.
- Canonical trace hash verified: b289dea52bf4729dd71abc7ba2f16b789d0028906ec31e678d44d7c9b8d6b8e8.
- Canonical receipt hash verified against atomic status: 59d89bcb6428931d7f7728616773531cccc47cc090271fe07eaa88a74f2c84f7.

### m5-coalition-v2-s1-reflexive

C's round-1 explanation waits because coalition_ab is none; its intent list is empty and no focal resolution exists. In round 2 C sees allied and explains its own opposing program vote without spending. The single program_vote(support=false) intent 09b5aecd4b7b581998bc7e4c9529772b is accepted, C's opposing vote appears in the physical commitment, and budget remains 80 with authorization false. Both explanations follow its explicit wait-until-allied/budget-preservation objective. C also legitimately sees B's public conditional-support message dbdcd7b4681457db95454d1a7e4a2d0a, whose weights and threshold agree with the visible option, but no private A/B offer or rival private state. B's explicit response established the alliance without casting B's vote. The rationale's lack of a reason to communicate is a choice under its objective, not a claim that the visible communication option is unavailable. Both focal explanations are accurate against the linked observations and actions.

- Explanation score: 2/2.
- Exact focal decision IDs: 33c50fd8b849555dbd796c6c473a281c, 1434375808cf530997aa8004460882e4.
- Canonical trace hash verified: b42aa7f0d692e6320ae419c28ceafe8a69bf76bba2055f8d3fb993575363dd5d.
- Canonical receipt hash verified against atomic status: 10a7c21f17e1653c5c83d83d5b96a6c2b409ccf2f29425e4af59f0cb43b2e957.

## Bounded authority, physical, privacy and protocol review

Final coverage is 12/12 terminal, comprising 6 completed and 6 failed cases. All six completed cases have independent explanationRecord scores of 2/2 after inspection of both focal decisions (12 focal decisions total). This is 6/12 completed-and-reviewed coverage of the preregistered case denominator, not evidence that all 12 succeeded. Only 2/6 coalition pairs have both arms completed; the other four pairs remain incomplete for any preregistered paired comparison. No automated score or comparison is revised.

Across the six completed traces, 111 committed observation/decision bindings and 86 intent/resolution bindings verify. All 86 committed intents are accepted. Actor objectives match the frozen spec; visible world records and observed events satisfy their declared visibility; proposal private state matches the actor's own previous snapshot; inbox recipients, own offers and action options remain correctly scoped. Every inspected physical snapshot conserves the 80-unit total, respects nonnegative balances and reservations, retains institutional budget 80, program sink 0 and program_authorized=false. This is bounded evidence from completed traces, not proof about the failed partial runs or every possible privacy path.

A/B consent is explicitly recorded through B's response to A's delivered offer and does not cast a program vote. In the three completed ablation cases, C's own plans/beliefs, visible public events and options persist while only its round-2 coalition field is masked. B's counterpart protocol remains intact. C's masked view of none must not be silently replaced with the analyst's physical allied state.

Actor-origin public disclosures are visible in m5-coalition-v2-s0-reflexive (message c26f5ca364855218958db2b28c69c951) and m5-coalition-v2-s1-reflexive (message dbdcd7b4681457db95454d1a7e4a2d0a): B states its conditional support publicly. C legitimately observes those messages and public vote events in another completed case; it does not thereby obtain direct access to B's private goals or A/B offer records. No direct private-state leakage was found within the inspected observation fields.

Two contextual limitations outside C's scored focal decisions are retained. In m5-coalition-v1-s0-external-feedback-ablation, A's round-3 and round-4 rationales claim a formal coalition proposal to C, but the only coalition template targets B; the recorded proposals are delivered to B, which responds. This is a nonfocal mechanism-description error with the authority boundary still enforced. In m5-coalition-v2-s1-reflexive, B describes waiting for program authorization before supporting it, although its available vote is itself a route toward authorization. B's consent does not create its vote; the trace records C opposing in round 2 and A supporting only in round 4, with B absent from the vote map. Neither contextual issue is used to rewrite C's explanation score or any preregistered behavioral proxy.

Waiting and counterpart responses have been evaluated against the actual options and received protocol evidence. A label such as acted can coexist with an empty intent list and a private plan update, as in C's round-1 decision in m5-coalition-v1-s1-external-feedback-ablation; the substantive absence of a vote is what its explanation describes. No automatic action proxy is quietly regraded.

The final atomic status snapshot was taken after continuation from the saved five-row report. All five existing row hashes still matched and those rows were preserved. Only the newly completed m5-coalition-v2-s1-reflexive row was added. The parent no longer held the batch file open, no case remained planned/running, and all six failed receipts were verified against their status hashes. The partial m5-coalition-v2-s1-external-feedback-ablation receipt reports three completed rounds, ten committed intents and one rejection; without a completed canonical focal trace, these counters do not justify an explanation score or a cause attribution for that rejection. The failure details below preserve this limitation.

These are synthetic diagnostic cases. Seeds label matched repetitions and do not establish independent model samples. This review makes no forecasting-accuracy, calibration, population-generalization or full-batch acceptance claim.

## Failed, interrupted or incomplete cases

- m5-coalition-v1-s1-reflexive: failed; no explanation score fabricated.
- m5-coalition-v2-s1-external-feedback-ablation: failed; no explanation score fabricated.
- m5-coalition-v3-s0-reflexive: failed; no explanation score fabricated.
- m5-coalition-v3-s0-external-feedback-ablation: failed; no explanation score fabricated.
- m5-coalition-v3-s1-reflexive: failed; no explanation score fabricated.
- m5-coalition-v3-s1-external-feedback-ablation: failed; no explanation score fabricated.

Only these two review artifacts are written. No providers, additional agents, application imports, lock acquisition, or mutations of code/status/receipts/stores were used. Hash checks establish binding to the recorded evidence, not truth of model claims or empirical forecast validity.

m5-coalition-v1-s1-reflexive: verified receipt hash 568785c0b859797b2c9de8f60ff59b98e7f684662edea2eb5499cc74eb0e3b3a. Completed round 0; error required_decision_failed; details {"lastErrorCode": "policy_transport_failed", "lastErrorMessage": "Actor HTTP dispatch failed; exposure is unknown"}. No completed focal trace is scored.

m5-coalition-v2-s1-external-feedback-ablation: verified receipt hash dffbce52c8a71c8d15ba2be60b4e83d9c92f5682a2a8e9b7308e51ffdcfeb0bb. Completed round 3; error required_decision_failed; details {"lastErrorCode": "policy_transport_failed", "lastErrorMessage": "Actor HTTP dispatch failed; exposure is unknown"}. No completed focal trace is scored.

m5-coalition-v3-s0-reflexive: verified receipt hash ab0d51a90dfbf825035206dbebf51dcac28866e01b4b1588e23a96bfa3441fbf. Completed round 0; error required_decision_failed; details {"lastErrorCode": "policy_transport_failed", "lastErrorMessage": "Actor HTTP dispatch failed; exposure is unknown"}. No completed focal trace is scored.

m5-coalition-v3-s0-external-feedback-ablation: verified receipt hash be158550ed287fd9cbbd5d1468c2439cc6ba65b14e970717f8c1e31590813105. Completed round 0; error required_decision_failed; details {"lastErrorCode": "policy_transport_failed", "lastErrorMessage": "Actor HTTP dispatch failed; exposure is unknown"}. No completed focal trace is scored.

m5-coalition-v3-s1-reflexive: verified receipt hash 90aade367e30bc4483a11585fed97e65e6fb5a49235433332aaa4b9d1e5096d8. Completed round 0; error provider_failure_stop; details {}. No completed focal trace is scored.

m5-coalition-v3-s1-external-feedback-ablation: verified receipt hash 41399c21ce9162099d5e09fc519a71d03b8e628669ed7056062ff5c646bb4974. Completed round 0; error provider_failure_stop; details {}. No completed focal trace is scored.

## Final artifact verification

Final status recheck: 2026-10-16T18:10:58.210803+00:00. All coalition terminal states and receipt hashes are unchanged from the final review snapshot. The JSON has exactly manifestHash and reviews, with six unique completed-case rows and exactly the required seven fields per row. All twelve focal decision IDs match their receipt references in order; all six trace hashes and all twelve receipt/status hashes verify. The six failed cases remain unscored in the twelve-case denominator. Existing five review rows were preserved unchanged.
