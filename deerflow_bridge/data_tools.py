"""Official-data vendor tools: FRED/ALFRED vintage-pinned macro series (TIME-10)
and SEC EDGAR company statements as filed on or before as_of (TIME-11).

Portions adapted from TradingAgents 0.5.1 tradingagents/dataflows/vendors/fred.py (Apache-2.0),
modified for DRF: the curated alias table with a descriptive phrase rejected
before any API call (:func:`resolve_series`), and both realtime bounds of every
request pinned to ``min(as_of, the vendor's own date in America/Chicago)``
(:func:`fred_pit`).  Portions adapted from TradingAgents 0.5.1
tradingagents/dataflows/vendors/sec_edgar.py (Apache-2.0), modified for DRF: the
as-filed reading of XBRL company facts (:func:`_as_filed`) and the statement tag
lists (:data:`EDGAR_LINES_US_GAAP`).  Everything else here is DRF's own.
Attribution: NOTICE at the repository root.

Self-contained like the other bridge modules: stdlib only, plus httpx imported
lazily inside the default transport.  It never imports the backend, and no
public function raises to its caller: every failure is a :class:`DataResult`
with a status.  The module is inert until the research engine binds it
(TIME-13); it is deployed beside the other bare-imported bridge modules
(setup.sh and ``pipeline_orchestrator._DEPLOYED_BRIDGE_MODULES``).

The contract of :func:`fred_series`:

* Vintage.  Every request carries ``realtime_start == realtime_end == pit``
  with ``pit <= as_of``; a request that would not is never sent.  The caller
  fixes ``pit`` once per run (``fred_pit(as_of)``), and a historical pit never
  falls back to the latest revisions: a vintage FRED does not hold is
  ``no_vintage``, never a second, unpinned request.  The answer is checked too:
  a response or row stamped with a real-time period that excludes the pin is
  ``no_vintage`` at a historical pin and ``unavailable`` at today's.
* Honesty.  ALFRED's error semantics are unverified against the live API, so
  the mapping is conservative: an HTTP 400 saying the series "does not exist"
  is ``not_found`` at FRED's today and ``no_vintage`` at an earlier pin; any
  other 400, a 429, a 5xx or a transport failure is ``unavailable``.  So is an
  HTTP 200 without the series or observation list: only a list FRED sends
  empty is an absence.
* Rendering.  Deterministic lines whose numbers DRF's page-number parser reads
  in their units ("4.3%", "159,000 thousand persons", "29,000.5 billion USD").
  The header names the source, the series id and the vintage, and so does every
  support sentence.  Year-on-year and change lines are DRF computations from
  the pinned levels and say so ("derived by DRF").
* Secrecy.  The API key goes into the request parameters only: never into a
  result field, URL, cache file or log line.  The default transport redacts
  ``api_key=`` from httpx's request log line and reports an exception by its
  type name alone (the message can echo the request URL).  Vendor text is
  redacted whole before anything cuts it, so no clip leaves part of the key.
* Cache.  Only successful fetches are stored (file name: sha256 of
  ``fred|ID|pit|as_of|window``; atomic writes; an unreadable file is a miss):
  for 30 days when the vintage is before FRED's today (it can no longer
  change), else for DATA_FRED_CACHE_TTL_H hours, read at every lookup.  The
  provenance's ``fetched_at`` says when FRED answered: at today's still-open
  vintage, the values are those published by then.

The contract of :func:`edgar_statements` (SEC EDGAR XBRL company facts):

* As filed.  A value is served only when the filing that reported it was filed
  on or before ``as_of`` (dates parsed with ``date.fromisoformat`` and compared
  as dates; a fact whose dates do not parse is skipped), at the value that
  filing reported: the latest filing on or before ``as_of`` wins, so an
  amendment or a recast counts from its own filing date.  A fact whose period
  ends after its own filing date (a context-date typo) is skipped too, so no
  served period ends after ``as_of``, and so is a balance dated after the
  period its own filing reports (a liquidity or debt note's later "as of"
  date is no statement period).  A post-condition re-checks every served value
  and fails closed (``unavailable``).
* Never derived.  A quarter is a 60-115 day span and a fiscal year a 300-400
  day span reported by an annual-report form; no fourth quarter is computed
  from the annual total and no year-to-date figure is split, so quarterly
  cash-flow lines are served as fiscal years.  Tags are tried in priority
  order and the first (tag, unit) pair reporting a period owns it: values are
  never summed across tags, and each period keeps its own unit.  A table row
  whose values were filed under more than one tag marks the cells of the other
  tags and names every tag, so no change of concept is hidden.
* Identity.  A CIK is used as given; a ticker is resolved through SEC's
  current ticker map, which the result says when ``as_of`` is in the past.
  Either is named by the filer's name in companyfacts, so a filer other than
  the one meant shows.  The User-Agent SEC requires (a name and a contact
  address) is sent with every request and never written into a result, cache
  file or log line.
* Cache.  The ticker map and each company's companyfacts (reduced to the tags
  the statement lines use, which the entry records: an entry reduced to another
  tag set is a miss; each tag's units kept in the filer's order, so a hit
  serves what the fetch did) are cached for DATA_EDGAR_CACHE_TTL_H hours
  whatever ``as_of`` is: facts filed after ``as_of`` are dropped when the
  statement is read, so one fetch serves every date.  When ``as_of`` is not
  before the day SEC answered, the text says when that was: a later filing is
  not in the snapshot.

Environment knobs, read on every call: DATA_TOOLS_CACHE_DIR (default
``<module dir>/.cache/data_cache``), DATA_FRED_CACHE_TTL_H (6),
DATA_EDGAR_CACHE_TTL_H (24), DATA_TOOL_TIMEOUT_S (20) and DATA_FRED_WINDOW_YEARS
(10, clamped to 1-40).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import math
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, fields
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext
from types import MappingProxyType
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

ENGLISH = "English"
CHINESE = "Chinese"

# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

STATUS_OK = "ok"
STATUS_INVALID_INPUT = "invalid_input"
STATUS_NOT_FOUND = "not_found"
STATUS_NO_VINTAGE = "no_vintage"
STATUS_NOT_A_FILER = "not_a_filer"
STATUS_NO_XBRL_FACTS = "no_xbrl_facts"
STATUS_UNAVAILABLE = "unavailable"
STATUSES = frozenset({STATUS_OK, STATUS_INVALID_INPUT, STATUS_NOT_FOUND, STATUS_NO_VINTAGE,
                      STATUS_NOT_A_FILER, STATUS_NO_XBRL_FACTS, STATUS_UNAVAILABLE})


@dataclass(frozen=True)
class DataResult:
    """One data-tool answer.

    ``status`` is one of :data:`STATUSES`.  ``key`` is the item's identity
    (``fred:<ID>@<vintage>``, ``edgar:<CIK>:<freq>@<as_of>``) and ``url`` its
    citable address, the vintage or as-of day part of both.  ``model_text`` is
    what the research agent reads; ``page_text`` the rendered value lines
    registered as the fetched page (empty unless ok); ``supports``
    self-contained value sentences for citation spans; ``date`` the vintage day
    (FRED) or the latest filing date served (EDGAR), ISO; ``provenance`` the
    request identity (when ok, also the UTC instant the vendor answered,
    ``fetched_at``); ``facts`` structured values (``provenance_kind``
    ``structured`` for a vendor value, ``derived`` for a DRF computation);
    ``detail`` why a lookup did not succeed.
    """

    status: str
    key: str
    url: str
    title: str
    model_text: str
    page_text: str
    supports: tuple[str, ...]
    date: Optional[str]
    provenance: Mapping[str, Any]
    facts: tuple[Mapping[str, Any], ...]
    detail: str = ""


def _failure(status: str, detail: str, *, key: str = "", url: str = "",
             provenance: Optional[Mapping[str, Any]] = None, source: str = "FRED") -> DataResult:
    return DataResult(status=status, key=key, url=url, title="", model_text=f"{source}: {detail}", page_text="",
                      supports=(), date=None, provenance=dict(provenance or {}), facts=(), detail=detail)


def _scrub(result: DataResult, secret: str) -> DataResult:
    """``result`` with every occurrence of ``secret`` in its text replaced (defence in depth: nothing
    here writes the key into a result, but vendor text is echoed into ``detail``)."""
    if not secret:
        return result

    def clean(value: Any) -> Any:
        if isinstance(value, str):
            return value.replace(secret, "[redacted]")
        if isinstance(value, tuple):
            return tuple(clean(item) for item in value)
        if isinstance(value, Mapping):
            return {name: clean(item) for name, item in value.items()}
        return value

    return DataResult(**{spec.name: clean(getattr(result, spec.name)) for spec in fields(result)})


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

# (url, params, timeout seconds, headers) -> (HTTP status, parsed JSON or None, body text[:500]).
# Status 0 is a transport failure; its text is then the exception's type name, never its message.
Transport = Callable[[str, Mapping[str, str], float, Mapping[str, str]], tuple[int, Any, str]]

_BODY_CHARS = 500
_SECRET_PARAM_RE = re.compile(r"(?i)\b(api_key=)[^&#\s\"'<>]*")


def _redact_secret_params(text: str) -> str:
    return _SECRET_PARAM_RE.sub(r"\1REDACTED", text)


def _redact_text(text: str, secret: str) -> str:
    """``text`` with every occurrence of ``secret`` and every ``api_key=`` query value redacted.
    Vendor text is redacted whole, before any cut: a cut made first could leave part of the key."""
    if secret:
        text = text.replace(secret, "[redacted]")
    return _redact_secret_params(text) if "api_key=" in text.lower() else text


_KEY_TAIL_MIN = 4  # the shortest trailing key fragment _drop_key_tail removes


def _drop_key_tail(text: str, secret: str) -> str:
    """``text`` without a trailing fragment of ``secret`` (at least four characters): what is left
    of an echoed key when a transport's own length limit cut the body inside it."""
    for size in range(len(secret) - 1, _KEY_TAIL_MIN - 1, -1):
        if text.endswith(secret[:size]):
            return text[:-size] + "[redacted]"
    return text


def _redact_json(value: Any, secret: str) -> Any:
    """A parsed JSON answer with every string in it passed through :func:`_redact_text`."""
    if isinstance(value, str):
        return _redact_text(value, secret)
    if isinstance(value, list):
        return [_redact_json(item, secret) for item in value]
    if isinstance(value, Mapping):
        return {name: _redact_json(item, secret) for name, item in value.items()}
    return value


def _redact_arg(value: Any) -> Any:
    text = str(value)
    return _redact_secret_params(text) if "api_key=" in text.lower() else value


