"""Offline public API checks for the target-first UI artifact boundary."""
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from app.api import graph, simulation, graph_bp, simulation_bp
from app.config import Config
from app.services.target_simulation import run_paths
from deerflow_bridge.forecast_case import validate_case, case_hash, graph_projection, simulation_projection


@pytest.fixture
def target_api(tmp_path, monkeypatch):
    pipeline_root, simulation_root = tmp_path / 'pipelines', tmp_path / 'simulations'
    handoff = pipeline_root / 'pipe_ui' / 'handoff'
    sim_dir = simulation_root / 'sim_ui'
    handoff.mkdir(parents=True)
    sim_dir.mkdir(parents=True)
    monkeypatch.setattr(Config, 'PIPELINE_DATA_DIR', str(pipeline_root))
    monkeypatch.setattr(Config, 'OASIS_SIMULATION_DATA_DIR', str(simulation_root))
    monkeypatch.setattr(Config, 'ZEP_API_KEY', '')
    case = validate_case(json.loads((Path(__file__).parent / 'fixtures/target_case.json').read_text()))
    digest = case_hash(case)
    settings = {'paths': 2, 'periods': 2, 'seed': 7}
    binding = {'authority': 'target-first-v1', 'caseId': case['caseId'], 'caseHash': digest,
               'questionHash': hashlib.sha256(json.dumps(case['question'], ensure_ascii=False,
                                                        separators=(',', ':')).encode()).hexdigest(),
               'policyVersion': 1}
    state = {'pipeline_id': 'pipe_ui', 'prompt': case['question'], 'graph_id': 'target_graph_pipe_ui', 'simulation_id': 'sim_ui',
             'handoff_dir': str(handoff), 'options': {'forecast_authority': 'target-first-v1', 'target_simulation': settings}}
    state['options']['target_case_binding'] = binding
    state['options']['target_decision_budget_v1'] = {'max_calls': 128}
    state_file = pipeline_root / 'pipe_ui' / 'pipeline_state.json'
    manifest = {}

    def write(path, data):
        path.write_text(json.dumps(data, allow_nan=False))

    def seal(name, path, data):
        write(path, data)
        manifest[name] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        write(handoff / 'manifest.json', manifest)

    write(state_file, state)
    projection = {**graph_projection(case), 'graph_id': 'target_graph_pipe_ui'}
    result = run_paths(case, **settings)
    inputs = {'schemaVersion': 'target-input/v1', 'pipelineId': 'pipe_ui', 'caseHash': digest,
              'simulation': settings, 'structure': simulation_projection(case), 'simulationWeight': 0.0,
              'decisionBudget': {'max_calls': 128}}
    seal('forecast_case', handoff / 'forecast_case.json', case)
    seal('target_graph', handoff / 'target_graph.json', projection)
    seal('target_case', sim_dir / 'target_case.json', case)
    seal('target_input', sim_dir / 'target_input.json', inputs)
    seal('target_simulation', sim_dir / 'target_simulation.json', result)
    def forbidden(*args, **kwargs):
        pytest.fail('Target reads must not acquire Graphiti or a legacy simulation manager')
    monkeypatch.setattr(graph, 'GraphBuilderService', forbidden)
    monkeypatch.setattr(simulation, 'SimulationManager', forbidden)
    monkeypatch.setattr(simulation, 'ZepEntityReader', forbidden)
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    return SimpleNamespace(client=app.test_client(), root=tmp_path, handoff=handoff, sim_dir=sim_dir,
                           state=state, state_file=state_file, case=case, result=result, inputs=inputs,
                           projection=projection, write=write, seal=seal, manifest=manifest)


TARGET = '/api/simulation/sim_ui/target?pipeline_id=pipe_ui'
GRAPH = '/api/graph/data/target_graph_pipe_ui'


def test_real_case_projection_and_paths_read_without_mutation_or_providers(target_api):
    a = target_api
    before = {str(p): p.read_bytes() for p in a.root.rglob('*.json')}
    response = a.client.get(TARGET)
    assert response.status_code == 200, response.json
    data = response.json['data']
    assert data['pipelineId'] == 'pipe_ui'
    assert data['simulationId'] == 'sim_ui'
    assert data['caseHash'] == case_hash(a.case)
    assert data['simulation'] == a.result
    assert data['simulation']['simulationWeight'] == 0
    assert 'assessments' not in data
    assert any(node.get('basis') == 'assumed' for node in data['nodes'])
    response = a.client.get(GRAPH)
    assert response.status_code == 200, response.json
    assert response.json['data']['nodes'] == a.projection['nodes']
    assert response.json['data']['node_count'] == len(a.projection['nodes'])
    assert before == {str(p): p.read_bytes() for p in a.root.rglob('*.json')}


