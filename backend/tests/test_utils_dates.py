"""Golden tests for lenient date parsing (EXECPLAN2 I-7-3)."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.utils.dates import date_period, parse_as_of


def test_parse_iso_and_slash_and_dot():
    for s in ("2030-06-15", "2030/06/15", "2030.06.15"):
        d = parse_as_of(s)
        assert d == datetime(2030, 6, 15, tzinfo=timezone.utc)


def test_parse_cjk():
    assert parse_as_of("2030年6月15日") == datetime(2030, 6, 15, tzinfo=timezone.utc)
    assert parse_as_of("2030年6月") == datetime(2030, 6, 1, tzinfo=timezone.utc)


def test_parse_year_only_and_year_month():
    assert parse_as_of("2030") == datetime(2030, 1, 1, tzinfo=timezone.utc)
    assert parse_as_of("2030-06") == datetime(2030, 6, 1, tzinfo=timezone.utc)


def test_parse_passthrough_and_failures():
    assert parse_as_of(None) is None
    assert parse_as_of("") is None
    assert parse_as_of("no date here") is None
    naive = datetime(2030, 1, 2)
    assert parse_as_of(naive).tzinfo is not None  # naive -> UTC-stamped


def test_parse_overflow_day_falls_back_to_first():
    # 2 月 30 日 -> 当月 1 日
    assert parse_as_of("2030-02-30") == datetime(2030, 2, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("value, period", [
    ("2024-06-15", (date(2024, 6, 15), date(2024, 6, 15))),
    ("2024/6/1", (date(2024, 6, 1), date(2024, 6, 1))),
    ("2024年6月15日", (date(2024, 6, 15), date(2024, 6, 15))),
    ("2024-06-15T23:00:00Z", (date(2024, 6, 15), date(2024, 6, 15))),
    ("2024-06", (date(2024, 6, 1), date(2024, 6, 30))),
    ("2024年2月", (date(2024, 2, 1), date(2024, 2, 29))),
    ("2023.02", (date(2023, 2, 1), date(2023, 2, 28))),
    ("2030-02-30", (date(2030, 2, 1), date(2030, 2, 28))),   # parse_as_of reads the month
    ("2024", (date(2024, 1, 1), date(2024, 12, 31))),
    ("FY 2024 annual report", (date(2024, 1, 1), date(2024, 12, 31))),
    (date(2024, 6, 15), (date(2024, 6, 15), date(2024, 6, 15))),
    (datetime(2024, 6, 15, 12), (date(2024, 6, 15), date(2024, 6, 15))),
])
def test_date_period_follows_the_dates_own_precision(value, period):
    assert date_period(value) == period
    # The period always starts on the day parse_as_of reads.
    assert date_period(value)[0] == parse_as_of(value).date()


def test_date_period_takes_an_aware_datetime_in_utc():
    tokyo = timezone(timedelta(hours=9))
    assert date_period(datetime(2024, 6, 1, 3, tzinfo=tokyo)) == (date(2024, 5, 31), date(2024, 5, 31))


def test_date_period_declared_precision_only_widens():
    assert date_period("2024-06-15", "month") == (date(2024, 6, 1), date(2024, 6, 30))
    assert date_period("2024-06-15", "year") == (date(2024, 1, 1), date(2024, 12, 31))
    assert date_period("2024-06", "year") == (date(2024, 1, 1), date(2024, 12, 31))
    assert date_period("2024", "day") == (date(2024, 1, 1), date(2024, 12, 31))
    assert date_period("2024-06", "day") == (date(2024, 6, 1), date(2024, 6, 30))
    for ignored in ("decade", "", None, 3, ["month"], {"p": "year"}):
        assert date_period("2024-06-15", ignored) == (date(2024, 6, 15), date(2024, 6, 15))


def test_date_period_is_none_whenever_parse_as_of_is():
    for value in (None, "", "  ", "no date here", "2024年13月", "2024-13"):
        assert parse_as_of(value) is None
        assert date_period(value, "day") is None
