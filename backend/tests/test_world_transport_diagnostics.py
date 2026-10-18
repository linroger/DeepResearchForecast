"""Real SDK classification retains no raw error payload and never retries."""
import pytest
import httpx

import test_world_policy as fixtures

actor_case = fixtures.actor_case
boundary = fixtures.boundary
pytestmark = pytest.mark.guarded_runner


@pytest.mark.parametrize('status', [400, 401, 403, 429, 500, 503])
def test_http_failure_keeps_only_status_and_unknown_exposure(actor_case, boundary, status):
    from app.services.world_simulation.policy import PolicyFailure
    from app.services.world_simulation.consistency_evaluation import _error_message

    case = boundary(status=status, raw_body=b'{"error":"PRIVATE_PROVIDER_BODY_WITH_CREDENTIAL"}')
    quote = case.policy.reservation(actor_case.observation)
    with pytest.raises(PolicyFailure) as failed:
        case.policy.decide(actor_case.observation)
    error = failed.value
    if status == 429:  # A capacity refusal: classified from the status, nothing metered.
        assert error.code == 'provider_throttled' and error.usage == {'tokens': 0, 'costUsd': '0'}
        assert str(error) == 'Provider refused the request for capacity; nothing was metered'
    else:
        assert error.code == 'policy_transport_failed' and error.usage is None
        assert str(error) == f'Actor HTTP dispatch failed with status {status}; exposure is unknown'
        assert _error_message(error) == str(error)
    assert 'PRIVATE_PROVIDER' not in str(error) and len(case.sent) == 1
    assert case.policy.reservation(actor_case.observation) == quote


@pytest.mark.parametrize('error,category', [(httpx.ReadTimeout('SECRET_TIMEOUT'), 'timed out'),
                                          (httpx.ConnectError('SECRET_CONNECTION'), 'connection failed')])
def test_network_failure_uses_fixed_category_only(actor_case, boundary, error, category):
    from app.services.world_simulation.policy import PolicyFailure
    from app.services.world_simulation.consistency_evaluation import _error_message

    case = boundary(error=error)
    with pytest.raises(PolicyFailure) as failed:
        case.policy.decide(actor_case.observation)
    assert failed.value.usage is None and len(case.sent) == 1
    assert category in str(failed.value) and 'SECRET_' not in str(failed.value)
    assert _error_message(failed.value) == str(failed.value)


def test_arbitrary_transport_message_cannot_enter_journal():
    from app.services.world_simulation.consistency_evaluation import _error_message, _GENERIC_FAILURE
    from app.services.world_simulation.policy import PolicyFailure

    assert _error_message(PolicyFailure('policy_transport_failed', 'SECRET_REQUEST_BODY')) == _GENERIC_FAILURE
