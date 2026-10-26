"""Actual Flask display readers and translation persistence without external calls."""
import hashlib
import json
import threading
import time
from pathlib import Path

import pytest

from app.services import artifact_translation as at
from test_translation_pairs_integrity import Translator
from test_translation_dates import GlmLikeTranslator
from test_forecast_feedback_sdk import published  # real audit/publication fixture


class CombinedTranslator(GlmLikeTranslator):
    def __init__(self):
        super().__init__()
        self.pairs = Translator()
        self.fail = False
        self.after_call = None

    def chat(self, messages, **kwargs):
        if self.fail:
            raise RuntimeError('scripted provider unavailable')
        if self.after_call:
            callback, self.after_call = self.after_call, None
            callback()
        return super().chat(messages, **kwargs)


@pytest.fixture
def client():
    from app import create_app
    app = create_app()
    app.config['TESTING'] = True
    return app.test_client()


def wait_for(client, url):
    for _ in range(200):
        response = client.get(url)
        assert response.status_code == 200, response.json
        data = response.json['data']
        if data['status'] != 'generating':
            return data
        time.sleep(.01)
    raise AssertionError('translation did not complete within test bound')


def test_simulation_actual_post_poll_contexts_and_incremental_growth(client, tmp_path, monkeypatch):
    directory = tmp_path / 'sim_http'
    directory.mkdir()
    from app.config import Config
    from app.services.translation.scheduler import stop_schedulers
    stop_schedulers()
    monkeypatch.setattr(Config, 'OASIS_SIMULATION_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(tmp_path / 'uploads'))
    # This route scenario isolates transport/selection growth. Real world-v1
    # authority is exercised separately in test_overlay_durable_redesign.
    monkeypatch.setattr(at, '_simulation_projection', lambda sid, context: {'content': [
        'A private decision with 25 MW.', 'The next decision.'] if context.get('view') == 'actor' else []})
    llm = Translator()
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: llm)
    context = {'engine': 'world-v1', 'view': 'actor', 'actor_id': 'actor_A', 'round': 2,
               'revision': 'v2', 'generation_id': 'gen1'}
    base = '/api/simulation/sim_http/translations/zh'
    result = client.post(base, json={'texts': ['A private decision with 25 MW.'], 'context': context})
    assert result.status_code in (200, 202), result.json
    data = result.json['data']
    query = '?request_digest=' + data['request_digest'] + '&context=' + __import__('urllib.parse', fromlist=['quote']).quote(json.dumps(context))
    data = wait_for(client, base + query)
    assert data['context'] == context and data['simulation_id'] == 'sim_http'
    assert data['status'] == 'available' and '25 MW' in data['translations'][0]['text']
    calls = len(llm.calls)
    assert client.get(base).json['data']['translations'] == []
    assert client.get(base + '?request_digest=' + data['request_digest']).status_code == 400
    result = client.post(base, json={'texts': ['A private decision with 25 MW.', 'The next decision.'], 'context': context})
    newer = result.json['data']
    query2 = '?request_digest=' + newer['request_digest'] + '&context=' + __import__('urllib.parse', fromlist=['quote']).quote(json.dumps(context))
    assert wait_for(client, base + query2)['status'] == 'available'
    assert len(llm.calls) == calls + 2
    assert sum('25 MW' in str(payload.get('entries', {})) for payload in llm.calls) == 1
    assert client.post(base, json={'texts': [12]}).status_code == 400
    assert client.post('/api/simulation/sim_absent/translations/zh', json={'texts': ['Text']}).status_code == 404
    assert client.get('/api/simulation/sim_http/translations/fr').status_code == 400

    stop_schedulers()


def _dispatch_research(api):
    """Step the registered handler under a real SQLite claim and ownership epoch."""
    from app.services.translation import scheduler
    from app.services.translation.contracts import safe_error
    from app.services.translation.store import Store, database_path
    with Store(database_path()) as store:
        epoch = store.elect()
        claim = store.claim_task(epoch, [api._RESEARCH_TRANSLATION_OPERATION])
        assert claim is not None
        job_id, kind, payload = claim
        token = scheduler._task_id.set(job_id)
        epoch_token = scheduler._task_epoch.set(epoch)
        try:
            result = scheduler._handlers[kind](payload)
        except Exception as exc:
            store.finish_task(job_id, epoch, error=safe_error(exc, 'operation'))
        else:
            store.finish_task(job_id, epoch, result=result)
        finally:
            scheduler._task_id.reset(token)
            scheduler._task_epoch.reset(epoch_token)
        return store.task(job_id)


@pytest.fixture
def report_scheduler(tmp_path, monkeypatch):
    from test_report_durable_routes import queue_only_scheduler
    queue_only_scheduler(monkeypatch, tmp_path / 'report-uploads')


