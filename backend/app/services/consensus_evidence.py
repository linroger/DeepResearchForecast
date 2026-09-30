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
  ``value_num`` that stays finite at full scale;
* dates (``as_of_date``, timeline ``date``) are read as the research engine
  reads them (quant_typing's copy of its period parser): the strict forms,
  then a whole free-text month, quarter or half ("August 2026", "2026年8月",
  "2026年底"), then the years free text names;
* leakage guard (with a full as-of day), fail closed: a projection whose
  ``as_of_date`` begins after the as-of date is excluded (``after_as_of``),
  even when that date is a target date misplaced there (the publication date
  is then unknown), and so is one whose ``as_of_date`` states something no
  reading can date (``unparsed_as_of``: "FY29"); a blank or placeholder
  ("n/a", "unknown") ``as_of_date`` is an undated vintage;
* group key: the metric family, else the metric without years, forecast
  words and the row's own forecaster/analyst tokens; the region, else the
  geography; the target year (target_date, else period_end, else the
  bridge's ``year`` unless as_of_date names that year: the bridge fills
  ``year`` from as_of_date when a row states no period, and a publication
  year is no target); the unit (case, punctuation and plural insensitive,
  its scale word dropped);
* values are ``value_num`` at full scale: the scale word right after the
  number ``value_num`` is read from (the bridge's reading: the first range,
  else the first number; "1.2 million", "$1.2T", "1.2-1.5 trillion"), else
  the one of ``unit`` ("USD billion"), multiplies it, so "1.2 million" units
  and "250,000" units compare and "250,000 (1 million by 2035)" stays 250,000;
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

import datetime as _dt
import itertools
import math
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from ..utils.canonical_json import canonical_json_sha256
from ..utils.quant_typing import _NO_PERIOD, _loose_period_bounds, PROJECTED, quant_class

SCHEMA = "drf.consensus_diagnostics/v1"
FILENAME = "consensus_evidence.json"
DEFAULT_STALE_DAYS = 120
# A group whose max/min spread is at least this counts as wide (uncalibrated DRF constant).
WIDE_SPREAD_RATIO = 2.0
# Leakage-guard exclusion reasons: published after the as-of date, or a
# stated publication date no reading can date.
AFTER_AS_OF = "after_as_of"
UNPARSED_AS_OF = "unparsed_as_of"

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
_LOOSE_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
# Scale words: after the number value_num is read from (a single letter only
# after a currency sign, as the research number checks read it) or as a unit token.
_SCALE_FACTORS = {
    "thousand": 1e3, "million": 1e6, "mn": 1e6, "mln": 1e6, "billion": 1e9, "bn": 1e9, "bln": 1e9,
    "trillion": 1e12, "tn": 1e12, "trn": 1e12, "万": 1e4, "亿": 1e8, "万亿": 1e12,
    "k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12,
}
# The number the bridge's value_num is read from (_quant_value_num: the first
# range "a-b" / "a to b", else the first number), with the scale word right
# after it; a range's trailing word covers both numbers ("1.2-1.5 trillion").
_VALUE_NUM = r"\d[\d,]*(?:\.\d+)?"
_VALUE_SCALE_AFTER = (r"(?:\s*(?:(?P<word>thousand|million|billion|trillion|mn|mln|bn|bln|tn|trn)s?\b"
                      r"|(?P<cjk>万亿|亿|万)|(?P<letter>[kmbt])\b))?")
_VALUE_RANGE_RE = re.compile(rf"(?P<currency>[$€£¥])?\s*{_VALUE_NUM}\s*(?:[-–—~]|to)\s*[$€£¥]?\s*{_VALUE_NUM}"
                             rf"{_VALUE_SCALE_AFTER}", re.I)
_VALUE_FIRST_RE = re.compile(rf"(?P<currency>[$€£¥])?\s*{_VALUE_NUM}{_VALUE_SCALE_AFTER}", re.I)
_UNIT_SCALE_TOKENS = frozenset({"thousand", "million", "mn", "mln", "billion", "bn", "bln", "trillion", "tn", "trn",
                                "万", "亿", "万亿"})

_Date = Optional[_dt.date]
_Key = Tuple[str, str, Optional[int], str]


# ── Parsing ──────────────────────────────────────────────────────────────────

def _date_text(value: Any) -> str:
    """A date field as one line of text (a non-string as its text); "" when missing."""
    return " ".join(("" if value is None else str(value)).split())


def _states_date(text: str) -> bool:
    """True when a date field states something: not blank, not punctuation
    only and not a placeholder ("n/a", "unknown": quant_typing's no-period
    words)."""
    return any(ch.isalnum() for ch in text) and text.casefold() not in _NO_PERIOD


def _as_of_day(value: Any) -> _Date:
    """The as-of date: a date, or a full YYYY-MM-DD day; None otherwise (a
    coarse or missing as-of disables the leakage guard and staleness)."""
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    first, last = _loose_period_bounds(_date_text(value))
    return first if first is not None and first == last else None


def _number(value: Any) -> Optional[float]:
    """A finite number from a number or numeric text (thousands commas
    allowed); None otherwise."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value.strip().replace(",", "") if isinstance(value, str) else value)
    except (OverflowError, ValueError):  # not a number, or an int beyond the float range
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
    number *= own if own != 1.0 else unit_scale
    return number if math.isfinite(number) else None


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
    """The factor of the scale word right after the number a text ``value``
    is read from (its first range, else its first number: the bridge's
    value_num), a single letter only after a currency sign; 1 without one."""
    if not isinstance(value, str):
        return 1.0
    text = unicodedata.normalize("NFKC", value)
    found = _VALUE_RANGE_RE.search(text) or _VALUE_FIRST_RE.search(text)
    if found is None:
        return 1.0
    letter = found.group("letter") if found.group("currency") else None
    word = found.group("word") or found.group("cjk") or letter
    return _SCALE_FACTORS[word.casefold()] if word else 1.0


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
    period_end, else the row's ``year`` unless as_of_date names that year (the
    bridge fills ``year`` from as_of_date when a row states no period: a
    publication year is no target); None without one."""
    for key in ("target_date", "period_end"):
        years = [int(year) for year in _YEAR_RE.findall(str(row.get(key) or ""))]
        if years:
            return max(years)
    year = row.get("year")
    if isinstance(year, str) and re.fullmatch(r"(?:19|20|21)\d{2}", year.strip()):
        year = int(year)
    if not (isinstance(year, int) and not isinstance(year, bool) and 1900 <= year <= 2199):
        return None
    published = {int(named) for named in _YEAR_RE.findall(_date_text(row.get("as_of_date")))}
    return None if year in published else year


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


def _median(values: Iterable[float]) -> float:
    """:func:`statistics.median` that halves before adding, so the middle
    pair of two huge finite values never overflows (the same result otherwise)."""
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else ordered[middle - 1] / 2 + ordered[middle] / 2


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
        out.append((vintage[0], _median(e["value"] for e in vintage)))
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
        return _median(e["value"] for e in entries)
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
        date_text = _date_text(row.get("as_of_date"))
        as_of_text = date_text[:40]
        first, last = _loose_period_bounds(date_text)
        if as_of_day is not None:
            reason = (AFTER_AS_OF if first is not None and first > as_of_day
                      else UNPARSED_AS_OF if first is None and _states_date(date_text) else None)
            if reason:
                excluded.append({"metric": _clean(row.get("metric")), "as_of_date": as_of_text, "reason": reason})
                continue
        value = _number(row.get("value_num"))
        unit, unit_scale = _unit_and_scale(row.get("unit"))
        if value is not None:
            value_scale = _value_scale(row.get("value"))
            value *= value_scale if value_scale != 1.0 else unit_scale
        if value is None or not math.isfinite(value):   # unparsed, or beyond the float range at full scale
            counts["no_value"] += 1
            continue
        counts["eligible"] += 1
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

    event_days = sorted(day for day in (_loose_period_bounds(_date_text(event.get("date")))[0]
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
        ratio = high / low if low > 0 and _is_level(key[0], key[3]) else None
        dated = sorted((e for e in buckets[key] if e["as_of_first"] is not None), key=_vintage_order)
        stale, events_since = _staleness(max((e["as_of_last"] for e in dated), default=None), as_of_day,
                                         event_days, stale_days)
        groups.append({
            "key": _key_record(key),
            "n_rows": len(buckets[key]),
            "n_forecasters": len(by_forecaster),
            "forecasters": sorted(names.values(), key=lambda name: (name.casefold(), name)),
            "min": _plain(low), "max": _plain(high), "median": _plain(_median(points)),
            "spread_ratio": round(ratio, 4) if ratio is not None and math.isfinite(ratio) else None,
            "oldest_as_of": dated[0]["as_of_text"] if dated else None,
            "newest_as_of": dated[-1]["as_of_text"] if dated else None,
            "stale": stale,
            "events_since": events_since,
            "revisions": key_revisions,
        })
    excluded.sort(key=lambda item: (item["metric"], item["as_of_date"], item["reason"]))
    # Every field of a range entry, so the order (and the sha256) never depends on the row order.
    ranges.sort(key=lambda item: (item["metric"], item["region"], item["target_year"] or 0, item["unit"],
                                  item["forecaster"], item["low"], item["high"], item["row_metric"],
                                  (item["n_forecasters"] is not None, item["n_forecasters"] or 0),
                                  item["range_kind"] or ""))
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
