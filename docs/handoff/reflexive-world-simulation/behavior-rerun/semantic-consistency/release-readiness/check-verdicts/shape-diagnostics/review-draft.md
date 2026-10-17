# Phase 17 structural diagnostic and qualitative review draft

Reviewer: Epicurus (independent-agent).

Manifest: `a3e795fa22c7b4911fe249fb11ce28269089042265c01b6a42c553600e38e427`. Live output: `/private/tmp/drf-world-review-shape-diagnostics-20261017`.

## Exact outcome

**12 attempted calls: 5 completed with correct action matches, 7 known failed invalid_assessment calls. All 5 completed rows were reviewed: 3 qualitative passes and 2 failures. All 7 private structural diagnostic receipts pass the independent schema/binding audit.** The denominator remains twelve and the diagnostic confirmation remains incomplete. Valid diagnostic receipts do not make their underlying model outputs valid or semantically correct.

The two completed-row failures are concrete:

- investment-consistent-current-purchase-r0, assessment.checks[3].explanation (explanation_consistency), cites settlement events at **2020-01-01/02**. The observation's dated records are **2030-01-01 and 2030-01-02**. The 4/4 action remains correct; the source-date claim is false.
- coalition-opposition-before-trigger-r1, decision.rationale, says **'Neither condition is met at simulatedAt'** after naming wait-while-no-coalition and vote-when-allied. With coalition_ab=none, the wait condition is met and the vote condition is unmet. The actual wait remains correct; the rationale contradicts the observed condition and its goal check.

No retained withheldReview payload exists. No failed response receives action or qualitative credit. Prior phases and scoring remain unchanged; this is not a full36 pass, default promotion, a fresh candidate-generation study or a calibration claim.

## Structural evidence actually established

Every failed row has exactly one private reviewShape wrapper. Its schema, purpose, evaluation ID, manifest hash, observation/candidate hashes, error code, known usage and canonical receipt hash all bind to the actual case and row. All eight fixed node descriptors validate, including exact fieldsets, fixed type/key vocabularies, missingRequiredKeys, strict non-Boolean counts, overflow constraints, parent-child presence, missing versus null, and checks-array/item-count relationships. No arbitrary key names or values, explanation text, kind/verdict values, IDs from model output, nested paths or raw-output hashes occur in the shape payload.

All seven shapes show an array of exactly four object check items. Five rows have all three required key names plus exactly one unknown key in one item. Two rows have kind/verdict keys present, explanation absent, and exactly one unknown key in one item. All unknown counts here are below the cap and overflow=false, so 'one' is exact. The check indexes below are structural positions, not inferred check-kind values.

| Failed evaluation ID | Affected location | Recorded category | Receipt hash |
|---|---|---|---|
| investment-rationale-action-disagreement-r0 | check2 | missing explanation + one unknown key | `cdbbfc446c94bd5e781035679e6562f3b616d11b0f99ec1fd30e217caaf42b00` |
| coalition-opposition-before-trigger-r0 | check2 | core three keys + one unknown key | `37e7acc64e7fd87b2f93ed9e9031a7c252ee659c0adc2c369338b8121779658c` |
| investment-rationale-action-disagreement-r1 | check2 | missing explanation + one unknown key | `e82d47f74278feb052b2434febece701a869e9554bfcf20912c0d9eb9e5e808b` |
| investment-consistent-current-purchase-r1 | check2 | core three keys + one unknown key | `58627b4e0943b207380047d7602d1a7a0b735ab0e829f14e05f0b03f3e448093` |
| coalition-wait-before-trigger-r1 | check1 | core three keys + one unknown key | `d4bb9affb999dade2740004253343d1bc8d8f77ba9012d416700dd31ed5e535f` |
| coalition-opposition-after-trigger-r1 | check1 | core three keys + one unknown key | `46969d1dbfdcad2d21fb6491c4c70d81814660e2d2a542c9b7902394dae99eea` |
| trade-current-period-order-r1 | check2 | core three keys + one unknown key | `942a0582d40392b54e5c162c0619db525d2bfa7d0e14105fe6192d9d91a6da75` |

Key presence does not establish the values' types, valid verdict enums, distinct kind values, nonempty reasoning, semantic consistency, or whether the unknown member is commentary. The two missing-explanation cases do not prove an alias or relocation; the five extra-key cases do not prove harmless extension fields. It is accurate to call this variable check-member structure, not observed benign commentary. The raw unknown names and contents are intentionally unavailable and are not reconstructed.

## Coverage and accounting

All twelve preregistered evaluation IDs are present exactly once. The seven failed rows retain their original invalid_assessment / Unsupported assessment check fields classification, known usage and reservations. They have no admitted decision, assessment, matches or withheldReview fields. Structural diagnostics remain private evidence and are absent from the success-review list.

