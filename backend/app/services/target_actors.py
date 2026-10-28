"""Typed actor information boundaries for the target-first structural runtime.

Only identifiers and finite numeric/control fields cross the decision boundary.
The original case and free-form research/persona prose never cross it.
"""
from __future__ import annotations

from copy import deepcopy
import math


def finite(value, name="value"):
    try:
        valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{name} must be finite numeric data")
    return float(value)


def integer(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def predicate_matches(predicate, values):
    node_id = predicate["nodeId"]
    if node_id not in values:
        return False
    value = finite(values[node_id])
    operator = predicate["operator"]
    if operator == "between":
        return predicate["low"] <= value <= predicate["high"]
    threshold = predicate["value"]
    return {"lt": value < threshold, "lte": value <= threshold,
            "gt": value > threshold, "gte": value >= threshold}[operator]


def validate_predicate(predicate, node_ids):
    if not isinstance(predicate, dict) or predicate.get("nodeId") not in node_ids:
        raise ValueError("predicate references an invalid node")
    operator = predicate.get("operator")
    if operator not in {"lt", "lte", "gt", "gte", "between"}:
        raise ValueError("unsupported predicate operator")
    keys = {"nodeId", "operator", "low", "high"} if operator == "between" else {"nodeId", "operator", "value"}
    if set(predicate) != keys:
        raise ValueError("predicate keys do not match operator")
    if operator == "between":
        if finite(predicate["low"]) > finite(predicate["high"]):
            raise ValueError("predicate bounds are reversed")
    else:
        finite(predicate["value"])


def validate_scenarios(case):
    """Bind settlement classifiers; legacy reducers prebind their own target."""
    nodes = {node["nodeId"] for node in case["nodes"]}
    target = case.get("resolution", {}).get("targetNodeId")
    intervals = []
    for scenario in case.get("scenarios", []):
        if scenario["scenarioId"] == "other":
            raise ValueError("scenarioId 'other' is reserved for unmatched outcomes")
        pred = scenario["predicate"]
        validate_predicate(pred, nodes)
        if target is not None and pred["nodeId"] != target:
            raise ValueError("settlement scenario predicate must reference the resolution target")
        op = pred["operator"]
        if op == "between":
            interval = (pred["low"], True, pred["high"], True)
        elif op in {"lt", "lte"}:
            interval = (-math.inf, False, pred["value"], op == "lte")
        else:
            interval = (pred["value"], op == "gte", math.inf, False)
        for previous_node, previous in intervals:
            if previous_node != pred["nodeId"]:
                raise ValueError("scenario predicates on different nodes may overlap")
            low = max(interval[0], previous[0])
            high = min(interval[2], previous[2])
            if low < high or (low == high and
                    (low != interval[0] or interval[1]) and
                    (low != previous[0] or previous[1]) and
                    (high != interval[2] or interval[3]) and
                    (high != previous[2] or previous[3])):
                raise ValueError("overlapping scenario predicates")
        intervals.append((pred["nodeId"], interval))


def visible_nodes(case, actor):
    requested = set(actor.get("information", {}).get("nodeIds", []))
    return {node["nodeId"] for node in case["nodes"]
            if node["nodeId"] in requested and
            (node.get("visibility", "public") == "public"
             or node.get("ownerActorId") == actor["actorId"])}


def safe_observation(case, state, actor_id, *, period=0):
    """Construct an allowlist from current values plus dated observation history.

    With a flat value mapping, only period-zero, zero-lag values are admissible.
    A later snapshot needs history to establish release eligibility; the latest
    truth must never be substituted for a missing historical release.
    """
    integer(period, "period")
    actor = next((row for row in case["actors"] if row["actorId"] == actor_id), None)
    if actor is None:
        raise ValueError("unknown actorId")
    permitted = visible_nodes(case, actor)
    nodes = {node["nodeId"]: node for node in case["nodes"]}
    lag = integer(actor.get("information", {}).get("releaseLagPeriods", 0), "releaseLagPeriods")
    structured = "values" in state and isinstance(state["values"], dict)
    history = state.get("history", []) if structured else ([{"period": 0, "values": state}] if period == 0 else [])
    observations, observed_periods = {}, {}
    for node_id in sorted(permitted):
        private = nodes[node_id].get("visibility") == "private"
        cutoff = period if private else period - lag
        eligible = [row for row in history if row["period"] <= cutoff and node_id in row["values"]]
        if eligible:
            row = max(eligible, key=lambda item: item["period"])
            observations[node_id] = finite(row["values"][node_id])
            observed_periods[node_id] = row["period"]
    beliefs = dict(observations)
    signals = []
    if structured:
        for signal in state.get("signals", []):
            node_id = signal.get("nodeId")
            if (node_id not in observations or actor_id not in signal.get("recipients", [])
                    or signal.get("period", period) >= period or signal.get("resolved", False)):
                continue
            credibility = finite(state.get("credibility", {}).get(signal["actorId"], 0.5))
            claim = finite(signal["value"])
            beliefs[node_id] = finite((1 - credibility) * beliefs[node_id] + credibility * claim)
            signals.append({"actorId": signal["actorId"], "nodeId": node_id,
                            "value": claim, "credibility": credibility,
                            "period": signal["period"], "duePeriod": signal["duePeriod"]})
    levers = []
    for lever in actor["levers"]:
        if lever["nodeId"] not in permitted:
            continue
        levers.append({key: deepcopy(lever[key]) for key in
                       ("leverId", "nodeId", "minimum", "maximum", "cost", "lagPeriods", "reversible", "requiresConsent")})
    plans = []
    plan_rows = state.get("plans", {}).get(actor_id, []) if structured and "plans" in state else actor.get("plans", [])
    for plan in plan_rows:
        if plan["leverId"] not in {lever["leverId"] for lever in levers}:
            continue
        if (plan.get("condition") or {}).get("nodeId", "") not in permitted and plan.get("condition"):
            continue
        plans.append({key: deepcopy(plan[key]) for key in ("planId", "leverId", "value", "duePeriod", "condition", "status") if key in plan})
    objectives = [{key: row[key] for key in ("nodeId", "direction", "weight")}
                  for row in actor.get("objectives", []) if row["nodeId"] in permitted]
    capacity = (state.get("capacity", {}).get(actor_id, actor["constraints"]["capacity"])
                if structured else actor["constraints"]["capacity"])
    return {"schemaVersion": "target-actor-observation/v1", "actorId": actor_id,
            "period": period, "values": observations, "observedPeriods": observed_periods,
            "beliefs": beliefs, "signals": signals, "levers": levers, "plans": plans,
            "objectives": objectives, "capacity": finite(capacity),
            "decisionRule": {"kind": actor["decisionRule"]["kind"],
                             "cadencePeriods": actor["decisionRule"]["cadencePeriods"],
                             "triggers": [deepcopy(p) for p in actor["decisionRule"].get("triggers", [])
                                          if p["nodeId"] in permitted]}}


def rule_actions(observation):
    """Bounded direct-lever objectives; credible claims inform matching levers.

    A signal supplies an expectation for its node. With no received signal the
    stated objective selects the corresponding endpoint. This is deliberately a
    small transparent controller, not an implied optimal strategic policy.
    """
    actions = []
    signalled = {signal["nodeId"] for signal in observation["signals"]}
    for lever in observation["levers"]:
        node_id = lever["nodeId"]
        if node_id not in observation["values"]:
            continue
        objectives = [obj for obj in observation["objectives"] if obj["nodeId"] == node_id]
        direction = sum(obj["weight"] * (1 if obj["direction"] == "increase" else -1) for obj in objectives)
        if not direction:
            continue
        desired = (observation["beliefs"][node_id] if node_id in signalled
                   else lever["maximum"] if direction > 0 else lever["minimum"])
        desired = max(lever["minimum"], min(lever["maximum"], desired))
        if desired != observation["values"][node_id]:
            actions.append({"actorId": observation["actorId"], "leverId": lever["leverId"], "value": desired})
    return actions


class DecisionIdentities:
    """Reversible identifier-only boundary; names and source fields are never added."""

    _fields = {"actorId": "actor", "forActorId": "actor", "leverId": "lever",
               "nodeId": "node", "planId": "plan"}
    _lists = {"requiresConsent": "actor", "recipients": "actor", "nodeIds": "node"}
    _node_maps = {"values", "beliefs", "observedPeriods", "objectiveValues",
                  "baselineObjectiveValues", "objectiveDeltas"}

    def __init__(self, case):
        registries = {
            "actor": [row["actorId"] for row in case["actors"]],
            "node": [row["nodeId"] for row in case["nodes"]],
            "lever": [lever["leverId"] for row in case["actors"] for lever in row["levers"]],
            "plan": [plan["planId"] for row in case["actors"] for plan in row.get("plans", [])],
        }
        self.forward = {kind: {value: f"{kind}-{index + 1:04d}" for index, value in
                               enumerate(sorted(set(values)))} for kind, values in registries.items()}
        self.reverse = {kind: {token: value for value, token in entries.items()}
                        for kind, entries in self.forward.items()}

    def _identifier(self, value, kind, decoding):
        if not isinstance(value, str):
            raise ValueError("invalid opaque identifier")
        if not decoding and kind == "plan" and value not in self.forward[kind]:
            token = f"plan-{len(self.forward[kind]) + 1:04d}"
            self.forward[kind][value] = token
            self.reverse[kind][token] = value
        mapping = self.reverse if decoding else self.forward
        if value not in mapping[kind]:
            raise ValueError("unknown opaque identifier")
        return mapping[kind][value]

    def transform(self, value, *, decoding=False, field=None):
        if field in self._fields:
            return self._identifier(value, self._fields[field], decoding)
        if field in self._lists:
            if not isinstance(value, list):
                raise ValueError("invalid opaque references")
            return [self._identifier(item, self._lists[field], decoding) for item in value]
        if isinstance(value, dict):
            if field in self._node_maps:
                return {self._identifier(key, "node", decoding): deepcopy(item)
                        for key, item in value.items()}
            return {key: self.transform(item, decoding=decoding, field=key)
                    for key, item in value.items()}
        if isinstance(value, list):
            return [self.transform(item, decoding=decoding) for item in value]
        return deepcopy(value)

    def decode_actions(self, actions, actor_id):
        """A bad response field stays local to that action, not the whole round."""
        envelope = isinstance(actions, dict) and set(actions) == {"actions"}
        items = actions["actions"] if envelope else actions
        def decode(item):
            try:
                return self.transform(item, decoding=True)
            except ValueError:
                return {"actorId": actor_id, "kind": "invalid_opaque_action", "value": 0}
        if isinstance(items, list):
            decoded = [decode(item) for item in items]
            return {"actions": decoded} if envelope else decoded
        return decode(items)


def add_lookahead(observation, model):
    """Evaluate one-step own-lever options from visible beliefs, never latent truth.

    Declared prior midpoints are common structural assumptions, not the path's
    sampled parameters. Missing upstream inputs make the objective unavailable.
    Bounds/capacity are checked from observations only; the runtime remains the
    authoritative feasibility check, including consent and irreversible rights.
    """
    from .target_mechanisms import MechanismValidationError

    observation = deepcopy(observation)
    period = observation["period"]
    objectives = observation["objectives"]
    visible = observation["beliefs"]
    try:
        baseline = model.visible_projection(visible, period + 1)
    except MechanismValidationError:
        baseline = {}
    options = []
    for lever in observation["levers"]:
        node_id = lever["nodeId"]
        if node_id not in observation["values"]:
            continue
        current = observation["values"][node_id]
        for value in sorted(set((lever["minimum"], current, lever["maximum"]))):
            if not lever["minimum"] <= value <= lever["maximum"]:
                continue
            cost = abs(value - current) * lever["cost"]
            row = {"action": {"actorId": observation["actorId"], "leverId": lever["leverId"], "value": value},
                   "evaluationPeriod": period + 1, "effectivePeriod": period + lever["lagPeriods"],
                   "requiresConsent": list(lever["requiresConsent"]),
                   "parameterBasis": "declared_prior_midpoints", "informationBasis": "actor_visible_beliefs",
                   "feasibility": "preliminary_observed_constraints", "status": "evaluated"}
            if not math.isfinite(cost) or cost > observation["capacity"]:
                row.update(status="blocked", reason="observed_capacity", objectiveValues={},
                           baselineObjectiveValues={}, objectiveDeltas={}, score=None)
                options.append(row)
                continue
            candidate = dict(visible)
            if lever["lagPeriods"] <= 1:
                candidate[node_id] = value
            try:
                projected = model.visible_projection(candidate, period + 1)
            except MechanismValidationError:
                projected = {}
            available = bool(objectives) and all(obj["nodeId"] in projected and obj["nodeId"] in baseline for obj in objectives)
            outcomes = {obj["nodeId"]: projected[obj["nodeId"]] for obj in objectives if obj["nodeId"] in projected}
            reference = {obj["nodeId"]: baseline[obj["nodeId"]] for obj in objectives if obj["nodeId"] in baseline}
            deltas = {key: outcomes[key] - reference[key] for key in outcomes.keys() & reference.keys()}
            if any(not math.isfinite(value) for value in deltas.values()):
                available, deltas = False, {}
            score = sum((1 if obj["direction"] == "increase" else -1) * obj["weight"] *
                        (deltas[obj["nodeId"]] / max(1, abs(reference[obj["nodeId"]])))
                        for obj in objectives) if available else None
            if score is not None and not math.isfinite(score):
                available, score = False, None
            row.update(objectiveValues=outcomes, baselineObjectiveValues=reference,
                       objectiveDeltas=deltas, score=score,
                       status="evaluated" if available else "unavailable",
                       reason=("lag_outside_one_step" if lever["lagPeriods"] > 1 else "conditional_on_consent" if lever["requiresConsent"] else "visible_model") if available else "insufficient_visible_inputs")
            options.append(row)
    observation["options"] = options
    return observation
