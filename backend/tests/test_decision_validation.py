"""SIM-2 (C26): roster-bound decision validation (``services.decision_validation``).

Pins the pure validator's reason-coded accounting (unknown ids, duplicates, id
canonicalisation, magnitude/confidence parsing and clamping, scenario
normalisation, abstention, missing actors), the run-level ``summarize_validation``
fallback share, the fail-closed elicitation path, the knobs, and the orchestrator
summary fields. Offline and deterministic (no LLM, no network).
"""

import ast
import copy
import json
import os

import pytest

from app.config import Config
from app.services import decision_channel as dc
from app.services import decision_validation as dv
from app.services.decision_validation import (
    DECISION_VALIDATION_POLICY_V1,
    summarize_validation,
    validate_round_decisions,
)
from tests.conftest import FakeLLMClient

_ROSTER = [{"agent_id": 1}, {"agent_id": 2}, {"agent_id": 3}]
_SCENARIOS = ["S1", "S2"]
_ABSTAIN = "弃权"


def _validate(decisions, roster=None, scenarios=None):
    return validate_round_decisions(
        decisions, _ROSTER if roster is None else roster,
        _SCENARIOS if scenarios is None else scenarios, abstain_token=_ABSTAIN)


def _row(agent_id, scenario="S1", magnitude=1, confidence=1):
    return {"agent_id": agent_id, "scenario": scenario, "magnitude": magnitude,
            "confidence": confidence}


# ------------------------------------------------------------------ id handling
def test_unknown_id_and_duplicate_are_rejected_first_entry_wins():
    out = _validate([_row(999, "S2"), _row(1, "S1"), _row(1, "S2")])
    rec = out["record"]
    assert [r["agent_id"] for r in out["accepted"]] == [1]
    assert out["accepted"][0]["scenario"] == "S1"          # the first entry for id 1 is kept
    assert rec["reasons"]["unknown_agent"] == 1
    assert rec["reasons"]["duplicate"] == 1
    assert rec["rejected"] == 2 and rec["answered"] == 3
    assert {"agent_id": "999", "reason": "unknown_agent"} in rec["rejected_samples"]
    assert {"agent_id": "1", "reason": "duplicate"} in rec["rejected_samples"]
    assert "999" not in rec["roster_agent_ids"]            # never a roster slot


def test_string_ids_map_to_canonical_roster_ids():
    out = _validate([_row("1"), _row("id=2", "S2"), _row(" ID= 3 ", "S2")])
    assert [r["agent_id"] for r in out["accepted"]] == [1, 2, 3]
    assert all(isinstance(r["agent_id"], int) for r in out["accepted"])
    assert out["record"]["normalized"]["id_coerced"] == 3
    single = _validate([_row("1")])
    assert single["accepted"][0]["agent_id"] == 1
    assert single["record"]["normalized"]["id_coerced"] == 1


def test_integral_float_ids_map_to_canonical_roster_ids():
    out = _validate([_row(1.0), _row(2.5, "S2"), _row(float("nan"), "S2")])
    assert out["accepted"] == [{"agent_id": 1, "scenario": "S1", "magnitude": 1.0,
                                "confidence": 1.0}]
    assert isinstance(out["accepted"][0]["agent_id"], int)
    assert out["record"]["normalized"]["id_coerced"] == 1
    assert out["record"]["reasons"]["unknown_agent"] == 2      # 2.5 and NaN are not ids
    float_roster = _validate([_row(3), _row(4.0, "S2")],
                             roster=[{"agent_id": 3.0}, {"agent_id": 4}])
    assert [type(r["agent_id"]) for r in float_roster["accepted"]] == [float, int]  # roster's own
    assert float_roster["record"]["normalized"]["id_coerced"] == 2
    assert float_roster["record"]["roster_agent_ids"] == ["3", "4"]


