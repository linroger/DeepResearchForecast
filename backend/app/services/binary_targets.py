"""EVAL-14 (P14): structured numeric targets on binary forecasts.

A binary such as "US data-centre grid demand exceeds 230 GW on 2030-12-31" resolves
on one number, but DRF stores it only as prose: the criteria regex
(``forecast_extractor._extract_comparable_numeric_range``) reads very few real rows.
Under FORECAST_BINARY_STRUCTURED_TARGET the binary draw also asks the model for an
optional ``target`` object, and this module checks it deterministically:

* :func:`validate_binary_target` accepts a target only when every field is well
  formed (metric, canonical unit, comparator, finite threshold, statistic, strict
  dates, resolution source, optional pre-registered tolerance) and it agrees with
  the binary's own wording.  A criteria clause the regex cannot read is
  informational (``criteria_check = 'criteria_unparsed'``, i.e. unverifiable),
  never a mismatch; a clause it reads that disagrees is the error
  ``criteria_mismatch``.  Path-dependent wording ("at any point", "ever",
  "intraday", 任何时候) needs a max/min window statistic.
* :func:`threshold_ladder_audit` checks that the binaries resolving on the same
  target (metric, unit, statistic, target date, window start) form a monotone
  ladder: the probability that the value exceeds a higher threshold must not
  exceed that of a lower one by more than :data:`LADDER_TOLERANCE`.  Warn only.
* :func:`resolve_binary_by_target` settles a binary from one realized number in
  BASE units (``threshold * scale`` units), so every binary linked to the same
  target (:func:`target_group_key`, which leaves the magnitude out: ``USD billion
  800`` and ``USD trillion 1`` link) resolves from that single observation.

Units never convert across ``%``, ``pp`` and ``bp`` (a rate is never scaled);
currency and count magnitudes (K/M/B/T, thousand ... trillion, 万/亿) fold into
``scale``, so ``threshold * scale`` is the value in base units.

Pure: no I/O and no LLM, and only stdlib imports at module level.  The extractor
helpers are imported lazily inside the functions that need them, because
``forecast_extractor`` imports this module; :mod:`quantity_scoring` imports it for
:func:`canonical_unit` and :func:`comparator_holds`, which never touch the
extractor.
"""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SCHEMA = "drf.binary_target/1"

STATISTICS = frozenset({"value_on", "period_value", "max_over_window", "min_over_window",
                        "mean_over_window", "sum_over_window"})
WINDOW_STATISTICS = frozenset({"max_over_window", "min_over_window", "mean_over_window",
                               "sum_over_window"})
# The statistics that can represent an event which may happen at any point of a window.
EXTREME_WINDOW_STATISTICS = frozenset({"max_over_window", "min_over_window"})
COMPARATORS = frozenset({">", ">=", "<", "<=", "=="})
# Unambiguous spellings the validator reads as the ASCII comparator.
_COMPARATOR_ALIASES = {"≥": ">=", "≤": "<="}
RATE_UNITS = frozenset({"%", "pp", "bp"})

YES = "YES"
NO = "NO"
AMBIGUOUS = "AMBIGUOUS"
UNVERIFIABLE = "UNVERIFIABLE"

CRITERIA_CONSISTENT = "consistent"
# Same bound and direction, but one side is strict and the other inclusive ("> 170" against
# "at least 170"): the two disagree only when the realized value equals the threshold.
CRITERIA_BOUND_ONLY = "consistent_bound_only"
CRITERIA_UNPARSED = "criteria_unparsed"

# A higher threshold's exceedance probability may exceed a lower one's by at most this.
LADDER_TOLERANCE = 0.02
LADDER_MAX_VIOLATIONS = 50
CODE_LADDER_NON_MONOTONE = "ladder_non_monotone"
CODE_LADDER_DUPLICATE = "ladder_duplicate_inconsistent"

METRIC_MAX_CHARS = 120
UNIT_MAX_CHARS = 40
RESOLUTION_SOURCE_MAX_CHARS = 300
TOLERANCE_BASIS_MAX_CHARS = 200

