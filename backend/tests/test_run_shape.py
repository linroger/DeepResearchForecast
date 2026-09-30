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
    # A stage made stale in an earlier attempt refuses with the stored reason;
    # evidence from this attempt is named first.
    stale = {"report": "run_recomputed", "ontology": "research_recomputed"}
    assert run_shape.lineage_refusal(
        "report", set(), bound_ids=("s", "s"), invalidated=stale) == "run_recomputed"
    assert run_shape.lineage_refusal("ontology", set(), invalidated=stale) == (
        "research_recomputed")
    assert run_shape.lineage_refusal(
        "report", set(), bound_ids=("s1", "s2"), invalidated=stale) == "simulation_id_mismatch"
    assert run_shape.lineage_refusal("graph", {"ontology"}, invalidated=stale) == (
        "ontology_recomputed")
    assert run_shape.lineage_refusal("graph", set(), invalidated=stale) is None
    assert run_shape.lineage_refusal("report", set(), bound_ids=("s", "s"),
                                     invalidated={"report": ""}) == "lineage_invalidated"
    # The artifact the stage's rebuild produced from current inputs is exempt
    # from the durable entry; any other (or an unnamed) artifact is not.
    rebuilt = {"report": "report_new"}
    assert run_shape.lineage_refusal(
        "report", set(), bound_ids=("s", "s"), invalidated=stale,
        artifact_id="report_new", rebuilt=rebuilt) is None
    assert run_shape.lineage_refusal(
        "report", set(), bound_ids=("s", "s"), invalidated=stale,
        artifact_id="report_old", rebuilt=rebuilt) == "run_recomputed"
    assert run_shape.lineage_refusal(
        "report", set(), bound_ids=("s", "s"), invalidated=stale,
        artifact_id=None, rebuilt=rebuilt) == "run_recomputed"
    # Evidence from this attempt and the bound id still refuse the rebuilt id.
    assert run_shape.lineage_refusal(
        "report", {"run"}, bound_ids=("s", "s"), invalidated=stale,
        artifact_id="report_new", rebuilt=rebuilt) == "run_recomputed"
    assert run_shape.lineage_refusal(
        "report", set(), bound_ids=("s1", "s2"), invalidated=stale,
        artifact_id="report_new", rebuilt=rebuilt) == "simulation_id_mismatch"


def test_durable_invalidation_walk():
    assert run_shape.downstream_stages("research") == [
        "ontology", "graph", "prepare", "run", "report"]
    assert run_shape.downstream_stages("graph") == ["prepare", "run", "report"]
    assert run_shape.downstream_stages("prepare") == ["run", "report"]
    assert run_shape.downstream_stages("report") == []
    batch = run_shape.lineage_exemptions({run_shape.SHARED_GRAPH_OPTION: "pipe_anchor"})
    assert batch == {"graph": ("ontology",)}
    assert run_shape.lineage_exemptions({}) == {}
    # The exempt GRAPH <- ONTOLOGY edge is not followed; RESEARCH -> GRAPH still is.
    assert run_shape.downstream_stages("ontology", exemptions=batch) == []
    assert run_shape.downstream_stages("research", exemptions=batch) == [
        "ontology", "graph", "prepare", "run", "report"]
    # Only guarded stages are recorded (RUN is bound to its simulation instead).
    marked = run_shape.invalidate_downstream(None, "research")
    assert marked == {"ontology": "research_recomputed", "graph": "research_recomputed",
                      "prepare": "research_recomputed", "report": "research_recomputed"}
    # Recomputing a stage clears only its own entry and keeps root-cause reasons.
    after_ontology = run_shape.invalidate_downstream(marked, "ontology")
    assert after_ontology == {"graph": "research_recomputed",
                              "prepare": "research_recomputed",
                              "report": "research_recomputed"}
    assert marked["ontology"] == "research_recomputed"  # input left untouched
    assert run_shape.invalidate_downstream(None, "run") == {"report": "run_recomputed"}
    assert run_shape.invalidate_downstream({"report": "run_recomputed"}, "report") == {}
    assert run_shape.invalidate_downstream("junk", "ontology", exemptions=batch) == {}


def test_rebuilt_artifact_bookkeeping():
    stale = {"report": "run_recomputed"}
    # A rebuild is recorded only for an invalidated stage and a real id; the
    # newest rebuild replaces an earlier one.
    assert run_shape.mark_rebuilt(stale, None, "report", "report_a") == {"report": "report_a"}
    assert run_shape.mark_rebuilt(stale, {"report": "report_a"}, "report", "report_b") == {
        "report": "report_b"}
    assert run_shape.mark_rebuilt({}, None, "report", "report_a") == {}
    assert run_shape.mark_rebuilt(stale, None, "report", "") == {}
    # An upstream recompute drops the rebuilt artifacts built from its old output.
    rebuilt = {"report": "report_a"}
    assert run_shape.settle_rebuilt(rebuilt, "run") == {}
    assert run_shape.settle_rebuilt(rebuilt, "research") == {}
    assert run_shape.settle_rebuilt(rebuilt, "report") == {}
    assert run_shape.settle_rebuilt(rebuilt, "ontology", exemptions={"graph": ("ontology",)}) == (
        rebuilt)
    assert rebuilt == {"report": "report_a"}  # input left untouched
    # Reusing the rebuilt artifact finishes the rebuild; other reuses change nothing.
    assert run_shape.settle_reused_rebuild(stale, rebuilt, "report") == ({}, {})
    both = {"report": "run_recomputed", "graph": "research_recomputed"}
    assert run_shape.settle_reused_rebuild(both, rebuilt, "run") == (both, rebuilt)
    assert run_shape.settle_reused_rebuild(both, None, "report") == (both, {})


