"""Source publication dates for the v3 research tools (TIME-2, RESEARCH_SOURCE_DATES).

Stdlib only and self-contained: the module is deployed beside cached_fetch.py
and research_gateway.py (both import it by bare name, lazily or behind a
try-import) and the backend tests import it straight from deerflow_bridge/.
Nothing here raises on bad input, and every regular expression runs in time
linear in its input (bounded repetitions, no nested quantifiers): the input is
untrusted web text.

Three layers:

* :func:`parse_published` turns one raw value (a provider metadata field, a
  page string, an epoch number, a ``datetime``) into a :class:`PubDate` on the
  UTC calendar with its precision, or a rejection reason.  An offset is always
  converted to UTC before the date is taken ("2025-05-10T01:00:00+05:00" is
  2025-05-09); an offset-less timestamp and an epoch are UTC, never host-local
  (no ``.timestamp()`` on a naive value, no ``fromtimestamp`` without a zone).
  A date after ``now``'s UTC date is ``future`` and a year before 1900 is
  ``pre_1900``: both rejected, never clamped.
* Candidate extractors return ``(rank, source, role, raw)`` tuples, ``role``
  being ``published`` or ``modified``: provider metadata (rank 7), JSON-LD (6),
  ``<meta>`` tags (5), ``<time datetime>`` (4), a dateline in the page head
  (3) and the URL path (2).  A search provider's row date is rank 1 and is
  built by the caller.
* :func:`resolve` keeps the highest-ranked parseable candidate per role (the
  first one on a tie) and lists the rejection reasons it met.

The extractors are DRF-original and unproven on real pages, which is why the
knob that feeds them into the research artifacts defaults off.
"""

from __future__ import annotations

import datetime as _dt
import email.utils
import html
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

# Every raw value is kept (and parsed) at most this long.
RAW_CHARS = 80
# Only the start of a page's HTML is scanned: dates live in the head.
HTML_SCAN_CHARS = 200_000
TEXT_HEAD_LINES = 40
# A page-head line longer than this is prose, never a dateline.
_TEXT_LINE_CHARS = 240
# At most this many candidates per extractor (resolve keeps the first per rank).
_MAX_CANDIDATES = 24
# fetch metadata key under which cached_fetch stores from_html() candidates.
HTML_DATES_KEY = "html_dates"

RANK_PROVIDER_META = 7
RANK_JSON_LD = 6
RANK_META_TAG = 5
RANK_TIME_TAG = 4
RANK_TEXT_HEAD = 3
RANK_URL = 2
RANK_SEARCH = 1

SOURCE_PROVIDER_META = "provider_meta"
SOURCE_JSON_LD = "json_ld"
SOURCE_META_TAG = "meta_tag"
SOURCE_TIME_TAG = "time_tag"
SOURCE_TEXT_HEAD = "text_head"
SOURCE_URL = "url_path"
SOURCE_SEARCH = "search_provider"

ROLE_PUBLISHED = "published"
ROLE_MODIFIED = "modified"
_ROLES = (ROLE_PUBLISHED, ROLE_MODIFIED)

REJECT_UNPARSEABLE = "unparseable"
REJECT_FUTURE = "future"
REJECT_PRE_1900 = "pre_1900"
MIN_YEAR = 1900

PUBLISHED_META_KEYS = (
    "publishedTime", "published_time", "article:published_time", "og:published_time",
    "datePublished", "date_published", "publishedDate", "published_date", "dcterms.created",
    "dc.date", "citation_publication_date", "citation_date", "parsely-pub-date", "sailthru.date",
)
MODIFIED_META_KEYS = (
    "modifiedTime", "modified_time", "article:modified_time", "og:updated_time",
    "dateModified", "date_modified", "updated_time",
)
_META_ROLES: dict[str, str] = {
    **{key.lower(): ROLE_PUBLISHED for key in PUBLISHED_META_KEYS},
    **{key.lower(): ROLE_MODIFIED for key in MODIFIED_META_KEYS},
}
# A metadata list value is read element-wise, at most this many elements.
_META_LIST_ITEMS = 4


