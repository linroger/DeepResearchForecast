"""Single-host lifecycle facade for a sealed world generation and its child."""
from __future__ import annotations

from contextlib import contextmanager
import os
import hashlib
import logging
from pathlib import Path
import signal
import subprocess
import sys
import threading
import uuid

from .artifacts import atomic_json, exclusive_file, file_digest, input_manifest, load_inputs, read_json, seal_inputs
from .contracts import ENGINE, REFUSAL_CODES, WorldError, canonical_json, clone, identifier, require
from .results import export_result, load_frozen_result, validate_recoverable_export
from .store import WorldStore

_processes = {}
_lock = threading.RLock()
_LOG = logging.getLogger(__name__)
# Stops a later start() resumes: an operator cancel, SIGTERM, or capacity refusals that outlasted their waits.
_RESUMABLE_STOPS = frozenset({'cancelled', 'terminated', *REFUSAL_CODES})


def _child_environment():
    """The API's environment plus the shared model-call lease ledger, exactly as pipeline research
    subprocesses receive it, so world calls draw on the same cross-process provider envelope."""
    from ...config import Config
    env = dict(os.environ)
    env['RESEARCH_MODEL_LEASE_DB'] = os.path.realpath(
        getattr(Config, 'RESEARCH_MODEL_LEASE_DB', '')
        or os.path.join(Config.UPLOAD_FOLDER, 'research_model_leases.sqlite3'))
    return env


def _hold_inherited_launch_lock(fd, directory):
    """The inherited descriptor must be this world's launch lock and hold its exclusive flock."""
    import fcntl
    actual = os.fstat(fd)
    expected = os.stat(directory / 'world_launch.lock')
    require((actual.st_dev, actual.st_ino) == (expected.st_dev, expected.st_ino),
            'invalid_launch_lock', 'Inherited launch lock does not belong to this simulation')
    # Re-locking through the holder's own open file description is a no-op; if any other
    # description holds the lock this fails, so a passing child provably owns the launch.
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise WorldError('invalid_launch_lock', 'Inherited launch lock is held by another launch') from None


