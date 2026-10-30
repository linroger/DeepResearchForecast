"""Bounded, pure World Anchor adapter for the existing forecast-case authority.

The authenticated contract retains a prebinding ``forecast_case`` projection,
without assessments/binaries. No schema extensions or numeric runtime live here.
Unsupported executable mappings fail closed rather than becoming ignored keys.
"""

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import json
import math

if __package__:
    from . import forecast_case as fc
    from . import world_anchor as wa
else:  # Deployed research children load bridge modules as bare siblings.
    import forecast_case as fc
    import world_anchor as wa

ENGINE = "target-first-v1"
ADAPTER_VERSION = "world-anchor-target/v1"


def _time(value):
    if value["precision"] == "unknown":
        return None
    instant = datetime.fromisoformat(value["value"].replace("Z", "+00:00"))
    return (
        instant.replace(hour=23, minute=59, second=59)
        if value["precision"] == "day"
        else instant
    )


def _eligible(obs, actor_id, at, cutoff):
    """Mirror the pure actor gate on exact IDs, never on display content."""
    if (
        obs["producer_class"] in {"research_analyst", "model_prior", "simulation"}
        or obs["value_kind"] in {"analyst_inferred", "assumed", "simulated"}
        or obs["actor_basis"] == "none"
    ):
        return False
    audience = obs["audience"]
    if audience["kind"] == "analyst" or (
        audience["kind"] == "actors" and actor_id not in audience["actor_refs"]
    ):
        return False
    known, visible = _time(obs["known_by"]), _time(obs["visible_at"])
    instant = datetime.fromisoformat(at.replace("Z", "+00:00"))
    limit = min(instant, datetime.fromisoformat(cutoff.replace("Z", "+00:00")))
    return (
        known is not None
        and visible is not None
        and known <= limit
        and visible <= instant
    )


def _visible_ids(pack, actor_id, at):
    bound = {
        oid
        for b in pack["bindings"]
        if b["status"] == "bound"
        for oid in b["observation_ids"]
    }
    return {
        o["observation_id"]
        for o in pack["observations"]
        if o["observation_id"] in bound
        and _eligible(o, actor_id, at, pack["scope"]["cutoff"])
    }


def _native_unit(label):
    """Installed bounded subset of the existing native unit vocabulary.

    Composite unit expressions require a separate admitted mapping. Rejecting
    them here cannot silently change the numeric compiler's interpretation.
    """
    if label in {"fraction", "ratio", "1", "dimensionless"}:
        return "dimensionless", None, Decimal(1)
    if label in {"percent", "%"}:
        return "dimensionless", None, Decimal("0.01")
    if label in {"unit", "units", "count", "counts"}:
        return "count", None, Decimal(1)
    power_scales = {"W": 1, "kW": 1000, "MW": 1000000, "GW": 1000000000}
    if label in power_scales:
        return "power", None, Decimal(power_scales[label])
    for currency in ("USD", "EUR", "CNY"):
        for scale, amount in (("", 1), ("million", 1000000), ("billion", 1000000000)):
            if label in {f"{currency} {scale}".strip(), f"{scale} {currency}".strip()}:
                return "currency", currency, Decimal(amount)
    raise wa.AnchorError("E_NOT_READY", "unsupported_native_unit")


def _unit_key(unit):
    return (
        unit["dimension"],
        unit["currency"],
        Decimal(unit["scale"]),
        unit["price_basis"],
        unit["base_period"],
    )


def _unit_contract(unit, label, rid=None):
    _need(_unit_key(unit)[:3] == _native_unit(label), "unit_dimension_or_scale", rid)
    if unit["dimension"] != "currency":
        _need(
            unit["price_basis"] == "not_applicable" and unit["base_period"] is None,
            "unit_basis",
            rid,
        )


def _period_unit(unit, rid):
    _need(
        unit["id"] == "period"
        and unit["dimension"] == "time"
        and unit["scale"] == "1"
        and unit["currency"] is None
        and unit["price_basis"] == "not_applicable"
        and unit["base_period"] is None,
        "simulation_period_unit",
        rid,
    )


def _actor_unit(actor, field, term, node_units):
    slot = _actor_slot(actor, field)
    if slot is None or slot[1] == "reversible":
        return
    rid, unit = term["requirement_id"], term["identity"]["unit"]
    if slot[1] in {"duePeriod", "lagPeriods", "cadencePeriods", "releaseLagPeriods"}:
        _period_unit(unit, rid)
    elif slot[1] in {"minimum", "maximum", "value"}:
        obj = slot[0]
        nid = obj.get("nodeId")
        if nid is None:
            nid = next(
                l["nodeId"] for l in actor["levers"] if l["leverId"] == obj["leverId"]
            )
        _need(_unit_key(unit) == _unit_key(node_units[nid]), "actor_amount_unit", rid)
    elif slot[1] == "capacity":
        _need(
            unit["id"] == "capacity"
            and _unit_key(unit)
            == ("dimensionless", None, Decimal(1), "not_applicable", None),
            "actor_capacity_unit",
            rid,
        )
    elif slot[1] == "cost":
        _need(
            unit["id"] == "capacity/" + node_units[slot[0]["nodeId"]]["id"]
            and unit["dimension"] == "capacity_per_unit"
            and unit["scale"] == "1"
            and unit["currency"] is None
            and unit["price_basis"] == "not_applicable"
            and unit["base_period"] is None,
            "actor_cost_unit",
            rid,
        )
    else:
        _need(
            _unit_key(unit)
            == ("dimensionless", None, Decimal(1), "not_applicable", None),
            "actor_fraction_unit",
            rid,
        )