def test_fork_base_record():
    config = _config(GRAPH_MAX_ENTITIES=400, ACTOR_CAST_MAX=40)
    base_pin = run_shape.pin(config, {"depth": "deep"}, origin="admission", pinned_at="t0")
    config.GRAPH_MAX_ENTITIES = 123
    fork_pin = run_shape.pin(config, {"depth": "deep", "max_rounds": 9}, origin="fork",
                             pinned_at="t1")
    assert run_shape.fork_base_record(base_pin, fork_pin, "pipe_base") == {
        "pipeline_id": "pipe_base",
        "sha256": base_pin["sha256"],
        "identity_diff": {"GRAPH_MAX_ENTITIES": [400, 123], "max_rounds": [None, 9]},
    }
    assert run_shape.fork_base_record(None, fork_pin, "pipe_legacy") == {
        "pipeline_id": "pipe_legacy", "sha256": None, "identity_diff": None}
    # A per-run option the fork does not carry (a scenario fork never copies the
    # base's depth/research_language) is not drift; a Config knob unset on the
    # fork side, or an option the fork sets differently, still is.
    config.GRAPH_MAX_ENTITIES = None
    uncarried = run_shape.pin(config, {"max_rounds": 9}, origin="fork", pinned_at="t2")
    assert run_shape.fork_base_record(base_pin, uncarried, "pipe_base")["identity_diff"] == {
        "GRAPH_MAX_ENTITIES": [400, None], "max_rounds": [None, 9]}
    changed = run_shape.pin(config, {"depth": "quick"}, origin="fork", pinned_at="t3")
    assert run_shape.fork_base_record(base_pin, changed, "pipe_base")["identity_diff"] == {
        "GRAPH_MAX_ENTITIES": [400, None], "depth": ["deep", "quick"]}


def test_report_producer_record_and_reuse_stamp():
    pair = {"provider": "provider-a", "model_name": "model-a"}
    record = run_shape.producer_record("report_x", pair)
    assert record == {"report_id": "report_x", **pair}
    # No pending mint: the carried-forward stamp already describes the report.
    assert run_shape.reused_report_stamp(None, "report_x") is None
    # Reusing the minted report stamps its recorded producer.
    assert run_shape.reused_report_stamp(record, "report_x") == pair
    # Any other report (the minted one never reached disk) has no known producer.
    unknown = {"provider": None, "model_name": None}
    assert run_shape.reused_report_stamp(record, "report_old") == unknown
    assert run_shape.reused_report_stamp(record, None) == unknown


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
    # A RUN restamp keeps only what this attempt's RUN wrote: the carried-forward
    # total_rounds/n_rounds belong to the replaced simulation.
    run_shape.stamp_resolved_stage(resolved, "run", fresh=fresh, provider=pair)
    assert resolved["simulation"] == {"max_agents": 80, "total_rounds": None}
    run_shape.stamp_resolved_stage(resolved, "run", fresh=fresh, provider=pair,
                                   sim_runtime={"total_rounds": 10, "n_rounds": None})
    assert resolved["simulation"] == {"max_agents": 80, "total_rounds": 10}
    assert fresh["simulation"] == {"max_agents": 80, "total_rounds": None}
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


def _admit_completed_base(**start_kwargs):
    """A base admitted through start() (depth/language pinned), then marked graph-complete."""
    base = po.PipelineOrchestrator.start("Will X happen by 2030?", mode="full", **start_kwargs)
    _join(base.pipeline_id)
    data = po.PipelineManager.load(base.pipeline_id)
    data.update(status="completed", graph_id="graph", project_id="proj")
    with open(po.PipelineManager.state_path(base.pipeline_id), "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return data


def test_scenario_fork_pins_origin_fork(roots, monkeypatch):
    _noop_run(monkeypatch)
    base = _admit_completed_base(depth="deep", language="English")
    assert base["options"]["run_shape_v1"]["identity"]["depth"] == "deep"
    # The environment changed since the base was admitted: the fork's own pin
    # captures the new value, and discloses that its reused upstream stages
    # were built under the base's.  depth/research_language are not carried by
    # a scenario fork (it reuses the research they shaped): not drift.
    monkeypatch.setattr(Config, "GRAPH_MAX_ENTITIES", 123, raising=False)
    fork = po.PipelineOrchestrator.fork(base["pipeline_id"],
                                        {"label": "what-if", "max_rounds": 9})
    _join(fork.pipeline_id)
    pin = po.PipelineManager.load(fork.pipeline_id)["options"]["run_shape_v1"]
    assert pin["origin"] == run_shape.ORIGIN_FORK
    assert pin["identity"]["max_rounds"] == 9
    assert pin["identity"]["GRAPH_MAX_ENTITIES"] == 123
    assert pin["fork_base"] == {
        "pipeline_id": base["pipeline_id"],
        "sha256": base["options"]["run_shape_v1"]["sha256"],
        "identity_diff": {"GRAPH_MAX_ENTITIES": [400, 123], "max_rounds": [None, 9]},
    }


def test_scenario_fork_without_any_change_reports_no_identity_diff(roots, monkeypatch):
    """Round-3 review: a real (start()-admitted) base used to diff depth/language."""
    _noop_run(monkeypatch)
    base = _admit_completed_base(depth="deep", language="English")
    fork = po.PipelineOrchestrator.fork(base["pipeline_id"], {"label": "what-if"})
    _join(fork.pipeline_id)
    pin = po.PipelineManager.load(fork.pipeline_id)["options"]["run_shape_v1"]
    assert pin["fork_base"]["identity_diff"] == {}
    assert pin["fork_base"]["sha256"] == base["options"]["run_shape_v1"]["sha256"]


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
        # The anchor predates the pin: nothing to compare the fork's shape with.
        assert options["run_shape_v1"]["fork_base"] == {
            "pipeline_id": base.pipeline_id, "sha256": None, "identity_diff": None}
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


def _drive_full(monkeypatch, pid, *, research_reused, sim_graph_id="graph",
                ontology_failures=0, ontology_completion_crashes=0, options=None,
                handoff_dir=None, real_run_manifest=False):
    """Run the real ``_run`` over a resumed full pipeline whose every stage completed.

    Fakes stop the attempt with a named sentinel at the first expensive call:
    GRAPH_REBUILT (graph rebuild), PREPARE_REBUILT (new simulation) or
    PREPARE_REUSED (PREPARE reuse handed over to the RUN checks).  The first
    ``ontology_failures`` ontology generations raise (a provider outage); the
    first ``ontology_completion_crashes`` completions of a regenerated
    ontology crash after it was saved (a restart before ``_complete_stage``).
    ``handoff_dir`` overrides the pipeline's own handoff directory;
    ``real_run_manifest`` keeps the real run.json writers.  The fakes stay
    installed, so ``resume(pid)`` runs a second attempt on them.
    """
    calls: list[str] = []
    _real_run_research_only(monkeypatch, calls)
    if not real_run_manifest:
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
            if len(ontology_calls) <= ontology_failures:
                raise RuntimeError("ontology provider outage")
            return {"entity_types": [{"name": "Agency"}], "edge_types": [],
                    "analysis_summary": "regenerated"}

    monkeypatch.setattr(po, "OntologyGenerator", FakeOntologyGenerator)
    real_complete_stage = po.PipelineOrchestrator._complete_stage
    completion_crashes = {"left": ontology_completion_crashes}

    def complete_stage(self, state, stage, message="完成", *, reused=False):
        if stage == po.STAGE_ONTOLOGY and not reused and completion_crashes["left"] > 0:
            completion_crashes["left"] -= 1
            raise _Sentinel("ONTOLOGY_COMPLETION_CRASHED")
        return real_complete_stage(self, state, stage, message, reused=reused)

    monkeypatch.setattr(po.PipelineOrchestrator, "_complete_stage", complete_stage)

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
                             simulation_id="sim_old", report_id="report_old",
                             options=dict(options or {}))
    state.handoff_dir = handoff_dir or po.PipelineManager.handoff_dir(pid)
    state.stages = {name: po.StageState(name=name, status="completed", progress=100)
                    for name in po.STAGE_BANDS}
    if research_reused:
        with open(os.path.join(state.handoff_dir, "research_report.md"), "w",
                  encoding="utf-8") as fh:
            fh.write(REPORT)
    po.PipelineManager.save(state)
    po.PipelineOrchestrator._run(state)
    return SimpleNamespace(state=state, calls=calls, ontology_calls=ontology_calls,
                           project=project)


