"""Backtest mode in the research-stage market snapshot (design §5, "Prediction markets").

A fake ``_polymarket_get`` plays Gamma public-search (a resolved election event with
markets open, closed and not yet opened at the cutoff) and CLOB prices-history (hourly
points on both sides of the cutoff).  No network, no LLM.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BRIDGE_DIR = os.path.join(_REPO_ROOT, "deerflow_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

import backtest_cutoff as bt  # noqa: E402
import deerflow_research as d  # noqa: E402

POLICY = bt.parse_policy({"as_of": "2024-11-01"})
CUTOFF = POLICY.cutoff_ts


def _market(mid, question, *, start, closed_time=None, volume="1500000", prices='["1", "0"]'):
    return {"id": mid, "question": question, "startDate": start, "createdAt": start,
            "closed": closed_time is not None, "closedTime": closed_time, "endDate": "2024-11-05T12:00:00Z",
            "outcomes": '["Yes", "No"]', "outcomePrices": prices, "volume": volume, "liquidity": "0",
            "oneDayPriceChange": "0.4", "bestBid": "0.999", "bestAsk": "1",
            "umaResolutionStatus": "resolved", "clobTokenIds": f'["{mid}-yes", "{mid}-no"]'}


EVENTS = {"events": [{
    "title": "Presidential Election Winner 2024", "slug": "presidential-election-winner-2024",
    "markets": [
        _market("open", "Will Donald Trump win the 2024 US Presidential Election?",
                start="2024-01-04T22:58:00Z", closed_time="2024-11-06 15:17:41+00"),
        _market("closed-early", "Will Joe Biden be the Democratic nominee?",
                start="2024-01-04T22:58:00Z", closed_time="2024-08-20 10:00:00+00", prices='["0", "1"]'),
        _market("opened-late", "Will the winner be inaugurated on time?",
                start="2024-11-10T00:00:00Z", closed_time="2025-01-21 00:00:00+00"),
        _market("thin", "Will a third-party candidate win a state?",
                start="2024-01-04T22:58:00Z", closed_time="2024-11-06 15:00:00+00", volume="50"),
    ]}]}


class Polymarket:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, path, params, timeout=None, base_url=None):
        self.calls.append((path, dict(params)))
        if path == "/public-search":
            return EVENTS
        if path == "/prices-history":
            if params["market"] != "open-yes":
                return {"history": []}
            return {"history": [{"t": CUTOFF - 7200, "p": 0.6}, {"t": CUTOFF - 3600, "p": 0.59},
                                {"t": CUTOFF + 3600, "p": 0.93}, {"t": CUTOFF + 7 * 86400, "p": 1.0}]}
        raise AssertionError(path)


@pytest.fixture()
def polymarket(monkeypatch):
    fake = Polymarket()
    monkeypatch.setattr(d, "_polymarket_get", fake)
    monkeypatch.setenv("DRF_BACKTEST_POLICY", POLICY.to_env())
    return fake


def test_backtest_snapshot_searches_all_events_and_prices_at_the_cutoff(polymarket):
    diagnostics: dict = {}
    rows = d._pm_snapshot(["2024 presidential election"], diagnostics=diagnostics)
    search = [params for path, params in polymarket.calls if path == "/public-search"]
    assert search and "events_status" not in search[0]
    assert [row["market_id"] for row in rows] == ["open"]
    row = rows[0]
    assert row["implied_yes_prob"] == 0.59 and row["price_basis"] == "clob_history_at_cutoff"
    assert row["price_as_of"] == datetime.fromtimestamp(CUTOFF - 3600, timezone.utc).isoformat(timespec="seconds")
    history = [params for path, params in polymarket.calls if path == "/prices-history"]
    assert history == [{"market": "open-yes", "startTs": CUTOFF - 7 * 86400, "endTs": CUTOFF, "fidelity": 60}]
    text = json.dumps(rows)
    for leaked in ("outcomePrices", "outcome_prices", "one_day_price_change", "best_bid", "best_ask",
                   "umaResolutionStatus", "0.93", "closed"):
        assert leaked not in text
    assert diagnostics["backtest_priced_count"] == 1


def test_live_snapshot_is_unchanged(monkeypatch):
    fake = Polymarket()
    monkeypatch.setattr(d, "_polymarket_get", fake)
    monkeypatch.delenv("DRF_BACKTEST_POLICY", raising=False)
    rows = d._pm_snapshot(["2024 presidential election"])
    assert fake.calls == [("/public-search", {"q": "2024 presidential election", "limit_per_type": 8,
                                             "events_status": "active"})]
    assert rows == []  # every fixture market is closed: live keeps none


def test_chart_history_ends_at_the_cutoff(polymarket):
    series = d._pm_fetch_price_history("open-yes", days=90)
    params = [params for path, params in polymarket.calls if path == "/prices-history"][-1]
    assert params == {"market": "open-yes", "startTs": CUTOFF - 90 * 86400, "endTs": CUTOFF, "fidelity": 1440}
    assert series == [{"t": CUTOFF - 7200, "p": 0.6}, {"t": CUTOFF - 3600, "p": 0.59}]


def test_unusable_policy_never_reaches_current_prices(monkeypatch, tmp_path):
    fake = Polymarket()
    monkeypatch.setattr(d, "_polymarket_get", fake)
    monkeypatch.setenv("DRF_BACKTEST_POLICY", "{broken")
    monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "true")

    class Log:
        def write(self, level, message):
            pass

    meta: dict = {}
    d._collect_prediction_markets(tmp_path, "Will Trump win?", "report", meta, Log(), model_name="test")
    payload = json.loads((tmp_path / d.PREDICTION_MARKETS_FILENAME).read_text(encoding="utf-8"))
    assert payload["status"]["empty_reason"] == "backtest_policy_unusable" and payload["markets"] == []
    assert fake.calls == [] and d._pm_fetch_price_history("open-yes") == []


def test_collector_writes_an_as_of_snapshot_and_section(polymarket, monkeypatch, tmp_path):
    monkeypatch.setattr(d, "_pm_resolve_queries", lambda *args, **kwargs: ["2024 presidential election"])
    monkeypatch.setattr(d, "score_market_relevance", lambda question, markets, *args: {
        row["market_id"]: 9.0 for row in markets})
    monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "true")
    monkeypatch.setenv("PREDICTION_MARKETS_PRICE_HISTORY", "true")
    (tmp_path / d.PREDICTION_MARKET_CANDIDATES_FILENAME).write_text(
        json.dumps({"market_id": "tool-live", "question": "Will Trump win?", "implied_yes_prob": 0.99}) + "\n")
    (tmp_path / d.REPORT_FILENAME).write_text("# Report\n\nBody.\n", encoding="utf-8")
    d._set_pm_transport_unavailable(False)

    class Log:
        def write(self, level, message):
            pass

    meta: dict = {}
    d._collect_prediction_markets(tmp_path, "Will Trump win the 2024 election?", "# Report\n\nBody.\n",
                                  meta, Log(), model_name="test")
    payload = json.loads((tmp_path / d.PREDICTION_MARKETS_FILENAME).read_text(encoding="utf-8"))
    assert payload["as_of"] == POLICY.cutoff.isoformat()
    assert payload["backtest"]["price_basis"] == "clob_history_at_cutoff"
    assert [row["market_id"] for row in payload["markets"]] == ["open"]  # the live tool row is ignored
    report = (tmp_path / d.REPORT_FILENAME).read_text(encoding="utf-8")
    assert f"as of {POLICY.cutoff.isoformat()}" in report and "| 59% |" in report
    history = json.loads((tmp_path / d.PRICE_HISTORY_FILENAME).read_text(encoding="utf-8"))
    assert all(point["t"] <= CUTOFF for point in history["open"])
    assert meta["prediction_markets_as_of"] == POLICY.cutoff.isoformat()