class _RedactSecretParams(logging.Filter):
    """Redacts ``api_key=`` query values from the records of the logger it is attached to: httpx
    logs every request URL, query string included, at INFO."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and "api_key=" in record.msg.lower():
            record.msg = _redact_secret_params(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_arg(arg) for arg in record.args)
        elif isinstance(record.args, Mapping):
            record.args = {name: _redact_arg(arg) for name, arg in record.args.items()}
        return True


_REDACTION_LOCK = threading.Lock()


def _install_httpx_redaction() -> None:
    target = logging.getLogger("httpx")
    with _REDACTION_LOCK:
        if not any(isinstance(item, _RedactSecretParams) for item in target.filters):
            target.addFilter(_RedactSecretParams())


def _well_formed(answer: Any) -> bool:
    """Whether a transport answered ``(HTTP status, payload, text)`` with an int status (a bool is not one)."""
    return (isinstance(answer, tuple) and len(answer) == 3 and isinstance(answer[0], int)
            and not isinstance(answer[0], bool))


def _httpx_transport(url: str, params: Mapping[str, str], timeout: float,
                     headers: Mapping[str, str]) -> tuple[int, Any, str]:
    """The default :data:`Transport`: one httpx GET, redirects not followed."""
    try:
        import httpx

        _install_httpx_redaction()
        response = httpx.get(url, params=dict(params), headers=dict(headers), timeout=timeout)
        # Redacted whole, then cut: a proxy's error page may echo the request URL and its key.
        text = _redact_text(response.text, str(params.get("api_key") or ""))[:_BODY_CHARS]
        try:
            payload = response.json()
        except ValueError:
            payload = None
        return response.status_code, payload, text
    except Exception as exc:  # a transport never raises, and the message may echo the URL and its key
        return 0, None, type(exc).__name__


class _Throttle:
    """Spaces one vendor's requests at least ``min_interval_s`` apart across the process's threads
    (the lock is held while waiting, so concurrent callers queue)."""

    def __init__(self, min_interval_s: float, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.min_interval_s = max(0.0, float(min_interval_s))
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last: Optional[float] = None

    def wait(self) -> None:
        with self._lock:
            if self._last is not None:
                delay = self._last + self.min_interval_s - self._clock()
                if delay > 0:
                    self._sleep(delay)
            self._last = self._clock()


_FRED_THROTTLE = _Throttle(0.5)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

class _DiskCache:
    """A JSON file per key under ``root``, named by the key's sha256.  Only ``status == "ok"``
    payloads are stored, each with its own time to live (``ttl_s`` is the default); a missing,
    truncated, corrupt, expired or future-dated entry is a miss, and so is one older than a read's
    ``max_age_s`` (a TTL lowered since the write takes effect at once).  Writes go to a temporary
    file that replaces the entry atomically, and a failed write only skips caching."""

    def __init__(self, root: str, ttl_s: float, *, clock: Callable[[], float] = time.time) -> None:
        self.root = str(root)
        self.ttl_s = float(ttl_s)
        self._clock = clock

    def path(self, key: str) -> str:
        return os.path.join(self.root, hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json")

    def get(self, key: str, max_age_s: Optional[float] = None) -> Optional[dict]:
        try:
            with open(self.path(key), encoding="utf-8") as handle:
                entry = json.load(handle)
        except (OSError, ValueError):
            return None
        if not isinstance(entry, dict):
            return None
        stored_at, ttl_s, payload = entry.get("stored_at"), entry.get("ttl_s"), entry.get("payload")
        if not (_finite_number(stored_at) and _finite_number(ttl_s) and isinstance(payload, dict)
                and payload.get("status") == STATUS_OK):
            return None
        if max_age_s is not None:
            ttl_s = min(ttl_s, max_age_s)
        age = self._clock() - stored_at
        return payload if 0 <= age < ttl_s else None

    def put(self, key: str, payload: Mapping[str, Any], ttl_s: Optional[float] = None) -> bool:
        ttl = self.ttl_s if ttl_s is None else float(ttl_s)
        if payload.get("status") != STATUS_OK or not ttl > 0:
            return False
        temp_path = None
        try:
            os.makedirs(self.root, exist_ok=True)
            handle, temp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=self.root)
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"stored_at": self._clock(), "ttl_s": ttl, "payload": dict(payload)}, stream,
                          ensure_ascii=False, sort_keys=True)
            os.replace(temp_path, self.path(key))
            return True
        except (OSError, TypeError, ValueError) as exc:
            logger.debug("data_tools: cache write skipped (%s)", type(exc).__name__)
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            return False


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


# ---------------------------------------------------------------------------
# Series ids and the vendor clock
# ---------------------------------------------------------------------------

# Curated aliases -> FRED series ids.  No series whose FRED terms restrict redistribution or
# history (SP500, NASDAQCOM, the ICE BofA BAML indices).  Anything else is passed through as a
# raw id when it looks like one.
MACRO_ALIASES: Mapping[str, str] = MappingProxyType({
    "fed_funds": "FEDFUNDS",
    "fed_funds_rate": "FEDFUNDS",
    "federal_funds_rate": "FEDFUNDS",
    "effective_fed_funds": "DFF",
    "3m_treasury": "DGS3MO",
    "2y_treasury": "DGS2",
    "10y_treasury": "DGS10",
    "10_year_treasury": "DGS10",
    "30y_treasury": "DGS30",
    "yield_curve": "T10Y2Y",
    "10y_2y": "T10Y2Y",
    "cpi": "CPIAUCSL",
    "cpi_nsa": "CPIAUCNS",
    "core_cpi": "CPILFESL",
    "pce": "PCEPI",
    "core_pce": "PCEPILFE",
    "breakeven_5y": "T5YIE",
    "breakeven_10y": "T10YIE",
    "gdp": "GDP",
    "real_gdp": "GDPC1",
    "industrial_production": "INDPRO",
    "unemployment": "UNRATE",
    "payrolls": "PAYEMS",
    "initial_claims": "ICSA",
    "m2": "M2SL",
    "vix": "VIXCLS",
    "dollar_index": "DTWEXBGS",
    "consumer_sentiment": "UMCSENT",
    "housing_starts": "HOUST",
    "retail_sales": "RSAFS",
    "wti": "DCOILWTICO",
    "brent": "DCOILBRENTEU",
    "ecb_deposit_rate": "ECBDFR",
    "usd_cny": "DEXCHUS",
    "eur_usd": "DEXUSEU",
})

# The guidance a rejected or unknown series gets: every alias, and the raw-id form.
_ALIAS_HINT = ("pass an alias (" + ", ".join(sorted(MACRO_ALIASES)) + ") or a raw FRED series id such as "
               "CPIAUCSL")

_SERIES_ID_RE = re.compile(r"[A-Z0-9_]{1,30}")
_ALIAS_SEPARATORS_RE = re.compile(r"[\s\-\u2010-\u2014]+")  # spaces, hyphens and Unicode dashes


def resolve_series(text: Any) -> Optional[str]:
    """The FRED series id ``text`` names: a :data:`MACRO_ALIASES` entry (stripped, lower-cased,
    spaces and dashes read as ``_``: "Fed Funds Rate" is FEDFUNDS), else the upper-cased text when
    it is a plausible raw id (``[A-Z0-9_]{1,30}``), else None.  A descriptive phrase ("bank of
    japan rate") or anything that could smuggle a query parameter ("CPI?&x=1") is None."""
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    alias = _ALIAS_SEPARATORS_RE.sub("_", stripped.lower())
    if alias in MACRO_ALIASES:
        return MACRO_ALIASES[alias]
    candidate = stripped.upper()
    return candidate if _SERIES_ID_RE.fullmatch(candidate) else None


VENDOR_TZ = "America/Chicago"
# Chicago is UTC-6 (CST) or UTC-5 (CDT): UTC minus six hours is never a later calendar date.
_FALLBACK_UTC_OFFSET = _dt.timedelta(hours=6)
_ISO_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_UTC_STAMP_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


def _utc_instant(now: Any) -> _dt.datetime:
    """``now`` in UTC; a naive datetime is local time, Python's own reading (``datetime.now()``
    on a host east of UTC is not read hours late, which would put FRED's today a day ahead).  The
    current instant when ``now`` is not a datetime or cannot be placed in UTC."""
    if isinstance(now, _dt.datetime):
        try:
            return now.astimezone(_dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass
    return _dt.datetime.now(_dt.timezone.utc)


def vendor_today_chicago(now: Optional[_dt.datetime] = None) -> _dt.date:
    """FRED's calendar date (the St. Louis Fed's clock runs on US Central time): FRED rejects a
    realtime date after it.  Without tz data it is the UTC date six hours back, which is never
    later than the true Chicago date."""
    instant = _utc_instant(now)
    try:
        return instant.astimezone(ZoneInfo(VENDOR_TZ)).date()
    except (ZoneInfoNotFoundError, OSError, ValueError, OverflowError):
        pass
    try:
        return (instant - _FALLBACK_UTC_OFFSET).date()
    except OverflowError:  # within six hours of datetime.min: no earlier date exists
        return _dt.date.min


def _as_date(value: Any) -> Optional[_dt.date]:
    """A date from a ``date``, a ``datetime`` (its own calendar date) or a zero-padded
    ``YYYY-MM-DD`` string; None for anything else.  Dates are always compared as date objects: a
    string minimum of "2025-9-30" and "2025-10-01" is the later day."""
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str) and _ISO_DATE_RE.fullmatch(value.strip()):
        try:
            return _dt.date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def fred_pit(as_of: Any, now: Optional[_dt.datetime] = None) -> Optional[_dt.date]:
    """The vintage pin of a run: ``min(as_of, FRED's today)`` on dates, None when ``as_of`` is not a
    date.  A past ``as_of`` passes through; a live run whose UTC date is already tomorrow in
    Chicago is clamped to Chicago's today.  Compute it once per run and pass it to every
    :func:`fred_series` call, so a run that crosses Chicago midnight keeps one vintage."""
    day = _as_date(as_of)
    if day is None:
        return None
    return min(day, vendor_today_chicago(now))


def _years_before(day: _dt.date, years: int) -> _dt.date:
    """``day`` moved back ``years`` calendar years; 29 February becomes the 28th."""
    year = day.year - years
    if year < _dt.MINYEAR:
        return _dt.date.min
    try:
        return day.replace(year=year)
    except ValueError:
        return day.replace(year=year, day=28)


# ---------------------------------------------------------------------------
# Knobs
# ---------------------------------------------------------------------------

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_CLOSED_VINTAGE_TTL_S = 30 * 86400.0


def _env_number(name: str, default: float, *, low: float, high: float) -> float:
    """An env knob clamped to ``[low, high]``; unset, unparseable or non-finite is ``default``."""
    raw = os.environ.get(name, "").strip()
    try:
        value = float(raw) if raw else float(default)
    except ValueError:
        return float(default)
    if not math.isfinite(value):
        return float(default)
    return min(max(value, low), high)


def _cache_root() -> str:
    raw = os.environ.get("DATA_TOOLS_CACHE_DIR", "").strip()
    return os.path.abspath(os.path.expanduser(raw)) if raw else os.path.join(_MODULE_DIR, ".cache", "data_cache")


def _open_vintage_ttl_s() -> float:
    return _env_number("DATA_FRED_CACHE_TTL_H", 6, low=0, high=24 * 30) * 3600.0


def _edgar_ttl_s() -> float:
    """Seconds SEC EDGAR fetches stay cached: DATA_EDGAR_CACHE_TTL_H (24; empty is 24, 0 disables)."""
    return _env_number("DATA_EDGAR_CACHE_TTL_H", 24, low=0, high=24 * 30) * 3600.0


def _timeout_s() -> float:
    return _env_number("DATA_TOOL_TIMEOUT_S", 20, low=1, high=120)


def _window_years(value: Any) -> Optional[int]:
    """The observation window in years, clamped to 1-40: ``value`` when it is a whole number (an
    int, an integral float or a numeric string such as "5", as a tool argument may arrive),
    DATA_FRED_WINDOW_YEARS (default 10) when it is None, and None (invalid input, never a silent
    default) for anything else."""
    if value is None:
        return int(_env_number("DATA_FRED_WINDOW_YEARS", 10, low=1, high=40))
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not (math.isfinite(value) and value.is_integer()):
        return None
    return min(max(int(value), 1), 40)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

MODEL_TEXT_MAX_CHARS = 2600
OBSERVATION_LINES = 24
SUPPORTS_MAX = 40
_TITLE_CHARS = 240
_LABEL_CHARS = 160
_DETAIL_CHARS = 160
_VALUE_RE = re.compile(r"-?[0-9]{1,20}(?:\.[0-9]{1,12})?")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December")
_DERIVED = "derived by DRF from the pinned levels"
_YOY_BASIS = "derived by DRF from the pinned levels; may differ from the publisher's headline basis"
_DERIVED_ZH = "由 DRF 根据锁定版本的水平值推算"
_YOY_BASIS_ZH = "由 DRF 根据锁定版本的水平值推算，可能与发布机构的标题口径不同"


def _clip(text: Any, limit: int = _DETAIL_CHARS) -> str:
    """Vendor text made one bounded line: control characters and runs of whitespace collapse."""
    return " ".join(_CONTROL_RE.sub(" ", str(text or "")).split())[:limit]


@dataclass(frozen=True)
class _UnitStyle:
    """How a value in a series' units is written: ``suffix`` after the number, thousands
    separators when ``group``; ``rate`` marks a percent series, whose changes are in percentage
    points and which has no year-on-year percent change."""

    suffix: str = ""
    group: bool = False
    rate: bool = False


_UNIT_STYLES = {
    "dollars per barrel": _UnitStyle(" USD per barrel"),
    "u.s. dollars to 1 euro": _UnitStyle(" USD per euro"),
    "chinese yuan renminbi to 1 u.s. dollar": _UnitStyle(" CNY per USD"),
    "number": _UnitStyle("", group=True),
}
_SCALED_UNITS_RE = re.compile(r"(thousands|millions|billions|trillions) of ([a-z0-9 .]{1,40})")
_DOLLARS_RE = re.compile(r"\b(?:u\.s\. )?dollars\b")


def _unit_style(units: str) -> _UnitStyle:
    """The :class:`_UnitStyle` of FRED's ``units`` text.  Percent units are written ``4.3%``,
    "Thousands of Persons" ``159,000 thousand persons``, "Billions of Dollars" ``29,000.5 billion
    USD``, "Dollars per Barrel" ``USD per barrel``; index and unrecognised units are bare numbers
    (the header states them)."""
    text = " ".join(units.split()).lower()
    if text.startswith("percent"):
        return _UnitStyle("%", rate=True)
    if text in _UNIT_STYLES:
        return _UNIT_STYLES[text]
    scaled = _SCALED_UNITS_RE.fullmatch(text)
    if scaled:
        noun = _DOLLARS_RE.sub("USD", scaled.group(2))
        return _UnitStyle(f" {scaled.group(1)[:-1]} {noun}", group=True)
    return _UnitStyle()


def _number(value: Decimal, style: _UnitStyle) -> str:
    return format(value, ",f" if style.group else "f")


def _fmt(value: Decimal, style: _UnitStyle) -> str:
    return _number(value, style) + style.suffix


# Derived arithmetic runs in this context.  A value _VALUE_RE admits has at most 32 significant
# digits (20 before the point, 12 after), so a difference is exact here (the default 28-digit
# context would round it) and a percent change, below 10**35, quantizes to hundredths within
# 80 digits (the default context signals InvalidOperation instead).
_ARITHMETIC = Context(prec=80, rounding=ROUND_HALF_EVEN)
_HUNDREDTHS = Decimal("0.01")


def _percent_change(latest: Decimal, base: Decimal) -> Decimal:
    """``(latest - base) / base`` in percent, to two decimals (``base`` is positive)."""
    with localcontext(_ARITHMETIC):
        return ((latest - base) / base * 100).quantize(_HUNDREDTHS)


def _change(latest: Decimal, base: Decimal, style: _UnitStyle) -> str:
    """``latest - base`` with its sign, in percentage points for a rate, else in the series' unit
    followed by the relative change when the base is positive."""
    with localcontext(_ARITHMETIC):  # abs() rounds to the context too
        delta = latest - base
        size = abs(delta)
    sign = "+" if delta > 0 else "-" if delta < 0 else ""
    if style.rate:
        return f"{sign}{_number(size, style)} percentage points"
    text = f"{sign}{_number(size, style)}{style.suffix}"
    if base > 0:
        relative = _percent_change(latest, base)
        text += f" ({'+' if relative > 0 else ''}{relative}%)"
    return text


def _cadence(frequency: str) -> str:
    text = frequency.strip().lower()
    return next((name for name in ("monthly", "quarterly", "annual", "weekly", "daily") if text.startswith(name)), "")


def _period(day: _dt.date, frequency: str, language: str) -> str:
    """The period an observation dated ``day`` covers, as a phrase ("for August 2025", "2025年8月")."""
    cadence = _cadence(frequency)
    chinese = language == CHINESE
    if cadence == "monthly":
        return f"{day.year}年{day.month}月" if chinese else f"for {_MONTHS[day.month - 1]} {day.year}"
    if cadence == "quarterly":
        quarter = (day.month - 1) // 3 + 1
        return f"{day.year}年第{quarter}季度" if chinese else f"for {day.year} Q{quarter}"
    if cadence == "annual":
        return f"{day.year}年" if chinese else f"for {day.year}"
    if cadence == "weekly" and "ending" in frequency.lower():
        return f"截至 {day.isoformat()} 的一周" if chinese else f"for the week ending {day.isoformat()}"
    return day.isoformat() if chinese else f"on {day.isoformat()}"


def _twelve_month_base(points: Sequence[tuple[_dt.date, Decimal]],
                       exact: bool) -> Optional[tuple[_dt.date, Decimal]]:
    """The observation a year before the latest one: the same period for a monthly, quarterly or
    annual series (``exact``), else the last observation at most 14 days before the 12-month mark.
    None when the window holds no such observation."""
    latest_day = points[-1][0]
    target = _years_before(latest_day, 1)
    earlier = [point for point in points[:-1] if point[0] <= target]
    if not earlier:
        return None
    day, value = earlier[-1]
    if exact:
        return (day, value) if day == target else None
    return (day, value) if (target - day).days <= 14 else None


@dataclass(frozen=True)
class _Snapshot:
    """A successful FRED fetch: series metadata, the pinned observations (oldest first) and the UTC
    instant FRED answered (``fetched_at``: at today's still-open vintage, the values are those
    published by then)."""

    series_id: str
    title: str
    units: str
    frequency: str
    seasonal_adjustment: str
    vintage: _dt.date
    observation_start: _dt.date
    observation_end: _dt.date
    points: tuple[tuple[_dt.date, Decimal], ...]
    fetched_at: str

    def to_payload(self) -> dict:
        return {
            "status": STATUS_OK, "vendor": "fred", "series_id": self.series_id, "title": self.title,
            "units": self.units, "frequency": self.frequency, "seasonal_adjustment": self.seasonal_adjustment,
            "vintage": self.vintage.isoformat(), "observation_start": self.observation_start.isoformat(),
            "observation_end": self.observation_end.isoformat(),
            # Fixed-point, as parsed: str() writes 0.0000002 as 2E-7, which from_payload rejects.
            "observations": [[day.isoformat(), format(value, "f")] for day, value in self.points],
            "fetched_at": self.fetched_at,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> Optional["_Snapshot"]:
        """The snapshot a cached payload holds; None when any part of it is malformed (a miss)."""
        try:
            texts = [payload[name] for name in ("series_id", "title", "units", "frequency", "seasonal_adjustment")]
            if not all(isinstance(text, str) for text in texts) or not _SERIES_ID_RE.fullmatch(texts[0]):
                return None
            days = [_as_date(payload[name]) for name in ("vintage", "observation_start", "observation_end")]
            points = []
            for day_text, value_text in payload["observations"]:
                day = _as_date(day_text)
                if day is None or not isinstance(value_text, str) or not _VALUE_RE.fullmatch(value_text):
                    return None
                points.append((day, Decimal(value_text)))
            fetched_at = payload["fetched_at"]
        except (KeyError, TypeError, ValueError, InvalidOperation):
            return None
        if None in days or not points or not (isinstance(fetched_at, str) and _UTC_STAMP_RE.fullmatch(fetched_at)):
            return None
        return cls(*texts, *days, tuple(points), fetched_at)


def alfred_url(series_id: str, vintage: _dt.date) -> str:
    """The citable ALFRED page of ``series_id`` as published on ``vintage`` (one URL per vintage)."""
    return f"https://alfred.stlouisfed.org/series?seid={series_id}&vintage={vintage.isoformat()}"


def _support(snapshot: _Snapshot, language: str, body: str) -> str:
    title, sid, pit = snapshot.title, snapshot.series_id, snapshot.vintage.isoformat()
    if language == CHINESE:
        return f"FRED/ALFRED 数据 {title}（{sid}，{pit} 发布的版本）{body}"
    return f"{title} ({sid}), FRED/ALFRED values as published on {pit}: {body}"


def _render(snapshot: _Snapshot, *, language: str) -> DataResult:
    """The deterministic text, sentences and facts of a successful fetch."""
    sid, pit = snapshot.series_id, snapshot.vintage.isoformat()
    style = _unit_style(snapshot.units)
    points = snapshot.points
    latest_day, latest = points[-1]
    chinese = language == CHINESE
    url = alfred_url(sid, snapshot.vintage)
    adjustment = f" {snapshot.seasonal_adjustment}" if snapshot.seasonal_adjustment else ""
    head = [
        f"FRED/ALFRED: {snapshot.title} ({sid}) — {snapshot.units or 'units not stated'}, "
        f"{snapshot.frequency or 'frequency not stated'}{adjustment}; values as published on {pit}",
        f"Latest: {_fmt(latest, style)} ({latest_day.isoformat()})",
    ]
    period = _period(latest_day, snapshot.frequency, language)
    supports = [_support(snapshot, language, f"{period}的数值为 {_fmt(latest, style)}。" if chinese
                         else f"{_fmt(latest, style)} {period}.")]
    common = {"series_id": sid, "source": "FRED/ALFRED", "vintage": pit, "url": url}
    facts: list[dict] = [{
        **common, "metric": snapshot.title, "value": format(latest, "f"), "unit": snapshot.units,
        "text": _fmt(latest, style), "observation_date": latest_day.isoformat(),
        "value_type": "actual", "provenance_kind": "structured",
    }]
    cadence = _cadence(snapshot.frequency)
    periodic = cadence in ("monthly", "quarterly", "annual")
    base = _twelve_month_base(points, exact=periodic)
    if base is not None and periodic and not style.rate and base[1] > 0:
        yoy = _percent_change(latest, base[1])
        head.append(f"Year-on-year: {yoy}% ({_YOY_BASIS})")
        supports.append(_support(snapshot, language, f"{period}同比变化 {yoy}%（{_YOY_BASIS_ZH}）。" if chinese
                                 else f"year-on-year change {yoy}% {period} ({_YOY_BASIS})."))
        facts.append({
            **common, "metric": f"{snapshot.title}, year-on-year change", "value": str(yoy), "unit": "percent",
            "text": f"{yoy}%", "observation_date": latest_day.isoformat(), "base_date": base[0].isoformat(),
            "value_type": "actual", "provenance_kind": "derived", "basis": _YOY_BASIS,
        })
    for label, label_zh, endpoint in (("Change over 12 months", "近 12 个月变化", base),
                                      ("Change over the window", "窗口期变化", points[0] if len(points) > 1 else None)):
        if endpoint is None:
            continue
        change = _change(latest, endpoint[1], style)
        head.append(f"{label}: {change} from {_fmt(endpoint[1], style)} ({endpoint[0].isoformat()}) "
                    f"to {_fmt(latest, style)} ({latest_day.isoformat()}) ({_DERIVED})")
        if chinese:
            supports.append(_support(snapshot, language, f"{label_zh} {change}：从 {_fmt(endpoint[1], style)}"
                                     f"（{_period(endpoint[0], snapshot.frequency, language)}）到 "
                                     f"{_fmt(latest, style)}（{period}）（{_DERIVED_ZH}）。"))
        else:
            supports.append(_support(snapshot, language, f"{label.lower()} {change}, from {_fmt(endpoint[1], style)} "
                                     f"{_period(endpoint[0], snapshot.frequency, language)} to "
                                     f"{_fmt(latest, style)} {period} ({_DERIVED})."))
    # The most recent observations, oldest dropped first while the agent's text is over its cap;
    # the page holds exactly the lines the agent is shown (the omission note aside).
    shown = list(points[-OBSERVATION_LINES:])
    while shown and len("\n".join([*head, *_observation_lines(shown, style), _OMITTED_NOTE])) > MODEL_TEXT_MAX_CHARS:
        shown.pop(0)
    lines = [*head, *_observation_lines(shown, style)]
    for day, value in reversed(shown[:-1]):
        if len(supports) >= SUPPORTS_MAX:
            break
        when = _period(day, snapshot.frequency, language)
        supports.append(_support(snapshot, language, f"{when}的数值为 {_fmt(value, style)}。" if chinese
                                 else f"{_fmt(value, style)} {when}."))
    model_text = "\n".join([*lines, _OMITTED_NOTE] if len(shown) < len(points) else lines)
    return DataResult(
        status=STATUS_OK, key=f"fred:{sid}@{pit}", url=url, title=f"{snapshot.title} ({sid}), FRED/ALFRED vintage {pit}",
        model_text=model_text[:MODEL_TEXT_MAX_CHARS], page_text="\n".join(lines),
        supports=tuple(supports[:SUPPORTS_MAX]), date=pit, provenance=_provenance(snapshot), facts=tuple(facts))


_OMITTED_NOTE = "Older observations in the window are omitted."


def _observation_lines(points: Sequence[tuple[_dt.date, Decimal]], style: _UnitStyle) -> list[str]:
    return [f"{day.isoformat()}: {_fmt(value, style)}" for day, value in points]


def _provenance(snapshot: _Snapshot) -> dict:
    return {"vendor": "fred", "series_id": snapshot.series_id, "vintage": snapshot.vintage.isoformat(),
            "observation_start": snapshot.observation_start.isoformat(),
            "observation_end": snapshot.observation_end.isoformat(), "units": snapshot.units,
            "frequency": snapshot.frequency, "fetched_at": snapshot.fetched_at}


# ---------------------------------------------------------------------------
# FRED
# ---------------------------------------------------------------------------

FRED_API_BASE = "https://api.stlouisfed.org/fred"
_FRED_KEY_RE = re.compile(r"[a-z0-9]{32}")  # FRED documents its keys as 32 lower-case alphanumerics
_HEADERS = MappingProxyType({"Accept": "application/json"})
_REFUSED = -1  # the transport status of a request refused before sending


def _pinned(params: Mapping[str, str], pit: _dt.date, as_of: _dt.date) -> bool:
    """The vintage invariant of every FRED request: both realtime bounds are the pin and the pin
    is not after ``as_of``."""
    stamp = pit.isoformat()
    return params.get("realtime_start") == stamp and params.get("realtime_end") == stamp and pit <= as_of


def _fred_get(transport: Transport, path: str, params: Mapping[str, str], *, key: str, pit: _dt.date,
              as_of: _dt.date, timeout: float) -> tuple[int, Any, str]:
    """One FRED GET through ``transport``, throttled.  A request that breaks :func:`_pinned` is
    never sent (status :data:`_REFUSED`); a transport that raises or answers malformed is status 0.
    The answer comes back with the key redacted from its body text and from every string of its
    JSON, whole and before any cut, so no later clip can leave part of the key behind (a proxy's
    error page may echo the request URL; a transport's own 500-character cut may leave a tail)."""
    if not _pinned(params, pit, as_of):
        return _REFUSED, None, ""
    _FRED_THROTTLE.wait()
    query = {**params, "api_key": key, "file_type": "json"}
    try:
        answer = transport(f"{FRED_API_BASE}/{path}", query, timeout, dict(_HEADERS))
    except Exception as exc:  # an injected transport may raise; the message may echo the key
        return 0, None, type(exc).__name__
    if not _well_formed(answer):
        return 0, None, "malformed transport answer"
    code, payload, text = answer
    text = _drop_key_tail(_redact_text(str(text or ""), key), key)
    return code, _redact_json(payload, key), text[:_BODY_CHARS]


def _http_failure(code: int, payload: Any, text: str, *, series_id: str, pit: _dt.date,
                  historical: bool) -> Optional[tuple[str, str]]:
    """``(status, detail)`` of a FRED answer that is not a JSON object with HTTP 200, else None."""
    if code == 200 and isinstance(payload, Mapping):
        return None
    if code == _REFUSED:
        return STATUS_UNAVAILABLE, "the request was not pinned to the vintage, so it was not sent"
    if code == 0:
        return STATUS_UNAVAILABLE, f"FRED is unreachable ({_clip(text) or 'transport failure'})"
    if code == 400:
        message = payload.get("error_message") if isinstance(payload, Mapping) else None
        message = message if isinstance(message, str) else text
        if "does not exist" in message.lower():
            if historical:
                return STATUS_NO_VINTAGE, (
                    f"FRED/ALFRED holds no vintage of {series_id} as published on {pit.isoformat()} (the series "
                    "may start later or predate ALFRED's coverage); later revisions are never substituted")
            return STATUS_NOT_FOUND, f"FRED has no series {series_id}; {_ALIAS_HINT}"
        return STATUS_UNAVAILABLE, f"FRED rejected the request (HTTP 400: {_clip(message)})"
    if code == 200:
        return STATUS_UNAVAILABLE, "FRED answered with a body that is not a JSON object"
    return STATUS_UNAVAILABLE, f"FRED answered HTTP {code}"


def _parse_observations(rows: Sequence[Any], *, start: _dt.date,
                        end: _dt.date) -> tuple[tuple[_dt.date, Decimal], ...]:
    """The numeric observations dated within ``[start, end]``, oldest first, one per date (the last
    listed wins).  FRED's missing-value marker ".", blanks and malformed rows are skipped."""
    found: dict[_dt.date, Decimal] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        day, value = _as_date(row.get("date")), row.get("value")
        if day is None or not start <= day <= end or not isinstance(value, str):
            continue
        value = value.strip()
        if _VALUE_RE.fullmatch(value):
            found[day] = Decimal(value)
    return tuple(sorted(found.items()))


def _at_vintage(stamped: Any, pit: _dt.date) -> bool:
    """Whether an answer, or one row of it, agrees with the pin.  FRED stamps each with the
    real-time period it describes (``realtime_start``/``realtime_end``), which must contain
    ``pit``: an answer that ignored the pin and carries later revisions fails here instead of
    being labelled the pinned vintage.  Without either stamp nothing contradicts the pinned
    request; a stamp that is not a date is a contradiction."""
    if not isinstance(stamped, Mapping):
        return True
    start, end = stamped.get("realtime_start"), stamped.get("realtime_end")
    if start is None and end is None:
        return True
    low, high = _as_date(start), _as_date(end)
    return low is not None and high is not None and low <= pit <= high


def _off_vintage(series_id: str, pit: _dt.date, historical: bool) -> tuple[str, str]:
    """``(status, detail)`` of an answer stamped with a real-time period that excludes the pin."""
    if historical:
        return STATUS_NO_VINTAGE, (f"FRED/ALFRED answered {series_id} with values outside the vintage of "
                                   f"{pit.isoformat()}; later revisions are never substituted")
    return STATUS_UNAVAILABLE, f"FRED answered {series_id} with values outside the requested vintage {pit.isoformat()}"


def fred_series(series: Any, *, as_of: Any, pit: Any, key: Any, window_years: Any = None,
                language: str = ENGLISH, transport: Optional[Transport] = None, cache: Optional[_DiskCache] = None,
                now: Optional[_dt.datetime] = None) -> DataResult:
    """One FRED/ALFRED series as published on ``pit`` (see the module docstring for the contract).

    ``as_of`` ends the observation window, which starts ``window_years`` earlier (a whole number,
    clamped to 1-40; None: DATA_FRED_WINDOW_YEARS); ``pit`` is the run's vintage pin
    (:func:`fred_pit`), never after ``as_of`` or FRED's today; ``key`` is the FRED API key.
    ``transport``, ``cache`` and ``now`` (the current instant; a naive datetime is local time) are
    injectable for tests.  Never raises.
    """
    secret = key if isinstance(key, str) and _FRED_KEY_RE.fullmatch(key) else ""
    try:
        result = _fred_series(series, as_of=as_of, pit=pit, key=secret, window_years=window_years,
                              language=language, transport=transport, cache=cache, now=now)
    except Exception as exc:  # the tool layer must never see an exception
        logger.warning("data_tools: FRED lookup failed internally (%s)", type(exc).__name__)
        result = _failure(STATUS_UNAVAILABLE, f"the FRED lookup failed internally ({type(exc).__name__})")
    return _scrub(result, secret)


def _fred_series(series: Any, *, as_of: Any, pit: Any, key: str, window_years: Any, language: str,
                 transport: Optional[Transport], cache: Optional[_DiskCache],
                 now: Optional[_dt.datetime]) -> DataResult:
    series_id = resolve_series(series)
    if series_id is None:
        if isinstance(series, str):
            shown = repr(_clip(_redact_text(series, key), 80))
        else:  # named by its type, never stringified: a container's text could carry the key past the clip
            shown = f"a {_clip(_redact_text(type(series).__name__, key), 40)} value"
        return _failure(STATUS_INVALID_INPUT, f"{shown} is not a FRED series; {_ALIAS_HINT}")
    as_of_day, pit_day = _as_date(as_of), _as_date(pit)
    if as_of_day is None or pit_day is None:
        return _failure(STATUS_INVALID_INPUT, "as_of and the vintage pin must be dates (YYYY-MM-DD)")
    instant = _utc_instant(now)
    today = vendor_today_chicago(instant)
    if pit_day > as_of_day or pit_day > today:
        return _failure(STATUS_INVALID_INPUT, (
            f"the vintage pin {pit_day.isoformat()} is after as_of {as_of_day.isoformat()} or FRED's today "
            f"{today.isoformat()}; pin with fred_pit(as_of)"))
    window = _window_years(window_years)
    if window is None:
        return _failure(STATUS_INVALID_INPUT, "window_years must be a whole number of years (1-40), or None for "
                                              "the DATA_FRED_WINDOW_YEARS default")
    item_key = f"fred:{series_id}@{pit_day.isoformat()}"
    url = alfred_url(series_id, pit_day)
    if not key:
        return _failure(STATUS_UNAVAILABLE, "no valid FRED API key is configured", key=item_key, url=url)
    start = _years_before(as_of_day, window)
    historical = pit_day < today
    provenance = {"vendor": "fred", "series_id": series_id, "vintage": pit_day.isoformat(),
                  "observation_start": start.isoformat(), "observation_end": as_of_day.isoformat()}
    cache = cache if cache is not None else _DiskCache(_cache_root(), _open_vintage_ttl_s())
    cache_key = f"fred|{series_id}|{pit_day.isoformat()}|{as_of_day.isoformat()}|{window}"
    # An open vintage's entry lives at most the current DATA_FRED_CACHE_TTL_H, whatever it was at the write.
    stored = cache.get(cache_key, max_age_s=None if historical else _open_vintage_ttl_s())
    snapshot = _cached_snapshot(stored, series_id=series_id, pit=pit_day, as_of=as_of_day)
    hit = snapshot is not None
    if snapshot is None:
        outcome = _fetch(series_id, key=key, pit=pit_day, as_of=as_of_day, start=start, historical=historical,
                         transport=transport or _httpx_transport,
                         fetched_at=instant.replace(microsecond=0, tzinfo=None).isoformat() + "Z")
        if isinstance(outcome, tuple):
            status, detail = outcome
            logger.debug("data_tools: FRED %s at vintage %s -> %s", series_id, pit_day.isoformat(), status)
            return _failure(status, detail, key=item_key, url=url, provenance=provenance)
        snapshot = outcome
        cache.put(cache_key, snapshot.to_payload(), _CLOSED_VINTAGE_TTL_S if historical else _open_vintage_ttl_s())
    logger.debug("data_tools: FRED %s at vintage %s -> ok (%d observations, cache hit: %s)", series_id,
                 pit_day.isoformat(), len(snapshot.points), hit)
    return _render(snapshot, language=language)


def _cached_snapshot(payload: Any, *, series_id: str, pit: _dt.date, as_of: _dt.date) -> Optional[_Snapshot]:
    """The snapshot a cache hit holds, when it is well-formed and is this series at this vintage
    and window end; else None (a miss)."""
    snapshot = _Snapshot.from_payload(payload) if isinstance(payload, Mapping) else None
    if snapshot is None or (snapshot.series_id, snapshot.vintage, snapshot.observation_end) != (series_id, pit, as_of):
        return None
    return snapshot


def _fetch(series_id: str, *, key: str, pit: _dt.date, as_of: _dt.date, start: _dt.date, historical: bool,
           transport: Transport, fetched_at: str) -> _Snapshot | tuple[str, str]:
    """The series metadata and observations as published on ``pit``: a :class:`_Snapshot`, or the
    ``(status, detail)`` of the first failure.  Nothing is retried, and an answer whose real-time
    stamps exclude the pin fails (:func:`_at_vintage`).  Only a list FRED sends empty is an absence
    (``no_vintage`` or ``not_found``); an answer without the list, or with a series entry that is
    not an object, establishes nothing about FRED's holdings and is ``unavailable``."""
    realtime = {"realtime_start": pit.isoformat(), "realtime_end": pit.isoformat()}
    timeout = _timeout_s()
    code, payload, text = _fred_get(transport, "series", {"series_id": series_id, **realtime}, key=key, pit=pit,
                                    as_of=as_of, timeout=timeout)
    failure = _http_failure(code, payload, text, series_id=series_id, pit=pit, historical=historical)
    if failure:
        return failure
    rows = payload.get("seriess")
    if not isinstance(rows, list):
        return STATUS_UNAVAILABLE, "FRED answered without a series list"
    if not rows:
        if historical:
            return STATUS_NO_VINTAGE, (f"FRED/ALFRED lists no vintage of {series_id} as published on "
                                       f"{pit.isoformat()}; later revisions are never substituted")
        return STATUS_NOT_FOUND, f"FRED has no series {series_id}; {_ALIAS_HINT}"
    info = rows[0]
    if not isinstance(info, Mapping):
        return STATUS_UNAVAILABLE, "FRED answered with a series entry that is not an object"
    if str(info.get("id") or series_id).upper() != series_id:
        return STATUS_UNAVAILABLE, "FRED answered with metadata of another series"
    if not (_at_vintage(payload, pit) and _at_vintage(info, pit)):
        return _off_vintage(series_id, pit, historical)
    code, payload, text = _fred_get(
        transport, "series/observations",
        {"series_id": series_id, **realtime, "observation_start": start.isoformat(),
         "observation_end": as_of.isoformat(), "sort_order": "asc"},
        key=key, pit=pit, as_of=as_of, timeout=timeout)
    failure = _http_failure(code, payload, text, series_id=series_id, pit=pit, historical=historical)
    if failure:
        return failure
    observation_rows = payload.get("observations")
    if not isinstance(observation_rows, list):
        return STATUS_UNAVAILABLE, "FRED answered without an observation list"
    if not (_at_vintage(payload, pit) and all(_at_vintage(row, pit) for row in observation_rows)):
        return _off_vintage(series_id, pit, historical)
    frequency = _clip(info.get("frequency"), 60)
    points = _parse_observations(observation_rows, start=start, end=as_of)
    if not points:
        return STATUS_NOT_FOUND, (
            f"FRED holds no observation of {series_id} ({frequency or 'frequency not stated'}) between "
            f"{start.isoformat()} and {as_of.isoformat()} as published on {pit.isoformat()}")
    return _Snapshot(series_id=series_id, title=_clip(info.get("title"), _TITLE_CHARS) or series_id,
                     units=_clip(info.get("units"), _LABEL_CHARS), frequency=frequency,
                     seasonal_adjustment=_clip(info.get("seasonal_adjustment_short"), 20),
                     vintage=pit, observation_start=start, observation_end=as_of, points=points,
                     fetched_at=fetched_at)


# ---------------------------------------------------------------------------
# SEC EDGAR: company statements as filed
# ---------------------------------------------------------------------------

EDGAR_SOURCE = "SEC EDGAR"
EDGAR_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
EDGAR_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
EDGAR_FREQS = ("annual", "quarterly")
# A fiscal-year column is a period an annual report (or its amendment) covers: a 10-Q balance has no
# span to reject, and some 10-Qs report twelve-month totals that pass the annual span gate.
EDGAR_ANNUAL_FORMS = ("10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A")
# Duration spans in days.  One filing reports the quarter and the year to date under the same end
# date, so a match on the end date alone could read half a year as a quarter.
SPAN_QUARTER = (60, 115)
SPAN_ANNUAL = (300, 400)
EDGAR_ANNUAL_PERIODS = 5
EDGAR_QUARTERLY_PERIODS = 6
EDGAR_UNTAGGED = "not tagged by this filer"
EDGAR_TICKER_NOTE = "Ticker resolved via today's SEC ticker map."
EDGAR_CASH_FLOW_NOTE = "cash-flow statements are filed year-to-date; quarterly cash-flow values are not derived"
EDGAR_UA_REJECTED = "sec_user_agent_rejected"
_EDGAR_RATE_LIMIT_PAGE = "request rate threshold"  # in SEC's 403 page for an address over 10 requests a second
EDGAR_NO_US_GAAP = "us-gaap facts absent (IFRS filers not supported in v1)"
_EDGAR_THROTTLE = _Throttle(0.2)  # SEC's fair-access limit is 10 requests per second
_NO_VALUE = "—"


@dataclass(frozen=True)
class EdgarLine:
    """One statement line: its English and Chinese labels, the us-gaap tags filers use for it (best
    first: filers renamed lines over the years) and its statement (``income``, ``balance`` or
    ``cash_flow``; cash-flow statements are filed year to date)."""

    label: str
    label_zh: str
    tags: tuple[str, ...]
    statement: str


EDGAR_LINES_US_GAAP: tuple[EdgarLine, ...] = (
    EdgarLine("Revenue", "营业收入", ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                                   "SalesRevenueNet"), "income"),
    EdgarLine("Gross profit", "毛利润", ("GrossProfit",), "income"),
    EdgarLine("Operating income", "营业利润", ("OperatingIncomeLoss",), "income"),
    EdgarLine("Net income", "净利润", ("NetIncomeLoss",), "income"),
    EdgarLine("Diluted EPS", "稀释每股收益", ("EarningsPerShareDiluted",), "income"),
    EdgarLine("R&D", "研发费用", ("ResearchAndDevelopmentExpense",), "income"),
    EdgarLine("Total assets", "总资产", ("Assets",), "balance"),
    EdgarLine("Total liabilities", "总负债", ("Liabilities",), "balance"),
    EdgarLine("Stockholders' equity", "股东权益", ("StockholdersEquity",), "balance"),
    EdgarLine("Cash", "现金及现金等价物", ("CashAndCashEquivalentsAtCarryingValue",), "balance"),
    EdgarLine("Long-term debt", "长期债务", ("LongTermDebtNoncurrent", "LongTermDebt"), "balance"),
    EdgarLine("Diluted shares", "稀释加权平均股数", ("WeightedAverageNumberOfDilutedSharesOutstanding",), "income"),
    EdgarLine("Operating cash flow", "经营活动现金流量净额", ("NetCashProvidedByUsedInOperatingActivities",),
              "cash_flow"),
    EdgarLine("Capex", "资本支出", ("PaymentsToAcquirePropertyPlantAndEquipment",
                                  "PaymentsToAcquireProductiveAssets"), "cash_flow"),
)
_EDGAR_TAGS = tuple(dict.fromkeys(tag for line in EDGAR_LINES_US_GAAP for tag in line.tags))
_FACT_FIELDS = ("start", "end", "val", "filed", "form", "accn")  # what the cache keeps of a fact
# A table cell filed under another tag than its row's latest value carries the mark of its tag: one
# mark per other tag of the longest tag list (a test pins that there are enough).
_EDGAR_TAG_MARKS = ("†", "‡")
# What a fallback tag measures beyond its line's label, said wherever a row shows a value of it.
_EDGAR_TAG_NOTES: Mapping[str, str] = MappingProxyType({"LongTermDebt": "includes the current portion"})
_CIK_RE = re.compile(r"[0-9]{10}")
_CIK_INPUT_RE = re.compile(r"[0-9]{1,10}")
_TICKER_RE = re.compile(r"[A-Z0-9.-]{1,10}")
_ACCN_RE = re.compile(r"[0-9]{10}-[0-9]{2}-[0-9]{6}")
_FORM_RE = re.compile(r"[0-9A-Z][0-9A-Z ./-]{0,19}")
_XBRL_UNIT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9/_.-]{0,39}")
_CURRENCY_UNIT_RE = re.compile(r"[A-Z]{3}")
_PER_SHARE_UNIT_RE = re.compile(r"([A-Z]{3})/shares")
_USER_AGENT_MAX_CHARS = 200
# A statement value at or beyond this magnitude, or with more decimal places than this, is malformed,
# not a figure (the largest filers report about 10**13 in their currency, per-share values two to four
# decimals): the fact is skipped like any other malformed fact.  Both bounds keep every table cell
# short, so a one-column table always fits MODEL_TEXT_MAX_CHARS (a test pins the widest case).
_EDGAR_VALUE_LIMIT = Decimal(10) ** 18
_EDGAR_MAX_DECIMALS = 6
_ENTITY_NAME_CHARS = 80  # companyfacts' entityName, kept to name a CIK's filer
_BILLION = Decimal(10) ** 9
_YI = Decimal(10) ** 8  # 亿
_TENTHS = Decimal("0.1")