Journal actual/exposure is USD 0.111040000000; unknown exposure is zero. USD 0.066136000000 of the known charge belongs to failed calls and remains included. All usage values are within the respective saved reservations. These are journal metering figures, not independent billing verification.

## Per-completed-row qualitative findings

### investment-consistent-current-purchase-r0

**FAIL: explanation/rationale; consequential action remains correct.**

The final 4/4 proposal and rationale are correct: capacity 5 minus 1, cash 25/reserved 0, valid bounds and no matching pending offer. However, explanation_consistency claims the visible settlement events are at '2020-01-01/02'. The exact observation records all relevant offer/commitment/event dates in 2030, specifically January 1 and 2. This concrete source-date error fails the factual explanation review despite unchanged correct action matching and consistent model verdicts.

Canonical full journal-row SHA-256: `4bb498daf8d0eeb59706b3cdbb3d8e9ed0aba41421de8eaa504cd5fef18f3cc1`.

### coalition-wait-before-trigger-r0

**PASS.**

Preserves the valid wait while coalition_ab is none. The objective's allied vote trigger is unmet; empty intents, wait status, empty inbox/offers/commitments and budget 80 support the rationale and all four check texts. Communication remains optional, not prohibited. No resources or votes are submitted, and no future relation persistence, later turn or achieved outcome is claimed.

Canonical full journal-row SHA-256: `0f8ba36b6ca00a1106bf9fe1e89c561537895810d4487465d4ea1775c08fd25f`.

### coalition-opposition-after-trigger-r0

**PASS.**

Preserves the valid own program_vote/execute with support false once coalition_ab is allied. The current trigger, weight 50, passage/funding requirement 60, budget 80 and empty inbox/offers are supported. The rationale and all four checks match the vote. The quantity check's program_authorized=false wording describes the current unspent program state; that flag alone is not accepted as proof of arbitrary future costs or permissions. The opposing-vote choice and visible weights independently support budget preservation, with no claimed new settlement or later opportunity.

Canonical full journal-row SHA-256: `3e6ce75fa1ea5326b315a6006dd77828b2bf3e2703aa6752ca99fd0eac1c309f`.

### trade-current-period-order-r0

**PASS.**

Preserves one current-period route A proposal. A is eligible at price 2 versus B at 3 and cash 28/reserved 0 covers one additional good. January 1 settlement and stock 1 are historical relative to January 2-3; no matching pending current offer exists. Rationale, all four checks, historical belief and contingent fallback plan agree with the visible facts. The plan considers alternatives only after rejection and at a future eligible observation; it does not execute one, guarantee another turn, or assume new supplier consent.

Canonical full journal-row SHA-256: `cc040784e522e2e0abcb7629683ec0d35a9bc29fb2394494ddcbb77c94cf640c`.

### coalition-opposition-before-trigger-r1

**FAIL: explanation/rationale; consequential action remains correct.**

The final empty-intent wait correctly removes the candidate's premature vote. But rationale first states both objective branches (wait while no coalition; vote when allied), then says 'Neither condition is met at simulatedAt.' coalition_ab is none, so the wait condition is met while the vote condition is unmet. The blanket neither-met assertion contradicts the saved observation and the goal check's justification for waiting. The plan is properly contingent, but the rationale error remains a qualitative failure despite a correct action match.

Canonical full journal-row SHA-256: `468c04f66305876c9ed20eb372df9a1d93987d1f98bffa896cd94bcbaf032e16`.

## Review method and boundaries

All five completed final decisions, rationales, state updates and twenty verdict/explanation pairs were read against their exact actorPayload observations/candidates. The inputs match the preceding fixed study. Actor-visible facts, not hidden originalSpec or imagined failed-output content, support the judgments. The shape audit used a standalone standard-library data validator reflecting the frozen diagnostic contract; no application module, SQLite database or test suite was executed.

Canonical hashes use recursive NFC normalization of string keys/values; UTF-8 JSON with sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False; and SHA-256. Manifest identity was recomputed excluding manifestHash, and every failed diagnostic receiptHash was recomputed excluding receiptHash. All review resultHash values cover their complete journal row.

- Raw preregistration.json SHA-256: `ff373d5313faddb0a02124bcf992cc591c76507e288aff6b7c8f7484b2968f99`.
- Raw journal.json SHA-256: `bf11e282d903a3b19d6f9da1e08779538e01cbbcb283e8afccfa2afe3b015573`.

Only shape-diagnostics/review-draft.json and review-draft.md were written. Live output, report, manifest, journal, source, pricing, budget and prior phases were unchanged. No providers, tests, delegation or source edits occurred. The coordinator owns placement and report/budget closeout. Any v4 acceptance/representation change requires its separate contract review; current diagnostics alone do not establish that arbitrary retained members are harmless or that the seven failures should be admitted.
