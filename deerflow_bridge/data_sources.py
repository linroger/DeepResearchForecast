"""Official quantitative evidence: normalized data, persistence and safe anchors.

Only stdlib and the inert catalog/hub modules are imported. Provider processes
and HTTP start exclusively through an enabled DataSources request. Stored
observations, never model-supplied numbers, are the authority for consumers.
"""
from __future__ import annotations

import atexit
import calendar
import copy
import csv
import hashlib
import io
import json
import logging
import math
import os
import re
import secrets
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    from . import backtest_cutoff
    from . import data_catalog as catalog
    from .data_mcp import McpHub, _source_path, get_hub
except ImportError:  # deployed bridge is also loaded as bare modules
    import backtest_cutoff
    import data_catalog as catalog
    from data_mcp import McpHub, _source_path, get_hub

PROVIDERS = tuple(catalog.PROVIDERS)
logger = logging.getLogger(__name__)
_MAX_BYTES = 2 * 1024 * 1024
_MAX_ROWS = 5000
NORMALIZATION_POLICY_VERSION = 3
# Restores re-render stored pages and require byte equality with the hash-bound
# copy, so display rules apply only to rows fetched under this policy or later;
# rows without provenance.normalization_policy_version (or older) keep the
# original rendering byte for byte.
_DISPLAY_POLICY_VERSION = 3
_WRITE_LOCK = threading.RLock()
_QUOTA_LOCK = threading.RLock()
_SECRET = re.compile(r"(?i)(?:api[_-]?key|token|secret|password|authorization|registrationkey)")
# Environment values scrubbed from provider text: credential-shaped names only, and only values
# that cannot be ordinary data (MAX_TOKENS=20 or IMPLICIT_TOKEN=1 would otherwise corrupt dates).
_CREDENTIAL_NAME = re.compile(r"(?i)(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD)$")
_NOT_CREDENTIALS = frozenset(("true", "false", "none", "null", "yes", "no", "on", "off"))
_MIN_CREDENTIAL_LEN = 8
_CACHE_MAX_AGE_S = 7 * 86400
_CACHE_FILE = re.compile(r"[0-9a-f]{64}\.json")
_MEMORY_MAX = 512
_PRUNED_CACHES: set[str] = set()
_DEFAULT_MAX_SERIES = 24
# Registration keys a provider rejected in this process, as (provider, sha256 of the key): every
# DataSources sharing the process hub then serves that provider keyless (FRED CSV, BLS keyless quota).
_KEY_NAMES = {"fred": "FRED_API_KEY", "bls": "BLS_API_KEY"}
_REJECTED_KEYS: set[tuple[str, str]] = set()
_KEY_LOCK = threading.Lock()
# FRED: native daily windows longer than this can exceed one 5000-row page (7-day series); such
# windows use FRED's own monthly aggregation for older months and native days for the latest ones.
_FRED_DAILY_SPAN_DAYS = 4500
_FRED_RECENT_MONTHS = 24
# A daily history whose first native day comes more than this many days into its first month
# (licensing-truncated FRED series such as SP500 or the ICE spreads start mid-month; FRED's own
# monthly aggregation leaves such a month empty) covers that month only from that day. Weekends
# and holidays never open a month this late.
_LATE_FIRST_DAY_DAYS = 7
_FRED_FALLBACK_CODES = ("rate_limited", "provider_unavailable", "timeout")
# Upper bound (seconds) of the FRED tag lookup that gives an uncatalogued series its geography.
_FRED_TAGS_S = 5.0
# USAspending fiscal years keep rising with late agency reporting for months after they end.
_FISCAL_SETTLE_DAYS = 120
# eia_query rows newest first; a 200-row page of the widest route is ~22 kB, inside the usgov
# server's 40 kB response budget (MAX_RESPONSE_BYTES).
_EIA_PAGE_ROWS = 200
_BEA_ROMAN_QUARTERS = {"I": 1, "II": 2, "III": 3, "IV": 4}


def _credentials(env: Mapping[str, Any]) -> tuple[str, ...]:
    """Secret values to scrub, longest first, from credential-named variables only."""
    values = {str(v).strip() for k, v in env.items()
              if isinstance(k, str) and isinstance(v, str) and _CREDENTIAL_NAME.search(k.strip())}
    kept = (v for v in values if len(v) >= _MIN_CREDENTIAL_LEN and not v.isdigit() and v.lower() not in _NOT_CREDENTIALS)
    return tuple(sorted(kept, key=len, reverse=True))


def _clean(value: Any, limit: int = 400) -> str:
    text = re.sub(r"(?i)The key:\S+", "The key:[redacted]", str(value or ""))
    text = re.sub(r"(?i)((?:api[_-]?key|token|secret|password|authorization|registrationkey)\s*[:=]\s*)[^\s&,;]+", r"\1[redacted]", text)
    return " ".join(text.split())[:limit]


def _url(value: str) -> str:
    try:
        p = urlsplit(value)
        if p.scheme not in ("http", "https") or not p.hostname or "." not in p.hostname or p.username or p.password:
            return ""
        query = urlencode([(k, v) for k, v in parse_qsl(p.query) if not _SECRET.search(k)])
        return urlunsplit((p.scheme, p.netloc, p.path, query, ""))
    except (TypeError, ValueError):
        return ""


def _number(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and value.strip().upper() in ("", ".", "-", "NA", "N/A", "NULL", "NONE", "NAN")):
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean observation is not numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Nonfinite observation")
    return result


def _period(value: Any) -> str:
    """Normalize publisher period labels; reject invented/invalid dates."""
    text = str(value).strip()
    m = re.fullmatch(r"(\d{4})(?:[- ]?Q([1-4])|-?M(\d{2}))", text, re.I)
    if m:
        return date(int(m[1]), (int(m[2]) - 1) * 3 + 1 if m[2] else int(m[3]), 1).isoformat()
    if re.fullmatch(r"\d{4}", text):
        return date(int(text), 1, 1).isoformat()
    if re.fullmatch(r"\d{4}-\d{2}", text):
        return date.fromisoformat(text + "-01").isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise ValueError("Unrecognized observation period")
    return date.fromisoformat(text).isoformat()


def _end_period(value: Any) -> str:
    """Request-window end: a bare year, quarter or month means its last day."""
    text = str(value).strip()
    first = _period(text)
    months = (12 if re.fullmatch(r"\d{4}", text) else 3 if re.fullmatch(r"\d{4}[- ]?Q[1-4]", text, re.I)
              else 1 if re.fullmatch(r"\d{4}-\d{2}|\d{4}-?M\d{2}", text, re.I) else 0)
    return (date.fromisoformat(_shift(first, months)) - timedelta(days=1)).isoformat() if months else first


def _shift(period: str, months: int) -> str:
    d = date.fromisoformat(period)
    n = d.year * 12 + d.month - 1 + months
    year, month = n // 12, n % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1])).isoformat()


def _kiq_ids(values: Iterable[Any]) -> list[str]:
    """Requesting KIQ ids (producer-set): bounded, single-line, first-seen order."""
    return list(dict.fromkeys(_clean(k, 40) for k in values if isinstance(k, str) and k.strip()))[:20]


def parse_series_id(text: str) -> tuple[str, str] | None:
    if not isinstance(text, str) or len(text) > 300:
        return None
    raw = text.strip().strip("`").strip()
    provider, sep, native = raw.partition(":")
    provider = provider.lower()
    if not sep or provider not in PROVIDERS:
        return None
    base, marker, transform = native.partition("#")
    if marker and transform.lower() not in ("yoy", "pct"):
        return None
    if provider in ("fred", "bls"):
        base = base.upper()
        valid = re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,99}", base)
    elif provider in ("bis", "imf"):
        base = base.upper()
        valid = re.fullmatch(r"[A-Z][A-Z0-9_]{0,59}/[A-Z0-9_]+(?:\.[A-Z0-9_]+)+", base)
        if valid:
            flow, key = base.split("/")
            meta = catalog.BIS_FLOWS.get(flow) if provider == "bis" else catalog.imf_flow_info(flow)
            valid = meta and len(key.split(".")) == len(meta["dims"])
    elif provider == "wb":
        base = base.upper()
        valid = re.fullmatch(r"[A-Z0-9_]+/[A-Z0-9]{3}", base) and catalog.wb_database(base.split("/")[0])
    else:
        valid = re.fullmatch(r"[A-Za-z0-9_ /().-]+", base) and ".." not in base
        recipe = catalog.resolve_usgov_recipe(base) if valid else None
        valid = bool(recipe)
        if recipe:
            base = recipe[0] + ("/" + recipe[2] if recipe[2] else "")
    return (provider, base + ("#" + transform.lower() if marker else "")) if valid else None


@dataclass
class Observation:
    date: str
    value: float | None
    flag: str = ""

    def __post_init__(self):
        self.date = _period(self.date)
        self.value = _number(self.value)
        self.flag = _clean(self.flag, 120)


@dataclass
class Series:
    series: str
    provider: str = ""
    provider_name: str = ""
    title: str = ""
    title_zh: str = ""
    units: str = ""
    frequency: str = ""
    seasonal_adjustment: str = ""
    observations: list[Observation] = field(default_factory=list)
    source_url: str = ""
    api_url: str = ""
    retrieved_at: str = ""
    last_updated: str = ""
    transform: str = ""
    projection_from: str = ""
    notes: str = ""
    route: str = ""
    geography: str = ""
    vintage: str = ""
    provenance: dict = field(default_factory=dict)
    kiqs: list[str] = field(default_factory=list)

    def __post_init__(self):
        parsed = parse_series_id(self.series)
        if not parsed or (self.provider and parsed[0] != self.provider):
            raise ValueError("Invalid or mismatched series identity")
        if not isinstance(self.kiqs, (list, tuple)):
            raise ValueError("Series kiqs must be a list of KIQ ids")
        self.kiqs = _kiq_ids(self.kiqs)
        self.provider = parsed[0]
        self.series = ":".join(parsed)
        suffix = parsed[1].partition("#")[2]
        if self.transform and self.transform != suffix:
            raise ValueError("Transform must match canonical series suffix")
        self.transform = suffix
        unique = {}
        for item in self.observations:
            obs = item if isinstance(item, Observation) else Observation(**item)
            if obs.date in unique and unique[obs.date] != obs:
                raise ValueError("Conflicting observations for one period")
            unique[obs.date] = obs
        if len(unique) > _MAX_ROWS:
            raise ValueError("Observation limit exceeded")
        self.observations = sorted(unique.values(), key=lambda o: o.date)
        if not isinstance(self.provenance, dict):
            raise ValueError("Series provenance must be an object")
        if self.provider == "usgov" and self.series.startswith("usgov:sec/"):
            raise ValueError("SEC complete annual/as-of evidence is unavailable from the native handler")
        # Apply current fidelity on every constructor/from_dict path, including
        # older hash-consistent carriers. Byte integrity is not semantic proof.
        lossy = self.provider == "wb" or self.series.split("#")[0] == "usgov:spending/total"
        weo = self.series.startswith(("imf:WEO/", "imf:WEO_"))
        # Feeds that strip status get it from a deterministic rule of the series identity,
        # never from stored flags, and only for rows fetched under the current policy;
        # older carriers keep "unknown" and re-render byte for byte.
        policy = _status_policy(self.series) if _policy_current(self.provenance) else ""
        vintage_year = self.provenance.get("vintage_year")
        retrieved = re.match(r"(\d{4})-\d{2}-\d{2}", str(self.retrieved_at or ""))
        for obs in self.observations:
            raw = obs.flag
            if policy:
                obs.flag = _policy_flag(policy, obs.date, vintage_year, int(retrieved[1]) if retrieved else None)
            elif lossy or weo and not raw:
                obs.flag = "unknown"
            elif self.provider == "bls" and raw == "P":
                obs.flag = "preliminary"
                self.provenance.setdefault("raw_status", {}).setdefault(obs.date, [{"code": "P", "text": "Preliminary (BLS code)"}])
            elif raw:
                obs.flag = _status_flag(raw)
        if lossy:
            self.provenance["fidelity_policy_version"] = NORMALIZATION_POLICY_VERSION
        if policy:
            self.provenance["status_basis"] = _STATUS_BASIS[policy]
        if lossy or policy in ("weo_vintage", "gep_vintage"):
            # Inferred status shows history; it never proves an exact observation for resolution.
            self.provenance["resolution_safe"] = False
        if self.series.split("#")[0] == "usgov:spending/total":
            periods = self.provenance.get("periods")
            if not isinstance(periods, dict):
                raise ValueError("USAspending fiscal period identity is unavailable")
            for obs in self.observations:
                p = periods.get(obs.date)
                if not isinstance(p, dict) or p.get("calendar") != "us_federal_fiscal_year" or p.get("start") != obs.date:
                    raise ValueError("Missing or invalid fiscal period metadata")
                start = date.fromisoformat(obs.date)
                end = date(start.year + 1, 9, 30).isoformat()
                if (start.month, start.day) != (10, 1) or p.get("label") != f"FY{start.year + 1}" or p.get("end") != end:
                    raise ValueError("Fiscal label/start/end disagree")
                if not isinstance(p.get("complete"), bool) or not obs.date <= _period(p.get("covered_start")) <= _period(p.get("covered_end")) <= end:
                    raise ValueError("Fiscal coverage is invalid")
                if p["complete"] and (p["covered_start"] != obs.date or p["covered_end"] != end):
                    raise ValueError("Partial fiscal coverage cannot be marked complete")
            self.provenance["periods"] = {o.date: periods[o.date] for o in self.observations}
        self.source_url, self.api_url = _url(self.source_url), _url(self.api_url)
        for name in ("title", "title_zh", "notes", "units", "provider_name", "geography", "vintage"):
            setattr(self, name, _clean(getattr(self, name)))
        if self.projection_from:
            self.projection_from = _period(self.projection_from)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Series:
        if not isinstance(value, Mapping) or not isinstance(value.get("observations", []), list):
            raise ValueError("Invalid normalized series object")
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: copy.deepcopy(v) for k, v in value.items() if k in allowed})


@dataclass
class SearchHit:
    series: str
    title: str
    units: str
    frequency: str
    coverage: str
    provider: str
    note: str = ""


# Note prefix of a discovered or weak search result whose title shares no concept with the query
# (catalog.shares_concept): listed after every other result, still fetchable.
OFF_CONCEPT_NOTE = "Not matching: its title shares no concept with the query"


def _entry_text(entry: Any) -> str:
    """A catalog entry's title and curated keywords: the words its concept is judged by."""
    return " ".join((entry.title, *entry.keywords))


DATA_ERROR_CODES = ("invalid_input", "invalid_window", "unsupported_transform", "unknown_series", "unknown_recipe",
                    "rate_limited", "quota_exhausted", "key_invalid", "provider_unavailable", "not_found", "timeout",
                    "persistence_failed", "provider_error")
_RETRYABLE_CODES = frozenset(("rate_limited", "timeout", "provider_unavailable"))
_HINTS = {
    "invalid_input": "Check the series ID, dates (YYYY-MM-DD) and max_obs.",
    "invalid_window": "Use a narrower window inside the series coverage.",
    "unsupported_transform": "Request the level series or a supported transform (yoy, pct).",
    "unknown_series": "Find a valid ID with data_search or the official catalog.",
    "unknown_recipe": "Use a usgov recipe listed in the official catalog.",
    "rate_limited": "Retry in a minute and avoid request bursts.",
    "quota_exhausted": "Use another provider or retry after the quota resets.",
    "key_invalid": "Fix or remove the provider API key; keyless access may work.",
    "provider_unavailable": "Retry later or use another source.",
    "not_found": "Check the ID, geography and window, or search for another series.",
    "timeout": "Retry later with a narrower window.",
    "persistence_failed": "Check the run output directory; the data was not stored.",
    "provider_error": "Use another series or source.",
}


@dataclass
class DataError:
    """Agent-facing failure: ``code`` is the stable reason class (DATA_ERROR_CODES)."""
    series: str
    message: str
    retryable: bool = False
    code: str = "provider_error"

    def __post_init__(self):
        self.series = _clean(self.series, 200)
        self.message = _clean(self.message, 300)
        if self.code not in DATA_ERROR_CODES:
            self.code = "provider_error"

    def unavailable_text(self) -> str:
        return f"DATA_UNAVAILABLE[{self.code}]: {self.message}"


class DataFailure(ValueError):
    """Adapter failure with a known reason class; still a ValueError for callers."""

    def __init__(self, message: str, code: str = "provider_error", retryable: bool | None = None):
        super().__init__(message)
        self.code = code if code in DATA_ERROR_CODES else "provider_error"
        self.retryable = self.code in _RETRYABLE_CODES if retryable is None else bool(retryable)


class _DailyOverflow(DataFailure):
    """A native-daily FRED window exceeds one page; it is refetched as server-side months plus
    recent native days."""


