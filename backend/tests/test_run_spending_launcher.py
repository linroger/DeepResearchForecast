"""Synthetic-only acceptance of the private launcher, under the offline guard.

No provider, real authorization, credential discovery or dependency provisioning.
"""
import contextvars
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
import types


def _load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _stage_private_startup(evidence):
    """Explicitly requested offline copies; no application/dependency execution."""
    import hashlib
    import stat
    evidence = Path(evidence)
    assert evidence.is_absolute() and evidence.parent.resolve() == evidence.parent and not evidence.exists()
    evidence.mkdir(mode=0o700)
    repo = Path(__file__).resolve().parents[2]
    distribution = Path('/Users/rogerlin/.local/share/uv/python/cpython-3.12.6-macos-aarch64-none')
    bundle = Path('/private/tmp/run-spending-langchain-proof-20261029-01')
    installed_harness = Path('/Users/rogerlin/Downloads/DeepResearchForecast/deer-flow')
    prefix, source = evidence / 'python', evidence / 'source'
    prefix.mkdir(mode=0o700)
    source.mkdir(mode=0o700)
    originals = {}

    def copy_file(origin, dest, expected=None, *, boundary=None):
        resolved = origin.resolve()
        assert boundary is None or resolved.is_relative_to(boundary)
        info = resolved.stat()
        assert stat.S_ISREG(info.st_mode)
        content = resolved.read_bytes()
        sha = hashlib.sha256(content).hexdigest()
        assert expected is None or sha == expected
        dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        dest.write_bytes(content)
        dest.chmod(0o500 if info.st_mode & 0o111 else 0o400)
        originals[str(resolved)] = {'sha256': sha, 'mode': stat.S_IMODE(info.st_mode)}
        return sha

    copy_file(distribution / 'bin/python3.12', prefix / 'bin/python3.12', boundary=distribution)
    for folder, dirs, names in os.walk(distribution / 'lib', followlinks=False):
        dirs[:] = [d for d in dirs if d not in {'site-packages', '__pycache__'}]
        for name in names:
            if name.endswith(('.pyc', '.pyo', '.pth')):
                continue
            origin = Path(folder) / name
            copy_file(origin, prefix / origin.relative_to(distribution), boundary=distribution)
    pins = json.loads((bundle / 'package-pins.json').read_text())['files']
    for name, sha in pins.items():
        assert hashlib.sha256((bundle / name).read_bytes()).hexdigest() == sha
    assert pins['proof.py'] == 'da6482cd6df0f4109006de59ab99f54883f8419edda5279e16b46ca33a2127d0'
    assert pins['dependencies.json'] == '36ba5f3487f15ea88e0dee910fb62bc8390d677fa17a39bbac5d8d72cd52297c'
    dependencies = json.loads((bundle / 'dependencies.json').read_text())
    site = prefix / 'lib/python3.12/site-packages'
    for name, row in dependencies['files'].items():
        copy_file(bundle / 'site-packages' / name, site / name, row['sha256'], boundary=bundle / 'site-packages')
    # Reuse the child owner's exact transport proof and dependencies once.
    copy_file(bundle / 'proof.py', source / 'backend/tests/sdk_proof.py', pins['proof.py'])
    selected = [repo / 'backend/scripts/target_acceptance_run.py', repo / 'backend/scripts/main_offline_pytest.py', Path(__file__).resolve()]
    for directory in (repo / 'backend/app', repo / 'deerflow_bridge'):
        for folder, dirs, names in os.walk(directory, followlinks=False):
            dirs[:] = [d for d in dirs if d not in {'__pycache__', 'uploads', 'logs', '.git', '.venv'}]
            for name in names:
                if name.endswith(('.py', '.json', '.md', '.txt')) and not name.startswith('.env'):
                    selected.append(Path(folder) / name)
    for origin in selected:
        copy_file(origin, source / origin.relative_to(repo), boundary=repo)
    app_files = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in source.rglob('*') if p.is_file()}
    harness_files = {}
    for folder, dirs, names in os.walk(installed_harness / 'backend/packages/harness/deerflow', followlinks=False):
        dirs[:] = [d for d in dirs if d not in {'__pycache__', 'logs', 'uploads', '.env', '.git', '.venv'}]
        for name in names:
            if name.endswith(('.py', '.json', '.md', '.txt')) and not name.startswith('.env'):
                origin = Path(folder) / name
                assert not origin.is_symlink()
                harness_files[str(origin.relative_to(installed_harness))] = hashlib.sha256(origin.read_bytes()).hexdigest()
    launcher = _load_file('staging_launcher', repo / 'backend/scripts/target_acceptance_run.py')
    model = {'provider': 'glm', 'alias': 'glm', 'name': 'glm-5.3', 'endpoint': 'https://model.invalid/v1',
             'input_ceiling': 1000, 'max_output_tokens': 128000}
    request = {'prompt': 'Synthetic startup capacity forecast', 'mode': 'full', 'depth': 'quick', 'language': 'English',
               'model': 'glm', 'forecast_authority': 'target-first-v1', 'target_simulation': {'paths': 1, 'periods': 1, 'seed': 7}}
    spec = {'schema': 'target-acceptance-prepare/v1', 'python': str(prefix / 'bin/python3.12'),
            'python_sha256': hashlib.sha256((prefix / 'bin/python3.12').read_bytes()).hexdigest(),
            'app_files': app_files, 'deerflow_files': harness_files, 'request': request, 'model': model,
            'dependencies': [{'path': str(site), 'files': launcher.tree_files(site)},
                             {'path': str(prefix / 'lib'), 'files': launcher.tree_files(prefix / 'lib')}]}
    spec_path = evidence / 'prepare-spec.json'
    spec_path.write_bytes(launcher.canonical(spec))
    os.chdir(evidence)
    launcher.prepare(source, installed_harness, evidence / 'runtime', spec_path)
    (evidence / 'runtime/spend/fixture-context.json').write_text(json.dumps({
        'guard_runner': str(repo / 'backend/scripts/main_offline_pytest.py')}))
    receipt = {'python': str(prefix / 'bin/python3.12'), 'root': str(evidence / 'runtime'),
               'dependency_manifest_sha256': pins['dependencies.json'], 'proof_sha256': pins['proof.py'],
               'original_files': originals}
    (evidence / 'staging.json').write_text(json.dumps(receipt, sort_keys=True))
    print(json.dumps({'status': 'staged_offline_copy', 'python': receipt['python'], 'root': receipt['root']}))
    return 0


def _private_authority(launcher, core, root, checked):
    key = 'offline-synthetic-credential'
    common = {'account_sha256': launcher.digest(key.encode()), 'basis_sha256': core.hash_payload('synthetic-only'),
              'coverage': 'all_billable_dimensions'}
    routes = {'model': {**common, 'kind': 'openai_chat', 'endpoint': checked['model']['endpoint'], 'model': 'glm-5.3',
                       'billing_class': 'external_model', 'input_bound': 'enforced_context_ceiling',
                       'input_ceiling': 1000, 'max_output_tokens': 128000, 'max_tool_units': 0,
                       'pricing': {'input_usd_per_million': '1', 'output_usd_per_million': '2', 'tool_usd_per_unit': '0',
                                   'fixed_usd': '0', 'surcharge_usd': '0'}}}
    for name, units in (('search', 5), ('scrape', 1)):
        routes[name] = {**common, 'kind': 'firecrawl_' + name, 'endpoint': 'https://api.firecrawl.dev/v2/' + name,
                        'model': '', 'billing_class': 'external_tool', 'input_bound': 'not_applicable',
                        'input_ceiling': 0, 'max_output_tokens': 0, 'max_tool_units': units,
                        'pricing': {'input_usd_per_million': '0', 'output_usd_per_million': '0', 'tool_usd_per_unit': '0.01',
                                    'fixed_usd': '0', 'surcharge_usd': '0'}}
    manifest = {'schema': 'target-run-spending/v1', 'authorization_id': 'synthetic-private-bootstrap', 'root': str(root),
                'currency': 'USD', 'cap_usd': '1.00', 'request_sha256': core.hash_payload(checked['request']),
                'source_files': checked['source_files'], 'source_sha256': core.hash_payload(checked['source_files']),
                'routes': routes, 'routes_sha256': core.hash_payload(routes), 'resume_policy': 'explicit_clean_only'}
    launcher.qualify_manifest(core, checked, manifest)
    launcher.write_new(root / 'spend/authorization.json', launcher.canonical(manifest))
    registry = Path(sys.base_prefix) / 'synthetic-archive'
    registry.mkdir(mode=0o700)
    return core.create_authorization(root / 'spend/authorization.json', registry_dir=registry)


