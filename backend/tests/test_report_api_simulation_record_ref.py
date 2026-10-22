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
def api(monkeypatch):
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


def _publish_record(sim_id: str, *, passed: bool = True, sha: str = "a" * 64) -> Path:
    sim_dir = Path(Config.OASIS_SIMULATION_DATA_DIR) / sim_id
    sim_dir.mkdir(parents=True)
    (sim_dir / "simulation_record.json").write_text(json.dumps({"schema": "simulation-record/v1"}))
    (sim_dir / "simulation_record.md").write_text("# record\n")
    (sim_dir / "simulation_record_audit.json").write_text(json.dumps({
        "sha256": sha, "hard_issues": [] if passed else ["G2: number 7 not in artifacts"],
        "warnings": [], "publication_status": "passed" if passed else "failed"}))
    return sim_dir


def _payload(api, report):
    with Flask(__name__).test_request_context():
        return api.get_report(report.report_id).get_json()["data"]


def test_payload_carries_record_ref_and_bridge_policy_when_the_gate_passed(api, monkeypatch):
    report = _report("sim_ref_passed")
    _publish_record("sim_ref_passed", sha="b" * 64)
    monkeypatch.setattr(ReportManager, "load_structured_forecast",
                        classmethod(lambda cls, rid: {"simulation_bridge": {
                            "sha256": "c" * 64, "forecast_effect": "diagnostic_only",
                            "probabilityEvidence": False}}))
    data = _payload(api, report)
    assert data["simulation_record_ref"] == {"sha256": "b" * 64, "url": "/api/simulation/sim_ref_passed/record"}
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


def test_record_ref_falls_back_to_the_record_file_hash_and_refuses_unsafe_ids(api, monkeypatch):
    report = _report("sim_ref_nosha")
    sim_dir = _publish_record("sim_ref_nosha", sha="")
    monkeypatch.setattr(ReportManager, "load_structured_forecast", classmethod(lambda cls, rid: None))
    monkeypatch.setattr(api, "_pinned_simulation_policy", lambda report_dir: None)
    data = _payload(api, report)
    expected = hashlib.sha256((sim_dir / "simulation_record.md").read_bytes()).hexdigest()
    assert data["simulation_record_ref"] == {"sha256": expected, "url": "/api/simulation/sim_ref_nosha/record"}
    # a simulation id that escapes the simulations root never produces a reference
    unsafe = Report(report_id="report_unsafe", simulation_id="../sim_ref_nosha", graph_id="g",
                    simulation_requirement="x", status=ReportStatus.COMPLETED, markdown_content="# x")
    assert api._simulation_record_ref(unsafe) is None
