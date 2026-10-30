"""Production admission, lifecycle and consumer checks for target-first authority."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from app.services import target_pipeline as tp


@pytest.mark.parametrize('authority, options', [
    ('unknown', None), ('legacy', {}), ('target-first-v1', {'paths': True}),
    ('target-first-v1', {'paths': 0}), ('target-first-v1', {'periods': 121}),
    ('target-first-v1', {'seed': -1}), ('target-first-v1', {'weight': 0.5}),
    ('target-first-v1', '32'),
])
def test_admission_rejects_bad_options(authority, options):
    with pytest.raises(tp.TargetPipelineError):
        tp.normalize_target_options(authority, options)


def test_default_is_compatible_and_explicit_target_is_bounded():
    assert tp.normalize_target_options() == {}
    assert tp.normalize_target_options('target-first-v1')['target_simulation'] == {
        'paths': 32, 'periods': 12, 'seed': 0}


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    from app.services import pipeline_orchestrator as po
    from app.config import Config
    monkeypatch.setattr(Config, 'PIPELINE_DATA_DIR', str(tmp_path / 'pipelines'))
    monkeypatch.setattr(Config, 'OASIS_SIMULATION_DATA_DIR', str(tmp_path / 'simulations'))
    monkeypatch.setattr(Config, 'DEFAULT_SIMULATION_ENGINE', 'oasis-legacy')
    monkeypatch.setattr(Config, 'RESEARCH_ENGINE', 'v3')
    monkeypatch.setattr(po.PipelineOrchestrator, '_threads', {})
    monkeypatch.setattr(po.PipelineOrchestrator, '_cancel_events', {})
    launched = []
    class ParkedThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
        def start(self):
            launched.append(self.kwargs)
        def is_alive(self):
            return False
    tasks = SimpleNamespace(create_task=lambda **kwargs: 'task_target',
        update_task=lambda *args, **kwargs: None, complete_task=lambda *args, **kwargs: None,
        fail_task=lambda *args, **kwargs: None)
    monkeypatch.setattr(po, 'TaskManager', lambda: tasks)
    monkeypatch.setattr(po, 'threading', SimpleNamespace(Thread=ParkedThread,
        Event=threading.Event, Lock=threading.Lock))
    return SimpleNamespace(po=po, root=tmp_path, launched=launched, config=Config)


def test_authority_pinned_before_execution_and_survives_reload(runtime):
    po = runtime.po
    state = po.PipelineOrchestrator.start('What is 2027 spending?',
        forecast_authority='target-first-v1', target_simulation={'paths': 2, 'seed': 17})
    saved = po.PipelineState.from_dict(po.PipelineManager.load(state.pipeline_id))
    assert tp.is_target(saved)
    assert saved.options['target_simulation'] == {'paths': 2, 'periods': 12, 'seed': 17}
    assert po.PipelineOrchestrator._simulation_engine(saved) == 'target-first-v1'
    saved.options['simulation_engine'] = 'oasis-legacy'
    with pytest.raises(ValueError, match='differ'):
        po.PipelineOrchestrator._simulation_engine(saved)


@pytest.mark.parametrize('extra', [
    {'world_spec': {}}, {'simulation_engine': 'world-v1'},
    {'backtest': {'as_of': '2020-01-01'}},
])
def test_incompatible_modes_rejected_before_state_creation(runtime, extra):
    with pytest.raises(tp.TargetPipelineError):
        runtime.po.PipelineOrchestrator.start('Target', forecast_authority='target-first-v1', **extra)
    assert not (runtime.root / 'pipelines').exists()
    assert not runtime.launched


def test_http_request_selects_target_preflight_and_reports_bad_options(runtime, monkeypatch):
    from flask import Flask
    from app.api import research
    seen = []
    monkeypatch.setattr(research, 'preflight_pipeline', lambda **kw: seen.append(kw) or [])
    app = Flask(__name__)
    app.register_blueprint(research.research_bp, url_prefix='/api/research')
    client = app.test_client()
    response = client.post('/api/research/run', json={'prompt': 'Spending?',
        'forecast_authority': 'target-first-v1', 'target_simulation': {'paths': 2}})
    assert response.status_code == 200, response.json
    assert seen[0]['mode'] == 'research_only'
    state = runtime.po.PipelineManager.load(response.json['data']['pipeline_id'])
    assert state['options']['forecast_authority'] == 'target-first-v1'
    response = client.post('/api/research/run', json={'prompt': 'Spending?',
        'forecast_authority': 'target-first-v1', 'target_simulation': {'paths': True}})
    assert response.status_code == 400


def test_missing_completed_case_receipt_does_not_silently_regenerate(runtime):
    po = runtime.po
    state = po.PipelineOrchestrator.start('Spending?', forecast_authority='target-first-v1')
    state.stages['research'].status = 'completed'
    assert not tp.validate_stage(state, 'research')
    with pytest.raises(tp.TargetPipelineError, match='changed'):
        tp._already_complete(state, 'research')


@pytest.fixture
def case():
    return json.loads((Path(__file__).parent / 'fixtures' / 'target_case.json').read_text())


@pytest.fixture
def execution(runtime, case, monkeypatch):
    po = runtime.po
    from app.services.official_data import bridge_module
    fc = bridge_module('forecast_case')
    tr = bridge_module('target_research')
    monkeypatch.setattr(po.ProjectManager, 'PROJECTS_DIR', str(runtime.root / 'projects'))
    monkeypatch.setattr(po.ReportManager, 'REPORTS_DIR', str(runtime.root / 'reports'))
    monkeypatch.setattr(po.PipelineOrchestrator, '_write_run_manifest', lambda *a, **kw: None)
    monkeypatch.setattr(po.PipelineOrchestrator, '_init_telemetry_flush', lambda *a, **kw: None)
    monkeypatch.setattr(po.PipelineOrchestrator, '_flush_run_telemetry', lambda *a, **kw: None)
    monkeypatch.setattr(po.PipelineOrchestrator, '_start_heartbeat', lambda *a, **kw: threading.Event())
    monkeypatch.setattr(po, '_register_outage_breaker', lambda *a: None)
    calls = []
    class Methods:
        def chat_json(self, **kwargs):
            return {"scenario_distribution": {"below": 0.45, "above": 0.55}, "binaries": [],
                    "rationale": "Controlled independent method fixture", "cruxes": ["Next source release"]}
    monkeypatch.setattr(tp, "_method_gateway", Methods)
    def research(prompt, folder, **kwargs):
        calls.append(kwargs)
        assert kwargs['forecast_authority'] == 'target-first-v1'
        assert kwargs['research_engine'] == 'v3'
        assert kwargs['dual_track'] is False
        root = Path(folder)
        fc.write_case(root / 'forecast_case.json', case)
        (root / 'research_report.md').write_text(tr.render_case_research(case))
        return {'meta': {}, 'actors': {}, 'sources': case['sources']}
    monkeypatch.setattr(po.DeerFlowResearchRunner, 'run', research)
    runtime.calls = calls
    runtime.case = case
    return runtime


def _execute(execution, mode='full'):
    po = execution.po
    state = po.PipelineOrchestrator.start(execution.case['question'], mode=mode,
        forecast_authority='target-first-v1', target_simulation={'paths': 3, 'periods': 3, 'seed': 11})
    po.PipelineOrchestrator._run(state)
    return state


def test_actual_pipeline_runs_case_to_published_report_without_graph_or_probability_model(execution):
    po = execution.po
    state = _execute(execution)
    assert state.status == 'completed', state.error
    assert all(stage.status == 'completed' for stage in state.stages.values())
    assert po.ReportManager.publication_status(state.report_id)['publishable']
    forecast = json.loads((Path(po.ReportManager._get_report_folder(state.report_id)) / 'forecast.json').read_text())
    assert [s['probability'] for s in forecast['scenarios']] == [0.4, 0.6]
    assert len(execution.calls) == 1
    assert all(tp.validate_stage(state, stage) for stage in state.stages)
    result = json.loads(Path(state.artifacts['target_simulation']).read_text())
    assert result['simulationWeight'] == 0
    assert len(result['paths']) == 3
    assert 'target_graph_' in state.graph_id


def test_completed_case_and_paths_are_reused_on_report_retry(execution):
    state = _execute(execution)
    assert state.status == 'completed', state.error
    original = Path(state.artifacts['target_simulation']).read_bytes()
    state.status = 'failed'
    state.stages['report'].status = 'pending'
    execution.po.PipelineOrchestrator._run(state)
    assert state.status == 'completed', state.error
    assert Path(state.artifacts['target_simulation']).read_bytes() == original
    assert len(execution.calls) == 1


def test_mutated_research_cannot_be_reused_as_completed_case(execution):
    state = _execute(execution, 'research_only')
    assert state.status == 'completed', state.error
    path = Path(state.artifacts['forecast_case'])
    data = json.loads(path.read_text())
    data['question'] = 'A different target'
    path.write_text(json.dumps(data))
    state.status = 'failed'
    execution.po.PipelineOrchestrator._run(state)
    assert state.status == 'failed'
    assert 'changed' in state.error
    assert len(execution.calls) == 1


def test_research_only_continues_without_reextracting_case(execution):
    po = execution.po
    state = _execute(execution, 'research_only')
    assert state.status == 'completed', state.error
    continued = po.PipelineOrchestrator.continue_to_full(state.pipeline_id)
    po.PipelineOrchestrator._run(continued)
    assert continued.status == 'completed', continued.error
    assert len(execution.calls) == 1
    assert po.ReportManager.publication_status(continued.report_id)['publishable']



def test_manual_resolution_sdk_passes_frozen_contract_and_maps_errors(runtime, monkeypatch):
    from flask import Flask
    from app.api import sdk
    from app.services import forecast_feedback as feedback
    calls = []
    def resolve(report_id, forecast_id, **kwargs):
        calls.append((report_id, forecast_id, kwargs))
        return {"report_id": report_id, "forecast_id": forecast_id, "outcome": kwargs["outcome"]}
    monkeypatch.setattr(feedback, "resolve_published_binary", resolve)
    app = Flask(__name__)
    app.register_blueprint(sdk.sdk_bp, url_prefix="/api/v1")
    client = app.test_client()
    response = client.post("/api/v1/resolve-binary/report_target", json={
        "forecast_id": "B1", "outcome": True, "contract_sha256": "a" * 64,
        "evidence": {"text": "Publisher stated the event", "url": "https://example.test/event"}})
    assert response.status_code == 200
    assert calls[0][2]["contract_sha256"] == "a" * 64
    assert calls[0][2]["resolved_at"].endswith("+00:00")
    assert client.post("/api/v1/resolve-binary/report_target", json=[]).status_code == 400



def test_cancellation_at_research_return_boundary_cannot_complete(execution, monkeypatch):
    po = execution.po
    original = po.DeerFlowResearchRunner.run
    def cancel_on_return(*args, **kwargs):
        result = original(*args, **kwargs)
        kwargs["cancel_event"].set()
        return result
    monkeypatch.setattr(po.DeerFlowResearchRunner, "run", cancel_on_return)
    state = _execute(execution, "research_only")
    assert state.status == "cancelled"
    assert Path(state.handoff_dir, "forecast_case.json").is_file()
    assert state.stages["research"].status != "completed"


def test_target_fork_owns_artifacts_and_preserves_parent(execution):
    po = execution.po
    state = _execute(execution)
    assert state.status == "completed", state.error
    parent_case = Path(state.artifacts["forecast_case"]).read_bytes()
    parent_result = Path(state.artifacts["target_simulation"]).read_bytes()
    child = po.PipelineOrchestrator.fork(state.pipeline_id, {"label": "seed placebo", "seed": 12})
    po.PipelineOrchestrator._run(child)
    assert child.status == "completed", child.error
    assert child.handoff_dir != state.handoff_dir
    assert child.project_id != state.project_id
    assert len(execution.calls) == 1
    assert Path(state.artifacts["forecast_case"]).read_bytes() == parent_case
    assert Path(state.artifacts["target_simulation"]).read_bytes() == parent_result
    receipt = json.loads(Path(child.artifacts["target_comparison"]).read_text())
    assert receipt["productionEligible"] is False
    forecast = json.loads(Path(child.artifacts["target_forecast"]).read_text())
    assert forecast["characterization_only"] is True



def test_live_decision_callback_has_pinned_budget_and_reuses_identical_observations(runtime, monkeypatch):
    from app.utils import llm_client
    calls = []
    class Client:
        def chat_json(self, *args, **kwargs):
            calls.append(args)
            return {"actions": []}
    monkeypatch.setattr(llm_client, "LLMClient", Client)
    state = runtime.po.PipelineOrchestrator.start("Spending?", forecast_authority="target-first-v1")
    state.options["target_decision_budget_v1"] = {"max_calls": 1}
    callback = tp._decision_provider(runtime.po.PipelineOrchestrator(), state)
    callback({"actorId": "A1", "period": 1})
    callback({"actorId": "A1", "period": 1})
    callback({"actorId": "A1", "period": 2})
    assert len(calls) == 1
    assert state.options["target_decision_usage"] == {
        "maximumRequests": 1, "requests": 1, "cacheHits": 1, "exhausted": True}



def test_llm_actor_requires_provider_before_simulation(execution, monkeypatch):
    execution.case["actors"][0]["decisionRule"]["kind"] = "llm"
    monkeypatch.setattr(execution.config, "LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(execution.config, "LLM_API_KEY", "")
    state = _execute(execution)
    assert state.status == "failed"
    assert "requires its configured API key" in state.error
    assert "target_simulation" not in state.artifacts


def test_rule_only_case_does_not_require_decision_provider(execution, monkeypatch):
    monkeypatch.setattr(execution.config, "LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(execution.config, "LLM_API_KEY", "")
    state = _execute(execution)
    assert state.status == "completed", state.error


def test_valid_target_fork_serves_child_graph_and_simulation(execution):
    from flask import Flask
    from app.api import graph, simulation
    po = execution.po
    parent = _execute(execution)
    assert parent.status == 'completed', parent.error
    child = po.PipelineOrchestrator.fork(parent.pipeline_id, {'label': 'API seed', 'seed': 13})
    po.PipelineOrchestrator._run(child)
    assert child.status == 'completed', child.error
    assert Path(child.handoff_dir) == Path(po.PipelineManager.handoff_dir(child.pipeline_id))
    app = Flask(__name__)
    app.register_blueprint(graph.graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation.simulation_bp, url_prefix='/api/simulation')
    client = app.test_client()
    for state in (parent, child):
        response = client.get(f'/api/graph/data/{state.graph_id}')
        assert response.status_code == 200, response.json
        response = client.get(f'/api/simulation/{state.simulation_id}/target?pipeline_id={state.pipeline_id}')
        assert response.status_code == 200, response.json


def test_target_fork_rejects_parent_research_tampering_before_admission(execution):
    parent = _execute(execution)
    assert parent.status == 'completed', parent.error
    path = Path(parent.artifacts['report'])
    path.write_text(path.read_text() + '\nFabricated parent sentence.\n')
    count = len(list((execution.root / 'pipelines').glob('pipe_*')))
    with pytest.raises(tp.TargetPipelineError, match='research receipts'):
        execution.po.PipelineOrchestrator.fork(parent.pipeline_id, {'label': 'must fail'})
    assert len(list((execution.root / 'pipelines').glob('pipe_*'))) == count


def test_target_fork_rejects_parent_change_after_admission(execution):
    parent = _execute(execution)
    assert parent.status == 'completed', parent.error
    child = execution.po.PipelineOrchestrator.fork(parent.pipeline_id, {'label': 'must fail'})
    path = Path(parent.artifacts['report'])
    path.write_text(path.read_text() + '\nChanged after fork admission.\n')
    execution.po.PipelineOrchestrator._run(child)
    assert child.status == 'failed'
    assert 'parent research receipts' in child.error
    assert not Path(execution.po.PipelineManager.handoff_dir(child.pipeline_id), 'research_report.md').exists()


def test_report_retry_uses_saved_method_lanes_after_environment_flag_flip(execution, monkeypatch):
    parent = _execute(execution)
    assert parent.status == 'completed', parent.error
    saved = Path(parent.artifacts['target_estimators']).read_bytes()
    before = json.loads(Path(parent.artifacts['target_forecast']).read_text())
    monkeypatch.setattr(execution.config, 'REPORT_TOURNAMENT', False)
    parent.status = 'failed'
    parent.stages['report'].status = 'pending'
    execution.po.PipelineOrchestrator._run(parent)
    assert parent.status == 'completed', parent.error
    after = json.loads(Path(parent.artifacts['target_forecast']).read_text())
    assert len(before['estimators']) > 1
    assert after['estimators'] == before['estimators']
    assert Path(parent.artifacts['target_estimators']).read_bytes() == saved


def test_second_case_consumes_library_published_by_real_pipeline(execution):
    first = _execute(execution)
    assert first.status == 'completed', first.error
    published = json.loads(Path(first.artifacts['target_library_publication']).read_text())
    assert published['entries']
    execution.case['caseId'] = 'second-spending-case'
    second = _execute(execution, 'research_only')
    assert second.status == 'completed', second.error
    context = json.loads(Path(second.artifacts['target_library']).read_text())
    assert any(row['provenance']['caseId'] == published['caseId'] for row in context['entries'])
    assert context['authority'] == 'prior_context_only'


def test_completed_llm_run_can_retry_report_without_decision_provider(execution, monkeypatch):
    from app.utils import llm_client
    class Client:
        def chat_json(self, *args, **kwargs):
            return {'actions': []}
    monkeypatch.setattr(llm_client, 'LLMClient', Client)
    monkeypatch.setattr(execution.config, 'LLM_PROVIDER', 'deepseek')
    monkeypatch.setattr(execution.config, 'LLM_API_KEY', 'fixture-only')
    execution.case['actors'][0]['decisionRule']['kind'] = 'llm'
    state = _execute(execution)
    assert state.status == 'completed', state.error
    original = Path(state.artifacts['target_simulation']).read_bytes()
    monkeypatch.setattr(execution.config, 'LLM_API_KEY', '')
    state.status = 'failed'
    state.stages['report'].status = 'pending'
    execution.po.PipelineOrchestrator._run(state)
    assert state.status == 'completed', state.error
    assert Path(state.artifacts['target_simulation']).read_bytes() == original


@pytest.mark.parametrize('status,cache_hit,expected', [('ok', False, 'unavailable'), ('stale', True, 'unavailable')])
def test_native_market_payload_reaches_frozen_estimates_and_publication(execution, monkeypatch, status, cache_hit, expected):
    from datetime import datetime, timezone
    execution.case['binaries'][0]['resolution_contract'] = {
        'kind': 'polymarket', 'market_id': 'M1', 'equivalence': 'exact'}
    stamp = datetime.now(timezone.utc).isoformat()
    payload = {'markets': [{'market_id': 'M1', 'implied_yes_prob': 0.73,
        'question': execution.case['binaries'][0]['question'], 'url': 'https://example.test/market',
        'endDate': execution.case['resolution']['horizon'], 'retrieved_at': stamp}],
        'as_of': stamp, 'status': {'state': status}, 'cache': {'hit': cache_hit}}
    original = execution.po.DeerFlowResearchRunner.run
    def with_market(*args, **kwargs):
        result = original(*args, **kwargs)
        Path(args[1], 'prediction_markets.json').write_text(json.dumps(payload))
        return result
    monkeypatch.setattr(execution.po.DeerFlowResearchRunner, 'run', with_market)
    state = _execute(execution)
    assert state.status == 'completed', state.error
    evidence = json.loads(Path(state.artifacts['target_evidence']).read_text())
    assert evidence['markets'] == payload
    frozen = json.loads(Path(state.artifacts['target_estimators']).read_text())
    lane = next(row for row in frozen['estimators'] if row['source'] == 'market_implied')
    assert lane['status'] == expected
    forecast = json.loads(Path(state.artifacts['target_forecast']).read_text())
    # Transport freshness does not establish settlement equivalence. This
    # title-only source still supplies health diagnostics, never market authority.
    assert forecast['inputs_health']['markets']['status'] == ('fresh' if status == 'ok' else 'stale')
    assert forecast['binary_forecasts'][0]['probability'] == 0.6
    assert 'market_anchor' not in forecast['binary_forecasts'][0]
    assert forecast['binary_forecasts'][0]['resolution_contract']['kind'] == 'named_source_event'
    assert forecast['binary_forecasts'][0]['market_equivalence']['status'] == 'unavailable'
