"""Public-contract scenarios for the target-first structural simulator.

Fixtures are synthetic except the explicitly identified copied publisher-vintage rows. Run through main_offline_pytest.py so imports,
fixtures, and callbacks stay inside the project's offline audit boundary.
"""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import random
import sys

import pytest

from app.services.target_mechanisms import MechanismValidationError
from app.services.target_simulation import (
    SimulationCancelled,
    actor_observation,
    run_paths as runtime_run_paths,
)


def run_paths(case, **kwargs):
    """Keep literal-ID legacy scenarios explicit; new tests use the public default."""
    kwargs.setdefault("identity_mode", "named")
    return runtime_run_paths(case, **kwargs)


def _node(node_id, value, *, units="units", private_owner=None):
    node = {
        "nodeId": node_id, "label": f"Synthetic {node_id}", "units": units,
        "status": "settled", "value": value,
        "range": {"low": value, "high": value}, "vintage": "2026-10-26",
        "sourceIds": ["S1"], "claimIds": [], "sensitivity": 1.0,
        "evidenceAvailability": 1.0, "retrievalCost": 1.0, "pivotal": True,
        "visibility": "private" if private_owner else "public",
    }
    if private_owner:
        node["ownerActorId"] = private_owner
    return node


def _actor(actor_id="a", *, node_id="rate", kind="llm", capacity=10.0,
           cadence=1, lag=0, cost=1.0, reversible=True, release_lag=0):
    return {
        "actorId": actor_id, "name": f"Synthetic actor {actor_id}",
        "decisionBasis": "Synthetic documented control; not real evidence.",
        "objectives": [{"nodeId": "target", "direction": "increase", "weight": 1.0}],
        "constraints": {"capacity": capacity},
        "levers": [{"leverId": f"{actor_id}-lever", "nodeId": node_id,
                    "minimum": 0.0, "maximum": 1.0, "cost": cost,
                    "lagPeriods": lag, "reversible": reversible,
                    "requiresConsent": []}],
        "decisionRule": {"kind": kind, "cadencePeriods": cadence, "triggers": []},
        "plans": [], "information": {"nodeIds": ["base", "rate", "target"],
                                      "releaseLagPeriods": release_lag},
        "credibility": 0.75,
    }


def _action(value, actor_id="a", **extra):
    return {"actorId": actor_id, "leverId": f"{actor_id}-lever", "value": value, **extra}


def _by_node(case, node_id):
    return next(node for node in case["nodes"] if node["nodeId"] == node_id)


def _values(path, node_id="rate"):
    return [row["values"][node_id] for row in path["trajectory"]]


def _uncertain(case):
    node = _by_node(case, "rate")
    node.update(status="unknown", value=None, range={"low": 0.05, "high": 0.15},
                vintage=None, sourceIds=[], claimIds=[], evidenceAvailability=0.0,
                basis="assumed", gap="Synthetic bounded rate; no observed evidence.")
    case["claims"] = [claim for claim in case["claims"] if claim["nodeId"] != "rate"]
    return case


@pytest.fixture
def case():
    """Complete frozen schema, with a fixed two-input growth mechanism."""
    nodes = [_node("base", 100.0), _node("rate", 0.1, units="fraction"),
             _node("target", 110.0)]
    nodes[0]["claimIds"] = ["C1"]
    nodes[1]["claimIds"] = ["C2"]
    nodes[2].update(status="unknown", value=None, range={"low": 0.0, "high": 1000.0},
                    vintage=None, sourceIds=[], evidenceAvailability=0.0)
    return {
        "schemaVersion": "forecast-case/v1", "caseId": "synthetic-growth",
        "question": "What is the synthetic terminal output?", "asOf": "2026-10-27",
        "revision": 1, "authority": "target-first-v1",
        "resolution": {"targetNodeId": "target", "horizon": "2027-10-27",
                       "settlementSource": {"name": "Synthetic settlement release",
                                            "url": "https://example.test/settlement",
                                            "releaseLagDays": 7},
                       "units": "units", "comparatorPolicy": "Use the first release."},
        "nodes": nodes,
        "sources": [{"sourceId": "S1", "url": "https://example.test/evidence",
                     "title": "Synthetic fixture evidence, not a real observation",
                     "publishedAt": "2026-10-26", "retrievedAt": "2026-10-27T00:00:00Z",
                     "originCluster": "synthetic", "tier": "primary", "fetched": True,
                     "passage": "Synthetic base 100. Synthetic reference rate 0.1."}],
        "claims": [{"claimId": "C1", "nodeId": "base", "sourceIds": ["S1"],
                    "passage": "Synthetic base 100.", "status": "verified"},
                   {"claimId": "C2", "nodeId": "rate", "sourceIds": ["S1"],
                    "passage": "Synthetic reference rate 0.1.", "status": "verified"}],
        "mechanisms": [{"mechanismId": "growth", "kind": "growth",
                        "outputNodeId": "target", "inputNodeIds": ["base", "rate"],
                        "parameters": {}, "basis": "assumed", "sourceIds": [],
                        "gap": "Synthetic one-step structural relationship."}],
        "actors": [],
        "scenarios": [{"scenarioId": "low", "label": "Below 105",
                       "predicate": {"nodeId": "target", "operator": "lt", "value": 105.0}},
                      {"scenarioId": "high", "label": "At least 115",
                       "predicate": {"nodeId": "target", "operator": "gte", "value": 115.0}}],
        "assessments": [{"assessmentId": "prior-1", "version": 1, "kind": "prior",
                         "scenarioWeights": {"low": 0.2, "high": 0.3, "other": 0.5},
                         "targetDistribution": {"mean": 110.0}, "updates": []}],
        "binaries": [{"binaryId": "B1", "question": "Is the output at least 115?",
                      "predicate": {"nodeId": "target", "operator": "gte", "value": 115.0},
                      "probability": 0.3, "sourceIds": ["S1"]}],
    }


def test_fixed_growth_and_explicit_unmatched_mass(case):
    result = run_paths(case, paths=3, periods=4, seed=7)
    assert result["schemaVersion"] == "target-simulation/v1"
    assert result["caseId"] == case["caseId"]
    assert result["seed"] == 7
    assert len(result["caseHash"]) == 64
    assert result["simulationWeight"] == 0.0
    assert len(result["paths"]) == 3
    assert len({path["pathId"] for path in result["paths"]}) == 3
    for path in result["paths"]:
        assert [row["period"] for row in path["trajectory"]] == list(range(5))
        assert _values(path, "target") == pytest.approx([110.0] * 5)
        assert path["targetValue"] == pytest.approx(110.0)
        assert path["decisions"] == []
    assert result["scenarioShares"] == {"low": 0.0, "high": 0.0, "other": 1.0}
    assert isinstance(result["baseline"], dict)
    assert isinstance(result["replay"], dict)
    assert {"targetSummary", "sensitivity", "signposts"} <= result.keys()
    json.dumps(result, allow_nan=False)


def test_seeded_replay_is_exact_and_preserves_case_and_global_rng(case):
    _uncertain(case)
    before, rng_state = deepcopy(case), random.getstate()
    first = run_paths(case, paths=12, periods=3, seed=19)
    second = run_paths(case, paths=12, periods=3, seed=19)
    assert first == second
    assert case == before
    assert random.getstate() == rng_state
    rates = [_values(path)[0] for path in first["paths"]]
    assert all(0.05 <= value <= 0.15 for value in rates)
    assert len(set(rates)) > 1
    for path in first["paths"]:
        assert _values(path) == [_values(path)[0]] * 4
    changed_seed = run_paths(case, paths=12, periods=3, seed=20)
    assert [_values(path) for path in changed_seed["paths"]] != [
        _values(path) for path in first["paths"]]


def test_lagged_action_changes_only_the_effective_period_and_later(case):
    case["actors"] = [_actor(lag=2, cadence=99)]
    calls = []

    def decide(observation):
        calls.append(deepcopy(observation))
        return _action(0.4)

    result = run_paths(case, paths=1, periods=5, decision_provider=decide)
    path = result["paths"][0]
    assert [call["period"] for call in calls] == [1]
    assert _values(path) == pytest.approx([0.1, 0.1, 0.1, 0.4, 0.4, 0.4])
    assert _values(path, "target") == pytest.approx([110, 110, 110, 140, 140, 140])
    assert _values(result["baseline"]) == pytest.approx([0.1] * 6)
    assert result["baseline"]["decisions"] == []
    assert all({"period", "actorId", "leverId", "value", "status", "reason"} <= row.keys()
               for row in path["decisions"])


@pytest.mark.parametrize("attack", ["impersonate", "foreign-lever", "unknown-lever"])
def test_callback_cannot_exercise_another_actors_rights(case, attack):
    case["nodes"].append(_node("b-private", 0.2, private_owner="b"))
    other = _actor("b", node_id="b-private")
    other["information"]["nodeIds"].append("b-private")
    case["actors"] = [_actor(), other]

    def decide(observation):
        if observation["actorId"] != "a":
            return []
        if attack == "impersonate":
            return _action(0.8, "b")
        return _action(0.8, leverId="b-lever" if attack == "foreign-lever" else "missing")

    result = run_paths(case, paths=1, periods=2, decision_provider=decide)
    path = result["paths"][0]
    assert _values(path) == pytest.approx([0.1] * 3)
    assert _values(path, "b-private") == pytest.approx([0.2] * 3)
    assert path["decisions"]
    assert all(row["status"] == "blocked" and row["reason"] for row in path["decisions"])


