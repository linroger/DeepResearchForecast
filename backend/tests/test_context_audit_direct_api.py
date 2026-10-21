"""Direct routes, real storage/bindings/producers, scripted external responses.

Run only through the unchanged main_offline_pytest runner in a fresh mirror.
"""
from copy import deepcopy
import json
import hashlib
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from app.api import report as report_api, simulation as simulation_api
from app.config import Config
from app.models.project import ProjectManager
from app.models.task import TaskManager, TaskStatus
from app.services import backtest_mode, official_data, pipeline_orchestrator as pipeline, forecast_ledger
from app.services.report_agent import Report, ReportAgent, ReportManager, ReportStatus
from app.services.simulation_manager import SimulationManager, SimulationState, SimulationStatus
from app.services.simulation_runner import SimulationRunner
from tests.test_actor_context_runtime import REPORT, _dossier
from tests.test_context_audit_prepare import prepare_env
from tests.test_context_audit_report import Graph, ScriptedModel
from tests.test_final_publish_audit import _forecast
from tests.test_forecast_feedback_sdk import published


pytestmark = pytest.mark.guarded_runner


QUESTION = "请评估电网许可。"
POLICY = {"report_spine_selfconsistency_k": 1, "ensemble_extremize_a": 1.0,
          "simulation_forecast_effect": "diagnostic_only"}
ARTIFACTS = {
    "quantitative": [{"metric": "BOUND_CAPACITY", "value": 47, "unit": "GW", "tier": "S1"}],
    "contested": [{"claim": "BOUND_DISAGREEMENT", "positions": [{"stance": "constrained"}]}],
    "timeline_events": [{"date": "2027-01-01", "event": "BOUND_TIMELINE"}],
    "graph_priors": {"Alpha Systems": 0.8},
    "graph_priors_structural": {"chokepoints": ["Alpha Systems"]},
}


class InlineThread:
    def __init__(self, target, **_kwargs):
        self.target = target

    def start(self):
        self.target()


_REAL_THREAD = threading.Thread


def _dispatch_thread(target, **kwargs):
    if target.__name__ in {"run_prepare", "run_generate"}:
        return InlineThread(target, **kwargs)
    return _REAL_THREAD(target=target, **kwargs)


def _client():
    app = Flask(__name__)
    app.register_blueprint(simulation_api.simulation_bp, url_prefix="/api/simulation")
    app.register_blueprint(report_api.report_bp, url_prefix="/api/report")
    return app.test_client()


def _request(fn, payload):
    path = {simulation_api.prepare_simulation: "/api/simulation/prepare",
            simulation_api.start_simulation: "/api/simulation/start",
            report_api.generate_report: "/api/report/generate",
            report_api.chat_with_report_agent: "/api/report/chat",
            report_api.get_generate_status: "/api/report/generate/status"}[fn]
    response = _client().post(path, json=payload)
    return response.status_code, response.get_json()


@pytest.fixture
def bound_case(tmp_path, monkeypatch):
    simulations = tmp_path / "simulations"
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(simulations))
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(simulations))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(simulations))
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"))
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(threading, "Thread", _dispatch_thread)
    project = ProjectManager.create_project("Direct API audit")
    project.simulation_requirement = "MUTABLE_PROJECT_QUESTION"
    project.graph_id = "graph_fixture"
    ProjectManager.save_project(project)
    ProjectManager.save_extracted_text(project.project_id, "MUTABLE_PROJECT_PROSE")
    manager = SimulationManager()
    simulation = manager.create_simulation(project.project_id, project.graph_id)
    state = pipeline.PipelineState(pipeline_id="pipe_direct", prompt=QUESTION,
                                   project_id=project.project_id, simulation_id="sim_primary")
    state.options.update({"research_language": "English", "max_rounds": 12,
                          "safety_policy_v1": deepcopy(POLICY),
                          "backtest_v1": backtest_mode.normalize_backtest_request({
                              "as_of": "2025-01-01", "arm": "research_only"})})
    handoff = Path(pipeline.PipelineManager.handoff_dir(state.pipeline_id))
    handoff.mkdir(parents=True)
    state.handoff_dir = str(handoff)
    pipeline.PipelineManager.save(state)
    dossier = _dossier()
    dossier["forecast_horizon"] = "2029-12-31"
    for name, value in {"actors.json": dossier, "sources.json": [], **{
        ("timeline.json" if key == "timeline_events" else key + ".json"): value
        for key, value in ARTIFACTS.items()}}.items():
        (handoff / name).write_text(json.dumps(value))
    (handoff / "research_report.md").write_text(REPORT)
    official_data.bind_simulation_research(simulation.simulation_id, handoff,
                                           pipeline_id=state.pipeline_id)
    return SimpleNamespace(simulation=simulation, manager=manager, state=state,
                           handoff=handoff, actors=dossier)


