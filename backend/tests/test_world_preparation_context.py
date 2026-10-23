"""Official carrier -> shared preparation -> native modeler/compiler/controller.

The SDK HTTP transport is synthetic; source projection, request construction,
compilation, immutable artifacts, journal and observations are production code.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

from app.services.research_preparation import compile_preparation_context
from app.services.world_simulation.artifacts import atomic_json, input_manifest, load_inputs, read_json
from app.services.world_simulation.compiler import build_compiler_messages, compile_world_spec
from app.services.world_simulation.contracts import WorldError, canonical_json, initial_snapshot
from app.services.world_simulation.modeler import generate_candidate
from app.services.world_simulation.observations import build_observation
from app.services.world_simulation.service import WorldSimulationService, run_child
from test_world_compiler import ASSUMPTION, REPORT, producer, source_bundle
from test_world_lifecycle import raw_model

pytestmark = pytest.mark.guarded_runner


@pytest.fixture(autouse=True)
def record_sources():
    guard = sys.modules.get('main_offline_guard')
    if guard:
        root = Path(__file__).resolve().parents[1] / 'app/services'
        for path in [root / 'research_preparation.py', root / 'actor_context.py',
                     *[root / 'world_simulation' / (name + '.py') for name in
                       ('compiler', 'modeler', 'service', 'artifacts', 'contracts', 'observations', 'policy')]]:
            guard.source_hashes.setdefault(str(path), hashlib.sha256(path.read_bytes()).hexdigest())


def official_data():
    return {'series': [{
        'series': 'fred:GDP', 'provider': 'fred', 'provider_name': 'FRED',
        'title': 'US gross domestic product', 'geography': 'US', 'units': 'Billions of Dollars',
        'frequency': 'Q', 'seasonal_adjustment': 'SAAR',
        'retrieved_at': '2029-10-20T12:00:00Z', 'source_url': 'https://fixture.invalid/series/GDP',
        'source_refs': ['official_gdp'], 'provenance': {'release_id': 'gdp_fixture', 'resolution_safe': True},
        'observations': [{'date': '2029-04-01', 'value': 29900.5, 'flag': 'observed'},
                         {'date': '2029-07-01', 'value': 30000.25, 'flag': 'preliminary'},
                         {'date': '2030-01-01', 'value': 32000.0, 'flag': 'projection'}],
    }]}


def bundle(*, actors=None, report=REPORT, generation='research1', official=None, packs=None,
           question='How might domestic output evolve?'):
    return compile_preparation_context(question=question, research_report=report,
        actors=source_bundle() if actors is None else actors,
        official_data=official_data() if official is None else official,
        actor_context_packs=packs, source_binding={'research_generation_id': generation}, as_of='2029-10-31')


def reference(prepared, row=None):
    row = row or prepared['quantitative']['observations'][0]
    return {'kind': 'official_observation', 'refs': [{'observationId': row['id'],
        'bundleSha256': prepared['content_sha256'], 'target': 'value', 'unit': row['unit'], 'period': row['period']}]}


def proposal(prepared):
    raw = raw_model()
    assert prepared['quantitative']['observations'], prepared['gaps']
    row = prepared['quantitative']['observations'][0]
    raw['initialState']['metrics']['output'] = {'kind': 'quantity', 'unit': row['unit'],
        'value': str(row['value']), 'basis': reference(prepared), 'visibility': {'kind': 'public'}}
    raw['periods'].append({'start': '2030-01-02T00:00:00Z', 'end': '2030-01-03T00:00:00Z'})
    raw['scheduledEvents'] = [{'eventId': 'scenario_change', 'kind': 'metric_delta',
        'at': '2030-01-01T12:00:00Z', 'parameters': {'targetMetric': 'output', 'delta': '3'},
        'visibility': {'kind': 'public'}, 'basis': deepcopy(ASSUMPTION)}]
    return raw


def inputs(prepared):
    raw = proposal(prepared)
    return {'research_report': REPORT, 'research_generation_id': 'research1', 'research_engine': 'v3',
            'actor_bundle': source_bundle(), 'preparation_context': prepared, 'ontology': {},
            'simulation_requirement': 'Study domestic output with explicit scenario mechanics.',
            'policy_spec': {'policy': raw['policy'], 'limits': {**raw['limits'], 'maxTokens': 250000}}}


def compile_model(raw, prepared):
    return compile_world_spec(raw, simulation_id='native_fixture', generation_id='world_fixture',
        research_report=REPORT, research_generation_id='research1', research_engine='v3',
        actor_bundle=source_bundle(), preparation_context=prepared)


def pin_state(root, sim_id, result):
    atomic_json(root / sim_id / 'state.json', {'simulation_engine': 'world-v1',
        'world_input_manifest_sha256': result['manifest_sha256'],
        'world_generation_id': result['spec']['generationId'], 'world_spec_sha256': result['manifest']['specSha256']})


@pytest.fixture
def transport(monkeypatch):
    import httpx
    from openai import OpenAI
    from app.config import Config
    from app.services.world_simulation.policy import StrictHTTPModeler, StrictHTTPPolicy

    sent = []
    control = {'candidate': None}
    monkeypatch.setattr(Config, 'LLM_PROVIDER', 'openai')
    monkeypatch.setattr(Config, 'resolve_endpoint', classmethod(
        lambda cls, provider, model=None: ('https://fixture.invalid/v1', 'fixture-model-v1')))
    monkeypatch.setattr('platform.processor', lambda: 'fixture')

    def dispatch(request):
        body = json.loads(request.content)
        sent.append(body)
        payload = json.loads(body['messages'][1]['content'])
        result = (deepcopy(control['candidate']) if 'actorId' not in payload else
                  {'intents': [], 'stateUpdates': {'beliefs': ['Output may change under the stated scenario.']}})
        return httpx.Response(200, json={'id': 'native_fixture', 'object': 'chat.completion', 'created': 0,
            'model': 'fixture-model-v1', 'choices': [{'index': 0, 'finish_reason': 'stop',
                'message': {'role': 'assistant', 'content': json.dumps(result)}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 40, 'total_tokens': 140}})

    def client(self, config):
        http = httpx.Client(transport=httpx.MockTransport(dispatch), follow_redirects=False, trust_env=False)
        return OpenAI(api_key='synthetic-test-key', base_url=self.base_url, http_client=http, max_retries=0)

    monkeypatch.setattr(StrictHTTPModeler, '_build_client', client)
    monkeypatch.setattr(StrictHTTPPolicy, '_build_client', client)
    return control, sent


def test_official_to_real_modeler_compiler_controller_and_restart(tmp_path, transport):
    prepared = bundle()
    control, sent = transport
    control['candidate'] = proposal(prepared)
    result = WorldSimulationService.prepare_model('native_fixture', raw_spec=None, root=tmp_path, **inputs(prepared))
    pin_state(tmp_path, 'native_fixture', result)
    modeler = json.loads(sent[0]['messages'][1]['content'])['preparationContext']
    assert modeler['contentSha256'] == prepared['content_sha256']
    assert '30000.25' in modeler['modelerContext'] and 'Billions of Dollars' in modeler['modelerContext']
    assert 'projection' in modeler['modelerContext']
    assert run_child(tmp_path / 'native_fixture') == 0
    observations = [json.loads(call['messages'][1]['content']) for call in sent[1:]]
    assert [o['world']['metrics']['output']['value'] for o in observations] == ['30000.25', '30003.25']
    for observation in observations:
        metric = observation['world']['metrics']['output']
        original = metric['baseline']['observation']
        assert original['value'] == '30000.25' and original['unit'] == 'Billions of Dollars'
        assert original['period'] == '2029-07-01' and original['period_end'] == '2029-09-30'
        assert original['status'] == 'preliminary' and original['provider'] == 'fred' and original['series'] == 'fred:GDP'
        assert original['source_refs'] == ['official_gdp'] and original['provenance']['release_id'] == 'gdp_fixture'
        assert 'preparationSha256' not in metric['baseline'] and 'researchGenerationId' not in metric['baseline']
        assert 'bundleSha256' not in metric['basis']['refs'][0]
        assert metric['valueSemantics']['kind'] == 'simulated_state'
        assert metric['valueSemantics']['baselineAppliesTo'] == 'initial_value'
        assert 'secret loss' not in canonical_json(observation)
    assert observations[1]['privateState']['beliefs'][0]['basis']['kind'] == 'simulation_event'
    assert observations[1]['actor']['beliefs'] == []
    assert 'initial research-bound beliefs' in sent[1]['messages'][0]['content']
    spec, manifest = load_inputs(tmp_path / 'native_fixture', expected_manifest_sha256=result['manifest_sha256'])
    assert manifest['sourceBindings']['preparationContext']['contentSha256'] == prepared['content_sha256']
    assert spec == result['spec']
    before = len(sent)
    replay, receipt = generate_candidate(tmp_path / 'native_fixture', **inputs(prepared))
    assert len(sent) == before and receipt == spec['sourceBindings']['modelPreparation']
    assert replay['initialState']['metrics']['output']['basis'] == reference(prepared)


@pytest.mark.parametrize('mutation', ['bundle_hash', 'ref_hash', 'id', 'unit', 'record_unit', 'period',
                                      'value', 'generation', 'report', 'actors', 'guidance', 'target', 'future_start'])
def test_present_invalid_proof_or_mapping_fails_closed(mutation):
    prepared = bundle()
    raw = proposal(prepared)
    ref = raw['initialState']['metrics']['output']['basis']['refs'][0]
    if mutation == 'bundle_hash':
        prepared['content_sha256'] = '0' * 64
    elif mutation == 'ref_hash':
        ref['bundleSha256'] = '0' * 64
    elif mutation == 'id':
        ref['observationId'] = 'q_missing'
    elif mutation in {'unit', 'period', 'target'}:
        ref[mutation] = {'unit': 'USD', 'period': '2029-04-01', 'target': 'balance'}[mutation]
    elif mutation == 'record_unit':
        raw['initialState']['metrics']['output']['unit'] = 'USD'
    elif mutation == 'value':
        raw['initialState']['metrics']['output']['value'] = '30000.26'
    elif mutation == 'generation':
        prepared = bundle(generation='other_research')
        raw = proposal(prepared)
    elif mutation == 'report':
        prepared = bundle(report=REPORT + ' Changed.')
        raw = proposal(prepared)
    elif mutation == 'actors':
        actors = source_bundle()
        actors['extra_context'] = 'changed'
        prepared = bundle(actors=actors)
        raw = proposal(prepared)
    elif mutation == 'guidance':
        row = prepared['quantitative']['guidance'][0]
        raw['initialState']['metrics']['output'].update(value=str(row['value']), basis=reference(prepared, row))
    else:
        raw['periods'] = [{'start': '2029-07-01T00:00:00Z', 'end': '2029-08-01T00:00:00Z'}]
        raw['scheduledEvents'] = []
    with pytest.raises(WorldError):
        compile_model(raw, prepared)


@pytest.mark.parametrize('consumer', ['account', 'action', 'event', 'flow', 'actor'])
def test_official_observation_cannot_establish_other_parameters(consumer):
    prepared = bundle()
    raw = proposal(prepared)
    basis = reference(prepared)
    if consumer == 'account':
        raw['initialState']['accounts']['cash'] = {'ownerId': 'a', 'unit': 'USD', 'balance': '30000.25',
            'basis': basis, 'visibility': {'kind': 'public'}}
    elif consumer == 'action':
        raw['actionCatalog'][0]['basis'] = basis
    elif consumer == 'event':
        raw['scheduledEvents'][0]['basis'] = basis
    elif consumer == 'actor':
        raw['actors'][0]['basis'] = basis
    else:
        raw['flows'] = [{'flowId': 'not_a_flow_rate', 'ratePerDay': '30000.25',
                        'basis': basis, 'visibility': {'kind': 'public'}}]
    with pytest.raises(WorldError):
        compile_model(raw, prepared)


def test_missing_bundle_does_not_accept_official_reference():
    prepared = bundle()
    with pytest.raises(WorldError):
        compile_model(proposal(prepared), None)


def test_future_context_cannot_leak_through_unseeded_actor_projection():
    prepared = bundle()
    raw = raw_model()
    raw['periods'] = [{'start': '2029-07-01T00:00:00Z', 'end': '2029-08-01T00:00:00Z'}]
    with pytest.raises(WorldError) as error:
        compile_model(raw, prepared)
    assert error.value.code == 'preparation_period_mismatch'


def test_baseline_diagnostic_precision_is_not_an_executable_quantity_limit():
    official = official_data()
    official['series'][0]['observations'] = [
        {'date': '2029-04-01', 'value': 0.1, 'flag': 'observed'},
        {'date': '2029-07-01', 'value': 0.3, 'flag': 'observed'}]
    prepared = bundle(official=official)
    spec = compile_model(proposal(prepared), prepared)
    metric = spec['initialState']['metrics']['output']
    assert metric['value'] == '0.3'
    assert metric['baseline']['observation']['diagnostic_summary']['change_native_units'] == '0.19999999999999998'
    raw = proposal(prepared)
    raw['initialState']['metrics']['output']['value'] = '0.123456789012345'
    with pytest.raises(WorldError) as error:
        compile_model(raw, prepared)
    assert error.value.code == 'invalid_quantity'


def test_public_gap_diagnostic_cannot_disclose_denied_research():
    actors = source_bundle()
    actors['quantitative_facts'] = [{'metric': 'The analyst projects a secret loss.', 'value': 'bad',
        'unit': 'USD', 'source': 'fixture', 'as_of_date': '2029-10-31', 'period_end': '2029-09-30',
        'visibility': 'public', 'value_type': 'actual'}]
    prepared = bundle(actors=actors)
    spec = compile_world_spec(raw_model(), simulation_id='gap_fixture', generation_id='world_gap',
        research_report=REPORT, research_generation_id='research1', research_engine='v3',
        actor_bundle=actors, preparation_context=prepared)
    observation = build_observation(spec, initial_snapshot(spec), 'a', 1)
    assert 'secret loss' not in canonical_json(observation)
    assert 'quantitative_not_admitted' in observation['actor']['researchContext']


@pytest.mark.parametrize('question', ['', 'What changes?\n{Ordinary scenario description}'])
def test_renderer_header_accepts_empty_or_multiline_questions(question):
    prepared = bundle(question=question)
    spec = compile_model(proposal(prepared), prepared)
    observation = build_observation(spec, initial_snapshot(spec), 'a', 1)
    assert 'Question: ' + question in observation['actor']['researchContext']


def test_modeler_only_research_change_cannot_change_actor_observation():
    from test_world_compiler import span
    original = bundle()
    first_spec = compile_model(proposal(original), original)
    actors = source_bundle()
    private_text = 'The analyst expects a concealed contraction.'
    report = REPORT.replace('The analyst projects a secret loss.', private_text)
    actors['actors'][0]['claims'][1].update(claim=private_text, report_ref=span(private_text, report))
    changed = bundle(actors=actors, report=report)
    second_spec = compile_world_spec(proposal(changed), simulation_id='native_fixture', generation_id='world_fixture',
        research_report=report, research_generation_id='research1', research_engine='v3',
        actor_bundle=actors, preparation_context=changed)
    assert original['content_sha256'] != changed['content_sha256']
    first = build_observation(first_spec, initial_snapshot(first_spec), 'a', 1)
    second = build_observation(second_spec, initial_snapshot(second_spec), 'a', 1)
    assert first == second
    assert original['content_sha256'] not in canonical_json(first)


@pytest.mark.parametrize('audience', ['public', 'actors', 'analyst'])
@pytest.mark.parametrize('location', ['omitted_series', 'history_only'])
def test_complete_baseline_metadata_obeys_visibility_even_when_prompt_omits_it(audience, location):
    from app.services.research_preparation import render_preparation_context
    official = official_data()
    provenance = official['series'][0]['provenance']
    denied = 'The analyst projects a secret loss.'
    if location == 'omitted_series':
        # Individually bounded strings make the complete row exceed the prompt
        # budget without triggering an unrelated per-string size rejection.
        provenance['details'] = {f'field_{n}': 'Additional measurement metadata. ' * 10 for n in range(50)}
        provenance['cited_text'] = denied
    else:
        provenance['periods'] = {'2029-04-01': {'start': '2029-04-01', 'end': '2029-06-30', 'note': denied}}
    prepared = bundle(official=official)
    rendered = render_preparation_context(prepared, audience='actor', actor_id='a', max_chars=12000)
    assert denied not in rendered  # The independent baseline path is the test target.
    raw = proposal(prepared)
    raw['initialState']['metrics']['output']['visibility'] = (
        {'kind': 'actors', 'actorIds': ['a']} if audience == 'actors' else {'kind': audience})
    if audience == 'analyst':
        spec = compile_model(raw, prepared)
        assert denied in canonical_json(spec['initialState']['metrics']['output']['baseline'])
        assert 'output' not in build_observation(spec, initial_snapshot(spec), 'a', 1)['world']['metrics']
    else:
        with pytest.raises(WorldError) as error:
            compile_model(raw, prepared)
        assert error.value.code == 'forbidden_actor_evidence'


@pytest.mark.parametrize('mutation', ['missing_pin', 'null_pin', 'null_hash', 'short_hash', 'null_sources', 'missing_context'])
def test_hybrid_spec_cannot_downgrade_or_disable_required_proof(tmp_path, mutation):
    prepared = bundle()
    spec = compile_model(proposal(prepared), prepared)
    if mutation == 'missing_pin':
        del spec['sourceBindings']['preparationContext']
    elif mutation == 'null_pin':
        spec['sourceBindings']['preparationContext'] = None
    elif mutation == 'missing_context':
        del spec['researchContext']
    else:
        key, value = {'null_hash': ('contentSha256', None), 'short_hash': ('contentSha256', 'abc'),
                      'null_sources': ('source', None)}[mutation]
        spec['sourceBindings']['preparationContext'][key] = value
    # A self-consistent outer manifest cannot bypass the inner contract. These
    # are new synthetic artifacts, never an existing saved generation.
    atomic_json(tmp_path / 'world_spec.json', spec)
    atomic_json(tmp_path / 'world_input_manifest.json', input_manifest(spec))
    with pytest.raises(WorldError) as error:
        load_inputs(tmp_path)
    assert error.value.code == 'invalid_preparation_context'


@pytest.mark.parametrize('mutation', ['bundle', 'manifest', 'missing_bundle', 'missing_manifest'])
def test_current_artifact_tamper_and_missing_proof_fail_closed(tmp_path, mutation):
    prepared = bundle()
    result = WorldSimulationService.prepare_model('native_fixture', raw_spec=proposal(prepared), root=tmp_path, **inputs(prepared))
    directory = tmp_path / 'native_fixture'
    name = 'research_preparation_manifest.json' if 'manifest' in mutation else 'research_preparation.json'
    if mutation.startswith('missing'):
        (directory / name).unlink()
    else:
        value = read_json(directory / name) if 'manifest' in mutation else json.loads((directory / name).read_text())
        value['content_sha256'] = '0' * 64
        (directory / name).write_text(json.dumps(value))
    with pytest.raises(WorldError, match='preparation'):
        load_inputs(directory, expected_manifest_sha256=result['manifest_sha256'])


def test_fork_preserves_exact_bundle_and_owner_artifacts(tmp_path):
    prepared = bundle()
    parent = WorldSimulationService.prepare_model('native_fixture', raw_spec=proposal(prepared), root=tmp_path, **inputs(prepared))
    pin_state(tmp_path, 'native_fixture', parent)
    def hashes():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (tmp_path / 'native_fixture').iterdir() if p.is_file()}
    before = hashes()
    child = WorldSimulationService.fork('native_fixture', 'native_fork', root=tmp_path, seed=77)
    assert hashes() == before
    assert child['spec']['sourceBindings'] == parent['spec']['sourceBindings']
    assert child['spec']['generationId'] != parent['spec']['generationId']
    loaded, _ = load_inputs(tmp_path / 'native_fork', expected_manifest_sha256=child['manifest_sha256'])
    assert loaded['initialState'] == parent['spec']['initialState']
    assert (tmp_path / 'native_fork/research_preparation.json').read_bytes() == (tmp_path / 'native_fixture/research_preparation.json').read_bytes()


def test_modeler_reuse_binds_bundle_even_when_projection_is_unchanged(tmp_path, transport):
    prepared = bundle()
    control, sent = transport
    control['candidate'] = proposal(prepared)
    generate_candidate(tmp_path, **inputs(prepared))
    # The caller's generation metadata changes while all visible rows stay the same.
    from app.services.actor_context import canonical_json_sha256
    changed = deepcopy(prepared)
    changed['source']['source_binding']['revision'] = 2
    changed['source']['source_binding_sha256'] = canonical_json_sha256(changed['source']['source_binding'])
    changed['content_sha256'] = canonical_json_sha256({k: v for k, v in changed.items() if k != 'content_sha256'})
    before = len(sent)
    with pytest.raises(WorldError) as error:
        generate_candidate(tmp_path, **inputs(changed))
    assert error.value.code == 'modeling_binding_mismatch' and len(sent) == before


def test_no_bundle_compatibility_retains_no_native_context(tmp_path):
    raw = raw_model()
    result = WorldSimulationService.prepare_model('old_fixture', raw_spec=raw, root=tmp_path,
        research_report=REPORT, research_generation_id='research1', research_engine='v3', actor_bundle=source_bundle())
    spec, _ = load_inputs(tmp_path / 'old_fixture')
    assert 'preparationContext' not in result['manifest']['sourceBindings']
    assert 'researchContext' not in build_observation(spec, initial_snapshot(spec), 'a', 1)['actor']


def test_sealed_qualitative_modeler_actor_public_denial_boundaries(tmp_path, monkeypatch, producer):
    from app.services.actor_context import build_actor_context_artifacts
    import test_pipeline_actor_contract as fixture
    from test_world_compiler import sealed_proposal
    original = fixture._producer_raw_claim
    def claim(name, dimension):
        row = original(name, dimension)
        row['visibility'] = 'public'
        if dimension == 'motivations':
            row['visibility'] = 'actor_known'
        if dimension == 'knowledge_state':
            row['actor_knows'] = False
        return row
    monkeypatch.setattr(fixture, '_producer_raw_claim', claim)
    source = fixture._write_producer_valid_bundle(tmp_path, producer, monkeypatch)
    # Give the actual context selector actor-relevant sections, then ask the
    # real source producer to bind the revised report (never fabricate seals).
    source['report'] += '\n\n## Acme\nAcme participates in the market order.\n\n## Beta\nBeta participates in the market order.'
    producer_root = tmp_path / 'producer'
    (producer_root / 'research_report.md').write_text(source['report'])
    log = producer.ProgressLog(producer_root / 'native_reseal.log')
    try:
        producer.persist_final_actor_intelligence_contract(producer_root,
            report=source['report'], dossier=source['dossier'], meta={'thread_id': 'research-actor-thread'},
            plog=log, required=True)
    finally:
        log.close()
    source['actors'] = json.loads((producer_root / 'actors.json').read_text())
    source['sources'] = json.loads((producer_root / 'sources.json').read_text())
    actors = source['actors']
    packs, _, _ = build_actor_context_artifacts(str(tmp_path / 'packs'), actors, actors['actors'], source['report'])
    prepared = bundle(actors=actors, report=source['report'], packs=packs)
    native_bundle = {key: source[key] for key in ('actors', 'sources', 'dossier')}
    kwargs = {'research_report': source['report'], 'research_generation_id': 'research1',
              'research_engine': 'legacy', 'actor_bundle': native_bundle, 'preparation_context': prepared}
    raw = sealed_proposal(source)
    spec = compile_world_spec(raw, simulation_id='qualitative_fixture', generation_id='world_qualitative', **kwargs)
    modeler = json.loads(build_compiler_messages(**kwargs)[1]['content'])
    actor = actors['actors'][0]
    other = actors['actors'][1]
    own_goal = actor['intelligence']['dimensions']['motivations'][0]['claim']
    other_goal = other['intelligence']['dimensions']['motivations'][0]['claim']
    denied = actor['intelligence']['dimensions']['knowledge_state'][0]['claim']
    modeler_context = modeler['preparationContext']['modelerContext']
    assert denied in modeler_context and other_goal in modeler_context
    observation = build_observation(spec, initial_snapshot(spec), actor['actor_id'], 1)
    context = observation['actor']['researchContext']
    assert own_goal in context and other_goal not in context and denied not in context
    assert 'Omitted rows:' in context
    raw['actors'][0]['beliefs'] = [{'text': denied, 'basis': deepcopy(ASSUMPTION)}]
    with pytest.raises(WorldError) as error:
        compile_world_spec(raw, simulation_id='qualitative_fixture', generation_id='world_qualitative', **kwargs)
    assert error.value.code == 'forbidden_actor_evidence'
