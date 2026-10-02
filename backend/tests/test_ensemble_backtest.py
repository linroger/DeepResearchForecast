"""Golden tests for ensemble aggregation + backtest scoring (EXECPLAN2 I-9-0/I-9-2/I-3-5)."""

from app.services.ensemble import aggregate_forecasts
from app.services.backtest import score_forecast, calibration_report
from app.services.forecast_extractor import self_critique_forecast
from tests.conftest import FakeLLMClient


def _fc(pairs, headline="h"):
    return {"headline": headline, "horizon": "2030",
            "scenarios": [{"name": n, "probability": p, "key_drivers": [], "resolution_criteria": "c"}
                          for n, p in pairs]}


def test_aggregate_matches_by_name_and_normalizes():
    runs = [
        _fc([("Samsung leads", 0.6), ("Stalemate", 0.4)]),
        _fc([("samsung  leads.", 0.8), ("Stalemate", 0.2)]),
        _fc([("Samsung leads", 0.7), ("Stalemate", 0.3)]),
    ]
    agg = aggregate_forecasts(runs)
    assert agg["n_runs"] == 3
    top = agg["scenarios"][0]
    assert top["name"].lower().startswith("samsung")
    assert top["support"] == 3 and top["support_ratio"] == 1.0
    assert abs(sum(s["probability"] for s in agg["scenarios"]) - 1.0) < 1e-6
    assert 0.0 <= agg["agreement"] <= 1.0


def test_aggregate_empty():
    assert aggregate_forecasts([])["n_runs"] == 0


def test_score_forecast_brier():
    fc = _fc([("A", 0.7), ("B", 0.3)])
    sc = score_forecast(fc, "A")
    # brier = (0.7-1)^2 + (0.3-0)^2 = 0.09 + 0.09 = 0.18
    assert sc["brier"] == 0.18
    assert sc["realized_probability"] == 0.7
    assert sc["outcome_matched_a_scenario"] is True


def test_calibration_report_bins():
    resolved = [
        {"forecast": _fc([("A", 0.9), ("B", 0.1)]), "outcome": "A"},
        {"forecast": _fc([("A", 0.8), ("B", 0.2)]), "outcome": "A"},
        {"forecast": _fc([("A", 0.2), ("B", 0.8)]), "outcome": "B"},
    ]
    rep = calibration_report(resolved, bins=5)
    assert rep["n"] == 3
    assert rep["mean_brier"] is not None
    assert rep["calibration_error"] is not None
    assert sum(b["count"] for b in rep["bins"]) == 6  # 3 forecasts x 2 scenarios
    assert rep["n_unmatched_outcome"] == 0


def test_calibration_report_counts_unmatched_outcomes_additively():
    """EVAL-5: n_unmatched_outcome is additive; an unmatched outcome still scores as an
    all-miss in every legacy number exactly as before."""
    resolved = [
        {"forecast": _fc([("A", 0.9), ("B", 0.1)]), "outcome": "A"},
        {"forecast": _fc([("A", 0.6), ("B", 0.4)]), "outcome": "Neither"},
    ]
    rep = calibration_report(resolved, bins=5)
    assert rep["n_unmatched_outcome"] == 1
    assert set(rep) == {"n", "mean_brier", "calibration_error", "brier_decomposition",
                        "resolution", "insufficient_data", "bins", "n_unmatched_outcome"}
    # Legacy numbers by hand: Brier 0.02 and 0.36 + 0.16; bins hold 0.1/0, 0.4/0, 0.6/0, 0.9/1.
    assert rep["n"] == 2 and rep["mean_brier"] == 0.27
    assert rep["calibration_error"] == 0.3
    assert [(b["count"], b["observed_hit_rate"]) for b in rep["bins"]] == [
        (1, 0.0), (0, None), (1, 0.0), (1, 0.0), (1, 1.0)]
    assert rep["brier_decomposition"] == {"reliability": 0.135, "resolution": 0.1875,
                                          "uncertainty": 0.1875, "brier_pooled": 0.135}
    # Items without a forecast or without scenarios are not unmatched outcomes.
    assert calibration_report([{"forecast": {"scenarios": []}, "outcome": "A"}])[
        "n_unmatched_outcome"] == 0
    assert calibration_report([]) == {"n": 0, "mean_brier": None, "bins": [],
                                      "calibration_error": None, "n_unmatched_outcome": 0}


def test_self_critique_degrades_safely_on_error():
    # FakeLLMClient with no json_responses returns {} -> no scenarios -> returns input unchanged
    fc = _fc([("A", 0.7), ("B", 0.3)])
    out = self_critique_forecast(fc, FakeLLMClient())
    assert out == fc  # unchanged


def test_self_critique_applies_correction():
    fixed = {"scenarios": [{"name": "A", "probability": 0.55, "resolution_criteria": "c",
                            "critique_note": "向基率回归"},
                           {"name": "B", "probability": 0.45, "resolution_criteria": "c"}],
             "confidence": "low"}
    out = self_critique_forecast(_fc([("A", 0.9), ("B", 0.1)]), FakeLLMClient(json_responses=[fixed]))
    assert out["critiqued"] is True
    assert out["confidence"] == "low"
    assert out["scenarios"][0]["critique_note"]