@pytest.mark.parametrize("primary", [False, True])
def test_policy_reads_exact_owner_for_primary_and_bound_secondary(bound_case, primary):
    case = bound_case
    sid = case.simulation.simulation_id
    if primary:
        case.state.simulation_id = sid
        pipeline.PipelineManager.save(case.state)
    assert backtest_mode.policy_for_simulation(sid) == case.state.options["backtest_v1"]
    # A project lookup or an unrelated later pipeline may not replace ownership.
    foreign = pipeline.PipelineState(pipeline_id="pipe_foreign", prompt="foreign",
                                     project_id=case.state.project_id, simulation_id="sim_foreign")
    pipeline.PipelineManager.save(foreign)
    assert backtest_mode.policy_for_simulation(sid) == case.state.options["backtest_v1"]


@pytest.mark.parametrize("mutation", ["research", "missing_owner", "bad_option"])
def test_required_bound_policy_failure_cannot_become_live(bound_case, mutation):
    case = bound_case
    if mutation == "research":
        (case.handoff / "research_report.md").write_text("FOREIGN_GENERATION")
    elif mutation == "missing_owner":
        Path(pipeline.PipelineManager.state_path(case.state.pipeline_id)).unlink()
    else:
        case.state.options["backtest_v1"] = {"version": "broken"}
        pipeline.PipelineManager.save(case.state)
    with pytest.raises(ValueError):
        backtest_mode.policy_for_simulation(case.simulation.simulation_id)


def test_unbound_same_project_does_not_inherit_policy(bound_case):
    other = bound_case.manager.create_simulation(bound_case.state.project_id, "graph_fixture")
    assert backtest_mode.policy_for_simulation(other.simulation_id) is None


def test_optional_dataset_failure_keeps_verified_core_policy(bound_case):
    case = bound_case
    data = case.handoff / "data"
    data.mkdir()
    (data / "datasets.json").write_text("{}")
    # Adding a previously absent optional dataset invalidates enrichment proof,
    # while the consumed core remains verifiable. Never select a live arm.
    assert official_data.simulation_research_binding(case.simulation.simulation_id)["status"] == "invalid"
    assert backtest_mode.policy_for_simulation(case.simulation.simulation_id) == case.state.options["backtest_v1"]


def test_core_change_while_loading_owner_is_rejected(bound_case, monkeypatch):
    original = pipeline.PipelineManager.load
    def load(pid):
        result = original(pid)
        (bound_case.handoff / "research_report.md").write_text("CHANGED_DURING_OWNER_READ")
        return result
    monkeypatch.setattr(pipeline.PipelineManager, "load", load)
    with pytest.raises(ValueError, match="changed"):
        backtest_mode.policy_for_simulation(bound_case.simulation.simulation_id)


@pytest.mark.parametrize("arm", [None, {}, {"name": "research_only"},
    {"name": "research_only", "markets": True, "simulation": True, "world_channel": True},
    {"name": "research_only", "markets": 0, "simulation": False, "world_channel": False}])
def test_malformed_saved_arm_cannot_enable_live_defaults(bound_case, arm):
    case = bound_case
    case.state.options["backtest_v1"]["arm"] = arm
    pipeline.PipelineManager.save(case.state)
    with pytest.raises(ValueError, match="arm"):
        backtest_mode.policy_for_simulation(case.simulation.simulation_id)