@dataclass(frozen=True)
class PubDate:
    """A publication date on the UTC calendar.

    ``value`` is ``YYYY-MM-DD``, ``YYYY-MM`` or ``YYYY`` at ``precision``
    ``day`` / ``month`` / ``year``; ``instant`` is the ISO UTC timestamp when
    the raw value carried a time (else None); ``source`` is the extractor
    label and ``raw`` the value it was parsed from (at most RAW_CHARS)."""

    value: str
    precision: str
    instant: str | None
    source: str
    raw: str


def to_utc(dt: _dt.datetime) -> _dt.datetime:
    """``dt`` in UTC: a naive value IS UTC (tzinfo attached, never host-local);
    an aware one is converted (its offset is applied, never truncated)."""
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc)


def _utc_today(now: Any) -> _dt.date:
    if isinstance(now, _dt.datetime):
        return to_utc(now).date()
    if isinstance(now, _dt.date):
        return now
    return _dt.datetime.now(_dt.timezone.utc).date()


# ------------------------------------------------------------------ patterns
_MONTH_NAMES = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?" \
               r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_MONTH_INDEX = {name: index for index, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
_WEEKDAY = r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]{0,6}\.?,?\s{1,3}"
_ORDINAL = r"(?:st|nd|rd|th)?"
# A clock time after a named-month date: "May 9, 2025 10:00 AM ET" keeps its
# calendar date (the zone is unknown, so no instant is claimed).
_TRAILING_TIME = r"(?:,?\s{1,3}(?:at\s{1,3})?\d{1,2}[:.]\d{2}\b.{0,40})?"
_ZONE = r"(?P<zone>Z|UTC|GMT|[+-]\d{2}(?::?\d{2})?)"

_ISO_DATETIME_RE = re.compile(
    r"(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})[T ](?P<H>\d{1,2}):(?P<M>\d{2})"
    r"(?::(?P<S>\d{2})(?:[.,]\d{1,9})?)?\s?" + _ZONE + r"?", re.I)
_NUMERIC_DAY_RE = re.compile(r"(?P<y>\d{4})[-/.](?P<m>\d{1,2})[-/.](?P<d>\d{1,2})")
_NUMERIC_MONTH_RE = re.compile(r"(?P<y>\d{4})[-/](?P<m>\d{1,2})")
_YEAR_RE = re.compile(r"(?P<y>\d{4})")
_COMPACT_DAY_RE = re.compile(r"(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})")
_EPOCH_RE = re.compile(r"-?\d{9,13}(?:\.\d{1,6})?")
_RFC2822_RE = re.compile(
    r"(?:[a-z]{3},\s{0,3})?\d{1,2}\s{1,3}[a-z]{3}\s{1,3}\d{4}\s{1,3}\d{1,2}:\d{2}(?::\d{2})?"
    r"(?:\s{1,3}(?:[+-]\d{4}|[a-z]{1,5}))?", re.I)
_MDY_RE = re.compile(r"(?:" + _WEEKDAY + r")?(?P<mon>" + _MONTH_NAMES + r")\b\.?\s{1,3}(?P<d>\d{1,2})"
                     + _ORDINAL + r",?\s{1,3}(?P<y>\d{4})" + _TRAILING_TIME, re.I)
_DMY_RE = re.compile(r"(?:" + _WEEKDAY + r")?(?P<d>\d{1,2})" + _ORDINAL + r"\s{1,3}(?P<mon>" + _MONTH_NAMES
                     + r")\b\.?,?\s{1,3}(?P<y>\d{4})" + _TRAILING_TIME, re.I)
_MY_RE = re.compile(r"(?P<mon>" + _MONTH_NAMES + r")\b\.?,?\s{1,3}(?P<y>\d{4})", re.I)
_CJK_DAY_RE = re.compile(r"(?P<y>\d{4})\s?年\s?(?P<m>\d{1,2})\s?月\s?(?P<d>\d{1,2})\s?[日号]"
                         r"(?:\s{0,3}\d{1,2}[:：]\d{2}(?:[:：]\d{2})?)?")
