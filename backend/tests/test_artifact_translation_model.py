"""Current raw-model receipts through native cache/display/research readers."""
import copy
import json
from pathlib import Path

import pytest

from app.services import artifact_translation as at
from app.services.model_translation import ENGINE, translate_document
from test_translation_pairs_integrity import Translator


@pytest.fixture
def model_cache(tmp_path, monkeypatch):
    directory = tmp_path / 'sim_model'
    directory.mkdir()
    from app.config import Config
    monkeypatch.setattr(Config, 'OASIS_SIMULATION_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(tmp_path / 'uploads'))
    # Explicit synthetic visibility authority; real engine readers have separate integration cases.
    monkeypatch.setattr(at, '_simulation_projection', lambda sid, context: {'content': [
        'The budget is $3.7 billion by November 10, 2026.', 'The plant supplies 25 kW.', 'A policy statement.']})
    model = Translator()
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: model)
    return directory, model


def test_model_review_receipt_admits_equivalent_formats_and_reuses_only_exact_requested_text(model_cache):
    directory, model = model_cache
    source = 'The budget is $3.7 billion by November 10, 2026.'
    target = '截至2026年11月10日，预算为37亿美元。'
    model.translations[source] = target
    context = {'view': 'analyst', 'round': 1, 'revision': 'r1', 'generation_id': 'g1'}
    first = at.simulation_translation('sim_model', 'zh', texts=[source], context=context)
    assert first['status'] == 'available' and first['translations'][0]['text'] == target
    assert first['translation_engine'] == ENGINE and first['schema_version'] == 4
    assert first['model_calls'] == len(model.calls) == 2
    path = Path(at._inventory('simulation', 'sim_model', 'zh', texts=[source], context=context)[0])
    entry = next(iter(json.loads(path.read_text())['entries'].values()))
    assert entry['receipt']['review'] == {'faithful': True, 'complete': True, 'target_language': True, 'issues': []}
    # A changed live context has a new durable scope; admission is source- and
    # revision-bound even if its natural-language text remains identical.
    next_context = {**context, 'round': 2, 'revision': 'r2'}
    next_view = at.simulation_translation('sim_model', 'zh', texts=[source], context=next_context)
    assert next_view['request_digest'] != first['request_digest']
    assert next_view['translations'] == first['translations'] and len(model.calls) == 4
    assert at.translation_status('simulation', 'sim_model', 'zh')['translations'] == []
    with pytest.raises(ValueError, match='context does not match'):
        at.translation_status('simulation', 'sim_model', 'zh', request_digest=first['request_digest'], context=next_context)


@pytest.mark.parametrize('damage', ['missing_receipt', 'review_false', 'changed_target', 'wrong_context', 'wrong_engine'])
def test_cache_reader_rechecks_actual_receipt_without_acquisition(model_cache, damage):
    directory, model = model_cache
    context = {'view': 'public'}
    result = at.simulation_translation('sim_model', 'zh', texts=['The plant supplies 25 kW.'], context=context)
    path = Path(at._inventory('simulation', 'sim_model', 'zh', texts=['The plant supplies 25 kW.'], context=context)[0])
    cache = json.loads(path.read_text())
    entry = next(iter(cache['entries'].values()))
    if damage == 'missing_receipt':
        entry.pop('receipt')
    elif damage == 'review_false':
        entry['receipt']['review']['faithful'] = False
    elif damage == 'changed_target':
        entry['text'] = '该设施供应25 W。'
        entry['text_sha256'] = at._sha(entry['text'])
    elif damage == 'wrong_context':
        entry['receipt']['context_sha256'] = at._sha('different artifact kind')
    else:
        entry['receipt']['engine'] = 'historical-unreviewed'
    path.write_text(json.dumps(cache))
    calls = len(model.calls)
    status = at.translation_status('simulation', 'sim_model', 'zh', request_digest=result['request_digest'], context=context)
    assert status['pending'] == 1 and status['translations'] == [] and status['retryable']
    assert len(model.calls) == calls


def test_version_three_pool_cannot_supply_unreviewed_text(model_cache):
    directory, model = model_cache
    source = 'A policy statement.'
    target = '旧的未审查缓存。'
    pool = directory / 'translations' / 'zh' / '.validated-texts.json'
    pool.parent.mkdir(parents=True)
    pool.write_text(json.dumps({'schema_version': 3, 'ref_id': 'sim_model', 'target_lang': 'zh',
        'entries': {at._sha(source): {'sha': at._sha(source), 'text': target, 'text_sha256': at._sha(target)}}}))
    result = at.simulation_translation('sim_model', 'zh', texts=[source])
    assert result['status'] == 'available' and len(model.calls) == 2
    assert result['translations'][0]['text'] != target
    stored = json.loads(pool.read_text())
    assert stored['schema_version'] == 3, 'Historical unscoped pools remain untouched and unread for reuse'


