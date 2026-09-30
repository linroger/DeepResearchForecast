"""NEXTSTEPS P1-1 integration: decision-channel orchestration (offline, fake LLM)."""

import copy
import hashlib
import json
import logging

import pytest

from app.config import Config
from app.services import decision_channel as dc
from app.services.decision_channel import (
    PUBLIC_BLOCK_ID,
    _activation_weight_map,
    _build_active_roster,
    _build_round_decision_prompt,
    _elicit_round_decisions,
    _inertia_for_gap,
    _outcome_power_map,
    run_decision_channel,
)
from tests.conftest import FakeLLMClient


def test_run_decision_channel_evolves_outcome():
    actions = [
        {"round": 1, "agent_id": 1, "agent_name": "A"},
        {"round": 1, "agent_id": 2, "agent_name": "B"},
        {"round": 2, "agent_id": 1, "agent_name": "A"},
    ]
    agent_configs = [
        {"agent_id": 1, "entity_name": "A", "stance": "pro", "influence_weight": 3.0},
        {"agent_id": 2, "entity_name": "B", "stance": "con", "influence_weight": 1.0},
    ]
    seed = {"scenarios": ["S1", "S2"], "base_rates": {"S1": 0.5, "S2": 0.5}}
    fake = FakeLLMClient(json_responses=[
        {"decisions": [{"agent_id": 1, "scenario": "S1", "magnitude": 1, "confidence": 1},
                       {"agent_id": 2, "scenario": "S1", "magnitude": 1, "confidence": 1}]},
        {"decisions": [{"agent_id": 1, "scenario": "S1", "magnitude": 1, "confidence": 1}]},
    ])
    # concurrency=1: FakeLLMClient pops replies FIFO, and roster-bound validation (SIM-2)
    # rejects a reply that a thread pool delivered to another round's roster.
    res = run_decision_channel(actions, agent_configs, seed, fake, inertia=0.5, concurrency=1)
    assert res["outcome"]["leader"] == "S1"         # evolved toward the committed scenario
    assert res["outcome"]["shares"]["S1"] > 0.5
    assert res["n_rounds"] == 2
    assert len(res["trajectory"]) == 3              # round 0 (seed) + rounds 1, 2
    assert len(fake.calls) == 2                      # exactly one batched call per round


def test_decision_channel_empty_seed_is_noop():
    assert run_decision_channel([], None, {}, FakeLLMClient()) == {}
    assert run_decision_channel([], None, {"scenarios": []}, FakeLLMClient()) == {}


def test_elicit_round_filters_invalid_scenarios():
    fake = FakeLLMClient(json_responses=[
        {"decisions": [{"agent_id": 1, "scenario": "S1", "magnitude": 1, "confidence": 1},
                       {"agent_id": 2, "scenario": "BOGUS", "magnitude": 1, "confidence": 1}]},
    ])
    out, status = _elicit_round_decisions(
        fake, ["S1", "S2"], [{"agent_id": 1}, {"agent_id": 2}], 1)
    assert len(out) == 1 and out[0]["scenario"] == "S1"   # invalid scenario dropped
    assert status == "committed"                          # Foglamp 1C: typed round status


def test_round_to_date_stamps_trajectory():
    actions = [{"round": 1, "agent_id": 1, "agent_name": "A"}]
    fake = FakeLLMClient(json_responses=[
        {"decisions": [{"agent_id": 1, "scenario": "S1", "magnitude": 1, "confidence": 1}]}])
    res = run_decision_channel(actions, [{"agent_id": 1}], {"scenarios": ["S1", "S2"]}, fake,
                               round_to_date=lambda r: f"2027-{r:02d}-01")
    snap = [t for t in res["trajectory"] if t["round"] == 1][0]
    assert snap["as_of"] == "2027-01-01"             # P1-2: round stamped with mapped date


# --------------------------------------------------------------- SIM-5 / R2-EXEC-10
def test_power_sort_and_public_block_collapse():
    """SIM-5 + R2-EXEC-10: top-``cap`` by activation kept individually; the tail is
    collapsed into ONE public block whose outcome power sums the tail (never dropped)."""
    entries = [{"agent_id": 1, "influence": 1.0}, {"agent_id": 2, "influence": 5.0},
               {"agent_id": 3, "influence": 2.0}]
    act = {1: 1.0, 2: 5.0, 3: 2.0}
    roster = _build_active_roster(entries, act, act, cap=1)
    assert len(roster) == 2
    assert roster[0]["agent_id"] == 2                 # loudest kept individually
    assert roster[1]["agent_id"] == PUBLIC_BLOCK_ID
    assert roster[1]["outcome_power"] == 1.0 + 2.0    # tail power aggregated, not lost


