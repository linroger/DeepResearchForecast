"""Guarded overlay contracts: actual durable engine/scheduler, scripted transport only."""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import pytest

from app.config import Config
from app.services import artifact_translation as at
from app.services.translation import scheduler
from app.services.translation.store import Store, database_path
from test_translation_pairs_integrity import Translator


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    scheduler.stop_schedulers()
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(tmp_path / 'uploads'))
    monkeypatch.setattr(Config, 'OASIS_SIMULATION_DATA_DIR', str(tmp_path / 'simulations'))
    root = Path(Config.OASIS_SIMULATION_DATA_DIR)
    root.mkdir()
    model = Translator()
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: model)
    from app import create_app
    app = create_app()
    app.config['TESTING'] = True
    yield app.test_client(), model, root
    scheduler.stop_schedulers()


def wait(client, url, **query):
    deadline = time.monotonic() + 45
    while True:
        response = client.get(url, query_string=query)
        assert response.status_code == 200, response.json
        data = response.json['data']
        if data['status'] != 'generating':
            return data
        assert time.monotonic() < deadline, data
        time.sleep(.05)


def graph(monkeypatch, count=1001):
    data = {'revision': 'r1', 'nodes': [
        {'uuid': f'n{i:05}', 'summary': f'Policy statement number {i}.', 'labels': ['Policy']}
        for i in range(count // 2)], 'edges': [
        {'uuid': f'e{i:05}', 'fact': f'The connection number {i} remains active.',
         'source_node_uuid': 'n00000', 'target_node_uuid': 'n00000'}
        for i in range(count - count // 2)]}
    from app.services.graph_builder import GraphBuilderService
    monkeypatch.setattr(GraphBuilderService, 'get_graph_data', lambda self, graph_id, **kw: copy.deepcopy(data))
    return data


def test_complete_graph_inventory_advances_bounded_pages_and_get_is_read_only(runtime, monkeypatch):
    client, model, _ = runtime
    data = graph(monkeypatch)
    original = copy.deepcopy(data)
    url = '/api/graph/graph_large/translations/zh'
    fresh = client.get(url).json['data']
    assert fresh['pending'] == fresh['total_candidates'] == 1001
    assert model.calls == []
    pending = 1001
    task_ids = []
    while pending:
        started = client.post(url)
        assert started.status_code == 202, started.json
        result = wait(client, url)
        task_ids.append(result['translation_job']['job_id'])
        assert result['translation_job']['job_state'] == 'completed'
        assert result['pending'] < pending
        assert pending - result['pending'] <= at._PAGE_PAIRS
        assert result['total_candidates'] == 1001
        assert result['continuation']['available'] is bool(result['pending'])
        pending = result['pending']
    assert len(set(task_ids)) == 5
    assert result['status'] == 'available' and len(result['translations']) == 1001
    assert 'node:n00499:summary' in result['overlay']
    assert 'edge:e00500:fact' in result['overlay']
    submitted = [key for payload in model.calls for key in payload.get('entries', {})]
    assert len(submitted) == len(set(submitted)) == 1001
    calls = len(model.calls)
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: pytest.fail('GET constructed provider'))
    monkeypatch.setattr(scheduler, 'submit', lambda *a, **k: pytest.fail('GET submitted work'))
    monkeypatch.setattr(at, '_save_cache', lambda *a, **k: pytest.fail('GET wrote cache'))
    assert client.get(url).json['data']['overlay'] == result['overlay']
    assert len(model.calls) == calls and data == original


def test_graph_revision_and_typed_source_changes_do_not_reuse_old_uuid_cache(runtime, monkeypatch):
    client, model, _ = runtime
    data = graph(monkeypatch, 4)
    url = '/api/graph/graph_revision/translations/zh'
    assert client.post(url).status_code == 202
    prior = wait(client, url)
    assert prior['status'] == 'available'
    data['revision'] = 'r2'
    data['nodes'][0]['labels'] = ['Changed typed context']
    newer = client.get(url).json['data']
    assert newer['overlay'] == {} and newer['source_fingerprint'] != prior['source_fingerprint']
    assert client.get(url, query_string={'request_digest': prior['request_digest']}).status_code == 400
    assert client.post(url, json={'context': {'revision': 'r1'}}).status_code == 400
    assert client.post(url + '?force=0').status_code == 202
    current = wait(client, url)
    assert current['status'] == 'available'
    calls = len(model.calls)
    assert client.post(url + '?force=false').status_code == 200
    assert len(model.calls) == calls


def test_structured_display_has_durable_identity_and_preserves_typed_carriers(runtime):
    _, model, root = runtime
    document = {'title': 'The policy outlook.', 'scenarios': [{'name': 'The base case.', 'probability': .7}],
                'source_ref': 'S1', 'provenance': {'source_sha256': 'abc', 'description': 'Typed provenance.'}}
    original = copy.deepcopy(document)
    first = at.display_document(str(root), 'dossier', 'pipe_projection', 'zh', document, generate=True)
    assert first['coverage']['complete']
    assert first['translation_job']['job_id'].startswith('tr_')
    with Store(database_path(), read_only=True) as store:
        row = store.db.execute('SELECT identity FROM jobs').fetchone()
        identity = json.loads(row['identity'])['resource']
    assert identity['kind'] == 'dossier' and identity['ref_id'] == 'pipe_projection'
    assert identity['scope']['source_fingerprint'] == at._digest(document)
    assert first['display']['provenance'] == document['provenance']
    assert first['display']['scenarios'][0]['probability'] == .7 and original == document
    calls = len(model.calls)
    assert at.display_document(str(root), 'dossier', 'pipe_projection', 'zh', document)['display'] == first['display']
    assert len(model.calls) == calls
    document['scenarios'][0]['probability'] = .3
    assert not at.display_document(str(root), 'dossier', 'pipe_projection', 'zh', document)['coverage']['complete']


def test_simulation_selector_hash_is_reloadable_and_private_text_never_crosses_scope(runtime, monkeypatch):
    client, model, root = runtime
    (root / 'sim_scope').mkdir()
    public = 'A public capacity plan.'
    private = 'A private negotiation strategy.'
    def projection(sid, context):
        return {'content': private if context.get('view') == 'analyst' else public, 'value': 25}
    monkeypatch.setattr(at, '_simulation_projection', projection)
    context = {'view': 'analyst'}
    url = '/api/simulation/sim_scope/translations/zh'
    response = client.post(url, json={'context': context, 'texts': [private]})
    assert response.status_code == 202, response.json
    digest = at._digest(['simulation', 'sim_scope', 'zh', context, at._visible_pairs([private])])
    assert response.json['data']['request_digest'] == digest
    result = wait(client, url, request_digest=digest, context=json.dumps(context))
    assert result['status'] == 'available'
    assert result['source_fingerprint'] == at._digest(projection('sim_scope', context))
    assert client.get(url).json['data']['translations'] == []
    assert client.get(url, query_string={'request_digest': digest, 'context': '{}'}).status_code == 400
    assert client.post(url, json={'texts': [private], 'context': {'view': 'public'}}).status_code == 400
    assert client.get(url, query_string={'request_digest': 'f' * 64, 'context': '{}'}).status_code == 404
    calls = len(model.calls)
    # The manifest reconnects after registry loss; it is not itself published text.
    scheduler.stop_schedulers()
    assert client.get(url, query_string={'request_digest': digest, 'context': json.dumps(context)}).json['data']['translations'] == result['translations']
    assert len(model.calls) == calls
    monkeypatch.setattr(at, '_simulation_projection', lambda *a: {'content': private, 'value': 99})
    changed = client.get(url, query_string={'request_digest': digest, 'context': json.dumps(context)}).json['data']
    assert changed['source_fingerprint'] != result['source_fingerprint'] and changed['overlay'] == {}


def test_retry_reviews_saved_candidate_without_second_translation(runtime, monkeypatch):
    client, _, _ = runtime
    graph(monkeypatch, 2)
    class ReviewOutage(Translator):
        unavailable = True
        def chat(self, messages, **kwargs):
            if 'pairs' in json.loads(messages[-1]['content']) and self.unavailable:
                raise TimeoutError('scripted review timeout')
            return super().chat(messages, **kwargs)
    model = ReviewOutage()
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: model)
    url = '/api/graph/graph_restart/translations/zh'
    assert client.post(url).status_code == 202
    failed = wait(client, url)
    assert failed['translation_job']['job_state'] == 'failed' and not failed['continuation']['available']
    assert model.generation_calls == 1
    scheduler.stop_schedulers()
    model.unavailable = False
    assert client.post(url).status_code == 202
    recovered = wait(client, url)
    assert recovered['status'] == 'available' and recovered['pending'] == 0
    assert recovered['translation_job']['job_id'] == failed['translation_job']['job_id']
    assert model.generation_calls == 1


def test_exhausted_page_budget_resume_advances_saved_tail(runtime, monkeypatch):
    client, model, _ = runtime
    graph(monkeypatch, 40)
    real = at.translate_pairs
    monkeypatch.setattr(at, 'translate_pairs', lambda *a, **k: real(*a, **k, max_calls=2))
    url = '/api/graph/graph_budget/translations/zh'
    assert client.post(url).status_code == 202
    first = wait(client, url)
    assert first['pending'] == 22 and not first['continuation']['available']
    assert client.post(url).status_code == 202
    second = wait(client, url)
    assert second['pending'] == 4
    assert client.post(url).status_code == 202
    final = wait(client, url)
    assert final['status'] == 'available'
    submitted = [key for event in model.calls for key in event.get('entries', {})]
    assert len(submitted) == len(set(submitted)) == 40


def test_refresh_failure_keeps_accepted_translation_and_plain_retry_resumes(runtime, monkeypatch):
    client, model, _ = runtime
    graph(monkeypatch, 4)
    url = '/api/graph/graph_refresh/translations/zh'
    client.post(url)
    good = wait(client, url)
    model.mutator = lambda *a: 'not JSON'
    assert client.post(url + '?force=1').status_code == 202
    bad = wait(client, url)
    assert bad['overlay'] == good['overlay'] and bad['refresh_pending'] == 4
    assert not bad['coverage']['complete'] and bad['retryable']
    model.mutator = None
    assert client.post(url).status_code == 202
    resumed = wait(client, url)
    assert resumed['status'] == 'available' and resumed['refresh_pending'] == 0


def test_cancel_during_provider_never_publishes_overlay(runtime, monkeypatch):
    client, _, _ = runtime
    graph(monkeypatch, 2)
    class Cancel(Translator):
        def chat(self, *a, **k):
            response = super().chat(*a, **k)
            scheduler.cancel(scheduler.current_task_id())
            return response
    model = Cancel()
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: model)
    url = '/api/graph/graph_cancel/translations/zh'
    client.post(url)
    result = wait(client, url)
    assert result['overlay'] == {} and result['status'] == 'cancelled'


def test_no_overlay_local_threads_or_inflight_registry_remain():
    source = Path(at.__file__).read_text()
    assert '_INFLIGHT' not in source and 'threading.Thread' not in source


def test_oversize_is_explicit_and_never_disguised_as_complete(runtime, monkeypatch):
    client, model, _ = runtime
    data = graph(monkeypatch, 2)
    data['nodes'][0]['summary'] = 'A' * (at._MAX_TEXT + 1)
    response = client.post('/api/graph/graph_bigentry/translations/zh')
    assert response.status_code == 400 and 'bounds' in response.json['error']
    assert model.calls == []


def test_real_world_projection_enforces_public_actor_analyst_and_revision(runtime):
    client, model, root = runtime
    from test_world_service_results import prepare
    from app.services.world_simulation.examples import ExamplePolicy
    from app.services.world_simulation.service import run_child
    from app.services.world_simulation.results import read_result
    from app.api.simulation import simulation_translation_projection
    _, state, directory = prepare(root)
    assert run_child(directory, policy=ExamplePolicy('investment')) == 0
    analyst = read_result(directory, view='analyst')
    public = read_result(directory)
    hidden = next(text for text in at._projection_strings(analyst['decisions'])
                  if len(text) > 30 and not any(text in value for value in at._projection_strings(public)))
    context = {'engine': 'world-v1', 'view': 'analyst', 'revision': analyst['revision'],
               'round': analyst['round'], 'generation_id': state.world_generation_id}
    source_bytes = {path.name: path.read_bytes() for path in directory.glob('*.json')}
    url = f'/api/simulation/{state.simulation_id}/translations/zh'
    result = client.post(url, json={'texts': [hidden], 'context': context})
    assert result.status_code == 202, result.json
    accepted = wait(client, url, request_digest=result.json['data']['request_digest'], context=json.dumps(context))
    assert accepted['status'] == 'available'
    calls = len(model.calls)
    assert client.post(url, json={'texts': [hidden], 'context': {**context, 'view': 'public'}}).status_code == 400
    assert client.post(url, json={'texts': [hidden], 'context': {**context, 'revision': 'obsolete'}}).status_code == 400
    assert client.post(url, json={'texts': [hidden], 'context': {**context, 'view': 'actor', 'actor_id': 'not-an-actor'}}).status_code == 400
    assert len(model.calls) == calls
    actor = simulation_translation_projection(state.simulation_id, {**context, 'view': 'actor', 'actor_id': 'producer'})
    assert actor['world']['view'] == 'actor' and actor['world']['actorId'] == 'producer'
    assert source_bytes == {path.name: path.read_bytes() for path in directory.glob('*.json')}


@pytest.mark.parametrize('engine', ['oasis', 'world-v1'])
def test_audited_completed_record_uses_same_simulation_service_and_preserves_canonical_facts(runtime, engine):
    client, model, root = runtime
    from app.services import simulation_record as sr, simulation_record_contract as rc, simulation_record_gate as gate
    from app.api.simulation import simulation_translation_projection
    if engine == 'oasis':
        from test_simulation_record_routes import _published_run
        directory = _published_run(root, 'sim_3ec25e64209e')
        sid = directory.name
    else:
        from test_world_service_results import prepare
        from app.services.world_simulation.examples import ExamplePolicy
        from app.services.world_simulation.service import run_child
        _, state, directory = prepare(root)
        sid = state.simulation_id
        assert run_child(directory, policy=ExamplePolicy('investment')) == 0
        record = sr.build_record(str(directory), language='en', synthesis=False)
        sr.write_record(str(directory), record)
        audit = gate.audit_record(str(directory), record)
        assert audit['publication_status'] == 'passed', audit['hard_issues']
    record, status = rc.load_published_record(str(directory))
    assert record and status == 'passed'
    context = {'surface': 'record', 'view': 'record', 'engine': 'world-v1' if engine == 'world-v1' else 'oasis-legacy',
               'round': record['periods'][0]['round'], 'revision': json.dumps([
                   record.get('config_hash') or '', record.get('generator_version') or '', record.get('generated_at') or ''
               ], separators=(',', ':'))}
    canonical = {path.name: path.read_bytes() for path in directory.glob('*') if path.is_file()}
    projected = simulation_translation_projection(sid, context)
    texts = [text for text in dict.fromkeys(at._projection_strings(projected.get('display', [])))
             if len(text) > 10 and not text.isdigit()]
    assert record['banner'] in texts, 'Actual record prose must reach the visible inventory'
    url = f'/api/simulation/{sid}/translations/zh'
    response = client.post(url, json={'texts': texts, 'context': context})
    assert response.status_code == 202, response.json
    result = wait(client, url, request_digest=response.json['data']['request_digest'], context=json.dumps(context))
    assert result['status'] == 'available', result
    assert any(row['source'] == record['banner'] for row in result['translations'])
    assert canonical == {path.name: path.read_bytes() for path in directory.glob('*') if path.is_file()}
    # Scope identity gates the record: it never leaks through a default live GET.
    live = client.get(url)
    assert live.status_code == 200 and all(row['source'] != record['banner'] for row in live.json['data']['translations'])
    calls = len(model.calls)
    assert client.get(url, query_string={'request_digest': result['request_digest'], 'context': '{}'}).status_code == 400
    assert client.post(url, json={'texts': ['An invented hidden setup instruction.'], 'context': context}).status_code == 400
    assert len(model.calls) == calls
    # Lose the publication seal: no previously accepted overlay can bypass it.
    (directory / rc.RECORD_AUDIT_JSON).unlink()
    assert client.get(url, query_string={'request_digest': result['request_digest'], 'context': json.dumps(context)}).status_code == 404


def test_selection_growth_reuses_only_the_same_source_and_visibility_pool(runtime, monkeypatch):
    _, model, root = runtime
    (root / 'sim_growth').mkdir()
    texts = ['One policy decision.', 'Another policy decision.']
    monkeypatch.setattr(at, '_simulation_projection', lambda sid, context: {'content': texts})
    first = at.simulation_translation('sim_growth', 'zh', texts=texts[:1], context={'view': 'public'})
    assert first['status'] == 'available'
    second = at.simulation_translation('sim_growth', 'zh', texts=texts, context={'view': 'public'})
    assert second['status'] == 'available' and model.generation_calls == 2
    assert list(model.calls[-2]['entries'].values()) == texts[1:]
    # Identical words under a different view do not import the public receipt.
    private = at.simulation_translation('sim_growth', 'zh', texts=texts, context={'view': 'analyst'})
    assert private['status'] == 'available' and model.generation_calls == 3
    assert len(model.calls[-2]['entries']) == 2


def test_explicit_post_repairs_corrupt_publication_after_completed_operation(runtime, monkeypatch):
    client, model, _ = runtime
    graph(monkeypatch, 2)
    url = '/api/graph/graph_tamper/translations/zh'
    client.post(url)
    first = wait(client, url)
    path = Path(at._inventory('graph', 'graph_tamper', 'zh')[0])
    cache = json.loads(path.read_text())
    cache['entries'] = {}
    path.write_text(json.dumps(cache))
    calls = len(model.calls)
    assert client.get(url).json['data']['pending'] == 2
    assert client.post(url).status_code == 202
    repaired = wait(client, url)
    assert repaired['status'] == 'available' and repaired['overlay'] == first['overlay']
    assert len(model.calls) == calls, 'Durable accepted receipts repair presentation without acquisition'


def test_direct_service_partial_can_resume_through_scheduler(runtime, monkeypatch):
    client, model, _ = runtime
    graph(monkeypatch, 40)
    real = at.translate_pairs
    monkeypatch.setattr(at, 'translate_pairs', lambda *a, **k: real(*a, **k, max_calls=2))
    first = at.graph_translation('graph_direct_partial', 'zh')
    assert first['pending'] == 22
    url = '/api/graph/graph_direct_partial/translations/zh'
    assert client.post(url).status_code == 202
    next_page = wait(client, url)
    assert next_page['pending'] == 4
    assert next_page['translation_job']['kind'] == 'artifact-overlay'


def test_upstream_truncated_graph_is_an_explicit_error(runtime, monkeypatch):
    client, model, _ = runtime
    data = graph(monkeypatch, 2)
    data.update(total_node_count=301, truncated=True)
    response = client.post('/api/graph/graph_upstream_cutoff/translations/zh')
    assert response.status_code == 400 and 'incomplete inventory' in response.json['error']
    assert model.calls == []


def test_oasis_visible_personas_feed_and_world_provenance_use_public_readers(runtime):
    client, model, root = runtime
    import sqlite3
    from app.api.simulation import simulation_translation_projection
    directory = root / 'sim_oasis_visible'
    directory.mkdir()
    (directory / 'state.json').write_text(json.dumps({'simulation_id': directory.name, 'simulation_engine': 'oasis-legacy'}))
    (directory / 'reddit_profiles.json').write_text(json.dumps([{'agent_id': 1, 'name': 'Public actor',
        'persona': 'The producer plans a capacity expansion.', 'private_notes': 'Never expose this hidden profile note.'}]))
    with sqlite3.connect(directory / 'reddit_simulation.db') as db:
        db.executescript('CREATE TABLE post(post_id INTEGER,user_id INTEGER,content TEXT);'
                         'CREATE TABLE comment(comment_id INTEGER,post_id INTEGER,user_id INTEGER,content TEXT);')
        db.execute('INSERT INTO post VALUES(1,1,?)', ('A public post with 25 MW.',))
        db.execute('INSERT INTO comment VALUES(1,1,1,?)', ('A public reply.',))
    (directory / 'world_state.json').write_text(json.dumps({'committed_round': 1,
        'world': {'question': 'Will capacity increase?', 'variables': [{'id': 'capacity', 'name': 'Capacity',
            'value': 25, 'unit': 'MW', 'provenance': 'A public planning estimate.',
            'history': [{'value': 20}, {'value': 25}]}]}}))
    sealed = {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}
    url = f'/api/simulation/{directory.name}/translations/zh'
    context = {'engine': 'oasis-legacy', 'view': 'public', 'platform': 'reddit'}
    feed_texts = ['The producer plans a capacity expansion.', 'A public post with 25 MW.', 'A public reply.']
    response = client.post(url, json={'texts': feed_texts, 'context': context})
    assert response.status_code == 202, response.json
    result = wait(client, url, request_digest=response.json['data']['request_digest'], context=json.dumps(context))
    assert result['status'] == 'available' and len(result['translations']) == 3
    assert client.post(url, json={'texts': ['Never expose this hidden profile note.'], 'context': context}).status_code == 400
    world_context = {'engine': 'oasis-legacy', 'view': 'public', 'platform': '', 'round': 1, 'revision': '1'}
    world = simulation_translation_projection(directory.name, world_context)
    assert {'text': '20 MW → 25 MW'} in world['display']
    response = client.post(url, json={'texts': ['A public planning estimate.', '20 MW → 25 MW'], 'context': world_context})
    assert response.status_code == 202, response.json
    result = wait(client, url, request_digest=response.json['data']['request_digest'], context=json.dumps(world_context))
    assert result['status'] == 'available'
    assert sealed == {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}


def test_duplicate_post_joins_while_provider_is_blocked(runtime, monkeypatch):
    client, _, _ = runtime
    import threading
    graph(monkeypatch, 2)
    entered, release = threading.Event(), threading.Event()
    class Held(Translator):
        def chat(self, *a, **k):
            entered.set()
            assert release.wait(8)
            return super().chat(*a, **k)
    model = Held()
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: model)
    url = '/api/graph/graph_join/translations/zh'
    first = client.post(url)
    assert first.status_code == 202 and entered.wait(3)
    duplicate = []
    def post():
        with client.application.test_client() as other:
            duplicate.append(other.post(url))
    second = threading.Thread(target=post)
    second.start()
    try:
        second.join(1)
        assert not second.is_alive(), 'Duplicate POST waited behind the provider worker'
        assert duplicate[0].json['data']['started'] is False
        assert duplicate[0].json['data']['translation_job']['job_id'] == first.json['data']['translation_job']['job_id']
    finally:
        release.set()
        second.join(5)
    assert wait(client, url)['status'] == 'available'
    assert model.generation_calls == 1