class _ToolFailure(ValueError):
    """A provider tool's own error answer. str() is the hub's clipped reason (what every
    caller saw before); ``detail`` keeps the tool's full scrubbed text for adapters that read
    the provider's diagnosis."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.detail = detail


# mcp-bis answers a 404 with its own diagnosis (datamcps/mcp-bis-main diagnoseNoData).
_BIS_EMPTY_RE = re.compile(r"ARE valid\b.{0,200}?genuinely empty result", re.S)
_BIS_LAST_RE = re.compile(r"most recent published observation is (\d{4}(?:-(?:Q[1-4]|S[12]|\d{2})(?:-\d{2})?)?)")
_BIS_NOTE_RE = re.compile(r"BIS's own note on this series: \"(.+?)\"", re.S)
_BIS_NEVER_RE = re.compile(r"never published a series matching key")
_BIS_DIMS_RE = re.compile(r"in order: ([A-Z0-9_]+(?:\.[A-Z0-9_]+)*)")


def _bis_failure(text: str, req: Mapping[str, Any]) -> DataFailure | None:
    """BIS's diagnosis of an empty answer as a classified failure, else None.

    A well-formed key with nothing in the window (a period not yet published, or a
    discontinued series) is not_found, so callers wait for publication; a key BIS never
    published is unknown_series. BIS's series note keeps its first clause, the current
    regime (e.g. 'discontinued as Germany joined the euro area')."""
    if _BIS_EMPTY_RE.search(text):
        last = _BIS_LAST_RE.search(text)
        note = _BIS_NOTE_RE.search(text)
        clause = _clean(re.split(r";\s|\.\s", note[1], maxsplit=1)[0], 160) if note else ""
        return DataFailure(f"BIS publishes this series but has no observations from {req['fetch_start']} to {req['end']}"
                           + (f"; its most recent observation is {last[1]}" if last else "")
                           + (f"; BIS note: {clause}" if clause else ""), "not_found")
    if _BIS_NEVER_RE.search(text):
        dims = _BIS_DIMS_RE.search(text)
        return DataFailure("BIS has never published a series under this key"
                           + (f"; the key's positions are {dims[1]}" if dims else ""), "unknown_series")
    return None


# Ordered: the first matching provider/hub text decides the reason class.
_FAILURE_TEXT = (
    ("rate_limited", re.compile(r"(?i)\b429\b|too many requests|rate.?limit")),
    ("quota_exhausted", re.compile(r"(?i)daily threshold|quota (?:reached|exceeded|exhausted)")),
    ("key_invalid", re.compile(r"(?i)\b40[13]\b|unauthori[sz]ed|forbidden|key(?::\S+)?\s+provided by the user is invalid"
                               r"|(?:invalid|rejected)\s+(?:api\s*)?key|api_key\s+is\s+not\s+registered"
                               r"|\b(?:api[_ ]?)?key\s+(?:is\s+)?(?:invalid|rejected)\b")),
    ("timeout", re.compile(r"(?i)timed?\s*out|deadline exceeded|ETIMEDOUT")),
    # FRED 400 "The series does not exist."; BLS "Series does not exist for Series <id>".
    ("unknown_series", re.compile(r"(?i)series does not exist")),
    ("invalid_window", re.compile(r"(?i)narrow (?:the requested window|start/end)")),
    ("provider_unavailable", re.compile(r"(?i)\b50[0-4]\b|(?:service|server|provider|temporarily) unavailable|^unavailable$"
                                        r"|bad gateway|connection (?:to the server )?(?:was )?(?:lost|reset|refused)|ECONNRESET"
                                        r"|ECONNREFUSED|fetch failed|still starting|circuit open|not ready|automatic restart"
                                        r"|hub (?:loop unavailable|is closed)")),
    ("not_found", re.compile(r"(?i)\b404\b|not found|returned no (?:observations|data)")),
)
_NOT_RETRYABLE_TEXT = re.compile(r"(?i)hub is closed")


def _failure_class(exc: Any) -> tuple[str, bool]:
    """Map an exception (or reason text) to a DATA_ERROR_CODES code and retryability."""
    if isinstance(exc, DataFailure):
        return exc.code, exc.retryable
    if isinstance(exc, TimeoutError):
        return "timeout", True
    status = getattr(exc, "code", None)
    if isinstance(exc, OSError) and isinstance(status, int) and not isinstance(status, bool):
        # urllib HTTPError carries the HTTP status as .code.
        if status == 429:
            return "rate_limited", True
        if status == 404:
            return "not_found", False
        return ("provider_unavailable", True) if status >= 500 else ("provider_error", False)
    if isinstance(exc, OSError):
        return "provider_unavailable", True
    text = str(exc or "")
    for code, pattern in _FAILURE_TEXT:
        if pattern.search(text):
            return code, code in _RETRYABLE_CODES and not _NOT_RETRYABLE_TEXT.search(text)
    return "provider_error", False


def _status_flag(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    kinds = set()
    for token in re.split(r"[;,]", text):
        token = token.strip()
        kinds.add({"a": "observed", "r": "observed", "actual": "observed", "reported": "observed", "revised": "observed",
                   "forecast": "projection", "projected": "projection", "estimated": "estimate", "provisional": "preliminary"}.get(token, token))
    if not kinds <= {"observed", "unknown", "preliminary", "estimate", "projection"}:
        return "unknown"
    return next((k for k in ("unknown", "projection", "estimate", "preliminary", "observed") if k in kinds), "unknown")


_WB_STATUS_POLICIES = {"WB_WDI": "history_only", "IMF_WEO": "weo_vintage", "WB_GEP": "gep_vintage"}
_STATUS_BASIS = {"history_only": "WDI publishes history only", "weo_vintage": "inferred_from_vintage",
                 "gep_vintage": "inferred_from_vintage"}


def _policy_current(provenance: Any) -> bool:
    version = provenance.get("normalization_policy_version") if isinstance(provenance, Mapping) else None
    return isinstance(version, int) and not isinstance(version, bool) and version >= _DISPLAY_POLICY_VERSION


def _status_policy(series_id: str) -> str:
    """Status rule for feeds that strip observation status (fix contract §1.4), by identity:
    the curated entry's status_policy, else the Data360 database or the IMF WEO flow."""
    base = str(series_id or "").partition("#")[0]
    policy = catalog_field(base, "status_policy")
    if policy:
        return policy
    provider, _, native = base.partition(":")
    if provider == "wb":
        return _WB_STATUS_POLICIES.get(catalog.wb_database(native.split("/")[0]) or "", "")
    if provider == "imf":
        meta = catalog.imf_flow_info(native.split("/")[0])
        return "weo_vintage" if meta and meta.get("base_flow") == "WEO" else ""
    return ""


def _aggregation(req: Mapping[str, Any]) -> str:
    """How native daily points become months: the curated entry's (or usgov recipe's)
    aggregation, 'eop' for stocks and policy targets, else 'avg'."""
    method = catalog_field(req["base"], "aggregation")
    if not method and req["provider"] == "usgov":
        recipe = catalog.resolve_usgov_recipe(req["native"])
        method = recipe[1].get("aggregation", "") if recipe else ""
    return method if method in ("avg", "eop") else "avg"


def _min_start(provider: str, sid: str, native: str) -> str:
    """Earliest valid request start: the curated entry's (or usgov recipe's) min_start, else ''."""
    floor = catalog_field(sid, "min_start")
    if not floor and provider == "usgov":
        recipe = catalog.resolve_usgov_recipe(native)
        floor = str(recipe[1].get("min_start") or "") if recipe else ""
    try:
        return _period(floor) if floor else ""
    except ValueError:
        return ""


def _policy_flag(policy: str, period: str, vintage_year: Any, retrieval_year: int | None) -> str:
    """WDI: years before the retrieval year are history. WEO/GEP vintage V: years >= V are
    publisher projections, V-1 an estimate, earlier years history (revisable)."""
    year = int(period[:4])
    if policy == "history_only":
        return "observed" if retrieval_year and year < retrieval_year else "unknown"
    if not isinstance(vintage_year, int) or isinstance(vintage_year, bool) or not 1900 <= vintage_year <= 2100:
        return "unknown"
    return "projection" if year >= vintage_year else "estimate" if year == vintage_year - 1 else "observed"


def _observation_kind(obs: Observation, series: Series) -> str:
    if obs.flag:
        kind = "preliminary" if series.provider == "bls" and obs.flag == "P" else _status_flag(obs.flag)
        if kind == "observed" and series.projection_from and obs.date >= series.projection_from:
            return "unknown"
        return kind
    if series.provider == "wb" or series.series.split("#")[0] == "usgov:spending/total" or series.series.startswith(("imf:WEO/", "imf:WEO_")):
        return "unknown"
    return "projection" if series.projection_from and obs.date >= series.projection_from else "observed"


def _projected(obs: Observation, series: Series) -> bool:
    return _observation_kind(obs, series) == "projection"


def series_stats(series: Series) -> dict:
    obs = series.observations
    # Rows under the current policy also exclude partial periods and future-dated points.
    kind = observation_kind if _display_current(series) else _observation_kind
    finite = [o for o in obs if o.value is not None and kind(o, series) == "observed"]
    def point(o):
        return {"date": o.date, "value": o.value} if o else None
    latest = finite[-1] if finite else None
    prior = next((o for o in finite if latest and series.frequency != "W" and o.date == _shift(latest.date, -12)), None)
    window = [o for o in finite if latest and o.date >= _shift(latest.date, -60)]
    decade = next((o for o in finite if latest and o.date == _shift(latest.date, -120)), None)
    change = latest.value - prior.value if latest and prior else None
    pct = change / abs(prior.value) * 100 if prior and prior.value and change is not None else None
    cagr = None
    if decade and latest and decade.value > 0 and latest.value > 0 and not series.transform and not re.search(r"per\s*cent|rate|%", series.units, re.I):
        cagr = ((latest.value / decade.value) ** 0.1 - 1) * 100
    return {"latest": point(latest), "previous_year": point(prior), "yoy_change": change, "yoy_change_pct": pct,
            "five_year_min": point(min(window, key=lambda o: o.value)) if window else None,
            "five_year_max": point(max(window, key=lambda o: o.value)) if window else None,
            "cagr_10y": cagr, "count": len(obs), "first": obs[0].date if obs else "",
            "last": obs[-1].date if obs else "", "projection_count": sum(kind(o, series) == "projection" for o in obs)}


def _legacy_format_value(value: float | None, units: str = "") -> str:
    """Policy <= 2 value text; kept so stored pages re-render byte for byte."""
    if value is None:
        return "missing"
    n = _number(value)
    if n is None:
        return "missing"
    percent = bool(re.search(r"per\s*cent|%", units, re.I)) and not re.search(r"point", units, re.I)
    text = f"{n:.2f}" if percent else f"{n:.4f}"
    text = text.rstrip("0").rstrip(".")
    if text == "-0":
        text = "0"
    return text + ("%" if percent else "")


def _trim(text: str) -> str:
    text = text.rstrip("0").rstrip(".") if "." in text else text
    return "0" if text in ("-0", "") else text


def is_percent_units(units: str) -> bool:
    """Values are percents (changes are percentage points); 'percentage points' units are not."""
    text = str(units or "")
    return bool(re.search(r"per\s*cent|%", text, re.I)) and not re.search(r"point", text, re.I)


def format_value(value: float | None, units: str = "") -> str:
    """Percent-like units keep up to 3 decimals (3.875%); levels keep up to 4 decimals within
    16 significant digits (debt 40171825101340.31, never binary noise), 4 significant below 1."""
    if value is None:
        return "missing"
    n = _number(value)
    if n is None:
        return "missing"
    if is_percent_units(units):
        return _trim(f"{n:.3f}") + "%"
    if n == 0 or abs(n) >= 1:
        decimals = max(0, min(4, 15 - math.floor(math.log10(abs(n))))) if n else 4
    else:
        decimals = min(12, 3 - math.floor(math.log10(abs(n))))
    return _trim(f"{n:.{decimals}f}")


def _signed(text: str) -> str:
    return text if text.startswith("-") or text.rstrip("% p") == "0" else "+" + text


def format_change(delta: float | None, units: str = "") -> str:
    """Signed change: percentage points for percent-like units (+0.25 pp), else a signed level."""
    if delta is None:
        return "missing"
    n = _number(delta)
    if n is None:
        return "missing"
    if is_percent_units(units):
        return _signed(_trim(f"{n:.3f}") + " pp")
    return _signed(format_value(n, units))


_SCALE_WORD = re.compile(r"(?i)\b(?:thousands?|millions?|billions?|trillions?)\b")
_ZH_UNITS = {"u.s. dollars": "美元", "us dollars": "美元", "u.s. dollar": "美元", "us dollar": "美元", "dollars": "美元"}


def scaled_value(value: float | None, units: str = "", lang: str = "en") -> str:
    """Magnitude companion such as '≈ 40.27 trillion U.S. dollars' (zh '≈40.27万亿美元').

    The scale comes from the value's magnitude only, never from provider
    multipliers; units that already carry a scale word or percents get ''.
    """
    try:
        n = _number(value)
    except (TypeError, ValueError):
        return ""
    text = _clean(units, 80)
    if n is None or abs(n) < 1e9 or is_percent_units(text) or _SCALE_WORD.search(text):
        return ""
    if text.lower() in ("number", "value", "unknown", "units", "count"):
        text = ""
    if str(lang or "").lower().startswith("zh"):
        divisor, word = (1e12, "万亿") if abs(n) >= 1e12 else (1e8, "亿")
        unit = _ZH_UNITS.get(text.lower(), " " + text if text else "")
        return f"≈{_trim(f'{n / divisor:.2f}')}{word}{unit}"
    divisor, word = (1e12, "trillion") if abs(n) >= 1e12 else (1e9, "billion")
    return f"≈ {_trim(f'{n / divisor:.2f}')} {word}" + (" " + text if text else "")


_CATALOG_FIELD_DEFAULTS = {"native_unit": None, "native_dims": {}, "aggregation": "", "status_policy": "",
                           "fred_equivalent": "", "preferred": "", "min_start": "", "requires_key": ""}


def catalog_field(entry_or_series: Any, name: str) -> Any:
    """Optional curated CatalogEntry field, validated, with its default when absent.

    Reads by getattr so older catalogs without the field keep current behaviour.
    Accepts a CatalogEntry or a series id (a '#transform' suffix is ignored).
    """
    if name not in _CATALOG_FIELD_DEFAULTS:
        raise KeyError(name)
    entry = entry_or_series
    if isinstance(entry_or_series, str):
        entry = catalog.lookup(entry_or_series.partition("#")[0])
    value = getattr(entry, name, None) if entry is not None else None
    default = copy.copy(_CATALOG_FIELD_DEFAULTS[name])
    if name == "native_unit":
        valid = (isinstance(value, (tuple, list)) and len(value) == 2 and isinstance(value[0], str)
                 and isinstance(value[1], int) and not isinstance(value[1], bool))
        return (value[0], value[1]) if valid else default
    if name == "native_dims":
        if not isinstance(value, Mapping) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            return default
        return dict(value)
    allowed = {"aggregation": ("avg", "eop"), "status_policy": ("history_only", "weo_vintage", "gep_vintage")}.get(name)
    if not isinstance(value, str) or (allowed and value not in allowed):
        return default
    return value.strip()


def _display_current(series: Series) -> bool:
    return _policy_current(series.provenance)


def format_series_value(value: float | None, series: Series) -> str:
    """Value text under the row's own display policy, so it matches that row's stored page."""
    return (format_value if _display_current(series) else _legacy_format_value)(value, series.units)


# A US state names its geography for a US series (EIA state recipes: "Retail Sales of Electricity:
# Virginia, commercial sector"; zh "弗吉尼亚州…"), so no " — United States" is appended.
_US_STATE_RE = re.compile(
    r"(?<![A-Za-z])(?:Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|"
    r"Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|"
    r"Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|"
    r"North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|"
    r"Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming|District of Columbia)"
    r"(?![A-Za-z])|[㐀-鿿]{2,6}州")


def _geography_named(title: str, code: str, name: str, aliases: Iterable[str]) -> bool:
    folded = title.casefold()
    for term in (name, code, *aliases):
        term = str(term or "").strip().casefold()
        if not term:
            continue
        if re.search(r"[㐀-鿿]", term):
            if term in folded:
                return True
        elif re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", folded):
            return True
    if code == "USA" and (re.search(r"(?<![A-Za-z])U\.?S\.?A?(?![A-Za-z])", title) or _US_STATE_RE.search(title)):
        return True
    return code == "GBR" and bool(re.search(r"(?<![A-Za-z])U\.?K\.?(?![A-Za-z])", title))


def series_label(series_or_row: Series | Mapping[str, Any], lang: str = "en") -> str:
    """Reader/model-facing series name: curated title, transform, then geography when not named.

    zh uses the curated title_zh and Chinese geography names. Never raises.
    """
    def value(name):
        raw = series_or_row.get(name) if isinstance(series_or_row, Mapping) else getattr(series_or_row, name, "")
        return _clean(raw, 300) if isinstance(raw, str) else ""
    try:
        sid = value("series")
        base, _, transform = sid.partition("#")
        entry = catalog.lookup(base) if base else None
        zh = str(lang or "").lower().startswith("zh")
        title = ((entry.title_zh if entry else "") or value("title_zh")) if zh else ""
        title = title or (entry.title if entry else "") or value("title") or sid
        if transform in ("yoy", "pct"):
            word = {"yoy": ("同比", "year-over-year % change"), "pct": ("环比", "% change from previous period")}[transform]
            title += f"（{word[0]}）" if zh else f" ({word[1]})"
        code = (value("geography") or (entry.geography if entry else "")).upper()
        if not code:
            return title
        name, aliases = catalog.GEOGRAPHIES.get(code, (code, ()))
        if zh:
            name = next((a for a in aliases if re.search(r"[㐀-鿿]", a)), name)
        return title if _geography_named(title, code, name, aliases) else f"{title} — {name}"
    except Exception:
        return _clean(getattr(series_or_row, "series", "") if not isinstance(series_or_row, Mapping) else series_or_row.get("series", ""), 300)


def _partial_period(period: Any) -> bool:
    if not isinstance(period, dict):
        return False
    if period.get("complete") is False:
        return True
    bounds = [period.get(k) for k in ("start", "end", "covered_start", "covered_end")]
    return all(isinstance(b, str) for b in bounds) and (bounds[2], bounds[3]) != (bounds[0], bounds[1])


def _legacy_month_complete(period: Any, series: Series) -> bool:
    """Completeness of a calendar month stored under policy < 3, which marked every month
    incomplete. The month is complete when its coverage spans the whole month and the row
    holds a later period or was retrieved more than a week after month end: the rule
    forecast_extractor._official_legacy_periods re-derives, so the snapshot, report pack,
    charts and anchors agree on old stored rows."""
    version = series.provenance.get("normalization_policy_version")
    if isinstance(version, bool) or isinstance(version, int) and version >= _DISPLAY_POLICY_VERSION:
        return False
    if not isinstance(period, dict) or period.get("calendar") != "calendar_month" or period.get("complete") is not False:
        return False
    if (period.get("covered_start"), period.get("covered_end")) != (period.get("start"), period.get("end")):
        return False
    try:
        end = date.fromisoformat(str(period.get("end")))
    except ValueError:
        return False
    if series.observations and series.observations[-1].date > str(period.get("end")):
        return True
    try:
        return date.fromisoformat(str(series.retrieved_at or "")[:10]) > end + timedelta(days=7)
    except ValueError:
        return False


def observation_kind(obs: Observation | Mapping[str, Any], series: Series | Mapping[str, Any]) -> str:
    """'observed'|'preliminary'|'estimate'|'projection'|'unknown'|'partial' for one stored point.

    'partial' marks an aggregated period (provenance.periods) that is not fully
    covered or not complete; months of rows stored under policy < 3 get their
    completeness re-derived (_legacy_month_complete). Under the current policy a
    period starting after the retrieval date cannot have been observed and is a
    projection. Pass a Series when classifying many points.
    """
    try:
        s = series if isinstance(series, Series) else Series.from_dict(series)
        o = obs if isinstance(obs, Observation) else Observation(obs.get("date"), obs.get("value"), obs.get("flag") or "")
        kind = _observation_kind(o, s)
        retrieved = str(s.retrieved_at or "")[:10]
        if (kind != "projection" and _display_current(s) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", retrieved)
                and o.date > retrieved):
            return "projection"
        periods = s.provenance.get("periods")
        period = periods.get(o.date) if isinstance(periods, dict) else None
        if kind not in ("projection", "estimate") and _partial_period(period) and not _legacy_month_complete(period, s):
            return "partial"
        return kind
    except (ValueError, TypeError, KeyError, AttributeError):
        return "unknown"


def latest_observed(series: Series | Mapping[str, Any]) -> Observation | None:
    """Newest non-missing point classified 'observed' (never partial/projection/estimate/unknown)."""
    try:
        s = series if isinstance(series, Series) else Series.from_dict(series)
    except (ValueError, TypeError, KeyError):
        return None
    return next((o for o in reversed(s.observations) if o.value is not None and observation_kind(o, s) == "observed"), None)


def _display_period(period: str, frequency: str, series: Series | None = None) -> str:
    metadata = series.provenance.get("periods", {}).get(period, {}) if series else {}
    if metadata.get("label"):
        return str(metadata["label"]) + (" (partial)" if metadata.get("complete") is False else "")
    return period[:4] if frequency == "A" else period[:7] if frequency == "M" else period


def _latest_daily(series: Series) -> dict | None:
    """provenance.latest_daily {date, value}: the last native daily point behind monthly rows."""
    point = series.provenance.get("latest_daily")
    try:
        if isinstance(point, Mapping) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(point.get("date"))):
            value = _number(point.get("value"))
            if value is not None:
                return {"date": _period(point["date"]), "value": value}
    except (ValueError, TypeError):
        pass
    return None


def _aggregation_words(series: Series) -> str:
    return "end-of-month values" if series.provenance.get("aggregation_method") == "eop" else "means"


