"""Actual SDK/mock HTTP checks for explicit per-check review verdicts.

Run only through the parent's guarded runner. These protocol fixtures do not
prove a model's explanations true or establish a passing behavior study.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json

import pytest

import test_world_consistency_policy as policy_fixtures

actor_case = policy_fixtures.actor_case
boundary = policy_fixtures.boundary
consistency_case = policy_fixtures.consistency_case
modeler_case = policy_fixtures.modeler_case

pytestmark = pytest.mark.guarded_runner

_USAGE = {'tokens': 140, 'costUsd': '0.000560000000'}
_KINDS = ('goal_alignment', 'conditional_timing', 'quantity_consistency', 'explanation_consistency')


def _assessment(verdict='consistent'):
    checks = [{'kind': kind, 'verdict': 'consistent',
               'explanation': 'The visible facts support this final decision.'} for kind in _KINDS]
    # Deliberately keep positive prose: only the typed verdict determines status.
    checks[0]['verdict'] = verdict
    return {'checks': checks}


@pytest.fixture
def v3_case(consistency_case):
    from app.services.world_simulation.review import MODE_V3

    spec, observation, candidate, final = deepcopy(consistency_case)
    spec['policy']['decisionReview'] = MODE_V3
    return spec, observation, candidate, final


@pytest.mark.parametrize('verdict', ['consistent', 'inconsistent', 'unknown'])
def test_v3_exact_private_wire_quote_and_verdicts_retain_known_usage(v3_case, boundary, verdict):
    from app.services.world_simulation import policy
    from app.services.world_simulation.contracts import canonical_json
    from app.services.world_simulation.review import MODE_V3, assessment_status

    spec, observation, candidate, final = v3_case
    spec['hiddenResearch'] = 'HIDDEN_RESEARCH_NEVER_SENT'
    spec['actors'][2]['beliefs'] = ['OTHER_ACTOR_PRIVATE_BELIEF']
    original = deepcopy((observation, candidate))
    assessment = _assessment(verdict)
    case = boundary(spec=spec, content=json.dumps({'decision': final, 'assessment': assessment}))
    quote = case.policy.reservation(observation, review=candidate)
    assert case.sent == []
    result = case.policy.decide(observation, review=candidate)
    assert len(case.sent) == 1
    body = json.loads(case.sent[0].content)
    assert set(body) == {'model', 'messages', 'n', 'stream', 'max_completion_tokens'}
    assert body['model'] == spec['policy']['model'] and body['max_completion_tokens'] == 512
    assert body['n'] == 1 and body['stream'] is False
    assert case.policy._client.max_retries == 0 and case.sdk.max_retries == 6
    assert all(value == 17 for value in case.sent[0].extensions['timeout'].values())
    messages = body['messages']
    assert messages == [
        {'role': 'system', 'content': policy._REVIEW_SYSTEM_V3
         + f'Use at most {spec["limits"]["maxIntentsPerPhase"]} intents in decision.'
         + policy._REVIEW_CANDIDATE_PREFIX + canonical_json(candidate)},
        {'role': 'user', 'content': canonical_json(observation)},
    ]
    system = messages[0]['content'].partition(policy._REVIEW_CANDIDATE_PREFIX)[0]
    assert 'exactly two outer fields: decision and assessment' in system
    assert 'assessment contains exactly checks, with no aggregate status field' in system
    assert 'Each check contains exactly kind, verdict and explanation' in system
    assert 'verdict is exactly consistent, inconsistent or unknown' in system
    assert policy._SYSTEM[policy._SYSTEM.index('Each intent may contain only'):] in system
    for required in (
        'actor.objectives and actor.constraints separately from actor.priorityRules',
        'scope any absence claim to the specific visible fields or records actually checked',
        'A visible menu offers an action type but does not prove every prerequisite',
        'Distinguish objective preferences from binding constraints',
        'not a guarantee that values persist through periodEnd',
        'Still check known affordability, authority and protocol constraints',
        'future fulfilment or counterparty consent need not be certain',
        'do not force a consistent verdict or justify inventing a wait',
        'nonempty string of at most 400 characters',
    ):
        assert required in system
    for denied in ('HIDDEN_RESEARCH_NEVER_SENT', 'OTHER_ACTOR_PRIVATE_BELIEF',
                   'inputUsdPerMillion', 'fixture-only-secret-never-real',
                   'objectiveIndices', 'evidencePaths', 'm5-', 'ablation', 'rubric'):
        assert denied not in case.sent[0].content.decode()
    size = len(json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8'))
    assert quote['tokens'] == size + spec['policy']['pricing']['inputOverheadTokens'] + 512
    assert Decimal(quote['costUsd']) >= (Decimal(size + 256) * 2 + Decimal(512) * 9) / 1000000
    assert result.usage == _USAGE
    assert result.assessment == assessment and set(result.assessment) == {'checks'}
    assert assessment_status(result.assessment, mode=MODE_V3) == (
        'clear' if verdict == 'consistent' else 'unresolved')
    assert result.decision == {**final, 'actorId': observation['actorId'],
                               'observationId': observation['observationId']}
    assert (observation, candidate) == original


@pytest.mark.parametrize('defect', [
    'aggregate', 'missing_verdict', 'invalid_verdict', 'references',
    'duplicate_kind', 'missing_checks', 'long_explanation', 'outer_extra',
])
def test_v3_invalid_assessments_keep_known_usage_without_repair_dispatch(v3_case, boundary, defect):
    from app.services.world_simulation.policy import PolicyFailure

    spec, observation, candidate, final = v3_case
    assessment = _assessment()
    envelope = {'decision': final, 'assessment': assessment}
    if defect == 'aggregate':
        assessment['status'] = 'clear'
    elif defect == 'missing_verdict':
        del assessment['checks'][0]['verdict']
    elif defect == 'invalid_verdict':
        assessment['checks'][0]['verdict'] = 'clear'
    elif defect == 'references':
        assessment['checks'][0]['evidencePaths'] = [['actor', 'objectives']]
    elif defect == 'duplicate_kind':
        assessment['checks'][1]['kind'] = assessment['checks'][0]['kind']
    elif defect == 'missing_checks':
        assessment['checks'] = []
    elif defect == 'long_explanation':
        assessment['checks'][0]['explanation'] = 'x' * 401
    else:
        envelope['status'] = 'clear'
    case = boundary(spec=spec, content=json.dumps(envelope))
    with pytest.raises(PolicyFailure) as failed:
        case.policy.decide(observation, review=candidate)
    assert failed.value.code == ('invalid_review_response' if defect == 'outer_extra' else 'invalid_assessment')
    assert failed.value.usage == _USAGE and len(case.sent) == 1


@pytest.mark.parametrize('content', [
    '{"decision":{"intents":[]},"assessment":{"checks":[],"checks":[]}}',
    '{"decision":{"intents":[],"rationale":1.5},"assessment":{"checks":[]}}',
])
def test_native_json_format_does_not_weaken_strict_parser(v3_case, boundary, content):
    from app.services.world_simulation.policy import PolicyFailure

    spec, observation, candidate, _ = v3_case
    spec['policy']['responseFormat'] = 'json_object'
    case = boundary(spec=spec, content=content)
    with pytest.raises(PolicyFailure) as failed:
        case.policy.decide(observation, review=candidate)
    assert failed.value.code == 'policy_invalid_response'
    assert failed.value.usage == _USAGE and len(case.sent) == 1
    assert json.loads(case.sent[0].content)['response_format'] == {'type': 'json_object'}


def test_old_literals_revision_wire_and_all_candidate_wire_remain_exact(consistency_case, boundary):
    from app.services.world_simulation import policy
    from app.services.world_simulation.contracts import canonical_json
    from app.services.world_simulation.review import MODE, MODE_V2, MODE_V3

    expected = {
        '_SYSTEM': 'b35a1b0a7053ef95f1bf457c4d56bace3ca6de3b8a07e2714dac8b9ef11382ba',
        '_REVIEW_SYSTEM': 'b2ad82d72790da7b0fd6d260af7f16fd2e58f3acee463ef436fc29eb752d344f',
        '_REVIEW_CANDIDATE_PREFIX': '0fb6dd5524ff936caf7e84d2c72eb7d01f277b246d2e62beb089806ae59253aa',
        '_REVIEW_SYSTEM_V2': 'e6d159758ff6498f798c340a01b72a32ef534ee700b19839db1b34a68d254053',
    }
    for name, digest in expected.items():
        assert hashlib.sha256(getattr(policy, name).encode()).hexdigest() == digest
    spec, observation, candidate, final = consistency_case
    ordinary_spec = deepcopy(spec)
    del ordinary_spec['policy']['decisionReview']
    ordinary = boundary(spec=ordinary_spec)
    ordinary.policy.decide(observation)
    for mode in (MODE, MODE_V2, MODE_V3):
        pinned_spec = deepcopy(spec)
        pinned_spec['policy']['decisionReview'] = mode
        draft = boundary(spec=pinned_spec)
        assert draft.policy.decide(observation, review=None).assessment is None
        assert draft.sent[0].content == ordinary.sent[0].content
        assert draft.policy._response_format is None
    for mode in (MODE, MODE_V2):
        legacy_spec = deepcopy(spec)
        legacy_spec['policy']['decisionReview'] = mode
        assessment = policy_fixtures._assessment(observation, final)
        prefix = policy._SYSTEM + f'Use at most {spec["limits"]["maxIntentsPerPhase"]} intents.' + policy._REVIEW_SYSTEM
        if mode == MODE_V2:
            assessment = {'status': 'clear', 'checks': [
                {'kind': check['kind'], 'explanation': check['explanation']}
                for check in assessment['checks']
            ]}
            prefix = policy._REVIEW_SYSTEM_V2 + f'Use at most {spec["limits"]["maxIntentsPerPhase"]} intents in decision.'
        case = boundary(spec=legacy_spec, content=json.dumps({'decision': final, 'assessment': assessment}))
        assert case.policy.decide(observation, review=candidate).assessment == assessment
        assert json.loads(case.sent[0].content) == {
            'model': spec['policy']['model'], 'n': 1, 'stream': False, 'max_completion_tokens': 512,
            'messages': [
                {'role': 'system', 'content': prefix + policy._REVIEW_CANDIDATE_PREFIX + canonical_json(candidate)},
                {'role': 'user', 'content': canonical_json(observation)},
            ],
        }


@pytest.mark.parametrize('purpose', ['candidate', 'revision', 'modeler'])
def test_explicit_response_format_is_detached_and_is_the_only_wire_change(
        v3_case, modeler_case, boundary, purpose):
    from app.services.world_simulation.policy import StrictHTTPModeler, StrictHTTPPolicy
    from app.services.world_simulation.review import MODE_V3

    spec, observation, candidate, final = v3_case
    policy_type, request, kwargs = StrictHTTPPolicy, observation, {}
    response = final
    if purpose == 'revision':
        kwargs = {'review': candidate}
        response = {'decision': final, 'assessment': _assessment()}
    elif purpose == 'modeler':
        spec = deepcopy(modeler_case.spec)
        spec['policy']['decisionReview'] = MODE_V3
        policy_type, request, response = StrictHTTPModeler, modeler_case.messages, modeler_case.proposal
    legacy = boundary(spec=spec, policy_type=policy_type, content=json.dumps(response))
    pinned_spec = deepcopy(spec)
    pinned_spec['policy']['responseFormat'] = 'json_object'
    pinned = boundary(spec=pinned_spec, policy_type=policy_type, content=json.dumps(response))
    # Both injected source specs are caller-owned, not live adapter configuration.
    legacy.spec['policy']['responseFormat'] = 'json_object'
    pinned.spec['policy']['responseFormat'] = None
    assert legacy.policy._response_format is None and pinned.policy._response_format == 'json_object'
    assert legacy.policy.reservation(request, **kwargs) == pinned.policy.reservation(request, **kwargs)
    first = legacy.policy.decide(request, **kwargs)
    second = pinned.policy.decide(request, **kwargs)
    old_body, new_body = (json.loads(item.sent[0].content) for item in (legacy, pinned))
    assert 'response_format' not in old_body
    assert new_body.pop('response_format') == {'type': 'json_object'}
    assert new_body == old_body
    assert first.decision == second.decision and first.assessment == second.assessment
    assert first.usage == second.usage == _USAGE
    assert len(legacy.sent) == len(pinned.sent) == 1
    if purpose == 'modeler':
        assert second.decision == modeler_case.proposal and second.assessment is None
        assert new_body['messages'] == modeler_case.messages
        assert not hasattr(pinned.policy, 'decision_review')


@pytest.mark.parametrize('value', [None, 'json_schema', {'type': 'json_object'}])
def test_invalid_response_format_fails_before_dispatch_for_both_adapters(actor_case, boundary, value):
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.policy import StrictHTTPModeler, StrictHTTPPolicy

    valid = boundary()
    spec = deepcopy(actor_case.spec)
    spec['policy']['responseFormat'] = value
    for policy_type in (StrictHTTPPolicy, StrictHTTPModeler):
        with pytest.raises(WorldError) as failed:
            policy_type(spec, client=valid.sdk)
        assert failed.value.code == 'invalid_policy_metadata'
    assert valid.sent == []


def test_v3_captures_mode_observation_and_own_candidate_before_http(v3_case, boundary):
    from app.services.world_simulation.contracts import canonical_json
    from app.services.world_simulation.policy import _REVIEW_CANDIDATE_PREFIX, _REVIEW_SYSTEM_V3
    from app.services.world_simulation.review import MODE_V2

    spec, observation, candidate, final = v3_case
    original_observation, original_candidate = deepcopy((observation, candidate))
    assessment = _assessment()
    holder = {}

    def mutate(request, number):
        observation['actorId'] = 'producer'
        observation['actor']['objectives'].append('MUTATED_PRIVATE_GOAL')
        candidate.clear()
        holder['policy'].decision_review = MODE_V2
        return json.dumps({'decision': {**final, 'actorId': 'producer', 'observationId': 'wrong'},
                           'assessment': assessment})

    case = boundary(spec=spec, content_factory=mutate)
    holder['policy'] = case.policy
    result = case.policy.decide(observation, review=candidate)
    messages = json.loads(case.sent[0].content)['messages']
    assert messages[0]['content'].startswith(_REVIEW_SYSTEM_V3)
    assert messages[0]['content'].partition(_REVIEW_CANDIDATE_PREFIX)[2] == canonical_json(original_candidate)
    assert messages[1]['content'] == canonical_json(original_observation)
    assert 'MUTATED_PRIVATE_GOAL' not in case.sent[0].content.decode()
    assert case.policy.decision_review == MODE_V2 and candidate == {}
    assert result.decision['actorId'] == original_observation['actorId']
    assert result.decision['observationId'] == original_observation['observationId']
    assert result.assessment == assessment and result.usage == _USAGE and len(case.sent) == 1


@pytest.mark.parametrize('limit', ['input', 'context'])
def test_v3_full_utf8_request_is_reserved_and_bounded_before_dispatch(v3_case, boundary, limit):
    from app.services.world_simulation.contracts import WorldError

    spec, observation, candidate, final = v3_case
    candidate['rationale'] = 'Own candidate 采购 🌊'
    assessment = _assessment()
    assessment['checks'][0]['explanation'] = 'x' * 400
    case = boundary(spec=spec, content=json.dumps({'decision': final, 'assessment': assessment}))
    quote = case.policy.reservation(observation, review=candidate)
    upper = quote['tokens'] - spec['limits']['maxOutputTokens']
    case.body['usage'] = {
        'prompt_tokens': upper, 'completion_tokens': 512, 'total_tokens': upper + 512,
        'prompt_tokens_details': {'cached_tokens': upper},
        'completion_tokens_details': {'reasoning_tokens': 512},
    }
    assert case.policy.decide(observation, review=candidate).usage == quote
    assert len(case.sent) == 1
    limited = deepcopy(spec)
    if limit == 'input':
        limited['policy']['maxInputTokens'] = upper - 1
    else:
        limited['policy']['pricing']['contextWindowTokens'] = quote['tokens'] - 1
    denied = boundary(spec=limited)
    for method in (denied.policy.reservation, denied.policy.decide):
        with pytest.raises(WorldError) as failed:
            method(observation, review=candidate)
        assert failed.value.code == 'policy_context_limit'
    assert denied.sent == []


def test_v3_rejects_foreign_candidate_before_reservation_or_dispatch(v3_case, boundary):
    from app.services.world_simulation.contracts import WorldError

    spec, observation, candidate, _ = v3_case
    candidate['actorId'] = 'producer'
    candidate['rationale'] = 'FOREIGN_PRIVATE_CANDIDATE'
    case = boundary(spec=spec)
    for method in (case.policy.reservation, case.policy.decide):
        with pytest.raises(WorldError) as failed:
            method(observation, review=candidate)
        assert failed.value.code == 'decision_identity_mismatch'
        assert 'FOREIGN_PRIVATE_CANDIDATE' not in str(failed.value)
    assert case.sent == []


def test_v3_native_format_keeps_sanitized_single_dispatch_transport_failure(v3_case, boundary):
    from app.services.world_simulation.policy import PolicyFailure

    spec, observation, candidate, _ = v3_case
    spec['policy']['responseFormat'] = 'json_object'
    case = boundary(spec=spec, status=503, raw_body=b'{"error":"PRIVATE_PROVIDER_DETAIL"}',
                    headers={'retry-after': '0', 'x-should-retry': 'true'})
    with pytest.raises(PolicyFailure) as failed:
        case.policy.decide(observation, review=candidate)
    assert failed.value.code == 'policy_transport_failed'
    assert str(failed.value) == 'Actor HTTP dispatch failed with status 503; exposure is unknown'
    assert failed.value.usage is None and len(case.sent) == 1


@pytest.fixture
def repair_case(v3_case):
    from app.services.world_simulation.review import CANDIDATE_REPAIR_MODE

    spec, observation, candidate, final = deepcopy(v3_case)
    spec['policy']['candidateRepair'] = CANDIDATE_REPAIR_MODE
    return spec, observation, candidate, final


@pytest.mark.parametrize('defect', ['parse', 'grammar'])
def test_metered_candidate_failure_then_closed_context_revision_is_two_calls(repair_case, boundary, defect):
    from app.services.world_simulation import policy
    from app.services.world_simulation.contracts import canonical_json
    from app.services.world_simulation.review import CANDIDATE_REPAIR_MODE, candidate_error_context

    spec, observation, _, final = repair_case
    raw = ('PRIVATE_MALFORMED_OUTPUT' if defect == 'parse' else
           json.dumps({'intents': 'PRIVATE_INVALID_INTENTS', 'rationale': 'PRIVATE_RAW_CANDIDATE'}))
    assessment = _assessment()

    def respond(request, number):
        return raw if number == 1 else json.dumps({'decision': final, 'assessment': assessment})

    case = boundary(spec=spec, content_factory=respond)
    assert case.policy.candidate_repair == CANDIDATE_REPAIR_MODE
    with pytest.raises(policy.PolicyFailure) as failed:
        case.policy.decide(observation)
    assert failed.value.usage == _USAGE and policy.is_candidate_output_failure(failed.value)
    assert failed.value.code == ('policy_invalid_response' if defect == 'parse' else 'invalid_decision')
    assert len(case.sent) == 1  # The adapter never dispatches its own repair.
    context = candidate_error_context(observation, failed.value.code)
    quote = case.policy.reservation(observation, review=context)
    assert len(case.sent) == 1
    result = case.policy.decide(observation, review=context)
    assert len(case.sent) == 2 and result.usage == _USAGE and result.assessment == assessment
    assert result.decision == {**final, 'actorId': observation['actorId'],
                               'observationId': observation['observationId']}
    messages = json.loads(case.sent[1].content)['messages']
    system, marker, encoded_context = messages[0]['content'].partition(policy._REVIEW_ERROR_PREFIX)
    assert marker and json.loads(encoded_context) == context
    assert 'No usable candidate exists for this request' in system
    assert 'Generate a complete final decision from the unchanged original observation' in system
    assert policy._REVIEW_CANDIDATE_PREFIX not in messages[0]['content']
    assert all(secret not in case.sent[1].content.decode() for secret in (
        'PRIVATE_MALFORMED_OUTPUT', 'PRIVATE_INVALID_INTENTS', 'PRIVATE_RAW_CANDIDATE', 'attemptId'))
    assert messages[1]['content'] == canonical_json(observation)
    assert set(context) == {'schemaVersion', 'actorId', 'observationId', 'errorCode'}
    size = len(json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8'))
    assert quote['tokens'] == size + spec['policy']['pricing']['inputOverheadTokens'] + 512
    assert case.policy._client.max_retries == 0


def test_candidate_repair_pin_preserves_successful_candidate_and_revision_wire(v3_case, repair_case, boundary):
    plain_spec, observation, candidate, final = v3_case
    pinned_spec = repair_case[0]
    plain, pinned = boundary(spec=plain_spec), boundary(spec=pinned_spec)
    assert plain.policy.candidate_repair is None
    assert plain.policy.reservation(observation) == pinned.policy.reservation(observation)
    for case in (plain, pinned):
        assert case.policy.decide(observation).assessment is None
        case.body['choices'][0]['message']['content'] = json.dumps(
            {'decision': final, 'assessment': _assessment()})
    assert plain.sent[0].content == pinned.sent[0].content
    assert plain.policy.reservation(observation, review=candidate) == pinned.policy.reservation(observation, review=candidate)
    for case in (plain, pinned):
        assert case.policy.decide(observation, review=candidate).assessment == _assessment()
    assert plain.sent[1].content == pinned.sent[1].content


@pytest.mark.parametrize('defect', ['extra_raw', 'wrong_observation', 'bad_code', 'no_pin'])
def test_candidate_error_context_rejects_before_quote_or_dispatch(repair_case, boundary, defect):
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.review import candidate_error_context

    spec, observation, _, _ = repair_case
    context = candidate_error_context(observation, 'policy_invalid_response')
    if defect == 'extra_raw':
        context['message'] = 'PRIVATE_RAW_ERROR'
    elif defect == 'wrong_observation':
        context['observationId'] = 'another-observation'
    elif defect == 'bad_code':
        context['errorCode'] = 'policy_transport_failed'
    else:
        del spec['policy']['candidateRepair']
    case = boundary(spec=spec)
    for method in (case.policy.reservation, case.policy.decide):
        with pytest.raises(WorldError) as failed:
            method(observation, review=context)
        assert failed.value.code == ('invalid_policy_review' if defect == 'no_pin' else 'invalid_review_input')
        assert 'PRIVATE_RAW_ERROR' not in str(failed.value)
    assert case.sent == []


def test_candidate_repair_captures_original_context_mode_and_observation(repair_case, boundary):
    from app.services.world_simulation.contracts import canonical_json
    from app.services.world_simulation.policy import _REVIEW_ERROR_PREFIX
    from app.services.world_simulation.review import MODE_V2, candidate_error_context

    spec, observation, _, final = repair_case
    context = candidate_error_context(observation, 'invalid_input')
    original_observation, original_context = deepcopy((observation, context))
    holder = {}

    def mutate(request, number):
        context.clear()
        context['message'] = 'MUTATED_PRIVATE_CONTEXT'
        observation['actorId'] = 'producer'
        holder['policy'].decision_review = MODE_V2
        holder['policy'].candidate_repair = None
        return json.dumps({'decision': final, 'assessment': _assessment('unknown')})

    case = boundary(spec=spec, content_factory=mutate)
    holder['policy'] = case.policy
    result = case.policy.decide(observation, review=context)
    messages = json.loads(case.sent[0].content)['messages']
    assert messages[0]['content'].partition(_REVIEW_ERROR_PREFIX)[2] == canonical_json(original_context)
    assert messages[1]['content'] == canonical_json(original_observation)
    assert 'MUTATED_PRIVATE_CONTEXT' not in case.sent[0].content.decode()
    assert result.decision['actorId'] == original_observation['actorId']
    assert result.decision['observationId'] == original_observation['observationId']
    assert result.assessment == _assessment('unknown') and result.usage == _USAGE
    assert len(case.sent) == 1


def test_candidate_error_context_full_prompt_and_context_bounds_precede_http(repair_case, boundary):
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.review import candidate_error_context

    spec, observation, _, _ = repair_case
    context = candidate_error_context(observation, 'invalid_input')
    quote = boundary(spec=spec).policy.reservation(observation, review=context)
    for bound in ('input', 'context'):
        limited = deepcopy(spec)
        if bound == 'input':
            limited['policy']['maxInputTokens'] = quote['tokens'] - 512 - 1
        else:
            limited['policy']['pricing']['contextWindowTokens'] = quote['tokens'] - 1
        case = boundary(spec=limited)
        for method in (case.policy.reservation, case.policy.decide):
            with pytest.raises(WorldError) as failed:
                method(observation, review=context)
            assert failed.value.code == 'policy_context_limit'
        assert case.sent == []


def test_output_origin_cannot_be_spoofed_by_code_usage_or_changed_after_capture(repair_case, boundary):
    from app.services.world_simulation.policy import PolicyFailure, is_candidate_output_failure
    from app.services.world_simulation.review import CANDIDATE_OUTPUT_ERRORS

    spec, observation, _, _ = repair_case
    for code in CANDIDATE_OUTPUT_ERRORS:
        spoof = PolicyFailure(code, 'not an adapter output receipt', usage=_USAGE)
        assert not is_candidate_output_failure(spoof)
        spoof._candidate_output_origin = True
        assert not is_candidate_output_failure(spoof)
    case = boundary(spec=spec, content='MALFORMED_OUTPUT')
    with pytest.raises(PolicyFailure) as failed:
        case.policy.decide(observation)
    error = failed.value
    assert is_candidate_output_failure(error)
    error.usage['tokens'] += 1
    assert not is_candidate_output_failure(error)
    error.usage = deepcopy(_USAGE)
    error.code = 'invalid_input'  # Another eligible code cannot replace the captured code.
    assert not is_candidate_output_failure(error)
    error.code = 'policy_invalid_response'
    error.usage = None
    assert not is_candidate_output_failure(error) and len(case.sent) == 1


def test_non_candidate_unknown_and_internal_failures_never_open_repair(repair_case, modeler_case, boundary, monkeypatch):
    from app.services.world_simulation import policy
    from app.services.world_simulation.review import candidate_error_context

    spec, observation, _, final = repair_case
    context = candidate_error_context(observation, 'invalid_input')
    for defect in ('transport', 'identity', 'metering', 'modeler', 'revision_parse', 'revision_grammar',
                   'parser_internal', 'grammar_internal', 'grammar_identity'):
        kwargs, request, call_kwargs = {'spec': spec}, observation, {}
        if defect == 'transport':
            kwargs['status'] = 503
        elif defect == 'identity':
            kwargs['model'] = 'different-model'
        elif defect == 'modeler':
            kwargs.update(spec=modeler_case.spec, policy_type=policy.StrictHTTPModeler, content='BROKEN_JSON')
            request = modeler_case.messages
        elif defect.startswith('revision_'):
            call_kwargs['review'] = context
            kwargs['content'] = ('BROKEN_JSON' if defect == 'revision_parse' else
                                 json.dumps({'decision': {'intents': 'invalid'}, 'assessment': _assessment()}))
        else:
            kwargs['content'] = json.dumps(final)
        case = boundary(**kwargs)
        if defect == 'metering':
            case.body['usage'] = None
        with monkeypatch.context() as patch:
            if defect == 'parser_internal':
                original = policy._strict_json

                def broken_parser(text, *, envelope=False):
                    if envelope:
                        return original(text, envelope=True)
                    raise RuntimeError('INTERNAL_PARSER_FAILURE')

                patch.setattr(policy, '_strict_json', broken_parser)
            elif defect.startswith('grammar_'):
                def broken_grammar(decision, sent_observation):
                    if defect == 'grammar_identity':
                        raise policy.WorldError('policy_identity_mismatch', 'Controlled identity failure')
                    raise RuntimeError('INTERNAL_GRAMMAR_FAILURE')

                patch.setattr(case.policy, '_validate_visible_input_grammar', broken_grammar)
            with pytest.raises(policy.PolicyFailure) as failed:
                case.policy.decide(request, **call_kwargs)
        assert not policy.is_candidate_output_failure(failed.value), defect
        assert len(case.sent) == 1
        assert failed.value.usage == (None if defect in {'transport', 'identity', 'metering'} else _USAGE)
        assert 'INTERNAL_' not in str(failed.value)


def test_candidate_repair_requires_v3_and_the_existing_two_attempt_pin(repair_case, boundary):
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.policy import StrictHTTPPolicy
    from app.services.world_simulation.review import MODE, MODE_V2

    spec = repair_case[0]
    valid = boundary(spec=spec)
    for mode, repair, attempts in ((MODE, 'known-output-error-v1', 2),
                                   (MODE_V2, 'known-output-error-v1', 2),
                                   ('actor-consistency-v3', 'unknown-repair', 2),
                                   ('actor-consistency-v3', 'known-output-error-v1', 3)):
        invalid = deepcopy(spec)
        invalid['policy'].update(decisionReview=mode, candidateRepair=repair)
        invalid['limits']['maxAttemptsPerSlot'] = attempts
        with pytest.raises(WorldError) as failed:
            StrictHTTPPolicy(invalid, client=valid.sdk)
        assert failed.value.code in {'invalid_policy_metadata', 'invalid_limit'}
    assert valid.sent == []


@pytest.mark.parametrize('input_kind', ['candidate', 'candidate_error'])
def test_v3_wire_audits_shape_without_prescribing_action_or_verdict(repair_case, boundary, input_kind):
    from app.services.world_simulation import policy
    from app.services.world_simulation.contracts import canonical_json
    from app.services.world_simulation.review import MODE_V3, assessment_status, candidate_error_context

    spec, observation, candidate, final = repair_case
    review = candidate
    prefix = policy._REVIEW_CANDIDATE_PREFIX
    verdict = 'unknown'
    if input_kind == 'candidate_error':
        review = candidate_error_context(observation, 'invalid_input')
        prefix = policy._REVIEW_ERROR_PREFIX
        verdict = 'inconsistent'
    final['stateUpdates'] = {'beliefs': ['A tentative belief, not an asserted world change.']}
    assessment = _assessment(verdict)
    original_observation, original_review = deepcopy((observation, review))
    case = boundary(spec=spec, content=json.dumps({'decision': final, 'assessment': assessment}))
    quote = case.policy.reservation(observation, review=review)
    assert case.sent == []
    result = case.policy.decide(observation, review=review)
    assert len(case.sent) == 1
    messages = json.loads(case.sent[0].content)['messages']
    system, marker, encoded_review = messages[0]['content'].partition(prefix)
    assert marker and encoded_review == canonical_json(original_review)
    assert messages[1]['content'] == canonical_json(original_observation)
    assert 'Structural illustration only, not literal output' in system
    assert '{"decision": FINAL_DECISION, "assessment": {"checks": [CHECK_1, CHECK_2, CHECK_3, CHECK_4]}}' in system
    assert '{"kind": KIND_STRING, "verdict": VERDICT_STRING, "explanation": EXPLANATION_STRING}' in system
    assert 'uppercase names are non-output metavariables, not JSON values to echo' in system
    assert 'the illustration specifies no action or default verdict' in system
    assert 'audit structure separately from semantic verdicts' in system
    assert 'assessment.checks is a JSON array of exactly four objects, one for each required kind' in system
    assert 'Every check has exactly kind, verdict and explanation, all with string values' in system
    assert "only inside that check's explanation string, within 400 characters" in system
    assert 'does not restrict permitted decision.rationale or decision.stateUpdates' in system
    assert 'Optional decision.status is acted, wait or unable; check.verdict is consistent, inconsistent or unknown' in system
    assert 'Do not add an aggregate status to assessment or the outer object' in system
    assert 'Correct structure does not establish consistency or change a semantic verdict' in system
    if input_kind == 'candidate_error':
        assert 'Return the same outer object with exactly decision and assessment' in system
        assert 'do not return the decision alone or echo the error context' in system
        assert policy._REVIEW_CANDIDATE_PREFIX not in messages[0]['content']
    else:
        assert policy._REVIEW_ERROR_PREFIX not in messages[0]['content']
    size = len(json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8'))
    assert quote['tokens'] == size + spec['policy']['pricing']['inputOverheadTokens'] + 512
    assert result.assessment == assessment and assessment_status(result.assessment, mode=MODE_V3) == 'unresolved'
    assert result.decision == {**final, 'actorId': observation['actorId'], 'observationId': observation['observationId']}
    assert result.usage == _USAGE and (observation, review) == (original_observation, original_review)
