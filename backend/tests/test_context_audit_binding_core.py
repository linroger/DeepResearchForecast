"""Independent review probe; synthetic storage, real binding/lookup/report consumers."""
import copy
import json
from pathlib import Path

import pytest

from app.config import Config
from app.services import official_data
from app.services import pipeline_orchestrator as po
from app.services.report_agent import ReportAgent, ReportManager
from app.services.simulation_manager import SimulationManager
from app.services.simulation_runner import SimulationRunner

pytestmark = pytest.mark.guarded_runner
OLD = 'ORIGINAL_CONSUMED_GENERATION capacity 40 MW'
NEW = 'REPLACEMENT_AFTER_PREPARE capacity 99 MW'

class Model:
    def __init__(self):
        self.calls = []
    def chat_json(self, messages, **kwargs):
        self.calls.append(copy.deepcopy(messages))
        return {'title': 'Capacity outlook', 'summary': 'Synthetic external model response.',
                'sections': [{'title': f'Outlook {i}', 'description': 'Capacity evidence'} for i in range(4)]}

class GraphResponse:
    def get_simulation_context(self, **kwargs):
        return {'graph_statistics': {}, 'related_facts': []}

@pytest.mark.parametrize('changed', ['none', 'actors', 'datasets'])
def test_bound_report_prompt_does_not_adopt_replacement_dossier(tmp_path, monkeypatch, changed):
    monkeypatch.setattr(Config, 'PIPELINE_DATA_DIR', str(tmp_path / 'pipelines'))
    monkeypatch.setattr(Config, 'OASIS_SIMULATION_DATA_DIR', str(tmp_path / 'simulations'))
    monkeypatch.setattr(SimulationManager, 'SIMULATION_DATA_DIR', str(tmp_path / 'simulations'))
    monkeypatch.setattr(SimulationRunner, 'RUN_STATE_DIR', str(tmp_path / 'simulations'))
    monkeypatch.setattr(ReportManager, 'REPORTS_DIR', str(tmp_path / 'reports'))
    monkeypatch.setattr(Config, 'PREDICTION_MARKETS_ENABLED', False)
    monkeypatch.setenv('REPORT_OUTPUT_LANGUAGE', 'English')
    pid = 'pipe_review_legacy'
    po.PipelineManager.ensure_dirs(pid)
    handoff = Path(po.PipelineManager.handoff_dir(pid))
    actors = {'central_question': 'Will the permit unlock capacity by 2029?',
              'as_of_date': '2026-10-20', 'actors': [], 'hot_topics': [OLD]}
    (handoff / 'research_report.md').write_text('# Consumed research\n' + (OLD + '.\n') * 40)
    (handoff / 'actors.json').write_text(json.dumps(actors))
    (handoff / 'sources.json').write_text('[]')
    manager = SimulationManager()
    sim = manager.create_simulation('project_review', 'graph_review', enable_twitter=True, enable_reddit=True)
    state = po.PipelineState(pipeline_id=pid, prompt=actors['central_question'], simulation_id=sim.simulation_id,
                             handoff_dir=str(handoff), stages={po.STAGE_RESEARCH: po.StageState(
                                 name=po.STAGE_RESEARCH, status='completed', progress=100)})
    po.PipelineManager.save(state)
    (handoff / 'data').mkdir()
    (handoff / 'data' / 'datasets.json').write_text(json.dumps({'datasets': []}))
    official_data.bind_simulation_research(sim.simulation_id, handoff, pipeline_id=pid)
    assert official_data.simulation_research_binding(sim.simulation_id)['status'] == 'valid'
    if changed == 'actors':
        actors['hot_topics'] = [NEW]
        (handoff / 'actors.json').write_text(json.dumps(actors))
    if changed == 'datasets':
        (handoff / 'data' / 'datasets.json').write_text(json.dumps({'datasets': [{'unexpected': NEW}]}))
    proof = official_data.simulation_research_binding(sim.simulation_id)
    assert proof['status'] == ('valid' if changed == 'none' else 'invalid')
    if changed == 'actors':
        with pytest.raises(ValueError, match='Consumed research generation core'):
            po.load_research_dossier_for_simulation(sim.simulation_id)
        return
    dossier = po.load_research_dossier_for_simulation(sim.simulation_id)
    model = Model()
    agent = ReportAgent(graph_id='graph_review', simulation_id=sim.simulation_id,
        simulation_requirement=state.prompt, llm_client=model, zep_tools=GraphResponse(),
        situation_brief=dossier['situation_brief'], actors=dossier['actors'],
        sources=dossier['sources'], research_report=dossier['research_report'],
        official_data=dossier['official_data'], news_market_context=dossier['news_market_context'])
    agent.plan_outline()
    assert model.calls, 'The actual report outline must reach the model boundary'
    prompt = json.dumps(model.calls, ensure_ascii=False)
    (tmp_path / 'actual-consumer.json').write_text(json.dumps({
        'binding_status': proof['status'], 'model_messages': model.calls,
        'official_data': dossier['official_data'], 'dossier': dossier}, ensure_ascii=False, indent=2))
    if changed in ('none', 'datasets'):
        assert OLD in prompt, 'Matching generation must reach the actual prompt'
    if changed == 'datasets':
        assert dossier['official_data'] is None and dossier['report_artifacts'] == {}
    assert NEW not in prompt, 'An invalid binding allowed replacement research into the real report prompt'
