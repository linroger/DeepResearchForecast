"""Typed probability coercion with an explicit review state (REPORT-1).

LLM-authored forecast JSON sometimes carries a probability as a string
('30%', '３０％', '30-40%', 'N/A'), a boolean, or a number on a mixed scale
([0.45, 35, 0.2]).  The legacy coercion (``float(v)``, else 0.0) turned every
one of those into a plausible number: an unreadable scenario became 0.0 and the
partition was renormalised into a uniform split, and a binary written as 30 was
clamped to 0.98.  This module parses each value into a typed ``ProbParse`` and
never guesses.  A value it cannot read with certainty gets the explicit
``needs_review`` status; callers keep such a value as ``null``, so the
fail-closed scenario contract audit rejects it instead of certifying a
manufactured number.

Idea credit: TradingAgents (Apache-2.0), "an unreadable value becomes an
explicit review state, never a default".  Reimplemented from the idea; no code
was copied.

Pure and stdlib-only so it is unit-testable offline.
"""

from __future__ import annotations

import math
import numbers
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Any, List, Optional, Sequence, Tuple

PROB_OK = "ok"
PROB_REVIEW = "needs_review"
PROB_ABSENT = "absent"

# Casefolded tokens that mean "no value was given" (after NFKC + strip).
_NULLISH = frozenset({
    "", "none", "n/a", "na", "null", "nil", "-", "—", "tbd", "unknown",
    "not provided", "未知", "不适用", "无", "待定",
})

_UNSIGNED = r"(?:\d+(?:\.\d*)?|\.\d+)"
_NUMBER = rf"[+-]?{_UNSIGNED}(?:[eE][+-]?\d+)?"
_PERCENT_UNIT = r"(?:%|percent|per\s+cent|pct)"

_BARE_RE = re.compile(rf"^({_NUMBER})$")
_PERCENT_RE = re.compile(rf"^({_NUMBER})\s*{_PERCENT_UNIT}$", re.I)
_RANGE_RE = re.compile(
    rf"{_UNSIGNED}\s*{_PERCENT_UNIT}?\s*(?:-|–|—|~|～|to|至|到)\s*[+-]?{_UNSIGNED}",
    re.I,
)
_LEADING_BOUND_RE = re.compile(
    r"^(?:>|<|≥|≤|at\s+least|at\s+most|more\s+than|less\s+than|over\b|under\b|"
    r"至少|至多|不低于|超过|以上|以下)",
    re.I,
)
# 以上/以下 are postfix in Chinese ("30%以上"), so they also mark a bound at the end.
_TRAILING_BOUND_RE = re.compile(r"(?:以上|以下)$")
_ANY_NUMBER_RE = re.compile(_UNSIGNED)


@dataclass(frozen=True)
class ProbParse:
    """One parsed probability value.

    ``value`` is the canonical number (a fraction, a percent divided by 100, or a
    raw partition weight) when ``status`` is ``ok`` and ``None`` otherwise.
    ``reason`` is '' for ``ok`` and otherwise one of: nullish, bool, non_finite,
    out_of_range, plain_gt1, range, bound, multiple_values, unparseable,
    ambiguous_scale.  ``unit`` records how the value was written: ``fraction``
    (a JSON number in [0, 1]), ``percent`` (an explicit percent string),
    ``plain`` (a bare numeric string or a JSON number above 1) or '' when no
    number was read.  ``raw`` is ``repr(value)[:80]`` for telemetry.
    """

    value: Optional[float]
    status: str
    reason: str
    unit: str
    raw: str


def is_nullish(value: Any) -> bool:
    """True for ``None`` or a placeholder string such as 'N/A', 'unknown' or '未知'."""
    if value is None:
        return True
    return (isinstance(value, str)
            and unicodedata.normalize("NFKC", value).strip().casefold() in _NULLISH)


def _review(reason: str, unit: str, raw: str) -> ProbParse:
    return ProbParse(None, PROB_REVIEW, reason, unit, raw)


def _from_number(number: float, unit: str, raw: str, *, allow_gt1: bool) -> ProbParse:
    """Apply the numeric rules to an already-read number."""
    if not math.isfinite(number):
        return _review("non_finite", unit, raw)
    if number < 0:
        return _review("out_of_range", unit, raw)
    if number <= 1:
        return ProbParse(number, PROB_OK, "", unit, raw)
    if allow_gt1:
        # Partition rows only: resolved later by the partition scale rules.
        return ProbParse(number, PROB_OK, "", "plain", raw)
    # A point field never guesses whether 30 meant 30% or a typo.
    return _review("plain_gt1", "plain", raw)