@dataclass(frozen=True)
class _FiledValue:
    """One statement value as a filing reported it: the number in its own ``unit``, the us-gaap
    ``tag`` it was filed under, the filing (``form``, ``filed`` date, accession ``accn``) and the
    period (``start`` and ``span_days`` are None for an instant such as a balance)."""

    val: Decimal
    unit: str
    tag: str
    form: str
    filed: _dt.date
    accn: str
    end: _dt.date
    start: Optional[_dt.date]
    span_days: Optional[int]


def _iso_day(value: Any) -> Optional[_dt.date]:
    """The date ``date.fromisoformat`` reads in a string (surrounding whitespace ignored); None for
    anything else.  EDGAR dates are only ever compared as dates: as strings, " 2024-11-01" sorts
    before "2024-10-15"."""
    if not isinstance(value, str):
        return None
    try:
        return _dt.date.fromisoformat(value.strip())
    except ValueError:
        return None


def _fact_value(value: Any) -> Optional[Decimal]:
    """A fact's number exactly (a float by its shortest repr), or None when it is not a finite JSON
    number below :data:`_EDGAR_VALUE_LIMIT` with at most :data:`_EDGAR_MAX_DECIMALS` decimal places
    (``1e-200`` would print as a 200-digit cell)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    number = Decimal(value) if isinstance(value, int) else Decimal(repr(value))
    if abs(number) >= _EDGAR_VALUE_LIMIT or number.normalize(_ARITHMETIC).as_tuple().exponent < -_EDGAR_MAX_DECIMALS:
        return None
    return number


def _parse_fact(row: Any, tag: str, unit: str) -> Optional[_FiledValue]:
    """One companyfacts row as a :class:`_FiledValue`; None when any part of it is malformed: a date
    that does not parse, a period that ends after the filing reporting it (a context-date typo: a
    period is filed as an actual only once it has ended, so with ``filed <= as_of`` no served
    period ends after ``as_of``), a non-numeric value, a start after the end, or no form or
    accession to say which filing reported it."""
    if not isinstance(row, Mapping):
        return None
    filed, end, value = _iso_day(row.get("filed")), _iso_day(row.get("end")), _fact_value(row.get("val"))
    form, accn = row.get("form"), row.get("accn")
    if filed is None or end is None or value is None or end > filed:
        return None
    if not (isinstance(form, str) and _FORM_RE.fullmatch(form.strip())
            and isinstance(accn, str) and _ACCN_RE.fullmatch(accn.strip())):
        return None
    start = span_days = None
    if "start" in row:
        start = _iso_day(row.get("start"))
        if start is None or start > end:
            return None
        span_days = (end - start).days
    return _FiledValue(val=value, unit=unit, tag=tag, form=form.strip(), filed=filed, accn=accn.strip(), end=end,
                       start=start, span_days=span_days)


def _unit_rows(tag_rows: Sequence[tuple[str, Any]]) -> Iterator[tuple[str, str, Sequence[Any]]]:
    """``(tag, unit, rows)`` of each well-formed unit list, tags in the given order and, within a tag,
    units in the filer's order."""
    for tag, units in tag_rows:
        if not isinstance(units, Mapping):
            continue
        for unit, rows in units.items():
            if isinstance(unit, str) and _XBRL_UNIT_RE.fullmatch(unit) and isinstance(rows, (list, tuple)):
                yield tag, unit, rows


