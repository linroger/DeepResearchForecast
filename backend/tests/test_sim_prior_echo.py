"""SIM-4 (C30): zero-LLM prior-echo diagnostic for the decision channel.

prior_echo_diagnostics reads world_state_trajectory.json alone: the seed prior is
the round-0 row, the final shares are outcome.shares, and the commitments are the
decisions rows. Verdicts (first match): unavailable, inconclusive, prior_echo,
prior_leader_herd, divergent ("not trivially hollow", never "informative").
The orchestrator records the verdict in decision_channel_summary.prior_echo and
the report world-state block gets one number-free caveat line for echo/herd.
"""

import copy
import json
import math
import os
import re
import subprocess
import sys

import pytest

from app.config import Config
from app.services import pipeline_orchestrator as po
from app.services import sim_prior_echo as spe
from app.services.forecast_extractor import world_state_outcome_from_signal_pack
from app.services.report_agent import ReportAgent

PRIOR = {"A": 0.6, "B": 0.4}


def _traj(final, *, decisions=(), statuses=("committed",) * 3, validity: "str | None" = "valid", prior=PRIOR,
          uniform_prior=False):
    rows = [{"round": 0, "shares": dict(prior), "uniform_prior": uniform_prior}]
    for i, status in enumerate(statuses, start=1):
        rows.append({"round": i, "shares": dict(final), "round_status": status})
    doc = {"outcome": {"shares": dict(final), "leader": max(final, key=final.get)},
           "trajectory": rows, "decisions": [dict(d) for d in decisions]}
    if validity is not None:
        doc["validity"] = validity
    return doc


def _decisions(scenario, n=6, **extra):
    return [{"agent_id": i, "scenario": scenario, "magnitude": 0.8, "confidence": 0.9,
             "round": 1 + i % 3, **extra} for i in range(n)]


# ------------------------------------------------------------------ verdicts
def test_final_equal_to_the_prior_is_a_prior_echo():
    out = spe.prior_echo_diagnostics(_traj(PRIOR, statuses=("abstained",) * 3))
    assert out["verdict"] == "prior_echo" and out["tv_to_prior"] == 0.0
    assert out["policy_version"] == "drf-sim-control/v1" and out["valid_rounds"] == 3


def test_commitments_on_the_prior_leader_are_a_herd():
    out = spe.prior_echo_diagnostics(_traj({"A": 0.8, "B": 0.2}, decisions=_decisions("A")))
    assert out["tv_to_prior"] == 0.2 and out["prior_leader"] == "A"
    assert out["prior_leader_commit_rate"] == 1.0 and out["verdict"] == "prior_leader_herd"


def test_sustained_commitments_to_a_non_leader_are_divergent():
    decisions = _decisions("B", 8) + _decisions("A", 2)
    out = spe.prior_echo_diagnostics(_traj({"A": 0.35, "B": 0.65}, decisions=decisions))
    assert out["verdict"] == "divergent" and out["reasons"] == []
    assert out["prior_leader_commit_rate"] == 0.2


@pytest.mark.parametrize("prior,uniform", [({"A": 0.5, "B": 0.5}, False), (PRIOR, True)])
def test_a_uniform_or_tied_prior_has_no_leader_and_is_never_a_herd(prior, uniform):
    out = spe.prior_echo_diagnostics(
        _traj({"A": 0.8, "B": 0.2}, decisions=_decisions("A"), prior=prior, uniform_prior=uniform))
    assert out["prior_leader"] is None and out["prior_leader_commit_rate"] is None
    assert out["uniform_prior"] is uniform and out["verdict"] == "divergent"


def test_a_non_valid_trajectory_or_too_few_valid_rounds_is_inconclusive():
    out = spe.prior_echo_diagnostics(_traj(PRIOR, validity="inconclusive"))
    assert (out["verdict"], out["reasons"]) == ("inconclusive", ["trajectory_not_valid"])
    out = spe.prior_echo_diagnostics(_traj(PRIOR, statuses=("committed", "failed", "abstained")))
    assert (out["verdict"], out["reasons"], out["valid_rounds"]) == (
        "inconclusive", ["too_few_valid_rounds"], 2)


