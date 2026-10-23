"""Record producer → pipeline registry → public API, with no live execution.

Use main_offline_pytest.py. Only provider/process boundaries are substituted;
the compiler, receipt verifier, state projection and artifact routes stay real.
"""
import ast
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import threading
from types import SimpleNamespace

import pytest

from app.config import Config
from app.services import pipeline_orchestrator as po
from app.services import simulation_record as compiler
from app.services import simulation_record_contract as rc
from app.services.simulation_manager import SimulationManager
from app.services.simulation_runner import RunnerStatus, SimulationRunner, SimulationRunState
from test_world_lifecycle import boundary, run_pipeline_world

pytestmark = pytest.mark.guarded_runner
FIXTURE = Path(__file__).parent / "fixtures" / "sim_record" / "reflexive3"


@pytest.fixture
def case(tmp_path, monkeypatch):
    root = tmp_path / "simulations"
    directory = root / "sim_record_lifecycle"
    shutil.copytree(FIXTURE, directory)
    summary_path = directory / "run_summary.json"
    summary = json.loads(summary_path.read_text())
    summary["simulation_id"] = directory.name
    summary_path.write_text(json.dumps(summary))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(root))
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(root))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(root))
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"))
    monkeypatch.setattr(Config, "SIM_RECORD_ENABLED", True)
    monkeypatch.setattr(Config, "SIM_RECORD_SYNTHESIS", False)
    monkeypatch.setattr(Config, "PIPELINE_VALIDATE_ARTIFACTS", True)
    run = SimulationRunState(simulation_id=directory.name, runner_status=RunnerStatus.COMPLETED,
        current_round=3, total_rounds=3, twitter_enabled=True, reddit_enabled=True,
        twitter_completed=True, reddit_completed=True)
    monkeypatch.setattr(SimulationRunner, "_run_states", {directory.name: run})
    state = po.PipelineState(pipeline_id="pipe_record_lifecycle", prompt="Fixture", status="running",
                            simulation_id=directory.name, options={"research_language": "en"})
    po.PipelineManager.ensure_dirs(state.pipeline_id)
    po.PipelineManager.save(state)
    return SimpleNamespace(directory=directory, root=root, run=run, state=state,
                           orchestrator=po.PipelineOrchestrator())


def snapshot(directory):
    return {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}


def publish(case):
    assert case.orchestrator._publish_run_summary(case.state, case.directory.name, regenerate=False)
    record, status = rc.load_published_record(str(case.directory))
    assert record is not None, status
    return record


def test_completion_and_reuse_preserve_a_servable_record(case):
    data = json.loads((case.directory / "state.json").read_text())
    data.update(status="ready", current_round=0, twitter_status="not_started", reddit_status="not_started")
    (case.directory / "state.json").write_text(json.dumps(data))
    record = publish(case)
    saved = json.loads((case.directory / "state.json").read_text())
    assert saved["status"] == "completed" and saved["current_round"] == 3
    assert saved["twitter_status"] == saved["reddit_status"] == "completed"
    assert case.state.artifacts["simulation_record"] == str(case.directory / rc.RECORD_JSON)
    before = snapshot(case.directory)
    assert publish(case) == record
    assert snapshot(case.directory) == before


@pytest.mark.parametrize("damage", ["missing", "changed", "failed_audit", "missing_markdown"])
def test_derivative_damage_preserves_paid_run_reuse_and_repairs(case, damage, monkeypatch):
    publish(case)
    summary = (case.directory / "run_summary.json").read_bytes()
    if damage == "missing":
        (case.directory / rc.RECORD_JSON).unlink()
    elif damage == "changed":
        (case.directory / rc.RECORD_JSON).write_text('{}')
    elif damage == "missing_markdown":
        (case.directory / rc.RECORD_MD).unlink()
    else:
        (case.directory / rc.RECORD_AUDIT_JSON).write_text('{"publication_status":"failed","hard_issues":["fixture"]}')
    assert rc.load_published_record(str(case.directory))[0] is None
    assert case.orchestrator._reuse_ok(case.state, po.STAGE_RUN)
    monkeypatch.setattr(SimulationRunner, "start_simulation", lambda *a, **k: pytest.fail("paid RUN restarted"))
    monkeypatch.setattr(SimulationRunner, "write_run_summary", lambda *a, **k: pytest.fail("valid summary rewritten"))
    monkeypatch.setattr(compiler, "_apply_synthesis", lambda *a, **k: pytest.fail("repair called synthesis"))
    monkeypatch.setattr(Config, "SIM_RECORD_SYNTHESIS", True)
    publish(case)
    assert (case.directory / "run_summary.json").read_bytes() == summary


