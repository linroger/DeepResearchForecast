"""Real strict adapter and installed SDK; only HTTP I/O is replaced.

Run through docs/handoff/reflexive-world-simulation/run_offline.py. Synthetic
prices and provider guarantees are fixture assertions, not live-provider proof.
"""
from copy import deepcopy
from decimal import Decimal
import json
import logging
from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.guarded_runner


@pytest.fixture
def actor_case():
    from app.services.world_simulation.contracts import initial_snapshot
    from app.services.world_simulation.examples import example_spec
    from app.services.world_simulation.observations import build_observation

    spec = example_spec('investment')
    spec['limits'].update(maxOutputTokens=512, maxCostUsd='25')
    spec['policy'] = {
        'provider': 'openai', 'model': 'fixture-model-v1', 'baseUrl': 'https://fixture.invalid/v1',
        'timeoutSeconds': 17, 'maxInputTokens': 30000,
        'pricing': {
            'provider': 'openai', 'model': 'fixture-model-v1', 'baseUrl': 'https://fixture.invalid/v1',
            'inputUsdPerMillion': '2', 'outputUsdPerMillion': '9',
            'contextWindowTokens': 32768, 'maxOutputTokens': 2048, 'inputOverheadTokens': 256,
            'outputTokenParameter': 'max_completion_tokens', 'maxOutputIncludesReasoning': True,
            'source': {'reference': 'fixture://synthetic-inclusive-tariff-and-bounds',
                       'asOf': '2026-10-16T00:00:00Z'},
        },
    }
    snapshot = initial_snapshot(spec)
    observation = build_observation(spec, snapshot, 'buyer', 1)
    return SimpleNamespace(spec=spec, snapshot=snapshot, observation=observation)


def _decision(observation):
    return {'actorId': observation['actorId'], 'observationId': observation['observationId'],
            'intents': [], 'status': 'wait'}


@pytest.fixture
def boundary(actor_case):
    """The SDK is real; a fake HTTP boundary records each actual dispatch."""
    import httpx
    from openai import OpenAI

    from app.services.world_simulation.policy import StrictHTTPPolicy

    clients = []

    def create(*, spec=None, content=None, usage=None, status=200, error=None, model=None,
               finish='stop', message_extra=None, headers=None, raw_body=None, policy_type=StrictHTTPPolicy,
               content_factory=None):
        spec = deepcopy(spec or actor_case.spec)
        sent = []
        body = {
            'id': 'completion-fixture', 'object': 'chat.completion', 'created': 0,
            'model': model or spec['policy']['model'],
            'choices': [{'index': 0, 'finish_reason': finish,
                         'message': {'role': 'assistant',
                                     'content': content if content is not None else json.dumps(_decision(actor_case.observation)),
                                     **(message_extra or {})}}],
            'usage': usage if usage is not None else {
                'prompt_tokens': 100, 'completion_tokens': 40, 'total_tokens': 140,
                'prompt_tokens_details': {'cached_tokens': 80},
                'completion_tokens_details': {'reasoning_tokens': 30},
            },
        }

        def dispatch(request):
            sent.append(request)
            if error is not None:
                raise error
            if raw_body is not None:
                return httpx.Response(status, content=raw_body,
                                      headers={'content-type': 'application/json', **(headers or {})})
            response_body = deepcopy(body)
            if content_factory is not None:
                response_body['choices'][0]['message']['content'] = content_factory(request, len(sent))
            return httpx.Response(status, json=response_body, headers=headers)

        http = httpx.Client(transport=httpx.MockTransport(dispatch), follow_redirects=False, trust_env=False)
        sdk = OpenAI(api_key='fixture-only-secret-never-real', base_url=spec['policy']['baseUrl'],
                     http_client=http, max_retries=6)
        clients.append(sdk)
        adapter = policy_type(spec, client=sdk)
        clients.append(adapter)
        return SimpleNamespace(policy=adapter, sdk=sdk, http=http, sent=sent, body=body, spec=spec)

    yield create
    for client in clients:
        client.close()


def test_one_dispatch_exact_contract_and_inclusive_metering(actor_case, boundary):
    from app.services.world_simulation.controller import PolicyResponse

    case = boundary()
    reserve = case.policy.reservation(actor_case.observation)
    assert case.sent == []
    result = case.policy.decide(actor_case.observation)
    assert isinstance(result, PolicyResponse)
    assert result.decision == _decision(actor_case.observation)
    assert result.usage == {'tokens': 140, 'costUsd': '0.000560000000'}
    assert reserve['tokens'] >= result.usage['tokens']
    assert Decimal(reserve['costUsd']) >= Decimal(result.usage['costUsd'])
    assert len(case.sent) == 1
    request = case.sent[0]
    payload = json.loads(request.content)
    assert set(payload) == {'messages', 'model', 'max_completion_tokens', 'n', 'stream'}
    assert payload['model'] == actor_case.spec['policy']['model']
    assert payload['max_completion_tokens'] == 512
    assert payload['n'] == 1 and payload['stream'] is False
    assert all(value == 17 for value in request.extensions['timeout'].values())
    assert case.policy._client.max_retries == 0
    assert case.sdk.max_retries == 6  # Caller-owned SDK was not mutated.
    assert str(request.url) == 'https://fixture.invalid/v1/chat/completions'


def test_utf8_exact_bytes_and_maximum_exposure(actor_case, boundary):
    from app.services.world_simulation.contracts import canonical_json, digest

    observation = deepcopy(actor_case.observation)
    observation['actor']['name'] = '采购方 🌊 é e\u0301'
    observation['observationId'] = digest({k: v for k, v in observation.items() if k != 'observationId'})
    case = boundary(content=json.dumps(_decision(observation)))
    reserve = case.policy.reservation(observation)
    upper = reserve['tokens'] - 512
    case.body['usage'] = {'prompt_tokens': upper, 'completion_tokens': 512, 'total_tokens': upper + 512,
                          'prompt_tokens_details': {'cached_tokens': upper},
                          'completion_tokens_details': {'reasoning_tokens': 500}}
    result = case.policy.decide(observation)
    messages = json.loads(case.sent[0].content)['messages']
    assert messages[1]['content'] == canonical_json(observation)
    encoded = canonical_json(messages).encode('utf-8')
    assert len(encoded) > len(canonical_json(messages))
    assert upper == len(encoded) + 256
    assert result.usage == reserve
    assert Decimal(reserve['costUsd']) >= (Decimal(upper) * 2 + Decimal(512) * 9) / 1000000


