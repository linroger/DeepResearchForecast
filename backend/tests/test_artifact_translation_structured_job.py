"""Published-body structured repair through the real durable operation authority.

Historical inline/thread scenarios now enter the registered scheduler handler.
Only dispatch timing and model transport are controlled; source/publication,
SQLite ownership, adapters, retry semantics and public readers remain real.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading

import pytest

from app.config import Config
from app.services.report_agent import ReportAgent, ReportManager
from app.services.translation import scheduler
from app.services.translation.store import Store, database_path
from test_artifact_translation_routes import CombinedTranslator
from test_forecast_feedback_sdk import published
from test_report_durable_routes import run_queued_report


@pytest.fixture(autouse=True)
def durable_boundary(tmp_path, monkeypatch):
    scheduler.stop_schedulers()
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(tmp_path / 'uploads'))
    monkeypatch.setattr(scheduler, 'start_scheduler', lambda: None)
    from app.api import report as api
    api.register_translation_handler()
    yield
    scheduler.stop_schedulers()


def _prepare_repair(published, monkeypatch, *, claims_complete=False):
    from app.api import report as api
    report, folder, client = published['report'], published['folder'], published['client']
    # Model the actual historical state: an admitted body with no completed
    # forecast job. Damaging a completed job's sidecar would correctly reuse its
    # durable accepted fields and never reach the held/refusing model below.
    with monkeypatch.context() as setup:
        setup.setattr(ReportAgent, '_start_dashboard_localization', lambda *a: None)
        made = ReportManager.generate_translation_variant(report.report_id, 'zh', llm_client=CombinedTranslator())
    assert made['available'] and ReportManager.is_publishable(report.report_id, 'zh'), made
    snapshot = ReportManager.resolve_translation(report.report_id, 'zh')
    assert 'forecast.json' not in snapshot.assets
    monkeypatch.setattr('app.utils.llm_client.LLMClient', CombinedTranslator)
    with client.application.app_context():
        assert api._report_display(report, 'zh', generate=True)['translation_status']['complete']
    source = ReportManager.load_structured_forecast(report.report_id)
    partial = deepcopy(source)
    partial['localization'] = {'lang': 'zh', 'complete': claims_complete,
        'source_forecast_sha256': hashlib.sha256((folder / 'forecast.json').read_bytes()).hexdigest()}
    (folder / 'forecast.zh.json').write_text(json.dumps(partial))
    _, info = ReportManager.load_localized_forecast(report.report_id, 'zh')
    assert info['localized'] and not info['complete']
    stable = {path: path.read_bytes() for path in Path(snapshot.path).iterdir() if path.is_file()}
    stable.update({folder / name: (folder / name).read_bytes() for name in (
        'full_report.md', 'final_audit.json', 'forecast.json', 'meta.json', 'citations.json')})
    def forbidden(*args, **kwargs):
        raise AssertionError('structured repair must not regenerate admitted Markdown')
    monkeypatch.setattr(ReportManager, 'generate_translation_variant', classmethod(forbidden))
    monkeypatch.setattr(ReportAgent, '_generate_bilingual_report', forbidden)
    return api, report, folder, client, snapshot, source, stable


def _unchanged(stable, *, except_paths=()):
    assert all(path.read_bytes() == value for path, value in stable.items() if path not in except_paths)


def _task_count():
    with Store(database_path(), read_only=True) as store:
        return store.db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]


def _dispatch_thread():
    outcomes, errors = [], []
    def dispatch():
        try:
            outcomes.append(run_queued_report())
        except BaseException as exc:
            errors.append(exc)
    thread = threading.Thread(target=dispatch)
    thread.start()
    return thread, outcomes, errors


def _holding_model(entered, release):
    class HoldingTranslator(CombinedTranslator):
        def __init__(self):
            super().__init__()
            self.calls = 0
        def hold(self):
            self.calls += 1
            entered.set()
            assert release.wait(10), 'test must release controlled forecast translator'
        def chat(self, *args, **kwargs):
            self.hold()
            return super().chat(*args, **kwargs)
        def chat_json(self, *args, **kwargs):
            self.hold()
            return super().chat_json(*args, **kwargs)
    return HoldingTranslator()


@pytest.mark.parametrize('claims_complete', [False, True])
def test_plain_post_repairs_forecast_and_display_with_immutable_body(published, monkeypatch, claims_complete):
    api, report, folder, client, snapshot, source, stable = _prepare_repair(
        published, monkeypatch, claims_complete=claims_complete)
    entered, release = threading.Event(), threading.Event()
    model = _holding_model(entered, release)
    factories = []
    def factory():
        factories.append(True)
        return model
    monkeypatch.setattr('app.utils.llm_client.LLMClient', factory)
    base = f'/api/report/{report.report_id}'
    started = client.post(base + '/translations/zh')
    assert started.status_code == 200 and started.json['data']['available'], started.json
    job_id = started.json['data']['translation_job']['job_id']
    assert scheduler.status(job_id)['identity']['scope'] == 'structured'
    duplicate = client.post(base + '/translations/zh')
    assert duplicate.status_code == 200 and duplicate.json['data']['task_id'] == job_id
    assert _task_count() == 1
    thread, outcomes, errors = _dispatch_thread()
    try:
        assert entered.wait(5), 'real forecast localization producer was not called'
        before = (len(factories), model.calls)
        pending = client.get(base + '/forecast?lang=zh').json['data']
        assert not pending['localization']['complete']
        assert pending['structured_translation']['status'] == 'generating'
        assert not pending['structured_translation']['complete']
        body = client.get(base + '/translations/zh/status').json['data']
        assert body['available'] and body['translation_job']['job_state'] == 'running'
        assert (len(factories), model.calls) == before, 'GET must not acquire work'
        _unchanged(stable)
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive() and errors == [] and outcomes[0]['job_state'] == 'completed', outcomes
    final = client.get(base + '/forecast?lang=zh').json['data']
    assert final['localization']['complete'] and final['structured_translation']['complete'], final
    assert final['structured_translation']['status'] == 'available'
    assert final['forecast']['scenarios'][0]['probability'] == .7
    assert final['forecast']['headline'] != source['headline']
    assert len(factories) == 1
    _unchanged(stable)
    current = ReportManager.resolve_translation(report.report_id, 'zh')
    assert current.markdown == snapshot.markdown and current.audit == snapshot.audit
    assert ReportManager.is_publishable(report.report_id, 'zh')
    assert client.post(base + '/translations/zh').status_code == 200
    assert _task_count() == 1 and len(factories) == 1


def test_structured_refusal_is_partial_retriable_and_never_regenerates_body(published, monkeypatch):
    _, report, _, client, snapshot, _, stable = _prepare_repair(published, monkeypatch)
    model = CombinedTranslator()
    model.fail = True
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: model)
    base = f'/api/report/{report.report_id}'
    response = client.post(base + '/translations/zh')
    assert response.status_code == 200
    job_id = response.json['data']['task_id']
    failed = run_queued_report()
    assert failed['job_id'] == job_id and failed['job_state'] == 'failed'
    partial = client.get(base + '/forecast?lang=zh').json['data']
    assert not partial['localization']['complete']
    assert partial['structured_translation']['status'] == 'partial'
    assert partial['structured_translation']['retryable'] and partial['structured_translation']['issues']
    assert client.get(base + '/translations/zh/status').json['data']['available']
    assert ReportManager.resolve_translation(report.report_id, 'zh').generation == snapshot.generation
    _unchanged(stable)
    model.fail = False
    retry = client.post(base + '/translations/zh')
    assert retry.status_code == 200 and retry.json['data']['task_id'] == job_id
    assert _task_count() == 1 and run_queued_report()['job_state'] == 'completed'
    final = client.get(base + '/forecast?lang=zh').json['data']
    assert final['localization']['complete'] and final['structured_translation']['complete']
    _unchanged(stable)


def test_source_change_during_forecast_repair_is_not_read_as_current(published, monkeypatch):
    _, report, folder, client, _, source, stable = _prepare_repair(published, monkeypatch)
    changed = {**source, 'headline': 'Different source generation after admission.'}
    replacement = json.dumps(changed).encode()
    model = CombinedTranslator()
    model.after_call = lambda: (folder / 'forecast.json').write_bytes(replacement)
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: model)
    base = f'/api/report/{report.report_id}'
    assert client.post(base + '/translations/zh').status_code == 200
    failed = run_queued_report()
    assert failed['job_state'] == 'failed' and failed['error']['code'] == 'stale_artifact', failed
    assert (folder / 'forecast.json').read_bytes() == replacement
    _unchanged(stable, except_paths=(folder / 'forecast.json',))
    current, info = ReportManager.load_localized_forecast(report.report_id, 'zh')
    assert current is None and not info['localized']
    assert client.get(base + '/forecast?lang=zh').status_code == 409
    assert scheduler.status(failed['job_id'])['actions']['stop'] is False


def test_direct_inline_forecast_repair_is_generating_and_plain_post_joins(published, monkeypatch):
    """The former direct caller now enqueues the same registered operation as POST."""
    api, report, _, client, _, _, stable = _prepare_repair(published, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    model = _holding_model(entered, release)
    factories = []
    def factory():
        factories.append(True)
        return model
    monkeypatch.setattr('app.utils.llm_client.LLMClient', factory)
    job = api.enqueue_report_translation(report.report_id, 'zh', mode='structured')
    thread, outcomes, errors = _dispatch_thread()
    base = f'/api/report/{report.report_id}'
    try:
        assert entered.wait(5)
        data = client.get(base + '/forecast?lang=zh').json['data']
        assert data['structured_translation']['status'] == 'generating'
        assert not data['structured_translation']['complete']
        duplicate = client.post(base + '/translations/zh')
        assert duplicate.status_code == 200 and duplicate.json['data']['available']
        assert duplicate.json['data']['task_id'] == job['job_id']
        assert _task_count() == 1 and len(factories) == 1
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive() and not errors and outcomes[0]['job_state'] == 'completed', outcomes
    assert not hasattr(api, '_report_display_inflight')
    assert client.get(base + '/forecast?lang=zh').json['data']['structured_translation']['complete']
    _unchanged(stable)


def test_inline_repair_failure_clears_activity_and_preserves_good_body(published, monkeypatch):
    """Constructor failure becomes a durable retryable outcome, not stranded activity."""
    api, report, _, client, snapshot, _, stable = _prepare_repair(published, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    factories = []
    def failure():
        factories.append(True)
        entered.set()
        assert release.wait(10)
        raise RuntimeError('controlled inline constructor failure')
    monkeypatch.setattr('app.utils.llm_client.LLMClient', failure)
    job = api.enqueue_report_translation(report.report_id, 'zh', mode='structured')
    thread, outcomes, errors = _dispatch_thread()
    base = f'/api/report/{report.report_id}'
    try:
        assert entered.wait(5)
        data = client.get(base + '/forecast?lang=zh').json['data']
        assert data['structured_translation']['status'] == 'generating' and len(factories) == 1
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive() and not errors
    failed = scheduler.status(job['job_id'])
    assert failed['job_state'] == 'failed' and failed['error']['code'] == 'provider_failure'
    assert failed['actions']['retry'] and not failed['actions']['stop']
    assert 'controlled inline constructor failure' not in json.dumps(failed)
    after = client.get(base + '/forecast?lang=zh').json['data']
    assert after['structured_translation']['status'] == 'partial' and after['structured_translation']['retryable']
    assert client.get(base + '/translations/zh/status').json['data']['available']
    assert ReportManager.resolve_translation(report.report_id, 'zh').generation == snapshot.generation
    assert len(factories) == 1
    _unchanged(stable)
