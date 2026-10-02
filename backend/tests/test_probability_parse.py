"""REPORT-1: typed probability parsing (app/utils/probability_parse.py).

Pure, offline tables pinning the point-field rules, the partition scale rules
and the scoreability predicate.
"""

import dataclasses
import math

import pytest

from app.utils.probability_parse import (
    _RANGE_RE,
    PROB_ABSENT,
    PROB_OK,
    PROB_REVIEW,
    ProbParse,
    is_nullish,
    is_scoreable,
    parse_probability_field,
    parse_scenario_partition,
)


@pytest.mark.parametrize("value, expected, unit", [
    (0.3, 0.3, "fraction"),
    (0, 0.0, "fraction"),
    (1, 1.0, "fraction"),
    ("0.3", 0.3, "plain"),
    (" 0.25 ", 0.25, "plain"),
    ("30%", 0.30, "percent"),
    ("３０％", 0.30, "percent"),           # fullwidth digits and percent sign (NFKC)
    ("30 percent", 0.30, "percent"),
    ("30 Per Cent", 0.30, "percent"),
    ("30pct", 0.30, "percent"),
    ("0%", 0.0, "percent"),
    ("100%", 1.0, "percent"),
])
def test_field_ok(value, expected, unit):
    parsed = parse_probability_field(value)
    assert parsed.status == PROB_OK
    assert parsed.reason == ""
    assert parsed.unit == unit
    assert parsed.value == pytest.approx(expected)
    assert parsed.raw == repr(value)[:80]


@pytest.mark.parametrize("value, status, reason", [
    (True, PROB_REVIEW, "bool"),
    (False, PROB_REVIEW, "bool"),
    (float("nan"), PROB_REVIEW, "non_finite"),
    (float("inf"), PROB_REVIEW, "non_finite"),
    (10 ** 400, PROB_REVIEW, "non_finite"),
    (30, PROB_REVIEW, "plain_gt1"),
    ("30", PROB_REVIEW, "plain_gt1"),
    (-0.1, PROB_REVIEW, "out_of_range"),
    ("130%", PROB_REVIEW, "out_of_range"),
    ("-5%", PROB_REVIEW, "out_of_range"),
    (None, PROB_ABSENT, "nullish"),
    ("N/A", PROB_ABSENT, "nullish"),
    ("unknown", PROB_ABSENT, "nullish"),
    ("未知", PROB_ABSENT, "nullish"),
    ("", PROB_ABSENT, "nullish"),
    ("  ", PROB_ABSENT, "nullish"),
    ("30-40%", PROB_REVIEW, "range"),
    ("0.3 to 0.4", PROB_REVIEW, "range"),
    ("30%～40%", PROB_REVIEW, "range"),
    ("30至40%", PROB_REVIEW, "range"),
    (">30%", PROB_REVIEW, "bound"),
    ("≥ 0.3", PROB_REVIEW, "bound"),
    ("at least 30%", PROB_REVIEW, "bound"),
    ("至少30%", PROB_REVIEW, "bound"),
    ("30%以上", PROB_REVIEW, "bound"),
    ("30% (was 45%)", PROB_REVIEW, "multiple_values"),
    ("~30%", PROB_REVIEW, "unparseable"),
    ("about 30%", PROB_REVIEW, "unparseable"),
    ("likely", PROB_REVIEW, "unparseable"),
    ([0.3], PROB_REVIEW, "unparseable"),
])
def test_field_table(value, status, reason):
    parsed = parse_probability_field(value)
    assert parsed.status == status
    assert parsed.reason == reason
    assert parsed.value is None
    assert parsed.raw == repr(value)[:80]


def test_field_raw_is_truncated_and_result_is_frozen():
    long_text = "x" * 200
    parsed = parse_probability_field(long_text)
    assert isinstance(parsed, ProbParse)
    assert parsed.raw == repr(long_text)[:80]
    with pytest.raises(dataclasses.FrozenInstanceError):
        parsed.value = 0.5


def test_long_text_is_unparseable_without_backtracking():
    # A 50k-digit run used to make the unanchored range search quadratic (about 100 s);
    # over-long unreadable text now skips the reason heuristics entirely.
    digits = "1" * 50_000
    for text in (digits + "x", digits + "-2", "30-40% " + "y" * 60):
        parsed = parse_probability_field(text)
        assert (parsed.status, parsed.reason) == (PROB_REVIEW, "unparseable")
        assert parsed.raw == repr(text)[:80]
    rows, status, reason = parse_scenario_partition([0.5, digits + "x"])
    assert (status, reason) == (PROB_REVIEW, "unparseable")
    # the range pattern can no longer restart inside a digit run
    assert _RANGE_RE.search(digits + "x") is None
    assert _RANGE_RE.search("v" + digits + "-2") is not None
    # a readable value is still read however long its digit string is
    assert parse_probability_field("0." + "3" * 100).value == pytest.approx(1 / 3)