def test_hidden_spec_mutations_leave_actual_request_bytes_identical(actor_case, boundary):
    from app.services.world_simulation.contracts import initial_snapshot
    from app.services.world_simulation.observations import build_observation

    other = deepcopy(actor_case.spec)
    other['actors'][2]['beliefs'] = ['DENIED_RIVAL_BELIEF']
    other['initialState']['accounts']['producer_cash']['balance'] = '987654'
    other['actionCatalog'][0]['parameters']['cost'] = '4444'
    other['privateResearch'] = {'secret': 'DENIED_RESEARCH', 'specHash': 'DENIED_HASH'}
    other_obs = build_observation(other, initial_snapshot(other), 'buyer', 1)
    assert other_obs == actor_case.observation
    first, second = boundary(), boundary(spec=other)
    first.policy.decide(actor_case.observation)
    second.policy.decide(other_obs)
    assert first.sent[0].content == second.sent[0].content
    body = first.sent[0].content.decode()
    for denied in ('DENIED_RIVAL_BELIEF', 'DENIED_RESEARCH', 'DENIED_HASH', '987654', '4444',
                   'specHash', 'generationId', 'inputUsdPerMillion', 'baseUrl'):
        assert denied not in body


@pytest.mark.parametrize('status', [429, 500, 503, 307])
def test_http_error_or_redirect_never_retries(actor_case, boundary, status):
    from app.services.world_simulation.policy import PolicyFailure

    case = boundary(status=status, headers={'location': 'https://fallback.invalid/v1/chat/completions',
                                           'retry-after': '0', 'x-should-retry': 'true'})
    with pytest.raises(PolicyFailure) as caught:
        case.policy.decide(actor_case.observation)
    assert caught.value.usage is None
    assert len(case.sent) == 1


def test_timeout_is_one_dispatch_and_logs_and_errors_are_sanitized(actor_case, boundary, caplog):
    import httpx
    from app.services.world_simulation.policy import PolicyFailure

    secret = 'PRIVATE_KEY_FROM_PROVIDER_EXCEPTION'
    case = boundary(error=httpx.ReadTimeout(secret))
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(PolicyFailure) as caught:
            case.policy.decide(actor_case.observation)
    assert len(case.sent) == 1
    assert caught.value.usage is None
    assert caught.value.__suppress_context__
    assert secret not in str(caught.value) and secret not in caplog.text
    assert 'fixture-only-secret-never-real' not in caplog.text
    assert actor_case.observation['observationId'] not in caplog.text


@pytest.mark.parametrize('content', [
    '{"actorId":"buyer","actorId":"authority"}',
    '{"stateUpdates":{"é":[],"e\\u0301":[]}}',
    '{"intents":[{"parameters":{"amount":1.25}}]}',
    '{"priority":1e2}', '{"x":NaN}', '{"x":Infinity}',
    '[]', 'null', 'not JSON', '```json\n{}\n```', '{} {}', '{"x":"\\ud800"}',
])
def test_strict_malformed_responses_keep_usage(actor_case, boundary, content):
    from app.services.world_simulation.policy import PolicyFailure

    case = boundary(content=content)
    with pytest.raises(PolicyFailure) as caught:
        case.policy.decide(actor_case.observation)
    assert caught.value.code == 'policy_invalid_response'
    assert caught.value.usage == {'tokens': 140, 'costUsd': '0.000560000000'}
    assert len(case.sent) == 1
    assert content not in str(caught.value)


def test_decimal_strings_and_integer_quantities_preserved_for_controller(actor_case, boundary):
    from app.services.world_simulation.contracts import validate_decision

    decision = _decision(actor_case.observation)
    decision.update(status='acted', intents=[{'templateId': 'purchase', 'operation': 'propose',
                                            'parameters': {'quantity': '1.25', 'price': 3}}])
    case = boundary(content=json.dumps(decision))
    response = case.policy.decide(actor_case.observation)
    validated = validate_decision(actor_case.spec, response.decision, 'buyer', actor_case.observation,
                                  phase='proposal')
    assert validated['intents'][0]['parameters'] == {'quantity': '1.25', 'price': 3}


@pytest.mark.parametrize('finish,message_extra', [
    ('length', {}), ('content_filter', {}),
    ('tool_calls', {'tool_calls': [{'id': 'call_x', 'type': 'function',
                                  'function': {'name': 'browse', 'arguments': '{}'}}]}),
    ('stop', {'function_call': {'name': 'browse', 'arguments': '{}'}}),
    ('stop', {'refusal': 'refused'}),
])
def test_incomplete_or_tool_responses_retain_usage(actor_case, boundary, finish, message_extra):
    from app.services.world_simulation.policy import PolicyFailure

    case = boundary(finish=finish, message_extra=message_extra)
    with pytest.raises(PolicyFailure) as caught:
        case.policy.decide(actor_case.observation)
    assert caught.value.usage['tokens'] == 140
    assert len(case.sent) == 1


@pytest.mark.parametrize('usage', [
    {}, {'prompt_tokens': 0, 'completion_tokens': 0},
    {'prompt_tokens': -1, 'completion_tokens': 2, 'total_tokens': 1},
    {'prompt_tokens': 100, 'completion_tokens': 600, 'total_tokens': 700},
    {'prompt_tokens': 1000000, 'completion_tokens': 1, 'total_tokens': 1000001},
    {'prompt_tokens': 100, 'completion_tokens': 40, 'total_tokens': 141},
    {'prompt_tokens': True, 'completion_tokens': 40, 'total_tokens': 41},
    {'prompt_tokens': 100.5, 'completion_tokens': 40, 'total_tokens': 140},
    {'prompt_tokens': 100, 'completion_tokens': 40, 'total_tokens': 140,
     'completion_tokens_details': {'reasoning_tokens': 41}},
    {'prompt_tokens': 100, 'completion_tokens': 40, 'total_tokens': 140,
     'prompt_tokens_details': {'cached_tokens': 101}},
    {'prompt_tokens': 100, 'completion_tokens': 40, 'total_tokens': 140,
     'prompt_tokens_details': {'cached_tokens': False}},
    {'prompt_tokens': 100, 'completion_tokens': 40, 'total_tokens': 140,
     'cache_read_input_tokens': 60, 'cache_creation_input_tokens': 60},
])
def test_missing_or_unbounded_usage_keeps_unknown_exposure(actor_case, boundary, usage):
    from app.services.world_simulation.policy import PolicyFailure

    case = boundary(usage=usage)
    with pytest.raises(PolicyFailure) as caught:
        case.policy.decide(actor_case.observation)
    assert caught.value.code == 'policy_usage_unavailable'
    assert caught.value.usage is None
    assert len(case.sent) == 1


def test_cache_categories_never_discount_reserved_or_actual_cost(actor_case, boundary):
    usage = {'prompt_tokens': 100, 'completion_tokens': 40, 'total_tokens': 140,
             'cache_read_input_tokens': 60, 'cache_creation_input_tokens': 40,
             'prompt_cache_hit_tokens': 60, 'prompt_cache_miss_tokens': 40}
    case = boundary(usage=usage)
    result = case.policy.decide(actor_case.observation)
    assert result.usage == {'tokens': 140, 'costUsd': '0.000560000000'}