def test_roster_cache_dedupes_identical_rosters():
    """R2-EXEC-10: a stable roster across rounds reuses one elicitation (one LLM call)."""
    actions = [{"round": 1, "agent_id": 1}, {"round": 2, "agent_id": 1},
               {"round": 3, "agent_id": 1}]
    fake = FakeLLMClient(json_responses=[
        {"decisions": [{"agent_id": 1, "scenario": "S1", "magnitude": 1, "confidence": 1}]}])
    res = run_decision_channel(actions, [{"agent_id": 1, "influence_weight": 1.0}],
                               {"scenarios": ["S1", "S2"]}, fake)
    assert len(fake.calls) == 1                       # 3 identical rosters → 1 cached call
    assert res["n_rounds"] == 3 and len(res["trajectory"]) == 4


# ------------------------------------------------------------ R2-SIM-2 + Foglamp I-15
def test_outcome_power_distinct_from_influence():
    """Foglamp WP1 (I-15): visibility never defaults to outcome power. An actor
    without an explicit ``outcome_power`` is UNKNOWN (absent from the power map)
    and receives a declared-neutral 1.0 in the roster — never its
    ``influence_weight``. The pre-containment fallback (unknown → influence 5.0)
    let media prominence become institutional power by construction."""
    cfgs = [{"agent_id": 1, "influence_weight": 1.0, "outcome_power": 9.0},
            {"agent_id": 2, "influence_weight": 5.0}]   # no outcome_power → UNKNOWN
    assert _activation_weight_map(cfgs) == {1: 1.0, 2: 5.0}
    assert _outcome_power_map(cfgs) == {1: 9.0}          # I-15: no visibility fallback
    roster = _build_active_roster(
        [{"agent_id": 1, "influence": 1.0}, {"agent_id": 2, "influence": 5.0}],
        _activation_weight_map(cfgs), _outcome_power_map(cfgs), cap=10)
    by_id = {e["agent_id"]: e for e in roster}
    assert by_id[1]["outcome_power"] == 9.0 and by_id[1]["outcome_power_known"] is True
    assert by_id[2]["outcome_power"] == 1.0 and by_id[2]["outcome_power_known"] is False


# ------------------------------------------------------------------------ R2-SIM-1/3
def test_prompt_injects_base_shares_incentives_and_abstention():
    active = [{"agent_id": 1, "name": "A", "stance": "pro",
               "gains_if": "稳价", "loses_if": "失份额", "affect": "情绪亢奋",
               "post": "我支持"}]
    prompt = _build_round_decision_prompt(["S1", "S2"], active, 1, None,
                                          base_shares={"S1": 0.6, "S2": 0.4})
    assert "基线分布" in prompt and "S1=60%" in prompt   # R2-SIM-1 base distribution
    assert "稳价" in prompt and "失份额" in prompt        # R2-SIM-3 incentives
    assert "情绪亢奋" in prompt and "我支持" in prompt     # R2-SIM-1 affect + post
    assert dc.ABSTAIN_TOKEN in prompt                    # abstention offered
    p2 = _build_round_decision_prompt(["S1", "S2"], active, 1, None, abstain_allowed=False)
    assert dc.ABSTAIN_TOKEN not in p2


# ------------------------------------------------------------------------ R2-SIM-12
def test_calendar_scaled_inertia():
    assert _inertia_for_gap(0.7, None, None, 10) is None            # no dates → base
    assert abs(_inertia_for_gap(0.7, "2027-01-01", "2027-01-11", 10) - 0.7) < 1e-9
    assert abs(_inertia_for_gap(0.7, "2027-01-01", "2027-01-21", 10) - 0.7 ** 2) < 1e-9
    assert _inertia_for_gap(0.7, "2027-01-01", "2027-01-02", 10) == 0.95  # clamp high


# --------------------------------------------------------------------------- SIM-1
def test_windowed_convergence(monkeypatch):
    """SIM-1: convergence requires SIM_CONVERGENCE_WINDOW stable rounds before settling."""
    from app import config as cfgmod
    monkeypatch.setattr(cfgmod.Config, "SIM_CONVERGENCE_WINDOW", 3, raising=False)
    actions = [{"round": r, "agent_id": 1} for r in range(1, 8)]
    fake = FakeLLMClient(json_responses=[
        {"decisions": [{"agent_id": 1, "scenario": "S1", "magnitude": 1, "confidence": 1}]}])
    res = run_decision_channel(actions, [{"agent_id": 1, "influence_weight": 1.0}],
                               {"scenarios": ["S1", "S2"], "base_rates": {"S1": 0.5, "S2": 0.5}},
                               fake, inertia=0.5)
    ca = res["converged_at"]
    assert ca is None or ca >= 3                        # never before the window fills


# --------------------------------------------------------------------------- SIM-2
def _one_round(reply):
    """One replayed round for actors 1 and 2 (outcome power 1.0 and 3.0)."""
    actions = [{"round": 1, "agent_id": 1, "agent_name": "A"},
               {"round": 1, "agent_id": 2, "agent_name": "B"}]
    cfgs = [
        {"agent_id": 1, "entity_name": "A", "influence_weight": 2.0, "outcome_power": 1.0},
        {"agent_id": 2, "entity_name": "B", "influence_weight": 1.0, "outcome_power": 3.0}]
    return run_decision_channel(actions, cfgs, {"scenarios": ["S1", "S2"],
                                                "base_rates": {"S1": 0.5, "S2": 0.5}},
                                FakeLLMClient(json_responses=[reply]), inertia=0.5,
                                concurrency=1)


