"""Saved pipeline report IDs must obey current-cache retirement as well."""
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

import test_orchestrator_research_wiring as wiring
from app.services import pipeline_orchestrator as po
from app.services.report_agent import Report

pytestmark = pytest.mark.guarded_runner


@pytest.mark.parametrize("retired", [False, True])
def test_saved_report_id_cannot_bypass_current_simulation_retirement(monkeypatch, tmp_path, retired):
    actual_run = po.PipelineOrchestrator._run
    captured = []
    observed = {}

    def enter(cls, state):
        old_id = state.report_id
        folder = Path(po.ReportManager._get_report_folder(old_id))
        folder.mkdir(parents=True, exist_ok=True)
        historical = folder / "historical-publication-sentinel.txt"
        historical.write_text("Original published audit, forecast and narrative remain historical")
        before = historical.read_bytes()
        if retired:
            # Presence-only current-cache predicate; no publication gate is replaced.
            (folder / po.ReportManager._RETIREMENT_FILENAME).write_text('{"reason":"simulation_restart"}')

        def report(**kwargs):
            captured.append(kwargs)
            def generate(**request):
                return SimpleNamespace(report_id=request["report_id"], status=po.ReportStatus.COMPLETED)
            return SimpleNamespace(generate_report=generate)
        monkeypatch.setattr(po, "ReportAgent", report)
        actual_run(state)
        observed.update(status=state.status, error=state.error, report_id=state.report_id, old_id=old_id)
        assert historical.read_bytes() == before

    monkeypatch.setattr(po.PipelineOrchestrator, "_run", classmethod(enter))
    wiring._exercise_prepare_run_resume(monkeypatch, tmp_path, rebuild_prepare=False)
    assert observed["status"] == "completed", observed["error"]
    if retired:
        assert len(captured) == 1, "Saved report_id bypassed current-cache retirement"
        assert observed["report_id"] != observed["old_id"]
    else:
        assert not captured and observed["report_id"] == observed["old_id"]


@pytest.mark.parametrize("matching", [False, True])
def test_saved_native_report_must_belong_to_current_simulation(monkeypatch, tmp_path, matching):
    actual_run = po.PipelineOrchestrator._run
    native_get = po.ReportManager.get_report
    generated, observed = [], {}

    def enter(cls, state):
        report = Report(report_id=state.report_id,
                        simulation_id=state.simulation_id if matching else "sim_foreign_generation",
                        graph_id=state.graph_id, simulation_requirement=state.prompt,
                        status=po.ReportStatus.COMPLETED)
        path = Path(po.ReportManager._get_report_folder(state.report_id)) / "meta.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report.to_dict()))
        monkeypatch.setattr(po.ReportManager, "get_report", classmethod(lambda cls, rid: native_get(rid)))
        def producer(**kwargs):
            generated.append(kwargs)
            return SimpleNamespace(generate_report=lambda **request: Report(
                report_id=request["report_id"], simulation_id=kwargs["simulation_id"],
                graph_id=kwargs["graph_id"], simulation_requirement=kwargs["simulation_requirement"],
                status=po.ReportStatus.COMPLETED))
        monkeypatch.setattr(po, "ReportAgent", producer)
        actual_run(state)
        observed.update(status=state.status, error=state.error)

    monkeypatch.setattr(po.PipelineOrchestrator, "_run", classmethod(enter))
    wiring._exercise_prepare_run_resume(monkeypatch, tmp_path, rebuild_prepare=False)
    assert observed["status"] == "completed", observed["error"]
    assert len(generated) == (0 if matching else 1), "A foreign saved report satisfied current report work"
