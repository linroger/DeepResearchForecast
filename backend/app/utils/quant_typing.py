"""Reported vs projected reading of research quantitative rows (RESEARCH-5).

With RESEARCH_QUANT_TYPING on, the v3 research engine stamps every
quantitative.json row with ``epistemic_class`` (RESEARCH-4,
``deerflow_bridge/linear_research.py::classify_quant_row``): ``reported`` is a
value that has happened, ``projected`` is someone's forecast, estimate or
target for a later date, and ``unknown`` is anything the engine could not
place.  Report-side consumers (the persona expectation qualifier, the chart
labels, the projection-attribution lint and the report figures block) also
meet rows the engine never typed: legacy research, reused handoffs, runs with
typing off.  This module is their one reading of a row:

* :func:`quant_class` -- the stamped ``epistemic_class`` first; else
  RESEARCH-4's rule over ``value_type`` (including the estimate-year rule);
  else the legacy bridge's ``value_kind`` (actual / forecast); else
  ``unknown``.  ``value_type`` is read before ``value_kind`` because the legacy
  bridge folds ``estimate`` into ``value_kind = forecast``, which would erase
  the reported-estimate class.
* :func:`reference_period` -- the date a value is about: its target date, else
  its period end, else the source's as-of date.
* :func:`expectation_qualifier` -- "expectation by IBM, target 2029-12-31" /
  "IBM的预期，目标期 2029-12-31"; a row that states only the source's as-of
  date reads "expectation by CNBC, as of 2026-07-30" / "CNBC的预期，截至
  2026-07-30" (a publication date is not a target).
* :func:`is_unverified` -- the RESEARCH-4 page check did not find the number
  on its cited page, or could not check it there.

The period parser below is a copy of the bridge's (``_period_bounds`` /
``_loose_period_bounds``): the bridge runs in the research child's interpreter
and the backend never imports it.  test_report_quant_typing pins the copy to
``classify_quant_row`` on a shared fixture list.

Pure and stdlib-only; nothing here raises on a malformed row.
"""

from __future__ import annotations

import calendar
import datetime as _dt
import re
from typing import Any, Mapping, Optional

REPORTED = "reported"
PROJECTED = "projected"
UNKNOWN = "unknown"
EPISTEMIC_CLASSES = frozenset({REPORTED, PROJECTED, UNKNOWN})

# RESEARCH-4's value_type vocabulary (linear_research._VALUE_TYPES).
_VALUE_TYPES = frozenset({"actual", "estimate", "forecast", "target"})
# RESEARCH-4 page-check labels that mean the number was not confirmed on its
# cited page: fetched but not found, never fetched, or no resolvable source.
_UNVERIFIED_LABELS = frozenset({"unverified", "snippet_only", "none"})

# ── Period parsing (copy of deerflow_bridge/linear_research.py) ──────────────
# A stated date or period, matched whole: (pattern, precision).  "FY2025" is
# taken as the calendar year; a day may carry an ISO time.
_PERIOD_FORMS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?",
                re.I), "day"),
    (re.compile(r"(\d{4})-(\d{1,2})"), "month"),
    (re.compile(r"(\d{4})[-\s]?Q([1-4])", re.I), "quarter"),
    (re.compile(r"(\d{4})[-\s]?H([12])", re.I), "half"),
    (re.compile(r"(?:FY\s?)?(\d{4})", re.I), "year"),
)
_MONTHS_PER = {"month": 1, "quarter": 3, "half": 6}
# A year named inside free text ("2025-2035", "by 2030", "2030E"), optionally
# closing a range with two digits ("2025/26", "FY2025-29").
_PERIOD_YEAR_RE = re.compile(r"(?<!\d)((?:19|20|21)\d{2})(?:\s*[/-]\s*(\d{2})(?!\d))?(?!\d)")
# Free-text spellings of a whole month, quarter or half ("Q4 2026", "2H 2026",
# "Dec 2026", "2026年第三季度", "2026年上半年", "2026年3月"); a year's end
# ("end of 2026", "2026年底") is its December.  Named groups: y and q / h / m.
_FREE_PERIOD_FORMS: tuple[re.Pattern[str], ...] = tuple(re.compile(pattern, re.I) for pattern in (
    r"Q(?P<q>[1-4])[\s,/-]*(?P<y>\d{4})",
    r"(?P<q>[1-4])Q[\s,/-]*(?P<y>\d{4})",
    r"(?P<y>\d{4})[\s/-]*(?P<q>[1-4])Q",
    r"H(?P<h>[12])[\s,/-]*(?P<y>\d{4})",
    r"(?P<h>[12])H[\s,/-]*(?P<y>\d{4})",
    r"(?P<y>\d{4})[\s/-]*(?P<h>[12])H",
    r"(?P<m>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?[\s,]*(?P<y>\d{4})",
    r"(?:(?:the\s+)?end(?:\s+of)?|year[\s-]?end)[\s,-]*(?P<y>\d{4})",
    r"(?P<y>\d{4})[\s-]*year[\s-]?end",
    r"(?P<y>\d{4})\s*年\s*(?:第\s*)?(?P<q>[1-4一二三四])\s*季度",
    r"(?P<y>\d{4})\s*年\s*(?:Q(?P<q>[1-4])|H(?P<h>[12]))",
    r"(?P<y>\d{4})\s*年\s*(?P<h>[上下])半年",
    r"(?P<y>\d{4})\s*年\s*(?P<m>\d{1,2})\s*月份?",
    r"(?P<y>\d{4})\s*年\s*年?[底末]",
))
_FREE_PERIOD_DIGITS = {"一": "1", "二": "2", "三": "3", "四": "4", "上": "1", "下": "2"}
_MONTH_ABBREVIATIONS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
# period_end placeholders that state no period, like an empty field.
_NO_PERIOD = frozenset({"n/a", "na", "none", "null", "unknown", "not applicable"})