_FLOAT_EPS = 1e-9
# Base-unit values this close are the same number: threshold * scale carries float noise
# (2.3 * 1e8 == 229999999.99999997), which must never flip a boundary resolution.
_BASE_UNIT_REL_TOL = 1e-12
# Horizontal whitespace runs collapse before the criteria regex runs: the extractor's
# patterns backtrack super-linearly on long runs (newlines stay: they split clauses).
_HORIZONTAL_SPACE_RUN_RE = re.compile(r"[^\S\n]+")
# Magnitude words for ladder labels, so "1 trillion USD" never reads as "1 USD".
_SCALE_LABELS = {1e3: "thousand", 1e6: "million", 1e9: "billion", 1e12: "trillion"}
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_NUMERIC_TEXT_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
_PATH_DEPENDENT_RE = re.compile(r"\bat\s+any\s+(?:point|time)\b|\bever\b|\bintraday\b|任何时候", re.I)

# ── units ────────────────────────────────────────────────────────────────────
_NOT_LETTER = r"(?![A-Za-z])"
# A rate unit, optionally followed by a qualifier ("% of GDP", "pp YoY").  pp before %,
# because "percentage points" starts like "percent".
_RATE_UNIT_RES: Tuple[Tuple[re.Pattern, str], ...] = (
    (re.compile(r"(?:(?:percent(?:age)?|per[ \-]?cent|pct\.?|%)[ \-]?(?:points?|pts?)|pp|p\.p\.|pps)"
                + _NOT_LETTER + r"(?:\s.*)?|(?:个)?百分点.*", re.I), "pp"),
    (re.compile(r"(?:basis[ \-]?points?|bps?)" + _NOT_LETTER + r"(?:\s.*)?|(?:个)?基点.*", re.I), "bp"),
    (re.compile(r"(?:%|percent(?:age)?|per[ \-]?cent|pct)" + _NOT_LETTER + r"(?:\s.*)?|百分比.*", re.I),
     "%"),
)
# Any rate token left inside a currency/count unit makes the unit malformed.
_RATE_TOKEN_RE = re.compile(
    r"%|百分点|百分比|基点|\b(?:percent(?:age)?|per[ \-]?cent|pct|pp|pps|bps?"
    r"|percentage[ \-]?points?|basis[ \-]?points?)\b", re.I)
_CURRENCY_SYMBOL_RE = re.compile(r"u\.?s\.?\$|hk\$|nt\$|a\$|c\$|s\$|\$|€|£|¥|₹|₩", re.I)
# Keyed by the casefolded symbol without dots ("U.S.$" -> "us$").
_SYMBOL_CURRENCY = {"us$": "USD", "$": "USD", "hk$": "HKD", "nt$": "TWD",
                    "a$": "AUD", "c$": "CAD", "s$": "SGD", "€": "EUR", "£": "GBP", "₹": "INR",
                    "₩": "KRW", "¥": "¥"}
_US_DOLLARS_RE = re.compile(r"\bu\.?s\.?\s+dollars?\b", re.I)
_WORD_CURRENCY = {
    "usd": "USD", "dollar": "USD", "dollars": "USD", "eur": "EUR", "euro": "EUR", "euros": "EUR",
    "gbp": "GBP", "sterling": "GBP", "jpy": "JPY", "yen": "JPY", "cny": "CNY", "rmb": "CNY",
    "yuan": "CNY", "renminbi": "CNY", "hkd": "HKD", "twd": "TWD", "ntd": "TWD", "inr": "INR",
    "krw": "KRW", "aud": "AUD", "cad": "CAD", "sgd": "SGD", "chf": "CHF",
}
# "¥" is written for both yen and yuan: it agrees with either code, never with another.
_AMBIGUOUS_CURRENCY = {"¥": frozenset({"JPY", "CNY"})}
_CURRENCY_CODES = frozenset(_WORD_CURRENCY.values()) | frozenset(_AMBIGUOUS_CURRENCY)
# A criteria unit that may or may not be a rate.
_AMBIGUOUS_POINT_UNITS = frozenset({"point", "points"})
# Standalone magnitude words.  Single letters follow _range_value's K/M/B/T reading
# (so "t" is trillion and "m" is million, never tonnes or metres).
_WORD_SCALE = {
    "k": 1e3, "thousand": 1e3, "thousands": 1e3,
    "m": 1e6, "mn": 1e6, "mln": 1e6, "mm": 1e6, "million": 1e6, "millions": 1e6,
    "b": 1e9, "bn": 1e9, "bln": 1e9, "billion": 1e9, "billions": 1e9,
    "t": 1e12, "tn": 1e12, "trn": 1e12, "trillion": 1e12, "trillions": 1e12,
}
_CJK_CURRENCY_SUFFIXES = (("人民币", "CNY"), ("美元", "USD"), ("欧元", "EUR"), ("英镑", "GBP"),
                          ("日元", "JPY"), ("港元", "HKD"), ("港币", "HKD"), ("元", "CNY"))
