"""Foglamp WP1 — Immediate correctness containment (EXECPLAN_FOGLAMP §9).

Offline red tests for the five containment slices:

- 1A: no default simulation→observed-graph feedback (activity, typed edges,
      end-of-simulation interviews);
- 1B: compatibility safety-policy pin (safetyPolicyV1) at admission/resume;
- 1C: typed round validity — failure/silence/abstention/no-change/convergence
      are distinct states; invalid rounds cannot update WorldState or converge;
- 1D: diagnostic simulation policy — single-draw defaults, elicited-model-
      projection labeling, no simulation input into probability generation;
- 1E: golden-ledger isolation — evaluation rows never enter production
      calibration/recalibration.

Plus the I-15 containment: visibility (influence_weight) never becomes outcome
power.

All tests are deterministic and network-free (FakeLLMClient; conftest disables
prediction-market network).
"""

import json
import re

from app.config import Config
from app.services import decision_channel as dc
from app.services.decision_channel import run_decision_channel
from app.services.worldstate import (
    CONVERGENCE_POLICY_V1,
    ROUND_STATUS_ABSTAINED,
    ROUND_STATUS_FAILED,
    ROUND_STATUS_SILENT,
    WorldState,
)
from tests.conftest import FakeLLMClient

CONFIG_SRC = None


def _config_source() -> str:
    global CONFIG_SRC
    if CONFIG_SRC is None:
        import app.config as _cfgmod
        with open(_cfgmod.__file__, encoding="utf-8") as f:
            CONFIG_SRC = f.read()
    return CONFIG_SRC


class FailingLLM:
    """LLM stub whose every chat_json call raises (injected provider failure)."""

    def __init__(self):
        self.calls = 0

    def chat_json(self, *a, **k):
        self.calls += 1
        raise RuntimeError("injected decision-provider failure")


# =========================================================== 1A graph feedback
def test_default_observed_graph_feedback_is_off():
    """1A red test: default configuration cannot write activity, typed-edge, or
    interview feedback to the observed graph (I-11/I-12)."""
    src = _config_source()
    assert re.search(
        r"SIM_GRAPH_FEEDBACK\s*=\s*os\.environ\.get\('SIM_GRAPH_FEEDBACK',\s*'false'\)", src
    ), "SIM_GRAPH_FEEDBACK must default to 'false'"
    assert re.search(
        r"SIM_TYPED_FEEDBACK_EDGES\s*=\s*os\.environ\.get\('SIM_TYPED_FEEDBACK_EDGES',\s*'false'\)",
        src,
    ), "SIM_TYPED_FEEDBACK_EDGES must default to 'false'"
    assert re.search(
        r"'SIM_INTERVIEW_GRAPH_FEEDBACK',\s*'false'\)", src
    ), "SIM_INTERVIEW_GRAPH_FEEDBACK must exist and default to 'false'"


def test_interview_fact_write_refused_when_gated(monkeypatch):
    """1A: write_interview_fact refuses the observed graph when the interview
    gate is off (default), and writes only when explicitly enabled."""
    from app.services.zep_graph_memory_updater import ZepGraphMemoryUpdater

    class _FakeGraph:
        def __init__(self):
            self.triplets = []

        def add_triplet(self, *a, **k):
            self.triplets.append((a, k))

    class _FakeClient:
        def __init__(self):
            self.graph = _FakeGraph()

    stub = ZepGraphMemoryUpdater.__new__(ZepGraphMemoryUpdater)
    stub.graph_id = "g_test"
    stub.client = _FakeClient()

    monkeypatch.setattr(Config, "SIM_INTERVIEW_GRAPH_FEEDBACK", False, raising=False)
    assert stub.write_interview_fact("ActorA", "终局反思陈述") is False
    assert stub.client.graph.triplets == []

    monkeypatch.setattr(Config, "SIM_INTERVIEW_GRAPH_FEEDBACK", True, raising=False)
    assert stub.write_interview_fact("ActorA", "终局反思陈述") is True
    assert len(stub.client.graph.triplets) == 1


