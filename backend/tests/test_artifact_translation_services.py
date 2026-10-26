"""Actual source-bound overlay producer/cache readers with a scripted transport only."""
import json
from pathlib import Path

import pytest

from app.services import artifact_translation as at
from test_translation_pairs_integrity import Translator


@pytest.fixture
def simulation(tmp_path, monkeypatch):
    directory = tmp_path / 'sim_translate'
    directory.mkdir()
    from app.config import Config
    monkeypatch.setattr(Config, 'OASIS_SIMULATION_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(tmp_path / 'uploads'))
    llm = Translator()
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: llm)
    return directory, llm


def test_native_inventory_covers_history_decisions_offers_and_digests_without_clipping(simulation):
    directory, llm = simulation
    world = {'world': {'question': 'Will policy change?', 'variables': [
        {'id': 'v1', 'name': 'Capacity', 'value': 25, 'unit': 'MW', 'rationale': 'Public source says so.'}],
        'actors': [{'name': 'NVIDIA', 'commitments': [{'description': 'Deliver 25 MW capacity.', 'status': 'pending'}]}],
        'interactions': [{'id': 'offer1', 'terms': 'Build a plant.'}], 'seed_gaps': [{'note': 'No official measurement.'}]},
        'committed_round': 1, 'headline': 'The committee delays.', 'digest': 'A long digest.'}
    (directory / 'world_state.json').write_text(json.dumps(world))
    (directory / 'world_state_history.jsonl').write_text(json.dumps({'round': 1,
        'narrative': 'A period narrative.', 'decisions': {'rationale': 'Capacity cannot increase yet.'},
        'diff': {'variables_changed': [{'id': 'v1', 'name': 'Capacity pressure'}]}}) + '\n')
    long_digest = 'The committee delayed policy. ' * 85
    (directory / 'world_digest.jsonl').write_text(json.dumps({'round': 1, 'digest': long_digest}) + '\n')
    result = at.simulation_translation('sim_translate', 'zh')
    assert result['status'] == 'available', result
    assert any('narrative' in key for key in result['overlay'])
    assert any('commitments' in key for key in result['overlay'])
    assert any('interactions' in key for key in result['overlay'])
    assert len(next(row['source'] for row in result['translations'] if row['source'] == long_digest)) > 1500
    assert '25 MW' in str(result['overlay'])
    snapshot = (directory / 'world_state.json').read_bytes()
    calls = len(llm.calls)
    assert at.translation_status('simulation', 'sim_translate', 'zh')['status'] == 'available'
    assert len(llm.calls) == calls
    world['world']['question'] = 'Will another policy change?'
    world['world']['actors'] = []
    (directory / 'world_state.json').write_text(json.dumps(world))
    stale = at.translation_status('simulation', 'sim_translate', 'zh')
    assert stale['status'] == 'unavailable' and stale['pending'] == stale['total_candidates']
    assert 'world:question' not in stale['overlay']
    assert not any('commitments' in key for key in stale['overlay'])
    fresh = at.simulation_translation('sim_translate', 'zh')
    assert fresh['status'] == 'available'
    assert len(llm.calls) > calls
    assert snapshot != (directory / 'world_state.json').read_bytes()


def test_visible_context_cache_never_leaks_between_public_actor_analyst_or_round(simulation, monkeypatch):
    directory, llm = simulation
    # Controlled visibility reader; the durable-redesign suite separately exercises real world-v1 readers.
    monkeypatch.setattr(at, '_simulation_projection', lambda sid, context: {
        'text': 'Secret policy statement.' if context.get('view') == 'analyst' else 'Public summary.'})
    context = {'engine': 'world-v1', 'view': 'analyst', 'revision': 'r1', 'round': 1,
               'generation_id': 'g1', 'actor_id': None, 'platform': None}
    result = at.simulation_translation('sim_translate', 'zh', texts=['Secret policy statement.'], context=context)
    assert result['status'] == 'available' and result['context'] == context
    digest = result['request_digest']
    result2 = at.translation_status('simulation', 'sim_translate', 'zh', request_digest=digest, context=context)
    assert result2['translations'] == result['translations']
    assert at.translation_status('simulation', 'sim_translate', 'zh')['translations'] == []
    for field, value in [('view', 'public'), ('round', 2), ('revision', 'r2'), ('generation_id', 'g2')]:
        with pytest.raises(ValueError, match='context does not match'):
            at.translation_status('simulation', 'sim_translate', 'zh', request_digest=digest,
                                  context={**context, field: value})
    assert len(llm.calls) == 2


