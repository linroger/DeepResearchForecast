"""Explicit, read-only Gamma/CLOB probe through the configured production client.

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


def probe_markets(query, *, token_id=None, timeout=10.0, limit=3):
    # Resolve the exact production client lazily; module import performs no IO.
    from app.utils.prediction_markets import PolymarketClient, CLOB_BASE_URL
    from app.services.forecast_inputs_health import build_inputs_health

    client = PolymarketClient(timeout=timeout)
    start = time.monotonic()
    markets = client.snapshot_for_queries([query], max_total=limit, min_volume=0)
    snapshot_at = datetime.now(timezone.utc).isoformat()
    gamma_errors = dict(client.transport_errors)
    gamma_status = ("disabled" if not client.enabled else "offline" if gamma_errors
                    else "fresh" if markets else "empty")
    gamma_ms = round((time.monotonic() - start) * 1000, 2)
    if token_id is None:
        for market in markets:
            if market.get("clob_yes_token_id"):
                token_id = market["clob_yes_token_id"]
                break
    history, clob_status, clob_ms = [], "unknown", None
    if token_id and client.enabled:
        start = time.monotonic()
        prior_errors = dict(client.transport_errors)
        history = client.fetch_price_history(str(token_id), days=0)
        clob_ms = round((time.monotonic() - start) * 1000, 2)
        clob_status = ("offline" if client.transport_errors != prior_errors
                       else "fresh" if history else "empty")
    elif not client.enabled:
        clob_status = "disabled"
    return {
        "schemaVersion": "market-probe/v1", "as_of": snapshot_at,
        "gamma": {"endpoint": _safe_endpoint(client.base_url), "status": gamma_status,
                  "latency_ms": gamma_ms, "rows": markets[:limit], "errors": gamma_errors},
        "clob": {"endpoint": _safe_endpoint(CLOB_BASE_URL), "status": clob_status,
                 "latency_ms": clob_ms, "rows": history[:limit],
                 "reason": "missing_token_id" if clob_status == "unknown" else None},
        "inputs_health": build_inputs_health(markets={"markets": markets, "as_of": snapshot_at,
                                                     "status": gamma_status}, as_of=snapshot_at),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Plain market query; no LLM query generation")
    parser.add_argument("--token-id", help="Optional CLOB token; otherwise use a returned market")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 60 or not 1 <= args.limit <= 20:
        parser.error("timeout must be (0,60] seconds; limit must be 1..20")
    if not args.query.strip():
        parser.error("query must be nonempty")
    result = probe_markets(args.query, token_id=args.token_id, timeout=args.timeout, limit=args.limit)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["gamma"]["status"] == "fresh" and result["clob"]["status"] == "fresh" else 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