@pytest.mark.parametrize(("kind", "inputs", "parameters", "expected"), [
    ("sum", ["base", "rate"], {}, [100.1] * 4),
    ("product", ["base", "rate"], {}, [10.0] * 4),
    ("linear", ["base", "rate"], {"coefficients": [2.0, -10.0], "intercept": 3.0}, [202.0] * 4),
    ("supply_demand", ["rate", "base"], {}, [99.9] * 4),
    ("adoption", ["rate", "base"], {"rate": 0.2}, [20.08] * 4),
    ("regulatory_milestone", [], {"milestonePeriod": 2, "before": 0.0, "after": 1.0},
     [0.0, 0.0, 1.0, 1.0]),
])
def test_whitelisted_templates_through_public_runtime(case, kind, inputs, parameters, expected):
    case["mechanisms"][0].update(kind=kind, inputNodeIds=inputs, parameters=parameters)
    result = run_paths(case, paths=2, periods=3)
    for path in result["paths"]:
        assert _values(path, "target") == pytest.approx(expected)
        assert path["targetValue"] == pytest.approx(expected[-1])


def test_dag_propagates_dependencies_independently_of_mechanism_row_order(case):
    intermediate = deepcopy(_by_node(case, "target"))
    intermediate.update(nodeId="intermediate", label="Synthetic intermediate")
    case["nodes"].append(intermediate)
    upstream = deepcopy(case["mechanisms"][0])
    upstream.update(mechanismId="upstream", outputNodeId="intermediate")
    case["mechanisms"][0].update(kind="sum", inputNodeIds=["intermediate", "base"])
    case["mechanisms"].append(upstream)  # Deliberately reverse topological order.
    first = run_paths(case, paths=2, periods=2, seed=9)
    reordered = deepcopy(case)
    reordered["mechanisms"].reverse()
    second = run_paths(reordered, paths=2, periods=2, seed=9)
    assert [p["trajectory"] for p in first["paths"]] == [p["trajectory"] for p in second["paths"]]
    assert _values(first["paths"][0], "target") == pytest.approx([210.0] * 3)


@pytest.mark.parametrize("bounded_key", ["coefficient", "intercept"])
def test_bounded_parameter_is_drawn_once_and_has_numeric_sensitivity(case, bounded_key):
    prior = {"low": 1.0, "high": 3.0, "basis": "assumed", "gap": "Synthetic prior."}
    parameters = {"coefficients": [deepcopy(prior) if bounded_key == "coefficient" else 1.0],
                  "intercept": deepcopy(prior) if bounded_key == "intercept" else 0.0}
    case["mechanisms"][0].update(kind="linear", inputNodeIds=["base"], parameters=parameters)
    result = run_paths(case, paths=8, periods=4, seed=91)
    targets = [p["targetValue"] for p in result["paths"]]
    assert len(set(targets)) > 1
    bounds = (100.0, 300.0) if bounded_key == "coefficient" else (101.0, 103.0)
    for path in result["paths"]:
        assert bounds[0] <= path["targetValue"] <= bounds[1]
        assert _values(path, "target") == [path["targetValue"]] * 5
    expected_key = "coefficient:base" if bounded_key == "coefficient" else "intercept"
    contrast = next(row for row in result["sensitivity"]
                    if row.get("parameter") == expected_key)
    assert contrast["targetAtLow"] == pytest.approx(bounds[0])
    assert contrast["targetAtHigh"] == pytest.approx(bounds[1])
    assert contrast["targetDelta"] == pytest.approx(bounds[1] - bounds[0])
    assert result["parameterBases"]


def test_parameter_prior_cannot_silently_ignore_an_explicit_value(case):
    case["mechanisms"][0].update(kind="adoption", inputNodeIds=["rate", "base"],
        parameters={"rate": {"low": 0.1, "high": 0.2, "value": 0.15,
                             "basis": "assumed", "gap": "Synthetic prior."}})
    with pytest.raises(ValueError):
        run_paths(case, paths=1, periods=1)


def test_capacity_is_cumulative_and_charged_on_absolute_delta(case):
    case["actors"] = [_actor(capacity=0.7, cost=2.0)]

    def decide(observation):
        return _action({1: 0.3, 2: 0.2, 3: 0.4}[observation["period"]])

    path = run_paths(case, paths=1, periods=3, decision_provider=decide)["paths"][0]
    # First increase costs .4, reversal costs .2, leaving .1: final .4 cost fails.
    assert _values(path) == pytest.approx([0.1, 0.3, 0.2, 0.2])
    assert path["decisions"][-1]["status"] == "blocked"
    assert path["decisions"][-1]["reason"] == "capacity"


@pytest.mark.parametrize(("capacity", "allowed"), [(0.25, True), (0.249, False)])
def test_capacity_boundary_is_exact(case, capacity, allowed):
    _by_node(case, "rate").update(value=0.0, range={"low": 0.0, "high": 0.0},
                                 status="contested", claimIds=[])
    case["claims"] = [claim for claim in case["claims"] if claim["nodeId"] != "rate"]
    case["actors"] = [_actor(capacity=capacity)]
    path = run_paths(case, paths=1, periods=1, decision_provider=lambda observation: _action(0.25))["paths"][0]
    assert _values(path)[-1] == pytest.approx(0.25 if allowed else 0.0)


def test_multiple_actions_share_one_capacity_budget(case):
    case["actors"] = [_actor(capacity=0.35)]
    second = deepcopy(case["actors"][0]["levers"][0])
    second.update(leverId="base-lever", nodeId="base", minimum=100.0, maximum=101.0)
    case["actors"][0]["levers"].append(second)
    path = run_paths(case, paths=1, periods=1,
                     decision_provider=lambda observation: [
                         _action(0.3), _action(100.2, leverId="base-lever")])["paths"][0]
    assert _values(path) == pytest.approx([0.1, 0.3])
    assert _values(path, "base") == pytest.approx([100.0, 100.0])
    assert any(row["status"] == "blocked" for row in path["decisions"])


@pytest.mark.parametrize("reversible", [False, True])
def test_irreversible_lever_cannot_reverse_an_accepted_direction(case, reversible):
    case["actors"] = [_actor(reversible=reversible)]
    path = run_paths(case, paths=1, periods=3, decision_provider=lambda observation:
                     _action({1: 0.4, 2: 0.2, 3: 0.5}[observation["period"]]))["paths"][0]
    assert _values(path) == pytest.approx([0.1, 0.4, 0.2 if reversible else 0.4, 0.5])
    if not reversible:
        assert any(row["reason"] == "irreversible" for row in path["decisions"])


def test_pending_lag_does_not_allow_double_spending_or_overwrite(case):
    case["actors"] = [_actor(lag=2, capacity=0.31)]
    path = run_paths(case, paths=1, periods=3, decision_provider=lambda observation:
                     _action(0.4 if observation["period"] == 1 else 0.8))["paths"][0]
    assert _values(path) == pytest.approx([0.1, 0.1, 0.1, 0.4])
    assert path["targetValue"] == pytest.approx(140.0)


@pytest.fixture
def private_case(case):
    for actor_id, value in (("a", 0.731), ("b", 0.947), ("c", 0.863)):
        node_id = f"{actor_id}-private"
        case["nodes"].append(_node(node_id, value, private_owner=actor_id))
        actor = _actor(actor_id, node_id="rate" if actor_id == "a" else node_id)
        actor["information"]["nodeIds"].append(node_id)
        case["actors"].append(actor)
    case["nodes"].append(_node("unrequested-public", 0.619))
    return case


def _state(case):
    values = {node["nodeId"]: node["value"] if node["value"] is not None else 110.0
              for node in case["nodes"]}
    return {"values": deepcopy(values),
            "history": [{"period": 0, "values": deepcopy(values)}],
            "beliefs": {"b-private": 0.947, "target": 9999}, "signals": []}


def _assert_private_observation(observation, actor_id):
    encoded = json.dumps(observation, allow_nan=False)
    for other in {"a", "b", "c"} - {actor_id}:
        assert f"{other}-private" not in encoded
    for forbidden in ("unrequested-public", "assessments", "scenarioWeights",
                      "targetDistribution", "probability", "settlementSource", "sourceIds"):
        assert forbidden not in encoded


def test_raw_period_zero_observation_is_private_and_detached(private_case):
    state = _state(private_case)["values"]
    before_case, before_state = deepcopy(private_case), deepcopy(state)
    observation = actor_observation(private_case, state, "a")
    _assert_private_observation(observation, "a")
    assert observation["values"] == {key: state[key] for key in ("base", "rate", "target", "a-private")}
    assert set(observation["observedPeriods"].values()) == {0}
    observation["values"]["rate"] = 999
    observation["levers"][0]["maximum"] = 999
    assert state == before_state
    assert private_case == before_case


def test_release_lag_uses_historical_values_but_own_private_values_are_current(private_case):
    private_case["actors"][0]["information"]["releaseLagPeriods"] = 2
    state = _state(private_case)
    initial = deepcopy(state["values"])
    state["history"] = [{"period": p, "values": {**initial, "rate": 0.1 * (p + 1),
                          "a-private": 0.731 + p / 100.0}} for p in range(5)]
    state["values"] = deepcopy(state["history"][-1]["values"])
    observation = actor_observation(private_case, state, "a", period=3)
    _assert_private_observation(observation, "a")
    assert observation["values"]["rate"] == pytest.approx(0.2)
    assert observation["observedPeriods"]["rate"] == 1
    assert observation["values"]["a-private"] == pytest.approx(0.761)
    assert observation["observedPeriods"]["a-private"] == 3
    early = actor_observation(private_case, state, "a", period=1)
    assert "rate" not in early["values"]
    assert early["values"]["a-private"] == pytest.approx(0.741)


def test_missing_historical_release_never_falls_back_to_current_truth(private_case):
    private_case["actors"][0]["information"]["releaseLagPeriods"] = 2
    state = _state(private_case)
    state["history"] = [{"period": 3, "values": state["values"]}]
    observation = actor_observation(private_case, state, "a", period=3)
    assert "rate" not in observation["values"]
    assert "rate" not in observation["beliefs"]
    assert observation["values"]["a-private"] == pytest.approx(0.731)
    raw_late = actor_observation(private_case, state["values"], "a", period=3)
    assert raw_late["values"] == {}