def _resume_attempt(pid):
    """Resume a failed pipeline for real (a fresh orchestrator) and return its state."""
    po.PipelineOrchestrator.resume(pid)
    _join(pid)
    return po.PipelineManager.load(pid)


_STALE_AFTER_RESEARCH = {
    po.STAGE_GRAPH: "research_recomputed",
    po.STAGE_PREPARE: "research_recomputed",
    po.STAGE_REPORT: "research_recomputed",
}


def test_research_recompute_refuses_ontology_and_graph_reuse(roots, monkeypatch):
    run = _drive_full(monkeypatch, "pipe_rs_lineage_research", research_reused=False)
    state = run.state
    assert run.calls, "research was recomputed this attempt"
    assert state.status == "failed" and state.error == "GRAPH_REBUILT"
    assert len(run.ontology_calls) == 1, "ontology regenerated from the new research"
    notes = state.options["stage_notes"]
    assert notes[po.STAGE_ONTOLOGY] == ["reuse_refused: research_recomputed"]
    assert notes[po.STAGE_GRAPH] == ["reuse_refused: research_recomputed"]
    decisions = [(row["stage"], row["reused"]) for row in state.options["stage_reuse_v1"]]
    assert decisions == [(po.STAGE_RESEARCH, False), (po.STAGE_ONTOLOGY, False)]
    # The regenerated ontology left the invalidation map; the unfinished
    # graph rebuild and everything below it stay stale for the next attempt.
    assert state.options["lineage_invalidated"] == _STALE_AFTER_RESEARCH
    persisted = po.PipelineManager.load(state.pipeline_id)
    assert persisted["options"]["stage_notes"] == notes
    assert persisted["options"]["lineage_invalidated"] == _STALE_AFTER_RESEARCH


def test_failed_ontology_rebuild_is_not_reused_on_the_next_attempt(roots, monkeypatch):
    """Research recompute -> ontology rebuild fails -> resume must still rebuild it."""
    pid = "pipe_rs_lineage_xattempt"
    run = _drive_full(monkeypatch, pid, research_reused=False, ontology_failures=1)
    assert run.state.status == "failed"
    assert run.state.error == "ontology provider outage"
    assert run.project.ontology["entity_types"] == [{"name": "Company"}], "old ontology"
    persisted = po.PipelineManager.load(pid)
    assert persisted["options"]["lineage_invalidated"] == {
        po.STAGE_ONTOLOGY: "research_recomputed", **_STALE_AFTER_RESEARCH}

    resumed = _resume_attempt(pid)
    assert len(run.calls) == 1, "research is reused on the next attempt"
    assert resumed["status"] == "failed" and resumed["error"] == "GRAPH_REBUILT"
    assert len(run.ontology_calls) == 2, "the stale ontology is regenerated, not reused"
    assert run.project.ontology["entity_types"] == [{"name": "Agency"}]
    notes = resumed["options"]["stage_notes"]
    assert notes[po.STAGE_ONTOLOGY] == ["reuse_refused: research_recomputed"] * 2
    assert notes[po.STAGE_GRAPH] == ["reuse_refused: ontology_recomputed"]
    decisions = [(row["stage"], row["reused"])
                 for row in resumed["options"]["stage_reuse_v1"]]
    assert decisions[-2:] == [(po.STAGE_RESEARCH, True), (po.STAGE_ONTOLOGY, False)]
    assert resumed["options"]["lineage_invalidated"] == _STALE_AFTER_RESEARCH


