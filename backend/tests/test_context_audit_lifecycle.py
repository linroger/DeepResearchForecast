"""Actual route/state/manifest probes for orchestration context continuity."""

import pytest
import json
from pathlib import Path
from flask import Flask

import test_backtest_pipeline as backtest_fixtures
from app.services import pipeline_orchestrator as po
from app.services import backtest_mode as bm
import app.api.research as research_api
import app.api.sdk as sdk_api

admission = backtest_fixtures.admission
pytestmark = pytest.mark.guarded_runner


@pytest.fixture
def api_client(admission, monkeypatch):
    monkeypatch.setattr(research_api, "preflight_pipeline", lambda **kw: [])
    monkeypatch.setattr(sdk_api, "preflight_pipeline", lambda **kw: [])
    app = Flask(__name__)
    app.register_blueprint(research_api.research_bp, url_prefix="/api/research")
    app.register_blueprint(sdk_api.sdk_bp, url_prefix="/api/v1")
    return app.test_client()


@pytest.mark.parametrize("route", ["/api/research/run", "/api/v1/run"])
def test_supported_cutoff_reaches_real_admission_and_saved_state(admission, api_client, route):
    response = api_client.post(route, json={"prompt": "CTX request: outlook through 2030", "mode": "research_only",
        "language": "English", "backtest": {"as_of": "2024-11-01", "strict": True, "arm": "research_only"}})
    assert response.status_code == 200, response.get_json()
    pid = response.get_json()["data"]["pipeline_id"]
    state = po.PipelineManager.load(pid)
    assert state["prompt"] == "CTX request: outlook through 2030"
    assert state["options"]["research_language"] == "English"
    assert state["options"][bm.BACKTEST_OPTION]["as_of"] == "2024-11-01"
    assert state["options"][bm.BACKTEST_OPTION]["arm"]["name"] == "research_only"


@pytest.mark.parametrize("route", ["/api/research/run", "/api/v1/run"])
def test_invalid_cutoff_is_not_silently_admitted_as_live(admission, api_client, route):
    before = set(admission.root.iterdir()) if admission.root.exists() else set()
    response = api_client.post(route, json={"prompt": "CTX cutoff request", "mode": "research_only",
                                          "backtest": {"as_of": "not-a-date"}})
    assert response.status_code == 400, response.get_json()
    assert (set(admission.root.iterdir()) if admission.root.exists() else set()) == before
    assert admission.started == []


@pytest.mark.parametrize("route", ["/api/research/run", "/api/v1/run"])
def test_existing_research_language_alias_survives_both_admission_routes(admission, api_client, route):
    response = api_client.post(route, json={"prompt": "CTX English alias request", "mode": "research_only",
                                          "research_language": "English"})
    assert response.status_code == 200, response.get_json()
    saved = po.PipelineManager.load(response.get_json()["data"]["pipeline_id"])
    assert saved["options"]["research_language"] == "English"


def _fork(admission, monkeypatch, overlay=None):
    base = po.PipelineState(pipeline_id="pipe_contextbase", prompt="CTX original forecast through 2030",
                           mode="full", status="completed", project_id="project_context", graph_id="graph_context")
    base.options.update({"project_name": "CTX project", "simulation_engine": "oasis-legacy", "depth": "deep",
        "research_language": "English", "research_model": "minimax", "research_engine": "v3", "max_rounds": 17,
        "actor_intelligence_policy_v1": {"mode": "legacy"},
        "safety_policy_v1": {"sim_graph_feedback": True, "simulation_forecast_effect": "legacy_prompt"}})
    po.PipelineManager.ensure_dirs(base.pipeline_id)
    base.handoff_dir = po.PipelineManager.handoff_dir(base.pipeline_id)
    (admission.root / base.pipeline_id / "handoff" / "research_report.md").write_text("# CTX original findings\n")
    po.PipelineManager.save(base)
    before = (admission.root / base.pipeline_id / "pipeline_state.json").read_bytes()
    child = po.PipelineOrchestrator.fork(base.pipeline_id, overlay or {"label": "CTX changed policy"})
    assert (admission.root / base.pipeline_id / "pipeline_state.json").read_bytes() == before
    return base, child


