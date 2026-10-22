"""Published-body repair must include forecast localization, without regenerating Markdown."""
from copy import deepcopy
import hashlib
import json
import threading
import time

import pytest

from app.services.report_agent import ReportAgent, ReportManager
from test_artifact_translation_routes import CombinedTranslator
from test_forecast_feedback_sdk import published


@pytest.mark.parametrize('claims_complete', [False, True])
def test_plain_post_repairs_forecast_and_display_with_immutable_body(published, monkeypatch, claims_complete):
    from app.api import report as api
    report, folder, client = published['report'], published['folder'], published['client']
    made = ReportManager.generate_translation_variant(report.report_id, 'zh', llm_client=CombinedTranslator())
    assert made['available'] and ReportManager.is_publishable(report.report_id, 'zh'), made
    # Make display already complete: the old API's display-only job then exits
    # without ever repairing this independently incomplete dashboard sidecar.
    monkeypatch.setattr('app.utils.llm_client.LLMClient', CombinedTranslator)
    with client.application.app_context():
        assert api._report_display(report, 'zh', generate=True)['translation_status']['complete']
    source = ReportManager.load_structured_forecast(report.report_id)
    partial = deepcopy(source)
    source_sha = hashlib.sha256((folder / 'forecast.json').read_bytes()).hexdigest()
    partial['localization'] = {'lang': 'zh', 'source_forecast_sha256': source_sha,
                               'complete': claims_complete}
    (folder / 'forecast.zh.json').write_text(json.dumps(partial))
    _, info = ReportManager.load_localized_forecast(report.report_id, 'zh')
    assert info['localized'] is True and info['complete'] is False
    assert ReportManager.translation_status(report.report_id, 'zh')['available'] is True
    immutable = {name: (folder / name).read_bytes() for name in (
        'full_report.md', 'full_report.zh.md', 'final_audit.json', 'final_audit.zh.json',
        'forecast.json', 'meta.json', 'citations.json', 'citations.zh.json') if (folder / name).is_file()}
    queued = []
    monkeypatch.setattr(api, '_launch_translation_thread', queued.append)
    def forbidden(*args, **kwargs):
        raise AssertionError('an audited-body structured retry must never regenerate Markdown')
    monkeypatch.setattr(ReportManager, 'generate_translation_variant', classmethod(forbidden))
    monkeypatch.setattr(ReportAgent, '_generate_bilingual_report', forbidden)
    entered, release = threading.Event(), threading.Event()
    class HoldingTranslator(CombinedTranslator):
        def __init__(self):
            super().__init__()
            self.calls = 0
        def hold(self):
            self.calls += 1
            entered.set()
            assert release.wait(5), 'test must release controlled forecast translator'
        def chat(self, *args, **kwargs):
            self.hold()
            return super().chat(*args, **kwargs)
        def chat_json(self, *args, **kwargs):
            self.hold()
            return super().chat_json(*args, **kwargs)
    model = HoldingTranslator()
    factories = []
    def factory():
        factories.append(True)
        return model
    monkeypatch.setattr('app.utils.llm_client.LLMClient', factory)
    base = f'/api/report/{report.report_id}'
    started = client.post(base + '/translations/zh')
    assert started.status_code == 200 and started.json['data']['available'] is True, started.json
    assert len(queued) == 1, 'forecast-only missing strings must start a structured repair job'
    duplicate = client.post(base + '/translations/zh')
    assert duplicate.status_code == 200 and len(queued) == 1
    job = threading.Thread(target=queued[0])
    job.start()
    try:
        assert entered.wait(3), 'real forecast localization producer was not called'
        before = (len(factories), model.calls)
        pending = client.get(base + '/forecast?lang=zh').json['data']
        assert pending['localization']['complete'] is False
        assert pending['structured_translation']['status'] == 'generating'
        assert pending['structured_translation']['complete'] is False
        body_status = client.get(base + '/translations/zh/status').json['data']
        assert body_status['available'] is True
        assert body_status['structured_translation']['status'] == 'generating'
        assert (len(factories), model.calls) == before, 'GET must never acquire translation work'
    finally:
        release.set()
        job.join(timeout=10)
    assert not job.is_alive()
    final = client.get(base + '/forecast?lang=zh').json['data']
    assert final['localization']['complete'] is True, final
    assert final['structured_translation']['complete'] is True
    assert final['structured_translation']['status'] == 'available'
    assert final['forecast']['scenarios'][0]['probability'] == .7
    assert final['forecast']['headline'] != source['headline']
    assert len(factories) == 1
    assert all((folder / name).read_bytes() == value for name, value in immutable.items())
    assert ReportManager.is_publishable(report.report_id, 'zh')
    # A repeated plain request reuses both complete projections and starts no job.
    assert client.post(base + '/translations/zh').status_code == 200
    assert len(queued) == 1


