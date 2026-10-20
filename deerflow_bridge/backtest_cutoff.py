"""Backtest mode: one as-of cutoff for every external input of a research run.

Design: ``docs/handoff/backtest/design.md``.  A backtest pipeline pins an as-of
date; the orchestrator hands the research child one parent-owned variable,
``DRF_BACKTEST_POLICY`` (compact JSON), and every research-side input reads it
through this module: web search (``search_tools``), fetch and search rendering
(``research_gateway.ResearchTools``), the plan date (``linear_research``),
official data (``data_sources``) and prediction markets
(``deerflow_research._collect_prediction_markets``).  The backend imports the
same module (``official_data.bridge_module``) for the report stage.

Without the variable nothing here runs: every caller checks
``policy_from_env`` first and keeps its live path unchanged.

Semantics:

* The cutoff is the END of the as-of day in UTC; a source dated on the as-of
  day is admissible.
* A date is an interval with a precision (day, month or year).  A source is
  ``before`` when every date known about it ends at or before the cutoff,
  ``after`` when any of them starts after it (a page published before the
  cutoff but modified after it is ``after``) and ``undated`` otherwise (no date,
  or a month or year that straddles the cutoff).
* ``after`` sources are always dropped; ``undated`` ones are kept and flagged in
  lenient mode and dropped in strict mode (the default).
* Every decision is appended to the audit file named by the policy.

Stdlib only: the module is deployed beside the other bridge modules and runs
in both the deer-flow and the backend virtual environments.
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Iterable, Mapping, Sequence

POLICY_ENV = "DRF_BACKTEST_POLICY"
POLICY_VERSION = "backtest/v1"
ARCHIVES = ("wayback", "off")
VERDICTS = ("before", "after", "undated")

# Strict mode admits a current-revision observation only once its period ended
# at least this many days before the cutoff (a conservative publication lag;
# a vintage-dated value needs none).  Unknown frequencies use the annual lag.
RELEASE_LAG_DAYS = {"D": 1, "W": 7, "M": 45, "Q": 90, "A": 180}
# A market price older than this at the cutoff is not "the price at the cutoff".
MARKET_PRICE_MAX_AGE_S = 7 * 86400

WAYBACK_CDX_URL = "https://web.archive.org/cdx/search/cdx"
WAYBACK_SNAPSHOT_URL = "https://web.archive.org/web/{timestamp}id_/{original}"
_HTTP_UA = ("Mozilla/5.0 (compatible; DeepResearchForecast-backtest/1.0; "
            "+https://github.com/linroger/DeepResearchForecast)")


class BacktestPolicyError(ValueError):
    """``DRF_BACKTEST_POLICY`` is set but is not a valid policy (fail closed)."""


@dataclass(frozen=True)
class BacktestPolicy:
    as_of: date
    strict: bool = True
    archive: str = "wayback"
    audit_path: str = ""

    @property
    def as_of_iso(self) -> str:
        return self.as_of.isoformat()

    @property
    def cutoff(self) -> datetime:
        """The last admissible instant: the end of the as-of day (UTC)."""
        return datetime.combine(self.as_of, dtime(23, 59, 59), tzinfo=timezone.utc)

    @property
    def cutoff_ts(self) -> int:
        return int(self.cutoff.timestamp())

    @property
    def tag(self) -> str:
        """Cache-key namespace: requests and filters differ by date and strictness."""
        return f"backtest:{self.as_of_iso}:{'strict' if self.strict else 'lenient'}"

    def to_dict(self) -> dict:
        return {"version": POLICY_VERSION, "as_of": self.as_of_iso, "strict": self.strict,
                "archive": self.archive, "audit_path": self.audit_path}

    def to_env(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_policy(value: Any) -> BacktestPolicy:
    """A policy from its JSON text or mapping; raises :class:`BacktestPolicyError`."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise BacktestPolicyError(f"{POLICY_ENV} is not JSON") from None
    if not isinstance(value, Mapping):
        raise BacktestPolicyError(f"{POLICY_ENV} must be a JSON object")
    raw_as_of = str(value.get("as_of") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_as_of):
        raise BacktestPolicyError("backtest as_of must be a YYYY-MM-DD date")
    try:
        as_of = date.fromisoformat(raw_as_of)
    except ValueError:
        raise BacktestPolicyError(f"backtest as_of is not a calendar date: {raw_as_of}") from None
    strict = value.get("strict", True)
    if not isinstance(strict, bool):
        raise BacktestPolicyError("backtest strict must be true or false")
    archive = str(value.get("archive") or "wayback").strip().lower()
    if archive not in ARCHIVES:
        raise BacktestPolicyError(f"backtest archive must be one of {ARCHIVES}")
    audit_path = value.get("audit_path") or ""
    if not isinstance(audit_path, str):
        raise BacktestPolicyError("backtest audit_path must be a string")
    return BacktestPolicy(as_of=as_of, strict=strict, archive=archive, audit_path=audit_path)


