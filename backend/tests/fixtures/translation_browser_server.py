#!/usr/bin/env python3
"""Loopback-only real Flask translation fixture with the existing offline boundary.

Run using backend/.venv/bin/python -I -S -B. This extends only socket creation and
one exact listener bind; outbound connection, DNS, saved-data access, credentials,
external writes and unregistered children remain denied by the existing runner.
"""
from __future__ import annotations

import argparse
import atexit
import importlib.util
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[3]
GUARD_PATH = REPO / 'backend/scripts/main_offline_pytest.py'
spec = importlib.util.spec_from_file_location('translation_browser_base_guard', GUARD_PATH)
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)


class BrowserGuard(base.Guard):
    def __init__(self, root, port):
        super().__init__(root)
        self.endpoint = ('127.0.0.1', port)
        self.listener_bound = False

    def audit(self, event, args):
        if event == 'socket.__new__' and args[1] == 2 and args[2] & 0xF == 1:
            # Construction also occurs for sockets accepted by the sole listener.
            # connect/connect_ex, DNS and datagrams still hit the base denial.
            self.record('allowed:fixture_stream_socket')
            return
        if event == 'socket.bind' and args[1] == self.endpoint and not self.listener_bound:
            self.listener_bound = True
            self.record('allowed:fixture_listener', host=self.endpoint[0], port=self.endpoint[1])
            return
        return super().audit(event, args)