@pytest.mark.parametrize('raw_body', [
    '{"model":"fixture-model-v1","usage":{"prompt_tokens":1,"prompt_tokens":100,"completion_tokens":40,"total_tokens":41}}',
    '{"model":"fixture-model-v1","usage":{"prompt_tokens":1.0,"completion_tokens":40,"total_tokens":41}}',
    '{"model":"fixture-model-v1","usage":{"prompt_tokens":1,"completion_tokens":40,"total_tokens":41},"usage":null}',
])
def test_raw_envelope_metering_is_validated_before_sdk_coercion(actor_case, boundary, raw_body):
    from app.services.world_simulation.policy import PolicyFailure

    case = boundary(raw_body=raw_body)
    with pytest.raises(PolicyFailure) as caught:
        case.policy.decide(actor_case.observation)
    assert caught.value.code == 'policy_usage_unavailable'
    assert caught.value.usage is None
    assert len(case.sent) == 1


def test_native_constructor_pins_config_and_disables_all_retry_layers(actor_case, monkeypatch):
    from app.config import Config
    from app.services.world_simulation.policy import StrictHTTPPolicy

    # These values are synthetic. Do not inventory or read real credentials.
    monkeypatch.setattr(Config, 'LLM_PROVIDER', 'openai')
    monkeypatch.setattr(Config, 'LLM_BASE_URL', actor_case.spec['policy']['baseUrl'])
    monkeypatch.setattr(Config, 'LLM_API_KEY', 'fixture-only-secret-never-real')
    adapter = StrictHTTPPolicy(actor_case.spec)
    try:
        assert adapter._client.max_retries == 0
        assert adapter._client._client.follow_redirects is False
        assert adapter._client._client._transport._pool._retries == 0
        assert adapter._client.timeout == 17
    finally:
        adapter.close()


def test_fractional_auxiliary_provider_telemetry_preserves_valid_metering(actor_case, boundary):
    case = boundary()
    case.body['provider_cost'] = 0.000123
    case.body['choices'][0]['logprobs'] = {'content': [{'logprob': -0.01234}]}
    response = case.policy.decide(actor_case.observation)
    assert response.usage == {'tokens': 140, 'costUsd': '0.000560000000'}
    assert len(case.sent) == 1


def test_injected_http_client_mutation_cannot_enable_hidden_dispatches(actor_case, boundary):
    from app.services.world_simulation.policy import PolicyFailure

    case = boundary(status=307, headers={'location': 'https://fallback.invalid/v1/chat/completions'})
    case.http.follow_redirects = True
    hook_calls = []
    case.http.event_hooks = {'request': [lambda request: hook_calls.append(request)]}
    case.sdk.max_retries = 4
    with pytest.raises(PolicyFailure):
        case.policy.decide(actor_case.observation)
    assert len(case.sent) == 1
    assert hook_calls == []
    assert case.policy._client._client is not case.http
    assert case.policy._client._client.follow_redirects is False


@pytest.mark.parametrize('field', [
    'provider', 'model', 'baseUrl', 'inputUsdPerMillion', 'outputUsdPerMillion',
    'contextWindowTokens', 'maxOutputTokens', 'inputOverheadTokens',
    'outputTokenParameter', 'maxOutputIncludesReasoning', 'source',
])
def test_missing_price_or_capability_metadata_fails_preflight(actor_case, boundary, field):
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.policy import StrictHTTPPolicy

    case = boundary()
    spec = deepcopy(actor_case.spec)
    del spec['policy']['pricing'][field]
    with pytest.raises(WorldError):
        StrictHTTPPolicy(spec, client=case.sdk)
    assert case.sent == []


@pytest.mark.parametrize('change', [
    {'provider': 'codex-cli'}, {'provider': 'claude-cli'}, {'provider': 'unsupported-http'},
    {'model': 'different-model'}, {'timeoutSeconds': 0}, {'timeoutSeconds': 121},
    {'timeoutSeconds': True}, {'baseUrl': 'https://key:secret@fixture.invalid/v1'},
    {'baseUrl': 'https://fixture.invalid/v1?api_key=secret'},
])
def test_transport_identity_and_limits_reject_before_dispatch(actor_case, boundary, change):
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.policy import StrictHTTPPolicy

    case = boundary()
    spec = deepcopy(actor_case.spec)
    spec['policy'].update(change)
    with pytest.raises(WorldError) as caught:
        StrictHTTPPolicy(spec, client=case.sdk)
    assert 'secret' not in str(caught.value)
    assert case.sent == []


def test_pricing_override_must_equal_pinned_spec(actor_case, boundary):
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.policy import StrictHTTPPolicy

    case = boundary()
    price = deepcopy(actor_case.spec['policy']['pricing'])
    StrictHTTPPolicy(actor_case.spec, client=case.sdk, pricing=price)
    price['inputUsdPerMillion'] = '0.1'
    with pytest.raises(WorldError, match='pinned specification'):
        StrictHTTPPolicy(actor_case.spec, client=case.sdk, pricing=price)
    spec = deepcopy(actor_case.spec)
    del spec['policy']['pricing']
    with pytest.raises(WorldError):
        StrictHTTPPolicy(spec, client=case.sdk, pricing=price)
    assert case.sent == []


def test_max_input_and_context_reject_actual_observation_before_dispatch(actor_case, boundary):
    from app.services.world_simulation.contracts import WorldError

    for key, value in [('maxInputTokens', 1), ('contextWindowTokens', 600)]:
        spec = deepcopy(actor_case.spec)
        target = spec['policy'] if key == 'maxInputTokens' else spec['policy']['pricing']
        target[key] = value
        case = boundary(spec=spec)
        with pytest.raises(WorldError, match='context token bound'):
            case.policy.reservation(actor_case.observation)
        with pytest.raises(WorldError, match='context token bound'):
            case.policy.decide(actor_case.observation)
        assert case.sent == []


def test_unprojected_or_tampered_observation_fails_before_dispatch(actor_case, boundary):
    from app.services.world_simulation.contracts import WorldError, digest

    case = boundary()
    for mutation in ('extra', 'digest', 'denied', 'menu'):
        obs = deepcopy(actor_case.observation)
        if mutation == 'extra':
            obs['specHash'] = 'hidden'
        elif mutation == 'digest':
            obs['actor']['name'] = 'tampered'
        elif mutation == 'denied':
            obs['world']['accounts']['secret'] = {
                'visibility': {'kind': 'actors', 'actorIds': ['producer']}, 'balance': '123'}
        else:
            obs['options'][0]['parameters'] = {'cost': 'hidden'}
        if mutation != 'digest':
            obs['observationId'] = digest({k: v for k, v in obs.items() if k != 'observationId'})
        with pytest.raises(WorldError):
            case.policy.decide(obs)
    assert case.sent == []


def test_response_model_mismatch_rejected_and_detached_spec_cannot_change_request(actor_case, boundary):
    from app.services.world_simulation.policy import PolicyFailure

    case = boundary(model='fallback-model')
    case.spec['policy']['model'] = 'fallback-model'
    with pytest.raises(PolicyFailure) as caught:
        case.policy.decide(actor_case.observation)
    assert caught.value.code == 'policy_identity_mismatch'
    assert caught.value.usage is None
    assert json.loads(case.sent[0].content)['model'] == 'fixture-model-v1'
    assert len(case.sent) == 1


