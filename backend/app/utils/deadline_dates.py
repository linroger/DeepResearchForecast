"""Strict scan of the calendar dates a forecast's free text names (EVAL-2 settlement).

Settlement uses these dates to decide when an unresolved forecast is closed for good
and which market may label it, so a date it misses or misreads is an honesty failure,
not a cosmetic one. ``scan_date_mentions`` therefore returns EVERY date-shaped span,
including the ones it cannot pin to a real day, and never guesses silently:

- A span that names a real day, or a period with a clear last day, gets ``day``: the
  named day, or the period's last day ('Q2 2027' → 2027-06-30).
- A date-shaped span that is not a real day ('2027-02-30', '2027年13月', '06/07/2027',
  which reads either way) or only a vague period ('early 2027', '2027年初') gets
  ``day=None``. Callers must treat such a span as unverifiable, never skip it.
- ``latest`` is always set: the latest day the span can plausibly mean (``day`` when
  pinned; otherwise the end of the month, half or year it falls in). A caller that must
  never act early (a grace terminal) can wait for it.

Reuse: the rich period forms ('end of 2027', '2027年底', 'mid-2027', '2027年中',
quarters incl. '2028年第三季度', halves incl. '上半年', 'March 2027', '2027年11月') come
from ``sim_timeline``'s anchored-period table, the one ``extract_horizon`` uses. That
function returns only the first horizon after an as-of date, and ``dates.parse_as_of``
maps an invalid day to the 1st of its month, which is exactly what must not happen
here, so this module adds strict readers only for what those do not cover: numeric and
CJK year-month-day dates (validated, never clamped), 'Month D, YYYY', 'D Month YYYY',
day-first dotted/slashed dates, 'YYYY-MM' / 'YYYY/MM' (month end), 'end-YYYY' /
'year-end YYYY' / '2027年末' (year end), 'middle of YYYY' (30 June) and the vague
early-year forms. Years are 2000-2099. Relative spans ('within 7 days of the
recount') are not dates: they count from an event, not from the forecast origin.
Pure: no I/O, no clock; never raises.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, List, Optional, Pattern, Tuple

from .sim_timeline import _TIER2 as _ANCHORED_PERIODS  # (regex, handler) pairs

_MONTH = (r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?"
          r"|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
_MONTH_NUMBER = {name: index for index, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
    start=1)}
_YEAR_RE = re.compile(r"20\d{2}")

# Day-level forms, claimed first. Separators must repeat ('2027-06/30' is not a date).
# A hyphen may precede a date ('2027-01-01-2027-12-31' is a range of two dates).
_YMD_RE = re.compile(r"(?<![\d./])(20\d{2})([-/.])(\d{1,2})\2(\d{1,2})(?!\d)")
_CJK_YMD_RE = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})(?!\d)\s*[日号]?")
_MONTH_DAY_YEAR_RE = re.compile(
    rf"(?<![A-Za-z]){_MONTH}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}})(?!\d)",
    re.IGNORECASE)
_DAY_MONTH_YEAR_RE = re.compile(
    rf"(?<![\dA-Za-z])(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}\.?,?\s+(20\d{{2}})(?!\d)",
    re.IGNORECASE)
_NUMERIC_DMY_RE = re.compile(r"(?<![\d./-])(\d{1,2})([./-])(\d{1,2})\2(20\d{2})(?!\d)")

# Period forms sim_timeline does not cover.
_YEAR_END_RE = re.compile(
    r"(?<![A-Za-z])(?:year[- ]?end|end|YE)[- ]?(?:of[- ])?(?:the[- ])?(?:year[- ])?(20\d{2})(?!\d)",
    re.IGNORECASE)
_CJK_YEAR_END_RE = re.compile(r"(20\d{2})\s*年\s*年?\s*[底末]")
_CJK_YEAR_MID_RE = re.compile(r"(20\d{2})\s*年\s*年中")
_MIDDLE_OF_RE = re.compile(r"(?<![A-Za-z])middle\s+of\s+(?:the\s+year\s+)?(20\d{2})(?!\d)",
                           re.IGNORECASE)
# Vague: no clear last day. Pinned to nothing; ``latest`` is the end of that half-year.
_EARLY_YEAR_RE = re.compile(
    r"(?<![A-Za-z])(?:early|start\s+of|beginning\s+of)[\s-]*(?:the\s+year\s+)?(20\d{2})(?!\d)",
    re.IGNORECASE)
_CJK_EARLY_YEAR_RE = re.compile(r"(20\d{2})\s*年\s*初")

# Year-month, claimed last: '2027-06' → 30 June. A month outside 1-12 ('2026-27',
# '2026/27') is a fiscal range, not a date, and is not a mention. A dotted '2027.06'
# is left alone: it reads as a decimal number far more often than as a month.
_YEAR_MONTH_RE = re.compile(r"(?<![\d./-])(20\d{2})([-/])(\d{1,2})(?!\d)(?![-/.]\d)")


@dataclass(frozen=True)
class DateMention:
    """One date-shaped span of a text (offsets into that text)."""

    start: int
    end: int
    text: str
    day: Optional[date]  # the day named (a period: its last day); None: not a pinnable day
    latest: date  # the latest day the span can plausibly mean (== day when pinned)


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _latest_for(year: int, month: Optional[int]) -> date:
    """Latest plausible day of an unpinnable span: its month's end, else its year's end."""
    if month is not None and 1 <= month <= 12:
        return _month_end(year, month)
    return date(year, 12, 31)


def _strict_day(year: int, month: int, day: int) -> Tuple[Optional[date], date]:
    try:
        exact = date(year, month, day)
    except ValueError:
        return None, _latest_for(year, month)
    return exact, exact


def _read_ymd(m: re.Match) -> Tuple[Optional[date], date]:
    return _strict_day(int(m.group(1)), int(m.group(3)), int(m.group(4)))


def _read_cjk_ymd(m: re.Match) -> Tuple[Optional[date], date]:
    return _strict_day(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _read_month_day_year(m: re.Match) -> Tuple[Optional[date], date]:
    return _strict_day(int(m.group(3)), _MONTH_NUMBER[m.group(1)[:3].lower()], int(m.group(2)))


def _read_day_month_year(m: re.Match) -> Tuple[Optional[date], date]:
    return _strict_day(int(m.group(3)), _MONTH_NUMBER[m.group(2)[:3].lower()], int(m.group(1)))


def _read_numeric_dmy(m: re.Match) -> Tuple[Optional[date], date]:
    """'30.06.2027' / '6/30/2027': whichever of day-first and month-first is a real date.
    When both are and they differ ('06/07/2027'), the span is ambiguous: not pinned."""
    first, second, year = int(m.group(1)), int(m.group(3)), int(m.group(4))
    readings = {d for d in (_strict_day(year, second, first)[0],
                            _strict_day(year, first, second)[0]) if d is not None}
    if len(readings) == 1:
        only = readings.pop()
        return only, only
    latest = max(readings) if readings else date(year, 12, 31)
    return None, latest


def _read_year_end(m: re.Match) -> Tuple[Optional[date], date]:
    end = date(int(m.group(1)), 12, 31)
    return end, end


def _read_mid_year(m: re.Match) -> Tuple[Optional[date], date]:
    mid = date(int(m.group(1)), 6, 30)
    return mid, mid


def _read_early_year(m: re.Match) -> Tuple[Optional[date], date]:
    return None, date(int(m.group(1)), 6, 30)


def _read_year_month(m: re.Match) -> Optional[Tuple[Optional[date], date]]:
    month = int(m.group(3))
    if not 1 <= month <= 12:
        return None  # a fiscal range ('2026-27'), not a date
    end = _month_end(int(m.group(1)), month)
    return end, end


def _anchored_period_reader(handler: Callable[[re.Match], Optional[date]]
                            ) -> Callable[[re.Match], Tuple[Optional[date], date]]:
    """Wrap a sim_timeline period handler: its date when real, else an unpinned span."""
    def read(m: re.Match) -> Tuple[Optional[date], date]:
        try:
            day = handler(m)
        except (ValueError, OverflowError, TypeError):
            day = None
        if day is not None:
            return day, day
        year = _YEAR_RE.search(m.group(0))
        return None, date(int(year.group(0)) if year else 2099, 12, 31)
    return read


_Reader = Callable[[re.Match], Optional[Tuple[Optional[date], date]]]

# Claim order: a span claimed by an earlier tier hides any later match overlapping it,
# so '30 June 2027' is one day, not also the month 'June 2027'.
_TIERS: List[List[Tuple[Pattern[str], _Reader]]] = [
    [(_YMD_RE, _read_ymd), (_CJK_YMD_RE, _read_cjk_ymd),
     (_MONTH_DAY_YEAR_RE, _read_month_day_year), (_DAY_MONTH_YEAR_RE, _read_day_month_year),
     (_NUMERIC_DMY_RE, _read_numeric_dmy)],
    [(_YEAR_END_RE, _read_year_end), (_CJK_YEAR_END_RE, _read_year_end),
     (_CJK_YEAR_MID_RE, _read_mid_year), (_MIDDLE_OF_RE, _read_mid_year),
     (_EARLY_YEAR_RE, _read_early_year), (_CJK_EARLY_YEAR_RE, _read_early_year)]
    + [(pattern, _anchored_period_reader(handler)) for pattern, handler in _ANCHORED_PERIODS],
    [(_YEAR_MONTH_RE, _read_year_month)],
]


def scan_date_mentions(text: Any) -> List[DateMention]:
    """Every date-shaped span of ``text`` (see the module docstring), in text order.

    Non-strings and empty text give ``[]``. Never raises.
    """
    if not isinstance(text, str) or not text:
        return []
    claimed: List[Tuple[int, int]] = []
    mentions: List[DateMention] = []
    for tier in _TIERS:
        hits = sorted(((m.start(), index, m, reader)
                       for index, (pattern, reader) in enumerate(tier)
                       for m in pattern.finditer(text)), key=lambda hit: (hit[0], hit[1]))
        for start, _index, m, reader in hits:
            end = m.end()
            if any(start < taken_end and taken_start < end for taken_start, taken_end in claimed):
                continue
            reading = reader(m)
            if reading is None:
                continue
            claimed.append((start, end))
            mentions.append(DateMention(start, end, m.group(0), reading[0], reading[1]))
    return sorted(mentions, key=lambda mention: mention.start)