def test_typed_fact_values_are_never_submitted_as_prose_and_display_remains_a_copy(model_cache):
    directory, model = model_cache
    document = {'datasets': {'series': [{'series': 'GDP_USD', 'series_id': 'GDP_USD',
        'title': 'Economic activity', 'label': 'Industrial output', 'geography': 'United States',
        'frequency': 'Quarterly', 'latest': '1e-3', 'value': '25.5', 'unit': 'kW', 'csv': 'GDP.csv',
        'provenance': {'fiscal_period': 'FY2026', 'calendar': 'fiscal'},
        'kiqs': ['Q1_2027'], 'url': 'https://example.test/2026'}]},
        'viz_manifest': {'charts': [{'chart': 'probability_cdf', 'title': 'Capacity distribution',
            'data': {'x': ['1e-3'], 'y': ['0.4']}, 'unit': 'USD_per_contract'}]},
        'details': {'description': 'Expected supply constraint.', 'quantity': '25.5', 'method': 'simulation_v1'},
        'parameters': {'capacity': '25', 'unit': 'kW', 'rationale': 'A planning estimate.'},
        'news_market_context': {'items': [{'title': 'A public announcement.',
            'rules_primary': 'Resolves Yes if capacity reaches 25 kW.',
            'quote': {'yes_bid': .4, 'last_price': .41, 'unit': 'USD_per_contract'}, 'outcome': 'Yes'}]}}
    before = copy.deepcopy(document)
    result = at.display_document(str(directory), 'dossier', 'pipe_model', 'zh', document, generate=True)
    assert result['coverage']['complete'], result
    submitted = [value for payload in model.calls if 'entries' in payload for value in payload['entries'].values()]
    for code in ['GDP_USD', 'Quarterly', '1e-3', '25.5', 'kW', 'GDP.csv', 'FY2026', 'fiscal',
                 'Q1_2027', 'probability_cdf', 'simulation_v1', 'USD_per_contract', 'Yes']:
        assert code not in submitted
    assert 'Economic activity' in submitted and 'United States' in submitted
    display = result['display']
    for key in ('series', 'series_id', 'frequency', 'latest', 'value', 'unit', 'csv', 'provenance', 'kiqs', 'url'):
        assert display['datasets']['series'][0][key] == document['datasets']['series'][0][key]
    assert display['viz_manifest']['charts'][0]['data'] == document['viz_manifest']['charts'][0]['data']
    assert display['details']['quantity'] == '25.5' and display['details']['method'] == 'simulation_v1'
    assert document == before


@pytest.mark.parametrize('proof_mode', ['valid', 'missing', 'bad_review', 'wrong_context', 'legacy'])
def test_research_reader_requires_new_document_proof_but_keeps_legacy_audit_contract(tmp_path, monkeypatch, proof_mode):
    from app.api import research as api
    directory = tmp_path / 'handoff'
    directory.mkdir()
    source = '# Policy outlook\n\nThe budget is $3.7 billion.\n'
    model = Translator(translations={'# Policy outlook': '# 政策展望', 'The budget is $3.7 billion.': '预算为37亿美元。'})
    target, proof = translate_document(model, source, 'zh')
    # Use the real current producer to construct complete proof for the fixture.
    assert proof['complete']
    src, variant, audit_path, status_path, _ = map(Path, api._research_report_paths(str(directory), 'zh'))
    src.write_text(source)
    variant.write_text(target)
    audit = {'hard_passed': True, 'translator_version': ENGINE, 'model_translation': proof}
    if proof_mode == 'missing':
        audit.pop('model_translation')
    elif proof_mode == 'bad_review':
        audit['model_translation']['sections'][0]['receipt']['review']['complete'] = False
    elif proof_mode == 'wrong_context':
        audit['model_translation']['context'] = 'Wrong outline'
    elif proof_mode == 'legacy':
        audit = {'hard_passed': True, 'translator_version': 'legacy-audited/v2'}
    audit_path.write_text(json.dumps(audit))
    status_path.write_text(json.dumps({'status': 'available', 'schema_version': 2, 'target_lang': 'zh',
        'source_sha256': api._research_source_sha(src), 'markdown_sha256': api._research_source_sha(variant),
        'audit_sha256': api._research_source_sha(audit_path)}))
    def forbidden():
        raise AssertionError('A research reader must not acquire any client')
    monkeypatch.setattr('app.utils.llm_client.LLMClient', forbidden)
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    status, markdown = api._research_variant(str(directory), 'zh')
    if proof_mode in {'valid', 'legacy'}:
        assert status['status'] == 'available' and markdown == target
    else:
        assert status['status'] == 'failed' and markdown is None
    assert before == {path.name: path.read_bytes() for path in directory.iterdir()}


