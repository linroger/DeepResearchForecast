"""EVAL-14 (P14): structured numeric targets on binary forecasts (binary_targets.py)
and their wiring (FORECAST_BINARY_STRUCTURED_TARGET, default off)."""

import copy
import json
import math
import time

import pytest

from app.config import Config
from app.services import binary_targets as bt
from app.services import forecast_extractor as fe
from app.services import forecast_ledger
from app.services.forecast_extractor import (_extract_comparable_numeric_range,
                                             audit_scenario_contract, extract_binary_forecasts)
from app.services.forecast_ledger import compact_binary
from app.services.report_agent import ReportAgent, ReportManager
from tests import test_binary_quality_rescore as rescore
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


def test_huge_json_integers_never_raise():
    """json.loads keeps a 400-digit literal as an int, and float() of it overflows."""
    huge = json.loads('{"n": ' + "9" * 400 + "}")["n"]
    assert isinstance(huge, int)
    clean, errors = _valid({"threshold": huge})
    assert clean is None and errors == ["threshold_not_finite"]
    clean, errors = _valid({"threshold": "9" * 400})
    assert clean is None and errors == ["threshold_not_finite"]
    clean, errors = _valid({"resolution_tolerance": {"epsilon_abs": huge, "basis": "revisions"}})
    assert clean is None and errors[0].startswith("resolution_tolerance_invalid")
    target = _valid()[0]
    assert bt.resolve_binary_by_target(target, huge) == "UNVERIFIABLE"
    assert bt.resolve_binary_by_target(target, 231, realized_scale=huge) == "UNVERIFIABLE"
    assert bt.resolve_binary_by_target(dict(target, threshold=huge), 231) == "UNVERIFIABLE"
    rows = [{"id": "F1", "probability": 0.5, "target": dict(target, threshold=huge)},
            {"id": "F2", "probability": huge, "target": target},
            {"id": "F3", "probability": 0.4, "target": dict(target, scale=huge)}]
    assert bt.threshold_ladder_audit(rows)["groups_checked"] == 0


def test_window_start_is_ignored_for_non_window_statistics():
    clean, errors = _valid({"window_start": "2030-01-01"})
    assert errors == [] and clean["window_start"] is None
    clean, errors = _valid({"window_start": "not a date"})          # ignored, not an error
    assert errors == [] and clean["window_start"] is None
    with_window = {"id": "F1", "probability": 0.57,
                   "target": dict(_valid({"comparator": ">=", "threshold": 170})[0],
                                  window_start="2030-01-01")}
    without = {"id": "F2", "probability": 0.12, "target": _valid()[0]}
    # two value_on rungs, one carrying a stray window start, still form one ladder
    assert bt.target_group_key(with_window["target"]) == bt.target_group_key(without["target"])
    assert bt.threshold_ladder_audit([with_window, without])["groups_checked"] == 1
    # a window statistic still requires (and keys on) its window start
    clean, errors = _valid({"statistic": "max_over_window", "window_start": "2030-01-01"})
    assert errors == [] and clean["window_start"] == "2030-01-01"


def test_long_whitespace_runs_in_criteria_stay_fast():
    started = time.perf_counter()
    clean, errors = _valid(criteria="失业率" + " " * 5000 + "1%")
    assert errors == [] and clean["criteria_check"] == "criteria_unparsed"
    # collapsing the runs keeps a readable clause readable
    clean, errors = bt.validate_binary_target(
        dict(GOOD, metric="revenue", unit="USD billion", threshold=100), statement="",
        criteria="Revenue   exceeds \t $100 billion")
    assert errors == [] and clean["criteria_check"] == "consistent"
    assert time.perf_counter() - started < 2.0
    # The parser itself collapses the runs, so the uncollapsed scenario-audit path is
    # linear too: digit-terminated runs reach every pattern's value slot.
    started = time.perf_counter()
    assert _extract_comparable_numeric_range("失业率" + " " * 5000 + "1%") is None
    parsed = _extract_comparable_numeric_range("失业率" + " \t" * 2500 + "1%至2%")
    assert parsed is not None and (parsed["low"], parsed["high"]) == (1.0, 2.0)
    parsed = _extract_comparable_numeric_range("失业率" + " " * 5000 + "超过5%")
    assert parsed is not None and (parsed["metric"], parsed["low"]) == ("失业率", 5.0)
    parsed = _extract_comparable_numeric_range("Revenue" + " " * 5000 + "exceeds $100 billion")
    assert parsed is not None and (parsed["metric"], parsed["low"]) == ("revenue", 100.0)
    assert time.perf_counter() - started < 2.0


