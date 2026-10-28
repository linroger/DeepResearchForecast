"""Owned producer/consumer regressions for approved part2 A1/A2/F6/F7."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.config import Config
from app.services import forecast_extractor as fe
from app.services.forecast_aggregator import (aggregate_forecast, default_aggregation_policy,
    estimator_from_forecast, pin_aggregation_policy, validate_estimator)
from app.services.forecast_tournament import run_forecast_tournament
from app.utils.actors import forecast_inputs_block, research_prior_from_actors


@pytest.fixture
def case():
    return json.loads((Path(__file__).parent / "fixtures/target_case.json").read_text())


def forecast():
    return {"scenarios": [{"name": "low", "probability": 0.123456789012345},
                           {"name": "high", "probability": 0.876543210987655}],
            "binary_forecasts": [{"id": "B1", "probability": 0}, {"id": "B2", "probability": 1}],
            "key_uncertainties": []}


def lane(base, source, probabilities):
    result = deepcopy(base)
    result.update(source=source, kind=source, rationale="Documented test method.")
    result["scenario_distribution"] = dict(zip(result["scenario_distribution"], probabilities))
    return result


def test_identity_keeps_exact_numbers_and_detaches_inputs():
    original = forecast()
    authority = estimator_from_forecast(original)
    shadow = lane(authority, "simulation", [0.999, 0.001])
    before = json.dumps(original, sort_keys=True)
    out = aggregate_forecast(original, [authority, shadow])
    assert json.dumps({k: out[k] for k in original}, sort_keys=True) == before
    out["scenarios"][0]["probability"] = 0.9
    assert json.dumps(original, sort_keys=True) == before


@pytest.mark.parametrize("field,value", [("simulation", 0.1), ("structural", 0.1)])
def test_never_promotes_simulated_lanes(field, value):
    policy = default_aggregation_policy()
    policy["method"] = "weighted_log_odds"
    policy["weights"][field] = value
    with pytest.raises(ValueError, match="cannot be promoted"):
        pin_aggregation_policy(policy)


def test_weighted_log_odds_requires_explicit_policy_and_pools_known_rows():
    original = forecast()
    original["scenarios"][0]["probability"] = 0.2
    original["scenarios"][1]["probability"] = 0.8
    authority = estimator_from_forecast(original)
    trend = lane(authority, "trend", [0.5, 0.5])
    policy = default_aggregation_policy()
    policy["weights"]["trend"] = 1
    with pytest.raises(ValueError, match="identity"):
        pin_aggregation_policy(policy)
    policy["method"] = "weighted_log_odds"
    out = aggregate_forecast(original, [authority, trend], policy)
    assert out["scenarios"][0]["probability"] == pytest.approx(1/3)
    assert out["scenarios"][1]["probability"] == pytest.approx(2/3)
    assert out["binary_forecasts"][0]["probability"] == pytest.approx(0.03)
    assert out["binary_forecasts"][1]["probability"] == pytest.approx(0.97)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, -0.1, 1.1])
def test_bad_estimator_probabilities_rejected(bad):
    row = estimator_from_forecast(forecast())
    row["binaries"][0]["p"] = bad
    with pytest.raises(ValueError):
        validate_estimator(row)


def test_policy_pin_is_detached_and_not_changed_by_environment(monkeypatch):
    p = default_aggregation_policy()
    pinned = pin_aggregation_policy(p)
    p["weights"]["spine"] = 0
    monkeypatch.setattr(Config, "REPORT_TOURNAMENT", False, raising=False)
    assert pinned["weights"]["spine"] == 1
    assert pin_aggregation_policy(pinned) == pinned


class Gateway:
    def __init__(self, output=None):
        self.calls = []
        self.output = output

    def chat_json(self, **kwargs):
        self.calls.append(kwargs)
        return deepcopy(self.output or {"scenario_distribution": {"low": 0.4, "high": 0.6},
                       "binaries": [], "rationale": "S1 dated comparators.", "cruxes": ["S1 growth persistence"]})


def test_tournament_bounded_diverse_injected_gateway_and_shadow_invariance():
    gateway = Gateway()
    original = forecast()
    evidence = {"quantitative_rows": [{"date": "2026-01-01", "value": 3, "sourceIds": ["S1"]}]}
    plain = run_forecast_tournament(original, llm=gateway, evidence=evidence, enabled=True)
    assert len(gateway.calls) == 3
    assert len({c["messages"][0]["content"].splitlines()[0] for c in gateway.calls}) == 3
    assert all(c["max_tokens"] == 2000 for c in gateway.calls)
    with_sim = run_forecast_tournament(original, llm=Gateway(), evidence=evidence, enabled=True,
        simulation={"scenarioShares": {"low": 0.1, "high": 0.8, "other": 0.1}, "simulationWeight": 0})
    assert {k: v for k, v in plain.items() if k != "estimators"} == {k: v for k, v in with_sim.items() if k != "estimators"}
    assert plain["estimators"] == [r for r in with_sim["estimators"] if r["source"] != "simulation"]
    assert with_sim["estimators"][-1]["scenario_distribution"]["other"] == 0.1
    for key in ("scenarios", "binary_forecasts"):
        assert json.dumps(plain[key]) == json.dumps(original[key])


def test_no_gateway_or_evidence_never_invents_method_estimates():
    out = run_forecast_tournament(forecast(), llm=None, enabled=True)
    assert all(e["status"] == "unavailable" for e in out["estimators"][1:])
    gateway = Gateway()
    run_forecast_tournament(forecast(), llm=gateway, enabled=True)
    assert gateway.calls == []
    disabled = run_forecast_tournament(forecast(), llm=gateway, enabled=False)
    assert len(disabled["estimators"]) == 1
    assert gateway.calls == []


def test_bad_gateway_reply_and_input_budget_degrade_without_secret_leak():
    gateway = Gateway({"scenario_distribution": {"made-up": 1}, "cruxes": []})
    out = run_forecast_tournament(forecast(), llm=gateway, enabled=True, evidence={"base_rates": ["known"]})
    assert all(e["status"] == "error" for e in out["estimators"][1:4])
    gateway = Gateway()
    out = run_forecast_tournament(forecast(), llm=gateway, enabled=True, evidence={"base_rates": ["x"*25000]})
    assert gateway.calls == []
    assert all(e["status"] == "unavailable" for e in out["estimators"][1:4])


def test_market_lane_requires_exact_stored_snapshot():
    original = forecast()
    original["binary_forecasts"][0]["market_anchor"] = {"market_id": "M1", "equivalence": "exact"}
    original["binary_forecasts"][1]["market_anchor"] = {"market_id": "M2", "equivalence": "near"}
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).isoformat()
    out = run_forecast_tournament(original, enabled=True, markets=[
        {"market_id": "M1", "implied_yes_prob": 0.25, "retrieved_at": stamp},
        {"market_id": "M2", "implied_yes_prob": 0.9, "retrieved_at": stamp}])
    market = next(e for e in out["estimators"] if e["source"] == "market_implied")
    assert market["binaries"] == [{"id": "B1", "p": 0.25}]
    assert out["binary_forecasts"] == original["binary_forecasts"]


def test_tree_entrypoint_ignores_quota_and_never_calls_gateway(case, monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_BINARIES_SOURCE", "tree", raising=False)
    gateway = Gateway()
    out = fe.extract_binary_forecasts("ignored prose", gateway, min_count=100, forecast_case=case)
    assert len(out["binary_forecasts"]) == 2
    assert gateway.calls == []
    b = out["binary_forecasts"][0]
    assert b["probability"] == case["binaries"][0]["probability"]
    assert b["source_ids"] == case["binaries"][0]["sourceIds"]
    assert b["predicate"] == case["binaries"][0]["predicate"]
    assert b["scenario_membership"] == {"derivable": True, "yes_scenarios": ["At least 280"]}
    assert b["resolution_contract"]["deadline"] == "2028-03-30"
    assert b["contract_valid"]


def test_tree_six_predicates_have_contracts_without_probability_quotas(case):
    case["binaries"] = [dict(case["binaries"][0], binaryId=f"B{i}", probability=p,
        predicate={"nodeId": "spending", "operator": "gte", "value": threshold})
        for i, (threshold, p) in enumerate([(270, 0.9), (275, 0.8), (285, 0.5), (290, 0.4), (295, 0.2), (300, 0.1)])]
    out = fe.derive_binaries_from_tree(case)
    assert len(out["binary_forecasts"]) == 8
    assert all(b["contract_valid"] for b in out["binary_forecasts"])
    assert all(not b["scenario_membership"]["derivable"] for b in out["binary_forecasts"][:6])


def test_tree_partial_region_never_infers_mass_and_extremes_stay_exact(case):
    case["binaries"][0].update(probability=0.123456789012345)
    case["binaries"][0]["predicate"]["value"] = 300
    out = fe.derive_binaries_from_tree(case)
    assert out["binary_forecasts"][0]["probability"] == 0.123456789012345
    assert not out["binary_forecasts"][0]["scenario_membership"]["derivable"]
    case["binaries"][0].update(probability=0)
    assert fe.derive_binaries_from_tree(case)["binary_forecasts"][0]["probability"] == 0


def test_tree_rejects_probability_contradictions_and_driver_settlement_inheritance(case):
    bad = deepcopy(case)
    bad["binaries"][0]["probability"] = 0.7
    with pytest.raises(ValueError, match="contradicts"):
        fe.derive_binaries_from_tree(bad)
    bad = deepcopy(case)
    bad["binaries"][0]["predicate"]["nodeId"] = "trend"
    with pytest.raises(ValueError, match="resolution contract"):
        fe.derive_binaries_from_tree(bad)


def test_tree_reconciliation_uses_declared_memberships(case):
    out = fe.derive_binaries_from_tree(case)
    state = {**out, "scenarios": [{"name": "Below 280", "probability": 0.4}, {"name": "At least 280", "probability": 0.6}]}
    original = [b["probability"] for b in state["binary_forecasts"]]
    fe.reconcile_forecast_contract(state)
    assert [b["probability"] for b in state["binary_forecasts"]] == original


def test_binary_quality_grade_diagnostics_and_fail_rollback(monkeypatch):
    rows = [{"probability": 0.5, "criteria_sharp": True} for _ in range(13)]
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MODE", "grade", raising=False)
    grade = fe._binary_quality(rows, min_count=10)
    assert "passed" not in grade
    assert grade["legacy_passed"] is False
    assert grade["sharpness"]["midband_share"] == 1
    assert grade["epistemic_issues"]
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MODE", "fail")
    old = fe._binary_quality(rows, min_count=10)
    assert old["passed"] is False
    assert "sharpness" not in old and "legacy_passed" not in old


def test_research_prior_rendering_and_prompt_rollback(monkeypatch):
    actors = {"as_of_date": "2026-10-27", "forecast_inputs": {"scenarios": [
        {"name": "low", "probability": 0.4}, {"name": "high", "probability": 0.6}]}}
    monkeypatch.setattr(Config, "REPORT_SPINE_RESEARCH_PRIOR", False, raising=False)
    old = forecast_inputs_block(actors)
    assert "research prior" not in old and research_prior_from_actors(actors) is None
    monkeypatch.setattr(Config, "REPORT_SPINE_RESEARCH_PRIOR", True)
    assert "research prior 0.4" in forecast_inputs_block(actors)
    assert "dated 2026-10-27" in forecast_inputs_block(actors)
    prior = research_prior_from_actors(actors)
    monkeypatch.setattr(Config, "FORECAST_PROB_FLOOR", 0, raising=False)
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 1, raising=False)
    raw = {"scenarios": [{"name": "low", "probability": 0.3}, {"name": "high", "probability": 0.7}],
           "scenario_updates": [{"name": "low", "prior": 0.4, "posterior": 0.3, "reason": "S1"},
                                {"name": "high", "prior": 0.6, "posterior": 0.7, "reason": "S1"}]}
    gateway = Gateway(raw)
    result = fe.derive_forecast_spine(gateway, research_prior=prior)
    assert result["scenarios"][0]["prior"] == 0.4
    assert result["scenario_updates"][0]["posterior"] == result["scenarios"][0]["probability"]
    monkeypatch.setattr(Config, "REPORT_SPINE_RESEARCH_PRIOR", False)
    a, b = Gateway(raw), Gateway(raw)
    fe.derive_forecast_spine(a, research_prior=prior)
    fe.derive_forecast_spine(b)
    assert a.calls == b.calls


@pytest.mark.parametrize("change", ["missing", "posterior", "reason"])
def test_prior_update_contract_rejects_unaccounted_changes(change):
    prior = {"scenarioWeights": {"low": 0.4, "high": 0.6}, "asOf": "2026-10-27"}
    output = {"scenarios": [{"name": "low", "probability": 0.3}, {"name": "high", "probability": 0.7}]}
    updates = [{"name": "low", "prior": 0.4, "posterior": 0.3, "reason": "S1"},
               {"name": "high", "prior": 0.6, "posterior": 0.7, "reason": "S1"}]
    if change == "missing": updates.pop()
    if change == "posterior": updates[0]["posterior"] = 0.5
    if change == "reason": updates[0]["reason"] = ""
    with pytest.raises(ValueError):
        fe.validate_prior_posterior_updates(output, prior, updates)


def test_explicit_single_lane_weighted_policy_obeys_floor_and_extremization():
    original = forecast()
    original["scenarios"] = [{"name": "low", "probability": 0.2}, {"name": "high", "probability": 0.8}]
    policy = default_aggregation_policy()
    policy.update(method="weighted_log_odds", extremize_a=2)
    out = aggregate_forecast(original, [estimator_from_forecast(original)], policy)
    assert out["scenarios"][0]["probability"] == pytest.approx(1/17)
    assert out["binary_forecasts"][0]["probability"] > 0
    policy = default_aggregation_policy()
    policy["weights"]["trend"] = 1e-20
    with pytest.raises(ValueError, match="identity"):
        pin_aggregation_policy(policy)


def test_method_prompt_changes_when_proposition_changes():
    original = forecast()
    original["binary_forecasts"][0]["statement"] = "Will A win the presidency in 2028?"
    a, b = Gateway(), Gateway()
    evidence = {"base_rates": ["S1 documented comparisons"]}
    run_forecast_tournament(original, llm=a, evidence=evidence, enabled=True)
    original["binary_forecasts"][0]["statement"] = "Will A win the senate in 2032?"
    run_forecast_tournament(original, llm=b, evidence=evidence, enabled=True)
    assert a.calls[0] != b.calls[0]
    assert "senate in 2032" in b.calls[0]["messages"][0]["content"]


def test_upstream_saved_estimators_replay_without_gateway_calls(case):
    from app.services.target_report import build_target_report
    from app.services.forecast_tournament import freeze_target_estimators
    from app.services.official_data import bridge_module
    original = build_target_report(case)["forecast"]
    policy = pin_aggregation_policy(authority="research")
    gateway = Gateway({"scenario_distribution": {"below": 0.3, "above": 0.7},
                       "binaries": [], "rationale": "S1", "cruxes": ["Trend persistence"]})
    frozen = freeze_target_estimators(case, original, policy, llm=gateway, enabled=True)
    assert len(gateway.calls) == 3
    forbidden = Gateway()
    simulation = {"caseId": case["caseId"], "caseHash": bridge_module("forecast_case").case_hash(case),
                  "simulationWeight": 0, "scenarioShares": {"below": 0.2, "above": 0.8, "other": 0}}
    replay = run_forecast_tournament(original, case=case, simulation=simulation, policy=policy,
                                    saved_estimators=frozen, llm=forbidden, enabled=True)
    assert forbidden.calls == []
    assert replay["estimators"][:-1] == frozen["estimators"]
    assert replay["scenarios"] == original["scenarios"]
    assert replay["binary_forecasts"] == original["binary_forecasts"]
    for field in ("case_hash", "policy_hash"):
        wrong = deepcopy(frozen)
        wrong[field] = "0"*64
        with pytest.raises(ValueError, match="identity mismatch"):
            run_forecast_tournament(original, case=case, policy=policy, saved_estimators=wrong)
    wrong = deepcopy(frozen)
    wrong["estimators"].append(replay["estimators"][-1])
    with pytest.raises(ValueError, match="simulation lanes"):
        run_forecast_tournament(original, case=case, policy=policy, saved_estimators=wrong)
    wrong = deepcopy(frozen)
    wrong["estimators"][0]["rationale"] = "tampered authority"
    with pytest.raises(ValueError, match="authority"):
        run_forecast_tournament(original, case=case, policy=policy, saved_estimators=wrong)


def test_research_prior_zero_and_subfloor_probability_are_preserved(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SPINE_RESEARCH_PRIOR", True, raising=False)
    monkeypatch.setattr(Config, "FORECAST_PROB_FLOOR", 0.03, raising=False)
    actors = {"forecast_inputs": {"scenarios": [{"name": "low", "probability": 0}, {"name": "high", "probability": 1}]}}
    prior = research_prior_from_actors(actors)
    assert prior["scenarioWeights"]["low"] == 0
    raw = {"scenarios": [{"name": "low", "probability": 0.00123456789}, {"name": "high", "probability": 0.99876543211}],
           "scenario_updates": [{"name": "low", "prior": 0, "posterior": 0.00123456789, "reason": "S1"},
                                {"name": "high", "prior": 1, "posterior": 0.99876543211, "reason": "S1"}]}
    out = fe.derive_forecast_spine(Gateway(raw), research_prior=prior)
    assert out["scenarios"][0]["probability"] == 0.00123456789


def test_tree_driver_own_contract_and_declared_membership_validation(case):
    binary = case["binaries"][0]
    binary["predicate"] = {"nodeId": "trend", "operator": "gte", "value": 0.1}
    binary["resolution_contract"] = {"kind": "named_source_event", "publisher": "Synthetic statistics", "event": "Trend reached 0.1", "deadline": "2027-06-01"}
    out = fe.derive_binaries_from_tree(case)
    assert out["binary_forecasts"][0]["resolution_contract"]["deadline"] == "2027-06-01"
    binary["scenario_membership"] = {"derivable": True, "yes_scenarios": ["At least 280"]}
    with pytest.raises(ValueError, match="contradicts typed predicate"):
        fe.derive_binaries_from_tree(case)


def test_tree_exact_market_adapts_stored_snapshot_without_changing_p(case):
    case["binaries"][0]["resolution_contract"] = {"kind": "polymarket", "market_id": "M1", "equivalence": "exact"}
    market = {"market_id": "M1", "implied_yes_prob": 0.73, "question": case["binaries"][0]["question"],
              "url": "https://example.test/market", "endDate": "2027-12-31"}
    out = fe.derive_binaries_from_tree(case, markets=[market])
    row = out["binary_forecasts"][0]
    assert row["probability"] == 0.6
    assert row["market_anchor"]["resolution_equivalence"] == "exact"
    assert fe._market_anchor_binding_valid(row, row["market_anchor"])
    with pytest.raises(ValueError, match="stored snapshot"):
        fe.derive_binaries_from_tree(case, markets=[])


def test_tree_official_contract_binds_existing_carrier_with_native_units(case):
    carrier = json.loads((Path(__file__).parent / "fixtures/data_sources/real/forecast_carrier-2026-10-11.json").read_text())
    node = case["nodes"][1]
    node.update(label="US unemployment rate", units="Percent")
    binary = case["binaries"][0]
    binary.update(question="Will the US unemployment rate be at least 5% in June 2027?",
                  predicate={"nodeId": "trend", "operator": "gte", "value": 5})
    binary["resolution_contract"] = {"kind": "official_data", "series": "fred:UNRATE", "comparator": ">=", "threshold": 5, "period": "2027-06", "units": "Percent"}
    out = fe.derive_binaries_from_tree(case, official_data=carrier)
    row = out["binary_forecasts"][0]
    assert row["probability"] == 0.6
    assert row["data_anchor"]["series"] == "fred:UNRATE"
    assert row["data_anchor"]["frequency"] == "M"
    node["units"] = "USD billion"
    with pytest.raises(ValueError, match="stored snapshot"):
        fe.derive_binaries_from_tree(case, official_data=carrier)


def test_tree_reconcile_rejects_tampering_instead_of_changing_authority(case):
    out = fe.derive_binaries_from_tree(case)
    out["scenarios"] = [{"name": "Below 280", "probability": 0.4}, {"name": "At least 280", "probability": 0.6}]
    out["binary_forecasts"][0]["probability"] = 0.8
    with pytest.raises(ValueError, match="typed binary probability contradicts"):
        fe.reconcile_forecast_contract(out)


def test_prior_self_consistency_ledger_equals_final_pooled_probabilities(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SPINE_RESEARCH_PRIOR", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 2, raising=False)
    raw = {"scenarios": [{"name": "low", "probability": 0.3}, {"name": "high", "probability": 0.7}],
           "scenario_updates": [{"name": "low", "prior": 0.4, "posterior": 0.3, "reason": "S1"},
                                {"name": "high", "prior": 0.6, "posterior": 0.7, "reason": "S1"}]}
    gateway = Gateway(raw)
    out = fe.derive_forecast_spine(gateway, research_prior={"scenarioWeights": {"low": 0.4, "high": 0.6}})
    assert len(gateway.calls) == 2
    assert out["self_consistency_k"] == 2
    assert all(u["posterior"] == next(s["probability"] for s in out["scenarios"] if s["name"] == u["name"]) for u in out["scenario_updates"])


@pytest.mark.parametrize("health_fields", [{}, {"retrieved_at": "2020-01-01"},
    {"status": "offline"}, {"status": "unavailable"}, {"status": "stale"}, {"cached": True}])
def test_market_estimator_excludes_unhealthy_snapshots(health_fields):
    from datetime import datetime, timezone
    original = forecast()
    original["binary_forecasts"][0]["market_anchor"] = {"market_id": "M1", "resolution_equivalence": "exact"}
    row = {"market_id": "M1", "implied_yes_prob": 0.25, **health_fields}
    if health_fields and "retrieved_at" not in health_fields:
        row["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    out = run_forecast_tournament(original, enabled=True, markets=[row])
    market = next(e for e in out["estimators"] if e["source"] == "market_implied")
    assert market["status"] == "unavailable" and market["binaries"] == []


@pytest.mark.parametrize("field", ["statement", "predicate", "resolution_contract", "source_ids", "probability"])
def test_saved_estimators_bind_complete_forecast_propositions(case, field):
    from app.services.target_report import build_target_report
    from app.services.forecast_tournament import freeze_target_estimators
    original = build_target_report(case)["forecast"]
    policy = pin_aggregation_policy(authority="research")
    saved = freeze_target_estimators(case, original, policy, enabled=True)
    changed = deepcopy(original)
    row = changed["binary_forecasts"][0]
    if field == "statement": row[field] = "Different event"
    elif field == "predicate": row[field]["value"] = 380
    elif field == "resolution_contract": row[field]["deadline"] = "2030-01-01"
    elif field == "source_ids": row[field] = []
    else: row[field] = 0.65
    with pytest.raises(ValueError, match="authority"):
        run_forecast_tournament(changed, case=case, policy=policy, saved_estimators=saved, enabled=True)


def test_upstream_estimator_freeze_rejects_foreign_forecast_identity(case):
    from app.services.target_report import build_target_report
    from app.services.forecast_tournament import freeze_target_estimators
    original = build_target_report(case)["forecast"]
    original["case_id"] = "different-case"
    with pytest.raises(ValueError, match="case identity"):
        freeze_target_estimators(case, original, pin_aggregation_policy(authority="research"))


def test_market_estimator_preserves_native_envelope_health():
    from datetime import datetime, timezone
    from app.services.forecast_tournament import _market_lane
    original = forecast()
    original['binary_forecasts'][0]['market_anchor'] = {'market_id': 'M1', 'resolution_equivalence': 'exact'}
    stamp = datetime.now(timezone.utc).isoformat()
    snapshot = {'market_id': 'M1', 'implied_yes_prob': 0.73, 'retrieved_at': stamp}
    payload = {'markets': [snapshot], 'as_of': stamp, 'status': {'state': 'ok'}, 'cache': {'hit': False}}
    fresh = _market_lane(original, payload)
    assert fresh['status'] == 'ok'
    payload['cache']['hit'] = True
    stale = _market_lane(original, payload)
    assert stale['status'] == 'unavailable' and stale['binaries'] == []
    payload['cache']['hit'] = False
    payload['status']['state'] = 'transport_failure'
    assert _market_lane(original, payload)['status'] == 'unavailable'
