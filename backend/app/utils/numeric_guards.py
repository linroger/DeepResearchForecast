"""Shadow numeric-coherence guard for published binary thresholds (TIME-5).

A published binary such as "US single-year data-centre capex falls below $1.5
trillion by end-2027" priced at p=0.22 is incoherent when the dossier's latest
actual (about $0.75 trillion) already satisfies it (report_ffe1ea6bf50d F13,
roughly 0.6 Brier per row).  This module reads the threshold a binary resolves
on, binds it to the latest ACTUAL value of the same metric and records
deterministic findings:

* ``inverted_interval`` (misparse): a between-range or written range whose
  first bound exceeds its second (``between 120 and 80``);
* ``scale_mismatch`` (misparse): threshold and actual share a unit class and
  currency but differ by ``scale_ratio`` or more (a thousand/billion slip);
* ``status_quo_contradiction`` (excursion): the latest actual already
  satisfies, or already violates, the comparator by at least ``margin * |K|``
  while the probability sits on the other side of 0.5.

An excursion is ``justified`` when the binary's adjustment_rationale or
base_rate_anchor cites a source marker ([S<n>]); a misparse is a reading error
that no citation justifies.  A stamp is ``flagged`` iff it carries an
unjustified finding.

A negated event ("never falls below 8%", "fails to recover above 10%", "未超过")
is read with the inverted comparator its YES outcome needs; ranges are read
only where they are ranges ("~" before a figure means "approximately", "from
40% to 30%" is a trajectory, "the 2026 ~$700B level" is a year and an amount).

Binding order: the binary's own ``latest_actual`` field (drafted together with
the binary under NUMERIC_GUARD_MODE=shadow) when its value parses, its as_of is
already known (the stated period has ended by ``today``) and its unit is
compatible; else the single research quantitative row that states an actual
(see :func:`_row_is_actual`) whose metric tokens (Latin words plus CJK bigrams)
match the claim's metric span with Jaccard >= 0.5 and a margin >= 0.15 over
the runner-up, with a compatible unit; else ``unbound``.  Units are compatible
when unit class and currency are equal and the class is not ``unknown``: a
measure such as GW or tonnes never binds, because the guard cannot tell GW
from GWh.

Shadow only: :func:`stamp_forecast` writes ``binary['numeric_guard']`` stamps
and returns the ``quality.numeric_guards`` summary.  Nothing here changes a
probability, the report markdown, the publish gate or the final audit (the
latest_actual request that shadow adds to the binary prompt is the extractor's
and can shift what the model drafts); enforce mode is deliberately not
implemented (it needs prospective evidence, ADR 0002 I-21).

Pure and stdlib-only; no I/O; the public functions never raise (an internal
error yields ``unchecked`` / ``None`` / ``[]`` / an ``error`` summary).
"""

from __future__ import annotations

import datetime as _dt
import math
import re
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from . import quant_typing

SCHEMA = 1

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODES = (MODE_OFF, MODE_SHADOW)

DEFAULT_SCALE_RATIO = 300.0
DEFAULT_STATUS_QUO_MARGIN = 0.25

STATUS_OK = "ok"
STATUS_FLAGGED = "flagged"
STATUS_UNBOUND = "unbound"
STATUS_NOT_NUMERIC = "not_numeric"
STATUS_UNCHECKED = "unchecked"

CODE_INVERTED_INTERVAL = "inverted_interval"
CODE_SCALE_MISMATCH = "scale_mismatch"
CODE_STATUS_QUO = "status_quo_contradiction"
SEVERITY_MISPARSE = "misparse"
SEVERITY_EXCURSION = "excursion"

BASIS_LLM_FIELD = "llm_field"
BASIS_QUANT_ROW = "quant_row"

# Fields of the drafted ``latest_actual`` object and their character cap.
LATEST_ACTUAL_FIELDS = ("value", "unit", "as_of", "source_ref")
LATEST_ACTUAL_MAX_CHARS = 80

# Quant-row binding thresholds (metric-token Jaccard and lead over the runner-up).
BIND_MIN_JACCARD = 0.5
BIND_MIN_MARGIN = 0.15

_CLAIM_TEXT_MAX_CHARS = 300
_SCENARIO_FINDINGS_MAX = 20
_EPS = 1e-9

# ── Quantity parsing ─────────────────────────────────────────────────────────
_MONTHS = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
           r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
# A number with thousands separators, decimals and an optional exponent ("1e-6").
_NUMBER_RE = re.compile(r"(?<![\d.,])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+−]?\d+)?(?!\d)")
# Calendar dates masked before scanning (length-preserving): ISO days, US days,
# 年月(日), and a year followed by a two-digit month or fiscal-year tail.
_DATE_MASK_RES = (
    re.compile(r"(?<!\d)\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?!\d)"),
    re.compile(r"(?<!\d)\d{1,2}/\d{1,2}/\d{4}(?!\d)"),
    re.compile(r"(?<!\d)\d{4}\s*年\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*[日号])?"),
    re.compile(r"(?<![\d.,])(?:19|20)\d{2}\s?[-–/]\s?\d{2}(?![\d%.,])"),
)
_BARE_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
# Context that makes a bare year token a date ("in 2027", "by 2030", "end of
# 2027", "December 2027", "Dec 31, 2026", "Q3 2026") ...
_DATE_BEFORE_RE = re.compile(
    r"(?:\b(?:in|by|before|after|since|until|till|through|thru|during|for|circa|end|early|mid|late"
    r"|fy|cy)|\b(?:end|start|beginning|middle|close|as|half|quarter)\s+of|\byear[ -]?end"
    r"|\b(?:q[1-4]|h[12])|\b" + _MONTHS + r"\.?(?:\s+\d{1,2}(?:st|nd|rd|th)?,?)?)[\s,\-–]*$", re.I)
# ... or a following 年 / month / quarter / estimate suffix ("2027年", "2030E").
_DATE_AFTER_RE = re.compile(
    r"^(?:\s*(?:年|/\d{1,2}\b|[-–]?\s*(?:q[1-4]|h[12])\b|[ef]\b)|\s+" + _MONTHS + r"\b)", re.I)
# A day of the month next to a month word ("December 31", "31 December", "3月", "12日").
_DAY_BEFORE_RE = re.compile(r"\b" + _MONTHS + r"\.?\s*$", re.I)
_DAY_AFTER_RE = re.compile(r"^(?:(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTHS + r"\b|\s*[月日号](?![元圆]))", re.I)

_SYMBOL_CURRENCY = {
    "$": "USD", "us$": "USD", "u.s.$": "USD", "nt$": "TWD", "hk$": "HKD", "a$": "AUD",
    "c$": "CAD", "s$": "SGD", "€": "EUR", "£": "GBP", "¥": "JPY", "￥": "JPY", "₹": "INR",
    "₩": "KRW", "人民币": "CNY", "美元": "USD", "港币": "HKD", "新台币": "TWD",
}
_CODE_CURRENCY = {
    "usd": "USD", "eur": "EUR", "gbp": "GBP", "cny": "CNY", "rmb": "CNY", "twd": "TWD",
    "ntd": "TWD", "hkd": "HKD", "jpy": "JPY", "inr": "INR", "krw": "KRW", "aud": "AUD",
    "cad": "CAD", "sgd": "SGD", "chf": "CHF",
}
_CODES = "|".join(code.upper() for code in _CODE_CURRENCY)
_PREFIX_TOKEN = (r"(?:US|U\.S\.|NT|HK|A|C|S)?\$|[€£¥￥₹₩]|(?<![A-Za-z])(?:" + _CODES
                 + r")(?![A-Za-z])|人民币|美元|港币|新台币")
# A currency prefix (and optional sign) immediately before a number.
_PREFIX_BEFORE_RE = re.compile(r"(?P<tok>" + _PREFIX_TOKEN + r")[ \u00a0]?(?P<sign>[-−])?[ \u00a0]?$",
                               re.I)
_PREFIX_AT_RE = re.compile(r"(?P<tok>" + _PREFIX_TOKEN + r")[ \u00a0]?", re.I)
_SIGN_AT_RE = re.compile(r"[-−][ \u00a0]?")

