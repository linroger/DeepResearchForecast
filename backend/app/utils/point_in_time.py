"""Point-in-time date helpers (strict, fail-closed).

``validate_as_of`` is the single definition of a trustworthy as-of date: the
exact canonical ``YYYY-MM-DD`` spelling of a real calendar date that is not in
the future (UTC).  Lenient parsing (``utils.dates.parse_as_of``) is right for
reading messy research text, but an identity or admission key must never be
derived from a guess, so anything else raises ``ValueError``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional


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