def test_required_summary_damage_still_rejects_run_reuse(case):
    publish(case)
    (case.directory / "run_summary.json").write_text('{}')
    assert not case.orchestrator._reuse_ok(case.state, po.STAGE_RUN)


def test_projection_failure_preserves_run_evidence(case, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("projection write unavailable")
    monkeypatch.setattr(SimulationRunner, "reconcile_completed_record_state", unavailable)
    assert case.orchestrator._publish_run_summary(case.state, case.directory.name, regenerate=False)
    assert case.orchestrator._reuse_ok(case.state, po.STAGE_RUN)
    assert not (case.directory / rc.RECORD_JSON).exists()


def test_concurrent_publishers_synthesize_once(case, monkeypatch):
    calls = []
    monkeypatch.setattr(Config, "SIM_RECORD_SYNTHESIS", True)
    monkeypatch.setattr(compiler, "_apply_synthesis", lambda *a, **k: calls.append("synthesis"))
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: SimulationRunner.publish_simulation_record(case.directory.name), range(2)))
    assert results == [True, True]
    assert calls == ["synthesis"]
    assert rc.load_published_record(str(case.directory))[0] is not None


def test_interrupted_compilation_cannot_retry_paid_synthesis(case, monkeypatch):
    original = compiler.build_record
    modes = []
    def interrupted(*args, **kwargs):
        modes.append(kwargs.get("synthesis"))
        if len(modes) == 1:
            raise RuntimeError("crash before record write")
        return original(*args, **kwargs)
    monkeypatch.setattr(compiler, "build_record", interrupted)
    assert not SimulationRunner.publish_simulation_record(case.directory.name)
    assert SimulationRunner.publish_simulation_record(case.directory.name)
    assert modes[0] is None and all(mode is False for mode in modes[1:])


@pytest.fixture
def client(case):
    from flask import Flask
    from app.api import research_bp
    from app.api import research  # noqa: F401
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(research_bp, url_prefix="/api/research")
    return app.test_client()


@pytest.mark.parametrize("name", ["simulation_record", "simulation_record_partial"])
@pytest.mark.parametrize("damage", ["none", "failed", "json", "source", "missing"])
def test_generic_artifact_consumer_uses_verified_identity(case, client, name, damage):
    record = publish(case)
    # Even a registered alternate path must not supply the response bytes.
    case.state.artifacts[name] = str(case.directory / "run_summary.json")
    po.PipelineManager.save(case.state)
    if damage == "failed":
        (case.directory / rc.RECORD_AUDIT_JSON).write_text('{"publication_status":"failed","hard_issues":["fixture"]}')
    elif damage == "json":
        (case.directory / rc.RECORD_JSON).write_text('{}')
    elif damage == "source":
        (case.directory / "world_state.json").write_text('{}')
    elif damage == "missing":
        (case.directory / rc.RECORD_JSON).unlink()
    response = client.get(f"/api/research/{case.state.pipeline_id}/artifact/{name}")
    assert response.status_code == (200 if damage == "none" else 404 if damage == "missing" else 409)
    if damage == "none":
        assert response.json["data"]["content"] == record
    else:
        assert "content" not in json.dumps(response.json)


def test_world_main_reuse_and_seed_produce_records(boundary, monkeypatch):
    b = boundary
    monkeypatch.setattr(Config, "SIM_RECORD_SYNTHESIS", False)
    state = b.pipeline()
    sim = run_pipeline_world(b, state)
    directory = b.root / sim.simulation_id
    assert rc.load_published_record(str(directory))[0] is not None
    assert state.artifacts["simulation_record"] == str(directory / rc.RECORD_JSON)
    before = snapshot(directory)
    run_pipeline_world(b, state)
    assert snapshot(directory) == before and len(b.launches) == 1
    seed = b.po.PipelineOrchestrator()._run_world_seed(state, seed=7)
    assert rc.load_published_record(str(b.root / seed.simulation_id))[0] is not None
    assert state.artifacts["simulation_record"] == str(directory / rc.RECORD_JSON)