def _mechanism_units(nodes, mechanisms, node_units):
    known = dict(node_units)
    pending = list(mechanisms.values())
    while pending:
        ready = [m for m in pending if all(n in known for n in m["inputNodeIds"])]
        _need(bool(ready), "unbound_intermediate_unit", code="E_NOT_READY")
        for m in ready:
            inputs = [known[n] for n in m["inputNodeIds"]]
            output = m["outputNodeId"]
            kind = m["kind"]
            if kind == "regulatory_milestone":
                _need(output in known, "unbound_milestone_unit", code="E_NOT_READY")
                expected = known[output]
            elif kind == "growth":
                _need(
                    _unit_key(inputs[1])
                    == ("dimensionless", None, Decimal(1), "not_applicable", None),
                    "growth_rate_unit",
                )
                expected = inputs[0]
            elif kind == "product":
                material = [u for u in inputs if u["dimension"] != "dimensionless"]
                _need(
                    len(material) <= 1, "unsupported_product_unit", code="E_NOT_READY"
                )
                expected = deepcopy(material[0] if material else inputs[0])
                scale = Decimal(1)
                for unit in inputs:
                    scale *= Decimal(unit["scale"])
                expected["scale"] = str(scale)
            else:
                _need(
                    all(_unit_key(u) == _unit_key(inputs[0]) for u in inputs),
                    "mechanism_input_units",
                )
                expected = inputs[0]
            _unit_contract(expected, nodes[output]["units"])
            if output in known:
                _need(
                    _unit_key(known[output]) == _unit_key(expected),
                    "mechanism_output_unit_basis",
                )
            known[output] = expected
            pending.remove(m)
    return known


def _need(condition, path, requirement=None, code="E_CONTRACT"):
    if not condition:
        raise wa.AnchorError(code, path, requirement)


def _pointer(value, pointer):
    try:
        for key in pointer.split("/")[1:]:
            key = key.replace("~1", "/").replace("~0", "~")
            value = value[int(key)] if isinstance(value, list) else value[key]
        return value
    except (KeyError, ValueError, IndexError, TypeError):
        raise wa.AnchorError("E_REFERENCE", "target_registry") from None


def _native(index, contract):
    authority = _pointer(
        json.loads(index.artifact_bytes(contract["authority_artifact_id"])),
        contract["authority_pointer"],
    )
    native = authority.get("forecast_case")
    _need(
        isinstance(native, dict) and not {"assessments", "binaries"} & native.keys(),
        "missing_native_case",
    )
    identities = authority.get("node_identities", {})
    _need(isinstance(identities, dict), "node_identity_registry")
    return deepcopy(native), deepcopy(identities)


def _number(value, rid):
    decimal = Decimal(value)
    result = int(decimal) if decimal == decimal.to_integral_value() else float(decimal)
    _need(
        math.isfinite(result) and Decimal(str(result)) == decimal,
        "unsupported_numeric_precision",
        rid,
        "E_NOT_READY",
    )
    return result


def _bounds(value, rid):
    _need(
        value["kind"] in {"number", "range"}, "unsupported_mapping", rid, "E_NOT_READY"
    )
    if value["kind"] == "number":
        point = _number(value["value"], rid)
        return point, point, point
    return None, _number(value["low"], rid), _number(value["high"], rid)


def _slots(mechanism):
    kind = mechanism["kind"]
    if kind == "linear":
        return ["coefficient:" + nid for nid in mechanism["inputNodeIds"]] + [
            "intercept"
        ]
    return {
        "adoption": ["rate"],
        "regulatory_milestone": ["milestonePeriod", "before", "after"],
    }.get(kind, [])


def _actor_slot(actor, field):
    """Supported selectors are explicit native leaves, never arbitrary pointers."""
    direct = {
        "constraints.capacity": (actor["constraints"], "capacity"),
        "decisionRule.cadencePeriods": (actor["decisionRule"], "cadencePeriods"),
        "information.releaseLagPeriods": (actor["information"], "releaseLagPeriods"),
        "credibility": (actor, "credibility"),
    }
    if field in direct:
        return direct[field]
    bits = field.split("/")
    if len(bits) == 3 and bits[0] in {"levers", "plans"}:
        collection, identifier, key = bits
        allowed = (
            {"minimum", "maximum", "cost", "lagPeriods", "reversible"}
            if collection == "levers"
            else {"value", "duePeriod"}
        )
        id_key = "leverId" if collection == "levers" else "planId"
        rows = [row for row in actor[collection] if row[id_key] == identifier]
        if len(rows) == 1 and key in allowed:
            return rows[0], key
    return None


