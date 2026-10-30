"""Legacy share policy: typed target facts outrank votes; unavailable inputs freeze."""
import json
from pathlib import Path
import shutil

import pytest

from app.services.worldstate import WorldState, commitments_from_decisions, pressure_commitments


PREDICATES = {"X": {"nodeId": "target", "operator": "lt", "value": 100},
              "Y": {"nodeId": "target", "operator": "gte", "value": 100}}
VOTES = [{"agent_id": 1, "scenario": "X", "magnitude": 1, "confidence": 1},
         {"agent_id": 2, "scenario": "X", "magnitude": 1, "confidence": 1}]


def _state(source="predicates", **kwargs):
    return WorldState(["X", "Y"], {"X": .9, "Y": .1}, share_prior="uniform",
                      share_source=source, target_node_id="target", scenario_predicates=PREDICATES, **kwargs)


def test_unanimous_x_votes_follow_target_y_with_existing_inertia():
    state = _state()
    state.step_from_source(VOTES, target_values={"target": 120}, round_status="missing", entropy_mix_days=365)
    assert state.shares == {"X": .35, "Y": .65}
    assert state.outcome()["share_update_reason"] == "target_predicate_mass"
    assert state.round_statuses == ["committed"]


def test_k_target_outcomes_classify_mass_once():
    state = _state(inertia=0)
    state.step_from_source(VOTES, target_values=[{"target": 90}, {"target": 100}, {"target": 110}, {"target": 120}])
    assert state.shares == {"X": .25, "Y": .75}
    assert state.last_share_update["paths"] == 4


@pytest.mark.parametrize("target", [None, {}, [], {"target": None}, {"target": True}, {"target": float("nan")},
                                    [{"target": 110}, {}]])
def test_unavailable_target_never_falls_back_to_votes(target):
    state = _state(inertia=0)
    state.step_from_source(VOTES, weight_by_agent={1: 100, 2: 100}, resolutions={1: "success", 2: "success"},
                           target_values=target, target_reason="model_unavailable")
    assert state.shares == {"X": .5, "Y": .5}
    assert state.last_share_update["reason"] == "target_unavailable"
    assert state._ewma_delta == 1


def test_predicate_overlap_or_missing_target_identity_declines():
    for predicates in ({}, {"X": PREDICATES["Y"], "Y": PREDICATES["Y"]},
                       {"X": {"nodeId": "other", "operator": "lt", "value": 100}, "Y": PREDICATES["Y"]}):
        state = _state()
        state.scenario_predicates = predicates
        state.step_from_source(VOTES, target_values={"target": 120})
        assert state.shares == {"X": .5, "Y": .5}
        assert state.last_share_update["reason"] == "invalid_target_predicates"


def test_unmatched_path_is_not_discarded_or_renormalized():
    state = _state()
    state.scenario_predicates["Y"] = {"nodeId": "target", "operator": "gt", "value": 100}
    state.step_from_source(VOTES, target_values=[{"target": 110}, {"target": 100}])
    assert state.shares == {"X": .5, "Y": .5}
    assert state.last_share_update["reason"] == "target_outside_scenario_partition"


@pytest.mark.parametrize("power", [None, "1", True, -1, float("inf"), float("nan")])
def test_unknown_power_abstains_and_freezes_ewma_despite_self_declared_power(power):
    state = _state("power_votes")
    for _ in range(12):
        state.step_from_source([{**VOTES[0], "outcome_power": 999}], weight_by_agent={1: power},
                               resolutions={1: "success"}, entropy_mix_days=365, round_status="committed")
    assert state.shares == {"X": .5, "Y": .5}
    assert state.last_share_update["reason"] == "unknown_power"
    assert not state.converged()
    assert state._ewma_delta == 1
    assert state.round_accounting()["valid_transitions"] == 0


