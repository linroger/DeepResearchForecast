"""Cross-source forecast-dispersion diagnostics (RESEARCH-6, shadow only).

A research run's quantitative.json often holds several institutions' forecasts
of one quantity: Omdia's 38,000 humanoid robots shipped in 2030 next to
Goldman Sachs' 250,000 and Bank of America's 1.2 million.  This module groups
those projections deterministically and records how far the forecasters
disagree, how old their numbers are and whether a forecaster revised its own
number, with zero model calls.  It never moves a probability, a prompt or a
gate: with REPORT_CONSENSUS_DIAGNOSTICS=shadow the report stage writes the
result to ``consensus_evidence.json`` and its digest (:func:`quality_summary`)
to ``forecast.quality.consensus``.

The rules are DRF constructions (the dispersion threshold is uncalibrated):

* eligible rows are projections (:func:`app.utils.quant_typing.quant_class`:
  the research typing stamp, else the value_type rule) with a parseable
  ``value_num``;
* leakage guard: a projection whose ``as_of_date`` begins after the as-of
  date is excluded (``after_as_of``), fail closed even when that date is a
  target date misplaced there (the publication date is then unknown);
* group key: the metric family, else the metric without years, forecast
  words and the row's own forecaster/analyst tokens; the region, else the
  geography; the target year (target_date, else period_end, else year); the
  unit (case, punctuation and plural insensitive, its scale word dropped);
* values are ``value_num`` at full scale: the first scale word of ``value``
  ("1.2 million", "$1.2T"), else of ``unit`` ("USD billion"), multiplies it,
  so "1.2 million" units and "250,000" units compare;
* a group is reported when it has >= 2 distinct forecasters (forecaster,
  else analyst, else source).  Each forecaster adds one point, the median of
  its newest vintage, so a revised forecast never counts twice;
* ``spread_ratio`` is max / min for a positive level quantity (not a rate,
  share or percentage); a group is wide at :data:`WIDE_SPREAD_RATIO`;
* ``stale``: the newest vintage is older than ``stale_days`` at the as-of
  date, or dated timeline events fall after it and on or before the as-of
  date (``events_since``);
* revisions: one forecaster's consecutive vintages (different as_of_date)
  under one key, up / down / unchanged.  They are listed per group and, for
  every key including single-forecaster ones, at the top level;
* within-row ranges (low/high of RESEARCH_FORECASTER_ATTRIBUTION) are listed
  separately and never enter the group statistics.

``sha256`` hashes the canonical JSON of the payload without it (sorted keys,
compact separators, NaN rejected).  Pure; nothing here raises.
"""

from __future__ import annotations

import calendar
import datetime as _dt
import itertools
import math
import re
import statistics
import unicodedata
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..utils.canonical_json import canonical_json_sha256
from ..utils.quant_typing import PROJECTED, quant_class

SCHEMA = "drf.consensus_diagnostics/v1"
FILENAME = "consensus_evidence.json"
DEFAULT_STALE_DAYS = 120
# A group whose max/min spread is at least this counts as wide (uncalibrated DRF constant).
WIDE_SPREAD_RATIO = 2.0
AFTER_AS_OF = "after_as_of"

# Metric words that name the forecast rather than the quantity.
_FORECAST_WORDS = frozenset({
    "forecast", "forecasts", "forecasted", "forecasting", "projection", "projections", "projected",
    "estimate", "estimates", "estimated", "target", "targets", "outlook", "expected", "expectation",
    "expectations", "guidance", "prediction", "predictions", "predicted", "consensus", "base", "case",
    "预测", "预计", "目标", "展望", "预期",
})
_STOP_WORDS = frozenset({"the", "of", "in", "by", "for", "a", "an", "to", "at", "on", "and"})
# A year token of a metric ("2030", "2030e", "fy2030").
_YEAR_TOKEN_RE = re.compile(r"(?:fy)?(?:19|20|21)\d{2}[a-z]?")
_YEAR_RE = re.compile(r"(?<!\d)((?:19|20|21)\d{2})(?!\d)")
# Units, metric families and metric words of rates, shares and percentages:
# their max/min ratio says nothing about disagreement.
_RATE_UNIT_TOKENS = frozenset({
    "%", "percent", "percentage", "pct", "pp", "ppt", "bp", "bps", "basis", "ratio", "share", "rate",
    "cagr", "yoy", "growth", "x", "multiple", "probability", "百分比", "百分点",
})
_RATE_METRIC_TOKENS = frozenset({
    "share", "rate", "growth", "cagr", "probability", "penetration", "margin", "yield", "efficiency",
    "utilization", "utilisation", "ratio",
})
_DAY_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?",
                     re.I)