def _structure(case, terms):
    result = deepcopy(case)
    for key in ("assessments", "binaries"):
        result.pop(key, None)
    # Added evidence rows are compared separately by the final validator.
    result.pop("sources", None)
    result.pop("claims", None)
    for node in result["nodes"]:
        for key in (
            "value",
            "range",
            "status",
            "basis",
            "gap",
            "vintage",
            "sourceIds",
            "claimIds",
        ):
            node.pop(key, None)
    for mechanism in result["mechanisms"]:
        mechanism.pop("parameters", None)
    actors = {a["actorId"]: a for a in result["actors"]}
    supported_plans = {
        (c["object_id"], c["field"].split("/")[1])
        for term in terms
        for c in term["consumers"]
        if c["engine"] == ENGINE
        and c["role"] == "actor_brief"
        and c["field"].startswith("plans/")
        and len(c["field"].split("/")) == 3
    }
    for aid, actor in actors.items():
        actor.pop("decisionBasis", None)
        actor["objectives"] = []
        actor["decisionRule"]["triggers"] = []
        actor["plans"] = [
            p for p in actor["plans"] if (aid, p["planId"]) in supported_plans
        ]
    for term in terms:
        for consumer in term["consumers"]:
            if consumer["engine"] == ENGINE and consumer["role"] == "actor_brief":
                actor = actors.get(consumer["object_id"])
                slot = (
                    _actor_slot(actor, consumer["field"]) if actor is not None else None
                )
                if slot:
                    slot[0][slot[1]] = None
    return result


