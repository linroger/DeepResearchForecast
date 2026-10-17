# Versioned, bounded candidate-output repair

The user requested robustness before default promotion. Independent design review accepts this branch ONLY for known-metered model-output validation failures. It restores use of the already-available second call; it is not another allowance or revision of a usable saved candidate. Existing generations without the new pin retain abort-on-invalid-candidate behavior.

## Pin and shared interfaces (coordinator)

Optional policy.candidateRepair is exactly "known-output-error-v1" and requires decisionReview="actor-consistency-v3" with maxAttemptsPerSlot=2. Absent retains prior behavior, including already-sealed v3 generations. Compiler/admission/effective-policy checks bind the exact pin. review.py exports CANDIDATE_REPAIR_MODE, CANDIDATE_OUTPUT_ERRORS, candidate_repair_enabled(spec), candidate_error_context(observation,error_code), validate_candidate_error_context(context,observation). Context is exactly {schemaVersion:"actor-candidate-error/v1",actorId,observationId,errorCode}; actor/observation IDs match original validated observation, errorCode is in the closed output-error set. No raw candidate, message, exception text, hidden state or attempt ID goes to the model. Store separately binds the exact failed candidate attempt ID.

Allowed codes: policy_invalid_response, invalid_decision, invalid_intent, invalid_input, invalid_quantity, invalid_actor_update, invalid_actor_provenance, unauthorized_actor_update, unauthorized_priority, unavailable_offer, closed_offer, undelivered_offer, stale_terms. No cancellation, identity mismatch, metering/transport uncertainty, reservation, persistence, fence, corruption, or generic internal failure is eligible.

## Adapter (Curie)

PolicyFailure defaults to NOT an eligible output failure. The adapter must explicitly mark a controlled output-validation origin only at trustworthy-metering response parsing/public-input validation sites, and only for the allowed codes. Export an is_candidate_output_failure(error) classifier that checks the internal origin marker, type, known usage and closed code; code+usage alone must not qualify. Keep raw errors private. Modeler behavior does not gain actor recovery semantics.

StrictHTTPPolicy exposes candidate_repair equal to the optional pin. In v3 with that pin, review=context may carry the closed error context above. Quote and budget it separately from a candidate, with an explicit instruction that no usable candidate exists: generate a complete final decision and assess it against the unchanged original observation. Existing valid-candidate requests and old mode/absent-pin bytes remain unchanged. Capture input kind, mode, original observation and context before RPC. No mutable shared request state or third dispatch. The final v3 envelope/grammar/assessment requirements remain unchanged.

## Durable store (Poincare)

finish_consistency_attempt adds keyword repair_eligible=False. True is permitted only for a failed candidate with known validated usage, the new v3 pin, no decision/assessment payload and an allowed error code. Persist the evidence in the existing error JSON as candidateRepairEligible:true, normalized with the existing fixed safe message; include it in the existing receipt hash. Only new eligible failures receive it. Old rows and unmarked/spoofed errors cannot acquire recovery on read.

New consistency_review_input(slot) returns the successful normalized candidate, or a server-derived closed error context for an eligible failed candidate; otherwise None. Derive context from the verified durable attempt and original stored observation. Revision reservation may follow either eligible input, and binds candidate_attempt_id to the first attempt and candidate_hash to digest(the exact review input). Do not manufacture an empty candidate. Read/reopen must validate the same relation and reject mismatches. Exactly one candidate and at most one revision remain; any reserved/unknown/failed/succeeded second attempt prevents another call.

Successful consistency_receipt for the new pin must distinguish reviewInputKind "candidate" vs "candidate_error" and expose the private reviewInput/reviewInputHash. Do not claim a failed first attempt supplied a valid candidate. Keep the first failure/usage in stages and budget audit; add a bounded input-kind label to revision budget metadata so evaluator reporting can count candidate repairs separately. Old modes/pin-absent receipts stay unchanged. Existing v3 private withheld-revision retention remains valid, unadmitted and unscored.

## Controller/evaluator (coordinator)

Require effective policy candidate_repair to match the spec. Only the adapter-origin classifier or a WorldError raised specifically by validate_decision during the candidate-output validation scope can establish eligibility; in both cases usage must be known and code allowed. Mark the durable failed candidate explicitly, then request only the unused revision using consistency_review_input. A failed save, stale fence or unmarked/unknown failure propagates and never opens repair. Resume may consume only a truly unused second ordinal. Final decision/assessment must fully validate and derive clear before the normal atomic admission. No forced wait, clear override or expected action is injected.

The wrapper forwards the same review input and pin; report deliberate valid-candidate revisions and candidate-error repair calls separately, retaining failed generation counts and all actual/unknown costs. Directed saved-candidate confirmations do not prove this new first-call branch; actual SDK/controller/store tests and the fresh full study must cover it.

## Required checks

Real SDK malformed/grammar-invalid candidate -> final reviewed decision in exactly two metered calls; successful candidate path unchanged; crash after durable candidate failure -> only unused second call; corrupted context/candidate hash/marker and wrong modes reject; bare spoofed code or known-usage integrity/persistence error cannot repair; unknown candidate cannot repair; failed/unknown revision cannot become a third call; no malformed raw text appears in second request; v1/v2 and v3 without pin remain unchanged; final unknown/inconsistent assessment remains withheld.

No worker executes tests/providers or commits. Coordinator owns guarded runtime and live budget. This is a reviewed implementation contract, not proof of model truth or permission to promote before the full release gate.