def test_hallucinated_duplicate_and_inflated_rows_add_no_weight():
    """SIM-2: an out-of-roster id, a duplicate row, a string id and magnitude 7 move
    WorldState exactly as the equivalent clean reply; every repair is reason-coded."""
    clean = _one_round({"decisions": [
        {"agent_id": 1, "scenario": "S1", "magnitude": 1, "confidence": 1},
        {"agent_id": 2, "scenario": "S2", "magnitude": 1, "confidence": 1}]})
    messy = _one_round({"decisions": [
        {"agent_id": 1, "scenario": "S1", "magnitude": 1, "confidence": 1},
        {"agent_id": 999, "scenario": "S2", "magnitude": 1, "confidence": 1},
        {"agent_id": 1, "scenario": "S2", "magnitude": 1, "confidence": 1},
        {"agent_id": "2", "scenario": "S2", "magnitude": 7, "confidence": 1}]})
    assert messy["outcome"]["shares"] == clean["outcome"]["shares"]
    assert [t["shares"] for t in messy["trajectory"]] == [t["shares"] for t in clean["trajectory"]]
    # the string id kept its actor's outcome power (canonical roster id → pmap hit)
    assert [(d["agent_id"], d["outcome_power"]) for d in messy["decisions"]] == [(1, 1.0), (2, 3.0)]
    rec = messy["trajectory"][1]["decision_validation"]
    assert rec["reasons"]["unknown_agent"] == 1 and rec["reasons"]["duplicate"] == 1
    assert rec["normalized"]["id_coerced"] == 1 and rec["normalized"]["clamped"] == 1
    assert rec["roster_agent_ids"] == ["1", "2"] and rec["fallback_slots"] == 0
    assert clean["trajectory"][1]["decision_validation"]["rejected"] == 0
    assert messy["decision_validation"]["measured_rounds"] == 1
    assert messy["decision_validation"]["fallback_share"] == 0.0
    assert messy["validity"] == "valid"


def test_elicit_round_records_validation_in_ctx():
    roster = [{"agent_id": 1, "outcome_power": 2.0}, {"agent_id": 2}]
    fake = FakeLLMClient(json_responses=[{"decisions": [
        {"agent_id": 999, "scenario": "S1", "magnitude": 1, "confidence": 1},
        {"agent_id": "1", "scenario": "S1", "magnitude": 1, "confidence": 0.5},
        {"agent_id": 2, "scenario": dc.ABSTAIN_TOKEN}]}])
    ctx = {"llm": fake, "scenarios": ["S1", "S2"], "round_num": 3}
    out = dc.elicit_round(roster, ctx)
    rec = ctx["decision_validation"]
    assert rec["reasons"]["unknown_agent"] == 1
    assert rec["roster_agent_ids"] == ["1", "2"]
    assert rec["abstained_agent_ids"] == ["2"] and rec["measured"] is True
    assert ctx["round_status"] == "committed"
    assert len(out) == 1 and out[0]["agent_id"] == 1
    assert out[0]["outcome_power"] == 2.0 and out[0]["weight"] == 2.0 * 0.5
    # no attempt (empty roster) → no record
    ctx_empty = {"llm": fake, "scenarios": ["S1"]}
    assert dc.elicit_round([], ctx_empty) == [] and "decision_validation" not in ctx_empty


# Pre-SIM-2 golden: sha256 of json.dumps({"result": ..., "calls": [[prompt, temperature,
# max_tokens], ...]}, ensure_ascii=False) for the fixture below, computed by running this
# exact fixture against backend/app/services/{decision_channel,worldstate}.py at
# feat/finharness-transplants c1b0604 (post-SIM-1, before this change).
_LEGACY_GOLDEN_SHA256 = "a55c1ec5ddac68ec22410f895fee1262f1eb884604e4f5c022d4e1a26df02408"
_MESSY_REPLIES = [
    {"decisions": [
        {"agent_id": 1, "scenario": "S1", "magnitude": 1, "confidence": 1},
        {"agent_id": 999, "scenario": "S2", "magnitude": 1, "confidence": 1},
        {"agent_id": 1, "scenario": "S2", "magnitude": 1, "confidence": 1},
        {"agent_id": "2", "scenario": "S2", "magnitude": 7, "confidence": 0.9},
        {"agent_id": 3, "scenario": "S1"},
    ]},
    {"decisions": [
        {"agent_id": 1, "scenario": "弃权"},
        {"agent_id": 2, "scenario": "S2", "magnitude": 0.5},
    ]},
]