@pytest.mark.parametrize("arm", list(backtest_mode.ARMS))
def test_each_valid_saved_arm_keeps_admitted_flags(bound_case, arm):
    case = bound_case
    policy = backtest_mode.normalize_backtest_request({"as_of": "2025-01-01", "arm": arm})
    case.state.options["backtest_v1"] = policy
    pipeline.PipelineManager.save(case.state)
    assert backtest_mode.policy_for_simulation(case.simulation.simulation_id) == policy


@pytest.mark.parametrize("field,value", [("as_of", "not-a-date"), ("strict", 1), ("archive", "live")])
def test_damaged_saved_cutoff_controls_are_rejected(bound_case, field, value):
    case = bound_case
    case.state.options["backtest_v1"][field] = value
    pipeline.PipelineManager.save(case.state)
    with pytest.raises(ValueError):
        backtest_mode.policy_for_simulation(case.simulation.simulation_id)


@pytest.mark.parametrize("endpoint", ["prepare", "generate", "chat"])
def test_routes_reject_changed_bound_core_before_dispatch(bound_case, monkeypatch, endpoint):
    case = bound_case
    (case.handoff / "actors.json").write_text('{"actors":[],"foreign":true}')
    def forbidden(*args, **kwargs):
        pytest.fail("changed bound core reached a producer")
    monkeypatch.setattr(SimulationManager, "prepare_simulation", forbidden)
    monkeypatch.setattr(report_api, "ReportAgent", forbidden)
    fn = {"prepare": simulation_api.prepare_simulation, "generate": report_api.generate_report,
          "chat": report_api.chat_with_report_agent}[endpoint]
    code, response = _request(fn, {"simulation_id": case.simulation.simulation_id, "message": "scope"})
    assert code >= 400 and response["success"] is False


def test_unbound_prepare_keeps_project_fallback(prepare_env, bound_case, monkeypatch):
    case = bound_case
    simulation = case.manager.create_simulation(case.state.project_id, "graph_fixture")
    monkeypatch.setattr(simulation_api, "ZepEntityReader", lambda: SimpleNamespace(
        filter_defined_entities=lambda **kw: SimpleNamespace(filtered_count=0, entity_types=set())))
    actual = SimulationManager.prepare_simulation
    calls = []
    def prepare(self, **kwargs):
        calls.append(kwargs)
        return actual(self, **kwargs)
    monkeypatch.setattr(SimulationManager, "prepare_simulation", prepare)
    code, response = _request(simulation_api.prepare_simulation, {"simulation_id": simulation.simulation_id})
    assert code == 200, response
    task = TaskManager().get_task(response["data"]["task_id"])
    assert task.status == TaskStatus.FAILED
    assert calls[0]["simulation_requirement"] == "MUTABLE_PROJECT_QUESTION"
    assert calls[0]["document_text"] == "MUTABLE_PROJECT_PROSE"
    assert calls[0]["actors"] is None
    saved = SimulationManager().get_simulation(simulation.simulation_id)
    assert saved.status == SimulationStatus.FAILED and saved.actor_context_count == 0


