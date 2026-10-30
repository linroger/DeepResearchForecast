"""R1/R4 behavioral review under main_offline_pytest.py only.

The coordinator owns production release and documentation. This module records
the actual runner/API boundary and authenticated replay failures without repairs.
"""

from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
import random
import sys

import pytest


_GUARD = sys.modules.get("main_offline_guard")
if _GUARD is None or not _GUARD.configured:
    raise RuntimeError("Run this module through main_offline_pytest.py")
_ROOT = Path(__file__).resolve().parents[2]
_PINS = (
    "backend/app/api/simulation.py",
    "backend/app/services/world_update.py",
    "backend/app/services/world_model.py",
    "backend/app/services/world_model_seed.py",
    "backend/app/services/world_anchor.py",
    "backend/app/services/actor_context.py",
    "backend/app/services/agent_decision.py",
    "backend/app/services/research_preparation.py",
    "backend/app/services/preparation_adapter.py",
    "backend/app/services/world_paths.py",
    "backend/app/services/simulation_record.py",
    "backend/app/services/simulation_record_gate.py",
    "backend/app/services/simulation_record_contract.py",
    "backend/scripts/run_parallel_simulation.py",
    "backend/scripts/replay_saved_world.py",
    "backend/tests/conftest.py",
    "backend/tests/test_calendar_round_loop.py",
    "backend/tests/test_world_model_loop.py",
    "backend/tests/test_world_paths.py",
    "backend/tests/test_world_anchor_reflexive.py",
    "backend/tests/test_world_anchor.py",
    "backend/tests/test_target_simulation.py",
    "backend/tests/test_agency_classification.py",
)
for _name in _PINS:
    _path = _ROOT / _name
    _GUARD.source_hashes.setdefault(str(_path), hashlib.sha256(_path.read_bytes()).hexdigest())

from app.services import world_update as wu  # noqa: E402
from app.services.actor_context import canonical_json_sha256  # noqa: E402
from app.services.world_model import WorldModel  # noqa: E402
from test_target_simulation import case as _target_case  # noqa: E402

target_case = _target_case
_SENTINEL = "PRIVATE_CANDIDATE_SENTINEL_R1"


def _write_receipt(name, value):
    (_GUARD.root / ("review-r1-r4-" + name + ".json")).write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _occurrences(value, sentinel, path="$"):
    if isinstance(value, dict):
        return [found for key, item in value.items()
                for found in _occurrences(item, sentinel, f"{path}.{key}")]
    if isinstance(value, list):
        return [found for index, item in enumerate(value)
                for found in _occurrences(item, sentinel, f"{path}[{index}]")]
    return [path] if isinstance(value, str) and sentinel in value else []