def test_legacy_rows_count_distinct_decision_rounds():
    doc = _traj(PRIOR, decisions=_decisions("B", 6), validity=None)
    for row in doc["trajectory"]:
        row.pop("round_status", None)
    out = spe.prior_echo_diagnostics(doc)
    assert out["valid_rounds"] == 3 and out["verdict"] == "prior_echo"


@pytest.mark.parametrize("doc,reason", [
    ({}, "no_prior"),
    ({"trajectory": [{"round": 0, "shares": PRIOR}]}, "no_final_shares"),
    ({"trajectory": [{"round": 0, "shares": {"A": 1.0}}], "outcome": {"shares": {"A": 1.0}}},
     "fewer_than_two_scenarios"),
    ("not a trajectory", "no_trajectory"),
])
def test_missing_or_degenerate_input_is_unavailable(doc, reason):
    out = spe.prior_echo_diagnostics(doc)
    assert (out["verdict"], out["reasons"]) == ("unavailable", [reason])


def test_non_finite_commitments_are_skipped_and_output_is_deterministic():
    decisions = _decisions("A", 6) + [
        {"scenario": "B", "magnitude": float("nan"), "confidence": 1.0},
        {"scenario": "B", "magnitude": "lots", "confidence": 1.0},
        {"scenario": "B", "magnitude": 1.0, "confidence": float("inf")},
        {"scenario": "B", "magnitude": 1.0, "confidence": 1.0, "outcome_power": None}]
    doc = _traj({"A": 0.8, "B": 0.2}, decisions=decisions)
    first = spe.prior_echo_diagnostics(doc)
    assert first["prior_leader_commit_rate"] == 1.0
    assert spe.prior_echo_diagnostics(copy.deepcopy(doc)) == first
    assert json.dumps(first, sort_keys=True) == json.dumps(spe.prior_echo_diagnostics(doc), sort_keys=True)


def test_outcome_power_weights_the_commitment_mass():
    decisions = [{"scenario": "A", "magnitude": 1.0, "confidence": 1.0, "outcome_power": 9.0, "round": 1},
                 {"scenario": "B", "magnitude": 1.0, "confidence": 1.0, "round": 2},
                 {"scenario": "B", "magnitude": 1.0, "confidence": 1.0, "outcome_power": -3, "round": 3}]
    out = spe.prior_echo_diagnostics(_traj({"A": 0.8, "B": 0.2}, decisions=decisions))
    assert out["prior_leader_commit_rate"] == 0.9 and out["verdict"] == "prior_leader_herd"


def test_an_internal_error_is_unavailable_never_raised():
    class Boom(dict):
        def get(self, *args, **kwargs):
            raise RuntimeError("boom")

    out = spe.prior_echo_diagnostics(Boom(outcome={}))
    assert out["verdict"] == "unavailable" and out["reasons"] == ["diagnostics_error:RuntimeError"]


def test_policy_is_frozen_and_the_module_is_pure():
    assert dict(spe.SIM_CONTROL_POLICY_V1) == {
        "version": "drf-sim-control/v1", "echo_tv": 0.05, "leader_commit_rate": 0.9, "min_valid_rounds": 3}
    # Load the module file on its own (the app.services package __init__ imports other
    # services): the module itself must pull in no camel, oasis or app module.
    path = spe.__file__
    probe = ("import importlib.util, sys; "
             f"spec = importlib.util.spec_from_file_location('sim_prior_echo', {path!r}); "
             "mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); "
             "print(sorted(m for m in sys.modules if m.split('.')[0] in ('camel', 'oasis', 'app')))")
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"


# ------------------------------------------------------------------ report block
@pytest.fixture
def sim_root(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(Config, "REPORT_WORLDSTATE_HIDE_INVALID", True, raising=False)
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "diagnostic_only", raising=False)
    return tmp_path


def _block(sim_root, doc, sim_id="sim_echo"):
    os.makedirs(sim_root / sim_id, exist_ok=True)
    (sim_root / sim_id / "world_state_trajectory.json").write_text(json.dumps(doc), encoding="utf-8")
    agent = ReportAgent.__new__(ReportAgent)
    agent.simulation_id = sim_id
    return agent._world_state_block()


