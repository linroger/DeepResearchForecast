"""Provider facts in the strict transport: modeler envelope, thinking pin, 1301 and truncation.

The OpenAI SDK is real; HTTP is an httpx.MockTransport that records each dispatch.
"""
from copy import deepcopy
import json

import pytest

import test_world_default_admission as admission_fixtures
import test_world_policy as fixtures

actor_case = fixtures.actor_case
boundary = fixtures.boundary
modeler_case = fixtures.modeler_case
offline_http = admission_fixtures.offline_http
pytestmark = pytest.mark.guarded_runner

MODELER = {"maxInputTokens": 300000, "maxOutputTokens": 1024, "timeoutSeconds": 600}
ZHIPU_1301 = json.dumps({"error": {"code": "1301", "message": "PRIVATE_PROVIDER_TEXT 系统检测到输入或生成内容可能包含不安全或敏感内容"}}).encode()


def _pinned(spec, **policy):
    spec = deepcopy(spec)
    spec["policy"].update(policy)
    return spec


def test_modeler_uses_its_own_pinned_envelope_and_actors_keep_theirs(actor_case, modeler_case, boundary):
    from app.services.world_simulation.policy import StrictHTTPModeler

    spec = _pinned(modeler_case.spec, modeler=dict(MODELER))
    case = boundary(spec=spec, policy_type=StrictHTTPModeler, content=json.dumps(modeler_case.proposal))
    assert (case.policy.max_input, case.policy.max_output, case.policy.timeout) == (300000, 1024, 600)
    exact = json.dumps(modeler_case.messages, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert case.policy.reservation(modeler_case.messages)["tokens"] == len(exact) + 256 + 1024
    case.policy.decide(modeler_case.messages)
    assert json.loads(case.sent[0].content)["max_completion_tokens"] == 1024
    assert case.policy._client.timeout == 600 and case.policy._client.max_retries == 0
    # The same policy object drives actors with the shared envelope.
    actor = boundary(spec=_pinned(actor_case.spec, modeler=dict(MODELER)))
    assert (actor.policy.max_input, actor.policy.max_output, actor.policy.timeout) == (30000, 512, 17)
    actor.policy.decide(actor_case.observation)
    assert json.loads(actor.sent[0].content)["max_completion_tokens"] == 512


def test_modeler_input_bound_comes_from_its_pin(modeler_case, boundary):
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.policy import StrictHTTPModeler

    exact = len(json.dumps(modeler_case.messages, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    shared_too_small = _pinned(modeler_case.spec, maxInputTokens=exact // 2, modeler=dict(MODELER))
    case = boundary(spec=shared_too_small, policy_type=StrictHTTPModeler, content=json.dumps(modeler_case.proposal))
    case.policy.decide(modeler_case.messages)
    assert len(case.sent) == 1
    pin_too_small = _pinned(modeler_case.spec, modeler={**MODELER, "maxInputTokens": exact // 2})
    denied = boundary(spec=pin_too_small, policy_type=StrictHTTPModeler)
    with pytest.raises(WorldError) as error:
        denied.policy.decide(modeler_case.messages)
    assert error.value.code == "policy_context_limit" and denied.sent == []


@pytest.mark.parametrize("modeler", [{**MODELER, "timeoutSeconds": 1801}, {**MODELER, "maxOutputTokens": 4096},
                                     {"maxInputTokens": 300000, "maxOutputTokens": 1024}])
def test_modeler_pin_must_fit_its_closed_shape_and_provider_bounds(modeler_case, boundary, modeler):
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.policy import StrictHTTPModeler

    with pytest.raises(WorldError) as error:
        boundary(spec=_pinned(modeler_case.spec, modeler=modeler), policy_type=StrictHTTPModeler)
    assert error.value.code == "invalid_policy_metadata"


def test_thinking_pin_is_sent_as_extra_body_on_actor_and_modeler_requests(actor_case, modeler_case, boundary):
    from app.services.world_simulation.policy import StrictHTTPModeler

    plain = boundary()
    plain.policy.decide(actor_case.observation)
    assert "thinking" not in json.loads(plain.sent[0].content)
    actor = boundary(spec=_pinned(actor_case.spec, thinking="disabled"))
    actor.policy.decide(actor_case.observation)
    assert json.loads(actor.sent[0].content)["thinking"] == {"type": "disabled"}
    modeler = boundary(spec=_pinned(modeler_case.spec, thinking="disabled"), policy_type=StrictHTTPModeler,
                       content=json.dumps(modeler_case.proposal))
    modeler.policy.decide(modeler_case.messages)
    body = json.loads(modeler.sent[0].content)
    assert body["thinking"] == {"type": "disabled"} and "reasoning_effort" not in body


@pytest.mark.parametrize("policy", [{"thinking": "enabled"}, {"thinking": False},
                                    {"thinking": "disabled", "reasoningEffort": "high"}])
def test_thinking_pin_is_closed(actor_case, boundary, policy):
    from app.services.world_simulation.contracts import WorldError

    with pytest.raises(WorldError) as error:
        boundary(spec=_pinned(actor_case.spec, **policy))
    assert error.value.code == "invalid_policy_metadata"


@pytest.mark.parametrize("raw_body", [
    ZHIPU_1301,
    json.dumps({"error": {"code": 1301, "message": "PRIVATE_PROVIDER_TEXT"}}).encode(),
    json.dumps({"error": {"code": "content_filter", "message": "PRIVATE_PROVIDER_TEXT"}}).encode(),
])
def test_provider_content_filter_is_typed_with_unknown_exposure(actor_case, boundary, raw_body):
    from app.services.world_simulation.policy import PolicyFailure, is_candidate_output_failure

    case = boundary(status=400, raw_body=raw_body)
    with pytest.raises(PolicyFailure) as caught:
        case.policy.decide(actor_case.observation)
    error = caught.value
    assert error.code == "provider_content_filtered" and error.usage is None
    assert "PRIVATE_PROVIDER_TEXT" not in str(error) and len(case.sent) == 1
    assert not is_candidate_output_failure(error)


def test_other_bad_requests_stay_untyped_transport_failures(actor_case, boundary):
    from app.services.world_simulation.policy import PolicyFailure

    case = boundary(status=400, raw_body=json.dumps({"error": {"code": "1214", "message": "bad parameter"}}).encode())
    with pytest.raises(PolicyFailure) as caught:
        case.policy.decide(actor_case.observation)
    assert caught.value.code == "policy_transport_failed"
    assert str(caught.value) == "Actor HTTP dispatch failed with status 400; exposure is unknown"


@pytest.mark.parametrize("finish,code", [("sensitive", "provider_content_filtered"),
                                         ("content_filter", "provider_content_filtered"),
                                         ("length", "policy_output_truncated")])
def test_filtered_or_truncated_output_keeps_usage_and_is_not_repairable(actor_case, boundary, finish, code):
    from app.services.world_simulation.policy import NON_RETRYABLE_POLICY_CODES, PolicyFailure, is_candidate_output_failure
    from app.services.world_simulation.review import CANDIDATE_OUTPUT_ERRORS

    case = boundary(finish=finish)
    with pytest.raises(PolicyFailure) as caught:
        case.policy.decide(actor_case.observation)
    error = caught.value
    assert error.code == code and error.usage == {"tokens": 140, "costUsd": "0.000560000000"}
    assert not is_candidate_output_failure(error) and code not in CANDIDATE_OUTPUT_ERRORS
    assert code in NON_RETRYABLE_POLICY_CODES and len(case.sent) == 1


@pytest.mark.parametrize("finish,code", [("sensitive", "provider_content_filtered"),
                                         ("length", "policy_output_truncated")])
def test_typed_stop_wins_even_without_trustworthy_metering(actor_case, boundary, finish, code):
    from app.services.world_simulation.policy import PolicyFailure

    case = boundary(finish=finish, usage={"prompt_tokens": 100})
    with pytest.raises(PolicyFailure) as caught:
        case.policy.decide(actor_case.observation)
    assert caught.value.code == code and caught.value.usage is None and len(case.sent) == 1


@pytest.mark.parametrize("outcome", ["filtered_request", "truncated"])
def test_plain_controller_never_resends_a_filtered_or_truncated_observation(actor_case, boundary, tmp_path, outcome):
    from app.services.world_simulation.contracts import WorldError, validate_spec
    from app.services.world_simulation.controller import run_round
    from app.services.world_simulation.store import WorldStore

    spec = deepcopy(actor_case.spec)
    actor = next(actor for actor in spec["actors"] if actor["actorId"] == "buyer")
    actor.update(capabilities=["wait"], controlledAccounts=[])
    spec.update(actors=[actor], flows=[], scheduledEvents=[], periods=spec["periods"][:1],
                horizon=spec["periods"][0]["end"],
                initialState={"accounts": {}, "metrics": {}, "rules": {}, "relations": {}},
                actionCatalog=[{"templateId": "wait", "kind": "wait", "actorIds": ["buyer"],
                                "description": "Wait.", "parameters": {}, "inputs": {}, "basis": actor["basis"]}])
    spec = validate_spec(spec)
    case = (boundary(spec=spec, status=400, raw_body=ZHIPU_1301) if outcome == "filtered_request"
            else boundary(spec=spec, finish="length"))
    with WorldStore(tmp_path / "plain.sqlite3", spec) as store:
        fence = store.acquire_writer("plain")
        with pytest.raises(WorldError) as caught:
            run_round(store, case.policy, fence)
        assert caught.value.code == "required_decision_failed"
        expected = "provider_content_filtered" if outcome == "filtered_request" else "policy_output_truncated"
        assert caught.value.details["lastErrorCode"] == expected
        assert len(case.sent) == 1 and store.head()["round"] == 0
        assert [row["status"] for row in store.budget_summary()["attempts"]] == [
            "unknown" if outcome == "filtered_request" else "failed"]
        store.release_writer(fence)


def test_fresh_admission_checks_the_modeler_envelope_against_the_budget(offline_http):
    from app.services.world_simulation.contracts import WorldError

    value = admission_fixtures.profile()
    value["policy"]["thinking"] = "disabled"
    value["policy"]["modeler"] = {"maxInputTokens": 30000, "maxOutputTokens": 2048, "timeoutSeconds": 900}
    value["limits"]["maxTokens"] = 32047  # one token short of the modeler's 30,000 + 2,048 envelope
    with pytest.raises(WorldError) as error:
        admission_fixtures.resolve(mode="full", simulation_engine="world-v1", world_policy_spec=value)
    assert error.value.code == "invalid_modeling_budget"
    value["limits"]["maxTokens"] = 32048
    result = admission_fixtures.resolve(mode="full", simulation_engine="world-v1", world_policy_spec=value)
    assert result["world_policy_spec"]["policy"]["modeler"] == value["policy"]["modeler"]
    assert result["world_policy_spec"]["policy"]["thinking"] == "disabled"
    assert result["simulation_admission_v1"]["status"] == "ready" and offline_http.sent == []


@pytest.mark.parametrize("change", ["actor_output_over_provider", "actor_envelope_over_budget"])
def test_fresh_admission_still_checks_the_actor_envelope_when_the_modeler_is_pinned(offline_http, change):
    from app.services.world_simulation.contracts import WorldError

    value = admission_fixtures.profile()
    value["policy"]["modeler"] = {"maxInputTokens": 1000, "maxOutputTokens": 100, "timeoutSeconds": 900}
    if change == "actor_output_over_provider":
        value["limits"]["maxOutputTokens"] = 4096  # pricing.maxOutputTokens is 2048
        expected = "invalid_policy_metadata"
    else:
        value["limits"]["maxTokens"] = 20000  # covers the modeler (1,100) but not one actor request (30,512)
        expected = "invalid_modeling_budget"
    with pytest.raises(WorldError) as error:
        admission_fixtures.resolve(mode="full", simulation_engine="world-v1", world_policy_spec=value)
    assert error.value.code == expected and offline_http.sent == []


@pytest.mark.parametrize("mode", ["v3", "v4"])
@pytest.mark.parametrize("code", ["policy_output_truncated", "provider_content_filtered"])
def test_review_mode_candidate_cut_off_gets_no_repair_request(tmp_path, mode, code):
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.controller import PolicyResponse, run_round
    from app.services.world_simulation.policy import PolicyFailure
    from app.services.world_simulation.review import MODE_V3, MODE_V4, normalize_v4_assessment_output
    from app.services.world_simulation.store import WorldStore
    from test_world_candidate_repair_controller import RepairingPolicy, repair_spec

    review = MODE_V3 if mode == "v3" else MODE_V4
    spec = repair_spec()
    spec["policy"]["decisionReview"] = review

    class Stopped(RepairingPolicy):
        decision_review = review

        def decide(self, obs, *, review=None):
            if obs["actorId"] == "buyer":
                self.calls.append(("buyer", obs["phase"], review is not None))
                raise PolicyFailure(code, "synthetic provider stop", usage={"tokens": 0, "costUsd": "0"})
            response = super().decide(obs, review=review)
            if mode == "v4" and response.assessment is not None:
                # The shared fixture scripts v3 checks; v4 validates their packed form.
                response = PolicyResponse(response.decision, response.usage,
                                          assessment=normalize_v4_assessment_output(response.assessment))
            return response

    policy = Stopped()
    with WorldStore(tmp_path / "stopped.sqlite3", spec) as store:
        fence = store.acquire_writer("stopped")
        with pytest.raises(WorldError) as caught:
            run_round(store, policy, fence)
        assert caught.value.code == "required_decision_failed"
        assert caught.value.details["lastErrorCode"] == code
        assert [call for call in policy.calls if call[0] == "buyer"] == [("buyer", "proposal", False)]
        store.release_writer(fence)