def test_canonical_unit_never_crosses_rate_units():
    assert bt.canonical_unit("percent") == ("%", 1.0) and bt.canonical_unit("pct") == ("%", 1.0)
    assert bt.canonical_unit("percentage points") == ("pp", 1.0) and bt.canonical_unit("pp") == ("pp", 1.0)
    assert bt.canonical_unit("basis points") == ("bp", 1.0) and bt.canonical_unit("bps") == ("bp", 1.0)
    assert bt.canonical_unit("USD billion") == ("USD", 1e9) and bt.canonical_unit("$b") == ("USD", 1e9)
    assert bt.canonical_unit("亿美元") == ("USD", 1e8)
    assert bt.canonical_unit("% billion") is None and bt.canonical_unit("billion bps") is None
    # A lone K / M / B / T (or mm, tn) is a unit of its own (tonnes, metres, kelvin): a
    # magnitude only next to a currency or a count of units.
    for unit in ("t", "T", "m", "K", "b", "mm", "tn", "m GW"):
        assert bt.canonical_unit(unit) is None, unit
    assert bt.canonical_unit("USD m") == ("USD", 1e6) and bt.canonical_unit("M units") == ("units", 1e6)
    assert _valid({"unit": "t"}) == (None, ["unit_invalid"])
    # A number multiplies the magnitude after it (glued or not); any other number is no unit.
    assert bt.canonical_unit("RMB 100 million") == ("CNY", 1e8)
    assert bt.canonical_unit("USD 100M") == ("USD", 1e8) and bt.canonical_unit("100亿元") == ("CNY", 1e10)
    for unit in ("2020 USD", "billion 2020 USD", "USD 100", "USD 0 million"):
        assert bt.canonical_unit(unit) is None, unit
    assert bt.canonical_unit("3D printers") == ("3D printers", 1.0)
    # "ppt" may be percentage points or parts per trillion; a second magnitude never
    # multiplies the first; a scientific-notation number is no unit word and no magnitude.
    for unit in ("ppt", "ppts", "USD billion billion", "billion 亿美元", "million M units",
                 "USD 1e9", "1E9 USD", "USD 10^9", "1.5e3 units"):
        assert bt.canonical_unit(unit) is None, unit
    assert _valid({"unit": "ppt"}) == (None, ["unit_invalid"])
    assert bt.canonical_unit("deaths per 1e5 people") == ("deaths per 1e5 people", 1.0)
    # A denominator's numbers and magnitudes stay in the label: they divide, never scale.
    assert bt.canonical_unit("deaths per million") == ("deaths per million", 1.0)
    assert bt.canonical_unit("deaths per 100,000 people") == ("deaths per 100,000 people", 1.0)
    assert bt.canonical_unit("例/万人") == ("例/万人", 1.0)
    assert bt.canonical_unit("USD million per year") == ("USD per year", 1e6)
    # so a target in "RMB 100 million" resolves from the same base-unit number as one in 亿元
    clean, errors = _valid({"unit": "RMB 100 million", "threshold": 5})
    assert errors == [] and (clean["unit"], clean["scale"]) == ("CNY", 1e8)
    assert bt.resolve_binary_by_target(clean, 6e8) == "YES"
    assert bt.resolve_binary_by_target(dict(clean, unit="亿元", scale=1e8), 6e8) == "YES"
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
    # "ever" inside a hyphenated compound is no path-dependent wording
    clean, errors = _valid(statement="Ever-growing data-centre demand exceeds 230 GW on 2030-12-31")
    assert errors == [] and clean["statistic"] == "value_on"
    clean, errors = _valid(statement="Grid demand ever exceeds 230 GW in 2030")
    assert clean is None and "path_dependent_requires_window_extreme" in errors


@pytest.mark.parametrize("comparator,statistic,statement,criteria,ok", [
    # min > X is "always above X", not "above X at some point"
    (">", "min_over_window", "Bitcoin trades above $100,000 at any point in 2024", "", False),
    (">=", "min_over_window", "Bitcoin trades above $100,000 at any point in 2024", "", False),
    ("<", "max_over_window", "Bitcoin falls below $100,000 at any point in 2024", "", False),
    ("<", "min_over_window", "Bitcoin falls below $100,000 at any point in 2024", "", True),
    (">", "min_over_window", "比特币2024年任何时候高于10万美元", "", False),
    # the path-dependent clause may sit in the criteria
    (">", "min_over_window", "Bitcoin tops $100k in 2024",
     "YES if BTC trades above $100,000 at any point in 2024, NO otherwise.", False),
    (">", "max_over_window", "Bitcoin tops $100k in 2024",
     "YES if BTC trades above $100,000 at any point in 2024, NO otherwise.", True),
    # a negated or inverted clause reverses the event, so its direction is not read
    ("<=", "max_over_window", "Bitcoin does not trade above $100,000 at any point in 2024", "", True),
    (">=", "min_over_window", "比特币2024年任何时候都不低于10万美元", "", True),
    ("<=", "max_over_window", "Bitcoin stays capped in 2024",
     "Resolves NO if BTC trades above $100,000 at any point in 2024.", True),
    # the negation may sit in a neighbouring comma clause of the same sentence
    ("<=", "max_over_window", "Bitcoin does not, at any point in 2024, trade above $100,000", "",
     True),
    ("<=", "max_over_window", "Bitcoin stays capped in 2024",
     "Resolves NO if, at any point in 2024, BTC trades above $100,000", True),
    ("<=", "max_over_window", "In 2024, at any point, Bitcoin never trades above $100,000", "",
     True),
    # an inverted verdict reverses the event too
    ("<=", "max_over_window", "Bitcoin stays capped in 2024",
     "Resolves negatively if BTC trades above $100,000 at any point in 2024.", True),
    ("<=", "max_over_window", "Bitcoin stays capped in 2024",
     "Fails if, at any point in 2024, BTC trades above $100,000.", True),
    # a closing complement negates nothing, and a plain comma clause is still read
    (">", "min_over_window", "Bitcoin tops $100k in 2024",
     "YES if BTC trades above $100,000 at any point in 2024, otherwise it resolves NO.", False),
    (">", "min_over_window", "Bitcoin tops $100k in 2024",
     "Resolves YES if BTC trades above $100,000 at any point in 2024, and NO if not.", False),
    (">", "min_over_window", "比特币2024年任何时候高于10万美元则为是，否则为否", "", False),
    (">", "min_over_window", "In 2024, at any point, Bitcoin trades above $100,000", "", False),
])
def test_path_dependent_statistic_is_on_the_comparator_side(comparator, statistic, statement,
                                                             criteria, ok):
    clean, errors = _valid({"comparator": comparator, "statistic": statistic,
                            "window_start": "2024-01-01"}, statement=statement, criteria=criteria)
    if ok:
        assert errors == [] and clean["statistic"] == statistic
    else:
        expected = "max_over_window" if comparator in (">", ">=") else "min_over_window"
        assert clean is None
        assert errors == [f"path_dependent_statistic_direction: {comparator} needs {expected}"]


