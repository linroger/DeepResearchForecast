"""Real publication -> sealed runtime -> saved world -> public record/report.

Run only with main_offline_pytest.py. All evidence is synthetic, with the real
index/review/publication/host-loader/WorldModel and deterministic report APIs.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random

import pytest

from app.services import simulation_record as sr, simulation_record_contract as rc
from app.services import target_report as tr, world_anchor as host
from app.services.official_data import bind_simulation_research, bridge_module
from app.services.simulation_manager import SimulationManager, build_simulation_config_seal
from app.services.world_model import WorldModel
from test_target_simulation import case as _target_case
from test_world_anchor_reflexive import _anchored_fixture, _anchor_config

target_case = _target_case


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")


@pytest.fixture
def saved(tmp_path, monkeypatch, target_case, request):
    from app.config import Config
    import test_world_anchor as fixtures
    variant = getattr(request, "param", None)
    if variant == "private":
        original_review = fixtures.review_fixture
        monkeypatch.setattr(fixtures, "review_fixture", lambda f: original_review(
            f, audience={"kind": "analyst", "actor_refs": []}))
    elif variant == "gap":
        original_fixture = fixtures.make_fixture
        def with_gap(*args, **kwargs):
            f = original_fixture(*args, **kwargs)
            contract = f["requirements"]["contract"]
            row = deepcopy(contract["terms"][1])
            row.update(origin_pointer="/terms/2", kind="indicator", required=False,
                       consumers=[fixtures.consumer("oasis-legacy", "observation", "target", "value")])
            row["identity"]["metric_id"] = "missing_public_indicator"
            contract["terms"].append(row)
            return f
        monkeypatch.setattr(fixtures, "make_fixture", with_gap)
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    original, case = _anchored_fixture(fixture, target_case, temporal=True)
    pipelines = tmp_path / "pipelines"
    handoff = pipelines / "pipe_anchor" / "handoff"
    pub = bridge_module("world_anchor_publication")
    receipts = {h.manifest_hash: h for h in original.index._review_pins.values()}
    publication = pub.publish_completion(handoff, original.pack, requirements=original.requirements,
        index=original.index, policy=original.policy, receipts=tuple(receipts.values()))
    context = host.load_research_anchor(handoff, expected_manifest_sha256=publication["manifest_sha256"])
    sims = tmp_path / "simulations"
    directory = sims / "sim_anchor"
    directory.mkdir(parents=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sims))
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(pipelines))
    (directory / "actor_cast_manifest.json").write_bytes(original._cast_bytes)
    context = host.bind_actor_cast(context, directory)
    config = _anchor_config(monkeypatch, context, case).to_dict()
    config["simulation_id"] = "sim_anchor"
    write(directory / "simulation_config.json", config)
    for name, content in {"research_report.md": "Synthetic research source.", "actors.json": '{"actors":[]}',
                          "sources.json": "[]", "actor_dossier.md": "Synthetic source registry."}.items():
        (handoff / name).write_text(content)
    bind_simulation_research("sim_anchor", handoff, pipeline_id=context.pack["scope"]["run_id"])
    config_sha, manifest_sha = build_simulation_config_seal(str(directory), simulation_id="sim_anchor",
        actor_cast_manifest_sha256=hashlib.sha256(original._cast_bytes).hexdigest(),
        actor_context_manifest_sha256=None, actor_role_manifest_sha256={})
    write(directory / "state.json", {"simulation_id": "sim_anchor", "simulation_engine": "oasis-legacy",
        "simulation_config_sha256": config_sha, "simulation_config_manifest_sha256": manifest_sha})
    world = WorldModel.from_seed(config["world_model"], config["agent_configs"], anchor_context=context)
    for rnd, end in ((1, "2026-10-31"), (2, "2026-11-30")):
        world.start_round(rnd, {"period_start": "2026-10-28" if rnd == 1 else "2026-11-01", "period_end": end})
        world.evaluate_target_projection(rnd, random.Random(7))
    world.committed_round = 2
    write(directory / "world_state.json", {"simulation_id": "sim_anchor", "world": world.to_dict(),
                                           "summary": {"rounds_committed": 2}})
    write(directory / "run_summary.json", {"simulation_id": "sim_anchor", "simulation_health": "ok", "total_rounds": 2})
    write(directory / "world_state_trajectory.json", {"validity": "valid"})
    (directory / "world_state_history.jsonl").write_text("\n".join(json.dumps({
        "round": r, "period_label": "P" + str(r), "arbiter": {"status": "applied"},
        "narrative": "", "diff": {}, "period": {"period_end": end}})
        for r, end in ((1, "2026-10-31"), (2, "2026-11-30"))) + "\n")
    monkeypatch.setattr(sr, "_utcnow", lambda: "2026-10-29T00:00:00Z")
    # The report's existing research channel is public, independent of privileged
    # anchor evidence. Its original generic fixture passage included all classes.
    case["claims"][0]["passage"] = "Synthetic baseline 247.5."
    case["sources"][0]["passage"] = "Synthetic baseline 247.5."
    case["assessments"][0]["scenarioWeights"] = {"low": 0.2, "high": 0.8}
    case["binaries"][0]["probability"] = 0.8
    return {"directory": directory, "handoff": handoff, "context": context, "case": case, "world": world}


def _rerun_saved_with_baseline(saved, value):
    """Produce a consistent changed simulation via the actual runtime methods."""
    config = json.loads((saved["directory"] / "simulation_config.json").read_text())
    world = WorldModel.from_seed(config["world_model"], config["agent_configs"], anchor_context=saved["context"])
    for rnd, end in ((1, "2026-10-31"), (2, "2026-11-30")):
        world.start_round(rnd, {"period_start": "2026-10-28" if rnd == 1 else "2026-11-01", "period_end": end})
        if rnd == 2:
            world.variables["baseline"].set_value(value, round_num=rnd, source="action", cause="Synthetic intervention")
        world.evaluate_target_projection(rnd, random.Random(7))
    world.committed_round = 2
    path = saved["directory"] / "world_state.json"
    state = json.loads(path.read_text())
    state["world"] = world.to_dict()
    write(path, state)


def test_saved_runtime_reaches_real_record_render_and_gate(saved):
    from app.services.simulation_record_gate import audit_record
    directory = saved["directory"]
    record = sr.build_record(str(directory), synthesis=False)
    diagnostic = record["setup"]["world_anchor"]
    target = next(row for row in diagnostic["variables"] if row["node_id"] == "target")
    assert target["initial"] == 247.5 and target["initial_round"] == 1
    assert target["final"] == 257.5 and target["final_value_kind"] == "simulated"
    baseline = next(row for row in diagnostic["variables"] if row["node_id"] == "baseline")
    assert target["provenance"] == baseline["provenance"]
    assert target["derivation"] == {"template": "sum", "input_node_ids": ["baseline"]}
    source = baseline["provenance"][0]
    assert source["status"] == "bound" and source["value_kind"] == "third_party_forecast"
    assert source["anchor_hash"] == rc.record_sha256({k: v for k, v in source.items() if k != "anchor_hash"})
    assert source["source_hashes"] and "vintage" in source
    assert [r["triggered"] for r in diagnostic["signposts"]] == [False, True]
    assert not rc.validate_shape(record)
    paths = sr.write_record(str(directory), record)
    markdown = Path(paths["md"]).read_text()
    assert "World Anchor diagnostics" in markdown and "257.5" in markdown
    assert "世界锚点诊断" in Path(paths["md_zh"]).read_text()
    assert saved["context"].pack_hash not in json.dumps(diagnostic)
    audit = audit_record(str(directory), record)
    assert audit["hard_issues"] == [], audit["hard_issues"]
    altered = deepcopy(record)
    altered["setup"]["world_anchor"]["variables"][0]["final"] = 123456
    assert audit_record(str(directory), altered)["hard_issues"]


def test_privileged_metadata_and_unclassified_prose_do_not_reach_record_or_prompt(saved):
    directory = saved["directory"]
    before = sr.build_record(str(directory), synthesis=False)
    path = directory / "world_state.json"
    state = json.loads(path.read_text())
    world = state["world"]
    world["seed_gaps"] = [{"kind": "private", "subject": "DENIED_PRIVATE", "note": "DENIED_PLAN"}] * 12
    world["actors"][0].update(documented_plans=["DENIED_PLAN"], red_lines=["DENIED_ANALYST"],
                               commitments=[{"status": "fulfilled", "description": "DENIED_PLAN"}])
    for variable in world["variables"]:
        for row in variable["history"]:
            if row["round"] > 0:
                row["cause"] = "DENIED_ANALYST"
    write(path, state)
    history = directory / "world_state_history.jsonl"
    rows = [json.loads(line) for line in history.read_text().splitlines()]
    for row in rows:
        row["narrative"] = "DENIED_ANALYST"
        row["arbiter"]["red_lines_crossed"] = ["DENIED_PRIVATE"]
    history.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    after = sr.build_record(str(directory), synthesis=False)
    assert rc.record_bytes(after) == rc.record_bytes(before)
    assert sr.render_markdown(after) == sr.render_markdown(before)
    assert sr._synthesis_prompt(after) == sr._synthesis_prompt(before)
    assert "DENIED_" not in json.dumps(after)


def test_target_report_fence_frozen_authority_and_saved_runtime(saved):
    case, directory = saved["case"], saved["directory"]
    before = tr.build_target_report(case)
    after = tr.build_target_report(case, simulation_dir=directory)
    assert after["forecast"] == before["forecast"]
    assert after["record"]["policy"]["simulationWeight"] == 0.0
    assert after["record"]["worldAnchor"] == sr.build_record(str(directory), synthesis=False)["setup"]["world_anchor"]
    prefix, diagnostic = after["markdown"].split(tr.BRIDGE_START)
    assert prefix == before["markdown"].split(tr.BRIDGE_START)[0]
    assert "World Anchor diagnostics" in diagnostic.split(tr.BRIDGE_END)[0]
    assert tr.audit_target_report(case, None, after["forecast"], after["record"], simulation_dir=directory)["valid"]
    _rerun_saved_with_baseline(saved, 300.0)
    revised = tr.build_target_report(case, simulation_dir=directory)
    assert revised["forecast"] == after["forecast"]
    assert revised["record"]["worldAnchor"] != after["record"]["worldAnchor"]
    changed = deepcopy(case)
    changed["nodes"][0]["visibility"] = "private"
    with pytest.raises((rc.RecordContractError, ValueError)):
        tr.build_target_report(changed, simulation_dir=directory)


@pytest.mark.parametrize("saved", ["private"], indirect=True)
def test_authenticated_private_audience_never_becomes_public_value_or_count(saved):
    directory = saved["directory"]
    before = sr.build_record(str(directory), synthesis=False)
    diagnostic = before["setup"]["world_anchor"]
    assert diagnostic["variables"] == diagnostic["signposts"] == []
    assert diagnostic["target_node_id"] is None
    _rerun_saved_with_baseline(saved, 999999)
    state_path = directory / "world_state.json"
    state = json.loads(state_path.read_text())
    state["world"]["seed_gaps"] = [{"kind": "private", "note": "DENIED_PRIVATE"}] * 17
    write(state_path, state)
    after = sr.build_record(str(directory), synthesis=False)
    assert rc.record_bytes(before) == rc.record_bytes(after)
    assert sr._synthesis_prompt(before) == sr._synthesis_prompt(after)
    assert "247.5" not in json.dumps(after) and "DENIED_" not in json.dumps(after)


@pytest.mark.parametrize("tamper", ["metadata", "cached_target", "signpost"])
def test_privileged_runtime_corruption_is_rejected_before_public_projection(saved, tamper):
    path = saved["directory"] / "world_state.json"
    state = json.loads(path.read_text())
    if tamper == "metadata":
        state["world"]["variables"][0]["anchor_metadata"] = {"private_rationale": "DENIED_PRIVATE"}
    elif tamper == "cached_target":
        state["world"]["target_projection_state"]["values"]["target"] = 999999
    else:
        state["world"]["anchor_signposts"].append({"indicator_id": "DENIED_PRIVATE", "round": 2,
                                                    "node_id": "target", "value": 99999, "triggered": True})
    write(path, state)
    with pytest.raises(ValueError, match="invalid restored state"):
        sr.build_record(str(saved["directory"]), synthesis=False)


@pytest.mark.parametrize("saved", ["gap"], indirect=True)
def test_public_unmet_requirement_reaches_rendered_gap_without_private_detail(saved):
    record = sr.build_record(str(saved["directory"]), synthesis=False)
    gaps = record["setup"]["world_anchor"]["gaps"]
    assert gaps and all(set(gap) == {"node_id", "status", "code"} for gap in gaps)
    assert gaps[0]["node_id"] == "target" and gaps[0]["status"] == "gap"
    assert gaps[0]["code"] in sr.render_markdown(record)


def test_published_record_revalidates_external_anchor_proof(saved):
    from app.services.simulation_record_gate import audit_record
    directory = str(saved["directory"])
    record = sr.build_record(directory, synthesis=False)
    sr.write_record(directory, record)
    assert audit_record(directory, record)["hard_issues"] == []
    assert rc.is_published(directory)
    path = saved["handoff"] / "world_anchor_inputs/v3/pages/page.txt"
    path.write_text("changed external source after record publication")
    assert rc.load_published_record(directory) == (None, "stale_audit")


def test_uncommitted_target_and_signposts_are_not_final_results(saved):
    path = saved["directory"] / "world_state.json"
    state = json.loads(path.read_text())
    state["world"]["committed_round"] = 1
    write(path, state)
    diagnostic = sr.build_record(str(saved["directory"]), synthesis=False)["setup"]["world_anchor"]
    assert all(row["final"] is None and row["status"] == "unavailable" for row in diagnostic["variables"])
    assert [row["round"] for row in diagnostic["signposts"]] == [1]


@pytest.mark.parametrize("tamper", ["source", "runtime", "projection", "join"])
def test_enabled_report_fails_closed_on_untrusted_saved_artifacts(saved, tamper):
    directory = saved["directory"]
    if tamper == "source":
        path = saved["handoff"] / "world_anchor_inputs/v3/pages/page.txt"
        path.write_text("forged")
    elif tamper == "join":
        (directory / "world_anchor_join.json").unlink()
    else:
        path = directory / "world_state.json"
        state = json.loads(path.read_text())
        if tamper == "runtime":
            state["world"]["anchor_runtime"]["pin"]["pack_hash"] = "a" * 64
        else:
            state["world"]["target_projection"]["nodes"][0]["visibility"] = "private"
        write(path, state)
    with pytest.raises((ValueError, rc.RecordContractError)):
        sr.build_record(str(directory), synthesis=False)


def test_off_serialization_rendering_and_loader_unchanged(tmp_path, monkeypatch):
    from test_simulation_record import _copy_reflexive
    directory = _copy_reflexive(tmp_path)
    before = sr.build_record(directory, synthesis=False)
    monkeypatch.setenv("SIM_WORLD_ANCHOR", "true")
    monkeypatch.setattr(host, "load_runtime_anchor", lambda *a, **k: pytest.fail("off entered anchor loader"))
    write(Path(directory) / "world_anchor.json", {"private": "DENIED_PRIVATE"})
    after = sr.build_record(directory, synthesis=False)
    before.pop("generated_at")
    after.pop("generated_at")
    assert rc.record_bytes(after) == rc.record_bytes(before)
    assert sr.render_markdown(after) == sr.render_markdown(before)
    assert "world_anchor" not in after["setup"]


@pytest.fixture
def native_world(tmp_path, monkeypatch, target_case, request):
    """Real native compiler/service/kernel/store/export; no reflexive artifacts."""
    from app.config import Config
    from app.services.world_simulation.service import WorldSimulationService, run_child
    from app.services.world_simulation.examples import ExamplePolicy
    import test_world_anchor as fixtures
    if getattr(request, "param", None) == "private":
        review = fixtures.review_fixture
        monkeypatch.setattr(fixtures, "review_fixture", lambda f: review(f, audience={"kind": "analyst", "actor_refs": []}))
    source = tmp_path / "source"
    source.mkdir()
    from app.services.world_simulation.compiler import ANCHOR_ADAPTER_VERSION
    def native_policy(policy):
        for rule in policy["consumer_rules"]:
            if rule["engine"] == "world-v1":
                rule["adapter_version"] = ANCHOR_ADAPTER_VERSION
    original, _ = _anchored_fixture(source, target_case, temporal=False, policy_edit=native_policy)
    pipelines = tmp_path / "pipelines"
    handoff = pipelines / "pipe_native" / "handoff"
    pub = bridge_module("world_anchor_publication")
    receipts = {h.manifest_hash: h for h in original.index._review_pins.values()}
    publication = pub.publish_completion(handoff, original.pack, requirements=original.requirements,
        index=original.index, policy=original.policy, receipts=tuple(receipts.values()))
    context = host.load_research_anchor(handoff, expected_manifest_sha256=publication["manifest_sha256"])
    sims = tmp_path / "simulations"
    directory = sims / "sim_native"
    directory.mkdir(parents=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sims))
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(pipelines))
    (directory / "actor_cast_manifest.json").write_bytes(original._cast_bytes)
    context = host.bind_actor_cast(context, directory)
    native_bundle = {"actors": [{"actor_id": "entity-1", "name": "Acme", "claims": []}]}
    for name, text in {"research_report.md": "Synthetic native source.", "actors.json": json.dumps(native_bundle),
                       "sources.json": "[]", "actor_dossier.md": "Synthetic registry."}.items():
        (handoff / name).write_text(text)
    bind_simulation_research("sim_native", handoff, pipeline_id=context.pack["scope"]["run_id"])
    context = host.bind_context_sources(context, simulation_id="sim_native")
    req = next(r for r in context.requirements["requirements"] if r["kind"] == "baseline")
    binding = next(b for b in context.pack["bindings"] if b["requirement_id"] == req["requirement_id"])
    ref = {"pack_hash": context.pack_hash, "requirement_id": req["requirement_id"],
           "binding_id": binding["binding_id"], "observation_id": binding["observation_ids"][0],
           "field": "value", "target": "/initialState/metrics/baseline/value", "target_object_id": "baseline"}
    basis = {"kind": "scenario_assumption", "refs": ["synthetic-native/v1"]}
    raw = {"periods": [{"start": "2026-10-28T00:00:00Z", "end": "2026-10-29T00:00:00Z"},
                       {"start": "2026-10-29T00:00:00Z", "end": "2026-10-30T00:00:00Z"}],
           "actors": [{"actorId": "entity-1", "name": "Acme", "basis": basis, "capabilities": ["wait"]}],
           "initialState": {"accounts": {}, "rules": {}, "relations": {}, "metrics": {
               "baseline": {"kind": "stock", "value": "247.5", "unit": "usd_billion", "visibility": {"kind": "public"},
                            "basis": {"kind": "anchor_evidence", "refs": [ref]}, "structuralBasis": basis}}},
           "actionCatalog": [{"templateId": "wait", "kind": "wait", "actorIds": ["entity-1"],
                              "description": "Wait", "parameters": {}, "inputs": {}, "basis": basis,
                              "visibility": {"kind": "public"}}],
           "scheduledEvents": [{"eventId": "synthetic-delta", "at": "2026-10-29T12:00:00Z", "kind": "metric_delta",
                                "parameters": {"targetMetric": "baseline", "delta": "10"},
                                "basis": basis, "visibility": {"kind": "public"}}],
           "assumptions": [{"assumptionId": "synthetic-native/v1", "description": "Synthetic structure and +10 native metric_delta event."}]}
    prepared = WorldSimulationService.prepare_model("sim_native", raw_spec=raw, research_report="Synthetic native source.",
        research_generation_id=context.pack["scope"]["research_generation_id"], research_engine="v3",
        actor_bundle=native_bundle, root=sims, anchor_context=context)
    write(directory / "state.json", {"simulation_id": "sim_native", "simulation_engine": "world-v1",
          "world_generation_id": prepared["spec"]["generationId"], "world_spec_sha256": prepared["manifest"]["specSha256"],
          "world_input_manifest_sha256": prepared["manifest_sha256"]})
    assert run_child(directory, policy=ExamplePolicy("fixture")) == 0
    monkeypatch.setattr(sr, "_utcnow", lambda: "2026-10-29T00:00:00Z")
    return {"directory": directory, "handoff": handoff, "context": context}


def test_native_world_producer_to_record_and_render_without_reflexive_state(native_world):
    from app.services.simulation_record_gate import audit_record
    directory = native_world["directory"]
    assert not (directory / "world_state.json").exists() and not (directory / "simulation_config.json").exists()
    record = sr.build_record(str(directory), synthesis=False)
    diagnostic = record["setup"]["world_anchor"]
    assert diagnostic["engine"] == record["engine"] == "world-v1"
    assert diagnostic["variables"][0]["initial"] == "247.5"
    assert diagnostic["variables"][0]["final"] == "257.5"
    assert diagnostic["variables"][0]["provenance"][0]["value_kind"] == "third_party_forecast"
    assert diagnostic["target_node_id"] is None
    assert any(g["code"] == "target_not_produced_by_native_world" for g in diagnostic["gaps"])
    assert "DENIED_" not in json.dumps(record) and native_world["context"].pack_hash not in json.dumps(record)
    paths = sr.write_record(str(directory), record)
    assert "257.5" in Path(paths["md"]).read_text() and "World Anchor diagnostics" in Path(paths["md"]).read_text()
    assert audit_record(str(directory), record)["hard_issues"] == []
    assert rc.is_published(str(directory))


@pytest.mark.parametrize("native_world", ["private"], indirect=True)
def test_native_world_private_anchor_does_not_become_public_through_visibility_label(native_world):
    record = sr.build_record(str(native_world["directory"]), synthesis=False)
    diagnostic = record["setup"]["world_anchor"]
    assert diagnostic["variables"] == [] and record["overall"]["final_variables"] == []
    assert "247.5" not in json.dumps(record) and "257.5" not in json.dumps(record)
    assert "DENIED_" not in sr.render_markdown(record)


@pytest.mark.parametrize("tamper", ["external_source", "result", "state_pin", "observation_projection"])
def test_native_world_record_refuses_changed_native_proof(native_world, tamper):
    directory = native_world["directory"]
    if tamper == "external_source":
        (native_world["handoff"] / "world_anchor_inputs/v3/pages/page.txt").write_text("changed")
    elif tamper == "state_pin":
        path = directory / "state.json"
        state = json.loads(path.read_text())
        state["world_input_manifest_sha256"] = "f" * 64
        write(path, state)
    else:
        path = directory / ("world_result.json" if tamper == "result" else "world_spec.json")
        data = json.loads(path.read_text())
        if tamper == "result":
            data["world"]["metrics"]["baseline"]["value"] = "99999"
        else:
            data["worldAnchorObservations"]["actors"]["entity-1"]["periods"]["1"]["items"] = []
        write(path, data)
    with pytest.raises(ValueError):
        sr.build_record(str(directory), synthesis=False)


def test_native_world_off_bytes_ignore_loose_anchor_and_environment(tmp_path, monkeypatch):
    from test_world_service_results import prepare
    from app.services.world_simulation.service import run_child
    from app.services.world_simulation.examples import ExamplePolicy
    _, _, directory = prepare(tmp_path)
    assert run_child(directory, policy=ExamplePolicy("investment")) == 0
    monkeypatch.setattr(sr, "_utcnow", lambda: "2026-10-29T00:00:00Z")
    before = sr.build_record(str(directory), synthesis=False)
    monkeypatch.setenv("SIM_WORLD_ANCHOR", "true")
    monkeypatch.setattr(host, "load_runtime_anchor", lambda *a, **k: pytest.fail("off called anchor loader"))
    write(directory / "world_anchor.json", {"private": "DENIED_PRIVATE"})
    after = sr.build_record(str(directory), synthesis=False)
    assert rc.record_bytes(before) == rc.record_bytes(after)
    assert sr.render_markdown(before) == sr.render_markdown(after)


@pytest.fixture
def native_target(tmp_path, monkeypatch, target_case, request):
    """Native run_paths + real pipeline artifact receipts, without OASIS files."""
    from app.config import Config
    from app.services.pipeline_orchestrator import PipelineManager, PipelineState, StageState
    from app.services.target_pipeline import record_stage
    from app.services.target_simulation import run_paths
    from app.services.forecast_aggregator import default_aggregation_policy
    from app.services.forecast_tournament import freeze_target_estimators
    from app.services.forecast_library import publish_case_mechanisms
    from tests import test_world_anchor_target as target_fixtures
    from tests.test_world_anchor_target import _fixture, _bind
    make_fixture = target_fixtures.fixtures.make_fixture
    def pipeline_scope(*args, **kwargs):
        f = make_fixture(*args, **kwargs)
        # The native fixture rebuilds its authenticated index after this point.
        # Bind it to a real controller identity before review/publication seals.
        f["scope"]["run_id"] = "pipe_native_target"
        f["manifest"]["scope"]["run_id"] = "pipe_native_target"
        return f
    monkeypatch.setattr(target_fixtures.fixtures, "make_fixture", pipeline_scope)
    def unknown_derived_seed(case):
        target = next(row for row in case["nodes"] if row["nodeId"] == case["resolution"]["targetNodeId"])
        target.update(value=None, range={"low": 0, "high": 500})
    variant = getattr(request, "param", None)
    fixture_options = {"rival_value": 3} if variant == "private" else (variant if isinstance(variant, dict) else {})
    native = _fixture(tmp_path / "source", mutation=unknown_derived_seed, **fixture_options)
    case = _bind(native)
    original = native["context"]
    pipelines, sims = tmp_path / "pipelines", tmp_path / "simulations"
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(pipelines))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(sims))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sims))
    state = PipelineState(pipeline_id=native["scope"]["run_id"], prompt=case["question"], simulation_id="sim_native_target",
                          options={"forecast_authority": "target-first-v1", "simulation_engine": "target-first-v1"})
    state.options["world_anchor"] = {"mode": "v1"}
    state.options["world_anchor_lifecycle"] = host.pending_lifecycle(
        state.pipeline_id, {"world_anchor": {"mode": "v1"}})
    state.handoff_dir = PipelineManager.handoff_dir(state.pipeline_id)
    PipelineManager.save(state)
    handoff = Path(state.handoff_dir)
    pub = bridge_module("world_anchor_publication")
    receipts = {h.manifest_hash: h for h in original.index._review_pins.values()}
    publication = pub.publish_completion(handoff, original.pack, requirements=original.requirements,
        index=original.index, policy=original.policy, receipts=tuple(receipts.values()))
    context = host.accept_completion(state, expected_manifest_sha256=publication["manifest_sha256"])
    directory = sims / state.simulation_id
    directory.mkdir(parents=True)
    for name, text in {"research_report.md": "Synthetic native target source.", "actors.json": '{"actors":[]}',
                       "sources.json": "[]", "actor_dossier.md": "Synthetic registry."}.items():
        (handoff / name).write_text(text)
    bind_simulation_research(state.simulation_id, handoff, pipeline_id=state.pipeline_id)
    api = bridge_module("forecast_case")
    case_hash = api.case_hash(case)
    state.options["target_case_binding"] = {"authority": "target-first-v1", "caseId": case["caseId"],
        "caseHash": case_hash, "questionHash": tr._hash(case["question"]), "policyVersion": 1}
    policy = default_aggregation_policy("research")
    state.options["aggregation_policy_v1"] = policy
    evidence = {"schemaVersion": "target-evidence/v1", "caseHash": case_hash,
                "official_data": None, "markets": None, "news_market_context": None}
    typed = tr.build_target_report(case)["forecast"]
    estimators = freeze_target_estimators(case, typed, policy, enabled=False)
    api.write_case(handoff / "forecast_case.json", case)
    library = {"schemaVersion": "target-library-context/v1", "entries": [], "authority": "prior_context_only"}
    library_publication = publish_case_mechanisms(tmp_path / "library", case)
    for name, value in (("target_estimators", estimators), ("target_evidence", evidence),
                        ("target_library", library), ("target_library_publication", library_publication)):
        write(handoff / (name + ".json"), value)
        state.options[name + "_binding"] = tr._hash(value)
    state.stages["research"] = StageState(name="research", status="completed")
    record_stage(state, "research")
    api.write_case(directory / "target_case.json", case)
    settings = {"paths": 2, "periods": 2, "seed": 7}
    inputs = {"schemaVersion": "target-input/v1", "pipelineId": state.pipeline_id, "caseHash": api.case_hash(case),
              "structure": api.simulation_projection(case), "simulation": settings, "simulationWeight": 0.0,
              "worldAnchor": host.anchor_config_pin(context, require_join=False)}
    write(directory / "target_input.json", inputs)
    state.stages["prepare"] = StageState(name="prepare", status="completed")
    record_stage(state, "prepare")
    PipelineManager.save(state)
    observations = []
    def decide(obs):
        observations.append(deepcopy(obs))
        return {"actorId": "regulator", "leverId": "mandate", "value": 20} if obs["actorId"] == "regulator" else []
    result = run_paths(case, **settings, identity_mode="named", anchor_context=context, model_validation="admission",
        decision_provider=decide)
    write(directory / "target_simulation.json", result)
    state.stages["run"] = StageState(name="run", status="completed")
    record_stage(state, "run")
    PipelineManager.save(state)
    return {"directory": directory, "context": context, "case": case, "result": result,
            "pipeline_state": state, "handoff": handoff, "policy": policy,
            "estimators": estimators, "evidence": evidence, "observations": observations}


def test_native_target_saved_paths_public_projection(native_target):
    # This lower boundary is distinct from shared-loader call-through. The
    # latter remains a separate test once the parent's prepare seal lands.
    diagnostic = rc._target_anchor_diagnostics(native_target["directory"],
        native_target["context"], native_target["case"], native_target["result"])
    assert diagnostic["engine"] == "target-first-v1"
    assert diagnostic["target_node_id"] == "target"
    targets = [row for row in diagnostic["variables"] if row["node_id"] == "target"]
    assert len(targets) == 2 and all(row["initial"] == 257.5 and row["final"] == 267.5 for row in targets)
    assert all(row["provenance"] and row["derivation"]["template"] == "linear" for row in targets)
    assert {p["identity"]["metric_id"] for p in targets[0]["provenance"]} >= {
        "spending", "control", "coefficient:baseline", "coefficient:control", "intercept"}
    assert not (native_target["directory"] / "state.json").exists()
    assert not (native_target["directory"] / "world_state.json").exists()
    assert not (native_target["directory"] / "simulation_config.json").exists()
    assert "DENIED_" not in rc.anchor_diagnostic_markdown(diagnostic)


def test_native_target_private_result_fields_do_not_change_public_projection(native_target):
    from app.services.target_pipeline import record_stage
    original = rc._target_anchor_diagnostics(native_target["directory"],
        native_target["context"], native_target["case"], native_target["result"])
    report_before = tr.build_target_report(native_target["case"], native_target["result"],
                                          simulation_dir=native_target["directory"])
    result = deepcopy(native_target["result"])
    result["signposts"].append({"actorId": "DENIED_ACTOR", "nodeId": "baseline", "value": 99999,
                               "basis": "planned_earliest_effect", "condition": "DENIED_PLAN"})
    result["decisionBudget"] = {"maximumRequests": 128, "requests": 77, "cacheHits": 8, "exhausted": False}
    result["parameterBases"].append({"nodeId": "DENIED_NODE", "value": 0.999, "basis": "private"})
    result["targetSummary"] = {"mean": 99999, "private_notes": "DENIED_PLAN"}
    for path in result["paths"]:
        path["plans"] = {"DENIED_ACTOR": [{"planId": "DENIED_PLAN", "value": 99999}]}
    write(native_target["directory"] / "target_simulation.json", result)
    record_stage(native_target["pipeline_state"], "run")
    altered = rc._target_anchor_diagnostics(native_target["directory"],
        native_target["context"], native_target["case"], result)
    assert rc.record_bytes(original) == rc.record_bytes(altered)
    report_after = tr.build_target_report(native_target["case"], result, simulation_dir=native_target["directory"])
    assert tr.canonical_json(report_before) == tr.canonical_json(report_after)
    assert "DENIED_" not in tr.canonical_json(report_after)


def test_native_target_result_requires_external_run_receipt(native_target):
    result = deepcopy(native_target["result"])
    result["signposts"].append({"nodeId": "baseline", "value": 99999})
    write(native_target["directory"] / "target_simulation.json", result)
    with pytest.raises(rc.RecordContractError, match="external run receipt"):
        rc._target_anchor_diagnostics(native_target["directory"],
            native_target["context"], native_target["case"], result)


def test_native_target_off_report_bytes_remain_identical(native_target, monkeypatch):
    from app.services.pipeline_orchestrator import PipelineManager
    from app.services.target_simulation import run_paths
    case = native_target["case"]
    result = run_paths(case, paths=2, periods=2, seed=7, identity_mode="named",
        decision_provider=lambda obs: {"actorId": "regulator", "leverId": "mandate", "value": 20})
    write(native_target["directory"] / "target_simulation.json", result)
    before = tr.build_target_report(case, result)
    path = native_target["directory"] / "target_input.json"
    inputs = json.loads(path.read_text())
    inputs.pop("worldAnchor")
    write(path, inputs)
    state = native_target["pipeline_state"]
    state.options.pop("world_anchor")
    state.options.pop("world_anchor_lifecycle")
    PipelineManager.save(state)
    monkeypatch.setenv("SIM_WORLD_ANCHOR", "true")
    monkeypatch.setattr(host, "load_runtime_anchor", lambda *a, **k: pytest.fail("off called anchor loader"))
    after = tr.build_target_report(case, result, simulation_dir=native_target["directory"])
    assert tr.canonical_json(before) == tr.canonical_json(after)


@pytest.mark.parametrize("artifact", ["target_input.json", "target_case.json"])
def test_native_target_changed_prepare_bytes_are_not_report_authority(native_target, artifact):
    path = native_target["directory"] / artifact
    data = json.loads(path.read_text())
    data["DENIED_FIELD"] = "changed"
    write(path, data)
    with pytest.raises(rc.RecordContractError, match="external prepare receipt"):
        rc._target_anchor_diagnostics(native_target["directory"],
            native_target["context"], native_target["case"], native_target["result"])


def test_native_target_report_cannot_bypass_missing_host_prepare_pin(native_target):
    from app.services.pipeline_orchestrator import PipelineManager
    state = native_target["pipeline_state"]
    manifest = PipelineManager.load_artifact_manifest(state.pipeline_id)
    manifest.pop("target_input")
    PipelineManager.write_artifact_manifest(state.pipeline_id, manifest)
    with pytest.raises(ValueError, match="anchor_"):
        tr.build_target_report(native_target["case"], native_target["result"],
                               simulation_dir=native_target["directory"])


def test_native_target_admission_never_reads_oasis_state(native_target, monkeypatch):
    original_read = rc.read_regular
    def read(path):
        assert Path(path).name not in {"state.json", "world_state.json", "simulation_config.json"}
        return original_read(path)
    monkeypatch.setattr(rc, "read_regular", read)
    pub = host._publication()
    pub_read = pub.read_bytes
    def read_host(root, relative, **kwargs):
        assert Path(relative).name not in {"state.json", "world_state.json", "simulation_config.json"}
        return pub_read(root, relative, **kwargs)
    monkeypatch.setattr(pub, "read_bytes", read_host)
    result = tr.build_target_report(native_target["case"], native_target["result"],
                                    simulation_dir=native_target["directory"])
    assert result["record"]["worldAnchor"]["engine"] == "target-first-v1"


def test_native_target_stripped_input_pin_cannot_override_external_enabled_intent(native_target):
    path = native_target["directory"] / "target_input.json"
    inputs = json.loads(path.read_text())
    inputs.pop("worldAnchor")
    write(path, inputs)
    with pytest.raises(ValueError, match="anchor_"):
        tr.build_target_report(native_target["case"], native_target["result"],
                               simulation_dir=native_target["directory"])


def test_target_runtime_receipt_alone_cannot_authorize_public_report():
    from test_target_report import simulation
    case = json.loads((Path(__file__).parent / "fixtures/target_case.json").read_text())
    result = simulation(case)
    result["worldAnchor"] = {"adapterVersion": "world-anchor-target/v1", "packHash": "a" * 64,
        "contractHash": "b" * 64, "inputHash": "c" * 64, "caseHash": result["caseHash"]}
    with pytest.raises(ValueError, match="saved artifact admission"):
        tr.build_target_report(case, result)
    result["worldAnchor"]["private_notes"] = "DENIED_PRIVATE"
    with pytest.raises(ValueError, match="invalid target anchor runtime receipt"):
        tr.build_target_report(case, result)


def test_native_target_real_loader_build_and_audit(native_target):
    from app.services.pipeline_orchestrator import PipelineManager
    state, case, directory = native_target["pipeline_state"], native_target["case"], native_target["directory"]
    loaded = host.load_target_anchor(directory, expected_case_hash=tr._case_api().case_hash(case))
    assert loaded.pack_hash == native_target["context"].pack_hash
    manifest = PipelineManager.load_artifact_manifest(state.pipeline_id)
    assert {"world_anchor_" + name for name in (
        "manifest", "pack", "sheet", "gaps", "coverage", "inputs", "contract", "policy")} <= set(manifest)
    report = tr.build_target_report(case, native_target["result"], simulation_dir=directory)
    assert report["forecast"] == tr.build_target_report(case)["forecast"]
    diagnostic = report["record"]["worldAnchor"]
    targets = [row for row in diagnostic["variables"] if row["node_id"] == "target"]
    assert len(targets) == 2 and all(row["initial"] == 257.5 and row["final"] == 267.5 for row in targets)
    assert diagnostic["simulationWeight"] == report["record"]["simulationWeight"] == 0
    assert "World Anchor diagnostics" in report["markdown"].split(tr.BRIDGE_START)[1].split(tr.BRIDGE_END)[0]
    assert loaded.pack_hash not in tr.canonical_json(report)
    assert tr.audit_target_report(case, native_target["result"], report["forecast"], report["record"],
                                  simulation_dir=directory)["valid"]
    with pytest.raises(ValueError, match="anchor_"):
        host.load_target_anchor(directory, expected_case_hash="a" * 64)


@pytest.mark.parametrize("native_target", ["private"], indirect=True)
def test_native_target_private_nodes_and_model_bases_are_not_public_report_fields(native_target):
    case, result = native_target["case"], native_target["result"]
    assert any(row["nodeId"] == "rival-state" for row in case["nodes"])
    assert "modelValidation" in result
    report = tr.build_target_report(case, result, simulation_dir=native_target["directory"])
    assert "rival-state" not in tr.canonical_json(report)
    assert "rival-lever" not in tr.canonical_json(report)
    assert "PRIVATE_SELF_INFERENCE" not in tr.canonical_json(report)
    assert report["record"]["worldAnchor"]["target_node_id"] is None
    assert report["record"]["targetSummary"] is None
    assert report["record"]["parameterBases"] == []
    assert "modelValidation" not in report["record"]
    assert [s["probability"] for s in report["forecast"]["scenarios"]] == [0.5, 0.5]


@pytest.mark.parametrize("tamper", ["research_stage", "prepare_stage", "research_receipt", "source", "lifecycle", "owner"])
def test_native_target_public_reader_rejects_external_authority_tamper(native_target, tamper):
    from app.services.pipeline_orchestrator import PipelineManager
    state = native_target["pipeline_state"]
    if tamper in {"research_stage", "prepare_stage"}:
        state.stages[tamper.split("_")[0]].status = "pending"
    elif tamper == "lifecycle":
        state.options["world_anchor_lifecycle"]["status"] = "pending"
    elif tamper == "owner":
        state.simulation_id = "sim_other_owner"
    elif tamper == "research_receipt":
        manifest = PipelineManager.load_artifact_manifest(state.pipeline_id)
        manifest.pop("world_anchor_policy")
        PipelineManager.write_artifact_manifest(state.pipeline_id, manifest)
    else:
        page = native_target["handoff"] / "world_anchor_inputs/v3/pages/page.txt"
        page.write_text("changed source bytes")
    PipelineManager.save(state)
    with pytest.raises(ValueError, match="anchor_"):
        tr.build_target_report(native_target["case"], native_target["result"],
                               simulation_dir=native_target["directory"])


def test_native_target_reportagent_generates_and_audits_real_sealed_record(native_target, tmp_path, monkeypatch):
    from app.config import Config
    from app.services import report_agent as ra, forecast_tournament as ft
    from app.services.pipeline_orchestrator import PipelineManager
    monkeypatch.setattr(ra.ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True)
    def forbidden(*args, **kwargs):
        pytest.fail("native deterministic report acquired a provider or legacy world")
    for name in ("LLMClient", "ZepToolsService", "load_simulation_world"):
        monkeypatch.setattr(ra, name, forbidden)
    monkeypatch.setattr(ft, "_method_lane", forbidden)
    state, case, directory = native_target["pipeline_state"], native_target["case"], native_target["directory"]
    protected = {str(path): path.read_bytes() for root in (native_target["handoff"], directory)
                 for path in root.rglob("*") if path.is_file()}
    agent = ra.ReportAgent(graph_id="target_graph_native", simulation_id=state.simulation_id,
        simulation_requirement=case["question"], forecast_case=case, target_simulation=native_target["result"],
        aggregation_policy=native_target["policy"], saved_estimators=native_target["estimators"],
        target_evidence=native_target["evidence"], anchor_context=native_target["context"])
    report = agent.generate_report(report_id="report_native_anchor_record")
    assert report.status == ra.ReportStatus.COMPLETED, report.error
    assert ra.ReportManager.publication_status(report.report_id)["publishable"]
    folder = Path(ra.ReportManager._get_report_folder(report.report_id))
    forecast = json.loads((folder / "forecast.json").read_text())
    record = json.loads((folder / "target_report.json").read_text())
    markdown = (folder / "full_report.md").read_text()
    assert record["worldAnchor"]["target_node_id"] == "target"
    assert "World Anchor diagnostics" in markdown and "267.5" in markdown
    assert "PRIVATE_SELF_INFERENCE" not in markdown and "unsafe-plan" not in markdown
    assert native_target["context"].pack_hash not in json.dumps(record)
    assert agent._audit_target_authority(report.report_id, forecast, markdown)["valid"]
    assert report.telemetry["totals"] == {"llm_calls": 0, "tool_calls": 0, "tokens": 0}
    assert all(Path(path).read_bytes() == value for path, value in protected.items())
    # The actual ReportAgent audit must re-enter the native loader. Old report
    # files alone cannot hide a changed external preparation receipt.
    manifest = PipelineManager.load_artifact_manifest(state.pipeline_id)
    manifest.pop("target_case")
    PipelineManager.write_artifact_manifest(state.pipeline_id, manifest)
    audit = agent._audit_target_authority(report.report_id, forecast, markdown)
    assert not audit["valid"] and any("anchor_" in issue for issue in audit["issues"])


def test_record_downgrade_reflexive_pin_removal_is_rejected(saved):
    path = saved["directory"] / "simulation_config.json"
    config = json.loads(path.read_text())
    config.pop("world_anchor")
    write(path, config)
    with pytest.raises(ValueError):
        sr.build_record(str(saved["directory"]), synthesis=False)


def test_record_downgrade_native_world_engine_change_is_rejected(native_world):
    path = native_world["directory"] / "state.json"
    state = json.loads(path.read_text())
    state["simulation_engine"] = "oasis-legacy"
    write(path, state)
    with pytest.raises(ValueError):
        sr.build_record(str(native_world["directory"]), synthesis=False)


def test_record_downgrade_native_world_removed_manifest_and_spec_pins(native_world):
    directory = native_world["directory"]
    path = directory / "world_input_manifest.json"
    manifest = json.loads(path.read_text())
    manifest.pop("worldAnchor")
    write(path, manifest)
    path = directory / "world_spec.json"
    spec = json.loads(path.read_text())
    spec["sourceBindings"].pop("worldAnchor")
    spec.pop("worldAnchorObservations")
    write(path, spec)
    with pytest.raises(ValueError):
        sr.build_record(str(directory), synthesis=False)


def test_record_downgrade_native_target_pending_run_is_rejected(native_target):
    from app.services.pipeline_orchestrator import PipelineManager
    state = native_target["pipeline_state"]
    state.stages["run"].status = "pending"
    PipelineManager.save(state)
    with pytest.raises(ValueError):
        tr.build_target_report(native_target["case"], native_target["result"],
                               simulation_dir=native_target["directory"])


def test_record_downgrade_native_target_authority_revoked_during_projection(native_target, monkeypatch):
    from app.services.pipeline_orchestrator import PipelineManager
    original = tr._simulation
    calls = []
    def validated_then_revoked(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(True)
        # First validation is the builder's input check. The second happens
        # inside the actual artifact projection, after host admission.
        if len(calls) == 2:
            state = native_target["pipeline_state"]
            state.options["world_anchor_lifecycle"]["status"] = "failed"
            PipelineManager.save(state)
        return result
    monkeypatch.setattr(tr, "_simulation", validated_then_revoked)
    with pytest.raises(ValueError):
        tr.build_target_report(native_target["case"], native_target["result"],
                               simulation_dir=native_target["directory"])
    assert len(calls) == 2


def _prepare_native_retry_receipts(native_target):
    from app.config import Config
    from app.services.pipeline_orchestrator import PipelineManager, _manifest_entry_for
    from app.services.target_pipeline import record_stage, _digest
    state, directory = native_target["pipeline_state"], native_target["directory"]
    path = directory / "target_input.json"
    inputs = json.loads(path.read_text())
    state.graph_id = "target_graph_" + state.pipeline_id
    state.options["target_simulation"] = inputs["simulation"]
    state.options["target_decision_budget_v1"] = {"max_calls": 128}
    inputs["decisionBudget"] = state.options["target_decision_budget_v1"]
    write(path, inputs)
    record_stage(state, "prepare")
    registry = Path(Config.PIPELINE_DATA_DIR) / "_target_comparisons"
    receipt = tr.register_comparison(registry / (_digest(native_target["case"]["caseId"]) + ".json"),
        native_target["case"], native_target["result"], enrolled_at=tr._utcnow().isoformat())
    comparison = directory / "target_comparison.json"
    write(comparison, receipt)
    manifest = PipelineManager.load_artifact_manifest(state.pipeline_id)
    manifest["target_comparison"] = _manifest_entry_for("target_comparison", str(comparison), "run")
    PipelineManager.write_artifact_manifest(state.pipeline_id, manifest)
    PipelineManager.save(state)
    return state


def test_native_target_retry_admission_never_falls_back_to_unanchored_builder(native_target, tmp_path, monkeypatch):
    """The real enabled retry must admit and publish; refusal is not a pass."""
    from app.config import Config
    from app.api.report import _target_report_inputs
    from app.services import report_agent as ra, forecast_tournament as ft
    from app.services.pipeline_orchestrator import PipelineManager
    state = _prepare_native_retry_receipts(native_target)
    monkeypatch.setattr(ra.ReportManager, "REPORTS_DIR", str(tmp_path / "retry-reports"))
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True)
    def forbidden(*args, **kwargs):
        pytest.fail("native retry acquired a provider or legacy world")
    for name in ("LLMClient", "ZepToolsService", "load_simulation_world"):
        monkeypatch.setattr(ra, name, forbidden)
    monkeypatch.setattr(ft, "_method_lane", forbidden)
    protected = {str(p): p.read_bytes() for root in (native_target["handoff"], native_target["directory"])
                 for p in root.rglob("*") if p.is_file()}
    admitted = _target_report_inputs(state.simulation_id, PipelineManager.load(state.pipeline_id))
    assert admitted["anchor_context"].pack_hash == native_target["context"].pack_hash
    agent = ra.ReportAgent(**admitted)
    report = agent.generate_report(report_id="report_native_retry")
    assert report.status == ra.ReportStatus.COMPLETED, report.error
    assert ra.ReportManager.publication_status(report.report_id)["publishable"]
    record = json.loads(agent._target_bundle_json)["record"]
    assert record["worldAnchor"]["engine"] == "target-first-v1"
    assert record["simulationWeight"] == 0
    assert "World Anchor diagnostics" in report.markdown_content
    assert "PRIVATE_SELF_INFERENCE" not in report.markdown_content and "unsafe-plan" not in report.markdown_content
    assert report.telemetry["totals"] == {"llm_calls": 0, "tool_calls": 0, "tokens": 0}
    folder = Path(ra.ReportManager._get_report_folder(report.report_id))
    forecast = json.loads((folder / "forecast.json").read_text())
    markdown = (folder / "full_report.md").read_text()
    audit = agent._audit_target_authority(report.report_id, forecast, markdown)
    assert audit["valid"], audit["issues"]
    assert all(Path(p).read_bytes() == value for p, value in protected.items())
    write(tmp_path / "native-retry-admission.json", {"status": "published", "private_fields_exposed": False,
                                                   "report_id": report.report_id, "target_authority_audit_valid": audit["valid"]})


def test_historical_off_target_without_pipeline_state_renders_identically(tmp_path, monkeypatch):
    from app.config import Config
    from app.services.target_simulation import run_paths
    case = json.loads((Path(__file__).parent / "fixtures/target_case.json").read_text())
    result = run_paths(case, paths=1, periods=2, seed=7)
    sims = tmp_path / "simulations"
    directory = sims / "sim_historical_off"
    directory.mkdir(parents=True)
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(sims))
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "absent-pipelines"))
    write(directory / "target_case.json", case)
    write(directory / "target_input.json", {"schemaVersion": "target-input/v1", "pipelineId": "pipe_historical_off",
        "caseHash": tr._case_api().case_hash(case), "structure": tr._case_api().simulation_projection(case),
        "simulation": {"paths": 1, "periods": 2, "seed": 7}, "simulationWeight": 0.0})
    write(directory / "target_simulation.json", result)
    before = tr.build_target_report(case, result)
    assert host.load_target_anchor(directory) is None
    after = tr.build_target_report(case, result, simulation_dir=directory)
    assert tr.canonical_json(after) == tr.canonical_json(before)
    assert "worldAnchor" not in after["record"]


def test_marked_target_without_pipeline_state_fails_closed(native_target):
    from app.services.pipeline_orchestrator import PipelineManager
    Path(PipelineManager.state_path(native_target["pipeline_state"].pipeline_id)).unlink()
    with pytest.raises(ValueError, match="anchor_"):
        host.load_target_anchor(native_target["directory"])


def test_native_target_retry_rejects_lost_enabled_pins(native_target, tmp_path):
    from app.api.report import _target_report_inputs
    from app.services import report_agent as ra
    from app.services.pipeline_orchestrator import PipelineManager
    from app.services.target_pipeline import record_stage, TargetPipelineError
    directory = native_target["directory"]
    path = directory / "target_input.json"
    inputs = json.loads(path.read_text())
    inputs.pop("worldAnchor")
    write(path, inputs)
    result = deepcopy(native_target["result"])
    result.pop("worldAnchor")
    result["signposts"].append({"actorId": "DENIED_PRIVATE_ACTOR", "nodeId": "control",
                               "value": 19, "basis": "planned_earliest_effect", "condition": "DENIED_PRIVATE_PLAN"})
    native_target["result"] = result
    write(directory / "target_simulation.json", result)
    record_stage(native_target["pipeline_state"], "run")
    state = _prepare_native_retry_receipts(native_target)
    # Even with internally consistent artifact receipts, the externally saved
    # enabled lifecycle forbids dropping its native preparation pin.
    with pytest.raises(ValueError):
        host.load_target_anchor(directory)
    try:
        admitted = _target_report_inputs(state.simulation_id, PipelineManager.load(state.pipeline_id))
    except TargetPipelineError:
        return
    agent = ra.ReportAgent(**admitted)
    exposed = "DENIED_PRIVATE_PLAN" in agent._target_bundle_json
    write(tmp_path / "native-retry-downgrade.json", {"status": "admitted_without_pin",
        "private_signpost_exposed": exposed, "native_loader_rejects": True})
    pytest.fail("retry accepted a stripped enabled pin; private signpost exposed=" + str(exposed))


@pytest.mark.parametrize("saved", ["private"], indirect=True)
@pytest.mark.parametrize("carrier", ["summary", "fallback"])
def test_r4_private_path_shocks_never_reach_record_or_synthesis(saved, carrier):
    from app.services.world_paths import paths_summary
    directory = saved["directory"]
    primary = saved["world"]
    shares = {name: 1 / len(primary.scenarios) for name in primary.scenarios}
    write(directory / "world_state_trajectory.json", {"validity": "valid", "outcome": {"shares": shares}})
    sibling = WorldModel.from_dict(primary.to_dict(), anchor_context=saved["context"])
    def save_paths():
        summary = paths_summary(k=2, temperature=0.7, arbiter_enabled=False, rounds=2,
            per_path_shares=[shares, shares], scenarios=list(shares), worlds=[primary, sibling], arbiter_failed=[0, 0])
        state = json.loads((directory / "world_state.json").read_text())
        if carrier == "summary":
            state["summary"]["paths"] = summary
        else:
            state["summary"].pop("paths", None)
            write(directory / "world_paths.json", {"k": 2, "paths": [
                {"path": i, "shares": shares, "arbiter_failed_rounds": 0, "world": w.to_dict()}
                for i, w in enumerate((primary, sibling))]})
        write(directory / "world_state.json", state)
        return summary
    save_paths()
    before = sr.build_record(str(directory), synthesis=False)
    class AlwaysFire:
        def random(self):
            return 0
    assert sibling.fire_shocks(2, AlwaysFire())
    produced = save_paths()
    assert produced["per_path"][1]["shocks_fired"]
    after = sr.build_record(str(directory), synthesis=False)
    assert rc.record_bytes(after) == rc.record_bytes(before)
    assert sr._synthesis_prompt(after) == sr._synthesis_prompt(before)


@pytest.mark.parametrize("language", ["en", "zh"])
def test_r5_all_native_values_are_actual_markdown_table_rows(native_target, language):
    import mistune
    bundle = tr.build_target_report(native_target["case"], native_target["result"],
                                    simulation_dir=native_target["directory"])
    diagnostic = bundle["record"]["worldAnchor"]
    assert len(diagnostic["variables"]) >= 4
    rendered = rc.anchor_diagnostic_markdown(diagnostic, language=language)
    nodes = mistune.create_markdown(renderer="ast", plugins=["table"])(rendered)
    tables = [node for node in nodes if node["type"] == "table"]
    assert len(tables) == 1
    body = next(child for child in tables[0]["children"] if child["type"] == "table_body")
    assert len(body["children"]) == len(diagnostic["variables"])


@pytest.mark.parametrize("native_target", [{"primary_authority": True, "private_authority": {
    "text": "Regulator has sole authority. PRIVATE_AUTHORITY_ALPHA", "url": "https://private.example.test/authority-alpha"}}], indirect=True)
def test_r1_actor_only_authority_does_not_inherit_public_node_permission(native_target):
    case = native_target["case"]
    authority = next(c for c in case["claims"] if c["claimId"].startswith("anchor_authority_"))
    assert authority["nodeId"] == "control"
    assert "PRIVATE_AUTHORITY_ALPHA" in json.dumps(native_target["observations"])
    report = tr.build_target_report(case, native_target["result"], simulation_dir=native_target["directory"])
    assert any(row["node_id"] == "control" and row["initial"] == 10 for row in report["record"]["worldAnchor"]["variables"])
    exposed = tr.canonical_json(report)
    assert "PRIVATE_AUTHORITY_ALPHA" not in exposed
    assert "https://private.example.test/authority-alpha" not in exposed
    control = next(n for n in report["record"]["unknownParameters"] if n["nodeId"] == "control")
    assert not set(authority["sourceIds"]) & set(control["sourceIds"])


@pytest.mark.parametrize("native_target", [{"primary_authority": True}], indirect=True)
def test_r1_exact_public_authority_claim_and_source_remain_visible(native_target):
    case = native_target["case"]
    authority = next(c for c in case["claims"] if c["claimId"].startswith("anchor_authority_"))
    report = tr.build_target_report(case, native_target["result"], simulation_dir=native_target["directory"])
    control = next(n for n in report["record"]["unknownParameters"] if n["nodeId"] == "control")
    assert set(authority["sourceIds"]) <= set(control["sourceIds"])
    assert authority["passage"] in report["markdown"]
    assert any(f"[Source {sid}]" in report["markdown"] for sid in authority["sourceIds"])


def test_r1_private_authority_perturbations_preserve_public_values_and_publish(tmp_path, monkeypatch, target_case):
    from types import SimpleNamespace
    from app.config import Config
    from app.services import report_agent as ra, forecast_tournament as ft
    snapshots = []
    for suffix in ("alpha", "beta"):
        with monkeypatch.context() as patch:
            root = tmp_path / suffix
            root.mkdir()
            private = {"text": "Regulator has sole authority. PRIVATE_AUTHORITY_" + suffix.upper(),
                       "url": "https://private.example.test/authority-" + suffix}
            native = native_target.__wrapped__(root, patch, target_case,
                SimpleNamespace(param={"primary_authority": True, "private_authority": private}))
            def forbidden(*args, **kwargs):
                pytest.fail("native privacy report acquired a provider")
            patch.setattr(ra, "LLMClient", forbidden)
            patch.setattr(ra, "ZepToolsService", forbidden)
            patch.setattr(ft, "_method_lane", forbidden)
            patch.setattr(ra.ReportManager, "REPORTS_DIR", str(root / "reports"))
            patch.setattr(Config, "REPORT_PUBLISH_GATE", True)
            agent = ra.ReportAgent(graph_id="target_graph_native", simulation_id=native["pipeline_state"].simulation_id,
                simulation_requirement=native["case"]["question"], forecast_case=native["case"],
                target_simulation=native["result"], aggregation_policy=native["policy"],
                saved_estimators=native["estimators"], target_evidence=native["evidence"], anchor_context=native["context"])
            report = agent.generate_report(report_id="report_private_authority_" + suffix)
            assert report.status == ra.ReportStatus.COMPLETED, report.error
            assert ra.ReportManager.publication_status(report.report_id)["publishable"]
            folder = Path(ra.ReportManager._get_report_folder(report.report_id))
            record = json.loads((folder / "target_report.json").read_text())
            forecast = json.loads((folder / "forecast.json").read_text())
            public = json.dumps([record, forecast, report.markdown_content])
            assert "PRIVATE_AUTHORITY_" not in public and "private.example.test" not in public
            assert "PRIVATE_AUTHORITY_" + suffix.upper() in json.dumps(native["observations"])
            snapshots.append({"variables": record["worldAnchor"]["variables"],
                              "unknown": record["unknownParameters"], "bases": record["parameterBases"],
                              "probabilities": [s["probability"] for s in forecast["scenarios"]]})
    assert snapshots[0] == snapshots[1]