def controls(guard):
    import socket
    checks = {}
    def denied(name, operation):
        try:
            operation()
        except base.GuardViolation:
            checks[name] = 'blocked'
        else:
            raise AssertionError('Isolation negative control escaped: ' + name)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        denied('outbound_connection', lambda: sock.connect(('203.0.113.1', 443)))
    denied('outbound_dns', lambda: socket.getaddrinfo('fixture.invalid', 443))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        denied('wildcard_bind', lambda: sock.bind(('0.0.0.0', guard.endpoint[1])))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        denied('other_loopback_bind', lambda: sock.bind(('127.0.0.1', guard.endpoint[1] + 1)))
    denied('saved_data_write', lambda: (REPO / 'backend/uploads/translation_browser_negative_control.json').write_text('must never exist'))
    denied('external_write', lambda: (guard.root.parent / 'translation_browser_forbidden.txt').write_text('must never exist'))
    denied('credential_read', lambda: (REPO / '.env').read_bytes())
    (guard.root / 'negative-controls.json').write_text(json.dumps(checks, indent=2) + '\n')
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir', required=True, type=Path)
    parser.add_argument('--static-dir', type=Path)
    parser.add_argument('--port', type=int, default=18761)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if not sys.flags.isolated or not sys.flags.no_site:
        parser.error('Use the existing interpreter with -I -S -B')
    root = args.evidence_dir.absolute()
    if root.exists() or root.is_symlink() or root.parent.resolve() != root.parent:
        parser.error('evidence directory must be new, with a canonical existing parent')
    if args.port != 18761:
        parser.error('the only permitted fixture endpoint is 127.0.0.1:18761')
    guard = BrowserGuard(root, args.port)
    reason = guard.protected_reason(root)
    if reason:
        parser.error('evidence directory is protected: ' + reason)
    root.mkdir(mode=0o700)
    if args.static_dir:
        static = args.static_dir.resolve()
        if guard.protected_reason(static):
            parser.error('protected static directory')
        guard.read_roots.append(static)
    else:
        static = root / 'www'
    sys.modules['main_offline_guard'] = guard
    sys.addaudithook(guard.audit)
    guard.configure()
    atexit.register(guard.finish, parent=True, shutdown_complete=False)
    checks = controls(guard)
    import hashlib
    for path in [GUARD_PATH, Path(__file__)]:
        guard.source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    if args.self_test:
        guard.exit_code = 0
        atexit.unregister(guard.finish)
        guard.finish(parent=True, shutdown_complete=True)
        print(json.dumps({'negative_controls': checks, 'guard_receipt': str(root / 'completed.json')}), flush=True)
        return

    for folder in [REPO / 'backend/app', REPO / 'frontend/src', REPO / 'backend/tests/fixtures', REPO / 'frontend/tests/browser']:
        for path in folder.rglob('*'):
            if path.is_file() and path.suffix in {'.py', '.js', '.mjs', '.vue', '.html'}:
                if folder.name == 'fixtures' and not path.name.startswith('translation_browser_'):
                    continue
                guard.source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    for helper in ['model_translation_fakes.py', 'test_report_bilingual.py']:
        path = REPO / 'backend/tests' / helper
        guard.source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / 'source-hashes.json').write_text(json.dumps(guard.source_hashes, indent=2) + '\n')

    # No application/framework/provider imports occur before the guard and tests.
    sys.path[:0] = [str(REPO / 'backend/tests'), str(REPO / 'backend/tests/fixtures')]
    import copy
    import threading
    import time
    import pytest
    from flask import jsonify, request
    from model_translation_fakes import model_protocol, raw_fixture_zh
    from app.config import Config
    from app import create_app
    from app.services.translation import scheduler
    from app.services.translation.store import Store, database_path

    monkeypatch = pytest.MonkeyPatch()
    state_lock = threading.RLock()
    state = {'fail_provider': False, 'delay_provider': 0.015, 'faults': [], 'requests': []}

    class ControlledModel:
        model = 'browser-fixture-translation-reviewer'
        provider = 'controlled-fixture'
        def __init__(self):
            self.calls = []
        def render(self, source):
            return raw_fixture_zh(source)
        def chat(self, messages, **kwargs):
            payload = json.loads(messages[-1]['content'])
            with state_lock:
                fail, delay = state['fail_provider'], state['delay_provider']
                event = {'index': len(self.calls) + 1, 'failed': fail, 'payload': payload}
                self.calls.append(event)
                with (root / 'provider-calls.jsonl').open('a') as out:
                    out.write(json.dumps(event, ensure_ascii=False) + '\n')
            time.sleep(delay)
            if fail:
                raise RuntimeError('Controlled browser fixture provider unavailable')
            result = model_protocol(messages, self.render)
            if result is None:
                raise AssertionError('Unexpected model protocol in controlled browser fixture')
            return result

    model = ControlledModel()
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda *a, **kw: model)
    Config.TESTING = True
    Config.DEBUG = False
    Config.REPORT_PDF_EXPORT = True
    Config.REPORT_BILINGUAL = True
    os.environ['FRONTEND_DIST'] = str(static)
    app = create_app()
    ids, bootstrap = {}, {}

    def receipt():
        tasks, units = [], {}
        path = database_path()
        if path.exists():
            with Store(path, read_only=True) as store:
                tasks = [dict(row) for row in store.db.execute('SELECT id AS job_id,kind,state AS job_state,revision AS job_revision FROM tasks')]
                for row in store.db.execute('SELECT data FROM units'):
                    stage = json.loads(row[0]).get('stage', 'unknown')
                    units[stage] = units.get(stage, 0) + 1
        return {'schema': 'translation-browser-fixture/v1', 'ids': ids, 'provider_calls': len(model.calls),
                'provider_failures': sum(call['failed'] for call in model.calls),
                'tasks': tasks, 'units': units, 'requests': copy.deepcopy(state['requests']),
                'negative_controls': checks, 'guard': guard.receipt('serving'),
                'limits': ['controlled deterministic translation/review oracle, not live semantic quality',
                           'PDF browser transport uses fixture renderer; real layout tested separately']}

    @app.before_request
    def fixture_faults():
        if request.path.startswith('/api/'):
            with state_lock:
                state['requests'].append({'method': request.method, 'path': request.path,
                    'query': dict(request.args), 'body': request.get_json(silent=True)})
                match = next((fault for fault in state['faults'] if fault['count'] > 0 and fault['path'] == request.path
                              and request.method == 'GET'), None)
                if match:
                    match['count'] -= 1
                    if match.get('delay'):
                        time.sleep(match['delay'])
                    if match.get('status'):
                        return jsonify(success=False, error='Controlled read interruption'), match['status']

    @app.get('/__fixture/bootstrap')
    def fixture_bootstrap():
        return jsonify(bootstrap)

    @app.get('/__fixture/receipt')
    def fixture_receipt():
        return jsonify(receipt())

    @app.post('/__fixture/control')
    def fixture_control():
        command = request.get_json(force=True)
        action = command.get('action')
        with state_lock:
            if action == 'fail_provider':
                state['fail_provider'] = command.get('value') is True
            elif action == 'delay_provider':
                state['delay_provider'] = min(0.5, max(0, float(command.get('seconds', 0))))
            elif action in {'fail_get', 'delay_get'}:
                path = command.get('path', '')
                if not path.startswith('/api/') or 'translations/' not in path:
                    return jsonify(error='Only translation GET routes can be interrupted'), 400
                state['faults'].append({'path': path, 'count': min(5, max(1, int(command.get('count', 1)))),
                    'status': 503 if action == 'fail_get' else None,
                    'delay': min(2, max(0, float(command.get('seconds', 0)))) if action == 'delay_get' else 0})
            elif action == 'shutdown':
                threading.Thread(target=server.shutdown, daemon=True).start()
            else:
                return jsonify(error='Unknown fixture action'), 400
        return jsonify(ok=True)

    from translation_browser_documents import install_documents
    from translation_browser_simulations import install_simulations
    documents = install_documents(root, monkeypatch, app, model)
    simulations = install_simulations(root, monkeypatch, app, model)
    ids = {'pipeline': documents.get('pipeline_id', 'pipe_browser'), 'report': documents.get('report_id', 'report_browser'),
           **simulations['ids']}
    bootstrap = {'dossier': documents['dossier'], 'graph': simulations['graph'], 'ids': ids}

    from socketserver import ThreadingMixIn, TCPServer
    from wsgiref.simple_server import WSGIServer, WSGIRequestHandler
    class FixtureServer(ThreadingMixIn, WSGIServer):
        daemon_threads = True
        active_requests = 0
        request_lock = threading.Lock()
        def process_request(self, *args):
            # Count before dispatch: a newly spawned thread may not yet run when
            # another request asks the main loop to shut down.
            with self.request_lock:
                self.active_requests += 1
            try:
                return super().process_request(*args)
            except BaseException:
                with self.request_lock:
                    self.active_requests -= 1
                raise
        def process_request_thread(self, *args):
            try:
                return super().process_request_thread(*args)
            finally:
                with self.request_lock:
                    self.active_requests -= 1
        def request_count(self):
            with self.request_lock:
                return self.active_requests
        def server_bind(self):
            TCPServer.server_bind(self)
            self.server_name, self.server_port = guard.endpoint
            self.setup_environ()
    class Handler(WSGIRequestHandler):
        def log_message(self, fmt, *values):
            print('HTTP ' + (fmt % values), flush=True)
    server = FixtureServer(guard.endpoint, Handler)
    server.set_app(app)
    print(json.dumps({'ready': True, 'url': f'http://127.0.0.1:{args.port}', 'root': str(root), 'ids': ids}), flush=True)
    guard.receipt('started')
    clean_serve = False
    try:
        server.serve_forever(poll_interval=0.1)
        clean_serve = True
    finally:
        # Stop acceptance first, then prove request/dispatcher quiescence. A
        # timeout or serving exception is a failed receipt, never clean success.
        deadline = time.monotonic() + 10
        while server.request_count() and time.monotonic() < deadline:
            time.sleep(0.05)
        scheduler.stop_schedulers(timeout=15)
        with scheduler._guard:
            alive = [thread.name for thread in scheduler._threads.values() if thread.is_alive()]
        requests_alive = server.request_count()
        quiet = requests_alive == 0 and not alive
        server.server_close()
        final = receipt()
        final['shutdown'] = {'serve_returned_normally': clean_serve, 'active_requests': requests_alive,
                             'live_scheduler_threads': alive, 'quiescent': quiet}
        (root / 'browser-server-receipt.json').write_text(json.dumps(final, ensure_ascii=False, indent=2) + '\n')
        guard.exit_code = 0 if clean_serve and quiet else 1
        atexit.unregister(guard.finish)
        guard.finish(parent=True, shutdown_complete=quiet)
        if not clean_serve or not quiet:
            raise RuntimeError('Fixture shutdown did not finish cleanly; inspect the failed receipt')


if __name__ == '__main__':
    main()