def test_transport_rejects_redirects_hooks_and_connection_retries(actor_case, boundary):
    import httpx
    from openai import OpenAI
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.policy import StrictHTTPPolicy

    case = boundary()
    case.http.follow_redirects = True
    with pytest.raises(WorldError):
        StrictHTTPPolicy(actor_case.spec, client=case.sdk)
    case.http.follow_redirects = False
    case.http.event_hooks = {'request': [lambda request: None]}
    with pytest.raises(WorldError):
        StrictHTTPPolicy(actor_case.spec, client=case.sdk)
    with httpx.Client(transport=httpx.HTTPTransport(retries=2), trust_env=False) as http:
        sdk = OpenAI(api_key='fake', base_url=actor_case.spec['policy']['baseUrl'], http_client=http)
        with pytest.raises(WorldError):
            StrictHTTPPolicy(actor_case.spec, client=sdk)
    assert case.sent == []


def test_tiny_rates_round_exposure_up_to_durable_decimal_precision(actor_case, boundary):
    spec = deepcopy(actor_case.spec)
    spec['policy']['pricing'].update(inputUsdPerMillion='0.000000000001', outputUsdPerMillion='0.000000000001')
    case = boundary(spec=spec)
    reserve = case.policy.reservation(actor_case.observation)
    result = case.policy.decide(actor_case.observation)
    assert Decimal(result.usage['costUsd']) == Decimal('0.000000000001')
    assert Decimal(reserve['costUsd']) >= Decimal(result.usage['costUsd'])


@pytest.mark.parametrize('failure,expected_status', [('malformed', 'failed'), ('model', 'unknown')])
def test_real_controller_charges_adapter_failures_and_keeps_attempt_limit(
        actor_case, boundary, tmp_path, failure, expected_status):
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.controller import run_round
    from app.services.world_simulation.store import WorldStore

    case = boundary(content='invalid JSON' if failure == 'malformed' else '{}',
                    model='fallback-model' if failure == 'model' else None)
    with WorldStore(tmp_path / 'policy.sqlite3', case.spec) as store:
        fence = store.acquire_writer('policy-adapter-test')
        with pytest.raises(WorldError):
            run_round(store, case.policy, fence)
        assert store.head()['round'] == 0
        count = len(case.spec['actors']) * case.spec['limits']['maxAttemptsPerSlot']
        summary = store.budget_summary()
        assert len(case.sent) == len(summary['attempts']) == count
        assert {attempt['status'] for attempt in summary['attempts']} == {expected_status}
        if failure == 'malformed':
            assert summary['actual']['tokens'] == 140 * count
            assert Decimal(summary['actual']['costUsd']) == Decimal('0.00056') * count
            assert summary['unknown']['tokens'] == 0
        else:
            assert summary['actual']['tokens'] == 0
            assert summary['unknown'] == summary['reserved']
        with pytest.raises(WorldError):
            run_round(store, case.policy, fence)
        assert len(case.sent) == count


def test_real_controller_budget_denial_prevents_first_http_dispatch(actor_case, boundary, tmp_path):
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.controller import run_round
    from app.services.world_simulation.store import WorldStore

    spec = deepcopy(actor_case.spec)
    spec['limits']['maxCostUsd'] = '0.000000000001'
    case = boundary(spec=spec)
    with WorldStore(tmp_path / 'denied.sqlite3', spec) as store:
        fence = store.acquire_writer('policy-budget-test')
        with pytest.raises(WorldError):
            run_round(store, case.policy, fence)
        assert case.sent == []
        assert store.budget_summary()['attempts'] == []
        assert store.head()['round'] == 0


@pytest.fixture
def modeler_case(actor_case):
    from app.services.world_simulation.compiler import build_compiler_messages

    report = 'Acme studies supply. Cafe\u0301 采购方 🌊 remains source text.'
    bundle = {'actors': [{'actor_id': 'acme', 'name': 'Acme', 'claims': []}]}
    messages = build_compiler_messages(research_report=report, research_generation_id='research-modeler',
                                       research_engine='v3', actor_bundle=bundle,
                                       ontology={'entityTypes': ['Organization']})
    # No actor roster or actor-only limits exist before the world is compiled.
    spec = {'policy': deepcopy(actor_case.spec['policy']), 'limits': {'maxOutputTokens': 512}}
    basis = {'kind': 'scenario_assumption', 'refs': ['modeler-fixture']}
    proposal = {
        'periods': [{'start': '2030-01-01T00:00:00Z', 'end': '2030-01-02T00:00:00Z'}],
        'actors': [{'actorId': 'acme', 'name': 'Acme', 'basis': deepcopy(basis),
                    'capabilities': ['wait'], 'controlledAccounts': []}],
        'initialState': {'accounts': {}, 'metrics': {}, 'rules': {}, 'relations': {}},
        'actionCatalog': [{'templateId': 'wait', 'kind': 'wait', 'actorIds': ['acme'],
                           'description': 'Wait for the next decision.', 'parameters': {}, 'inputs': {},
                           'basis': deepcopy(basis), 'visibility': {'kind': 'public'}}],
        'assumptions': [{'assumptionId': 'modeler-fixture', 'description': 'Synthetic timing and waiting.',
                         'visibility': {'kind': 'public'}}],
    }
    return SimpleNamespace(spec=spec, messages=messages, report=report, bundle=bundle, proposal=proposal)