def test_string_roster_id_and_public_block_resolve():
    roster = [{"agent_id": 5}, {"agent_id": dc.PUBLIC_BLOCK_ID}]
    out = _validate([_row("__public__", "S2"), _row(5)], roster=roster)
    assert [r["agent_id"] for r in out["accepted"]] == [dc.PUBLIC_BLOCK_ID, 5]
    assert out["record"]["normalized"]["id_coerced"] == 0   # exact types: no coercion
    assert out["record"]["roster_agent_ids"] == ["5", "__public__"]


def test_malformed_entries_and_missing_ids_are_rejected():
    out = _validate(["1: S1", None, {"scenario": "S1", "magnitude": 1}])
    rec = out["record"]
    assert out["accepted"] == [] and out["round_status"] == "silent"
    assert rec["reasons"]["malformed_entry"] == 2
    assert rec["reasons"]["unknown_agent"] == 1             # agent_id absent → 'None'
    assert rec["rejected_samples"][0] == {"agent_id": "'1: S1'", "reason": "malformed_entry"}


# -------------------------------------------------------------------- magnitude
def test_magnitude_above_one_is_clamped():
    out = _validate([_row(1, magnitude=7)])
    assert out["accepted"][0]["magnitude"] == 1.0
    assert out["record"]["normalized"]["clamped"] == 1
    neg = _validate([_row(1, magnitude=-0.5, confidence=3)])
    assert neg["accepted"][0]["magnitude"] == 0.0 and neg["accepted"][0]["confidence"] == 1.0
    assert neg["record"]["normalized"]["clamped"] == 2      # counted per clamped field


@pytest.mark.parametrize("missing", [{}, {"magnitude": None}])
def test_missing_magnitude_is_rejected_not_defaulted_to_one(missing):
    row = {"agent_id": 1, "scenario": "S1", "confidence": 1, **missing}
    out = _validate([row])
    assert out["accepted"] == []
    assert out["record"]["reasons"]["missing_magnitude"] == 1


@pytest.mark.parametrize("bad", ["inf", "-inf", float("inf"), float("nan"), "nan", True,
                                 False, "high", "", [1], {"v": 1}, 10 ** 400])
def test_non_numeric_or_non_finite_magnitude_is_rejected(bad):
    out = _validate([_row(1, magnitude=bad)])
    assert out["accepted"] == []
    assert out["record"]["reasons"]["non_numeric"] == 1
    assert out["round_status"] == "silent"


def test_numeric_strings_are_parsed():
    out = _validate([_row(1, magnitude=" 0.25 ", confidence="0.5")])
    assert (out["accepted"][0]["magnitude"], out["accepted"][0]["confidence"]) == (0.25, 0.5)
    assert out["record"]["normalized"] == {"clamped": 0, "confidence_defaulted": 0,
                                           "id_coerced": 0, "scenario_normalized": 0}


# ------------------------------------------------------------ confidence/scenario
def test_missing_confidence_defaults_and_is_counted():
    out = _validate([{"agent_id": 1, "scenario": "S1", "magnitude": 0.5}])
    assert out["accepted"][0]["confidence"] == DECISION_VALIDATION_POLICY_V1[
        "default_confidence"] == 0.7
    assert out["record"]["normalized"]["confidence_defaulted"] == 1


@pytest.mark.parametrize("bad", [float("nan"), "-inf", False, "sure"])
def test_non_numeric_confidence_is_rejected(bad):
    out = _validate([_row(1, confidence=bad)])
    assert out["accepted"] == [] and out["record"]["reasons"]["non_numeric"] == 1
    assert out["record"]["normalized"]["clamped"] == 0    # rejected rows count no repair


@pytest.mark.parametrize("variant", ["“S1”", " s1 ", "「S1」", "（s1）", "【S1】", "'S1'", "Ｓ１",
                                     "‘S1’", "《S1》"])
def test_scenario_normalised_when_unique(variant):
    out = _validate([_row(1, variant)])
    assert out["accepted"][0]["scenario"] == "S1"
    assert out["record"]["normalized"]["scenario_normalized"] == 1


def test_exact_scenario_match_needs_no_normalisation():
    out = _validate([_row(1, " S2 ")])  # surrounding whitespace is stripped first
    assert out["accepted"][0]["scenario"] == "S2"
    assert out["record"]["normalized"]["scenario_normalized"] == 0