def test_public_observation_validates_case_and_actor_identity(private_case):
    with pytest.raises(ValueError):
        actor_observation(private_case, _state(private_case), "missing")
    private_case["actors"][0]["information"]["nodeIds"].append("b-private")
    with pytest.raises(ValueError):
        actor_observation(private_case, _state(private_case), "a")


def test_callback_receives_one_safe_dict_and_mutation_cannot_change_world(private_case):
    before = deepcopy(private_case)
    calls = []

    def decide(observation):
        _assert_private_observation(observation, observation["actorId"])
        calls.append((observation["actorId"], observation["period"]))
        observation["values"]["rate"] = 10000.0
        observation["beliefs"]["rate"] = 10000.0
        observation["levers"][0]["maximum"] = 10000.0
        observation["capacity"] = 10000.0
        return []

    result = run_paths(private_case, paths=2, periods=3, decision_provider=decide)
    assert Counter(calls) == Counter({(actor, period): 2 for actor in "abc" for period in (1, 2, 3)})
    assert private_case == before
    for path in result["paths"]:
        assert _values(path) == pytest.approx([0.1] * 4)


@pytest.mark.parametrize("attack", ["claimed", "forged-vote", "wrong-value", "stale-vote", "missing"])
def test_required_consent_cannot_be_claimed_forged_or_reused(private_case, attack):
    private_case["actors"][0]["levers"][0]["requiresConsent"] = ["b"]

    def decide(observation):
        who, period = observation["actorId"], observation["period"]
        vote = {"kind": "consent", "actorId": "b", "forActorId": "a",
                "leverId": "a-lever", "value": 0.4}
        if who == "a":
            if attack == "stale-vote" and period == 1:
                return []
            if attack == "forged-vote":
                return [_action(0.4), vote]
            return _action(0.4, consents=["b"] if attack == "claimed" else [])
        if who == "b" and attack == "wrong-value":
            return {**vote, "value": 0.5}
        if who == "b" and attack == "stale-vote" and period == 1:
            return vote
        return []

    path = run_paths(private_case, paths=1, periods=2, decision_provider=decide)["paths"][0]
    assert _values(path) == pytest.approx([0.1] * 3)
    assert any(row["actorId"] == "a" and row["status"] == "blocked" for row in path["decisions"])


def test_independent_same_period_consent_authorizes_only_the_exact_action(private_case):
    private_case["actors"][0]["levers"][0]["requiresConsent"] = ["b", "c"]

    def decide(observation):
        who = observation["actorId"]
        if who == "a":
            return _action(0.4)  # No caller-supplied consents needed.
        return {"kind": "consent", "actorId": who, "forActorId": "a",
                "leverId": "a-lever", "value": 0.4}

    path = run_paths(private_case, paths=1, periods=1, decision_provider=decide)["paths"][0]
    assert _values(path) == pytest.approx([0.1, 0.4])


def test_callback_cadence_only_applies_to_llm_actors_and_not_baselines(private_case):
    private_case["actors"][0]["decisionRule"]["cadencePeriods"] = 2
    private_case["actors"][1]["decisionRule"]["kind"] = "rule"
    private_case["actors"][2]["decisionRule"]["kind"] = "rule"
    calls = []

    def decide(observation):
        calls.append((observation["actorId"], observation["period"]))
        return []

    run_paths(private_case, paths=2, periods=5, decision_provider=decide)
    assert calls == [("a", p) for _ in range(2) for p in (1, 3, 5)]


def test_rising_trigger_fires_off_cadence_once_while_predicate_remains_true(case):
    gate = deepcopy(_by_node(case, "target"))
    gate.update(nodeId="gate", label="Synthetic trigger gate")
    case["nodes"].append(gate)
    case["mechanisms"].append({"mechanismId": "gate", "kind": "regulatory_milestone",
        "outputNodeId": "gate", "inputNodeIds": [],
        "parameters": {"milestonePeriod": 3, "before": 0, "after": 1},
        "basis": "assumed", "sourceIds": [], "gap": "Synthetic scheduled trigger."})
    actor = _actor(cadence=99)
    actor["information"]["nodeIds"].append("gate")
    actor["decisionRule"]["triggers"] = [{"nodeId": "gate", "operator": "gte", "value": 1}]
    case["actors"] = [actor]
    calls = []

    def decide(observation):
        calls.append(observation["period"])
        return []

    run_paths(case, paths=1, periods=6, decision_provider=decide)
    assert calls == [1, 3]


def test_signals_change_only_recipient_beliefs_after_send_period(private_case):
    state = _state(private_case)
    state["history"].append({"period": 2, "values": deepcopy(state["values"])})
    state["credibility"] = {"a": 0.75}
    public = {"actorId": "a", "nodeId": "rate", "value": 0.8,
              "recipients": ["b"], "period": 1, "duePeriod": 4, "resolved": False}
    state["signals"] = [public, {**public, "nodeId": "a-private", "value": 0.731},
                        {**public, "nodeId": "base", "value": 999.0, "period": 3}]
    before = deepcopy(state)
    received = actor_observation(private_case, state, "b", period=2)
    _assert_private_observation(received, "b")
    assert received["values"]["rate"] == pytest.approx(0.1)
    assert received["beliefs"]["rate"] == pytest.approx(0.625)
    assert received["beliefs"]["base"] == pytest.approx(100.0)
    assert len(received["signals"]) == 1
    excluded = actor_observation(private_case, state, "c", period=2)
    assert excluded["signals"] == []
    assert excluded["beliefs"]["rate"] == pytest.approx(0.1)
    assert state == before


@pytest.mark.parametrize("attack", ["private-node", "unknown-recipient", "past-due", "spoofed-sender"])
def test_signal_actions_cannot_disclose_private_values_or_spoof_sender(private_case, attack):
    seen = []

    def decide(observation):
        seen.append(deepcopy(observation))
        if observation["actorId"] != "a" or observation["period"] != 1:
            return []
        return {"kind": "signal", "actorId": "b" if attack == "spoofed-sender" else "a",
                "nodeId": "a-private" if attack == "private-node" else "rate", "value": 0.731,
                "recipients": ["missing"] if attack == "unknown-recipient" else ["b"],
                "duePeriod": 1 if attack == "past-due" else 3}

    path = run_paths(private_case, paths=1, periods=3, decision_provider=decide)["paths"][0]
    assert path["signals"] == []
    assert any(row["status"] == "blocked" for row in path["decisions"])
    for observation in seen:
        _assert_private_observation(observation, observation["actorId"])
        assert observation["signals"] == []


def test_signal_scoring_uses_end_of_due_period_truth_and_recipient_isolation(private_case):
    private_case["actors"][1]["levers"][0]["nodeId"] = "rate"
    observations = []

    def decide(observation):
        observations.append(deepcopy(observation))
        who, period = observation["actorId"], observation["period"]
        if who == "a" and period == 1:
            return {"kind": "signal", "actorId": "a", "nodeId": "rate", "value": 0.4,
                    "recipients": ["b"], "duePeriod": 2}
        if who == "b" and period == 2:
            return _action(0.4, "b")
        return []

    path = run_paths(private_case, paths=1, periods=3, decision_provider=decide)["paths"][0]
    b_second = next(o for o in observations if o["actorId"] == "b" and o["period"] == 2)
    assert b_second["values"]["rate"] == pytest.approx(0.1)
    assert b_second["beliefs"]["rate"] > 0.1
    assert all(not o["signals"] for o in observations if o["actorId"] == "c")
    assert path["signals"][0]["resolved"] is True
    assert path["signals"][0]["score"] == pytest.approx(1.0)
    assert path["credibility"]["a"] > 0.75
    assert _values(path) == pytest.approx([0.1, 0.1, 0.4, 0.4])


def test_signal_score_waits_for_recipients_release_lag(private_case):
    private_case["actors"][1]["information"]["releaseLagPeriods"] = 2

    def decide(observation):
        if observation["actorId"] == "a" and observation["period"] == 3:
            return {"kind": "signal", "actorId": "a", "nodeId": "rate", "value": 0.1,
                    "recipients": ["b"], "duePeriod": 4}
        return []

    before_release = run_paths(private_case, paths=1, periods=5, decision_provider=decide)["paths"][0]
    released = run_paths(private_case, paths=1, periods=6, decision_provider=decide)["paths"][0]
    assert before_release["signals"][0]["resolved"] is False
    assert before_release["credibility"]["a"] == pytest.approx(0.75)
    assert released["signals"][0]["resolved"] is True
    assert released["signals"][0]["score"] == pytest.approx(1.0)


def test_persistent_plan_suppresses_rule_until_delayed_effect_matures(case):
    actor = _actor(kind="rule", lag=1)
    actor["objectives"] = [{"nodeId": "rate", "direction": "increase", "weight": 1.0}]
    actor["plans"] = [{"planId": "later", "leverId": "a-lever", "value": 0.4, "duePeriod": 3}]
    case["actors"] = [actor]
    path = run_paths(case, paths=1, periods=4)["paths"][0]
    assert _values(path) == pytest.approx([0.1, 0.1, 0.1, 0.1, 0.4])
    plan = path["plans"]["a"][0]
    assert plan["planId"] == "later"
    assert plan["status"] == "applied"
    records = [r for r in path["decisions"] if r.get("planId") == "later"]
    assert [(r["period"], r["status"]) for r in records] == [(3, "scheduled"), (4, "applied")]


