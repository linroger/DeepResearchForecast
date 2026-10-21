"""No-cost live smoke of the backtest cutoff against free public endpoints (no LLM, no keys).

Run: backend/.venv/bin/python docs/handoff/backtest/free_endpoint_smoke.py > out.json
Wayback CDX, Polymarket Gamma + CLOB and FRED's keyless CSV only; nothing is written.
"""
import json, os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "deerflow_bridge"))
import backtest_cutoff as bt
policy = bt.parse_policy({"as_of": "2024-11-01", "strict": True, "archive": "wayback"})
os.environ["DRF_BACKTEST_POLICY"] = policy.to_env()
out = {"as_of": policy.as_of_iso}

# 1. Wayback: last capture at or before the cutoff of a page edited after it.
snap, status = bt.lookup_snapshot("https://en.wikipedia.org/wiki/2024_United_States_presidential_election", policy)
out["wayback"] = {"status": status, **({"timestamp": snap.timestamp, "url": snap.url,
                  "captured_on_or_before_cutoff": snap.captured <= policy.cutoff} if snap else {})}
out["run_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds")

# 2. Polymarket: the bridge's as-of snapshot of the 2024 election.
import deerflow_research as d
diagnostics = {}
rows = d._pm_snapshot(["presidential election winner 2024"], per_query=3, max_total=4, diagnostics=diagnostics)
out["polymarket"] = {"diagnostics": diagnostics,
                     "rows": [{k: r.get(k) for k in ("market_id", "question", "implied_yes_prob", "price_as_of", "price_basis")} for r in rows],
                     "leaked_fields": sorted({k for r in rows for k in r if k in ("outcome_prices", "outcomePrices", "closed", "one_day_price_change", "best_bid", "best_ask")})}

# 3. FRED keyless CSV (current revision + strict release lag), via DataSources with no hub calls.
import data_sources as ds
with tempfile.TemporaryDirectory() as cache:
    source = ds.DataSources(env={"DATA_SOURCES_ENABLED": "true", "FRED_API_KEY": ""}, cache_dir=cache)
    source.apply_backtest(policy)
    series = source.get("fred:UNRATE", start="2024-01-01", deadline_s=30)
    if isinstance(series, ds.DataError):
        out["fred_csv"] = {"error": series.message, "code": series.code}
    else:
        out["fred_csv"] = {"route": series.route, "last_observation": series.observations[-1].date,
                           "count": len(series.observations), "backtest": series.provenance.get("backtest"),
                           "api_url": series.api_url}
    source.close()
print(json.dumps(out, indent=2, ensure_ascii=False))