def render_series_page(series: Series) -> str:
    # Policy <= 2 rows keep their original bytes (see _DISPLAY_POLICY_VERSION).
    current = _display_current(series)
    fmt, kind = (format_value, observation_kind) if current else (_legacy_format_value, _observation_kind)
    stats = series_stats(series)
    lines = [f"# {series_label(series) if current else series.title}", f"Provider: {series.provider_name} · Series: {series.series} · Units: {series.units} · Frequency: {series.frequency} · Seasonal adjustment: {series.seasonal_adjustment or 'unknown'}",
             f"Source: {series.source_url} · Retrieved: {series.retrieved_at or 'unknown'} · Coverage shown: {stats['first']} to {stats['last']} ({stats['count']} observations)",
             f"Geography: {series.geography or 'unknown'} · Vintage: {series.vintage or 'unknown'} · Route: {series.route or 'unknown'}"]
    if not current and any(_projected(o, series) for o in series.observations):
        lines.append("Projections: explicitly classified publisher projections are marked in the observation table.")
    elif current and stats["projection_count"]:
        lines.append("Projections: publisher projections are marked 'projection' in the observation table; they are not observed history.")
    if series.notes:
        lines.append(f"Notes: {series.notes}")
    lines += ["## Summary"]
    if stats["latest"]:
        p = stats["latest"]
        scaled = scaled_value(p["value"], series.units) if current else ""
        lines.append(f"- Latest: {fmt(p['value'], series.units)} ({p['date']}){'; ' + scaled if scaled else ''}; see observation status below.")
    daily = _latest_daily(series) if current else None
    if daily:
        lines.append(f"- Latest daily value: {fmt(daily['value'], series.units)} ({daily['date']}); monthly values are {_aggregation_words(series)} of daily data.")
    if stats["previous_year"]:
        p = stats["previous_year"]
        if not current:
            change = f"{fmt(stats['yoy_change'], series.units)} ({fmt(stats['yoy_change_pct'], 'Percent')})"
        elif is_percent_units(series.units) or stats["yoy_change_pct"] is None:
            change = format_change(stats["yoy_change"], series.units)
        else:
            change = f"{format_change(stats['yoy_change'], series.units)} ({_signed(format_value(stats['yoy_change_pct'], 'Percent'))})"
        lines.append(f"- Year earlier: {fmt(p['value'], series.units)} ({p['date']}); change {change}.")
    if stats["five_year_min"]:
        low, high = stats["five_year_min"], stats["five_year_max"]
        lines.append(f"- 5-year range: {fmt(low['value'], series.units)} ({low['date']}) to {fmt(high['value'], series.units)} ({high['date']}).")
    lines += [f"## Observations ({series.units})", f"Values in {series.units or 'unknown units'}.", "| Period | Value | Status |", "|---|---|---|"]
    table = [f"| {_display_period(o.date, series.frequency, series)} | {fmt(o.value, series.units)} | {'missing' if o.value is None else kind(o, series)} |" for o in series.observations]
    while table and len("\n".join(lines + table)) > 11900:
        table.pop(0)
    if len(table) < len(series.observations):
        lines.append("Older rows omitted from this bounded page; stored dataset retains them.")
    return "\n".join(lines + table)[:12000]


def render_series_brief(series: Series, sid: int | None = None) -> str:
    current = _display_current(series)
    fmt, kind = (format_value, observation_kind) if current else (_legacy_format_value, _observation_kind)
    citation = f"[S{sid}] " if isinstance(sid, int) and not isinstance(sid, bool) and sid > 0 else ""
    lines = [f"{citation}{series.series} — {series_label(series) if current else series.title} ({series.units}, {series.frequency})"]
    if current:
        latest = series_stats(series)["latest"]
        if latest:
            scaled = scaled_value(latest["value"], series.units)
            lines.append(f"Latest observed: {fmt(latest['value'], series.units)} ({_display_period(latest['date'], series.frequency, series)})"
                         + (f"; {scaled}" if scaled else ""))
        daily = _latest_daily(series)
        if daily:
            lines.append(f"Latest daily: {fmt(daily['value'], series.units)} ({daily['date']})")
    for o in series.observations[-8:]:
        status = kind(o, series)
        lines.append(f"{_display_period(o.date, series.frequency, series)}: {fmt(o.value, series.units)} [{status}]")
    if series.notes:
        lines.append(series.notes)
    return "\n".join(lines)[:900]


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")


def _no_symlinks(path: Path) -> Path:
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Symlink artifacts are not accepted")
    return path


def _safe_path(root: Path, relative: str = "") -> Path:
    """``relative`` below the configured ``root``. The root is trusted configuration and is
    resolved once (a symlinked ancestor such as macOS /var or a mounted uploads volume is
    fine); no component below it may be a symlink, and nothing may escape it."""
    part = Path(relative)
    if part.is_absolute() or ".." in part.parts:
        raise ValueError("Artifact path escapes output directory")
    return _no_symlinks(Path(os.path.realpath(Path(root).absolute())) / part)


def _read(path: Path, max_bytes: int = _MAX_BYTES) -> bytes:
    _no_symlinks(path)
    directory = _directory_fd(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise ValueError("Artifact must be a regular file")
    finally:
        os.close(directory)
    with os.fdopen(fd, "rb") as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("Artifact exceeds byte limit")
    return data


def _directory_fd(path: Path, *, create: bool = False) -> int:
    """Pin a directory with kernel-enforced no-symlink traversal at every level."""
    path = _no_symlinks(path)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_NOFOLLOW_ANY"):
        # Darwin rejects a symlink in *any* component in the same lookup. Inode
        # checks before/after opening cannot detect a transient ancestor link.
        try:
            # Darwin rejects combining O_NOFOLLOW with O_NOFOLLOW_ANY.
            return os.open(path, (flags & ~os.O_NOFOLLOW) | os.O_NOFOLLOW_ANY)
        except FileNotFoundError:
            if not create:
                raise
        parent = _directory_fd(path.parent, create=True)
        try:
            try:
                os.mkdir(path.name, 0o700, dir_fd=parent)
            except FileExistsError:
                pass
            return os.open(path.name, flags, dir_fd=parent)
        finally:
            os.close(parent)
    # Other POSIX hosts: retain a descriptor at each component. No absolute
    # pathname with mutable ancestors is used after acquiring the root fd.
    fd = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            try:
                child = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _atomic(path: Path, data: bytes):
    _no_symlinks(path)
    directory = _directory_fd(path.parent, create=True)
    tmp = ".data-" + secrets.token_hex(16)
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path.name, src_dir_fd=directory, dst_dir_fd=directory)
    finally:
        try:
            os.unlink(tmp, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)


def _slug(series_id: str) -> str:
    # All provider separators are lossy; always suffix a hash of full identity.
    stem = re.sub(r"[^a-z0-9]+", "_", series_id.lower()).strip("_")[:43]
    return stem + "_" + hashlib.sha256(series_id.encode()).hexdigest()[:16]


def _reason(exc: BaseException) -> str:
    """Concrete, bounded log reason (containment, integrity or OS error), never a raw payload."""
    return f"{type(exc).__name__}: {_clean(exc, 200)}"


def _citation(value: Any) -> str:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return f"S{value}"
    return value if isinstance(value, str) and re.fullmatch(r"S[1-9]\d*", value) else ""


def load_datasets(out_dir: str | Path) -> list[dict]:
    """Read hash-bound local data only. Corrupt rows never become evidence."""
    try:
        root = Path(out_dir)
        manifest_path = _safe_path(root, "data/datasets.json")
        if not manifest_path.exists():
            return []
        manifest = json.loads(_read(manifest_path))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or not isinstance(manifest.get("series"), list) or len(manifest["series"]) > 200:
            raise ValueError("Invalid dataset manifest")
        result, seen = [], set()
        for row in manifest["series"]:
            try:
                if not isinstance(row, dict) or row.get("series") in seen:
                    raise ValueError("Duplicate or invalid manifest row")
                raw = _read(_safe_path(root, row["file"]))
                csv_raw = _read(_safe_path(root, row["csv"]))
                if hashlib.sha256(raw).hexdigest() != row.get("sha256") or hashlib.sha256(csv_raw).hexdigest() != row.get("csv_sha256"):
                    raise ValueError("Artifact hash mismatch")
                series = Series.from_dict(json.loads(raw))
                data = series.to_dict()
                slug = _slug(series.series)
                json_names = (f"data/{slug}.json", f"data/{slug}.{row['sha256'][:16]}.json")
                csv_names = (f"data/{slug}.csv", f"data/{slug}.{row['csv_sha256'][:16]}.csv")
                if row.get("slug") != slug or row["file"] not in json_names or row["csv"] not in csv_names:
                    raise ValueError("Manifest file/slug identity mismatch")
                if row.get("chart") and row["chart"] != f"charts/data_{slug}.png":
                    raise ValueError("Invalid manifest chart path")
                if row.get("source_id") and _citation(row["source_id"]) != row["source_id"]:
                    raise ValueError("Invalid manifest source ID")
                for name in ("series", "provider", "units", "frequency", "seasonal_adjustment", "transform", "source_url", "api_url", "geography", "vintage", "projection_from"):
                    if row.get(name, "") != data[name]:
                        raise ValueError("Artifact metadata/identity mismatch")
                if not series.observations or not series.source_url:
                    raise ValueError("Empty or uncitable dataset")
                seen.add(series.series)
                result.append({**row, **data})
            except (ValueError, TypeError, KeyError, OSError) as exc:
                logger.warning("Official data row unavailable: integrity or containment validation failed (%s)", _reason(exc))
        return result
    except (ValueError, TypeError, KeyError, OSError) as exc:
        logger.warning("Official data manifest unavailable: integrity or containment validation failed (%s)", _reason(exc))
        return []


def write_dataset_files(series_list: Iterable[Series], out_dir: str | Path, *, citations: Mapping[str, Any] | None = None) -> dict:
    """Incrementally merge datasets, committing the manifest after JSON and CSV."""
    with _WRITE_LOCK:
        try:
            root = Path(out_dir)
            _safe_path(root, "data")
            existing = {r["series"]: r for r in load_datasets(root)}
            incoming = list(series_list)
            if len(incoming) > 200:
                raise ValueError("Too many datasets")
            for value in incoming:
                s = Series.from_dict(value.to_dict() if isinstance(value, Series) else value)
                if not s.observations or not s.source_url:
                    raise ValueError("Empty or uncitable dataset")
                prior = existing.get(s.series, {})
                # KIQ links accumulate across requests for the same series.
                s.kiqs = _kiq_ids([*(prior.get("kiqs") or []), *s.kiqs])
                slug = _slug(s.series)
                raw = _bytes(s.to_dict())
                stream = io.StringIO(newline="")
                writer = csv.writer(stream, lineterminator="\n")
                writer.writerow(["date", "value"])
                writer.writerows((o.date, "" if o.value is None else o.value) for o in s.observations)
                csv_raw = stream.getvalue().encode()
                digest, csv_digest = hashlib.sha256(raw).hexdigest(), hashlib.sha256(csv_raw).hexdigest()
                # Immutable content generations keep the old manifest readable
                # through a failed update or an in-flight successful write.
                json_name, csv_name = f"{slug}.{digest[:16]}.json", f"{slug}.{csv_digest[:16]}.csv"
                _atomic(_safe_path(root, "data/" + json_name), raw)
                _atomic(_safe_path(root, "data/" + csv_name), csv_raw)
                stats = series_stats(s)
                row = {**s.to_dict(), "slug": slug, "observations": len(s.observations), "first": stats["first"], "last": stats["last"], "latest": stats["latest"],
                       "file": f"data/{json_name}", "csv": f"data/{csv_name}", "sha256": digest,
                       "csv_sha256": csv_digest, "source_id": _citation((citations or {}).get(s.series, prior.get("source_id"))),
                       "chart": prior.get("chart", f"charts/data_{slug}.png")}
                existing[s.series] = row
            rows = []
            for sid, row in existing.items():
                if isinstance(row.get("observations"), list):
                    row["observations"] = len(row["observations"])
                if citations and sid in citations:
                    row["source_id"] = _citation(citations[sid])
                rows.append(row)
            manifest = {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(), "series": rows}
            _atomic(_safe_path(root, "data/datasets.json"), _bytes(manifest))
            return manifest
        except (ValueError, TypeError, KeyError, OSError) as exc:
            logger.warning("Official data persistence failed: invalid input or unavailable output directory (%s)", _reason(exc))
            return {"schema_version": 1, "series": [], "error": "Official data persistence failed", "code": "persistence_failed"}


_REPORT_CITATION = re.compile(r"[\[【]\s*(S\d+(?:\s*[,，;；]\s*S\d+)*)\s*[\]】]", re.I)


def _report_citations(root: Path) -> set[str]:
    """Source ids ([S#]) cited in the run's research_report.md; empty when unreadable."""
    try:
        text = _read(_safe_path(root, "research_report.md"), 8 * _MAX_BYTES).decode("utf-8", "replace")
    except (ValueError, OSError):
        return set()
    return {f"S{int(n)}" for group in _REPORT_CITATION.findall(text) for n in re.findall(r"\d+", group)}


def _max_series(value: Any) -> int | None:
    """Carrier cap: the explicit value, else DATA_SOURCES_MAX_SERIES, else 24 (at most 200)."""
    if value is None:
        raw = str(os.environ.get("DATA_SOURCES_MAX_SERIES") or "").strip()
        value = int(raw) if re.fullmatch(r"\d{1,4}", raw) and int(raw) >= 1 else _DEFAULT_MAX_SERIES
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return None
    return min(value, 200)


def load_official_data(handoff_dir: str | Path, *, max_series: int | None = None,
                       anchored: Iterable[str] = ()) -> dict | None:
    """The bounded official-data carrier for downstream stages.

    ``max_series`` defaults to DATA_SOURCES_MAX_SERIES (24). Rows rank anchored series
    first, then series cited in the research report, then KIQ-linked ones, then the rest,
    each in manifest order; ids beyond the cap are listed under ``omitted``.
    """
    limit = _max_series(max_series)
    if limit is None:
        return None
    rows = load_datasets(handoff_dir)
    if not rows:
        return None
    try:
        anchors = set() if isinstance(anchored, (str, bytes)) else {a for a in anchored if isinstance(a, str)}
    except TypeError:
        anchors = set()
    cited = _report_citations(Path(handoff_dir))
    def rank(row):
        if row["series"] in anchors:
            return 0
        if row.get("source_id") in cited:
            return 1
        return 2 if row.get("kiqs") else 3
    ranked = sorted(rows, key=rank)
    kept, omitted = ranked[:limit], [row["series"] for row in ranked[limit:]]
    for row in kept:
        row["observations"] = row["observations"][-240:]
    carrier = {"schema_version": 1, "series": kept}
    if omitted:
        carrier["omitted"] = omitted
        logger.warning("Official data carrier keeps %d of %d series (cap %d); omitted: %s",
                       len(kept), len(rows), limit, ", ".join(omitted))
    return carrier


def _fiscal_label_period(text: str, series: Series) -> str | None:
    """Start date of the stored fiscal period labelled ``text`` ('FY2026', 'FY 2026'), if any."""
    label = re.fullmatch(r"(?i)FY\s?(\d{4})", text.strip())
    periods = series.provenance.get("periods")
    if not label or not isinstance(periods, dict):
        return None
    starts = [start for start, record in periods.items()
              if isinstance(record, dict) and record.get("label") == f"FY{label.group(1)}"]
    return starts[0] if len(starts) == 1 else None


def _anchor_period(period: Any, series: Series) -> str:
    text = str(period)
    if series.frequency == "A":
        # A fiscal-year series may be anchored by its stored label ('FY2026' -> 2025-10-01).
        text = _fiscal_label_period(text, series) or text
        period = text
    if series.frequency == "M" and not re.fullmatch(r"\d{4}-\d{2}(?:-01)?", text):
        raise ValueError("Monthly anchor needs a month")
    if series.frequency == "Q" and not re.fullmatch(r"\d{4}-Q[1-4]|\d{4}-(?:01|04|07|10)-01", text):
        raise ValueError("Quarterly anchor needs a quarter")
    if series.frequency in ("D", "W") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise ValueError("Daily or weekly anchor needs an exact date")
    if series.frequency == "A" and not re.fullmatch(r"\d{4}|\d{4}-\d{2}-01", text):
        raise ValueError("Annual anchor needs a year or exact period start")
    normalized = _period(period)
    d = date.fromisoformat(normalized)
    if series.frequency == "M" and d.day != 1:
        raise ValueError("Not an exact monthly period")
    if series.frequency == "Q" and (d.day != 1 or d.month not in (1, 4, 7, 10)):
        raise ValueError("Not an exact quarterly period")
    if series.frequency == "A":
        # Fiscal calendar has to be explicit in canonical metadata.
        month = series.provenance.get("fiscal_start_month", 1)
        if d.day != 1 or d.month != month:
            raise ValueError("Not an exact annual period")
    if series.frequency not in ("D", "W", "M", "Q", "A"):
        raise ValueError("Unknown frequency")
    return normalized


def validate_data_anchor(anchor: Any, official_data: Any) -> dict | None:
    try:
        if not isinstance(anchor, dict) or not isinstance(official_data, dict):
            return None
        sid = anchor.get("series")
        rows = [r for r in official_data.get("series", []) if isinstance(r, dict) and r.get("series") == sid]
        if len(rows) != 1:
            return None
        s = Series.from_dict(rows[0])
        threshold = _number(anchor.get("threshold"))
        if threshold is None or not s.units or s.units.lower() in ("unknown", "value"):
            return None
        if anchor.get("comparator") not in (">", ">=", "<", "<="):
            return None
        if "units" in anchor and anchor["units"] != s.units or "transform" in anchor and anchor["transform"] != s.transform:
            return None
        supplied = anchor.get("observation", anchor.get("period"))
        period = _anchor_period(supplied, s)
        if "observation" in anchor and "period" in anchor and _anchor_period(anchor["period"], s) != period:
            return None
        historical = [o for o in s.observations if o.value is not None and _observation_kind(o, s) == "observed"]
        latest = historical[-1] if historical and s.provenance.get("resolution_safe") is not False else None
        return {"series": s.series, "period": period, "observation": supplied,
                "threshold": threshold, "comparator": anchor["comparator"],
                "units": s.units, "transform": s.transform, "frequency": s.frequency, "geography": s.geography,
                "vintage": s.vintage, "source_url": s.source_url,
                "latest_value": latest.value if latest else None, "latest_date": latest.date if latest else ""}
    except (ValueError, TypeError, KeyError, OverflowError):
        return None


def _resolution_instant(value: Any, *, date_end: bool = True) -> datetime:
    """ISO dates span a UTC day; ISO timestamps retain exact instant precision."""
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        instant = datetime.fromisoformat(_period(text)).replace(tzinfo=timezone.utc)
        return instant + timedelta(days=1, microseconds=-1) if date_end else instant
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?", text):
        raise ValueError("Availability/cutoff requires an ISO date or timestamp")
    instant = datetime.fromisoformat(text.replace("Z", "+00:00"))
    # Naive ISO timestamps use UTC explicitly, never the host local timezone.
    return instant.replace(tzinfo=timezone.utc) if instant.tzinfo is None else instant.astimezone(timezone.utc)


def resolution_instant(value: Any, date_end: bool = True) -> datetime:
    """Public UTC parsing contract shared by resolution, monitoring and snapshots."""
    return _resolution_instant(value, date_end=date_end)


def _period_complete_at(period: str, frequency: str) -> datetime:
    if frequency in ("M", "Q", "A"):
        following = _shift(period, {"M": 1, "Q": 3, "A": 12}[frequency])
    elif frequency in ("D", "W"):
        following = (date.fromisoformat(period) + timedelta(days=1 if frequency == "D" else 7)).isoformat()
    else:
        raise ValueError("Unknown observation period duration")
    return _resolution_instant(following, date_end=False) - timedelta(microseconds=1)