@pytest.mark.parametrize("budget", ["explicit", "calendar_default", "hours_default"])
def test_direct_prepare_reaches_actual_context_config_and_roles(prepare_env, bound_case, monkeypatch, budget):
    case = bound_case
    expected_budget = 12
    if budget != "explicit":
        case.state.options.pop("max_rounds")
        pipeline.PipelineManager.save(case.state)
        expected_budget = None if budget == "calendar_default" else 9
    if budget == "hours_default":
        monkeypatch.setattr(Config, "SIM_TEMPORAL_MODE", "hours")
        monkeypatch.setattr(Config, "OASIS_DEFAULT_MAX_ROUNDS", 9)
    actual = SimulationManager.prepare_simulation
    calls = []
    def prepare(self, **kwargs):
        calls.append(deepcopy(kwargs))
        return actual(self, **kwargs)
    monkeypatch.setattr(SimulationManager, "prepare_simulation", prepare)
    # External graph response only. The real manager, context packs, role
    # compiler, config prompt, persisted seal and task storage remain real.
    monkeypatch.setattr(simulation_api, "ZepEntityReader", lambda: SimpleNamespace(
        filter_defined_entities=lambda **kw: SimpleNamespace(filtered_count=0, entity_types=set())))
    code, response = _request(simulation_api.prepare_simulation,
                              {"simulation_id": case.simulation.simulation_id})
    assert code == 200, response
    task = TaskManager().get_task(response["data"]["task_id"])
    assert task.status == TaskStatus.COMPLETED, task.error
    state = SimulationManager().get_simulation(case.simulation.simulation_id)
    assert state.actor_context_count == state.actor_role_count == 2
    directory = Path(case.manager._get_simulation_dir(state.simulation_id))
    config = json.loads((directory / "simulation_config.json").read_text())
    assert config["simulation_requirement"] == QUESTION
    assert config["output_language"] == "English"
    if budget != "hours_default":
        assert "2029-12-31" in json.dumps(config)
    assert len(calls) == 1 and calls[0]["max_rounds"] == expected_budget
    assert calls[0]["graph_priors"] == ARTIFACTS["graph_priors"]
    assert calls[0]["actors"] == case.actors
    assert "2026-07-01" in json.dumps(prepare_env)
    assert "MUTABLE_PROJECT_PROSE" not in json.dumps(prepare_env)
    case.manager.validate_prepared_simulation_config(state.simulation_id)


@pytest.mark.parametrize("scenario", [False, True])
@pytest.mark.parametrize("endpoint", ["generate", "chat"])
def test_manual_routes_deliver_rich_context_and_saved_policy(bound_case, monkeypatch, endpoint, scenario):
    case = bound_case
    agents = []
    model = ScriptedModel()
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", False)
    monkeypatch.setattr(Config, "REPORT_VISUALIZATIONS", False)
    baseline = pipeline.PipelineState(pipeline_id="pipe_baseline", prompt="baseline",
                                      simulation_id="sim_baseline")
    pipeline.PipelineManager.save(baseline)
    if scenario:
        case.state.options.update(scenario_label="BOUND_SCENARIO", base_pipeline_id=baseline.pipeline_id)
        pipeline.PipelineManager.save(case.state)

    def construct(**kwargs):
        agent = ReportAgent(**kwargs, llm_client=model, zep_tools=Graph())
        agents.append(agent)
        agent.plan_outline()
        return agent

    monkeypatch.setattr(report_api, "ReportAgent", construct)
    fn = report_api.generate_report if endpoint == "generate" else report_api.chat_with_report_agent
    code, response = _request(fn, {"simulation_id": case.simulation.simulation_id,
                                   "message": "Discuss the constraints"})
    assert code == 200, response
    assert len(agents) == 1
    agent = agents[0]
    assert agent.simulation_requirement == QUESTION
    assert agent._report_policy == POLICY
    assert agent._backtest() == case.state.options["backtest_v1"]
    assert agent._simulation_forecast_effect() == "no_update"
    for key, value in ARTIFACTS.items():
        assert getattr(agent, key) == value, key
    actual_prompt = json.dumps(model.calls, ensure_ascii=False)
    if scenario:
        assert agent.base_simulation_id == baseline.simulation_id
        assert agent.scenario_label == "BOUND_SCENARIO"
        assert "BOUND_SCENARIO" in actual_prompt
    else:
        assert agent.base_simulation_id is None and not agent.scenario_label
        assert "BOUND_SCENARIO" not in actual_prompt


@pytest.mark.parametrize("failure", [None, "write", "start"])
@pytest.mark.parametrize("status", [SimulationStatus.COMPLETED, SimulationStatus.READY,
                                   SimulationStatus.RUNNING])