_KIND_CLASS, _KIND_MEASURE, _KIND_SCALE, _KIND_CURRENCY = "class", "measure", "scale", "currency"
# A time span ("30 days", "3个月", "1个交易日"): a measure that states a window or a
# persistence requirement, never the level a binary resolves on.
_KIND_DURATION = "duration"
# A single-letter scale (k/m/b/t): before a "/" it reads as a scale only after a currency
# ("$5B/yr"), never in "500 t/y" or "3% m/m".
_KIND_LETTER_SCALE = "letter_scale"
_NOT_LETTER = r"(?![A-Za-z])"
# Unit tokens read after a number (and anywhere in a unit string), tried in
# order at one position: classes before measures (durations included) before
# scale words before currencies before the single-letter scales, and 万亿
# before 亿/万.  Reading stops after a class (%, pp, bp) or a measure: nothing
# scales a percentage.
_UNIT_TOKENS: Tuple[Tuple[re.Pattern, str, Any], ...] = tuple(
    (re.compile(pattern, re.I), kind, value) for pattern, kind, value in (
        (r"percentage[ \-]?points?" + _NOT_LETTER + r"|pp(?:ts?)?" + _NOT_LETTER + r"|个百分点|百分点",
         _KIND_CLASS, "pp"),
        (r"basis[ \-]?points?" + _NOT_LETTER + r"|bps?" + _NOT_LETTER + r"|个基点|基点", _KIND_CLASS, "bp"),
        (r"%|％|per[ \-]?cent" + _NOT_LETTER + r"|percent" + _NOT_LETTER, _KIND_CLASS, "percent"),
        (r"(?:(?:consecutive|straight|successive|calendar|business|trading)[ \-]+){0,2}"
         r"(?:sessions?|hours?|days?|weeks?|months?|quarters?|years?)" + _NOT_LETTER
         + r"|个?交易日|个季度|个星期|小时|个月|星期|天|周|年", _KIND_DURATION, None),
        (r"(?:[kmgt]wh?|tonnes?|tons?|mt|kt|bbl|barrels?|mb/d|b/d|bpd|km|kg|times|x)" + _NOT_LETTER
         + r"|倍|千瓦时|千瓦|兆瓦|吉瓦|太瓦|吨|桶|公里", _KIND_MEASURE, None),
        (r"trillions?" + _NOT_LETTER + r"|(?:trn|tn)" + _NOT_LETTER, _KIND_SCALE, 10 ** 12),
        (r"billions?" + _NOT_LETTER + r"|(?:bln|bn)" + _NOT_LETTER, _KIND_SCALE, 10 ** 9),
        (r"millions?" + _NOT_LETTER + r"|(?:mln|mn)" + _NOT_LETTER, _KIND_SCALE, 10 ** 6),
        (r"thousands?" + _NOT_LETTER, _KIND_SCALE, 10 ** 3),
        (r"万亿", _KIND_SCALE, 10 ** 12),
        (r"千亿", _KIND_SCALE, 10 ** 11),
        (r"百亿", _KIND_SCALE, 10 ** 10),
        (r"十亿", _KIND_SCALE, 10 ** 9),
        (r"千万", _KIND_SCALE, 10 ** 7),
        (r"百万", _KIND_SCALE, 10 ** 6),
        (r"亿", _KIND_SCALE, 10 ** 8),
        (r"万", _KIND_SCALE, 10 ** 4),
        (r"千", _KIND_SCALE, 10 ** 3),
        (r"us[ \-]?dollars?" + _NOT_LETTER + r"|dollars?" + _NOT_LETTER + r"|美元", _KIND_CURRENCY, "USD"),
        (r"euros?" + _NOT_LETTER + r"|欧元", _KIND_CURRENCY, "EUR"),
        (r"yen" + _NOT_LETTER + r"|日元|日圆", _KIND_CURRENCY, "JPY"),
        (r"港元|港币", _KIND_CURRENCY, "HKD"),
        (r"新台币|台币", _KIND_CURRENCY, "TWD"),
        (r"英镑", _KIND_CURRENCY, "GBP"),
        (r"韩元", _KIND_CURRENCY, "KRW"),
        (r"yuan" + _NOT_LETTER + r"|renminbi" + _NOT_LETTER + r"|人民币|元", _KIND_CURRENCY, "CNY"),
        (r"(?:" + _CODES + r")" + _NOT_LETTER, _KIND_CURRENCY, None),
        (r"k" + _NOT_LETTER, _KIND_LETTER_SCALE, 10 ** 3),
        (r"m" + _NOT_LETTER, _KIND_LETTER_SCALE, 10 ** 6),
        (r"b" + _NOT_LETTER, _KIND_LETTER_SCALE, 10 ** 9),
        (r"t" + _NOT_LETTER, _KIND_LETTER_SCALE, 10 ** 12),
    ))
# Currency symbols are unit tokens only inside a unit string ("US$ bn").
_UNIT_SYMBOL_RE = re.compile(_PREFIX_TOKEN, re.I)
_UNIT_GAP_RE = re.compile(r"[ \u00a0]{0,2}")
_MAX_UNIT_TOKENS = 4
# Range separators.  ASCII "~" separates only when written tight between two
# numbers ("700~725"): with a space or before a currency ("the 2026 ~$700B
# level") it means "approximately".
_RANGE_SEP_RE = re.compile(r"~(?=\d)|[ \u00a0]*(?:[–—\u2011～]|-(?![ \u00a0]*[A-Za-z])|to(?![A-Za-z])|至|到)[ \u00a0]*",
                           re.I)
# A tight hyphen, dash or tilde ("2000-2500亿元", "2000~2500亿元"), the only
# separator after which a bare year-like first bound still opens a range with a
# marked second bound.
_TIGHT_DASH_SEPS = frozenset(("-", "–", "—", "\u2011", "~", "～"))
# "from 40% to 30%", "从40%至30%": a trajectory, not an interval.
_TRAJECTORY_BEFORE_RE = re.compile(r"(?:\bfrom|从|由)[ \u00a0]*$", re.I)
_AND_SEP_RE = re.compile(r"[ \u00a0]*(?:and(?![A-Za-z])|&|和|与)[ \u00a0]*", re.I)


def _ascii_letter(char: str) -> bool:
    return ("a" <= char <= "z") or ("A" <= char <= "Z")


def _read_units(text: str, pos: int, *, symbols: bool = False, currency_known: bool = False,
                limit: int = _MAX_UNIT_TOKENS) -> Tuple[Dict[str, Any], int]:
    """Consecutive unit tokens from ``pos``: ``({scale, currency, cls, measure,
    duration, cny_mark}, end)``.  Stops at the first non-token and after a class
    or a measure (a duration is a measure).  ``currency_known`` (a prefix such as
    $) lets a single-letter scale stand before a slash ("$5B/yr")."""
    marks: Dict[str, Any] = {"scale": None, "currency": None, "cls": None, "measure": False,
                             "duration": False, "cny_mark": False}
    end = pos
    for _ in range(limit):
        gap = _UNIT_GAP_RE.match(text, end)
        at = gap.end() if gap else end
        if at >= len(text):
            break
        hit = None
        for pattern, kind, value in _UNIT_TOKENS:
            found = pattern.match(text, at)
            if found:
                hit = (found, kind, value)
                break
        if hit is None and symbols:
            found = _UNIT_SYMBOL_RE.match(text, at)
            if found:
                hit = (found, _KIND_CURRENCY, _SYMBOL_CURRENCY.get(found.group(0).lower()))
        if hit is not None and hit[1] == _KIND_LETTER_SCALE and text[hit[0].end():hit[0].end() + 1] == "/" \
                and not (currency_known or marks["currency"]):
            hit = None
        if hit is None:
            break
        found, kind, value = hit
        token = found.group(0)
        if kind == _KIND_CLASS:
            marks["cls"] = marks["cls"] or value
        elif kind in (_KIND_MEASURE, _KIND_DURATION):
            marks["measure"] = True
            marks["duration"] = kind == _KIND_DURATION
        elif kind in (_KIND_SCALE, _KIND_LETTER_SCALE):
            marks["scale"] = (marks["scale"] or 1) * value
        else:
            code = value or _CODE_CURRENCY.get(token.strip().lower())
            marks["cny_mark"] = marks["cny_mark"] or code == "CNY"
            marks["currency"] = marks["currency"] or code
        end = found.end()
        if kind in (_KIND_CLASS, _KIND_MEASURE, _KIND_DURATION):
            break
    return marks, end


def _unit_class(marks: Mapping[str, Any]) -> str:
    if marks.get("cls"):
        return str(marks["cls"])
    if marks.get("measure"):
        return "unknown"
    if marks.get("currency"):
        return "currency"
    return "count"


def _has_marks(marks: Mapping[str, Any]) -> bool:
    return bool(marks.get("scale") or marks.get("currency") or marks.get("cls")
                or marks.get("measure"))


def _kind(marks: Mapping[str, Any]) -> Optional[str]:
    """What a side measures (class, currency or measure), None for a bare number."""
    if marks.get("cls"):
        return str(marks["cls"])
    if marks.get("currency"):
        return "currency"
    return "measure" if marks.get("measure") else None


def _bare_year_side(side: Mapping[str, Any]) -> bool:
    return (side["prefix"] is None and not _has_marks(side["marks"])
            and bool(_BARE_YEAR_RE.fullmatch(side["number"])))