def resolve_data_anchor(anchor: Any, series: Series | Mapping[str, Any], *, as_of: str | None = None) -> dict:
    """Resolve only completed periods whose stored value was available by cutoff.

    Date-only cutoffs include the complete UTC day. ISO timestamp cutoffs retain
    offsets/intraday precision; unzoned timestamps mean UTC. Availability comes
    from the canonical retrieval receipt. Current adapters do not authenticate
    historical-vintage availability proofs, so free-form vintage, last_updated,
    available_at or model-provided provenance cannot substitute for retrieval.
    """
    sid = _clean(anchor.get("series", "")) if isinstance(anchor, dict) else ""
    def result(status, reason, obs=None, outcome=None):
        row = {"status": status, "reason": reason, "series": sid}
        if obs is not None:
            row["observation"] = asdict(obs)
        if status == "resolved":
            row["outcome"] = bool(outcome)
        return row
    try:
        s = Series.from_dict(series.to_dict() if isinstance(series, Series) else series)
        valid = validate_data_anchor(anchor, {"series": [s.to_dict()]})
        if not valid:
            return result("manual", "Unknown series, period, units, transform or comparison")
        cutoff = _resolution_instant(as_of) if as_of is not None else datetime.now(timezone.utc)
        obs = next((o for o in s.observations if o.date == valid["period"]), None)
        if obs and _observation_kind(obs, s) != "observed":
            return result("manual", "Projection, estimate or ambiguous observation status", obs)
        if s.provenance.get("resolution_safe") is False:
            return result("manual", "Provider metadata cannot establish an exact historical observation", obs)
        completed_at = _period_complete_at(valid["period"], s.frequency)
        if cutoff < completed_at:
            return result("pending", "The full observation period has not ended at the cutoff", obs)
        if obs is None or obs.value is None:
            return result("pending", "Exact historical observation is not yet available", obs)
        try:
            earliest_retrieval = _resolution_instant(s.retrieved_at, date_end=False)
            latest_retrieval = _resolution_instant(s.retrieved_at)
        except (ValueError, TypeError, OverflowError):
            return result("manual", "Historical availability is unknown: valid retrieval evidence is required", obs)
        if latest_retrieval > cutoff:
            return result("manual", "Stored value availability is not established at the historical cutoff", obs)
        if earliest_retrieval < completed_at:
            return result("manual", "Stored observation was retrieved before its full period ended", obs)
        value, threshold = obs.value, valid["threshold"]
        outcome = {">": value > threshold, ">=": value >= threshold, "<": value < threshold, "<=": value <= threshold}[valid["comparator"]]
        return result("resolved", "Exact historical observation satisfies comparison", obs, outcome)
    except (ValueError, TypeError, KeyError, OverflowError):
        return result("manual", "Invalid or ambiguous canonical observation metadata")


def _frequency(value: Any) -> str:
    """Native frequency label -> D/W/M/Q/A. FRED qualifies labels ("Daily, 7-Day", "Weekly,
    Ending Friday", "Quarterly, End of Period"); the leading word names the frequency."""
    text = str(value or "").upper().strip().split(",")[0].strip()
    return {"DAILY": "D", "WEEKLY": "W", "MONTHLY": "M", "QUARTERLY": "Q", "ANNUAL": "A", "YEARLY": "A"}.get(text, text if text in ("D", "W", "M", "Q", "A") else "")


def _seasonal(value: Any) -> str:
    return {"Seasonally Adjusted": "SA", "Not Seasonally Adjusted": "NSA", "Seasonally Adjusted Annual Rate": "SAAR"}.get(str(value), str(value) if value in ("SA", "NSA", "SAAR") else "")


def _native_period(value: Any, frequency: str) -> str:
    text = str(value)
    patterns = {"M": r"\d{4}(?:-\d{2}(?:-01)?|-?M\d{2})",
                "Q": r"\d{4}[- ]?Q[1-4]|\d{4}-(?:01|04|07|10)-01",
                "A": r"\d{4}(?:-01-01)?", "D": r"\d{4}-\d{2}-\d{2}",
                "W": r"\d{4}-\d{2}-\d{2}"}
    if frequency not in patterns or not re.fullmatch(patterns[frequency], text, re.I):
        raise ValueError("Provider period precision conflicts with series frequency")
    return _period(text)


# SDMX unit-measure codelist names, used only for uncurated keys of a known BIS flow (curated
# entries carry a verified pin and always show their catalog units).
_SDMX_UNIT_NAMES = {"367": "Per cent", "368": "Per cent per year", "770": "Percentage of GDP",
                    "771": "Year-on-year changes, in per cent", "628": "Index, 2010 = 100", "882": "Index, 2020 = 100"}
# Data360 unit codes; their free-text metadata unit is often terser ("%", "Unit") or richer.
_WB_UNIT_NAMES = {"PC": "Percent change", "PC_A": "Percent change per annum", "PT_GDP": "Percent of GDP",
                  "PT_LF": "Percent of labor force", "PT_POP": "Percent of population", "PS": "Persons",
                  "USD": "US dollars", "MTCO2E": "Mt CO2 equivalent", "KWH": "Kilowatt-hours"}
_UNINFORMATIVE_UNITS = frozenset(("", "%", "unit", "units", "number", "value", "none", "n/a", "na"))
_SCALE_NAMES = {3: "thousands", 6: "millions", 9: "billions", 12: "trillions"}
_WB_BREAKDOWNS = ("SEX", "AGE", "URBANISATION", "COMP_BREAKDOWN_1", "COMP_BREAKDOWN_2")
_V_LST_VINTAGE = "latest published (V_LST)"
_WEO_STATUS_NOTE = ("Publisher feed strips observation status; inferred from the vintage year V: periods from V are "
                    "publisher projections, V-1 an estimate, earlier periods history (revisable).")


def _release_year(metadata: Mapping[str, Any], retrieval_year: int) -> tuple[int, str] | None:
    """Release year of a Data360 vintage from its metadata (released, version or update date)."""
    version = metadata.get("version_statement")
    candidates = (("date_released", metadata.get("date_released")),
                  ("version_statement.version_date", version.get("version_date") if isinstance(version, Mapping) else None),
                  ("date_last_update", metadata.get("date_last_update")))
    for name, raw in candidates:
        found = re.match(r"\s*(\d{4})-\d{2}-\d{2}", str(raw or ""))
        if found and 1990 <= int(found[1]) <= retrieval_year:
            return int(found[1]), f"Data360 {name} {found[0].strip()}"
    return None


def _scale_of(text: str) -> int:
    """Power of ten named by a scale word in unit text ("US dollar, millions" -> 6), else 0."""
    for exponent, word in ((12, "trillion"), (9, "billion"), (6, "million"), (3, "thousand")):
        if re.search(r"(?i)\b" + word + r"s?\b", str(text or "")):
            return exponent
    return 0


def _native_unit(attributes: Mapping[str, Any], label_key: str) -> tuple[str, str, int]:
    """(unit code, label, UNIT_MULT exponent) as rows carry them; absent code '' and multiplier 0."""
    code = str(next(iter(attributes.get("UNIT_MEASURE", [])), "") or "")
    label = _clean(next(iter(attributes.get(label_key, [])), "") or "", 200)
    raw = str(next(iter(attributes.get("UNIT_MULT", [])), "") or "").strip()
    if raw and not re.fullmatch(r"-?\d{1,2}", raw):
        raise DataFailure("Native unit multiplier is not an integer", "provider_error")
    return code, label, int(raw or 0)


def _pin_matches(entry: Any, code: str, multiplier: int, dims: Mapping[str, set]) -> bool | None:
    """None when ``entry`` pins no native identity, else whether rows carry exactly the pin."""
    pin = catalog_field(entry, "native_unit") if entry is not None else None
    if pin is None:
        return None
    return (code, multiplier) == pin and all(dims.get(d) == {v} for d, v in catalog_field(entry, "native_dims").items())


def _pinned_units(entry: Any, code: str, multiplier: int, dims: Mapping[str, set], what: str) -> str | None:
    """Curated units when the entry pins its native identity; fail closed on any drift."""
    matched = _pin_matches(entry, code, multiplier, dims)
    if matched is None:
        return None
    pin = catalog_field(entry, "native_unit")
    if (code, multiplier) != pin:
        raise DataFailure(f"{what} native unit {code or 'none'} x10^{multiplier} differs from the verified catalog pin "
                          f"{pin[0] or 'none'} x10^{pin[1]}; units cannot be established", "provider_error")
    if not matched:
        raise DataFailure(f"{what} key dimensions differ from the verified catalog pin; units cannot be established", "provider_error")
    return entry.units


# Key dimensions naming the economy: a curated series and an uncurated key that differ only
# there are the same statistic, so the curated units (and unit pin) carry over.
_GEOGRAPHY_DIMS = frozenset(("REF_AREA", "COUNTRY", "BORROWERS_CTY"))


def _curated_sibling(req: dict) -> Any:
    """For an uncurated id: the curated entry for the same indicator/flow key in another
    economy, when all such entries agree on units and native identity; None otherwise."""
    provider, native = req["provider"], req["native"]
    if provider == "wb":
        indicator = native.split("/")[0]
        def same(e):
            return e.native.split("/")[0] == indicator
    elif provider in ("bis", "imf"):
        flow, key = native.split("/")
        info = catalog.BIS_FLOWS.get if provider == "bis" else catalog.imf_flow_info
        meta, parts = info(flow), key.split(".")
        keep = [i for i, dim in enumerate(meta["dims"]) if dim not in _GEOGRAPHY_DIMS]
        def same(e):
            other_flow, other_key = e.native.split("/")
            other, other_meta = other_key.split("."), info(other_flow)
            family = other_flow == flow if provider == "bis" else bool(other_meta) and other_meta["base_flow"] == meta["base_flow"]
            return family and len(other) == len(parts) and all(other[i] == parts[i] for i in keep)
    else:
        return None
    siblings = [e for e in catalog.CATALOG if e.provider == provider and same(e)]
    identities = {(e.units, catalog_field(e, "native_unit"), tuple(sorted(catalog_field(e, "native_dims").items())))
                  for e in siblings}
    return siblings[0] if len(identities) == 1 else None


def _sdmx_units(req: dict, attributes: dict, dims: Mapping[str, str]) -> tuple[str, dict]:
    """Display units plus the native identity kept in provenance; fail closed on contradictions.

    Curated entries pin (UNIT_MEASURE, UNIT_MULT) and key dimensions and always show their
    catalog units. An uncurated key takes a curated sibling's units when its rows carry the
    sibling's pin, else the native label or codelist name; IMF rows carry no unit attributes,
    so an uncurated IMF key without a sibling has unknown units.
    """
    entry = catalog.lookup(req["base"])
    code, label, multiplier = _native_unit(attributes, "UNIT_MEASURE_LABEL")
    record = {"code": code, "label": label, "multiplier": multiplier}
    row_dims = {k: {v} for k, v in dims.items()}
    pinned = _pinned_units(entry, code, multiplier, row_dims, "SDMX")
    if pinned is not None:
        return pinned, {**record, "basis": "verified catalog pin"}
    if entry is None:
        sibling = _curated_sibling(req)
        matched = _pin_matches(sibling, code, multiplier, row_dims)
        if matched or matched is None and sibling is not None and not (code or label or multiplier):
            return sibling.units, {**record, "basis": f"curated sibling {sibling.series}"}
    if entry is not None:
        # Curated without a pin (IMF rows carry no unit attributes): only the scale is checkable.
        if (code or label or multiplier) and multiplier != _scale_of(entry.units):
            raise DataFailure("Native SDMX scale conflicts with catalog units", "provider_error")
        return entry.units, {**record, "basis": "curated catalog"}
    if multiplier not in (0, *_SCALE_NAMES):
        raise DataFailure("Native SDMX unit multiplier is unsupported", "provider_error")
    base = label or _SDMX_UNIT_NAMES.get(code, "")
    if not base and req["provider"] == "bis" and req["native"].startswith("WS_XRU/") and dims.get("CURRENCY"):
        base = f"{dims['CURRENCY']} per US dollar"  # the BIS XRU flow quotes every currency per US dollar
    if not base:
        if req["provider"] == "imf" and not multiplier:
            return "", {**record, "basis": "not supplied by provider"}
        raise DataFailure("Native SDMX units are unavailable for an uncurated key", "provider_error")
    named = _scale_of(base)
    if multiplier and named and named != multiplier:
        raise DataFailure("Native SDMX unit label and multiplier conflict", "provider_error")
    if multiplier and not named:
        base = f"{base}, {_SCALE_NAMES[multiplier]}"
    return base, {**record, "basis": "native label" if label else "native codelist"}


def _columnar(payload: dict) -> list[dict]:
    data = payload.get("data", {})
    if payload.get("truncatedToFit") or data.get("truncated"):
        raise ValueError("Provider response truncated; narrow the requested window")
    columns, rows = data.get("columns"), data.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list) or len(columns) != len(set(columns)):
        raise ValueError("Invalid columnar response")
    if any(not isinstance(r, list) or len(r) != len(columns) for r in rows):
        raise ValueError("Column count mismatch")
    return [dict(zip(columns, row)) for row in rows]


def _unit_text(text: Any) -> str:
    return " ".join(str(text or "").lower().split())


def _wb_units(req: dict, attributes: dict, metadata: dict, dims: Mapping[str, set]) -> tuple[str, dict]:
    """Display units for a Data360 series plus the native identity kept in provenance.

    Curated entries pin (UNIT_MEASURE, UNIT_MULT): on an exact match the curated units are
    shown, never the native label (labels can be wrong: KWH drops "per capita", WEO LUR says
    "of population"). The same indicator for an uncurated economy takes a curated sibling's
    units when its rows carry that sibling's exact pin. Data360 multipliers are otherwise
    unverified (IMF_WEO_NGDPD says x10^9 on whole-dollar values), so any other indicator with a
    non-zero multiplier, or whose label and metadata name different scales, fails closed.
    """
    entry = catalog.lookup(req["base"])
    code, label, multiplier = _native_unit(attributes, "UNIT_MEASURE_NAME")
    measure = _clean(metadata.get("measurement_unit") or "", 200)
    record = {"code": code, "label": label, "multiplier": multiplier, "metadata_unit": measure}
    pinned = _pinned_units(entry, code, multiplier, dims, "Data360")
    if pinned is not None:
        return pinned, {**record, "basis": "verified catalog pin"}
    sibling = _curated_sibling(req) if entry is None else None
    if _pin_matches(sibling, code, multiplier, dims):
        # Same indicator in another economy with exactly the verified native identity.
        return sibling.units, {**record, "basis": f"verified pin of curated sibling {sibling.series}"}
    if not code:
        raise DataFailure("Data360 unit code is unavailable", "provider_error")
    informative = measure if _unit_text(measure) not in _UNINFORMATIVE_UNITS else ""
    if multiplier or (label and informative and _scale_of(label) != _scale_of(informative)):
        raise DataFailure("Data360 unit multiplier cannot be verified for an uncurated indicator; "
                          "use a curated catalog series", "provider_error")
    units = informative or label or _WB_UNIT_NAMES.get(code.upper(), "")
    if not units:
        raise DataFailure("Data360 units are unavailable for an uncurated indicator", "provider_error")
    return units, {**record, "basis": "native metadata" if informative else "native label" if label else "native codelist"}


