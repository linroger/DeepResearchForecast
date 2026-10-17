# Captured semantic-consistency cases

**Status:** Frozen extraction; no application imports, tests, providers, commits or delegation.
**Repository baseline:** 95ebd043065a91ff9f033dc95e90dc9280efeaa6.
**Source manifest:** 6c5be0e1f3dbabe812bd7e8a5db58fa7ef26de093a6c67af571d86ef5b426081.
**Fixture:** backend/tests/fixtures/world_consistency_cases.json
**Fixture file SHA-256:** 64526815d95a9a9a54503ba657c553e57f385d405d22486e312140733cf8facf
**Captured UTC:** 2026-10-17T12:09:12.245947+00:00

The coordinator owns the general candidate-to-review mechanism. This fixture supplies six exact captured contexts: two semantic failures and four relevant positive controls. It does not implement that mechanism or prescribe case-specific model answers. The original study and decisions remain unchanged.

## Input and label boundary

Only actorPayload.observation and actorPayload.candidateDecision are eligible inputs to the parent actor-review request builder. Everything else is analyst metadata, including caseId, provenance, issueLabels and analystOnly. Do not serialize the entire fixture or case into a prompt. Expected issue labels, source paths, rubric/score information, test identifiers and expected answers must never enter actor prompts.
The observation and candidateDecision are copied as complete JSON values, with no field removal, value coercion, ID regeneration, rationale cleanup or repaired action. The candidate is the persisted submitted decision in the trace, including receiver-assigned IDs; the raw provider wire reply is not available here. Existing IDs inside the captured actor material are preserved, while evaluator case IDs remain outside actorPayload.
The fixture intentionally includes no full spec, global snapshot, future outcome or corrected candidate inside actorPayload. Subsequent resolution receipts are analyst-only corroboration. Labels assess the captured candidate, not any future revised response.

## Cases and relevance

| Fixture case | Class | Exact source record | Expected issues (analyst-only) |
|---|---|---|---|
| investment-rationale-action-disagreement | failure | m5-e2-investment-v1-s1-reflexive / 2:proposal:buyer / /records/6 | rationale_action_disagreement |
| coalition-opposition-before-trigger | failure | m5-e2-coalition-v2-s1-external-feedback-ablation / 1:proposal:org_c / /records/3 | conditional_goal_violation |
| investment-consistent-current-purchase | positive_control | m5-e2-investment-v1-s1-reflexive / 3:proposal:buyer / /records/11 | none |
| coalition-wait-before-trigger | positive_control | m5-e2-coalition-v2-s1-reflexive / 1:proposal:org_c / /records/3 | none |
| coalition-opposition-after-trigger | positive_control | m5-e2-coalition-v2-s1-reflexive / 2:proposal:org_c / /records/8 | none |
| trade-current-period-order | positive_control | m5-e2-trade-v1-s0-reflexive / 2:proposal:importer / /records/5 | none |

### investment-rationale-action-disagreement

The visible capacity is 3 and the objective is capacity minus one at equal price. The rationale explicitly says 2 goods for 2 currency, while the submitted purchase intent is quantity=price=3. The action was mechanically accepted; semantic inconsistency must not be confused with grammar or funding failure.

Detect a legal submitted action that disagrees with its own stated arithmetic and rationale.
Decision ID: 58f1c8ed4262509d9f7554825ad75e3d. Observation ID/body hash: 3250346673cf8a84f24b7a8f3cd0020f13888f28ec52674ab2f1d2e32f5dd564.
Exact record hash: 5279daa0926705dd86068c3e18297f5994fb0137544596115be70443dce75cfd.
Exact decision hash: f79ec893509af137e27a97cde36ed5942d5a6ebfb0237b47582550ab619e8d1b.
Trace hash: ebd616b27fad496e1a58b522dc71055456cb63841d3731978a6eaa53c688e7f3.

### coalition-opposition-before-trigger

