"""ADR 0003 slice S3.7 — GET /api/report/<id> carries ``forecast_effect`` and, only for a
gate-passed Simulation After-Action Record, ``simulation_record_ref {sha256, url}``."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from flask import Flask

from app.config import Config
from app.services.report_agent import Report, ReportManager, ReportStatus


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path / "simulations"))
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    from app.api import report as api_module
    monkeypatch.setattr(ReportManager, "publication_status", lambda *a, **kw: {"publishable": True})
    monkeypatch.setattr(ReportManager, "translation_status", lambda *a, **kw: {})
    return api_module


def _report(sim_id: str) -> Report:
    report = Report(report_id=f"report_{sim_id}", simulation_id=sim_id, graph_id="graph_fixture",
                    simulation_requirement="Fixture outlook", status=ReportStatus.COMPLETED,
                    markdown_content="# Fixture\n\nBody.")
    ReportManager.save_report(report)
    return report


def _publish_record(sim_id: str, *, passed: bool = True) -> Path:
    from tests.test_sim_bridge_isolation import write_sim, TOKENS
    sim_dir = write_sim(Path(Config.OASIS_SIMULATION_DATA_DIR), sim_id,
                        shares={"Expansion": 0.44, "Status quo": 0.56}, token=TOKENS[0])
    if not passed:
        audit_path = sim_dir / "simulation_record_audit.json"
        audit = json.loads(audit_path.read_text())
        audit.update(publication_status="failed", hard_issues=["G2: synthetic rejection"])
        audit_path.write_text(json.dumps(audit))
    return sim_dir


def _payload(api, report):
    with Flask(__name__).test_request_context():
        return api.get_report(report.report_id).get_json()["data"]


def test_payload_carries_record_ref_and_bridge_policy_when_the_gate_passed(api, monkeypatch):
    report = _report("sim_ref_passed")
    directory = _publish_record("sim_ref_passed")
    expected = hashlib.sha256((directory / "simulation_record.json").read_bytes()).hexdigest()
    monkeypatch.setattr(ReportManager, "load_structured_forecast",
                        classmethod(lambda cls, rid: {"simulation_bridge": {
                            "sha256": "c" * 64, "forecast_effect": "diagnostic_only",
                            "probabilityEvidence": False}}))
    data = _payload(api, report)
    assert data["simulation_record_ref"] == {"sha256": expected, "url": "/api/simulation/sim_ref_passed/record"}
    assert data["forecast_effect"] == "diagnostic_only"


def test_payload_omits_record_ref_for_failed_or_missing_gate_and_reads_pinned_policy(api, monkeypatch):
    from app.api import report as api_module
    report = _report("sim_ref_failed")
    _publish_record("sim_ref_failed", passed=False)
    monkeypatch.setattr(ReportManager, "load_structured_forecast", classmethod(lambda cls, rid: None))
    monkeypatch.setattr(api_module, "_pinned_simulation_policy", lambda report_dir: "no_update")
    data = _payload(api, report)
    assert "simulation_record_ref" not in data
    assert data["forecast_effect"] == "no_update"
    # no record at all, no pinned policy: the payload states nothing it did not read
    other = _report("sim_ref_absent")
    monkeypatch.setattr(api_module, "_pinned_simulation_policy", lambda report_dir: None)
    data = _payload(api, other)
    assert "simulation_record_ref" not in data and data["forecast_effect"] is None


def test_record_ref_rejects_missing_seal_tampering_and_unsafe_ids(api, monkeypatch):
    report = _report("sim_ref_nosha")
    sim_dir = _publish_record("sim_ref_nosha")
    monkeypatch.setattr(ReportManager, "load_structured_forecast", classmethod(lambda cls, rid: None))
    monkeypatch.setattr(api, "_pinned_simulation_policy", lambda report_dir: "diagnostic_only")
    assert "simulation_record_ref" in _payload(api, report)
    audit_path = sim_dir / "simulation_record_audit.json"
    audit = json.loads(audit_path.read_text())
    audit["sha256"] = ""
    audit_path.write_text(json.dumps(audit))
    assert "simulation_record_ref" not in _payload(api, report)
    unsafe = Report(report_id="report_unsafe", simulation_id="../sim_ref_nosha", graph_id="g",
                    simulation_requirement="x", status=ReportStatus.COMPLETED, markdown_content="# x")
    assert api._simulation_record_ref(unsafe) is None


@pytest.mark.parametrize("name", ["simulation_record.json", "simulation_record.md", "simulation_record.zh.md",
                                  "world_state_history.jsonl"])
def test_changed_record_or_input_never_receives_report_link(api, name):
    report = _report("sim_ref_tamper")
    directory = _publish_record(report.simulation_id)
    assert api._simulation_record_ref(report) is not None
    path = directory / name
    path.write_text(path.read_text() + " ")
    assert api._simulation_record_ref(report) is None


def test_no_update_omits_link_even_when_record_is_available(api, monkeypatch):
    report = _report("sim_no_update_with_record")
    monkeypatch.setattr(api, "_report_forecast_effect", lambda report: "no_update")
    monkeypatch.setattr(api, "_simulation_record_ref", lambda report: {"sha256": "a" * 64, "url": "/record"})
    data = _payload(api, report)
    assert data["forecast_effect"] == "no_update"
    assert "simulation_record_ref" not in data


@pytest.mark.parametrize('policy', ['no_update', None])
def test_durable_audited_policy_controls_link_without_telemetry(api, monkeypatch, policy):
    report = _report('sim_ref_no_telemetry')
    _publish_record(report.simulation_id)
    forecast = {'quality': {'final_audit': {'simulation_bridge': {'policy': policy}}}}
    monkeypatch.setattr(ReportManager, 'load_structured_forecast', classmethod(lambda cls, rid: forecast))
    monkeypatch.setattr(api, '_pinned_simulation_policy', lambda folder: None)
    payload = _payload(api, report)
    assert payload['forecast_effect'] == policy
    assert 'simulation_record_ref' not in payload
