"""Root arbiter execution contract, exercised with actual world/actor consumers.

Brief: accept a typed, current-world-bound proposal atomically; give malformed
content one constrained correction, never retry a transport failure here. Keep
the legacy filtering helper available. Rejected candidates leave only the
deterministic round and hash/path diagnostics, never provider text.

Run through main_offline_pytest.py before imports. No saved runs or providers.
The coordinator owns the shared handoff; this file owns the scenario evidence.
"""

import copy
import hashlib
import json
import random

import pytest

from app.services import world_update as wu
from app.services.world_model import WorldModel
from tests.conftest import content_filter_error
from tests.test_run_arbiter_contract import _parse, _promise, _prompt, _world


def _proposal(**fields):
    return {"narrative": "The technical assessment changed the tracked facts.",
            "variable_changes": [], "new_variables": [], "events": [],
            "relationship_changes": [], "pending_effects": [],
            "action_resolutions": [], "red_line_crossings": [],
            "scenario_pressure": {}, **fields}


class Model:
    """One scripted model response per call, with no implicit parse retry."""

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = []

    def chat_json(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        assert self.outputs, "arbiter exceeded its bounded call budget"
        value = self.outputs.pop(0)
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)


def _run(world, llm, decisions=(), *, round_num=3):
    return wu.run_world_round(world, round_num, {"label": f"period-{round_num}"},
                              decisions, (), llm=llm, rng=random.Random(29))


def _reload(world):
    return WorldModel.from_dict(json.loads(json.dumps(world.to_dict())))


def _resolution(promise=None, **fields):
    return {"agent_id": 0, "outcome": "success", "rationale": "The entire package was delivered.",
            "commitment_id": promise["id"] if promise else None,
            "action_round": 3 if promise else None, **fields}


def test_mixed_invalid_proposal_is_repaired_before_any_apply(monkeypatch):
    world = _world()
    bad = _proposal(variable_changes=[
        {"variable_id": "talks_status", "new_value": "signed"},
        {"variable_id": "recent_momentum", "new_value": "accelerating"},
    ], events=[{"description": "REJECTED CANDIDATE EVENT", "kind": "emergent"}])
    good = _proposal(variable_changes=[{"variable_id": "recent_momentum", "new_value": 3.2}])
    llm = Model(bad, good)
    seen = []
    original = WorldModel.apply_arbiter_update

    def apply(self, round_num, update):
        seen.append(copy.deepcopy(update))
        assert len(llm.calls) == 2
        assert self.variables["talks_status"].value == "pending"
        return original(self, round_num, update)

    monkeypatch.setattr(WorldModel, "apply_arbiter_update", apply)
    record = _run(world, llm)
    assert len(llm.calls) == 2 and len(seen) == 1
    assert record["arbiter_status"] == "applied"
    assert world.variables["talks_status"].value == "pending"
    assert world.variables["recent_momentum"].value == pytest.approx(3.17)
    assert not any("REJECTED CANDIDATE EVENT" in event.description for event in world.events)
    assert world.committed_round == 3
    restored = _reload(world)
    restored.start_round(4, {"label": "period-4"})
    feedback = _prompt(restored, 0, 4, record["digest"])
    assert "3.17" in feedback and "REJECTED CANDIDATE EVENT" not in feedback
    correction = llm.calls[1]["messages"][-1]["content"]
    context = llm.calls[1]["messages"][0]["content"]
    assert "recent_momentum" in context and "numeric" in context
    assert "variable_changes" in correction and "new_value" in correction
    assert "accelerating" not in correction and "REJECTED CANDIDATE EVENT" not in correction
    attempts = record["arbiter_attempts"]
    assert [a["status"] for a in attempts] == ["invalid", "valid"]
    assert all(len(a["source_hash"]) == len(a["candidate_hash"]) == 64 for a in attempts)
    assert attempts[0]["source_hash"] == attempts[1]["source_hash"]
    assert attempts[0]["candidate_hash"] != attempts[1]["candidate_hash"]
    assert record["arbiter_problems"] == []  # rejected attempts are audit history, not current problems