def _private_parent(root):
    """Store-only setup, then unchanged Guard before all app/SDK imports."""
    import atexit
    import subprocess
    root = Path(root)
    launcher = _load_file('private_launcher', root / 'app/backend/scripts/target_acceptance_run.py')
    checked = launcher.verify(root)
    core = launcher.load_core(root)
    binding = _private_authority(launcher, core, root, checked)
    with core.run_lock(binding):
        binding = core.bind_pipeline(binding, 'pipe-private-startup', checked['request'])
        core.activate_binding(binding)
        fixture = json.loads((root / 'spend/fixture-context.json').read_text())
        runner = _load_file('offline_runner_for_fixture', fixture['guard_runner'])
        guard = runner.Guard(root)
        sys.modules['main_offline_guard'] = guard
        sys.addaudithook(guard.audit)
        atexit.register(guard.finish, parent=True, shutdown_complete=True)
        guard.configure()
        driver = root / 'app/backend/tests/test_run_spending_launcher.py'
        guard.allow_python_script(driver)
        guard.source_hashes[str(driver)] = launcher.digest(driver.read_bytes())
        guard.source_hashes[str(root / launcher.LAUNCHER)] = checked['source_files'][launcher.LAUNCHER]
        guard.receipt('started')
        keys = {'LLM_API_KEY': 'offline-synthetic-credential', 'FIRECRAWL_API_KEY': 'offline-synthetic-credential'}
        env = {**os.environ, **launcher.controlled_environment(root, checked), **keys}
        handoff = root / 'app/backend/uploads/pipelines/pipe-private-startup/handoff'
        handoff.mkdir(parents=True)
        (handoff / 'prompt.txt').write_text(checked['request']['prompt'])
        env.update(RESEARCH_BUDGET_RUN_ID=binding['pipeline_id'], RESEARCH_BUDGET_LANE_ID='outer-track-1',
                   RESEARCH_BUDGET_EPOCH='task-private-startup', DEERFLOW_RUN_ARTIFACT_DIR=str(handoff),
                   RESEARCH_BUDGET_DB=str(handoff / 'count-budget.sqlite3'),
                   RESEARCH_BUDGET_TELEMETRY_PATH=str(handoff / 'count-budget.json'))
        statuses = {}
        try:
            for case in ('app', 'child'):
                if case == 'child':
                    with core.operation('research', 'private-bootstrap-root'):
                        carrier = core.register_participant(binding, 'research-bootstrap',
                            spawn_receipt_sha256=core.hash_payload('private-executable-spawn'))
                        env.update(core.export_environment(carrier))
                else:
                    env.update(core.export_environment(binding))
                process = subprocess.run([sys.executable, '-B', str(driver), '--private-case', case, str(root)],
                                         env=env, cwd=root, capture_output=True, text=True, timeout=120)
                (root / f'{case}-stdout.txt').write_text(process.stdout)
                (root / f'{case}-stderr.txt').write_text(process.stderr)
                statuses[case] = process.returncode
                if case == 'child':
                    core.participant_exited(binding, 'research-bootstrap',
                        exit_receipt_sha256=core.hash_payload({'exit': process.returncode}))
                assert process.returncode == 0, f'private {case} startup refused; inspect private evidence'
            summary = core.summary(binding)
            assert summary['attempt_count'] == 8 and summary['reserved_max_microusd'] == 66112
            core.close_run(binding)
            (root / 'private-startup-result.json').write_text(json.dumps({'status': 'passed', 'cases': statuses,
                'summary': core.summary(binding), 'python': sys.executable, 'base_prefix': sys.base_prefix}, sort_keys=True))
            guard.exit_code = 0
        finally:
            guard.finish(parent=True)
    return 0


def _private_case(case, root):
    """The existing GuardedPopen starts this with real copied Python -I -S -B."""
    root = Path(root)
    guard = sys.modules['main_offline_guard']
    assert guard.configured and sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
    original_record = guard.record
    def observe_denial(kind, **details):
        # Passive source attribution only: the unchanged guard still makes and
        # records every decision. Never inspect args, locals or credentials.
        if kind.startswith('blocked:'):
            frames, frame = [], sys._getframe(1)
            while frame is not None and len(frames) < 18:
                frames.append({'file': frame.f_code.co_filename, 'function': frame.f_code.co_name,
                               'line': frame.f_lineno})
                frame = frame.f_back
            with (root / ('probe-origins-' + str(os.getpid()) + '.jsonl')).open('a') as stream:
                stream.write(json.dumps({'event': kind, 'frames': frames}) + '\n')
        return original_record(kind, **details)
    guard.record = observe_denial
    launcher = _load_file('private_launcher', root / 'app/backend/scripts/target_acceptance_run.py')
    checked = launcher.verify(root)
    if case == 'app':
        binding = json.loads(os.environ['DRF_RUN_SPENDING_BINDING'])
        launcher.setup_execution(root, checked,
            {key: os.environ[key] for key in ('LLM_API_KEY', 'FIRECRAWL_API_KEY')},
            {key: os.environ[key] for key in launcher.CARRIERS if key in os.environ}, binding['registry_dir'])
        from app.config import Config
        from app.services.pipeline_orchestrator import PipelineOrchestrator, PipelineManager
        import app.services.run_spending  # noqa: F401 -- Exercise the real application import boundary.
        assert Config.DEERFLOW_MODEL == 'glm' and Config.LLM_MODEL_NAME == 'glm-5.3'
        pipeline_path = Path(PipelineManager.handoff_dir('pipe_0123456789ab'))
        assert pipeline_path == root / 'app/backend/uploads/pipelines/pipe_0123456789ab/handoff'
        PipelineManager.ensure_dirs('pipe_0123456789ab')
        assert pipeline_path.is_dir()
        (root / 'actual-app-imports.json').write_text(json.dumps({'status': 'imported', 'pipeline': PipelineOrchestrator.__module__,
            'origins': {name: getattr(module, '__file__', None) for name, module in sys.modules.copy().items()
                        if name.startswith('app.')}}))
        return 0
    script = root / launcher.CHILD
    handoff = root / 'app/backend/uploads/pipelines/pipe-private-startup/handoff'
    argv = ['--', str(script), '--prompt-file', str(handoff / 'prompt.txt'), '--out-dir', str(handoff),
            '--model', 'glm', '--depth', 'quick', '--forecast-authority', 'target-first-v1', '--target-language', 'English', '--subagents']
    saved_metadata = {key: os.environ[key] for key in ('RESEARCH_BUDGET_RUN_ID', 'RESEARCH_BUDGET_LANE_ID', 'RESEARCH_BUDGET_EPOCH',
                      'DEERFLOW_RUN_ARTIFACT_DIR', 'RESEARCH_BUDGET_DB', 'RESEARCH_BUDGET_TELEMETRY_PATH')}
    source_bridge = []

    def fake_research_stage(question, out_dir, args, meta, plog, write_meta):
        # Enter the actual v3 run admission (including the in-memory request
        # check), replacing only its long-running engine with the bounded SDK
        # exercise. The real factory/SDK/gateway use HTTP MockTransport only.
        import run_spending as core
        from deerflow_bridge import linear_research
        assert args.subagents is True and args.model == 'glm'
        assert all(os.environ.get(key) == value for key, value in saved_metadata.items())
        assert callable(linear_research._validate_spending_request)
        result = {}
        class AdapterExercise:
            def __init__(self, actual_question, *engine_args):
                assert actual_question == checked['request']['prompt']
                result['in_memory_request_checked_before_engine'] = True

            def execute(self):
                from deerflow.config import get_app_config
                config = get_app_config()
                assert config.get_model_config('glm').model == 'glm-5.3'
                proof = _load_file('private_sdk_proof', root / 'app/backend/tests/sdk_proof.py')
                real_factory = linear_research._bound_chat_model
                linear_research._bound_chat_model = lambda arguments, app_config=None: real_factory(arguments, config)
                try:
                    result.update(proof.run_proof(out_dir / 'sdk-proof', core.check_context()))
                finally:
                    linear_research._bound_chat_model = real_factory
                result.update({'python': sys.executable, 'no_site': bool(sys.flags.no_site), 'isolated': bool(sys.flags.isolated),
                               'argv_preserved': sys.argv == argv[1:], 'execution_metadata': saved_metadata,
                               'imports': proof.pin_loaded_dependencies(Path(sys.base_prefix) / 'lib/python3.12/site-packages'),
                               'harness_origins': {name: getattr(module, '__file__', None) for name, module in sys.modules.copy().items()
                                                   if name.startswith('deerflow.')}})
                (out_dir / 'actual-child-startup.json').write_text(json.dumps(result, sort_keys=True))
                meta.update(status='completed')
                return 0

            def attach_telemetry(self):
                return None

            def cancel(self):
                return None
        original_engine = linear_research._Engine
        linear_research._Engine = AdapterExercise
        try:
            code = linear_research.run(question, out_dir, args, meta, plog, write_meta, bridge=source_bridge[0]())
        finally:
            linear_research._Engine = original_engine
        plog.close()
        assert code == 0 and result['in_memory_request_checked_before_engine']
        return code

    def hook(frame, event, arg):
        if event == 'call' and frame.f_code.co_filename == str(script) and frame.f_code.co_name == 'main':
            source_bridge.append(frame.f_globals['_bridge_module'])
            frame.f_globals['_dispatch_v3_engine'] = fake_research_stage
            sys.settrace(None)
        return hook

    # The actual script uses os._exit to skip stuck SDK thread joins. Convert
    # only that exit in this fixture so the unchanged Guard can finish receipts.
    def observed_exit(code):
        raise SystemExit(code)
    os._exit = observed_exit
    sys.settrace(hook)
    launcher.child(argv)
    return 0


