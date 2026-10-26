"""Retained independent review regressions at real producer/API/cache boundaries."""
import json
import re
import time
from pathlib import Path

import pytest

from app.services.report_agent import ReportManager
from app.services.translation_tools import translate_pairs, valid_pair_translation
from test_artifact_translation_routes import client
from test_report_forecast_localization import _seal_forecast
from test_translation_pairs_integrity import Translator


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    from app.config import Config
    from app.services.translation.scheduler import stop_schedulers
    stop_schedulers()
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(tmp_path / 'uploads'))
    monkeypatch.setattr(Config, 'OASIS_SIMULATION_DATA_DIR', str(tmp_path))
    yield
    stop_schedulers()


@pytest.mark.parametrize('variant', [False, True])
def test_forecast_api_preserves_actual_manager_completeness(client, tmp_path, monkeypatch, variant):
    monkeypatch.setattr(ReportManager, 'REPORTS_DIR', str(tmp_path / 'reports'))
    report_id = 'report_review_complete_' + str(int(variant))
    source = {'headline': 'English conclusion remains.' if variant else '预测总结',
              'scenarios': [{'name': 'Base' if variant else '基准情景', 'probability': .7}],
              'binary_forecasts': []}
    sha = _seal_forecast(report_id, source, '# Outlook\n\n## Decision\n\nCapacity is constrained.\n')
    if variant:
        value = {**source, 'localization': {'lang': 'zh', 'source_forecast_sha256': sha, 'complete': False}}
        with open(ReportManager._get_report_localized_forecast_path(report_id, 'zh'), 'w') as handle:
            json.dump(value, handle)
    _, expected = ReportManager.load_localized_forecast(report_id, 'zh')
    assert expected['complete'] is (not variant), expected
    response = client.get(f'/api/report/{report_id}/forecast?lang=zh')
    assert response.status_code == 200, response.json
    assert response.json['data']['localization'] == expected


def test_raw_quarter_and_year_translation_keeps_native_source_readable():
    source = 'The Q1 2027 forecast remains unchanged.'
    target = '2027年第一季度的预测保持不变。'
    model = Translator(translations={source: target})
    mapping, _ = translate_pairs(model, [('claim', source)], '简体中文')
    assert mapping == {'claim': target}
    assert model.calls[0]['entries'] == {'claim': source}
    assert model.calls[1]['pairs']['claim']['source'] == source
    assert mapping.calls_used == 2
    # Technical identifiers in code have exact parser ownership, without a
    # broad regex that mistakes a localized date for an immutable numeric ID.
    source = 'The `Q12027` forecast remains unchanged.'
    target = '`Q12027`的预测保持不变。'
    model = Translator(translations={source: target})
    assert translate_pairs(model, [('claim', source)], '简体中文')[0] == {'claim': target}
    wrong = Translator(lambda values, count: json.dumps({key: value.replace('Q12027', 'Q12028') for key, value in values.items()}), translations={source: target})
    assert translate_pairs(wrong, [('claim', source)], '简体中文')[0] == {}


def test_cjk_prefix_does_not_admit_substantive_english_sentences():
    source = 'The committee delayed its planned decision. The market expects further restrictions.'
    assert not valid_pair_translation(source, '译文：' + source, '简体中文')
    assert not valid_pair_translation(source, '这是译文。' + source, '简体中文')
    assert valid_pair_translation('NVIDIA', 'NVIDIA', '简体中文')
    assert valid_pair_translation('Federal Reserve', 'Federal Reserve', '简体中文')
    assert valid_pair_translation('The committee delayed its planned decision.', '委员会推迟了原定决策。', '简体中文')
    assert valid_pair_translation('NVIDIA and Federal Reserve are mentioned.',
                                  '文中提到了 NVIDIA 和 Federal Reserve。', '简体中文')


