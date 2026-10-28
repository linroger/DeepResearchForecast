"""MR-1/MR-2: settlement model admission through actual typed consumers.

Fixtures are synthetic. Run only with the existing guarded offline runner.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from deerflow_bridge.forecast_case import CaseValidationError, validate_case
from app.services.target_actors import validate_scenarios
from app.services.target_mechanisms import MechanismValidationError, validate_model
from app.services.target_simulation import run_paths


@pytest.fixture
def case():
    return json.loads((Path(__file__).parent / "fixtures" / "target_case.json").read_text())


def node(case, node_id):
    return next(row for row in case["nodes"] if row["nodeId"] == node_id)


@pytest.mark.parametrize("contradiction", ["scale", "currency", "rate_scale", "seed"])
def test_known_contradictions_fail_admission_before_actor_callback(case, contradiction):
    """Known arithmetic contradictions cannot become successful production paths."""
    from app.services.target_mechanisms import admit_model

    if contradiction == "scale":
        node(case, "base")["units"] = "USD million"
    elif contradiction == "currency":
        node(case, "base")["units"] = "EUR billion"
    elif contradiction == "rate_scale":
        node(case, "trend")["units"] = "percent"
    else:
        node(case, "spending")["value"] = 290.0
    # The wire shape is legal; this is a model admission check, not JSON repair.
    validate_case(case)
    with pytest.raises(MechanismValidationError, match="model admission"):
        admit_model(case)
    calls = []
    case["actors"][0]["decisionRule"]["kind"] = "llm"
    with pytest.raises(MechanismValidationError, match="model admission"):
        run_paths(case, paths=1, periods=1, model_validation="admission",
                  decision_provider=lambda observation: calls.append(observation))
    assert calls == []


def test_admission_retains_valid_controlled_case_and_paths(case):
    from app.services.target_mechanisms import admit_model

    before = deepcopy(case)
    receipt = admit_model(case)
    assert receipt["status"] == "passed"
    assert receipt["policy"] == "known-contradictions/v1"
    assert all(row["status"] == "passed" for row in receipt["dimensionChecks"] + receipt["seedChecks"])
    admitted = run_paths(case, paths=2, periods=3, model_validation="admission")
    ordinary = run_paths(case, paths=2, periods=3)
    assert admitted.pop("modelValidation") == receipt
    assert admitted == ordinary
    assert case == before


def test_missing_seed_evidence_is_unmeasured_not_an_asserted_pass(case):
    from app.services.target_mechanisms import admit_model

    node(case, "spending")["value"] = None
    receipt = admit_model(case)
    assert receipt["status"] == "unmeasured"
    assert any(row["status"] == "unmeasured" for row in receipt["seedChecks"])
    result = run_paths(case, paths=1, periods=1, model_validation="admission")
    assert result["modelValidation"] == receipt
    assert result["paths"][0]["targetValue"] == pytest.approx(282.5)


def test_unsupported_units_are_retained_and_never_reported_as_validated(case):
    from app.services.target_mechanisms import admit_model

    node(case, "base")["units"] = "unmodeled-unit"
    receipt = admit_model(case)
    assert receipt["status"] == "unsupported"
    assert any(row["status"] == "unsupported" and row["unsupportedUnits"]
               for row in receipt["dimensionChecks"])
    result = run_paths(case, paths=1, periods=1, model_validation="admission")
    assert result["modelValidation"] == receipt
    # The existing stricter diagnostic API retains its documented semantics.
    assert validate_model(case)["status"] == "failed"
    with pytest.raises(MechanismValidationError):
        run_paths(case, paths=1, periods=1, model_validation="strict")


def test_unsupported_unit_does_not_hide_an_independent_seed_contradiction(case):
    from app.services.target_mechanisms import admit_model

    node(case, "base")["units"] = "unmodeled-unit"
    node(case, "spending")["value"] = 290.0
    with pytest.raises(MechanismValidationError, match="model admission"):
        admit_model(case)


@pytest.mark.parametrize("kind", ["growth", "sum"])
def test_unknown_unit_does_not_mask_known_dimensions_in_same_equation(case, kind):
    from app.services.target_mechanisms import admit_model

    if kind == "growth":
        node(case, "growth")["units"] = "unmodeled-unit"
        node(case, "base")["units"] = "EUR billion"
    else:
        node(case, "shock")["units"] = "unmodeled-unit"
        node(case, "trend")["units"] = "percent"
    diagnostics = validate_model(case)
    checks = [row for row in diagnostics["dimensionChecks"]
              if row["kind"] == kind and row["status"] == "failed"]
    assert checks and checks[0]["unsupportedUnits"]
    with pytest.raises(MechanismValidationError, match="model admission"):
        admit_model(case)


@pytest.mark.parametrize("consumer", [validate_case, validate_scenarios, run_paths])
def test_settlement_scenarios_cannot_classify_a_driver(case, consumer):
    for scenario in case["scenarios"]:
        scenario["predicate"]["nodeId"] = "trend"
    with pytest.raises(ValueError, match="resolution target"):
        consumer(case)


def test_driver_conditions_remain_valid_for_binaries_triggers_and_plans(case):
    predicate = {"nodeId": "regulation", "operator": "gte", "value": 0.01}
    case["actors"][0]["decisionRule"]["triggers"] = [deepcopy(predicate)]
    case["actors"][0]["plans"][0]["condition"] = deepcopy(predicate)
    case["binaries"].append({"binaryId": "driver", "question": "Synthetic regulation reaches 0.01?",
                             "predicate": deepcopy(predicate), "probability": 0.5, "sourceIds": []})
    assert validate_case(case)["binaries"][-1]["predicate"] == predicate
    result = run_paths(case, paths=1, periods=2, model_validation="admission",
                       conditions=[{"conditionId": "driver-condition", "predicate": predicate}])
    assert result["modelValidation"]["status"] == "passed"
    assert result["scenarioShares"] == {"below": 0.0, "above": 1.0, "other": 0.0}


def test_single_wrong_target_scenario_also_fails(case):
    case["scenarios"] = case["scenarios"][:1]
    case["scenarios"][0]["predicate"]["nodeId"] = "trend"
    case["assessments"] = [{"assessmentId": "prior", "version": 1, "kind": "prior",
                            "scenarioWeights": {"below": 1.0}, "updates": []}]
    with pytest.raises(CaseValidationError, match="resolution target"):
        validate_case(case)


def test_legacy_prebound_predicate_validator_remains_compatible():
    """The legacy reducer binds its target before calling this shared helper."""
    from app.services.worldstate import WorldState

    scenarios = {"below": {"nodeId": "target", "operator": "lt", "value": 10},
                 "above": {"nodeId": "target", "operator": "gte", "value": 10}}
    world = WorldState(list(scenarios), share_prior="uniform", share_source="predicates",
                       scenario_predicates=scenarios, target_node_id="target", inertia=0)
    world.step_from_source([], target_values={"target": 12})
    assert world.shares == {"below": 0.0, "above": 1.0}
