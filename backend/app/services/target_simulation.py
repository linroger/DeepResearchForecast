"""Deterministic target-first structural paths, with an explicit actor boundary.

This module has no provider client and performs no import-time I/O. The optional
one-argument decision callback belongs to the caller. Simulation remains a
zero-weight diagnostic estimator, independent of research scenario assessments.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from functools import wraps
import hashlib
import json
import math
import random

from .target_actors import (DecisionIdentities, add_lookahead, finite, integer, predicate_matches, rule_actions,
                            safe_observation, validate_predicate,
                            validate_scenarios)
from .target_mechanisms import MechanismValidationError, compile_model


class SimulationCancelled(RuntimeError):
    """A caller cancelled a structural path run before publication."""


class _CallerCancellation(BaseException):
    """Carry hook failures through field-repair handlers without reclassification."""

    def __init__(self, original):
        self.original = original


def _cancellation_boundary(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except _CallerCancellation as failure:
            raise failure.original
    return call


def _cancel(check):
    if check is None:
        return
    try:
        cancelled = check()
    except Exception as exc:
        raise _CallerCancellation(exc) from exc
    if cancelled:
        raise SimulationCancelled("target simulation cancelled")


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _case_api():
    # Production backend/run.py does not add the repository root to sys.path.
    from .official_data import bridge_module
    return bridge_module("forecast_case")


def actor_observation(case, state, actor_id, *, period=0, lookahead=False, identity_mode="named",
                      anchor_context=None, at=None):
    """Return a detached, typed actor-specific projection of dated state."""
    validated = _case_api().validate_case(case)
    _identity_mode(identity_mode)
    if not isinstance(lookahead, bool):
        raise ValueError("lookahead must be boolean")
    if anchor_context is not None:
        _validate_anchor(validated, anchor_context)
        observation = safe_observation(validated, state, actor_id, period=period,
                                       anchor_context=anchor_context, at=at)
    else:
        observation = safe_observation(_decision_case(validated), state, actor_id, period=period)
    if lookahead:
        observation = add_lookahead(observation, compile_model(validated))
    return DecisionIdentities(validated).transform(observation) if identity_mode == "opaque" else observation



def _identity_mode(mode):
    if mode not in ("opaque", "named"):
        raise ValueError("identity_mode must be opaque or named")


def _decision_case(case):
    """Remove assessments/classifiers/prose before entering any actor runtime."""
    return {
        "nodes": [{key: deepcopy(node[key]) for key in
                   ("nodeId", "visibility", "ownerActorId") if key in node}
                  for node in case["nodes"]],
        "actors": [{key: deepcopy(actor[key]) for key in
                    ("actorId", "objectives", "constraints", "levers", "decisionRule",
                     "plans", "information", "credibility")}
                   for actor in case["actors"]],
        "resolution": {"targetNodeId": case["resolution"]["targetNodeId"]},
    }


def _validate_anchor(case, context):
    from .official_data import bridge_module
    from .world_anchor import validate_anchor_context
    validate_anchor_context(context, engine="target-first-v1")
    return bridge_module("world_anchor_case").validate_anchored_case(
        case, pack=context.pack, requirements=context.requirements,
        index=context.index, policy=context.policy)


def _anchor_time(case, context, period, periods):
    start = datetime.fromisoformat(context.pack["scope"]["cutoff"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(case["resolution"]["horizon"] + "T23:59:59+00:00")
    return (start + (end - start) * (period / periods)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_actors(case):
    if sum(actor["decisionRule"]["kind"] == "llm" for actor in case["actors"]) > 8:
        raise ValueError("target simulation permits at most eight llm-decision actors")
    nodes = {node["nodeId"] for node in case["nodes"]}
    writers = {mechanism["outputNodeId"] for mechanism in case["mechanisms"]}
    actor_ids = {actor["actorId"] for actor in case["actors"]}
    for actor in case["actors"]:
        finite(actor["constraints"]["capacity"], "capacity")
        if actor["constraints"]["capacity"] < 0:
            raise ValueError("capacity cannot be negative")
        integer(actor["decisionRule"]["cadencePeriods"], "cadencePeriods", 1)
        if actor["decisionRule"]["kind"] not in {"rule", "llm"}:
            raise ValueError("unsupported actor decision rule")
        integer(actor["information"]["releaseLagPeriods"], "releaseLagPeriods")
        if not set(actor["information"]["nodeIds"]) <= nodes:
            raise ValueError("information references an invalid node")
        if not 0 <= finite(actor["credibility"]) <= 1:
            raise ValueError("credibility must be between zero and one")
        levers = {}
        for lever in actor["levers"]:
            if lever["leverId"] in levers:
                raise ValueError("duplicate actor leverId")
            levers[lever["leverId"]] = lever
            if lever["nodeId"] not in nodes or lever["nodeId"] in writers:
                raise ValueError("lever must control an existing primitive node, not a mechanism output")
            if finite(lever["minimum"]) > finite(lever["maximum"]):
                raise ValueError("lever bounds reversed")
            if finite(lever["cost"]) < 0:
                raise ValueError("lever cost cannot be negative")
            integer(lever["lagPeriods"], "lagPeriods")
            if not isinstance(lever["reversible"], bool):
                raise ValueError("reversible must be boolean")
            if not set(lever["requiresConsent"]) <= actor_ids - {actor["actorId"]}:
                raise ValueError("invalid consent actor reference")
        for objective in actor.get("objectives", []):
            if objective["nodeId"] not in nodes or objective["direction"] not in {"increase", "decrease"}:
                raise ValueError("invalid objective")
            if finite(objective["weight"]) < 0:
                raise ValueError("objective weight cannot be negative")
        for trigger in actor["decisionRule"].get("triggers", []):
            validate_predicate(trigger, nodes)
        plan_ids = set()
        for plan in actor.get("plans", []):
            if plan["planId"] in plan_ids or plan["leverId"] not in levers:
                raise ValueError("invalid or duplicate plan")
            plan_ids.add(plan["planId"])
            integer(plan["duePeriod"], "duePeriod")
            lever = levers[plan["leverId"]]
            if not lever["minimum"] <= finite(plan["value"]) <= lever["maximum"]:
                raise ValueError("plan value outside lever bounds")
            if plan.get("condition") is not None:
                validate_predicate(plan["condition"], nodes)


def _safe_action(action, actor_id):
    """Reject untyped payloads without ever persisting raw callback text."""
    if not isinstance(action, dict) or action.get("actorId") != actor_id:
        raise ValueError("rights")
    kind = action.get("kind", "lever")
    common = {"kind", "actorId", "value"}
    extras = {"lever": {"leverId", "consents"},
              "commitment": {"leverId", "duePeriod", "condition", "consents"},
              "consent": {"forActorId", "leverId"},
              "signal": {"nodeId", "recipients", "duePeriod"}}
    if not isinstance(kind, str) or kind not in extras or set(action) - common - extras[kind]:
        raise ValueError("action_schema")
    finite(action.get("value"))
    if kind in {"lever", "commitment", "consent"} and not isinstance(action.get("leverId"), str):
        raise ValueError("action_schema")
    for key in ("nodeId", "forActorId"):
        if key in action and not isinstance(action[key], str):
            raise ValueError("action_schema")
    if "duePeriod" in action:
        integer(action["duePeriod"], "duePeriod")
    if "condition" in action and action["condition"] is not None:
        if not isinstance(action["condition"], dict):
            raise ValueError("action_schema")
    if "recipients" in action and (not isinstance(action["recipients"], list)
                                  or not all(isinstance(item, str) for item in action["recipients"])):
        raise ValueError("action_schema")
    if "consents" in action and (not isinstance(action["consents"], list)
                                or not all(isinstance(item, str) for item in action["consents"])):
        raise ValueError("action_schema")
    return deepcopy({**action, "kind": kind})


def _record(period, actor_id, status, reason, action=None):
    row = {"period": period, "actorId": actor_id, "status": status, "reason": reason}
    if action:
        for key in ("kind", "leverId", "value", "nodeId", "duePeriod", "planId"):
            if key in action:
                row[key] = deepcopy(action[key])
    return row



def _lever_error(action, actor_id, levers, values, capacities, pending,
                 irreversible, consents, model, parameters, period):
    """Field-local feasibility; never reserves capacity or changes world state."""
    key = (actor_id, action["leverId"])
    lever = levers.get(key)
    if lever is None:
        return "rights", 0, 0
    if not lever["minimum"] <= action["value"] <= lever["maximum"]:
        return "bounds", 0, 0
    delta = action["value"] - values[lever["nodeId"]]
    cost = abs(delta) * lever["cost"]
    if any(levers[(item["actorId"], item["leverId"])]["nodeId"] == lever["nodeId"] for item in pending):
        return "pending_effect", cost, delta
    if any((other, actor_id, action["leverId"], action["value"]) not in consents for other in lever["requiresConsent"]):
        return "consent", cost, delta
    if not math.isfinite(cost) or cost > capacities[actor_id]:
        return "capacity", cost, delta
    if not lever["reversible"] and delta * irreversible.get(key, 0) < 0:
        return "irreversible", cost, delta
    try:
        model.propagate({**values, lever["nodeId"]: action["value"]},
                        parameters, period + lever["lagPeriods"])
    except MechanismValidationError:
        return "mechanism_constraint", cost, delta
    return None, cost, delta


def _run_path(case, model, initial, parameters, periods, *, callback=None,
              baseline=False, cancel_check=None, lookahead=False, identity_mode="opaque", path_id=None,
              anchor_context=None):
    identities = DecisionIdentities(case)
    actors = sorted(case["actors"], key=lambda actor: actor["actorId"])
    actors_by_id = {actor["actorId"]: actor for actor in actors}
    levers = {(actor["actorId"], lever["leverId"]): lever for actor in actors for lever in actor["levers"]}
    values = model.propagate(dict(initial), parameters, 0)
    history = [{"period": 0, "values": dict(values)}]
    decisions, pending, signals = [], [], []
    capacities = {actor["actorId"]: float(actor["constraints"]["capacity"]) for actor in actors}
    credibility = {actor["actorId"]: float(actor["credibility"]) for actor in actors}
    plans = {actor["actorId"]: [{**deepcopy(plan), "status": "pending"} for plan in (actor.get("plans", []) if not baseline else [])]
             for actor in actors}
    previous_triggers = {actor["actorId"]: [False] * len(actor["decisionRule"].get("triggers", [])) for actor in actors}
    irreversible = {}
    if anchor_context is not None:
        simulated_plans = {actor["actorId"]: set() for actor in actors}
        simulated_nodes = {actor["actorId"]: set() for actor in actors}
    for period in range(1, periods + 1):
        _cancel(cancel_check)
        for action in list(pending):
            if action["effectivePeriod"] == period:
                lever = levers[(action["actorId"], action["leverId"])]
                candidate = {**values, lever["nodeId"]: action["value"]}
                try:
                    model.propagate(candidate, parameters, period)
                except MechanismValidationError:
                    capacities[action["actorId"]] += action["reservedCost"]
                    key = (action["actorId"], action["leverId"])
                    irreversible[key] = action["previousDirection"]
                    status, reason = "blocked", "effect_constraint"
                else:
                    values = candidate
                    if anchor_context is not None:
                        simulated_nodes[action["actorId"]].add(lever["nodeId"])
                    status, reason = "applied", "lag_elapsed"
                decisions.append(_record(period, action["actorId"], status, reason, action))
                for plan in plans[action["actorId"]]:
                    if plan["planId"] == action.get("planId"):
                        plan["status"] = status
                pending.remove(action)
        values = model.propagate(values, parameters, period)
        history.append({"period": period, "values": dict(values)})
        if baseline:
            continue
        state = {"values": values, "history": history, "plans": plans, "signals": signals,
                 "capacity": capacities, "credibility": credibility}
        if anchor_context is not None:
            state.update(simulatedPlanIds=simulated_plans, simulatedOwnNodeIds=simulated_nodes)
            observations = {actor["actorId"]: safe_observation(
                case, state, actor["actorId"], period=period, anchor_context=anchor_context,
                at=_anchor_time(case, anchor_context, period, periods)) for actor in actors}
        else:
            observations = {actor["actorId"]: safe_observation(case, state, actor["actorId"], period=period) for actor in actors}
        proposals = []
        # Decisions are collected from the same beginning-of-period information
        # set. No same-period actor ordering leaks another actor's intervention.
        for actor in actors:
            actor_id = actor["actorId"]
            observation = observations[actor_id]
            for plan in plans[actor_id]:
                if anchor_context is not None and plan["planId"] not in {p["planId"] for p in observation["plans"]}:
                    continue
                if (plan["status"] == "pending" and plan["duePeriod"] <= period
                        and (not plan.get("condition") or predicate_matches(plan["condition"], observation["values"]))):
                    proposals.append((actor_id, {"kind": "lever", "actorId": actor_id,
                                                "leverId": plan["leverId"], "value": plan["value"], "planId": plan["planId"]}, plan))
            triggers = [predicate_matches(trigger, observation["values"])
                        for trigger in actor["decisionRule"].get("triggers", [])]
            fired = any(now and not before for now, before in zip(triggers, previous_triggers[actor_id]))
            previous_triggers[actor_id] = triggers
            cadence = (period - 1) % actor["decisionRule"]["cadencePeriods"] == 0
            counterparty = any(signal["period"] == period - 1 and actor_id in signal["recipients"] for signal in signals)
            if not (fired or cadence or counterparty):
                continue
            if actor["decisionRule"]["kind"] == "llm" and callback is not None:
                _cancel(cancel_check)
                try:
                    decision_observation = add_lookahead(observation, model) if lookahead else deepcopy(observation)
                    if identity_mode == "opaque":
                        decision_observation = identities.transform(decision_observation)
                    from .run_spending import model_operation
                    with model_operation("actor", {"case": case.get("caseId"), "path": path_id,
                                                    "period": period, "actor": actor_id,
                                                    "observation": _hash(decision_observation)}):
                        actions = callback(decision_observation)
                    if identity_mode == "opaque":
                        actions = identities.decode_actions(actions, actor_id)
                except SimulationCancelled:
                    raise
                except Exception as error:
                    from .run_spending import api as spending_api
                    if spending_api().is_spending_stop(error):
                        raise
                    # Repair a failed field/actor; the deterministic world still
                    # propagates. Exception messages may contain private prompts.
                    decisions.append(_record(period, actor_id, "blocked", "decision_provider_error"))
                    continue
            else:
                planned_levers = {plan["leverId"] for plan in plans[actor_id]
                                  if plan["status"] in {"pending", "scheduled"}}
                actions = [action for action in rule_actions(observation)
                           if action["leverId"] not in planned_levers]
            if actions is None:
                actions = []
            elif isinstance(actions, dict):
                actions = actions["actions"] if set(actions) == {"actions"} else [actions]
            if not isinstance(actions, list) or len(actions) > 100:
                decisions.append(_record(period, actor_id, "blocked", "action_schema"))
                continue
            for action in actions:
                try:
                    safe = _safe_action(action, actor_id)
                except (ValueError, TypeError):
                    decisions.append(_record(period, actor_id, "blocked", "invalid_action"))
                    continue
                proposals.append((actor_id, safe, None))
        _cancel(cancel_check)
        consents = set()
        for actor_id, action, _ in proposals:
            if action["kind"] != "consent":
                continue
            target_actor = action.get("forActorId")
            key = (target_actor, action["leverId"])
            lever = levers.get(key)
            if (lever is not None and actor_id in lever["requiresConsent"]
                    and lever["nodeId"] in observations[actor_id]["values"]):
                consents.add((actor_id, target_actor, action["leverId"], action["value"]))
                decisions.append(_record(period, actor_id, "accepted", "consent", action))
            else:
                decisions.append(_record(period, actor_id, "blocked", "consent_rights", action))
        # Rejected fields cannot veto valid proposals via the conflict set.
        # Preflight uses the common beginning-of-period state; the apply pass
        # rechecks budgets after each accepted field to enforce aggregate limits.
        feasible = []
        for actor_id, action, plan in proposals:
            reason = None
            if action["kind"] == "lever":
                reason, _, _ = _lever_error(action, actor_id, levers, values,
                    capacities, pending, irreversible, consents, model, parameters, period)
            if reason is not None:
                decisions.append(_record(period, actor_id, "blocked", reason, action))
                if plan is not None:
                    plan["status"] = "blocked"
            else:
                feasible.append((actor_id, action, plan))
        proposals = feasible
        # Conflicting simultaneous writes are blocked together. No UUID or cast
        # iteration order arbitrarily awards a shared control to one actor.
        writers = {}
        for actor_id, action, _ in proposals:
            if action["kind"] == "lever" and (actor_id, action["leverId"]) in levers:
                node_id = levers[(actor_id, action["leverId"])]["nodeId"]
                writers.setdefault(node_id, set()).add((actor_id, action["value"]))
        for actor_id, action, plan in proposals:
            kind = action["kind"]
            if kind == "consent":
                continue
            if kind == "signal":
                recipients = action.get("recipients", [])
                node_id = action.get("nodeId")
                due = action.get("duePeriod", period + 1)
                valid = (isinstance(recipients, list) and bool(recipients)
                         and all(isinstance(r, str) and r in observations and node_id in observations[r]["values"] for r in recipients)
                         and node_id in observations[actor_id]["values"]
                         and isinstance(due, int) and not isinstance(due, bool) and due > period)
                if valid:
                    signals.append({"actorId": actor_id, "nodeId": node_id, "value": action["value"],
                                    "recipients": sorted(set(recipients)), "period": period,
                                    "duePeriod": due, "resolved": False})
                decisions.append(_record(period, actor_id, "accepted" if valid else "blocked",
                                         "signal" if valid else "signal_information", action))
                continue
            key = (actor_id, action["leverId"])
            lever = levers.get(key)
            reason = None
            if lever is None:
                reason = "rights"
            elif not lever["minimum"] <= action["value"] <= lever["maximum"]:
                reason = "bounds"
            elif kind == "commitment":
                try:
                    due = integer(action.get("duePeriod"), "duePeriod", period + 1)
                    if action.get("condition") is not None:
                        validate_predicate(action["condition"], set(observations[actor_id]["values"]))
                except (ValueError, TypeError):
                    reason = "commitment_condition_or_date"
                else:
                    plans[actor_id].append({"planId": f"commitment-{period}-{len(plans[actor_id])}",
                                           "leverId": action["leverId"], "value": action["value"],
                                           "duePeriod": due, "condition": deepcopy(action.get("condition")), "status": "pending"})
                    if anchor_context is not None:
                        simulated_plans[actor_id].add(plans[actor_id][-1]["planId"])
                    decisions.append(_record(period, actor_id, "accepted", "commitment", action))
                    continue
            if reason is None:
                reason, cost, delta = _lever_error(action, actor_id, levers, values,
                    capacities, pending, irreversible, consents, model, parameters, period)
                if reason is None and len(writers.get(lever["nodeId"], [])) > 1:
                    reason = "simultaneous_conflict"
            if reason is not None:
                decisions.append(_record(period, actor_id, "blocked", reason, action))
                if plan is not None:
                    plan["status"] = "blocked"
                continue
            capacities[actor_id] -= cost
            previous_direction = irreversible.get(key, 0)
            if not lever["reversible"] and delta:
                irreversible[key] = 1 if delta > 0 else -1
            effective = period + lever["lagPeriods"]
            accepted = {**action, "effectivePeriod": effective,
                        "reservedCost": cost, "previousDirection": previous_direction}
            if lever["lagPeriods"]:
                pending.append(accepted)
                status = "scheduled"
            else:
                values[lever["nodeId"]] = action["value"]
                if anchor_context is not None:
                    simulated_nodes[actor_id].add(lever["nodeId"])
                status = "applied"
            row = _record(period, actor_id, status, "lever", action)
            row.update(effectivePeriod=effective, cost=cost, remainingCapacity=capacities[actor_id])
            decisions.append(row)
            if plan is not None:
                plan["status"] = status
        values = model.propagate(values, parameters, period)
        history[-1] = {"period": period, "values": dict(values)}
        # Score final-period truth only after every recipient's public release
        # lag. Beginning-of-period truth may still change through interventions.
        for signal in signals:
            lag = max((actors_by_id[recipient]["information"]["releaseLagPeriods"]
                       for recipient in signal["recipients"]), default=0)
            if signal["resolved"] or period < signal["duePeriod"] + lag:
                continue
            truth = next((row["values"][signal["nodeId"]] for row in history if row["period"] == signal["duePeriod"]), None)
            if truth is None:
                continue
            scale = max(1.0, abs(truth), abs(signal["value"]))
            score = 1.0 - min(1.0, abs(truth / scale - signal["value"] / scale))
            credibility[signal["actorId"]] = (credibility[signal["actorId"]] + score) / 2
            signal.update(resolved=True, score=score, resolvedPeriod=period)
    return {"parameters": deepcopy(parameters), "initialValues": deepcopy(history[0]["values"] if anchor_context is not None else initial),
            "trajectory": history, "decisions": decisions, "plans": plans,
            "pendingEffects": pending, "signals": signals, "credibility": credibility,
            "remainingCapacity": capacities,
            "targetValue": finite(values[case["resolution"]["targetNodeId"]])}


def _summary(values):
    ordered = sorted(values)
    def quantile(q):
        position = (len(ordered) - 1) * q
        low = math.floor(position)
        high = math.ceil(position)
        return ordered[low] * (high - position) + ordered[high] * (position - low) if low != high else ordered[low]
    return {"count": len(values), "mean": finite(math.fsum(value / len(values) for value in values)),
            "minimum": ordered[0], "maximum": ordered[-1],
            "p05": quantile(.05), "median": quantile(.5), "p95": quantile(.95)}


def _shares(case, paths):
    counts = {scenario["scenarioId"]: 0 for scenario in case.get("scenarios", [])}
    counts["other"] = 0
    for path in paths:
        terminal = path["trajectory"][-1]["values"]
        matched = [scenario["scenarioId"] for scenario in case.get("scenarios", [])
                   if predicate_matches(scenario["predicate"], terminal)]
        if len(matched) > 1:
            raise ValueError("overlapping terminal scenario predicates")
        counts[matched[0] if matched else "other"] += 1
    return {key: count / len(paths) for key, count in counts.items()}



def _contrast(endings):
    feasible = None not in endings
    delta = endings[1] - endings[0] if feasible else None
    finite_delta = delta is not None and math.isfinite(delta)
    return {"targetAtLow": endings[0], "targetAtHigh": endings[1],
            "targetDelta": delta if finite_delta else None,
            "status": ("infeasible_endpoint" if not feasible else
                       "feasible" if finite_delta else "nonfinite_contrast"),
            "method": "bounded_structural_contrast"}


def _diagnostics(case, model, initial, parameters, periods, cancel_check):
    """Finite structural contrasts with fixed draws; these are not causal estimates."""
    decision_case = _decision_case(case)
    sensitivity = []
    written = {mechanism["outputNodeId"] for mechanism in case["mechanisms"]}
    for node in case["nodes"]:
        if node["nodeId"] in written or not node.get("range"):
            continue
        low, high = node["range"]["low"], node["range"]["high"]
        if low == high:
            continue
        _cancel(cancel_check)
        endings = []
        for value in (low, high):
            changed = {**initial, node["nodeId"]: value}
            try:
                endings.append(_run_path(decision_case, model, changed, parameters, periods, baseline=True, cancel_check=cancel_check)["targetValue"])
            except MechanismValidationError:
                endings.append(None)
        sensitivity.append({"nodeId": node["nodeId"], "low": low, "high": high,
                            **_contrast(endings)})
    # Compiler-flattened bounds also include coefficients in linear vectors.
    for mechanism_id, scalar_bounds in model.parameter_bounds.items():
        for key, spec in scalar_bounds.items():
            if spec["low"] == spec["high"]:
                continue
            _cancel(cancel_check)
            endings = []
            for value in (spec["low"], spec["high"]):
                changed = deepcopy(parameters)
                changed[mechanism_id][key] = value
                try:
                    endings.append(_run_path(decision_case, model, initial, changed, periods, baseline=True, cancel_check=cancel_check)["targetValue"])
                except MechanismValidationError:
                    endings.append(None)
            sensitivity.append({"mechanismId": mechanism_id, "parameter": key,
                                "low": spec["low"], "high": spec["high"], **_contrast(endings)})
    return sensitivity


@_cancellation_boundary
def run_paths(case, *, paths=32, periods=12, seed=0, decision_provider=None, cancel_check=None,
              lookahead=False, identity_mode="opaque", interventions=None, conditions=None,
              model_validation="off", hindcast_snapshots=None, anchor_context=None):
    """Compile once and run K seeded closed-loop paths without provider side effects.

    ``decision_provider(observation)`` takes one detached typed dictionary and
    returns a lever action, a list of actions, or ``{"actions": [...]}``.
    ``cancel_check()`` returning truthy raises SimulationCancelled; exceptions
    from the check propagate unchanged. No partial success record is returned.
    """
    _identity_mode(identity_mode)
    if not isinstance(lookahead, bool):
        raise ValueError("lookahead must be boolean")
    if model_validation not in ("off", "diagnostic", "strict", "admission"):
        raise ValueError("model_validation must be off, diagnostic, strict or admission")
    integer(paths, "paths", 1)
    integer(periods, "periods", 1)
    integer(seed, "seed", 0)
    if paths > 10000 or periods > 10000 or paths * periods > 1000000:
        raise ValueError("run exceeds bounded path/period budget")
    if decision_provider is not None and not callable(decision_provider):
        raise ValueError("decision_provider must be callable")
    if cancel_check is not None and not callable(cancel_check):
        raise ValueError("cancel_check must be callable")
    _cancel(cancel_check)
    api = _case_api()
    validated = api.validate_case(case)
    if anchor_context is not None:
        validated = _validate_anchor(validated, anchor_context)
        if hindcast_snapshots is not None:
            from .official_data import bridge_module
            raise bridge_module("world_anchor").AnchorError("E_NOT_READY", "unsupported_anchored_hindcast")
    validate_scenarios(validated)
    _validate_actors(validated)
    model = compile_model(validated)
    intervention_requests, condition_requests = _table_requests(validated, interventions, conditions, periods)
    validation = None
    if model_validation == "admission":
        from .target_mechanisms import admit_model
        validation = admit_model(validated)
    elif model_validation != "off":
        from .target_mechanisms import validate_model
        validation = validate_model(validated, strict=model_validation == "strict")
    hindcast_results = (validate_hindcasts(validated, hindcast_snapshots, paths=paths, periods=periods,
                                          seed=seed, cancel_check=cancel_check)
                        if hindcast_snapshots is not None else None)
    decision_case = validated if anchor_context is not None else _decision_case(validated)
    results, baselines = [], []
    for index in range(paths):
        _cancel(cancel_check)
        path_seed = int(_hash({"seed": seed, "pathIndex": index})[:16], 16)
        rng = random.Random(path_seed)
        initial = model.initial_values(rng)
        parameters = model.draw_parameters(rng)
        path_options = {"anchor_context": anchor_context} if anchor_context is not None else {}
        path = _run_path(decision_case, model, initial, parameters, periods, callback=decision_provider,
                         cancel_check=cancel_check, lookahead=lookahead, identity_mode=identity_mode,
                         path_id=f"path-{index:05d}", **path_options)
        path.update(pathId=f"path-{index:05d}", seed=path_seed)
        baseline = _run_path(decision_case, model, initial, parameters, periods, baseline=True, cancel_check=cancel_check, **path_options)
        baseline.update(pathId=path["pathId"], seed=path_seed)
        results.append(path)
        baselines.append(baseline)
    sensitivity = _diagnostics(validated, model, results[0]["initialValues"], results[0]["parameters"], periods, cancel_check)
    baseline = deepcopy(baselines[0])
    start = date.fromisoformat(validated["asOf"])
    horizon = date.fromisoformat(validated["resolution"]["horizon"])
    if horizon < start:
        raise ValueError("horizon precedes asOf")
    release_lag = validated["resolution"]["settlementSource"]["releaseLagDays"]
    def period_date(period):
        return (start + timedelta(days=round((horizon - start).days * period / periods))).isoformat()
    signposts = [{"nodeId": node["nodeId"], "date": horizon.isoformat(),
                  "expectedRange": {"low": min(path["trajectory"][-1]["values"][node["nodeId"]] for path in results),
                                    "high": max(path["trajectory"][-1]["values"][node["nodeId"]] for path in results)},
                  "sourceIds": list(node.get("sourceIds", [])), "basis": "simulated_terminal_range"}
                 for node in validated["nodes"] if node.get("pivotal") or node["nodeId"] == validated["resolution"]["targetNodeId"]]
    for signpost in signposts:
        if signpost["nodeId"] == validated["resolution"]["targetNodeId"]:
            signpost["releaseDate"] = (horizon + timedelta(days=release_lag)).isoformat()
    for actor in validated["actors"]:
        for plan in actor.get("plans", []):
            lever = next(item for item in actor["levers"] if item["leverId"] == plan["leverId"])
            signposts.append({"actorId": actor["actorId"], "nodeId": lever["nodeId"],
                              "date": period_date(max(1, plan["duePeriod"]) + lever["lagPeriods"]),
                              "value": plan["value"], "condition": deepcopy(plan.get("condition")),
                              "basis": "planned_earliest_effect"})
        for trigger in actor["decisionRule"].get("triggers", []):
            signposts.append({"actorId": actor["actorId"], "nodeId": trigger["nodeId"],
                              "date": period_date(1),
                              "predicate": deepcopy(trigger), "basis": "actor_trigger"})
    # Structural identity intentionally excludes scenarios and research prose.
    structural = {"nodes": [{key: deepcopy(node[key]) for key in ("nodeId", "value", "range", "visibility", "ownerActorId") if key in node}
                            for node in validated["nodes"]],
                  "mechanisms": validated["mechanisms"],
                  "actors": [{key: deepcopy(actor[key]) for key in ("actorId", "objectives", "constraints", "levers", "decisionRule", "plans", "information", "credibility")}
                             for actor in validated["actors"]]}
    replay = {"version": "target-runtime/v1", "seed": seed, "rng": "python.random.Random/MT19937",
              "pathSeeds": [path["seed"] for path in results], "periods": periods,
              "structuralHash": _hash(structural), "decisionMode": "callback" if decision_provider else "rule", "identityMode": identity_mode,
              "lookahead": lookahead,
              "decisionHash": _hash([path["decisions"] for path in results]),
              "outputHash": _hash(results),
              "callbackReplayRequirement": "Supply the same typed callback outputs for the same ordered observations."}
    output = {"schemaVersion": "target-simulation/v1", "caseId": validated["caseId"],
              "caseHash": api.case_hash(validated), "seed": seed, "paths": results,
              "scenarioShares": _shares(validated, results), "targetSummary": _summary([path["targetValue"] for path in results]),
              "baseline": baseline, "baselinePaths": baselines,
              "baselineSummary": _summary([path["targetValue"] for path in baselines]),
              "baselineScenarioShares": _shares(validated, baselines),
              "sensitivity": sensitivity, "signposts": signposts,
              "parameterBases": deepcopy(model.parameter_bases), "replay": replay,
              "simulationWeight": 0.0}
    if anchor_context is not None:
        output["worldAnchor"] = {"adapterVersion": "world-anchor-target/v1",
                                 "packHash": anchor_context.pack_hash,
                                 "contractHash": anchor_context.pack["contract_hash"],
                                 "inputHash": anchor_context.pack["input_hash"],
                                 "caseHash": output["caseHash"]}
    if validation is not None:
        output["modelValidation"] = validation
    if interventions is not None:
        output["interventionTables"] = _intervention_tables(validated, model, baselines, intervention_requests, periods, cancel_check)
    if conditions is not None:
        output["conditionalTables"] = _conditional_tables(validated, results, condition_requests)
    if hindcast_snapshots is not None:
        output["hindcastValidation"] = hindcast_results
    # Guard arithmetic overflow and accidental non-JSON callback data at output.
    json.dumps(output, allow_nan=False)
    return output


def _request_rows(rows, name, id_key):
    if rows is None:
        return []
    if not isinstance(rows, list) or len(rows) > 32:
        raise ValueError(f"{name} must be a list with at most 32 entries")
    identifiers = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get(id_key), str) or not row[id_key].strip():
            raise ValueError(f"{name} requires {id_key}")
        if row[id_key] in identifiers:
            raise ValueError(f"duplicate {id_key}")
        identifiers.add(row[id_key])
    return deepcopy(rows)


def _table_requests(case, interventions, conditions, periods):
    interventions = _request_rows(interventions, "interventions", "interventionId")
    conditions = _request_rows(conditions, "conditions", "conditionId")
    levers = {(actor["actorId"], lever["leverId"]): lever
              for actor in case["actors"] for lever in actor["levers"]}
    for row in interventions:
        if set(row) != {"interventionId", "settings"} or not isinstance(row["settings"], list) or not 1 <= len(row["settings"]) <= 16:
            raise ValueError("intervention requires 1..16 declared settings")
        writes = set()
        for setting in row["settings"]:
            if not isinstance(setting, dict) or set(setting) - {"actorId", "leverId", "value", "period"}:
                raise ValueError("invalid intervention setting")
            actor_id, lever_id = setting.get("actorId"), setting.get("leverId")
            if not isinstance(actor_id, str) or not isinstance(lever_id, str):
                raise ValueError("intervention requires actor and lever identifiers")
            lever = levers.get((actor_id, lever_id))
            if lever is None:
                raise ValueError("intervention references an undeclared actor lever")
            value = finite(setting.get("value"), "intervention value")
            period = integer(setting.get("period", 1), "intervention period", 1)
            if period > periods or not lever["minimum"] <= value <= lever["maximum"]:
                raise ValueError("intervention outside declared period or lever bounds")
            effective = period + lever["lagPeriods"]
            slot = (lever["nodeId"], effective)
            if slot in writes:
                raise ValueError("intervention contains conflicting simultaneous settings")
            writes.add(slot)
            setting.update(period=period, effectivePeriod=effective, nodeId=lever["nodeId"])
    nodes = {node["nodeId"] for node in case["nodes"]}
    for row in conditions:
        if set(row) - {"conditionId", "predicate", "period"} or "predicate" not in row:
            raise ValueError("invalid observational condition")
        validate_predicate(row["predicate"], nodes)
        row["period"] = integer(row.get("period", periods), "condition period")
        if row["period"] > periods:
            raise ValueError("condition period exceeds modeled horizon")
    return interventions, conditions


def _conditional_tables(case, paths, conditions):
    tables = []
    for condition in conditions:
        selected = [path for path in paths if predicate_matches(condition["predicate"],
                    path["trajectory"][condition["period"]]["values"])]
        tables.append({**deepcopy(condition), "kind": "observational_conditioning",
                       "causalInterpretation": "none; selection on existing simulated paths",
                       "status": "measured" if selected else "empty_subset", "sampleCount": len(selected),
                       "totalPaths": len(paths), "selectedPathIds": [path["pathId"] for path in selected],
                       "targetSummary": _summary([path["targetValue"] for path in selected]) if selected else None,
                       "scenarioShares": _shares(case, selected) if selected else None,
                       "simulationWeight": 0.0})
    return tables


def _intervention_tables(case, model, baselines, requests, periods, cancel_check):
    tables = []
    for request in requests:
        changed_paths, failures, pairs = [], [], []
        for reference in baselines:
            _cancel(cancel_check)
            values = dict(reference["initialValues"])
            parameters = reference["parameters"]
            trajectory = []
            try:
                for period in range(periods + 1):
                    _cancel(cancel_check)
                    for setting in request["settings"]:
                        if setting["effectivePeriod"] == period:
                            values[setting["nodeId"]] = setting["value"]
                    values = model.propagate(values, parameters, period)
                    trajectory.append({"period": period, "values": dict(values)})
            except MechanismValidationError:
                failures.append(reference["pathId"])
                continue
            value = values[case["resolution"]["targetNodeId"]]
            changed_paths.append({"pathId": reference["pathId"], "parameters": deepcopy(parameters),
                                  "initialValues": deepcopy(reference["initialValues"]),
                                  "trajectory": trajectory, "targetValue": value})
            delta = value - reference["targetValue"]
            pairs.append({"pathId": reference["pathId"], "referenceTarget": reference["targetValue"],
                          "intervenedTarget": value, "delta": delta if math.isfinite(delta) else None})
        complete = not failures
        deltas = [pair["delta"] for pair in pairs]
        tables.append({**deepcopy(request), "kind": "intervention", "reference": "paired_no_actor_baseline",
                       "causalInterpretation": "structural_do_under_declared_equations",
                       "feasibility": "not_assessed; actor capacity, consent and policy response are not assumed",
                       "actorPolicy": "disabled", "status": "measured" if complete else "infeasible_model",
                       "paths": changed_paths, "pairs": pairs, "invalidPathIds": failures,
                       "sampleCount": len(changed_paths), "totalPaths": len(baselines),
                       "targetSummary": _summary([path["targetValue"] for path in changed_paths]) if complete else None,
                       "scenarioShares": _shares(case, changed_paths) if complete else None,
                       "pairedDeltaSummary": _summary(deltas) if complete and None not in deltas else None,
                       "simulationWeight": 0.0})
    return tables


@_cancellation_boundary
def validate_hindcasts(case, snapshots, *, paths=32, periods=12, seed=0, cancel_check=None):
    """Validate supplied dated cases; never fetch or invent historical episodes.

    Publisher-vintage consistency checks arithmetic against a dated forecast or
    estimate and may reconstruct its publication-era inputs. Realized-outcome
    checks require cutoff-dated archived inputs and post-horizon observations.
    Neither type is prospective scoring or an estimator promotion gate.
    """
    from urllib.parse import urlsplit

    integer(paths, "hindcast paths", 1)
    integer(periods, "hindcast periods", 1)
    integer(seed, "hindcast seed")
    if paths > 256 or periods > 120:
        raise ValueError("hindcast diagnostic budget is at most 256 paths and 120 periods")
    current = _case_api().validate_case(case)
    cutoff = date.fromisoformat(current["asOf"])
    snapshots = _request_rows(snapshots, "hindcast_snapshots", "snapshotId")
    if len(snapshots) > 12:
        raise ValueError("hindcasts are bounded to twelve supplied snapshots")
    admitted = []
    for snapshot in snapshots:
        _cancel(cancel_check)
        if set(snapshot) - {"snapshotId", "kind", "case", "model", "comparison", "tolerance", "sourceReceipt", "evidenceKind"}:
            raise ValueError("unknown hindcast snapshot field")
        kind = snapshot.get("kind")
        if kind not in {"publisher_vintage_consistency", "realized_outcome"}:
            raise ValueError("hindcast kind must explicitly distinguish publisher vintage from realized outcome")
        if snapshot.get("evidenceKind") not in {"supplied_source", "synthetic_fixture"}:
            raise ValueError("hindcast evidenceKind must be explicit")
        if kind == "publisher_vintage_consistency":
            model_snapshot = snapshot.get("model")
            required_model = {"asOf", "horizon", "targetNodeId", "nodes", "mechanisms", "sources"}
            if "case" in snapshot or not isinstance(model_snapshot, dict) or set(model_snapshot) != required_model:
                raise ValueError("publisher vintage requires a dated model snapshot, not a fabricated archived forecast case")
            historical = {"asOf": model_snapshot["asOf"], "resolution": {
                "targetNodeId": model_snapshot["targetNodeId"], "horizon": model_snapshot["horizon"]},
                "nodes": deepcopy(model_snapshot["nodes"]), "mechanisms": deepcopy(model_snapshot["mechanisms"]),
                "sources": deepcopy(model_snapshot["sources"]), "actors": []}
            compile_model(historical)
        else:
            if "model" in snapshot:
                raise ValueError("realized outcome checks require an archived forecast case")
            historical = _case_api().validate_case(snapshot.get("case"))
        as_of = date.fromisoformat(historical["asOf"])
        horizon = date.fromisoformat(historical["resolution"]["horizon"])
        if horizon < as_of:
            raise ValueError("snapshot horizon precedes its publication-era cutoff")
        if as_of > cutoff:
            raise ValueError("snapshot cutoff is after current case cutoff")
        for node in historical["nodes"]:
            if node.get("vintage") and date.fromisoformat(node["vintage"]) > as_of:
                raise ValueError("hindcast node uses future vintage information")
        for source in historical["sources"]:
            published = source.get("publishedAt")
            if not published or date.fromisoformat(published[:10]) > as_of:
                raise ValueError("hindcast source publication is unknown or after cutoff")
            retrieval = source.get("retrievedAt")
            if not isinstance(retrieval, str) or date.fromisoformat(retrieval[:10]) > cutoff:
                raise ValueError("snapshot retrieval is missing or after evaluation cutoff")
            if date.fromisoformat(retrieval[:10]) < date.fromisoformat(published[:10]):
                raise ValueError("source retrieval precedes publication")
            if kind == "realized_outcome" and date.fromisoformat(retrieval[:10]) > as_of:
                raise ValueError("realized hindcast requires cutoff-dated archived retrieval")
        comparison = snapshot.get("comparison")
        required = {"nodeId", "value", "valueKind", "referenceDate", "publishedAt", "source"}
        if not isinstance(comparison, dict) or set(comparison) != required:
            raise ValueError("invalid dated hindcast comparison")
        if comparison["nodeId"] != historical["resolution"]["targetNodeId"]:
            raise ValueError("hindcast comparison must resolve the snapshot target")
        value = finite(comparison["value"], "hindcast comparison value")
        reference_date = date.fromisoformat(comparison["referenceDate"])
        published_date = date.fromisoformat(comparison["publishedAt"])
        if reference_date != horizon or published_date > cutoff:
            raise ValueError("comparison horizon or availability does not match the supplied case")
        if kind == "realized_outcome":
            if comparison["valueKind"] != "realized_observation" or published_date < horizon:
                raise ValueError("a publisher forecast cannot masquerade as realized outcome")
        elif comparison["valueKind"] not in {"publisher_forecast", "publisher_estimate"}:
            raise ValueError("publisher consistency requires a forecast or estimate comparison")
        elif published_date > as_of:
            raise ValueError("publisher comparison revision was unavailable at the model vintage cutoff")
        source = comparison["source"]
        if not isinstance(source, dict) or set(source) != {"sourceId", "url", "title"}:
            raise ValueError("comparison requires an explicit source identity")
        if not all(isinstance(source[key], str) and source[key].strip() for key in source):
            raise ValueError("invalid comparison source")
        url = urlsplit(source["url"])
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError("invalid comparison source URL")
        tolerance = finite(snapshot.get("tolerance", 0), "hindcast tolerance")
        if tolerance < 0:
            raise ValueError("hindcast tolerance cannot be negative")
        receipt = snapshot.get("sourceReceipt")
        if receipt is not None:
            if (not isinstance(receipt, dict) or set(receipt) != {"path", "sha256", "rowIndex"}
                    or not isinstance(receipt["path"], str) or not isinstance(receipt["sha256"], str)
                    or len(receipt["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in receipt["sha256"])):
                raise ValueError("invalid supplied source receipt")
            integer(receipt["rowIndex"], "source rowIndex")
        admitted.append((snapshot, historical, value, tolerance))
    rows = []
    for snapshot, historical, actual, tolerance in admitted:
        _cancel(cancel_check)
        # Evaluate only no-actor paths; historical actor policies and callbacks
        # cannot contaminate a publisher arithmetic consistency check.
        from .target_mechanisms import validate_model
        historical_model = compile_model(historical)
        historical_decisions = _decision_case(historical)
        terminal = []
        for index in range(paths):
            _cancel(cancel_check)
            path_seed = int(_hash({"seed": seed, "pathIndex": index})[:16], 16)
            rng = random.Random(path_seed)
            initial = historical_model.initial_values(rng)
            parameters = historical_model.draw_parameters(rng)
            terminal.append(_run_path(historical_decisions, historical_model, initial, parameters,
                                     periods, baseline=True, cancel_check=cancel_check)["targetValue"])
        summary = _summary(terminal)
        error = summary["mean"] - actual
        rows.append({"snapshotId": snapshot["snapshotId"], "kind": snapshot["kind"],
                     "evidenceKind": snapshot["evidenceKind"], "modelHash": _hash(historical),
                     "asOf": historical["asOf"], "horizon": historical["resolution"]["horizon"],
                     "comparison": deepcopy(snapshot["comparison"]), "sourceReceipt": deepcopy(snapshot.get("sourceReceipt")),
                     "targetSummary": summary, "tolerance": tolerance,
                     "absoluteError": abs(error) if math.isfinite(error) else None,
                     "withinRangeWithTolerance": summary["p05"] - tolerance <= actual <= summary["p95"] + tolerance,
                     "modelValidation": validate_model(historical),
                     "interpretation": "publisher arithmetic consistency; not realized-outcome skill" if snapshot["kind"] == "publisher_vintage_consistency" else "retrospective supplied-snapshot diagnostic; not prospective skill",
                     "evidenceVerification": "supplied dated records; authenticity not independently verified by runtime"})
    return {"schemaVersion": "target-hindcast-diagnostics/v1", "status": "measured" if rows else "unmeasured",
            "rows": rows, "prospectiveSkill": "unmeasured", "simulationWeight": 0.0,
            "realizedOutcomeChecks": sum(row["kind"] == "realized_outcome" for row in rows),
            "publisherVintageChecks": sum(row["kind"] == "publisher_vintage_consistency" for row in rows)}