def test_cancelled_queued_refresh_preserves_pending_intent_and_plain_resume(runtime, monkeypatch):
    client, model, _ = runtime
    graph(monkeypatch, 2)
    url = '/api/graph/graph_queued_refresh/translations/zh'
    client.post(url)
    first = wait(client, url)
    scheduler.stop_schedulers()
    real_start = scheduler.start_scheduler
    monkeypatch.setattr(scheduler, 'start_scheduler', lambda: None)
    queued = client.post(url + '?force=1').json['data']
    assert queued['refresh_pending'] == 2 and queued['status'] == 'generating'
    scheduler.cancel(queued['translation_job']['job_id'])
    cancelled = client.get(url).json['data']
    assert cancelled['status'] == 'cancelled' and cancelled['refresh_pending'] == 2
    assert cancelled['overlay'] == first['overlay'] and cancelled['retryable']
    monkeypatch.setattr(scheduler, 'start_scheduler', real_start)
    assert client.post(url).status_code == 202
    final = wait(client, url)
    assert final['status'] == 'available' and final['refresh_pending'] == 0
    assert model.generation_calls == 2


def test_native_no_text_selection_reconnects_by_returned_digest(runtime):
    client, model, root = runtime
    directory = root / 'sim_native_reconnect'
    directory.mkdir()
    (directory / 'world_state.json').write_text(json.dumps({'committed_round': 1,
        'world': {'question': 'Will the policy change?', 'variables': []}}))
    url = f'/api/simulation/{directory.name}/translations/zh'
    response = client.post(url)
    assert response.status_code == 202
    result = wait(client, url, request_digest=response.json['data']['request_digest'], context='{}')
    assert result['status'] == 'available' and result['translations']
    assert client.get(url).json['data']['overlay'] == result['overlay']


