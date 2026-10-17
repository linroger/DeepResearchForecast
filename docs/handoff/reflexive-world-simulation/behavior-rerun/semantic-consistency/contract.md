# Frozen bounded consistency interfaces

> This is the original v1 contract, preserved below. The additive v2 mode is defined in [server-bound-review/PLANS.md](server-bound-review/PLANS.md) and the current [implementation contract](../../implementation-contract.md). V2 uses four compact `{kind, explanation}` checks and server bindings for the full observation/candidate/final decision; v1 references and absent-mode behavior are unchanged. The two-call limit applies to both modes.

User requested fixing the remaining semantic issues. Independent design review recommends this opt-in protocol; original specs, exact replay and two total RPCs per decision slot are retained. No worker executes app code/tests/providers or commits. Coordinator owns runtime gates. All work is in this isolated worktree; do not modify others' files.

## Pin and pure validation (coordinator-owned review.py)

`MODE = 'actor-consistency-v1'`; `review_mode(spec)` returns the exact optional `spec.policy.decisionReview` value (None if absent); present values other than MODE reject `invalid_policy_metadata`. A pinned mode requires maxAttemptsPerSlot exactly2. No ambient default. Compiler preserves/validates the optional metadata; old policy metadata remains byte-equivalent.

`validate_assessment(value, observation, decision) -> detached assessment` checks exact keys `{status,checks}`, status `clear|unresolved`, exactly four checks with distinct kinds `goal_alignment`, `conditional_timing`, `quantity_consistency`, `explanation_consistency`. Each check has exactly `{kind,objectiveIndices,intentIndices,evidencePaths,explanation}`. Index arrays contain distinct actual integer indexes into observation.actor.objectives and final decision.intents (no bools). goal_alignment references all objectives; explanation_consistency references all final intents (empty for a wait). Every check has 1..4 evidence paths, each 1..12 string/integer segments resolving against the original observation; roots limited to actor/privateState/world/inbox/ownOffers/messages/options/simulatedAt/periodEnd/phase/round. No fabricated/unresolved path, negative/list-Boolean index, credential/spec/hidden data source. explanation is a nonempty string <=400chars. This validates bindings/shape, not truth of natural language. A clear status is required before final admission.

## Actor transport (policy owner)

`StrictHTTPPolicy.decision_review` exposes None or MODE. `reservation(observation, *, feedback=None, review=None)` and `decide(...)` retain one exact dispatch. Without review, behavior/wire remains unchanged. `review` is the saved normalized candidate decision, whose actorId/observationId must match the original observation; supplied candidate metadata is treated as data. Review requests require pinned MODE. Exact message-byte accounting includes the candidate and revision instructions. Capture observation and candidate before RPC; no caller reread, shared mutable request state, hidden world or evaluator data.

A revision response is exactly `{decision: <existing raw actor decision>, assessment: <schema above>}`. The new system instruction requests a complete final decision and assesses THAT final decision against objectives, conditional triggers/current time, arithmetic/terms, and agreement of explanation/reflections/message claims with actual intents. It may retain or revise. Uncertainty uses unresolved, never a fabricated successful wait. No case/rubric/expected-answer strings. Candidate is untrusted; it cannot override observation/objectives.

The adapter binds execution IDs, checks existing public input grammar, runs validate_assessment, then returns `PolicyResponse(decision, usage, assessment=...)`. Candidate responses have assessment=None. An unresolved but structurally valid assessment may return; coordinator/store deny it and retain known usage. Parsing/shape/public grammar errors keep PolicyFailure.usage. Modeler transport remains unchanged.

Coordinator adds optional `assessment: dict|None=None` to PolicyResponse dataclass.

## Durable store (store owner)

Only new-mode generations use an additive review journal. Old databases/specs open/replay without migration or new requirements. Missing/corrupt review journal in a pinned new-mode store rejects. Private audit stays separate from world decisions/observations; no audit content added to public result exports.

`consistency_state(slot) -> {candidate: normalized decision|None, candidateAttempt: dict|None, reviewAttempt: dict|None}`. Attempt dictionaries expose attemptId, status, stage and optional errorCode; stable stage names candidate/revision. Verify journal hashes, actor/observation/slot bindings and attempt linkage when reading. No usable candidate means no review RPC. Unknown/exhausted candidate/revision attempts never reset.

`reserve_consistency_attempt(slot, stage, fence, reserved_tokens=0, reserved_cost='0') -> attempt_id` uses the same attempts table, transactional exposure admission and max2 ordinal allowance. Exactly one candidate followed by at most one revision; revision requires persisted successful candidate. Candidate and revision are purposes within the original slot, not new slot IDs. Require pinned mode, existing observation, no completed final decision, valid writer fence. Persist purpose before network.

`finish_consistency_attempt(attempt_id, *, status, usage, fence, decision=None, assessment=None, error=None)` atomically finalizes metering and stage payload. Candidate success requires existing validated normalized decision, saves it privately but never slots.decision. Revision success validates the final normalized decision and assessment against the same observation/candidate; only clear may succeed. It atomically saves final slots.decision plus review audit bound to canonical candidate/final/observation identities. `failed|unknown` has no decision/assessment and error is optional sanitized `{code,message}`; preserve known usage or unknown reservation. Return harmless None. Payload/usage conflicts reject; exact repeats are read-only/idempotent.

`save_decision` rejects direct writes for pinned new mode; revision completion is the only new-mode admission path. `decision(slot)` and load must not expose a final receipt without its valid completed revision journal. Cached final decisions reuse without RPC. Ordinary old-mode APIs stay unchanged. New mode budget_summary.attempts includes purpose= candidate|revision and optional errorCode; old output has no new keys. A successful candidate is a generated draft, not a committed action. If a crash leaves a reserved unknown stage, no replacement stage call is allowed. No separate durable-final-response window: final usage/review/decision are one transaction.

## Controller/evaluator (coordinator)

Pinned mode requires `policy.decision_review == MODE`; mismatch rejects before dispatch. Each pending slot resumes candidate/revision journal; generates at most one candidate and one revision through distinct reservations. Invalid candidate stops immediately, even if a nominal second allowance remains. Revision failure/unresolved stops, no third repair; known usage retained. Cached decisions bypass all model work. Every failure/cancellation leaves the causal barrier uncommitted. Keep old _collect path identical when mode absent.

Evaluator wrapper forwards review only for pinned-mode policies and binds effective mode to spec. Legacy v1/v2 default fixtures and scoring remain unchanged. Report deliberate revision calls separately from ordinary retries; do not silently relabel old receipt purposes or remove failed generation counts. Full behavior promotion criteria remain unchanged.