@pytest.fixture
def research(tmp_path, monkeypatch, client):
    from app.api import research as api
    from app.config import Config
    from app.services.translation import scheduler
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(tmp_path / 'research-uploads'))
    monkeypatch.setattr(scheduler, 'start_scheduler', lambda: None)
    api.register_translation_handler()
    handoff = tmp_path / 'handoff'
    handoff.mkdir()
    (handoff / 'research_report.md').write_text('# Committee outlook\n\n## Policy\n\nThe committee plans 25 MW capacity by 2030.\n')
    (handoff / 'actors.json').write_text(json.dumps({'central_question': 'Will capacity increase?',
        'actors': [{'id': 'A1', 'name': 'NVIDIA', 'role': 'Supplies infrastructure.'}],
        'situation_brief': {'overview': 'Supply is constrained.'}, 'hot_topics': ['Future growth.']}))
    (handoff / 'data').mkdir()
    (handoff / 'data' / 'datasets.json').write_text(json.dumps({'series': [{'series_id': 'GDP_USD',
        'label': 'Economic output', 'value': '25', 'unit': 'MW'}]}))
    monkeypatch.setattr(api.PipelineManager, 'resolve_handoff_dir', lambda pid: str(handoff))
    llm = CombinedTranslator()
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: llm)
    return api, handoff, llm


def test_research_actual_worker_to_dossier_and_source_hash_audit_reader(client, research):
    api, handoff, llm = research
    originals = {p.name: p.read_bytes() for p in handoff.glob('*.json')}
    source = (handoff / 'research_report.md').read_bytes()
    base = '/api/research/pipe_http/dossier/translations/zh'
    response = client.post(base)
    assert response.status_code == 202, response.json
    assert _dispatch_research(api)['job_state'] == 'completed'
    data = wait_for(client, base)
    assert data['available'], data
    assert data['structured_translation']['complete'], data
    assert data['dossier']['actors']['central_question'] != 'Will capacity increase?'
    assert data['dossier']['datasets']['series'][0]['series_id'] == 'GDP_USD'
    assert data['dossier']['datasets']['series'][0]['value'] == '25'
    assert '25' in data['report'] and '2030' in data['report']
    assert source == (handoff / 'research_report.md').read_bytes()
    assert all((handoff / name).read_bytes() == value for name, value in originals.items())
    assert client.post(base).status_code == 200
    canonical = client.get('/api/research/pipe_http/dossier?lang=zh').json['data']
    assert canonical['dossier'] == data['dossier']
    assert canonical['actors']['central_question'] == 'Will capacity increase?'
    # Tamper with the artifact the public reader actually resolved, retaining its
    # timestamp: neither a legacy filename nor mtime is publication authority.
    import os
    snapshot = api._research_artifact(str(handoff), 'zh', 'pipe_http')[2]
    assert snapshot is not None and snapshot.generation == data['generation_id']
    target = Path(snapshot.path) / 'document.md'
    stamp = target.stat()
    target.write_text(data['report'] + 'TAMPER')
    os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert target.stat().st_mtime_ns == stamp.st_mtime_ns
    denied = client.get(base).json['data']
    assert not denied['available'] and denied['status'] == 'failed'
    assert denied['report'] is None and denied['generation_id'] is None
    assert client.get('/api/research/pipe_http/dossier/pdf?lang=zh').status_code == 409


def test_research_failed_force_keeps_previous_variant_and_restart_is_retriable(client, research):
    from app.services.translation import scheduler
    from app.services.translation.store import Store, database_path
    api, handoff, llm = research
    base = '/api/research/pipe_http/dossier/translations/zh'
    assert client.post(base).status_code == 202
    assert _dispatch_research(api)['job_state'] == 'completed'
    good = wait_for(client, base)
    assert good['available'], good
    snapshot = api._research_artifact(str(handoff), 'zh', 'pipe_http')[2]
    preserved = {path: path.read_bytes() for path in Path(snapshot.path).iterdir() if path.is_file()}
    llm.fail = True
    started = client.post(base + '?force=1')
    assert started.status_code == 202
    job_id = started.json['data']['translation_job']['job_id']
    assert _dispatch_research(api)['job_state'] == 'failed'
    failed = wait_for(client, base)
    assert failed['status'] == 'failed' and failed['available'] is True
    assert failed['generation_id'] == good['generation_id']
    assert all(path.read_bytes() == data for path, data in preserved.items())

    # Requeue, claim, and elect a new coordinator without running the old claim.
    # Restart recovery comes from the durable journal, not a synthetic PID file.
    assert client.post(base).json['data']['translation_job']['job_id'] == job_id
    with Store(database_path()) as store:
        epoch = store.elect()
        claim = store.claim_task(epoch, [api._RESEARCH_TRANSLATION_OPERATION])
        assert claim and claim[0] == job_id
    with Store(database_path()) as restarted:
        restarted.elect()
    for _ in range(2):
        interrupted = client.get(base).json['data']
        assert interrupted['status'] == 'interrupted' and interrupted['available'] is True
        assert interrupted['translation_job']['job_id'] == job_id
    assert scheduler.status(job_id)['job_state'] == 'interrupted'
    llm.fail = False
    resumed = client.post(base)
    assert resumed.json['data']['translation_job']['job_id'] == job_id
    assert _dispatch_research(api)['job_state'] == 'completed'
    final = wait_for(client, base)
    assert final['available'] and final['structured_translation']['complete']
    assert all(path.read_bytes() == data for path, data in preserved.items())


