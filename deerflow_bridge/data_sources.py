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
    from . import data_catalog as catalog
    from .data_mcp import McpHub, get_hub
except ImportError:  # deployed bridge is also loaded as bare modules
    import data_catalog as catalog
    from data_mcp import McpHub, get_hub

PROVIDERS = tuple(catalog.PROVIDERS)
logger = logging.getLogger(__name__)
_MAX_BYTES = 2 * 1024 * 1024
_MAX_ROWS = 5000
NORMALIZATION_POLICY_VERSION = 2
_WRITE_LOCK = threading.RLock()
_QUOTA_LOCK = threading.RLock()
_SECRET = re.compile(r"(?i)(?:api[_-]?key|token|secret|password|authorization|registrationkey)")


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


def _shift(period: str, months: int) -> str:
    d = date.fromisoformat(period)
    n = d.year * 12 + d.month - 1 + months
    year, month = n // 12, n % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1])).isoformat()


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
        for obs in self.observations:
            raw = obs.flag
            if lossy or weo and not raw:
                obs.flag = "unknown"
            elif self.provider == "bls" and raw == "P":
                obs.flag = "preliminary"
                self.provenance.setdefault("raw_status", {}).setdefault(obs.date, [{"code": "P", "text": "Preliminary (BLS code)"}])
            elif raw:
                obs.flag = _status_flag(raw)
        if lossy:
            self.provenance["resolution_safe"] = False
            self.provenance["fidelity_policy_version"] = NORMALIZATION_POLICY_VERSION
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


@dataclass
class DataError:
    series: str
    message: str
    retryable: bool = False

    def __post_init__(self):
        self.series = _clean(self.series, 200)
        self.message = _clean(self.message, 300)


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
    finite = [o for o in obs if o.value is not None and _observation_kind(o, series) == "observed"]
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
            "last": obs[-1].date if obs else "", "projection_count": sum(_projected(o, series) for o in obs)}


def format_value(value: float | None, units: str = "") -> str:
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


def _display_period(period: str, frequency: str, series: Series | None = None) -> str:
    metadata = series.provenance.get("periods", {}).get(period, {}) if series else {}
    if metadata.get("label"):
        return str(metadata["label"]) + (" (partial)" if metadata.get("complete") is False else "")
    return period[:4] if frequency == "A" else period[:7] if frequency == "M" else period


def render_series_page(series: Series) -> str:
    stats = series_stats(series)
    lines = [f"# {series.title}", f"Provider: {series.provider_name} · Series: {series.series} · Units: {series.units} · Frequency: {series.frequency} · Seasonal adjustment: {series.seasonal_adjustment or 'unknown'}",
             f"Source: {series.source_url} · Retrieved: {series.retrieved_at or 'unknown'} · Coverage shown: {stats['first']} to {stats['last']} ({stats['count']} observations)",
             f"Geography: {series.geography or 'unknown'} · Vintage: {series.vintage or 'unknown'} · Route: {series.route or 'unknown'}"]
    if any(_projected(o, series) for o in series.observations):
        lines.append("Projections: explicitly classified publisher projections are marked in the observation table.")
    if series.notes:
        lines.append(f"Notes: {series.notes}")
    lines += ["## Summary"]
    if stats["latest"]:
        p = stats["latest"]
        lines.append(f"- Latest: {format_value(p['value'], series.units)} ({p['date']}); see observation status below.")
    if stats["previous_year"]:
        p = stats["previous_year"]
        lines.append(f"- Year earlier: {format_value(p['value'], series.units)} ({p['date']}); change {format_value(stats['yoy_change'], series.units)} ({format_value(stats['yoy_change_pct'], 'Percent')}).")
    if stats["five_year_min"]:
        low, high = stats["five_year_min"], stats["five_year_max"]
        lines.append(f"- 5-year range: {format_value(low['value'], series.units)} ({low['date']}) to {format_value(high['value'], series.units)} ({high['date']}).")
    lines += [f"## Observations ({series.units})", f"Values in {series.units or 'unknown units'}.", "| Period | Value | Status |", "|---|---|---|"]
    table = [f"| {_display_period(o.date, series.frequency, series)} | {format_value(o.value, series.units)} | {'missing' if o.value is None else _observation_kind(o, series)} |" for o in series.observations]
    while table and len("\n".join(lines + table)) > 11900:
        table.pop(0)
    if len(table) < len(series.observations):
        lines.append("Older rows omitted from this bounded page; stored dataset retains them.")
    return "\n".join(lines + table)[:12000]


