"""Read a source/context-bound overlay in a separate interpreter under the same guard."""
import json
import subprocess
import sys
from pathlib import Path


def test_saved_visible_overlay_survives_real_guarded_interpreter_restart(tmp_path, monkeypatch):
    from app.services import artifact_translation as at
    from app.config import Config
    from test_translation_pairs_integrity import Translator
    root = tmp_path / 'simulations'
    directory = root / 'sim_restarted'
    directory.mkdir(parents=True)
    monkeypatch.setattr(Config, 'OASIS_SIMULATION_DATA_DIR', str(root))
    monkeypatch.setattr('app.utils.llm_client.LLMClient', lambda: Translator())
    context = {'engine': 'world-v1', 'view': 'analyst', 'round': 1, 'revision': 'r1',
               'generation_id': 'g1', 'actor_id': None}
    initial = at.simulation_translation('sim_restarted', 'zh', texts=['Private capacity is 25 MW.'], context=context)
    assert initial['status'] == 'available'
    output = tmp_path / 'child-result.json'
    result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()),
        '--read', str(root), initial['request_digest'], json.dumps(context), str(output)],
        capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr[-5000:]
    restarted = json.loads(output.read_text())
    assert restarted['status'] == 200 and restarted['data']['status'] == 'available'
    assert restarted['data']['translations'] == initial['translations']
    assert restarted['default_count'] == 0
    assert restarted['wrong_context_status'] == 400


if __name__ == '__main__':
    assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
    assert sys.argv[1] == '--read'
    from app import create_app
    from app.config import Config
    import app.utils.llm_client as client_module
    class NoProvider:
        def __init__(self):
            raise AssertionError('Restart GET must never construct a provider client')
    client_module.LLMClient = NoProvider
    Config.OASIS_SIMULATION_DATA_DIR = sys.argv[2]
    client = create_app().test_client()
    response = client.get('/api/simulation/sim_restarted/translations/zh',
        query_string={'request_digest': sys.argv[3], 'context': sys.argv[4]})
    default = client.get('/api/simulation/sim_restarted/translations/zh')
    wrong = client.get('/api/simulation/sim_restarted/translations/zh',
        query_string={'request_digest': sys.argv[3], 'context': json.dumps({'view': 'public'})})
    Path(sys.argv[5]).write_text(json.dumps({'status': response.status_code,
        'data': response.json['data'], 'default_count': len(default.json['data']['translations']),
        'wrong_context_status': wrong.status_code}))