# 千 alone is not folded: 千瓦 / 千克 are units of their own.
_CJK_SCALE_PREFIXES = (("万亿", 1e12), ("千亿", 1e11), ("百亿", 1e10), ("十亿", 1e9),
                       ("千万", 1e7), ("百万", 1e6), ("亿", 1e8), ("万", 1e4))
_CJK_RUN_RE = re.compile(r"^[一-鿿]+$")


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value))).strip()


def _fold_cjk(word: str) -> Tuple[Optional[str], float, str]:
    """(currency, scale, remaining unit) of one CJK run such as 亿美元 or 万辆."""
    currency: Optional[str] = None
    for suffix, code in _CJK_CURRENCY_SUFFIXES:
        if word.endswith(suffix):
            currency, word = code, word[:-len(suffix)]
            break
    scale = 1.0
    for prefix, factor in _CJK_SCALE_PREFIXES:
        if word.startswith(prefix):
            scale, word = factor, word[len(prefix):]
            break
    return currency, scale, word


def _residue_label(words: List[str]) -> str:
    """The unit words that are neither currency nor magnitude, case-normalized: short
    symbols keep their case (GW, TWh, kWh), words are casefolded (Units -> units)."""
    text = re.sub(r"\s*/\s*", "/", " ".join(words)).strip()
    return " ".join(
        token if len(token) <= 4 and any(ch.isupper() for ch in token) else token.casefold()
        for token in text.split(" ") if token)


def canonical_unit(unit: Any) -> Optional[Tuple[str, float]]:
    """``(canonical unit, scale)`` of a unit string, or None when unreadable.

    ``%`` / percent / pct -> ``('%', 1.0)``; percentage points / pp -> ``('pp', 1.0)``;
    bp / bps / basis points -> ``('bp', 1.0)``; a rate is never scaled or converted
    into another rate, so a magnitude or currency next to one is unreadable.
    Currencies fold to an ISO code with their magnitude in ``scale``: ``'$b'``,
    ``'USD billion'``, ``'billion US dollars'`` -> ``('USD', 1e9)``; ``'亿美元'`` ->
    ``('USD', 1e8)``; ``'USD/bbl'`` -> ``('USD/bbl', 1.0)``.  Any other unit keeps its
    words (``'GW'``, ``'million units'`` -> ``('units', 1e6)``); a bare magnitude is
    a count (``'million'`` -> ``('count', 1e6)``).
    """
    if not isinstance(unit, str):
        return None
    text = _normalized_text(unit)
    if not text or len(text) > UNIT_MAX_CHARS:
        return None
    for pattern, rate in _RATE_UNIT_RES:
        if pattern.fullmatch(text):
            # A qualifier may name the base ("% of GDP", "pp YoY") but never a magnitude or a
            # currency: "% billion" or "bp USD" is not a rate.
            qualifier = text.split(" ", 1)[1] if " " in text else ""
            if _CURRENCY_SYMBOL_RE.search(qualifier) or any(
                    word.casefold() in _WORD_SCALE or word.casefold() in _WORD_CURRENCY
                    for word in qualifier.split()):
                return None
            return rate, 1.0
    currencies: List[str] = []
    for match in _CURRENCY_SYMBOL_RE.finditer(text):
        currencies.append(_SYMBOL_CURRENCY[match.group(0).casefold().replace(".", "")])
    text = _CURRENCY_SYMBOL_RE.sub(" ", text)
    text = _US_DOLLARS_RE.sub(" usd ", text)
    text = re.sub(r"\s*/\s*", " / ", text)
    scale = 1.0
    residue: List[str] = []
    for word in text.split():
        folded = word.casefold()
        if folded in _WORD_SCALE:
            scale *= _WORD_SCALE[folded]
        elif folded in _WORD_CURRENCY:
            currencies.append(_WORD_CURRENCY[folded])
        elif _CJK_RUN_RE.match(word):
            code, factor, rest = _fold_cjk(word)
            if code:
                currencies.append(code)
            scale *= factor
            if rest:
                residue.append(rest)
        else:
            residue.append(word)
    if len(set(currencies)) > 1:
        return None
    label = _residue_label(residue)
    if _RATE_TOKEN_RE.search(label):
        return None
    if label.startswith("/") and not currencies:
        return None
    if currencies:
        code = currencies[0]
        if not label:
            return code, scale
        return (code + label if label.startswith("/") else f"{code} {label}"), scale
    return (label or "count"), scale


