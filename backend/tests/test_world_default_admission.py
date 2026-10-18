"""Fresh admission scenarios for the coordinator's guarded offline runner.

The SDK and strict adapter are real; HTTP is replaced with MockTransport.
All prices, guarantees and credentials below are synthetic fixture assertions.
"""
from copy import deepcopy
import json
import os
from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.guarded_runner


def profile():
    from app.services.world_simulation.review import CANDIDATE_REPAIR_MODE, MODE_V4

    return {
        "policy": {
            "provider": "openai", "model": "fixture-model-v1",
            "baseUrl": "https://fixture.invalid/v1", "timeoutSeconds": 17,
            "maxInputTokens": 30000, "decisionReview": MODE_V4, "responseFormat": "json_object",
            "candidateRepair": CANDIDATE_REPAIR_MODE,
            "pricing": {
                "provider": "openai", "model": "fixture-model-v1",
                "baseUrl": "https://fixture.invalid/v1",
                "inputUsdPerMillion": "2", "outputUsdPerMillion": "9",
                "contextWindowTokens": 32768, "maxOutputTokens": 2048,
                "inputOverheadTokens": 256, "outputTokenParameter": "max_completion_tokens",
                "maxOutputIncludesReasoning": True,
                "source": {"reference": "fixture://synthetic-price-and-bounds",
                           "asOf": "2026-10-17T00:00:00Z"},
            },
        },
        "limits": {"maxTokens": 250000, "maxCostUsd": "5.00", "maxOutputTokens": 512},
        "forecastEffect": "diagnostic_only",
    }


def raw_spec():
    return {
        **profile(), "actors": [{"actorId": "fixture_actor", "name": "Fixture actor"}],
        "periods": [{"start": "2026-10-17T00:00:00Z", "end": "2027-10-17T00:00:00Z"}],
        "initialState": {"accounts": {}, "metrics": {}, "rules": {}, "relations": {}},
        "actionCatalog": [], "assumptions": [], "scheduledEvents": [], "flows": [],
    }


def resolve(**kwargs):
    from app.services.world_simulation.admission import resolve_fresh_simulation_request

    return resolve_fresh_simulation_request(**kwargs)


def write_profile(tmp_path, value=None):
    # The resolver refuses symlinks in every component, including macOS /var.
    path = tmp_path.resolve() / "operator-profile.json"
    path.write_text(json.dumps(profile() if value is None else value), encoding="utf-8")
    return path


@pytest.fixture
def offline_http(monkeypatch):
    """Exercise real configuration/auth checks and SDK construction, never I/O."""
    import httpx
    from app.config import Config

    monkeypatch.setattr(Config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(Config, "LLM_BASE_URL", "https://fixture.invalid/v1")
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "fixture-model-v1")
    monkeypatch.setattr(Config, "LLM_API_KEY", "fixture-only-secret-never-real")
    clients, sent = [], []
    original_client = httpx.Client

    def dispatch(request):
        sent.append(request)
        raise AssertionError("Admission must never dispatch an HTTP request")

    class OfflineClient(original_client):
        def __init__(self, *args, **kwargs):
            transport = kwargs.pop("transport", None)
            if transport is not None:
                transport.close()
            kwargs["transport"] = httpx.MockTransport(dispatch)
            super().__init__(*args, **kwargs)
            clients.append(self)

    monkeypatch.setattr(httpx, "Client", OfflineClient)
    yield SimpleNamespace(clients=clients, sent=sent, config=Config)
    try:
        assert sent == [], "Admission issued HTTP requests"
    finally:
        for client in clients:
            client.close()


@pytest.fixture
def no_transport(monkeypatch):
    from app.services.world_simulation import policy

    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("This request must not construct a policy transport")

    monkeypatch.setattr(policy, "StrictHTTPModeler", forbidden)
    yield calls
    assert calls == []


