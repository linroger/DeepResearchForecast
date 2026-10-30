"""Combined main preparation/mechanics and feature anchor/target contracts."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import sys

import pytest

from app.services import agent_decision as ad
from app.services import world_update as wu
from app.services.world_model import StateVariable, WorldModel
from app.services.world_model_seed import build_world_model_seed
from test_target_simulation import case as _target_case

target_case = _target_case


@pytest.fixture(autouse=True)
def record_merge_source_pins():
    guard = sys.modules.get("main_offline_guard")
    if guard is not None:
        root = Path(__file__).resolve().parents[2]
        for name in ("backend/app/services/agent_decision.py", "backend/app/services/world_model.py",
                     "backend/app/services/world_model_seed.py", "backend/app/services/world_update.py",
                     "backend/scripts/run_parallel_simulation.py"):
            path = root / name
            guard.source_hashes.setdefault(str(path), hashlib.sha256(path.read_bytes()).hexdigest())


def test_preparation_and_anchor_are_both_admitted_before_seed_projection(tmp_path, monkeypatch, target_case):
    from app.services.agency_classification import build_agency_classifications
    from app.services.research_preparation import compile_preparation_context
    from test_agency_classification import _entity
    from test_world_anchor_reflexive import _anchored_fixture

    context, case = _anchored_fixture(tmp_path, target_case, temporal=False)
    configs = [{"agent_id": 0, "entity_uuid": "entity-1", "entity_name": "Acme",
                "entity_type": "Company", "agency_class": "firm"}]
    actors = {"as_of_date": "2026-10-27", "actors": [{"name": "Acme", "agency_class": "firm",
              "goals": ["DENIED_PREPARED_GOAL"], "future_plans": ["DENIED_PREPARED_PLAN"]}]}
    prepared = compile_preparation_context(question="Target", research_report="Prepared report", actors=actors)
    kwargs = {"preparation_context": prepared, "forecast_case": case, "anchor_context": context,
              "agency_classifications": build_agency_classifications([_entity()], actors, None)}
    seed = build_world_model_seed(actors, configs, **kwargs)
    assert seed["preparation_context_sha256"] == prepared["content_sha256"]
    assert seed["world_anchor"]["pack_hash"] == context.pack_hash
    assert seed["actors"][0]["goals"] == seed["actors"][0]["documented_plans"] == []
    world = WorldModel.from_seed(seed, configs, anchor_context=context)
    world.start_round(1, {"period_start": "2026-10-28", "period_end": "2026-10-31"})
    assert world.evaluate_target_projection(1, random.Random(1))["status"] == "ready"
    assert world.public_target_values()["target"] == 247.5
    assert WorldModel.from_dict(world.to_dict(), anchor_context=context).to_dict() == world.to_dict()
    broken = deepcopy(prepared)
    broken["content_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        build_world_model_seed(actors, configs, **{**kwargs, "preparation_context": broken})


def test_variable_round_trip_preserves_research_and_target_metadata():
    evidence = {"id": "source-row", "bundle_sha256": "a" * 64}
    identity = {"nodeId": "target", "unitId": "usd"}
    metadata = {"node_id": "target", "value_kind": "third_party_forecast"}
    var = StateVariable("target", "Target", 12, unit="USD billion", read_only=True,
                        identity=identity, anchor_metadata=metadata, research_evidence=evidence)
    restored = StateVariable.from_dict(var.to_dict())
    assert restored.to_dict() == var.to_dict()
    detached = restored.research_evidence
    detached["id"] = "changed"
    assert restored.research_evidence == evidence
    assert restored.identity == identity and restored.anchor_metadata == metadata


def test_strict_arbiter_binds_ordinary_action_and_separate_owned_delivery():
    world = WorldModel.from_seed({"settings": {"action_policy": "affordable-menu-v2"}, "actors": [
        {"agent_id": 0, "name": "Acme", "agency_class": "firm", "capacity_per_round": 3}]})
    world.start_round(1, None)
    promise = world.actors[0].add_commitment("Deliver the report", made_round=1, due_round=2)
    world.start_round(2, None)
    actor = world.actors[0]
    options = ad.build_option_menu(actor, world, 2)
    option = next(o for o in options if not o.get("targets_actor")
                  and not o["id"].startswith("fulfill:") and o["kind"] != "wait")
    decision = ad.parse_decision({"option_id": option["id"], "public_statement": "We delivered the report.",
                                 "deliveries": [promise["id"]]}, actor=actor, world=world,
                                options=options, scenarios=[], round_num=2)
    assert decision.ok
    world.register_decisions(2, [decision.to_dict()])
    payload = {"action_resolutions": [
        {"agent_id": 0, "outcome": "success", "rationale": "Statement published.",
         "commitment_id": None, "action_round": None},
        {"agent_id": 0, "outcome": "success", "rationale": "The exact report was delivered.",
         "commitment_id": promise["id"], "action_round": 2}]}
    update, problems = wu.validate_arbiter_update(payload, world, strict=True)
    assert not problems and len(update["action_resolutions"]) == 2
    world.apply_arbiter_update(2, update)
    assert promise["status"] == "fulfilled"
    assert actor.last_action["resolution"] == "success"


class _Model:
    def __init__(self, *rows):
        self.rows = iter(rows)
        self.calls = []

    def chat_json(self, **kwargs):
        self.calls.append(kwargs)
        return deepcopy(next(self.rows))


def test_default_transaction_and_explicit_field_repair_keep_distinct_receipts():
    def world():
        return WorldModel.from_seed({"state_variables": [{"id": "capacity", "name": "Capacity", "value": 100}]})

    bad = {"variable_changes": [{"variable_id": "capacity", "delta": 5}], "events": "invalid"}
    good = {"variable_changes": [{"variable_id": "capacity", "delta": 5}]}
    strict_model = _Model(bad, good)
    strict = wu.run_world_round(world(), 1, None, [], [], llm=strict_model, rng=random.Random(0))
    assert strict["arbiter_status"] == "applied"
    assert [row["status"] for row in strict["arbiter_attempts"]] == ["invalid", "valid"]
    field_model = _Model(bad)
    repaired = wu.run_world_round(world(), 1, None, [], [], llm=field_model, rng=random.Random(0),
                                  arbiter_repair="field")
    assert repaired["arbiter_status"] == "applied_partial" and len(field_model.calls) == 1
    assert repaired["arbiter_raw"] == bad and repaired["arbiter_raw_attempts"] == [bad]
    assert repaired["replay"]["accepted_arbiter_update"] == repaired["arbiter_validated"]
    assert wu.replay_world_round(repaired["replay"]).to_dict() == repaired["replay"]["after"]


def test_saved_arbiter_repair_policy_wins_over_environment(monkeypatch):
    from test_world_model_loop import rps

    monkeypatch.delenv("SIM_WORLD_ARBITER_REPAIR", raising=False)
    assert rps._world_arbiter_repair() is None
    monkeypatch.setenv("SIM_WORLD_ARBITER_REPAIR", "field")
    assert rps._world_arbiter_repair() == "field"
    assert rps._world_arbiter_repair({"arbiter_repair": "atomic"}) is None
    assert rps._world_arbiter_repair({"arbiter_repair": "round"}) == "round"
    with pytest.raises(ValueError, match="field or round"):
        rps._world_arbiter_repair({"arbiter_repair": "unknown"})


def test_compatibility_raw_attempts_stay_in_private_arbiter_records(tmp_path, monkeypatch):
    from tests.test_world_paths import _run_paths

    monkeypatch.setenv("SIM_WORLD_ARBITER_REPAIR", "field")
    _run_paths(monkeypatch, tmp_path, k="2")
    private = [json.loads(line) for line in (tmp_path / "arbiter_raw.jsonl").read_text().splitlines()]
    public = [json.loads(line) for line in (tmp_path / "world_state_history.jsonl").read_text().splitlines()]
    assert private and public
    assert all(row["arbiter_raw_attempts"] and row["arbiter_raw"] == row["arbiter_raw_attempts"][-1]
               for row in private)
    assert all("arbiter_raw" not in row and "arbiter_raw_attempts" not in row for row in public)
    assert all(isinstance(attempt, dict) and "source_hash" in attempt
               for row in public for attempt in row["arbiter_attempts"])


def test_unpinned_reducer_rejection_reaches_final_admission_audit():
    world = WorldModel.from_seed({"actors": [
        {"agent_id": 0, "name": "Acme", "agency_class": "firm", "capacity_per_round": 1}]})
    world.start_round(1, None)
    actor = world.actors[0]
    raw = {"agent_id": 0, "round": 1, "status": "ok", "targets": [],
           "option": {"id": "invest_capex", "kind": "economic", "cost": 2, "lag": 2}}
    world.register_decisions(1, [raw])
    assert actor.capacity_used == 0 and actor.commitments == [] and world.relationships == {}
    assert actor.last_action["status"] == actor.action_rejections[-1]["status"] == "invalid"
    assert world.last_decision_admissions == [{"agent_id": 0, "option_id": "invest_capex", "status": "invalid",
                                              "reason": actor.action_rejections[-1]["admission_problems"][0]}]


@pytest.mark.parametrize("rollback", [False, True])
def test_anchored_arbiter_checkpoint_preserves_authority_and_rolls_back_mutations(
        tmp_path, monkeypatch, target_case, rollback):
    from app.services.agency_classification import build_agency_classifications
    from app.services.world_anchor import validate_anchor_context
    from test_agency_classification import _entity
    from test_world_anchor_reflexive import _anchored_fixture

    context, case = _anchored_fixture(tmp_path, target_case, temporal=False)
    actors = {"actors": [{"name": "Acme", "agency_class": "firm"}]}
    configs = [{"agent_id": 0, "entity_uuid": "entity-1", "entity_name": "Acme", "entity_type": "Company"}]
    seed = build_world_model_seed(actors, configs, forecast_case=case, anchor_context=context,
                                 agency_classifications=build_agency_classifications([_entity()], actors, None))
    world = WorldModel.from_seed(seed, configs, anchor_context=context)
    original = WorldModel.apply_arbiter_update
    calls = []

    def apply(current, round_num, update):
        result = original(current, round_num, update)
        calls.append(current.variables["baseline"].value)
        if rollback:
            raise RuntimeError("PRIVATE_APPLY_ERROR")
        return result

    monkeypatch.setattr(WorldModel, "apply_arbiter_update", apply)
    record = wu.run_world_round(world, 1, {"period_start": "2026-10-28", "period_end": "2026-10-31"}, [], [],
                                llm=_Model({"variable_changes": [{"variable_id": "baseline", "delta": 5}]}),
                                rng=random.Random(0))
    assert calls and calls[0] > 247.5
    assert record["arbiter_status"] == ("failed" if rollback else "applied")
    assert world.variables["baseline"].value == (247.5 if rollback else calls[0])
    assert world._anchor_context is context
    validate_anchor_context(context, engine="oasis-legacy")
    assert "PRIVATE_APPLY_ERROR" not in json.dumps(record)
    assert world.evaluate_target_projection(1, random.Random(0))["status"] == "ready"
    assert world.public_target_values()["target"] == world.variables["baseline"].value
    assert WorldModel.from_dict(world.to_dict(), anchor_context=context).to_dict() == world.to_dict()