def test_partial_retry_restart_corrupt_cache_and_changed_source(simulation, monkeypatch):
    directory, llm = simulation
    texts = ['The first statement.', 'The second statement with 20% probability.']
    monkeypatch.setattr(at, '_simulation_projection', lambda sid, context: {'content': [*texts, 'A new statement.']})
    bad = Translator(lambda result, count: json.dumps({key: (value.replace('20%', '99%'))
        for key, value in result.items()}))
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: bad)
    result = at.simulation_translation('sim_translate', 'zh', texts=texts)
    assert result['status'] == 'partial' and result['pending'] == 1 and result['retryable']
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: llm)
    result = at.simulation_translation('sim_translate', 'zh', texts=texts)
    assert result['status'] == 'available' and len(llm.calls) == 2
    path = Path(at._inventory('simulation', 'sim_translate', 'zh', texts=texts)[0])
    data = json.loads(path.read_text())
    first = next(iter(data['entries']))
    data['entries'][first]['text'] = 'tampered 999 MW'
    path.write_text(json.dumps(data))
    status = at.translation_status('simulation', 'sim_translate', 'zh', request_digest=result['request_digest'], context={})
    assert status['status'] == 'partial' and 'tampered' not in str(status['translations'])
    # Restart authority is durable; there is no overlay-local activity registry.
    assert not hasattr(at, '_INFLIGHT')
    assert status['retryable']
    changed = at.simulation_translation('sim_translate', 'zh', texts=[texts[0], 'A new statement.'])
    assert changed['request_digest'] != result['request_digest']
    assert not any(row['source'] == texts[1] for row in changed['translations'])


def test_display_copy_covers_dossier_lists_and_preserves_native_contract(simulation):
    directory, llm = simulation
    document = {'actors': {'central_question': 'Will supply increase?',
        'actors': [{'id': 'actor_id', 'name': 'NVIDIA', 'role': 'The supply provider.'}],
        'situation_brief': {'overview': 'Supply remains constrained.'},
        'hot_topics': ['A capacity bottleneck.'], 'relationships': [{'relationship': 'Supplies chips.'}]},
        'datasets': {'series': [{'series_id': 'GDP_USD', 'label': 'Industrial output', 'unit': 'MW', 'value': '25.5'}]},
        'news_market_context': {'items': [{'title': 'A supply announcement.', 'snippet': 'The plant adds 25 MW.',
            'url': 'https://example.test/a', 'quote': {'yes_bid': .4, 'last_price': .41, 'unit': 'USD_per_contract'},
            'rules_primary': 'Resolves Yes if capacity reaches 25 MW.'}]}}
    before = json.dumps(document, sort_keys=True)
    result = at.display_document(str(directory), 'dossier', 'pipe_test', 'zh', document, generate=True)
    assert result['coverage']['complete'], result
    assert result['display']['actors']['situation_brief']['overview'] != document['actors']['situation_brief']['overview']
    assert result['display']['datasets']['series'][0]['value'] == '25.5'
    assert result['display']['datasets']['series'][0]['series_id'] == 'GDP_USD'
    assert result['display']['news_market_context']['items'][0]['quote'] == document['news_market_context']['items'][0]['quote']
    assert result['display']['news_market_context']['items'][0]['url'] == 'https://example.test/a'
    assert '25 MW' in result['display']['news_market_context']['items'][0]['rules_primary']
    assert json.dumps(document, sort_keys=True) == before
    calls = len(llm.calls)
    assert at.display_document(str(directory), 'dossier', 'pipe_test', 'zh', document)['coverage']['complete']
    assert len(llm.calls) == calls
    document['datasets']['series'][0]['value'] = '30'
    assert not at.display_document(str(directory), 'dossier', 'pipe_test', 'zh', document)['coverage']['complete']