def test_foreign_bound_receipt_cannot_be_rebound_through_cache_or_pool(runtime, monkeypatch):
    client, model, _ = runtime
    graph(monkeypatch, 2)
    url = '/api/graph/graph_foreign_receipt/translations/zh'
    client.post(url)
    first = wait(client, url)
    path = Path(at._inventory('graph', 'graph_foreign_receipt', 'zh')[0])
    cache = json.loads(path.read_text())
    for entry in cache['entries'].values():
        entry['receipt']['resource_scope_sha256'] = 'f' * 64
    path.write_text(json.dumps(cache))
    result = client.get(url).json['data']
    assert result['overlay'] == {} and result['pending'] == 2
    assert first['status'] == 'available'


def test_multi_page_refresh_activates_one_complete_replacement(runtime, monkeypatch):
    client, model, _ = runtime
    graph(monkeypatch, 220)
    url = '/api/graph/graph_atomic_refresh/translations/zh'
    client.post(url)
    initial = wait(client, url)
    assert initial['pending'] == 4
    client.post(url)
    initial = wait(client, url)
    assert initial['status'] == 'available'
    for row in initial['translations']:
        model.translations[row['source']] = '更新' + row['text']
    calls = len(model.calls)
    client.post(url + '?force=1')
    staged = wait(client, url)
    assert staged['refresh_pending'] == 4 and staged['pending'] == 0
    assert staged['overlay'] == initial['overlay'] and staged['continuation']['available']
    path, identity, _ = at._inventory('graph', 'graph_atomic_refresh', 'zh')
    pool_path = Path(path).parent / ('.validated-v2-' + at._digest(at._pool_identity(identity)) + '.json')
    pool = at._load_cache(str(pool_path))
    assert all(not row['text'].startswith('更新') for row in pool['entries'].values())
    client.post(url)
    final = wait(client, url)
    assert final['status'] == 'available' and final['refresh_pending'] == 0
    assert all(text.startswith('更新') for text in final['overlay'].values())
    refreshed = [key for event in model.calls[calls:] for key in event.get('entries', {})]
    assert len(refreshed) == len(set(refreshed)) == 220


