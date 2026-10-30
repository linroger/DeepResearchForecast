"""Target admission/reuse/fork must retain main's immutable FMP generation.

Run with main_offline_pytest.py. The existing target execution fixture retains
the real orchestrator and receipts. Only research/model responses are scripted;
FMP CaptureStore, source projection and capture validation remain production code.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from tests import test_target_pipeline as target_cases
from tests import test_target_reuse_preflight as reuse_cases
from tests import test_fmp_research_deployment as fmp_cases
import test_target_research as engine_cases
import test_fmp_research as fmp_protocol_cases

from app.services import official_data as od
from app.services import target_pipeline as tp

case = target_cases.case
runtime = target_cases.runtime
execution = target_cases.execution
client = reuse_cases.client
bridge = engine_cases.bridge
protocol = fmp_protocol_cases.protocol


@pytest.fixture(autouse=True)
def pin_sources():
    import sys
    guard = sys.modules.get("main_offline_guard")
    if guard is not None:
        root = Path(__file__).resolve().parents[2]
        for relative in ("backend/app/services/target_pipeline.py", "deerflow_bridge/target_research.py",
                         "backend/app/services/official_data.py", "deerflow_bridge/fmp_research.py",
                         "backend/app/services/pipeline_orchestrator.py"):
            path = root / relative
            guard.source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def captured_target(execution, monkeypatch):
    api = od.bridge_module("fmp_research")
    fc = od.bridge_module("forecast_case")
    target = od.bridge_module("target_research")
    original = execution.po.DeerFlowResearchRunner.run
    captures = []
    controls = {"damage_before_admission": None, "capture_question": None}

    class FinancialClient(fmp_cases.CapturedClient):
        def call(self, *args, **kwargs):
            captures.append("synthetic-financial-response")
            return super().call(*args, **kwargs)

    def research(prompt, folder, **kwargs):
        result = original(prompt, folder, **kwargs)
        root = Path(folder)
        store = api.CaptureStore(root, controls["capture_question"] or prompt, env={}, client=FinancialClient(176))
        response, item = store.request("call", {"tool": "statements", "arguments": {
            "endpoint": "income-statement", "symbol": "TEST", "period": "annual", "limit": 1}})
        store.freeze()
        row = {"sid": 2, "url": item["url"], "title": "Synthetic FMP financial response",
               "fetched": True, "passage": api.encoded(response), **api.metadata(item)}
        value = copy.deepcopy(execution.case)
        value["sources"].extend(target.source_rows([row]))
        value["revision"] += 1
        fc.write_case(root / "forecast_case.json", value)
        (root / "research_report.md").write_text(target.render_case_research(value))
        # Preserve the actual provider metadata in the handoff source carrier.
        # The typed case remains on its existing closed source schema.
        exported = [*value["sources"][:-1], {**value["sources"][-1], **api.metadata(item)}]
        (root / "sources.json").write_text(json.dumps(exported))
        result["sources"] = exported
        execution.capture_item = item
        execution.capture_bytes = od.fmp_capture_artifacts(str(root))
        if controls["damage_before_admission"]:
            damage_capture(root, item, controls["damage_before_admission"])
        return result

    monkeypatch.setattr(execution.po.DeerFlowResearchRunner, "run", research)
    monkeypatch.setattr(api.client_api(), "FmpMcpClient",
                        lambda *a, **kw: pytest.fail("Provider reacquired during target admission/reuse/fork"))
    execution.fmp_calls = captures
    execution.fmp_controls = controls
    return execution


def damage_capture(root, item, damage):
    if damage == "response_bytes":
        (root / item["file"]).write_text("{}")
    elif damage == "provenance":
        path = root / "sources.json"
        rows = json.loads(path.read_text())
        rows[-1]["eligibility"]["anchor"] = True
        path.write_text(json.dumps(rows))
    else:
        shutil.rmtree(root / "fmp")
        (root / "fmp_research_binding.json").unlink()


@pytest.mark.parametrize("damage", ["response_bytes", "entire_capture", "provenance", "wrong_question"])
def test_initial_target_admission_rejects_bad_fmp_before_downstream(captured_target, monkeypatch, damage):
    execution = captured_target
    if damage == "wrong_question":
        execution.fmp_controls["capture_question"] = "A different bound research question"
    else:
        execution.fmp_controls["damage_before_admission"] = damage
    downstream = []
    monkeypatch.setattr(tp, "_method_gateway", lambda: downstream.append("method") or pytest.fail("Downstream method reached"))
    state = target_cases._execute(execution)
    assert state.status == "failed", "Invalid captured FMP generation was admitted as target research"
    assert "fmp" in str(state.error).lower() or "capture" in str(state.error).lower()
    assert not downstream
    assert state.stages["prepare"].status != "completed"


@pytest.mark.parametrize("damage", ["response_bytes", "entire_capture"])
@pytest.mark.parametrize("operation,body", [
    ("resume", {}), ("continue", {}), ("scenario", {"label": "FMP-preserving fork", "seed": 17}),
])
def test_completed_target_reuse_rejects_fmp_damage_before_dispatch(captured_target, client, operation, body, damage):
    execution = captured_target
    state = target_cases._execute(execution, "research_only" if operation == "continue" else "full")
    assert state.status == "completed", state.error
    assert tp.validate_stage(state, "research")
    if operation == "resume":
        state.status = "failed"
        state.current_stage = "report"
        state.stages["report"].status = "failed"
        execution.po.PipelineManager.save(state)
    before = execution.po.PipelineManager.load(state.pipeline_id)
    launches = len(execution.launched)
    acquisitions = len(execution.fmp_calls)
    damage_capture(Path(state.handoff_dir), execution.capture_item, damage)
    response = client.post(f"/api/research/{state.pipeline_id}/{operation}", json=body)
    assert response.status_code == 400, "Changed FMP generation crossed completed target reuse admission"
    assert len(execution.launched) == launches
    assert len(execution.fmp_calls) == acquisitions
    assert execution.po.PipelineManager.load(state.pipeline_id) == before


def test_valid_target_fork_keeps_exact_capture_bytes_without_reacquisition(captured_target, client):
    execution = captured_target
    state = target_cases._execute(execution)
    assert state.status == "completed", state.error
    original = od.fmp_capture_artifacts(state.handoff_dir)
    assert original == execution.capture_bytes and original
    source_bytes = (Path(state.handoff_dir) / "sources.json").read_bytes()
    proof_bytes = (Path(state.handoff_dir) / "target_fmp_evidence.json").read_bytes()
    proof = json.loads(proof_bytes)
    assert set(proof["files"]) == {*original, "sources.json"}
    assert proof["binding"]["question_sha256"] == od.bridge_module("fmp_research").question_digest(state.prompt)
    acquisitions = len(execution.fmp_calls)
    response = client.post(f"/api/research/{state.pipeline_id}/scenario",
                           json={"label": "FMP-preserving fork", "seed": 17})
    assert response.status_code == 200, response.json
    child = execution.po.PipelineState.from_dict(execution.po.PipelineManager.load(response.json["data"]["pipeline_id"]))
    execution.po.PipelineOrchestrator._run(child)
    assert child.status == "completed", child.error
    assert od.fmp_capture_artifacts(child.handoff_dir) == original
    assert od.fmp_capture_artifacts(state.handoff_dir) == original
    assert (Path(child.handoff_dir) / "sources.json").read_bytes() == source_bytes
    assert (Path(child.handoff_dir) / "target_fmp_evidence.json").read_bytes() == proof_bytes
    assert len(execution.fmp_calls) == acquisitions
    assert len(execution.calls) == 1
    assert tp.validate_stage(child, "research")


@pytest.mark.parametrize("damage", ["response_bytes", "entire_capture"])
def test_fmp_api_control_rejects_same_damage(captured_target, damage):
    """The negative fixtures are invalid under the unchanged production API."""
    execution = captured_target
    state = target_cases._execute(execution, "research_only")
    assert state.status == "completed", state.error
    damage_capture(Path(state.handoff_dir), execution.capture_item, damage)
    with pytest.raises(ValueError):
        od.fmp_capture_artifacts(state.handoff_dir)


def test_completed_target_refuses_valid_but_expanded_fmp_artifact_set(captured_target, client):
    execution = captured_target
    state = target_cases._execute(execution, "research_only")
    assert state.status == "completed", state.error
    api = od.bridge_module("fmp_research")
    before = od.fmp_capture_artifacts(state.handoff_dir)
    store = api.CaptureStore(state.handoff_dir, state.prompt, env={}, client=fmp_cases.CapturedClient(999))
    store.request("call", {"tool": "statements", "arguments": {"symbol": "OTHER"}})
    store.freeze()
    assert set(od.fmp_capture_artifacts(state.handoff_dir)) > set(before)
    launches = len(execution.launched)
    response = client.post(f"/api/research/{state.pipeline_id}/continue", json={})
    assert response.status_code == 400
    assert len(execution.launched) == launches


@pytest.mark.parametrize("damage", ["response_bytes", "entire_capture"])
def test_fork_revalidates_parent_after_admission(captured_target, client, damage):
    execution = captured_target
    state = target_cases._execute(execution)
    assert state.status == "completed", state.error
    response = client.post(f"/api/research/{state.pipeline_id}/scenario", json={"label": "Race check", "seed": 17})
    assert response.status_code == 200
    child = execution.po.PipelineState.from_dict(execution.po.PipelineManager.load(response.json["data"]["pipeline_id"]))
    acquisitions = len(execution.fmp_calls)
    damage_capture(Path(state.handoff_dir), execution.capture_item, damage)
    execution.po.PipelineOrchestrator._run(child)
    assert child.status == "failed"
    assert "receipts" in child.error or "fmp" in child.error.lower()
    assert len(execution.fmp_calls) == acquisitions
    assert child.stages["prepare"].status != "completed"


def test_no_fmp_target_keeps_closed_evidence_bytes_and_no_optional_carrier(execution, client):
    state = target_cases._execute(execution, "research_only")
    assert state.status == "completed", state.error
    root = Path(state.handoff_dir)
    before = (root / "target_evidence.json").read_bytes()
    assert set(json.loads(before)) == {"schemaVersion", "caseHash", "official_data", "markets", "news_market_context"}
    assert not (root / "target_fmp_evidence.json").exists()
    assert "target_fmp_evidence_binding" not in state.options
    assert not any(name.startswith("target_fmp_") for name, _ in tp.stage_specs(state, "research"))
    response = client.post(f"/api/research/{state.pipeline_id}/continue", json={})
    assert response.status_code == 200, response.json
    continued = execution.po.PipelineState.from_dict(execution.po.PipelineManager.load(state.pipeline_id))
    execution.po.PipelineOrchestrator._run(continued)
    assert continued.status == "completed", continued.error
    assert (root / "target_evidence.json").read_bytes() == before
    assert not (root / "target_fmp_evidence.json").exists()


def test_real_target_producer_exports_exact_vendor_provenance(tmp_path, monkeypatch, bridge, protocol):
    engine_cases._hermetic_env.__wrapped__(monkeypatch)
    fetch = engine_cases.install_target_fixture(monkeypatch, gaps=0)
    monkeypatch.setenv("FMP_ENABLED", "true")
    monkeypatch.setenv("FMP_API_KEY", fmp_protocol_cases.KEY)
    v3 = engine_cases.v3
    api = v3.rg._fmp_api()
    server, created = protocol

    class CaptureClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 27, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(api.client_api(), "datetime", CaptureClock)
    original = v3.lr._Engine.gather_kiqs

    def gather_with_financials(engine, *args, **kwargs):
        result = original(engine, *args, **kwargs)
        engine.tools.fmp_query("fmp_call", tool="statements", arguments={
            "endpoint": "income-statement", "symbol": "NVDA", "period": "annual", "limit": 1},
            agent_id="target-financials")
        return result

    monkeypatch.setattr(v3.lr._Engine, "gather_kiqs", gather_with_financials)
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, engine_cases.TargetWorld(),
        args=v3.make_args(forecast_authority="target-first-v1"), fetch=fetch)
    assert rc == 0, meta
    assert server.requests and created == [True]
    case = od.bridge_module("forecast_case").read_case(out / "forecast_case.json")
    exported = json.loads((out / "sources.json").read_bytes())
    vendors = [row for row in exported if row.get("provider") == "fmp"]
    assert vendors
    proof = tp._capture_fmp_evidence(out, case["question"], case)
    assert proof["binding"] == api.CaptureStore(out, case["question"], env={}, replay=True).proof()
    for row in vendors:
        assert {key: row[key] for key in api.metadata(row["fmp_capture"])} == api.metadata(row["fmp_capture"])
        typed = next(item for item in case["sources"] if item["sourceId"] == row["sourceId"])
        assert "fmp_capture" not in typed
        assert {key: row[key] for key in typed} == typed
        assert row["eligibility"]["anchor"] is False and row["eligibility"]["official_data"] is False


@pytest.mark.parametrize("change", ["parent_option", "resealed_parent", "child_option"])
def test_fork_metadata_cannot_replace_captured_fmp_generation(captured_target, client, change):
    execution = captured_target
    state = target_cases._execute(execution)
    assert state.status == "completed", state.error
    response = client.post(f"/api/research/{state.pipeline_id}/scenario", json={"label": "Metadata check", "seed": 17})
    assert response.status_code == 200
    child = execution.po.PipelineState.from_dict(execution.po.PipelineManager.load(response.json["data"]["pipeline_id"]))
    if change == "parent_option":
        state.options["target_fmp_evidence_binding"] = "0" * 64
        execution.po.PipelineManager.save(state)
    elif change == "child_option":
        child.options["target_fmp_evidence_binding"] = "0" * 64
    else:
        api = od.bridge_module("fmp_research")
        store = api.CaptureStore(state.handoff_dir, state.prompt, env={}, client=fmp_cases.CapturedClient(999))
        store.request("call", {"tool": "statements", "arguments": {"symbol": "REPLACEMENT"}})
        store.freeze()
        root = Path(state.handoff_dir)
        case = od.bridge_module("forecast_case").read_case(root / "forecast_case.json")
        replacement = tp._capture_fmp_evidence(root, state.prompt, case)
        (root / "target_fmp_evidence.json").write_text(json.dumps(replacement))
        state.options["target_fmp_evidence_binding"] = tp._digest(replacement)
        execution.po.PipelineManager.save(state)
        tp.record_stage(state, "research")
        assert tp.validate_stage(state, "research")
    acquisitions = len(execution.fmp_calls)
    execution.po.PipelineOrchestrator._run(child)
    assert child.status == "failed"
    assert "receipts" in child.error or "generation changed" in child.error
    assert child.stages["prepare"].status != "completed"
    assert len(execution.fmp_calls) == acquisitions