def assert_error(code, **kwargs):
    from app.services.world_simulation.contracts import WorldError

    with pytest.raises(WorldError) as caught:
        resolve(**kwargs)
    assert caught.value.code == code
    return caught.value


def test_omission_stays_legacy_and_explicit_legacy_overrides_future_default(no_transport):
    from app.services.world_simulation.admission import UNSET

    for kwargs in ({}, {"simulation_engine": UNSET},
                   {"default_engine": "world-v1", "simulation_engine": "oasis-legacy"}):
        result = resolve(mode="full", profile_path="/unused/profile", max_rounds=3, **kwargs)
        assert result == {
            "simulation_engine": "oasis-legacy", "world_spec": None, "world_policy_spec": None,
            "simulation_admission_v1": {"version": "simulation-admission/v1", "source": "legacy",
                                        "status": "ready"},
        }


@pytest.mark.parametrize("engine", [None, "", "WORLD-V1", "future-world", 0, True, [], {}])
def test_explicit_invalid_engine_never_uses_default(engine, no_transport):
    assert_error("unsupported_engine", mode="full", simulation_engine=engine,
                 default_engine="world-v1", world_policy_spec=profile())


@pytest.mark.parametrize("mode", [None, "", "resume", [], False])
def test_unknown_mode_is_rejected(mode, no_transport):
    assert_error("invalid_world_request", mode=mode)


@pytest.mark.parametrize("field", ["world_spec", "world_policy_spec"])
@pytest.mark.parametrize("value", [{}, [], False, "not-an-object"])
def test_legacy_rejects_every_nonnull_world_input(field, value, no_transport):
    assert_error("invalid_world_request", mode="full", **{field: value})


def test_full_world_requires_policy_before_construction(no_transport):
    assert_error("world_configuration_required", mode="full", simulation_engine="world-v1")
    assert_error("world_configuration_required", mode="full", default_engine="world-v1")


def test_configured_profile_constructs_and_closes_real_sdk_without_dispatch(tmp_path, offline_http):
    path = write_profile(tmp_path)
    result = resolve(mode="full", default_engine="world-v1", profile_path=path)
    assert result["simulation_engine"] == "world-v1"
    assert result["world_spec"] is None
    assert result["world_policy_spec"]["limits"]["maxCostUsd"] == "5"
    assert result["world_policy_spec"]["limits"]["maxAttemptsPerSlot"] == 2
    record = result["simulation_admission_v1"]
    assert record["source"] == "operator_profile" and record["status"] == "ready"
    assert len(record["profile_sha256"]) == 64
    assert str(path) not in json.dumps(result)
    assert "fixture-only-secret-never-real" not in json.dumps(result)
    assert offline_http.clients and all(client.is_closed for client in offline_http.clients)
    assert offline_http.sent == []


def test_explicit_policy_wins_without_reading_profile_and_is_detached(tmp_path, offline_http):
    explicit = profile()
    original = deepcopy(explicit)
    result = resolve(mode="full", simulation_engine="world-v1", world_policy_spec=explicit,
                     profile_path=tmp_path / "missing-profile")
    assert explicit == original
    assert result["simulation_admission_v1"]["source"] == "request_policy"
    before = result["simulation_admission_v1"]["profile_sha256"]
    explicit["policy"]["pricing"]["source"]["reference"] = "changed"
    result["world_policy_spec"]["limits"]["maxActors"] = 1
    assert "maxActors" not in explicit["limits"]
    assert result["world_policy_spec"]["policy"]["pricing"]["source"] == original["policy"]["pricing"]["source"]
    again = resolve(mode="full", simulation_engine="world-v1", world_policy_spec=original)
    assert again["world_policy_spec"]["limits"]["maxActors"] == 20
    assert again["simulation_admission_v1"]["profile_sha256"] == before


def test_invalid_explicit_policy_never_falls_back_to_valid_file(tmp_path, no_transport):
    assert_error("invalid_world_request", mode="full", simulation_engine="world-v1",
                 world_policy_spec={}, profile_path=write_profile(tmp_path))