@pytest.mark.parametrize("field", ["research_language", "research_model", "depth", "research_engine", "max_rounds", "safety_policy_v1"])
def test_scenario_fork_preserves_unchanged_execution_context(admission, monkeypatch, field):
    base, child = _fork(admission, monkeypatch)
    saved = po.PipelineState.from_dict(po.PipelineManager.load(child.pipeline_id))
    assert saved.prompt == base.prompt and saved.handoff_dir == base.handoff_dir
    assert saved.options[field] == base.options[field]
    assert po.PipelineOrchestrator._pinned_safety(saved, "sim_graph_feedback", False) is True


def test_fork_pins_research_manifest_and_honors_explicit_overlay(admission, monkeypatch):
    base, child = _fork(admission, monkeypatch, {"label": "CTX overlay", "max_rounds": 23})
    monkeypatch.setattr(po, "_repo_git_sha", lambda: "source")
    monkeypatch.setattr(po, "_deerflow_ref", lambda: "source")
    manifest = po._build_run_manifest(child)
    assert manifest["resolved"]["research"]["language"] == "English"
    assert manifest["resolved"]["research"]["model"] == "minimax"
    assert manifest["resolved"]["research"]["depth"] == "deep"
    assert child.options["max_rounds"] == 23 and base.options["max_rounds"] == 17
    child.options["safety_policy_v1"]["sim_graph_feedback"] = False
    assert base.options["safety_policy_v1"]["sim_graph_feedback"] is True


@pytest.mark.parametrize("route", ["/api/research/{pid}/dossier", "/api/v1/dossier/{pid}"])
def test_scenario_dossier_reads_the_consumed_shared_handoff(admission, monkeypatch, api_client, route):
    base, child = _fork(admission, monkeypatch)
    response = api_client.get(route.format(pid=child.pipeline_id))
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()["data"]
    assert payload["has_report"] is True
    assert "CTX original findings" in payload["report"]


def test_bound_dossier_exposes_complete_report_artifact_arguments(admission, monkeypatch, tmp_path):
    from app.services import official_data
    from app.services.simulation_manager import SimulationManager
    base, _ = _fork(admission, monkeypatch)
    handoff = Path(base.handoff_dir)
    (handoff / "actors.json").write_text(json.dumps({"actors": [{"name": "CTX Actor", "type": "Company"}]}))
    (handoff / "sources.json").write_text("[]")
    values = {"quantitative": [{"metric": "CTX capacity", "value": 42, "unit": "GW"}],
              "contested": [{"claim": "CTX disputed commissioning date"}],
              "timeline_events": [{"date": "2027-01-01", "event": "CTX commissioning"}],
              "graph_priors": {"CTX Actor": .7},
              "graph_priors_structural": {"chokepoints": ["CTX Actor"]}}
    for key, value in values.items():
        name = "timeline" if key == "timeline_events" else key
        (handoff / (name + ".json")).write_text(json.dumps(value))
    sims = tmp_path / "simulations"
    (sims / "sim_context_extra").mkdir(parents=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sims))
    official_data.bind_simulation_research("sim_context_extra", handoff, pipeline_id=base.pipeline_id)
    loaded = po.load_research_dossier_for_simulation("sim_context_extra")
    assert loaded["report_artifacts"] == values
    loaded["report_artifacts"]["quantitative"].clear()
    assert po.load_research_dossier_for_simulation("sim_context_extra")["report_artifacts"] == values


