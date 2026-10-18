"""World runs pin the research generation they consumed, as OASIS PREPARE does.

Uses the lifecycle boundary: only HTTP and the child process are faked; the
pipeline stages, manager, compiler, seals and binding are production code.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_world_lifecycle as lifecycle

boundary = lifecycle.boundary
pytestmark = pytest.mark.guarded_runner
PROJECT = SimpleNamespace(project_id='project_fixture')


def research_handoff(b, state):
    """Write the consumed generation's files, then capture it as the RESEARCH stage does."""
    from app.services.official_data import capture_research_generation

    handoff = Path(state.handoff_dir)
    handoff.mkdir(parents=True, exist_ok=True)
    (handoff / 'research_report.md').write_text(b.report, encoding='utf-8')
    (handoff / 'actors.json').write_text(json.dumps(b.actors), encoding='utf-8')
    (handoff / 'sources.json').write_text('[]', encoding='utf-8')
    return capture_research_generation(state.handoff_dir, report=b.report, sources=[])


def run(b, state, consumed):
    return b.po.PipelineOrchestrator()._run_world_stages(
        state, PROJECT, 'graph_fixture', b.actors, b.report, consumed_generation=consumed, research_sources=[])


def test_world_run_binds_its_consumed_research_and_reuse_keeps_it(boundary):
    from app.services.official_data import simulation_research_binding
    from app.services.pipeline_orchestrator import load_research_dossier_for_simulation

    b = boundary
    state = b.pipeline()
    consumed = research_handoff(b, state)
    sim = run(b, state, consumed)
    binding = simulation_research_binding(sim.simulation_id)
    assert binding['status'] == 'valid' and binding['pipeline_id'] == state.pipeline_id
    assert binding['files'] == consumed['files'] and 'official_data_binding' not in state.options
    # The report-side dossier loader now resolves this world through the binding.
    assert load_research_dossier_for_simulation(sim.simulation_id)['research_report'] == b.report
    before = lifecycle.hashes(b.root / sim.simulation_id)
    restored = b.po.PipelineState.from_dict(b.po.PipelineManager.load(state.pipeline_id))
    run(b, restored, consumed)
    assert lifecycle.hashes(b.root / sim.simulation_id) == before
    assert simulation_research_binding(sim.simulation_id)['status'] == 'valid'


def test_reused_world_sealed_before_binding_is_bound_on_resume(boundary):
    from app.services.official_data import simulation_research_binding

    b = boundary
    state = b.pipeline()
    consumed = research_handoff(b, state)
    sim = run(b, state, consumed)
    # A world sealed by the previous code has the same inputs but no binding file.
    (b.root / sim.simulation_id / 'official_research_binding.json').unlink()
    assert simulation_research_binding(sim.simulation_id)['status'] == 'missing'
    restored = b.po.PipelineState.from_dict(b.po.PipelineManager.load(state.pipeline_id))
    run(b, restored, consumed)
    assert simulation_research_binding(sim.simulation_id)['status'] == 'valid'
    assert len(b.launches) == 1  # the sealed world is reused, not prepared or run again


def test_changed_research_degrades_to_unbound_official_data_without_failing(boundary):
    from app.services.official_data import simulation_research_binding

    b = boundary
    state = b.pipeline()
    consumed = research_handoff(b, state)
    (Path(state.handoff_dir) / 'sources.json').write_text('[{"source_id": "late"}]', encoding='utf-8')
    sim = run(b, state, consumed)
    assert state.stages['prepare'].status == state.stages['run'].status == 'completed'
    assert state.options['official_data_binding']['status'] == 'unavailable'
    assert state.options['official_data_binding']['stage'] == 'prepare'
    assert simulation_research_binding(sim.simulation_id)['status'] == 'missing'


def test_world_seed_child_inherits_the_parent_generation(boundary):
    from app.services.official_data import simulation_research_binding

    b = boundary
    state = b.pipeline()
    consumed = research_handoff(b, state)
    run(b, state, consumed)
    spec = json.loads((b.root / state.simulation_id / 'world_spec.json').read_text())
    child = b.po.PipelineOrchestrator()._run_world_seed(state, seed=spec['seed'] + 7919, report_md=b.report, sources=[])
    parent, seeded = simulation_research_binding(state.simulation_id), simulation_research_binding(child.simulation_id)
    assert seeded['status'] == 'valid' and seeded['files'] == parent['files'] == consumed['files']
    assert child.simulation_id != state.simulation_id


def test_unbound_parent_leaves_the_seed_unbound(boundary):
    from app.services.official_data import simulation_research_binding

    b = boundary
    state = b.pipeline()
    lifecycle.run_pipeline_world(b, state)
    spec = json.loads((b.root / state.simulation_id / 'world_spec.json').read_text())
    child = b.po.PipelineOrchestrator()._run_world_seed(state, seed=spec['seed'] + 7919, report_md=b.report, sources=[])
    assert simulation_research_binding(child.simulation_id)['status'] == 'missing'


def test_world_preparation_keeps_the_typed_error_code_on_the_pipeline(boundary):
    from app.services.world_simulation.contracts import WorldError

    b = boundary
    state = b.pipeline()
    state.options.pop('world_spec')
    state.options['world_policy_spec'] = lifecycle.modeling_policy()
    state.options['safety_policy_v1'] = {'simulation_forecast_effect': 'no_update'}
    candidate = lifecycle.raw_model()
    candidate['gaps'] = [{'code': 'no_quota_authority', 'description': 'No admitted authority sets quotas.'}]
    b.behavior.model_candidate = candidate
    with pytest.raises(WorldError) as error:
        b.po.PipelineOrchestrator()._run_world_stages(state, PROJECT, 'graph_fixture', b.actors, b.report)
    assert error.value.code == 'modeling_gap'
    assert state.options['world_preparation_error'] == {
        'code': 'modeling_gap', 'details': {'attempt': 1, 'declared': True, 'gapCodes': ['no_quota_authority']}}
    assert len(b.sent) == 1 and not b.launches


def test_unverifiable_parent_leaves_a_world_seed_unbound_but_running(boundary):
    from app.services.official_data import simulation_research_binding

    b = boundary
    state = b.pipeline()
    consumed = research_handoff(b, state)
    run(b, state, consumed)
    (Path(state.handoff_dir) / 'sources.json').write_text('[{"source_id": "late"}]', encoding='utf-8')
    assert simulation_research_binding(state.simulation_id)['status'] == 'invalid'
    spec = json.loads((b.root / state.simulation_id / 'world_spec.json').read_text())
    seed = spec['seed'] + 7919
    child = b.po.PipelineOrchestrator()._run_world_seed(state, seed=seed, report_md=b.report, sources=[])
    assert simulation_research_binding(child.simulation_id)['status'] == 'missing'
    row = state.options['world_seed_runs'][str(seed)]
    assert row['status'] == 'world_completed' and row['official_data_binding']['status'] == 'unavailable'
