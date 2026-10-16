"""Export real synthetic API responses for an isolated browser acceptance server."""
import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.guarded_runner


def test_export_real_api_responses_for_browser(tmp_path, monkeypatch):
    from flask import Flask
    from app.api import simulation_bp
    from app.api import simulation  # noqa: F401
    from app.services.simulation_manager import SimulationManager
    from app.services.simulation_runner import SimulationRunner
    from test_world_service_results import prepare
    from app.services.world_simulation.examples import ExamplePolicy
    from app.services.world_simulation.service import run_child
    monkeypatch.setattr(SimulationManager, 'SIMULATION_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(SimulationRunner, 'RUN_STATE_DIR', str(tmp_path))
    _, state, directory = prepare(tmp_path)
    assert run_child(directory, policy=ExamplePolicy('investment')) == 0
    app = Flask(__name__)
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    client = app.test_client()
    prefix = '/api/simulation/' + state.simulation_id
    fixture = {'simulationId': state.simulation_id, 'responses': {}}
    response = client.get(prefix)
    assert response.status_code == 200
    fixture['state'] = response.get_json()
    for view, actor in [('public', None), ('analyst', None), ('actor', 'buyer')]:
        for round_index in range(5):
            query = {'view': view, 'round': round_index}
            if actor:
                query['actor_id'] = actor
            response = client.get(prefix + '/world', query_string=query)
            assert response.status_code == 200, response.get_json()
            fixture['responses'][f'{view}:{actor or ""}:{round_index}'] = response.get_json()
    path = Path(os.environ['MAIN_OFFLINE_EVIDENCE']) / 'browser-api-fixture.json'
    path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + '\n')
    assert fixture['responses']['public::4']['data']['world']['metrics']['capacity']['value'] == '7'