def test_actual_service_does_not_cache_prefixed_english_source_as_available(tmp_path, monkeypatch):
    from app.services import artifact_translation as at
    folder = tmp_path / 'sim_review_mixed'
    folder.mkdir()
    monkeypatch.setattr(at, '_sim_dir', lambda sid: str(folder))
    source = '译文：The committee delayed its planned decision. The market expects further restrictions.'
    monkeypatch.setattr(at, '_simulation_projection', lambda *args: {'content': [source]})
    model = Translator(lambda values, count: json.dumps({key: source for key in values}),
                       translations={source: '委员会推迟了原定决策。市场预计限制将进一步加强。'})
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: model)
    observed = at.simulation_translation('sim_review_mixed', 'zh', texts=[source], context={'view': 'public'})
    assert observed['status'] != 'available', observed
    assert observed['pending'] == 1 and observed['retryable']
    assert len(model.calls) > 0


def test_actual_thousand_string_force_retry_resumes_missing_tail_through_api(client, tmp_path, monkeypatch):
    from app.services import artifact_translation as at
    folder = tmp_path / 'sim_review_large'
    folder.mkdir()
    monkeypatch.setattr(at, '_sim_dir', lambda sid: str(folder) if sid == 'sim_review_large' else None)
    model = Translator()
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: model)
    texts = [f'The policy statement number {index} remains unchanged.' for index in range(1000)]
    monkeypatch.setattr(at, '_simulation_projection', lambda *args: {'content': texts})
    context = {'view': 'public'}
    first = at.simulation_translation('sim_review_large', 'zh', texts=texts, context=context)
    assert first['status'] == 'partial' and first['pending'] == 784, first
    first_calls = len(model.calls)
    assert first_calls == 24
    retained = dict(first['overlay'])
    prior = first
    for expected_pending in (568, 352, 136, 0):
        response = client.post('/api/simulation/sim_review_large/translations/zh?force=1',
                               json={'texts': texts, 'context': context})
        assert response.status_code in (200, 202), response.json
        digest = response.json['data']['request_digest']
        deadline = time.monotonic() + 20
        while True:
            response = client.get('/api/simulation/sim_review_large/translations/zh',
                query_string={'request_digest': digest, 'context': json.dumps(context)})
            assert response.status_code == 200, response.json
            second = response.json['data']
            if second['status'] != 'generating':
                break
            assert time.monotonic() < deadline, second['status']
            time.sleep(.01)
        assert second['pending'] == expected_pending < prior['pending']
        assert all(second['overlay'][key] == value for key, value in retained.items())
        prior = second
    assert second['status'] == 'available' and len(second['overlay']) == 1000
    generations = [payload['entries'] for payload in model.calls if 'entries' in payload]
    keys = [key for payload in generations for key in payload]
    assert len(keys) == len(set(keys)) == 1000, 'accepted prefixes cannot be resubmitted'
    assert len(model.calls) == 112, '56 whole-entry batches each require translation + review'


def test_complete_inventory_force_refresh_preserves_good_text_and_resumes_its_tail(tmp_path, monkeypatch):
    from app.services import artifact_translation as at
    from app.services.translation_tools import translate_pairs as real_translate_pairs
    folder = tmp_path / 'sim_review_force_good'
    folder.mkdir()
    monkeypatch.setattr(at, '_sim_dir', lambda sid: str(folder))
    model = Translator()
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: model)
    texts = [f'A policy statement number {index}.' for index in range(20)]
    monkeypatch.setattr(at, '_simulation_projection', lambda *args: {'content': texts})
    first = at.simulation_translation('sim_review_force_good', 'zh', texts=texts)
    assert first['status'] == 'available'
    retained = dict(first['overlay'])
    def bounded(*args, **kwargs):
        return real_translate_pairs(*args, **kwargs, max_calls=2)
    monkeypatch.setattr(at, 'translate_pairs', bounded)
    model.translations.update({source: '更新' + model.render(source) for source in texts})
    calls = len(model.calls)
    refreshed = at.simulation_translation('sim_review_force_good', 'zh', texts=texts, force=True)
    assert refreshed['pending'] == 0 and refreshed['refresh_pending'] == 2
    assert refreshed['status'] == 'partial' and refreshed['retryable']
    assert set(refreshed['overlay']) == set(retained)
    assert refreshed['overlay'] == retained, 'Partial refresh must preserve the entire previous publication'
    first_refresh_keys = set(model.calls[-2]['entries'])
    done = at.simulation_translation('sim_review_force_good', 'zh', texts=texts, force=True)
    assert done['status'] == 'available' and done['refresh_pending'] == 0
    assert all(value.startswith('更新') for value in done['overlay'].values())
    assert first_refresh_keys.isdisjoint(model.calls[-2]['entries'])
    assert len(model.calls) - calls == 4
    # A failed force attempt cannot erase the last validated translations.
    good = dict(done['overlay'])
    model.mutator = lambda result, count: 'not JSON'
    failed = at.simulation_translation('sim_review_force_good', 'zh', texts=texts, force=True)
    assert failed['overlay'] == good
    assert failed['status'] == 'partial' and failed['refresh_pending'] == 20
    assert failed['issues'] and failed['retryable']