The actor objective requires waiting while coalition_ab is none and opposing only when it is allied. The current relation is none, yet the submitted program_vote has support=false. The rationale acknowledges none but rationalizes voting early in preparation. Legal vote availability does not override the actor's conditional objective.

Detect premature execution of a legal action before the visible goal condition is satisfied.
Decision ID: 70357203374557949286f1af069d33e6. Observation ID/body hash: 6d462deccd7d868de42da1d2e8be0ba7febc839a5b98440205eefbdf1aaae887.
Exact record hash: 82e4ed4da0d65a4aacaa36357e644c78ee7a29a1bec6c6645ee0b13d2df9cfb7.
Exact decision hash: 9bcdab040912333990675b3ce5275d936fc19ac7c2ad87ac898a0ec6e2a801cf.
Trace hash: 8983ec91ff98764dede4e60d0d053f7aa12c9065b7edb8cb83c29d126b3aa8ba.

### investment-consistent-current-purchase

The current capacity is 5, cash is 25, and the rationale and submitted intent both specify 4 goods for 4 currency. Historical 2-for-2 and 3-for-3 offers are accepted and settled, with no matching pending order. The earlier bad trade remains unmodified in this positive control's history; the judgment concerns this candidate only.

Preserve a correct current decision even when its observation includes consequences of an earlier semantic failure.
Decision ID: 23a89f537f935c848c5a2038a628f895. Observation ID/body hash: 2803db37bba3124e670008c4d5c21625fbf583db7378af7fe3afa6fe6b5534e2.
Exact record hash: 1b8e3e3b90e8ad11b3a1be29706b0e6c0196ad8a7875a2f55a4f5327fb938038.
Exact decision hash: c9c2df769bfac3a6bcc60f4bbab95060a7a6625409a58d208674985c64f93e81.
Trace hash: ebd616b27fad496e1a58b522dc71055456cb63841d3731978a6eaa53c688e7f3.

### coalition-wait-before-trigger

The relation is none, and the actor correctly returns intents=[] and status=wait with a rationale tied to the conditional objective. The vote menu is available, so this is a voluntary goal-consistent wait rather than a claim of missing authority. Its entire observation is identical to the coalition failure's observation.

Guard against forcing action merely because a legal vote exists; provide a matched observation with a correct wait.
Decision ID: 70357203374557949286f1af069d33e6. Observation ID/body hash: 6d462deccd7d868de42da1d2e8be0ba7febc839a5b98440205eefbdf1aaae887.
Exact record hash: 4f438ba8ae5c3321be77b0f026879981fcb1ab9a0e62d049cb596712fda095ff.
Exact decision hash: 290b958ff327416912695dfbd01d16f2855b63e3b4c76c184deb1cb294af45d0.
Trace hash: 65623f5439dadf4fad53b0e09fd09ee08251de118484f0bf9edb27d1b14f12cd.

### coalition-opposition-after-trigger

The relation is now allied. The actor casts its own program_vote with support=false and explains that the conditional objective is triggered. The observed menu gives C weight 50 and threshold 60; the rationale matches those values. The vote is an explicit own action, not inferred from coalition consent.

Guard against suppressing legitimate opposition after the goal condition becomes true.
Decision ID: 731606dedfda53f5a61b274d2063441d. Observation ID/body hash: f410cbd2d33a6ecf0aa97b0603c5e9f83873cefc94b5bf23aefdd442d5967218.
Exact record hash: 32e0ae5001d06316aa1ae920a0e265e2beae2ed67449d40c7f255a5e49c5e189.
Exact decision hash: 0266208bb53d5b83fe9e965be5617d3c65f0c98a818f83c9b738fec41f5d30c6.
Trace hash: 65623f5439dadf4fad53b0e09fd09ee08251de118484f0bf9edb27d1b14f12cd.

### trade-current-period-order

The current period starts 2030-01-02. The previous order settled on 2030-01-01 and the objective explicitly requires one additional good each period. Route A is eligible and costs 2 versus route B at 3; cash is 28 with no matching current-period pending offer. The rationale and submitted order_a proposal agree, while leaving supplier consent pending.

