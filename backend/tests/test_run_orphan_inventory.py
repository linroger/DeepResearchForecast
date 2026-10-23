"""Finder metadata is not a simulation and must not enter orphan recovery."""
import logging

from app.config import Config
from app.services.simulation_runner import SimulationRunner


def test_recovery_inventory_ignores_files_but_checks_simulation_directories(tmp_path, monkeypatch, caplog):
    (tmp_path / ".DS_Store").write_bytes(b"finder metadata")
    (tmp_path / "sim_notes.txt").write_text("not a simulation")
    (tmp_path / "sim_saved").mkdir()
    monkeypatch.setattr(Config, "SIMULATION_RECLAIM_PORT_PROBE", False)
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationRunner, "_processes", {})
    original = SimulationRunner.simulation_engine
    inspected = []

    def inspect(cls, simulation_id):
        inspected.append(simulation_id)
        return original(simulation_id)

    monkeypatch.setattr(SimulationRunner, "simulation_engine", classmethod(inspect))
    with caplog.at_level(logging.ERROR):
        SimulationRunner.reconcile_orphans()
    assert inspected == ["sim_saved"]
    assert not caplog.records
