"""Backtest mode in the official-data client (design §5, "Official data").

A fake MCP hub plays FRED: with ``vintage_dates`` it answers the values as published
on that date (fewer, older observations), without it the current revision.  The
keyless CSV route is a fake ``http_get``.  No network, injected clock.
"""

from __future__ import annotations

import json
import os
import sys

_BRIDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           "deerflow_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

import backtest_cutoff as bt  # noqa: E402
import data_sources as ds  # noqa: E402
from data_mcp import CallResult  # noqa: E402

NOW = 1791763200.0  # 2026-10-12T00:00:00Z

# Unemployment rate: the current revision runs to 2026-09.  The 2024-11-01 vintage
# (October's figure was released that morning) runs to 2024-10, with the values as
# first published, which differ from today's revision.
CURRENT = [{"date": f"{year}-{month:02d}-01", "value": 4.0 + month / 100}
           for year in (2024, 2025, 2026) for month in range(1, 13) if (year, month) <= (2026, 9)]
VINTAGE_2024_11_01 = [{"date": f"2024-{month:02d}-01", "value": 3.9 + month / 100} for month in range(1, 11)]


class Hub:
    def __init__(self):
        self.calls = []

    def call(self, provider, tool, args, **kw):
        self.calls.append(json.loads(json.dumps(args)))
        rows = VINTAGE_2024_11_01 if args.get("vintage_dates") == "2024-11-01" else CURRENT
        data = sorted((row for row in rows
                       if args["observation_start"] <= row["date"] <= args["observation_end"]),
                      key=lambda row: row["date"], reverse=True)
        payload = {"series_id": args["series_id"], "title": "Unemployment Rate", "units": "Percent",
                   "frequency": "Monthly", "seasonal_adjustment": "Seasonally Adjusted",
                   "total_observations": len(data), "data_offset": 0, "data_limit": 5000, "data": data}
        return CallResult(True, json.dumps(payload), None, 0.0)

    def status(self):
        return {p: {"state": "ready", "error": None} for p in ds.PROVIDERS}

    def start(self, names, **kw):
        pass

    def close(self):
        pass


def _source(tmp_path, *, key="synthetic-key-123456", http_get=None):
    hub = Hub()
    env = {"DATA_SOURCES_ENABLED": "true", "FRED_API_KEY": key}
    source = ds.DataSources(hub, env=env, cache_dir=tmp_path / "cache", clock=lambda: NOW,
                            **({"http_get": http_get} if http_get else {}))
    return source, hub


def _policy(strict=True):
    return bt.parse_policy({"as_of": "2024-11-01", "strict": strict})


def test_live_requests_are_unchanged(tmp_path):
    source, hub = _source(tmp_path)
    result = source.get("fred:UNRATE")
    assert "vintage_dates" not in hub.calls[-1]
    assert (hub.calls[-1]["observation_start"], hub.calls[-1]["observation_end"]) == ("2016-10-12", "2026-10-12")
    assert result.observations[-1].date == "2026-09-01" and "backtest" not in result.provenance


def test_fred_api_reads_the_as_of_vintage(tmp_path):
    source, hub = _source(tmp_path)
    source.apply_backtest(_policy())
    result = source.get("fred:UNRATE")
    args = hub.calls[-1]
    assert args["vintage_dates"] == "2024-11-01" and args["observation_end"] == "2024-11-01"
    assert args["observation_start"] == "2014-11-01"  # ten years back from the as-of date
    assert [o.date for o in result.observations][-2:] == ["2024-09-01", "2024-10-01"]
    assert result.observations[-1].value == 3.9 + 10 / 100  # the value as published then
    assert result.provenance["backtest"] == {"as_of": "2024-11-01", "strict": True,
                                             "basis": "as_of_vintage", "dropped_observations": 0}
    assert result.provenance["vintage_status"].startswith("as published on 2024-11-01")
    assert "vintage_dates=2024-11-01" in result.api_url


def test_backtest_and_live_never_share_cache_entries(tmp_path):
    source, hub = _source(tmp_path)
    source.get("fred:UNRATE", start="2024-01-01", end="2024-10-31")
    source.get("fred:UNRATE", start="2024-01-01", end="2024-10-31")
    assert len(hub.calls) == 1
    source.apply_backtest(_policy())
    vintage = source.get("fred:UNRATE", start="2024-01-01", end="2024-10-31")
    assert len(hub.calls) == 2 and vintage.observations[-1].value == 3.9 + 10 / 100
    source.get("fred:UNRATE", start="2024-01-01", end="2024-10-31")
    assert len(hub.calls) == 2  # its own cached entry
    source.apply_backtest(_policy(strict=False))
    source.get("fred:UNRATE", start="2024-01-01", end="2024-10-31")
    assert len(hub.calls) == 3  # strictness is part of the key


def _csv_get(calls):
    def get(url, **kw):
        calls.append(url)
        return ("observation_date,UNRATE\n" + "".join(
            f"{row['date']},{row['value']}\n" for row in CURRENT)).encode()
    return get


def test_current_revision_route_applies_the_release_lag(tmp_path):
    calls = []
    source, hub = _source(tmp_path, key="", http_get=_csv_get(calls))
    source.apply_backtest(_policy())
    result = source.get("fred:UNRATE", start="2024-01-01")
    assert not hub.calls and "coed=2024-11-01" in calls[0]
    # Strict: a month needs 45 days after its end; September (ends 09-30) is too recent.
    assert result.observations[-1].date == "2024-08-01"
    assert result.provenance["backtest"]["basis"] == "current_revision"
    # September, October and November (dated on the as-of day, its month still open).
    assert result.provenance["backtest"]["dropped_observations"] == 3
    calls.clear()
    source.apply_backtest(_policy(strict=False))
    lenient = source.get("fred:UNRATE", start="2024-01-01")
    assert lenient.observations[-1].date == "2024-10-01"  # ended before the as-of day


def test_windows_after_the_cutoff_are_refused(tmp_path):
    source, hub = _source(tmp_path)
    source.apply_backtest(_policy())
    error = source.get("fred:UNRATE", start="2025-01-01")
    assert isinstance(error, ds.DataError) and error.code == "invalid_window"
    assert "after the backtest cutoff" in error.message and not hub.calls
    # An explicit end after the cutoff is clamped to it.
    source.get("fred:UNRATE", start="2024-01-01", end="2026-06-30")
    assert hub.calls[-1]["observation_end"] == "2024-11-01"


def test_a_series_with_nothing_known_at_the_cutoff_fails(tmp_path):
    calls = []
    source, _ = _source(tmp_path, key="", http_get=_csv_get(calls))
    source.apply_backtest(bt.parse_policy({"as_of": "2024-01-20"}))
    error = source.get("fred:UNRATE", start="2024-01-01")
    assert isinstance(error, ds.DataError) and error.code == "invalid_window"
    assert "known at the backtest cutoff" in error.message


def test_fiscal_period_end_from_the_provider_decides():
    policy = bt.parse_policy({"as_of": "2024-11-01", "strict": False})
    # FY2024 starts 2023-10-01 and ends 2024-09-30: admitted; read as a calendar year it would end 2023-12-31.
    assert bt.observation_admitted("2023-10-01", "A", policy, vintage=False, end="2024-09-30")
    assert not bt.observation_admitted("2024-10-01", "A", policy, vintage=False, end="2025-09-30")