def render_series_brief(series: Series, sid: int | None = None) -> str:
    citation = f"[S{sid}] " if isinstance(sid, int) and not isinstance(sid, bool) and sid > 0 else ""
    lines = [f"{citation}{series.series} — {series.title} ({series.units}, {series.frequency})"]
    for o in series.observations[-8:]:
        status = _observation_kind(o, series)
        lines.append(f"{_display_period(o.date, series.frequency, series)}: {format_value(o.value, series.units)} [{status}]")
    if series.notes:
        lines.append(series.notes)
    return "\n".join(lines)[:900]


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")


def _safe_path(root: Path, relative: str = "") -> Path:
    root = root.absolute()
    part = Path(relative)
    if part.is_absolute() or ".." in part.parts:
        raise ValueError("Artifact path escapes output directory")
    path = root / part
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Symlink artifacts are not accepted")
    return path


def _read(path: Path, max_bytes: int = _MAX_BYTES) -> bytes:
    _safe_path(path)
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
    path = _safe_path(path)
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
    _safe_path(path)
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
            except (ValueError, TypeError, KeyError, OSError):
                logger.warning("Official data row unavailable: integrity or containment validation failed")
        return result
    except (ValueError, TypeError, KeyError, OSError):
        logger.warning("Official data manifest unavailable: integrity or containment validation failed")
        return []


def write_dataset_files(series_list: Iterable[Series], out_dir: str | Path, *, citations: Mapping[str, Any] | None = None) -> dict:
    """Incrementally merge datasets, committing the manifest after JSON and CSV."""
    with _WRITE_LOCK:
        try:
            root = Path(out_dir)
            directory = _safe_path(root, "data")
            existing = {r["series"]: r for r in load_datasets(root)}
            incoming = list(series_list)
            if len(incoming) > 200:
                raise ValueError("Too many datasets")
            for value in incoming:
                s = Series.from_dict(value.to_dict() if isinstance(value, Series) else value)
                if not s.observations or not s.source_url:
                    raise ValueError("Empty or uncitable dataset")
                prior = existing.get(s.series, {})
                if not s.kiqs:
                    s.kiqs = list(prior.get("kiqs", []))
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
                _atomic(_safe_path(directory, json_name), raw)
                _atomic(_safe_path(directory, csv_name), csv_raw)
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
            _atomic(_safe_path(directory, "datasets.json"), _bytes(manifest))
            return manifest
        except (ValueError, TypeError, KeyError, OSError):
            logger.warning("Official data persistence failed: invalid input or unavailable output directory")
            return {"schema_version": 1, "series": [], "error": "Official data persistence failed"}


def load_official_data(handoff_dir: str | Path, *, max_series: int = 12) -> dict | None:
    if not isinstance(max_series, int) or isinstance(max_series, bool) or max_series < 1:
        return None
    rows = load_datasets(handoff_dir)[:min(max_series, 200)]
    for row in rows:
        row["observations"] = row["observations"][-240:]
    return {"schema_version": 1, "series": rows} if rows else None


def _anchor_period(period: Any, series: Series) -> str:
    text = str(period)
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
    text = str(value or "").upper().strip()
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