def _values(rows):
    return [row.value for row in rows]


def test_partition_scale():
    rows, status, reason = parse_scenario_partition([0.45, 0.35, 0.2])
    assert (status, reason) == (PROB_OK, "")
    assert _values(rows) == [0.45, 0.35, 0.2]
    assert {row.unit for row in rows} == {"fraction"}

    rows, status, _ = parse_scenario_partition(["45%", "35%", "20%"])
    assert status == PROB_OK
    assert _values(rows) == pytest.approx([0.45, 0.35, 0.20])

    # weights keep their raw values so the caller's renormalisation gives 0.75/0.25
    rows, status, _ = parse_scenario_partition([3, 1])
    assert status == PROB_OK
    assert _values(rows) == [3.0, 1.0]

    rows, status, reason = parse_scenario_partition([0.45, 35, 0.2])
    assert (status, reason) == (PROB_REVIEW, "ambiguous_scale")
    assert _values(rows) == [None, None, None]

    rows, status, _ = parse_scenario_partition(["45%", 35, 20])
    assert status == PROB_OK
    assert _values(rows) == pytest.approx([0.45, 0.35, 0.20])

    rows, status, reason = parse_scenario_partition(["45%", 0.35])
    assert (status, reason) == (PROB_REVIEW, "ambiguous_scale")
    assert _values(rows) == [None, None]

    # an exact zero reads the same on every scale: never ambiguous next to percents
    for zero_mix in (["60%", "40%", 0], ["60%", "40%", 0.0], ["60%", "40%", "0"]):
        rows, status, reason = parse_scenario_partition(zero_mix)
        assert (status, reason) == (PROB_OK, "")
        assert _values(rows) == pytest.approx([0.6, 0.4, 0.0])
    rows, status, _ = parse_scenario_partition([0, "100%"])
    assert status == PROB_OK
    assert _values(rows) == [0.0, 1.0]
    rows, status, _ = parse_scenario_partition(["45%", 35, 0])
    assert status == PROB_OK
    assert _values(rows) == pytest.approx([0.45, 0.35, 0.0])
    # a plain 1 next to percents is still 1% or 100%: ambiguous
    rows, status, reason = parse_scenario_partition(["60%", "39%", 1])
    assert (status, reason) == (PROB_REVIEW, "ambiguous_scale")
    assert _values(rows) == [None, None, None]

    rows, status, reason = parse_scenario_partition([0.5, "N/A", 0.5])
    assert (status, reason) == (PROB_REVIEW, "nullish")
    assert _values(rows) == [0.5, None, 0.5]

    rows, status, reason = parse_scenario_partition([True, 0.5])
    assert (status, reason) == (PROB_REVIEW, "bool")
    assert rows[0].status == PROB_REVIEW and rows[1].value == 0.5

    assert is_scoreable(True) is False


def test_partition_incomplete_scales():
    # an absolute (percent) scale keeps readable rows' canonical values
    rows, status, reason = parse_scenario_partition(["45%", "30-40%", 20])
    assert (status, reason) == (PROB_REVIEW, "range")
    assert _values(rows) == pytest.approx([0.45, None, 0.20])
    # weights of an incomplete partition cannot be normalised: every row is nulled
    rows, status, reason = parse_scenario_partition([45, "N/A", 20])
    assert (status, reason) == (PROB_REVIEW, "nullish")
    assert _values(rows) == [None, None, None]
    assert [row.reason for row in rows] == ["ambiguous_scale", "nullish", "ambiguous_scale"]
    # a plain value that becomes > 100% under the percent scale is out of range
    rows, status, reason = parse_scenario_partition(["45%", 150])
    assert (status, reason) == (PROB_REVIEW, "out_of_range")
    assert _values(rows) == pytest.approx([0.45, None])
    assert parse_scenario_partition([]) == ([], PROB_OK, "")


def test_is_scoreable_and_is_nullish():
    assert is_scoreable(0) and is_scoreable(1) and is_scoreable(0.35)
    for bad in (True, False, None, "0.3", -0.01, 1.01, math.nan, math.inf):
        assert is_scoreable(bad) is False
    assert is_nullish(None) and is_nullish(" N/A ") and is_nullish("待定")
    assert not is_nullish("BLS") and not is_nullish(0)
