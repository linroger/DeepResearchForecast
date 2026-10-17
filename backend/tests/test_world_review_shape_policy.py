"""Bounded real-SDK/mock-HTTP checks for structural revision diagnostics.

The coordinator runs this module through the guarded offline runner. Diagnostic
fixtures contain no real provider content and do not establish model quality.
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
_NODES = {'root', 'decision', 'assessment', 'checks', 'check0', 'check1', 'check2', 'check3'}


def _malformed(final, location='check0'):
    raw = {'decision': deepcopy(final), 'assessment': v3_fixtures._assessment()}
    if location == 'root':
        del raw['decision']
        target = raw
    elif location == 'assessment':
        target = raw['assessment']
    else:
        target = raw['assessment']['checks'][0]
        del target['explanation']
        target['kind'] = 'PRIVATE_KIND_VALUE'
        target['verdict'] = 'PRIVATE_VERDICT_VALUE'
        target['evidencePaths'] = ['PRIVATE_PATH_VALUE']
    target['status'] = 'PRIVATE_STATUS_VALUE'
    for index in range(6):
        target[f'PRIVATE_UNKNOWN_KEY_{index}'] = {'PRIVATE_NESTED_KEY': 'PRIVATE_NESTED_VALUE'}
    return raw


@pytest.mark.parametrize('location', ['root', 'assessment', 'check0'])
def test_revision_shape_exposes_only_closed_structure_with_known_usage(v3_case, boundary, location):
    from app.services.world_simulation.policy import PolicyFailure, is_candidate_output_failure, revision_shape_diagnostic

    spec, observation, candidate, final = v3_case
    raw = _malformed(final, location)
    original = deepcopy(raw)
    case = boundary(spec=spec, content=json.dumps(raw))
    with pytest.raises(PolicyFailure) as failed:
        case.policy.decide(observation, review=candidate)
    error = failed.value
    assert error.code == ('invalid_review_response' if location == 'root' else 'invalid_assessment')
    assert error.usage == _USAGE and len(case.sent) == 1
    assert not is_candidate_output_failure(error)
    shape = revision_shape_diagnostic(error)
    assert set(shape) == {'schemaVersion', 'nodes', 'checksItemCount'}
    assert shape['schemaVersion'] == 'actor-revision-shape/v1'
    assert set(shape['nodes']) == _NODES and shape['checksItemCount'] == 4
    node = shape['nodes'][location]
    assert node['type'] == 'object'
    assert node['unknownKeyCount'] == 4 and node['unknownKeyOverflow'] is True
    assert node['missingRequiredKeys'] == ({'root': ['decision'], 'assessment': [], 'check0': ['explanation']}[location])
    assert node['recognizedKeys'] == sorted({
        'root': ['assessment', 'status'],
        'assessment': ['checks', 'status'],
        'check0': ['kind', 'verdict', 'status', 'evidencePaths'],
    }[location])
    for record in shape['nodes'].values():
        assert set(record) == {'type', 'recognizedKeys', 'missingRequiredKeys', 'unknownKeyCount', 'unknownKeyOverflow'}
    if location == 'root':
        assert shape['nodes']['decision']['type'] == 'missing'
        assert shape['nodes']['decision']['missingRequiredKeys'] == ['intents']
    encoded = json.dumps(shape)
    assert 'PRIVATE_' not in encoded
    assert observation['observationId'] not in encoded and observation['actorId'] not in encoded
    assert 'PRIVATE_' not in str(error) and raw == original


def test_shape_receipt_is_detached_and_bound_to_original_exception_code_usage_and_shape(v3_case, boundary):
    from app.services.world_simulation.policy import PolicyFailure, revision_shape_diagnostic

    spec, observation, candidate, final = v3_case
    case = boundary(spec=spec, content=json.dumps(_malformed(final)))
    with pytest.raises(PolicyFailure) as failed:
        case.policy.decide(observation, review=candidate)
    error = failed.value
    original = revision_shape_diagnostic(error)
    assert original is not None
    returned = revision_shape_diagnostic(error)
    returned['nodes']['root']['type'] = 'null'
    assert revision_shape_diagnostic(error) == original
    copied = PolicyFailure(error.code, str(error), usage=error.usage)
    copied.__dict__.update(error.__dict__)
    assert revision_shape_diagnostic(copied) is None  # Even all copied attributes retain the original owner.
    assert revision_shape_diagnostic(error) == original
    error.usage['tokens'] += 1
    assert revision_shape_diagnostic(error) is None
    error.usage = deepcopy(_USAGE)
    error.code = 'invalid_review_response'
    assert revision_shape_diagnostic(error) is None
    error.code = 'invalid_assessment'
    error._revision_shape['nodes']['check0']['unknownKeyOverflow'] = False
    assert revision_shape_diagnostic(error) is None
    error._revision_shape = deepcopy(original)
    assert revision_shape_diagnostic(error) == original
    assert error.usage == _USAGE and len(case.sent) == 1


@pytest.mark.parametrize('point', ['builder', 'capture_validator', 'getter_validator'])
def test_optional_shape_failures_preserve_original_typed_error_and_charge(v3_case, boundary, monkeypatch, point):
    from app.services.world_simulation import review
    from app.services.world_simulation.policy import PolicyFailure, revision_shape_diagnostic

    spec, observation, candidate, final = v3_case
    case = boundary(spec=spec, content=json.dumps(_malformed(final)))

    def fail(*args, **kwargs):
        raise RuntimeError('PRIVATE_DIAGNOSTIC_EXCEPTION')

    with monkeypatch.context() as patch:
        if point != 'getter_validator':
            patch.setattr(review, 'build_revision_shape' if point == 'builder' else 'validate_revision_shape', fail)
        with pytest.raises(PolicyFailure) as failed:
            case.policy.decide(observation, review=candidate)
        error = failed.value
        if point == 'getter_validator':
            assert revision_shape_diagnostic(error) is not None
            patch.setattr(review, 'validate_revision_shape', fail)
        assert revision_shape_diagnostic(error) is None
        assert error.code == 'invalid_assessment' and error.usage == _USAGE
        assert str(error) == 'Unsupported assessment check fields'
        assert error.__suppress_context__ and len(case.sent) == 1
    assert (revision_shape_diagnostic(error) is not None) == (point == 'getter_validator')


@pytest.mark.parametrize('origin', ['candidate', 'modeler', 'internal'])
def test_nonrevision_modeler_and_internal_errors_have_no_shape_receipt(v3_case, modeler_case, boundary, monkeypatch, origin):
    from app.services.world_simulation import review
    from app.services.world_simulation.policy import PolicyFailure, StrictHTTPModeler, revision_shape_diagnostic

    spec, observation, candidate, final = v3_case
    request, kwargs = observation, {'review': candidate}
    options = {'spec': spec, 'content': json.dumps(_malformed(final))}
    if origin == 'candidate':
        kwargs = {}
    elif origin == 'modeler':
        options.update(spec=modeler_case.spec, policy_type=StrictHTTPModeler, content='PRIVATE_BROKEN_JSON')
        request, kwargs = modeler_case.messages, {}
    else:
        def broken_validator(*args, **kwargs):
            raise RuntimeError('PRIVATE_INTERNAL_EXCEPTION')

        monkeypatch.setattr(review, 'validate_assessment', broken_validator)
    case = boundary(**options)
    with pytest.raises(PolicyFailure) as failed:
        case.policy.decide(request, **kwargs)
    assert failed.value.usage == _USAGE and revision_shape_diagnostic(failed.value) is None
    assert 'PRIVATE_' not in str(failed.value) and len(case.sent) == 1


def test_shape_diagnostics_reject_untrusted_codes_other_modes_and_excluded_sites(v3_case, boundary, monkeypatch):
    from app.services.world_simulation import review
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.policy import PolicyFailure, revision_shape_diagnostic

    for code in ('invalid_review_response', 'invalid_assessment'):
        bare = PolicyFailure(code, 'A code and charge do not prove origin', usage=_USAGE)
        assert revision_shape_diagnostic(bare) is None
        bare._revision_shape_origin = True
        assert revision_shape_diagnostic(bare) is None
    assert revision_shape_diagnostic(None) is None
    spec, observation, candidate, final = v3_case
    for origin in ('transport', 'metering', 'identity', 'parser', 'legacy', 'grammar', 'validator_spoof'):
        local_spec = deepcopy(spec)
        options = {'spec': local_spec, 'content': json.dumps(_malformed(final))}
        if origin == 'transport':
            options['status'] = 503
        elif origin == 'identity':
            options['model'] = 'another-model'
        elif origin == 'parser':
            options['content'] = 'PRIVATE_NOT_JSON'
        elif origin == 'legacy':
            local_spec['policy']['decisionReview'] = review.MODE_V2
        case = boundary(**options)
        if origin == 'metering':
            case.body['usage'] = None
        with monkeypatch.context() as patch:
            if origin == 'grammar':
                def wrong_site(*args, **kwargs):
                    raise WorldError('invalid_assessment', 'Synthetic error from the wrong scope')

                patch.setattr(case.policy, '_validate_visible_input_grammar', wrong_site)
            elif origin == 'validator_spoof':
                def spoof(*args, **kwargs):
                    raise PolicyFailure('invalid_assessment', 'Bare policy failure is not a validator receipt', usage=_USAGE)

                patch.setattr(review, 'validate_assessment', spoof)
            with pytest.raises(PolicyFailure) as failed:
                case.policy.decide(observation, review=candidate)
        assert revision_shape_diagnostic(failed.value) is None, origin
        assert failed.value.usage == (None if origin in {'transport', 'metering', 'identity'} else _USAGE)
        assert len(case.sent) == 1


def test_shape_capture_uses_request_mode_not_mutated_adapter_or_caller(v3_case, boundary):
    from app.services.world_simulation import review
    from app.services.world_simulation.policy import PolicyFailure, revision_shape_diagnostic

    source_spec, source_observation, source_candidate, final = v3_case
    for initial_mode in (review.MODE_V3, review.MODE_V2):
        spec, observation, candidate = deepcopy((source_spec, source_observation, source_candidate))
        spec['policy']['decisionReview'] = initial_mode
        raw = _malformed(final)
        holder = {}

        def mutate(request, number):
            holder['policy'].decision_review = review.MODE_V2 if initial_mode == review.MODE_V3 else review.MODE_V3
            observation['actorId'] = 'PRIVATE_MUTATED_ACTOR'
            candidate['rationale'] = 'PRIVATE_MUTATED_CANDIDATE'
            return json.dumps(raw)

        case = boundary(spec=spec, content_factory=mutate)
        holder['policy'] = case.policy
        with pytest.raises(PolicyFailure) as failed:
            case.policy.decide(observation, review=candidate)
        shape = revision_shape_diagnostic(failed.value)
        assert (shape is not None) == (initial_mode == review.MODE_V3)
        assert failed.value.usage == _USAGE and len(case.sent) == 1
        assert 'PRIVATE_' not in json.dumps(shape)