def test_typed_feedback_edges_gated(monkeypatch):
    """1A: typed feedback edges obey SIM_TYPED_FEEDBACK_EDGES (default off)."""
    from app.services.zep_graph_memory_updater import (
        AgentActivity,
        ZepGraphMemoryUpdater,
    )

    class _FakeGraph:
        def __init__(self):
            self.triplets = []

        def add_triplet(self, *a, **k):
            self.triplets.append((a, k))

    class _FakeClient:
        def __init__(self):
            self.graph = _FakeGraph()

    stub = ZepGraphMemoryUpdater.__new__(ZepGraphMemoryUpdater)
    stub.graph_id = "g_test"
    stub.client = _FakeClient()
    acts = [AgentActivity(platform="twitter", agent_id=1, agent_name="A",
                          action_type="FOLLOW",
                          action_args={"target_user_name": "B"},
                          round_num=1, timestamp="2026-07-17T00:00:00")]

    monkeypatch.setattr(Config, "SIM_TYPED_FEEDBACK_EDGES", False, raising=False)
    stub._write_typed_edges(acts)
    assert stub.client.graph.triplets == []

    monkeypatch.setattr(Config, "SIM_TYPED_FEEDBACK_EDGES", True, raising=False)
    stub._write_typed_edges(acts)
    assert len(stub.client.graph.triplets) == 1


# ======================================================= 1B safety-policy pin
def test_safety_policy_pinned_at_admission_shape():
    """1B: the admission snapshot captures every containment-relevant flag."""
    from app.services.pipeline_orchestrator import (
        SAFETY_POLICY_VERSION,
        capture_safety_policy_v1,
    )

    pol = capture_safety_policy_v1("admission")
    assert pol["version"] == SAFETY_POLICY_VERSION
    assert pol["origin"] == "admission"
    for key in ("sim_graph_feedback", "sim_typed_feedback_edges",
                "sim_interview_graph_feedback", "n_forecast_seeds",
                "report_spine_selfconsistency_k", "ensemble_extremize_a",
                "simulation_forecast_effect", "pinned_at"):
        assert key in pol, f"safetyPolicyV1 missing {key}"
    assert json.dumps(pol)  # snapshot must be JSON-serializable


def test_pinned_policy_beats_ambient_config(monkeypatch):
    """1B: a run keeps its pinned semantics even when ambient Config drifts —
    no run silently changes safety semantics on service reload."""
    from app.services.pipeline_orchestrator import PipelineOrchestrator, PipelineState

    state = PipelineState(pipeline_id="pipe_test", prompt="q")
    state.options["safety_policy_v1"] = {
        "version": "safety-policy/v1", "origin": "admission",
        "sim_graph_feedback": True, "n_forecast_seeds": 3,
    }
    monkeypatch.setattr(Config, "SIM_GRAPH_FEEDBACK", False, raising=False)
    assert PipelineOrchestrator._pinned_safety(
        state, "sim_graph_feedback", Config.SIM_GRAPH_FEEDBACK) is True
    assert PipelineOrchestrator._pinned_safety(state, "n_forecast_seeds", 1) == 3
    # missing key/pin → ambient (safe) default
    assert PipelineOrchestrator._pinned_safety(state, "unknown_key", "dflt") == "dflt"
    bare = PipelineState(pipeline_id="pipe_bare", prompt="q")
    assert PipelineOrchestrator._pinned_safety(bare, "sim_graph_feedback", False) is False


# ==================================================== 1C round validity states
def test_provider_failure_yields_invalid_no_update_not_converged():
    """1C red test: injected decision-provider failure ⇒ validity=invalid,
    forecast_effect=no_update, converged=false (I-16)."""
    actions = [{"round": r, "agent_id": 1, "agent_name": "A"} for r in range(1, 7)]
    res = run_decision_channel(
        actions, [{"agent_id": 1, "influence_weight": 1.0}],
        {"scenarios": ["S1", "S2"], "base_rates": {"S1": 0.5, "S2": 0.5}},
        FailingLLM(), inertia=0.5)
    assert res["validity"] == "invalid"
    assert res["forecast_effect"] == "no_update"
    assert res["outcome"]["converged"] is False
    assert res["converged_at"] is None
    acct = res["round_accounting"]
    assert acct["failed_rounds"] == 6 and acct["valid_transitions"] == 0
    assert all(t.get("round_status") == ROUND_STATUS_FAILED
               for t in res["trajectory"] if t["round"] >= 1)


