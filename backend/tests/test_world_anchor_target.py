"""Real reviewed-anchor admission through the target case and decision runtime."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import types

import pytest

from app.services import target_simulation as runtime, world_anchor as host
from deerflow_bridge import world_anchor as wa, world_anchor_case as adapter
from tests import test_world_anchor as fixtures

pytestmark = pytest.mark.guarded_runner


@pytest.mark.parametrize("mode", ["package", "bare"])
def test_adapter_import_layout_in_guarded_child(tmp_path, mode):
    guard = sys.modules["main_offline_guard"]
    child = tmp_path / "anchor_import_child.py"
    child.write_text("""import importlib, json, sys
from pathlib import Path
assert "main_offline_guard" in sys.modules
mode, repository = sys.argv[1:]
root = Path(repository)
sys.path.insert(0, str(root if mode == "package" else root / "deerflow_bridge"))
prefix = "deerflow_bridge." if mode == "package" else ""
adapter = importlib.import_module(prefix + "world_anchor_case")
wa = importlib.import_module(prefix + "world_anchor")
fc = importlib.import_module(prefix + "forecast_case")
assert adapter.wa is wa and adapter.fc is fc
assert adapter.__package__ == ("deerflow_bridge" if mode == "package" else "")
try:
    adapter.apply_anchors_to_case(None, pack={}, requirements={}, index=None, policy={})
except wa.AnchorError as error:
    assert type(error) is wa.AnchorError
else:
    raise AssertionError("invalid input did not raise the native AnchorError")
