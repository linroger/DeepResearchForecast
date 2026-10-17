"""Real SDK/mock HTTP checks for explicit, lossless v4 assessment fields.

Run only through the coordinator's guarded runner. Retention and format admission
do not establish that private model-generated fields are true or consistent.
"""
from copy import deepcopy
import json

import pytest

import test_world_consistency_v3_policy as v3_fixtures

actor_case = v3_fixtures.actor_case
boundary = v3_fixtures.boundary
consistency_case = v3_fixtures.consistency_case
modeler_case = v3_fixtures.modeler_case
v3_case = v3_fixtures.v3_case

pytestmark = pytest.mark.guarded_runner

_USAGE = {'tokens': 140, 'costUsd': '0.000560000000'}


def _raw_assessment(verdict='consistent'):
    return {'checks': [
        {'kind': 'goal_alignment', 'verdict': verdict,
         '  Commentary  ': 'PRIVATE_MODEL_SUPPORT',
         'counterpoint': {'text': 'PRIVATE_CONTRADICTORY_CLAIM', 'flags': [True, None, 2]}},
        {'kind': 'conditional_timing', 'verdict': 'consistent',
         'explanation': 'PRIVATE_EXPLANATION', 'additional_note': 'PRIVATE_OTHER_CLAIM'},
        {'kind': 'quantity_consistency', 'verdict': 'consistent',
         'fields': {'nested_note': 'PRIVATE_ORIGINAL_FIELDS_MEMBER'}},
        {'kind': 'explanation_consistency', 'verdict': 'consistent',
         'remarks': [{'text': 'PRIVATE_UNVERIFIED_REMARK'}], 'quantity': '3', 'enabled': False},
    ]}


def _reconstruct(assessment):
    return {'checks': [{'kind': check['kind'], 'verdict': check['verdict'], **deepcopy(check['fields'])}
                       for check in assessment['checks']]}


@pytest.fixture
def v4_case(v3_case):
    from app.services.world_simulation.review import MODE_V4

    spec, observation, candidate, final = deepcopy(v3_case)
    spec['policy']['decisionReview'] = MODE_V4
    return spec, observation, candidate, final


@pytest.mark.parametrize('verdict', ['consistent', 'inconsistent', 'unknown'])
def test_v4_preserves_every_raw_field_without_synthesizing_explanation_or_verdict(v4_case, boundary, monkeypatch, verdict):
    from app.services.world_simulation import review
    from app.services.world_simulation.contracts import WorldError, canonical_json

    spec, observation, candidate, final = v4_case
    raw = _raw_assessment(verdict)
    original = deepcopy(raw)
    normalized_inputs = []
    normalize = review.normalize_v4_assessment_output

    def tracked(value):
        normalized_inputs.append(deepcopy(value))
        return normalize(value)

    monkeypatch.setattr(review, 'normalize_v4_assessment_output', tracked)
    case = boundary(spec=spec, content=json.dumps({'decision': final, 'assessment': raw}))
    quoted = case.policy.reservation(observation, review=candidate)
    assert case.sent == [] and normalized_inputs == []
    result = case.policy.decide(observation, review=candidate)
    assert normalized_inputs == [original] and _reconstruct(result.assessment) == original
    assert all(set(check) == {'kind', 'verdict', 'fields'} for check in result.assessment['checks'])
    assert 'explanation' not in result.assessment['checks'][0]['fields']
    assert result.assessment['checks'][0]['fields']['counterpoint']['text'] == 'PRIVATE_CONTRADICTORY_CLAIM'
    assert result.assessment['checks'][2]['fields']['fields'] == original['checks'][2]['fields']
    assert review.assessment_status(result.assessment, mode=review.MODE_V4) == (
        'clear' if verdict == 'consistent' else 'unresolved')
    canonical = review.validate_assessment(result.assessment, observation, result.decision, mode=review.MODE_V4)
    assert review.validate_assessment(canonical, observation, result.decision, mode=review.MODE_V4) == canonical
    assert len(normalized_inputs) == 1  # Canonical validation does not normalize saved data again.
    with pytest.raises(WorldError):
        review.validate_assessment(canonical, observation, result.decision, mode=review.MODE_V3)
    assert result.decision == {**final, 'actorId': observation['actorId'], 'observationId': observation['observationId']}
    assert 'PRIVATE_' not in json.dumps(result.decision) and 'PRIVATE_' not in case.sent[0].content.decode()
    assert json.loads(case.sent[0].content)['messages'][1]['content'] == canonical_json(observation)
    assert result.usage == _USAGE and quoted['tokens'] >= result.usage['tokens']
    assert raw == original and len(case.sent) == 1 and case.policy._client.max_retries == 0


