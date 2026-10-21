"""Regression coverage for process-lifecycle isolation.

The Flask app factory owns destructive startup hooks in production.  A test
process must never run those hooks against the shared localhost uploads tree,
nor write into that tree, and a duplicate backend must not reclaim a simulator
owned by the backend that already holds the configured port.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

from app import create_app
from app.config import Config
from app.services.pipeline_orchestrator import PipelineOrchestrator
from app.services.simulation_runner import SimulationRunner


def test_app_factory_skips_destructive_lifecycle_in_test_process(monkeypatch):
    calls: list[str] = []
    monkeypatch.setenv("DRF_TEST_PROCESS", "1")
    monkeypatch.setattr(
        SimulationRunner,
        "register_cleanup",
        classmethod(lambda cls: calls.append("simulation-register")),
    )
    monkeypatch.setattr(
        SimulationRunner,
        "reconcile_orphans",
        classmethod(lambda cls: calls.append("simulation-reconcile")),
    )
    monkeypatch.setattr(
        PipelineOrchestrator,
        "register_cleanup",
        classmethod(lambda cls: calls.append("pipeline-register")),
    )
    monkeypatch.setattr(
        PipelineOrchestrator,
        "reconcile_orphans",
        classmethod(lambda cls: calls.append("pipeline-reconcile")),
    )

    app = create_app()

    assert app is not None
    assert calls == []


def test_app_factory_keeps_production_lifecycle_when_test_marker_absent(monkeypatch):
    calls: list[str] = []
    monkeypatch.delenv("DRF_TEST_PROCESS", raising=False)
    monkeypatch.setattr(
        SimulationRunner,
        "register_cleanup",
        classmethod(lambda cls: calls.append("simulation-register")),
    )
    monkeypatch.setattr(
        SimulationRunner,
        "reconcile_orphans",
        classmethod(lambda cls: calls.append("simulation-reconcile")),
    )
    monkeypatch.setattr(
        PipelineOrchestrator,
        "register_cleanup",
        classmethod(lambda cls: calls.append("pipeline-register")),
    )
    monkeypatch.setattr(
        PipelineOrchestrator,
        "reconcile_orphans",
        classmethod(lambda cls: calls.append("pipeline-reconcile")),
    )

    app = create_app()

    assert app is not None
    assert calls == [
        "simulation-register",
        "simulation-reconcile",
        "pipeline-reconcile",
        "pipeline-register",
    ]


class _OccupiedPort:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_simulation_orphan_reconcile_skips_when_backend_port_is_owned(
    tmp_path, monkeypatch,
):
    run_root = tmp_path / "simulations"
    run_root.mkdir()
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(run_root))
    monkeypatch.setattr(Config, "SIMULATION_RECLAIM_PORT_PROBE", True, raising=False)
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *args, **kwargs: _OccupiedPort(),
    )

    def _unexpected_kill(cls, state):
        raise AssertionError(f"must not reclaim {state.simulation_id}")

    monkeypatch.setattr(
        SimulationRunner,
        "_kill_orphan_simulation",
        classmethod(_unexpected_kill),
    )

    SimulationRunner.reconcile_orphans()


@pytest.mark.skipif(bool(os.environ.get("MAIN_OFFLINE_EVIDENCE")),
                    reason="the guarded runner redirects storage at import time and denies "
                           "writes outside its evidence directory")
def test_storage_roots_stay_out_of_the_checkout_uploads():
    """conftest's ``_no_checkout_uploads``: no storage root a test writes through
    resolves into the checkout's own backend/uploads (in the deployment checkout,
    the live forecast ledger, reports and simulations)."""
    from app.services import forecast_ledger
    from app.services.report_agent import ReportManager
    from app.services.simulation_manager import SimulationManager

    checkout_uploads = Path(__file__).resolve().parents[1] / "uploads"
    roots = {
        "Config.UPLOAD_FOLDER": Config.UPLOAD_FOLDER,
        "Config.PIPELINE_DATA_DIR": Config.PIPELINE_DATA_DIR,
        "Config.OASIS_SIMULATION_DATA_DIR": Config.OASIS_SIMULATION_DATA_DIR,
        "forecast_ledger.ledger_dir()": forecast_ledger.ledger_dir(),
        "ReportManager.REPORTS_DIR": ReportManager.REPORTS_DIR,
        "SimulationManager.SIMULATION_DATA_DIR": SimulationManager.SIMULATION_DATA_DIR,
        "SimulationRunner.RUN_STATE_DIR": SimulationRunner.RUN_STATE_DIR,
    }
    inside = {name: value for name, value in roots.items()
              if Path(value).resolve().is_relative_to(checkout_uploads)}
    assert inside == {}