@pytest.mark.parametrize("bad_change", [
    {"new_value": "4"}, {"new_value": "4 square miles"}, {"new_value": True},
    {"new_value": float("nan")}, {"delta": float("inf")},
    {"new_value": "slowing", "delta": 1}, {"new_value": 4, "delta": "slowing"},
])
def test_repeated_numeric_rejection_is_deterministic_only(bad_change, monkeypatch):
    world = _world()
    move = _parse(world, 0, 3, "public_statement", public_statement="We released the assessment.")
    bad = _proposal(variable_changes=[{"variable_id": "talks_status", "new_value": "signed"},
                                      {"variable_id": "recent_momentum", **bad_change}],
                    action_resolutions=[_resolution()])
    llm = Model(bad, bad)
    monkeypatch.setattr(world, "apply_arbiter_update", lambda *_: pytest.fail("invalid proposal reached kernel"))
    record = _run(world, llm, [move])
    assert record["arbiter_status"] == "invalid" and len(llm.calls) == 2
    assert record["arbiter"] == {} and record["scenario_pressure"] == {} and record["narrative"] == ""
    assert record["arbiter_problems"] and world.committed_round == 3
    assert world.variables["talks_status"].value == "pending"
    assert world.variables["recent_momentum"].value == 3
    assert world.actors[0].last_action["resolution"] is None
    assert any(event.kind == "action" for event in world.events)
    restored = _reload(world)
    restored.start_round(4, {"label": "period-4"})
    assert "signed" not in _prompt(restored, 0, 4, record["digest"])


@pytest.mark.parametrize("field,value", [
    ("variable_changes", {}), ("events", [None]), ("action_resolutions", "success"),
    ("new_variables", [{"name": "Rate", "kind": "numeric", "value": "high"}]),
    ("pending_effects", [{"description": "Later", "variable_id": "recent_momentum", "delta": "up"}]),
    ("pending_effects", [{"description": "Later", "variable_id": "unknown", "delta": 1}]),
    ("pending_effects", [{"description": "Later", "due_periods": True}]),
])
def test_other_malformed_fields_do_not_apply_filtered_partial_proposals(field, value):
    world = _world()
    bad = _proposal(**{field: value})
    bad["variable_changes"] = (value if field == "variable_changes" else
                               [{"variable_id": "talks_status", "new_value": "signed"}])
    llm = Model(bad, bad)
    record = _run(world, llm)
    assert record["arbiter_status"] == "invalid" and len(llm.calls) == 2
    assert world.variables["talks_status"].value == "pending"
    assert not world.pending_effects and len(world.variables) == 2


