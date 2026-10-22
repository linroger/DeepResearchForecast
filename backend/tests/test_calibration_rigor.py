"""Calibration-rigor tests for the forecast bucket (R2-CAL-* / REPORT-6 / EVAL-1).

Covers the round-2 calibration findings landed in forecast_extractor / ensemble /
backtest / forecast_ledger. Config flags are monkeypatched per-test so each behavior
is exercised deterministically regardless of the live default values.
"""

import math

import pytest

from app.config import Config
from app.services import forecast_extractor as FE
from app.services import ensemble as EN
from app.services import backtest as BT
from app.services import forecast_ledger as LG
from tests.conftest import FakeLLMClient


def _fc(pairs):
    return {"headline": "h", "horizon": "2030",
            "scenarios": [{"name": n, "probability": p, "key_drivers": [],
                           "resolution_criteria": "c"} for n, p in pairs]}


# --------------------------------------------------------------- R2-CAL-4 floor
def test_probability_floor_lifts_near_zero_and_renormalizes(monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_PROB_FLOOR", 0.03, raising=False)
    out = FE._normalize_scenarios([{"name": "A", "probability": 0.99},
                                   {"name": "B", "probability": 0.001}])
    probs = {s["name"]: s["probability"] for s in out}
    assert probs["B"] >= 0.029          # ~0.001 lifted off the floor (no catastrophic 0%)
    assert abs(sum(probs.values()) - 1.0) < 1e-6


def test_probability_floor_off_is_byte_identical(monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_PROB_FLOOR", 0.0, raising=False)
    out = FE._normalize_scenarios([{"name": "A", "probability": 3},
                                   {"name": "B", "probability": 1}])
    assert [s["probability"] for s in out] == [0.75, 0.25]


# ------------------------------------------------------------- REPORT-6 audit
def test_audit_counts_sim_and_edge_grounding_with_separate_source_metric():
    md = ('> "联盟规模达到 5000 人" 显示动员强烈。\n'        # sim-grounded quant line
          'A --[支持, sign=+, strength=high]--> B 提升 30% 概率。\n'  # edge-grounded quant line
          '经济损失 20% 出现。\n')                              # ungrounded quant line
    a = FE.audit_citation_grounding(md)
    assert a["quantitative_claims"] == 3
    assert a["cited"] == 2 and a["coverage"] == round(2 / 3, 3)   # grounded (sim/edge)
    assert a["source_cited"] == 0 and a["source_coverage"] == 0.0  # source-only separate


def test_audit_source_only_unchanged_when_no_sim_markers():
    md = "市场份额将达到 45% [S1]。\n营收增长 30%。\n到 2030年 格局重塑【S3】。\n"
    a = FE.audit_citation_grounding(md)
    assert a["cited"] == 2 and a["coverage"] == round(2 / 3, 3)
    assert a["source_coverage"] == round(2 / 3, 3)


# ----------------------------------------------------------- R2-CAL-7 criteria
def test_validate_resolution_criteria_sharpness():
    assert FE.validate_resolution_criteria("2030年 DRAM 份额>50%")["sharp"] is True
    assert FE.validate_resolution_criteria(
        "AP certifies 218 or more Democratic House seats after the November 3, 2026 election"
    )["sharp"] is True
    assert FE.validate_resolution_criteria(
        "SEC acknowledges an S-1 registration statement by 2028-12-31"
    )["sharp"] is True
    assert FE.validate_resolution_criteria(
        "FY26 cash capex totals between $630B and $770B"
    )["sharp"] is True
    assert FE.validate_resolution_criteria("利率可能上升")["sharp"] is False
    assert FE.validate_resolution_criteria("")["sharp"] is False


def test_validate_resolution_criteria_political_events():
    """Political/legal event criteria resolve on official markers (ballot lists,
    promulgation, rating actions, primaries) — as objectively decidable as a
    threshold. Regression: the 2026-10-16 FR budget-crisis run failed the publish
    gate 8/14 because these stems were missing from _RC_METRIC_RE."""
    assert FE.validate_resolution_criteria(
        "Marine Le Pen is on the ballot for the first round of the presidential "
        "election on 18 April 2027. Resolves YES if she appears among officially "
        "validated candidates (source: Conseil constitutionnel published list)"
    )["sharp"] is True
    assert FE.validate_resolution_criteria(
        "Moody's downgrades France's long-term rating below Aa3 at or following "
        "its 23 October 2026 scheduled review (source: Moody's publication)"
    )["sharp"] is True
    assert FE.validate_resolution_criteria(
        "The 2027 loi de finances is promulgated by 28 February 2027 "
        "(source: Journal officiel / Legifrance)"
    )["sharp"] is True
    assert FE.validate_resolution_criteria(
        "The 2026 United Left primary for the 2027 presidential election is "
        "officially canceled before a nominee is selected"
    )["sharp"] is True
    assert FE.validate_resolution_criteria(
        "No 2027 finance law promulgated by 30 April 2027 and taxes continue "
        "under a special law enacted for that purpose"
    )["sharp"] is True
    # Vague political prose still fails: no date, no verifiable marker.
    assert FE.validate_resolution_criteria(
        "The political situation may deteriorate further"
    )["sharp"] is False


def test_validate_resolution_criteria_political_and_gbp_markers():
    """Second regression set from the 2026-10-16 Burnham run (7/17 sharp → gate
    fail): office-holding on a date, comparators, £ thresholds, legal
    commencement and operational milestones must all count as metric signals."""
    assert FE.validate_resolution_criteria(
        "Andy Burnham is Prime Minister of the United Kingdom on polling day of "
        "the general election due by 28 August 2029"
    )["sharp"] is True
    assert FE.validate_resolution_criteria(
        "Greater Manchester records fewer than 14,400 net additional homes in 2027-28"
    )["sharp"] is True
    assert FE.validate_resolution_criteria(
        "Greater Manchester real GDP growth exceeds UK real GDP growth in 2027"
    )["sharp"] is True
    assert FE.validate_resolution_criteria(
        "The capital settlement is formally reprofiled downward from the "
        "£373.423m profiled for 2029-30"
    )["sharp"] is True
    assert FE.validate_resolution_criteria(
        "The prospective fiscal provisions of the Act are commenced by "
        "regulation before 1 April 2028"
    )["sharp"] is True
    assert FE.validate_resolution_criteria(
        "Sentiment around the devolution agenda could improve"
    )["sharp"] is False


def test_quality_vague_criteria_gated(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_REQUIRE_SHARP_CRITERIA", True, raising=False)
    out = FE._assemble_forecast({"scenarios": [
        {"name": "锐", "probability": 1, "resolution_criteria": "2030年 份额>50%"},
        {"name": "钝", "probability": 1, "resolution_criteria": "可能变化"}]})
    assert out["quality"]["vague_criteria"] == ["钝"]


def test_quality_absent_by_default(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_REQUIRE_SHARP_CRITERIA", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_REQUIRE_ANCHOR", False, raising=False)
    out = FE._assemble_forecast({"scenarios": [
        {"name": "A", "probability": 1, "resolution_criteria": "x"}]})
    assert "quality" not in out


# --------------------------------------------------- R2-CAL-1 / R2-CAL-17 spine
def test_spine_self_consistency_pools_mean_and_spread(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 5, raising=False)
    draws = [{"headline": "X", "horizon": "2030", "confidence": "high", "scenarios": [
        {"name": "A", "probability": pa, "resolution_criteria": "到2030 A>50%"},
        {"name": "B", "probability": round(1 - pa, 4), "resolution_criteria": "其它"}]}
        for pa in (0.6, 0.8, 0.4, 0.7, 0.5)]
    fake = FakeLLMClient(json_responses=draws)
    sp = FE.derive_forecast_spine(fake, central_question="q")
    assert sp["self_consistency_k"] == 5
    a = next(s for s in sp["scenarios"] if s["name"] == "A")
    assert a["self_consistency_n"] == 5
    assert a["p_low"] <= a["probability"] <= a["p_high"]
    assert a["p_low"] < a["p_high"]                      # real spread carried to interval
    assert abs(sum(s["probability"] for s in sp["scenarios"]) - 1.0) < 1e-6


def test_spine_single_draw_when_k_one(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 1, raising=False)
    fake = FakeLLMClient(json_responses=[{"headline": "X", "horizon": "2030", "scenarios": [
        {"name": "A", "probability": 2, "resolution_criteria": "r"},
        {"name": "维持现状", "probability": 2, "resolution_criteria": "r"}]}])
    sp = FE.derive_forecast_spine(fake, central_question="q")
    assert [s["probability"] for s in sp["scenarios"]] == [0.5, 0.5]
    assert len(fake.calls) == 1                          # exactly one call when K=1


# --------------------------------------------------------- R2-CAL-11 empty retry
def test_spine_empty_first_draw_retries_once(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 1, raising=False)
    fake = FakeLLMClient(json_responses=[
        {},                                              # first draw: no scenarios
        {"headline": "X", "scenarios": [{"name": "A", "probability": 1,
                                          "resolution_criteria": "r"}]}])
    sp = FE.derive_forecast_spine(fake, central_question="q")
    assert sp["scenarios"] and sp["scenarios"][0]["name"] == "A"
    assert len(fake.calls) == 2                          # warned + retried once


def test_spine_max_tokens_raised(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 1, raising=False)
    monkeypatch.setattr(Config, "REPORT_SPINE_MAX_TOKENS", 6144, raising=False)
    fake = FakeLLMClient(json_responses=[{"scenarios": [
        {"name": "A", "probability": 1, "resolution_criteria": "r"}]}])

    captured = {}
    orig = fake.chat_json

    def _spy(messages, temperature=0.3, max_tokens=4096):
        captured["max_tokens"] = max_tokens
        return orig(messages, temperature=temperature, max_tokens=max_tokens)

    fake.chat_json = _spy
    FE.derive_forecast_spine(fake, central_question="q")
    assert captured["max_tokens"] == 6144


# ----------------------------------------------- R2-CAL-3 / R2-CAL-18 worldstate
def test_spine_worldstate_anchor_and_divergence(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 1, raising=False)
    monkeypatch.setattr(Config, "REPORT_SPINE_ANCHOR_WORLDSTATE", True, raising=False)
    fake = FakeLLMClient(json_responses=[{"headline": "X", "confidence": "high", "scenarios": [
        {"name": "A", "probability": 0.8, "resolution_criteria": "r"},
        {"name": "B", "probability": 0.2, "resolution_criteria": "r"}]}])
    sp = FE.derive_forecast_spine(fake, central_question="q",
                                  base_distribution={"A": 0.4, "B": 0.6})
    assert sp["base_distribution"] == {"A": 0.4, "B": 0.6}
    a = next(s for s in sp["scenarios"] if s["name"] == "A")
    assert a["worldstate_divergence"] > 0
    assert sp["confidence"] in ("medium", "low")         # demoted on thin-evidence divergence
    # the anchor band instruction reaches the prompt
    assert "基准分布锚点" in fake.calls[0]["messages"][0]["content"]


def test_spine_worldstate_inert_when_flag_off(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 1, raising=False)
    monkeypatch.setattr(Config, "REPORT_SPINE_ANCHOR_WORLDSTATE", False, raising=False)
    fake = FakeLLMClient(json_responses=[{"scenarios": [
        {"name": "A", "probability": 1, "resolution_criteria": "r"}]}])
    sp = FE.derive_forecast_spine(fake, central_question="q",
                                  base_distribution={"A": 0.4})
    assert "base_distribution" not in sp
    assert "基准分布锚点" not in fake.calls[0]["messages"][0]["content"]


# ------------------------------------------------------------- R2-CAL-2 ensemble
def test_ensemble_extremized_logodds_sharpens(monkeypatch):
    monkeypatch.setattr(Config, "ENSEMBLE_EXTREMIZE_A", 2.0, raising=False)
    agg = EN.aggregate_forecasts([_fc([("A", 0.6), ("B", 0.4)]),
                                  _fc([("A", 0.8), ("B", 0.2)]),
                                  _fc([("A", 0.7), ("B", 0.3)])])
    a = next(s for s in agg["scenarios"] if s["name"] == "A")
    assert a["pooling"] == "extremized_logodds"
    assert a["probability"] > 0.7                        # extremized beyond arithmetic mean
    assert abs(sum(s["probability"] for s in agg["scenarios"]) - 1.0) < 1e-6
    assert "p_low" in a and "p_high" in a                # R2-CAL-17


def test_ensemble_arithmetic_when_flag_absent(monkeypatch):
    monkeypatch.setattr(Config, "ENSEMBLE_EXTREMIZE_A", None, raising=False)
    agg = EN.aggregate_forecasts([_fc([("A", 0.6), ("B", 0.4)]),
                                  _fc([("A", 0.8), ("B", 0.2)])])
    a = next(s for s in agg["scenarios"] if s["name"] == "A")
    assert a["pooling"] == "arithmetic_mean"
    assert a["probability"] == 0.7                       # arithmetic mean preserved


# ------------------------------------------------------------- R2-CAL-9 agreement
def test_agreement_tv_identical_runs_is_one():
    assert EN._ensemble_agreement([_fc([("A", 0.6), ("B", 0.4)]),
                                   _fc([("A", 0.6), ("B", 0.4)])]) == 1.0


def test_agreement_tv_disjoint_runs_penalized_by_support():
    # runs that disagree on which scenarios even exist score low
    assert EN._ensemble_agreement([_fc([("A", 1.0)]), _fc([("B", 1.0)])]) < 0.6


def test_agreement_single_run_is_one():
    assert EN._ensemble_agreement([_fc([("A", 0.6), ("B", 0.4)])]) == 1.0


# ------------------------------------------------------- R2-CAL-10 / R2-CAL-14
def test_calibration_report_murphy_decomposition_and_smoothing():
    resolved = [{"forecast": _fc([("A", 0.9), ("B", 0.1)]), "outcome": "A"},
                {"forecast": _fc([("A", 0.8), ("B", 0.2)]), "outcome": "A"},
                {"forecast": _fc([("A", 0.2), ("B", 0.8)]), "outcome": "B"}]
    rep = BT.calibration_report(resolved, bins=5)
    d = rep["brier_decomposition"]
    assert set(d) == {"reliability", "resolution", "uncertainty", "brier_pooled"}
    assert rep["resolution"] == d["resolution"]
    # Murphy identity for the per-prediction (pooled) Brier (binning residual aside)
    assert abs(d["brier_pooled"] - (d["reliability"] - d["resolution"] + d["uncertainty"])) < 0.02
    for b in rep["bins"]:
        if b["count"]:
            assert b["ci_low"] <= b["hit_rate_smoothed"] <= b["ci_high"]


def test_calibration_min_resolved_gate(monkeypatch):
    resolved = [{"forecast": _fc([("A", 0.9), ("B", 0.1)]), "outcome": "A"}]
    monkeypatch.setattr(Config, "CAL_MIN_RESOLVED", 10, raising=False)
    assert BT.calibration_report(resolved)["insufficient_data"] is True
    monkeypatch.setattr(Config, "CAL_MIN_RESOLVED", 0, raising=False)
    assert BT.calibration_report(resolved)["insufficient_data"] is False


# ------------------------------------------------------------- R2-CAL-5 recal
def test_recalibrator_identity_on_thin_data():
    fit = BT.fit_recalibrator([{"forecast": _fc([("A", 0.9), ("B", 0.1)]), "outcome": "A"}])
    assert fit["fitted"] is False and fit["slope"] == 1.0
    assert abs(BT.apply_recalibration(0.7, 1.0) - 0.7) < 1e-6


def test_recalibrator_fits_overconfidence():
    import random
    random.seed(0)
    rich = []
    for _ in range(80):
        p = random.choice([0.2, 0.5, 0.8])
        y = 1 if random.random() < p else 0
        rich.append({"forecast": {"scenarios": [{"name": "A", "probability": p},
                                                 {"name": "B", "probability": 1 - p}]},
                     "outcome": "A" if y else "B"})
    fit = BT.fit_recalibrator(rich)
    assert fit["fitted"] is True and 0.1 <= fit["slope"] <= 5.0


# --------------------------------------------------------------- R2-CAL-8 humility
def test_self_critique_is_humility_monotone():
    # a red-team reply that tries to RAISE the peak gets clamped back to the original peak
    overconf = {"scenarios": [{"name": "A", "probability": 0.95, "resolution_criteria": "c"},
                              {"name": "B", "probability": 0.05, "resolution_criteria": "c"}],
                "confidence": "high"}
    out = FE.self_critique_forecast(_fc([("A", 0.7), ("B", 0.3)]),
                                    FakeLLMClient(json_responses=[overconf]))
    assert max(s["probability"] for s in out["scenarios"]) <= 0.7 + 1e-9
    assert abs(sum(s["probability"] for s in out["scenarios"]) - 1.0) < 1e-6


def test_self_critique_allows_lower_confidence():
    fixed = {"scenarios": [{"name": "A", "probability": 0.55, "resolution_criteria": "c",
                            "critique_note": "向基率回归"},
                           {"name": "B", "probability": 0.45, "resolution_criteria": "c"}],
             "confidence": "low"}
    out = FE.self_critique_forecast(_fc([("A", 0.9), ("B", 0.1)]),
                                    FakeLLMClient(json_responses=[fixed]))
    assert out["critiqued"] is True and out["confidence"] == "low"
    assert out["scenarios"][0]["critique_note"]


def test_premortem_off_by_default_is_noop(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_PREMORTEM", False, raising=False)
    fc = _fc([("A", 0.7), ("B", 0.3)])
    out = FE.premortem_forecast(fc, FakeLLMClient())
    assert out is fc                                     # unchanged, no LLM call
    out_llm = FakeLLMClient()
    FE.premortem_forecast(fc, out_llm)
    assert out_llm.calls == []


def test_premortem_widens_uncertainty_when_enabled(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_PREMORTEM", True, raising=False)
    fc = _fc([("A", 0.8), ("B", 0.2)])
    fake = FakeLLMClient(json_responses=[{"underweighted_scenario": "B",
                                          "missed_signals": ["尾部冲击"],
                                          "overconfident_scenario": "A"}])
    out = FE.premortem_forecast(fc, fake)
    a = next(s for s in out["scenarios"] if s["name"] == "A")
    b = next(s for s in out["scenarios"] if s["name"] == "B")
    assert a["probability"] < 0.8 and b["probability"] > 0.2   # mass shifted, bounded
    assert "尾部冲击" in out["key_uncertainties"]


# ------------------------------------------------------- EVAL-1 / GAP-4 ledger
def test_ledger_persists_objective_signals(tmp_path):
    d = str(tmp_path)
    entry = LG.append_forecast(_fc([("A", 0.6), ("B", 0.4)]), report_id="r1",
                               horizon="2030", d=d,
                               objective_signals={"coverage": 0.8, "vague_criteria": 0})
    assert entry and entry["objective_signals"]["coverage"] == 0.8
    back = LG.read_ledger(d)
    assert back and back[0]["objective_signals"]["coverage"] == 0.8


def test_ledger_objective_signals_optional(tmp_path):
    d = str(tmp_path)
    entry = LG.append_forecast(_fc([("A", 0.6), ("B", 0.4)]), report_id="r1", d=d)
    assert entry is not None and "objective_signals" not in entry


def test_recalibration_param_thin_data_is_identity(tmp_path):
    d = str(tmp_path)
    LG.append_forecast(_fc([("A", 0.6), ("B", 0.4)]), report_id="r1", d=d)
    out = LG.recalibration_param(d=d)
    assert out["slope"] == 1.0 and out["fitted"] is False and "enabled" in out


# ---- 2026-10-18: midband relaxation for honestly-balanced domains (OPEC+ fix) ----
# A set with real spread (std>=0.15) and >=3 conviction calls is not a lazy hedge
# wall even when half its probabilities sit in 0.40-0.60; only weak-spread sets
# keep the strict 0.40 cap. Regression: pipe_fd2799f3ad41 had 7/14 midband,
# std=0.19, conviction=6 and was blocked at the 95% publish gate.

def _midband_rows(probs):
    return [{"statement": f"Forecast number {i} resolves by 2027 at over {i}%.",
             "probability": p, "resolution_criteria": "指数 超过 10% 于 2027年前 (WTO)",
             "theme": "policy", "horizon_year": 2027, "criteria_sharp": True}
            for i, p in enumerate(probs, 1)]


def test_binary_quality_midband_relaxed_when_spread_and_conviction_strong():
    # 7/14 in 0.40-0.60 (share 0.50) BUT std~0.19, conviction=6 → passes now.
    probs = [0.60, 0.40, 0.12, 0.30, 0.55, 0.06, 0.60, 0.30, 0.15, 0.55, 0.60, 0.40, 0.25, 0.65]
    out = FE._binary_quality(_midband_rows(probs), min_count=10)
    assert out["passed"] is True, out["issues"]
    assert out["midband_share"] == 0.5


def test_binary_quality_midband_strict_when_spread_weak():
    # Same midband share but std<0.15 (no real spread) → still under-committed.
    probs = [0.55, 0.45, 0.50, 0.42, 0.58, 0.48, 0.52, 0.55, 0.45, 0.50, 0.42, 0.58, 0.48, 0.52]
    out = FE._binary_quality(_midband_rows(probs), min_count=10)
    assert out["passed"] is False
    assert any("under-committed" in i for i in out["issues"])


def test_binary_quality_midband_strict_when_conviction_missing():
    # Spread comes only from two committed tails; conviction<3 keeps the strict cap.
    probs = [0.05, 0.95, 0.50, 0.45, 0.55, 0.48, 0.52, 0.50, 0.42, 0.58, 0.47, 0.53, 0.44, 0.56]
    out = FE._binary_quality(_midband_rows(probs), min_count=10)
    assert out["passed"] is False
    assert any("under-committed" in i for i in out["issues"])


def test_validate_resolution_criteria_continental_parliamentary_markers():
    """Third regression set from the 2026-10-18 Germany run (pipe_1c1255cee2e4,
    4/13 sharp → publish-gate abort at 95%): continental-parliamentary official
    registers — Chancellor listings, cabinet composition, Bundestag election
    dates, EDP procedures, roll-call votes, two-thirds majorities, reform bills.
    All resolve on official pages; all scored metric=0 before the extension."""
    assert FE.validate_resolution_criteria(
        "bundesregierung.de lists Friedrich Merz as Federal Chancellor on 2027-12-31."
    )["sharp"] is True
    assert FE.validate_resolution_criteria(
        "On 2027-12-31 the federal cabinet listed at bundesregierung.de includes "
        "ministers from CDU/CSU and SPD only, and no federal election has been held "
        "after 23 Feb 2025."
    )["sharp"] is True
    assert FE.validate_resolution_criteria(
        "The Federal Returning Officer announces a Bundestag election date in "
        "calendar year 2027, i.e. before the scheduled 2029 regular election."
    )["sharp"] is True
    assert FE.validate_resolution_criteria(
        "The Council/Commission EDP overview page (economy-finance.ec.europa.eu) "
        "lists an excessive deficit procedure as opened against Germany, dated "
        "on or before 2027-12-31."
    )["sharp"] is True
    assert FE.validate_resolution_criteria(
        "By 2027-12-31, either an SPD or CDU/CSU withdrawal from cabinet is "
        "reported by Reuters/AP, or the cabinet no longer comprises CDU/CSU and "
        "SPD members only."
    )["sharp"] is True
    assert FE.validate_resolution_criteria(
        "A Bundestag roll-call vote before 2027-12-31 amending Grundgesetz "
        "Articles 109 and/or 115 passes with at least a two-thirds majority."
    )["sharp"] is True
    assert FE.validate_resolution_criteria(
        "The Bundestag's printed-matters database (bundestag.de, BT-Drs. of the "
        "21st electoral term) shows a government pension reform bill introduced "
        "by 2026-12-31."
    )["sharp"] is True
    # Vague continental prose still fails (no date/number at all).
    assert FE.validate_resolution_criteria(
        "The coalition could become unstable at some point"
    )["sharp"] is False