def test_force_restart_retires_current_cache_preserving_publication(
    prepare_env, bound_case, monkeypatch, status, failure,
):
    case = bound_case
    sid = case.simulation.simulation_id
    state = case.manager.prepare_simulation(sid, QUESTION, REPORT, actors=case.actors,
                                           research_language="English", max_rounds=12)
    state.status = status
    case.manager._save_simulation_state(state)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True)
    agent = ReportAgent("graph_fixture", sid, QUESTION, llm_client=ScriptedModel(), zep_tools=Graph(),
                        report_policy=POLICY, research_report=REPORT)
    # A deterministic saved report input, sealed by the real read-only auditor.
    # Restart acceptance does not substitute generation, QA or publication code.
    report = Report(report_id="report_before_restart", simulation_id=sid, graph_id="graph_fixture",
                    simulation_requirement=QUESTION, status=ReportStatus.COMPLETED,
                    markdown_content="# Forecast\n\nCapacity depends on executed investment. The outcome remains uncertain.\n")
    ReportManager.save_report(report)
    folder = Path(ReportManager._get_report_folder(report.report_id))
    forecast = _forecast()
    forecast["backtest"] = backtest_mode.forecast_block(case.state.options["backtest_v1"])
    (folder / "forecast.json").write_text(json.dumps(forecast))
    audit = agent._audit_final_published_markdown(report.report_id, report)
    assert audit["hard_passed"] is True
    assert audit["publish_gate"]["enabled"] is True and audit["publish_gate"]["passed"] is True
    assert ReportManager.is_publishable(report.report_id)
    assert ReportManager.get_report_by_simulation(sid).report_id == report.report_id
    assert simulation_api._get_report_id_for_simulation(sid) == report.report_id
    original_markdown = (folder / "full_report.md").read_bytes()
    original_audit = (folder / "final_audit.json").read_bytes()
    # Preserve an unrelated simulation's publication bytes as a sibling control.
    sibling = folder.parent / "report_sibling"
    sibling.mkdir()
    (sibling / "meta.json").write_text(json.dumps({
        **report.to_dict(), "report_id": "report_sibling", "simulation_id": "sim_sibling"}))
    (sibling / "final_audit.json").write_bytes(original_audit)
    started = []
    runtime_calls = []
    actual_cleanup = SimulationRunner.cleanup_simulation_logs

    def cleanup(identity):
        runtime_calls.append("cleanup")
        return actual_cleanup(identity)

    def stop(identity):
        runtime_calls.append("stop")

    monkeypatch.setattr(SimulationRunner, "cleanup_simulation_logs", cleanup)
    monkeypatch.setattr(SimulationRunner, "stop_simulation", stop)
    if status == SimulationStatus.RUNNING:
        monkeypatch.setattr(SimulationRunner, "get_run_state", lambda identity: SimpleNamespace(
            runner_status=SimpleNamespace(value="running")))

    def start(**kwargs):
        # Invalidation must precede any new platform work, including failure.
        runtime_calls.append("start")
        started.append(kwargs)
        assert (folder / "final_audit.json").read_bytes() == original_audit
        assert ReportManager.is_publishable(report.report_id)
        current = _client().get(f"/api/report/by-simulation/{sid}")
        assert current.status_code == 404
        if failure == "start":
            raise RuntimeError("scripted platform failure")
        return SimpleNamespace(to_dict=lambda: {}, graph_memory_active=False,
                               graph_memory_requested=False, graph_memory_error=None)

    monkeypatch.setattr(SimulationRunner, "start_simulation", start)
    if failure == "write":
        from app.services import report_agent
        original_write = report_agent.write_json_atomic
        def fail_audit(path, *args, **kwargs):
            if Path(path).name == "current_simulation_retirement.json":
                raise OSError("scripted invalidation failure")
            return original_write(path, *args, **kwargs)
        monkeypatch.setattr(report_agent, "write_json_atomic", fail_audit)
    code, response = _request(simulation_api.start_simulation, {"simulation_id": sid, "force": True})
    assert (sibling / "final_audit.json").read_bytes() == original_audit
    if failure == "write":
        assert code == 500 and not started, response
        assert runtime_calls == [], "Retirement failure must precede stop, cleanup and start"
        assert (folder / "final_audit.json").read_bytes() == original_audit
        assert (folder / "full_report.md").read_bytes() == original_markdown
        assert SimulationManager().get_simulation(sid).status == status
        return
    assert code == (500 if failure == "start" else 200), response
    assert started
    assert runtime_calls == (["stop", "cleanup", "start"] if status == SimulationStatus.RUNNING
                             else ["cleanup", "start"] if status == SimulationStatus.COMPLETED
                             else ["start"])
    assert ReportManager.is_publishable(report.report_id)
    assert simulation_api._get_report_id_for_simulation(sid) is None
    assert (folder / "full_report.md").read_bytes() == original_markdown
    assert (folder / "final_audit.json").read_bytes() == original_audit
    code, response = _request(report_api.get_generate_status, {"simulation_id": sid})
    assert not response.get("data", {}).get("already_completed")
    response = _client().get(f"/api/report/{report.report_id}/download")
    assert response.status_code == 200


