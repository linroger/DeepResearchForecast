#!/usr/bin/env python3
"""Bounded read-only source compatibility check, separate from offline acceptance.

NEWSAPI_API_KEY is inherited in process memory, never an argument or output.
No dotenv, model, application, saved-run or service access is used.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--query", default="energy")
    parser.add_argument("--markets", action="store_true")
    parser.add_argument("--reddit", action="store_true")
    args = parser.parse_args()
    folder = args.output_dir.absolute()
    if folder.exists() or folder.parent.resolve() != folder.parent:
        parser.error("output directory must be new beneath a canonical existing parent")
    # A compatibility check owns no saved research budget or attempt lineage.
    for name in list(os.environ):
        if name.startswith("RESEARCH_BUDGET_"):
            del os.environ[name]
    os.environ.update(NEWS_CONTEXT_ENABLED="true", NEWSAPI_ENABLED="true",
                      NEWSAPI_MAX_REQUESTS="1", REDDIT_MAX_REQUESTS="1",
                      REDDIT_SIGNALS_ENABLED="true" if args.reddit else "false",
                      MARKET_INTELLIGENCE_ENABLED="true" if args.markets else "false",
                      MARKET_INTELLIGENCE_MAX_REQUESTS="4")
    sys.path.insert(0, str(ROOT))
    from deerflow_bridge import news_signals
    client = news_signals.get_context_client(
        folder, question="Read-only source compatibility: " + args.query,
        language="en", as_of=datetime.now(timezone.utc).date().isoformat(),
    )
    results = [client.search_news(args.query)]
    if args.reddit:
        results.append(client.search_social(args.query))
    if args.markets:
        results.append(client.market_compare(args.query))
    snapshot = client.seal()
    receipt = {
        "schema": "oddsense-live-compatibility/v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "model_calls": 0, "saved_runs_accessed": False,
        "results": [{"provider": result.get("provider"),
                     "status": result.get("status"),
                     "items": len(result.get("items") or [])} for result in results],
        "snapshot_sha256": snapshot.get("sha256"),
        "source_sha256": {
            name: hashlib.sha256((ROOT / "deerflow_bridge" / name).read_bytes()).hexdigest()
            for name in ("news_signals.py", "market_intelligence.py")
        },
        "scope": "Live source compatibility only; not paid-model, forecast-quality or deployment proof.",
    }
    (folder / "compatibility.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