@pytest.mark.parametrize('action', ['retry', 'new_refresh'])
def test_published_refresh_completion_failure_reconciles_or_explicitly_replaces(runtime, monkeypatch, action):
    client, model, _ = runtime
    from app.services.translation.contracts import TranslationError
    graph(monkeypatch, 2)
    url = '/api/graph/graph_publish_window/translations/zh'
    client.post(url)
    assert wait(client, url)['status'] == 'available'
    actual_handler = at._run_overlay
    failed = []
    def after_publish(payload):
        result = actual_handler(payload)
        if payload.get('refresh_generation') and not failed:
            failed.append(True)
            raise TranslationError('fixture_after_publication', 'Controlled completion failure.', retryable=True)
        return result
    monkeypatch.setattr(at, '_run_overlay', after_publish)
    client.post(url + '?force=1')
    published = wait(client, url)
    assert published['status'] == 'available' and published['translation_job']['job_state'] == 'failed'
    path, _, _ = at._inventory('graph', 'graph_publish_window', 'zh')
    generation = at._load_cache(path)['published_generation']
    calls = len(model.calls)
    task = published['translation_job']
    if action == 'retry':
        response = client.post(f"/api/translations/jobs/{task['job_id']}/retry", json={
            'job_revision': task['job_revision'], 'resource': {
                'kind': 'graph', 'ref_id': 'graph_publish_window', 'lang': 'zh',
                'request_digest': published['request_digest']}})
        assert response.status_code == 200, response.json
    else:
        response = client.post(url + '?force=1')
        assert response.status_code == 202, response.json
        assert response.json['data']['translation_job']['job_id'] != task['job_id']
    reconciled = wait(client, url)
    assert reconciled['translation_job']['job_state'] == 'completed'
    assert reconciled['overlay'] == published['overlay']
    assert len(model.calls) == calls + (0 if action == 'retry' else 2)
    assert at._load_cache(path)['published_generation'] == generation + (0 if action == 'retry' else 1)


