"""Deterministic target-first reports and outcome-blind comparison registration.

No clients, storage, or application startup at import. Research assessments are
numeric authority; structural paths are a separate, zero-weight estimator.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

BRIDGE_START = "<!-- sim-bridge:start -->"
BRIDGE_END = "<!-- sim-bridge:end -->"
POLICY_VERSION = "target-combination/zero-v1"


def _case_api():
    from .official_data import bridge_module
    return bridge_module("forecast_case")


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def combination_policy():
    """No environment setting or runtime argument can promote this policy."""
    return {"version": POLICY_VERSION, "researchWeight": 1.0,
            "simulationWeight": 0.0, "promotionAllowed": False,
            "status": "prospective_evaluation_required"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value):
    # Source strings cannot inject headings, citations, links, or audit fences.
    value = html.escape(str(value), quote=False)
    return " ".join(value.split()).replace("|", "&#124;").replace("[", "［").replace("]", "］")


def _probability(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def _predicate(predicate, nodes):
    node = nodes[predicate["nodeId"]]
    label = _text(node["label"])
    unit = _text(node["units"])
    if predicate["operator"] == "between":
        return f"{predicate['low']} ≤ {label} ≤ {predicate['high']} {unit}"
    operator = {"lt": "<", "lte": "≤", "gt": ">", "gte": "≥"}[predicate["operator"]]
    return f"{label} {operator} {predicate['value']} {unit}"


def _simulation(case, simulation):
    if simulation is None:
        return None
    result = json.loads(canonical_json(simulation))
    _require(isinstance(result, dict), "simulation must be an object")
    allowed_keys = {"schemaVersion", "caseId", "caseHash", "seed", "paths", "scenarioShares",
                    "targetSummary", "sensitivity", "signposts", "simulationWeight", "baseline",
                    "baselinePaths", "baselineSummary", "baselineScenarioShares", "parameterBases", "replay",
                    "modelValidation", "interventionTables", "conditionalTables", "hindcastValidation", "decisionBudget"}
    _require(set(result) <= allowed_keys, "unknown simulation fields")
    _require(result.get("schemaVersion") == "target-simulation/v1", "invalid simulation schema")
    _require(result.get("caseId") == case["caseId"] and
             result.get("caseHash") == _case_api().case_hash(case), "simulation case identity mismatch")
    _require(type(result.get("simulationWeight")) in (int, float) and
             result["simulationWeight"] == 0, "simulation weight must remain zero")
    if "decisionBudget" in result:
        budget = result["decisionBudget"]
        _require(isinstance(budget, dict) and set(budget) == {"maximumRequests", "requests", "cacheHits", "exhausted"},
                 "invalid decision budget fields")
        _require(all(type(budget[key]) is int and budget[key] >= 0 for key in ("maximumRequests", "requests", "cacheHits"))
                 and budget["requests"] <= budget["maximumRequests"]
                 and type(budget["exhausted"]) is bool, "invalid decision budget counters")
    shares = result.get("scenarioShares")
    _require(isinstance(shares, dict) and bool(shares), "simulation shares missing")
    allowed = {s["scenarioId"] for s in case["scenarios"]} | {"other"}
    _require(set(shares) <= allowed and all(_probability(v) for v in shares.values()),
             "invalid simulation scenario shares")
    _require(math.isclose(sum(shares.values()), 1.0, abs_tol=1e-9),
             "simulation shares must include unmatched mass")
    _require(isinstance(result.get("paths"), list) and bool(result["paths"]), "simulation paths missing")
    _validate_paths(case, result["paths"], shares)
    if "baselinePaths" in result:
        _validate_paths(case, result["baselinePaths"], result.get("baselineScenarioShares"))
    return result


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _validate_paths(case, paths, shares):
    """Validate scoring inputs and verify frequencies against terminal predicates."""
    from .target_simulation import _shares
    from .target_mechanisms import compile_model
    from random import Random
    _require(isinstance(paths, list) and bool(paths), "simulation paths missing")
    required = {"pathId", "parameters", "trajectory", "decisions", "targetValue"}
    allowed = required | {"initialValues", "plans", "pendingEffects", "signals", "credibility",
                          "remainingCapacity", "seed"}
    node_ids = {row["nodeId"] for row in case["nodes"]}
    # The compiler expands e.g. linear coefficients into coefficient:<nodeId>.
    # Read its public draw schema rather than guessing keys from source JSON.
    parameter_schema = compile_model(case).draw_parameters(Random(0))
    path_ids = set()
    for path in paths:
        _require(isinstance(path, dict) and required <= set(path) <= allowed, "invalid simulation path fields")
        pid = path["pathId"]
        _require(isinstance(pid, str) and bool(pid) and pid not in path_ids, "invalid or duplicate path identity")
        path_ids.add(pid)
        _require(isinstance(path["parameters"], dict) and set(path["parameters"]) <= set(parameter_schema), "invalid path parameter identity")
        for mid, parameters in path["parameters"].items():
            _require(isinstance(parameters, dict) and set(parameters) == set(parameter_schema[mid])
                     and all(_finite(value) for value in parameters.values()),
                     "invalid path parameter fields")
        _require(isinstance(path["trajectory"], list) and bool(path["trajectory"]), "missing path trajectory")
        previous = -1
        for step in path["trajectory"]:
            _require(isinstance(step, dict) and set(step) == {"period", "values"}, "invalid trajectory fields")
            _require(type(step["period"]) is int and step["period"] > previous, "trajectory periods must increase")
            previous = step["period"]
            values = step["values"]
            _require(isinstance(values, dict) and set(values) <= node_ids and all(_finite(v) for v in values.values()),
                     "invalid trajectory values")
        terminal = path["trajectory"][-1]["values"]
        target = case["resolution"]["targetNodeId"]
        needed = {s["predicate"]["nodeId"] for s in case["scenarios"]} | {target}
        _require(needed <= set(terminal) and _finite(path["targetValue"]) and path["targetValue"] == terminal[target],
                 "terminal target differs from trajectory")
        _require(isinstance(path["decisions"], list), "invalid path decisions")
        for decision in path["decisions"]:
            _require(isinstance(decision, dict) and set(decision) <= {
                "period", "actorId", "status", "reason", "kind", "leverId", "value", "nodeId", "duePeriod", "planId",
                "effectivePeriod", "cost", "remainingCapacity"},
                "invalid simulation decision fields")
        for signal in path.get("signals", []):
            _require(isinstance(signal, dict) and set(signal) <= {
                "actorId", "nodeId", "value", "recipients", "period", "duePeriod", "resolved", "score", "resolvedPeriod"},
                "invalid simulated signal fields")
        for pending in path.get("pendingEffects", []):
            _require(isinstance(pending, dict) and set(pending) <= {
                "actorId", "kind", "leverId", "value", "consents", "planId", "effectivePeriod", "reservedCost", "previousDirection"},
                "invalid pending effect fields")
        plans = path.get("plans", {})
        _require(isinstance(plans, dict), "invalid path plans")
        for actor_plans in plans.values():
            _require(isinstance(actor_plans, list), "invalid actor plans")
            for plan in actor_plans:
                _require(isinstance(plan, dict) and set(plan) <= {
                    "planId", "leverId", "value", "duePeriod", "condition", "status"}, "invalid plan fields")
    expected = _shares(case, paths)
    _require(isinstance(shares, dict) and set(shares) <= set(expected) and
             all(_probability(shares.get(key, 0)) and math.isclose(shares.get(key, 0), value, abs_tol=1e-12)
                 for key, value in expected.items()), "simulation shares differ from terminal paths")


def _assessment(case):
    rows = case["assessments"]
    _require(bool(rows), "typed report requires an assessment")
    latest = max(rows, key=lambda a: a["version"])
    _require(bool(latest["scenarioWeights"]), "typed report requires scenario weights")
    return latest


def build_target_report(case, simulation=None, *, official_data=None, markets=None,
                        scenario_label=None, base_simulation_id=None):
    """Project frozen typed inputs to the public forecast.json and Markdown shape."""
    case = _case_api().validate_case(case)
    from .target_mechanisms import admit_model
    model_admission = admit_model(case)
    simulation = _simulation(case, simulation)
    has_model_receipt = simulation is not None and "modelValidation" in simulation
    if has_model_receipt:
        receipt = simulation["modelValidation"]
        _require(isinstance(receipt, dict), "invalid model admission receipt")
        if "policy" in receipt:
            expected_receipt = model_admission
        else:
            # Historical diagnostic mode had no policy field. Verify its exact
            # shape/values too; an unknown policy cannot select that legacy path.
            from .target_mechanisms import validate_model
            expected_receipt = validate_model(case)
        _require(receipt == expected_receipt, "model admission receipt differs from frozen case")
    assessment = _assessment(case)
    nodes = {n["nodeId"]: n for n in case["nodes"]}
    weights = assessment["scenarioWeights"]
    scenarios = []
    for row in case["scenarios"]:
        sid = row["scenarioId"]
        _require(sid in weights, "assessment missing scenario weight: " + sid)
        scenarios.append({"id": sid, "name": row["label"], "probability": weights[sid],
                          "resolution_criteria": _predicate(row["predicate"], nodes),
                          "predicate": row["predicate"], "summary": "Frozen research assessment."})
    _require(math.isclose(sum(s["probability"] for s in scenarios), 1.0, abs_tol=1e-9),
             "report probabilities require approved typed scenarios for all assessment mass")
    resolution = case["resolution"]
    from .forecast_extractor import derive_binaries_from_tree
    # The native collector stores health/cache metadata alongside market rows.
    # Only the binary-anchor consumer needs rows; callers retain and seal the
    # original envelope for input health and estimator admission.
    market_rows = markets
    if isinstance(markets, dict):
        _require("markets" in markets, "stored market envelope requires markets")
        market_rows = markets["markets"]
        _require(isinstance(market_rows, list), "stored market envelope requires market rows")
    _require(market_rows is None or isinstance(market_rows, list) and
             all(isinstance(row, dict) for row in market_rows), "stored markets must be market rows")
    binary_projection = derive_binaries_from_tree(case, scenarios=scenarios,
                                                   official_data=official_data, markets=market_rows)
    binaries = binary_projection["binary_forecasts"]
    _require(bool(binaries), "typed report requires explicit binary forecasts")
    unknown = [{"nodeId": n["nodeId"], "status": n["status"], "range": n.get("range"),
                "vintage": n.get("vintage"), "sourceIds": n["sourceIds"],
                "basis": n.get("basis", "derived"), "gap": n.get("gap")}
               for n in case["nodes"] if n["status"] != "settled"]
    bases = [{k: m.get(k) for k in ("mechanismId", "kind", "basis", "parameters", "gap", "sourceIds")}
             for m in case["mechanisms"]]
    divergence = [{"scenarioId": s["id"], "researchProbability": s["probability"],
                   "simulatedShare": simulation["scenarioShares"].get(s["id"], 0.0),
                   "difference": simulation["scenarioShares"].get(s["id"], 0.0) - s["probability"]}
                  for s in scenarios] if simulation else []
    record = {"schemaVersion": "target-report/v1", "caseId": case["caseId"],
              "caseHash": _case_api().case_hash(case), "assessment": assessment,
              "assessmentLedger": case["assessments"], "policy": combination_policy(),
              "simulationHash": _hash(simulation) if simulation else None,
              "simulationWeight": 0.0, "probabilityEvidence": False,
              "divergence": divergence, "unknownParameters": unknown, "parameterBases": bases,
              "simulationParameterBases": simulation.get("parameterBases", []) if simulation else [],
              "decisionBudget": simulation.get("decisionBudget") if simulation else None,
              "sensitivity": simulation.get("sensitivity", []) if simulation else [],
              "signposts": simulation.get("signposts", []) if simulation else [],
              "targetSummary": simulation.get("targetSummary") if simulation else None}
    if has_model_receipt:
        record["modelValidation"] = model_admission
    forecast = {"schema_version": 1, "headline": case["question"], "horizon": resolution["horizon"],
                "scenarios": scenarios, "binary_forecasts": binaries,
                "binary_quality": binary_projection["binary_quality"],
                "confidence": "low", "confidence_rationale": "Frozen research assessment; prospective calibration unavailable.",
                "key_uncertainties": [n["nodeId"] + ": " + n["status"] for n in unknown],
                "authority": "target-first-v1", "case_id": case["caseId"], "case_hash": record["caseHash"],
                "assessment_id": assessment["assessmentId"], "assessment_version": assessment["version"],
                "target_distribution": assessment.get("targetDistribution"), "resolution": resolution,
                "combination_policy": combination_policy(), "quality": {}}
    if record["decisionBudget"] is not None:
        forecast["target_diagnostics"] = {"decisionBudget": record["decisionBudget"], "simulationWeight": 0.0}
    lines = ["# Target forecast", "", "<!-- binary-forecast-block:start -->",
             _text(case["question"]), "", "## Resolution contract", "",
             f"Target: {_text(nodes[resolution['targetNodeId']]['label'])}; units: {_text(resolution['units'])}.",
             f"Evidence cutoff: {case['asOf']}. Horizon: {resolution['horizon']}.",
             f"Settlement: {_text(resolution['settlementSource']['name'])}; publication lag: {resolution['settlementSource']['releaseLagDays']} days.",
             f"Settlement URL: {_text(resolution['settlementSource']['url'])}",
             f"Comparator policy: {_text(resolution['comparatorPolicy'])}",
             "<!-- binary-forecast-block:end -->", "", "## Research evidence", ""]
    for claim in case["claims"]:
        citations = " ".join(f"[{sid}]" for sid in claim["sourceIds"])
        lines.append(f"{_text(claim['passage'])} {citations}".rstrip())
        lines.append("")
    if not case["claims"]:
        lines += ["No source-backed claims supplied; parameter uncertainty remains explicit.", ""]
    lines += ["## Evidence provenance", "", "<!-- binary-forecast-block:start -->"]
    for source in case["sources"]:
        lines.append(f"- {_text(source['sourceId'])}: publication {_text(source['publishedAt'] or 'unknown')}; "
                     f"retrieved {_text(source['retrievedAt'])}; tier {_text(source['tier'])}; "
                     f"origin {_text(source['originCluster'])}; fetched {source['fetched']}.")
    lines += ["<!-- binary-forecast-block:end -->", ""]
    lines += ["## Research forecasts", "", "<!-- binary-forecast-block:start -->",
              "Probabilities below are the frozen research assessment. They are forecasts, not observed frequencies.", "",
              "| Scenario | Probability | Settlement predicate |", "|---|---:|---|"]
    for row in scenarios:
        lines.append(f"| {_text(row['name'])} | {row['probability'] * 100:.10g}% | {_text(row['resolution_criteria'])} |")
    lines += ["", "| Binary forecast | Probability | Settlement predicate |", "|---|---:|---|"]
    for row in binaries:
        lines.append(f"| {_text(row['statement'])} | {row['probability'] * 100:.10g}% | {_text(row['resolution_criteria'])} |")
    lines += ["", "## Assessment update ledger", ""]
    for row in case["assessments"]:
        lines.append(f"Assessment {_text(row['assessmentId'])}, version {row['version']}, {_text(row['kind'])}.")
        for update in row["updates"]:
            lines.append("- " + _text(canonical_json(update)))
        if not row["updates"]:
            lines.append("No updates recorded for this assessment.")
        lines.append("")
    lines += ["## Parameter bases and remaining uncertainty", ""]
    for n in unknown:
        lines.append("- " + _text(canonical_json(n)))
    for basis in bases:
        lines.append("- " + _text(canonical_json(basis)))
    if not unknown and not bases:
        lines.append("No unknown parameters declared.")
    lines += ["<!-- binary-forecast-block:end -->", "", diagnostic_markdown(record), ""]
    if scenario_label or base_simulation_id:
        provenance = {"scenarioLabel": scenario_label or "", "baseSimulationId": base_simulation_id,
                      "recordClass": "evaluation", "characterizationOnly": True}
        record["provenance"] = provenance
        forecast.update(characterization_only=True, record_class="evaluation", target_provenance=provenance)
        # Re-render the diagnostic record hash after adding owner-authorized provenance.
        lines = lines[:-3] + ["", diagnostic_markdown(record), "",
                 "## Comparison provenance", "", "<!-- binary-forecast-block:start -->",
                 "Diagnostic fork; excluded from the production forecast cohort.",
                 _text(canonical_json(provenance)), "<!-- binary-forecast-block:end -->", ""]
    return {"forecast": forecast, "markdown": "\n".join(lines), "record": record}


def diagnostic_markdown(record, *, forecast=None):
    """Exact ADR 0003 fence; no source markers or private path contents."""
    lines = [BRIDGE_START, "## Structural simulation diagnostics", "",
             "SIMULATED — structural sensitivity exercise. ZERO forecast weight. Not observed evidence.",
             "The research probabilities were not changed by this exercise.", "",
             "| Scenario | Research probability | Simulated share | Difference |", "|---|---:|---:|---:|"]
    for row in record["divergence"]:
        lines.append(f"| {_text(row['scenarioId'])} | {row['researchProbability']:.10g} | {row['simulatedShare']:.10g} | {row['difference']:+.10g} |")
    if not record["divergence"]:
        lines += ["", "No structural paths supplied."]
    from .forecast_estimator_table import render_estimator_table
    estimator_table = render_estimator_table(forecast)
    if estimator_table:
        lines += ["", estimator_table]
    for label, key in (("Target summary", "targetSummary"), ("Sensitivity", "sensitivity"),
                       ("Signposts", "signposts"), ("Structural parameter bases", "simulationParameterBases")):
        lines += ["", f"### {label}", "", _text(canonical_json(record[key]))]
    if record.get("decisionBudget") is not None:
        lines += ["", "### Decision request budget", "", _text(canonical_json(record["decisionBudget"])),
                  "These counts measure distinct decision requests; internal provider retries are recorded separately."]
        if record["decisionBudget"]["exhausted"]:
            lines += ["The decision request budget was exhausted. Subsequent uncached choices held their prior settings."]
    if "modelValidation" in record:
        lines += ["", "### Model validation", "", _text(canonical_json(record["modelValidation"])),
                  "Unsupported units and unmeasured seed identities remain evidence gaps; they are not successful validation checks."]
    lines += ["", "Prospective paired evaluation is required. No measured lift or promotion is claimed.",
              f"Policy: {POLICY_VERSION}. Record SHA-256: {_hash(record)}.", BRIDGE_END]
    return "\n".join(lines)


def audit_target_report(case, simulation, forecast, record, *, official_data=None, markets=None,
                        scenario_label=None, base_simulation_id=None):
    expected = build_target_report(case, simulation, official_data=official_data, markets=markets,
                                    scenario_label=scenario_label, base_simulation_id=base_simulation_id)
    issues = []
    if expected["record"] != record:
        issues.append("typed report record differs from frozen inputs")
    # Quality/audit metadata can change; numeric and settlement authority cannot.
    for key, value in expected["forecast"].items():
        if key not in {"quality", "confidence", "confidence_rationale", "key_uncertainties"} and forecast.get(key) != value:
            issues.append("typed forecast authority mismatch: " + key)
    return {"valid": not issues, "issues": issues, "case_hash": expected["record"]["caseHash"],
            "record_sha256": _hash(record), "simulation_weight": 0.0}


def _utcnow():
    return datetime.now(timezone.utc)


def _reject_outcomes(value):
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z]", "", key.lower())
            _require(not any(part in normalized for part in
                             ("outcome", "resolvedat", "resolutionresult", "realized", "realised", "actualvalue",
                              "observedtarget", "brierscore", "logscore", "winner", "promotion")),
                     "outcome-bearing enrollment field: " + key)
            _reject_outcomes(item)
    elif isinstance(value, list):
        for item in value:
            _reject_outcomes(item)


def _create_immutable(path, serialized):
    """Publish complete bytes with create-only hard-link semantics, never replace."""
    if path.is_symlink():
        raise ValueError("comparison destination cannot be a symlink")
    if path.exists():
        _require(path.read_text(encoding="utf-8") == serialized, "immutable comparison already differs")
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".comparison-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            _require(not path.is_symlink() and path.read_text(encoding="utf-8") == serialized,
                     "immutable comparison already differs")
    finally:
        os.unlink(temporary)


def register_comparison(path, case, simulation, *, enrolled_at, registry_dir=None):
    """Enroll one immutable pair per case in the destination registry directory.

    Callers must use one durable registry directory. Changing filenames within it
    cannot re-enroll a revised case, seed, timestamp, or scoring policy. This is
    preregistration, not a scorer or a runtime promotion mechanism.
    """
    _reject_outcomes(case)
    _reject_outcomes(simulation)
    case = _case_api().validate_case(case)
    simulation = _simulation(case, simulation)
    _require(simulation is not None, "paired comparison requires structural paths")
    _require(isinstance(enrolled_at, str), "enrollment requires a timezone-aware timestamp")
    try:
        enrolled = datetime.fromisoformat(enrolled_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid enrollment timestamp") from exc
    _require(enrolled.tzinfo is not None, "enrollment timestamp must include timezone")
    enrolled = enrolled.astimezone(timezone.utc)
    now = _utcnow()
    bundle = build_target_report(case, simulation)
    record = {"schemaVersion": "target-comparison/v1", "caseId": case["caseId"],
              "caseHash": bundle["record"]["caseHash"], "simulationHash": _hash(simulation),
              "enrolledAt": enrolled.isoformat(), "resolution": case["resolution"],
              "policy": combination_policy(), "outcomesIncluded": False,
              "scoringProtocol": {"version": "paired-terminal-regions/v1", "metrics": ["brier", "log"],
                                  "logEpsilon": 1e-12, "paired": True,
                                  "unit": "one terminal scenario per case", "promotionAllowed": False},
              "researchArm": {s["id"]: s["probability"] for s in bundle["forecast"]["scenarios"]},
              "structuralArm": simulation["scenarioShares"]}
    path = Path(path)
    # Guard a case identity independently of the user-selected output filename.
    registry = Path(registry_dir) if registry_dir is not None else path.parent
    identity_path = registry / (".target-comparison-" + _hash(case["caseId"]) + ".json")
    # A failed report may retry with a new clock reading. The enrolled instant
    # belongs to the immutable receipt, not to the latest attempt.
    recovered = False
    for existing in (identity_path, path):
        if existing.exists() or existing.is_symlink():
            _require(not existing.is_symlink(), "comparison destination cannot be a symlink")
            original = json.loads(existing.read_text(encoding="utf-8"))
            frozen = dict(original)
            original_time = frozen.pop("enrolledAt", None)
            comparison = dict(record)
            comparison.pop("enrolledAt")
            _require(frozen == comparison, "immutable comparison already differs")
            instant = datetime.fromisoformat(str(original_time).replace("Z", "+00:00"))
            _require(instant.tzinfo is not None and instant <= now and
                     date.fromisoformat(case["asOf"]) <= instant.date() <
                     date.fromisoformat(case["resolution"]["horizon"]),
                     "invalid original prospective enrollment")
            record["enrolledAt"] = original_time
            recovered = True
    if not recovered:
        _require(enrolled <= now and enrolled.date() == now.date(), "enrollment must occur today, not be backdated or future-dated")
        _require(date.fromisoformat(case["asOf"]) <= enrolled.date(), "case cutoff postdates enrollment")
        _require(date.fromisoformat(case["resolution"]["horizon"]) > now.date(), "comparison requires a future resolution horizon")
    path.parent.mkdir(parents=True, exist_ok=True)
    registry.mkdir(parents=True, exist_ok=True)
    serialized = canonical_json(record) + "\n"
    if path.exists() or path.is_symlink():
        _require(not path.is_symlink() and path.read_text(encoding="utf-8") == serialized,
                 "immutable comparison already differs")
    _create_immutable(identity_path, serialized)
    _create_immutable(path, serialized)
    return record