def test_ambiguous_or_unknown_scenario_is_rejected():
    out = _validate([_row(1, "“s1”"), _row(2, "BOGUS"), _row(3, "")],
                    scenarios=["S1", "s1"])
    assert out["accepted"] == []
    assert out["record"]["reasons"]["invalid_scenario"] == 3
    exact = _validate([_row(1, "s1")], scenarios=["S1", "s1"])
    assert exact["accepted"][0]["scenario"] == "s1"        # exact match wins over ambiguity


# ------------------------------------------------------------ abstention/status
def test_abstention_and_missing_actor_accounting():
    out = _validate([{"agent_id": 1, "scenario": _ABSTAIN},
                     {"agent_id": "2", "scenario": f" “{_ABSTAIN}” ", "magnitude": "x"}])
    rec = out["record"]
    assert out["round_status"] == "abstained"
    assert out["abstained_ids"] == [1, 2]
    assert rec["abstained_agent_ids"] == ["1", "2"]       # magnitude ignored when abstaining
    assert rec["abstained"] == 2 and rec["accepted"] == 0 and rec["rejected"] == 0
    assert rec["normalized"]["id_coerced"] == 1
    assert rec["normalized"]["scenario_normalized"] == 1
    assert rec["missing_from_reply"] == 1 and rec["missing_agent_ids"] == ["3"]
    assert rec["fallback_slots"] == 1


def test_fallback_slots_count_rejected_and_missing_roster_actors():
    out = _validate([_row(1), _row(2, "BOGUS")])
    rec = out["record"]
    assert out["round_status"] == "committed"
    assert rec["missing_from_reply"] == 1                  # id 3 named by no element
    assert rec["fallback_slots"] == 2                      # id 2 (rejected) + id 3 (missing)
    assert rec["roster_size"] == 3
    assert rec["accepted"] + rec["abstained"] + rec["rejected"] == rec["answered"]


def test_all_invalid_reply_is_silent_never_infeasible():
    out = _validate([_row(999), _row(1, "BOGUS"), _row(2, magnitude="inf")])
    assert out["round_status"] == "silent"
    assert out["round_status"] != "infeasible"
    assert out["record"]["fallback_slots"] == 3
    assert _validate([])["round_status"] == "silent"


def test_record_shape_and_determinism():
    reply = [_row(999, "S2"), _row("1"), _row(1, "S2"), _row(2, magnitude=7),
             {"agent_id": 3, "scenario": _ABSTAIN}]
    first = _validate(copy.deepcopy(reply))
    second = _validate(copy.deepcopy(reply))
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    rec = first["record"]
    assert set(rec) == {
        "measured", "roster_size", "answered", "accepted", "abstained", "rejected",
        "missing_from_reply", "fallback_slots", "reasons", "normalized", "roster_agent_ids",
        "abstained_agent_ids", "missing_agent_ids", "rejected_samples"}
    assert rec["measured"] is True
    assert list(rec["reasons"]) == sorted(rec["reasons"])
    assert set(rec["reasons"]) == {"malformed_entry", "unknown_agent", "duplicate",
                                   "invalid_scenario", "missing_magnitude", "non_numeric"}
    assert list(rec["normalized"]) == sorted(rec["normalized"])
    assert rec["roster_agent_ids"] == ["1", "2", "3"]
    assert first["accepted"] == [
        {"agent_id": 1, "scenario": "S1", "magnitude": 1.0, "confidence": 1.0},
        {"agent_id": 2, "scenario": "S1", "magnitude": 1.0, "confidence": 1.0}]


def test_rejected_samples_are_capped():
    out = _validate([_row(1000 + i) for i in range(25)])
    rec = out["record"]
    assert rec["reasons"]["unknown_agent"] == 25
    assert len(rec["rejected_samples"]) == DECISION_VALIDATION_POLICY_V1[
        "max_rejected_samples"] == 10
    long_id = "x" * 200
    assert len(_validate([_row(long_id)])["record"]["rejected_samples"][0]["agent_id"]) == 40