def _period_bounds(value: Any) -> tuple[Optional[_dt.date], Optional[_dt.date]]:
    """``(first day, last day)`` of a stated date or period; ``(None, None)``
    for anything else."""
    text = str(value or "").strip()
    for pattern, precision in _PERIOD_FORMS:
        match = pattern.fullmatch(text)
        if match is None:
            continue
        year = int(match.group(1))
        try:
            if precision == "day":
                day = _dt.date(year, int(match.group(2)), int(match.group(3)))
                return day, day
            if precision == "year":
                return _dt.date(year, 1, 1), _dt.date(year, 12, 31)
            months = _MONTHS_PER[precision]
            last = months * int(match.group(2))
            return (_dt.date(year, last - months + 1, 1),
                    _dt.date(year, last, calendar.monthrange(year, last)[1]))
        except ValueError:  # month 13, Feb 30, year 0
            return None, None
    return None, None


def _period_end_date(value: Any) -> Optional[_dt.date]:
    """The LAST day of a stated date or period, so a period never counts as
    known before it ends: YYYY and FYyyyy → Dec 31, YYYY-MM → the month's last
    day, YYYY-Qn / YYYY-Hn → the quarter's / half's last day, an ISO date (or
    date-time) → itself; None for anything else."""
    return _period_bounds(value)[1]


def _free_period(text: str) -> Optional[str]:
    """The canonical spelling (YYYY-MM, YYYY-Qn or YYYY-Hn) of a whole
    free-text month, quarter or half, else None."""
    for pattern in _FREE_PERIOD_FORMS:
        match = pattern.fullmatch(text)
        if match is None:
            continue
        parts = match.groupdict()
        for kind in ("q", "h"):
            if parts.get(kind):
                return f"{parts['y']}-{kind.upper()}{_FREE_PERIOD_DIGITS.get(parts[kind], parts[kind])}"
        month = parts.get("m") or "12"
        number = int(month) if month.isdigit() else _MONTH_ABBREVIATIONS.index(month[:3].lower()) + 1
        return f"{parts['y']}-{number:02d}"
    return None


def _loose_period_bounds(value: Any) -> tuple[Optional[_dt.date], Optional[_dt.date]]:
    """:func:`_period_bounds`, else a whole free-text month, quarter or half,
    else the years free text names ("by 2030", "2030E", "FY2025-29") read as
    Jan 1 of the earliest to Dec 31 of the latest; ``(None, None)`` without one."""
    bounds = _period_bounds(value)
    if bounds[1] is not None:
        return bounds
    free = _free_period(str(value or "").strip())
    bounds = _period_bounds(free) if free else bounds
    if bounds[1] is not None:
        return bounds
    years: list[int] = []
    for match in _PERIOD_YEAR_RE.finditer(str(value or "")):
        year = int(match.group(1))
        years.append(year)
        if match.group(2):
            closing = year - year % 100 + int(match.group(2))
            if closing > year:
                years.append(closing)
    if not years:
        return None, None
    return _dt.date(min(years), 1, 1), _dt.date(max(years), 12, 31)


# ── Classification ───────────────────────────────────────────────────────────

def _label(value: Any) -> str:
    return str(value or "").strip().lower()


def _as_date(as_of: Any) -> Optional[_dt.date]:
    if isinstance(as_of, _dt.datetime):
        return as_of.date()
    return as_of if isinstance(as_of, _dt.date) else None