def test_saved_ontology_is_reused_when_its_attempt_ends_before_completion(roots, monkeypatch):
    """Research recompute -> ontology regenerated and saved -> crash -> resume reuses it."""
    pid = "pipe_rs_lineage_onto_saved"
    run = _drive_full(monkeypatch, pid, research_reused=False, ontology_completion_crashes=1)
    assert run.state.status == "failed" and run.state.error == "ONTOLOGY_COMPLETION_CRASHED"
    assert run.project.ontology["entity_types"] == [{"name": "Agency"}], "new ontology saved"
    # The saved ontology left the invalidation map at once; its downstream stays stale.
    assert po.PipelineManager.load(pid)["options"]["lineage_invalidated"] == (
        _STALE_AFTER_RESEARCH)

    resumed = _resume_attempt(pid)
    assert len(run.calls) == 1, "research is reused on the next attempt"
    assert resumed["status"] == "failed" and resumed["error"] == "GRAPH_REBUILT"
    assert len(run.ontology_calls) == 1, "the fresh ontology is reused, not regenerated"
    notes = resumed["options"]["stage_notes"]
    assert notes[po.STAGE_ONTOLOGY] == ["reuse_refused: research_recomputed"]
    assert notes[po.STAGE_GRAPH] == ["reuse_refused: research_recomputed"]
    decisions = [(row["stage"], row["reused"])
                 for row in resumed["options"]["stage_reuse_v1"]]
    assert decisions[-2:] == [(po.STAGE_RESEARCH, True), (po.STAGE_ONTOLOGY, True)]
    assert resumed["options"]["lineage_invalidated"] == _STALE_AFTER_RESEARCH


def test_saved_ontology_reused_next_attempt_keeps_its_producer_stamp(roots, monkeypatch):
    """Round-3 review: the reused ontology used to keep the replaced ontology's stamp.

    Attempt 1 (provider-a) regenerates and saves the ontology, then crashes before
    ``_complete_stage``; attempt 2 (provider-b) reuses it.  run.json must name
    provider-a, the ontology's producer, both at rest and after the reuse.
    """
    pid = "pipe_rs_onto_stamp"
    po.PipelineManager.ensure_dirs(pid)
    with open(po.PipelineManager.manifest_path(pid), "w", encoding="utf-8") as fh:
        json.dump({"resolved": {"ontology": {"provider": "provider-0",
                                             "model_name": "model-0"}}}, fh)
    run = _drive_full(monkeypatch, pid, research_reused=False,
                      ontology_completion_crashes=1, real_run_manifest=True)
    assert run.state.error == "ONTOLOGY_COMPLETION_CRASHED"
    producer = {"provider": "provider-a", "model_name": "model-a"}
    assert _manifest(pid)["resolved"]["ontology"] == producer

    monkeypatch.setattr(Config, "LLM_PROVIDER", "provider-b", raising=False)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "model-b", raising=False)
    resumed = _resume_attempt(pid)
    assert resumed["error"] == "GRAPH_REBUILT"
    assert len(run.ontology_calls) == 1, "the saved ontology is reused"
    decisions = [(row["stage"], row["reused"])
                 for row in resumed["options"]["stage_reuse_v1"]]
    assert decisions[-1] == (po.STAGE_ONTOLOGY, True)
    manifest = _manifest(pid)
    assert len(manifest["attempts"]) == 2
    # INFRA-8 adds the producer pair's requested label to the reused block (served unknown).
    assert manifest["resolved"]["ontology"] == {**producer, **_REUSED_MODEL_KEYS_A}


def test_guards_off_recompute_drops_a_stale_rebuilt_exemption(monkeypatch):
    """Round-3 review: guards on (report_x minted) -> guards off (RUN re-run) -> guards on.

    report_x predates the guards-off attempt's RUN, so it must lose its exemption.
    """
    state = po.PipelineState(pipeline_id="pipe_rs_toggle", prompt="q", options={
        run_shape.LINEAGE_INVALIDATED_OPTION: {po.STAGE_REPORT: "run_recomputed"},
        run_shape.LINEAGE_REBUILT_OPTION: {po.STAGE_REPORT: "report_x"},
    })
    monkeypatch.setattr(Config, "RESUME_LINEAGE_GUARDS", False, raising=False)
    po.PipelineOrchestrator()._record_stage_lineage(state, po.STAGE_RUN, reused=False)
    # Only the exemption goes; the guards-off attempt records nothing else.
    assert state.options == {
        run_shape.LINEAGE_INVALIDATED_OPTION: {po.STAGE_REPORT: "run_recomputed"}}
    monkeypatch.setattr(Config, "RESUME_LINEAGE_GUARDS", True, raising=False)
    assert po.PipelineOrchestrator()._lineage_refuses_reuse(
        state, po.STAGE_REPORT, bound_ids=("sim", "sim"),
        artifact_id="report_x") == "run_recomputed"


def test_guards_off_lineage_bookkeeping_leaves_legacy_state_untouched(monkeypatch):
    """No map was ever written: a guards-off recompute or ontology save changes nothing."""
    saves: list[str] = []
    monkeypatch.setattr(po.PipelineManager, "save",
                        classmethod(lambda cls, state: saves.append(state.pipeline_id)))
    monkeypatch.setattr(Config, "RESUME_LINEAGE_GUARDS", False, raising=False)
    orch = po.PipelineOrchestrator()
    state = po.PipelineState(pipeline_id="pipe_rs_legacy_maps", prompt="q",
                             options={"depth": "deep"})
    orch._record_stage_lineage(state, po.STAGE_RUN, reused=False)
    orch._record_lineage_artifact_replaced(state, po.STAGE_ONTOLOGY)
    assert state.options == {"depth": "deep"}
    assert saves == [], "no extra state save with the guards off"
    # A rebuilt map left by an earlier guards-on attempt is settled (and saved)
    # as soon as a guards-off attempt saves a regenerated ontology upstream of it.
    state.options[run_shape.LINEAGE_REBUILT_OPTION] = {po.STAGE_REPORT: "report_x"}
    orch._record_lineage_artifact_replaced(state, po.STAGE_ONTOLOGY)
    assert state.options == {"depth": "deep"}
    assert saves == ["pipe_rs_legacy_maps"]