_CJK_MONTH_RE = re.compile(r"(?P<y>\d{4})\s?年\s?(?P<m>\d{1,2})\s?月")

# A date inside a page-head line, right after its label (see _HEAD_LINE_RE).
_TEXT_DATE = (
    r"(?:\d{4}-\d{1,2}-\d{1,2}(?:[T ]\d{1,2}:\d{2}(?::\d{2}(?:[.,]\d{1,9})?)?"
    r"\s?(?:Z|UTC|GMT|[+-]\d{2}(?::?\d{2})?)?)?(?!\d)"
    r"|\d{4}[/.]\d{1,2}[/.]\d{1,2}(?!\d)"
    r"|\d{4}\s?年\s?\d{1,2}\s?月(?:\s?\d{1,2}\s?[日号])?"
    r"|" + _MONTH_NAMES + r"\b\.?\s{1,3}\d{1,2}" + _ORDINAL + r",?\s{1,3}\d{4}(?!\d)"
    r"|\d{1,2}" + _ORDINAL + r"\s{1,3}" + _MONTH_NAMES + r"\b\.?,?\s{1,3}\d{4}(?!\d)"
    r"|" + _MONTH_NAMES + r"\b\.?,?\s{1,3}\d{4}(?!\d))"
)
_PUBLISHED_LABELS = r"first\s+published|published(?:\s+(?:time|date|on|at))?|posted(?:\s+(?:on|at))?|date"
_MODIFIED_LABELS = r"last\s+updated|updated(?:\s+(?:on|at))?|last\s+modified|modified(?:\s+(?:on|at))?"
_HEAD_LINE_RE = re.compile(
    r"[\s*_>#|-]{0,6}(?P<label>" + _MODIFIED_LABELS + "|" + _PUBLISHED_LABELS
    + r"|发布时间|发布日期|发表于|更新时间)[\s*_]{0,3}(?P<sep>[:：]?)[\s*_]{0,3}(?:(?:on|at)\s{1,3})?"
    r"(?:" + _WEEKDAY + r")?(?P<date>" + _TEXT_DATE + r")", re.I)
_MODIFIED_LABEL_RE = re.compile(r"updated|modified|更新", re.I)

_SCRIPT_TAG_RE = re.compile(r"<script\b[^<>]{0,500}>", re.I)
_SCRIPT_CLOSE = "</script"
_LD_DATE_RE = re.compile(r'"(?P<key>datePublished|dateModified)"\s{0,20}:\s{0,20}"(?P<value>[^"\\]{1,80})"')
_META_TAG_RE = re.compile(r"<meta\b[^<>]{0,1000}>", re.I)
_TIME_TAG_RE = re.compile(r"<time\b[^<>]{0,500}>", re.I)
_ATTR_RE = re.compile(
    r"""(?P<name>[A-Za-z_:][-A-Za-z0-9_:.]{0,40})\s{0,5}=\s{0,5}"""
    r"""(?:"(?P<dq>[^"]{0,300})"|'(?P<sq>[^']{0,300})'|(?P<bare>[^\s"'=<>`]{1,300}))""")

_URL_DAY_RE = re.compile(r"/(?P<y>(?:19|20)\d{2})/(?P<m>\d{1,2})/(?P<d>\d{1,2})(?=[/.]|$)")
_URL_ISO_RE = re.compile(r"/(?P<y>(?:19|20)\d{2})-(?P<m>\d{2})-(?P<d>\d{2})(?!\d)")
_URL_COMPACT_RE = re.compile(r"/(?P<y>(?:19|20)\d{2})(?P<m>\d{2})(?P<d>\d{2})(?=/|$)")
_URL_MONTH_RE = re.compile(r"/(?P<y>(?:19|20)\d{2})/(?P<m>\d{1,2})/(?=[^/])")

_VALUE_RE = re.compile(r"(?P<y>\d{4})(?:-(?P<m>\d{2})(?:-(?P<d>\d{2}))?)?")