@dataclass(frozen=True)
class _FilingPeriod:
    """The period one filing reports (:func:`_filing_periods`): its ``end`` and the ``boundaries``
    its statements date a balance at."""

    end: _dt.date
    boundaries: frozenset[_dt.date]


def _filing_periods(facts: Mapping[str, Sequence[Sequence[Any]]], as_of: _dt.date) -> dict[str, _FilingPeriod]:
    """{accession: the period that filing reports} over every tag and unit of ``facts`` (as
    :func:`_needed_facts` keeps them), read from the filing's well-formed durations of at least a
    quarter (:data:`SPAN_QUARTER`'s lower bound) filed on or before ``as_of``.  A shorter duration (a
    subsequent-events note's month to date) says nothing, and an accession reporting no such
    duration (a balance-only filing, as TradingAgents' Apple 2008 fixture) has no period.

    The period ends where the latest fiscal-year duration (:data:`SPAN_ANNUAL`) of an annual report
    (:data:`EDGAR_ANNUAL_FORMS`) ends, and in any other filing, or an annual report without one,
    where its latest duration ends: a 10-K filed late can tag "the two months ended" after the year in
    a subsequent-events note, a quarter by its span, and that stub never moves the year's end (so a
    fiscal-year change reported on a 10-K rather than a 10-KT serves its transition period only once
    a later filing presents it).  Its boundaries are the dates its statements date a balance at: each
    duration's end, and the day before each duration's start (XBRL dates a start by its first day),
    where the comparative and opening balances stand."""
    durations: dict[str, list[_FiledValue]] = {}
    for tag, unit, rows in _unit_rows([(tag, dict(pairs)) for tag, pairs in facts.items()]):
        for row in rows:
            fact = _parse_fact(row, tag, unit)
            if (fact is not None and fact.start is not None and fact.span_days is not None
                    and fact.filed <= as_of and fact.span_days >= SPAN_QUARTER[0]):
                durations.setdefault(fact.accn, []).append(fact)
    periods: dict[str, _FilingPeriod] = {}
    for accn, reported in durations.items():
        years = [fact.end for fact in reported
                 if fact.form in EDGAR_ANNUAL_FORMS and SPAN_ANNUAL[0] <= fact.span_days <= SPAN_ANNUAL[1]]
        boundaries = {day for fact in reported for day in (fact.end, fact.start - _dt.timedelta(days=1))}
        periods[accn] = _FilingPeriod(end=max(years or [fact.end for fact in reported]),
                                      boundaries=frozenset(boundaries))
    return periods