def test_profile_snapshot_and_digest_do_not_follow_file_edits(tmp_path, offline_http):
    path = write_profile(tmp_path)
    original = resolve(mode="full", simulation_engine="world-v1", profile_path=path)
    changed = profile()
    changed["limits"]["maxCostUsd"] = "6"
    write_profile(tmp_path, changed)
    new = resolve(mode="full", simulation_engine="world-v1", profile_path=path)
    assert original["world_policy_spec"]["limits"]["maxCostUsd"] == "5"
    assert new["world_policy_spec"]["limits"]["maxCostUsd"] == "6"
    assert original["simulation_admission_v1"]["profile_sha256"] != new["simulation_admission_v1"]["profile_sha256"]


def test_raw_uses_own_profile_leaves_periods_untouched_and_detaches(tmp_path, offline_http):
    raw = raw_spec()
    before = deepcopy(raw)
    result = resolve(mode="full", simulation_engine="world-v1", world_spec=raw,
                     profile_path=tmp_path / "missing-profile")
    assert raw == before and result["world_policy_spec"] is None
    assert result["world_spec"]["periods"] == before["periods"]
    assert result["simulation_admission_v1"]["source"] == "raw_spec"
    result["world_spec"]["actors"][0]["name"] = "changed"
    raw["periods"][0]["end"] = "2099-01-01T00:00:00Z"
    assert raw["actors"] == before["actors"]
    assert result["world_spec"]["periods"] == before["periods"]


@pytest.mark.parametrize("mode", ["full", "research_only"])
def test_raw_plus_policy_is_ambiguous(mode, no_transport):
    assert_error("invalid_world_request", mode=mode, simulation_engine="world-v1",
                 world_spec=raw_spec(), world_policy_spec=profile())


@pytest.mark.parametrize("raw", [False, True])
@pytest.mark.parametrize("cap", [1, 1000, 0, -1, False, "3", [], {}])
def test_full_world_rejects_any_round_override(cap, raw, no_transport):
    inputs = {"world_spec": raw_spec()} if raw else {"world_policy_spec": profile()}
    assert_error("world_calendar_override", mode="full", simulation_engine="world-v1",
                 max_rounds=cap, **inputs)


@pytest.mark.parametrize("explicit", [False, True])
def test_research_only_defers_without_profile_or_auth(tmp_path, no_transport, explicit):
    kwargs = {"simulation_engine": "world-v1"} if explicit else {"default_engine": "world-v1"}
    result = resolve(mode="research_only", profile_path=tmp_path / "missing-profile", **kwargs)
    assert result["simulation_engine"] == "world-v1"
    assert result["world_spec"] is result["world_policy_spec"] is None
    assert result["simulation_admission_v1"] == {
        "version": "simulation-admission/v1", "source": "deferred", "status": "deferred",
    }


@pytest.mark.parametrize("field", ["world_spec", "world_policy_spec"])
def test_research_only_partial_explicit_metadata_is_checked_and_detached(field, no_transport):
    from app.services.world_simulation.review import MODE_V4

    explicit = {"policy": {"decisionReview": MODE_V4}}
    result = resolve(mode="research_only", simulation_engine="world-v1", **{field: explicit})
    assert result["simulation_admission_v1"]["status"] == "deferred"
    assert result[field] == explicit and "limits" not in result[field]
    explicit["policy"]["decisionReview"] = "changed"
    assert result[field]["policy"]["decisionReview"] == MODE_V4


@pytest.mark.parametrize("field", ["world_spec", "world_policy_spec"])
@pytest.mark.parametrize("value", [[], "text", True, {"api_key": "private-marker"},
                                    {"policy": {"api_key": "private-marker"}},
                                    {"policy": {"pricing": {"headers": {"Authorization": "private-marker"}}}}])
