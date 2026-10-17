"""One causal barrier for world proposals, recipient responses and durable commit."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

from .contracts import WorldError, clone, require, validate_decision
from .kernel import resolve_round, stage_interactions
from .observations import build_observation, response_actors
from .review import review_mode, validate_assessment


@dataclass(frozen=True)
class PolicyResponse:
    decision: dict
    usage: dict
    assessment: dict | None = None


def slot_id(round_index: int, phase: str, actor_id: str) -> str:
    return f'{round_index}:{phase}:{actor_id}'


def _cancelled(cancel: Callable[[], bool]) -> None:
    require(not cancel(), 'cancelled', 'World simulation cancelled before the next causal boundary')


def _consistent_decision(store, policy, slot, observation, actor_id, phase, fence, cancel):
    """Use two separately reserved stages; only the final revision can act."""
    state = store.consistency_state(slot)

    def dispatch(stage, candidate=None):
        _cancelled(cancel)
        kwargs = {"review": clone(candidate)} if stage == "revision" else {}
        reservation = policy.reservation(clone(observation), **kwargs) if getattr(policy, "external", False) else {
            "tokens": 0, "costUsd": "0"}
        require(not getattr(policy, "external", False) or reservation["tokens"] > 0,
                "unbounded_transport", "External policy must reserve its complete request bound")
        attempt = store.reserve_consistency_attempt(slot, stage, fence, reserved_tokens=reservation["tokens"],
                                                    reserved_cost=reservation["costUsd"])
        usage = None
        try:
            output = policy.decide(clone(observation), **kwargs)
            if isinstance(output, PolicyResponse):
                raw, usage, assessment = output.decision, output.usage, output.assessment
            else:
                require(not getattr(policy, "external", False), "missing_usage", "External policy must return accountable output")
                raw, usage, assessment = output, {"tokens": 0, "costUsd": "0"}, None
            decision = validate_decision(store.spec, raw, actor_id, observation, phase=phase)
            if stage == "revision":
                assessment = validate_assessment(assessment, observation, decision, mode=review_mode(store.spec))
                require(assessment["status"] == "clear", "consistency_unresolved",
                        "The actor revision retains an unresolved consistency conflict")
        except Exception as error:
            usage = usage if usage is not None else getattr(error, "usage", None)
            diagnostic = {"code": error.code if isinstance(error, WorldError) else "policy_decision_failed",
                          "message": str(error)[:400] if isinstance(error, WorldError) else "The decision was unavailable."}
            store.finish_consistency_attempt(attempt, status="failed" if usage is not None else "unknown",
                                             usage=usage or reservation, fence=fence, error=diagnostic)
            raise WorldError("required_decision_failed", "A required consistency stage failed without a replacement allowance",
                             details={"lastErrorCode": diagnostic["code"], "lastErrorMessage": diagnostic["message"]}) from None
        store.finish_consistency_attempt(attempt, status="succeeded", usage=usage, fence=fence,
                                         decision=decision, assessment=assessment if stage == "revision" else None)

    if state["candidate"] is None:
        require(state["candidateAttempt"] is None, "consistency_candidate_unavailable",
                "A prior candidate attempt has no usable durable response; ordinary resume cannot replace it")
        dispatch("candidate")
        state = store.consistency_state(slot)
    require(state["reviewAttempt"] is None, "consistency_revision_exhausted",
            "A prior revision consumed the remaining allowance; ordinary resume cannot replace it")
    dispatch("revision", state["candidate"])
    return store.decision(slot)


def _collect(store, policy, fence: int, snapshot: dict, round_index: int, phase: str,
             actor_ids: list[str], cancel: Callable[[], bool]) -> list[dict]:
    spec = store.spec
    mode = review_mode(spec)
    require(getattr(policy, "decision_review", None) == mode, "policy_review_mismatch",
            "Effective actor review mode must match the prepared specification")
    store.freeze_phase(round_index, phase, actor_ids, fence)

    def decide(actor_id):
        slot = slot_id(round_index, phase, actor_id)
        observation = build_observation(spec, snapshot, actor_id, round_index, phase)
        store.save_observation(slot, observation, fence)
        cached = store.decision(slot)
        if cached is not None:
            return cached
        if mode is not None:
            return _consistent_decision(store, policy, slot, observation, actor_id, phase, fence, cancel)
        feedback = None
        for _ in range(spec['limits']['maxAttemptsPerSlot']):
            _cancelled(cancel)
            policy_kwargs = {'feedback': feedback} if getattr(policy, 'supports_feedback', False) else {}
            reservation = policy.reservation(clone(observation), **policy_kwargs) if getattr(policy, 'external', False) else {
                'tokens': 0, 'costUsd': '0'}
            require(not getattr(policy, 'external', False) or reservation['tokens'] > 0,
                    'unbounded_transport', 'External policy must reserve its complete request bound')
            attempt = store.reserve_attempt(slot, fence, reserved_tokens=reservation['tokens'],
                                            reserved_cost=reservation['costUsd'])
            usage = None
            try:
                output = policy.decide(clone(observation), **policy_kwargs)
                if isinstance(output, PolicyResponse):
                    raw, usage = output.decision, output.usage
                else:
                    require(not getattr(policy, 'external', False), 'missing_usage',
                            'External policy must return an accountable response')
                    raw, usage = output, {'tokens': 0, 'costUsd': '0'}
                decision = validate_decision(spec, raw, actor_id, observation, phase=phase)
            except Exception as error:
                # A network failure after dispatch has an unknown charge. Retain
                # the full reservation; never log prompt/response or credentials.
                usage = usage if usage is not None else getattr(error, 'usage', None)
                feedback = {
                    'code': error.code if isinstance(error, WorldError) else 'policy_decision_failed',
                    'message': str(error)[:400] if isinstance(error, WorldError) else 'The previous decision was unavailable.',
                }
                store.finish_attempt(attempt, 'failed' if usage is not None else 'unknown',
                                     usage or reservation, fence)
                continue
            store.finish_attempt(attempt, 'succeeded', usage, fence)
            store.save_decision(slot, decision, fence)
            return store.decision(slot)
        raise WorldError('required_decision_failed', 'A required actor decision exhausted its durable allowance',
                         details={'lastErrorCode': feedback['code'], 'lastErrorMessage': feedback['message']})

    if not actor_ids:
        return []
    decisions = []
    # All slots share the same immutable snapshot. Arrival order cannot advance
    # the clock; peers that succeed remain durable if another slot fails.
    with ThreadPoolExecutor(max_workers=min(spec['limits']['maxConcurrentCalls'], len(actor_ids))) as executor:
        futures = [executor.submit(decide, actor_id) for actor_id in actor_ids]
        errors = []
        for future in as_completed(futures):
            try:
                decisions.append(future.result())
            except Exception as error:
                errors.append(error)
        if errors:
            raise errors[0]
    return sorted(decisions, key=lambda item: item['actorId'])


def run_round(store, policy, fence: int, *, cancelled: Callable[[], bool] = lambda: False) -> dict:
    _cancelled(cancelled)
    spec, before = store.spec, store.head()
    round_index = before['round'] + 1
    require(round_index <= len(spec['periods']), 'horizon_complete', 'The declared horizon is already committed')
    participants = sorted(a['actorId'] for a in spec['actors'] if (round_index - 1) % a['cadence'] == 0)
    proposals = _collect(store, policy, fence, before, round_index, 'proposal', participants, cancelled)
    staged = stage_interactions(spec, before, proposals, round_index)
    recipients = response_actors(spec, staged, round_index)
    responses = _collect(store, policy, fence, staged, round_index, 'response', recipients, cancelled)
    result = resolve_round(spec, before, proposals + responses, round_index)
    _cancelled(cancelled)
    store.commit_round(before['round'], result['snapshot'], result['events'], result['resolutions'],
                       proposals + responses, fence)
    return store.head()


def run_to_horizon(store, policy, fence: int, *, cancelled: Callable[[], bool] = lambda: False,
                   on_commit: Callable[[dict], None] | None = None) -> dict:
    while store.head()['round'] < len(store.spec['periods']):
        head = run_round(store, policy, fence, cancelled=cancelled)
        if on_commit is not None:
            on_commit(head)
    return store.head()
