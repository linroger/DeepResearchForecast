"""Durable upstream modeling budget and compiled downstream consumption."""
import pytest

from app.services.world_simulation.artifacts import read_json
from app.services.world_simulation.contracts import WorldError, clone
from app.services.world_simulation.controller import PolicyResponse
from app.services.world_simulation.examples import example_spec
from app.services.world_simulation.modeler import generate_candidate
from app.services.world_simulation.service import WorldSimulationService

pytestmark = pytest.mark.guarded_runner


def parameters():
    from test_world_lifecycle import raw_model
    model = raw_model()
    return {'research_report': 'All values in this model are synthetic assumptions.',
            'research_generation_id': 'research_synthetic', 'research_engine': 'v3',
            'actor_bundle': None, 'ontology': {}, 'simulation_requirement': 'Study concrete world dynamics.',
            'policy_spec': {'policy': model['policy'], 'forecastEffect': 'no_update',
                            'limits': {'maxTokens': 10000, 'maxCostUsd': '1', 'maxOutputTokens': 512}}}


class Boundary:
    def __init__(self, failures=0):
        self.calls = 0
        self.failures = failures
    def reservation(self, messages):
        return {'tokens': 1000, 'costUsd': '0.1'}
    def decide(self, messages):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError('Synthetic disconnect after dispatch')
        raw = example_spec()
        raw.pop('simulationId')
        raw.pop('generationId')
        raw['forecastEffect'] = 'diagnostic_only'
        raw['limits']['maxCostUsd'] = '1000000'  # Model cannot grant its own budget.
        return PolicyResponse(raw, {'tokens': 500, 'costUsd': '0.05'})


def test_two_attempts_persist_and_compilation_receives_remaining_budget(tmp_path):
    boundary = Boundary(failures=1)
    kwargs = parameters()
    raw, receipt = generate_candidate(tmp_path, transport=boundary, **kwargs)
    assert boundary.calls == 2
    assert receipt['used'] == {'tokens': 1500, 'costUsd': '0.15'}
    assert raw['limits']['maxCostUsd'] == '0.85'
    assert raw['limits']['maxTokens'] == 8500
    assert raw['forecastEffect'] == 'no_update'
    assert raw['policy'] == kwargs['policy_spec']['policy']
    replay = Boundary()
    assert generate_candidate(tmp_path, transport=replay, **kwargs) == (raw, receipt)
    assert replay.calls == 0


def test_unknown_attempts_never_refunded_on_resume(tmp_path):
    kwargs = parameters()
    boundary = Boundary(failures=9)
    with pytest.raises(WorldError) as error:
        generate_candidate(tmp_path, transport=boundary, **kwargs)
    assert error.value.code == 'modeling_attempts_exhausted'
    assert boundary.calls == 2
    resumed = Boundary()
    with pytest.raises(WorldError):
        generate_candidate(tmp_path, transport=resumed, **kwargs)
    assert resumed.calls == 0
    ledger = read_json(tmp_path / 'world_modeling_receipts.json')
    assert all(a['status'] == 'unknown' and a['usage'] is None for a in ledger['attempts'])


def test_modeling_budget_and_source_identity_refuse_before_dispatch(tmp_path):
    kwargs = parameters()
    kwargs['policy_spec']['limits']['maxCostUsd'] = '0.09'
    boundary = Boundary()
    with pytest.raises(WorldError) as error:
        generate_candidate(tmp_path, transport=boundary, **kwargs)
    assert error.value.code == 'modeling_budget_exhausted'
    assert boundary.calls == 0
    kwargs = parameters()
    generate_candidate(tmp_path, transport=boundary, **kwargs)
    changed = clone(kwargs)
    changed['research_report'] += ' Changed source.'
    with pytest.raises(WorldError) as error:
        generate_candidate(tmp_path, transport=Boundary(), **changed)
    assert error.value.code == 'modeling_binding_mismatch'


def test_real_service_automatic_modeler_compiles_and_seals(tmp_path, monkeypatch):
    from app.services.world_simulation import policy
    class FakeModeler(Boundary):
        def __init__(self, spec):
            super().__init__()
        def close(self):
            pass
    monkeypatch.setattr(policy, 'StrictHTTPModeler', FakeModeler)
    prepared = WorldSimulationService.prepare_model('sim_auto', raw_spec=None, root=tmp_path, **parameters())
    assert prepared['spec']['forecastEffect'] == 'no_update'
    assert prepared['spec']['sourceBindings']['modelPreparation']['used']['costUsd'] == '0.05'
    assert prepared['spec']['limits']['maxCostUsd'] == '0.95'
    assert prepared['spec']['sourceBindings']['researchGenerationId'] == 'research_synthetic'
    assert (tmp_path / 'sim_auto/world_input_manifest.json').is_file()


def test_exact_unicode_candidate_is_identical_on_fresh_and_resumed_compilation(tmp_path):
    from app.services.world_simulation.compiler import compile_world_spec
    class UnicodeBoundary(Boundary):
        def decide(self, messages):
            response = super().decide(messages)
            response.decision['actors'][0]['name'] = 'Cafe\u0301'
            return response
    kwargs = parameters()
    first = generate_candidate(tmp_path, transport=UnicodeBoundary(), **kwargs)
    replay = generate_candidate(tmp_path, transport=Boundary(), **kwargs)
    assert first == replay
    assert first[0]['actors'][0]['name'] == 'Cafe\u0301'
    compile_kwargs = {key: kwargs[key] for key in ('research_report', 'research_generation_id', 'research_engine', 'actor_bundle')}
    errors = []
    for candidate in (first[0], replay[0]):
        with pytest.raises(WorldError) as error:
            compile_world_spec(candidate, simulation_id='sim_unicode', generation_id='gen_unicode', **compile_kwargs)
        errors.append(error.value.code)
    assert errors == ['unsafe_model_text', 'unsafe_model_text']


def test_reservation_parent_directory_fsync_failure_prevents_dispatch(tmp_path, monkeypatch):
    import os
    import stat
    from app.services.world_simulation import artifacts
    original = os.fsync
    observed = []
    def fsync(fd):
        kind = 'directory' if stat.S_ISDIR(os.fstat(fd).st_mode) else 'file'
        observed.append(kind)
        if kind == 'directory':
            raise OSError('synthetic directory durability failure')
        return original(fd)
    monkeypatch.setattr(artifacts.os, 'fsync', fsync)
    boundary = Boundary()
    with pytest.raises(OSError):
        generate_candidate(tmp_path, transport=boundary, **parameters())
    assert observed == ['file', 'directory']
    assert boundary.calls == 0