def test_research_only_rejects_bad_explicit_shapes_and_closed_metadata(field, value, no_transport):
    from app.services.world_simulation.contracts import WorldError

    with pytest.raises(WorldError) as caught:
        resolve(mode="research_only", simulation_engine="world-v1", **{field: value})
    assert "private-marker" not in str(caught.value)


@pytest.mark.parametrize("field", ["policy", "limits"])
@pytest.mark.parametrize("raw", [False, True])
def test_full_world_requires_own_complete_policy(field, raw, no_transport):
    value = raw_spec() if raw else profile()
    del value[field]
    assert_error("invalid_world_request", mode="full", simulation_engine="world-v1",
                 **{"world_spec" if raw else "world_policy_spec": value})


@pytest.mark.parametrize("field", ["maxTokens", "maxCostUsd", "maxOutputTokens"])
def test_paid_limits_must_be_explicit(field, no_transport):
    value = profile()
    del value["limits"][field]
    assert_error("invalid_modeling_budget", mode="full", simulation_engine="world-v1", world_policy_spec=value)


@pytest.mark.parametrize("field,value", [
    ("maxTokens", 0), ("maxTokens", True), ("maxTokens", "10"), ("maxTokens", 10000001),
    ("maxOutputTokens", -1), ("maxActors", 101), ("maxIntentsPerPhase", 11),
    ("maxAttemptsPerSlot", 1), ("maxAttemptsPerSlot", 3), ("maxConcurrentCalls", False),
    ("unknownBudget", 100), ("maxCostUsd", 5), ("maxCostUsd", "0"), ("maxCostUsd", "-1"),
    ("maxCostUsd", "NaN"), ("maxCostUsd", "Infinity"), ("maxCostUsd", "0.0000000000001"),
])
def test_invalid_limits_fail_before_transport(field, value, no_transport):
    from app.services.world_simulation.contracts import WorldError

    candidate = profile()
    candidate["limits"][field] = value
    with pytest.raises(WorldError):
        resolve(mode="full", simulation_engine="world-v1", world_policy_spec=candidate)


@pytest.mark.parametrize("review", ["actor-consistency-v1", "actor-consistency-v2", "actor-consistency-v3", "unknown", [], True])
def test_fresh_world_rejects_review_pins_other_than_v4(review, no_transport):
    # No pin at all is now the fresh default (test_world_review_admission.py).
    value = profile()
    value["policy"]["decisionReview"] = review
    assert_error("invalid_policy_metadata", mode="full", simulation_engine="world-v1", world_policy_spec=value)


@pytest.mark.parametrize("response_format", [None, "text", "json_schema", [], {}, True])
def test_fresh_world_requires_explicit_json_response_format(response_format, no_transport):
    value = profile()
    if response_format is None:
        del value["policy"]["responseFormat"]
    else:
        value["policy"]["responseFormat"] = response_format
    assert_error("invalid_policy_metadata", mode="full", simulation_engine="world-v1", world_policy_spec=value)


@pytest.mark.parametrize("present,repair", [
    (False, None), (True, None), (True, ""), (True, "unknown"),
    (True, "KNOWN-OUTPUT-ERROR-V1"), (True, True), (True, False), (True, []), (True, {}),
])
@pytest.mark.parametrize("source", ["request", "raw", "file"])
def test_fresh_world_requires_exact_candidate_repair_pin(present, repair, source, tmp_path, no_transport):
    value = raw_spec() if source == "raw" else profile()
    if present:
        value["policy"]["candidateRepair"] = repair
    else:
        del value["policy"]["candidateRepair"]
    before = deepcopy(value)
    kwargs = ({"profile_path": write_profile(tmp_path, value)} if source == "file" else
              {"world_spec" if source == "raw" else "world_policy_spec": value})
    assert_error("invalid_policy_metadata", mode="full", simulation_engine="world-v1", **kwargs)
    assert value == before


