# Condition and decision-opportunity explanation repair

The user explicitly requested fixing the two remaining explanation errors and rerunning confirmation within the remaining original budget. This is a narrow continuation of the approved actor-consistency-v2 bug fix, not a new simulation architecture. No additional user approval or budget reset is needed for this scoped work.

## Evidence and diagnosis

Phase11 produced12correct actions and10full qualitative passes. Its investment timing explanation inferred no conditions from an empty priorityRules list despite a conditional objective. Its coalition rationale inferred an extra within-period voting opportunity from a current action menu and possible state change. Both actual decisions were correct; all prior rows remain failed/passed exactly as recorded.

Current run_round gathers one proposal per selected actor, then responses to delivered offers, and resolves chronological state effects. A current menu or conditional plan does not itself install a future action or create another eligible decision. Objectives and constraints are narrative fields and can contain conditions independently of structured priorityRules. The existing v2 prompt states broad principles but does not require a check-by-check examination of those sources or distinguish future world changes from a future turn.

## Narrow change

Only refine _REVIEW_SYSTEM_V2: conditional_timing must inspect conditional clauses in objectives/constraints as well as priorityRules and visible relevant rules/terms, identify each relevant condition as met/unmet/unknown at the snapshot, and never infer absence from an empty priorityRules list. Current menus authorize the current decision only; a plan or empty intents does not register a contingent action or reserve another turn. Future contingent intentions may refer to a future eligible observation but must not promise a decision before periodEnd without explicit scheduling evidence. Apply this to rationale/stateUpdates/messages as well as the assessment, with no forced action or clear verdict.

Keep v2 shape and400character checks, v1/None wire, original observations/candidates, schema, controller/store/kernel, pricing/provider/reasoning/output cap, attempts and scoring unchanged. No regex censor, prose rewriting, hidden-state check, new response metadata, case identifiers or expected domain actions. This is an instruction repair whose semantic effect must be measured; tests do not prove model adherence.

## Acceptance and execution

1. Preserve hashes of every earlier closed phase and current accepted source; reconcile original25USD minus18.913368955664USD =6.086631044336USD. No provider is active.
2. Independent bounded design review while coordinator writes actual SDK request regressions and checks temporal source semantics. Author tests before production prompt changes; run their bounded red under the existing offline guard.
3. Refine only the v2 constant. Focused current-source SDK/v1/v2/controller/store/replay/launcher gate plus exact delta review, without re-running unrelated broad suites.
4. Preregister one new12-call saved-context confirmation with cap1.25USD within the original remaining6.086631044336USD. Same six contexts twice, same criteria and strict all12 qualitative gate. No replacement/regrading of previous rows; no repeated same-treatment calls to seek a pass.
5. Freeze all runtime/tests/pricing, finish all12fixedcalls, independently review all completed actions/rationales/assessments, close report via frozen guarded source, reconcile budget, update issue/handoff/docs and commit only owned changes. Keep world-v1 opt-in and full36gate unchanged regardless of directed outcome.

Coordinator owns policy.py, v2 policy tests and current scoped notes/receipts. Epicurus owns read-only design/source review and later only the new phase's qualitative review files. No worker provider calls. Success means the current confirmation passes all12full qualitative reviews while preserving all actions/controls and prior artifacts; if not, report remaining failures and preserve the denominator.