# ------------------------------------------------------------------ criteria parser (RESEARCH-15 c)
@pytest.mark.parametrize("criteria,low,high,inclusive", [
    ("Revenue does not exceed $100 billion", -math.inf, 100.0, True),
    ("Revenue is no more than $100 billion", -math.inf, 100.0, True),
    ("Revenue is not above $100 billion", -math.inf, 100.0, True),
    ("Revenue will not exceed $100 billion", -math.inf, 100.0, True),
    ("Turnout is not below 60%", 60.0, math.inf, True),
    ("Turnout is no less than 60%", 60.0, math.inf, True),
    ("Revenue exceeds $100 billion", 100.0, math.inf, False),
    ("Revenue is at most $100 billion", -math.inf, 100.0, True),
    ("Revenue is below $100 billion", -math.inf, 100.0, False),
    # Chinese negated forms, incl. the 不超过 family
    ("失业率不超过5%", -math.inf, 5.0, True),
    ("失业率不高于5%", -math.inf, 5.0, True),
    ("失业率不大于5%", -math.inf, 5.0, True),
    ("失业率不多于5%", -math.inf, 5.0, True),
    ("失业率不低于5%", 5.0, math.inf, True),
    ("失业率不少于5%", 5.0, math.inf, True),
    ("失业率不小于5%", 5.0, math.inf, True),
    ("失业率超过5%", 5.0, math.inf, False),
])
def test_negated_comparators_read_the_right_way_round(criteria, low, high, inclusive):
    parsed = _extract_comparable_numeric_range(criteria)
    assert parsed is not None and (parsed["low"], parsed["high"]) == (low, high)
    assert parsed["metric"] in ("revenue", "turnout", "失业率")
    assert parsed["inclusive"] is inclusive


@pytest.mark.parametrize("criteria", [
    "Revenue will not be above $100 billion",
    "Revenue never exceeds $100 billion",
    "Revenue cannot exceed $100 billion",
    "Revenue fails to exceed $100 billion",
    "Revenue is not expected to exceed $100 billion",
    "Revenue does not rise above $100 billion",
    "Revenue does not fall below $100 billion",
    "Revenue does not go below $100 billion",
    "Revenue is not between $1 billion and $2 billion",
    "Resolves YES unless unemployment rate exceeds 5%",
    "Resolves YES except if revenue exceeds $100 billion",
    "Revenue doesnt exceed $100 billion",
    "Revenue wont exceed $100 billion",
    "Revenue is unlikely to exceed $100 billion",
    "Revenue hardly exceeds $100 billion",
    "失业率不会超过5%",
    "失业率未超过5%",
    "失业率没有超过5%",
    "失业率未能超过5%",
    "失业率不在4%至5%之间",
    # a negation character among the metric's last three characters, whatever follows it
    "失业率未曾超过5%",
    "失业率无法超过5%",
    "失业率没能超过5%",
    "失业率不可能超过5%",
    "失业率不可超过5%",
    "失业率不宜超过5%",
    "失业率不必超过5%",
    "失业率未必超过5%",
    "失业率不至于超过5%",
    "失业率不太可能超过5%",
    "截至2030年，失业率未曾超过5%",
    # an inverted verdict before the condition: YES needs the complement
    "Resolves negatively if revenue exceeds $100 billion",
    "Resolves false if revenue exceeds $100 billion",
    "Resolves as N if revenue exceeds $100 billion",
    "Resolves to 0 if revenue exceeds $100 billion",
    "Resolves in the negative if revenue exceeds $100 billion",
    "Fails if revenue exceeds $100 billion",
    "Also falsified if global EV share by 2032 falls below 55%",
    "This resolves negatively for revenue above $100 billion",
])
def test_negation_swallowed_by_the_metric_is_never_parsed(criteria):
    """A negation the metric swallowed would flip the bare comparator after it."""
    assert _extract_comparable_numeric_range(criteria) is None