def _compile(case, *, pack, requirements, index, policy, _provenance=None):
    projection = wa.engine_projection(
        pack, requirements=requirements, index=index, policy=policy, engine=ENGINE
    )
    contract = requirements["contract"]
    native, declared_identities = _native(index, contract)
    try:
        supplied = fc.validate_case(case)
    except fc.CaseValidationError:
        raise wa.AnchorError("E_CONTRACT", "invalid_native_case") from None
    terms = requirements["requirements"]
    _need(
        _structure(supplied, terms) == _structure(native, terms),
        "native_case_structure",
    )
    result = {
        **deepcopy(native),
        "assessments": supplied["assessments"],
        "binaries": supplied["binaries"],
    }
    result["claims"] = []
    for node in result["nodes"]:
        node["claimIds"] = []
    nodes = {n["nodeId"]: n for n in result["nodes"]}
    mechanisms = {m["mechanismId"]: m for m in result["mechanisms"]}
    actors = {a["actorId"]: a for a in result["actors"]}
    scope = pack["scope"]
    settlement = contract["settlement"]
    _need(
        scope["authority"] == result["authority"] == ENGINE
        and scope["cutoff"][:10] == result["asOf"]
        and scope["horizon"]["end"] == result["resolution"]["horizon"]
        and settlement["target_node_id"] == result["resolution"]["targetNodeId"]
        and settlement["identity"]["reference_period"] == scope["horizon"],
        "target_identity_or_period",
    )

    def unit_matches(native_unit, unit):
        return native_unit == unit["id"] or any(
            alias["field"] == "unit"
            and alias["canonical_id"] == unit["id"]
            and alias["literal"] == native_unit
            for alias in contract["aliases"]
        )

    _need(
        unit_matches(result["resolution"]["units"], settlement["identity"]["unit"]),
        "target_unit",
    )
    _unit_contract(settlement["identity"]["unit"], result["resolution"]["units"])
    bindings = {b["requirement_id"]: b for b in projection["bindings"]}
    observations = {o["observation_id"]: o for o in projection["observations"]}
    refs = {r["ref_id"]: r for r in pack["references"]}
    sources = {s["source_key"]: s for s in pack["sources"]}
    requirements_by_origin = {r["origin_pointer"]: r for r in terms}
    mapped = set()
    node_terms, parameter_terms, actor_terms = {}, {}, {}

    def binding(term):
        rid = term["requirement_id"]
        row = bindings.get(rid)
        _need(row is not None, "unbound_required_mapping", rid, "E_NOT_READY")
        if row["assumption"]:
            return row, None, row["assumption"]["value"]
        _need(len(row["observation_ids"]) == 1, "ambiguous_support", rid, "E_NOT_READY")
        obs = observations[row["observation_ids"][0]]
        _need(obs["identity"] == term["identity"], "identity_unit_period_mismatch", rid)
        return row, obs, obs["value"]

    def source_ids(obs, rid):
        if obs is None:
            return []
        ids = []
        for source_key in sorted({refs[r]["source_key"] for r in obs["ref_ids"]}):
            source = sources[source_key]
            quotes = [
                refs[r]["locator"].get("quote", "")
                for r in obs["ref_ids"]
                if refs[r]["source_key"] == source_key
            ]
            # Native source rows have no independent known-by field. Do not
            # fabricate publication/retrieval to fit their stricter contract.
            retrieved = source["retrieved_at"]["value"]
            _need(
                source["url"]
                and retrieved
                and retrieved[:10] <= result["asOf"]
                and any(quotes),
                "unsupported_source_mapping",
                rid,
                "E_NOT_READY",
            )
            row = {
                "sourceId": "",
                "url": source["url"],
                "title": source["title"] or "Retained anchor source",
                "publishedAt": source["published_at"]["value"],
                "retrievedAt": retrieved,
                "originCluster": source_key,
                "tier": source["tier"],
                "fetched": source["retention"] in {"fetched_page", "official_row"},
                "passage": "\n".join(dict.fromkeys(q for q in quotes if q)),
            }
            # Reuse only an exact generated row, not an incidental URL/SID.
            existing = next(
                (
                    s
                    for s in result["sources"]
                    if {k: v for k, v in s.items() if k != "sourceId"}
                    == {k: v for k, v in row.items() if k != "sourceId"}
                ),
                None,
            )
            if existing is None:
                row["sourceId"] = "S" + str(
                    max((int(s["sourceId"][1:]) for s in result["sources"]), default=0)
                    + 1
                )
                result["sources"].append(row)
                existing = row
            ids.append(existing["sourceId"])
            if _provenance is not None:
                link = {
                    "requirement_id": rid,
                    "binding_id": bindings[rid]["binding_id"],
                    "observation_id": obs["observation_id"],
                    "source_key": source_key,
                    "ref_ids": sorted(
                        r for r in obs["ref_ids"] if refs[r]["source_key"] == source_key
                    ),
                }
                rows = _provenance["sources"].setdefault(existing["sourceId"], [])
                if link not in rows:
                    rows.append(link)
        return ids

    def source_incidence(destination, ids, term, obs):
        if _provenance is None or obs is None:
            return
        for sid in ids:
            rows = destination.setdefault(sid, [])
            for link in _provenance["sources"].get(sid, []):
                if (
                    link["requirement_id"] == term["requirement_id"]
                    and link["observation_id"] == obs["observation_id"]
                    and link not in rows
                ):
                    rows.append(deepcopy(link))

    def claim_provenance(claim_id, node_id, origin, term, obs, ref_id, selector, ids):
        if _provenance is not None:
            _provenance["claims"][claim_id] = {
                "node_id": node_id,
                "origin": origin,
                "requirement_id": term["requirement_id"],
                "binding_id": bindings[term["requirement_id"]]["binding_id"],
                "observation_id": obs["observation_id"],
                "ref_id": ref_id,
                "selector": deepcopy(selector),
                "source_ids": list(ids),
            }

    def provenance(term, bound, obs):
        if bound["assumption"]:
            return {
                "basis": "assumed",
                "sourceIds": [],
                "gap": bound["assumption"]["rationale"],
            }
        kind = obs["value_kind"]
        _need(
            kind
            in {"observed", "reported", "third_party_forecast", "analyst_inferred"},
            "unsupported_value_kind",
            term["requirement_id"],
            "E_NOT_READY",
        )
        return {
            "basis": "observed" if kind == "observed" else "estimated",
            "sourceIds": source_ids(obs, term["requirement_id"]),
            "gap": "World Anchor value kind: " + kind,
        }

    def authority_reference(term, observation):
        """Return only the independently approved authority field's passage."""
        rid = term["requirement_id"]
        error = "unapproved_actor_authority"
        _need(
            term["value_type"] == observation["value"]["kind"] == "text",
            error,
            rid,
            "E_PRIVACY",
        )
        _need(
            observation["value_kind"] in {"observed", "reported"},
            error,
            rid,
            "E_PRIVACY",
        )
        reviews = [
            r
            for r in pack["review_receipts"]
            if r["review_id"] == observation["review_id"]
        ]
        _need(len(reviews) == 1, error, rid, "E_PRIVACY")
        review = reviews[0]
        proposals = [
            p
            for p in pack["evidence_proposals"]
            if wa.anchor_hash(p) == review["proposal_hash"]
        ]
        _need(len(proposals) == 1, error, rid, "E_PRIVACY")
        rows = [
            r
            for r in proposals[0]["rows"]
            if wa._id("obs", r["claim_id"], r, review["review_id"])
            == observation["observation_id"]
        ]
        _need(len(rows) == 1, error, rid, "E_PRIVACY")
        row = rows[0]
        decisions = [
            d for d in review["decisions"] if d["proposal_id"] == row["proposal_id"]
        ]
        _need(
            len(decisions) == 1 and decisions[0]["verdict"] == "explicit_support",
            error,
            rid,
            "E_PRIVACY",
        )
        supports = [s for s in row["support"] if s["field"] == "authority"]
        checks = [c for c in decisions[0]["checks"] if c["field"] == "authority"]
        _need(
            len(supports) == len(checks) == 1
            and checks[0]["verdict"] == "explicit_support",
            error,
            rid,
            "E_PRIVACY",
        )
        support = supports[0]
        _need(
            support["ref_id"] in checks[0]["ref_ids"]
            and support["ref_id"] in observation["ref_ids"],
            error,
            rid,
            "E_PRIVACY",
        )
        selector = support["selector"]
        _need(
            selector["kind"] == "text_span" and bool(selector["quote"]),
            "unsupported_claim_mapping",
            rid,
            "E_NOT_READY",
        )
        return support["ref_id"], selector["quote"], selector

    for term in terms:
        rid = term["requirement_id"]
        for consumer in term["consumers"]:
            if consumer["engine"] != ENGINE or consumer["role"] == "research_note":
                continue
            rule = [
                r
                for r in policy["consumer_rules"]
                if all(r[k] == consumer[k] for k in consumer)
            ]
            _need(
                len(rule) == 1 and rule[0]["adapter_version"] == ADAPTER_VERSION,
                "unsupported_adapter",
                rid,
                "E_NOT_READY",
            )
            key = (consumer["role"], consumer["object_id"], consumer["field"])
            _need(key not in mapped, "duplicate_mapping", rid)
            mapped.add(key)
            role, obj, field = key
            if term["kind"] == "target_definition":
                _need(
                    key == ("diagnostic", settlement["target_node_id"], "definition"),
                    "unsupported_target_mapping",
                    rid,
                    "E_NOT_READY",
                )
                continue
            if rid not in bindings and not term["required"]:
                continue
            bound, obs, value = binding(term)
            if (
                role == "initial_state"
                and field == "value"
                and obj in nodes
                and term["kind"] == "baseline"
            ):
                _need(
                    term["identity"]
                    and unit_matches(nodes[obj]["units"], term["identity"]["unit"]),
                    "node_unit",
                    rid,
                )
                _need(
                    obj not in {m["outputNodeId"] for m in mechanisms.values()},
                    "derived_initial_write",
                    rid,
                )
                node_terms[obj] = term
                _unit_contract(term["identity"]["unit"], nodes[obj]["units"], rid)
                point, low, high = _bounds(value, rid)
                prov = provenance(term, bound, obs)
                node = nodes[obj]
                node.update(
                    value=point,
                    range={"low": low, "high": high},
                    basis=prov["basis"],
                    gap=prov["gap"],
                    sourceIds=sorted(set(node["sourceIds"] + prov["sourceIds"])),
                )
                if _provenance is not None:
                    source_incidence(
                        _provenance["node_sources"].setdefault(obj, {}),
                        prov["sourceIds"],
                        term,
                        obs,
                    )
                node["status"] = (
                    "unknown" if prov["basis"] == "assumed" else "contested"
                )
                node["vintage"] = (
                    obs["vintage"]["value"][:10]
                    if obs and obs["vintage"]["value"]
                    else None
                )
                if obs:
                    for ref_id in obs["ref_ids"]:
                        passage = refs[ref_id]["locator"].get("quote")
                        _need(
                            bool(passage),
                            "unsupported_claim_mapping",
                            rid,
                            "E_NOT_READY",
                        )
                        cid = "anchor_" + wa.anchor_hash(
                            [obj, obs["observation_id"], ref_id]
                        )
                        result["claims"].append(
                            {
                                "claimId": cid,
                                "nodeId": obj,
                                "sourceIds": prov["sourceIds"],
                                "passage": passage,
                                "status": "reported",
                            }
                        )
                        node["claimIds"].append(cid)
                        claim_provenance(
                            cid,
                            obj,
                            "initial_state",
                            term,
                            obs,
                            ref_id,
                            refs[ref_id]["locator"],
                            prov["sourceIds"],
                        )
            elif (
                role == "mechanism"
                and obj in mechanisms
                and field in _slots(mechanisms[obj])
            ):
                _need(
                    term["kind"] in {"mechanism_parameter", "event"}
                    and term["identity"] is not None,
                    "parameter_identity",
                    rid,
                )
                parameter_terms[(obj, field)] = term
                _, low, high = _bounds(value, rid)
                scalar = {"low": low, "high": high, **provenance(term, bound, obs)}
                if _provenance is not None:
                    source_incidence(
                        _provenance["parameter_sources"]
                        .setdefault(obj, {})
                        .setdefault(field, {}),
                        scalar["sourceIds"],
                        term,
                        obs,
                    )
                if field.startswith("coefficient:"):
                    i = mechanisms[obj]["inputNodeIds"].index(
                        field[len("coefficient:") :]
                    )
                    mechanisms[obj]["parameters"]["coefficients"][i] = scalar
                else:
                    mechanisms[obj]["parameters"][field] = scalar
                if field == "milestonePeriod":
                    _need(
                        low == high and isinstance(low, int),
                        "unsupported_event_time",
                        rid,
                        "E_NOT_READY",
                    )
            elif role == "actor_brief" and obj in actors:
                _need(term["actor_ref"] == obj, "actor_identity", rid)
                _need(
                    obs is not None and obs["subject_actor_ref"] == obj,
                    "actor_evidence_identity",
                    rid,
                )
                actor_terms[(obj, field)] = term
                slot = _actor_slot(actors[obj], field)
                if slot is not None or field.startswith("authority:"):
                    _need(
                        _eligible(obs, obj, scope["cutoff"], scope["cutoff"]),
                        "unavailable_actor_control",
                        rid,
                        "E_PRIVACY",
                    )
                if slot is not None:
                    if value["kind"] == "boolean" and slot[1] == "reversible":
                        slot[0][slot[1]] = value["value"]
                    else:
                        point, _, _ = _bounds(value, rid)
                        _need(
                            point is not None,
                            "unsupported_actor_range",
                            rid,
                            "E_NOT_READY",
                        )
                        slot[0][slot[1]] = point
                else:
                    _need(
                        field == "statement" or field.startswith("authority:"),
                        "unsupported_mapping",
                        rid,
                        "E_NOT_READY",
                    )
            else:
                _need(False, "unsupported_mapping", rid, "E_NOT_READY")

    writers = {m["outputNodeId"] for m in mechanisms.values()}
    for node_id in writers:
        node = nodes[node_id]
        _need(node["range"] is not None, "missing_derived_bounds", code="E_NOT_READY")
        # The retained bounds remain explicit planning assumptions; their seed
        # point cannot survive rebinding inputs. The native compiler computes
        # actual derived state at period zero and thereafter.
        node.update(
            value=None,
            status="unknown",
            vintage=None,
            basis="assumed",
            gap="Retained planning bounds; derived state is computed by the admitted mechanism.",
        )
    _need(
        set(nodes) - writers == set(node_terms), "unbound_primitive", code="E_NOT_READY"
    )
    node_units = {nid: term["identity"]["unit"] for nid, term in node_terms.items()}
    if settlement["target_node_id"] in node_terms:
        _need(
            node_terms[settlement["target_node_id"]]["identity"]
            == settlement["identity"],
            "primitive_target_identity_unit_period",
        )
    node_units[settlement["target_node_id"]] = settlement["identity"]["unit"]
    _need(set(declared_identities) <= set(nodes), "node_identity_registry")
    admitted_identities = {nid: term["identity"] for nid, term in node_terms.items()}
    admitted_identities[settlement["target_node_id"]] = settlement["identity"]
    for nid, identity in declared_identities.items():
        # Reuse the core's closed Identity validator. These declarations come
        # only from the authenticated prebinding authority, never a caller's
        # numeric values, and do not create observations or new case fields.
        wa._identity(identity)
        _need(unit_matches(nodes[nid]["units"], identity["unit"]), "node_identity_unit")
        _unit_contract(identity["unit"], nodes[nid]["units"])
        if nid in admitted_identities:
            _need(
                identity == admitted_identities[nid], "node_identity_contract_mismatch"
            )
        node_units[nid] = identity["unit"]
    node_units = _mechanism_units(nodes, mechanisms, node_units)
    for (aid, field), term in actor_terms.items():
        _actor_unit(actors[aid], field, term, node_units)
    projected = {m["mechanism_id"]: m for m in projection["mechanisms"]}
    _need(set(projected) == set(mechanisms), "mechanism_registry")
    for mid, mechanism in mechanisms.items():
        descriptor = projected[mid]
        _need(
            descriptor["template"] == mechanism["kind"]
            and descriptor["input_node_ids"] == mechanism["inputNodeIds"]
            and descriptor["output_node_id"] == mechanism["outputNodeId"],
            "mechanism_structure",
        )
        _need(
            descriptor["template_version"] == "v1"
            and descriptor["lag_requirement_origin"] is None
            and not descriptor["applicability_requirement_origins"],
            "unsupported_mechanism_semantics",
            code="E_NOT_READY",
        )
        _need(
            {p["name"] for p in descriptor["parameters"]} == set(_slots(mechanism)),
            "parameter_slots",
        )
        for consumer in descriptor["consumers"]:
            if consumer["engine"] == ENGINE:
                rules = [
                    r
                    for r in policy["consumer_rules"]
                    if all(r[k] == consumer[k] for k in consumer)
                ]
                _need(
                    len(rules) == 1
                    and rules[0]["adapter_version"] == ADAPTER_VERSION
                    and rules[0]["template_versions"] == ["v1"]
                    and consumer["role"] == "mechanism"
                    and consumer["object_id"] == mid
                    and consumer["field"] == "template",
                    "unsupported_mechanism_adapter",
                    code="E_NOT_READY",
                )
        for parameter in descriptor["parameters"]:
            term = parameter_terms.get((mid, parameter["name"]))
            _need(
                term is not None
                and term["origin_pointer"] == parameter["requirement_origin"]
                and term["identity"]["unit"] == parameter["unit"],
                "parameter_identity_unit_period",
            )
            # Dimensionless coefficients/rates and native output intercepts are
            # the installed bounded grammar. No implicit dimensional conversion.
            unit = parameter["unit"]
            if (
                parameter["name"].startswith("coefficient:")
                or parameter["name"] == "rate"
            ):
                _need(
                    unit["dimension"] == "dimensionless"
                    and unit["scale"] == "1"
                    and unit["currency"] is None,
                    "parameter_unit",
                )
                if parameter["name"].startswith("coefficient:"):
                    input_id = parameter["name"][len("coefficient:") :]
                    _need(
                        nodes[input_id]["units"]
                        == nodes[mechanism["outputNodeId"]]["units"],
                        "coefficient_unit",
                    )
            elif parameter["name"] == "milestonePeriod":
                _period_unit(unit, term["requirement_id"])
            else:
                _need(
                    _unit_key(node_units[mechanism["outputNodeId"]]) == _unit_key(unit),
                    "parameter_unit",
                )

    dossiers = {a["actor_ref"]: a for a in contract["actors"]}
    _need(len(dossiers) == len(contract["actors"]), "duplicate_actor_registry")
    # Research dossiers may describe more subjects than the executable cast.
    # Only native case actors proceed to row and lever-authority validation.
    _need(set(actors) <= set(dossiers), "actor_registry")
    native_actors = {a["actorId"]: a for a in native["actors"]}
    for aid, actor in actors.items():
        dossier = dossiers[aid]
        registry = _pointer(
            json.loads(index.artifact_bytes(dossier["registry_artifact_id"])),
            dossier["registry_pointer"],
        )
        _need(registry == native_actors[aid], "actor_registry_identity")
        authority = {a["lever_id"]: a for a in dossier["authority"]}
        _need(
            set(authority) == {a["leverId"] for a in actor["levers"]},
            "missing_authority",
            code="E_NOT_READY",
        )
        authority_claim_ids = []
        for lever in actor["levers"]:
            auth = authority[lever["leverId"]]
            term = actor_terms.get((aid, "authority:" + lever["leverId"]))
            _need(
                term is not None
                and term["kind"] == "actor_authority"
                and term["origin_pointer"] == auth["requirement_origin"]
                and auth["node_id"] == lever["nodeId"],
                "missing_authority",
                code="E_NOT_READY",
            )
            _need(
                (
                    auth["mode"] == "sole"
                    and not auth["coholder_actor_refs"]
                    and not lever["requiresConsent"]
                )
                or (
                    auth["mode"] == "consent"
                    and sorted(auth["coholder_actor_refs"])
                    == sorted(lever["requiresConsent"])
                ),
                "unsupported_authority",
                term["requirement_id"],
                "E_NOT_READY",
            )
            for origin in auth["bound_requirement_origins"]:
                _need(
                    origin in requirements_by_origin
                    and requirements_by_origin[origin]["requirement_id"] in bindings,
                    "unbound_authority",
                    term["requirement_id"],
                    "E_NOT_READY",
                )
            _, observation, _ = binding(term)
            _need(
                observation is not None,
                "missing_authority",
                term["requirement_id"],
                "E_NOT_READY",
            )
            ref_id, quote, selector = authority_reference(term, observation)
            # Each claim cites only the source that contains this exact
            # admitted authority passage. A numeric baseline is not proof
            # of control, and a secondary source is not made primary here.
            ids = source_ids(
                {**observation, "ref_ids": [ref_id]}, term["requirement_id"]
            )
            claim_id = "anchor_authority_" + wa.anchor_hash(
                [aid, lever["leverId"], observation["observation_id"], ref_id]
            )
            result["claims"].append(
                {
                    "claimId": claim_id,
                    "nodeId": lever["nodeId"],
                    "sourceIds": ids,
                    "passage": quote,
                    "status": "reported",
                }
            )
            node = nodes[lever["nodeId"]]
            node["claimIds"].append(claim_id)
            node["sourceIds"] = sorted(set(node["sourceIds"]) | set(ids))
            if _provenance is not None:
                source_incidence(
                    _provenance["node_sources"].setdefault(lever["nodeId"], {}),
                    ids,
                    term,
                    observation,
                )
            claim_provenance(
                claim_id,
                lever["nodeId"],
                "actor_authority",
                term,
                observation,
                ref_id,
                selector,
                ids,
            )
            authority_claim_ids.append(claim_id)
        actor["decisionBasis"] = "World Anchor admitted lever authority: " + "; ".join(
            sorted(authority_claim_ids)
        )
        # Initial inference is never executable just because it was in a plan.
        actor["objectives"] = []
        actor["decisionRule"]["triggers"] = []
        actor["plans"] = [
            p
            for p in actor["plans"]
            if all(
                (aid, f"plans/{p['planId']}/{field}") in actor_terms
                for field in ("value", "duePeriod")
            )
        ]
        _need(
            not any(p.get("condition") for p in actor["plans"]),
            "unsupported_plan_condition",
            code="E_NOT_READY",
        )
        _need(not dossier["red_lines"], "unsupported_red_line", code="E_NOT_READY")
    _need(
        not projection["hazards"]
        and not projection["identities"]
        and not projection["indicators"],
        "unsupported_mapping",
        code="E_NOT_READY",
    )
    # Native milestone parameters are supported; arbitrary calendar instructions
    # have no runtime scheduler in this engine and cannot be silently accepted.
    _need(
        not projection["calendar"], "unsupported_calendar_mapping", code="E_NOT_READY"
    )
    try:
        validated = fc.validate_case(result)
    except fc.CaseValidationError:
        raise wa.AnchorError("E_NOT_READY", "unsupported_native_case_mapping") from None
    if _provenance is not None:
        for source in validated["sources"]:
            _provenance["sources"].setdefault(source["sourceId"], [])
        for node in validated["nodes"]:
            links = _provenance["node_sources"].setdefault(node["nodeId"], {})
            for sid in node["sourceIds"]:
                links.setdefault(sid, [])
        for mechanism in validated["mechanisms"]:
            mid = mechanism["mechanismId"]
            _provenance["mechanism_sources"][mid] = {
                sid: [] for sid in mechanism["sourceIds"]
            }
            parameters = _provenance["parameter_sources"].setdefault(mid, {})
            for slot in _slots(mechanism):
                if slot.startswith("coefficient:"):
                    scalar = mechanism["parameters"]["coefficients"][
                        mechanism["inputNodeIds"].index(slot[len("coefficient:") :])
                    ]
                else:
                    scalar = mechanism["parameters"][slot]
                links = parameters.setdefault(slot, {})
                ids = (
                    scalar.get("sourceIds", mechanism["sourceIds"])
                    if isinstance(scalar, dict)
                    else mechanism["sourceIds"]
                )
                for sid in ids:
                    links.setdefault(sid, [])
        _need(
            set(_provenance["claims"]) == {c["claimId"] for c in validated["claims"]},
            "claim_provenance_closure",
        )
    return validated