def test_research_changed_source_during_provider_call_is_never_published(client, research):
    from app.services.translation import scheduler
    api, handoff, llm = research
    old_source = (handoff / 'research_report.md').read_bytes()
    llm.after_call = lambda: (handoff / 'research_report.md').write_text('# New source\n\nDifferent claim.\n')
    base = '/api/research/pipe_http/dossier/translations/zh'
    started = client.post(base)
    assert started.status_code == 202
    job_id = started.json['data']['translation_job']['job_id']
    assert _dispatch_research(api)['job_state'] == 'failed'
    failed = scheduler.status(job_id)
    assert failed['job_state'] == 'failed'
    assert failed['identity']['source_sha256'] == hashlib.sha256(old_source).hexdigest()
    data = wait_for(client, base)
    # The failed old-source job stays inspectable, but cannot own the new view.
    assert data['status'] == 'unavailable' and not data['available']
    assert data['translation_job'] is None and data['generation_id'] is None
    assert data['source_sha256'] == hashlib.sha256((handoff / 'research_report.md').read_bytes()).hexdigest()
    assert data['source_sha256'] != failed['identity']['source_sha256']
    assert api._research_artifact(str(handoff), 'zh', 'pipe_http')[2] is None


def test_actual_published_forecast_display_reader_preserves_seals_and_sdk(published, monkeypatch, report_scheduler):
    from app.api import report as api
    report, folder, client = published['report'], published['folder'], published['client']
    llm = Translator()
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: llm)
    (folder / 'viz_manifest.json').write_text(json.dumps({'items': [
        {'id': 'chart_1', 'path': 'charts/output.png', 'caption': 'Expected supply trend.'},
        {'id': 'bad', 'path': '/private/secret.png', 'caption': 'Do not expose.'}]}))
    sealed = {name: (folder / name).read_bytes() for name in ('full_report.md', 'forecast.json', 'final_audit.json')}
    with client.application.app_context():
        rendered = api._report_display(report, 'zh', generate=True)
    assert rendered['translation_status']['complete'], rendered
    response = client.get(f'/api/report/{report.report_id}/forecast?lang=zh')
    assert response.status_code == 200, response.json
    data = response.json['data']
    assert data['display']['title'] != 'Committee outlook'
    assert data['display']['viz_manifest'][0]['path'] == 'charts/output.png'
    assert len(data['display']['viz_manifest']) == 1
    assert data['forecast']['scenarios'][0]['probability'] == .7
    assert all((folder / name).read_bytes() == content for name, content in sealed.items())
    assert client.get(f'/api/report/{report.report_id}/download').status_code == 200
    resolved = client.post(f'/api/v1/resolve/{report.report_id}', json={'outcome': 'Base case'})
    assert resolved.status_code == 200, resolved.json


def test_stale_available_result_cannot_start_display_acquisition(published, monkeypatch, report_scheduler):
    from app.api import report as api
    from app.services.report_agent import ReportManager
    report, client = published['report'], published['client']
    assert not ReportManager.is_publishable(report.report_id, 'zh')
    monkeypatch.setattr(ReportManager, 'generate_translation_variant',
        classmethod(lambda cls, *args, **kwargs: {'available': True, 'updated': True}))
    from test_report_durable_routes import run_queued_report
    def forbidden(*args, **kwargs):
        raise AssertionError('unpublished translation must not acquire display translation')
    monkeypatch.setattr('app.utils.llm_client.LLMClient', forbidden)
    monkeypatch.setattr(api, '_repair_report_structured', forbidden)
    response = client.post(f'/api/report/{report.report_id}/translations/zh')
    assert response.status_code == 202
    job_id = response.json['data']['task_id']
    failed = run_queued_report()
    assert failed['job_id'] == job_id and failed['job_state'] == 'failed'
    assert failed['error']['code'] == 'translation_not_admitted'
    status = client.get(f'/api/report/{report.report_id}/translations/zh/status?task_id={job_id}').json['data']
    assert status['status'] == 'failed' and not status['available']
    assert not status['structured_translation']['complete']
    assert not (published['folder'] / 'translations').exists()