def test_flags_off_research_recompute_keeps_legacy_reuse(roots, monkeypatch):
    _flags_off(monkeypatch)
    run = _drive_full(monkeypatch, "pipe_rs_lineage_legacy", research_reused=False)
    assert run.calls
    assert run.state.error == "PREPARE_REUSED", "legacy reuses ontology, graph and PREPARE"
    assert run.ontology_calls == []
    for key in ("stage_notes", "stage_reuse_v1", "lineage_invalidated"):
        assert key not in run.state.options


def test_prepare_reuse_refused_when_simulation_graph_differs(roots, monkeypatch):
    run = _drive_full(monkeypatch, "pipe_rs_lineage_prepare", research_reused=True,
                      sim_graph_id="graph_other")
    state = run.state
    assert run.calls == [] and run.ontology_calls == []
    assert state.error == "PREPARE_REBUILT"
    assert state.options["stage_notes"] == {
        po.STAGE_PREPARE: ["reuse_refused: graph_id_mismatch"]}
    assert state.options["lineage_invalidated"] == {po.STAGE_PREPARE: "graph_id_mismatch"}
    decisions = [(row["stage"], row["reused"]) for row in state.options["stage_reuse_v1"]]
    assert decisions == [(po.STAGE_RESEARCH, True), (po.STAGE_ONTOLOGY, True),
                         (po.STAGE_GRAPH, True)]


def test_prepare_reuse_kept_when_simulation_graph_matches(roots, monkeypatch):
    run = _drive_full(monkeypatch, "pipe_rs_lineage_prepare_ok", research_reused=True)
    assert run.state.error == "PREPARE_REUSED"
    assert "stage_notes" not in run.state.options
    assert "lineage_invalidated" not in run.state.options


def test_prepare_graph_mismatch_ignored_with_guards_off(roots, monkeypatch):
    monkeypatch.setattr(Config, "RESUME_LINEAGE_GUARDS", False, raising=False)
    run = _drive_full(monkeypatch, "pipe_rs_lineage_prepare_off", research_reused=True,
                      sim_graph_id="graph_other")
    assert run.state.error == "PREPARE_REUSED"
    assert "stage_notes" not in run.state.options
    assert "lineage_invalidated" not in run.state.options


def _save_base(pipeline_id, project_id):
    base = po.PipelineState(pipeline_id=pipeline_id, prompt="base", mode="full",
                            status="completed", graph_id="graph", project_id=project_id)
    po.PipelineManager.ensure_dirs(pipeline_id)
    po.PipelineManager.save(base)


def test_scenario_fork_sharing_the_base_project_fails_closed(roots, monkeypatch):
    """The guard never regenerates the base pipeline's ontology in place."""
    _save_base("pipe_rs_fork_base", "proj")
    run = _drive_full(monkeypatch, "pipe_rs_fork_shared", research_reused=False,
                      options={"base_pipeline_id": "pipe_rs_fork_base",
                               "scenario_overlay": {}, "scenario_label": "what-if"})
    assert run.state.status == "failed"
    assert "shared with base pipeline pipe_rs_fork_base" in run.state.error
    assert "research_recomputed" in run.state.error
    assert run.ontology_calls == []
    assert run.project.ontology["entity_types"] == [{"name": "Company"}], "base untouched"


def test_scenario_fork_graph_guard_fails_closed_on_the_shared_project(roots, monkeypatch):
    _save_base("pipe_rs_fork_base_graph", "proj")
    run = _drive_full(monkeypatch, "pipe_rs_fork_shared_graph", research_reused=True,
                      options={"base_pipeline_id": "pipe_rs_fork_base_graph",
                               "scenario_overlay": {},
                               "lineage_invalidated": {po.STAGE_GRAPH: "ontology_recomputed"}})
    assert run.state.status == "failed"
    assert "graph artifact" in run.state.error
    assert "shared with base pipeline pipe_rs_fork_base_graph" in run.state.error
    assert run.project.graph_id == "graph"


def test_fork_owning_its_project_rebuilds_normally(roots, monkeypatch):
    """A fork whose project is not the base's (batch question forks) is unaffected."""
    _save_base("pipe_rs_fork_base_other", "proj_anchor")
    run = _drive_full(monkeypatch, "pipe_rs_fork_own", research_reused=False,
                      options={"base_pipeline_id": "pipe_rs_fork_base_other"})
    assert run.state.error == "GRAPH_REBUILT"
    assert len(run.ontology_calls) == 1