def apply_anchors_to_case(case, *, pack, requirements, index, policy):
    """Bind a native preassessment case without mutation or implicit point choice."""
    return _compile(
        case, pack=pack, requirements=requirements, index=index, policy=policy
    )


def validate_anchored_case(case, *, pack, requirements, index, policy):
    """Reconstruct and require the final native case's admitted numeric authority."""
    expected = _compile(
        case, pack=pack, requirements=requirements, index=index, policy=policy
    )
    _need(expected == case, "anchored_case_mismatch")
    return expected


def anchored_case_provenance(case, *, pack, requirements, index, policy):
    """Return exact privileged evidence joins for a reconstructed native case.

    All maps use the native IDs present in the validated case. Empty source
    link lists mean unanchored inherited provenance, never public permission.
    Callers must apply audience/value-kind and full source closure themselves;
    neither public-node membership nor any single source use grants access to
    other claims or uses. This metadata, including its hashes, is not public.
    """
    trace = {
        "claims": {},
        "sources": {},
        "node_sources": {},
        "parameter_sources": {},
        "mechanism_sources": {},
    }
    expected = _compile(
        case,
        pack=pack,
        requirements=requirements,
        index=index,
        policy=policy,
        _provenance=trace,
    )
    _need(expected == case, "anchored_case_mismatch")
    return {
        "schema_version": "world-anchor-case-provenance/v1",
        "case_hash": fc.case_hash(expected),
        "pack_hash": wa.anchor_hash(pack),
        **deepcopy(trace),
    }


