"""Real ensemble admission/replay and seed-report consumer boundary checks."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Config
from app.services import pipeline_orchestrator as po
from app.services.report_agent import ReportAgent, ReportManager
from app.services.simulation_manager import SimulationManager

pytestmark = pytest.mark.guarded_runner


def _forecast(p=.6):
    return {"scenarios": [{"name": "Approved", "probability": p,
                            "resolution_criteria": "Permit approved by 2029"},
                           {"name": "Other", "probability": 1-p,
                            "resolution_criteria": "Permit not approved by 2029"}]}


@pytest.fixture
def ensemble(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"))
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(Config, "ENSEMBLE_SEED_CONCURRENCY", 1)
    monkeypatch.setattr(Config, "SIM_SEED", 0)
    monkeypatch.setattr(Config, "REPORT_STRUCTURED_FORECAST", True)
    monkeypatch.setattr(Config, "CALENDAR_MODE", False, raising=False)
    state = po.PipelineState(pipeline_id="pipe_ensemble_child", prompt="Will the permit be approved by 2029?",
                             mode="full", report_id="report_primary", options={
                                 "safety_policy_v1": {"n_forecast_seeds": 2,
                                                       "ensemble_extremize_a": 1.0,
                                                       "report_spine_selfconsistency_k": 1,
                                                       "simulation_forecast_effect": "diagnostic_only"}})
    po.PipelineManager.ensure_dirs(state.pipeline_id)
    state.handoff_dir = po.PipelineManager.handoff_dir(state.pipeline_id)
    po.PipelineManager.save(state)
    def publish(rid, fc):
        folder = Path(ReportManager._get_report_folder(rid))
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "forecast.json").write_text(json.dumps(fc))
    publish(state.report_id, _forecast())
    runner = po.PipelineOrchestrator()
    monkeypatch.setattr(runner, "_flush_run_telemetry", lambda *a: None)
    calls = []
    def seed(*a, **kw):
        rid = f"report_fresh_{len(calls)}"
        fc = _forecast(.7)
        publish(rid, fc)
        calls.append(copy.deepcopy(kw))
        return "sim_fresh", rid, fc
    monkeypatch.setattr(runner, "_run_one_seed", seed)
    def run(coordinator=None):
        (coordinator or runner)._maybe_run_seed_ensemble(state, SimpleNamespace(project_id="project_current"),
                                       "graph_current", {"central_question": state.prompt},
                                       {"sources": []}, "CURRENT CONSUMED RESEARCH")
    return SimpleNamespace(state=state, runner=runner, seed=seed, calls=calls, run=run, publish=publish,
                           checkpoint=Path(state.handoff_dir) / "ensemble_checkpoint.json")


@pytest.mark.parametrize("foreign", ["pipeline_id", "primary_report_id", "legacy_unproven"])
def test_foreign_or_unproven_checkpoint_cannot_supply_a_seed(ensemble, foreign):
    e = ensemble
    e.publish("report_foreign", _forecast(.99))
    checkpoint = {"schema_version": 1, "pipeline_id": e.state.pipeline_id,
                  "primary_report_id": e.state.report_id, "completed": [{
                      "seed": 15838, "simulation_id": "sim_foreign", "report_id": "report_foreign"}]}
    if foreign != "legacy_unproven":
        checkpoint[foreign] = "foreign_owner"
    e.checkpoint.write_text(json.dumps(checkpoint))
    e.run()
    assert len(e.calls) == 1, "Foreign/unproven checkpoint bypassed the actual seed producer"
    sidecar = json.loads((Path(e.state.handoff_dir) / "ensemble_forecast.json").read_text())
    assert sidecar["extra_runs"][0]["report_id"] != "report_foreign"


@pytest.mark.parametrize("mutation", ["none", "prompt", "policy", "forecast", "primary", "graph_priors", "scenario_overlay"])
def test_checkpoint_replay_requires_matching_inputs_and_seed_output(ensemble, monkeypatch, mutation):
    e = ensemble
    e.run()
    assert len(e.calls) == 1
    saved = json.loads(e.checkpoint.read_text())
    e.state.options.pop("ensemble_done", None)  # Re-enter the interrupted ensemble window.
    if mutation == "prompt":
        e.state.prompt = "A different forecast question through 2035"
    elif mutation == "policy":
        e.state.options["safety_policy_v1"]["ensemble_extremize_a"] = 2.0
    elif mutation == "forecast":
        e.publish(saved["completed"][0]["report_id"], _forecast(.99))
    elif mutation == "primary":
        e.publish(e.state.report_id, _forecast(.8))
    elif mutation == "graph_priors":
        (Path(e.state.handoff_dir) / "graph_priors.json").write_text('{"NEW_ACTOR": 0.99}')
    elif mutation == "scenario_overlay":
        e.state.options["scenario_overlay"] = {"conditions": {"permit_fast_track": True}}
    # A new coordinator instance exercises persisted checkpoint reuse, not an in-memory cache.
    coordinator = po.PipelineOrchestrator()
    monkeypatch.setattr(coordinator, "_run_one_seed", e.seed)
    monkeypatch.setattr(coordinator, "_flush_run_telemetry", lambda *a: None)
    e.run(coordinator)
    assert len(e.calls) == (1 if mutation == "none" else 2)


@pytest.mark.parametrize("seed_failure", [False, True])
def test_child_ensemble_does_not_write_parent_or_sibling_handoff(ensemble, monkeypatch, seed_failure):
    e = ensemble
    parent = Path(po.PipelineManager.handoff_dir("pipe_parent"))
    parent.mkdir(parents=True)
    for name in ("ensemble_checkpoint.json", "ensemble_forecast.json", "graph_priors.json"):
        (parent / name).write_text(json.dumps({"owner": "parent", "name": name}))
    e.state.handoff_dir = str(parent)
    before = {p.name: p.read_bytes() for p in parent.iterdir()}
    if seed_failure:
        monkeypatch.setattr(e.runner, "_run_one_seed", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("scripted external failure")))
    e.run()
    assert {p.name: p.read_bytes() for p in parent.iterdir()} == before
    own = Path(po.PipelineManager.handoff_dir(e.state.pipeline_id))
    assert (own / "ensemble_checkpoint.json").is_file() or seed_failure


def test_seed_report_receives_scenario_owner_and_actual_baseline_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path / "simulations"))
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    manager = SimulationManager()
    base_sim = manager.create_simulation("project_test", "graph_test", enable_twitter=True, enable_reddit=True)
    base = po.PipelineState(pipeline_id="pipe_base", prompt="Baseline", simulation_id=base_sim.simulation_id)
    po.PipelineManager.ensure_dirs(base.pipeline_id)
    po.PipelineManager.save(base)
    state = po.PipelineState(pipeline_id="pipe_scenario", prompt="Permit forecast through 2029",
                            simulation_id=base_sim.simulation_id, options={
        "scenario_label": "PERMIT_FAST_TRACK", "base_pipeline_id": base.pipeline_id})
    po.PipelineManager.ensure_dirs(state.pipeline_id)
    state.handoff_dir = po.PipelineManager.handoff_dir(state.pipeline_id)
    po.PipelineManager.save(state)
    monkeypatch.setattr(SimulationManager, "prepare_simulation", lambda *a, **kw: None)
    monkeypatch.setattr(po.SimulationRunner, "start_simulation", lambda **kw: None)
    monkeypatch.setattr(po.SimulationRunner, "get_run_state", lambda *a: SimpleNamespace(current_round=1, runner_status=po.RunnerStatus.COMPLETED))
    monkeypatch.setattr(po.SimulationRunner, "write_run_summary", lambda *a: None)
    captured_messages, diffs, constructors = [], [], []
    class Model:
        def chat_json(self, messages: list, **kw):
            captured_messages.extend(copy.deepcopy(messages))
            return {"title": "Forecast", "summary": "Scenario outlook", "sections": [
                {"title": f"Outlook {i}", "description": "Permit evidence"} for i in range(4)]}
    class Graph:
        def get_simulation_context(self, **kw):
            return {"graph_statistics": {}, "related_facts": []}
        def scenario_diff(self, baseline, scenario):
            diffs.append((baseline, scenario))
            return "ACTUAL_BASELINE_DIFF_SENTINEL"
    def report(**kw):
        constructors.append(copy.deepcopy(kw))
        agent = ReportAgent(llm_client=Model(), zep_tools=Graph(), **kw)
        agent.generate_report = lambda **ignored: agent.plan_outline()
        return agent
    monkeypatch.setattr(po, "ReportAgent", report)
    runner = po.PipelineOrchestrator()
    monkeypatch.setattr(runner, "_read_report_forecast", lambda *a: _forecast())
    sim, _, _ = runner._run_one_seed(state, SimpleNamespace(project_id="project_test"), "graph_test", {},
                                    {"sources": []}, "Original research", seed=15838, max_rounds=1)
    assert constructors[0].get("scenario_label") == "PERMIT_FAST_TRACK"
    assert constructors[0].get("base_simulation_id") == base_sim.simulation_id
    prompt = json.dumps(captured_messages, ensure_ascii=False)
    assert "PERMIT_FAST_TRACK" in prompt and "ACTUAL_BASELINE_DIFF_SENTINEL" in prompt
    assert (base_sim.simulation_id, sim) in diffs


def test_new_report_attempt_retires_previous_ensemble_pointers(ensemble):
    e = ensemble
    e.run()
    old_report = Path(ReportManager._get_report_folder(e.state.report_id)) / "ensemble_forecast.json"
    old_bytes = old_report.read_bytes()
    assert e.state.options["ensemble_done"] is True
    e.runner._clear_report_attempt_artifacts(e.state)
    assert not ({"ensemble_done", "ensemble", "ensemble_wall"} & e.state.options.keys())
    assert "ensemble_forecast" not in e.state.artifacts
    assert old_report.read_bytes() == old_bytes, "Retire cache pointers without changing historical reports"