def _as_filed(tag_rows: Sequence[tuple[str, Any]], as_of: _dt.date, span: tuple[int, int],
              annual_forms: tuple[str, ...] = EDGAR_ANNUAL_FORMS, *,
              periods: Mapping[str, _FilingPeriod] = MappingProxyType({})) -> dict[_dt.date, _FiledValue]:
    """{period end: value} of one statement line as it stood on ``as_of``, oldest first.

    ``tag_rows`` is ``(tag, {unit: [companyfacts rows]})`` in priority order.  A fact counts only
    when its dates parse and it was filed on or before ``as_of``; a duration (a fact with a start)
    must span ``span`` days (inclusive).  A fact of a filing that reports a period (``periods``,
    :func:`_filing_periods`) must end on or before that period's end, and an instant must stand on one
    of its boundaries: a liquidity, going-concern or debt note tags a balance "as of" a later date, or
    at an issuance date inside the year, and that date is no statement period.  The first (tag, unit)
    pair serving a period end owns it: values are never summed across tags or units, a later pair
    cannot claim the period, and each period keeps its own unit.  With ``annual_forms`` (a fiscal-year
    reading) a period end must be reported by one of those forms, but its value is the latest filing
    of any form on or before ``as_of``, so an amendment or an 8-K/6-K recast counts from its own
    filing date.  Of two filed the same day an amendment (a form ending "/A") wins, then the later
    accession; the first ten digits of an accession name its submitter (the filer or a filing agent),
    so across submitters that order is deterministic, not chronological.  Nothing is derived: no
    fourth quarter, no year-to-date split.
    """
    low, high = span
    served: dict[_dt.date, _FiledValue] = {}
    for tag, unit, rows in _unit_rows(tag_rows):
        latest: dict[_dt.date, _FiledValue] = {}
        covered: set[_dt.date] = set()  # period ends an annual-report form reports (all ends without a gate)
        for row in rows:
            fact = _parse_fact(row, tag, unit)
            if fact is None or fact.filed > as_of or fact.end in served:
                continue
            period = periods.get(fact.accn)
            if period is not None and (fact.end > period.end
                                       or (fact.span_days is None and fact.end not in period.boundaries)):
                continue
            if fact.span_days is not None and not low <= fact.span_days <= high:
                continue
            if not annual_forms or fact.form in annual_forms:
                covered.add(fact.end)
            seen = latest.get(fact.end)
            if seen is None or _filing_order(fact) >= _filing_order(seen):
                latest[fact.end] = fact
        served.update((end, fact) for end, fact in latest.items() if end in covered)
    return dict(sorted(served.items()))