def test_parallel_terminal_marker_controls_completion(case, monkeypatch):
    # Extract the actual child producer to avoid importing the OASIS stack.
    path = Path(__file__).parents[1] / "scripts" / "run_parallel_simulation.py"
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_publish_terminal_artifacts_ready")
    import os
    namespace = {"os": os}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    run = case.run
    run.runner_status = RunnerStatus.RUNNING
    run.options["terminal_artifacts_token"] = "current-attempt"
    marker = case.directory / "simulation_artifacts_ready.json"
    marker.write_text('{"schema":"simulation-artifacts-ready/v1","run_token":"old-attempt"}')
    for platform in ("twitter", "reddit"):
        folder = case.directory / platform
        folder.mkdir()
        path = folder / "actions.jsonl"
        path.write_text('{"event_type":"simulation_end","total_rounds":3}\n')
        SimulationRunner._read_action_log(str(path), 0, run, platform)
    assert run.runner_status == RunnerStatus.RUNNING
    SimulationRunner._complete_after_artifact_barrier(run)
    assert run.runner_status == RunnerStatus.RUNNING
    completed = SimpleNamespace(simulation_id=run.simulation_id, status=po.SimulationStatus.COMPLETED)
    assert not case.orchestrator._run_reuse_ready(case.state, completed)
    with pytest.raises(RuntimeError, match="terminal artifacts"):
        case.orchestrator._require_run_completion_evidence(case.state, run.simulation_id, run, True)
    monkeypatch.setenv("SIM_TERMINAL_ARTIFACTS_TOKEN", "current-attempt")
    namespace["_publish_terminal_artifacts_ready"](str(case.directory))
    SimulationRunner._complete_after_artifact_barrier(run)
    assert run.runner_status == RunnerStatus.COMPLETED
    assert case.orchestrator._run_reuse_ready(case.state, completed)
    case.orchestrator._require_run_completion_evidence(case.state, run.simulation_id, run, True)
    SimulationRunner._rotate_stale_action_logs(str(case.directory))
    assert not marker.exists() and Path(str(marker) + ".prev").exists()


def test_hours_posthoc_tail_cannot_publish_completion_before_decisions(case, monkeypatch):
    """Execute the real child finalization tail with a held provider boundary."""
    import os
    from app.services import decision_channel
    from app.utils import llm_client
    source = Path(__file__).parents[1] / "scripts" / "run_parallel_simulation.py"
    tree = ast.parse(source.read_text())
    main = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "main")
    marker = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_publish_terminal_artifacts_ready")
    start = next(i for i, n in enumerate(main.body) if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "_ws_seed" for t in n.targets))
    end = next(i for i, n in enumerate(main.body) if isinstance(n, ast.Expr)
               and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
               and n.value.func.id == "_publish_terminal_artifacts_ready")
    tail = ast.AsyncFunctionDef(name="run_tail", args=ast.arguments(posonlyargs=[], args=[],
        kwonlyargs=[], kw_defaults=[], defaults=[]), body=main.body[start:end + 1], decorator_list=[])
    namespace = dict(os=os, json=json, simulation_dir=str(case.directory),
        config={"world_state_seed": {"scenarios": ["fixture"]}}, _inband_traj_written=False,
        log_manager=SimpleNamespace(info=lambda *a: None, error=lambda *a: None),
        _read_actions_for_decision_channel=lambda p: [], _wrap_llm_client_usage=lambda c: c,
        _build_round_to_date=lambda *a: {})
    exec(compile(ast.fix_missing_locations(ast.Module(body=[marker, tail], type_ignores=[])), str(source), "exec"), namespace)
    trajectory = case.directory / "world_state_trajectory.json"
    result = json.loads(trajectory.read_text())
    trajectory.unlink()
    entered, release = threading.Event(), threading.Event()
    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(5), "test did not release the provider boundary"
        return result
    monkeypatch.setattr(decision_channel, "run_decision_channel", delayed)
    monkeypatch.setattr(llm_client, "LLMClient", lambda: object())
    monkeypatch.setenv("SIM_DECISION_CHANNEL", "true")
    monkeypatch.setenv("SIM_TERMINAL_ARTIFACTS_TOKEN", "hours-attempt")
    case.run.runner_status = RunnerStatus.RUNNING
    case.run.options["terminal_artifacts_token"] = "hours-attempt"
    with ThreadPoolExecutor(max_workers=1) as worker:
        future = worker.submit(lambda: asyncio.run(namespace["run_tail"]()))
        try:
            assert entered.wait(5)
            SimulationRunner._complete_after_artifact_barrier(case.run)
            assert case.run.runner_status == RunnerStatus.RUNNING
            assert not trajectory.exists()
            assert not (case.directory / "simulation_artifacts_ready.json").exists()
        finally:
            release.set()
        future.result(timeout=5)
    assert trajectory.exists() and (case.directory / "decisions.jsonl").exists()
    SimulationRunner._complete_after_artifact_barrier(case.run)
    assert case.run.runner_status == RunnerStatus.COMPLETED
    assert rc.load_published_record(str(case.directory))[0] is None
    publish(case)