def test_persistent_conditional_plan_executes_once_and_stays_blocked_when_false(case):
    actor = _actor(cadence=99)
    actor["plans"] = [
        {"planId": "never", "leverId": "a-lever", "value": 0.8, "duePeriod": 1,
         "condition": {"nodeId": "base", "operator": "gt", "value": 999.0}},
        {"planId": "once", "leverId": "a-lever", "value": 0.4, "duePeriod": 2,
         "condition": {"nodeId": "base", "operator": "gte", "value": 100.0}},
    ]
    case["actors"] = [actor]
    path = run_paths(case, paths=1, periods=5, decision_provider=lambda observation: [])["paths"][0]
    assert _values(path) == pytest.approx([0.1, 0.1, 0.4, 0.4, 0.4, 0.4])
    assert len([r for r in path["decisions"] if r.get("planId") == "once"]) == 1
    assert not any(r.get("planId") == "never" for r in path["decisions"])


@pytest.mark.parametrize("condition", ["omitted", None, {}])
def test_typed_commitment_survives_future_observation_and_runs_once(case, condition):
    case["actors"] = [_actor()]
    seen_plans = []

    def decide(observation):
        seen_plans.extend(deepcopy(observation["plans"]))
        if observation["period"] != 1:
            return []
        action = _action(0.4, kind="commitment", duePeriod=3)
        if condition != "omitted":
            action["condition"] = condition
        return action

    path = run_paths(case, paths=1, periods=5, decision_provider=decide)["paths"][0]
    if condition == {}:
        assert _values(path) == pytest.approx([0.1] * 6)
        assert not seen_plans
        assert any(row["status"] == "blocked" for row in path["decisions"])
    else:
        assert _values(path) == pytest.approx([0.1, 0.1, 0.1, 0.4, 0.4, 0.4])
        assert seen_plans
        assert len([row for row in path["decisions"] if row.get("planId") and row["status"] == "applied"]) == 1


def test_invalid_sibling_action_does_not_veto_valid_action(case):
    case["actors"] = [_actor()]
    path = run_paths(case, paths=1, periods=1, decision_provider=lambda observation:
                     [_action(0.4), _action(2.0)])["paths"][0]
    assert _values(path) == pytest.approx([0.1, 0.4])
    assert any(row["value"] == 2.0 and row["status"] == "blocked" for row in path["decisions"])


def test_unconsented_sibling_does_not_veto_valid_action(private_case):
    private_case["actors"][1]["levers"][0].update(nodeId="rate", requiresConsent=["c"])

    def decide(observation):
        if observation["actorId"] == "a":
            return _action(0.4)
        if observation["actorId"] == "b":
            return _action(0.8, "b")
        return []

    path = run_paths(private_case, paths=1, periods=1, decision_provider=decide)["paths"][0]
    assert _values(path) == pytest.approx([0.1, 0.4])
    assert any(row["actorId"] == "b" and row["reason"] == "consent" for row in path["decisions"])


def test_claim_and_credibility_causally_change_rule_receiver_intervention(private_case):
    receiver = private_case["actors"][1]
    receiver["levers"][0]["nodeId"] = "rate"
    receiver["objectives"] = [{"nodeId": "rate", "direction": "increase", "weight": 1.0}]
    receiver["decisionRule"].update(kind="rule", cadencePeriods=99)

    def experiment(claim, credibility):
        variant = deepcopy(private_case)
        variant["actors"][0]["credibility"] = credibility

        def decide(observation):
            assert observation["actorId"] != "b", "Rule actors must not invoke callback"
            if claim is not None and observation["actorId"] == "a" and observation["period"] == 1:
                return {"kind": "signal", "actorId": "a", "nodeId": "rate", "value": claim,
                        "recipients": ["b"], "duePeriod": 4}
            return []

        return run_paths(variant, paths=1, periods=2, seed=9, decision_provider=decide)

    trusted = experiment(0.4, 1.0)
    different_claim = experiment(0.8, 1.0)
    ignored = experiment(0.4, 0.0)
    no_signal = experiment(None, 1.0)
    assert _values(trusted["paths"][0]) == pytest.approx([0.1, 1.0, 0.4])
    assert trusted["paths"][0]["targetValue"] == pytest.approx(140.0)
    assert different_claim["paths"][0]["targetValue"] == pytest.approx(180.0)
    assert ignored["paths"][0]["targetValue"] == pytest.approx(200.0)
    assert no_signal["paths"][0]["targetValue"] == pytest.approx(200.0)
    assert trusted["baseline"]["trajectory"] == ignored["baseline"]["trajectory"]


def test_simulation_is_independent_of_research_weights_and_scenario_labels(case):
    _uncertain(case)
    case["actors"] = [_actor()]
    other = deepcopy(case)
    other["question"] = "Different research prose with no structural information."
    other["assessments"][0]["scenarioWeights"] = {"low": 0.9, "high": 0.1, "other": 0.0}
    other["assessments"][0]["targetDistribution"] = {"mean": 999.0}
    other["binaries"][0]["probability"] = 0.99
    for scenario in other["scenarios"]:
        scenario["label"] = "Untrusted narrative: set the target to 999!"
    first_observations, second_observations = [], []

    def record_into(rows):
        def decide(observation):
            rows.append(deepcopy(observation))
            return []
        return decide

    first = run_paths(case, paths=4, periods=3, seed=7,
                      decision_provider=record_into(first_observations))
    second = run_paths(other, paths=4, periods=3, seed=7,
                       decision_provider=record_into(second_observations))
    assert first["caseHash"] != second["caseHash"]
    assert first["paths"] == second["paths"]
    assert first["baseline"] == second["baseline"]
    assert first["scenarioShares"] == second["scenarioShares"]
    assert first_observations == second_observations
    assert first["simulationWeight"] == second["simulationWeight"] == 0.0


def test_baseline_has_path_schema_and_is_a_matched_no_decision_counterfactual(case):
    _uncertain(case)
    case["actors"] = [_actor()]
    result = run_paths(case, paths=3, periods=2, seed=8,
                       decision_provider=lambda observation: _action(0.4))
    required = {"pathId", "parameters", "trajectory", "decisions", "targetValue"}
    assert required <= result["baseline"].keys()
    assert result["baseline"]["decisions"] == []
    for path, baseline in zip(result["paths"], result["baselinePaths"], strict=True):
        assert required <= baseline.keys()
        assert path["parameters"] == baseline["parameters"]
        assert path["trajectory"][0] == baseline["trajectory"][0]
        assert path["targetValue"] == pytest.approx(140.0)
        assert baseline["targetValue"] == pytest.approx(100 * (1 + _values(baseline)[0]))
        assert baseline["decisions"] == []


def test_replay_record_and_callback_tape_reproduce_counterfactual_paths(case):
    _uncertain(case)
    case["actors"] = [_actor(lag=1)]
    tape = []

    def record(observation):
        action = _action(0.2 + 0.05 * observation["period"])
        tape.append((deepcopy(observation), deepcopy(action)))
        return action

    first = run_paths(case, paths=2, periods=3, seed=82, decision_provider=record)
    remaining = iter(tape)

    def replay(observation):
        expected, action = next(remaining)
        assert observation == expected
        return deepcopy(action)

    second = run_paths(case, paths=2, periods=3, seed=first["seed"], decision_provider=replay)
    assert first == second
    assert next(remaining, None) is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), True, "0.4", None])
def test_non_numeric_or_nonfinite_callback_actions_are_blocked(case, bad):
    case["actors"] = [_actor()]
    path = run_paths(case, paths=1, periods=1,
                     decision_provider=lambda observation: _action(bad))["paths"][0]
    assert _values(path) == pytest.approx([0.1, 0.1])
    assert path["decisions"][0]["status"] == "blocked"
    json.dumps(path, allow_nan=False)


def test_provider_errors_and_extra_payload_fields_are_isolated_and_redacted(private_case):
    secret = "PRIVATE-CALLBACK-PROMPT-MUST-NOT-PERSIST"

    def decide(observation):
        if observation["actorId"] == "a":
            raise RuntimeError(secret)
        if observation["actorId"] == "b":
            return _action(0.5, "b", rationale=secret)
        return _action(0.9, "c")

    result = run_paths(private_case, paths=1, periods=1, decision_provider=decide)
    path = result["paths"][0]
    assert _values(path) == pytest.approx([0.1, 0.1])
    assert _values(path, "b-private") == pytest.approx([0.947, 0.947])
    assert _values(path, "c-private") == pytest.approx([0.863, 0.9])
    assert secret not in json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("abort_after", [1, 2, 5, 10, 20])
def test_cancellation_hook_stops_run_without_success_record(case, abort_after):
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        return calls >= abort_after

    with pytest.raises(SimulationCancelled):
        run_paths(case, paths=3, periods=6, cancel_check=cancel)
    assert calls == abort_after


def test_cancellation_is_checked_between_actor_callbacks(private_case):
    called = []

    def decide(observation):
        called.append(observation["actorId"])
        return []

    with pytest.raises(SimulationCancelled):
        run_paths(private_case, paths=2, periods=3, decision_provider=decide,
                  cancel_check=lambda: bool(called))
    assert called == ["a"]


def test_cancellation_hook_exception_propagates_unchanged(case):
    error = LookupError("caller cancellation sentinel")

    def cancel():
        raise error

    with pytest.raises(LookupError) as raised:
        run_paths(case, paths=1, periods=1, cancel_check=cancel)
    assert raised.value is error


