"""World admission through real APIs, manager, runner, service and pipeline stages.

Only transport/process boundaries are faked. Compiler, input seals, SQLite,
controller, completion reader and pipeline stage persistence are production code.
Run exclusively under main_offline_pytest.py via the worktree snapshot wrapper.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

pytestmark = pytest.mark.guarded_runner


def raw_model():
    from test_world_compiler import proposal
    raw = proposal()
    raw['limits'] = {'maxOutputTokens': 512, 'maxCostUsd': '5'}
    raw['policy'] = {
        'provider': 'openai', 'model': 'fixture-model-v1', 'baseUrl': 'https://fixture.invalid/v1',
        'timeoutSeconds': 17, 'maxInputTokens': 30000,
        'pricing': {
            'provider': 'openai', 'model': 'fixture-model-v1', 'baseUrl': 'https://fixture.invalid/v1',
            'inputUsdPerMillion': '2', 'outputUsdPerMillion': '9',
            'contextWindowTokens': 32768, 'maxOutputTokens': 2048, 'inputOverheadTokens': 256,
            'outputTokenParameter': 'max_completion_tokens', 'maxOutputIncludesReasoning': True,
            'source': {'reference': 'fixture://synthetic-tariff', 'asOf': '2026-10-16T00:00:00Z'},
        },
    }
    return raw


def hashes(directory):
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob('*') if p.is_file()}


@pytest.fixture
def boundary(monkeypatch, tmp_path):
    import httpx
    from openai import OpenAI
    from flask import Flask
    from app.api import simulation_bp, research_bp
    from app.api import simulation, research  # noqa: F401 -- register real routes
    from app.config import Config
    from app.services import pipeline_orchestrator as po
    from app.services.simulation_manager import SimulationManager
    from app.services.simulation_runner import SimulationRunner
    from app.services.world_simulation import service
    from app.services.world_simulation.policy import StrictHTTPPolicy, StrictHTTPModeler
    from test_world_compiler import REPORT, source_bundle

    root = tmp_path / 'simulations'
    root.mkdir()
    monkeypatch.setattr(Config, 'OASIS_SIMULATION_DATA_DIR', str(root))
    monkeypatch.setattr(Config, 'PIPELINE_DATA_DIR', str(tmp_path / 'pipelines'))
    monkeypatch.setattr(Config, 'RESEARCH_ENGINE', 'v3')
    monkeypatch.setattr(Config, 'LLM_PROVIDER', 'openai')
    monkeypatch.setattr(Config, 'resolve_endpoint', classmethod(lambda cls, provider, model=None: ('https://fixture.invalid/v1', 'fixture-model-v1')))
    monkeypatch.setattr(SimulationManager, 'SIMULATION_DATA_DIR', str(root))
    monkeypatch.setattr(SimulationRunner, 'RUN_STATE_DIR', str(root))
    monkeypatch.setattr(SimulationRunner, '_world_simulations', set())
    monkeypatch.setattr(SimulationRunner, '_run_states', {})
    monkeypatch.setattr(service, '_processes', {})
    sent, launches = [], []
    behavior = SimpleNamespace(mode='complete', on_launch=None, on_poll=None, model_candidate=None)

    def dispatch(request):
        body = json.loads(request.content)
        observation = json.loads(body['messages'][-1]['content'])
        sent.append(observation)
        if 'actorId' in observation:
            decision = {'actorId': observation['actorId'], 'observationId': observation['observationId'],
                        'intents': [], 'status': 'wait'}
        else:
            decision = deepcopy(behavior.model_candidate)
            assert decision is not None, 'Unexpected modeler call'
        return httpx.Response(200, json={
            'id': 'fixture', 'object': 'chat.completion', 'created': 0, 'model': 'fixture-model-v1',
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': json.dumps(decision)}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 40, 'total_tokens': 140}})

    def build_client(self, config):
        http = httpx.Client(transport=httpx.MockTransport(dispatch), follow_redirects=False, trust_env=False)
        return OpenAI(api_key='synthetic-test-key', base_url=self.base_url, http_client=http, max_retries=0)
    monkeypatch.setattr(StrictHTTPPolicy, '_build_client', build_client)
    monkeypatch.setattr(StrictHTTPModeler, '_build_client', build_client)

    class ChildProcess:
        def __init__(self, command, **kwargs):
            launches.append((command, kwargs))
            self.pid = 99999999
            self.returncode = None
            directory = Path(command[command.index('--simulation-dir') + 1])
            if behavior.on_launch:
                behavior.on_launch(directory)
            if behavior.mode == 'complete':
                self.returncode = service.run_child(directory,
                    expected_manifest_sha256=command[command.index('--manifest-sha256') + 1],
                    launch_id=command[command.index('--launch-id') + 1],
                    launch_lock_fd=int(command[command.index('--lock-fd') + 1]))
            elif behavior.mode == 'empty_exit':
                self.returncode = 0
        def poll(self):
            if behavior.on_poll:
                behavior.on_poll()
            return self.returncode
    monkeypatch.setattr(service, 'subprocess', SimpleNamespace(
        Popen=ChildProcess, DEVNULL=service.subprocess.DEVNULL, STDOUT=service.subprocess.STDOUT))
    # SDK platform metadata is a process boundary too; avoid ambient uname discovery.
    monkeypatch.setattr('platform.processor', lambda: 'fixture')

    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(research_bp, url_prefix='/api/research')
    manager = SimulationManager()
    sim = manager.create_simulation('project_fixture', 'graph_fixture', simulation_engine='world-v1')
    payload = {'simulation_id': sim.simulation_id, 'world_spec': raw_model(),
               'research_report': REPORT, 'research_generation_id': 'research_fixture',
               'research_engine': 'v3', 'actors': source_bundle()}
    def pipeline():
        pid = 'pipe_lifecycle'
        po.PipelineManager.ensure_dirs(pid)
        state = po.PipelineState(pipeline_id=pid, prompt='Synthetic lifecycle test', status='running',
            handoff_dir=po.PipelineManager.handoff_dir(pid),
            stages={k: po.StageState(name=k) for k in po.STAGE_BANDS},
            options={'simulation_engine': 'world-v1', 'world_spec': raw_model()})
        po.PipelineManager.save(state)
        return state
    yield SimpleNamespace(root=root, manager=manager, sim=sim, payload=payload, client=app.test_client(),
                          sent=sent, launches=launches, behavior=behavior, pipeline=pipeline,
                          po=po, service=service, runner=SimulationRunner, report=REPORT, actors=source_bundle())
    SimulationRunner._world_simulations.clear()


def prepare(b):
    response = b.client.post('/api/simulation/prepare', json=b.payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()['data']


def test_api_prepare_start_real_http_child_result_and_readonly_resume(boundary):
    b = boundary
    data = prepare(b)
    assert data['simulation_engine'] == 'world-v1'
    manifest = json.loads((b.root / b.sim.simulation_id / 'world_input_manifest.json').read_text())
    assert data['world_spec_sha256'] == manifest['specSha256']
    assert data['world_spec_sha256'] != manifest['specHash']
    response = b.client.post('/api/simulation/start', json={'simulation_id': b.sim.simulation_id})
    assert response.status_code == 200, response.get_json()
    assert response.json['data']['runner_status'] == 'completed'
    assert response.json['data']['twitter_completed'] is False
    assert response.json['data']['reddit_enabled'] is False
    assert len(b.launches) == 1 and len(b.sent) == 1
    command = b.launches[0][0]
    assert any(arg.endswith('run_world_simulation.py') for arg in command)
    directory = b.root / b.sim.simulation_id
    before = hashes(directory)
    view = b.client.get(f'/api/simulation/{b.sim.simulation_id}/world')
    assert view.status_code == 200, view.json
    assert view.json['data']['completed'] is True
    assert view.json['data']['view'] == 'public'
    again = b.client.post('/api/simulation/start', json={'simulation_id': b.sim.simulation_id})
    assert again.json['data']['runner_status'] == 'completed'
    assert len(b.launches) == 1 and len(b.sent) == 1
    assert hashes(directory) == before
    assert not (directory / 'simulation_config.json').exists()


@pytest.mark.parametrize('mode,expected', [('complete', 'completed'), ('empty_exit', 'failed')])
def test_list_matches_current_world_status_without_writing_preparation(boundary, mode, expected):
    b = boundary
    prepare(b)
    legacy = b.manager.create_simulation('project_legacy', 'graph_legacy')
    legacy_before = legacy.to_dict()
    b.behavior.mode = mode
    b.runner.start_simulation(b.sim.simulation_id)
    b.runner.get_run_state(b.sim.simulation_id)
    directory = b.root / b.sim.simulation_id
    assert json.loads((directory / 'state.json').read_text())['status'] == 'ready'
    before = hashes(b.root)
    single = b.client.get(f'/api/simulation/{b.sim.simulation_id}').json['data']
    assert single['status'] == expected
    response = b.client.get('/api/simulation/list')
    assert response.status_code == 200, response.json
    rows = {row['simulation_id']: row for row in response.json['data']}
    assert rows[b.sim.simulation_id] == single
    assert rows[legacy.simulation_id] == legacy_before
    filtered = b.client.get('/api/simulation/list?project_id=project_fixture')
    assert filtered.json['count'] == 1 and filtered.json['data'] == [single]
    assert hashes(b.root) == before


def test_project_list_excludes_corrupt_unselected_world_before_projection(boundary):
    b = boundary
    prepare(b)
    legacy = b.manager.create_simulation('project_legacy', 'graph_legacy')
    spec = b.root / b.sim.simulation_id / 'world_spec.json'
    spec.write_bytes(spec.read_bytes() + b' ')
    before = hashes(b.root)
    response = b.client.get('/api/simulation/list?project_id=project_legacy')
    assert response.status_code == 200, response.json
    assert response.json['data'] == [legacy.to_dict()]
    assert b.client.get('/api/simulation/list?project_id=project_fixture').status_code == 500
    assert b.client.get('/api/simulation/list').status_code == 500
    assert hashes(b.root) == before and not b.sent and not b.launches


def test_api_world_stale_cursor_and_views_are_readonly(boundary):
    b = boundary
    prepare(b)
    b.runner.start_simulation(b.sim.simulation_id)
    directory = b.root / b.sim.simulation_id
    before = hashes(directory)
    path = f'/api/simulation/{b.sim.simulation_id}/world'
    for view in ('public', 'analyst', 'actor'):
        response = b.client.get(path, query_string={'view': view, **({'actor_id': 'a'} if view == 'actor' else {})})
        assert response.status_code == 200, response.json
        assert response.json['data']['view'] == view
    stale = b.client.get(path, query_string={'revision': 'old_revision'})
    assert stale.status_code == 409 and stale.json['code'] == 'stale_revision'
    assert hashes(directory) == before


def test_api_missing_model_is_explicit_readiness_failure(boundary):
    b = boundary
    del b.payload['world_spec']
    response = b.client.post('/api/simulation/prepare', json=b.payload)
    assert response.status_code == 409, response.json
    assert b.launches == [] and b.sent == []
    assert not (b.root / b.sim.simulation_id / 'simulation_config.json').exists()


@pytest.mark.parametrize('engine', ['future-world', '', None])
def test_unknown_engine_rejected_at_public_and_runner_boundaries(boundary, engine):
    b = boundary
    response = b.client.post('/api/simulation/start', json={'simulation_id': b.sim.simulation_id, 'simulation_engine': engine})
    assert response.status_code == 400
    response = b.client.post('/api/research/run', json={'prompt': 'test', 'simulation_engine': engine})
    assert response.status_code == 400
    state_path = b.root / b.sim.simulation_id / 'state.json'
    state = json.loads(state_path.read_text()); state['simulation_engine'] = engine
    state_path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match='Unsupported simulation_engine'):
        b.runner.start_simulation(b.sim.simulation_id)
    assert b.launches == []


@pytest.mark.parametrize('field', ['world_generation_id', 'world_spec_sha256', 'world_input_manifest_sha256'])
def test_saved_input_pin_tamper_rejected_before_child(boundary, field):
    b = boundary
    prepare(b)
    path = b.root / b.sim.simulation_id / 'state.json'
    state = json.loads(path.read_text()); state[field] = 'tampered'; path.write_text(json.dumps(state))
    with pytest.raises(ValueError):
        b.runner.start_simulation(b.sim.simulation_id)
    assert b.launches == [] and b.sent == []


def test_spec_tamper_rejected_before_child_and_get_cannot_repair(boundary):
    b = boundary
    prepare(b)
    directory = b.root / b.sim.simulation_id
    path = directory / 'world_spec.json'
    path.write_text(path.read_text() + ' ')
    before = hashes(directory)
    with pytest.raises(ValueError):
        b.runner.start_simulation(b.sim.simulation_id)
    assert b.client.get(f'/api/simulation/{b.sim.simulation_id}/world').status_code == 409
    assert hashes(directory) == before and not b.launches


def test_zero_exit_without_committed_horizon_is_failed(boundary):
    b = boundary
    prepare(b)
    b.behavior.mode = 'empty_exit'
    b.runner.start_simulation(b.sim.simulation_id)
    state = b.runner.get_run_state(b.sim.simulation_id)
    assert state.runner_status.value == 'failed'
    assert state.error == 'child_exited_before_committed_horizon'
    assert not state.twitter_completed and not state.reddit_completed
    with pytest.raises(ValueError):
        b.service.WorldSimulationService.require_complete(b.sim.simulation_id)


def test_cancel_token_stops_real_controller_without_dispatch(boundary):
    b = boundary
    prepare(b)
    b.behavior.mode = 'waiting'
    b.runner.start_simulation(b.sim.simulation_id)
    response = b.client.post('/api/simulation/stop', json={'simulation_id': b.sim.simulation_id})
    assert response.status_code == 200, response.json
    assert response.json['data']['runner_status'] == 'stopping'
    assert b.service.run_child(b.root / b.sim.simulation_id) == 1
    state = b.runner.get_run_state(b.sim.simulation_id)
    assert state.runner_status.value == 'stopped' and state.current_round == 0
    assert not b.sent


def test_world_interviews_and_force_restart_are_explicitly_unsupported(boundary):
    b = boundary
    prepare(b)
    before = hashes(b.root / b.sim.simulation_id)
    with pytest.raises(ValueError, match='unsupported_capability'):
        b.runner.interview_agent(b.sim.simulation_id, 1, 'Question')
    response = b.client.post('/api/simulation/interview', json={'simulation_id': b.sim.simulation_id, 'agent_id': 1, 'prompt': 'Question'})
    assert response.status_code == 400 and 'unsupported_capability' in response.json['error']
    response = b.client.post('/api/simulation/start', json={'simulation_id': b.sim.simulation_id, 'force': True})
    assert response.status_code == 409
    assert hashes(b.root / b.sim.simulation_id) == before


def run_pipeline_world(b, state):
    return b.po.PipelineOrchestrator()._run_world_stages(state, SimpleNamespace(project_id='project_fixture'),
            'graph_fixture', b.actors, b.report)


def test_pipeline_prepare_run_complete_and_resume_without_world_writes(boundary):
    b = boundary
    state = b.pipeline()
    sim = run_pipeline_world(b, state)
    assert state.stages['prepare'].status == state.stages['run'].status == 'completed'
    assert state.simulation_id == sim.simulation_id
    assert state.options['world_research_generation_id'].startswith('research_')
    directory = b.root / sim.simulation_id
    before = hashes(directory)
    b.po.PipelineOrchestrator()._validate_reuse(state, 'prepare')
    assert b.po.PipelineOrchestrator()._validate_reuse(state, 'run')
    restored = b.po.PipelineState.from_dict(b.po.PipelineManager.load(state.pipeline_id))
    run_pipeline_world(b, restored)
    assert len(b.launches) == 1 and len(b.sent) == 1
    assert hashes(directory) == before
    assert {'world_spec', 'world_input_manifest', 'world_result', 'world_result_manifest'} <= set(restored.artifacts)
    assert 'personas' not in restored.artifacts and 'run_summary' not in restored.artifacts
    health = b.po.PipelineOrchestrator()._assess_run_health(sim.simulation_id)
    assert health[0] == 'ok' and health[2]['simulation_engine'] == 'world-v1'


def test_pipeline_saved_candidate_runs_same_compiler(boundary):
    b = boundary
    state = b.pipeline()
    raw = state.options.pop('world_spec')
    (Path(state.handoff_dir) / 'world_modeling_candidate.json').write_text(json.dumps({'world_spec': raw}))
    sim = run_pipeline_world(b, state)
    assert b.service.WorldSimulationService.require_complete(sim.simulation_id)['completed']


def test_pipeline_missing_model_no_legacy_fallback(boundary):
    b = boundary
    state = b.pipeline(); state.options.pop('world_spec')
    with pytest.raises(ValueError, match='world_spec'):
        run_pipeline_world(b, state)
    assert not b.launches and state.stages['prepare'].status != 'completed'


def test_pipeline_tampered_result_cannot_rebuild_or_complete(boundary):
    b = boundary
    state = b.pipeline(); sim = run_pipeline_world(b, state)
    path = b.root / sim.simulation_id / 'world_result.json'; path.write_text(path.read_text() + ' ')
    before = hashes(path.parent)
    with pytest.raises(ValueError):
        run_pipeline_world(b, state)
    assert len(b.launches) == 1 and hashes(path.parent) == before


def test_pipeline_failed_zero_child_never_completes_run(boundary):
    b = boundary
    state = b.pipeline(); b.behavior.mode = 'empty_exit'
    with pytest.raises(RuntimeError, match='did not complete'):
        run_pipeline_world(b, state)
    assert state.stages['prepare'].status == 'completed'
    assert state.stages['run'].status != 'completed'


def test_pipeline_cancel_routes_to_real_service(boundary):
    b = boundary
    state = b.pipeline(); event = threading.Event()
    b.po.PipelineOrchestrator._cancel_events[state.pipeline_id] = event
    b.behavior.mode = 'waiting'
    b.behavior.on_launch = lambda directory: event.set()
    try:
        with pytest.raises(b.po.PipelineCancelled):
            run_pipeline_world(b, state)
        directory = b.root / state.simulation_id
        assert (directory / 'world_cancel.json').exists()
        assert b.service.run_child(directory) == 1
        assert not b.sent and state.stages['run'].status != 'completed'
    finally:
        b.po.PipelineOrchestrator._cancel_events.pop(state.pipeline_id, None)


def test_fork_new_generation_and_seed_preserve_parent(boundary):
    b = boundary
    prepare(b); b.runner.start_simulation(b.sim.simulation_id)
    before = hashes(b.root / b.sim.simulation_id)
    child = b.manager.fork_world_simulation(b.sim.simulation_id, seed=17)
    assert child.simulation_engine == 'world-v1' and child.world_generation_id != b.manager.get_simulation(b.sim.simulation_id).world_generation_id
    directory = b.root / child.simulation_id
    assert not (directory / 'world.sqlite3').exists()
    assert json.loads((directory / 'world_spec.json').read_text())['seed'] == 17
    b.runner.start_simulation(child.simulation_id)
    assert hashes(b.root / b.sim.simulation_id) == before


class DeferredThread:
    """OS scheduling boundary; never substitutes for a pipeline stage."""
    def __init__(self, *, target, args, **kwargs):
        self.target, self.args = target, args
    def start(self):
        pass
    def is_alive(self):
        return False


def test_public_pipeline_resume_retains_completed_world_then_reuses(boundary, monkeypatch):
    b = boundary
    state = b.pipeline(); sim = run_pipeline_world(b, state)
    state.status = 'failed'; state.current_stage = 'report'
    b.po.PipelineManager.save(state)
    before = hashes(b.root / sim.simulation_id)
    with monkeypatch.context() as patch:
        patch.setattr(b.po.threading, 'Thread', DeferredThread)
        resumed = b.po.PipelineOrchestrator.resume(state.pipeline_id)
    assert resumed.simulation_id == sim.simulation_id
    assert resumed.stages['prepare'].status == resumed.stages['run'].status == 'completed'
    run_pipeline_world(b, resumed)
    assert len(b.launches) == 1 and hashes(b.root / sim.simulation_id) == before


def test_public_pipeline_fork_uses_world_baseline_and_preserves_parent(boundary, monkeypatch):
    b = boundary
    state = b.pipeline(); sim = run_pipeline_world(b, state)
    state.project_id = 'project_fixture'; state.graph_id = 'graph_fixture'
    b.po.PipelineManager.save(state)
    before = hashes(b.root / sim.simulation_id)
    with monkeypatch.context() as patch:
        patch.setattr(b.po.threading, 'Thread', DeferredThread)
        fork = b.po.PipelineOrchestrator.fork(state.pipeline_id, {'label': 'seed test', 'seed': 83})
    assert fork.options['simulation_engine'] == 'world-v1'
    assert fork.simulation_id != sim.simulation_id
    child = run_pipeline_world(b, fork)
    spec = json.loads((b.root / child.simulation_id / 'world_spec.json').read_text())
    assert spec['seed'] == 83
    assert hashes(b.root / sim.simulation_id) == before


def test_stage_artifact_manifest_is_required_even_when_legacy_validation_disabled(boundary, monkeypatch):
    from app.config import Config
    b = boundary
    state = b.pipeline(); run_pipeline_world(b, state)
    monkeypatch.setattr(Config, 'PIPELINE_VALIDATE_ARTIFACTS', False)
    b.po.PipelineManager.write_artifact_manifest(state.pipeline_id, {})
    assert not b.po.PipelineOrchestrator()._reuse_ok(state, 'run')
    with pytest.raises(ValueError, match='artifacts changed'):
        run_pipeline_world(b, state)
    assert len(b.launches) == 1


def test_pipeline_source_change_cannot_reuse_world(boundary):
    b = boundary
    state = b.pipeline(); run_pipeline_world(b, state)
    b.report += ' Updated source.'
    with pytest.raises(ValueError, match='generation changed'):
        run_pipeline_world(b, state)
    assert len(b.launches) == 1


def test_pipeline_cannot_drop_world_pin_and_enter_legacy_path(boundary):
    b = boundary
    state = b.pipeline(); run_pipeline_world(b, state)
    del state.options['simulation_engine']
    with pytest.raises(ValueError, match='engine pins differ'):
        b.po.PipelineOrchestrator._simulation_engine(state)


def test_simulation_status_projection_reports_committed_world_without_writes(boundary):
    b = boundary
    prepare(b); b.runner.start_simulation(b.sim.simulation_id)
    before = hashes(b.root / b.sim.simulation_id)
    state = b.manager.get_simulation(b.sim.simulation_id)
    assert state.status.value == 'completed' and state.current_round == 1
    assert hashes(b.root / b.sim.simulation_id) == before


def test_model_source_float_estimates_do_not_break_derivative_identity(boundary):
    b = boundary
    state = b.pipeline(); b.actors['estimate'] = 0.75
    sim = run_pipeline_world(b, state)
    assert b.service.WorldSimulationService.require_complete(sim.simulation_id)['completed']


def test_pipeline_rejects_same_bad_artifact_pin_across_repeated_resume(boundary, monkeypatch):
    b = boundary
    state = b.pipeline(); run_pipeline_world(b, state)
    manifest = b.po.PipelineManager.load_artifact_manifest(state.pipeline_id)
    manifest['world_spec']['sha256'] = 'bad_hash'
    b.po.PipelineManager.write_artifact_manifest(state.pipeline_id, manifest)
    for attempt in range(2):
        with pytest.raises(ValueError, match='artifacts changed'):
            run_pipeline_world(b, state)
        state.status = 'failed'; state.stages['prepare'].status = 'failed'
        b.po.PipelineManager.save(state)
        with monkeypatch.context() as patch:
            patch.setattr(b.po.threading, 'Thread', DeferredThread)
            state = b.po.PipelineOrchestrator.resume(state.pipeline_id)
        assert b.po.PipelineManager.load_artifact_manifest(state.pipeline_id)['world_spec']['sha256'] == 'bad_hash'
    assert len(b.launches) == 1


def test_cancel_arriving_during_status_read_still_signals_child(boundary):
    b = boundary
    state = b.pipeline(); event = threading.Event()
    b.po.PipelineOrchestrator._cancel_events[state.pipeline_id] = event
    b.behavior.mode = 'waiting'
    polls = []
    def on_poll():
        polls.append(True)
        if len(polls) == 2:
            event.set()
    b.behavior.on_poll = on_poll
    try:
        with pytest.raises(b.po.PipelineCancelled):
            run_pipeline_world(b, state)
        assert len(polls) >= 2
        assert (b.root / state.simulation_id / 'world_cancel.json').exists()
        assert b.service.run_child(b.root / state.simulation_id) == 1
        assert not b.sent
    finally:
        b.po.PipelineOrchestrator._cancel_events.pop(state.pipeline_id, None)


def test_missing_world_engine_pin_cannot_enter_legacy_preparation(boundary):
    b = boundary
    prepare(b)
    directory = b.root / b.sim.simulation_id
    path = directory / 'state.json'; state = json.loads(path.read_text())
    del state['simulation_engine']; path.write_text(json.dumps(state))
    before = hashes(directory)
    response = b.client.post('/api/simulation/prepare', json={'simulation_id': b.sim.simulation_id, 'force_regenerate': True})
    assert response.status_code == 400 and 'engine pin' in response.json['error']
    with pytest.raises(ValueError, match='engine pin'):
        b.manager.prepare_simulation(b.sim.simulation_id, 'test', b.report)
    assert hashes(directory) == before and not b.launches


def test_seed_child_checkpoint_survives_report_failure_window(boundary):
    b = boundary
    state = b.pipeline(); run_pipeline_world(b, state)
    worker = b.po.PipelineOrchestrator()
    child = worker._run_world_seed(state, seed=71)
    assert len(b.launches) == 2 and len(b.sent) == 2
    # The report has not succeeded. A crash here must retain the admitted child.
    restored = b.po.PipelineState.from_dict(b.po.PipelineManager.load(state.pipeline_id))
    assert restored.options['world_seed_runs']['71']['report_id'] is None
    before = hashes(b.root / child.simulation_id)
    again = worker._run_world_seed(restored, seed=71)
    assert again.simulation_id == child.simulation_id
    assert len(b.launches) == 2 and len(b.sent) == 2
    assert hashes(b.root / child.simulation_id) == before


def test_orphan_pipeline_cancel_targets_persisted_seed_child(boundary):
    b = boundary
    state = b.pipeline(); run_pipeline_world(b, state)
    b.behavior.mode = 'waiting'
    event = threading.Event()
    b.po.PipelineOrchestrator._cancel_events[state.pipeline_id] = event
    b.behavior.on_launch = lambda directory: event.set()
    try:
        with pytest.raises(b.po.PipelineCancelled):
            b.po.PipelineOrchestrator()._run_world_seed(state, seed=47)
        row = state.options['world_seed_runs']['47']
        cancel_file = b.root / row['simulation_id'] / 'world_cancel.json'
        cancel_file.unlink()
        b.po.PipelineOrchestrator._cancel_events.pop(state.pipeline_id, None)
        b.po.PipelineOrchestrator._threads.pop(state.pipeline_id, None)
        result = b.po.PipelineOrchestrator.cancel(state.pipeline_id)
        assert result['ok'] and cancel_file.exists()
    finally:
        b.po.PipelineOrchestrator._cancel_events.pop(state.pipeline_id, None)


def modeling_policy():
    raw = raw_model()
    return {'policy': raw['policy'], 'limits': {
        'maxTokens': 250000, 'maxCostUsd': '5', 'maxOutputTokens': 1200, 'maxIntentsPerPhase': 3},
        'forecastEffect': 'no_update'}


def test_api_automatic_modeler_compiles_seals_and_debits_actor_budget(boundary):
    b = boundary
    b.payload.pop('world_spec')
    b.payload['world_policy_spec'] = modeling_policy()
    b.payload['ontology'] = {'entity_types': []}
    b.payload['simulation_requirement'] = 'Only grounded waiting behavior'
    b.behavior.model_candidate = raw_model()
    data = prepare(b)
    assert len(b.sent) == 1 and 'researchGenerationId' in b.sent[0]
    spec = json.loads((b.root / b.sim.simulation_id / 'world_spec.json').read_text())
    preparation = spec['sourceBindings']['modelPreparation']
    assert preparation['used']['tokens'] == 140
    assert spec['limits']['maxTokens'] == 250000 - 140
    assert spec['forecastEffect'] == 'no_update'
    assert b.sent[0]['ontology'] == b.payload['ontology']
    assert b.sent[0]['requirement'] == b.payload['simulation_requirement']
    result = b.runner.start_simulation(data['simulation_id'])
    assert result.runner_status.value == 'completed' and len(b.sent) == 2


def test_pipeline_automatic_modeler_receives_pinned_policy_and_ontology(boundary):
    b = boundary
    state = b.pipeline(); state.options.pop('world_spec')
    state.options['world_policy_spec'] = modeling_policy()
    state.options['safety_policy_v1'] = {'simulation_forecast_effect': 'no_update'}
    b.behavior.model_candidate = raw_model()
    sim = b.po.PipelineOrchestrator()._run_world_stages(state,
        SimpleNamespace(project_id='project_fixture', ontology={'entity_types': []}),
        'graph_fixture', b.actors, b.report)
    result = b.service.WorldSimulationService.require_complete(sim.simulation_id)
    assert result['completed'] and result['forecastEffect'] == 'no_update'
    assert b.sent[0]['requirement'] == state.prompt
    assert b.sent[0]['ontology'] == {'entity_types': []}
    assert len(b.sent) == 2


def test_world_api_reads_exactly_one_result_revision(boundary, monkeypatch):
    from app.services.world_simulation import results
    b = boundary
    prepare(b); b.runner.start_simulation(b.sim.simulation_id)
    reads = []
    original = results.read_result
    def observe(*args, **kwargs):
        value = original(*args, **kwargs)
        reads.append(value['revision'])
        return value
    monkeypatch.setattr(results, 'read_result', observe)
    response = b.client.get(f'/api/simulation/{b.sim.simulation_id}/world')
    assert response.status_code == 200
    assert reads == [response.json['data']['revision']]


@pytest.mark.parametrize('tamper', ['world_generation_id', 'world_input_manifest_sha256', 'simulation_id'])
def test_completed_seed_reuse_validates_saved_generation_and_manifest(boundary, tamper):
    b = boundary
    state = b.pipeline(); run_pipeline_world(b, state)
    spec = json.loads((b.root / state.simulation_id / 'world_spec.json').read_text())
    seed = spec['seed'] + 2 * 7919
    worker = b.po.PipelineOrchestrator()
    worker._run_world_seed(state, seed=seed)
    row = state.options['world_seed_runs'][str(seed)]
    row.update(status='completed', report_id='report_fixture')
    state.options['safety_policy_v1'] = {'n_forecast_seeds': 2}
    row[tamper] = state.simulation_id if tamper == 'simulation_id' else 'tampered'
    b.po.PipelineManager.save(state)
    restored = b.po.PipelineState.from_dict(b.po.PipelineManager.load(state.pipeline_id))
    before = hashes(b.root)
    with pytest.raises(ValueError, match='Saved seed generation changed'):
        worker._maybe_run_seed_ensemble(restored, SimpleNamespace(project_id='project_fixture'),
            'graph_fixture', b.actors, {}, b.report)
    assert len(b.launches) == 2 and hashes(b.root) == before


# These fixtures call the real legacy producer and promote its research seal.
from test_world_compiler import producer, sealed_bundle  # noqa: E402,F401 -- pytest fixture discovery


def legacy_pipeline_case(boundary, sealed_bundle):  # noqa: F811 -- intentional fixture-name parameter
    from test_world_compiler import sealed_proposal
    b = boundary
    state = b.pipeline()
    state.handoff_dir = sealed_bundle['handoff_dir']
    state.options['actor_intelligence_policy_v1'] = {'required': True}
    raw = sealed_proposal(sealed_bundle)
    transport = raw_model()
    raw.update(policy=transport['policy'], limits=transport['limits'])
    state.options['world_spec'] = raw
    b.report, b.actors = sealed_bundle['report'], sealed_bundle['actors']
    return state


def test_pipeline_sealed_legacy_list_sources_complete_and_readonly_reuse(boundary, sealed_bundle):  # noqa: F811
    from app.services.official_data import capture_research_generation
    b = boundary
    state = legacy_pipeline_case(b, sealed_bundle)
    assert isinstance(sealed_bundle['sources'], list)
    handoff = Path(state.handoff_dir)
    source_before = {name: (handoff / name).read_bytes() for name in
                     ('actors.json', 'sources.json', 'actor_dossier.md', 'research_report.md', 'research_contract_manifest.json')}
    consumed = capture_research_generation(state.handoff_dir, report=b.report, sources=sealed_bundle['sources'])
    worker = b.po.PipelineOrchestrator()
    sim = worker._run_world_stages(state, SimpleNamespace(project_id='project_fixture'),
        'graph_fixture', b.actors, b.report, consumed_generation=consumed)
    assert state.stages['prepare'].status == state.stages['run'].status == 'completed'
    spec = json.loads((b.root / sim.simulation_id / 'world_spec.json').read_text())
    assert spec['sourceBindings']['researchEngine'] == 'legacy'
    assert spec['sourceBindings']['actorEvidenceGrade'] == 'sealed-legacy'
    assert spec['sourceBindings']['legacyContractSha256']
    assert spec['actors'][0]['evidenceGrade'] == 'sealed-legacy'
    assert len(b.launches) == len(b.sent) == 1
    before = hashes(b.root / sim.simulation_id)
    restored = b.po.PipelineState.from_dict(b.po.PipelineManager.load(state.pipeline_id))
    worker._run_world_stages(restored, SimpleNamespace(project_id='project_fixture'),
        'graph_fixture', b.actors, b.report, consumed_generation=consumed)
    assert len(b.launches) == len(b.sent) == 1
    assert hashes(b.root / sim.simulation_id) == before
    assert source_before == {name: (handoff / name).read_bytes() for name in source_before}


@pytest.mark.parametrize('name', ['sources.json', 'actor_dossier.md'])
def test_pipeline_legacy_rejects_changed_consumed_source_bytes(boundary, sealed_bundle, name):  # noqa: F811
    from app.services.official_data import capture_research_generation
    b = boundary
    state = legacy_pipeline_case(b, sealed_bundle)
    consumed = capture_research_generation(state.handoff_dir, report=b.report, sources=sealed_bundle['sources'])
    path = Path(state.handoff_dir) / name
    # Whitespace preserves JSON semantics but changes the captured byte generation.
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError, match='Consumed legacy research artifact changed'):
        b.po.PipelineOrchestrator()._run_world_stages(state, SimpleNamespace(project_id='project_fixture'),
            'graph_fixture', b.actors, b.report, consumed_generation=consumed)
    assert not b.launches and not b.sent


@pytest.mark.parametrize('corrupt', [False, True])
def test_pipeline_partial_prior_export_recovery_after_committed_horizon(boundary, corrupt):
    from app.services.world_simulation.artifacts import load_inputs
    from app.services.world_simulation.controller import run_round
    from app.services.world_simulation.policy import StrictHTTPPolicy
    from app.services.world_simulation.results import export_result
    from app.services.world_simulation.store import WorldStore
    b = boundary
    state = b.pipeline()
    state.options['world_spec']['periods'].append({
        'start': '2030-01-02T00:00:00Z', 'end': '2030-01-03T00:00:00Z'})
    b.behavior.mode = 'empty_exit'
    with pytest.raises(RuntimeError, match='did not complete'):
        run_pipeline_world(b, state)
    assert state.stages['prepare'].status == 'completed'
    directory = b.root / state.simulation_id
    spec, _ = load_inputs(directory)
    policy = StrictHTTPPolicy(spec)
    with WorldStore(directory / 'world.sqlite3', spec) as store:
        fence = store.acquire_writer('crash-fixture')
        try:
            run_round(store, policy, fence)
            export_result(directory)
            run_round(store, policy, fence)
        finally:
            store.release_writer(fence)
            policy.close()
    # This is the actual crash window: final round committed, prior export intact.
    worker = b.po.PipelineOrchestrator()
    worker._register_partial_artifacts(state, 'run')
    assert 'world_result_partial' in state.artifacts
    assert 'world_result_manifest_partial' in state.artifacts
    assert 'world_result' not in state.artifacts
    assert 'world_result' not in b.po.PipelineManager.load_artifact_manifest(state.pipeline_id)
    assert len(b.launches) == 1 and len(b.sent) == 2
    b.po.PipelineManager.save(state)
    restored = b.po.PipelineState.from_dict(b.po.PipelineManager.load(state.pipeline_id))
    sqlite_before = (directory / 'world.sqlite3').read_bytes()
    if corrupt:
        path = directory / 'world_result.json'; path.write_bytes(path.read_bytes() + b' ')
        before = hashes(directory)
        with pytest.raises(ValueError):
            run_pipeline_world(b, restored)
        assert restored.stages['run'].status != 'completed'
        # SQLite mode=ro may create empty WAL/shared-memory indexing sidecars.
        # Every authoritative byte and the rejected result must remain intact.
        after = hashes(directory)
        sidecars = {'world.sqlite3-shm', 'world.sqlite3-wal'}
        assert {k: v for k, v in after.items() if k not in sidecars} == {
            k: v for k, v in before.items() if k not in sidecars}
        if (directory / 'world.sqlite3-wal').exists():
            assert (directory / 'world.sqlite3-wal').stat().st_size == 0
    else:
        run_pipeline_world(b, restored)
        assert restored.stages['run'].status == 'completed'
        result = b.service.WorldSimulationService.require_complete(state.simulation_id)
        assert result['committedRound'] == 2 and result['completed']
    assert (directory / 'world.sqlite3').read_bytes() == sqlite_before
    assert len(b.launches) == 1 and len(b.sent) == 2


@pytest.mark.parametrize('mutation', ['changed_source', 'symlink', 'oversized'])
def test_legacy_pipeline_source_reader_preserves_seal_and_bounds(boundary, sealed_bundle, mutation):  # noqa: F811
    b = boundary
    state = legacy_pipeline_case(b, sealed_bundle)
    path = Path(state.handoff_dir) / 'sources.json'
    if mutation == 'changed_source':
        sources = json.loads(path.read_text()); sources[0]['excerpt'] += ' Not in the sealed source.'
        path.write_text(json.dumps(sources))
        expected = ValueError
    elif mutation == 'symlink':
        actual = path.with_name('source-original.json'); path.rename(actual)
        path.symlink_to(actual.name)
        expected = OSError
    else:
        path.write_bytes(b' ' * (8 * 1024 * 1024 + 1))
        expected = ValueError
    with pytest.raises(expected):
        run_pipeline_world(b, state)
    assert not b.launches and not b.sent
    assert state.stages['prepare'].status != 'completed'