def _legacy_fixture_run():
    actions = [{"round": 1, "agent_id": 1, "agent_name": "A"},
               {"round": 1, "agent_id": 2, "agent_name": "B"},
               {"round": 1, "agent_id": 3, "agent_name": "C"},
               {"round": 2, "agent_id": 1, "agent_name": "A"},
               {"round": 2, "agent_id": 2, "agent_name": "B"}]
    cfgs = [{"agent_id": 1, "entity_name": "A", "stance": "pro", "influence_weight": 2.0,
             "outcome_power": 1.0},
            {"agent_id": 2, "entity_name": "B", "stance": "con", "influence_weight": 1.0,
             "outcome_power": 3.0},
            {"agent_id": 3, "entity_name": "C", "stance": "neutral", "influence_weight": 0.5}]
    seed = {"scenarios": ["S1", "S2"], "base_rates": {"S1": 0.6, "S2": 0.4}}
    fake = FakeLLMClient(json_responses=copy.deepcopy(_MESSY_REPLIES))
    res = run_decision_channel(actions, cfgs, seed, fake, inertia=0.5, concurrency=1,
                               round_to_date=lambda r: f"2027-0{r}-01")
    calls = [[c["messages"][0]["content"], c["temperature"], c["max_tokens"]]
             for c in fake.calls]
    return res, calls


def test_validation_flag_off_is_legacy(monkeypatch):
    """DECISION_CHANNEL_VALIDATION=false: prompts, decisions and trajectories are
    byte-identical to the post-SIM-1 state (agent 999 and magnitude 7 pass through)."""
    monkeypatch.setattr(Config, "DECISION_CHANNEL_VALIDATION", False, raising=False)
    res, calls = _legacy_fixture_run()
    blob = json.dumps({"result": res, "calls": calls}, ensure_ascii=False)
    assert hashlib.sha256(blob.encode("utf-8")).hexdigest() == _LEGACY_GOLDEN_SHA256
    ids = [d["agent_id"] for d in res["decisions"]]
    assert 999 in ids and "2" in ids and ids.count(1) == 2
    assert [d["magnitude"] for d in res["decisions"] if d["agent_id"] == "2"] == [7]
    assert "decision_validation" not in res
    assert all("decision_validation" not in t for t in res["trajectory"])

    # the legacy parse loop itself, directly: report untouched, raw values kept
    report = {}
    fake = FakeLLMClient(json_responses=[copy.deepcopy(_MESSY_REPLIES[0])])
    out, status = _elicit_round_decisions(
        fake, ["S1", "S2"], [{"agent_id": i} for i in (1, 2, 3)], 1, report=report)
    assert status == "committed" and report == {}
    assert out == [{"agent_id": 1, "scenario": "S1", "magnitude": 1, "confidence": 1},
                   {"agent_id": 999, "scenario": "S2", "magnitude": 1, "confidence": 1},
                   {"agent_id": 1, "scenario": "S2", "magnitude": 1, "confidence": 1},
                   {"agent_id": "2", "scenario": "S2", "magnitude": 7, "confidence": 0.9},
                   {"agent_id": 3, "scenario": "S1", "magnitude": 1.0, "confidence": 0.7}]


def test_validation_on_keeps_prompts_and_call_count(monkeypatch):
    """SIM-2 adds zero LLM calls and leaves prompt text unchanged; only the output
    changes (validated decisions + per-round record + run summary)."""
    monkeypatch.setattr(Config, "DECISION_CHANNEL_VALIDATION", False, raising=False)
    _, legacy_calls = _legacy_fixture_run()
    monkeypatch.setattr(Config, "DECISION_CHANNEL_VALIDATION", True, raising=False)
    res, calls = _legacy_fixture_run()
    assert calls == legacy_calls                     # same prompts, temperature, max_tokens
    assert [d["agent_id"] for d in res["decisions"]] == [1, 2, 2]
    assert res["decision_validation"]["measured_rounds"] == 2
    assert res["decision_validation"]["fallback_share"] == round(1 / 5, 6)
    assert res["decision_validation"]["reasons"]["missing_magnitude"] == 1
    assert res["trajectory"][2]["decision_validation"]["abstained_agent_ids"] == ["1"]


class _SpyLLM:
    def __init__(self):
        self.max_tokens = []

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, **kw):
        self.max_tokens.append(max_tokens)
        return {"decisions": []}


def test_max_tokens_scales_only_above_17(monkeypatch):
    spy = _SpyLLM()
    for n in (10, 17, 18, 20):
        _elicit_round_decisions(spy, ["S1"], [{"agent_id": i} for i in range(n)], 1)
    assert spy.max_tokens == [2048, 2048, 2080, 2272]
    big = _SpyLLM()
    _elicit_round_decisions(big, ["S1"], [{"agent_id": i} for i in range(200)], 1)
    assert big.max_tokens == [8192]                  # capped
    monkeypatch.setattr(Config, "DECISION_CHANNEL_VALIDATION", False, raising=False)
    legacy = _SpyLLM()
    _elicit_round_decisions(legacy, ["S1"], [{"agent_id": i} for i in range(18)], 1)
    assert legacy.max_tokens == [2048]               # flag off → unchanged budget


