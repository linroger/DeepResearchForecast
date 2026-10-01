"""EVAL-14 (P14): structured numeric targets on binary forecasts (binary_targets.py)
and their wiring (FORECAST_BINARY_STRUCTURED_TARGET, default off)."""

import copy
import json
import math

import pytest

from app.config import Config
from app.services import binary_targets as bt
from app.services import forecast_extractor as fe
from app.services.forecast_extractor import _extract_comparable_numeric_range, extract_binary_forecasts
from app.services.forecast_ledger import compact_binary
from tests.conftest import FakeLLMClient

GOOD = {"metric": "US data-centre grid demand", "unit": "GW", "comparator": ">", "threshold": 230,
        "statistic": "value_on", "target_date": "2030-12-31", "window_start": None,
        "resolution_source": "EIA Electric Power Monthly"}


def _valid(target=None, statement="US data-centre grid demand exceeds 230 GW at end-2030",
           criteria="YES if EIA reports US data-centre grid demand above 230 GW for 2030-12-31."):
    return bt.validate_binary_target(dict(GOOD, **(target or {})), statement=statement, criteria=criteria)


# ------------------------------------------------------------------ validation
def test_validate_accepts_and_rejects():
    clean, errors = _valid()
    assert errors == [] and clean["unit"] == "GW" and clean["scale"] == 1.0 and clean["threshold"] == 230
    assert clean["schema"] == bt.SCHEMA and clean["window_start"] is None
    for bad, code in [({"target_date": "2030-13-01"}, "target_date_invalid"),
                      ({"target_date": "31/12/2030"}, "target_date_invalid"),
                      ({"statistic": "max_over_window"}, "window_start_missing"),
                      ({"threshold": float("inf")}, "threshold_not_finite"),
                      ({"threshold": True}, "threshold_invalid"),
                      ({"comparator": "~"}, "comparator_invalid"),
                      ({"metric": "x" * 121}, "metric_too_long"),
                      ({"resolution_source": ""}, "resolution_source_missing"),
                      ({"unit": "% billion"}, "unit_invalid")]:
        clean, errors = _valid(bad)
        assert clean is None and code in errors, bad
    clean, errors = _valid({"statistic": "max_over_window", "window_start": "2031-01-01"})
    assert "window_start_after_target_date" in errors
    assert bt.validate_binary_target("not a target") == (None, ["target_not_object"])


def test_canonical_unit_never_crosses_rate_units():
    assert bt.canonical_unit("percent") == ("%", 1.0) and bt.canonical_unit("pct") == ("%", 1.0)
    assert bt.canonical_unit("percentage points") == ("pp", 1.0) and bt.canonical_unit("pp") == ("pp", 1.0)
    assert bt.canonical_unit("basis points") == ("bp", 1.0) and bt.canonical_unit("bps") == ("bp", 1.0)
    assert bt.canonical_unit("USD billion") == ("USD", 1e9) and bt.canonical_unit("$b") == ("USD", 1e9)
    assert bt.canonical_unit("亿美元") == ("USD", 1e8)
    assert bt.canonical_unit("% billion") is None and bt.canonical_unit("billion bps") is None
    # A rate is never scaled into another rate: a target in % does not match a criteria in pp.
    clean, errors = bt.validate_binary_target(
        dict(GOOD, metric="unemployment rate", unit="pp", comparator=">", threshold=5),
        statement="Unemployment rate rises", criteria="Unemployment rate above 5%")
    assert clean is None and errors[0].startswith("criteria_mismatch")


def test_criteria_unparsed_is_informational_not_error():
    clean, errors = _valid(criteria="Resolves YES if the EIA figure is high.")
    assert errors == [] and clean["criteria_check"] == "criteria_unparsed"


def test_criteria_mismatch_error():
    target = dict(GOOD, metric="revenue", unit="USD billion", threshold=100)
    clean, errors = bt.validate_binary_target(target, statement="Revenue tops $100 billion",
                                              criteria="Revenue exceeds $100 billion")
    assert errors == [] and clean["criteria_check"] == "consistent"
    clean, errors = bt.validate_binary_target(dict(target, threshold=120), statement="Revenue tops",
                                              criteria="Revenue exceeds $100 billion")
    assert clean is None and errors[0].startswith("criteria_mismatch")
    # direction: a ">" target against an upper-bound criterion
    clean, errors = bt.validate_binary_target(target, statement="Revenue stays capped",
                                              criteria="Revenue does not exceed $100 billion")
    assert clean is None and "comparator" in errors[0]