def test_structured_refusal_is_partial_retriable_and_never_regenerates_body(published, monkeypatch):
    from app.api import report as api
    report, folder, client = published['report'], published['folder'], published['client']
    assert ReportManager.generate_translation_variant(report.report_id, 'zh', llm_client=CombinedTranslator())['available']
    monkeypatch.setattr('app.utils.llm_client.LLMClient', CombinedTranslator)
    with client.application.app_context():
        api._report_display(report, 'zh', generate=True)
    source = ReportManager.load_structured_forecast(report.report_id)
    source['localization'] = {'lang': 'zh', 'complete': False,
        'source_forecast_sha256': hashlib.sha256((folder / 'forecast.json').read_bytes()).hexdigest()}
    (folder / 'forecast.zh.json').write_text(json.dumps(source))
    unchanged = {name: (folder / name).read_bytes() for name in (
        'full_report.md', 'full_report.zh.md', 'final_audit.json', 'final_audit.zh.json', 'forecast.json', 'meta.json')}
    queued = []
    monkeypatch.setattr(api, '_launch_translation_thread', queued.append)
    def forbidden(*args, **kwargs):
        raise AssertionError('structured-only repair must not regenerate the audited body')
    monkeypatch.setattr(ReportManager, 'generate_translation_variant', classmethod(forbidden))
    model = CombinedTranslator()
    model.fail = True
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: model)
    base = f'/api/report/{report.report_id}'
    assert client.post(base + '/translations/zh').status_code == 200
    assert len(queued) == 1
    queued[0]()
    partial = client.get(base + '/forecast?lang=zh').json['data']
    assert partial['localization']['complete'] is False
    assert partial['structured_translation']['status'] == 'partial'
    assert partial['structured_translation']['retryable']
    assert partial['structured_translation']['issues']
    assert client.get(base + '/translations/zh/status').json['data']['available'] is True
    assert all((folder / name).read_bytes() == value for name, value in unchanged.items())
    model.fail = False
    assert client.post(base + '/translations/zh').status_code == 200
    assert len(queued) == 2
    queued[1]()
    final = client.get(base + '/forecast?lang=zh').json['data']
    assert final['localization']['complete'] is True
    assert final['structured_translation']['complete'] is True
    assert all((folder / name).read_bytes() == value for name, value in unchanged.items())


def test_source_change_during_forecast_repair_is_not_read_as_current(published, monkeypatch):
    from app.api import report as api
    report, folder, client = published['report'], published['folder'], published['client']
    assert ReportManager.generate_translation_variant(report.report_id, 'zh', llm_client=CombinedTranslator())['available']
    source = ReportManager.load_structured_forecast(report.report_id)
    source_sha = hashlib.sha256((folder / 'forecast.json').read_bytes()).hexdigest()
    partial = {**source, 'localization': {'lang': 'zh', 'complete': False, 'source_forecast_sha256': source_sha}}
    (folder / 'forecast.zh.json').write_text(json.dumps(partial))
    stable = {name: (folder / name).read_bytes() for name in (
        'full_report.md', 'full_report.zh.md', 'final_audit.json', 'final_audit.zh.json', 'meta.json')}
    queued = []
    monkeypatch.setattr(api, '_launch_translation_thread', queued.append)
    changed = dict(source)
    changed['headline'] = 'Different source generation after admission.'
    replacement = json.dumps(changed).encode()
    model = CombinedTranslator()
    model.after_call = lambda: (folder / 'forecast.json').write_bytes(replacement)
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: model)
    base = f'/api/report/{report.report_id}'
    assert client.post(base + '/translations/zh').status_code == 200
    assert len(queued) == 1
    queued[0]()
    assert (folder / 'forecast.json').read_bytes() == replacement
    assert all((folder / name).read_bytes() == value for name, value in stable.items())
    # The canonical mutation did not acquire a new seal. Both real reader and
    # API refuse to present this job's old-source sidecar as the current forecast.
    current, info = ReportManager.load_localized_forecast(report.report_id, 'zh')
    assert current is None and info['localized'] is False
    assert client.get(base + '/forecast?lang=zh').status_code == 409
    assert (report.report_id, 'zh') not in api._report_display_inflight