def test_abstention_silence_failure_and_equilibrium_are_distinct():
    """1C red test: all-abstention, zero-valid (silent), forced failure, and a
    genuine equilibrium produce four different results (I-16)."""
    seed = {"scenarios": ["S1", "S2"], "base_rates": {"S1": 0.5, "S2": 0.5}}
    actions = [{"round": r, "agent_id": r, "agent_name": f"A{r}"} for r in range(1, 6)]
    cfgs = [{"agent_id": r, "influence_weight": 1.0} for r in range(1, 6)]

    # (a) explicit all-abstention: valid evidence of no-move → may converge
    abstain = FakeLLMClient(json_responses=[
        {"decisions": [{"agent_id": r, "scenario": dc.ABSTAIN_TOKEN}]} for r in range(1, 6)
    ])
    # concurrency=1 (SIM-2): FIFO fake replies must land on their own round's roster
    res_a = run_decision_channel(actions, cfgs, dict(seed), abstain, inertia=0.5,
                                 concurrency=1)
    assert res_a["round_accounting"]["counts"].get(ROUND_STATUS_ABSTAINED) == 5
    assert res_a["validity"] == "valid"

    # (b) silent (model answered, zero usable decisions): NOT stability evidence
    silent = FakeLLMClient(json_responses=[{"decisions": []} for _ in range(5)])
    res_b = run_decision_channel(actions, cfgs, dict(seed), silent, inertia=0.5)
    assert res_b["round_accounting"]["counts"].get(ROUND_STATUS_SILENT) == 5
    assert res_b["validity"] == "invalid"
    assert res_b["outcome"]["converged"] is False

    # (c) forced failure: distinct from both
    res_c = run_decision_channel(actions, cfgs, dict(seed), FailingLLM(), inertia=0.5)
    assert res_c["round_accounting"]["failed_rounds"] == 5
    assert res_c["validity"] == "invalid"

    # (d) genuine equilibrium: committed rounds, stable distribution → converged
    commit = FakeLLMClient(json_responses=[
        {"decisions": [{"agent_id": r, "scenario": "S1", "magnitude": 1,
                        "confidence": 1}]} for r in range(1, 6)
    ])
    res_d = run_decision_channel(actions, cfgs, dict(seed), commit, inertia=0.9,
                                 concurrency=1)
    assert res_d["validity"] == "valid"
    assert res_d["round_accounting"]["valid_transitions"] == 5
    # four distinct verdicts overall
    assert (res_a["round_accounting"]["counts"] != res_b["round_accounting"]["counts"]
            != res_c["round_accounting"]["counts"] != res_d["round_accounting"]["counts"])


def test_invalid_rounds_freeze_worldstate_and_never_decay_to_convergence():
    """1C: a dead channel can no longer decay the EWMA into convergence."""
    ws = WorldState(["A", "B"], base_rates={"A": 0.6, "B": 0.4})
    before = dict(ws.shares)
    for _ in range(40):
        ws.step([], round_status=ROUND_STATUS_FAILED)
    assert ws.shares == before
    assert ws.converged() is False
    assert ws.convergence_state() == "active"  # EWMA untouched → never settled
    acct = ws.round_accounting()
    assert acct["failed_rounds"] == 40 and acct["valid_transitions"] == 0


def test_settled_ewma_with_policy_violation_is_inconclusive():
    """1C: a settled EWMA that fails the frozen policy guards is
    ``inconclusive``, never ``converged`` (missing data ≠ equilibrium)."""
    ws = WorldState(["A", "B"], base_rates={"A": 0.5, "B": 0.5}, inertia=0.9)
    for _ in range(10):  # settle the EWMA with genuine commitments
        ws.step([{"scenario": "A", "magnitude": 1.0, "weight": 1.0},
                 {"scenario": "B", "magnitude": 1.0, "weight": 1.0}])
    assert ws.convergence_state() == "converged"
    ws.step([], round_status=ROUND_STATUS_FAILED)  # one provider failure
    assert ws.convergence_state() == "inconclusive"
    assert ws.converged() is False
    assert CONVERGENCE_POLICY_V1["max_failed_rounds"] == 0