def test_generic_overlay_actions_resolve_current_resource_view_and_source(runtime, monkeypatch):
    client, model, root = runtime
    (root / 'sim_control_scope').mkdir()
    source = {'text': 'A private policy plan.', 'quantity': 25}
    monkeypatch.setattr(at, '_simulation_projection', lambda sid, context: copy.deepcopy(source))
    scheduler.stop_schedulers()
    monkeypatch.setattr(scheduler, 'start_scheduler', lambda: None)
    context = {'view': 'analyst', 'revision': 'r1'}
    result = client.post('/api/simulation/sim_control_scope/translations/zh',
        json={'context': context, 'texts': [source['text']]}).json['data']
    task = result['translation_job']
    base = f"/api/translations/jobs/{task['job_id']}"
    resource = {'kind': 'simulation', 'ref_id': 'sim_control_scope', 'lang': 'zh',
                'request_digest': result['request_digest'], 'context': context}
    assert client.post(base + '/cancel', json={'job_revision': task['job_revision'],
        'resource': {**resource, 'context': {'view': 'public', 'revision': 'r1'}}}).status_code == 403
    assert client.post(base + '/cancel', json={'job_revision': task['job_revision'],
        'resource': {'identity': task.get('identity')}}).status_code == 403
    cancelled = client.post(base + '/cancel', json={'job_revision': task['job_revision'], 'resource': resource})
    assert cancelled.status_code == 200 and cancelled.json['data']['job_state'] == 'cancelled'
    revision = cancelled.json['data']['job_revision']
    source['quantity'] = 99
    assert client.post(base + '/retry', json={'job_revision': revision, 'resource': resource}).status_code == 403
    source['quantity'] = 25
    resumed = client.post(base + '/retry', json={'job_revision': revision, 'resource': resource})
    assert resumed.status_code == 200 and resumed.json['data']['job_state'] == 'queued'
    public_status = client.get(base).json['data']
    assert 'identity' not in public_status and 'result' not in public_status and model.calls == []