@pytest.mark.parametrize("source", ["request", "raw", "file"])
def test_fresh_repair_pin_is_preserved_and_hashed(source, tmp_path, offline_http):
    from app.services.world_simulation.contracts import digest
    from app.services.world_simulation.review import CANDIDATE_REPAIR_MODE, candidate_repair_enabled

    value = raw_spec() if source == "raw" else profile()
    before = deepcopy(value)
    kwargs = ({"profile_path": write_profile(tmp_path, value)} if source == "file" else
              {"world_spec" if source == "raw" else "world_policy_spec": value})
    result = resolve(mode="full", simulation_engine="world-v1", **kwargs)
    resolved = result["world_spec"] if source == "raw" else result["world_policy_spec"]
    assert resolved["policy"]["candidateRepair"] == CANDIDATE_REPAIR_MODE
    assert candidate_repair_enabled(resolved) is True
    assert resolved["limits"]["maxAttemptsPerSlot"] == 2
    normalized = {key: resolved[key] for key in ("policy", "limits", "forecastEffect")}
    recorded_hash = result["simulation_admission_v1"]["profile_sha256"]
    assert recorded_hash == digest(normalized)
    without_repair = deepcopy(normalized)
    del without_repair["policy"]["candidateRepair"]
    assert digest(without_repair) != recorded_hash
    assert value == before and offline_http.sent == []
    assert offline_http.clients and all(client.is_closed for client in offline_http.clients)


@pytest.mark.parametrize("repair", [None, "unknown", True, {}])
def test_research_only_rejects_invalid_explicit_repair_pin(repair, no_transport):
    from app.services.world_simulation.review import MODE_V4

    value = {"policy": {"decisionReview": MODE_V4, "candidateRepair": repair}}
    assert_error("invalid_policy_metadata", mode="research_only", simulation_engine="world-v1",
                 world_policy_spec=value)


@pytest.mark.parametrize("saved_review", [
    None, "actor-consistency-v1", "actor-consistency-v2", "actor-consistency-v3",
])
def test_existing_review_reader_keeps_historical_modes(saved_review, no_transport):
    from app.services.world_simulation.review import candidate_repair_enabled, review_mode

    saved = {"policy": {}, "limits": {"maxAttemptsPerSlot": 2}}
    if saved_review is not None:
        saved["policy"]["decisionReview"] = saved_review
    before = deepcopy(saved)
    # Saved readers bypass fresh admission; this does not test pipeline routing.
    assert review_mode(saved) == saved_review
    assert candidate_repair_enabled(saved) is False
    assert saved == before


@pytest.mark.parametrize("snapshot,effect", [("diagnostic_only", "no_update"),
    ("no_update", "diagnostic_only"), ("legacy_prompt", "legacy_prompt"),
    ("validated_update", "validated_update"), ("diagnostic_only", None)])
def test_effect_must_be_safe_and_match_snapshot(snapshot, effect, no_transport):
    value = profile()
    value["forecastEffect"] = effect
    assert_error("unsupported_policy", mode="full", simulation_engine="world-v1",
                 forecast_effect=snapshot, world_policy_spec=value)


def test_no_update_is_preserved(offline_http):
    value = profile()
    value["forecastEffect"] = "no_update"
    result = resolve(mode="full", simulation_engine="world-v1", world_policy_spec=value,
                     forecast_effect="no_update")
    assert result["world_policy_spec"]["forecastEffect"] == "no_update"