@pytest.mark.parametrize("mode", ["atomic", "field", "round"])
def test_r1_complete_runner_history_and_actual_api_keep_rejected_text_private(
        tmp_path, monkeypatch, mode):
    from flask import Flask
    from app.api.simulation import simulation_bp
    from app.config import Config
    from tests import test_world_model_loop as harness

    sim_dir = tmp_path / "sim_review_r1"
    sim_dir.mkdir()
    harness._patch_world(monkeypatch, str(sim_dir), [])
    monkeypatch.setenv("SIM_WORLD_ARBITER_REPAIR", mode)
    monkeypatch.setenv("SIM_WORLD_PATHS", "1")
    monkeypatch.setattr(harness.rps, "_RNG", random.Random(7))
    calls = []
    records = []
    real_run = wu.run_world_round

    def capture_round(*args, **kwargs):
        record = real_run(*args, **kwargs)
        records.append(deepcopy(record))
        return record

    monkeypatch.setattr(wu, "run_world_round", capture_round)
    candidate = {"variable_changes": [
        {"variable_id": "tariff_rate", "delta": 1},
        {"variable_id": _SENTINEL, "delta": 1},
    ]}

    class ReviewModel(harness._WorldLLM):
        def chat_json(self, messages, **kwargs):
            if messages[0]["content"].startswith("You are the consequence arbiter"):
                calls.append(deepcopy(messages))
                return deepcopy(candidate)
            return super().chat_json(messages, **kwargs)

    monkeypatch.setattr("app.utils.llm_client.LLMClient", ReviewModel)
    config = harness._world_config()
    config["world_model"]["settings"]["arbiter_repair"] = mode
    harness._run(config, str(sim_dir))
    history = harness._read_jsonl(str(sim_dir / "world_state_history.jsonl"))
    private = harness._read_jsonl(str(sim_dir / "arbiter_raw.jsonl"))
    state = json.loads((sim_dir / "world_state.json").read_text())
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    app = Flask(__name__)
    app.register_blueprint(simulation_bp, url_prefix="/api/simulation")
    response = app.test_client().get("/api/simulation/sim_review_r1/world-state")
    assert response.status_code == 200
    payload = response.get_json()
    api_history = payload["data"]["history"]
    assert [row["round"] for row in history] == [1, 2, 3]
    assert len(private) == len(api_history) == 3
    assert len(records) == 3
    per_round = 2 if mode == "atomic" else 1
    assert len(calls) == 3 * per_round
    expected_status = "applied_partial" if mode == "field" else "invalid"
    candidate_hash = canonical_json_sha256(candidate)
    for index, (row, api_row, raw_row) in enumerate(zip(history, api_history, private, strict=True)):
        assert row["arbiter_status"] == api_row["arbiter_status"] == expected_status
        assert len(row["arbiter_attempts"]) == len(api_row["arbiter_attempts"]) == per_round
        for offset, (attempt, public_attempt) in enumerate(zip(
                row["arbiter_attempts"], api_row["arbiter_attempts"], strict=True)):
            expected = {"attempt": offset + 1, "status": "invalid",
                        "source_hash": hashlib.sha256(
                            calls[index * per_round + offset][0]["content"].encode()).hexdigest(),
                        "candidate_hash": candidate_hash}
            assert {key: attempt[key] for key in expected} == expected
            assert {key: public_attempt[key] for key in expected} == expected
        if mode == "atomic":
            assert raw_row["arbiter_raw"] is None and raw_row["arbiter_raw_attempts"] == []
            assert _SENTINEL not in json.dumps(raw_row)
        else:
            assert raw_row["arbiter_raw"] == candidate
            assert raw_row["arbiter_raw_attempts"] == [candidate]
            # Legacy raw evidence remains available even when the whole round rejects.
            assert _SENTINEL in json.dumps(raw_row)
        changed = row["diff"]["variables_changed"]
        assert bool(changed) == (mode == "field")
        assert (bool(row["replay"]["accepted_arbiter_update"])) == (mode == "field")
        assert _SENTINEL not in json.dumps(row["replay"])
    assert all("arbiter_raw" not in row and "arbiter_raw_attempts" not in row for row in history)
    exposures = {
        "history": _occurrences(history, _SENTINEL),
        "api": _occurrences(payload, _SENTINEL),
        "state": _occurrences(state, _SENTINEL),
        "public_record_diagnostics": _occurrences([
            {key: row[key] for key in ("arbiter_problems", "arbiter_attempts", "arbiter_problem_details")}
            for row in records], _SENTINEL),
    }
    _write_receipt("r1-" + mode, {
        "mode": mode, "status": expected_status, "rounds": 3,
        "candidate_sha256": candidate_hash, "attempts_per_round": per_round,
        "history_path": str(sim_dir / "world_state_history.jsonl"),
        "private_path": str(sim_dir / "arbiter_raw.jsonl"),
        "private_diagnostic_paths": _occurrences(private, _SENTINEL),
        "public_exposures": exposures, "api_payload": payload,
        "status_and_hash_controls_passed": True,
    })
    assert not any(exposures.values()), exposures
    assert "arbiter_private_problems" not in json.dumps(history) + json.dumps(payload)
    for record, raw_row in zip(records, private, strict=True):
        if mode == "atomic":
            assert record.get("arbiter_private_problems", []) == raw_row.get("arbiter_private_problems", []) == []
        else:
            expected_private = [f"unknown variable '{_SENTINEL}'"]
            assert record["arbiter_private_problems"] == raw_row["arbiter_private_problems"] == expected_private


@pytest.mark.parametrize("mode", ["field", "round"])
def test_r1_compatible_field_validation_keeps_name_and_numeric_coercion(mode):
    world = WorldModel.from_seed({"state_variables": [
        {"id": "capacity", "name": "Available capacity", "value": 100}]})
    raw = {"variable_changes": [{"variable_id": "Available capacity", "delta": "2"}]}

    class Model:
        def chat_json(self, **kwargs):
            return deepcopy(raw)

    record = wu.run_world_round(world, 1, None, [], [], llm=Model(),
                                rng=random.Random(7), arbiter_repair=mode)
    assert record["arbiter_status"] == "applied"
    assert record["arbiter_validated"]["variable_changes"][0]["variable_id"] == "capacity"
    assert record["arbiter_validated"]["variable_changes"][0]["delta"] == 2
    assert world.variables["capacity"].value > 100