_MONTH_RE = re.compile(r"(\d{4})-(\d{1,2})")
_PART_RE = re.compile(r"(\d{4})[-\s]?([QH])([1-4])", re.I)
_YEAR_ONLY_RE = re.compile(r"(?:FY\s?)?(\d{4})", re.I)
_LOOSE_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
# Scale words: after a number of ``value`` (a single letter only after a
# currency sign, as the research number checks read it) or as a unit token.
_SCALE_FACTORS = {
    "thousand": 1e3, "million": 1e6, "mn": 1e6, "mln": 1e6, "billion": 1e9, "bn": 1e9, "bln": 1e9,
    "trillion": 1e12, "tn": 1e12, "trn": 1e12, "万": 1e4, "亿": 1e8, "万亿": 1e12,
    "k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12,
}
_VALUE_SCALE_RE = re.compile(
    r"\d\s*(?:(?P<word>thousand|million|billion|trillion|mn|mln|bn|bln|tn|trn)s?\b|(?P<cjk>万亿|亿|万))"
    r"|[$€£¥]\s*\d[\d,]*(?:\.\d+)?\s*(?P<letter>[kmbt])\b", re.I)
_UNIT_SCALE_TOKENS = frozenset({"thousand", "million", "mn", "mln", "billion", "bn", "bln", "trillion", "tn", "trn",
                                "万", "亿", "万亿"})

_Date = Optional[_dt.date]
_Key = Tuple[str, str, Optional[int], str]


# ── Parsing ──────────────────────────────────────────────────────────────────

def _date_bounds(value: Any) -> Tuple[_Date, _Date]:
    """``(first day, last day)`` of a stated date or period (YYYY-MM-DD with an
    optional time, YYYY-MM, YYYY-Qn, YYYY-Hn, YYYY or FYyyyy); ``(None, None)``
    for anything else."""
    if isinstance(value, _dt.datetime):
        return value.date(), value.date()
    if isinstance(value, _dt.date):
        return value, value
    text = value.strip() if isinstance(value, str) else ""
    try:
        day = _DAY_RE.fullmatch(text)
        if day:
            found = _dt.date(int(day.group(1)), int(day.group(2)), int(day.group(3)))
            return found, found
        month = _MONTH_RE.fullmatch(text)
        if month:
            year, number = int(month.group(1)), int(month.group(2))
            return (_dt.date(year, number, 1),
                    _dt.date(year, number, calendar.monthrange(year, number)[1]))
        part = _PART_RE.fullmatch(text)
        if part:
            year, kind, index = int(part.group(1)), part.group(2).upper(), int(part.group(3))
            months = 3 if kind == "Q" else 6
            if index * months > 12:
                return None, None
            last = index * months
            return (_dt.date(year, last - months + 1, 1),
                    _dt.date(year, last, calendar.monthrange(year, last)[1]))
        year_only = _YEAR_ONLY_RE.fullmatch(text)
        if year_only:
            year = int(year_only.group(1))
            return _dt.date(year, 1, 1), _dt.date(year, 12, 31)
    except ValueError:  # month 13, Feb 30, year 0
        return None, None
    return None, None


def _as_of_day(value: Any) -> _Date:
    """The as-of date: a date, or a full YYYY-MM-DD day; None otherwise (a
    coarse or missing as-of disables the leakage guard and staleness)."""
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    first, last = _date_bounds(value)
    return first if first is not None and first == last else None


def _number(value: Any) -> Optional[float]:
    """A finite number from a number or numeric text (thousands commas
    allowed); None otherwise."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip().replace(",", ""))
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _loose_number(value: Any) -> Optional[float]:
    """The first number of a bound as written ("38,000", "$1.2"); None without one."""
    exact = _number(value)
    if exact is not None or not isinstance(value, str):
        return exact
    text = re.sub(r"[,$€£¥]", "", unicodedata.normalize("NFKC", value))
    found = _LOOSE_NUMBER_RE.search(text)
    return _number(found.group(0)) if found else None


def _bound(value: Any, unit_scale: float) -> Optional[float]:
    """A within-row low/high at full scale: its own scale word, else the unit's."""
    number = _loose_number(value)
    if number is None:
        return None
    own = _value_scale(value)
    return number * (own if own != 1.0 else unit_scale)


