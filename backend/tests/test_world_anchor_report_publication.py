"""Published target report authority and estimator privacy at real consumers."""
from copy import deepcopy
import json
from pathlib import Path

from flask import Flask
import pytest

from app.services import report_agent as ra, target_report as tr, forecast_tournament as ft
from app.services.pipeline_orchestrator import PipelineManager
from app.services.target_pipeline import record_stage
from test_world_anchor_records import native_target as _native_target, target_case as _target_case

native_target = _native_target
target_case = _target_case


def _write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False))


def _publish(native, tmp_path, monkeypatch, *, report_id="report_anchor_publication", multiple=False):
    from app.config import Config
    monkeypatch.setattr(ra.ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True)
    report_id += "_" + tr._hash(str(tmp_path))[:10]
    case = native["case"]
    if multiple:
        forecast = tr.build_target_report(case)["forecast"]
        estimators = ft.freeze_target_estimators(case, forecast, native["policy"], enabled=True, llm=None)
        assert len(estimators["estimators"]) > 1
        native["estimators"] = estimators
        _write(native["handoff"] / "target_estimators.json", estimators)
        state = native["pipeline_state"]
        state.options["target_estimators_binding"] = tr._hash(estimators)
        record_stage(state, "research")
        PipelineManager.save(state)

    def forbidden(*args, **kwargs):
        pytest.fail("stored target publication acquired a provider")

    monkeypatch.setattr(ra, "LLMClient", forbidden)
    monkeypatch.setattr(ra, "ZepToolsService", forbidden)
    monkeypatch.setattr(ft, "_method_lane", forbidden)
    agent = ra.ReportAgent(graph_id="target_graph_native", simulation_id=native["pipeline_state"].simulation_id,
        simulation_requirement=case["question"], forecast_case=case, target_simulation=native["result"],
        aggregation_policy=native["policy"], saved_estimators=native["estimators"],
        target_evidence=native["evidence"], anchor_context=native["context"])
    report = agent.generate_report(report_id=report_id)
    assert report.status == ra.ReportStatus.COMPLETED, report.error
    assert ra.ReportManager.publication_status(report_id)["publishable"]
    folder = Path(ra.ReportManager._get_report_folder(report_id))
    return agent, report, folder


@pytest.mark.parametrize("tamper", ["source", "lifecycle", "prepare", "result"])
def test_published_target_read_and_download_revalidate_external_anchor(native_target, tmp_path, monkeypatch, tamper):
    from app.api.report import report_bp
    _, report, folder = _publish(native_target, tmp_path, monkeypatch)
    app = Flask(__name__)
    app.register_blueprint(report_bp, url_prefix="/api/report")
    client = app.test_client()
    assert client.get(f"/api/report/{report.report_id}/forecast").status_code == 200
    assert client.get(f"/api/report/{report.report_id}/download").status_code == 200
    local_bytes = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    state = native_target["pipeline_state"]
    if tamper == "source":
        (native_target["handoff"] / "world_anchor_inputs/v3/pages/page.txt").write_text("Changed retained source.")
    elif tamper == "lifecycle":
        state.options["world_anchor_lifecycle"]["status"] = "pending"
        PipelineManager.save(state)
    elif tamper == "prepare":
        manifest = PipelineManager.load_artifact_manifest(state.pipeline_id)
        manifest.pop("target_case")
        PipelineManager.write_artifact_manifest(state.pipeline_id, manifest)
    else:
        result = deepcopy(native_target["result"])
        result["signposts"].append({"nodeId": "baseline", "value": 999})
        _write(native_target["directory"] / "target_simulation.json", result)
    status = ra.ReportManager.publication_status(report.report_id)
    assert not status["publishable"], status
    assert client.get(f"/api/report/{report.report_id}/forecast").status_code == 409
    assert client.get(f"/api/report/{report.report_id}/download").status_code == 409
    assert all((folder / name).read_bytes() == content for name, content in local_bytes.items())


@pytest.mark.parametrize("native_target", ["private"], indirect=True)
def test_multiple_frozen_estimators_cannot_reintroduce_private_simulation(native_target, tmp_path, monkeypatch):
    agent, report, folder = _publish(native_target, tmp_path, monkeypatch, multiple=True)
    before = json.loads((folder / "forecast.json").read_text())
    record = json.loads((folder / "target_report.json").read_text())
    assert record["worldAnchor"]["target_node_id"] is None
    assert record["targetSummary"] is None and record["divergence"] == []
    assert len(before["estimators"]) > 1
    assert all(row["source"] != "simulation" for row in before["estimators"])
    assert "files" not in before["quality"]["final_audit"]["target_report"]
    assert "target_simulation.json" in json.loads((folder / "final_audit.json").read_text())["target_report"]["files"]
    assert [row["probability"] for row in before["scenarios"]] == [0.5, 0.5]
    assert agent._audit_target_authority(report.report_id, before, (folder / "full_report.md").read_text())["valid"]
    changed = deepcopy(native_target["result"])
    changed["decisionBudget"] = {"maximumRequests": 128, "requests": 77, "cacheHits": 8, "exhausted": False}
    for path in changed["paths"]:
        path["plans"] = {"DENIED_ACTOR": [{"planId": "DENIED_PRIVATE_PLAN", "value": 99999}]}
    native_target["result"] = changed
    _write(native_target["directory"] / "target_simulation.json", changed)
    record_stage(native_target["pipeline_state"], "run")
    _, _, second = _publish(native_target, tmp_path, monkeypatch, report_id="report_anchor_publication_second")
    after = json.loads((second / "forecast.json").read_text())
    # Report identity and audit clock are intentionally different. No other
    # public field may depend on the private-only result perturbation.
    for value in (before, after):
        for key in ("audited_at", "report_id"):
            value["quality"]["final_audit"].pop(key)
    assert tr.canonical_json(after) == tr.canonical_json(before)
    assert "DENIED_" not in (second / "full_report.md").read_text()
