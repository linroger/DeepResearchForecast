"""Point-in-time date helpers (strict, fail-closed).

``validate_as_of`` is the single definition of a trustworthy as-of date: the
exact canonical ``YYYY-MM-DD`` spelling of a real calendar date that is not in
the future (UTC).  Lenient parsing (``utils.dates.parse_as_of``) is right for
reading messy research text, but an identity or admission key must never be
derived from a guess, so anything else raises ``ValueError``.

``parse_stamp_strict`` is the matching reader for instants (settlement
known-at and processing stamps): an unambiguous UTC moment or ``None``.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Optional

_STAMP_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
# A date-time must name its zone: ``Z`` or an explicit ``±HH``, ``±HHMM`` or ``±HH:MM`` offset.
_STAMP_DATETIME_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:[Zz]|[+-]\d{2}(?::?\d{2})?)",
    re.ASCII)


def validate_as_of(value: Any, *, today_utc: Optional[date] = None) -> str:
    """Return ``value`` unchanged when it is a canonical, non-future date.

    ``today_utc`` injects "today" for deterministic callers and tests (a
    ``datetime`` is reduced to its date); the default is the current UTC date.
    Raises ``ValueError`` for non-strings, non-canonical spellings (such as
    ``'2024-6-1'`` or ``'2024-06-01 00:00'``) and dates after today.
    """
    if not isinstance(value, str):
        raise ValueError("as_of must be a canonical YYYY-MM-DD date")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValueError("as_of must be a canonical YYYY-MM-DD date") from None
    if parsed.strftime("%Y-%m-%d") != value:
        raise ValueError("as_of must be a canonical YYYY-MM-DD date")
    if today_utc is None:
        today = datetime.now(timezone.utc).date()
    elif isinstance(today_utc, datetime):
        today = today_utc.date()
    else:
        today = today_utc
    if parsed.date() > today:
        raise ValueError("as_of cannot be in the future")
    return value


def parse_stamp_strict(value: Any, *, allow_date: bool = True) -> Optional[datetime]:
    """Return ``value`` as an aware UTC datetime, or ``None`` when it is not unambiguous.

    Accepted: a canonical calendar date ``YYYY-MM-DD`` (read as 00:00 UTC that
    day; refused when ``allow_date`` is False) and an ISO 8601 date-time with a
    ``Z`` or an explicit UTC offset (``T`` or a space before the time). Refused:
    naive date-times (their zone would be a guess), bare years, year-months,
    week or ordinal dates, surrounding whitespace, free text and non-strings.
    Lenient parsing (``utils.dates.parse_as_of``) is never used, because these
    stamps decide whether an outcome was knowable before a forecast. Never raises.
    """
    if not isinstance(value, str):
        return None
    try:
        if _STAMP_DATE_RE.fullmatch(value):
            if not allow_date:
                return None
            return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if not _STAMP_DATETIME_RE.fullmatch(value):
            return None
        text = value[:-1] + "+00:00" if value[-1] in "Zz" else value
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None