@pytest.mark.parametrize('defect', ['reserved', 'members', 'bytes', 'depth', 'missing_verdict', 'float'])
def test_v4_rejects_controls_reserved_keys_and_excess_content_with_known_usage(v4_case, boundary, defect):
    from app.services.world_simulation.policy import PolicyFailure, is_candidate_output_failure, revision_shape_diagnostic

    spec, observation, candidate, final = v4_case
    raw = _raw_assessment()
    check = raw['checks'][0]
    if defect == 'reserved':
        check[' StAtUs '] = 'PRIVATE_RESERVED_VALUE'
    elif defect == 'members':
        check.update({f'extra{index}': 'kept only if within bound' for index in range(7)})
    elif defect == 'bytes':
        check['  Commentary  '] = '采购' * 700
    elif defect == 'depth':
        check['counterpoint'] = {'b': {'c': {'d': {'e': 'too deep'}}}}
    elif defect == 'missing_verdict':
        del check['verdict']
    else:
        check['coefficient'] = 1.25
    original = deepcopy(raw)
    case = boundary(spec=spec, content=json.dumps({'decision': final, 'assessment': raw}))
    with pytest.raises(PolicyFailure) as failed:
        case.policy.decide(observation, review=candidate)
    assert failed.value.code == ('policy_invalid_response' if defect == 'float' else 'invalid_assessment')
    assert failed.value.usage == _USAGE and len(case.sent) == 1
    assert revision_shape_diagnostic(failed.value) is None and not is_candidate_output_failure(failed.value)
    assert 'PRIVATE_RESERVED_VALUE' not in str(failed.value) and raw == original


@pytest.mark.parametrize('review_kind', ['candidate', 'candidate_error'])
def test_v4_reuses_exact_v3_preferred_and_repair_request_bytes(v3_case, boundary, review_kind):
    from app.services.world_simulation import review

    source_spec, observation, candidate, final = v3_case
    review_input = candidate
    if review_kind == 'candidate_error':
        review_input = review.candidate_error_context(observation, 'invalid_input')
    raw = v3_fixtures._assessment()
    cases, responses, quotes = [], [], []
    for mode in (review.MODE_V3, review.MODE_V4):
        spec = deepcopy(source_spec)
        spec['policy']['decisionReview'] = mode
        spec['policy']['responseFormat'] = 'json_object'
        spec['policy']['candidateRepair'] = review.CANDIDATE_REPAIR_MODE
        case = boundary(spec=spec, content=json.dumps({'decision': final, 'assessment': raw}))
        cases.append(case)
        quotes.append(case.policy.reservation(observation, review=review_input))
        responses.append(case.policy.decide(observation, review=review_input))
        assert case.policy.candidate_repair == review.CANDIDATE_REPAIR_MODE and len(case.sent) == 1
    assert quotes[0] == quotes[1] and cases[0].sent[0].content == cases[1].sent[0].content
    assert responses[0].decision == responses[1].decision and responses[0].usage == responses[1].usage == _USAGE
    assert responses[0].assessment == raw and _reconstruct(responses[1].assessment) == raw


def test_v4_normalizes_using_immutable_before_rpc_mode_and_observation(v4_case, boundary):
    from app.services.world_simulation.contracts import canonical_json
    from app.services.world_simulation.review import MODE_V3

    spec, observation, candidate, final = v4_case
    original_observation, original_candidate = deepcopy((observation, candidate))
    raw = _raw_assessment('unknown')
    holder = {}

    def mutate(request, number):
        holder['policy'].decision_review = MODE_V3
        observation['actorId'] = 'producer'
        candidate.clear()
        return json.dumps({'decision': final, 'assessment': raw})

    case = boundary(spec=spec, content_factory=mutate)
    holder['policy'] = case.policy
    result = case.policy.decide(observation, review=candidate)
    messages = json.loads(case.sent[0].content)['messages']
    assert messages[1]['content'] == canonical_json(original_observation)
    assert canonical_json(original_candidate) in messages[0]['content']
    assert result.decision['actorId'] == original_observation['actorId']
    assert result.decision['observationId'] == original_observation['observationId']
    assert _reconstruct(result.assessment) == raw and result.usage == _USAGE and len(case.sent) == 1