def test_only_trusted_declared_power_and_resolutions_count():
    votes = [VOTES[0], {**VOTES[1], "scenario": "Y", "outcome_power": 999}]
    state = _state("power_votes", inertia=0)
    state.step_from_source(votes, weight_by_agent={1: 2, 2: 2}, resolutions={1: "partial", 2: "success"})
    assert state.shares == {"X": .333333, "Y": .666667}
    assert state.last_share_update["reason"] == "resolved_declared_power"


@pytest.mark.parametrize("magnitude, expected", [(0, 0), (.01, .009901)])
def test_small_magnitudes_are_not_floored(magnitude, expected):
    state = _state("power_votes", inertia=0)
    state.step_from_source([{**VOTES[0], "magnitude": magnitude}, {**VOTES[1], "scenario": "Y"}],
                           weight_by_agent={1: 1, 2: 1}, resolutions={1: "success", 2: "success"})
    assert state.shares["X"] == expected


@pytest.mark.parametrize("resolution, reason", [("blocked", "zero_effect"), ("failed", "zero_effect"),
                                                  ("pending", "zero_effect"), (None, "unknown_resolution")])
def test_blocked_failed_pending_or_missing_resolution_adds_no_power(resolution, reason):
    state = _state("power_votes", inertia=0)
    state.step_from_source(VOTES[:1], weight_by_agent={1: 5}, resolutions={1: resolution})
    assert state.shares == {"X": .5, "Y": .5}
    assert state.last_share_update["reason"] == reason


def test_invalid_actor_round_cannot_become_convergence_signal():
    state = _state("power_votes")
    state.step_from_source(VOTES, weight_by_agent={1: 1, 2: 1}, resolutions={1: "success", 2: "success"},
                           round_status="failed")
    assert state._ewma_delta == 1 and state.shares == {"X": .5, "Y": .5}
    assert state.last_share_update["reason"] == "invalid_round_status"
    assert state.round_accounting()["failed_rounds"] == 1


def test_failure_after_settled_shares_remains_inconclusive():
    state = _state("power_votes")
    balanced = [VOTES[0], {**VOTES[1], "scenario": "Y"}]
    for _ in range(6):
        state.step_from_source(balanced, weight_by_agent={1: 1, 2: 1},
                               resolutions={1: "success", 2: "success"}, round_status="committed")
    assert state.converged()
    state.step_from_source(balanced, weight_by_agent={1: 1, 2: 1},
                           resolutions={1: "success", 2: "success"}, round_status="failed")
    assert state.round_accounting()["failed_rounds"] == 1
    assert state.convergence_state() == "inconclusive"


def test_absent_trusted_power_map_does_not_use_decision_claims():
    state = _state("power_votes")
    state.step_from_source([{**VOTES[0], "outcome_power": 1}], resolutions={1: "success"})
    assert state.last_share_update["reason"] == "unknown_power"


def test_original_vote_trajectory_and_outcome_are_byte_identical_without_policy():
    direct = WorldState(["X", "Y"], {"X": .8, "Y": .2})
    adapter = WorldState(["X", "Y"], {"X": .8, "Y": .2})
    for status in ("committed", "abstained", "silent", "failed", "committed"):
        direct.step(commitments_from_decisions(VOTES), round_status=status, entropy_mix_days=30)
        adapter.step_from_source(VOTES, round_status=status, entropy_mix_days=30)
    assert json.dumps(direct.outcome()) == json.dumps(adapter.outcome())
    assert direct.history == adapter.history
    assert "share_source" not in adapter.outcome()


def test_explicit_votes_rollback_keeps_original_pressure_calculation():
    old = WorldState(["X", "Y"], {"X": .8, "Y": .2})
    rollback = WorldState(["X", "Y"], {"X": .8, "Y": .2}, share_source="votes", share_prior="research")
    for _ in range(5):
        commitments = commitments_from_decisions(VOTES)
        commitments += pressure_commitments({"Y": "up"}, old.shares, 2, weight_ratio=.35)
        old.step(commitments, entropy_mix_days=90)
        rollback.step(commitments, entropy_mix_days=90)
    policy_keys = {"share_prior", "share_source", "share_source_reason", "share_update_reason", "share_update"}
    assert json.dumps(old.outcome()) == json.dumps({k: v for k, v in rollback.outcome().items() if k not in policy_keys})
    assert old.history == rollback.history