@pytest.mark.parametrize("criteria,metric,low,high", [
    ("南非通胀率超过5%", "南非通胀率", 5.0, math.inf),
    ("不良贷款率超过5%", "不良贷款率", 5.0, math.inf),
    ("非农就业增速超过5%", "非农就业增速", 5.0, math.inf),
    ("无人机出货量超过500 units", "无人机出货量", 500.0, math.inf),
    ("Non-farm payrolls exceed 200 thousand", "non-farm payrolls", 200.0, math.inf),
    # the negation sits in the comparator the parser reads, not in the metric
    ("失业率并不超过5%", "失业率并", -math.inf, 5.0),
    ("失业率绝不超过5%", "失业率绝", -math.inf, 5.0),
    ("失业率从不超过5%", "失业率从", -math.inf, 5.0),
    # a YES verdict reads, and a NO word outside a verdict is part of the metric
    ("Resolves YES if revenue exceeds $100 billion", "resolves yes if revenue", 100.0, math.inf),
    ("Verified if revenue exceeds $100 billion", "verified if revenue", 100.0, math.inf),
    ("False positive rate exceeds 5%", "false positive rate", 5.0, math.inf),
])
def test_negation_characters_inside_a_metric_stay_readable(criteria, metric, low, high):
    parsed = _extract_comparable_numeric_range(criteria)
    assert parsed is not None and (parsed["metric"], parsed["low"], parsed["high"]) == (metric, low, high)


def test_negated_criteria_never_stamp_an_inverted_target_consistent():
    target = dict(GOOD, metric="revenue", unit="USD billion", threshold=100)
    # the inverted target is no longer accepted as "consistent" (the clause is unverifiable)
    clean, errors = bt.validate_binary_target(
        target, statement="Revenue stays capped", criteria="Revenue will not be above $100 billion")
    assert errors == [] and clean["criteria_check"] == "criteria_unparsed"
    # the right-way-round target is no longer rejected as a mismatch
    clean, errors = bt.validate_binary_target(
        dict(target, comparator="<="), statement="Revenue stays capped",
        criteria="Revenue does not exceed $100 billion")
    assert errors == [] and clean["criteria_check"] == "consistent"
    clean, errors = bt.validate_binary_target(
        dict(target, comparator="<="), statement="营收封顶", criteria="营收不高于$100 billion")
    assert errors == [] and clean["criteria_check"] == "consistent"
    # 未曾 ("never") swallowed by the metric: the inverted target is unverifiable, never
    # "consistent", and the right-way-round one is never rejected as a mismatch.
    # an inverted verdict ("Fails if") is unverifiable too, never "consistent"
    for comparator in (">", "<="):
        clean, errors = bt.validate_binary_target(
            dict(target, comparator=comparator), statement="Revenue stays capped",
            criteria="Fails if revenue exceeds $100 billion")
        assert errors == [] and clean["criteria_check"] == "criteria_unparsed", comparator
    rate = dict(GOOD, metric="失业率", unit="%", threshold=5)
    for comparator in (">", "<="):
        clean, errors = bt.validate_binary_target(
            dict(rate, comparator=comparator), statement="失业率封顶",
            criteria="截至2030年，失业率未曾超过5%")
        assert errors == [] and clean["criteria_check"] == "criteria_unparsed", comparator


@pytest.mark.parametrize("unit,threshold,criteria,check", [
    ("GW", 230, "Output exceeds 230 tons", "criteria_unparsed"),
    ("barrels", 230, "Output exceeds 230 tonnes", "criteria_unparsed"),
    ("units", 230, "Seats exceed 230 seats", "criteria_unparsed"),
    ("tonnes", 230, "Output exceeds 230 tons", "criteria_unparsed"),     # short ton != tonne
    ("Seat", 230, "Seats exceed 230 seats", "consistent"),               # singular = plural
    ("million units", 5, "Shipments exceed 5 million", "consistent"),    # a count = units
    ("tons", 230, "Output exceeds 230 tons", "consistent"),
])
def test_plain_units_must_agree_to_be_consistent(unit, threshold, criteria, check):
    """Neither a currency nor a rate: different labels are not comparable, so the clause is
    unverifiable, never a positive "consistent"."""
    clean, errors = bt.validate_binary_target(
        dict(GOOD, metric="output", unit=unit, threshold=threshold), statement="", criteria=criteria)
    assert errors == [] and clean["criteria_check"] == check


def test_strict_vs_inclusive_comparator_is_consistent_bound_only():
    target = dict(GOOD, metric="revenue", unit="USD billion", threshold=100)
    for comparator, criteria in ((">", "Revenue is at least $100 billion"),
                                 (">=", "Revenue exceeds $100 billion"),
                                 ("<", "Revenue does not exceed $100 billion")):
        clean, errors = bt.validate_binary_target(dict(target, comparator=comparator),
                                                  statement="", criteria=criteria)
        assert errors == [] and clean["criteria_check"] == "consistent_bound_only", comparator
    clean, _errors = bt.validate_binary_target(dict(target, comparator=">="), statement="",
                                               criteria="Revenue is at least $100 billion")
    assert clean["criteria_check"] == "consistent"