def test_fork_graph_rebuild_never_writes_into_the_base_handoff(roots, monkeypatch):
    """A batch question fork (own project, base handoff) fails closed at GRAPH."""
    _save_base("pipe_rs_batch_anchor", "proj_anchor")
    base_handoff = po.PipelineManager.handoff_dir("pipe_rs_batch_anchor")
    os.makedirs(base_handoff, exist_ok=True)
    communities = os.path.join(base_handoff, "communities.json")
    with open(communities, "w", encoding="utf-8") as fh:
        fh.write('{"communities": ["anchor"]}')
    run = _drive_full(monkeypatch, "pipe_rs_batch_fork", research_reused=False,
                      handoff_dir=base_handoff,
                      options={"base_pipeline_id": "pipe_rs_batch_anchor",
                               run_shape.SHARED_GRAPH_OPTION: "pipe_rs_batch_anchor"})
    assert run.state.status == "failed"
    error = run.state.error
    assert "graph artifact" in error and "research_recomputed" in error
    # Only the handoff is shared: the fork owns its project.
    assert (f"but its handoff dir {base_handoff} is shared with base pipeline "
            "pipe_rs_batch_anchor") in error
    assert len(run.ontology_calls) == 1, "the fork still regenerates its own ontology"
    with open(communities, encoding="utf-8") as fh:
        assert fh.read() == '{"communities": ["anchor"]}', "base graph artifacts untouched"


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

    result = _exercise_prepare_run_resume(
        monkeypatch, tmp_path, rebuild_prepare=False, report_simulation_id="sim_other",
        lineage_flags=guards)
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

    result = _exercise_prepare_run_resume(
        monkeypatch, tmp_path, rebuild_prepare=False, corrupt_run=True, lineage_flags=False)
    assert result.state.status == "completed"
    assert result.start_calls == [result.old_id]
    assert result.report_generations == []
    assert result.state.report_id == "report_existing"


@pytest.mark.parametrize("interrupt", ["cancel_after_publish", "complete_stage_crash"])
def test_report_published_before_stage_completion_is_reused_on_resume(
        monkeypatch, tmp_path, interrupt):
    """RUN re-executed -> report minted and published -> attempt cut off -> reused.

    The cancel is raised from the report's final progress callback (as
    ReportAgent.generate_report does after saving the completed report); the
    crash models a restart before ``_complete_stage(REPORT)``.
    """
    from tests.test_orchestrator_research_wiring import _exercise_prepare_run_resume

    result = _exercise_prepare_run_resume(
        monkeypatch, tmp_path, rebuild_prepare=False, corrupt_run=True,
        report_interrupt=interrupt)
    minted = result.state.report_id
    assert result.state.status == (
        "cancelled" if interrupt == "cancel_after_publish" else "failed")
    assert result.report_generations == [result.old_id]
    assert minted not in (None, "report_existing")
    persisted = po.PipelineManager.load(result.pid)
    assert persisted["report_id"] == minted
    assert persisted["options"]["lineage_invalidated"] == {po.STAGE_REPORT: "run_recomputed"}
    assert persisted["options"]["lineage_rebuilt"] == {po.STAGE_REPORT: minted}

    resumed = _resume_attempt(result.pid)
    assert resumed["status"] == "completed", resumed.get("error")
    assert result.report_generations == [result.old_id], "no second report generation"
    assert resumed["report_id"] == minted, "the published report_id is kept"
    assert resumed["options"]["stage_notes"][po.STAGE_REPORT] == [
        "reuse_refused: run_recomputed"]
    for key in ("lineage_invalidated", "lineage_rebuilt"):
        assert key not in resumed["options"]
    decisions = [(row["stage"], row["reused"]) for row in resumed["options"]["stage_reuse_v1"]]
    assert decisions[-1] == (po.STAGE_REPORT, True)


def test_unfinished_minted_report_is_not_exempt_from_the_refusal(monkeypatch, tmp_path):
    """Round-3 review: the minted report reached disk only as GENERATING.

    With the health gate off the lineage refusal is the only barrier: the
    unfinished report must be regenerated, not reused through the exemption.
    """
    from tests.test_orchestrator_research_wiring import _exercise_prepare_run_resume

    monkeypatch.setattr(Config, "PIPELINE_HEALTH_GATE", False, raising=False)
    result = _exercise_prepare_run_resume(
        monkeypatch, tmp_path, rebuild_prepare=False, corrupt_run=True,
        report_interrupt="cancel_after_publish")
    minted = result.state.report_id
    assert po.PipelineManager.load(result.pid)["options"]["lineage_rebuilt"] == {
        po.STAGE_REPORT: minted}
    po.ReportManager.get_report(minted).status = po.ReportStatus.GENERATING

    resumed = _resume_attempt(result.pid)
    assert resumed["status"] == "completed", resumed.get("error")
    assert result.report_generations == [result.old_id, result.old_id]
    assert resumed["report_id"] not in (minted, "report_existing")
    assert resumed["options"]["stage_notes"][po.STAGE_REPORT] == [
        "reuse_refused: run_recomputed"] * 2
    for key in ("lineage_invalidated", "lineage_rebuilt"):
        assert key not in resumed["options"]


def test_minted_report_that_never_reached_disk_keeps_the_stale_report_refused(
        monkeypatch, tmp_path):
    """Cancelled right after the mint: the simulation lookup's stale report stays refused."""
    from tests.test_orchestrator_research_wiring import _exercise_prepare_run_resume

    result = _exercise_prepare_run_resume(
        monkeypatch, tmp_path, rebuild_prepare=False, corrupt_run=True,
        report_interrupt="cancel_before_meta")
    minted = result.state.report_id
    assert result.state.status == "cancelled"
    assert result.report_generations == []
    assert minted not in (None, "report_existing")
    assert po.PipelineManager.load(result.pid)["options"]["lineage_rebuilt"] == {
        po.STAGE_REPORT: minted}

    resumed = _resume_attempt(result.pid)
    assert resumed["status"] == "completed", resumed.get("error")
    # The minted id never resolved, so the lookup fell back to the simulation's
    # newest report: the stale one, still refused.
    assert result.report_generations == [result.old_id]
    assert resumed["report_id"] not in (minted, "report_existing")
    assert resumed["options"]["stage_notes"][po.STAGE_REPORT] == [
        "reuse_refused: run_recomputed"] * 2
    for key in ("lineage_invalidated", "lineage_rebuilt"):
        assert key not in resumed["options"]