def _filing_order(fact: _FiledValue) -> tuple[_dt.date, bool, str]:
    """The key :func:`_as_filed` keeps a period's latest filing by: filing date, then an amendment
    over the filing it amends, then the accession."""
    return fact.filed, fact.form.endswith("/A"), fact.accn


def _tagged_by(tag_rows: Sequence[tuple[str, Any]], as_of: _dt.date) -> bool:
    """Whether the filer had filed a well-formed fact under one of these tags on or before ``as_of``.
    A line it had not reads "not tagged by this filer": a tag first used later never shows through."""
    return any(fact is not None and fact.filed <= as_of
               for tag, unit, rows in _unit_rows(tag_rows) for fact in (_parse_fact(row, tag, unit) for row in rows))


def _cik_text(value: Any) -> Optional[str]:
    """``value`` (an int, or a string of 1-10 digits) as SEC's zero-padded 10-digit CIK; None for
    anything else, and for 0, which names no filer."""
    if isinstance(value, str) and _CIK_INPUT_RE.fullmatch(value.strip()):
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 10 ** 10:
        return None
    return f"{value:010d}"


def _edgar_identity(company: Any) -> Optional[tuple[str, str]]:
    """``("cik", CIK)`` for 1-10 digits, ``("ticker", TICKER)`` for a ticker (upper-cased; letters,
    digits, "." and "-", at most 10), else None.  Only ASCII input is read: upper-casing turns some
    other characters into ASCII letters ("ﬀ" into "FF", "straße" into "STRASSE"), another filer's
    ticker."""
    if not isinstance(company, str) or not company.isascii():
        return None
    text = company.strip()
    if _CIK_INPUT_RE.fullmatch(text):
        cik = _cik_text(text)
        return ("cik", cik) if cik else None
    ticker = text.upper()
    return ("ticker", ticker) if _TICKER_RE.fullmatch(ticker) else None