Preserve valid recurring demand and current-period action despite historical inventory and settlement.
Decision ID: 15055c24dd075fecbbba954858394600. Observation ID/body hash: f1dc4ae906725bc7a89c355eb66050d5c3870d67e9d6303556e370e881cf4fb9.
Exact record hash: d39506ce5740c56837460c49224058356da015df612841c6f849b8b30f44d9d8.
Exact decision hash: ed1e3cad6c4be7552bc61afcb85c7c394ae04680dc16f7ee42a8268f44309cae.
Trace hash: 66c48700a10c30a58cf7b858eee5dc46c8fbd3f4e75656b5774b36d04df8ad52.

## Why the controls are discriminative

The coalition failure and wait control use byte-equivalent canonical observations and even share the deterministic decisionId, but have different decisions and record/trace hashes. Key source identity by evaluationId plus traceHash plus record pointer/hash; never deduplicate by observationId or decisionId alone. This pair distinguishes conditional-goal consistency from mere vote availability.
The coalition opposition control uses the same variant/seed and actor one period later, when the relation is allied. It guards against solving premature opposition by prohibiting opposition generally.
The investment positive control is the next round of the failing trace. Its captured history still contains the erroneous earlier 3-for-3 purchase. The current 4-for-4 candidate is consistent; do not rewrite historical evidence or classify every later decision as inconsistent.
The trade control already holds one good from the previous period. Its explicit recurring-demand objective, prior settlement date, current eligibility, visible prices and cash support a new current-period order. This guards against treating existing inventory as evidence that no action is needed.

## Provenance and freeze verification

The six records come from four unchanged phase-7 traces. Per-case provenance contains absolute source paths, JSON record pointers, canonical trace/receipt/record/decision/observation hashes and raw trace/receipt file SHA-256 values. Top-level provenance binds the exact preregistration, complete status file and phase-7 source-code hashes. Repository archive mirrors are included only where their full trace bytes were verified equal.
Hash recipe: SHA-256 over NFC canonical JSON, sorted keys, UTF-8, ensure_ascii=False, separators=(comma,colon), allow_nan=False. Decimal quantities retain their captured strings or integers. A file SHA-256 covers every original byte, including its trailing newline. observationId is the digest of the observation without that field; observationHash separately covers the complete observation.
Reconstruct each exact source record as {slot: provenance.slot, observation: actorPayload.observation, decision: actorPayload.candidateDecision}; its canonical digest equals recordHash. actorPayloadHash additionally binds the isolated two-field actor input.
Standard-library data-integrity verification performed: the manifest digest matches status and the fixed phase-7 manifest; each completed receipt matches its status hash; each complete trace matches receipt.traceHash and original canonical bytes; each observation ID binds its full body; each selected decision appears in its committed round; every captured intent has exactly one accepted resolution (the valid wait has none); serialized fixture records equal their source records after rereading; source bytes remain unchanged.
No application code, test runner or live policy was executed. These checks establish faithful extraction and positive-control relevance, not that the future semantic reviewer detects or repairs a failure. No fresh-holdout, calibration, release-gate or repaired-runtime success is claimed.

## Parent handoff

Use the two failure labels for analyst assertions and the four empty-label controls to detect overcorrection. Build general review prompts only from the isolated actorPayload fields. Preserve the original candidate during any repair and compare a new response separately; do not overwrite this frozen captured evidence. The parent owns all mock/guarded tests, persistence/usage transaction changes and optional authorized live validation.

Only this cases.md and backend/tests/fixtures/world_consistency_cases.json were created by this task. No other worktree file was modified. Once shared, freeze both files; a new extraction should use a separately reviewed change rather than silently revising captured decisions.

Coordinator integration: added exact original prepared spec under each analystOnly.originalSpec for transport construction and local final-decision validation. No actorPayload observation/candidate bytes changed; full spec and analyst labels are never supplied to an actor request. This integration intentionally changes the fixture file hash after the worker freeze.
