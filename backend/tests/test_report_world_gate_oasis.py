"""OASIS reports behind world-v1's report integrity gate.

world-v1 added a ``before_request`` gate to every ``/api/report/<id>/...`` route and a
canonical world reader that rejects floats.  Report telemetry writes floats into the
report's own meta.json (``telemetry.totals.duration_s``, ``est_cost_usd``,
``latency_ms``; 30 of 72 saved reports on 2026-10-18), so a strict read of meta.json
answered 409 for ordinary reports.  These pins keep such reports readable and keep
world artefacts without a saved world identity failing closed.

All checks are offline: tmp REPORTS_DIR and simulation root, no LLM, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import Config
from app.services.report_agent import Report, ReportManager, ReportStatus
from app.services.world_simulation.contracts import WorldError

TELEMETRY = {"totals": {"duration_s": 812.4, "est_cost_usd": 0.4213, "latency_ms": 2311.7}}


@pytest.fixture
def storage(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(reports))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path / "simulations"))
    return reports


@pytest.fixture
def client(storage):
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _save_oasis_report(report_id: str, simulation_id: str = "sim_d6ebcc77e22d") -> Path:
    ReportManager.save_report(Report(
        report_id=report_id,
        simulation_id=simulation_id,
        graph_id="graph_test",
        simulation_requirement="Forecast the outcome.",
        status=ReportStatus.COMPLETED,
        markdown_content="# Forecast\n\nBody.",
        created_at="2026-10-18T00:00:00+00:00",
    ))
    folder = Path(ReportManager._get_report_folder(report_id))
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    meta["telemetry"] = TELEMETRY  # the shape the final telemetry save writes
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return folder


def test_oasis_report_with_telemetry_floats_has_no_world(storage):
    _save_oasis_report("report_oasis_floats")
    assert ReportManager.load_world_result("report_oasis_floats") is None


def test_report_api_serves_oasis_report_with_telemetry_floats(client):
    _save_oasis_report("report_oasis_api")
    response = client.get("/api/report/report_oasis_api")
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["success"] is True
    # CORS preflight carries no report data and is not gated
    assert client.open("/api/report/report_oasis_api", method="OPTIONS").status_code != 409


def test_world_artefacts_without_saved_identity_still_fail_closed(client):
    folder = _save_oasis_report("report_orphan_world")
    (folder / "world_result.json").write_text("{}", encoding="utf-8")
    with pytest.raises(WorldError):
        ReportManager.load_world_result("report_orphan_world")
    response = client.get("/api/report/report_orphan_world")
    assert response.status_code == 409
    assert response.get_json()["code"] == "world_result_integrity"