@pytest.mark.parametrize("mode", ["atomic", "field", "round"])
def test_r1_sibling_records_do_not_extend_public_projections(tmp_path, monkeypatch, mode):
    from flask import Flask
    from app.api.simulation import simulation_bp
    from app.config import Config
    from app.services import simulation_record as sr
    from tests import test_world_paths as harness

    sim_dir = tmp_path / "sim_review_siblings"
    sim_dir.mkdir()
    original = harness._PathLLM.chat_json
    candidate = {"variable_changes": [{"variable_id": "tariff_rate", "delta": 1},
                                      {"variable_id": _SENTINEL, "delta": 1}]}

    def chat_json(self, messages, **kwargs):
        if messages[0]["content"].startswith("You are the consequence arbiter"):
            return deepcopy(candidate)
        return original(self, messages, **kwargs)

    monkeypatch.setattr(harness._PathLLM, "chat_json", chat_json)
    monkeypatch.setenv("SIM_WORLD_ARBITER_REPAIR", mode)
    config = harness._world_config()
    config["world_model"]["settings"]["arbiter_repair"] = mode
    harness._run_paths(monkeypatch, sim_dir, k="2", cfg=config)
    paths = json.loads((sim_dir / "world_paths.json").read_text())
    assert paths["k"] == 2 and len(paths["paths"]) == 1
    records = paths["paths"][0]["records"]
    assert [row["round"] for row in records] == [1, 2, 3]
    assert all(row["arbiter_status"] == ("applied_partial" if mode == "field" else "invalid")
               for row in records)
    raw = harness._read_jsonl(str(sim_dir / "arbiter_raw.jsonl"))
    assert {(row["round"], row["path"]) for row in raw} == {(r, p) for r in (1, 2, 3) for p in (0, 1)}
    if mode != "atomic":
        assert all(row["arbiter_raw"] == candidate for row in raw)
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    app = Flask(__name__)
    app.register_blueprint(simulation_bp, url_prefix="/api/simulation")
    response = app.test_client().get("/api/simulation/sim_review_siblings/world-state")
    assert response.status_code == 200
    record = sr.build_record(str(sim_dir), engine_hint="oasis-reflexive", synthesis=False)
    public = {"world_state_api": response.get_json(), "after_action_record": record,
              "record_markdown": sr.render_markdown(record, "en")}
    # Exercise the saved-path fallback as well as the normal summary projection.
    artifacts = sr._Artifacts(str(sim_dir))
    artifacts.world_state["summary"] = {}
    public["record_saved_paths_fallback"] = sr._paths_block(artifacts, ["A", "B"])
    exposures = _occurrences(public, _SENTINEL)
    diagnostic_copies = [row["round"] for row in records if "arbiter_private_problems" in row]
    _write_receipt("r1-siblings-" + mode, {
        "mode": mode, "public_exposures": exposures,
        "private_diagnostic_copies_in_world_paths": diagnostic_copies,
        "raw_path": str(sim_dir / "arbiter_raw.jsonl"),
        "checkpoint_path": str(sim_dir / "world_paths.json"),
        "public_projection": public,
    })
    assert not exposures
    assert "arbiter_private_problems" not in json.dumps(public)
    assert diagnostic_copies == []
    if mode != "atomic":
        assert all(row["arbiter_private_problems"] == [f"unknown variable '{_SENTINEL}'"] for row in raw)


@pytest.fixture(params=[(False, False), (True, False), (False, True), (True, True)],
                ids=["accepted", "rollback", "prepared-accepted", "prepared-rollback"])
def anchored_record(request, tmp_path, monkeypatch, target_case):
    from app.services.agency_classification import build_agency_classifications
    from app.services.research_preparation import compile_preparation_context
    from app.services.world_anchor import validate_anchor_context
    from app.services.world_model_seed import build_world_model_seed
    from test_agency_classification import _entity
    from test_world_anchor_reflexive import _anchored_fixture

    rollback, prepared = request.param
    context, case = _anchored_fixture(tmp_path, target_case, temporal=False)
    actors = {"as_of_date": "2026-10-27", "actors": [{"name": "Acme", "agency_class": "firm"}]}
    configs = [{"agent_id": 0, "entity_uuid": "entity-1", "entity_name": "Acme", "entity_type": "Company"}]
    preparation = (compile_preparation_context(question="Target", research_report="Prepared report", actors=actors)
                   if prepared else None)
    seed = build_world_model_seed(actors, configs, forecast_case=case, anchor_context=context,
        preparation_context=preparation,
        agency_classifications=build_agency_classifications([_entity()], actors, None))
    world = WorldModel.from_seed(seed, configs, anchor_context=context)
    original = WorldModel.apply_arbiter_update
    mutations = []

    class Model:
        def chat_json(self, **kwargs):
            return {"variable_changes": [{"variable_id": "baseline", "delta": 5}]}

    def apply(current, round_num, update):
        result = original(current, round_num, update)
        mutations.append(current.variables["baseline"].value)
        if rollback:
            raise RuntimeError("PRIVATE_APPLY_FAILURE_R4")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(WorldModel, "apply_arbiter_update", apply)
        record = wu.run_world_round(world, 1,
            {"period_start": "2026-10-28", "period_end": "2026-10-31"}, [], [],
            llm=Model(), rng=random.Random(7), preparation_context=preparation)
    assert mutations and mutations[0] > 247.5
    assert record["arbiter_status"] == ("failed" if rollback else "applied")
    assert world.variables["baseline"].value == (247.5 if rollback else mutations[0])
    assert bool(record["replay"]["accepted_arbiter_update"]) is not rollback
    assert world._anchor_context is context
    validate_anchor_context(context, engine="oasis-legacy")
    replay = json.loads(json.dumps(record["replay"]))
    assert canonical_json_sha256({k: v for k, v in replay.items() if k != "content_sha256"}) == replay["content_sha256"]
    # Both saved boundaries already accept the same authenticated host context.
    for key in ("before", "after"):
        assert WorldModel.from_dict(replay[key], anchor_context=context).to_dict() == replay[key]
    return replay, context, preparation


