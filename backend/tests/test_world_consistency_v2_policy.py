"""Bounded actual-SDK checks for the distinct server-bound review-v2 protocol."""
from copy import deepcopy
import hashlib
import json

import pytest

import test_world_consistency_policy as v1_fixtures

actor_case = v1_fixtures.actor_case
boundary = v1_fixtures.boundary
consistency_case = v1_fixtures.consistency_case

pytestmark = pytest.mark.guarded_runner


def _compact_assessment(status='clear'):
    return {'status': status, 'checks': [
        {'kind': kind, 'explanation': 'Considered the full supplied context and final decision.'}
        for kind in ('goal_alignment', 'conditional_timing', 'quantity_consistency', 'explanation_consistency')
    ]}


@pytest.fixture
def v2_case(consistency_case):
    from app.services.world_simulation.review import MODE_V2

    spec, observation, candidate, final = deepcopy(consistency_case)
    spec['policy']['decisionReview'] = MODE_V2
    return spec, observation, candidate, final


@pytest.mark.parametrize('status', ['clear', 'unresolved'])
def test_v2_standalone_envelope_full_action_rules_exact_quote_and_known_usage(v2_case, boundary, status):
    from app.services.world_simulation import policy
    from app.services.world_simulation.contracts import canonical_json

    spec, observation, candidate, final = v2_case
    assessment = _compact_assessment(status)
    case = boundary(spec=spec, content=json.dumps({'decision': final, 'assessment': assessment}))
    quoted = case.policy.reservation(observation, review=candidate)
    assert case.sent == []
    result = case.policy.decide(observation, review=candidate)
    payload = json.loads(case.sent[0].content)
    messages = payload['messages']
    assert set(payload) == {'model', 'messages', 'n', 'stream', 'max_completion_tokens'}
    system, marker, draft = messages[0]['content'].partition(policy._REVIEW_CANDIDATE_PREFIX)
    assert marker and json.loads(draft) == candidate
    assert messages[1]['content'] == canonical_json(observation)
    assert 'exactly two outer fields: decision and assessment' in system
    assert 'replace only the response format above' not in system
    assert 'Fields: intents (an array)' not in system
    assert policy._SYSTEM[policy._SYSTEM.index('Each intent may contain only'):] in system
    assert 'Preserve legitimate discretionary choices' in system
    assert 'those bindings do not prove the explanation is true' in system
    assert not any(name in system for name in ('objectiveIndices', 'intentIndices', 'evidencePaths', 'm5-', 'ablation', 'rubric'))
    size = len(json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8'))
    assert quoted['tokens'] == size + spec['policy']['pricing']['inputOverheadTokens'] + spec['limits']['maxOutputTokens']
    assert result.assessment == assessment
    assert result.decision == {**final, 'actorId': observation['actorId'], 'observationId': observation['observationId']}
    assert result.usage == {'tokens': 140, 'costUsd': '0.000560000000'} and len(case.sent) == 1


def test_v1_literals_and_v1_none_wire_remain_exact(consistency_case, boundary):
    from app.services.world_simulation import policy
    from app.services.world_simulation.contracts import canonical_json
    from app.services.world_simulation.review import MODE_V2

    expected = {
        '_SYSTEM': 'b35a1b0a7053ef95f1bf457c4d56bace3ca6de3b8a07e2714dac8b9ef11382ba',
        '_REVIEW_SYSTEM': 'b2ad82d72790da7b0fd6d260af7f16fd2e58f3acee463ef436fc29eb752d344f',
        '_REVIEW_CANDIDATE_PREFIX': '0fb6dd5524ff936caf7e84d2c72eb7d01f277b246d2e62beb089806ae59253aa',
    }
    for name, digest in expected.items():
        assert hashlib.sha256(getattr(policy, name).encode()).hexdigest() == digest
    spec, observation, candidate, final = consistency_case
    legacy_spec = deepcopy(spec)
    del legacy_spec['policy']['decisionReview']
    ordinary = boundary(spec=legacy_spec)
    ordinary.policy.decide(observation)
    v1 = boundary(spec=spec, content=json.dumps({'decision': final,
                  'assessment': v1_fixtures._assessment(observation, final)}))
    assert v1.policy.decide(observation, review=candidate).assessment['status'] == 'clear'
    assert json.loads(v1.sent[0].content)['messages'] == [
        {'role': 'system', 'content': policy._SYSTEM + f'Use at most {spec["limits"]["maxIntentsPerPhase"]} intents.'
         + policy._REVIEW_SYSTEM + policy._REVIEW_CANDIDATE_PREFIX + canonical_json(candidate)},
        {'role': 'user', 'content': canonical_json(observation)},
    ]
    v2_spec = deepcopy(spec)
    v2_spec['policy']['decisionReview'] = MODE_V2
    v2 = boundary(spec=v2_spec)
    assert v2.policy.decide(observation, review=None).assessment is None
    assert v2.sent[0].content == ordinary.sent[0].content


@pytest.mark.parametrize('defect', ['references', 'extra_value', 'missing_kind', 'long_explanation', 'envelope_extra'])
def test_v2_rejects_reference_fields_and_shape_errors_without_losing_usage(v2_case, boundary, defect):
    from app.services.world_simulation.policy import PolicyFailure

    spec, observation, candidate, final = v2_case
    assessment = _compact_assessment()
    envelope = {'decision': final, 'assessment': assessment}
    if defect == 'references':
        assessment['checks'][0]['evidencePaths'] = [['actor', 'objectives']]
    elif defect == 'extra_value':
        assessment['checks'][0]['value'] = 'invented'
    elif defect == 'missing_kind':
        assessment['checks'].pop()
    elif defect == 'long_explanation':
        assessment['checks'][0]['explanation'] = 'x' * 401
    else:
        envelope['audit'] = {'observationHash': 'MODEL_MUST_NOT_CREATE_SERVER_BINDING'}
    original = deepcopy(envelope)
    case = boundary(spec=spec, content=json.dumps(envelope))
    with pytest.raises(PolicyFailure) as failed:
        case.policy.decide(observation, review=candidate)
    assert failed.value.code == ('invalid_review_response' if defect == 'envelope_extra' else 'invalid_assessment')
    assert failed.value.usage == {'tokens': 140, 'costUsd': '0.000560000000'}
    assert envelope == original and len(case.sent) == 1


@pytest.mark.parametrize('request_version', ['v1', 'v2'])
def test_review_modes_do_not_accept_each_others_schema(consistency_case, boundary, request_version):
    from app.services.world_simulation.policy import PolicyFailure
    from app.services.world_simulation.review import MODE_V2

    spec, observation, candidate, final = deepcopy(consistency_case)
    wrong_assessment = _compact_assessment()
    if request_version == 'v2':
        spec['policy']['decisionReview'] = MODE_V2
        wrong_assessment = v1_fixtures._assessment(observation, final)
    case = boundary(spec=spec, content=json.dumps({'decision': final, 'assessment': wrong_assessment}))
    with pytest.raises(PolicyFailure) as failed:
        case.policy.decide(observation, review=candidate)
    assert failed.value.code == 'invalid_assessment'
    assert failed.value.usage['tokens'] == 140 and len(case.sent) == 1


def test_v2_uses_before_rpc_mode_observation_and_candidate(v2_case, boundary):
    from app.services.world_simulation.contracts import canonical_json
    from app.services.world_simulation.review import MODE

    spec, observation, candidate, final = v2_case
    original_observation, original_candidate = deepcopy((observation, candidate))
    envelope = {'decision': final, 'assessment': _compact_assessment()}
    holder = {}
    def mutate(request, number):
        observation['actorId'] = 'producer'
        observation['actor']['objectives'].append('MUTATED_PRIVATE_OBJECTIVE')
        candidate.clear()
        holder['policy'].decision_review = MODE
        return json.dumps(envelope)
    case = boundary(spec=spec, content_factory=mutate)
    holder['policy'] = case.policy
    result = case.policy.decide(observation, review=candidate)
    wire = json.loads(case.sent[0].content)['messages']
    assert wire[1]['content'] == canonical_json(original_observation)
    assert canonical_json(original_candidate) in wire[0]['content']
    assert 'MUTATED_PRIVATE_OBJECTIVE' not in case.sent[0].content.decode()
    assert case.policy.decision_review == MODE and candidate == {}
    assert result.decision['actorId'] == original_observation['actorId']
    assert result.assessment == envelope['assessment'] and len(case.sent) == 1


def test_v2_full_revision_prompt_is_bounded_before_dispatch(v2_case, boundary):
    from app.services.world_simulation.contracts import WorldError

    spec, observation, candidate, _ = v2_case
    probe = boundary(spec=spec)
    original = probe.policy.reservation(observation)
    spec['policy']['maxInputTokens'] = original['tokens'] - spec['limits']['maxOutputTokens']
    case = boundary(spec=spec)
    assert case.policy.reservation(observation, review=None) == original
    for method in (case.policy.reservation, case.policy.decide):
        with pytest.raises(WorldError) as failed:
            method(observation, review=candidate)
        assert failed.value.code == 'policy_context_limit'
    assert case.sent == []


def test_v2_wire_distinguishes_rule_existence_snapshot_time_and_future_consent(v2_case, boundary):
    from app.services.world_simulation.contracts import canonical_json
    from app.services.world_simulation.policy import _REVIEW_CANDIDATE_PREFIX

    spec, observation, candidate, final = v2_case
    assessment = _compact_assessment('unresolved')
    case = boundary(spec=spec, content=json.dumps({'decision': final, 'assessment': assessment}))
    result = case.policy.decide(observation, review=candidate)
    messages = json.loads(case.sent[0].content)['messages']
    system, marker, draft = messages[0]['content'].partition(_REVIEW_CANDIDATE_PREFIX)
    assert 'A conditional rule still exists when its predicate is currently unmet' in system
    assert 'distinguish existence from current applicability' in system
    assert 'snapshot at simulatedAt, not a guarantee that values persist through periodEnd' in system
    assert 'Preserve historical event dates and pending/proposed statuses' in system
    assert 'future fulfilment or counterparty consent need not be certain' in system
    assert 'Still check known affordability, authority and protocol constraints' in system
    assert 'do not force clear or justify inventing a wait' in system
    assert not any(label in system for label in ('m5-', '2030-01-01', 'ablation', 'rubric'))
    assert marker and json.loads(draft) == candidate
    assert messages[1]['content'] == canonical_json(observation)
    assert result.assessment == assessment and result.assessment['status'] == 'unresolved'
    assert result.decision['intents'] == final['intents']
    assert result.usage == {'tokens': 140, 'costUsd': '0.000560000000'} and len(case.sent) == 1