def test_scenario_audit_reads_negated_partitions_flag_independently(monkeypatch):
    """The parser fix is not behind the flag: the scenario partition audit now reads a
    negated bin under its real metric (correct partitions stay valid, overlaps surface)."""
    monkeypatch.setattr(Config, "FORECAST_BINARY_STRUCTURED_TARGET", False, raising=False)

    def audit(capped, other_name="Other"):
        return audit_scenario_contract({"scenarios": [
            {"name": "Capped", "probability": 0.4, "resolution_criteria": capped},
            {"name": "Breakout", "probability": 0.4,
             "resolution_criteria": "Revenue exceeds $100 billion"},
            {"name": other_name, "probability": 0.2, "resolution_criteria": "All other outcomes"},
        ]})

    def overlaps(result):
        return [e for e in result["examples"] if e["code"] == "overlapping_numeric_ranges"]

    assert audit("Revenue does not exceed $100 billion")["valid"] is True
    assert audit("Revenue is no more than $100 billion")["valid"] is True
    overlap = overlaps(audit("Revenue does not exceed $120 billion"))
    assert len(overlap) == 1 and overlap[0]["metric"] == "revenue"
    assert overlap[0]["overlap"] == [100.0, 120.0]
    # a negation the metric swallowed is skipped, never read as a second lower bound
    assert not overlaps(audit("Revenue will not be above $120 billion"))
    # so is an inverted verdict ("Fails if" holds only below the bound)
    assert not overlaps(audit("Fails if revenue exceeds $120 billion"))
    # Horizontal whitespace runs (a tab, U+3000) read as one space: such a clause now parses.
    for gap in ("\t", "\u3000", " \t "):
        parsed = _extract_comparable_numeric_range(f"Data{gap}centre demand exceeds $100 billion")
        assert parsed is not None and parsed["metric"] == "data centre demand", repr(gap)


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
    # One threshold in two magnitudes (2.3 * 1e8 == 229999999.99999997): the coherent pair
    # P(Y >= K) = 0.60 >= P(Y > K) = 0.50 is clean, the reversed pricing is not.
    coherent = bt.threshold_ladder_audit([_rung(1, ">", 2.3, 0.50, unit="亿元"),
                                          _rung(2, ">=", 230, 0.60, unit="百万元")])
    assert coherent == {"groups_checked": 1, "violation_count": 0, "violations": []}
    reversed_ = bt.threshold_ladder_audit([_rung(1, ">", 2.3, 0.60, unit="亿元"),
                                           _rung(2, ">=", 230, 0.50, unit="百万元")])
    assert reversed_["violation_count"] == 1 and reversed_["violations"][0]["ids"] == ["F2", "F1"]
    assert reversed_["violations"][0]["code"] == "ladder_non_monotone"
    other_date = _rung(2, ">", 230, 0.9, target_date="2031-12-31")
    assert bt.threshold_ladder_audit([_rung(1, ">=", 170, 0.1), other_date])["groups_checked"] == 0
    assert bt.threshold_ladder_audit([{"id": "F1", "probability": 0.4}, "junk"])["groups_checked"] == 0


def test_short_metric_codes_join_a_ladder():
    """A short code the extractor's label normaliser blanks (M2) still links its rungs, so a
    non-monotone M2 pair is never a silent miss; a generic label stays unlinkable."""
    rows = [_rung(1, ">", 300, 0.2, metric="M2", unit="CNY trillion"),
            _rung(2, ">", 350, 0.7, metric="M2", unit="CNY trillion")]
    audit = bt.threshold_ladder_audit(rows)
    assert audit["groups_checked"] == 1 and audit["violation_count"] == 1
    assert audit["violations"][0]["group"]["metric"] == "m2"
    assert bt.target_group_key(dict(rows[0]["target"], metric=" m2 ")) == bt.target_group_key(
        rows[0]["target"])
    for generic in ("value", "Metric", "2030", "-"):
        assert bt.target_group_key(dict(rows[0]["target"], metric=generic)) is None, generic


def test_ladder_label_keeps_the_magnitude():
    rows = [{"id": "F1", "probability": 0.40, "target": _usd(800, "USD billion")},
            {"id": "F2", "probability": 0.60, "target": _usd(1, "USD trillion")}]
    audit = bt.threshold_ladder_audit(rows)
    assert audit["groups_checked"] == 1 and audit["violation_count"] == 1
    reason = audit["violations"][0]["reason"]
    assert "P(Y > 1 trillion USD) = 0.60" in reason and "P(Y > 800 billion USD) = 0.40" in reason


def test_bound_only_target_is_ambiguous_exactly_at_the_threshold():
    """A consistent_bound_only target differs from its criteria only in strictness, so the
    two give opposite answers at the threshold itself, and only there."""
    rate = dict(GOOD, metric="unemployment rate", unit="%", comparator="<", threshold=5)
    target, errors = bt.validate_binary_target(rate, statement="",
                                               criteria="Unemployment rate does not exceed 5%")
    assert errors == [] and target["criteria_check"] == "consistent_bound_only"
    assert bt.resolve_binary_by_target(target, 5.0) == "AMBIGUOUS"
    assert bt.resolve_binary_by_target(target, 4.9) == "YES"
    assert bt.resolve_binary_by_target(target, 5.1) == "NO"
    revenue = dict(GOOD, metric="revenue", unit="USD billion", comparator=">", threshold=100)
    target, errors = bt.validate_binary_target(revenue, statement="",
                                               criteria="Revenue is at least $100 billion")
    assert errors == [] and target["criteria_check"] == "consistent_bound_only"
    assert bt.resolve_binary_by_target(target, 100e9) == "AMBIGUOUS"
    assert bt.resolve_binary_by_target(target, 100, realized_scale=1e9) == "AMBIGUOUS"
    assert bt.resolve_binary_by_target(target, 101, realized_scale=1e9) == "YES"
    # a target that agrees with its criteria settles its boundary
    target, errors = bt.validate_binary_target(dict(rate, comparator="<="), statement="",
                                               criteria="Unemployment rate does not exceed 5%")
    assert errors == [] and target["criteria_check"] == "consistent"
    assert bt.resolve_binary_by_target(target, 5.0) == "YES"


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
    # a raw target without a readable unit has no known scale
    assert bt.resolve_binary_by_target(dict(target, unit="% billion"), 231) == "UNVERIFIABLE"


