"""Declared institutional identity reaches sealed cast, executable config and world."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from app.config import Config
from app.services.simulation_manager import SimulationManager, SimulationStatus
from app.services import pipeline_orchestrator as pipeline
from tests import test_context_audit_prepare as prepare_cases
from tests import test_context_audit_direct_api as api_cases

prepare_env = prepare_cases.prepare_env
bound_case = api_cases.bound_case


def dossier():
    # Short source-matched institutional descriptions, without private action text.
    return {'as_of_date': '2026-10-26', 'forecast_horizon': '2027-12-31',
        'central_question': 'How will the security industry change through 2027?',
        'actors': [
            {'name': 'CrowdStrike', 'type': 'Organization', 'role': 'AI-native endpoint security leader',
             'description': 'Vendor benchmark and external advisor.', 'simulation_tier': 1},
            {'name': 'Anthropic', 'type': 'Organization', 'role': 'Frontier lab with a safety stance',
             'description': 'Subject of a reported FTC investigation.', 'simulation_tier': 1},
            {'name': 'Munich Re', 'type': 'Organization', 'role': 'Cyber insurer projecting market growth',
             'description': 'Reviews policy language after lab disclosures.', 'simulation_tier': 2}],
        'forecast_inputs': {'scenarios': [{'name': 'Growth', 'probability': .6}, {'name': 'Other', 'probability': .4}]}}


def ontology():
    return {'entity_types': [
        {'name': 'Organization', 'agency_class': 'firm', 'examples': ['CrowdStrike', 'Anthropic', 'Munich Re']},
        {'name': 'CybersecurityVendor', 'agency_class': 'firm', 'examples': ['CrowdStrike']},
        {'name': 'FrontierAILab', 'agency_class': 'firm', 'examples': ['Anthropic']},
        {'name': 'CyberInsurer', 'agency_class': 'financial_institution', 'examples': ['Munich Re']}]}


def test_real_prepare_seals_one_classification_used_by_config_and_world(prepare_env, monkeypatch):
    monkeypatch.setattr(Config, 'SIM_WORLD_MODEL', True)
    monkeypatch.setattr(Config, 'SIM_AGENCY_CLASS_SOURCE', 'ontology')
    manager = SimulationManager()
    sim = manager.create_simulation('cast-project', 'cast-graph')
    actors = dossier()
    declared = ontology()
    original = deepcopy((actors, declared))
    state = manager.prepare_simulation(sim.simulation_id, actors['central_question'], 'Institutional description.',
                                       actors=actors, ontology=declared, research_language='English', max_rounds=3)
    assert state.status == SimulationStatus.READY, state.error
    root = Path(manager._get_simulation_dir(sim.simulation_id))
    config = json.loads((root / 'simulation_config.json').read_text())
    cast = json.loads((root / 'actor_cast_manifest.json').read_text())
    expected = {'CrowdStrike': 'firm', 'Anthropic': 'firm', 'Munich Re': 'financial_institution'}
    assert {row['entity_name']: row['agency_class'] for row in config['agent_configs']} == expected
    assert {row['name']: row['agency_class'] for row in config['world_model']['actors']} == expected
    from app.services.world_model import WorldModel
    from app.services.agent_decision import build_option_menu
    world = WorldModel.from_seed(config['world_model'], config['agent_configs'])
    for actor in world.actors.values():
        assert actor.agency_class == expected[actor.name]
        menu = build_option_menu(actor, world, 1)
        assert menu, actor.name
    for row in config['agent_configs']:
        classification = cast['agency_classifications'][row['entity_uuid']]
        assert row['agency_class_basis'] == classification['basis']
        assert row['agency_class'] == classification['agency_class']
        assert classification['basis']['source'] == 'ontology'
    selected = [row for row in cast['decisions'] if row['status'] == 'selected']
    assert {row['actor_name']: row['agency_class'] for row in selected} == expected
    assert manager.validate_prepared_simulation_config(state.simulation_id)['simulation_config_sha256']
    assert (actors, declared) == original


@pytest.mark.parametrize('legacy', [False, True])
def test_missing_ontology_or_explicit_rollback_keeps_prior_serialization(prepare_env, monkeypatch, legacy):
    monkeypatch.setattr(Config, 'SIM_WORLD_MODEL', True)
    monkeypatch.setattr(Config, 'SIM_AGENCY_CLASS_SOURCE', 'legacy' if legacy else 'ontology')
    manager = SimulationManager()
    sim = manager.create_simulation('cast-project', 'cast-graph')
    actors = dossier()
    state = manager.prepare_simulation(sim.simulation_id, actors['central_question'], 'Institutional description.',
        actors=actors, ontology=ontology() if legacy else None, research_language='English', max_rounds=3)
    assert state.status == SimulationStatus.READY, state.error
    root = Path(manager._get_simulation_dir(sim.simulation_id))
    config = json.loads((root / 'simulation_config.json').read_text())
    cast = json.loads((root / 'actor_cast_manifest.json').read_text())
    assert 'agency_classifications' not in cast
    assert all('agency_class_basis' not in row for row in config['agent_configs'])
    assert all('agency_class_basis' not in row for row in config['world_model']['actors'])


def _seal_ontology(case, value):
    path = case.handoff / 'ontology.json'
    path.write_text(json.dumps(value))
    entry = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
             'produced_by_stage': 'ontology', 'schema_ok': True}
    pipeline.PipelineManager.write_artifact_manifest(case.state.pipeline_id, {'ontology': entry})
    return path


def test_ontology_read_uses_exact_owner_receipt_and_rejects_tamper(bound_case, monkeypatch):
    monkeypatch.setattr(Config, 'SIM_AGENCY_CLASS_SOURCE', 'ontology')
    path = _seal_ontology(bound_case, ontology())
    assert pipeline.load_preparation_ontology(bound_case.state.pipeline_id, str(bound_case.handoff)) == ontology()
    path.write_text(json.dumps({'entity_types': []}))
    with pytest.raises(ValueError, match='receipt'):
        pipeline.load_preparation_ontology(bound_case.state.pipeline_id, str(bound_case.handoff))
    monkeypatch.setattr(Config, 'SIM_AGENCY_CLASS_SOURCE', 'legacy')
    assert pipeline.load_preparation_ontology(bound_case.state.pipeline_id, str(bound_case.handoff)) is None


def test_manual_prepare_rejects_tampered_owned_ontology_before_dispatch(prepare_env, bound_case, monkeypatch):
    monkeypatch.setattr(Config, 'SIM_AGENCY_CLASS_SOURCE', 'ontology')
    path = _seal_ontology(bound_case, ontology())
    path.write_text('{}')
    response = api_cases._client().post('/api/simulation/prepare', json={'simulation_id': bound_case.simulation.simulation_id})
    assert response.status_code == 409, response.json
    assert response.json['error'] == 'Preparation ontology generation is invalid'


def test_manual_prepare_consumes_bound_ontology_not_mutable_project(prepare_env, bound_case, monkeypatch):
    from types import SimpleNamespace
    from app.api import simulation as simulation_api
    from app.models.project import ProjectManager
    from app.models.task import TaskManager, TaskStatus
    monkeypatch.setattr(Config, 'SIM_AGENCY_CLASS_SOURCE', 'ontology')
    declared = {'entity_types': [{'name': 'Organization', 'agency_class': 'financial_institution'}]}
    _seal_ontology(bound_case, declared)
    project = ProjectManager.get_project(bound_case.state.project_id)
    project.ontology = {'entity_types': [{'name': 'Organization', 'agency_class': 'regulator_agency'}]}
    ProjectManager.save_project(project)
    monkeypatch.setattr(simulation_api, 'ZepEntityReader', lambda: SimpleNamespace(
        filter_defined_entities=lambda **kwargs: SimpleNamespace(filtered_count=0, entity_types=set())))
    calls = []
    original = SimulationManager.prepare_simulation
    def capture(self, **kwargs):
        calls.append(deepcopy(kwargs))
        return original(self, **kwargs)
    monkeypatch.setattr(SimulationManager, 'prepare_simulation', capture)
    response = api_cases._client().post('/api/simulation/prepare', json={'simulation_id': bound_case.simulation.simulation_id})
    assert response.status_code == 200, response.json
    task = TaskManager().get_task(response.json['data']['task_id'])
    assert task.status == TaskStatus.COMPLETED, task.error
    assert len(calls) == 1 and calls[0]['ontology'] == declared
    root = Path(bound_case.manager._get_simulation_dir(bound_case.simulation.simulation_id))
    cast = json.loads((root / 'actor_cast_manifest.json').read_text())
    assert cast['agency_classifications']
    # The immutable selected input wins; today's unrelated project cannot replace it.
    assert all(row['agency_class'] == 'financial_institution' for row in cast['agency_classifications'].values())


def test_ontology_receipt_rejects_foreign_path_even_with_matching_bytes(bound_case, monkeypatch):
    monkeypatch.setattr(Config, 'SIM_AGENCY_CLASS_SOURCE', 'ontology')
    path = _seal_ontology(bound_case, ontology())
    manifest = pipeline.PipelineManager.load_artifact_manifest(bound_case.state.pipeline_id)
    foreign = bound_case.handoff.parent / 'foreign-ontology.json'
    foreign.write_bytes(path.read_bytes())
    manifest['ontology']['path'] = str(foreign)
    pipeline.PipelineManager.write_artifact_manifest(bound_case.state.pipeline_id, manifest)
    with pytest.raises(ValueError, match='receipt'):
        pipeline.load_preparation_ontology(bound_case.state.pipeline_id, str(bound_case.handoff))


@pytest.mark.parametrize('content', ['{"ontology": null}', '{broken', '[]'])
def test_present_invalid_ontology_manifest_is_not_optional_absence(prepare_env, bound_case, monkeypatch, content):
    monkeypatch.setattr(Config, 'SIM_AGENCY_CLASS_SOURCE', 'ontology')
    _seal_ontology(bound_case, ontology())
    Path(pipeline.PipelineManager.artifact_manifest_path(bound_case.state.pipeline_id)).write_text(content)
    response = api_cases._client().post('/api/simulation/prepare', json={'simulation_id': bound_case.simulation.simulation_id})
    assert response.status_code == 409, response.json
    assert 'ontology' in response.json['error'].lower()
    assert prepare_env == []