if __name__ == '__main__':
    if sys.argv[1] == '--stage-private':
        raise SystemExit(_stage_private_startup(sys.argv[2]))
    if sys.argv[1] == '--private-parent':
        raise SystemExit(_private_parent(sys.argv[2]))
    if sys.argv[1] == '--private-case':
        raise SystemExit(_private_case(sys.argv[2], sys.argv[3]))
    raise SystemExit('unknown offline fixture mode')

import pytest

from app.services.official_data import bridge_module

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "backend/scripts/target_acceptance_run.py"
spec = importlib.util.spec_from_file_location("spending_launcher_tested", SCRIPT)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
core = bridge_module("run_spending")
pytestmark = pytest.mark.guarded_runner


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else launcher.canonical(value))
    path.chmod(0o600)


@pytest.fixture(autouse=True)
def isolation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Broad collection imports tokenizer libraries that set this process hint.
    # Each launcher case starts with its own explicit environment; production
    # rejection remains strict and has a separate control below.
    monkeypatch.delenv("TOKENIZERS_PARALLELISM", raising=False)
    for name in list(os.environ):
        if name.startswith("DRF_RUN_SPENDING_"):
            monkeypatch.delenv(name)
    for name, value in {"_REQUIRED": False, "_ACTIVE_AUTH": None, "_ENV_PIN": None, "_LOCAL_STOPS": {},
                        "_binding": contextvars.ContextVar("launcher_test_binding", default=None),
                        "_operation": contextvars.ContextVar("launcher_test_operation", default=None)}.items():
        monkeypatch.setattr(core, name, value)


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    # Synthetic interpreter identity only; no executable is launched. The
    # installed test interpreter is group-writable and intentionally would not
    # qualify as a private future-run executable without separate provisioning.
    python = tmp_path / "synthetic-python"
    put(python, b"synthetic interpreter identity; never executed\n")
    python.chmod(0o700)
    monkeypatch.setattr(sys, "executable", str(python))
    source, harness, dependencies = [tmp_path / name for name in ("source", "harness", "dependencies")]
    for folder in (source, harness, dependencies):
        folder.mkdir(mode=0o700)
    app = {
        "backend/scripts/target_acceptance_run.py": SCRIPT.read_bytes(),
        "backend/app/config.py": b"# fake config\n",
        "backend/app/services/run_spending.py": b"# fake lifecycle\n",
        "backend/app/services/pipeline_orchestrator.py": b"# fake orchestrator\n",
        "deerflow_bridge/run_spending.py": (REPO / "deerflow_bridge/run_spending.py").read_bytes(),
        "deerflow_bridge/deerflow_research.py": b"# fake research entrypoint\n",
    }
    for name, raw in app.items():
        put(source / name, raw)
    put(harness / "backend/packages/harness/deerflow/__init__.py", b"# fake harness\n")
    put(harness / "backend/packages/harness/deerflow/config/__init__.py", b"# fake config\n")
    put(dependencies / "synthetic_dependency.py", b"VALUE = 'synthetic'\n")
    request = {"prompt": "Synthetic forecast only", "mode": "full", "depth": "quick", "language": "English",
               "model": "glm", "forecast_authority": "target-first-v1", "target_simulation": {"paths": 1, "periods": 1, "seed": 7}}
    model = {"provider": "glm", "alias": "glm", "name": "glm-5.3", "endpoint": "https://synthetic.invalid/v1",
             "input_ceiling": 100, "max_output_tokens": 100}
    data = {"schema": "target-acceptance-prepare/v1", "python": str(Path(sys.executable).resolve()),
            "python_sha256": launcher.digest(Path(sys.executable).resolve().read_bytes()),
            "app_files": {k: launcher.digest(v) for k, v in app.items()},
            "deerflow_files": launcher.tree_files(harness),
            "dependencies": [{"path": str(dependencies), "files": launcher.tree_files(dependencies)}],
            "request": request, "model": model}
    spec_path, root = tmp_path / "spec.json", tmp_path / "runtime"
    put(spec_path, data)
    checked = launcher.prepare(source, harness, root, spec_path)
    return types.SimpleNamespace(root=root, source=source, harness=harness, dependencies=dependencies,
                                 spec_path=spec_path, spec=data, checked=checked)


def manifest_for(prepared):
    checked = prepared.checked
    route = {"kind": "openai_chat", "endpoint": checked["model"]["endpoint"], "model": "glm-5.3",
             "account_sha256": launcher.digest(b"synthetic-model-key"), "billing_class": "external_model",
             "basis_sha256": core.hash_payload("synthetic qualification only"), "input_bound": "enforced_context_ceiling",
             "input_ceiling": 100, "max_output_tokens": 100, "max_tool_units": 0,
             "pricing": {"input_usd_per_million": "1", "output_usd_per_million": "2", "tool_usd_per_unit": "0",
                         "fixed_usd": "0", "surcharge_usd": "0"}, "coverage": "all_billable_dimensions"}
    routes = {"model": route}
    for name in ("search", "scrape"):
        routes[name] = {**route, "kind": "firecrawl_" + name, "endpoint": "https://api.firecrawl.dev/v2/" + name,
                        "model": "", "billing_class": "external_tool", "account_sha256": launcher.digest(b"synthetic-tool-key"),
                        "input_bound": "not_applicable", "input_ceiling": 0, "max_output_tokens": 0, "max_tool_units": 1,
                        "pricing": {**route["pricing"], "input_usd_per_million": "0", "output_usd_per_million": "0",
                                    "tool_usd_per_unit": "0.01"}}
    return {"schema": "target-run-spending/v1", "authorization_id": "synthetic-launcher-only", "root": str(prepared.root),
            "currency": "USD", "cap_usd": "1.00", "request_sha256": core.hash_payload(checked["request"]),
            "source_files": checked["source_files"], "source_sha256": core.hash_payload(checked["source_files"]),
            "routes": routes, "routes_sha256": core.hash_payload(routes), "resume_policy": "explicit_clean_only"}


