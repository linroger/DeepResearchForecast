"""Finite, source-aware forecast cases. No app imports or import-time I/O.

The case is numeric authority; simulation receives an allowlisted structural
projection. A caller must pin ``case_hash`` outside the case to authenticate a
read. Hashes detect changes, not the truth of evidence supplied by a producer.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
from datetime import date, datetime, timezone
from uuid import NAMESPACE_URL, uuid5

SCHEMA_VERSION = "forecast-case/v1"
AUTHORITY = "target-first-v1"
_MAX_BYTES = 8 * 1024 * 1024
_KINDS = {"growth", "sum", "product", "linear", "supply_demand", "adoption", "regulatory_milestone"}


class CaseValidationError(ValueError):
    """The case, its references, or its persisted identity is invalid."""


def _fail(where, message):
    raise CaseValidationError(f"{where}: {message}")


def _object(value, where, required=(), optional=()):
    if type(value) is not dict:
        _fail(where, "expected an object")
    missing = set(required) - value.keys()
    extra = value.keys() - set(required) - set(optional)
    if missing:
        _fail(where, "missing fields " + ", ".join(sorted(missing)))
    if extra:
        _fail(where, "unknown fields " + ", ".join(sorted(extra)))
    return value


def _text(value, where, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        _fail(where, "expected nonempty text" if not empty else "expected text")
    return value


def _number(value, where, *, low=None, high=None):
    if type(value) not in (int, float):
        _fail(where, "expected a finite number, not a boolean")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or (low is not None and value < low) or (high is not None and value > high):
        _fail(where, "number is nonfinite or outside bounds")
    return value


def _integer(value, where, minimum=0):
    if type(value) is not int or value < minimum:
        _fail(where, f"expected integer >= {minimum}")
    return value


def _boolean(value, where):
    if type(value) is not bool:
        _fail(where, "expected boolean")


def _enum(value, values, where):
    if not isinstance(value, str) or value not in values:
        _fail(where, "expected one of " + ", ".join(sorted(values)))


def _list(value, where):
    if type(value) is not list:
        _fail(where, "expected a list")
    return value


def _ids(value, where, registry=None):
    values = _list(value, where)
    for item in values:
        _text(item, where)
    if len(set(values)) != len(values):
        _fail(where, "duplicate reference")
    if registry is not None and set(values) - registry.keys():
        _fail(where, "unresolved reference")
    return values


def _date(value, where, *, timestamp=False, nullable=False):
    if value is None and nullable:
        return None
    _text(value, where)
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value)
        if timestamp:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None and "T" in value:
                return parsed.astimezone(timezone.utc).date()
    except (ValueError, OverflowError):
        pass
    _fail(where, "expected ISO date or timezone-aware timestamp" if timestamp else "expected ISO date")


def _url(value, where):
    from urllib.parse import urlsplit
    _text(value, where)
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username and not parsed.password:
            return
    except ValueError:
        pass
    _fail(where, "expected an HTTP(S) source URL without credentials")


def _json_copy(value):
    """Reject non-JSON objects, cycles, coercible keys and nonfinite numbers."""
    active = set()
    budget = [100000]

    def walk(item, depth=0):
        budget[0] -= 1
        if depth > 64 or budget[0] < 0:
            _fail("case", "JSON exceeds depth/item budget")
        if item is None or type(item) in (str, bool):
            return item
        if type(item) in (int, float):
            return _number(item, "case")
        if type(item) not in (dict, list):
            _fail("case", "only JSON objects, arrays and scalar values are accepted")
        if id(item) in active:
            _fail("case", "cyclic JSON object")
        active.add(id(item))
        if isinstance(item, dict):
            if any(type(key) is not str for key in item):
                _fail("case", "JSON keys must be strings")
            result = {key: walk(val, depth + 1) for key, val in item.items()}
        else:
            result = [walk(val, depth + 1) for val in item]
        active.remove(id(item))
        return result

    result = walk(value)
    if len(_canonical(result)) > _MAX_BYTES:
        _fail("case", "JSON exceeds byte budget")
    return result


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")


def _registry(rows, key, where):
    registry = {}
    for row in _list(rows, where):
        if type(row) is not dict:
            _fail(where, "expected object rows")
        identifier = _text(row.get(key), where + "." + key)
        if identifier in registry:
            _fail(where, "duplicate " + key)
        registry[identifier] = row
    return registry


def _predicate(value, nodes, where):
    if type(value) is not dict:
        _fail(where, "expected predicate object")
    op = value.get("operator")
    _enum(op, {"lt", "lte", "gt", "gte", "between"}, where)
    keys = ("nodeId", "operator", "low", "high") if op == "between" else ("nodeId", "operator", "value")
    _object(value, where, keys)
    _ids([value["nodeId"]], where, nodes)
    if op == "between":
        low = _number(value["low"], where)
        high = _number(value["high"], where)
        if low > high:
            _fail(where, "range low exceeds high")
        return low, high, True, True
    bound = _number(value["value"], where)
    return {"lt": (-math.inf, bound, False, False), "lte": (-math.inf, bound, False, True),
            "gt": (bound, math.inf, False, False), "gte": (bound, math.inf, True, False)}[op]


def _overlap(a, b):
    low, high = max(a[0], b[0]), min(a[1], b[1])
    if low < high:
        return True
    if low > high:
        return False
    return all((low > x[0] or x[2]) and (low < x[1] or x[3]) for x in (a, b))



def _resolution_contract(value, where):
    """Admit the explicit legacy adapter shape, without resolving an outcome.

    Snake_case is intentional here: forecast_extractor owns the existing
    source/series/market validators. This structural boundary never infers a
    contract from a node, the target settlement, or narrative text.
    """
    if type(value) is not dict:
        _fail(where, "expected a resolution contract object")
    kind = value.get("kind")
    _enum(kind, {"named_source_event", "official_data", "polymarket"}, where)
    if kind == "named_source_event":
        _object(value, where, ("kind", "publisher", "event", "deadline"), ("url",))
        _text(value["publisher"], where + ".publisher")
        _text(value["event"], where + ".event")
        _date(value["deadline"], where + ".deadline", timestamp=True)
        if "url" in value:
            _url(value["url"], where + ".url")
    elif kind == "official_data":
        _object(value, where, ("kind", "series", "comparator", "threshold", "period"), ("units", "transform"))
        _text(value["series"], where + ".series")
        _enum(value["comparator"], {">", ">=", "<", "<="}, where + ".comparator")
        _number(value["threshold"], where + ".threshold")
        # A year, quarter, month or day may be correct, depending on the
        # series' native frequency. That check belongs to the anchor validator.
        _text(value["period"], where + ".period")
        for key in ("units", "transform"):
            if key in value:
                _text(value[key], where + "." + key)
    else:
        _object(value, where, ("kind", "market_id", "equivalence"))
        _text(value["market_id"], where + ".market_id")
        _enum(value["equivalence"], {"exact"}, where + ".equivalence")


def _scenario_membership(value, scenarios, where):
    """Preserve explicit legacy scenario names; never guess a partition sum."""
    _object(value, where, ("derivable", "yes_scenarios"))
    _boolean(value["derivable"], where + ".derivable")
    yes_names = _ids(value["yes_scenarios"], where + ".yes_scenarios")
    if not value["derivable"]:
        if yes_names:
            _fail(where, "non-derivable membership requires empty yes_scenarios")
        return
    if not yes_names:
        _fail(where, "derivable membership requires at least one YES scenario")
    labels = [scenario["label"] for scenario in scenarios.values()]
    if len(set(labels)) != len(labels):
        _fail(where, "scenario labels must be unique for explicit membership")
    if set(yes_names) - set(labels):
        _fail(where, "yes_scenarios must reference existing scenario labels")


def _parameter(value, sources, where, inherited_basis, inherited_gap, inherited_sources):
    """Parameters are numeric scalars/vectors or bounded numeric priors."""
    if type(value) in (int, float):
        _number(value, where)
        return
    if type(value) is list:
        for item in value:
            _parameter(item, sources, where, inherited_basis, inherited_gap, inherited_sources)
        return
    _object(value, where, ("low", "high"), ("basis", "gap", "sourceIds"))
    low, high = _number(value["low"], where), _number(value["high"], where)
    if low > high:
        _fail(where, "parameter low exceeds high")
    basis = value.get("basis", inherited_basis)
    _enum(basis, {"observed", "estimated", "assumed"}, where)
    if basis == "assumed":
        _text(value.get("gap", inherited_gap), where + ".gap")
    effective_sources = value.get("sourceIds", inherited_sources)
    _ids(effective_sources, where, sources)
    if basis != "assumed" and not effective_sources:
        _fail(where, "observed/estimated parameter requires source provenance")


def validate_case(case):
    """Return an independent finite JSON case, or raise CaseValidationError.

    Unknown leaf nodes require an explicit bounded assumption (basis/gap).
    Assessment versions increase and every posterior delta must replay exactly
    from its predecessor. ``write_case`` additionally enforces persisted history.
    """
    case = _json_copy(case)
    _object(case, "case", ("schemaVersion", "caseId", "question", "asOf", "revision", "authority", "resolution",
                            "nodes", "sources", "claims", "mechanisms", "actors", "scenarios", "assessments", "binaries"))
    _enum(case["schemaVersion"], {SCHEMA_VERSION}, "schemaVersion")
    _enum(case["authority"], {AUTHORITY}, "authority")
    _text(case["caseId"], "caseId")
    _text(case["question"], "question")
    as_of = _date(case["asOf"], "asOf")
    _integer(case["revision"], "revision", 1)
    nodes = _registry(case["nodes"], "nodeId", "nodes")
    sources = _registry(case["sources"], "sourceId", "sources")
    claims = _registry(case["claims"], "claimId", "claims")
    actors = _registry(case["actors"], "actorId", "actors")
    mechanisms = _registry(case["mechanisms"], "mechanismId", "mechanisms")
    scenarios = _registry(case["scenarios"], "scenarioId", "scenarios")
    _registry(case["binaries"], "binaryId", "binaries")
    assessments = _registry(case["assessments"], "assessmentId", "assessments")
    if not nodes or not scenarios or not assessments:
        _fail("case", "nodes, scenarios and assessments must be nonempty")
    if "other" in scenarios:
        _fail("scenarios", "other is reserved for unmatched outcome mass")

    resolution = _object(case["resolution"], "resolution", ("targetNodeId", "horizon", "settlementSource", "units", "comparatorPolicy"))
    _ids([resolution["targetNodeId"]], "resolution.targetNodeId", nodes)
    if _date(resolution["horizon"], "resolution.horizon") < as_of:
        _fail("resolution.horizon", "forecast horizon precedes asOf")
    _text(resolution["units"], "resolution.units")
    _text(resolution["comparatorPolicy"], "resolution.comparatorPolicy")
    settlement = _object(resolution["settlementSource"], "settlementSource", ("name", "url", "releaseLagDays"))
    _text(settlement["name"], "settlementSource.name")
    _url(settlement["url"], "settlementSource.url")
    _integer(settlement["releaseLagDays"], "settlementSource.releaseLagDays")

    for sid, source in sources.items():
        _object(source, sid, ("sourceId", "url", "title", "publishedAt", "retrievedAt", "originCluster", "tier", "fetched", "passage"))
        if not re.fullmatch(r"S[1-9][0-9]*", sid):
            _fail(sid, "sourceId must use canonical S# form")
        _url(source["url"], sid)
        _text(source["title"], sid)
        published = _date(source["publishedAt"], sid + ".publishedAt", timestamp=True, nullable=True)
        retrieved = _date(source["retrievedAt"], sid + ".retrievedAt", timestamp=True)
        if retrieved > as_of or (published is not None and (published > as_of or published > retrieved)):
            _fail(sid, "source is unavailable at asOf or publication follows retrieval")
        if published is not None and "T" in source["publishedAt"] and "T" in source["retrievedAt"]:
            published_time = datetime.fromisoformat(source["publishedAt"].replace("Z", "+00:00"))
            retrieved_time = datetime.fromisoformat(source["retrievedAt"].replace("Z", "+00:00"))
            if published_time > retrieved_time:
                _fail(sid, "publication follows retrieval instant")
        _text(source["originCluster"], sid)
        _enum(source["tier"], {"primary", "secondary", "social", "unknown"}, sid)
        _boolean(source["fetched"], sid)
        _text(source["passage"], sid, empty=True)
        if source["fetched"] and not source["passage"].strip():
            _fail(sid, "fetched evidence requires a retained passage")

    writers = {}
    for mid, mechanism in mechanisms.items():
        _object(mechanism, mid, ("mechanismId", "kind", "outputNodeId", "inputNodeIds", "parameters", "basis", "sourceIds"), ("gap",))
        _enum(mechanism["kind"], _KINDS, mid)
        _ids([mechanism["outputNodeId"]], mid, nodes)
        _ids(mechanism["inputNodeIds"], mid, nodes)
        if mechanism["outputNodeId"] in writers:
            _fail(mid, "duplicate output writer")
        writers[mechanism["outputNodeId"]] = mechanism
        _enum(mechanism["basis"], {"observed", "estimated", "assumed"}, mid)
        _ids(mechanism["sourceIds"], mid, sources)
        if mechanism["basis"] == "assumed":
            _text(mechanism.get("gap"), mid + ".gap")
        elif not mechanism["sourceIds"]:
            _fail(mid, "observed/estimated mechanisms require source provenance")
        if "gap" in mechanism:
            _text(mechanism["gap"], mid, empty=True)
        if type(mechanism["parameters"]) is not dict:
            _fail(mid, "parameters must be an object")
        kind, count, params = mechanism["kind"], len(mechanism["inputNodeIds"]), mechanism["parameters"]
        expected = {"linear": {"coefficients", "intercept"}, "adoption": {"rate"},
                    "regulatory_milestone": {"milestonePeriod", "before", "after"}}.get(kind, set())
        if set(params) != expected:
            _fail(mid, "parameter keys do not match the declared template")
        if ((kind in {"growth", "supply_demand", "adoption"} and count != 2)
                or (kind in {"sum", "product", "linear"} and count == 0)
                or (kind == "regulatory_milestone" and count != 0)):
            _fail(mid, "input count does not match the declared template")
        if kind == "linear":
            coefficients = _list(params["coefficients"], mid)
            if len(coefficients) != count:
                _fail(mid, "linear needs one coefficient per input")
            if any(type(item) is list for item in coefficients):
                _fail(mid, "coefficients must be scalar parameters")
        for name, parameter in mechanism["parameters"].items():
            if isinstance(parameter, list) and name != "coefficients":
                _fail(mid, "only coefficients may be a parameter vector")
            _text(name, mid)
            _parameter(parameter, sources, mid + ".parameters." + name, mechanism["basis"], mechanism.get("gap"), mechanism["sourceIds"])
            if kind in {"adoption", "regulatory_milestone"} and name in {"rate", "milestonePeriod"}:
                bounds = [parameter["low"], parameter["high"]] if isinstance(parameter, dict) else [parameter]
                for bound in bounds:
                    _number(bound, mid, low=0, high=1 if name == "rate" else None)

    # Kahn traversal rejects cycles without recursion or dependence on row order.
    pending = set(writers)
    ready = set(nodes) - pending
    while pending:
        available = {node for node in pending if set(writers[node]["inputNodeIds"]) <= ready}
        if not available:
            _fail("mechanisms", "cyclic resolution graph")
        ready.update(available)
        pending.difference_update(available)

    def primary(ids):
        return any(sources[s]["fetched"] and sources[s]["tier"] == "primary" and sources[s]["passage"].strip() for s in ids)

    for nid, node in nodes.items():
        _object(node, nid, ("nodeId", "label", "units", "status", "value", "range", "vintage", "sourceIds", "claimIds", "sensitivity", "evidenceAvailability", "retrievalCost", "pivotal", "visibility"), ("ownerActorId", "basis", "gap", "resolution_contract"))
        if "resolution_contract" in node:
            _resolution_contract(node["resolution_contract"], nid + ".resolution_contract")
        _text(node["label"], nid)
        _text(node["units"], nid)
        _enum(node["status"], {"settled", "contested", "unknown"}, nid)
        _enum(node["visibility"], {"public", "private"}, nid)
        _boolean(node["pivotal"], nid)
        _number(node["sensitivity"], nid, low=0)
        _number(node["evidenceAvailability"], nid, low=0, high=1)
        if _number(node["retrievalCost"], nid, low=0) == 0:
            _fail(nid, "retrievalCost must be positive")
        _ids(node["sourceIds"], nid, sources)
        _ids(node["claimIds"], nid, claims)
        vintage = _date(node["vintage"], nid + ".vintage", nullable=True)
        if vintage is not None and vintage > as_of:
            _fail(nid, "node vintage follows asOf")
        if node["value"] is not None:
            _number(node["value"], nid)
        if node["range"] is not None:
            bounds = _object(node["range"], nid + ".range", ("low", "high"))
            low, high = _number(bounds["low"], nid), _number(bounds["high"], nid)
            if low > high:
                _fail(nid, "range low exceeds high")
            if node["value"] is not None:
                _number(node["value"], nid, low=low, high=high)
        elif node["value"] is None:
            _fail(nid, "numeric node needs a value or bounded range")
        if "ownerActorId" in node:
            _ids([node["ownerActorId"]], nid, actors)
        if node["visibility"] == "private" and not node.get("ownerActorId"):
            _fail(nid, "private node requires an ownerActorId")
        if "basis" in node:
            _enum(node["basis"], {"observed", "estimated", "assumed"}, nid)
        if "gap" in node:
            _text(node["gap"], nid)
        if node["status"] == "unknown" and nid not in writers:
            if node.get("basis") != "assumed" or node["range"] is None:
                _fail(nid, "unknown leaf requires bounded assumed basis")
            _text(node.get("gap"), nid + ".gap")
        if node["status"] == "settled":
            if node["value"] is None:
                _fail(nid, "settled node requires a value")
            if not node["sourceIds"] or vintage is None:
                _fail(nid, "settled node requires sources and vintage")
            if node["pivotal"] and not primary(node["sourceIds"]):
                _fail(nid, "pivotal settled node requires fetched primary evidence")
        for cid in node["claimIds"]:
            if claims[cid].get("nodeId") != nid:
                _fail(nid, "claim points to another node")
    if nodes[resolution["targetNodeId"]]["units"] != resolution["units"]:
        _fail("resolution", "target units mismatch")

    for cid, claim in claims.items():
        _object(claim, cid, ("claimId", "nodeId", "sourceIds", "passage", "status"))
        _ids([claim["nodeId"]], cid, nodes)
        _ids(claim["sourceIds"], cid, sources)
        _enum(claim["status"], {"verified", "reported", "contested", "unknown"}, cid)
        _text(claim["passage"], cid, empty=claim["status"] == "unknown")
        node = nodes[claim["nodeId"]]
        if cid not in node["claimIds"] or not set(claim["sourceIds"]) <= set(node["sourceIds"]):
            _fail(cid, "claim/node provenance links must agree")
        if claim["status"] != "unknown" and not claim["sourceIds"]:
            _fail(cid, "asserted claim requires source references")
        if claim["status"] == "verified":
            quote = " ".join(claim["passage"].split())
            supporting = [sid for sid in claim["sourceIds"] if sources[sid]["fetched"]
                          and quote in " ".join(sources[sid]["passage"].split())]
            if not supporting:
                _fail(cid, "verified claim requires its passage in fetched evidence")
            if node["pivotal"] and not primary(supporting):
                _fail(cid, "verified pivotal claim requires fetched primary evidence")
            if node["status"] == "unknown":
                _fail(cid, "unknown node cannot carry a verified claim")

    _validate_actors(actors, nodes, writers)
    intervals = []
    for sid, scenario in scenarios.items():
        _object(scenario, sid, ("scenarioId", "label", "predicate"))
        _text(scenario["label"], sid)
        interval = _predicate(scenario["predicate"], nodes, sid)
        for other, prior in intervals:
            # With independent dimensions, both one-dimensional regions can
            # hold simultaneously. A joint-region DSL is deliberately absent.
            if scenario["predicate"]["nodeId"] != other["predicate"]["nodeId"] or _overlap(interval, prior):
                _fail(sid, "scenario regions overlap")
        intervals.append((scenario, interval))
    _validate_assessments(case["assessments"], scenarios, nodes, sources, claims)
    for binary in case["binaries"]:
        _object(binary, "binary", ("binaryId", "question", "predicate", "probability", "sourceIds"), ("resolution_contract", "scenario_membership"))
        if "resolution_contract" in binary:
            _resolution_contract(binary["resolution_contract"], "binary.resolution_contract")
        if "scenario_membership" in binary:
            _scenario_membership(binary["scenario_membership"], scenarios, "binary.scenario_membership")
        _text(binary["question"], "binary.question")
        _predicate(binary["predicate"], nodes, "binary.predicate")
        _number(binary["probability"], "binary.probability", low=0, high=1)
        _ids(binary["sourceIds"], "binary.sourceIds", sources)
    return case


def _validate_actors(actors, nodes, writers):
    lever_ids = set()
    for aid, actor in actors.items():
        _object(actor, aid, ("actorId", "name", "decisionBasis", "objectives", "constraints", "levers", "decisionRule", "plans", "information", "credibility"))
        _text(actor["name"], aid)
        _text(actor["decisionBasis"], aid)
        _number(actor["credibility"], aid, low=0, high=1)
        _object(actor["constraints"], aid + ".constraints", ("capacity",))
        _number(actor["constraints"]["capacity"], aid, low=0)
        info = _object(actor["information"], aid + ".information", ("nodeIds", "releaseLagPeriods"))
        _ids(info["nodeIds"], aid, nodes)
        _integer(info["releaseLagPeriods"], aid)

        def visible(nid):
            _ids([nid], aid, nodes)
            if nodes[nid]["visibility"] == "private" and nodes[nid].get("ownerActorId") != aid:
                _fail(aid, "actor references another actor's private node")

        for nid in info["nodeIds"]:
            visible(nid)
        for objective in _list(actor["objectives"], aid):
            _object(objective, aid, ("nodeId", "direction", "weight"))
            visible(objective["nodeId"])
            _enum(objective["direction"], {"increase", "decrease"}, aid)
            _number(objective["weight"], aid, low=0)
        levers = _registry(actor["levers"], "leverId", aid)
        if not levers:
            _fail(aid, "cast membership requires a documented lever")
        for lid, lever in levers.items():
            _object(lever, lid, ("leverId", "nodeId", "minimum", "maximum", "cost", "lagPeriods", "reversible", "requiresConsent"))
            if lid in lever_ids:
                _fail(lid, "duplicate leverId across actors")
            lever_ids.add(lid)
            visible(lever["nodeId"])
            if lever["nodeId"] in writers:
                _fail(lid, "lever cannot overwrite a mechanism output")
            minimum, maximum = _number(lever["minimum"], lid), _number(lever["maximum"], lid)
            if minimum > maximum:
                _fail(lid, "lever minimum exceeds maximum")
            _number(lever["cost"], lid, low=0)
            _integer(lever["lagPeriods"], lid)
            _boolean(lever["reversible"], lid)
            _ids(lever["requiresConsent"], lid, actors)
            if aid in lever["requiresConsent"]:
                _fail(lid, "counterparty consent cannot name the acting owner")
        rule = _object(actor["decisionRule"], aid, ("kind", "cadencePeriods", "triggers"))
        _enum(rule["kind"], {"rule", "llm"}, aid)
        _integer(rule["cadencePeriods"], aid, 1)
        for trigger in _list(rule["triggers"], aid):
            _predicate(trigger, nodes, aid)
            visible(trigger["nodeId"])
            if trigger["nodeId"] not in info["nodeIds"]:
                _fail(aid, "trigger must belong to actor information set")
        plans = _registry(actor["plans"], "planId", aid)
        for pid, plan in plans.items():
            _object(plan, pid, ("planId", "leverId", "value", "duePeriod"), ("condition",))
            _ids([plan["leverId"]], pid, levers)
            lever = levers[plan["leverId"]]
            _number(plan["value"], pid, low=lever["minimum"], high=lever["maximum"])
            _integer(plan["duePeriod"], pid)
            if "condition" in plan:
                _predicate(plan["condition"], nodes, pid)
                visible(plan["condition"]["nodeId"])
                if plan["condition"]["nodeId"] not in info["nodeIds"]:
                    _fail(pid, "plan condition must belong to actor information set")


def _validate_assessments(rows, scenarios, nodes, sources, claims):
    previous = None
    version = 0
    for row in rows:
        where = row["assessmentId"]
        _object(row, where, ("assessmentId", "version", "kind", "scenarioWeights", "updates"), ("targetDistribution",))
        _integer(row["version"], where, 1)
        if row["version"] <= version:
            _fail(where, "assessment versions must strictly increase")
        version = row["version"]
        _enum(row["kind"], {"prior", "posterior"}, where)
        if (previous is None) != (row["kind"] == "prior"):
            _fail(where, "one initial prior must precede all posteriors")
        weights = row["scenarioWeights"]
        if type(weights) is not dict or not set(scenarios) <= weights.keys() or weights.keys() - set(scenarios) - {"other"}:
            _fail(where, "weights must name every scenario and optionally explicit other")
        for weight in weights.values():
            _number(weight, where, low=0, high=1)
        if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9, rel_tol=0):
            _fail(where, "weights must sum to one; unmatched mass requires explicit other")
        if "targetDistribution" in row:
            distribution = _object(row["targetDistribution"], where, (), ("mean", "median", "low", "high", "quantiles", "samples"))
            if not distribution:
                _fail(where, "targetDistribution must contain numeric summaries")
            for key in ("mean", "median", "low", "high"):
                if key in distribution:
                    _number(distribution[key], where)
            if ("low" in distribution) != ("high" in distribution):
                _fail(where, "distribution bounds require both low and high")
            if "low" in distribution and distribution["low"] > distribution["high"]:
                _fail(where, "distribution bounds reversed")
            if "samples" in distribution:
                for sample in _list(distribution["samples"], where):
                    _number(sample, where)
            if "quantiles" in distribution:
                if type(distribution["quantiles"]) is not dict:
                    _fail(where, "quantiles must be an object")
                quantiles = []
                for key, val in distribution["quantiles"].items():
                    try:
                        quantile = float(key)
                    except ValueError:
                        _fail(where, "quantile keys must be numeric probabilities")
                    _number(quantile, where, low=0, high=1)
                    quantiles.append((quantile, _number(val, where)))
                ordered = sorted(quantiles)
                if len({q for q, _ in ordered}) != len(ordered) or any(a[1] > b[1] for a, b in zip(ordered, ordered[1:])):
                    _fail(where, "quantiles must be unique and monotone")
        updates = _list(row["updates"], where)
        if previous is None:
            if updates:
                _fail(where, "initial prior cannot have posterior updates")
        else:
            running = dict(previous)
            seen = set()
            for update in updates:
                _object(update, where, ("evidenceId", "nodeId", "direction", "size", "oldWeight", "newWeight", "scenarioId", "reason"))
                _ids([update["nodeId"]], where, nodes)
                sid = update["scenarioId"]
                _text(sid, where)
                if sid not in weights:
                    _fail(where, "update scenario is unresolved")
                evidence = update["evidenceId"]
                _text(evidence, where)
                node = nodes[update["nodeId"]]
                if evidence in claims:
                    if claims[evidence]["nodeId"] != update["nodeId"] or claims[evidence]["status"] == "unknown":
                        _fail(where, "update evidence does not support its node")
                elif evidence not in sources or evidence not in node["sourceIds"]:
                    _fail(where, "update evidence is unresolved or unrelated to node")
                identity = (evidence, update["nodeId"], sid)
                if identity in seen:
                    _fail(where, "duplicate evidence update for scenario/node")
                seen.add(identity)
                _enum(update["direction"], {"increase", "decrease", "unchanged"}, where)
                old = _number(update["oldWeight"], where, low=0, high=1)
                new = _number(update["newWeight"], where, low=0, high=1)
                size = _number(update["size"], where, low=0, high=1)
                _text(update["reason"], where)
                delta = new - old
                direction = "increase" if delta > 0 else "decrease" if delta < 0 else "unchanged"
                if (not math.isclose(old, running.get(sid, 0), abs_tol=1e-9, rel_tol=0)
                        or direction != update["direction"] or not math.isclose(abs(delta), size, abs_tol=1e-9, rel_tol=0)):
                    _fail(where, "update ledger oldWeight/direction/size does not replay")
                running[sid] = new
            if any(not math.isclose(running.get(sid, 0), weights.get(sid, 0), abs_tol=1e-9, rel_tol=0) for sid in running.keys() | weights.keys()):
                _fail(where, "posterior weights do not match replayed update ledger")
        previous = weights


def case_hash(case):
    """Canonical full-case SHA-256; dict ordering/JSON whitespace do not matter."""
    return hashlib.sha256(_canonical(validate_case(case))).hexdigest()


def simulation_projection(case):
    """Engine-only input. Never pass this whole object to an actor provider.

    No assessments, binary weights, source passages, question or scenario labels
    cross this boundary. Predicates belong exclusively to outcome classification.
    The digest is of this projection, so probability-only edits cannot alter it.
    """
    case = validate_case(case)
    projection = {key: case[key] for key in ("schemaVersion", "caseId", "authority", "asOf")}
    projection["resolution"] = {key: case["resolution"][key] for key in ("targetNodeId", "horizon", "units")}
    projection["nodes"] = [{key: node[key] for key in ("nodeId", "units", "status", "value", "range", "vintage", "visibility", "ownerActorId", "basis") if key in node} for node in case["nodes"]]
    projection["mechanisms"] = [{key: mechanism[key] for key in ("mechanismId", "kind", "outputNodeId", "inputNodeIds", "parameters", "basis")} for mechanism in case["mechanisms"]]

    def parameters(value):
        if isinstance(value, dict):
            return {key: parameters(val) for key, val in value.items() if key not in {"gap", "sourceIds"}}
        if isinstance(value, list):
            return [parameters(val) for val in value]
        return value

    for mechanism in projection["mechanisms"]:
        mechanism["parameters"] = parameters(mechanism["parameters"])
    projection["actors"] = [{key: actor[key] for key in ("actorId", "objectives", "constraints", "levers", "decisionRule", "plans", "information", "credibility")} for actor in case["actors"]]
    projection["scenarios"] = [{"scenarioId": scenario["scenarioId"], "predicate": scenario["predicate"]} for scenario in case["scenarios"]]
    return projection


def report_projection(case):
    """Full authorized report input; the latest assessment is exact authority."""
    case = validate_case(case)
    return {**case, "caseHash": case_hash(case), "assessment": _json_copy(case["assessments"][-1]), "simulationWeight": 0.0}


def graph_projection(case):
    """Public graph API shape; private node rows and their edges are excluded."""
    case = validate_case(case)
    public = {row["nodeId"]: row for row in case["nodes"] if row["visibility"] == "public"}

    def uid(kind, *parts):
        return str(uuid5(NAMESPACE_URL, _canonical([case["caseId"], kind, *parts]).decode("ascii")))

    rows = [{"uuid": uid("node", nid), "name": node["label"], "labels": ["ForecastVariable"],
             "summary": f"{node['status']} variable in {node['units']}",
             "attributes": {key: node[key] for key in ("nodeId", "units", "status", "value", "range", "vintage", "sourceIds", "claimIds", "pivotal", "resolution_contract") if key in node}}
            for nid, node in public.items()]
    edges = []
    for mechanism in case["mechanisms"]:
        output = mechanism["outputNodeId"]
        for nid in mechanism["inputNodeIds"]:
            if nid in public and output in public:
                edges.append({"uuid": uid("edge", mechanism["mechanismId"], nid),
                              "source_node_uuid": uid("node", nid), "target_node_uuid": uid("node", output),
                              "name": mechanism["kind"], "fact": "Declared structural dependency",
                              "attributes": {"mechanismId": mechanism["mechanismId"], "basis": mechanism["basis"]}})
    for actor in case["actors"]:
        aid = actor["actorId"]
        # Public summaries never incorporate private plans or decision rationales.
        rows.append({"uuid": uid("actor", aid), "name": actor["name"], "labels": ["ForecastActor"],
                     "summary": "Holder of declared decision rights", "attributes": {"actorId": aid}})
        for lever in actor["levers"]:
            if lever["nodeId"] in public:
                edges.append({"uuid": uid("lever", lever["leverId"]), "source_node_uuid": uid("actor", aid),
                              "target_node_uuid": uid("node", lever["nodeId"]), "name": "CONTROLS",
                              "fact": "Declared lever ownership", "attributes": {"leverId": lever["leverId"]}})
    return {"schemaVersion": "forecast-graph/v1", "caseId": case["caseId"], "caseHash": case_hash(case), "nodes": rows, "edges": edges}


def _pairs(pairs):
    row = {}
    for key, value in pairs:
        if key in row:
            _fail("case file", "duplicate JSON object key")
        row[key] = value
    return row


def read_case(path, expected_hash=None):
    """Read a regular JSON file, rejecting duplicate keys and pinned-hash drift."""
    path = Path(path)
    if path.is_symlink():
        _fail("case file", "symlink files are not accepted")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            _fail("case file", "expected a regular file")
        payload = stream.read(_MAX_BYTES + 1)
    if len(payload) > _MAX_BYTES:
        _fail("case file", "JSON exceeds byte budget")
    try:
        case = validate_case(json.loads(payload, object_pairs_hook=_pairs))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise CaseValidationError("case file: malformed JSON") from exc
    digest = hashlib.sha256(_canonical(case)).hexdigest()
    if expected_hash is not None:
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            _fail("expected_hash", "expected lowercase SHA-256")
        if not hmac.compare_digest(digest, expected_hash):
            _fail("case file", "hash mismatch; stale or tampered case")
    return case


def _transition(old, new):
    for key in ("caseId", "authority", "question"):
        if old[key] != new[key]:
            _fail("case update", key + " is immutable; fork a new case")
    if new["revision"] <= old["revision"]:
        _fail("case update", "changed case requires increasing revision")
    if new["asOf"] < old["asOf"]:
        _fail("case update", "asOf cannot move backwards")
    for collection, id_key in (("sources", "sourceId"), ("claims", "claimId")):
        retained = {row[id_key]: row for row in new[collection]}
        for row in old[collection]:
            if retained.get(row[id_key]) != row:
                _fail("case update", "existing evidence is immutable; append a new source/claim identity")
    previous = old["assessments"]
    if len(new["assessments"]) < len(previous) or new["assessments"][:len(previous)] != previous:
        _fail("case update", "existing assessments are immutable; append a new version")
    if (old["scenarios"] != new["scenarios"] or old["resolution"] != new["resolution"]):
        if len(new["assessments"]) == len(previous):
            _fail("case update", "definition changes require a new assessment version")
        # Old weights remain meaningful only under the same definitions. A new
        # definition set therefore belongs to a new case file, preserving history.
        _fail("case update", "definition changes require a new revision file; do not rewrite historical definitions")


def write_case(path, case):
    """Atomically persist a validated case, with append-only assessment history.

    Concurrent writers fail visibly via an exclusive sibling lock. A process
    killed during a write may leave this lock for explicit operator recovery;
    it cannot silently bypass history checks. Parent directories must exist.
    """
    case = validate_case(case)
    payload = _canonical(case)
    digest = hashlib.sha256(payload).hexdigest()
    path = Path(path)
    lock = path.with_name(path.name + ".lock")
    try:
        lock_fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise CaseValidationError("case file: another writer or unrecovered write lock") from exc
    temporary = None
    try:
        os.close(lock_fd)
        if path.is_symlink():
            _fail("case file", "symlink files are not accepted")
        if path.exists():
            old = read_case(path)
            if _canonical(old) == payload:
                return digest
            _transition(old, case)
        fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        return digest
    finally:
        if temporary is not None:
            os.unlink(temporary)
        os.unlink(lock)
