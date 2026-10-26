"""Research route acceptance with real SQLite/generations and scripted providers.

Run only through backend/scripts/main_offline_pytest.py. Dispatch is stepped by
this fixture so no daemon or native renderer escapes a test's temporary roots.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from flask import Flask

from app.api import research as api
from app.services.report_agent import ReportAgent, ReportManager
from app.services.translation import scheduler
from app.services.translation.artifacts import ArtifactError, publish_generation, resolve_generation
from app.services.translation.contracts import safe_error
from app.services.translation.store import Store, database_path


SOURCE = '# Capacity outlook\r\n\r\nThe committee plans 25 MW by 2030.\r\n'
TARGET = '# 产能展望\n\n委员会计划到2030年实现25 MW。\n'
BASE = '/api/research/pipe_durable/dossier'
REAL_TRANSLATE = ReportAgent.translate_research_markdown
REAL_START_SCHEDULER = scheduler.start_scheduler
REAL_DISPLAY = api._research_display

# Add adapter and shared-consumer bytes to the guarded runner's completion receipt.
# Normal pytest runs do not create or modify verification records.
_guard = sys.modules.get('main_offline_guard')
if _guard is not None:
    for _relative in ('app/api/research.py', 'app/api/translations.py', 'app/services/report_agent.py',
                      'app/services/artifact_translation.py', 'app/services/model_translation.py',
                      'app/services/translation/artifacts.py', 'app/services/translation/scheduler.py',
                      'app/services/translation/contracts.py', 'app/services/translation/store.py',
                      'app/services/translation/service.py', 'app/services/translation/engine.py'):
        _path = Path(__file__).resolve().parents[1] / _relative
        _guard.source_hashes[str(_path)] = hashlib.sha256(_path.read_bytes()).hexdigest()


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()


def audit_for(source=SOURCE, target=TARGET, *, passed=True, proof=None, report_id='research::pipe_durable'):
    result = {'hard_passed': passed, 'markdown_sha256': sha(target),
              'source_markdown_sha256': sha(source), 'source_language': 'en', 'language': 'zh',
              'translator_version': 'model-translation/v1', 'report_id': report_id}
    if proof is None:
        from app.services.model_translation import ENGINE, split_document, _document_context, _receipt
        context = _document_context(source)
        rows = [{'source': src, 'target': tgt, 'receipt': _receipt(src, tgt, 'zh', context,
                 {'faithful': True, 'complete': True, 'target_language': True, 'issues': []}, object())}
                for src, tgt in zip(split_document(source), split_document(target))]
        proof = {'engine': ENGINE, 'complete': True, 'issues': {}, 'source_sha256': sha(source),
                 'target_sha256': sha(target), 'target_lang': 'zh', 'context': context, 'sections': rows}
    result['model_translation'] = proof
    return result


@pytest.fixture
def route(tmp_path, monkeypatch):
    handoff = tmp_path / 'handoff'
    handoff.mkdir()
    (handoff / 'research_report.md').write_bytes(SOURCE.encode())
    (handoff / 'actors.json').write_text(json.dumps({'actors': [{'id': 'A1', 'role': 'A supplier.'}]}))
    monkeypatch.setattr(api.Config, 'UPLOAD_FOLDER', str(tmp_path / 'uploads'))
    monkeypatch.setattr(api.Config, 'REPORT_PDF_EXPORT', True)
    monkeypatch.setattr(api.PipelineManager, 'resolve_handoff_dir', lambda pid: str(handoff))
    monkeypatch.setattr(scheduler, 'start_scheduler', lambda: None)
    api.register_translation_handler()
    env = SimpleNamespace(handoff=handoff, source=handoff / 'research_report.md',
                          display_complete=True, display_calls=[], translations=[])

    def display(directory, pipeline_id, lang, *, generate=False, force=False):
        env.display_calls.append((generate, force))
        return {'dossier': {'actors': {'actors': [{'id': 'A1', 'role': '供应商。'}]}},
                'structured_translation': {'complete': env.display_complete,
                    'issues': [] if env.display_complete else ['one pending display field'],
                    'coverage': {'total': 1, 'translated': int(env.display_complete),
                                 'complete': env.display_complete}}}

    monkeypatch.setattr(api, '_research_display', display)
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: object())

    def translate(self, markdown, **kwargs):
        env.translations.append((markdown, kwargs))
        return {'available': True, 'translated_md': TARGET, 'src': 'en', 'tgt': 'zh',
                'audit': audit_for(markdown, report_id=kwargs['label']),
                'citations': {'S1': {'url': 'https://example.test/'}}}

    monkeypatch.setattr(ReportAgent, 'translate_research_markdown', translate)
    application = Flask(__name__)
    application.config['TESTING'] = True
    application.register_blueprint(api.research_bp, url_prefix='/api/research')
    from app.api.translations import translations_bp
    application.register_blueprint(translations_bp, url_prefix='/api/translations')
    env.client = application.test_client()

    def dispatch():
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
        return scheduler.status(job_id)

    env.dispatch = dispatch
    return env


def publish(route, target=TARGET):
    source = route.source.read_bytes().decode('utf-8')
    return publish_generation(api._research_generation_root(str(route.handoff), 'pipe_durable'), kind='research', ref_id='pipe_durable', lang='zh',
        source_sha256=sha(source), markdown=target, audit=audit_for(source, target),
        source_path=route.source, assets={'citations.json': b'{"S1": {"title": "source"}}'})


def legacy(route, *, proof=None):
    source = route.source.read_bytes().decode('utf-8')
    variant = route.handoff / 'research_report.zh.md'
    audit_path = route.handoff / 'research_report.final_audit.zh.json'
    status_path = route.handoff / 'research_report.translation.zh.json'
    variant.write_bytes(TARGET.encode())
    audit_path.write_text(json.dumps(audit_for(source, proof=proof)))
    status_path.write_text(json.dumps({'schema_version': 2, 'status': 'available',
        'target_lang': 'zh', 'source_lang': 'en', 'source_sha256': sha(source),
        'markdown_sha256': sha(variant.read_bytes()), 'audit_sha256': sha(audit_path.read_bytes())}))
    return variant, audit_path, status_path


def data(route):
    response = route.client.get(BASE + '/translations/zh')
    assert response.status_code == 200, response.json
    return response.json['data']


def test_named_submission_deduplicates_and_persists_polling_authority(route):
    assert scheduler._handlers[api._RESEARCH_TRANSLATION_OPERATION] is api._run_research_translation
    assert not hasattr(api, '_research_translation_inflight')
    url = BASE + '/translations/zh'
    first = route.client.post(url)
    assert first.status_code == 202
    job = first.json['data']['translation_job']
    assert job['identity']['source_sha256'] == sha(SOURCE)
    assert job['identity']['scope']['display_sha256']
    duplicate = route.client.post(url)
    force_while_running = route.client.post(url + '?force=true')
    assert duplicate.json['data']['translation_job']['job_id'] == job['job_id']
    assert force_while_running.json['data']['translation_job']['job_id'] == job['job_id']
    assert not route.translations  # submission does not run an inline legacy worker
    assert data(route)['status'] == 'generating'
    with Store(database_path()) as store:
        epoch = store.elect()
        assert store.claim_task(epoch, [api._RESEARCH_TRANSLATION_OPERATION])
    with Store(database_path()) as restarted:
        restarted.elect()
    assert data(route)['translation_job']['job_state'] == 'interrupted'
    resumed = route.client.post(url)
    assert resumed.json['data']['translation_job']['job_id'] == job['job_id']
    assert route.dispatch()['job_state'] == 'completed'
    accepted = data(route)
    assert accepted['status'] == 'available' and accepted['report'] == TARGET
    assert accepted['generation'] and accepted['structured_translation']['complete']
    assert route.translations[0][0] == SOURCE  # CRLFs were never normalized
    assert route.translations[0][1]['identity']['kind'] == 'research_body'
    assert route.client.post(url).status_code == 200
    assert len(route.translations) == 1
    assert route.source.read_bytes() == SOURCE.encode()
    assert not (route.handoff / 'research_report.zh.md').exists()


def test_display_retry_preserves_body_and_uses_same_operation(route):
    route.display_complete = False
    first = route.client.post(BASE + '/translations/zh').json['data']['translation_job']
    failed = route.dispatch()
    assert failed['job_state'] == 'failed'
    assert failed['error']['code'] == 'structured_translation_incomplete'
    partial = data(route)
    assert partial['available'] and partial['partial'] and partial['status'] == 'failed'
    generation = partial['generation']
    retry = route.client.post(BASE + '/translations/zh')
    assert retry.json['data']['translation_job']['job_id'] == first['job_id']
    route.display_complete = True
    assert route.dispatch()['job_state'] == 'completed'
    assert data(route)['generation'] != generation
    assert data(route)['structured_translation']['sealed'] is True
    assert data(route)['report'] == TARGET
    assert len(route.translations) == 1


def test_force_display_retry_does_not_force_an_already_published_body(route):
    publish(route, TARGET.replace('委员会', '研究委员会'))
    route.display_complete = False
    first = route.client.post(BASE + '/translations/zh?force=true')
    assert first.status_code == 202
    assert route.dispatch()['job_state'] == 'failed'
    generation = data(route)['generation']
    resumed = route.client.post(BASE + '/translations/zh')
    assert resumed.json['data']['translation_job']['job_id'] == first.json['data']['translation_job']['job_id']
    route.display_complete = True
    assert route.dispatch()['job_state'] == 'completed'
    assert data(route)['generation'] != generation
    assert data(route)['structured_translation']['sealed'] is True
    assert data(route)['report'] == TARGET
    assert len(route.translations) == 1


def test_legacy_failed_proof_and_new_failed_checkpoint_seed_retry(route, monkeypatch):
    import copy
    from app.services.translation.contracts import ScopedImport, scope_digest
    old = audit_for()['model_translation']
    old.update(complete=False, issues={'section:0': ['review still pending']})
    new = copy.deepcopy(old)
    expected_identity = api._research_body_identity('pipe_durable', sha(SOURCE), {})
    new['resource_scope_sha256'] = scope_digest(expected_identity)
    for row in new['sections']:
        row['receipt']['resource_scope_sha256'] = scope_digest(expected_identity)
    audit_path = route.handoff / 'research_report.final_audit.zh.json'
    audit_path.write_text(json.dumps(audit_for(passed=False, proof=old)))

    def fail_then_pass(self, markdown, **kwargs):
        route.translations.append(kwargs)
        succeeds = len(route.translations) > 1
        return {'available': succeeds, 'tgt': 'zh', 'src': 'en', 'translated_md': TARGET,
                'audit': audit_for(passed=succeeds, proof=None if succeeds else new)}

    monkeypatch.setattr(ReportAgent, 'translate_research_markdown', fail_then_pass)
    first = route.client.post(BASE + '/translations/zh')
    assert route.dispatch()['error']['code'] == 'translation_rejected'
    assert route.translations[0]['previous_proof'] == old
    assert isinstance(route.translations[0]['previous_proof'], ScopedImport)
    assert route.translations[0]['previous_proof'].binding == scope_digest(route.translations[0]['identity'])
    assert not data(route)['available']
    resumed = route.client.post(BASE + '/translations/zh')
    assert resumed.json['data']['translation_job']['job_id'] == first.json['data']['translation_job']['job_id']
    assert route.dispatch()['job_state'] == 'completed'
    assert route.translations[1]['previous_proof'] == new
    assert type(route.translations[1]['previous_proof']) is dict
    assert route.translations[1]['force'] is False
    assert json.loads(audit_path.read_text())['model_translation'] == old


@pytest.mark.parametrize('accepted_kind', ['legacy', 'generation'])
def test_failed_force_preserves_accepted_bytes(route, monkeypatch, accepted_kind):
    if accepted_kind == 'legacy':
        preserved = {p: p.read_bytes() for p in legacy(route)}
    else:
        snapshot = publish(route)
        preserved = {p: p.read_bytes() for p in Path(snapshot.path).iterdir()}
    def reject(self, markdown, **kwargs):
        return {'available': False, 'tgt': 'zh', 'translated_md': 'rejected',
                'audit': audit_for(target='rejected', passed=False)}
    monkeypatch.setattr(ReportAgent, 'translate_research_markdown', reject)
    assert route.client.post(BASE + '/translations/zh?force=1').status_code == 202
    assert route.dispatch()['job_state'] == 'failed'
    failed = data(route)
    assert failed['available'] and failed['report'] == TARGET and failed['status'] == 'failed'
    assert all(p.read_bytes() == before for p, before in preserved.items())


@pytest.mark.parametrize('change', ['body', 'display'])
def test_changed_source_gets_new_identity_and_old_worker_cannot_publish(route, change):
    first = route.client.post(BASE + '/translations/zh').json['data']['translation_job']
    if change == 'body':
        route.source.write_bytes(SOURCE.replace('25 MW', '30 MW').encode())
    else:
        (route.handoff / 'actors.json').write_text('{"actors": [{"id": "A1", "role": "Changed context"}]}')
    assert route.dispatch()['job_state'] == 'failed'
    assert not route.translations
    assert not data(route)['available']
    second = route.client.post(BASE + '/translations/zh').json['data']['translation_job']
    assert first['job_id'] != second['job_id'] and first['identity'] != second['identity']


def test_source_drift_inside_translation_never_publishes(route, monkeypatch):
    def racing(self, markdown, **kwargs):
        route.source.write_text('# New source\n\nA different fact.\n')
        return {'available': True, 'tgt': 'zh', 'translated_md': TARGET, 'audit': audit_for()}
    monkeypatch.setattr(ReportAgent, 'translate_research_markdown', racing)
    route.client.post(BASE + '/translations/zh')
    assert route.dispatch()['job_state'] == 'failed'
    assert not (Path(api._research_generation_root(str(route.handoff), 'pipe_durable')) / '.translation-artifacts/research/zh/current.json').exists()


def test_stale_generation_can_be_replaced_for_new_source(route):
    previous = publish(route)
    route.source.write_bytes(SOURCE.replace('25 MW', '30 MW').encode())
    assert data(route)['status'] == 'stale'
    assert route.client.post(BASE + '/translations/zh').status_code == 202
    assert route.dispatch()['job_state'] == 'completed'
    assert data(route)['generation'] != previous.generation
    assert Path(previous.path, 'document.md').read_text() == TARGET.replace('\r\n', '\n')


def test_get_and_pdf_do_not_submit_or_acquire_provider(route, monkeypatch):
    snapshot = publish(route)
    def forbidden(*args, **kwargs):
        raise AssertionError('read path attempted provider work or scheduler mutation')
    monkeypatch.setattr('app.utils.llm_client.LLMClient', forbidden)
    monkeypatch.setattr(scheduler, 'submit', forbidden)
    monkeypatch.setattr(scheduler, 'retry', forbidden)
    monkeypatch.setattr(scheduler, 'start_scheduler', forbidden)
    observed = {}
    immutable = route.handoff / 'returned-cache.pdf'
    immutable.write_bytes(b'%PDF-1.7\nimmutable exact result\n')
    (route.handoff / 'research_report.zh.pdf').write_bytes(b'%PDF-1.7\nWRONG mutable alias\n')
    def export(markdown, folder, out_pdf, **kwargs):
        observed.update(markdown=markdown, **kwargs)
        kwargs['check_current']()
        return str(immutable)
    monkeypatch.setattr(ReportManager, 'export_document_pdf', export)
    assert data(route)['report'] == snapshot.markdown
    response = route.client.get(BASE + '/pdf?lang=zh')
    assert response.status_code == 200
    assert response.data == immutable.read_bytes() and b'WRONG' not in response.data
    assert observed['markdown'] == TARGET and observed['snapshot'].generation == snapshot.generation
    assert observed['source_path'] == str(route.source)
    assert 'research_report.zh.pdf' in response.headers['Content-Disposition']
    assert not any(generate for generate, _ in route.display_calls)


@pytest.mark.parametrize('language,source', [('en', SOURCE), ('zh', TARGET)])
def test_explicit_primary_language_exports_without_translation(route, monkeypatch, language, source):
    route.source.write_bytes(source.encode())
    observed = {}
    output = route.handoff / 'primary-cache.pdf'
    output.write_bytes(b'%PDF-1.7\nprimary\n')
    def export(markdown, folder, path, **kwargs):
        observed.update(markdown=markdown, **kwargs)
        return str(output)
    monkeypatch.setattr(ReportManager, 'export_document_pdf', export)
    result = route.client.get(BASE + '/pdf?lang=' + language)
    assert result.status_code == 200, result.json
    assert observed['markdown'] == source and observed['snapshot'] is None
    assert result.data == output.read_bytes()


@pytest.mark.parametrize('query,status', [('?lang=', 400), ('?lang=fr', 400),
    ('?lang=zh&lang=en', 400), ('?lang=zh', 404)])
def test_pdf_language_errors_are_explicit(route, query, status):
    assert route.client.get(BASE + '/pdf' + query).status_code == status


def test_pdf_disabled_and_missing_source(route, monkeypatch):
    monkeypatch.setattr(api.Config, 'REPORT_PDF_EXPORT', False)
    assert route.client.get(BASE + '/pdf').status_code == 503
    monkeypatch.setattr(api.Config, 'REPORT_PDF_EXPORT', True)
    route.source.unlink()
    assert route.client.get(BASE + '/pdf').status_code == 404
    assert route.client.get(BASE + '/translations/zh').status_code == 404
    assert route.client.post(BASE + '/translations/zh').status_code == 404


@pytest.mark.parametrize('mutation', ['source', 'generation', 'legacy'])
def test_pdf_delivery_rechecks_source_and_selected_publication(route, monkeypatch, mutation):
    if mutation == 'legacy':
        variant, _, _ = legacy(route)
    else:
        publish(route)
    output = route.handoff / 'cache.pdf'
    output.write_bytes(b'%PDF-1.7\nold selected body\n')
    def export(markdown, folder, path, **kwargs):
        if mutation == 'source':
            route.source.write_text(SOURCE + '\nnew fact')
        elif mutation == 'generation':
            publish(route, TARGET.replace('委员会', '另一委员会'))
        else:
            variant.write_text(TARGET + '\nchanged legacy body')
        return str(output)
    monkeypatch.setattr(ReportManager, 'export_document_pdf', export)
    assert route.client.get(BASE + '/pdf?lang=zh').status_code == 409


def test_malformed_generation_never_falls_back_to_valid_legacy(route, monkeypatch):
    legacy(route)
    snapshot = publish(route)
    Path(snapshot.path, 'document.md').write_text('tampered generation')
    assert not data(route)['available']
    def forbidden(*args, **kwargs):
        raise AssertionError('corrupt generation reached renderer')
    monkeypatch.setattr(ReportManager, 'export_document_pdf', forbidden)
    response = route.client.get(BASE + '/pdf?lang=zh')
    assert response.status_code == 409 and response.json['code'] == 'invalid_artifact'


@pytest.mark.parametrize('code,status', [('artifact_busy', 409), ('pdf_export_disabled', 503)])
def test_exporter_typed_errors_keep_status(route, monkeypatch, code, status):
    def export(*args, **kwargs):
        raise ArtifactError(code, 'safe export message', status_code=status)
    monkeypatch.setattr(ReportManager, 'export_document_pdf', export)
    response = route.client.get(BASE + '/pdf?lang=en')
    assert response.status_code == status and response.json['code'] == code


def test_displayed_identity_mismatch_rejected_before_render(route, monkeypatch):
    publish(route)
    def forbidden(*args, **kwargs):
        raise AssertionError('stale browser identity reached renderer')
    monkeypatch.setattr(ReportManager, 'export_document_pdf', forbidden)
    assert route.client.get(BASE + '/pdf?lang=zh&source_sha256=old').status_code == 409
    assert route.client.get(BASE + '/pdf?lang=zh&generation=old').status_code == 409


def test_sqlite_outage_preserves_readable_publication_and_refuses_mutation(route, monkeypatch):
    import sqlite3
    publish(route)
    route.display_complete = False
    response = route.client.post(BASE + '/translations/zh')
    assert response.status_code == 202
    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError('scripted unavailable store')
    monkeypatch.setattr(scheduler, 'status', unavailable)
    assert data(route)['available']
    response = route.client.post(BASE + '/translations/zh?force=1')
    assert response.status_code == 503


def test_job_reference_cannot_select_another_resource_identity(route):
    response = route.client.post(BASE + '/translations/zh')
    job = response.json['data']['translation_job']
    with Store(database_path()) as store:
        foreign = store.create_task(api._RESEARCH_TRANSLATION_OPERATION,
            {**job['identity'], 'ref_id': 'pipe_other'}, {'pipeline_id': 'pipe_other'})
    path = Path(api._research_job_path(str(route.handoff), job['identity']))
    path.write_text(json.dumps({'identity': job['identity'], 'job_id': foreign}))
    assert data(route)['translation_job'] is None


def test_real_dispatcher_and_document_worker_publish_reviewed_generation(route, monkeypatch):
    import time
    from test_translation_dates import GlmLikeTranslator
    from app.services.model_translation import valid_document_receipt
    model = GlmLikeTranslator()
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: model)
    monkeypatch.setattr(ReportAgent, 'translate_research_markdown', REAL_TRANSLATE)
    monkeypatch.setattr(scheduler, 'start_scheduler', REAL_START_SCHEDULER)
    try:
        started = route.client.post(BASE + '/translations/zh')
        assert started.status_code == 202, started.json
        job_id = started.json['data']['translation_job']['job_id']
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = scheduler.status(job_id)
            if job['job_state'] not in {'queued', 'running'}:
                break
            time.sleep(.01)
        assert job['job_state'] == 'completed', job
        accepted = data(route)
        snapshot = resolve_generation(api._research_generation_root(str(route.handoff), 'pipe_durable'), kind='research', ref_id='pipe_durable',
            lang='zh', source_sha256=sha(SOURCE), source_path=route.source)
        assert accepted['available'] and snapshot is not None
        assert valid_document_receipt(SOURCE, snapshot.markdown, 'zh', snapshot.audit['model_translation'])
        def forbidden(*args, **kwargs):
            raise AssertionError('accepted body attempted another provider call')
        monkeypatch.setattr(model, 'chat', forbidden)
        assert route.client.post(BASE + '/translations/zh').status_code == 200
    finally:
        scheduler.stop_schedulers()


@pytest.mark.parametrize('lang', ['en', 'zh'])
def test_real_inprocess_pdf_export_uses_admitted_language(route, monkeypatch, lang):
    import fitz
    if lang == 'zh':
        publish(route)
    # No executable discovery or subprocess renderer: use installed PyMuPDF in-process.
    monkeypatch.setattr(ReportManager, '_export_pdf_pandoc', lambda *args, **kwargs: False)
    monkeypatch.setattr(ReportManager, '_pdf_renderer_fingerprint', lambda: {'renderer': 'guarded-pymupdf'})
    response = route.client.get(BASE + '/pdf?lang=' + lang)
    assert response.status_code == 200, response.json
    assert response.data.startswith(b'%PDF-')
    with fitz.open(stream=response.data, filetype='pdf') as pdf:
        text = ''.join(page.get_text() for page in pdf)
    assert '25' in text and '2030' in text and '\ufffd' not in text
    assert ('产能展望' in text) if lang == 'zh' else ('Capacity outlook' in text)


@pytest.mark.parametrize('defect', ['missing_proof', 'bad_review', 'wrong_language', 'wrong_source_language'])
def test_generation_seal_cannot_replace_domain_review_admission(route, defect):
    audit = audit_for()
    if defect == 'missing_proof':
        audit.pop('model_translation')
    elif defect == 'bad_review':
        audit['model_translation']['sections'][0]['receipt']['review']['faithful'] = False
    elif defect == 'wrong_language':
        audit['language'] = 'en'
    else:
        audit['source_language'] = 'zh'
    publish_generation(api._research_generation_root(str(route.handoff), 'pipe_durable'),
        kind='research', ref_id='pipe_durable', lang='zh', source_sha256=sha(SOURCE),
        markdown=TARGET, audit=audit, source_path=route.source)
    assert not data(route)['available']
    assert route.client.get(BASE + '/pdf?lang=zh').status_code == 409


def test_parent_and_fork_sharing_handoff_keep_independent_publications(route):
    parent = publish(route)
    fork = BASE.replace('pipe_durable', 'pipe_fork')
    assert route.client.post(fork + '/translations/zh').status_code == 202
    assert route.dispatch()['job_state'] == 'completed'
    assert data(route)['generation'] == parent.generation
    assert route.client.get(fork + '/translations/zh').json['data']['available']
    assert route.source.read_bytes() == SOURCE.encode()
    assert api._research_proof_path(str(route.handoff), 'zh', sha(SOURCE), 'pipe_fork') != (
        api._research_proof_path(str(route.handoff), 'zh', sha(SOURCE), 'pipe_durable'))


def test_failed_refresh_is_resumed_even_with_complete_accepted_publication(route, monkeypatch):
    publish(route)
    calls = []
    def fail_then_pass(self, markdown, **kwargs):
        calls.append(kwargs)
        return {'available': len(calls) > 1, 'tgt': 'zh', 'src': 'en', 'translated_md': TARGET,
                'audit': audit_for(passed=len(calls) > 1)}
    monkeypatch.setattr(ReportAgent, 'translate_research_markdown', fail_then_pass)
    first = route.client.post(BASE + '/translations/zh?force=1').json['data']['translation_job']
    assert route.dispatch()['job_state'] == 'failed'
    assert data(route)['available']
    response = route.client.post(BASE + '/translations/zh')
    assert response.status_code == 202
    assert response.json['data']['translation_job']['job_id'] == first['job_id']
    assert route.dispatch()['job_state'] == 'completed'
    assert len(calls) == 2 and calls[1]['previous_proof'] is not None


def test_sealed_display_is_read_with_its_body_and_invalidated_by_source_digest(route, monkeypatch):
    route.client.post(BASE + '/translations/zh')
    assert route.dispatch()['job_state'] == 'completed'
    first = data(route)
    snapshot = resolve_generation(api._research_generation_root(str(route.handoff), 'pipe_durable'),
        kind='research', ref_id='pipe_durable', lang='zh', source_sha256=sha(SOURCE), source_path=route.source)
    assert 'display.json' in snapshot.assets and 'citations.json' in snapshot.assets
    def forbidden(*args, **kwargs):
        raise AssertionError('sealed display unexpectedly read mutable display cache')
    with monkeypatch.context() as scoped:
        scoped.setattr(api, '_research_display', forbidden)
        assert data(route)['dossier'] == first['dossier']
    (route.handoff / 'actors.json').write_text('{"actors": [{"id": "A2", "role": "Changed"}]}')
    changed = data(route)
    assert changed['available'] and changed['partial']
    assert changed['structured_translation']['sealed'] is False
    assert route.client.post(BASE + '/translations/zh').status_code == 202
    assert route.dispatch()['job_state'] == 'completed'
    assert len(route.translations) == 1
    assert data(route)['structured_translation']['sealed'] is True


def test_refresh_replay_after_structured_completion_does_not_repeat_provider_work(route, monkeypatch):
    from test_translation_dates import GlmLikeTranslator
    model = GlmLikeTranslator()
    calls = []
    original_chat = model.chat
    def tracked(*args, **kwargs):
        calls.append(1)
        return original_chat(*args, **kwargs)
    monkeypatch.setattr(model, 'chat', tracked)
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: model)
    monkeypatch.setattr(api, '_research_display', REAL_DISPLAY)
    route.client.post(BASE + '/translations/zh?force=1')
    with Store(database_path()) as store:
        epoch = store.elect()
        job_id, kind, payload = store.claim_task(epoch, [api._RESEARCH_TRANSLATION_OPERATION])
        token, epoch_token = scheduler._task_id.set(job_id), scheduler._task_epoch.set(epoch)
        try:
            scheduler._handlers[kind](payload)
            accepted_calls = len(calls)
            assert accepted_calls > 0
            # The process loses its operation completion after both artifacts persisted.
        finally:
            scheduler._task_id.reset(token)
            scheduler._task_epoch.reset(epoch_token)
    with Store(database_path()) as restarted:
        restarted.elect()
    before = data(route)['generation']
    assert route.client.post(BASE + '/translations/zh').status_code == 202
    assert route.dispatch()['job_state'] == 'completed'
    assert len(calls) == accepted_calls and len(route.translations) == 1
    assert data(route)['generation'] == before


def test_refresh_recovers_final_pointer_before_checkpoint_without_retranslating_body(route, monkeypatch):
    from app.services import artifact_translation
    original_save = artifact_translation._save_cache
    body_publications = []
    def lose_final_checkpoint(path, payload):
        if 'published_generation' in payload and 'display_ref_id' not in payload:
            body_publications.append(payload['published_generation'])
        if (payload.get('display_ref_id') and payload.get('published_generation')
                and payload['published_generation'] != body_publications[0]
                and len(body_publications) == 1):
            body_publications.append('interrupted')
            raise OSError('scripted crash after final publication before checkpoint')
        return original_save(path, payload)
    monkeypatch.setattr(artifact_translation, '_save_cache', lose_final_checkpoint)
    route.client.post(BASE + '/translations/zh?force=1')
    assert route.dispatch()['job_state'] == 'failed'
    assert data(route)['structured_translation']['sealed'] is True
    assert route.client.post(BASE + '/translations/zh').status_code == 202
    assert route.dispatch()['job_state'] == 'completed'
    assert len(route.translations) == 1


def test_primary_dossier_exposes_exact_displayed_bytes_digest_for_export(route):
    response = route.client.get(BASE)
    assert response.status_code == 200
    assert response.json['data']['report'] == SOURCE
    assert response.json['data']['source_sha256'] == sha(SOURCE)


def test_failed_structured_refresh_retains_previous_sealed_display(route):
    route.client.post(BASE + '/translations/zh')
    assert route.dispatch()['job_state'] == 'completed'
    accepted = data(route)
    route.display_complete = False
    route.client.post(BASE + '/translations/zh?force=1')
    assert route.dispatch()['error']['code'] == 'structured_translation_incomplete'
    failed = data(route)
    assert failed['status'] == 'failed' and failed['available']
    assert failed['structured_translation']['complete'] and failed['structured_translation']['sealed']
    assert failed['dossier'] == accepted['dossier']


@pytest.mark.parametrize('when', ['queued', 'provider'])
def test_figure_drift_changes_operation_identity_and_cannot_publish(route, monkeypatch, when):
    figure = route.handoff / 'charts' / 'supply.png'
    figure.parent.mkdir()
    figure.write_bytes(b'original figure bytes')
    source = SOURCE + '\n![Production](charts/supply.png)\n'
    target = TARGET + '\n![产量](charts/supply.png)\n'
    route.source.write_bytes(source.encode())
    def translate(self, markdown, **kwargs):
        if when == 'provider':
            figure.write_bytes(b'replaced figure bytes')
        return {'available': True, 'tgt': 'zh', 'src': 'en', 'translated_md': target,
                'audit': audit_for(source, target)}
    monkeypatch.setattr(ReportAgent, 'translate_research_markdown', translate)
    first = route.client.post(BASE + '/translations/zh').json['data']['translation_job']
    assert first['identity']['scope']['figures'] == {'charts/supply.png': sha(b'original figure bytes')}
    if when == 'queued':
        figure.write_bytes(b'replaced figure bytes')
    failed = route.dispatch()
    assert failed['job_state'] == 'failed' and failed['error']['code'] == 'source_changed'
    root = Path(api._research_generation_root(str(route.handoff), 'pipe_durable'))
    assert not (root / '.translation-artifacts/research/zh/current.json').exists()
    second = route.client.post(BASE + '/translations/zh').json['data']['translation_job']
    assert second['job_id'] != first['job_id']


def _bound_proof(proof, identity):
    import copy
    from app.services.translation.contracts import scope_digest
    bound = copy.deepcopy(proof)
    bound['resource_scope_sha256'] = scope_digest(identity)
    for row in bound['sections']:
        if isinstance(row.get('receipt'), dict):
            row['receipt']['resource_scope_sha256'] = scope_digest(identity)
    return bound


def _previous(route, identity=None):
    identity = identity or api._research_body_identity('pipe_durable', sha(SOURCE), {})
    return api._research_previous_proof(str(route.handoff), 'zh', sha(SOURCE),
                                       'pipe_durable', identity=identity)


@pytest.mark.parametrize('defect', ['report_id', 'source', 'language', 'source_language',
                                  'context', 'target_digest', 'missing_report_id'])
def test_legacy_import_requires_resource_audit_binding(route, defect):
    audit = audit_for(passed=False)
    if defect == 'report_id':
        audit['report_id'] = 'research::pipe_foreign'
    elif defect == 'source':
        audit['source_markdown_sha256'] = sha('other source')
    elif defect == 'language':
        audit['language'] = 'en'
    elif defect == 'source_language':
        audit['source_language'] = 'zh'
    elif defect == 'context':
        audit['model_translation']['context'] = 'Document outline: another report'
    elif defect == 'target_digest':
        audit['markdown_sha256'] = sha('another target')
    else:
        audit.pop('report_id')
    (route.handoff / 'research_report.final_audit.zh.json').write_text(json.dumps(audit))
    assert _previous(route) is None


@pytest.mark.parametrize('defect', ['identity', 'report_id', 'language', 'context', 'source_sha256'])
def test_checkpoint_import_requires_persisted_binding(route, defect):
    identity = api._research_body_identity('pipe_durable', sha(SOURCE), {})
    audit = audit_for()
    audit['model_translation'] = _bound_proof(audit['model_translation'], identity)
    record = api._research_proof_record(audit, identity, 'operation-fixture')
    if defect == 'identity':
        record['identity'] = {**identity, 'ref_id': 'pipe_foreign'}
    else:
        record[defect] = 'foreign'
    path = Path(api._research_proof_path(str(route.handoff), 'zh', sha(SOURCE), 'pipe_durable'))
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record))
    assert _previous(route) is None


@pytest.mark.parametrize('location', ['proof', 'receipt', 'legacy_proof_foreign_receipt', 'mixed_unbound_receipt'])
def test_foreign_or_mixed_scopes_are_never_given_legacy_capability(route, monkeypatch, location):
    from app.services.translation import contracts
    identity = api._research_body_identity('pipe_durable', sha(SOURCE), {})
    audit = audit_for()
    proof = _bound_proof(audit['model_translation'], identity)
    foreign = contracts.scope_digest({**identity, 'ref_id': 'pipe_foreign'})
    if location == 'proof':
        proof['resource_scope_sha256'] = foreign
    elif location == 'receipt':
        proof['sections'][0]['receipt']['resource_scope_sha256'] = foreign
    elif location == 'legacy_proof_foreign_receipt':
        proof.pop('resource_scope_sha256')
        proof['sections'][0]['receipt']['resource_scope_sha256'] = foreign
    else:
        proof['sections'][0]['receipt'].pop('resource_scope_sha256')
    audit['model_translation'] = proof
    (route.handoff / 'research_report.final_audit.zh.json').write_text(json.dumps(audit))
    def forbidden(*args, **kwargs):
        raise AssertionError('foreign or mixed proof was wrapped as a trusted legacy import')
    monkeypatch.setattr(contracts, 'trusted_import', forbidden)
    assert _previous(route) is None
    publish_generation(api._research_generation_root(str(route.handoff), 'pipe_durable'),
        kind='research', ref_id='pipe_durable', lang='zh', source_sha256=sha(SOURCE),
        markdown=TARGET, audit=audit, source_path=route.source)
    assert not data(route)['available']
    assert route.client.get(BASE + '/pdf?lang=zh').status_code == 409


def test_matching_bound_checkpoint_is_returned_without_wrapping(route, monkeypatch):
    from app.services.translation import contracts
    identity = api._research_body_identity('pipe_durable', sha(SOURCE), {})
    audit = audit_for()
    audit['model_translation'] = _bound_proof(audit['model_translation'], identity)
    record = api._research_proof_record(audit, identity, 'operation-fixture')
    path = Path(api._research_proof_path(str(route.handoff), 'zh', sha(SOURCE), 'pipe_durable'))
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record))
    def forbidden(*args, **kwargs):
        raise AssertionError('a scoped proof does not need a legacy capability')
    monkeypatch.setattr(contracts, 'trusted_import', forbidden)
    proof = _previous(route)
    assert type(proof) is dict and proof == audit['model_translation']
    publish_generation(api._research_generation_root(str(route.handoff), 'pipe_durable'),
        kind='research', ref_id='pipe_durable', lang='zh', source_sha256=sha(SOURCE),
        markdown=TARGET, audit=audit, source_path=route.source)
    assert data(route)['available']


def test_trusted_legacy_import_reuses_reviewed_sections_without_provider_calls(route):
    from app.services.model_translation import translate_document
    from app.services.translation.contracts import ScopedImport, scope_digest
    identity = api._research_body_identity('pipe_durable', sha(SOURCE), {})
    audit = audit_for(passed=False)
    audit['model_translation']['complete'] = False  # Individual reviewed rows remain reusable.
    (route.handoff / 'research_report.final_audit.zh.json').write_text(json.dumps(audit))
    seed = _previous(route)
    assert isinstance(seed, ScopedImport) and seed.binding == scope_digest(identity)
    class NoProvider:
        def chat(self, *args, **kwargs):
            raise AssertionError('trusted reviewed sections must not be translated again')
    target, proof = translate_document(NoProvider(), SOURCE, 'zh', identity=identity, previous_proof=seed)
    assert target == TARGET and proof['complete'] and proof['calls_used'] == 0
    assert proof['resource_scope_sha256'] == scope_digest(identity)
    assert all(row['receipt']['resource_scope_sha256'] == scope_digest(identity) for row in proof['sections'])


def _actionable_research_job(route, action):
    if action == 'retry':
        route.display_complete = False
    submitted = route.client.post(BASE + '/translations/zh')
    assert submitted.status_code == 202, submitted.json
    return route.dispatch() if action == 'retry' else submitted.json['data']['translation_job']


def _generic_research_action(route, job, action, resource=None, revision=None):
    return route.client.post(f"/api/translations/jobs/{job['job_id']}/{action}", json={
        'job_revision': job['job_revision'] if revision is None else revision,
        'resource': resource if resource is not None else {
            'pipeline_id': 'pipe_durable', 'lang': 'zh', 'scope': 'dossier'}})


@pytest.mark.parametrize('action,expected', [('retry', 'queued'), ('cancel', 'cancelled')])
def test_generic_research_actions_admit_current_resource_and_fence_revisions(route, action, expected):
    from app.api import translations
    api.register_translation_handler()  # Repeated registration keeps the real resolver.
    assert translations._authorizers[api._RESEARCH_TRANSLATION_OPERATION] is api._authorize_research_translation
    job = _actionable_research_job(route, action)
    calls = len(route.translations)
    response = _generic_research_action(route, job, action)
    assert response.status_code == 200, response.json
    public = response.json['data']
    assert public['job_id'] == job['job_id'] and public['job_state'] == expected
    assert public['job_revision'] == job['job_revision'] + 1
    assert 'identity' not in public and 'result' not in public
    assert len(route.translations) == calls
    stale = _generic_research_action(route, job, action)
    assert stale.status_code == 409 and stale.json['code'] == 'stale_job'
    assert scheduler.status(job['job_id'])['job_revision'] == public['job_revision']


@pytest.mark.parametrize('action', ['retry', 'cancel'])
@pytest.mark.parametrize('change', ['body', 'display', 'missing_source', 'wrong_resource', 'wrong_language'])
def test_generic_research_actions_reject_noncurrent_or_wrong_resource(route, action, change):
    job = _actionable_research_job(route, action)
    resource = {'pipeline_id': 'pipe_durable', 'lang': 'zh', 'mode': 'dossier'}
    if change == 'body':
        route.source.write_text(SOURCE + '\nChanged canonical claim.\n')
    elif change == 'display':
        (route.handoff / 'actors.json').write_text('{"actors": [{"id": "A2", "role": "Other context"}]}')
    elif change == 'missing_source':
        route.source.unlink()
    elif change == 'wrong_resource':
        # The fixture deliberately shares a handoff; matching text is not authority.
        resource['pipeline_id'] = 'pipe_foreign'
    else:
        resource['lang'] = 'en'
    response = _generic_research_action(route, job, action, resource=resource)
    assert response.status_code == 403 and response.json['code'] == 'resource_forbidden'
    current = scheduler.status(job['job_id'])
    assert current['job_state'] == job['job_state'] and current['job_revision'] == job['job_revision']


@pytest.mark.parametrize('selection', [
    {'pipeline_id': '../pipe_durable', 'lang': 'zh'},
    {'pipeline_id': 'pipe_durable', 'lang': 'zh', 'scope': 'private'},
    {'pipeline_id': 'pipe_durable', 'lang': 'zh', 'mode': 'private'},
    {'pipeline_id': 'pipe_durable', 'lang': 'zh', 'source_sha256': 'client-controlled'},
    {'pipeline_id': 'pipe_durable', 'lang': 'zh', 'identity': {'ref_id': 'pipe_durable'}},
])
def test_generic_research_authorizer_rejects_identity_assertions_and_invalid_selections(route, selection):
    job = _actionable_research_job(route, 'cancel')
    response = _generic_research_action(route, job, 'cancel', resource=selection)
    assert response.status_code == 403
    assert scheduler.status(job['job_id'])['job_state'] == 'queued'


def test_generic_research_authorizer_accepts_minimal_selection_without_client_hashes(route):
    job = _actionable_research_job(route, 'cancel')
    response = _generic_research_action(route, job, 'cancel', resource={
        'pipeline_id': 'pipe_durable', 'lang': 'zh'})
    assert response.status_code == 200 and response.json['data']['job_state'] == 'cancelled'