def authorize(prepared, tmp_path):
    manifest = manifest_for(prepared)
    put(prepared.root / "spend/authorization.json", manifest)
    registry = tmp_path / "registry"
    registry.mkdir(mode=0o700)
    binding = core.create_authorization(prepared.root / "spend/authorization.json", registry_dir=registry)
    put(prepared.root / "spend/binding.json", binding)
    return manifest, binding, registry


def credentials():
    return {"LLM_API_KEY": "synthetic-model-key", "FIRECRAWL_API_KEY": "synthetic-tool-key"}


def test_prepare_is_new_private_provider_free_and_no_authority(prepared):
    root = prepared.root
    assert (root.stat().st_mode & 0o777) == 0o700
    assert {p.name for p in (root / "spend").iterdir()} == {"runtime.json"}
    assert not (root / "spend/run.sqlite3").exists()
    assert prepared.checked["runtime"]["python"] == str(Path(sys.executable).resolve())
    assert launcher.verify(root) == prepared.checked
    with pytest.raises(launcher.LauncherStop, match="runtime_exists"):
        launcher.prepare(prepared.source, prepared.harness, root, prepared.spec_path)


@pytest.mark.parametrize("newline", ["\r", "\r\n"])
def test_cr_prompt_is_rejected_before_private_preparation(prepared, tmp_path, newline):
    spec = json.loads(launcher.canonical(prepared.spec))
    spec["request"]["prompt"] = "First line" + newline + "Second line"
    put(prepared.spec_path, spec)
    root = tmp_path / "unqualified-newline-runtime"
    with pytest.raises(launcher.LauncherStop, match="invalid_request"):
        launcher.prepare(prepared.source, prepared.harness, root, prepared.spec_path)
    assert not root.exists()


def test_approved_lf_multiline_utf8_prompt_reaches_child_argv_unchanged(prepared):
    request = {**prepared.checked["request"], "prompt": "First line\n第二行：只做离线验证"}
    assert launcher.check_request(request) == request
    argv = child_args(prepared)
    prompt_path = Path(argv[argv.index("--prompt-file") + 1])
    raw = request["prompt"].encode("utf-8")
    put(prompt_path, raw)
    checked = {**prepared.checked, "request": request}
    assert launcher.child_argv(prepared.root, checked, argv) == argv[1:]
    assert prompt_path.read_bytes() == raw


def test_research_alias_and_served_model_are_distinct(prepared):
    config = launcher.read_json(prepared.root / "deer-flow/config.yaml")["models"]
    assert len(config) == 1 and config[0]["name"] == "glm" and config[0]["model"] == "glm-5.3"
    assert config[0]["api_key"] == "$LLM_API_KEY" and config[0]["max_retries"] == 0
    env = launcher.controlled_environment(prepared.root, prepared.checked)
    assert env["LLM_PROVIDER"] == "glm"
    assert env["LLM_MODEL_NAME"] == env["LLM_FAST_MODEL"] == env["LLM_STRONG_MODEL"] == "glm-5.3"
    assert env["DEERFLOW_MODEL"] == prepared.checked["request"]["model"] == "glm"
    assert env["LLM_TIERED_ROUTING"] == "false"
    assert launcher.qualify_manifest(core, prepared.checked, manifest_for(prepared))["routes"]["model"]["model"] == "glm-5.3"


@pytest.mark.parametrize("change", [{"provider": "openai", "alias": "new-model"}, {"provider": "claude-cli"},
                                    {"alias": "glm-5.3"}, {"provider": "qwen", "alias": "glm"}])
def test_unknown_profile_and_alias_refused(prepared, change):
    with pytest.raises(launcher.LauncherStop, match="billing_class_unverified"):
        launcher.model_config({**prepared.spec["model"], **change})


@pytest.mark.parametrize("relative", ["app/backend/app/config.py", "deer-flow/run_spending.py", "control/request.json",
                                       "control/config.json", "deer-flow/config.yaml"])
def test_source_request_or_config_tamper_refused(prepared, relative):
    with (prepared.root / relative).open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(launcher.LauncherStop, match="source_drift"):
        launcher.verify(prepared.root)


@pytest.mark.parametrize("key,value", [("root", "/outside"), ("import_roots", ["/outside"]), ("mutable_roots", ["/outside"])])
def test_runtime_path_tamper_refused(prepared, key, value):
    runtime = launcher.read_json(prepared.root / "spend/runtime.json")
    runtime[key] = value
    put(prepared.root / "spend/runtime.json", runtime)
    put(prepared.root / "control/runtime.json", runtime)
    with pytest.raises(launcher.LauncherStop, match="invalid_binding"):
        launcher.verify(prepared.root)


def test_descriptor_is_pinned_by_authorization(prepared):
    manifest = manifest_for(prepared)
    put(prepared.root / "spend/runtime.json", launcher.canonical(prepared.checked["runtime"]) + b"\n")
    put(prepared.root / "control/runtime.json", launcher.canonical(prepared.checked["runtime"]) + b"\n")
    changed = launcher.verify(prepared.root)
    with pytest.raises(launcher.LauncherStop, match="source_drift"):
        launcher.qualify_manifest(core, changed, manifest)


def test_extra_source_and_dependency_tamper(prepared):
    put(prepared.root / "app/backend/extra.py", b"raise AssertionError('must not execute')\n")
    with pytest.raises(launcher.LauncherStop, match="source_drift"):
        launcher.verify(prepared.root)
    (prepared.root / "app/backend/extra.py").unlink()
    put(prepared.dependencies / "synthetic_dependency.py", b"VALUE = 'changed'\n")
    with pytest.raises(launcher.LauncherStop, match="source_drift"):
        launcher.verify(prepared.root)


def test_pth_and_editable_app_dependency_refused(prepared):
    put(prepared.dependencies / "injection.pth", b"import builtins; builtins.UNSAFE_PTH = True\n")
    with pytest.raises(launcher.LauncherStop, match="unsafe_import"):
        launcher.verify(prepared.root)
    import builtins
    assert not hasattr(builtins, "UNSAFE_PTH")
    (prepared.dependencies / "injection.pth").unlink()
    put(prepared.dependencies / "app/__init__.py", b"# editable lookalike\n")
    dependencies = [{"path": str(prepared.dependencies), "files": launcher.tree_files(prepared.dependencies)}]
    with pytest.raises(launcher.LauncherStop, match="unsafe_import"):
        launcher.check_dependencies(dependencies, prepared.root)


def test_symlink_source_and_private_mutable_escape(prepared, tmp_path):
    target = prepared.root / "app/backend/app/config.py"
    target.unlink()
    target.symlink_to(prepared.source / "backend/app/config.py")
    with pytest.raises(launcher.LauncherStop, match="invalid_path"):
        launcher.verify(prepared.root)
    guard = launcher.RuntimeGuard(prepared.checked, tmp_path / "registry")
    (prepared.root / "tmp/escape").symlink_to(tmp_path)
    with pytest.raises(launcher.LauncherStop, match="invalid_path"):
        guard.write_path(prepared.root / "tmp/escape/mutation")


@pytest.mark.parametrize("name", [".env", ".env.production", "uploads/user.json", ".git/config", "secrets/key.json", "library.pth"])
def test_forbidden_source_names_rejected_before_read(name):
    with pytest.raises(launcher.LauncherStop):
        launcher.relative(name, source=True)


