"""Actual projected overlay GET and candidate resume in a new guarded interpreter."""
import json
import subprocess
import sys
from pathlib import Path


SOURCE = 'Public capacity is 25 MW.'
CONTEXT = {'engine': 'oasis-legacy', 'view': 'public', 'platform': '', 'round': 1, 'revision': '1'}


def _source(tmp_path, monkeypatch):
    from app.config import Config
    root = tmp_path / 'simulations'
    directory = root / 'sim_restarted'
    directory.mkdir(parents=True)
    (directory / 'world_state.json').write_text(json.dumps({
        'committed_round': 1, 'world': {'question': SOURCE, 'variables': []}}))
    monkeypatch.setattr(Config, 'OASIS_SIMULATION_DATA_DIR', str(root))
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(tmp_path / 'uploads'))
    return root


def _child(root, digest, output, action='--read'):
    result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()),
        action, str(root), digest, json.dumps(CONTEXT), str(output), str(root.parent / 'uploads')],
        capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr[-5000:]
    return json.loads(output.read_text())


def test_saved_visible_overlay_survives_real_guarded_interpreter_restart(tmp_path, monkeypatch):
    from app.services import artifact_translation as at
    from test_translation_pairs_integrity import Translator
    root = _source(tmp_path, monkeypatch)
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: Translator())
    initial = at.simulation_translation('sim_restarted', 'zh', texts=[SOURCE], context=CONTEXT)
    assert initial['status'] == 'available'
    restarted = _child(root, initial['request_digest'], tmp_path / 'read.json')
    assert restarted['status'] == 200 and restarted['data']['status'] == 'available'
    assert restarted['data']['translations'] == initial['translations']
    assert restarted['default_count'] == 0 and restarted['wrong_context_status'] == 400


def test_saved_unreviewed_candidate_resumes_review_after_real_process_restart(tmp_path, monkeypatch):
    from app.services import artifact_translation as at
    from test_translation_pairs_integrity import Translator
    root = _source(tmp_path, monkeypatch)
    class ReviewUnavailable(Translator):
        def chat(self, messages, **kwargs):
            if 'pairs' in json.loads(messages[-1]['content']):
                raise TimeoutError('controlled review interruption')
            return super().chat(messages, **kwargs)
    model = ReviewUnavailable()
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: model)
    first = at.simulation_translation('sim_restarted', 'zh', texts=[SOURCE], context=CONTEXT)
    assert first['pending'] == 1 and model.generation_calls == 1
    restarted = _child(root, first['request_digest'], tmp_path / 'resume.json', '--resume')
    assert restarted['data']['status'] == 'available'
    assert restarted['generation_calls'] == 0
    assert len(restarted['calls']) == 1 and 'pairs' in restarted['calls'][0]


if __name__ == '__main__':
    assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
    from app.config import Config
    import app.utils.llm_client as client_module
    Config.OASIS_SIMULATION_DATA_DIR = sys.argv[2]
    if len(sys.argv) > 6:
        Config.UPLOAD_FOLDER = sys.argv[6]
    if sys.argv[1] == '--read':
        class NoProvider:
            def __init__(self):
                raise AssertionError('Restart GET must never construct a provider client')
        client_module.LLMClient = NoProvider
        from app import create_app
        from app.services.translation.scheduler import stop_schedulers
        client = create_app().test_client()
        response = client.get('/api/simulation/sim_restarted/translations/zh',
            query_string={'request_digest': sys.argv[3], 'context': sys.argv[4]})
        default = client.get('/api/simulation/sim_restarted/translations/zh')
        wrong = client.get('/api/simulation/sim_restarted/translations/zh',
            query_string={'request_digest': sys.argv[3], 'context': json.dumps({'view': 'analyst'})})
        output = {'status': response.status_code, 'data': response.json['data'],
            'default_count': len(default.json['data']['translations']), 'wrong_context_status': wrong.status_code}
        stop_schedulers()
    else:
        assert sys.argv[1] == '--resume'
        from app.services import artifact_translation as at
        from test_translation_pairs_integrity import Translator
        model = Translator()
        client_module.LLMClient = lambda: model
        result = at.simulation_translation('sim_restarted', 'zh', texts=[SOURCE], context=CONTEXT)
        output = {'data': result, 'calls': model.calls, 'generation_calls': model.generation_calls}
    Path(sys.argv[5]).write_text(json.dumps(output))