# ------------------------------------------------------------------ parsing
def _raw_text(value: Any) -> str:
    if isinstance(value, (_dt.datetime, _dt.date)):
        text = value.isoformat()
    else:
        text = str(value)[:RAW_CHARS * 4]
    return " ".join(text.split())[:RAW_CHARS]


def _month_number(name: str) -> int:
    return _MONTH_INDEX[name[:3].lower()]


def _checked(year: int, month: int | None, day: int | None, raw: str, source: str, today: _dt.date,
             instant: str | None = None) -> tuple[PubDate | None, str | None]:
    """The PubDate of a calendar value at its precision, or its rejection."""
    if year < MIN_YEAR:
        return None, REJECT_PRE_1900
    try:
        start = _dt.date(year, month or 1, day or 1)
    except ValueError:
        return None, REJECT_UNPARSEABLE
    if start > today:
        return None, REJECT_FUTURE
    if day is not None:
        return PubDate(f"{year:04d}-{month:02d}-{day:02d}", "day", instant, source, raw), None
    if month is not None:
        return PubDate(f"{year:04d}-{month:02d}", "month", None, source, raw), None
    return PubDate(f"{year:04d}", "year", None, source, raw), None


def _from_instant(moment: _dt.datetime, raw: str, source: str,
                  today: _dt.date) -> tuple[PubDate | None, str | None]:
    utc = to_utc(moment)
    return _checked(utc.year, utc.month, utc.day, raw, source, today,
                    instant=utc.strftime("%Y-%m-%dT%H:%M:%SZ"))


def _from_number(number: float, raw: str, source: str, today: _dt.date) -> tuple[PubDate | None, str | None]:
    if not math.isfinite(number):
        return None, REJECT_UNPARSEABLE
    if number.is_integer() and 1000 <= number <= 9999:
        return _checked(int(number), None, None, raw, source, today)
    # Values this small are "unknown" placeholders (0, -1), not 1970 dates.
    if abs(number) < 1e8:
        return None, REJECT_UNPARSEABLE
    seconds = number / 1000.0 if abs(number) > 1e12 else number
    try:
        moment = _dt.datetime.fromtimestamp(seconds, tz=_dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None, REJECT_UNPARSEABLE
    return _from_instant(moment, raw, source, today)


def _zone(text: str | None) -> _dt.tzinfo:
    if not text or text.upper() in ("Z", "UTC", "GMT"):
        return _dt.timezone.utc
    sign = -1 if text[0] == "-" else 1
    digits = text[1:].replace(":", "")
    minutes = int(digits[:2]) * 60 + (int(digits[2:4]) if len(digits) >= 4 else 0)
    return _dt.timezone(sign * _dt.timedelta(minutes=minutes))


def _from_string(text: str, raw: str, source: str, today: _dt.date) -> tuple[PubDate | None, str | None]:
    if not text:
        return None, REJECT_UNPARSEABLE
    match = _YEAR_RE.fullmatch(text)
    if match:
        return _checked(int(match["y"]), None, None, raw, source, today)
    match = _COMPACT_DAY_RE.fullmatch(text)
    if match:
        return _checked(int(match["y"]), int(match["m"]), int(match["d"]), raw, source, today)
    if _EPOCH_RE.fullmatch(text):
        return _from_number(float(text), raw, source, today)
    match = _ISO_DATETIME_RE.fullmatch(text)
    if match:
        try:
            moment = _dt.datetime(int(match["y"]), int(match["m"]), int(match["d"]), int(match["H"]),
                                  int(match["M"]), int(match["S"] or 0), tzinfo=_zone(match["zone"]))
        except (ValueError, OverflowError):
            return None, REJECT_UNPARSEABLE
        return _from_instant(moment, raw, source, today)
    for pattern, has_day in ((_NUMERIC_DAY_RE, True), (_NUMERIC_MONTH_RE, False)):
        match = pattern.fullmatch(text)
        if match:
            return _checked(int(match["y"]), int(match["m"]), int(match["d"]) if has_day else None,
                            raw, source, today)
    if _RFC2822_RE.fullmatch(text):
        try:
            moment = email.utils.parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError, OverflowError):
            moment = None
        if moment is not None:
            return _from_instant(moment, raw, source, today)
    for pattern in (_MDY_RE, _DMY_RE):
        match = pattern.fullmatch(text)
        if match:
            return _checked(int(match["y"]), _month_number(match["mon"]), int(match["d"]), raw, source, today)
    match = _MY_RE.fullmatch(text)
    if match:
        return _checked(int(match["y"]), _month_number(match["mon"]), None, raw, source, today)
    match = _CJK_DAY_RE.fullmatch(text)
    if match:
        return _checked(int(match["y"]), int(match["m"]), int(match["d"]), raw, source, today)
    match = _CJK_MONTH_RE.fullmatch(text)
    if match:
        return _checked(int(match["y"]), int(match["m"]), None, raw, source, today)
    return None, REJECT_UNPARSEABLE