def test_ambient_dotenv_is_detected_without_read(prepared, monkeypatch):
    exists = Path.exists
    target = prepared.root.parent / ".env"
    monkeypatch.setattr(Path, "exists", lambda self: True if self == target else exists(self))
    with pytest.raises(launcher.LauncherStop, match="unsafe_environment"):
        launcher.verify(prepared.root)


@pytest.mark.parametrize("env", [{"SERPER_API_KEY": "synthetic"}, {"LLM_FAST_API_KEY": "synthetic"},
                                 {"LLM_FALLBACK_MODEL_NAME": "fallback"}, {"PYTHONPATH": "/deployment"},
                                 {"OPENAI_API_KEY": "synthetic"}, {"AWS_SECRET_ACCESS_KEY": "synthetic"},
                                 {"TOKENIZERS_PARALLELISM": "false"}])
def test_ambient_fallback_credentials_refused(env):
    with pytest.raises(launcher.LauncherStop, match="unsafe_environment"):
        launcher.reject_ambient(env)


def test_same_key_provider_alias_only(prepared):
    env = {**credentials(), "ZHIPUAI_API_KEY": "synthetic-model-key"}
    launcher.reject_ambient(env, child=True, model=prepared.checked["model"])
    env["ZHIPUAI_API_KEY"] = "different-synthetic-key"
    with pytest.raises(launcher.LauncherStop, match="billing_class_unverified"):
        launcher.reject_ambient(env, child=True, model=prepared.checked["model"])


def test_legitimate_child_controls_are_not_misclassified_as_credentials(prepared):
    env = {**launcher.controlled_environment(prepared.root, prepared.checked), **credentials(),
           "ZHIPUAI_API_KEY": "synthetic-model-key"}
    launcher.reject_ambient(env, child=True, model=prepared.checked["model"])


def test_child_preserves_validated_checkpoint_and_count_budget_controls(prepared):
    argv = launcher.child_argv(prepared.root, prepared.checked, child_args(prepared) + ["--resume"])
    binding = {"pipeline_id": "pipe-synthetic", "generation": 2}
    env = {**launcher.controlled_environment(prepared.root, prepared.checked),
           "RESEARCH_BUDGET_RUN_ID": "pipe-synthetic", "RESEARCH_BUDGET_EPOCH": "task-synthetic",
           "RESEARCH_BUDGET_LANE_ID": "outer-track-1", "RESEARCH_CHECKPOINT_ID": "checkpoint-synthetic",
           "RESEARCH_BUDGET_DB": str(prepared.root / "app/backend/uploads/pipelines/pipe-synthetic/handoff/synthetic.sqlite3"),
           "RESEARCH_BUDGET_ATTEMPTS_GLOBAL": "100", "DEERFLOW_RESEARCH_TIMEOUT": "300"}
    kept = launcher.child_controls(env, prepared.root, prepared.checked, binding, argv)
    assert kept["RESEARCH_BUDGET_RUN_ID"] == "pipe-synthetic"
    assert kept["RESEARCH_CHECKPOINT_ID"] == "checkpoint-synthetic"
    assert kept["RESEARCH_BUDGET_ATTEMPTS_GLOBAL"] == "100"
    env["RESEARCH_BUDGET_DB"] = str(prepared.root.parent / "outside.sqlite3")
    with pytest.raises(launcher.LauncherStop, match="invalid_path"):
        launcher.child_controls(env, prepared.root, prepared.checked, binding, argv)


def test_fresh_child_derives_owned_metadata_and_preserves_subagents(prepared):
    argv = launcher.child_argv(prepared.root, prepared.checked, child_args(prepared) + ["--subagents"])
    controls = launcher.child_controls({}, prepared.root, prepared.checked,
                                       {"pipeline_id": "pipe-synthetic", "generation": 1}, argv)
    assert controls["RESEARCH_BUDGET_RUN_ID"] == "pipe-synthetic"
    assert controls["RESEARCH_BUDGET_LANE_ID"] == "outer-track-1"
    assert controls["RESEARCH_BUDGET_EPOCH"] == "spending-generation-1"
    assert controls["DEERFLOW_SUBAGENTS"] == "true"
    assert controls["DEERFLOW_RUN_ARTIFACT_DIR"] == argv[argv.index("--out-dir") + 1]
    assert argv[-1] == "--subagents"


@pytest.mark.parametrize("explicit", [True, False])
def test_unreviewed_v3_resume_is_denied_even_without_flag(prepared, explicit):
    args = child_args(prepared) + (["--resume"] if explicit else [])
    argv = launcher.child_argv(prepared.root, prepared.checked, args)
    if not explicit:
        work = Path(argv[argv.index("--out-dir") + 1]) / "v3"
        work.mkdir()
        put(work / "state.json", {"identity": "synthetic previous state"})
    with pytest.raises(launcher.LauncherStop, match="resume_denied"):
        launcher.require_fresh_child(argv)


@pytest.mark.parametrize("explicit", [True, False])
def test_child_resume_refusal_precedes_model_or_script_invocation(prepared, monkeypatch, explicit):
    args = child_args(prepared) + (["--resume"] if explicit else [])
    if not explicit:
        (Path(args[args.index("--out-dir") + 1]) / "v3").mkdir()
    supplied = {"root": str(prepared.root), "participant_id": "registered-synthetic-child"}
    env = {"DRF_RUN_SPENDING_REQUIRED": "1", "DRF_RUN_SPENDING_BINDING": json.dumps(supplied),
           "DRF_RUN_SPENDING_MODULE_SHA256": prepared.checked["source_files"][launcher.CORE],
           "DRF_RUN_SPENDING_OPERATION": json.dumps({"stage": "research", "logical_key": "synthetic"})}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(launcher, "__file__", str(prepared.root / launcher.LAUNCHER))
    invoked = []
    monkeypatch.setattr(launcher, "load_core", lambda *a, **kw: invoked.append("core"))
    monkeypatch.setattr(launcher, "setup_execution", lambda *a, **kw: invoked.append("app"))
    monkeypatch.setattr(launcher.runpy, "run_path", lambda *a, **kw: invoked.append("script"))
    with pytest.raises(launcher.LauncherStop, match="resume_denied"):
        launcher.child(args)
    assert invoked == []


@pytest.mark.parametrize("change", ["generation", "checkpoint", "epoch", "lane", "pipeline", "sibling_path"])
def test_resume_and_ownership_metadata_refuse_mismatches(prepared, change):
    argv = launcher.child_argv(prepared.root, prepared.checked, child_args(prepared) + ["--resume"])
    binding = {"pipeline_id": "pipe-synthetic", "generation": 2}
    env = {"RESEARCH_BUDGET_RUN_ID": "pipe-synthetic", "RESEARCH_BUDGET_LANE_ID": "outer-track-1",
           "RESEARCH_BUDGET_EPOCH": "prior-attempt", "RESEARCH_CHECKPOINT_ID": "checkpoint-synthetic"}
    if change == "generation":
        binding["generation"] = 1
    elif change in {"checkpoint", "epoch"}:
        del env["RESEARCH_CHECKPOINT_ID" if change == "checkpoint" else "RESEARCH_BUDGET_EPOCH"]
    elif change == "lane":
        env["RESEARCH_BUDGET_LANE_ID"] = "unpriced-outer-track"
    elif change == "pipeline":
        env["RESEARCH_BUDGET_RUN_ID"] = "another-pipeline"
    else:
        env["RESEARCH_BUDGET_DB"] = str(prepared.root / "app/backend/uploads/pipelines/other/ledger.sqlite3")
    with pytest.raises(launcher.LauncherStop):
        launcher.child_controls(env, prepared.root, prepared.checked, binding, argv)