# ------------------------------------------------------------ summarize_validation
def test_summarize_validation_fallback_share():
    recs = [_validate([_row(1)])["record"],                        # 3 slots, 2 fallback
            _validate([_row(1), _row(2), _row(3, _ABSTAIN)])["record"]]  # 3 slots, 0 fallback
    summary = summarize_validation(recs, unmeasured_rounds=1)
    assert summary["slots"] == 6 and summary["fallback_slots"] == 2
    assert summary["fallback_share"] == round(2 / 6, 6)
    assert summary["measured_rounds"] == 2 and summary["unmeasured_rounds"] == 1
    assert summary["accepted"] == 3 and summary["abstained"] == 1
    assert summary["missing_from_reply"] == 2
    assert summary["policy_version"] == "drf-decision-validation/v1"
    assert list(summary) == sorted(summary)
    assert set(summary) == {
        "policy_version", "measured_rounds", "unmeasured_rounds", "slots", "fallback_slots",
        "fallback_share", "accepted", "abstained", "rejected", "missing_from_reply",
        "reasons", "normalized"}
    assert summarize_validation(copy.deepcopy(recs), unmeasured_rounds=1) == summary


def test_summarize_validation_none_when_no_slots():
    summary = summarize_validation([])
    assert summary["slots"] == 0 and summary["fallback_share"] is None
    failed_only = summarize_validation([{"measured": False}, {"measured": False}],
                                       unmeasured_rounds=1)
    assert failed_only["fallback_share"] is None
    assert failed_only["measured_rounds"] == 0 and failed_only["unmeasured_rounds"] == 3


def test_summarize_merges_reason_counts():
    recs = [_validate([_row(999), _row(1, magnitude=7)])["record"],
            _validate([_row(999), _row(1, "S1"), _row(1, "S2")])["record"]]
    summary = summarize_validation(recs)
    assert summary["reasons"]["unknown_agent"] == 2
    assert summary["reasons"]["duplicate"] == 1
    assert summary["normalized"]["clamped"] == 1
    assert summary["rejected"] == 3


# ------------------------------------------------------- elicitation fail-closed
def test_failed_call_and_bad_payload_are_unmeasured():
    class _Boom:
        def chat_json(self, *a, **k):
            raise RuntimeError("transport down")

    report = {}
    assert dc._elicit_round_decisions(_Boom(), _SCENARIOS, _ROSTER, 1, report=report) == (
        [], "failed")
    assert report == {"measured": False}
    report = {}
    fake = FakeLLMClient(json_responses=[{"decisions": "S1"}])
    assert dc._elicit_round_decisions(fake, _SCENARIOS, _ROSTER, 1, report=report) == (
        [], "failed")
    assert report == {"measured": False}


def test_validator_crash_fails_closed(monkeypatch):
    def _crash(*a, **k):
        raise RuntimeError("validator bug")

    monkeypatch.setattr(dc, "validate_round_decisions", _crash)
    fake = FakeLLMClient(json_responses=[{"decisions": [_row(1)]}])
    report = {}
    decisions, status = dc._elicit_round_decisions(fake, _SCENARIOS, _ROSTER, 1, report=report)
    assert (decisions, status) == ([], "failed")           # an unvalidated reply never votes
    assert report == {"measured": False}


def test_failed_rounds_record_unmeasured_on_trajectory():
    class _Boom:
        def chat_json(self, *a, **k):
            raise RuntimeError("transport down")

    res = dc.run_decision_channel(
        [{"round": r, "agent_id": 1} for r in (1, 2)], [{"agent_id": 1}],
        {"scenarios": _SCENARIOS}, _Boom(), concurrency=1)
    assert all(t["decision_validation"] == {"measured": False}
               for t in res["trajectory"] if t["round"] >= 1)
    assert res["decision_validation"]["measured_rounds"] == 0
    assert res["decision_validation"]["unmeasured_rounds"] == 2
    assert res["decision_validation"]["fallback_share"] is None
    assert res["validity"] == "invalid" and res["validity_reasons"] == ["no_valid_rounds"]