def _stamped_run_manifest(monkeypatch):
    """A run.json from an earlier attempt: calendar-mode simulation, provider-0 stamps."""
    monkeypatch.setattr(Config, "LLM_PROVIDER", "provider-a", raising=False)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "model-a", raising=False)
    stamp = {"provider": "provider-0", "model_name": "model-0"}
    return {
        "resolved": {
            "ontology": dict(stamp), "graph": dict(stamp), "report": dict(stamp),
            "simulation": {"max_agents": 3, "total_rounds": 18, "calendar_unit": "week",
                           "n_rounds": 18, "horizon_date": "2027-06-30"},
        },
        "attempts": [{"started_at": "t0", "run_shape_sha256": None, "drift_knobs": []}],
    }


def test_failed_report_rebuild_after_run_recompute_is_not_reused_next_attempt(
        monkeypatch, tmp_path):
    """RUN re-executed -> report refused -> preflight fails -> resume regenerates it.

    Driven through the real ``_run`` twice with the real run.json writers, so it
    also checks the attempt history, the RUN runtime fields and the provider
    stamps across a provider switch.
    """
    from tests.test_orchestrator_research_wiring import _exercise_prepare_run_resume

    result = _exercise_prepare_run_resume(
        monkeypatch, tmp_path, rebuild_prepare=False, corrupt_run=True,
        report_preflight_failures=1, real_run_manifest=True,
        prior_run_manifest=_stamped_run_manifest(monkeypatch))
    assert result.state.status == "failed"
    assert "报告前置探测失败" in result.state.error
    assert result.start_calls == [result.old_id]
    assert result.report_generations == []
    assert result.state.report_id == "report_existing", "no new report was minted"
    assert result.state.options["lineage_invalidated"] == {
        po.STAGE_REPORT: "run_recomputed"}
    # While the re-executed RUN was in flight, run.json held this attempt's fresh
    # simulation block, not the replaced simulation's calendar/round fields.
    in_flight = result.run_manifest_at_start[0]
    assert in_flight["total_rounds"] is None
    assert in_flight["max_agents"] == Config.OASIS_MAX_AGENTS
    assert not {"calendar_unit", "n_rounds", "horizon_date"} & set(in_flight)
    first = _manifest(result.pid)
    assert first["resolved"]["simulation"]["total_rounds"] == 9
    assert first["resolved"]["simulation"]["calendar_unit"] == "year"
    assert first["resolved"]["simulation"]["horizon_date"] == "2035-12-31"

    monkeypatch.setattr(Config, "LLM_PROVIDER", "provider-b", raising=False)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "model-b", raising=False)
    resumed = _resume_attempt(result.pid)
    assert resumed["status"] == "completed", resumed.get("error")
    assert result.start_calls == [result.old_id], "RUN is reused on the next attempt"
    assert result.report_generations == [result.old_id], "the stale report is regenerated"
    assert resumed["report_id"] not in (None, "report_existing")
    assert resumed["options"]["stage_notes"][po.STAGE_REPORT] == [
        "reuse_refused: run_recomputed"] * 2
    assert "lineage_invalidated" not in resumed["options"]
    decisions = [(row["stage"], row["reused"]) for row in resumed["options"]["stage_reuse_v1"]]
    assert decisions[-3:] == [(po.STAGE_PREPARE, True), (po.STAGE_RUN, True),
                              (po.STAGE_REPORT, False)]

    final = _manifest(result.pid)
    assert len(final["attempts"]) == 3
    resolved = final["resolved"]
    # Reused stages keep the stamp of the attempt that produced them; INFRA-8 adds the
    # requested label of a stamped pair that lacks it (served ids unknown).
    no_calls = {"requested_models": [], "served_models": []}
    assert resolved["ontology"] == {"provider": "provider-0", "model_name": "model-0",
                                    "requested_model": "model-0", **no_calls}
    assert resolved["graph"] == {"provider": "provider-0", "model_name": "model-0",
                                 "requested_model": "model-0", **no_calls}
    # INFRA-8 merges the recomputing attempt's requested / served models next to the pair.
    assert resolved["report"] == {"provider": "provider-b", "model_name": "model-b",
                                  "requested_model": "model-b", **no_calls}
    assert resolved["simulation"] == first["resolved"]["simulation"]


_PRODUCER_A = {"provider": "provider-a", "model_name": "model-a"}
# INFRA-8: what a reused stage restamped with producer A gains (its served ids are unknown).
_REUSED_MODEL_KEYS_A = {"requested_model": "model-a", "requested_models": [], "served_models": []}


def _switch_provider_and_resume(monkeypatch, pid):
    monkeypatch.setattr(Config, "LLM_PROVIDER", "provider-b", raising=False)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "model-b", raising=False)
    return _resume_attempt(pid)


def test_reused_rebuilt_report_keeps_its_producer_stamp(monkeypatch, tmp_path):
    """Round-3 review: RUN re-run -> report X minted+published (provider-a) -> cancel
    -> provider-b resume reuses X.  run.json must name X's producer, not the
    replaced report's (provider-0), both at rest and after the reuse."""
    from tests.test_orchestrator_research_wiring import _exercise_prepare_run_resume

    result = _exercise_prepare_run_resume(
        monkeypatch, tmp_path, rebuild_prepare=False, corrupt_run=True,
        report_interrupt="cancel_after_publish", real_run_manifest=True,
        prior_run_manifest=_stamped_run_manifest(monkeypatch))
    minted = result.state.report_id
    assert result.state.status == "cancelled"
    assert _manifest(result.pid)["resolved"]["report"] == _PRODUCER_A
    assert po.PipelineManager.load(result.pid)["options"][
        run_shape.REPORT_PRODUCER_OPTION] == {"report_id": minted, **_PRODUCER_A}

    resumed = _switch_provider_and_resume(monkeypatch, result.pid)
    assert resumed["status"] == "completed", resumed.get("error")
    assert resumed["report_id"] == minted
    assert result.report_generations == [result.old_id], "X was reused"
    assert _manifest(result.pid)["resolved"]["report"] == {**_PRODUCER_A, **_REUSED_MODEL_KEYS_A}
    assert run_shape.REPORT_PRODUCER_OPTION not in resumed["options"]