def _unit_currency(unit: str) -> Optional[str]:
    head = re.split(r"[ /]", unit, maxsplit=1)[0]
    return head if head in _CURRENCY_CODES else None


def _currencies_agree(left: str, right: str) -> bool:
    if left == right:
        return True
    left_set = _AMBIGUOUS_CURRENCY.get(left, frozenset({left}))
    right_set = _AMBIGUOUS_CURRENCY.get(right, frozenset({right}))
    return bool(left_set & right_set)


# ── small readers ────────────────────────────────────────────────────────────
def _finite_number(value: Any) -> Optional[float]:
    """A finite int/float (never a bool), else None.  An int too large for a float
    (json.loads keeps a 400-digit literal as an int) is not finite either."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _strict_date(value: Any) -> Optional[str]:
    """A strict ``YYYY-MM-DD`` calendar date (round-trips through date.fromisoformat)."""
    if not isinstance(value, str) or not _ISO_DATE_RE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _bounded_text(value: Any, max_chars: int) -> Tuple[Optional[str], Optional[str]]:
    """``(text, None)`` for a non-empty string within ``max_chars``, else ``(None, reason)``."""
    if not isinstance(value, str) or not _normalized_text(value):
        return None, "missing"
    text = _normalized_text(value)
    if len(text) > max_chars:
        return None, "too_long"
    return text, None


def comparator_holds(value: float, comparator: str, threshold: float) -> bool:
    """Whether ``value <comparator> threshold`` holds (exact, no tolerance)."""
    if comparator == ">":
        return value > threshold
    if comparator == ">=":
        return value >= threshold
    if comparator == "<":
        return value < threshold
    if comparator == "<=":
        return value <= threshold
    if comparator == "==":
        return value == threshold
    raise ValueError(f"unknown comparator {comparator!r}")


def _read_threshold(value: Any) -> Tuple[Optional[float], Optional[str]]:
    if isinstance(value, str) and _NUMERIC_TEXT_RE.fullmatch(value.strip()):
        value = float(value.strip())
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, "threshold_invalid"
    if _finite_number(value) is None:
        return None, "threshold_not_finite"
    return value, None


def _read_tolerance(value: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """A pre-registered tolerance: exactly one of epsilon_abs / epsilon_rel (finite, > 0;
    a relative one < 1) plus a non-empty ``basis``."""
    if not isinstance(value, Mapping):
        return None, "resolution_tolerance_invalid: not an object"
    kinds = [key for key in ("epsilon_abs", "epsilon_rel") if value.get(key) is not None]
    if len(kinds) != 1:
        return None, "resolution_tolerance_invalid: give exactly one of epsilon_abs, epsilon_rel"
    kind = kinds[0]
    epsilon = _finite_number(value.get(kind))
    if epsilon is None or epsilon <= 0 or (kind == "epsilon_rel" and epsilon >= 1):
        return None, f"resolution_tolerance_invalid: {kind} must be a finite number in range"
    basis, problem = _bounded_text(value.get("basis"), TOLERANCE_BASIS_MAX_CHARS)
    if basis is None:
        return None, f"resolution_tolerance_invalid: basis {problem}"
    return {kind: epsilon, "basis": basis}, None


def _tolerance_epsilon(tolerance: Mapping[str, Any], threshold: float) -> float:
    """The tolerance half-width in the units of ``threshold`` (an absolute epsilon is
    pre-registered in the target's own unit and scale, like the threshold)."""
    if tolerance.get("epsilon_abs") is not None:
        return float(tolerance["epsilon_abs"])
    return float(tolerance["epsilon_rel"]) * abs(threshold)


def _target_scale(target: Mapping[str, Any]) -> Optional[float]:
    """The target's magnitude: its ``scale`` (finite, > 0) or, when a raw target has
    none, the scale :func:`canonical_unit` reads from its ``unit``; None if neither."""
    if "scale" in target:
        scale = _finite_number(target.get("scale"))
        return scale if scale is not None and scale > 0 else None
    unit = canonical_unit(target.get("unit"))
    return unit[1] if unit is not None else None


def _magnitude_label(threshold: float, scale: float, unit: Any) -> str:
    """``800 billion USD`` / ``230 GW`` / ``5 x1e+07 units``: a rung's threshold with its
    magnitude, so rungs of one group (which may differ in scale) read comparably."""
    if math.isclose(scale, 1.0):
        return f"{threshold:g} {unit}"
    for factor, word in _SCALE_LABELS.items():
        if math.isclose(scale, factor, rel_tol=_FLOAT_EPS):
            return f"{threshold:g} {word} {unit}"
    return f"{threshold:g} x{scale:g} {unit}"


def _extractor():
    from . import forecast_extractor
    return forecast_extractor


# ── criteria cross-check ─────────────────────────────────────────────────────
def _criteria_disagreement(clean: Mapping[str, Any], parsed: Mapping[str, Any]) -> Optional[str]:
    """Why the criteria interval ``parsed`` disagrees with the target, or None when they
    agree.  Returns ``CRITERIA_UNPARSED`` when the parsed unit cannot be read, and
    ``CRITERIA_BOUND_ONLY`` when bound and direction agree but the parsed comparator's
    strictness (``parsed['inclusive']``) differs from the target's."""
    parsed_unit = canonical_unit(parsed.get("unit"))
    if parsed_unit is None:
        return CRITERIA_UNPARSED
    unit, parsed_name = clean["unit"], parsed_unit[0]
    if unit in RATE_UNITS and parsed_name in _AMBIGUOUS_POINT_UNITS:
        return CRITERIA_UNPARSED  # "points" may be percentage points or index points
    if unit in RATE_UNITS or parsed_name in RATE_UNITS:
        if unit != parsed_name:
            return f"unit {unit} vs criteria {parsed_name}"
    else:
        currency, parsed_currency = _unit_currency(unit), _unit_currency(parsed_name)
        if (currency is None) != (parsed_currency is None) or (
                currency and parsed_currency and not _currencies_agree(currency, parsed_currency)):
            return f"unit {unit} vs criteria {parsed_name}"
    target_value = float(clean["threshold"]) * float(clean["scale"])
    low, high = float(parsed["low"]), float(parsed["high"])
    comparator = clean["comparator"]
    if comparator in (">", ">="):
        direction_ok, bound = math.isinf(high) and not math.isinf(low), low
    elif comparator in ("<", "<="):
        direction_ok, bound = math.isinf(low) and not math.isinf(high), high
    else:
        direction_ok, bound = low == high, low
    if not direction_ok:
        return f"comparator {comparator} vs criteria interval [{low}, {high}]"
    bound_value = bound * parsed_unit[1]
    if not math.isclose(target_value, bound_value, rel_tol=_FLOAT_EPS, abs_tol=1e-12):
        return f"threshold {target_value:g} vs criteria {bound_value:g} (base units)"
    inclusive = parsed.get("inclusive")
    if (comparator != "==" and isinstance(inclusive, bool)
            and inclusive != (comparator in (">=", "<="))):
        return CRITERIA_BOUND_ONLY
    return None


# ── validation ───────────────────────────────────────────────────────────────
def validate_binary_target(target: Any, *, statement: Any = "",
                           criteria: Any = "") -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """``(clean target, [])`` when ``target`` is a valid structured target for the binary
    with this ``statement`` and ``criteria``; ``(None, errors)`` otherwise.

    Errors are ``'code'`` or ``'code: detail'`` strings.  The clean target carries
    ``schema``, ``metric``, ``unit`` (canonical), ``scale`` (magnitude folded out of
    the unit), ``comparator``, ``threshold``, ``statistic``, ``target_date``,
    ``window_start`` (a window statistic's start; always None for ``value_on`` /
    ``period_value``, whatever the model wrote, so it never splits a ladder group),
    ``resolution_source``, ``criteria_check`` (``consistent`` |
    ``consistent_bound_only`` | ``criteria_unparsed``) and, when pre-registered,
    ``resolution_tolerance``.  Never raises on malformed input.
    """
    if not isinstance(target, Mapping):
        return None, ["target_not_object"]
    errors: List[str] = []

    metric, problem = _bounded_text(target.get("metric"), METRIC_MAX_CHARS)
    if metric is None:
        errors.append(f"metric_{problem}")

    unit = canonical_unit(target.get("unit"))
    if unit is None:
        errors.append("unit_invalid")

    raw_comparator = target.get("comparator")
    comparator = (_COMPARATOR_ALIASES.get(raw_comparator.strip(), raw_comparator.strip())
                  if isinstance(raw_comparator, str) else None)
    if comparator not in COMPARATORS:
        errors.append("comparator_invalid")

    threshold, problem = _read_threshold(target.get("threshold"))
    if problem:
        errors.append(problem)

    statistic = target.get("statistic")
    if not isinstance(statistic, str) or statistic not in STATISTICS:
        errors.append("statistic_invalid")
        statistic = None

    target_date = _strict_date(target.get("target_date"))
    if target_date is None:
        errors.append("target_date_invalid")

    # A window start means something only for a window statistic; elsewhere it is ignored.
    raw_window = target.get("window_start") if statistic in WINDOW_STATISTICS else None
    window_start: Optional[str] = None
    if raw_window is not None:
        window_start = _strict_date(raw_window)
        if window_start is None:
            errors.append("window_start_invalid")
        elif target_date is not None and window_start > target_date:
            errors.append("window_start_after_target_date")
    elif statistic in WINDOW_STATISTICS:
        errors.append("window_start_missing")

    source, problem = _bounded_text(target.get("resolution_source"), RESOLUTION_SOURCE_MAX_CHARS)
    if source is None:
        errors.append(f"resolution_source_{problem}")

    tolerance: Optional[Dict[str, Any]] = None
    if target.get("resolution_tolerance") is not None:
        tolerance, problem = _read_tolerance(target.get("resolution_tolerance"))
        if problem:
            errors.append(problem)

    statement_text = statement if isinstance(statement, str) else ""
    criteria_text = criteria if isinstance(criteria, str) else ""
    if (statistic is not None and statistic not in EXTREME_WINDOW_STATISTICS
            and _PATH_DEPENDENT_RE.search(f"{statement_text}\n{criteria_text}")):
        errors.append("path_dependent_requires_window_extreme")

    if errors:
        return None, errors

    clean: Dict[str, Any] = {
        "schema": SCHEMA,
        "metric": metric,
        "unit": unit[0],
        "scale": unit[1],
        "comparator": comparator,
        "threshold": threshold,
        "statistic": statistic,
        "target_date": target_date,
        "window_start": window_start,
        "resolution_source": source,
    }
    if tolerance is not None:
        clean["resolution_tolerance"] = tolerance

    parsed = _extractor()._extract_comparable_numeric_range(
        _HORIZONTAL_SPACE_RUN_RE.sub(" ", criteria_text))
    disagreement = _criteria_disagreement(clean, parsed) if parsed else CRITERIA_UNPARSED
    if disagreement in (CRITERIA_UNPARSED, CRITERIA_BOUND_ONLY):
        clean["criteria_check"] = disagreement
    elif disagreement:
        return None, [f"criteria_mismatch: {disagreement}"]
    else:
        clean["criteria_check"] = CRITERIA_CONSISTENT
    return clean, []


# ── same-target threshold ladders ────────────────────────────────────────────
def target_group_key(target: Any) -> Optional[Tuple[str, str, str, str, Optional[str]]]:
    """``(metric label, unit, statistic, target_date, window_start)`` that links the
    binaries resolving on the same number, or None when the target cannot be linked.
    The magnitude (``scale``) is left out, so thresholds compare in base units; a
    window start counts only for a window statistic."""
    if not isinstance(target, Mapping):
        return None
    metric = _extractor()._normalise_metric_label(target.get("metric"))
    unit = target.get("unit")
    statistic = target.get("statistic")
    target_date = _strict_date(target.get("target_date"))
    window = (target.get("window_start")
              if isinstance(statistic, str) and statistic in WINDOW_STATISTICS else None)
    if (not metric or not isinstance(unit, str) or not unit
            or not isinstance(statistic, str) or statistic not in STATISTICS
            or target_date is None or (window is not None and _strict_date(window) is None)):
        return None
    return metric, unit, statistic, target_date, window


def _ladder_rung(row: Any) -> Optional[Dict[str, Any]]:
    """One exceedance rung of a binary row with a structured target, or None."""
    if not isinstance(row, Mapping):
        return None
    target = row.get("target")
    key = target_group_key(target)
    probability = _finite_number(row.get("probability"))
    if key is None or probability is None or not 0.0 <= probability <= 1.0:
        return None
    comparator = target.get("comparator")
    threshold = _finite_number(target.get("threshold"))
    scale = _finite_number(target.get("scale"))
    if comparator not in (">", ">=", "<", "<=") or threshold is None or not scale or scale <= 0:
        return None
    base = threshold * scale
    if not math.isfinite(base):
        return None
    # "> K" and "<= K" price the event Y > K; ">= K" and "< K" price Y >= K.
    strict = comparator in (">", "<=")
    exceedance = probability if comparator in (">", ">=") else 1.0 - probability
    return {"key": key, "id": str(row.get("id") or ""), "base": base,
            "strict": strict, "exceedance": exceedance,
            "label": (f"P(Y {'>' if strict else '>='} "
                      f"{_magnitude_label(threshold, scale, target.get('unit'))})")}


def threshold_ladder_audit(binaries: Any) -> Dict[str, Any]:
    """Monotonicity of same-target threshold ladders (warn only).

    Binaries with a structured ``target`` are grouped by :func:`target_group_key` and
    priced as exceedance events (``p`` for > / >=, ``1 - p`` for < / <=).  Event
    ``Y > K`` implies ``Y >= K`` implies ``Y > K'`` for any lower ``K'``, so a rung whose
    event is implied by another's may not be priced more than :data:`LADDER_TOLERANCE`
    above it (``ladder_non_monotone``); two rungs on the very same event may not differ
    by more than it (``ladder_duplicate_inconsistent``).  ``==`` rows are not rungs.

    Returns ``{groups_checked, violation_count, violations: [{group, ids, code,
    reason}]}`` (the first :data:`LADDER_MAX_VIOLATIONS`); ``groups_checked`` counts
    groups with at least two rungs.
    """
    groups: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for row in binaries if isinstance(binaries, Sequence) and not isinstance(binaries, str) else ():
        rung = _ladder_rung(row)
        if rung is not None:
            groups.setdefault(rung["key"], []).append(rung)
    groups_checked = 0
    violations: List[Dict[str, Any]] = []
    violation_count = 0
    for key, rungs in groups.items():
        if len(rungs) < 2:
            continue
        groups_checked += 1
        rungs.sort(key=lambda rung: (rung["base"], rung["strict"]))
        group = {"metric": key[0], "unit": key[1], "statistic": key[2],
                 "target_date": key[3], "window_start": key[4]}
        for i, lower in enumerate(rungs):
            for higher in rungs[i + 1:]:
                same_event = (lower["strict"] == higher["strict"] and math.isclose(
                    lower["base"], higher["base"], rel_tol=_FLOAT_EPS, abs_tol=1e-12))
                gap = higher["exceedance"] - lower["exceedance"]
                if same_event and abs(gap) > LADDER_TOLERANCE + _FLOAT_EPS:
                    code = CODE_LADDER_DUPLICATE
                    reason = (f"{lower['label']} priced {lower['exceedance']:.2f} and "
                              f"{higher['exceedance']:.2f} for the same event")
                elif not same_event and gap > LADDER_TOLERANCE + _FLOAT_EPS:
                    code = CODE_LADDER_NON_MONOTONE
                    reason = (f"{higher['label']} = {higher['exceedance']:.2f} exceeds "
                              f"{lower['label']} = {lower['exceedance']:.2f} by more than "
                              f"{LADDER_TOLERANCE:.2f}")
                else:
                    continue
                violation_count += 1
                if len(violations) < LADDER_MAX_VIOLATIONS:
                    violations.append({"group": dict(group), "ids": [lower["id"], higher["id"]],
                                       "code": code, "reason": reason})
    return {"groups_checked": groups_checked, "violation_count": violation_count,
            "violations": violations}


# ── resolution ───────────────────────────────────────────────────────────────
def resolve_binary_by_target(target: Any, realized_value: Any, *,
                             realized_scale: Any = 1.0) -> str:
    """YES / NO / AMBIGUOUS / UNVERIFIABLE for a binary from one realized number.

    Contract: ``realized_value * realized_scale`` is the target statistic's realized
    value in BASE units of the target's canonical unit, and it is compared with
    ``threshold * scale``.  With the default ``realized_scale=1.0`` the caller passes
    base units (``900e9`` for USD 900 billion), so one observation settles every
    binary of a :func:`target_group_key` group whatever magnitude each row was
    written in (``USD billion 800`` and ``USD trillion 1``); a caller holding the
    number in some magnitude passes it (``900, realized_scale=1e9``).  A raw target
    without ``scale`` takes it from its ``unit``.

    A non-finite or non-numeric value or scale, or a target without a known
    comparator, finite threshold and readable scale, is UNVERIFIABLE.  A value within
    the target's PRE-REGISTERED ``resolution_tolerance`` of the threshold is AMBIGUOUS
    (an ``epsilon_abs`` is in the target's own unit and scale, like the threshold; a
    malformed tolerance is UNVERIFIABLE: tolerance is never chosen at resolution
    time); otherwise the exact comparator decides (two base-unit values within
    1e-12 relative of each other are equal: that is float noise from the scaling).
    """
    if not isinstance(target, Mapping):
        return UNVERIFIABLE
    value = _finite_number(realized_value)
    value_scale = _finite_number(realized_scale)
    threshold = _finite_number(target.get("threshold"))
    scale = _target_scale(target)
    comparator = target.get("comparator")
    if (value is None or value_scale is None or value_scale <= 0 or threshold is None
            or scale is None or not isinstance(comparator, str)
            or comparator not in COMPARATORS):
        return UNVERIFIABLE
    value_base, threshold_base = value * value_scale, threshold * scale
    if not (math.isfinite(value_base) and math.isfinite(threshold_base)):
        return UNVERIFIABLE
    if math.isclose(value_base, threshold_base, rel_tol=_BASE_UNIT_REL_TOL, abs_tol=0.0):
        value_base = threshold_base
    if target.get("resolution_tolerance") is not None:
        tolerance, problem = _read_tolerance(target.get("resolution_tolerance"))
        if problem:
            return UNVERIFIABLE
        if abs(value_base - threshold_base) <= _tolerance_epsilon(tolerance, threshold) * scale:
            return AMBIGUOUS
    return YES if comparator_holds(value_base, comparator, threshold_base) else NO