@pytest.mark.parametrize("source", ["request", "raw", "file"])
@pytest.mark.parametrize("effect", ["diagnostic_only", "no_update"])
def test_omitted_effect_pins_snapshot_before_digest(source, effect, tmp_path, offline_http):
    from app.services.world_simulation.contracts import digest

    value = raw_spec() if source == "raw" else profile()
    del value["forecastEffect"]
    before = deepcopy(value)
    if source == "file":
        path = write_profile(tmp_path, value)
        file_before = path.read_bytes()
        kwargs = {"profile_path": path}
    else:
        kwargs = {"world_spec" if source == "raw" else "world_policy_spec": value}
    result = resolve(mode="full", simulation_engine="world-v1", forecast_effect=effect, **kwargs)
    resolved = result["world_spec"] if source == "raw" else result["world_policy_spec"]
    assert resolved["forecastEffect"] == effect
    assert value == before and "forecastEffect" not in value
    normalized = {key: resolved[key] for key in ("policy", "limits", "forecastEffect")}
    assert result["simulation_admission_v1"]["profile_sha256"] == digest(normalized)
    if source == "file":
        assert path.read_bytes() == file_before
    other_effect = "no_update" if effect == "diagnostic_only" else "diagnostic_only"
    other = resolve(mode="full", simulation_engine="world-v1", forecast_effect=other_effect, **kwargs)
    assert other["simulation_admission_v1"]["profile_sha256"] != result["simulation_admission_v1"]["profile_sha256"]


@pytest.mark.parametrize("source", ["request", "raw", "file"])
@pytest.mark.parametrize("explicit_effect", [None, "no_update", "legacy_prompt"])
def test_explicit_effect_is_never_overwritten(source, explicit_effect, tmp_path, no_transport):
    value = raw_spec() if source == "raw" else profile()
    value["forecastEffect"] = explicit_effect
    before = deepcopy(value)
    kwargs = ({"profile_path": write_profile(tmp_path, value)} if source == "file" else
              {"world_spec" if source == "raw" else "world_policy_spec": value})
    assert_error("unsupported_policy", mode="full", simulation_engine="world-v1",
                 forecast_effect="diagnostic_only", **kwargs)
    assert value == before


@pytest.mark.parametrize("field,limit", [("maxTokens", 30511), ("maxCostUsd", "0.064607999999")])
@pytest.mark.parametrize("source", ["request", "raw", "file"])
def test_declared_envelope_exceeds_budget_without_dispatch_and_closes_client(
    field, limit, source, tmp_path, offline_http,
):
    value = raw_spec() if source == "raw" else profile()
    value["limits"][field] = limit
    kwargs = ({"profile_path": write_profile(tmp_path, value)} if source == "file" else
              {"world_spec" if source == "raw" else "world_policy_spec": value})
    assert_error("invalid_modeling_budget", mode="full", simulation_engine="world-v1", **kwargs)
    assert offline_http.clients and all(client.is_closed for client in offline_http.clients)
    assert offline_http.sent == []


def test_exact_single_envelope_budget_is_accepted_without_trajectory_claim(offline_http):
    value = profile()
    # Synthetic envelope: 30,000 input + 512 output; USD 0.060000 + 0.004608.
    value["limits"].update(maxTokens=30512, maxCostUsd="0.064608")
    result = resolve(mode="full", simulation_engine="world-v1", world_policy_spec=value)
    assert result["world_policy_spec"]["limits"]["maxTokens"] == 30512
    assert result["world_policy_spec"]["limits"]["maxCostUsd"] == "0.064608"
    assert result["simulation_admission_v1"]["status"] == "ready"
    assert offline_http.clients and all(client.is_closed for client in offline_http.clients)
    assert offline_http.sent == []


@pytest.mark.parametrize("provider", ["claude-cli", "codex-cli", "unsupported-http"])
def test_unsupported_provider_never_constructs_http_client(provider, offline_http):
    value = profile()
    value["policy"]["provider"] = value["policy"]["pricing"]["provider"] = provider
    assert_error("unbounded_transport", mode="full", simulation_engine="world-v1", world_policy_spec=value)
    assert offline_http.clients == []