def test_world_state_block_flags_a_prior_echo_without_numbers(sim_root, monkeypatch):
    monkeypatch.setattr(Config, "SIM_PRIOR_ECHO_DIAGNOSTIC", True, raising=False)
    doc = _traj(PRIOR)
    block = _block(sim_root, doc)
    line = [ln for ln in block.split("\n") if ln.startswith("对照诊断")]
    assert len(line) == 1 and not re.search(r"\d", line[0])
    assert block.split("\n")[-2] == line[0]                  # right before the closing note
    # the share parser reads the same shares as without the caveat
    monkeypatch.setattr(Config, "SIM_PRIOR_ECHO_DIAGNOSTIC", False, raising=False)
    off = _block(sim_root, doc)
    assert world_state_outcome_from_signal_pack(block) == world_state_outcome_from_signal_pack(off)
    assert block.replace(line[0] + "\n", "") == off


def test_world_state_block_names_the_herd_leader(sim_root, monkeypatch):
    monkeypatch.setattr(Config, "SIM_PRIOR_ECHO_DIAGNOSTIC", True, raising=False)
    block = _block(sim_root, _traj({"A": 0.8, "B": 0.2}, decisions=_decisions("A")))
    assert "对照诊断：承诺绝大多数集中于先验领先情景「A」" in block


def test_world_state_block_is_unchanged_for_other_verdicts(sim_root, monkeypatch):
    for doc in (_traj({"A": 0.35, "B": 0.65}, decisions=_decisions("B")),     # divergent
                _traj(PRIOR, statuses=("committed",)),                       # inconclusive
                _traj(PRIOR, validity="inconclusive")):                      # hidden shares
        monkeypatch.setattr(Config, "SIM_PRIOR_ECHO_DIAGNOSTIC", True, raising=False)
        on = _block(sim_root, doc)
        monkeypatch.setattr(Config, "SIM_PRIOR_ECHO_DIAGNOSTIC", False, raising=False)
        assert on == _block(sim_root, doc) and "对照诊断" not in on


# ------------------------------------------------------------------ orchestrator
def test_decision_channel_summary_records_the_verdict_and_warns(sim_root, monkeypatch):
    sim = sim_root / "sim_log"
    sim.mkdir()
    (sim / "simulation_config.json").write_text(
        json.dumps({"world_state_seed": {"scenarios": ["A", "B"]}}), encoding="utf-8")
    (sim / "world_state_trajectory.json").write_text(json.dumps(_traj(PRIOR)), encoding="utf-8")
    monkeypatch.setattr(po.PipelineManager, "save", classmethod(lambda cls, state: None))
    warnings = []
    monkeypatch.setattr(po.logger, "warning", lambda msg, *a, **k: warnings.append(msg % a))
    monkeypatch.setattr(Config, "SIM_PRIOR_ECHO_DIAGNOSTIC", True, raising=False)
    state = po.PipelineState(pipeline_id="pipe_echo", prompt="q")
    orch = po.PipelineOrchestrator.__new__(po.PipelineOrchestrator)
    orch._log_decision_channel_outcome(state, "sim_log")
    echo = state.options["decision_channel_summary"]["prior_echo"]
    assert echo["verdict"] == "prior_echo" and echo["policy_version"] == "drf-sim-control/v1"
    assert any("先验回声诊断=prior_echo" in w for w in warnings)
    # knob off: not computed, no warning
    warnings.clear()
    monkeypatch.setattr(Config, "SIM_PRIOR_ECHO_DIAGNOSTIC", False, raising=False)
    state = po.PipelineState(pipeline_id="pipe_echo_off", prompt="q")
    orch._log_decision_channel_outcome(state, "sim_log")
    assert "prior_echo" not in state.options["decision_channel_summary"]
    assert not any("先验回声" in w for w in warnings)


def test_knob_defaults_on_and_is_documented():
    assert Config.SIM_PRIOR_ECHO_DIAGNOSTIC is True
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, ".env.example"), encoding="utf-8") as f:
        assert "# SIM_PRIOR_ECHO_DIAGNOSTIC=true" in f.read()


def test_finite_helper_rejects_bools_and_non_finite():
    assert spe._number(True) is None and spe._number(math.inf) is None and spe._number("2") == 2.0
