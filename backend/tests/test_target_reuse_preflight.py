"""HTTP reuse must depend on remaining work, not unavailable completed-stage providers."""
from pathlib import Path

import pytest
from flask import Flask

from tests import test_target_pipeline as pipeline_cases

# Reuse the real pipeline fixture without collecting its tests a second time.
case = pipeline_cases.case
runtime = pipeline_cases.runtime
execution = pipeline_cases.execution
_execute = pipeline_cases._execute


@pytest.fixture
def client(execution, monkeypatch):
    from app.api import research
    monkeypatch.setattr(execution.config, "DEERFLOW_DIR", str(execution.root / "missing-research-engine"))
    monkeypatch.setattr(execution.config, "DEERFLOW_MODEL", "deepseek")
    monkeypatch.setattr(execution.config, "DEERFLOW_KEY_ENV", {"deepseek": "FIRST_TEN_ABSENT_RESEARCH_KEY"})
    monkeypatch.delenv("FIRST_TEN_ABSENT_RESEARCH_KEY", raising=False)
    app = Flask(__name__)
    app.register_blueprint(research.research_bp, url_prefix="/api/research")
    return app.test_client()


def test_http_resume_published_inputs_needs_no_research_provider(execution, client):
    state = _execute(execution)
    assert state.status == "completed", state.error
    original = Path(state.artifacts["target_simulation"]).read_bytes()
    state.status = "failed"
    state.current_stage = "report"
    state.stages["report"].status = "failed"
    execution.po.PipelineManager.save(state)
    response = client.post(f"/api/research/{state.pipeline_id}/resume", json={})
    assert response.status_code == 200, response.json
    resumed = execution.po.PipelineState.from_dict(execution.po.PipelineManager.load(state.pipeline_id))
    execution.po.PipelineOrchestrator._run(resumed)
    assert resumed.status == "completed", resumed.error
    assert len(execution.calls) == 1
    assert Path(resumed.artifacts["target_simulation"]).read_bytes() == original
    assert execution.po.ReportManager.publication_status(resumed.report_id)["publishable"]


def test_http_continue_rule_case_needs_no_research_provider(execution, client):
    state = _execute(execution, "research_only")
    assert state.status == "completed", state.error
    response = client.post(f"/api/research/{state.pipeline_id}/continue", json={})
    assert response.status_code == 200, response.json
    continued = execution.po.PipelineState.from_dict(execution.po.PipelineManager.load(state.pipeline_id))
    execution.po.PipelineOrchestrator._run(continued)
    assert continued.status == "completed", continued.error
    assert len(execution.calls) == 1
    assert execution.po.ReportManager.publication_status(continued.report_id)["publishable"]


def test_http_seed_fork_rule_case_needs_no_research_provider(execution, client):
    state = _execute(execution)
    assert state.status == "completed", state.error
    original = Path(state.artifacts["target_simulation"]).read_bytes()
    response = client.post(f"/api/research/{state.pipeline_id}/scenario", json={"label": "Seed replay", "seed": 17})
    assert response.status_code == 200, response.json
    child = execution.po.PipelineState.from_dict(execution.po.PipelineManager.load(response.json["data"]["pipeline_id"]))
    execution.po.PipelineOrchestrator._run(child)
    assert child.status == "completed", child.error
    assert len(execution.calls) == 1
    assert Path(state.artifacts["target_simulation"]).read_bytes() == original


@pytest.mark.parametrize('operation,body', [
    ('resume', {}), ('continue', {}), ('scenario', {'label': 'Replay', 'seed': 17}),
])
def test_http_reuse_rejects_changed_research_without_dispatch(execution, client, operation, body):
    state = _execute(execution, 'research_only' if operation == 'continue' else 'full')
    assert state.status == 'completed', state.error
    if operation == 'resume':
        state.status = 'failed'
        state.current_stage = 'report'
        state.stages['report'].status = 'failed'
        execution.po.PipelineManager.save(state)
    Path(state.artifacts['report']).write_text('Changed source generation')
    before = execution.po.PipelineManager.load(state.pipeline_id)
    launches = len(execution.launched)
    response = client.post(f'/api/research/{state.pipeline_id}/{operation}', json=body)
    assert response.status_code == 400, response.json
    assert 'invalid' in response.json['preflight_errors'][0]
    assert len(execution.launched) == launches
    assert execution.po.PipelineManager.load(state.pipeline_id) == before