def parse_published(value: Any, *, now: Any, source: str = "") -> tuple[PubDate | None, str | None]:
    """``(PubDate, None)`` for a parseable date not after ``now``'s UTC date,
    else ``(None, reason)`` with reason ``unparseable``, ``future`` or
    ``pre_1900``.  Never raises.

    Accepted: ``datetime`` (naive = UTC) and ``date``; epoch seconds and
    milliseconds (above 1e12), as numbers or digit strings; ISO-8601
    date-times with ``Z``/an offset (converted to UTC before the date is
    taken) or without one (UTC); RFC-2822; English month names ("May 9,
    2025", "9 May 2025", "May 2025"); CJK YYYY年M月D日 / YYYY年M月;
    YYYY/MM/DD, YYYY-MM-DD, YYYY.MM.DD, YYYYMMDD, YYYY-MM and YYYY."""
    try:
        today = _utc_today(now)
        if value is None or isinstance(value, bool):
            return None, REJECT_UNPARSEABLE
        raw = _raw_text(value)
        if isinstance(value, _dt.datetime):
            return _from_instant(value, raw, source, today)
        if isinstance(value, _dt.date):
            return _checked(value.year, value.month, value.day, raw, source, today)
        if isinstance(value, (int, float)):
            return _from_number(float(value), raw, source, today)
        if not isinstance(value, str):
            return None, REJECT_UNPARSEABLE
        return _from_string(raw, raw, source, today)
    except Exception:  # noqa: BLE001 — a date parser never breaks a fetch
        return None, REJECT_UNPARSEABLE


