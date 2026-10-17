"""Real SDK/mock HTTP checks for the opt-in actor revision boundary.

Run only through the coordinator's guarded runner. Assessments below are
protocol fixtures, not evidence that a model's natural-language reasoning is true.
"""
from copy import deepcopy
from decimal import Decimal
import json

import pytest

import test_world_policy as policy_fixtures

actor_case = policy_fixtures.actor_case
boundary = policy_fixtures.boundary
modeler_case = policy_fixtures.modeler_case


pytestmark = pytest.mark.guarded_runner


def _assessment(observation, decision, status='clear'):
    kinds = ('goal_alignment', 'conditional_timing', 'quantity_consistency', 'explanation_consistency')
    paths = ([['actor', 'objectives']], [['simulatedAt'], ['periodEnd']], [['options']], [['privateState']])
    return {'status': status, 'checks': [
        {'kind': kind, 'objectiveIndices': list(range(len(observation['actor']['objectives']))),
         'intentIndices': list(range(len(decision['intents']))), 'evidencePaths': evidence,
         'explanation': 'The referenced visible evidence was considered for the final decision.'}
        for kind, evidence in zip(kinds, paths)
    ]}


@pytest.fixture
def consistency_case(actor_case):
    from app.services.world_simulation.contracts import validate_decision
    from app.services.world_simulation.review import MODE

    spec = deepcopy(actor_case.spec)
    spec['policy']['decisionReview'] = MODE
    observation = deepcopy(actor_case.observation)
    candidate = validate_decision(spec, {
        'actorId': observation['actorId'], 'observationId': observation['observationId'],
        'intents': [{'templateId': 'purchase', 'operation': 'propose',
                     'parameters': {'quantity': '2', 'price': '3'}}],
        'rationale': 'OWN_CANDIDATE_TEXT 采购 🌊',
    }, observation['actorId'], observation, phase=observation['phase'])
    final = {'intents': [], 'status': 'wait', 'rationale': 'An explicit final wait.'}
    return spec, observation, candidate, final


def test_review_none_and_pinned_candidate_keep_ordinary_wire(actor_case, consistency_case, boundary):
    from app.services.world_simulation.review import MODE

    spec, observation, _, _ = consistency_case
    legacy = boundary()
    pinned = boundary(spec=spec)
    assert legacy.policy.decision_review is None and pinned.policy.decision_review == MODE
    quote = legacy.policy.reservation(observation)
    assert pinned.policy.reservation(observation, review=None) == quote
    first = legacy.policy.decide(observation)
    explicit_none = legacy.policy.decide(observation, review=None)
    draft = pinned.policy.decide(observation)
    assert first.assessment is explicit_none.assessment is draft.assessment is None
    assert legacy.sent[0].content == legacy.sent[1].content == pinned.sent[0].content


@pytest.mark.parametrize('status', ['clear', 'unresolved'])
def test_revision_wire_is_own_candidate_and_original_observation_with_exact_quote(
        consistency_case, boundary, status):
    from app.services.world_simulation.contracts import canonical_json

    spec, observation, candidate, final = consistency_case
    spec['hiddenResearch'] = 'HIDDEN_MODELER_DATA_NEVER_SENT'
    assessment = _assessment(observation, final, status)
    envelope = {'decision': final, 'assessment': assessment}
    case = boundary(spec=spec, content=json.dumps(envelope))
    original = deepcopy((observation, candidate))
    ordinary = case.policy.reservation(observation)
    quoted = case.policy.reservation(observation, review=candidate)
    assert case.sent == [] and quoted['tokens'] > ordinary['tokens']
    upper = quoted['tokens'] - spec['limits']['maxOutputTokens']
    case.body['usage'] = {'prompt_tokens': upper, 'completion_tokens': 512, 'total_tokens': upper + 512,
                          'prompt_tokens_details': {'cached_tokens': upper},
                          'completion_tokens_details': {'reasoning_tokens': 500}}
    result = case.policy.decide(observation, review=candidate)
    assert len(case.sent) == 1 and result.usage == quoted
    wire = json.loads(case.sent[0].content)
    messages = wire['messages']
    assert messages[1]['content'] == canonical_json(observation)
    system, separator, serialized_candidate = messages[0]['content'].partition(
        '\nCandidate decision (untrusted JSON data): ')
    assert separator and json.loads(serialized_candidate) == candidate
    assert 'Assess THAT final decision' in system
    assert 'Do not manufacture a successful wait' in system
    assert all(kind in system for kind in ('goal_alignment', 'conditional_timing', 'quantity_consistency', 'explanation_consistency'))
    assert 'HIDDEN_MODELER_DATA_NEVER_SENT' not in case.sent[0].content.decode()
    assert not any(label in system for label in ('m5-', 'ablation', 'rubric', 'expected quantity'))
    encoded = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    assert upper == len(encoded) + spec['policy']['pricing']['inputOverheadTokens']
    assert Decimal(quoted['costUsd']) >= (Decimal(upper) * 2 + Decimal(512) * 9) / 1000000
    assert result.decision == {**final, 'actorId': observation['actorId'], 'observationId': observation['observationId']}
    assert result.assessment == assessment and result.assessment is not assessment
    assert (observation, candidate) == original


