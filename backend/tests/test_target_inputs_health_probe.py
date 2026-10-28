"""Typed status, configured transport and cadence checks; no external calls."""
import json

import pytest

from app.config import Config
from app.services.forecast_inputs_health import build_inputs_health
from app.services import resolution_autorun as autorun
from app.utils import prediction_markets as pm
from scripts import probe_markets as probe

pytestmark = pytest.mark.guarded_runner
NOW = "2026-10-27T12:00:00Z"


@pytest.mark.parametrize("payload,status,reason", [
    (None, "unknown", "missing_status_evidence"),
    ({"markets": [{}]}, "unknown", "missing_snapshot_time"),
    ({"status": "fresh", "markets": [{}]}, "unknown", "missing_snapshot_time"),
    ({"as_of": "2026-10-28", "markets": [{}]}, "unknown", "future_snapshot_time"),
    ({"as_of": "2026-10-01", "markets": [{}]}, "stale", "snapshot_age_exceeded"),
    ({"as_of": NOW, "markets": [{}]}, "fresh", "dated_snapshot"),
    ({"as_of": NOW, "markets": [], "status": {"empty_reason": "transport_failure"}}, "offline", "transport_failure"),
    ({"as_of": NOW, "markets": [], "status": {"successful_query_count": 2}}, "empty", "no_rows"),
    ({"as_of": NOW, "markets": [], "status": {"attempted": True}}, "unknown", "missing_status_evidence"),
    ({"as_of": NOW, "markets": [], "status": {"successful_query_count": None}}, "unknown", "missing_status_evidence"),
    ({"as_of": NOW, "markets": [{}], "cached": True}, "stale", "cached_snapshot"),
    ({"markets": [{}], "status": "stale"}, "stale", "cached_snapshot"),
    ({"as_of": NOW, "markets": [{"requote_failed": True}, {}]}, "stale", "cached_snapshot"),
    ({"as_of": NOW, "markets": [{}], "cached": True, "status": "offline"}, "stale", "cached_after_failure"),
    ({"status": "disabled"}, "disabled", "input_disabled"),
])
def test_input_status_does_not_invent_freshness(payload, status, reason):
    result = build_inputs_health(markets=payload, as_of=NOW)["markets"]
    assert result["status"] == status and result["reason"] == reason


def test_input_health_all_categories_preserve_evidence_and_not_configured_presence():
    result = build_inputs_health(
        news={"items": [{"published_at": "2026-10-01"}], "retrieved_at": NOW},
        official_data={"series": [{"retrieved_at": "2026-10-01"}, {"retrieved_at": NOW}]},
        provider={"configured": True, "model": "test"}, as_of=NOW)
    assert result["news"]["as_of"] == NOW  # Snapshot time, not the article date.
    assert result["official_data"]["status"] == "stale"
    assert result["official_data"]["as_of"] == "2026-10-01"
    assert result["provider"]["status"] == "unknown"


def test_provider_receipt_needs_success_date_and_observed_rows():
    result = build_inputs_health(provider={"status": "ok", "as_of": NOW, "rows": 1}, as_of=NOW)
    assert result["provider"]["status"] == "fresh"
    assert build_inputs_health(provider={"status": "offline", "as_of": NOW, "rows": 1}, as_of=NOW)["provider"]["status"] == "offline"


@pytest.mark.parametrize("state,expected", [("timeout", "offline"), ("unavailable", "offline"),
                                            ("verified_empty", "empty"), ("disabled", "disabled"),
                                            ("partial", "unknown")])
def test_native_news_status_consumes_query_proof_and_never_uses_search_cutoff_as_date(state, expected):
    context = {"as_of": "2099-12-31", "providers": {"newsapi": {"state": state}}, "items": [],
               "queries": [{"status": {"state": state, "attempted": True}, "retrieved_at": NOW}]}
    row = build_inputs_health(news=context, as_of=NOW)["news"]
    assert row["status"] == expected and row["as_of"] == NOW