def _mask_dates(text: str) -> str:
    for pattern in _DATE_MASK_RES:
        text = pattern.sub(lambda m: " " * len(m.group(0)), text)
    return text


def _is_date_token(text: str, start: int, end: int, raw: str) -> bool:
    """A bare year or day number that reads as a calendar date in context."""
    before = text[max(0, start - 32):start]
    after = text[end:end + 16]
    if _BARE_YEAR_RE.fullmatch(raw):
        return bool(_DATE_BEFORE_RE.search(before) or _DATE_AFTER_RE.match(after))
    if raw.isdigit() and len(raw) <= 2 and 1 <= int(raw) <= 31:
        return bool(_DAY_BEFORE_RE.search(before) or _DAY_AFTER_RE.match(after))
    return False


def _read_side(text: str, pos: int, *, allow_prefix_at: bool) -> Optional[Dict[str, Any]]:
    """One number with its prefix currency, sign and unit tokens, starting at
    ``pos`` (second side of a range) -- or None."""
    at = pos
    prefix = None
    if allow_prefix_at:
        found = _PREFIX_AT_RE.match(text, at)
        if found:
            prefix = found.group("tok")
            at = found.end()
    negative = False
    sign = _SIGN_AT_RE.match(text, at)
    if sign:
        negative = True
        at = sign.end()
    number = _NUMBER_RE.match(text, at)
    if not number:
        return None
    side = _finish_side(text, pos, number, prefix, negative)
    return None if _is_identifier(text, side, number) else side


def _is_identifier(text: str, side: Mapping[str, Any], number: re.Match) -> bool:
    """A bare number glued to letters that are no unit ("28nm", "5G", "10th",
    "1990s"): a name or an ordinal, not a quantity."""
    return (side["prefix"] is None and not _has_marks(side["marks"])
            and _ascii_letter(text[number.end():number.end() + 1]))


def _finish_side(text: str, start: int, number: re.Match, prefix: Optional[str],
                 negative: bool) -> Dict[str, Any]:
    prefix_currency = _SYMBOL_CURRENCY.get((prefix or "").lower()) or _CODE_CURRENCY.get(
        (prefix or "").strip().lower())
    marks, end = _read_units(text, number.end(), currency_known=bool(prefix_currency))
    currency = prefix_currency or marks["currency"]
    if prefix_currency == "JPY" and (prefix or "") in ("¥", "￥") and marks["cny_mark"]:
        currency = "CNY"  # ¥ with 元 is renminbi
    marks = dict(marks, currency=currency)
    value = Decimal(number.group(0).replace(",", "").replace("−", "-"))
    return {"start": start, "end": end, "number": number.group(0), "value": -value if negative else value,
            "marks": marks, "prefix": prefix}


def _inherit(side: Dict[str, Any], other: Mapping[str, Any]) -> Dict[str, Any]:
    marks = dict(side["marks"])
    for key in ("scale", "currency", "cls"):
        if not marks.get(key) and other.get(key):
            marks[key] = other[key]
    if not marks.get("measure") and other.get("measure") and not marks.get("cls"):
        marks["measure"] = True
        marks["duration"] = bool(other.get("duration"))
    return dict(side, marks=marks)


def _side_value(side: Mapping[str, Any]) -> float:
    return float(side["value"] * Decimal(side["marks"].get("scale") or 1))


def _range_blocked(masked: str, side_a: Mapping[str, Any], sep: re.Match, side_b: Mapping[str, Any]) -> bool:
    """True when "A <sep> B" reads as two figures rather than one range: sides
    measuring different things ("5% to $10 billion"), a marked amount before a
    bare year ("10% to 2030") or a bare year before a marked amount ("2026 -
    $700B") -- except a tight dash rising to an unprefixed amount ("2000-2500
    亿元"), the one written range whose first bound looks like a year."""
    kind_a, kind_b = _kind(side_a["marks"]), _kind(side_b["marks"])
    if kind_a and kind_b and kind_a != kind_b:
        return True
    if _has_marks(side_a["marks"]) and _bare_year_side(side_b):
        return True
    if _bare_year_side(side_a) and (_has_marks(side_b["marks"]) or side_b["prefix"] is not None):
        return not (masked[sep.start():sep.end()] in _TIGHT_DASH_SEPS and side_b["prefix"] is None
                    and side_b["value"] >= side_a["value"])
    return False


def _scan(text: str, *, and_ranges: bool = False) -> List[Dict[str, Any]]:
    """Every number in ``text`` as a hit: ``{start, end, raw, date, year_like}``
    for a calendar date, else also ``{lo, hi, unit_class, currency,
    scale_explicit, range, has_marks, duration}``.  ``and_ranges`` also reads "A
    and B" as a range (the body of a between-claim).  A number glued to letters
    that are no unit ("28nm") is skipped, and "from A to B" is two figures (a
    trajectory), never a range."""
    source = str(text or "")
    masked = _mask_dates(source)
    hits: List[Dict[str, Any]] = []
    pos = 0
    while True:
        number = _NUMBER_RE.search(masked, pos)
        if not number:
            break
        start = number.start()
        prefix_match = _PREFIX_BEFORE_RE.search(masked, max(0, start - 10), start)
        prefix = prefix_match.group("tok") if prefix_match else None
        negative = bool(prefix_match and prefix_match.group("sign"))
        side_start = start - (len(prefix_match.group(0)) if prefix_match else 0)
        before = masked[side_start - 1] if side_start > 0 else ""
        if prefix is None:
            if before and _ascii_letter(before):
                pos = number.end()  # an identifier such as F13, S3, Q3 or FY2026
                continue
            if before in ("-", "−"):
                ahead = masked[side_start - 2] if side_start > 1 else ""
                if ahead and _ascii_letter(ahead):
                    pos = number.end()  # hyphenated: end-2027, COVID-19, mid-2026
                    continue
                if not ahead or not ahead.isalnum():
                    negative = True
                    side_start -= 1
        elif not negative and before in ("-", "−") and (side_start < 2
                                                         or not masked[side_start - 2].isalnum()):
            negative = True
            side_start -= 1
        raw_number = number.group(0)
        if prefix is None and not negative and _is_date_token(masked, start, number.end(), raw_number):
            hits.append({"start": start, "end": number.end(), "raw": source[start:number.end()],
                         "date": True, "year_like": True})
            pos = number.end()
            continue
        side_a = _finish_side(masked, side_start, number, prefix, negative)
        if _is_identifier(masked, side_a, number):
            pos = number.end()
            continue
        side_b = None
        if not _TRAJECTORY_BEFORE_RE.search(masked, max(0, side_start - 8), side_start):
            for sep_re in ((_RANGE_SEP_RE, _AND_SEP_RE) if and_ranges else (_RANGE_SEP_RE,)):
                sep = sep_re.match(masked, side_a["end"])
                if sep:
                    side_b = _read_side(masked, sep.end(), allow_prefix_at=True)
                    if side_b is not None and _range_blocked(masked, side_a, sep, side_b):
                        side_b = None
                    if side_b is not None:
                        break
        year_like = _bare_year_side(side_a)
        if side_b is not None:
            b_bare = _bare_year_side(side_b)
            side_a, side_b = _inherit(side_a, side_b["marks"]), _inherit(side_b, side_a["marks"])
            if year_like and b_bare:
                end = side_b["end"]
                hits.append({"start": side_start, "end": end, "raw": source[side_start:end],
                             "date": True, "year_like": True})
                pos = end
                continue
            year_like = False
        end = (side_b or side_a)["end"]
        marks = side_a["marks"]
        unit_class = _unit_class(marks)
        lo = _side_value(side_a)
        hi = _side_value(side_b) if side_b is not None else lo
        hits.append({
            "start": side_start, "end": end, "raw": source[side_start:end].strip(), "date": False,
            "year_like": year_like, "lo": lo, "hi": hi, "unit_class": unit_class,
            "currency": marks.get("currency") if unit_class == "currency" else None,
            "scale_explicit": bool(marks.get("scale")), "range": side_b is not None,
            "has_marks": _has_marks(marks) or prefix is not None, "duration": bool(marks.get("duration")),
        })
        pos = max(end, number.end())
    return hits