@pytest.mark.parametrize("resume", [False, True])
def test_actual_run_attempt_argv_and_metadata_are_accepted_without_rewrite(prepared, tmp_path, monkeypatch, resume):
    from app.config import Config
    from app.services import pipeline_orchestrator as pipeline
    from app.services import run_spending as lifecycle  # noqa: F401 -- Load the adapter before authorization.
    _, binding, _ = authorize(prepared, tmp_path)
    monkeypatch.setattr(Config, "DEERFLOW_DIR", str(prepared.root / "deer-flow"))
    monkeypatch.setattr(Config, "RESEARCH_MODEL_LEASE_DB", str(prepared.root / "spend/research-model-leases.sqlite3"))
    monkeypatch.setattr(Config, "RESEARCH_BUDGET_ENABLED", True)
    monkeypatch.setattr(pipeline, "_sync_deerflow_bridge_if_stale", lambda _: None)
    monkeypatch.setattr(pipeline, "_detect_deerflow_python", lambda _: [str(sys.executable)])
    monkeypatch.setattr(pipeline, "_data_sources_subprocess_env", lambda: {})
    monkeypatch.setattr(pipeline, "_news_context_subprocess_env", lambda **kw: {})
    handoff = prepared.root / "app/backend/uploads/pipelines/pipe-synthetic/handoff"
    observed = []
    class CapturedSpawn(Exception):
        pass
    with core.run_lock(binding):
        binding = core.bind_pipeline(binding, "pipe-synthetic", prepared.checked["request"])
        core.activate_binding(binding)
        if resume:
            core.mark_recoverable(binding)
            m = manifest_for(prepared)
            binding = core.resume_existing(binding, {"approval_sha256": core.hash_payload("explicit synthetic resume"),
                **{k: m[k] for k in ("request_sha256", "source_sha256", "routes_sha256")},
                "participants_sha256": core.hash_payload(core.summary(binding)["participants"])})
            core.activate_binding(binding)
        with core.operation("research", "producer-argv"):
            participant = core.register_participant(binding, "argv-child", spawn_receipt_sha256=core.hash_payload("argv-spawn"))
            def capture(cmd, **kwargs):
                marker = cmd.index("_child")
                argv = launcher.child_argv(prepared.root, prepared.checked, cmd[marker + 1:])
                controls = launcher.child_controls(kwargs["env"], prepared.root, prepared.checked, participant, argv)
                observed.append((argv, controls))
                raise CapturedSpawn()
            monkeypatch.setattr(pipeline.subprocess, "Popen", capture)
            with pytest.raises(CapturedSpawn):
                pipeline.DeerFlowResearchRunner._run_attempt(prepared.checked["request"]["prompt"], str(handoff),
                    on_progress=lambda *a: None, model="glm", depth="quick", language="English", subagents=True,
                    research_engine="v3", forecast_authority="target-first-v1", dual_track=False, timeout=300,
                    budget_run_id="pipe-synthetic", budget_lane_id="outer-track-1", budget_epoch="current-task",
                    budget_db_path=str(handoff / "epoch/current.sqlite3"), budget_telemetry_path=str(handoff / "count.json"),
                    resume=resume, resume_attempt_id="prior-task" if resume else None,
                    resume_checkpoint_id="checkpoint-synthetic" if resume else None, spending_binding=participant)
    assert len(observed) == 1
    argv, controls = observed[0]
    assert "--subagents" in argv and ("--resume" in argv) is resume
    assert controls["RESEARCH_BUDGET_EPOCH"] == ("prior-task" if resume else "current-task")
    assert controls["RESEARCH_BUDGET_DB"] == str(handoff / "epoch/current.sqlite3")
    assert controls["DEERFLOW_RUN_ARTIFACT_DIR"] == str(handoff)
    if resume:
        assert controls["RESEARCH_CHECKPOINT_ID"] == "checkpoint-synthetic"


@pytest.mark.parametrize("key,value", [("LLM_BASE_URL", "https://unreviewed.invalid/v1"), ("DEERFLOW_DUAL_TRACK", "true"),
                                     ("RESEARCH_ENGINE", "legacy"), ("DEER_FLOW_CONFIG_PATH", "/deployment/config.yaml")])
def test_child_effective_profile_drift_denies(prepared, key, value):
    env = {**launcher.controlled_environment(prepared.root, prepared.checked), key: value}
    with pytest.raises(launcher.LauncherStop, match="unsafe_environment"):
        launcher.child_controls(env, prepared.root, prepared.checked, {"pipeline_id": "pipe-synthetic", "generation": 1},
                                launcher.child_argv(prepared.root, prepared.checked, child_args(prepared)))


def test_dependency_source_loader_ignores_forged_unchecked_bytecode(prepared):
    import marshal
    import struct
    path = prepared.dependencies / "synthetic_dependency.py"
    cached = Path(importlib.util.cache_from_source(str(path)))
    malicious = compile("VALUE = 'unreviewed-cache'", str(path), "exec")
    put(cached, importlib.util.MAGIC_NUMBER + struct.pack("<I", 1) + b"\x00" * 8 + marshal.dumps(malicious))
    checked = launcher.verify(prepared.root)
    found = launcher.ImportBoundary(checked).find_spec("synthetic_dependency", [str(prepared.dependencies)])
    module = importlib.util.module_from_spec(found)
    found.loader.exec_module(module)
    assert module.VALUE == "synthetic"


def test_real_harness_layout_and_empty_skill_lock(prepared):
    roots = prepared.checked["runtime"]["import_roots"]
    assert str(prepared.root / launcher.HARNESS) in roots
    found = launcher.ImportBoundary(prepared.checked).find_spec("deerflow", roots)
    assert found.origin == str(prepared.root / launcher.HARNESS / "deerflow/__init__.py")
    put(prepared.root / launcher.SKILL_LOCK, b"")
    assert launcher.verify(prepared.root) == prepared.checked
    put(prepared.root / launcher.SKILL_LOCK, b"unreviewed bytes")
    with pytest.raises(launcher.LauncherStop, match="source_drift"):
        launcher.verify(prepared.root)


def test_mismatched_descriptor_copies_refuse(prepared):
    put(prepared.root / "spend/runtime.json", launcher.canonical(prepared.checked["runtime"]) + b"\n")
    with pytest.raises(launcher.LauncherStop, match="source_drift"):
        launcher.verify(prepared.root)


def test_nonprivate_running_launcher_refuses_before_credentials(prepared, monkeypatch):
    monkeypatch.setattr(launcher, "load_core", lambda *a, **kw: pytest.fail("core import before launcher origin check"))
    with pytest.raises(launcher.LauncherStop, match="source_drift"):
        launcher.run(prepared.root, "/unread-approval", "/unread-registry", "/unread-private-input")


def test_cli_errors_do_not_echo_unknown_values(capsys):
    with pytest.raises(launcher.LauncherStop, match="invalid_request"):
        launcher.main(["verify", "--root", "/unused", "--api-key", "synthetic-private-value"])
    assert "synthetic-private-value" not in capsys.readouterr().err


@pytest.mark.parametrize("change", ["unverified", "free", "missing_tool", "wrong_model", "wrong_account", "wrong_request"])
def test_qualification_refusals(prepared, change):
    m = manifest_for(prepared)
    if change == "unverified":
        m["routes"]["model"]["billing_class"] = "subscription"
    elif change == "free":
        m["routes"]["model"]["pricing"]["input_usd_per_million"] = "0"
    elif change == "missing_tool":
        del m["routes"]["scrape"]
    elif change == "wrong_model":
        m["routes"]["model"]["model"] = "glm"
    elif change == "wrong_request":
        m["request_sha256"] = core.hash_payload({"mode": "research_only"})
    else:
        m["routes"]["model"]["account_sha256"] = launcher.digest(b"different-synthetic-key")
    m["routes_sha256"] = core.hash_payload(m["routes"])
    with pytest.raises((launcher.LauncherStop, core.SpendingStop)):
        launcher.qualify_manifest(core, prepared.checked, m)
        launcher.check_credentials(credentials(), m)