def interval_bounds(value: Any) -> tuple[_dt.date | None, _dt.date | None]:
    """``(first day, last day)`` of a ``YYYY`` / ``YYYY-MM`` / ``YYYY-MM-DD``
    value (a :attr:`PubDate.value`); ``(None, None)`` for anything else."""
    match = _VALUE_RE.fullmatch(str(value or "").strip())
    if match is None:
        return None, None
    year = int(match["y"])
    try:
        if match["d"]:
            day = _dt.date(year, int(match["m"]), int(match["d"]))
            return day, day
        if match["m"]:
            month = int(match["m"])
            start = _dt.date(year, month, 1)
            following = _dt.date(year + month // 12, month % 12 + 1, 1)
            return start, following - _dt.timedelta(days=1)
        return _dt.date(year, 1, 1), _dt.date(year, 12, 31)
    except (ValueError, OverflowError):
        return None, None


# ------------------------------------------------------------------ candidates
Candidate = tuple[int, str, str, str]


def _clip(value: Any) -> str:
    return " ".join(str(value)[:RAW_CHARS * 4].split())[:RAW_CHARS]


def from_provider_meta(meta: Any) -> list[Candidate]:
    """Rank-7 candidates of a provider's metadata mapping (Firecrawl scrape
    metadata, Exa ``publishedDate``): keys of PUBLISHED_META_KEYS /
    MODIFIED_META_KEYS, matched case-insensitively; a list value is read
    element-wise."""
    out: list[Candidate] = []
    if not isinstance(meta, Mapping):
        return out
    for key, value in meta.items():
        role = _META_ROLES.get(str(key).strip().lower())
        if role is None:
            continue
        values = list(value)[:_META_LIST_ITEMS] if isinstance(value, (list, tuple)) else [value]
        for item in values:
            if item is None or isinstance(item, (bool, Mapping, list, tuple)):
                continue
            raw = _clip(item)
            if raw:
                out.append((RANK_PROVIDER_META, SOURCE_PROVIDER_META, role, raw))
            if len(out) >= _MAX_CANDIDATES:
                return out
    return out


def _attributes(tag: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in _ATTR_RE.finditer(tag):
        name = match["name"].lower()
        if name not in attrs:
            value = match["dq"] if match["dq"] is not None else (
                match["sq"] if match["sq"] is not None else match["bare"])
            attrs[name] = html.unescape(value or "").strip()
    return attrs


def _json_ld_candidates(text: str) -> list[Candidate]:
    out: list[Candidate] = []
    pos = 0
    while len(out) < _MAX_CANDIDATES:
        tag = _SCRIPT_TAG_RE.search(text, pos)
        if tag is None:
            break
        close = text.find(_SCRIPT_CLOSE, tag.end())
        end = len(text) if close < 0 else close
        if "ld+json" in tag.group(0).lower():
            for match in _LD_DATE_RE.finditer(text, tag.end(), end):
                role = ROLE_PUBLISHED if match["key"] == "datePublished" else ROLE_MODIFIED
                out.append((RANK_JSON_LD, SOURCE_JSON_LD, role, _clip(match["value"])))
                if len(out) >= _MAX_CANDIDATES:
                    break
        if close < 0:
            break
        pos = close + len(_SCRIPT_CLOSE)
    return out


def from_html(raw: Any) -> list[Candidate]:
    """Candidates of a page's HTML (its first HTML_SCAN_CHARS): JSON-LD
    ``datePublished`` / ``dateModified`` (rank 6), ``<meta>`` tags whose
    ``property`` / ``name`` / ``itemprop`` is a known key (rank 5, attribute
    order free) and ``<time datetime>`` (rank 4)."""
    text = str(raw or "")[:HTML_SCAN_CHARS] if isinstance(raw, str) else ""
    if not text:
        return []
    out = _json_ld_candidates(text)
    metas = 0
    for match in _META_TAG_RE.finditer(text):
        attrs = _attributes(match.group(0))
        content = attrs.get("content")
        role = next((_META_ROLES[key] for key in (attrs.get(name, "").lower()
                                                  for name in ("property", "name", "itemprop"))
                     if key in _META_ROLES), None)
        if role is not None and content:
            out.append((RANK_META_TAG, SOURCE_META_TAG, role, _clip(content)))
            metas += 1
            if metas >= _MAX_CANDIDATES:
                break
    times = 0
    for match in _TIME_TAG_RE.finditer(text):
        attrs = _attributes(match.group(0))
        value = attrs.get("datetime")
        if value:
            role = _META_ROLES.get(attrs.get("itemprop", "").lower(), ROLE_PUBLISHED)
            out.append((RANK_TIME_TAG, SOURCE_TIME_TAG, role, _clip(value)))
            times += 1
            if times >= _MAX_CANDIDATES:
                break
    return out


def from_text_head(text: Any, max_lines: int = TEXT_HEAD_LINES) -> list[Candidate]:
    """Rank-3 candidates of the datelines among a page's first ``max_lines``
    lines: Published / Posted / First published / Date (published) and
    Updated / Last updated / Last modified (modified), 发布时间 / 发布日期 /
    发表于 (published) and 更新时间 (modified), each followed directly by a
    date.  A bare "Date" line needs a colon ("Date of birth 1950" is no
    dateline)."""
    out: list[Candidate] = []
    if not isinstance(text, str):
        return out
    for line in text.split("\n", max(0, int(max_lines)))[:max(0, int(max_lines))]:
        match = _HEAD_LINE_RE.match(line[:_TEXT_LINE_CHARS])
        if match is None:
            continue
        label = match["label"]
        if label.lower() == "date" and not match["sep"]:
            continue
        role = ROLE_MODIFIED if _MODIFIED_LABEL_RE.search(label) else ROLE_PUBLISHED
        out.append((RANK_TEXT_HEAD, SOURCE_TEXT_HEAD, role, _clip(match["date"])))
        if len(out) >= _MAX_CANDIDATES:
            break
    return out


def _valid_day(year: int, month: int, day: int) -> bool:
    try:
        _dt.date(year, month, day)
    except ValueError:
        return False
    return True


def from_url(url: Any) -> list[Candidate]:
    """At most one rank-2 candidate from a URL's path (never its query):
    ``/YYYY/MM/DD/`` or ``/YYYY-MM-DD`` (day), a whole ``/YYYYMMDD/``
    segment that is a valid date (day), else ``/YYYY/MM/<slug>`` (month)."""
    try:
        path = urlsplit(str(url or "").strip()).path
    except ValueError:
        return []
    for pattern in (_URL_DAY_RE, _URL_ISO_RE, _URL_COMPACT_RE):
        match = pattern.search(path)
        if match and _valid_day(int(match["y"]), int(match["m"]), int(match["d"])):
            value = f"{int(match['y']):04d}-{int(match['m']):02d}-{int(match['d']):02d}"
            return [(RANK_URL, SOURCE_URL, ROLE_PUBLISHED, value)]
    match = _URL_MONTH_RE.search(path)
    if match and 1 <= int(match["m"]) <= 12:
        return [(RANK_URL, SOURCE_URL, ROLE_PUBLISHED, f"{int(match['y']):04d}-{int(match['m']):02d}")]
    return []


def from_fetch_meta(meta: Any) -> list[Candidate]:
    """Candidates of a fetch's metadata side channel (cached_fetch): the
    provider keys (:func:`from_provider_meta`) plus the :func:`from_html`
    candidates the direct fetch stored under HTML_DATES_KEY (validated: an
    HTML rank, a known role, a string raw)."""
    out = from_provider_meta(meta)
    stored = meta.get(HTML_DATES_KEY) if isinstance(meta, Mapping) else None
    for item in stored if isinstance(stored, list) else []:
        if not isinstance(item, (list, tuple)) or len(item) != 4:
            continue
        rank, source, role, raw = item
        if (isinstance(rank, int) and not isinstance(rank, bool) and RANK_TIME_TAG <= rank <= RANK_JSON_LD
                and role in _ROLES and isinstance(source, str) and isinstance(raw, str) and raw):
            out.append((rank, source[:40], role, _clip(raw)))
        if len(out) >= 2 * _MAX_CANDIDATES:
            break
    return out


def resolve(candidates: Iterable[Any], *, now: Any) -> dict[str, Any]:
    """``{"published", "modified", "rank", "rejected"}``: per role the
    highest-ranked candidate that parses (the first one on a tie), ``rank``
    the published pick's rank (0 when none) and ``rejected`` the reason of
    every candidate that did not parse, in order.  Never raises."""
    best: dict[str, PubDate | None] = {role: None for role in _ROLES}
    ranks: dict[str, int] = {role: 0 for role in _ROLES}
    rejected: list[str] = []
    for candidate in candidates or ():
        if not isinstance(candidate, Sequence) or isinstance(candidate, str) or len(candidate) != 4:
            continue
        rank, source, role, raw = candidate
        if role not in best or not isinstance(rank, int) or isinstance(rank, bool):
            continue
        parsed, reason = parse_published(raw, now=now, source=str(source))
        if parsed is None:
            rejected.append(reason or REJECT_UNPARSEABLE)
            continue
        if best[role] is None or rank > ranks[role]:
            best[role], ranks[role] = parsed, rank
    return {"published": best[ROLE_PUBLISHED], "modified": best[ROLE_MODIFIED],
            "rank": ranks[ROLE_PUBLISHED], "rejected": rejected}
