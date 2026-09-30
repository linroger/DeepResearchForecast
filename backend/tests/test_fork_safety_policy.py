"""INFRA-9: scenario and batch-question forks inherit the base run's safety policy.

Offline: pipelines live under tmp_path and the pipeline thread body (_run) is a
no-op, so only the admission-time options of each fork are exercised.
"""

from __future__ import annotations

import pytest

from app.config import Config
from app.services import pipeline_orchestrator as po


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """Point every artifact root at tmp_path; the pipeline thread does nothing."""
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"), raising=False)
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"), raising=False)
    monkeypatch.setattr(po.PipelineOrchestrator, "_run", classmethod(lambda cls, state: None))
    # Admission-time policy of the base run.
    for name, value in {
        "FORK_INHERIT_SAFETY_POLICY": True,
        "SIM_GRAPH_FEEDBACK": True,
        "N_FORECAST_SEEDS": 3,
        "ENSEMBLE_EXTREMIZE_A": 1.5,
        "SIMULATION_FORECAST_EFFECT": "bounded",
    }.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    return tmp_path


def _change_ambient(monkeypatch):
    """A service reload after the base was admitted: every safety default moved."""
    for name, value in {
        "SIM_GRAPH_FEEDBACK": False,
        "N_FORECAST_SEEDS": 1,
        "ENSEMBLE_EXTREMIZE_A": 1.0,
        "SIMULATION_FORECAST_EFFECT": "diagnostic_only",
    }.items():
        monkeypatch.setattr(Config, name, value, raising=False)


def _base(pipeline_id, *, pinned):
    state = po.PipelineState(pipeline_id=pipeline_id, prompt="Will X happen by 2030?",
                             mode="full", status="completed", graph_id="graph_infra9",
                             simulation_id="sim_infra9", project_id="proj_infra9",
                             options={"project_name": "infra9"})
    if pinned:
        state.options["safety_policy_v1"] = po.capture_safety_policy_v1("admission")
    po.PipelineManager.ensure_dirs(pipeline_id)
    po.PipelineManager.save(state)
    return state


def _join(pipeline_id):
    thread = po.PipelineOrchestrator._threads.pop(pipeline_id, None)
    if thread is not None:
        thread.join(timeout=10)
        assert not thread.is_alive()
    po.PipelineOrchestrator._cancel_events.pop(pipeline_id, None)


def _scenario_fork(base_id):
    fork = po.PipelineOrchestrator.fork(base_id, {"label": "what-if"})
    _join(fork.pipeline_id)
    return fork


def _question_fork(base_id):
    from scripts import batch_runs

    fork = batch_runs.fork_question(base_id, "Question two?", batch_id="batch_infra9")
    _join(fork.pipeline_id)
    return fork


FORKS = pytest.mark.parametrize("make_fork", [_scenario_fork, _question_fork],
                                ids=["scenario_fork", "question_fork"])


def _persisted(pipeline_id):
    return po.PipelineState.from_dict(po.PipelineManager.load(pipeline_id))


@FORKS
def test_fork_inherits_the_base_policy_after_the_ambient_config_changed(roots, monkeypatch,
                                                                         make_fork):
    base = _base("pipe_infra9_base", pinned=True)
    base_policy = base.options["safety_policy_v1"]
    _change_ambient(monkeypatch)

    fork = make_fork(base.pipeline_id)

    persisted = _persisted(fork.pipeline_id)
    policy = persisted.options["safety_policy_v1"]
    assert policy == {**base_policy, "origin": "fork_inherited"}
    assert policy["pinned_at"] == base_policy["pinned_at"]
    # _pinned_safety serves the inherited values, not today's ambient defaults.
    pinned = po.PipelineOrchestrator._pinned_safety
    assert pinned(persisted, "n_forecast_seeds", Config.N_FORECAST_SEEDS) == 3
    assert pinned(persisted, "sim_graph_feedback", Config.SIM_GRAPH_FEEDBACK) is True
    assert pinned(persisted, "ensemble_extremize_a", Config.ENSEMBLE_EXTREMIZE_A) == 1.5
    assert pinned(persisted, "simulation_forecast_effect",
                  Config.SIMULATION_FORECAST_EFFECT) == "bounded"
    # A deep copy: the fork's pin never aliases the base's.
    assert fork.options["safety_policy_v1"] is not base_policy
    assert _persisted(base.pipeline_id).options["safety_policy_v1"] == base_policy


@FORKS
def test_fork_of_a_legacy_base_captures_the_policy_at_fork_admission(roots, monkeypatch,
                                                                      make_fork):
    base = _base("pipe_infra9_legacy", pinned=False)
    _change_ambient(monkeypatch)

    fork = make_fork(base.pipeline_id)

    persisted = _persisted(fork.pipeline_id)
    policy = persisted.options["safety_policy_v1"]
    expected = po.capture_safety_policy_v1("fork_admission")
    assert policy["origin"] == "fork_admission"
    assert {k: v for k, v in policy.items() if k != "pinned_at"} == {
        k: v for k, v in expected.items() if k != "pinned_at"}
    # Later ambient drift no longer reaches the fork.
    monkeypatch.setattr(Config, "N_FORECAST_SEEDS", 5, raising=False)
    assert po.PipelineOrchestrator._pinned_safety(
        persisted, "n_forecast_seeds", Config.N_FORECAST_SEEDS) == 1
    assert "safety_policy_v1" not in _persisted(base.pipeline_id).options


@FORKS
def test_flag_off_fork_carries_no_pin_and_reads_ambient(roots, monkeypatch, make_fork):
    base = _base("pipe_infra9_off", pinned=True)
    _change_ambient(monkeypatch)
    on = make_fork(base.pipeline_id)
    monkeypatch.setattr(Config, "FORK_INHERIT_SAFETY_POLICY", False, raising=False)

    off = make_fork(base.pipeline_id)

    off_options = po.PipelineManager.load(off.pipeline_id)["options"]
    on_options = po.PipelineManager.load(on.pipeline_id)["options"]
    assert "safety_policy_v1" not in off_options
    # The pin is the only option the knob adds (legacy options otherwise unchanged).
    assert set(on_options) - set(off_options) == {"safety_policy_v1"}
    for key in set(off_options) - {"run_shape_v1"}:
        assert off_options[key] == on_options[key], key
    assert po.PipelineOrchestrator._pinned_safety(
        _persisted(off.pipeline_id), "n_forecast_seeds", Config.N_FORECAST_SEEDS) == 1


def test_fork_policy_helper_contract(monkeypatch):
    monkeypatch.setattr(Config, "FORK_INHERIT_SAFETY_POLICY", True, raising=False)
    base_policy = {"version": po.SAFETY_POLICY_VERSION, "origin": "resume_reconstructed_safe",
                   "n_forecast_seeds": 2, "nested": {"k": [1]}}
    inherited = po.fork_safety_policy_v1({"safety_policy_v1": base_policy})
    assert inherited == {**base_policy, "origin": "fork_inherited"}
    assert inherited["nested"] is not base_policy["nested"]
    for legacy in (None, {}, {"safety_policy_v1": None}, {"safety_policy_v1": "junk"}, "junk"):
        assert po.fork_safety_policy_v1(legacy)["origin"] == "fork_admission"
    monkeypatch.setattr(Config, "FORK_INHERIT_SAFETY_POLICY", False, raising=False)
    assert po.fork_safety_policy_v1({"safety_policy_v1": base_policy}) is None
    assert po.fork_safety_policy_v1(None) is None