@contextmanager
def _sigterm_cancels(event):
    """While the child runs, SIGTERM requests cancellation instead of killing it mid-call: it
    stops at the next causal boundary, records 'stopped' and releases its writer fence."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.signal(signal.SIGTERM, lambda signum, frame: event.set())
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_DFL if previous is None else previous)


def _launch_active(directory):
    import fcntl
    path = directory / 'world_launch.lock'
    if not path.is_file():
        return False
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)


def _write_run(directory, record, *, parent_pid=None):
    with exclusive_file(directory / 'world_status.lock'):
        path = directory / 'world_run.json'
        if parent_pid is not None:
            current = read_json(path)
            require(current.get('launch_id') == record['launch_id'], 'launch_changed', 'World launch identity changed')
            if current.get('runner_status') != 'starting':
                return
            record = {**current, 'process_pid': parent_pid}
        atomic_json(path, record)


class WorldSimulationService:
    @staticmethod
    def directory(simulation_id, root=None):
        identifier(simulation_id, 'simulation_id')
        if root is None:
            from ...config import Config
            root = Config.OASIS_SIMULATION_DATA_DIR
        root = Path(root).resolve()
        directory = root / simulation_id
        require(not directory.is_symlink() and directory.resolve().parent == root,
                'invalid_directory', 'Simulation directory must belong to its storage root')
        return directory

    @classmethod
    def prepare_model(cls, simulation_id, *, raw_spec, research_report, research_generation_id,
                      research_engine, actor_bundle=None, root=None, policy_spec=None,
                      ontology=None, simulation_requirement=''):
        from .compiler import compile_world_spec
        directory = cls.directory(simulation_id, root)
        preparation = None
        if raw_spec is None:
            from .modeler import generate_candidate
            raw_spec, preparation = generate_candidate(directory, research_report=research_report,
                research_generation_id=research_generation_id, research_engine=research_engine,
                actor_bundle=actor_bundle, ontology=ontology, simulation_requirement=simulation_requirement,
                policy_spec=policy_spec)
        spec = compile_world_spec(raw_spec, simulation_id=simulation_id,
            generation_id='world_' + uuid.uuid4().hex, research_report=research_report,
            research_generation_id=research_generation_id, research_engine=research_engine,
            actor_bundle=actor_bundle)
        # Pin scheduling semantics only for genuinely new preparation, never load/fork.
        spec['interactionQueuePolicy'] = 'presented-v1'
        if preparation is not None:
            spec['sourceBindings']['modelPreparation'] = preparation
        manifest = seal_inputs(directory, spec)
        return {'spec': spec, 'manifest': manifest,
                'manifest_sha256': file_digest(directory / 'world_input_manifest.json')}

    @classmethod
    def _inputs(cls, simulation_id, root=None, expected_manifest_sha256=None):
        directory = cls.directory(simulation_id, root)
        state_file = directory / 'state.json'
        state = read_json(state_file) if state_file.exists() else None
        require(state is not None, 'missing_engine_pin', 'World execution requires its saved preparation identity')
        if state is not None:
            require(state.get('simulation_engine') == ENGINE, 'engine_mismatch', 'Saved simulation is not world-v1')
            pinned = state.get('world_input_manifest_sha256')
            require(bool(pinned), 'missing_input_binding', 'Prepared world state lacks its manifest pin')
            require(expected_manifest_sha256 is None or expected_manifest_sha256 == pinned,
                    'input_binding_mismatch', 'World admission uses a different manifest pin')
            expected_manifest_sha256 = pinned
        spec, manifest = load_inputs(directory, simulation_id=simulation_id,
                                     expected_manifest_sha256=expected_manifest_sha256)
        if state is not None:
            require(state.get('world_generation_id') == spec['generationId']
                    and state.get('world_spec_sha256') == manifest['specSha256'],
                    'input_binding_mismatch', 'Saved world generation or specification pin changed')
        return directory, spec

    @classmethod
    def status(cls, simulation_id, *, root=None):
        directory = cls.directory(simulation_id, root)
        if not (directory / 'world_input_manifest.json').exists():
            return None
        directory, spec = cls._inputs(simulation_id, root)
        run_path = directory / 'world_run.json'
        run = read_json(run_path) if run_path.exists() else {}
        if run:
            require(run.get('simulation_id') == simulation_id and run.get('generation_id') == spec['generationId'],
                    'run_identity_mismatch', 'Runtime projection belongs to another world')
        result = {'simulation_id': simulation_id, 'simulation_engine': ENGINE,
                  'runner_status': run.get('runner_status', 'idle'), 'current_round': 0,
                  'total_rounds': len(spec['periods']), 'process_pid': run.get('process_pid'),
                  'current_period_end': spec['asOf'], 'horizon_date': spec['horizon'],
                  'error': run.get('error')}
        process = _processes.get(str(directory))
        # Liveness: this process's own child handle, else the launch flock every child holds for
        # its whole life (the kernel releases it when the child exits, also across a reboot).
        # Never the recorded PID: macOS reuses PIDs, so a dead child's soon names a live process.
        alive = process is not None and process.pid == run.get('process_pid') and process.poll() is None
        active_launch = (run.get('runner_status') in {'starting', 'running', 'stopping'}
                         and (alive or _launch_active(directory)))
        database = directory / 'world.sqlite3'
        if database.exists():
            with WorldStore(database, spec, read_only=True) as store:
                head = store.head()
            result.update(current_round=head['round'], current_period_end=head['simulatedAt'])
            if head['round'] == len(spec['periods']):
                try:
                    load_frozen_result(directory)
                except WorldError as error:
                    result.update(runner_status='running' if active_launch else 'failed',
                                  error=None if active_launch else error.code)
                else:
                    result.update(runner_status='completed', error=None)
                return result
        if result['runner_status'] in {'starting', 'running', 'stopping'} and not active_launch:
            result.update(runner_status='failed', error='child_exited_before_committed_horizon')
        elif result['runner_status'] == 'completed':
            result.update(runner_status='failed', error='missing_completion_evidence')
        return result

    @classmethod
    def start(cls, simulation_id, *, root=None, expected_manifest_sha256=None):
        import fcntl
        from .policy import StrictHTTPPolicy
        directory, spec = cls._inputs(simulation_id, root, expected_manifest_sha256)
        require('evaluationObservationMask' not in spec, 'evaluation_only',
                'Observation ablation is restricted to the evaluation harness')
        admitted_pin = hashlib.sha256((canonical_json(input_manifest(spec)) + '\n').encode('utf-8')).hexdigest()
        require(file_digest(directory / 'world_input_manifest.json') == admitted_pin,
                'input_binding_mismatch', 'World admission manifest differs from its immutable canonical inputs')
        with _lock:
            # This launch lock is inherited by the child, so it protects duplicate
            # starts across API processes and lasts until the child exits.
            lock_fd = os.open(directory / 'world_launch.lock', os.O_RDWR | os.O_CREAT, 0o600)
            try:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise WorldError('world_running', 'This world already has a running child') from None
                current = cls.status(simulation_id, root=root)
                if current and current['runner_status'] == 'completed':
                    return current
                # Completed SQLite with missing export is a recoverable explicit
                # writer operation. Existing corrupt result bytes are not repaired.
                if (directory / 'world.sqlite3').exists():
                    with WorldStore(directory / 'world.sqlite3', spec, read_only=True) as store:
                        complete = store.head()['round'] == len(spec['periods'])
                    if complete:
                        validate_recoverable_export(directory)
                        export_result(directory)
                        return cls.status(simulation_id, root=root)
                policy = StrictHTTPPolicy(spec)  # capability/config validation; no network call
                policy.close()
                cancel = directory / 'world_cancel.json'
                if cancel.exists():
                    cancel.unlink()
                record = {
                    'simulation_id': simulation_id, 'generation_id': spec['generationId'],
                    'launch_id': uuid.uuid4().hex, 'runner_status': 'starting', 'process_pid': None, 'error': None}
                _write_run(directory, record)
                script = Path(__file__).resolve().parents[3] / 'scripts' / 'run_world_simulation.py'
                with (directory / 'world_child.log').open('ab') as output:
                    process = subprocess.Popen([sys.executable, '-B', str(script),
                        '--simulation-dir', str(directory), '--lock-fd', str(lock_fd),
                        '--manifest-sha256', admitted_pin, '--launch-id', record['launch_id']],
                        stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                        start_new_session=True, pass_fds=(lock_fd,), env=_child_environment())
                _processes[str(directory)] = process
                _write_run(directory, record, parent_pid=process.pid)
                result = cls.status(simulation_id, root=root)
                result['process_pid'] = process.pid
                return result
            finally:
                # Closing only this reference leaves the inherited flock intact.
                os.close(lock_fd)

    @classmethod
    def stop(cls, simulation_id, *, root=None):
        directory, spec = cls._inputs(simulation_id, root)
        status = cls.status(simulation_id, root=root)
        if status['runner_status'] not in {'starting', 'running', 'stopping'}:
            return status
        atomic_json(directory / 'world_cancel.json', {'generationId': spec['generationId']})
        return {**status, 'runner_status': 'stopping'}

    @classmethod
    def require_complete(cls, simulation_id, *, root=None):
        directory, _ = cls._inputs(simulation_id, root)
        return load_frozen_result(directory)

    @classmethod
    def fork(cls, simulation_id, new_simulation_id, *, root=None, seed=None):
        _, original = cls._inputs(simulation_id, root)
        spec = clone(original)
        spec.update(simulationId=new_simulation_id, generationId='world_' + uuid.uuid4().hex)
        if seed is not None:
            require(type(seed) is int and seed >= 0, 'invalid_seed', 'Seed must be a nonnegative integer')
            spec['seed'] = seed
        directory = cls.directory(new_simulation_id, root)
        manifest = seal_inputs(directory, spec)
        return {'spec': spec, 'manifest': manifest,
                'manifest_sha256': file_digest(directory / 'world_input_manifest.json')}


def run_child(directory, *, policy=None, expected_manifest_sha256=None, launch_id=None, launch_lock_fd=None):
    """Actual child entry, also exercised offline with a scripted policy boundary."""
    from .controller import run_to_horizon
    from .policy import StrictHTTPPolicy
    directory = Path(directory).resolve()
    _, spec = WorldSimulationService._inputs(directory.name, directory.parent, expected_manifest_sha256)
    require('evaluationObservationMask' not in spec, 'evaluation_only',
            'Observation ablation is restricted to the evaluation harness')
    record = {'simulation_id': spec['simulationId'], 'generation_id': spec['generationId'],
              'launch_id': launch_id or uuid.uuid4().hex,
              'runner_status': 'running', 'process_pid': os.getpid(), 'error': None}
    owns_policy = policy is None
    store = None
    fence = None
    own_launch = None
    terminate = threading.Event()
    with _sigterm_cancels(terminate):
        try:
            if launch_lock_fd is None:
                own_launch = exclusive_file(directory / 'world_launch.lock', blocking=False)
                own_launch.__enter__()
            else:
                _hold_inherited_launch_lock(launch_lock_fd, directory)
            if launch_id is not None:
                projection = read_json(directory / 'world_run.json')
                require(projection.get('launch_id') == launch_id and projection.get('generation_id') == spec['generationId'],
                        'launch_changed', 'Child launch identity differs from admission')
            store = WorldStore(directory / 'world.sqlite3', spec)
            # This child holds the launch flock, so any other recorded writer process has exited.
            fence = store.acquire_writer('child_' + uuid.uuid4().hex, takeover=True, holds_launch_lock=True)
            if policy is None:
                policy = StrictHTTPPolicy(spec)
            _write_run(directory, record)
            def cancelled():
                if terminate.is_set():
                    return True
                path = directory / 'world_cancel.json'
                return path.exists() and read_json(path).get('generationId') == spec['generationId']
            run_to_horizon(store, policy, fence, cancelled=cancelled,
                           on_commit=lambda head: export_result(directory))
            export_result(directory)
            record['runner_status'] = 'completed'
            _write_run(directory, record)
            return 0
        except Exception as error:
            code = getattr(error, 'code', 'world_execution_failed')
            if code == 'cancelled' and terminate.is_set():
                code = 'terminated'
            record.update(runner_status='stopped' if code in _RESUMABLE_STOPS else 'failed', error=code)
            if fence is not None:
                _write_run(directory, record)
            else:
                # Without the fence this child owns nothing it may record (another launch can own
                # the projection), so the cause reaches only the log (world_child.log for a child).
                _LOG.error('World child %s failed before acquiring its writer fence: %s (%s)', directory.name, code,
                           str(error) if isinstance(error, WorldError) else type(error).__name__)
            return 1
        finally:
            if store is not None:
                if fence is not None:
                    store.release_writer(fence)
                store.close()
            if owns_policy and policy is not None:
                policy.close()
            if own_launch is not None:
                own_launch.__exit__(None, None, None)