def actor_observation_inputs(case, *, pack, requirements, index, policy, actor_id, at):
    """Project only visible admitted inputs; this is never a global pack view."""
    validate_anchored_case(
        case, pack=pack, requirements=requirements, index=index, policy=policy
    )
    _need(
        any(a["actorId"] == actor_id for a in case["actors"])
        and any(a["actor_ref"] == actor_id for a in requirements["contract"]["actors"]),
        "actor_registry",
    )
    projection = wa.actor_projection(
        pack,
        requirements=requirements,
        index=index,
        policy=policy,
        actor_ref=actor_id,
        at=at,
    )

    # This runtime initializes at the frozen research cutoff. Its control state
    # is not a historical actor reconstruction and cannot be replayed earlier.
    _need(at >= pack["scope"]["cutoff"], "before_simulation_cutoff", code="E_PRIVACY")
    settlement = requirements["contract"]["settlement"]
    excluded = set()
    if (
        settlement["identity"]["reference_period"]["end"] + "T23:59:59Z"
        > pack["scope"]["cutoff"]
    ):
        # The sealed generation contains no subsequently published settlement
        # evidence. Advancing the simulation clock cannot turn its prediction
        # into a factual observation, even after the nominal release date.
        excluded.add(settlement["target_node_id"])
        for _ in case["mechanisms"]:
            for mechanism in case["mechanisms"]:
                if excluded.intersection(mechanism["inputNodeIds"]):
                    excluded.add(mechanism["outputNodeId"])
    visible = _visible_ids(pack, actor_id, at)
    bindings = {
        b["requirement_id"]: b
        for b in pack["bindings"]
        if b["status"] == "bound"
        and b["observation_ids"]
        and set(b["observation_ids"]) <= visible
    }
    nodes, plans, parameters = set(), {}, set()
    for term in requirements["requirements"]:
        if term["requirement_id"] not in bindings:
            continue
        for c in term["consumers"]:
            if c["engine"] != ENGINE or c["role"] == "research_note":
                continue
            if c["role"] == "initial_state" and c["field"] == "value":
                nodes.add(c["object_id"])
            if c["role"] == "mechanism":
                parameters.add((c["object_id"], c["field"]))
            if c["role"] == "actor_brief" and c["object_id"] == actor_id:
                bits = c["field"].split("/")
                if len(bits) == 3 and bits[0] == "plans":
                    plans.setdefault(bits[1], set()).add(bits[2])
    node_rows = {n["nodeId"]: n for n in case["nodes"]}
    nodes = {
        n
        for n in nodes
        if n not in excluded
        and (
            node_rows[n]["visibility"] == "public"
            or node_rows[n].get("ownerActorId") == actor_id
        )
    }
    for _ in case["mechanisms"]:
        for mechanism in case["mechanisms"]:
            if mechanism["outputNodeId"] in excluded:
                continue
            if set(mechanism["inputNodeIds"]) <= nodes and all(
                (mechanism["mechanismId"], s) in parameters for s in _slots(mechanism)
            ):
                node = node_rows[mechanism["outputNodeId"]]
                if (
                    node["visibility"] == "public"
                    or node.get("ownerActorId") == actor_id
                ):
                    nodes.add(node["nodeId"])
    return {
        "actor": projection,
        "node_ids": sorted(nodes),
        "excluded_node_ids": sorted(excluded),
        "plan_ids": sorted(
            pid for pid, fields in plans.items() if {"value", "duePeriod"} <= fields
        ),
    }