def _clean(value: Any, limit: int = 200) -> str:
    """One-line text of a string field, capped at ``limit`` characters."""
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def _norm_text(value: Any) -> str:
    """NFKC, casefolded, punctuation-free text (``%`` kept) with single spaces."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.sub(r"[^\w%]+", " ", text).replace("_", " ").split())


def _unit_and_scale(value: Any) -> Tuple[str, float]:
    """``(unit key, scale)``: the unit compared case, punctuation and plural
    insensitively ("Units" = "unit") without its scale word, whose factor is
    the scale ("USD billions" → ("usd", 1e9))."""
    tokens: List[str] = []
    scale = 1.0
    for token in _norm_text(value).split():
        if len(token) > 3 and token.isalpha() and token.endswith("s"):
            token = token[:-1]
        if token in _UNIT_SCALE_TOKENS and scale == 1.0:
            scale = _SCALE_FACTORS[token]
            continue
        tokens.append(token)
    return " ".join(tokens), scale


def _value_scale(value: Any) -> float:
    """The factor of the first scale word after a number of a text ``value``; 1 without one."""
    if not isinstance(value, str):
        return 1.0
    found = _VALUE_SCALE_RE.search(unicodedata.normalize("NFKC", value))
    if found is None:
        return 1.0
    word = found.group("word") or found.group("cjk") or found.group("letter")
    return _SCALE_FACTORS[word.casefold()]


def _norm_metric(row: Mapping[str, Any]) -> str:
    """The metric without years, forecast words, stop words and the tokens of
    the row's own forecaster/analyst; the whole normalized metric when
    nothing else remains."""
    whole = _norm_text(row.get("metric"))
    own = set(_norm_text(f"{row.get('forecaster') or ''} {row.get('analyst') or ''}").split())
    kept = [token for token in whole.split()
            if token not in own and token not in _FORECAST_WORDS and token not in _STOP_WORDS
            and not _YEAR_TOKEN_RE.fullmatch(token)]
    return " ".join(kept) or whole


def _target_year(row: Mapping[str, Any]) -> Optional[int]:
    """The year a projection is for: the latest year target_date names, else
    period_end, else the row's ``year``; None without one."""
    for key in ("target_date", "period_end"):
        years = [int(year) for year in _YEAR_RE.findall(str(row.get(key) or ""))]
        if years:
            return max(years)
    year = row.get("year")
    if isinstance(year, str) and re.fullmatch(r"(?:19|20|21)\d{2}", year.strip()):
        return int(year)
    if isinstance(year, int) and not isinstance(year, bool) and 1900 <= year <= 2199:
        return year
    return None


def _forecaster(row: Mapping[str, Any]) -> str:
    """Who made the number: forecaster, else analyst, else source."""
    for key in ("forecaster", "analyst", "source"):
        name = _clean(row.get(key))
        if name:
            return name
    return ""


def _is_level(metric: str, unit: str) -> bool:
    """True unless the unit or the metric marks a rate, share or percentage."""
    return not (set(unit.split()) & _RATE_UNIT_TOKENS or "%" in unit
                or set(metric.split()) & _RATE_METRIC_TOKENS)


def _plain(number: float) -> Any:
    """A number at 12 significant digits (scale products drop their float
    noise), an integral one as an int (38000.0 → 38000)."""
    number = float(f"{number:.12g}")
    return int(number) if number.is_integer() and abs(number) < 1e15 else number


# ── Building ─────────────────────────────────────────────────────────────────

def _vintage_order(entry: Mapping[str, Any]) -> Tuple[_dt.date, _dt.date, str]:
    return entry["as_of_first"], entry["as_of_last"], entry["as_of_text"]


def _vintages(entries: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], float]]:
    """``(first entry, median value)`` per distinct dated as_of_date period
    (the same day or period however written), oldest first."""
    dated = sorted((e for e in entries if e["as_of_first"] is not None), key=_vintage_order)
    out: List[Tuple[Dict[str, Any], float]] = []
    for _, same in itertools.groupby(dated, key=lambda e: (e["as_of_first"], e["as_of_last"])):
        vintage = list(same)
        out.append((vintage[0], statistics.median(e["value"] for e in vintage)))
    return out


