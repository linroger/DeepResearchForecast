#!/usr/bin/env python3
"""Paced live sweep of the official-data catalog through the real data MCP servers.

Every requested id is fetched through ``data_sources.DataSources`` and the process hub,
exactly as research runs fetch it (default windows, normalization, unit pins, fallbacks),
and the outcome is written to a JSON report. Exit status: 0 only when every requested id
returned a normalized series; 1 when any requested id failed (or none was requested);
2 on a usage error.

Budgets
-------
* FRED tool calls are paced by the hub's rolling-minute window; this script sets
  ``DATA_SOURCES_FRED_PER_MINUTE=30`` unless the environment already sets it.
* BLS ids go out in batched requests of up to 25 ids and one year chunk (``--bls-start``
  defaults to January 1 of last year), so the whole BLS catalog costs ceil(n / 25) requests.
* IMF calls take about 40 s each, so IMF ids are capped (``--max-per-provider imf=6`` by
  default; ``imf=all`` lifts the cap). Capped ids are reported as skipped, not failed.
* Recipes whose provider key is not configured (EIA/BEA) are skipped, not failed.

The default cache directory is a fresh temporary directory, so every result is a live fetch.

Usage::

    python scripts/datamcp_smoke.py                                  # whole catalog
    python scripts/datamcp_smoke.py --providers fred,usgov --report out.json
    python scripts/datamcp_smoke.py --series fred:UNRATE usgov:eia/electricity_sales/US.COM
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from collections import Counter
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

_BRIDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "deerflow_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

import data_catalog as catalog  # noqa: E402
import data_sources as ds  # noqa: E402

DEFAULT_CAPS = {"imf": 6}
DEFAULT_DEADLINE_S = 1800.0
_KEY_NAMES = ("FRED_API_KEY", "BLS_API_KEY", "EIA_API_KEY", "BEA_API_KEY", "CENSUS_API_KEY", "DATA_GOV_API_KEY")


def _caps(values: List[str]) -> Dict[str, Optional[int]]:
    caps: Dict[str, Optional[int]] = dict(DEFAULT_CAPS)
    for value in values:
        provider, sep, count = value.partition("=")
        provider = provider.strip().lower()
        if not sep or provider not in ds.PROVIDERS or not (count == "all" or count.isdigit() and int(count) >= 1):
            raise ValueError(f"--max-per-provider expects <provider>=<N>|all, got {value!r}")
        caps[provider] = None if count == "all" else int(count)
    return caps


def _family(entry) -> str:
    """Dataset family within a provider (IMF/BIS flow, Data360 database, usgov recipe)."""
    native = entry.native
    if entry.provider in ("imf", "bis"):
        return native.split("/")[0]
    if entry.provider == "wb":
        return "_".join(native.split("_")[:2])
    if entry.provider == "usgov":
        resolved = catalog.resolve_usgov_recipe(native)
        return resolved[0] if resolved else native
    return entry.provider


def select(*, providers: Optional[List[str]], series: Optional[List[str]], caps: Dict[str, Optional[int]],
           env) -> tuple[List[str], Dict[str, str]]:
    """(requested ids, {skipped id: reason}). Explicit ids are never capped; a capped provider's
    ids are picked round-robin across its dataset families, so a small cap still covers each flow."""
    skipped: Dict[str, str] = {}
    if series:
        requested = []
        for raw in series:
            parsed = ds.parse_series_id(raw)
            requested.append(":".join(parsed) if parsed else raw)
        return list(dict.fromkeys(requested)), skipped
    wanted = set(providers or ds.PROVIDERS)
    families: Dict[str, Dict[str, List[str]]] = {}
    for entry in catalog.CATALOG:
        if entry.provider not in wanted:
            continue
        if not catalog.entry_available(entry, env=env):
            skipped[entry.series] = f"{entry.requires_key} not configured"
            continue
        families.setdefault(entry.provider, {}).setdefault(_family(entry), []).append(entry.series)
    requested: List[str] = []
    for provider, groups in families.items():
        cap = caps.get(provider)
        queues = [list(ids) for ids in groups.values()]
        picked: List[str] = []
        while any(queues) and (cap is None or len(picked) < cap):
            for queue in queues:
                if queue and (cap is None or len(picked) < cap):
                    picked.append(queue.pop(0))
        chosen = set(picked)
        for ids in groups.values():
            for sid in ids:
                if sid in chosen:
                    requested.append(sid)
                else:
                    skipped[sid] = f"{provider} cap {cap} (--max-per-provider)"
    return requested, skipped


def _row(sid: str, value: Any) -> Dict[str, Any]:
    if not isinstance(value, ds.Series):
        return {"ok": False, "code": getattr(value, "code", "provider_error"),
                "retryable": bool(getattr(value, "retryable", False)),
                "message": getattr(value, "message", str(value))}
    latest = ds.latest_observed(value)
    entry = catalog.lookup(sid.partition("#")[0])
    row = {"ok": True, "route": value.route, "observations": len(value.observations),
           "first": value.observations[0].date, "last": value.observations[-1].date,
           "latest_observed": {"date": latest.date, "value": latest.value} if latest else None,
           "units": value.units, "frequency": value.frequency,
           "units_match_catalog": entry is None or value.units == entry.units,
           "kinds": dict(Counter(ds.observation_kind(o, value) for o in value.observations))}
    for name in ("fallback_reason", "server_aggregation", "latest_daily"):
        if name in value.provenance:
            row[name] = value.provenance[name]
    return row


def run(source: ds.DataSources, requested: List[str], *, bls_start: str, deadline_s: float,
        log=print) -> Dict[str, Dict[str, Any]]:
    """Fetch ``requested`` with one concurrent get_many per provider; returns {id: report row}."""
    groups: Dict[str, List[str]] = {}
    for sid in requested:
        groups.setdefault(sid.partition(":")[0].lower(), []).append(sid)
    results: Dict[str, Dict[str, Any]] = {}
    lock = threading.Lock()

    def sweep(provider: str, ids: List[str]) -> None:
        started = time.monotonic()
        options = {"start": bls_start} if provider == "bls" else {}
        try:
            values = source.get_many(ids, deadline_s=deadline_s, **options)
        except Exception as exc:  # get_many never raises by contract; report it if it ever does
            values = {sid: ds.DataError(sid, f"{type(exc).__name__}: {exc}") for sid in ids}
        elapsed = round(time.monotonic() - started, 1)
        with lock:
            for sid in ids:
                row = _row(sid, values.get(sid) or ds.DataError(sid, "no result returned", code="provider_error"))
                row["group_elapsed_s"] = elapsed
                results[sid] = row
                if row["ok"]:
                    latest = row["latest_observed"] or {}
                    log(f"OK   {sid:48s} n={row['observations']:4d} route={row['route']:8s} "
                        f"latest={latest.get('date')} {latest.get('value')} {row['units'][:32]!r}")
                else:
                    log(f"FAIL {sid:48s} [{row['code']}] {row['message'][:160]}")

    threads = [threading.Thread(target=sweep, args=(p, ids), name=f"smoke-{p}") for p, ids in groups.items()]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return {sid: results[sid] for sid in requested}


def summarize(results: Dict[str, Dict[str, Any]], skipped: Dict[str, str]) -> Dict[str, Dict[str, int]]:
    summary: Dict[str, Dict[str, int]] = {}
    for sid, row in results.items():
        bucket = summary.setdefault(sid.partition(":")[0], {"requested": 0, "ok": 0, "failed": 0, "skipped": 0})
        bucket["requested"] += 1
        bucket["ok" if row["ok"] else "failed"] += 1
    for sid in skipped:
        bucket = summary.setdefault(sid.partition(":")[0], {"requested": 0, "ok": 0, "failed": 0, "skipped": 0})
        bucket["skipped"] += 1
    return dict(sorted(summary.items()))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Paced live sweep of the official-data catalog.")
    parser.add_argument("--providers", help="comma-separated providers (default: all six)")
    parser.add_argument("--series", nargs="+", help="explicit series ids instead of the catalog")
    parser.add_argument("--max-per-provider", action="append", default=[], metavar="PROVIDER=N|all",
                        help="cap catalog ids per provider (default imf=6)")
    parser.add_argument("--bls-start", help="start date for BLS ids (default: Jan 1 of last year, one request chunk)")
    parser.add_argument("--cache-dir", help="data cache directory (default: a fresh temporary directory)")
    parser.add_argument("--deadline", type=float, default=DEFAULT_DEADLINE_S, help="seconds per provider group")
    parser.add_argument("--report", help="JSON report path (default: <cache dir>/datamcp-smoke-report.json)")
    return parser


def main(argv: Optional[List[str]] = None, *, source: Optional[ds.DataSources] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        caps = _caps(args.max_per_provider)
        providers = None
        if args.providers:
            providers = [p.strip().lower() for p in args.providers.split(",") if p.strip()]
            unknown = sorted(set(providers) - set(ds.PROVIDERS))
            if unknown:
                raise ValueError(f"unknown provider(s): {', '.join(unknown)}")
        bls_start = args.bls_start or f"{datetime.now(timezone.utc).year - 1}-01-01"
        date.fromisoformat(bls_start)
        if not args.deadline > 0:
            raise ValueError("--deadline must be positive")
    except ValueError as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return 2
    cache_dir = args.cache_dir or tempfile.mkdtemp(prefix="drf-datamcp-smoke-")
    own = source is None
    if own:
        # Read when the process hub is created: its logs and the usgov server cache follow the
        # cache directory, and FRED tool calls are paced at 30 a minute unless configured.
        os.environ["DATA_SOURCES_CACHE_DIR"] = cache_dir
        os.environ.setdefault("DATA_SOURCES_FRED_PER_MINUTE", "30")
    requested, skipped = select(providers=providers, series=args.series, caps=caps, env=os.environ)
    source = source or ds.DataSources(cache_dir=cache_dir)
    started = time.monotonic()
    report: Dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "options": {"providers": providers or list(ds.PROVIDERS), "series": args.series, "caps": caps,
                    "bls_start": bls_start, "deadline_s": args.deadline, "cache_dir": cache_dir,
                    "fred_calls_per_minute": os.environ.get("DATA_SOURCES_FRED_PER_MINUTE")},
        "keys": {name: "set" if (os.environ.get(name) or "").strip() else "not set" for name in _KEY_NAMES},
    }
    try:
        report["providers_before"] = source.providers()
        print(f"requested {len(requested)} ids, skipped {len(skipped)}; providers {report['providers_before']}", flush=True)
        results = run(source, requested, bls_start=bls_start, deadline_s=args.deadline,
                      log=lambda line: print(line, flush=True))
        report["providers_after"] = source.providers()
        report["tool_calls"] = {p: {k: s.get(k) for k in ("calls", "failures")} for p, s in source.hub_status().items()}
    finally:
        if own:
            source.close()
    report.update(wall_s=round(time.monotonic() - started, 1),
                  summary=summarize(results, skipped), results=results, skipped=skipped)
    path = args.report or os.path.join(cache_dir, "datamcp-smoke-report.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1, ensure_ascii=False, default=str)
    failed = [sid for sid, row in results.items() if not row["ok"]]
    print(f"SUMMARY {json.dumps(report['summary'])} wall={report['wall_s']}s report={path}", flush=True)
    for sid in failed:
        print(f"  FAILED {sid} [{results[sid]['code']}] {results[sid]['message'][:200]}", flush=True)
    return 0 if requested and not failed else 1


if __name__ == "__main__":
    sys.exit(main())