@pytest.mark.parametrize("failure", [None, "copy", "save"])
def test_private_fork_snapshot_preserves_parent_and_rolls_back_failed_install(admission, monkeypatch, failure):
    base, child = _fork(admission, monkeypatch)
    source = Path(base.handoff_dir)
    (source / "actors.json").write_text('{"actors":[],"central_question":"Original fork task"}')
    (source / "sources.json").write_text('[]')
    (source / "graph_priors.json").write_text('{"Original actor":0.7}')
    before = {p.name: p.read_bytes() for p in source.iterdir() if p.is_file()}
    saved_before = Path(po.PipelineManager.state_path(child.pipeline_id)).read_bytes()
    if failure == "copy":
        def fail_copy(*args, **kwargs):
            raise OSError("scripted snapshot read failure")
        monkeypatch.setattr(po, "_research_data_read", fail_copy)
    elif failure == "save":
        def fail_save(cls, state):
            raise OSError("scripted snapshot state save failure")
        monkeypatch.setattr(po.PipelineManager, "save", classmethod(fail_save))
    if failure:
        with pytest.raises(OSError, match="scripted snapshot"):
            po.PipelineOrchestrator._isolate_fork_handoff(child)
        assert child.handoff_dir == base.handoff_dir
        assert Path(po.PipelineManager.state_path(child.pipeline_id)).read_bytes() == saved_before
        assert not list(Path(po.PipelineManager._dir(child.pipeline_id)).glob("consumed-handoff-*"))
    else:
        po.PipelineOrchestrator._isolate_fork_handoff(child)
        private = Path(child.handoff_dir)
        assert private.is_relative_to(Path(po.PipelineManager._dir(child.pipeline_id)))
        assert {p.name: p.read_bytes() for p in private.iterdir() if p.is_file()} == before
        loaded = po.PipelineState.from_dict(po.PipelineManager.load(child.pipeline_id))
        assert loaded.handoff_dir == child.handoff_dir
        from app.services.official_data import capture_research_generation
        assert capture_research_generation(private)["files"] == capture_research_generation(source)["files"]
        po.PipelineOrchestrator._isolate_fork_handoff(loaded)
        assert loaded.handoff_dir == child.handoff_dir
    assert {p.name: p.read_bytes() for p in source.iterdir() if p.is_file()} == before


def test_research_retirement_removes_real_stage_manifest_rows_but_preserves_history(admission, tmp_path):
    state = po.PipelineState(pipeline_id="pipe_retire_context", prompt="Original task",
                             project_id="project_old", graph_id="graph_old",
                             simulation_id="sim_old_context", report_id="report_old_context")
    po.PipelineManager.ensure_dirs(state.pipeline_id)
    state.handoff_dir = po.PipelineManager.handoff_dir(state.pipeline_id)
    preserved = Path(state.handoff_dir) / "research_report.md"
    preserved.write_text("Original research remains available")
    state.artifacts["report"] = str(preserved)
    manifest = {"report": po._manifest_entry_for("report", str(preserved), po.STAGE_RESEARCH)}
    old = {}
    for name, stage, filename, body in (
        ("initial_posts", po.STAGE_PREPARE, "simulation_config.json", '{}'),
        ("personas", po.STAGE_PREPARE, "twitter_profiles.csv", 'name\nActor\n'),
        ("run_summary", po.STAGE_RUN, "run_summary.json", '{"simulation_id":"sim_old_context"}'),
    ):
        path = tmp_path / "historical_simulation" / filename
        path.parent.mkdir(exist_ok=True)
        path.write_text(body)
        old[path] = path.read_bytes()
        manifest[name] = po._manifest_entry_for(name, str(path), stage)
        assert manifest[name]["produced_by_stage"] == stage
        state.artifacts[name] = str(path)
    po.PipelineManager.write_artifact_manifest(state.pipeline_id, manifest)
    po.PipelineManager.save(state)
    po.PipelineOrchestrator._retire_research_derivatives(state)
    remaining = po.PipelineManager.load_artifact_manifest(state.pipeline_id)
    assert not ({"initial_posts", "personas", "run_summary"} & remaining.keys())
    assert not ({"initial_posts", "personas", "run_summary"} & state.artifacts.keys())
    assert remaining["report"] == manifest["report"] and preserved.read_text() == "Original research remains available"
    assert all(path.read_bytes() == before for path, before in old.items())
    assert state.simulation_id is None and state.report_id is None and state.project_id is None