def _usd(threshold, unit, comparator=">", **extra):
    clean, errors = bt.validate_binary_target(
        dict(GOOD, metric="hyperscaler capex", unit=unit, comparator=comparator,
             threshold=threshold, **extra), statement="", criteria="")
    assert errors == [], errors
    return clean


def test_mixed_scale_group_resolves_from_one_base_unit_observation():
    """target_group_key folds the magnitude out, so resolution compares in base units."""
    billion, trillion = _usd(800, "USD billion"), _usd(1, "USD trillion")
    assert bt.target_group_key(billion) == bt.target_group_key(trillion)
    # true value USD 900 billion: above 800 billion, below 1 trillion
    assert [bt.resolve_binary_by_target(t, 900e9) for t in (billion, trillion)] == ["YES", "NO"]
    assert [bt.resolve_binary_by_target(t, 900, realized_scale=1e9)
            for t in (billion, trillion)] == ["YES", "NO"]
    assert [bt.resolve_binary_by_target(t, 0.9, realized_scale=1e12)
            for t in (billion, trillion)] == ["YES", "NO"]
    # an absolute tolerance is pre-registered in the target's own unit and scale
    tol = _usd(800, "USD billion", resolution_tolerance={"epsilon_abs": 5, "basis": "restatements"})
    assert bt.resolve_binary_by_target(tol, 803e9) == "AMBIGUOUS"
    assert bt.resolve_binary_by_target(tol, 806e9) == "YES"
    # float noise of threshold * scale never flips a boundary (2.3 * 1e8 != 2.3e8 in floats)
    yi = bt.validate_binary_target(dict(GOOD, metric="营收", unit="亿元", threshold=2.3),
                                   statement="", criteria="")[0]
    assert yi["scale"] == 1e8 and 2.3 * 1e8 != 2.3e8
    assert bt.resolve_binary_by_target(yi, 2.3e8) == "NO"
    assert bt.resolve_binary_by_target(dict(yi, comparator=">="), 2.3e8) == "YES"
    assert bt.resolve_binary_by_target(dict(yi, comparator="=="), 2.3e8) == "YES"
    for bad_scale in (0, -1e9, float("nan"), "1e9", True):
        assert bt.resolve_binary_by_target(billion, 900, realized_scale=bad_scale) == "UNVERIFIABLE"


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
    {"id": "F4", "statement": "The Senate confirms a new FERC chair by 2027", "probability": 0.6,
     "resolution_criteria": "YES if confirmed by 2027-12-31.", "theme": "policy", "horizon_year": 2027,
     "adjustment_rationale": "base rate", "target": {}},
]}
_TARGET_KEYS = ("target", "target_rejected")


def _extract(monkeypatch, flag, draw=None):
    monkeypatch.setattr(Config, "FORECAST_BINARY_STRUCTURED_TARGET", flag, raising=False)
    monkeypatch.setattr(Config, "FORECAST_BINARY_CONTRARIAN", False, raising=False)
    monkeypatch.setattr(Config, "FORECAST_ENSEMBLE_MODELS", "", raising=False)
    fake = FakeLLMClient(json_responses=[copy.deepcopy(draw or _DRAW)])
    out = extract_binary_forecasts("dossier", fake, min_count=4, language="English")
    prompts = [c["messages"][-1]["content"] for c in fake.calls if c["kind"] == "chat_json"]
    return out, prompts, [c["max_tokens"] for c in fake.calls if c["kind"] == "chat_json"]


def test_flag_off_prompts_and_rows_byte_identical(monkeypatch):
    out_off, prompts_off, max_tokens_off = _extract(monkeypatch, False)
    assert all("STRUCTURED TARGET" not in p for p in prompts_off) and max_tokens_off == [4096]
    assert all(key not in b for b in out_off["binary_forecasts"] for key in _TARGET_KEYS)
    assert fe._binary_draw_max_tokens(10, False) == fe._binary_draw_max_tokens(10, False, False) == 4096
    # byte identity: the flag adds exactly the rule to the prompt and only the target keys
    # to the rows; everything else (prompt text, rows, scorecard) is unchanged
    out_on, prompts_on, _max_tokens_on = _extract(monkeypatch, True)
    assert len(prompts_on) == len(prompts_off) == 1
    assert prompts_on[0].replace(fe._BINARY_TARGET_RULE, "") == prompts_off[0]
    stripped = [{k: v for k, v in b.items() if k not in _TARGET_KEYS} for b in out_on["binary_forecasts"]]
    assert json.dumps(stripped, sort_keys=True) == json.dumps(out_off["binary_forecasts"], sort_keys=True)
    assert out_on["binary_quality"] == out_off["binary_quality"]


