"""The two simulation engines in one tree: guarantees for OASIS runs.

world-v1 (opt-in) arrived with code paths that also run for OASIS users. Pins: the
simulation list skips an unloadable entry (a duplicate folder name, a symlinked
directory, a corrupt state.json, world artefacts under an OASIS pin) instead of failing
for every engine; a world-v1 run that fails integrity verification fails a list that
selects it closed (world-v1's rule) but is skipped by the cross-project history index;
the shutdown cleanup survives a failing world-v1 stop and still runs the OASIS
teardown; the default engine stays oasis-legacy.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.services import simulation_manager as sm  # noqa: E402
from app.services import simulation_runner as sr  # noqa: E402


def _state(directory, **extra):
    os.makedirs(directory, exist_ok=True)
    payload = {"simulation_id": os.path.basename(directory), "project_id": "proj_1", "graph_id": "g1",
               "status": "completed", **extra}
    with open(os.path.join(directory, "state.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f)


def test_default_engine_is_oasis():
    assert Config.DEFAULT_SIMULATION_ENGINE == "oasis-legacy"
    assert sm.validate_simulation_engine("oasis-legacy") == "oasis-legacy"


def test_list_skips_unloadable_entries_instead_of_failing(tmp_path, monkeypatch):
    root = tmp_path / "simulations"
    _state(str(root / "sim_good"))
    _state(str(root / "sim_good copy"))                                    # Finder duplicate: invalid id
    _state(str(tmp_path / "elsewhere" / "sim_real"))
    os.symlink(str(tmp_path / "elsewhere" / "sim_real"), str(root / "sim_link"))   # symlinked directory
    os.makedirs(str(root / "sim_corrupt"))
    (root / "sim_corrupt" / "state.json").write_text("{not json", encoding="utf-8")
    _state(str(root / "sim_mislabelled"), world_generation_id="gen_1")    # world pin under an OASIS engine
    os.makedirs(str(root / "logs"))                                       # no state.json: not a simulation
    monkeypatch.setattr(sm.SimulationManager, "SIMULATION_DATA_DIR", str(root), raising=False)
    manager = sm.SimulationManager()
    sims = manager.list_simulations()
    assert [s.simulation_id for s in sims] == ["sim_good"]
    assert sims[0].simulation_engine == "oasis-legacy"
    assert [s.simulation_id for s in manager.list_simulations(project_id="proj_1")] == ["sim_good"]
    assert manager.list_simulations(project_id="other") == []



def test_damaged_world_fails_a_list_that_selects_it_but_not_the_history(tmp_path, monkeypatch):
    root = tmp_path / "simulations"
    _state(str(root / "sim_oasis"))
    _state(str(root / "sim_world"), project_id="proj_world")
    monkeypatch.setattr(sm.SimulationManager, "SIMULATION_DATA_DIR", str(root), raising=False)
    manager = sm.SimulationManager()
    original = manager._project_world_status

    def _verify(state):
        if state.simulation_id == "sim_world":
            raise ValueError("Prepared world bytes changed")             # stands in for a WorldError
        return original(state)

    monkeypatch.setattr(manager, "_project_world_status", _verify)
    assert [s.simulation_id for s in manager.list_simulations(skip_unverifiable_worlds=True)] == ["sim_oasis"]
    assert [s.simulation_id for s in manager.list_simulations(project_id="proj_1")] == ["sim_oasis"]
    for selecting in ({}, {"project_id": "proj_world"}):
        with pytest.raises(ValueError):
            manager.list_simulations(**selecting)


def test_history_endpoint_survives_a_damaged_world(tmp_path, monkeypatch):
    from app import create_app
    from app.models.project import ProjectManager
    from app.services.report_agent import ReportManager

    root = tmp_path / "simulations"
    _state(str(root / "sim_oasis"))
    _state(str(root / "sim_world"), project_id="proj_world")
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(root))
    monkeypatch.setattr(sm.SimulationManager, "SIMULATION_DATA_DIR", str(root), raising=False)
    monkeypatch.setattr(sr.SimulationRunner, "RUN_STATE_DIR", str(root), raising=False)
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path / "projects"), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    original = sm.SimulationManager._project_world_status

    def _verify(self, state):
        if state.simulation_id == "sim_world":
            raise ValueError("Prepared world bytes changed")             # stands in for a WorldError
        return original(self, state)

    monkeypatch.setattr(sm.SimulationManager, "_project_world_status", _verify)
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    history = client.get("/api/simulation/history")
    assert history.status_code == 200, history.get_json()
    assert [row["simulation_id"] for row in history.get_json()["data"]] == ["sim_oasis"]
    assert client.get("/api/simulation/list").status_code == 500             # a list that selects it fails closed
    assert client.get("/api/simulation/list?project_id=proj_1").status_code == 200

def test_cleanup_survives_a_failing_world_stop(monkeypatch):
    from app.services.world_simulation import service as world_service

    calls = []

    def _boom(simulation_id, root=None):
        calls.append(simulation_id)
        raise RuntimeError("store not initialised")

    monkeypatch.setattr(world_service.WorldSimulationService, "stop", staticmethod(_boom))
    monkeypatch.setattr(sr.SimulationRunner, "_world_simulations", {"sim_w1": object(), "sim_w2": object()},
                        raising=False)
    monkeypatch.setattr(sr.SimulationRunner, "_cleanup_done", False, raising=False)

    class _Exited:
        pid = 4242

        def poll(self):
            return 0                                                       # already exited: nothing to kill

    monkeypatch.setattr(sr.SimulationRunner, "_processes", {"sim_oasis": _Exited()}, raising=False)
    monkeypatch.setattr(sr.SimulationRunner, "_graph_memory_enabled", {}, raising=False)
    sr.SimulationRunner.cleanup_all_simulations()                          # must not raise
    assert sorted(calls) == ["sim_w1", "sim_w2"]                           # every world was attempted
    assert sr.SimulationRunner._world_simulations == {}
    assert sr.SimulationRunner._cleanup_done is True                       # the OASIS teardown ran
