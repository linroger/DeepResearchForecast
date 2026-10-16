"""M0 admission contract at the existing public simulation start boundary."""

from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.guarded_runner


@pytest.fixture
def legacy_start_boundary(monkeypatch):
    """Use the real route/state types; replace storage and process dispatch only."""
    from flask import Flask

    from app.api import simulation_bp
    from app.api import simulation as api
    from app.services.simulation_manager import SimulationState, SimulationStatus
    from app.services.simulation_runner import RunnerStatus, SimulationRunState

    # Historical prepared states have no world engine identity or world manifest.
    state = SimulationState(
        simulation_id="sim_m0_legacy_prepared",
        project_id="project_m0_synthetic",
        graph_id="graph_m0_synthetic",
        status=SimulationStatus.READY,
        config_generated=True,
        entities_count=1,
        profiles_count=1,
    )
    lookups = []
    launches = []
    saves = []

    def get_simulation(_manager, simulation_id):
        lookups.append(simulation_id)
        return state if simulation_id == state.simulation_id else None

    def save_simulation(_manager, saved_state):
        saves.append(saved_state.to_dict())

    def start_legacy_simulation(**kwargs):
        launches.append(dict(kwargs))
        return SimulationRunState(
            simulation_id=kwargs["simulation_id"],
            runner_status=RunnerStatus.RUNNING,
            twitter_running=True,
            reddit_running=True,
        )

    monkeypatch.setattr(api.SimulationManager, "get_simulation", get_simulation)
    monkeypatch.setattr(api.SimulationManager, "_save_simulation_state", save_simulation)
    monkeypatch.setattr(
        api.SimulationRunner, "start_simulation", staticmethod(start_legacy_simulation)
    )

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(simulation_bp, url_prefix="/api/simulation")
    return SimpleNamespace(
        client=app.test_client(), state=state, lookups=lookups,
        launches=launches, saves=saves,
    )


def test_legacy_start_without_engine_still_dispatches(legacy_start_boundary):
    boundary = legacy_start_boundary

    response = boundary.client.post(
        "/api/simulation/start",
        json={"simulation_id": boundary.state.simulation_id},
    )

    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["success"] is True
    assert body["data"]["runner_status"] == "running"
    assert boundary.lookups == [boundary.state.simulation_id]
    assert boundary.launches == [{
        "simulation_id": boundary.state.simulation_id,
        "platform": "parallel",
        "max_rounds": None,
        "enable_graph_memory_update": False,
        "graph_id": None,
    }]
    assert len(boundary.saves) == 1
    assert boundary.saves[0]["status"] == "running"
    assert boundary.state.status.value == "running"


def test_world_engine_request_rejects_legacy_prepared_simulation(legacy_start_boundary):
    boundary = legacy_start_boundary
    before = boundary.state.to_dict()

    response = boundary.client.post(
        "/api/simulation/start",
        json={
            "simulation_id": boundary.state.simulation_id,
            "simulation_engine": "world-v1",
        },
    )

    body = response.get_json()
    assert response.status_code == 409, (
        "world-v1 requested for legacy preparation must return HTTP 409 engine "
        f"mismatch before launch; got HTTP {response.status_code}, "
        f"success={body.get('success')}, legacy_launches={boundary.launches!r}, "
        f"saved_statuses={[saved['status'] for saved in boundary.saves]!r}"
    )
    assert body["success"] is False
    # Freeze the meaning, without prescribing a future error-code/envelope schema.
    error = str(body["error"])
    assert "world-v1" in error and "oasis-legacy" in error, body
    assert boundary.lookups == [boundary.state.simulation_id]
    assert boundary.launches == [], "Engine mismatch must never dispatch OASIS"
    assert boundary.saves == [], "Engine mismatch must not persist RUNNING"
    assert boundary.state.to_dict() == before