def test_flag_on_addendum_once_and_targets_kept(monkeypatch):
    out, prompts, max_tokens = _extract(monkeypatch, True)
    assert sum(p.count("STRUCTURED TARGET") for p in prompts) == 1
    assert max_tokens == [4096 + fe._BINARY_TARGET_TOKENS_PER_ROW * 10]
    assert fe._BINARY_TARGET_TOKENS_PER_ROW >= 112   # a long pretty-printed target is ~123 tokens
    by_id = {b["id"]: b for b in out["binary_forecasts"]}
    assert by_id["F1"]["target"]["threshold"] == 230 and by_id["F1"]["target"]["unit"] == "GW"
    assert by_id["F2"]["target"]["comparator"] == ">="
    assert "target" not in by_id["F3"] and "unit_invalid" not in by_id["F3"]["target_rejected"]
    assert "comparator_invalid" in by_id["F3"]["target_rejected"]
    # an empty target object is an omission, not seven error codes
    assert not any(key in by_id["F4"] for key in _TARGET_KEYS)
    # the ledger commit copies the validated target
    assert compact_binary(by_id["F1"])["target"] == by_id["F1"]["target"]
    assert "target" not in compact_binary(by_id["F3"])


def test_target_validation_error_keeps_every_binary(monkeypatch):
    """An unexpected validator failure records target_rejected; it never drops the draw."""
    def boom(*_args, **_kwargs):
        raise OverflowError("int too large to convert to float")

    monkeypatch.setattr(bt, "validate_binary_target", boom)
    out, _prompts, _max_tokens = _extract(monkeypatch, True)
    by_id = {b["id"]: b for b in out["binary_forecasts"]}
    assert set(by_id) == {"F1", "F2", "F3", "F4"}
    assert by_id["F1"]["target_rejected"] == ["target_validation_error"]
    assert "target" not in by_id["F1"] and not any(key in by_id["F4"] for key in _TARGET_KEYS)


def test_huge_threshold_in_a_draw_is_rejected_not_raised(monkeypatch):
    draw = copy.deepcopy(_DRAW)
    draw["binary_forecasts"][0]["target"]["threshold"] = json.loads("9" * 400)
    out, _prompts, _max_tokens = _extract(monkeypatch, True, draw=draw)
    by_id = {b["id"]: b for b in out["binary_forecasts"]}
    assert by_id["F1"]["target_rejected"] == ["threshold_not_finite"]
    assert by_id["F2"]["target"]["threshold"] == 170


# ------------------------------------------------------------------ report path
def _ladder_rows():
    """Binaries with validated targets on one ladder: P(Y > 230 GW) = 0.57 above
    P(Y >= 170 GW) = 0.12 is non-monotone; F3 carries no target."""
    rows = []
    for i, (comparator, threshold, p) in enumerate(((">=", 170, 0.12), (">", 230, 0.57)), 1):
        stmt = f"US data-centre grid demand {comparator} {threshold} GW at end-2030"
        criteria = f"YES if EIA reports demand {comparator} {threshold} GW for 2030-12-31."
        target, errors = bt.validate_binary_target(
            dict(GOOD, comparator=comparator, threshold=threshold), statement=stmt, criteria=criteria)
        assert errors == []
        rows.append({"id": f"F{i}", "statement": stmt, "probability": p,
                     "resolution_criteria": criteria, "theme": "grid", "horizon_year": 2030,
                     "criteria_sharp": True, "target": target})
    rows.append({"id": "F3", "statement": "Congress passes a permitting reform by 2027",
                 "probability": 0.35, "resolution_criteria": "YES if signed into law by 2027-12-31.",
                 "theme": "policy", "horizon_year": 2027, "criteria_sharp": True})
    return rows