def test_native_news_cutoff_alone_cannot_prove_freshness():
    context = {"as_of": NOW, "providers": {"newsapi": {"state": "ok"}},
               "items": [{"published_at": NOW}], "queries": []}
    assert build_inputs_health(news=context, as_of=NOW)["news"]["status"] == "unknown"


def test_native_official_cache_route_stays_stale_even_if_recent():
    row = build_inputs_health(official_data={"series": [{"series": "fred:TEST",
                              "route": "cache", "retrieved_at": NOW}]}, as_of=NOW)["official_data"]
    assert row["status"] == "stale" and row["as_of"] == NOW


def test_schedule_fake_clock_uses_24_hours_and_cancels_without_threads():
    clock, fired, waits = [0.0], [], []

    def wait(seconds):
        waits.append(seconds)
        clock[0] += seconds
        return len(fired) == 3

    autorun.run_schedule(24, wait=wait, trigger=lambda: fired.append(clock[0]), initial_delay_s=60)
    assert fired == [60, 86460, 172860]
    assert waits == [60, 86400, 86400, 86400]


@pytest.mark.parametrize("interval", [0, -1, float("inf"), float("nan")])
def test_disabled_or_invalid_cadence_does_not_wait_or_trigger(interval):
    def forbidden(*args):
        raise AssertionError("inactive cadence performed work")

    autorun.run_schedule(interval, wait=forbidden, trigger=forbidden)
    assert autorun.start(interval) is None


def test_configured_24h_scheduler_start_with_fake_thread_no_runtime(monkeypatch):
    monkeypatch.setattr(Config, "RESOLUTION_MONITOR_AUTORUN_HOURS", 24)
    targets = []

    class FakeThread:
        def __init__(self, **kwargs):
            targets.append(kwargs)

        def start(self):
            pass

    monkeypatch.setattr(autorun.threading, "Thread", FakeThread)
    assert autorun.start() is not None
    assert len(targets) == 1 and targets[0]["daemon"] is True
    monkeypatch.setattr(Config, "RESOLUTION_MONITOR_AUTORUN_HOURS", 0)
    assert autorun.start() is None


def test_probe_cli_uses_real_configured_gamma_and_clob_transport(monkeypatch, capsys):
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True)
    monkeypatch.setattr(pm, "POLYMARKET_BASE_URL", "https://gamma.fixture")
    monkeypatch.setattr(pm, "CLOB_BASE_URL", "https://clob.fixture")
    # The real class default is bound at definition; use its configured constructor
    # while leaving every client method and normalization path real.
    original = pm.PolymarketClient
    monkeypatch.setattr(pm, "PolymarketClient", lambda **kw: original(base_url="https://gamma.fixture", **kw))
    requests = []

    class Response:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    def get(url, **kwargs):
        requests.append((url, kwargs))
        if url.endswith("public-search"):
            return Response({"events": [{"id": "e1", "title": "Event", "markets": [{
                "id": "m1", "question": "Event happens?", "volume": 1000, "liquidity": 500,
                "closed": False, "outcomes": '["Yes","No"]', "outcomePrices": '["0.4","0.6"]',
                "clobTokenIds": '["token1","token2"]'}]}]})
        assert url == "https://clob.fixture/prices-history"
        assert kwargs["params"]["market"] == "token1"
        return Response({"history": [{"t": 1793102400, "p": 0.4}]})

    monkeypatch.setattr(pm.httpx, "get", get)
    assert probe.main(["event", "--timeout", "3"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["gamma"]["status"] == result["clob"]["status"] == "fresh"
    assert result["inputs_health"]["markets"]["rows"] == 1
    assert [r[0] for r in requests] == ["https://gamma.fixture/public-search", "https://clob.fixture/prices-history"]
    assert all(r[1]["timeout"] == 3 and r[1]["headers"]["User-Agent"] for r in requests)


def test_probe_disabled_and_missing_clob_token_do_not_claim_success(monkeypatch):
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", False)
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: pytest.fail("disabled probe touched transport"))
    result = probe.probe_markets("event")
    assert result["gamma"]["status"] == result["clob"]["status"] == "disabled"
    assert probe._safe_endpoint("https://user:secret@host/path?key=secret") == "https://host/path"