# -------------------------------------------------------------- module/knobs
def test_module_imports_only_stdlib_and_worldstate():
    with open(dv.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add("." * node.level + (node.module or ""))
    assert imported == {"__future__", "math", "unicodedata", "typing", ".worldstate"}


def test_knobs_defined_and_documented():
    import app.config as cfgmod
    for name in ("DECISION_CHANNEL_VALIDATION", "DECISION_CHANNEL_FALLBACK_MAX_SHARE",
                 "DECISION_CHANNEL_MAX_ACTIVE"):
        assert name in vars(Config), name      # defined on Config, not a getattr ghost
    assert isinstance(Config.DECISION_CHANNEL_VALIDATION, bool)
    assert isinstance(Config.DECISION_CHANNEL_FALLBACK_MAX_SHARE, float)
    assert isinstance(Config.DECISION_CHANNEL_MAX_ACTIVE, int)
    with open(cfgmod.__file__, encoding="utf-8") as f:
        src = f.read()
    assert ("DECISION_CHANNEL_VALIDATION = os.environ.get(\n"
            "        'DECISION_CHANNEL_VALIDATION', 'true').strip().lower() == 'true'") in src
    assert "os.environ.get('DECISION_CHANNEL_FALLBACK_MAX_SHARE', '0.5') or '0.5')" in src
    assert "os.environ.get('DECISION_CHANNEL_MAX_ACTIVE', '60') or '60')" in src
    env_example = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(cfgmod.__file__)))), ".env.example")
    with open(env_example, encoding="utf-8") as f:
        text = f.read()
    for line in ("# DECISION_CHANNEL_VALIDATION=true", "# DECISION_CHANNEL_FALLBACK_MAX_SHARE=0.5",
                 "# DECISION_CHANNEL_MAX_ACTIVE=60"):
        assert line in text


# ------------------------------------------------------- orchestrator summary
def test_orchestrator_summary_carries_fallback_share(tmp_path, monkeypatch):
    from app.services import pipeline_orchestrator as po

    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(po.PipelineManager, "save", classmethod(lambda cls, state: None))
    sim = tmp_path / "sim_dv"
    sim.mkdir()
    (sim / "simulation_config.json").write_text(
        json.dumps({"world_state_seed": {"scenarios": ["A", "B"]}}), encoding="utf-8")
    traj = {"trajectory": [{"round": 0}], "outcome": {"leader": "A", "shares": {"A": 1.0}},
            "validity": "inconclusive", "validity_reasons": ["fallback_share_exceeded"],
            "forecast_effect": "no_update",
            "decision_validation": {"fallback_share": 0.75, "measured_rounds": 5}}
    (sim / "world_state_trajectory.json").write_text(json.dumps(traj), encoding="utf-8")
    orch = po.PipelineOrchestrator.__new__(po.PipelineOrchestrator)

    state = po.PipelineState(pipeline_id="pipe_sim2", prompt="q")
    orch._log_decision_channel_outcome(state, "sim_dv")
    summary = state.options["decision_channel_summary"]
    assert summary["fallback_share"] == 0.75
    assert summary["decision_validation_measured_rounds"] == 5
    assert summary["validity_reasons"] == ["fallback_share_exceeded"]

    del traj["decision_validation"]
    (sim / "world_state_trajectory.json").write_text(json.dumps(traj), encoding="utf-8")
    state = po.PipelineState(pipeline_id="pipe_sim2b", prompt="q")
    orch._log_decision_channel_outcome(state, "sim_dv")
    summary = state.options["decision_channel_summary"]
    assert summary["fallback_share"] is None
    assert summary["decision_validation_measured_rounds"] is None


def test_policy_is_not_mutated_by_use():
    before = copy.deepcopy(DECISION_VALIDATION_POLICY_V1)
    _validate([_row(1000 + i) for i in range(12)])
    summarize_validation([_validate([_row(1)])["record"]])
    assert DECISION_VALIDATION_POLICY_V1 == before
