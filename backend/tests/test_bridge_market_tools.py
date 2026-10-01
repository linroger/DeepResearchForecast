"""Offline regression tests for the DeerFlow prediction-market tool delivery lane."""

from __future__ import annotations

import importlib.util
import json
import threading
import time
from pathlib import Path

import pytest


BRIDGE_FILE = Path(__file__).resolve().parents[2] / "deerflow_bridge" / "market_tools.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("loop009_market_tools", BRIDGE_FILE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_identical_normalized_queries_use_one_snapshot_and_one_ledger_record(
    tmp_path, monkeypatch,
):
    module = _load_module()
    calls: list[list[str]] = []

    def fake_snapshot(queries, **_kwargs):
        calls.append(list(queries))
        return [{
            "market_id": "691340",
            "question": "AI bubble burst in 2026?",
            "implied_yes_prob": 0.1545,
            "volume": 2_310_000.0,
            "url": "https://polymarket.com/event/ai-bubble-burst-in-2026",
        }]

    monkeypatch.setattr(module, "snapshot_for_queries", fake_snapshot)
    monkeypatch.setenv("DEERFLOW_RUN_ARTIFACT_DIR", str(tmp_path))
    module._reset_market_query_cache()

    first = json.loads(module.prediction_market_search_impl(
        " AI bubble 2026,ai BUBBLE 2026, US recession 2026"))
    second = json.loads(module.prediction_market_search_impl(
        "US recession 2026, AI bubble 2026"))

    assert calls == [["AI bubble 2026", "US recession 2026"]]
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    ledger = (tmp_path / module.MARKET_CANDIDATES_FILENAME).read_text(encoding="utf-8")
    rows = [json.loads(line) for line in ledger.splitlines()]
    assert len(rows) == 1
    assert rows[0]["markets"][0]["market_id"] == "691340"


def test_capture_is_disabled_outside_trusted_existing_artifact_dir(tmp_path, monkeypatch):
    module = _load_module()
    missing = tmp_path / "missing"
    monkeypatch.setenv("DEERFLOW_RUN_ARTIFACT_DIR", str(missing))
    module._capture_market_candidates(["x"], [{"market_id": "1"}])
    assert not missing.exists()


def test_snapshot_diagnostics_distinguish_provider_failure_from_empty(monkeypatch):
    module = _load_module()
    diagnostics: dict[str, int] = {}
    monkeypatch.setattr(module, "_http_get", lambda *_args, **_kwargs: None)

    assert module.snapshot_for_queries(["outage"], diagnostics=diagnostics) == []
    assert diagnostics == {
        "attempted_query_count": 1,
        "successful_query_count": 0,
        "transport_failure_count": 1,
        "raw_candidate_count": 0,
        "candidate_count": 0,
    }

    empty_diagnostics: dict[str, int] = {}
    monkeypatch.setattr(module, "_http_get", lambda *_args, **_kwargs: {"events": []})
    assert module.snapshot_for_queries(["empty"], diagnostics=empty_diagnostics) == []
    assert empty_diagnostics["successful_query_count"] == 1
    assert empty_diagnostics["transport_failure_count"] == 0

    for malformed in ({"error": "temporarily unavailable"}, ["unexpected"]):
        malformed_diagnostics: dict[str, int] = {}
        monkeypatch.setattr(
            module, "_http_get", lambda *_args, _value=malformed, **_kwargs: _value
        )
        assert module.snapshot_for_queries(
            ["malformed"], diagnostics=malformed_diagnostics
        ) == []
        assert malformed_diagnostics["successful_query_count"] == 0
        assert malformed_diagnostics["transport_failure_count"] == 1


def test_no_queries_has_explicit_not_attempted_status():
    module = _load_module()
    payload = json.loads(module.prediction_market_search_impl("  \n , "))
    assert payload["status"]["attempted"] is False
    assert payload["status"]["state"] == "no_queries"
    assert payload["status"]["empty_reason"] == "no_queries"


def test_duration_knobs_are_always_finite(monkeypatch):
    module = _load_module()
    monkeypatch.setenv("PREDICTION_MARKETS_NEGATIVE_CACHE_TTL_SECONDS", "inf")
    monkeypatch.setenv("PREDICTION_MARKETS_SINGLEFLIGHT_WAIT_SECONDS", "999999")
    assert module._bounded_env_seconds(
        "PREDICTION_MARKETS_NEGATIVE_CACHE_TTL_SECONDS", 30.0, 3600.0
    ) == 30.0
    assert module._bounded_env_seconds(
        "PREDICTION_MARKETS_SINGLEFLIGHT_WAIT_SECONDS", 35.0, 120.0
    ) == 120.0