@pytest.mark.parametrize("terminal", [RunnerStatus.STOPPING, RunnerStatus.STOPPED, RunnerStatus.FAILED])
def test_artifact_barrier_preserves_concurrent_stop(case, monkeypatch, terminal):
    entered, release = threading.Event(), threading.Event()
    def held_read(state):
        entered.set()
        assert release.wait(5)
        return True
    monkeypatch.setattr(SimulationRunner, "_terminal_artifacts_ready", held_read)
    case.run.runner_status = RunnerStatus.RUNNING
    with ThreadPoolExecutor(max_workers=1) as worker:
        future = worker.submit(SimulationRunner._complete_after_artifact_barrier, case.run)
        try:
            assert entered.wait(5)
            with case.run._lock:
                case.run.runner_status = terminal
                case.run.completed_at = "stop-transition"
        finally:
            release.set()
        future.result(timeout=5)
    assert case.run.runner_status == terminal
    assert case.run.completed_at == "stop-transition"
    monkeypatch.setattr(SimulationRunner, "write_run_summary", lambda *a, **k: None)
    monkeypatch.setattr(SimulationRunner, "reconcile_completed_record_state",
                        lambda *a, **k: pytest.fail("stop was finalized as successful"))
    calls = []
    monkeypatch.setattr(SimulationRunner, "publish_simulation_record", lambda *a, **k: calls.append(k))
    SimulationRunner._finalize_standalone_artifacts(case.run)
    assert all(call["synthesis"] is False for call in calls)


def test_standalone_finalization_and_pipeline_ownership(case, monkeypatch):
    original_summary = json.loads((case.directory / "run_summary.json").read_text())
    writes = []
    monkeypatch.setattr(SimulationRunner, "write_run_summary", lambda sid: writes.append(sid) or original_summary)
    case.run.options["record_owner"] = "pipeline"
    SimulationRunner._finalize_standalone_artifacts(case.run)
    assert not writes
    case.run.options["record_owner"] = "runner"
    SimulationRunner._finalize_standalone_artifacts(case.run)
    before = snapshot(case.directory)
    SimulationRunner._finalize_standalone_artifacts(case.run)
    assert writes == [case.directory.name]
    assert snapshot(case.directory) == before
    assert rc.load_published_record(str(case.directory))[0] is not None


def test_standalone_world_start_publishes_at_native_terminal_boundary(boundary, monkeypatch):
    from test_world_lifecycle import prepare
    b = boundary
    monkeypatch.setattr(Config, "SIM_RECORD_SYNTHESIS", False)
    prepare(b)
    run = b.runner.start_simulation(b.sim.simulation_id)
    assert run.runner_status == RunnerStatus.COMPLETED
    assert rc.load_published_record(str(b.root / b.sim.simulation_id))[0] is not None


def test_failed_child_produces_a_deterministic_health_stub(case, monkeypatch):
    case.run.runner_status = RunnerStatus.FAILED
    case.run.error = "scripted child failure"
    case.run.options["record_owner"] = "pipeline"
    monkeypatch.setattr(Config, "SIM_RECORD_SYNTHESIS", True)
    monkeypatch.setattr(compiler, "_apply_synthesis", lambda *a, **k: pytest.fail("failed run called a model"))
    SimulationRunner._finalize_standalone_artifacts(case.run)
    record, status = rc.load_published_record(str(case.directory))
    assert record is not None, status
    assert record["limits"]["stub"] is True


@pytest.mark.parametrize("survivor", [rc.RECORD_MD, rc.RECORD_MD_ZH])
def test_markdown_only_survivor_disables_paid_repair(case, monkeypatch, survivor):
    (case.directory / survivor).write_text("Old record rendering")
    monkeypatch.setattr(Config, "SIM_RECORD_SYNTHESIS", True)
    monkeypatch.setattr(compiler, "_apply_synthesis", lambda *a, **k: pytest.fail("Markdown-only repair spent on synthesis"))
    assert not (case.directory / rc.RECORD_JSON).exists()
    assert not (case.directory / rc.RECORD_AUDIT_JSON).exists()
    assert not (case.directory / "simulation_record_attempt.json").exists()
    assert SimulationRunner.publish_simulation_record(case.directory.name)
    assert rc.load_published_record(str(case.directory))[0] is not None


