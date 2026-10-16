"""Pure, deterministic transitions for the declared world-v1 mechanisms.

There is no provider, clock, persistence or generated-code boundary here. All
physical laws are explicit prepared parameters. Actor failures roll back their
whole intent/bundle; malformed authoritative configuration fails the round.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, localcontext
from typing import Any

from .contracts import (
    WorldError, actors_by_id, add_days, canonical_json, clone, decimal, identifier,
    initial_snapshot, parse_time, period_for, quantity, require, stable_id,
    templates_by_id, time_text, validate_snapshot, validate_spec, visibility, visible_to,
)

_DAY_MICROS = Decimal(86400000000)
_NUMERIC = {"stock", "rate", "quantity"}
_PARAMETERS = {
    "wait": set(),
    "transfer": {"fromAccount", "toAccount", "amount"},
    "investment": {"fromAccount", "toAccount", "cost", "targetMetric", "delta",
                   "durationDays", "requiresRule", "requiredRuleValue"},
    "agreement": {"recipientIds", "transfers", "durationDays", "relationId", "relationValue",
                  "requiresRule", "requiredRuleValue", "messageDelayDays", "offerTtlDays"},
    "policy": {"ruleId", "value", "durationDays", "authorityIds"},
    "vote": {"motionId", "weights", "threshold", "fromAccount", "toAccount", "cost",
             "targetRule", "ruleValue", "mandateRule"},
    "message": {"recipientIds", "messageDelayDays", "offerTtlDays"},
    "breach": {"penaltyFromAccount", "penaltyToAccount", "penalty", "relationId", "relationValue"},
}


def _config(ok: bool, message: str) -> None:
    require(ok, "invalid_mechanism", message)


def _basis(record: dict) -> None:
    value = record.get("basis")
    _config(isinstance(value, dict) and value.get("kind") in {
        "scenario_assumption", "source_claim", "report_excerpt", "simulation_event"
    } and isinstance(value.get("refs"), list) and bool(value["refs"]), "Mechanism requires provenance")


def _policy(record: dict, actors: dict) -> dict:
    # A mechanism with no disclosure policy defaults to analyst-only, never public.
    return visibility(record.get("visibility", {"kind": "analyst"}), set(actors))


def _pair(state: dict, source: Any, target: Any) -> None:
    _config(isinstance(source, str) and isinstance(target, str)
            and source in state["accounts"] and target in state["accounts"], "Unknown transfer account")
    _config(source != target, "Transfers require distinct source and target accounts")
    _config(state["accounts"][source]["unit"] == state["accounts"][target]["unit"], "Transfer units must match")


def _metric(state: dict, key: Any) -> None:
    _config(isinstance(key, str) and key in state["metrics"] and state["metrics"][key]["kind"] in _NUMERIC,
            "Mechanism requires a declared numeric metric")
    _config(state["metrics"][key].get("value") is not None,
            "A required numeric metric must have a specified initial value before actor dispatch")


def _rule(state: dict, key: Any, *, requires_value: bool = False) -> None:
    _config(isinstance(key, str) and key in state["rules"], "Mechanism references an unknown rule")
    # False is an executable modeled condition; None is missing model input.
    # A rule-set target need not already have a value because setting it does
    # not consume the prior value, unlike a prerequisite or voting mandate.
    if requires_value:
        _config(state["rules"][key].get("value") is not None,
                "A prerequisite or mandate rule must have a specified initial value before actor dispatch")


def _duration(spec: dict, value: Any) -> None:
    add_days(spec["asOf"], value)


def _effect_config(state: dict, effect: dict) -> None:
    kind, p = effect.get("kind"), effect.get("parameters")
    _config(isinstance(p, dict), "Effect parameters must be an object")
    if kind == "transfer":
        _config(set(p) == {"fromAccount", "toAccount", "amount"}, "Invalid transfer effect")
        _pair(state, p["fromAccount"], p["toAccount"])
        decimal(p["amount"], nonnegative=True)
    elif kind == "metric_delta":
        _config(set(p) == {"targetMetric", "delta"}, "Invalid metric effect")
        _metric(state, p["targetMetric"])
        decimal(p["delta"])
    elif kind == "rule_set":
        _config(set(p) == {"ruleId", "value"}, "Invalid rule effect")
        _rule(state, p["ruleId"])
    else:
        raise WorldError("invalid_mechanism", "Unknown scheduled effect")


def validate_mechanisms(spec: dict) -> None:
    """Validate privileged configuration without consulting private feasibility.

    Call after ``validate_spec`` at preparation. Public reducer entry points also
    perform this check, including mechanisms unused by the current decisions.
    """
    state, actors = spec["initialState"], actors_by_id(spec)
    motions = {}
    for template in spec["actionCatalog"]:
        kind, p, inputs = template["kind"], template["parameters"], template["inputs"]
        _config(kind in _PARAMETERS and set(p) <= _PARAMETERS[kind], "Unknown mechanism parameters")
        _policy(template, actors)
        for name, field in inputs.items():
            identifier(name, "input")
            _config(isinstance(field, dict) and set(field) <= {"type", "min", "max", "enum", "required"},
                    "Invalid action input schema")
            _config(field.get("type") in {"decimal", "integer", "string", "boolean", "actor"},
                    "Unknown input type")
            _config(type(field.get("required", False)) is bool, "Input required must be boolean")
            if "enum" in field:
                _config(isinstance(field["enum"], list) and bool(field["enum"]), "Invalid input enumeration")
            if "min" in field or "max" in field:
                _config(field["type"] in {"decimal", "integer", "string"}, "Unsupported input bound")
                lower, upper = field.get("min"), field.get("max")
                if lower is not None:
                    decimal(lower)
                if upper is not None:
                    decimal(upper)
                _config(lower is None or upper is None or decimal(lower) <= decimal(upper), "Inverted input bounds")
        for key in ("durationDays", "messageDelayDays", "offerTtlDays"):
            if key in p:
                _duration(spec, p[key])
        if "offerTtlDays" in p:
            _config(decimal(p["offerTtlDays"]) > 0, "Offer lifetime must be positive")
        if "requiresRule" in p:
            _rule(state, p["requiresRule"], requires_value=True)
        _config("requiredRuleValue" not in p or "requiresRule" in p, "Rule value requires a rule")
        if "relationId" in p:
            _config(p["relationId"] in state["relations"] and "relationValue" in p, "Invalid relation effect")
        _config("relationValue" not in p or "relationId" in p, "Relation value requires a relation")
        if kind in {"transfer", "investment", "vote"}:
            _pair(state, p.get("fromAccount"), p.get("toAccount"))
        if kind == "transfer":
            _config("amount" in p or inputs.get("amount", {}).get("type") == "decimal", "Transfer amount required")
            if "amount" in p:
                decimal(p["amount"], nonnegative=True)
        elif kind == "investment":
            for key in ("cost", "targetMetric", "delta", "durationDays"):
                _config(key in p, "Incomplete investment mechanism")
            _config(state["accounts"][p["toAccount"]]["ownerId"] == "external", "Investment requires named external sink")
            decimal(p["cost"], nonnegative=True)
            decimal(p["delta"])
            _metric(state, p["targetMetric"])
        elif kind == "agreement":
            recipients = p.get("recipientIds")
            _config(isinstance(recipients, list) and bool(recipients)
                    and all(isinstance(a, str) and a in actors for a in recipients)
                    and len(set(recipients)) == len(recipients), "Agreement recipients must be admitted")
            _config(isinstance(p.get("transfers", []), list), "Agreement transfers must be a list")
            for transfer in p.get("transfers", []):
                _config(isinstance(transfer, dict) and set(transfer) == {"fromAccount", "toAccount", "amount"},
                        "Invalid agreement transfer")
                _pair(state, transfer["fromAccount"], transfer["toAccount"])
                amount = transfer["amount"]
                if isinstance(amount, str) and amount.startswith("$"):
                    field = inputs.get(amount[1:], {})
                    _config(field.get("type") == "decimal" and field.get("required") is True,
                            "Agreement amount must reference a required decimal input")
                else:
                    decimal(amount, nonnegative=True)
        elif kind == "policy":
            _rule(state, p.get("ruleId"))
            _config("value" in p and "durationDays" in p, "Incomplete policy mechanism")
            ids = p.get("authorityIds")
            _config(isinstance(ids, list) and bool(ids) and all(isinstance(a, str) and a in actors for a in ids),
                    "Policy authority must be explicit and nonempty")
        elif kind == "vote":
            identifier(p.get("motionId"), "motionId")
            _config("cost" in p and "threshold" in p, "Incomplete voting mechanism")
            decimal(p["cost"], nonnegative=True)
            _config(decimal(p["threshold"]) > 0, "Vote threshold must be positive")
            weights = p.get("weights")
            _config(isinstance(weights, dict) and bool(weights) and all(a in actors for a in weights), "Invalid vote entitlements")
            for weight in weights.values():
                decimal(weight, nonnegative=True)
            _config(inputs.get("support", {}).get("type") == "boolean", "Voting requires boolean support input")
            for key in ("targetRule", "mandateRule"):
                if key in p:
                    _rule(state, p[key], requires_value=key == "mandateRule")
            _config(("targetRule" in p) == ("ruleValue" in p), "Vote effect must specify its rule and value")
            signature = canonical_json(p)
            _config(p["motionId"] not in motions or motions[p["motionId"]] == signature, "Conflicting motion definitions")
            motions[p["motionId"]] = signature
        elif kind == "message":
            _config(inputs.get("text", {}).get("type") == "string", "Messages require a text input")
            _config(isinstance(p.get("recipientIds", []), list)
                    and all(isinstance(a, str) and a in actors for a in p.get("recipientIds", [])),
                    "Invalid message recipients")
        elif kind == "breach":
            _pair(state, p.get("penaltyFromAccount"), p.get("penaltyToAccount"))
            _config("penalty" in p, "Breach requires an explicit penalty")
            decimal(p["penalty"], nonnegative=True)
            _config(inputs.get("commitmentId", {}).get("type") == "string", "Breach requires commitment identity input")
    seen = set()
    for event in spec["scheduledEvents"]:
        _config(isinstance(event, dict), "Scheduled event must be an object")
        eid = identifier(event.get("eventId"), "eventId")
        _config(eid not in seen, "Duplicate scheduled event identity")
        seen.add(eid)
        _config(parse_time(event.get("at")) >= parse_time(spec["asOf"]), "Overdue initial scheduled event")
        _effect_config(state, event)
        visibility(event.get("visibility"), set(actors))
        _basis(event)
    seen.clear()
    flow_sources, flow_targets = set(), set()
    for flow in spec["flows"]:
        _config(isinstance(flow, dict) and set(flow) <= {"flowId", "sourceAccount", "targetAccount", "ratePerDay",
                                                      "rateMetric", "limitMetric", "visibility", "basis"}, "Invalid flow")
        fid = identifier(flow.get("flowId"), "flowId")
        _config(fid not in seen, "Duplicate flow identity")
        seen.add(fid)
        _pair(state, flow.get("sourceAccount"), flow.get("targetAccount"))
        _config(flow["sourceAccount"] not in flow_sources, "Competing flows require an explicit allocation mechanism")
        flow_sources.add(flow["sourceAccount"])
        flow_targets.add(flow["targetAccount"])
        _config(("ratePerDay" in flow) != ("rateMetric" in flow), "Flow needs exactly one explicit rate")
        if "ratePerDay" in flow:
            decimal(flow["ratePerDay"], nonnegative=True)
        for key in ("rateMetric", "limitMetric"):
            if key in flow:
                _metric(state, flow[key])
                _config(state["metrics"][flow[key]]["kind"] == "rate", "Flow metric must be a rate per day")
                unit = state["accounts"][flow["sourceAccount"]]["unit"]
                _config(state["metrics"][flow[key]]["unit"] == unit + "_per_day",
                        "Flow rate and account units must match")
        visibility(flow.get("visibility"), set(actors))
        _basis(flow)
    _config(not flow_sources.intersection(flow_targets), "Coupled flows require an explicit process mechanism")
    for actor in actors.values():
        seen.clear()
        for rule in actor["priorityRules"]:
            _config(isinstance(rule, dict) and set(rule) <= {"ruleId", "trigger", "priorityId", "value", "basis"},
                    "Invalid priority revision rule")
            rid = identifier(rule.get("ruleId"), "priority rule")
            _config(rid not in seen, "Duplicate priority revision rule")
            seen.add(rid)
            identifier(rule.get("priorityId"), "priorityId")
            _config("value" in rule, "Priority revision requires a fixed value")
            trigger = rule.get("trigger")
            _config(isinstance(trigger, dict) and set(trigger) == {"section", "recordId", "value"}, "Invalid priority trigger")
            section = trigger["section"]
            _config(isinstance(section, str) and section in {"metrics", "rules", "relations"}
                    and isinstance(trigger["recordId"], str) and trigger["recordId"] in state[section],
                    "Priority trigger references an unknown record")
            _basis(rule)
    _validate_flow_precision(spec)


def _validate_flow_precision(spec: dict) -> None:
    """Reject unrepresentable flow grids before dispatch, without inventing rounding.

    All possible decision, completion and expiry instants are prepared constants.
    Checking each primitive metric increment also covers any sum of accepted
    investments and shocks, including either side of a minimum rate/limit.
    """
    if not spec["flows"]:
        return
    opening, horizon = parse_time(spec["asOf"]), parse_time(spec["horizon"])
    boundaries = {opening, horizon}
    for period in spec["periods"]:
        boundaries.update((parse_time(period["start"]), parse_time(period["end"])))
        for template in spec["actionCatalog"]:
            p = template["parameters"]
            offsets = [p["durationDays"]] if "durationDays" in p else []
            if template["kind"] == "agreement":
                offsets.append(p.get("offerTtlDays", "30"))
            for offset in offsets:
                at = parse_time(add_days(period["start"], offset))
                if opening < at < horizon:
                    boundaries.add(at)
    boundaries.update(parse_time(event["at"]) for event in spec["scheduledEvents"]
                      if opening <= parse_time(event["at"]) <= horizon)
    points = sorted(boundaries)
    intervals = set()
    for left, right in zip(points, points[1:]):
        delta = right - left
        intervals.add(Decimal((delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds))
    for flow in spec["flows"]:
        metrics = {flow[key] for key in ("rateMetric", "limitMetric") if key in flow}
        rates = [decimal(flow["ratePerDay"])] if "ratePerDay" in flow else []
        for key in metrics:
            value = spec["initialState"]["metrics"][key].get("value")
            _config(value is not None, "Flow rate must be specified before actor dispatch")
            rates.append(decimal(value, nonnegative=True))
        for template in spec["actionCatalog"]:
            p = template["parameters"]
            if template["kind"] == "investment" and p["targetMetric"] in metrics:
                rates.append(decimal(p["delta"]))
        for event in spec["scheduledEvents"]:
            p = event["parameters"]
            if event["kind"] == "metric_delta" and p["targetMetric"] in metrics:
                rates.append(decimal(p["delta"]))
        with localcontext() as ctx:
            ctx.prec = 80
            for rate in rates:
                for micros in intervals:
                    amount = rate * micros / _DAY_MICROS
                    require(amount == amount.quantize(Decimal("0.000000000001")), "invalid_flow_precision",
                            "Flow rates and chronological boundaries exceed exact twelve-place accounting")


def _input_values(template: dict, intent: dict, actors: dict | None, max_chars: int) -> dict:
    """Validate declared inputs; None omits only private roster membership."""
    supplied, schema = intent.get("parameters", {}), template["inputs"]
    require(isinstance(supplied, dict) and set(supplied) <= set(schema), "invalid_input", "Unsupported action input")
    # Empty consent/reject/defer/withdraw has no new offer inputs.
    if intent["operation"] in {"accept", "reject", "defer", "withdraw"}:
        require(not supplied, "invalid_input", "Responses must reference exact terms without replacing them")
        return {}
    result = clone(supplied)
    for name, field in schema.items():
        require(not field.get("required", False) or name in supplied, "invalid_input", "Required action input is missing")
        if name not in supplied:
            continue
        value, kind = supplied[name], field["type"]
        if kind == "decimal":
            measure = decimal(value)
            result[name] = quantity(measure)
        elif kind == "integer":
            require(type(value) is int, "invalid_input", "Integer input required")
            measure = decimal(value)
        elif kind == "boolean":
            require(type(value) is bool, "invalid_input", "Boolean input required")
            measure = None
        else:
            require(isinstance(value, str), "invalid_input", "String input required")
            require(len(value) <= max_chars, "invalid_input", "Action text exceeds declared limit")
            require(kind != "actor" or actors is None or value in actors, "invalid_input", "Unknown actor input")
            measure = Decimal(len(value))
        if measure is not None:
            require("min" not in field or measure >= decimal(field["min"]), "invalid_input", "Input below declared minimum")
            require("max" not in field or measure <= decimal(field["max"]), "invalid_input", "Input above declared maximum")
        if "enum" in field:
            choices = [quantity(x) for x in field["enum"]] if kind == "decimal" else field["enum"]
            require(result[name] in choices, "invalid_input", "Input is outside the declared choices")
    return result


def _available(state: dict, account: str) -> Decimal:
    record = state["accounts"][account]
    return decimal(record["balance"]) - decimal(record["reserved"])


def _transfer(state: dict, transfers: list[dict], *, reserve: bool = False, release: bool = False) -> None:
    """Aggregate gross debits first: cycles never manufacture spendable funds."""
    debits = defaultdict(Decimal)
    for transfer in transfers:
        _pair(state, transfer["fromAccount"], transfer["toAccount"])
        debits[transfer["fromAccount"]] += decimal(transfer["amount"], nonnegative=True)
    for account, amount in debits.items():
        require(amount <= (decimal(state["accounts"][account]["reserved"]) if release else _available(state, account)),
                "insufficient_resources", "Action cannot be funded under the declared resource constraints")
    for account, amount in debits.items():
        record = state["accounts"][account]
        if reserve or release:
            record["reserved"] = quantity(decimal(record["reserved"]) + (amount if reserve else -amount))
    if not reserve:
        for transfer in transfers:
            source, target, amount = transfer["fromAccount"], transfer["toAccount"], decimal(transfer["amount"])
            state["accounts"][source]["balance"] = quantity(decimal(state["accounts"][source]["balance"]) - amount)
            state["accounts"][target]["balance"] = quantity(decimal(state["accounts"][target]["balance"]) + amount)


def _controls(spec: dict, state: dict, actor_id: str, account: str) -> None:
    actor = actors_by_id(spec)[actor_id]
    require(state["accounts"][account]["ownerId"] == actor_id or account in actor["controlledAccounts"],
            "unauthorized_resource", "Actor does not control the declared source account")
    # A motion treasury can only be spent through its prepared voting mechanism.
    protected = {t["parameters"]["fromAccount"] for t in spec["actionCatalog"] if t["kind"] == "vote"}
    require(account not in protected, "institutional_resource", "Institutional funds require the declared motion")


def _prerequisite(state: dict, p: dict) -> None:
    if "requiresRule" in p:
        require(state["rules"][p["requiresRule"]].get("value") == p.get("requiredRuleValue", True),
                "rule_ineligible", "Action does not satisfy the declared rule prerequisite")


def _event(spec: dict, state: dict, events: list, kind: str, at: str, record: dict,
           identity: str, *, actor_id: str | None = None, intent_id: str | None = None,
           details: dict | None = None) -> dict:
    eid = stable_id(spec["generationId"], identity, kind)
    require(eid not in state["appliedEvents"], "duplicate_effect", "An effect cannot be applied twice")
    item = {"eventId": eid, "round": state["round"], "at": time_text(at), "kind": kind,
            "visibility": _policy(record, actors_by_id(spec)), "basis": clone(record["basis"]),
            "description": kind.replace("_", " ").capitalize(), "details": clone(details or {})}
    if actor_id is not None:
        item["actorId"] = actor_id
    if intent_id is not None:
        item["sourceIntentId"] = intent_id
    events.append(item)
    state["appliedEvents"].append(eid)
    require(len(events) <= spec["limits"]["maxEventsPerRound"], "event_limit", "Round exceeds declared event limit")
    return item


def _effect(state: dict, effect: dict) -> None:
    p, kind = effect["parameters"], effect["kind"]
    if kind == "transfer":
        _transfer(state, [p])
    elif kind == "rule_set":
        state["rules"][p["ruleId"]]["value"] = clone(p["value"])
    elif kind == "metric_delta":
        metric = state["metrics"][p["targetMetric"]]
        require(metric.get("value") is not None, "unknown_quantity", "An unknown metric cannot be incremented")
        value = decimal(metric["value"]) + decimal(p["delta"])
        require(metric["kind"] not in {"stock", "rate"} or value >= 0, "negative_quantity", "A stock or rate cannot become negative")
        metric["value"] = quantity(value)
    else:
        raise WorldError("invalid_mechanism", "Unknown committed effect")


def _commitment(spec: dict, state: dict, template: dict, intent: dict, now: str, *,
                effects: list, transfers: list | None = None, participants: list | None = None,
                identity: str | None = None) -> dict:
    cid = stable_id(spec["generationId"], identity or intent["intentId"], "commitment")
    require(cid not in state["commitments"], "duplicate_intent", "Intent already has an obligation")
    item = {"commitmentId": cid, "templateId": template["templateId"], "kind": template["kind"],
            "actorId": intent["actorId"], "sourceIntentId": intent["intentId"], "createdAt": now,
            "dueAt": add_days(now, template["parameters"].get("durationDays", "0")), "status": "pending",
            "participantIds": sorted(set(participants or [intent["actorId"]])), "effects": clone(effects),
            "transfers": clone(transfers or []), "visibility": _policy(template, actors_by_id(spec)),
            "basis": clone(template["basis"])}
    state["commitments"][cid] = item
    return item


def _settle(spec: dict, state: dict, events: list, item: dict) -> None:
    if item["transfers"]:
        _transfer(state, item["transfers"], release=True)
    for effect in item["effects"]:
        _effect(state, effect)
    p = templates_by_id(spec)[item["templateId"]]["parameters"]
    if "relationId" in p:
        state["relations"][p["relationId"]]["value"] = clone(p["relationValue"])
    item["status"] = "settled"
    _event(spec, state, events, "commitment_settled", item["dueAt"], item, item["commitmentId"],
           actor_id=item["actorId"], intent_id=item["sourceIntentId"], details={"commitmentId": item["commitmentId"]})


def _obligations(spec: dict, state: dict, template: dict, terms: dict, participants: list) -> dict:
    """Participant-visible consequences of consent, never private feasibility."""
    p = template["parameters"]
    transfers = []
    for transfer in p.get("transfers", []):
        source, target = state["accounts"][transfer["fromAccount"]], state["accounts"][transfer["toAccount"]]
        require(source["ownerId"] in participants, "unauthorized_resource", "Agreement cannot bind an unconsenting account owner")
        amount = transfer["amount"]
        if isinstance(amount, str) and amount.startswith("$"):
            amount = terms[amount[1:]]
        transfers.append({"fromAccount": transfer["fromAccount"], "toAccount": transfer["toAccount"],
                          "fromActorId": source["ownerId"], "toActorId": target["ownerId"], "unit": source["unit"],
                          "amount": quantity(decimal(amount, nonnegative=True))})
    result = {"transfers": transfers, "durationDays": quantity(p.get("durationDays", "0"))}
    if "relationId" in p:
        result.update(relationId=p["relationId"], relationValue=clone(p["relationValue"]))
    if "requiresRule" in p:
        result["condition"] = {"ruleId": p["requiresRule"], "requiredValue": clone(p.get("requiredRuleValue", True))}
    return result


def _offer(spec: dict, state: dict, template: dict, intent: dict, now: str, terms: dict,
           recipients: list, *, version: int = 1) -> dict:
    oid = stable_id(spec["generationId"], intent["intentId"], "offer")
    require(oid not in state["interactions"], "duplicate_intent", "Offer identity already exists")
    recipients = sorted(set(recipients) - {intent["actorId"]})
    require(bool(recipients), "invalid_recipient", "Offer requires a distinct recipient")
    p = template["parameters"]
    policy = _policy(template, actors_by_id(spec))
    if policy["kind"] != "public":
        policy = {"kind": "actors", "actorIds": sorted(set(recipients + [intent["actorId"]]))}
    item = {"interactionId": oid, "templateId": template["templateId"], "proposerId": intent["actorId"],
            "recipientIds": recipients, "terms": clone(terms), "termsVersion": version, "createdAt": now,
            "deliverAt": add_days(now, p.get("messageDelayDays", "0")),
            "expiresAt": add_days(now, p.get("offerTtlDays", "30")), "status": "pending",
            "visibility": policy, "basis": clone(template["basis"]), "lastResponseRound": 0, "acceptedBy": [],
            "createdRound": state["round"], "createdPhase": intent["phase"]}
    if template["kind"] == "agreement":
        item["obligations"] = _obligations(spec, state, template, terms, [intent["actorId"], *recipients])
    state["interactions"][oid] = item
    return item


def _response(spec: dict, state: dict, events: list, template: dict, intent: dict, now: str, values: dict) -> str:
    oid = intent.get("interactionId")
    require(isinstance(oid, str), "invalid_input", "Response requires an offer identity")
    item = state["interactions"].get(oid)
    require(item is not None and item["templateId"] == template["templateId"] and visible_to(item, intent["actorId"]),
            "unavailable_offer", "Offer is unavailable to this actor")
    require(item["status"] == "pending" and parse_time(now) < parse_time(item["expiresAt"]),
            "closed_offer", "Offer is no longer pending")
    require(type(intent.get("termsVersion")) is int and intent["termsVersion"] == item["termsVersion"],
            "stale_terms", "Response must identify the exact terms version")
    op, aid = intent["operation"], intent["actorId"]
    commitment = None
    if op == "withdraw":
        require(aid == item["proposerId"], "unauthorized_response", "Only the proposer may withdraw")
        item["status"] = "withdrawn"
    else:
        require(intent["phase"] == "response" and aid in item["recipientIds"],
                "unauthorized_response", "Only an eligible recipient may respond")
        require(actors_by_id(spec)[aid]["respondToOffers"], "unauthorized_response", "Actor cannot respond to offers")
        require(parse_time(item["deliverAt"]) <= parse_time(now)
                and not (item.get("createdRound") == state["round"] and item.get("createdPhase") == "response"),
                "undelivered_offer", "Offer is not eligible in this response phase")
        require(aid not in item["acceptedBy"], "duplicate_response", "Actor already consented to these terms")
        item["lastResponseRound"] = state["round"]
        if op == "reject":
            item["status"] = "rejected"
        elif op == "counter":
            counter = _offer(spec, state, template, intent, now, values, [item["proposerId"]], version=item["termsVersion"] + 1)
            item["status"] = "superseded"
            item["supersededBy"] = counter["interactionId"]
        elif op == "accept":
            _prerequisite(state, template["parameters"])
            item["acceptedBy"] = sorted(item["acceptedBy"] + [aid])
            if set(item["acceptedBy"]) == set(item["recipientIds"]):
                participants = [item["proposerId"], *item["recipientIds"]]
                obligations = _obligations(spec, state, template, item["terms"], participants)
                require(item.get("obligations") == obligations, "stale_terms", "Operative obligations differ from the offered terms")
                transfers = [{key: transfer[key] for key in ("fromAccount", "toAccount", "amount")}
                             for transfer in obligations["transfers"]]
                for transfer in transfers:
                    require(state["accounts"][transfer["fromAccount"]]["ownerId"] in participants,
                            "unauthorized_resource", "Agreement cannot bind an unconsenting account owner")
                    # Institutional envelopes are not available through private agreements.
                    _controls(spec, state, state["accounts"][transfer["fromAccount"]]["ownerId"], transfer["fromAccount"])
                    if isinstance(transfer["amount"], str) and transfer["amount"].startswith("$"):
                        transfer["amount"] = item["terms"][transfer["amount"][1:]]
                    transfer["amount"] = quantity(decimal(transfer["amount"], nonnegative=True))
                _transfer(state, transfers, reserve=True)
                obligated = sorted({state["accounts"][t["fromAccount"]]["ownerId"] for t in transfers}) or participants
                commitment = _commitment(spec, state, template, intent, now, effects=[], transfers=transfers,
                                         participants=obligated, identity=item["interactionId"])
                commitment["interactionId"] = item["interactionId"]
                item.update(status="accepted", commitmentId=commitment["commitmentId"])
        elif op != "defer":
            raise WorldError("invalid_operation", "Unsupported agreement response")
    _event(spec, state, events, "offer_" + op, now, item, intent["intentId"], actor_id=aid,
           intent_id=intent["intentId"], details={"interactionId": item["interactionId"], "termsVersion": item["termsVersion"]})
    if commitment is not None and parse_time(commitment["dueAt"]) == parse_time(now):
        _settle(spec, state, events, commitment)
    return "consent_recorded" if op == "accept" and item["status"] == "pending" else "accepted"


def _apply(spec: dict, state: dict, events: list, intent: dict, now: str) -> str:
    actors, templates = actors_by_id(spec), templates_by_id(spec)
    aid, tid, op = intent["actorId"], intent["templateId"], intent["operation"]
    require(aid in actors, "unknown_actor", "Actor is not admitted")
    require(tid in templates, "unknown_template", "Action template is not admitted")
    template = templates[tid]
    kind, p = template["kind"], template["parameters"]
    values = _input_values(template, intent, actors, spec["limits"]["maxMessageChars"])
    if kind == "agreement" and op in {"accept", "reject", "counter", "defer", "withdraw"}:
        return _response(spec, state, events, template, intent, now, values)
    require(aid in template["actorIds"] and tid in actors[aid]["capabilities"],
            "unauthorized_action", "Actor is not entitled to initiate this mechanism")
    require(intent["phase"] == "proposal", "invalid_phase", "Only offer responses are allowed in the response phase")
    require(op == ("propose" if kind == "agreement" else "execute"), "invalid_operation", "Unsupported action operation")
    # Communication is conditional. Hidden rule/resource feasibility cannot alter
    # staging, the response roster, or the terms a recipient is asked to consider.
    if kind != "agreement":
        _prerequisite(state, p)
    commitment = None
    passed_motion = None
    details = {}
    event_record = template
    if kind == "wait":
        pass
    elif kind == "transfer":
        _controls(spec, state, aid, p["fromAccount"])
        amount = p.get("amount", values.get("amount"))
        require(amount is not None, "invalid_input", "Transfer amount is required")
        _transfer(state, [{"fromAccount": p["fromAccount"], "toAccount": p["toAccount"], "amount": amount}])
    elif kind == "investment":
        _controls(spec, state, aid, p["fromAccount"])
        require(state["metrics"][p["targetMetric"]].get("value") is not None,
                "unknown_quantity", "Investment requires a specified target metric")
        _transfer(state, [{"fromAccount": p["fromAccount"], "toAccount": p["toAccount"], "amount": p["cost"]}])
        commitment = _commitment(spec, state, template, intent, now,
                                 effects=[{"kind": "metric_delta", "parameters": {"targetMetric": p["targetMetric"], "delta": p["delta"]}}])
    elif kind == "policy":
        require(aid in p["authorityIds"], "unauthorized_policy", "Actor lacks the declared policy authority")
        commitment = _commitment(spec, state, template, intent, now,
                                 effects=[{"kind": "rule_set", "parameters": {"ruleId": p["ruleId"], "value": p["value"]}}])
    elif kind == "agreement":
        item = _offer(spec, state, template, intent, now, values, p["recipientIds"])
        details = {"interactionId": item["interactionId"], "termsVersion": item["termsVersion"]}
        event_record = item
    elif kind == "message":
        require("text" in values, "invalid_input", "Message text is required")
        item = _offer(spec, state, template, intent, now, values,
                      p.get("recipientIds") or sorted(set(actors) - {aid}))
        # Messages persist and become visible at delivery, but do not request consent.
        item.update(status="accepted", kind="message")
        details = {"interactionId": item["interactionId"]}
        event_record = item
    elif kind == "vote":
        require(aid in p["weights"] and decimal(p["weights"][aid]) > 0,
                "unauthorized_vote", "Actor has no voting entitlement")
        require(type(values.get("support")) is bool, "invalid_input", "A vote must explicitly state support")
        if "mandateRule" in p:
            require(state["rules"][p["mandateRule"]].get("value") is True, "invalid_mandate", "The voting mandate is not valid")
        cid = stable_id(spec["generationId"], p["motionId"], "motion")
        motion = state["commitments"].get(cid)
        if motion is None:
            motion = {"commitmentId": cid, "templateId": tid, "kind": "vote", "status": "voting", "votes": {},
                      "createdAt": now, "actorId": aid, "sourceIntentId": intent["intentId"], "participantIds": [],
                      "transfers": [], "effects": [], "visibility": _policy(template, actors), "basis": clone(template["basis"])}
            state["commitments"][cid] = motion
        require(motion["status"] == "voting", "motion_closed", "The motion has already executed")
        motion["votes"][aid] = values["support"]
        support = sum((decimal(p["weights"][voter]) for voter, yes in motion["votes"].items() if yes), Decimal(0))
        if support >= decimal(p["threshold"]):
            _transfer(state, [{"fromAccount": p["fromAccount"], "toAccount": p["toAccount"], "amount": p["cost"]}])
            if "targetRule" in p:
                state["rules"][p["targetRule"]]["value"] = clone(p["ruleValue"])
            motion.update(status="settled", dueAt=now, participantIds=sorted(motion["votes"]))
            passed_motion = cid
        details = {"commitmentId": cid}
    elif kind == "breach":
        require(isinstance(values.get("commitmentId"), str), "invalid_input", "Breach requires commitment identity")
        target = state["commitments"].get(values.get("commitmentId"))
        require(target is not None and target["status"] == "pending" and aid in target["participantIds"],
                "unavailable_obligation", "Actor has no pending obligation eligible for breach")
        _controls(spec, state, aid, p["penaltyFromAccount"])
        for transfer in target["transfers"]:
            record = state["accounts"][transfer["fromAccount"]]
            record["reserved"] = quantity(decimal(record["reserved"]) - decimal(transfer["amount"]))
        _transfer(state, [{"fromAccount": p["penaltyFromAccount"], "toAccount": p["penaltyToAccount"], "amount": p["penalty"]}])
        target["status"] = "breached"
        if "relationId" in p:
            state["relations"][p["relationId"]]["value"] = clone(p["relationValue"])
        details = {"commitmentId": target["commitmentId"]}
    else:
        raise WorldError("invalid_mechanism", "Unknown action mechanism")
    if commitment is not None:
        details = {"commitmentId": commitment["commitmentId"]}
    _event(spec, state, events, kind + "_accepted", now, event_record, intent["intentId"],
           actor_id=aid, intent_id=intent["intentId"], details=details)
    if passed_motion is not None:
        _event(spec, state, events, "motion_passed", now, template, passed_motion,
               details={"commitmentId": passed_motion, "motionId": p["motionId"]})
    if commitment is not None and parse_time(commitment["dueAt"]) == parse_time(now):
        _settle(spec, state, events, commitment)
    return "accepted"


def _flows(spec: dict, state: dict, events: list, start: str, end: str) -> None:
    delta = parse_time(end) - parse_time(start)
    micros = Decimal((delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds)
    if not micros:
        return
    for flow in sorted(spec["flows"], key=lambda f: f["flowId"]):
        def rate_metric(key):
            value = state["metrics"][flow[key]].get("value")
            require(value is not None, "unknown_quantity", "Flow requires a specified rate")
            return decimal(value, nonnegative=True)
        rate = rate_metric("rateMetric") if "rateMetric" in flow else decimal(flow["ratePerDay"], nonnegative=True)
        if "limitMetric" in flow:
            rate = min(rate, rate_metric("limitMetric"))
        amount = min(_available(state, flow["sourceAccount"]), rate * micros / _DAY_MICROS)
        # No implicit rounding: the admitted decimal precision must represent the interval.
        amount_text = quantity(amount.normalize())
        _transfer(state, [{"fromAccount": flow["sourceAccount"], "toAccount": flow["targetAccount"], "amount": amount_text}])
        _event(spec, state, events, "flow_transfer", end, flow, stable_id(spec["generationId"], flow["flowId"], start, end),
               details={"flowId": flow["flowId"], "start": start, "end": end, "amount": amount_text,
                        "fromAccount": flow["sourceAccount"], "toAccount": flow["targetAccount"]})


def _advance(spec: dict, state: dict, events: list, start: str, end: str, *, initial: bool = False) -> None:
    boundaries = defaultdict(list)
    for event in state["scheduledEvents"]:
        eid = stable_id(spec["generationId"], event["eventId"], "scheduled_" + event["kind"])
        if eid in state["appliedEvents"]:
            continue
        at = time_text(event["at"])
        require(parse_time(at) >= parse_time(start) and (initial or parse_time(at) > parse_time(start)),
                "overdue_event", "Opening effects must be settled before actor observations")
        if parse_time(at) <= parse_time(end):
            boundaries[at].append((event["eventId"], "scheduled", event))
    for item in state["commitments"].values():
        if item["status"] != "pending":
            continue
        at = time_text(item["dueAt"])
        require(parse_time(at) >= parse_time(start), "overdue_event", "Pending commitment is overdue")
        if parse_time(at) <= parse_time(end):
            boundaries[at].append((stable_id(spec["generationId"], item["commitmentId"], "commitment_settled"), "commitment", item))
    for item in state["interactions"].values():
        if item["status"] == "pending" and parse_time(item["expiresAt"]) <= parse_time(end):
            at = max(time_text(item["expiresAt"]), start)
            boundaries[at].append((stable_id(spec["generationId"], item["interactionId"], "offer_expired"), "expiry", item))
    cursor = start
    for at in sorted(boundaries):
        _flows(spec, state, events, cursor, at)
        for _, kind, item in sorted(boundaries[at], key=lambda entry: entry[0]):
            if kind == "scheduled":
                _effect(state, item)
                _event(spec, state, events, "scheduled_" + item["kind"], at, item, item["eventId"])
            elif kind == "commitment":
                _settle(spec, state, events, item)
            else:
                item["status"] = "expired"
                _event(spec, state, events, "offer_expired", at, item, item["interactionId"],
                       details={"interactionId": item["interactionId"]})
        cursor = at
    _flows(spec, state, events, cursor, end)
    state["simulatedAt"] = end


def _state_check(spec: dict, state: dict) -> None:
    validate_snapshot(spec, state)
    for section in ("accounts", "metrics", "rules", "relations"):
        require(set(state[section]) == set(spec["initialState"][section]), "invalid_state", "World record roster changed")
    held = defaultdict(Decimal)
    for item in state["commitments"].values():
        require(item["templateId"] in templates_by_id(spec), "invalid_state", "Unknown commitment mechanism")
        if item["status"] == "pending":
            for transfer in item["transfers"]:
                held[transfer["fromAccount"]] += decimal(transfer["amount"], nonnegative=True)
    for aid, record in state["accounts"].items():
        initial = spec["initialState"]["accounts"][aid]
        require(record["ownerId"] == initial["ownerId"] and record["unit"] == initial["unit"],
                "invalid_state", "Account ownership or unit changed")
        require(decimal(record["reserved"]) == held[aid], "resource_violation", "Resource holds do not match pending commitments")
    for record in state["metrics"].values():
        if record["kind"] in _NUMERIC and record.get("value") is not None:
            decimal(record["value"], nonnegative=record["kind"] in {"stock", "rate"})
    require(len(state["appliedEvents"]) == len(set(state["appliedEvents"])), "duplicate_effect", "Duplicate applied event identity")


def _prepare(spec: dict, snapshot: dict, round_index: int) -> tuple[dict, dict, dict]:
    spec = validate_spec(spec)
    validate_mechanisms(spec)
    _state_check(spec, snapshot)
    period = period_for(spec, round_index)
    require(snapshot["round"] == round_index - 1 and parse_time(snapshot["simulatedAt"]) == parse_time(period["start"]),
            "invalid_round", "Round must advance exactly one committed period")
    state = clone(snapshot)
    state.pop("revision", None)
    # An unsettled opening event is a preparation failure, never a silent late effect.
    for event in state["scheduledEvents"]:
        eid = stable_id(spec["generationId"], event["eventId"], "scheduled_" + event["kind"])
        require(eid in state["appliedEvents"] or parse_time(event["at"]) > parse_time(period["start"]),
                "overdue_event", "Initialize opening effects before the first observation")
    return spec, state, period


def _decisions(spec: dict, decisions: list, round_index: int) -> list:
    require(isinstance(decisions, list), "invalid_decision", "Decisions must be a list")
    slots, intent_ids = set(), set()
    result = clone(decisions)
    for decision in result:
        require(isinstance(decision, dict) and decision.get("actorId") in actors_by_id(spec), "unknown_actor", "Unknown decision actor")
        require(decision.get("round") == round_index and decision.get("phase") in {"proposal", "response"},
                "invalid_decision", "Decision is not bound to this round and phase")
        slot = (decision["phase"], decision["actorId"])
        require(slot not in slots, "duplicate_decision", "A phase has one decision slot per actor")
        slots.add(slot)
        require(isinstance(decision.get("observationId"), str) and bool(decision["observationId"])
                and isinstance(decision.get("decisionId"), str), "invalid_decision", "Normalized decision provenance is required")
        require(isinstance(decision.get("intents"), list)
                and len(decision["intents"]) <= spec["limits"]["maxIntentsPerPhase"], "invalid_decision", "Invalid intent count")
        for intent in decision["intents"]:
            require(intent.get("actorId") == decision["actorId"] and intent.get("phase") == decision["phase"]
                    and type(intent.get("priority")) is int, "invalid_intent", "Intent identity is not normalized")
            identifier(intent.get("intentId"), "intentId")
            require(intent["intentId"] not in intent_ids, "duplicate_intent", "An intent cannot occur twice in a round")
            intent_ids.add(intent["intentId"])
            if intent.get("bundleId") is not None:
                identifier(intent["bundleId"], "bundleId")
    return sorted(result, key=lambda d: (d["phase"] != "proposal", d["actorId"]))


def _groups(decisions: list, *, communication_only: bool = False, spec: dict | None = None) -> list:
    groups = {}
    for decision in decisions:
        for intent in decision["intents"]:
            key = (decision["phase"], intent["actorId"], "bundle" if intent.get("bundleId") else "intent",
                   intent.get("bundleId") or intent["intentId"])
            groups.setdefault(key, []).append(intent)
    groups = [sorted(group, key=lambda i: (i["priority"], i["intentId"])) for group in groups.values()]
    if communication_only:
        # Select whole bundles, never communication fragments whose final rollback
        # could change a recipient roster after its response opportunity is lost.
        groups = [group for group in groups if group[0]["phase"] == "proposal" and any(
            templates_by_id(spec).get(intent["templateId"], {}).get("kind") in {"agreement", "message"}
            for intent in group)]
    return sorted(groups, key=lambda g: (g[0]["phase"] != "proposal", g[0]["actorId"], g[0]["priority"], g[0]["intentId"]))


def _run_intents(spec: dict, state: dict, decisions: list, now: str, *, stage: bool = False) -> tuple[dict, list, list]:
    events, resolutions = [], []
    for group in _groups(decisions, communication_only=stage, spec=spec):
        trial, emitted, codes = clone(state), [], []
        try:
            kinds = {templates_by_id(spec).get(i["templateId"], {}).get("kind") for i in group}
            require(not (kinds.intersection({"agreement", "message"}) and kinds - {"agreement", "message", "wait"}),
                    "unsupported_bundle", "Communication and physical actions require separate atomic bundles")
            for intent in group:
                codes.append(_apply(spec, trial, emitted, intent, now))
            _state_check(spec, trial)
            require(len(events) + len(emitted) <= spec["limits"]["maxEventsPerRound"], "event_limit", "Round exceeds declared event limit")
        except WorldError as error:
            if error.code in {"invalid_mechanism", "event_limit", "invalid_state", "resource_violation"}:
                raise
            # Explanations are fixed messages, never balances, hidden facts or actor text.
            for intent in group:
                resolutions.append({"intentId": intent["intentId"], "actorId": intent["actorId"], "round": state["round"],
                                    "accepted": False, "code": error.code if len(group) == 1 else "bundle_rejected",
                                    "explanation": str(error) if len(group) == 1 else "Atomic bundle could not be executed"})
        else:
            state = trial
            events.extend(emitted)
            for intent, code in zip(group, codes):
                resolutions.append({"intentId": intent["intentId"], "actorId": intent["actorId"], "round": state["round"],
                                    "accepted": True, "code": code, "explanation": "Action accepted under the declared mechanism"})
    return state, events, resolutions


def _actor_updates(spec: dict, state: dict, opening: dict, decisions: list) -> None:
    actors = actors_by_id(spec)
    for decision in decisions:
        updates, aid = decision.get("stateUpdates", {}), decision["actorId"]
        require(isinstance(updates, dict) and set(updates) <= {"beliefs", "plans", "priorityChanges"},
                "unauthorized_actor_update", "Stable actor goals, values and incentives cannot be rewritten")
        for key, items in updates.items():
            require(isinstance(items, list) and len(items) <= 20, "invalid_actor_update", "Actor update must be a bounded list")
            stamped = []
            for item in items:
                require(isinstance(item, dict), "invalid_actor_update", "Actor update must be an object with provenance")
                require(item.get("observationId", decision["observationId"]) == decision["observationId"],
                        "invalid_actor_provenance", "Actor update cites another observation")
                if key == "priorityChanges":
                    rule = next((r for r in actors[aid]["priorityRules"] if r["ruleId"] == item.get("ruleId")), None)
                    require(rule is not None and item.get("priorityId") == rule["priorityId"] and item.get("value") == rule["value"],
                            "unauthorized_priority", "Priority revision is not authorized by a declared rule")
                    trigger = rule["trigger"]
                    record = opening[trigger["section"]][trigger["recordId"]]
                    require(visible_to(record, aid) and record.get("value") == trigger["value"],
                            "unauthorized_priority", "Priority trigger was not present in the actor's observation")
                entry = clone(item)
                entry.update(observationId=decision["observationId"], decisionId=decision["decisionId"], round=decision["round"],
                             basis={"kind": "simulation_event", "refs": [decision["observationId"], decision["decisionId"]]})
                stamped.append(entry)
            if key == "priorityChanges":
                state["actorStates"][aid][key].extend(stamped)
            else:
                state["actorStates"][aid][key] = stamped


def _summarize_flow_feedback(spec: dict, state: dict, events: list, start: str, end: str) -> None:
    """Emit actual period totals without disclosing private integration boundaries."""
    totals = defaultdict(Decimal)
    for event in events:
        if event["kind"] == "flow_transfer":
            totals[event["details"]["flowId"]] += decimal(event["details"]["amount"])
    flows = {flow["flowId"]: flow for flow in spec["flows"]}
    for fid in sorted(totals):
        flow = flows[fid]
        _event(spec, state, events, "flow_summary", end, flow,
               stable_id(spec["generationId"], fid, state["round"], "period_feedback"),
               details={"flowId": fid, "start": start, "end": end, "amount": quantity(totals[fid]),
                        "fromAccount": flow["sourceAccount"], "toAccount": flow["targetAccount"]})


def _record_actor_feedback(spec: dict, state: dict, events: list, resolutions: list) -> None:
    """Keep bounded causal feedback in the actor-only next-observation payload.

    Filtering precedes truncation so hidden activity cannot evict visible memory.
    Quiet rounds retain the last action receipt and recent visible event window:
    an actor on a slower cadence must still learn its previous action's outcome.
    """
    result_limit = spec["limits"]["maxIntentsPerPhase"] * 2
    event_limit = spec["limits"]["maxInboxItems"]
    pending = state.get("pendingFeedbackEvents", [])
    pending_ids = {event["eventId"] for event in pending}
    candidates = [*pending, *(event for event in events if event["kind"] != "flow_transfer")]
    now = parse_time(state["simulatedAt"])

    def waiting_for_delivery(event):
        interaction = state["interactions"].get(event["details"].get("interactionId"))
        if interaction is not None and event["kind"] == "offer_counter":
            interaction = state["interactions"].get(interaction.get("supersededBy"), interaction)
        return interaction is not None and parse_time(interaction["deliverAt"]) > now

    for aid, private in state["actorStates"].items():
        own = [result for result in resolutions if result["actorId"] == aid]
        if not own:
            own = [result for result in private.get("lastActionResults", []) if result["actorId"] == aid]
        private["lastActionResults"] = clone(own[-result_limit:])
        recent = {}
        # The sender already received queued receipts when it sent the action;
        # only other permitted audiences receive them at the delivery boundary.
        delivered = [event for event in candidates
                     if not (event["eventId"] in pending_ids and event.get("actorId") == aid)
                     and (event.get("actorId") == aid or not waiting_for_delivery(event))]
        for event in [*private.get("lastObservedEvents", []), *delivered]:
            if visible_to(event, aid):
                recent[event["eventId"]] = event
        visible = list(recent.values())[-event_limit:]
        private["lastObservedEvents"] = clone(visible)
        private["observedEvents"] = [event["eventId"] for event in visible]
    # Durable reducer-owned queue; it is not part of any actor observation.
    state["pendingFeedbackEvents"] = clone([event for event in candidates if waiting_for_delivery(event)
        and any(aid != event.get("actorId") and visible_to(event, aid) for aid in state["actorStates"])])


def initialize_world(spec: dict) -> dict:
    """Create S0 with scheduled asOf effects settled before any observation."""
    with localcontext() as ctx:
        ctx.prec = 80
        spec = validate_spec(spec)
        validate_mechanisms(spec)
        state = initial_snapshot(spec)
        events = []
        _advance(spec, state, events, spec["asOf"], spec["asOf"], initial=True)
        # Initial receipts are carried in the initial snapshot for store export.
        state["initialEvents"] = events
        _record_actor_feedback(spec, state, events, [])
        _state_check(spec, state)
        return state


def stage_interactions(spec: dict, snapshot: dict, decisions: list, round_index: int) -> dict:
    """Project proposal communication without physical, clock or actor-state effects."""
    with localcontext() as ctx:
        ctx.prec = 80
        spec, state, period = _prepare(spec, snapshot, round_index)
        decisions = _decisions(spec, decisions, round_index)
        state["round"] = round_index
        staged, _, _ = _run_intents(spec, state, decisions, period["start"], stage=True)
        # Response observations use the same opening physical/private state. Event
        # receipts belong exclusively to resolution, never tentative staging.
        state = clone(snapshot)
        state.pop("revision", None)
        state["interactions"] = staged["interactions"]
        return state


def _presented_queue_updates(spec: dict, opening: dict, decisions: list, round_index: int) -> dict:
    """Versioned response-phase service accounting, separate from actor consent.

    A valid empty response still consumed the presented inbox opportunity.
    Never add cursor state to legacy specs or queues that have never overflowed.
    The root-level cursor is intentionally outside all actor/API projections.
    """
    if spec.get("interactionQueuePolicy") != "presented-v1":
        return {}
    from .observations import _eligible_inbox

    proposals = [decision for decision in decisions if decision["phase"] == "proposal"]
    staged = stage_interactions(spec, opening, proposals, round_index)
    updates = {}
    limit = spec["limits"]["maxInboxItems"]
    for decision in decisions:
        if decision["phase"] != "response":
            continue
        aid = decision["actorId"]
        pending = _eligible_inbox(spec, staged, aid, round_index)
        if len(pending) > limit:
            updates[aid] = {item["interactionId"]: round_index for item in pending[:limit]}
    return updates


def resolve_round(spec: dict, snapshot: dict, decisions: list, round_index: int) -> dict:
    """Resolve normalized receipts and advance one complete physical period."""
    with localcontext() as ctx:
        ctx.prec = 80
        spec, state, period = _prepare(spec, snapshot, round_index)
        decisions = _decisions(spec, decisions, round_index)
        state["round"] = round_index
        presented = _presented_queue_updates(spec, snapshot, decisions, round_index)
        # Validate provenance against the opening observation, before any effects.
        _actor_updates(spec, state, snapshot, decisions)
        state, events, resolutions = _run_intents(spec, state, decisions, period["start"])
        _advance(spec, state, events, period["start"], period["end"])
        _summarize_flow_feedback(spec, state, events, period["start"], period["end"])
        _record_actor_feedback(spec, state, events, resolutions)
        if presented:
            queue = state.setdefault("interactionQueueState", {})
            for aid, seen in presented.items():
                queue.setdefault(aid, {}).update(seen)
        _state_check(spec, state)
        return {"snapshot": state, "events": events, "resolutions": resolutions}