def _http_csv(url: str, *, timeout: float = 15) -> bytes:
    """Bounded, fixed-origin keyless fetch; no redirects or ambient proxies."""
    from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ValueError("FRED CSV redirect refused")

    p = urlsplit(url)
    if p.scheme != "https" or p.netloc != "fred.stlouisfed.org" or p.path != "/graph/fredgraph.csv":
        raise ValueError("Invalid FRED CSV origin")
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request(url, headers={"Accept": "text/csv", "User-Agent": "DeepResearchForecast/official-data"})
    with opener.open(request, timeout=timeout) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("FRED CSV HTTP response unavailable")
        length = response.headers.get("Content-Length")
        if length and int(length) > _MAX_BYTES:
            raise ValueError("FRED CSV response exceeds byte limit")
        chunks, size = [], 0
        deadline = time.monotonic() + timeout
        while size <= _MAX_BYTES:
            if time.monotonic() >= deadline:
                raise TimeoutError("FRED CSV body deadline exceeded")
            chunk = response.read1(min(65536, _MAX_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        content = b"".join(chunks)
        if len(content) > _MAX_BYTES:
            raise ValueError("FRED CSV response exceeds byte limit")
        return content


class DataSources:
    def __init__(self, hub: McpHub | None = None, *, env: Mapping[str, str] | None = None,
                 cache_dir: str | Path | None = None, providers: Iterable[str] | None = None,
                 clock=time.time, http_get=None):
        self._env = dict(os.environ if env is None else env)
        self._hub = hub
        raw = providers if providers is not None else (self._env.get("DATA_SOURCES", "") or ",".join(PROVIDERS)).split(",")
        self._allowed = {p.strip().lower() for p in raw if isinstance(p, str)} & set(PROVIDERS)
        self._on = self._env.get("DATA_SOURCES_ENABLED", "true").strip().lower() == "true"
        # Match source/deployed layout without inspecting saved datasets at import. A relative
        # DATA_SOURCES_CACHE_DIR means the repository root (as for the hub logs), never the cwd,
        # so research, backend and monitor share one cache and one keyless BLS quota record;
        # the root is resolved once (its own ancestors may be symlinks, nothing below it).
        root = Path(__file__).resolve().parent.parent
        default = root / "backend/uploads/.data_cache"
        configured = _source_path({"DATA_SOURCES_CACHE_DIR": str(cache_dir or self._env.get("DATA_SOURCES_CACHE_DIR") or "")},
                                  "DATA_SOURCES_CACHE_DIR", default)
        self._cache_dir = Path(os.path.realpath(configured))
        self._clock, self._http = clock, http_get or _http_csv
        self._secrets = _credentials(self._env)
        self._lock = threading.RLock()
        self._locks: dict[str, threading.Lock] = {}
        self._memory: dict[str, tuple[float, dict]] = {}
        self._local = threading.local()
        self._imf_defs: dict[str, dict] = {}
        self._semaphores = {p: threading.BoundedSemaphore(1 if p in ("imf", "bls") else 3) for p in PROVIDERS}
        self._closed = False
        # Backtest mode (apply_backtest): every window ends at the cutoff; None = live.
        self._backtest = None
        self._prune_cache()

    def _prune_cache(self) -> None:
        """Drop provider-cache files older than a week, once per directory and process; never raises."""
        key = str(self._cache_dir)
        with _WRITE_LOCK:
            if key in _PRUNED_CACHES:
                return
            _PRUNED_CACHES.add(key)
        try:
            cutoff = self._clock() - _CACHE_MAX_AGE_S
            with os.scandir(self._cache_dir) as entries:
                for item in entries:
                    if _CACHE_FILE.fullmatch(item.name) and item.is_file(follow_symlinks=False) and item.stat(follow_symlinks=False).st_mtime < cutoff:
                        os.unlink(item.path)
        except (OSError, ValueError, TypeError):
            pass

    def _get_hub(self):
        with self._lock:
            if self._hub is None:
                self._hub = get_hub(env=self._env)
            return self._hub

    def apply_backtest(self, policy) -> None:
        """Backtest mode (docs/handoff/backtest/design.md §5): windows end at the
        cutoff, FRED requests the as-of vintage (``vintage_dates``), and every
        other observation must be known by then (``backtest_cutoff.observation_admitted``).
        Cache keys carry the policy tag, so live and backtest entries never mix.
        Only the v3 research engine calls this; a client without it stays live."""
        self._backtest = policy

    def _today(self) -> str:
        """Today's UTC date, or the backtest as-of date when it is earlier."""
        today = datetime.fromtimestamp(self._clock(), timezone.utc).date().isoformat()
        return min(today, self._backtest.as_of_iso) if self._backtest is not None else today

    def providers(self) -> dict[str, str]:
        """Per provider: ready | keyless (FRED CSV route) | key_invalid (the provider rejected the
        configured key; FRED continues via CSV, BLS via a keyless server) | disabled | closed |
        the hub's redacted failure reason."""
        if not self._on or self._closed:
            return {p: "disabled" if not self._on else "closed" for p in PROVIDERS}
        try:
            statuses = self._get_hub().status()
        except Exception:
            statuses = {}
        result = {}
        for p in PROVIDERS:
            status = statuses.get(p, {})
            if p not in self._allowed:
                result[p] = "disabled"
            elif p == "fred" and not self._key("fred"):
                result[p] = "key_invalid" if self._key_rejected("fred") else "keyless"
            elif status.get("state") in ("ready", "idle", "starting"):
                result[p] = "key_invalid" if p == "bls" and self._key_rejected("bls") else "ready"
            else:
                result[p] = self._redact(status.get("error") or status.get("state") or "unavailable")
        return result

    def hub_status(self) -> dict[str, dict]:
        """The hub's per-provider status (state, error, tool calls, failures); {} before any use."""
        try:
            return dict(self._hub.status()) if self._hub is not None else {}
        except Exception:
            return {}

    def _server_down(self, provider: str) -> bool:
        """The provider's MCP server cannot serve now: unavailable (not built, no node) or failed."""
        status = self.hub_status().get(provider)
        return isinstance(status, Mapping) and status.get("state") in ("unavailable", "failed")

    def enabled(self) -> bool:
        return self._on and not self._closed and any(v in ("ready", "keyless", "key_invalid") for v in self.providers().values())

    def _key(self, provider: str) -> str:
        """The configured registration key, or '' when absent or rejected earlier in this process."""
        value = str(self._env.get(_KEY_NAMES[provider]) or "").strip()
        return "" if not value or self._key_rejected(provider) else value

    def _key_rejected(self, provider: str) -> bool:
        value = str(self._env.get(_KEY_NAMES[provider]) or "").strip()
        with _KEY_LOCK:
            return bool(value) and (provider, hashlib.sha256(value.encode()).hexdigest()) in _REJECTED_KEYS

    def _reject_key(self, provider: str) -> None:
        value = str(self._env.get(_KEY_NAMES[provider]) or "").strip()
        if value:
            with _KEY_LOCK:
                _REJECTED_KEYS.add((provider, hashlib.sha256(value.encode()).hexdigest()))
            logger.warning("Official data: %s rejected %s; continuing keyless", provider, _KEY_NAMES[provider])

    def prewarm(self) -> None:
        if not self._on or self._closed:
            return
        names = [p for p, s in self.providers().items() if s == "ready" or s == "key_invalid" and p != "fred"]
        if names:
            try:
                self._get_hub().start(names)
            except Exception:
                logger.warning("Official data prewarm unavailable")

    def close(self) -> None:
        self._closed = True
        if self._hub is not None:
            try:
                self._hub.close()
            except Exception:
                logger.warning("Official data hub close failed")

    def _scrub(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, "[redacted]")
        return text

    def _redact(self, value: Any) -> str:
        return _clean(self._scrub(str(value or "")), 300)

    def _error(self, sid, exc) -> DataError:
        """The only DataError factory: classified code, redacted reason, then a hint."""
        code, retryable = _failure_class(exc)
        hint = self._hint(sid, code)
        reason = self._redact(exc).rstrip(" .;:") or code.replace("_", " ")
        reason = reason[:300 - len(hint) - 2].rstrip(" .;:")
        return DataError(self._redact(sid), f"{reason}. {hint}", retryable, code)

    @staticmethod
    def _hint(sid, code: str) -> str:
        """Actionable hint; operational failures name a curated equivalent series."""
        if code in ("rate_limited", "quota_exhausted", "key_invalid", "provider_unavailable", "timeout") and isinstance(sid, str):
            base, _, transform = sid.strip().partition("#")
            for name, why in (("fred_equivalent", "same data on FRED"), ("preferred", "faster equivalent")):
                target = catalog_field(base, name) if parse_series_id(base) else ""
                if target and ":" not in target:
                    target = "fred:" + target
                parsed = parse_series_id(target + ("#" + transform if transform else "")) if target else None
                if parsed and ":".join(parsed) != sid.strip():
                    return f"Use {':'.join(parsed)} ({why})" + (" or retry later." if code in _RETRYABLE_CODES else " instead.")
        return _HINTS[code]

    def _remaining(self) -> float | None:
        deadline = getattr(self._local, "deadline", None)
        if self._closed:
            raise DataFailure("Data sources closed", "provider_unavailable", False)
        if deadline is None:
            return None
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("Data request deadline exceeded")
        return left

    def _call(self, provider, tool, args):
        left = self._remaining()
        hub = self._get_hub()
        left = self._remaining()
        if left is not None and hub.status().get(provider, {}).get("state") != "ready":
            hub.start([provider], wait=left)
            left = self._remaining()
            if hub.status().get(provider, {}).get("state") != "ready":
                raise TimeoutError("Provider was not ready within the data deadline")
        options = {"timeout": left, "deadline": self._local.deadline} if left is not None else {}
        result = hub.call(provider, tool, args, **options)
        self._remaining()
        if not result.ok:
            raise _ToolFailure(self._redact(result.error or result.text or "Provider unavailable"),
                               self._scrub(result.text or "")[:4000] if getattr(result, "is_tool_error", False) else "")
        raw = result.structured if result.structured is not None else result.text
        if isinstance(raw, str):
            if len(raw) > 8 * _MAX_BYTES:
                raise ValueError("Provider response exceeds byte limit")
            if raw.lstrip().lower().startswith(("error:", "unexpected error:")):
                raise ValueError(self._redact(raw))
            try:
                raw = json.loads(raw)
                if isinstance(raw, str):  # FastMCP string content can be JSON encoded twice
                    raw = json.loads(raw)
            except (ValueError, TypeError):
                raise ValueError("Provider returned malformed JSON") from None
        if not isinstance(raw, (dict, list)):
            raise ValueError("Provider returned an unsupported payload")
        if isinstance(raw, dict) and (raw.get("error") or raw.get("isError")):
            raise ValueError(self._redact(raw.get("error") or "Provider tool error"))
        # Store only the digest of raw responses, never raw bodies or credentials.
        digest = hashlib.sha256(_bytes(raw)).hexdigest()
        receipts = getattr(self._local, "receipts", None)
        if receipts is not None:
            receipt = {"tool": tool, "sha256": digest, "arguments": args}
            if isinstance(raw, dict):
                sources = raw.get("meta", {}).get("sources", [])
                receipt["sources"] = [{"url": _url(s.get("url", "")), "fetchedAt": _clean(s.get("fetchedAt", "")),
                                       "cached": bool(s.get("cached", False)), "method": _clean(s.get("method", ""))}
                                      for s in sources[:10] if isinstance(s, dict)]
            receipts.append(receipt)
        return raw

    def search(self, query: str, *, provider: str | None = None, limit: int = 6,
               deadline_s: float | None = None) -> list[SearchHit]:
        """Curated catalog hits, then live discovery; ``deadline_s`` bounds the provider calls."""
        if not self._on or self._closed or not isinstance(query, str) or not query.strip():
            return []
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            return []
        try:
            previous = self._bounded(deadline_s)
        except Exception:
            return []
        try:
            return self._search(query, provider, limit)
        finally:
            self._local.deadline = previous

    def _search(self, query, provider, limit) -> list[SearchHit]:
        """Strong catalog matches first, then live FRED and Data360 search (English rendering of
        the query; Data360 pinned to the geographies the query names, else the world aggregate),
        then BIS/Treasury discovery, then weak catalog matches as last-resort hints.  A discovered
        or weak result whose title (catalog entries: title and keywords) shares no concept with the
        query ("Arms exports" for "global semiconductor sales") comes last, its note starting with
        ``OFF_CONCEPT_NOTE``."""
        selected = {provider.lower()} if isinstance(provider, str) else self._allowed
        selected &= self._allowed
        if not selected:
            return []
        query = query[:300]
        hits: dict[str, SearchHit] = {}
        unmatched: dict[str, SearchHit] = {}
        terms = None

        def add(sid, *fields):
            hits.setdefault(sid, SearchHit(sid, *fields))

        def add_live(sid, title, units, frequency, coverage, provider_id, hint, text=None):
            if sid in hits or sid in unmatched:
                return
            if terms is not None and catalog.shares_concept(terms, title if text is None else text) is False:
                unmatched[sid] = SearchHit(sid, title, units, frequency, coverage, provider_id,
                                           "; ".join(part for part in (OFF_CONCEPT_NOTE, hint) if part))
            else:
                hits[sid] = SearchHit(sid, title, units, frequency, coverage, provider_id, hint)

        def note(value):
            text = self._redact(value)
            return "" if text.strip().lower() in ("undefined", "null", "none") else text

        try:
            terms = catalog.concept_terms(query)
            ranked = [h for h in catalog.search_catalog_scored(query, provider=provider, limit=50, env=self._env)
                      if h.entry.provider in selected]
            for hit in ranked:
                if hit.strong:
                    e = hit.entry
                    add(e.series, e.title, e.units, e.frequency, "", e.provider, e.notes)
            if len(hits) >= limit:
                return list(hits.values())[:limit]
            english = catalog.english_query(query)
            if "fred" in selected and english and self._key("fred"):
                try:
                    payload = self._call("fred", "fred_search", {"search_text": english, "limit": limit, "offset": 0})
                    for row in payload.get("results", []):
                        parsed = parse_series_id("fred:" + str(row.get("id", "")))
                        if parsed:
                            add_live(":".join(parsed), self._redact(row.get("title")), self._redact(row.get("units")),
                                     _frequency(row.get("frequency")), self._redact(row.get("observation_range")),
                                     "fred", note(row.get("notes")))
                except Exception:
                    logger.warning("Official FRED search unavailable")
            if "wb" in selected and english and len(hits) < limit:
                try:
                    # Countries come from whole-word/ZH geography names only; Data360 marks
                    # coverage only for requested economies, so a query naming none asks for WLD.
                    geos = sorted(catalog.query_geographies(query)) or ["WLD"]
                    payload = self._call("wb", "data360_search_indicators",
                                         {"query": english, "limit": limit, "required_country": ";".join(geos)})
                    for row in payload.get("indicators", []):
                        covered = row.get("covers_country") or {}
                        for area in geos:
                            parsed = parse_series_id(f"wb:{row.get('idno', '')}/{area}") if covered.get(area) else None
                            if parsed:
                                add_live(":".join(parsed), self._redact(row.get("name")), "",
                                         _frequency(row.get("periodicity")), "", "wb",
                                         "Discovery metadata; fetch before citing")
                except Exception as exc:
                    if not re.search(r"(?i)no indicators found", str(exc)):  # Data360 reports an empty result as an error
                        logger.warning("Official Data360 search unavailable")
            if len(hits) < limit and "bis" in selected:
                try:
                    payload = self._call("bis", "search_dataflows", {"query": english or query, "limit": limit})
                    flows = {row.get("flow_ref") for row in payload.get("dataflows", [])}
                    for entry in catalog.CATALOG:
                        if entry.provider != "bis":
                            continue
                        flow = entry.native.split("/")[0]
                        if f"BIS,{flow},{catalog.BIS_FLOWS[flow]['version']}" in flows:
                            add_live(entry.series, entry.title, entry.units, entry.frequency, "", "bis",
                                     "Discovered flow; exact key from curated catalog", _entry_text(entry))
                except Exception:
                    logger.warning("Official BIS flow discovery unavailable")
            if len(hits) < limit and "usgov" in selected:
                try:
                    payload = self._call("usgov", "treasury_search_datasets", {"query": english or query})
                    endpoints = {row.get("endpoint") for row in (payload.get("data") or {}).get("items", [])}
                    for entry in catalog.CATALOG:
                        if entry.provider != "usgov" or not catalog.entry_available(entry, env=self._env):
                            continue
                        recipe = catalog.resolve_usgov_recipe(entry.native)
                        if recipe and recipe[1]["endpoint"] in endpoints:
                            add_live(entry.series, entry.title, entry.units, entry.frequency, "", "usgov",
                                     "Discovered endpoint; selected accounting recipe from curated catalog",
                                     _entry_text(entry))
                except Exception:
                    logger.warning("Official Treasury discovery unavailable")
            # Weak catalog matches (a topic word, partial coverage) are hints; results sharing no
            # concept with the query follow them.
            for hit in ranked:
                e = hit.entry
                add_live(e.series, e.title, e.units, e.frequency, "", e.provider, e.notes, _entry_text(e))
            # Flow/endpoint discovery supplies no arbitrary new series keys.
            # Every returned series still has a complete curated fetch recipe.
            return [*hits.values(), *(hit for sid, hit in unmatched.items() if sid not in hits)][:limit]
        except Exception:
            logger.warning("Official data search unavailable")
            return [*hits.values(), *(hit for sid, hit in unmatched.items() if sid not in hits)][:limit]

    def _request(self, series, start, end, transform, max_obs):
        if not self._on or self._closed:
            raise DataFailure("Data sources disabled or closed", "provider_unavailable", False)
        parsed = parse_series_id(series)
        if not parsed:
            if isinstance(series, str) and series.strip().lower().startswith("usgov:"):
                raise DataFailure("Unknown usgov recipe. Valid recipes: " + ", ".join(catalog.USGOV_RECIPES), "unknown_recipe")
            raise DataFailure("Invalid series ID; use data_search or the official catalog", "unknown_series")
        provider, native = parsed
        if provider not in self._allowed:
            raise DataFailure("Provider is not enabled", "provider_unavailable", False)
        native, _, suffix = native.partition("#")
        if transform is not None and suffix and transform != suffix:
            raise DataFailure("Conflicting transform and series suffix", "invalid_input")
        transform = suffix or transform or ""
        if transform not in ("", "yoy", "pct"):
            raise DataFailure("Unsupported transform; use yoy or pct", "unsupported_transform")
        if not isinstance(max_obs, int) or isinstance(max_obs, bool) or not 1 <= max_obs <= _MAX_ROWS:
            raise DataFailure("max_obs must be an integer from 1 to 5000", "invalid_input")
        sid = f"{provider}:{native}"
        entry = catalog.lookup(sid)
        frequency = entry.frequency if entry else ""
        if provider in ("bis", "imf"):
            flow, key = native.split("/")
            meta = catalog.BIS_FLOWS[flow] if provider == "bis" else catalog.imf_flow_info(flow)
            for dim, code in zip(meta["dims"], key.split(".")):
                if dim in ("FREQ", "FREQUENCY"):
                    frequency = _frequency(code)
        if provider == "wb":
            frequency = "A"
        if provider == "usgov":
            frequency = catalog.resolve_usgov_recipe(native)[1]["frequency"]
        today = self._today()
        try:
            # Publisher projection paths (WEO, GEP) run past today: by default request them
            # to the end of the sixth following year; history still counts back from today.
            projecting = _status_policy(sid) in ("weo_vintage", "gep_vintage") or bool(entry and "projections" in entry.topics)
            finish = _end_period(end) if end is not None else f"{int(today[:4]) + 6}-12-31" if projecting else today
            # Daily data become months. FRED aggregates the older months server-side (_fred_split),
            # so its daily series get the ten years monthly series get (enough h-step samples for
            # an empirical base rate) in two bounded pages; Treasury's unaggregated daily pages
            # keep two years.
            years = 25 if frequency == "A" else 2 if frequency == "D" and provider != "fred" else 10
            begin = _period(start) if start is not None else max("1900-01-01", _shift(min(finish, today), -12 * years))
            if start is None and frequency == "D":
                begin = begin[:8] + "01"  # daily data become months: never open on a partial first month
        except (ValueError, TypeError, OverflowError):
            raise DataFailure("start/end must be dates such as YYYY-MM-DD", "invalid_input") from None
        if self._backtest is not None:
            # Nothing after the cutoff, projections included (a current vintage's
            # projections were made after it).
            finish = min(finish, self._backtest.as_of_iso)
            if begin > finish:
                raise DataFailure("The requested window starts after the backtest cutoff "
                                  f"({self._backtest.as_of_iso})", "invalid_window")
        # Providers reject windows before their earliest data (USAspending: FY2008).
        floor = _min_start(provider, sid, native)
        begin = max(begin, floor) if floor else begin
        if begin > finish or date.fromisoformat(begin).year < 1900 or date.fromisoformat(finish).year > 2100:
            raise DataFailure("Invalid start/end window (supported years 1900–2100"
                              + (f"; no data before {floor}" if floor else "") + ")", "invalid_window")
        warmup = 12 if transform == "yoy" else {"A": 12, "Q": 3, "M": 1, "D": 1, "W": 1}.get(frequency, 12) if transform == "pct" else 0
        if frequency == "W" and transform == "yoy":
            raise DataFailure("Weekly yoy is unsupported without a verified week-alignment policy", "unsupported_transform")
        fetch_start = max("1900-01-01", floor or "", _shift(begin, -warmup)) if warmup else begin
        canonical = sid + ("#" + transform if transform else "")
        identity = [NORMALIZATION_POLICY_VERSION, canonical, begin, finish, max_obs]
        if self._backtest is not None:
            identity.append(self._backtest.tag)
        key = hashlib.sha256(_bytes(identity)).hexdigest()
        request = {"series": canonical, "base": sid, "provider": provider, "native": native, "start": begin, "end": finish,
                   "fetch_start": fetch_start, "transform": transform, "max_obs": max_obs, "frequency": frequency, "key": key,
                   "default_window": start is None}
        if self._backtest is not None and provider == "fred":
            request["vintage"] = self._backtest.as_of_iso
        return request

    def _cached(self, req):
        key = req["key"]
        with self._lock:
            cached = self._memory.get(key)
        if cached is None:
            try:
                body = json.loads(_read(_safe_path(self._cache_dir, key + ".json")))
                if body.get("key") != key or hashlib.sha256(_bytes(body["series"])).hexdigest() != body.get("sha256"):
                    return None
                cached = (float(body["stored_at"]), body["series"])
            except (ValueError, TypeError, OSError, KeyError):
                return None
        timestamp, data = cached
        if not isinstance(data, dict) or not isinstance(data.get("provenance"), dict) or data["provenance"].get("normalization_policy_version") != NORMALIZATION_POLICY_VERSION:
            return None
        ttl = {"D": 21600, "W": 21600, "A": 86400}.get(data.get("provenance", {}).get("native_frequency") or data.get("frequency"), 43200)
        if not 0 <= self._clock() - timestamp <= ttl or data.get("series") != req["series"]:
            return None
        try:
            result = Series.from_dict(data)
            result.route = "cache"
            return result
        except (ValueError, TypeError):
            return None

    def _save_cache(self, req, result):
        timestamp, data = self._clock(), result.to_dict()
        with self._lock:
            self._memory.pop(req["key"], None)
            self._memory[req["key"]] = timestamp, data
            while len(self._memory) > _MEMORY_MAX:
                self._memory.pop(next(iter(self._memory)))
        try:
            _atomic(_safe_path(self._cache_dir, req["key"] + ".json"), _bytes({"key": req["key"], "stored_at": timestamp, "series": data, "sha256": hashlib.sha256(_bytes(data)).hexdigest()}))
        except (ValueError, OSError):
            logger.warning("Official data cache unavailable; fetched result retained")

    def _bounded(self, deadline_s: float | None):
        """Install a thread-local deadline for one call; returns the one it replaced.

        ``None`` keeps the caller's current deadline (unbounded when none). A
        nested bound never extends an outer one.
        """
        previous = getattr(self._local, "deadline", None)
        if deadline_s is None:
            return previous
        if isinstance(deadline_s, bool) or not isinstance(deadline_s, (int, float)) or not math.isfinite(deadline_s):
            raise DataFailure("deadline_s must be a finite number of seconds", "invalid_input")
        if deadline_s <= 0:
            raise TimeoutError("Data request deadline exceeded")
        deadline = time.monotonic() + deadline_s
        self._local.deadline = deadline if previous is None else min(previous, deadline)
        return previous

    def get(self, series: str, *, start: str | None = None, end: str | None = None,
            transform: str | None = None, max_obs: int = 240, deadline_s: float | None = None) -> Series | DataError:
        """One normalized series or a DataError; ``deadline_s`` bounds every provider wait."""
        try:
            previous = self._bounded(deadline_s)
        except Exception as exc:
            return self._error(series, exc)
        try:
            return self._get(series, start, end, transform, max_obs)
        finally:
            self._local.deadline = previous

    def _get(self, series, start, end, transform, max_obs) -> Series | DataError:
        try:
            req = self._request(series, start, end, transform, max_obs)
            with self._lock:
                lock = self._locks.setdefault(req["key"], threading.Lock())
                if len(self._locks) > _MEMORY_MAX:
                    # Long-lived processes (backend, monitor) see unbounded windows; idle
                    # single-flight locks are recreated on demand.
                    for key in [k for k, v in self._locks.items() if k != req["key"] and not v.locked()]:
                        del self._locks[key]
            left = self._remaining()
            if not lock.acquire(timeout=left if left is not None else -1):
                raise TimeoutError("Data request deadline exceeded")
            try:
                cached = self._cached(req)
                self._remaining()
                if cached:
                    return cached
                semaphore = self._semaphores[req["provider"]]
                left = self._remaining()
                if not semaphore.acquire(timeout=left):
                    raise TimeoutError("Data request deadline exceeded")
                try:
                    # A batched request may have populated this key while we
                    # waited for the same provider's admission slot.
                    cached = self._cached(req)
                    self._remaining()
                    if cached:
                        return cached
                    self._local.receipts = []
                    if req["provider"] == "bls":
                        result = self._bls_batch([req])[req["series"]]
                    else:
                        result = getattr(self, "_fetch_" + req["provider"])(req)
                    if isinstance(result, DataError):
                        return result
                    result = self._finish(req, result)
                    self._remaining()
                    self._save_cache(req, result)
                    return result
                finally:
                    semaphore.release()
            finally:
                lock.release()
        except Exception as exc:
            return self._error(series, exc)

    def get_many(self, ids: Sequence[str], *, deadline_s: float, **kw) -> dict[str, Series | DataError]:
        """Each id's Series or DataError within one deadline; never raises."""
        try:
            members = [] if isinstance(ids, (str, bytes)) or ids is None else list(ids)
        except TypeError:
            members = []
        invalid = {_clean(m, 200) or "invalid": self._error(m, DataFailure("Series IDs must be strings", "invalid_input"))
                   for m in members if not isinstance(m, str)}
        ids = list(dict.fromkeys(m for m in members if isinstance(m, str)))[:200]
        unexpected = sorted(set(kw) - {"start", "end", "transform", "max_obs"})
        if unexpected:
            failure = DataFailure("Unsupported argument(s): " + ", ".join(_clean(k, 40) for k in unexpected[:5]), "invalid_input")
            return {**invalid, **{sid: self._error(sid, failure) for sid in ids}}
        if isinstance(deadline_s, bool) or not isinstance(deadline_s, (float, int)) or not math.isfinite(deadline_s) or deadline_s <= 0:
            return {**invalid, **{sid: self._error(sid, TimeoutError("Data request deadline exceeded")) for sid in ids}}
        deadline = time.monotonic() + deadline_s
        output, bls = {}, []
        ordinary = []
        for sid in ids:
            try:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Data request deadline exceeded")
                req = self._request(sid, kw.get("start"), kw.get("end"), kw.get("transform"), kw.get("max_obs", 240))
                # Disk cache work belongs in deadline-bound workers, never on
                # the caller's return-latency path.
                if req["provider"] == "bls":
                    bls.append((sid, req))
                else:
                    ordinary.append(sid)
            except Exception as exc:
                output[sid] = self._error(sid, exc)

        def one(sid):
            self._local.deadline = deadline
            try:
                return {sid: self.get(sid, **kw)}
            finally:
                self._local.deadline = None

        def batch(items):
            self._local.deadline, self._local.receipts = deadline, []
            acquired = False
            try:
                acquired = self._semaphores["bls"].acquire(timeout=max(0, deadline - time.monotonic()))
                if not acquired:
                    raise TimeoutError("Data request deadline exceeded")
                values = {}
                missing = []
                for sid, req in items:
                    self._remaining()
                    cached = self._cached(req)
                    self._remaining()
                    if cached:
                        values[sid] = cached
                    else:
                        missing.append((sid, req))
                raw = self._bls_batch([r for _, r in missing]) if missing else {}
                for sid, req in missing:
                    value = raw[req["series"]]
                    if not isinstance(value, DataError):
                        value = self._finish(req, value)
                        self._remaining()
                        self._save_cache(req, value)
                    values[sid] = value
                return values
            except Exception as exc:
                return {sid: self._error(sid, exc) for sid, _ in items}
            finally:
                if acquired:
                    self._semaphores["bls"].release()
                self._local.deadline = None

        pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="official-data")
        jobs = [pool.submit(one, sid) for sid in ordinary]
        jobs += [pool.submit(batch, bls[i:i + 25]) for i in range(0, len(bls), 25)]
        done, pending = wait(jobs, timeout=max(0, deadline - time.monotonic()))
        for future in done:
            try:
                output.update(future.result())
            except Exception:
                logger.warning("Official data batch unavailable")
        for future in pending:
            future.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
        return {**invalid, **{sid: output.get(sid) or self._error(sid, TimeoutError("Data request deadline exceeded")) for sid in ids}}

    def _base(self, req, **metadata):
        entry = catalog.lookup(req["base"])
        values = {name: getattr(entry, name) for name in ("title", "title_zh", "units", "frequency", "seasonal_adjustment", "geography", "source_url", "notes")} if entry else {}
        values.update({k: v for k, v in metadata.items() if v not in (None, "")})
        if entry is not None and entry.title:
            # Curated titles name the economy and stay stable across provider wording; the
            # provider's own title is kept in provenance.
            provider_title = _clean(metadata.get("title") or "")
            values["title"], values["title_zh"] = entry.title, entry.title_zh or values.get("title_zh", "")
            if provider_title and provider_title != entry.title:
                values["provenance"] = {**values.get("provenance", {}), "provider_title": provider_title}
        return Series(series=req["base"], provider=req["provider"], provider_name=catalog.provider_name(req["provider"], req["native"]),
                      route="mcp", retrieved_at=datetime.fromtimestamp(self._clock(), timezone.utc).isoformat(), **values)

    def _monthly(self, req, s) -> tuple[list[Observation], dict]:
        """Native daily points as calendar months, with each month's coverage in periods.

        Stocks and policy targets (catalog aggregation "eop") keep the month's last value;
        other series average the available days. A month is complete only when the request
        covers all of it, the provider's history does too (_LATE_FIRST_DAY_DAYS), it ended
        before retrieval and later native data (or two weeks) show it settled; any other month
        is a partial, 'preliminary' period. Provenance keeps the last native daily point,
        which forecast questions usually reference.
        """
        method = _aggregation(req)
        today = date.fromisoformat(self._today())
        months: dict[str, list[Observation]] = {}
        for o in s.observations:
            months.setdefault(o.date[:7] + "-01", []).append(o)
        last_native = s.observations[-1].date if s.observations else ""
        first_native = s.observations[0].date if s.observations else ""
        observations, periods = [], {}
        for start, rows in sorted(months.items()):
            end = (date.fromisoformat(_shift(start, 1)) - timedelta(days=1)).isoformat()
            covered = (max(start, req["fetch_start"]), min(end, req["end"]))
            if start == first_native[:8] + "01" and (
                    date.fromisoformat(first_native) - date.fromisoformat(covered[0])).days > _LATE_FIRST_DAY_DAYS:
                covered = (first_native, covered[1])  # the provider's history opens inside this month
            settled = last_native > end or today > date.fromisoformat(end) + timedelta(days=14)
            complete = covered == (start, end) and end < today.isoformat() and settled
            values = [o.value for o in rows if o.value is not None]
            value = (values[-1] if method == "eop" else sum(values) / len(values)) if values else None
            flag = ";".join(sorted({o.flag for o in rows if o.flag})) if complete else "preliminary"
            observations.append(Observation(start, value, flag))
            periods[start] = {"calendar": "calendar_month", "label": start[:7], "start": start, "end": end,
                              "covered_start": covered[0], "covered_end": covered[1], "complete": complete}
        latest = next((o for o in reversed(s.observations) if o.value is not None), None)
        words = "end-of-month values (last available daily observation)" if method == "eop" else "means of available daily observations"
        s.frequency = "M"
        s.provenance.update({"aggregation": f"Monthly {words}; a month still open at retrieval is partial",
                             "aggregation_method": method, "resolution_safe": False})
        if latest is not None:
            s.provenance["latest_daily"] = {"date": latest.date, "value": latest.value}
        # First, so a long provider note cannot truncate it away.
        s.notes = _clean(f"Daily data aggregated to monthly {words}; the open month is partial. {s.notes}")
        return observations, periods

    def _cut_at_backtest(self, req, s) -> None:
        """Backtest mode: keep the observations known at the cutoff (an as-of
        vintage proves it; a current revision needs its period to have ended,
        plus a publication lag in strict mode) and record the basis."""
        policy = self._backtest
        vintage = bool(req.get("vintage")) and s.provenance.get("vintage_dates") == req["vintage"]
        periods = s.provenance.get("periods") if isinstance(s.provenance.get("periods"), dict) else {}
        kept = [o for o in s.observations
                if backtest_cutoff.observation_admitted(o.date, s.frequency, policy, vintage=vintage,
                                                        end=(periods.get(o.date) or {}).get("end"))]
        s.provenance["backtest"] = {"as_of": policy.as_of_iso, "strict": policy.strict,
                                    "basis": "as_of_vintage" if vintage else "current_revision",
                                    "dropped_observations": len(s.observations) - len(kept)}
        s.observations = kept
        if not kept:
            raise DataFailure(f"No observations were known at the backtest cutoff ({policy.as_of_iso})",
                              "invalid_window")

    def _finish(self, req, s):
        native_frequency = s.frequency
        if not s.observations:
            raise DataFailure("Provider returned no observations for the requested series", "not_found")
        periods = s.provenance.get("periods", {})
        def intersects(o, start):
            return o.date <= req["end"] and periods.get(o.date, {}).get("end", o.date) >= start
        s.observations = [o for o in s.observations if intersects(o, req["fetch_start"])]
        if self._backtest is not None:
            self._cut_at_backtest(req, s)
        if s.frequency == "D":
            s.observations, periods = self._monthly(req, s)
        s.provenance["native_frequency"] = native_frequency
        if req["transform"]:
            if s.frequency == "W" and req["transform"] == "yoy":
                raise DataFailure("Weekly yoy is unsupported without a verified week-alignment policy", "unsupported_transform")
            if s.series == "usgov:spending/total" and any(not periods.get(o.date, {}).get("complete") for o in s.observations):
                raise DataFailure("Cannot transform partial fiscal-year aggregates", "unsupported_transform")
            original = {o.date: o for o in s.observations}
            transformed = []
            for o in s.observations:
                if req["transform"] == "yoy":
                    before = _shift(o.date, -12)
                elif s.frequency == "W":
                    before = (date.fromisoformat(o.date) - timedelta(days=7)).isoformat()
                else:
                    step = {"M": -1, "Q": -3, "A": -12}.get(s.frequency)
                    if step is None:
                        raise DataFailure("Cannot transform a series of unknown frequency", "unsupported_transform")
                    before = _shift(o.date, step)
                prior = original.get(before)
                value = (o.value / prior.value - 1) * 100 if o.value is not None and prior and prior.value not in (None, 0) else None
                flag = ";".join(sorted({v for v in (o.flag, prior.flag if prior else "") if v}))
                transformed.append(Observation(o.date, value, flag))
            s.provenance["original_units"] = s.units
            s.units = "Percent change from year ago" if req["transform"] == "yoy" else "Percent change from previous period"
            s.observations = transformed
            s.transform, s.series = req["transform"], req["series"]
        admitted_count = sum(intersects(o, req["start"]) for o in s.observations)
        s.observations = [o for o in s.observations if intersects(o, req["start"])][-req["max_obs"]:]
        if not s.observations:
            raise DataFailure("No observations in requested window", "invalid_window")
        receipts = getattr(self._local, "receipts", [])
        s.provenance.setdefault("metadata_origin", "provider_and_curated_catalog")
        if periods:
            s.provenance["periods"] = {o.date: periods[o.date] for o in s.observations if o.date in periods}
        if isinstance(s.provenance.get("raw_status"), dict):
            s.provenance["raw_status"] = {o.date: s.provenance["raw_status"][o.date] for o in s.observations if o.date in s.provenance["raw_status"]}
        s.provenance.update({"normalization_policy_version": NORMALIZATION_POLICY_VERSION,
                             "intentional_delivery_trim": admitted_count > len(s.observations),
                             "requested_start": req["start"], "requested_end": req["end"],
                             "tool_responses": receipts, "response_sha256": hashlib.sha256(_bytes(receipts)).hexdigest(),
                             "delivered_start": s.observations[0].date, "delivered_end": s.observations[-1].date,
                             "retrieval_route": s.route})
        # Redact all provider-originated strings before any disk/cache write. Observation
        # dates and values are validated data, never provider prose, so they are not scrubbed.
        def scrub(value):
            if isinstance(value, str):
                text = self._scrub(value)
                return _clean(text, max(len(text), 1))
            if isinstance(value, list):
                return [scrub(v) for v in value]
            if isinstance(value, dict):
                return {k: "[redacted]" if _SECRET.search(k) else v if k == "observations" else scrub(v) for k, v in value.items()}
            return value
        return Series.from_dict(scrub(s.to_dict()))

    def _fetch_fred(self, req):
        """FRED API route while a key works, else the keyless fredgraph CSV.

        A rejected key switches this process to CSV (providers() reports key_invalid), and so
        does a FRED MCP server that cannot run (not built, crashed past its restart): the CSV
        route needs neither. A rate limit, 5xx or timeout falls back to CSV for curated ids
        only (their catalog title and units stand in for the API metadata); other ids fail
        retryable.
        """
        entry = catalog.lookup(req["base"])
        daily = bool(entry and entry.frequency == "D")
        reason, failure = ("key_invalid" if self._key_rejected("fred") else ""), None
        if self._key("fred"):
            try:
                series = self._fred_window(req, self._fred_api, daily)
                if entry is None:
                    self._fred_geography(req, series)
                return series
            except (ValueError, TimeoutError) as exc:  # DataFailure is a ValueError
                code = _failure_class(exc)[0]
                if code == "key_invalid":
                    self._reject_key("fred")
                    reason = code
                elif self._server_down("fred"):
                    reason, failure = "provider_unavailable", exc
                elif code in _FRED_FALLBACK_CODES and entry is not None:
                    reason, failure = code, exc
                else:
                    raise
            self._local.receipts = []  # receipts describe the delivered route only
        try:
            series = self._fred_window(req, self._fred_csv, daily)
        except Exception as exc:
            if failure is not None:
                raise DataFailure(f"{_clean(failure, 150)}; the keyless FRED CSV fallback failed too "
                                  f"({_clean(exc, 100)})", reason, True) from None
            raise
        if reason:
            series.provenance["fallback_reason"] = reason
        return series

    def _fred_window(self, req, fetch, daily: bool):
        """One native request, or for a long native-daily window FRED's own monthly aggregation
        (catalog avg/eop) for older months plus native days for the latest months, so the open
        month stays partial and the last daily value is kept."""
        split = ""
        if daily:
            split = self._fred_split(req)
        if not split:
            try:
                return fetch(req, req["fetch_start"], req["end"], "")
            except _DailyOverflow:
                split = self._fred_split(req)
                if not split:
                    raise DataFailure("FRED history exceeds bound; narrow start/end", "invalid_window") from None
        method = _aggregation(req)
        start = req["fetch_start"]
        first = start if start.endswith("-01") else _shift(start[:8] + "01", 1)  # whole months only
        recent = fetch(req, split, req["end"], "")
        recent.frequency = recent.frequency or "D"  # split only for native-daily data
        if first < split:
            older = fetch(req, first, (date.fromisoformat(split) - timedelta(days=1)).isoformat(), method)
            if any(o.date[8:] != "01" or o.date >= split for o in older.observations):
                raise ValueError("FRED monthly aggregation returned non-month periods")
            recent.observations = older.observations + recent.observations
            words = "end-of-month values" if method == "eop" else "monthly means"
            recent.provenance["server_aggregation"] = {
                "method": method, "through": (date.fromisoformat(split) - timedelta(days=1)).isoformat(),
                "route": recent.route, "request": older.api_url}
            recent.notes = _clean(f"Months before {split[:7]} are FRED's own {words}. {recent.notes}")
        return recent

    def _fred_geography(self, req, series) -> None:
        """Geography of a FRED series outside the catalog, from FRED's own tags: the exact id
        among series tagged 'nation' and 'usa' is a United States national series. A FRED title
        that names no economy (US national series, but also the Nikkei 225) never decides it.
        Best effort and bounded to half the time left (at most _FRED_TAGS_S), so the lookup can
        never cost the fetched series its deadline; any other answer or failure leaves the
        geography unknown."""
        if series.geography:
            return
        args = {"search_text": req["native"], "search_type": "series_id", "tag_names": "nation;usa", "limit": 25}
        try:
            left = self._remaining()
            previous = self._bounded(_FRED_TAGS_S if left is None else min(_FRED_TAGS_S, left / 2))
            try:
                payload = self._call("fred", "fred_search", args)
            finally:
                self._local.deadline = previous
            results = payload.get("results") if isinstance(payload, dict) else None
            if isinstance(results, list) and any(isinstance(r, dict) and r.get("id") == req["native"] for r in results):
                series.geography = "USA"
                series.provenance["geography_basis"] = "FRED series tags: nation, usa"
        except Exception:  # enrichment never fails a fetched series
            logger.info("Official data: FRED geography tags unavailable for %s", req["native"])

    @staticmethod
    def _fred_split(req) -> str:
        """First day of the native-daily part of a daily window, else '': a window too long for one
        daily page, or the ten-year default window (no start given), keeps native days for the
        latest _FRED_RECENT_MONTHS months only; an explicit window that fits one page is not split."""
        span = (date.fromisoformat(req["end"]) - date.fromisoformat(req["fetch_start"])).days
        if span <= _FRED_DAILY_SPAN_DAYS and not req.get("default_window"):
            return ""
        split = _shift(req["end"][:8] + "01", -_FRED_RECENT_MONTHS)
        return split if split > req["fetch_start"] else ""

    def _fred_api(self, req, start: str, end: str, method: str):
        native = req["native"]
        args = {"series_id": native, "observation_start": start, "observation_end": end,
                "units": "lin", "sort_order": "desc", "offset": 0, "limit": _MAX_ROWS}
        if method:
            args.update(frequency="m", aggregation_method=method)
        if req.get("vintage"):
            # Backtest mode: the values as published on the as-of date (ALFRED).
            args["vintage_dates"] = req["vintage"]
        payload = self._call("fred", "fred_get_series", args)
        if payload.get("series_id") != native or not isinstance(payload.get("data"), list):
            raise ValueError("FRED response series identity mismatch")
        count, offset, limit = (payload.get(k) for k in ("total_observations", "data_offset", "data_limit"))
        if any(not isinstance(v, int) or isinstance(v, bool) for v in (count, offset, limit)) or count < 0 or offset != 0 or limit != _MAX_ROWS:
            raise ValueError("FRED native pagination metadata is invalid")
        if count > _MAX_ROWS:
            if not method and _frequency(payload.get("frequency")) == "D":
                raise _DailyOverflow("FRED daily history exceeds one page", "invalid_window")
            raise DataFailure("FRED history exceeds bound; narrow start/end", "invalid_window")
        if len(payload["data"]) != count:
            raise ValueError("FRED native page is incomplete")
        observations = [Observation(r["date"], r["value"]) for r in payload["data"]]
        entry = catalog.lookup(req["base"])
        metadata = {"title": payload.get("title"), "units": payload.get("units"), "frequency": _frequency(payload.get("frequency")),
                    "seasonal_adjustment": _seasonal(payload.get("seasonal_adjustment"))}
        if metadata["units"] in ("Value", "Unknown", "Transformed (lin)"):
            metadata["units"] = ""
        if metadata["title"] == f"FRED Series: {native}":
            metadata["title"] = ""
        authority = {k: "provider" if v else "curated_catalog" if entry and getattr(entry, k) else "unknown" for k, v in metadata.items()}
        return self._base(req, title=metadata["title"], units=metadata["units"],
                          frequency=_frequency(payload.get("frequency")), seasonal_adjustment=_seasonal(payload.get("seasonal_adjustment")),
                          observations=observations, source_url=f"https://fred.stlouisfed.org/series/{native}",
                          api_url="https://api.stlouisfed.org/fred/series/observations?" + urlencode(args),
                          # Curated pitfalls outrank FRED's release boilerplate (kept in provenance),
                          # so the API and CSV routes describe a curated series alike.
                          notes="" if entry is not None and entry.notes else _clean(payload.get("notes")),
                          provenance={"metadata_fields": authority, "native_complete": True, "native_count": count,
                                      **({"provider_notes": _clean(payload.get("notes"))} if entry is not None and entry.notes else {}),
                                      **({"vintage_dates": req["vintage"]} if req.get("vintage") else {}),
                                      "vintage_status": (f"as published on {req['vintage']} (FRED vintage_dates)" if req.get("vintage")
                                                         else "not supplied by native handler"),
                                      "numeric_lexemes": "native handler parses floats; null may also represent invalid upstream numeric text"})

    def _fred_csv(self, req, start: str, end: str, method: str):
        params = {"id": req["native"], "cosd": start, "coed": end}
        if method:
            params.update(fq="Monthly", fam=method)
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?" + urlencode(params)
        left = self._remaining()
        raw = self._http(url, timeout=min(left, 15) if left is not None else 15)
        self._remaining()
        if isinstance(raw, str):
            raw = raw.encode()
        if not isinstance(raw, bytes) or len(raw) > _MAX_BYTES:
            raise ValueError("FRED CSV response exceeds byte limit or has invalid type")
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        if reader.fieldnames not in (["observation_date", req["native"]], ["DATE", req["native"]]):
            raise ValueError("FRED CSV header does not match requested series")
        rows = []
        for row in reader:
            if None in row or None in row.values():
                raise ValueError("FRED CSV has malformed rows")
            rows.append(Observation(row[reader.fieldnames[0]], row[req["native"]]))
            if len(rows) > _MAX_ROWS:
                days = (date.fromisoformat(rows[-1].date) - date.fromisoformat(rows[0].date)).days
                if not method and days <= 3 * len(rows):  # business-day or 7-day spacing
                    raise _DailyOverflow("FRED CSV daily history exceeds one page", "invalid_window")
                raise DataFailure("FRED CSV observation limit exceeded; narrow start/end", "invalid_window")
        receipts = getattr(self._local, "receipts", None)
        if receipts is not None:
            receipts.append({"tool": "fred_csv", "sha256": hashlib.sha256(raw).hexdigest()})
        series = self._base(req, observations=rows, source_url=f"https://fred.stlouisfed.org/series/{req['native']}", api_url=url,
                            provenance={"metadata_origin": "curated_catalog" if catalog.lookup(req["base"]) else "unknown",
                                        "vintage_status": "not available in keyless CSV"})
        series.route = "fred_csv"
        if not series.title:
            series.title = "FRED series " + req["native"]
        return series

    def _bls_quota(self):
        if self._key("bls"):
            return
        # flock serializes reservations across API instances/processes; reserve
        # before dispatch, so crashes cannot refund an already sent request.
        import fcntl
        with _QUOTA_LOCK:
            lock_path = _safe_path(self._cache_dir, "bls-quota.lock")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "a+b") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX)
                path = _safe_path(self._cache_dir, "bls-quota.json")
                today = datetime.fromtimestamp(self._clock(), timezone.utc).date().isoformat()
                value = {"day": today, "count": 0}
                if path.exists():
                    try:
                        old = json.loads(_read(path, 4096))
                        if not isinstance(old.get("count"), int) or isinstance(old["count"], bool) or old["count"] < 0:
                            raise ValueError("Invalid quota")
                        if old.get("day") == today:
                            value = old
                    except (ValueError, TypeError, KeyError):
                        raise DataFailure("BLS quota record corrupt; quota cannot safely be established", "provider_unavailable", False) from None
                if value["count"] >= 20:
                    raise DataFailure("BLS keyless daily quota reached (20 requests); retry tomorrow", "quota_exhausted")
                value["count"] += 1
                _atomic(path, _bytes(value))

    def _bls_call(self, args):
        """One get_multiple_series request. A rejected registration key respawns the BLS server
        without it (hub.restart_without) and the request is retried once under the keyless quota."""
        keyed = bool(self._key("bls"))
        self._bls_quota()
        payload = self._call("bls", "get_multiple_series", args)
        if payload.get("status") == "REQUEST_SUCCEEDED":
            return payload
        failure = ValueError(self._redact("BLS request failed: " + str(payload.get("message", "invalid status"))))
        restart = getattr(self._get_hub(), "restart_without", None)
        if not keyed or _failure_class(failure)[0] != "key_invalid" or restart is None:
            raise failure
        self._reject_key("bls")
        restart("bls", ("BLS_API_KEY",))  # False when a concurrent request already respawned it
        self._remaining()
        self._bls_quota()
        payload = self._call("bls", "get_multiple_series", args)
        if payload.get("status") != "REQUEST_SUCCEEDED":
            raise ValueError(self._redact("BLS keyless retry failed: " + str(payload.get("message", "invalid status"))))
        return payload

    def _bls_messages(self, payload, requested, invalid: set) -> list[str]:
        """Per-series BLS notices returned for provenance: 'No Data Available for Series X Year: Y'
        (not yet published or before coverage) and 'Unable to get Catalog Data for series X'
        (descriptive metadata only; curated titles and units apply). 'Invalid Series for Series X'
        marks X invalid in ``invalid`` without failing the batch; any other message fails it."""
        messages = payload.get("message") or []
        notices = []
        for text in [messages] if isinstance(messages, str) else messages:
            text = str(text).strip()
            benign = (re.fullmatch(r"No Data Available for Series (\S+) Year: \d{4}", text)
                      or re.fullmatch(r"Unable to get Catalog Data for series (\S+)", text, re.I))
            bad = re.fullmatch(r"(?:Invalid Series for Series|Series does not exist for Series) (\S+)", text)
            if benign and benign[1] in requested:
                notices.append(_clean(text, 120))
            elif bad and bad[1] in requested:
                invalid.add(bad[1])
            elif text:
                raise ValueError(self._redact("BLS response has warnings: " + text))
        return notices

    def _bls_batch(self, requests):
        # Grouping by explicit windows retains true 25-ID batches even when
        # callers use mixed native frequencies/default windows.
        groups = {}
        for req in requests:
            groups.setdefault((req["fetch_start"][:4], req["end"][:4]), []).append(req)
        output = {}
        for (first, last), group in groups.items():
            gathered = {r["native"]: [] for r in group}
            metadata, raw_status, omitted, chunks = {}, {r["native"]: {} for r in group}, set(), []
            invalid: set[str] = set()
            high = int(last)
            while high >= int(first):
                low = max(int(first), high - 9)
                self._remaining()
                args = {"series_ids": list(gathered), "start_year": str(low), "end_year": str(high)}
                payload = self._bls_call(args)
                notices = self._bls_messages(payload, gathered, invalid)
                rows = payload.get("Results", {}).get("series")
                if not isinstance(rows, list):
                    raise ValueError("BLS returned no series records")
                seen = set()
                for row in rows:
                    native = row.get("seriesID")
                    if native not in gathered or native in seen:
                        raise ValueError("BLS returned unexpected or duplicate series ID")
                    seen.add(native)
                    metadata[native] = row.get("catalog") or {}
                    if not isinstance(row.get("data"), list):
                        raise ValueError("BLS series record has no explicit data list")
                    for item in row["data"]:
                        period = str(item.get("period", ""))
                        if period in ("M13", "Q05", "S03"):
                            continue  # annual summaries cannot mix with native periods
                        if not low <= int(item["year"]) <= high:
                            raise ValueError("BLS returned data outside requested year chunk")
                        if not re.fullmatch(r"M(?:0[1-9]|1[0-2])|Q0[1-4]|A01", period):
                            raise ValueError("BLS period frequency is unsupported")
                        month = int(period[1:]) if period[0] == "M" else (int(period[1:]) - 1) * 3 + 1 if period[0] == "Q" else 1
                        notes = [{"code": _clean(f.get("code", ""), 30), "text": _clean(f.get("text", ""))} for f in item.get("footnotes", []) if isinstance(f, dict) and (f.get("code") or f.get("text"))]
                        # Only code P marks a status (preliminary). Other footnotes are notes on a
                        # published value (R revised, numbered notes such as CPS population
                        # controls or a lapse in appropriations) and stay in raw_status.
                        flag_values = ["preliminary" if f["code"].upper() == "P" else "observed" for f in notes]
                        flag = _status_flag(";".join(flag_values)) if flag_values else "observed"
                        normalized_date = date(int(item["year"]), month, 1).isoformat()
                        raw_status[native][normalized_date] = notes
                        gathered[native].append((Observation(normalized_date, item.get("value"), flag), period[0]))
                omitted.update(set(gathered) - seen)
                chunk = {"start_year": low, "end_year": high, "returned_ids": sorted(seen)}
                if notices:
                    chunk["notices"] = notices
                chunks.append(chunk)
                high = low - 1
            for req in group:
                if req["native"] in invalid:
                    output[req["series"]] = self._error(req["series"], DataFailure("BLS reports an invalid series ID", "unknown_series"))
                    continue
                if req["native"] in omitted:
                    output[req["series"]] = self._error(req["series"], DataFailure("BLS omitted the requested series from at least one year chunk", "not_found"))
                    continue
                rows = gathered[req["native"]]
                if not rows:
                    output[req["series"]] = self._error(req["series"], DataFailure("BLS returned no observations for this series", "not_found"))
                    continue
                frequencies = {freq for _, freq in rows}
                if len(frequencies) != 1 or req["frequency"] and req["frequency"] not in frequencies:
                    raise ValueError("BLS returned conflicting native frequencies")
                meta = metadata.get(req["native"], {})
                output[req["series"]] = self._base(req, observations=[o for o, _ in rows], frequency=next(iter(frequencies)),
                                                      title=meta.get("series_title"), units=meta.get("measure_data_type"),
                                                      source_url=f"https://data.bls.gov/timeseries/{req['native']}",
                                                      api_url="https://api.bls.gov/publicAPI/v2/timeseries/data/",
                                                      provenance={"raw_status": raw_status[req["native"]], "chunks": chunks, "native_complete": True,
                                                                  "annual_summaries": "Excluded M13/Q05/S03", "vintage_status": "not supplied", "request_method": "POST", "series_ids": [req["native"]]})
        return output

    def _sdmx_rows(self, req, payload, dimensions):
        if payload.get("truncated"):
            raise ValueError("Provider response is truncated; narrow the requested window")
        rows = payload.get("rows")
        if not isinstance(rows, list) or len(rows) > _MAX_ROWS:
            raise ValueError("Invalid or excessive SDMX rows")
        observations, attributes, raw_status = [], {}, {}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Invalid SDMX row")
            lower = {k.upper(): v for k, v in row.items()}
            for name, expected in dimensions.items():
                actual = lower.get(name.upper())
                if actual is None or str(actual).upper() != expected.upper():
                    raise ValueError("SDMX returned a different or missing series dimension")
            period = _native_period(lower["TIME_PERIOD"], req["frequency"])
            if "OBS_VALUE" not in lower:
                raise ValueError("SDMX returned no observation value")
            status = str(lower.get("OBS_STATUS", "") or "")
            observations.append(Observation(period, lower["OBS_VALUE"], status))
            if status:
                raw_status[period] = [{"code": status, "text": _clean(lower.get("OBS_STATUS_LABEL", ""))}]
            for key in ("UNIT_MEASURE", "UNIT_MEASURE_LABEL", "UNIT_MULT", "DECIMALS", "TITLE", "COMPILATION"):
                if key in lower and lower[key] is not None:
                    attributes.setdefault(key, set()).add(str(lower[key]))
        if any(len(attributes.get(k, [])) > 1 for k in ("UNIT_MEASURE", "UNIT_MULT")):
            raise ValueError("SDMX mixed units or scale within series")
        return observations, {**{k: sorted(v) for k, v in attributes.items()}, "raw_status": raw_status}

    def _fetch_bis(self, req):
        flow, key = req["native"].split("/")
        meta = catalog.BIS_FLOWS[flow]
        dims = dict(zip(meta["dims"], key.split(".")))
        ref = f"BIS,{flow},{meta['version']}"
        args = {"flow_ref": ref, "key": key, "start_period": req["fetch_start"], "end_period": req["end"], "limit": _MAX_ROWS}
        try:
            payload = self._call("bis", "fetch_dataset", args)
        except _ToolFailure as exc:
            failure = _bis_failure(exc.detail or str(exc), req)
            if failure is None:
                raise
            raise failure from None
        if payload.get("flow_ref") != ref:
            raise ValueError("BIS returned a different flow/version")
        observations, attributes = self._sdmx_rows(req, payload, dims)
        raw_status = attributes.pop("raw_status", {})
        units, native_unit = _sdmx_units(req, attributes, dims)
        return self._base(req, observations=observations, frequency=_frequency(dims.get("FREQ")), units=units,
                          source_url=f"https://data.bis.org/topics/{meta['topic']}/BIS,{flow},{meta['version']}/{key}",
                          api_url=f"https://stats.bis.org/api/v2/data/dataflow/BIS/{flow}/{meta['version']}/{key}?" + urlencode({"startPeriod": req["fetch_start"], "endPeriod": req["end"], "format": "csv", "labels": "both"}),
                          provenance={"raw_status": raw_status, "attributes": attributes, "flow_ref": ref, "dimensions": dims,
                                      "native_unit": native_unit})

    def _fetch_imf(self, req):
        flow, key = req["native"].split("/")
        meta = catalog.imf_flow_info(flow)
        if flow not in self._imf_defs:
            definitions = self._call("imf", "imf_get_parameter_defs", {"params": {"database_id": flow}})
            if not isinstance(definitions, list):
                raise ValueError("IMF parameter definitions unavailable")
            self._imf_defs[flow] = {str(d["parameter"]).upper(): str(d["parameter"]) for d in definitions if isinstance(d, dict) and "parameter" in d}
        definitions = self._imf_defs[flow]
        aliases = {"COUNTRY": ("COUNTRY", "REF_AREA"), "FREQUENCY": ("FREQUENCY", "FREQ"),
                   "INDICATOR": ("INDICATOR", "COMMODITY")}
        filters = {}
        for dimension, code in zip(meta["dims"], key.split(".")):
            found = [definitions[name] for name in aliases.get(dimension, (dimension,)) if name in definitions]
            if len(found) != 1:
                raise ValueError("IMF parameter names do not match the catalog dimensions")
            filters[found[0]] = [code]
        args = {"params": {"database_id": flow, "start_year": int(req["fetch_start"][:4]), "end_year": int(req["end"][:4]), "filters": filters, "max_rows": _MAX_ROWS}}
        payload = self._call("imf", "imf_fetch_data", args)
        if payload.get("database_id") != flow:
            raise ValueError("IMF returned no data or a different database/vintage")
        observations, attributes = self._sdmx_rows(req, payload, {k: v[0] for k, v in filters.items()})
        raw_status = attributes.pop("raw_status", {})
        units, native_unit = _sdmx_units(req, attributes, dict(zip(meta["dims"], key.split("."))))
        projection_family = meta["base_flow"] == "WEO"
        provenance = {"raw_status": raw_status, "attributes": attributes, "database_id": flow,
                      "dimensions": {k: v[0] for k, v in filters.items()}, "native_unit": native_unit,
                      "projection_status": "per-observation only; no inferred cutoff", "vintage_availability": "not supplied"}
        projection_from = ""
        if projection_family:
            for obs in observations:
                if not obs.flag:
                    obs.flag = "unknown"
            # The IMF server strips status; the vintage flow names its year, the live flow
            # has no release date, so the retrieval year stands in (fix contract §1.4).
            named = re.fullmatch(r"WEO_(\d{4})_(?:APR|OCT)_VINTAGE", flow)
            vintage_year = int(named[1]) if named else datetime.fromtimestamp(self._clock(), timezone.utc).year
            provenance.update({"vintage_year": vintage_year, "projection_status": "inferred from the vintage year",
                               "vintage_basis": f"vintage flow {flow}" if named else "retrieval year (the live WEO flow carries no release date)"})
            projection_from = f"{vintage_year}-01-01"
        return self._base(req, observations=observations, frequency=req["frequency"], units=units,
                          source_url=f"https://data.imf.org/en/datasets/{meta['agency']}:{meta['base_flow']}",
                          vintage=flow if "_VINTAGE" in flow else "", projection_from=projection_from,
                          notes=_WEO_STATUS_NOTE if projection_family else "", provenance=provenance)

    def _fetch_wb(self, req):
        indicator, country = req["native"].split("/")
        database = catalog.wb_database(indicator)
        meta_payload = self._call("wb", "data360_get_metadata", {"database_id": database, "indicator_id": indicator, "fetch_disaggregation": False, "required_country": country})
        if meta_payload.get("stale"):
            raise ValueError("Data360 metadata is stale; canonical units/status cannot be established")
        metadata = meta_payload.get("indicator_metadata") or {}
        if metadata.get("idno") != indicator or metadata.get("database_id") != database:
            raise ValueError("Data360 metadata identity mismatch")
        native_frequency = _frequency(metadata.get("periodicity"))
        if native_frequency != "A":
            raise ValueError("Data360 annual periodicity is unknown or conflicting")
        rows, offset, attributes = [], 0, {}
        fingerprints, expected_total, page_receipts = set(), None, []
        for _ in range(50):
            args = {"database_id": database, "indicator_id": indicator, "country_code": country,
                    "start_year": int(req["fetch_start"][:4]), "end_year": int(req["end"][:4]),
                    "limit": 100, "offset": offset, "ref_area_filter": "none"}
            payload = self._call("wb", "data360_get_data", args)
            if payload.get("failed_validation") or payload.get("stale"):
                raise ValueError("Data360 query validation or metadata failed")
            if payload.get("truncated") or payload.get("truncatedToFit"):
                raise ValueError("Data360 page is explicitly truncated")
            page = payload.get("data")
            if not isinstance(page, list):
                raise ValueError("Data360 returned no observation list")
            count, page_offset, has_more = payload.get("count"), payload.get("offset"), payload.get("has_more")
            if (not isinstance(count, int) or isinstance(count, bool) or count != len(page) or count > 100
                    or not isinstance(page_offset, int) or isinstance(page_offset, bool) or page_offset != offset
                    or not isinstance(has_more, bool)):
                raise ValueError("Data360 page count, offset or termination signal is invalid")
            total = payload.get("total_count")
            if total is not None:
                if not isinstance(total, int) or isinstance(total, bool) or total < 0 or (expected_total is not None and total != expected_total):
                    raise ValueError("Data360 total count is invalid or changed")
                expected_total = total
            fingerprint = hashlib.sha256(_bytes(page)).hexdigest()
            if page and fingerprint in fingerprints:
                raise ValueError("Data360 repeated a page; completeness cannot be established")
            fingerprints.add(fingerprint)
            page_metadata = payload.get("metadata") or {}
            if page_metadata.get("idno", indicator) != indicator or page_metadata.get("database_id", database) != database:
                raise ValueError("Data360 page metadata identity mismatch")
            page_frequency = _frequency(page_metadata.get("periodicity"))
            if page_frequency and page_frequency != "A":
                raise ValueError("Data360 page periodicity conflicts with annual series")
            if "measurement_unit" in page_metadata:
                if _unit_text(page_metadata["measurement_unit"]) != _unit_text(metadata.get("measurement_unit", "")):
                    raise ValueError("Data360 page units contradict separate metadata")
            rows.extend(page)
            page_receipts.append({"offset": offset, "count": count, "has_more": has_more, "total_count": total})
            if not has_more:
                if payload.get("next_offset") is not None or (expected_total is not None and offset + count != expected_total):
                    raise ValueError("Data360 terminal page does not complete the advertised result")
                break
            new_offset = payload.get("next_offset")
            if (not isinstance(new_offset, int) or isinstance(new_offset, bool) or new_offset <= offset or new_offset < offset + count
                    or expected_total is not None and new_offset >= expected_total):
                raise ValueError("Data360 pagination cursor is invalid")
            offset = new_offset
        else:
            raise ValueError("Data360 pagination limit reached; narrow the requested window")
        observations, per_row_units, breakdowns = [], set(), {}
        for row in rows:
            if row.get("REF_AREA") != country:
                raise ValueError("Data360 returned a different geography")
            for k in _WB_BREAKDOWNS:
                breakdowns.setdefault(k, set()).add("" if row.get(k) in (None, "", "_T", "_Z") else str(row[k]))
            if "OBS_VALUE" not in row:
                raise ValueError("Data360 observation value missing")
            observations.append(Observation(_native_period(row["TIME_PERIOD"], "A"), row["OBS_VALUE"], "unknown"))
            if observations[-1].value is not None:
                per_row_units.add(_native_unit({k: [row[k]] for k in ("UNIT_MEASURE", "UNIT_MEASURE_NAME", "UNIT_MULT")
                                                if row.get(k) not in (None, "")}, "UNIT_MEASURE_NAME"))
            for k in ("UNIT_MEASURE", "UNIT_MEASURE_NAME", "UNIT_MULT"):
                if row.get(k) not in (None, ""):
                    attributes.setdefault(k, set()).add(str(row[k]))
        if any(len(v) > 1 for v in attributes.values()):
            raise ValueError("Data360 returned inconsistent units or scale")
        if len(per_row_units) > 1:
            raise ValueError("Data360 observation-level units or scale are inconsistent")
        # Disaggregations must be absent, except IMF WEO's "latest published vintage" marker
        # (COMP_BREAKDOWN_1="V_LST"), which is accepted only when every row carries it.
        dims = {k: v for k, v in breakdowns.items() if v != {""}}
        if any(k != "COMP_BREAKDOWN_1" or v != {"V_LST"} for k, v in dims.items()):
            raise ValueError("Data360 returned ambiguous disaggregations")
        units, native_unit = _wb_units(req, attributes, metadata, dims)
        policy = _status_policy(req["base"])
        provenance = {"database_id": database, "indicator_id": indicator, "country_code": country,
                      "attributes": {k: sorted(v) for k, v in attributes.items()}, "native_unit": native_unit,
                      "projection_status": "not supplied", "native_periodicity": native_frequency, "metadata": metadata,
                      "pages": page_receipts, "native_complete": True, "native_rows": len(rows), "resolution_safe": False}
        notes, projection_from = "Native Data360 strips observation status and may omit upstream metadata warnings.", ""
        if policy == "history_only":
            notes = "Native Data360 strips observation status; WDI publishes history only, so periods before the retrieval year are history."
        elif policy in ("weo_vintage", "gep_vintage"):
            retrieved = datetime.fromtimestamp(self._clock(), timezone.utc).year
            released = _release_year(metadata, retrieved)
            vintage_year, basis = released or (retrieved, "retrieval year (Data360 metadata carries no release date)")
            provenance.update({"vintage_year": vintage_year, "vintage_basis": basis, "projection_status": "inferred from the vintage year"})
            notes, projection_from = _WEO_STATUS_NOTE, f"{vintage_year}-01-01"
        return self._base(req, observations=observations, geography=country, frequency="A", units=units,
                          title=metadata.get("indicator_name") or metadata.get("name"), projection_from=projection_from,
                          vintage=_V_LST_VINTAGE if dims else "",
                          source_url=f"https://data360.worldbank.org/en/indicator/{indicator}", notes=notes, provenance=provenance)

    def _fetch_usgov(self, req):
        name, recipe, param = catalog.resolve_usgov_recipe(req["native"])
        kind = recipe.get("kind", "treasury")
        if kind == "sec":
            # Handler classifies by filing form and drops duration/start/accession;
            # its last 20 annual-form rows are not an annual time series.
            return self._error(req["series"], DataFailure("SEC native concept handler drops period starts/filing provenance and caps history; complete annual or as-of series is unavailable", "unknown_recipe"))
        if not catalog.recipe_available(recipe, env=self._env):
            raise DataFailure(f"usgov {name} needs {recipe.get('requires_key')}, which is not configured "
                              "(the usgov server loads that module only with its key)", "unknown_recipe")
        if kind == "eia":
            return self._fetch_eia(req, name, recipe, param)
        if kind in ("bea_nipa", "bea_industry"):
            return self._fetch_bea(req, name, recipe, param)
        if kind not in ("treasury", "usaspending"):
            raise DataFailure(f"usgov recipe kind {kind} is not supported", "unknown_recipe")
        if kind == "usaspending":
            payload = self._call("usgov", recipe["tool"], {**recipe["tool_args"], "start_date": req["fetch_start"], "end_date": req["end"]})
            rows = _columnar(payload)
            if payload.get("meta", {}).get("group") != "fiscal_year" or payload.get("data", {}).get("total") != len(rows):
                raise ValueError("USAspending fiscal grouping or row count is invalid")
            observations, periods = [], {}
            today = datetime.fromtimestamp(self._clock(), timezone.utc).date().isoformat()
            for row in rows:
                begin = _period(row["periodStart"])
                d = date.fromisoformat(begin)
                finish, label = date(d.year + 1, 9, 30).isoformat(), f"FY{d.year + 1}"
                if (d.month, d.day) != (10, 1) or row.get("fiscalPeriod") != label:
                    raise ValueError("USAspending fiscal label and start disagree")
                covered_start, covered_end = max(begin, req["fetch_start"]), min(finish, req["end"], today)
                if covered_start > covered_end:
                    continue
                # Agencies report late: a fiscal year counts as complete only once it has settled.
                settled = today > (date.fromisoformat(finish) + timedelta(days=_FISCAL_SETTLE_DAYS)).isoformat()
                periods[begin] = {"calendar": "us_federal_fiscal_year", "label": label, "start": begin, "end": finish,
                                  "covered_start": covered_start, "covered_end": covered_end,
                                  "complete": covered_start == begin and covered_end == finish and settled}
                observations.append(Observation(begin, row["amount"], "unknown"))
            return self._base(req, observations=observations, title=recipe["title"], units=recipe["units"], frequency="A", geography="USA",
                              source_url=recipe["source_url"], api_url=recipe["api_url"],
                              notes="Fiscal-year award obligations; native handler converts missing amounts to zero. Missingness cannot be certified.",
                              provenance={"resolution_safe": False, "fiscal_start_month": 10, "native_missingness": "lost; do not resolve",
                                          "metadata_origin": "curated_recipe", "periods": periods})
        filters = [recipe["filters"]] if recipe["filters"] else []
        if recipe["param_field"]:
            filters.append(f"{recipe['param_field']}:eq:{param}")
        filters += [f"record_date:gte:{req['fetch_start']}", f"record_date:lte:{req['end']}"]
        rows, seen_pages, expected_total, expected_pages = [], set(), None, None
        for page in range(1, 51):
            args = {"endpoint": recipe["endpoint"], "fields": recipe["fields"], "filter": ",".join(filters),
                    "sort": recipe["sort"], "page_number": page, "page_size": 100}
            payload = self._call("usgov", recipe["tool"], args)
            chunk = _columnar(payload)
            if payload.get("meta", {}).get("endpoint") != recipe["endpoint"]:
                raise ValueError("Treasury returned a different endpoint")
            total_pages = payload.get("meta", {}).get("totalPages")
            if not isinstance(total_pages, int) or total_pages < page or total_pages > 50:
                raise ValueError("Treasury pagination is missing or exceeds bound")
            total = payload.get("data", {}).get("total")
            returned = payload.get("meta", {}).get("recordsReturned")
            if not isinstance(total, int) or isinstance(total, bool) or total < 0 or returned != len(chunk):
                raise ValueError("Treasury pagination counts are invalid")
            if expected_total is None:
                expected_total, expected_pages = total, total_pages
            elif total != expected_total or total_pages != expected_pages:
                raise ValueError("Treasury pagination changed during retrieval")
            fingerprint = hashlib.sha256(_bytes(chunk)).hexdigest()
            if chunk and fingerprint in seen_pages:
                raise ValueError("Treasury repeated a page; completeness cannot be established")
            seen_pages.add(fingerprint)
            if not chunk and expected_total:
                raise ValueError("Treasury pagination is incomplete")
            rows.extend(chunk)
            if page == total_pages:
                break
        if len(rows) != expected_total:
            raise ValueError("Treasury returned an incomplete requested window")
        points = {}
        for row in rows:
            if recipe["param_field"] and str(row.get(recipe["param_field"])) != param:
                raise ValueError("Treasury parameter identity mismatch")
            if recipe["filters"]:
                column, _, expected = recipe["filters"].split(":", 2)
                if str(row.get(column)) != expected:
                    raise ValueError("Treasury accounting row identity mismatch")
            original_date = _period(row[recipe["date_field"]])
            if not req["fetch_start"] <= original_date <= req["end"]:
                continue
            d = date.fromisoformat(original_date)
            if recipe["frequency"] == "M":
                period = d.replace(day=1).isoformat()
            elif recipe["frequency"] == "Q":
                period = d.replace(month=(d.month - 1) // 3 * 3 + 1, day=1).isoformat()
            else:
                period = original_date
            obs = Observation(period, row[recipe["value_field"]])
            tie = row.get(recipe["tiebreak_field"], "") if recipe["tiebreak_field"] else ""
            old = points.get(period)
            if old and not recipe["tiebreak_field"] and old[1] != obs:
                raise ValueError("Treasury has conflicting rows for one period")
            if old is None or tie < old[0]:
                points[period] = (tie, obs)
        entry = catalog.lookup(req["base"])
        geography = entry.geography if entry else "" if name == "treasury/fx" else "USA"
        return self._base(req, observations=[o for _, o in points.values()], title=recipe["title"] + (f" — {param}" if param else ""),
                          title_zh=recipe["title_zh"], units=recipe["units"], frequency=recipe["frequency"],
                          seasonal_adjustment=recipe["seasonal_adjustment"], geography=geography, source_url=recipe["source_url"],
                          api_url=recipe["api_url"] + "?" + urlencode({"fields": recipe["fields"], "filter": ",".join(filters), "sort": recipe["sort"]}),
                          notes=recipe["notes"], provenance={"recipe": name, "parameter": param, "pages": page,
                                                             "metadata_origin": "curated_recipe", "native_complete": True})

    def _fetch_eia(self, req, name, recipe, param):
        """EIA v2 route through eia_query, paged newest first. Every row must carry the recipe's
        facet values and its verified unit text; one row per period."""
        facets = dict(recipe["facets"])
        if recipe["param_facets"]:
            values = param.split(".")
            if len(values) != len(recipe["param_facets"]):
                raise DataFailure("EIA recipe parameter does not match its facets", "unknown_recipe")
            facets.update(zip(recipe["param_facets"], values))
        width = 7 if recipe["frequency"] == "M" else 4
        query = {**recipe["tool_args"], "facets": "; ".join(f"{k}={v}" for k, v in facets.items()),
                 "start": req["fetch_start"][:width], "end": req["end"][:width]}
        route = str(recipe["tool_args"]["route"]).strip("/")
        rows, total, offset, pages = [], None, 0, 0
        for _ in range(50):
            payload = self._call("usgov", recipe["tool"], {**query, "length": _EIA_PAGE_ROWS, "offset": offset})
            pages += 1
            if payload.get("dataType") == "empty" and payload.get("data") is None:
                if offset:
                    raise ValueError("EIA pagination ended before the advertised total")
                break  # no rows in the window; reported as no observations
            chunk = _columnar(payload)
            if str((payload.get("meta") or {}).get("route", "")).strip("/") != route:
                raise ValueError("EIA returned a different route")
            page_total = payload["data"].get("total")
            if not isinstance(page_total, int) or isinstance(page_total, bool) or page_total < 0 or total not in (None, page_total):
                raise ValueError("EIA total row count is invalid or changed")
            total = page_total
            if not chunk or len(chunk) > _EIA_PAGE_ROWS:
                raise ValueError("EIA page is empty or exceeds the requested length")
            rows.extend(chunk)
            offset += len(chunk)
            if offset >= total:
                break
        else:
            raise ValueError("EIA pagination limit reached; narrow the requested window")
        if total is not None and len(rows) != total:
            raise ValueError("EIA returned an incomplete requested window")
        points: dict[str, Observation] = {}
        for row in rows:
            if any(str(row.get(k)) != v for k, v in facets.items()):
                raise ValueError("EIA returned a row outside the recipe facets")
            unit = " ".join(str(row.get(recipe["units_field"]) or "").split())
            if recipe["native_units"] and unit.lower() != recipe["native_units"].lower():
                raise DataFailure(f"EIA unit text {unit or 'none'!r} differs from the verified recipe units "
                                  f"{recipe['native_units']!r}", "provider_error")
            period = _native_period(row.get(recipe["date_field"]), recipe["frequency"])
            if period in points:
                raise ValueError("EIA returned several rows for one period; the recipe facets are not unique")
            points[period] = Observation(period, row.get(recipe["value_field"]))
        entry = catalog.lookup(req["base"])
        citable = [("frequency", query["frequency"]), ("data[0]", query["data"]),
                   *((f"facets[{k}][]", v) for k, v in facets.items()), ("start", query["start"]), ("end", query["end"])]
        return self._base(req, observations=list(points.values()), title=recipe["title"] + (f" — {param}" if param else ""),
                          title_zh=recipe["title_zh"], units=recipe["units"], frequency=recipe["frequency"],
                          seasonal_adjustment=recipe["seasonal_adjustment"], geography=entry.geography if entry else "USA",
                          source_url=recipe["source_url"], api_url=recipe["api_url"] + "?" + urlencode(citable),
                          notes=recipe["notes"], provenance={"recipe": name, "parameter": param, "facets": facets,
                                                             "native_units": recipe["native_units"], "pages": pages,
                                                             "native_total": total or 0, "metadata_origin": "curated_recipe",
                                                             "native_complete": True})

    def _fetch_bea(self, req, name, recipe, param):
        """BEA NIPA table line or GDP-by-industry row. The tools return at most
        ``max_obs_per_call`` points per line, so the window is read in year chunks that cannot
        reach the cap (newest first); the tools drop units, so the curated recipe units apply."""
        per_year = {"Q": 4, "A": 1}[recipe["frequency"]]
        span = recipe["max_obs_per_call"] // per_year
        if span < 1:
            raise DataFailure("BEA recipe cap is below one year of observations", "unknown_recipe")
        first, last = int(req["fetch_start"][:4]), int(req["end"][:4])
        this_year = datetime.fromtimestamp(self._clock(), timezone.utc).year
        points: dict[str, Any] = {}
        labels, chunks, high = set(), [], last
        while high >= first:
            low = max(first, high - span + 1)
            args = {**recipe["tool_args"], "year": ",".join(str(y) for y in range(low, high + 1))}
            if recipe["kind"] == "bea_industry":
                args[recipe["param_field"]] = param
            try:
                payload = self._call("usgov", recipe["tool"], args)
            except ValueError as exc:
                # BEA rejects a year it has not published yet ("Invalid year", "No data exists").
                if low >= this_year and re.search(r"(?i)invalid year|no data exists", str(exc)):
                    chunks.append({"years": [low, high], "lines": 0, "note": "not yet published"})
                    high = low - 1
                    continue
                raise
            rows = [] if payload.get("dataType") == "empty" and payload.get("data") is None else _columnar(payload)
            if recipe["kind"] == "bea_nipa":
                rows = [r for r in rows if r.get("description") == recipe["line_description"]]
            if len(rows) != 1:
                if not rows and low >= this_year:
                    chunks.append({"years": [low, high], "lines": 0, "note": "not yet published"})
                    high = low - 1
                    continue
                what = recipe["line_description"] or f"industry {param}"
                raise DataFailure(f"BEA returned {len(rows)} rows for {what}; exactly one is required",
                                  "not_found" if not rows else "provider_error")
            labels.add(_clean(rows[0].get("description") or rows[0].get("industry"), 200))
            observations = rows[0].get("observations")
            if isinstance(observations, str):
                observations = json.loads(observations)
            if not isinstance(observations, list) or len(observations) > recipe["max_obs_per_call"]:
                raise ValueError("BEA observation list is missing or exceeds the tool cap")
            for point in observations:
                if not isinstance(point, dict):
                    raise ValueError("Invalid BEA observation")
                period = _bea_period(point.get("period"), recipe["frequency"])
                if not low <= int(period[:4]) <= high:
                    raise ValueError("BEA returned a period outside the requested years")
                value = _number(point.get("value"))
                if period in points and points[period] != value:
                    raise ValueError("BEA returned conflicting values for one period")
                points[period] = value
            chunks.append({"years": [low, high], "lines": 1, "observations": len(observations)})
            high = low - 1
        if len(labels) > 1:
            raise ValueError("BEA line identity changed between year chunks")
        label = next(iter(labels), "")
        title = recipe["title"] + (f": {label} ({param})" if recipe["kind"] == "bea_industry" and label else "")
        query = {"Year": f"{first}-{last}", **({"Industry": param} if recipe["kind"] == "bea_industry" else {})}
        return self._base(req, observations=[Observation(d, v) for d, v in points.items()], title=title,
                          title_zh=recipe["title_zh"], units=recipe["units"], frequency=recipe["frequency"],
                          seasonal_adjustment=recipe["seasonal_adjustment"], geography="USA",
                          source_url=recipe["source_url"], api_url=recipe["api_url"] + "&" + urlencode(query),
                          notes=recipe["notes"], provenance={"recipe": name, "parameter": param, "line": label,
                                                             "chunks": chunks, "metadata_origin": "curated_recipe",
                                                             "units_origin": "curated recipe (the BEA tool returns no units)",
                                                             "native_complete": True})


def _bea_period(value: Any, frequency: str) -> str:
    """BEA periods: NIPA '2025Q1', GDP by Industry '2025QIV' (roman quarters), annual '2025'."""
    roman = re.fullmatch(r"(\d{4})Q(I{1,3}|IV)", str(value or "").strip())
    if roman and frequency == "Q":
        return date(int(roman[1]), (_BEA_ROMAN_QUARTERS[roman[2]] - 1) * 3 + 1, 1).isoformat()
    return _native_period(value, frequency)


_SINGLETON: DataSources | None = None
_SINGLETON_LOCK = threading.Lock()


def get_data_sources(*, env=None) -> DataSources:
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is None:
            _SINGLETON = DataSources(env=env)
        return _SINGLETON


def reset_data_sources_for_tests() -> None:
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is not None:
            _SINGLETON.close()
        _SINGLETON = None
    with _KEY_LOCK:
        _REJECTED_KEYS.clear()


atexit.register(reset_data_sources_for_tests)
