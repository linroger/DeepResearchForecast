"""TIME-8: the point-in-time availability rule of deerflow_bridge/source_dates.py.

``resolve_upper`` reads a date as the latest day it is consistent with,
``availability`` is the later of a source's published and modified days, and
``gate`` is the one cut rule of a gated hindcast (strict by default: the as-of
day itself is late).  Pure and offline.
"""

from __future__ import annotations

import datetime as dt
import os
import sys

import pytest

_BRIDGE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "deerflow_bridge")
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

import source_dates as sd  # noqa: E402

NOW = dt.datetime(2026, 9, 30, 12, 0, tzinfo=dt.timezone.utc)
AS_OF = dt.date(2024, 6, 1)


@pytest.mark.parametrize("value, expected", [
    ("2024-03", dt.date(2024, 3, 31)),
    ("2024-02", dt.date(2024, 2, 29)),
    ("Q3 2024", dt.date(2024, 9, 30)),
    ("2024Q3", dt.date(2024, 9, 30)),
    ("2024-q1", dt.date(2024, 3, 31)),
    ("q4 2024", dt.date(2024, 12, 31)),
    ("H1 2025", dt.date(2025, 6, 30)),
    ("2025H2", dt.date(2025, 12, 31)),
    ("2024", dt.date(2024, 12, 31)),
    ("2024-05-09", dt.date(2024, 5, 9)),
    ("May 2024", dt.date(2024, 5, 31)),
    ("May 9, 2024", dt.date(2024, 5, 9)),
    # An offset is applied before the day is taken (TIME-2's UTC calendar).
    ("2024-06-01T23:30:00-05:00", dt.date(2024, 6, 2)),
    (dt.date(2024, 5, 9), dt.date(2024, 5, 9)),
    (dt.datetime(2024, 5, 9, 23, 0, tzinfo=dt.timezone(dt.timedelta(hours=-3))), dt.date(2024, 5, 10)),
    (1717200000, dt.date(2024, 6, 1)),
    # A date after today is kept (it is after any as-of), never rejected as "future".
    ("2027-01-05", dt.date(2027, 1, 5)),
    ("Q2 2030", dt.date(2030, 6, 30)),
])
def test_resolve_upper_reads_the_latest_consistent_day(value, expected):
    assert sd.resolve_upper(value, now=NOW) == expected


@pytest.mark.parametrize("value", ["garbage", "", "   ", None, True, "Q5 2024", "H3 2024", "1899", "1899-12",
                                   {"published": "2024"}, ["2024"], "2024-13", "FY2024"])
def test_resolve_upper_is_none_for_anything_else(value):
    assert sd.resolve_upper(value, now=NOW) is None


def test_resolve_upper_reads_a_pubdate():
    parsed, _ = sd.parse_published("2024-05", now=NOW)
    assert sd.resolve_upper(parsed) == dt.date(2024, 5, 31)


@pytest.mark.parametrize("value, expected", [
    ("3 days ago", dt.date(2026, 9, 27)),
    ("an hour ago", dt.date(2026, 9, 30)),
    ("5 mins ago", dt.date(2026, 9, 30)),
    ("yesterday", dt.date(2026, 9, 29)),
    ("Today", dt.date(2026, 9, 30)),
    ("2 weeks ago", dt.date(2026, 9, 16)),
    # Months and years are counted short (28 / 365 days): the day read is never
    # earlier than the real one, so the gate errs towards late.
    ("1 month ago", dt.date(2026, 9, 2)),
    ("a year ago", dt.date(2025, 9, 30)),
])
def test_relative_dates_resolve_against_the_clock(value, expected):
    assert sd.resolve_upper(value, now=NOW) == expected


def test_relative_dates_default_to_the_wall_clock():
    today = dt.datetime.now(dt.timezone.utc).date()
    assert sd.resolve_upper("yesterday") == today - dt.timedelta(days=1)


def test_availability_is_the_later_of_published_and_modified():
    assert sd.availability("2024-05-01", "2024-08-01") == dt.date(2024, 8, 1)
    assert sd.availability("2024-08-01", "2024-05-01") == dt.date(2024, 8, 1)
    assert sd.availability("2024-05", None) == dt.date(2024, 5, 31)
    assert sd.availability(None, "Q2 2024") == dt.date(2024, 6, 30)
    assert sd.availability("garbage", None) is None
    assert sd.availability(None, None) is None


@pytest.mark.parametrize("avail, same_day, expected", [
    (dt.date(2024, 5, 31), "exclude", "admit"),
    (dt.date(2024, 5, 31), "include", "admit"),
    (dt.date(2024, 6, 1), "exclude", "late"),
    (dt.date(2024, 6, 1), "include", "same_day"),
    (dt.date(2024, 6, 2), "exclude", "late"),
    (dt.date(2024, 6, 2), "include", "late"),
    (None, "exclude", "unverifiable"),
    (None, "include", "unverifiable"),
    # A month counts as its last day: June 2024 is not over on June 1.
    ("2024-06", "exclude", "late"),
    ("2024-06", "include", "late"),
    ("2024-05", "exclude", "admit"),
    ("garbage", "exclude", "unverifiable"),
    # Anything but "include" is the strict default.
    (dt.date(2024, 6, 1), "INCLUDE", "late"),
    (dt.date(2024, 6, 1), "", "late"),
])
def test_gate(avail, same_day, expected):
    assert sd.gate(avail, AS_OF, same_day=same_day) == expected


def test_gate_default_is_strict_and_reads_resolve_upper_values():
    assert sd.gate(sd.resolve_upper("2024-06"), AS_OF) == "late"
    assert sd.gate(dt.date(2024, 6, 1), AS_OF) == "late"
    assert sd.gate(dt.date(2024, 5, 31), "2024-06-01") == "admit"
    assert sd.gate(dt.datetime(2024, 5, 31, 23, 0, tzinfo=dt.timezone.utc), AS_OF) == "admit"


def test_a_page_published_before_but_updated_after_as_of_is_late():
    assert sd.gate(sd.availability("2024-03-01", None), AS_OF) == "admit"
    assert sd.gate(sd.availability("2024-03-01", "2024-07-15"), AS_OF) == "late"


@pytest.mark.parametrize("as_of", [None, "", "2024-6-1", "not a date", 20240601])
def test_an_unusable_as_of_gates_everything_late(as_of):
    assert sd.gate(dt.date(2000, 1, 1), as_of) == "late"
    assert sd.gate(None, as_of) == "late"


def test_url_date():
    assert sd.url_date("https://news.example/2024/06/05/story") == dt.date(2024, 6, 5)
    assert sd.url_date("https://news.example/2024-05-31-story") == dt.date(2024, 5, 31)
    # A month-precision path counts as the month's last day.
    assert sd.url_date("https://news.example/2024/05/story") == dt.date(2024, 5, 31)
    assert sd.url_date("https://news.example/story?d=2024-01-01") is None
    assert sd.url_date("https://news.example/about") is None
    assert sd.url_date(None) is None
    assert sd.gate(sd.url_date("https://news.example/2024/06/01/story"), AS_OF) == "late"