@pytest.mark.parametrize("agreement,duplicates", [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize("outcome", ["success", "partial", "failed"])
def test_bound_delivery_commit_and_reloaded_actor_feedback(agreement, duplicates, outcome):
    world = _world(duplicate_names=duplicates)
    promise = _promise(world, agreement)
    other = world.actors[0].add_commitment("Publish a separate report.", made_round=2, due_round=4)
    world.start_round(3, {"label": "period-3"})
    targets = [1] if agreement else []
    move = _parse(world, 0, 3, f"fulfill:{promise['id']}", targets=targets)
    assert move.ok
    llm = Model(_proposal(action_resolutions=[_resolution(promise, outcome=outcome)]))
    record = _run(world, llm, [move])
    assert record["arbiter_status"] == "applied" and len(llm.calls) == 1
    assert record["arbiter"]["commitments_fulfilled"] == int(outcome == "success")
    assert promise["status"] == ("fulfilled" if outcome == "success" else "due")
    assert other["status"] == "pending"
    assert promise["last_fulfillment_attempt"]["outcome"] == outcome
    restored = _reload(world)
    restored.start_round(4, {"label": "period-4"})
    feedback = _prompt(restored, 0, 4, record["digest"])
    assert f"outcome so far: {outcome}" in feedback
    assert (f"fulfilled commitment [{promise['id']}]" in feedback) == (outcome == "success")
    assert f"[fulfill:{other['id']}]" in feedback


@pytest.mark.parametrize("mutation", ["wrong_id", "wrong_round", "string_round", "no_rationale",
                                      "duplicate", "wrong_actor", "wrong_targets"])
def test_unbound_delivery_cannot_be_partially_applied(mutation):
    world = _world()
    promise = _promise(world, False)
    world.start_round(3, {"label": "period-3"})
    move = _parse(world, 0, 3, f"fulfill:{promise['id']}", targets=[])
    assert move.ok
    row = _resolution(promise)
    rows = [row]
    if mutation == "wrong_id":
        row["commitment_id"] = "not-this-promise"
    elif mutation == "wrong_round":
        row["action_round"] = 2
    elif mutation == "string_round":
        row["action_round"] = "3"
    elif mutation == "no_rationale":
        row["rationale"] = ""
    elif mutation == "duplicate":
        rows.append(copy.deepcopy(row))
    elif mutation == "wrong_actor":
        row["agent_id"] = 1
    else:
        # An invalid producer target must not create an attestation binding.
        move.targets = ["Mediator"]
    bad = _proposal(action_resolutions=rows,
                    variable_changes=[{"variable_id": "talks_status", "new_value": "signed"}])
    llm = Model(bad, bad)
    record = _run(world, llm, [move])
    assert record["arbiter_status"] == "invalid" and len(llm.calls) == 2
    assert promise["status"] == "due" and "fulfillment_evidence" not in promise
    assert world.variables["talks_status"].value == "pending" and world.track_record(0)["kept"] == 0


@pytest.mark.parametrize("claims_delivery", [False, True])
def test_ordinary_success_cannot_fulfil_promise(claims_delivery):
    world = _world()
    promise = _promise(world, False)
    world.start_round(3, {"label": "period-3"})
    move = _parse(world, 0, 3, "public_statement", public_statement="We delivered everything.")
    payload = _proposal(action_resolutions=[_resolution(promise if claims_delivery else None)])
    llm = Model(payload, payload)
    record = _run(world, llm, [move])
    assert record["arbiter_status"] == ("invalid" if claims_delivery else "applied")
    assert len(llm.calls) == (2 if claims_delivery else 1)
    assert promise["status"] == "due" and "fulfillment_evidence" not in promise
    assert world.track_record(0)["kept"] == 0


def test_malformed_json_gets_exactly_one_content_correction():
    class TextModel(Model):
        # Production LLMClient has both surfaces. chat_json must never multiply
        # the arbiter's two content attempts by its own two-attempt parser loop.
        _parse_json_response = staticmethod(lambda _: pytest.fail("client parser must not run"))

        def chat(self, **kwargs):
            return super().chat_json(**kwargs)

        def chat_json(self, **kwargs):
            pytest.fail("retrying chat_json surface used for a raw-capable client")

    world = _world()
    raw = '{"narrative": "secret-provider-body", "variable_changes": ['
    llm = TextModel(raw, json.dumps(_proposal(variable_changes=[{"variable_id": "recent_momentum", "delta": 0.2}])))
    record = _run(world, llm)
    assert record["arbiter_status"] == "applied" and len(llm.calls) == 2
    assert record["arbiter_attempts"][0]["candidate_hash"] == hashlib.sha256(raw.encode()).hexdigest()
    assert "secret-provider-body" not in json.dumps(record) + json.dumps(llm.calls[1])


@pytest.mark.parametrize("after_invalid", [False, True])
def test_transport_error_never_gets_content_retry_or_raw_error_diagnostics(after_invalid, caplog):
    world = _world()
    outputs = [_proposal(variable_changes=[{"variable_id": "recent_momentum", "new_value": "secret-candidate"}])] if after_invalid else []
    llm = Model(*outputs, TimeoutError("Authorization: Bearer secret-provider-body"))
    record = _run(world, llm)
    assert record["arbiter_status"] == "failed" and len(llm.calls) == 1 + int(after_invalid)
    assert world.committed_round == 3 and record["arbiter"] == {}
    assert "TimeoutError" in json.dumps(record["arbiter_problems"])
    assert "secret-" not in json.dumps(record) + caplog.text


def test_legacy_filter_helper_stays_available_but_runtime_is_strict():
    world = _world()
    raw = {"variable_changes": [{"variable_id": "recent_momentum", "new_value": "3.2"}]}
    legacy, problems = wu.validate_arbiter_update(raw, world)
    assert not problems and legacy["variable_changes"][0]["new_value"] == 3.2
    record = _run(world, Model(raw, raw))
    assert record["arbiter_status"] == "invalid" and world.variables["recent_momentum"].value == 3


def test_native_llm_client_transport_failure_does_not_multiply_fallbacks(scripted_failover):
    client, transports = scripted_failover(content_filter_error(), fallback_error=content_filter_error("assistant"))
    world = _world()
    record = _run(world, client)
    assert record["arbiter_status"] == "failed"
    assert transports == [("glm", False), ("kimi", True)]
    assert len(record["arbiter_attempts"]) == 1 and world.committed_round == 3
    assert world.variables["recent_momentum"].value == 3


def test_native_llm_client_content_budget_is_two_not_four(monkeypatch):
    from app.utils.llm_client import LLMClient
    from app.config import Config

    monkeypatch.setattr(Config, "LLM_CACHE_ENABLED", False)
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", False)
    client = LLMClient(provider="glm", model="offline", api_key="synthetic", base_url="http://127.0.0.1:1/v1")
    replies = iter(['{"bad":', '{"bad":'])
    calls = []

    def transport(self, messages, temperature, max_tokens, response_format=None, tier="strong"):
        calls.append(copy.deepcopy(messages))
        return next(replies)

    monkeypatch.setattr(LLMClient, "_chat_openai", transport)
    record = _run(_world(), client)
    assert record["arbiter_status"] == "invalid" and len(calls) == 2
    assert len(record["arbiter_attempts"]) == 2


def test_apply_exception_rolls_back_before_deterministic_commit(monkeypatch, caplog):
    world = _world()
    move = _parse(world, 0, 3, "public_statement", public_statement="The assessment was published.")
    original = WorldModel.apply_arbiter_update

    def broken(self, round_num, update):
        original(self, round_num, update)
        raise RuntimeError("secret-provider-body")

    monkeypatch.setattr(WorldModel, "apply_arbiter_update", broken)
    record = _run(world, Model(_proposal(
        variable_changes=[{"variable_id": "talks_status", "new_value": "signed"}],
        action_resolutions=[_resolution()])), [move])
    assert record["arbiter_status"] == "failed" and world.committed_round == 3
    assert world.variables["talks_status"].value == "pending"
    assert world.actors[0].last_action["resolution"] is None
    assert record["arbiter"] == {} and record["narrative"] == "" and record["scenario_pressure"] == {}
    assert "secret-provider-body" not in json.dumps(record) + caplog.text


def test_generated_contract_is_shared_with_validator_and_covers_full_registry():
    world = _world()
    for index in range(25):
        world.add_variable(f"Count {index}", index, kind="numeric")
    contract = wu.build_arbiter_contract(world)
    assert len(contract["x-variable-registry"]) == 27
    raw = _proposal(variable_changes=[{"variable_id": "count_24", "new_value": 24.1}])
    assert wu._contract_problems(raw, contract) == []
    assert wu.validate_arbiter_update(raw, world, strict=True)[1] == []
    prompt = wu.build_arbiter_prompt(world, 0, None, (), {}, ())
    embedded = json.loads(prompt.split("## Machine-readable proposal contract\n", 1)[1].split("\n", 1)[1])
    assert embedded == contract
    record = _run(world, Model(raw))
    assert record["arbiter_status"] == "applied"
    assert world.variables["count_24"].value != 24


def test_typed_delayed_boolean_survives_commit_reload_and_next_round():
    world = _world()
    world.add_variable("Approved", True, kind="boolean")
    raw = _proposal(pending_effects=[{"description": "The approval expires next period.",
                                     "due_periods": 1, "variable_id": "approved", "new_value": False,
                                     "probability": 1}])
    record = _run(world, Model(raw))
    assert record["arbiter_status"] == "applied" and world.variables["approved"].value is True
    restored = _reload(world)
    assert restored.pending_effects[0].value is False
    _run(restored, Model(_proposal()), round_num=4)
    assert restored.variables["approved"].value is False
    restored.start_round(5, {"label": "period-5"})
    assert "Approved: no" in _prompt(restored, 0, 5)


def test_exact_scenario_key_survives_validation_and_world_round():
    world = _world()
    scenarios = ["Limited escalation", "Escalation"]
    raw = _proposal(scenario_pressure={"Escalation": "up"})
    record = wu.run_world_round(world, 3, {"label": "period-3"}, (), (),
                                llm=Model(raw), rng=random.Random(29), scenarios=scenarios)
    assert record["arbiter_status"] == "applied"
    assert record["scenario_pressure"] == {"Escalation": "up"}


@pytest.mark.parametrize("actor", [2, "Mediator"])
def test_relationship_identity_never_rebinds_through_duplicate_display_name(actor):
    world = _world(duplicate_names=True)
    payload = _proposal(relationship_changes=[{"source": actor, "target": 0, "direction": "closer"}])
    record = _run(world, Model(payload, payload))
    assert world._relationship_between(1, 0) is None
    if type(actor) is int:
        assert record["arbiter_status"] == "applied" and world._relationship_between(2, 0) is not None
    else:
        assert record["arbiter_status"] == "invalid" and world._relationship_between(2, 0) is None


@pytest.mark.parametrize("names", [["Recent-momentum"], ["New rate", "New-rate"]])
def test_new_variable_identity_collision_rejects_whole_proposal(names):
    world = _world()
    payload = _proposal(variable_changes=[{"variable_id": "talks_status", "new_value": "signed"}],
                        new_variables=[{"name": name, "kind": "categorical", "value": "high"} for name in names])
    record = _run(world, Model(payload, payload))
    assert record["arbiter_status"] == "invalid"
    assert world.variables["talks_status"].value == "pending" and len(world.variables) == 2


@pytest.mark.parametrize("repair", [True, False], ids=["repaired", "repeated-invalid"])
def test_actual_calendar_loop_validation_commit_history_and_next_actor_feedback(tmp_path, monkeypatch, repair):
    from tests import test_world_model_loop as harness
    from flask import Flask
    from app.api.simulation import simulation_bp
    from app.config import Config

    envs = []
    sim_dir = tmp_path / "sim_transaction"
    sim_dir.mkdir()
    harness._patch_world(monkeypatch, str(sim_dir), envs)
    attempts = []
    candidates = []

    class TransactionModel(harness._WorldLLM):
        def chat_json(self, messages, **kwargs):
            original = messages[0]
            if "consequence arbiter" not in original["content"]:
                return super().chat_json(messages, **kwargs)
            attempts.append(copy.deepcopy(messages))
            result = super().chat_json([original], **kwargs)
            if not repair or len(attempts) % 2:
                result["variable_changes"] = [{"variable_id": "tariff_rate", "new_value": "higher"}]
                result["events"] = [{"description": "REJECTED CALENDAR EVENT", "kind": "emergent"}]
            candidates.append(copy.deepcopy(result))
            return result

    monkeypatch.setattr("app.utils.llm_client.LLMClient", TransactionModel)
    harness._run(harness._world_config(), str(sim_dir))
    history = harness._read_jsonl(str(sim_dir / "world_state_history.jsonl"))
    assert len(attempts) == 6 and [row["round"] for row in history] == [1, 2, 3]
    assert all(row["arbiter_status"] == ("applied" if repair else "invalid") for row in history)
    problem = "$.variable_changes[0].new_value: expected number (numbers must be finite)"
    for index, row in enumerate(history):
        assert row["arbiter_problems"] == ([] if repair else [problem])
        expected = []
        for offset in range(2):
            trace = index * 2 + offset
            valid = repair and offset == 1
            expected.append({
                "attempt": offset + 1, "status": "valid" if valid else "invalid",
                "source_hash": hashlib.sha256(attempts[trace][0]["content"].encode()).hexdigest(),
                "candidate_hash": hashlib.sha256(json.dumps(candidates[trace], ensure_ascii=True,
                                                           sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                "problems": [] if valid else [problem],
            })
        assert row["arbiter_attempts"] == expected
    state = json.loads((sim_dir / "world_state.json").read_text())
    assert state["committed_round"] == 3
    next_actor = next(call["content"] for call in harness._WorldLLM.calls
                      if call["kind"] == "decision" and call["actor"] == "Actor0" and call["round"] == 2)
    assert ("- Tariff rate: 13.5% (was 10% last period)" in next_actor) == repair
    if not repair:
        assert "- Tariff rate: 10%" in next_actor and "outcome so far: success" not in next_actor
        assert all(row["diff"]["variables_changed"] == [] for row in history)
    assert "REJECTED CALENDAR EVENT" not in next_actor
    # Read the real writer's artifacts through the actual typed API consumer.
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    app = Flask(__name__)
    app.register_blueprint(simulation_bp, url_prefix="/api/simulation")
    response = app.test_client().get("/api/simulation/sim_transaction/world-state")
    assert response.status_code == 200
    public_history = response.get_json()["data"]["history"]
    assert [row["arbiter_attempts"] for row in public_history] == [row["arbiter_attempts"] for row in history]
    assert [row["arbiter_problems"] for row in public_history] == [row["arbiter_problems"] for row in history]
    assert "REJECTED CALENDAR EVENT" not in json.dumps(history) + response.get_data(as_text=True)
    assert '"new_value": "higher"' not in json.dumps(history) + response.get_data(as_text=True)


@pytest.mark.parametrize("label_length", [70, 240], ids=["full-path", "bounded-long-path"])
def test_multilingual_rejection_receipt_survives_actual_history_api(tmp_path, monkeypatch, label_length):
    from flask import Flask
    from app.api.simulation import simulation_bp
    from app.config import Config

    scenarios = ["甲" * label_length, "乙" * label_length]
    bad = _proposal(scenario_pressure={scenario: "unknown" for scenario in scenarios})
    world = _world()
    world.scenarios = scenarios
    record = wu.run_world_round(world, 3, {"label": "period-3"}, (), (), llm=Model(bad, _proposal()),
                                rng=random.Random(29), scenarios=scenarios)
    assert record["arbiter_status"] == "applied"
    path = tmp_path / "sim_receipts"
    path.mkdir()
    (path / "world_state.json").write_text(json.dumps({"world": world.to_dict(), "committed_round": 3}))
    (path / "world_state_history.jsonl").write_text(json.dumps(record) + "\n")
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    app = Flask(__name__)
    app.register_blueprint(simulation_bp, url_prefix="/api/simulation")
    response = app.test_client().get("/api/simulation/sim_receipts/world-state")
    assert response.status_code == 200
    readback = response.get_json()["data"]["history"][0]
    assert record["arbiter_problems"] == readback["arbiter_problems"] == []
    assert readback["arbiter_attempts"] == record["arbiter_attempts"]
    assert all(len(problem) <= 200 for attempt in readback["arbiter_attempts"] for problem in attempt["problems"])


def _read_history_api(tmp_path, monkeypatch, history):
    from flask import Flask
    from app.api.simulation import simulation_bp
    from app.config import Config

    path = tmp_path / "sim_attempts"
    path.mkdir()
    (path / "world_state.json").write_text(json.dumps({"world": _world().to_dict(), "committed_round": 3}))
    (path / "world_state_history.jsonl").write_text("".join(json.dumps(row) + "\n" for row in history))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    app = Flask(__name__)
    app.register_blueprint(simulation_bp, url_prefix="/api/simulation")
    response = app.test_client().get("/api/simulation/sim_attempts/world-state")
    assert response.status_code == 200
    return response.get_json()["data"]["history"]


def test_history_api_legacy_rows_without_attempts_remain_readable(tmp_path, monkeypatch):
    rows = [{"round": 1, "arbiter_status": "applied", "arbiter_problems": []},
            {"round": 2, "arbiter_status": "failed", "arbiter_problems": ["llm error: RuntimeError"]}]
    history = _read_history_api(tmp_path, monkeypatch, rows)
    assert [row["arbiter_attempts"] for row in history] == [[], []]
    assert [row["arbiter_problems"] for row in history] == [[], ["llm error: RuntimeError"]]
    assert [row["arbiter_status"] for row in history] == ["applied", "failed"]


def test_history_api_attempts_are_typed_bounded_and_body_free(tmp_path, monkeypatch):
    paths = [f"$.variable_changes[{index}].new_value: expected number (numbers must be finite)" for index in range(15)]
    invalid = {"attempt": 1, "status": "invalid", "source_hash": "a" * 64, "candidate_hash": "b" * 64,
               "problems": paths, "raw_candidate": "fixture-candidate-secret",
               "provider_body": {"token": "fixture-provider-secret"}}
    failed = {"attempt": 2, "status": "failed", "source_hash": "a" * 64,
              "problems": ["TimeoutError; HTTP 429; provider code 1301; quota/rate limit",
                           {"body": "fixture-provider-secret"}, "Authorization: Bearer fixture-provider-secret"]}
    history = _read_history_api(tmp_path, monkeypatch, [{"round": 3, "arbiter_status": "failed",
        "arbiter_problems": ["llm error: TimeoutError"], "arbiter_attempts": [invalid, failed, invalid]}])
    assert history[0]["arbiter_attempts"] == [
        {"attempt": 1, "status": "invalid", "source_hash": "a" * 64, "candidate_hash": "b" * 64,
         "problems": [path[:200] for path in paths[:12]]},
        {"attempt": 2, "status": "failed", "source_hash": "a" * 64,
         "problems": ["TimeoutError; HTTP 429; provider code 1301; quota/rate limit"]}]
    assert history[0]["arbiter_problems"] == ["llm error: TimeoutError"]
    assert "fixture-" not in json.dumps(history)


@pytest.mark.parametrize("unsafe", [
    "$.events[0]: Authorization: Bearer fixture-path-secret",
    "$: raw provider body fixture-path-secret",
    "$.events[0].fixture_path_secret: required",
    "$.events[0]: value outside current contract fixture-path-secret",
])
def test_history_api_rejects_path_prefixed_provider_text(tmp_path, monkeypatch, unsafe):
    safe = "$.events[0].kind: value outside current contract"
    history = _read_history_api(tmp_path, monkeypatch, [{"round": 3, "arbiter_attempts": [
        {"attempt": 1, "status": "invalid", "source_hash": "a" * 64,
         "candidate_hash": "b" * 64, "problems": [unsafe, safe]}]}])
    assert history[0]["arbiter_attempts"] == [
        {"attempt": 1, "status": "invalid", "source_hash": "a" * 64,
         "candidate_hash": "b" * 64, "problems": [safe]}]
    assert "fixture-" not in json.dumps(history) and "fixture_path_secret" not in json.dumps(history)


@pytest.mark.parametrize("mutation", ["status", "source_hash", "candidate_hash", "missing_candidate", "attempt", "not_object"])
def test_history_api_rejects_malformed_attempts_without_coercion(tmp_path, monkeypatch, mutation):
    row = {"attempt": 1, "status": "invalid", "source_hash": "a" * 64, "candidate_hash": "b" * 64,
           "problems": ["$.variable_changes: expected array"]}
    if mutation == "status":
        row["status"] = "rejected"
    elif mutation == "source_hash":
        row["source_hash"] = "z" * 64
    elif mutation == "candidate_hash":
        row["candidate_hash"] = "b" * 63
    elif mutation == "missing_candidate":
        row.pop("candidate_hash")
    elif mutation == "attempt":
        row["attempt"] = True
    else:
        row = "fixture-provider-secret"
    history = _read_history_api(tmp_path, monkeypatch, [{"round": 3, "arbiter_attempts": [row]}])
    assert history[0]["arbiter_attempts"] == []