@pytest.mark.parametrize('action', ['none', 'same-simulation', 'sibling-simulation', 'tampered-report'])
def test_simulation_restart_retires_current_cache_but_preserves_published_resolution(
    published, monkeypatch, action,
):
    case = published
    report, folder, client = case['report'], case['folder'], case['client']
    sid = report.simulation_id
    monkeypatch.setattr(SimulationManager, 'SIMULATION_DATA_DIR', Config.OASIS_SIMULATION_DATA_DIR)
    monkeypatch.setattr(SimulationRunner, 'RUN_STATE_DIR', Config.OASIS_SIMULATION_DATA_DIR)
    manager = SimulationManager()
    for identity in (sid, 'sim_review_sibling'):
        manager._save_simulation_state(SimulationState(simulation_id=identity, project_id='project_review',
            graph_id=report.graph_id, status=SimulationStatus.READY, config_generated=True))
    journal_path = case['ledger'] / 'published_forecasts.jsonl'
    before_journal = journal_path.read_bytes()
    before_audit = (folder / 'final_audit.json').read_bytes()
    before_snapshot = forecast_ledger.read_published_forecast(report.report_id)
    assert before_snapshot == case['snapshot']
    assert not before_snapshot['forecast'].get('backtest')
    assert ReportManager.publication_status(report.report_id)['publishable']
    starts = []
    def spawn(**kwargs):
        starts.append(kwargs)
        return SimpleNamespace(to_dict=lambda: {'simulation_id': kwargs['simulation_id'], 'runner_status': 'running'},
            graph_memory_active=False, graph_memory_requested=False, graph_memory_error=None)
    monkeypatch.setattr(SimulationRunner, 'start_simulation', spawn)
    restart = None
    if action in ('same-simulation', 'sibling-simulation'):
        restart = client.post('/api/simulation/start', json={
            'simulation_id': sid if action == 'same-simulation' else 'sim_review_sibling', 'force': True})
        assert restart.status_code == 200, restart.get_json()
        assert starts
    if action == 'tampered-report':
        (folder / 'full_report.md').write_text('TAMPERED AFTER PUBLICATION')
    # A restart never authorizes rewriting the retained publication row.
    assert journal_path.read_bytes() == before_journal
    assert forecast_ledger.read_published_forecast(report.report_id) == before_snapshot
    response = client.post('/api/v1/resolve/' + report.report_id, json={'outcome': 'Base case'})
    record = {'action': action, 'restart': restart.get_json() if restart is not None else None,
              'resolve_status': response.status_code, 'resolve_response': response.get_json(),
              'publication_status': ReportManager.publication_status(report.report_id),
              'original_audit_sha256': hashlib.sha256(before_audit).hexdigest(),
              'current_audit_sha256': hashlib.sha256((folder / 'final_audit.json').read_bytes()).hexdigest(),
              'published_snapshot': before_snapshot}
    (folder / 'independent-restart-ledger-proof.json').write_text(json.dumps(record, indent=2))
    if action == 'tampered-report':
        assert response.status_code == 409
        assert journal_path.read_bytes() == before_journal
        return
    assert response.status_code == 200, response.get_json()
    scoring = response.get_json()['data']['scoring']
    assert scoring['brier'] == pytest.approx(0.18)
    assert scoring['realized_probability'] == 0.7
    assert (folder / 'final_audit.json').read_bytes() == before_audit