def test_path_dependent_requires_window_stat():
    clean, errors = _valid(statement="Bitcoin trades above $100,000 at any point in 2024")
    assert clean is None and "path_dependent_requires_window_extreme" in errors
    clean, errors = _valid({"statistic": "max_over_window", "window_start": "2024-01-01"},
                           statement="Bitcoin trades above $100,000 at any point in 2024",
                           criteria="任何时候 BTC 价格")
    assert errors == [] and clean["statistic"] == "max_over_window"


# ------------------------------------------------------------------ criteria parser (RESEARCH-15 c)
@pytest.mark.parametrize("criteria,low,high", [
    ("Revenue does not exceed $100 billion", -math.inf, 100.0),
    ("Revenue is no more than $100 billion", -math.inf, 100.0),
    ("Revenue is not above $100 billion", -math.inf, 100.0),
    ("Revenue will not exceed $100 billion", -math.inf, 100.0),
    ("Turnout is not below 60%", 60.0, math.inf),
    ("Turnout is no less than 60%", 60.0, math.inf),
    ("Revenue exceeds $100 billion", 100.0, math.inf),
    ("Revenue is at most $100 billion", -math.inf, 100.0),
])
def test_negated_comparators_read_the_right_way_round(criteria, low, high):
    parsed = _extract_comparable_numeric_range(criteria)
    assert parsed is not None and (parsed["low"], parsed["high"]) == (low, high)


# ------------------------------------------------------------------ ladder audit
def _rung(i, comparator, threshold, p, **target):
    return {"id": f"F{i}", "probability": p,
            "target": dict(bt.validate_binary_target(
                dict(GOOD, comparator=comparator, threshold=threshold, **target),
                statement="", criteria="")[0])}


def test_ladder_audit_violation_and_clean():
    clean = bt.threshold_ladder_audit([_rung(1, ">=", 170, 0.57), _rung(2, ">", 230, 0.12)])
    assert clean == {"groups_checked": 1, "violation_count": 0, "violations": []}
    reversed_ = bt.threshold_ladder_audit([_rung(1, ">=", 170, 0.12), _rung(2, ">", 230, 0.57)])
    assert reversed_["violation_count"] == 1
    assert reversed_["violations"][0]["code"] == "ladder_non_monotone"
    assert reversed_["violations"][0]["ids"] == ["F1", "F2"]
    # "<" rungs are priced as 1 - p exceedance: P(Y < 170) = 0.9 is P(Y >= 170) = 0.1 < 0.57 at 230
    mixed = bt.threshold_ladder_audit([_rung(1, "<", 170, 0.9), _rung(2, ">", 230, 0.57)])
    assert mixed["violation_count"] == 1
    # within the 0.02 tolerance, different targets and single rungs are not violations
    assert bt.threshold_ladder_audit([_rung(1, ">=", 170, 0.50), _rung(2, ">", 230, 0.515)])["violation_count"] == 0
    other_date = _rung(2, ">", 230, 0.9, target_date="2031-12-31")
    assert bt.threshold_ladder_audit([_rung(1, ">=", 170, 0.1), other_date])["groups_checked"] == 0
    assert bt.threshold_ladder_audit([{"id": "F1", "probability": 0.4}, "junk"])["groups_checked"] == 0


def test_resolve_binary_by_target_comparators_and_tolerance():
    target = dict(GOOD)
    assert bt.resolve_binary_by_target(target, 231) == "YES"
    assert bt.resolve_binary_by_target(target, 230) == "NO"
    assert bt.resolve_binary_by_target(dict(target, comparator=">="), 230) == "YES"
    assert bt.resolve_binary_by_target(dict(target, comparator="<"), 229.9) == "YES"
    assert bt.resolve_binary_by_target(dict(target, comparator="=="), 230.0) == "YES"
    tol = dict(target, resolution_tolerance={"epsilon_abs": 2, "basis": "EIA revisions"})
    assert bt.resolve_binary_by_target(tol, 231) == "AMBIGUOUS"
    assert bt.resolve_binary_by_target(tol, 233) == "YES"
    rel = dict(target, resolution_tolerance={"epsilon_rel": 0.01, "basis": "rounding"})
    assert bt.resolve_binary_by_target(rel, 231.5) == "AMBIGUOUS"
    assert bt.resolve_binary_by_target(target, float("nan")) == "UNVERIFIABLE"
    assert bt.resolve_binary_by_target(target, "lots") == "UNVERIFIABLE"
    assert bt.resolve_binary_by_target(dict(target, resolution_tolerance={"epsilon_abs": -1}), 231) == \
        "UNVERIFIABLE"