@pytest.mark.parametrize("damage", ["remove", "tamper"])
@pytest.mark.parametrize("existing_record", [False, True])
def test_world_native_manifest_required_for_publish_and_public_consumer(boundary, monkeypatch, damage, existing_record):
    from test_world_lifecycle import prepare
    b = boundary
    monkeypatch.setattr(Config, "SIM_RECORD_SYNTHESIS", False)
    prepare(b)
    run = b.runner.start_simulation(b.sim.simulation_id, finalize_record=False)
    assert run.runner_status == RunnerStatus.COMPLETED
    directory = b.root / b.sim.simulation_id
    if existing_record:
        assert b.runner.publish_simulation_record(b.sim.simulation_id)
        assert b.client.get(f"/api/simulation/{b.sim.simulation_id}/record").status_code == 200
    manifest = directory / "world_result_manifest.json"
    original = manifest.read_bytes()
    if damage == "remove":
        manifest.unlink()
    else:
        data = json.loads(original)
        data["resultSha256"] = "0" * 64
        manifest.write_text(json.dumps(data))
    assert b.service.WorldSimulationService.status(b.sim.simulation_id)["runner_status"] == "failed"
    # Already-published records must be withheld without invoking a writer.
    assert rc.load_published_record(str(directory))[0] is None
    if existing_record:
        assert b.client.get(f"/api/simulation/{b.sim.simulation_id}/record").status_code == 409
    with pytest.MonkeyPatch.context() as blocked:
        blocked.setattr(compiler, "build_record", lambda *a, **k: pytest.fail("compiled an unverified native world"))
        assert not b.runner.publish_simulation_record(b.sim.simulation_id)
        b.runner._start_world_record_monitor(b.sim.simulation_id)
    assert rc.load_published_record(str(directory))[0] is None
    manifest.write_bytes(original)
    assert b.runner.publish_simulation_record(b.sim.simulation_id)
    assert rc.load_published_record(str(directory))[0] is not None


def test_obsolete_world_finalizer_cannot_touch_new_launch_record(boundary, monkeypatch):
    from test_world_lifecycle import prepare
    b = boundary
    monkeypatch.setattr(Config, "SIM_RECORD_SYNTHESIS", False)
    prepare(b)
    b.runner.start_simulation(b.sim.simulation_id)
    current = b.runner._world_record_launch_identity(b.sim.simulation_id)
    directory = b.root / b.sim.simulation_id
    before = snapshot(directory)
    assert not b.runner.publish_simulation_record(b.sim.simulation_id, engine_hint="world-v1",
                                                  world_launch_identity=(*current[:2], "prior-launch"))
    assert snapshot(directory) == before
    assert rc.load_published_record(str(directory))[0] is not None


def test_relaunched_world_gets_finalizer_while_old_worker_is_exiting(monkeypatch):
    from app.services.world_simulation.service import WorldSimulationService
    old = ("sim_monitor", "world_generation", "old-launch")
    new = ("sim_monitor", "world_generation", "new-launch")
    current = {"identity": old}
    counts = {old: 0, new: 0}
    entered = {old: threading.Event(), new: threading.Event()}
    release = {old: threading.Event(), new: threading.Event()}
    monkeypatch.setattr(SimulationRunner, "_record_threads", {})
    monkeypatch.setattr(SimulationRunner, "_world_record_launch_identity", lambda sid: current["identity"])
    def status(*args, **kwargs):
        identity = current["identity"]
        counts[identity] += 1
        return {"runner_status": "running" if counts[identity] == 1 else "failed" if identity == old else "completed"}
    monkeypatch.setattr(WorldSimulationService, "status", status)
    published = []
    def publish_record(sid, **kwargs):
        identity = kwargs["world_launch_identity"]
        entered[identity].set()
        assert release[identity].wait(5)
        if identity == current["identity"]:
            published.append(identity)
        return identity == current["identity"]
    monkeypatch.setattr(SimulationRunner, "publish_simulation_record", publish_record)
    workers = []
    try:
        SimulationRunner._start_world_record_monitor(old[0])
        workers.append(SimulationRunner._record_threads[old])
        assert entered[old].wait(5)
        current["identity"] = new
        SimulationRunner._start_world_record_monitor(new[0])
        workers.append(SimulationRunner._record_threads[new])
        assert entered[new].wait(5), "old finalizer swallowed the new launch"
        release[old].set()
        workers[0].join(5)
        assert not workers[0].is_alive()
        assert new in SimulationRunner._record_threads, "old cleanup removed the new worker"
    finally:
        for event in release.values():
            event.set()
        for worker in workers:
            worker.join(5)
    assert published == [new]
    assert not SimulationRunner._record_threads
