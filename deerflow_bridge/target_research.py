"""Opt-in, evidence-bound research case production; no work occurs at import.

The existing engine owns model/tool budgets and gathering. This module admits
its structured findings, persists versioned cases, and renders their projections
without passing a finished report back through an extractor or frame repair.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import math
import re
import uuid

AUTHORITY = "target-first-v1"
RESEARCH_VERSION = 1


def _core():
    try:
        from . import forecast_case
    except ImportError:  # deployed bridge modules are siblings on sys.path
        import forecast_case
    return forecast_case


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _hash(value):
    return hashlib.sha256(_dump(value).encode()).hexdigest()


def _flat(value):
    return " ".join(str(value or "").split())


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) and ("T" not in value or parsed.tzinfo is None):
            return None
        return value
    except ValueError:
        return None


def _number_in(value, text):
    """Exact numeric token support, never substring '12' inside '312'."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return False
    return any(float(token.replace(",", "")) == value for token in
               re.findall(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?(?![\w.])", text))


def source_rows(rows):
    """Use recorded tool metadata, never an LLM's invented publisher/date."""
    result = []
    for row in rows:
        sid = row.get("sourceId") or (f"S{row['sid']}" if row.get("sid") else None)
        if not sid:
            raise ValueError("target source has no canonical S# identity")
        passages = row.get("passages") or []
        passage = row.get("passage") or "\n\n".join(
            p if isinstance(p, str) else str(p.get("text") or p.get("passage") or "") for p in passages)
        published = _date(row.get("publishedAt") or row.get("published_at"))
        retrieved = _date(row.get("retrievedAt") or row.get("retrieved_at") or row.get("fetched_at"))
        if not retrieved:
            raise ValueError(f"target source {sid} has no recorded retrieval date")
        tier = row.get("evidence_tier") or row.get("tier")
        if tier not in {"primary", "secondary", "social", "unknown"}:
            tier = "unknown"
        result.append({"sourceId": sid, "url": row["url"], "title": row.get("title") or row["url"],
                       "publishedAt": published, "retrievedAt": retrieved,
                       "originCluster": row.get("originCluster") or row.get("origin_cluster") or "unknown",
                       "tier": tier, "fetched": bool(row.get("fetched")), "passage": passage})
    return result


def _supported(claim, sources, *, pivotal=False):
    ids, quote = claim.get("sourceIds") or [], _flat(claim.get("passage"))
    if not ids or not quote or any(sid not in sources for sid in ids):
        return False
    matches = [sources[sid] for sid in ids if sources[sid]["fetched"]
               and quote in _flat(sources[sid].get("passage"))]
    return len(matches) == len(ids) and (not pivotal or any(s["tier"] == "primary" for s in matches))


def _parameter_leaves(parameters):
    for name, value in parameters.items():
        if isinstance(value, list):
            for index, item in enumerate(value):
                yield f"{name}.{index}", item
        else:
            yield name, value


def _mechanism_updates(case, payload, claims, sources):
    """Admit parameter updates with replayable, current-evidence bindings."""
    if "mechanismEvidence" in payload and "mechanisms" not in payload:
        raise ValueError("mechanismEvidence requires mechanisms")
    if "mechanisms" not in payload:
        return
    updated = copy.deepcopy(payload["mechanisms"])
    old = {m["mechanismId"]: m for m in case["mechanisms"]}
    if not isinstance(updated, list) or {m.get("mechanismId") for m in updated} != set(old):
        raise ValueError("mechanism updates must cover the existing resolution edges")
    bindings = {}
    for proof in payload.get("mechanismEvidence", []):
        required = {"mechanismId", "parameter", "claimIds", "sourceIds", "method"}
        if not isinstance(proof, dict) or not required <= proof.keys() or proof.keys() - required - {"operands"}:
            raise ValueError("invalid mechanism evidence binding fields")
        if any(not isinstance(proof[name], list) or not all(isinstance(v, str) and v for v in proof[name])
               or len(proof[name]) != len(set(proof[name])) for name in ("claimIds", "sourceIds")):
            raise ValueError("invalid mechanism evidence references")
        key = (proof["mechanismId"], proof["parameter"])
        if key in bindings:
            raise ValueError("duplicate mechanism evidence binding")
        bindings[key] = proof
    used = set()
    for mechanism in updated:
        mid = mechanism["mechanismId"]
        if any(mechanism.get(key) != old[mid].get(key) for key in ("kind", "outputNodeId", "inputNodeIds")):
            raise ValueError("mechanism structure changes require a new revision case")
        leaves = list(_parameter_leaves(mechanism["parameters"])) or [("", None)]
        for path, parameter in leaves:
            basis = parameter.get("basis", mechanism["basis"]) if isinstance(parameter, dict) else mechanism["basis"]
            if basis == "assumed":
                gap = parameter.get("gap", mechanism.get("gap")) if isinstance(parameter, dict) else mechanism.get("gap")
                if not gap or (parameter is not None and (not isinstance(parameter, dict) or
                        not {"low", "high"} <= parameter.keys())):
                    raise ValueError("unresolved mechanism parameters need explicit bounded assumptions and gaps")
                continue
            key = (mid, path)
            proof = bindings.get(key)
            if not proof or not proof["claimIds"] or not proof["sourceIds"]:
                raise ValueError("observed/estimated mechanism parameter lacks evidence binding")
            used.add(key)
            evidence = []
            for cid in proof["claimIds"]:
                claim = claims.get(cid)
                if (not claim or claim["status"] == "unknown" or claim["nodeId"] not in
                        [*mechanism["inputNodeIds"], mechanism["outputNodeId"]]
                        or not _supported(claim, sources, pivotal=True)):
                    raise ValueError("mechanism binding needs admitted primary node claims")
                if basis == "observed" and claim["status"] != "verified":
                    raise ValueError("observed parameter cannot use merely reported evidence")
                evidence.append(claim)
            claimed_sources = {sid for claim in evidence for sid in claim["sourceIds"]}
            if set(proof["sourceIds"]) != claimed_sources or not claimed_sources <= set(mechanism["sourceIds"]):
                raise ValueError("mechanism evidence/source links disagree")
            if isinstance(parameter, dict) and not claimed_sources <= set(parameter.get("sourceIds", mechanism["sourceIds"])):
                raise ValueError("parameter source links disagree")
            numbers = [] if parameter is None else ([parameter["low"], parameter["high"]]
                       if isinstance(parameter, dict) else [parameter])
            method = proof["method"]
            if method == "quoted":
                if proof.get("operands"):
                    raise ValueError("quoted mechanism binding cannot contain calculation operands")
                if any(not any(_number_in(number, claim["passage"]) for claim in evidence) for number in numbers):
                    raise ValueError("mechanism parameter number absent from admitted passages")
            elif method in {"ratio", "difference", "growth_rate"}:
                if basis == "observed":
                    raise ValueError("derived mechanism calculations must be labelled estimated")
                operands = proof.get("operands")
                if not isinstance(operands, list) or len(operands) != 2 or not numbers:
                    raise ValueError("mechanism calculation requires two sourced operands")
                values = []
                for operand in operands:
                    if not isinstance(operand, dict) or set(operand) != {"claimId", "value"}:
                        raise ValueError("invalid mechanism operand")
                    claim = next((c for c in evidence if c["claimId"] == operand["claimId"]), None)
                    if claim is None or not _number_in(operand["value"], claim["passage"]):
                        raise ValueError("mechanism operand is not in its admitted claim")
                    values.append(operand["value"])
                if method != "difference" and values[1] == 0:
                    raise ValueError("mechanism calculation divides by zero")
                computed = (values[0] - values[1] if method == "difference" else values[0] / values[1]
                            - (1 if method == "growth_rate" else 0))
                if any(not math.isclose(number, computed, rel_tol=1e-9, abs_tol=1e-12) for number in numbers):
                    raise ValueError("mechanism calculation does not reproduce its parameter")
            else:
                raise ValueError("unsupported mechanism binding method")
    if set(bindings) != used:
        raise ValueError("unconsumed mechanism evidence binding")
    case["mechanisms"] = updated


def build_case(plan, evidence, sources, *, question, as_of):
    """Admit typed findings against actual fetched passages, then validate.

    ``plan.forecastCase`` is the model-planned tree. ``evidence`` is a list of
    node findings or an object with findings, an assessment, and optional typed
    actors/binaries. No settled node is inferred from an unrelated numeric row.
    """
    case = copy.deepcopy(plan.get("forecastCase"))
    if not isinstance(case, dict):
        raise ValueError("target planning must supply forecastCase")
    if case.get("question") != question or case.get("asOf") != as_of:
        raise ValueError("target case question/asOf identity mismatch")
    if case.get("authority") != AUTHORITY:
        raise ValueError("target case authority mismatch")
    previous_sources = {s["sourceId"]: s for s in case.get("sources", [])}
    case["sources"] = source_rows(sources)
    for row in case["sources"]:
        old = previous_sources.get(row["sourceId"])
        if old:
            for key in ("url", "publishedAt", "originCluster", "tier"):
                if old[key] not in (None, "unknown") and old[key] != row[key]:
                    raise ValueError("target source provenance changed within the case")
    source_map = {s["sourceId"]: s for s in case["sources"]}
    nodes = {n["nodeId"]: n for n in case["nodes"]}
    claims = {c["claimId"]: c for c in case.get("claims", [])}
    payload = {"findings": evidence} if isinstance(evidence, list) else evidence
    if not isinstance(payload, dict):
        raise ValueError("target findings must be an object or list")
    allowed = {"findings", "assessment", "actors", "binaries", "scenarios", "mechanisms", "mechanismEvidence"}
    if payload.keys() - allowed:
        raise ValueError("unknown target evidence payload fields: " + ", ".join(sorted(payload.keys() - allowed)))
    by_node = {}
    for finding in payload.get("findings", []):
        item = copy.deepcopy(finding)
        if not isinstance(item, dict) or item.keys() - {"claimId", "nodeId", "sourceIds", "passage", "status", "value", "vintage"}:
            raise ValueError("unknown target finding fields")
        node_id = item.get("nodeId")
        if node_id not in nodes:
            raise ValueError("target finding references an unknown node")
        status = item.get("status")
        if status not in {"verified", "reported", "contested", "unknown"}:
            raise ValueError("target finding has invalid evidence status")
        claim_id = item.get("claimId")
        if not isinstance(claim_id, str) or not claim_id:
            raise ValueError("target finding needs a claimId")
        if status != "unknown" and not _supported(item, source_map):
            raise ValueError(f"target finding {claim_id} lacks its fetched passage")
        if status == "verified" and (not _supported(item, source_map, pivotal=nodes[node_id].get("pivotal"))
                or re.search(r"\b(?:estimat(?:e[ds]?|ion)|forecast[st]?|project(?:s|ed|ion)?|expects?|targets?)\b|预计|预测|估计|目标",
                             item.get("passage", ""), re.I)):
            item["status"] = "reported"
        if item.get("value") is not None and not _number_in(item["value"], item.get("passage", "")):
            raise ValueError(f"target finding {claim_id} numeric value absent from passage")
        if item.get("vintage") is not None:
            vintage = _date(item["vintage"])
            if not vintage or (vintage not in item.get("passage", "") and not any(
                    str(source_map[sid].get("publishedAt") or "").startswith(vintage)
                    for sid in item.get("sourceIds", []) if sid in source_map)):
                raise ValueError(f"target finding {claim_id} vintage lacks evidence")
        if claim_id in claims and claims[claim_id] != {key: item[key] for key in ("claimId", "nodeId", "sourceIds", "passage", "status")}:
            raise ValueError("target finding cannot overwrite an existing claim")
        claims[claim_id] = {key: item[key] for key in ("claimId", "nodeId", "sourceIds", "passage", "status")}
        by_node.setdefault(node_id, []).append(item)
    for node_id, findings in by_node.items():
        node = nodes[node_id]
        node["claimIds"] = list(dict.fromkeys([*node.get("claimIds", []), *(f["claimId"] for f in findings)]))
        node["sourceIds"] = list(dict.fromkeys([*node.get("sourceIds", []),
                                               *(s for f in findings for s in f.get("sourceIds", []))]))
        values = {f["value"] for f in findings if f.get("value") is not None and f["status"] != "unknown"}
        if node["status"] == "settled" and node.get("value") is not None:
            values.add(node["value"])
        elif node["status"] == "contested" and node.get("claimIds"):
            values.update((node["range"]["low"], node["range"]["high"]))
        grounded = [f for f in findings if f["status"] == "verified" and f.get("vintage")
                    and f.get("value") is not None]
        if len(values) > 1:
            node.update(status="contested", value=None, range={"low": min(values), "high": max(values)})
        elif grounded:
            value = grounded[0]["value"]
            node.update(status="settled", value=value, range={"low": value, "high": value},
                        vintage=grounded[0]["vintage"])
        elif any(f["status"] in {"contested", "verified"} for f in findings):
            node["status"] = "contested"
    case["claims"] = list(claims.values())
    for claim in case["claims"]:
        if claim["status"] != "unknown" and not _supported(claim, source_map,
                pivotal=claim["status"] == "verified" and nodes[claim["nodeId"]].get("pivotal")):
            raise ValueError("target case contains an unsupported claim")
    for node in case["nodes"]:
        if node["status"] == "settled":
            support = [claims[cid] for cid in node.get("claimIds", []) if cid in claims]
            if not node.get("vintage") or not any(c["status"] == "verified" and _supported(
                    c, source_map, pivotal=node.get("pivotal")) and _number_in(node.get("value"), c["passage"])
                    for c in support):
                raise ValueError(f"settled node {node['nodeId']} has no verified dated numeric evidence")
    _mechanism_updates(case, payload, claims, source_map)
    if "actors" in payload:
        case["actors"] = copy.deepcopy(payload["actors"])
    for actor in case.get("actors", []):
        for lever in actor.get("levers", []):
            proof = next((c for c in case["claims"] if c["nodeId"] == lever["nodeId"]
                          and c["claimId"] in actor["decisionBasis"] and _supported(c, source_map, pivotal=True)), None)
            if proof is None:
                raise ValueError("target actor decisionBasis must cite a primary claim for every lever")
    # Definitions are immutable within this case. A new definition set needs a
    # separate revision file (the core contract), never reinterpret old weights.
    if "scenarios" in payload and payload["scenarios"] != case["scenarios"]:
        raise ValueError("scenario definition changes require a new revision case; prior definitions are immutable")
    if payload.get("assessment") is not None:
        previous = case["assessments"][-1]
        new = copy.deepcopy(payload["assessment"])
        if new.get("kind") != "posterior" or new.get("version") != previous["version"] + 1:
            raise ValueError("target posterior must append the next assessment version")
        if any(new.get("assessmentId") == old["assessmentId"] for old in case["assessments"]):
            raise ValueError("target assessment identity already exists")
        for update in new.get("updates", []):
            claim = claims.get(update.get("evidenceId"))
            if not claim or claim["status"] == "unknown" or claim["nodeId"] != update.get("nodeId"):
                raise ValueError("target assessment update needs admitted node evidence")
        case["assessments"].append(new)
    if "binaries" in payload:
        case["binaries"] = copy.deepcopy(payload["binaries"])
    for binary in case["binaries"]:
        for scenario in case["scenarios"]:
            if binary["predicate"] == scenario["predicate"] and not math.isclose(
                    binary["probability"], case["assessments"][-1]["scenarioWeights"][scenario["scenarioId"]], abs_tol=1e-9):
                raise ValueError("binary probability conflicts with the assessment of the same predicate")
    return _core().validate_case(case)


def research_priorities(case):
    """Sensitivity x remaining uncertainty x evidence availability / cost."""
    source_map = {s["sourceId"]: s for s in case["sources"]}
    result = []
    for node in case["nodes"]:
        origins = {source_map[s]["originCluster"] for s in node.get("sourceIds", [])
                   if s in source_map and source_map[s]["fetched"] and source_map[s]["originCluster"] != "unknown"}
        uncertainty = 1.0 if node["status"] != "settled" else (0.5 if len(origins) < 2 else 0.0)
        bounds = node.get("range") or {}
        if bounds and bounds["high"] != bounds["low"]:
            uncertainty = max(uncertainty, min(1.0, abs(bounds["high"] - bounds["low"]) /
                                               max(abs(bounds["high"]), abs(bounds["low"]), 1e-12)))
        if uncertainty == 0:
            continue
        result.append({"nodeId": node["nodeId"], "label": node["label"], "status": node["status"],
                       "pivotal": node.get("pivotal", False), "independentOrigins": len(origins),
                       "uncertainty": uncertainty, "score": node["sensitivity"] * uncertainty *
                       node["evidenceAvailability"] / node["retrievalCost"],
                       "reason": "numeric conflict" if node["status"] == "contested" else
                       "unresolved node" if node["status"] == "unknown" else "single or unknown origin"})
    return sorted(result, key=lambda r: (-r["score"], not r["pivotal"], r["nodeId"]))


def _actor_additions(current, additions):
    """Gathering may add sourced candidates; it cannot silently erase a prior one."""
    if not isinstance(additions, list):
        raise ValueError("target candidate actors must be a list")
    actors = {actor["actorId"]: copy.deepcopy(actor) for actor in current}
    seen = set()
    for actor in additions:
        if not isinstance(actor, dict) or not isinstance(actor.get("actorId"), str) or actor["actorId"] in seen:
            raise ValueError("invalid target candidate actor identity")
        aid = actor["actorId"]
        seen.add(aid)
        if aid in actors and actors[aid] != actor:
            raise ValueError("target candidate actor cannot overwrite an admitted candidate")
        actors[aid] = copy.deepcopy(actor)
    return list(actors.values())


def render_case_research(case):
    case = _core().validate_case(case)
    resolution = case["resolution"]
    lines = [f"# {case['question']}", "", f"Authority: {AUTHORITY}; case {case['caseId']}; revision {case['revision']}.",
             f"Information as of {case['asOf']}. Target: {resolution['targetNodeId']} ({resolution['units']}); "
             f"horizon {resolution['horizon']}.", "", "## Resolution and evidence policy",
             f"Settlement: {resolution['settlementSource']['name']} ({resolution['settlementSource']['url']}); "
             f"release lag {resolution['settlementSource']['releaseLagDays']} days.", resolution['comparatorPolicy'],
             "Unknown and contested nodes remain explicit. Publication dates are distinct from retrieval dates. "
             "A shared or unknown origin does not provide independent corroboration. Mechanism assumptions are "
             "diagnostic inputs, and simulation carries zero weight in the research assessment.", "", "## Resolution nodes"]
    for n in case["nodes"]:
        lines.append(f"- {n['nodeId']} — {n['label']}: {n['status']}; value={n.get('value')}; "
                     f"range={_dump(n.get('range'))}; units={n['units']}; vintage={n.get('vintage') or 'unknown'}; "
                     f"basis={n.get('basis', 'derived' if n['status'] != 'settled' else 'observed')}. "
                     + str(n.get("gap") or "") + " " + " ".join(f"[{s}]" for s in n["sourceIds"]))
    lines += ["", "## Mechanism parameters and evidence bases"]
    for mechanism in case["mechanisms"]:
        lines.append(f"- {mechanism['mechanismId']} ({mechanism['kind']}): {_dump(mechanism['parameters'])}; "
                     f"basis={mechanism['basis']}; gap={mechanism.get('gap') or 'none'}; "
                     + " ".join(f"[{sid}]" for sid in mechanism['sourceIds']))
    lines += ["", "## Findings and conflicting evidence"]
    for c in case["claims"]:
        lines.append(f"- {c['claimId']} → {c['nodeId']} ({c['status']}): {c['passage']} "
                     + " ".join(f"[{s}]" for s in c["sourceIds"]))
    for a in case["assessments"]:
        lines += ["", f"## {a['kind'].title()} assessment {a['assessmentId']} (version {a['version']})"]
        lines += [f"- {key}: {value:.6g}" for key, value in a["scenarioWeights"].items()]
        for update in a.get("updates", []):
            lines.append(f"- {update['evidenceId']} → {update['nodeId']} → {update['scenarioId']}: "
                         f"{update['oldWeight']} → {update['newWeight']} ({update['direction']}, "
                         f"size {update['size']}): {update['reason']}")
    lines += ["", "## Remaining evidence priorities"]
    lines += [f"- {p['nodeId']}: {p['reason']}; value of information score {p['score']:.6g}; "
              f"independent origins {p['independentOrigins']}." for p in research_priorities(case)] or ["- No unresolved priorities."]
    lines += ["", "## Sources"]
    for s in case["sources"]:
        lines += [f"- [{s['sourceId']}] {s['title']} — {s['url']}; publication {s['publishedAt'] or 'unknown'}; "
                  f"retrieval {s['retrievedAt']}; origin {s['originCluster']}; {s['tier']}; fetched={s['fetched']}."]
    return "\n".join(lines) + "\n"


# This describes the frozen producer contract to the model. It is intentionally
# local to this opt-in route, rather than changing the legacy planner prompts.
CASE_INSTRUCTIONS = """Return {"forecastCase": <forecast-case/v1 object>} for the exact question/asOf below.
Required case fields: schemaVersion='forecast-case/v1', authority='target-first-v1', caseId, question,
asOf (ISO date), revision=1, resolution, nodes, sources, claims, mechanisms, actors, scenarios,
assessments, binaries. resolution={targetNodeId,horizon (ISO date),settlementSource:{name,url,releaseLagDays},
units,comparatorPolicy}. Derive target, settlement source/calendar, accounting identities, drivers and
observable indicators from the actual question. Never fabricate a target from incidental numbers.
Each node={nodeId,label,units,status:unknown|contested|settled,value:number|null,range:{low,high},
vintage:ISO date|null,sourceIds:[],claimIds:[],sensitivity:nonnegative,evidenceAvailability:0..1,
retrievalCost:positive,pivotal:bool,visibility:public|private,basis:assumed|estimated|observed,gap:text}.
An unobserved input has finite bounded assumptions, basis='assumed', and explicit gap. Initial sourceIds
and claimIds are empty: scout snippets do not settle facts. Sources and claims start empty. Actors start
empty until documented levers are fetched. Every used numeric parameter needs a bounded range.
mechanisms=[{mechanismId,kind,outputNodeId,inputNodeIds,parameters,basis,sourceIds,gap}].
Use sum/product (any inputs), growth (base, fractional rate), linear (one or more inputs; coefficients list matching input count, intercept),
supply_demand (supply,demand, no parameters), adoption (current,capacity; rate parameter), or
regulatory_milestone (no inputs; milestonePeriod,before,after parameters). No expressions or cycles.
All unobserved numeric mechanism parameters use {low,high,basis:'assumed',gap}, including coefficient
array elements. Do not supply claimed source evidence, actors or settled nodes in this fresh plan.
scenarios=[{scenarioId,label,predicate:{nodeId,operator:lt|lte|gt|gte|between,value OR low/high}}].
Predicates must not overlap. assessments=[{assessmentId,version:1,kind:'prior',scenarioWeights:{scenarioId:0..1},
updates:[]}]. Weights sum to one; this prior may be revised by evidence. binaries may be empty.
No settled numeric facts without fetched primary passages and dates. If target/settlement cannot be
identified, fail visibly rather than substituting a generic tree. Keep the case compact and load-bearing.
"""


def _engine_sources(engine, rows=None):
    # The gateway stores selected passages; do not replace them with a page's
    # opening N characters. Verify that every stored passage still belongs to
    # the pinned fetched page before exposing it to another model phase.
    rows = engine.ledger.rows() if rows is None else rows
    for row in rows:
        if row.get("fetched"):
            page = engine.tools.page_text(row["sid"])
            if page is None:
                raise ValueError("target source stored page is missing or changed")
            rg = __import__(engine.tools.__class__.__module__, fromlist=["neutralize_instructions"])
            page = rg.neutralize_instructions(rg.neutralize_citation_markers(page))
            for p in row.get("passages") or []:
                text = p if isinstance(p, str) else p.get("text") or p.get("passage") or ""
                # Selectors can join nonadjacent passages with an ellipsis.
                for fragment in re.split(r"(?:^|\n)\s*(?:…|\.\.\.)\s*(?:\n|$)|\n\s*\n", text):
                    if _flat(fragment) and _flat(fragment) not in _flat(page):
                        raise ValueError("target source passage differs from pinned page")
    return source_rows(rows)


def _kiqs(engine, case, *, round_no=0, limit=None):
    # Import lazily to avoid changing the standalone bridge import graph.
    lr = __import__(engine.__class__.__module__, fromlist=["Kiq"])
    priorities = research_priorities(case)
    cap = limit if limit is not None else engine.preset.max_kiqs
    selected = priorities[:max(0, cap - (1 if round_no == 0 else 0))]
    settlement = case["resolution"]["settlementSource"]
    rows = []
    for p in selected:
        question = (f"For resolution node {p['nodeId']} ({p['label']}), resolve {p['reason']}. "
                    f"Find dated values, vintages, direct quotations and conflicting observations in {case['resolution']['units']} "
                    f"where applicable. Confirm settlement release calendar with {settlement['name']}.")
        rows.append(lr.Kiq(id=f"G{round_no}F{len(rows)+1}" if round_no else f"K{len(rows)+1}",
                           question=question, queries=[f"{settlement['name']} {p['label']} release",
                           f"{p['label']} primary data conflicting estimates"], kind="data", round=round_no,
                           why=f"Node {p['nodeId']}; VOI {p['score']:.6g}; {p['reason']}."))
    if round_no == 0:
        leading = max(case["assessments"][-1]["scenarioWeights"], key=case["assessments"][-1]["scenarioWeights"].get)
        hypothesis = next((s for s in case["scenarios"] if s["scenarioId"] == leading), {"label": "other"})
        rows.append(lr.Kiq(id=f"K{len(rows)+1}", question=("Adversarial evidence: find the strongest primary-source "
            "evidence against the leading prior scenario and the resolution tree's assumptions. Identify omitted "
            "drivers, contradictory numbers, common original publishers behind syndicated sources, and negative evidence. "
            "Bind each finding to a node or an explicit modeling gap. Leading hypothesis: " + _dump(hypothesis)),
            queries=[f"{engine.question} contrary evidence", f"{engine.question} revisions limitations"],
            why="Mandatory independent adversarial retrieval; initial scenario weights are revisable."))
    return rows


def execute_target(engine):
    """Production _Engine hook: plan → node agents → findings → assessment → artifacts."""
    core = _core()
    anchor_control = getattr(engine, "world_anchor_control", None)
    anchor = None
    folder = engine.work / "target"
    folder.mkdir(exist_ok=True)
    binding = engine.state._data.setdefault("targetResearch", {})
    if "caseId" not in binding:
        if any(key in binding for key in ("plan", "assessed", "finalCaseHash")):
            raise ValueError("saved target generation lacks producer case identity; cannot relabel accepted case")
        binding["caseId"] = "case_" + uuid.uuid4().hex
        engine.state.save()
    if not re.fullmatch(r"case_[a-f0-9]{32}", str(binding["caseId"])):
        raise ValueError("invalid producer case identity")
    case_id = binding["caseId"]
    authenticated = set()
    library_path = engine.out_dir / "target_library.json"
    library_bytes = library_path.read_bytes() if library_path.is_file() and not library_path.is_symlink() else None
    if library_path.is_symlink():
        raise ValueError("target library context cannot be a symlink")
    library_hash = hashlib.sha256(library_bytes).hexdigest() if library_bytes is not None else None
    if "libraryHash" in binding and binding["libraryHash"] != library_hash:
        raise ValueError("target library context changed after first use")
    binding["libraryHash"] = library_hash
    engine.state.save()
    library_context = ""
    if library_bytes is not None:
        if len(library_bytes) > 4 * 1024 * 1024:
            raise ValueError("target library context too large")
        library = json.loads(library_bytes)
        if (not isinstance(library, dict) or library.get("schemaVersion") != "target-library-context/v1"
                or library.get("authority") != "prior_context_only" or not isinstance(library.get("entries"), list)):
            raise ValueError("invalid target library context")
        cutoff = dt.datetime.combine(dt.date.fromisoformat(engine.plan.as_of), dt.time.max, dt.timezone.utc)
        def available(value):
            parsed = _date(value)
            if parsed is None:
                return False
            instant = (dt.datetime.combine(dt.date.fromisoformat(parsed), dt.time.max, dt.timezone.utc)
                       if len(parsed) == 10 else dt.datetime.fromisoformat(parsed.replace("Z", "+00:00")))
            return instant <= cutoff
        entries = [row for row in library["entries"] if isinstance(row, dict)
                   and available(row.get("availableAt")) and available(row.get("asOf"))]
        library_context = ("\nPRIOR LIBRARY CONTEXT ONLY: these are historical planning hypotheses, not current "
                           "fetched evidence or current claims. Preserve original provenance/gaps. Current source "
                           "lookup is required before any verified claim or parameter binding.\n" +
                           engine.delimit("PRIOR LIBRARY", _dump(entries)))

    def check_library():
        if library_path.is_symlink():
            raise ValueError("target library context changed after first use")
        current_bytes = library_path.read_bytes() if library_path.is_file() else None
        current_hash = hashlib.sha256(current_bytes).hexdigest() if current_bytes is not None else None
        if current_hash != binding["libraryHash"]:
            raise ValueError("target library context changed after first use")

    def continuation_sources(case):
        if _hash(case) not in authenticated:
            raise ValueError("retained passages require an authenticated case checkpoint")
        core.validate_case(case)
        current = _engine_sources(engine)
        by_id = {row["sourceId"]: row for row in current}
        gateway = __import__(engine.tools.__class__.__module__, fromlist=["neutralize_instructions"])
        for prior in case["sources"]:
            retained = prior.get("passage") or ""
            if not retained:
                continue
            source = by_id.get(prior["sourceId"])
            if source is None or not source["fetched"]:
                raise ValueError("retained source is no longer fetched")
            page = engine.tools.page_text(int(prior["sourceId"][1:]))
            if page is None:
                raise ValueError("retained original page is missing")
            page = gateway.neutralize_instructions(gateway.neutralize_citation_markers(page))
            for fragment in re.split(r"(?:^|\n)\s*(?:…|\.\.\.)\s*(?:\n|$)|\n\s*\n", retained):
                if _flat(fragment) and _flat(fragment) not in _flat(page):
                    raise ValueError("retained passage is absent from its pinned original page")
            if retained not in source["passage"]:
                source["passage"] = retained + "\n\n" + source["passage"]
        return current

    def pin_sources():
        """Pin every fetched generation before its next model consumer.

        New sources may be appended after a partial checkpoint. Consumed page
        bytes, dates, tiers and origins cannot change, including on partial
        restart; rotating the selected-passage cache does not change identity.
        """
        with engine.state._lock:
            snapshot = engine.ledger.rows()
            rows = {f"S{r['sid']}": r for r in snapshot}
            current = {}
            for source in _engine_sources(engine, snapshot):
                if source["fetched"]:
                    identity = {k: v for k, v in source.items() if k != "passage"}
                    identity["content_sha256"] = rows[source["sourceId"]].get("content_sha256")
                    current[source["sourceId"]] = _hash(identity)
            previous = binding.get("sourceBindings", {})
            if any(current.get(sid) != value for sid, value in previous.items()):
                raise ValueError("target source evidence identity changed since consumed checkpoint")
            binding["sourceBindings"] = {**previous, **current}
            engine.state.save()

    engine.target_pin_sources = pin_sources
    pin_sources()

    def checkpoint(name, producer):
        check_library()
        path = folder / f"{name}.json"
        if name in binding:
            if not path.is_file():
                raise ValueError(f"target checkpoint missing: {name}")
            data = json.loads(path.read_text("utf-8"))
            if _hash(data) != binding[name]:
                raise ValueError(f"target checkpoint changed: {name}")
            if data.get("caseId") != case_id:
                raise ValueError("target checkpoint case identity mismatch")
            core.validate_case(data)
            authenticated.add(_hash(data))
            return data
        data = producer()
        pin_sources()
        engine.write_json(path, data)
        if data.get("caseId") != case_id:
            raise ValueError("target producer changed its pinned case identity")
        binding[name] = _hash(data)
        engine.state.save()
        authenticated.add(_hash(data))
        return data

    def plan_case():
        with engine.phase("target_plan") as deadline:
            anchor_instructions = ""
            if anchor_control is not None:
                if __package__:
                    from .world_anchor_binding import TARGET_IDENTITIES_INSTRUCTIONS, validate_target_declaration
                    from .world_anchor import anchor_hash
                else:
                    from world_anchor_binding import TARGET_IDENTITIES_INSTRUCTIONS, validate_target_declaration
                    from world_anchor import anchor_hash
                anchor_instructions = TARGET_IDENTITIES_INSTRUCTIONS
            raw = engine.json_call(["Revisable initial planning context: " + _dump(engine.plan.to_dict())], "TARGET CASE PLANNING TASK\n" + CASE_INSTRUCTIONS + anchor_instructions +
                    "\nProducer-owned opaque caseId (use exactly): " + case_id +
                    "\nQuestion: " + engine.question + "\nasOf: " + engine.plan.as_of + library_context,
                    label="target:plan", required=("forecastCase", "worldAnchorIdentities") if anchor_control is not None else ("forecastCase",), deadline=deadline)
            if set(raw) != ({"forecastCase", "worldAnchorIdentities"} if anchor_control is not None else {"forecastCase"}):
                raise ValueError("unknown target planning response fields")
            candidate = raw.get("forecastCase")
            if not isinstance(candidate, dict):
                raise ValueError("target planning must supply forecastCase")
            if (candidate.get("sources") or candidate.get("claims") or any(
                    n.get("status") == "settled" or n.get("sourceIds") or n.get("claimIds") or n.get("vintage")
                    for n in candidate.get("nodes", []))):
                raise ValueError("fresh target planning cannot supply evidence or settled nodes")
            for mechanism in candidate.get("mechanisms", []):
                if mechanism.get("basis") != "assumed" or mechanism.get("sourceIds"):
                    raise ValueError("fresh planning mechanisms cannot claim current evidence")
                for _, parameter in _parameter_leaves(mechanism.get("parameters", {})):
                    if (not isinstance(parameter, dict) or not {"low", "high"} <= parameter.keys()
                            or parameter.get("basis", "assumed") != "assumed" or parameter.get("sourceIds")):
                        raise ValueError("fresh planning mechanisms require explicit bounded assumptions")
            candidate["caseId"] = case_id
            case = build_case(raw, [], _engine_sources(engine), question=engine.question, as_of=engine.plan.as_of)
            if len(case["assessments"]) != 1 or case["assessments"][0]["kind"] != "prior":
                raise ValueError("target plan must freeze exactly one prior assessment")
            if anchor_control is not None:
                identities = raw["worldAnchorIdentities"]
                validate_target_declaration(identities)
                engine.write_json(folder / "world_anchor_identities.json", identities)
                binding["anchorIdentityHash"] = anchor_hash(identities)
            engine.state.set_phase("target_plan", "done")
            return case

    if "assessed" in binding and binding.get("sourceEvidenceHash") != _hash(_engine_sources(engine)):
        raise ValueError("target source evidence identity changed after assessment")
    case = core.validate_case(checkpoint("plan", plan_case))
    if case["question"] != engine.question or case["asOf"] != engine.plan.as_of:
        raise ValueError("target saved plan identity mismatch")
    # Target briefs deliberately omit legacy frame instructions and probabilities.
    engine.brief = (f"Target-led research. Question: {engine.question}\nasOf: {case['asOf']}\n"
                    f"Resolution: {_dump(case['resolution'])}\nNodes: {_dump(case['nodes'])}\n"
                    "Follow the evidence. Challenge the initial frame; missing evidence stays unknown.")
    engine.kiqs = _kiqs(engine, case)
    if "assessed" not in binding and "mechanisms" not in binding:
        engine.phase_data()

    def gather_case(round_no, current, kiqs):
        engine.kiqs.extend(k for k in kiqs if k.id not in {x.id for x in engine.kiqs})
        engine._load_records(kiqs, retry_cut_short=True)
        pending = [k for k in kiqs if k.id not in engine.records]
        with engine.phase("gather" if round_no == 0 else "gap") as deadline:
            if pending:
                summary = engine.gather_kiqs(pending, deadline)
                if summary["provider_error"] is not None:
                    raise summary["provider_error"]
            sources = continuation_sources(current)
            pin_sources()
            task = ("TARGET FINDINGS TASK\nReturn {\"findings\": [...]} from "
                "the supplied node investigations and fetched passages. Each finding has claimId (unique), nodeId, "
                "sourceIds, passage (exact source quote), status verified|reported|contested|unknown, optional numeric "
                "value and ISO vintage. A value must appear literally in the passage; vintage must be in the passage "
                "or publication metadata. Never label projections/estimates as observed or verified. Pivotal verified "
                "claims require fetched primary evidence. Sources with missing metadata remain unknown. Name the "
                "node only when the evidence answers its exact metric/period/units; do not attach incidental numbers. "
                "Existing claims are immutable; emit only new claims. Include adversarial/conflicting findings. "
                "No evidence yields an empty list, never invented facts.\nExisting claims: " + _dump(current["claims"]) +
                "\nInvestigations: " + engine.delimit("NODE INVESTIGATIONS", _dump([engine.records[k.id] for k in kiqs
                    if k.id in engine.records])) + "\nSources: " + engine.delimit("FETCHED PASSAGES", _dump(sources)))
            if anchor_control is not None:
                task += ("\nWORLD ANCHOR CANDIDATE ACTORS: You may additionally return actors:[...] using the closed "
                    "forecast-case Actor shape: actorId,name,decisionBasis,objectives,constraints:{capacity},"
                    "levers:[{leverId,nodeId,minimum,maximum,cost,lagPeriods,reversible,requiresConsent}],"
                    "decisionRule:{kind,cadencePeriods,triggers},plans,information:{nodeIds,releaseLagPeriods},credibility. "
                    "Each lever must target an existing primitive node, with a fetched primary claim ID in decisionBasis. "
                    "Supply every quantity only when its precise meaning/unit is documented in those sources. "
                    "Authority must be explicitly documented, not inferred from a name or interest. "
                    "Do not invent utility weights, triggers, plans or rights; empty objectives/triggers/plans are allowed. "
                    "A candidate remains untrusted until the anchor independently reviews quantities and authority. "
                    "Keep existing actors; omit actors when the evidence justifies no addition. No actor changes occur after binding.")
                task += "\nExisting actor registry: " + _dump(current["actors"])
            raw = engine.json_call([engine.brief], task,
                label=f"target:findings:{round_no}", required=("findings",), deadline=deadline)
            allowed_fields = {"findings", "actors"} if anchor_control is not None else {"findings"}
            if "findings" not in raw or set(raw) - allowed_fields:
                raise ValueError("unknown target findings response fields")
            if anchor_control is not None and "actors" in raw:
                raw = {**raw, "actors": _actor_additions(current["actors"], raw["actors"])}
            updated = build_case({"forecastCase": current}, raw, sources,
                                 question=engine.question, as_of=engine.plan.as_of)
            engine.write_json(folder / f"findings-{round_no}.json", raw)
            engine.state.set_phase("gather" if round_no == 0 else "gap", "done")
            return updated

    # Once parameters are bound, partial resume retries only assessment. A new
    # research generation must be explicit; never reopen gaps then restore an
    # older mechanism checkpoint over their newly admitted findings.
    if "assessed" not in binding and "mechanisms" not in binding:
        case = checkpoint("gather-0", lambda: gather_case(0, case, list(engine.kiqs)))
        for number in range(1, engine.preset.gap_rounds + 1):
            priorities = research_priorities(case)
            if not priorities:
                break
            capacity, _ = engine._followup_capacity()
            name = f"gather-{number}"
            if name not in binding and (capacity <= 0 or not engine.optional_allowed(4000, engine.deadline,
                                                                                   keep_reserve=True, min_seconds=30)):
                break
            followups = _kiqs(engine, case, round_no=number,
                             limit=min(engine.preset.followups_per_round, capacity))
            if not followups and name not in binding:
                break
            case = checkpoint(name, lambda: gather_case(number, case, followups))
    if anchor_control is not None:
        anchor = engine.run_anchor_stage(case=case)
        pin_sources()
    engine._seal_context()

    def bind_mechanisms():
        pin_sources()
        if anchor is not None:
            if __package__:
                from .world_anchor_case import apply_anchors_to_case
            else:
                from world_anchor_case import apply_anchors_to_case
            compiled = apply_anchors_to_case(case, pack=anchor["pack"], requirements=anchor["requirements"],
                index=anchor["index"], policy=anchor["policy"])
            proof = {"schema_version": "world-anchor-case-compilation/v1", "pack_hash": anchor["manifest"]["pack_hash"],
                "contract_hash": anchor["pack"]["contract_hash"], "mechanisms": compiled["mechanisms"]}
            engine.write_json(folder / "mechanism-bindings.json", proof)
            binding["mechanismEvidenceHash"] = _hash(proof)
            engine.state.set_phase("target_mechanisms", "done", "World Anchor deterministic compilation")
            return compiled
        with engine.phase("target_mechanisms") as deadline:
            task = ("TARGET MECHANISM BINDING TASK\nReturn {\"mechanisms\": [...], \"mechanismEvidence\": [...]} "
                "covering every existing mechanism ID without changing kind/inputNodeIds/outputNodeId. Use only the "
                "admitted claims below; no report extraction. Update parameters from evidence, not scout guesses. "
                "Unresolved parameters MUST be {low,high,basis:'assumed',gap} with finite bounds and explicit gaps. "
                "An observed/estimated parameter needs a binding {mechanismId,parameter,claimIds,sourceIds,method}. "
                "Parameter paths are names or coefficients.0, coefficients.1, etc; use '' for a parameter-free edge. "
                "Every cited claim must concern an input/output node and have fetched primary support. Observed "
                "parameters require verified claims; estimates stay estimated. method='quoted' requires each scalar "
                "or range endpoint literally in the cited claim passage. Alternatively ratio/difference/growth_rate "
                "takes exactly two operands [{claimId,value},{claimId,value}], each value literally quoted; "
                "the engine recomputes a/b, a-b, or a/b-1. No arbitrary calculations or invented precision. "
                "Bindings and parameter/mechanism sourceIds must agree. Assumed parameters need no invented binding. "
                "Do not emit unknown keys.\n" + engine.delimit("ADMITTED CASE", _dump(case)) + library_context)
            raw = engine.json_call([engine.brief], task, label="target:mechanisms", required=("mechanisms",), deadline=deadline)
            if set(raw) - {"mechanisms", "mechanismEvidence"}:
                raise ValueError("unknown target mechanism response fields")
            updated = build_case({"forecastCase": case}, raw, continuation_sources(case),
                                 question=engine.question, as_of=engine.plan.as_of)
            engine.write_json(folder / "mechanism-bindings.json", raw)
            binding["mechanismEvidenceHash"] = _hash(raw)
            engine.state.set_phase("target_mechanisms", "done")
            return updated

    if "assessed" not in binding or anchor is not None:
        case = checkpoint("mechanisms", bind_mechanisms)
    if anchor is not None:
        if __package__:
            from .world_anchor_case import validate_anchored_case
        else:
            from world_anchor_case import validate_anchored_case
        validate_anchored_case(case, pack=anchor["pack"], requirements=anchor["requirements"],
            index=anchor["index"], policy=anchor["policy"])

    def assess():
        pin_sources()
        with engine.phase("target_assessment") as deadline:
            raw = engine.json_call([engine.brief], "TARGET ASSESSMENT TASK\nReturn {\"assessment\": {...}, "
                "\"binaries\": [...]} for the following case. Append a posterior at the next version with an "
                "assessmentId, kind='posterior', scenarioWeights (sum=1), and updates. Each changed scenario weight "
                "must have evidenceId (admitted claimId), nodeId, direction increase|decrease, size=absolute change, "
                "oldWeight, newWeight, scenarioId, reason. Preserve prior exactly. Evidence may overturn it; never "
                "lock weights to planner beliefs. Without new evidence keep weights and explain gaps, do not invent "
                "an update. Scenario definitions are pinned in this case; a different definition set needs a new revision case. "
                "Binaries are explicit predicates with binaryId, question, predicate, probability and sourceIds; "
                "do not extract them from a report. Optional actors must have documented levers; decisionBasis must cite "
                "an admitted primary claimId for each lever node. Use the strict actor wire fields only. Do not invent actors.\n" +
                engine.delimit("ADMITTED CASE", _dump(case)), label="target:assessment", required=("assessment",),
                deadline=deadline)
            if set(raw) - {"assessment", "binaries", "actors", "scenarios"}:
                raise ValueError("unknown target assessment response fields")
            assessment_sources = case["sources"] if anchor is not None else continuation_sources(case)
            if anchor is not None and "actors" in raw and raw["actors"] != case["actors"]:
                raise ValueError("anchor assessment cannot change admitted actor structure")
            updated = build_case({"forecastCase": case}, raw, assessment_sources,
                                 question=engine.question, as_of=engine.plan.as_of)
            binding["sourceEvidenceHash"] = _hash(_engine_sources(engine))
            engine.state.set_phase("target_assessment", "done")
            return updated

    case = core.validate_case(checkpoint("assessed", assess))
    if anchor is not None:
        if __package__:
            from .world_anchor_case import validate_anchored_case
        else:
            from world_anchor_case import validate_anchored_case
        validate_anchored_case(case, pack=anchor["pack"], requirements=anchor["requirements"],
            index=anchor["index"], policy=anchor["policy"])
    mechanism_proof_path = folder / "mechanism-bindings.json"
    proof = json.loads(mechanism_proof_path.read_text("utf-8")) if mechanism_proof_path.is_file() else None
    if (proof is None or _hash(proof) != binding.get("mechanismEvidenceHash")
            or proof.get("mechanisms") != case["mechanisms"]):
        raise ValueError("target mechanism evidence binding changed or missing")
    check_library()
    engine._check_web_reuse()
    engine._check_data_reuse()
    engine._check_context_reuse()
    case_path = engine.out_dir / "forecast_case.json"
    digest = core.case_hash(case)
    if binding.get("finalCaseHash"):
        if digest != binding["finalCaseHash"]:
            raise ValueError("target final case identity changed")
        core.read_case(case_path, expected_hash=digest)
    else:
        core.write_case(case_path, case)
        binding["finalCaseHash"] = digest
        engine.state.save()
    report = render_case_research(case)
    if len(report.strip()) < 400:
        raise ValueError("target report is shorter than the child contract")
    projection = core.graph_projection(case)
    latest = case["assessments"][-1]
    artifacts = {"sources.json": case["sources"], "actors.json": {
                    "central_question": case["question"], "as_of_date": case["asOf"], "actors": case["actors"],
                    "relationships": [], "forecast_authority": AUTHORITY, "caseHash": digest},
                 "target_graph.json": projection,
                 "quantitative.json": case["nodes"], "contested.json": [c for c in case["claims"] if c["status"] == "contested"],
                 "timeline.json": [], "forecast_inputs.json": {"authority": AUTHORITY, "caseHash": digest,
                    "resolution": case["resolution"], "scenarios": case["scenarios"], "assessment": latest,
                    "binaries": case["binaries"]}}
    if anchor is not None:
        if __package__:
            from .world_anchor_binding import research_note_projection, research_report_appendix
        else:
            from world_anchor_binding import research_note_projection, research_report_appendix
        _, artifacts["timeline.json"] = research_note_projection(anchor)
        report += research_report_appendix(anchor)
    for filename, payload in artifacts.items():
        engine.write_json(engine.out_dir / filename, payload, internal=False)
    engine.write_text(engine.out_dir / "research_report.md", report)
    engine.final_report = report
    engine.state.set_phase("finalize", "done", "typed case projections; no prose extraction")
    engine.meta.update(status="completed", forecast_authority=AUTHORITY, forecast_case_hash=digest,
                       forecast_case_id=case["caseId"], forecast_case_revision=case["revision"],
                       report_chars=len(report), sources_count=len(case["sources"]),
                       as_of_date=case["asOf"], finished_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                       target_research={"version": RESEARCH_VERSION, "open_nodes": research_priorities(case),
                           "stop_reason": "resolved" if not research_priorities(case) else "bounded_research_exhausted"})
    engine.meta.pop("error", None)
    engine.log("done", f"target research complete: {case['caseId']} {digest}")
    return 0