def test_cold_backend_import_uses_fixed_bridge_loader_without_repo_path(target_api, monkeypatch):
    repo = Path(__file__).resolve().parents[2]
    monkeypatch.setattr(sys, 'path', [p for p in sys.path if Path(p or '.').resolve() != repo])
    for name in list(sys.modules):
        if name == 'deerflow_bridge' or name.startswith('deerflow_bridge.'):
            monkeypatch.delitem(sys.modules, name)
    before = list(sys.path)
    assert target_api.client.get(TARGET).status_code == 200
    assert target_api.client.get(GRAPH).status_code == 200
    assert sys.path == before


@pytest.mark.parametrize('field', ['caseId', 'caseHash', 'questionHash', 'authority', 'policyVersion'])
def test_frozen_case_binding_is_required_even_for_consistent_sealed_artifacts(target_api, field):
    a = target_api
    a.state['options']['target_case_binding'][field] = 'different'
    a.write(a.state_file, a.state)
    assert a.client.get(TARGET).status_code == 409
    assert a.client.get(GRAPH).status_code == 409


@pytest.mark.parametrize('settings', [{'paths': 1, 'periods': 2, 'seed': 7},
                                     {'paths': 2, 'periods': 1, 'seed': 7},
                                     {'paths': 2, 'periods': 2, 'seed': 99}])
def test_same_case_results_from_different_execution_settings_are_rejected(target_api, settings):
    a = target_api
    a.seal('target_simulation', a.sim_dir / 'target_simulation.json', run_paths(a.case, **settings))
    assert a.client.get(TARGET).status_code == 409


def test_decision_budget_binding_and_optional_exhaustion_diagnostic(target_api):
    a = target_api
    a.result['decisionBudget'] = {'maximumRequests': 128, 'requests': 128, 'cacheHits': 3, 'exhausted': True}
    a.seal('target_simulation', a.sim_dir / 'target_simulation.json', a.result)
    assert a.client.get(TARGET).json['data']['simulation']['decisionBudget']['exhausted'] is True
    a.state['options']['target_decision_budget_v1'] = {'max_calls': 64}
    a.write(a.state_file, a.state)
    assert a.client.get(TARGET).status_code == 409


def test_result_from_different_decision_budget_is_rejected(target_api):
    a = target_api
    a.result['decisionBudget'] = {'maximumRequests': 64, 'requests': 64, 'cacheHits': 0, 'exhausted': True}
    a.seal('target_simulation', a.sim_dir / 'target_simulation.json', a.result)
    assert a.client.get(TARGET).status_code == 409


def test_graph_details_and_neighbors_use_local_projection(target_api):
    a = target_api
    node, edge = a.projection['nodes'][0], a.projection['edges'][0]
    for suffix, row in [(f"node/{node['uuid']}", node), (f"edge/{edge['uuid']}", edge)]:
        response = a.client.get(f'{GRAPH}/{suffix}')
        assert response.status_code == 200
        assert response.json['data'] == row
    response = a.client.get(f"{GRAPH}/neighbors/{node['uuid']}?depth=3")
    assert response.status_code == 200
    assert node in response.json['data']['nodes']
    assert a.client.get(f'{GRAPH}/node/missing').status_code == 404


@pytest.mark.parametrize('field,value', [('pipeline_id', 'pipe_other'), ('graph_id', 'target_graph_pipe_other'),
                                        ('handoff_dir', '/private/tmp/unrelated'), ('handoff_dir', 123),
                                        ('handoff_dir', ''), ('options', {})])
def test_graph_requires_matching_owner(target_api, field, value):
    a = target_api
    a.state[field] = value
    a.write(a.state_file, a.state)
    assert a.client.get(GRAPH).status_code == 409


@pytest.mark.parametrize('url', [
    '/api/simulation/sim_ui/target', '/api/simulation/sim_ui/target?pipeline_id=../pipe_ui',
    '/api/simulation/sim_ui/target?pipeline_id=pipe_x%2F..',
    '/api/simulation/sim_ui/target?pipeline_id=pipe_x%5C..',
    '/api/simulation/bad.sim/target?pipeline_id=pipe_ui', '/api/graph/data/target_graph_bad',
])
def test_invalid_ids_fail_before_artifact_access(target_api, url):
    assert target_api.client.get(url).status_code == 400


def test_simulation_requires_exact_owner(target_api):
    a = target_api
    a.state['simulation_id'] = 'sim_other'
    a.write(a.state_file, a.state)
    assert a.client.get(TARGET).status_code == 409


@pytest.mark.parametrize('name', ['forecast_case', 'target_graph', 'target_case', 'target_input', 'target_simulation'])
def test_byte_tampering_is_rejected_even_with_original_case_hash(target_api, name):
    a = target_api
    path = Path(a.manifest[name]['path'])
    data = json.loads(path.read_text())
    data['tampered'] = True
    a.write(path, data)
    url = GRAPH if name == 'target_graph' else TARGET
    assert a.client.get(url).status_code == 409


