"""Fresh share policy seeds are independent of research probabilities; old seeds stay readable."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.services.worldstate import WorldState, build_world_state_seed
from app.services.world_model_seed import build_world_model_seed


def _case():
    return json.loads((Path(__file__).parent / "fixtures" / "target_case.json").read_text())


def _seed():
    return {"scenarios": ["Below 280", "At least 280"],
            "base_rates": {"Below 280": .93, "At least 280": .07}, "horizon_date": "2027-12-31"}


def _world(seed):
    return WorldState(seed["scenarios"], seed["base_rates"], **{k: seed[k] for k in (
        "share_prior", "share_source", "scenario_predicates", "target_node_id", "share_source_reason") if k in seed})


def test_uniform_round_zero_and_research_rollback():
    original = _seed()
    original["uniform_prior"] = False
    fresh = build_world_state_seed(original)
    assert original == {**_seed(), "uniform_prior": False}
    assert fresh["horizon_date"] == original["horizon_date"]
    assert fresh["base_rates"] == {"Below 280": .5, "At least 280": .5}
    assert _world(fresh).history[0] == fresh["base_rates"]
    assert _world(fresh).outcome()["uniform_prior"] is True
    assert fresh["uniform_prior"] is True
    assert fresh["share_source"] == "power_votes"
    research = build_world_state_seed(original, share_prior="research", share_source="votes")
    assert _world(research).shares == original["base_rates"]
    assert research["share_source_reason"] == "explicit_votes_rollback"


def test_default_seed_does_not_respond_to_research_probability_changes():
    first = _seed()
    second = _seed()
    second["base_rates"] = {"Below 280": .01, "At least 280": .99}
    assert build_world_state_seed(first) == build_world_state_seed(second)


def test_typed_model_and_classifier_projection_ignore_changed_assessment_weights():
    original = _case()
    changed = deepcopy(original)
    changed["assessments"][0]["scenarioWeights"] = {"below": .8, "above": .2}
    changed["assessments"][1]["scenarioWeights"] = {"below": .7, "above": .3}
    for row in changed["assessments"][1]["updates"]:
        row["oldWeight"] = changed["assessments"][0]["scenarioWeights"][row["scenarioId"]]
        row["newWeight"] = changed["assessments"][1]["scenarioWeights"][row["scenarioId"]]
    assert build_world_model_seed({}, [], forecast_case=original) == build_world_model_seed({}, [], forecast_case=changed)
    assert build_world_state_seed(_seed(), forecast_case=original) == build_world_state_seed(_seed(), forecast_case=changed)


def test_auto_requires_typed_identity_and_exact_scenario_binding():
    case = _case()
    seed = build_world_state_seed(_seed(), forecast_case=case, share_source="auto")
    assert seed["share_source"] == "predicates"
    assert seed["target_node_id"] == "spending"
    assert seed["scenario_predicates"]["Below 280"] == case["scenarios"][0]["predicate"]
    wrong = _seed()
    wrong["scenarios"] = ["unrelated", "At least 280"]
    declined = build_world_state_seed(wrong, forecast_case=case)
    assert declined["share_source"] == "power_votes"
    assert declined["share_source_reason"] == "invalid_target_predicates"
    assert "scenario_predicates" not in declined


def test_explicit_predicates_missing_identity_freezes_and_does_not_fallback():
    seed = build_world_state_seed(_seed(), share_source="predicates")
    assert seed["share_source"] == "predicates"
    world = _world(seed)
    before = dict(world.shares)
    world.step_from_source([{"agent_id": 1, "scenario": "Below 280"}], weight_by_agent={1: 10}, resolutions={1: "success"})
    assert world.shares == before
    assert world.last_share_update["reason"] == "invalid_target_predicates"


def test_private_target_cannot_select_auto_predicates():
    case = _case()
    case["nodes"][-1].update(visibility="private", ownerActorId="vendor")
    case["actors"][0]["information"]["nodeIds"].remove("spending")
    case["actors"][0]["objectives"][0]["nodeId"] = "regulation"
    seed = build_world_state_seed(_seed(), forecast_case=case)
    model = build_world_model_seed({}, [], forecast_case=case)
    assert seed["share_source"] == "power_votes"
    assert seed["share_source_reason"] == model["target_projection_reason"] == "private_target_unavailable"
    assert "target_projection" not in model
    assert "scenario_predicates" not in seed


def test_target_first_seed_contains_identity_without_actor_probabilities_or_private_nodes():
    case = _case()
    original = deepcopy(case)
    seed = build_world_model_seed({}, [], forecast_case=case, max_variables=1)
    assert case == original
    rows = seed["state_variables"]
    assert rows[0]["id"] == "spending"
    assert rows[0]["read_only"] is True
    assert rows[0]["identity"] == {"mechanismId": "spending-growth", "kind": "growth", "inputs": ["base", "growth"], "parameters": {}}
    assert "ai" not in {r["id"] for r in rows}
    assert "ai" in {n["nodeId"] for n in seed["target_projection"]["nodes"]}
    assert len(rows) > 1  # incidental fact cap must not truncate a typed DAG
    blob = json.dumps({"state_variables": rows, "target_projection": seed["target_projection"]})
    for forbidden in ("scenarioWeights", "assessments", "probability", "sourceIds", "The synthetic 2026"):
        assert forbidden not in blob


def test_missing_identity_never_infers_a_fake_target_from_quantitative_facts():
    actors = {"quantitative_facts": [{"metric": "incidental capex", "value": "US$3 billion"}]}
    seed = build_world_model_seed(actors, [])
    assert "target_projection" not in seed
    assert [row["id"] for row in seed["state_variables"]] == ["incidental_capex"]
    case = _case()
    case["mechanisms"] = case["mechanisms"][:1]
    case["nodes"][-1].update(basis="assumed", gap="No target identity in this regression fixture.")
    declined = build_world_model_seed(actors, [], forecast_case=case)
    assert "target_projection" not in declined
    assert declined["target_projection_reason"] == "missing_target_identity"


def test_expression_code_is_not_an_identity():
    case = _case()
    case["mechanisms"][-1]["expression"] = "__import__('os').system('false')"
    declined = build_world_model_seed({}, [], forecast_case=case)
    assert "target_projection" not in declined
    assert declined["target_projection_reason"] == "invalid_forecast_case"


def test_generic_power_is_not_promoted_to_declared_outcome_power():
    actors = {"actors": [{"name": "Alpha", "type": "Organization", "power": 9, "influence": "high"}]}
    configs = [{"agent_id": 1, "entity_name": "Alpha", "power": 8}]
    assert build_world_model_seed(actors, configs)["actors"][0]["outcome_power"] == 8
    assert build_world_model_seed(actors, configs, share_source="votes")["actors"][0]["outcome_power"] == 8
    seed = build_world_model_seed(actors, configs, share_source="power_votes")
    assert seed["actors"][0]["outcome_power"] is None
    actors["actors"][0]["outcome_power"] = 2
    seed = build_world_model_seed(actors, configs, share_source="auto")
    assert seed["actors"][0]["outcome_power"] == 2


def test_seed_copy_drops_stale_predicate_metadata_without_typed_case():
    seed = build_world_state_seed(_seed(), forecast_case=_case())
    rebuilt = build_world_state_seed(seed)
    assert rebuilt["share_source"] == "power_votes"
    assert "scenario_predicates" not in rebuilt and "target_node_id" not in rebuilt


@pytest.mark.parametrize("kwargs", [{"share_prior": "guess"}, {"share_source": "guess"}])
def test_policy_configuration_rejects_unknown_enum(kwargs):
    with pytest.raises(ValueError):
        build_world_state_seed(_seed(), **kwargs)