@pytest.mark.parametrize('endpoint', ['A1', 'NVIDIA'])
def test_native_research_relationship_endpoints_stay_canonical_and_scalar_basis_is_translated(
    tmp_path, monkeypatch, endpoint,
):
    from test_model_translation_workflow import ScriptedModel, _client, _wait, TARGET
    import test_model_translation_workflow as workflow
    from app.api import research as api
    # Reproduce the review's native actors/research fixture without replacing
    # the actual worker, display collector, cache, review, or API reader.
    from test_model_translation_workflow import SOURCE
    handoff = tmp_path / 'relationship-handoff'
    handoff.mkdir()
    (handoff / 'research_report.md').write_text(SOURCE)
    source = 'The budget constrains available options.'
    target = '预算限制了可行的选择。'
    actors = {'central_question': 'Will capacity increase?',
        'actors': [{'id': 'A1', 'name': 'NVIDIA', 'role': 'Supplies infrastructure.'},
                   {'id': 'A2', 'name': 'Congress'}],
        'relationships': [{'source': endpoint, 'target': 'A2', 'type': 'cooperative', 'basis': source}]}
    path = handoff / 'actors.json'
    path.write_text(json.dumps(actors))
    original = path.read_bytes()
    monkeypatch.setattr(api.PipelineManager, 'resolve_handoff_dir', lambda pid: str(handoff))
    for before, after in [(source, target), ('cooperative', '合作'), ('Congress', '国会'), ('A1', '参与方甲'), ('A2', '参与方乙')]:
        monkeypatch.setitem(workflow._TEXT, before, after)
    model = ScriptedModel()
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: model)
    client = _client()
    url = '/api/research/pipe_relation_projection/dossier/translations/zh'
    assert client.post(url).status_code == 202
    data = _wait(client, url)
    assert data['available'] and data['report'] == TARGET, data
    assert data['structured_translation']['complete'], data
    row = data['dossier']['actors']['relationships'][0]
    assert row == {'source': endpoint, 'target': 'A2', 'type': '合作', 'basis': target}
    assert path.read_bytes() == original
    submitted = {key: value for event in model.trace if event['stage'] in {'translate', 'repair'}
                 for key, value in event['payload']['entries'].items()}
    assert source in submitted.values()
    assert not any(key.endswith(('/source', '/target')) for key in submitted)
    calls = len(model.trace)
    assert client.get(url).json['data']['dossier']['actors']['relationships'][0] == row
    assert len(model.trace) == calls


def test_relation_typed_basis_is_copied_and_source_credit_is_schema_scoped(model_cache):
    directory, model = model_cache
    explanation = 'The budget constrains available options.'
    credit = 'Official economic outlook'
    model.translations.update({explanation: '预算限制了可行的选择。', credit: '官方经济展望',
                               'A1': '参与方甲', 'A2': '参与方乙'})
    basis = {'source_ref': 'S1', 'refs': ['A1', 'A2'],
             'provenance': {'source': 'S1', 'description': 'Canonical evidence metadata.'}}
    document = {'actors': {'relationships': [
        {'source': 'A1', 'target': 'A2', 'type': 'cooperative', 'basis': explanation},
        {'source': 'A2', 'target': 'A1', 'type': 'opposes', 'basis': basis}]},
        'datasets': {'series': [{'series_id': 'GDP_USD', 'source': credit, 'unit': 'USD'}]},
        'viz_manifest': {'charts': [{'id': 'chart_1', 'source': credit, 'caption': 'Supply trend.'}]},
        'details': {'source': 'S1', 'target': 'A2', 'basis': basis},
        'untyped': {'source': 'A1'}}
    original = copy.deepcopy(document)
    result = at.display_document(str(directory), 'dossier', 'pipe_relation_basis', 'zh', document, generate=True)
    assert result['coverage']['complete'], result
    display = result['display']
    assert display['actors']['relationships'][0]['basis'] == '预算限制了可行的选择。'
    assert display['actors']['relationships'][1]['basis'] == basis
    for actual, source in zip(display['actors']['relationships'], original['actors']['relationships']):
        assert actual['source'] == source['source'] and actual['target'] == source['target']
    assert display['datasets']['series'][0]['source'] == '官方经济展望'
    assert display['viz_manifest']['charts'][0]['source'] == '官方经济展望'
    assert display['details'] == original['details'] and display['untyped'] == original['untyped']
    submitted = {key: text for payload in model.calls if 'entries' in payload for key, text in payload['entries'].items()}
    assert explanation in submitted.values() and credit in submitted.values()
    assert 'A1' not in submitted.values() and 'A2' not in submitted.values()
    assert not any('/basis/' in key for key in submitted)
    assert document == original