def _sdmx_units(req: dict, attributes: dict) -> str:
    """Recognize supported native units/scale; fail closed on contradictions."""
    entry = catalog.lookup(req["base"])
    expected = entry.units if entry else ""
    def normalize(value):
        text = re.sub(r"[^a-z0-9%]+", " ", value.lower()).strip()
        text = text.replace("per cent", "percent")
        return {"%": "percent", "percentage": "percent", "pct": "percent", "pt": "percent", "pc": "percent",
                "usd": "u s dollars", "us dollars": "u s dollars", "us dollar": "u s dollars", "us dollar per barrel": "u s dollars per barrel"}.get(text, text)
    code = next(iter(attributes.get("UNIT_MEASURE", [])), "")
    label = next(iter(attributes.get("UNIT_MEASURE_LABEL", [])), "")
    scale = next(iter(attributes.get("UNIT_MULT", [])), "")
    canonical = normalize(expected)
    scale_words = {3: "thousand", 6: "million", 9: "billion", 12: "trillion"}
    if scale:
        exponent = int(scale)
        expected_scale = next((n for n, word in scale_words.items() if word in canonical), 0)
        if exponent != expected_scale:
            raise ValueError("Native SDMX scale conflicts with catalog units")
    if not code and not label:
        return expected
    if not expected:
        if label and (not scale or int(scale) == 0):
            return label
        raise ValueError("Native SDMX units lack a verified canonical label")
    stripped = re.sub(r"\b(thousands?|millions?|billions?|trillions?)\s+(?:of\s+)?", "", canonical)
    stripped = re.sub(r" per (?:year|annum)$", "", stripped)
    candidates = {normalize(v) for v in (code, label) if v}
    compatible = {canonical, stripped}
    recognized_codes = {"USD", "EUR", "GBP", "JPY", "PCT", "PC", "PT", "PERCENT", "PERCENTAGE", "%", "INDEX"}
    if label and normalize(label) not in compatible:
        raise ValueError("Native SDMX unit label contradicts the canonical units")
    if code.upper() in recognized_codes and normalize(code) not in compatible:
        raise ValueError("Native SDMX unit code contradicts the canonical units")
    if canonical not in candidates and stripped not in candidates:
        raise ValueError("Native SDMX units conflict with catalog label or are unrecognized")
    return expected


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


def _wb_unit_parts(text: str) -> tuple[str, int]:
    normalized = re.sub(r"[^a-z0-9%]+", " ", text.lower()).strip().replace("per cent", "percent")
    exponent = 0
    for number, word in ((3, "thousand"), (6, "million"), (9, "billion"), (12, "trillion")):
        if re.search(r"\b" + word + r"s?\b", normalized):
            exponent = number
            normalized = re.sub(r"\b" + word + r"s?\s*(?:of\s+)?", "", normalized).strip()
    aliases = {"pt": "percent", "pct": "percent", "%": "percent", "percentage": "percent",
               "ps": "people", "persons": "people", "person": "people", "number of people": "people",
               "usd": "us dollars", "u s dollars": "us dollars", "ix": "index"}
    normalized = aliases.get(normalized, normalized)
    if normalized.startswith("percent") and "point" not in normalized:
        normalized = "percent"
    return normalized, exponent