def _unit_marks(unit: str) -> Dict[str, Any]:
    """Unit tokens anywhere in a unit string ("USD billion", "% of GDP", "亿元")."""
    text = str(unit or "")
    total: Dict[str, Any] = {"scale": None, "currency": None, "cls": None, "measure": False,
                             "duration": False, "cny_mark": False}
    i = 0
    while i < len(text):
        char = text[i]
        if char.isspace() or (_ascii_letter(char) and i > 0 and _ascii_letter(text[i - 1])):
            i += 1
            continue
        marks, end = _read_units(text, i, symbols=True, limit=1)
        if end == i:
            i += 1
            continue
        if marks["scale"]:
            total["scale"] = (total["scale"] or 1) * marks["scale"]
        total["currency"] = total["currency"] or marks["currency"]
        total["cls"] = total["cls"] or marks["cls"]
        total["measure"] = total["measure"] or marks["measure"]
        total["duration"] = total["duration"] or marks["duration"]
        i = end
    return total


def _quantity(hit: Mapping[str, Any], unit: str = "") -> Dict[str, Any]:
    lo, hi = float(hit["lo"]), float(hit["hi"])
    unit_class, currency = hit["unit_class"], hit["currency"]
    extra = _unit_marks(unit) if unit else None
    if extra:
        if not hit["scale_explicit"] and extra["scale"]:
            lo, hi = lo * extra["scale"], hi * extra["scale"]
        if unit_class == "count":
            unit_class = _unit_class(extra)
        if unit_class == "currency" and currency is None:
            currency = extra["currency"]
    return {"lo": lo, "hi": hi, "unit_class": unit_class,
            "currency": currency if unit_class == "currency" else None, "raw": hit["raw"]}


