"""Versioned, dependency-free boundaries shared by all world-engine consumers.

External records use lowerCamelCase. Decimal quantities are canonical strings;
JSON floats, nonfinite numbers and duplicate normalized keys are rejected.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import unicodedata
import uuid
from typing import Any

ENGINE = "world-v1"
SPEC_SCHEMA = "simulation-world-spec/v1"
SNAPSHOT_SCHEMA = "world-snapshot/v1"
RESULT_SCHEMA = "world-result/v1"
KINDS = frozenset({"wait", "transfer", "investment", "agreement", "policy", "vote", "message", "breach"})
OPERATIONS = frozenset({"execute", "propose", "accept", "reject", "counter", "withdraw", "defer"})
DEFAULT_LIMITS = {
    "maxActors": 20, "maxIntentsPerPhase": 3, "maxAttemptsPerSlot": 2,
    "maxInboxItems": 20, "maxMessageChars": 1200, "maxEventsPerRound": 1000,
    "maxTokens": 250000, "maxCostUsd": "0", "maxOutputTokens": 1200,
    "maxConcurrentCalls": 4,
}
_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,127}$")


class WorldError(ValueError):
    """Structured boundary failure; details must not contain credentials."""

    def __init__(self, code: str, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self), "details": self.details}


def require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise WorldError(code, message)


def identifier(value: Any, field: str = "id") -> str:
    require(isinstance(value, str) and bool(_ID.fullmatch(value)), "invalid_identity", f"Invalid {field}")
    return value


def decimal(value: Any, *, nonnegative: bool = False) -> Decimal:
    require(not isinstance(value, (bool, float)) and isinstance(value, (str, int, Decimal)),
            "invalid_quantity", "Quantities must be decimal strings or integers")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError):
        raise WorldError("invalid_quantity", "Invalid decimal quantity") from None
    require(result.is_finite() and abs(result) <= Decimal("1e30"), "invalid_quantity", "Nonfinite or excessive quantity")
    require(result.as_tuple().exponent >= -12, "invalid_quantity", "Quantity precision exceeds twelve decimal places")
    require(not nonnegative or result >= 0, "negative_quantity", "Quantity cannot be negative")
    return result


def quantity(value: Any) -> str:
    result = decimal(value)
    if result == 0:
        return "0"
    text = format(result, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _canonical(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, Decimal):
        return quantity(value)
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            require(isinstance(key, str), "invalid_json", "JSON object keys must be strings")
            normalized = unicodedata.normalize("NFC", key)
            require(normalized not in result, "invalid_json", "Duplicate normalized JSON key")
            result[normalized] = _canonical(item)
        return result
    raise WorldError("invalid_json", "Unsupported JSON value; use decimal strings instead of floats")


def canonical_json(value: Any) -> str:
    return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def clone(value: Any) -> Any:
    return deepcopy(value)


def parse_time(value: Any) -> datetime:
    require(isinstance(value, str) and bool(value), "invalid_time", "A simulated time is required")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise WorldError("invalid_time", "Invalid simulated time") from None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def time_text(value: datetime | str) -> str:
    parsed = parse_time(value) if isinstance(value, str) else value.astimezone(timezone.utc)
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")


def add_days(value: str, days: Any) -> str:
    micros = decimal(days, nonnegative=True) * Decimal(86400000000)
    require(micros == micros.to_integral_value(), "invalid_time", "Duration exceeds microsecond precision")
    return time_text(parse_time(value) + timedelta(microseconds=int(micros)))


def stable_id(namespace: str, *parts: Any) -> str:
    """Stable causal identity under an opaque prepared generation, never a path."""
    return uuid.uuid5(uuid.NAMESPACE_URL, canonical_json([namespace, *parts])).hex


def visibility(value: Any, actor_ids: set[str]) -> dict:
    require(isinstance(value, dict), "invalid_visibility", "Explicit visibility is required")
    require(value.get("kind") in {"public", "actors", "analyst"}, "invalid_visibility", "Unknown visibility kind")
    result = {"kind": value["kind"]}
    if value["kind"] == "actors":
        ids = value.get("actorIds")
        require(isinstance(ids, list) and bool(ids) and all(item in actor_ids for item in ids),
                "invalid_visibility", "Visibility recipients must be admitted actors")
        result["actorIds"] = sorted(set(ids))
    return result


def visible_to(record: dict, actor_id: str | None = None, *, view: str = "public") -> bool:
    if view == "analyst":
        return True
    policy = record.get("visibility") or {"kind": "analyst"}
    return policy.get("kind") == "public" or (
        actor_id is not None and policy.get("kind") == "actors" and actor_id in policy.get("actorIds", [])
    )


def period_for(spec: dict, round_index: int) -> dict:
    require(type(round_index) is int and 1 <= round_index <= len(spec["periods"]),
            "invalid_round", "Round is outside the declared horizon")
    return spec["periods"][round_index - 1]


def actors_by_id(spec: dict) -> dict[str, dict]:
    return {actor["actorId"]: actor for actor in spec["actors"]}


def templates_by_id(spec: dict) -> dict[str, dict]:
    return {template["templateId"]: template for template in spec["actionCatalog"]}


def _basis(record: dict) -> None:
    basis = record.get("basis")
    require(isinstance(basis, dict) and basis.get("kind") in {
        "source_claim", "report_excerpt", "scenario_assumption", "simulation_event"
    }, "missing_provenance", "Every modeled value needs an explicit evidence/assumption basis")
    require(isinstance(basis.get("refs"), list) and bool(basis["refs"]),
            "missing_provenance", "A modeled value requires basis references")


def validate_spec(raw: Any) -> dict:
    require(isinstance(raw, dict), "invalid_spec", "World specification must be an object")
    spec = clone(raw)
    if "interactionQueuePolicy" in spec:
        require(spec["interactionQueuePolicy"] == "presented-v1", "unsupported_queue_policy",
                "Unknown interaction queue policy")
    require(spec.get("schemaVersion") == SPEC_SCHEMA and spec.get("engine") == ENGINE,
            "unsupported_engine", "Unsupported world specification or engine")
    identifier(spec.get("simulationId"), "simulationId")
    identifier(spec.get("generationId"), "generationId")
    require(spec.get("forecastEffect", "diagnostic_only") in {"diagnostic_only", "no_update"},
            "unsupported_policy", "World-v1 only supports safe forecast policies")
    spec.setdefault("forecastEffect", "diagnostic_only")
    require(isinstance(spec.get("actors"), list) and bool(spec["actors"]), "missing_actors", "Actor models are required")
    limits = {**DEFAULT_LIMITS, **spec.get("limits", {})}
    for key in DEFAULT_LIMITS:
        if key != "maxCostUsd":
            require(type(limits[key]) is int and 1 <= limits[key] <= 10000000,
                    "invalid_limit", f"Invalid {key}")
    require(limits["maxActors"] <= 100 and limits["maxIntentsPerPhase"] <= 10 and limits["maxAttemptsPerSlot"] <= 2,
            "invalid_limit", "World admission exceeds actor/intent/attempt safety bounds")
    limits["maxCostUsd"] = quantity(decimal(limits["maxCostUsd"], nonnegative=True))
    spec["limits"] = limits
    require(len(spec["actors"]) <= limits["maxActors"], "actor_limit", "Too many principal actors")
    actor_ids = set()
    for actor in spec["actors"]:
        require(isinstance(actor, dict), "invalid_actor", "Actor must be an object")
        aid = identifier(actor.get("actorId"), "actorId")
        require(aid not in actor_ids, "duplicate_actor", "Duplicate actor identity")
        actor_ids.add(aid)
        require(isinstance(actor.get("name"), str) and bool(actor["name"].strip()), "invalid_actor", "Actor name required")
        for key in ("objectives", "values", "incentives", "constraints", "beliefs", "capabilities"):
            require(isinstance(actor.get(key), list), "invalid_actor", f"Actor {key} must be explicit")
        require(actor.get("evidenceGrade") in {"sealed-legacy", "unsealed-v3", "scenario-assumption"},
                "invalid_actor", "Actor evidence grade is required")
        actor.setdefault("cadence", 1)
        require(type(actor["cadence"]) is int and actor["cadence"] >= 1, "invalid_actor", "Invalid decision cadence")
        actor.setdefault("respondToOffers", True)
        require(type(actor["respondToOffers"]) is bool, "invalid_actor", "Response capability must be a boolean")
        actor.setdefault("controlledAccounts", [])
        actor.setdefault("priorityRules", [])
        _basis(actor)
    periods = spec.get("periods")
    require(isinstance(periods, list) and 1 <= len(periods) <= 1000, "invalid_calendar", "A bounded calendar is required")
    previous = None
    for index, period in enumerate(periods, 1):
        require(isinstance(period, dict), "invalid_calendar", "Period must be an object")
        start, end = parse_time(period.get("start")), parse_time(period.get("end"))
        require(start < end and (previous is None or start == previous), "invalid_calendar", "Periods must be contiguous")
        require(period.get("index", index) == index, "invalid_calendar", "Periods must be ordered")
        period.update(index=index, start=time_text(start), end=time_text(end))
        previous = end
    spec["asOf"] = periods[0]["start"]
    spec["horizon"] = periods[-1]["end"]
    initial = spec.get("initialState")
    require(isinstance(initial, dict), "missing_state", "An initial concrete world is required")
    for section in ("accounts", "metrics", "rules", "relations"):
        require(isinstance(initial.get(section, {}), dict), "invalid_state", f"Invalid initial {section}")
        initial.setdefault(section, {})
        for record_id, record in initial[section].items():
            identifier(record_id)
            require(isinstance(record, dict), "invalid_state", "World records must be objects")
            record["visibility"] = visibility(record.get("visibility"), actor_ids)
            _basis(record)
            if section == "accounts":
                require(record.get("ownerId") in actor_ids or record.get("ownerId") == "external",
                        "unknown_owner", "Account owner must be admitted")
                identifier(record.get("unit"), "unit")
                record["balance"] = quantity(decimal(record.get("balance"), nonnegative=True))
                record["reserved"] = "0"
            if section == "metrics":
                require(record.get("kind") in {"stock", "rate", "quantity", "category", "boolean"},
                        "invalid_metric", "Metric kind required")
                identifier(record.get("unit"), "unit")
                if record["kind"] in {"stock", "rate", "quantity"} and record.get("value") is not None:
                    record["value"] = quantity(record["value"])
                record.setdefault("valueStatus", "specified" if record.get("value") is not None else "unknown")
    catalog = spec.get("actionCatalog")
    require(isinstance(catalog, list) and bool(catalog), "missing_actions", "An explicit action catalog is required")
    template_ids = set()
    for template in catalog:
        tid = identifier(template.get("templateId"), "templateId")
        require(tid not in template_ids and template.get("kind") in KINDS,
                "invalid_template", "Duplicate or unsupported action template")
        template_ids.add(tid)
        require(isinstance(template.get("actorIds"), list) and bool(template["actorIds"])
                and all(a in actor_ids for a in template["actorIds"]), "invalid_template", "Template actors must be admitted")
        require(isinstance(template.get("parameters"), dict), "invalid_template", "Mechanism parameters are required")
        require(isinstance(template.get("inputs", {}), dict), "invalid_template", "Action input schema must be an object")
        template.setdefault("inputs", {})
        template.setdefault("description", template["kind"])
        _basis(template)
    for actor in spec["actors"]:
        require(all(t in template_ids for t in actor["capabilities"]), "invalid_actor", "Unknown action capability")
        require(all(a in initial["accounts"] for a in actor["controlledAccounts"]), "invalid_actor", "Unknown controlled account")
    spec.setdefault("scheduledEvents", [])
    spec.setdefault("flows", [])
    spec.setdefault("assumptions", [])
    spec.setdefault("sourceBindings", {})
    spec.setdefault("seed", 0)
    require(type(spec["seed"]) is int and spec["seed"] >= 0, "invalid_seed", "Invalid simulation seed")
    require(isinstance(spec["scheduledEvents"], list) and isinstance(spec["flows"], list)
            and isinstance(spec["assumptions"], list) and isinstance(spec["sourceBindings"], dict),
            "invalid_spec", "Malformed schedules/flows/assumptions/source bindings")
    require(len(canonical_json(spec).encode()) <= 2 * 1024 * 1024, "spec_too_large", "World specification exceeds size limit")
    return spec


def initial_snapshot(spec: dict) -> dict:
    spec = validate_spec(spec)
    state = clone(spec["initialState"])
    state.update(schemaVersion=SNAPSHOT_SCHEMA, simulationId=spec["simulationId"], generationId=spec["generationId"],
                 round=0, simulatedAt=spec["asOf"], specHash=digest(spec), commitments={}, interactions={},
                 actorStates={a["actorId"]: {"beliefs": clone(a["beliefs"]), "plans": [], "priorityChanges": [],
                                             "observedEvents": [], "lastObservedEvents": [],
                                             "lastActionResults": []} for a in spec["actors"]},
                 scheduledEvents=clone(spec["scheduledEvents"]), appliedEvents=[], sampling={"seed": spec["seed"], "draws": []})
    return state


def validate_snapshot(spec: dict, snapshot: dict) -> None:
    require(snapshot.get("schemaVersion") == SNAPSHOT_SCHEMA and snapshot.get("simulationId") == spec["simulationId"]
            and snapshot.get("generationId") == spec["generationId"] and snapshot.get("specHash") == digest(spec),
            "world_identity_mismatch", "World state does not belong to prepared inputs")
    require(type(snapshot.get("round")) is int and 0 <= snapshot["round"] <= len(spec["periods"]),
            "invalid_round", "Invalid committed round")
    for account in snapshot["accounts"].values():
        balance, held = decimal(account["balance"], nonnegative=True), decimal(account["reserved"], nonnegative=True)
        require(held <= balance, "resource_violation", "Reserved resources exceed account balance")
    require(set(snapshot["actorStates"]) == set(actors_by_id(spec)), "actor_identity_mismatch", "Actor state roster changed")
    canonical_json(snapshot)


def validate_decision(spec: dict, raw: Any, actor_id: str, observation: dict, *, phase: str) -> dict:
    require(isinstance(raw, dict), "invalid_decision", "Actor response must be an object")
    require(set(raw) <= {"actorId", "observationId", "intents", "stateUpdates", "rationale", "status"},
            "invalid_decision", "Actor response contains unsupported fields")
    require(raw.get("actorId") == actor_id and raw.get("observationId") == observation["observationId"],
            "decision_identity_mismatch", "Actor response is bound to another observation")
    require(isinstance(raw.get("intents"), list) and len(raw["intents"]) <= spec["limits"]["maxIntentsPerPhase"],
            "invalid_decision", "Actor intents exceed the phase limit")
    decision = clone(raw)
    menu = {item["templateId"]: item for item in observation.get("options", [])}
    for index, intent in enumerate(decision["intents"]):
        require(isinstance(intent, dict) and set(intent) <= {
            "templateId", "operation", "parameters", "interactionId", "termsVersion", "priority", "bundleId"
        }, "invalid_intent", "Action intent contains unsupported fields")
        tid = intent.get("templateId")
        operation = intent.setdefault("operation", "execute")
        require(tid in menu and operation in menu[tid]["operations"] and operation in OPERATIONS,
                "invalid_intent", "Action is not in the actor's visible menu")
        require(isinstance(intent.get("parameters", {}), dict), "invalid_intent", "Intent parameters must be an object")
        intent.setdefault("parameters", {})
        require(type(intent.get("priority", index)) is int, "invalid_intent", "Invalid action priority")
        intent.setdefault("priority", index)
        intent["intentId"] = stable_id(spec["generationId"], observation["round"], phase, actor_id, index)
        intent["actorId"] = actor_id
        intent["phase"] = phase
    updates = decision.setdefault("stateUpdates", {})
    require(isinstance(updates, dict) and set(updates) <= {"beliefs", "plans", "priorityChanges"},
            "unauthorized_actor_update", "Stable goals/values/incentives cannot be rewritten by a decision")
    for key, value in updates.items():
        require(isinstance(value, list) and len(value) <= 20, "invalid_actor_update", f"Invalid actor update {key}")
        normalized = []
        for item in value:
            if isinstance(item, str) and key in {'beliefs', 'plans'}:
                require(len(item) <= spec['limits']['maxMessageChars'], 'invalid_actor_update',
                        'Actor reflection text exceeds its bound')
                item = {'text': item}
            require(isinstance(item, dict), 'invalid_actor_update', 'Actor update requires text or a structured object')
            require(item.get('observationId', observation['observationId']) == observation['observationId'],
                    'invalid_actor_provenance', 'Actor reflection cites another observation')
            if key == 'priorityChanges':
                rules = actors_by_id(spec)[actor_id]['priorityRules']
                rule = next((rule for rule in rules if rule['ruleId'] == item.get('ruleId')), None)
                require(rule is not None and item.get('priorityId') == rule['priorityId']
                        and item.get('value') == rule['value'], 'unauthorized_priority',
                        'Priority revision is not authorized by a declared rule')
                trigger = rule['trigger']
                record = observation['world'].get(trigger['section'], {}).get(trigger['recordId'])
                require(record is not None and record.get('value') == trigger['value'], 'unauthorized_priority',
                        'Priority trigger is not present in the actor observation')
            normalized.append(clone(item))
        updates[key] = normalized
    require(isinstance(decision.get("rationale", ""), str) and len(decision.get("rationale", "")) <= 1200,
            "invalid_decision", "Actor rationale exceeds the declared bound")
    decision.setdefault("rationale", "")
    decision.setdefault("status", "acted" if decision["intents"] else "wait")
    require(decision["status"] in {"acted", "wait", "unable"}, "invalid_decision", "Invalid actor response status")
    decision.update(round=observation["round"], phase=phase,
                    decisionId=stable_id(spec["generationId"], observation["round"], phase, actor_id))
    canonical_json(decision)
    return decision
