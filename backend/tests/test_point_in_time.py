"""TIME-7: ``validate_as_of`` is the strict point-in-time admission rule.

A hindcast's as-of date must be the exact canonical ``YYYY-MM-DD`` spelling of a
real calendar date on or before today (UTC).  Lenient spellings are refused
instead of guessed, because the same string is later compared against source
and market dates.  Offline and pure.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.utils.point_in_time import validate_as_of

TODAY = date(2026, 9, 30)
CANONICAL = "as_of must be a canonical YYYY-MM-DD date"


@pytest.mark.parametrize("value", [
    "2024-6-1",            # unpadded month and day
    "2024-06-01 00:00",    # a date-time, not a date
    "2024-06-01T00:00:00Z",
    " 2024-06-01",         # surrounding whitespace is not canonical
    "2024-06-01\n",
    "Sept 1",
    "2024/06/01",
    "2024-02-30",          # not a calendar date
    "",
    None,
    20240601,
    date(2024, 6, 1),      # a date object is not the canonical string
])
def test_rejects_non_canonical_values(value):
    with pytest.raises(ValueError, match=CANONICAL):
        validate_as_of(value, today_utc=TODAY)


def test_rejects_tomorrow_against_the_injected_utc_today():
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match="as_of cannot be in the future"):
        validate_as_of(tomorrow, today_utc=TODAY)


def test_accepts_a_canonical_past_date_and_today():
    assert validate_as_of("2024-06-01", today_utc=TODAY) == "2024-06-01"
    assert validate_as_of(TODAY.isoformat(), today_utc=TODAY) == TODAY.isoformat()


def test_future_check_compares_dates_not_strings():
    # A datetime "today" is reduced to its date: late on 30 September the 30th is still today.
    late = datetime(2026, 9, 30, 23, 59, tzinfo=timezone.utc)
    assert validate_as_of("2026-09-30", today_utc=late) == "2026-09-30"
    with pytest.raises(ValueError, match="in the future"):
        validate_as_of("2026-10-01", today_utc=late)


def test_default_today_is_the_current_utc_date():
    today = datetime.now(timezone.utc).date()
    assert validate_as_of(today.isoformat()) == today.isoformat()
    with pytest.raises(ValueError, match="in the future"):
        validate_as_of((today + timedelta(days=2)).isoformat())