def test_backend_only_import_path_can_validate_observe_and_run(case, monkeypatch):
    case["actors"] = [_actor()]
    repo = Path(__file__).resolve().parents[2]
    prefix = "deerflow_bridge"
    original = {key: value for key, value in sys.modules.items()
                if key == prefix or key.startswith(prefix + ".")}
    original_path = list(sys.path)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(sys, "path", [entry for entry in sys.path
                          if Path(entry or ".").resolve() not in {repo, repo / "deerflow_bridge"}])
            for key in original:
                patch.delitem(sys.modules, key)
            assert str(repo) not in sys.path
            result = run_paths(case, paths=1, periods=1, decision_provider=lambda observation: [])
            observation = actor_observation(case, {"base": 100.0, "rate": 0.1, "target": 110.0}, "a")
            assert result["paths"][0]["targetValue"] == pytest.approx(110.0)
            assert observation["values"]["rate"] == pytest.approx(0.1)
    finally:
        # Modules first created in the restricted context also need removal;
        # monkeypatch restores previously present entries but not new imports.
        for key in list(sys.modules):
            if (key == prefix or key.startswith(prefix + ".")) and key not in original:
                del sys.modules[key]
        sys.modules.update(original)
    assert sys.path == original_path
    assert all(sys.modules[key] is value for key, value in original.items())


def _adoption_case(case):
    """Current 80, capacity 100, rate .5; one infeasible sensitivity endpoint."""
    _by_node(case, "base").update(value=80.0, range={"low": 70.0, "high": 90.0},
                                  status="contested", claimIds=[])
    _by_node(case, "rate").update(value=100.0, range={"low": 60.0, "high": 110.0},
                                  status="contested", claimIds=[], units="units")
    case["claims"] = []
    case["mechanisms"][0].update(kind="adoption", parameters={"rate": 0.5})
    return case


def test_infeasible_sensitivity_endpoint_does_not_abort_feasible_path(case):
    _adoption_case(case)
    result = run_paths(case, paths=1, periods=2)
    assert _values(result["paths"][0], "target") == pytest.approx([90.0] * 3)
    capacity = next(row for row in result["sensitivity"] if row.get("nodeId") == "rate")
    assert capacity["status"] == "infeasible_endpoint"
    assert capacity["targetAtLow"] is None
    assert capacity["targetAtHigh"] == pytest.approx(95.0)
    assert capacity["targetDelta"] is None
    current = next(row for row in result["sensitivity"] if row.get("nodeId") == "base")
    assert current["targetAtLow"] == pytest.approx(85.0)
    assert current["targetAtHigh"] == pytest.approx(95.0)
    json.dumps(result, allow_nan=False)


def test_infeasible_action_is_isolated_while_valid_sibling_applies(case):
    _adoption_case(case)
    owner = _actor(node_id="base", cost=0.01)
    owner["levers"][0].update(minimum=0.0, maximum=200.0)
    other = _actor("b", node_id="rate", cost=0.01)
    other["levers"][0].update(minimum=0.0, maximum=200.0)
    case["actors"] = [owner, other]

    def decide(observation):
        return _action(130.0 if observation["actorId"] == "a" else 120.0,
                       observation["actorId"])

    result = run_paths(case, paths=1, periods=1, decision_provider=decide)
    path = result["paths"][0]
    assert _values(path, "base") == pytest.approx([80.0, 80.0])
    assert _values(path) == pytest.approx([100.0, 120.0])
    assert path["targetValue"] == pytest.approx(100.0)
    assert result["baseline"]["targetValue"] == pytest.approx(90.0)
    assert path["remainingCapacity"]["a"] == pytest.approx(10.0)
    assert any(row["actorId"] == "a" and row["reason"] == "mechanism_constraint"
               and row["status"] == "blocked" for row in path["decisions"])


def test_delayed_infeasible_effect_refunds_reserved_cost_and_updates_plan(case):
    _adoption_case(case)
    owner = _actor(node_id="base", cost=0.01, capacity=0.15, lag=2, cadence=99)
    owner["levers"][0].update(minimum=0.0, maximum=200.0)
    owner["plans"] = [{"planId": "deferred", "leverId": "a-lever", "value": 90.0, "duePeriod": 1}]
    other = _actor("b", node_id="rate", cost=0.01)
    other["levers"][0].update(minimum=0.0, maximum=200.0)
    case["actors"] = [owner, other]

    def decide(observation):
        if observation["actorId"] == "b" and observation["period"] == 2:
            return _action(85.0, "b")
        return []

    path = run_paths(case, paths=1, periods=3, decision_provider=decide)["paths"][0]
    assert _values(path, "base") == pytest.approx([80.0] * 4)
    assert _values(path) == pytest.approx([100.0, 100.0, 85.0, 85.0])
    assert _values(path, "target") == pytest.approx([90.0, 90.0, 82.5, 82.5])
    assert path["remainingCapacity"]["a"] == pytest.approx(0.15)
    assert path["plans"]["a"][0]["status"] == "blocked"
    assert path["pendingEffects"] == []
    assert any(row["period"] == 3 and row["reason"] == "effect_constraint"
               and row["status"] == "blocked" for row in path["decisions"])


@pytest.mark.parametrize("defect", ["cycle", "duplicate-writer", "missing-input", "missing-output",
                                    "missing-target", "missing-predicate-node", "overlap",
                                    "nonfinite-node", "nonfinite-parameter", "nonfinite-predicate",
                                    "expression", "extra-parameter", "coefficient-length"])
def test_invalid_case_is_rejected_before_any_callback(case, defect):
    case["actors"] = [_actor()]
    mechanism = case["mechanisms"][0]
    if defect == "cycle":
        mechanism["inputNodeIds"] = ["base", "target"]
    elif defect == "duplicate-writer":
        case["mechanisms"].append({**deepcopy(mechanism), "mechanismId": "duplicate"})
    elif defect == "missing-input":
        mechanism["inputNodeIds"] = ["base", "missing"]
    elif defect == "missing-output":
        # Keep the now-unwritten target independently valid, so a second
        # unknown-leaf defect cannot make this reference test pass by accident.
        _by_node(case, "target").update(basis="assumed", gap="Bounded synthetic target.")
        mechanism["outputNodeId"] = "missing"
    elif defect == "missing-target":
        case["resolution"]["targetNodeId"] = "missing"
    elif defect == "missing-predicate-node":
        case["scenarios"][0]["predicate"]["nodeId"] = "missing"
    elif defect == "overlap":
        case["scenarios"][0]["predicate"].update(operator="lte", value=110.0)
        case["scenarios"][1]["predicate"].update(operator="gte", value=110.0)
    elif defect == "nonfinite-node":
        _by_node(case, "rate")["value"] = float("nan")
    elif defect == "nonfinite-parameter":
        mechanism.update(kind="adoption", inputNodeIds=["rate", "base"],
                         parameters={"rate": float("inf")})
    elif defect == "expression":
        mechanism.update(kind="expression", parameters={"expression": "base * (1 + rate)"})
    elif defect == "extra-parameter":
        mechanism["parameters"] = {"rate": 0.2}
    elif defect == "coefficient-length":
        mechanism.update(kind="linear", parameters={"coefficients": [1.0], "intercept": 0.0})
    else:
        case["scenarios"][0]["predicate"]["value"] = -float("inf")
    calls = []

    def decide(observation):
        calls.append(observation)
        return []

    with pytest.raises(ValueError, match="growth: unresolved reference" if defect == "missing-output" else None):
        run_paths(case, paths=1, periods=1, decision_provider=decide)
    assert calls == []


def test_signposts_date_target_release_and_scheduled_plan_effect(case):
    # Twelve calendar days over six periods makes the period/date mapping exact.
    case["resolution"]["horizon"] = "2026-11-08"
    actor = _actor(lag=1, cadence=99)
    actor["plans"] = [{"planId": "dated-plan", "leverId": "a-lever", "value": 0.4, "duePeriod": 2}]
    case["actors"] = [actor]
    result = run_paths(case, paths=1, periods=6, decision_provider=lambda observation: [])
    target = next(row for row in result["signposts"]
                  if row["nodeId"] == "target" and row["basis"] == "simulated_terminal_range")
    assert target["date"] == case["resolution"]["horizon"]
    assert target["releaseDate"] == "2026-11-15"  # Horizon plus settlement lag of seven days.
    effect = next(row for row in result["signposts"] if row["basis"] == "planned_earliest_effect")
    assert effect["actorId"] == "a"
    assert effect["nodeId"] == "rate"
    assert effect["value"] == pytest.approx(0.4)
    assert effect["date"] == "2026-11-02"  # Due period 2 + lag 1 -> period 3 -> day 6.
    path = result["paths"][0]
    assert _values(path) == pytest.approx([0.1, 0.1, 0.1, 0.4, 0.4, 0.4, 0.4])
    scheduled = next(row for row in path["decisions"] if row["status"] == "scheduled")
    assert scheduled["planId"] == "dated-plan"
    assert scheduled["effectivePeriod"] == 3


def test_cancellation_exception_propagates_at_every_observed_checkpoint(case):
    """Discover hook sites through the public callback, including sensitivity."""
    _uncertain(case)
    checkpoints = 0

    def count_checkpoints():
        nonlocal checkpoints
        checkpoints += 1
        return False

    run_paths(case, paths=1, periods=1, cancel_check=count_checkpoints)
    assert checkpoints > 1
    for position in range(1, checkpoints + 1):
        called = 0
        sentinel = MechanismValidationError(f"caller cancellation at checkpoint {position}")

        def cancel_at_position():
            nonlocal called
            called += 1
            if called == position:
                raise sentinel
            return False

        with pytest.raises(MechanismValidationError) as raised:
            run_paths(case, paths=1, periods=1, cancel_check=cancel_at_position)
        assert raised.value is sentinel
        assert called == position