def test_fallback_share_demotes_validity():
    """4-actor rosters, replies covering 1 actor for 5 rounds → fallback_share 0.75 >
    DECISION_CHANNEL_FALLBACK_MAX_SHARE (0.5) → inconclusive / no_update."""
    actions = [{"round": r, "agent_id": a} for r in range(1, 6) for a in (1, 2, 3, 4)]
    cfgs = [{"agent_id": a, "influence_weight": 1.0} for a in (1, 2, 3, 4)]
    fake = FakeLLMClient(json_responses=[
        {"decisions": [{"agent_id": 1, "scenario": "S1", "magnitude": 1, "confidence": 1}]}
        for _ in range(5)])
    res = run_decision_channel(actions, cfgs, {"scenarios": ["S1", "S2"]}, fake,
                               concurrency=1, round_to_date=lambda r: f"2027-0{r}-01")
    assert len(fake.calls) == 5
    assert res["decision_validation"]["fallback_share"] == 0.75
    assert res["decision_validation"]["slots"] == 20
    assert res["round_accounting"]["valid_transitions"] == 5   # every round committed …
    assert res["validity"] == "inconclusive"                    # … yet mostly fallback
    assert "fallback_share_exceeded" in res["validity_reasons"]
    assert res["forecast_effect"] == "no_update"


def test_verdict_fallback_share_threshold(monkeypatch):
    from app.services.worldstate import WorldState

    ws = WorldState(["A", "B"])
    for _ in range(3):
        ws.step([{"scenario": "A", "magnitude": 1.0, "weight": 1.0}], round_status="committed")
    acct = ws.round_accounting()
    assert dc.decision_channel_verdict(acct)["validity"] == "valid"
    assert dc.decision_channel_verdict(acct, fallback_share=None)["validity"] == "valid"
    assert dc.decision_channel_verdict(acct, fallback_share=0.5)["validity"] == "valid"
    demoted = dc.decision_channel_verdict(acct, fallback_share=0.51)
    assert (demoted["validity"], demoted["validity_reasons"], demoted["forecast_effect"]) == (
        "inconclusive", ["fallback_share_exceeded"], "no_update")
    assert demoted["round_accounting"] == acct
    monkeypatch.setattr(Config, "DECISION_CHANNEL_FALLBACK_MAX_SHARE", 0.9, raising=False)
    assert dc.decision_channel_verdict(acct, fallback_share=0.75)["validity"] == "valid"
    # a non-valid verdict keeps its own reasons (fallback never masks them)
    failed = WorldState(["A", "B"])
    failed.step([], round_status="failed")
    verdict = dc.decision_channel_verdict(failed.round_accounting(), fallback_share=1.0)
    assert verdict["validity"] == "invalid" and verdict["validity_reasons"] == ["no_valid_rounds"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 50.0, -0.1, "abc", None])
def test_misconfigured_fallback_threshold_uses_default(monkeypatch, caplog, bad):
    """A NaN/out-of-range/non-numeric threshold must not disable (or invert) the gate:
    it falls back to 0.5 with a warning."""
    from app.services.worldstate import WorldState

    ws = WorldState(["A", "B"])
    for _ in range(3):
        ws.step([{"scenario": "A", "magnitude": 1.0, "weight": 1.0}], round_status="committed")
    acct = ws.round_accounting()
    monkeypatch.setattr(Config, "DECISION_CHANNEL_FALLBACK_MAX_SHARE", bad, raising=False)
    with caplog.at_level(logging.WARNING, logger=dc.logger.name):
        assert dc.decision_channel_verdict(acct, fallback_share=0.5)["validity"] == "valid"
        demoted = dc.decision_channel_verdict(acct, fallback_share=0.51)
    assert demoted["validity_reasons"] == ["fallback_share_exceeded"]
    assert any("DECISION_CHANNEL_FALLBACK_MAX_SHARE" in r.getMessage() for r in caplog.records)


def test_fallback_threshold_bounds_and_non_finite_share(monkeypatch):
    from app.services.worldstate import WorldState

    ws = WorldState(["A", "B"])
    for _ in range(3):
        ws.step([{"scenario": "A", "magnitude": 1.0, "weight": 1.0}], round_status="committed")
    acct = ws.round_accounting()
    monkeypatch.setattr(Config, "DECISION_CHANNEL_FALLBACK_MAX_SHARE", 0.0, raising=False)
    assert dc.decision_channel_verdict(acct, fallback_share=0.0)["validity"] == "valid"
    assert dc.decision_channel_verdict(acct, fallback_share=0.01)["validity"] == "inconclusive"
    monkeypatch.setattr(Config, "DECISION_CHANNEL_FALLBACK_MAX_SHARE", 1.0, raising=False)
    assert dc.decision_channel_verdict(acct, fallback_share=1.0)["validity"] == "valid"
    # a non-finite share is a broken measurement, never a pass (fail closed)
    nan_share = dc.decision_channel_verdict(acct, fallback_share=float("nan"))
    assert nan_share["validity_reasons"] == ["fallback_share_exceeded"]