def test_missing_ledger_never_recreated(prepared, tmp_path, monkeypatch):
    _, binding, _ = authorize(prepared, tmp_path)
    (prepared.root / "spend/run.sqlite3").unlink()
    monkeypatch.setattr(launcher, "load_core", lambda *a, **kw: core)
    with pytest.raises(launcher.LauncherStop, match="missing_ledger"):
        launcher.main(["verify", "--root", str(prepared.root)])
    with pytest.raises(core.SpendingStop):
        core.open_existing(binding)
    assert not (prepared.root / "spend/run.sqlite3").exists()


def test_import_origin_enforcement(prepared):
    boundary = launcher.ImportBoundary(prepared.checked)
    boundary.origin(str(prepared.root / "app/backend/app/config.py"))
    boundary.origin(str(prepared.dependencies / "synthetic_dependency.py"))
    with pytest.raises(launcher.LauncherStop, match="unsafe_import"):
        boundary.origin(str(prepared.source / "backend/app/config.py"))
    put(prepared.dependencies / "synthetic_dependency.py", b"# drift\n")
    with pytest.raises(launcher.LauncherStop, match="source_drift"):
        boundary.origin(str(prepared.dependencies / "synthetic_dependency.py"))


def test_guard_pins_sources_and_outside_registry_receipt(prepared, tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir(mode=0o700)
    guard = launcher.RuntimeGuard(prepared.checked, registry, "synthetic-launcher-only")
    guard.write_path(prepared.root / "tmp/new-output")
    for path in (tmp_path / "outside", prepared.root / launcher.CORE):
        with pytest.raises(launcher.LauncherStop, match="invalid_path"):
            guard.write_path(path)
    receipt = registry / (core.hash_payload("synthetic-launcher-only") + ".pipeline.json")
    guard("open", (str(receipt), None, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW))
    with pytest.raises(launcher.LauncherStop, match="invalid_path"):
        guard("open", (str(receipt), None, os.O_WRONLY | os.O_TRUNC))
    with pytest.raises(launcher.LauncherStop, match="unsafe_environment"):
        guard("subprocess.Popen", ("sh", ["sh", "-c", "ignored"], None, {}))
    with pytest.raises(launcher.LauncherStop, match="unsafe_environment"):
        guard("socket.bind", (None, None))


def child_args(prepared):
    folder = prepared.root / "app/backend/uploads/pipelines/pipe-synthetic/handoff"
    folder.mkdir(parents=True, exist_ok=True)
    put(folder / "prompt.txt", prepared.checked["request"]["prompt"].encode("utf-8"))
    return ["--", str(prepared.root / launcher.CHILD), "--prompt-file", str(folder / "prompt.txt"),
            "--out-dir", str(folder), "--model", "glm", "--depth", "quick", "--forecast-authority", "target-first-v1",
            "--target-language", "English"]


@pytest.mark.parametrize("bad", [["--subagents", "--subagents"], ["--extract-only"], ["--config", "/deployment/config.yaml"],
                                 ["--model", "new-model"], ["--api-key", "synthetic"]])
def test_child_argv_rejects_unreviewed_switches(prepared, bad):
    with pytest.raises(launcher.LauncherStop, match="invalid_request"):
        launcher.child_argv(prepared.root, prepared.checked, child_args(prepared) + bad)


def test_child_runs_actual_script_after_participant_activation(prepared, tmp_path, monkeypatch):
    _, binding, _ = authorize(prepared, tmp_path)
    with core.run_lock(binding):
        binding = core.bind_pipeline(binding, "pipe-synthetic", prepared.checked["request"])
        core.activate_binding(binding)
        with core.operation("research", "synthetic-root"):
            child = core.register_participant(binding, "synthetic-child", spawn_receipt_sha256=core.hash_payload("spawn"))
            env = core.export_environment(child)
        for key, value in {**env, **credentials()}.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setattr(launcher, "__file__", str(prepared.root / launcher.LAUNCHER))
        monkeypatch.setattr(launcher, "load_core", lambda *a, **kw: core)
        events = []
        monkeypatch.setattr(launcher, "setup_execution", lambda *a, **kw: events.append("imports_setup"))
        run_path = launcher.runpy.run_path
        def observed(path, run_name):
            assert core.check_context()["participant_id"] == "synthetic-child"
            assert core.current_operation() == {"stage": "research", "logical_key": "synthetic-root"}
            assert sys.argv[0] == str(prepared.root / launcher.CHILD)
            events.append("actual_runpy")
            return run_path(path, run_name=run_name)
        monkeypatch.setattr(launcher.runpy, "run_path", observed)
        monkeypatch.setattr(sys, "argv", ["original"])
        launcher.child(child_args(prepared))
        assert events == ["imports_setup", "actual_runpy"]


@pytest.mark.parametrize("variant", ["valid", "different_question", "invalid_utf8", "trailing_newline", "bom"])
def test_child_prompt_matches_immutable_request_before_imports(prepared, tmp_path, monkeypatch, variant):
    """All authority/source/route carriers are valid; only prompt bytes vary."""
    manifest, binding, _ = authorize(prepared, tmp_path)
    argv = child_args(prepared)
    prompt_path = Path(argv[argv.index("--prompt-file") + 1])
    approved = prepared.checked["request"]["prompt"].encode("utf-8")
    bodies = {"valid": approved, "different_question": b"Different" + approved[len(b"Synthetic"):],
              "invalid_utf8": b"\xff" + approved[1:], "trailing_newline": approved + b"\n", "bom": b"\xef\xbb\xbf" + approved}
    put(prompt_path, bodies[variant])
    with core.run_lock(binding):
        binding = core.bind_pipeline(binding, "pipe-synthetic", prepared.checked["request"])
        core.activate_binding(binding)
        with core.operation("research", "verified-prompt-control"):
            child = core.register_participant(binding, "prompt-child", spawn_receipt_sha256=core.hash_payload("prompt-spawn"))
            env = core.export_environment(child)
        for key, value in {**env, **credentials()}.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setattr(launcher, "__file__", str(prepared.root / launcher.LAUNCHER))
        monkeypatch.setattr(sys, "argv", ["prior-argv"])
        events = []
        def load(*args, **kwargs):
            events.append("core_import")
            return core
        def model_and_script(*args, **kwargs):
            events.extend(["model_import", "script"])
            assert core.check_context()["participant_id"] == "prompt-child"
            route = manifest["routes"]["model"]
            def send():
                events.append("send")
                return None
            core.dispatch("model", {"endpoint": route["endpoint"], "model": route["model"],
                "input_tokens": route["input_ceiling"], "max_output_tokens": 8, "tool_units": 0,
                "payload_sha256": core.hash_payload({"prompt": prepared.checked["request"]["prompt"]})}, send)
        monkeypatch.setattr(launcher, "load_core", load)
        monkeypatch.setattr(launcher, "setup_execution", lambda *a, **kw: events.append("app_imports"))
        monkeypatch.setattr(launcher.runpy, "run_path", model_and_script)
        if variant == "valid":
            launcher.child(argv)
            assert events == ["core_import", "app_imports", "model_import", "script", "send"]
            assert core.summary(binding)["attempt_count"] == 1
            assert sys.argv == argv[1:]
        else:
            with pytest.raises(launcher.LauncherStop, match="invalid_request"):
                launcher.child(argv)
            assert events == []
            assert core.summary(binding)["attempt_count"] == 0
            assert prompt_path.read_bytes() == bodies[variant]  # no rewrite to manufacture success


@pytest.mark.parametrize("key", list(launcher.CARRIERS))
def test_child_missing_contract_denies_before_app(prepared, monkeypatch, key):
    for name in launcher.CARRIERS:
        monkeypatch.setenv(name, "invalid-synthetic")
    monkeypatch.setenv(launcher.CARRIERS[0], "1")
    monkeypatch.delenv(key)
    monkeypatch.setattr(launcher, "setup_execution", lambda *a, **kw: pytest.fail("app imports reached"))
    with pytest.raises(launcher.LauncherStop, match="invalid_binding"):
        launcher.child(["--", "unused"])


def test_async_parent_retains_lock_through_worker_terminal_cleanup(prepared, tmp_path, monkeypatch):
    manifest = manifest_for(prepared)
    approval, secrets, registry = tmp_path / "synthetic-approval.json", tmp_path / "synthetic-input.json", tmp_path / "registry"
    put(approval, manifest)
    put(secrets, credentials())
    registry.mkdir(mode=0o700)
    monkeypatch.setattr(launcher, "load_core", lambda *a, **kw: core)
    monkeypatch.setattr(launcher, "__file__", str(prepared.root / launcher.LAUNCHER))
    # Only process-global import/audit setup is substituted. The real core,
    # filesystem manifest, authorization registry, SQL ledger and run_lock run.
    def fake_setup(root, checked, keys, carriers, archive):
        for key, value in carriers.items():
            monkeypatch.setenv(key, value)
    monkeypatch.setattr(launcher, "setup_execution", fake_setup)
    completed, checks, errors = {}, [], []
    module = types.ModuleType("app.services.pipeline_orchestrator")
    class Orchestrator:
        _threads = {}
        @classmethod
        def start(cls, **request):
            assert request["model"] == "glm"  # common start consumes research alias
            b = core.bind_pipeline(core.binding_from_environment(), "pipe-synthetic", request)
            core.activate_binding(b)
            state = types.SimpleNamespace(pipeline_id="pipe-synthetic")
            def worker():
                try:
                    completed.update(status="completed")
                    time.sleep(0.02)  # saved terminal != joined worker
                    checks.append(core._lock_held(b))
                    core.close_run(b)
                except BaseException as error:
                    errors.append(error)
                finally:
                    cls._threads.pop(state.pipeline_id, None)
            thread = threading.Thread(target=contextvars.copy_context().run, args=(worker,))
            cls._threads[state.pipeline_id] = thread
            thread.start()
            return state
    module.PipelineOrchestrator = Orchestrator
    module.PipelineManager = types.SimpleNamespace(load=lambda _: completed)
    monkeypatch.setitem(sys.modules, "app.services.pipeline_orchestrator", module)
    result = launcher.run(prepared.root, approval, registry, secrets)
    assert not errors and checks == [True] and result["state"] == "closed"
    assert result["attempt_count"] == 0 and result["reserved_max_microusd"] == 0
    assert not core._LOCK_FDS
    assert launcher.read_json(prepared.root / "spend/result.json") == result
    assert len(list(registry.glob("*.pipeline.json"))) == 1


def test_actual_common_start_and_child_descriptor_keep_alias_and_served_model(prepared, tmp_path, monkeypatch):
    """Use real common start/admission and child command producer; fake stages only."""
    from app.config import Config
    from app.models.project import ProjectManager
    from app.services.report_agent import ReportManager
    from app.services import pipeline_orchestrator as pipeline
    from app.services import run_spending as lifecycle  # noqa: F401 -- Load the adapter before authorization.
    _, binding, _ = authorize(prepared, tmp_path)
    for name, path in {"UPLOAD_FOLDER": "app/backend/uploads", "PIPELINE_DATA_DIR": "app/backend/uploads/pipelines",
                       "OASIS_SIMULATION_DATA_DIR": "app/backend/uploads/simulations", "DEERFLOW_DIR": "deer-flow"}.items():
        monkeypatch.setattr(Config, name, str(prepared.root / path))
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(prepared.root / "app/backend/uploads/projects"))
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(prepared.root / "app/backend/uploads/reports"))
    monkeypatch.setattr(Config, "LLM_PROVIDER", "glm")
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "glm-5.3")
    seen, failures = [], []
    def fake_stages(cls, state):
        try:
            with lifecycle.pipeline_scope(state):
                active = core.check_context()
                seen.append((state.options["research_model"], state.options["spending_request_v1"]["model"],
                             Config.LLM_MODEL_NAME, core._lock_held(active)))
                core.close_run(active)
                state.status = "completed"
                pipeline.PipelineManager.save(state)
        except BaseException as error:
            failures.append(error)
        finally:
            cls._threads.pop(state.pipeline_id, None)
    monkeypatch.setattr(pipeline.PipelineOrchestrator, "_run", classmethod(fake_stages))
    with core.run_lock(binding):
        for key, value in core.export_environment(binding).items():
            monkeypatch.setenv(key, value)
        core.activate_binding(binding)
        result = launcher.wait_pipeline(core, binding, prepared.checked["request"])
    assert not failures and seen == [("glm", "glm", "glm-5.3", True)]
    assert result["state"] == "closed"
    # The real child command producer reads the verified executable descriptor.
    # It exports the existing child carrier; authorization for this producer
    # check uses a separate synthetic fixture to avoid reopening a closed run.
    monkeypatch.setattr(lifecycle, "api", lambda: types.SimpleNamespace(
        export_environment=lambda b: {"DRF_RUN_SPENDING_REQUIRED": "1"},
        deny=lambda code: (_ for _ in ()).throw(core.SpendingStop(code))))
    args = launcher.child_argv(prepared.root, prepared.checked, child_args(prepared))
    env = launcher.controlled_environment(prepared.root, prepared.checked)
    cmd = lifecycle.configure_child(binding, env, [str(prepared.root / "ignored-python"), *args], args[0])
    assert cmd == [prepared.checked["runtime"]["python"], "-I", "-S", "-B",
                   str(prepared.root / launcher.LAUNCHER), "_child", "--", *args]
    assert args[args.index("--model") + 1] == "glm"
    assert launcher.read_json(prepared.root / "deer-flow/config.yaml")["models"][0]["model"] == "glm-5.3"