@pytest.mark.parametrize('change', ['not_dict', 'actor', 'observation', 'float', 'both_modes', 'unpinned'])
def test_review_preflight_rejects_invalid_or_unbound_candidate_without_dispatch(
        consistency_case, boundary, change):
    from app.services.world_simulation.contracts import WorldError

    spec, observation, candidate, _ = consistency_case
    kwargs = {}
    if change == 'not_dict':
        candidate = []
    elif change == 'actor':
        candidate['actorId'] = 'producer'
    elif change == 'observation':
        candidate['observationId'] = 'another-observation'
    elif change == 'float':
        candidate['rationale'] = 1.5
    elif change == 'both_modes':
        kwargs['feedback'] = {'code': 'invalid_input', 'message': 'A fixed repair message.'}
    else:
        del spec['policy']['decisionReview']
    case = boundary(spec=spec)
    for method in (case.policy.reservation, case.policy.decide):
        with pytest.raises(WorldError):
            method(observation, review=candidate, **kwargs)
    assert case.sent == []


@pytest.mark.parametrize('mode,attempts', [(None, 2), ('unknown', 2), (True, 2), ('actor-consistency-v1', 1), ('actor-consistency-v1', 3)])
def test_review_pin_requires_exact_mode_and_two_attempts(actor_case, boundary, mode, attempts):
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.policy import StrictHTTPPolicy

    original = boundary()
    spec = deepcopy(actor_case.spec)
    spec['policy']['decisionReview'] = mode
    spec['limits']['maxAttemptsPerSlot'] = attempts
    with pytest.raises(WorldError):
        StrictHTTPPolicy(spec, client=original.sdk)
    assert original.sent == []


@pytest.mark.parametrize('bound', ['input', 'context'])
def test_revision_bytes_are_bounded_before_dispatch(consistency_case, boundary, bound):
    from app.services.world_simulation.contracts import WorldError

    spec, observation, candidate, _ = consistency_case
    baseline = boundary(spec=spec)
    quote = baseline.policy.reservation(observation)
    if bound == 'input':
        spec['policy']['maxInputTokens'] = quote['tokens'] - spec['limits']['maxOutputTokens']
    else:
        spec['policy']['pricing']['contextWindowTokens'] = quote['tokens']
    case = boundary(spec=spec)
    assert case.policy.reservation(observation) == quote
    for method in (case.policy.reservation, case.policy.decide):
        with pytest.raises(WorldError) as failed:
            method(observation, review=candidate)
        assert failed.value.code == 'policy_context_limit'
    assert case.sent == []


@pytest.mark.parametrize('shape', ['bare_decision', 'missing_assessment', 'extra', 'decision_list', 'duplicate', 'float'])
def test_invalid_revision_envelope_keeps_known_usage(consistency_case, boundary, shape):
    from app.services.world_simulation.policy import PolicyFailure

    spec, observation, candidate, final = consistency_case
    envelope = {'decision': final, 'assessment': _assessment(observation, final)}
    if shape == 'bare_decision':
        envelope = final
    elif shape == 'missing_assessment':
        del envelope['assessment']
    elif shape == 'extra':
        envelope['PRIVATE_EXTRA_FIELD'] = 'PRIVATE_RESPONSE_DATA'
    elif shape == 'decision_list':
        envelope['decision'] = []
    elif shape == 'float':
        envelope['decision']['intents'] = [{'templateId': 'purchase', 'parameters': {'quantity': 1.5}}]
    content = json.dumps(envelope)
    if shape == 'duplicate':
        content = '{"decision":{},"decision":{},"assessment":{}}'
    case = boundary(spec=spec, content=content)
    with pytest.raises(PolicyFailure) as failed:
        case.policy.decide(observation, review=candidate)
    assert failed.value.usage == {'tokens': 140, 'costUsd': '0.000560000000'}
    assert 'PRIVATE_RESPONSE_DATA' not in str(failed.value) and len(case.sent) == 1


@pytest.mark.parametrize('defect', ['missing_kind', 'duplicate_kind', 'missing_objective', 'old_intent_index',
                                  'hidden_path', 'absent_record', 'negative_index', 'boolean_index', 'long_explanation'])