@pytest.mark.parametrize('change', ['caseHash', 'caseId', 'weight', 'input-owner', 'input-settings', 'input-structure', 'case-copy', 'projection'])
def test_sealed_but_mismatched_case_contract_is_rejected(target_api, change):
    a = target_api
    url = TARGET
    if change in {'caseHash', 'caseId', 'weight'}:
        a.result[{'weight': 'simulationWeight'}.get(change, change)] = 0.1 if change == 'weight' else 'wrong'
        a.seal('target_simulation', a.sim_dir / 'target_simulation.json', a.result)
    elif change.startswith('input-'):
        if change == 'input-owner': a.inputs['pipelineId'] = 'pipe_other'
        if change == 'input-settings': a.inputs['simulation'] = {'paths': 1, 'periods': 1, 'seed': 1}
        if change == 'input-structure': a.inputs['structure']['caseId'] = 'other'
        a.seal('target_input', a.sim_dir / 'target_input.json', a.inputs)
    elif change == 'case-copy':
        a.case['question'] += ' altered'
        a.seal('target_case', a.sim_dir / 'target_case.json', a.case)
    else:
        a.projection['nodes'][0]['name'] = 'Altered projection'
        a.seal('target_graph', a.handoff / 'target_graph.json', a.projection)
        url = GRAPH
    assert a.client.get(url).status_code == 409


@pytest.mark.parametrize('kind', ['file', 'directory', 'handoff', 'manifest-path'])
def test_known_artifacts_reject_symlink_or_manifest_redirection(target_api, kind):
    a = target_api
    if kind == 'file':
        source = a.sim_dir / 'target_simulation.json'
        dest = a.root / 'elsewhere.json'
        source.rename(dest)
        source.symlink_to(dest)
    elif kind == 'directory':
        dest = a.root / 'other-simulation'
        a.sim_dir.rename(dest)
        a.sim_dir.symlink_to(dest, target_is_directory=True)
    elif kind == 'handoff':
        dest = a.root / 'other-handoff'
        a.handoff.rename(dest)
        a.handoff.symlink_to(dest, target_is_directory=True)
    else:
        a.manifest['target_simulation']['path'] = str(a.root / 'elsewhere.json')
        a.write(a.handoff / 'manifest.json', a.manifest)
    assert a.client.get(TARGET).status_code == 409


@pytest.mark.parametrize('raw', ['{"pipeline_id":"pipe_ui","pipeline_id":"pipe_other"}', '{"bad":1e999}', '{"bad":NaN}'])
def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(target_api, raw):
    target_api.state_file.write_text(raw)
    assert target_api.client.get(TARGET).status_code == 409


def test_unsealed_or_missing_artifact_is_pending_and_target_endpoint_is_readonly(target_api):
    a = target_api
    del a.manifest['target_simulation']
    a.write(a.handoff / 'manifest.json', a.manifest)
    assert a.client.get(TARGET).status_code == 404
    assert a.client.post(TARGET).status_code == 405


@pytest.mark.parametrize('method,url,body', [
    ('get', '/api/simulation/sim_ui', None), ('get', '/api/simulation/sim_ui/run-status', None),
    ('get', '/api/simulation/sim_ui/trajectory', None), ('get', '/api/simulation/sim_ui/record', None),
    ('get', '/api/simulation/entities/target_graph_pipe_ui', None),
    ('post', '/api/simulation/start', {'simulation_id': 'sim_ui'}),
    ('post', '/api/simulation/prepare', {'simulation_id': 'sim_ui'}),
    ('post', '/api/simulation/create', {'simulation_engine': 'target-first-v1'}),
    ('post', '/api/graph/target_graph_pipe_ui/translations/zh', {}),
    ('delete', '/api/graph/delete/target_graph_pipe_ui', None),
])
def test_target_ids_never_enter_legacy_consumers(target_api, method, url, body):
    assert getattr(target_api.client, method)(url, json=body).status_code == 409


def test_implicit_project_graph_cannot_create_legacy_simulation(target_api, monkeypatch):
    monkeypatch.setattr(simulation.ProjectManager, 'get_project', lambda _: SimpleNamespace(graph_id='target_graph_pipe_ui'))
    assert target_api.client.post('/api/simulation/create', json={'project_id': 'proj_ui'}).status_code == 409


def test_ordinary_graph_still_uses_existing_builder(target_api, monkeypatch):
    monkeypatch.setattr(Config, 'ZEP_API_KEY', 'offline-placeholder')
    calls = []
    class Builder:
        def __init__(self, **kwargs): calls.append('constructed')
        def get_graph_data(self, graph_id, **kwargs):
            calls.append(graph_id)
            return {'nodes': [], 'edges': []}
    monkeypatch.setattr(graph, 'GraphBuilderService', Builder)
    response = target_api.client.get('/api/graph/data/legacy_graph')
    assert response.status_code == 200
    assert calls == ['constructed', 'legacy_graph']