def test_record_preserves_source_and_explains_uniform_unknown_power(tmp_path):
    from app.services import simulation_record as sr
    from app.services import simulation_record_contract as rc
    source = Path(__file__).parent / "fixtures" / "sim_record" / "reflexive3"
    dest = tmp_path / "sim_shares"
    shutil.copytree(source, dest)
    trajectory_path = dest / "world_state_trajectory.json"
    trajectory = json.loads(trajectory_path.read_text())
    trajectory["outcome"].update(share_prior="uniform", share_source="power_votes",
                                 share_source_reason="missing_forecast_case", share_update_reason="unknown_power")
    trajectory_path.write_text(json.dumps(trajectory))
    record = sr.build_record(str(dest), language="English", synthesis=False)
    assert rc.validate_shape(record) == []
    assert record["overall"]["shares"]["share_source"] == "power_votes"
    markdown = sr.render_markdown(record)
    assert "Shares started uniform; the research prior was not used." in markdown
    assert "Shares froze because outcome power was unknown." in markdown
    assert "未使用研究先验" in sr.share_policy_note(record["overall"]["shares"], "zh")
    assert sr.share_policy_note({}) == ""


def test_real_world_loop_unknown_power_freezes_and_records_reason(tmp_path, monkeypatch):
    from test_calendar_round_loop import _run
    from test_world_model_loop import _patch_world, _world_config
    from app.services.worldstate import build_world_state_seed
    config = _world_config()
    config["world_state_seed"] = build_world_state_seed(config["world_state_seed"])
    _patch_world(monkeypatch, str(tmp_path), [])
    _run(config, str(tmp_path))
    trajectory = json.loads((tmp_path / "world_state_trajectory.json").read_text())
    assert trajectory["trajectory"][0]["shares"] == {"A": .5, "B": .5}
    assert all(row["shares"] == {"A": .5, "B": .5} for row in trajectory["trajectory"])
    assert trajectory["outcome"]["share_source"] == "power_votes"
    assert trajectory["outcome"]["share_update_reason"] == "unknown_power"
    assert not trajectory["outcome"]["converged"]


def test_real_world_loop_votes_a_target_b_uses_propagated_identity(tmp_path, monkeypatch):
    from test_calendar_round_loop import _run
    from test_world_model_loop import _WorldLLM, _patch_world, _world_config
    from app.services.worldstate import build_world_state_seed
    from app.services.world_model_seed import build_world_model_seed
    case = json.loads((Path(__file__).parent / "fixtures" / "target_case.json").read_text())
    case["scenarios"][0]["label"], case["scenarios"][1]["label"] = "A", "B"
    config = _world_config()
    config["world_state_seed"] = build_world_state_seed(config["world_state_seed"], forecast_case=case)
    typed_seed = build_world_model_seed({}, [], forecast_case=case)
    for key in ("target_projection", "target_projection_reason", "state_variables"):
        config["world_model"][key] = typed_seed[key]
    _patch_world(monkeypatch, str(tmp_path), [])
    _run(config, str(tmp_path))
    trajectory = json.loads((tmp_path / "world_state_trajectory.json").read_text())
    assert trajectory["outcome"]["share_source"] == "predicates"
    assert trajectory["outcome"]["share_update_reason"] == "target_predicate_mass"
    assert trajectory["outcome"]["shares"]["B"] > trajectory["outcome"]["shares"]["A"]
    rows = [json.loads(line) for line in (tmp_path / "world_actions.jsonl").read_text().splitlines()]
    assert any(row.get("scenario") == "A" for row in rows)
    assert all(row.get("scenario") in (None, "abstain", "A") for row in rows)
    prompts = "\n".join(row["content"] for row in _WorldLLM.calls if row["kind"] == "decision")
    assert "AI segment contribution" not in prompts and "scenarioWeights" not in prompts
