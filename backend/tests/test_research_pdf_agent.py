"""Guarded workflow tests with pixel-reading model and deterministic render doubles.

These tests prove orchestration, coverage, persistence and refusal boundaries.
Renderer-native acceptance and real-provider image comprehension belong to parent.
"""
import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from app.config import Config
from app.services.research_pdf import agent, renderer
from app.services.research_pdf.contracts import PdfExportError
from app.services.research_pdf.model import canonical

pytestmark = pytest.mark.guarded_runner
_REAL_PREPARE = renderer.prepare_document
_REAL_RENDER = renderer.render_document
_REAL_SKILL_ROOT = agent.SKILL_ROOT


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(canonical(value), encoding='utf-8')


class Driver:
    def __init__(self):
        self.calls = []
        self.prepares = 0
        self.renders = []
        self.pages = 2
        self.hook = None
        self.page_calls = 0
        self.repair = False
        self.always_repair = False
        self.cancelled = False
        self.expected_markers = ('EXACT_SKILL_MARKER', 'APP_MODE_MARKER')
        self.repair_handler = None

    def factory(self, role):
        owner = self

        class Model:
            def identity(self):
                return {'provider': 'controlled', 'model': role, 'api': 'chat_completions', 'fallback': False}

            def complete(self, *, system, payload, images, timeout, max_tokens):
                owner.calls.append({'role': role, 'system': system, 'payload': payload,
                                    'images': images, 'timeout': timeout, 'max_tokens': max_tokens})
                if owner.hook:
                    owner.hook(owner.calls[-1])
                assert timeout > 0 and max_tokens > 0
                assert all(marker in system for marker in owner.expected_markers)
                if payload.get('task') == 'image_input_capability_probe':
                    # Read the supplied pixels; never inspect the private expected-answer record.
                    palette = {(255, 0, 0): 'red', (0, 128, 0): 'green', (0, 0, 255): 'blue', (255, 255, 0): 'yellow'}
                    image = Image.open(io.BytesIO(images[0]['bytes'])).convert('RGB')
                    answer = {'cells': [palette[image.getpixel(((i % 3) * 120 + 60, (i // 3) * 120 + 60))] for i in range(9)]}
                elif 'page_findings' in payload:
                    answer = {'layout': owner.repair_handler(payload) if owner.repair_handler else {'body_font_size': 9.5}}
                elif 'page' in payload:
                    assert images and images[0]['sha256'] == payload['page_sha256']
                    owner.page_calls += 1
                    needs_repair = owner.always_repair or (owner.repair and owner.page_calls <= owner.pages)
                    answer = {'page': payload['page'], 'page_sha256': payload['page_sha256'],
                              'verdict': 'repair' if needs_repair else 'pass',
                              'issues': [{'kind': 'layout', 'description': 'A label overlaps.'}] if needs_repair else []}
                else:
                    answer = {'source_part': payload['source_part'],
                              'component_ids': [item['id'] for item in payload['components']], 'issues': []}
                    if 'Plan source-preserving' in system:
                        answer['layout'] = {'body_font_size': 10}
                    else:
                        answer['verdict'] = 'pass'
                return {'data': answer, 'usage': {'input_tokens': 10, 'output_tokens': 5, 'precision': 'controlled'},
                        'identity': self.identity()}

        return Model()

    def prepare(self, snapshot, directory):
        self.prepares += 1
        directory.mkdir()
        components = [{'id': 'body-1', 'kind': 'paragraph', 'source_text': snapshot['markdown'],
                       'render_text': snapshot['markdown'], 'source_span': {'start': 0, 'end': len(snapshot['markdown'])}}]
        report = {'source_inventory': ['body-1'], 'blocks': [{'id': 'body-1', 'type': 'paragraph',
                  'text': {snapshot['language']: snapshot['markdown']}}]}
        path = directory / 'report.json'
        write(path, report)
        return {'report': report, 'components': components, 'source_digest': snapshot['source_digest'],
                'input_sha256': sha(path), 'report_path': str(path), 'language': snapshot['language'],
                'layout_schema': renderer.LAYOUT_SCHEMA}

    def render(self, prepared, directory, layout=None):
        self.renders.append(layout)
        directory.mkdir()
        pdf = directory / 'report.pdf'
        pdf.write_bytes(b'%PDF-controlled-' + str(len(self.renders)).encode())
        pages = []
        for number in range(1, self.pages + 1):
            path = directory / f'page-{number}.png'
            Image.new('RGB', (50, 80), ('blue' if len(self.renders) == 1 else 'green')).save(path)
            pages.append({'page': number, 'path': str(path), 'sha256': sha(path)})
        qa = {'checks': dict.fromkeys(agent._CHECKS, True), 'page_images': pages, 'sha256': sha(pdf),
              'component_draws': [{'id': c['id'] + '.text', 'page': page['page']}
                                  for page in pages for c in prepared['components']]}
        qa_path = directory / 'qa.json'
        write(qa_path, qa)
        return {'pdf_path': str(pdf), 'pdf_sha256': sha(pdf), 'qa_path': str(qa_path), 'qa': qa, 'pages': pages,
                'language': prepared['language'], 'input_sha256': prepared['input_sha256'],
                'source_digest': prepared['source_digest'], 'component_count': len(prepared['components'])}


@pytest.fixture
def case(tmp_path, monkeypatch):
    for name, value in {'LLM_PROVIDER': 'openai', 'LLM_MODEL_NAME': 'test-model',
                        'LLM_BASE_URL': 'https://configured.test/v1', 'LLM_API_KEY': 'secret-not-for-receipts',
                        'RESEARCH_PDF_REVIEW_PROVIDER': '', 'RESEARCH_PDF_REVIEW_MODEL': '',
                        'RESEARCH_PDF_REVIEW_BASE_URL': '', 'RESEARCH_PDF_REVIEW_API_KEY': '',
                        'RESEARCH_PDF_MAX_CALLS': 48, 'RESEARCH_PDF_TIMEOUT_SECONDS': 900}.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    skill = tmp_path / 'skill'
    for name in (*agent._REQUIRED_SKILL, 'scripts/export_report.py'):
        path = skill / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('EXACT_SKILL_MARKER' if name == 'SKILL.md' else 'APP_MODE_MARKER ' + name)
    monkeypatch.setattr(agent, 'SKILL_ROOT', skill)
    original_policy = agent.policy_fingerprint

    def fixture_policy():
        policy = original_policy()
        # The renderer is a controlled double here; concurrent renderer-worker
        # edits must not invalidate this unrelated test's resumable identity.
        policy['implementation']['renderer.py'] = 'controlled-renderer-v1'
        return policy

    monkeypatch.setattr(agent, 'policy_fingerprint', fixture_policy)
    folder = tmp_path / 'snapshot'
    folder.mkdir()
    source = folder / 'source.md'
    source.write_text('Complete accepted source: (1.2%) loss; outlook conditional, not guaranteed.\n')
    snapshot = {'schema': 'research-pdf-source/v1', 'kind': 'dossier', 'resource_id': 'pipeline-test',
                'requested_lang': None, 'language': 'en', 'source_digest': 'aggregate-source-digest',
                'markdown_sha256': sha(source), 'markdown': source.read_text(), 'folder': str(folder),
                'markdown_path': str(source), 'assets': [], 'admission': {}, 'citations': {}, 'title': 'Source title'}
    driver = Driver()
    monkeypatch.setattr(renderer, 'prepare_document', driver.prepare)
    monkeypatch.setattr(renderer, 'render_document', driver.render)
    phases = []

    def run():
        return agent.run_export(snapshot, tmp_path / 'work', progress=lambda phase: phases.append(phase),
                                is_cancelled=lambda: driver.cancelled, model_factory=driver.factory)

    return snapshot, driver, run, phases, tmp_path


def test_complete_source_skill_and_every_page_are_actually_consumed(case):
    snapshot, driver, run, phases, root = case
    original = Path(snapshot['markdown_path']).read_bytes()
    result = run()
    assert driver.prepares == len(driver.renders) == 1
    assert result['calls_used'] == 5
    assert driver.page_calls == 2
    assert Path(snapshot['markdown_path']).read_bytes() == original
    assert all('secret-not-for-receipts' not in p.read_text() for p in (root / 'work').rglob('*.json'))
    assert snapshot['markdown'] == next(c['payload']['source_text'] for c in driver.calls if 'source_text' in c['payload'])
    receipt = json.loads(Path(result['review_path']).read_text())
    assert receipt['schema'] == 'research-pdf-agent-review/v1'
    assert receipt['review_kind'] == 'automated_model_review'
    assert receipt['accepted'] is True and receipt['page_count'] == 2
    assert receipt['language'] == result['language']
    assert receipt['input_sha256'] == result['input_sha256']
    assert receipt['pdf_sha256'] == result['pdf_sha256']
    assert receipt['component_ids'] == ['body-1']
    assert [p['page'] for p in receipt['page_reviews']] == [1, 2]
    assert not {'visual_review', 'semantic_review', 'source_reconciled'}.intersection(receipt)
    assert result['review_sha256'] == sha(result['review_path'])
    assert result['agent_receipt_sha256'] == sha(result['agent_receipt_path'])
    assert phases[-1] == 'publishing'


def test_completed_phases_resume_without_paid_replay(case):
    _, driver, run, _, _ = case
    first = run()
    count = len(driver.calls)
    second = run()
    assert first['pdf_sha256'] == second['pdf_sha256']
    assert len(driver.calls) == count
    assert driver.prepares == len(driver.renders) == 1


def test_one_layout_repair_rerenders_and_reviews_every_new_page(case):
    _, driver, run, _, _ = case
    driver.repair = True
    result = run()
    assert driver.renders == [{'body_font_size': 10}, {'body_font_size': 9.5}]
    assert driver.page_calls == 4
    receipt = json.loads(Path(result['review_path']).read_text())
    assert all(p['verdict'] == 'pass' for p in receipt['page_reviews'])
    assert result['calls_used'] == 8


def test_second_visual_failure_never_renders_a_third_generation(case):
    _, driver, run, _, root = case
    driver.always_repair = True
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'visual_review_failed'
    assert len(driver.renders) == 2
    assert not (root / 'work' / 'agent-receipt.json').exists()


def test_unknown_dispatch_is_persisted_and_never_replayed(case):
    _, driver, run, _, root = case

    def timeout(call):
        if call['payload'].get('task') == 'image_input_capability_probe':
            raise PdfExportError('model_dispatch_unknown', 'unknown')

    driver.hook = timeout
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'model_dispatch_unknown'
    state = json.loads((root / 'work' / 'agent-state.json').read_text())
    assert state['calls']['vision-probe']['state'] == 'unknown'
    count = len(driver.calls)
    driver.hook = None
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'model_dispatch_unknown'
    assert len(driver.calls) == count


def test_crash_after_dispatch_marker_is_ambiguous(case):
    _, driver, run, _, root = case

    def crash(_call):
        raise KeyboardInterrupt('process interrupted')

    driver.hook = crash
    with pytest.raises(KeyboardInterrupt):
        run()
    state = json.loads((root / 'work' / 'agent-state.json').read_text())
    assert state['calls']['vision-probe']['state'] == 'dispatching'
    driver.hook = None
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'model_dispatch_unknown'
    assert len(driver.calls) == 1


def test_changed_source_stops_before_provider(case):
    snapshot, driver, run, _, _ = case
    Path(snapshot['markdown_path']).write_text('changed')
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'artifact_changed'
    assert not driver.calls


def test_cancel_during_confirmed_call_preserves_result_but_cannot_publish(case):
    _, driver, run, _, root = case
    driver.hook = lambda _call: setattr(driver, 'cancelled', True)
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'export_cancelled'
    state = json.loads((root / 'work' / 'agent-state.json').read_text())
    assert state['calls']['vision-probe']['state'] == 'completed'
    assert not (root / 'work' / 'agent-receipt.json').exists()


def test_insufficient_budget_never_samples_only_some_pages(case, monkeypatch):
    _, driver, run, _, root = case
    monkeypatch.setattr(Config, 'RESEARCH_PDF_MAX_CALLS', 4)
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'export_budget'
    assert driver.page_calls == 0
    assert not (root / 'work' / 'automated-review.json').exists()


def test_english_only_snapshot_does_not_request_translation(case):
    snapshot, driver, run, _, _ = case
    run()
    assert snapshot['language'] == 'en'
    assert all(call['payload'].get('language', 'en') == 'en' for call in driver.calls)
    assert not any('translate this' in call['system'].lower() for call in driver.calls)


def test_mandarin_primary_remains_selected_language(case):
    snapshot, driver, run, _, _ = case
    snapshot['language'] = 'zh-CN'
    snapshot['markdown'] = '完整原文；亏损(1.2%)。预测附带条件。'
    Path(snapshot['markdown_path']).write_text(snapshot['markdown'])
    snapshot['markdown_sha256'] = sha(snapshot['markdown_path'])
    result = run()
    assert result['language'] == 'zh-CN'
    assert snapshot['markdown'] == next(c['payload']['source_text'] for c in driver.calls if 'source_text' in c['payload'])


def test_mutated_review_image_invalidates_reuse(case):
    _, driver, run, _, _ = case
    result = run()
    Path(result['pages'][0]['path']).write_bytes(b'changed')
    count = len(driver.calls)
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'artifact_changed'
    assert len(driver.calls) == count


def test_phase_receipt_tampering_is_not_trusted(case):
    _, driver, run, _, root = case
    run()
    path = root / 'work' / 'calls' / 'content-0000.json'
    path.write_text('{}')
    count = len(driver.calls)
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'artifact_changed'
    assert len(driver.calls) == count


def test_model_cannot_rewrite_content_or_add_arbitrary_layout_fields(case):
    _, driver, run, _, _ = case
    factory = driver.factory

    def altered_factory(role):
        model = factory(role)
        original = model.complete

        def complete(**kwargs):
            result = original(**kwargs)
            if 'layout' in result['data']:
                result['data']['layout']['rewritten_body'] = 'invented research'
            return result
        model.complete = complete
        return model
    driver.factory = altered_factory
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'model_response_invalid'
    assert not driver.renders


def test_missing_component_coverage_cannot_pass(case):
    _, driver, run, _, _ = case
    factory = driver.factory

    def altered_factory(role):
        model = factory(role)
        original = model.complete

        def complete(**kwargs):
            result = original(**kwargs)
            if result['data'].get('component_ids'):
                result['data']['component_ids'] = []
            return result
        model.complete = complete
        return model
    driver.factory = altered_factory
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'review_incomplete'


def test_false_vision_probe_cannot_reach_render(case):
    _, driver, run, _, _ = case
    factory = driver.factory

    def altered_factory(role):
        model = factory(role)
        original = model.complete

        def complete(**kwargs):
            result = original(**kwargs)
            if 'cells' in result['data']:
                result['data']['cells'] = ['unknown'] * 9
            return result
        model.complete = complete
        return model
    driver.factory = altered_factory
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'image_review_unavailable'
    assert not driver.renders
    assert len(driver.calls) == 1
    assert driver.calls[0]['payload']['task'] == 'image_input_capability_probe'


def test_immutable_prepared_checkpoint_is_verified(case):
    _, _, run, _, root = case
    run()
    path = root / 'work' / 'prepared-record.json'
    data = json.loads(path.read_text())
    data['components'][0]['render_text'] = 'unrelated substitute'
    write(path, data)
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'artifact_changed'


def test_successful_render_is_reusable_after_cancellation(case, monkeypatch):
    _, driver, run, _, _ = case
    original = driver.render

    def cancel_after_render(*args, **kwargs):
        result = original(*args, **kwargs)
        driver.cancelled = True
        return result

    monkeypatch.setattr(renderer, 'render_document', cancel_after_render)
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'export_cancelled'
    driver.cancelled = False
    result = run()
    assert len(driver.renders) == 1
    assert result['calls_used'] == 5


def test_render_wait_is_bounded_and_late_output_can_be_reused(case, monkeypatch):
    import threading
    from types import SimpleNamespace
    _, driver, run, _, root = case
    release = threading.Event()
    original = driver.render
    clock = SimpleNamespace(now=0.0)
    # Replace this module's time reference only, not Python's process-wide clock.
    monkeypatch.setattr(agent, 'time', SimpleNamespace(monotonic=lambda: clock.now))

    def delayed(*args, **kwargs):
        clock.now = 2.0  # Deterministically cross the one-second attempt deadline.
        release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(Config, 'RESEARCH_PDF_TIMEOUT_SECONDS', 1.0)
    monkeypatch.setattr(renderer, 'render_document', delayed)
    try:
        with pytest.raises(PdfExportError) as caught:
            run()
        assert caught.value.code == 'export_timeout'
        assert not (root / 'work' / 'agent-receipt.json').exists()
        with agent._LOCAL_LOCK:
            workers = list(agent._LOCAL_WORKERS.values())
        assert workers
    finally:
        release.set()
    for worker in workers:
        worker.join(2)
    clock.now = 0.0  # Explicit retry receives a fresh allowance, same policy/bytes.
    result = run()
    assert len(driver.renders) == 1
    assert result['calls_used'] == 5


def test_large_durable_receipts_do_not_inherit_model_output_limit(tmp_path):
    path = tmp_path / 'large-receipt.json'
    value = {'source': '原' * 300000}
    agent._write(path, value)
    assert agent._read(path) == value


def test_raw_source_reading_is_separate_from_paired_component_review():
    raw = 'First paragraph.\nSecond paragraph.'
    components = [
        {'id': 'a', 'source_text': raw[:17], 'render_text': 'First paragraph.', 'source_span': {'start': 0, 'end': 17}},
        {'id': 'b', 'source_text': raw[17:], 'render_text': 'Second paragraph.', 'source_span': {'start': 17, 'end': len(raw)}}]
    source, paired = agent._batches({'markdown': raw, 'language': 'en', 'source_digest': 'source'},
                                    {'components': components, 'input_sha256': 'input'}, 180)
    assert ''.join(batch['source_text'] for batch in source) == raw
    assert all(batch['components'] == [] for batch in source)
    assert [item for batch in paired for item in batch['components']] == components
    assert all(batch['batch_kind'] == 'paired_component_reconciliation' for batch in paired)


def test_invalid_component_source_span_fails_before_model(case, monkeypatch):
    _, driver, run, _, _ = case
    original = driver.prepare

    def bad_span(*args):
        prepared = original(*args)
        prepared['components'][0]['source_span'] = {'start': 2, 'end': 4}
        return prepared

    monkeypatch.setattr(renderer, 'prepare_document', bad_span)
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'source_incomplete'
    assert not driver.calls


def test_explicit_retry_of_confirmed_rejection_counts_both_attempts(case):
    _, driver, run, _, root = case

    def reject(_call):
        raise PdfExportError('model_request_rejected', 'Rate limited.', retryable=True)

    driver.hook = reject
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'model_request_rejected'
    driver.hook = None
    result = run()
    assert result['calls_used'] == len(driver.calls) == 6
    assert (root / 'work' / 'calls' / 'vision-probe.json').exists()
    assert (root / 'work' / 'calls' / 'vision-probe-attempt-2.json').exists()
    state = json.loads((root / 'work' / 'agent-state.json').read_text())
    assert state['calls']['vision-probe']['history'][0]['state'] == 'failed'


def test_parent_progress_error_propagates_unchanged(case):
    snapshot, driver, _, _, root = case
    expected = PdfExportError('cancelled', 'Cancelled by the owning export job.')

    def progress(phase, detail=None):
        if phase == 'planning':
            raise expected

    with pytest.raises(PdfExportError) as caught:
        agent.run_export(snapshot, root / 'work', progress=progress, is_cancelled=lambda: False,
                         model_factory=driver.factory)
    assert caught.value is expected
    assert all(call['payload'].get('task') == 'image_input_capability_probe' for call in driver.calls)


def test_packaged_skill_loads_real_application_profile():
    text, hashes = agent._skill()
    assert 'Selected-language application integration' in text
    assert 'references/application-mode.md' in hashes
    assert hashes['SKILL.md'] == sha(agent.SKILL_ROOT / 'SKILL.md')


@pytest.fixture(autouse=True)
def record_owned_production_hashes():
    import sys
    guard = sys.modules.get('main_offline_guard')
    if guard is not None:
        for name in ('agent.py', 'model.py'):
            path = Path(agent.__file__).with_name(name)
            guard.source_hashes[str(path)] = sha(path)


def test_native_renderer_and_packaged_skill_reach_real_pdf_with_controlled_review(case, monkeypatch):
    snapshot, driver, run, _, _ = case
    monkeypatch.setattr(agent, 'SKILL_ROOT', _REAL_SKILL_ROOT)
    monkeypatch.setattr(renderer, 'prepare_document', _REAL_PREPARE)
    monkeypatch.setattr(renderer, 'render_document', _REAL_RENDER)
    driver.expected_markers = ('Equity Research PDF', 'Selected-language application integration')
    snapshot.update(publisher='DeepResearchForecast', report_type='Deep research', date='2026-10-26')
    result = run()
    assert Path(result['pdf_path']).stat().st_size > 10000
    assert result['qa']['checks']['component_text_regions'] is True
    assert result['qa']['checks']['used_fonts_embedded'] is True
    assert driver.page_calls == len(result['pages'])
    review = json.loads(Path(result['review_path']).read_text())
    assert review['accepted'] is True
    assert review['pdf_sha256'] == sha(result['pdf_path'])
    assert review['policy']['skill_files']['SKILL.md'] == sha(_REAL_SKILL_ROOT / 'SKILL.md')


def test_inventory_omitting_second_source_paragraph_fails(case, monkeypatch):
    snapshot, driver, run, _, _ = case
    snapshot['markdown'] = 'Paragraph A.\n\nParagraph B must survive.'
    Path(snapshot['markdown_path']).write_text(snapshot['markdown'])
    snapshot['markdown_sha256'] = sha(snapshot['markdown_path'])
    original = driver.prepare

    def omit_second(*args):
        prepared = original(*args)
        prepared['components'][0].update(source_text='Paragraph A.', render_text='Paragraph A.',
                                         source_span={'start': 0, 'end': len('Paragraph A.')})
        return prepared

    monkeypatch.setattr(renderer, 'prepare_document', omit_second)
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'source_incomplete'
    assert not driver.calls


def test_confirmed_prepare_recovers_after_state_commit_failure(case, monkeypatch):
    _, driver, run, _, _ = case
    original = agent._write
    failed = False

    def fail_state_reference(path, value):
        nonlocal failed
        if Path(path).name == 'agent-state.json' and 'prepared_sha256' in value and not failed:
            failed = True
            raise OSError('controlled state commit failure')
        return original(path, value)

    monkeypatch.setattr(agent, '_write', fail_state_reference)
    with pytest.raises(PdfExportError):
        run()
    monkeypatch.setattr(agent, '_write', original)
    result = run()
    assert driver.prepares == 1
    assert result['calls_used'] == 5


def test_export_context_isolated_from_existing_pipeline_and_restored(case):
    from app.utils.telemetry import get_run_context, set_run_context, active_run_ids
    _, driver, run, _, _ = case
    contexts = []
    driver.hook = lambda _call: contexts.append(get_run_context())
    set_run_context('unrelated-pipeline', 'unrelated-stage')
    try:
        result = run()
        assert get_run_context() == ('unrelated-pipeline', 'unrelated-stage')
        receipt = json.loads(Path(result['agent_receipt_path']).read_text())
        assert all(run_id == receipt['telemetry_run_id'] and run_id != 'unrelated-pipeline' for run_id, _ in contexts)
        assert receipt['telemetry_run_id'] not in active_run_ids()
    finally:
        set_run_context(None)


def test_native_full_markdown_inventory_including_footnotes_and_figure(case, monkeypatch):
    snapshot, driver, run, _, _ = case
    monkeypatch.setattr(agent, 'SKILL_ROOT', _REAL_SKILL_ROOT)
    monkeypatch.setattr(renderer, 'prepare_document', _REAL_PREPARE)
    monkeypatch.setattr(renderer, 'render_document', _REAL_RENDER)
    driver.expected_markers = ('Equity Research PDF', 'Selected-language application integration')
    driver.repair_handler = lambda payload: {'body_font_size': 9.5, 'figure_max_height': 180,
        'page_break_before': [c['id'] for c in payload['component_index'] if c['kind'] == 'figure']}
    source = Path(__file__).parent / 'fixtures' / 'research_pdf_full.md'
    snapshot['markdown'] = source.read_text()
    Path(snapshot['markdown_path']).write_text(snapshot['markdown'])
    snapshot['markdown_sha256'] = sha(snapshot['markdown_path'])
    asset = Path(snapshot['folder']) / 'charts' / 'forecast.png'
    asset.parent.mkdir()
    Image.new('RGB', (400, 180), 'navy').save(asset)
    snapshot['assets'] = [{'relative_path': 'charts/forecast.png', 'sha256': sha(asset)}]
    snapshot.update(publisher='DeepResearchForecast', report_type='Deep research', date='2026-10-26',
                    citations={'S1': {'url': 'https://example.org/filing?year=2026&unit=USD', 'title': 'Source filing'}})
    result = run()
    assert result['qa']['checks']['component_text_regions'] is True
    assert result['qa']['checks']['figure_pixels_present'] is True
    assert result['qa']['checks']['inline_link_regions'] is True
    assert driver.page_calls == len(result['pages'])


def test_typed_renderer_layout_failure_uses_single_model_repair(case, monkeypatch):
    _, driver, run, _, _ = case
    original = driver.render

    def typed_failure(*args, **kwargs):
        result = original(*args, **kwargs)
        if len(driver.renders) == 1:
            raise PdfExportError('pdf_figure_qa_failed', 'Controlled chart grouping defect.')
        return result

    monkeypatch.setattr(renderer, 'render_document', typed_failure)
    result = run()
    assert len(driver.renders) == 2
    receipt = json.loads(Path(result['agent_receipt_path']).read_text())
    assert receipt['renders']['0']['state'] == 'failed'
    assert receipt['renders']['1']['state'] == 'completed'
    assert sum('page_findings' in call['payload'] for call in driver.calls) == 1


def test_renderer_content_integrity_failure_never_receives_layout_repair(case, monkeypatch):
    _, driver, run, _, _ = case

    def content_failure(*args, **kwargs):
        raise PdfExportError('pdf_input_changed', 'Controlled content mutation.')

    monkeypatch.setattr(renderer, 'render_document', content_failure)
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'pdf_input_changed'
    assert not any('page_findings' in call['payload'] for call in driver.calls)


def test_page_estimate_is_diagnostic_and_actual_pages_enforce_budget(case, monkeypatch):
    snapshot, driver, run, _, _ = case
    snapshot['markdown'] = 'Accepted source. ' * 700
    Path(snapshot['markdown_path']).write_text(snapshot['markdown'])
    snapshot['markdown_sha256'] = sha(snapshot['markdown_path'])
    monkeypatch.setattr(Config, 'RESEARCH_PDF_BATCH_CHARS', 100000, raising=False)
    monkeypatch.setattr(Config, 'RESEARCH_PDF_MAX_CALLS', 5)
    result = run()
    receipt = json.loads(Path(result['review_path']).read_text())
    assert receipt['estimated_calls'] > 5
    assert result['calls_used'] == 5
    assert driver.page_calls == len(result['pages']) == 2


def test_planning_index_is_explicitly_layout_metadata_not_reconciliation_ids(case):
    _, driver, run, _, _ = case
    run()
    planning = next(call for call in driver.calls if 'Plan source-preserving' in call['system'])
    assert planning['payload']['components'] == []
    assert planning['payload']['component_index'] == [{'id': 'body-1', 'kind': 'paragraph'}]
    assert 'exactly the IDs in components' in planning['system']
    assert 'component_index is layout-reference metadata only' in planning['system']


def test_late_confirmed_figure_failure_can_repair_on_explicit_retry(case, monkeypatch):
    import threading
    from types import SimpleNamespace
    _, driver, run, _, _ = case
    original = driver.render
    release = threading.Event()
    clock = SimpleNamespace(now=0.0)
    attempts = []
    monkeypatch.setattr(agent, 'time', SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(Config, 'RESEARCH_PDF_TIMEOUT_SECONDS', 1.0)

    def late_failure(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            clock.now = 2.0
            release.wait(3)
            raise PdfExportError('pdf_figure_qa_failed', 'Late controlled layout failure.')
        return original(*args, **kwargs)

    monkeypatch.setattr(renderer, 'render_document', late_failure)
    try:
        with pytest.raises(PdfExportError) as caught:
            run()
        assert caught.value.code == 'export_timeout'
        with agent._LOCAL_LOCK:
            workers = list(agent._LOCAL_WORKERS.values())
    finally:
        release.set()
    for worker in workers:
        worker.join(2)
    clock.now = 0.0
    result = run()
    assert len(attempts) == 2
    assert result['calls_used'] == 6
    assert sum('page_findings' in call['payload'] for call in driver.calls) == 1


def _mixed_source(snapshot):
    snapshot.update(language='zh-CN', requested_lang='zh',
                    markdown='中文分析保留原文。Source quotation: "Growth is conditional". 图表原始轴为 Revenue (USD).\n')
    Path(snapshot['markdown_path']).write_text(snapshot['markdown'])
    snapshot['markdown_sha256'] = sha(snapshot['markdown_path'])
    snapshot['admission'] = {'rule': 'dossier_translation', 'available': True, 'language': 'zh',
        'source_language': 'en', 'partial': True, 'verbatim_chunks': [2, 4],
        'private_internal_error': 'do-not-send-admission-debug-text'}


def test_admitted_mixed_language_scope_reaches_all_reviews_and_receipt(case):
    snapshot, driver, run, _, _ = case
    _mixed_source(snapshot)
    original = Path(snapshot['markdown_path']).read_bytes()
    result = run()
    page_calls = [call for call in driver.calls if 'page' in call['payload']]
    assert len(page_calls) == 2
    for call in page_calls:
        scope = call['payload']['source_preservation_scope']
        assert scope['selected_language'] == 'zh-CN'
        assert scope['preserve_existing_mixed_language'] is True
        assert scope['translation_requested'] is False
        assert scope['translation_completeness'] == 'not_asserted'
        assert scope['known_admission_scope']['partial'] is True
        assert scope['known_admission_scope']['verbatim_chunk_count'] == 2
        assert scope['figure_pixel_identity_required'] is True
        assert call['payload']['figure_pixel_identity_verified'] is True
        assert call['payload']['source_components'][0]['source_text'] == snapshot['markdown']
        assert 'Do not request retranslation solely' in call['system']
    for call in driver.calls:
        assert 'do-not-send-admission-debug-text' not in canonical(call['payload'])
        if 'source_text' in call['payload']:
            assert call['payload']['source_preservation_scope']['preserve_partial_translation_disclosure'] is True
    receipt = json.loads(Path(result['review_path']).read_text())
    assert receipt['source_preservation_scope'] == page_calls[-1]['payload']['source_preservation_scope']
    assert 'a claim that all exhibit text was translated' in receipt['limitations']
    assert Path(snapshot['markdown_path']).read_bytes() == original


def test_unknown_translation_completeness_is_not_upgraded_to_complete(case):
    _, driver, run, _, _ = case
    run()
    scope = next(c['payload']['source_preservation_scope'] for c in driver.calls if 'page' in c['payload'])
    assert scope['translation_completeness'] == 'not_asserted'
    assert 'partial' not in scope['known_admission_scope']


def test_mixed_source_policy_does_not_accept_formatter_added_language(case):
    snapshot, driver, run, _, root = case
    _mixed_source(snapshot)
    factory = driver.factory

    def altered_factory(role):
        model = factory(role)
        original = model.complete

        def complete(**kwargs):
            result = original(**kwargs)
            if 'page' in kwargs['payload']:
                assert kwargs['payload']['source_preservation_scope']['unexpected_formatter_language'] == 'content_failure'
                result['data']['verdict'] = 'fail'
                result['data']['issues'] = [{'kind': 'content', 'description':
                    'Formatter introduced an English footer absent from the admitted source.'}]
            return result
        model.complete = complete
        return model

    driver.factory = altered_factory
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'visual_review_failed'
    assert not (root / 'work' / 'automated-review.json').exists()
    assert not any('page_findings' in call['payload'] for call in driver.calls)


def test_declared_static_link_adaptation_is_explicit_review_evidence(case, monkeypatch):
    _, driver, run, _, _ = case
    original = driver.prepare
    adaptation = {'kind': 'interactive_html_to_static_anchor', 'source_reference': 'charts/forecast.html',
                  'asset_reference': 'charts/forecast.png', 'target_reference': '#figure-source',
                  'asset_sha256': 'captured-source-asset-sha256'}

    def with_record(*args):
        prepared = original(*args)
        prepared['report']['chart_link_adaptations'] = [adaptation]
        prepared['components'][0]['adaptations'] = [adaptation]
        write(prepared['report_path'], prepared['report'])
        prepared['input_sha256'] = sha(prepared['report_path'])
        return prepared

    monkeypatch.setattr(renderer, 'prepare_document', with_record)
    result = run()
    assert all(call['payload']['source_preservation_scope']['declared_adaptations'] == [adaptation]
               for call in driver.calls if 'source_preservation_scope' in call['payload'])
    receipt = json.loads(Path(result['review_path']).read_text())
    assert receipt['source_preservation_scope']['declared_adaptations'] == [adaptation]


def test_vendored_renderer_executable_change_invalidates_completed_reuse(case):
    _, driver, run, _, _ = case
    run()
    before = agent.policy_fingerprint()
    script = agent.SKILL_ROOT / 'scripts' / 'export_report.py'
    assert before['renderer_executable_sha256'] == sha(script)
    assert before['skill_files']['scripts/export_report.py'] == sha(script)
    script.write_text(script.read_text() + '\n# changed renderer template\n')
    after = agent.policy_fingerprint()
    assert after['renderer_executable_sha256'] != before['renderer_executable_sha256']
    count = len(driver.calls)
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'export_stale'
    assert len(driver.calls) == count


def test_monospace_font_override_change_invalidates_completed_reuse(case, monkeypatch):
    _, driver, run, _, _ = case
    monkeypatch.delenv('EQUITY_PDF_MONO_FONT', raising=False)
    run()
    before = agent.policy_fingerprint()
    monkeypatch.setenv('EQUITY_PDF_MONO_FONT', '/private/configured-fonts/source-mono.ttf')
    after = agent.policy_fingerprint()
    assert after['font_overrides_sha256'] != before['font_overrides_sha256']
    count = len(driver.calls)
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'export_stale'
    assert len(driver.calls) == count


def test_missing_vendored_renderer_is_not_a_usable_skill(case):
    _, driver, run, _, _ = case
    (agent.SKILL_ROOT / 'scripts' / 'export_report.py').unlink()
    with pytest.raises(PdfExportError) as caught:
        run()
    assert caught.value.code == 'skill_unavailable'
    assert not driver.calls


def _prepare_native_for_compaction(case, markdown, folder_name):
    snapshot, _, _, _, root = case
    snapshot.update(markdown=markdown, publisher='DeepResearchForecast', report_type='Deep research', date='2026-10-26')
    Path(snapshot['markdown_path']).write_text(markdown)
    snapshot['markdown_sha256'] = sha(snapshot['markdown_path'])
    return snapshot, _REAL_PREPARE(snapshot, root / folder_name)


def test_large_reference_list_uses_exact_child_nodes_without_repeating_parent(case):
    markdown = '# References\n\n' + '\n'.join(
        f'- Reference {i}: ' + ('Original condition, USD 12.5 and source qualification. ' * 5)
        + f'[source](https://example.org/{i}).' for i in range(70))
    snapshot, prepared = _prepare_native_for_compaction(case, markdown, 'reference-prepared')
    before = canonical(prepared)
    inventory_before = sha(prepared['inventory_path'])
    assert max(len(c['source_text']) for c in prepared['components']) > 12000
    raw, paired = agent._batches(snapshot, prepared, 12000)
    units = [c for batch in paired for c in batch['components']]
    assert ''.join(batch['source_text'] for batch in raw) == markdown
    assert [u['id'] for u in units] == [c['id'] for c in prepared['components']]
    assert len(paired) < 15
    for unit, original in zip(units, prepared['components'], strict=True):
        assert unit['source_representation'] == 'parsed_subtree'
        assert unit['source_node_sha256'] == original['source_node_sha256']
        assert unit['source_locator'] == original['source_locator']
        assert unit['render_text'] == original['render_text']
        assert 'source_text' not in unit and 'source_span' not in unit
        assert unit['ancestor_source_span']['sha256'] == hashlib.sha256(original['source_text'].encode()).hexdigest()
        assert len(canonical(unit)) < 12000
    assert canonical(prepared) == before
    assert sha(prepared['inventory_path']) == inventory_before
    qa = {'component_draws': [{'id': c['id'] + '.text', 'page': 1} for c in prepared['components']],
          'checks': {'figure_pixels_present': True}}
    context = agent._page_source_context(snapshot, prepared, {'qa': qa}, {'page': 1}, units)
    assert len(canonical(context)) < 12000 * 8


def test_compact_child_node_hash_is_verified_before_model_use(case):
    snapshot, prepared = _prepare_native_for_compaction(case, '# Heading\n\n- One [link](https://example.org).\n', 'hashed-node')
    tokens = agent._source_coverage(snapshot, prepared)
    tokens[0]['children'][0]['raw'] = 'Changed content'
    with pytest.raises(PdfExportError) as caught:
        agent._review_components(prepared, tokens, 12000)
    assert caught.value.code == 'source_incomplete'


def test_oversized_table_reconciliation_preserves_every_header_row_and_cell(case):
    columns = ['Year', 'Value', 'Condition', 'Source']
    rows = [[str(2020 + i), f'USD {i}.50', 'Only if demand holds. ' * 6,
             f'[Source {i}](https://example.org/source/{i})'] for i in range(28)]
    markdown = '| ' + ' | '.join(columns) + ' |\n| --- | --- | --- | --- |\n'
    markdown += '\n'.join('| ' + ' | '.join(row) + ' |' for row in rows)
    snapshot, prepared = _prepare_native_for_compaction(case, markdown, 'table-prepared')
    before = canonical(prepared)
    raw, paired = agent._batches(snapshot, prepared, 12000)
    units = [c for batch in paired for c in batch['components']]
    table = prepared['components'][0]
    assert len(units) == len(rows) + 1
    assert ''.join(batch['source_text'] for batch in raw) == markdown
    assert '\n'.join(unit['render_text'] for unit in units) == table['render_text']
    assert {unit['component_id'] for unit in units} == {table['id']}
    assert all(unit['component_source_node_sha256'] == table['source_node_sha256'] for unit in units)
    assert [unit['source_node']['type'] for unit in units] == ['table_head'] + ['table_row'] * len(rows)
    assert all(unit['source_representation'] == 'parsed_subtree' and 'source_span' not in unit for unit in units)
    assert all(len(canonical(batch['components'])) <= 12000 + len(batch['components']) + 1 for batch in paired)
    assert canonical(prepared) == before