def _prepare_inline_repair(published, monkeypatch):
    from app.api import report as api
    report, folder, client = published['report'], published['folder'], published['client']
    assert ReportManager.generate_translation_variant(report.report_id, 'zh', llm_client=CombinedTranslator())['available']
    monkeypatch.setattr('app.utils.llm_client.LLMClient', CombinedTranslator)
    with client.application.app_context():
        assert api._report_display(report, 'zh', generate=True)['translation_status']['complete']
    source = ReportManager.load_structured_forecast(report.report_id)
    source['localization'] = {'lang': 'zh', 'complete': False,
        'source_forecast_sha256': hashlib.sha256((folder / 'forecast.json').read_bytes()).hexdigest()}
    (folder / 'forecast.zh.json').write_text(json.dumps(source))
    def forbidden(*args, **kwargs):
        raise AssertionError('inline structured repair cannot generate Markdown')
    monkeypatch.setattr(ReportManager, 'generate_translation_variant', classmethod(forbidden))
    monkeypatch.setattr(ReportAgent, '_generate_bilingual_report', forbidden)
    stable = {name: (folder / name).read_bytes() for name in (
        'full_report.md', 'full_report.zh.md', 'final_audit.json', 'final_audit.zh.json', 'forecast.json', 'meta.json')}
    return api, report, folder, client, stable


def test_direct_inline_forecast_repair_is_generating_and_plain_post_joins(published, monkeypatch):
    api, report, folder, client, stable = _prepare_inline_repair(published, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    class Held(CombinedTranslator):
        def hold(self):
            entered.set()
            assert release.wait(5)
        def chat(self, *args, **kwargs):
            self.hold()
            return super().chat(*args, **kwargs)
        def chat_json(self, *args, **kwargs):
            self.hold()
            return super().chat_json(*args, **kwargs)
    model = Held()
    factories = []
    def factory():
        factories.append(True)
        return model
    monkeypatch.setattr('app.utils.llm_client.LLMClient', factory)
    queued, errors = [], []
    monkeypatch.setattr(api, '_launch_translation_thread', queued.append)
    def run():
        try:
            api._repair_report_structured(report, 'zh')
        except BaseException as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    base = f'/api/report/{report.report_id}'
    try:
        assert entered.wait(3)
        data = client.get(base + '/forecast?lang=zh').json['data']
        assert data['structured_translation']['status'] == 'generating'
        assert data['structured_translation']['complete'] is False
        duplicate = client.post(base + '/translations/zh')
        assert duplicate.status_code == 200 and duplicate.json['data']['available'] is True
        assert duplicate.json['data']['structured_translation']['status'] == 'generating'
        assert queued == [] and len(factories) == 1
    finally:
        release.set()
        thread.join(timeout=10)
    assert not thread.is_alive() and errors == []
    assert (report.report_id, 'zh') not in api._report_display_inflight
    assert client.get(base + '/forecast?lang=zh').json['data']['structured_translation']['complete'] is True
    assert all((folder / name).read_bytes() == value for name, value in stable.items())


def test_inline_repair_failure_clears_activity_and_preserves_good_body(published, monkeypatch):
    api, report, folder, client, stable = _prepare_inline_repair(published, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    factories, errors = [], []
    def failure():
        factories.append(True)
        entered.set()
        assert release.wait(5)
        raise RuntimeError('controlled inline constructor failure')
    monkeypatch.setattr('app.utils.llm_client.LLMClient', failure)
    def run():
        try:
            api._repair_report_structured(report, 'zh')
        except BaseException as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    base = f'/api/report/{report.report_id}'
    try:
        assert entered.wait(3)
        during = client.get(base + '/forecast?lang=zh').json['data']
        assert during['structured_translation']['status'] == 'generating'
        assert len(factories) == 1
    finally:
        release.set()
        thread.join(timeout=10)
    assert not thread.is_alive()
    assert len(errors) == 1 and str(errors[0]) == 'controlled inline constructor failure'
    assert (report.report_id, 'zh') not in api._report_display_inflight
    after = client.get(base + '/forecast?lang=zh').json['data']
    assert after['structured_translation']['status'] == 'partial'
    assert after['structured_translation']['retryable']
    assert client.get(base + '/translations/zh/status').json['data']['available'] is True
    assert all((folder / name).read_bytes() == value for name, value in stable.items())