def _roster_ids_per_round(res):
    return [row["decision_validation"]["roster_agent_ids"] for row in res["trajectory"][1:]]


def test_max_active_keyword_wins_over_config(monkeypatch):
    """An explicit max_active_per_round caps the roster; without it the Config knob does."""
    actions = [{"round": 1, "agent_id": a} for a in (1, 2, 3)]
    cfgs = [{"agent_id": a, "influence_weight": float(4 - a)} for a in (1, 2, 3)]
    reply = {"decisions": [{"agent_id": 1, "scenario": "S1", "magnitude": 1, "confidence": 1}]}

    def _run(**kw):
        return run_decision_channel(actions, cfgs, {"scenarios": ["S1", "S2"]},
                                    FakeLLMClient(json_responses=[reply]), concurrency=1, **kw)

    assert _roster_ids_per_round(_run()) == [["1", "2", "3"]]            # Config default 60
    assert _roster_ids_per_round(_run(max_active_per_round=1)) == [["1", PUBLIC_BLOCK_ID]]
    monkeypatch.setattr(Config, "DECISION_CHANNEL_MAX_ACTIVE", 2, raising=False)
    assert _roster_ids_per_round(_run()) == [["1", "2", PUBLIC_BLOCK_ID]]
    assert _roster_ids_per_round(_run(max_active_per_round=60)) == [["1", "2", "3"]]


def test_bare_all_abstain_rounds_stay_valid():
    """Foglamp I-16 unchanged: explicit bare abstentions are valid evidence and are
    not fallback slots."""
    actions = [{"round": r, "agent_id": a} for r in (1, 2, 3) for a in (1, 2)]
    fake = FakeLLMClient(json_responses=[
        {"decisions": [{"agent_id": 1, "scenario": dc.ABSTAIN_TOKEN},
                       {"agent_id": 2, "scenario": dc.ABSTAIN_TOKEN}]}])
    res = run_decision_channel(actions, [{"agent_id": 1}, {"agent_id": 2}],
                               {"scenarios": ["S1", "S2"]}, fake, concurrency=1)
    assert res["round_accounting"]["counts"] == {"abstained": 3}
    assert res["validity"] == "valid" and res["validity_reasons"] == []
    assert res["decision_validation"]["fallback_share"] == 0.0
    assert res["decision_validation"]["abstained"] == 6


# ------------------------------------------------------------------------ SIM-8 (P23)
_SIM8_ACTIVE = [{"agent_id": 1, "name": "A", "stance": "pro", "influence": 1.0,
                 "gains_if": "稳价", "post": "我支持"},
                {"agent_id": PUBLIC_BLOCK_ID, "name": "公众", "stance": "", "influence": 2.0}]
_SIM8_PERIOD = {"period_start": "2026-10-01", "period_end": "2026-12-31", "label": "2026-Q4"}
# sha256 of the pre-SIM-8 prompts built by _sim8_prompts() (recorded before the change).
_PRE_SIM8_PROMPT_SHA256 = {
    "hours": "3de80902c63e4c960b3a3bb1b47ecd9a271417cbab500673ccbee0294f28aef0",
    "calendar": "9fe35e39dca67dc19a87661ab60d35d6b0d2c8a2bd9bc31acd2afdbbf99d4057",
}
_SIM8_EVENTS = [{"date": "2027-01-05", "content": "X happens"},
                {"date": "2027-01-09", "content": "Y", "is_scenario_injection": True}]


def _sim8_prompts(**kw):
    shares = {"S1": 0.6, "S2": 0.4}
    return {
        "hours": _build_round_decision_prompt(["S1", "S2"], _SIM8_ACTIVE, 3, "2027-01-01",
                                              base_shares=shares, **kw),
        "calendar": _build_round_decision_prompt(
            ["S1", "S2"], _SIM8_ACTIVE, 2, "2026-12-31", base_shares=shares,
            period=_SIM8_PERIOD, n_rounds=3, horizon_date="2027-03-31", unit="quarter", **kw),
    }


def _sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_sim_decision_events_default_on_and_documented():
    import os
    assert Config.SIM_DECISION_EVENTS is True
    env_example = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), ".env.example")
    with open(env_example, encoding="utf-8") as f:
        assert "# SIM_DECISION_EVENTS=true" in f.read()


def test_prompt_events_block_before_roster():
    """SIM-8: the labelled events block sits immediately before the roster; None/[] leave
    the prompt byte-identical to the pre-SIM-8 output in both framings."""
    for kw in ({}, {"events": None}, {"events": []}):
        assert {k: _sha256(v) for k, v in _sim8_prompts(**kw).items()} == _PRE_SIM8_PROMPT_SHA256
    legacy = _sim8_prompts()
    assert dc.EVENTS_BLOCK_HEADER == (
        "本时段日程事件（来自研究时间线的预期外生事件，并非任何角色的发言；结果尚未确定）：")
    block = dc._render_events_block(_SIM8_EVENTS)
    assert block == (dc.EVENTS_BLOCK_HEADER + "\n- [2027-01-05] X happens"
                     "\n- 【情景假设】[2027-01-09] Y")
    for mode, prompt in _sim8_prompts(events=_SIM8_EVENTS).items():
        assert "本时段日程事件" in prompt and "[2027-01-05] X happens" in prompt
        assert "【情景假设】" in prompt
        assert prompt.index("本时段日程事件") < prompt.index("角色名册：")
        # inserted verbatim right before the roster; every other byte is unchanged
        assert prompt == legacy[mode].replace("角色名册：", block + "\n角色名册：")
        assert "投票/下单/站队/分配" in prompt          # characterization pin unchanged
    # herding guard: no WorldState number or percentage, and no direction is asked for
    assert "%" not in block and "60" not in block
    assert not any(ch.isdigit() for ch in dc.EVENTS_BLOCK_HEADER)