def _class_by_value_type(row: Mapping[str, Any], value_type: str,
                         as_of: Optional[_dt.date]) -> str:
    """RESEARCH-4's rule (``classify_quant_row``) reduced to the class.

    ``forecast`` / ``target`` are projected; an ``estimate`` whose reference
    date (end of ``period_end``, else of ``as_of_date``) is after as-of is
    projected.  Any other ``actual`` / ``estimate`` is reported, except that it
    is unknown when its reference date or the first day of its ``as_of_date``
    is after as-of (no source publishes after as-of), or when ``period_end``
    states a period whose end cannot be read.  Without an as-of date an
    estimate cannot be placed before or after it and is unknown.
    """
    if value_type in ("forecast", "target"):
        return PROJECTED
    period_text = str(row.get("period_end") or "").strip()
    period = _loose_period_bounds(period_text)[1]
    period_unparsed = (period is None and any(ch.isalnum() for ch in period_text)
                       and period_text.casefold() not in _NO_PERIOD)
    if as_of is None:
        return UNKNOWN if value_type == "estimate" or period_unparsed else REPORTED
    stated_start, stated_end = _loose_period_bounds(row.get("as_of_date"))
    if period is not None:
        reference = period
    elif period_unparsed:
        reference = None
    else:
        reference = stated_end
    after_as_of = reference is not None and reference > as_of
    if value_type == "estimate" and after_as_of:
        return PROJECTED
    stated_after_as_of = stated_start is not None and stated_start > as_of
    return UNKNOWN if after_as_of or stated_after_as_of or period_unparsed else REPORTED


def quant_class(row: Any, as_of: Optional[_dt.date] = None) -> str:
    """``reported`` | ``projected`` | ``unknown`` for one quantitative row.

    Precedence: the research engine's ``epistemic_class`` stamp; else
    ``value_type`` in {actual, estimate, forecast, target} under RESEARCH-4's
    rule against ``as_of`` (a date or datetime; None disables the date tests);
    else ``value_kind`` (actual → reported, forecast → projected); else unknown.
    """
    if not isinstance(row, Mapping):
        return UNKNOWN
    stamped = _label(row.get("epistemic_class"))
    if stamped in EPISTEMIC_CLASSES:
        return stamped
    value_type = _label(row.get("value_type"))
    if value_type in _VALUE_TYPES:
        return _class_by_value_type(row, value_type, _as_date(as_of))
    value_kind = _label(row.get("value_kind"))
    if value_kind == "actual":
        return REPORTED
    if value_kind == "forecast":
        return PROJECTED
    return UNKNOWN


def _clean(value: Any, limit: int) -> str:
    """One-line text of a row field, capped at ``limit`` characters."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _stated_period(row: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    """The first of ``keys`` that states a date or period.  Placeholders are
    skipped: "n/a"-style words and text without a letter or digit ("-", "?"),
    the bridge's rule for a period_end that states nothing."""
    for key in keys:
        text = _clean(row.get(key), 60)
        if any(ch.isalnum() for ch in text) and text.casefold() not in _NO_PERIOD:
            return text
    return ""


def reference_period(row: Any) -> str:
    """The date or period a value is about: ``target_date``, else
    ``period_end``, else ``as_of_date`` (placeholders such as "n/a" or "-"
    skipped); "" when the row states none."""
    if not isinstance(row, Mapping):
        return ""
    return _stated_period(row, ("target_date", "period_end", "as_of_date"))


def _is_zh(lang: Any) -> bool:
    return str(lang or "").strip().lower().startswith(("zh", "chinese", "中"))


def expectation_qualifier(row: Any, lang: str = "en") -> str:
    """Who expects a projected value and for when, in ``lang`` (zh* / Chinese /
    中文 → Chinese, anything else → English): "expectation by {source},
    target {period}" / "{source}的预期，目标期 {period}", the period being
    ``target_date``, else ``period_end``.  A row that states neither reads
    "…, as of {as_of_date}" / "…，截至 {as_of_date}" instead: the source's
    publication date is not the target.  The expecting party is ``source``,
    else ``analyst``, else an unnamed source; the date clause is dropped when
    the row states no date at all."""
    fields = row if isinstance(row, Mapping) else {}
    who = _clean(fields.get("source") or fields.get("analyst"), 100)
    target = _stated_period(fields, ("target_date", "period_end"))
    stated = "" if target else _stated_period(fields, ("as_of_date",))
    if _is_zh(lang):
        who = who or "未具名来源"
        if target:
            return f"{who}的预期，目标期 {target}"
        return f"{who}的预期，截至 {stated}" if stated else f"{who}的预期"
    who = who or "an unnamed source"
    if target:
        return f"expectation by {who}, target {target}"
    return f"expectation by {who}, as of {stated}" if stated else f"expectation by {who}"


def is_unverified(row: Any) -> bool:
    """True when RESEARCH-4's page check labelled the row ``unverified``
    (fetched, number not found), ``snippet_only`` (source never fetched) or
    ``none`` (no resolvable source).  An absent label means unchecked: False."""
    return isinstance(row, Mapping) and _label(row.get("verification")) in _UNVERIFIED_LABELS