def test_candidates_old_review_modes_and_modeler_never_use_v4_normalizer(v4_case, modeler_case, boundary, monkeypatch):
    from app.services.world_simulation import review
    from app.services.world_simulation.policy import StrictHTTPModeler

    def forbidden(value):
        raise AssertionError('Only a fresh v4 actor revision may normalize an assessment')

    monkeypatch.setattr(review, 'normalize_v4_assessment_output', forbidden)
    source_spec, observation, candidate, final = v4_case
    candidate_bodies = []
    for mode in (None, review.MODE, review.MODE_V2, review.MODE_V3, review.MODE_V4):
        spec = deepcopy(source_spec)
        if mode is None:
            del spec['policy']['decisionReview']
        else:
            spec['policy']['decisionReview'] = mode
        case = boundary(spec=spec, content=json.dumps(final))
        assert case.policy.decide(observation, review=None).assessment is None
        candidate_bodies.append(case.sent[0].content)
        if mode in (review.MODE, review.MODE_V2, review.MODE_V3):
            if mode == review.MODE:
                assessment = v3_fixtures.policy_fixtures._assessment(observation, final)
            elif mode == review.MODE_V2:
                assessment = {'status': 'clear', 'checks': [
                    {'kind': c['kind'], 'explanation': c['explanation']}
                    for c in v3_fixtures._assessment()['checks']]}
            else:
                assessment = v3_fixtures._assessment()
            case.body['choices'][0]['message']['content'] = json.dumps({'decision': final, 'assessment': assessment})
            assert case.policy.decide(observation, review=candidate).assessment == assessment
    assert all(body == candidate_bodies[0] for body in candidate_bodies)
    modeler_spec = deepcopy(modeler_case.spec)
    modeler_spec['policy']['decisionReview'] = review.MODE_V4
    raw = {'assessment': _raw_assessment()}
    case = boundary(spec=modeler_spec, policy_type=StrictHTTPModeler, content=json.dumps(raw))
    result = case.policy.decide(modeler_case.messages)
    assert result.decision == raw and result.assessment is None and result.usage == _USAGE
    assert len(case.sent) == 1


def test_v4_candidate_repair_failure_retains_two_known_charges_without_an_automatic_third_call(v4_case, boundary):
    from app.services.world_simulation import review
    from app.services.world_simulation.policy import PolicyFailure, is_candidate_output_failure, revision_shape_diagnostic

    spec, observation, _, final = v4_case
    spec['policy']['candidateRepair'] = review.CANDIDATE_REPAIR_MODE
    raw = _raw_assessment()
    raw['checks'][0]['status'] = 'an aggregate control cannot hide in fields'

    def respond(request, number):
        return 'MALFORMED_FIRST_CANDIDATE' if number == 1 else json.dumps({'decision': final, 'assessment': raw})

    case = boundary(spec=spec, content_factory=respond)
    with pytest.raises(PolicyFailure) as first:
        case.policy.decide(observation)
    assert is_candidate_output_failure(first.value) and first.value.usage == _USAGE and len(case.sent) == 1
    context = review.candidate_error_context(observation, first.value.code)
    case.policy.reservation(observation, review=context)
    assert len(case.sent) == 1
    with pytest.raises(PolicyFailure) as second:
        case.policy.decide(observation, review=context)
    assert second.value.code == 'invalid_assessment' and second.value.usage == _USAGE
    assert not is_candidate_output_failure(second.value) and revision_shape_diagnostic(second.value) is None
    assert len(case.sent) == 2 and 'MALFORMED_FIRST_CANDIDATE' not in case.sent[1].content.decode()
    assert case.policy._client.max_retries == 0


def test_explanation_shape_diagnostics_remain_v3_only(v3_case, boundary):
    from app.services.world_simulation import review
    from app.services.world_simulation.policy import PolicyFailure, revision_shape_diagnostic

    source_spec, observation, candidate, final = v3_case
    raw = v3_fixtures._assessment()
    raw['checks'][0]['status'] = 'reserved'
    for mode in (review.MODE_V3, review.MODE_V4):
        spec = deepcopy(source_spec)
        spec['policy']['decisionReview'] = mode
        case = boundary(spec=spec, content=json.dumps({'decision': final, 'assessment': raw}))
        with pytest.raises(PolicyFailure) as failed:
            case.policy.decide(observation, review=candidate)
        assert failed.value.code == 'invalid_assessment' and failed.value.usage == _USAGE
        assert (revision_shape_diagnostic(failed.value) is not None) == (mode == review.MODE_V3)
        assert len(case.sent) == 1