def _replay_with_host(replay, context, preparation):
    """Exercise the old restore boundary until the proposed keyword is released.

    This avoids a TypeError-only red. Successful replay still requires exact
    state equality; the current signature reaches from_dict with no authority.
    """
    kwargs = {"preparation_context": preparation}
    if "anchor_context" in inspect.signature(wu.replay_world_round).parameters:
        kwargs["anchor_context"] = context
    return wu.replay_world_round(replay, **kwargs)


def test_r4_authenticated_accepted_and_rollback_replay_preserves_exact_hashes(anchored_record):
    replay, context, preparation = anchored_record
    before = deepcopy(replay)
    name = ("prepared-" if preparation else "") + replay["arbiter_status"]
    evidence = {"content_sha256": replay["content_sha256"],
                "deterministic_sha256": canonical_json_sha256(replay["deterministic_state"]),
                "after_sha256": canonical_json_sha256(replay["after"]),
                "host_context_pack_hash": context.pack_hash,
                "host_restore_controls_passed": True,
                "has_anchor_context_parameter": "anchor_context" in inspect.signature(wu.replay_world_round).parameters}
    try:
        restored = _replay_with_host(replay, context, preparation)
    except Exception as exc:
        evidence.update(error_type=type(exc).__name__, error=str(exc))
        raise
    else:
        assert restored._anchor_context is context
        assert restored.to_dict() == replay["after"]
        assert canonical_json_sha256(restored.to_dict()) == evidence["after_sha256"]
        assert replay == before
        evidence["exact_replay_passed"] = True
    finally:
        _write_receipt("r4-" + name, evidence)


def test_r4_missing_context_still_rejects_anchored_replay(anchored_record):
    replay, _, preparation = anchored_record
    with pytest.raises(ValueError, match="invalid_anchor_context"):
        wu.replay_world_round(replay, preparation_context=preparation)


def test_r4_serialized_anchor_pin_is_not_restore_authority(anchored_record):
    replay, _, _ = anchored_record
    with pytest.raises(ValueError, match="invalid_anchor_context"):
        WorldModel.from_dict(replay["before"], anchor_context=replay["before"]["world_anchor"])


def test_r4_authentic_wrong_context_rejects_before_any_transition(
        anchored_record, tmp_path, target_case):
    from test_world_anchor_reflexive import _anchored_fixture

    replay, context, preparation = anchored_record
    (tmp_path / "other").mkdir()
    other, _ = _anchored_fixture(tmp_path / "other", target_case, temporal=False, hidden="OTHER_SOURCE")
    assert other.pack_hash != context.pack_hash
    with pytest.raises(ValueError, match="world anchor context/runtime binding mismatch"):
        WorldModel.from_dict(replay["before"], anchor_context=other)
    with pytest.raises(ValueError, match="world anchor context/runtime binding mismatch"):
        _replay_with_host(replay, other, preparation)


@pytest.mark.parametrize("tamper", ["fingerprint", "deterministic_state", "after"])
def test_r4_transition_tampering_rejects_with_authenticated_host(anchored_record, tamper):
    replay, context, preparation = anchored_record
    replay = deepcopy(replay)
    if tamper == "fingerprint":
        replay["content_sha256"] = "0" * 64
        error = "World replay fingerprint mismatch"
    else:
        baseline = next(row for row in replay[tamper]["variables"] if row["id"] == "baseline")
        baseline["value"] += 1
        replay["content_sha256"] = canonical_json_sha256(
            {k: v for k, v in replay.items() if k != "content_sha256"})
        error = "World replay " + ("deterministic" if tamper == "deterministic_state" else "accepted") + " transition drifted"
    with pytest.raises(ValueError, match=error):
        _replay_with_host(replay, context, preparation)