def _parse(value: Any, *, allow_gt1: bool) -> ProbParse:
    raw = repr(value)[:80]
    if is_nullish(value):
        return ProbParse(None, PROB_ABSENT, "nullish", "", raw)
    if isinstance(value, bool):
        return _review("bool", "", raw)
    if isinstance(value, numbers.Real):
        try:
            number = float(value)
        except OverflowError:
            return _review("non_finite", "", raw)
        if not math.isfinite(number):
            return _review("non_finite", "", raw)
        unit = "fraction" if 0 <= number <= 1 else "plain"
        return _from_number(number, unit, raw, allow_gt1=allow_gt1)
    if not isinstance(value, str):
        return _review("unparseable", "", raw)

    text = unicodedata.normalize("NFKC", value).strip()
    bare = _BARE_RE.match(text)
    if bare:
        return _from_number(float(bare.group(1)), "plain", raw, allow_gt1=allow_gt1)
    percent = _PERCENT_RE.match(text)
    if percent:
        number = float(percent.group(1))
        if not math.isfinite(number):
            return _review("non_finite", "percent", raw)
        if not 0 <= number <= 100:
            return _review("out_of_range", "percent", raw)
        return ProbParse(number / 100.0, PROB_OK, "", "percent", raw)
    if _RANGE_RE.search(text):
        return _review("range", "", raw)
    if _LEADING_BOUND_RE.match(text) or _TRAILING_BOUND_RE.search(text):
        return _review("bound", "", raw)
    if len(_ANY_NUMBER_RE.findall(text)) >= 2:
        return _review("multiple_values", "", raw)
    return _review("unparseable", "", raw)


def parse_probability_field(value: Any) -> ProbParse:
    """Parse one point probability (a binary forecast, a market restatement).

    ``None`` and nullish tokens are ``absent``; a JSON number or bare numeric
    string in [0, 1] is ``ok``; '30%' / '30 percent' / '３０％' read as 0.30;
    everything else (booleans, non-finite values, numbers above 1, ranges,
    bounds, several numbers, hedged text) is ``needs_review``.
    """
    return _parse(value, allow_gt1=False)


def parse_scenario_partition(
    values: Sequence[Any],
) -> Tuple[List[ProbParse], str, str]:
    """Parse the probabilities of one mutually-exclusive scenario partition.

    Returns ``(rows, status, reason)`` with ``status`` ``ok`` or
    ``needs_review``.  Rows follow the point-field rules except that plain
    numbers above 1 are accepted provisionally, then one scale is chosen for
    the whole partition:

    * explicit percents with every plain row above 1 -> percent (plain / 100);
    * an explicit percent next to a plain value <= 1 -> ambiguous_scale;
    * no explicit percent, some plain value above 1: a non-integer below 1
      anywhere -> ambiguous_scale, otherwise weights (raw values kept so the
      caller's renormalisation reproduces [3, 1] -> 0.75 / 0.25);
    * otherwise fractions.

    Any unreadable row makes the partition ``needs_review`` with that row's
    reason.  Readable rows keep their canonical value only when the scale is
    absolute (fraction or percent); weights of an incomplete partition cannot
    be normalised and are returned as review/ambiguous_scale.
    """
    rows = [_parse(value, allow_gt1=True) for value in values]
    readable = [i for i, row in enumerate(rows) if row.status == PROB_OK]
    percent_idx = [i for i in readable if rows[i].unit == "percent"]
    plain_idx = [i for i in readable if rows[i].unit != "percent"]
    row_failure = next((row.reason for row in rows if row.status != PROB_OK), "")

    scaled = list(rows)
    if percent_idx:
        if all(rows[i].value > 1 for i in plain_idx):
            for i in plain_idx:
                fraction = rows[i].value / 100.0
                scaled[i] = (
                    replace(rows[i], value=fraction) if fraction <= 1
                    else _review("out_of_range", "plain", rows[i].raw)
                )
        else:
            for i in readable:
                scaled[i] = _review("ambiguous_scale", rows[i].unit, rows[i].raw)
    elif any(rows[i].value > 1 for i in plain_idx):
        mixed = any(
            rows[i].value < 1 and not float(rows[i].value).is_integer()
            for i in plain_idx
        )
        if mixed or row_failure:
            for i in readable:
                scaled[i] = _review("ambiguous_scale", rows[i].unit, rows[i].raw)

    scale_failure = next(
        (row.reason for row in scaled if row.status != PROB_OK), "",
    )
    reason = row_failure or scale_failure
    return scaled, (PROB_REVIEW if reason else PROB_OK), reason


def is_scoreable(value: Any) -> bool:
    """True only for a non-bool finite number in [0, 1]."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return False
    try:
        number = float(value)
    except OverflowError:
        return False
    return math.isfinite(number) and 0.0 <= number <= 1.0