def _revisions(name: str, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One forecaster's consecutive vintages under one key: up / down / unchanged."""
    vintages = _vintages(entries)
    out = []
    for (before, old), (after, new) in itertools.pairwise(vintages):
        direction = "up" if new > old else "down" if new < old else "unchanged"
        out.append({"forecaster": name, "from_as_of": before["as_of_text"], "to_as_of": after["as_of_text"],
                    "from": _plain(old), "to": _plain(new), "direction": direction})
    return out


def _point(entries: List[Dict[str, Any]]) -> float:
    """A forecaster's point: the median of its newest vintage (all its rows when undated)."""
    vintages = _vintages(entries)
    if not vintages:
        return statistics.median(e["value"] for e in entries)
    return vintages[-1][1]


def _staleness(newest_last: _Date, as_of: _Date, event_days: List[_dt.date],
               stale_days: int) -> Tuple[Optional[bool], Optional[int]]:
    """``(stale, events_since)``; both None without an as-of or a dated vintage.
    An event counts from its first day, a vintage until its last day."""
    if as_of is None or newest_last is None:
        return None, None
    events_since = sum(1 for day in event_days if newest_last < day <= as_of)
    return (as_of - newest_last).days > stale_days or events_since > 0, events_since


def _key_record(key: _Key) -> Dict[str, Any]:
    return {"metric": key[0], "region": key[1], "target_year": key[2], "unit": key[3]}


def _build(quantitative: Any, timeline: Any, as_of: Any, stale_days: int) -> Dict[str, Any]:
    as_of_day = _as_of_day(as_of)
    counts = {"rows": 0, "projected": 0, "eligible": 0, "no_value": 0, "no_target_year": 0, "no_forecaster": 0}
    excluded: List[Dict[str, Any]] = []
    ranges: List[Dict[str, Any]] = []
    buckets: Dict[_Key, List[Dict[str, Any]]] = {}
    for row in quantitative if isinstance(quantitative, list) else []:
        if not isinstance(row, Mapping):
            continue
        counts["rows"] += 1
        if quant_class(row, as_of_day) != PROJECTED:
            continue
        counts["projected"] += 1
        as_of_text = _clean(row.get("as_of_date"), 40)
        first, last = _date_bounds(as_of_text)
        if as_of_day is not None and first is not None and first > as_of_day:
            excluded.append({"metric": _clean(row.get("metric")), "as_of_date": as_of_text, "reason": AFTER_AS_OF})
            continue
        value = _number(row.get("value_num"))
        if value is None:
            counts["no_value"] += 1
            continue
        counts["eligible"] += 1
        unit, unit_scale = _unit_and_scale(row.get("unit"))
        value_scale = _value_scale(row.get("value"))
        value *= value_scale if value_scale != 1.0 else unit_scale
        family = _norm_text(row.get("metric_family"))
        key_metric = family or _norm_metric(row)
        year = _target_year(row)
        name = _forecaster(row)
        key = (key_metric, _norm_text(row.get("region") or row.get("geography")), year, unit)
        low, high = (_bound(row.get(side), unit_scale) for side in ("low", "high"))
        if low is not None and high is not None and low <= high:
            count = row.get("n_forecasters")
            ranges.append({**_key_record(key), "row_metric": _clean(row.get("metric")), "forecaster": name,
                           "low": _plain(low), "high": _plain(high),
                           "n_forecasters": count if isinstance(count, int) and not isinstance(count, bool)
                           else None,
                           "range_kind": _clean(row.get("range_kind"), 40) or None})
        if year is None:
            counts["no_target_year"] += 1
            continue
        if not name:
            counts["no_forecaster"] += 1
            continue
        buckets.setdefault(key, []).append({
            "value": value, "name": name, "forecaster_key": _norm_text(name), "as_of_text": as_of_text,
            "as_of_first": first, "as_of_last": last})

    event_days = sorted(day for day in (_date_bounds(_clean(event.get("date"), 40))[0]
                                        for event in (timeline if isinstance(timeline, list) else [])
                                        if isinstance(event, Mapping)) if day is not None)
    groups: List[Dict[str, Any]] = []
    revisions: List[Dict[str, Any]] = []
    for key in sorted(buckets):
        by_forecaster: Dict[str, List[Dict[str, Any]]] = {}
        for entry in buckets[key]:
            by_forecaster.setdefault(entry["forecaster_key"], []).append(entry)
        names = {fkey: min(e["name"] for e in entries) for fkey, entries in by_forecaster.items()}
        key_revisions = [revision for fkey in sorted(by_forecaster, key=lambda k: (names[k].casefold(), names[k]))
                         for revision in _revisions(names[fkey], by_forecaster[fkey])]
        revisions.extend({"key": _key_record(key), **revision} for revision in key_revisions)
        if len(by_forecaster) < 2:
            continue
        points = [_point(entries) for entries in by_forecaster.values()]
        low, high = min(points), max(points)
        dated = sorted((e for e in buckets[key] if e["as_of_first"] is not None), key=_vintage_order)
        stale, events_since = _staleness(max((e["as_of_last"] for e in dated), default=None), as_of_day,
                                         event_days, stale_days)
        groups.append({
            "key": _key_record(key),
            "n_rows": len(buckets[key]),
            "n_forecasters": len(by_forecaster),
            "forecasters": sorted(names.values(), key=lambda name: (name.casefold(), name)),
            "min": _plain(low), "max": _plain(high), "median": _plain(statistics.median(points)),
            "spread_ratio": round(high / low, 4) if low > 0 and _is_level(key[0], key[3]) else None,
            "oldest_as_of": dated[0]["as_of_text"] if dated else None,
            "newest_as_of": dated[-1]["as_of_text"] if dated else None,
            "stale": stale,
            "events_since": events_since,
            "revisions": key_revisions,
        })
    excluded.sort(key=lambda item: (item["metric"], item["as_of_date"], item["reason"]))
    ranges.sort(key=lambda item: (item["metric"], item["region"], item["target_year"] or 0, item["unit"],
                                  item["forecaster"], item["low"], item["high"], item["row_metric"]))
    return {
        "schema": SCHEMA,
        "as_of": as_of_day.isoformat() if as_of_day else None,
        "stale_days": stale_days,
        "wide_spread_ratio": WIDE_SPREAD_RATIO,
        "counts": counts,
        "groups": groups,
        "ranges": ranges,
        "revisions": revisions,
        "excluded": excluded,
    }


def build_dispersion_diagnostics(quantitative: Any, timeline: Any, as_of: Any, *,
                                 stale_days: int = DEFAULT_STALE_DAYS) -> Dict[str, Any]:
    """Dispersion diagnostics of research quantitative rows (see the module
    docstring), schema :data:`SCHEMA`, with ``sha256`` over the canonical
    JSON of the rest.  ``timeline`` is timeline.json's ``[{date, event}]``;
    ``as_of`` the research as-of date (a date or YYYY-MM-DD; anything else
    disables the leakage guard and staleness).  Never raises: a failure
    yields an empty payload that names the error."""
    days = stale_days if isinstance(stale_days, int) and not isinstance(stale_days, bool) and stale_days >= 0 \
        else DEFAULT_STALE_DAYS
    try:
        payload = _build(quantitative, timeline, as_of, days)
        payload["sha256"] = canonical_json_sha256(payload)
        return payload
    except Exception as exc:  # noqa: BLE001 — diagnostics never fail a report
        failed: Dict[str, Any] = {"schema": SCHEMA, "error": f"{type(exc).__name__}: {exc}"[:300],
                                  "groups": [], "ranges": [], "revisions": [], "excluded": []}
        try:
            failed["sha256"] = canonical_json_sha256(failed)
        except Exception:  # noqa: BLE001 — an unhashable error text still returns
            failed["sha256"] = None
        return failed


def quality_summary(diagnostics: Mapping[str, Any]) -> Dict[str, Any]:
    """The digest recorded in ``forecast.quality.consensus``: ``schema``,
    ``groups_n``, ``wide_groups_n`` (spread_ratio >= :data:`WIDE_SPREAD_RATIO`),
    ``forecasters_n`` (distinct across the groups), ``excluded_n`` and
    ``sha256`` (of the full payload); ``error`` when the build failed."""
    groups = [group for group in diagnostics.get("groups") or [] if isinstance(group, Mapping)]
    forecasters = {_norm_text(name) for group in groups for name in group.get("forecasters") or []}
    summary = {
        "schema": diagnostics.get("schema", SCHEMA),
        "groups_n": len(groups),
        "wide_groups_n": sum(1 for group in groups
                             if isinstance(group.get("spread_ratio"), (int, float))
                             and group["spread_ratio"] >= WIDE_SPREAD_RATIO),
        "forecasters_n": len(forecasters),
        "excluded_n": len(diagnostics.get("excluded") or []),
        "sha256": diagnostics.get("sha256"),
    }
    if diagnostics.get("error"):
        summary["error"] = diagnostics["error"]
    return summary