def _user_agent_header(value: Any) -> Optional[str]:
    """The User-Agent SEC requires, stripped: printable ASCII naming a contact address (it contains
    "@"), at most :data:`_USER_AGENT_MAX_CHARS` characters; None for anything else."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if "@" not in text or len(text) > _USER_AGENT_MAX_CHARS or not text.isascii() or _CONTROL_RE.search(text):
        return None
    return text


def _edgar_get(transport: Transport, url: str, *, agent: str, timeout: float) -> tuple[int, Any, str]:
    """One SEC GET through ``transport`` with the caller's User-Agent, throttled.  A transport that
    raises or answers malformed is status 0 (an exception by its type name alone)."""
    _EDGAR_THROTTLE.wait()
    try:
        answer = transport(url, {}, timeout, {"User-Agent": agent, "Accept": "application/json"})
    except Exception as exc:  # an injected transport may raise
        return 0, None, type(exc).__name__
    if not _well_formed(answer):
        return 0, None, "malformed transport answer"
    code, payload, text = answer
    return code, payload, str(text or "")[:_BODY_CHARS]


def _edgar_http_failure(code: int, payload: Any, text: str, *, document: str) -> Optional[tuple[str, str]]:
    """``(status, detail)`` of an SEC answer that is not a JSON object with HTTP 200, else None.  SEC
    refuses a request whose User-Agent names no contact with 403, and with 403 too an address over
    its request rate (several DRF processes together can be; its page says so, and the detail then
    says to retry rather than to change a valid User-Agent); anything else (a 429 or 5xx throttle, a
    transport failure) is ``unavailable`` too."""
    if code == 200 and isinstance(payload, Mapping):
        return None
    if code == 403 and _EDGAR_RATE_LIMIT_PAGE in text.lower():
        return STATUS_UNAVAILABLE, (f"SEC EDGAR answered HTTP 403 for {document} with its rate-limit page (Request "
                                    "Rate Threshold Exceeded): retry later")
    if code == 403:
        return STATUS_UNAVAILABLE, EDGAR_UA_REJECTED
    if code == 0:
        return STATUS_UNAVAILABLE, f"SEC EDGAR is unreachable ({_clip(text) or 'transport failure'})"
    if code == 200:
        return STATUS_UNAVAILABLE, f"SEC EDGAR answered {document} with a body that is not a JSON object"
    return STATUS_UNAVAILABLE, f"SEC EDGAR answered HTTP {code} for {document}"


def _parse_ticker_map(payload: Mapping[str, Any]) -> dict[str, str]:
    """{TICKER: CIK} from SEC's company_tickers.json (``{"0": {"cik_str": 320193, "ticker": "AAPL",
    ...}, ...}``); malformed entries (a ticker that is not ASCII among them, as in
    :func:`_edgar_identity`) are skipped and the first entry of a ticker wins."""
    tickers: dict[str, str] = {}
    for entry in payload.values():
        if (not isinstance(entry, Mapping) or not isinstance(entry.get("ticker"), str)
                or not entry["ticker"].isascii()):
            continue
        ticker, cik = entry["ticker"].strip().upper(), _cik_text(entry.get("cik_str"))
        if cik and _TICKER_RE.fullmatch(ticker):
            tickers.setdefault(ticker, cik)
    return tickers


def _ticker_map(*, transport: Transport, cache: _DiskCache, agent: str,
                timeout: float) -> dict[str, str] | tuple[str, str]:
    """SEC's current ticker map ({TICKER: CIK}), cached for DATA_EDGAR_CACHE_TTL_H hours, or the
    ``(status, detail)`` of the failure.  A map without a usable entry establishes nothing."""
    cache_key = "edgar|company_tickers"
    stored = cache.get(cache_key, max_age_s=_edgar_ttl_s())
    if isinstance(stored, Mapping) and stored.get("kind") == "company_tickers":
        tickers = stored.get("tickers")
        if (isinstance(tickers, Mapping) and tickers
                and all(isinstance(cik, str) and _CIK_RE.fullmatch(cik) for cik in tickers.values())):
            return dict(tickers)
    code, payload, text = _edgar_get(transport, EDGAR_TICKERS_URL, agent=agent, timeout=timeout)
    failure = _edgar_http_failure(code, payload, text, document="the ticker map")
    if failure:
        return failure
    tickers = _parse_ticker_map(payload)
    if not tickers:
        return STATUS_UNAVAILABLE, "SEC EDGAR answered the ticker map without a usable entry"
    cache.put(cache_key, {"status": STATUS_OK, "vendor": "sec_edgar", "kind": "company_tickers", "tickers": tickers},
              _edgar_ttl_s())
    return tickers


def _needed_facts(us_gaap: Mapping[str, Any]) -> dict[str, list[list]]:
    """{tag: [[unit, [rows]], ...]} of the tags the statement lines use, units in the filer's order
    and each row reduced to the fields :func:`_parse_fact` reads (validated there, when a statement
    is read).  A tag's units are pairs, not an object: the cache writes JSON with sorted keys, so an
    object of units would come back in alphabetical order and a cache hit could hand a period to
    another unit than the fetch did (the first unit serving a period owns it, :func:`_as_filed`)."""
    kept: dict[str, list[list]] = {}
    for tag in _EDGAR_TAGS:
        entry = us_gaap.get(tag)
        units = entry.get("units") if isinstance(entry, Mapping) else None
        if not isinstance(units, Mapping):
            continue
        kept[tag] = [[unit, [{name: row[name] for name in _FACT_FIELDS if name in row}
                             for row in rows if isinstance(row, Mapping)]]
                     for unit, rows in units.items() if isinstance(unit, str) and isinstance(rows, list)]
    return kept


def _unit_pairs(facts: Any) -> bool:
    """Whether ``facts`` has the shape :func:`_needed_facts` writes (an entry written before units
    were kept in order holds an object per tag)."""
    return isinstance(facts, Mapping) and all(
        isinstance(pairs, list) and all(isinstance(pair, list) and len(pair) == 2 and isinstance(pair[0], str)
                                        and isinstance(pair[1], list) for pair in pairs)
        for pairs in facts.values())


def _entity_name(value: Any) -> str:
    """companyfacts' ``entityName`` as one bounded line ("" when it is not a string).  Idempotent, so
    a cached name reads back as written (a cut can end in a space, which is dropped)."""
    return _clip(value, _ENTITY_NAME_CHARS).rstrip() if isinstance(value, str) else ""


def _company_facts(cik: str, *, transport: Transport, cache: _DiskCache, agent: str, timeout: float,
                   fetched_at: str) -> dict | tuple[str, str]:
    """The company's filing history (``entity_name``, ``us_gaap_present``, ``facts`` as
    :func:`_needed_facts` keeps them and ``fetched_at``, when SEC answered), cached for
    DATA_EDGAR_CACHE_TTL_H hours whatever the as-of date, or the ``(status, detail)`` of the failure.
    A 404 is ``no_xbrl_facts``; an answer without a facts object, or of another CIK, establishes
    nothing and is ``unavailable``.  The snapshot records the tags and fact fields it was reduced to:
    one reduced to another set (an earlier :data:`EDGAR_LINES_US_GAAP`) is a miss, so a line or
    fallback tag added since is never read as untagged, and so is one of another shape."""
    cache_key = f"edgar|companyfacts|{cik}"
    stored = cache.get(cache_key, max_age_s=_edgar_ttl_s())
    if (isinstance(stored, Mapping) and stored.get("kind") == "companyfacts" and stored.get("cik") == cik
            and stored.get("tags") == list(_EDGAR_TAGS) and stored.get("fields") == list(_FACT_FIELDS)
            and _entity_name(stored.get("entity_name")) == stored.get("entity_name")
            and isinstance(stored.get("us_gaap_present"), bool) and _unit_pairs(stored.get("facts"))
            and isinstance(stored.get("fetched_at"), str) and _UTC_STAMP_RE.fullmatch(stored["fetched_at"])):
        return dict(stored)
    code, payload, text = _edgar_get(transport, EDGAR_FACTS_URL.format(cik=cik), agent=agent, timeout=timeout)
    if code == 404:
        return STATUS_NO_XBRL_FACTS, f"SEC EDGAR holds no XBRL company facts for CIK {cik}"
    failure = _edgar_http_failure(code, payload, text, document="companyfacts")
    if failure:
        return failure
    facts = payload.get("facts")
    if not isinstance(facts, Mapping):
        return STATUS_UNAVAILABLE, "SEC EDGAR answered companyfacts without a facts object"
    if payload.get("cik") is not None and _cik_text(payload.get("cik")) != cik:
        return STATUS_UNAVAILABLE, "SEC EDGAR answered with the company facts of another CIK"
    us_gaap = facts.get("us-gaap")
    if us_gaap is not None and not isinstance(us_gaap, Mapping):
        return STATUS_UNAVAILABLE, "SEC EDGAR answered with us-gaap facts that are not an object"
    snapshot = {"status": STATUS_OK, "vendor": "sec_edgar", "kind": "companyfacts", "cik": cik,
                "tags": list(_EDGAR_TAGS), "fields": list(_FACT_FIELDS),
                "entity_name": _entity_name(payload.get("entityName")), "us_gaap_present": bool(us_gaap),
                "facts": _needed_facts(us_gaap or {}), "fetched_at": fetched_at}
    cache.put(cache_key, snapshot, _edgar_ttl_s())
    return snapshot


@dataclass(frozen=True)
class _Section:
    """One statement table: fiscal years (``annual``) or quarters, the ``periods`` most recent of which
    are shown, and per line whether the filer had tagged it by as_of and what it serves (period end
    -> :class:`_FiledValue`)."""

    annual: bool
    periods: int
    lines: tuple[tuple[EdgarLine, bool, Mapping[_dt.date, _FiledValue]], ...]


def _edgar_sections(facts: Mapping[str, Sequence[Sequence[Any]]], as_of: _dt.date, *,
                    quarterly: bool) -> list[_Section]:
    """The statement as it stood on ``as_of`` (``facts`` as :func:`_needed_facts` keeps them): one
    fiscal-year table, or a quarterly table of the income and balance lines plus a fiscal-year table
    of the cash-flow lines (filed year to date: only a first quarter would pass the quarter span, and
    no later quarter is derived)."""
    periods = _filing_periods(facts, as_of)

    def section(lines: Sequence[EdgarLine], annual: bool) -> _Section:
        rows = []
        for line in lines:
            # dict() of the [unit, rows] pairs keeps the filer's unit order.
            tag_rows = [(tag, dict(facts[tag])) for tag in line.tags if tag in facts]
            served = _as_filed(tag_rows, as_of, SPAN_ANNUAL if annual else SPAN_QUARTER,
                               EDGAR_ANNUAL_FORMS if annual else (), periods=periods)
            rows.append((line, _tagged_by(tag_rows, as_of), served))
        return _Section(annual, EDGAR_ANNUAL_PERIODS if annual else EDGAR_QUARTERLY_PERIODS, tuple(rows))

    if not quarterly:
        return [section(EDGAR_LINES_US_GAAP, True)]
    return [section([line for line in EDGAR_LINES_US_GAAP if line.statement != "cash_flow"], False),
            section([line for line in EDGAR_LINES_US_GAAP if line.statement == "cash_flow"], True)]


def _postcondition_breaches(sections: Sequence[_Section], as_of: _dt.date) -> int:
    """How many served values break the as-filed contract (0 when none does): not a filed value of
    the period and line it serves, filed after ``as_of``, of a period ending after its filing (so
    after ``as_of``), or without the form and accession that identify its filing."""
    breaches = 0
    for section in sections:
        for line, _, served in section.lines:
            for end, fact in served.items():
                breaches += not (isinstance(fact, _FiledValue) and fact.end == end and fact.tag in line.tags
                                 and isinstance(fact.filed, _dt.date) and fact.end <= fact.filed <= as_of
                                 and bool(fact.form)
                                 and isinstance(fact.accn, str) and bool(_ACCN_RE.fullmatch(fact.accn)))
    return breaches


def _grouped(value: Decimal) -> str:
    """``value`` in fixed point with thousands separators, trailing zeros dropped ("391,035", "6.08")."""
    with localcontext(_ARITHMETIC):
        value = value.normalize()
    return format(value if value else Decimal(0), ",f")


def _scaled(value: Decimal, exponent: int) -> str:
    """``value / 10**exponent`` exactly, written as :func:`_grouped` writes it."""
    with localcontext(_ARITHMETIC):
        return _grouped(value.scaleb(-exponent))


def _rounded(value: Decimal, exponent: int) -> str:
    """``value / 10**exponent`` to one decimal ("391.0")."""
    with localcontext(_ARITHMETIC):
        return format(value.scaleb(-exponent).quantize(_TENTHS, rounding=ROUND_HALF_UP), ",f")


def _edgar_value_text(value: Decimal, unit: str, language: str) -> str:
    """A value in words DRF's page-number parser reads in its unit: money exactly in millions plus a
    rounded billions (亿) reading ("391,035 million USD (391.0 billion USD)"), a per-share value and
    a share count in their own units ("6.08 USD/shares", "15,408,095,000 shares"), any other unit
    as filed."""
    chinese = language == CHINESE
    per_share = _PER_SHARE_UNIT_RE.fullmatch(unit)
    if _CURRENCY_UNIT_RE.fullmatch(unit):
        name = ("美元" if unit == "USD" else unit) if chinese else unit
        exact = f"{_scaled(value, 6)}百万{name}" if chinese else f"{_scaled(value, 6)} million {name}"
    elif unit == "shares":
        name = "股" if chinese else "shares"
        exact = f"{_grouped(value)} {name}"
    elif per_share and chinese:
        return f"{_grouped(value)} {'美元' if per_share.group(1) == 'USD' else per_share.group(1)}/股"
    else:
        return f"{_grouped(value)} {unit}"
    if chinese:
        return exact + (f"（{_rounded(value, 8)}亿{name}）" if abs(value) >= _YI else "")
    return exact + (f" ({_rounded(value, 9)} billion {name})" if abs(value) >= _BILLION else "")


def _edgar_cell(fact: _FiledValue) -> str:
    """A table cell: USD in millions, bare (the table is headed "USD millions"); any other unit
    written out ("1,000 million EUR", "6.08 USD/shares")."""
    if fact.unit == "USD":
        return _scaled(fact.val, 6)
    if _CURRENCY_UNIT_RE.fullmatch(fact.unit):
        return f"{_scaled(fact.val, 6)} million {fact.unit}"
    return f"{_grouped(fact.val)} {fact.unit}"


def _edgar_period(fact: _FiledValue, annual: bool, language: str) -> str:
    end = fact.end.isoformat()
    if language == CHINESE:
        if annual:
            return f"{end} 财年末" if fact.start is None else f"截至 {end} 的财年"
        return f"{end} 季末" if fact.start is None else f"截至 {end} 的季度"
    if annual:
        return f"at FY end {end}" if fact.start is None else f"FY ending {end}"
    return f"at quarter end {end}" if fact.start is None else f"quarter ending {end}"


def _edgar_sentence(who: str, line: EdgarLine, fact: _FiledValue, annual: bool, language: str) -> str:
    """One served value as a self-contained sentence naming its tag, period, form, filing date and
    accession."""
    value = _edgar_value_text(fact.val, fact.unit, language)
    period = _edgar_period(fact, annual, language)
    if language == CHINESE:
        return (f"{who}：{line.label_zh}（us-gaap:{fact.tag}），{period}，{fact.form} 于 "
                f"{fact.filed.isoformat()} 提交（申报编号 {fact.accn}）：{value}。")
    return (f"{who}: {line.label} (us-gaap:{fact.tag}), {period}, {fact.form} filed {fact.filed.isoformat()} "
            f"(accession {fact.accn}): {value}.")


def _row_tags(line: EdgarLine, served: Mapping[_dt.date, _FiledValue],
              columns: Sequence[_dt.date]) -> tuple[Optional[str], dict[str, str]]:
    """The tag of a row's latest shown value and {other tag: its mark} for each other tag the row's
    shown values were filed under, in the line's priority order; ``(None, {})`` for a row showing no
    value."""
    shown = [served[end].tag for end in columns if end in served]
    if not shown:
        return None, {}
    return shown[0], dict(zip((tag for tag in line.tags if tag != shown[0] and tag in shown), _EDGAR_TAG_MARKS))


def _tag_text(tag: str) -> str:
    """``us-gaap:TAG``, with what the tag measures beyond its line's label when that differs."""
    note = _EDGAR_TAG_NOTES.get(tag)
    return f"us-gaap:{tag} ({note})" if note else f"us-gaap:{tag}"


def _tag_legend(line: EdgarLine, served: Mapping[_dt.date, _FiledValue], columns: Sequence[_dt.date]) -> Optional[str]:
    """The line naming a row's tags when its shown values were filed under more than one tag (a change
    of concept the table must not hide: the other tags' cells carry their marks) or under a tag that
    measures more than the label says; None otherwise."""
    latest, marks = _row_tags(line, served, columns)
    if latest is None or not (marks or latest in _EDGAR_TAG_NOTES):
        return None
    if not marks:
        return f"{line.label}: {_tag_text(latest)}."
    return (f"{line.label} mixes tags: " + "; ".join(f"{mark} = {_tag_text(tag)}" for tag, mark in marks.items())
            + f"; unmarked = {_tag_text(latest)}.")


def _edgar_table(section: _Section, columns: Sequence[_dt.date], as_of: _dt.date) -> list[str]:
    """The section's lines as a pipe table, one column per period end (latest first); a cell filed
    under another tag than its row's latest value carries that tag's mark (:func:`_row_tags`)."""
    if not columns:
        return [f"{line.label}: " + (f"no value filed on or before {as_of.isoformat()}" if tagged else EDGAR_UNTAGGED)
                for line, tagged, _ in section.lines]
    rows = ["| Line | " + " | ".join(end.isoformat() for end in columns) + " |", "|---|" + "---|" * len(columns)]
    for line, tagged, served in section.lines:
        if tagged:
            marks = _row_tags(line, served, columns)[1]
            cells = [_edgar_cell(served[end]) + marks.get(served[end].tag, "") if end in served else _NO_VALUE
                     for end in columns]
        else:
            cells = [EDGAR_UNTAGGED] * len(columns)
        rows.append(f"| {line.label} | " + " | ".join(cells) + " |")
    return rows


