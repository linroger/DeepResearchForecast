"""Prepared input → real child controller → committed public/analyst consumers."""
from pathlib import Path

import pytest

from app.services.world_simulation.artifacts import atomic_json, read_json
from app.services.world_simulation.contracts import WorldError, validate_decision
from app.services.world_simulation.examples import ExamplePolicy, example_spec
from app.services.world_simulation.kernel import initialize_world, resolve_round
from app.services.world_simulation.observations import build_observation
from app.services.world_simulation.results import load_frozen_result, read_result, report_context
from app.services.world_simulation.service import WorldSimulationService as Service, run_child
from app.services.world_simulation.store import WorldStore

pytestmark = pytest.mark.guarded_runner


def prepare(tmp_path, domain='investment', **changes):
    from app.services.simulation_manager import SimulationManager
    manager = SimulationManager()
    manager.SIMULATION_DATA_DIR = str(tmp_path)
    state = manager.create_simulation('project_world', 'graph_world', simulation_engine='world-v1')
    raw = example_spec(domain)
    raw.pop('simulationId')
    raw.pop('generationId')
    raw.update(changes)
    state = manager.prepare_world_simulation(state.simulation_id, raw_spec=raw,
        research_report='Synthetic cross-domain test; all mechanism values are assumptions.',
        research_generation_id='research_fixture', research_engine='v3')
    return manager, state, Path(tmp_path) / state.simulation_id


@pytest.mark.parametrize('domain', ['investment', 'trade', 'coalition'])
def test_real_prepared_child_to_frozen_consumers(tmp_path, domain):
    manager, state, directory = prepare(tmp_path, domain)
    assert state.world_generation_id
    assert state.world_input_manifest_sha256
    assert run_child(directory, policy=ExamplePolicy(domain)) == 0
    status = Service.status(state.simulation_id, root=tmp_path)
    assert status['runner_status'] == 'completed'
    assert status['current_round'] == 4
    assert not any(key.startswith('twitter') or key.startswith('reddit') for key in status)
    result = Service.require_complete(state.simulation_id, root=tmp_path)
    assert result == load_frozen_result(directory) == read_result(directory)
    assert result['valueStatus'] == 'simulated'
    for record in result['world']['metrics'].values():
        assert record['valueStatus'] == 'simulated'
        assert record['basis']['kind'] == 'simulation_event'
        assert record['initialBasis']['kind'] == 'scenario_assumption'
    assert report_context(result)['probabilityEvidence'] is False
    assert result['events']
    assert result['assumptions']
    assert not result['decisions']  # Private rationale is not public report data.
    analyst = read_result(directory, view='analyst')
    assert analyst['decisions']
    assert all(d['observationId'] for d in analyst['decisions'])
    assert 'actorStates' in analyst['world'] and 'actorStates' not in result['world']
    assert analyst['revision'] == result['revision']
    history = read_result(directory, round_index=1, revision=result['revision'])
    assert history['round'] == 1 and len(history['trajectory']) == 2
    before = {p.name: p.read_bytes() for p in directory.glob('*.json')}
    assert Service.require_complete(state.simulation_id, root=tmp_path) == result
    assert before == {p.name: p.read_bytes() for p in directory.glob('*.json')}


def test_output_tamper_and_stale_revision_fail_without_get_repair(tmp_path):
    _, state, directory = prepare(tmp_path)
    assert run_child(directory, policy=ExamplePolicy('investment')) == 0
    with pytest.raises(WorldError, match='refresh'):
        read_result(directory, revision='older')
    result_path = directory / 'world_result.json'
    result = read_json(result_path)
    result['world']['metrics']['capacity']['value'] = '9000'
    atomic_json(result_path, result)
    corrupt = result_path.read_bytes()
    with pytest.raises(WorldError):
        load_frozen_result(directory)
    assert result_path.read_bytes() == corrupt
    assert Service.status(state.simulation_id, root=tmp_path)['runner_status'] == 'failed'


def test_state_pin_and_prepared_bytes_tamper_reject_before_child(tmp_path):
    _, state, directory = prepare(tmp_path)
    path = directory / 'world_spec.json'
    original = path.read_bytes()
    value = read_json(path)
    value['seed'] = 400
    atomic_json(path, value)
    with pytest.raises(WorldError):
        Service.start(state.simulation_id, root=tmp_path)
    assert not (directory / 'world.sqlite3').exists()
    path.write_bytes(original)
    value = read_json(directory / 'state.json')
    value['world_generation_id'] = 'another'
    atomic_json(directory / 'state.json', value)
    with pytest.raises(WorldError):
        Service.require_complete(state.simulation_id, root=tmp_path)


def test_child_exit_or_completed_projection_without_commit_is_not_success(tmp_path):
    _, state, directory = prepare(tmp_path)
    atomic_json(directory / 'world_run.json', {'simulation_id': state.simulation_id,
        'generation_id': state.world_generation_id, 'runner_status': 'completed', 'process_pid': None})
    status = Service.status(state.simulation_id, root=tmp_path)
    assert status['runner_status'] == 'failed'
    assert status['error'] == 'missing_completion_evidence'


def test_cancelled_child_no_world_advance_and_fork_has_new_baseline(tmp_path):
    manager, state, directory = prepare(tmp_path)
    atomic_json(directory / 'world_cancel.json', {'generationId': state.world_generation_id})
    policy = ExamplePolicy('investment')
    assert run_child(directory, policy=policy) == 1
    assert policy.observations == []
    assert Service.status(state.simulation_id, root=tmp_path)['runner_status'] == 'stopped'
    child = manager.fork_world_simulation(state.simulation_id, seed=19)
    assert child.simulation_id != state.simulation_id
    assert child.world_generation_id != state.world_generation_id
    child_dir = Path(tmp_path) / child.simulation_id
    assert not (child_dir / 'world.sqlite3').exists()
    assert read_json(child_dir / 'world_spec.json')['seed'] == 19
    assert read_json(directory / 'world_spec.json')['seed'] == 0