@pytest.fixture
def finalize_env(monkeypatch, tmp_path):
    """The offline _finalize_structured_forecast harness of test_binary_quality_rescore."""
    for key, value in (("UPLOAD_FOLDER", str(tmp_path)), ("FORECAST_LEDGER_DIR", str(tmp_path / "ledger")),
                       ("REPORT_PUBLISH_GATE", False), ("REPORT_REPAIR_PASSES", False),
                       ("REPORT_FORECAST_SELF_CRITIQUE", False), ("REPORT_SPINE_SELFCONSISTENCY_K", 1),
                       ("FORECAST_EMIT_BINARY", True), ("PREDICTION_MARKETS_ENABLED", False),
                       ("FORECAST_BINARY_THEMES", None), ("BINARY_FORECASTS_MIN_COUNT", 10)):
        monkeypatch.setattr(Config, key, value, raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(forecast_ledger, "append_forecast", lambda forecast, **kw: None)

    def fake_extract(*_args, **kwargs):
        rows = _ladder_rows()
        return {"binary_forecasts": rows,
                "binary_quality": fe._binary_quality(rows, min_count=kwargs["min_count"],
                                                     themes_expected=kwargs.get("themes"))}

    monkeypatch.setattr(fe, "extract_binary_forecasts", fake_extract)
    monkeypatch.setattr(fe, "reconcile_forecast_contract",
                        lambda forecast, *a, **kw: {"checked": 0, "stub": True})
    return tmp_path


def _finalize_with_flag(monkeypatch, tmp_path, flag, report_id):
    monkeypatch.setattr(Config, "FORECAST_BINARY_STRUCTURED_TARGET", flag, raising=False)
    rescore._agent()._finalize_structured_forecast(report_id, "# T\n\nBody.")
    return rescore._forecast(tmp_path, report_id)


def _diff_paths(left, right, path=""):
    """The key paths at which two JSON values differ."""
    if isinstance(left, dict) and isinstance(right, dict):
        out = set()
        for key in set(left) | set(right):
            sub = f"{path}.{key}" if path else key
            if key not in left or key not in right:
                out.add(sub)
            else:
                out |= _diff_paths(left[key], right[key], sub)
        return out
    return set() if left == right else {path}


def test_report_path_ladder_audit_is_warn_only_and_absent_with_the_flag_off(monkeypatch, finalize_env):
    off = _finalize_with_flag(monkeypatch, finalize_env, False, "report_ladder_off")
    on = _finalize_with_flag(monkeypatch, finalize_env, True, "report_ladder_on")
    ladder = on["binary_quality"]["threshold_ladder"]
    assert ladder["groups_checked"] == 1 and ladder["violation_count"] >= 1
    assert ladder["violations"][0]["code"] == "ladder_non_monotone"
    assert ladder["violations"][0]["ids"] == ["F1", "F2"]
    # flag off: no audit key; the targets the (stubbed) extractor returned pass through
    assert "threshold_ladder" not in off["binary_quality"]
    # warn only: the scorecard, its issues and verdict are identical with the flag on
    bq_on = {k: v for k, v in on["binary_quality"].items() if k != "threshold_ladder"}
    assert bq_on == off["binary_quality"]
    assert on["binary_quality"]["issues"] == off["binary_quality"]["issues"]
    assert on["binary_quality"]["passed"] == off["binary_quality"]["passed"]
    # and so is everything the publish gate reads from the forecast
    gated_on = ReportAgent._apply_publish_gate(dict(on, citation_audit={"coverage": 1.0}))
    gated_off = ReportAgent._apply_publish_gate(dict(off, citation_audit={"coverage": 1.0}))
    for key in ("passed", "confidence", "epistemic_issues", "issues"):
        assert gated_on["quality"].get(key) == gated_off["quality"].get(key), key
    assert gated_on.get("confidence") == gated_off.get("confidence")
    # the only forecast.json differences are the audit, the recorded prompt policy and
    # per-run identity / timestamps
    policy = {"binary_symmetric_guard": False, "binary_structured_target": True}
    assert on["quality"]["forecast_policy"] == policy
    assert "forecast_policy" not in off["quality"]
    allowed = {"binary_quality.threshold_ladder", "quality.forecast_policy",
               "quality.probability_shape.policy.binary_structured_target"}
    diff = _diff_paths(on, off)
    assert allowed <= diff
    extra = {p for p in diff - allowed
             if not any(token in p for token in ("report_id", "_at", "timestamp"))}
    assert extra == set(), extra


def test_backfill_rebuild_keeps_the_ladder_audit():
    from scripts.backfill_report_visuals import rebuild_binary_quality
    rows = _ladder_rows()
    rebuilt = rebuild_binary_quality(rows, {"checked": 0}, {"ensemble": {"pooled_models": ["kimi"]}})
    assert rebuilt["threshold_ladder"]["violation_count"] == 1
    assert rebuilt["ensemble"] == {"pooled_models": ["kimi"]}
    assert rebuilt["proposition_consistency"] == {"checked": 0}
    # a replay that removed a rung recomputes the audit over the retained rows
    rebuilt = rebuild_binary_quality(rows[1:], {}, {"threshold_ladder": {"violation_count": 1}})
    assert rebuilt["threshold_ladder"]["violation_count"] == 0
    # a report without targets keeps the old shape
    plain = [{k: v for k, v in row.items() if k != "target"} for row in rows]
    assert "threshold_ladder" not in rebuild_binary_quality(plain, {}, {})


def test_knob_defaults_off_and_is_documented():
    import os
    assert Config.FORECAST_BINARY_STRUCTURED_TARGET is False
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert "# FORECAST_BINARY_STRUCTURED_TARGET=false" in open(os.path.join(root, ".env.example"),
                                                                 encoding="utf-8").read()


def test_config_hash_tells_structured_target_runs_apart_and_keeps_flag_off_bytes():
    """The knob changes the binary prompt and max_tokens, so on and off runs never share a
    config_hash; it is recorded only when on, so a flag-off fingerprint is exactly the one
    a config without the knob (before EVAL-14) produced."""
    from types import SimpleNamespace

    from app.utils import cost_accounting as ca

    knobs = {"FORECAST_ENSEMBLE_MODELS": "", "FORECAST_MARKET_ANCHORING": True,
             "PREDICTION_MARKETS_ENABLED": True}
    options = {"safety_policy_v1": {"n_forecast_seeds": 1}, "max_rounds": 9}

    def fingerprint(**extra):
        return ca.config_fingerprint(options, None, config=SimpleNamespace(**knobs, **extra))

    before = fingerprint()
    off = fingerprint(FORECAST_BINARY_STRUCTURED_TARGET=False)
    on = fingerprint(FORECAST_BINARY_STRUCTURED_TARGET=True)
    assert off == before and ca.config_hash(off) == ca.config_hash(before)
    assert set(off["forecast"]) == {"ensemble_models", "market_anchoring",
                                    "prediction_markets_enabled"}
    assert on["forecast"] == dict(off["forecast"], binary_structured_target=True)
    assert ca.config_hash(on) != ca.config_hash(off)
    assert "binary_structured_target" not in ca.config_fingerprint(options, None)["forecast"]