def test_interrupt_with_failed_halt_still_cancels_and_joins_under_lock(prepared, tmp_path, monkeypatch):
    _, binding, _ = authorize(prepared, tmp_path)
    module = types.ModuleType("app.services.pipeline_orchestrator")
    cancelled = threading.Event()
    observed = []
    class Orchestrator:
        _threads = {}
        @classmethod
        def start(cls, **request):
            bound = core.bind_pipeline(binding, "pipe-synthetic", request)
            core.activate_binding(bound)
            def cleanup():
                assert cancelled.wait(timeout=3)
                # Registry disappearance is deliberately earlier than actual
                # completion, proving the retained worker itself is joined.
                cls._threads.pop("pipe-synthetic")
                time.sleep(0.02)
                observed.append(("cleanup", core._lock_held(bound)))
            thread = threading.Thread(target=cleanup)
            original_join = thread.join
            attempts = []
            def interrupt_once(*args, **kwargs):
                if not attempts:
                    attempts.append(True)
                    raise KeyboardInterrupt()
                return original_join(*args, **kwargs)
            thread.join = interrupt_once
            cls._threads["pipe-synthetic"] = thread
            thread.start()
            return types.SimpleNamespace(pipeline_id="pipe-synthetic")
        @classmethod
        def cancel(cls, pipeline_id):
            observed.append(("cancel", core._lock_held(binding)))
            cancelled.set()
    module.PipelineOrchestrator = Orchestrator
    module.PipelineManager = types.SimpleNamespace(load=lambda _: pytest.fail("interrupted run must not report success"))
    monkeypatch.setitem(sys.modules, "app.services.pipeline_orchestrator", module)
    monkeypatch.setattr(core, "halt", lambda *a, **kw: (_ for _ in ()).throw(core.SpendingStop("storage_unavailable")))
    with core.run_lock(binding):
        with pytest.raises(KeyboardInterrupt) as raised:
            launcher.wait_pipeline(core, binding, prepared.checked["request"])
        assert "durable_halt_failed" in raised.value.__notes__
        assert observed == [("cancel", True), ("cleanup", True)]
        assert core._lock_held(binding)
