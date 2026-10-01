"""Official-data vendor tools: FRED/ALFRED vintage-pinned macro series (TIME-10).

Portions adapted from TradingAgents 0.5.1 tradingagents/dataflows/vendors/fred.py (Apache-2.0),
modified for DRF: the curated alias table with a descriptive phrase rejected
before any API call (:func:`resolve_series`), and both realtime bounds of every
request pinned to ``min(as_of, the vendor's own date in America/Chicago)``
(:func:`fred_pit`).  Everything else here is DRF's own.  Attribution: NOTICE at
the repository root.

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

Environment knobs, read on every call: DATA_TOOLS_CACHE_DIR (default
``<module dir>/.cache/data_cache``), DATA_FRED_CACHE_TTL_H (6),
DATA_TOOL_TIMEOUT_S (20) and DATA_FRED_WINDOW_YEARS (10, clamped to 1-40).
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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
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
    (``fred:<ID>@<vintage>``) and ``url`` its citable address, the vintage part
    of both.  ``model_text`` is what the research agent reads; ``page_text`` the
    rendered value lines registered as the fetched page (empty unless ok);
    ``supports`` self-contained value sentences for citation spans; ``date`` the
    vintage day (ISO); ``provenance`` the request identity (when ok, also the
    UTC instant the vendor answered, ``fetched_at``); ``facts`` structured
    values (``provenance_kind`` ``structured`` for a vendor value, ``derived``
    for a DRF computation); ``detail`` why a lookup did not succeed.
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
             provenance: Optional[Mapping[str, Any]] = None) -> DataResult:
    return DataResult(status=status, key=key, url=url, title="", model_text=f"FRED: {detail}", page_text="",
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
    if not (isinstance(answer, tuple) and len(answer) == 3 and isinstance(answer[0], int)
            and not isinstance(answer[0], bool)):
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