def test_http_resume_incomplete_research_keeps_provider_preflight(execution, client):
    state = execution.po.PipelineOrchestrator.start('Spending?', forecast_authority='target-first-v1')
    state.status = 'failed'
    execution.po.PipelineManager.save(state)
    launches = len(execution.launched)
    response = client.post(f'/api/research/{state.pipeline_id}/resume', json={})
    assert response.status_code == 400
    assert any('FIRST_TEN_ABSENT_RESEARCH_KEY' in error for error in response.json['preflight_errors'])
    assert len(execution.launched) == launches


def test_http_continue_llm_case_still_requires_decision_provider(execution, client, monkeypatch):
    execution.case['actors'][0]['decisionRule']['kind'] = 'llm'
    state = _execute(execution, 'research_only')
    assert state.status == 'completed', state.error
    monkeypatch.setattr(execution.config, 'LLM_PROVIDER', 'deepseek')
    monkeypatch.setattr(execution.config, 'LLM_API_KEY', '')
    launches = len(execution.launched)
    response = client.post(f'/api/research/{state.pipeline_id}/continue', json={})
    assert response.status_code == 400
    assert response.json['preflight_errors'] == ['Target decision provider deepseek requires its configured API key']
    assert len(execution.launched) == launches


def test_http_saved_llm_paths_retry_but_new_seed_requires_provider(execution, client, monkeypatch):
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
    response = client.post(f'/api/research/{state.pipeline_id}/scenario', json={'label': 'Replay', 'seed': 17})
    assert response.status_code == 400
    assert 'decision provider' in response.json['preflight_errors'][0]
    state.status = 'failed'
    state.current_stage = 'report'
    state.stages['report'].status = 'failed'
    execution.po.PipelineManager.save(state)
    response = client.post(f'/api/research/{state.pipeline_id}/resume', json={})
    assert response.status_code == 200, response.json
    resumed = execution.po.PipelineState.from_dict(execution.po.PipelineManager.load(state.pipeline_id))
    execution.po.PipelineOrchestrator._run(resumed)
    assert resumed.status == 'completed', resumed.error
    assert Path(resumed.artifacts['target_simulation']).read_bytes() == original


@pytest.mark.parametrize('operation,expected', [
    ('resume', {'mode': 'research_only'}),
    ('continue', {'mode': 'full', 'model': 'deepseek'}),
    ('scenario', {'mode': 'full'}),
])
def test_legacy_readiness_arguments_are_unchanged(monkeypatch, operation, expected):
    from app.api import research
    seen = []
    monkeypatch.setattr(research, 'preflight_pipeline', lambda **kwargs: seen.append(kwargs) or ['legacy preflight'])
    saved = {'mode': 'research_only', 'options': {'research_model': 'deepseek'}}
    assert research._preflight_existing_pipeline(saved, operation=operation) == ['legacy preflight']
    assert seen == [expected]


@pytest.mark.parametrize('tamper', [False, True])
def test_http_resume_interrupted_seed_fork_uses_verified_parent(execution, client, tamper):
    parent = _execute(execution)
    assert parent.status == 'completed', parent.error
    response = client.post(f'/api/research/{parent.pipeline_id}/scenario', json={'label': 'Interrupted replay', 'seed': 17})
    assert response.status_code == 200, response.json
    child = execution.po.PipelineState.from_dict(execution.po.PipelineManager.load(response.json['data']['pipeline_id']))
    assert child.stages['research'].status == 'pending'
    child.status = 'failed'
    execution.po.PipelineManager.save(child)
    launches = len(execution.launched)
    if tamper:
        Path(parent.artifacts['report']).write_text('Changed admitted parent generation')
    response = client.post(f'/api/research/{child.pipeline_id}/resume', json={})
    if tamper:
        assert response.status_code == 400
        assert 'invalid' in response.json['preflight_errors'][0]
        assert len(execution.launched) == launches
    else:
        assert response.status_code == 200, response.json
        resumed = execution.po.PipelineState.from_dict(execution.po.PipelineManager.load(child.pipeline_id))
        execution.po.PipelineOrchestrator._run(resumed)
        assert resumed.status == 'completed', resumed.error
        assert len(execution.calls) == 1
        assert execution.po.ReportManager.publication_status(resumed.report_id)['publishable']