print(json.dumps({"mode": mode, "guarded": True, "native_classes": True}))
""")
    guard.allow_python_script(child)
    result = subprocess.run(
        [sys.executable, str(child), mode, str(Path(__file__).resolve().parents[2])],
        cwd=tmp_path,
        env={},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"mode": mode, "guarded": True, "native_classes": True}


def _case():
    original = json.loads((Path(__file__).parent / "fixtures/target_case.json").read_text())
    case = deepcopy(original)
    case.update(
        caseId="anchored-target",
        sources=[],
        claims=[],
        binaries=[],
        assessments=[
            {
                "assessmentId": "prior",
                "version": 1,
                "kind": "prior",
                "scenarioWeights": {"below": 0.5, "above": 0.5},
                "updates": [],
            }
        ],
    )
    case["resolution"]["targetNodeId"] = "target"
    case["nodes"] = []
    for nid in ("baseline", "control", "target"):
        node = deepcopy(original["nodes"][0])
        node.update(
            nodeId=nid,
            label=nid,
            units="USD billion",
            value=1,
            range={"low": 1, "high": 1},
            status="unknown",
            sourceIds=[],
            claimIds=[],
            vintage=None,
            basis="assumed",
            gap="Synthetic prebinding prior.",
        )
        case["nodes"].append(node)
    case["mechanisms"] = [
        {
            "mechanismId": "total",
            "kind": "linear",
            "inputNodeIds": ["baseline", "control"],
            "outputNodeId": "target",
            "parameters": {"coefficients": [1, 1], "intercept": 0},
            "basis": "assumed",
            "sourceIds": [],
            "gap": "Synthetic admitted additive mechanism.",
        }
    ]
    actor = deepcopy(original["actors"][0])
    actor.update(
        actorId="regulator",
        objectives=[{"nodeId": "target", "direction": "increase", "weight": 0.76}],
        decisionBasis="PRIVATE_SELF_INFERENCE",
        decisionRule={"kind": "llm", "cadencePeriods": 1, "triggers": []},
        constraints={"capacity": 100},
        information={"nodeIds": ["baseline", "control", "target"], "releaseLagPeriods": 0},
        levers=[
            {
                "leverId": "mandate",
                "nodeId": "control",
                "minimum": 0,
                "maximum": 20,
                "cost": 1,
                "lagPeriods": 0,
                "reversible": True,
                "requiresConsent": [],
            }
        ],
        plans=[{"planId": "unsafe-plan", "leverId": "mandate", "value": 19, "duePeriod": 1}],
    )
    case["actors"] = [actor]
    for scenario in case["scenarios"]:
        scenario["predicate"]["nodeId"] = "target"
    return case


def _fixture(
    root,
    *,
    mutation=None,
    hidden="PRIVATE_SELF_INFERENCE",
    value_kind="reported",
    range_value=False,
    parameter_unit=None,
    adapter_version=None,
    template_version="v1",
    unready=False,
    rival_value=None,
    rival_private=True,
    admitted_plan=False,
    observation_mutation=None,
    actor_free=False,
    control=None,
    mechanism_kind="linear",
    primitive_unit=None,
    matching_visibility=False,
    primitive_target=False,
    external_target_forecast=False,
    quantity_unit=None,
    quantities=("247.5", "10"),
    research_dossiers=False,
    registry_mutation=None,
    run_id=None,
    target_descendants=False,
    reverse_mechanisms=False,
    milestone=False,
    declared_node_identities=False,
    identity_mutation=None,
    research_notes=False,
    primary_authority=False,
    authority_review="explicit_support",
    mixed_authority_sources=False,
    private_authority=None,
    private_parameter=None,
):
    root.mkdir(parents=True, exist_ok=True)
    page = (
        "Synthetic cybersecurity spending records: baseline 247.5 USD billion for 2025, control 10 USD billion, coefficients 1, intercept 0. "
        "Regulator has sole authority. Rival has sole authority. Rival state 3 or 7 USD billion. "
        "The admitted plan chooses 20 at period 2. "
        "Public statements in this synthetic record are visible to all actors from 2026-10-27T00:00:00Z."
    )
    if private_authority is not None:
        assert set(private_authority) == {"text", "url"} and not mixed_authority_sources
        page = page.replace("Regulator has sole authority. Rival has sole authority. ", "")
    if external_target_forecast:
        page += " An external analyst forecasts 247.5 USD billion for 2027."
    if milestone:
        page += " The supported milestone switches from 0 to 10 at simulation period 2."
    if quantity_unit:
        page = page.replace("USD billion", quantity_unit["id"])
    page = page.replace("baseline 247.5", "baseline " + quantities[0]).replace("control 10", "control " + quantities[1])
    f = fixtures.make_fixture(root / "source", page=page)
    if private_authority is not None:
        private_page = (
            private_authority["text"] + " This statement is visible only to regulator from 2026-10-27T00:00:00Z."
        )
        private_bytes = private_page.encode()
        private_path = "v3/pages/private-authority.txt"
        (f["root"] / private_path).write_bytes(private_bytes)
        f["manifest"]["artifacts"].append(
            {
                "artifact_id": "private-authority",
                "track_id": "main",
                "path": private_path,
                "sha256": fixtures.digest(private_bytes),
                "bytes": len(private_bytes),
                "encoding": "utf8_text",
                "role": "page",
            }
        )
        ledger = json.loads((f["root"] / "v3/sources_ledger.json").read_bytes())
        ledger.append(
            {
                **deepcopy(ledger[0]),
                "sid": 109,
                "tier": "primary",
                "url": private_authority["url"],
                "title": "Private primary mandate",
                "page_path": "pages/private-authority.txt",
                "content_sha256": fixtures.digest(private_bytes),
            }
        )
        raw_ledger = fixtures.dump(ledger)
        (f["root"] / "v3/sources_ledger.json").write_bytes(raw_ledger)
        next(a for a in f["manifest"]["artifacts"] if a["artifact_id"] == "ledger").update(
            sha256=fixtures.digest(raw_ledger), bytes=len(raw_ledger)
        )
    if mixed_authority_sources:
        primary_page = "An unrelated primary record states a measured quantity."
        primary_bytes = primary_page.encode()
        (f["root"] / "v3/pages/unrelated-primary.txt").write_bytes(primary_bytes)
        f["manifest"]["artifacts"].append(
            {
                "artifact_id": "unrelated-primary",
                "track_id": "main",
                "path": "v3/pages/unrelated-primary.txt",
                "sha256": fixtures.digest(primary_bytes),
                "bytes": len(primary_bytes),
                "encoding": "utf8_text",
                "role": "page",
            }
        )
        ledger = json.loads((f["root"] / "v3/sources_ledger.json").read_bytes())
        ledger.append(
            {
                **deepcopy(ledger[0]),
                "sid": 108,
                "tier": "primary",
                "url": "https://example.test/unrelated",
                "title": "Unrelated primary record",
                "page_path": "pages/unrelated-primary.txt",
                "content_sha256": fixtures.digest(primary_bytes),
            }
        )
        raw_ledger = fixtures.dump(ledger)
        (f["root"] / "v3/sources_ledger.json").write_bytes(raw_ledger)
        next(a for a in f["manifest"]["artifacts"] if a["artifact_id"] == "ledger").update(
            sha256=fixtures.digest(raw_ledger), bytes=len(raw_ledger)
        )
    if primary_authority:
        ledger = json.loads((f["root"] / "v3/sources_ledger.json").read_bytes())
        ledger[0]["tier"] = "primary"
        raw_ledger = fixtures.dump(ledger)
        (f["root"] / "v3/sources_ledger.json").write_bytes(raw_ledger)
        next(a for a in f["manifest"]["artifacts"] if a["artifact_id"] == "ledger").update(
            sha256=fixtures.digest(raw_ledger), bytes=len(raw_ledger)
        )
    if run_id is not None:
        # Rebuild all requirements, source IDs and receipts below from this
        # admitted owner scope; never rewrite IDs inside an already sealed pack.
        f["scope"]["run_id"] = run_id
    case = _case()
    if quantity_unit:
        case["resolution"]["units"] = quantity_unit["id"]
        for node in case["nodes"]:
            node["units"] = quantity_unit["id"]
    case["actors"][0]["decisionBasis"] = hidden
    if primary_authority:
        case["sources"] = [
            {
                "sourceId": "S1",
                "url": "https://example.test/report",
                "title": "Primary synthetic mandate",
                "publishedAt": None,
                "retrievedAt": "2026-10-26T09:29:13Z",
                "originCluster": "synthetic-primary",
                "tier": "primary",
                "fetched": True,
                "passage": page,
            }
        ]
        case["claims"] = [
            {
                "claimId": "C3",
                "nodeId": "control",
                "sourceIds": ["S1"],
                "passage": "Regulator has sole authority.",
                "status": "reported",
            }
        ]
        case["nodes"][1].update(sourceIds=["S1"], claimIds=["C3"])
        case["actors"][0]["decisionBasis"] = "Primary mandate evidence C3."
        if private_authority is not None:
            case["sources"].append(
                {
                    **deepcopy(case["sources"][0]),
                    "sourceId": "S2",
                    "url": private_authority["url"],
                    "title": "Private primary mandate",
                    "originCluster": "synthetic-private-primary",
                    "passage": private_page,
                }
            )
            case["claims"][0].update(sourceIds=["S2"], passage=private_authority["text"])
            case["nodes"][1].update(sourceIds=["S2"], claimIds=["C3"])
    if primitive_unit:
        case["nodes"][1]["units"] = primitive_unit["id"]
    if rival_value is not None:
        rival_node = deepcopy(case["nodes"][0])
        rival_node.update(
            nodeId="rival-state",
            label="Rival state",
            visibility="private" if rival_private else "public",
            ownerActorId="rival",
        )
        case["nodes"].append(rival_node)
        case["mechanisms"][0]["inputNodeIds"].append("rival-state")
        case["mechanisms"][0]["parameters"]["coefficients"].append(1)
        rival = deepcopy(case["actors"][0])
        rival.update(
            actorId="rival",
            name="Rival",
            plans=[],
            information={"nodeIds": ["baseline", "control", "rival-state", "target"], "releaseLagPeriods": 0},
        )
        rival["levers"][0].update(leverId="rival-lever", nodeId="rival-state")
        case["actors"].append(rival)
        if not rival_private:
            case["actors"][0]["information"]["nodeIds"].append("rival-state")
    if actor_free:
        case["actors"] = []
    if matching_visibility:
        copied = deepcopy(case["nodes"][0])
        copied.update(nodeId="public-copy", label="Public copy")
        case["nodes"].append(copied)
        case["actors"][0]["information"]["nodeIds"].append("public-copy")
    if mechanism_kind != "linear":
        case["mechanisms"][0].update(kind=mechanism_kind, parameters={})
    if primitive_target:
        case["resolution"]["targetNodeId"] = "baseline"
        case["nodes"] = [n for n in case["nodes"] if n["nodeId"] != "target"]
        case["mechanisms"] = []
        for a in case["actors"]:
            a["information"]["nodeIds"] = [n for n in a["information"]["nodeIds"] if n != "target"]
            a["objectives"] = []
        for scenario in case["scenarios"]:
            scenario["predicate"]["nodeId"] = "baseline"
    if mutation:
        mutation(case)
    if milestone:
        assert mechanism_kind == "sum"
        for nid in ("milestone", "intermediate"):
            node = deepcopy(next(n for n in case["nodes"] if n["nodeId"] == "target"))
            node.update(nodeId=nid, label=nid, value=0, range={"low": 0, "high": 10})
            case["nodes"].append(node)
        case["mechanisms"][0]["inputNodeIds"].append("intermediate")
        case["mechanisms"].extend(
            [
                {
                    "mechanismId": "milestone-switch",
                    "kind": "regulatory_milestone",
                    "outputNodeId": "milestone",
                    "inputNodeIds": [],
                    "parameters": {"milestonePeriod": 2, "before": 0, "after": 10},
                    "basis": "assumed",
                    "sourceIds": [],
                    "gap": "Explicit synthetic milestone.",
                },
                {
                    "mechanismId": "intermediate-sum",
                    "kind": "sum",
                    "outputNodeId": "intermediate",
                    "inputNodeIds": ["milestone"],
                    "parameters": {},
                    "basis": "assumed",
                    "sourceIds": [],
                    "gap": "Explicit synthetic intermediate.",
                },
            ]
        )
    if target_descendants:
        for nid, inputs in (
            ("target-alias", ["target"]),
            ("target-copy", ["target-alias"]),
            ("current-total", ["baseline", "control"]),
        ):
            node = deepcopy(next(n for n in case["nodes"] if n["nodeId"] == "target"))
            node.update(nodeId=nid, label=nid)
            case["nodes"].append(node)
            case["mechanisms"].append(
                {
                    "mechanismId": nid + "-sum",
                    "kind": "sum",
                    "outputNodeId": nid,
                    "inputNodeIds": inputs,
                    "parameters": {},
                    "basis": "assumed",
                    "sourceIds": [],
                    "gap": "Explicit synthetic dependency for observation admission.",
                }
            )
            for actor in case["actors"]:
                actor["information"]["nodeIds"].append(nid)
    contract = deepcopy(f["requirements"]["contract"])
    f["scope"]["authority"] = "target-first-v1"
    f["manifest"]["scope"] = deepcopy(f["scope"])
    f["manifest"]["tracks"][0]["adapter"] = "target-case/v1"
    contract["scope"] = deepcopy(f["scope"])
    money = deepcopy(quantity_unit) if quantity_unit else {**fixtures.unit(), "id": "USD billion"}
    scalar = {
        "id": "fraction",
        "dimension": "dimensionless",
        "scale": "1",
        "currency": None,
        "price_basis": "not_applicable",
        "base_period": None,
    }

    def identity(metric, unit, year=2025):
        return {**fixtures.identity(year), "metric_id": metric, "unit": deepcopy(unit)}

    target_id = case["resolution"]["targetNodeId"]
    contract["settlement"].update(target_node_id=target_id, identity=identity("spending", money, 2027))
    prototype = deepcopy(contract["terms"][1])
    target = deepcopy(contract["terms"][0])
    target.update(
        identity=contract["settlement"]["identity"],
        consumers=[fixtures.consumer(adapter.ENGINE, "diagnostic", target_id, "definition")],
    )
    contract["terms"] = [target]
    values = []

    def term(kind, role, obj, field, ident, value, actor=None):
        row = deepcopy(prototype)
        row.update(
            origin_pointer=f"/terms/{1 + max(int(t['origin_pointer'].rsplit('/', 1)[1]) for t in contract['terms'])}",
            kind=kind,
            identity=ident,
            actor_ref=actor,
            value_type=value["kind"],
            accepted_value_kinds=["reported"] if kind == "actor_authority" else [value_kind],
            consumers=[fixtures.consumer(adapter.ENGINE, role, obj, field)],
        )
        contract["terms"].append(row)
        values.append(value)
        return row["origin_pointer"]

    baseline = (
        {"kind": "range", "low": "10", "high": "247.5"} if range_value else {"kind": "number", "value": quantities[0]}
    )
    term("baseline", "initial_state", "baseline", "value", identity("spending", money), baseline)
    term(
        "baseline",
        "initial_state",
        "control",
        "value",
        identity("control", primitive_unit or money),
        {"kind": "number", "value": quantities[1]},
    )
    if matching_visibility:
        term(
            "baseline",
            "initial_state",
            "public-copy",
            "value",
            identity("spending", money),
            {"kind": "number", "value": "247.5"},
        )
    if rival_value is not None:
        term(
            "baseline",
            "initial_state",
            "rival-state",
            "value",
            identity("rival-state", money),
            {"kind": "number", "value": str(rival_value)},
        )
    slots = []
    slot_values = (
        []
        if primitive_target
        else [("coefficient:" + nid, scalar, "1") for nid in case["mechanisms"][0]["inputNodeIds"]]
        + [("intercept", money, "0")]
    )
    for name, unit, number in slot_values:
        unit = parameter_unit if parameter_unit is not None and name.startswith("coefficient:") else unit
        origin = term(
            "mechanism_parameter", "mechanism", "total", name, identity(name, unit), {"kind": "number", "value": number}
        )
        slots.append({"name": name, "requirement_origin": origin, "unit": deepcopy(unit)})
    actor_specs = []
    for i, actor in enumerate(case["actors"]):
        aid, lever = actor["actorId"], actor["levers"][0]
        auth_origin = term(
            "actor_authority",
            "actor_brief",
            aid,
            "authority:" + lever["leverId"],
            identity(aid + ":authority", scalar),
            {
                "kind": "text",
                "value": private_authority["text"]
                if private_authority is not None and aid == "regulator"
                else "Regulator has sole authority."
                if aid == "regulator"
                else "Rival has sole authority.",
            },
            actor=aid,
        )
        actor_specs.append(
            {
                "actor_ref": aid,
                "registry_artifact_id": "contract",
                "registry_pointer": f"/forecast_case/actors/{i}",
                "statements": [],
                "authority": [
                    {
                        "lever_id": lever["leverId"],
                        "requirement_origin": auth_origin,
                        "node_id": lever["nodeId"],
                        "mode": "sole",
                        "coholder_actor_refs": [],
                        "bound_requirement_origins": [],
                    }
                ],
                "plans": [],
                "red_lines": [],
            }
        )
    if admitted_plan:
        for field, value, unit in (
            ("value", "20", money),
            ("duePeriod", "2", {**scalar, "id": "period", "dimension": "time"}),
        ):
            origin = term(
                "actor_plan",
                "actor_brief",
                "regulator",
                "plans/unsafe-plan/" + field,
                identity(field, unit),
                {"kind": "number", "value": value},
                actor="regulator",
            )
            actor_specs[0]["plans"].append(origin)
    if control:
        term(
            "actor_plan",
            "actor_brief",
            "regulator",
            control["field"],
            identity(control["field"], control["unit"]),
            {"kind": "number", "value": control["value"]},
            actor="regulator",
        )
    if mechanism_kind != "linear":
        removed = {p["requirement_origin"] for p in slots}
        pairs = [(t, v) for t, v in zip(contract["terms"][1:], values) if t["origin_pointer"] not in removed]
        contract["terms"] = [target] + [t for t, _ in pairs]
        values = [v for _, v in pairs]
        slots = []
    if external_target_forecast:
        term(
            "actor_statement",
            "actor_brief",
            "regulator",
            "statement",
            identity("spending", money, 2027),
            {"kind": "number", "value": "247.5"},
            actor="regulator",
        )
        contract["terms"][-1]["accepted_value_kinds"] = ["third_party_forecast"]
    contract["mechanisms"] = (
        []
        if primitive_target
        else [
            {
                "mechanism_id": "total",
                "template": mechanism_kind,
                "template_version": template_version,
                "input_node_ids": list(case["mechanisms"][0]["inputNodeIds"]),
                "output_node_id": "target",
                "parameters": slots,
                "lag_requirement_origin": None,
                "applicability_requirement_origins": [],
                "consumers": [fixtures.consumer(adapter.ENGINE, "mechanism", "total", "template")],
            }
        ]
    )
    if milestone:
        milestone_slots = []
        for name, val, unit in (
            ("milestonePeriod", "2", {**scalar, "id": "period", "dimension": "time"}),
            ("before", "0", money),
            ("after", "10", money),
        ):
            origin = term(
                "mechanism_parameter",
                "mechanism",
                "milestone-switch",
                name,
                identity(name, unit),
                {"kind": "number", "value": val},
            )
            milestone_slots.append({"name": name, "requirement_origin": origin, "unit": unit})
        contract["mechanisms"].extend(
            {
                "mechanism_id": m["mechanismId"],
                "template": m["kind"],
                "template_version": "v1",
                "input_node_ids": m["inputNodeIds"],
                "output_node_id": m["outputNodeId"],
                "parameters": milestone_slots if m["kind"] == "regulatory_milestone" else [],
                "lag_requirement_origin": None,
                "applicability_requirement_origins": [],
                "consumers": [fixtures.consumer(adapter.ENGINE, "mechanism", m["mechanismId"], "template")],
            }
            for m in case["mechanisms"][1:]
        )
    if target_descendants:
        contract["mechanisms"].extend(
            {
                "mechanism_id": m["mechanismId"],
                "template": m["kind"],
                "template_version": "v1",
                "input_node_ids": m["inputNodeIds"],
                "output_node_id": m["outputNodeId"],
                "parameters": [],
                "lag_requirement_origin": None,
                "applicability_requirement_origins": [],
                "consumers": [fixtures.consumer(adapter.ENGINE, "mechanism", m["mechanismId"], "template")],
            }
            for m in case["mechanisms"][1:]
        )
    if research_notes:
        assert research_dossiers
        note_origins = []
        for kind, text in (
            ("actor_statement", "Regulator has sole authority."),
            ("event", "The admitted plan chooses 20 at period 2."),
            ("indicator", "Rival state 3 or 7 USD billion."),
        ):
            note_origins.append(
                term(
                    kind,
                    "research_note",
                    "research-only",
                    kind,
                    None,
                    {"kind": "text", "value": text},
                    actor="research-only" if kind == "actor_statement" else None,
                )
            )
    research_registry = []
    if research_dossiers:
        research_registry.append(
            {
                "actor_ref": "research-only",
                "name": "Research-only subject",
                "quoted_public_statement": "Regulator has sole authority.",
                "source_id": "S107",
            }
        )
        actor_specs.append(
            {
                "actor_ref": "research-only",
                "registry_artifact_id": "contract",
                "registry_pointer": "/research_actor_registry/0",
                "statements": note_origins[:1] if research_notes else [],
                "authority": [],
                "plans": [],
                "red_lines": [],
            }
        )
    if registry_mutation:
        registry_mutation(actor_specs)
    contract["actors"] = actor_specs
    if reverse_mechanisms:
        case["mechanisms"].reverse()
        contract["mechanisms"].reverse()
    native = {k: deepcopy(v) for k, v in case.items() if k not in {"assessments", "binaries"}}
    authority = {
        "settlement": contract["settlement"]["identity"],
        "terms": contract["terms"],
        "forecast_case": native,
        "research_actor_registry": research_registry,
        "target_sources": [
            {"sourceId": "S107", "url": "https://example.test/report", "content_sha256": fixtures.digest(page.encode())}
        ],
        **{k: contract[k] for k in (*wa.SPEC_FIELDS, "aliases")},
    }
    if declared_node_identities:
        identities = {n["nodeId"]: identity(n["nodeId"], money, 2027) for n in case["nodes"]}
        for t in contract["terms"]:
            if t["kind"] in {"baseline", "target_definition"}:
                identities[t["consumers"][0]["object_id"]] = deepcopy(t["identity"])
        if identity_mutation:
            identity_mutation(identities)
        authority["node_identities"] = identities
    raw = fixtures.dump(authority)
    (f["root"] / "contract.json").write_bytes(raw)
    next(a for a in f["manifest"]["artifacts"] if a["artifact_id"] == "contract").update(
        sha256=fixtures.digest(raw), bytes=len(raw)
    )
    contract["authority_artifact_hash"] = fixtures.digest(raw)
    kiq = fixtures.dump(
        {
            "id": "K1",
            "facts": [{"kiq": "K1", "text": page, "sids": [107, 108] if mixed_authority_sources else [107]}]
            * (2 if matching_visibility else 1),
        }
    )
    if private_authority is not None:
        facts = json.loads(kiq)
        facts["facts"].append({"kiq": "K1", "text": private_page, "sids": [109]})
        kiq = fixtures.dump(facts)
    (f["root"] / "v3/kiq/K1.json").write_bytes(kiq)
    next(a for a in f["manifest"]["artifacts"] if a["artifact_id"] == "kiq").update(
        sha256=fixtures.digest(kiq), bytes=len(kiq)
    )
    f["manifest"]["crosswalk"] = [
        {
            "crosswalk_id": "target-source",
            "source_key": wa._id("source", f["scope"], "main", "ledger", "/0"),
            "namespace": "target_source_id",
            "external_id": "S107",
            "track_id": "main",
            "artifact_id": "contract",
            "pointer": "/target_sources/0",
            "proof_ref_ids": [],
        }
    ]
    f["requirements"] = wa.requirements_from_contract(contract, scope=f["scope"])
    f["policy"]["consumer_rules"] = [
        {**c, "adapter_version": adapter_version or adapter.ADAPTER_VERSION, "template_versions": []}
        for t in contract["terms"]
        for c in t["consumers"]
    ]
    f["policy"]["consumer_rules"] += (
        []
        if primitive_target
        else [
            {
                **mechanism["consumers"][0],
                "adapter_version": adapter_version or adapter.ADAPTER_VERSION,
                "template_versions": [template_version],
            }
            for mechanism in contract["mechanisms"]
        ]
    )
    f["index"] = wa.index_snapshot(
        f["root"],
        f["manifest"],
        expected_manifest_hash=wa.anchor_hash(f["manifest"]),
        expected_scope=f["scope"],
        requirements=f["requirements"],
        policy=f["policy"],
    )
    proposal, review = fixtures.review_fixture(f)
    proto, review_proto = deepcopy(proposal["rows"][0]), deepcopy(review["decisions"][0])
    proposal["rows"], review["decisions"] = [], []
    ordered = sorted(
        (r for r in f["requirements"]["requirements"] if r["kind"] != "target_definition"),
        key=lambda r: int(r["origin_pointer"].split("/")[-1]),
    )
    for n, (requirement, value) in enumerate(zip(ordered, values)):
        row = deepcopy(proto)
        row.update(
            proposal_id=f"p-{n}",
            requirement_ids=[requirement["requirement_id"]],
            identity=deepcopy(requirement["identity"]),
            value=deepcopy(value),
            source_value=deepcopy(value),
            value_kind=requirement["accepted_value_kinds"][0],
        )
        row["subject_actor_ref"] = requirement["actor_ref"]
        if matching_visibility and requirement["consumers"][0]["object_id"] == "baseline":
            row["audience"] = {"kind": "analyst", "actor_refs": []}
        if matching_visibility and requirement["consumers"][0]["object_id"] == "public-copy":
            claim = next(c for c in f["index"].snapshot()["inventory"] if c["fact_index"] == 1)
            ref = deepcopy(proposal["references"][0])
            old_ref = ref["ref_id"]
            ref.update(claim_id=claim["claim_id"], fact_index=1)
            ref["locator"].update(start_byte=10, quote=page[10:])
            ref["ref_id"] = wa._id("ref", ref["source_key"], ref["content_hash"], ref["locator"])
            proposal["references"].append(ref)
            row.update(claim_id=claim["claim_id"], ref_ids=[ref["ref_id"]])
            for support in row["support"]:
                support.update(ref_id=ref["ref_id"], selector=deepcopy(ref["locator"]), expected=page[10:])
            row["visible_at"]["basis_ref_ids"] = [ref["ref_id"]]
            copied_review = deepcopy(review_proto)
            for check in copied_review["checks"]:
                check["ref_ids"] = [ref["ref_id"] if r == old_ref else r for r in check["ref_ids"]]
        else:
            copied_review = deepcopy(review_proto)
        if private_authority is not None and (
            requirement["kind"] == "actor_authority"
            or (
                requirement["kind"] == "mechanism_parameter"
                and requirement["consumers"][0]["field"] == private_parameter
            )
        ):
            data = f["index"].snapshot()
            source = next(s for s in data["sources"] if s["local_source_id"] == "109")
            claim = next(c for c in data["inventory"] if source["source_key"] in c["source_keys"])
            ref = deepcopy(proposal["references"][0])
            ref.update(
                source_key=source["source_key"],
                artifact_id="private-authority",
                content_hash=source["content_hash"],
                claim_id=claim["claim_id"],
                fact_index=claim["fact_index"],
                locator={
                    "kind": "text_span",
                    "start_byte": 0,
                    "end_byte": len(private_bytes),
                    "quote": private_page,
                },
            )
            ref["ref_id"] = wa._id("ref", ref["source_key"], ref["content_hash"], ref["locator"])
            if ref["ref_id"] not in {r["ref_id"] for r in proposal["references"]}:
                proposal["references"].append(ref)
            row.update(
                claim_id=claim["claim_id"],
                ref_ids=[ref["ref_id"]],
                producer_class="primary_statement",
                audience={"kind": "actors", "actor_refs": ["regulator"]},
                owner_actor_ref="regulator",
            )
            row["visible_at"]["basis_ref_ids"] = [ref["ref_id"]]
            for support in row["support"]:
                support.update(ref_id=ref["ref_id"], selector=deepcopy(ref["locator"]), expected=private_page)
            for check in copied_review["checks"]:
                check["ref_ids"] = [ref["ref_id"]]
        if requirement["kind"] == "actor_authority":
            if authority_review != "missing":
                row["support"].append({**deepcopy(row["support"][0]), "field": "authority"})
                copied_review["checks"].append(
                    {"field": "authority", "verdict": authority_review, "ref_ids": list(row["ref_ids"])}
                )
            if mixed_authority_sources:
                source = next(s for s in f["index"].snapshot()["sources"] if s["local_source_id"] == "108")
                extra = deepcopy(proposal["references"][0])
                extra.update(
                    source_key=source["source_key"],
                    artifact_id="unrelated-primary",
                    content_hash=source["content_hash"],
                    locator={
                        "kind": "text_span",
                        "start_byte": 0,
                        "end_byte": len(primary_bytes),
                        "quote": primary_page,
                    },
                )
                extra["ref_id"] = wa._id("ref", extra["source_key"], extra["content_hash"], extra["locator"])
                if extra["ref_id"] not in {r["ref_id"] for r in proposal["references"]}:
                    proposal["references"].append(extra)
                row["ref_ids"].append(extra["ref_id"])
        if requirement["identity"] and requirement["identity"]["metric_id"] == "rival-state" and rival_private:
            row["audience"] = {"kind": "actors", "actor_refs": ["rival"]}
            row["owner_actor_ref"] = "rival"
        if observation_mutation:
            observation_mutation(row, requirement)
        proposal["rows"].append(row)
        review["decisions"].append({**copied_review, "proposal_id": row["proposal_id"]})
    review["proposal_hash"] = wa.anchor_hash(proposal)
    receipts = fixtures.receipt_fixture(f, proposal, review)
    f["receipts"] = [receipts]
    f["index"] = wa.admit_reviewed_evidence(
        f["index"], proposal, review, requirements=f["requirements"], policy=f["policy"], receipts=receipts
    )
    f["pack"] = fixtures.build_pack(f)
    if matching_visibility:
        proposal = deepcopy(f["pack"]["proposal"])
        reqs = {r["requirement_id"]: r for r in f["requirements"]["requirements"]}
        observations = {o["observation_id"]: o for o in f["pack"]["observations"]}
        candidates = {c["requirement_id"]: c for c in f["pack"]["candidates"]["rows"]}
        for row in proposal["rows"]:
            obj = reqs[row["requirement_id"]]["consumers"][0]["object_id"]
            if obj in {"baseline", "public-copy"}:
                kind = "analyst" if obj == "baseline" else "public"
                row["candidate_ids"] = [
                    next(
                        c["candidate_id"]
                        for c in candidates[row["requirement_id"]]["ranked"]
                        if observations[c["observation_id"]]["audience"]["kind"] == kind
                    )
                ]
        f["pack"] = wa.admit_bindings(
            f["requirements"],
            f["index"],
            f["pack"]["candidates"],
            proposal,
            policy=f["policy"],
            attempts=[],
            metering=f["pack"]["metering"],
        )
    if not unready and observation_mutation is None:
        assert next(r for r in f["pack"]["readiness"] if r["engine"] == adapter.ENGINE)["status"] == "ready", (
            json.dumps({"gaps": f["pack"]["gaps"], "observations": len(f["pack"]["observations"])}, indent=2)
        )
    if unready:
        # A genuine absence of reviewed evidence gives a gap pack.
        f["receipts"] = []
        f["index"] = wa.index_snapshot(
            f["root"],
            f["manifest"],
            expected_manifest_hash=wa.anchor_hash(f["manifest"]),
            expected_scope=f["scope"],
            requirements=f["requirements"],
            policy=f["policy"],
        )
        f["pack"] = fixtures.build_pack(f)
    f["case"] = case
    f["context"] = host.make_anchor_context(
        f["pack"],
        requirements=f["requirements"],
        index=f["index"],
        policy=f["policy"],
        expected_pack_hash=wa.anchor_hash(f["pack"]),
    )
    return f


def _args(f):
    return {key: f[key] for key in ("pack", "requirements", "index", "policy")}


def _bind(f):
    return adapter.apply_anchors_to_case(f["case"], **_args(f))


def test_real_admission_case_runtime_baseline_action_mechanism_target(tmp_path):
    f = _fixture(tmp_path)
    before = deepcopy(f["case"])
    case = _bind(f)
    assert before == f["case"]
    assert adapter.validate_anchored_case(case, **_args(f)) == case
    seen = []

    def decide(observation):
        seen.append(observation)
        return {"actorId": "regulator", "leverId": "mandate", "value": 20}

    result = runtime.run_paths(
        case,
        paths=1,
        periods=2,
        identity_mode="named",
        decision_provider=decide,
        anchor_context=f["context"],
        model_validation="admission",
    )
    assert result["baseline"]["targetValue"] == 257.5
    assert result["paths"][0]["targetValue"] == 267.5
    assert result["paths"][0]["initialValues"]["baseline"] == 247.5
    assert result["paths"][0]["initialValues"]["target"] == 257.5
    assert result["simulationWeight"] == 0
    assert result["worldAnchor"]["packHash"] == f["context"].pack_hash
    assert seen[0]["anchorItems"] and seen[0]["values"]["baseline"] == 247.5
    assert seen[0]["objectives"] == seen[0]["plans"] == []
    text = json.dumps(seen)
    assert "PRIVATE_SELF_INFERENCE" not in text and "unsafe-plan" not in text
    assert f["context"].pack_hash not in text
    assert all(
        row["basis"] == "estimated"
        for row in result["parameterBases"]
        if row.get("parameter") == "initialValue" and row.get("nodeId") in {"baseline", "control"}
    )


@pytest.mark.parametrize("change", ["target", "units", "period", "topology", "value", "parameter", "basis", "registry"])
def test_final_case_mismatch_rejected_before_callback(tmp_path, change):
    f = _fixture(tmp_path)
    case = _bind(f)
    if change == "target":
        case["resolution"]["targetNodeId"] = "baseline"
    elif change == "units":
        case["nodes"][0]["units"] = "USD million"
    elif change == "period":
        case["resolution"]["horizon"] = "2028-12-31"
    elif change == "topology":
        case["mechanisms"][0]["inputNodeIds"].reverse()
    elif change == "value":
        case["nodes"][0].update(value=246, range={"low": 246, "high": 246})
    elif change == "parameter":
        case["mechanisms"][0]["parameters"]["coefficients"][0]["high"] = 2
    elif change == "basis":
        case["mechanisms"][0]["parameters"]["coefficients"][0]["basis"] = "observed"
    else:
        case["actors"][0]["levers"][0]["nodeId"] = "baseline"
    with pytest.raises((wa.AnchorError, ValueError)):
        runtime.run_paths(
            case, paths=1, periods=1, anchor_context=f["context"], decision_provider=lambda _: pytest.fail("called")
        )


@pytest.mark.parametrize(
    "options",
    [
        {"adapter_version": "made-up/v9"},
        {"template_version": "v2"},
        {"parameter_unit": fixtures.unit()},
        {"unready": True},
    ],
)
def test_policy_declaration_does_not_install_semantics(tmp_path, options):
    f = _fixture(tmp_path, **options)
    with pytest.raises(wa.AnchorError):
        _bind(f)


def test_forecast_stays_estimated_and_range_has_no_invented_point(tmp_path):
    f = _fixture(tmp_path / "forecast", value_kind="third_party_forecast")
    node = _bind(f)["nodes"][0]
    assert node["basis"] == "estimated" and node["status"] == "contested"
    assert "third_party_forecast" in node["gap"]
    g = _fixture(tmp_path / "range", range_value=True)
    ranged = _bind(g)["nodes"][0]
    assert ranged["value"] is None and ranged["range"] == {"low": 10, "high": 247.5}


def test_whole_callback_payload_invariant_to_unqualified_self_and_probability(tmp_path):
    a = _fixture(tmp_path / "a", hidden="PRIVATE_SELF_A")
    b = _fixture(tmp_path / "b", hidden="PRIVATE_SELF_B")
    ca, cb = _bind(a), _bind(b)
    cb["assessments"][0]["scenarioWeights"] = {"below": 0.23, "above": 0.77}
    ca["actors"][0]["objectives"] = []
    seen = [[], []]
    results = []
    for i, (case, f) in enumerate(((ca, a), (cb, b))):
        results.append(
            runtime.run_paths(
                case,
                paths=1,
                periods=2,
                anchor_context=f["context"],
                decision_provider=lambda observation, i=i: seen[i].append(observation) or [],
            )
        )
    assert fixtures.dump(seen[0]) == fixtures.dump(seen[1])
    assert results[0]["paths"] == results[1]["paths"]


def test_omitted_and_none_context_preserve_bytes_rng_and_calls(monkeypatch):
    case = json.loads((Path(__file__).parent / "fixtures/target_case.json").read_text())
    monkeypatch.setattr(host, "validate_anchor_context", lambda *a, **kw: pytest.fail("off anchor call"))
    monkeypatch.setattr(adapter, "validate_anchored_case", lambda *a, **kw: pytest.fail("off adapter call"))
    counts = []
    original = runtime.random.Random

    class Counted(original):
        def random(self):
            counts[-1] += 1
            return super().random()

    monkeypatch.setattr(runtime.random, "Random", Counted)
    counts.append(0)
    first = runtime.run_paths(case, paths=2, periods=3, seed=7)
    counts.append(0)
    second = runtime.run_paths(case, paths=2, periods=3, seed=7, anchor_context=None)
    assert fixtures.dump(first) == fixtures.dump(second) and counts[0] == counts[1]
    assert "worldAnchor" not in first


def test_runtime_commitment_retains_protocol_and_initial_plan_is_excluded(tmp_path):
    f = _fixture(tmp_path)
    case = _bind(f)
    seen = []

    def decide(obs):
        seen.append(obs)
        return (
            {"kind": "commitment", "actorId": "regulator", "leverId": "mandate", "value": 20, "duePeriod": 2}
            if obs["period"] == 1
            else []
        )

    output = runtime.run_paths(
        case, paths=1, periods=3, identity_mode="named", anchor_context=f["context"], decision_provider=decide
    )
    assert seen[0]["plans"] == []
    assert seen[1]["plans"][0]["planId"].startswith("commitment-")
    assert output["paths"][0]["targetValue"] == 267.5


def test_forged_numeric_index_is_not_evidence(tmp_path):
    f = _fixture(tmp_path)
    arguments = _args(f)
    arguments["index"] = f["index"].snapshot()
    with pytest.raises(wa.AnchorError):
        adapter.apply_anchors_to_case(f["case"], **arguments)


@pytest.mark.parametrize(
    "field", ["entity_id", "metric_id", "denominator_id", "geography_id", "unit", "reference_period"]
)
def test_same_number_wrong_identity_cannot_bind(tmp_path, field):
    def mutate(row, requirement):
        if requirement["kind"] != "baseline" or requirement["consumers"][0]["object_id"] != "baseline":
            return
        if field == "unit":
            row["identity"]["unit"]["scale"] = "1000000"
        elif field == "reference_period":
            row["identity"][field] = fixtures.identity(2024)["reference_period"]
        else:
            row["identity"][field] = "wrong-identity"

    f = _fixture(tmp_path, observation_mutation=mutate)
    with pytest.raises(wa.AnchorError) as error:
        _bind(f)
    assert error.value.code == "E_NOT_READY"


def test_rival_private_state_cannot_change_whole_actor_payload(tmp_path):
    f = _fixture(tmp_path / "first", rival_value=3)
    g = _fixture(tmp_path / "second", rival_value=7)
    payloads, decisions = [], []
    for source in (f, g):
        own = []

        def decide(obs):
            if obs["actorId"] == "regulator":
                own.append(obs)
                return {"actorId": "regulator", "leverId": "mandate", "value": 20}
            return []

        output = runtime.run_paths(
            _bind(source),
            paths=1,
            periods=2,
            lookahead=True,
            identity_mode="named",
            anchor_context=source["context"],
            decision_provider=decide,
        )
        payloads.append(own)
        decisions.append([r for r in output["paths"][0]["decisions"] if r["actorId"] == "regulator"])
    assert fixtures.dump(payloads[0]) == fixtures.dump(payloads[1])
    assert decisions[0] == decisions[1]
    assert all("target" not in obs["values"] and "rival-state" not in obs["values"] for obs in payloads[0])


def test_simultaneous_actor_observations_precede_actions(tmp_path):
    f = _fixture(tmp_path, rival_value=3, rival_private=False)
    seen = []

    def decide(obs):
        seen.append(obs)
        return {
            "actorId": obs["actorId"],
            "leverId": "mandate" if obs["actorId"] == "regulator" else "rival-lever",
            "value": 20,
        }

    output = runtime.run_paths(
        _bind(f), paths=1, periods=2, identity_mode="named", anchor_context=f["context"], decision_provider=decide
    )
    first = [obs for obs in seen if obs["period"] == 1]
    assert len(first) == 2 and all(obs["values"]["control"] == 10 for obs in first)
    assert all(obs["values"]["rival-state"] == 3 for obs in first)
    later = [obs for obs in seen if obs["period"] == 2]
    assert len(later) == 2 and all(
        obs["values"]["control"] == 20 and obs["values"]["rival-state"] == 20 for obs in later
    )
    assert all("target" not in obs["values"] for obs in seen)
    assert output["paths"][0]["targetValue"] == 287.5


def test_admitted_plan_fires_at_bound_period_and_actor_free_case_stays_empty(tmp_path):
    f = _fixture(tmp_path / "plan", admitted_plan=True)
    output = runtime.run_paths(
        _bind(f), paths=1, periods=3, identity_mode="named", anchor_context=f["context"], decision_provider=lambda _: []
    )
    assert output["paths"][0]["trajectory"][1]["values"]["control"] == 10
    assert output["paths"][0]["trajectory"][2]["values"]["control"] == 20
    g = _fixture(tmp_path / "empty", actor_free=True)
    case = _bind(g)
    assert case["actors"] == []
    result = runtime.run_paths(
        case, paths=1, periods=2, anchor_context=g["context"], decision_provider=lambda _: pytest.fail("invented actor")
    )
    assert result["paths"][0]["targetValue"] == result["baseline"]["targetValue"] == 257.5


def test_admitted_claim_closure_accepts_new_posterior_without_candidate_claims(tmp_path):
    f = _fixture(tmp_path)
    case = _bind(f)
    claim = case["claims"][0]
    assert claim["status"] == "reported" and claim["claimId"].startswith("anchor_")
    case["assessments"].append(
        {
            "assessmentId": "posterior",
            "version": 2,
            "kind": "posterior",
            "scenarioWeights": {"below": 0.4, "above": 0.6},
            "updates": [
                {
                    "evidenceId": claim["claimId"],
                    "nodeId": claim["nodeId"],
                    "direction": direction,
                    "size": 0.1,
                    "oldWeight": 0.5,
                    "newWeight": weight,
                    "scenarioId": scenario,
                    "reason": "Admitted synthetic evidence.",
                }
                for direction, weight, scenario in (("decrease", 0.4, "below"), ("increase", 0.6, "above"))
            ],
        }
    )
    assert adapter.validate_anchored_case(case, **_args(f)) == case


def test_initial_actor_observation_is_time_gated_and_case_authenticated(tmp_path):
    f = _fixture(tmp_path)
    case = _bind(f)
    state = {"baseline": 247.5, "control": 10, "target": 257.5}
    with pytest.raises(wa.AnchorError, match="before_simulation_cutoff"):
        runtime.actor_observation(case, state, "regulator", anchor_context=f["context"], at="2026-10-25T00:00:00Z")
    current = runtime.actor_observation(case, state, "regulator", anchor_context=f["context"], at=f["scope"]["cutoff"])
    assert current["values"]["baseline"] == 247.5 and current["anchorItems"]
    case["actors"][0]["constraints"]["capacity"] = 123
    with pytest.raises(wa.AnchorError):
        runtime.safe_observation(case, state, "regulator", anchor_context=f["context"], at=f["scope"]["cutoff"])


def test_archived_off_reference_bytes_rng_and_calls(monkeypatch):
    """Supply archived source JSON through stdin with -s, under the same guard."""
    if type(sys.stdin).__name__ == "DontReadFromInput":
        pytest.skip("archived source supplied through stdin in the separate off-reference gate")
    payload = json.loads(sys.stdin.read(256 * 1024))
    assert payload["revision"] == "9916b3be"
    previous_actors = types.ModuleType("app.services._target_actors_reference")
    previous_actors.__package__ = "app.services"
    exec(compile(payload["actors"], "<archived-target-actors>", "exec"), previous_actors.__dict__)
    monkeypatch.setitem(sys.modules, previous_actors.__name__, previous_actors)
    previous = types.ModuleType("app.services._target_simulation_reference")
    previous.__package__ = "app.services"
    source = payload["simulation"].replace("from .target_actors import", "from ._target_actors_reference import")
    exec(compile(source, "<archived-target-simulation>", "exec"), previous.__dict__)
    original_rng = runtime.random.Random
    counts = []

    class Counted(original_rng):
        def random(self):
            counts[-1] += 1
            return super().random()

    monkeypatch.setattr(runtime.random, "Random", Counted)
    for mode in ("named", "opaque"):
        for lookahead in (False, True):
            for actor_mode in ("rule", "llm"):
                case = json.loads((Path(__file__).parent / "fixtures/target_case.json").read_text())
                for actor in case["actors"]:
                    actor["decisionRule"]["kind"] = actor_mode
                results, payloads = [], []
                for module in (previous, runtime):
                    counts.append(0)
                    seen = []

                    def decide(obs):
                        seen.append(obs)
                        lever = obs["levers"][0]
                        return {"actorId": obs["actorId"], "leverId": lever["leverId"], "value": lever["maximum"]}

                    results.append(
                        module.run_paths(
                            case,
                            paths=3,
                            periods=4,
                            seed=37,
                            identity_mode=mode,
                            lookahead=lookahead,
                            decision_provider=decide if actor_mode == "llm" else None,
                        )
                    )
                    payloads.append(seen)
                assert fixtures.dump(results[0]) == fixtures.dump(results[1])
                assert fixtures.dump(payloads[0]) == fixtures.dump(payloads[1])
                assert counts[-1] == counts[-2]


def test_review_hidden_actor_control_is_not_executable(tmp_path):
    def hidden(row, requirement):
        if requirement["consumers"][0]["field"] == "constraints.capacity":
            row["audience"] = {"kind": "analyst", "actor_refs": []}

    f = _fixture(
        tmp_path,
        control={
            "field": "constraints.capacity",
            "value": "10",
            "unit": {
                "id": "capacity",
                "dimension": "dimensionless",
                "scale": "1",
                "currency": None,
                "price_basis": "not_applicable",
                "base_period": None,
            },
        },
        observation_mutation=hidden,
    )
    with pytest.raises(wa.AnchorError) as error:
        _bind(f)
    assert error.value.code == "E_PRIVACY"


def test_review_unadmitted_initial_plan_condition_rejected(tmp_path):
    def conditional(case):
        case["actors"][0]["plans"][0]["condition"] = {"nodeId": "control", "operator": "gte", "value": 10}

    f = _fixture(tmp_path, admitted_plan=True, mutation=conditional)
    with pytest.raises(wa.AnchorError, match="unsupported_plan_condition"):
        _bind(f)


@pytest.mark.parametrize(
    "mechanism_kind,unit",
    [
        (
            "growth",
            {
                "id": "percent",
                "dimension": "dimensionless",
                "scale": "0.01",
                "currency": None,
                "price_basis": "not_applicable",
                "base_period": None,
            },
        ),
        ("sum", {**fixtures.unit(), "id": "USD million", "scale": "1000000"}),
    ],
)
def test_review_mechanism_dimensions_and_scales_fail_closed(tmp_path, mechanism_kind, unit):
    f = _fixture(tmp_path, actor_free=True, mechanism_kind=mechanism_kind, primitive_unit=unit)
    with pytest.raises(wa.AnchorError):
        _bind(f)


def test_review_actor_due_period_cannot_be_days(tmp_path):
    f = _fixture(
        tmp_path,
        control={
            "field": "decisionRule.cadencePeriods",
            "value": "2",
            "unit": {
                "id": "days",
                "dimension": "time",
                "scale": "1",
                "currency": None,
                "price_basis": "not_applicable",
                "base_period": None,
            },
        },
    )
    with pytest.raises(wa.AnchorError):
        _bind(f)


def test_review_matching_display_content_cannot_reauthorize_hidden_binding(tmp_path):
    f = _fixture(tmp_path, matching_visibility=True)
    case = _bind(f)
    seen = []
    runtime.run_paths(
        case,
        paths=1,
        periods=1,
        identity_mode="named",
        anchor_context=f["context"],
        decision_provider=lambda obs: seen.append(obs) or [],
    )
    assert seen[0]["values"]["public-copy"] == 247.5
    assert "baseline" not in seen[0]["values"] and "target" not in seen[0]["values"]
    visible = adapter._visible_ids(f["pack"], "regulator", f["scope"]["cutoff"])
    pair = [o for o in f["pack"]["observations"] if o["identity"] and o["identity"]["metric_id"] == "spending"]
    assert len(pair) == 2 and pair[0]["value"] == pair[1]["value"]
    assert sum(o["observation_id"] in visible for o in pair) == 1


def test_review_primitive_target_cannot_overwrite_declared_period_or_basis(tmp_path):
    f = _fixture(tmp_path, actor_free=True, primitive_target=True)
    with pytest.raises(wa.AnchorError):
        _bind(f)


def test_review_pre_cutoff_observation_cannot_disclose_later_control(tmp_path):
    f = _fixture(
        tmp_path,
        control={
            "field": "constraints.capacity",
            "value": "10",
            "unit": {
                "id": "capacity",
                "dimension": "dimensionless",
                "scale": "1",
                "currency": None,
                "price_basis": "not_applicable",
                "base_period": None,
            },
        },
    )
    case = _bind(f)
    with pytest.raises(wa.AnchorError) as error:
        runtime.actor_observation(
            case,
            {"baseline": 247.5, "control": 10, "target": 257.5},
            "regulator",
            anchor_context=f["context"],
            at="2026-10-25T00:00:00Z",
        )
    assert error.value.code == "E_PRIVACY"


def _future_settlement_payloads(tmp_path):
    f = _fixture(tmp_path, external_target_forecast=True)
    case = _bind(f)
    seen = []
    result = runtime.run_paths(
        case,
        paths=1,
        periods=4,
        identity_mode="named",
        lookahead=False,
        anchor_context=f["context"],
        decision_provider=lambda obs: seen.append(obs) or [],
    )
    target = case["resolution"]["targetNodeId"]
    period = f["requirements"]["contract"]["settlement"]["identity"]["reference_period"]
    first_at = runtime._anchor_time(case, f["context"], seen[0]["period"], 4)
    signpost = next(row for row in result["signposts"] if row["nodeId"] == target)
    assert first_at[:10] < period["end"] < signpost["releaseDate"]
    assert target in case["actors"][0]["information"]["nodeIds"]
    assert result["paths"][0]["initialValues"][target] == 257.5
    (tmp_path / "future-settlement-payloads.json").write_text(
        json.dumps(
            {
                "first_observation_at": first_at,
                "target_reference_period": period,
                "settlement_release_date": signpost["releaseDate"],
                "lookahead": False,
                "payloads": seen,
                "computed_initial_target": result["paths"][0]["initialValues"][target],
            },
            indent=2,
        )
    )
    return target, seen


def test_future_settlement_output_is_not_current_actor_knowledge(tmp_path):
    target, seen = _future_settlement_payloads(tmp_path)
    for observation in seen:
        assert target not in observation["values"]
        assert target not in observation["beliefs"]
        assert target not in observation["observedPeriods"]


def test_future_third_party_forecast_remains_an_explicit_quote(tmp_path):
    _, seen = _future_settlement_payloads(tmp_path)
    forecasts = [
        item
        for item in seen[0]["anchorItems"]
        if item["value_kind"] == "third_party_forecast" and item["identity"]["reference_period"]["end"] == "2027-12-31"
    ]
    assert len(forecasts) == 1
    assert forecasts[0]["value"] == {"kind": "number", "value": "247.5"}
    assert seen[0]["values"]["baseline"] == 247.5
    assert "options" not in seen[0]


def _power_unit(symbol, scale):
    return {
        "id": symbol,
        "dimension": "power",
        "scale": str(scale),
        "currency": None,
        "price_basis": "not_applicable",
        "base_period": None,
    }


@pytest.mark.parametrize("symbol,scale", [("W", 1), ("kW", 1000), ("MW", 1000000), ("GW", 1000000000)])
def test_power_units_reach_actual_target_runtime_without_rescaling(tmp_path, symbol, scale):
    f = _fixture(
        tmp_path,
        actor_free=True,
        mechanism_kind="sum",
        quantity_unit=_power_unit(symbol, scale),
        quantities=("176", "80"),
    )
    case = _bind(f)
    assert adapter.validate_anchored_case(case, **_args(f)) == case
    result = runtime.run_paths(case, paths=1, periods=2, anchor_context=f["context"], model_validation="admission")
    assert case["resolution"]["units"] == symbol
    assert [node["value"] for node in case["nodes"][:2]] == [176, 80]
    assert result["paths"][0]["initialValues"]["target"] == 256
    assert result["paths"][0]["targetValue"] == result["baseline"]["targetValue"] == 256


@pytest.mark.parametrize("other,scale", [("W", 1), ("kW", 1000), ("MW", 1000000)])
def test_power_units_do_not_implicitly_convert_mixed_scales(tmp_path, other, scale):
    f = _fixture(
        tmp_path,
        actor_free=True,
        mechanism_kind="sum",
        quantity_unit=_power_unit("GW", 1000000000),
        primitive_unit=_power_unit(other, scale),
        quantities=("176", "80"),
    )
    with pytest.raises(wa.AnchorError, match="mechanism_input_units"):
        _bind(f)


@pytest.mark.parametrize("change", ["scale", "dimension", "currency", "price_basis", "base_period"])
def test_power_unit_metadata_must_match_native_symbol(tmp_path, change):
    unit = _power_unit("GW", 1000000000)
    unit[change] = {
        "scale": "1000000",
        "dimension": "currency",
        "currency": "USD",
        "price_basis": "real",
        "base_period": fixtures.identity(2020)["reference_period"],
    }[change]
    f = _fixture(tmp_path, actor_free=True, mechanism_kind="sum", quantity_unit=unit, quantities=("176", "80"))
    with pytest.raises(wa.AnchorError, match="unit_dimension_or_scale|unit_basis"):
        _bind(f)


@pytest.mark.parametrize("actor_free", [True, False])
def test_research_registry_superset_never_creates_runtime_actors(tmp_path, actor_free):
    # This checks the registry boundary, not the pending text-collection API.
    f = _fixture(tmp_path, actor_free=actor_free, research_dossiers=True)
    case = _bind(f)
    expected = [] if actor_free else ["regulator"]
    assert [a["actorId"] for a in case["actors"]] == expected
    assert adapter.validate_anchored_case(case, **_args(f)) == case
    registry = json.loads(f["index"].artifact_bytes("contract"))["research_actor_registry"]
    assert registry[0]["quoted_public_statement"] == "Regulator has sole authority."
    assert any(a["actor_ref"] == "research-only" for a in f["pack"]["actor_dossiers"])
    seen = []
    result = runtime.run_paths(
        case,
        paths=1,
        periods=2,
        identity_mode="named",
        anchor_context=f["context"],
        decision_provider=lambda obs: seen.append(obs["actorId"]) or [],
    )
    assert set(seen) == set(expected)
    assert set(result["paths"][0]["remainingCapacity"]) == set(expected)
    assert result["paths"][0]["targetValue"] == 257.5
    with pytest.raises(wa.AnchorError, match="actor_registry"):
        adapter.actor_observation_inputs(case, **_args(f), actor_id="research-only", at=f["scope"]["cutoff"])


@pytest.mark.parametrize("fault", ["missing_native", "duplicate_native", "wrong_native_row", "missing_authority"])
def test_research_registry_superset_preserves_native_authority_checks(tmp_path, fault):
    def mutate(rows):
        if fault == "missing_native":
            rows[:] = [row for row in rows if row["actor_ref"] != "regulator"]
        elif fault == "duplicate_native":
            rows.append(deepcopy(next(row for row in rows if row["actor_ref"] == "regulator")))
        elif fault == "wrong_native_row":
            rows[0]["registry_pointer"] = "/research_actor_registry/0"
        else:
            rows[0]["authority"] = []

    f = _fixture(tmp_path, research_dossiers=True, registry_mutation=mutate)
    with pytest.raises(wa.AnchorError) as error:
        _bind(f)
    assert (
        error.value.path
        == {
            "missing_native": "actor_registry",
            "duplicate_native": "duplicate_actor_registry",
            "wrong_native_row": "actor_registry_identity",
            "missing_authority": "missing_authority",
        }[fault]
    )


def test_fixture_run_id_is_bound_before_real_index_and_receipts(tmp_path):
    f = _fixture(tmp_path / "owner", actor_free=True, research_dossiers=True, run_id="pipe_admitted_owner")
    for scoped in (
        f["scope"],
        f["manifest"]["scope"],
        f["requirements"]["scope"],
        f["requirements"]["contract"]["scope"],
        f["index"].snapshot()["scope"],
        f["pack"]["scope"],
    ):
        assert scoped["run_id"] == "pipe_admitted_owner"
    assert all(ref["run_id"] == "pipe_admitted_owner" for ref in f["pack"]["references"])
    assert f["context"].pack["scope"]["run_id"] == "pipe_admitted_owner"
    case = _bind(f)
    assert adapter.validate_anchored_case(case, **_args(f)) == case
    output = runtime.run_paths(case, paths=1, periods=1, anchor_context=f["context"])
    assert output["paths"][0]["targetValue"] == 257.5
    from deerflow_bridge import world_anchor_publication as publication

    assert f["receipts"] and all(type(receipt) is wa.ProducerReceipts for receipt in f["receipts"])
    published = publication.publish_completion(tmp_path / "published", **_args(f), receipts=f["receipts"])
    restored = host.load_research_anchor(
        tmp_path / "published", expected_manifest_sha256=published["manifest_sha256"], expected_scope=f["scope"]
    )
    assert restored.pack["scope"]["run_id"] == "pipe_admitted_owner"
    assert restored.pack_hash == f["context"].pack_hash
    assert runtime.run_paths(case, paths=1, periods=1, anchor_context=restored)["paths"][0]["targetValue"] == 257.5


def test_fixture_omitted_run_id_preserves_default_pack(tmp_path):
    implicit = _fixture(tmp_path / "implicit", actor_free=True)
    explicit = _fixture(tmp_path / "explicit", actor_free=True, run_id=fixtures.scope()["run_id"])
    assert fixtures.dump(implicit["pack"]) == fixtures.dump(explicit["pack"])
    assert _bind(implicit) == _bind(explicit)


def test_unready_fixture_public_receipts_match_unreviewed_pack(tmp_path):
    from deerflow_bridge import world_anchor_publication as publication

    f = _fixture(tmp_path / "gap", actor_free=True, unready=True, run_id="pipe_gap_owner")
    assert f["receipts"] == [] and f["pack"]["producer_manifest_hashes"] == []
    result = publication.publish_completion(tmp_path / "published", **_args(f), receipts=f["receipts"])
    restored = host.load_research_anchor(
        tmp_path / "published", expected_manifest_sha256=result["manifest_sha256"], expected_scope=f["scope"]
    )
    assert restored.pack_hash == f["context"].pack_hash
    with pytest.raises(wa.AnchorError):
        _bind(f)


@pytest.mark.parametrize("lookahead", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_future_target_descendants_are_not_observations_in_actual_callback(tmp_path, lookahead, reverse):
    f = _fixture(tmp_path, target_descendants=True, reverse_mechanisms=reverse, external_target_forecast=True)
    case = _bind(f)
    blocked = {"target", "target-alias", "target-copy"}
    seen = []

    def decide(obs):
        seen.append(obs)
        if obs["period"] != 1:
            return []
        return (
            [
                {
                    "kind": "signal",
                    "actorId": "regulator",
                    "nodeId": nid,
                    "value": 257.5,
                    "recipients": ["regulator"],
                    "duePeriod": 2,
                }
                for nid in sorted(blocked)
            ]
            + [
                {
                    "kind": "commitment",
                    "actorId": "regulator",
                    "leverId": "mandate",
                    "value": 20,
                    "duePeriod": 2,
                    "condition": {"nodeId": nid, "operator": "gte", "value": 0},
                }
                for nid in sorted(blocked)
            ]
            + [{"actorId": "regulator", "leverId": "mandate", "value": 20}]
        )

    output = runtime.run_paths(
        case,
        paths=1,
        periods=3,
        lookahead=lookahead,
        identity_mode="named",
        anchor_context=f["context"],
        decision_provider=decide,
    )
    assert len(seen) == 3
    for obs in seen:
        for field in ("values", "beliefs", "observedPeriods"):
            assert not blocked & obs[field].keys()
        assert obs["values"]["baseline"] == 247.5
        assert "current-total" in obs["values"]
        assert obs["signals"] == obs["plans"] == []
        assert ("options" in obs) == lookahead
        if lookahead:
            assert obs["options"] and all(o["informationBasis"] == "actor_visible_beliefs" for o in obs["options"])
        assert any(i["value_kind"] == "third_party_forecast" for i in obs["anchorItems"])
    decisions = output["paths"][0]["decisions"]
    assert sum(d["status"] == "blocked" and d.get("kind") == "signal" for d in decisions) == 3
    assert sum(d["status"] == "blocked" and d.get("kind") == "commitment" for d in decisions) == 3
    assert output["paths"][0]["targetValue"] == 267.5
    assert output["paths"][0]["trajectory"][-1]["values"]["target-copy"] == 267.5


@pytest.mark.parametrize("at", ["2027-12-31T23:59:59Z", "2028-03-31T00:00:00Z"])
def test_future_target_cannot_become_fact_by_date_or_forged_own_state(tmp_path, at):
    def own_target(case):
        next(n for n in case["nodes"] if n["nodeId"] == "target")["ownerActorId"] = "regulator"

    f = _fixture(tmp_path, mutation=own_target, target_descendants=True, reverse_mechanisms=True)
    case = _bind(f)
    blocked = {"target", "target-alias", "target-copy"}
    values = {
        n["nodeId"]: 257.5 if n["nodeId"] in blocked | {"current-total"} else 247.5 if n["nodeId"] == "baseline" else 10
        for n in case["nodes"]
    }
    state = {
        "values": values,
        "history": [{"period": 0, "values": values}, {"period": 3, "values": values}],
        "simulatedOwnNodeIds": {"regulator": blocked},
        "signals": [
            {
                "nodeId": "target",
                "actorId": "regulator",
                "recipients": ["regulator"],
                "period": 2,
                "duePeriod": 4,
                "value": 257.5,
            }
        ],
        "plans": {
            "regulator": [
                {
                    "planId": "forged",
                    "leverId": "mandate",
                    "value": 20,
                    "duePeriod": 4,
                    "condition": {"nodeId": "target-copy", "operator": "gte", "value": 0},
                }
            ]
        },
        "simulatedPlanIds": {"regulator": ["forged"]},
    }
    obs = runtime.actor_observation(case, state, "regulator", period=3, at=at, anchor_context=f["context"])
    for field in ("values", "beliefs", "observedPeriods"):
        assert not blocked & obs[field].keys()
    assert obs["signals"] == obs["plans"] == []
    assert obs["values"]["baseline"] == 247.5


@pytest.mark.parametrize("reverse", [False, True])
def test_authenticated_intermediate_identity_supports_milestone_target_path(tmp_path, reverse):
    f = _fixture(
        tmp_path,
        actor_free=True,
        mechanism_kind="sum",
        milestone=True,
        declared_node_identities=True,
        reverse_mechanisms=reverse,
    )
    assert not any(
        r["kind"] == "baseline" and r["consumers"][0]["object_id"] in {"milestone", "intermediate"}
        for r in f["requirements"]["requirements"]
    )
    case = _bind(f)
    assert adapter.validate_anchored_case(case, **_args(f)) == case
    assert next(n for n in case["nodes"] if n["nodeId"] == "milestone")["value"] is None
    output = runtime.run_paths(case, paths=1, periods=3, model_validation="admission", anchor_context=f["context"])
    trajectory = output["paths"][0]["trajectory"]
    assert [r["values"]["milestone"] for r in trajectory] == [0, 0, 10, 10]
    assert [r["values"]["target"] for r in trajectory] == [257.5, 257.5, 267.5, 267.5]
    assert output["paths"][0]["parameters"]["milestone-switch"]["milestonePeriod"] == 2


@pytest.mark.parametrize("fault", ["missing", "unknown_node", "unit", "scale", "primitive_identity", "target_period"])
def test_intermediate_identity_cannot_invent_nodes_or_change_existing_contract(tmp_path, fault):
    def change(identities):
        if fault == "unknown_node":
            identities["invented"] = deepcopy(identities["milestone"])
        elif fault == "unit":
            identities["milestone"]["unit"]["id"] = "fraction"
        elif fault == "scale":
            identities["milestone"]["unit"]["scale"] = "1000000"
        elif fault == "primitive_identity":
            identities["baseline"]["entity_id"] = "unrelated"
        elif fault == "target_period":
            identities["target"]["reference_period"] = fixtures.identity(2028)["reference_period"]

    f = _fixture(
        tmp_path,
        actor_free=True,
        mechanism_kind="sum",
        milestone=True,
        declared_node_identities=fault != "missing",
        identity_mutation=change,
    )
    with pytest.raises(wa.AnchorError):
        _bind(f)


@pytest.mark.parametrize("actor_free", [False, True])
def test_research_notes_are_retained_without_native_actor_or_runtime_authority(tmp_path, actor_free):
    from deerflow_bridge import world_anchor_publication as publication

    f = _fixture(tmp_path / "source", actor_free=actor_free, research_dossiers=True, research_notes=True)
    case = _bind(f)
    note_ids = {
        r["requirement_id"]
        for r in f["requirements"]["requirements"]
        if any(c["role"] == "research_note" for c in r["consumers"])
    }
    assert len(note_ids) == 3
    assert all(b["status"] == "bound" for b in f["pack"]["bindings"] if b["requirement_id"] in note_ids)
    projection = wa.engine_projection(**_args(f), engine=adapter.ENGINE)
    assert not note_ids & {b["requirement_id"] for b in projection["bindings"]}
    assert f["pack"]["research_items"] and all(item["executable"] is False for item in f["pack"]["research_items"])
    receipt = publication.publish_completion(tmp_path / "published", **_args(f), receipts=f["receipts"])
    context = host.load_research_anchor(tmp_path / "published", expected_manifest_sha256=receipt["manifest_sha256"])
    assert context.pack["research_items"] == f["pack"]["research_items"]
    seen = []
    result = runtime.run_paths(
        case,
        paths=1,
        periods=2,
        identity_mode="named",
        anchor_context=context,
        decision_provider=lambda obs: seen.append(obs) or [],
    )
    assert set(result["paths"][0]["remainingCapacity"]) == (set() if actor_free else {"regulator"})
    assert len(seen) == (0 if actor_free else 2)
    for obs in seen:
        assert "research-only" not in json.dumps(obs)
        assert not any(
            item["value"] == {"kind": "text", "value": "The admitted plan chooses 20 at period 2."}
            for item in obs["anchorItems"]
        )
    assert result["paths"][0]["targetValue"] == 257.5


def test_admitted_actor_authority_replaces_old_claim_link_and_revalidates_assessment(tmp_path):
    from deerflow_bridge import target_research

    f = _fixture(tmp_path, primary_authority=True)
    original = f["case"]
    assert (
        target_research.build_case(
            {"forecastCase": original},
            {"findings": []},
            original["sources"],
            question=original["question"],
            as_of=original["asOf"],
        )
        == original
    )
    case = _bind(f)
    assert "C3" not in {c["claimId"] for c in case["claims"]}
    actor = case["actors"][0]
    assert "C3" not in actor["decisionBasis"]
    claims = {c["claimId"]: c for c in case["claims"]}
    authority_ids = [cid for cid in claims if cid.startswith("anchor_authority_") and cid in actor["decisionBasis"]]
    assert authority_ids and all(
        claims[cid]["nodeId"] == "control" and claims[cid]["status"] == "reported" for cid in authority_ids
    )
    assert set(authority_ids) <= set(next(n for n in case["nodes"] if n["nodeId"] == "control")["claimIds"])
    updated = target_research.build_case(
        {"forecastCase": case},
        {
            "assessment": {
                "assessmentId": "posterior-2",
                "version": 2,
                "kind": "posterior",
                "scenarioWeights": {"below": 0.5, "above": 0.5},
                "updates": [],
            }
        },
        case["sources"],
        question=case["question"],
        as_of=case["asOf"],
    )
    assert adapter.validate_anchored_case(updated, **_args(f)) == updated
    result = runtime.run_paths(
        updated,
        paths=1,
        periods=2,
        identity_mode="named",
        anchor_context=f["context"],
        decision_provider=lambda obs: {"actorId": obs["actorId"], "leverId": "mandate", "value": 20},
    )
    assert result["paths"][0]["targetValue"] == 267.5


def test_secondary_actor_authority_does_not_pass_primary_revalidation(tmp_path):
    from deerflow_bridge import target_research

    f = _fixture(tmp_path)
    case = _bind(f)
    with pytest.raises(ValueError, match="primary claim for every lever"):
        target_research.build_case(
            {"forecastCase": case}, {"findings": []}, case["sources"], question=case["question"], as_of=case["asOf"]
        )


@pytest.mark.parametrize("fault", ["basis", "claim_node", "claim_quote", "claim_source", "missing_authority"])
def test_compiled_actor_authority_closure_cannot_be_replaced_or_forged(tmp_path, fault):
    f = _fixture(
        tmp_path,
        primary_authority=True,
        registry_mutation=(lambda rows: rows[0].update(authority=[])) if fault == "missing_authority" else None,
    )
    if fault == "missing_authority":
        with pytest.raises(wa.AnchorError, match="missing_authority"):
            _bind(f)
        return
    case = _bind(f)
    claim = next(c for c in case["claims"] if c["claimId"].startswith("anchor_authority_"))
    if fault == "basis":
        case["actors"][0]["decisionBasis"] = "C3"
    elif fault == "claim_node":
        claim["nodeId"] = "baseline"
    elif fault == "claim_quote":
        claim["passage"] = "Unadmitted utility or authority."
    else:
        claim["sourceIds"] = ["S1"]
    with pytest.raises(wa.AnchorError):
        adapter.validate_anchored_case(case, **_args(f))


@pytest.mark.parametrize("verdict", ["unsupported", "ambiguous", "missing"])
def test_actor_authority_requires_its_own_independent_field_approval(tmp_path, verdict):
    f = _fixture(tmp_path, primary_authority=True, authority_review=verdict)
    with pytest.raises(wa.AnchorError, match="unapproved_actor_authority"):
        _bind(f)


def test_unrelated_primary_reference_cannot_promote_secondary_authority(tmp_path):
    from deerflow_bridge import target_research

    f = _fixture(tmp_path, mixed_authority_sources=True)
    case = _bind(f)
    claims = [c for c in case["claims"] if c["claimId"].startswith("anchor_authority_")]
    sources = {s["sourceId"]: s for s in case["sources"]}
    assert claims and all(sources[sid]["tier"] == "secondary" for c in claims for sid in c["sourceIds"])
    assert all("unrelated primary record" not in c["passage"] for c in claims)
    with pytest.raises(ValueError, match="primary claim for every lever"):
        target_research.build_case(
            {"forecastCase": case}, {"findings": []}, case["sources"], question=case["question"], as_of=case["asOf"]
        )


def _public_provenance_view(case, trace, pack):
    """Test consumer: permission follows selected evidence, never node visibility."""
    observations = {o["observation_id"]: o for o in pack["observations"]}
    references = {r["ref_id"]: r for r in pack["references"]}
    sources = {s["source_key"]: s for s in pack["sources"]}
    native_sources = {s["sourceId"]: s for s in case["sources"]}

    def permitted(link):
        obs = observations[link["observation_id"]]
        return (
            obs["audience"]["kind"] == "public"
            and obs["value_kind"] in {"observed", "reported", "third_party_forecast"}
            and obs["producer_class"] not in {"research_analyst", "model_prior", "simulation"}
            and all(
                sources[references[r]["source_key"]]["audience"]["kind"] == "public"
                for r in link.get("ref_ids", [link.get("ref_id")])
            )
        )

    permitted_sources = {
        sid for sid, links in trace["sources"].items() if links and all(permitted(link) for link in links)
    }
    claims = [
        {"passage": claim["passage"], "urls": sorted(native_sources[s]["url"] for s in claim["sourceIds"])}
        for claim in case["claims"]
        if permitted(trace["claims"][claim["claimId"]]) and set(claim["sourceIds"]) <= permitted_sources
    ]

    def public_links(mapping):
        return sorted(
            native_sources[s]["url"]
            for s, links in mapping.items()
            if s in permitted_sources and links and all(permitted(link) for link in links)
        )

    return {
        "claims": sorted(claims, key=lambda c: (c["passage"], c["urls"])),
        "node_sources": {nid: public_links(links) for nid, links in trace["node_sources"].items()},
        "parameter_sources": {
            mid: {slot: public_links(links) for slot, links in slots.items()}
            for mid, slots in trace["parameter_sources"].items()
        },
    }


@pytest.mark.parametrize("private_parameter", [None, "coefficient:control"])
def test_exact_provenance_excludes_private_authority_from_public_node(tmp_path, private_parameter):
    from deerflow_bridge import target_research

    views, public_bytes = [], []
    for label in ("PRIVATE_AUTHORITY_A", "PRIVATE_AUTHORITY_B"):
        secret = {
            "text": f"Regulator has sole authority over control under {label}. Its reported coefficient is 1.",
            "url": f"https://private.example.test/{label}",
        }
        f = _fixture(
            tmp_path / label, primary_authority=True, private_authority=secret, private_parameter=private_parameter
        )
        public_bytes.append(f["index"].artifact_bytes("page"))
        assert label.encode() not in public_bytes[-1] and b"sole authority" not in public_bytes[-1]
        case = _bind(f)
        original = deepcopy(case)
        trace = adapter.anchored_case_provenance(case, **_args(f))
        assert case == original and adapter.validate_anchored_case(case, **_args(f)) == case
        assert set(trace["claims"]) == {c["claimId"] for c in case["claims"]}
        assert set(trace["sources"]) == {s["sourceId"] for s in case["sources"]}
        observations = {o["observation_id"]: o for o in f["pack"]["observations"]}
        claims = {c["claimId"]: c for c in case["claims"]}
        private_links = [p for p in trace["claims"].values() if p["origin"] == "actor_authority"]
        assert private_links and all(
            p["node_id"] == "control" and observations[p["observation_id"]]["audience"]["kind"] == "actors"
            for p in private_links
        )
        assert next(n for n in case["nodes"] if n["nodeId"] == "control")["visibility"] == "public"
        for cid, link in trace["claims"].items():
            assert link["selector"]["quote"] == claims[cid]["passage"]
            assert link["source_ids"] == claims[cid]["sourceIds"]
            assert link["ref_id"] in observations[link["observation_id"]]["ref_ids"]
        assert trace["sources"]["S2"] == [] and trace["node_sources"]["control"]["S2"] == []
        for mechanism in case["mechanisms"]:
            for slot, links in trace["parameter_sources"][mechanism["mechanismId"]].items():
                scalar = (
                    mechanism["parameters"]["coefficients"][mechanism["inputNodeIds"].index(slot.split(":", 1)[1])]
                    if slot.startswith("coefficient:")
                    else mechanism["parameters"][slot]
                )
                assert set(links) == set(scalar["sourceIds"])
        assert (
            target_research.build_case(
                {"forecastCase": case}, {"findings": []}, case["sources"], question=case["question"], as_of=case["asOf"]
            )
            == case
        )
        seen = []

        def decide(obs, seen=seen):
            seen.append(obs)
            return {"actorId": obs["actorId"], "leverId": "mandate", "value": 20}

        result = runtime.run_paths(
            case, paths=1, periods=2, identity_mode="named", anchor_context=f["context"], decision_provider=decide
        )
        assert result["paths"][0]["targetValue"] == 267.5
        assert any(label in item["text"] for item in seen[0]["anchorItems"])
        view = _public_provenance_view(case, trace, f["pack"])
        assert label not in json.dumps(view) and secret["url"] not in json.dumps(view)
        assert any("baseline 247.5" in claim["passage"] for claim in view["claims"])
        assert view["node_sources"]["baseline"] == ["https://example.test/report"]
        assert view["node_sources"]["control"] == ["https://example.test/report"]
        assert view["parameter_sources"]["total"]["coefficient:baseline"] == ["https://example.test/report"]
        if private_parameter:
            assert view["parameter_sources"]["total"][private_parameter] == []
        views.append(view)
        trace["claims"].clear()
        assert adapter.anchored_case_provenance(case, **_args(f))["claims"]
    assert public_bytes[0] == public_bytes[1] and views[0] == views[1]


def test_provenance_requires_exact_validated_case_and_inherited_refs_stay_unmapped(tmp_path):
    f = _fixture(tmp_path, primary_authority=True)
    case = _bind(f)
    trace = adapter.anchored_case_provenance(case, **_args(f))
    assert trace["case_hash"] == adapter.fc.case_hash(case) and trace["pack_hash"] == f["context"].pack_hash
    assert trace["sources"]["S1"] == []
    case["claims"][0]["passage"] = "Unadmitted content."
    with pytest.raises(wa.AnchorError):
        adapter.anchored_case_provenance(case, **_args(f))