def test_reused_force_regenerated_report_keeps_its_producer_stamp(monkeypatch, tmp_path):
    """The same holds without any lineage invalidation (a force re-report)."""
    from tests.test_orchestrator_research_wiring import _exercise_prepare_run_resume

    result = _exercise_prepare_run_resume(
        monkeypatch, tmp_path, rebuild_prepare=False,
        report_interrupt="cancel_after_publish", real_run_manifest=True,
        prior_run_manifest=_stamped_run_manifest(monkeypatch),
        extra_options={"force_report_regen": "2026-09-30T00:00:00Z"})
    minted = result.state.report_id
    assert result.state.status == "cancelled"
    assert "lineage_rebuilt" not in result.state.options
    assert _manifest(result.pid)["resolved"]["report"] == _PRODUCER_A

    resumed = _switch_provider_and_resume(monkeypatch, result.pid)
    assert resumed["status"] == "completed", resumed.get("error")
    assert resumed["report_id"] == minted
    assert result.report_generations == [result.old_id]
    assert _manifest(result.pid)["resolved"]["report"] == {**_PRODUCER_A, **_REUSED_MODEL_KEYS_A}


def test_reused_report_never_borrows_a_lost_mints_stamp(monkeypatch, tmp_path):
    """Minted report never reached disk; the simulation lookup's older report is reused.

    The mint restamped run.json for the report it minted; the older report's
    producer is not recorded, so it is stamped unknown rather than provider-a.
    """
    from tests.test_orchestrator_research_wiring import _exercise_prepare_run_resume

    result = _exercise_prepare_run_resume(
        monkeypatch, tmp_path, rebuild_prepare=False,
        report_interrupt="cancel_before_meta", real_run_manifest=True,
        prior_run_manifest=_stamped_run_manifest(monkeypatch),
        extra_options={"force_report_regen": "2026-09-30T00:00:00Z"})
    assert result.state.status == "cancelled"
    assert result.report_generations == []
    assert _manifest(result.pid)["resolved"]["report"] == _PRODUCER_A

    resumed = _switch_provider_and_resume(monkeypatch, result.pid)
    assert resumed["status"] == "completed", resumed.get("error")
    assert resumed["report_id"] == "report_existing"
    assert _manifest(result.pid)["resolved"]["report"] == {
        "provider": None, "model_name": None}
    assert run_shape.REPORT_PRODUCER_OPTION not in resumed["options"]


def test_guard_refused_report_consumes_the_force_regen_flag(monkeypatch, tmp_path):
    from tests.test_orchestrator_research_wiring import _exercise_prepare_run_resume

    result = _exercise_prepare_run_resume(
        monkeypatch, tmp_path, rebuild_prepare=False, corrupt_run=True,
        extra_options={"force_report_regen": "2026-09-30T00:00:00Z"})
    assert result.state.status == "completed", result.state.error
    assert result.report_generations == [result.old_id]
    assert "force_report_regen" not in result.state.options


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
    # INFRA-8 merges each recomputing attempt's requested / served models next to the pair.
    assert resolved["ontology"] == {"provider": "provider-a", "model_name": "model-a",
                                    "requested_model": "model-a", "requested_models": [],
                                    "served_models": []}
    assert resolved["graph"] == {"provider": "provider-b", "model_name": "model-b",
                                 "requested_model": "model-b", "requested_models": [],
                                 "served_models": []}
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
    path = po.PipelineManager.manifest_path(state.pipeline_id)
    with open(path, "rb") as fh:
        before = fh.read()
    second._reset_run_manifest_simulation(state)
    with open(path, "rb") as fh:
        assert fh.read() == before, "flags off: a RUN rerun leaves run.json alone"


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
    # The recomputed RUN wrote no round count: attempt 1's 12 is not carried.
    assert restamped["simulation"]["total_rounds"] is None


def test_run_rerun_drops_the_replaced_simulations_runtime_fields(roots, monkeypatch):
    """Calendar-mode attempt 1, then a rounds-mode RUN rerun: no calendar leftovers."""
    _complete_quietly(monkeypatch)
    state = po.PipelineState(pipeline_id="pipe_rs_simfields", prompt="q", mode="full")
    po.PipelineManager.ensure_dirs(state.pipeline_id)
    calendar = {"calendar_unit": "week", "n_rounds": 18, "horizon_date": "2027-06-30"}
    first = po.PipelineOrchestrator()
    first._write_run_manifest(state)
    first._reset_run_manifest_simulation(state)
    first._update_manifest(state, po.STAGE_RUN, total_rounds=18, temporal=calendar)
    first._complete_stage(state, po.STAGE_RUN)
    written = _manifest(state.pipeline_id)["resolved"]["simulation"]
    assert {key: written.get(key) for key in ("total_rounds", *calendar)} == {
        "total_rounds": 18, **calendar}

    second = po.PipelineOrchestrator()
    second._write_run_manifest(state)
    carried = _manifest(state.pipeline_id)["resolved"]["simulation"]
    assert carried["calendar_unit"] == "week", "carried until RUN decides to rerun"
    second._reset_run_manifest_simulation(state)
    in_flight = _manifest(state.pipeline_id)["resolved"]["simulation"]
    assert in_flight["total_rounds"] is None
    assert not set(calendar) & set(in_flight)
    second._update_manifest(state, po.STAGE_RUN, total_rounds=10, temporal=None)
    second._complete_stage(state, po.STAGE_RUN)
    final = _manifest(state.pipeline_id)["resolved"]["simulation"]
    assert final["total_rounds"] == 10
    assert not set(calendar) & set(final)
    assert second._attempt_sim_runtime() == {"total_rounds": 10}


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