def test_verified_empty_is_structured_and_negative_cache_expires(monkeypatch):
    module = _load_module()
    calls = 0

    def fake_snapshot(queries, diagnostics, **_kwargs):
        nonlocal calls
        calls += 1
        diagnostics.update({
            "attempted_query_count": len(queries),
            "successful_query_count": len(queries),
            "transport_failure_count": 0,
            "raw_candidate_count": 0,
            "candidate_count": 0,
        })
        return []

    monkeypatch.setattr(module, "snapshot_for_queries", fake_snapshot)
    monkeypatch.setenv("PREDICTION_MARKETS_NEGATIVE_CACHE_TTL_SECONDS", "0.02")
    module._reset_market_query_cache()

    first = json.loads(module.prediction_market_search_impl("no equivalent contract"))
    cached = json.loads(module.prediction_market_search_impl("no equivalent contract"))
    time.sleep(0.03)
    refreshed = json.loads(module.prediction_market_search_impl("no equivalent contract"))

    assert calls == 2
    assert first["status"]["state"] == "verified_empty"
    assert first["status"]["successful_query_count"] == 1
    assert first["status"]["empty_reason"] == "no_equivalent_market"
    assert "No active, liquid markets matched" in first["note"]
    assert cached["cache_hit"] is True
    assert refreshed["cache_hit"] is False


def test_transport_outage_is_structured_and_never_cached(monkeypatch):
    module = _load_module()
    calls = 0

    def failed_snapshot(queries, diagnostics, **_kwargs):
        nonlocal calls
        calls += 1
        diagnostics.update({
            "attempted_query_count": len(queries),
            "successful_query_count": 0,
            "transport_failure_count": len(queries),
            "raw_candidate_count": 0,
            "candidate_count": 0,
        })
        return []

    monkeypatch.setattr(module, "snapshot_for_queries", failed_snapshot)
    module._reset_market_query_cache()

    first = json.loads(module.prediction_market_search_impl("provider outage"))
    retried = json.loads(module.prediction_market_search_impl("provider outage"))

    assert calls == 2
    assert first["cache_hit"] is False
    assert retried["cache_hit"] is False
    assert first["status"]["state"] == "transport_failure"
    assert first["status"]["transport_failure_count"] == 1
    assert "no absence conclusion" in first["note"]
    assert "No active, liquid markets matched" not in first["note"]