def test_modeler_real_compiler_producer_and_consumer_preserve_source_bytes(modeler_case, boundary):
    from app.services.world_simulation.compiler import compile_world_spec
    from app.services.world_simulation.contracts import canonical_json
    from app.services.world_simulation.controller import PolicyResponse
    from app.services.world_simulation.policy import StrictHTTPModeler

    original = deepcopy(modeler_case.messages)
    case = boundary(spec=modeler_case.spec, policy_type=StrictHTTPModeler,
                    content=json.dumps(modeler_case.proposal))
    reservation = case.policy.reservation(messages=modeler_case.messages)
    assert case.sent == [] and case.policy.external is True
    response = case.policy.decide(messages=modeler_case.messages)
    assert isinstance(response, PolicyResponse) and response.decision == modeler_case.proposal
    assert modeler_case.messages == original
    sent = json.loads(case.sent[0].content)
    assert sent['messages'] == original
    assert 'Cafe\u0301' in sent['messages'][1]['content']
    exact = json.dumps(original, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    assert len(exact) > len(canonical_json(original).encode('utf-8'))
    assert reservation['tokens'] == len(exact) + 256 + 512
    assert response.usage == {'tokens': 140, 'costUsd': '0.000560000000'}
    assert len(case.sent) == 1 and case.policy._client.max_retries == 0
    compiled = compile_world_spec(response.decision, simulation_id='modeler-sim', generation_id='modeler-world',
                                  research_report=modeler_case.report, research_generation_id='research-modeler',
                                  research_engine='v3', actor_bundle=modeler_case.bundle)
    assert compiled['sourceBindings']['researchGenerationId'] == 'research-modeler'
    assert compiled['actors'][0]['actorId'] == 'acme'


@pytest.mark.parametrize('messages', [
    None, [], [{'role': 'user', 'content': 'x'}],
    [{'role': 'system', 'content': 'x'}, {'role': 'assistant', 'content': '{}'}],
    [{'role': 'system', 'content': 'x'}, {'role': 'tool', 'content': '{}'}],
    [{'role': 'system', 'content': 'x'}, {'role': 'user', 'content': [{'type': 'text', 'text': 'x'}]}],
    [{'role': 'system', 'content': 'x'}, {'role': 'user', 'content': 'x', 'tools': []}],
    [{'role': 'system', 'content': 'x'}, {'role': 'user', 'content': 'x', 'cache_control': {}}],
    [{'role': 'system', 'content': 'x'}, {'role': 'user', 'content': ''}],
    [{'role': 'system', 'content': 'x'}, {'role': 'user', 'content': '\ud800'}],
])
def test_modeler_rejects_noncanonical_message_shape_without_dispatch(modeler_case, boundary, messages):
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.policy import StrictHTTPModeler

    case = boundary(spec=modeler_case.spec, policy_type=StrictHTTPModeler)
    for method in (case.policy.reservation, case.policy.decide):
        with pytest.raises(WorldError) as caught:
            method(messages)
        assert caught.value.code == 'invalid_policy_messages'
    assert case.sent == []


def test_modeler_reservation_covers_maximum_usage_and_context_overflow(modeler_case, boundary):
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.policy import StrictHTTPModeler

    case = boundary(spec=modeler_case.spec, policy_type=StrictHTTPModeler, content='{"gaps":[]}')
    reservation = case.policy.reservation(modeler_case.messages)
    upper = reservation['tokens'] - 512
    case.body['usage'] = {'prompt_tokens': upper, 'completion_tokens': 512, 'total_tokens': upper + 512,
                          'completion_tokens_details': {'reasoning_tokens': 500},
                          'prompt_tokens_details': {'cached_tokens': upper}}
    assert case.policy.decide(modeler_case.messages).usage == reservation
    for key in ('maxInputTokens', 'contextWindowTokens'):
        spec = deepcopy(modeler_case.spec)
        if key == 'maxInputTokens':
            spec['policy'][key] = upper - 1
        else:
            spec['policy']['pricing'][key] = upper + 511
        denied = boundary(spec=spec, policy_type=StrictHTTPModeler)
        with pytest.raises(WorldError):
            denied.policy.decide(modeler_case.messages)
        assert denied.sent == []


@pytest.mark.parametrize('content', [
    '{"initialState":{"metrics":{"capacity":{"value":1.25}}}}',
    '{"initialState":{},"initialState":{"metrics":{}}}', '{"x":NaN}', '```json\n{}\n```',
])
def test_modeler_world_json_remains_strict_and_failed_usage_is_accountable(modeler_case, boundary, content):
    from app.services.world_simulation.policy import PolicyFailure, StrictHTTPModeler

    case = boundary(spec=modeler_case.spec, policy_type=StrictHTTPModeler, content=content)
    with pytest.raises(PolicyFailure) as caught:
        case.policy.decide(modeler_case.messages)
    assert caught.value.code == 'policy_invalid_response'
    assert caught.value.usage == {'tokens': 140, 'costUsd': '0.000560000000'}
    assert len(case.sent) == 1


@pytest.mark.parametrize('failure', ['429', 'redirect', 'timeout', 'model', 'metering'])
def test_modeler_uses_same_single_dispatch_failure_boundary(modeler_case, boundary, failure, caplog):
    import httpx
    from app.services.world_simulation.policy import PolicyFailure, StrictHTTPModeler

    secret = 'PRIVATE_MODELER_PROVIDER_EXCEPTION'
    kwargs = {'429': {'status': 429},
              'redirect': {'status': 307, 'headers': {'location': 'https://fallback.invalid/v1'}},
              'timeout': {'error': httpx.ReadTimeout(secret)},
              'model': {'model': 'fallback-model'}, 'metering': {'usage': {}}}[failure]
    case = boundary(spec=modeler_case.spec, policy_type=StrictHTTPModeler, **kwargs)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(PolicyFailure) as caught:
            case.policy.decide(modeler_case.messages)
    assert caught.value.usage is None and len(case.sent) == 1
    assert secret not in str(caught.value) and secret not in caplog.text
    assert modeler_case.report not in caplog.text


def test_modeler_messages_cannot_bypass_actor_projection(actor_case, modeler_case, boundary):
    from app.services.world_simulation.contracts import WorldError

    case = boundary()
    with pytest.raises(WorldError) as caught:
        case.policy.decide(modeler_case.messages)
    assert caught.value.code == 'invalid_observation' and case.sent == []


@pytest.fixture
def delivered_message_case(actor_case):
    from app.services.world_simulation.contracts import initial_snapshot, validate_decision
    from app.services.world_simulation.kernel import resolve_round, stage_interactions
    from app.services.world_simulation.observations import build_observation

    spec = deepcopy(actor_case.spec)
    template = next(item for item in spec['actionCatalog'] if item['templateId'] == 'communicate')
    template['parameters'] = {'recipientIds': ['buyer'], 'messageDelayDays': '1', 'offerTtlDays': '3'}
    template['visibility'] = {'kind': 'actors', 'actorIds': ['producer', 'buyer']}
    initial = initial_snapshot(spec)
    origin = build_observation(spec, initial, 'producer', 1)
    raw = _decision(origin)
    raw.update(status='acted', intents=[{'templateId': 'communicate',
                                       'parameters': {'text': 'DELIVERED_PRIVATE_MESSAGE 采购'}}])
    decision = validate_decision(spec, raw, 'producer', origin, phase='proposal')
    staged = stage_interactions(spec, initial, [decision], 1)
    early = build_observation(spec, staged, 'buyer', 1)
    after = resolve_round(spec, initial, [decision], 1)['snapshot']
    delivered = build_observation(spec, after, 'buyer', 2)
    denied = build_observation(spec, after, 'financier', 2)
    for round_index in (2, 3):
        after = resolve_round(spec, after, [], round_index)['snapshot']
    expired = build_observation(spec, after, 'buyer', 4)
    return SimpleNamespace(spec=spec, early=early, delivered=delivered, denied=denied, expired=expired)


def test_actor_http_preserves_real_delayed_message_projection(delivered_message_case, boundary):
    case = boundary(spec=delivered_message_case.spec)
    for observation in (delivered_message_case.early, delivered_message_case.delivered,
                        delivered_message_case.denied, delivered_message_case.expired):
        case.body['choices'][0]['message']['content'] = json.dumps(_decision(observation))
        result = case.policy.decide(observation)
        assert result.decision == _decision(observation)
        sent = json.loads(json.loads(case.sent[-1].content)['messages'][1]['content'])
        assert sent['messages'] == observation['messages']
        if observation is delivered_message_case.delivered:
            assert len(sent['messages']) == 1
            assert sent['messages'][0]['terms']['text'] == 'DELIVERED_PRIVATE_MESSAGE 采购'
        else:
            assert sent['messages'] == [] and 'DELIVERED_PRIVATE_MESSAGE' not in case.sent[-1].content.decode()
    assert len(case.sent) == 4


@pytest.mark.parametrize('change', ['audience', 'early', 'expired', 'extra', 'missing', 'kind', 'text'])
def test_actor_rejects_forged_delivered_message_before_http(delivered_message_case, boundary, change):
    from app.services.world_simulation.contracts import WorldError, digest

    case = boundary(spec=delivered_message_case.spec)
    observation = deepcopy(delivered_message_case.delivered)
    message = observation['messages'][0]
    if change == 'audience':
        message['visibility'] = {'kind': 'actors', 'actorIds': ['producer']}
    elif change == 'early':
        message['deliverAt'] = '2030-01-03T00:00:00Z'
    elif change == 'expired':
        message['expiresAt'] = observation['simulatedAt']
    elif change == 'extra':
        message['specHash'] = 'HIDDEN_GLOBAL_HASH'
    elif change == 'missing':
        del message['termsVersion']
    elif change == 'kind':
        message['kind'] = 'agreement'
    else:
        message['terms']['text'] = 1.25
        with pytest.raises(WorldError):
            case.policy.decide(observation)
        assert case.sent == []
        return
    observation['observationId'] = digest({k: v for k, v in observation.items() if k != 'observationId'})
    with pytest.raises(WorldError):
        case.policy.decide(observation)
    assert case.sent == []


@pytest.mark.parametrize('mode', ['actor', 'modeler'])
@pytest.mark.parametrize('effort', [None, 'low', 'high', 'max'])
def test_pinned_reasoning_effort_is_exact_optional_sdk_field(
        actor_case, modeler_case, boundary, monkeypatch, mode, effort):
    from app.services.world_simulation.policy import StrictHTTPModeler, StrictHTTPPolicy

    spec = deepcopy(actor_case.spec if mode == 'actor' else modeler_case.spec)
    spec['policy'].update(provider='glm', model='glm-5.3')
    spec['policy']['pricing'].update(provider='glm', model='glm-5.3', outputTokenParameter='max_tokens')
    if effort is not None:
        spec['policy']['reasoningEffort'] = effort
    monkeypatch.setenv('LLM_FALLBACK_REASONING_EFFORT', 'high')
    policy_type = StrictHTTPPolicy if mode == 'actor' else StrictHTTPModeler
    case = boundary(spec=spec, policy_type=policy_type, content='{}')
    request = actor_case.observation if mode == 'actor' else modeler_case.messages
    reservation = case.policy.reservation(request)
    response = case.policy.decide(request)
    assert len(case.sent) == 1
    payload = json.loads(case.sent[0].content)
    expected = {'model', 'messages', 'n', 'stream', 'max_tokens'}
    if effort is not None:
        expected.add('reasoning_effort')
        assert payload['reasoning_effort'] == effort
    assert set(payload) == expected
    assert payload['model'] == 'glm-5.3' and payload['max_tokens'] == 512
    assert response.usage == {'tokens': 140, 'costUsd': '0.000560000000'}
    assert reservation == case.policy.reservation(request)


@pytest.mark.parametrize('effort', [None, '', 'medium', 'LOW', 'high ', True, 1, [], {}])
def test_invalid_pinned_reasoning_effort_rejects_before_dispatch(actor_case, boundary, effort):
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.policy import StrictHTTPPolicy

    case = boundary()
    spec = deepcopy(actor_case.spec)
    spec['policy']['reasoningEffort'] = effort
    with pytest.raises(WorldError) as caught:
        StrictHTTPPolicy(spec, client=case.sdk)
    assert caught.value.code == 'invalid_policy_metadata'
    assert case.sent == []


def test_actor_prompt_reflection_shapes_match_validator_and_kernel(actor_case, boundary):
    from app.services.world_simulation.contracts import validate_decision
    from app.services.world_simulation.kernel import resolve_round

    decision = _decision(actor_case.observation)
    decision['stateUpdates'] = {
        'beliefs': ['Supply may tighten.', {'text': 'Capacity remains uncertain.'}],
        'plans': ['Review next-period deliveries.', {'text': 'Reassess purchase terms.'}],
        'priorityChanges': [],
    }
    case = boundary(content=json.dumps(decision))
    response = case.policy.decide(actor_case.observation)
    assert len(case.sent) == 1
    prompt = json.loads(case.sent[0].content)['messages'][0]['content']
    assert 'beliefs and plans may contain strings or objects' in prompt
    assert 'normalizes each string to {"text": "..."}' in prompt
    assert 'attaches observation/decision provenance' in prompt
    assert 'priorityChanges MUST contain objects with ruleId, priorityId and value' in prompt
    assert 'trigger matches a record visible in this observation' in prompt
    assert 'omit priorityChanges or use an empty array' in prompt
    assert response.decision == decision
    assert response.usage == {'tokens': 140, 'costUsd': '0.000560000000'}
    normalized = validate_decision(actor_case.spec, response.decision, 'buyer', actor_case.observation,
                                   phase='proposal')
    assert normalized['stateUpdates']['beliefs'][0] == {'text': 'Supply may tighten.'}
    result = resolve_round(actor_case.spec, actor_case.snapshot, [normalized], 1)
    private = result['snapshot']['actorStates']['buyer']
    for field in ('beliefs', 'plans'):
        assert [item['text'] for item in private[field]] == [
            item if isinstance(item, str) else item['text'] for item in decision['stateUpdates'][field]]
        for item in private[field]:
            assert item['observationId'] == actor_case.observation['observationId']
            assert item['decisionId'] == normalized['decisionId']
            assert item['basis'] == {'kind': 'simulation_event',
                                     'refs': [item['observationId'], item['decisionId']]}


def test_actor_feedback_none_preserves_exact_wire_body(actor_case, boundary):
    from app.services.world_simulation.contracts import canonical_json

    case = boundary()
    assert case.policy.supports_feedback is True
    quote = case.policy.reservation(actor_case.observation)
    assert case.policy.reservation(actor_case.observation, feedback=None) == quote
    assert case.sent == []
    case.policy.decide(actor_case.observation)
    case.policy.decide(actor_case.observation, feedback=None)
    assert len(case.sent) == 2 and case.sent[0].content == case.sent[1].content
    payload = json.loads(case.sent[0].content)
    assert payload['messages'][1]['content'] == canonical_json(actor_case.observation)
    assert 'Previous decision validation feedback' not in payload['messages'][0]['content']


def test_actor_feedback_is_quoted_scoped_and_fully_reserved(actor_case, boundary):
    from app.services.world_simulation.contracts import canonical_json

    feedback = {'code': 'invalid_decision', 'message': 'Use "intents".\n检查格式 🌊'}
    original = deepcopy(feedback)
    base, repair = boundary(), boundary()
    old_quote = base.policy.reservation(actor_case.observation)
    repair_quote = repair.policy.reservation(actor_case.observation, feedback=feedback)
    assert base.sent == repair.sent == []
    base.policy.decide(actor_case.observation)
    repair.policy.decide(actor_case.observation, feedback=feedback)
    first = json.loads(base.sent[0].content)
    second = json.loads(repair.sent[0].content)
    assert len(base.sent) == len(repair.sent) == 1
    assert set(first) == set(second)
    assert first['messages'][1] == second['messages'][1]
    assert json.loads(second['messages'][1]['content'])['observationId'] == actor_case.observation['observationId']
    assert second['messages'][0]['content'].startswith(first['messages'][0]['content'])
    assert canonical_json(feedback) in second['messages'][0]['content']
    assert 'feedback does not grant new facts or actions' in second['messages'][0]['content']
    assert feedback == original
    encode = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    extra_bytes = len(encode(second['messages'])) - len(encode(first['messages']))
    assert repair_quote['tokens'] - old_quote['tokens'] == extra_bytes > 0
    assert Decimal(repair_quote['costUsd']) - Decimal(old_quote['costUsd']) == Decimal(extra_bytes) * 2 / 1000000


@pytest.mark.parametrize('bound', ['input', 'context'])
def test_feedback_overflow_refuses_quote_and_dispatch(actor_case, boundary, bound):
    from app.services.world_simulation.contracts import WorldError

    probe = boundary()
    quote = probe.policy.reservation(actor_case.observation)
    spec = deepcopy(actor_case.spec)
    if bound == 'input':
        spec['policy']['maxInputTokens'] = quote['tokens'] - spec['limits']['maxOutputTokens']
    else:
        spec['policy']['pricing']['contextWindowTokens'] = quote['tokens']
    case = boundary(spec=spec)
    assert case.policy.reservation(actor_case.observation) == quote
    feedback = {'code': 'invalid_decision', 'message': '界' * 400}
    for method in (case.policy.reservation, case.policy.decide):
        with pytest.raises(WorldError) as caught:
            method(actor_case.observation, feedback=feedback)
        assert caught.value.code == 'policy_context_limit'
    assert case.sent == []


@pytest.mark.parametrize('feedback', [
    {}, [], 'raw provider text', {'code': 'invalid_decision'},
    {'code': 'invalid_decision', 'message': 'literal', 'body': 'PRIVATE_PROVIDER_BODY'},
    {'code': 'invalid_decision', 'message': 'literal', 'apiKey': 'SECRET'},
    {'code': 'x' * 129, 'message': 'literal'}, {'code': 'bad code', 'message': 'literal'},
    {'code': True, 'message': 'literal'}, {'code': ['bad'], 'message': 'literal'},
    {'code': 'invalid_decision', 'message': 'x' * 401}, {'code': 'invalid_decision', 'message': 42},
])
def test_feedback_rejects_unbounded_or_extra_information_before_sdk(actor_case, boundary, feedback):
    from app.services.world_simulation.contracts import WorldError

    case = boundary()
    for method in (case.policy.reservation, case.policy.decide):
        with pytest.raises(WorldError):
            method(actor_case.observation, feedback=feedback)
    assert case.sent == []


@pytest.mark.parametrize('repair_succeeds', [True, False])
def test_real_sdk_controller_repair_uses_only_two_durable_attempts(
        actor_case, boundary, tmp_path, repair_succeeds):
    from app.services.world_simulation.contracts import WorldError, validate_spec
    from app.services.world_simulation.controller import run_round
    from app.services.world_simulation.store import WorldStore

    spec = deepcopy(actor_case.spec)
    actor = next(actor for actor in spec['actors'] if actor['actorId'] == 'buyer')
    actor.update(capabilities=['wait'], controlledAccounts=[])
    spec.update(actors=[actor], flows=[], scheduledEvents=[], periods=spec['periods'][:1],
                horizon=spec['periods'][0]['end'],
                initialState={'accounts': {}, 'metrics': {}, 'rules': {}, 'relations': {}},
                actionCatalog=[{'templateId': 'wait', 'kind': 'wait', 'actorIds': ['buyer'],
                                'description': 'Wait.', 'parameters': {}, 'inputs': {}, 'basis': actor['basis']}])
    spec = validate_spec(spec)

    def completion(request, number):
        if number == 1 or not repair_succeeds:
            return '{"PRIVATE_PROVIDER_BODY_NEVER_FEEDBACK":'
        observation = json.loads(json.loads(request.content)['messages'][1]['content'])
        return json.dumps(_decision(observation))

    case = boundary(spec=spec, content_factory=completion)
    path = tmp_path / 'repair.sqlite3'
    with WorldStore(path, spec) as store:
        fence = store.acquire_writer('repair-first')
        if repair_succeeds:
            assert run_round(store, case.policy, fence)['round'] == 1
        else:
            with pytest.raises(WorldError) as caught:
                run_round(store, case.policy, fence)
            assert caught.value.code == 'required_decision_failed'
            assert store.head()['round'] == 0
        assert len(case.sent) == 2
        first, second = [json.loads(request.content) for request in case.sent]
        assert first['messages'][1] == second['messages'][1]
        assert 'Previous decision validation feedback' not in first['messages'][0]['content']
        assert '"code":"policy_invalid_response"' in second['messages'][0]['content']
        assert 'PRIVATE_PROVIDER_BODY_NEVER_FEEDBACK' not in case.sent[1].content.decode()
        summary = store.budget_summary()
        assert [row['status'] for row in summary['attempts']] == ['failed', 'succeeded' if repair_succeeds else 'failed']
        assert summary['actual']['tokens'] == 280 and summary['unknown']['tokens'] == 0
        assert summary['attempts'][1]['reserved']['tokens'] > summary['attempts'][0]['reserved']['tokens']
        store.release_writer(fence)
    with WorldStore(path, spec) as store:
        if repair_succeeds:
            assert store.head()['round'] == 1
            with pytest.raises(WorldError) as caught:
                store.acquire_writer('repair-resume')
            assert caught.value.code == 'horizon_complete'
        else:
            fence = store.acquire_writer('repair-resume')
            with pytest.raises(WorldError):
                run_round(store, case.policy, fence)
            store.release_writer(fence)
        assert len(case.sent) == 2  # Neither completion nor exhausted failure restores allowance.
        assert store.budget_summary()['attempts'] == summary['attempts']


@pytest.mark.parametrize('legacy_ids', [
    {}, {'actorId': 'authority', 'observationId': 'foreign-observation'},
    {'actorId': None, 'observationId': 99}, {'actorId': 'buyer'},
])
def test_actor_identity_is_bound_to_serialized_rpc_not_model_echo(actor_case, boundary, legacy_ids):
    from app.services.world_simulation.contracts import validate_decision

    model_decision = {'intents': [], 'status': 'wait', 'rationale': 'Wait for visible changes.', **legacy_ids}
    case = boundary(content=json.dumps(model_decision))
    response = case.policy.decide(actor_case.observation)
    sent = json.loads(case.sent[0].content)['messages']
    request_observation = json.loads(sent[1]['content'])
    assert 'Fields: intents (an array); optional stateUpdates, rationale, status.' in sent[0]['content']
    assert 'Do not include top-level actorId or observationId' in sent[0]['content']
    assert response.decision == {**model_decision, 'actorId': request_observation['actorId'],
                                 'observationId': request_observation['observationId']}
    assert response.usage == {'tokens': 140, 'costUsd': '0.000560000000'}
    validated = validate_decision(actor_case.spec, response.decision, 'buyer', actor_case.observation,
                                  phase='proposal')
    assert validated['actorId'] == 'buyer' and len(case.sent) == 1


@pytest.mark.parametrize('extra', [{'worldPatch': {}}, {'round': 2}, {'decisionId': 'foreign-decision'}])
def test_identity_binding_preserves_unknown_fields_for_validator_rejection(actor_case, boundary, extra):
    from app.services.world_simulation.contracts import WorldError, validate_decision

    case = boundary(content=json.dumps({'intents': [], **extra}))
    response = case.policy.decide(actor_case.observation)
    for key, value in extra.items():
        assert response.decision[key] == value
    with pytest.raises(WorldError) as caught:
        validate_decision(actor_case.spec, response.decision, 'buyer', actor_case.observation, phase='proposal')
    assert caught.value.code == 'invalid_decision' and len(case.sent) == 1


def test_identity_binding_does_not_repair_foreign_nested_provenance(actor_case, boundary):
    from app.services.world_simulation.contracts import WorldError, validate_decision

    updates = {'beliefs': [{'text': 'A belief.', 'observationId': 'foreign-observation'}]}
    case = boundary(content=json.dumps({'actorId': 'foreign-actor', 'observationId': 'foreign-observation',
                                       'intents': [], 'stateUpdates': updates}))
    response = case.policy.decide(actor_case.observation)
    assert response.decision['actorId'] == 'buyer'
    assert response.decision['observationId'] == actor_case.observation['observationId']
    assert response.decision['stateUpdates'] == updates
    with pytest.raises(WorldError) as caught:
        validate_decision(actor_case.spec, response.decision, 'buyer', actor_case.observation, phase='proposal')
    assert caught.value.code == 'invalid_actor_provenance' and len(case.sent) == 1


def test_identity_binding_cannot_authorize_foreign_action_capabilities(actor_case, boundary):
    from app.services.world_simulation.contracts import WorldError, validate_decision

    case = boundary(content=json.dumps({'actorId': 'producer', 'observationId': 'producer-view',
                                       'intents': [{'templateId': 'expand', 'operation': 'execute'}]}))
    response = case.policy.decide(actor_case.observation)
    assert response.decision['actorId'] == 'buyer'
    assert response.decision['intents'][0]['templateId'] == 'expand'
    with pytest.raises(WorldError) as caught:
        validate_decision(actor_case.spec, response.decision, 'buyer', actor_case.observation, phase='proposal')
    assert caught.value.code == 'invalid_intent' and len(case.sent) == 1


def test_identity_binding_survives_caller_mutation_during_http(actor_case, boundary):
    original = deepcopy(actor_case.observation)
    caller_observation = deepcopy(original)

    def mutate_caller(request, number):
        caller_observation.clear()
        caller_observation.update(actorId='authority', observationId='mutated-caller')
        return json.dumps({'actorId': 'authority', 'observationId': 'mutated-caller', 'intents': []})

    case = boundary(content_factory=mutate_caller)
    response = case.policy.decide(caller_observation)
    assert caller_observation['actorId'] == 'authority'
    assert json.loads(json.loads(case.sent[0].content)['messages'][1]['content']) == original
    assert response.decision == {'actorId': original['actorId'], 'observationId': original['observationId'],
                                 'intents': []}
    assert len(case.sent) == 1


def test_late_actor_call_remains_bound_to_old_observation_and_current_store_rejects(
        actor_case, boundary, tmp_path):
    from app.services.world_simulation.contracts import WorldError, validate_decision
    from app.services.world_simulation.controller import run_round
    from app.services.world_simulation.examples import ExamplePolicy
    from app.services.world_simulation.observations import build_observation
    from app.services.world_simulation.store import WorldStore

    old = deepcopy(actor_case.observation)
    with WorldStore(tmp_path / 'late-response.sqlite3', actor_case.spec) as store:
        fence = store.acquire_writer('late-response')
        assert run_round(store, ExamplePolicy('investment'), fence)['round'] == 1
        current = build_observation(actor_case.spec, store.head(), 'buyer', 2)
        assert old['observationId'] != current['observationId']
        case = boundary(content=json.dumps({'actorId': 'buyer', 'observationId': current['observationId'],
                                           'intents': []}))
        late = case.policy.decide(old)
        assert late.decision['observationId'] == old['observationId']
        normalized = validate_decision(actor_case.spec, late.decision, 'buyer', old, phase='proposal')
        store.freeze_phase(2, 'proposal', ['buyer'], fence)
        slot = '2:proposal:buyer'
        store.save_observation(slot, current, fence)
        with pytest.raises(WorldError) as caught:
            store.save_decision(slot, normalized, fence)
        assert caught.value.code == 'decision_identity_mismatch'
        assert store.decision(slot) is None and store.observation(slot) == current
        assert store.head()['round'] == 1 and len(case.sent) == 1
        store.release_writer(fence)


def test_concurrent_actor_calls_keep_independent_execution_bindings(actor_case, boundary):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from app.services.world_simulation.contracts import validate_decision
    from app.services.world_simulation.observations import build_observation

    observations = [build_observation(actor_case.spec, actor_case.snapshot, actor, 1)
                    for actor in ('buyer', 'producer')]
    both_dispatched = threading.Barrier(2)

    def completion(request, number):
        observed = json.loads(json.loads(request.content)['messages'][1]['content'])
        both_dispatched.wait(timeout=5)
        return json.dumps({'actorId': 'wrong-legacy-actor', 'observationId': 'wrong-legacy-view',
                           'intents': [], 'rationale': observed['actorId']})

    case = boundary(content_factory=completion)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(case.policy.decide, observations))
    assert len(case.sent) == 2
    for response, observation in zip(responses, observations):
        assert response.decision['actorId'] == response.decision['rationale'] == observation['actorId']
        assert response.decision['observationId'] == observation['observationId']
        validate_decision(actor_case.spec, response.decision, observation['actorId'], observation, phase='proposal')
