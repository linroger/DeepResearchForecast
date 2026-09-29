"""INFRA-7: run-shape pin, drift detection and resume lineage guards.

Offline: every stage service is faked; no LLM, graph or simulation is touched.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from app.config import Config
from app.services import pipeline_orchestrator as po
from app.services import run_shape
from app.utils import telemetry
from app.utils.security import redact_secrets

REPORT = "# Research\n\n" + ("Capacity reached 176 GW in 2023 [S1]. " * 20) + "\n"


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """Point every artifact root the orchestrator resolves at tmp_path."""
    sims = str(tmp_path / "simulations")
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"), raising=False)
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"), raising=False)
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", sims, raising=False)
    monkeypatch.setattr(po.SimulationRunner, "RUN_STATE_DIR", sims, raising=False)
    monkeypatch.setattr(po.ReportManager, "REPORTS_DIR", str(tmp_path / "reports"),
                        raising=False)
    monkeypatch.setattr(po, "_repo_git_sha", lambda: "gitsha")
    monkeypatch.setattr(po, "_deerflow_ref", lambda: None)
    for name, value in {
        "RESEARCH_ENGINE": "v3",
        "RESEARCH_PARALLEL_TRACKS": 1,
        "DEERFLOW_RESEARCH_LANGUAGE": None,
        "REPORT_LINT": False,
        "CAST_RECONCILE": False,
        "EMBED_WARM_AT_RESEARCH": False,
        "PIPELINE_VIZ_ARTIFACTS": False,
        "STAGE_SCORECARD_ENABLED": False,
        "RUN_SHAPE_PIN": True,
        "RUN_SHAPE_DRIFT_POLICY": "record",
        "RESUME_LINEAGE_GUARDS": True,
        "GRAPH_MAX_ENTITIES": 400,
        "LLM_PROVIDER": "provider-a",
        "LLM_MODEL_NAME": "model-a",
    }.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    return tmp_path


def _flags_off(monkeypatch):
    for name in ("RUN_SHAPE_PIN", "RESUME_LINEAGE_GUARDS"):
        monkeypatch.setattr(Config, name, False, raising=False)


def _config(**attrs):
    return SimpleNamespace(**attrs)


# ------------------------------------------------------------- pure module


def test_capture_is_deterministic_and_hashes_identity_only():
    cfg = _config(ACTOR_CAST_MAX=20, GRAPH_MAX_ENTITIES=400, LLM_PROVIDER="a",
                  RESEARCH_ENGINE="V3", DEERFLOW_MODEL="claude")
    options = {"depth": "standard", "max_rounds": None, "research_language": "English"}
    first = run_shape.capture(cfg, options)
    second = run_shape.capture(cfg, dict(options))
    assert first == second
    assert first["version"] == run_shape.RUN_SHAPE_VERSION
    assert first["sha256"] == run_shape.canonical_json_sha256(first["identity"])
    assert first["identity"]["depth"] == "standard"
    assert first["provenance"]["research_model"] == "claude"
    assert first["provenance"]["research_engine"] == "v3"
    # A provenance change leaves the shape fingerprint alone; identity changes it.
    provider_switched = run_shape.capture(
        _config(**{**vars(cfg), "LLM_PROVIDER": "b"}), options)
    assert provider_switched["sha256"] == first["sha256"]
    capped = run_shape.capture(_config(**{**vars(cfg), "GRAPH_MAX_ENTITIES": 200}), options)
    assert capped["sha256"] != first["sha256"]
    explicit = run_shape.capture(cfg, {**options, "research_model": "gpt"},
                                 research_engine="legacy")
    assert explicit["provenance"]["research_model"] == "gpt"
    assert explicit["provenance"]["research_engine"] == "legacy"


def test_capture_tolerates_missing_config_attrs():
    shape = run_shape.capture(object(), None)
    assert set(shape["identity"]) == set(run_shape.IDENTITY_KNOBS) | set(
        run_shape.IDENTITY_OPTIONS)
    assert all(value is None for value in shape["identity"].values())
    assert shape["provenance"]["research_engine"] is None
    odd = run_shape.capture(_config(FORECAST_PROB_FLOOR=float("nan"),
                                    ONTOLOGY_TEMPLATE=("a", "b")), {})
    assert odd["identity"]["FORECAST_PROB_FLOOR"] == "nan"
    assert odd["identity"]["ONTOLOGY_TEMPLATE"] == "('a', 'b')"


def test_identity_knobs_exist_on_config_and_skip_the_safety_pin():
    assert all(hasattr(Config, name) for name in run_shape.IDENTITY_KNOBS)
    assert all(hasattr(Config, name) for name in run_shape.PROVENANCE_KNOBS)
    safety_keys = set(po.capture_safety_policy_v1("admission"))
    assert not {name.lower() for name in run_shape.IDENTITY_KNOBS} & safety_keys


def test_diff_separates_identity_and_provenance():
    base = _config(GRAPH_MAX_ENTITIES=400, ACTOR_CAST_MAX=20, LLM_PROVIDER="a")
    pinned = run_shape.capture(base, {"depth": "standard"})
    current = run_shape.capture(
        _config(GRAPH_MAX_ENTITIES=200, ACTOR_CAST_MAX=20, LLM_PROVIDER="b"),
        {"depth": "standard"})
    drift = run_shape.diff(pinned, current)
    assert drift == {"identity": {"GRAPH_MAX_ENTITIES": [400, 200]},
                     "provenance": {"LLM_PROVIDER": ["a", "b"]}}
    assert run_shape.has_drift(drift)
    assert run_shape.drifted_knobs(drift) == ["GRAPH_MAX_ENTITIES", "LLM_PROVIDER"]
    same = run_shape.diff(pinned, run_shape.capture(base, {"depth": "standard"}))
    assert same == {"identity": {}, "provenance": {}} and not run_shape.has_drift(same)
    # A key the pin never had is not drift; malformed pins diff to nothing.
    legacy_pin = {"identity": {"GRAPH_MAX_ENTITIES": 200}, "provenance": {}}
    assert run_shape.diff(legacy_pin, current)["identity"] == {}
    assert run_shape.diff(None, current) == {"identity": {}, "provenance": {}}


def test_drift_policy_resolution_and_refusal():
    assert run_shape.resolve_drift_policy("refuse") == ("refuse", True)
    assert run_shape.resolve_drift_policy(" RECORD ") == ("record", True)
    assert run_shape.resolve_drift_policy("block") == ("record", False)
    assert run_shape.resolve_drift_policy(None) == ("record", False)
    identity = {"identity": {"GRAPH_MAX_ENTITIES": [400, 200]}, "provenance": {}}
    provenance = {"identity": {}, "provenance": {"LLM_PROVIDER": ["a", "b"]}}
    assert run_shape.refuses("refuse", identity)
    assert not run_shape.refuses("refuse", provenance)
    assert not run_shape.refuses("record", identity)
    message = run_shape.refusal_message(identity)
    assert "GRAPH_MAX_ENTITIES" in message and "400" in message and "200" in message


def test_lineage_refusal_rules():
    assert run_shape.lineage_refusal("ontology", {"research"}) == "research_recomputed"
    assert run_shape.lineage_refusal("ontology", set()) is None
    assert run_shape.lineage_refusal("graph", {"ontology"}) == "ontology_recomputed"
    assert run_shape.lineage_refusal(
        "graph", {"ontology"}, exempt=("ontology",)) is None
    assert run_shape.lineage_refusal(
        "graph", {"research", "ontology"}, exempt=("ontology",)) == "research_recomputed"
    assert run_shape.lineage_refusal(
        "prepare", set(), bound_ids=("g1", "g2")) == "graph_id_mismatch"
    assert run_shape.lineage_refusal(
        "prepare", set(), bound_ids=(None, "g1")) == "graph_id_mismatch"
    assert run_shape.lineage_refusal("prepare", {"graph"}, bound_ids=("g", "g")) == (
        "graph_recomputed")
    assert run_shape.lineage_refusal(
        "report", set(), bound_ids=("s1", "s2")) == "simulation_id_mismatch"
    assert run_shape.lineage_refusal("report", {"run"}, bound_ids=("s", "s")) == (
        "run_recomputed")
    assert run_shape.lineage_refusal("report", {"prepare"}, bound_ids=("s", "s")) is None
    assert run_shape.graph_lineage_exempt({run_shape.SHARED_GRAPH_OPTION: "pipe_x"}) == (
        "ontology",)
    assert run_shape.graph_lineage_exempt({}) == ()


def test_resolved_carry_forward_and_restamp():
    fresh = {"research": {"model": "new"}, "ontology": {"provider": None},
             "graph": {"provider": None}, "report": {"provider": None},
             "simulation": {"max_agents": 80, "total_rounds": None}}
    prior = {"research": {"model": "old"}, "ontology": {"provider": "a"},
             "simulation": {"max_agents": 60, "total_rounds": 12, "n_rounds": 12}}
    resolved = run_shape.carry_forward_resolved(prior, fresh)
    assert resolved["ontology"] == {"provider": "a"}
    assert resolved["research"] == {"model": "old"}
    assert resolved["graph"] == {"provider": None}
    assert resolved["simulation"]["total_rounds"] == 12
    assert fresh["research"] == {"model": "new"}  # fresh stays untouched
    pair = {"provider": "b", "model_name": "m"}
    assert run_shape.stamp_resolved_stage(resolved, "ontology", fresh=fresh, provider=pair)
    assert resolved["ontology"] == pair
    run_shape.stamp_resolved_stage(resolved, "research", fresh=fresh, provider=pair)
    assert resolved["research"] == {"model": "new"}
    run_shape.stamp_resolved_stage(resolved, "run", fresh=fresh, provider=pair)
    assert resolved["simulation"] == {"max_agents": 80, "total_rounds": 12, "n_rounds": 12}
    assert not run_shape.stamp_resolved_stage(resolved, "prepare", fresh=fresh, provider=pair)
    assert run_shape.carry_forward_resolved(None, fresh) == fresh


def test_attempt_record_survives_manifest_redaction():
    drift = {"identity": {"GRAPH_MAX_ENTITIES": [400, 200]}, "provenance": {}}
    record = run_shape.attempt_record("t0", {"sha256": "abc"}, drift)
    assert redact_secrets(record) == {
        "started_at": "t0", "run_shape_sha256": "abc", "drift_knobs": ["GRAPH_MAX_ENTITIES"]}
    assert run_shape.append_capped(list(range(5)), 5, 3) == [3, 4, 5]
    assert run_shape.append_capped("junk", 1, 3) == [1]


# ---------------------------------------------------------- admission pins


def _noop_run(monkeypatch):
    monkeypatch.setattr(po.PipelineOrchestrator, "_run", classmethod(lambda cls, state: None))


def _join(pipeline_id):
    thread = po.PipelineOrchestrator._threads.pop(pipeline_id, None)
    if thread is not None:
        thread.join(timeout=10)
        assert not thread.is_alive()
    po.PipelineOrchestrator._cancel_events.pop(pipeline_id, None)


def test_start_pins_run_shape_at_admission(roots, monkeypatch):
    _noop_run(monkeypatch)
    state = po.PipelineOrchestrator.start("Will X happen by 2030?", mode="full",
                                          depth="deep", max_rounds=12, language="English")
    _join(state.pipeline_id)
    pin = po.PipelineManager.load(state.pipeline_id)["options"]["run_shape_v1"]
    assert pin["origin"] == run_shape.ORIGIN_ADMISSION and pin["pinned_at"]
    assert pin["identity"]["GRAPH_MAX_ENTITIES"] == 400
    assert pin["identity"]["depth"] == "deep" and pin["identity"]["max_rounds"] == 12
    assert pin["provenance"]["LLM_PROVIDER"] == "provider-a"
    assert pin["provenance"]["research_engine"] == "v3"
    assert pin["sha256"] == run_shape.canonical_json_sha256(pin["identity"])


def test_flags_off_start_and_fork_record_nothing(roots, monkeypatch):
    _flags_off(monkeypatch)
    _noop_run(monkeypatch)
    state = po.PipelineOrchestrator.start("Will X happen by 2030?", mode="full")
    _join(state.pipeline_id)
    assert "run_shape_v1" not in po.PipelineManager.load(state.pipeline_id)["options"]
    base = po.PipelineState(pipeline_id="pipe_rs_base_off", prompt="q", mode="full",
                            status="completed", graph_id="graph")
    po.PipelineManager.ensure_dirs(base.pipeline_id)
    po.PipelineManager.save(base)
    fork = po.PipelineOrchestrator.fork(base.pipeline_id, {"label": "what-if"})
    _join(fork.pipeline_id)
    assert "run_shape_v1" not in po.PipelineManager.load(fork.pipeline_id)["options"]


def _save_failed(pipeline_id, options=None, **fields):
    state = po.PipelineState(pipeline_id=pipeline_id, prompt="q", mode="research_only",
                             status="failed", options=dict(options or {}), **fields)
    po.PipelineManager.ensure_dirs(pipeline_id)
    po.PipelineManager.save(state)
    return state


def test_resume_of_legacy_run_pins_resume_unpinned(roots, monkeypatch):
    _noop_run(monkeypatch)
    _save_failed("pipe_rs_legacy")
    po.PipelineOrchestrator.resume("pipe_rs_legacy")
    _join("pipe_rs_legacy")
    pin = po.PipelineManager.load("pipe_rs_legacy")["options"]["run_shape_v1"]
    assert pin["origin"] == run_shape.ORIGIN_RESUME_UNPINNED
    # An existing pin is never replaced on resume.
    po.PipelineManager.mark_failed("pipe_rs_legacy", "boom")
    monkeypatch.setattr(Config, "GRAPH_MAX_ENTITIES", 123, raising=False)
    po.PipelineOrchestrator.resume("pipe_rs_legacy")
    _join("pipe_rs_legacy")
    assert po.PipelineManager.load("pipe_rs_legacy")["options"]["run_shape_v1"] == pin


def test_continue_to_full_of_legacy_run_pins_resume_unpinned(roots, monkeypatch):
    _noop_run(monkeypatch)
    state = _save_failed("pipe_rs_continue")
    state.status = "completed"
    with open(os.path.join(state.handoff_dir or po.PipelineManager.handoff_dir(
            state.pipeline_id), "research_report.md"), "w", encoding="utf-8") as fh:
        fh.write(REPORT)
    po.PipelineManager.save(state)
    po.PipelineOrchestrator.continue_to_full("pipe_rs_continue")
    _join("pipe_rs_continue")
    pin = po.PipelineManager.load("pipe_rs_continue")["options"]["run_shape_v1"]
    assert pin["origin"] == run_shape.ORIGIN_RESUME_UNPINNED


def test_scenario_fork_pins_origin_fork(roots, monkeypatch):
    _noop_run(monkeypatch)
    base = po.PipelineState(pipeline_id="pipe_rs_base", prompt="q", mode="full",
                            status="completed", graph_id="graph", project_id="proj")
    po.PipelineManager.ensure_dirs(base.pipeline_id)
    po.PipelineManager.save(base)
    fork = po.PipelineOrchestrator.fork(base.pipeline_id, {"label": "what-if", "max_rounds": 9})
    _join(fork.pipeline_id)
    pin = po.PipelineManager.load(fork.pipeline_id)["options"]["run_shape_v1"]
    assert pin["origin"] == run_shape.ORIGIN_FORK
    assert pin["identity"]["max_rounds"] == 9


@pytest.mark.parametrize("flags_on", [True, False])
def test_batch_question_fork_pins_fork_and_declares_shared_graph(roots, monkeypatch, flags_on):
    from scripts import batch_runs

    if not flags_on:
        _flags_off(monkeypatch)
    _noop_run(monkeypatch)
    base = po.PipelineState(pipeline_id="pipe_rs_anchor", prompt="anchor", mode="full",
                            status="completed", graph_id="graph", simulation_id="sim")
    po.PipelineManager.ensure_dirs(base.pipeline_id)
    po.PipelineManager.save(base)
    child = batch_runs.fork_question(base.pipeline_id, "Question two?", batch_id="batch_1")
    _join(child.pipeline_id)
    options = po.PipelineManager.load(child.pipeline_id)["options"]
    if flags_on:
        assert options["run_shape_v1"]["origin"] == run_shape.ORIGIN_FORK
        assert options[run_shape.SHARED_GRAPH_OPTION] == base.pipeline_id
    else:
        assert "run_shape_v1" not in options
        assert run_shape.SHARED_GRAPH_OPTION not in options


# ---------------------------------------------------------------- drift


def _real_run_research_only(monkeypatch, calls):
    """Stub the research child and the observability side paths of ``_run``."""
    for name, replacement in {
        "_start_heartbeat": lambda self, state: None,
        "_init_telemetry_flush": lambda self, state: None,
        "_record_research_telemetry": lambda self, state, value: None,
        "_maybe_warm_embedder": lambda self, state, actors: None,
        "_surface_research_quality": lambda self, state, handoff_dir: {},
        "_surface_forecast_confidence_penalty": lambda self, state, handoff_dir: None,
        "_flush_run_telemetry": lambda self, state, **kwargs: None,
    }.items():
        monkeypatch.setattr(po.PipelineOrchestrator, name, replacement)
    monkeypatch.setattr(po, "_finalize_research_contract", lambda handoff_dir, research: None)

    def fake_research(prompt, handoff_dir, **kwargs):
        calls.append(prompt)
        path = os.path.join(handoff_dir, "research_report.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(REPORT)
        return {"report": REPORT, "report_path": path, "evidence_pack": None,
                "actor_dossier": "", "actors": None, "sources": None, "timeline": None,
                "exit_code": 0, "research_telemetry": {}}

    monkeypatch.setattr(po.DeerFlowResearchRunner, "run", staticmethod(fake_research))


def _admit_then_resume(monkeypatch, *, change, policy="record"):
    """start() pins the admission shape; the environment changes; resume() runs _run."""
    real_run = po.PipelineOrchestrator.__dict__["_run"]
    _noop_run(monkeypatch)
    state = po.PipelineOrchestrator.start("Will capacity exceed 250 GW?", mode="research_only")
    _join(state.pipeline_id)
    po.PipelineManager.mark_failed(state.pipeline_id, "provider outage")
    for name, value in change.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    monkeypatch.setattr(Config, "RUN_SHAPE_DRIFT_POLICY", policy, raising=False)
    calls: list[str] = []
    _real_run_research_only(monkeypatch, calls)
    monkeypatch.setattr(po.PipelineOrchestrator, "_run", real_run)
    po.PipelineOrchestrator.resume(state.pipeline_id)
    _join(state.pipeline_id)
    return po.PipelineManager.load(state.pipeline_id), calls


def test_resume_records_identity_drift_and_continues(roots, monkeypatch):
    persisted, calls = _admit_then_resume(monkeypatch, change={"GRAPH_MAX_ENTITIES": 123})
    assert persisted["status"] == "completed", persisted.get("error")
    assert calls, "record policy continues the attempt"
    drift = persisted["options"]["run_shape_drift"]
    assert drift["identity"] == {"GRAPH_MAX_ENTITIES": [400, 123]}
    history = persisted["options"]["run_shape_drift_history"]
    assert len(history) == 1 and history[0]["policy"] == "record"
    manifest = json.loads(open(po.PipelineManager.manifest_path(persisted["pipeline_id"]),
                               encoding="utf-8").read())
    assert manifest["attempts"][-1]["drift_knobs"] == ["GRAPH_MAX_ENTITIES"]
    assert manifest["run_shape"]["pin"]["origin"] == run_shape.ORIGIN_ADMISSION
    assert manifest["run_shape"]["drift"]["identity"] == {"GRAPH_MAX_ENTITIES": [400, 123]}


def test_refuse_policy_fails_the_attempt_naming_the_knob(roots, monkeypatch):
    persisted, calls = _admit_then_resume(
        monkeypatch, change={"GRAPH_MAX_ENTITIES": 123}, policy="refuse")
    assert persisted["status"] == "failed"
    assert "GRAPH_MAX_ENTITIES" in persisted["error"]
    assert "RUN_SHAPE_DRIFT_POLICY=refuse" in persisted["error"]
    assert calls == [], "the refusal is the first statement of the attempt"
    assert persisted["options"]["run_shape_drift"]["identity"] == {
        "GRAPH_MAX_ENTITIES": [400, 123]}


def test_provenance_only_drift_never_refuses(roots, monkeypatch):
    persisted, calls = _admit_then_resume(
        monkeypatch, change={"LLM_PROVIDER": "provider-b"}, policy="refuse")
    assert persisted["status"] == "completed", persisted.get("error")
    assert calls
    assert persisted["options"]["run_shape_drift"] == {
        "identity": {}, "provenance": {"LLM_PROVIDER": ["provider-a", "provider-b"]}}


def test_unknown_policy_acts_as_record(roots, monkeypatch):
    persisted, _calls = _admit_then_resume(
        monkeypatch, change={"GRAPH_MAX_ENTITIES": 123}, policy="block")
    assert persisted["status"] == "completed", persisted.get("error")
    assert persisted["options"]["run_shape_drift_history"][0]["policy"] == "record"


def test_no_drift_records_nothing(roots, monkeypatch):
    persisted, _calls = _admit_then_resume(monkeypatch, change={})
    assert persisted["status"] == "completed", persisted.get("error")
    assert "run_shape_drift" not in persisted["options"]
    assert "run_shape_drift_history" not in persisted["options"]


def test_flags_off_drift_is_not_checked(roots, monkeypatch):
    real_run = po.PipelineOrchestrator.__dict__["_run"]
    _noop_run(monkeypatch)
    state = po.PipelineOrchestrator.start("q?", mode="research_only")
    _join(state.pipeline_id)
    po.PipelineManager.mark_failed(state.pipeline_id, "boom")
    _flags_off(monkeypatch)
    monkeypatch.setattr(Config, "GRAPH_MAX_ENTITIES", 123, raising=False)
    monkeypatch.setattr(Config, "RUN_SHAPE_DRIFT_POLICY", "refuse", raising=False)
    _real_run_research_only(monkeypatch, [])
    monkeypatch.setattr(po.PipelineOrchestrator, "_run", real_run)
    po.PipelineOrchestrator.resume(state.pipeline_id)
    _join(state.pipeline_id)
    persisted = po.PipelineManager.load(state.pipeline_id)
    assert persisted["status"] == "completed"
    assert "run_shape_drift" not in persisted["options"]
    assert "stage_reuse_v1" not in persisted["options"]


# ------------------------------------------------------------ lineage guards


class _Sentinel(RuntimeError):
    pass


def _drive_full(monkeypatch, pid, *, research_reused, sim_graph_id="graph"):
    """Run the real ``_run`` over a resumed full pipeline whose every stage completed.

    Fakes stop the attempt with a named sentinel at the first expensive call:
    GRAPH_REBUILT (graph rebuild), PREPARE_REBUILT (new simulation) or
    PREPARE_REUSED (PREPARE reuse handed over to the RUN checks).
    """
    calls: list[str] = []
    _real_run_research_only(monkeypatch, calls)
    for name, replacement in {
        "_write_run_manifest": lambda self, state: None,
        "_update_manifest": lambda self, state, stage, **kwargs: None,
    }.items():
        monkeypatch.setattr(po.PipelineOrchestrator, name, replacement)
    project = SimpleNamespace(
        project_id="proj", name="EV", graph_id="graph", files=[], analysis_summary="",
        status=None, ontology={"entity_types": [{"name": "Company"}], "edge_types": []})
    monkeypatch.setattr(po.ProjectManager, "get_project", classmethod(lambda cls, pid: project))
    monkeypatch.setattr(po.ProjectManager, "save_project", classmethod(lambda cls, p: None))
    ontology_calls: list[dict] = []

    class FakeOntologyGenerator:
        def generate(self, **kwargs):
            ontology_calls.append(kwargs)
            return {"entity_types": [{"name": "Agency"}], "edge_types": [],
                    "analysis_summary": "regenerated"}

    monkeypatch.setattr(po, "OntologyGenerator", FakeOntologyGenerator)

    class FakeGraphBuilder:
        def __init__(self, **kwargs):
            pass

        def set_ontology(self, graph_id, ontology):
            return None

        def create_graph(self, name):
            raise _Sentinel("GRAPH_REBUILT")

    monkeypatch.setattr(po, "GraphBuilderService", FakeGraphBuilder)
    import app.services.zep_entity_reader as zep_reader

    monkeypatch.setattr(zep_reader, "ZepEntityReader", lambda: SimpleNamespace(
        filter_defined_entities=lambda graph_id, enrich_with_edges=False: SimpleNamespace(
            entities=[{"uuid": "one"}])))

    class FakeSimulationManager:
        def get_simulation(self, simulation_id):
            return SimpleNamespace(simulation_id=simulation_id, graph_id=sim_graph_id)

        def create_simulation(self, *args, **kwargs):
            raise _Sentinel("PREPARE_REBUILT")

        def validate_prepared_simulation_config(self, simulation_id):
            return None

    monkeypatch.setattr(po, "SimulationManager", FakeSimulationManager)

    def prepare_reused(state, sim_state):
        raise _Sentinel("PREPARE_REUSED")

    monkeypatch.setattr(po.PipelineOrchestrator, "_run_reuse_ready",
                        staticmethod(prepare_reused))

    po.PipelineManager.ensure_dirs(pid)
    state = po.PipelineState(pipeline_id=pid, prompt="Forecast EV adoption", mode="full",
                             status="running", project_id="proj", graph_id="graph",
                             simulation_id="sim_old", report_id="report_old")
    state.handoff_dir = po.PipelineManager.handoff_dir(pid)
    state.stages = {name: po.StageState(name=name, status="completed", progress=100)
                    for name in po.STAGE_BANDS}
    if research_reused:
        with open(os.path.join(state.handoff_dir, "research_report.md"), "w",
                  encoding="utf-8") as fh:
            fh.write(REPORT)
    po.PipelineManager.save(state)
    po.PipelineOrchestrator._run(state)
    return state, calls, ontology_calls


def test_research_recompute_refuses_ontology_and_graph_reuse(roots, monkeypatch):
    state, calls, ontology_calls = _drive_full(
        monkeypatch, "pipe_rs_lineage_research", research_reused=False)
    assert calls, "research was recomputed this attempt"
    assert state.status == "failed" and state.error == "GRAPH_REBUILT"
    assert len(ontology_calls) == 1, "ontology regenerated from the new research"
    notes = state.options["stage_notes"]
    assert notes[po.STAGE_ONTOLOGY] == ["reuse_refused: research_recomputed"]
    assert notes[po.STAGE_GRAPH] == ["reuse_refused: research_recomputed"]
    decisions = [(row["stage"], row["reused"]) for row in state.options["stage_reuse_v1"]]
    assert decisions == [(po.STAGE_RESEARCH, False), (po.STAGE_ONTOLOGY, False)]
    persisted = po.PipelineManager.load(state.pipeline_id)
    assert persisted["options"]["stage_notes"] == notes


def test_flags_off_research_recompute_keeps_legacy_reuse(roots, monkeypatch):
    _flags_off(monkeypatch)
    state, calls, ontology_calls = _drive_full(
        monkeypatch, "pipe_rs_lineage_legacy", research_reused=False)
    assert calls
    assert state.error == "PREPARE_REUSED", "legacy reuses ontology, graph and PREPARE"
    assert ontology_calls == []
    assert "stage_notes" not in state.options
    assert "stage_reuse_v1" not in state.options


def test_prepare_reuse_refused_when_simulation_graph_differs(roots, monkeypatch):
    state, calls, ontology_calls = _drive_full(
        monkeypatch, "pipe_rs_lineage_prepare", research_reused=True,
        sim_graph_id="graph_other")
    assert calls == [] and ontology_calls == []
    assert state.error == "PREPARE_REBUILT"
    assert state.options["stage_notes"] == {
        po.STAGE_PREPARE: ["reuse_refused: graph_id_mismatch"]}
    decisions = [(row["stage"], row["reused"]) for row in state.options["stage_reuse_v1"]]
    assert decisions == [(po.STAGE_RESEARCH, True), (po.STAGE_ONTOLOGY, True),
                         (po.STAGE_GRAPH, True)]


def test_prepare_reuse_kept_when_simulation_graph_matches(roots, monkeypatch):
    state, _calls, _ontology_calls = _drive_full(
        monkeypatch, "pipe_rs_lineage_prepare_ok", research_reused=True)
    assert state.error == "PREPARE_REUSED"
    assert "stage_notes" not in state.options


def test_prepare_graph_mismatch_ignored_with_guards_off(roots, monkeypatch):
    monkeypatch.setattr(Config, "RESUME_LINEAGE_GUARDS", False, raising=False)
    state, _calls, _ontology_calls = _drive_full(
        monkeypatch, "pipe_rs_lineage_prepare_off", research_reused=True,
        sim_graph_id="graph_other")
    assert state.error == "PREPARE_REUSED"
    assert "stage_notes" not in state.options


def test_graph_guard_honours_the_batch_shared_graph_declaration(monkeypatch):
    orch = po.PipelineOrchestrator()
    orch._attempt_recomputed().add(po.STAGE_ONTOLOGY)
    shared = po.PipelineState(pipeline_id="pipe_rs_batch", prompt="q",
                              options={run_shape.SHARED_GRAPH_OPTION: "pipe_anchor"})
    assert not orch._lineage_refuses_reuse(
        shared, po.STAGE_GRAPH, exempt=run_shape.graph_lineage_exempt(shared.options))
    assert "stage_notes" not in shared.options
    plain = po.PipelineState(pipeline_id="pipe_rs_plain", prompt="q")
    assert orch._lineage_refuses_reuse(
        plain, po.STAGE_GRAPH, exempt=run_shape.graph_lineage_exempt(plain.options))
    assert plain.options["stage_notes"][po.STAGE_GRAPH] == ["reuse_refused: ontology_recomputed"]


@pytest.mark.parametrize("guards", [True, False])
def test_report_reuse_refused_when_report_simulation_differs(monkeypatch, tmp_path, guards):
    from tests.test_orchestrator_research_wiring import _exercise_prepare_run_resume

    monkeypatch.setattr(Config, "RESUME_LINEAGE_GUARDS", guards, raising=False)
    result = _exercise_prepare_run_resume(
        monkeypatch, tmp_path, rebuild_prepare=False, report_simulation_id="sim_other")
    assert result.state.status == "completed", result.state.error
    assert result.state.simulation_id == result.old_id
    if guards:
        assert result.report_generations == [result.old_id]
        assert result.state.report_id != "report_existing"
        assert result.state.options["stage_notes"] == {
            po.STAGE_REPORT: ["reuse_refused: simulation_id_mismatch"]}
    else:
        assert result.report_generations == []
        assert result.state.report_id == "report_existing"


def test_report_reuse_kept_after_run_recompute_only_with_guards_off(monkeypatch, tmp_path):
    """Legacy (guards off): a re-executed RUN still reuses the stale report."""
    from tests.test_orchestrator_research_wiring import _exercise_prepare_run_resume

    monkeypatch.setattr(Config, "RESUME_LINEAGE_GUARDS", False, raising=False)
    result = _exercise_prepare_run_resume(
        monkeypatch, tmp_path, rebuild_prepare=False, corrupt_run=True)
    assert result.state.status == "completed"
    assert result.start_calls == [result.old_id]
    assert result.report_generations == []
    assert result.state.report_id == "report_existing"


# ------------------------------------------------------------- run.json


def _complete_quietly(monkeypatch):
    monkeypatch.setattr(po.PipelineOrchestrator, "_record_stage_artifacts",
                        lambda self, state, stage: None)
    monkeypatch.setattr(po.PipelineOrchestrator, "_flush_run_telemetry",
                        lambda self, state, **kwargs: None)


def _manifest(pipeline_id):
    with open(po.PipelineManager.manifest_path(pipeline_id), encoding="utf-8") as fh:
        return json.load(fh)


def _two_attempts(monkeypatch, pid):
    """Attempt 1 computes ontology+graph under provider A; attempt 2 (provider B)
    reuses ontology and recomputes graph."""
    _complete_quietly(monkeypatch)
    state = po.PipelineState(pipeline_id=pid, prompt="q", mode="full", status="running")
    po.PipelineManager.ensure_dirs(pid)
    first = po.PipelineOrchestrator()
    first._write_run_manifest(state)
    for stage in (po.STAGE_ONTOLOGY, po.STAGE_GRAPH):
        first._update_manifest(state, stage)
        first._complete_stage(state, stage)
    monkeypatch.setattr(Config, "LLM_PROVIDER", "provider-b", raising=False)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "model-b", raising=False)
    second = po.PipelineOrchestrator()
    second._write_run_manifest(state)
    second._update_manifest(state, po.STAGE_ONTOLOGY)
    second._complete_stage(state, po.STAGE_ONTOLOGY, reused=True)
    second._update_manifest(state, po.STAGE_GRAPH)
    second._complete_stage(state, po.STAGE_GRAPH)
    return state, _manifest(pid), second


def test_run_manifest_keeps_attempts_and_reused_stage_stamps(roots, monkeypatch):
    state, manifest, second = _two_attempts(monkeypatch, "pipe_rs_manifest")
    assert len(manifest["attempts"]) == 2
    assert all(row["drift_knobs"] == [] for row in manifest["attempts"])
    resolved = manifest["resolved"]
    assert resolved["ontology"] == {"provider": "provider-a", "model_name": "model-a"}
    assert resolved["graph"] == {"provider": "provider-b", "model_name": "model-b"}
    assert "run_shape" in manifest
    records = state.options["stage_reuse_v1"]
    assert [(r["stage"], r["reused"]) for r in records] == [
        (po.STAGE_ONTOLOGY, False), (po.STAGE_GRAPH, False),
        (po.STAGE_ONTOLOGY, True), (po.STAGE_GRAPH, False)]
    assert [(r["stage"], r["reused"]) for r in second._stage_reuse_this_attempt] == [
        (po.STAGE_ONTOLOGY, True), (po.STAGE_GRAPH, False)]


def test_run_manifest_attempts_are_capped(roots, monkeypatch):
    _complete_quietly(monkeypatch)
    state = po.PipelineState(pipeline_id="pipe_rs_cap", prompt="q", mode="full")
    po.PipelineManager.ensure_dirs(state.pipeline_id)
    for _ in range(run_shape.ATTEMPTS_CAP + 3):
        po.PipelineOrchestrator()._write_run_manifest(state)
    assert len(_manifest(state.pipeline_id)["attempts"]) == run_shape.ATTEMPTS_CAP


def test_flags_off_run_manifest_is_legacy(roots, monkeypatch):
    _flags_off(monkeypatch)
    state, manifest, second = _two_attempts(monkeypatch, "pipe_rs_manifest_off")
    assert "attempts" not in manifest and "run_shape" not in manifest
    # Legacy: the stage-entry stamp rewrites the reused ontology's provenance.
    assert manifest["resolved"]["ontology"] == {
        "provider": "provider-b", "model_name": "model-b"}
    assert "stage_reuse_v1" not in state.options
    assert second._stage_reuse_this_attempt == []
    assert set(manifest) == set(po._build_run_manifest(state))


def test_recomputed_research_and_run_restamp_their_blocks(roots, monkeypatch):
    _complete_quietly(monkeypatch)
    state = po.PipelineState(pipeline_id="pipe_rs_blocks", prompt="q", mode="full",
                             options={"research_model": "model-x"})
    po.PipelineManager.ensure_dirs(state.pipeline_id)
    first = po.PipelineOrchestrator()
    first._write_run_manifest(state)
    first._update_manifest(state, po.STAGE_RUN, total_rounds=12)
    first._complete_stage(state, po.STAGE_RUN)
    state.options["research_model"] = "model-y"
    monkeypatch.setattr(Config, "OASIS_MAX_AGENTS", 7, raising=False)
    second = po.PipelineOrchestrator()
    second._write_run_manifest(state)
    kept = _manifest(state.pipeline_id)["resolved"]
    assert kept["research"]["model"] == "model-x"
    assert kept["simulation"]["total_rounds"] == 12
    second._complete_stage(state, po.STAGE_RESEARCH)
    second._complete_stage(state, po.STAGE_RUN)
    restamped = _manifest(state.pipeline_id)["resolved"]
    assert restamped["research"]["model"] == "model-y"
    assert restamped["simulation"]["max_agents"] == 7
    assert restamped["simulation"]["total_rounds"] == 12


def test_manifest_sim_graph_feedback_follows_the_safety_pin(roots, monkeypatch):
    monkeypatch.setattr(Config, "SIM_GRAPH_FEEDBACK", True, raising=False)
    pinned = po.PipelineState(pipeline_id="pipe_rs_fb", prompt="q",
                              options={"safety_policy_v1": {"sim_graph_feedback": False}})
    sim = po._build_run_manifest(pinned)["resolved"]["simulation"]
    assert sim["sim_graph_feedback"] is False
    unpinned = po.PipelineState(pipeline_id="pipe_rs_fb2", prompt="q")
    assert po._build_run_manifest(unpinned)["resolved"]["simulation"][
        "sim_graph_feedback"] is True
    monkeypatch.setattr(Config, "RUN_SHAPE_PIN", False, raising=False)
    assert po._build_run_manifest(pinned)["resolved"]["simulation"][
        "sim_graph_feedback"] is True


def test_missing_manifest_is_not_created_by_stage_stamp(roots, monkeypatch):
    _complete_quietly(monkeypatch)
    state = po.PipelineState(pipeline_id="pipe_rs_nomani", prompt="q")
    po.PipelineManager.ensure_dirs(state.pipeline_id)
    po.PipelineOrchestrator()._complete_stage(state, po.STAGE_GRAPH)
    assert not os.path.exists(po.PipelineManager.manifest_path(state.pipeline_id))
    assert state.options["stage_reuse_v1"][0]["stage"] == po.STAGE_GRAPH


def test_bare_orchestrator_complete_stage_degrades_safe(monkeypatch):
    """Instances built without __init__ and invalid ids never break a stage."""
    monkeypatch.setattr(po.PipelineManager, "save", classmethod(lambda cls, state: None))
    orch = po.PipelineOrchestrator.__new__(po.PipelineOrchestrator)
    orch._tel_path = None
    monkeypatch.setattr(orch, "_record_stage_artifacts", lambda *args: None)
    state = po.PipelineState(pipeline_id="not-a-pipeline-id", prompt="q")
    orch._complete_stage(state, po.STAGE_REPORT)
    assert state.stages[po.STAGE_REPORT].status == "completed"
    assert orch._attempt_recomputed() == {po.STAGE_REPORT}


# ------------------------------------------------------------- telemetry


def test_stage_telemetry_reused_flag(monkeypatch):
    monkeypatch.setattr(telemetry.LLMMeter, "snapshot", classmethod(
        lambda cls, run_id=None: {"by_stage": {"report": {"calls": 2}}}))
    walls = {"research": 5.0, "graph": 1.0, "report": 9.0}
    baseline = telemetry.build_stage_telemetry("pipe_x", walls)
    assert telemetry.build_stage_telemetry("pipe_x", walls, stage_decisions=None) == baseline
    decided = telemetry.build_stage_telemetry("pipe_x", walls, stage_decisions=[
        {"stage": "research", "reused": True},
        {"stage": "report", "reused": True},
        {"stage": "report", "reused": False},
        {"stage": "prepare", "reused": True},
        "junk",
    ])
    assert decided["by_stage"]["research"]["reused"] is True
    assert decided["by_stage"]["report"]["reused"] is False
    assert "reused" not in decided["by_stage"]["graph"]
    assert "prepare" not in decided["by_stage"]
    assert decided["total"] == baseline["total"]
    assert telemetry.render_telemetry_appendix(decided) == (
        telemetry.render_telemetry_appendix(baseline))
