"""Guarded OS-2 fixtures. These are not evidence of live provider operation."""
from __future__ import annotations

import copy
import os
import importlib.util
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.guarded_runner
ROOT = Path(__file__).resolve().parents[2]


def load_bridge(name):
    assert "main_offline_guard" in sys.modules, "use the unchanged main offline runner"
    bridge_path = str(ROOT / "deerflow_bridge")
    if bridge_path not in sys.path:
        sys.path.insert(0, bridge_path)
    spec = importlib.util.spec_from_file_location("os2_" + name, ROOT / "deerflow_bridge" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def adapter(monkeypatch):
    module = load_bridge("market_intelligence")
    market_tools = load_bridge("market_tools")
    budget = SimpleNamespace(admit_network=lambda _: SimpleNamespace(allowed=True),
                             admit_attempt=lambda _: SimpleNamespace(allowed=True))
    monkeypatch.setattr(module, "_bridge", lambda name: {"market_tools": market_tools, "research_budget": budget}[name])
    monkeypatch.setenv("NEWS_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("MARKET_INTELLIGENCE_ENABLED", "true")
    monkeypatch.setenv("MARKET_INTELLIGENCE_MAX_REQUESTS", "4")
    monkeypatch.setenv("NEWS_CONTEXT_HTTP_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("NEWS_CONTEXT_DEADLINE_SECONDS", "10")
    return module


def kalshi(**changes):
    value = {"ticker": "CPI-26-T3", "event_ticker": "CPI-26", "title": "CPI above 3 in 2026?",
             "market_type": "binary", "yes_bid_dollars": "0.4200", "yes_ask_dollars": "0.4400",
             "no_bid_dollars": "0.5600", "no_ask_dollars": "0.5800", "last_price_dollars": "0.4300",
             "volume_fp": "1.50", "volume_24h_fp": "0.25", "open_interest_fp": "1.25",
             "notional_value_dollars": "1.0000", "status": "active",
             "rules_primary": "CPI strictly above 3 at the specified release.", "rules_secondary": "Use official release.",
             "close_time": "2026-12-31T23:59:59Z", "updated_time": "2026-10-18T11:00:00Z",
             "created_time": "2026-01-01T00:00:00Z", "floor_strike": 3, "strike_type": "greater"}
    value.update(changes)
    return value


def poly(**changes):
    value = {"id": "CPI-26-T3", "question": "CPI above 3 in 2026?", "outcomes": '["No", "Yes"]',
             "outcomePrices": '["0.8", "0.2"]', "volume": "1000", "slug": "cpi-2026",
             "description": "CPI strictly above 3 in 2026.", "endDate": "2026-12-31T23:59:59Z"}
    value.update(changes)
    return value


class Client:
    def __init__(self, **snapshot):
        self.data = {"queries": [], "items": [], "sealed": False, "as_of": None, "language": "en", **snapshot}

    def snapshot(self):
        return copy.deepcopy(self.data)

    def record_result(self, provider, query, result):
        for previous in self.data["queries"]:
            if previous["provider"] == provider and previous["query"].casefold() == query.casefold():
                return copy.deepcopy(previous)
        assert result["provider"] == provider and result["query"] == query
        if self.data["sealed"]:
            return {"provider": provider, "query": query,
                    "status": {"state": "unavailable", "attempted": False, "reason": "generation_sealed"},
                    "items": [], "retrieved_at": "2000-01-01T00:00:00Z"}
        self.data["queries"].append(copy.deepcopy(result))
        self.data["items"].extend(copy.deepcopy(result["items"]))
        return copy.deepcopy(result)

    def capture_market(self, provider, query, acquire, *, deadline=None):
        """Explicit single-process unit adapter; real-store tests prove locking."""
        for previous in self.data["queries"]:
            if previous["provider"] == provider and previous["query"].casefold() == query.casefold():
                return copy.deepcopy(previous)
        def denied(state, reason):
            return {"provider": provider, "query": query, "status": {"state": state, "attempted": False, "reason": reason},
                    "items": [], "retrieved_at": "2000-01-01T00:00:00Z", "network_requests": 0, "request_count": 0}
        if self.data["sealed"]:
            return denied("unavailable", "generation_sealed")
        cap = min(4, max(0, int(os.environ.get("MARKET_INTELLIGENCE_MAX_REQUESTS", "4"))))
        spent = sum(r.get("request_count", r.get("network_requests", 0)) for r in self.data["queries"])
        if spent >= cap:
            return self.record_result(provider, query, denied("budget_exhausted", "market_request_limit"))
        if deadline is not None and deadline <= time.monotonic():
            return self.record_result(provider, query, denied("timeout", "deadline_exhausted"))
        pending = denied("unavailable", "capture_interrupted")
        self.data["queries"].append(pending)
        def reserve():
            total = sum(r.get("request_count", r.get("network_requests", 0)) for r in self.data["queries"])
            if total >= cap:
                return {"allowed": False, "state": "budget_exhausted", "reason": "market_request_limit"}
            pending["request_count"] += 1
            pending["network_requests"] += 1
            pending["status"]["attempted"] = True
            return {"allowed": True, "state": "ok", "reason": ""}
        result = acquire(reserve)
        result["request_count"] = pending["request_count"]
        result["network_requests"] = pending["request_count"]
        self.data["queries"].remove(pending)
        return self.record_result(provider, query, result)


def script_transport(adapter, monkeypatch, scripted):
    instances = []
    class ScriptTransport:
        def __init__(self, deadline, allowance, *, reserve_network):
            self.deadline, self.allowance, self.calls = deadline, allowance, 0
            self.reserve_network = reserve_network
            self.urls = []
            instances.append(self)

        def get(self, url, params=None):
            if self.calls >= self.allowance:
                raise adapter._Failure("budget_exhausted", "market_request_limit")
            if self.deadline <= time.monotonic():
                raise adapter._Failure("timeout", "deadline_exhausted")
            reservation = self.reserve_network()
            if not reservation["allowed"]:
                raise adapter._Failure(reservation["state"], reservation["reason"])
            self.calls += 1
            self.urls.append((url, copy.deepcopy(params)))
            value = scripted.pop(0)
            if isinstance(value, BaseException):
                raise value
            return copy.deepcopy(value)
    monkeypatch.setattr(adapter, "_Transport", ScriptTransport)
    return instances


def test_native_dollars_fixed_point_rules_identity_and_unknown_quote_time(adapter):
    row = adapter.normalize_kalshi_market(kalshi(), "CPI", retrieved_at="capture", language="en")
    assert row["id"] == "kalshi:CPI-26-T3" and row["native_id"] == "CPI-26-T3"
    assert row["probability"] == .43 and row["yes_bid"] == .42 and row["yes_ask"] == .44
    assert row["volume"] == 1.5 and row["volume_unit"] == "contracts"
    assert row["price_unit"] == "USD_per_contract" and row["rules_primary"].startswith("CPI strictly")
    assert row["quote_at"] is None and row["metadata_updated_at"] is not None
    assert row["retrieved_at"] == "capture" and row["floor_strike"] == 3
    assert row["eligibility"] == {"context_only": True, "anchor": False, "resolution": False}


@pytest.mark.parametrize("value,expected", [("0.4321", .4321), (.5, .5), (1, 1), (0, 0),
                                              (None, None), ("NaN", None), (float("inf"), None),
                                              (-.1, None), (50, None), ("bad", None), (True, None)])
def test_prices_accept_current_units_and_reject_invalid_without_cent_fallback(adapter, value, expected):
    row = adapter.normalize_kalshi_market(kalshi(last_price_dollars=value, last_price=43), "CPI")
    assert row["last_price"] == expected and row["probability"] == expected
    json.dumps(row, allow_nan=False)


def test_nonbinary_and_missing_native_fields_do_not_become_binary_probability(adapter):
    assert adapter.normalize_kalshi_market(kalshi(ticker=None), "x") is None
    row = adapter.normalize_kalshi_market(kalshi(market_type="scalar", volume_fp=None, volume=1000,
                                               rules_primary=None, floor_strike=-4), "x")
    assert row["probability"] is None and row["outcome"] is None
    assert row["volume"] is None and row["rules_primary"] is None and row["floor_strike"] == -4


def test_compare_reuses_polymarket_and_persists_context_only_distinct_native_ids(adapter, monkeypatch, tmp_path):
    monkeypatch.setenv("DEERFLOW_RUN_ARTIFACT_DIR", str(tmp_path))
    instances = script_transport(adapter, monkeypatch, [
        {"events": [{"title": "Inflation", "slug": "inflation", "markets": [poly()]}]},
        {"markets": [kalshi()], "cursor": ""}, {"market": kalshi(rules_secondary="Detail rules")},
    ])
    client = Client()
    output = adapter.compare_markets(client, "CPI 2026")
    assert {item["id"] for item in output["items"]} == {"polymarket:CPI-26-T3", "kalshi:CPI-26-T3"}
    assert [i["probability"] for i in output["items"]] == [.2, .43]
    assert output["items"][0]["rules_primary"] == "CPI strictly above 3 in 2026."
    assert output["items"][1]["detail_obtained"] is True
    assert output["comparison_basis"] == "topic_candidates_only" and output["equivalence_established"] is False
    assert "markets" not in output and not list(tmp_path.iterdir())
    assert all(i["eligibility"]["anchor"] is False for i in output["items"])
    assert sum(t.calls for t in instances) == 3 and len(client.data["queries"]) == 3
    unsupported = output["providers"][2]
    assert unsupported["provider"] == "metaculus" and unsupported["status"]["state"] == "unsupported"
    assert unsupported["kind"] == "community_forecast" and not unsupported["items"]
    replay = adapter.compare_markets(client, "  cpi  2026  ")
    assert replay["items"] == output["items"] and sum(t.calls for t in instances) == 3
    assert replay["retrieved_at"] == output["retrieved_at"]
    client.data["sealed"] = True
    sealed = adapter.compare_markets(client, "CPI 2026")
    assert sealed["items"] == output["items"] and sum(t.calls for t in instances) == 3
    absent = adapter.compare_markets(client, "different query")
    assert not absent["items"] and sum(t.calls for t in instances) == 3
    assert absent["providers"][0]["status"]["reason"] == "generation_sealed"


def test_identical_titles_different_thresholds_and_years_are_not_equivalent(adapter, monkeypatch):
    script_transport(adapter, monkeypatch, [
        {"events": [{"markets": [poly()]}]},
        {"markets": [kalshi(ticker="CPI-27-T4", floor_strike=4, close_time="2027-12-31T00:00:00Z")], "cursor": ""},
        {"market": kalshi(ticker="CPI-27-T4", floor_strike=4, close_time="2027-12-31T00:00:00Z")},
    ])
    result = adapter.compare_markets(Client(), "CPI")
    assert len(result["items"]) == 2 and not result["equivalence_established"]
    assert result["items"][1]["floor_strike"] == 4
    assert result["items"][0]["end_date"] != result["items"][1]["end_date"]
    assert "price_difference" not in result and "arbitrage" not in result


def test_two_cursor_pages_are_bounded_and_nonexhaustive_scan_is_partial(adapter, monkeypatch):
    instances = script_transport(adapter, monkeypatch, [
        {"events": []}, {"markets": [], "cursor": "page2"},
        {"markets": [kalshi()], "cursor": "page3"}, {"market": kalshi()},
    ])
    result = adapter.compare_markets(Client(), "CPI")
    assert sum(t.calls for t in instances) == 4
    urls = [item for t in instances for item in t.urls]
    assert urls[2][1]["cursor"] == "page2"
    kalshi_result = result["providers"][1]
    assert kalshi_result["status"]["state"] == "partial" and not kalshi_result["recall_complete"]
    assert kalshi_result["pages"] == 2 and len(kalshi_result["items"]) == 1


def test_truncated_empty_is_not_verified_empty_and_counts_survive_reconstruction(adapter, monkeypatch):
    instances = script_transport(adapter, monkeypatch, [
        {"events": []}, {"markets": [], "cursor": "page2"}, {"markets": [], "cursor": "page3"},
        {"events": []},
    ])
    client = Client()
    result = adapter.compare_markets(client, "CPI")
    assert result["providers"][1]["status"]["state"] == "partial"
    restored = Client(**client.snapshot())
    second = adapter.compare_markets(restored, "different query")
    assert sum(t.calls for t in instances[2:]) == 1
    assert second["providers"][1]["status"]["state"] == "budget_exhausted"
    assert second["providers"][1]["status"]["attempted"] is False


def test_exhausted_empty_catalog_and_pm_empty_remain_verified_empty(adapter, monkeypatch):
    script_transport(adapter, monkeypatch, [{"events": []}, {"markets": [], "cursor": ""}])
    result = adapter.compare_markets(Client(), "CPI")
    assert [p["status"]["state"] for p in result["providers"]] == ["verified_empty", "verified_empty", "unsupported"]


@pytest.mark.parametrize("state,reason", [("forbidden", "http_403"), ("rate_limited", "http_429"),
                                          ("timeout", "deadline_exhausted"), ("unavailable", "invalid_json")])
def test_failures_are_distinct_without_retry_or_absence_claim(adapter, monkeypatch, state, reason):
    instances = script_transport(adapter, monkeypatch, [{"events": []}, adapter._Failure(state, reason)])
    result = adapter.compare_markets(Client(), "CPI")
    assert result["providers"][1]["status"]["state"] == state
    assert result["providers"][1]["status"]["reason"] == reason and sum(t.calls for t in instances) == 2


def test_singular_detail_mismatch_is_partial_and_preserves_list_candidate(adapter, monkeypatch):
    script_transport(adapter, monkeypatch, [{"events": []}, {"markets": [kalshi()], "cursor": ""},
                                          {"market": kalshi(ticker="OTHER")}])
    result = adapter.compare_markets(Client(), "CPI")["providers"][1]
    assert result["status"]["state"] == "partial" and result["status"]["reason"] == "invalid_detail_schema"
    assert result["items"][0]["native_id"] == "CPI-26-T3" and not result["items"][0]["detail_obtained"]


@pytest.mark.parametrize("mode", ["master_off", "market_off", "deadline", "budget", "historical"])
def test_disabled_historical_deadline_and_budget_have_zero_network(adapter, monkeypatch, mode):
    client = Client(as_of="2020-01-01T00:00:00Z" if mode == "historical" else None)
    if mode == "master_off": monkeypatch.setenv("NEWS_CONTEXT_ENABLED", "false")
    if mode == "market_off": monkeypatch.setenv("MARKET_INTELLIGENCE_ENABLED", "false")
    if mode == "budget": monkeypatch.setenv("MARKET_INTELLIGENCE_MAX_REQUESTS", "0")
    instances = script_transport(adapter, monkeypatch, [])
    result = adapter.compare_markets(client, "CPI", deadline=time.monotonic() - 1 if mode == "deadline" else None)
    assert sum(t.calls for t in instances) == 0
    assert not result["items"]
    if mode.endswith("off"):
        assert result["status"]["state"] == "disabled" and not client.data["queries"]
    else:
        state = {"deadline": "timeout", "budget": "budget_exhausted", "historical": "unsupported"}[mode]
        assert result["providers"][0]["status"]["state"] == state


def test_unknown_pm_fields_and_nonbinary_are_not_fabricated(adapter, monkeypatch):
    script_transport(adapter, monkeypatch, [{"events": [{"markets": [poly(outcomes='["Yes","No","Other"]',
        outcomePrices='["0.2","0.3","0.5"]', volume="Infinity", description=None)]}]}, {"markets": [], "cursor": ""}])
    row = adapter.compare_markets(Client(), "CPI")["items"][0]
    assert row["probability"] is None and row["volume"] is None and row["rules_primary"] is None
    assert row["probability_basis"] is None and row["outcome"] is None
    assert "clob_yes_token_id" not in row


def test_actual_transport_bounds_bytes_no_redirects_and_sanitizes_errors(adapter, monkeypatch):
    calls = []
    response = SimpleNamespace(status=200, read1=lambda size: b"x" * size)
    class Connection:
        sock = None
        def __init__(self, host, timeout): calls.append((host, timeout))
        def request(self, *args, **kwargs): pass
        def getresponse(self): return response
        def close(self): pass
    monkeypatch.setattr(adapter.http.client, "HTTPSConnection", Connection)
    transport = adapter._Transport(time.monotonic() + 10, 4, reserve_network=lambda: {"allowed": True})
    with pytest.raises(adapter._Failure) as exc:
        transport.get(adapter.KALSHI_BASE_URL + "/markets")
    assert exc.value.reason == "response_too_large" and calls[0][1] <= 5
    response.status = 302
    with pytest.raises(adapter._Failure) as exc:
        transport.get(adapter.KALSHI_BASE_URL + "/markets")
    assert exc.value.reason == "http_302" and transport.calls == 2
    with pytest.raises(adapter._Failure, match="endpoint_not_allowed"):
        transport.get("https://elsewhere.invalid/markets")
    assert transport.calls == 2


def test_transport_exception_does_not_expose_raw_exception(adapter, monkeypatch):
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): raise OSError("private failure body must not escape")
        def close(self): pass
    monkeypatch.setattr(adapter.http.client, "HTTPSConnection", Connection)
    with pytest.raises(adapter._Failure) as exc:
        adapter._Transport(time.monotonic() + 10, 1, reserve_network=lambda: {"allowed": True}).get(adapter.KALSHI_BASE_URL + "/markets")
    assert str(exc.value) == "transport_failure" and exc.value.state == "unavailable"


def test_research_attempt_budget_denial_skips_physical_requests(adapter, monkeypatch, tmp_path):
    signals = load_bridge("news_signals")
    monkeypatch.setattr(signals, "_budget", lambda kind: (False, "fixture_attempt_budget"))
    instances = script_transport(adapter, monkeypatch, [])
    result = adapter.compare_markets(signals.ContextClient(tmp_path, question="CPI"), "CPI")
    assert sum(t.calls for t in instances) == 0
    assert result["providers"][0]["status"]["reason"] == "fixture_attempt_budget"


def test_normal_v3_today_as_of_permits_present_capture_and_quote_aliases(adapter, monkeypatch):
    from datetime import datetime, timezone
    script_transport(adapter, monkeypatch, [{"events": [{"markets": [poly()]}]},
                                          {"markets": [kalshi()], "cursor": ""}, {"market": kalshi()}])
    result = adapter.compare_markets(Client(as_of=datetime.now(timezone.utc).date().isoformat()), "CPI")
    assert len(result["items"]) == 2
    row = result["items"][1]
    assert (row["bid"], row["ask"], row["last"], row["quote_units"]) == (.42, .44, .43, "USD_per_contract")
    assert row["source_price_fields"]["last_price_dollars"] == "0.4300"
    assert result["items"][0]["source_price_fields"]["outcomes"] == ["No", "Yes"]


@pytest.mark.parametrize("as_of", ["2020-01-01", "2020-01-01T23:59:59Z", "invalid", 123])
def test_historical_or_uninterpretable_cutoff_is_explicit_without_acquisition(adapter, monkeypatch, as_of):
    instances = script_transport(adapter, monkeypatch, [])
    result = adapter.compare_markets(Client(as_of=as_of), "CPI")
    assert not result["items"] and sum(t.calls for t in instances) == 0
    assert result["providers"][0]["status"]["reason"] == "historical_quote_availability_not_established"


def test_real_context_client_tool_to_snapshot_seal_restart_and_no_canonical_rows(adapter, monkeypatch, tmp_path):
    signals = load_bridge("news_signals")
    from datetime import datetime, timezone
    instances = script_transport(adapter, monkeypatch, [
        {"events": [{"markets": [poly()]}]}, {"markets": [kalshi()], "cursor": ""}, {"market": kalshi()},
    ])
    client = signals.ContextClient(tmp_path, question="CPI above 3?", language="en",
                                   as_of=datetime.now(timezone.utc).date().isoformat())
    monkeypatch.setitem(sys.modules, "market_intelligence", adapter)
    result = client.market_compare("CPI")
    assert len(result["items"]) == 2
    snapshot = client.seal(source_refs={result["items"][1]["url"]: "S2"})
    assert snapshot["sealed"] is True
    assert set(snapshot["providers"]) == {"polymarket", "kalshi", "metaculus"}
    assert all(i["eligibility"]["context_only"] for i in snapshot["items"])
    assert "markets" not in snapshot
    assert not (tmp_path / "prediction_markets.json").exists()
    assert not (tmp_path / "prediction_market_candidates.jsonl").exists()
    kalshi_item = next(i for i in snapshot["items"] if i["provider"] == "kalshi")
    assert kalshi_item["volume_units"] == "contracts" and kalshi_item["units"] == "USD_per_contract"
    assert kalshi_item["rules"].startswith("CPI strictly")
    assert kalshi_item["rules_primary"] == kalshi()["rules_primary"]
    assert kalshi_item["rules_secondary"] == kalshi()["rules_secondary"]
    assert kalshi_item["price_unit"] == "USD_per_contract" and kalshi_item["quote_units"] == "USD_per_contract"
    assert kalshi_item["probability_basis"] == "last_price_dollars/1_USD_binary_payout"
    assert kalshi_item["quote_at"] is None
    assert kalshi_item["source_price_fields"]["last_price_dollars"] == "0.4300"
    assert kalshi_item["floor_strike"] == 3 and kalshi_item["metadata_updated_at"] is not None
    assert kalshi_item["source_ref"] == "S2"
    assert sum(q.get("request_count", q.get("network_requests", 0)) for q in snapshot["queries"]) == 3
    restarted = signals.ContextClient(tmp_path)
    replay = adapter.compare_markets(restarted, "CPI")
    assert len(replay["items"]) == 2 and sum(t.calls for t in instances) == 3
    assert signals.load_context(tmp_path) == snapshot
    absent = adapter.compare_markets(restarted, "another topic")
    assert not absent["items"] and sum(t.calls for t in instances) == 3


def test_real_fresh_context_identity_and_absent_artifact_dir_block_before_network(adapter, monkeypatch, tmp_path):
    signals = load_bridge("news_signals")
    instances = script_transport(adapter, monkeypatch, [])
    old = signals.ContextClient(tmp_path, question="CPI", as_of="2020-01-01")
    result = adapter.compare_markets(old, "CPI")
    assert result["providers"][0]["status"]["state"] == "unsupported"
    assert sum(t.calls for t in instances) == 0
    monkeypatch.delenv("DEERFLOW_RUN_ARTIFACT_DIR", raising=False)
    missing = adapter.compare_markets(signals.ContextClient(None), "CPI")
    assert missing["status"]["reason"] == "artifact_dir_required" and sum(t.calls for t in instances) == 0


def test_real_unsealed_restart_retains_market_request_budget(adapter, monkeypatch, tmp_path):
    signals = load_bridge("news_signals")
    instances = script_transport(adapter, monkeypatch, [
        {"events": []}, {"markets": [], "cursor": "second"},
        {"markets": [], "cursor": "third"}, {"events": []},
    ])
    first = signals.ContextClient(tmp_path, question="CPI")
    adapter.compare_markets(first, "CPI")
    restarted = signals.ContextClient(tmp_path)
    output = adapter.compare_markets(restarted, "another topic")
    assert sum(t.calls for t in instances[2:]) == 1
    assert output["providers"][1]["status"]["state"] == "budget_exhausted"
    assert sum(r.get("request_count", r.get("network_requests", 0)) for r in restarted.snapshot()["queries"]) == 4


def test_detail_access_failure_stops_additional_details_and_keeps_provenance(adapter, monkeypatch):
    instances = script_transport(adapter, monkeypatch, [
        {"events": []}, {"markets": [kalshi(), kalshi(ticker="CPI-27-T4", floor_strike=4)], "cursor": ""},
        adapter._Failure("forbidden", "http_403"),
    ])
    result = adapter.compare_markets(Client(), "CPI")["providers"][1]
    assert sum(t.calls for t in instances) == 3
    assert len(result["items"]) == 2 and result["status"]["state"] == "partial"
    assert result["status"]["reason"] == "http_403" and all(not row["detail_obtained"] for row in result["items"])


def test_bad_list_or_cursor_is_unknown_not_empty(adapter, monkeypatch):
    script_transport(adapter, monkeypatch, [{"events": []}, {"markets": [], "cursor": None}])
    result = adapter.compare_markets(Client(), "CPI")["providers"][1]
    assert result["status"]["state"] == "partial" and result["status"]["reason"] == "invalid_cursor"
    assert result["items"] == []


def test_original_polymarket_wrapper_is_never_used(adapter, monkeypatch):
    markets = adapter._bridge("market_tools")
    monkeypatch.setattr(markets, "prediction_market_search_impl", lambda *a, **k: pytest.fail("canonical wrapper called"))
    monkeypatch.setattr(markets, "_capture_market_candidates", lambda *a, **k: pytest.fail("canonical capture called"))
    script_transport(adapter, monkeypatch, [{"events": [{"markets": [poly()]}]}, {"markets": [], "cursor": ""}])
    assert len(adapter.compare_markets(Client(), "CPI")["items"]) == 1


def _guarded_market_child(tmp_path, root, calls, gate, slot, query, *, crash=False):
    import subprocess
    guard = sys.modules.get("main_offline_guard")
    assert guard is not None
    script = Path(__file__).resolve()
    guard.allow_python_script(script)
    return subprocess.Popen(
        [sys.executable, "-B", str(script), "--market-process-child", str(root), str(calls),
         str(gate), str(slot), query, "crash" if crash else "normal"],
        cwd=str(tmp_path), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def _await_fixture_path(path, seconds=8):
    expires = time.monotonic() + seconds
    while not path.exists():
        if time.monotonic() >= expires:
            pytest.fail("bounded market child fixture gate timed out")
        time.sleep(.01)


def _physical_calls(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.mark.parametrize("same_query", [True, False])
def test_two_processes_reserve_before_http_and_share_generation_allowance(tmp_path, same_query):
    root, calls, gate = tmp_path / "generation", tmp_path / "physical.jsonl", tmp_path / "gate"
    children = []
    try:
        for slot in range(2):
            query = "CPI shared" if same_query else "CPI process " + str(slot)
            children.append(_guarded_market_child(tmp_path, root, calls, gate, slot, query))
        for slot in range(2):
            _await_fixture_path(tmp_path / ("ready-" + str(slot)))
        gate.touch()
        outputs = []
        for child in children:
            stdout, stderr = child.communicate(timeout=20)
            assert child.returncode == 0, stderr
            outputs.append(json.loads(stdout))
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
    physical = _physical_calls(calls)
    assert len(physical) == (3 if same_query else 4)
    import sqlite3
    with sqlite3.connect(tmp_path / "research-budget.sqlite") as conn:
        global_calls = conn.execute("SELECT value FROM counters WHERE scope='global' AND lane='' AND name='search_network'").fetchone()[0]
    assert global_calls == len(physical)
    signals = load_bridge("news_signals")
    snapshot = signals.load_context(root, require_sealed=False)
    assert sum(r.get("request_count", r.get("network_requests", 0)) for r in snapshot["queries"]) == len(physical)
    assert snapshot["network_requests"]["market"] == len(physical)
    assert len({r["request_id"] for r in snapshot["queries"]}) == len(snapshot["queries"])
    if same_query:
        assert outputs[0]["providers"] == outputs[1]["providers"]
    assert not (root / "prediction_markets.json").exists()


def test_interrupted_process_preserves_spent_allowance_and_never_refetches_capture(tmp_path, monkeypatch, adapter):
    root, calls, gate = tmp_path / "generation", tmp_path / "physical.jsonl", tmp_path / "gate"
    child = _guarded_market_child(tmp_path, root, calls, gate, 0, "CPI interrupted", crash=True)
    try:
        _await_fixture_path(tmp_path / "ready-0")
        gate.touch()
        _await_fixture_path(calls)
        child.terminate()
        child.wait(timeout=5)
        assert child.returncode != 0  # This admitted fixture is intentionally interrupted.
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
    signals = load_bridge("news_signals")
    snapshot = signals.load_context(root, require_sealed=False)
    pending = next(r for r in snapshot["queries"] if r["provider"] == "polymarket")
    assert pending["status"]["reason"] == "capture_interrupted" and pending["request_count"] == 1
    assert len(_physical_calls(calls)) == 1
    # The interrupted provider capture replays. Previously unrequested Kalshi
    # context may acquire its own capture within the remaining allowance.
    instances = script_transport(adapter, monkeypatch, [
        {"markets": [], "cursor": "second"}, {"markets": [], "cursor": "third"}, {"events": []},
    ])
    restored = signals.ContextClient(root)
    replay = adapter.compare_markets(restored, "CPI interrupted")
    assert replay["providers"][0]["status"]["reason"] == "capture_interrupted"
    assert instances[0].calls == 2
    other = adapter.compare_markets(restored, "CPI new topic")
    assert instances[1].calls == 1
    assert other["providers"][1]["status"]["state"] == "budget_exhausted"
    assert sum(r.get("request_count", r.get("network_requests", 0)) for r in restored.snapshot()["queries"]) == 4


def test_full_query_table_blocks_acquisition_before_physical_http(adapter, monkeypatch, tmp_path):
    signals = load_bridge("news_signals")
    client = signals.ContextClient(tmp_path, question="CPI")
    for number in range(signals.MAX_QUERIES):
        query = "table fixture " + str(number)
        client.record_result("metaculus", query, adapter._result("metaculus", query, "unsupported", reason="fixture"))
    before = client.snapshot()
    instances = script_transport(adapter, monkeypatch, [{"events": []}, {"markets": [], "cursor": ""}])
    result = adapter.compare_markets(client, "CPI not yet captured")
    assert sum(t.calls for t in instances) == 0
    assert all(p["status"]["state"] == "budget_exhausted" for p in result["providers"])
    assert client.snapshot() == before


def _market_process_fixture(root, calls, gate, slot, query, mode):
    """Actual separate process/client with fake HTTPS, under the parent guard."""
    import os
    sys.path.insert(0, str(ROOT))
    from deerflow_bridge import news_signals as signals
    module = load_bridge("market_intelligence")
    markets = load_bridge("market_tools")
    module._bridge = lambda name: {"market_tools": markets}[name]
    # Keep the real research budget deliberately generous. Independent physical
    # call logs and its SQLite search counter must both honor the market cap.
    os.environ["RESEARCH_BUDGET_DB"] = str(Path(gate).parent / "research-budget.sqlite")
    os.environ["RESEARCH_BUDGET_SEARCH_GLOBAL"] = "100"
    os.environ["RESEARCH_BUDGET_SEARCH_LANE"] = "100"
    os.environ["RESEARCH_BUDGET_ATTEMPTS_GLOBAL"] = "1000"
    os.environ["NEWS_CONTEXT_ENABLED"] = "true"
    os.environ["MARKET_INTELLIGENCE_ENABLED"] = "true"
    os.environ["MARKET_INTELLIGENCE_MAX_REQUESTS"] = "4"
    os.environ["NEWS_CONTEXT_DEADLINE_SECONDS"] = "10"
    os.environ["NEWS_CONTEXT_HTTP_TIMEOUT_SECONDS"] = "5"
    class Connection:
        sock = None
        def __init__(self, host, timeout):
            self.host = host
        def request(self, method, path, **kwargs):
            with Path(calls).open("a") as stream:
                stream.write(json.dumps({"pid": os.getpid(), "provider": "polymarket" if "polymarket" in self.host else "kalshi"}) + "\n")
            time.sleep(5 if mode == "crash" else .06)
            self.body = json.dumps({"events": []} if "polymarket" in self.host else {
                "markets": [], "cursor": "third" if "cursor=" in path else "second"}).encode()
        def getresponse(self):
            self.status = 200
            return self
        def read1(self, size):
            data, self.body = self.body[:size], self.body[size:]
            return data
        def close(self):
            pass
    module.http.client.HTTPSConnection = Connection
    client = signals.ContextClient(root, question="CPI process reservation fixture", language="en")
    (Path(gate).parent / ("ready-" + slot)).touch()
    expires = time.monotonic() + 8
    while not Path(gate).exists():
        if time.monotonic() >= expires:
            raise RuntimeError("market fixture start gate timed out")
        time.sleep(.01)
    print(json.dumps(module.compare_markets(client, query)))


if __name__ == "__main__" and sys.argv[1:2] == ["--market-process-child"]:
    _market_process_fixture(*sys.argv[2:])


def test_atomic_api_missing_fails_closed_without_transport(adapter, monkeypatch):
    client = SimpleNamespace(snapshot=lambda: {"as_of": None, "language": "en"})
    instances = script_transport(adapter, monkeypatch, [])
    output = adapter.compare_markets(client, "CPI")
    assert output["status"]["reason"] == "atomic_market_capture_unavailable"
    assert sum(t.calls for t in instances) == 0


def test_transport_reservation_denial_prevents_http_and_preserves_canonical_state(adapter, monkeypatch):
    monkeypatch.setattr(adapter.http.client, "HTTPSConnection", lambda *a, **k: pytest.fail("HTTP before durable admission"))
    transport = adapter._Transport(time.monotonic() + 10, 4, reserve_network=lambda: {
        "allowed": False, "state": "budget_exhausted", "reason": "market_request_limit"})
    with pytest.raises(adapter._Failure) as exc:
        transport.get(adapter.KALSHI_BASE_URL + "/markets")
    assert exc.value.state == "budget_exhausted" and exc.value.reason == "market_request_limit" and transport.calls == 0


def test_real_store_calls_existing_research_network_budget_once_per_physical_request(adapter, monkeypatch, tmp_path):
    signals = load_bridge("news_signals")
    admissions = []
    monkeypatch.setattr(signals, "_budget", lambda kind: (admissions.append(kind) or True, ""))
    instances = script_transport(adapter, monkeypatch, [{"events": []}, {"markets": [kalshi()], "cursor": ""}, {"market": kalshi()}])
    output = adapter.compare_markets(signals.ContextClient(tmp_path, question="CPI"), "CPI")
    assert len(output["items"]) == 1 and sum(t.calls for t in instances) == 3
    assert admissions.count("network") == 3 and admissions.count("attempt") == 2


def test_legacy_network_count_is_not_reset_during_atomic_api_migration(adapter, monkeypatch, tmp_path):
    signals = load_bridge("news_signals")
    client = signals.ContextClient(tmp_path, question="CPI")
    client.record_result("polymarket", "earlier query", adapter._result(
        "polymarket", "earlier query", "verified_empty", attempted=True, network_requests=3))
    instances = script_transport(adapter, monkeypatch, [{"events": []}])
    output = adapter.compare_markets(signals.ContextClient(tmp_path), "new query")
    assert sum(t.calls for t in instances) == 1
    assert output["providers"][1]["status"]["state"] == "budget_exhausted"
    assert client.snapshot()["network_requests"]["market"] == 4


def test_http_body_socket_keeps_remaining_deadline_after_connection_releases_socket(adapter, monkeypatch):
    timeouts = []
    body_socket = SimpleNamespace(settimeout=lambda timeout: timeouts.append(timeout))
    response = SimpleNamespace(status=200, fp=SimpleNamespace(raw=SimpleNamespace(_sock=body_socket)))
    chunks = [b'{"markets": [], "cursor": ""}', b""]
    response.read1 = lambda size: chunks.pop(0)
    class Connection:
        sock = None
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): pass
        def getresponse(self): return response
        def close(self): pass
    monkeypatch.setattr(adapter.http.client, "HTTPSConnection", Connection)
    transport = adapter._Transport(time.monotonic() + .5, 1, reserve_network=lambda: {"allowed": True})
    assert transport.get(adapter.KALSHI_BASE_URL + "/markets")["markets"] == []
    assert len(timeouts) == 2 and all(0 < timeout <= .5 for timeout in timeouts)


def test_native_transport_uses_store_residual_deadline(adapter, monkeypatch):
    timeouts = []
    chunks = [b'{"markets": []}', b""]
    response = SimpleNamespace(status=200, read1=lambda size: chunks.pop(0))
    class Connection:
        sock = None
        def __init__(self, host, timeout): timeouts.append(timeout)
        def request(self, *args, **kwargs): pass
        def getresponse(self): return response
        def close(self): pass
    monkeypatch.setattr(adapter.http.client, "HTTPSConnection", Connection)
    reservation = {"allowed": True, "deadline": time.monotonic() + .25}
    transport = adapter._Transport(time.monotonic() + 10, 4, reserve_network=lambda: reservation)
    assert transport.get(adapter.KALSHI_BASE_URL + "/markets")["markets"] == []
    assert len(timeouts) == 1 and 0 < timeouts[0] <= .25


def test_real_store_network_budget_denial_leaves_zero_market_reservations(adapter, monkeypatch, tmp_path):
    signals = load_bridge("news_signals")
    monkeypatch.setattr(signals, "_budget", lambda kind: (kind == "attempt", "" if kind == "attempt" else "fixture_network_budget"))
    instances = script_transport(adapter, monkeypatch, [])
    client = signals.ContextClient(tmp_path, question="CPI")
    output = adapter.compare_markets(client, "CPI")
    assert sum(t.calls for t in instances) == 0
    for result in output["providers"][:2]:
        assert result["status"]["state"] == "budget_exhausted"
        assert result["status"]["reason"] == "fixture_network_budget"
        assert result["status"]["attempted"] is False and result["request_count"] == 0
    assert client.snapshot()["network_requests"]["market"] == 0