def _edgar_model_text(sections: Sequence[_Section], columns: Sequence[Sequence[_dt.date]], *, who: str,
                      as_of: _dt.date, quarterly: bool, ticker_note: bool, latest: _FiledValue,
                      omitted: bool, open_fetch: Optional[str]) -> str:
    """The agent's text; ``open_fetch`` is the ``fetched_at`` of a snapshot that may predate a filing
    made on or before ``as_of`` (None when every such filing was in when SEC answered)."""
    day = as_of.isoformat()
    fetch_note = f"; SEC data as fetched {open_fetch} (a filing made after that is not included)" if open_fetch else ""
    lines = [f"SEC EDGAR as-filed statements: {who}, {'quarterly' if quarterly else 'annual'}, us-gaap XBRL "
             "company facts",
             f"USD millions; facts filed on or before {day}, at the values filed then{fetch_note}"]
    if ticker_note:
        lines.append(EDGAR_TICKER_NOTE)
    for section, section_columns in zip(sections, columns):
        if not section.annual:
            lines.append("Quarters (columns: quarter end dates, latest first):")
        elif quarterly:
            lines.append(f"Cash flow by fiscal year (columns: fiscal-year end dates, latest first): "
                         f"{EDGAR_CASH_FLOW_NOTE}.")
        else:
            lines.append("Fiscal years (columns: fiscal-year end dates, latest first):")
        lines.extend(_edgar_table(section, section_columns, as_of))
    if quarterly:
        lines.append(f"{_NO_VALUE} = no value filed for that period on or before {day}; a fourth quarter or a "
                     "year-to-date difference is never derived.")
    else:
        lines.append(f"{_NO_VALUE} = no fiscal-year value filed for that period on or before {day}.")
    for section, section_columns in zip(sections, columns):
        for line, _, served in section.lines:
            legend = _tag_legend(line, served, section_columns)
            if legend:
                lines.append(legend)
    lines.append(f"Latest filing served: {latest.form} filed {latest.filed.isoformat()} (accession {latest.accn}).")
    if omitted:
        lines.append("Older periods are omitted.")
    return "\n".join(lines)


def _shown_values(sections: Sequence[_Section],
                  columns: Sequence[Sequence[_dt.date]]) -> list[tuple[_Section, EdgarLine, _FiledValue]]:
    """The values in the shown columns, latest period first, then in table and line order."""
    found = []
    for section_index, (section, section_columns) in enumerate(zip(sections, columns)):
        for line_index, (line, _, served) in enumerate(section.lines):
            found.extend(((-end.toordinal(), section_index, line_index), section, line, served[end])
                         for end in section_columns if end in served)
    return [(section, line, fact) for _, section, line, fact in sorted(found, key=lambda item: item[0])]


def _render_edgar(sections: Sequence[_Section], *, who: str, cik: str, as_of: _dt.date, freq: str, key: str,
                  url: str, ticker_note: bool, open_fetch: Optional[str], language: str,
                  provenance: Mapping[str, Any]) -> DataResult:
    """The deterministic table, sentences and facts of an as-filed statement.  The table shows the
    most recent periods of each section; while it is over :data:`MODEL_TEXT_MAX_CHARS` the oldest
    shown period of every section is dropped, and the page holds exactly the values shown."""
    quarterly = freq == "quarterly"
    ends = [sorted({end for _, _, served in section.lines for end in served}, reverse=True) for section in sections]
    cut = 0
    while True:
        columns = [section_ends[:max(1, section.periods - cut)] for section, section_ends in zip(sections, ends)]
        omitted = any(len(shown) < min(section.periods, len(section_ends))
                      for section, shown, section_ends in zip(sections, columns, ends))
        shown_values = _shown_values(sections, columns)
        latest = max((fact for _, _, fact in shown_values), key=lambda fact: (fact.filed, fact.accn))
        model_text = _edgar_model_text(sections, columns, who=who, as_of=as_of, quarterly=quarterly,
                                       ticker_note=ticker_note, latest=latest, omitted=omitted,
                                       open_fetch=open_fetch)
        if len(model_text) <= MODEL_TEXT_MAX_CHARS or all(len(shown) <= 1 for shown in columns):
            break
        cut += 1
    sentences = [_edgar_sentence(who, line, fact, section.annual, language) for section, line, fact in shown_values]
    facts = []
    for section, section_columns in zip(sections, columns):
        for line, _, served in section.lines:
            end = next((end for end in section_columns if end in served), None)
            if end is None:
                continue
            fact = served[end]
            facts.append({
                "source": EDGAR_SOURCE, "cik": cik, "company": who, "metric": line.label,
                "value": format(fact.val, "f"), "unit": fact.unit,
                "text": _edgar_value_text(fact.val, fact.unit, ENGLISH), "observation_date": fact.end.isoformat(),
                "period_start": fact.start.isoformat() if fact.start else None,
                # A balance is a value at the period's end, as its sentence says ("at FY end ...").
                "period": ("fiscal year" if section.annual else "quarter") + (" end" if fact.start is None else ""),
                "tag": f"us-gaap:{fact.tag}",
                "form": fact.form, "filed": fact.filed.isoformat(), "accn": fact.accn, "url": url,
                "value_type": "actual", "provenance_kind": "structured",
            })
    return DataResult(
        status=STATUS_OK, key=key, url=url, title=f"{who} {freq} statements as filed on or before {as_of.isoformat()}, "
                                                  "SEC EDGAR",
        model_text=model_text[:MODEL_TEXT_MAX_CHARS], page_text="\n".join(sentences), supports=tuple(sentences),
        date=latest.filed.isoformat(), provenance={**provenance, "filed": latest.filed.isoformat()}, facts=tuple(facts))


def edgar_statements(company: Any, *, as_of: Any, freq: Any, user_agent: Any, language: str = ENGLISH,
                     transport: Optional[Transport] = None, cache: Optional[_DiskCache] = None,
                     now: Optional[_dt.datetime] = None) -> DataResult:
    """A US SEC filer's statements as filed on or before ``as_of`` (see the module docstring).

    ``company`` is a CIK (1-10 digits) or a ticker resolved through SEC's current ticker map;
    ``as_of`` a date (no default: the caller pins it); ``freq`` ``annual`` (the last five fiscal
    years) or ``quarterly`` (the last six quarters; cash-flow lines by fiscal year); ``user_agent``
    the identification SEC requires (a name and a contact address).  ``transport``, ``cache`` and
    ``now`` (the current instant: it stamps a fresh fetch's ``fetched_at`` and, as a UTC date,
    decides whether the ticker note is due; a naive datetime is local time) are injectable for
    tests.  Never raises.
    """
    try:
        return _edgar_statements(company, as_of=as_of, freq=freq, user_agent=user_agent, language=language,
                                 transport=transport, cache=cache, now=now)
    except Exception as exc:  # the tool layer must never see an exception
        logger.warning("data_tools: SEC EDGAR lookup failed internally (%s)", type(exc).__name__)
        return _failure(STATUS_UNAVAILABLE, f"the SEC EDGAR lookup failed internally ({type(exc).__name__})",
                        source=EDGAR_SOURCE)


def _edgar_statements(company: Any, *, as_of: Any, freq: Any, user_agent: Any, language: str,
                      transport: Optional[Transport], cache: Optional[_DiskCache],
                      now: Optional[_dt.datetime]) -> DataResult:
    agent = _user_agent_header(user_agent)
    if agent is None:
        return _failure(STATUS_INVALID_INPUT, "user_agent must name the caller and a contact address (printable "
                                              "ASCII containing '@'): SEC refuses unidentified requests",
                        source=EDGAR_SOURCE)
    identity = _edgar_identity(company)
    if identity is None:
        shown = repr(_clip(company, 40)) if isinstance(company, str) else f"a {type(company).__name__} value"
        return _failure(STATUS_INVALID_INPUT, f"{shown} is not a CIK (1-10 digits) or a ticker (1-10 letters, "
                                              "digits, '.' or '-')", source=EDGAR_SOURCE)
    as_of_day = _as_date(as_of)
    if as_of_day is None:
        return _failure(STATUS_INVALID_INPUT, "as_of must be a date (YYYY-MM-DD)", source=EDGAR_SOURCE)
    mode = freq.strip().lower() if isinstance(freq, str) else ""
    if mode not in EDGAR_FREQS:
        return _failure(STATUS_INVALID_INPUT, "freq must be 'annual' or 'quarterly'", source=EDGAR_SOURCE)
    instant = _utc_instant(now)
    cache = cache if cache is not None else _DiskCache(_cache_root(), _edgar_ttl_s())
    transport = transport or _httpx_transport
    timeout = _timeout_s()
    kind, value = identity
    provenance: dict[str, Any] = {"vendor": "sec_edgar", "company": value,
                                  "identity_basis": "cik" if kind == "cik" else "sec_current_ticker_map",
                                  "freq": mode, "as_of": as_of_day.isoformat()}
    if kind == "ticker":
        tickers = _ticker_map(transport=transport, cache=cache, agent=agent, timeout=timeout)
        if isinstance(tickers, tuple):
            return _failure(*tickers, provenance=provenance, source=EDGAR_SOURCE)
        # SEC's map writes a share class with a hyphen (BRK-B); BRK.B names the same listing.
        cik = tickers.get(value) or tickers.get(value.replace(".", "-"))
        if cik is None:
            return _failure(STATUS_NOT_A_FILER, (
                f"{value} is not in SEC's current ticker map: not a US SEC filer, or a ticker SEC no longer lists "
                "(pass the company's CIK)"), provenance=provenance, source=EDGAR_SOURCE)
    else:
        cik = value
    provenance["cik"] = cik
    key = f"edgar:{cik}:{mode}@{as_of_day.isoformat()}"
    url = (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
           f"&type={'10-K' if mode == 'annual' else '10-Q'}&dateb={as_of_day.isoformat().replace('-', '')}")
    snapshot = _company_facts(cik, transport=transport, cache=cache, agent=agent, timeout=timeout,
                              fetched_at=instant.replace(microsecond=0, tzinfo=None).isoformat() + "Z")
    if isinstance(snapshot, tuple):
        logger.debug("data_tools: SEC EDGAR CIK %s -> %s", cik, snapshot[0])
        return _failure(*snapshot, key=key, url=url, provenance=provenance, source=EDGAR_SOURCE)
    # The filer's name is what lets the reader notice a filer other than the one meant: a CIK is used
    # as given (a non-US exchange code, say), and a ticker resolves through today's map (reassigned
    # since a past as_of, it names today's holder).
    name = snapshot["entity_name"]
    provenance["entity_name"] = name
    if kind == "ticker":
        who = f"{value} (CIK {cik}, {name})" if name else f"{value} (CIK {cik})"
    else:
        who = f"CIK {cik} ({name})" if name else f"CIK {cik}"
    if not snapshot["us_gaap_present"]:
        return _failure(STATUS_NO_XBRL_FACTS, EDGAR_NO_US_GAAP, key=key, url=url, provenance=provenance,
                        source=EDGAR_SOURCE)
    sections = _edgar_sections(snapshot["facts"], as_of_day, quarterly=mode == "quarterly")
    breaches = _postcondition_breaches(sections, as_of_day)
    if breaches:
        logger.warning("data_tools: SEC EDGAR CIK %s: %d served value(s) broke the as-filed post-condition; "
                       "nothing served", cik, breaches)
        return _failure(STATUS_UNAVAILABLE, "a value to be served was not filed on or before as_of, was of a period "
                                            "ending after its filing or lacked its filing identity, so nothing is "
                                            "served (as-filed post-condition)",
                        key=key, url=url, provenance=provenance, source=EDGAR_SOURCE)
    if not any(served for section in sections for _, _, served in section.lines):
        return _failure(STATUS_NOT_FOUND, f"no {mode} us-gaap statement value of CIK {cik} was filed on or before "
                                          f"{as_of_day.isoformat()}", key=key, url=url, provenance=provenance,
                        source=EDGAR_SOURCE)
    provenance.update(taxonomy="us-gaap", fetched_at=snapshot["fetched_at"])
    # EDGAR dates a statement filing accepted after 17:30 ET the next business day, so a snapshot
    # fetched on a later UTC day than as_of held every filing dated up to as_of; one fetched on or
    # before as_of (a live run's 24-hour cache) may not, and the text says when SEC answered.
    fetched_day = _iso_day(snapshot["fetched_at"][:10])
    open_fetch = snapshot["fetched_at"] if fetched_day is None or as_of_day >= fetched_day else None
    logger.debug("data_tools: SEC EDGAR CIK %s %s as of %s -> ok", cik, mode, as_of_day.isoformat())
    return _render_edgar(sections, who=who, cik=cik, as_of=as_of_day, freq=mode, key=key, url=url,
                         ticker_note=kind == "ticker" and as_of_day < instant.date(), open_fetch=open_fetch,
                         language=language, provenance=provenance)
