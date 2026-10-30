"""Versioned estimator contracts and explicit, immutable aggregation policies.

Shadow diagnostics never pass through numeric normalization. No IO or clients.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math

ESTIMATOR_VERSION = "estimator/v1"
POLICY_VERSION = "aggregation_policy_v1"
LANES = ("spine", "research", "reference_class", "trend", "adversarial",
         "market_implied", "structural", "simulation")


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _number(value, label, *, low=0, high=None):
    if type(value) not in (int, float) or not math.isfinite(value) or value < low or (
            high is not None and value > high):
        raise ValueError("invalid " + label)
    return value


def default_aggregation_policy(authority="spine"):
    if authority not in ("spine", "research"):
        raise ValueError("authority must be spine or research")
    return {"schema_version": POLICY_VERSION, "authority": authority, "method": "identity",
            "weights": {lane: 1.0 if lane == authority else 0.0 for lane in LANES},
            "extremize_a": 1.0, "floor": 0.03}


def pin_aggregation_policy(policy=None, *, authority="spine"):
    """Return a detached validated policy. Persist this result once at admission.

    Explicit weighted_log_odds policies support non-simulation evidence lanes.
    Structural runs and simulations remain diagnostics under every policy.
    """
    result = deepcopy(default_aggregation_policy(authority) if policy is None else policy)
    if not isinstance(result, dict) or set(result) != {
            "schema_version", "authority", "method", "weights", "extremize_a", "floor"}:
        raise ValueError("invalid aggregation policy fields")
    if result["schema_version"] != POLICY_VERSION or result["authority"] not in ("spine", "research"):
        raise ValueError("unsupported aggregation policy")
    weights = result["weights"]
    if not isinstance(weights, dict) or set(weights) != set(LANES):
        raise ValueError("policy weights must explicitly declare every lane")
    for lane, weight in weights.items():
        _number(weight, lane + " weight")
    if weights["simulation"] or weights["structural"]:
        raise ValueError("simulation and structural estimators cannot be promoted")
    if weights[result["authority"]] <= 0 or weights["research" if result["authority"] == "spine" else "spine"]:
        raise ValueError("policy requires exactly one positive authority lane")
    _number(result["extremize_a"], "extremize_a", low=0.01, high=10)
    _number(result["floor"], "floor", low=0, high=0.49)
    if result["method"] == "identity":
        if weights[result["authority"]] != 1 or any(w != 0 for lane, w in weights.items() if lane != result["authority"]) or result["extremize_a"] != 1:
            raise ValueError("identity policy requires authority=1 and shadow weights=0")
    elif result["method"] != "weighted_log_odds":
        raise ValueError("unsupported aggregation method")
    return result


def validate_estimator(value):
    """Validate estimator/v1 without rounding, filling gaps or rescaling numbers."""
    row = deepcopy(value)
    required = {"schema_version", "source", "kind", "scenario_distribution", "binaries",
                "rationale", "cruxes", "inputs_hash", "status"}
    if not isinstance(row, dict) or set(row) != required or row["schema_version"] != ESTIMATOR_VERSION:
        raise ValueError("invalid estimator/v1 fields")
    if row["source"] not in LANES or not isinstance(row["kind"], str) or not row["kind"]:
        raise ValueError("invalid estimator source/kind")
    if row["status"] not in ("ok", "unavailable", "error"):
        raise ValueError("invalid estimator status")
    if not isinstance(row["rationale"], str) or not isinstance(row["cruxes"], list) or any(
            not isinstance(c, str) or not c.strip() for c in row["cruxes"]):
        raise ValueError("invalid estimator rationale/cruxes")
    if not isinstance(row["inputs_hash"], str) or len(row["inputs_hash"]) != 64 or any(
            c not in "0123456789abcdef" for c in row["inputs_hash"]):
        raise ValueError("invalid estimator inputs_hash")
    distribution = row["scenario_distribution"]
    if not isinstance(distribution, dict) or any(not isinstance(k, str) or not k for k in distribution):
        raise ValueError("invalid scenario distribution")
    for p in distribution.values():
        _number(p, "scenario probability", high=1)
    if distribution and not math.isclose(sum(distribution.values()), 1, abs_tol=1e-8):
        raise ValueError("estimator distribution must sum to one")
    if not isinstance(row["binaries"], list):
        raise ValueError("invalid estimator binaries")
    ids = set()
    for binary in row["binaries"]:
        if not isinstance(binary, dict) or set(binary) != {"id", "p"} or not isinstance(binary["id"], str) or not binary["id"] or binary["id"] in ids:
            raise ValueError("invalid or duplicate estimator binary")
        ids.add(binary["id"])
        _number(binary["p"], "binary probability", high=1)
    if row["status"] != "ok" and (distribution or row["binaries"]):
        raise ValueError("unavailable estimators cannot carry probabilities")
    if row["status"] == "ok" and not (distribution or row["binaries"]):
        raise ValueError("available estimator has no estimates")
    return row


def estimator_from_forecast(forecast, *, source="spine"):
    scenarios = forecast.get("scenarios") or []
    distribution = {str(s.get("id") or s["name"]): s["probability"] for s in scenarios}
    if len(distribution) != len(scenarios):
        raise ValueError("duplicate authority scenarios")
    binaries = [{"id": str(b["id"]), "p": b["probability"]} for b in forecast.get("binary_forecasts", [])]
    return validate_estimator({"schema_version": ESTIMATOR_VERSION, "source": source,
        "kind": "authoritative", "scenario_distribution": distribution, "binaries": binaries,
        "rationale": "Frozen authoritative forecast.", "cruxes": [],
        "inputs_hash": canonical_hash({"authority": forecast.get("authority"), "case_id": forecast.get("case_id"),
                                       "case_hash": forecast.get("case_hash"), "scenarios": scenarios,
                                       "binaries": forecast.get("binary_forecasts", [])}), "status": "ok"})


def _pool(pairs, policy):
    floor = max(policy["floor"], 1e-12)
    logit = sum(w * math.log(max(floor, min(1-floor, p)) / (1-max(floor, min(1-floor, p))))
                for p, w in pairs) / sum(w for _, w in pairs)
    z = policy["extremize_a"] * logit
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def aggregate_forecast(forecast, estimators, policy=None):
    """Attach diagnostics; change numbers only under explicit supported policy math."""
    authority = "research" if forecast.get("authority") == "target-first-v1" else "spine"
    pinned = pin_aggregation_policy(policy, authority=authority)
    if pinned["authority"] != authority:
        raise ValueError("aggregation authority does not match forecast")
    rows = [validate_estimator(r) for r in estimators]
    by_source = {r["source"]: r for r in rows}
    if len(by_source) != len(rows):
        raise ValueError("duplicate estimator sources")
    original = estimator_from_forecast(forecast, source=authority)
    if by_source.get(authority) != original:
        raise ValueError("authority estimator must match the published forecast exactly")
    out = deepcopy(forecast)
    out["estimators"] = rows
    out["aggregation"] = {"policy": pinned, "policy_hash": canonical_hash(pinned),
                          "method": pinned["method"], "simulation_weight": 0.0}
    # Do not touch any forecast row on this path, including floor/extremization.
    if pinned["method"] == "identity":
        return out
    active = [r for r in rows if r["status"] == "ok" and pinned["weights"][r["source"]] > 0]
    scenario_lanes = [r for r in active if set(r["scenario_distribution"]) == set(original["scenario_distribution"])]
    if scenario_lanes:
        pooled = {key: _pool([(r["scenario_distribution"][key], pinned["weights"][r["source"]])
                              for r in scenario_lanes], pinned) for key in original["scenario_distribution"]}
        total = sum(pooled.values())
        for row in out.get("scenarios", []):
            row["probability"] = pooled[str(row.get("id") or row["name"])] / total
    for row in out.get("binary_forecasts", []):
        pairs = [(b["p"], pinned["weights"][r["source"]]) for r in active for b in r["binaries"] if b["id"] == str(row["id"])]
        if pairs:
            row["probability"] = _pool(pairs, pinned)
    out["aggregation"]["active_sources"] = [r["source"] for r in active]
    return out
