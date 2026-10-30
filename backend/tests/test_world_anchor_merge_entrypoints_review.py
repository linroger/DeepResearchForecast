"""R2/R3 regressions at actual decision and coordinator admission boundaries."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys

import pytest

from app.services import agent_decision as ad
from app.services.world_model import WorldModel
from test_world_model_loop import _patch_world, _world_config, rps


@pytest.fixture(autouse=True)
def source_pins():
    guard = sys.modules.get("main_offline_guard")
    if guard is not None:
        root = Path(__file__).resolve().parents[2]
        for name in ("backend/app/services/agent_decision.py", "backend/scripts/run_parallel_simulation.py",
                     "backend/app/services/world_model.py"):
            path = root / name
            guard.source_hashes.setdefault(str(path), hashlib.sha256(path.read_bytes()).hexdigest())


def _cast(kind="name"):
    names = ["Mediator", "Mediator"] if kind == "name" else ["Eastern Office", "Western Office"]
    aliases = [["East unique", "Shared Office"], ["West unique", "Shared Office"]]
    world = WorldModel.from_seed({"actors": [
        {"agent_id": 0, "name": "Delegation", "agency_class": "firm", "capacity_per_round": 3},
        *[{"agent_id": aid, "name": name, "agency_class": "firm", "aliases": aliases[aid - 1]}
          for aid, name in enumerate(names, 1)]]})
    world.start_round(1, {"label": "P1"})
    return world


def _move(world, target):
    return ad.parse_decision({"option_id": "open_talks", "targets": [target],
                              "public_statement": "We propose technical talks."},
                             actor=world.actors[0], world=world,
                             options=ad.build_option_menu(world.actors[0], world, 1, max_options=512),
                             scenarios=[], round_num=1)


@pytest.mark.parametrize("kind,target", [("name", "Mediator"), ("alias", "Shared Office"),
                                         ("alias", "Office")])
def test_ambiguous_actor_claim_is_rejected_without_economic_mutation(kind, target):
    world = _cast(kind)
    actor = world.actors[0]
    decision = _move(world, target)
    world.register_decisions(1, [decision.to_dict()])
    assert not decision.ok and decision.status == "invalid"
    assert actor.capacity_used == 0 and actor.commitments == []
    assert world.interactions == {} and world.relationships == {}
    assert actor.last_action["status"] == actor.action_rejections[-1]["status"] == "invalid"
    assert world.last_decision_admissions[-1]["status"] == "invalid"


@pytest.mark.parametrize("target,expected", [(1, 1), (2, 2), ("West unique", 2)])
def test_explicit_identity_reaches_intended_duplicate_named_actor(target, expected):
    world = _cast()
    decision = _move(world, target)
    assert decision.ok and decision.targets == [expected]
    world.register_decisions(1, [decision.to_dict()])
    assert world.actors[0].capacity_used == 1
    assert len(world.interactions) == 1
    interaction = next(iter(world.interactions.values()))
    assert interaction.proposer == 0 and interaction.recipient == expected


@pytest.mark.parametrize("saved,expected", [("atomic", None), ("field", "field"), ("round", "round")])
def test_real_coordinator_saved_policy_precedes_invalid_environment(tmp_path, monkeypatch, saved, expected):
    _patch_world(monkeypatch, str(tmp_path), [])
    config = _world_config()
    config["world_model"]["settings"]["arbiter_repair"] = saved
    monkeypatch.setenv("SIM_WORLD_ARBITER_REPAIR", "invalid-ambient-policy")
    messages = []
    coordinator = rps._get_world_coordinator(config, str(tmp_path), 1, messages.append, resume=False)
    assert coordinator is not None and coordinator._arbiter_repair == expected
    assert rps._get_world_coordinator(config, str(tmp_path), 1, messages.append, resume=True) is coordinator
    assert not any("falling back" in message for message in messages)


@pytest.mark.parametrize("invalid", ["invalid-saved-policy", None, "", 4, {}, []])
def test_invalid_saved_policy_refuses_before_artifact_cleanup(tmp_path, monkeypatch, invalid):
    _patch_world(monkeypatch, str(tmp_path), [])
    config = _world_config()
    config["world_model"]["settings"]["arbiter_repair"] = deepcopy(invalid)
    monkeypatch.setenv("SIM_WORLD_ARBITER_REPAIR", "atomic")
    artifacts = {name: ("SAVED:" + name).encode() for name in (
        rps.WORLD_STATE_FILE, rps.WORLD_HISTORY_FILE, rps.WORLD_ACTIONS_FILE, rps.ARBITER_RAW_FILE,
        "world_digest.jsonl", "world_state_trajectory.json", "decisions.jsonl", "world_paths.json")}
    for name, payload in artifacts.items():
        (tmp_path / name).write_bytes(payload)
    messages = []
    error = None
    try:
        rps._get_world_coordinator(config, str(tmp_path), 1, messages.append, resume=False)
    except ValueError as exc:
        error = exc
    after = {name: (tmp_path / name).read_bytes() for name in artifacts if (tmp_path / name).exists()}
    assert after == artifacts, "invalid saved policy reached destructive fresh-run cleanup"
    assert error is not None and "SIM_WORLD_ARBITER_REPAIR" in str(error)
    assert not any("falling back" in message for message in messages)
    assert str(tmp_path.resolve()) not in rps._WORLD_COORDINATORS
