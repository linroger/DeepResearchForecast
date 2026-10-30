"""Explicit, read-only Gamma/CLOB probe through the research collector transport.

Import and --help are inert. Running the CLI makes public network requests and
must be separately authorized; test this entrypoint with a substituted transport.
No LLM, cache mutation, provider key or scheduling is involved.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit, urlunsplit


def _safe_endpoint(value):
    """Never print credentials or query parameters in configured mirror URLs."""
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "", ""))


def _error_counts(error):
    """Preserve transport classification without emitting exception text/URLs."""
    label = str(getattr(error, "error_class", "") or type(error).__name__)
    code = getattr(error, "http_status", None)
    return {f"{label}:{code}" if code is not None else label: 1}


def probe_markets(query, *, token_id=None, timeout=None, limit=3):
    # This is the same urllib helper used by _pm_snapshot and CLOB history.
    # It retains the collector's endpoints, UA, retries and default proxy/TLS
    # handling. Do not substitute the backend's separate httpx implementation.
    from app.services.official_data import bridge_module
    from app.services.forecast_inputs_health import build_inputs_health

    collector = bridge_module("deerflow_research")
    enabled = collector._env_flag("PREDICTION_MARKETS_ENABLED", True)
    start = time.monotonic()
    markets, gamma_errors = [], {}
    gamma_status = "disabled"
    if enabled:
        try:
            raw = collector._polymarket_get("/public-search", {
                "q": query, "limit_per_type": collector._pm_per_query(), "events_status": "active"},
                timeout=timeout)
            by_id = {}
            for event in raw.get("events", []) if isinstance(raw, dict) else []:
                if not isinstance(event, dict):
                    continue
                for item in event.get("markets") or []:
                    row = collector._pm_normalize_market(item, query, 0,
                        str(event.get("title") or ""), str(event.get("slug") or ""))
                    if row is not None:
                        by_id.setdefault(row["market_id"], row)
            markets = collector._pm_cap_per_event(
                sorted(by_id.values(), key=lambda row: -row["volume"]), 3, limit)
            gamma_status = "fresh" if markets else "empty"
        except Exception as error:
            gamma_errors = _error_counts(error)
            gamma_status = "offline"
    snapshot_at = datetime.now(timezone.utc).isoformat()
    gamma_ms = round((time.monotonic() - start) * 1000, 2)
    if token_id is None:
        for market in markets:
            if market.get("clob_yes_token_id"):
                token_id = market["clob_yes_token_id"]
                break
    history, clob_status, clob_ms = [], "unknown", None
    if token_id and enabled:
        start = time.monotonic()
        try:
            # The collector's live _pm_fetch_price_history uses interval=1d
            # and a 15s timeout; an explicit CLI timeout overrides both probes.
            raw = collector._polymarket_get("/prices-history", {"market": str(token_id), "interval": "1d"},
                timeout=15.0 if timeout is None else timeout, base_url=collector._CLOB_BASE_URL)
            history = collector._pm_parse_price_history(raw, days=0)
            clob_status = "fresh" if history else "empty"
        except Exception:
            clob_status = "offline"
        clob_ms = round((time.monotonic() - start) * 1000, 2)
    elif not enabled:
        clob_status = "disabled"
    return {
        "schemaVersion": "market-probe/v1", "as_of": snapshot_at,
        "gamma": {"endpoint": _safe_endpoint(collector._POLYMARKET_BASE_URL), "status": gamma_status,
                  "latency_ms": gamma_ms, "rows": markets[:limit], "errors": gamma_errors},
        "clob": {"endpoint": _safe_endpoint(collector._CLOB_BASE_URL), "status": clob_status,
                 "latency_ms": clob_ms, "rows": history[:limit],
                 "reason": "missing_token_id" if clob_status == "unknown" else None},
        "inputs_health": build_inputs_health(markets={"markets": markets,
            "as_of": snapshot_at if markets else None,
            "status": {"state": gamma_status, "attempted_at": snapshot_at}}, as_of=snapshot_at),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Plain market query; no LLM query generation")
    parser.add_argument("--token-id", help="Optional CLOB token; otherwise use a returned market")
    parser.add_argument("--timeout", type=float, default=None,
                        help="Override both transport timeouts; otherwise use collector defaults")
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args(argv)
    if (args.timeout is not None and not 0 < args.timeout <= 60) or not 1 <= args.limit <= 20:
        parser.error("timeout must be (0,60] seconds; limit must be 1..20")
    if not args.query.strip():
        parser.error("query must be nonempty")
    result = probe_markets(args.query, token_id=args.token_id, timeout=args.timeout, limit=args.limit)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["gamma"]["status"] == "fresh" and result["clob"]["status"] == "fresh" else 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