@pytest.mark.parametrize('unit,wrong', [
    ('W', 'kW'), ('kW', 'W'), ('mW', 'MW'), ('MW', 'mW'),
    ('Wh', 'kWh'), ('kWh', 'Wh'), ('mWh', 'MWh'), ('MWh', 'mWh'),
    ('GWh', 'TWh'), ('TWh', 'GWh'),
])
def test_common_si_power_energy_units_are_atomic_and_case_sensitive(unit, wrong):
    source = f'The plant supplies 25 {unit}.'
    model = Translator()
    mapping, _ = translate_pairs(model, [('claim', source)], '简体中文')
    assert f'25 {unit}' in mapping['claim']
    assert model.calls[0]['entries']['claim'] == source, 'Raw values and units must remain readable to the model'
    assert mapping.receipts['claim']['review']['faithful'] is True
    assert not valid_pair_translation(source, f'该设施供应25 {wrong}。', '简体中文')
    assert not valid_pair_translation(f'The plant supplies 25{unit}.',
                                      f'该设施供应25{wrong}。', '简体中文')


def test_shared_fact_unit_pattern_has_safe_boundaries_and_preserves_raw_case():
    from app.services.translation_tools import FACT_UNIT_PATTERN
    assert re.findall(FACT_UNIT_PATTERN, '25kW 2mW 3MW 4kWh 5mWh 6MWh', re.I) == [
        'kW', 'mW', 'MW', 'kWh', 'mWh', 'MWh']
    assert re.findall(FACT_UNIT_PATTERN, 'Watt kWord Whisk mWhistle XkW MW_variable kWh2', re.I) == []
    assert re.findall(FACT_UNIT_PATTERN, '25KW 25kw', re.I) == []


def test_actual_cache_rechecks_si_unit_even_when_tamper_checksum_is_updated(tmp_path, monkeypatch):
    from app.services import artifact_translation as at
    folder = tmp_path / 'sim_review_si_cache'
    folder.mkdir()
    monkeypatch.setattr(at, '_sim_dir', lambda sid: str(folder))
    model = Translator()
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: model)
    source = 'The plant supplies 25 kW.'
    monkeypatch.setattr(at, '_simulation_projection', lambda *args: {'content': [source]})
    result = at.simulation_translation('sim_review_si_cache', 'zh', texts=[source], context={'view': 'public'})
    assert result['status'] == 'available'
    path = Path(at._inventory('simulation', 'sim_review_si_cache', 'zh', texts=[source], context={'view': 'public'})[0])
    cache = json.loads(path.read_text())
    key = next(iter(cache['entries']))
    cache['entries'][key]['text'] = '该设施供应25 W。'
    cache['entries'][key]['text_sha256'] = at._sha(cache['entries'][key]['text'])
    path.write_text(json.dumps(cache))
    calls = len(model.calls)
    read = at.translation_status('simulation', 'sim_review_si_cache', 'zh',
        request_digest=result['request_digest'], context={'view': 'public'})
    assert read['status'] != 'available' and read['pending'] == 1
    assert read['translations'] == [] and read['retryable']
    assert len(model.calls) == calls, 'GET validation must not acquire'