def _wb_units(attributes: dict, metadata: dict) -> str:
    """Preserve raw values and verify their unit multiplier exactly once."""
    code = next(iter(attributes.get("UNIT_MEASURE", [])), "")
    label = next(iter(attributes.get("UNIT_MEASURE_NAME", [])), "")
    measure = str(metadata.get("measurement_unit") or "")
    scale = int(next(iter(attributes.get("UNIT_MULT", [])), "0"))
    multipliers = {0: "", 3: "Thousands", 6: "Millions", 9: "Billions", 12: "Trillions"}
    if scale not in multipliers or not code or not measure:
        raise ValueError("Data360 unit code, measurement unit or multiplier is unavailable")
    code_base, _ = _wb_unit_parts(code)
    meta_base, meta_scale = _wb_unit_parts(measure)
    if code_base != meta_base or meta_scale not in (0, scale):
        raise ValueError("Data360 unit code and metadata disagree")
    if label:
        label_base, label_scale = _wb_unit_parts(label)
        if label_base != code_base or label_scale != scale:
            raise ValueError("Data360 unit label or multiplier conflicts with its code")
        return label
    if meta_scale == scale:
        return measure
    return f"{multipliers[scale]} of {measure}" if scale else measure


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
        # Match source/deployed layout without inspecting saved datasets at import.
        root = Path(__file__).resolve().parent.parent
        self._cache_dir = Path(cache_dir or self._env.get("DATA_SOURCES_CACHE_DIR") or root / "backend/uploads/.data_cache")
        self._clock, self._http = clock, http_get or _http_csv
        self._lock = threading.RLock()
        self._locks: dict[str, threading.Lock] = {}
        self._memory: dict[str, tuple[float, dict]] = {}
        self._local = threading.local()
        self._imf_defs: dict[str, dict] = {}
        self._semaphores = {p: threading.BoundedSemaphore(1 if p in ("imf", "bls") else 3) for p in PROVIDERS}
        self._closed = False

    def _get_hub(self):
        with self._lock:
            if self._hub is None:
                self._hub = get_hub(env=self._env)
            return self._hub

    def providers(self) -> dict[str, str]:
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
            elif p == "fred" and not self._env.get("FRED_API_KEY", "").strip():
                result[p] = "keyless"
            elif status.get("state") in ("ready", "idle", "starting"):
                result[p] = "ready"
            else:
                result[p] = self._redact(status.get("error") or status.get("state") or "unavailable")
        return result

    def enabled(self) -> bool:
        return self._on and not self._closed and any(v in ("ready", "keyless") for v in self.providers().values())

    def prewarm(self) -> None:
        if not self._on or self._closed:
            return
        names = [p for p, s in self.providers().items() if s == "ready"]
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

    def _redact(self, value: Any) -> str:
        text = str(value or "")
        for key, secret in self._env.items():
            if _SECRET.search(key) and secret:
                text = text.replace(secret, "[redacted]")
        return _clean(text, 300)

    def _error(self, sid, exc, retryable=False):
        return DataError(self._redact(sid), self._redact(exc), retryable)

    def _remaining(self) -> float | None:
        deadline = getattr(self._local, "deadline", None)
        if self._closed:
            raise ValueError("Data sources closed")
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
            raise ValueError(self._redact(result.error or result.text or "Provider unavailable"))
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

    def search(self, query: str, *, provider: str | None = None, limit: int = 6) -> list[SearchHit]:
        if not self._on or self._closed or not isinstance(query, str) or not query.strip():
            return []
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            return []
        selected = {provider.lower()} if isinstance(provider, str) else self._allowed
        selected &= self._allowed
        if not selected:
            return []
        hits = {}
        try:
            for entry in catalog.search_catalog(query[:300], provider=provider, limit=limit):
                if entry.provider in selected:
                    hits[entry.series] = SearchHit(entry.series, entry.title, entry.units, entry.frequency, "", entry.provider, entry.notes)
            if len(hits) >= limit:
                return list(hits.values())[:limit]
            if "fred" in selected and self._env.get("FRED_API_KEY"):
                try:
                    payload = self._call("fred", "fred_search", {"search_text": query[:300], "limit": limit, "offset": 0})
                    for row in payload.get("results", []):
                        parsed = parse_series_id("fred:" + str(row.get("id", "")))
                        if parsed:
                            sid = ":".join(parsed)
                            hits.setdefault(sid, SearchHit(sid, self._redact(row.get("title")), self._redact(row.get("units")), _frequency(row.get("frequency")), self._redact(row.get("observation_range")), "fred", self._redact(row.get("notes"))))
                except Exception:
                    logger.warning("Official FRED search unavailable")
            if "wb" in selected and len(hits) < limit:
                try:
                    countries = [code for code, (name, aliases) in catalog.GEOGRAPHIES.items() if any(a.lower() in query.lower() for a in (name, *aliases))]
                    # Native search identifies indicators; country must be explicit, never guessed.
                    payload = self._call("wb", "data360_search_indicators", {"query": query[:300], "limit": limit, **({"required_country": countries[0]} if len(countries) == 1 else {})})
                    for row in payload.get("indicators", []):
                        areas = countries or [a for a, covered in (row.get("covers_country") or {}).items() if covered]
                        if len(areas) != 1:
                            continue
                        parsed = parse_series_id(f"wb:{row.get('idno', '')}/{areas[0]}")
                        if parsed:
                            sid = ":".join(parsed)
                            hits.setdefault(sid, SearchHit(sid, self._redact(row.get("name")), "", _frequency(row.get("periodicity")), "", "wb", "Discovery metadata; fetch before citing"))
                except Exception:
                    logger.warning("Official Data360 search unavailable")
            if len(hits) < limit and "bis" in selected:
                try:
                    payload = self._call("bis", "search_dataflows", {"query": query[:300], "limit": limit})
                    flows = {row.get("flow_ref") for row in payload.get("dataflows", [])}
                    for entry in catalog.CATALOG:
                        if entry.provider != "bis":
                            continue
                        flow = entry.native.split("/")[0]
                        if f"BIS,{flow},{catalog.BIS_FLOWS[flow]['version']}" in flows:
                            hits.setdefault(entry.series, SearchHit(entry.series, entry.title, entry.units, entry.frequency, "", "bis", "Discovered flow; exact key from curated catalog"))
                except Exception:
                    logger.warning("Official BIS flow discovery unavailable")
            if len(hits) < limit and "usgov" in selected:
                try:
                    payload = self._call("usgov", "treasury_search_datasets", {"query": query[:300]})
                    endpoints = {row.get("endpoint") for row in (payload.get("data") or {}).get("items", [])}
                    for entry in catalog.CATALOG:
                        if entry.provider != "usgov":
                            continue
                        recipe = catalog.resolve_usgov_recipe(entry.native)
                        if recipe and recipe[1]["endpoint"] in endpoints:
                            hits.setdefault(entry.series, SearchHit(entry.series, entry.title, entry.units, entry.frequency, "", "usgov", "Discovered endpoint; selected accounting recipe from curated catalog"))
                except Exception:
                    logger.warning("Official Treasury discovery unavailable")
            # Flow/endpoint discovery supplies no arbitrary new series keys.
            # Every returned series still has a complete curated fetch recipe.
            return list(hits.values())[:limit]
        except Exception:
            logger.warning("Official data search unavailable")
            return list(hits.values())[:limit]

    def _request(self, series, start, end, transform, max_obs):
        if not self._on or self._closed:
            raise ValueError("Data sources disabled or closed")
        parsed = parse_series_id(series)
        if not parsed:
            if isinstance(series, str) and series.strip().lower().startswith("usgov:"):
                raise ValueError("Unknown usgov recipe. Valid recipes: " + ", ".join(catalog.USGOV_RECIPES))
            raise ValueError("Invalid series ID; use data_search or the official catalog")
        provider, native = parsed
        if provider not in self._allowed:
            raise ValueError("Provider is not enabled")
        native, _, suffix = native.partition("#")
        if transform is not None and suffix and transform != suffix:
            raise ValueError("Conflicting transform and series suffix")
        transform = suffix or transform or ""
        if transform not in ("", "yoy", "pct"):
            raise ValueError("Unsupported transform; use yoy or pct")
        if not isinstance(max_obs, int) or isinstance(max_obs, bool) or not 1 <= max_obs <= _MAX_ROWS:
            raise ValueError("max_obs must be an integer from 1 to 5000")
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
        today = datetime.fromtimestamp(self._clock(), timezone.utc).date().isoformat()
        finish = _period(end) if end is not None else today
        years = 25 if frequency == "A" else 2 if frequency == "D" else 10
        begin = _period(start) if start is not None else max("1900-01-01", _shift(finish, -12 * years))
        if begin > finish or date.fromisoformat(begin).year < 1900 or date.fromisoformat(finish).year > 2100:
            raise ValueError("Invalid start/end window (supported years 1900–2100)")
        warmup = 12 if transform == "yoy" else {"A": 12, "Q": 3, "M": 1, "D": 1, "W": 1}.get(frequency, 12) if transform == "pct" else 0
        if frequency == "W" and transform == "yoy":
            raise ValueError("Weekly yoy is unsupported without a verified week-alignment policy")
        fetch_start = max("1900-01-01", _shift(begin, -warmup)) if warmup else begin
        canonical = sid + ("#" + transform if transform else "")
        key = hashlib.sha256(_bytes([NORMALIZATION_POLICY_VERSION, canonical, begin, finish, max_obs])).hexdigest()
        return {"series": canonical, "base": sid, "provider": provider, "native": native, "start": begin, "end": finish,
                "fetch_start": fetch_start, "transform": transform, "max_obs": max_obs, "frequency": frequency, "key": key}

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
            self._memory[req["key"]] = timestamp, data
        try:
            _atomic(_safe_path(self._cache_dir, req["key"] + ".json"), _bytes({"key": req["key"], "stored_at": timestamp, "series": data, "sha256": hashlib.sha256(_bytes(data)).hexdigest()}))
        except (ValueError, OSError):
            logger.warning("Official data cache unavailable; fetched result retained")

    def get(self, series: str, *, start: str | None = None, end: str | None = None,
            transform: str | None = None, max_obs: int = 240) -> Series | DataError:
        try:
            req = self._request(series, start, end, transform, max_obs)
            with self._lock:
                lock = self._locks.setdefault(req["key"], threading.Lock())
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
            return self._error(series, exc, isinstance(exc, (TimeoutError, OSError)))

    def get_many(self, ids: Sequence[str], *, deadline_s: float, **kw) -> dict[str, Series | DataError]:
        ids = list(dict.fromkeys(ids))[:200]
        if not isinstance(deadline_s, (float, int)) or not math.isfinite(deadline_s) or deadline_s <= 0:
            return {sid: self._error(sid, "Data request deadline exceeded", True) for sid in ids}
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
        return {sid: output.get(sid, self._error(sid, "Data request deadline exceeded", True)) for sid in ids}

    def _base(self, req, **metadata):
        entry = catalog.lookup(req["base"])
        values = {name: getattr(entry, name) for name in ("title", "title_zh", "units", "frequency", "seasonal_adjustment", "geography", "source_url", "notes")} if entry else {}
        values.update({k: v for k, v in metadata.items() if v not in (None, "")})
        return Series(series=req["base"], provider=req["provider"], provider_name=catalog.PROVIDERS[req["provider"]]["name"],
                      route="mcp", retrieved_at=datetime.fromtimestamp(self._clock(), timezone.utc).isoformat(), **values)

    def _finish(self, req, s):
        native_frequency = s.frequency
        if not s.observations:
            raise ValueError("Provider returned no observations for the requested series")
        periods = s.provenance.get("periods", {})
        def intersects(o, start):
            return o.date <= req["end"] and periods.get(o.date, {}).get("end", o.date) >= start
        s.observations = [o for o in s.observations if intersects(o, req["fetch_start"])]
        if s.frequency == "D":
            monthly = {}
            for o in s.observations:
                monthly.setdefault(o.date[:7] + "-01", []).append(o)
            s.observations = [Observation(d, sum(o.value for o in rows if o.value is not None) / sum(o.value is not None for o in rows) if any(o.value is not None for o in rows) else None,
                                          ";".join(sorted({o.flag for o in rows if o.flag}))) for d, rows in sorted(monthly.items())]
            s.frequency = "M"
            s.provenance["aggregation"] = "Arithmetic mean of available daily observations; partial months possible"
            s.provenance["resolution_safe"] = False
            periods = {}
            for d, rows in monthly.items():
                finish = (date.fromisoformat(_shift(d, 1)) - timedelta(days=1)).isoformat()
                periods[d] = {"calendar": "calendar_month", "label": d[:7], "start": d, "end": finish,
                              "covered_start": max(d, req["fetch_start"]), "covered_end": min(finish, req["end"]),
                              "complete": False}
            s.provenance["periods"] = periods
            s.notes = _clean(s.notes + " Daily data aggregated to monthly mean; partial months possible.")
        s.provenance["native_frequency"] = native_frequency
        if req["transform"]:
            if s.frequency == "W" and req["transform"] == "yoy":
                raise ValueError("Weekly yoy is unsupported without a verified week-alignment policy")
            if s.series == "usgov:spending/total" and any(not periods.get(o.date, {}).get("complete") for o in s.observations):
                raise ValueError("Cannot transform partial fiscal-year aggregates")
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
                        raise ValueError("Cannot transform a series of unknown frequency")
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
            raise ValueError("No observations in requested window")
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
        # Redact all provider-originated strings before any disk/cache write.
        def scrub(value):
            if isinstance(value, str):
                text = value
                for key, secret in self._env.items():
                    if _SECRET.search(key) and secret:
                        text = text.replace(secret, "[redacted]")
                return _clean(text, max(len(text), 1))
            if isinstance(value, list):
                return [scrub(v) for v in value]
            if isinstance(value, dict):
                return {k: "[redacted]" if _SECRET.search(k) else scrub(v) for k, v in value.items()}
            return value
        return Series.from_dict(scrub(s.to_dict()))

    def _fetch_fred(self, req):
        native = req["native"]
        if not self._env.get("FRED_API_KEY", "").strip():
            return self._fred_csv(req)
        args = {"series_id": native, "observation_start": req["fetch_start"], "observation_end": req["end"],
                "units": "lin", "sort_order": "desc", "offset": 0, "limit": _MAX_ROWS}
        try:
            payload = self._call("fred", "fred_get_series", args)
        except ValueError as exc:
            message = str(exc)
            operational = re.search(r"(?i)\b429\b|\b5\d\d\b|rate.?limit|quota|timed?\s*out|timeout|unavailable", message)
            auth = re.search(r"(?i)\b40[13]\b|unauthoriz|forbidden|(?:invalid|rejected|missing)\s+(?:api\s*)?key|(?:api\s*)?key\s+(?:is\s+)?(?:invalid|rejected|missing)", message)
            auth = auth or re.search(r"(?i)\bapi_key\s+is\s+not\s+registered\b", message)
            if auth and not operational:
                return self._fred_csv(req)
            raise
        if payload.get("series_id") != native or not isinstance(payload.get("data"), list):
            raise ValueError("FRED response series identity mismatch")
        count, offset, limit = (payload.get(k) for k in ("total_observations", "data_offset", "data_limit"))
        if any(not isinstance(v, int) or isinstance(v, bool) for v in (count, offset, limit)) or count < 0 or offset != 0 or limit != _MAX_ROWS:
            raise ValueError("FRED native pagination metadata is invalid")
        if count > _MAX_ROWS:
            raise ValueError("FRED history exceeds bound; narrow start/end")
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
                          notes=_clean(payload.get("notes")),
                          provenance={"metadata_fields": authority, "native_complete": True, "native_count": count,
                                      "vintage_status": "not supplied by native handler", "numeric_lexemes": "native handler parses floats; null may also represent invalid upstream numeric text"})

    def _fred_csv(self, req):
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?" + urlencode({"id": req["native"], "cosd": req["fetch_start"], "coed": req["end"]})
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
                raise ValueError("FRED CSV observation limit exceeded")
        self._local.receipts = [{"tool": "fred_csv", "sha256": hashlib.sha256(raw).hexdigest()}]
        series = self._base(req, observations=rows, source_url=f"https://fred.stlouisfed.org/series/{req['native']}", api_url=url,
                            provenance={"metadata_origin": "curated_catalog" if catalog.lookup(req["base"]) else "unknown",
                                        "vintage_status": "not available in keyless CSV"})
        series.route = "fred_csv"
        if not series.title:
            series.title = "FRED series " + req["native"]
        return series

    def _bls_quota(self):
        if self._env.get("BLS_API_KEY", "").strip():
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
                        raise ValueError("BLS quota record corrupt; quota cannot safely be established") from None
                if value["count"] >= 20:
                    raise ValueError("BLS keyless daily quota reached (20 requests); retry tomorrow")
                value["count"] += 1
                _atomic(path, _bytes(value))

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
            high = int(last)
            while high >= int(first):
                low = max(int(first), high - 9)
                self._remaining()
                self._bls_quota()
                args = {"series_ids": list(gathered), "start_year": str(low), "end_year": str(high)}
                payload = self._call("bls", "get_multiple_series", args)
                if payload.get("status") != "REQUEST_SUCCEEDED":
                    raise ValueError(self._redact("BLS request failed: " + str(payload.get("message", "invalid status"))))
                if payload.get("message"):
                    raise ValueError(self._redact("BLS response has warnings: " + str(payload["message"])))
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
                        flag_values = ["preliminary" if f["code"] == "P" else "observed" if f["code"] == "R" else "unknown" for f in notes]
                        flag = _status_flag(";".join(flag_values)) if flag_values else "observed"
                        normalized_date = date(int(item["year"]), month, 1).isoformat()
                        raw_status[native][normalized_date] = notes
                        gathered[native].append((Observation(normalized_date, item.get("value"), flag), period[0]))
                omitted.update(set(gathered) - seen)
                chunks.append({"start_year": low, "end_year": high, "returned_ids": sorted(seen)})
                high = low - 1
            for req in group:
                if req["native"] in omitted:
                    output[req["series"]] = self._error(req["series"], "BLS omitted the requested series from at least one year chunk")
                    continue
                rows = gathered[req["native"]]
                if not rows:
                    output[req["series"]] = self._error(req["series"], "BLS returned no observations for this series")
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
        payload = self._call("bis", "fetch_dataset", args)
        if payload.get("flow_ref") != ref:
            raise ValueError("BIS returned a different flow/version")
        observations, attributes = self._sdmx_rows(req, payload, dims)
        return self._base(req, observations=observations, frequency=_frequency(dims.get("FREQ")),
                          units=_sdmx_units(req, attributes),
                          source_url=f"https://data.bis.org/topics/{meta['topic']}/BIS,{flow},{meta['version']}/{key}",
                          api_url=f"https://stats.bis.org/api/v2/data/dataflow/BIS/{flow}/{meta['version']}/{key}?" + urlencode({"startPeriod": req["fetch_start"], "endPeriod": req["end"], "format": "csv", "labels": "both"}),
                          provenance={"raw_status": attributes.pop("raw_status", {}), "attributes": attributes, "flow_ref": ref, "dimensions": dims})

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
        projection_family = meta["base_flow"] == "WEO"
        if projection_family:
            for obs in observations:
                if not obs.flag:
                    obs.flag = "unknown"
        return self._base(req, observations=observations, frequency=req["frequency"],
                          units=_sdmx_units(req, attributes),
                          source_url=f"https://data.imf.org/en/datasets/{meta['agency']}:{meta['base_flow']}",
                          vintage=flow if "_VINTAGE" in flow else "",
                          notes="Observation status is unknown where not supplied; WEO mixes history, estimates and projections." if projection_family else "",
                          provenance={"raw_status": attributes.pop("raw_status", {}), "attributes": attributes, "database_id": flow, "dimensions": {k: v[0] for k, v in filters.items()},
                                      "projection_status": "per-observation only; no inferred cutoff", "vintage_availability": "not supplied"})

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
                if _wb_unit_parts(str(page_metadata["measurement_unit"])) != _wb_unit_parts(str(metadata.get("measurement_unit", ""))):
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
        observations, per_row_units = [], set()
        projection_family = database in ("IMF_WEO", "WB_GEP")
        for row in rows:
            if row.get("REF_AREA") != country:
                raise ValueError("Data360 returned a different geography")
            if any(row.get(k) not in (None, "", "_T", "_Z") for k in ("SEX", "AGE", "URBANISATION", "COMP_BREAKDOWN_1", "COMP_BREAKDOWN_2")):
                raise ValueError("Data360 returned ambiguous disaggregations")
            if "OBS_VALUE" not in row:
                raise ValueError("Data360 observation value missing")
            observations.append(Observation(_native_period(row["TIME_PERIOD"], "A"), row["OBS_VALUE"], "unknown"))
            row_attributes = {k: [str(row[k])] for k in ("UNIT_MEASURE", "UNIT_MEASURE_NAME", "UNIT_MULT") if row.get(k) not in (None, "")}
            if observations[-1].value is not None:
                per_row_units.add(_wb_unit_parts(_wb_units(row_attributes, metadata)))
            for k in ("UNIT_MEASURE", "UNIT_MEASURE_NAME", "UNIT_MULT"):
                if row.get(k) not in (None, ""):
                    attributes.setdefault(k, set()).add(str(row[k]))
        if any(len(v) > 1 for v in attributes.values()):
            raise ValueError("Data360 returned inconsistent units or scale")
        if len(per_row_units) > 1:
            raise ValueError("Data360 observation-level units or scale are inconsistent")
        units = _wb_units(attributes, metadata)
        return self._base(req, observations=observations, geography=country, frequency="A", units=units,
                          title=metadata.get("indicator_name") or metadata.get("name"),
                          source_url=f"https://data360.worldbank.org/en/indicator/{indicator}",
                          notes="Native Data360 strips observation status; historical/estimate/projection boundary is unknown." if projection_family else "Native Data360 strips observation status and may omit upstream metadata warnings.",
                          provenance={"database_id": database, "indicator_id": indicator, "country_code": country,
                                      "attributes": {k: sorted(v) for k, v in attributes.items()}, "projection_status": "not supplied",
                                      "native_periodicity": native_frequency, "metadata": metadata, "pages": page_receipts,
                                      "native_complete": True, "native_rows": len(rows),
                                      "resolution_safe": False})

    def _fetch_usgov(self, req):
        name, recipe, param = catalog.resolve_usgov_recipe(req["native"])
        if name == "sec":
            # Handler classifies by filing form and drops duration/start/accession;
            # its last 20 annual-form rows are not an annual time series.
            return self._error(req["series"], "SEC native concept handler drops period starts/filing provenance and caps history; complete annual or as-of series is unavailable")
        if name == "spending/total":
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
                periods[begin] = {"calendar": "us_federal_fiscal_year", "label": label, "start": begin, "end": finish,
                                  "covered_start": covered_start, "covered_end": covered_end,
                                  "complete": covered_start == begin and covered_end == finish and today > finish}
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


atexit.register(reset_data_sources_for_tests)