def _readable(value: Any) -> Optional[str]:
    """Text of a string or plain number; None for anything else (objects, bools)."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    return str(value)


def _parse_quantity(text: Any, unit: Any = "") -> Optional[Dict[str, Any]]:
    source = _readable(text)
    if source is None:
        return None
    for hit in _scan(source):
        if not hit["date"]:
            return _quantity(hit, _readable(unit) or "")
    return None


def parse_quantity(text: Any, unit: Any = "") -> Optional[Dict[str, Any]]:
    """The first non-date quantity in ``text``: ``{'lo', 'hi', 'unit_class',
    'currency', 'raw'}`` in base units, or None.

    ``unit_class`` is currency | percent | pp | bp | count | unknown (a measure
    such as GW, tonnes or years).  A range ('A–B', 'A-B', 'A to B', 'A至B')
    keeps lo/hi as written, so an inversion survives for flagging.  ``unit``
    supplies the scale and currency (and class) the text itself lacks.  A bare
    19xx/20xx token next to a month word or after in/by/end- is a date.
    """
    try:
        return _parse_quantity(text, unit)
    except Exception:  # noqa: BLE001 — pure reader: never raises
        return None


# ── Threshold claims ─────────────────────────────────────────────────────────
# (pattern, comparator, strict): a strict comparator ("over", "under", "top")
# pairs only with a number right after it, so "over the next 3 years" is not a
# threshold; "the top 3" / "a top 10" are rankings, never a comparator.  A
# negated event ("does not exceed", "never falls below", "未超过") is read as
# its comparator plus the negator before it (:func:`_negation`).
_COMPARATORS: Tuple[Tuple[re.Pattern, str, bool], ...] = tuple(
    (re.compile(pattern, re.I), comparator, strict) for pattern, comparator, strict in (
        (r"\bat\s+most\b|\bno\s+(?:more|greater|higher)\s+than\b|\bnot\s+(?:more|greater|higher)\s+than\b"
         r"|\bat\s+or\s+(?:below|under)\b|\bequal\s+to\s+or\s+(?:less|lower|fewer)\s+than\b"
         r"|\b(?:less|lower|fewer)\s+than\s+or\s+equal\s+to\b", "<=", False),
        (r"\bat\s+least\b|\bno\s+(?:less|fewer|lower)\s+than\b|\bnot\s+(?:less|fewer|lower)\s+than\b"
         r"|\bat\s+or\s+(?:above|over)\b|\bequal\s+to\s+or\s+(?:greater|more|higher)\s+than\b"
         r"|\b(?:greater|more|higher)\s+than\s+or\s+equal\s+to\b", ">=", False),
        (r"\bbetween\b", "between", False),
        (r"\b(?:ris(?:e|es|ing|en)|rose|climb(?:s|ed|ing)?|trad(?:e|es|ed|ing)|clos(?:e|es|ed|ing)"
         r"|settl(?:e|es|ed|ing)|stay(?:s|ed|ing)?|remain(?:s|ed|ing)?|break(?:s|ing)?|broke)\s+above\b"
         r"|\bexceed(?:s|ed|ing)?\b|\bsurpass(?:es|ed|ing)?\b|\b(?:greater|more|higher|larger)\s+than\b"
         r"|\bin\s+excess\s+of\b|\babove\b", ">", False),
        (r"(?<!the )(?<!\ba )\btop(?:s|ped|ping)?\b", ">", True),
        (r"\bover\b", ">", True),
        (r"\b(?:fall(?:s|ing|en)?|fell|drop(?:s|ped|ping)?|dip(?:s|ped|ping)?|declin(?:e|es|ed|ing)"
         r"|slip(?:s|ped|ping)?|trad(?:e|es|ed|ing)|clos(?:e|es|ed|ing)|settl(?:e|es|ed|ing)"
         r"|stay(?:s|ed|ing)?|remain(?:s|ed|ing)?)\s+(?:below|under)\b"
         r"|\b(?:less|fewer|lower|smaller)\s+than\b|\bbelow\b", "<", False),
        (r"\bunder\b", "<", True),
        (r"≥|>=", ">=", False),
        (r"≤|<=", "<=", False),
        (r"(?<![<>=])>(?!=)", ">", False),
        (r"(?<![<>=])<(?!=)", "<", False),
        (r"不超过|不高于|至多|不多于|不大于|最多|(?:达到|等于)或(?:低于|少于|小于)", "<=", False),
        (r"不低于|不少于|至少|不小于|最少|(?:达到|等于)或(?:超过|高于|大于|超出)", ">=", False),
        (r"介于|在(?=[^，。；;,\n]{1,40}?之间)", "between", False),
        (r"超过|高于|大于|突破|超出|多于", ">", False),
        (r"低于|少于|跌破|小于", "<", False),
    ))
# Comparators written after the number ("7500亿美元以上", "5% or more").
_SUFFIX_COMPARATORS: Tuple[Tuple[re.Pattern, str], ...] = tuple(
    (re.compile(pattern, re.I), comparator) for pattern, comparator in (
        (r"[ \u00a0]*(?:[及或]?以上|or\s+(?:more|higher|greater|above|over)\b|and\s+(?:above|over)\b)", ">="),
        (r"[ \u00a0]*(?:[及或]?以下|or\s+(?:less|lower|fewer|below|under)\b|and\s+(?:below|under)\b)", "<="),
    ))
# The comparator of the negated event: "does not exceed K" holds iff the level is <= K.
_NEGATED = {">": "<=", ">=": "<", "<": ">=", "<=": ">", "between": "between"}
_NEGATION_WINDOW = 60
# EN negators, read within three words before the comparator that open no new
# clause ("fails to recover above", "won't exceed", "whether or not" and "not
# only" excluded); ZH negators right before it, after at most an adverb
# ("不会再跌破", "未超过") -- or, for a suffix comparator, before the verb that
# states the level ("未达到1万亿元以上").
_EN_NEGATOR = (r"(?:(?<![A-Za-z'’])(?:never|(?<!or )not(?!\s+(?:only|just|merely|necessarily)\b)|cannot|unless"
               r"|no\s+longer|fail(?:s|ed|ing)?\s+to|without)(?![A-Za-z])"
               r"|(?<![A-Za-z'’])[A-Za-z]+n['’]t(?![A-Za-z]))")
_EN_CLAUSE_BREAK = r"(?:and|or|but|nor|while|whereas|whether|if|when|although|though|because|which|that|who|so|then)"
_NEGATION_EN_RE = re.compile(
    _EN_NEGATOR + r"(?:\s+(?!" + _EN_CLAUSE_BREAK + r"\b)[A-Za-z][A-Za-z'’\-]*){0,3}\s+$", re.I)
_ZH_NEGATOR = r"(?:从来没有|从未|从不|并未|尚未|未能|未曾|没有|没能|不会|不能|不再|不得|无法|未|没|不)"
_ZH_ADVERB = r"(?:再次|再度|能够|可能|再|能|会|曾|有)?"
_NEGATION_ZH_RE = re.compile(_ZH_NEGATOR + _ZH_ADVERB + r"\s*$")
_NEGATION_ZH_LEVEL_RE = re.compile(
    _ZH_NEGATOR + _ZH_ADVERB
    + r"(?:达到|达|维持在|保持在|维持|保持|站上|站稳|回到|回升至|升至|涨至|增至|降至|跌至|处于|在|为|是)?\s*$")
_NEGATOR_RE = re.compile(_EN_NEGATOR + "|" + _ZH_NEGATOR, re.I)
_NEVER_RE = re.compile(r"\bnever\b|从来没有|从未|从不", re.I)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_STRICT_GAP_RE = re.compile(r"\s*(?:(?:about|around|approximately|approx\.?|roughly|nearly|almost|some|~|≈"
                            r"|约)\s*)?", re.I)
_GAP_PUNCT_RE = re.compile(r"[,;:!?，；：。！？\n]")
_GAP_MAX_EN = 30
_GAP_MAX_ZH = 12
_CLAUSE_SPLIT_RE = re.compile(r"[;；。\n]|(?<!\d)\.(?!\d)")
# A size-of-change construction makes the number a size of decline, not a level
# the latest actual can be compared with: no pair.  "<decline> by" and "a
# <decline> of" (and 跌幅/降幅) do so before any comparator ("contracts by more
# than 1%", "falls by between 5% and 10%"); a bare decline verb only before a
# magnitude comparator ("falls more than 20%", "下降超过10%") -- never before a
# level comparator ("sinks below $100", "falls between 28% and 38%").
_DECLINE_VERBS = (r"fall(?:s|ing|en)?|fell|drop(?:s|ped|ping)?|declin(?:e|es|ed|ing)|decreas(?:e|es|ed|ing)"
                  r"|contract(?:s|ed|ing)?|shr(?:ink|inks|ank|inking)|slump(?:s|ed|ing)?|plung(?:e|es|ed|ing)"
                  r"|los(?:e|es|t|ing)|slid(?:e|es|ing)?|dip(?:s|ped|ping)?|tumbl(?:e|es|ed|ing)"
                  r"|s(?:ink|inks|ank|inking)|cut(?:s|ting)?")
_DECLINE_SIZE_BEFORE_RE = re.compile(
    r"(?:\b(?:" + _DECLINE_VERBS + r")(?:\s+[A-Za-z']+){0,3}?\s+by"
    r"|\b(?:decline|drop|fall|contraction|loss|cut|decrease|reduction)\s+of)\s*$|(?:跌幅|降幅|减幅)\s*$", re.I)
_DECLINE_VERB_BEFORE_RE = re.compile(
    r"\b(?:" + _DECLINE_VERBS + r")\s*$|(?:下降|下跌|减少|萎缩|回落|下滑|缩减|收缩)了?\s*$", re.I)
_LEVEL_COMPARATOR_RE = re.compile(r"below|under|between|跌破|介于|^在$", re.I)

_EVENT_AVERAGE_RE = re.compile(r"\baverag(?:e|es|ed|ing)\b|\bmean\b|平均|均值", re.I)
_EVENT_TOUCH_RE = re.compile(
    r"\bat\s+any\s+(?:point|time)\b|\b(?:reach(?:es|ed|ing)?|hit(?:s|ting)?|touch(?:es|ed|ing)?)\b"
    r"|\btrad(?:e|es|ed|ing)\s+(?:above|below|at)\b|\ball[- ]time\s+high\b|\bintraday\b|触及|曾|盘中", re.I)
_EVENT_SETTLE_RE = re.compile(
    r"\bclos(?:e|es|ed|ing)\b|\bend\s+of\b|\byear[- ]?end\b|\bon\s+\d{4}-\d{1,2}-\d{1,2}\b|\bas\s+of\b"
    r"|\bsettl(?:e|es|ed|ing)\b|收盘|年底|年末|截至", re.I)


def _comparator_matches(text: str) -> List[Tuple[int, int, str, bool]]:
    """Non-overlapping comparator spans, earliest first and longest at a tie."""
    found = []
    for pattern, comparator, strict in _COMPARATORS:
        for match in pattern.finditer(text):
            if match.end() > match.start():
                found.append((match.start(), match.end(), comparator, strict))
    found.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    accepted: List[Tuple[int, int, str, bool]] = []
    for item in found:
        if accepted and item[0] < accepted[-1][1]:
            continue
        accepted.append(item)
    return accepted


def _event_type(text: str) -> str:
    # Most conservative reading first: an average supports no status-quo
    # inference, a touch only the satisfied side.
    if _EVENT_AVERAGE_RE.search(text):
        return "average"
    if _EVENT_TOUCH_RE.search(text):
        return "touch"
    if _EVENT_SETTLE_RE.search(text):
        return "settle"
    return "unknown"


def _gap_ok(gap: str, *, strict: bool, cjk: bool) -> bool:
    if strict:
        return bool(_STRICT_GAP_RE.fullmatch(gap))
    if _GAP_PUNCT_RE.search(gap):
        return False
    return len(gap) <= (_GAP_MAX_ZH if cjk else _GAP_MAX_EN)


def _is_threshold_hit(hit: Mapping[str, Any]) -> bool:
    # A bare 19xx/20xx count right after a comparator reads as a year
    # reference ("exceeds 2025 levels"), never as a threshold.
    return not hit["date"] and not hit.get("year_like")


def _negation(clause: str, at: int, *, level_verb: bool = False) -> Optional[Dict[str, Any]]:
    """The negator governing the comparator that starts at ``at`` (with
    ``level_verb``, the number of a suffix comparator): ``{'start', 'never'}``,
    or None when the reading is not negated -- no negator, or an even number of
    them ("does not fail to exceed")."""
    low = max(0, at - _NEGATION_WINDOW)
    before = clause[low:at]
    for pattern in (_NEGATION_EN_RE, _NEGATION_ZH_LEVEL_RE if level_verb else _NEGATION_ZH_RE):
        match = pattern.search(before)
        if match is None:
            continue
        if len(_NEGATOR_RE.findall(match.group(0))) % 2 == 0:
            return None
        return {"start": low + match.start(), "never": bool(_NEVER_RE.search(match.group(0)))}
    return None


def _pair(clause: str, start: int, comparator: str, hit: Dict[str, Any], *,
          level_verb: bool = False) -> Dict[str, Any]:
    """One reading: ``{start, comparator, hit, negated, never}``.  A negated
    event takes the inverted comparator and starts at its negator, so the text
    before ``start`` names the metric."""
    negation = _negation(clause, start, level_verb=level_verb)
    if negation is None:
        return {"start": start, "comparator": comparator, "hit": hit, "negated": False, "never": False}
    return {"start": negation["start"], "comparator": _NEGATED[comparator], "hit": hit, "negated": True,
            "never": negation["never"]}


def _size_of_change(clause: str, start: int, end: int) -> bool:
    before = clause[max(0, start - 60):start]
    if _DECLINE_SIZE_BEFORE_RE.search(before):
        return True
    return not _LEVEL_COMPARATOR_RE.search(clause[start:end]) and bool(_DECLINE_VERB_BEFORE_RE.search(before))


def _suffix_comparators(clause: str, hits: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], str, int, int]]:
    """``(hit, comparator, span start, span end)`` for each threshold number
    followed by a suffix comparator ("以上", "or more")."""
    found = []
    for hit in hits:
        if not _is_threshold_hit(hit):
            continue
        for pattern, comparator in _SUFFIX_COMPARATORS:
            match = pattern.match(clause, hit["end"])
            if match and match.end() > match.start():
                found.append((hit, comparator, match.start(), match.end()))
                break
    return found


def _pairs(clause: str) -> List[Dict[str, Any]]:
    """Comparator-number pairs in one clause (see :func:`_pair`): a comparator
    before its number, then a suffix comparator after a number no comparator
    before it claimed.  A size-of-change construction yields no pair."""
    hits = _scan(clause)
    suffixes = _suffix_comparators(clause, hits)
    comparators = [item for item in _comparator_matches(clause)
                   if not any(item[0] < end and start < item[1] for _h, _c, start, end in suffixes)]
    pairs: List[Dict[str, Any]] = []
    for index, (start, end, comparator, strict) in enumerate(comparators):
        next_start = comparators[index + 1][0] if index + 1 < len(comparators) else len(clause)
        if _size_of_change(clause, start, end):
            continue
        cjk = bool(_CJK_RE.match(clause[start:start + 1]))
        if comparator == "between":
            tail = _scan(clause[end:next_start], and_ranges=True)
            hit = dict(tail[0], start=tail[0]["start"] + end, end=tail[0]["end"] + end) if tail else None
            if hit is None or not hit.get("range"):
                continue
        else:
            # A bare year after the comparator is a reference ("exceeds its 2019 peak of $5B",
            # "the 2026 ~$700B level"): the figure it introduces is the threshold.  A strict
            # comparator pairs only with the number right after it.
            hit = next((h for h in hits if h["start"] >= end
                        and (strict or h["date"] or not h.get("year_like"))), None)
            if hit is None or hit["start"] >= next_start:
                continue
        if not _gap_ok(clause[end:hit["start"]], strict=strict, cjk=cjk) or not _is_threshold_hit(hit):
            continue
        pairs.append(_pair(clause, start, comparator, hit))
    paired = {pair["hit"]["start"] for pair in pairs}
    for hit, comparator, _start, _end in suffixes:
        before = clause[max(0, hit["start"] - 60):hit["start"]]
        if hit["start"] in paired or _DECLINE_SIZE_BEFORE_RE.search(before) \
                or _DECLINE_VERB_BEFORE_RE.search(before):
            continue  # already read, or a size of decline ("下降10%以上", "falls 20% or more")
        pairs.append(_pair(clause, hit["start"], comparator, hit, level_verb=True))
    return pairs


def _clauses(criteria: str) -> List[str]:
    return [part for part in _CLAUSE_SPLIT_RE.split(criteria) if part.strip()]


def _parse_threshold_claim(statement: Any, criteria: Any) -> Optional[Dict[str, Any]]:
    statement_text = str(statement or "")
    criteria_text = str(criteria or "")
    chosen, levels, persistence = "", [], False
    for clause in [statement_text, *_clauses(criteria_text)]:
        pairs = _pairs(clause)
        # A time span ("for at least 30 days", "至少1个交易日") is a window or a
        # persistence requirement, never the level: the clause's levels decide.
        levels = [pair for pair in pairs if not pair["hit"].get("duration")]
        if levels:
            chosen = clause
            persistence = len(levels) < len(pairs)
            break
    if len(levels) != 1:
        return None
    pair = levels[0]
    hit = pair["hit"]
    comparator = pair["comparator"]
    threshold_hi = hit["hi"] if (hit.get("range") or comparator == "between") else None
    event = _event_type(f"{statement_text} {criteria_text}")
    if event != "average" and (pair["never"] or persistence):
        # "never falls below K" negates "falls below K at some point"; a level held for a
        # span, or on at least one day, is path-dependent: both read as a touch.
        event = "touch"
    return {
        "comparator": comparator,
        "threshold": hit["lo"],
        "threshold_hi": threshold_hi,
        "unit_class": hit["unit_class"],
        "currency": hit["currency"],
        "event_type": event,
        "negated": pair["negated"],
        "text": chosen.strip()[:_CLAIM_TEXT_MAX_CHARS],
        "metric": chosen[:pair["start"]].strip()[:_CLAIM_TEXT_MAX_CHARS],
        "raw": hit["raw"],
    }


def parse_threshold_claim(statement: Any, criteria: Any) -> Optional[Dict[str, Any]]:
    """The single numeric threshold a binary resolves on, or None.

    Returns ``{'comparator', 'threshold', 'threshold_hi', 'event_type', 'text'}``
    plus ``negated``, ``unit_class``, ``currency``, ``metric`` (the span before
    the comparator or its negator, used to bind research rows) and ``raw``.
    ``comparator`` is one of > >= < <= between -- for a negated event ("does not
    exceed", "never falls below", "未超过", "fails to recover above") the
    inverted comparator the YES outcome needs, with ``negated`` True.
    Comparators written after the number ("以上", "以下", "or more", "or less")
    count too.  ``threshold``/``threshold_hi`` are base-unit numbers as written
    (``threshold_hi`` for a between or written range, else None).
    ``event_type`` is touch | average | settle | unknown; "never ..." and a
    level held for a time span ("for at least 30 days", "至少1个交易日") read as
    touch (a negated touch holds only while the level never crosses).  The
    statement is read first, then each criteria clause; zero or two+
    comparator-number pairs in the chosen clause -> None (time spans are not
    counted).
    """
    try:
        return _parse_threshold_claim(statement, criteria)
    except Exception:  # noqa: BLE001 — pure reader: never raises
        return None


# ── Binding ──────────────────────────────────────────────────────────────────
_LATIN_TOKEN_RE = re.compile(r"[a-z][a-z0-9]+")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_STOPWORDS = frozenset((
    "the", "an", "of", "in", "on", "at", "by", "for", "to", "and", "or", "with", "from", "into",
    "will", "would", "shall", "should", "could", "may", "might", "be", "is", "are", "was", "were",
    "been", "being", "its", "their", "this", "that", "these", "those", "than", "as", "per", "does",
    "do", "did", "not", "no", "any", "all", "each", "end", "year", "years", "during", "through",
    "before", "after", "until", "reach", "reaches", "fall", "falls", "rise", "rises", "remain",
    "remains", "stay", "stays", "drop", "drops", "trade", "trades", "close", "closes", "exceed",
    "exceeds", "above", "below", "over", "under", "more", "less", "least", "most", "between",
    "level", "levels", "value", "total",
))
_SPELLING = {"centre": "center", "centres": "center"}


def _metric_tokens(text: Any) -> frozenset:
    raw = str(text or "")
    tokens = set()
    for word in _LATIN_TOKEN_RE.findall(raw.lower()):
        word = _SPELLING.get(word, word)
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        if word not in _STOPWORDS:
            tokens.add(word)
    for run in _CJK_RUN_RE.findall(raw):
        if len(run) == 1:
            tokens.add(run)
        tokens.update(run[i:i + 2] for i in range(len(run) - 1))
    return frozenset(tokens)


def _jaccard(a: frozenset, b: frozenset) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


# The stated date or period of an as_of / period_end value, finest first.
_YEAR = r"((?:19|20)\d{2})"
_PERIOD_DAY_RE = re.compile(r"(?<!\d)" + _YEAR + r"[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)")
_PERIOD_MONTH_RE = re.compile(r"(?<!\d)" + _YEAR + r"(?:[-/.]|\s*年\s*)(0?[1-9]|1[0-2])(?!\d)")
_PERIOD_QUARTER_RE = re.compile(
    r"(?<![A-Za-z\d])(?:Q([1-4])[\s,/-]*" + _YEAR + r"|" + _YEAR + r"[\s/-]*Q([1-4]))(?!\d)", re.I)
_PERIOD_HALF_RE = re.compile(
    r"(?<![A-Za-z\d])(?:H([12])[\s,/-]*" + _YEAR + r"|" + _YEAR + r"[\s/-]*H([12]))(?!\d)", re.I)
_PERIOD_MONTH_NAME_RE = re.compile(
    r"\b(" + _MONTHS + r")\b\.?[\s,]*(?:\d{1,2}(?:st|nd|rd|th)?[\s,]*)?" + _YEAR + r"(?!\d)", re.I)
_PERIOD_YEAR_RE = re.compile(r"(?<!\d)" + _YEAR + r"(?!\d)")
_MONTH_ABBREVIATIONS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def _month_end(year: int, month: int) -> _dt.date:
    following = _dt.date(year + month // 12, month % 12 + 1, 1)
    return following - _dt.timedelta(days=1)


def _period_end(text: str) -> Optional[_dt.date]:
    """The LAST day of the date or period ``text`` states -- an ISO day, a
    year-month (年月), a quarter, a half, a month name, else December 31 of the
    latest year named -- or None without a 19xx/20xx year or with an impossible
    date.  A period is known only once it has ended: "2026", "FY2026" and
    "2026-Q4" end on 2026-12-31 (the rule quant_typing applies under
    RESEARCH-4)."""
    try:
        match = _PERIOD_DAY_RE.search(text)
        if match:
            return _dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        match = _PERIOD_MONTH_RE.search(text)
        if match:
            return _month_end(int(match.group(1)), int(match.group(2)))
        for pattern, months in ((_PERIOD_QUARTER_RE, 3), (_PERIOD_HALF_RE, 6)):
            match = pattern.search(text)
            if match:
                part, year = (match.group(1), match.group(2)) if match.group(1) else (
                    match.group(4), match.group(3))
                return _month_end(int(year), int(part) * months)
        match = _PERIOD_MONTH_NAME_RE.search(text)
        if match:
            month = _MONTH_ABBREVIATIONS.index(match.group(1)[:3].lower()) + 1
            return _month_end(int(match.group(2)), month)
        years = [int(year) for year in _PERIOD_YEAR_RE.findall(text)]
        return _dt.date(max(years), 12, 31) if years else None
    except ValueError:  # month 13, Feb 30
        return None


def _not_yet_known(value: Any, today: _dt.date, *, require_date: bool) -> bool:
    """True when the date or period ``value`` states ends after ``today``; a
    missing or unreadable value counts as not yet known only when
    ``require_date`` (a hindcast, where no date means no proof it precedes the
    as-of)."""
    text = _readable(value)
    end = _period_end(text) if text and text.strip() else None
    if end is None:
        return require_date
    return end > today


def _compatible(claim: Mapping[str, Any], quantity: Mapping[str, Any]) -> bool:
    return (claim["unit_class"] == quantity["unit_class"] and claim["unit_class"] != "unknown"
            and claim.get("currency") == quantity.get("currency"))


def _text_field(value: Any) -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value).strip()[:LATEST_ACTUAL_MAX_CHARS]


def sanitize_latest_actual(raw: Any) -> Optional[Dict[str, str]]:
    """The drafted ``latest_actual`` object reduced to its four string fields
    (each capped at 80 characters), or None when it is not an object or states
    no value."""
    if not isinstance(raw, Mapping):
        return None
    out = {key: _text_field(raw.get(key)) for key in LATEST_ACTUAL_FIELDS}
    return out if out["value"] else None


# value_type labels that state an actual: RESEARCH-4's "actual", the legacy
# engine's "observed" (deerflow_research quant schema) and their synonyms; none
# at all is read by the other typing fields.
_ACTUAL_VALUE_TYPES = frozenset(("", "actual", "observed", "reported", "historical"))


def _label(value: Any) -> str:
    return str(value or "").strip().lower()


def _row_is_actual(row: Mapping[str, Any], today: _dt.date, *, require_date: bool) -> bool:
    """A research row that states an ACTUAL value known by ``today``.

    The class is quant_typing.quant_class's reading of the row (the stamped
    epistemic_class, else RESEARCH-4's value_type rule, else the legacy
    value_kind): ``reported`` binds, ``projected`` never does, and ``unknown``
    binds only for a row that carries none of those fields (the spec's
    "value_type missing").  The value_type must still be an actual label, so
    an estimate, forecast or target never binds, and neither the as_of_date
    nor the period_end may end after ``today`` (with ``require_date`` the
    as_of_date must be readable)."""
    value_type = _label(row.get("value_type"))
    if value_type not in _ACTUAL_VALUE_TYPES:
        return False
    klass = quant_typing.quant_class(row, today)
    untyped = not (value_type == "actual" or _label(row.get("epistemic_class"))
                   or _label(row.get("value_kind")))
    if klass != quant_typing.REPORTED and not (klass == quant_typing.UNKNOWN and untyped):
        return False
    return not (_not_yet_known(row.get("as_of_date"), today, require_date=require_date)
                or _not_yet_known(row.get("period_end"), today, require_date=False))


def _prepare_rows(quant_rows: Any, today: _dt.date, *,
                  require_date: bool = False) -> List[Tuple[Mapping[str, Any], Dict[str, Any], frozenset]]:
    """Research rows eligible as a latest actual (:func:`_row_is_actual`) whose
    value parses and whose metric has tokens."""
    prepared = []
    for row in list(quant_rows or ()):
        if not isinstance(row, Mapping):
            continue
        try:
            if not _row_is_actual(row, today, require_date=require_date):
                continue
            value = row.get("value")
            quantity = _parse_quantity("" if value is None else value, row.get("unit") or "")
            if quantity is None:
                continue
            tokens = _metric_tokens(row.get("metric") or row.get("definition") or "")
        except Exception:  # noqa: BLE001 — a malformed row is skipped, never fatal
            continue
        if tokens:
            prepared.append((row, quantity, tokens))
    return prepared


def _bind(binary: Mapping[str, Any], claim: Mapping[str, Any], prepared: List[Tuple[Any, ...]],
          today: _dt.date, *, require_date: bool = False
          ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """``(latest_actual record, parsed quantity)`` or ``(None, None)``."""
    field = sanitize_latest_actual(binary.get("latest_actual"))
    if field is not None and not _not_yet_known(field["as_of"], today, require_date=require_date):
        quantity = _parse_quantity(field["value"], field["unit"])
        if quantity is not None and _compatible(claim, quantity):
            return dict(field, basis=BASIS_LLM_FIELD), quantity
    claim_tokens = _metric_tokens(claim.get("metric"))
    if not claim_tokens:
        return None, None
    scored = sorted(((_jaccard(claim_tokens, tokens), row, quantity)
                     for row, quantity, tokens in prepared if _compatible(claim, quantity)),
                    key=lambda item: -item[0])
    if not scored or scored[0][0] + _EPS < BIND_MIN_JACCARD:
        return None, None
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if scored[0][0] - runner_up + _EPS < BIND_MIN_MARGIN:
        return None, None
    _score, row, quantity = scored[0]
    record = {
        "value": _text_field(row.get("value")),
        "unit": _text_field(row.get("unit")),
        "as_of": _text_field(row.get("as_of_date")),
        "source_ref": _text_field(row.get("source_ref") or row.get("source")),
        "basis": BASIS_QUANT_ROW,
    }
    return record, quantity


# ── Findings ─────────────────────────────────────────────────────────────────
_SOURCE_MARKER_RE = re.compile(r"[\[【]\s*S\d+\s*[\]】]")


def _num(value: float) -> str:
    return f"{value:.4g}"


def _inverted(first: float, second: float) -> bool:
    """First bound above the second -- except two negative bounds, which are
    often written by magnitude ("-1% to -3%")."""
    return first > second and not (first < 0 and second < 0)


def _finding(code: str, severity: str, detail: str, justified: bool = False) -> Dict[str, Any]:
    return {"code": code, "severity": severity, "detail": detail, "justified": bool(justified)}


def _probability(binary: Mapping[str, Any]) -> Optional[float]:
    try:
        value = float(binary.get("probability"))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _status_quo(claim: Mapping[str, Any], actual: Mapping[str, Any], margin: float) -> Optional[str]:
    """'satisfied' / 'violated' when the latest actual already decides the
    comparator by at least ``margin * |K|``, else None."""
    comparator = claim["comparator"]
    if comparator not in (">", ">=", "<", "<="):
        return None
    k_lo = claim["threshold"]
    k_hi = claim["threshold_hi"] if claim.get("threshold_hi") is not None else k_lo
    if k_lo == 0 or k_hi == 0:
        return None  # no relative margin around a zero threshold
    above = actual["lo"] >= k_hi + margin * abs(k_hi)
    below = actual["hi"] <= k_lo - margin * abs(k_lo)
    if comparator in (">", ">="):
        return "satisfied" if above else "violated" if below else None
    return "satisfied" if below else "violated" if above else None


def _findings(binary: Mapping[str, Any], claim: Mapping[str, Any], actual: Optional[Mapping[str, Any]],
              *, scale_ratio: float, margin: float) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    k_hi = claim.get("threshold_hi")
    if k_hi is not None and _inverted(claim["threshold"], k_hi):
        findings.append(_finding(CODE_INVERTED_INTERVAL, SEVERITY_MISPARSE,
                                 f"threshold range {claim['raw']} has its first bound "
                                 f"({_num(claim['threshold'])}) above its second ({_num(k_hi)})"))
    if actual is None:
        return findings
    if _inverted(actual["lo"], actual["hi"]):
        findings.append(_finding(CODE_INVERTED_INTERVAL, SEVERITY_MISPARSE,
                                 f"latest actual range {actual['raw']} has its first bound above its second"))
    threshold_mid = claim["threshold"] if k_hi is None else (claim["threshold"] + k_hi) / 2
    actual_mid = (actual["lo"] + actual["hi"]) / 2
    if threshold_mid and actual_mid and (threshold_mid > 0) == (actual_mid > 0):
        ratio = abs(threshold_mid) / abs(actual_mid)
        if ratio >= scale_ratio or ratio <= 1.0 / scale_ratio:
            findings.append(_finding(CODE_SCALE_MISMATCH, SEVERITY_MISPARSE,
                                     f"threshold {_num(threshold_mid)} vs latest actual {_num(actual_mid)} "
                                     f"({_num(ratio)}x; limit {_num(scale_ratio)}x)"))
    if findings:
        return findings  # a misparse makes any status-quo reading meaningless
    event = claim["event_type"]
    negated = bool(claim.get("negated"))
    probability = _probability(binary)
    state = _status_quo(claim, actual, margin)
    if probability is None or state is None or event in ("average",) or claim["comparator"] == "between":
        return findings
    # A touch is settled by a level already past K, never refuted by one short of it; a
    # negated touch ("never falls below K") is the mirror: only a level already past the
    # inverted comparator's K refutes it.  Other events read both sides.
    satisfied_counts = not (event == "touch" and negated)
    violated_counts = not (event == "touch" and not negated)
    contradicted = ((state == "satisfied" and probability < 0.5 and satisfied_counts)
                    or (state == "violated" and probability > 0.5 and violated_counts))
    if contradicted:
        justified = bool(_SOURCE_MARKER_RE.search(
            f"{binary.get('adjustment_rationale') or ''} {binary.get('base_rate_anchor') or ''}"))
        findings.append(_finding(
            CODE_STATUS_QUO, SEVERITY_EXCURSION,
            f"latest actual {_num(actual['lo'])}"
            + (f"–{_num(actual['hi'])}" if actual["hi"] != actual["lo"] else "")
            + f" already {'satisfies' if state == 'satisfied' else 'violates'} "
            f"'{claim['comparator']} {_num(claim['threshold'])}' ({'negated ' if negated else ''}{event} "
            f"event) by at least "
            f"{_num(margin * 100)}% of the threshold, yet p={_num(probability)}", justified))
    return findings


def _stamp(status: str, claim: Optional[Dict[str, Any]], latest_actual: Optional[Dict[str, Any]],
           findings: List[Dict[str, Any]], error: Optional[str] = None) -> Dict[str, Any]:
    stamp = {"schema": SCHEMA, "status": status, "claim": claim, "latest_actual": latest_actual,
             "findings": findings}
    if error:
        stamp["error"] = error
    return stamp


def _check(binary: Mapping[str, Any], prepared: List[Tuple[Any, ...]], *, scale_ratio: float,
           margin: float, today: _dt.date, require_as_of: bool = False) -> Dict[str, Any]:
    if not isinstance(binary, Mapping):
        raise TypeError("binary forecast is not an object")
    claim = _parse_threshold_claim(binary.get("statement"), binary.get("resolution_criteria"))
    if claim is None:
        return _stamp(STATUS_NOT_NUMERIC, None, None, [])
    latest_actual, actual = _bind(binary, claim, prepared, today, require_date=require_as_of)
    findings = _findings(binary, claim, actual, scale_ratio=scale_ratio, margin=margin)
    if any(not finding["justified"] for finding in findings):
        status = STATUS_FLAGGED
    elif latest_actual is None:
        status = STATUS_UNBOUND
    else:
        status = STATUS_OK
    return _stamp(status, claim, latest_actual, findings)


def _unchecked(exc: BaseException) -> Dict[str, Any]:
    return _stamp(STATUS_UNCHECKED, None, None, [], error=type(exc).__name__)


def _settings(scale_ratio: Any, margin: Any) -> Tuple[float, float]:
    """Knob values made safe: ratio > 1 and 0 <= margin < 1, else the defaults."""
    try:
        ratio = float(scale_ratio)
    except (TypeError, ValueError):
        ratio = DEFAULT_SCALE_RATIO
    if not math.isfinite(ratio) or ratio <= 1.0:
        ratio = DEFAULT_SCALE_RATIO
    try:
        m = float(margin)
    except (TypeError, ValueError):
        m = DEFAULT_STATUS_QUO_MARGIN
    if not math.isfinite(m) or not 0.0 <= m < 1.0:
        m = DEFAULT_STATUS_QUO_MARGIN
    return ratio, m


def _as_date(today: Any) -> _dt.date:
    return today if isinstance(today, _dt.date) else _dt.date.today()


def check_binary(binary: Any, *, quant_rows: Iterable[Any] = (), scale_ratio: float = DEFAULT_SCALE_RATIO,
                 status_quo_margin: float = DEFAULT_STATUS_QUO_MARGIN,
                 today: Optional[_dt.date] = None, require_as_of: bool = False) -> Dict[str, Any]:
    """The numeric-guard stamp of one binary forecast.

    ``{'schema': 1, 'status', 'claim', 'latest_actual', 'findings'}``; status is
    ok | flagged | unbound | not_numeric | unchecked (an internal error, with
    ``error`` naming its type -- never ``ok``).  ``latest_actual`` is
    ``{value, unit, as_of, source_ref, basis: llm_field|quant_row}`` or None.
    ``today`` (default: the system date) decides what is not yet known: an
    as_of or period_end whose stated period ENDS after it never binds ("2026"
    ends on 2026-12-31).  ``require_as_of`` (a hindcast, ``today`` being its
    pinned as-of) also refuses an as_of that is missing or unreadable.
    """
    try:
        day = _as_date(today)
        ratio, margin = _settings(scale_ratio, status_quo_margin)
        strict = bool(require_as_of)
        return _check(binary, _prepare_rows(quant_rows, day, require_date=strict), scale_ratio=ratio,
                      margin=margin, today=day, require_as_of=strict)
    except Exception as exc:  # noqa: BLE001 — an internal error is 'unchecked', never 'ok'
        return _unchecked(exc)


def _scenario_ranges(criteria: str) -> List[Dict[str, Any]]:
    ranges = []
    for _start, end, comparator, _strict in _comparator_matches(criteria):
        if comparator != "between":
            continue
        tail = _scan(criteria[end:end + 80], and_ranges=True)
        if tail and tail[0].get("range") and not tail[0]["date"]:
            ranges.append(tail[0])
    for hit in _scan(criteria):
        if hit.get("range") and not hit["date"] and hit.get("has_marks"):
            ranges.append(hit)
    return ranges


def check_scenarios(scenarios: Any) -> List[Dict[str, Any]]:
    """``inverted_interval`` findings for between-ranges and written ranges in
    scenario resolution criteria whose first bound exceeds the second."""
    try:
        findings: List[Dict[str, Any]] = []
        for scenario in list(scenarios or ()):
            if not isinstance(scenario, Mapping):
                continue
            seen = set()
            for hit in _scenario_ranges(str(scenario.get("resolution_criteria") or "")):
                if _inverted(hit["lo"], hit["hi"]) and hit["raw"] not in seen:
                    seen.add(hit["raw"])
                    findings.append(dict(
                        _finding(CODE_INVERTED_INTERVAL, SEVERITY_MISPARSE,
                                 f"range {hit['raw']} has its first bound ({_num(hit['lo'])}) above its "
                                 f"second ({_num(hit['hi'])})"),
                        scenario=str(scenario.get("name") or "")[:120]))
        return findings[:_SCENARIO_FINDINGS_MAX]
    except Exception:  # noqa: BLE001 — shadow diagnostic: never raises
        return []


def stamp_forecast(forecast: Any, *, quant_rows: Iterable[Any] = (), mode: str = MODE_SHADOW,
                   scale_ratio: float = DEFAULT_SCALE_RATIO, margin: float = DEFAULT_STATUS_QUO_MARGIN,
                   today: Optional[_dt.date] = None, require_as_of: bool = False) -> Dict[str, Any]:
    """Stamp every binary (``b['numeric_guard']``) and return the
    ``quality.numeric_guards`` summary (``today`` and ``require_as_of`` as in
    :func:`check_binary`).

    ``{'mode', 'status': ran|not_run, 'n_binaries', 'n_numeric', 'n_bound',
    'by_status', 'findings_by_code', 'scenario_findings', 'scale_ratio',
    'status_quo_margin'}``; ``not_run`` when the forecast has no binaries (the
    scenario check still runs).  An internal error returns ``{'mode', 'status':
    'error', 'error'}`` instead of raising.
    """
    try:
        day = _as_date(today)
        ratio, m = _settings(scale_ratio, margin)
        binaries = forecast.get("binary_forecasts") if isinstance(forecast, Mapping) else None
        rows = [b for b in binaries if isinstance(b, dict)] if isinstance(binaries, list) else []
        strict = bool(require_as_of)
        prepared = _prepare_rows(quant_rows, day, require_date=strict) if rows else []
        by_status: Dict[str, int] = {}
        by_code: Dict[str, int] = {}
        n_numeric = n_bound = 0
        for binary in rows:
            try:
                stamp = _check(binary, prepared, scale_ratio=ratio, margin=m, today=day, require_as_of=strict)
            except Exception as exc:  # noqa: BLE001 — one bad row is 'unchecked', the rest still run
                stamp = _unchecked(exc)
            binary["numeric_guard"] = stamp
            by_status[stamp["status"]] = by_status.get(stamp["status"], 0) + 1
            n_numeric += stamp["claim"] is not None
            n_bound += stamp["latest_actual"] is not None
            for finding in stamp["findings"]:
                by_code[finding["code"]] = by_code.get(finding["code"], 0) + 1
        return {
            "mode": mode,
            "status": "ran" if rows else "not_run",
            "n_binaries": len(rows),
            "n_numeric": n_numeric,
            "n_bound": n_bound,
            "by_status": by_status,
            "findings_by_code": by_code,
            "scenario_findings": check_scenarios(
                forecast.get("scenarios") if isinstance(forecast, Mapping) else None),
            "scale_ratio": ratio,
            "status_quo_margin": m,
        }
    except Exception as exc:  # noqa: BLE001 — shadow diagnostic: never raises
        return {"mode": mode, "status": "error", "error": type(exc).__name__}


def normalize_mode(value: Any) -> Tuple[str, bool]:
    """``(mode, valid)``: off | shadow; anything else (including empty) is
    ``('shadow', False)`` so the caller can warn."""
    text = str(value if value is not None else "").strip().lower()
    if text in MODES:
        return text, True
    return MODE_SHADOW, False