def test_partial_transport_result_is_not_cached(tmp_path, monkeypatch):
    module = _load_module()
    calls = 0

    def partial_snapshot(queries, diagnostics, **_kwargs):
        nonlocal calls
        calls += 1
        diagnostics.update({
            "attempted_query_count": len(queries),
            "successful_query_count": 1,
            "transport_failure_count": 1,
            "raw_candidate_count": 1,
            "candidate_count": 1,
        })
        return [{"market_id": "m1", "question": "Relevant?", "volume": 1000}]

    monkeypatch.setattr(module, "snapshot_for_queries", partial_snapshot)
    monkeypatch.setenv("DEERFLOW_RUN_ARTIFACT_DIR", str(tmp_path))
    module._reset_market_query_cache()

    first = json.loads(module.prediction_market_search_impl("one, two"))
    second = json.loads(module.prediction_market_search_impl("one, two"))

    assert calls == 2
    assert first["status"]["state"] == "partial_success"
    assert first["cache_hit"] is False and second["cache_hit"] is False
    records = [json.loads(row) for row in (
        tmp_path / module.MARKET_CANDIDATES_FILENAME
    ).read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    assert records[0]["status"]["transport_failure_count"] == 1


def test_singleflight_waiter_timeout_is_unknown_not_verified_empty(monkeypatch):
    module = _load_module()
    owner_started = threading.Event()
    release_owner = threading.Event()
    owner_payload: list[dict] = []

    def slow_snapshot(queries, diagnostics, **_kwargs):
        owner_started.set()
        assert release_owner.wait(timeout=2)
        diagnostics.update({
            "attempted_query_count": len(queries),
            "successful_query_count": len(queries),
            "transport_failure_count": 0,
            "raw_candidate_count": 0,
            "candidate_count": 0,
        })
        return []

    monkeypatch.setattr(module, "snapshot_for_queries", slow_snapshot)
    monkeypatch.setenv("PREDICTION_MARKETS_SINGLEFLIGHT_WAIT_SECONDS", "0.01")
    module._reset_market_query_cache()

    owner = threading.Thread(target=lambda: owner_payload.append(json.loads(
        module.prediction_market_search_impl("same query")
    )))
    owner.start()
    assert owner_started.wait(timeout=1)
    waiter = json.loads(module.prediction_market_search_impl("same query"))
    release_owner.set()
    owner.join(timeout=2)

    assert not owner.is_alive()
    assert waiter["cache_hit"] is False
    assert waiter["singleflight_shared"] is True
    assert waiter["status"]["state"] == "inflight_timeout"
    assert waiter["status"]["inflight_timeout_count"] == 1
    assert "still in flight" in waiter["note"]
    assert "No active, liquid markets matched" not in waiter["note"]
    assert owner_payload[0]["status"]["state"] == "verified_empty"


# ---------------------- LOOP-017 P1: tool-selected markets carry CLOB/history fields
def _gamma_row(**overrides):
    row = {
        "id": "m-clob", "question": "Will Optimus ship commercially in 2027?",
        "outcomes": '["No","Yes"]', "outcomePrices": '["0.875","0.125"]',
        "clobTokenIds": '["0xNO","0xYES"]',
        "volume": "5000", "liquidity": "800", "closed": False,
        "endDate": "2027-12-31T00:00:00Z", "slug": "optimus-market",
    }
    row.update(overrides)
    return row


def test_normalize_market_persists_clob_and_outcome_fields():
    """研究侧工具选中的市场必须带下游（历史价时间线/重报价）所需字段：
    clob_token_ids（原始位置序，与 outcomes 对齐）、outcomes、outcome_prices、
    clob_yes_token_id（按 "Yes" 下标定位，绝非下标 0）、url、end_date。
    历史事故：工具候选缺这些键 → 只被工具发现的市场（未被确定性刷新重召回）
    永远画不出历史价时间线。"""
    module = _load_module()
    rec = module.normalize_market(_gamma_row(), matched_query="optimus",
                                  event_title="Optimus", event_slug="optimus-2027")
    assert rec is not None
    assert rec["implied_yes_prob"] == 0.125              # 颠倒序仍按 "Yes" 名取价
    assert rec["clob_token_ids"] == ["0xNO", "0xYES"]    # 原始位置序（与 outcomes 对齐）
    assert rec["outcomes"] == ["No", "Yes"]
    assert rec["outcome_prices"] == [0.875, 0.125]
    assert rec["clob_yes_token_id"] == "0xYES"           # Yes 腿按名定位
    assert rec["url"] == "https://polymarket.com/event/optimus-2027"
    assert rec["end_date"] == "2027-12-31T00:00:00Z"


def test_normalize_market_degrades_when_gamma_omits_clob_fields():
    """Gamma 行缺 clobTokenIds/outcomes → 键不出现（缺失不造假），行仍有效。"""
    module = _load_module()
    row = _gamma_row()
    del row["clobTokenIds"]
    rec = module.normalize_market(row, matched_query="q")
    assert rec is not None and "clob_token_ids" not in rec
    assert "clob_yes_token_id" not in rec
    assert rec["outcomes"] == ["No", "Yes"]              # outcomes 仍在（价即由它定位）
    # outcomes 解析不出时（非法 JSON）连价都定位不了 → 整行不合格（既有行为）。
    bad = _gamma_row(outcomes="not-json")
    assert module.normalize_market(bad, matched_query="q") is None


def test_normalize_market_yes_index_outside_tokens_never_fabricates():
    """Yes 下标超出 clobTokenIds 范围 → 不造假（clob_yes_token_id 键不出现）。"""
    module = _load_module()
    rec = module.normalize_market(_gamma_row(clobTokenIds='["0xONLY"]'),
                                  matched_query="q")
    assert rec is not None
    assert rec["clob_token_ids"] == ["0xONLY"]
    assert "clob_yes_token_id" not in rec


def test_captured_tool_candidates_keep_clob_fields(tmp_path, monkeypatch):
    """工具结果落进 prediction_market_candidates.jsonl 时 CLOB/结局字段原样保留
    （registry 合并按整行 dict 透传，字段在此处丢了就永远丢了）。"""
    module = _load_module()

    def fake_fetch(query, limit):
        return [{"title": "Optimus", "slug": "optimus-2027",
                 "markets": [_gamma_row()]}]

    monkeypatch.setattr(module, "snapshot_for_queries",
                        lambda queries, **kw: [
                            module.normalize_market(_gamma_row(), matched_query=q,
                                                    event_slug="optimus-2027")
                            for q in queries])
    monkeypatch.setenv("DEERFLOW_RUN_ARTIFACT_DIR", str(tmp_path))
    module._reset_market_query_cache()
    payload = json.loads(module.prediction_market_search_impl("optimus 2027"))
    assert payload["markets"][0]["clob_yes_token_id"] == "0xYES"
    ledger = (tmp_path / module.MARKET_CANDIDATES_FILENAME).read_text(encoding="utf-8")
    row = json.loads(ledger.splitlines()[0])["markets"][0]
    assert row["clob_token_ids"] == ["0xNO", "0xYES"]
    assert row["clob_yes_token_id"] == "0xYES"
    assert row["outcomes"] == ["No", "Yes"]
    assert row["outcome_prices"] == [0.875, 0.125]


class _Resp:
    def __init__(self, status_code: int, headers: dict | None = None, payload=None) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _scripted_http(monkeypatch, module, responses):
    """Scripted requests.get plus a recorder of this thread's time.sleep calls."""
    import requests

    gets: list[str] = []
    sleeps: list[float] = []
    main = threading.current_thread()
    real_sleep = time.sleep

    def fake_get(url, params=None, timeout=None, headers=None):
        gets.append(url)
        return responses.pop(0)

    def fake_sleep(seconds):
        if threading.current_thread() is main:
            sleeps.append(seconds)
        else:
            real_sleep(seconds)

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(module.time, "sleep", fake_sleep)
    return gets, sleeps


@pytest.mark.parametrize("headers, expected", [
    ({"Retry-After": "3"}, 3.0),
    ({"Retry-After": "999"}, 10.0),
    ({"Retry-After": "0"}, 0.0),
    ({"Retry-After": "-4"}, 0.0),
])
def test_transient_status_waits_retry_after_clamped_then_retries_once(monkeypatch, headers, expected):
    module = _load_module()
    gets, sleeps = _scripted_http(monkeypatch, module, [_Resp(429, headers), _Resp(200, payload={"ok": 1})])
    assert module._http_get("/public-search", {"q": "x"}) == {"ok": 1}
    assert sleeps == [expected] and len(gets) == 2


@pytest.mark.parametrize("headers", [{}, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"},
                                     {"Retry-After": "nan"}, {"Retry-After": "inf"}])
def test_transient_status_without_a_numeric_retry_after_waits_jitter(monkeypatch, headers):
    module = _load_module()
    gets, sleeps = _scripted_http(monkeypatch, module, [_Resp(503, headers), _Resp(503, headers)])
    assert module._http_get("/public-search", {"q": "x"}) is None   # exactly one retry, then degrade
    assert len(gets) == 2 and len(sleeps) == 1
    assert 0.5 <= sleeps[0] <= 1.5


def test_non_transient_status_is_not_retried_or_delayed(monkeypatch):
    module = _load_module()
    gets, sleeps = _scripted_http(monkeypatch, module, [_Resp(404, {"Retry-After": "3"})])
    assert module._http_get("/public-search", {"q": "x"}) is None
    assert len(gets) == 1 and sleeps == []


def test_timed_out_request_is_never_a_verified_empty_search(monkeypatch):
    """FU-6: a query whose request timed out never finished, so the agent is never
    told 'no equivalent market'.  requests.Timeout is retried once and then counts
    as a transport failure; a completed empty search stays verified_empty."""
    import requests

    module = _load_module()
    sent: list[str] = []
    main = threading.current_thread()
    real_sleep = time.sleep

    def fake_get(url, params=None, timeout=None, headers=None):
        query = str((params or {}).get("q") or "")
        sent.append(query)
        if query.startswith("slow"):
            raise requests.Timeout(f"read timed out: {query}")
        return _Resp(200, payload={"events": []})

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(module.time, "sleep",
                        lambda s: None if threading.current_thread() is main else real_sleep(s))
    module._reset_market_query_cache()

    timed_out = json.loads(module.prediction_market_search_impl("slow a"))
    assert sent == ["slow a", "slow a"]                  # one retry, then degrade
    assert timed_out["status"]["state"] == "transport_failure"
    assert timed_out["status"]["empty_reason"] == "transport_failure"
    assert timed_out["status"]["successful_query_count"] == 0
    assert timed_out["status"]["transport_failure_count"] == 1
    assert "no absence conclusion" in timed_out["note"]
    assert "No active, liquid markets matched" not in timed_out["note"]

    partial = json.loads(module.prediction_market_search_impl("slow a, empty b"))
    assert partial["status"]["state"] == "partial_transport_failure"
    assert partial["status"]["empty_reason"] == "partial_transport_failure"
    assert "incomplete" in partial["note"]
    assert "No active, liquid markets matched" not in partial["note"]

    completed = json.loads(module.prediction_market_search_impl("empty c"))
    assert completed["status"]["state"] == "verified_empty"
    assert completed["status"]["empty_reason"] == "no_equivalent_market"
    assert "No active, liquid markets matched" in completed["note"]