def test_unexplained_empty_round_defaults_to_silent():
    """1C: legacy callers that pass empty commitments without a status get the
    conservative ``silent`` classification — not stability evidence."""
    ws = WorldState(["A", "B"], base_rates={"A": 0.6, "B": 0.4})
    ws.step([])
    assert ws.round_statuses == [ROUND_STATUS_SILENT]
    assert ws.convergence_state() != "converged"


# ================================================ I-15 visibility ≠ power
def test_unknown_outcome_power_gets_neutral_default_not_influence():
    """I-15: an actor without declared outcome_power commits with a
    declared-neutral 1.0 — never its visibility weight."""
    actions = [{"round": 1, "agent_id": 1, "agent_name": "Loud"}]
    cfgs = [{"agent_id": 1, "entity_name": "Loud", "influence_weight": 50.0}]
    fake = FakeLLMClient(json_responses=[
        {"decisions": [{"agent_id": 1, "scenario": "S1", "magnitude": 1, "confidence": 1}]}])
    res = run_decision_channel(actions, cfgs, {"scenarios": ["S1", "S2"]}, fake)
    d = res["decisions"][0]
    assert d.get("outcome_power") == 1.0, (
        "visibility (influence_weight=50) must not become outcome power")


# ============================================== 1D diagnostic simulation policy
def test_single_draw_and_identity_extremize_defaults():
    """1D red test: default new run uses one forecast seed, one spine draw, and
    identity extremization."""
    src = _config_source()
    assert re.search(r"'N_FORECAST_SEEDS',\s*'1'\)", src), "N_FORECAST_SEEDS default must be 1"
    assert re.search(r"'REPORT_SPINE_SELFCONSISTENCY_K',\s*'1'\)", src), (
        "REPORT_SPINE_SELFCONSISTENCY_K default must be 1")
    assert re.search(r"'ENSEMBLE_EXTREMIZE_A',\s*'1\.0'\)", src), (
        "ENSEMBLE_EXTREMIZE_A default must be identity 1.0")
    assert re.search(r"'SIMULATION_FORECAST_EFFECT',\s*'diagnostic_only'\)", src), (
        "SIMULATION_FORECAST_EFFECT must default to diagnostic_only")


def test_worldstate_labeled_elicited_model_projection():
    """1D red test: WorldState output is labeled elicited_model_projection in
    outcome and channel result (I-11)."""
    ws = WorldState(["A", "B"], base_rates={"A": 0.5, "B": 0.5})
    assert ws.outcome()["epistemic_status"] == "elicited_model_projection"
    fake = FakeLLMClient(json_responses=[
        {"decisions": [{"agent_id": 1, "scenario": "S1", "magnitude": 1, "confidence": 1}]}])
    res = run_decision_channel(
        [{"round": 1, "agent_id": 1, "agent_name": "A"}],
        [{"agent_id": 1}], {"scenarios": ["S1", "S2"]}, fake)
    assert res["epistemic_status"] == "elicited_model_projection"


def test_diagnostic_policy_keeps_sim_out_of_binary_probability_prompts(monkeypatch):
    """1D red test: under diagnostic_only (default) the simulation signal pack
    must NOT enter binary-probability extraction prompts; legacy_prompt (fixture
    characterization) restores the old inclusion."""
    from app.services import forecast_extractor as fe

    report_md = "# 报告\n\n结论：X 将在 2027 年发生。[S1]\n"
    signal_pack = "【推演结果分布 P(outcome)】\n· SCN-A: 60%\n· SCN-B: 40%"

    def _prompts(llm):
        return "\n".join(
            m.get("content", "") for c in llm.calls for m in c.get("messages", []))

    monkeypatch.setattr(Config, "FORECAST_SIM_SENSITIVITY", True, raising=False)
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "diagnostic_only",
                        raising=False)
    llm = FakeLLMClient(json_responses=[{"forecasts": []}] * 6)
    fe.extract_binary_forecasts(report_md, llm, min_count=1, signal_pack=signal_pack)
    assert "[Simulation quantitative signals]" not in _prompts(llm), (
        "diagnostic_only must keep simulation signals out of probability generation")

    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "legacy_prompt",
                        raising=False)
    llm2 = FakeLLMClient(json_responses=[{"forecasts": []}] * 6)
    fe.extract_binary_forecasts(report_md, llm2, min_count=1, signal_pack=signal_pack)
    assert "[Simulation quantitative signals]" in _prompts(llm2), (
        "legacy_prompt characterization must reproduce the pre-containment path")


