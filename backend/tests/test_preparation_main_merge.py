"""Cross-branch PREPARE revocation preserves artifacts and removes execution authority."""
import hashlib
import json

import pytest

from app.config import Config
from app.services import official_data
from app.services.forecast_task import KEY
from app.services.simulation_manager import SimulationStatus
from app.services.simulation_runner import SimulationRunner
from scripts.run_parallel_simulation import validate_direct_child_config_seal
from test_actor_context_runtime import (
    REPORT, _prepare_offline_simulation, _mock_actor_context_external_calls,
)


def artifact_hashes(directory):
    return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob("*") if p.is_file() and p.name != "state.json"}


@pytest.mark.parametrize("hours", [False, True])
def test_rejected_reprepare_revokes_calendar_and_hours_without_replacing_artifacts(tmp_path, monkeypatch, hours):
    from app.api.simulation import _check_simulation_prepared
    manager, state, dossier = _prepare_offline_simulation(tmp_path, monkeypatch)
    directory = tmp_path / state.simulation_id
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    if hours:
        # A real sealed preparation without a task marker covers the hours
        # compatibility lane; revocation must not depend on calendar admission.
        config = json.loads((directory / "simulation_config.json").read_text())
        config.pop(KEY, None)
        config.pop("temporal_config", None)
        (directory / "simulation_config.json").write_text(json.dumps(config))
        state.forecast_task_version = None
        manager._save_simulation_state(state)
        manager.reseal_simulation_config(state.simulation_id)
    manager.validate_prepared_simulation_config(state.simulation_id)
    prepared = _check_simulation_prepared(state.simulation_id)
    assert prepared[0] is True, prepared
    before = artifact_hashes(directory)
    with monkeypatch.context() as patch:
        patch.setattr(official_data, "simulation_research_binding", lambda _: {"status": "invalid"})
        with pytest.raises(ValueError, match="generation changed"):
            manager.prepare_simulation(state.simulation_id, "Model the grid permit", REPORT,
                                       actors=dossier, use_llm_for_profiles=False)
    after = manager.get_simulation(state.simulation_id)
    assert after.status == SimulationStatus.FAILED and after.config_generated is False
    assert artifact_hashes(directory) == before
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="not completed|revoked"):
        manager.validate_prepared_simulation_config(state.simulation_id)
    with pytest.raises(ValueError, match="not completed|revoked"):
        validate_direct_child_config_seal(str(directory / "simulation_config.json"))
    with pytest.raises(ValueError, match="not completed|revoked"):
        SimulationRunner.start_simulation(state.simulation_id)
    assert _check_simulation_prepared(state.simulation_id)[0] is False
    assert artifact_hashes(directory) == before
    # A subsequent successful producer can explicitly restore authority.
    monkeypatch.setattr(Config, "SIM_TEMPORAL_MODE", "calendar")
    ready = manager.prepare_simulation(state.simulation_id, "Model the grid permit", REPORT,
                                       actors=dossier, use_llm_for_profiles=False, research_language="English")
    assert ready.status == SimulationStatus.READY and ready.config_generated
    manager.validate_prepared_simulation_config(state.simulation_id)