# ------------------------------------------------------------------ extractor wiring
_DRAW = {"binary_forecasts": [
    {"id": "F1", "statement": "US data-centre grid demand exceeds 230 GW at end-2030", "probability": 0.12,
     "resolution_criteria": "YES if EIA reports demand above 230 GW for 2030-12-31.", "theme": "grid",
     "horizon_year": 2030, "adjustment_rationale": "trend", "target": dict(GOOD)},
    {"id": "F2", "statement": "US data-centre grid demand reaches at least 170 GW at end-2030",
     "probability": 0.57, "resolution_criteria": "YES if EIA reports demand of at least 170 GW.",
     "theme": "grid", "horizon_year": 2030, "adjustment_rationale": "trend",
     "target": dict(GOOD, comparator=">=", threshold=170)},
    {"id": "F3", "statement": "Congress passes a permitting reform by 2027", "probability": 0.35,
     "resolution_criteria": "YES if signed into law by 2027-12-31.", "theme": "policy", "horizon_year": 2027,
     "adjustment_rationale": "base rate", "target": {"metric": "law", "unit": "count"}},
]}


def _extract(monkeypatch, flag):
    monkeypatch.setattr(Config, "FORECAST_BINARY_STRUCTURED_TARGET", flag, raising=False)
    monkeypatch.setattr(Config, "FORECAST_BINARY_CONTRARIAN", False, raising=False)
    monkeypatch.setattr(Config, "FORECAST_ENSEMBLE_MODELS", "", raising=False)
    fake = FakeLLMClient(json_responses=[copy.deepcopy(_DRAW)])
    out = extract_binary_forecasts("dossier", fake, min_count=3, language="English")
    prompts = [c["messages"][-1]["content"] for c in fake.calls if c["kind"] == "chat_json"]
    return out, prompts, [c["max_tokens"] for c in fake.calls if c["kind"] == "chat_json"]


def test_flag_off_prompts_and_rows_byte_identical(monkeypatch):
    out, prompts, max_tokens = _extract(monkeypatch, False)
    assert all("STRUCTURED TARGET" not in p for p in prompts) and max_tokens == [4096]
    assert all("target" not in b and "target_rejected" not in b for b in out["binary_forecasts"])
    assert fe._binary_draw_max_tokens(10, False) == fe._binary_draw_max_tokens(10, False, False) == 4096


def test_flag_on_addendum_once_and_targets_kept(monkeypatch):
    out, prompts, max_tokens = _extract(monkeypatch, True)
    assert sum(p.count("STRUCTURED TARGET") for p in prompts) == 1
    assert max_tokens == [4096 + 64 * 10]
    by_id = {b["id"]: b for b in out["binary_forecasts"]}
    assert by_id["F1"]["target"]["threshold"] == 230 and by_id["F1"]["target"]["unit"] == "GW"
    assert by_id["F2"]["target"]["comparator"] == ">="
    assert "target" not in by_id["F3"] and "unit_invalid" not in by_id["F3"]["target_rejected"]
    assert "comparator_invalid" in by_id["F3"]["target_rejected"]
    # the ledger commit copies the validated target
    assert compact_binary(by_id["F1"])["target"] == by_id["F1"]["target"]
    assert "target" not in compact_binary(by_id["F3"])


def test_flag_on_ladder_audit_reaches_binary_quality_without_an_issue(monkeypatch):
    """The report merges the audit into binary_quality after reconcile; warn only."""
    from app.services.report_agent import ReportAgent
    import inspect
    src = inspect.getsource(ReportAgent._finalize_structured_forecast)
    assert '_quality["threshold_ladder"] = _ladder_audit(forecast["binary_forecasts"])' in src
    out, _p, _m = _extract(monkeypatch, True)
    audit = bt.threshold_ladder_audit(out["binary_forecasts"])
    assert audit["groups_checked"] == 1 and audit["violation_count"] == 0
    assert json.dumps(audit)  # serialisable


def test_knob_defaults_off_and_is_documented():
    import os
    assert Config.FORECAST_BINARY_STRUCTURED_TARGET is False
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert "# FORECAST_BINARY_STRUCTURED_TARGET=false" in open(os.path.join(root, ".env.example"),
                                                                 encoding="utf-8").read()