def policy_from_env(env: Mapping[str, str] | None = None) -> BacktestPolicy | None:
    """The run's policy, ``None`` for a live run; an invalid value raises."""
    raw = str((os.environ if env is None else env).get(POLICY_ENV) or "").strip()
    return parse_policy(raw) if raw else None


# =============================================================== dates

@dataclass(frozen=True)
class DateSpan:
    """A date known about a source: the interval it may lie in, and where it came from."""
    start: date
    end: date
    precision: str      # day | month | year
    kind: str           # published | modified | captured
    basis: str          # where the date was read (field name, "url", "page:…", "archive")

    def to_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(),
                "precision": self.precision, "kind": self.kind, "basis": self.basis}


_MONTHS = {name: index for index, names in enumerate(
    (("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",),
     ("jun", "june"), ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
     ("oct", "october"), ("nov", "november"), ("dec", "december")), start=1) for name in names}
_MONTH_RE = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
             r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?"
                     r"\s*(Z|[+-]\d{2}:?\d{2})?)?", re.I)
_YEAR_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_YEAR_RE = re.compile(r"^(\d{4})$")
_SLASH_YMD_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")
_MDY_RE = re.compile(_MONTH_RE + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", re.I)
_DMY_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+" + _MONTH_RE + r"\.?,?\s+(\d{4})", re.I)
_MY_RE = re.compile(_MONTH_RE + r"\.?,?\s+(\d{4})", re.I)
_CJK_YMD_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
_CJK_YM_RE = re.compile(r"(\d{4})年(\d{1,2})月")
_RELATIVE_RE = re.compile(r"^(\d+|an?|one)\s+(second|sec|minute|min|hour|hr|day|week|month|year)s?\s+ago$", re.I)
_RELATIVE_DAYS = {"second": 0, "sec": 0, "minute": 0, "min": 0, "hour": 0, "hr": 0,
                  "day": 1, "week": 7, "month": 31, "year": 366}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _valid_day(year: int, month: int, day: int) -> date | None:
    if not 1900 <= year <= 2100:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _month_span(year: int, month: int) -> tuple[date, date] | None:
    first = _valid_day(year, month, 1)
    if first is None:
        return None
    return first, _month_end(first)


def _month_end(day: date) -> date:
    following = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
    return following - timedelta(days=1)


def _month_number(name: str) -> int:
    """1..12 for a month name or abbreviation (``0`` when unknown)."""
    key = str(name or "").lower().rstrip(".")
    return _MONTHS.get(key, _MONTHS.get(key[:3], 0))


def parse_date(value: Any, *, now: datetime | None = None) -> tuple[date, date, str] | None:
    """``(start, end, precision)`` of one date value, or ``None``.

    Reads ISO dates and timestamps (an offset is converted to UTC), RFC 2822,
    "Nov 5, 2024", "5 November 2024", "November 2024", "2024-11", "2024",
    "2024/11/05", Chinese "2024年11月5日", epoch seconds or milliseconds, and
    relative ages ("3 days ago", "yesterday"), which are resolved against
    ``now`` (the wall clock): a relative age always means recent.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value) / (1000.0 if abs(value) > 1e11 else 1.0)
        try:
            day = datetime.fromtimestamp(seconds, timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
        return (day, day, "day") if 1900 <= day.year <= 2100 else None
    text = " ".join(str(value).split()).strip()
    if not text or len(text) > 120:
        return None
    lowered = text.lower()
    current = now or _utcnow()
    if lowered in ("today", "just now", "now"):
        return current.date(), current.date(), "day"
    if lowered == "yesterday":
        day = current.date() - timedelta(days=1)
        return day, day, "day"
    relative = _RELATIVE_RE.match(lowered)
    if relative:
        count = 1 if relative.group(1) in ("a", "an", "one") else int(relative.group(1))
        day = (current - timedelta(days=count * _RELATIVE_DAYS[relative.group(2)])).date()
        return day, day, "day"
    iso = _ISO_RE.match(text)
    if iso:
        year, month, day_n = int(iso.group(1)), int(iso.group(2)), int(iso.group(3))
        day = _valid_day(year, month, day_n)
        if day is None:
            return None
        if iso.group(4) is not None and iso.group(7):
            try:
                stamp = datetime.fromisoformat(iso.group(0).replace("z", "Z").replace(" ", "T", 1))
                day = stamp.astimezone(timezone.utc).date()
            except ValueError:
                pass
        return day, day, "day"
    match = _YEAR_MONTH_RE.match(text)
    if match:
        span = _month_span(int(match.group(1)), int(match.group(2)))
        return (span[0], span[1], "month") if span else None
    match = _YEAR_RE.match(text)
    if match:
        year = int(match.group(1))
        return (date(year, 1, 1), date(year, 12, 31), "year") if 1900 <= year <= 2100 else None
    try:
        stamp = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        stamp = None
    if stamp is not None:
        if stamp.tzinfo is not None:
            stamp = stamp.astimezone(timezone.utc)
        day = stamp.date()
        return (day, day, "day") if 1900 <= day.year <= 2100 else None
    for pattern, order in ((_SLASH_YMD_RE, "ymd"), (_MDY_RE, "mdy"), (_DMY_RE, "dmy"), (_CJK_YMD_RE, "ymd")):
        match = pattern.search(text)
        if not match:
            continue
        a, b, c = match.groups()
        if order == "ymd":
            day = _valid_day(int(a), int(b), int(c))
        elif order == "mdy":
            day = _valid_day(int(c), _month_number(a), int(b))
        else:
            day = _valid_day(int(c), _month_number(b), int(a))
        if day is not None:
            return day, day, "day"
    for pattern, swap in ((_MY_RE, False), (_CJK_YM_RE, True)):
        match = pattern.search(text)
        if not match:
            continue
        if swap:
            span = _month_span(int(match.group(1)), int(match.group(2)))
        else:
            span = _month_span(int(match.group(2)), _month_number(match.group(1)))
        if span:
            return span[0], span[1], "month"
    return None


def date_span(value: Any, *, kind: str, basis: str, now: datetime | None = None) -> DateSpan | None:
    parsed = parse_date(value, now=now)
    if parsed is None:
        return None
    return DateSpan(parsed[0], parsed[1], parsed[2], kind, basis)


_URL_DAY_RE = re.compile(r"/((?:19|20)\d{2})[/-](\d{1,2})[/-](\d{1,2})(?=[/_.-]|$)")
_URL_COMPACT_RE = re.compile(r"/((?:19|20)\d{2})(\d{2})(\d{2})(?=[/_.-]|$)")
_URL_MONTH_RE = re.compile(r"/((?:19|20)\d{2})[/-](\d{1,2})(?=/)")


def url_date(url: Any) -> DateSpan | None:
    """The date in a URL path (``/2024/11/05/``, ``/2024-11-05-slug``,
    ``/20241105/``, or a month ``/2024/11/``), or ``None``."""
    try:
        path = urllib.parse.urlsplit(str(url or "")).path
    except ValueError:
        return None
    for pattern in (_URL_DAY_RE, _URL_COMPACT_RE):
        match = pattern.search(path)
        if match:
            day = _valid_day(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            if day is not None:
                return DateSpan(day, day, "day", "published", "url")
    match = _URL_MONTH_RE.search(path)
    if match:
        span = _month_span(int(match.group(1)), int(match.group(2)))
        if span:
            return DateSpan(span[0], span[1], "month", "published", "url")
    return None


# Result-row fields that date a search hit, by kind.
_PUBLISHED_FIELDS = ("date", "published_date", "publishedDate", "published", "published_at",
                     "publishedAt", "datePublished", "pubDate", "page_age", "age")
_MODIFIED_FIELDS = ("last_updated", "lastUpdated", "updated", "updated_at", "dateModified",
                    "modified", "last_modified", "lastModified")


def result_dates(row: Mapping[str, Any], *, now: datetime | None = None) -> list[DateSpan]:
    """Every date a search-result row carries: its own fields, then its URL path."""
    spans: list[DateSpan] = []
    for kind, names in (("published", _PUBLISHED_FIELDS), ("modified", _MODIFIED_FIELDS)):
        for name in names:
            span = date_span(row.get(name), kind=kind, basis=f"result.{name}", now=now)
            if span is not None:
                spans.append(span)
    span = url_date(row.get("url") or row.get("link"))
    if span is not None:
        spans.append(span)
    return spans


_JSONLD_DATE_RE = re.compile(r'"date(Published|Modified|Created)"\s*:\s*"([^"]{4,40})"')
_META_DATE_RE = re.compile(
    r"(article:published_time|article:modified_time|og:updated_time|og:published_time"
    r"|published_time|modified_time)[\"']?\s*(?:content\s*=\s*|[:=]\s*)[\"']?([0-9][^\"'<>\n]{5,38})", re.I)
_HEADER_DATE_RE = re.compile(
    r"^[ \t>*_#-]*(published time|published on|published|date published|posted on|posted|date"
    r"|updated on|updated|last updated|last modified|modified|发布时间|发布日期|更新时间)"
    r"[ \t*_]*[:：][ \t]*(.{4,60})$", re.I | re.M)
_BYLINE_DATE_RE = re.compile(
    r"\b(published|updated|posted)\s+(?:on\s+)?(" + _MONTH_RE + r"\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}"
    r"|\d{1,2}\s+" + _MONTH_RE + r"\.?,?\s+\d{4}|\d{4}-\d{2}-\d{2})", re.I)
_PAGE_HEAD_CHARS = 3000
_MODIFIED_LABEL_RE = re.compile(r"updat|modif|更新", re.I)


def page_dates(text: Any, *, now: datetime | None = None) -> list[DateSpan]:
    """Dates a fetched page states about itself: JSON-LD, meta tags, reader
    headers ("Published Time: …") and labelled bylines near the top.  Dates in
    the article body are never read (they are about events, not the page)."""
    page = str(text or "")
    spans: list[DateSpan] = []
    for match in _JSONLD_DATE_RE.finditer(page[:200_000]):
        kind = "modified" if match.group(1) == "Modified" else "published"
        span = date_span(match.group(2), kind=kind, basis=f"page:jsonld.date{match.group(1)}", now=now)
        if span is not None:
            spans.append(span)
    for match in _META_DATE_RE.finditer(page[:200_000]):
        kind = "modified" if _MODIFIED_LABEL_RE.search(match.group(1)) else "published"
        span = date_span(match.group(2).strip(), kind=kind, basis=f"page:meta.{match.group(1).lower()}", now=now)
        if span is not None:
            spans.append(span)
    head = page[:_PAGE_HEAD_CHARS]
    for match in _HEADER_DATE_RE.finditer(head):
        label = match.group(1).lower()
        kind = "modified" if _MODIFIED_LABEL_RE.search(label) else "published"
        span = date_span(match.group(2).strip(" *_"), kind=kind, basis=f"page:header.{label}", now=now)
        if span is not None:
            spans.append(span)
    for match in _BYLINE_DATE_RE.finditer(head):
        kind = "modified" if match.group(1).lower() == "updated" else "published"
        span = date_span(match.group(2), kind=kind, basis=f"page:byline.{match.group(1).lower()}", now=now)
        if span is not None:
            spans.append(span)
    return spans


def verdict(spans: Iterable[DateSpan], policy: BacktestPolicy) -> tuple[str, DateSpan | None]:
    """``(before|after|undated, the deciding span)`` for the dates known about a source.

    An archive capture, when present, decides alone: its content was recorded
    at that instant.  Otherwise any date starting after the cutoff makes the
    source ``after``; it is ``before`` only when every known date ends by the
    cutoff; anything else (no date, a straddling month or year) is ``undated``.
    """
    spans = list(spans)
    cutoff = policy.as_of
    captured = [span for span in spans if span.kind == "captured"]
    if captured:
        span = captured[0]
        return ("before" if span.end <= cutoff else "after"), span
    if not spans:
        return "undated", None
    late = [span for span in spans if span.start > cutoff]
    if late:
        return "after", max(late, key=lambda span: span.start)
    if all(span.end <= cutoff for span in spans):
        return "before", max(spans, key=lambda span: span.end)
    return "undated", next(span for span in spans if span.end > cutoff)


def admits(decision: str, policy: BacktestPolicy) -> bool:
    """Whether a source with this verdict may reach the model."""
    return decision == "before" or (decision == "undated" and not policy.strict)


# =============================================================== audit

_AUDIT_LOCK = threading.Lock()


def record(policy: BacktestPolicy | None, event: Mapping[str, Any]) -> None:
    """Append one decision to the policy's audit file (JSON lines); never raises."""
    if policy is None or not policy.audit_path:
        return
    line = {"at": _utcnow().isoformat(timespec="seconds"), "as_of": policy.as_of_iso,
            "strict": policy.strict, **dict(event)}
    try:
        encoded = json.dumps(line, ensure_ascii=False, sort_keys=True, default=str)
        with _AUDIT_LOCK:
            os.makedirs(os.path.dirname(policy.audit_path) or ".", exist_ok=True)
            with open(policy.audit_path, "a", encoding="utf-8") as stream:
                stream.write(encoded + "\n")
    except (OSError, TypeError, ValueError):
        pass


def summarize_audit(path: str | os.PathLike[str]) -> dict:
    """Counts by ``kind`` → ``action`` / ``verdict`` from an audit file (``{}`` when absent)."""
    summary: dict[str, dict[str, int]] = {}
    try:
        with open(path, encoding="utf-8") as stream:
            for raw in stream:
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                bucket = summary.setdefault(str(event.get("kind") or "other"), {})
                for key in ("action", "verdict"):
                    value = event.get(key)
                    if value:
                        name = f"{key}:{value}"
                        bucket[name] = bucket.get(name, 0) + 1
    except OSError:
        return {}
    return summary


# =============================================================== search

def _verdict_record(spans: Sequence[DateSpan], decision: str, span: DateSpan | None) -> dict:
    return {"verdict": decision,
            "date": span.end.isoformat() if span is not None and span.precision == "day" else
                    (f"{span.start.isoformat()}..{span.end.isoformat()}" if span is not None else None),
            "basis": span.basis if span is not None else None,
            "dates_seen": len(spans)}


def filter_search_rows(rows: Sequence[Any], policy: BacktestPolicy, *, query: str = "",
                       now: datetime | None = None) -> tuple[list[dict], dict]:
    """``(kept rows, counts)``: rows dated after the cutoff dropped, undated rows
    dropped in strict mode; each kept row carries its ``backtest`` verdict."""
    kept: list[dict] = []
    counts = {"kept": 0, "kept_undated": 0, "dropped_after": 0, "dropped_undated": 0}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        spans = result_dates(row, now=now)
        decision, span = verdict(spans, policy)
        detail = _verdict_record(spans, decision, span)
        allowed = admits(decision, policy)
        url = str(row.get("url") or row.get("link") or "")
        record(policy, {"kind": "search", "query": str(query)[:200], "url": url[:500],
                        "action": "kept" if allowed else "dropped", **detail})
        if not allowed:
            counts["dropped_after" if decision == "after" else "dropped_undated"] += 1
            continue
        counts["kept"] += 1
        if decision == "undated":
            counts["kept_undated"] += 1
        kept.append({**row, "backtest": detail})
    return kept, counts


def filter_search_payload(raw: Any, policy: BacktestPolicy, *, query: str = "",
                          now: datetime | None = None) -> Any:
    """The search tool's JSON text (or list/dict payload) with the cutoff applied.

    A ``{"results": [...]}`` object keeps its shape (plus a ``backtest`` block);
    a bare list stays a list; error envelopes and unparsable text pass through
    unchanged (they carry no evidence).  Returns the same type it was given."""
    as_text = isinstance(raw, str)
    try:
        payload = json.loads(raw) if as_text else raw
    except ValueError:
        return raw
    if isinstance(payload, list):
        kept, _ = filter_search_rows(payload, policy, query=query, now=now)
        return json.dumps(kept, ensure_ascii=False) if as_text else kept
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return raw
    kept, counts = filter_search_rows(payload["results"], policy, query=query, now=now)
    out = dict(payload)
    out["results"] = kept
    if "total_results" in out:
        out["total_results"] = len(kept)
    out["backtest"] = {"as_of": policy.as_of_iso, "strict": policy.strict, **counts}
    return json.dumps(out, ensure_ascii=False) if as_text else out


def firecrawl_tbs(policy: BacktestPolicy) -> str:
    """Firecrawl/Google custom date range ending on the as-of day."""
    return f"cdr:1,cd_max:{policy.as_of.month}/{policy.as_of.day}/{policy.as_of.year}"


# =============================================================== archive

@dataclass(frozen=True)
class Snapshot:
    timestamp: str      # YYYYMMDDhhmmss (UTC)
    original: str
    url: str            # raw-content snapshot URL

    @property
    def captured(self) -> datetime:
        return datetime.strptime(self.timestamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)

    def span(self) -> DateSpan:
        day = self.captured.date()
        return DateSpan(day, day, "day", "captured", "archive")


def wayback_lookup_url(url: str, policy: BacktestPolicy) -> str:
    """CDX query for the last 200 capture of ``url`` at or before the cutoff."""
    params = {"url": url, "output": "json", "to": policy.cutoff.strftime("%Y%m%d%H%M%S"),
              "filter": "statuscode:200", "limit": "-1", "fastLatest": "true",
              "fl": "timestamp,original,statuscode,mimetype"}
    return WAYBACK_CDX_URL + "?" + urllib.parse.urlencode(params)


def parse_cdx(payload: Any, policy: BacktestPolicy) -> Snapshot | None:
    """The newest admissible capture in a CDX JSON reply (header row first), or ``None``.

    Never trusts the server's ``to`` bound: a capture after the cutoff, a
    non-200 status or a malformed timestamp is ignored."""
    try:
        rows = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
    except ValueError:
        return None
    if not isinstance(rows, list) or len(rows) < 2 or not isinstance(rows[0], list):
        return None
    header = [str(name) for name in rows[0]]
    if "timestamp" not in header or "original" not in header:
        return None
    best: Snapshot | None = None
    for row in rows[1:]:
        if not isinstance(row, list) or len(row) != len(header):
            continue
        item = dict(zip(header, (str(value) for value in row)))
        stamp = item.get("timestamp", "")
        if not re.fullmatch(r"\d{14}", stamp) or item.get("statuscode", "200") not in ("200", "-"):
            continue
        try:
            captured = datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if captured > policy.cutoff:
            continue
        original = item.get("original", "")
        if not original.startswith(("http://", "https://")):
            continue
        if best is None or stamp > best.timestamp:
            best = Snapshot(stamp, original, WAYBACK_SNAPSHOT_URL.format(timestamp=stamp, original=original))
    return best


def _http_get_text(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": _HTTP_UA, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — fixed https host
        return response.read(2_000_000).decode("utf-8", errors="replace")


def find_snapshot(url: str, policy: BacktestPolicy, *,
                  http_get: Callable[[str, float], str] | None = None,
                  timeout: float = 15.0) -> Snapshot | None:
    """The last archive capture of ``url`` at or before the cutoff, ``None`` when
    there is none, the archive is off, or the lookup fails (never raises)."""
    if policy.archive != "wayback" or not str(url or "").startswith(("http://", "https://")):
        return None
    try:
        return parse_cdx((http_get or _http_get_text)(wayback_lookup_url(url, policy), timeout), policy)
    except Exception:  # noqa: BLE001 — an unreachable archive means "no capture"
        return None


# =============================================================== official data

def period_end(period: str, frequency: str) -> date | None:
    """Last day of the period an observation dated ``period`` covers.

    Observations are dated by their period start (monthly ``2024-10-01`` is
    October), except weekly and daily ones, which are dated by the day itself.
    An unknown frequency is read as annual (the latest possible end)."""
    try:
        start = date.fromisoformat(str(period)[:10])
    except ValueError:
        return None
    code = str(frequency or "").upper()[:1]
    if code in ("D", "W"):
        return start
    if code == "M":
        return _month_end(start)
    if code == "Q":
        return _month_end(date(start.year, ((start.month - 1) // 3) * 3 + 3, 1))
    return date(start.year, 12, 31)


def observation_admitted(period: str, frequency: str, policy: BacktestPolicy, *, vintage: bool,
                         end: Any = None) -> bool:
    """Whether an observation could be known at the cutoff.

    A value from an as-of vintage (FRED/ALFRED ``vintage_dates``) was published
    by then, so its period only has to have started.  A current-revision value
    needs its period to have ended by the cutoff, and in strict mode a
    publication lag (``RELEASE_LAG_DAYS``) before it.  ``end`` is the
    provider's own period end when it has one (fiscal years)."""
    try:
        start = date.fromisoformat(str(period)[:10])
    except ValueError:
        return False
    if vintage:
        return start <= policy.as_of
    try:
        end = date.fromisoformat(str(end)[:10]) if end else period_end(period, frequency)
    except ValueError:
        end = period_end(period, frequency)
    if end is None:
        return False
    lag = RELEASE_LAG_DAYS.get(str(frequency or "").upper()[:1], RELEASE_LAG_DAYS["A"]) if policy.strict else 0
    return end + timedelta(days=lag) <= policy.as_of


# =============================================================== markets

def _instant(value: Any) -> datetime | None:
    """A timestamp field of a market (ISO or ``2024-11-06 15:17:41+00``) as UTC."""
    text = str(value or "").strip()
    if not text:
        return None
    candidate = text.replace(" ", "T", 1)
    if re.search(r"[+-]\d{2}$", candidate):
        candidate += ":00"
    try:
        stamp = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        parsed = parse_date(text)
        if parsed is None:
            return None
        return datetime.combine(parsed[0], dtime(0, 0), tzinfo=timezone.utc)
    return stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=timezone.utc)


def market_open_at_cutoff(raw: Mapping[str, Any], policy: BacktestPolicy) -> tuple[bool, str]:
    """``(eligible, reason)``: the market had started and had not closed by the cutoff."""
    opened = _instant(raw.get("startDate")) or _instant(raw.get("createdAt"))
    if opened is None:
        return False, "undated_market"
    if opened > policy.cutoff:
        return False, "opened_after_cutoff"
    closed = _instant(raw.get("closedTime"))
    if closed is not None and closed <= policy.cutoff:
        return False, "closed_before_cutoff"
    return True, "open_at_cutoff"


def price_at_cutoff(history: Iterable[Mapping[str, Any]], policy: BacktestPolicy) -> tuple[float, int] | None:
    """``(price, t)`` of the last history point at or before the cutoff and at
    most ``MARKET_PRICE_MAX_AGE_S`` older; ``None`` when there is none or it is
    not strictly inside (0, 1)."""
    best: tuple[float, int] | None = None
    floor = policy.cutoff_ts - MARKET_PRICE_MAX_AGE_S
    for point in history or []:
        if not isinstance(point, Mapping):
            continue
        try:
            stamp, price = int(float(point.get("t") or "nan")), float(point.get("p") or "nan")
        except (TypeError, ValueError, OverflowError):
            continue
        if price != price or not floor <= stamp <= policy.cutoff_ts:
            continue
        if best is None or stamp > best[1]:
            best = (price, stamp)
    if best is None or not 0.0 < best[0] < 1.0:
        return None
    return best


def price_history_window(policy: BacktestPolicy, days: int) -> dict:
    """CLOB ``prices-history`` parameters for the ``days`` before the cutoff."""
    end = policy.cutoff_ts
    return {"startTs": end - max(1, int(days)) * 86400, "endTs": end}


def _json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def market_tokens(raw: Mapping[str, Any]) -> tuple[list[str], list[str], str]:
    """``(outcome names, CLOB token ids, YES token id or "")``, position-aligned."""
    names = [str(name).strip() for name in _json_list(raw.get("outcomes"))]
    tokens = [str(token).strip() for token in _json_list(raw.get("clobTokenIds")) if str(token).strip()]
    yes_index = next((index for index, name in enumerate(names) if name.lower() == "yes"), None)
    yes = tokens[yes_index] if yes_index is not None and yes_index < len(tokens) else ""
    return names, tokens, yes


def as_of_market_row(raw: Mapping[str, Any], *, price: float, price_ts: int, policy: BacktestPolicy,
                     matched_query: str, event_title: str = "", event_slug: str = "") -> dict:
    """A market row as known at the cutoff, built from an allow-list.

    Never copies the live row: a resolved market's ``outcomePrices`` is the
    answer, and its closed flag, one-day change, bid/ask, liquidity and
    resolution status all postdate the cutoff.  ``volume`` is the market's
    lifetime volume (it includes trading after the cutoff) and is kept only to
    rank and filter noise; ``volume_basis`` says so."""
    names, tokens, yes = market_tokens(raw)
    try:
        volume = float(raw.get("volume") or 0.0)
    except (TypeError, ValueError):
        volume = 0.0
    row: dict[str, Any] = {
        "market_id": str(raw.get("id") or "").strip(),
        "exchange": "polymarket",
        "question": str(raw.get("question") or "").strip(),
        "implied_yes_prob": round(float(price), 4),
        "volume": volume if volume == volume else 0.0,
        "liquidity": 0.0,
        "event_title": event_title or str(raw.get("groupItemTitle") or "").strip(),
        "matched_query": matched_query,
        "price_as_of": datetime.fromtimestamp(price_ts, timezone.utc).isoformat(timespec="seconds"),
        "price_basis": "clob_history_at_cutoff",
        "volume_basis": "lifetime_at_retrieval",
        "backtest_as_of": policy.as_of_iso,
    }
    slug = str(event_slug or "").strip()
    if slug:
        row["url"] = row["event_url"] = f"https://polymarket.com/event/{slug}"
    end_date = str(raw.get("endDate") or "").strip()
    if end_date:
        row["end_date"] = end_date
    if names:
        row["outcomes"] = names
    if tokens:
        row["clob_token_ids"] = tokens
        if yes:
            row["clob_yes_token_id"] = yes
    return row