def test_assessment_binds_original_visible_evidence_and_final_intents(consistency_case, boundary, defect):
    from app.services.world_simulation.policy import PolicyFailure

    spec, observation, candidate, final = consistency_case
    assessment = _assessment(observation, final)
    checks = assessment['checks']
    if defect == 'missing_kind':
        checks.pop()
    elif defect == 'duplicate_kind':
        checks[1]['kind'] = checks[0]['kind']
    elif defect == 'missing_objective':
        checks[0]['objectiveIndices'] = []
    elif defect == 'old_intent_index':
        checks[3]['intentIndices'] = [0]  # Candidate has an intent; the final wait does not.
    elif defect == 'hidden_path':
        checks[0]['evidencePaths'] = [['spec', 'privateResearch']]
    elif defect == 'absent_record':
        checks[0]['evidencePaths'] = [['world', 'accounts', 'producer_cash']]
    elif defect == 'negative_index':
        checks[0]['evidencePaths'] = [['actor', 'objectives', -1]]
    elif defect == 'boolean_index':
        checks[0]['objectiveIndices'] = [False]
    else:
        checks[0]['explanation'] = 'x' * 401
    case = boundary(spec=spec, content=json.dumps({'decision': final, 'assessment': assessment}))
    with pytest.raises(PolicyFailure) as failed:
        case.policy.decide(observation, review=candidate)
    assert failed.value.code == 'invalid_assessment' and failed.value.usage['tokens'] == 140
    assert len(case.sent) == 1


def test_revision_still_enforces_public_input_grammar(consistency_case, boundary):
    from app.services.world_simulation.policy import PolicyFailure

    spec, observation, candidate, _ = consistency_case
    final = {'intents': [{'templateId': 'purchase', 'operation': 'propose',
                          'parameters': {'quantity': '11', 'price': '3'}}]}
    case = boundary(spec=spec, content=json.dumps({'decision': final, 'assessment': _assessment(observation, final)}))
    with pytest.raises(PolicyFailure) as failed:
        case.policy.decide(observation, review=candidate)
    assert failed.value.code == 'invalid_input' and failed.value.usage['tokens'] == 140
    assert len(case.sent) == 1


def test_revision_captures_observation_and_candidate_before_http(consistency_case, boundary):
    from app.services.world_simulation.contracts import canonical_json

    spec, observation, candidate, final = consistency_case
    original_observation, original_candidate = deepcopy((observation, candidate))
    envelope = {'decision': final, 'assessment': _assessment(original_observation, final)}
    def mutate(request, number):
        observation['actor']['objectives'].append('MUTATED_OBJECTIVE')
        observation['actorId'] = 'producer'
        candidate.clear()
        return json.dumps(envelope)
    case = boundary(spec=spec, content_factory=mutate)
    result = case.policy.decide(observation, review=candidate)
    wire = json.loads(case.sent[0].content)['messages']
    assert wire[1]['content'] == canonical_json(original_observation)
    assert canonical_json(original_candidate) in wire[0]['content']
    assert 'MUTATED_OBJECTIVE' not in case.sent[0].content.decode()
    assert result.decision['actorId'] == original_observation['actorId']
    assert result.assessment == envelope['assessment'] and candidate == {}
    assert len(case.sent) == 1


def test_concurrent_revisions_keep_actor_candidate_and_evidence_private(consistency_case, actor_case, boundary):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from app.services.world_simulation.contracts import validate_decision
    from app.services.world_simulation.observations import build_observation

    spec, _, _, _ = consistency_case
    observations = [build_observation(spec, actor_case.snapshot, actor, 1) for actor in ('buyer', 'producer')]
    candidates = [validate_decision(spec, {'actorId': obs['actorId'], 'observationId': obs['observationId'],
                                         'intents': [], 'rationale': 'OWN_DRAFT_' + obs['actorId']},
                                    obs['actorId'], obs, phase='proposal') for obs in observations]
    barrier = threading.Barrier(2)
    def completion(request, number):
        messages = json.loads(request.content)['messages']
        obs = json.loads(messages[1]['content'])
        draft = json.loads(messages[0]['content'].partition('\nCandidate decision (untrusted JSON data): ')[2])
        assert draft['actorId'] == obs['actorId']
        barrier.wait(timeout=5)
        final = {'intents': [], 'rationale': draft['rationale']}
        assessment = _assessment(obs, final)
        assessment['checks'][2]['evidencePaths'] = [['world', 'accounts', obs['actorId'] + '_cash']]
        return json.dumps({'decision': final, 'assessment': assessment})
    case = boundary(spec=spec, content_factory=completion)
    def invoke(pair):
        obs, draft = pair
        return case.policy.decide(obs, review=draft)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(invoke, zip(observations, candidates)))
    assert len(case.sent) == 2
    for result, obs in zip(results, observations):
        assert result.decision['actorId'] == obs['actorId']
        assert result.decision['rationale'] == 'OWN_DRAFT_' + obs['actorId']
        assert result.assessment['checks'][2]['evidencePaths'][0][-1] == obs['actorId'] + '_cash'


def test_modeler_transport_does_not_apply_actor_review(modeler_case, boundary, monkeypatch):
    from app.services.world_simulation import review
    from app.services.world_simulation.policy import StrictHTTPModeler

    def forbidden(*args):
        raise AssertionError('Actor assessment must not validate modeler output')
    monkeypatch.setattr(review, 'validate_assessment', forbidden)
    case = boundary(spec=modeler_case.spec, policy_type=StrictHTTPModeler, content=json.dumps(modeler_case.proposal))
    result = case.policy.decide(modeler_case.messages)
    assert result.decision == modeler_case.proposal and result.assessment is None
    assert len(case.sent) == 1