def test_events_block_labels_dedupe_and_skips():
    events = [
        {"date": "2026-11-05", "content": "[2026-11-05] 事件A发生"},     # already dated
        {"date": "2026-11-05", "content": "[2026-11-05] 事件A发生",       # same (date, content)
         "is_scenario_injection": True},
        {"date": "2026-08-01", "content": "早先事件", "carried_from_round": 1},  # SIM-6 carry
        {"date": "", "content": "无日期事件"},
        {"date": "2026-12-01", "content": "   "},                        # no content
        "not a dict",
        {"date": "2026-12-02", "content": "多行\n内容"},
    ]
    assert dc._render_events_block(events).split("\n") == [
        dc.EVENTS_BLOCK_HEADER,
        "- [2026-11-05] 事件A发生",                 # first occurrence wins, no double date
        "- 【更早时段】[2026-08-01] 早先事件",
        "- 无日期事件",
        "- [2026-12-02] 多行 内容",                 # one event is one line
    ]
    for empty in (None, [], [{"content": ""}], ["junk"], 5):
        assert dc._render_events_block(empty) == ""


def test_events_block_failure_degrades_safe(monkeypatch):
    """The block is advisory: a renderer failure leaves the legacy prompt, never a failed round."""
    legacy = _sim8_prompts()

    def _boom(*_a, **_k):
        raise RuntimeError("renderer down")

    monkeypatch.setattr(dc, "_render_events_block", _boom)
    assert _sim8_prompts(events=_SIM8_EVENTS) == legacy


def test_events_block_cap():
    """30 long events (plus duplicates): whole lines within 800 characters, input order,
    duplicates removed, and an explicit omission marker counting unique events."""
    unique = [{"date": f"2027-01-{i + 1:02d}", "content": f"事件{i:02d} " + "长" * 60}
              for i in range(30)]
    block = dc._render_events_block(unique + [dict(ev) for ev in unique[:10]])
    assert len(block) <= dc.EVENTS_BLOCK_MAX_CHARS == 800
    lines = block.split("\n")
    expected = [f"- [{ev['date']}] {ev['content']}" for ev in unique]
    kept = lines[1:-1]
    assert lines[0] == dc.EVENTS_BLOCK_HEADER
    assert 0 < len(kept) < 30 and kept == expected[:len(kept)]   # whole lines, no duplicates
    assert lines[-1] == f"（另有 {30 - len(kept)} 条事件省略）"
    # the next whole line would not have fitted beside its marker
    one_more = lines[:-1] + [expected[len(kept)], f"（另有 {30 - len(kept) - 1} 条事件省略）"]
    assert len("\n".join(one_more)) > 800
    small = dc._render_events_block(unique[:2])
    assert "省略" not in small and small.split("\n")[1:] == expected[:2]
    tight = dc._render_events_block(unique, max_chars=300)
    assert len(tight) <= 300 and tight.endswith("条事件省略）")
    # a single line longer than the budget is cut explicitly, never dropped silently
    huge = dc._render_events_block([{"date": "2027-01-01", "content": "巨" * 2000}])
    assert len(huge) <= 800 and huge.endswith("…(truncated)")


def test_events_digest():
    digest = dc._events_digest(_SIM8_EVENTS)
    pairs = sorted([("2027-01-05", "X happens"), ("2027-01-09", "Y")])
    assert digest == hashlib.sha1(json.dumps(pairs, ensure_ascii=False).encode("utf-8"),
                                  usedforsecurity=False).hexdigest()[:16]
    assert dc._events_digest(list(reversed(_SIM8_EVENTS))) == digest       # order-free
    assert dc._events_digest(_SIM8_EVENTS + _SIM8_EVENTS[:1]) == digest     # duplicates
    assert dc._events_digest(_SIM8_EVENTS[:1]) != digest


