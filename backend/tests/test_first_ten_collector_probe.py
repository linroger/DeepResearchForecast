"""Probe the collector's unmodified urllib transport with a scripted leaf."""
import io
import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

from deerflow_bridge import deerflow_research as collector
from scripts import probe_markets as probe

pytestmark = pytest.mark.guarded_runner


@pytest.fixture
def transport(monkeypatch):
    from app.config import Config
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True)
    monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "true")
    monkeypatch.setenv("PREDICTION_MARKETS_HTTP_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("PREDICTION_MARKETS_HTTP_ATTEMPTS", "2")
    monkeypatch.setenv("PREDICTION_MARKETS_PER_QUERY", "6")
    monkeypatch.setattr(collector, "_POLYMARKET_BASE_URL", "https://gamma.fixture")
    monkeypatch.setattr(collector, "_CLOB_BASE_URL", "https://clob.fixture")
    monkeypatch.setattr(collector, "_polymarket_backoff", lambda attempt: None)
    calls = []
    data = {"gamma": {"events": [{"title": "Event", "slug": "event", "markets": [{
        "id": "m1", "question": "Event happens?", "volume": 1000, "closed": False,
        "outcomes": '["No", "Yes"]', "outcomePrices": '["0.6", "0.4"]',
        "clobTokenIds": '["no-token", "yes-token"]'}]}]},
        "clob": {"history": [{"t": 1793163600, "p": 0.4}]}}

    def urlopen(request, **kwargs):
        calls.append((request, kwargs))
        name = "gamma" if request.full_url.startswith("https://gamma.fixture") else "clob"
        value = data[name]
        if isinstance(value, Exception):
            raise value
        return io.BytesIO(json.dumps(value).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    # A fallback through the old backend HTTP stack is a regression.
    import httpx
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: pytest.fail("probe bypassed collector urllib"))
    return calls, data


def test_cli_uses_exact_collector_transport_and_yes_leg(transport, capsys):
    calls, _ = transport
    assert probe.main(["event", "--timeout", "3", "--limit", "1"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schemaVersion"] == "market-probe/v1"
    assert result["gamma"]["status"] == result["clob"]["status"] == "fresh"
    assert result["gamma"]["rows"][0]["clob_yes_token_id"] == "yes-token"
    assert len(calls) == 2
    gamma, clob = [urllib.parse.urlsplit(request.full_url) for request, _ in calls]
    assert (gamma.netloc, gamma.path) == ("gamma.fixture", "/public-search")
    assert urllib.parse.parse_qs(gamma.query) == {"q": ["event"], "limit_per_type": ["6"], "events_status": ["active"]}
    assert (clob.netloc, clob.path) == ("clob.fixture", "/prices-history")
    assert urllib.parse.parse_qs(clob.query) == {"market": ["yes-token"], "interval": ["1d"]}
    for request, kwargs in calls:
        assert request.get_header("User-agent") == collector._POLYMARKET_UA
        assert request.get_header("Accept") == "application/json"
        assert kwargs == {"timeout": 3.0}  # No alternate opener, proxy or TLS context.
    assert result["inputs_health"]["markets"]["as_of"] is not None


def test_default_probe_uses_collector_timeout_settings(transport):
    calls, _ = transport
    probe.probe_markets("event")
    assert [kwargs["timeout"] for _, kwargs in calls] == [2.5, 15.0]


@pytest.mark.parametrize("state", ["empty", "offline", "disabled"])
def test_no_price_probe_keeps_snapshot_time_absent(transport, monkeypatch, state):
    calls, data = transport
    if state == "disabled":
        monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "false")
    elif state == "offline":
        data["gamma"] = urllib.error.URLError("scripted unavailable")
    else:
        data["gamma"] = {"events": []}
    result = probe.probe_markets("event")
    row = result["inputs_health"]["markets"]
    assert result["gamma"]["status"] == row["status"] == state
    assert row["as_of"] is None and row["attempted_at"] == result["as_of"]
    assert len(calls) == (0 if state == "disabled" else 2 if state == "offline" else 1)
    if state == "offline":
        assert result["gamma"]["errors"] == {"URLError": 1}


def test_clob_failure_is_not_reported_as_empty_and_retains_gamma_success(transport):
    calls, data = transport
    data["clob"] = urllib.error.HTTPError("https://clob.fixture", 403, "forbidden", {}, None)
    result = probe.probe_markets("event")
    assert result["gamma"]["status"] == "fresh"
    assert result["clob"]["status"] == "offline"
    assert len(calls) == 2  # Collector never retries a non-transient 403.


def test_missing_token_stays_unknown_and_explicit_token_uses_same_transport(transport):
    calls, data = transport
    data["gamma"]["events"][0]["markets"][0].pop("clobTokenIds")
    result = probe.probe_markets("event")
    assert result["clob"]["status"] == "unknown" and result["clob"]["reason"] == "missing_token_id"
    assert len(calls) == 1
    calls.clear()
    result = probe.probe_markets("event", token_id="explicit")
    assert result["clob"]["status"] == "fresh"
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(calls[-1][0].full_url).query)["market"] == ["explicit"]


def test_cli_help_is_inert_and_invalid_arguments_fail_before_transport(transport):
    calls, _ = transport
    for args, code in [(["--help"], 0), (["event", "--timeout", "0"], 2),
                       (["event", "--limit", "0"], 2), ([" "], 2)]:
        with pytest.raises(SystemExit) as error:
            probe.main(args)
        assert error.value.code == code
    assert not calls