def test_signal_pack_suppressed_under_no_update(monkeypatch):
    """1D: SIMULATION_FORECAST_EFFECT=no_update suppresses the whole signal
    pack (not even diagnostic prose)."""
    from app.services.report_agent import ReportAgent

    agent = ReportAgent.__new__(ReportAgent)
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "no_update", raising=False)
    assert agent._build_signal_pack() == ""


def test_signal_pack_header_requires_provenance_and_forbids_probability(monkeypatch):
    """1D red test: the pack header must require explicit simulation provenance
    and forbid probability authorship — the old header instructed transcribing
    simulation output into unlabeled real-world judgments."""
    import inspect

    from app.services import report_agent as ra

    src = inspect.getsource(ra.ReportAgent._build_signal_pack)
    assert "elicited model projection" in src
    assert "严禁依据本材料给出、调整或佐证任何结果概率数字" in src
    assert "显式标注来源为内部情景推演" in src
    # the laundering instruction is gone
    assert "绝不进入正文表述" not in src


# ================================================== 1E golden-ledger isolation
def test_golden_rows_never_enter_production_ledger(tmp_path, monkeypatch):
    """1E red test: append_golden_result targeting the production dir is
    redirected to the isolated evaluation ledger."""
    from app.services import forecast_ledger as fl

    prod = tmp_path / "_forecast_ledger"
    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(prod), raising=False)
    entry = fl.append_golden_result(
        question_id="q1", probability=0.8, resolved_outcome=True,
        question="Did X happen?", category="test")
    assert entry is not None and entry["ledger_redirected"] == "evaluation"
    assert entry["record_class"] == "evaluation"
    assert entry["characterization_only"] is True
    assert not (prod / "ledger.jsonl").exists(), (
        "production ledger.jsonl must not receive golden rows")
    eval_file = tmp_path / "_evaluation_ledger" / "ledger.jsonl"
    assert eval_file.exists() and "q1" in eval_file.read_text(encoding="utf-8")


def test_production_calibration_excludes_golden_and_characterization_rows():
    """1E red test: calibration_summary and recalibration_param exclude
    golden/characterization/evaluation rows by record type, including
    historical mixed-ledger rows (I-21)."""
    from app.services import forecast_ledger as fl

    prod_row = {
        "report_id": "r1", "resolved": True, "outcome": "YES",
        "scenarios": [{"name": "YES", "probability": 0.9},
                      {"name": "NO", "probability": 0.1}],
    }
    golden_row = dict(prod_row, report_id="golden:q1", golden=True)
    char_row = dict(prod_row, report_id="r2", characterization_only=True)
    eval_row = dict(prod_row, report_id="r3", record_class="evaluation")

    mixed = [prod_row, golden_row, char_row, eval_row]
    summary = fl.calibration_summary(entries=mixed)
    assert summary["n_resolved"] == 1, "only the production row may count"
    # the recalibrator fit over the mixed ledger must equal the fit over the
    # production-only subset — evaluation rows contribute zero labels
    assert (fl.recalibration_param(entries=mixed)
            == fl.recalibration_param(entries=[prod_row]))


def test_golden_eval_fixture_is_answer_bearing_characterization_only():
    """1E characterization: the historical golden fixture carries outcomes
    inline (answer-bearing) — it may never drive production calibration or
    promotion (I-21). WP14 owns the sealed, outcome-isolated replacement."""
    import os
    fixture = os.path.join(os.path.dirname(__file__), "eval", "golden_questions.json")
    with open(fixture, encoding="utf-8") as f:
        data = json.load(f)
    questions = data.get("questions") if isinstance(data, dict) else data
    assert questions and any("resolved_outcome" in q for q in questions), (
        "fixture is expected to be answer-bearing (characterization of the leak)")
