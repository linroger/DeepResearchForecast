"""Contract tests use synthetic evidence, never a provider or saved run."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from deerflow_bridge.forecast_case import (
    CaseValidationError, case_hash, graph_projection, read_case, report_projection,
    simulation_projection, validate_case, write_case,
)


def make_case():
    """Independent complete 2027 five-input fixture, reusable by consumers."""
    return json.loads((Path(__file__).parent / "fixtures" / "target_case.json").read_text())


@pytest.fixture
def case():
    return make_case()


def set_path(case, path, value):
    target = case
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def test_fixture_valid_and_normalized_copy(case):
    result = validate_case(case)
    assert result == case and result is not case
    result["nodes"][0]["value"] = 1
    assert case["nodes"][0]["value"] == 250
    assert case["sources"][0]["passage"].startswith("The synthetic")
    assert len(case["mechanisms"][0]["inputNodeIds"]) == 4


@pytest.mark.parametrize(("path", "value"), [
    (("revision",), True), (("revision",), 0), (("authority",), "legacy"),
    (("asOf",), "2026-02-30"), (("resolution", "targetNodeId"), "absent"),
    (("resolution", "units"), "USD"), (("resolution", "settlementSource", "releaseLagDays"), -1),
    (("sources", 0, "sourceId"), "http://bad-id"), (("sources", 0, "tier"), "social"),
    (("sources", 0, "fetched"), False), (("sources", 0, "fetched"), 1),
    (("sources", 0, "passage"), ""), (("sources", 0, "publishedAt"), "2026-10-28"),
    (("sources", 0, "retrievedAt"), "2026-10-27T01:00:00"),
    (("sources", 0, "url"), "file:///etc/passwd"),
    (("sources", 0, "url"), "https://user:secret@example.test/"),
    (("nodes", 0, "value"), True), (("nodes", 0, "value"), float("nan")),
    (("nodes", 0, "range", "high"), float("inf")), (("nodes", 0, "range", "high"), 200),
    (("nodes", 0, "vintage"), None), (("nodes", 0, "vintage"), "2027-01-01"),
    (("nodes", 0, "retrievalCost"), 0), (("nodes", 0, "evidenceAvailability"), 1.1),
    (("nodes", 0, "sourceIds"), ["S8"]), (("nodes", 0, "claimIds"), ["C2"]),
    (("nodes", 2, "gap"), ""), (("nodes", 2, "basis"), "observed"),
    (("nodes", 2, "range"), None), (("nodes", 4, "ownerActorId"), "absent"),
    (("claims", 0, "sourceIds"), []), (("claims", 0, "nodeId"), "trend"),
    (("mechanisms", 0, "inputNodeIds"), ["absent"]), (("mechanisms", 0, "kind"), "eval"),
    (("mechanisms", 0, "parameters"), {"expression": "__import__('os')"}),
    (("mechanisms", 0, "gap"), ""), (("mechanisms", 1, "sourceIds"), []),
    (("actors", 0, "information", "nodeIds"), ["ai"]),
    (("actors", 0, "levers"), []), (("actors", 0, "constraints", "capacity"), -1),
    (("actors", 0, "decisionRule", "cadencePeriods"), 0),
    (("actors", 0, "levers", 0, "requiresConsent"), ["missing"]),
    (("actors", 0, "levers", 0, "nodeId"), "spending"),
    (("actors", 0, "plans", 0, "value"), 100),
    (("actors", 0, "plans", 0, "leverId"), "deploy"),
    (("actors", 0, "plans", 0, "duePeriod"), True),
    (("actors", 0, "credibility"), 2),
    (("scenarios", 1, "predicate", "operator"), "gt;eval"),
    (("scenarios", 0, "predicate", "operator"), "lte"),
    (("assessments", 1, "version"), 1),
    (("assessments", 1, "scenarioWeights", "above"), 0.7),
    (("assessments", 1, "updates", 0, "oldWeight"), 0.6),
    (("assessments", 1, "updates", 0, "newWeight"), 0.3),
    (("assessments", 1, "updates", 0, "size"), 0.2),
    (("assessments", 1, "updates", 0, "direction"), "increase"),
    (("assessments", 1, "updates", 0, "evidenceId"), "missing"),
    (("assessments", 1, "updates", 0, "nodeId"), "ai"),
    (("assessments", 1, "updates"), []),
    (("binaries", 0, "predicate", "nodeId"), "missing"),
    (("binaries", 0, "probability"), 1.01),
])
def test_malformed_contracts_fail(case, path, value):
    set_path(case, path, value)
    with pytest.raises(CaseValidationError):
        validate_case(case)


@pytest.mark.parametrize("collection", ["nodes", "sources", "claims", "mechanisms", "actors", "scenarios", "assessments", "binaries"])
def test_duplicate_ids_rejected(case, collection):
    case[collection].append(copy.deepcopy(case[collection][0]))
    with pytest.raises(CaseValidationError, match="duplicate"):
        validate_case(case)


def test_cycles_and_duplicate_writers(case):
    case["mechanisms"][0]["inputNodeIds"].append("spending")
    with pytest.raises(CaseValidationError, match="cyclic"):
        validate_case(case)
    case = make_case()
    case["mechanisms"][1]["outputNodeId"] = "growth"
    with pytest.raises(CaseValidationError, match="duplicate output"):
        validate_case(case)


def test_missing_publication_date_stays_unknown(case):
    case["sources"][0]["publishedAt"] = None
    assert validate_case(case)["sources"][0]["publishedAt"] is None


def test_source_primary_not_just_node_tier(case):
    secondary = copy.deepcopy(case["sources"][0])
    secondary.update(sourceId="S2", tier="social")
    case["sources"].append(secondary)
    case["nodes"][0]["sourceIds"].append("S2")
    case["claims"][0]["sourceIds"] = ["S2"]
    with pytest.raises(CaseValidationError, match="primary"):
        validate_case(case)


def test_unknown_leaf_explicit_assumptions(case):
    case["nodes"][2]["value"] = None
    assert validate_case(case)["nodes"][2]["range"] == {"low": 0.0, "high": 0.03}
    del case["nodes"][2]["gap"]
    with pytest.raises(CaseValidationError, match="gap"):
        validate_case(case)


def test_finite_json_cyclic_nonstring_and_deep(case):
    for bad in (object(), (1, 2), {1: 2}):
        broken = copy.deepcopy(case)
        broken["surprise"] = bad
        with pytest.raises(CaseValidationError):
            validate_case(broken)
    case["cycle"] = case
    with pytest.raises(CaseValidationError, match="cyclic"):
        validate_case(case)
    nested = 0
    for _ in range(70):
        nested = [nested]
    with pytest.raises(CaseValidationError, match="depth"):
        validate_case(nested)


def test_predicate_boundaries_and_explicit_other(case):
    case["scenarios"][1]["predicate"] = {"nodeId": "spending", "operator": "between", "low": 281, "high": 300}
    case["assessments"] = [case["assessments"][0]]
    case["assessments"][0]["scenarioWeights"] = {"below": 0.4, "above": 0.4, "other": 0.2}
    assert validate_case(case)["assessments"][0]["scenarioWeights"]["other"] == 0.2
    case["scenarios"][0]["predicate"] = {"nodeId": "spending", "operator": "between", "low": 250, "high": 281}
    with pytest.raises(CaseValidationError, match="overlap"):
        validate_case(case)


def test_unobservable_trigger_is_rejected(case):
    case["actors"][1]["decisionRule"]["triggers"] = [{"nodeId": "shock", "operator": "gt", "value": 0.01}]
    with pytest.raises(CaseValidationError, match="information"):
        validate_case(case)


def test_assessment_distribution_and_duplicate_updates(case):
    case["assessments"][1]["targetDistribution"] = {"mean": 282.5, "quantiles": {"0.1": 270, "0.9": 300}}
    assert validate_case(case)
    case["assessments"][1]["targetDistribution"]["quantiles"]["0.1"] = 400
    with pytest.raises(CaseValidationError, match="monotone"):
        validate_case(case)
    case = make_case()
    case["assessments"][1]["updates"].append(copy.deepcopy(case["assessments"][1]["updates"][0]))
    with pytest.raises(CaseValidationError, match="duplicate"):
        validate_case(case)


def test_projection_probability_and_prose_isolation(case):
    before = simulation_projection(case)
    case["assessments"] = [case["assessments"][0]]
    case["assessments"][0]["scenarioWeights"] = {"below": 0.01, "above": 0.99}
    case["binaries"][0]["probability"] = 0.99
    case["revision"] += 1
    case["question"] = "PROSE_SECRET"
    case["scenarios"][0]["label"] = "PROSE_SECRET"
    case["actors"][0]["decisionBasis"] = "PROSE_SECRET"
    case["nodes"][0]["label"] = "PROSE_SECRET"
    case["mechanisms"][0]["gap"] = "PROSE_SECRET"
    after = simulation_projection(case)
    assert before == after
    assert "PROSE_SECRET" not in json.dumps(after)
    assert all("label" not in row for row in after["scenarios"])
    assert "assessments" not in after and "binaries" not in after
    after["nodes"][0]["value"] = 1
    assert case["nodes"][0]["value"] == 250


def test_report_and_graph_wire_shapes(case):
    report = report_projection(case)
    assert report["assessment"] == case["assessments"][-1]
    assert report["binaries"] == case["binaries"]
    assert report["simulationWeight"] == 0.0
    assert report["caseHash"] == case_hash(case)
    graph = graph_projection(case)
    assert graph == graph_projection(copy.deepcopy(case))
    ids = {row["uuid"] for row in graph["nodes"]}
    assert all({"uuid", "name", "labels", "summary", "attributes"} <= row.keys() for row in graph["nodes"])
    assert all({"uuid", "source_node_uuid", "target_node_uuid", "name", "fact"} <= row.keys() for row in graph["edges"])
    assert all(row["source_node_uuid"] in ids and row["target_node_uuid"] in ids for row in graph["edges"])
    assert "ai" not in {row["attributes"].get("nodeId") for row in graph["nodes"]}
    assert "Internal deployment" not in json.dumps(graph)


def test_hash_replay_and_tamper_control(case, tmp_path):
    path = tmp_path / "case.json"
    digest = write_case(path, case)
    assert digest == case_hash(dict(reversed(list(case.items()))))
    assert read_case(path, digest) == case
    before = path.read_bytes()
    assert write_case(path, case) == digest
    assert path.read_bytes() == before
    case["binaries"][0]["probability"] = 0.8
    path.write_text(json.dumps(case))
    with pytest.raises(CaseValidationError, match="hash mismatch"):
        read_case(path, digest)


def test_immutable_assessment_and_revision_control(case, tmp_path):
    path = tmp_path / "case.json"
    write_case(path, case)
    original = path.read_bytes()
    case["revision"] += 1
    case["assessments"][0]["assessmentId"] = "rewritten-prior"
    with pytest.raises(CaseValidationError, match="immutable"):
        write_case(path, case)
    assert path.read_bytes() == original
    case = make_case()
    case["binaries"][0]["probability"] = 0.7
    with pytest.raises(CaseValidationError, match="revision"):
        write_case(path, case)
    case["revision"] += 1
    write_case(path, case)
    assert read_case(path)["revision"] == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["case.json"]


def test_append_assessment_and_definition_fork(case, tmp_path):
    path = tmp_path / "case.json"
    write_case(path, case)
    case["revision"] += 1
    posterior = copy.deepcopy(case["assessments"][-1])
    posterior.update(assessmentId="posterior-3", version=3, updates=[])
    case["assessments"].append(posterior)
    write_case(path, case)
    assert len(read_case(path)["assessments"]) == 3
    case["revision"] += 1
    case["scenarios"][0]["label"] = "Revised definition"
    posterior = copy.deepcopy(posterior)
    posterior.update(assessmentId="posterior-4", version=4)
    case["assessments"].append(posterior)
    with pytest.raises(CaseValidationError, match="revision file"):
        write_case(path, case)
    write_case(tmp_path / "case-revision-4.json", case)


def test_atomic_failure_preserves_previous(case, tmp_path, monkeypatch):
    import deerflow_bridge.forecast_case as module
    path = tmp_path / "case.json"
    digest = write_case(path, case)
    case["revision"] += 1
    case["binaries"][0]["probability"] = 0.7

    def failure(*args):
        raise OSError("injected replace failure")

    monkeypatch.setattr(module.os, "replace", failure)
    with pytest.raises(OSError, match="injected"):
        write_case(path, case)
    assert read_case(path, digest)["revision"] == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["case.json"]


def test_strict_file_read_and_lock_controls(case, tmp_path):
    path = tmp_path / "case.json"
    path.write_text('{"caseId":"one","caseId":"two"}')
    with pytest.raises(CaseValidationError, match="duplicate"):
        read_case(path)
    path.write_text('{')
    with pytest.raises(CaseValidationError, match="malformed"):
        read_case(path)
    write_case(tmp_path / "valid.json", case)
    path.unlink()
    path.symlink_to(tmp_path / "valid.json")
    with pytest.raises(CaseValidationError, match="symlink"):
        write_case(path, case)
    with pytest.raises(CaseValidationError, match="symlink"):
        read_case(path)
    path.unlink()
    (tmp_path / "case.json.lock").touch()
    with pytest.raises(CaseValidationError, match="lock"):
        write_case(path, case)
    assert not path.exists()


def test_source_receipt_for_contract():
    """Pin production and shared fixture bytes in the guarded receipt."""
    import deerflow_bridge.forecast_case as module
    import sys
    guard = sys.modules.get("main_offline_guard")
    if guard is not None:
        for path in (Path(module.__file__), Path(__file__).parent / "fixtures" / "target_case.json"):
            guard.source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("parameter_sources", [None, []])
def test_parameter_effective_provenance_cannot_invent_observation(case, parameter_sources):
    mechanism = case["mechanisms"][0]
    coefficient = {"low": 1, "high": 1, "basis": "observed"}
    if parameter_sources is not None:
        coefficient["sourceIds"] = parameter_sources
    mechanism.update(kind="linear", parameters={"coefficients": [coefficient, 1, 1, 1], "intercept": 0})
    with pytest.raises(CaseValidationError, match="provenance"):
        validate_case(case)
    coefficient["sourceIds"] = ["S1"]
    assert validate_case(case)


@pytest.mark.parametrize(("kind", "inputs", "parameters"), [
    ("growth", ["base"], {}), ("sum", [], {}),
    ("linear", ["base"], {"coefficients": [], "intercept": 0}),
    ("linear", ["base"], {"coefficients": [[1]], "intercept": 0}),
    ("adoption", ["base", "growth"], {"rate": {"low": 0, "high": 2}}),
    ("regulatory_milestone", [], {"milestonePeriod": -1, "before": 0, "after": 1}),
    ("regulatory_milestone", [], {"milestonePeriod": {"low": 1, "high": 2, "value": 1}, "before": 0, "after": 1}),
])
def test_mechanism_template_contracts(case, kind, inputs, parameters):
    case["mechanisms"][1].update(kind=kind, inputNodeIds=inputs, parameters=parameters)
    with pytest.raises(CaseValidationError):
        validate_case(case)


def test_timestamp_precision_and_offsets(case):
    source = case["sources"][0]
    source.update(publishedAt="2026-10-27T23:00:00Z", retrievedAt="2026-10-27T00:00:00Z")
    with pytest.raises(CaseValidationError, match="instant"):
        validate_case(case)
    source.update(publishedAt="2026-10-27T08:00:00+08:00", retrievedAt="2026-10-27T00:00:00Z")
    assert validate_case(case)
    source["retrievedAt"] = "2026-10-27T23:00:00-02:00"
    with pytest.raises(CaseValidationError, match="asOf"):
        validate_case(case)


def test_unambiguous_graph_edge_ids(case):
    # Replace all exact identifiers, retaining labels and narrative untouched.
    def rename(value):
        if isinstance(value, dict):
            return {key: rename(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rename(item) for item in value]
        return "trend:base" if value == "trend" else value
    case = rename(case)
    case["mechanisms"][0]["mechanismId"] = "M"
    case["mechanisms"][1]["mechanismId"] = "M:trend"
    graph = graph_projection(case)
    assert len({row["uuid"] for row in graph["edges"]}) == len(graph["edges"])
    assert len({row["uuid"] for row in graph["nodes"]}) == len(graph["nodes"])


def test_size_boundary_roundtrip(case, tmp_path, monkeypatch):
    import deerflow_bridge.forecast_case as module
    encoded_size = len(module._canonical(case))
    monkeypatch.setattr(module, "_MAX_BYTES", encoded_size)
    path = tmp_path / "case.json"
    digest = write_case(path, case)
    assert read_case(path, digest) == case
    case["question"] += "x"
    with pytest.raises(CaseValidationError, match="byte budget"):
        write_case(path, case)
    assert read_case(path, digest)["question"] != case["question"]


def test_persisted_ledger_evidence_is_immutable(case, tmp_path):
    path = tmp_path / "case.json"
    write_case(path, case)
    case["revision"] += 1
    case["sources"][0]["title"] = "Replaced evidence origin"
    with pytest.raises(CaseValidationError, match="evidence is immutable"):
        write_case(path, case)


@pytest.mark.parametrize("timestamp", ["0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"])
def test_utc_timestamp_overflow_is_a_validation_error(case, timestamp):
    case["sources"][0]["publishedAt"] = timestamp
    with pytest.raises(CaseValidationError, match="ISO date"):
        validate_case(case)



def adapter_contract(kind="named_source_event"):
    """Fresh synthetic F6 contract examples without changing the shared fixture."""
    return {
        "named_source_event": {
            "kind": "named_source_event", "publisher": "Synthetic official statistics",
            "event": "Publication of the 2027 worldwide spending release",
            "deadline": "2028-03-30", "url": "https://example.test/spending",
        },
        "official_data": {
            "kind": "official_data", "series": "synthetic:SPENDING",
            "comparator": ">=", "threshold": 280.0, "period": "2027",
            "units": "USD billion", "transform": "level",
        },
        "polymarket": {"kind": "polymarket", "market_id": "synthetic-market-1", "equivalence": "exact"},
    }[kind]


@pytest.mark.parametrize("kind", ["named_source_event", "official_data", "polymarket"])
def test_f6_contract_shapes_preserved_and_probability_isolated(case, kind, tmp_path):
    before = simulation_projection(case)
    contract = adapter_contract(kind)
    case["nodes"][-1]["resolution_contract"] = copy.deepcopy(contract)
    case["binaries"][0]["resolution_contract"] = copy.deepcopy(contract)
    case["binaries"][0]["scenario_membership"] = {"derivable": True, "yes_scenarios": ["At least 280"]}
    validated = validate_case(case)
    assert validated == case
    report = report_projection(case)
    assert report["nodes"][-1]["resolution_contract"] == contract
    assert report["binaries"][0]["resolution_contract"] == contract
    assert report["binaries"][0]["scenario_membership"] == {"derivable": True, "yes_scenarios": ["At least 280"]}
    graph_nodes = {node["attributes"].get("nodeId"): node for node in graph_projection(case)["nodes"]}
    assert graph_nodes["spending"]["attributes"]["resolution_contract"] == contract
    assert simulation_projection(case) == before
    path = tmp_path / "case.json"
    digest = write_case(path, case)
    assert read_case(path, digest) == case
    report["binaries"][0]["resolution_contract"]["kind"] = "mutated-copy"
    assert case["binaries"][0]["resolution_contract"] == contract


@pytest.mark.parametrize("location", ["node", "binary"])
@pytest.mark.parametrize(("kind", "key", "value"), [
    ("named_source_event", "publisher", ""),
    ("named_source_event", "event", []),
    ("named_source_event", "deadline", "2028-02-30"),
    ("named_source_event", "url", "file:///etc/passwd"),
    ("named_source_event", "url", "https://user:secret@example.test/"),
    ("official_data", "series", ""),
    ("official_data", "comparator", "gte"),
    ("official_data", "threshold", True),
    ("official_data", "threshold", float("inf")),
    ("official_data", "period", 2027),
    ("official_data", "period", ""),
    ("official_data", "units", []),
    ("official_data", "transform", {}),
    ("polymarket", "market_id", 123),
    ("polymarket", "market_id", ""),
    ("polymarket", "equivalence", "near"),
    ("polymarket", "kind", "invented"),
])
def test_f6_malformed_resolution_contract(case, location, kind, key, value):
    row = case["nodes"][-1] if location == "node" else case["binaries"][0]
    contract = adapter_contract(kind)
    contract[key] = value
    row["resolution_contract"] = contract
    with pytest.raises(CaseValidationError):
        validate_case(case)


@pytest.mark.parametrize("contract", [None, [], "named_source_event", {},
    {"kind": "polymarket", "market_id": "m", "equivalence": "exact", "probability": 0.9},
    {"kind": "named_source_event", "publisher": "p", "event": "e"}])
def test_f6_contract_objects_are_explicit_and_exact(case, contract):
    case["binaries"][0]["resolution_contract"] = contract
    with pytest.raises(CaseValidationError):
        validate_case(case)


@pytest.mark.parametrize("membership", [
    None, [], {}, {"derivable": "false", "yes_scenarios": []},
    {"derivable": False, "yes_scenarios": ["At least 280"]},
    {"derivable": True, "yes_scenarios": []},
    {"derivable": True, "yes_scenarios": "At least 280"},
    {"derivable": True, "yes_scenarios": ["above"]},
    {"derivable": True, "yes_scenarios": ["At least 280", "At least 280"]},
    {"derivable": True, "yes_scenarios": ["absent"]},
    {"derivable": False, "yes_scenarios": [], "inferred": True},
])
def test_f6_scenario_membership_shape_and_references(case, membership):
    case["binaries"][0]["scenario_membership"] = membership
    with pytest.raises(CaseValidationError):
        validate_case(case)


def test_f6_driver_binary_never_inherits_target_or_node_contract(case):
    target_contract = adapter_contract()
    case["nodes"][-1]["resolution_contract"] = target_contract
    driver = {"binaryId": "B-driver", "question": "Will trend exceed 10 percent?",
              "predicate": {"nodeId": "trend", "operator": "gt", "value": 0.1},
              "probability": 0.3, "sourceIds": ["S1"],
              "scenario_membership": {"derivable": False, "yes_scenarios": []}}
    case["binaries"].append(driver)
    # Core never performs even a node-local fallback; the estimator must bind
    # and validate a contract explicitly when a driver really is resolvable.
    case["nodes"][1]["resolution_contract"] = adapter_contract("official_data")
    validated = validate_case(case)
    report = report_projection(case)
    assert "resolution_contract" not in validated["binaries"][-1]
    assert "resolution_contract" not in report["binaries"][-1]
    assert "resolution_contract" not in report["binaries"][0]
    assert report["binaries"][-1]["probability"] == 0.3
    assert report["nodes"][-1]["resolution_contract"] == target_contract


def test_f6_duplicate_partition_names_fail_when_membership_declared(case):
    case["scenarios"][0]["label"] = "At least 280"
    case["binaries"][0]["scenario_membership"] = {"derivable": True, "yes_scenarios": ["At least 280"]}
    with pytest.raises(CaseValidationError, match="unique"):
        validate_case(case)


def test_f6_snake_case_alias_exception_is_narrow(case):
    case["binaries"][0]["resolutionContract"] = adapter_contract()
    with pytest.raises(CaseValidationError, match="unknown fields"):
        validate_case(case)
    del case["binaries"][0]["resolutionContract"]
    case["nodes"][-1]["scenario_membership"] = {"derivable": False, "yes_scenarios": []}
    with pytest.raises(CaseValidationError, match="unknown fields"):
        validate_case(case)


def test_f6_private_node_resolution_contract_stays_private(case):
    case["nodes"][4]["resolution_contract"] = adapter_contract()
    assert "resolution_contract" not in json.dumps(graph_projection(case))
    assert "resolution_contract" not in json.dumps(simulation_projection(case))