def test_elicit_round_forwards_events(monkeypatch):
    roster = [{"agent_id": 1, "name": "A", "stance": "pro", "outcome_power": 1.0}]
    reply = {"decisions": [{"agent_id": 1, "scenario": "S1", "magnitude": 1, "confidence": 1}]}

    def _prompt(**ctx_extra):
        fake = FakeLLMClient(json_responses=[copy.deepcopy(reply)])
        ctx = {"llm": fake, "scenarios": ["S1", "S2"], "round_num": 1, **ctx_extra}
        out = dc.elicit_round(roster, ctx)
        assert len(out) == 1 and ctx["round_status"] == "committed"
        assert len(fake.calls) == 1                     # no extra LLM call
        return fake.calls[0]["messages"][0]["content"]

    plain = _prompt()
    with_events = _prompt(events=_SIM8_EVENTS)
    assert "本时段日程事件" in with_events and "[2027-01-05] X happens" in with_events
    assert with_events == plain.replace(
        "角色名册：", dc._render_events_block(_SIM8_EVENTS) + "\n角色名册：")
    monkeypatch.setattr(Config, "SIM_DECISION_EVENTS", False)
    off = _prompt(events=_SIM8_EVENTS)
    assert off == plain and "本时段日程事件" not in off


_SIM8_REPLY = {"decisions": [{"agent_id": 1, "scenario": "S1", "magnitude": 1, "confidence": 1}]}


def _sim8_posthoc(n_rounds, **kw):
    actions = [{"round": r, "agent_id": 1} for r in range(1, n_rounds + 1)]
    fake = FakeLLMClient(json_responses=[copy.deepcopy(_SIM8_REPLY) for _ in range(n_rounds)])
    res = run_decision_channel(actions, [{"agent_id": 1, "influence_weight": 1.0}],
                               {"scenarios": ["S1", "S2"]}, fake, concurrency=1, **kw)
    return res, [c["messages"][0]["content"] for c in fake.calls]


def test_posthoc_events_cache_key(monkeypatch):
    """Hours-mode rounds share one as_of date: different events → separate calls; rounds
    without events keep the legacy key and still dedupe (R2-EXEC-10)."""
    def same_day(_rnd):
        return "2027-01-01"

    ev_a = [{"date": "2027-01-05", "content": "A 发生"}]
    ev_b = [{"date": "2027-01-06", "content": "B 发生"}]
    base, base_prompts = _sim8_posthoc(4, round_to_date=same_day)
    assert len(base_prompts) == 1                      # stable roster + one date → one call

    res, prompts = _sim8_posthoc(4, round_to_date=same_day,
                                 events_by_round={1: ev_a, 2: ev_b, 4: ev_a + ev_a})
    # rounds 1 and 2 differ only in events → 2 calls; round 4 carries round 1's events
    # (duplicate removed) → reuses round 1's call; round 3 has none → one legacy-keyed call
    assert len(prompts) == 3
    assert "A 发生" in prompts[0] and "B 发生" not in prompts[0]
    assert "B 发生" in prompts[1] and "A 发生" not in prompts[1]
    assert "本时段日程事件" not in prompts[2]
    assert prompts[2] == base_prompts[0].replace("第 1 轮", "第 3 轮")
    assert res["n_rounds"] == 4 and len(res["trajectory"]) == 5

    # events on round 1 only: rounds 2-4 still dedupe to one call
    _, prompts = _sim8_posthoc(4, round_to_date=same_day, events_by_round={1: ev_a})
    assert len(prompts) == 2 and "本时段日程事件" not in prompts[1]

    # None / {} / rows without content: byte-identical to no events
    for empty in (None, {}, {1: []}, {1: [{"date": "2027-01-05", "content": ""}]}):
        assert _sim8_posthoc(4, round_to_date=same_day, events_by_round=empty) == (
            base, base_prompts)

    # SIM_DECISION_EVENTS=false: prompts, cache keys (call count) and result unchanged
    monkeypatch.setattr(Config, "SIM_DECISION_EVENTS", False)
    assert _sim8_posthoc(4, round_to_date=same_day,
                         events_by_round={1: ev_a, 2: ev_b}) == (base, base_prompts)


def test_posthoc_calendar_rounds_get_the_events_block():
    round_dates = [
        {"round": 0, "period_start": "2026-07-12", "period_end": "2026-09-30", "label": "2026-Q3"},
        {"round": 1, "period_start": "2026-10-01", "period_end": "2026-12-31", "label": "2026-Q4"},
        {"round": 2, "period_start": "2027-01-01", "period_end": "2027-03-31", "label": "2027-Q1"},
    ]
    event = {"date": "2026-11-05", "content": "[2026-11-05] 事件A发生"}
    base, base_prompts = _sim8_posthoc(3, round_dates=round_dates)
    res, prompts = _sim8_posthoc(3, round_dates=round_dates, events_by_round={2: [event]})
    assert len(prompts) == len(base_prompts) == 3      # no extra calls
    assert prompts[0] == base_prompts[0] and prompts[2] == base_prompts[2]
    assert prompts[1] == base_prompts[1].replace(
        "角色名册：", dc._render_events_block([event]) + "\n角色名册：")
    assert "时段：第 2/3 轮" in prompts[1] and "- [2026-11-05] 事件A发生\n角色名册：" in prompts[1]
    assert res["schema_version"] == 3
    assert res["trajectory"] == base["trajectory"] and res["decisions"] == base["decisions"]