def test_no_update_policy_keeps_view_but_excludes_report_reasoning(tmp_path):
    _, _, directory = prepare(tmp_path, forecastEffect='no_update')
    assert run_child(directory, policy=ExamplePolicy('investment')) == 0
    result = load_frozen_result(directory)
    assert result['trajectory'] and report_context(result) == {}


def test_delayed_message_is_delivered_without_becoming_a_resource_action():
    spec = example_spec(periods=2)
    template = next(t for t in spec['actionCatalog'] if t['templateId'] == 'communicate')
    template['parameters'].update(recipientIds=['buyer'], messageDelayDays='1')
    before = initialize_world(spec)
    obs = build_observation(spec, before, 'producer', 1)
    decision = validate_decision(spec, {'actorId': 'producer', 'observationId': obs['observationId'],
        'intents': [{'templateId': 'communicate', 'parameters': {'text': 'Expansion is an intention only.'}}]},
        'producer', obs, phase='proposal')
    assert build_observation(spec, before, 'buyer', 1)['messages'] == []
    result = resolve_round(spec, before, [decision], 1)
    later = build_observation(spec, result['snapshot'], 'buyer', 2)
    assert len(later['messages']) == 1
    assert later['messages'][0]['terms']['text'] == 'Expansion is an intention only.'
    assert result['snapshot']['metrics']['capacity']['value'] == '4'


@pytest.mark.parametrize('interrupted_manifest', [False, True])
def test_final_commit_recovers_verified_prior_or_split_export(tmp_path, interrupted_manifest):
    from app.services.world_simulation.controller import run_round
    from app.services.world_simulation.results import export_result
    from app.services.world_simulation.artifacts import load_inputs
    _, state, directory = prepare(tmp_path)
    spec, _ = load_inputs(directory)
    with WorldStore(directory / 'world.sqlite3', spec) as store:
        fence = store.acquire_writer('crash')
        policy = ExamplePolicy('investment')
        for _ in range(3):
            run_round(store, policy, fence)
        export_result(directory)
        prior_manifest = (directory / 'world_result_manifest.json').read_bytes()
        run_round(store, policy, fence)
        if interrupted_manifest:
            export_result(directory)
            (directory / 'world_result_manifest.json').write_bytes(prior_manifest)
        store.release_writer(fence)
    assert Service.start(state.simulation_id, root=tmp_path)['runner_status'] == 'completed'
    assert load_frozen_result(directory)['round'] == 4


def test_child_enforces_original_parent_manifest_pin(tmp_path):
    from app.services.world_simulation.artifacts import file_digest, input_manifest
    _, state, directory = prepare(tmp_path)
    original = state.world_input_manifest_sha256
    spec = read_json(directory / 'world_spec.json')
    spec['generationId'] = 'substituted'
    atomic_json(directory / 'world_spec.json', spec)
    atomic_json(directory / 'world_input_manifest.json', input_manifest(spec))
    saved = read_json(directory / 'state.json')
    saved.update(world_generation_id=spec['generationId'], world_spec_sha256=file_digest(directory / 'world_spec.json'),
                 world_input_manifest_sha256=file_digest(directory / 'world_input_manifest.json'))
    atomic_json(directory / 'state.json', saved)
    policy = ExamplePolicy('investment')
    with pytest.raises(WorldError):
        run_child(directory, policy=policy, expected_manifest_sha256=original)
    assert policy.observations == []
    assert not (directory / 'world.sqlite3').exists()


def test_stale_local_process_does_not_hide_resumed_child(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.services.world_simulation import service
    _, state, directory = prepare(tmp_path)
    atomic_json(directory / 'world_run.json', {'simulation_id': state.simulation_id,
        'generation_id': state.world_generation_id, 'runner_status': 'running', 'process_pid': 99})
    monkeypatch.setitem(service._processes, str(directory), SimpleNamespace(pid=88, poll=lambda: 0))
    monkeypatch.setattr(service, '_alive', lambda pid: pid == 99)
    assert Service.status(state.simulation_id, root=tmp_path)['runner_status'] == 'running'
    assert Service.stop(state.simulation_id, root=tmp_path)['runner_status'] == 'stopping'
    assert (directory / 'world_cancel.json').is_file()


def test_rejected_child_cannot_replace_active_writer_status(tmp_path):
    from app.services.world_simulation.artifacts import load_inputs
    _, state, directory = prepare(tmp_path)
    spec, _ = load_inputs(directory)
    atomic_json(directory / 'world_run.json', {'simulation_id': state.simulation_id,
        'generation_id': state.world_generation_id, 'runner_status': 'running', 'process_pid': 1})
    before = (directory / 'world_run.json').read_bytes()
    with WorldStore(directory / 'world.sqlite3', spec) as store:
        fence = store.acquire_writer('actual_owner')
        assert run_child(directory, policy=ExamplePolicy('investment')) == 1
        assert (directory / 'world_run.json').read_bytes() == before
        store.release_writer(fence)


def test_concurrent_preparation_has_one_immutable_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from app.services.world_simulation.artifacts import load_inputs, seal_inputs
    barrier = threading.Barrier(2)
    def attempt(generation):
        spec = example_spec(generation_id=generation)
        barrier.wait()
        try:
            seal_inputs(tmp_path, spec)
            return generation
        except WorldError as error:
            assert error.code == 'generation_exists'
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ['one', 'two']))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert load_inputs(tmp_path)[0]['generationId'] == winners[0]