def test_real_configuration_identity_and_authentication_are_checked(offline_http, monkeypatch):
    monkeypatch.setattr(offline_http.config, "LLM_PROVIDER", "claude-cli")
    assert_error("policy_identity_mismatch", mode="full", simulation_engine="world-v1", world_policy_spec=profile())
    monkeypatch.setattr(offline_http.config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(offline_http.config, "LLM_BASE_URL", "https://other.invalid/v1")
    assert_error("policy_identity_mismatch", mode="full", simulation_engine="world-v1", world_policy_spec=profile())
    monkeypatch.setattr(offline_http.config, "LLM_BASE_URL", "https://fixture.invalid/v1")
    monkeypatch.setattr(offline_http.config, "LLM_API_KEY", "")
    assert_error("missing_policy_credentials", mode="full", simulation_engine="world-v1", world_policy_spec=profile())
    assert offline_http.clients == []


@pytest.mark.parametrize("field", ["source", "maxOutputIncludesReasoning", "inputUsdPerMillion"])
def test_constructor_rejects_missing_transport_guarantees(field, offline_http):
    from app.services.world_simulation.contracts import WorldError

    value = profile()
    del value["policy"]["pricing"][field]
    with pytest.raises(WorldError):
        resolve(mode="full", simulation_engine="world-v1", world_policy_spec=value)
    assert offline_http.clients == []


@pytest.mark.parametrize("stage", ["construct", "close"])
def test_transport_exceptions_are_sanitized_and_close_is_attempted(stage, monkeypatch):
    from app.services.world_simulation import policy

    closed = []

    class BrokenTransport:
        def __init__(self, _):
            if stage == "construct":
                raise RuntimeError("private-marker credential path")
            self.max_input = 30000
            self.max_output = 512

        def _cost(self, input_tokens, output_tokens):
            return "0.064608"

        def close(self):
            closed.append(True)
            raise RuntimeError("private-marker credential path")

    monkeypatch.setattr(policy, "StrictHTTPModeler", BrokenTransport)
    error = assert_error("invalid_policy_client", mode="full", simulation_engine="world-v1",
                         world_policy_spec=profile())
    assert "private-marker" not in str(error) and error.details == {}
    assert closed == ([] if stage == "construct" else [True])


@pytest.mark.parametrize("payload", [
    b'{"policy":{},"policy":{}}', b'{"\xc3\xa9":1,"e\xcc\x81":2}',
    b'{"limits":{"maxTokens":NaN}}', b'{"limits":{"maxTokens":1.5}}',
    b'{"limits":{"maxTokens":1e5}}', b'\xff', b'{', b'[]',
    b'{' * 2000, b' ' * (65536 + 1),
])
def test_malformed_or_oversized_profile_is_rejected_without_leaking_path(payload, tmp_path, no_transport):
    from app.services.world_simulation.contracts import WorldError

    path = tmp_path.resolve() / "private-marker-profile.json"
    path.write_bytes(payload)
    with pytest.raises(WorldError) as caught:
        resolve(mode="full", simulation_engine="world-v1", profile_path=path)
    assert "private-marker" not in str(caught.value)


@pytest.mark.parametrize("kind", ["file_symlink", "parent_symlink", "directory", "fifo", "missing"])
def test_profile_requires_regular_file_without_symlink_components(kind, tmp_path, no_transport):
    root = tmp_path.resolve()
    target = write_profile(root)
    path = root / "private-marker"
    if kind == "file_symlink":
        path.symlink_to(target)
    elif kind == "parent_symlink":
        path.symlink_to(root, target_is_directory=True)
        path = path / target.name
    elif kind == "directory":
        path.mkdir()
    elif kind == "fifo":
        os.mkfifo(path)
    error = assert_error("invalid_world_profile", mode="full", simulation_engine="world-v1", profile_path=path)
    assert "private-marker" not in str(error)


def test_profile_exact_size_limit_is_accepted(tmp_path, offline_http):
    path = write_profile(tmp_path)
    data = path.read_bytes()
    path.write_bytes(data + b" " * (65536 - len(data)))
    result = resolve(mode="full", simulation_engine="world-v1", profile_path=path)
    assert result["simulation_admission_v1"]["source"] == "operator_profile"