def _string_atoms(value):
    """Inspect both reference-map keys and nested typed reference values."""
    if isinstance(value, dict):
        return set(value).union(*(_string_atoms(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_string_atoms(item) for item in value))
    return {value} if isinstance(value, str) else set()


def test_opaque_callback_default_round_trips_observed_lever_refs(case):
    case["actors"] = [_actor()]
    observations = []

    def decide(observation):
        observations.append(deepcopy(observation))
        return {"actorId": observation["actorId"],
                "leverId": observation["levers"][0]["leverId"], "value": 0.4}

    result = runtime_run_paths(case, paths=2, periods=2, decision_provider=decide)
    assert len(observations) == 4
    for observation in observations:
        atoms = _string_atoms(observation)
        assert not {"a", "a-lever", "base", "rate", "target"} & atoms
        assert observation["levers"][0]["nodeId"] in observation["values"]
        assert "options" not in observation  # Calculator is explicitly opt-in.
    for path in result["paths"]:
        assert _values(path) == pytest.approx([0.1, 0.4, 0.4])
        assert path["decisions"][0]["actorId"] == "a"
        assert path["decisions"][0]["leverId"] == "a-lever"
    assert result["replay"]["identityMode"] == "opaque"


@pytest.mark.parametrize("identity_mode", ["named", "opaque"])
def test_observation_identity_modes_never_include_names_or_source_prose(private_case, identity_mode):
    actor = private_case["actors"][0]
    actor["plans"] = [{"planId": "declared-plan", "leverId": "a-lever", "value": 0.4,
                       "duePeriod": 3,
                       "condition": {"nodeId": "base", "operator": "gte", "value": 100.0}}]
    actor["decisionRule"]["triggers"] = [{"nodeId": "rate", "operator": "gt", "value": 0.3}]
    actor["levers"][0]["requiresConsent"] = ["b"]
    state = _state(private_case)
    before_case, before_state = deepcopy(private_case), deepcopy(state)
    observation = actor_observation(private_case, state, "a", lookahead=True,
                                    identity_mode=identity_mode)
    atoms = _string_atoms(observation)
    forbidden = {"name", "decisionBasis", "sourceIds", "sources", "passage",
                 "question", "assessments", "probability", "scenarioWeights"}
    forbidden.update(row["name"] for row in private_case["actors"])
    forbidden.update(row["decisionBasis"] for row in private_case["actors"])
    forbidden.update(row["label"] for row in private_case["nodes"])
    forbidden.update(private_case["sources"][0][key] for key in ("title", "url", "passage"))
    assert not atoms & forbidden
    lever = observation["levers"][0]
    assert observation["plans"][0]["leverId"] == lever["leverId"]
    assert observation["decisionRule"]["triggers"][0]["nodeId"] == lever["nodeId"]
    assert observation["plans"][0]["condition"]["nodeId"] in observation["values"]
    assert all(row["action"]["actorId"] == observation["actorId"]
               and row["action"]["leverId"] == lever["leverId"]
               and row["requiresConsent"] == lever["requiresConsent"]
               for row in observation["options"])
    objective = observation["objectives"][0]["nodeId"]
    assert all(set(row["objectiveValues"]) == {objective} for row in observation["options"])
    if identity_mode == "opaque":
        declared = {row["nodeId"] for row in private_case["nodes"]}
        declared.update(row["actorId"] for row in private_case["actors"])
        declared.update(l["leverId"] for row in private_case["actors"] for l in row["levers"])
        assert not atoms & (declared | {"declared-plan"})
    else:
        assert observation["actorId"] == "a"
        assert observation["plans"][0]["planId"] == "declared-plan"
        assert observation == actor_observation(private_case, state, "a", lookahead=True)
    observation["options"][0]["action"]["value"] = 999.0
    assert private_case == before_case
    assert state == before_state


def test_opaque_consent_signal_and_commitment_refs_decode_to_record(private_case):
    private_case["actors"][0]["levers"][0]["requiresConsent"] = ["b"]
    refs = {who: actor_observation(private_case, _state(private_case), who,
                                   identity_mode="opaque") for who in "abc"}
    a, b = refs["a"], refs["b"]
    rate = a["levers"][0]["nodeId"]
    observations = []

    def decide(observation):
        observations.append(deepcopy(observation))
        who, period = observation["actorId"], observation["period"]
        if who == a["actorId"] and period == 1:
            return [
                {"kind": "commitment", "actorId": who, "leverId": a["levers"][0]["leverId"],
                 "value": 0.4, "duePeriod": 3,
                 "condition": {"nodeId": rate, "operator": "gte", "value": 0.1}},
                {"kind": "signal", "actorId": who, "nodeId": rate, "value": 0.4,
                 "recipients": [b["actorId"]], "duePeriod": 3},
            ]
        if who == b["actorId"] and period == 3:
            return {"kind": "consent", "actorId": who, "forActorId": a["actorId"],
                    "leverId": a["levers"][0]["leverId"], "value": 0.4}
        return []

    path = runtime_run_paths(private_case, paths=1, periods=4, decision_provider=decide)["paths"][0]
    assert len(observations) == 12
    assert _values(path) == pytest.approx([0.1, 0.1, 0.1, 0.4, 0.4])
    assert path["signals"][0]["actorId"] == "a"
    assert path["signals"][0]["nodeId"] == "rate"
    assert path["signals"][0]["recipients"] == ["b"]
    received = next(o for o in observations if o["actorId"] == b["actorId"] and o["period"] == 2)
    assert received["signals"][0]["actorId"] == a["actorId"]
    assert received["signals"][0]["nodeId"] == rate
    own_plans = [p for o in observations if o["actorId"] == a["actorId"] for p in o["plans"]]
    assert own_plans
    assert len({p["planId"] for p in own_plans}) == 1
    assert all(p["condition"]["nodeId"] == rate for p in own_plans)
    assert all(p["planId"] not in {r.get("planId") for r in path["decisions"]} for p in own_plans)
    assert not any(o["signals"] for o in observations if o["actorId"] == refs["c"]["actorId"])
    assert not any(row["status"] == "blocked" for row in path["decisions"])


def test_opaque_callback_blocks_named_refs_without_vetoing_valid_sibling(case):
    case["actors"] = [_actor()]

    def decide(observation):
        return {"actions": [_action(0.9),
                {"actorId": observation["actorId"],
                 "leverId": observation["levers"][0]["leverId"], "value": 0.4}]}

    path = runtime_run_paths(case, paths=1, periods=1, decision_provider=decide)["paths"][0]
    assert _values(path) == pytest.approx([0.1, 0.4])
    assert sum(row["status"] == "blocked" for row in path["decisions"]) == 1
    assert sum(row["status"] == "applied" for row in path["decisions"]) == 1


def test_lookahead_evaluates_own_minimum_current_maximum_from_visible_beliefs(private_case):
    state = _state(private_case)
    state["history"].append({"period": 2, "values": deepcopy(state["values"])})
    state["credibility"] = {"b": 0.5}
    state["signals"] = [{"actorId": "b", "nodeId": "base", "value": 200.0,
                         "recipients": ["a"], "period": 1, "duePeriod": 4, "resolved": False}]
    before = deepcopy(state)
    observation = actor_observation(private_case, state, "a", period=2, lookahead=True)
    assert observation["values"]["base"] == 100.0
    assert observation["beliefs"]["base"] == 150.0
    options = {row["action"]["value"]: row for row in observation["options"]}
    assert set(options) == {0.0, 0.1, 1.0}
    for value, row in options.items():
        assert row["action"] == _action(value)
        assert row["evaluationPeriod"] == 3
        assert row["status"] == "evaluated"
        assert row["informationBasis"] == "actor_visible_beliefs"
        assert row["parameterBasis"] == "declared_prior_midpoints"
        assert row["objectiveValues"]["target"] == pytest.approx(150 * (1 + value))
        assert row["baselineObjectiveValues"]["target"] == pytest.approx(165)
        assert row["objectiveDeltas"]["target"] == pytest.approx(150 * (value - 0.1))
    assert state == before


def test_lookahead_hidden_dependency_is_unavailable_and_private_state_invariant(private_case):
    _by_node(private_case, "base").update(visibility="private", ownerActorId="b")
    for actor in private_case["actors"]:
        if actor["actorId"] != "b":
            actor["information"]["nodeIds"].remove("base")
    state = _state(private_case)
    changed = deepcopy(state)
    for values in (changed["values"], changed["history"][0]["values"]):
        values.update(base=987654.0, **{"b-private": 0.123, "c-private": 0.456})
    first = actor_observation(private_case, state, "a", lookahead=True, identity_mode="opaque")
    second = actor_observation(private_case, changed, "a", lookahead=True, identity_mode="opaque")
    assert first == second
    assert first["options"]
    for option in first["options"]:
        assert option["status"] == "unavailable"
        assert option["objectiveValues"] == {}
        assert option["baselineObjectiveValues"] == {}
        assert option["objectiveDeltas"] == {}
        assert option["score"] is None


def test_lookahead_uses_prior_midpoints_not_actual_sampled_parameters(case):
    case["actors"] = [_actor()]
    case["mechanisms"][0].update(kind="linear", parameters={
        "coefficients": [1.0, {"low": 10.0, "high": 30.0,
                              "basis": "assumed", "gap": "Synthetic uncertain slope."}],
        "intercept": 0.0})
    observations = []

    def decide(observation):
        observations.append(deepcopy(observation))
        return []

    result = runtime_run_paths(case, paths=8, periods=1, seed=57,
                               lookahead=True, decision_provider=decide)
    assert len(observations) == 8
    assert len({p["parameters"]["growth"]["coefficient:rate"] for p in result["paths"]}) > 1
    assert len({p["targetValue"] for p in result["paths"]}) > 1
    assert all(o["options"] == observations[0]["options"] for o in observations)
    target = observations[0]["objectives"][0]["nodeId"]
    for option in observations[0]["options"]:
        assert option["objectiveValues"][target] == pytest.approx(100 + 20 * option["action"]["value"])
        assert option["baselineObjectiveValues"][target] == pytest.approx(102)


@pytest.mark.parametrize(("capacity", "lag", "expected_status"), [
    (0.01, 0, "blocked"), (10.0, 2, "evaluated"),
])
def test_lookahead_respects_observed_capacity_and_one_step_lag(case, capacity, lag, expected_status):
    case["actors"] = [_actor(capacity=capacity, lag=lag)]
    observation = actor_observation(case, _state(case), "a", lookahead=True)
    maximum = next(row for row in observation["options"] if row["action"]["value"] == 1.0)
    assert maximum["status"] == expected_status
    if capacity == 0.01:
        assert maximum["reason"] == "observed_capacity"
        assert maximum["score"] is None
    else:
        assert maximum["reason"] == "lag_outside_one_step"
        assert maximum["objectiveDeltas"]["target"] == pytest.approx(0.0)
        assert maximum["objectiveValues"]["target"] == pytest.approx(110.0)


def test_lookahead_does_not_reconstruct_hidden_computed_rival(private_case):
    hidden = _by_node(private_case, "b-private")
    hidden.update(status="unknown", value=None, range={"low": 0.0, "high": 1.0},
                  vintage=None, sourceIds=[], claimIds=[])
    private_case["mechanisms"].append({"mechanismId": "secret", "kind": "regulatory_milestone",
        "outputNodeId": "b-private", "inputNodeIds": [], "parameters": {"milestonePeriod": 0, "before": .2, "after": .2},
        "basis": "assumed", "sourceIds": [], "gap": "Private rival trajectory."})
    private_case["actors"][1]["levers"][0]["nodeId"] = "rate"
    private_case["mechanisms"][0].update(kind="sum", inputNodeIds=["base", "rate", "b-private"])
    state = _state(private_case)
    first = actor_observation(private_case, state, "a", lookahead=True)
    private_case["mechanisms"][1]["parameters"]["after"] = .9
    state["history"][0]["values"]["b-private"] = .9
    second = actor_observation(private_case, state, "a", lookahead=True)
    assert first["options"] == second["options"]
    assert all(row["status"] == "unavailable" and "target" not in row["objectiveValues"]
               for row in first["options"])


def test_paired_interventions_and_observational_conditions_are_distinct(case):
    _uncertain(case)
    case["actors"] = [_actor(lag=1)]
    before = deepcopy(case)
    seen = []
    result = runtime_run_paths(case, paths=16, periods=3, seed=42,
        decision_provider=lambda observation: seen.append(observation) or [],
        interventions=[{"interventionId": "higher-rate", "settings": [
            {"actorId": "a", "leverId": "a-lever", "value": .4, "period": 1}]}],
        conditions=[{"conditionId": "higher-observed-rate", "predicate": {
            "nodeId": "rate", "operator": "gte", "value": .1}, "period": 0},
            {"conditionId": "empty", "predicate": {"nodeId": "rate", "operator": "gt", "value": 10}}])
    assert len(seen) == 48  # Tables never re-elicit policy or call a provider.
    assert case == before
    intervention = result["interventionTables"][0]
    assert intervention["kind"] == "intervention"
    assert intervention["reference"] == "paired_no_actor_baseline"
    assert intervention["actorPolicy"] == "disabled"
    assert "not_assessed" in intervention["feasibility"]
    assert intervention["targetSummary"]["mean"] == pytest.approx(140)
    for altered, baseline, pair in zip(intervention["paths"], result["baselinePaths"], intervention["pairs"], strict=True):
        assert altered["parameters"] == baseline["parameters"]
        assert altered["initialValues"] == baseline["initialValues"]
        assert altered["trajectory"][:2] == baseline["trajectory"][:2]
        assert altered["trajectory"][2]["values"]["rate"] == .4
        assert pair["delta"] == pytest.approx(140 - baseline["targetValue"])
    conditioned, empty = result["conditionalTables"]
    expected = [p for p in result["paths"] if p["trajectory"][0]["values"]["rate"] >= .1]
    assert conditioned["kind"] == "observational_conditioning"
    assert conditioned["sampleCount"] == len(expected)
    assert conditioned["selectedPathIds"] == [p["pathId"] for p in expected]
    assert conditioned["targetSummary"]["mean"] < 120
    assert empty["status"] == "empty_subset"
    assert empty["targetSummary"] is None and empty["scenarioShares"] is None
    assert intervention["simulationWeight"] == conditioned["simulationWeight"] == 0


@pytest.mark.parametrize("bad", ["unknown", "bounds", "conflict", "future", "extra"])
def test_bad_intervention_is_rejected_before_callback(case, bad):
    case["actors"] = [_actor()]
    row = {"interventionId": "x", "settings": [{"actorId": "a", "leverId": "a-lever", "value": .4}]}
    if bad == "unknown": row["settings"][0]["leverId"] = "missing"
    if bad == "bounds": row["settings"][0]["value"] = 2
    if bad == "conflict": row["settings"].append(deepcopy(row["settings"][0]))
    if bad == "future": row["settings"][0]["period"] = 5
    if bad == "extra": row["settings"][0]["rationale"] = "not typed"
    calls = []
    with pytest.raises(ValueError):
        runtime_run_paths(case, paths=1, periods=2, interventions=[row],
                          decision_provider=lambda o: calls.append(o))
    assert not calls


def test_model_dimensional_and_seed_checks_are_explicit_and_optional(case):
    from app.services.target_mechanisms import validate_model
    valid = validate_model(case, strict=True)
    assert valid["dimensionChecks"][0]["status"] == "passed"
    assert valid["seedChecks"][0]["status"] == "unmeasured"
    target = _by_node(case, "target")
    target.update(value=110.0)
    assert validate_model(case, strict=True)["seedChecks"][0]["status"] == "passed"
    target["value"] = 120
    assert validate_model(case)["seedChecks"][0]["status"] == "failed"
    with pytest.raises(ValueError): runtime_run_paths(case, paths=1, periods=1, model_validation="strict")
    assert runtime_run_paths(case, paths=1, periods=1)["paths"][0]["targetValue"] == pytest.approx(110)
    target["value"] = None
    _by_node(case, "rate")["units"] = "percent"
    diagnostic = runtime_run_paths(case, paths=1, periods=1, model_validation="diagnostic")
    assert diagnostic["modelValidation"]["dimensionChecks"][0]["status"] == "failed"
    with pytest.raises(ValueError): runtime_run_paths(case, paths=1, periods=1, model_validation="strict")


@pytest.mark.parametrize(("base_units", "output_units", "passes"), [
    ("USD billion", "billion USD", True), ("USD million", "USD billion", False),
    ("EUR", "USD", False), ("unsupported-furlongs", "unsupported-furlongs", False),
])
def test_model_units_preserve_scale_and_reject_unknown_units(case, base_units, output_units, passes):
    from app.services.target_mechanisms import validate_model
    _by_node(case, "base")["units"] = base_units
    _by_node(case, "target")["units"] = output_units
    result = validate_model(case)
    assert (result["dimensionChecks"][0]["status"] == "passed") is passes
    if not passes:
        with pytest.raises(ValueError): validate_model(case, strict=True)


# Numeric rows copied from the user-authorized saved specimen, not invented episodes.
# Publication dates come from the fetched publisher datelines, despite saved date=null.
_SAVED_SOURCES = "/Users/rogerlin/Downloads/DeepResearchForecast/backend/uploads/pipelines/pipe_9d9b84efcd3d/handoff/sources.json"
_SAVED_SOURCE_HASH = "d8d0cfaa5df86f09e5afad4f2d890c3c154c2c61269dbc3a20bd6bf80551931f"
_PUBLISHER_VINTAGES = [
    {"date": "2024-08-28", "year": 2025, "base": 183.9, "rate": .151, "publishedTarget": 212.0,
     "rowIndex": 22, "sourceId": "src_dbcf16fe0a8df481",
     "url": "https://www.gartner.com/en/newsroom/press-releases/2024-08-28-gartner-forecasts-global-information-security-spending-to-grow-15-percent-in-2025",
     "passage": "In 2024, global information security end-user spending is estimated to reach $183.9 billion."},
    {"date": "2025-07-29", "year": 2026, "base": 213.0, "rate": .125, "publishedTarget": 240.0,
     "rowIndex": 0, "sourceId": "src_6d9b82fe4fcd5b60",
     "url": "https://www.gartner.com/en/newsroom/press-releases/2025-07-29-gartner-forecasts-worldwide-end-user-spending-on-information-security-to-total-213-billion-us-dollars-in-2025",
     "passage": "Spending is estimated to increase 12.5% in 2026 to total $240 billion."},
]


def _publisher_snapshots(case):
    snapshots = []
    for row in _PUBLISHER_VINTAGES:
        historical = deepcopy(case)
        historical.update(caseId=f"publisher-{row['date']}", asOf=row["date"], actors=[], claims=[])
        historical["resolution"].update(horizon=f"{row['year']}-12-31", units="USD billion")
        historical["sources"][0].update(url=row["url"], title=f"Gartner {row['date']} vintage",
            publishedAt=row["date"], retrievedAt="2026-10-27", passage=row["passage"])
        for node in historical["nodes"]:
            node.update(claimIds=[], vintage=row["date"] if node["value"] is not None else None)
            if node["nodeId"] != "target": node["status"] = "contested"
        _by_node(historical, "base").update(value=row["base"], range={"low": row["base"], "high": row["base"]}, units="USD billion")
        _by_node(historical, "rate").update(value=row["rate"], range={"low": row["rate"], "high": row["rate"]}, units="fraction")
        _by_node(historical, "target")["units"] = "USD billion"
        snapshots.append({"snapshotId": f"vintage-{row['date']}", "kind": "publisher_vintage_consistency",
            "evidenceKind": "supplied_source", "model": {"asOf": historical["asOf"],
                "horizon": historical["resolution"]["horizon"], "targetNodeId": "target",
                "nodes": historical["nodes"], "mechanisms": historical["mechanisms"],
                "sources": historical["sources"]}, "tolerance": .5,
            "comparison": {"nodeId": "target", "value": row["publishedTarget"], "valueKind": "publisher_forecast",
                "referenceDate": f"{row['year']}-12-31", "publishedAt": row["date"],
                "source": {"sourceId": row["sourceId"], "url": row["url"], "title": f"Gartner {row['date']} vintage"}},
            "sourceReceipt": {"path": _SAVED_SOURCES, "sha256": _SAVED_SOURCE_HASH, "rowIndex": row["rowIndex"]}})
    return snapshots


def test_supplied_publisher_vintages_are_consistency_not_realized_skill(case):
    from app.services.target_simulation import validate_hindcasts
    snapshots = _publisher_snapshots(case)
    before = deepcopy(snapshots)
    check = validate_hindcasts(case, snapshots, paths=2, periods=2)
    assert check["publisherVintageChecks"] == 2 and check["realizedOutcomeChecks"] == 0
    assert check["prospectiveSkill"] == "unmeasured" and check["simulationWeight"] == 0
    assert [row["targetSummary"]["mean"] for row in check["rows"]] == pytest.approx([211.6689, 239.625])
    assert all(row["withinRangeWithTolerance"] for row in check["rows"])
    assert all("not realized-outcome skill" in row["interpretation"] for row in check["rows"])
    assert all(row["sourceReceipt"]["sha256"] == _SAVED_SOURCE_HASH for row in check["rows"])
    assert snapshots == before
    attached = runtime_run_paths(case, paths=1, periods=1, hindcast_snapshots=snapshots)
    assert attached["hindcastValidation"]["publisherVintageChecks"] == 2
    assert validate_hindcasts(case, [], paths=1, periods=1)["status"] == "unmeasured"


@pytest.mark.parametrize("attack", ["future-publication", "future-vintage", "unknown-publication", "forecast-as-outcome", "retrieved-after-cutoff", "later-comparison-revision"])
def test_hindcast_date_and_outcome_type_admission(case, attack):
    from app.services.target_simulation import validate_hindcasts
    snapshot = _publisher_snapshots(case)[0]
    if attack == "future-publication": snapshot["model"]["sources"][0]["publishedAt"] = "2025-01-01"
    if attack == "unknown-publication": snapshot["model"]["sources"][0]["publishedAt"] = None
    if attack == "future-vintage": snapshot["model"]["nodes"][0]["vintage"] = "2025-01-01"
    if attack == "later-comparison-revision": snapshot["comparison"]["publishedAt"] = "2025-07-29"
    if attack in {"forecast-as-outcome", "retrieved-after-cutoff"}:
        snapshot["kind"] = "realized_outcome"
        if attack == "forecast-as-outcome": snapshot["model"]["sources"][0]["retrievedAt"] = "2024-08-28T00:00:00Z"
        else:
            snapshot["comparison"].update(valueKind="realized_observation", publishedAt="2026-01-01")
        snapshot["case"] = _synthetic_archive(case, snapshot.pop("model"))
    with pytest.raises(ValueError): validate_hindcasts(case, [snapshot], paths=1, periods=1)


def _synthetic_archive(case, model):
    historical = deepcopy(case)
    historical.update(asOf=model["asOf"], nodes=model["nodes"], mechanisms=model["mechanisms"],
                      sources=model["sources"], claims=[], actors=[])
    historical["resolution"].update(horizon=model["horizon"], units="USD billion")
    return historical


def test_supplied_synthetic_realized_snapshot_is_retrospective_only(case):
    from app.services.target_simulation import validate_hindcasts
    snapshot = _publisher_snapshots(case)[0]
    snapshot.update(kind="realized_outcome", evidenceKind="synthetic_fixture")
    snapshot["model"]["sources"][0]["retrievedAt"] = "2024-08-28T00:00:00Z"
    snapshot["case"] = _synthetic_archive(case, snapshot.pop("model"))
    snapshot["comparison"].update(valueKind="realized_observation", publishedAt="2026-01-01")
    result = validate_hindcasts(case, [snapshot], paths=1, periods=1)
    assert result["realizedOutcomeChecks"] == 1
    assert result["rows"][0]["evidenceKind"] == "synthetic_fixture"
    assert result["prospectiveSkill"] == "unmeasured"


def test_2027_no_decision_baseline_is_explicit_extrapolation_from_publisher_forecast(case):
    publisher = _PUBLISHER_VINTAGES[1]
    case["question"] = "Worldwide information-security spending through end-2027 under an assumed repeated growth rate."
    case["sources"][0].update(url=publisher["url"], title="Gartner July 2025 publisher vintage",
        publishedAt=publisher["date"], retrievedAt="2026-10-27", passage=publisher["passage"])
    _by_node(case, "base").update(value=240.0, range={"low": 240.0, "high": 240.0},
        units="USD billion", status="contested", claimIds=[], vintage="2025-07-29",
        label="2026 publisher forecast anchor; not a settled observation")
    _by_node(case, "rate").update(value=.125, range={"low": .125, "high": .125}, status="unknown",
        vintage=None, sourceIds=[], claimIds=[], basis="assumed", gap="Repeat 12.5 percent growth into 2027; not a publisher 2027 forecast.")
    _by_node(case, "target")["units"] = "USD billion"
    case["claims"] = []
    case["resolution"].update(horizon="2027-12-31", units="USD billion")
    case["actors"] = [_actor()]
    result = runtime_run_paths(case, paths=3, periods=2, model_validation="strict", decision_provider=lambda o: [],
        interventions=[{"interventionId": "rate-15-percent", "settings": [{"actorId": "a", "leverId": "a-lever", "value": .15}]}])
    assert result["baselineSummary"]["mean"] == pytest.approx(270)
    assert result["targetSummary"]["mean"] == pytest.approx(270)
    assert result["interventionTables"][0]["targetSummary"]["mean"] == pytest.approx(276)
    assert result["interventionTables"][0]["pairedDeltaSummary"]["mean"] == pytest.approx(6)


@pytest.mark.parametrize("kind", ["growth", "linear"])
def test_actual_runtime_output_reaches_strict_report_and_registration(case, tmp_path, monkeypatch, kind):
    from datetime import datetime, timezone
    from app.services import target_report
    case["assessments"][0]["scenarioWeights"] = {"low": .4, "high": .6, "other": 0.0}
    case["binaries"][0]["probability"] = .6
    case["actors"] = [_actor(lag=1)]
    if kind == "linear":
        case["mechanisms"][0].update(kind="linear", parameters={"coefficients": [1.0, 100.0], "intercept": 0.0})
    result = runtime_run_paths(case, paths=2, periods=3, lookahead=True,
        decision_provider=lambda obs: {"actorId": obs["actorId"], "leverId": obs["levers"][0]["leverId"], "value": .4},
        interventions=[{"interventionId": "declared", "settings": [{"actorId": "a", "leverId": "a-lever", "value": .3}]}],
        conditions=[{"conditionId": "tail", "predicate": {"nodeId": "target", "operator": "gte", "value": 110}}])
    bundle = target_report.build_target_report(case, result)
    assert bundle["forecast"]
    monkeypatch.setattr(target_report, "_utcnow", lambda: datetime(2026, 10, 27, 12, tzinfo=timezone.utc))
    record = target_report.register_comparison(tmp_path / f"{kind}.json", case, result, enrolled_at="2026-10-27T12:00:00Z")
    assert record["structuralArm"] == result["scenarioShares"]
    assert record["policy"]["simulationWeight"] == 0


def test_llm_roster_is_capped_before_callbacks(case):
    for index in range(9):
        actor = _actor(f"institution-{index}")
        case["actors"].append(actor)
    calls = []
    with pytest.raises(ValueError, match="eight"):
        runtime_run_paths(case, paths=1, periods=1, decision_provider=lambda o: calls.append(o))
    assert not calls
    case["actors"].pop()
    runtime_run_paths(case, paths=1, periods=1, decision_provider=lambda o: calls.append(o) or [])
    assert len(calls) == 8


@pytest.mark.parametrize(("kind", "inputs", "parameters", "output_units", "valid"), [
    ("sum", ["base", "rate"], {}, "USD", False),
    ("product", ["base", "rate"], {}, "USD", True),
    ("linear", ["base"], {"coefficients": [2], "intercept": 0}, "USD", True),
    ("supply_demand", ["base", "rate"], {}, "USD", False),
    ("adoption", ["base", "rate"], {"rate": .5}, "USD", False),
    ("regulatory_milestone", [], {"milestonePeriod": 1, "before": 0, "after": 1}, "USD", True),
])
def test_template_dimension_rules_are_specific(case, kind, inputs, parameters, output_units, valid):
    from app.services.target_mechanisms import validate_model
    _by_node(case, "base")["units"] = "USD"
    _by_node(case, "target")["units"] = output_units
    case["mechanisms"][0].update(kind=kind, inputNodeIds=inputs, parameters=parameters)
    result = validate_model(case)
    assert (result["dimensionChecks"][0]["status"] == "passed") is valid


def test_invalid_intervention_model_does_not_renormalize_failed_paths(case):
    _adoption_case(case)
    actor = _actor(node_id="base")
    actor["levers"][0].update(minimum=0, maximum=200)
    case["actors"] = [actor]
    result = runtime_run_paths(case, paths=2, periods=1, decision_provider=lambda o: [],
        interventions=[{"interventionId": "infeasible", "settings": [{"actorId": "a", "leverId": "a-lever", "value": 150}]}])
    table = result["interventionTables"][0]
    assert table["status"] == "infeasible_model"
    assert len(table["invalidPathIds"]) == 2
    assert table["scenarioShares"] is None and table["targetSummary"] is None
    assert result["targetSummary"]["mean"] == 90
